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
    ✅ 完全解耦：knotlink SDK 未安装时静默降级，不影响课表正常运行

📌 架构
═══════════════════════════════════════════════════════════════════════════
  外部节点 ──(KnotLink协议)──▶ knotlink_bridge.py ──(方法调用)──▶ 业务模块
                             knotlink_bridge.py ◀──(信号订阅)──  TimeManager
  外部节点 ◀──(KnotLink协议)── knotlink_bridge.py

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
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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
          2. 如果 SDK 可用，创建 OpenSocketResponser 并注册请求处理函数
          3. 订阅 TimeManager.time_tick 以检测上课/下课/放学事件
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

        # 创建 OpenSocketResponser 并注册处理函数
        cls._responser = OpenSocketResponser(APPID, SOCKET_ID)
        cls._responser.set_RecvFunc(cls._handle_request)
        logger.info(f"OpenSocketResponser 已创建：appID={APPID}, socketID={SOCKET_ID}")

        # 创建 SignalSender
        cls._sender = SignalSender(APPID, SIGNAL_ID)
        logger.info(f"SignalSender 已创建：appID={APPID}, signalID={SIGNAL_ID}")

        # 订阅 TimeManager.time_tick 以检测状态变化
        time_manager.time_tick.connect(cls._on_time_tick)
        logger.info("已订阅 TimeManager.time_tick，开始监测上课/下课/放学事件")

        cls._initialized = True
        logger.info("KnotLinkBridge 初始化完成")

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
