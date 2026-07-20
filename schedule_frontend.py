"""
╔══════════════════════════════════════════════════════════════════════════╗
║         📅 电子课表系统 —— schedule_frontend.py（主窗口模块）              ║
║                    （课表显示主窗口 · 四大按钮入口）                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件是前后端分离架构中的【主窗口前端】，负责：
  ✅ 显示课表课时标签（根据 period_count 动态创建）
  ✅ 底部四按钮栏（全屏时间 / 快捷编辑 / 设置 / 关闭）
  ✅ 提供公开方法供后端修改课时标签内容

📌 架构关系
═══════════════════════════════════════════════════════════════════════════
本窗口是四个主要窗口类之一，通过统一的 ThemeManager 获取主题颜色：
  - schedule_theme.py   — ThemeManager + ThemedWidget（共享基础）
  - schedule_time.py    — TimeWindow + FullscreenTimeWindow（时间模块）
  - schedule_quick_edit.py — SubjectSelectWindow（快捷编辑模块）
  - schedule_settings.py   — SettingsWindow（设置模块）
"""

import logging
import os
from typing import List, Optional

from PySide6.QtWidgets import QLabel, QPushButton
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont, QIcon

from schedule_theme import ThemeManager, ThemedWidget
from schedule_quick_edit import SubjectSelectWindow
from schedule_settings import SettingsWindow

logger: logging.Logger = logging.getLogger(__name__)


