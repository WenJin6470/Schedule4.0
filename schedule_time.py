"""
╔══════════════════════════════════════════════════════════════════════════╗
║          📅 电子课表系统 —— schedule_time.py（时间窗口模块）              ║
║       （置顶时间显示 + 创意模式全屏 + 考试模式全屏 + 滚轮时间选择）   ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责与时间显示相关的所有窗口：
  ✅ TimeWindow            — 屏幕右上角的置顶时间小窗口（实时时钟）
  ✅ FullscreenTimeWindow  — 创意模式全屏时间窗口（随机图片背景 + 红色时钟）
  ✅ ExamFullscreenWindow  — 考试模式全屏时间窗口（墨绿色背景 + 编辑区）
  ✅ WheelColumn           — iOS 风格滚轮列（自定义 QPainter 控件）
  ✅ TimeWheelPicker       — 滚轮时间选择弹窗（编辑考试起止时间）
"""

import logging
import os
import random
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QLabel, QApplication, QPushButton, QComboBox, QFrame,
    QGridLayout, QVBoxLayout, QHBoxLayout, QDialog, QWidget,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QFont, QPixmap, QPainter, QColor, QPen, QLinearGradient,
)

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
    #  公开方法：置顶开关
    # ================================================================
    def set_always_on_top(self, enabled: bool) -> None:
        """
        开启或关闭窗口置顶。

        参数：
            enabled（bool）：True=置顶，False=取消置顶
        """
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint  # type: ignore
        else:
            flags &= ~Qt.WindowStaysOnTopHint  # type: ignore
        self.setWindowFlags(flags)
        self.show()

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


# ==================== 考试模式工具函数 ====================

# 考试模式专用颜色常量
EXAM_BG_COLOR: str = '#0f261e'       # 墨绿色背景
EXAM_TEXT_COLOR: str = '#FFFFFF'      # 白色文字
EXAM_CLOCK_COLOR: str = '#FF0000'     # 红色时钟


def _exam_time_addition(unprocessed: List[int], add_minutes: int) -> List[int]:
    """对时间执行加法运算，返回 [hour, minute]."""
    dt = datetime(2023, 1, 1, unprocessed[0], unprocessed[1])
    result = dt + timedelta(minutes=add_minutes)
    return [result.hour, result.minute]


def _exam_time_match(unprocessed: List[int]) -> List[int]:
    """匹配到最近的 5 或 0 分钟，如 20:07 → 20:10."""
    result = list(unprocessed)
    while result[1] % 10 not in (5, 0):
        result = _exam_time_addition(result, 1)
    return result


def _exam_time_int_str(unprocessed: List[int]) -> str:
    """将 [hour, minute] 转为 HH:MM 字符串."""
    h, m = unprocessed[0], unprocessed[1]
    return f"{h:02d}:{m:02d}"


def predict_exam_times() -> Tuple[str, str, str, str]:
    """
    根据当前系统时间智能预测考试起止时间。

    规则：
      1. 当前时间 + 5~6 分钟 → 向上匹配到最近的 :05/:10/:15… 整点
      2. 结束时间 = 开始时间 + 60 分钟
      3. 下一场开始 = 结束时间 + 15 分钟
      4. 下一场结束 = 下一场开始 + 60 分钟

    返回值：
        (start, finish, next_start, next_finish) — 均为 HH:MM 格式
    """
    now = datetime.now()
    time_start = [now.hour, now.minute]

    if time_start[1] % 10 in (5, 0):
        time_adj = _exam_time_addition(time_start, 6)
    else:
        time_adj = _exam_time_addition(time_start, 5)

    match_start = _exam_time_match(time_adj)
    match_finish = _exam_time_addition(match_start, 60)
    match_next_start = _exam_time_addition(match_finish, 15)
    match_next_finish = _exam_time_addition(match_next_start, 60)

    return (
        _exam_time_int_str(match_start),
        _exam_time_int_str(match_finish),
        _exam_time_int_str(match_next_start),
        _exam_time_int_str(match_next_finish),
    )


