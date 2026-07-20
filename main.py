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
  schedule_theme.py    — ThemeManager + ThemedWidget（主题与基础控件）
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

from PySide6.QtWidgets import QApplication

# ================================================================
# ★ 导入主题、前端口、后端逻辑 ★
# ================================================================
from schedule_theme import ThemeManager
from schedule_time import TimeWindow, FullscreenTimeWindow
from schedule_frontend import ScheduleMainWindow
from schedule_backend import TimeManager, ScheduleBackend, WindowHelper


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
      3. 创建 ThemeManager（读取配置 → 主题颜色就绪）
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
    logger.info(f"ThemeManager 创建完成：theme={theme_manager.theme}, "
                f"period_count={theme_manager.period_count}")

    # ================================================================
    #  第4步：创建前端窗口
    # ================================================================
    # 4a. 时间窗口（屏幕右上角浮动时钟）
    logger.info("正在创建 TimeWindow...")
    time_window: TimeWindow = TimeWindow(theme_manager)
    logger.info("TimeWindow 创建完成")

    # 4b. 课表主窗口（课时标签 + 四按钮栏）
    logger.info("正在创建 ScheduleMainWindow...")
    main_window: ScheduleMainWindow = ScheduleMainWindow(theme_manager)
    logger.info("ScheduleMainWindow 创建完成")

    # 4c. 全屏时间窗口（默认隐藏，待后续实现）
    logger.info("正在创建 FullscreenTimeWindow...")
    fullscreen_window: FullscreenTimeWindow = FullscreenTimeWindow(theme_manager)
    logger.info("FullscreenTimeWindow 创建完成")

    # ================================================================
    #  第5步：创建后端实例
    # ================================================================
    logger.info("正在创建后端实例...")
    time_manager: TimeManager = TimeManager()
    backend_handler: ScheduleBackend = ScheduleBackend()
    logger.info("后端实例创建完成")

    # ================================================================
    #  第6步：连接信号和槽
    #   连接1：定时器 → 时间窗口显示更新
    #   连接2：定时器 → 全屏时间窗口显示更新（为未来准备）
    #   连接3：主窗口统一信号 → 后端处理器
    #   连接4：全屏时间关闭信号 → 隐藏窗口
    # ================================================================

    # ----- 连接1：定时器 → 时间窗口 -----
    logger.info("连接信号：定时器 → TimeWindow.update_time_display()")
    time_manager.start(lambda t: time_window.update_time_display(t))
    logger.info("定时器已启动")

    # ----- 连接2：全屏时间窗口关闭 → 隐藏 -----
    fullscreen_window.close_requested.connect(
        lambda: fullscreen_window.hide()
    )

    # ----- 连接3：主窗口统一信号 → 后端 -----
    logger.info("连接信号：ScheduleMainWindow.backend_signal → ScheduleBackend")
    main_window.backend_signal.connect(
        lambda action: backend_handler.handle_action(
            action, main_window, time_window, fullscreen_window, app,
            subject_window=main_window._subject_window
        )
    )
    logger.info("统一后端信号已连接")

    # ================================================================
    #  第7步：显示窗口
    # ================================================================
    logger.info("正在显示窗口...")
    time_window.show()
    main_window.show()
    # fullscreen_window 默认隐藏，通过全屏时间按钮触发显示
    logger.info("窗口已显示，进入事件循环")

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
