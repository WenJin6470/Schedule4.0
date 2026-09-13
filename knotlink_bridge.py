"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— knotlink_bridge.py（KnotLink 协议桥接）        ║
║               （将 Schedule 4.0 接入 KnotLink 节点网络）                 ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
  本文件是 Schedule 4.0 与 KnotLink 协议之间的桥接层，负责：
    ✅ 接收其他节点发来的请求（3 个 openSocket 接口）
    ✅ 向外广播课表事件（2 个 signal 信号：onClassStart / onClassEnd）
    ✅ 自注册为 KnotLink 独立式节点（释放内嵌清单 + 写注册表，见文件末尾）
    ✅ 完全解耦：knotlink SDK 未安装时静默降级，不影响课表正常运行

📌 连接健壮性
═══════════════════════════════════════════════════════════════════════════
  KnotLink 的中继服务是 Windows 服务 KnotLinkService。它未运行时，
  SDK 直连会报 WinError 10061（连接被拒绝）。因此本文件：
    - 先用带超时的探测确认服务在监听，再创建 SDK 对象（不刷 ERROR 日志）
    - 连接过程放在后台线程并每 30s 重试，服务启动后自动接上
    - 服务不在时静默降级，课表本体功能完全不受影响

📌 使用方式
═══════════════════════════════════════════════════════════════════════════
  在 main.py 中所有组件创建完毕后调用：
      from knotlink_bridge import KnotLinkBridge
      KnotLinkBridge.setup(
          time_manager=time_manager,
          schedule_data=schedule_data,
          main_window=main_window,
          debug_config=debug_config,
      )
  退出时（事件循环结束后）调用：
      KnotLinkBridge.teardown()
