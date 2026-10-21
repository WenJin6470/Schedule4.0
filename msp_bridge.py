# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📡 MSP 桥接层 —— 电子课表接入 MSP 协议网络                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
把课表程序同时作为 MSP 网络里的两个角色：

  ① 功能提供方 —— 对外提供 3 个接口（MSP 里叫「工具」）
       · get-lesson-state      查询实时上课状态
       · get-today-schedule    获取当天/指定星期的完整课表
       · swap-course           临时换课

  ② 信息发出方 —— 对外发布 2 个信号
       · schedule.class.start  上课
       · schedule.class.end    下课

接口与信号的字段定义见 `API文档/KnotLink-API.md`。

📌 上下课信号的触发时间从哪里来（★ 关键）
═══════════════════════════════════════════════════════════════════════════
**不硬编码任何时间。** 每秒 tick 时都重新读 `schedule_data.timetable_data`，
也就是**程序当前正在使用的那一份时间表**。这份时间表由启动时
`DisplayRulesManager.resolve_for_today()` 按 `Config/Display_Rules.json`
的日期规则挑出来，例如：

    rule_2 → 2026年8月17日到2027年8月17日 → Config/timetable/timetable_4.json
    rule_1 → 每周一                        → Config/timetable/timetable_2.json
    rule_3 → 每年8月23日                   → Config/timetable/timetable_1.json

所以：换一条显示规则、换一份时间表，上下课信号的触发时间**自动跟着变**，
本文件一行都不用改。运行中通过设置页切换时间表（reload_timetable）也立刻生效。

时间比较一律把 "H:MM:SS" / "HH:MM:SS" 解析成 time 对象再比 ——
时间表里两种写法都有（如 timetable_4.json 的 lesson_1 是 "7:00:00"），
直接用字符串比较会得出错误结果。

📌 MSP SDK 是可选依赖
═══════════════════════════════════════════════════════════════════════════
未安装 `msp` 时本模块**静默降级**：课表所有功能不受影响，只是不接入 MSP 网络。
与 `knotlink_bridge.py` 并存、互不干扰，两者可以同时运行。

📌 线程模型（★ 容易踩坑）
═══════════════════════════════════════════════════════════════════════════
· 本模块 3 个工具函数**由 MSP 在后台线程里调用**（每次调用新起一个线程），
  所以工具内部**绝对不能直接碰 Qt 控件**。
