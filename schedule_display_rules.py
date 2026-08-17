"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_display_rules.py（显示规则 UI 模块）      ║
║          （上下键调序的规则列表 + 规则编辑子窗口 + 日期滚轮）               ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件提供「显示规则」功能所需的 UI 控件：
  ✅ DisplayRuleListWidget — 规则列表（每条规则最左上下键调整优先级，蓝色选中）
  ✅ RuleEditDialog        — 规则编辑子窗口（每周/每月/时间段 + 删除）
  ✅ DateWheelPicker       — 年/月/日滚轮日期选择器（复用 WheelColumn）

数据由 schedule_config.DisplayRulesManager 持久化到 Config/Display_Rules.json。
"""

import logging
import os
from datetime import date
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QComboBox, QFrame, QWidget, QMessageBox,
)

from schedule_config import (
    ThemeManager, ScheduleDataManager, DisplayRulesManager,
    parse_display_rule,
)
from schedule_backend import WheelColumn

logger: logging.Logger = logging.getLogger(__name__)

# 时间表 / 课程表文件相对目录前缀
_TIMETABLE_DIR: str = 'Config/timetable'
_CURRICULUM_DIR: str = 'Config/curriculum'

# 星期显示名与规则文本后缀
_WEEKDAY_LABELS: tuple = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')
_WEEKDAY_SUFFIX: tuple = ('一', '二', '三', '四', '五', '六', '日')


def _days_in_month(year: int, month: int) -> int:
    """返回指定年月的天数。"""
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, month, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


# ==================== 单条规则行 ====================


class _RuleRow(QFrame):
    """单条显示规则行：最左上下键 + 可点击的规则按钮。"""

    move_up_clicked = Signal()
    move_down_clicked = Signal()
    clicked = Signal()

    def __init__(self, theme_manager: ThemeManager, priority: int,
                 rule_text: str, timetable_path: str,
                 curriculum_path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._priority: int = priority
        self._rule_text: str = rule_text
        self._timetable_path: str = timetable_path
        self._curriculum_path: str = curriculum_path
        self._selected: bool = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(6)

        self._up_btn: QPushButton = QPushButton('▲')
        self._down_btn: QPushButton = QPushButton('▼')
        for btn in (self._up_btn, self._down_btn):
            btn.setFixedSize(26, 26)
            btn.setFont(QFont('Arial', 10, QFont.Bold))  # type: ignore
            btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._up_btn.clicked.connect(self.move_up_clicked.emit)
        self._down_btn.clicked.connect(self.move_down_clicked.emit)

        self._text_btn: QPushButton = QPushButton(self._format_text())
        self._text_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._text_btn.clicked.connect(self.clicked.emit)

        layout.addWidget(self._up_btn)
        layout.addWidget(self._down_btn)
        layout.addWidget(self._text_btn, 1)

        self.refresh_theme()

    def _format_text(self) -> str:
        tt: str = os.path.basename(self._timetable_path)
        cv: str = os.path.basename(self._curriculum_path)
        return f"优先级{self._priority} · {self._rule_text} · {tt} · {cv}"

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.refresh_theme()

    def refresh_theme(self) -> None:
        theme = self._theme
        fc: str = theme.font_color
        if theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255, 255, 255, 0.04)'
            border: str = 'rgba(255, 255, 255, 0.08)'
            arrow_bg: str = 'rgba(255, 255, 255, 0.06)'
            arrow_hover: str = 'rgba(255, 255, 255, 0.12)'
            text_hover: str = 'rgba(255, 255, 255, 0.08)'
        else:
            card_bg = 'rgba(0, 0, 0, 0.03)'
            border = 'rgba(0, 0, 0, 0.08)'
            arrow_bg = 'rgba(0, 0, 0, 0.04)'
            arrow_hover = 'rgba(0, 0, 0, 0.10)'
            text_hover = 'rgba(0, 0, 0, 0.06)'

        if self._selected:
            self.setStyleSheet(
                'QFrame { background-color: rgba(33, 150, 243, 0.20);'
                ' border: 1px solid #2196F3; border-radius: 8px; }'
            )
        else:
            self.setStyleSheet(
                f'QFrame {{ background-color: {card_bg};'
                f' border: 1px solid {border}; border-radius: 8px; }}'
            )

        arrow_qss: str = (
            f'QPushButton {{ background-color: {arrow_bg}; color: {fc};'
            f' border: none; border-radius: 4px; }}'
            f'QPushButton:hover {{ background-color: {arrow_hover}; }}'
        )
        self._up_btn.setStyleSheet(arrow_qss)
        self._down_btn.setStyleSheet(arrow_qss)

        text_qss: str = (
            f'QPushButton {{ background-color: transparent; color: {fc};'
            f' border: none; padding: 8px 10px; text-align: left; }}'
            f'QPushButton:hover {{ background-color: {text_hover};'
            f' border-radius: 6px; }}'
        )
        self._text_btn.setStyleSheet(text_qss)


# ==================== 可点击标签 ====================


class _ClickableLabel(QLabel):
    """可点击的标签（用于切换编辑哪个日期）。"""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # type: ignore
        self.clicked.emit()
        super().mousePressEvent(event)


# ==================== 日期滚轮 ====================


class DateWheelPicker(QWidget):
    """
    # DateWheelPicker — 年/月/日滚轮日期选择器

    复用 WheelColumn，三列分别选择年份、月份、日期。
    日期按实际月份天数自动截断（如 2 月选 31 日 → 28/29 日）。
    """

    value_changed = Signal()

    def __init__(self, theme_manager: ThemeManager,
                 initial: Optional[date] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        initial = initial or date.today()
        bg, tc = self._wheel_colors()

        self._year_wheel: WheelColumn = WheelColumn(
            [f'{y}年' for y in range(2020, 2100)],
            initial.year - 2020, bg_color=bg, text_color=tc,
        )
        self._month_wheel: WheelColumn = WheelColumn(
            [f'{m}月' for m in range(1, 13)],
            initial.month - 1, bg_color=bg, text_color=tc,
        )
        self._day_wheel: WheelColumn = WheelColumn(
            [f'{d}日' for d in range(1, 32)],
            initial.day - 1, bg_color=bg, text_color=tc,
        )

        # 加宽列：年份需完整显示「2026年」，月份/日期需完整显示「12月」「12日」
        self._year_wheel.setFixedWidth(100)
        self._month_wheel.setFixedWidth(72)
        self._day_wheel.setFixedWidth(72)
        for wc in (self._year_wheel, self._month_wheel, self._day_wheel):
            wc.setMinimumHeight(0)
            wc.setMaximumHeight(170)

        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._year_wheel)
        layout.addWidget(self._month_wheel)
        layout.addWidget(self._day_wheel)

        self._year_wheel.selection_changed.connect(
            lambda _i: self.value_changed.emit()
        )
        self._month_wheel.selection_changed.connect(
            lambda _i: self.value_changed.emit()
        )
        self._day_wheel.selection_changed.connect(
            lambda _i: self.value_changed.emit()
        )

        self.setFixedHeight(170)

    def _wheel_colors(self) -> tuple:
        if self._theme.theme == 'darkcolor':
            return '#2d2d2d', '#E0E0E0'
        return '#FFFFFF', '#212121'

    def value(self) -> date:
        """返回当前选择的日期（日期按月份天数截断）。"""
        y: int = 2020 + self._year_wheel.current_index
        m: int = 1 + self._month_wheel.current_index
        d: int = min(1 + self._day_wheel.current_index, _days_in_month(y, m))
        return date(y, m, d)

    def set_value(self, d: date) -> None:
        """程序化设置日期。"""
        self._year_wheel.set_current_index(d.year - 2020)
        self._month_wheel.set_current_index(d.month - 1)
        self._day_wheel.set_current_index(d.day - 1)


# ==================== 规则列表 ====================


class DisplayRuleListWidget(QWidget):
    """
    # DisplayRuleListWidget — 显示规则列表

    每条规则一行，最左为上下键（调整优先级），点击规则行进入编辑。
    选中某条规则时该行以蓝色高亮显示。
    """

    rules_changed = Signal()

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._manager: DisplayRulesManager = DisplayRulesManager()
        self._selected_tag: Optional[str] = None
        self._rows: List[tuple] = []  # (tag, _RuleRow)

        self._list_layout: QVBoxLayout = QVBoxLayout(self)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self.refresh()
        logger.info("DisplayRuleListWidget 初始化完成")

    # ================================================================
    #  刷新
    # ================================================================
    def refresh(self) -> None:
        """按优先级升序重建规则行列表。"""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []

        rules = self._manager.load_rules()
        items = sorted(rules.items(), key=lambda kv: kv[1][0])

        if not items:
            # 空状态：斜体小字提示
            dim: str = (
                'rgba(255, 255, 255, 0.55)'
                if self._theme.theme == 'darkcolor'
                else 'rgba(0, 0, 0, 0.50)'
            )
            empty: QLabel = QLabel("这里没有任何规则")
            f: QFont = QFont("Microsoft YaHei", 10)
            f.setItalic(True)
            empty.setFont(f)
            empty.setStyleSheet(f"color: {dim}; background: transparent;")
            empty.setAlignment(Qt.AlignCenter)  # type: ignore
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        for tag, rule in items:
            if not isinstance(rule, list) or len(rule) < 4:
                continue
            try:
                priority: int = int(rule[0])
            except (ValueError, TypeError):
                continue
            row: _RuleRow = _RuleRow(
                self._theme, priority, rule[1], rule[2], rule[3]
            )
            row.move_up_clicked.connect(lambda t=tag: self._move(t, -1))
            row.move_down_clicked.connect(lambda t=tag: self._move(t, 1))
            row.clicked.connect(lambda t=tag: self._on_row_clicked(t))
            self._list_layout.addWidget(row)
            self._rows.append((tag, row))

        self._list_layout.addStretch()
        self._update_selection()

    # ================================================================
    #  事件
    # ================================================================
    def _order(self) -> List[str]:
        return [tag for tag, _ in self._rows]

    def _move(self, tag: str, direction: int) -> None:
        """上移（-1）或下移（+1）一条规则。"""
        order: List[str] = self._order()
        if tag not in order:
            return
        idx: int = order.index(tag)
        new_idx: int = idx + direction
        if new_idx < 0 or new_idx >= len(self._rows):
            return
        self._rows[idx], self._rows[new_idx] = (
            self._rows[new_idx], self._rows[idx]
        )
        self._manager.reorder(self._order())
        self.refresh()
        self.rules_changed.emit()

    def _on_row_clicked(self, tag: str) -> None:
        """点击规则行：选中并打开编辑子窗口。"""
        self._selected_tag = tag
        self._update_selection()
        self._open_edit(tag)

    def _open_edit(self, tag: str) -> None:
        rule = self._manager.load_rules().get(tag)
        if not rule:
            return
        dialog: RuleEditDialog = RuleEditDialog(
            self._theme, tag=tag, rule=rule, parent=self
        )
        if dialog.exec() == QDialog.Accepted:
            if dialog.deleted():
                self._manager.delete_rule(tag)
            else:
                result: dict = dialog.result()
                self._manager.update_rule(
                    tag, result['rule_text'],
                    result['timetable'], result['curriculum'],
                )
            self.refresh()
            self.rules_changed.emit()

    def _update_selection(self) -> None:
        for tag, row in self._rows:
            row.set_selected(tag == self._selected_tag)

    # ================================================================
    #  公开方法
    # ================================================================
    def add_rule_dialog(self) -> None:
        """弹出「新建规则」子窗口。"""
        dialog: RuleEditDialog = RuleEditDialog(self._theme, parent=self)
        if dialog.exec() == QDialog.Accepted:
            result: dict = dialog.result()
            self._manager.add_rule(
                result['rule_text'],
                result['timetable'],
                result['curriculum'],
            )
            self.refresh()
            self.rules_changed.emit()

    def refresh_theme(self) -> None:
        for _, row in self._rows:
            row.refresh_theme()


# ==================== 规则编辑子窗口 ====================


class RuleEditDialog(QDialog):
    """
    # RuleEditDialog — 显示规则编辑子窗口

    用于新增或编辑一条显示规则：
      - 规则类型：每周（选星期）/ 每月（选日期）/ 时间段（滚轮选起止日期）
      - 时间段起止日期相同时即视为「每年」
      - 时间表 / 课程表文件选择
      - 编辑模式下提供「删除规则」按钮
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 tag: Optional[str] = None,
                 rule: Optional[list] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._tag: Optional[str] = tag
        self._rule: Optional[list] = rule
        self._deleted: bool = False
        self._active_side: str = 'start'
        self._start_date: date = date.today()
        self._end_date: date = date.today()

        self.setWindowTitle('编辑规则' if rule else '新建规则')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(480)

        self._setup_ui()
        logger.info(f"RuleEditDialog 初始化完成（tag={tag}）")

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        self.setStyleSheet(self._build_qss())

        # ---- 卡片1：规则类型 ----
        type_card: QVBoxLayout = self._add_card("规则类型", layout)

        self._weekly_radio = QRadioButton("每周")
        self._monthly_radio = QRadioButton("每月")
        self._range_radio = QRadioButton("时间段")
        for r in (self._weekly_radio, self._monthly_radio, self._range_radio):
            r.setFont(QFont("Microsoft YaHei", 11))

        radio_row: QHBoxLayout = QHBoxLayout()
        radio_row.setSpacing(20)
        radio_row.addWidget(self._weekly_radio)
        radio_row.addWidget(self._monthly_radio)
        radio_row.addWidget(self._range_radio)
        radio_row.addStretch()
        type_card.addLayout(radio_row)

        # 每周：星期选择
        self._weekday_combo = QComboBox()
        self._weekday_combo.setFont(QFont("Microsoft YaHei", 11))
        self._weekday_combo.setMinimumHeight(34)
        for label in _WEEKDAY_LABELS:
            self._weekday_combo.addItem(label)
        type_card.addWidget(self._weekday_combo)

        # 每月：日期选择
        self._day_combo = QComboBox()
        self._day_combo.setFont(QFont("Microsoft YaHei", 11))
        self._day_combo.setMinimumHeight(34)
        for d in range(1, 32):
            self._day_combo.addItem(f'{d}日', d)
        type_card.addWidget(self._day_combo)

        # 时间段：标签 + 滚轮
        self._range_frame = QFrame()
        self._range_frame.setStyleSheet("background: transparent;")
        range_layout: QVBoxLayout = QVBoxLayout(self._range_frame)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(8)

        self._start_label = _ClickableLabel()
        self._end_label = _ClickableLabel()
        for lbl in (self._start_label, self._end_label):
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setCursor(Qt.PointingHandCursor)  # type: ignore
            lbl.setAlignment(Qt.AlignCenter)  # type: ignore
            lbl.setMinimumHeight(30)
        self._start_label.clicked.connect(lambda: self._set_active('start'))
        self._end_label.clicked.connect(lambda: self._set_active('end'))

        labels_row: QHBoxLayout = QHBoxLayout()
        labels_row.setSpacing(10)
        labels_row.addWidget(self._start_label, 1)
        labels_row.addWidget(self._end_label, 1)
        range_layout.addLayout(labels_row)

        self._date_wheel = DateWheelPicker(self._theme, self._start_date)
        self._date_wheel.value_changed.connect(self._on_wheel_changed)
        range_layout.addWidget(self._date_wheel)

        type_card.addWidget(self._range_frame)

        # 提示（斜体小字）
        type_card.addWidget(
            self._make_hint("提示：时间段起止日期相同时，即视为「每年」规则")
        )

        # ---- 卡片2：使用数据 ----
        data_card: QVBoxLayout = self._add_card("使用数据", layout)

        data_card.addWidget(self._make_field_label("时间表"))
        self._tt_combo = QComboBox()
        self._tt_combo.setFont(QFont("Microsoft YaHei", 11))
        self._tt_combo.setMinimumHeight(34)
        for fname in ScheduleDataManager.get_timetable_files():
            self._tt_combo.addItem(fname, f"{_TIMETABLE_DIR}/{fname}")
        data_card.addWidget(self._tt_combo)

        data_card.addWidget(self._make_field_label("课程表"))
        self._cv_combo = QComboBox()
        self._cv_combo.setFont(QFont("Microsoft YaHei", 11))
        self._cv_combo.setMinimumHeight(34)
        for fname in ScheduleDataManager.get_curriculum_files():
            self._cv_combo.addItem(fname, f"{_CURRICULUM_DIR}/{fname}")
        data_card.addWidget(self._cv_combo)

        # ---- 按钮行 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)

        # 删除按钮（仅编辑模式）
        self._delete_btn = QPushButton("删除规则")
        self._delete_btn.setFont(QFont("Microsoft YaHei", 11))
        self._delete_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._delete_btn.setMinimumHeight(34)
        self._delete_btn.setMinimumWidth(88)
        self._delete_btn.setProperty('class', 'danger')
        self._delete_btn.setVisible(self._tag is not None)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cancel_btn.setMinimumHeight(34)
        cancel_btn.setMinimumWidth(88)
        cancel_btn.setProperty('class', 'secondary')
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn: QPushButton = QPushButton("确定")
        confirm_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        confirm_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        confirm_btn.setMinimumHeight(34)
        confirm_btn.setMinimumWidth(88)
        confirm_btn.setProperty('class', 'primary')
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)

        # ---- 联动 + 预填 ----
        self._weekly_radio.toggled.connect(self._on_type_changed)
        self._monthly_radio.toggled.connect(self._on_type_changed)
        self._range_radio.toggled.connect(self._on_type_changed)

        self._weekly_radio.setChecked(True)
        self._refresh_date_labels()
        self._prefill()

    # ================================================================
    #  样式 / 卡片辅助
    # ================================================================
    def _build_qss(self) -> str:
        theme = self._theme
        fc: str = theme.font_color
        if theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255, 255, 255, 0.04)'
            card_border: str = 'rgba(255, 255, 255, 0.08)'
            field_bg: str = '#2d2d2d'
            field_border: str = 'rgba(255, 255, 255, 0.14)'
            hover_bg: str = 'rgba(255, 255, 255, 0.08)'
            pressed_bg: str = 'rgba(255, 255, 255, 0.12)'
            accent: str = '#43A047'
            accent_hover: str = '#4CAF50'
            btn_bg: str = 'rgba(255, 255, 255, 0.06)'
            btn_hover: str = 'rgba(255, 255, 255, 0.12)'
            dim: str = 'rgba(255, 255, 255, 0.55)'
        else:
            card_bg = 'rgba(0, 0, 0, 0.03)'
            card_border = 'rgba(0, 0, 0, 0.06)'
            field_bg = '#FFFFFF'
            field_border = 'rgba(0, 0, 0, 0.14)'
            hover_bg = 'rgba(0, 0, 0, 0.04)'
            pressed_bg = 'rgba(0, 0, 0, 0.08)'
            accent = '#4CAF50'
            accent_hover = '#43A047'
            btn_bg = 'rgba(0, 0, 0, 0.04)'
            btn_hover = 'rgba(0, 0, 0, 0.08)'
            dim = 'rgba(0, 0, 0, 0.50)'

        self._card_bg: str = card_bg
        self._card_border: str = card_border
        self._dim: str = dim

        return f"""
            QDialog {{
                background-color: {theme.root_back_color};
            }}
            QLabel {{
                color: {fc};
                background: transparent;
            }}
            QRadioButton {{
                color: {fc};
                background: transparent;
                spacing: 6px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {field_border};
                border-radius: 9px;
                background: {field_bg};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {accent};
                background: {accent};
            }}
            QComboBox {{
                background-color: {field_bg};
                color: {fc};
                border: 1px solid {field_border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QComboBox:hover, QComboBox:focus {{
                border-color: {accent};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {field_bg};
                color: {fc};
                border: 1px solid {field_border};
                selection-background-color: {hover_bg};
                selection-color: {fc};
                outline: 0;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {fc};
                border: 1px solid {field_border};
                border-radius: 6px;
                padding: 7px 18px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
            QPushButton[class="primary"] {{
                background-color: {accent};
                color: #FFFFFF;
                border: none;
            }}
            QPushButton[class="primary"]:hover {{
                background-color: {accent_hover};
            }}
            QPushButton[class="danger"] {{
                background-color: transparent;
                color: #E53935;
                border: 1px solid #E53935;
            }}
            QPushButton[class="danger"]:hover {{
                background-color: rgba(229, 57, 53, 0.12);
            }}
        """

    def _add_card(self, title: str, parent_layout: QVBoxLayout) -> QVBoxLayout:
        card: QFrame = QFrame()
        card.setStyleSheet(
            f'QFrame {{ background-color: {self._card_bg};'
            f' border: 1px solid {self._card_border}; border-radius: 8px; }}'
        )
        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(10)

        title_label: QLabel = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))  # type: ignore
        title_label.setStyleSheet(
            f'color: {self._theme.font_color}; background: transparent;'
        )
        card_layout.addWidget(title_label)

        sep: QFrame = QFrame()
        sep.setFrameShape(QFrame.HLine)  # type: ignore
        sep.setStyleSheet(
            f'border: none; border-top: 1px solid {self._card_border};'
            f' background: transparent;'
        )
        card_layout.addWidget(sep)

        parent_layout.addWidget(card)
        return card_layout

    def _make_field_label(self, text: str) -> QLabel:
        lbl: QLabel = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 11))
        return lbl

    def _make_hint(self, text: str) -> QLabel:
        """斜体小字提示标签。"""
        lbl: QLabel = QLabel(text)
        f: QFont = QFont("Microsoft YaHei", 9)
        f.setItalic(True)
        lbl.setFont(f)
        lbl.setStyleSheet(
            f'color: {self._dim}; background: transparent;'
        )
        lbl.setWordWrap(True)
        return lbl

    # ================================================================
    #  预填 / 联动
    # ================================================================
    def _prefill(self) -> None:
        if not self._rule or len(self._rule) < 4:
            return
        parsed = parse_display_rule(
            self._rule[1] if isinstance(self._rule[1], str) else ''
        )
        if parsed is not None:
            kind = parsed[0]
            if kind == 'weekly':
                self._weekly_radio.setChecked(True)
                self._weekday_combo.setCurrentIndex(parsed[1])
            elif kind == 'monthly':
                self._monthly_radio.setChecked(True)
                idx = self._day_combo.findData(parsed[1])
                if idx >= 0:
                    self._day_combo.setCurrentIndex(idx)
            elif kind == 'yearly':
                self._range_radio.setChecked(True)
                month, day = parsed[1], parsed[2]
                y = date.today().year
                d = date(y, month, min(day, _days_in_month(y, month)))
                self._start_date = d
                self._end_date = d
            elif kind == 'range':
                self._range_radio.setChecked(True)
                self._start_date = parsed[1]
                self._end_date = parsed[2]
        self._sync_wheel()
        self._refresh_date_labels()

        tt_idx: int = self._tt_combo.findData(self._rule[2])
        if tt_idx >= 0:
            self._tt_combo.setCurrentIndex(tt_idx)
        cv_idx: int = self._cv_combo.findData(self._rule[3])
        if cv_idx >= 0:
            self._cv_combo.setCurrentIndex(cv_idx)

    def _on_type_changed(self, _checked: bool) -> None:
        self._weekday_combo.setVisible(self._weekly_radio.isChecked())
        self._day_combo.setVisible(self._monthly_radio.isChecked())
        self._range_frame.setVisible(self._range_radio.isChecked())

    # ================================================================
    #  日期标签 / 滚轮联动
    # ================================================================
    def _set_active(self, side: str) -> None:
        self._active_side = side
        self._sync_wheel()
        self._refresh_date_labels()

    def _sync_wheel(self) -> None:
        d: date = (
            self._start_date if self._active_side == 'start' else self._end_date
        )
        self._date_wheel.set_value(d)

    def _on_wheel_changed(self) -> None:
        d: date = self._date_wheel.value()
        if self._active_side == 'start':
            self._start_date = d
        else:
            self._end_date = d
        self._refresh_date_labels()

    def _refresh_date_labels(self) -> None:
        self._start_label.setText(
            f"开始：{self._start_date.year}年"
            f"{self._start_date.month}月{self._start_date.day}日"
        )
        self._end_label.setText(
            f"结束：{self._end_date.year}年"
            f"{self._end_date.month}月{self._end_date.day}日"
        )

        active_blue = '#2196F3'
        normal_border = self._card_border
        fc = self._theme.font_color
        for lbl, side in ((self._start_label, 'start'), (self._end_label, 'end')):
            if side == self._active_side:
                lbl.setStyleSheet(
                    f'color: {active_blue}; background: transparent;'
                    f' border: 1px solid {active_blue}; border-radius: 6px;'
                )
            else:
                lbl.setStyleSheet(
                    f'color: {fc}; background: transparent;'
                    f' border: 1px solid {normal_border}; border-radius: 6px;'
                )

    # ================================================================
    #  结果
    # ================================================================
    def _build_rule_text(self) -> str:
        if self._weekly_radio.isChecked():
            return f"每周{_WEEKDAY_SUFFIX[self._weekday_combo.currentIndex()]}"
        if self._monthly_radio.isChecked():
            return f"每月{self._day_combo.currentData()}日"
        s: date = self._start_date
        e: date = self._end_date
        if s == e:
            return f"每年{s.month}月{s.day}日"
        return (
            f"{s.year}年{s.month}月{s.day}日到"
            f"{e.year}年{e.month}月{e.day}日"
        )

    def _on_confirm(self) -> None:
        """点击确定（时间段校验起止顺序）。"""
        if self._range_radio.isChecked() and self._start_date > self._end_date:
            QMessageBox.warning(
                self, "日期无效",
                "开始日期不能晚于结束日期，请重新选择。",
            )
            return
        logger.info(f"RuleEditDialog 确认：{self._build_rule_text()}")
        self.accept()

    def _on_delete(self) -> None:
        """删除当前规则（编辑模式下）。"""
        reply: QMessageBox.StandardButton = QMessageBox.question(
            self, "删除规则",
            "确定要删除这条显示规则吗？",
            QMessageBox.No | QMessageBox.Yes,  # type: ignore
            QMessageBox.No,  # type: ignore
        )
        if reply != QMessageBox.Yes:  # type: ignore
            return
        self._deleted = True
        self.accept()

    def result(self) -> dict:  # type: ignore
        return {
            'rule_text': self._build_rule_text(),
            'timetable': self._tt_combo.currentData(),
            'curriculum': self._cv_combo.currentData(),
        }

    def deleted(self) -> bool:
        return self._deleted
