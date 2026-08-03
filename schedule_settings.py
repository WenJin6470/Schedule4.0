"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║                     （设置界面 — 待后续实现）                               ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责设置窗口：
  ✅ SettingsWindow — 设置界面窗口（当前为占位框架）

后续可在此窗口中添加：
  - 主题切换（浅色/深色/彩色自适应）
  - 课时数量调整
  - 语言切换
  - 其他系统参数设置
"""

import logging

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, SignalInstance

from schedule_config import ThemeManager, ThemedWidget

logger: logging.Logger = logging.getLogger(__name__)


class SettingsWindow(ThemedWidget):
    """
    # SettingsWindow — 设置窗口

    占位框架窗口，未来用于系统参数设置。
    ---

    当前包含：
      - 标题标签 "设置"
      - 提示标签 "功能待实现"
      - 关闭按钮
    """

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

        logger.info("SettingsWindow 初始化开始")

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.9)

        # 窗口大小和位置（居中）
        win_w: int = 400
        win_h: int = 300
        self.setFixedSize(win_w, win_h)
        pos_x: int = (self._theme.screen_width - win_w) // 2
        pos_y: int = (self._theme.screen_height - win_h) // 2
        self.move(pos_x, pos_y)

        # ---- 布局 ----
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 标题
        title_label: QLabel = QLabel("设置")
        title_label.setAlignment(Qt.AlignCenter)  # type: ignore
        title_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            font-size: 18px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(title_label)

        # 占位提示
        hint_label: QLabel = QLabel("功能待实现")
        hint_label.setAlignment(Qt.AlignCenter)  # type: ignore
        hint_label.setStyleSheet(f"""
            color: {self._theme.font_color};
            font-size: 14px;
            background: transparent;
            opacity: 0.6;
        """)
        layout.addWidget(hint_label)

        layout.addStretch()

        # 关闭按钮
        close_btn: QPushButton = QPushButton("关闭")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.12);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.25);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.35);
            }}
        """)
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(close_btn)

        logger.info("SettingsWindow 创建完成（默认隐藏）")

    def _on_close(self) -> None:
        """关闭设置窗口。"""
        logger.info("用户关闭设置窗口")
        self.hide()
