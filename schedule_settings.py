"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║                   （管理中心：时间表切换 + 全面课表编辑 + 事件管理）       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
import re
from typing import Any, Dict, List

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QTimer, SignalInstance
from PySide6.QtGui import QColor, QFont, QCloseEvent

from schedule_theme import ThemeManager, ThemedWidget

logger: logging.Logger = logging.getLogger(__name__)


# ==================== Delegates ====================

class SubjectDelegate(QStyledItemDelegate):
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
        combo.setStyleSheet("font-size: 13px; padding: 4px 8px; border: none;")
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


class TimeDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setPlaceholderText("HH:MM")
        editor.setStyleSheet("font-size: 13px; padding: 4px 8px; border: none;")
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.DisplayRole) or "")

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        if re.match(r'^\d{1,2}:\d{2}$', text):
            model.setData(index, text, Qt.DisplayRole)  # type: ignore


# ==================== Fluent-style helpers ====================

def _fluent_table_style(theme) -> str:
    """Fluent UI 表格样式。"""
    # 根据主题决定悬停/选中颜色
    return f"""
        QTableWidget {{
            color: {theme.font_color};
            background: {theme.root_back_color};
            border: none;
            border-radius: 8px;
            font-size: 13px;
            outline: none;
        }}
        QTableWidget::item {{
            padding: 6px 10px;
            border-bottom: 1px solid rgba(128,128,128,0.08);
        }}
        QTableWidget::item:selected {{
            background: rgba(33,150,243,0.12);
            color: {theme.font_color};
            border-bottom: 1px solid rgba(33,150,243,0.15);
        }}
        QTableWidget::item:hover {{
            background: rgba(128,128,128,0.04);
        }}
        QHeaderView::section {{
            color: {theme.font_color};
            background: rgba(128,128,128,0.04);
            border: none;
            border-bottom: 1px solid rgba(128,128,128,0.12);
            padding: 10px 10px;
            font-weight: 600;
            font-size: 12px;
            letter-spacing: 0.3px;
        }}
        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(128,128,128,0.2);
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(128,128,128,0.35);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
    """


def _fluent_combo_style(theme) -> str:
    """Fluent UI 下拉框样式。"""
    return f"""
        QComboBox {{
            color: {theme.font_color};
            background: rgba(128,128,128,0.06);
            border: 1px solid rgba(128,128,128,0.12);
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 14px;
            outline: none;
        }}
        QComboBox:hover {{
            background: rgba(128,128,128,0.1);
            border-color: rgba(128,128,128,0.2);
        }}
        QComboBox:focus {{
            border-color: rgba(33,150,243,0.4);
        }}
        QComboBox::drop-down {{
            border: none; width: 28px;
        }}
        QComboBox QAbstractItemView {{
            color: {theme.font_color};
            background: {theme.root_back_color};
            border: 1px solid rgba(128,128,128,0.15);
            border-radius: 4px;
            padding: 4px;
            font-size: 13px;
            outline: none;
            selection-background-color: rgba(33,150,243,0.12);
        }}
    """


def _fluent_btn(theme) -> str:
    """Fluent UI 普通按钮。"""
    return f"""
        QPushButton {{
            color: {theme.font_color};
            background: rgba(128,128,128,0.06);
            border: 1px solid rgba(128,128,128,0.12);
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
            outline: none;
        }}
        QPushButton:hover {{
            background: rgba(128,128,128,0.12);
        }}
        QPushButton:pressed {{
            background: rgba(128,128,128,0.18);
        }}
    """


def _fluent_accent_btn(theme) -> str:
    """Fluent UI 强调按钮。"""
    return f"""
        QPushButton {{
            color: #FFFFFF;
            background: #0078D4;
            border: none;
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
            font-weight: 600;
            outline: none;
        }}
        QPushButton:hover {{
            background: #106EBE;
        }}
        QPushButton:pressed {{
            background: #005A9E;
        }}
    """


# ==================== Settings Window ====================

