"""
╔══════════════════════════════════════════════════════════════════════════╗
║         📅 电子课表系统 —— schedule_frontend.py（主窗口模块）              ║
║                    （课表显示主窗口 · 四大按钮入口）                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
import os
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QIcon

from schedule_theme import ThemeManager, ThemedWidget
from schedule_quick_edit import SubjectSelectWindow
from schedule_settings import SettingsWindow

logger: logging.Logger = logging.getLogger(__name__)

EVENT_ROW_H = 16   # 事件行高度
BTN_BAR_H = 40     # 按钮栏高度
SEP_H = 1          # 分隔线


class ScheduleMainWindow(ThemedWidget):
    """课表主窗口：统一行列表渲染（课时 + 事件）。"""

    backend_signal = Signal(str)

    def __init__(self, theme_manager: ThemeManager) -> None:
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        logger.info("=" * 50)
        logger.info("ScheduleMainWindow 初始化开始")

        self._subject_window: Optional[SubjectSelectWindow] = None
        self._settings_window: Optional[SettingsWindow] = None

        # 光标闪烁
        self._cursor_index: int = 0
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_on: bool = False

        # 当前星期
        self._current_day_index: int = self._theme.current_day_index

        # ---- 窗口尺寸 ----
        sw, sh = self._theme.screen_width, self._theme.screen_height
        self._win_width: int = int(sw * (150 / 1920))
        self._win_height: int = int(sh / 13 * 11)
        self._pos_x: int = int(sw * (1765 / 1920))
        self._pos_y: int = int(sh / 12)

        logger.info(
            f"窗口尺寸：{self._win_width}×{self._win_height}，"
            f"位置({self._pos_x}, {self._pos_y})"
        )

        # ---- 内容行（统一管理）----
        self._period_labels: List[QLabel] = []   # 按 period_index 存储
        self._period_bars: List[QWidget] = []    # 按 period_index 存储
        self._all_content_widgets: List[QWidget] = []  # 所有内容行

        self._setup_ui()
        self._rebuild_content()

        logger.info("ScheduleMainWindow 初始化完成")
        logger.info("=" * 50)

    # ================================================================
    #  窗口框架
    # ================================================================
    def _setup_ui(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(self._theme.window_opacity)
        self.setFixedSize(self._win_width, self._win_height)
        self.move(self._pos_x, self._pos_y)

        # ---- 底部按钮栏 ----
        images_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'images'
        )
        icon_suffix = self._theme.get_icon_suffix()

        button_configs = [
            ('_fs_btn', 'FullScreenTime', self._on_fullscreen_time_clicked),
            ('_ed_btn', 'EDIT_S',        self._on_quick_edit_clicked),
            ('_st_btn', 'setting',       self._on_settings_clicked),
            ('_cl_btn', 'EXIT',          self._on_close_clicked),
        ]
        bs = 22
        bc = len(button_configs)
        sp = (self._win_width - bc * (bs + 4)) // (bc + 1)
        by = self._win_height - BTN_BAR_H + (BTN_BAR_H - bs) // 2

        for i, (attr, base, handler) in enumerate(button_configs):
            path = os.path.join(images_dir, f"{base}{icon_suffix}.svg")
            btn = QPushButton(self)
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(bs, bs))
            btn.setStyleSheet("""
                QPushButton { background: transparent; border: none; padding: 2px; }
                QPushButton:hover {
                    background: rgba(128,128,128,0.2); border-radius: 5px;
                }
            """)
            btn.setFixedSize(bs + 4, bs + 4)
            btn.move(sp + i * (bs + 4 + sp), by)
            btn.clicked.connect(handler)
            setattr(self, attr, btn)

        logger.info(f"按钮栏创建完成：{bc} 个按钮")

    # ================================================================
    #  统一行列表：构建 / 销毁 / 刷新
    # ================================================================
    def _get_merged_rows(self) -> List[Dict[str, Any]]:
        """将课时和事件按时序合并为统一列表。"""
        pc = self._theme.period_count
        times = self._theme.get_period_times()
        events = self._theme.get_active_events()

        rows: List[Dict[str, Any]] = []
        for i in range(pc):
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

    def _rebuild_content(self) -> None:
        """销毁并重建所有内容行（课时 + 事件）。"""
        # 清理旧控件
        for w in self._all_content_widgets:
            w.deleteLater()
        self._all_content_widgets.clear()
        self._period_labels.clear()
        self._period_bars.clear()

        # 扩展 period_labels / period_bars 到 period_count 大小
        pc = self._theme.period_count
        self._period_labels = [None] * pc  # type: ignore
        self._period_bars = [None] * pc    # type: ignore

        rows = self._get_merged_rows()
        subjects = self._theme.get_current_day_subjects()

        # 计算高度分配
        period_count = sum(1 for r in rows if r["type"] == "period")
        event_count = sum(1 for r in rows if r["type"] == "event")
        available = self._win_height - BTN_BAR_H
        period_h = (available - event_count * EVENT_ROW_H) // max(period_count, 1)
        if period_h < 32:
            period_h = 32  # 最小高度

        current_y = 0
        for row_data in rows:
            if row_data["type"] == "period":
                current_y = self._build_period_row(row_data, subjects,
                                                   period_h, current_y)
            else:
                current_y = self._build_event_row(row_data, current_y)

        logger.info(
            f"内容重建：{period_count} 课时行 + {event_count} 事件行，"
            f"课时高度 {period_h}px"
        )

    def _build_period_row(self, data: Dict, subjects: List[str],
                          h: int, y: int) -> int:
        """创建一个课时行，返回下一行的 y。"""
        pi = data["period_index"]
        subj = subjects[pi] if pi < len(subjects) else ""

        # 分隔线（非首行）
        if y > 0:
            sep = QLabel(self)
            sep.setStyleSheet(f"background: {self._theme.border_color};")
            sep.setGeometry(4, y, self._win_width - 8, SEP_H)
            self._all_content_widgets.append(sep)
            y += SEP_H

        # 标签
        label = QLabel(subj if subj else "—", self)
        label.setObjectName(f"period_label_{pi}")
        label.setFont(QFont("Microsoft YaHei", 13))
        label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            border-bottom: 1px solid {self._theme.border_color};
            padding-left: 10px;
        """)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        label.setGeometry(0, y, self._win_width, h)
        self._all_content_widgets.append(label)
        self._period_labels[pi] = label

        # 进度条
        bar = QWidget(self)
        bar.setFixedHeight(3)
        bar.setStyleSheet("background: #64B5F6; border: none; border-radius: 2px;")
        bar.setVisible(False)
        bar.setGeometry(4, y + h - 5, 0, 3)
        self._all_content_widgets.append(bar)
        self._period_bars[pi] = bar

        return y + h

    def _build_event_row(self, data: Dict, y: int) -> int:
        """创建一个事件行，返回下一行的 y。"""
        # 分隔线
        sep = QLabel(self)
        sep.setStyleSheet(f"background: {self._theme.border_color};")
        sep.setGeometry(4, y, self._win_width - 8, SEP_H)
        self._all_content_widgets.append(sep)
        y += SEP_H

        # 事件标记
        text = f" ▪ {data['name']}  {data['time']}"
        label = QLabel(text, self)
        label.setFont(QFont("Microsoft YaHei", 8))
        label.setStyleSheet(f"""
            color: {self._theme.font_color};
            background: transparent;
            padding-left: 10px;
        """)
        label.setGeometry(0, y, self._win_width, EVENT_ROW_H)
        self._all_content_widgets.append(label)

        return y + EVENT_ROW_H

    # ================================================================
    #  按钮事件
    # ================================================================
    def _on_fullscreen_time_clicked(self) -> None:
        logger.info("全屏时间")
        self.backend_signal.emit("fullscreen_time")

    def _on_quick_edit_clicked(self) -> None:
        logger.info("快捷编辑")
        self.backend_signal.emit("quick_edit_opened")
        self._show_subject_window()

    def _on_settings_clicked(self) -> None:
        logger.info("设置")
        self.backend_signal.emit("settings")
        self._show_settings_window()

    def _on_close_clicked(self) -> None:
        logger.info("关闭")
        if self._subject_window:
            self._subject_window.close()
            self._subject_window = None
        if self._settings_window:
            self._settings_window.close()
            self._settings_window = None
        self.backend_signal.emit("close")

    def _show_subject_window(self) -> None:
        if self._subject_window:
            self._subject_window.show()
            return
        self._subject_window = SubjectSelectWindow(
            parent_signal=self.backend_signal, theme_manager=self._theme
        )
        self._subject_window.show()

    def _show_settings_window(self) -> None:
        if self._settings_window:
            self._settings_window.close()
            self._settings_window = None
        self._settings_window = SettingsWindow(
            parent_signal=self.backend_signal, theme_manager=self._theme
        )
        self._settings_window.show()

    # ================================================================
    #  公开 API
    # ================================================================
    def get_theme(self) -> 'ThemeManager':
        return self._theme

    def get_current_day_index(self) -> int:
        return self._current_day_index

    def get_period_label(self, index: int) -> Optional[QLabel]:
        if 0 <= index < len(self._period_labels):
            return self._period_labels[index]
        return None

    def get_period_count(self) -> int:
        return self._theme.period_count

    def refresh_labels(self) -> None:
        """完全重建内容行。"""
        self._rebuild_content()

    def set_display_day(self, day_index: int) -> None:
        self._current_day_index = day_index
        self._theme.set_display_day(day_index)
        if self._blink_timer.isActive():
            self.stop_cursor_blink()
        self._rebuild_content()

    # ================================================================
    #  光标闪烁
    # ================================================================
    def start_cursor_blink(self, index: int = 0) -> str:
        if index < 0 or index >= len(self._period_labels):
            return ""
        self.stop_cursor_blink()
        self._cursor_index = index
        self._blink_on = False
        self._blink_timer.start()
        text = (self._period_labels[index].text().strip()
                if self._period_labels[index] else "")
        self.backend_signal.emit(f"cursor_info:{index}:{text}")
        return text

    def stop_cursor_blink(self) -> None:
        if self._blink_timer.isActive():
            self._blink_timer.stop()
        label = (self._period_labels[self._cursor_index]
                 if self._cursor_index < len(self._period_labels) else None)
        if label:
            label.setStyleSheet(f"""
                color: {self._theme.font_color};
                background: transparent;
                border-bottom: 1px solid {self._theme.border_color};
                padding-left: 10px;
            """)
        self._blink_on = False

    def _toggle_blink(self) -> None:
        if not (0 <= self._cursor_index < len(self._period_labels)):
            return
        label = self._period_labels[self._cursor_index]
        if label is None:
            return
        fc, bd = self._theme.font_color, self._theme.border_color
        if self._blink_on:
            label.setStyleSheet(f"""
                color: {fc}; background: transparent;
                border-bottom: 1px solid {bd}; padding-left: 10px;
            """)
        else:
            label.setStyleSheet(f"""
                color: {fc};
                background: rgba(33,150,243,0.18);
                border-bottom: 1px solid {bd};
                border-left: 3px solid rgba(33,150,243,0.6);
                padding-left: 7px;
            """)
        self._blink_on = not self._blink_on

    def move_cursor(self, steps: int) -> str:
        total = len(self._period_labels)
        if total == 0:
            return ""
        new_idx = (self._cursor_index + steps) % total
        self._cursor_index = new_idx
        self._blink_on = False
        # 恢复所有标签
        for lbl in self._period_labels:
            if lbl:
                lbl.setStyleSheet(f"""
                    color: {self._theme.font_color};
                    background: transparent;
                    border-bottom: 1px solid {self._theme.border_color};
                    padding-left: 10px;
                """)
        self._toggle_blink()
        text = (self._period_labels[new_idx].text().strip()
                if self._period_labels[new_idx] else "")
        self.backend_signal.emit(f"cursor_info:{new_idx}:{text}")
        return text

    def set_cursor_subject(self, subject_name: str) -> None:
        if 0 <= self._cursor_index < len(self._period_labels):
            label = self._period_labels[self._cursor_index]
            if label:
                label.setText(subject_name)
                self._theme.set_subject(
                    self._current_day_index, self._cursor_index, subject_name
                )

    def get_cursor_index(self) -> int:
        return self._cursor_index

    def get_cursor_subject(self) -> str:
        if 0 <= self._cursor_index < len(self._period_labels):
            label = self._period_labels[self._cursor_index]
            return label.text().strip() if label else ""
        return ""

    # ================================================================
    #  进度条
    # ================================================================
    def update_progress(self, time_str: str) -> None:
        now = time_str[:5]
        times = self._theme.get_period_times()
        if not times:
            return

        active_found = False
        for i, t in enumerate(times):
            bar = self._period_bars[i] if i < len(self._period_bars) else None
            if bar is None:
                continue
            if not active_found and t.get('start', '') <= now < t.get('end', ''):
                elapsed = self._tm(now) - self._tm(t['start'])
                total = self._tm(t['end']) - self._tm(t['start'])
                pct = max(0.0, min(1.0, elapsed / total)) if total > 0 else 0.0
                bar.setFixedWidth(max(2, int((self._win_width - 8) * pct)))
                bar.setStyleSheet(
                    "background: #64B5F6; border: none; border-radius: 2px;"
                )
                bar.setVisible(True)
                active_found = True
            elif not active_found and t.get('start', '') > now:
                bar.setFixedWidth(4)
                bar.setStyleSheet(
                    "background: rgba(128,128,128,0.25); border: none;"
                    "border-radius: 2px;"
                )
                bar.setVisible(True)
                active_found = True
            else:
                bar.setVisible(False)

    @staticmethod
    def _tm(t: str) -> int:
        parts = t.split(":")
        return int(parts[0]) * 60 + int(parts[1])
