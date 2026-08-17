"""
╔══════════════════════════════════════════════════════════════════════════╗
║      📅 电子课表系统 —— schedule_display_rules.py（显示规则 UI 模块）      ║
║              （可拖拽排序的规则列表 + 规则编辑子窗口）                       ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件提供「显示规则」功能所需的两个 UI 控件：
  ✅ DisplayRuleListWidget — 规则列表（QListWidget 内部拖拽排序 + 点击编辑）
  ✅ RuleEditDialog        — 规则编辑子窗口（每/时间段 + 时间表/课程表选择）

数据由 schedule_config.DisplayRulesManager 持久化到 Config/Display_Rules.json。
"""

import logging
import os
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QAbstractItemView,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QComboBox, QDateEdit, QFrame, QWidget,
    QMessageBox,
)

from schedule_config import (
    ThemeManager, ScheduleDataManager, DisplayRulesManager,
    parse_display_rule,
)

logger: logging.Logger = logging.getLogger(__name__)

# 时间表 / 课程表文件相对目录前缀
_TIMETABLE_DIR: str = 'Config/timetable'
_CURRICULUM_DIR: str = 'Config/curriculum'


class DisplayRuleListWidget(QListWidget):
    """
    # DisplayRuleListWidget — 显示规则列表

    基于 QListWidget，提供：
      - 内部拖拽排序（InternalMove），上下移动即改变优先级
      - 点击任意一条规则 → 打开编辑子窗口
      - refresh() 从 DisplayRulesManager 读取并按优先级排序重建
    ---
    """

    # 数据发生变化（增删改 / 拖拽重排）时发射
    rules_changed = Signal()

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化规则列表。
        --------------
        参数：
            theme_manager（ThemeManager）：主题管理器
            parent       （QWidget | None）：父控件
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._manager: DisplayRulesManager = DisplayRulesManager()

        # 拖拽重排（内部移动）
        self.setDragDropMode(QAbstractItemView.InternalMove)   # type: ignore
        self.setDefaultDropAction(Qt.MoveAction)               # type: ignore
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)  # type: ignore
        self.setCursor(Qt.PointingHandCursor)  # type: ignore

        # 拖拽结束 → 重新编号优先级并保存
        self.model().rowsMoved.connect(self._on_rows_moved)
        # 点击条目 → 打开编辑
        self.itemClicked.connect(self._on_item_clicked)

        self.refresh_theme()
        self.refresh()
        logger.info("DisplayRuleListWidget 初始化完成")

    # ================================================================
    #  数据刷新
    # ================================================================
    def refresh(self) -> None:
        """按优先级升序重建列表。"""
        self.clear()
        rules = self._manager.load_rules()
        items = sorted(rules.items(), key=lambda kv: kv[1][0])

        for tag, rule in items:
            if not isinstance(rule, list) or len(rule) < 4:
                continue
            try:
                priority: int = int(rule[0])
            except (ValueError, TypeError):
                continue
            text: str = self._format_text(
                priority, rule[1], rule[2], rule[3]
            )
            item: QListWidgetItem = QListWidgetItem(text)
            item.setData(Qt.UserRole, tag)  # type: ignore
            item.setToolTip(f"时间表：{rule[2]}\n课程表：{rule[3]}")
            item.setFlags(
                Qt.ItemIsSelectable          # type: ignore
                | Qt.ItemIsEnabled           # type: ignore
                | Qt.ItemIsDragEnabled       # type: ignore
                | Qt.ItemIsDropEnabled       # type: ignore
            )
            self.addItem(item)

    @staticmethod
    def _format_text(priority: int, rule_text: str,
                     timetable_path: str, curriculum_path: str) -> str:
        """生成条目显示文本：优先级 + 规则 + 时间表名 + 课程表名。"""
        tt_name: str = os.path.basename(timetable_path)
        cv_name: str = os.path.basename(curriculum_path)
        return f"优先级{priority} · {rule_text} · {tt_name} · {cv_name}"

    # ================================================================
    #  事件处理
    # ================================================================
    def _on_rows_moved(self, *_args) -> None:
        """拖拽重排后：按当前视觉顺序重新编号优先级并保存。"""
        tags: List[str] = [
            self.item(i).data(Qt.UserRole) for i in range(self.count())  # type: ignore
        ]
        self._manager.reorder(tags)
        # 刷新条目文本中的优先级编号
        rules = self._manager.load_rules()
        for i in range(self.count()):
            item: QListWidgetItem = self.item(i)
            tag: str = item.data(Qt.UserRole)  # type: ignore
            rule = rules.get(tag)
            if rule is not None and isinstance(rule, list) and len(rule) >= 4:
                item.setText(
                    self._format_text(int(rule[0]), rule[1], rule[2], rule[3])
                )
        self.rules_changed.emit()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """点击条目 → 打开编辑子窗口。"""
        tag: str = item.data(Qt.UserRole)  # type: ignore
        rule = self._manager.load_rules().get(tag)
        if not rule:
            return
        dialog: RuleEditDialog = RuleEditDialog(
            self._theme, tag=tag, rule=rule, parent=self
        )
        if dialog.exec() == QDialog.Accepted:
            result: dict = dialog.result()
            self._manager.update_rule(
                tag, result['rule_text'],
                result['timetable'], result['curriculum'],
            )
            self.refresh()
            self.rules_changed.emit()

    # ================================================================
    #  公开方法（由 SettingsWindow 调用）
    # ================================================================
    def add_rule_dialog(self) -> Optional[str]:
        """弹出「新建规则」子窗口，成功后新增并刷新。"""
        dialog: RuleEditDialog = RuleEditDialog(self._theme, parent=self)
        if dialog.exec() == QDialog.Accepted:
            result: dict = dialog.result()
            tag: str = self._manager.add_rule(
                result['rule_text'],
                result['timetable'],
                result['curriculum'],
            )
            self.refresh()
            self.rules_changed.emit()
            return tag or None
        return None

    def delete_selected(self) -> bool:
        """删除当前选中的规则。"""
        item: Optional[QListWidgetItem] = self.currentItem()
        if item is None:
            return False
        tag: str = item.data(Qt.UserRole)  # type: ignore
        if self._manager.delete_rule(tag):
            self.refresh()
            self.rules_changed.emit()
            return True
        return False

    # ================================================================
    #  主题刷新
    # ================================================================
    def refresh_theme(self) -> None:
        """主题变更后重套样式。"""
        theme = self._theme
        if theme.theme == 'darkcolor':
            bg = 'rgba(255, 255, 255, 0.04)'
            hover = 'rgba(255, 255, 255, 0.06)'
            sel = 'rgba(255, 255, 255, 0.10)'
        else:
            bg = 'rgba(0, 0, 0, 0.02)'
            hover = 'rgba(0, 0, 0, 0.04)'
            sel = 'rgba(0, 0, 0, 0.06)'
        border = theme.border_color
        fc = theme.font_color

        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
                color: {fc};
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 6px;
            }}
            QListWidget::item:hover {{
                background-color: {hover};
            }}
            QListWidget::item:selected {{
                background-color: {sel};
            }}
        """)


class RuleEditDialog(QDialog):
    """
    # RuleEditDialog — 显示规则编辑子窗口

    用于新增或编辑一条显示规则：
      - 规则类型：「每（每周/每月/每年）」或「时间段」
      - 时间表 / 课程表文件选择
    模态弹窗，确认后通过 result() 返回 dict。
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 tag: Optional[str] = None,
                 rule: Optional[list] = None,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化规则编辑对话框。
        ---------------------
        参数：
            theme_manager（ThemeManager）：主题管理器
            tag          （str | None）：编辑时传入规则标签，新建时 None
            rule         （list | None）：编辑时传入 [优先级, 文本, 时间表, 课程表]
            parent       （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._tag: Optional[str] = tag
        self._rule: Optional[list] = rule

        self.setWindowTitle('编辑规则' if rule else '新建规则')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(440)

        self._every_radio: Optional[QRadioButton] = None
        self._range_radio: Optional[QRadioButton] = None
        self._every_combo: Optional[QComboBox] = None
        self._range_frame: Optional[QFrame] = None
        self._start_edit: Optional[QDateEdit] = None
        self._end_edit: Optional[QDateEdit] = None
        self._tt_combo: Optional[QComboBox] = None
        self._cv_combo: Optional[QComboBox] = None

        self._setup_ui()
        logger.info(
            f"RuleEditDialog 初始化完成（tag={tag}）"
        )

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造对话框布局（卡片分组 + 主题化控件）。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # 主题化样式（含下拉框、日期框、按钮等）
        self.setStyleSheet(self._build_qss())

        # ---- 卡片1：规则类型 ----
        type_card: QVBoxLayout = self._add_card("规则类型", layout)

        self._every_radio = QRadioButton("每（每周 / 每月 / 每年）")
        self._every_radio.setFont(QFont("Microsoft YaHei", 11))
        self._range_radio = QRadioButton("时间段")
        self._range_radio.setFont(QFont("Microsoft YaHei", 11))

        radio_layout: QHBoxLayout = QHBoxLayout()
        radio_layout.setSpacing(20)
        radio_layout.addWidget(self._every_radio)
        radio_layout.addWidget(self._range_radio)
        radio_layout.addStretch()
        type_card.addLayout(radio_layout)

        # 「每」类：粒度下拉
        self._every_combo = QComboBox()
        self._every_combo.setFont(QFont("Microsoft YaHei", 11))
        self._every_combo.setMinimumHeight(34)
        for text in ('每周', '每月', '每年'):
            self._every_combo.addItem(text)
        type_card.addWidget(self._every_combo)

        # 时间段：起止日期
        self._range_frame = QFrame()
        self._range_frame.setStyleSheet("background: transparent;")
        range_layout: QHBoxLayout = QHBoxLayout(self._range_frame)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(10)

        self._start_edit = QDateEdit(QDate.currentDate())
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("yyyy年M月d日")
        self._start_edit.setFont(QFont("Microsoft YaHei", 11))
        self._start_edit.setMinimumHeight(34)

        self._end_edit = QDateEdit(QDate.currentDate())
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("yyyy年M月d日")
        self._end_edit.setFont(QFont("Microsoft YaHei", 11))
        self._end_edit.setMinimumHeight(34)

        range_label: QLabel = QLabel("到")
        range_label.setFont(QFont("Microsoft YaHei", 11))
        range_label.setStyleSheet(
            f"color: {self._theme.font_color}; background: transparent;"
        )

        range_layout.addWidget(self._start_edit, 1)
        range_layout.addWidget(range_label)
        range_layout.addWidget(self._end_edit, 1)
        type_card.addWidget(self._range_frame)

        # 单日提示
        hint: QLabel = QLabel("提示：起止日期相同时，仅在该日使用此规则")
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet(self._dim_label_style())
        type_card.addWidget(hint)

        # ---- 卡片2：使用数据 ----
        data_card: QVBoxLayout = self._add_card("使用数据", layout)

        tt_label: QLabel = QLabel("时间表")
        tt_label.setFont(QFont("Microsoft YaHei", 11))
        data_card.addWidget(tt_label)

        self._tt_combo = QComboBox()
        self._tt_combo.setFont(QFont("Microsoft YaHei", 11))
        self._tt_combo.setMinimumHeight(34)
        for fname in ScheduleDataManager.get_timetable_files():
            self._tt_combo.addItem(fname, f"{_TIMETABLE_DIR}/{fname}")
        data_card.addWidget(self._tt_combo)

        cv_label: QLabel = QLabel("课程表")
        cv_label.setFont(QFont("Microsoft YaHei", 11))
        data_card.addWidget(cv_label)

        self._cv_combo = QComboBox()
        self._cv_combo.setFont(QFont("Microsoft YaHei", 11))
        self._cv_combo.setMinimumHeight(34)
        for fname in ScheduleDataManager.get_curriculum_files():
            self._cv_combo.addItem(fname, f"{_CURRICULUM_DIR}/{fname}")
        data_card.addWidget(self._cv_combo)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)
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
        self.setFixedWidth(460)

        # ---- 联动 + 预填 ----
        self._every_radio.toggled.connect(self._on_type_changed)
        self._range_radio.toggled.connect(self._on_type_changed)

        self._every_radio.setChecked(True)
        self._prefill()

    # ================================================================
    #  样式 / 卡片辅助
    # ================================================================
    def _build_qss(self) -> str:
        """构建主题化样式表（下拉框、日期框、单选、按钮等）。"""
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
            QComboBox, QDateEdit {{
                background-color: {field_bg};
                color: {fc};
                border: 1px solid {field_border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QComboBox:hover, QDateEdit:hover,
            QComboBox:focus, QDateEdit:focus {{
                border-color: {accent};
            }}
            QComboBox::drop-down, QDateEdit::drop-down {{
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
            QCalendarWidget {{
                background-color: {field_bg};
                color: {fc};
            }}
            QCalendarWidget QToolButton {{
                color: {fc};
                background-color: transparent;
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
        """

    def _add_card(self, title: str, parent_layout: QVBoxLayout) -> QVBoxLayout:
        """创建带标题与分隔线的分组卡片，返回内容布局供添加子控件。"""
        card: QFrame = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {self._card_bg};
                border: 1px solid {self._card_border};
                border-radius: 8px;
            }}
        """)
        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(10)

        title_label: QLabel = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))  # type: ignore
        title_label.setStyleSheet(
            f"color: {self._theme.font_color}; background: transparent;"
        )
        card_layout.addWidget(title_label)

        sep: QFrame = QFrame()
        sep.setFrameShape(QFrame.HLine)  # type: ignore
        sep.setStyleSheet(
            f"border: none; border-top: 1px solid {self._card_border};"
            f" background: transparent;"
        )
        card_layout.addWidget(sep)

        parent_layout.addWidget(card)
        return card_layout

    def _dim_label_style(self) -> str:
        """次要提示标签的弱化文字样式。"""
        return f"color: {self._dim}; background: transparent;"

    # ================================================================
    #  预填 / 联动
    # ================================================================
    def _prefill(self) -> None:
        """编辑模式下预填已有规则的值。"""
        if not self._rule or len(self._rule) < 4:
            return
        parsed = parse_display_rule(
            self._rule[1] if isinstance(self._rule[1], str) else ''
        )
        if parsed is not None and parsed[0] == 'every':
            self._every_radio.setChecked(True)
            idx: int = self._every_combo.findText(parsed[1])
            if idx >= 0:
                self._every_combo.setCurrentIndex(idx)
        elif parsed is not None and parsed[0] == 'range':
            self._range_radio.setChecked(True)
            start, end = parsed[1], parsed[2]
            self._start_edit.setDate(
                QDate(start.year, start.month, start.day)
            )
            self._end_edit.setDate(QDate(end.year, end.month, end.day))

        # 时间表 / 课程表路径匹配
        tt_idx: int = self._tt_combo.findData(self._rule[2])
        if tt_idx >= 0:
            self._tt_combo.setCurrentIndex(tt_idx)
        cv_idx: int = self._cv_combo.findData(self._rule[3])
        if cv_idx >= 0:
            self._cv_combo.setCurrentIndex(cv_idx)

    def _on_type_changed(self, _checked: bool) -> None:
        """类型切换时更新可见区域。"""
        is_every: bool = self._every_radio.isChecked()
        self._every_combo.setVisible(is_every)
        self._range_frame.setVisible(not is_every)

    # ================================================================
    #  结果
    # ================================================================
    def _build_rule_text(self) -> str:
        """根据当前选择生成规则文本。"""
        if self._every_radio.isChecked():
            return self._every_combo.currentText()

        start: QDate = self._start_edit.date()
        end: QDate = self._end_edit.date()
        s: str = f"{start.year()}年{start.month()}月{start.day()}日"
        e: str = f"{end.year()}年{end.month()}月{end.day()}日"
        if s == e:
            return s
        return f"{s}到{e}"

    def _on_confirm(self) -> None:
        """点击确定（时间段规则校验起止日期顺序）。"""
        if self._range_radio.isChecked():
            start: QDate = self._start_edit.date()
            end: QDate = self._end_edit.date()
            if start > end:
                QMessageBox.warning(
                    self,
                    "日期无效",
                    "开始日期不能晚于结束日期，请重新选择。",
                )
                return
        logger.info(f"RuleEditDialog 确认：{self._build_rule_text()}")
        self.accept()

    def result(self) -> dict:  # type: ignore
        """返回编辑结果。"""
        return {
            'rule_text': self._build_rule_text(),
            'timetable': self._tt_combo.currentData(),
            'curriculum': self._cv_combo.currentData(),
        }
