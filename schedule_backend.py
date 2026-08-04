"""
╔══════════════════════════════════════════════════════════════════════════╗
║               📅 电子课表系统 —— schedule_backend.py（后端）              ║
║                      （前后端分离架构 · 后端部分）                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 类说明
═══════════════════════════════════════════════════════════════════════════
  TimeManager  — 时间管理类：负责实时时间的获取，通过 QTimer 定时触发
  WindowHelper — 辅助功能类：负责关闭所有窗口并退出程序

📌 设计理念
═══════════════════════════════════════════════════════════════════════════
  后端 ≈ 餐厅的厨师
  - 厨师只负责：做菜（处理业务逻辑）
  - 厨师不管：客人坐在哪、盘子长什么样（那是服务员/前端的事）

  TimeManager ≈ 厨房里的计时器，到点了喊一声"时间到了！"
  WindowHelper ≈ 打烊时关灯锁门的帮手
"""

import logging
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtCore import QTimer, QTime, Signal, QObject
from PySide6.QtWidgets import QApplication, QWidget

from schedule_actions import ActionMessage, ActionType

if TYPE_CHECKING:
    from schedule_config import DebugConfig

# 获取本模块的 logger，日志将传播到 main.py 配置的根 logger
logger: logging.Logger = logging.getLogger(__name__)


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
                       subject_window=None) -> None:
        """
        处理来自前端的统一信号。
        ----------------------
        参数：
            msg                （ActionMessage）：      结构化动作消息
            main_window        （ScheduleMainWindow）： 课表主窗口引用
            time_window        （TimeWindow）：         时间窗口引用
            fullscreen_window  （FullscreenTimeWindow）：全屏时间窗口引用
            app                （QApplication）：       QApplication 实例
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
                        ActionType.WEEK_CHANGED):
            self.quick_edit.handle(msg, main_window, subject_window)
            return

        # ---- 系统操作 → 本类处理 ----
        if msg.type == ActionType.CLOSE:
            # 先停止光标闪烁
            main_window.stop_cursor_blink()
            WindowHelper.close_all(
                [time_window, main_window, fullscreen_window], app
            )
        elif msg.type == ActionType.FULLSCREEN_TIME:
            self._logger.info("[后端] 全屏时间 — 显示全屏时间窗口")
            fullscreen_window.show_fullscreen()
        elif msg.type == ActionType.SETTINGS:
            self._logger.info("[后端] 设置")
        else:
            self._logger.warning(f"[后端] 未知动作: {msg.type.value}")
