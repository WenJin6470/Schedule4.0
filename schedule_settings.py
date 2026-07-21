"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║                   （管理中心：时间表切换 + 全面课表编辑）                  ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责设置/管理中心窗口：
  ✅ 时间表下拉切换
  ✅ QTableWidget 全面课表编辑（节次 + 开始/结束时间 + 周一~周五）
  ✅ 单元格编辑自动保存
"""

import logging
import re
from typing import Dict, List

from PySide6.QtWidgets import (
    QComboBox, QHeaderView, QLabel, QMessageBox, QPushButton,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QFont, QCloseEvent

from schedule_theme import ThemeManager, ThemedWidget

logger: logging.Logger = logging.getLogger(__name__)


# ==================== 科目单元格代理 ====================

class SubjectDelegate(QStyledItemDelegate):
    """科目列编辑器：双击弹出 QComboBox 选择科目。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._subjects: List[str] = []

    def set_subjects(self, subjects: List[str]) -> None:
        self._subjects = subjects

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItem("")  # 空选项
        combo.addItems(self._subjects)
        combo.setEditable(True)
        combo.setStyleSheet("""
            QComboBox {
                font-size: 12px;
                padding: 2px 4px;
            }
            QComboBox QAbstractItemView {
                font-size: 12px;
            }
        """)
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.DisplayRole) or ""
        idx = editor.findText(current)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setEditText(current)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.DisplayRole)  # type: ignore


# ==================== 时间校验代理 ====================

class TimeDelegate(QStyledItemDelegate):
    """时间列编辑器：双击输入 HH:MM 格式。"""

    def createEditor(self, parent, option, index):
        from PySide6.QtWidgets import QLineEdit
        editor = QLineEdit(parent)
        editor.setPlaceholderText("HH:MM")
        editor.setStyleSheet("font-size: 12px; padding: 2px 4px;")
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.DisplayRole) or "")

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        if re.match(r'^\d{1,2}:\d{2}$', text):
            model.setData(index, text, Qt.DisplayRole)  # type: ignore
        else:
            # 无效输入 → 恢复原值
            pass


# ==================== 设置窗口 ====================

