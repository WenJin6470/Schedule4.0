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
import os
import random
from typing import Optional

from PySide6.QtWidgets import QLabel, QApplication
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QPainter

from schedule_config import ThemeManager, ThemedWidget

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


# ==================== 全屏时间窗口 ====================

class FullscreenTimeWindow(ThemedWidget):
    """
    # FullscreenTimeWindow — 全屏时间显示窗口

    全屏显示当前时间的窗口，适合在教室投影等场景使用。
    支持两种模式：
      - 考试模式（exam）：纯色背景 + 实时时间（与旧版行为一致）
      - 创意模式（creative）：随机图片背景 + 红色实时时间
    ---

    对外接口：
      - show_fullscreen(mode) — 以指定模式显示全屏时间窗口
      - hide_fullscreen()     — 隐藏全屏时间窗口
      - set_mode(mode)        — 切换显示模式
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

        # ---- 当前模式 ----
        self._mode: str = 'exam'  # 'exam' 或 'creative'
        self._bg_pixmap: Optional[QPixmap] = None  # 创意模式的背景图片

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(1.0)

        # 全屏尺寸
        self.setFixedSize(
            self._theme.screen_width,
            self._theme.screen_height,
        )
        self.move(0, 0)

        # ---- 居中时间标签（红色，始终显示）----
        self._time_label: QLabel = QLabel(self)
        self._time_label.setFont(QFont("Arial", 180))
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

    def set_mode(self, mode: str) -> None:
        """
        设置全屏时间的显示模式。
        ----------------------
        参数：
            mode（str）：'exam' — 考试模式（纯色背景）
                        'creative' — 创意模式（随机图片背景）
        """
        if mode not in ('exam', 'creative'):
            logger.warning(f"未知的全屏时间模式：'{mode}'，保持当前模式")
            return
        self._mode = mode
        logger.info(f"全屏时间模式已切换为：{mode}")

    def show_fullscreen(self, mode: str = 'exam') -> None:
        """
        以指定模式显示全屏时间窗口。
        -------------------------
        参数：
            mode（str）：'exam' — 考试模式（纯色背景 + 实时时间）
                        'creative' — 创意模式（随机图片背景 + 红色实时时间）
        """
        logger.info(f"显示全屏时间窗口（模式：{mode}）")
        self.set_mode(mode)

        if self._mode == 'creative':
            self._load_random_background()

        self.show()

    def hide_fullscreen(self) -> None:
        """隐藏全屏时间窗口。"""
        logger.info("隐藏全屏时间窗口")
        if self._bg_pixmap is not None:
            self._bg_pixmap = None
        self.hide()

    # ================================================================
    #  创意模式：随机加载背景图片
    # ================================================================
    def _load_random_background(self) -> None:
        """
        从配置的文件夹中随机选取一张图片作为创意模式背景。
        -----------------------------------------------
        支持的格式：png, jpg, jpeg, bmp
        若文件夹不存在或无可用图片，回退到纯色背景。
        """
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        bg_folder: str = os.path.join(script_dir, self._theme.fullscreen_bg_folder)

        logger.info(f"创意模式：在文件夹中随机选择背景图片：{bg_folder}")

        if not os.path.isdir(bg_folder):
            logger.warning(f"背景图片文件夹不存在：{bg_folder}，回退到纯色背景")
            self._bg_pixmap = None
            return

        # 收集支持的图片文件
        valid_extensions: tuple = ('.png', '.jpg', '.jpeg', '.bmp')
        image_files: list = [
            f for f in os.listdir(bg_folder)
            if f.lower().endswith(valid_extensions)
        ]

        if not image_files:
            logger.warning(f"背景图片文件夹为空（无支持的图片文件）：{bg_folder}，回退到纯色背景")
            self._bg_pixmap = None
            return

        # 随机选择一张图片
        chosen_file: str = random.choice(image_files)
        image_path: str = os.path.join(bg_folder, chosen_file)

        logger.info(f"创意模式：随机选中背景图片：{chosen_file}")

        pixmap: QPixmap = QPixmap(image_path)
        if pixmap.isNull():
            logger.warning(f"无法加载图片：{image_path}，回退到纯色背景")
            self._bg_pixmap = None
            return

        # 缩放图片到全屏尺寸（拉伸充满，考虑高 DPI 避免模糊）
        dpr: float = self.devicePixelRatio()
        self._bg_pixmap = pixmap.scaled(
            int(self._theme.screen_width * dpr),
            int(self._theme.screen_height * dpr),
            Qt.IgnoreAspectRatio,            # type: ignore
            Qt.SmoothTransformation,          # type: ignore
        )
        self._bg_pixmap.setDevicePixelRatio(dpr)

    # ================================================================
    #  鼠标点击关闭
    # ================================================================
    def mousePressEvent(self, event) -> None:
        """点击任意位置关闭全屏时间。"""
        logger.info("用户点击全屏时间窗口，关闭")
        self.hide()
        self.close_requested.emit()

    # ================================================================
    #  重写 paintEvent：创意模式绘制背景图片
    # ================================================================
    def paintEvent(self, event) -> None:
        """
        自定义背景绘制。
        -------------
        创意模式：绘制随机背景图片（拉伸覆盖全屏）。
        考试模式：使用父类 ThemedWidget 的纯色背景填充。
        """
        painter: QPainter = QPainter(self)

        if self._mode == 'creative' and self._bg_pixmap is not None:
            # 创意模式：拉伸图片充满整个窗口
            painter.drawPixmap(self.rect(), self._bg_pixmap)
        else:
            # 考试模式或创意模式无图片时：使用纯色背景
            painter.fillRect(self.rect(), self._bg_color)