class SettingsWindow(ThemedWidget):
    """管理中心：Fluent UI 风格。"""

    COL_IDX = 0
    COL_START = 1
    COL_END = 2
    COL_MONDAY = 3

    DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    DAY_NAMES = {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
                 "Thursday": "周四", "Friday": "周五"}

    ROW_TYPE_ROLE = Qt.UserRole  # type: ignore
    ROW_DATA_ROLE = Qt.UserRole + 1  # type: ignore

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager) -> None:
        super().__init__(theme_manager, bg_color_attr='root_back_color')
        self._parent_signal = parent_signal
        self._updating = False

        self.setWindowFlags(
            Qt.Window | Qt.WindowStaysOnTopHint          # type: ignore
            | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint  # type: ignore
        )
        self.setWindowTitle("设置 — 课表管理中心")
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.96)

        ww = int(self._theme.screen_width * 0.72)
        wh = int(self._theme.screen_height * 0.68)
        self.setMinimumSize(680, 440)
        self.resize(ww, wh)
        self.move(
            (self._theme.screen_width - ww) // 2,
            (self._theme.screen_height - wh) // 2,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._time_combo = self._build_time_selector()
        layout.addWidget(self._time_combo)

        self._table = self._build_schedule_table()
        layout.addWidget(self._table, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = QPushButton("＋ 添加事件")
        add_btn.setStyleSheet(_fluent_accent_btn(self._theme))
        add_btn.setFixedHeight(34)
        add_btn.clicked.connect(self._on_add_event)
        btn_row.addWidget(add_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(_fluent_btn(self._theme))
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self._on_close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._load_table_data()

    # ================================================================
    #  Selector
    # ================================================================
    def _build_time_selector(self) -> QComboBox:
        combo = QComboBox()
        combo.setStyleSheet(_fluent_combo_style(self._theme))
        combo.setFixedHeight(38)
        combo.currentTextChanged.connect(self._on_time_schedule_changed)
        return combo

    # ================================================================
    #  Table
    # ================================================================
    def _build_schedule_table(self) -> QTableWidget:
        headers = ["节次", "开始", "结束",
                   "周一", "周二", "周三", "周四", "周五", ""]
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_IDX, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_IDX, 38)
        hdr.setSectionResizeMode(self.COL_START, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_START, 62)
        hdr.setSectionResizeMode(self.COL_END, QHeaderView.Fixed)
        table.setColumnWidth(self.COL_END, 62)
        for c in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            hdr.setSectionResizeMode(c, QHeaderView.Stretch)
        hdr.setSectionResizeMode(8, QHeaderView.Fixed)
        table.setColumnWidth(8, 34)

        table.verticalHeader().setDefaultSectionSize(40)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            _fluent_table_style(self._theme)
            + f"""
            QTableWidget {{
                alternate-background-color: rgba(128,128,128,0.02);
            }}
            """
        )
        table.setFrameShape(QTableWidget.NoFrame)

        td = TimeDelegate(table)
        table.setItemDelegateForColumn(self.COL_START, td)
        table.setItemDelegateForColumn(self.COL_END, td)

        self._subject_delegate = SubjectDelegate(table)
        self._update_subject_list()
        for c in range(self.COL_MONDAY, self.COL_MONDAY + 5):
            table.setItemDelegateForColumn(c, self._subject_delegate)

        table.cellChanged.connect(self._on_cell_changed)
        return table

    # ================================================================
    #  Data
    # ================================================================
    def _update_subject_list(self) -> None:
        subjects: List[str] = []
        for _cat, items in self._theme.subject_config.get("Subject_Types", {}).items():
            if isinstance(items, list):
                subjects.extend(items)
        self._subject_delegate.set_subjects(subjects)

    def _get_merged_rows(self) -> List[Dict[str, Any]]:
        times = self._theme.get_period_times()
        events = self._theme.get_active_events()
        rows: List[Dict[str, Any]] = []
        for i in range(self._theme.period_count):
            t = times[i] if i < len(times) else {}
            rows.append({
                "type": "period", "period_index": i,
                "sort_time": t.get("start", "99:99"),
                "start": t.get("start", ""), "end": t.get("end", ""),
            })
        for j, e in enumerate(events):
            rows.append({
                "type": "event", "event_index": j,
                "sort_time": e.get("time", "99:99"),
                "time": e.get("time", ""), "name": e.get("name", ""),
            })
        rows.sort(key=lambda r: (r["sort_time"], 0 if r["type"] == "event" else 1))
        return rows

    def _load_table_data(self) -> None:
        self._updating = True

        self._time_combo.blockSignals(True)
        self._time_combo.clear()
        self._time_combo.addItems(self._theme.get_time_schedule_names())
        idx = self._time_combo.findText(self._theme.get_active_time_schedule_name())
        if idx >= 0:
            self._time_combo.setCurrentIndex(idx)
        self._time_combo.blockSignals(False)

        merged = self._get_merged_rows()
        self._table.setRowCount(len(merged))
        weekly = self._theme.weekly_schedule

        for row, data in enumerate(merged):
            if data["type"] == "period":
                self._fill_period_row(row, data, weekly)
            else:
                self._fill_event_row(row, data)

        self._updating = False

    def _fill_period_row(self, row: int, data: Dict,
                         weekly: Dict[str, List[str]]) -> None:
        pi = data["period_index"]
        item = QTableWidgetItem(str(pi + 1))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
        item.setTextAlignment(Qt.AlignCenter)  # type: ignore
        item.setData(self.ROW_TYPE_ROLE, "period")
        item.setData(self.ROW_DATA_ROLE, pi)
        self._table.setItem(row, self.COL_IDX, item)

        self._set(row, self.COL_START, data["start"], True)
        self._set(row, self.COL_END, data["end"], True)

        for di, day in enumerate(self.DAY_ORDER):
            subs = weekly.get(day, [])
            self._set(row, self.COL_MONDAY + di,
                      subs[pi] if pi < len(subs) else "")
        self._set(row, 8, "")

    def _fill_event_row(self, row: int, data: Dict) -> None:
        ei = data["event_index"]
        bg = QColor(0, 120, 212, 22)  # Fluent blue, very subtle

        item = QTableWidgetItem("")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # type: ignore
        item.setData(self.ROW_TYPE_ROLE, "event")
        item.setData(self.ROW_DATA_ROLE, ei)
        item.setBackground(bg)
        self._table.setItem(row, self.COL_IDX, item)

        ti = QTableWidgetItem(data["time"])
        ti.setData(self.ROW_TYPE_ROLE, "event")
        ti.setData(self.ROW_DATA_ROLE, ei)
        ti.setTextAlignment(Qt.AlignCenter)  # type: ignore
        ti.setBackground(bg)
        self._table.setItem(row, self.COL_START, ti)

        # 合并：结束列 + 5 个科目列
        self._table.setSpan(row, self.COL_END, 1, 6)
        ni = QTableWidgetItem(f"  {data['name']}")
        ni.setData(self.ROW_TYPE_ROLE, "event")
        ni.setData(self.ROW_DATA_ROLE, ei)
        ni.setBackground(bg)
        ni.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._table.setItem(row, self.COL_END, ni)

        for c in range(self.COL_END + 1, 8):
            e = QTableWidgetItem("")
            e.setFlags(e.flags() & ~Qt.ItemIsEditable)  # type: ignore
            e.setBackground(bg)
            self._table.setItem(row, c, e)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet("""
            QPushButton {
                color: #C62828; background: transparent; border: none;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(198,40,40,0.1); border-radius: 4px;
            }
        """)
        del_btn.clicked.connect(
            lambda checked=False, e=ei: self._on_delete_event(e)
        )
        self._table.setCellWidget(row, 8, del_btn)

    def _set(self, row: int, col: int, text: str,
             center: bool = False) -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)
        if center:
            item.setTextAlignment(Qt.AlignCenter)  # type: ignore

    # ================================================================
    #  Events
    # ================================================================
    def _on_add_event(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("添加事件")
        dlg.setFixedSize(280, 130)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {self._theme.root_back_color};
                border-radius: 8px;
            }}
            QLabel {{ color: {self._theme.font_color}; font-size: 13px; }}
            QLineEdit {{
                color: {self._theme.font_color};
                background: rgba(128,128,128,0.06);
                border: 1px solid rgba(128,128,128,0.12);
                border-radius: 4px; padding: 6px 10px; font-size: 13px;
            }}
        """)
        layout = QFormLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 14)
        layout.setSpacing(10)
        time_edit = QLineEdit()
        time_edit.setPlaceholderText("HH:MM")
        layout.addRow("时间：", time_edit)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("如：眼保健操")
        layout.addRow("名称：", name_edit)
        br = QHBoxLayout()
        c1 = QPushButton("取消")
        c1.setStyleSheet(_fluent_btn(self._theme))
        c1.clicked.connect(dlg.reject)
        c2 = QPushButton("确定")
        c2.setStyleSheet(_fluent_accent_btn(self._theme))
        c2.clicked.connect(dlg.accept)
        br.addWidget(c1)
        br.addWidget(c2)
        layout.addRow(br)

        if dlg.exec() == QDialog.Accepted:
            tv = time_edit.text().strip()
            nv = name_edit.text().strip()
            if tv and nv and re.match(r'^\d{1,2}:\d{2}$', tv):
                sn = self._theme.get_active_time_schedule_name()
                self._parent_signal.emit(f"add_event:{sn}|{tv}|{nv}")
                QTimer.singleShot(50, self._load_table_data)
            else:
                QMessageBox.warning(self, "输入错误", "请输入有效时间（HH:MM）和名称。")

    def _on_delete_event(self, event_index: int) -> None:
        sn = self._theme.get_active_time_schedule_name()
        self._parent_signal.emit(f"remove_event:{sn}|{event_index}")
        QTimer.singleShot(50, self._load_table_data)

    # ================================================================
    #  Handlers
    # ================================================================
    def _on_time_schedule_changed(self, name: str) -> None:
        if self._updating or not name:
            return
        if self._theme.switch_time_schedule(name):
            self._parent_signal.emit(f"switch_time_schedule:{name}")
            QTimer.singleShot(50, self._load_table_data)
        else:
            QMessageBox.warning(
                self, "无法切换",
                f"时间表 '{name}' 节数与 period_count="
                f"{self._theme.period_count} 不匹配。",
            )
            self._time_combo.blockSignals(True)
            a = self._theme.get_active_time_schedule_name()
            i = self._time_combo.findText(a)
            if i >= 0:
                self._time_combo.setCurrentIndex(i)
            self._time_combo.blockSignals(False)

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        idx_item = self._table.item(row, self.COL_IDX)
        if idx_item is None:
            return
        rt = idx_item.data(self.ROW_TYPE_ROLE)
        rdi = idx_item.data(self.ROW_DATA_ROLE)
        item = self._table.item(row, col)
        if item is None:
            return
        val = item.text().strip()

        if rt == "event":
            self._on_event_cell_changed(rdi, col, val)
        elif rt == "period":
            self._on_period_cell_changed(rdi, col, val)

    def _on_period_cell_changed(self, pi: int, col: int, val: str) -> None:
        if col in (self.COL_START, self.COL_END):
            f = "start" if col == self.COL_START else "end"
            if re.match(r'^\d{1,2}:\d{2}$', val):
                self._parent_signal.emit(f"set_period_time:{pi}|{f}|{val}")
                QTimer.singleShot(50, self._load_table_data)
        elif self.COL_MONDAY <= col <= self.COL_MONDAY + 4:
            self._parent_signal.emit(
                f"set_subject_cell:{col - self.COL_MONDAY}|{pi}|{val}"
            )
            QTimer.singleShot(50, self._load_table_data)

    def _on_event_cell_changed(self, ei: int, col: int, val: str) -> None:
        events = self._theme.get_active_events()
        if ei < 0 or ei >= len(events):
            return
        cur = events[ei]
        if col == self.COL_START and re.match(r'^\d{1,2}:\d{2}$', val):
            cur["time"] = val
        elif col == self.COL_END:
            cur["name"] = val.lstrip()
        else:
            return
        sn = self._theme.get_active_time_schedule_name()
        self._parent_signal.emit(
            f"set_event:{sn}|{ei}|{cur['time']}|{cur['name']}"
        )
        QTimer.singleShot(50, self._load_table_data)

    def _on_close(self) -> None:
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def show(self) -> None:
        self._load_table_data()
        super().show()