# ==================== 滚轮时间选择器 ====================

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
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化滚轮列。

        参数：
            items         （List[str]）：所有可选值
            initial_index （int）：      初始选中项索引
            parent        （QWidget | None）：父控件
        """
        super().__init__(parent)
        self._items: List[str] = list(items)
        self._item_height: int = 55
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
        painter.fillRect(self.rect(), QColor(EXAM_BG_COLOR))

        if n == 0:
            return

        center_idx: int = round(self._float_pos)
        offset: float = center_idx - self._float_pos  # -0.5 ~ 0.5

        # 可见范围：覆盖 widget 高度 + 上下各一个 item_height 的余量
        visible_range: int = int((h / 2 + self._item_height) / self._item_height) + 2

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
            painter.setPen(QColor(255, 255, 255, int(255 * opacity)))

            text_rect: QRectF = QRectF(
                0, item_y - self._item_height / 2, w, self._item_height
            )
            painter.drawText(text_rect, Qt.AlignCenter, self._items[wrapped_idx])  # type: ignore

        # 中心指示线（选中项的上下边界）
        line_y_top: float = center_y - self._item_height / 2
        line_y_bot: float = center_y + self._item_height / 2
        line_margin: float = w * 0.12
        line_w: float = w - 2 * line_margin

        pen: QPen = QPen(QColor(255, 255, 255, 50))
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
        top_grad.setColorAt(0.0, QColor(EXAM_BG_COLOR))
        top_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(0, 0, w, fade_h), top_grad)

        bot_grad: QLinearGradient = QLinearGradient(0, h - fade_h, 0, h)
        bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1.0, QColor(EXAM_BG_COLOR))
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
        """滚轮滚动一格，吸附到邻近项（支持循环）。"""
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

    考试模式中用于编辑起止时间的现代化弹窗，包含：
      - 4 列 iOS 风格滚轮（开始-时 / 开始-分 / 结束-时 / 结束-分）
      - 分隔符（: 和 —）
      - 确认 / 取消 按钮
    ---

    信号：
      time_confirmed(str, str) — 编辑完成，携带 (start_time, finish_time)
    """

    time_confirmed = Signal(str, str)

    def __init__(self, start_time: str, finish_time: str,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化滚轮时间选择器。

        参数：
            start_time  (str)：当前开始时间 HH:MM
            finish_time (str)：当前结束时间 HH:MM
            parent      (QWidget | None)：父窗口
        """
        super().__init__(parent)
        self.setWindowTitle('设置考试时间')
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
        # 外层布局（无 margin，由容器提供内边距）
        outer: QVBoxLayout = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 圆角容器
        container: QFrame = QFrame(self)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {EXAM_BG_COLOR};
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

        self._start_hour: WheelColumn = WheelColumn(hour_items, sh)
        self._start_hour.setFixedWidth(60)
        wheels_row.addWidget(self._start_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._start_min: WheelColumn = WheelColumn(min_items, sm)
        self._start_min.setFixedWidth(60)
        wheels_row.addWidget(self._start_min)
        wheels_row.addWidget(self._make_sep('—'))

        self._end_hour: WheelColumn = WheelColumn(hour_items, fh)
        self._end_hour.setFixedWidth(60)
        wheels_row.addWidget(self._end_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._end_min: WheelColumn = WheelColumn(min_items, fm)
        self._end_min.setFixedWidth(60)
        wheels_row.addWidget(self._end_min)

        inner.addLayout(wheels_row)

        # ---- 分组标签 ----
        labels_row: QHBoxLayout = QHBoxLayout()
        labels_row.setSpacing(0)
        labels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        start_lbl: QLabel = QLabel('开始时间')
        start_lbl.setFont(QFont('Arial', 11))
        start_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.40); background: transparent;"
        )
        start_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        start_lbl.setFixedWidth(60 + 16 + 60)  # 两个滚轮 + 冒号分隔符
        labels_row.addWidget(start_lbl)

        labels_row.addSpacing(16)  # "—" 分隔符的空间

        end_lbl: QLabel = QLabel('结束时间')
        end_lbl.setFont(QFont('Arial', 11))
        end_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.40); background: transparent;"
        )
        end_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        end_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(end_lbl)

        inner.addLayout(labels_row)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(20)
        btn_row.setAlignment(Qt.AlignCenter)  # type: ignore

        cancel_btn: QPushButton = QPushButton('取消')
        cancel_btn.setFont(QFont('Arial', 14))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                color: rgba(255,255,255,0.50);
                background: transparent;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 8px 28px;
            }}
            QPushButton:hover {{
                color: {EXAM_TEXT_COLOR};
                border-color: rgba(255,255,255,0.30);
            }}
            QPushButton:pressed {{
                background-color: rgba(255,255,255,0.05);
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn: QPushButton = QPushButton('确认')
        confirm_btn.setFont(QFont('Arial', 14, QFont.Bold)) # type: ignore
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                color: {EXAM_TEXT_COLOR};
                background-color: #1a4a32;
                border: none;
                border-radius: 8px;
                padding: 8px 28px;
            }}
            QPushButton:hover {{
                background-color: #235a40;
            }}
            QPushButton:pressed {{
                background-color: #0f261e;
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
        label: QLabel = QLabel(text)
        label.setFont(QFont('Arial', 22))
        label.setStyleSheet(
            "color: rgba(255,255,255,0.35); background: transparent;"
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


# ==================== 考试模式全屏窗口 ====================

class ExamFullscreenWindow(QWidget):
    """
    # ExamFullscreenWindow — 考试模式全屏时间窗口

    全屏墨绿色背景，展示：
      - 顶部横向标语：「以学品证人品 不抄袭不作弊」
      - 左侧纵向标语：「缜密思考」
      - 右侧纵向标语：「细心作答」
      - 中央红色实时时钟
      - 可编辑区：科目 / 卷长 / 考试时间 / 下一场时间
      - 底部退出全屏按钮
    ---

    对外接口：
      - show_fullscreen()            — 显示窗口
      - hide_fullscreen()            — 隐藏窗口
      - update_time_display(time_str) — 刷新实时时钟
    """

    close_requested = Signal()

    def __init__(self, theme_manager: ThemeManager) -> None:
        """
        初始化考试模式全屏窗口。

        参数：
            theme_manager（ThemeManager）：全局主题管理器（取屏幕尺寸）
        """
        super().__init__()
        self._theme: ThemeManager = theme_manager

        # ---- 科目列表 ----
        self._subjects: List[str] = [
            '语文', '数学', '英语', '政治', '历史',
            '物理', '化学', '地理', '生物', '信息技术',
        ]

        # ---- 卷长列表 ----
        self._roll_sheet: List[str] = [
            '共1张', '共2张', '共3张', '共4张',
            '共5张', '共6张', '共7张', '共8张',
        ]
        self._roll_page: List[str] = [
            '共1页', '共2页', '共3页', '共4页',
            '共5页', '共6页', '共7页', '共8页',
        ]

        # ---- 预测时间 ----
        st, ft, st_n, ft_n = predict_exam_times()
        self._start_time: str = st
        self._finish_time: str = ft
        self._next_start_time: str = st_n
        self._next_finish_time: str = ft_n

        logger.info(
            f"ExamFullscreenWindow 预测时间：{st}—{ft}，"
            f"下一场 {st_n}—{ft_n}"
        )

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setStyleSheet(f"background-color: {EXAM_BG_COLOR};")
        self.setFixedSize(
            self._theme.screen_width,
            self._theme.screen_height,
        )
        self.move(0, 0)

        # ---- 控件引用 ----
        self._time_label: Optional[QLabel] = None
        self._time_btn: Optional[QPushButton] = None
        self._next_time_btn: Optional[QPushButton] = None

        # ---- 构建 UI ----
        self._setup_ui()
        logger.info("ExamFullscreenWindow 初始化完成")

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造考试模式全屏窗口布局."""
        root: QGridLayout = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.setRowStretch(0, 2)  # 更多顶部空间，整体下移
        root.setRowStretch(1, 2)
        root.setRowStretch(2, 2)
        root.setRowStretch(3, 2)
        root.setRowStretch(4, 1)  # 退出按钮保持原位

        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 3)
        root.setColumnStretch(2, 1)

        # ---- 1. 顶部横向标语 ----
        slogan_top = QLabel('以学品证人品 不抄袭不作弊', self)
        slogan_top.setFont(QFont('宋体', 55))
        slogan_top.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        slogan_top.setAlignment(Qt.AlignCenter)  # type: ignore
        root.addWidget(slogan_top, 0, 0, 1, 3)

        # ---- 2. 左侧纵向标语 ----
        left_slogan = QLabel('缜\n\n密\n\n思\n\n考', self)
        left_slogan.setFont(QFont('宋体', 40))
        left_slogan.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        left_slogan.setAlignment(Qt.AlignCenter)  # type: ignore
        root.addWidget(left_slogan, 1, 0, 3, 1)

        # ---- 3. 右侧纵向标语 ----
        right_slogan = QLabel('细\n\n心\n\n作\n\n答', self)
        right_slogan.setFont(QFont('宋体', 40))
        right_slogan.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        right_slogan.setAlignment(Qt.AlignCenter)  # type: ignore
        root.addWidget(right_slogan, 1, 2, 3, 1)

        # ---- 4. 中央实时时钟 ----
        self._time_label = QLabel('--:--:--', self)
        self._time_label.setFont(QFont('Arial', 150))
        self._time_label.setStyleSheet(
            f"color: {EXAM_CLOCK_COLOR}; background: transparent;"
        )
        self._time_label.setAlignment(Qt.AlignCenter)  # type: ignore
        root.addWidget(self._time_label, 1, 1)

        # ---- 5. 可编辑区域 ----
        edit_frame: QFrame = QFrame(self)
        edit_frame.setStyleSheet("background: transparent;")
        edit_layout: QGridLayout = QGridLayout(edit_frame)
        edit_layout.setVerticalSpacing(12)
        edit_layout.setHorizontalSpacing(8)
        edit_layout.setContentsMargins(10, 5, 10, 5)
        edit_layout.setAlignment(Qt.AlignCenter)  # type: ignore

        font_label = QFont('宋体', 30)
        font_time_btn = QFont('宋体', 25)

        # —— 科目行 ——
        subj_label = QLabel('科目:', self)
        subj_label.setFont(font_label)
        subj_label.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        edit_layout.addWidget(subj_label, 0, 0)

        self._subject_combo = self._make_combo(self._subjects, 0)
        edit_layout.addWidget(self._subject_combo, 0, 1, 1, 3)

        # —— 卷长行 ——
        roll_label = QLabel('卷长:', self)
        roll_label.setFont(font_label)
        roll_label.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        edit_layout.addWidget(roll_label, 1, 0)

        self._sheet_combo = self._make_combo(self._roll_sheet, 0)
        edit_layout.addWidget(self._sheet_combo, 1, 1)
        self._page_combo = self._make_combo(self._roll_page, 0)
        edit_layout.addWidget(self._page_combo, 1, 2)

        # —— 时间行 ——
        time_label_w = QLabel('时间:', self)
        time_label_w.setFont(font_label)
        time_label_w.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        edit_layout.addWidget(time_label_w, 2, 0)

        combined_time = f"{self._start_time} — {self._finish_time}"
        self._time_btn = self._make_time_button(
            combined_time,
            lambda: self._open_keypad(self._time_btn), # type: ignore
        )
        edit_layout.addWidget(self._time_btn, 2, 1, 1, 3)

        # —— 下一场行 ——
        next_label = QLabel('下一场:', self)
        next_label.setFont(font_label)
        next_label.setStyleSheet(f"color: {EXAM_TEXT_COLOR}; background: transparent;")
        edit_layout.addWidget(next_label, 3, 0)

        self._next_subject_combo = self._make_combo(self._subjects, 0)
        edit_layout.addWidget(self._next_subject_combo, 3, 1)

        combined_next = f"{self._next_start_time} — {self._next_finish_time}"
        self._next_time_btn = self._make_time_button(
            combined_next,
            lambda: self._open_keypad(self._next_time_btn), # type: ignore
        )
        edit_layout.addWidget(self._next_time_btn, 3, 2, 1, 3)

        # ---- 使用提示 ----
        hint_label = QLabel('点击 语文 或 白色时间 则可进行修改。', self)
        hint_label.setFont(QFont('宋体', 12))
        hint_label.setStyleSheet(
            "color: rgba(255,255,255,0.35); background: transparent; font-style: italic;"
        )
        hint_label.setAlignment(Qt.AlignCenter)  # type: ignore
        edit_layout.addWidget(hint_label, 4, 0, 1, 4, Qt.AlignCenter)  # type: ignore

        root.addWidget(edit_frame, 2, 1, 2, 1, Qt.AlignCenter)  # type: ignore

        # ---- 6. 退出全屏按钮 ----
        exit_btn = QPushButton('退出全屏', self)
        exit_btn.setFont(QFont('黑体', 15))
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                color: rgba(255,255,255,0.45);
                background: transparent;
                border: none;
                padding: 8px 20px;
            }}
            QPushButton:hover {{
                color: {EXAM_TEXT_COLOR};
            }}
        """)
        exit_btn.clicked.connect(self._on_exit)
        root.addWidget(exit_btn, 4, 2, Qt.AlignRight | Qt.AlignBottom)  # type: ignore

        self.setLayout(root)

    # ================================================================
    #  控件工厂方法
    # ================================================================
    def _make_combo(self, items: List[str], default_index: int) -> QComboBox:
        """创建统一样式的下拉框（完全无边框）."""
        combo = QComboBox(self)
        combo.addItems(items)
        combo.setCurrentIndex(default_index)
        combo.setFont(QFont('宋体', 28))
        combo.setStyleSheet(f"""
            QComboBox {{
                color: {EXAM_TEXT_COLOR};
                background: transparent;
                border: none;
                padding: 6px 24px 6px 6px;
                min-width: 70px;
            }}
            QComboBox:hover {{
                color: {EXAM_TEXT_COLOR};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                color: {EXAM_TEXT_COLOR};
                background-color: #0f261e;
                selection-background-color: #1a3a2e;
                border: none;
                outline: none;
                padding: 4px;
            }}
        """)
        return combo

    def _make_time_button(self, text: str, slot) -> QPushButton:
        """创建时间按钮（无边框，点击弹出数字小键盘）."""
        btn = QPushButton(text, self)
        btn.setFont(QFont('宋体', 28))
        btn.setStyleSheet(f"""
            QPushButton {{
                color: {EXAM_TEXT_COLOR};
                background: transparent;
                border: none;
                border-radius: 0;
                padding: 0px;
                max-width: 300px;
            }}
            QPushButton:hover {{
                color: rgba(255,255,255,0.75);
            }}
        """)
        btn.clicked.connect(slot)
        return btn

    # ================================================================
    #  滚轮时间选择器
    # ================================================================
    def _open_keypad(self, btn: QPushButton) -> None:
        """
        打开滚轮时间选择器编辑起止时间。

        参数：
            btn（QPushButton）：合并的时间按钮，文本格式为 "HH:MM — HH:MM"
        """
        parts = btn.text().split(' — ')
        start_time = parts[0].strip() if len(parts) >= 1 else '00:00'
        finish_time = parts[1].strip() if len(parts) >= 2 else '00:00'

        picker = TimeWheelPicker(start_time, finish_time, parent=self)
        picker.time_confirmed.connect(
            lambda st, ft: self._on_time_confirmed(btn, st, ft)
        )
        picker.exec()

    def _on_time_confirmed(self, btn: QPushButton,
                           start_time: str,
                           finish_time: str) -> None:
        """数字小键盘确认后将结果写入对应按钮."""
        btn.setText(f"{start_time} — {finish_time}")
        logger.info(f"时间已更新：{start_time} — {finish_time}")

    # ================================================================
    #  公开方法
    # ================================================================
    def show_fullscreen(self) -> None:
        """显示考试模式全屏窗口."""
        logger.info("显示考试模式全屏窗口")
        self.show()

    def hide_fullscreen(self) -> None:
        """隐藏考试模式全屏窗口."""
        logger.info("隐藏考试模式全屏窗口")
        self.hide()

    def update_time_display(self, time_str: str) -> None:
        """刷新中央实时时钟."""
        if self._time_label is not None:
            self._time_label.setText(time_str)

    # ================================================================
    #  退出
    # ================================================================
    def _on_exit(self) -> None:
        """退出全屏按钮."""
        logger.info("用户点击退出全屏（考试模式）")
        self.hide()
        self.close_requested.emit()

    # ================================================================
    #  键盘事件
    # ================================================================
    def keyPressEvent(self, event) -> None:
        """ESC 键退出全屏."""
        if event.key() == Qt.Key_Escape:  # type: ignore
            logger.info("用户按 Esc 退出考试模式全屏")
            self.hide()
            self.close_requested.emit()
