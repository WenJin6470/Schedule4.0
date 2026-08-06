"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║               （全屏设置页面 · 左侧导航 + 右侧内容区）                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责全屏设置窗口：
  ✅ SettingsWindow — 全屏设置窗口（系统标题栏 + 左2右8布局）

左侧导航栏从上到下：
  - 图标展示（DAILY_SCHEDULE.svg + Schedule4.0 并排）
  - 基础设置 / 美化 / 课表编辑 / 关于（带 emoji 图标）

右侧为 QStackedWidget，随左侧导航切换内容页面（暂为占位）。
"""

import logging
import os
from typing import List, Optional

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
)
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QFont, QIcon, QCloseEvent

from schedule_config import ThemeManager, ThemedWidget

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

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager) -> None:
        """
        初始化设置窗口。
        ---------------
        参数：
            parent_signal（SignalInstance）：父窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal
        self._nav_buttons: List[QPushButton] = []
        self._exit_btn: Optional[QPushButton] = None
        self._current_index: int = 0

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
        main_layout.addWidget(left_panel, stretch=2)

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
        main_layout.addWidget(right_panel, stretch=8)

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
        使用 QStackedWidget 管理 4 个占位页面，
        随左侧导航按钮切换显示。
        """
        right_panel: QWidget = QWidget()
        right_panel.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(right_panel)
        layout.setContentsMargins(32, 32, 32, 32)

        self._stack: QStackedWidget = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        # 为每个导航项创建占位页面
        page_titles: List[str] = ["基础设置", "美化", "课表编辑", "关于"]
        for title in page_titles:
            page: QWidget = self._create_placeholder_page(title)
            self._stack.addWidget(page)

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
