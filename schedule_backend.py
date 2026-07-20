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
from typing import Callable, List, Optional

from PySide6.QtCore import QTimer, QTime
from PySide6.QtWidgets import QApplication, QWidget

# 获取本模块的 logger，日志将传播到 main.py 配置的根 logger
logger: logging.Logger = logging.getLogger(__name__)


# ==================== 时间管理类 ====================

class TimeManager:
    """
    # TimeManager — 时间管理类

    负责实时时间的获取与管理。
    内部使用 QTimer 每秒触发一次，通过回调函数将当前时间传递给外部。
    ---

    使用方式：
        tm = TimeManager()
        tm.start(lambda time_str: frontend.update_time_display(time_str))
        # ... 程序结束时调用 tm.stop()

    对外接口：
      - start(callback)：   启动定时器，传入回调函数接收时间字符串
      - stop()：            停止定时器
      - get_current_time()：手动获取当前时间字符串（不依赖定时器）
    """

    def __init__(self) -> None:
        """
        初始化时间管理器。
        -----------------
        创建 QTimer 实例并设置间隔为 1000ms（1 秒）。
        定时器在调用 start() 之前不会启动。
        """
        logger.info("TimeManager 初始化：创建 QTimer（间隔 1000ms）")
        # ===== 创建定时器 =====
        # QTimer 是 Qt 的定时器类，每隔指定毫秒数发射 timeout 信号
        self._timer: QTimer = QTimer()
        self._timer.setInterval(1000)  # 1000 毫秒 = 1 秒

        # ===== 回调函数引用 =====
        # 外部通过 start(callback) 传入的回调函数存储在这里
        # None 表示尚未设置回调（定时器未启动）
        self._callback: Optional[Callable[[str], None]] = None
        logger.info("TimeManager 初始化完成")

    # ================================================================
    #  公开方法1：启动定时器
    # ================================================================
    def start(self, callback: Callable[[str], None]) -> None:
        """
        启动定时器，开始每秒更新时间。
        ---------------------------
        参数：
            callback（Callable[[str], None]）：
                回调函数，签名为 callback(time_str: str)
                每次定时器触发时，会将当前时间字符串（格式 HH:MM:SS）
                作为参数传入回调函数。

        使用示例：
            def on_time_update(time_str):
                print(f"当前时间：{time_str}")

            tm = TimeManager()
            tm.start(on_time_update)

        说明：
          - 调用 start() 后会立即触发一次回调（不等 1 秒），确保界面立刻显示时间
          - 如果之前已经启动过，会先停止旧定时器再启动新的
        """
        # 如果已有回调在运行，先停止
        if self._callback is not None:
            logger.info("检测到已有回调在运行，先停止旧定时器")
            self.stop()

        # 保存回调引用
        self._callback = callback
        logger.info(f"TimeManager 启动：回调函数已注册，定时器间隔 1000ms")

        # 连接定时器的 timeout 信号到内部处理函数
        self._timer.timeout.connect(self._on_timeout)

        # 启动定时器
        self._timer.start()
        logger.info("QTimer 已启动，立即触发首次时间回调")

        # 立即触发一次，不等 1 秒 —— 确保界面立刻显示当前时间
        self._on_timeout()

    # ================================================================
    #  公开方法2：停止定时器
    # ================================================================
    def stop(self) -> None:
        """
        停止定时器，断开信号连接。
        ------------------------
        调用时机：
          - 程序退出前
          - 需要暂停时间更新时

        说明：
          - 安全地断开 timeout 信号与回调的连接，避免内存泄漏
          - 多次调用 stop() 不会出错
        """
        logger.info("TimeManager 停止：正在停止定时器...")
        # 停止定时器
        self._timer.stop()

        # 断开信号连接（防止重复连接导致多次触发）
        if self._callback is not None:
            try:
                self._timer.timeout.disconnect(self._on_timeout)
                logger.info("已断开 timeout 信号连接")
            except (TypeError, RuntimeError):
                # 信号尚未连接或已断开，忽略异常
                logger.debug("timeout 信号已断开或未连接，跳过")
                pass

        # 清空回调引用
        self._callback = None
        logger.info("TimeManager 已停止，回调引用已清空")

    # ================================================================
    #  公开方法3：手动获取当前时间
    # ================================================================
    def get_current_time(self) -> str:
        """
        手动获取当前时间字符串（不依赖定时器）。
        -------------------------------------
        返回值：
            str：当前时间，格式为 HH:MM:SS（24 小时制）
                 示例："14:30:05"

        使用场景：
          - 需要在定时器未启动时获取一次当前时间
          - 其他模块直接调用获取时间，不需要走回调
        """
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
          2. 调用外部传入的回调函数，将时间传递出去
        """
        if self._callback is not None:
            current_time = self.get_current_time()
            logger.debug(f"定时器触发，当前时间：{current_time}")
            self._callback(current_time)


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

    def handle(self, action: str, main_window,
               subject_window=None) -> None:
        """
        处理快捷编辑相关的动作。
        ----------------------
        参数：
            action         （str）：                  动作标识符
            main_window    （ScheduleMainWindow）：   课表主窗口引用
            subject_window （SubjectSelectWindow）：  快捷编辑子窗口引用（可选）
        """
        self._logger.info(f"[QuickEdit] 收到动作: {action}")

        if action == "quick_edit_opened":
            self._on_quick_edit_opened(main_window, subject_window)

        elif action.startswith("subject:"):
            subject_name: str = action.split(":", 1)[1]
            self._on_subject_selected(main_window, subject_name)

        elif action == "move_up":
            self._on_move(main_window, -1, subject_window)

        elif action == "move_down":
            self._on_move(main_window, 1, subject_window)

        elif action == "move_double_up":
            self._on_move(main_window, -2, subject_window)

        elif action == "move_double_down":
            self._on_move(main_window, 2, subject_window)

        elif action == "confirm":
            self._on_confirm(main_window, subject_window)

        elif action == "quick_edit_closed":
            self._on_quick_edit_closed(main_window)

        elif action.startswith("cursor_info:"):
            # 主窗口发来的光标信息 → 转发给快捷编辑窗口显示
            self._on_cursor_info(action, subject_window)

        else:
            self._logger.debug(f"[QuickEdit] 不处理的动作: {action}")

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
        """确认编辑 → 停止光标闪烁并退出快捷编辑界面。"""
        self._logger.info("[QuickEdit] 确认编辑，停止光标闪烁并关闭快捷编辑窗口")
        main_window.stop_cursor_blink()
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
    #  光标信息回传
    # ================================================================
    def _on_cursor_info(self, action: str, subject_window=None) -> None:
        """
        收到主窗口发来的光标信息 → 更新快捷编辑窗口的状态栏。
        格式：cursor_info:<index>:<subject_text>
        """
        parts = action.split(":", 2)
        if len(parts) >= 3:
            try:
                index: int = int(parts[1])
            except ValueError:
                return
            subject_text: str = parts[2]
            self._logger.debug(f"[QuickEdit] 光标信息：第{index + 1}节 '{subject_text}'")
            if subject_window is not None:
                subject_window.update_cursor_info(index, subject_text)


# ==================== 后端信号处理类 ====================

class ScheduleBackend:
    """
    # ScheduleBackend — 后端信号处理器

    接收前端统一的后端信号（backend_signal），根据动作标识符
    分派给对应的业务逻辑处理。
    ---

    对外接口：
      - handle_action(action, frontend, app)：处理来自前端的动作信号

    动作标识符说明：
      - "close"              → 关闭所有窗口并退出程序
      - "quick_edit_opened"  → 快捷编辑窗口已打开
      - "subject:<科目名>"   → 用户选择了一个科目
      - "move_up"            → 向上移动选择
      - "move_down"          → 向下移动选择
      - "move_double_up"     → 倍速向上移动（2×向上）
      - "move_double_down"   → 倍速向下移动（2×向下）
      - "confirm"            → 确认操作
      - "quick_edit_closed"  → 快捷编辑窗口关闭（点击 ✕）
    """

    def __init__(self) -> None:
        """初始化后端信号处理器。"""
        self._logger: logging.Logger = logging.getLogger(__name__)
        # 快捷编辑专属处理器
        self.quick_edit: QuickEditHandler = QuickEditHandler()
        self._logger.info("ScheduleBackend 初始化完成")

    def handle_action(self, action: str, main_window,
                       time_window, fullscreen_window,
                       app: QApplication,
                       subject_window=None) -> None:
        """
        处理来自前端的统一信号。
        ----------------------
        参数：
            action             （str）：                动作标识符
            main_window        （ScheduleMainWindow）： 课表主窗口引用
            time_window        （TimeWindow）：         时间窗口引用
            fullscreen_window  （FullscreenTimeWindow）：全屏时间窗口引用
            app                （QApplication）：       QApplication 实例
            subject_window     （SubjectSelectWindow）：快捷编辑窗口引用（可选）

        说明：
          快捷编辑类动作委托给 QuickEditHandler 处理，
          系统类动作（关闭/全屏/设置）在本类中直接处理。
        """
        self._logger.info(f"[后端] 收到动作: {action}")

        # ---- 快捷编辑相关 → 委托 QuickEditHandler ----
        if action in ("quick_edit_opened", "confirm", "quick_edit_closed") or \
           action.startswith("subject:") or \
           action.startswith("cursor_info:") or \
           action in ("move_up", "move_down", "move_double_up", "move_double_down"):
            self.quick_edit.handle(action, main_window, subject_window)
            return

        # ---- 系统操作 → 本类处理 ----
        if action == "close":
            # 先停止光标闪烁
            main_window.stop_cursor_blink()
            WindowHelper.close_all(
                [time_window, main_window, fullscreen_window], app
            )
        elif action == "fullscreen_time":
            self._logger.info(f"[后端] 全屏时间 — 显示全屏时间窗口")
            fullscreen_window.show_fullscreen()
        elif action == "settings":
            self._logger.info(f"[后端] 设置")
        else:
            self._logger.warning(f"[后端] 未知动作: {action}")
