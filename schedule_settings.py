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

import json
import logging
import os
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QLineEdit, QComboBox, QRadioButton, QFileDialog, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal, SignalInstance
from PySide6.QtGui import QFont, QIcon, QCloseEvent, QColor

from schedule_config import ThemeManager, ThemedWidget, ScheduleDataManager
from schedule_backend import TimeWheelPicker

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
        构建"课表编辑 → 时间表"编辑页面。
        -------------------------------
        包含：
          - 二级标题 "时间表"
          - [加载时间表] [新建时间表] 按钮行
          - 状态标签
          - 条目表格（序号 / 类型 / 开始时间 / 结束时间）
          - [新加条目] 按钮
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
        layout.addWidget(page_title)

        # ---- 缩进容器（时间表板块整体右移）----
        indent: QWidget = QWidget()
        indent.setStyleSheet("background: transparent;")
        indent_layout: QVBoxLayout = QVBoxLayout(indent)
        indent_layout.setContentsMargins(28, 0, 0, 0)
        indent_layout.setSpacing(12)

        # ---- 二级标题：时间表 ----
        section_title: QLabel = QLabel("时间表")
        section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        indent_layout.addWidget(section_title)

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

        indent_layout.addLayout(btn_row)

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
        indent_layout.addWidget(self._status_card)

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
        indent_layout.addWidget(self._table_frame, stretch=1)

        # ---- 新加条目按钮（实色强调）----
        add_btn: QPushButton = QPushButton("＋ 新加条目")
        add_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        add_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        add_btn.setMinimumHeight(38)
        add_btn.clicked.connect(self._on_add_entry)
        add_btn.setStyleSheet(self._get_add_btn_style())
        indent_layout.addWidget(add_btn)

        # 将缩进容器添加到主布局
        layout.addWidget(indent, stretch=1)

        # 初始加载数据
        self._refresh_table()

        return page

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
            # 空白模板
            data = {"lesson_1": ["8:00:00", "8:40:00"]}

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
    def _on_add_entry(self) -> None:
        """弹出条目编辑器添加新条目。"""
        dialog: TimetableEntryDialog = TimetableEntryDialog(
            entry_type='lesson',
            start_time='08:00',
            end_time='08:40',
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            result: dict = dialog.result()
            data: Dict = self._schedule_data.timetable_data # type: ignore

            # 生成新 key
            if result['type'] == 'lesson':
                # 找到下一个可用的 lesson_N
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
                    f"{result['start_time']}:00",
                    f"{result['end_time']}:00",
                ]
            else:
                # 分隔线：找到下一个可用的 dividerline_N
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
      - 课时：需要设置开始和结束时间
      - 分隔线：不需要时间设置
    ---
    """

    def __init__(self, entry_type: str = 'lesson',
                 start_time: str = '08:00',
                 end_time: str = '08:40',
                 theme_manager: Optional[ThemeManager] = None,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化条目编辑对话框。

        参数：
            entry_type    （str）：'lesson' 或 'dividerline'
            start_time    （str）：课时开始时间 HH:MM
            end_time      （str）：课时结束时间 HH:MM
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: Optional[ThemeManager] = theme_manager
        self._entry_type: str = entry_type
        self._start_time: str = start_time
        self._end_time: str = end_time

        self.setWindowTitle('编辑条目')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(320)

        self._setup_ui()
        logger.info(f"TimetableEntryDialog 初始化完成（类型={entry_type}）")

    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ---- 类型选择 ----
        type_label: QLabel = QLabel("条目类型：")
        type_label.setFont(QFont("Microsoft YaHei", 12))
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

        # ---- 时间区域（仅课时有）----
        self._time_frame: QFrame = QFrame()
        time_layout: QVBoxLayout = QVBoxLayout(self._time_frame)
        time_layout.setContentsMargins(0, 4, 0, 0)
        time_layout.setSpacing(8)

        self._time_display: QLabel = QLabel(
            f"当前时间：{self._start_time} — {self._end_time}"
        )
        self._time_display.setFont(QFont("Microsoft YaHei", 11))
        time_layout.addWidget(self._time_display)

        set_time_btn: QPushButton = QPushButton("设置时间")
        set_time_btn.setFont(QFont("Microsoft YaHei", 11))
        set_time_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        set_time_btn.setMinimumHeight(32)
        set_time_btn.clicked.connect(self._on_set_time)
        time_layout.addWidget(set_time_btn)

        layout.addWidget(self._time_frame)

        # 分隔线提示
        self._divider_hint: QLabel = QLabel("分隔线不需要时间设置")
        self._divider_hint.setFont(QFont("Microsoft YaHei", 11))
        self._divider_hint.setStyleSheet("opacity: 0.5;")
        self._divider_hint.setVisible(self._entry_type == 'dividerline')
        layout.addWidget(self._divider_hint)

        # ---- 联动：radio 切换 ----
        self._lesson_radio.toggled.connect(self._on_type_changed)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn: QPushButton = QPushButton("确认")
        confirm_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        confirm_btn.setMinimumHeight(32)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._update_visibility()

    def _on_type_changed(self, _checked: bool) -> None:
        """课时/分隔线切换时更新可见区域。"""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """根据当前选择显示/隐藏对应区域。"""
        is_lesson: bool = self._lesson_radio.isChecked()
        self._time_frame.setVisible(is_lesson)
        self._divider_hint.setVisible(not is_lesson)

    # ================================================================
    #  设置时间
    # ================================================================
    def _on_set_time(self) -> None:
        """打开共享的 TimeWheelPicker 选择时间。"""
        # 获取主题适配的颜色
        if self._theme is not None:
            if self._theme.theme == 'lightcolor':
                bg: str = '#FFFFFF'
                tc: str = '#212121'
            elif self._theme.theme == 'darkcolor':
                bg = '#252526'
                tc = '#E0E0E0'
            else:
                bg = self._theme.back_color
                tc = self._theme.font_color
        else:
            bg = '#FFFFFF'
            tc = '#212121'

        picker: TimeWheelPicker = TimeWheelPicker(
            self._start_time, self._end_time, parent=self,
            bg_color=bg, text_color=tc,
        )
        picker.time_confirmed.connect(self._on_time_confirmed)
        picker.exec()

    def _on_time_confirmed(self, start_time: str, finish_time: str) -> None:
        """时间选择确认后更新显示。"""
        self._start_time = start_time
        self._end_time = finish_time
        self._time_display.setText(
            f"当前时间：{self._start_time} — {self._end_time}"
        )
        logger.info(f"条目时间已更新：{start_time} — {finish_time}")

    # ================================================================
    #  确认
    # ================================================================
    def _on_confirm(self) -> None:
        """确认编辑，接受对话框。"""
        logger.info("TimetableEntryDialog 确认")
        self.accept()

    # ================================================================
    #  获取结果
    # ================================================================
    def result(self) -> dict: # type: ignore
        """返回编辑结果。"""
        return {
            'type': 'lesson' if self._lesson_radio.isChecked() else 'dividerline',
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
