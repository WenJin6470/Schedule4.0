"""
╔══════════════════════════════════════════════════════════════════════════╗
║           📅 电子课表系统 —— main.py（程序入口 + 连接器）                 ║
║                     （前后端分离架构 · 中间层）                            ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
main.py 是整个程序的入口，也是前后端分离架构中的"中间层"。

它的唯一工作就是"牵线搭桥"——把前端的信号和后端的方法连接起来。

📌 四大窗口模块
═══════════════════════════════════════════════════════════════════════════
  schedule_config.py   — ThemeManager + ScheduleDataManager + ThemedWidget
  schedule_time.py     — TimeWindow + FullscreenTimeWindow（时间模块）
  schedule_frontend.py — ScheduleMainWindow（课表主窗口）
  schedule_quick_edit.py — SubjectSelectWindow（快捷编辑模块）
  schedule_settings.py   — SettingsWindow（设置模块）

📌 运行方式
═══════════════════════════════════════════════════════════════════════════
  venv\\Scripts\\python main.py
"""

import logging
import os
import sys
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# ================================================================
# ★ 导入主题、前端口、后端逻辑 ★
# ================================================================
from schedule_config import (
    ThemeManager, ScheduleDataManager, DebugConfig, SwapManager,
    DisplayRulesManager,
)
from schedule_time import TimeWindow, FullscreenTimeWindow, ExamFullscreenWindow
from schedule_frontend import ScheduleMainWindow
from schedule_backend import TimeManager, ScheduleBackend, WindowHelper, LogManager
from knotlink_bridge import KnotLinkBridge


# ================================================================
#  彩色日志格式化器 —— 终端输出按级别着色
# ================================================================
class ColoredFormatter(logging.Formatter):
    """带 ANSI 颜色的日志格式化器，仅用于终端 StreamHandler。"""

    COLORS: dict = {
        'DEBUG':    '\033[93m',
        'INFO':     '\033[36m',
        'WARNING':  '\033[38;5;214m',
        'ERROR':    '\033[91m',
        'CRITICAL': '\033[41m\033[97m',
    }
    RESET: str = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        color: str = self.COLORS.get(record.levelname, '')
        formatted: str = super().format(record)
        if color:
            formatted = f"{color}{formatted}{self.RESET}"
        return formatted


