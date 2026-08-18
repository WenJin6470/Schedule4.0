"""
╔══════════════════════════════════════════════════════════════════════════╗
║               📅 电子课表系统 —— schedule_backend.py（后端）              ║
║                      （前后端分离架构 · 后端部分）                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 类说明
═══════════════════════════════════════════════════════════════════════════
  TimeManager  — 时间管理类：负责实时时间的获取，通过 QTimer 定时触发
  WindowHelper — 辅助功能类：负责关闭所有窗口并退出程序
  LogManager   — 日志管理类：负责清理过期日志文件

📌 设计理念
═══════════════════════════════════════════════════════════════════════════
  后端 ≈ 餐厅的厨师
  - 厨师只负责：做菜（处理业务逻辑）
  - 厨师不管：客人坐在哪、盘子长什么样（那是服务员/前端的事）

  TimeManager ≈ 厨房里的计时器，到点了喊一声"时间到了！"
  WindowHelper ≈ 打烊时关灯锁门的帮手
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QTime, Signal, QObject, QPointF, QRectF
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame,
    QGridLayout, QVBoxLayout, QHBoxLayout, QDialog,
)
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QColor, QPen, QLinearGradient

from schedule_actions import ActionMessage, ActionType

if TYPE_CHECKING:
    from schedule_config import DebugConfig

# 获取本模块的 logger，日志将传播到 main.py 配置的根 logger
logger: logging.Logger = logging.getLogger(__name__)


# ==================== 主窗口科目标签字体自适应 ====================

# 主窗口科目显示字体的标准字号（点），自适应只缩小、绝不放大。
SUBJECT_FONT_STANDARD_SIZE: int = 16
# 自适应缩小的最小字号（点）：即使仍放不下也以此下限返回，避免出现 0 号字。
SUBJECT_FONT_MIN_SIZE: int = 1
# 标签左右各预留的像素边距，避免文字贴住标签边缘。
SUBJECT_FONT_H_PADDING: int = 4


def fit_subject_font(font_family: str, text: str,
                     max_width: int, max_height: int,
                     base_size: int = SUBJECT_FONT_STANDARD_SIZE,
                     min_size: int = SUBJECT_FONT_MIN_SIZE,
                     h_padding: int = SUBJECT_FONT_H_PADDING) -> QFont:
    """
    自适应计算主窗口科目标签的字体大小。
    ---------------------------------
    从标准字号 base_size 开始逐点向下缩小，直到文字能在
    max_width × max_height 区域内完全显示；返回的字号永远不会大于 base_size。

    参数：
        font_family（str）：字体家族名（如 Arial、Microsoft YaHei）
        text       （str）：要显示的科目文字（中文或英文）
        max_width  （int）：标签可用宽度（像素）
        max_height （int）：标签可用高度（像素）
        base_size  （int）：标准字号（点），默认 16，结果不会超过它
        min_size   （int）：允许缩到的最小字号（点），仍放不下时按此返回
        h_padding  （int）：左右各预留的边距（像素），避免文字贴边

    返回值：
        QFont：字号 ≤ base_size、且能容纳 text 的最大字体
    """
    if not font_family:
        font_family = 'Arial'
    text = text or ''

    usable_width: int = max(1, int(max_width) - 2 * int(h_padding))
    usable_height: int = max(1, int(max_height))

    # 空文字无需测量，直接返回标准字号
    if not text.strip():
        return QFont(font_family, base_size)

    for size in range(int(base_size), int(min_size) - 1, -1):
        font: QFont = QFont(font_family, size)
        metrics: QFontMetrics = QFontMetrics(font)
        if (metrics.horizontalAdvance(text) <= usable_width
                and metrics.height() <= usable_height):
            return font

    return QFont(font_family, min_size)


# ==================== 时间管理类 ====================

class TimeManager(QObject):
    """
    # TimeManager — 时间管理类（发布-订阅模式）

    负责实时时间的获取与管理。
    内部使用 QTimer 每秒触发一次，通过 Qt Signal 将当前时间广播给所有订阅者。
    ---

    使用方式：
        tm = TimeManager()
        tm.time_tick.connect(time_window.update_time_display)           # 订阅者1
        tm.time_tick.connect(fullscreen_window.update_time_display)     # 订阅者2
        tm.start()
        # ... 程序结束时调用 tm.stop()

    对外接口：
      - time_tick : Signal(str) — 时间滴答信号，每秒发射一次，携带时间字符串
      - start()                  — 启动定时器
      - stop()                   — 停止定时器
      - get_current_time()       — 手动获取当前时间字符串
    """

    # ================================================================
    #  ★ 核心变更：用 Signal 替代 callback
    #  Signal 原生支持多订阅者，无需管理回调列表
    # ================================================================
    time_tick = Signal(str)

    def __init__(self, debug_config: "Optional[DebugConfig]" = None) -> None:
        """
        初始化时间管理器。
        -----------------
        创建 QTimer 实例并设置间隔为 1000ms（1 秒）。
        定时器在调用 start() 之前不会启动。

        参数：
            debug_config（Optional[DebugConfig]）：调试配置管理器，
              传入后时间将使用调试模拟时间（流动计时）
        """
        super().__init__()
        logger.info("TimeManager 初始化：创建 QTimer（间隔 1000ms）+ time_tick Signal")
        self._debug_config: "Optional[DebugConfig]" = debug_config
        self._timer: QTimer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timeout)
        logger.info("TimeManager 初始化完成")

    # ================================================================
    #  公开方法1：启动定时器
    # ================================================================
    def start(self) -> None:
        """
        启动定时器，开始每秒广播时间。
        ---------------------------
        说明：
          - 调用 start() 后会立即发射一次时间信号，确保界面立刻显示时间
          - 不需要传入回调 —— 订阅者通过 time_tick.connect() 自行注册
          - 多次调用 start() 安全（Qt 内部处理重复启动）
        """
        logger.info("TimeManager 启动：定时器间隔 1000ms")
        self._timer.start()
        # 立即发射一次，不等 1 秒 —— 确保界面立刻显示当前时间
        self._on_timeout()

    # ================================================================
    #  公开方法2：停止定时器
    # ================================================================
    def stop(self) -> None:
        """
        停止定时器。
        -----------
        说明：
          - 仅停止 QTimer，不自动断开 Signal 连接
          - 订阅者如需取消订阅，应自行调用 time_tick.disconnect()
          - 这种设计让订阅者自己管理生命周期，TimeManager 不越权
        """
        logger.info("TimeManager 停止：正在停止定时器...")
        self._timer.stop()
        logger.info("TimeManager 已停止")

    # ================================================================
    #  公开方法3：手动获取当前时间（不变）
    # ================================================================
    def get_current_time(self) -> str:
        """
        手动获取当前时间字符串（不依赖定时器）。
        -------------------------------------
        若调试模式启用，返回流动的调试模拟时间；
        否则返回系统真实时间。

        返回值：
            str：当前时间，格式为 HH:MM:SS（24 小时制）
                 示例："14:30:05"
        """
        if self._debug_config is not None:
            debug_time = self._debug_config.get_current_time_str()
            if debug_time is not None:
                return debug_time
        return QTime.currentTime().toString("hh:mm:ss")

    # ================================================================
    #  私有方法：定时器超时处理
    # ================================================================
    def _on_timeout(self) -> None:
        """
        定时器超时回调（私有方法，每秒自动调用一次）。
        -------------------------------------------
        功能：
          1. 获取当前时间字符串
          2. 通过 time_tick Signal 广播给所有订阅者
        """
        current_time = self.get_current_time()
        logger.debug(f"定时器触发，当前时间：{current_time}")
        self.time_tick.emit(current_time)


# ==================== 辅助功能类 ====================

class WindowHelper:
    """
    # WindowHelper — 辅助功能类

    提供窗口相关的辅助操作，目前包含关闭所有窗口并退出程序的功能。
    ---

    所有方法均为静态方法，无需实例化即可使用，也可以创建实例使用。

    对外接口：
      - close_all(widgets, app)：关闭所有窗口并退出程序
    """

    @staticmethod
    def close_all(widgets: List[Optional[QWidget]], app: QApplication) -> None:
        """
        关闭所有窗口并退出应用程序。
        -------------------------
        参数：
            widgets（List[Optional[QWidget]]）：需要关闭的 QWidget 列表
                                               列表中的每个元素会被依次关闭
            app     （QApplication）：          QApplication 实例，用于调用 quit()

        使用示例：
            # 作为静态方法调用
            WindowHelper.close_all([window, root_window], app)

            # 或者创建实例调用
            helper = WindowHelper()
            helper.close_all([window, root_window], app)

        执行流程：
          1. 遍历 widgets 列表，逐个调用 close() 关闭每个窗口
          2. 调用 app.quit() 退出 Qt 事件循环，程序结束

        安全说明：
          - 传入 None 的 widget 会被自动跳过，不会报错
          - close() 只是发送关闭事件，窗口的资源由 Qt 自动管理
        """
        # 第1步：逐个关闭所有窗口
        for widget in widgets:
            if widget is not None:
                logger.info(f"正在关闭窗口：{widget.__class__.__name__}")
                widget.close()

        # 第2步：退出应用程序事件循环
        # QApplication.quit() 会让 app.exec() 返回，程序正常退出
        logger.info("所有窗口已关闭，正在退出 QApplication 事件循环...")
        app.quit()
        logger.info("已调用 app.quit()，程序即将退出")


# ==================== 课表快捷编辑专属处理类 ====================

class QuickEditHandler:
    """
    # QuickEditHandler — 课表快捷编辑专属后端处理器

    负责处理快捷编辑相关的所有业务逻辑：
      - 光标管理与闪烁
      - 科目标签更新
      - 光标移动（上下 / 倍速）
      - 确认并退出编辑

    此类持有对主窗口（ScheduleMainWindow）的引用，
    通过调用主窗口的公开 API 来操作课时标签。
    ---

    对外接口：
      - handle(action, main_window, subject_window) — 分发快捷编辑动作
    """

    def __init__(self) -> None:
        """初始化快捷编辑处理器。"""
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._logger.info("QuickEditHandler 初始化完成")

    def handle(self, msg: ActionMessage, main_window,
               subject_window=None) -> None:
        """
        处理快捷编辑相关的动作。
        ----------------------
        参数：
            msg            （ActionMessage）：        结构化动作消息
            main_window    （ScheduleMainWindow）：   课表主窗口引用
            subject_window （SubjectSelectWindow）：  快捷编辑子窗口引用（可选）
        """
        self._logger.info(f"[QuickEdit] 收到动作: {msg.type.value}")

        if msg.type == ActionType.QUICK_EDIT_OPENED:
            self._on_quick_edit_opened(main_window, subject_window)

        elif msg.type == ActionType.SUBJECT_SELECTED:
            subject_name: str = msg.payload["name"]
            self._on_subject_selected(main_window, subject_name)

        elif msg.type == ActionType.MOVE_UP:
            self._on_move(main_window, -1, subject_window)

        elif msg.type == ActionType.MOVE_DOWN:
            self._on_move(main_window, 1, subject_window)

        elif msg.type == ActionType.MOVE_DOUBLE_UP:
            self._on_move(main_window, -2, subject_window)

        elif msg.type == ActionType.MOVE_DOUBLE_DOWN:
            self._on_move(main_window, 2, subject_window)

        elif msg.type == ActionType.CONFIRM:
            self._on_confirm(main_window, subject_window)

        elif msg.type == ActionType.QUICK_EDIT_CLOSED:
            self._on_quick_edit_closed(main_window)

        elif msg.type == ActionType.CURSOR_INFO:
            # 主窗口发来的光标信息 → 转发给快捷编辑窗口显示
            self._on_cursor_info(msg, subject_window)

        elif msg.type == ActionType.WEEK_CHANGED:
            # 星期滚轮切换 → 更新主窗口课表显示
            self._on_week_changed(msg, main_window)

        elif msg.type == ActionType.TEMP_SWAP_CONFIRMED:
            # 用户确认临时换课 → 保存换课记录并立即应用
            self._on_temp_swap_confirmed(msg, main_window)

        else:
            self._logger.debug(f"[QuickEdit] 不处理的动作: {msg.type.value}")

    # ================================================================
    #  快捷编辑窗口打开
    # ================================================================
    def _on_quick_edit_opened(self, main_window,
                               subject_window=None) -> None:
        """快捷编辑窗口打开 → 启动第一个标签的光标闪烁。"""
        self._logger.info("[QuickEdit] 快捷编辑窗口已打开，启动光标闪烁")
        current_text: str = main_window.start_cursor_blink(0)
        self._logger.info(f"[QuickEdit] 光标位置：第1节，当前内容：'{current_text}'")

    # ================================================================
    #  科目按钮点击
    # ================================================================
    def _on_subject_selected(self, main_window,
                               subject_name: str) -> None:
        """
        用户选择了科目 → 更新光标标签并自动下移光标。
        """
        old_subject: str = main_window.get_cursor_subject()
        cursor_idx: int = main_window.get_cursor_index()

        self._logger.info(f"[QuickEdit] 科目选择：第{cursor_idx + 1}节 "
                          f"'{old_subject}' → '{subject_name}'")

        # 更新光标标签内容
        main_window.set_cursor_subject(subject_name)

        # 自动下移光标
        total: int = main_window.get_period_count()
        if cursor_idx + 1 < total:
            main_window.move_cursor(1)
        else:
            self._logger.info("[QuickEdit] 已到最后一节，光标不移动")

    # ================================================================
    #  光标移动
    # ================================================================
    def _on_move(self, main_window, steps: int,
                  subject_window=None) -> None:
        """移动光标（steps 正数向下，负数向上）。"""
        main_window.move_cursor(steps)

    # ================================================================
    #  确认操作
    # ================================================================
    def _on_confirm(self, main_window, subject_window=None) -> None:
        """
        确认编辑 → 保存课表数据到文件，停止光标闪烁并退出快捷编辑界面。
        ---------------------------------------------------------
        流程：
          1. 将当前显示星期的标签修改同步回 curriculum_data
          2. 将完整的七日课表数据写入 JSON 文件
          3. 停止光标闪烁
          4. 隐藏快捷编辑窗口
        """
        self._logger.info("[QuickEdit] 确认编辑，正在保存课表数据...")

        # 第1步：同步当前星期的标签修改到内存数据
        main_window._sync_current_day_labels()

        # 第2步：将完整的七日课表写入 JSON 文件
        success: bool = main_window._schedule_data.save_curriculum()
        if success:
            self._logger.info("[QuickEdit] 课表数据已成功保存到文件")
        else:
            self._logger.error("[QuickEdit] 课表数据保存失败！")

        # 第3步：停止光标闪烁
        main_window.stop_cursor_blink()

        # 第4步：隐藏快捷编辑窗口
        if subject_window is not None:
            subject_window.hide()

    # ================================================================
    #  快捷编辑窗口关闭（点击 ✕）
    # ================================================================
    def _on_quick_edit_closed(self, main_window) -> None:
        """快捷编辑窗口关闭 → 停止光标闪烁，退出快捷编辑界面。"""
        self._logger.info("[QuickEdit] 快捷编辑窗口关闭，停止光标闪烁")
        main_window.stop_cursor_blink()

    # ================================================================
    #  星期滚轮切换
    # ================================================================
    def _on_week_changed(self, msg: ActionMessage, main_window) -> None:
        """
        用户通过星期滚轮切换了显示星期 → 更新主窗口课表标签。
        """
        week_name: str = msg.payload.get("week_name", "Monday")
        self._logger.info(f"[QuickEdit] 星期切换：{week_name}")
        main_window.set_display_week(week_name)

    # ================================================================
    #  临时换课确认
    # ================================================================
    def _on_temp_swap_confirmed(self, msg: ActionMessage, main_window) -> None:
        """
        用户确认临时换课 → 保存换课记录并立即应用到当前课表。
        --------------------------------------------------
        流程：
          1. 从消息中提取换课数据
          2. 通过 SwapManager 追加换课记录到文件
          3. 立即将换课应用到当前 curriculum_data（内存中）
          4. 刷新主窗口显示
        """
        from schedule_config import SwapManager

        swaps: list = msg.payload.get("swaps", [])
        if not swaps:
            self._logger.warning("[QuickEdit] 换课确认信号中无数据")
            return

        self._logger.info(f"[QuickEdit] 收到换课确认：{len(swaps)} 条")

        # 打印换课详情
        for swap in swaps:
            self._logger.info(
                f"  换课：{swap.get('day_name', '')} "
                f"{swap.get('lesson_key', '')} "
                f"'{swap.get('old_subject', '')}' → "
                f"'{swap.get('new_subject', '')}' "
                f"日期={swap.get('swap_date', '')}"
            )

        # 保存换课记录到文件
        swap_manager: SwapManager = SwapManager()
        swap_manager.add_swaps(swaps)

        # 立即将今日的换课应用到内存中的课表数据
        # ★ 使用 SwapManager 统一获取生效日期（自动适配调试模式）
        today_str: str = SwapManager._get_effective_today(
            main_window._debug_config
        )
        schedule_data = main_window._schedule_data
        applied_today: int = 0
        for swap in swaps:
            if swap.get('swap_date', '') == today_str:
                day_name: str = swap.get('day_name', '')
                lesson_key: str = swap.get('lesson_key', '')
                new_subject: str = swap.get('new_subject', '')
                if day_name and lesson_key:
                    if day_name in schedule_data.curriculum_data:
                        schedule_data.curriculum_data[day_name][lesson_key] = new_subject
                        applied_today += 1

        if applied_today > 0:
            self._logger.info(
                f"[QuickEdit] 已立即应用 {applied_today} 条今日换课到内存数据"
            )
            # 如果当前显示的是被修改的星期，刷新标签
            current_day: str = main_window.get_display_week()
            main_window.set_display_week(current_day)

        self._logger.info("[QuickEdit] 换课处理完成")

    # ================================================================
    #  光标信息回传
    # ================================================================
    def _on_cursor_info(self, msg: ActionMessage, subject_window=None) -> None:
        """
        收到主窗口发来的光标信息 → 更新快捷编辑窗口的状态栏。
        从 ActionMessage.payload 中提取 index 和 text。
        """
        index: int = msg.payload.get("index", -1)
        text: str = msg.payload.get("text", "")
        if index < 0:
            return
        self._logger.debug(f"[QuickEdit] 光标信息：第{index + 1}节 '{text}'")
        if subject_window is not None:
            subject_window.update_cursor_info(index, text)


# ==================== 后端信号处理类 ====================

class ScheduleBackend:
    """
    # ScheduleBackend — 后端信号处理器

    接收前端统一的后端信号（backend_signal），根据 ActionMessage.type
    分派给对应的业务逻辑处理。
    ---

    对外接口：
      - handle_action(msg, main_window, ...) — 处理来自前端的动作消息

    动作类型说明（详见 schedule_actions.ActionType）：
      - CLOSE            → 关闭所有窗口并退出程序
      - FULLSCREEN_TIME  → 显示全屏时间窗口
      - SETTINGS         → 打开设置窗口
      - QUICK_EDIT_*     → 快捷编辑相关动作（委托 QuickEditHandler）
      - SUBJECT_SELECTED → 用户选择了一个科目
      - MOVE_*           → 光标移动操作
      - CONFIRM          → 确认编辑操作
      - CURSOR_INFO      → 光标位置信息回传
    """

    def __init__(self) -> None:
        """初始化后端信号处理器。"""
        self._logger: logging.Logger = logging.getLogger(__name__)
        # 快捷编辑专属处理器
        self.quick_edit: QuickEditHandler = QuickEditHandler()
        self._logger.info("ScheduleBackend 初始化完成")

    def handle_action(self, msg: ActionMessage, main_window,
                       time_window, fullscreen_window,
                       app: QApplication,
                       exam_window=None,
                       subject_window=None) -> None:
        """
        处理来自前端的统一信号。
        ----------------------
        参数：
            msg                （ActionMessage）：      结构化动作消息
            main_window        （ScheduleMainWindow）： 课表主窗口引用
            time_window        （TimeWindow）：         时间窗口引用
            fullscreen_window  （FullscreenTimeWindow）：全屏时间窗口引用（创意模式）
            app                （QApplication）：       QApplication 实例
            exam_window        （ExamFullscreenWindow）：考试模式全屏窗口引用（可选）
            subject_window     （SubjectSelectWindow）：快捷编辑窗口引用（可选）

        说明：
          快捷编辑类动作委托给 QuickEditHandler 处理，
          系统类动作（关闭/全屏/设置）在本类中直接处理。
        """
        self._logger.info(f"[后端] 收到动作: {msg.type.value}")

        # ---- 快捷编辑相关 → 委托 QuickEditHandler ----
        if msg.type in (ActionType.QUICK_EDIT_OPENED, ActionType.CONFIRM,
                        ActionType.QUICK_EDIT_CLOSED, ActionType.SUBJECT_SELECTED,
                        ActionType.CURSOR_INFO, ActionType.MOVE_UP, ActionType.MOVE_DOWN,
                        ActionType.MOVE_DOUBLE_UP, ActionType.MOVE_DOUBLE_DOWN,
                        ActionType.WEEK_CHANGED, ActionType.TEMP_SWAP_CONFIRMED):
            self.quick_edit.handle(msg, main_window, subject_window)
            return

        # ---- 系统操作 → 本类处理 ----
        if msg.type == ActionType.CLOSE:
            # 先停止光标闪烁
            main_window.stop_cursor_blink()
            WindowHelper.close_all(
                [time_window, main_window, fullscreen_window, exam_window], app
            )
        elif msg.type == ActionType.FULLSCREEN_TIME:
            self._logger.info("[后端] 全屏时间 — 显示全屏时间窗口（旧版兼容）")
            time_window.set_always_on_top(False)
            fullscreen_window.show_fullscreen(mode='exam')
        elif msg.type == ActionType.FULLSCREEN_TIME_EXAM:
            self._logger.info("[后端] 全屏时间（考试模式）— 墨绿色背景 + 科目/时间编辑")
            if exam_window is not None:
                time_window.set_always_on_top(False)
                exam_window.show_fullscreen()
        elif msg.type == ActionType.FULLSCREEN_TIME_CREATIVE:
            self._logger.info("[后端] 全屏时间（创意模式）— 随机图片背景 + 红色实时时间")
            time_window.set_always_on_top(False)
            fullscreen_window.show_fullscreen(mode='creative')
        elif msg.type == ActionType.SETTINGS:
            self._logger.info("[后端] 设置")
        else:
            self._logger.warning(f"[后端] 未知动作: {msg.type.value}")


# ==================== 日志管理类 ====================

class LogManager:
    """
    # LogManager — 日志管理类

    负责清理超过保留期限的旧日志文件。
    ---

    所有方法均为静态方法，无需实例化即可使用。

    对外接口：
      - cleanup_old_logs(log_dir, retention_days) — 清理过期日志文件
    """

    # 日志文件名正则：schedule_YYYY-MM-DD.log
    _LOG_FILE_PATTERN: str = r'^schedule_(\d{4}-\d{2}-\d{2})\.log$'

    @staticmethod
    def cleanup_old_logs(log_dir: str, retention_days: int,
                         logger: Optional[logging.Logger] = None) -> int:
        """
        清理超过保留期限的旧日志文件。
        ---------------------------
        参数：
            log_dir        （str）：          日志文件所在目录
            retention_days （int）：          日志保留天数，≤0 表示跳过清理
            logger         （Optional[Logger]）：用于记录清理结果的 logger

        返回值：
            int：删除的日志文件数量

        说明：
          日志文件名格式为 schedule_YYYY-MM-DD.log，
          文件名中的日期早于 (今天 - retention_days) 的文件将被删除。
        """
        if logger is None:
            logger = logging.getLogger(__name__)

        if retention_days <= 0:
            logger.info("log_retention_days ≤ 0，跳过日志清理")
            return 0

        if not os.path.isdir(log_dir):
            logger.warning(f"日志目录不存在：{log_dir}，跳过日志清理")
            return 0

        # 计算保留截止日期（在此日期之前的日志将被删除）
        cutoff_date: datetime = datetime.now() - timedelta(days=retention_days)
        logger.info(
            f"开始日志清理：保留最近 {retention_days} 天，"
            f"截止日期 {cutoff_date.strftime('%Y-%m-%d')} 之前的日志将被删除"
        )

        pattern = re.compile(LogManager._LOG_FILE_PATTERN)
        deleted_count: int = 0

        try:
            for filename in os.listdir(log_dir):
                match = pattern.match(filename)
                if not match:
                    continue

                try:
                    file_date: datetime = datetime.strptime(
                        match.group(1), '%Y-%m-%d'
                    )
                except ValueError:
                    logger.debug(f"无法解析日志文件日期：{filename}，跳过")
                    continue

                if file_date < cutoff_date:
                    filepath: str = os.path.join(log_dir, filename)
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                        logger.info(f"已删除过期日志：{filename}")
                    except OSError as e:
                        logger.warning(f"无法删除日志文件 {filename}：{e}")

        except OSError as e:
            logger.error(f"遍历日志目录失败：{e}")
            return deleted_count

        if deleted_count == 0:
            logger.info("日志清理完成，无需删除的文件")
        else:
            logger.info(f"日志清理完成，共删除 {deleted_count} 个过期日志文件")

        return deleted_count


# ==================== 滚轮时间选择器（共享组件）====================

class WheelColumn(QWidget):
    """
    # WheelColumn — iOS 风格滚轮列

    自定义 QPainter 绘制的垂直滚轮控件，用于选择时间数值。
    特性：
      - 中心高亮行（较大字体 + 100% 不透明度）
      - 远离中心的项渐变缩小并淡出
      - 顶部/底部渐变遮罩（淡出效果）
      - 鼠标拖拽 + 滚轮滚动
      - 松开时自动吸附到最近项（缓出动画）
    ---

    信号：
      selection_changed(int) — 选中项索引变化时发射
    """

    selection_changed = Signal(int)

    def __init__(self, items: List[str], initial_index: int = 0,
                 parent: Optional[QWidget] = None,
                 bg_color: str = '#0f261e',
                 text_color: str = '#FFFFFF') -> None:
        """
        初始化滚轮列。

        参数：
            items         （List[str]）：所有可选值
            initial_index （int）：      初始选中项索引
            parent        （QWidget | None）：父控件
            bg_color      （str）：      背景颜色（默认墨绿色）
            text_color    （str）：      文字颜色（默认白色）
        """
        super().__init__(parent)
        self._items: List[str] = list(items)
        self._item_height: int = 55
        self._bg_color: str = bg_color
        self._text_color: str = text_color
        self._float_pos: float = float(
            max(0, min(initial_index, len(self._items) - 1))
        ) if self._items else 0.0

        # ---- 拖拽状态 ----
        self._is_dragging: bool = False
        self._drag_start_y: float = 0.0
        self._drag_start_pos: float = 0.0
        self._has_moved: bool = False

        # ---- 吸附动画 ----
        self._anim_timer: QTimer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._animate_step)
        self._anim_start_pos: float = 0.0
        self._anim_target_pos: float = 0.0
        self._anim_frame: int = 0
        self._anim_total_frames: int = 12

        self._prev_index: int = self.current_index

        self.setFixedWidth(80)
        self.setMinimumHeight(250)
        self.setMouseTracking(True)

    # ================================================================
    #  公开属性 / 方法
    # ================================================================
    @property
    def current_index(self) -> int:
        """当前选中项索引（四舍五入后取模，实现循环滚动）。"""
        if not self._items:
            return 0
        n: int = len(self._items)
        return round(self._float_pos) % n

    def current_text(self) -> str:
        """当前选中项文本。"""
        if not self._items:
            return ""
        return self._items[self.current_index]

    def set_current_index(self, index: int) -> None:
        """程序化设置选中索引。"""
        self._anim_timer.stop()
        self._float_pos = float(index)
        self._prev_index = self.current_index
        self.update()

    # ================================================================
    #  绘制
    # ================================================================
    def paintEvent(self, event) -> None:
        """自定义绘制：循环数值列表 + 中心高亮线 + 渐变遮罩。"""
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # type: ignore

        w: int = self.width()
        h: int = self.height()
        center_y: float = h / 2.0
        n: int = len(self._items)

        # 填充背景
        painter.fillRect(self.rect(), QColor(self._bg_color))

        if n == 0:
            return

        center_idx: int = round(self._float_pos)
        offset: float = center_idx - self._float_pos  # -0.5 ~ 0.5

        # 可见范围：覆盖 widget 高度 + 上下各一个 item_height 的余量
        visible_range: int = int((h / 2 + self._item_height) / self._item_height) + 2

        # 解析文字颜色
        tc: QColor = QColor(self._text_color)

        for vi in range(center_idx - visible_range, center_idx + visible_range + 1):
            wrapped_idx: int = vi % n
            item_y: float = center_y + (vi - center_idx + offset) * self._item_height

            # 跳过完全不可见的项
            if item_y < -self._item_height or item_y > h + self._item_height:
                continue

            dist: float = abs(vi - center_idx + offset)
            dist_clamped: float = min(dist, 2.5)
            ratio: float = dist_clamped / 2.5  # 0.0=中心, 1.0=边缘及以外

            font_size: int = max(12, 28 - int(16 * ratio))
            opacity: float = max(0.12, 1.0 - 0.88 * (ratio ** 1.3))

            painter.setFont(QFont("Arial", font_size))
            painter.setPen(QColor(tc.red(), tc.green(), tc.blue(), int(255 * opacity)))

            text_rect: QRectF = QRectF(
                0, item_y - self._item_height / 2, w, self._item_height
            )
            painter.drawText(text_rect, Qt.AlignCenter, self._items[wrapped_idx])  # type: ignore

        # 中心指示线（选中项的上下边界）
        line_y_top: float = center_y - self._item_height / 2
        line_y_bot: float = center_y + self._item_height / 2
        line_margin: float = w * 0.12
        line_w: float = w - 2 * line_margin

        pen: QPen = QPen(QColor(tc.red(), tc.green(), tc.blue(), 50))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(line_margin, line_y_top),
            QPointF(line_margin + line_w, line_y_top),
        )
        painter.drawLine(
            QPointF(line_margin, line_y_bot),
            QPointF(line_margin + line_w, line_y_bot),
        )

        # 渐变遮罩：顶部/底部淡出
        fade_h: int = int(h * 0.35)

        top_grad: QLinearGradient = QLinearGradient(0, 0, 0, fade_h)
        top_grad.setColorAt(0.0, QColor(self._bg_color))
        top_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(0, 0, w, fade_h), top_grad)

        bot_grad: QLinearGradient = QLinearGradient(0, h - fade_h, 0, h)
        bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1.0, QColor(self._bg_color))
        painter.fillRect(QRectF(0, h - fade_h, w, fade_h), bot_grad)

    # ================================================================
    #  鼠标拖拽
    # ================================================================
    def mousePressEvent(self, event) -> None:
        """记录拖拽起点，停止动画。"""
        self._anim_timer.stop()
        self._is_dragging = True
        self._has_moved = False
        self._drag_start_y = event.position().y()
        self._drag_start_pos = self._float_pos

    def mouseMoveEvent(self, event) -> None:
        """拖拽中实时更新浮点位置（无边界限制，支持循环滚动）。"""
        if not self._is_dragging:
            return
        dy: float = self._drag_start_y - event.position().y()
        # 移动超过阈值才标记为拖拽（过滤手抖）
        if abs(dy) > 4:
            self._has_moved = True
        if not self._has_moved:
            return
        self._float_pos = self._drag_start_pos + dy / self._item_height

        ci: int = self.current_index
        if ci != self._prev_index:
            self._prev_index = ci
            self.selection_changed.emit(ci)

        self.update()

    def mouseReleaseEvent(self, event) -> None:
        """松开后吸附：点击则上下滚动一项，拖拽则吸附到最近项（均支持循环）。"""
        self._is_dragging = False
        if not self._items:
            return

        if not self._has_moved:
            # 纯点击（无拖拽）：点击上半区 → 上一项，点击下半区 → 下一项
            click_y: float = event.position().y()
            center_y: float = self.height() / 2.0
            if click_y < center_y:
                target = round(self._float_pos) - 1
            else:
                target = round(self._float_pos) + 1
        else:
            # 拖拽后吸附到最近项
            target = round(self._float_pos)
        self._start_snap(target)

    # ================================================================
    #  鼠标滚轮
    # ================================================================
    def wheelEvent(self, event) -> None:
        """滚轮滚轮一格，吸附到邻近项（支持循环）。"""
        self._anim_timer.stop()
        delta: int = event.angleDelta().y()
        direction: int = 1 if delta < 0 else -1
        self._float_pos += direction * 0.8
        self._start_snap(round(self._float_pos))
        self.update()

    # ================================================================
    #  吸附动画（缓出三次方）
    # ================================================================
    def _start_snap(self, target: int) -> None:
        """启动吸附动画。"""
        self._anim_start_pos = self._float_pos
        self._anim_target_pos = float(target)
        self._anim_frame = 0
        self._anim_timer.start()

    def _animate_step(self) -> None:
        """动画每帧更新（约 60fps）。"""
        self._anim_frame += 1
        t: float = self._anim_frame / self._anim_total_frames
        eased: float = 1.0 - (1.0 - t) ** 3  # ease-out cubic
        self._float_pos = (
            self._anim_start_pos
            + (self._anim_target_pos - self._anim_start_pos) * eased
        )

        if self._anim_frame >= self._anim_total_frames:
            self._anim_timer.stop()
            self._float_pos = self._anim_target_pos
            ci: int = self.current_index
            if ci != self._prev_index:
                self._prev_index = ci
                self.selection_changed.emit(ci)

        self.update()


class TimeWheelPicker(QDialog):
    """
    # TimeWheelPicker — 滚轮时间选择弹窗

    用于编辑起止时间的现代化弹窗，包含：
      - 4 列 iOS 风格滚轮（开始-时 / 开始-分 / 结束-时 / 结束-分）
      - 分隔符（: 和 —）
      - 确认 / 取消 按钮

    支持自定义颜色方案，可用于考试模式（墨绿背景）或设置页面（主题色）。
    ---

    信号：
      time_confirmed(str, str) — 编辑完成，携带 (start_time, finish_time)
    """

    time_confirmed = Signal(str, str)

    def __init__(self, start_time: str, finish_time: str,
                 parent: Optional[QWidget] = None,
                 bg_color: str = '#0f261e',
                 text_color: str = '#FFFFFF') -> None:
        """
        初始化滚轮时间选择器。

        参数：
            start_time  (str)：当前开始时间 HH:MM
            finish_time (str)：当前结束时间 HH:MM
            parent      (QWidget | None)：父窗口
            bg_color    (str)：背景颜色（默认墨绿色 #0f261e）
            text_color  (str)：文字颜色（默认白色 #FFFFFF）
        """
        super().__init__(parent)
        self._bg_color: str = bg_color
        self._text_color: str = text_color

        self.setWindowTitle('时间设置')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowStaysOnTopHint         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
            | Qt.WindowMinimizeButtonHint     # type: ignore
            | Qt.WindowMaximizeButtonHint     # type: ignore
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)    # type: ignore
        self.setModal(True)

        # ---- 解析初始时间 ----
        sh_str, sm_str = start_time.split(':')
        fh_str, fm_str = finish_time.split(':')
        sh: int = int(sh_str)
        sm: int = int(sm_str)
        fh: int = int(fh_str)
        fm: int = int(fm_str)

        # ---- 构建 UI ----
        self._setup_ui(sh, sm, fh, fm)
        logger.info("TimeWheelPicker 初始化完成")

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self, sh: int, sm: int, fh: int, fm: int) -> None:
        """构造弹窗布局。"""
        bg: str = self._bg_color
        tc: str = self._text_color

        # 外层布局（无 margin，由容器提供内边距）
        outer: QVBoxLayout = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 圆角容器
        container: QFrame = QFrame(self)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.08);
            }}
        """)

        inner: QVBoxLayout = QVBoxLayout(container)
        inner.setSpacing(10)
        inner.setContentsMargins(16, 8, 16, 16)

        # ---- 滚轮列 ----
        hour_items: List[str] = [f"{i:02d}" for i in range(24)]
        min_items: List[str] = [f"{i:02d}" for i in range(60)]

        wheels_row: QHBoxLayout = QHBoxLayout()
        wheels_row.setSpacing(0)
        wheels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        self._start_hour: WheelColumn = WheelColumn(
            hour_items, sh, bg_color=bg, text_color=tc
        )
        self._start_hour.setFixedWidth(60)
        wheels_row.addWidget(self._start_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._start_min: WheelColumn = WheelColumn(
            min_items, sm, bg_color=bg, text_color=tc
        )
        self._start_min.setFixedWidth(60)
        wheels_row.addWidget(self._start_min)
        wheels_row.addWidget(self._make_sep('—'))

        self._end_hour: WheelColumn = WheelColumn(
            hour_items, fh, bg_color=bg, text_color=tc
        )
        self._end_hour.setFixedWidth(60)
        wheels_row.addWidget(self._end_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._end_min: WheelColumn = WheelColumn(
            min_items, fm, bg_color=bg, text_color=tc
        )
        self._end_min.setFixedWidth(60)
        wheels_row.addWidget(self._end_min)

        inner.addLayout(wheels_row)

        # ---- 分组标签 ----
        labels_row: QHBoxLayout = QHBoxLayout()
        labels_row.setSpacing(0)
        labels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        label_alpha: str = "rgba(255,255,255,0.40)"
        if tc != '#FFFFFF':
            label_alpha = "rgba(0,0,0,0.40)"

        start_lbl: QLabel = QLabel('开始时间')
        start_lbl.setFont(QFont('Arial', 11))
        start_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        start_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        start_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(start_lbl)

        labels_row.addSpacing(16)

        end_lbl: QLabel = QLabel('结束时间')
        end_lbl.setFont(QFont('Arial', 11))
        end_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        end_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        end_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(end_lbl)

        inner.addLayout(labels_row)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(20)
        btn_row.setAlignment(Qt.AlignCenter)  # type: ignore

        # 按钮透明度适配
        btn_dim: str = "rgba(255,255,255,0.50)" if tc == '#FFFFFF' else "rgba(0,0,0,0.45)"
        btn_border: str = "rgba(255,255,255,0.12)" if tc == '#FFFFFF' else "rgba(0,0,0,0.12)"
        btn_hover_border: str = "rgba(255,255,255,0.30)" if tc == '#FFFFFF' else "rgba(0,0,0,0.30)"
        btn_pressed: str = "rgba(255,255,255,0.05)" if tc == '#FFFFFF' else "rgba(0,0,0,0.05)"

        cancel_btn: QPushButton = QPushButton('取消')
        cancel_btn.setFont(QFont('Arial', 14))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                color: {btn_dim};
                background: transparent;
                border: 1px solid {btn_border};
                border-radius: 8px;
                padding: 8px 28px;
            }}
            QPushButton:hover {{
                color: {tc};
                border-color: {btn_hover_border};
            }}
            QPushButton:pressed {{
                background-color: {btn_pressed};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        accent: str = '#1a4a32' if tc == '#FFFFFF' else '#1976D2'
        accent_hover: str = '#235a40' if tc == '#FFFFFF' else '#1565C0'
        accent_pressed: str = '#0f261e' if tc == '#FFFFFF' else '#0D47A1'

        confirm_btn: QPushButton = QPushButton('确认')
        confirm_btn.setFont(QFont('Arial', 14, QFont.Bold)) # type: ignore
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                color: {tc if tc == '#FFFFFF' else '#FFFFFF'};
                background-color: {accent};
                border: none;
                border-radius: 8px;
                padding: 8px 28px;
            }}
            QPushButton:hover {{
                background-color: {accent_hover};
            }}
            QPushButton:pressed {{
                background-color: {accent_pressed};
            }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        inner.addSpacing(2)
        inner.addLayout(btn_row)

        outer.addWidget(container)
        self.setLayout(outer)
        self.setFixedSize(self.sizeHint())

    def _make_sep(self, text: str) -> QLabel:
        """创建分隔符标签（: 或 —）。"""
        sep_alpha: str = "rgba(255,255,255,0.35)" if self._text_color == '#FFFFFF' else "rgba(0,0,0,0.30)"
        label: QLabel = QLabel(text)
        label.setFont(QFont('Arial', 22))
        label.setStyleSheet(
            f"color: {sep_alpha}; background: transparent;"
        )
        label.setAlignment(Qt.AlignCenter)  # type: ignore
        label.setFixedWidth(16)
        return label

    # ================================================================
    #  确认 / 键盘
    # ================================================================
    def _on_confirm(self) -> None:
        """读取 4 个滚轮的值，发射 time_confirmed 信号并关闭。"""
        st: str = (
            f"{self._start_hour.current_index:02d}:"
            f"{self._start_min.current_index:02d}"
        )
        ft: str = (
            f"{self._end_hour.current_index:02d}:"
            f"{self._end_min.current_index:02d}"
        )
        logger.info(f"滚轮时间选择器确认：{st} — {ft}")
        self.time_confirmed.emit(st, ft)
        self.accept()

    def keyPressEvent(self, event) -> None:
        """键盘快捷键：Esc 取消，Enter 确认。"""
        if event.key() == Qt.Key_Escape:   # type: ignore
            self.reject()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):  # type: ignore
            self._on_confirm()
        else:
            super().keyPressEvent(event)
