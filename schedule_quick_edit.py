"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_quick_edit.py（快捷课表编辑模块）        ║
║                     （科目选择子窗口）                                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责快捷课表编辑功能：
  ✅ SubjectSelectWindow — 科目选择子窗口（标题栏 + 左8右2布局）
  ✅ WeekScrollWheel      — 星期滚轮控件（切换主页面课表星期）

用户点击主窗口的快捷编辑按钮后弹出此窗口，左侧显示按分类分组的
科目按钮，右侧提供移动光标和确认操作的控制按钮。
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import QFont, QCloseEvent

from schedule_config import ThemeManager, ThemedWidget
from schedule_actions import ActionMessage

logger: logging.Logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ★ 星期滚轮控件 — WeekScrollWheel ★
# ═══════════════════════════════════════════════════════════════════════════


class WeekScrollWheel(QWidget):
    """
    # WeekScrollWheel — 星期滚轮控件

    类似相机滚轮的竖直星期选择器，用于切换主页面显示的课表星期。
    ---

    布局：
        ╭──────────────────╮
        │      ▲ Mon       │  ← 上一星期（颜色稍淡，可点击）
        │──────────────────│
        │       Tue        │  ← 当前星期（加粗突出）
        │──────────────────│
        │      ▼ Wed       │  ← 下一星期（颜色稍淡，可点击）
        ╰──────────────────╯

    交互：
      - 点击上方区域：切换到上一星期
      - 点击下方区域：切换到下一星期
      - 长按上方/下方区域：自动连续滚动（200ms 间隔）
      - 鼠标滚轮：向上滚动切换上一星期，向下切换下一星期
      - 首尾循环：从 Sunday 继续向下回到 Monday，反之亦然

    信号：
      week_changed(int, str) — 星期索引和名称变更通知
    """

    # 星期列表（与课表 JSON 键名一致）
    WEEKS: list = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday', 'Sunday']

    # 长按自动滚动间隔（毫秒）
    _AUTO_SCROLL_INTERVAL: int = 200

    # 星期变更信号
    week_changed = Signal(int, str)

    def __init__(self, theme_manager: ThemeManager,
                 parent: QWidget | None = None) -> None:
        """
        初始化星期滚轮控件。
        ------------------
        参数：
            theme_manager（ThemeManager）：全局主题管理器
            parent       （QWidget | None）：父控件
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._current_index: int = 0  # 默认 Monday

        # 长按自动滚动定时器
        self._scroll_timer: QTimer = QTimer(self)
        self._scroll_timer.setInterval(self._AUTO_SCROLL_INTERVAL)
        self._scroll_timer.timeout.connect(self._on_scroll_timer)
        self._scroll_direction: int = 0  # -1: 上, 1: 下, 0: 停止

        self._setup_ui()
        logger.info("WeekScrollWheel 初始化完成")

    # ================================================================
    #  私有方法：创建 UI
    # ================================================================
    def _setup_ui(self) -> None:
        """创建滚轮的三个标签区域并布局。"""

        # ---- 确定滚轮尺寸 ----
        wheel_width: int = 132
        wheel_height: int = 148
        self.setFixedSize(wheel_width, wheel_height)
        self.setMouseTracking(True)

        # ---- 滚轮外壳样式（轻微内凹效果）----
        if self._theme.theme == 'darkcolor':
            shell_bg: str = "rgba(0, 0, 0, 0.25)"
            shell_border: str = f"2px solid {self._theme.border_color}"
        else:
            shell_bg = "rgba(0, 0, 0, 0.05)"
            shell_border = f"2px solid {self._theme.border_color}"

        self.setStyleSheet(f"""
            WeekScrollWheel {{
                background: {shell_bg};
                border: {shell_border};
                border-radius: 14px;
            }}
        """)

        # ---- 主布局 ----
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)

        # ---- 上方星期按钮（上一星期 / 颜色稍淡）----
        self._upper_btn: QPushButton = QPushButton(self._get_week_text(-1))
        self._upper_btn.setFlat(True)
        self._upper_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._upper_btn.setFixedHeight(40)
        self._upper_btn.setFont(QFont("Arial", 8))
        self._upper_btn.pressed.connect(self._on_upper_pressed)
        self._upper_btn.released.connect(self._on_scroll_released)

        # ---- 中间星期标签（当前星期 / 加粗突出）----
        self._current_label: QLabel = QLabel(self.WEEKS[self._current_index])
        self._current_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self._current_label.setFont(QFont("Arial", 12, QFont.Bold)) # type: ignore
        self._current_label.setFixedHeight(44)

        # ---- 下方星期按钮（下一星期 / 颜色稍淡）----
        self._lower_btn: QPushButton = QPushButton(self._get_week_text(1))
        self._lower_btn.setFlat(True)
        self._lower_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._lower_btn.setFixedHeight(40)
        self._lower_btn.setFont(QFont("Arial", 8))
        self._lower_btn.pressed.connect(self._on_lower_pressed)
        self._lower_btn.released.connect(self._on_scroll_released)

        # ---- 组装布局 ----
        layout.addWidget(self._upper_btn)
        layout.addWidget(self._current_label)
        layout.addWidget(self._lower_btn)

        # ---- 应用样式 ----
        self._refresh_styles()

    # ================================================================
    #  私有方法：获取星期文本（带箭头）
    # ================================================================
    def _get_week_text(self, offset: int) -> str:
        """
        获取距离当前星期 offset 位的星期名（含箭头指示）。
        -------------------------------------------------
        参数：
            offset（int）：偏移量，-1 为上一星期，1 为下一星期

        返回值：
            str：格式化文本，如 "▲ Monday" 或 "▼ Wednesday"
        """
        index: int = (self._current_index + offset) % len(self.WEEKS)
        arrow: str = "▲" if offset < 0 else "▼"
        week_name: str = self.WEEKS[index]
        return f"{arrow} {week_name}"

    # ================================================================
    #  私有方法：刷新三区域样式
    # ================================================================
    def _refresh_styles(self) -> None:
        """根据当前主题刷新所有子控件的样式。"""
        font_color: str = self._theme.font_color
        border_color: str = self._theme.border_color

        # 根据主题计算淡色文字颜色
        if self._theme.theme == 'darkcolor':
            dimmed_color: str = "rgba(255, 255, 255, 0.40)"
            hover_bg: str = "rgba(255, 255, 255, 0.08)"
        else:
            dimmed_color = "rgba(0, 0, 0, 0.35)"
            hover_bg = "rgba(0, 0, 0, 0.06)"

        # ---- 上方 / 下方按钮：淡色样式 ----
        faded_style: str = f"""
            QPushButton {{
                color: {dimmed_color};
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 4px 6px;
                text-align: center;
            }}
            QPushButton:hover {{
                color: {font_color};
                background: {hover_bg};
                border: 1px solid {border_color};
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.20);
                border: 1px solid rgba(128, 128, 128, 0.35);
            }}
        """

        self._upper_btn.setStyleSheet(faded_style)
        self._lower_btn.setStyleSheet(faded_style)

        # ---- 中间标签：加粗突出样式 ----
        current_style: str = f"""
            QLabel {{
                color: {font_color};
                background: rgba(128, 128, 128, 0.10);
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 4px 6px;
            }}
        """
        self._current_label.setStyleSheet(current_style)

    # ================================================================
    #  滚动逻辑
    # ================================================================
    def _scroll_up(self) -> None:
        """滚动到上一星期（索引递减，Sunday → ... → Monday）。"""
        self._current_index = (self._current_index - 1) % len(self.WEEKS)
        self._update_display()
        self.week_changed.emit(self._current_index, self.WEEKS[self._current_index])

    def _scroll_down(self) -> None:
        """滚动到下一星期（索引递增，Monday → ... → Sunday）。"""
        self._current_index = (self._current_index + 1) % len(self.WEEKS)
        self._update_display()
        self.week_changed.emit(self._current_index, self.WEEKS[self._current_index])

    def _update_display(self) -> None:
        """滚动后更新三个标签/按钮的显示文本。"""
        self._upper_btn.setText(self._get_week_text(-1))
        self._current_label.setText(self.WEEKS[self._current_index])
        self._lower_btn.setText(self._get_week_text(1))

    # ================================================================
    #  长按自动滚动（按住鼠标时持续触发）
    # ================================================================
    def _on_upper_pressed(self) -> None:
        """按下上方区域：立即滚动一次，启动长按自动滚动。"""
        self._scroll_up()
        self._scroll_direction = -1
        self._scroll_timer.start()

    def _on_lower_pressed(self) -> None:
        """按下下方区域：立即滚动一次，启动长按自动滚动。"""
        self._scroll_down()
        self._scroll_direction = 1
        self._scroll_timer.start()

    def _on_scroll_released(self) -> None:
        """释放鼠标：停止长按自动滚动。"""
        self._scroll_timer.stop()
        self._scroll_direction = 0

    def _on_scroll_timer(self) -> None:
        """定时器回调：按当前方向持续滚动（长按自动重复）。"""
        if self._scroll_direction == -1:
            self._scroll_up()
        elif self._scroll_direction == 1:
            self._scroll_down()

    # ================================================================
    #  鼠标滚轮事件
    # ================================================================
    #  鼠标滚轮事件
    # ================================================================
    def wheelEvent(self, event) -> None:
        """
        处理鼠标滚轮事件。
        -----------------
        向上滚动（正值）→ 上一星期
        向下滚动（负值）→ 下一星期
        """
        delta = event.angleDelta().y()
        if delta > 0:
            self._scroll_up()
        elif delta < 0:
            self._scroll_down()

    # ================================================================
    #  公开 API
    # ================================================================
    def current_week(self) -> str:
        """获取当前选中的星期名称。"""
        return self.WEEKS[self._current_index]

    def current_index(self) -> int:
        """获取当前选中的星期索引（0=Monday, ..., 6=Sunday）。"""
        return self._current_index

    def set_week(self, index: int) -> None:
        """
        以编程方式设置当前星期。
        ----------------------
        参数：
            index（int）：目标星期索引，自动取模适配
        """
        self._current_index = index % len(self.WEEKS)
        self._update_display()


class SubjectSelectWindow(ThemedWidget):
    """
    # SubjectSelectWindow — 快捷课表编辑科目选择窗口

    在用户点击快捷编辑按钮后弹出，提供科目选择和移动控制功能。
    ---

    窗口布局（使用系统默认标题栏）：
      ┌ 快捷课表编辑 ─────── □ ─ ✕ ┐  ← 系统标题栏（可拖拽移动）
      ├──────────────────────┬──────────┤
      │ ── Category_1 ────── │ 倍速向上 │
      │ [语文][数学][英语]...│  向上    │
      │ ── Category_2 ────── │  向下    │
      │ [活动][体育][信息]...│ 倍速向下 │  ← 右侧面板（轻微分色）
      │ ── Category_3 ────── │          │
      │ [None]               │ ╭────╮   │
      │                      │ │▲ Mon│   │  ← 星期滚轮
      │                      │ │ Tue │   │
      │                      │ │▼ Wed│   │
      │                      │ ╰────╯   │
      │                      │  确定    │
      └──────────────────────┴──────────┘
    """

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager,
                 initial_week: str = 'Monday') -> None:
        """
        初始化科目选择窗口。
        -----------------
        参数：
            parent_signal（SignalInstance）：父窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
            initial_week （str）：           初始显示的星期，默认 'Monday'
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal

        self._initial_week: str = initial_week

        logger.info("SubjectSelectWindow 初始化开始")
        self._setup_ui()
        # 将滚轮同步到初始星期
        self.sync_week(initial_week)
        # 连接滚轮信号 → 父窗口信号
        self._week_wheel.week_changed.connect(self._on_week_changed)
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

        # 窗口大小和位置（左8右2比例，右侧需容纳星期滚轮）
        win_w: int = int(self._theme.screen_width * 0.40)
        win_h: int = int(self._theme.screen_height * 0.65)
        self.setMinimumSize(int(self._theme.screen_width * 0.26), 400)
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
    #  公开方法：更新光标信息显示 / 星期滚轮同步
    # ================================================================
    def update_cursor_info(self, index: int, subject_text: str) -> None:
        """
        保留方法签名以兼容后端调用，状态栏已改为静态使用提示。
        """
        pass

    def sync_week(self, week_name: str) -> None:
        """
        将星期滚轮同步到指定的星期。
        -------------------------
        参数：
            week_name（str）：英文星期名，如 'Monday'
        """
        week_map: dict = {name: i for i, name in enumerate(WeekScrollWheel.WEEKS)}
        index: int = week_map.get(week_name, 0)
        self._week_wheel.set_week(index)

    def _on_week_changed(self, index: int, week_name: str) -> None:
        """
        星期滚轮变动 → 通过父窗口信号通知后端切换课表显示。
        -------------------------------------------------
        参数：
            index     （int）：星期索引
            week_name （str）：星期名称
        """
        logger.info(f"[SubjectSelectWindow] 滚轮切换至：{week_name} (index={index})")
        self._parent_signal.emit(ActionMessage.week_changed(index, week_name))

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
        构建右侧控制按钮面板（4 个方向按钮 + 星期滚轮 + 确认按钮）。
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

        # ---- 星期滚轮（在倍速向下和确定之间）----
        self._week_wheel: WeekScrollWheel = WeekScrollWheel(self._theme)
        # 居中放置滚轮：外层 HBox 包裹实现水平居中
        wheel_wrapper: QHBoxLayout = QHBoxLayout()
        wheel_wrapper.setContentsMargins(0, 0, 0, 0)
        wheel_wrapper.addStretch()
        wheel_wrapper.addWidget(self._week_wheel)
        wheel_wrapper.addStretch()
        layout.addLayout(wheel_wrapper)

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
