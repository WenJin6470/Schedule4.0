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
from schedule_backend import TimeWheelPicker

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

        picker = TimeWheelPicker(start_time, finish_time, parent=self,
                                bg_color=EXAM_BG_COLOR, text_color=EXAM_TEXT_COLOR)
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
