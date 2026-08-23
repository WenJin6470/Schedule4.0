"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— knotlink_bridge.py（KnotLink 协议桥接）        ║
║               （将 Schedule 4.0 接入 KnotLink 节点网络）                 ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
  本文件是 Schedule 4.0 与 KnotLink 协议之间的桥接层，负责：
    ✅ 接收其他节点发来的请求（5 个 openSocket 接口）
    ✅ 向外广播课表事件（3 个 signal 信号）
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
          time_window=time_window,
          fullscreen_window=fullscreen_window,
          exam_window=exam_window,
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
    _time_window: Optional[Any] = None
    _fullscreen_window: Optional[Any] = None
    _exam_window: Optional[Any] = None
    _debug_config: Optional[Any] = None

    # ---- KnotLink SDK 实例 ----
    _responser: Optional[OpenSocketResponser] = None
    _sender: Optional[SignalSender] = None

    # ---- 信号状态跟踪（用于检测上课/下课/放学切换） ----
    _prev_state: str = "unknown"       # "in_class" | "break" | "after_school" | "unknown"
    _prev_period_key: str = ""         # 上一秒所在课时的 lesson_key
    _initialized: bool = False

    # ---- 事件系统状态跟踪（用于事件触发检测，防止同一条事件重复广播） ----
    _event_rules_cache: List[Dict] = []
    _event_rules_mtime: Optional[float] = None
    _fired_events: set = set()

    # ══════════════════════════════════════════════════════════════════
    #  公开方法：初始化桥接
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def setup(cls, *,
              time_manager: Any,
              schedule_data: Any,
              main_window: Any,
              time_window: Any,
              fullscreen_window: Any,
              exam_window: Any = None,
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
        cls._time_window = time_window
        cls._fullscreen_window = fullscreen_window
        cls._exam_window = exam_window
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
        elif action == "enter-fullscreen":
            return cls._handle_enter_fullscreen(req)
        elif action == "exit-fullscreen":
            return cls._handle_exit_fullscreen()
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
            resp["isAfterSchool"] = "false"
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
                resp["isAfterSchool"] = "false"
            else:
                resp["isBreak"] = "false"
                resp["isAfterSchool"] = "true"

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
    #  请求处理：enter-fullscreen
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_enter_fullscreen(cls, req: KLKVMap) -> str:
        """
        进入全屏时间模式（考试模式或创意模式）。
        """
        resp: KLKVMap = KLKVMap()
        mode: str = req.get("mode", "exam").strip().lower()

        if mode not in ("exam", "creative"):
            resp["status"] = "err"
            resp["message"] = f"无效的模式：'{mode}'，合法值：exam / creative"
            return resp.serialize()

        # 取消 TimeWindow 置顶
        if cls._time_window is not None:
            cls._time_window.set_always_on_top(False)

        if mode == "exam" and cls._exam_window is not None:
            cls._exam_window.show_fullscreen()
            resp["mode"] = "exam"
            logger.info("[KnotLink] 已进入考试模式全屏")
        elif mode == "creative" and cls._fullscreen_window is not None:
            cls._fullscreen_window.show_fullscreen(mode='creative')
            resp["mode"] = "creative"
            logger.info("[KnotLink] 已进入创意模式全屏")
        else:
            resp["status"] = "err"
            resp["message"] = "对应模式的窗口未初始化"
            return resp.serialize()

        resp["status"] = "ok"
        return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  请求处理：exit-fullscreen
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _handle_exit_fullscreen(cls) -> str:
        """
        退出全屏模式，恢复浮动窗口。
        """
        resp: KLKVMap = KLKVMap()

        # 隐藏全屏窗口
        if cls._fullscreen_window is not None:
            cls._fullscreen_window.hide()
        if cls._exam_window is not None:
            cls._exam_window.hide()

        # 恢复 TimeWindow 置顶
        if cls._time_window is not None:
            cls._time_window.set_always_on_top(True)

        resp["status"] = "ok"
        logger.info("[KnotLink] 已退出全屏模式，恢复浮动窗口")
        return resp.serialize()

    # ══════════════════════════════════════════════════════════════════
    #  信号广播：时间滴答回调
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _on_time_tick(cls, time_str: str) -> None:
        """
        TimeManager.time_tick 回调（每秒一次）。
        ---------------------------------------
        检测上课/下课/放学状态切换，并在切换时广播对应信号。

        状态切换规则：
          - 从"非上课"进入某节课 → 发射 onClassStart
          - 从"上课中"进入课间   → 发射 onClassEnd
          - 从"上课中"进入放学   → 发射 onDayEnd（最后一节课结束后）
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
            elif current_state == "after_school" and cls._prev_state == "in_class":
                cls._emit_on_day_end()

        # 事件系统：检测用户自定义事件是否到达触发时刻（独立于上课状态）
        cls._check_and_emit_events(time_str)

        cls._prev_state = current_state
        cls._prev_period_key = current_key if current_state == "in_class" else ""

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

    @classmethod
    def _emit_on_day_end(cls) -> None:
        """发射 onDayEnd 信号。"""
        if cls._sender is None:
            return

        kv: KLKVMap = KLKVMap()
        kv["event"] = "onDayEnd"
        cls._sender.emitt(kv.serialize())
        logger.info("[KnotLink] 信号发射：onDayEnd")

    # ══════════════════════════════════════════════════════════════════
    #  信号广播：事件系统（用户自定义事件触发）
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def _check_and_emit_events(cls, time_str: str) -> None:
        """
        检测用户自定义事件是否到达触发时刻，并广播对应信号。
        ---------------------------------------------------
        事件规则来自 Config/event_rules.json，每项含 type/time/name 及
        类型相关字段，支持五种触发类型：
          daily   → 每天固定时间触发
          weekly  → 每周指定星期触发（weekday：0=周一 … 6=周日）
          monthly → 每月指定日期触发（day：1-31）
          yearly  → 每年指定月日触发（month：1-12，day：1-31）
          date    → 具体日期触发（date：YYYY-MM-DD；旧格式规则视为该类型）
        当「规则命中今天」且「事件时间（HH:MM）== 当前时间」时触发；
        已触发过的事件（以 日期|时间|名称|类型等 为键）在本会话内不再重复广播，
        循环规则每天使用新的日期键，因此每天都会重新触发一次。
        """
        if cls._sender is None:
            return

        date_str: str = cls._get_current_date_str()
        current_hm: str = time_str[:5]  # HH:MM

        rules: List[Dict] = cls._load_event_rules_cached()
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            r_time: str = str(rule.get('time', '') or '').strip()
            r_name: str = str(rule.get('name', '') or '').strip()
            if not r_time or r_time[:5] != current_hm:
                continue
            if not cls._rule_matches_date(rule, date_str):
                continue

            key: str = (
                f"{date_str}|{r_time}|{r_name}|{rule.get('type', 'date')}|"
                f"{rule.get('weekday', '')}|{rule.get('month', '')}|"
                f"{rule.get('day', '')}|{rule.get('date', '')}"
            )
            if key in cls._fired_events:
                continue
            cls._fired_events.add(key)
            cls._emit_on_event_trigger(r_name, date_str, r_time)

    @classmethod
    def _rule_matches_date(cls, rule: Dict, date_str: str) -> bool:
        """
        判断事件规则是否命中指定日期。
        ---------------------------
        旧格式规则（无 type 字段）视为具体时间点（date 类型）。
        """
        rtype: str = str(rule.get('type', '') or '').strip() or 'date'
        if rtype == 'daily':
            return True
        try:
            today_dt: datetime = datetime.strptime(date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            return False
        if rtype == 'weekly':
            try:
                return today_dt.weekday() == int(rule.get('weekday'))
            except (TypeError, ValueError):
                return False
        if rtype == 'monthly':
            try:
                return today_dt.day == int(rule.get('day'))
            except (TypeError, ValueError):
                return False
        if rtype == 'yearly':
            try:
                return (today_dt.month == int(rule.get('month'))
                        and today_dt.day == int(rule.get('day')))
            except (TypeError, ValueError):
                return False
        # 具体时间点（date）
        return str(rule.get('date', '') or '').strip() == date_str

    @classmethod
    def _load_event_rules_cached(cls) -> List[Dict]:
        """
        读取事件规则（带文件修改时间缓存）。
        ----------------------------------
        仅当 Config/event_rules.json 的内容发生变化时重新读取，
        避免每秒一次的文件 IO 与 JSON 解析开销；设置页实时增删改后
        下一次 tick 即可感知到最新规则。
        """
        import os as _os
        from schedule_config import EventRulesManager

        path: str = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)),
            'Config', 'event_rules.json',
        )
        try:
            mtime: float = _os.path.getmtime(path)
        except OSError:
            cls._event_rules_mtime = None
            cls._event_rules_cache = []
            return []

        if cls._event_rules_mtime == mtime and cls._event_rules_cache is not None:
            return cls._event_rules_cache

        cls._event_rules_mtime = mtime
        cls._event_rules_cache = EventRulesManager().load_rules()
        return cls._event_rules_cache

    @classmethod
    def _emit_on_event_trigger(cls, name: str, date_str: str,
                               time_str: str) -> None:
        """发射 onEventTrigger 信号。"""
        if cls._sender is None:
            return

        kv: KLKVMap = KLKVMap()
        kv["event"] = "onEventTrigger"
        kv["name"] = name
        kv["date"] = date_str
        kv["time"] = time_str

        cls._sender.emitt(kv.serialize())
        logger.info(
            f"[KnotLink] 信号发射：onEventTrigger name='{name}' "
            f"date={date_str} time={time_str}"
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

    @classmethod
    def _get_current_date_str(cls) -> str:
        """获取当前日期字符串（优先使用调试模式下的模拟日期，YYYY-MM-DD）。"""
        if cls._debug_config is not None and cls._debug_config.enabled:
            debug_dt = cls._debug_config.get_current_datetime()
            if debug_dt is not None:
                return debug_dt.strftime('%Y-%m-%d')
        return datetime.now().strftime('%Y-%m-%d')

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
