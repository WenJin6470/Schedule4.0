"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_quick_edit.py（快捷课表编辑模块）        ║
║                     （科目选择子窗口）                                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责快捷课表编辑功能：
  ✅ SubjectSelectWindow — 科目选择子窗口（左8右2布局）

用户点击主窗口的快捷编辑按钮后弹出此窗口，左侧显示按分类分组的
科目按钮，右侧提供移动光标和确认操作的控制按钮。
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QPainter

from schedule_theme import ThemeManager, ThemedWidget

logger: logging.Logger = logging.getLogger(__name__)


class SubjectSelectWindow(ThemedWidget):
    """
    # SubjectSelectWindow — 快捷课表编辑科目选择窗口

    在用户点击快捷编辑按钮后弹出，提供科目选择和移动控制功能。
    ---

    窗口布局（左:右 = 8:2）：
      ┌──────────────────────────┬──────────┐
      │  Category_1 标题         │ 倍速向上  │
      │  [语文] [数学] [英语]... │          │
      │  ─── 分割线 ───         │  向上    │
      │  Category_2 标题         │          │
      │  [活动] [体育] [信息]... │  向下    │
      │  ─── 分割线 ───         │          │
      │  Category_3 标题         │ 倍速向下  │
      │  [None]                  │          │
      │                          │  确定    │
      └──────────────────────────┴──────────┘

    所有按钮点击均通过 parent_signal 发射统一的 backend_signal，
    动作标识符由后端解析处理。
    """

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager) -> None:
        """
        初始化科目选择窗口。
        -----------------
        参数：
            parent_signal（SignalInstance）：父窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
        """
        # 使用 root_back_color 作为窗口背景
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal

        logger.info("SubjectSelectWindow 初始化开始")
        self._setup_ui()
        logger.info("SubjectSelectWindow 初始化完成")

    # ================================================================
    #  私有方法：创建 UI 元素
    # ================================================================
    def _setup_ui(self) -> None:
        """创建科目选择窗口的所有 UI 元素。"""

        # ----- 窗口属性 -----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.9)

        # 窗口大小和位置（居中偏左，避免遮挡主窗口）
        win_w: int = int(self._theme.screen_width * 0.35)
        win_h: int = int(self._theme.screen_height * 0.65)
        self.setFixedSize(win_w, win_h)
        pos_x: int = (self._theme.screen_width - win_w) // 2 - int(self._theme.screen_width * 0.08)
        pos_y: int = (self._theme.screen_height - win_h) // 2
        self.move(pos_x, pos_y)

        # ----- 主布局：左右 8:2 -----
        main_layout: QHBoxLayout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        left_panel: QWidget = self._build_left_panel()
        main_layout.addWidget(left_panel, stretch=8)

        right_panel: QWidget = self._build_right_panel()
        main_layout.addWidget(right_panel, stretch=2)

        logger.info(f"SubjectSelectWindow UI 创建完成：{win_w}×{win_h}")

    # ================================================================
    #  构建左侧面板：科目按钮（分组 + 分割线）
    # ================================================================
    def _build_left_panel(self) -> QWidget:
        """构建左侧科目按钮面板（可滚动，按分类分组）。"""

        # 滚动区域
        scroll_area: QScrollArea = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: {self._theme.border_color};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        inner_widget: QWidget = QWidget()
        inner_widget.setStyleSheet("background: transparent;")
        inner_layout: QVBoxLayout = QVBoxLayout(inner_widget)
        inner_layout.setContentsMargins(4, 4, 4, 4)
        inner_layout.setSpacing(4)

        # 按钮样式
        btn_style: str = f"""
            QPushButton {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.08);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.25);
                border: 1px solid rgba(128, 128, 128, 0.4);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.35);
            }}
        """

        separator_style: str = f"""
            QFrame {{
                border: none;
                border-top: 1px solid {self._theme.border_color};
                margin: 6px 0px;
                max-height: 1px;
            }}
        """

        category_label_style: str = f"""
            QLabel {{
                color: {self._theme.font_color};
                font-size: 11px;
                font-weight: bold;
                padding: 4px 0px 2px 2px;
                background: transparent;
            }}
        """

        category_names: Dict[str, str] = {
            "Category_1": "文化课",
            "Category_2": "活动课",
            "Category_3": "其他",
        }

        subject_types: Dict = self._theme.subject_config.get("Subject_Types", {})
        category_keys: List[str] = list(subject_types.keys())

        for idx, category_key in enumerate(category_keys):
            if idx > 0:
                sep: QFrame = QFrame()
                sep.setStyleSheet(separator_style)
                sep.setFrameShape(QFrame.HLine)  # type: ignore
                inner_layout.addWidget(sep)

            cat_display_name: str = category_names.get(category_key, category_key)
            cat_label: QLabel = QLabel(cat_display_name)
            cat_label.setStyleSheet(category_label_style)
            inner_layout.addWidget(cat_label)

            subjects = subject_types[category_key]

            if isinstance(subjects, str):
                if subjects.lower() != "none":
                    btn: QPushButton = self._create_subject_button(subjects, btn_style)
                    inner_layout.addWidget(btn)
                else:
                    btn = QPushButton("无")
                    btn.setEnabled(False)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            color: rgba(128, 128, 128, 0.5);
                            background: rgba(128, 128, 128, 0.05);
                            border: 1px solid rgba(128, 128, 128, 0.1);
                            border-radius: 4px;
                            padding: 6px 10px;
                            font-size: 13px;
                        }}
                    """)
                    inner_layout.addWidget(btn)
            elif isinstance(subjects, list):
                buttons_per_row: int = 4
                current_row: Optional[QHBoxLayout] = None

                for i, subject_name in enumerate(subjects):
                    if i % buttons_per_row == 0:
                        current_row = QHBoxLayout()
                        current_row.setSpacing(4)
                        current_row.setContentsMargins(0, 0, 0, 0)
                        inner_layout.addLayout(current_row)

                    btn = self._create_subject_button(subject_name, btn_style)
                    if current_row is not None:
                        current_row.addWidget(btn, stretch=1)

                remaining: int = len(subjects) % buttons_per_row
                if remaining > 0 and current_row is not None:
                    for _ in range(buttons_per_row - remaining):
                        spacer: QWidget = QWidget()
                        spacer.setStyleSheet("background: transparent;")
                        current_row.addWidget(spacer, stretch=1)

        inner_layout.addStretch()
        scroll_area.setWidget(inner_widget)
        return scroll_area

    # ================================================================
    #  创建单个科目按钮
    # ================================================================
    def _create_subject_button(self, subject_name: str, style: str) -> QPushButton:
        """创建一个科目按钮并连接点击信号。"""
        btn: QPushButton = QPushButton(subject_name)
        btn.setStyleSheet(style)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        btn.setMinimumHeight(32)
        btn.clicked.connect(
            lambda checked=False, name=subject_name: self._emit_action(f"subject:{name}")
        )
        return btn

    # ================================================================
    #  构建右侧面板：控制按钮
    # ================================================================
    def _build_right_panel(self) -> QWidget:
        """构建右侧控制按钮面板（5 个按钮竖向排列）。"""

        panel: QWidget = QWidget()
        panel.setStyleSheet("background: transparent;")
        layout: QVBoxLayout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(6)

        ctrl_btn_style: str = f"""
            QPushButton {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.12);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 8px 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.3);
                border: 1px solid rgba(128, 128, 128, 0.5);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.4);
            }}
        """

        confirm_btn_style: str = f"""
            QPushButton {{
                color: #FFFFFF;
                background: rgba(33, 150, 243, 0.7);
                border: 1px solid rgba(33, 150, 243, 0.5);
                border-radius: 4px;
                padding: 8px 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(33, 150, 243, 0.9);
            }}
            QPushButton:pressed {{
                background: rgba(33, 150, 243, 1.0);
            }}
        """

        control_buttons = [
            ("倍速向上", "move_double_up", ctrl_btn_style),
            ("向上",     "move_up",       ctrl_btn_style),
            ("向下",     "move_down",     ctrl_btn_style),
            ("倍速向下", "move_double_down", ctrl_btn_style),
        ]

        layout.addStretch()

        for text, action, style in control_buttons:
            btn: QPushButton = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
            btn.clicked.connect(
                lambda checked=False, a=action: self._emit_action(a)
            )
            layout.addWidget(btn)

        layout.addSpacing(10)

        confirm_btn: QPushButton = QPushButton("确定")
        confirm_btn.setStyleSheet(confirm_btn_style)
        confirm_btn.setMinimumHeight(40)
        confirm_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        confirm_btn.clicked.connect(lambda: self._emit_action("confirm"))
        layout.addWidget(confirm_btn)

        layout.addStretch()

        return panel

    # ================================================================
    #  发射动作信号
    # ================================================================
    def _emit_action(self, action: str) -> None:
        """通过父窗口的 backend_signal 发射动作信号。"""
        logger.info(f"[SubjectSelectWindow] 发射动作: {action}")
        self._parent_signal.emit(action)
