"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║               （全屏设置页面 · 左侧导航 + 右侧内容区）                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责全屏设置窗口：
  ✅ SettingsWindow — 全屏设置窗口（系统标题栏 + 左2右8布局）
  ✅ TimetableEntryDialog — 时间表条目编辑子窗口
  ✅ NewTimetableDialog — 新建时间表子窗口

左侧导航栏从上到下：
  - 图标展示（DAILY_SCHEDULE.svg + Schedule4.0 并排）
  - 基础设置 / 美化 / 课表编辑 / 关于（带 emoji 图标）

右侧为 QStackedWidget，随左侧导航切换内容页面。
课表编辑页面已实现时间表编辑器。
"""

import copy
import json
import logging
import os
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QLineEdit, QComboBox, QRadioButton, QFileDialog, QAbstractItemView,
    QScrollArea, QScroller, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, SignalInstance, QTimer
from PySide6.QtGui import QFont, QIcon, QCloseEvent, QColor

from schedule_config import ThemeManager, ThemedWidget, ScheduleDataManager
from schedule_backend import TimeWheelPicker, WheelColumn

logger: logging.Logger = logging.getLogger(__name__)


class SettingsWindow(ThemedWidget):
    """
    # SettingsWindow — 全屏设置窗口

    参考 Windows 系统设置页面布局：
      - 左侧导航栏（20%）：图标 + 分类标签
      - 右侧内容区（80%）：QStackedWidget 切换页面
    ---

    窗口属性：
      - 系统标题栏（可最小化 / 最大化 / 关闭）
      - 全屏最大化显示
    """

    # 导航项配置：(emoji 图标, 显示文字, 页面索引)
    NAV_ITEMS: List[tuple] = [
        ("⚙️", "基础设置", 0),
        ("🎨", "美化",     1),
        ("📝", "课表编辑", 2),
        ("ℹ️", "关于",     3),
    ]

    # 信号：时间表发生变更，通知主窗口重建标签
    timetable_changed = Signal()

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager,
                 schedule_data: Optional[ScheduleDataManager] = None) -> None:
        """
        初始化设置窗口。
        ---------------
        参数：
            parent_signal（SignalInstance）：父窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
            schedule_data（ScheduleDataManager）：课表数据管理器
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal
        self._schedule_data: Optional[ScheduleDataManager] = schedule_data
        self._nav_buttons: List[QPushButton] = []
        self._exit_btn: Optional[QPushButton] = None
        self._current_index: int = 0

        # 时间表编辑器引用
        self._timetable_table: Optional[QTableWidget] = None
        self._status_label: Optional[QLabel] = None
        self._status_card: Optional[QFrame] = None
        self._table_frame: Optional[QFrame] = None
        self._add_dialog: Optional[TimetableEntryDialog] = None

        # 课程表编辑器引用
        self._curriculum_table: Optional[QTableWidget] = None
        self._curriculum_status_label: Optional[QLabel] = None
        self._curriculum_status_card: Optional[QFrame] = None
        self._curriculum_table_frame: Optional[QFrame] = None

        # 课程表内联编辑器
        self._cv_editor_card: Optional[QFrame] = None
        self._cv_cursor_row: int = -1
        self._cv_cursor_col: int = -1
        self._cv_cursor_day: str = ''
        self._cv_cursor_lesson: str = ''
        self._cv_blink_timer: QTimer = QTimer()
        self._cv_blink_timer.setInterval(500)
        self._cv_blink_timer.timeout.connect(self._toggle_cv_blink)
        self._cv_blink_on: bool = False
        self._pending_curriculum_data: Dict = {}
        self._cv_status_label: Optional[QLabel] = None
        self._cv_subject_buttons: List[QPushButton] = []
        self._cv_subject_categories: Dict[str, List[str]] = {}

        logger.info("SettingsWindow 初始化开始")
        self._setup_ui()
        logger.info("SettingsWindow 初始化完成")

    # ================================================================
    #  私有方法：创建 UI
    # ================================================================
    def _setup_ui(self) -> None:
        """创建全屏设置窗口及其内部控件。"""

        # ---- 窗口属性 ----
        # 使用系统标题栏（参照 SubjectSelectWindow 的模式）
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
            | Qt.WindowMinimizeButtonHint     # type: ignore
            | Qt.WindowMaximizeButtonHint     # type: ignore
        )
        self.setWindowTitle("设置")
        self.setAutoFillBackground(True)
        self.setWindowOpacity(1.0)

        # 窗口初始大小覆盖全屏（showMaximized 由调用方执行）
        self.resize(self._theme.screen_width, self._theme.screen_height)

        # ---- 主布局：左 2 + 分割线 + 右 8 ----
        main_layout: QHBoxLayout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧导航栏
        left_panel: QWidget = self._build_left_panel()
        main_layout.addWidget(left_panel, stretch=1)

        # 垂直分割线
        divider: QFrame = QFrame()
        divider.setFrameShape(QFrame.VLine)  # type: ignore
        divider.setStyleSheet(f"""
            border: none;
            border-left: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        main_layout.addWidget(divider)

        # 右侧内容区
        right_panel: QWidget = self._build_right_panel()
        main_layout.addWidget(right_panel, stretch=9)

    # ================================================================
    #  构建左侧导航栏
    # ================================================================
    def _build_left_panel(self) -> QWidget:
        """
        构建左侧导航栏面板。
        -----------------
        从上到下：
          1. 图标 + 应用名（DAILY_SCHEDULE.svg + Schedule4.0）
          2. 分割线
          3. 4 个导航按钮（带 emoji 图标）
          4. 底部弹簧
        """
        panel: QWidget = QWidget()
        panel.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(4)

        # ---- 第1部分：图标 + 应用名 ----
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setContentsMargins(12, 12, 12, 28)
        header_layout.setSpacing(14)

        # 图标（大尺寸，填充头部区域）
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        icon_path: str = os.path.join(script_dir, 'images', 'Icons', 'DAILY_SCHEDULE.svg')

        icon_label: QLabel = QLabel()
        icon_label.setFixedSize(56, 56)
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(56, 56))
        icon_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(icon_label)

        # 应用名（大号加粗字体）
        name_label: QLabel = QLabel("Schedule4.0")
        name_label.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        name_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            border: none;
        """)
        header_layout.addWidget(name_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # ---- 分割线 ----
        sep: QFrame = QFrame()
        sep.setFrameShape(QFrame.HLine)  # type: ignore
        sep.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        layout.addWidget(sep)
        layout.addSpacing(8)

        # ---- 导航按钮 ----
        for emoji, text, index in self.NAV_ITEMS:
            btn: QPushButton = QPushButton(f"  {emoji}  {text}")
            btn.setFont(QFont("Microsoft YaHei", 11))
            btn.setCursor(Qt.PointingHandCursor)  # type: ignore
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
            btn.clicked.connect(
                lambda checked=False, i=index: self._on_nav_clicked(i)
            )
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        # ---- 底部弹簧（将退出按钮推至最下方）----
        layout.addStretch()

        # ---- 退出按钮 ----
        exit_btn: QPushButton = QPushButton("  🚪  退出")
        exit_btn.setFont(QFont("Microsoft YaHei", 11))
        exit_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        exit_btn.setMinimumHeight(44)
        exit_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        exit_btn.clicked.connect(self._on_exit_clicked)
        self._exit_btn = exit_btn
        layout.addWidget(exit_btn)

        # 应用初始样式
        self._refresh_nav_styles()
        self._refresh_exit_btn_style()

        return panel

    # ================================================================
    #  构建右侧内容区
    # ================================================================
    def _build_right_panel(self) -> QWidget:
        """
        构建右侧内容区域。
        ----------------
        使用 QStackedWidget 管理 4 个页面，
        其中"课表编辑"为实际功能页面，其余为占位。
        """
        right_panel: QWidget = QWidget()
        right_panel.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(right_panel)
        layout.setContentsMargins(32, 32, 32, 32)

        self._stack: QStackedWidget = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        # 页面 0：基础设置（占位）
        self._stack.addWidget(self._create_placeholder_page("基础设置"))
        # 页面 1：美化（占位）
        self._stack.addWidget(self._create_placeholder_page("美化"))
        # 页面 2：课表编辑（实际编辑器）
        self._stack.addWidget(self._create_timetable_editor_page())
        # 页面 3：关于（占位）
        self._stack.addWidget(self._create_placeholder_page("关于"))

        # 默认显示第一页
        self._stack.setCurrentIndex(0)

        layout.addWidget(self._stack)

        return right_panel

    # ================================================================
    #  创建占位页面
    # ================================================================
    def _create_placeholder_page(self, title: str) -> QWidget:
        """
        创建一个占位内容页面。
        -------------------
        参数：
            title（str）：页面标题

        返回值：
            QWidget：包含标题和提示文字的页面控件
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # 页面标题
        title_label: QLabel = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        title_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
        """)
        layout.addWidget(title_label)

        # 占位提示
        hint_label: QLabel = QLabel("此设置页面正在开发中...")
        hint_label.setFont(QFont("Microsoft YaHei", 12))
        hint_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            opacity: 0.5;
        """)
        layout.addWidget(hint_label)

        layout.addStretch()

        return page

    # ================================================================
    #  创建时间表编辑器页面
    # ================================================================
    def _create_timetable_editor_page(self) -> QWidget:
        """
        构建"课表编辑"页面。
        ------------------
        一级标题：
          - 基础（特殊课表规则开关 + 时间表/课程表选择卡片）
          - 时间表（加载/新建按钮、状态标签、条目表格、新加条目按钮）
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        fc: str = self._theme.font_color

        # ---- 页面主标题 ----
        page_title: QLabel = QLabel("课表编辑")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(page_title)

        # ---- 一级标题：时间表 ----
        section_title: QLabel = QLabel("时间表")
        section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(section_title)

        # ---- 缩进容器（时间表控件统一缩进 28px）----
        tt_indent: QWidget = QWidget()
        tt_indent.setStyleSheet("background: transparent;")
        tt_indent_layout: QVBoxLayout = QVBoxLayout(tt_indent)
        tt_indent_layout.setContentsMargins(28, 0, 0, 0)
        tt_indent_layout.setSpacing(12)

        # ---- 按钮行 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)

        load_btn: QPushButton = QPushButton("加载时间表")
        load_btn.setFont(QFont("Microsoft YaHei", 11))
        load_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        load_btn.setMinimumHeight(36)
        load_btn.clicked.connect(self._on_load_timetable)
        btn_row.addWidget(load_btn)

        new_btn: QPushButton = QPushButton("新建时间表")
        new_btn.setFont(QFont("Microsoft YaHei", 11))
        new_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        new_btn.setMinimumHeight(36)
        new_btn.clicked.connect(self._on_new_timetable)
        btn_row.addWidget(new_btn)

        btn_row.addStretch()

        # 按钮样式
        self._style_timetable_buttons(load_btn, new_btn)

        tt_indent_layout.addLayout(btn_row)

        # ---- 状态标签（卡片式）----
        self._status_card = QFrame()
        self._status_card.setStyleSheet(self._get_status_card_style())
        status_card_layout: QVBoxLayout = QVBoxLayout(self._status_card)
        status_card_layout.setContentsMargins(14, 10, 14, 10)

        self._status_label = QLabel(self._get_status_text())
        self._status_label.setFont(QFont("Microsoft YaHei", 10))
        self._status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        status_card_layout.addWidget(self._status_label)
        tt_indent_layout.addWidget(self._status_card)

        # ---- 条目表格（带外框）----
        self._table_frame = QFrame()
        self._table_frame.setStyleSheet(self._get_table_frame_style())
        table_frame_layout: QVBoxLayout = QVBoxLayout(self._table_frame)
        table_frame_layout.setContentsMargins(1, 1, 1, 1)

        self._timetable_table = QTableWidget()
        self._timetable_table.setColumnCount(4)
        self._timetable_table.setHorizontalHeaderLabels(
            ["序号", "类型", "开始时间", "结束时间"]
        )
        self._timetable_table.setSelectionBehavior(QAbstractItemView.SelectRows)  # type: ignore
        self._timetable_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # type: ignore
        self._timetable_table.setAlternatingRowColors(True)
        self._timetable_table.setShowGrid(False)
        self._timetable_table.horizontalHeader().setStretchLastSection(True)
        self._timetable_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch  # type: ignore
        )
        self._timetable_table.verticalHeader().setVisible(False)
        self._timetable_table.cellDoubleClicked.connect(self._on_entry_double_clicked)
        self._style_table()

        table_frame_layout.addWidget(self._timetable_table)
        tt_indent_layout.addWidget(self._table_frame)

        # ---- 新加条目按钮（实色强调）----
        add_btn: QPushButton = QPushButton("＋ 新加条目")
        add_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        add_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        add_btn.setMinimumHeight(38)
        add_btn.clicked.connect(self._on_add_entry)
        add_btn.setStyleSheet(self._get_add_btn_style())
        tt_indent_layout.addWidget(add_btn)

        # 将"时间表"缩进容器添加到主布局（无 stretch，高度自适应条目数量）
        layout.addWidget(tt_indent)

        # ════════════════════════════════════════════════════════════
        #  课程表
        # ════════════════════════════════════════════════════════════
        # ---- 分割线 ----
        cv_sep_line: QFrame = QFrame()
        cv_sep_line.setFrameShape(QFrame.HLine)  # type: ignore
        cv_sep_line.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        layout.addWidget(cv_sep_line)
        layout.addSpacing(4)

        # ---- 一级标题：课程表 ----
        cv_section_title: QLabel = QLabel("课程表")
        cv_section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        cv_section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        cv_section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(cv_section_title)

        # ---- 缩进容器（课程表控件统一缩进 28px）----
        cv_indent: QWidget = QWidget()
        cv_indent.setStyleSheet("background: transparent;")
        cv_indent_layout: QVBoxLayout = QVBoxLayout(cv_indent)
        cv_indent_layout.setContentsMargins(28, 0, 0, 0)
        cv_indent_layout.setSpacing(12)

        # ---- 按钮行 ----
        cv_btn_row: QHBoxLayout = QHBoxLayout()
        cv_btn_row.setSpacing(12)

        cv_load_btn: QPushButton = QPushButton("加载课程表")
        cv_load_btn.setFont(QFont("Microsoft YaHei", 11))
        cv_load_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cv_load_btn.setMinimumHeight(36)
        cv_load_btn.clicked.connect(self._on_load_curriculum)
        cv_btn_row.addWidget(cv_load_btn)

        cv_new_btn: QPushButton = QPushButton("新建课程表")
        cv_new_btn.setFont(QFont("Microsoft YaHei", 11))
        cv_new_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cv_new_btn.setMinimumHeight(36)
        cv_new_btn.clicked.connect(self._on_new_curriculum)
        cv_btn_row.addWidget(cv_new_btn)

        cv_btn_row.addStretch()

        # 按钮样式（与时间表按钮相同）
        self._style_timetable_buttons(cv_load_btn, cv_new_btn)

        cv_indent_layout.addLayout(cv_btn_row)

        # ---- 状态标签（卡片式）----
        self._curriculum_status_card = QFrame()
        self._curriculum_status_card.setStyleSheet(self._get_status_card_style())
        cv_status_card_layout: QVBoxLayout = QVBoxLayout(self._curriculum_status_card)
        cv_status_card_layout.setContentsMargins(14, 10, 14, 10)

        self._curriculum_status_label = QLabel(self._get_curriculum_status_text())
        self._curriculum_status_label.setFont(QFont("Microsoft YaHei", 10))
        self._curriculum_status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        cv_status_card_layout.addWidget(self._curriculum_status_label)
        cv_indent_layout.addWidget(self._curriculum_status_card)

        # ---- 课程表表格（带外框）----
        self._curriculum_table_frame = QFrame()
        self._curriculum_table_frame.setStyleSheet(self._get_table_frame_style())
        cv_table_frame_layout: QVBoxLayout = QVBoxLayout(self._curriculum_table_frame)
        cv_table_frame_layout.setContentsMargins(1, 1, 1, 1)

        self._curriculum_table = QTableWidget()
        # 8 列：行标签 + 周一～周日
        self._curriculum_table.setColumnCount(8)
        self._curriculum_table.setHorizontalHeaderLabels(
            ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        )
        self._curriculum_table.setSelectionBehavior(QAbstractItemView.SelectItems)  # type: ignore
        self._curriculum_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # type: ignore
        self._curriculum_table.setAlternatingRowColors(True)
        self._curriculum_table.setShowGrid(True)
        self._curriculum_table.horizontalHeader().setStretchLastSection(True)
        self._curriculum_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch  # type: ignore
        )
        self._curriculum_table.verticalHeader().setVisible(False)
        self._curriculum_table.cellClicked.connect(self._on_curriculum_cell_clicked)
        self._style_curriculum_table()

        cv_table_frame_layout.addWidget(self._curriculum_table)
        cv_indent_layout.addWidget(self._curriculum_table_frame)

        # ---- 课程表内联编辑器卡片（初始隐藏，点击单元格后显示）----
        self._cv_editor_card = self._build_curriculum_editor_card()
        self._cv_editor_card.setVisible(False)
        cv_indent_layout.addWidget(self._cv_editor_card)

        # 将"课程表"缩进容器添加到主布局
        layout.addWidget(cv_indent)

        # 底部弹簧：吸收多余空白区域，避免表格下方出现大片空白
        layout.addStretch()

        # 初始加载数据
        self._refresh_table()

        # ---- 将 page 包裹在 QScrollArea 中，防止表格被压缩 ----
        scroll: QScrollArea = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)

        # 启用鼠标拖拽滑动（手指/鼠标按住后拖动即可滚动）
        QScroller.grabGesture(
            scroll.viewport(),
            QScroller.LeftMouseButtonGesture  # type: ignore
        )

        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(128, 128, 128, 0.5);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore

        return scroll

    # ================================================================
    #  状态文本
    # ================================================================
    def _get_status_text(self) -> str:
        """生成当前状态标签文字。"""
        if self._schedule_data is None:
            return "状态：未加载数据"
        path: str = self._schedule_data.timetable_path
        fname: str = os.path.basename(path) if path else "未知"
        count: int = len(self._schedule_data.timetable_data)
        return f"状态：已加载 {fname}（共 {count} 条）"

    # ================================================================
    #  刷新表格
    # ================================================================
    def _refresh_table(self) -> None:
        """根据当前 schedule_data 刷新表格内容。"""
        if self._timetable_table is None:
            return

        self._timetable_table.setRowCount(0)

        if self._schedule_data is None:
            if self._status_label:
                self._status_label.setText(self._get_status_text())
            # 仍需刷新课程表（清空显示）
            self._refresh_curriculum_table()
            return

        data: Dict = self._schedule_data.timetable_data
        row: int = 0

        for key, value in data.items():
            self._timetable_table.insertRow(row)

            if key.startswith('lesson_'):
                # 课时条目
                lesson_num: str = key.replace('lesson_', '')
                start_time: str = '—'
                end_time: str = '—'
                if isinstance(value, list) and len(value) >= 2:
                    start_time = self._fmt_time(value[0])
                    end_time = self._fmt_time(value[1])

                self._set_table_row(row, lesson_num, '课时', start_time, end_time, key)
            elif key.startswith('dividerline_'):
                # 分隔线条目
                self._set_table_row(row, '—', '分隔线', '—', '—', key)

            row += 1

        if self._status_label:
            self._status_label.setText(self._get_status_text())

        # 根据实际行高和表头高度精确计算表格高度，自适应内容不留空白
        row_count: int = self._timetable_table.rowCount()
        # 表头高度
        h_header: int = self._timetable_table.horizontalHeader().height()
        # 所有数据行高度（逐行累加，适配不同 DPI / 字体下的实际行高）
        h_rows: int = 0
        for r in range(row_count):
            h_rows += self._timetable_table.rowHeight(r)
        # 表格外框宽度（上下边框各 frameWidth px）
        h_frame: int = self._timetable_table.frameWidth() * 2
        exact_h: int = h_header + h_rows + h_frame
        self._timetable_table.setFixedHeight(exact_h)

        # 同步刷新课程表表格（其行结构依赖时间表数据）
        self._refresh_curriculum_table()

    def _set_table_row(self, row: int, seq: str, etype: str,
                       start: str, end: str, key: str) -> None:
        """填充表格的一行数据。"""
        items = [
            (seq, seq),
            (etype, etype),
            (start, start),
            (end, end),
        ]
        fc: str = self._theme.font_color

        for col, (text, _data) in enumerate(items):
            item: QTableWidgetItem = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)  # type: ignore
            item.setForeground(QColor(fc))  # type: ignore
            # 在第一列存储 key 用于编辑时检索
            if col == 0:
                item.setData(Qt.UserRole, key)  # type: ignore
            self._timetable_table.setItem(row, col, item)  # type: ignore

    @staticmethod
    def _fmt_time(time_str: str) -> str:
        """将 '8:00:00' 格式化为 '08:00'。"""
        parts: list = time_str.split(':')
        if len(parts) >= 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return time_str

    # ================================================================
    #  状态卡片样式
    # ================================================================
    def _get_status_card_style(self) -> str:
        """返回状态标签卡片的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.04)'
            card_border: str = 'rgba(255,255,255,0.08)'
        else:
            card_bg = 'rgba(0,0,0,0.03)'
            card_border = 'rgba(0,0,0,0.06)'

        return f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
            }}
        """

    # ================================================================
    #  表格外框样式
    # ================================================================
    def _get_table_frame_style(self) -> str:
        """返回表格外框的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            frame_border: str = 'rgba(255,255,255,0.10)'
        else:
            frame_border = 'rgba(0,0,0,0.10)'

        return f"""
            QFrame {{
                background: transparent;
                border: 1px solid {frame_border};
                border-radius: 8px;
            }}
        """

    # ================================================================
    #  表格样式
    # ================================================================
    def _style_table(self) -> None:
        """根据主题刷新表格样式。"""
        fc: str = self._theme.font_color
        bc: str = self._theme.root_back_color

        if self._theme.theme == 'darkcolor':
            header_bg: str = '#2d2d2d'
            alt_bg: str = '#252525'
            sel_bg: str = 'rgba(255,255,255,0.08)'
            hover_bg: str = 'rgba(255,255,255,0.04)'
        else:
            header_bg = '#f5f5f5'
            alt_bg = '#fafafa'
            sel_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.02)'

        assert self._timetable_table is not None
        self._timetable_table.setStyleSheet(f""" # type: ignore  # pyright: ignore[reportOptionalMemberAccess]
            QTableWidget {{
                background-color: {bc};
                color: {fc};
                border: none;
                border-radius: 7px;
            }}
            QTableWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid transparent;
            }}
            QTableWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTableWidget::item:selected {{
                background-color: {sel_bg};
                color: {fc};
            }}
            QTableWidget::item:alternate {{
                background-color: {alt_bg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {fc};
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 10px 12px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    # ================================================================
    #  按钮样式
    # ================================================================
    def _style_timetable_buttons(self, load_btn: QPushButton,
                                  new_btn: QPushButton) -> None:
        """刷新时间表操作按钮样式。"""
        fc: str = self._theme.font_color
        border: str = self._theme.border_color

        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.04)'
            hover_bg: str = 'rgba(255,255,255,0.08)'
            pressed_bg: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.03)'
            hover_bg = 'rgba(0,0,0,0.06)'
            pressed_bg = 'rgba(0,0,0,0.10)'

        style: str = f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 18px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """
        load_btn.setStyleSheet(style)
        new_btn.setStyleSheet(style)

    def _get_add_btn_style(self) -> str:
        """返回新加条目按钮的样式（实色强调）。"""
        fc: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.12)'
            pressed_bg: str = 'rgba(255,255,255,0.16)'
            border: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
            pressed_bg = 'rgba(0,0,0,0.12)'
            border = 'rgba(0,0,0,0.12)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-color: {self._theme.border_color};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """

    # ================================================================
    #  事件：加载时间表
    # ================================================================
    def _on_load_timetable(self) -> None:
        """打开文件对话框选择 JSON 文件加载为当前时间表。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        start_dir: str = os.path.join(script_dir, 'Config', 'timetable')

        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载时间表", start_dir,
            "JSON 文件 (*.json);;所有文件 (*)"
        )

        if not file_path:
            return

        # 计算相对路径
        try:
            rel_path: str = os.path.relpath(file_path, script_dir)
        except ValueError:
            rel_path = file_path

        logger.info(f"加载时间表：{rel_path}")

        if self._schedule_data is not None:
            self._schedule_data.reload_timetable(rel_path)
            self._refresh_table()
            self.timetable_changed.emit()

    # ================================================================
    #  事件：新建时间表
    # ================================================================
    def _on_new_timetable(self) -> None:
        """弹出新建时间表对话框。"""
        dialog: NewTimetableDialog = NewTimetableDialog(
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            new_name: str = dialog.result_name()
            copy_from: str = dialog.result_copy_from()
            self._create_new_timetable_file(new_name, copy_from)

    def _create_new_timetable_file(self, name: str, copy_from: str) -> None:
        """创建新的时间表 JSON 文件并加载。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        timetable_dir: str = os.path.join(script_dir, 'Config', 'timetable')
        os.makedirs(timetable_dir, exist_ok=True)

        new_path: str = os.path.join(timetable_dir, name)

        if copy_from:
            # 从已有文件复制
            src_path: str = os.path.join(timetable_dir, copy_from)
            try:
                with open(src_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"复制时间表模板失败：{e}")
                data = {"lesson_1": ["8:00:00", "8:40:00"]}
        else:
            # 空白模板（默认第一节课 7:00–7:40）
            data = {"lesson_1": ["7:00:00", "7:40:00"]}

        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"创建时间表文件失败：{e}")
            return

        logger.info(f"已创建新时间表：{name}（模板={'复制 ' + copy_from if copy_from else '空白'}）")

        # 加载新文件
        rel_path: str = f"Config/timetable/{name}"
        if self._schedule_data is not None:
            self._schedule_data.reload_timetable(rel_path)
            self._refresh_table()
            self.timetable_changed.emit()

    # ================================================================
    #  事件：双击条目 → 编辑
    # ================================================================
    def _on_entry_double_clicked(self, row: int, _col: int) -> None:
        """双击表格行，打开编辑对话框。"""
        item: Optional[QTableWidgetItem] = self._timetable_table.item(row, 0) # type: ignore
        if item is None:
            return

        key: str = item.data(Qt.UserRole)  # type: ignore
        data: Dict = self._schedule_data.timetable_data # type: ignore

        if key not in data:
            return

        is_lesson: bool = key.startswith('lesson_')
        start_time: str = '08:00'
        end_time: str = '08:40'

        if is_lesson:
            val = data[key]
            if isinstance(val, list) and len(val) >= 2:
                start_time = self._fmt_time(val[0])
                end_time = self._fmt_time(val[1])

        dialog: TimetableEntryDialog = TimetableEntryDialog(
            entry_type='lesson' if is_lesson else 'dividerline',
            start_time=start_time,
            end_time=end_time,
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            result: dict = dialog.result()
            if result['type'] == 'lesson':
                # 保存为 HH:MM:SS 格式
                data[key] = [
                    f"{result['start_time']}:00",
                    f"{result['end_time']}:00",
                ]
            else:
                data[key] = "-"

            if self._schedule_data is not None:
                self._schedule_data.save_timetable()
            self._refresh_table()
            self.timetable_changed.emit()

    # ================================================================
    #  事件：新加条目
    # ================================================================
    def _calculate_default_times(self) -> tuple:
        """根据上一节课的结束时间计算新条目的默认起止时间。

        规则：
          - 开始时间 = 上一节课结束时间 + 10 分钟
          - 结束时间 = 开始时间 + 40 分钟
          - 若无现有课时，默认 7:00–7:40
        """
        data: Dict = self._schedule_data.timetable_data  # type: ignore

        # 收集所有课时的结束时间，按 lesson_N 序号排序
        last_end_minutes: Optional[int] = None
        for key in data:
            if key.startswith('lesson_'):
                val = data[key]
                if isinstance(val, list) and len(val) >= 2:
                    try:
                        parts = val[1].split(':')
                        h, m = int(parts[0]), int(parts[1])
                        end_mins = h * 60 + m
                        if last_end_minutes is None or end_mins > last_end_minutes:
                            last_end_minutes = end_mins
                    except (ValueError, IndexError):
                        pass

        if last_end_minutes is None:
            # 无现有课时，默认 7:00–7:40
            return '07:00', '07:40'

        # 开始时间 = 最后结束时间 + 10 分钟
        start_mins: int = last_end_minutes + 10
        start_h: int = (start_mins // 60) % 24
        start_m: int = start_mins % 60

        # 结束时间 = 开始时间 + 40 分钟
        end_mins: int = start_mins + 40
        end_h: int = (end_mins // 60) % 24
        end_m: int = end_mins % 60

        return f"{start_h:02d}:{start_m:02d}", f"{end_h:02d}:{end_m:02d}"

    def _on_add_entry(self) -> None:
        """弹出条目编辑器添加新条目（非模态，可连续添加）。"""
        # 若已有打开的添加对话框，激活它
        if self._add_dialog is not None and self._add_dialog.isVisible():
            self._add_dialog.raise_()
            self._add_dialog.activateWindow()
            return

        # 根据上一节课计算默认时间
        start_time, end_time = self._calculate_default_times()

        dialog: TimetableEntryDialog = TimetableEntryDialog(
            entry_type='lesson',
            start_time=start_time,
            end_time=end_time,
            theme_manager=self._theme,
            parent=self,
            stay_open=True,
        )
        dialog.entry_confirmed.connect(self._on_entry_confirmed)
        self._add_dialog = dialog
        dialog.show()

    def _on_entry_confirmed(self, etype: str,
                            start_time: str, end_time: str) -> None:
        """处理新建条目对话框的确认信号（不关闭对话框）。"""
        data: Dict = self._schedule_data.timetable_data  # type: ignore

        if etype == 'lesson':
            lesson_nums: List[int] = []
            for k in data:
                if k.startswith('lesson_'):
                    try:
                        lesson_nums.append(int(k.replace('lesson_', '')))
                    except ValueError:
                        pass
            next_num: int = max(lesson_nums) + 1 if lesson_nums else 1
            new_key: str = f"lesson_{next_num}"
            data[new_key] = [
                f"{start_time}:00",
                f"{end_time}:00",
            ]
        else:
            div_nums: List[int] = []
            for k in data:
                if k.startswith('dividerline_'):
                    try:
                        div_nums.append(int(k.replace('dividerline_', '')))
                    except ValueError:
                        pass
            next_num = max(div_nums) + 1 if div_nums else 1
            new_key = f"dividerline_{next_num}"
            data[new_key] = "-"

        if self._schedule_data is not None:
            self._schedule_data.save_timetable()
        self._refresh_table()
        self.timetable_changed.emit()

        # 计算下一次默认时间（结束时间 + 10 分钟开始，+ 40 分钟结束）
        next_start_time, next_end_time = self._calculate_default_times()

        # 在对话框中显示结果
        lesson_label: str = (
            f"第{next_num}节课" if etype == 'lesson'
            else f"分隔线{next_num}"
        )
        if self._add_dialog is not None:
            self._add_dialog.show_result(
                lesson_label, start_time, end_time,
                next_start_time, next_end_time,
            )

    # ================================================================
    #  课程表 — 状态文本
    # ================================================================
    def _get_curriculum_status_text(self) -> str:
        """生成课程表状态标签文字。"""
        if self._schedule_data is None:
            return "状态：未加载数据"
        path: str = self._schedule_data.curriculum_path
        fname: str = os.path.basename(path) if path else "未知"
        # 统计总科目数（所有天的非空科目之和）
        total_subjects: int = 0
        for day_data in self._schedule_data.curriculum_data.values():
            if isinstance(day_data, dict):
                total_subjects += len([
                    v for v in day_data.values()
                    if v and isinstance(v, str) and v.strip()
                ])
        return f"状态：已加载 {fname}（共 {total_subjects} 个科目设置）"

    # ================================================================
    #  课程表 — 刷新表格
    # ================================================================
    def _refresh_curriculum_table(self) -> None:
        """根据 timetable_data 和 curriculum_data 刷新课程表表格。"""
        if self._curriculum_table is None:
            return

        self._curriculum_table.setRowCount(0)

        if self._schedule_data is None:
            if self._curriculum_status_label:
                self._curriculum_status_label.setText(
                    self._get_curriculum_status_text()
                )
            return

        timetable: Dict = self._schedule_data.timetable_data
        curriculum: Dict = self._schedule_data.curriculum_data
        day_names: List[str] = [
            'Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday'
        ]
        fc: str = self._theme.font_color

        row: int = 0
        for key, value in timetable.items():
            self._curriculum_table.insertRow(row)

            if key.startswith('lesson_'):
                # 课时行：第1列为标签，其余7列显示科目
                lesson_num: str = key.replace('lesson_', '')
                # 构建时间范围字符串
                time_str: str = ''
                if isinstance(value, list) and len(value) >= 2:
                    time_str = (
                        f"{self._fmt_time(value[0])}–"
                        f"{self._fmt_time(value[1])}"
                    )
                label_text: str = f"第{lesson_num}节\n{time_str}"

                label_item: QTableWidgetItem = QTableWidgetItem(label_text)
                label_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                label_item.setForeground(QColor(fc))  # type: ignore
                label_item.setData(Qt.UserRole, key)  # type: ignore
                self._curriculum_table.setItem(row, 0, label_item)  # type: ignore

                # 填充每一天的科目
                for day_idx, day_name in enumerate(day_names):
                    day_data: Dict = curriculum.get(day_name, {})
                    subject: str = day_data.get(key, '')
                    cell_text: str = subject if subject else '—'

                    cell_item: QTableWidgetItem = QTableWidgetItem(cell_text)
                    cell_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                    if subject and subject.strip():
                        cell_item.setForeground(QColor(fc))  # type: ignore
                    else:
                        # 空科目用半透明颜色显示 "—"
                        dim_color: str = (
                            'rgba(255,255,255,0.25)'
                            if self._theme.theme == 'darkcolor'
                            else 'rgba(0,0,0,0.25)'
                        )
                        cell_item.setForeground(QColor(dim_color))  # type: ignore
                    # 存储 (day_name, lesson_key) 用于点击编辑
                    cell_item.setData(
                        Qt.UserRole,  # type: ignore
                        {'day': day_name, 'lesson': key}
                    )
                    self._curriculum_table.setItem(  # type: ignore
                        row, day_idx + 1, cell_item
                    )

            elif key.startswith('dividerline_'):
                # 分隔线行：合并为一整行
                divider_item: QTableWidgetItem = QTableWidgetItem(
                    "————— 分隔线 —————"
                )
                divider_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                dim_color: str = (
                    'rgba(255,255,255,0.30)'
                    if self._theme.theme == 'darkcolor'
                    else 'rgba(0,0,0,0.30)'
                )
                divider_item.setForeground(QColor(dim_color))  # type: ignore
                divider_item.setData(Qt.UserRole, '__divider__')  # type: ignore
                self._curriculum_table.setItem(row, 0, divider_item)  # type: ignore
                # 其余列留空（透明占位）
                for col in range(1, 8):
                    empty_item: QTableWidgetItem = QTableWidgetItem('')
                    empty_item.setFlags(Qt.NoItemFlags)  # type: ignore
                    self._curriculum_table.setItem(row, col, empty_item)  # type: ignore
                # 合并该行所有列
                self._curriculum_table.setSpan(row, 0, 1, 8)

            row += 1

        if self._curriculum_status_label:
            self._curriculum_status_label.setText(
                self._get_curriculum_status_text()
            )

        # 自适应行高
        row_count: int = self._curriculum_table.rowCount()
        h_header: int = self._curriculum_table.horizontalHeader().height()
        h_rows: int = 0
        for r in range(row_count):
            h_rows += self._curriculum_table.rowHeight(r)
        h_frame: int = self._curriculum_table.frameWidth() * 2
        exact_h: int = h_header + h_rows + h_frame + 50  # +50 for two-line labels
        self._curriculum_table.setMinimumHeight(exact_h)

    # ================================================================
    #  课程表 — 单元格点击 → 启动内联编辑器
    # ================================================================
    def _on_curriculum_cell_clicked(self, row: int, col: int) -> None:
        """点击课程表单元格，启动光标闪烁并显示内联编辑器卡片。"""
        if self._curriculum_table is None:
            return
        # 忽略行标签列（col 0）和分隔线行
        if col == 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is None:
            return
        cell_data = item.data(Qt.UserRole)  # type: ignore
        if not isinstance(cell_data, dict):
            return

        day_name: str = cell_data['day']
        lesson_key: str = cell_data['lesson']

        # 如果已有编辑器在运行，先停止旧光标
        self._stop_cv_blink()

        # 深拷贝当前课程表数据作为待编辑副本
        if self._schedule_data is not None:
            self._pending_curriculum_data = copy.deepcopy(
                self._schedule_data.curriculum_data
            )

        # 记录光标位置
        self._cv_cursor_row = row
        self._cv_cursor_col = col
        self._cv_cursor_day = day_name
        self._cv_cursor_lesson = lesson_key

        # 显示编辑器卡片
        if self._cv_editor_card is not None:
            self._cv_editor_card.setVisible(True)

        # 启动闪烁光标
        self._start_cv_blink()

        # 刷新编辑器状态和高亮
        self._refresh_cv_editor_status()

    # ================================================================
    #  课程表内联编辑器 — 构建卡片
    # ================================================================
    def _build_curriculum_editor_card(self) -> QFrame:
        """构建课程表内联编辑器卡片控件（左7右3布局，参照快捷编辑窗口）。"""
        fc: str = self._theme.font_color

        card: QFrame = QFrame()
        card.setStyleSheet(self._get_cv_card_style())
        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        # ════════════════════════════════════════════════════════
        #  状态区（消息气泡样式，横跨整个卡片顶部）
        # ════════════════════════════════════════════════════════
        # 状态标签背景色（消息气泡质感）
        if self._theme.theme == 'darkcolor':
            bubble_bg: str = 'rgba(255,255,255,0.06)'
            bubble_border: str = 'rgba(255,255,255,0.10)'
        else:
            bubble_bg = 'rgba(0,0,0,0.04)'
            bubble_border = 'rgba(0,0,0,0.08)'

        status_bubble: QFrame = QFrame()
        status_bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {bubble_bg};
                border: 1px solid {bubble_border};
                border-radius: 10px;
            }}
        """)
        bubble_layout: QVBoxLayout = QVBoxLayout(status_bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)

        self._cv_status_label = QLabel("")
        self._cv_status_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))  # type: ignore
        self._cv_status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        self._cv_status_label.setWordWrap(True)
        bubble_layout.addWidget(self._cv_status_label)

        card_layout.addWidget(status_bubble)

        # ════════════════════════════════════════════════════════
        #  主体区域：左7（科目按钮）+ 竖分割线 + 右3（方向键 + 操作按钮）
        # ════════════════════════════════════════════════════════
        body_row: QHBoxLayout = QHBoxLayout()
        body_row.setSpacing(0)

        # ---- 左侧：科目按钮区（滚动区域，占 70%）----
        self._load_cv_subject_categories()
        btn_style: str = self._get_cv_subject_btn_style()

        subjects_scroll: QScrollArea = QScrollArea()
        subjects_scroll.setWidgetResizable(True)
        subjects_scroll.setMaximumHeight(200)
        subjects_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 0.3);
                border-radius: 3px;
                min-height: 20px;
            }
        """)

        subjects_widget: QWidget = QWidget()
        subjects_widget.setStyleSheet("background: transparent;")
        subjects_layout: QVBoxLayout = QVBoxLayout(subjects_widget)
        subjects_layout.setContentsMargins(0, 0, 0, 0)
        subjects_layout.setSpacing(6)

        dim_color: str = (
            'rgba(255,255,255,0.50)' if self._theme.theme == 'darkcolor'
            else 'rgba(0,0,0,0.50)'
        )

        self._cv_subject_buttons.clear()
        for cat_name, subjects in self._cv_subject_categories.items():
            # 类别标题
            cat_title: QLabel = QLabel(f"—— {cat_name} ——")
            cat_title.setFont(QFont("Microsoft YaHei", 10))
            cat_title.setStyleSheet(
                f"color: {dim_color}; background: transparent;"
            )
            subjects_layout.addWidget(cat_title)

            # 科目按钮流式布局（自动换行）
            flow_widget: QWidget = QWidget()
            flow_widget.setStyleSheet("background: transparent;")
            flow_layout: QHBoxLayout = QHBoxLayout(flow_widget)
            flow_layout.setContentsMargins(0, 0, 0, 0)
            flow_layout.setSpacing(6)

            for subject in subjects:
                btn: QPushButton = QPushButton(subject)
                btn.setFont(QFont("Microsoft YaHei", 11))
                btn.setCursor(Qt.PointingHandCursor)  # type: ignore
                btn.setMinimumHeight(32)
                btn.setMinimumWidth(44)
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(
                    lambda checked=False, s=subject: self._on_cv_subject_clicked(s)
                )
                self._cv_subject_buttons.append(btn)
                flow_layout.addWidget(btn)

            flow_layout.addStretch()
            subjects_layout.addWidget(flow_widget)

        subjects_layout.addStretch()
        subjects_scroll.setWidget(subjects_widget)
        body_row.addWidget(subjects_scroll, stretch=7)

        # ---- 竖分割线（区分科目区与操作区）----
        v_sep: QFrame = QFrame()
        v_sep.setFrameShape(QFrame.VLine)  # type: ignore
        v_sep.setStyleSheet(f"""
            border: none;
            border-left: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        body_row.addWidget(v_sep)
        body_row.addSpacing(12)

        # ---- 右侧：操作区（占 30%）----
        right_panel: QWidget = QWidget()
        right_panel.setStyleSheet("background: transparent;")
        right_layout: QVBoxLayout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        nav_style: str = self._get_cv_nav_btn_style()

        # 计算导航按钮统一宽度（取最长文字所需宽度）
        nav_btn_width: int = 130

        # -- D-Pad 方向键 --
        dpad: QWidget = QWidget()
        dpad.setStyleSheet("background: transparent;")
        dpad_layout: QVBoxLayout = QVBoxLayout(dpad)
        dpad_layout.setContentsMargins(0, 0, 0, 0)
        dpad_layout.setSpacing(4)

        # 上
        btn_up: QPushButton = QPushButton("▲ 上一节")
        btn_up.setFont(QFont("Microsoft YaHei", 10))
        btn_up.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_up.setMinimumHeight(32)
        btn_up.setFixedWidth(nav_btn_width)
        btn_up.setStyleSheet(nav_style)
        btn_up.clicked.connect(lambda: self._on_cv_navigate('up'))
        dpad_layout.addWidget(btn_up, alignment=Qt.AlignCenter)  # type: ignore

        # 左 右
        lr_row: QHBoxLayout = QHBoxLayout()
        lr_row.setSpacing(4)
        lr_row.setAlignment(Qt.AlignCenter)  # type: ignore

        btn_left: QPushButton = QPushButton("◀ 前一天")
        btn_left.setFont(QFont("Microsoft YaHei", 10))
        btn_left.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_left.setMinimumHeight(32)
        btn_left.setFixedWidth(nav_btn_width)
        btn_left.setStyleSheet(nav_style)
        btn_left.clicked.connect(lambda: self._on_cv_navigate('left'))
        lr_row.addWidget(btn_left)

        btn_right: QPushButton = QPushButton("后一天 ▶")
        btn_right.setFont(QFont("Microsoft YaHei", 10))
        btn_right.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_right.setMinimumHeight(32)
        btn_right.setFixedWidth(nav_btn_width)
        btn_right.setStyleSheet(nav_style)
        btn_right.clicked.connect(lambda: self._on_cv_navigate('right'))
        lr_row.addWidget(btn_right)

        dpad_layout.addLayout(lr_row)

        # 下
        btn_down: QPushButton = QPushButton("▼ 下一节")
        btn_down.setFont(QFont("Microsoft YaHei", 10))
        btn_down.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_down.setMinimumHeight(32)
        btn_down.setFixedWidth(nav_btn_width)
        btn_down.setStyleSheet(nav_style)
        btn_down.clicked.connect(lambda: self._on_cv_navigate('down'))
        dpad_layout.addWidget(btn_down, alignment=Qt.AlignCenter)  # type: ignore

        right_layout.addWidget(dpad)

        # 分割线
        sep: QFrame = QFrame()
        sep.setFrameShape(QFrame.HLine)  # type: ignore
        sep.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        right_layout.addWidget(sep)

        # -- 操作按钮（垂直排列）--
        confirm_btn: QPushButton = QPushButton("确认保存")
        confirm_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))  # type: ignore
        confirm_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        confirm_btn.setMinimumHeight(34)
        confirm_btn.clicked.connect(self._on_cv_confirm)
        right_layout.addWidget(confirm_btn)

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        cancel_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self._on_cv_cancel)
        right_layout.addWidget(cancel_btn)

        clear_btn: QPushButton = QPushButton("清除")
        clear_btn.setFont(QFont("Microsoft YaHei", 10))
        clear_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        clear_btn.setMinimumHeight(32)
        clear_btn.clicked.connect(self._on_cv_clear)
        right_layout.addWidget(clear_btn)

        right_layout.addStretch()

        body_row.addWidget(right_panel, stretch=3)

        card_layout.addLayout(body_row)

        return card

    # ================================================================
    #  课程表内联编辑器 — 加载科目配置
    # ================================================================
    def _load_cv_subject_categories(self) -> None:
        """从 subject_config.json 加载科目分类到缓存。"""
        if self._cv_subject_categories:
            return  # 已缓存

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(
            script_dir, 'Config', 'subject_config.json'
        )
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                subject_types = config_data.get('Subject_Types', {})
                for cat_name, subjects in subject_types.items():
                    if isinstance(subjects, list):
                        self._cv_subject_categories[cat_name] = subjects
                    elif subjects == 'None' or subjects is None:
                        self._cv_subject_categories[cat_name] = ['None']
            else:
                self._cv_subject_categories = {'Category_1': []}
        except Exception as e:
            logger.error(f"读取科目配置失败：{e}")
            self._cv_subject_categories = {'Category_1': []}

    # ================================================================
    #  课程表内联编辑器 — 闪烁光标
    # ================================================================
    def _start_cv_blink(self) -> None:
        """启动单元格闪烁光标。"""
        if self._cv_blink_timer.isActive():
            self._cv_blink_timer.stop()
        self._cv_blink_on = False
        # 禁用表格选中，防止 CSS :selected 样式覆盖光标背景
        if self._curriculum_table is not None:
            self._curriculum_table.setSelectionMode(
                QAbstractItemView.NoSelection  # type: ignore
            )
            self._curriculum_table.clearSelection()
        self._cv_blink_timer.start()

    def _stop_cv_blink(self) -> None:
        """停止闪烁光标，恢复单元格背景，隐藏编辑器卡片。"""
        if self._cv_blink_timer.isActive():
            self._cv_blink_timer.stop()
        # 恢复当前光标单元格背景
        self._restore_cv_cell_bg()
        self._cv_blink_on = False
        # 恢复表格选中模式
        if self._curriculum_table is not None:
            self._curriculum_table.setSelectionMode(
                QAbstractItemView.SingleSelection  # type: ignore
            )
        # 隐藏编辑器卡片
        if self._cv_editor_card is not None:
            self._cv_editor_card.setVisible(False)
        # 取消所有科目按钮高亮
        for btn in self._cv_subject_buttons:
            btn.setProperty('selected', 'false')  # type: ignore
            btn.setStyleSheet(self._get_cv_subject_btn_style())
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

    def _toggle_cv_blink(self) -> None:
        """切换光标单元格的闪烁状态（由 QTimer 触发）。"""
        if self._curriculum_table is None:
            return
        row: int = self._cv_cursor_row
        col: int = self._cv_cursor_col
        if row < 0 or col < 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is None:
            return

        if self._cv_blink_on:
            # 恢复常态
            item.setBackground(QColor(0, 0, 0, 0))  # transparent
        else:
            # 蓝色高亮光标
            if self._theme.theme == 'darkcolor':
                item.setBackground(QColor(33, 150, 243, 77))   # ~30% alpha
            else:
                item.setBackground(QColor(33, 150, 243, 77))

        self._cv_blink_on = not self._cv_blink_on

    def _restore_cv_cell_bg(self) -> None:
        """恢复当前光标单元格的背景为透明。"""
        if self._curriculum_table is None:
            return
        row: int = self._cv_cursor_row
        col: int = self._cv_cursor_col
        if row < 0 or col < 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is not None:
            item.setBackground(QColor(0, 0, 0, 0))

    # ================================================================
    #  课程表内联编辑器 — 科目点击（直接修改，无需确认）
    # ================================================================
    def _on_cv_subject_clicked(self, subject: str) -> None:
        """科目按钮点击：直接修改当前光标单元格的科目。"""
        day: str = self._cv_cursor_day
        lesson: str = self._cv_cursor_lesson
        if not day or not lesson:
            return

        # "None" 科目等同于清空
        new_subject: str = '' if subject == 'None' else subject

        # 更新待编辑数据
        if day not in self._pending_curriculum_data:
            self._pending_curriculum_data[day] = {}
        if new_subject:
            self._pending_curriculum_data[day][lesson] = new_subject
        else:
            self._pending_curriculum_data[day].pop(lesson, None)

        # 直接更新表格单元格显示
        if self._curriculum_table is not None:
            row: int = self._cv_cursor_row
            col: int = self._cv_cursor_col
            item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
            if item is not None:
                cell_text: str = new_subject if new_subject else '—'
                item.setText(cell_text)
                fc: str = self._theme.font_color
                if new_subject:
                    item.setForeground(QColor(fc))
                else:
                    dim_color: str = (
                        'rgba(255,255,255,0.25)'
                        if self._theme.theme == 'darkcolor'
                        else 'rgba(0,0,0,0.25)'
                    )
                    item.setForeground(QColor(dim_color))

        # 刷新编辑器状态和高亮按钮
        self._refresh_cv_editor_status()

        # 高亮当前科目按钮
        self._highlight_cv_subject_btn(subject)

        logger.info(
            f"课程表内联编辑：{day} {lesson} → "
            f"{new_subject or '（清除）'}"
        )

    # ================================================================
    #  课程表内联编辑器 — 导航
    # ================================================================
    def _on_cv_navigate(self, direction: str) -> None:
        """移动光标到相邻单元格。"""
        if self._curriculum_table is None:
            return

        day_names: List[str] = [
            'Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday',
        ]

        # 获取当前天在列表中的索引
        try:
            day_idx: int = day_names.index(self._cv_cursor_day)
        except ValueError:
            return

        # 获取所有课时行（跳过非 lesson 行）
        lesson_rows: List[int] = []
        lesson_keys: List[str] = []
        for r in range(self._curriculum_table.rowCount()):
            label_item: Optional[QTableWidgetItem] = (
                self._curriculum_table.item(r, 0)
            )
            if label_item is None:
                continue
            key = label_item.data(Qt.UserRole)  # type: ignore
            if isinstance(key, str) and key.startswith('lesson_'):
                lesson_rows.append(r)
                lesson_keys.append(key)

        if not lesson_rows:
            return

        # 获取当前 lesson 在列表中的索引
        try:
            lesson_idx: int = lesson_keys.index(self._cv_cursor_lesson)
        except ValueError:
            return

        new_day_idx: int = day_idx
        new_lesson_idx: int = lesson_idx

        if direction == 'left':
            new_day_idx = (day_idx - 1) % 7
        elif direction == 'right':
            new_day_idx = (day_idx + 1) % 7
        elif direction == 'up':
            new_lesson_idx = (lesson_idx - 1) % len(lesson_keys)
        elif direction == 'down':
            new_lesson_idx = (lesson_idx + 1) % len(lesson_keys)

        # 停止旧光标
        self._restore_cv_cell_bg()
        self._cv_blink_on = False

        # 更新光标位置
        new_row: int = lesson_rows[new_lesson_idx]
        new_col: int = new_day_idx + 1  # col 0 是行标签
        new_day: str = day_names[new_day_idx]
        new_lesson: str = lesson_keys[new_lesson_idx]

        self._cv_cursor_row = new_row
        self._cv_cursor_col = new_col
        self._cv_cursor_day = new_day
        self._cv_cursor_lesson = new_lesson

        # 刷新状态和按钮高亮
        self._refresh_cv_editor_status()

        # 重启发闪烁
        self._start_cv_blink()

        logger.info(f"课程表光标导航：{direction} → {new_day} {new_lesson}")

    # ================================================================
    #  课程表内联编辑器 — 清除
    # ================================================================
    def _on_cv_clear(self) -> None:
        """清除当前光标单元格的科目。"""
        self._on_cv_subject_clicked('None')

    # ================================================================
    #  课程表内联编辑器 — 确认保存
    # ================================================================
    def _on_cv_confirm(self) -> None:
        """弹出二次确认对话框，确认后保存课程表并关闭编辑器。"""
        reply: QMessageBox.StandardButton = QMessageBox.question(
            self,
            "确认保存",
            "是否保存课程表修改？\n\n修改内容将写入课程表文件。",
            QMessageBox.Yes | QMessageBox.No,  # type: ignore
            QMessageBox.No,  # type: ignore
        )

        if reply == QMessageBox.Yes:  # type: ignore
            # 应用待编辑数据
            if self._schedule_data is not None:
                self._schedule_data.curriculum_data = (
                    self._pending_curriculum_data
                )
                self._schedule_data.save_curriculum()
                logger.info("课程表修改已确认并保存")

            # 停止光标并隐藏编辑器
            self._stop_cv_blink()
            # 刷新课程表状态
            self._refresh_curriculum_status()
        else:
            logger.info("课程表修改：用户取消确认，保持编辑状态")

    # ================================================================
    #  课程表内联编辑器 — 取消
    # ================================================================
    def _on_cv_cancel(self) -> None:
        """取消编辑：丢弃待编辑数据，恢复表格显示，关闭编辑器。"""
        logger.info("课程表修改已取消，丢弃待编辑数据")
        self._stop_cv_blink()
        # 从原始数据刷新表格
        self._refresh_curriculum_table()

    # ================================================================
    #  课程表内联编辑器 — 刷新状态显示
    # ================================================================
    def _refresh_cv_editor_status(self) -> None:
        """刷新编辑器卡片中的状态标签和科目按钮高亮。"""
        if self._cv_status_label is None:
            return

        day_labels: Dict[str, str] = {
            'Monday': '周一', 'Tuesday': '周二', 'Wednesday': '周三',
            'Thursday': '周四', 'Friday': '周五', 'Saturday': '周六',
            'Sunday': '周日',
        }
        day_label: str = day_labels.get(self._cv_cursor_day,
                                        self._cv_cursor_day)
        lesson_num: str = self._cv_cursor_lesson.replace('lesson_', '')

        # 获取时间信息
        time_info: str = ''
        if self._schedule_data is not None:
            timetable_val = self._schedule_data.timetable_data.get(
                self._cv_cursor_lesson
            )
            if isinstance(timetable_val, list) and len(timetable_val) >= 2:
                time_info = (
                    f"{self._fmt_time(timetable_val[0])}–"
                    f"{self._fmt_time(timetable_val[1])}"
                )

        # 获取当前科目（从待编辑数据中读取）
        current_subject: str = ''
        day_data: Dict = self._pending_curriculum_data.get(
            self._cv_cursor_day, {}
        )
        if isinstance(day_data, dict):
            current_subject = day_data.get(self._cv_cursor_lesson, '')

        status_text: str = (
            f"📍 {day_label} · 第{lesson_num}节"
        )
        if time_info:
            status_text += f" ({time_info})"
        if current_subject:
            status_text += f"\n当前科目：{current_subject}"
        else:
            status_text += "\n当前科目：（未设置）"

        self._cv_status_label.setText(status_text)

        # 高亮当前科目对应的按钮
        self._highlight_cv_subject_btn(current_subject)

    def _highlight_cv_subject_btn(self, subject: str) -> None:
        """高亮指定科目的按钮（取消其他按钮高亮）。"""
        target: str = subject if subject else 'None'
        for btn in self._cv_subject_buttons:
            if btn.text() == target:
                btn.setProperty('selected', 'true')  # type: ignore
            else:
                btn.setProperty('selected', 'false')  # type: ignore
            btn.setStyleSheet(self._get_cv_subject_btn_style())
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

    # ================================================================
    #  课程表内联编辑器 — 样式方法
    # ================================================================
    def _get_cv_card_style(self) -> str:
        """返回编辑器卡片的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.05)'
            card_border: str = 'rgba(33, 150, 243, 0.25)'
        else:
            card_bg = 'rgba(33, 150, 243, 0.03)'
            card_border = 'rgba(33, 150, 243, 0.20)'

        return f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 10px;
            }}
        """

    def _get_cv_nav_btn_style(self) -> str:
        """返回导航按钮的 QSS 样式。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.14)'
            border: str = 'rgba(255,255,255,0.10)'
        else:
            bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
            border = 'rgba(0,0,0,0.10)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """

    def _get_cv_subject_btn_style(self) -> str:
        """返回科目按钮的 QSS 样式。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.14)'
            sel_bg: str = 'rgba(76, 175, 80, 0.25)'
            sel_border: str = 'rgba(76, 175, 80, 0.50)'
            border: str = 'rgba(255,255,255,0.10)'
        else:
            bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
            sel_bg = 'rgba(76, 175, 80, 0.15)'
            sel_border = 'rgba(76, 175, 80, 0.40)'
            border = 'rgba(0,0,0,0.10)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton[selected="true"] {{
                background-color: {sel_bg};
                border-color: {sel_border};
            }}
        """

    # ================================================================
    #  课程表 — 加载
    # ================================================================
    def _on_load_curriculum(self) -> None:
        """打开文件对话框选择 JSON 文件加载为当前课程表。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        start_dir: str = os.path.join(script_dir, 'Config', 'curriculum')

        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载课程表", start_dir,
            "JSON 文件 (*.json);;所有文件 (*)"
        )

        if not file_path:
            return

        try:
            rel_path: str = os.path.relpath(file_path, script_dir)
        except ValueError:
            rel_path = file_path

        logger.info(f"加载课程表：{rel_path}")

        if self._schedule_data is not None:
            self._schedule_data.reload_curriculum(rel_path)
            self._refresh_curriculum_table()

    # ================================================================
    #  课程表 — 新建
    # ================================================================
    def _on_new_curriculum(self) -> None:
        """弹出新建课程表对话框。"""
        dialog: NewCurriculumDialog = NewCurriculumDialog(
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            new_name: str = dialog.result_name()
            copy_from: str = dialog.result_copy_from()
            self._create_new_curriculum_file(new_name, copy_from)

    def _create_new_curriculum_file(self, name: str, copy_from: str) -> None:
        """创建新的课程表 JSON 文件并加载。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        curriculum_dir: str = os.path.join(script_dir, 'Config', 'curriculum')
        os.makedirs(curriculum_dir, exist_ok=True)

        new_path: str = os.path.join(curriculum_dir, name)

        if copy_from:
            src_path: str = os.path.join(curriculum_dir, copy_from)
            try:
                with open(src_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"复制课程表模板失败：{e}")
                data = {
                    "Monday": {}, "Tuesday": {}, "Wednesday": {},
                    "Thursday": {}, "Friday": {}, "Saturday": {},
                    "Sunday": {},
                }
        else:
            # 空白 7 天模板
            data = {
                "Monday": {}, "Tuesday": {}, "Wednesday": {},
                "Thursday": {}, "Friday": {}, "Saturday": {},
                "Sunday": {},
            }

        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"创建课程表文件失败：{e}")
            return

        logger.info(
            f"已创建新课程表：{name}"
            f"（模板={'复制 ' + copy_from if copy_from else '空白'}）"
        )

        rel_path: str = f"Config/curriculum/{name}"
        if self._schedule_data is not None:
            self._schedule_data.reload_curriculum(rel_path)
            self._refresh_curriculum_table()

    # ================================================================
    #  课程表 — 表格样式
    # ================================================================
    def _style_curriculum_table(self) -> None:
        """根据主题刷新课程表表格样式。"""
        if self._curriculum_table is None:
            return

        fc: str = self._theme.font_color
        bc: str = self._theme.root_back_color

        if self._theme.theme == 'darkcolor':
            header_bg: str = '#2d2d2d'
            alt_bg: str = '#252525'
            sel_bg: str = 'rgba(255,255,255,0.08)'
            hover_bg: str = 'rgba(255,255,255,0.04)'
            grid_color: str = 'rgba(255,255,255,0.06)'
        else:
            header_bg = '#f5f5f5'
            alt_bg = '#fafafa'
            sel_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.02)'
            grid_color = 'rgba(0,0,0,0.06)'

        self._curriculum_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bc};
                color: {fc};
                border: none;
                border-radius: 7px;
                gridline-color: {grid_color};
            }}
            QTableWidget::item {{
                padding: 8px 6px;
            }}
            QTableWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTableWidget::item:selected {{
                background-color: {sel_bg};
                color: {fc};
            }}
            QTableWidget::item:alternate {{
                background-color: {alt_bg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {fc};
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 10px 6px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    # ================================================================
    #  课程表 — 刷新状态
    # ================================================================
    def _refresh_curriculum_status(self) -> None:
        """刷新课程表状态标签文字。"""
        if self._curriculum_status_label is not None:
            self._curriculum_status_label.setText(
                self._get_curriculum_status_text()
            )

    # ================================================================
    #  主题刷新（覆盖基类）
    # ================================================================
    def refresh_theme(self) -> None:
        """主题变更后刷新所有样式。"""
        super().refresh_theme()
        self._refresh_nav_styles()
        self._refresh_exit_btn_style()
        if self._status_card is not None:
            self._status_card.setStyleSheet(self._get_status_card_style())
        if self._status_label is not None:
            self._status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._table_frame is not None:
            self._table_frame.setStyleSheet(self._get_table_frame_style())
        if self._timetable_table is not None:
            self._style_table()
        # 刷新课程表 UI
        if self._curriculum_status_card is not None:
            self._curriculum_status_card.setStyleSheet(
                self._get_status_card_style()
            )
        if self._curriculum_status_label is not None:
            self._curriculum_status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._curriculum_table_frame is not None:
            self._curriculum_table_frame.setStyleSheet(
                self._get_table_frame_style()
            )
        if self._curriculum_table is not None:
            self._style_curriculum_table()
        # 刷新课程表内联编辑器
        if self._cv_editor_card is not None:
            self._cv_editor_card.setStyleSheet(self._get_cv_card_style())
        if self._cv_status_label is not None:
            self._cv_status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        # 重刷科目按钮样式
        btn_style: str = self._get_cv_subject_btn_style()
        for btn in self._cv_subject_buttons:
            btn.setStyleSheet(btn_style)
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

    # ================================================================
    #  导航按钮样式刷新
    # ================================================================
    def _refresh_nav_styles(self) -> None:
        """根据当前选中项和主题刷新所有导航按钮的样式。"""
        font_color: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            active_bg: str = "rgba(255, 255, 255, 0.08)"
            active_border: str = "rgba(255, 255, 255, 0.15)"
            hover_bg: str = "rgba(255, 255, 255, 0.04)"
            dim_color: str = "rgba(255, 255, 255, 0.50)"
        else:
            active_bg = "rgba(0, 0, 0, 0.06)"
            active_border = "rgba(0, 0, 0, 0.10)"
            hover_bg = "rgba(0, 0, 0, 0.03)"
            dim_color = "rgba(0, 0, 0, 0.45)"

        for i, btn in enumerate(self._nav_buttons):
            is_active: bool = (i == self._current_index)

            if is_active:
                style: str = f"""
                    QPushButton {{
                        color: {font_color};
                        background: {active_bg};
                        border: 1px solid {active_border};
                        border-radius: 6px;
                        padding: 10px 14px;
                        text-align: left;
                        font-weight: bold;
                    }}
                """
            else:
                style = f"""
                    QPushButton {{
                        color: {dim_color};
                        background: transparent;
                        border: 1px solid transparent;
                        border-radius: 6px;
                        padding: 10px 14px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        color: {font_color};
                        background: {hover_bg};
                        border: 1px solid {self._theme.border_color};
                    }}
                """

            btn.setStyleSheet(style)

    # ================================================================
    #  导航点击处理
    # ================================================================
    def _on_nav_clicked(self, index: int) -> None:
        """
        处理左侧导航按钮点击。
        -------------------
        参数：
            index（int）：目标页面索引（0-3）
        """
        logger.info(f"[SettingsWindow] 导航切换至页面 {index}：{self.NAV_ITEMS[index][1]}")
        self._current_index = index
        self._stack.setCurrentIndex(index)
        self._refresh_nav_styles()

    # ================================================================
    #  退出按钮
    # ================================================================
    def _on_exit_clicked(self) -> None:
        """点击退出按钮：隐藏设置窗口。"""
        logger.info("[SettingsWindow] 退出按钮被点击 → 隐藏窗口")
        self.hide()

    def _refresh_exit_btn_style(self) -> None:
        """刷新退出按钮的样式（与未选中导航按钮一致但 hover 为红色调）。"""
        font_color: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            dim_color: str = "rgba(255, 255, 255, 0.50)"
            hover_bg: str = "rgba(244, 67, 54, 0.15)"
            hover_border: str = "rgba(244, 67, 54, 0.35)"
        else:
            dim_color = "rgba(0, 0, 0, 0.45)"
            hover_bg = "rgba(244, 67, 54, 0.10)"
            hover_border = "rgba(244, 67, 54, 0.30)"

        if self._exit_btn is not None:
            self._exit_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {dim_color};
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                    padding: 10px 14px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    color: {font_color};
                    background: {hover_bg};
                    border: 1px solid {hover_border};
                }}
            """)

    # ================================================================
    #  关闭事件：仅隐藏窗口，不销毁
    # ================================================================
    def closeEvent(self, event: QCloseEvent) -> None:
        """
        重写关闭事件：点击标题栏 ✕ 或按 Alt+F4 时隐藏窗口，
        不触发销毁，以便再次打开时复用。
        """
        logger.info("[SettingsWindow] 关闭事件 → 隐藏窗口")
        event.ignore()
        self.hide()


# ==================== 时间表条目编辑对话框 ====================


class TimetableEntryDialog(QDialog):
    """
    # TimetableEntryDialog — 时间表条目编辑子窗口

    用于新增或编辑时间表中的一条记录。
    支持两种类型：
      - 课时：需要设置开始和结束时间（内嵌滚轮控件）
      - 分隔线：不需要时间设置

    支持两种模式：
      - 编辑模式（stay_open=False）：模态弹窗，确认后关闭
      - 新建模式（stay_open=True）： 非模态，确认后保持打开，显示反馈
    ---
    """

    # 信号：新建模式下条目确认（类型, 开始时间, 结束时间）
    entry_confirmed = Signal(str, str, str)

    def __init__(self, entry_type: str = 'lesson',
                 start_time: str = '08:00',
                 end_time: str = '08:40',
                 theme_manager: Optional[ThemeManager] = None,
                 parent: Optional[QWidget] = None,
                 stay_open: bool = False) -> None:
        """
        初始化条目编辑对话框。

        参数：
            entry_type    （str）：'lesson' 或 'dividerline'
            start_time    （str）：课时开始时间 HH:MM
            end_time      （str）：课时结束时间 HH:MM
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
            stay_open     （bool）：True=新建模式（不关闭），False=编辑模式
        """
        super().__init__(parent)
        self._theme: Optional[ThemeManager] = theme_manager
        self._entry_type: str = entry_type
        self._start_time: str = start_time
        self._end_time: str = end_time
        self._stay_open: bool = stay_open

        self.setWindowTitle('新建条目' if stay_open else '编辑条目')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(not stay_open)
        self.setMinimumWidth(380)

        # 滚轮控件引用
        self._start_hour: Optional[WheelColumn] = None
        self._start_min: Optional[WheelColumn] = None
        self._end_hour: Optional[WheelColumn] = None
        self._end_min: Optional[WheelColumn] = None
        self._result_label: Optional[QLabel] = None
        self._confirm_btn: Optional[QPushButton] = None

        self._setup_ui()
        logger.info(
            f"TimetableEntryDialog 初始化完成"
            f"（类型={entry_type}, stay_open={stay_open}）"
        )

    # ================================================================
    #  主题颜色获取
    # ================================================================
    def _get_wheel_colors(self) -> tuple:
        """根据主题获取滚轮的背景色和文字色。"""
        if self._theme is not None:
            if self._theme.theme == 'lightcolor':
                return '#FFFFFF', '#212121'
            elif self._theme.theme == 'darkcolor':
                return '#252526', '#E0E0E0'
            else:
                return self._theme.back_color, self._theme.font_color
        return '#FFFFFF', '#212121'

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造对话框布局（内嵌时间滚轮控件）。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color if self._theme else '#212121'

        # ---- 类型选择 ----
        type_label: QLabel = QLabel("条目类型：")
        type_label.setFont(QFont("Microsoft YaHei", 12))
        if self._theme:
            type_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(type_label)

        self._lesson_radio: QRadioButton = QRadioButton("课时")
        self._lesson_radio.setFont(QFont("Microsoft YaHei", 11))
        self._divider_radio: QRadioButton = QRadioButton("分隔线")
        self._divider_radio.setFont(QFont("Microsoft YaHei", 11))

        radio_layout: QHBoxLayout = QHBoxLayout()
        radio_layout.addWidget(self._lesson_radio)
        radio_layout.addWidget(self._divider_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        # 默认选中
        if self._entry_type == 'dividerline':
            self._divider_radio.setChecked(True)
        else:
            self._lesson_radio.setChecked(True)

        # ---- 时间滚轮区域（内嵌，替代原来的弹窗按钮）----
        self._time_frame: QFrame = QFrame()
        time_layout: QVBoxLayout = QVBoxLayout(self._time_frame)
        time_layout.setContentsMargins(0, 6, 0, 0)
        time_layout.setSpacing(4)

        bg, tc = self._get_wheel_colors()

        # 解析初始时间
        sh_str, sm_str = self._start_time.split(':')
        fh_str, fm_str = self._end_time.split(':')
        sh: int = int(sh_str)
        sm: int = int(sm_str)
        fh: int = int(fh_str)
        fm: int = int(fm_str)

        hour_items: List[str] = [f"{i:02d}" for i in range(24)]
        min_items: List[str] = [f"{i:02d}" for i in range(60)]

        # 滚轮行（4 列滚轮 + 分隔符）
        wheels_row: QHBoxLayout = QHBoxLayout()
        wheels_row.setSpacing(0)
        wheels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        self._start_hour = WheelColumn(
            hour_items, sh, bg_color=bg, text_color=tc
        )
        self._start_hour.setFixedWidth(60)
        wheels_row.addWidget(self._start_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._start_min = WheelColumn(
            min_items, sm, bg_color=bg, text_color=tc
        )
        self._start_min.setFixedWidth(60)
        wheels_row.addWidget(self._start_min)
        wheels_row.addWidget(self._make_sep('—'))

        self._end_hour = WheelColumn(
            hour_items, fh, bg_color=bg, text_color=tc
        )
        self._end_hour.setFixedWidth(60)
        wheels_row.addWidget(self._end_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._end_min = WheelColumn(
            min_items, fm, bg_color=bg, text_color=tc
        )
        self._end_min.setFixedWidth(60)
        wheels_row.addWidget(self._end_min)

        time_layout.addLayout(wheels_row)

        # 分组标签行（"开始时间" / "结束时间"）
        labels_row: QHBoxLayout = QHBoxLayout()
        labels_row.setSpacing(0)
        labels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        label_alpha: str = (
            "rgba(0,0,0,0.40)" if tc == '#212121'
            else "rgba(255,255,255,0.40)"
        )

        start_lbl: QLabel = QLabel('开始时间')
        start_lbl.setFont(QFont('Microsoft YaHei', 10))
        start_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        start_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        start_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(start_lbl)

        labels_row.addSpacing(16)

        end_lbl: QLabel = QLabel('结束时间')
        end_lbl.setFont(QFont('Microsoft YaHei', 10))
        end_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        end_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        end_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(end_lbl)

        time_layout.addLayout(labels_row)

        layout.addWidget(self._time_frame)

        # ---- 分隔线提示 ----
        self._divider_hint: QLabel = QLabel("分隔线不需要时间设置")
        self._divider_hint.setFont(QFont("Microsoft YaHei", 11))
        self._divider_hint.setStyleSheet("opacity: 0.5;")
        self._divider_hint.setVisible(self._entry_type == 'dividerline')
        layout.addWidget(self._divider_hint)

        # ---- 结果反馈标签（新建模式下显示）----
        self._result_label = QLabel("")
        self._result_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))  # type: ignore
        self._result_label.setStyleSheet(
            "color: #4CAF50; background: transparent; padding: 4px 0;"
        )
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        # ---- 联动：radio 切换 ----
        self._lesson_radio.toggled.connect(self._on_type_changed)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        if self._stay_open:
            done_btn: QPushButton = QPushButton("完成")
            done_btn.setFont(QFont("Microsoft YaHei", 11))
            done_btn.setMinimumHeight(32)
            done_btn.clicked.connect(self.reject)
            btn_row.addWidget(done_btn)
        else:
            cancel_btn: QPushButton = QPushButton("取消")
            cancel_btn.setFont(QFont("Microsoft YaHei", 11))
            cancel_btn.setMinimumHeight(32)
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        self._confirm_btn = QPushButton("确认")
        self._confirm_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        self._confirm_btn.setMinimumHeight(32)
        self._confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._confirm_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._update_visibility()
        self.setFixedSize(self.sizeHint())

    # ================================================================
    #  分隔符标签
    # ================================================================
    def _make_sep(self, text: str) -> QLabel:
        """创建分隔符标签（: 或 —）。"""
        _, tc = self._get_wheel_colors()
        sep_alpha: str = (
            "rgba(0,0,0,0.30)" if tc == '#212121'
            else "rgba(255,255,255,0.35)"
        )
        label: QLabel = QLabel(text)
        label.setFont(QFont('Arial', 22))
        label.setStyleSheet(
            f"color: {sep_alpha}; background: transparent;"
        )
        label.setAlignment(Qt.AlignCenter)  # type: ignore
        label.setFixedWidth(16)
        return label

    # ================================================================
    #  事件处理
    # ================================================================
    def _on_type_changed(self, _checked: bool) -> None:
        """课时/分隔线切换时更新可见区域。"""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """根据当前选择显示/隐藏对应区域。"""
        is_lesson: bool = self._lesson_radio.isChecked()
        self._time_frame.setVisible(is_lesson)
        self._divider_hint.setVisible(not is_lesson)
        # 调整窗口大小以适应内容变化
        self.setFixedSize(self.sizeHint())

    def _on_confirm(self) -> None:
        """确认编辑。

        编辑模式：accept() 关闭对话框。
        新建模式：发射 entry_confirmed 信号，不关闭对话框。
        """
        if self._lesson_radio.isChecked() and self._start_hour is not None:
            st: str = (
                f"{self._start_hour.current_index:02d}:"
                f"{self._start_min.current_index:02d}" # type: ignore
            )
            ft: str = (
                f"{self._end_hour.current_index:02d}:" # type: ignore
                f"{self._end_min.current_index:02d}" # type: ignore
            )
            self._start_time = st
            self._end_time = ft
        else:
            st = self._start_time
            ft = self._end_time

        if self._stay_open:
            etype: str = (
                'lesson' if self._lesson_radio.isChecked()
                else 'dividerline'
            )
            logger.info(
                f"TimetableEntryDialog 确认（新建模式）：{etype} {st} — {ft}"
            )
            self.entry_confirmed.emit(etype, st, ft)
        else:
            logger.info("TimetableEntryDialog 确认（编辑模式）")
            self.accept()

    # ================================================================
    #  公开方法
    # ================================================================
    def show_result(self, lesson_label: str,
                    start_time: str, end_time: str,
                    next_start_time: str = '',
                    next_end_time: str = '') -> None:
        """显示新建结果并自动设置下一次的默认时间。

        参数：
            lesson_label    （str）：如 "第3节课" 或 "分隔线2"
            start_time      （str）：本次开始时间 HH:MM
            end_time        （str）：本次结束时间 HH:MM
            next_start_time （str）：下一次默认开始时间 HH:MM
            next_end_time   （str）：下一次默认结束时间 HH:MM
        """
        if self._result_label is not None:
            self._result_label.setText(
                f"✓ {lesson_label} {start_time}到{end_time}新建完成"
            )
            self._result_label.setVisible(True)

        # 自动设置下一次的默认时间
        if next_start_time and next_end_time:
            try:
                sh, sm = next_start_time.split(':')
                eh, em = next_end_time.split(':')
                if self._start_hour:
                    self._start_hour.set_current_index(int(sh))
                if self._start_min:
                    self._start_min.set_current_index(int(sm))
                if self._end_hour:
                    self._end_hour.set_current_index(int(eh))
                if self._end_min:
                    self._end_min.set_current_index(int(em))
            except (ValueError, IndexError):
                pass

    def result(self) -> dict:  # type: ignore
        """返回编辑结果（编辑模式下使用）。"""
        return {
            'type': (
                'lesson' if self._lesson_radio.isChecked()
                else 'dividerline'
            ),
            'start_time': self._start_time,
            'end_time': self._end_time,
        }


# ==================== 新建时间表对话框 ====================


class NewTimetableDialog(QDialog):
    """
    # NewTimetableDialog — 新建时间表子窗口

    用于命名新时间表并可选择从已有时间表复制。
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化新建时间表对话框。

        参数：
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager

        self.setWindowTitle('新建时间表')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(380)

        self._name_input: Optional[QLineEdit] = None
        self._copy_combo: Optional[QComboBox] = None

        self._setup_ui()
        logger.info("NewTimetableDialog 初始化完成")

    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color

        # ---- 名称输入 ----
        name_label: QLabel = QLabel("时间表名称：")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(name_label)

        default_name: str = ScheduleDataManager.get_next_timetable_name()
        self._name_input = QLineEdit(default_name)
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        layout.addWidget(self._name_input)

        # ---- 复制来源 ----
        copy_label: QLabel = QLabel("从已有时间表复制（可选）：")
        copy_label.setFont(QFont("Microsoft YaHei", 12))
        copy_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(copy_label)

        self._copy_combo = QComboBox()
        self._copy_combo.setFont(QFont("Microsoft YaHei", 11))
        self._copy_combo.setMinimumHeight(32)
        self._copy_combo.addItem("（空白）", "")
        for fname in ScheduleDataManager.get_timetable_files():
            self._copy_combo.addItem(fname, fname)
        layout.addWidget(self._copy_combo)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn: QPushButton = QPushButton("创建")
        create_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        create_btn.setMinimumHeight(32)
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _on_create(self) -> None:
        """点击创建按钮。"""
        name: str = self._name_input.text().strip() if self._name_input else ''
        if not name:
            logger.warning("新建时间表：名称为空")
            return
        if not name.endswith('.json'):
            name += '.json'
        logger.info(f"新建时间表：名称={name}")
        # 名称验证通过，存储在 result_name 中
        self._result_name: str = name
        self._result_copy_from: str = (
            self._copy_combo.currentData() if self._copy_combo else ''
        )
        self.accept()

    def result_name(self) -> str:
        """返回用户输入的名称。"""
        return getattr(self, '_result_name', 'timetable_1.json')

    def result_copy_from(self) -> str:
        """返回选择的复制来源（空字符串表示空白）。"""
        return getattr(self, '_result_copy_from', '')


# ==================== 新建课程表对话框 ====================


class NewCurriculumDialog(QDialog):
    """
    # NewCurriculumDialog — 新建课程表子窗口

    用于命名新课程表并可选择从已有课程表复制。
    结构与 NewTimetableDialog 一致，仅默认命名和目录不同。
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化新建课程表对话框。

        参数：
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager

        self.setWindowTitle('新建课程表')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(380)

        self._name_input: Optional[QLineEdit] = None
        self._copy_combo: Optional[QComboBox] = None

        self._setup_ui()
        logger.info("NewCurriculumDialog 初始化完成")

    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color

        # ---- 名称输入 ----
        name_label: QLabel = QLabel("课程表名称：")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(name_label)

        default_name: str = ScheduleDataManager.get_next_curriculum_name()
        self._name_input = QLineEdit(default_name)
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        layout.addWidget(self._name_input)

        # ---- 复制来源 ----
        copy_label: QLabel = QLabel("从已有课程表复制（可选）：")
        copy_label.setFont(QFont("Microsoft YaHei", 12))
        copy_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(copy_label)

        self._copy_combo = QComboBox()
        self._copy_combo.setFont(QFont("Microsoft YaHei", 11))
        self._copy_combo.setMinimumHeight(32)
        self._copy_combo.addItem("（空白）", "")
        for fname in ScheduleDataManager.get_curriculum_files():
            self._copy_combo.addItem(fname, fname)
        layout.addWidget(self._copy_combo)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn: QPushButton = QPushButton("创建")
        create_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        create_btn.setMinimumHeight(32)
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _on_create(self) -> None:
        """点击创建按钮。"""
        name: str = self._name_input.text().strip() if self._name_input else ''
        if not name:
            logger.warning("新建课程表：名称为空")
            return
        if not name.endswith('.json'):
            name += '.json'
        logger.info(f"新建课程表：名称={name}")
        self._result_name: str = name
        self._result_copy_from: str = (
            self._copy_combo.currentData() if self._copy_combo else ''
        )
        self.accept()

    def result_name(self) -> str:
        """返回用户输入的名称。"""
        return getattr(self, '_result_name', 'table_1.json')

    def result_copy_from(self) -> str:
        """返回选择的复制来源（空字符串表示空白）。"""
        return getattr(self, '_result_copy_from', '')