· `swap-course` 需要刷新界面时，通过 `_UiRelay` 这个 Qt 信号投递回主线程执行。
· `_on_time_tick` 是 Qt 信号槽，运行在**主线程**，在里面调 `node.publish()` 是安全的。
"""
import logging
import re
from datetime import date, datetime, time as dtime, timedelta
from typing import Annotated, Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

logger: logging.Logger = logging.getLogger('msp_bridge')

# ================================================================
#  ★ MSP SDK 可选导入 —— 未安装时静默降级 ★
# ================================================================
try:
    from msp import MSPNode, Preset  # type: ignore
    _HAS_MSP: bool = True
    logger.info("MSP SDK 已加载，桥接功能可用")
except ImportError:
    MSPNode = None  # type: ignore
    Preset = None  # type: ignore
    _HAS_MSP = False
    logger.warning("MSP SDK 未安装，桥接功能不可用（课表系统正常运行）")


# ================================================================
#  常量
# ================================================================
VALID_WEEKS: Tuple[str, ...] = (
    'Monday', 'Tuesday', 'Wednesday', 'Thursday',
    'Friday', 'Saturday', 'Sunday',
)

#: 临时换课记录格式：lesson_N
_LESSON_KEY_RE = re.compile(r'^lesson_\d+$')
#: 日期格式：YYYY-MM-DD
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# ================================================================
#  UI 中继 —— 把「刷新界面」这件事从工作线程投递回主线程
# ================================================================
class _UiRelay(QObject):
    """跨线程 UI 中继。

    MSP 的工具函数在后台线程执行，直接调用 `main_window.set_display_week()`
    属于跨线程操作 Qt 控件，会导致崩溃或未定义行为。
    这里用 Qt 信号（自动队列连接）把请求投递回主线程。
    """

    #: (day_name, lesson_key, new_subject) —— 请求把换课立即应用到界面
    apply_swap = Signal(str, str, str)


# ================================================================
#  主桥接类
# ================================================================
class MSPBridge:
    """MSP 桥接：把课表接入 MSP 网络（功能提供方 + 信号发出方）。"""

    # ---- 节点身份（MSP 规范要求 [a-z0-9_-]+，不能含点）----
    NODE_ID: str = 'schedule4'

    # ---- 工具名（与 KnotLink-API.md 的三个 action 保持一致）----
    TOOL_LESSON_STATE: str = 'get-lesson-state'
    TOOL_TODAY_SCHEDULE: str = 'get-today-schedule'
    TOOL_SWAP_COURSE: str = 'swap-course'

    # ---- 信号路径（域.实体.动作，便于对端用 schedule.** 一次性订阅）----
    SIG_CLASS_START: str = 'schedule.class.start'
    SIG_CLASS_END: str = 'schedule.class.end'

    # ---- 运行状态 ----
    _initialized: bool = False
    _node: Any = None
    _relay: Optional[_UiRelay] = None
    _time_manager: Any = None
    _schedule_data: Any = None
    _main_window: Any = None
    _debug_config: Any = None

    #: 上一次的课时状态：unknown / in_class / break / after_school
    _prev_state: str = 'unknown'

    # ================================================================
    #  生命周期
    # ================================================================
    @classmethod
    def setup(cls, *, time_manager: Any, schedule_data: Any,
              main_window: Any, debug_config: Any = None) -> None:
        """初始化 MSP 桥接并启动课表节点。

        参数：
            time_manager  （TimeManager）       —— 提供 time_tick 秒级信号
            schedule_data （ScheduleDataManager）—— 提供 timetabledata / curriculum_data
            main_window   （ScheduleMainWindow）—— 换课需要立即刷新界面时使用
            debug_config  （DebugConfig | None）—— 调试模式（模拟日期/时间）

        说明：重复调用只警告一次；SDK 缺失时静默降级。
        """
        if cls._initialized:
            logger.warning("MSP 桥接已初始化，忽略重复调用")
            return

        cls._time_manager = time_manager
        cls._schedule_data = schedule_data
        cls._main_window = main_window
        cls._debug_config = debug_config

        if not _HAS_MSP:
            logger.info("MSP SDK 不可用，跳过 MSP 网络层初始化")
            cls._initialized = True
            return

        try:
            cls._start_node()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MSP 节点启动失败，桥接功能不可用（忽略）：{e}")
            cls._node = None

        cls._initialized = True

    @classmethod
    def _start_node(cls) -> None:
        """创建节点、注册工具与信号、启动监听。"""
        # LOCAL_TOOL：宣告自己 + 提供工具 + 可广播，不主动发现别人（accept-only）。
        # 对端（如通知程序）用带发现能力的预设连上来即可。
        node: Any = MSPNode(cls.NODE_ID, preset=Preset.LOCAL_TOOL) # type: ignore

        # ---- 注册 3 个工具 ----
        node.tool(cls.TOOL_LESSON_STATE, "查询当前实时上课状态")(
            _tool_get_lesson_state)
        node.tool(cls.TOOL_TODAY_SCHEDULE, "获取当天或指定星期的完整课表")(
            _tool_get_today_schedule)
        node.tool(cls.TOOL_SWAP_COURSE, "临时换课（写入换课记录，当天生效）")(
            _tool_swap_course)

        # ---- 声明 2 个信号路径（进能力清单，对端可据此判断）----
        node.declare_signal(cls.SIG_CLASS_START, description="上课事件")
        node.declare_signal(cls.SIG_CLASS_END, description="下课事件")

        # ---- 连接状态回调（仅打日志；回调在握手线程里执行）----
        node.on_connected(
            lambda peer_id, manifest: logger.info(f"[MSP] 节点已连接：{peer_id}"))
        node.on_disconnected(
            lambda peer_id: logger.info(f"[MSP] 节点已断开：{peer_id}"))

        # ---- 启动（settle=False：不阻塞启动流程）----
        node.start(settle=False)
        cls._node = node

        logger.info(f"[MSP] 课表节点已启动：node_id={cls.NODE_ID} "
                    f"endpoint={node.endpoint}")

        # ---- UI 中继（在主线程创建，工作线程 emit 会被排队回主线程）----
        cls._relay = _UiRelay()
        cls._relay.apply_swap.connect(cls._on_apply_swap_requested)

        # ---- 订阅秒级 tick，做上下课状态切换检测 ----
        #   time_tick 由主线程的 QTimer 发出，且已自动尊重调试模式的模拟时间
        cls._time_manager.time_tick.connect(cls._on_time_tick)
        logger.info("[MSP] 已订阅 TimeManager.time_tick，开始监测上下课事件")

        # ---- 打印一次当前使用的时间表，便于确认信号时间来源 ----
        try:
            tt_path: str = getattr(cls._schedule_data, 'timetable_path', '?')
            logger.info(f"[MSP] 当前使用的时间表：{tt_path}"
                        f"（共 {len(cls._ordered_periods())} 节课，"
                        f"上下课信号将按此时间表触发）")
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def teardown(cls) -> None:
        """关闭 MSP 节点（撤销声明、断开连接）。幂等，可在退出时安全调用。

        注意：MSP 0.1.0 的节点**不可 stop 后再次 start**（心跳线程不会复活），
        所以这里是进程退出前的一次性收尾。
        """
        node: Any = cls._node
        cls._node = None
        if node is None:
            return
        try:
            if cls._time_manager is not None:
                try:
                    cls._time_manager.time_tick.disconnect(cls._on_time_tick)
                except Exception:  # noqa: BLE001
                    pass
            node.stop()
            logger.info("[MSP] 课表节点已停止")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MSP] 节点停止失败（忽略）：{e}")

    # ================================================================
    #  手动发送信号 —— 设置页「MSP 测试」使用
    #  ★ 只发布信号，**不触碰** _prev_state 状态机，
    #    所以手动测试不会干扰真实的上下课判定。
    # ================================================================
    @classmethod
    def is_running(cls) -> bool:
        """MSP 节点是否已启动。"""
        return cls._node is not None

    @classmethod
    def peers(cls) -> List[str]:
        """当前已连接的对端节点 id 列表。"""
        node: Any = cls._node
        if node is None:
            return []
        try:
            return list(node.connections())
        except Exception:  # noqa: BLE001
            return []

    @classmethod
    def endpoint_str(cls) -> str:
        """当前节点对外端点；未启动时返回空字符串。"""
        node: Any = cls._node
        if node is None:
            return ''
        ep: Any = getattr(node, 'endpoint', None)
        if ep is None:
            return ''
        # 拼成 tcp://host:port 这种可读形式，避免直接暴露 Endpoint 的 repr
        addr: Any = getattr(ep, 'address', None)
        ttype: str = str(getattr(ep, 'transport_type', '') or '')
        if isinstance(addr, dict):
            host: Any = addr.get('host', '')
            port: Any = addr.get('port', '')
            if host and port:
                return f'{ttype}://{host}:{port}'
        return str(ep)

    @classmethod
    def publish_signal(cls, path: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """手动发布一个信号（测试用，不改变内部状态机）。

        参数：
            path    （str）：信号路径，如 schedule.class.start
            payload （dict）：信号负载，必须是 JSON 对象

        返回值：
            (是否成功, 给人看的说明)
        """
        node: Any = cls._node
        if node is None:
            return False, 'MSP 节点未启动（SDK 未安装，或桥接尚未初始化完成）'
        clean_path: str = (path or '').strip()
        if not clean_path:
            return False, '信号路径不能为空'
        if not isinstance(payload, dict):
            return False, 'payload 必须是 JSON 对象'
        try:
            node.publish(clean_path, payload)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MSP] 手动发布信号失败：{e}")
            return False, f'发布失败：{e}'

        connected: List[str] = cls.peers()
        logger.info(
            f"[MSP] 手动发布 {clean_path}（对端 {len(connected)} 个）：{payload}"
        )
        if not connected:
            return True, (f'已发布 {clean_path}，但当前没有已连接的对端 —— '
                          f'没有人能收到，信号会丢失')
        return True, (f'已发布 {clean_path} → {len(connected)} 个对端：'
                      f'{", ".join(connected)}')

    @classmethod
    def build_start_payload(cls) -> Tuple[Optional[Dict[str, Any]], str]:
        """按「当前时间 + 当前课表」构造与真实上课信号同构的 payload。

        优先取当前正在上的那节课；不在课上时退化为下一节；再不行取第一节。

        返回值：
            (payload 或 None, 说明)
        """
        now: Optional[dtime] = cls._now_time()
        if now is None:
            return None, '取不到当前时间'
        periods: List[Tuple[int, str, dtime, dtime]] = cls._ordered_periods()
        if not periods:
            return None, '当前时间表里没有可用课时'

        _state, key = cls._detect_period_state(now)
        target: Optional[Tuple[int, str, dtime, dtime]] = None
        if key is not None:
            for item in periods:
                if item[1] == key:
                    target = item
                    break
        if target is None:
            target = cls._next_period(now) or periods[0]

        no, lkey, start, end = target
        return {
            'event': 'onClassStart',
            'period': no,
            'subject': cls._subject_of(lkey),
            'startTime': cls._fmt_hms(start),
            'endTime': cls._fmt_hms(end),
        }, f'取第 {no} 节（{lkey}）'

    @classmethod
    def build_end_payload(cls) -> Tuple[Optional[Dict[str, Any]], str]:
        """按「当前时间 + 当前课表」构造与真实下课信号同构的 payload。

        返回值：
            (payload 或 None, 说明)
        """
        now: Optional[dtime] = cls._now_time()
        if now is None:
            return None, '取不到当前时间'
        nxt: Optional[Tuple[int, str, dtime, dtime]] = cls._next_period(now)
        if nxt is None:
            return {
                'event': 'onClassEnd',
                'nextPeriod': -1,
                'nextSubject': '',
                'nextStartTime': '',
                'leftTime': '00:00:00',
            }, '今天已无后续课时'

        no, lkey, start, _end = nxt
        return {
            'event': 'onClassEnd',
            'nextPeriod': no,
            'nextSubject': cls._subject_of(lkey),
            'nextStartTime': cls._fmt_hms(start),
            'leftTime': cls._fmt_delta(cls._seconds_between(now, start)),
        }, f'下一节第 {no} 节（{lkey}）'

    # ================================================================
    #  工具实现 —— 供 _tool_* 模块级函数调用
    # ================================================================
    @classmethod
    def _build_lesson_state(cls) -> Dict[str, Any]:
        """构造 get-lesson-state 的返回值。"""
        now: Optional[dtime] = cls._now_time()
        if now is None or not cls._ordered_periods():
            return {'status': 'err', 'message': '时间表数据为空'}

        state, key = cls._detect_period_state(now)
        periods: List[Tuple[int, str, dtime, dtime]] = cls._ordered_periods()

        resp: Dict[str, Any] = {
            'status': 'ok',
            'isInClass': state == 'in_class',
            'isBreak': state == 'break',
            'currentPeriod': -1,
            'currentSubject': '',
            'currentStartTime': '',
            'currentEndTime': '',
            'remainingTime': '00:00:00',
            'nextPeriod': -1,
            'nextSubject': '',
            'nextStartTime': '',
        }

        # ---- 当前课时 ----
        if state == 'in_class' and key is not None:
            for no, lkey, start, end in periods:
                if lkey == key:
                    resp['currentPeriod'] = no
                    resp['currentSubject'] = cls._subject_of(lkey)
                    resp['currentStartTime'] = cls._fmt_hms(start)
                    resp['currentEndTime'] = cls._fmt_hms(end)
                    resp['remainingTime'] = cls._fmt_delta(cls._seconds_between(now, end))
                    break

        # ---- 下一节课 ----
        nxt = cls._next_period(now)
        if nxt is not None:
            no, lkey, start, _end = nxt
            resp['nextPeriod'] = no
            resp['nextSubject'] = cls._subject_of(lkey)
            resp['nextStartTime'] = cls._fmt_hms(start)

        return resp

    @classmethod
    def _build_today_schedule(cls, day: str = '') -> Dict[str, Any]:
        """构造 get-today-schedule 的返回值。"""
        day_name: str = (day or '').strip()
        if not day_name:
            day_name = cls._current_day_name()
        if day_name not in VALID_WEEKS:
            return {'status': 'err',
                    'message': f'非法的星期名：{day!r}（应为 Monday~Sunday）'}

        periods: List[Tuple[int, str, dtime, dtime]] = cls._ordered_periods()
        if not periods:
            return {'status': 'err', 'day': day_name, 'message': '时间表数据为空'}

        curriculum: Dict[str, str] = cls._curriculum_for_day(day_name)

        lessons: List[Dict[str, Any]] = []
        for no, lkey, start, end in periods:
            lessons.append({
                'period': no,
                'key': lkey,
                'subject': curriculum.get(lkey, ''),
                'startTime': cls._fmt_hms(start),
                'endTime': cls._fmt_hms(end),
            })

        return {
            'status': 'ok',
            'day': day_name,
            'lessons': lessons,                        # 原生数组（不再二次 JSON 编码）
            'dividerIndices': cls._divider_indices(),  # 原生数组
            'totalPeriods': len(lessons),
        }

    @classmethod
    def _build_swap_course(cls, day_name: str = '', lesson_key: str = '',
                           old_subject: str = '', new_subject: str = '',
                           swap_date: str = '') -> Dict[str, Any]:
        """构造 swap-course 的返回值：校验 + 落盘 + 请求立即刷新界面。"""
        from schedule_config import SwapManager  # 延迟导入，避免循环依赖

        day_name = (day_name or '').strip()
        lesson_key = (lesson_key or '').strip()
        new_subject = (new_subject or '').strip()
        swap_date = (swap_date or '').strip()

        # ---- 校验 ----
        if day_name not in VALID_WEEKS:
            return {'status': 'err',
                    'message': f'非法的星期名：{day_name!r}（应为 Monday~Sunday）'}
        if not _LESSON_KEY_RE.match(lesson_key):
            return {'status': 'err',
                    'message': f'非法的课时键：{lesson_key!r}（应形如 lesson_2）'}

        valid_keys = {lkey for _no, lkey, _s, _e in cls._ordered_periods()}
        if lesson_key not in valid_keys:
            return {'status': 'err',
                    'message': f'课时不存在于当前时间表：{lesson_key}'}

        if not swap_date:
            swap_date = cls._next_date_for_weekday(day_name)
        elif not _DATE_RE.match(swap_date):
            return {'status': 'err',
                    'message': f'非法的日期：{swap_date!r}（应形如 2026-10-15）'}
        else:
            try:
                datetime.strptime(swap_date, '%Y-%m-%d')
            except ValueError:
                return {'status': 'err',
                        'message': f'非法的日期：{swap_date!r}（不是一个真实日期）'}

        if not old_subject:
            old_subject = cls._curriculum_for_day(day_name).get(lesson_key, '')

        # ---- 落盘 ----
        record: Dict[str, str] = {
            'day_name': day_name,
            'lesson_key': lesson_key,
            'old_subject': old_subject,
            'new_subject': new_subject,
            'swap_date': swap_date,
        }
        try:
            ok: bool = SwapManager().add_swaps([record])
        except Exception as e:  # noqa: BLE001
            return {'status': 'err', 'message': f'写入换课记录失败：{e}'}
        if not ok:
            return {'status': 'err', 'message': '写入换课记录失败'}

        logger.info(f"[MSP] swap-course 已记录：{record}")

        # ---- 若生效日就是今天，请求主线程立即刷新界面 ----
        today: str = cls._today_str()
        applied_now: bool = False
        if swap_date == today and cls._relay is not None:
            try:
                cls._relay.apply_swap.emit(day_name, lesson_key, new_subject)
                applied_now = True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[MSP] 请求立即刷新界面失败（忽略）：{e}")

        return {
            'status': 'ok',
            'swap_date': swap_date,
            'appliedNow': applied_now,
            'message': ('换课记录已保存；生效日为今天，已请求立即刷新界面'
                        if applied_now else '换课记录已保存，将在生效日当天应用'),
        }

    # ================================================================
    #  主线程槽：把换课立即应用到界面
    # ================================================================
    @classmethod
    def _on_apply_swap_requested(cls, day_name: str, lesson_key: str,
                                 new_subject: str) -> None:
        """在主线程执行：改内存课程表 + 刷新主窗口。"""
        try:
            schedule_data: Any = cls._schedule_data
            window: Any = cls._main_window
            if schedule_data is None or window is None:
                return
            day_data: Dict[str, str] = schedule_data.curriculum_data.setdefault(
                day_name, {})
            day_data[lesson_key] = new_subject
            if window.get_display_week() == day_name:
                window.set_display_week(day_name)
                logger.info(f"[MSP] 换课已立即应用到界面：{day_name} {lesson_key}"
                            f" -> {new_subject}")
            else:
                logger.info(f"[MSP] 换课已写入内存（当前显示的是"
                            f" {window.get_display_week()}，未刷新界面）")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MSP] 应用换课到界面失败（忽略）：{e}")

    # ================================================================
    #  信号：上下课状态机
    # ================================================================
    @classmethod
    def _on_time_tick(cls, time_str: str) -> None:
        """每秒 tick：检测状态切换，仅在**切换时**发布信号。

        状态含义：
            unknown       尚未取到基线（首帧只记录，不发信号）
            in_class      正在上某节课
            break         课间休息（今天还有后续课时）
            after_school  放学后（今天没有后续课时了）
        """
        if cls._node is None:
            return
        try:
            now: Optional[dtime] = cls._parse_hms(time_str)
            if now is None:
                return
            state, key = cls._detect_period_state(now)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MSP] 课时状态检测失败（忽略）：{e}")
            return

        prev: str = cls._prev_state
        if prev == 'unknown':
            cls._prev_state = state
            return                      # 首帧建立基线，不补发信号

        try:
            if state == 'in_class' and prev != 'in_class':
                cls._publish_class_start(key, now)
            elif prev == 'in_class' and state != 'in_class':
                # ★ 只要「离开上课状态」就发下课信号，覆盖两种情况：
                #     in_class → break         课间
                #     in_class → after_school  当天最后一节课结束
                #   原 KnotLink 版只处理了 break（`elif state == "break"`），
                #   导致**当天最后一节课的下课信号永远发不出去**。这里修掉。
                cls._publish_class_end(now)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MSP] 发布信号失败（忽略）：{e}")

        cls._prev_state = state

    @classmethod
    def _publish_class_start(cls, lesson_key: Optional[str],
                             now: dtime) -> None:
        """发布「上课」信号。"""
        periods: List[Tuple[int, str, dtime, dtime]] = cls._ordered_periods()
        for no, lkey, start, end in periods:
            if lkey != lesson_key:
                continue
            payload: Dict[str, Any] = {
                'event': 'onClassStart',                 # 保留 event 字段，与 API 文档一致
                'period': no,
                'subject': cls._subject_of(lkey),
                'startTime': cls._fmt_hms(start),
                'endTime': cls._fmt_hms(end),
            }
            cls._node.publish(cls.SIG_CLASS_START, payload)
            logger.info(f"[MSP] ▶ 发布 {cls.SIG_CLASS_START}：{payload}")
            return

    @classmethod
    def _publish_class_end(cls, now: dtime) -> None:
        """发布「下课」信号（含下一节课预告）。"""
        nxt = cls._next_period(now)
        if nxt is not None:
            no, lkey, start, _end = nxt
            next_period: int = no
            next_subject: str = cls._subject_of(lkey)
            next_start: str = cls._fmt_hms(start)
            left_time: str = cls._fmt_delta(cls._seconds_between(now, start))
        else:
            next_period = -1
            next_subject = ''
            next_start = ''
            left_time = '00:00:00'

        payload: Dict[str, Any] = {
            'event': 'onClassEnd',
            'nextPeriod': next_period,
            'nextSubject': next_subject,
            'nextStartTime': next_start,
            'leftTime': left_time,
        }
        cls._node.publish(cls.SIG_CLASS_END, payload)
        logger.info(f"[MSP] ▶ 发布 {cls.SIG_CLASS_END}：{payload}")

    # ================================================================
    #  课时判定
    # ================================================================
    @classmethod
    def _detect_period_state(cls, now: dtime) -> Tuple[str, Optional[str]]:
        """判断 now 处于什么状态。

        返回值：(state, lesson_key)
            ('in_class', 'lesson_3')  正在上 lesson_3
            ('break', None)           课间休息
            ('after_school', None)    今天没有后续课时
        """
        next_start: Optional[dtime] = None
        for _no, lkey, start, end in cls._ordered_periods():
            # 起止时间颠倒的异常项（如 timetable_4 的 lesson_10）直接跳过，
            # 不参与「是否在上课」的判断
            if start >= end:
                continue
            if start <= now < end:
                return 'in_class', lkey
            if start > now and (next_start is None or start < next_start):
                next_start = start
        return ('break', None) if next_start is not None else ('after_school', None)

    @classmethod
    def _ordered_periods(cls) -> List[Tuple[int, str, dtime, dtime]]:
        """按 lesson_N 的编号顺序返回 [(课时序号, 键名, 开始, 结束)]。

        注意：**不能依赖 JSON 的键顺序** —— timetable_4.json 里键的书写顺序是
        lesson_2, lesson_1, lesson_4, ... 并不按编号排列。课时序号取 lesson_N 的 N。
        起止时间解析失败或格式不完整的项会被跳过。
        """
        result: List[Tuple[int, str, dtime, dtime]] = []
        data: Dict[str, Any] = cls._timetable_data()
        for key, val in data.items():
            if not isinstance(key, str) or not key.startswith('lesson_'):
                continue
            try:
                no: int = int(key.split('_', 1)[1])
            except (IndexError, ValueError):
                continue
            if not isinstance(val, (list, tuple)) or len(val) < 2:
                continue
            start: Optional[dtime] = cls._parse_hms(val[0])
            end: Optional[dtime] = cls._parse_hms(val[1])
            if start is None or end is None:
                continue
            result.append((no, key, start, end))
        result.sort(key=lambda item: item[0])
        return result

    @classmethod
    def _next_period(cls, now: dtime) -> Optional[Tuple[int, str, dtime, dtime]]:
        """返回 now 之后最近的一节课（按开始时间）。"""
        best: Optional[Tuple[int, str, dtime, dtime]] = None
        for item in cls._ordered_periods():
            _no, _lkey, start, end = item
            if start >= end:
                continue
            if start > now and (best is None or start < best[2]):
                best = item
        return best

    # ================================================================
    #  数据访问
    # ================================================================
    @classmethod
    def _timetable_data(cls) -> Dict[str, Any]:
        """当前时间表原始数据（程序当前使用的那一份）。"""
        return dict(getattr(cls._schedule_data, 'timetable_data', None) or {})

    @classmethod
    def _curriculum_for_day(cls, day_name: str) -> Dict[str, str]:
        """指定星期的课程表 {lesson_key: subject}。"""
        try:
            return dict(cls._schedule_data.get_curriculum_for_day(day_name) or {})
        except Exception:  # noqa: BLE001
            return {}

    @classmethod
    def _subject_of(cls, lesson_key: str) -> str:
        """当前星期下某节课的科目名。"""
        return cls._curriculum_for_day(cls._current_day_name()).get(lesson_key, '')

    @classmethod
    def _divider_indices(cls) -> List[int]:
        """分隔线位置（0-based 课时索引）。

        复用 ScheduleDataManager 的实现以保证与界面显示一致；
        同时过滤掉负值 —— 原实现在 dividerline 出现在任何 lesson 之前时会
        返回 -1（`indices.append(lesson_counter - 1)` 且无防护）。
        """
        try:
            return [i for i in cls._schedule_data.get_divider_indices() if i >= 0]
        except Exception:  # noqa: BLE001
            return []

    @classmethod
    def _now_time(cls) -> Optional[dtime]:
        """当前时间（尊重调试模式的模拟时间）。"""
        if cls._debug_config is not None:
            try:
                s: Optional[str] = cls._debug_config.get_current_time_str()
                if s:
                    parsed: Optional[dtime] = cls._parse_hms(s)
                    if parsed is not None:
                        return parsed
            except Exception:  # noqa: BLE001
                pass
        return datetime.now().time().replace(microsecond=0)

    @classmethod
    def _current_day_name(cls) -> str:
        """当前英文星期名（尊重调试模式的模拟日期）。

        刻意**不用** `strftime('%A')` —— 它受系统 locale 影响，中文 locale 下会
        返回「星期一」这类本地化名称，既通不过 VALID_WEEKS 校验，也无法与
        课程表 JSON 里的英文键名对应。改用 weekday() 直接索引。
        """
        if cls._debug_config is not None:
            try:
                name: Optional[str] = cls._debug_config.get_weekday_name()
                if name in VALID_WEEKS:
                    return name
            except Exception:  # noqa: BLE001
                pass
        return VALID_WEEKS[datetime.now().weekday()]

    @classmethod
    def _today_str(cls) -> str:
        """生效的「今天」日期串 YYYY-MM-DD（尊重调试模式的模拟日期）。"""
        if cls._debug_config is not None and getattr(cls._debug_config, 'enabled', False):
            try:
                dt: Optional[datetime] = cls._debug_config.get_current_datetime()
                if dt is not None:
                    return dt.strftime('%Y-%m-%d')
            except Exception:  # noqa: BLE001
                pass
        return datetime.now().strftime('%Y-%m-%d')

    # ================================================================
    #  小工具
    # ================================================================
    @staticmethod
    def _parse_hms(value: Any) -> Optional[dtime]:
        """把 'H:MM:SS' 或 'HH:MM:SS' 解析成 time。

        时间表里两种写法都有（timetable_4.json 的 lesson_1 是 "7:00:00"），
        所以必须解析后再比较，不能直接比字符串。
        """
        if isinstance(value, dtime):
            return value
        parts = str(value).strip().split(':')
        if len(parts) != 3:
            return None
        try:
            hour, minute, second = (int(p) for p in parts)
        except ValueError:
            return None
        if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
            return None
        return dtime(hour, minute, second)

    @staticmethod
    def _fmt_hms(value: dtime) -> str:
        """time → 'HH:MM:SS'（统一补零，保证对端格式一致）。"""
        return value.strftime('%H:%M:%S')

    @staticmethod
    def _seconds_between(start: dtime, end: dtime) -> int:
        """end - start 的秒数（同一天内，负数取 0）。"""
        base: date = date(2000, 1, 1)
        delta: timedelta = (datetime.combine(base, end)
                            - datetime.combine(base, start))
        return max(0, int(delta.total_seconds()))

    @classmethod
    def _fmt_delta(cls, seconds: int) -> str:
        """秒数 → 'HH:MM:SS'。"""
        seconds = max(0, int(seconds))
        return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'

    @classmethod
    def _next_date_for_weekday(cls, day_name: str) -> str:
        """返回该星期几的下一个匹配日期（今天匹配则取今天），YYYY-MM-DD。"""
        try:
            target: int = VALID_WEEKS.index(day_name)
        except ValueError:
            return cls._today_str()
        today: date = datetime.strptime(cls._today_str(), '%Y-%m-%d').date()
        delta: int = (target - today.weekday()) % 7
        return (today + timedelta(days=delta)).strftime('%Y-%m-%d')


# ================================================================
#  模块级工具函数
#  —— 单独定义是为了让 MSP 能从「函数签名 + 类型注解」自动生成 JSON Schema；
#     它们只是薄薄一层，真正的逻辑在 MSPBridge 里。
# ================================================================
def _tool_get_lesson_state() -> dict:
    """查询当前实时上课状态。"""
    try:
        return MSPBridge._build_lesson_state()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[MSP] get-lesson-state 执行失败：{e}")
        return {'status': 'err', 'message': f'内部错误：{e}'}


def _tool_get_today_schedule(
    day: Annotated[str, "目标星期（Monday~Sunday），留空则取当天"] = '',
) -> dict:
    """获取当天或指定星期的完整课表。"""
    try:
        return MSPBridge._build_today_schedule(day)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[MSP] get-today-schedule 执行失败：{e}")
        return {'status': 'err', 'message': f'内部错误：{e}'}


def _tool_swap_course(
    day_name: Annotated[str, "星期名称，如 Monday"] = '',
    lesson_key: Annotated[str, "课时键名，如 lesson_2"] = '',
    old_subject: Annotated[str, "换课前的原始科目名，留空则自动取当前科目"] = '',
    new_subject: Annotated[str, "换课后的新科目名"] = '',
    swap_date: Annotated[str, "生效日期 YYYY-MM-DD，留空则取该星期的下一个匹配日期"] = '',
) -> dict:
    """临时换课：写入换课记录，生效日当天自动替换科目。"""
    try:
        return MSPBridge._build_swap_course(
            day_name, lesson_key, old_subject, new_subject, swap_date)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[MSP] swap-course 执行失败：{e}")
        return {'status': 'err', 'message': f'内部错误：{e}'}
