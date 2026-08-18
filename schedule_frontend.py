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
  - schedule_config.py  — ThemeManager + ScheduleDataManager + ThemedWidget
  - schedule_time.py    — TimeWindow + FullscreenTimeWindow（时间模块）
  - schedule_quick_edit.py — SubjectSelectWindow（快捷编辑模块）
  - schedule_settings.py   — SettingsWindow（设置模块）
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtWidgets import QLabel, QPushButton, QMenu
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QAction

from schedule_config import ThemeManager, ThemedWidget, ScheduleDataManager, DebugConfig, is_color_dark
from schedule_actions import ActionMessage, ActionType

# ═══════════════════════════════════════════════════════════════════════════
# ★ 启动优化：懒加载子模块 ★
# 将 SubjectSelectWindow 和 SettingsWindow 的 import 从模块顶层移除，
# 改为在 _show_subject_window() / _show_settings_window() 方法内按需导入。
# 避免主窗口构造时加载整个快捷编辑模块（~430行）和设置模块（~130行），
# 显著减少 ScheduleMainWindow.__init__ 的耗时。
# ═══════════════════════════════════════════════════════════════════════════

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
    backend_signal = Signal(ActionMessage)

    # ================================================================
    #  构造函数
    # ================================================================
    def __init__(self, theme_manager: ThemeManager,
                 schedule_data: ScheduleDataManager,
                 debug_config: DebugConfig) -> None:
        """
        初始化课表主窗口。
        -----------------
        参数：
            theme_manager（ThemeManager）：        全局主题管理器（含配置和颜色）
            schedule_data（ScheduleDataManager）： 课表数据管理器（含时间表和课程表数据）
            debug_config（DebugConfig）：          调试配置管理器（含时间覆盖参数）
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        logger.info("=" * 50)
        logger.info("ScheduleMainWindow 初始化开始")

        # ---- 数据引用 ----
        self._schedule_data: ScheduleDataManager = schedule_data
        self._debug_config: DebugConfig = debug_config

        # ---- 控件引用 ----
        self._subject_window: Optional[SubjectSelectWindow] = None # type: ignore
        self._settings_window: Optional[SettingsWindow] = None # type: ignore

        # ---- 光标闪烁状态 ----
        self._cursor_index: int = 0
        self._blink_timer: QTimer = QTimer()
        self._blink_timer.setInterval(500)  # 500ms 闪烁间隔
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_on: bool = False

        # ---- 课时标签列表 ----
        self.period_labels: List[QLabel] = []

        # ---- 当前显示的星期 ----
        self._current_display_day: str = 'Monday'

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

        # ★ 启动优化：暂时禁用界面更新，避免每创建一个控件就触发一次重绘，
        # 在所有控件创建完毕后统一刷新，减少约 15-25% 的 UI 构建时间。
        self.setUpdatesEnabled(False)

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
        divider_height: int = 6
        # 从时间表数据中获取实际课时数和分隔线位置
        lesson_count: int = self._schedule_data.get_lesson_count()
        divider_indices: List[int] = self._schedule_data.get_divider_indices()
        divider_count: int = len(divider_indices)
        available_height: int = self._win_height - close_btn_height
        total_divider_height: int = divider_count * divider_height
        label_height: int = (
            (available_height - total_divider_height) // lesson_count
            if lesson_count > 0 else available_height
        )

        # 获取今天对应星期的课程表（调试模式下使用模拟日期）
        debug_weekday: Optional[str] = self._debug_config.get_weekday_name()
        today_name: str = (
            debug_weekday if debug_weekday is not None
            else datetime.now().strftime('%A')
        )
        today_curriculum: Dict[str, str] = (
            self._schedule_data.get_curriculum_for_day(today_name)
        )

        # 记住当前显示的星期（供后续星期滚轮切换使用）
        self._current_display_day = today_name

        logger.info(
            f"创建课时标签：共 {lesson_count} 节课（含 {divider_count} 条分隔线），"
            f"每个标签高度 {label_height}px，今天={today_name}"
        )

        # 根据主题确定分隔线颜色
        if self._theme.theme == 'lightcolor':
            divider_color: str = '#999999'
        elif self._theme.theme == 'darkcolor':
            divider_color: str = '#AAAAAA'
        else:  # multicolor：根据桌面背景明暗自动选择
            divider_color = '#AAAAAA' if is_color_dark(self._theme.back_color) else '#999999'

        # 按时间表 JSON 键顺序遍历，依次创建课时标签和分隔线
        y_offset: int = 0
        for key in self._schedule_data.timetable_data:
            if key.startswith('lesson_'):
                subject: str = today_curriculum.get(key, '')
                label: QLabel = QLabel(self)
                label.setObjectName(key)
                label.setFont(QFont(self._theme.subject_font, 16))
                label.setStyleSheet(f"""
                    color: {self._theme.font_color};
                    background: transparent;
                """)
                label.setAlignment(Qt.AlignCenter)  # type: ignore
                label.setGeometry(0, y_offset, self._win_width, label_height)
                label.setText(subject)
                self.period_labels.append(label)
                y_offset += label_height
            elif key.startswith('dividerline_'):
                divider: QLabel = QLabel(self)
                divider.setObjectName(key)
                # 水平分割线：透明背景 + 顶部细边框，颜色随主题自适应
                divider.setStyleSheet(
                    f"background: transparent;"
                    f"border-top: 2px solid {divider_color};"
                )
                divider.setGeometry(0, y_offset, self._win_width, divider_height)
                y_offset += divider_height

        # ===== 底部按钮栏（4 个图标按钮）=====
        images_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images', 'Icons')
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
        btn_y: int = y_offset + (close_btn_height - btn_size) // 2

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

        # ★ 启动优化：所有控件创建完毕，恢复界面更新并触发一次性刷新
        self.setUpdatesEnabled(True)

    # ================================================================
    #  按钮点击槽函数
    # ================================================================
    def _on_fullscreen_time_clicked(self) -> None:
        """
        全屏时间按钮 — 弹出模式选择菜单（考试模式 / 创意模式）。
        ------------------------------------------------
        用户点击按钮后，在按钮上方弹出一个下拉菜单，
        让用户选择进入考试模式或创意模式的全屏时间。
        """
        logger.info("用户点击了全屏时间按钮，弹出模式选择菜单")

        # 创建弹出菜单
        menu: QMenu = QMenu(self)
        menu.setFont(QFont("Arial", 11))

        # 菜单样式：与主窗口主题协调
        is_dark: bool = (self._theme.theme == 'darkcolor')
        menu_bg: str = '#2D2D30' if is_dark else '#FFFFFF'
        menu_text: str = '#E0E0E0' if is_dark else '#212121'
        menu_hover: str = '#3E3E42' if is_dark else '#E8E8E8'
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {menu_bg};
                color: {menu_text};
                border: 1px solid rgba(128, 128, 128, 0.3);
                border-radius: 6px;
                padding: 4px 0px;
            }}
            QMenu::item {{
                padding: 8px 32px 8px 16px;
                border-radius: 4px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
            }}
            QMenu::separator {{
                height: 1px;
                background: rgba(128, 128, 128, 0.2);
                margin: 4px 8px;
            }}
        """)

        # 创建两个模式选项
        exam_action: QAction = QAction("📝  考试模式", menu)
        exam_action.setToolTip("纯色背景 + 实时时间")

        creative_action: QAction = QAction("🎨  创意模式", menu)
        creative_action.setToolTip("随机图片背景 + 红色实时时间")

        menu.addAction(exam_action)
        menu.addSeparator()
        menu.addAction(creative_action)

        # 连接动作信号
        exam_action.triggered.connect(
            lambda: self._start_fullscreen_mode('exam')
        )
        creative_action.triggered.connect(
            lambda: self._start_fullscreen_mode('creative')
        )

        # 在按钮上方弹出菜单
        btn: QPushButton = getattr(self, '_fullscreen_btn', None)
        if btn is not None:
            # 弹出在按钮右上方
            menu.exec(btn.mapToGlobal(btn.rect().topRight()))
        else:
            menu.exec(self.mapToGlobal(self.rect().center()))

    def _start_fullscreen_mode(self, mode: str) -> None:
        """
        根据用户选择的模式启动全屏时间。
        ---------------------------
        参数：
            mode（str）：'exam' — 考试模式；'creative' — 创意模式
        """
        if mode == 'exam':
            logger.info("用户选择了考试模式全屏时间")
            self.backend_signal.emit(ActionMessage.fullscreen_time_exam())
        elif mode == 'creative':
            logger.info("用户选择了创意模式全屏时间")
            self.backend_signal.emit(ActionMessage.fullscreen_time_creative())
        else:
            logger.warning(f"未知的全屏时间模式：'{mode}'")

    def _on_quick_edit_clicked(self) -> None:
        """快捷编辑按钮 — 发射信号并显示科目选择子窗口。"""
        logger.info("用户点击了快捷课表编辑按钮")
        self.backend_signal.emit(ActionMessage.quick_edit_opened())
        self._show_subject_window()

    def _on_settings_clicked(self) -> None:
        """设置按钮 — 发射信号并显示设置窗口。"""
        logger.info("用户点击了设置按钮")
        self.backend_signal.emit(ActionMessage.settings())
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
        self.backend_signal.emit(ActionMessage.close())

    # ================================================================
    #  私有方法：显示子窗口
    # ================================================================
    def _show_subject_window(self) -> None:
        """显示科目选择子窗口（复用已有实例或新建）。"""
        if self._subject_window is not None:
            # 窗口已存在（可能被隐藏），同步滚轮到当前显示星期后显示
            logger.info("复用已有的科目选择子窗口")
            self._subject_window.sync_week(self._current_display_day)
            self._subject_window.show()
            return

        # ★ 启动优化：懒加载 — 仅在首次点击快捷编辑按钮时才导入模块
        from schedule_quick_edit import SubjectSelectWindow  # noqa: E402

        logger.info("创建科目选择子窗口...")
        self._subject_window = SubjectSelectWindow(
            parent_signal=self.backend_signal,
            theme_manager=self._theme,
            initial_week=self._current_display_day,
            main_window=self,
        )
        self._subject_window.show() # type: ignore
        logger.info("科目选择子窗口已显示")

    def _show_settings_window(self) -> None:
        """显示全屏设置窗口（复用已有实例或新建）。"""
        if self._settings_window is not None:
            # 窗口已存在（可能被隐藏），直接最大化显示
            logger.info("复用已有的设置窗口")
            self._settings_window.showMaximized()
            return

        # ★ 启动优化：懒加载 — 仅在首次点击设置按钮时才导入模块
        from schedule_settings import SettingsWindow  # noqa: E402

        logger.info("创建设置窗口...")
        self._settings_window = SettingsWindow(
            parent_signal=self.backend_signal,
            theme_manager=self._theme,
            schedule_data=self._schedule_data,
        )
        # 用户应用更改后重建主窗口标签
        self._settings_window.changes_applied.connect(
            self._rebuild_period_labels
        )
        self._settings_window.showMaximized()  # type: ignore
        logger.info("设置窗口已显示")

    # ================================================================
    #  重建课时标签（用户应用更改后调用）
    # ================================================================
    def _rebuild_period_labels(self) -> None:
        """
        时间表或课程表变更后重建所有课时标签和分隔线。

        此方法由设置页面的 changes_applied 信号触发，
        用于同步主窗口的课时显示与新数据。
        """
        logger.info("时间表结构变更，重建主窗口课时标签...")

        # 停止光标闪烁
        self.stop_cursor_blink()

        # 删除所有课时和分隔线标签
        for child in self.findChildren(QLabel):
            objname: str = child.objectName() or ''
            if objname.startswith('lesson_') or objname.startswith('dividerline_'):
                child.deleteLater()

        self.period_labels.clear()

        # 重新计算布局参数
        close_btn_height: int = 36
        divider_height: int = 6
        lesson_count: int = self._schedule_data.get_lesson_count()
        divider_indices: List[int] = self._schedule_data.get_divider_indices()
        divider_count: int = len(divider_indices)
        available_height: int = self._win_height - close_btn_height
        total_divider_height: int = divider_count * divider_height
        label_height: int = (
            (available_height - total_divider_height) // lesson_count
            if lesson_count > 0 else available_height
        )

        # 获取当天课程表数据
        debug_weekday: Optional[str] = self._debug_config.get_weekday_name()
        today_name: str = (
            debug_weekday if debug_weekday is not None
            else datetime.now().strftime('%A')
        )
        today_curriculum: Dict[str, str] = (
            self._schedule_data.get_curriculum_for_day(today_name)
        )
        self._current_display_day = today_name

        # 分隔线颜色
        if self._theme.theme == 'lightcolor':
            divider_color: str = '#999999'
        elif self._theme.theme == 'darkcolor':
            divider_color: str = '#AAAAAA'
        else:
            divider_color = '#AAAAAA' if is_color_dark(self._theme.back_color) else '#999999'

        # 按时间表 JSON 键顺序重新创建标签
        y_offset: int = 0
        for key in self._schedule_data.timetable_data:
            if key.startswith('lesson_'):
                subject: str = today_curriculum.get(key, '')
                label: QLabel = QLabel(self)
                label.setObjectName(key)
                label.setFont(QFont(self._theme.subject_font, 16))
                label.setStyleSheet(f"""
                    color: {self._theme.font_color};
                    background: transparent;
                """)
                label.setAlignment(Qt.AlignCenter)  # type: ignore
                label.setGeometry(0, y_offset, self._win_width, label_height)
                label.setText(subject)
                self.period_labels.append(label)
                y_offset += label_height
            elif key.startswith('dividerline_'):
                divider: QLabel = QLabel(self)
                divider.setObjectName(key)
                divider.setStyleSheet(
                    f"background: transparent;"
                    f"border-top: 2px solid {divider_color};"
                )
                divider.setGeometry(0, y_offset, self._win_width, divider_height)
                y_offset += divider_height

        # 重置光标索引
        self._cursor_index = 0

        logger.info(
            f"课时标签重建完成：共 {len(self.period_labels)} 个标签，"
            f"每个高度 {label_height}px"
        )

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
        """获取当前课时数量（从时间表数据中实际课时数计算）。"""
        return len(self.period_labels)

    def get_all_period_labels(self) -> List[QLabel]:
        """获取所有课时标签控件的列表。"""
        return self.period_labels

    # ================================================================
    #  公开 API：光标闪烁（快捷编辑用）
    # ================================================================

    def start_cursor_blink(self, index: int = 0) -> str:
        """
        在指定索引的课时标签上启动光标闪烁效果。
        --------------------------------------
        通过 QTimer 间歇切换标签背景色，模拟文本编辑器中的光标。

        参数：
            index（int）：要闪烁的标签索引，默认 0（第1节）

        返回值：
            str：该标签当前的文字内容（发送给快捷编辑窗口）
        """
        if index < 0 or index >= len(self.period_labels):
            logger.warning(f"start_cursor_blink: 索引 {index} 越界")
            return ""

        # 先停止之前的闪烁
        self.stop_cursor_blink()

        self._cursor_index = index
        self._blink_on = False
        self._blink_timer.start()
        logger.info(f"光标闪烁已启动：第 {index + 1} 节")

        # 返回当前标签的文字内容
        current_text: str = self.period_labels[index].text().strip()
        # 发射信号通知后端 / 快捷编辑窗口
        self.backend_signal.emit(ActionMessage.cursor_info(index, current_text))
        return current_text

    def stop_cursor_blink(self) -> None:
        """停止光标闪烁并恢复标签原始样式。"""
        if self._blink_timer.isActive():
            self._blink_timer.stop()
        # 恢复当前标签样式
        if 0 <= self._cursor_index < len(self.period_labels):
            label = self.period_labels[self._cursor_index]
            label.setStyleSheet(f"""
                color: {self._theme.font_color};
                background: transparent;
            """)
        self._blink_on = False
        logger.info("光标闪烁已停止")

    def _toggle_blink(self) -> None:
        """切换光标标签的闪烁状态（由 QTimer 触发）。"""
        if self._cursor_index < 0 or self._cursor_index >= len(self.period_labels):
            return

        label = self.period_labels[self._cursor_index]
        font_color = self._theme.font_color

        if self._blink_on:
            # 恢复常态
            label.setStyleSheet(f"""
                color: {font_color};
                background: transparent;
            """)
        else:
            # 高亮闪烁（淡蓝色光标杆）
            # 深色模式：提高蓝色亮度，使光标在暗背景上更醒目
            # 浅色模式：降低蓝色亮度，使光标在白背景上更柔和
            if self._theme.theme == 'darkcolor':
                bg_alpha: str = "0.30"
                border_alpha: str = "0.80"
            else:
                bg_alpha = "0.30"
                border_alpha = "0.65"

            label.setStyleSheet(f"""
                color: {font_color};
                background: rgba(33, 150, 243, {bg_alpha});
                border-left: 3px solid rgba(33, 150, 243, {border_alpha});
            """)

        self._blink_on = not self._blink_on

    def move_cursor(self, steps: int) -> str:
        """
        移动光标到相邻的课时标签（首尾循环）。
        ------------------------------------
        参数：
            steps（int）：移动步数，正数向下，负数向上

        返回值：
            str：移动后新标签的文字内容

        说明：
          光标到达顶部继续向上则跳到底部，到达底部继续向下则跳到顶部。
        """
        total: int = len(self.period_labels)
        if total == 0:
            return ""

        # 首尾循环：使用取模运算实现 wrap-around
        new_index: int = (self._cursor_index + steps) % total

        # 停止旧光标 → 在新位置启动
        self._cursor_index = new_index
        # 重置闪烁状态，确保新标签从正常态开始
        self._blink_on = False
        # 先恢复所有标签样式
        for label in self.period_labels:
            label.setStyleSheet(f"""
                color: {self._theme.font_color};
                background: transparent;
            """)
        # 立即显示一次高亮
        self._toggle_blink()

        logger.info(f"光标移动到：第 {new_index + 1} 节")
        current_text: str = self.period_labels[new_index].text().strip()
        self.backend_signal.emit(ActionMessage.cursor_info(new_index, current_text))
        return current_text

    def set_cursor_subject(self, subject_name: str) -> None:
        """
        将光标当前所在标签的内容设置为指定科目名称。
        ------------------------------------------
        参数：
            subject_name（str）：科目名称
        """
        if 0 <= self._cursor_index < len(self.period_labels):
            label = self.period_labels[self._cursor_index]
            old_text: str = label.text().strip()
            label.setText(subject_name)
            logger.info(f"标签更新：第 {self._cursor_index + 1} 节 "
                        f"'{old_text}' → '{subject_name}'")

    def get_cursor_index(self) -> int:
        """获取当前光标所在的标签索引。"""
        return self._cursor_index

    def get_cursor_subject(self) -> str:
        """获取当前光标所在标签的文字内容。"""
        if 0 <= self._cursor_index < len(self.period_labels):
            return self.period_labels[self._cursor_index].text().strip()
        return ""

    # ================================================================
    #  公开 API：切换显示星期
    # ================================================================
    def set_display_week(self, week_name: str) -> None:
        """
        将主窗口的课时标签切换为指定星期的课程表。
        -----------------------------------------
        参数：
            week_name（str）：英文星期名，如 'Monday'、'Tuesday' 等

        说明：
          遍历所有 period_labels，根据其 objectName（如 lesson_1）从
          课程表数据中查找对应课时的科目名称并更新显示文字。
          切换前会自动保存当前星期的标签修改到 curriculum_data 中。
          无效的星期名会被静默忽略。
        """
        valid_weeks = {'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                       'Friday', 'Saturday', 'Sunday'}
        if week_name not in valid_weeks:
            logger.warning(f"set_display_week: 无效的星期名 '{week_name}'")
            return

        # 切换前：将当前显示的标签内容同步回 curriculum_data
        self._sync_current_day_labels()

        self._current_display_day = week_name
        curriculum: Dict[str, str] = self._schedule_data.get_curriculum_for_day(week_name)

        for label in self.period_labels:
            key: str = label.objectName()  # type: ignore
            if key.startswith('lesson_'):
                label.setText(curriculum.get(key, ''))

        logger.info(f"主窗口课表已切换至：{week_name}")

    def _sync_current_day_labels(self) -> None:
        """
        将当前显示星期的所有课时标签文字同步回 curriculum_data。
        ----------------------------------------------------
        这样用户在快捷编辑中对标签的修改不会因为切换星期而丢失。
        """
        day: str = self._current_display_day
        day_data: Dict[str, str] = {}
        for label in self.period_labels:
            key: str = label.objectName()  # type: ignore
            if key.startswith('lesson_'):
                day_data[key] = label.text().strip()
        # 更新内存中的课程表数据
        self._schedule_data.curriculum_data[day] = day_data
        logger.debug(f"已同步 {day} 的 {len(day_data)} 个课时标签到 curriculum_data")

    def get_display_week(self) -> str:
        """获取主窗口当前显示的星期名称。"""
        return self._current_display_day

    # ================================================================
    #  公开 API：课时标签高亮（根据当前时间动态变色）
    # ================================================================

    def update_period_highlight(self, time_str: str) -> None:
        """
        根据当前时间高亮对应的科目标签。
        -----------------------------
        规则：
          - 当前时间在某节课的 [开始, 结束) 区间内 → 该课标签字体红色
          - 当前时间不在任何课内，但下一节课即将到来 → 下一节课标签橙色
          - 其他情况（如放学后）→ 所有标签保持默认颜色

        参数：
            time_str（str）：当前时间字符串，格式 HH:MM:SS
        """
        # 解析当前时间
        try:
            current_time = datetime.strptime(time_str, "%H:%M:%S").time()
        except (ValueError, TypeError):
            return

        timetable = self._schedule_data.timetable_data
        if not timetable:
            return

        # 第一步：将所有标签重置为默认字体颜色
        default_color = self._theme.font_color
        for label in self.period_labels:
            label.setStyleSheet(f"color: {default_color}; background: transparent;")

        # 第二步：提取所有课时的时间范围（保持 JSON 原始顺序）
        lessons: list = []  # [(lesson_key, start_time, end_time), ...]
        for key in timetable:
            if not key.startswith('lesson_'):
                continue
            times = timetable[key]
            if not (isinstance(times, list) and len(times) == 2):
                continue
            try:
                start = datetime.strptime(times[0], "%H:%M:%S").time()
                end = datetime.strptime(times[1], "%H:%M:%S").time()
                lessons.append((key, start, end))
            except (ValueError, TypeError):
                continue

        if not lessons:
            return

        # 第三步：判断当前时间是否在某节课期间 → 红色
        for key, start, end in lessons:
            if start <= current_time < end:
                self._set_label_color_by_lesson_key(key, 'red')
                return

        # 第四步：不在任何课内 → 查找下一节课 → 橙色
        for key, start, end in lessons:
            if current_time < start:
                self._set_label_color_by_lesson_key(key, 'orange')
                return

        # 第五步：在所有课之后 → 保持默认颜色（已在第一步重置）

    def _set_label_color_by_lesson_key(self, lesson_key: str, color: str) -> None:
        """
        根据课时键名（如 lesson_3）找到对应的 QLabel 并设置字体颜色。
        ------------------------------------------------------------
        参数：
            lesson_key（str）：课时键名，如 'lesson_1'
            color     （str）：目标颜色，如 'red' / 'orange' / '#FF0000'
        """
        for label in self.period_labels:
            if label.objectName() == lesson_key:
                label.setStyleSheet(f"color: {color}; background: transparent;")
                return