class SettingsWindow(ThemedWidget):
    """
    # SettingsWindow — 管理中心窗口

    功能：
      - 时间表下拉切换（带冲突验证）
      - 全面课表编辑表格（节次 | 开始 | 结束 | 周一~周五）
    """

    # 列索引常量
    COL_IDX = 0
    COL_START = 1
    COL_END = 2
    COL_MONDAY = 3  # 周一，后续 +1 到周五

    DAY_ORDER: List[str] = [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
    ]
    DAY_NAMES: Dict[str, str] = {
        "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
        "Thursday": "周四", "Friday": "周五",
    }

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager) -> None:
        """
        初始化设置窗口。
        ---------------
        参数：
            parent_signal（SignalInstance）：主窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal
        self._updating: bool = False  # 防止循环更新

        logger.info("SettingsWindow 初始化开始")

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowStaysOnTopHint         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
            | Qt.WindowMinimizeButtonHint     # type: ignore
        )
        self.setWindowTitle("设置 — 课表管理中心")
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.95)

        win_w: int = int(self._theme.screen_width * 0.75)
        win_h: int = int(self._theme.screen_height * 0.7)
        self.setMinimumSize(620, 400)
        self.resize(win_w, win_h)
        pos_x: int = (self._theme.screen_width - win_w) // 2
        pos_y: int = (self._theme.screen_height - win_h) // 2
        self.move(pos_x, pos_y)

        # ---- 布局 ----
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ---- 标题 + 时间表下拉 ----
        self._time_combo = self._build_time_schedule_selector()
        layout.addWidget(self._time_combo)

        # ---- 课表表格 ----
        self._table = self._build_schedule_table()
        layout.addWidget(self._table, stretch=1)

        # ---- 关闭按钮 ----
        close_btn: QPushButton = QPushButton("关闭")
        close_btn.setStyleSheet(self._button_style())
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(close_btn)

        # ---- 加载数据 ----
        self._load_table_data()

        logger.info(f"SettingsWindow 创建完成：{win_w}×{win_h}")

    # ================================================================
    #  时间表下拉选择器
    # ================================================================
    def _build_time_schedule_selector(self) -> QComboBox:
        """构建时间表下拉选择器。"""
        combo = QComboBox()
        combo.setStyleSheet(f"""
            QComboBox {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.1);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 14px;
            }}
            QComboBox:hover {{
                background: rgba(128, 128, 128, 0.2);
            }}
            QComboBox QAbstractItemView {{
                color: {self._theme.font_color};
                background: {self._theme.root_back_color};
                border: 1px solid {self._theme.border_color};
                font-size: 13px;
                selection-background-color: rgba(33, 150, 243, 0.3);
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
        """)
        combo.setFixedHeight(36)
        combo.currentTextChanged.connect(self._on_time_schedule_changed)
        return combo

    # ================================================================
    #  课表编辑表格
    # ================================================================
    def _build_schedule_table(self) -> QTableWidget:
        """构建全面课表编辑表格（8 列）。"""
        pc = self._theme.period_count
        headers = [
            "节次", "开始", "结束",
            "周一", "周二", "周三", "周四", "周五",
        ]

        table = QTableWidget(pc, len(headers))
        table.setHorizontalHeaderLabels(headers)

        # ---- 列宽 ----
        header = table.horizontalHeader()
        header.setSectionResizeMode(self.COL_IDX, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_IDX, 40)
        header.setSectionResizeMode(self.COL_START, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_START, 60)
        header.setSectionResizeMode(self.COL_END, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_END, 60)
        for col in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            header.setSectionResizeMode(col, QHeaderView.Stretch)

        # ---- 行高 ----
        table.verticalHeader().setDefaultSectionSize(34)
        table.verticalHeader().setVisible(False)

        # ---- 样式 ----
        table.setStyleSheet(f"""
            QTableWidget {{
                color: {self._theme.font_color};
                background: transparent;
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                gridline-color: {self._theme.border_color};
                font-size: 13px;
            }}
            QTableWidget::item {{
                padding: 2px 6px;
            }}
            QTableWidget::item:selected {{
                background: rgba(33, 150, 243, 0.25);
                color: {self._theme.font_color};
            }}
            QHeaderView::section {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.1);
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 4px 6px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

        # ---- 节次列只读 ----
        for row in range(pc):
            item = QTableWidgetItem(str(row + 1))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
            item.setTextAlignment(Qt.AlignCenter)  # type: ignore
            table.setItem(row, self.COL_IDX, item)

        # ---- 时间列代理 ----
        time_delegate = TimeDelegate(table)
        table.setItemDelegateForColumn(self.COL_START, time_delegate)
        table.setItemDelegateForColumn(self.COL_END, time_delegate)

        # ---- 科目列代理 ----
        self._subject_delegate = SubjectDelegate(table)
        self._update_subject_list()
        for col in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            table.setItemDelegateForColumn(col, self._subject_delegate)

        # ---- 信号：单元格修改 → 保存 ----
        table.cellChanged.connect(self._on_cell_changed)

        return table

    # ================================================================
    #  数据加载 + 刷新
    # ================================================================
    def _update_subject_list(self) -> None:
        """从 subject_config 收集所有可用科目。"""
        subjects: List[str] = []
        subject_types = self._theme.subject_config.get("Subject_Types", {})
        for _category, items in subject_types.items():
            if isinstance(items, list):
                subjects.extend(items)
        self._subject_delegate.set_subjects(subjects)

    def _load_table_data(self) -> None:
        """从 ThemeManager 加载数据到表格。"""
        self._updating = True

        # ---- 更新时间表下拉 ----
        self._time_combo.blockSignals(True)
        self._time_combo.clear()
        self._time_combo.addItems(self._theme.get_time_schedule_names())
        active = self._theme.get_active_time_schedule_name()
        idx = self._time_combo.findText(active)
        if idx >= 0:
            self._time_combo.setCurrentIndex(idx)
        self._time_combo.blockSignals(False)

        # ---- 更新表格 ----
        pc = self._theme.period_count
        self._table.setRowCount(pc)

        # 更新节次列
        for row in range(pc):
            item = self._table.item(row, self.COL_IDX)
            if item:
                item.setText(str(row + 1))

        # 时间列
        times = self._theme.get_period_times()
        for row in range(pc):
            if row < len(times):
                t = times[row]
                self._set_cell(row, self.COL_START, t.get('start', ''))
                self._set_cell(row, self.COL_END, t.get('end', ''))
            else:
                self._set_cell(row, self.COL_START, '')
                self._set_cell(row, self.COL_END, '')

        # 科目列
        for day_idx, day in enumerate(self.DAY_ORDER):
            subjects = self._theme.weekly_schedule.get(day, [])
            for row in range(pc):
                subject = subjects[row] if row < len(subjects) else ""
                self._set_cell(row, self.COL_MONDAY + day_idx, subject)

        self._updating = False

    def _set_cell(self, row: int, col: int, text: str) -> None:
        """设置单元格文本，保留已有 item 或创建新 item。"""
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)

    # ================================================================
    #  事件处理
    # ================================================================
    def _on_time_schedule_changed(self, name: str) -> None:
        """时间表下拉切换（含冲突验证）。"""
        if self._updating or not name:
            return

        logger.info(f"用户选择时间表：'{name}'")
        if self._theme.switch_time_schedule(name):
            self._parent_signal.emit(f"switch_time_schedule:{name}")
            self._load_table_data()
        else:
            QMessageBox.warning(
                self,
                "无法切换",
                f"时间表 '{name}' 的节数与当前配置 (period_count={self._theme.period_count}) 不匹配，无法切换。",
            )
            # 恢复下拉框
            self._time_combo.blockSignals(True)
            active = self._theme.get_active_time_schedule_name()
            idx = self._time_combo.findText(active)
            if idx >= 0:
                self._time_combo.setCurrentIndex(idx)
            self._time_combo.blockSignals(False)

    def _on_cell_changed(self, row: int, col: int) -> None:
        """表格单元格被编辑后保存。"""
        if self._updating:
            return

        item = self._table.item(row, col)
        if item is None:
            return
        value = item.text().strip()

        if col == self.COL_START or col == self.COL_END:
            # 时间列编辑
            field = "start" if col == self.COL_START else "end"
            if re.match(r'^\d{1,2}:\d{2}$', value):
                self._parent_signal.emit(
                    f"set_period_time:{row}:{field}:{value}"
                )
                logger.info(f"时间编辑：第{row + 1}节 {field} = {value}")
        elif col >= self.COL_MONDAY:
            # 科目列编辑
            day_idx = col - self.COL_MONDAY
            if 0 <= day_idx < 5:
                self._parent_signal.emit(
                    f"set_subject_cell:{day_idx}:{row}:{value}"
                )
                logger.info(
                    f"科目编辑：{self.DAY_NAMES[self.DAY_ORDER[day_idx]]} "
                    f"第{row + 1}节 → '{value}'"
                )

    def _on_close(self) -> None:
        """关闭设置窗口。"""
        logger.info("用户关闭设置窗口")
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        """重写关闭事件：仅隐藏窗口。"""
        logger.info("[SettingsWindow] 关闭事件 → 隐藏窗口")
        event.ignore()
        self.hide()

    # ================================================================
    #  公开方法：显示时刷新数据
    # ================================================================
    def show(self) -> None:
        """显示窗口时刷新数据。"""
        self._load_table_data()
        super().show()

    def _button_style(self) -> str:
        """通用按钮样式。"""
        return f"""
            QPushButton {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.12);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.25);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.35);
            }}
        """
