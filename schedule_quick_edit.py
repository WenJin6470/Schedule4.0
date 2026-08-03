"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_quick_edit.py（快捷课表编辑模块）        ║
║                     （科目选择子窗口）                                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责快捷课表编辑功能：
  ✅ SubjectSelectWindow — 科目选择子窗口（标题栏 + 左8右2布局）

用户点击主窗口的快捷编辑按钮后弹出此窗口，左侧显示按分类分组的
科目按钮，右侧提供移动光标和确认操作的控制按钮。
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QFont, QCloseEvent

from schedule_config import ThemeManager, ThemedWidget
from schedule_actions import ActionMessage

logger: logging.Logger = logging.getLogger(__name__)


class SubjectSelectWindow(ThemedWidget):
    """
    # SubjectSelectWindow — 快捷课表编辑科目选择窗口

    在用户点击快捷编辑按钮后弹出，提供科目选择和移动控制功能。
    ---

    窗口布局（使用系统默认标题栏）：
      ┌ 快捷课表编辑 ─────── □ ─ ✕ ┐  ← 系统标题栏（可拖拽移动）
      ├──────────────────────┬──────────┤
      │ ── Category_1 ────── │ 倍速向上 │
      │ [语文][数学][英语]...│          │
      │ ── Category_2 ────── │  向上    │
      │ [活动][体育][信息]...│          │
      │ ── Category_3 ────── │  向下    │  ← 右侧面板（轻微分色）
      │ [None]               │          │
      │                      │ 倍速向下 │
      │                      │          │
      │                      │  确定    │
      └──────────────────────┴──────────┘
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
        # 使用系统默认标题栏：可最小化 / 最大化 / 关闭，可拖拽移动
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowStaysOnTopHint         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
            | Qt.WindowMinimizeButtonHint     # type: ignore
            | Qt.WindowMaximizeButtonHint     # type: ignore
        )
        self.setWindowTitle("快捷课表编辑")
        self.setAutoFillBackground(True)
        self.setWindowOpacity(1.0)

        # 窗口大小和位置
        win_w: int = int(self._theme.screen_width * 0.35)
        win_h: int = int(self._theme.screen_height * 0.65)
        self.setMinimumSize(int(self._theme.screen_width * 0.22), 400)
        self.resize(win_w, win_h)
        pos_x: int = (self._theme.screen_width - win_w) // 2 - int(self._theme.screen_width * 0.08)
        pos_y: int = (self._theme.screen_height - win_h) // 2
        self.move(pos_x, pos_y)

        # ----- 主布局：内容区（左右 8:2）+ 状态栏 ----
        outer_layout: QVBoxLayout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 4)
        outer_layout.setSpacing(0)

        # 内容区：左右 8:2
        content_layout: QHBoxLayout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        left_panel: QWidget = self._build_left_panel()
        content_layout.addWidget(left_panel, stretch=8)

        right_panel: QWidget = self._build_right_panel()
        content_layout.addWidget(right_panel, stretch=2)

        outer_layout.addLayout(content_layout, stretch=1)

        # 状态栏：使用提示
        self._status_label: QLabel = QLabel(
            "上下移动光标，点击左侧科目即可完成修改，最后点击 确认 保存修改"
        )
        hint_font = QFont("Microsoft YaHei", 8)
        hint_font.setItalic(True)
        self._status_label.setFont(hint_font)
        self._status_label.setFixedHeight(24)
        self._status_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            border-top: 1px solid {self._theme.border_color};
            padding: 2px 6px;
        """)
        outer_layout.addWidget(self._status_label)

        logger.info(f"SubjectSelectWindow UI 创建完成：{win_w}×{win_h}")

    # ================================================================
    #  公开方法：更新光标信息显示
    # ================================================================
    def update_cursor_info(self, index: int, subject_text: str) -> None:
        """
        保留方法签名以兼容后端调用，状态栏已改为静态使用提示。
        """
        pass

    # ================================================================
    #  构建左侧面板：科目按钮（分组 + 分割线）
    # ================================================================
    def _build_left_panel(self) -> QWidget:
        """构建左侧科目按钮面板（可滚动，按分类分组，分割线骑缝显示 Category 名）。"""

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
        inner_layout.setContentsMargins(4, 4, 8, 4)
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

        subject_types: Dict = self._theme.subject_config.get("Subject_Types", {})
        category_keys: List[str] = list(subject_types.keys())

        for idx, category_key in enumerate(category_keys):
            # ---- 骑缝分割线：Category 名嵌入在分割线左侧 ----
            if idx > 0:
                inner_layout.addSpacing(4)

            sep_widget: QWidget = self._build_category_separator(category_key)
            inner_layout.addWidget(sep_widget)

            # ---- 科目按钮 ----
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
    #  构建骑缝分割线（Category 名称嵌入在分割线左侧）
    # ================================================================
    def _build_category_separator(self, category_key: str) -> QWidget:
        """
        构建一条水平分割线，Category 名称"骑缝"显示在分割线左侧。

        效果：
          Category_1 ──────────────────────
        （文字坐落在线上，后面跟着横线）
        """
        widget: QWidget = QWidget()
        widget.setFixedHeight(20)

        layout: QHBoxLayout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Category 名称标签 — 左侧
        cat_label: QLabel = QLabel(category_key)
        cat_label.setFont(QFont("Arial", 9))
        cat_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            padding-right: 6px;
            font-weight: bold;
        """)
        cat_label.setFixedHeight(20)
        layout.addWidget(cat_label)

        # 分割线 — 填充剩余空间
        line: QFrame = QFrame()
        line.setFrameShape(QFrame.HLine)  # type: ignore
        line.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        line.setFixedHeight(20)
        layout.addWidget(line, stretch=1)

        return widget

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
            lambda checked=False, name=subject_name: self._emit_action(
                ActionMessage.subject_selected(name)
            )
        )
        return btn

    # ================================================================
    #  构建右侧面板：控制按钮（轻微分色背景）
    # ================================================================
    def _build_right_panel(self) -> QWidget:
        """
        构建右侧控制按钮面板（5 个按钮竖向排列）。
        右侧面板使用轻微分色背景，与左侧形成层次感。
        """

        # 计算分色背景：在 root_back_color 基础上叠加半透明层
        # lightcolor 主题：叠加更深的灰色 → 右侧稍暗
        # darkcolor 主题：叠加更浅的白色 → 右侧稍亮
        if self._theme.theme == 'darkcolor':
            panel_bg: str = "rgba(255, 255, 255, 0.04)"
        else:
            panel_bg = "rgba(0, 0, 0, 0.03)"

        panel: QWidget = QWidget()
        panel.setStyleSheet(f"""
            background: {panel_bg};
            border-left: 1px solid {self._theme.border_color};
            border-radius: 4px;
        """)

        layout: QVBoxLayout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 8, 6, 8)
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
            ("倍速向上", ActionMessage.move_double_up, ctrl_btn_style),
            ("向上",     ActionMessage.move_up,       ctrl_btn_style),
            ("向下",     ActionMessage.move_down,     ctrl_btn_style),
            ("倍速向下", ActionMessage.move_double_down, ctrl_btn_style),
        ]

        layout.addStretch()

        for text, factory, style in control_buttons:
            btn: QPushButton = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
            btn.clicked.connect(
                lambda checked=False, f=factory: self._emit_action(f())
            )
            layout.addWidget(btn)

        layout.addSpacing(10)

        confirm_btn: QPushButton = QPushButton("确定")
        confirm_btn.setStyleSheet(confirm_btn_style)
        confirm_btn.setMinimumHeight(40)
        confirm_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        confirm_btn.clicked.connect(
            lambda: self._emit_action(ActionMessage.confirm())
        )
        layout.addWidget(confirm_btn)

        layout.addStretch()

        return panel

    # ================================================================
    #  关闭事件：仅隐藏窗口，不关闭整个应用
    # ================================================================
    def closeEvent(self, event: QCloseEvent) -> None:
        """
        重写关闭事件：点击标题栏 ✕ 或按 Alt+F4 时通知后端停止光标闪烁，
        然后隐藏窗口，不触发 QApplication 退出。
        """
        logger.info("[SubjectSelectWindow] 关闭事件 → 通知后端、隐藏窗口")
        self._parent_signal.emit(ActionMessage.quick_edit_closed())
        event.ignore()
        self.hide()

    # ================================================================
    #  发射动作信号
    # ================================================================
    def _emit_action(self, msg: ActionMessage) -> None:
        """通过父窗口的 backend_signal 发射结构化动作消息。"""
        logger.info(f"[SubjectSelectWindow] 发射动作: {msg.type.value}")
        self._parent_signal.emit(msg)
