"""
╔══════════════════════════════════════════════════════════════════════════╗
║          📅 电子课表系统 —— schedule_time.py（时间窗口模块）              ║
║                     （置顶时间显示 + 全屏时间窗口）                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责与时间显示相关的所有窗口：
  ✅ TimeWindow — 屏幕右上角的置顶时间小窗口（实时时钟）
  ✅ FullscreenTimeWindow — 全屏时间显示窗口（待后续实现）

两个窗口均继承 ThemedWidget，通过 ThemeManager 获取统一的主题颜色。
"""

import logging
from typing import Optional

from PySide6.QtWidgets import QLabel, QApplication
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from schedule_theme import ThemeManager, ThemedWidget

logger: logging.Logger = logging.getLogger(__name__)


# ==================== 置顶时间小窗口 ====================

class TimeWindow(ThemedWidget):
    """
    # TimeWindow — 置顶实时时间显示窗口

    位于屏幕右上角，显示 HH:MM:SS 格式的实时时间。
    ---

    对外接口：
      - update_time_display(time_str) — 更新时间显示文字
    """

    def __init__(self, theme_manager: ThemeManager) -> None:
        """
        初始化时间窗口。
        ---------------
        参数：
            theme_manager（ThemeManager）：全局主题管理器
        """
        super().__init__(theme_manager, bg_color_attr='back_color')

        logger.info("TimeWindow 初始化开始")

        # ---- 计算窗口尺寸和位置 ----
        self._win_width: int = int(self._theme.screen_width * (150 / 1920))
        self._win_height: int = int(self._theme.screen_height / 26)
        self._pos_x: int = int(self._theme.screen_width * (1765 / 1920))
        self._pos_y: int = int(self._theme.screen_height * (45 / 1080))

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(self._theme.window_opacity)
        self.setFixedSize(self._win_width, self._win_height)
        self.move(self._pos_x, self._pos_y)

        # ---- 时间标签 ----
        self._time_label: QLabel = QLabel(self)
        self._time_label.setFont(QFont("Arial", 18))
        self._time_label.setStyleSheet(
            f"color: {self._theme.time_color}; background: transparent;"
        )
        self._time_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self._time_label.setGeometry(0, 0, self._win_width, self._win_height)
        self._time_label.setText("--:--:--")

        logger.info(f"TimeWindow 创建完成：位置({self._pos_x}, {self._pos_y})，"
                    f"大小 {self._win_width}×{self._win_height}")

    # ================================================================
    #  公开方法：更新时间显示
    # ================================================================
    def update_time_display(self, time_str: str) -> None:
        """
        更新时间标签的显示文字。
        ---------------------
        参数：
            time_str（str）：时间字符串，格式 HH:MM:SS

        调用时机：
          - TimeManager 定时器每秒触发时调用
        """
        self._time_label.setText(time_str)


# ==================== 全屏时间窗口（预留） ====================

class FullscreenTimeWindow(ThemedWidget):
    """
    # FullscreenTimeWindow — 全屏时间显示窗口

    全屏显示当前时间的窗口，适合在教室投影等场景使用。
    ---

    当前状态：界面框架已搭建，具体功能待后续实现。

    对外接口：
      - show_fullscreen() — 显示全屏时间窗口
      - hide_fullscreen() — 隐藏全屏时间窗口
    """

    # 信号：全屏时间窗口关闭请求
    close_requested = Signal()

    def __init__(self, theme_manager: ThemeManager) -> None:
        """
        初始化全屏时间窗口。
        -----------------
        参数：
            theme_manager（ThemeManager）：全局主题管理器
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        logger.info("FullscreenTimeWindow 初始化开始")

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.95)

        # 全屏尺寸
        self.setFixedSize(
            self._theme.screen_width,
            self._theme.screen_height,
        )
        self.move(0, 0)

        # ---- 居中时间标签 ----
        self._time_label: QLabel = QLabel(self)
        self._time_label.setFont(QFont("Arial", 120))
        self._time_label.setStyleSheet(
            f"color: {self._theme.time_color}; background: transparent;"
        )
        self._time_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self._time_label.setGeometry(
            0, 0, self._theme.screen_width, self._theme.screen_height
        )
        self._time_label.setText("--:--:--")

        # ---- 提示文字 ----
        self._hint_label: QLabel = QLabel(self)
        self._hint_label.setFont(QFont("Arial", 14))
        self._hint_label.setStyleSheet(
            f"color: {self._theme.font_color}; background: transparent;"
        )
        self._hint_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self._hint_label.setGeometry(
            0, self._theme.screen_height - 80,
            self._theme.screen_width, 40,
        )
        self._hint_label.setText("按 Esc 或点击任意位置关闭全屏时间")

        logger.info("FullscreenTimeWindow 创建完成（默认隐藏）")

    # ================================================================
    #  公开方法
    # ================================================================
    def update_time_display(self, time_str: str) -> None:
        """更新时间显示（与 TimeWindow 接口一致）。"""
        self._time_label.setText(time_str)

    def show_fullscreen(self) -> None:
        """显示全屏时间窗口。"""
        logger.info("显示全屏时间窗口")
        self.show()

    def hide_fullscreen(self) -> None:
        """隐藏全屏时间窗口。"""
        logger.info("隐藏全屏时间窗口")
        self.hide()

    # ================================================================
    #  鼠标点击关闭
    # ================================================================
    def mousePressEvent(self, event) -> None:
        """点击任意位置关闭全屏时间。"""
        logger.info("用户点击全屏时间窗口，关闭")
        self.hide()
        self.close_requested.emit()