# ================================================================
#  主函数：创建窗口、创建后端、连接信号
# ================================================================
def main() -> None:
    """
    程序入口函数。
    ------------
    执行顺序：
      1. 配置日志系统
      2. 创建 QApplication
      3. 创建 ThemeManager（读取 INI 配置 → 主题颜色就绪）
      3b. 创建 ScheduleDataManager（读取课程表和时间表 JSON）
      4. 创建各前端窗口（时间窗口、主窗口、全屏时间窗口）
      5. 创建后端实例（TimeManager、ScheduleBackend）
      6. 连接信号与槽
      7. 显示窗口
      8. 启动事件循环
    """
    # ================================================================
    #  第1步：配置日志系统
    # ================================================================
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    log_dir: str = os.path.join(script_dir, 'log')
    os.makedirs(log_dir, exist_ok=True)

    log_filename: str = f"schedule_{datetime.now().strftime('%Y-%m-%d')}.log"
    log_filepath: str = os.path.join(log_dir, log_filename)

    log_format: str = '%(asctime)s [%(levelname)-7s] %(name)s: %(message)s'
    date_format: str = '%Y-%m-%d %H:%M:%S'

    stream_handler: logging.StreamHandler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(ColoredFormatter(log_format, datefmt=date_format))

    file_handler: logging.FileHandler = logging.FileHandler(
        log_filepath, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

    root_logger: logging.Logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    logger: logging.Logger = logging.getLogger('main')
    logger.info(f"日志系统已就绪，日志文件：{log_filepath}")

    # ================================================================
    #  第2步：创建 QApplication
    # ================================================================
    logger.info("正在创建 QApplication...")
    app: QApplication = QApplication(sys.argv)
    logger.info("QApplication 创建成功")

    # ================================================================
    #  第3步：创建 ThemeManager（读取配置 + 应用主题）
    # ================================================================
    logger.info("正在创建 ThemeManager...")
    theme_manager: ThemeManager = ThemeManager()
    logger.info(f"ThemeManager 创建完成：theme={theme_manager.theme}")

    # ================================================================
    #  第3.5步：清理过期日志（在 ThemeManager 读取 log_retention_days 之后）
    # ================================================================
    LogManager.cleanup_old_logs(log_dir, theme_manager.log_retention_days, logger)

    #  3c. 创建 DebugConfig（读取调试配置，提前创建供显示规则解析使用）
    logger.info("正在创建 DebugConfig...")
    debug_config: DebugConfig = DebugConfig()
    logger.info(f"DebugConfig 创建完成：enabled={debug_config.enabled}")

    #  3d. 解析显示规则：命中则覆盖时间表/课程表路径并写回 INI
    logger.info("正在解析显示规则...")
    display_rules: DisplayRulesManager = DisplayRulesManager()
    resolved = display_rules.resolve_for_today(debug_config)
    if resolved is not None:
        resolved_timetable, resolved_curriculum = resolved
        curriculum_path: str = resolved_curriculum
        timetable_path: str = resolved_timetable
        theme_manager.curriculum_path = curriculum_path
        theme_manager.timetable_path = timetable_path
        display_rules.persist_resolved_paths(curriculum_path, timetable_path)
        logger.info("显示规则解析命中，已切换到对应时间表/课程表")
    else:
        curriculum_path = theme_manager.curriculum_path
        timetable_path = theme_manager.timetable_path
        logger.info("显示规则未命中，沿用默认时间表/课程表")
    logger.info("显示规则解析完成")

    #  3b. 创建 ScheduleDataManager（读取课程表和时间表 JSON）
    logger.info("正在创建 ScheduleDataManager...")
    schedule_data: ScheduleDataManager = ScheduleDataManager(
        curriculum_path=curriculum_path,
        timetable_path=timetable_path,
    )
    logger.info("ScheduleDataManager 创建完成")

    #  3e. 处理换课记录：应用今日换课、清理过期记录
    logger.info("正在处理换课记录...")
    swap_manager: SwapManager = SwapManager()
    swap_manager.process_on_startup(schedule_data.curriculum_data, debug_config)
    logger.info("换课记录处理完成")

    # ================================================================
    #  第4步：创建前端窗口
    #  ★ 启动优化：先创建轻量级的 TimeWindow 并立即显示，
    #  让用户第一时间看到时间；重量级的主窗口延后构造，
    #  避免用户感知到"点了图标没反应"的空白期。
    # ================================================================
    # 4a. 时间窗口（屏幕右上角浮动时钟）— 轻量，优先创建并显示
    logger.info("正在创建 TimeWindow...")
    time_window: TimeWindow = TimeWindow(theme_manager)
    logger.info("TimeWindow 创建完成")

    # ★ 启动优化：立即显示 TimeWindow 并刷新界面，
    # 让用户瞬间看到置顶时间，无需等待主窗口构造完成。
    time_window.show()
    app.processEvents()  # 强制 Qt 立即渲染 TimeWindow
    logger.info("TimeWindow 已提前显示（启动优化：用户可立即看到时间）")

    # 4b. 课表主窗口（课时标签 + 四按钮栏）— 重量级，延后构造
    logger.info("正在创建 ScheduleMainWindow...")
    main_window: ScheduleMainWindow = ScheduleMainWindow(theme_manager, schedule_data, debug_config)
    logger.info("ScheduleMainWindow 创建完成")

    # 4c. 全屏时间窗口（默认隐藏，支持考试/创意模式）
    logger.info("正在创建 FullscreenTimeWindow...")
    fullscreen_window: FullscreenTimeWindow = FullscreenTimeWindow(theme_manager)
    logger.info("FullscreenTimeWindow 创建完成")

    # 4d. 考试模式全屏窗口（默认隐藏）
    logger.info("正在创建 ExamFullscreenWindow...")
    exam_window: ExamFullscreenWindow = ExamFullscreenWindow(theme_manager)
    logger.info("ExamFullscreenWindow 创建完成")

    # ================================================================
    #  第5步：创建后端实例
    # ================================================================
    logger.info("正在创建后端实例...")
    time_manager: TimeManager = TimeManager(debug_config=debug_config)
    backend_handler: ScheduleBackend = ScheduleBackend()
    logger.info("后端实例创建完成")

    # ================================================================
    #  第6步：连接信号和槽
    #   连接1：TimeManager.time_tick → 置顶时间窗口（订阅者1）
    #   连接2：TimeManager.time_tick → 全屏时间窗口（订阅者2，修复全屏时间bug）
    #   连接3：全屏时间关闭信号 → 隐藏窗口
    #   连接4：主窗口统一信号 → 后端处理器
    # ================================================================

    # ----- 连接1：TimeManager.time_tick → 置顶时间窗口 -----
    logger.info("连接信号：TimeManager.time_tick → TimeWindow.update_time_display()")
    time_manager.time_tick.connect(time_window.update_time_display)

    # ----- 连接2：TimeManager.time_tick → 全屏时间窗口 -----
    logger.info("连接信号：TimeManager.time_tick → FullscreenTimeWindow.update_time_display()")
    time_manager.time_tick.connect(fullscreen_window.update_time_display)

    # ----- 连接2c：TimeManager.time_tick → 考试模式全屏窗口 -----
    logger.info("连接信号：TimeManager.time_tick → ExamFullscreenWindow.update_time_display()")
    time_manager.time_tick.connect(exam_window.update_time_display)

    # ----- 连接2b：TimeManager.time_tick → 主窗口科目标签高亮 -----
    logger.info("连接信号：TimeManager.time_tick → ScheduleMainWindow.update_period_highlight()")
    time_manager.time_tick.connect(main_window.update_period_highlight)

    # ----- TimeManager 启动（不再需要传入 callback）-----
    time_manager.start()
    logger.info("TimeManager 定时器已启动，时间信号广播中")

    # ----- 连接3：全屏时间窗口关闭 → 隐藏 + 恢复 TimeWindow 置顶 -----
    fullscreen_window.close_requested.connect(
        lambda: (
            fullscreen_window.hide(),
            time_window.set_always_on_top(True),
        )
    )

    # ----- 连接3b：考试模式全屏窗口关闭 → 隐藏 + 恢复 TimeWindow 置顶 -----
    exam_window.close_requested.connect(
        lambda: (
            exam_window.hide(),
            time_window.set_always_on_top(True),
        )
    )

    # ----- 连接4：主窗口统一信号 → 后端 -----
    logger.info("连接信号：ScheduleMainWindow.backend_signal → ScheduleBackend")
    main_window.backend_signal.connect(
        lambda msg: backend_handler.handle_action(
            msg, main_window, time_window, fullscreen_window, app,
            exam_window=exam_window,
            subject_window=main_window._subject_window,
        )
    )
    logger.info("统一后端信号已连接")

    # ================================================================
    #  第7步：显示窗口
    #  ★ 注意：TimeWindow 已在第4步提前显示，这里只需显示主窗口
    # ================================================================
    logger.info("正在显示主窗口...")
    main_window.show()
    # 强制处理事件：确保置顶时间窗口和主窗口的内容都真正渲染出来
    app.processEvents()
    # fullscreen_window 默认隐藏，通过全屏时间按钮触发显示
    logger.info("窗口内容已显示")

    # ================================================================
    #  第6.5步：延迟初始化 KnotLink 桥接（窗口内容显示后再进行）
    # ================================================================
    logger.info("KnotLink 桥接已安排，将在窗口内容显示后初始化...")

    def _init_knotlink() -> None:
        """窗口内容显示后初始化 KnotLink 桥接，避免阻塞启动流程。"""
        logger.info("正在初始化 KnotLink 桥接...")
        KnotLinkBridge.setup(
            time_manager=time_manager,
            schedule_data=schedule_data,
            main_window=main_window,
            time_window=time_window,
            fullscreen_window=fullscreen_window,
            exam_window=exam_window,
            debug_config=debug_config,
        )
        logger.info("KnotLink 桥接初始化完成")

    QTimer.singleShot(0, _init_knotlink)

    logger.info("进入事件循环")

    # ================================================================
    #  第8步：启动事件循环
    # ================================================================
    exit_code: int = app.exec()
    logger.info(f"事件循环已退出（exit_code={exit_code}），程序结束")
    sys.exit(exit_code)


# ================================================================
#  程序入口
# ================================================================
if __name__ == "__main__":
    main()
