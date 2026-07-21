"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║                   （管理中心：时间表切换 + 全面课表编辑 + 事件管理）       ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责设置/管理中心窗口：
  ✅ 时间表下拉切换
  ✅ 混合表格：课时行 + 事件行按时序混排
  ✅ 事件添加/删除/编辑
  ✅ 单元格编辑自动保存
"""

import logging
import re
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, SignalInstance
from PySide6.QtGui import QColor, QFont, QCloseEvent

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
        combo.addItem("")
        combo.addItems(self._subjects)
        combo.setEditable(True)
        combo.setStyleSheet("font-size: 12px; padding: 2px 4px;")
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


# ==================== 设置窗口 ====================

class SettingsWindow(ThemedWidget):
    """管理中心窗口：时间表切换 + 课时/事件混合表格编辑。"""

    COL_IDX = 0
    COL_START = 1
    COL_END = 2
    COL_MONDAY = 3

    DAY_ORDER: List[str] = [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
    ]
    DAY_NAMES: Dict[str, str] = {
        "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
        "Thursday": "周四", "Friday": "周五",
    }

    # 行类型 Role
    ROW_TYPE_ROLE = Qt.UserRole  # type: ignore
    ROW_DATA_ROLE = Qt.UserRole + 1  # type: ignore

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager) -> None:
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal
        self._updating: bool = False

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
        self.setMinimumSize(650, 420)
        self.resize(win_w, win_h)
        pos_x: int = (self._theme.screen_width - win_w) // 2
        pos_y: int = (self._theme.screen_height - win_h) // 2
        self.move(pos_x, pos_y)

        # ---- 布局 ----
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 时间表下拉
        self._time_combo = self._build_time_selector()
        layout.addWidget(self._time_combo)

        # 混合表格
        self._table = self._build_schedule_table()
        layout.addWidget(self._table, stretch=1)

        # 添加事件按钮 + 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("＋ 添加事件")
        add_btn.setStyleSheet(self._accent_button_style())
        add_btn.setFixedHeight(32)
        add_btn.clicked.connect(self._on_add_event)
        btn_row.addWidget(add_btn)

        btn_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(self._button_style())
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self._on_close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        # 加载数据
        self._load_table_data()

        logger.info(f"SettingsWindow 创建完成：{win_w}×{win_h}")

    # ================================================================
    #  时间表下拉
    # ================================================================
    def _build_time_selector(self) -> QComboBox:
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
            QComboBox:hover {{ background: rgba(128, 128, 128, 0.2); }}
            QComboBox QAbstractItemView {{
                color: {self._theme.font_color};
                background: {self._theme.root_back_color};
                border: 1px solid {self._theme.border_color};
                font-size: 13px;
                selection-background-color: rgba(33, 150, 243, 0.3);
            }}
        """)
        combo.setFixedHeight(36)
        combo.currentTextChanged.connect(self._on_time_schedule_changed)
        return combo

    # ================================================================
    #  混合表格构建
    # ================================================================
    def _build_schedule_table(self) -> QTableWidget:
        """构建混合表格（初始行数会动态调整）。"""
        headers = [
            "节次", "开始", "结束",
            "周一", "周二", "周三", "周四", "周五", "",
        ]

        table = QTableWidget(0, len(headers))  # 0 行，动态设置
        table.setHorizontalHeaderLabels(headers)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_IDX, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_IDX, 36)
        hdr.setSectionResizeMode(self.COL_START, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_START, 56)
        hdr.setSectionResizeMode(self.COL_END, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_END, 56)
        for col in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            hdr.setSectionResizeMode(col, QHeaderView.Stretch)
        hdr.setSectionResizeMode(8, QHeaderView.Fixed)
        table.setColumnWidth(8, 32)

        table.verticalHeader().setDefaultSectionSize(36)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)

        table.setStyleSheet(f"""
            QTableWidget {{
                color: {self._theme.font_color};
                background: transparent;
                border: 1px solid {self._theme.border_color};
                border-radius: 6px;
                font-size: 13px;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {self._theme.border_color};
            }}
            QTableWidget::item:selected {{
                background: rgba(33, 150, 243, 0.2);
                color: {self._theme.font_color};
            }}
            QTableWidget {{
                alternate-background-color: rgba(128, 128, 128, 0.04);
            }}
            QHeaderView::section {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.08);
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 6px 8px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

        # 代理
        time_delegate = TimeDelegate(table)
        table.setItemDelegateForColumn(self.COL_START, time_delegate)
        table.setItemDelegateForColumn(self.COL_END, time_delegate)

        self._subject_delegate = SubjectDelegate(table)
        self._update_subject_list()
        for col in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            table.setItemDelegateForColumn(col, self._subject_delegate)

        table.cellChanged.connect(self._on_cell_changed)
        return table

    # ================================================================
    #  数据加载
    # ================================================================
    def _update_subject_list(self) -> None:
        subjects: List[str] = []
        subject_types = self._theme.subject_config.get("Subject_Types", {})
        for _category, items in subject_types.items():
            if isinstance(items, list):
                subjects.extend(items)
        self._subject_delegate.set_subjects(subjects)

    def _get_merged_rows(self) -> List[Dict[str, Any]]:
        """将课时和事件按时序合并为统一的列表。"""
        pc = self._theme.period_count
        times = self._theme.get_period_times()
        events = self._theme.get_active_events()

        rows: List[Dict[str, Any]] = []

        # 课时行
        for i in range(pc):
            t = times[i] if i < len(times) else {}
            rows.append({
                "type": "period",
                "period_index": i,
                "sort_time": t.get("start", "99:99"),
                "start": t.get("start", ""),
                "end": t.get("end", ""),
            })

        # 事件行
        for j, e in enumerate(events):
            rows.append({
                "type": "event",
                "event_index": j,
                "sort_time": e.get("time", "99:99"),
                "time": e.get("time", ""),
                "name": e.get("name", ""),
            })

        # 排序：同时间事件在上
        rows.sort(key=lambda r: (r["sort_time"], 0 if r["type"] == "event" else 1))
        return rows

    def _load_table_data(self) -> None:
        """从 ThemeManager 加载混合数据到表格。"""
        self._updating = True

        # 更新时间表下拉
        self._time_combo.blockSignals(True)
        self._time_combo.clear()
        self._time_combo.addItems(self._theme.get_time_schedule_names())
        active = self._theme.get_active_time_schedule_name()
        idx = self._time_combo.findText(active)
        if idx >= 0:
            self._time_combo.setCurrentIndex(idx)
        self._time_combo.blockSignals(False)

        # 合并行数据
        merged = self._get_merged_rows()
        self._table.setRowCount(len(merged))

        # 科目数据
        weekly = self._theme.weekly_schedule

        for row, data in enumerate(merged):
            if data["type"] == "period":
                self._fill_period_row(row, data, weekly)
            else:
                self._fill_event_row(row, data)

        self._updating = False

    def _fill_period_row(self, row: int, data: Dict,
                         weekly: Dict[str, List[str]]) -> None:
        """填充课时行。"""
        pi = data["period_index"]

        # 节次
        item = QTableWidgetItem(str(pi + 1))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
        item.setTextAlignment(Qt.AlignCenter)  # type: ignore
        item.setData(self.ROW_TYPE_ROLE, "period")
        item.setData(self.ROW_DATA_ROLE, pi)
        self._table.setItem(row, self.COL_IDX, item)

        # 开始/结束
        self._set_item(row, self.COL_START, data["start"])
        self._set_item(row, self.COL_END, data["end"])

        # 科目列
        for day_idx, day in enumerate(self.DAY_ORDER):
            subjects = weekly.get(day, [])
            subject = subjects[pi] if pi < len(subjects) else ""
            self._set_item(row, self.COL_MONDAY + day_idx, subject)

        # 最后一列空（无删除按钮）
        self._set_item(row, 8, "")

    def _fill_event_row(self, row: int, data: Dict) -> None:
        """填充事件行。"""
        ei = data["event_index"]
        event_name = data["name"]
        event_time = data["time"]

        # 节次 → 空，不可编辑
        item = QTableWidgetItem("")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
        item.setData(self.ROW_TYPE_ROLE, "event")
        item.setData(self.ROW_DATA_ROLE, ei)
        item.setBackground(QColor(33, 150, 243, 35))
        self._table.setItem(row, self.COL_IDX, item)

        # 开始 → 事件时间
        time_item = QTableWidgetItem(event_time)
        time_item.setData(self.ROW_TYPE_ROLE, "event")
        time_item.setData(self.ROW_DATA_ROLE, ei)
        time_item.setBackground(QColor(33, 150, 243, 35))
        time_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
        self._table.setItem(row, self.COL_START, time_item)

        # 结束 + 5 个科目列 → 合并为一个单元格显示事件名
        self._table.setSpan(row, self.COL_END, 1, 6)
        name_item = QTableWidgetItem(f"  {event_name}")
        name_item.setData(self.ROW_TYPE_ROLE, "event")
        name_item.setData(self.ROW_DATA_ROLE, ei)
        name_item.setBackground(QColor(33, 150, 243, 35))
        name_item.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._table.setItem(row, self.COL_END, name_item)

        # 第 5 个科目列之后的合并已通过 setSpan 处理
        # 清除 merge 范围内的其他 cell
        for c in range(self.COL_END + 1, 8):
            empty = QTableWidgetItem("")
            empty.setFlags(empty.flags() & ~Qt.ItemIsEditable)  # type: ignore
            empty.setBackground(QColor(33, 150, 243, 35))
            self._table.setItem(row, c, empty)

        # 删除按钮（第 8 列）
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 26)
        del_btn.setStyleSheet("""
            QPushButton {
                color: #E53935; background: transparent; border: none;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(229, 57, 53, 0.2); border-radius: 3px;
            }
        """)
        del_btn.clicked.connect(
            lambda checked=False, e=ei: self._on_delete_event(e)
        )
        self._table.setCellWidget(row, 8, del_btn)

    def _set_item(self, row: int, col: int, text: str) -> None:
        """设置普通单元格文本。"""
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)

    # ================================================================
    #  事件管理
    # ================================================================
    def _on_add_event(self) -> None:
        """弹出对话框添加新事件。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("添加事件")
        dlg.setFixedSize(260, 120)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {self._theme.root_back_color};
                color: {self._theme.font_color};
            }}
            QLabel {{ color: {self._theme.font_color}; font-size: 13px; }}
            QLineEdit {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.1);
                border: 1px solid {self._theme.border_color};
                border-radius: 3px; padding: 4px 8px; font-size: 13px;
            }}
        """)

        layout = QFormLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        time_edit = QLineEdit()
        time_edit.setPlaceholderText("HH:MM")
        layout.addRow("时间：", time_edit)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("如：眼保健操")
        layout.addRow("名称：", name_edit)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(self._button_style())
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet(self._accent_button_style())
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addRow(btn_row)

        if dlg.exec() == QDialog.Accepted:
            time_val = time_edit.text().strip()
            name_val = name_edit.text().strip()
            if time_val and name_val and re.match(r'^\d{1,2}:\d{2}$', time_val):
                schedule_name = self._theme.get_active_time_schedule_name()
                self._parent_signal.emit(
                    f"add_event:{schedule_name}:{time_val}:{name_val}"
                )
                logger.info(f"添加事件：'{name_val}' @ {time_val}")
                self._load_table_data()
            else:
                QMessageBox.warning(self, "输入错误", "请输入有效时间（HH:MM）和名称。")

    def _on_delete_event(self, event_index: int) -> None:
        """删除指定事件。"""
        schedule_name = self._theme.get_active_time_schedule_name()
        logger.info(f"删除事件：索引 {event_index}")
        self._parent_signal.emit(
            f"remove_event:{schedule_name}:{event_index}"
        )
        self._load_table_data()

    # ================================================================
    #  事件处理
    # ================================================================
    def _on_time_schedule_changed(self, name: str) -> None:
        if self._updating or not name:
            return
        logger.info(f"切换时间表：'{name}'")
        if self._theme.switch_time_schedule(name):
            self._parent_signal.emit(f"switch_time_schedule:{name}")
            self._load_table_data()
        else:
            QMessageBox.warning(
                self, "无法切换",
                f"时间表 '{name}' 节数与 period_count={self._theme.period_count} 不匹配。",
            )
            self._time_combo.blockSignals(True)
            active = self._theme.get_active_time_schedule_name()
            idx = self._time_combo.findText(active)
            if idx >= 0:
                self._time_combo.setCurrentIndex(idx)
            self._time_combo.blockSignals(False)

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return

        # 获取行类型
        idx_item = self._table.item(row, self.COL_IDX)
        if idx_item is None:
            return
        row_type = idx_item.data(self.ROW_TYPE_ROLE)
        row_data_idx = idx_item.data(self.ROW_DATA_ROLE)

        if row_type == "event":
            self._on_event_cell_changed(row, col, row_data_idx)
        elif row_type == "period":
            self._on_period_cell_changed(row, col, row_data_idx)

    def _on_period_cell_changed(self, row: int, col: int,
                                period_idx: int) -> None:
        item = self._table.item(row, col)
        if item is None:
            return
        value = item.text().strip()

        if col in (self.COL_START, self.COL_END):
            field = "start" if col == self.COL_START else "end"
            if re.match(r'^\d{1,2}:\d{2}$', value):
                self._parent_signal.emit(
                    f"set_period_time:{period_idx}:{field}:{value}"
                )
                logger.info(f"时间：第{period_idx + 1}节 {field} = {value}")
                # 刷新以更新事件自动同步
        elif col >= self.COL_MONDAY and col <= self.COL_MONDAY + 4:
            day_idx = col - self.COL_MONDAY
            self._parent_signal.emit(
                f"set_subject_cell:{day_idx}:{period_idx}:{value}"
            )
            logger.info(
                f"科目：{self.DAY_NAMES[self.DAY_ORDER[day_idx]]} "
                f"第{period_idx + 1}节 → '{value}'"
            )

    def _on_event_cell_changed(self, row: int, col: int,
                               event_idx: int) -> None:
        item = self._table.item(row, col)
        if item is None:
            return
        value = item.text().strip()

        # 获取当前事件的完整数据
        events = self._theme.get_active_events()
        if event_idx < 0 or event_idx >= len(events):
            return
        current = events[event_idx]

        if col == self.COL_START:
            # 时间被编辑
            if re.match(r'^\d{1,2}:\d{2}$', value):
                current["time"] = value
            else:
                return
        elif col == self.COL_END:
            # 名称被编辑（合并单元格中）
            current["name"] = value.lstrip()

        schedule_name = self._theme.get_active_time_schedule_name()
        self._parent_signal.emit(
            f"set_event:{schedule_name}:{event_idx}:"
            f"{current['time']}:{current['name']}"
        )
        logger.info(f"事件更新：'{current['name']}' @ {current['time']}")
        # 刷新以重新排序
        self._load_table_data()

    def _on_close(self) -> None:
        logger.info("用户关闭设置窗口")
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("[SettingsWindow] 关闭事件 → 隐藏窗口")
        event.ignore()
        self.hide()

    def show(self) -> None:
        self._load_table_data()
        super().show()

    def _button_style(self) -> str:
        return f"""
            QPushButton {{
                color: {self._theme.font_color};
                background: rgba(128, 128, 128, 0.12);
                border: 1px solid {self._theme.border_color};
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background: rgba(128, 128, 128, 0.25); }}
            QPushButton:pressed {{ background: rgba(128, 128, 128, 0.35); }}
        """

    def _accent_button_style(self) -> str:
        return f"""
            QPushButton {{
                color: #FFFFFF;
                background: rgba(33, 150, 243, 0.75);
                border: 1px solid rgba(33, 150, 243, 0.5);
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: rgba(33, 150, 243, 0.9); }}
            QPushButton:pressed {{ background: rgba(33, 150, 243, 1.0); }}
        """