class ScheduleMainWindow(ThemedWidget):
    """
    # ScheduleMainWindow — 课表主窗口

    继承 ThemedWidget，负责显示课表科目和四个功能入口按钮。
    ---

    窗口结构：
      ┌──────────────┐
      │   第1节       │
      │   第2节       │
      │   第3节       │
      │   ...        │
      │   第7节       │
      │              │
      │ ⏰ 📝 ⚙ ✕  │  ← 底部按钮栏
      └──────────────┘

    信号：
      backend_signal(str) — 统一后端信号，所有按钮点击均通过此信号发送

    公开 API：
      get_period_label(index)        — 获取指定课时标签
      get_period_count()             — 获取课时总数
      get_all_period_labels()        — 获取所有课时标签列表
    """

    # ================================================================
    #  信号定义
    # ================================================================
    backend_signal = Signal(str)

    # ================================================================
    #  构造函数
    # ================================================================
    def __init__(self, theme_manager: ThemeManager) -> None:
        """
        初始化课表主窗口。
        -----------------
        参数：
            theme_manager（ThemeManager）：全局主题管理器（含配置和颜色）
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        logger.info("=" * 50)
        logger.info("ScheduleMainWindow 初始化开始")

        # ---- 控件引用 ----
        self._subject_window: Optional[SubjectSelectWindow] = None
        self._settings_window: Optional[SettingsWindow] = None

        # ---- 课时标签列表 ----
        self.period_labels: List[QLabel] = []

        # ---- 计算窗口尺寸和位置 ----
        self._win_width: int = int(self._theme.screen_width * (150 / 1920))
        self._win_height: int = int(self._theme.screen_height / 13 * 11)
        self._pos_x: int = int(self._theme.screen_width * (1765 / 1920))
        self._pos_y: int = int(self._theme.screen_height / 12)

        logger.info(f"窗口尺寸：{self._win_width}×{self._win_height}，"
                    f"位置({self._pos_x}, {self._pos_y})")

        # ---- 创建 UI ----
        logger.info("开始创建 UI 元素...")
        self._setup_ui()
        logger.info("ScheduleMainWindow 初始化完成")
        logger.info("=" * 50)

    # ================================================================
    #  私有方法：创建所有 UI 元素
    # ================================================================
    def _setup_ui(self) -> None:
        """创建课表主窗口及其内部控件。"""

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

        # ===== 课时标签区域 =====
        close_btn_height: int = 36
        available_height: int = self._win_height - close_btn_height
        period_count: int = self._theme.period_count
        label_height: int = available_height // period_count if period_count > 0 else available_height

        logger.info(f"创建 {period_count} 个课时标签（每个高度 {label_height}px）...")
        for i in range(period_count):
            label: QLabel = QLabel(self)
            label.setObjectName(f"period_label_{i}")
            label.setFont(QFont("Arial", 12))
            label.setStyleSheet(f"""
                color: {self._theme.font_color};
                background: transparent;
                border-bottom: 1px solid {self._theme.border_color};
            """)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
            label.setGeometry(0, i * label_height, self._win_width, label_height)
            label.setText(f"  第{i + 1}节")
            self.period_labels.append(label)

        # ===== 底部按钮栏（4 个图标按钮）=====
        images_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images')
        icon_suffix: str = self._theme.get_icon_suffix()

        logger.info(f"图标后缀：'{icon_suffix}'（主题={self._theme.theme}）")

        button_configs = [
            ('_fullscreen_btn', 'FullScreenTime', self._on_fullscreen_time_clicked),
            ('_edit_btn',       'EDIT_S',        self._on_quick_edit_clicked),
            ('_settings_btn',   'setting',       self._on_settings_clicked),
            ('_close_btn',      'EXIT',          self._on_close_clicked),
        ]

        btn_size: int = 20
        btn_count: int = len(button_configs)
        total_btn_width: int = btn_count * btn_size
        spacing: int = (self._win_width - total_btn_width) // (btn_count + 1)
        btn_y: int = period_count * label_height + (close_btn_height - btn_size) // 2

        for i, (attr_name, image_base, handler) in enumerate(button_configs):
            icon_path: str = os.path.join(images_dir, f"{image_base}{icon_suffix}.svg")
            btn: QPushButton = QPushButton(self)
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(btn_size, btn_size))
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    padding: 0px;
                }
                QPushButton:hover {
                    background: rgba(128, 128, 128, 0.25);
                    border-radius: 4px;
                }
            """)
            btn.setFixedSize(btn_size, btn_size)
            btn_x: int = spacing + i * (btn_size + spacing)
            btn.move(btn_x, btn_y)
            btn.clicked.connect(handler)
            setattr(self, attr_name, btn)

        logger.info(f"底部按钮栏创建完成：{btn_count} 个图标按钮，间距={spacing}px")

    # ================================================================
    #  按钮点击槽函数
    # ================================================================
    def _on_fullscreen_time_clicked(self) -> None:
        """全屏时间按钮 — 发射 backend_signal('fullscreen_time')。"""
        logger.info("用户点击了全屏时间按钮")
        self.backend_signal.emit("fullscreen_time")

    def _on_quick_edit_clicked(self) -> None:
        """快捷编辑按钮 — 发射信号并显示科目选择子窗口。"""
        logger.info("用户点击了快捷课表编辑按钮")
        self.backend_signal.emit("quick_edit_opened")
        self._show_subject_window()

    def _on_settings_clicked(self) -> None:
        """设置按钮 — 发射信号并显示设置窗口。"""
        logger.info("用户点击了设置按钮")
        self.backend_signal.emit("settings")
        self._show_settings_window()

    def _on_close_clicked(self) -> None:
        """关闭按钮 — 发射 backend_signal('close')。"""
        logger.info("用户点击了关闭按钮")
        if self._subject_window is not None:
            self._subject_window.close()
            self._subject_window = None
        if self._settings_window is not None:
            self._settings_window.close()
            self._settings_window = None
        self.backend_signal.emit("close")

    # ================================================================
    #  私有方法：显示子窗口
    # ================================================================
    def _show_subject_window(self) -> None:
        """显示科目选择子窗口（复用已有实例或新建）。"""
        if self._subject_window is not None:
            # 窗口已存在（可能被隐藏），直接显示
            logger.info("复用已有的科目选择子窗口")
            self._subject_window.show()
            return

        logger.info("创建科目选择子窗口...")
        self._subject_window = SubjectSelectWindow(
            parent_signal=self.backend_signal,
            theme_manager=self._theme,
        )
        self._subject_window.show()
        logger.info("科目选择子窗口已显示")

    def _show_settings_window(self) -> None:
        """创建并显示设置窗口。"""
        if self._settings_window is not None:
            self._settings_window.close()
            self._settings_window = None

        logger.info("创建设置窗口...")
        self._settings_window = SettingsWindow(
            parent_signal=self.backend_signal,
            theme_manager=self._theme,
        )
        self._settings_window.show()
        logger.info("设置窗口已显示")

    # ================================================================
    #  公开 API：课时标签操作
    # ================================================================
    def get_period_label(self, index: int) -> Optional[QLabel]:
        """根据索引获取指定的课时标签控件。"""
        if 0 <= index < len(self.period_labels):
            return self.period_labels[index]
        logger.warning(f"get_period_label: 索引 {index} 越界 (共 {len(self.period_labels)} 个)")
        return None

    def get_period_label_by_name(self, name: str) -> Optional[QLabel]:
        """根据 objectName 获取指定的课时标签控件。"""
        for label in self.period_labels:
            if label.objectName() == name:
                return label
        logger.warning(f"get_period_label_by_name: 未找到名称为 '{name}' 的标签")
        return None

    def get_period_count(self) -> int:
        """获取当前课时数量。"""
        return self._theme.period_count

    def get_all_period_labels(self) -> List[QLabel]:
        """获取所有课时标签控件的列表。"""
        return self.period_labels