"""

import atexit
import importlib
import json
import logging
import os
import shutil
import socket
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app_paths import app_root, is_frozen

logger: logging.Logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
#  尝试导入 KnotLink SDK（可选依赖）
# ═══════════════════════════════════════════════════════════════════════════
try:
    from knotlink import OpenSocketResponser, SignalSender, KLKVMap  # type: ignore
    _HAS_KNOTLINK: bool = True
    logger.info("KnotLink SDK 已加载，桥接功能可用")
except ImportError:
    _HAS_KNOTLINK = False
    logger.warning("KnotLink SDK 未安装，桥接功能不可用（课表系统正常运行）")

    # 占位类型，避免类型注解报错
    class KLKVMap(dict):  # type: ignore
        """占位 KLKVMap —— KnotLink SDK 未安装时的降级实现。"""
        def serialize(self) -> str:
            return ";".join(f"{k}={v}" for k, v in self.items())
        def deserialize(self, data: str) -> None:
            for part in data.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    self[k] = v

    class OpenSocketResponser:  # type: ignore
        """占位 OpenSocketResponser —— 不执行任何网络操作。"""
        def __init__(self, app_id: str, socket_id: str) -> None:
            pass
        def set_RecvFunc(self, func) -> None:
            pass

    class SignalSender:  # type: ignore
        """占位 SignalSender —— 不执行任何网络操作。"""
        def __init__(self, app_id: str, signal_id: str) -> None:
            pass
        def emitt(self, data: str) -> None:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════════════════
APPID: str = "com.github.wenjin6470.schedule4"
SOCKET_ID: str = "schedule"
SIGNAL_ID: str = "events"

# 合法的星期名称集合
_VALID_WEEKDAYS: set = {
    'Monday', 'Tuesday', 'Wednesday', 'Thursday',
    'Friday', 'Saturday', 'Sunday',
}


# ═══════════════════════════════════════════════════════════════════════════
#  连接层加固（服务探测 + 连接超时 + 后台重连）
# ═══════════════════════════════════════════════════════════════════════════
#
#  📌 背景
#  ═══════════════════════════════════════════════════════════════════════════
#  KnotLink 的四个角色（6370 发送者 / 6372 订阅者 / 6376 询问者 /
#  6378 回复者）都是「连出去」的客户端，本机必须有一个中继服务在监听
#  这些端口 —— 即 KnotLinkService（Windows 服务）。服务未运行时，
#  SDK 的 connect 会抛 WinError 10061（连接被拒绝）。
#
#  SDK 原生行为有三个问题：
#    1. connect 是阻塞调用且未设超时，在主线程执行会卡住界面
#    2. 连接失败只尝试一次，之后永不重连（先开课表、后开服务就永远是死的）
#    3. 每次失败都直接 logger.error，服务长期不在时会持续刷错误日志
#
#  对策：先用带超时的探测判断服务是否在监听，只有确认可用才创建 SDK
#  对象；整套连接过程放在后台线程并周期性重试。

# SDK 内写死的两个端口（见 SDK 的 OpenSocketResponser / SignalSender）
_RESPONSER_PORT: int = 6378
_SENDER_PORT: int = 6370

# 服务探测超时（秒）。loopback 上正常应为亚毫秒级，0.5s 足够宽松。
_CONNECT_TIMEOUT: float = 0.5

# KnotLinkService 不可用时的重试间隔（秒）
_RECONNECT_INTERVAL: float = 30.0


def _probe_port(port: int, timeout: float = _CONNECT_TIMEOUT) -> bool:
    """
    探测本机端口是否有进程在监听。
    ------------------------------
    用一次带超时的连接做快速判断。先探测、再创建 SDK 对象，
    可以避免服务不在时由 SDK 刷出 ERROR 级日志。

    参数：
        port    （int）：  目标端口
        timeout （float）：探测超时（秒）

    返回值：
        bool：True 表示端口可连接（服务在监听）
    """
    try:
        with socket.create_connection(('127.0.0.1', port), timeout):
            return True
    except OSError:
        return False


def _install_connect_timeout(timeout: float = _CONNECT_TIMEOUT) -> bool:
    """
    为 KnotLink SDK 的 TcpClient 安装连接超时。
    ------------------------------------------
    SDK 内部 `TcpClient.connect_to_server()` 使用阻塞 socket 且未设超时：
    回环连接被拒绝时通常立刻返回，但若被安全软件过滤/丢弃，connect 可能
    阻塞到系统默认值（约 20 秒）。

    做法：不修改 site-packages，而是用子类替换 SDK 模块内的 TcpClient
    名字 —— `OpenSocketResponser.py` / `SignalSender.py` 都是
    `from .tcpclient import TcpClient`，运行时按模块全局名解析，
    因此重绑定模块属性即可生效（子类关系不变，isinstance 仍成立）。

    ★ 超时只能覆盖「连接瞬间」。连接成功后 SDK 会立刻启动接收线程做
      阻塞 recv，若此时超时仍然生效，第一次 recv 就会抛
      socket.timeout，SDK 会打出 "Failed to receive data: timed out"
      并误判连接断开（实测会导致 0.3s 一次的连接抖动）。
      由于接收线程是在 connect 内部启动的，无法在 connect 返回后再恢复，
      因此改为**在 receive_data / send_data 的最开头**恢复阻塞模式 ——
      这两个入口必然先于任何真正的收发动作执行，不存在竞态窗口。

    参数：
        timeout（float）：连接阶段超时（秒）

    返回值：
        bool：True 表示安装成功；False 表示退回 SDK 原生行为
              （SDK 结构变化时不影响功能，只是失去超时保护）
    """
    if not _HAS_KNOTLINK:
        return False
    try:
        tcp_mod = importlib.import_module('knotlink.tcpclient')
        resp_mod = importlib.import_module('knotlink.OpenSocketResponser')
        send_mod = importlib.import_module('knotlink.SignalSender')

        base_client = tcp_mod.TcpClient
        if getattr(base_client, '_schedule4_timeout_installed', False):
            return True

        class _TimeoutTcpClient(base_client):  # type: ignore[misc, valid-type]
            """仅连接阶段带超时的 TcpClient，正式收发阶段保持阻塞模式。"""

            def _restore_blocking(self) -> None:
                """恢复阻塞模式（失败忽略：socket 可能已关闭）。"""
                try:
                    self.tcp_socket.settimeout(None)
                except OSError:
                    pass

            def connect_to_server(self, ip: str, port: int) -> None:
                try:
                    self.tcp_socket.settimeout(timeout)
                except OSError:
                    pass
                # 不在此处恢复：接收线程由 connect 内部启动，
                # 这里的 finally 与它存在竞态窗口
                super().connect_to_server(ip, port)

            def receive_data(self) -> None:
                # ★ 必须在任何 recv 之前恢复阻塞模式
                self._restore_blocking()
                super().receive_data()

            def send_data(self, data: bytes) -> None:
                # 注册键在 connect 后立即发送，同样要确保非超时模式
                self._restore_blocking()
                super().send_data(data)

        _TimeoutTcpClient._schedule4_timeout_installed = True  # type: ignore[attr-defined]
        resp_mod.TcpClient = _TimeoutTcpClient # type: ignore
        send_mod.TcpClient = _TimeoutTcpClient # pyright: ignore[reportAttributeAccessIssue]
        logger.debug(f"已为 KnotLink TcpClient 安装连接超时：{timeout}s")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"安装 KnotLink 连接超时失败（退回 SDK 默认行为）：{e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  KnotLinkBridge — 桥接主类
# ═══════════════════════════════════════════════════════════════════════════

class KnotLinkBridge:
    """
    # KnotLinkBridge — KnotLink 协议桥接主类

    统一管理请求响应和信号广播，将 KnotLink 协议消息
    转换为对业务模块的方法调用。

    所有方法均为静态方法或类方法，全局只有一个桥接实例。
    ---

    使用方式：
        KnotLinkBridge.setup(time_manager=..., schedule_data=..., ...)
    """

    # ---- 组件引用（由 setup() 注入） ----
    _time_manager: Optional[Any] = None
    _schedule_data: Optional[Any] = None
    _main_window: Optional[Any] = None
    _debug_config: Optional[Any] = None

    # ---- KnotLink SDK 实例 ----
    _responser: Optional[OpenSocketResponser] = None
    _sender: Optional[SignalSender] = None

    # ---- 信号状态跟踪（用于检测上课/下课/放学切换） ----
    _prev_state: str = "unknown"       # "in_class" | "break" | "after_school" | "unknown"
    _initialized: bool = False

    # ---- 后台连接线程（服务不在时周期性重试） ----
    _connector_thread: Optional[threading.Thread] = None
    _stop_event: Optional[threading.Event] = None

    # ══════════════════════════════════════════════════════════════════
    #  公开方法：初始化桥接
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def setup(cls, *,
              time_manager: Any,
              schedule_data: Any,
              main_window: Any,
              debug_config: Any = None) -> None:
        """
        初始化 KnotLink 桥接，注入所有需要的组件引用。
        -------------------------------------------
        必须在所有前端窗口和后端实例创建完毕后调用。
        此方法会：
          1. 保存组件引用
          2. 订阅 TimeManager.time_tick 以检测上课/下课/放学事件
          3. 自注册为 KnotLink 独立式节点（释放清单 + 写注册表）
          4. 启动后台线程建立 KnotLink 网络连接（不阻塞主线程）

        ★ 网络连接为什么放后台线程：
          SDK 的 connect 是阻塞调用。KnotLinkService 未运行时，本机回环
          连接被拒绝实测耗时约 2s（受安全软件网络过滤影响，正常应为
          亚毫秒级），若在主线程执行，界面启动时会卡住约 4 秒。
          后台线程还会周期性重试，服务启动后自动接上。
        """
        if cls._initialized:
            logger.warning("KnotLinkBridge 已经初始化过，跳过重复设置")
            return

        cls._time_manager = time_manager
        cls._schedule_data = schedule_data
        cls._main_window = main_window
        cls._debug_config = debug_config

        if not _HAS_KNOTLINK:
            logger.info("KnotLink SDK 不可用，跳过网络层初始化")
            cls._initialized = True
            return

        # 订阅 TimeManager.time_tick（纯 Qt 信号连接，不涉及网络，开销可忽略）
        time_manager.time_tick.connect(cls._on_time_tick)
        logger.info("已订阅 TimeManager.time_tick，开始监测上课/下课/放学事件")

        # 自注册为 KnotLink 独立式节点。
        # 放在 SDK 可用性检查之后：清单声明了本节点提供的接口，
        # 若 SDK 缺失则请求无法响应，注册出去只会让 Hub 看到一个死节点。
        # 该步骤只写文件与注册表，与 TCP 连接是否成功无关。
        register_self()

        # 给 SDK 的 TcpClient 装上连接超时，避免异常网络下长时间阻塞
        _install_connect_timeout()

        # 后台连接线程（daemon：不阻止进程退出；teardown() 会显式收尾）
        stop_event: threading.Event = threading.Event()
        cls._stop_event = stop_event
        cls._connector_thread = threading.Thread(
            target=cls._connect_worker,
            args=(stop_event,),
            name='KnotLinkConnector',
            daemon=True,
        )
        cls._connector_thread.start()

        cls._initialized = True
        logger.info("KnotLinkBridge 初始化完成（网络连接在后台建立）")

    @classmethod
    def teardown(cls) -> None:
        """
        停止桥接：结束后台连接线程并断开 SDK 连接。
        ------------------------------------------
        由 main.py 在事件循环退出后调用；可重复调用（幂等）。
        """
        stop_event: Optional[threading.Event] = cls._stop_event
        if stop_event is not None:
            stop_event.set()

        thread: Optional[threading.Thread] = cls._connector_thread
        if thread is not None and thread.is_alive():
            # 连接线程最多阻塞在带超时的 connect 上，1.5s 足够收尾
            thread.join(timeout=1.5)
        cls._connector_thread = None
        cls._stop_event = None

        cls._discard_connections("程序退出")
        cls._initialized = False
        logger.info("KnotLinkBridge 已停止")

    # ══════════════════════════════════════════════════════════════════
    #  后台连接线程：建立 / 重建 SDK 连接
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _connect_worker(cls, stop_event: threading.Event) -> None:
        """
        后台连接线程主体。
        ------------------
        周期性检查连接状态：
          - 未连接（服务未启动 / 启动时服务不在）→ 探测并尝试连接
          - 已连接但连接失效（如服务被重启）      → 丢弃旧对象后重连

        服务不在时只在**首次**打一条 INFO 说明已静默降级，之后静默重试，
        不再刷日志（避免把 SDK 的 ERROR 刷屏换成我们自己的 INFO 刷屏）。
        """
        logger.info(
            f"KnotLink 连接线程已启动（服务不可用时每 "
            f"{_RECONNECT_INTERVAL:.0f}s 重试一次）"
        )
        degraded_logged: bool = False

        while not stop_event.is_set():
            if cls._responser is not None and cls._connection_alive():
                # 连接正常：等待下一轮检查
                degraded_logged = False
                stop_event.wait(_RECONNECT_INTERVAL)
                continue

            if cls._responser is not None:
                # 连接存在但已失效（服务重启过）→ 丢弃后重连
                cls._discard_connections("连接已失效（KnotLinkService 可能被重启）")

            if cls._try_connect():
                degraded_logged = False
            elif not degraded_logged:
                logger.info(
                    f"KnotLinkService 未运行，KnotLink 功能已静默降级"
                    f"（每 {_RECONNECT_INTERVAL:.0f}s 重试，服务启动后自动接上）"
                )
                degraded_logged = True

            stop_event.wait(_RECONNECT_INTERVAL)

        logger.info("KnotLink 连接线程已退出")

    @classmethod
    def _try_connect(cls) -> bool:
        """
        尝试建立 SDK 连接（仅在后台线程中调用）。
        ----------------------------------------
        先用带超时的探测确认 KnotLinkService 在监听，再创建 SDK 对象：
        服务不在时直接跳过，既避免 SDK 刷 ERROR 日志，也避免无谓等待。

        返回值：
            bool：True 表示连接已建立
        """
        if not (_probe_port(_RESPONSER_PORT) and _probe_port(_SENDER_PORT)):
            return False

        responser: Any = None
        try:
            responser = OpenSocketResponser(APPID, SOCKET_ID)
            responser.set_RecvFunc(cls._handle_request)
            sender = SignalSender(APPID, SIGNAL_ID)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"建立 KnotLink 连接失败，稍后重试：{e}")
            if responser is not None:
                try:
                    responser.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            return False

        # 两个对象都创建成功后再一次性赋值，避免 _on_time_tick 读到半成品
        cls._responser = responser
        cls._sender = sender
        logger.info(
            f"KnotLink 已连接：appID={APPID}, "
            f"socketID={SOCKET_ID}, signalID={SIGNAL_ID}"
        )
        return True

    @classmethod
    def _connection_alive(cls) -> bool:
        """
        判断当前 SDK 连接是否仍然有效。
        ------------------------------
        读取 SDK 内部的连接标志（best-effort）：取不到标志时保守认为
        连接仍然有效，避免因 SDK 结构变化而反复重连。
        """
        for obj, attr in ((cls._responser, 'KLresponser'),
                          (cls._sender, 'KLsender')):
            if obj is None:
                continue
            client: Any = getattr(obj, attr, None)
            connected: Any = getattr(client, 'connected', None)
            if connected is False:
                return False
        return True

    @classmethod
    def _discard_connections(cls, reason: str) -> None:
        """断开并清空当前 SDK 连接对象（失败只记日志）。"""
        if cls._responser is None and cls._sender is None:
            return
        logger.info(f"释放 KnotLink 连接：{reason}")
        for obj in (cls._responser, cls._sender):
            if obj is None:
                continue
            try:
                obj.disconnect() # type: ignore
            except Exception as e:  # noqa: BLE001
                logger.warning(f"断开 KnotLink 连接失败（忽略）：{e}")
        cls._responser = None
        cls._sender = None

    # ══════════════════════════════════════════════════════════════════
    #  请求处理：入口
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_request(cls, data: str) -> str:
        """
        处理来自 KnotLink 网络的请求（由 OpenSocketResponser 回调）。
        ---------------------------------------------------------
        参数：
            data（str）：KLKVMap 序列化后的键值对字符串

        返回值：
            str：KLKVMap 序列化后的响应字符串
        """
        req: KLKVMap = KLKVMap()
        req.deserialize(data)
        action: str = req.get("action", "")

        logger.info(f"[KnotLink] 收到请求：action={action}, raw={data}")

        # 根据 action 分发到对应的处理方法
        if action == "get-lesson-state":
            return cls._handle_get_lesson_state()
        elif action == "get-today-schedule":
            return cls._handle_get_today_schedule(req)
        elif action == "swap-course":
            return cls._handle_swap_course(req)
        else:
            logger.warning(f"[KnotLink] 未知 action：{action}")
            resp: KLKVMap = KLKVMap()
            resp["status"] = "err"
            resp["message"] = f"未知的 action：{action}"
            return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  请求处理：get-lesson-state
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_get_lesson_state(cls) -> str:
        """
        查询当前实时上课状态。
        -------------------
        根据当前时间和时间表数据，判断是否在上课/课间/放学。
        """
        resp: KLKVMap = KLKVMap()

        current_time_str: str = cls._get_current_time_str()
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}

        if not timetable:
            resp["status"] = "err"
            resp["message"] = "时间表数据为空"
            return resp.serialize()

        # 解析课时列表
        lessons: List[Tuple[str, str, str]] = []
        for key in timetable:
            if not key.startswith('lesson_'):
                continue
            times = timetable[key]
            if not (isinstance(times, list) and len(times) == 2):
                continue
            lessons.append((key, times[0], times[1]))

        if not lessons:
            resp["status"] = "err"
            resp["message"] = "时间表中无课时数据"
            return resp.serialize()

        try:
            current_t = datetime.strptime(current_time_str, "%H:%M:%S").time()
        except (ValueError, TypeError):
            resp["status"] = "err"
            resp["message"] = f"时间格式异常：{current_time_str}"
            return resp.serialize()

        # 查找当前所在课时
        current_lesson: Optional[Tuple[str, str, str]] = None
        next_lesson: Optional[Tuple[str, str, str]] = None

        for key, start_str, end_str in lessons:
            try:
                start_t = datetime.strptime(start_str, "%H:%M:%S").time()
                end_t = datetime.strptime(end_str, "%H:%M:%S").time()
            except (ValueError, TypeError):
                continue

            if start_t <= current_t < end_t:
                current_lesson = (key, start_str, end_str)
            elif current_t < start_t and next_lesson is None:
                next_lesson = (key, start_str, end_str)

        # 获取当天课表（用于填充科目名称）
        day_name: str = cls._get_current_day_name()
        curriculum: Dict[str, str] = cls._schedule_data.get_curriculum_for_day(day_name) if cls._schedule_data else {}

        resp["status"] = "ok"

        if current_lesson is not None:
            key, start_str, end_str = current_lesson
            period_num: int = int(key.split('_')[1]) if '_' in key else 0

            # 计算剩余时间
            try:
                end_dt = datetime.strptime(end_str, "%H:%M:%S")
                cur_dt = datetime.strptime(current_time_str, "%H:%M:%S")
                remaining_sec = int((end_dt - cur_dt).total_seconds())
                if remaining_sec < 0:
                    remaining_sec = 0
                remaining_str = f"{remaining_sec // 3600:02d}:{(remaining_sec % 3600) // 60:02d}:{remaining_sec % 60:02d}"
            except (ValueError, TypeError):
                remaining_str = "00:00:00"

            resp["isInClass"] = "true"
            resp["isBreak"] = "false"
            resp["currentPeriod"] = str(period_num)
            resp["currentSubject"] = curriculum.get(key, "")
            resp["currentStartTime"] = start_str
            resp["currentEndTime"] = end_str
            resp["remainingTime"] = remaining_str
        else:
            resp["isInClass"] = "false"
            resp["currentPeriod"] = "-1"
            resp["currentSubject"] = ""
            resp["currentStartTime"] = ""
            resp["currentEndTime"] = ""
            resp["remainingTime"] = "00:00:00"

            # 判断是课间还是放学
            if next_lesson is not None:
                resp["isBreak"] = "true"
            else:
                resp["isBreak"] = "false"

        # 下一节课信息
        if next_lesson is not None:
            n_key, n_start, n_end = next_lesson
            n_period: int = int(n_key.split('_')[1]) if '_' in n_key else 0
            resp["nextPeriod"] = str(n_period)
            resp["nextSubject"] = curriculum.get(n_key, "")
            resp["nextStartTime"] = n_start
        else:
            resp["nextPeriod"] = "-1"
            resp["nextSubject"] = ""
            resp["nextStartTime"] = ""

        logger.info(
            f"[KnotLink] get-lesson-state 响应：isInClass={resp.get('isInClass')}, "
            f"period={resp.get('currentPeriod')}, subject={resp.get('currentSubject')}"
        )
        return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  请求处理：get-today-schedule
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_get_today_schedule(cls, req: KLKVMap) -> str:
        """
        获取当天（或指定星期）完整课表。
        """
        resp: KLKVMap = KLKVMap()

        day_name: str = req.get("day", "").strip()
        if not day_name:
            day_name = cls._get_current_day_name()

        if day_name not in _VALID_WEEKDAYS:
            resp["status"] = "err"
            resp["message"] = f"无效的星期名称：'{day_name}'，合法值：Monday~Sunday"
            return resp.serialize()

        curriculum: Dict[str, str] = cls._schedule_data.get_curriculum_for_day(day_name) if cls._schedule_data else {}
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}

        # 构建 lessons 数组
        lessons_list: List[Dict[str, Any]] = []
        period_idx: int = 0

        for key in timetable:
            if not key.startswith('lesson_'):
                continue
            period_idx += 1
            times = timetable.get(key, ["", ""])
            lessons_list.append({
                "period": period_idx,
                "key": key,
                "subject": curriculum.get(key, ""),
                "startTime": times[0] if isinstance(times, list) and len(times) >= 2 else "",
                "endTime": times[1] if isinstance(times, list) and len(times) >= 2 else "",
            })

        # 分隔线位置
        divider_indices: List[int] = cls._schedule_data.get_divider_indices() if cls._schedule_data else []

        import json
        resp["status"] = "ok"
        resp["day"] = day_name
        resp["lessons"] = json.dumps(lessons_list, ensure_ascii=False)
        resp["dividerIndices"] = json.dumps(divider_indices)
        resp["totalPeriods"] = str(period_idx)

        logger.info(
            f"[KnotLink] get-today-schedule 响应：day={day_name}, "
            f"totalPeriods={period_idx}"
        )
        return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  请求处理：swap-course
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_swap_course(cls, req: KLKVMap) -> str:
        """
        处理临时换课请求。
        ----------------
        验证参数后通过 SwapManager 写入换课记录文件。
        如果当前正在显示被修改的星期且换课日期是今天，立即刷新主窗口显示。
        """
        from schedule_config import SwapManager

        resp: KLKVMap = KLKVMap()

        day_name: str = req.get("day_name", "").strip()
        lesson_key: str = req.get("lesson_key", "").strip()
        old_subject: str = req.get("old_subject", "")
        new_subject: str = req.get("new_subject", "")
        swap_date: str = req.get("swap_date", "").strip()

        # ---- 参数校验 ----
        if day_name not in _VALID_WEEKDAYS:
            resp["status"] = "err"
            resp["message"] = f"无效的星期名称：'{day_name}'，合法值：Monday~Sunday"
            return resp.serialize()

        if not lesson_key.startswith('lesson_'):
            resp["status"] = "err"
            resp["message"] = f"无效的课时键名：'{lesson_key}'，格式应为 lesson_N（如 lesson_2）"
            return resp.serialize()

        # 校验 lesson_key 是否存在于当前时间表中
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}
        if lesson_key not in timetable:
            resp["status"] = "err"
            resp["message"] = f"课时键名 '{lesson_key}' 在当前时间表中不存在"
            return resp.serialize()

        # 如果未指定日期，自动计算该星期的下一个匹配日期
        if not swap_date:
            swap_date = cls._calc_next_date_for_weekday(day_name)

        # 校验日期格式
        try:
            datetime.strptime(swap_date, "%Y-%m-%d")
        except ValueError:
            resp["status"] = "err"
            resp["message"] = f"无效的日期格式：'{swap_date}'，格式应为 YYYY-MM-DD"
            return resp.serialize()

        # ---- 写入换课记录 ----
        swap_manager: SwapManager = SwapManager()
        swaps: List[Dict] = [{
            "day_name": day_name,
            "lesson_key": lesson_key,
            "old_subject": old_subject,
            "new_subject": new_subject,
            "swap_date": swap_date,
        }]

        success: bool = swap_manager.add_swaps(swaps)
        if not success:
            resp["status"] = "err"
            resp["message"] = "换课记录写入文件失败"
            return resp.serialize()

        logger.info(
            f"[KnotLink] swap-course 成功：{day_name} {lesson_key} "
            f"'{old_subject}' → '{new_subject}'，日期={swap_date}"
        )

        # 如果换课日期是今天，且主窗口当前显示的星期匹配，立即刷新
        today_str: str = SwapManager._get_effective_today(cls._debug_config)
        if swap_date == today_str and cls._main_window is not None:
            current_display_day: str = cls._main_window.get_display_week()
            if current_display_day == day_name:
                # 直接修改内存中的课表数据并刷新标签
                if cls._schedule_data is not None:
                    if day_name in cls._schedule_data.curriculum_data:
                        cls._schedule_data.curriculum_data[day_name][lesson_key] = new_subject
                cls._main_window.set_display_week(day_name)
                logger.info(f"[KnotLink] 换课已立即应用到当前显示：{day_name}")

        resp["status"] = "ok"
        resp["swap_date"] = swap_date
        return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  信号广播：时间滴答回调
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _on_time_tick(cls, time_str: str) -> None:
        """
        TimeManager.time_tick 回调（每秒一次）。
        ---------------------------------------
        检测上课/下课状态切换，并在切换时广播对应信号。

        状态切换规则：
          - 从"非上课"进入某节课 → 发射 onClassStart
          - 从"上课中"进入课间   → 发射 onClassEnd
        """
        if cls._sender is None:
            return

        current_state, current_key = cls._detect_period_state(time_str)

        # 状态切换检测
        if current_state != cls._prev_state:
            logger.info(
                f"[KnotLink] 状态切换：{cls._prev_state} → {current_state} "
                f"(period_key={current_key})"
            )

            if current_state == "in_class":
                cls._emit_on_class_start(current_key, time_str)
            elif current_state == "break" and cls._prev_state == "in_class":
                cls._emit_on_class_end(current_key, time_str)

        cls._prev_state = current_state

    @classmethod
    def _detect_period_state(cls, time_str: str) -> Tuple[str, str]:
        """
        检测当前时间所在的状态。
        -----------------------
        返回值：
            Tuple[str, str]：(state, lesson_key)
            state 取值："in_class" | "break" | "after_school"
            lesson_key：当前课时键名（非上课状态时为空字符串）
        """
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}
        if not timetable:
            return ("after_school", "")

        try:
            current_t = datetime.strptime(time_str, "%H:%M:%S").time()
        except (ValueError, TypeError):
            return ("after_school", "")

        lessons: List[Tuple[str, str, str]] = []
        for key in timetable:
            if not key.startswith('lesson_'):
                continue
            times = timetable[key]
            if not (isinstance(times, list) and len(times) == 2):
                continue
            lessons.append((key, times[0], times[1]))

        has_next: bool = False
        for key, start_str, end_str in lessons:
            try:
                start_t = datetime.strptime(start_str, "%H:%M:%S").time()
                end_t = datetime.strptime(end_str, "%H:%M:%S").time()
            except (ValueError, TypeError):
                continue

            if start_t <= current_t < end_t:
                return ("in_class", key)
            if current_t < start_t:
                has_next = True

        if has_next:
            return ("break", "")
        else:
            return ("after_school", "")

    @classmethod
    def _emit_on_class_start(cls, lesson_key: str, time_str: str) -> None:
        """发射 onClassStart 信号。"""
        if cls._sender is None:
            return

        # 获取科目名称
        day_name: str = cls._get_current_day_name()
        curriculum: Dict[str, str] = cls._schedule_data.get_curriculum_for_day(day_name) if cls._schedule_data else {}
        subject: str = curriculum.get(lesson_key, "")

        # 获取课时起止时间
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}
        times = timetable.get(lesson_key, ["", ""])
        start_time: str = times[0] if isinstance(times, list) and len(times) >= 2 else ""
        end_time: str = times[1] if isinstance(times, list) and len(times) >= 2 else ""

        period_num: int = int(lesson_key.split('_')[1]) if '_' in lesson_key else 0

        kv: KLKVMap = KLKVMap()
        kv["event"] = "onClassStart"
        kv["period"] = str(period_num)
        kv["subject"] = subject
        kv["startTime"] = start_time
        kv["endTime"] = end_time

        cls._sender.emitt(kv.serialize())
        logger.info(
            f"[KnotLink] 信号发射：onClassStart period={period_num} subject='{subject}'"
        )

    @classmethod
    def _emit_on_class_end(cls, next_lesson_key: str, time_str: str) -> None:
        """发射 onClassEnd 信号。"""
        if cls._sender is None:
            return

        # 查找下一节课
        timetable: Dict = cls._schedule_data.timetable_data if cls._schedule_data else {}
        day_name: str = cls._get_current_day_name()
        curriculum: Dict[str, str] = cls._schedule_data.get_curriculum_for_day(day_name) if cls._schedule_data else {}

        try:
            current_t = datetime.strptime(time_str, "%H:%M:%S").time()
        except (ValueError, TypeError):
            return

        next_key: str = ""
        next_subject: str = ""
        next_start: str = ""
        next_period: int = -1
        left_time_str: str = "00:00:00"

        for key in timetable:
            if not key.startswith('lesson_'):
                continue
            times = timetable[key]
            if not (isinstance(times, list) and len(times) == 2):
                continue
            try:
                start_t = datetime.strptime(times[0], "%H:%M:%S").time()
            except (ValueError, TypeError):
                continue

            if current_t < start_t:
                next_key = key
                next_start = times[0]
                next_subject = curriculum.get(key, "")
                next_period = int(key.split('_')[1]) if '_' in key else 0

                # 计算剩余时间
                try:
                    start_dt = datetime.strptime(times[0], "%H:%M:%S")
                    cur_dt = datetime.strptime(time_str, "%H:%M:%S")
                    left_sec = int((start_dt - cur_dt).total_seconds())
                    if left_sec < 0:
                        left_sec = 0
                    left_time_str = f"{left_sec // 3600:02d}:{(left_sec % 3600) // 60:02d}:{left_sec % 60:02d}"
                except (ValueError, TypeError):
                    left_time_str = "00:00:00"
                break

        kv: KLKVMap = KLKVMap()
        kv["event"] = "onClassEnd"
        kv["nextPeriod"] = str(next_period)
        kv["nextSubject"] = next_subject
        kv["nextStartTime"] = next_start
        kv["leftTime"] = left_time_str

        cls._sender.emitt(kv.serialize())
        logger.info(
            f"[KnotLink] 信号发射：onClassEnd nextPeriod={next_period} "
            f"nextSubject='{next_subject}' leftTime={left_time_str}"
        )

    # ══════════════════════════════════════════════════════════════════
    #  工具方法
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _get_current_time_str(cls) -> str:
        """获取当前时间字符串（优先使用调试模式下的模拟时间）。"""
        if cls._debug_config is not None:
            debug_time: Optional[str] = cls._debug_config.get_current_time_str()
            if debug_time is not None:
                return debug_time
        from PySide6.QtCore import QTime
        return QTime.currentTime().toString("hh:mm:ss")

    @classmethod
    def _get_current_day_name(cls) -> str:
        """获取当前星期名称（优先使用调试模式下的模拟星期）。"""
        if cls._debug_config is not None:
            debug_weekday: Optional[str] = cls._debug_config.get_weekday_name()
            if debug_weekday is not None:
                return debug_weekday
        return datetime.now().strftime('%A')

    @staticmethod
    def _calc_next_date_for_weekday(weekday_name: str) -> str:
        """
        计算指定星期的下一个匹配日期。
        ---------------------------
        参数：
            weekday_name（str）：英文星期名，如 'Monday'

        返回值：
            str：YYYY-MM-DD 格式的日期字符串
        """
        weekday_map: Dict[str, int] = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6,
        }
        target_wd: int = weekday_map.get(weekday_name, 0)
        today: datetime = datetime.now()
        today_wd: int = today.weekday()
        days_until: int = (target_wd - today_wd) % 7
        if days_until == 0:
            days_until = 0  # 今天就算
        next_date: datetime = today + timedelta(days=days_until)
        return next_date.strftime('%Y-%m-%d')


# ═══════════════════════════════════════════════════════════════════════════
#  节点自注册（KnotLink 独立式节点）
# ═══════════════════════════════════════════════════════════════════════════
#
#  📌 作用
#  ═══════════════════════════════════════════════════════════════════════════
#  让 KnotLink Hub 能在「独立式节点」列表中发现本程序。做法：
#    1. 启动时把内嵌的节点清单释放到
#         %LOCALAPPDATA%\KnotLink\<APP_ID>\
#       （清单必须内嵌进源码：打包后 exe 内没有仓库文件，无法从磁盘读取，
#         而 KnotLink Hub 需要 standalone_manifest.json + FuncList.json）
#    2. 写注册表
#         HKCU\Software\KnotLink\StandaloneNodes\<APP_ID> → 清单目录
#    3. 退出时（atexit）删除注册表项并清理清单目录
#
#  ⚠️ 内嵌清单的权威来源
#  ═══════════════════════════════════════════════════════════════════════════
#  下面两个常量是以下文件的**逐字节副本**：
#      KnotLink-Output/release/<APP_ID>/standalone_manifest.json
#      KnotLink-Output/release/<APP_ID>/FuncList.json
#  新增/删除 openSocket 接口或 signal 信号后，必须同步更新这两个常量，
#  否则 KnotLink Hub 会看到并不存在的接口。
#  （开发环境启动时会自动比对磁盘文件，不一致给出 warning，见
#    _check_embedded_manifests。）
#
#  📌 与安装包的关系
#  ═══════════════════════════════════════════════════════════════════════════
#  KnotLink-Output/nsis-registry.nsh 提供了等价的 ${KL_Register} /
#  ${KL_Unregister} 宏（注册表指向 $INSTDIR）。当前安装包并未
#  !include 它，也不需要：本模块的自注册不依赖安装目录里存在清单文件。

# 内嵌清单的权威来源（仅开发环境存在，用于漂移自检）
_MANIFEST_SRC_REL: str = os.path.join('KnotLink-Output', 'release', APPID)
_MANIFEST_NAME: str = 'standalone_manifest.json'
_FUNCLIST_NAME: str = 'FuncList.json'

# 清单释放目标目录：%LOCALAPPDATA%\KnotLink\<APP_ID>
_MANIFEST_DEST_DIR: str = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'KnotLink',
    APPID,
)

# KnotLink Hub 扫描独立式节点的注册表位置
_REG_KEY_PATH: str = r'Software\KnotLink\StandaloneNodes'

# atexit 退出清理只注册一次
_atexit_registered: bool = False


# === 内嵌 standalone_manifest.json（与 KnotLink-Output/release/<APP_ID>/ 逐字节一致）===
_EMBEDDED_STANDALONE_MANIFEST: str = '''{
  "app_id": "com.github.wenjin6470.schedule4",
  "app_name": "Schedule 4.0",
  "author": "WenJin",
  "version": "v1.0.0",
  "description": "桌面浮动电子课表系统 — 半透明置顶窗口实时显示课时科目与当前时间，支持快捷编辑、临时换课、考试/创意全屏模式",
  "download_url": "https://github.com/WenJin6470/Schedule4.0/releases/latest"
}
'''

# === 内嵌 FuncList.json（与 KnotLink-Output/release/<APP_ID>/ 逐字节一致）===
_EMBEDDED_FUNCLIST: str = '''{
  "appName": "Schedule 4.0",
  "specVersion": "1.0",
  "manifestVersion": "1.0.0",
  "openSocket": {
    "get-lesson-state": {
      "appID": "com.github.wenjin6470.schedule4",
      "openSocketID": "schedule",
      "description": "查询当前实时上课状态，包括当前科目、剩余时间、下一节课、是否上课中/课间/放学",
      "args": {
        "action": {
          "type": "static",
          "value": "get-lesson-state",
          "description": "命令类型（固定为 get-lesson-state）"
        }
      },
      "returns": [
        ["请求状态（ok/err）", "status"],
        ["是否正在上课（true/false）", "isInClass"],
        ["是否课间休息（true/false）", "isBreak"],
        ["当前课时序号（从1开始，无则为-1）", "currentPeriod"],
        ["当前科目名称", "currentSubject"],
        ["当前课时开始时间（HH:MM:SS）", "currentStartTime"],
        ["当前课时结束时间（HH:MM:SS）", "currentEndTime"],
        ["当前课时剩余时间（HH:MM:SS）", "remainingTime"],
        ["下一节课时序号（无则为-1）", "nextPeriod"],
        ["下一节科目名称", "nextSubject"],
        ["下一节课开始时间（HH:MM:SS）", "nextStartTime"],
        ["错误信息（status=err时返回）", "message"]
      ]
    },
    "get-today-schedule": {
      "appID": "com.github.wenjin6470.schedule4",
      "openSocketID": "schedule",
      "description": "获取当天或指定星期全部课时的科目与时间安排，含分隔线位置",
      "args": {
        "action": {
          "type": "static",
          "value": "get-today-schedule",
          "description": "命令类型（固定为 get-today-schedule）"
        },
        "day": {
          "type": "input",
          "defaultVal": "",
          "description": "目标星期（Monday~Sunday），留空则取当天"
        }
      },
      "returns": [
        ["请求状态（ok/err）", "status"],
        ["实际返回的星期名称", "day"],
        ["课表数据（JSON数组，每项含period/key/subject/startTime/endTime）", "lessons"],
        ["分隔线位置（JSON数组，值为分隔线前的课时索引0-based）", "dividerIndices"],
        ["总课时数", "totalPeriods"],
        ["错误信息（status=err时返回）", "message"]
      ]
    },
    "swap-course": {
      "appID": "com.github.wenjin6470.schedule4",
      "openSocketID": "schedule",
      "description": "临时换课：记录换课信息到swap_schedule.json，在指定日期当天自动将对应课时的科目替换为新科目，过期自动清理",
      "args": {
        "action": {
          "type": "static",
          "value": "swap-course",
          "description": "命令类型（固定为 swap-course）"
        },
        "day_name": {
          "type": "input",
          "defaultVal": "",
          "description": "星期名称（Monday~Sunday）"
        },
        "lesson_key": {
          "type": "input",
          "defaultVal": "",
          "description": "课时键名（如lesson_2）"
        },
        "old_subject": {
          "type": "input",
          "defaultVal": "",
          "description": "换课前的原始科目名称"
        },
        "new_subject": {
          "type": "input",
          "defaultVal": "",
          "description": "换课后的新科目名称"
        },
        "swap_date": {
          "type": "input",
          "defaultVal": "",
          "description": "换课生效日期（YYYY-MM-DD），留空则自动取该星期的下一个匹配日期"
        }
      },
      "returns": [
        ["请求状态（ok/err）", "status"],
        ["实际生效日期（YYYY-MM-DD）", "swap_date"],
        ["错误信息（status=err时返回）", "message"]
      ]
    }
  },
  "signal": {
    "onClassStart": {
      "appID": "com.github.wenjin6470.schedule4",
      "signalID": "events",
      "description": "上课事件，新一节课开始时触发推送",
      "returns": {
        "event": {
          "description": "事件标识（固定值onClassStart），用于鉴别信号类型",
          "verification": "onClassStart"
        },
        "period": {
          "description": "课时序号（从1开始）"
        },
        "subject": {
          "description": "当前科目名称"
        },
        "startTime": {
          "description": "课时开始时间（HH:MM:SS）"
        },
        "endTime": {
          "description": "课时结束时间（HH:MM:SS）"
        }
      }
    },
    "onClassEnd": {
      "appID": "com.github.wenjin6470.schedule4",
      "signalID": "events",
      "description": "下课事件，一节课结束时触发推送，含下一节课预告信息",
      "returns": {
        "event": {
          "description": "事件标识（固定值onClassEnd），用于鉴别信号类型",
          "verification": "onClassEnd"
        },
        "nextPeriod": {
          "description": "下一节课时序号（无则为-1）"
        },
        "nextSubject": {
          "description": "下一节科目名称（无则为空字符串）"
        },
        "nextStartTime": {
          "description": "下一节课开始时间（HH:MM:SS）"
        },
        "leftTime": {
          "description": "课间剩余时间（HH:MM:SS格式，距下一节课还有多久）"
        }
      }
    }
  }
}
'''


def _check_embedded_manifests() -> None:
    """
    开发环境自检：内嵌清单与仓库中的权威文件是否一致。
    --------------------------------------------------
    打包环境直接跳过（exe 旁不会有 KnotLink-Output/）；
    文件不存在时静默跳过；只在内容不一致时打 warning。
    """
    if is_frozen():
        return
    try:
        src_dir: str = os.path.join(app_root(), _MANIFEST_SRC_REL)
        pairs = (
            (_MANIFEST_NAME, _EMBEDDED_STANDALONE_MANIFEST),
            (_FUNCLIST_NAME, _EMBEDDED_FUNCLIST),
        )
        for fname, embedded in pairs:
            path: str = os.path.join(src_dir, fname)
            if not os.path.isfile(path):
                continue
            with open(path, 'r', encoding='utf-8') as f:
                on_disk: str = f.read()
            if on_disk != embedded:
                logger.warning(
                    f"[KnotLink] 内嵌 {fname} 与 {path} 不一致！"
                    f"请同步 knotlink_bridge.py 中的内嵌常量，"
                    f"否则 Hub 会看到过期的接口/信号列表"
                )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"内嵌清单自检跳过：{e}")


def register_self() -> None:
    """
    启动时：把内嵌清单释放到 %LOCALAPPDATA% 并写入注册表。
    -----------------------------------------------------
    每次启动都覆盖写入，确保清单内容与当前版本一致。
    开发环境与打包环境都会执行（便于源码运行时被 KnotLink Hub 识别）。
    注册成功后在 atexit 注册 unregister_self，退出时自动清理。
    """
    _check_embedded_manifests()

    # 1. 从内嵌字符串写入清单文件
    try:
        os.makedirs(_MANIFEST_DEST_DIR, exist_ok=True)

        manifest_path: str = os.path.join(_MANIFEST_DEST_DIR, _MANIFEST_NAME)
        funclist_path: str = os.path.join(_MANIFEST_DEST_DIR, _FUNCLIST_NAME)

        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write(_EMBEDDED_STANDALONE_MANIFEST)
        logger.info(f"[KnotLink] 已释放: {_MANIFEST_NAME} → {manifest_path}")

        with open(funclist_path, 'w', encoding='utf-8') as f:
            f.write(_EMBEDDED_FUNCLIST)
        logger.info(f"[KnotLink] 已释放: {_FUNCLIST_NAME} → {funclist_path}")
    except OSError as e:
        logger.warning(f"[KnotLink] 释放节点清单失败，跳过自注册：{e}")
        return

    # 2. 写入注册表
    try:
        import winreg  # noqa: PLC0415

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _REG_KEY_PATH,
                0, winreg.KEY_SET_VALUE,
            )
        except FileNotFoundError:
            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                _REG_KEY_PATH,
            )

        winreg.SetValueEx(key, APPID, 0, winreg.REG_SZ, _MANIFEST_DEST_DIR)
        winreg.CloseKey(key)
        logger.info(f"[KnotLink] 注册表已写入: {APPID} → {_MANIFEST_DEST_DIR}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[KnotLink] 写入自注册表项失败，跳过自注册：{e}")
        return

    # 3. 注册退出清理（确保只注册一次）
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(unregister_self)
        _atexit_registered = True
        logger.info("[KnotLink] 已注册退出清理回调")


def unregister_self() -> None:
    """退出时：删除注册表项 + 清理释放的清单文件。"""
    # 1. 删除注册表项
    try:
        import winreg  # noqa: PLC0415

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_KEY_PATH,
            0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, APPID)
        winreg.CloseKey(key)
        logger.info(f"[KnotLink] 注册表项已删除: {APPID}")
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[KnotLink] 删除注册表项失败: {e}")

    # 2. 删除释放的清单目录
    if os.path.exists(_MANIFEST_DEST_DIR):
        try:
            shutil.rmtree(_MANIFEST_DEST_DIR)
            logger.info(f"[KnotLink] 清单目录已清理: {_MANIFEST_DEST_DIR}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[KnotLink] 清理清单目录失败: {e}")
