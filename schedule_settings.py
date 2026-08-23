"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_settings.py（设置窗口模块）            ║
║               （全屏设置页面 · 左侧导航 + 右侧内容区）                      ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件负责全屏设置窗口：
  ✅ SettingsWindow — 全屏设置窗口（系统标题栏 + 左2右8布局）
  ✅ TimetableEntryDialog — 时间表条目编辑子窗口
  ✅ NewTimetableDialog — 新建时间表子窗口

左侧导航栏从上到下：
  - 图标展示（DAILY_SCHEDULE.svg + Schedule4.0 并排）
  - 基础设置 / 美化 / 课表编辑 / KnotLink / 关于（带 emoji 图标）

右侧为 QStackedWidget，随左侧导航切换内容页面。
课表编辑页面已实现时间表编辑器；KnotLink 页面展示 openSocket
接口规则与 signal 信号规则参考。
"""

import copy
import json
import logging
import math
import os
import subprocess
import sys
from datetime import date
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QLineEdit, QComboBox, QRadioButton, QFileDialog, QAbstractItemView,
    QScrollArea, QScroller, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, SignalInstance, QTimer, QPointF
from PySide6.QtGui import (
    QFont, QFontDatabase, QIcon, QCloseEvent, QColor,
    QBrush, QImage, QPainter, QPen,
)

from schedule_config import (
    ThemeManager, ThemedWidget, ScheduleDataManager,
    DisplayRulesManager, parse_display_rule,
    SubjectConfigManager, parse_subject_entry, is_color_dark,
    EventRulesManager, SwapManager,
)
from schedule_backend import TimeWheelPicker, WheelColumn
from schedule_translate import TranslateWorker, load_sites, get_default_site
from knotlink_bridge import APPID, SOCKET_ID, SIGNAL_ID

logger: logging.Logger = logging.getLogger(__name__)

# 已关闭对话框遗留的翻译线程池：持有引用直到线程自然结束，
# 防止 QThread 对象在后台线程仍在运行时被销毁导致 Qt 崩溃。
_ORPHAN_WORKERS: List = []


def _cleanup_orphan_worker(worker: Optional[TranslateWorker]) -> None:
    """翻译线程结束后从孤儿池移除并释放对象。"""
    if worker is None:
        return
    if worker in _ORPHAN_WORKERS:
        _ORPHAN_WORKERS.remove(worker)
    worker.deleteLater()


# ==================== 关于页艺术字体 ====================

# 艺术字体候选（按优先级，取系统中第一个可用的字体族）
_ARTISTIC_FONT_CANDIDATES: tuple = (
    'Segoe Script',
    '华文行楷',
    '华文楷体',
    'KaiTi',
    '楷体',
    'Monotype Corsiva',
    'Segoe Print',
    'Lucida Handwriting',
)


def _pick_artistic_font() -> str:
    """从候选列表中挑选第一个已安装的艺术字体；全部缺失时回退到微软雅黑。"""
    available: set = set(QFontDatabase.families())
    for fam in _ARTISTIC_FONT_CANDIDATES:
        if fam in available:
            return fam
    return 'Microsoft YaHei'


# ==================== 开机自启动（注册表） ====================

# 当前用户 Run 键路径：登录 Windows 后自动运行其中的程序
_AUTOSTART_REG_KEY: str = r'Software\Microsoft\Windows\CurrentVersion\Run'
# 本程序在 Run 键下的值名称
_AUTOSTART_VALUE_NAME: str = 'Schedule4.0'


# ==================== KnotLink 接口 / 信号参考数据 ====================
#
# 以下数据与 knotlink_bridge.py 中的实现一一对应，
# 用于设置页 "KnotLink" 标签页展示接口规则（openSocket）与信号规则（signal）。
#
# 接口规则字段：
#   name         接口动作名（action）
#   title        接口标题
#   intro        一句话简介
#   params       参数列表：(字段名, 类型, 是否必填(bool), 说明)
#   returns      返回值列表：(字段名, 类型, 说明)
#   req_example  请求示例（KLKVMap 序列化字符串）
#   resp_example 响应示例（KLKVMap 序列化字符串）
#
# 信号规则字段：
#   name     信号名
#   title    信号标题
#   intro    一句话简介
#   trigger  触发时机
#   fields   载荷字段列表：(字段名, 类型, 说明)
#   example  广播示例（KLKVMap 序列化字符串）

_KNOTLINK_INTERFACES: List[Dict[str, Any]] = [
    {
        "name": "get-lesson-state",
        "title": "查询实时上课状态",
        "intro": "根据当前时间判断是否在上课 / 课间 / 放学，并返回当前课时与下一节课的详细信息。",
        "params": [],
        "returns": [
            ("status", "string", "响应状态：ok（成功）/ err（失败）"),
            ("message", "string", "错误信息（仅在失败时返回）"),
            ("isInClass", "string", "是否正在上课：true / false"),
            ("isBreak", "string", "是否处于课间：true / false"),
            ("isAfterSchool", "string", "是否已放学：true / false"),
            ("currentPeriod", "string", "当前第几节课（非上课状态为 -1）"),
            ("currentSubject", "string", "当前科目名称"),
            ("currentStartTime", "string", "当前课时开始时间（HH:MM:SS）"),
            ("currentEndTime", "string", "当前课时结束时间（HH:MM:SS）"),
            ("remainingTime", "string", "距离下课剩余时间（HH:MM:SS）"),
            ("nextPeriod", "string", "下一节课序号（无下一节为 -1）"),
            ("nextSubject", "string", "下一节课科目名称"),
            ("nextStartTime", "string", "下一节课开始时间（HH:MM:SS）"),
        ],
        "req_example": '{"action": "get-lesson-state"}',
        "resp_example": (
            '{"status": "ok", "isInClass": "true", "isBreak": "false", '
            '"isAfterSchool": "false", "currentPeriod": "3", '
            '"currentSubject": "数学", "currentStartTime": "10:10:00", '
            '"currentEndTime": "10:50:00", "remainingTime": "00:20:00", '
            '"nextPeriod": "4", "nextSubject": "英语", '
            '"nextStartTime": "11:00:00"}'
        ),
    },
    {
        "name": "get-today-schedule",
        "title": "获取当天（或指定星期）完整课表",
        "intro": "获取当天或指定星期（Monday~Sunday）的完整课表，包含每节课的科目、起止时间与分隔线位置。",
        "params": [
            ("day", "string", False, "英文星期名 Monday~Sunday；缺省时为今天"),
        ],
        "returns": [
            ("status", "string", "响应状态：ok（成功）/ err（失败）"),
            ("message", "string", "错误信息（仅在失败时返回）"),
            ("day", "string", "实际查询的星期名称"),
            ("lessons", "json", "课程数组（JSON 字符串），每项含 period / key / subject / startTime / endTime"),
            ("dividerIndices", "json", "分隔线位置数组（JSON 字符串）"),
            ("totalPeriods", "string", "总课时数"),
        ],
        "req_example": '{"action": "get-today-schedule", "day": "Monday"}',
        "resp_example": (
            '{"status": "ok", "day": "Monday", "lessons": '
            '"[{\\"period\\":1,\\"key\\":\\"lesson_1\\",\\"subject\\":\\"语文\\",'
            '\\"startTime\\":\\"08:00:00\\",\\"endTime\\":\\"08:40:00\\"}, ...]", '
            '"dividerIndices": "[2, 4]", "totalPeriods": "8"}'
        ),
    },
    {
        "name": "swap-course",
        "title": "临时换课",
        "intro": "将某天某节课临时替换为其他科目并写入换课记录；若换课日期是今天且主窗口正在显示该星期，立即刷新显示。",
        "params": [
            ("day_name", "string", True, "英文星期名 Monday~Sunday"),
            ("lesson_key", "string", True, "课时键名 lesson_N（如 lesson_2）"),
            ("old_subject", "string", False, "原科目名称"),
            ("new_subject", "string", False, "新科目名称"),
            ("swap_date", "string", False, "换课日期 YYYY-MM-DD；缺省时自动计算该星期下一个匹配日期"),
        ],
        "returns": [
            ("status", "string", "响应状态：ok（成功）/ err（失败）"),
            ("message", "string", "错误信息（仅在失败时返回）"),
            ("swap_date", "string", "实际生效的换课日期（YYYY-MM-DD）"),
        ],
        "req_example": (
            '{"action": "swap-course", "day_name": "Monday", '
            '"lesson_key": "lesson_2", "old_subject": "数学", '
            '"new_subject": "体育", "swap_date": "2025-07-07"}'
        ),
        "resp_example": '{"status": "ok", "swap_date": "2025-07-07"}',
    },
    {
        "name": "enter-fullscreen",
        "title": "进入全屏时间模式",
        "intro": "进入考试模式或创意模式的全屏时间显示；进入前会取消浮动时间窗口的置顶状态。",
        "params": [
            ("mode", "string", False, "全屏模式：exam（考试模式，缺省）/ creative（创意模式）"),
        ],
        "returns": [
            ("status", "string", "响应状态：ok（成功）/ err（失败）"),
            ("message", "string", "错误信息（仅在失败时返回）"),
            ("mode", "string", "实际进入的全屏模式：exam / creative"),
        ],
        "req_example": '{"action": "enter-fullscreen", "mode": "exam"}',
        "resp_example": '{"status": "ok", "mode": "exam"}',
    },
    {
        "name": "exit-fullscreen",
        "title": "退出全屏时间模式",
        "intro": "退出全屏模式并隐藏对应窗口，恢复浮动时间窗口的置顶状态。",
        "params": [],
        "returns": [
            ("status", "string", "响应状态：ok（成功）/ err（失败）"),
            ("message", "string", "错误信息（仅在失败时返回）"),
        ],
        "req_example": '{"action": "exit-fullscreen"}',
        "resp_example": '{"status": "ok"}',
    },
]

_KNOTLINK_SIGNALS: List[Dict[str, Any]] = [
    {
        "name": "onClassStart",
        "title": "上课开始",
        "intro": "状态从「非上课」切换为「上课」（上课铃响）时广播，携带当前课时信息。",
        "trigger": "每节课开始时（从课间或放学状态进入上课状态）",
        "fields": [
            ("event", "string", "固定为 onClassStart"),
            ("period", "string", "当前第几节课"),
            ("subject", "string", "当前科目名称"),
            ("startTime", "string", "本节课开始时间（HH:MM:SS）"),
            ("endTime", "string", "本节课结束时间（HH:MM:SS）"),
        ],
        "example": (
            '{"event": "onClassStart", "period": "3", "subject": "数学", '
            '"startTime": "10:10:00", "endTime": "10:50:00"}'
        ),
    },
    {
        "name": "onClassEnd",
        "title": "下课（进入课间）",
        "intro": "状态从「上课中」切换为「课间」时广播，携带下一节课信息与距离下节课的剩余时间。",
        "trigger": "本节课结束时（从上课状态进入课间状态）",
        "fields": [
            ("event", "string", "固定为 onClassEnd"),
            ("nextPeriod", "string", "下一节课序号（无下一节为 -1）"),
            ("nextSubject", "string", "下一节课科目名称"),
            ("nextStartTime", "string", "下一节课开始时间（HH:MM:SS）"),
            ("leftTime", "string", "距离下一节课开始剩余时间（HH:MM:SS）"),
        ],
        "example": (
            '{"event": "onClassEnd", "nextPeriod": "4", "nextSubject": "英语", '
            '"nextStartTime": "11:00:00", "leftTime": "00:10:00"}'
        ),
    },
    {
        "name": "onDayEnd",
        "title": "放学",
        "intro": "最后一节课结束、状态切换为「放学」时广播。",
        "trigger": "当天最后一节课结束时（从上课状态进入放学状态）",
        "fields": [
            ("event", "string", "固定为 onDayEnd"),
        ],
        "example": '{"event": "onDayEnd"}',
    },
    {
        "name": "onEventTrigger",
        "title": "自定义事件触发",
        "intro": "用户自定义事件规则（Config/event_rules.json）到达触发时刻时广播。",
        "trigger": "事件规则命中今天且事件时间（HH:MM）与当前时间一致；同一条事件每天只广播一次",
        "fields": [
            ("event", "string", "固定为 onEventTrigger"),
            ("name", "string", "事件名称"),
            ("date", "string", "触发日期（YYYY-MM-DD）"),
            ("time", "string", "触发时间（HH:MM）"),
        ],
        "example": (
            '{"event": "onEventTrigger", "name": "午休提醒", '
            '"date": "2025-07-07", "time": "12:00"}'
        ),
    },
]


def _html_escape(text: str) -> str:
    """转义富文本标签中的 HTML 特殊字符（& < >）。"""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


# ==================== 科目名称自动缩写 ====================

# 中文名最大长度（字符），超过则截断到前 SUBJECT_CN_MAX_LEN 个字符。
SUBJECT_CN_MAX_LEN: int = 7
# 英文名最大长度（字符，含空格与符号），超过则自动缩写。
SUBJECT_EN_MAX_LEN: int = 12

# 众所周知的整句英文缩写（键统一小写，整句优先匹配）。
# 缩写结果统一为无空格、无连字符的紧凑形式。
_ENGLISH_PHRASE_ABBR: Dict[str, str] = {
    'information technology': 'InfoTech',
    'physical education': 'PE',
    'general technology': 'GenTech',
    'physical and chemical': 'PhysChem',
}

# 单词级英文缩写（键统一小写；仅当整句未命中时逐词使用）。
_ENGLISH_WORD_ABBR: Dict[str, str] = {
    'electromagnetics': 'Electromag',
    'biochemistry': 'Biochem',
    'general': 'Gen',
}

# 缩写时跳过的英文虚词（对辨识度无贡献）。
_ENGLISH_STOPWORDS = {'and', 'of', 'the', 'in', 'on', 'for', 'with', 'or'}


def abbreviate_chinese_name(name: str, max_len: int = SUBJECT_CN_MAX_LEN) -> str:
    """
    中文名超过 max_len 个字符时截断到前 max_len 个字符。
    -----------------------------------------------
    参数：
        name    （str）：待处理的中文名
        max_len （int）：最大长度，默认 7

    返回值：
        str：未超长时原样返回，超长时返回前 max_len 个字符
    """
    text: str = name.strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def abbreviate_english_name(name: str, max_len: int = SUBJECT_EN_MAX_LEN) -> str:
    """
    把过长的科目英文名缩写为易辨识的紧凑短形式（无空格、无连字符）。
    -------------------------------------------------------------
    规则：
      1. 整句（小写比较）命中已知缩写表时直接使用；
      2. 否则先按空白、连字符、下划线、斜杠等分隔符拆成单词，再逐词缩写：
         命中单词表用对应缩写，否则取单词前 4 个字母并首字母大写
         （不足 7 个字母的单词保持原样），英文虚词跳过；
      3. 单词缩写结果直接拼接（去掉空格与连字符等分隔符）；
      4. 最终结果若仍超过 max_len，则截断到 max_len。

    参数：
        name    （str）：待缩写的英文名
        max_len （int）：目标最大长度，默认 12

    返回值：
        str：缩写结果；无法产生有效缩写时返回原字符串
    """
    original: str = name.strip()
    if not original:
        return original

    lowered: str = original.lower()
    # 归一化分隔符：连字符 / 下划线 / 斜杠等统一视为空格，使
    # 「Physical-Education」等写法也能命中整句缩写表（如 PE）。
    normalized: str = lowered.replace('-', ' ').replace('_', ' ').replace('/', ' ')
    if normalized in _ENGLISH_PHRASE_ABBR:
        return _ENGLISH_PHRASE_ABBR[normalized]

    # 先按空白、连字符、下划线、斜杠等分隔符拆成单词
    separated: str = normalized

    abbr_words: List[str] = []
    for raw_word in separated.split():
        letters: str = ''.join(ch for ch in raw_word if ch.isalpha())
        if not letters:
            continue
        lw: str = letters.lower()
        if lw in _ENGLISH_STOPWORDS:
            continue
        if lw in _ENGLISH_WORD_ABBR:
            abbr_words.append(_ENGLISH_WORD_ABBR[lw])
        elif len(letters) <= 6:
            abbr_words.append(letters[:1].upper() + letters[1:].lower())
        else:
            stem: str = letters[:4].lower()
            abbr_words.append(stem[:1].upper() + stem[1:])

    if not abbr_words:
        return original

    # 紧凑拼接：去掉单词之间的空格（连字符等已在拆分时去除）
    result: str = ''.join(abbr_words).strip()
    if len(result) > max_len:
        result = result[:max_len].rstrip()
    return result if result else original


# ==================== 开关控件 ====================

class ToggleSwitch(QWidget):
    """
    # ToggleSwitch — 简单的开关按钮

    点击切换开/关状态，通过 paintEvent 绘制圆角轨道与滑块。
    """

    # 信号：状态切换（参数为新状态）
    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化开关控件。"""
        super().__init__(parent)
        self._checked: bool = False
        self.setFixedSize(48, 26)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore

    def isChecked(self) -> bool:
        """返回当前开关状态。"""
        return self._checked

    def setChecked(self, checked: bool) -> None:
        """设置开关状态（不触发 toggled 信号）。"""
        self._checked = bool(checked)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        """点击切换状态并发出 toggled 信号。"""
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        """绘制开关轨道与滑块。"""
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # type: ignore

        w: int = self.width()
        h: int = self.height()
        track: QColor = QColor('#2196F3') if self._checked else QColor('#9E9E9E')
        painter.setPen(Qt.NoPen)  # type: ignore
        painter.setBrush(QBrush(track))
        painter.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        margin: int = 3
        knob_d: int = h - margin * 2
        knob_x: int = (w - knob_d - margin) if self._checked else margin
        painter.setBrush(QBrush(QColor('#FFFFFF')))
        painter.drawEllipse(knob_x, margin, knob_d, knob_d)


# ==================== 色相圆盘控件 ====================

class ColorWheel(QWidget):
    """
    # ColorWheel — HSV 色相圆盘

    圆盘一周为色相，半径方向为饱和度（中心为白色，边缘为纯色）。
    点击 / 拖动选择颜色，通过 color_changed 信号通知。
    """

    # 信号：颜色变化（参数为当前选中颜色）
    color_changed = Signal(QColor)

    def __init__(self, parent: QWidget | None = None, size: int = 180) -> None:
        """初始化色相圆盘。"""
        super().__init__(parent)
        self._radius: int = size // 2
        self._hue: float = 0.0
        self._sat: float = 0.0
        self._indicator_radius: int = 6
        self._image: Optional[QImage] = None
        self.setFixedSize(size, size)
        self.setCursor(Qt.CrossCursor)  # type: ignore
        self._build_wheel_image()

    def _build_wheel_image(self) -> None:
        """逐像素生成 HSV 色相圆盘图像并缓存。"""
        d: int = self._radius * 2
        img: QImage = QImage(d, d, QImage.Format_ARGB32)  # type: ignore
        img.fill(QColor(0, 0, 0, 0))
        cx: int = self._radius
        cy: int = self._radius
        max_r: float = float(self._radius - 2)
        for y in range(d):
            for x in range(d):
                dx: int = x - cx
                dy: int = y - cy
                dist: float = math.hypot(dx, dy)
                if dist <= max_r:
                    hue: float = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
                    sat: float = dist / max_r
                    color: QColor = QColor.fromHsvF(hue / 360.0, sat, 1.0)
                    img.setPixel(x, y, color.rgb())
        self._image = img

    def current_color(self) -> QColor:
        """返回当前选中的颜色。"""
        return QColor.fromHsvF(self._hue / 360.0, self._sat, 1.0)

    def set_color(self, color: QColor) -> None:
        """设置当前颜色（不触发信号）。"""
        h, s, _v, _a = color.getHsvF() # type: ignore
        self._hue = h * 360.0
        self._sat = s
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        """绘制圆盘与选中指示器。"""
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # type: ignore
        if self._image is not None:
            painter.drawImage(0, 0, self._image)

        angle: float = math.radians(self._hue)
        r: float = self._sat * float(self._radius - 2)
        px: float = self._radius + r * math.cos(angle)
        py: float = self._radius + r * math.sin(angle)
        painter.setPen(QPen(QColor('#FFFFFF'), 2))
        painter.setBrush(QBrush(self.current_color()))
        painter.drawEllipse(
            QPointF(px, py),
            float(self._indicator_radius),
            float(self._indicator_radius),
        )

    def _update_from_pos(self, pos) -> None:  # noqa: ANN001
        """根据坐标更新色相 / 饱和度并发出信号。"""
        dx: float = float(pos.x() - self._radius)
        dy: float = float(pos.y() - self._radius)
        dist: float = math.hypot(dx, dy)
        max_r: float = float(self._radius - 2)
        self._sat = min(1.0, max(0.0, dist / max_r))
        self._hue = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
        self.update()
        self.color_changed.emit(self.current_color())

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        """按下即选择颜色。"""
        self._update_from_pos(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        """按住拖动连续选择颜色。"""
        if event.buttons() & Qt.LeftButton:  # type: ignore
            self._update_from_pos(event.position().toPoint())


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
        ("🔗", "KnotLink", 3),
        ("ℹ️", "关于",     4),
    ]

    # 信号：时间表发生变更，通知主窗口重建标签
    timetable_changed = Signal()
    # 信号：用户显式应用修改后通知主窗口刷新
    changes_applied = Signal()

    def __init__(self, parent_signal: SignalInstance,
                 theme_manager: ThemeManager,
                 schedule_data: Optional[ScheduleDataManager] = None) -> None:
        """
        初始化设置窗口。
        ---------------
        参数：
            parent_signal（SignalInstance）：父窗口的 backend_signal
            theme_manager（ThemeManager）：  全局主题管理器
            schedule_data（ScheduleDataManager）：课表数据管理器
        """
        super().__init__(theme_manager, bg_color_attr='root_back_color')

        self._parent_signal: SignalInstance = parent_signal
        self._schedule_data: Optional[ScheduleDataManager] = schedule_data
        self._nav_buttons: List[QPushButton] = []
        self._exit_btn: Optional[QPushButton] = None
        self._current_index: int = 0

        # 时间表编辑器引用
        self._timetable_table: Optional[QTableWidget] = None
        self._status_label: Optional[QLabel] = None
        self._status_card: Optional[QFrame] = None
        self._table_frame: Optional[QFrame] = None
        self._add_dialog: Optional[TimetableEntryDialog] = None

        # 课程表编辑器引用
        self._curriculum_table: Optional[QTableWidget] = None
        self._curriculum_status_label: Optional[QLabel] = None
        self._curriculum_status_card: Optional[QFrame] = None
        self._curriculum_table_frame: Optional[QFrame] = None

        # 课程表内联编辑器
        self._cv_editor_card: Optional[QFrame] = None
        self._cv_cursor_row: int = -1
        self._cv_cursor_col: int = -1
        self._cv_cursor_day: str = ''
        self._cv_cursor_lesson: str = ''
        self._cv_blink_timer: QTimer = QTimer()
        self._cv_blink_timer.setInterval(500)
        self._cv_blink_timer.timeout.connect(self._toggle_cv_blink)
        self._cv_blink_on: bool = False
        self._pending_curriculum_data: Dict = {}
        self._cv_status_label: Optional[QLabel] = None
        self._cv_subject_buttons: List[QPushButton] = []
        self._cv_subject_categories: Dict[str, List[str]] = {}

        # 编辑副本：隔离设置页面编辑操作与主窗口共享数据
        self._editing_timetable_data: Dict = {}
        self._editing_curriculum_data: Dict = {}
        self._editing_timetable_path: str = ''   # 当前编辑的时间表文件路径
        self._editing_curriculum_path: str = ''  # 当前编辑的课程表文件路径
        self._has_unsaved_changes: bool = False  # 是否有尚未应用到当前程序的修改
        self._editing_initialized: bool = False  # 编辑副本是否已完成首次初始化

        # 应用修改按钮引用（位于左侧导航栏底部、退出按钮下方）
        self._apply_btn: Optional[QPushButton] = None

        # 基础设置 — 字体修改引用
        self._font_card: Optional[QFrame] = None
        self._font_combo: Optional[QComboBox] = None
        self._font_preview_label: Optional[QLabel] = None
        self._font_preview_title_label: Optional[QLabel] = None
        self._font_title_label: Optional[QLabel] = None
        self._font_hint_label: Optional[QLabel] = None
        self._applied_subject_font: str = self._theme.subject_font

        # 基础设置 — 语言切换引用
        self._language_card: Optional[QFrame] = None
        self._language_combo: Optional[QComboBox] = None
        self._language_title_label: Optional[QLabel] = None
        self._language_hint_label: Optional[QLabel] = None
        self._applied_language: str = self._theme.language

        # 基础设置 — 开机自启动引用
        self._autostart_card: Optional[QFrame] = None
        self._autostart_switch: Optional[ToggleSwitch] = None
        self._autostart_title_label: Optional[QLabel] = None
        self._autostart_hint_label: Optional[QLabel] = None
        self._applied_autostart: bool = self._is_autostart_enabled()

        # 美化 — 明暗模式 / 主题色引用
        self._applied_theme: str = self._theme.theme
        self._applied_theme_color: str = self._theme.theme_color
        self._pending_color: str = self._theme.theme_color
        self._theme_card: Optional[QFrame] = None
        self._theme_combo: Optional[QComboBox] = None
        self._theme_title_label: Optional[QLabel] = None
        self._theme_hint_label: Optional[QLabel] = None
        self._color_card: Optional[QFrame] = None
        self._color_mode_switch: Optional[ToggleSwitch] = None
        self._color_title_label: Optional[QLabel] = None
        self._color_hint_label: Optional[QLabel] = None
        self._color_picker_area: Optional[QWidget] = None
        self._color_wheel: Optional[ColorWheel] = None
        self._color_preview: Optional[QFrame] = None
        self._color_rgb_label: Optional[QLabel] = None
        self._color_confirm_btn: Optional[QPushButton] = None

        # 显示规则引用
        self._rule_list: Optional[DisplayRuleListWidget] = None
        self._rule_add_btn: Optional[QPushButton] = None

        # 科目编辑引用
        self._subject_config_manager: SubjectConfigManager = SubjectConfigManager()
        self._subject_config_data: Dict = {}
        self._subject_card: Optional[QFrame] = None
        self._subject_scroll_layout: Optional[QVBoxLayout] = None
        self._subject_buttons: List[QPushButton] = []
        # 课程表内联编辑器的科目按钮区布局（重建时使用）
        self._cv_subject_layout: Optional[QVBoxLayout] = None

        # 事件系统引用
        self._event_manager: EventRulesManager = EventRulesManager()
        self._event_rules: List[Dict] = []
        self._event_card: Optional[QFrame] = None
        self._event_scroll_layout: Optional[QVBoxLayout] = None
        self._event_buttons: List[QPushButton] = []

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
        main_layout.addWidget(left_panel, stretch=1)

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
        main_layout.addWidget(right_panel, stretch=9)

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
          5. 退出按钮（🚪）
          6. 应用修改按钮（✅，位于退出按钮下方）
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

        # ---- 应用修改按钮（位于退出按钮下方）----
        self._apply_btn = QPushButton("  ✅  应用修改")
        self._apply_btn.setFont(QFont("Microsoft YaHei", 11))
        self._apply_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._apply_btn.setMinimumHeight(44)
        self._apply_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        self._apply_btn.setEnabled(False)  # 初始无修改时禁用
        self._apply_btn.clicked.connect(self._on_apply_changes)
        layout.addWidget(self._apply_btn)

        # 应用初始样式
        self._refresh_nav_styles()
        self._refresh_exit_btn_style()
        self._refresh_apply_button()

        return panel

    # ================================================================
    #  构建右侧内容区
    # ================================================================
    def _build_right_panel(self) -> QWidget:
        """
        构建右侧内容区域。
        ----------------
        使用 QStackedWidget 管理 5 个页面：
        基础设置 / 美化 / 课表编辑 / KnotLink / 关于。
        """
        right_panel: QWidget = QWidget()
        right_panel.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(right_panel)
        layout.setContentsMargins(32, 32, 32, 32)

        self._stack: QStackedWidget = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        # 页面 0：基础设置（开机自启动 + 字体修改 + 语言切换）
        self._stack.addWidget(self._create_basic_settings_page())
        # 页面 1：美化（明暗模式 + 主题色）
        self._stack.addWidget(self._create_beautify_page())
        # 页面 2：课表编辑（实际编辑器）
        self._stack.addWidget(self._create_timetable_editor_page())
        # 页面 3：KnotLink（openSocket 接口规则 + signal 信号规则）
        self._stack.addWidget(self._create_knotlink_page())
        # 页面 4：关于
        self._stack.addWidget(self._create_about_page())

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
    #  创建关于页面
    # ================================================================
    def _create_about_page(self) -> QWidget:
        """
        构建「关于」页面。
        -----------------
        不使用卡片容器，页面自上而下：
          页面标题（左上角）→ 内容区（水平居中、垂直分布在页面中部）：
            品牌行（软件图标 + Schedule4.0 标题，左右排版、整体居中）
            → 作者署名 → 软件简介
        软件名称使用艺术字体，作者署名与简介均水平居中，
        作者署名通过上下弹性空间的比例控制，尽量落在页面垂直中心附近。
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        fc: str = self._theme.font_color

        # ---- 页面主标题 ----
        page_title: QLabel = QLabel("关于")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(page_title)

        # ---- 内容区（无卡片，整体居中）----
        content: QWidget = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout: QVBoxLayout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 计算上下弹性空间权重，使作者署名尽量落在页面垂直中心：
        #   author_y = 标题区高度 + 上方间隙 + 品牌行高度/间距 + 署名半高
        #   令 author_y ≈ 页面高度 / 2，反推上方间隙，其余空间留给下方。
        _title_block_h: int = 52      # 页面标题(40) + 布局间距(12)
        _above_author_h: int = 160    # 品牌行128 + 间距20 + 署名半高12
        _content_block_h: int = 242   # 品牌行128 + 间距20 + 署名24 + 间距26 + 简介44
        _avail_h: int = max(1, self._theme.screen_height - _title_block_h - _content_block_h)
        _top_gap: int = max(1, self._theme.screen_height // 2 - _title_block_h - _above_author_h)
        _bottom_gap: int = max(1, _avail_h - _top_gap)

        # 上方弹性空间（使作者署名位于页面垂直中心附近）
        content_layout.addStretch(_top_gap)

        # ---- 品牌行：软件图标 + 软件名称（左右排版，整体居中）----
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        icon_path: str = os.path.join(
            script_dir, 'images', 'Icons', 'DAILY_SCHEDULE.svg'
        )

        icon_label: QLabel = QLabel()
        icon_label.setFixedSize(128, 128)
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(128, 128))
        icon_label.setStyleSheet("background: transparent; border: none;")

        name_label: QLabel = QLabel("Schedule4.0")
        name_label.setFont(QFont(_pick_artistic_font(), 44))
        name_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)  # type: ignore

        brand_row: QHBoxLayout = QHBoxLayout()
        brand_row.setSpacing(24)
        brand_row.setAlignment(Qt.AlignCenter)  # type: ignore
        brand_row.addWidget(icon_label)
        brand_row.addWidget(name_label)
        content_layout.addLayout(brand_row)

        content_layout.addSpacing(20)

        # ---- 作者署名（居中，LG 参数决定）----
        author_text: str = "高2026届 赵晨羽" if self._theme.lg else "温谨"
        author_label: QLabel = QLabel(f"作者：{author_text}")
        author_label.setFont(QFont("Microsoft YaHei", 14))
        author_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        author_label.setAlignment(Qt.AlignCenter)  # type: ignore
        content_layout.addWidget(author_label, 0, Qt.AlignHCenter)  # type: ignore

        content_layout.addSpacing(26)

        # ---- 软件简介（居中显示，固定宽度并按宽度计算高度保证完整换行）----
        intro_label: QLabel = QLabel(
            "桌面浮动电子课表系统，半透明置顶窗口实时显示课时科目与当前时间，"
            "支持快捷编辑、临时换课、考试 / 创意全屏模式，"
            "并可通过 KnotLink 协议对外广播课表与自定义事件。"
        )
        intro_label.setFont(QFont("Microsoft YaHei", 11))
        intro_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        intro_label.setWordWrap(True)
        intro_label.setAlignment(Qt.AlignCenter)  # type: ignore
        intro_label.setFixedWidth(640)
        # 固定宽度下按文字换行计算所需高度，保证简介完整显示不被裁剪
        intro_label.setFixedHeight(intro_label.heightForWidth(640))
        content_layout.addWidget(intro_label, 0, Qt.AlignHCenter)  # type: ignore

        # 下方弹性空间（吸收剩余空间，保持署名居中）
        content_layout.addStretch(_bottom_gap)

        layout.addWidget(content, 1)

        return page

    # ================================================================
    #  创建 KnotLink 页面
    # ================================================================
    def _create_knotlink_page(self) -> QWidget:
        """
        构建"KnotLink"页面。
        ------------------
        页面标题（左侧 KnotLink 图标 + "KnotLink设置"），下方三个卡片分区：
          - 接口（openSocket）：openSocket 接口规则列表
          - 信号（signal）：signal 信号规则列表
          - 事件系统：自定义事件规则列表（触发时广播 onEventTrigger 信号）
        每条规则是一个按钮，按钮上显示规则名称与简介；
        点击按钮弹出详情对话框，展示接口 / 参数 / 返回值等详细信息。
        页面整体放入滚动区域，内容较多时自动出现滚动条。
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 滚动区域（内容超出可视高度时自动滚动）
        scroll: QScrollArea = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)  # type: ignore
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore

        inner: QWidget = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout: QVBoxLayout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(14)

        fc: str = self._theme.font_color

        # ---- 页面主标题（KnotLink 图标 + 标题文字）----
        title_row: QHBoxLayout = QHBoxLayout()
        title_row.setSpacing(12)

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        icon_path: str = os.path.join(script_dir, 'images', 'Icons', 'knotlink.svg')

        icon_label: QLabel = QLabel()
        icon_label.setFixedSize(36, 36)
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(36, 36))
        icon_label.setStyleSheet("background: transparent; border: none;")
        title_row.addWidget(icon_label)

        page_title: QLabel = QLabel("KnotLink设置")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        title_row.addWidget(page_title)
        title_row.addStretch()
        inner_layout.addLayout(title_row)

        # ---- 本机接口 AppID 卡片 ----
        node_card: QFrame = QFrame()
        node_card.setObjectName('knotlinkCard')
        node_card.setStyleSheet(self._get_knotlink_card_style())
        node_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        node_card_layout: QVBoxLayout = QVBoxLayout(node_card)
        node_card_layout.setContentsMargins(20, 12, 20, 12)
        node_card_layout.setSpacing(4)

        node_title: QLabel = QLabel("本机接口AppID")
        node_title.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))  # type: ignore
        node_title.setStyleSheet(f"color: {fc}; background: transparent;")
        node_card_layout.addWidget(node_title)

        # 点击按钮将本机 AppID 复制到剪切板
        node_id_btn: QPushButton = QPushButton(APPID)
        node_id_btn.setFont(QFont("Consolas", 12))
        node_id_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        node_id_btn.setToolTip("点击复制本机 AppID 到剪切板")
        node_id_btn.setStyleSheet(self._get_appid_button_style())
        node_id_btn.clicked.connect(self._on_copy_appid)
        self._knotlink_appid_btn = node_id_btn
        node_card_layout.addWidget(node_id_btn)

        inner_layout.addWidget(node_card)

        # ---- 事件系统分区 ----
        inner_layout.addWidget(self._build_event_section_card())

        # ---- 接口（openSocket）分区 ----
        inner_layout.addWidget(self._build_knotlink_section_card(
            "接口（openSocket）", _KNOTLINK_INTERFACES, is_signal=False,
        ))

        # ---- 信号（signal）分区 ----
        inner_layout.addWidget(self._build_knotlink_section_card(
            "信号（signal）", _KNOTLINK_SIGNALS, is_signal=True,
        ))

        inner_layout.addStretch()

        scroll.setWidget(inner)
        layout.addWidget(scroll)

        return page

    def _build_knotlink_section_card(self, title: str, items: List[Dict],
                                     is_signal: bool) -> QFrame:
        """
        构建一个 KnotLink 规则分区卡片。
        -----------------------------
        卡片内部：分区标题 + 简短提示 + 规则表格（每条规则为一个按钮）。
        """
        fc: str = self._theme.font_color

        card: QFrame = QFrame()
        card.setObjectName('knotlinkCard')
        card.setStyleSheet(self._get_knotlink_card_style())
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore

        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 14, 20, 16)
        card_layout.setSpacing(10)

        # ---- 分区标题 ----
        section_title: QLabel = QLabel(title)
        section_title.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))  # type: ignore
        section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        card_layout.addWidget(section_title)

        # ---- 分区提示 ----
        hint: QLabel = QLabel(
            "点击任意一条信号规则，查看触发时机与载荷字段说明"
            if is_signal else
            "点击任意一条接口规则，查看接口、参数与返回值说明"
        )
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet(f"color: {fc}; background: transparent; opacity: 0.55;")
        card_layout.addWidget(hint)

        # ---- 规则表格：每行一个按钮（名称 + 简介）----
        table: QTableWidget = QTableWidget()
        table.setFrameShape(QFrame.NoFrame)  # type: ignore
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["名称", "简介"])
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # type: ignore
        table.setSelectionMode(QAbstractItemView.NoSelection)  # type: ignore
        table.setFocusPolicy(Qt.NoFocus)  # type: ignore
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch  # type: ignore
        )
        self._style_knotlink_table(table)

        row: int = 0
        for item in items:
            name: str = str(item.get('name', ''))
            item_title: str = str(item.get('title', ''))
            intro: str = str(item.get('intro', ''))
            intro_short: str = intro if len(intro) <= 50 else intro[:50] + "…"

            btn_text: str = f"{name} — {item_title}\n{intro_short}"
            btn: QPushButton = QPushButton(btn_text)
            btn.setFont(QFont("Microsoft YaHei", 11))
            btn.setCursor(Qt.PointingHandCursor)  # type: ignore
            btn.setMinimumHeight(60)
            self._style_knotlink_row_button(btn)

            btn.clicked.connect(
                lambda checked=False, it=item, sig=is_signal:
                self._on_knotlink_item_clicked(it, sig)
            )

            table.insertRow(row)
            table.setSpan(row, 0, 1, 2)
            table.setCellWidget(row, 0, btn)
            table.setRowHeight(row, 62)
            row += 1

        # 表格高度固定为内容高度（表头 + 各行按钮，无外框）
        header_h: int = table.horizontalHeader().sizeHint().height()
        table.setFixedHeight(max(34, header_h) + 62 * len(items) + 1)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        card_layout.addWidget(table)

        return card

    def _build_event_section_card(self) -> QFrame:
        """
        构建"事件系统"分区卡片（格式与 KnotLink 其余卡片一致）。
        -----------------------------------------------------
        卡片内部：分区标题 + 简短提示 + 事件规则按钮列表 + 新建事件按钮。
        事件规则到达触发时刻时，KnotLink 会广播 onEventTrigger 信号。
        """
        fc: str = self._theme.font_color

        card: QFrame = QFrame()
        card.setObjectName('knotlinkCard')
        card.setStyleSheet(self._get_knotlink_card_style())
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        self._event_card = card

        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 14, 20, 16)
        card_layout.setSpacing(10)

        # ---- 分区标题 ----
        section_title: QLabel = QLabel("事件系统")
        section_title.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))  # type: ignore
        section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        card_layout.addWidget(section_title)

        # ---- 分区提示 ----
        hint: QLabel = QLabel(
            "自定义事件到达触发时刻时，KnotLink 将广播 onEventTrigger 信号；"
            "点击任意一条事件规则查看或编辑，也可新建自定义事件。"
        )
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet(f"color: {fc}; background: transparent; opacity: 0.55;")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        # ---- 事件规则按钮列表 ----
        # 规则按钮直接放在普通容器中（不使用内部 QScrollArea）：
        # 卡片高度时刻等于内容高度，所有事件规则按钮完整显示；
        # 内容超出页面时由页面外层滚动区统一滚动，不会压缩卡片高度。
        ev_subjects_widget: QWidget = QWidget()
        ev_subjects_widget.setStyleSheet("background: transparent;")
        self._event_scroll_layout = QVBoxLayout(ev_subjects_widget)
        self._event_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._event_scroll_layout.setSpacing(6)
        card_layout.addWidget(ev_subjects_widget)

        # ---- 新建事件按钮 ----
        ev_btn_row: QHBoxLayout = QHBoxLayout()
        ev_btn_row.setSpacing(12)

        new_event_btn: QPushButton = QPushButton("＋ 新建事件")
        new_event_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        new_event_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        new_event_btn.setMinimumHeight(38)
        new_event_btn.setStyleSheet(self._get_add_btn_style())
        new_event_btn.clicked.connect(self._on_new_event)
        ev_btn_row.addWidget(new_event_btn)

        ev_btn_row.addStretch()
        card_layout.addLayout(ev_btn_row)

        # 初始加载事件规则并渲染规则按钮
        self._load_event_rules()
        self._refresh_event_rules()

        return card

    # ================================================================
    #  KnotLink 规则表格 / 按钮样式
    # ================================================================
    def _style_knotlink_table(self, table: QTableWidget) -> None:
        """根据主题刷新 KnotLink 规则表格样式。"""
        fc: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            header_bg: str = 'rgba(255,255,255,0.06)'
        else:
            header_bg = 'rgba(0,0,0,0.04)'

        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: transparent;
                color: {fc};
                border: none;
            }}
            QTableWidget::item {{
                padding: 0px;
                border: none;
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {fc};
                border: none;
                border-bottom: 1px solid {self._theme.border_color};
                padding: 8px 12px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    def _style_knotlink_row_button(self, btn: QPushButton) -> None:
        """设置 KnotLink 规则按钮的样式（左对齐、悬浮高亮）。"""
        fc: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.03)'
            hover_bg: str = 'rgba(255,255,255,0.08)'
            pressed_bg: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.02)'
            hover_bg = 'rgba(0,0,0,0.06)'
            pressed_bg = 'rgba(0,0,0,0.10)'

        btn.setStyleSheet(f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: none;
                border-radius: 4px;
                padding: 10px 14px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """)

    def _get_knotlink_card_style(self) -> str:
        """返回 KnotLink 卡片容器样式。

        通过对象名限定选择器只作用于卡片本身，
        避免 QFrame 规则泄漏到卡片内部的 QLabel 等控件上
        （QLabel 是 QFrame 子类，未限定时会继承 1px 边框）。
        """
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.04)'
            card_border: str = 'rgba(255,255,255,0.08)'
        else:
            card_bg = 'rgba(0,0,0,0.03)'
            card_border = 'rgba(0,0,0,0.06)'

        return f"""
            QFrame#knotlinkCard {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
            }}
        """

    def _get_appid_button_style(self) -> str:
        """返回本机 AppID 按钮的样式（无边框、左对齐、悬浮高亮）。"""
        fc: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            hover_bg: str = 'rgba(255,255,255,0.08)'
            pressed_bg: str = 'rgba(255,255,255,0.12)'
        else:
            hover_bg = 'rgba(0,0,0,0.06)'
            pressed_bg = 'rgba(0,0,0,0.10)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 6px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """

    # ================================================================
    #  点击本机 AppID 按钮
    # ================================================================
    def _on_copy_appid(self) -> None:
        """点击本机 AppID 按钮：复制到系统剪切板并短暂显示"已复制"反馈。"""
        QApplication.clipboard().setText(APPID)
        logger.info("[SettingsWindow] 已复制本机 AppID 到剪切板")
        btn: Optional[QPushButton] = self._knotlink_appid_btn
        if btn is not None:
            btn.setText("已复制 ✓")
            QTimer.singleShot(1500, lambda: btn.setText(APPID))

    # ================================================================
    #  点击 KnotLink 规则按钮
    # ================================================================
    def _on_knotlink_item_clicked(self, item: Dict, is_signal: bool) -> None:
        """点击 KnotLink 规则按钮：弹出该规则的详情对话框。"""
        logger.info(
            f"[SettingsWindow] 查看 KnotLink {'信号' if is_signal else '接口'}详情："
            f"{item.get('name')}"
        )
        dialog: KnotLinkDetailDialog = KnotLinkDetailDialog(
            item=item, is_signal=is_signal,
            theme_manager=self._theme, parent=self,
        )
        dialog.exec()

    # ================================================================
    #  创建基础设置页面
    # ================================================================
    def _create_basic_settings_page(self) -> QWidget:
        """
        构建"基础设置"页面。
        ------------------
        目前包含：开机自启动卡片（注册表方式）+ 字体修改卡片 + 语言切换卡片。
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        fc: str = self._theme.font_color

        # ---- 页面主标题 ----
        page_title: QLabel = QLabel("基础设置")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(page_title)

        # ---- 开机自启动卡片 ----
        self._autostart_card = QFrame()
        self._autostart_card.setStyleSheet(self._get_status_card_style())
        self._autostart_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed  # type: ignore
        )
        autostart_card_layout: QVBoxLayout = QVBoxLayout(self._autostart_card)
        autostart_card_layout.setContentsMargins(20, 12, 20, 12)
        autostart_card_layout.setSpacing(4)

        # 顶部：左侧（标题 + 提示） + 右侧（开启/关闭下拉框）
        autostart_top_row: QHBoxLayout = QHBoxLayout()
        autostart_top_row.setSpacing(16)

        autostart_left_col: QVBoxLayout = QVBoxLayout()
        autostart_left_col.setSpacing(6)

        self._autostart_title_label = QLabel("开机自启动")
        self._autostart_title_label.setFont(
            QFont("Microsoft YaHei", 14, QFont.Bold)  # type: ignore
        )
        self._autostart_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        autostart_left_col.addWidget(self._autostart_title_label)

        self._autostart_hint_label = QLabel(
            "开启后，登录 Windows 时自动启动本程序；"
            "该设置通过修改注册表实现，点击「应用修改」后立即生效。"
        )
        autostart_hint_font: QFont = QFont("Microsoft YaHei", 9)
        autostart_hint_font.setItalic(True)
        self._autostart_hint_label.setFont(autostart_hint_font)
        self._autostart_hint_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none; opacity: 0.6;"
        )
        self._autostart_hint_label.setWordWrap(True)
        autostart_left_col.addWidget(self._autostart_hint_label)

        autostart_top_row.addLayout(autostart_left_col, stretch=1)

        # ---- 开启/关闭开关（右侧）----
        self._autostart_switch = ToggleSwitch()
        self._autostart_switch.setChecked(self._applied_autostart)

        autostart_top_row.addWidget(
            self._autostart_switch, 0, Qt.AlignTop  # type: ignore
        )
        autostart_card_layout.addLayout(autostart_top_row)

        layout.addWidget(self._autostart_card)

        # ---- 字体修改卡片 ----
        self._font_card = QFrame()
        self._font_card.setStyleSheet(self._get_status_card_style())
        self._font_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        card_layout: QVBoxLayout = QVBoxLayout(self._font_card)
        card_layout.setContentsMargins(20, 12, 20, 12)
        card_layout.setSpacing(4)

        # 顶部：左侧（标题 + 提示） + 右侧（字体下拉框）
        top_row: QHBoxLayout = QHBoxLayout()
        top_row.setSpacing(16)

        left_col: QVBoxLayout = QVBoxLayout()
        left_col.setSpacing(6)

        self._font_title_label = QLabel("字体修改")
        self._font_title_label.setFont(
            QFont("Microsoft YaHei", 14, QFont.Bold)  # type: ignore
        )
        self._font_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        left_col.addWidget(self._font_title_label)

        self._font_hint_label = QLabel(
            "该字体修改范围仅用于主窗口的科目显示；"
            "选择新的字体后先不应用到系统，"
            "而是在点击「应用修改」后重启以进行修改。"
        )
        hint_font: QFont = QFont("Microsoft YaHei", 9)
        hint_font.setItalic(True)
        self._font_hint_label.setFont(hint_font)
        self._font_hint_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none; opacity: 0.6;"
        )
        self._font_hint_label.setWordWrap(True)
        left_col.addWidget(self._font_hint_label)

        top_row.addLayout(left_col, stretch=1)

        # ---- 字体下拉框（右侧）----
        self._font_combo = QComboBox()
        self._font_combo.setMinimumWidth(260)
        self._font_combo.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._font_combo.setStyleSheet(self._get_font_combo_style())

        # 填充系统可用字体，并选中当前已应用的字体
        families: List[str] = list(QFontDatabase.families())
        if not families:
            families = ['Arial', 'Microsoft YaHei', 'SimSun']
        if self._applied_subject_font not in families:
            families.insert(0, self._applied_subject_font)
        self._font_combo.addItems(families)
        self._font_combo.setCurrentText(self._applied_subject_font)

        top_row.addWidget(self._font_combo, 0, Qt.AlignTop)  # type: ignore
        card_layout.addLayout(top_row)

        # ---- 预览标题（预览标签上一行）----
        self._font_preview_title_label = QLabel("预览")
        self._font_preview_title_label.setFont(
            QFont("Microsoft YaHei", 13, QFont.Bold)  # type: ignore
        )
        self._font_preview_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        card_layout.addWidget(self._font_preview_title_label)

        # ---- 预览标签 ----
        self._font_preview_label = QLabel("AaBbCc 0123456789 语文 · 数学 · 英语")
        self._font_preview_label.setFont(
            QFont(self._applied_subject_font, 16)
        )
        self._font_preview_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self._font_preview_label.setStyleSheet(self._get_font_preview_style())
        self._font_preview_label.setMinimumHeight(36)
        card_layout.addWidget(self._font_preview_label)

        layout.addWidget(self._font_card)

        # ---- 语言切换卡片 ----
        self._language_card = QFrame()
        self._language_card.setStyleSheet(self._get_status_card_style())
        self._language_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        lang_card_layout: QVBoxLayout = QVBoxLayout(self._language_card)
        lang_card_layout.setContentsMargins(20, 12, 20, 12)
        lang_card_layout.setSpacing(4)

        # 顶部：左侧（标题 + 提示） + 右侧（语言下拉框）
        lang_top_row: QHBoxLayout = QHBoxLayout()
        lang_top_row.setSpacing(16)

        lang_left_col: QVBoxLayout = QVBoxLayout()
        lang_left_col.setSpacing(6)

        self._language_title_label = QLabel("语言切换")
        self._language_title_label.setFont(
            QFont("Microsoft YaHei", 14, QFont.Bold)  # type: ignore
        )
        self._language_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        lang_left_col.addWidget(self._language_title_label)

        self._language_hint_label = QLabel(
            "该语言设置仅影响主页面显示科目时使用的语言；"
            "选择新语言后点击「应用修改」重启以生效。"
        )
        lang_hint_font: QFont = QFont("Microsoft YaHei", 9)
        lang_hint_font.setItalic(True)
        self._language_hint_label.setFont(lang_hint_font)
        self._language_hint_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none; opacity: 0.6;"
        )
        self._language_hint_label.setWordWrap(True)
        lang_left_col.addWidget(self._language_hint_label)

        lang_top_row.addLayout(lang_left_col, stretch=1)

        # ---- 语言下拉框（右侧）----
        self._language_combo = QComboBox()
        self._language_combo.setMinimumWidth(260)
        self._language_combo.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._language_combo.setStyleSheet(self._get_font_combo_style())
        self._language_combo.addItem("中文", "Chinese")
        self._language_combo.addItem("英文", "English")

        # 选中当前已应用的语言
        current_lang_idx: int = self._language_combo.findData(self._applied_language)
        if current_lang_idx >= 0:
            self._language_combo.setCurrentIndex(current_lang_idx)

        lang_top_row.addWidget(self._language_combo, 0, Qt.AlignTop)  # type: ignore
        lang_card_layout.addLayout(lang_top_row)

        layout.addWidget(self._language_card)
        layout.addStretch(1)

        # 先设置初始值，再连接信号，避免初始化时触发脏标记
        self._font_combo.currentTextChanged.connect(self._on_font_changed)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._autostart_switch.toggled.connect(self._on_autostart_toggled)

        return page

    # ================================================================
    #  创建美化页面
    # ================================================================
    def _create_beautify_page(self) -> QWidget:
        """
        构建"美化"页面。
        ----------------
        包含两张卡片：
          1. 明暗模式卡片 — 亮色 / 暗色（适用于全部窗口）
          2. 主题色卡片   — 彩色模式开关 + 颜色圆盘选择区
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        fc: str = self._theme.font_color

        # ---- 页面主标题 ----
        page_title: QLabel = QLabel("美化")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(page_title)

        # ================================================================
        #  卡片 1：明暗模式
        # ================================================================
        self._theme_card = QFrame()
        self._theme_card.setStyleSheet(self._get_status_card_style())
        self._theme_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed  # type: ignore
        )
        theme_card_layout: QVBoxLayout = QVBoxLayout(self._theme_card)
        theme_card_layout.setContentsMargins(20, 12, 20, 12)
        theme_card_layout.setSpacing(4)

        theme_top_row: QHBoxLayout = QHBoxLayout()
        theme_top_row.setSpacing(16)

        theme_left_col: QVBoxLayout = QVBoxLayout()
        theme_left_col.setSpacing(6)

        self._theme_title_label = QLabel("明暗模式")
        self._theme_title_label.setFont(
            QFont("Microsoft YaHei", 14, QFont.Bold)  # type: ignore
        )
        self._theme_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        theme_left_col.addWidget(self._theme_title_label)

        self._theme_hint_label = QLabel(
            "亮色与暗色模式适用于全部窗口；"
            "选择后点击「应用修改」重启以生效。"
        )
        theme_hint_font: QFont = QFont("Microsoft YaHei", 9)
        theme_hint_font.setItalic(True)
        self._theme_hint_label.setFont(theme_hint_font)
        self._theme_hint_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none; opacity: 0.6;"
        )
        self._theme_hint_label.setWordWrap(True)
        theme_left_col.addWidget(self._theme_hint_label)

        theme_top_row.addLayout(theme_left_col, stretch=1)

        # ---- 明暗模式下拉框（右侧）----
        self._theme_combo = QComboBox()
        self._theme_combo.setMinimumWidth(260)
        self._theme_combo.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._theme_combo.setStyleSheet(self._get_font_combo_style())
        self._theme_combo.addItem("亮色模式", "lightcolor")
        self._theme_combo.addItem("暗色模式", "darkcolor")

        # 选中当前已应用的主题（彩色模式时回退为亮色）
        combo_theme: str = (
            self._applied_theme
            if self._applied_theme in ('lightcolor', 'darkcolor')
            else 'lightcolor'
        )
        theme_idx: int = self._theme_combo.findData(combo_theme)
        if theme_idx >= 0:
            self._theme_combo.setCurrentIndex(theme_idx)

        theme_top_row.addWidget(self._theme_combo, 0, Qt.AlignTop)  # type: ignore
        theme_card_layout.addLayout(theme_top_row)

        layout.addWidget(self._theme_card)

        # ================================================================
        #  卡片 2：主题色
        # ================================================================
        self._color_card = QFrame()
        self._color_card.setStyleSheet(self._get_status_card_style())
        self._color_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed  # type: ignore
        )
        color_card_layout: QVBoxLayout = QVBoxLayout(self._color_card)
        color_card_layout.setContentsMargins(20, 12, 20, 12)
        color_card_layout.setSpacing(4)

        color_top_row: QHBoxLayout = QHBoxLayout()
        color_top_row.setSpacing(16)

        color_left_col: QVBoxLayout = QVBoxLayout()
        color_left_col.setSpacing(6)

        self._color_title_label = QLabel("主题色")
        self._color_title_label.setFont(
            QFont("Microsoft YaHei", 14, QFont.Bold)  # type: ignore
        )
        self._color_title_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        color_left_col.addWidget(self._color_title_label)

        self._color_hint_label = QLabel(
            "开启后进入彩色模式，主题色仅应用于课表主窗口与置顶时间窗口，"
            "其余窗口保持浅色；在下方圆盘选择颜色后点击「确定」，"
            "再点击「应用修改」重启以生效。"
        )
        color_hint_font: QFont = QFont("Microsoft YaHei", 9)
        color_hint_font.setItalic(True)
        self._color_hint_label.setFont(color_hint_font)
        self._color_hint_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none; opacity: 0.6;"
        )
        self._color_hint_label.setWordWrap(True)
        color_left_col.addWidget(self._color_hint_label)

        color_top_row.addLayout(color_left_col, stretch=1)

        # ---- 彩色模式开关（右侧）----
        self._color_mode_switch = ToggleSwitch()
        self._color_mode_switch.setChecked(self._applied_theme == 'multicolor')
        color_top_row.addWidget(self._color_mode_switch, 0, Qt.AlignTop)  # type: ignore
        color_card_layout.addLayout(color_top_row)

        # ---- 颜色选择区域（开关打开时显示）----
        self._color_picker_area = QWidget()
        self._color_picker_area.setStyleSheet("background: transparent;")
        picker_layout: QHBoxLayout = QHBoxLayout(self._color_picker_area)
        picker_layout.setContentsMargins(0, 12, 0, 0)
        picker_layout.setSpacing(20)

        self._color_wheel = ColorWheel()
        picker_layout.addWidget(self._color_wheel, 0, Qt.AlignLeft)  # type: ignore

        right_col: QVBoxLayout = QVBoxLayout()
        right_col.setSpacing(10)

        # 颜色预览（一个控件同时展示颜色与 RGB 值）
        self._color_preview = QFrame()
        self._color_preview.setMinimumSize(170, 110)
        preview_layout: QVBoxLayout = QVBoxLayout(self._color_preview)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.addStretch()
        self._color_rgb_label = QLabel()
        self._color_rgb_label.setAlignment(Qt.AlignCenter)  # type: ignore
        preview_layout.addWidget(self._color_rgb_label)
        right_col.addWidget(self._color_preview)

        self._color_confirm_btn = QPushButton("确定")
        self._color_confirm_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._color_confirm_btn.setMinimumHeight(34)
        self._color_confirm_btn.setStyleSheet(self._get_confirm_btn_style())
        right_col.addWidget(self._color_confirm_btn)
        right_col.addStretch()

        picker_layout.addLayout(right_col, stretch=1)
        color_card_layout.addWidget(self._color_picker_area)

        layout.addWidget(self._color_card)
        layout.addStretch(1)

        # ---- 初始化颜色与显隐（先设值，后连信号，避免触发脏标记）----
        init_color: QColor = QColor(self._pending_color)
        if not init_color.isValid():
            init_color = QColor('#2196F3')
        self._color_wheel.set_color(init_color)
        self._update_color_preview(init_color)
        self._refresh_color_picker_visibility()

        self._theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        self._color_mode_switch.toggled.connect(self._on_color_mode_toggled)
        self._color_wheel.color_changed.connect(self._on_color_wheel_changed)
        self._color_confirm_btn.clicked.connect(self._on_color_confirm_clicked)

        return page

    # ================================================================
    #  美化页面 — 样式与事件处理
    # ================================================================
    def _get_confirm_btn_style(self) -> str:
        """返回「确定」按钮的 QSS 样式。"""
        return """
            QPushButton {
                color: white;
                background-color: #2196F3;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #42A5F5; }
            QPushButton:pressed { background-color: #1E88E5; }
        """

    def _effective_theme(self) -> str:
        """返回当前 UI 状态下应写入配置的主题名。"""
        # 控件尚未构建（初始化期间）时回退到已应用主题，避免误判脏状态
        if self._color_mode_switch is None or self._theme_combo is None:
            return self._applied_theme
        if self._color_mode_switch.isChecked():
            return 'multicolor'
        return self._theme_combo.currentData() or 'lightcolor'

    def _appearance_is_dirty(self) -> bool:
        """判断外观（主题 / 主题色）是否存在未应用的修改。"""
        if self._theme_combo is None or self._color_mode_switch is None:
            return False
        if self._effective_theme() != self._applied_theme:
            return True
        if self._effective_theme() == 'multicolor':
            return (self._pending_color or '').lower() != (
                self._applied_theme_color or ''
            ).lower()
        return False

    def _on_theme_combo_changed(self, index: int) -> None:
        """明暗模式下拉框变化：刷新「应用修改」按钮状态。"""
        self._refresh_apply_button()

    def _on_color_mode_toggled(self, checked: bool) -> None:
        """彩色模式开关切换：刷新颜色选择区显隐与「应用修改」按钮状态。"""
        self._refresh_color_picker_visibility()
        self._refresh_apply_button()

    def _on_color_wheel_changed(self, color: QColor) -> None:
        """颜色圆盘变化：实时更新预览（不影响已确认的颜色）。"""
        self._update_color_preview(color)

    def _on_color_confirm_clicked(self) -> None:
        """「确定」按钮：把圆盘当前颜色固化为待应用的主题色。"""
        if self._color_wheel is None:
            return
        self._pending_color = self._color_wheel.current_color().name()
        self._update_color_preview(self._color_wheel.current_color())
        self._refresh_apply_button()

    def _refresh_color_picker_visibility(self) -> None:
        """根据彩色模式开关刷新颜色选择区域的显隐。"""
        if self._color_picker_area is not None and self._color_mode_switch is not None:
            self._color_picker_area.setVisible(self._color_mode_switch.isChecked())

    def _update_color_preview(self, color: QColor) -> None:
        """刷新颜色预览控件的背景色与 RGB 文本。"""
        if self._color_preview is None or self._color_rgb_label is None:
            return
        hex_str: str = color.name()
        r, g, b, _a = color.getRgb() # type: ignore
        self._color_preview.setStyleSheet(
            f"QFrame {{"
            f"background-color: {hex_str};"
            f"border: 1px solid rgba(128,128,128,0.35);"
            f"border-radius: 8px;"
            f"}}"
        )
        text_color: str = '#FFFFFF' if is_color_dark(hex_str) else '#000000'
        self._color_rgb_label.setStyleSheet(
            f"color: {text_color}; background: transparent; border: none;"
        )
        self._color_rgb_label.setText(f"RGB({r}, {g}, {b})\n{hex_str}")

    def _get_font_combo_style(self) -> str:
        """返回字体下拉框的 QSS 样式（兼容深/浅色主题）。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = '#2d2d2d'
            border: str = 'rgba(255,255,255,0.14)'
        else:
            bg = '#FFFFFF'
            border = 'rgba(0,0,0,0.14)'

        return f"""
            QComboBox {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 12px;
            }}
            QComboBox:hover, QComboBox:focus {{
                border-color: #2196F3;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                selection-background-color: rgba(33, 150, 243, 0.25);
                selection-color: {fc};
                outline: 0;
            }}
        """

    def _get_font_preview_style(self) -> str:
        """返回字体预览标签的 QSS 样式。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.04)'
            border: str = 'rgba(255,255,255,0.10)'
        else:
            bg = 'rgba(0,0,0,0.03)'
            border = 'rgba(0,0,0,0.10)'

        return f"""
            QLabel {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px 16px;
            }}
        """

    # ================================================================
    #  创建时间表编辑器页面
    # ================================================================
    def _create_timetable_editor_page(self) -> QWidget:
        """
        构建"课表编辑"页面。
        ------------------
        一级标题：
          - 基础（特殊课表规则开关 + 时间表/课程表选择卡片）
          - 时间表（加载/新建按钮、状态标签、条目表格、新加条目按钮）
        """
        page: QWidget = QWidget()
        page.setStyleSheet("background: transparent;")

        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        fc: str = self._theme.font_color

        # ---- 页面主标题 ----
        page_title: QLabel = QLabel("课表编辑")
        page_title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))  # type: ignore
        page_title.setStyleSheet(f"color: {fc}; background: transparent;")
        page_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(page_title)

        # ---- 一级标题：时间表 ----
        section_title: QLabel = QLabel("时间表")
        section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(section_title)

        # ---- 缩进容器（时间表控件统一缩进 28px）----
        tt_indent: QWidget = QWidget()
        tt_indent.setStyleSheet("background: transparent;")
        tt_indent_layout: QVBoxLayout = QVBoxLayout(tt_indent)
        tt_indent_layout.setContentsMargins(28, 0, 0, 0)
        tt_indent_layout.setSpacing(12)

        # ---- 按钮行 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)

        load_btn: QPushButton = QPushButton("加载时间表")
        load_btn.setFont(QFont("Microsoft YaHei", 11))
        load_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        load_btn.setMinimumHeight(36)
        load_btn.clicked.connect(self._on_load_timetable)
        btn_row.addWidget(load_btn)

        new_btn: QPushButton = QPushButton("新建时间表")
        new_btn.setFont(QFont("Microsoft YaHei", 11))
        new_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        new_btn.setMinimumHeight(36)
        new_btn.clicked.connect(self._on_new_timetable)
        btn_row.addWidget(new_btn)

        btn_row.addStretch()

        # 按钮样式
        self._style_timetable_buttons(load_btn, new_btn)

        tt_indent_layout.addLayout(btn_row)

        # ---- 状态标签（卡片式）----
        self._status_card = QFrame()
        self._status_card.setStyleSheet(self._get_status_card_style())
        status_card_layout: QVBoxLayout = QVBoxLayout(self._status_card)
        status_card_layout.setContentsMargins(14, 10, 14, 10)

        self._status_label = QLabel(self._get_status_text())
        self._status_label.setFont(QFont("Microsoft YaHei", 10))
        self._status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        status_card_layout.addWidget(self._status_label)
        tt_indent_layout.addWidget(self._status_card)

        # ---- 条目表格（带外框）----
        self._table_frame = QFrame()
        self._table_frame.setStyleSheet(self._get_table_frame_style())
        table_frame_layout: QVBoxLayout = QVBoxLayout(self._table_frame)
        table_frame_layout.setContentsMargins(1, 1, 1, 1)

        self._timetable_table = QTableWidget()
        self._timetable_table.setColumnCount(4)
        self._timetable_table.setHorizontalHeaderLabels(
            ["序号", "类型", "开始时间", "结束时间"]
        )
        self._timetable_table.setSelectionBehavior(QAbstractItemView.SelectRows)  # type: ignore
        self._timetable_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # type: ignore
        self._timetable_table.setAlternatingRowColors(True)
        self._timetable_table.setShowGrid(False)
        self._timetable_table.horizontalHeader().setStretchLastSection(True)
        self._timetable_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch  # type: ignore
        )
        self._timetable_table.verticalHeader().setVisible(False)
        self._timetable_table.cellDoubleClicked.connect(self._on_entry_double_clicked)
        self._style_table()

        table_frame_layout.addWidget(self._timetable_table)
        tt_indent_layout.addWidget(self._table_frame)

        # ---- 新加条目按钮（实色强调）----
        add_btn: QPushButton = QPushButton("＋ 新加条目")
        add_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        add_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        add_btn.setMinimumHeight(38)
        add_btn.clicked.connect(self._on_add_entry)
        add_btn.setStyleSheet(self._get_add_btn_style())
        tt_indent_layout.addWidget(add_btn)

        # 将"时间表"缩进容器添加到主布局（无 stretch，高度自适应条目数量）
        layout.addWidget(tt_indent)

        # ════════════════════════════════════════════════════════════
        #  课程表
        # ════════════════════════════════════════════════════════════
        # ---- 分割线 ----
        cv_sep_line: QFrame = QFrame()
        cv_sep_line.setFrameShape(QFrame.HLine)  # type: ignore
        cv_sep_line.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        layout.addWidget(cv_sep_line)
        layout.addSpacing(4)

        # ---- 一级标题：课程表 ----
        cv_section_title: QLabel = QLabel("课程表")
        cv_section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        cv_section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        cv_section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(cv_section_title)

        # ---- 缩进容器（课程表控件统一缩进 28px）----
        cv_indent: QWidget = QWidget()
        cv_indent.setStyleSheet("background: transparent;")
        cv_indent_layout: QVBoxLayout = QVBoxLayout(cv_indent)
        cv_indent_layout.setContentsMargins(28, 0, 0, 0)
        cv_indent_layout.setSpacing(12)

        # ---- 按钮行 ----
        cv_btn_row: QHBoxLayout = QHBoxLayout()
        cv_btn_row.setSpacing(12)

        cv_load_btn: QPushButton = QPushButton("加载课程表")
        cv_load_btn.setFont(QFont("Microsoft YaHei", 11))
        cv_load_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cv_load_btn.setMinimumHeight(36)
        cv_load_btn.clicked.connect(self._on_load_curriculum)
        cv_btn_row.addWidget(cv_load_btn)

        cv_new_btn: QPushButton = QPushButton("新建课程表")
        cv_new_btn.setFont(QFont("Microsoft YaHei", 11))
        cv_new_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cv_new_btn.setMinimumHeight(36)
        cv_new_btn.clicked.connect(self._on_new_curriculum)
        cv_btn_row.addWidget(cv_new_btn)

        cv_btn_row.addStretch()

        # 按钮样式（与时间表按钮相同）
        self._style_timetable_buttons(cv_load_btn, cv_new_btn)

        cv_indent_layout.addLayout(cv_btn_row)

        # ---- 状态标签（卡片式）----
        self._curriculum_status_card = QFrame()
        self._curriculum_status_card.setStyleSheet(self._get_status_card_style())
        cv_status_card_layout: QVBoxLayout = QVBoxLayout(self._curriculum_status_card)
        cv_status_card_layout.setContentsMargins(14, 10, 14, 10)

        self._curriculum_status_label = QLabel(self._get_curriculum_status_text())
        self._curriculum_status_label.setFont(QFont("Microsoft YaHei", 10))
        self._curriculum_status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        cv_status_card_layout.addWidget(self._curriculum_status_label)
        cv_indent_layout.addWidget(self._curriculum_status_card)

        # ---- 课程表表格（带外框）----
        self._curriculum_table_frame = QFrame()
        self._curriculum_table_frame.setStyleSheet(self._get_table_frame_style())
        cv_table_frame_layout: QVBoxLayout = QVBoxLayout(self._curriculum_table_frame)
        cv_table_frame_layout.setContentsMargins(1, 1, 1, 1)

        self._curriculum_table = QTableWidget()
        # 8 列：行标签 + 周一～周日
        self._curriculum_table.setColumnCount(8)
        self._curriculum_table.setHorizontalHeaderLabels(
            ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        )
        self._curriculum_table.setSelectionBehavior(QAbstractItemView.SelectItems)  # type: ignore
        self._curriculum_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # type: ignore
        self._curriculum_table.setAlternatingRowColors(True)
        self._curriculum_table.setShowGrid(True)
        self._curriculum_table.horizontalHeader().setStretchLastSection(True)
        self._curriculum_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch  # type: ignore
        )
        self._curriculum_table.verticalHeader().setVisible(False)
        self._curriculum_table.cellClicked.connect(self._on_curriculum_cell_clicked)
        self._style_curriculum_table()

        cv_table_frame_layout.addWidget(self._curriculum_table)
        cv_indent_layout.addWidget(self._curriculum_table_frame)

        # ---- 课程表内联编辑器卡片（初始隐藏，点击单元格后显示）----
        self._cv_editor_card = self._build_curriculum_editor_card()
        self._cv_editor_card.setVisible(False)
        cv_indent_layout.addWidget(self._cv_editor_card)

        # 将"课程表"缩进容器添加到主布局
        layout.addWidget(cv_indent)

        # ════════════════════════════════════════════════════════════
        #  显示规则
        # ════════════════════════════════════════════════════════════
        # ---- 分割线 ----
        dr_sep_line: QFrame = QFrame()
        dr_sep_line.setFrameShape(QFrame.HLine)  # type: ignore
        dr_sep_line.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        layout.addWidget(dr_sep_line)
        layout.addSpacing(4)

        # ---- 一级标题：显示规则 ----
        dr_section_title: QLabel = QLabel("显示规则")
        dr_section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        dr_section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        dr_section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(dr_section_title)

        # ---- 缩进容器（显示规则控件统一缩进 28px）----
        dr_indent: QWidget = QWidget()
        dr_indent.setStyleSheet("background: transparent;")
        dr_indent_layout: QVBoxLayout = QVBoxLayout(dr_indent)
        dr_indent_layout.setContentsMargins(28, 0, 0, 0)
        dr_indent_layout.setSpacing(12)

        # ---- 按钮行 ----
        dr_btn_row: QHBoxLayout = QHBoxLayout()
        dr_btn_row.setSpacing(12)

        self._rule_add_btn = QPushButton("新建规则")
        self._rule_add_btn.setFont(QFont("Microsoft YaHei", 11))
        self._rule_add_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._rule_add_btn.setMinimumHeight(36)
        self._rule_add_btn.setStyleSheet(self._get_add_btn_style())
        self._rule_add_btn.clicked.connect(self._on_add_rule)
        dr_btn_row.addWidget(self._rule_add_btn)

        dr_btn_row.addStretch()

        dr_indent_layout.addLayout(dr_btn_row)

        # ---- 规则列表（上下键调序 + 点击编辑）----
        self._rule_list = DisplayRuleListWidget(self._theme)
        self._rule_list.setMinimumHeight(120)
        dr_indent_layout.addWidget(self._rule_list)

        # ---- 提示（斜体小字）----
        dr_hint: QLabel = QLabel(
            "提示：从上到下优先级依次降低；点击规则可编辑，"
            "使用规则左侧的上下键调整优先级。"
        )
        dr_hint_font: QFont = QFont("Microsoft YaHei", 9)
        dr_hint_font.setItalic(True)
        dr_hint.setFont(dr_hint_font)
        dr_hint.setStyleSheet(
            f"color: {fc}; background: transparent; opacity: 0.6;"
        )
        dr_hint.setWordWrap(True)
        dr_indent_layout.addWidget(dr_hint)

        layout.addWidget(dr_indent)

        # ════════════════════════════════════════════════════════════
        #  科目编辑
        # ════════════════════════════════════════════════════════════
        # ---- 分割线 ----
        sj_sep_line: QFrame = QFrame()
        sj_sep_line.setFrameShape(QFrame.HLine)  # type: ignore
        sj_sep_line.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        layout.addWidget(sj_sep_line)
        layout.addSpacing(4)

        # ---- 一级标题：科目编辑 ----
        sj_section_title: QLabel = QLabel("科目编辑")
        sj_section_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))  # type: ignore
        sj_section_title.setStyleSheet(f"color: {fc}; background: transparent;")
        sj_section_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        layout.addWidget(sj_section_title)

        # ---- 缩进容器（科目编辑控件统一缩进 28px）----
        sj_indent: QWidget = QWidget()
        sj_indent.setStyleSheet("background: transparent;")
        sj_indent_layout: QVBoxLayout = QVBoxLayout(sj_indent)
        sj_indent_layout.setContentsMargins(28, 0, 0, 0)
        sj_indent_layout.setSpacing(12)

        # ---- 科目按钮卡片（参照快捷编辑窗口左侧科目按钮区）----
        self._subject_card = QFrame()
        self._subject_card.setStyleSheet(self._get_status_card_style())
        sj_card_layout: QVBoxLayout = QVBoxLayout(self._subject_card)
        sj_card_layout.setContentsMargins(12, 10, 12, 10)

        # 科目按钮直接放在普通容器中（不使用内部 QScrollArea）：
        # 卡片高度时刻等于内容高度，所有科目按钮完整显示、下方无多余空白；
        # 内容超出页面时由页面外层滚动区统一滚动，不会压缩卡片高度。
        sj_subjects_widget: QWidget = QWidget()
        sj_subjects_widget.setStyleSheet("background: transparent;")
        self._subject_scroll_layout = QVBoxLayout(sj_subjects_widget)
        self._subject_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._subject_scroll_layout.setSpacing(6)

        sj_card_layout.addWidget(sj_subjects_widget)
        sj_indent_layout.addWidget(self._subject_card)

        # ---- 新建科目 / 新建类别按钮行 ----
        sj_btn_row: QHBoxLayout = QHBoxLayout()
        sj_btn_row.setSpacing(12)

        new_subject_btn: QPushButton = QPushButton("＋ 新建科目")
        new_subject_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        new_subject_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        new_subject_btn.setMinimumHeight(38)
        new_subject_btn.setStyleSheet(self._get_add_btn_style())
        new_subject_btn.clicked.connect(self._on_new_subject)
        sj_btn_row.addWidget(new_subject_btn)

        new_category_btn: QPushButton = QPushButton("＋ 新建类别")
        new_category_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        new_category_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        new_category_btn.setMinimumHeight(38)
        new_category_btn.setStyleSheet(self._get_add_btn_style())
        new_category_btn.clicked.connect(self._on_new_category)
        sj_btn_row.addWidget(new_category_btn)

        sj_btn_row.addStretch()
        sj_indent_layout.addLayout(sj_btn_row)

        # ---- 提示（斜体小字）----
        sj_hint: QLabel = QLabel(
            "提示：第一类别为系统保护类别，不能新建科目到其中，"
            "其中的科目也不能移动到其他类别；"
            "未输入科目英文名时可使用窗口内的翻译功能自动翻译。"
        )
        sj_hint_font: QFont = QFont("Microsoft YaHei", 9)
        sj_hint_font.setItalic(True)
        sj_hint.setFont(sj_hint_font)
        sj_hint.setStyleSheet(
            f"color: {fc}; background: transparent; opacity: 0.6;"
        )
        sj_hint.setWordWrap(True)
        sj_indent_layout.addWidget(sj_hint)

        layout.addWidget(sj_indent)

        # 初始加载科目配置并渲染科目按钮
        self._load_subject_config_data()
        self._refresh_subject_buttons()

        # 初始加载数据
        self._refresh_table()

        # ---- 将 page 包裹在 QScrollArea 中，防止表格被压缩 ----
        scroll: QScrollArea = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)

        # 启用鼠标拖拽滑动（手指/鼠标按住后拖动即可滚动）
        QScroller.grabGesture(
            scroll.viewport(),
            QScroller.LeftMouseButtonGesture  # type: ignore
        )

        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(128, 128, 128, 0.5);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore

        return scroll

    # ================================================================
    #  状态文本
    # ================================================================
    def _get_status_text(self) -> str:
        """生成当前状态标签文字。"""
        if self._schedule_data is None:
            return "状态：未加载数据"
        path: str = self._editing_timetable_path or self._schedule_data.timetable_path
        fname: str = os.path.basename(path) if path else "未知"
        count: int = (
            len(self._editing_timetable_data)
            if self._editing_timetable_data
            else len(self._schedule_data.timetable_data)
        )
        prefix: str = "[编辑中] " if self._has_unsaved_changes else ""
        return f"{prefix}状态：已加载 {fname}（共 {count} 条）"

    # ================================================================
    #  编辑副本管理
    # ================================================================
    def _init_editing_copies(self) -> None:
        """从共享数据管理器深拷贝数据到编辑副本。"""
        if self._schedule_data is not None:
            self._editing_timetable_data = copy.deepcopy(
                self._schedule_data.timetable_data
            )
            self._editing_curriculum_data = copy.deepcopy(
                self._schedule_data.curriculum_data
            )
            self._editing_timetable_path = self._schedule_data.timetable_path
            self._editing_curriculum_path = self._schedule_data.curriculum_path
            self._has_unsaved_changes = False
            self._refresh_apply_button()
            logger.info("编辑副本已从共享数据初始化")
        else:
            self._editing_timetable_data = {}
            self._editing_curriculum_data = {}
            self._editing_timetable_path = ''
            self._editing_curriculum_path = ''
            self._has_unsaved_changes = False

    def _font_is_dirty(self) -> bool:
        """判断字体下拉框的当前选择是否与已应用字体不同。"""
        if self._font_combo is None:
            return False
        return self._font_combo.currentText() != self._applied_subject_font

    def _language_is_dirty(self) -> bool:
        """判断语言下拉框的当前选择是否与已应用语言不同。"""
        if self._language_combo is None:
            return False
        return self._language_combo.currentData() != self._applied_language

    def _autostart_is_dirty(self) -> bool:
        """判断自启动开关的当前状态是否与已应用状态不同。"""
        if self._autostart_switch is None:
            return False
        return self._autostart_switch.isChecked() != self._applied_autostart

    def _on_font_changed(self, font_name: str) -> None:
        """字体下拉框选择变化：更新预览，并刷新「应用修改」按钮状态。"""
        if not font_name:
            return
        if self._font_preview_label is not None:
            self._font_preview_label.setFont(QFont(font_name, 16))
        self._refresh_apply_button()

    def _on_language_changed(self, index: int) -> None:
        """语言下拉框选择变化：刷新「应用修改」按钮状态。"""
        self._refresh_apply_button()

    def _on_autostart_toggled(self, checked: bool) -> None:
        """自启动开关状态变化：刷新「应用修改」按钮状态。"""
        self._refresh_apply_button()

    def _refresh_apply_button(self) -> None:
        """根据是否有未应用修改，刷新「应用修改」按钮的状态和样式。

        该按钮位于左侧导航栏底部、退出按钮下方：
          - 无未应用修改时：灰色禁用态（不可点击）
          - 有未应用修改时：绿色实色背景（可点击应用）
        """
        if not hasattr(self, '_apply_btn') or self._apply_btn is None:
            return

        enabled: bool = (
            self._has_unsaved_changes
            or self._font_is_dirty()
            or self._language_is_dirty()
            or self._autostart_is_dirty()
            or self._appearance_is_dirty()
        )
        self._apply_btn.setEnabled(enabled)

        if self._theme.theme == 'darkcolor':
            apply_primary: str = '#4CAF50'
            apply_hover: str = '#66BB6A'
            disabled_bg: str = 'rgba(255,255,255,0.05)'
            disabled_fg: str = 'rgba(255,255,255,0.25)'
        else:
            apply_primary = '#43A047'
            apply_hover = '#66BB6A'
            disabled_bg = 'rgba(0,0,0,0.04)'
            disabled_fg = 'rgba(0,0,0,0.25)'

        if enabled:
            self._apply_btn.setStyleSheet(f"""
                QPushButton {{
                    color: white; background-color: {apply_primary};
                    border: none; border-radius: 6px;
                    padding: 10px 14px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {apply_hover};
                }}
            """)
        else:
            self._apply_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {disabled_fg}; background-color: {disabled_bg};
                    border: none; border-radius: 6px;
                    padding: 10px 14px;
                    text-align: left;
                }}
            """)

    # ================================================================
    #  直接保存编辑副本到本地文件（不入缓存）
    # ================================================================
    def _save_editing_timetable_file(self) -> bool:
        """将时间表编辑副本直接写入其对应文件。"""
        if not self._editing_timetable_path:
            return False
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        path: str = os.path.join(script_dir, self._editing_timetable_path)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._editing_timetable_data, f,
                          ensure_ascii=False, indent=4)
            logger.info(f"时间表已直接保存至文件：{self._editing_timetable_path}")
            return True
        except Exception as e:
            logger.error(f"保存时间表文件失败：{e}")
            return False

    def _save_editing_curriculum_file(self) -> bool:
        """将课程表编辑副本直接写入其对应文件。"""
        if not self._editing_curriculum_path:
            return False
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        path: str = os.path.join(script_dir, self._editing_curriculum_path)

        # 按星期顺序排列键（Monday → Sunday），与 ScheduleDataManager 保持一致
        day_order: List[str] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                                'Friday', 'Saturday', 'Sunday']
        ordered_data: Dict = {}
        for day in day_order:
            if day in self._editing_curriculum_data:
                ordered_data[day] = self._editing_curriculum_data[day]
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(ordered_data, f, ensure_ascii=False, indent=4)
            logger.info(f"课程表已直接保存至文件：{self._editing_curriculum_path}")
            return True
        except Exception as e:
            logger.error(f"保存课程表文件失败：{e}")
            return False

    def _persist_active_paths(self) -> None:
        """把当前编辑的时间表/课程表路径写回 schedule_config.ini（重启后仍生效）。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        ini_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')
        if not os.path.exists(ini_path):
            logger.warning(f"配置文件不存在，无法写回路径：{ini_path}")
            return
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                lines: List[str] = f.readlines()

            updated: Dict[str, bool] = {'table': False, 'timetable': False}
            out: List[str] = []
            for line in lines:
                stripped: str = line.lstrip()
                if stripped.startswith(';') or stripped.startswith('#'):
                    out.append(line)
                    continue
                if '=' in line:
                    key: str = line.split('=', 1)[0].strip()
                    if key == 'table' and not updated['table'] \
                            and self._editing_curriculum_path:
                        out.append(f"table = {self._editing_curriculum_path}\n")
                        updated['table'] = True
                        continue
                    if key == 'timetable' and not updated['timetable'] \
                            and self._editing_timetable_path:
                        out.append(f"timetable = {self._editing_timetable_path}\n")
                        updated['timetable'] = True
                        continue
                out.append(line)

            if not updated['table'] and self._editing_curriculum_path:
                out.append(f"table = {self._editing_curriculum_path}\n")
            if not updated['timetable'] and self._editing_timetable_path:
                out.append(f"timetable = {self._editing_timetable_path}\n")

            with open(ini_path, 'w', encoding='utf-8') as f:
                f.writelines(out)
            logger.info(
                f"已将活动路径写回 schedule_config.ini："
                f"table={self._editing_curriculum_path}, "
                f"timetable={self._editing_timetable_path}"
            )
        except Exception as e:
            logger.error(f"写回 schedule_config.ini 失败：{e}")

    def _persist_subject_font(self) -> None:
        """把当前选中的科目显示字体写回 schedule_config.ini（重启后生效）。"""
        if self._font_combo is None:
            return
        font_name: str = self._font_combo.currentText().strip()
        if not font_name:
            return

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        ini_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')
        if not os.path.exists(ini_path):
            logger.warning(f"配置文件不存在，无法写回字体：{ini_path}")
            return
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                lines: List[str] = f.readlines()

            updated: bool = False
            out: List[str] = []
            for line in lines:
                stripped: str = line.lstrip()
                if stripped.startswith(';') or stripped.startswith('#'):
                    out.append(line)
                    continue
                if '=' in line:
                    key: str = line.split('=', 1)[0].strip()
                    if key == 'subject_font' and not updated:
                        out.append(f"subject_font = {font_name}\n")
                        updated = True
                        continue
                out.append(line)

            if not updated:
                out.append(f"subject_font = {font_name}\n")

            with open(ini_path, 'w', encoding='utf-8') as f:
                f.writelines(out)
            logger.info(f"已把科目显示字体写回 schedule_config.ini：{font_name}")
        except Exception as e:
            logger.error(f"写回 schedule_config.ini 字体失败：{e}")

    def _persist_language(self) -> None:
        """把当前选中的科目显示语言写回 schedule_config.ini（重启后生效）。"""
        if self._language_combo is None:
            return
        lang_value = self._language_combo.currentData()
        if not lang_value:
            return

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        ini_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')
        if not os.path.exists(ini_path):
            logger.warning(f"配置文件不存在，无法写回语言：{ini_path}")
            return
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                lines: List[str] = f.readlines()

            updated: bool = False
            out: List[str] = []
            for line in lines:
                stripped: str = line.lstrip()
                if stripped.startswith(';') or stripped.startswith('#'):
                    out.append(line)
                    continue
                if '=' in line:
                    key: str = line.split('=', 1)[0].strip()
                    if key == 'language' and not updated:
                        out.append(f"language = {lang_value}\n")
                        updated = True
                        continue
                out.append(line)

            if not updated:
                out.append(f"language = {lang_value}\n")

            with open(ini_path, 'w', encoding='utf-8') as f:
                f.writelines(out)
            logger.info(f"已把科目显示语言写回 schedule_config.ini：{lang_value}")
        except Exception as e:
            logger.error(f"写回 schedule_config.ini 语言失败：{e}")

    def _persist_appearance(self) -> None:
        """把当前主题（theme）与主题色（theme_color）写回 schedule_config.ini。"""
        theme_value: str = self._effective_theme()
        color_value: str = (self._pending_color or '#2196f3').lower()

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        ini_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')
        if not os.path.exists(ini_path):
            logger.warning(f"配置文件不存在，无法写回外观设置：{ini_path}")
            return
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                lines: List[str] = f.readlines()

            updated: Dict[str, bool] = {'theme': False, 'theme_color': False}
            out: List[str] = []
            for line in lines:
                stripped: str = line.lstrip()
                if stripped.startswith(';') or stripped.startswith('#'):
                    out.append(line)
                    continue
                if '=' in line:
                    key: str = line.split('=', 1)[0].strip()
                    if key == 'theme' and not updated['theme']:
                        out.append(f"theme = {theme_value}\n")
                        updated['theme'] = True
                        continue
                    if key == 'theme_color' and not updated['theme_color']:
                        out.append(f"theme_color = {color_value}\n")
                        updated['theme_color'] = True
                        continue
                out.append(line)

            if not updated['theme']:
                out.append(f"theme = {theme_value}\n")
            if not updated['theme_color']:
                out.append(f"theme_color = {color_value}\n")

            with open(ini_path, 'w', encoding='utf-8') as f:
                f.writelines(out)
            logger.info(
                f"已把外观设置写回 schedule_config.ini："
                f"theme={theme_value}, theme_color={color_value}"
            )
        except Exception as e:
            logger.error(f"写回 schedule_config.ini 外观设置失败：{e}")

    # ================================================================
    #  开机自启动（注册表）
    # ================================================================
    def _build_autostart_command(self) -> str:
        """
        构造写入注册表的自启动启动命令。
        ---------------------------------
        已打包（PyInstaller）时直接使用当前可执行文件；
        源码运行时使用「python 解释器 + main.py」组合，
        与 _restart_app 的启动方式保持一致。
        """
        if getattr(sys, 'frozen', False):
            return f'"{sys.executable}"'
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        main_script: str = os.path.join(script_dir, 'main.py')
        return f'"{sys.executable}" "{main_script}"'

    def _is_autostart_enabled(self) -> bool:
        """查询注册表 Run 键，判断开机自启动是否已开启。"""
        if sys.platform != 'win32':
            logger.warning("非 Windows 平台，跳过开机自启动查询")
            return False
        try:
            import winreg  # noqa: PLC0415
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_REG_KEY
            ) as key:
                value, _ = winreg.QueryValueEx(key, _AUTOSTART_VALUE_NAME)
            return bool(value)
        except OSError:
            return False

    def _set_autostart_enabled(self, enabled: bool) -> bool:
        """
        写入或删除注册表 Run 键下的自启动项。
        -------------------------------------
        参数：
            enabled（bool）：True 写入启动命令，False 删除自启动项

        返回值：
            bool：操作是否成功
        """
        if sys.platform != 'win32':
            logger.warning("非 Windows 平台，无法修改开机自启动")
            return False
        try:
            import winreg  # noqa: PLC0415
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_REG_KEY,
                0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, _AUTOSTART_VALUE_NAME, 0,
                        winreg.REG_SZ, self._build_autostart_command()
                    )
                else:
                    try:
                        winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)
                    except FileNotFoundError:
                        pass  # 值不存在视为已删除
            logger.info(
                f"开机自启动已{'开启' if enabled else '关闭'}："
                f"{_AUTOSTART_VALUE_NAME} @ HKCU\\{_AUTOSTART_REG_KEY}"
            )
            return True
        except OSError as e:
            logger.error(f"修改注册表开机自启动失败：{e}")
            return False

    def _persist_autostart(self) -> None:
        """把当前选中的开机自启动状态写入注册表（立即生效）。"""
        if self._autostart_switch is None:
            return
        enabled: bool = self._autostart_switch.isChecked()
        if enabled == self._applied_autostart:
            return
        if self._set_autostart_enabled(enabled):
            self._applied_autostart = enabled
            logger.info(f"开机自启动状态已更新：{'开启' if enabled else '关闭'}")

    def _restart_app(self) -> None:
        """重启软件：启动新进程并退出当前程序。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        main_script: str = os.path.join(script_dir, 'main.py')
        try:
            subprocess.Popen([sys.executable, main_script], cwd=script_dir)
            logger.info(f"已启动新进程：{sys.executable} {main_script}")
        except Exception as e:
            logger.error(f"启动新进程失败：{e}")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_apply_changes(self) -> None:
        """应用修改：持久化字体/课表修改、同步共享数据并重启软件。"""
        # 1. 持久化字体设置（若已选择新字体）
        self._persist_subject_font()
        if self._font_combo is not None:
            self._applied_subject_font = self._font_combo.currentText()

        # 1b. 持久化语言设置（若已选择新语言）
        self._persist_language()
        if self._language_combo is not None:
            self._applied_language = self._language_combo.currentData()

        # 1c. 持久化开机自启动设置（若已修改，立即写入注册表）
        self._persist_autostart()

        # 1d. 持久化外观设置（主题 / 主题色，重启后生效）
        self._persist_appearance()
        self._applied_theme = self._effective_theme()
        self._applied_theme_color = self._pending_color

        if self._schedule_data is None:
            # 仅字体等不依赖 schedule_data 的修改：直接重启生效
            self._has_unsaved_changes = False
            self._refresh_apply_button()
            logger.info("应用修改：重启软件以立即生效")
            self._restart_app()
            return

        # 2. 将编辑副本直接写入本地文件
        self._save_editing_timetable_file()
        self._save_editing_curriculum_file()

        # 3. 同步共享数据管理器（内存），使重启前程序状态保持一致
        if self._editing_timetable_path:
            self._schedule_data.timetable_data = copy.deepcopy(
                self._editing_timetable_data
            )
            self._schedule_data.timetable_path = self._editing_timetable_path
        if self._editing_curriculum_path:
            self._schedule_data.curriculum_data = copy.deepcopy(
                self._editing_curriculum_data
            )
            self._schedule_data.curriculum_path = self._editing_curriculum_path

        # 4. 写回 INI 活动路径（重启后使用）
        self._persist_active_paths()

        # 5. 重置未应用标志并刷新
        self._has_unsaved_changes = False
        self._refresh_apply_button()
        self._refresh_status_label()
        self._refresh_curriculum_status()

        # 6. 通知主窗口重建课时标签（重启前内存已一致）
        self.changes_applied.emit()

        # 7. 重启软件以立即生效
        logger.info("应用修改：重启软件以立即生效")
        self._restart_app()

    def _on_postpone_changes(self) -> None:
        """暂不应用：把修改直接保存到本地文件，当前运行程序不受影响（下次启动生效）。"""
        # 1. 持久化字体设置（若已选择新字体）
        self._persist_subject_font()
        if self._font_combo is not None:
            self._applied_subject_font = self._font_combo.currentText()

        # 1b. 持久化语言设置（若已选择新语言）
        self._persist_language()
        if self._language_combo is not None:
            self._applied_language = self._language_combo.currentData()

        # 1c. 持久化开机自启动设置（若已修改，立即写入注册表）
        self._persist_autostart()

        # 1d. 持久化外观设置（主题 / 主题色，下次启动生效）
        self._persist_appearance()
        self._applied_theme = self._effective_theme()
        self._applied_theme_color = self._pending_color

        # 2. 将编辑副本直接写入本地文件
        self._save_editing_timetable_file()
        self._save_editing_curriculum_file()

        # 3. 写回 INI 活动路径（下次启动使用新选择的文件）
        self._persist_active_paths()

        # 4. 重置未应用标志并刷新
        self._has_unsaved_changes = False
        self._refresh_apply_button()
        self._refresh_status_label()
        self._refresh_curriculum_status()

        logger.info("已暂不应用：修改已保存到本地文件，当前程序不受影响")

    # ================================================================
    #  显示规则事件处理
    # ================================================================
    def _on_add_rule(self) -> None:
        """新建一条显示规则。"""
        if self._rule_list is not None:
            self._rule_list.add_rule_dialog()

    # ================================================================
    #  事件系统 — 数据加载与渲染
    # ================================================================
    def _load_event_rules(self) -> None:
        """从 event_rules.json 加载事件规则到工作副本。"""
        self._event_rules = self._event_manager.load_rules()

    def _clear_event_layout(self) -> None:
        """清空事件卡片内全部旧按钮，避免残留孤儿控件。"""
        if self._event_scroll_layout is None:
            return
        while self._event_scroll_layout.count():
            item = self._event_scroll_layout.takeAt(0)
            w = item.widget()  # type: ignore
            if w is not None:
                w.deleteLater()
        self._event_buttons.clear()

    def _get_event_rule_btn_style(self) -> str:
        """返回事件规则按钮的 QSS 样式（与 KnotLink 规则按钮一致：无边框、悬浮高亮）。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.03)'
            hover_bg: str = 'rgba(255,255,255,0.08)'
            pressed_bg: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.02)'
            hover_bg = 'rgba(0,0,0,0.06)'
            pressed_bg = 'rgba(0,0,0,0.10)'
        return f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """

    def _refresh_event_rules(self) -> None:
        """按当前事件规则重建规则按钮列表。"""
        if self._event_scroll_layout is None:
            return
        self._clear_event_layout()

        btn_style: str = self._get_event_rule_btn_style()
        dim_color: str = (
            'rgba(255,255,255,0.50)' if self._theme.theme == 'darkcolor'
            else 'rgba(0,0,0,0.50)'
        )

        if not self._event_rules:
            empty: QLabel = QLabel("这里还没有事件规则")
            f: QFont = QFont("Microsoft YaHei", 10)
            f.setItalic(True)
            empty.setFont(f)
            empty.setStyleSheet(
                f"color: {dim_color}; background: transparent;"
            )
            empty.setAlignment(Qt.AlignCenter)  # type: ignore
            self._event_scroll_layout.addStretch()
            self._event_scroll_layout.addWidget(empty)
            self._event_scroll_layout.addStretch()
            return

        for index, rule in enumerate(self._event_rules):
            summary: str = _event_rule_summary(rule)
            time_str: str = str(rule.get('time', '') or '')
            name: str = str(rule.get('name', '') or '')
            btn: QPushButton = QPushButton(
                f"{summary}  ·  {time_str}  ·  {name}"
            )
            btn.setFont(QFont("Microsoft YaHei", 11))
            btn.setCursor(Qt.PointingHandCursor)  # type: ignore
            btn.setMinimumHeight(36)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(
                lambda checked=False, i=index: self._on_event_rule_clicked(i)
            )
            self._event_buttons.append(btn)
            self._event_scroll_layout.addWidget(btn)

        self._event_scroll_layout.addStretch()

    # ================================================================
    #  事件系统 — 事件处理
    # ================================================================
    def _on_new_event(self) -> None:
        """点击「新建事件」→ 打开事件规则子窗口（新建模式）。"""
        dialog: EventRuleDialog = EventRuleDialog(
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            result: dict = dialog.result()
            self._event_manager.add_rule(result)
            self._load_event_rules()
            self._refresh_event_rules()
            logger.info(
                f"已新建事件：{_event_rule_summary(result)} "
                f"{result['time']} '{result['name']}'"
            )

    def _on_event_rule_clicked(self, index: int) -> None:
        """点击事件规则按钮 → 打开事件规则子窗口（编辑模式）。"""
        if not (0 <= index < len(self._event_rules)):
            return
        rule: Dict = self._event_rules[index]
        dialog: EventRuleDialog = EventRuleDialog(
            theme_manager=self._theme,
            rule=rule,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            if dialog.deleted():
                self._event_manager.delete_rule(index)
            else:
                result: dict = dialog.result()
                self._event_manager.update_rule(index, result)
            self._load_event_rules()
            self._refresh_event_rules()

    def _refresh_status_label(self) -> None:
        """刷新时间表状态标签文字。"""
        if self._status_label is not None:
            self._status_label.setText(self._get_status_text())

    # ================================================================
    #  科目编辑 — 数据加载与渲染
    # ================================================================
    def _load_subject_config_data(self) -> None:
        """从 subject_config.json 加载科目配置到工作副本。"""
        self._subject_config_data = self._subject_config_manager.load()

    def _clear_subject_layout(self) -> None:
        """
        清空科目卡片内全部旧控件（含每行科目按钮），避免残留孤儿控件。
        ------------------------------------------------------------
        之前的清空只删除顶层 QLabel，行内按钮随 QHBoxLayout 被移出后
        仍作为内容容器的子控件残留，导致重建后按钮堆积、显示异常。
        """
        while self._subject_scroll_layout.count(): # type: ignore
            item = self._subject_scroll_layout.takeAt(0) # type: ignore
            w = item.widget()  # type: ignore
            if w is not None:
                w.deleteLater()
                continue
            row = item.layout()  # type: ignore
            if row is not None:
                while row.count():
                    ritem = row.takeAt(0)
                    rw = ritem.widget()  # type: ignore
                    if rw is not None:
                        rw.deleteLater()
        self._subject_buttons.clear()

    def _refresh_subject_buttons(self) -> None:
        """按类别重建科目按钮（参照快捷编辑窗口左侧科目按钮区）。"""
        if self._subject_scroll_layout is None:
            return
        # 清空旧按钮（含行内按钮，避免残留孤儿控件）
        self._clear_subject_layout()

        data: Dict = self._subject_config_data or {}
        subject_types: Any = data.get('Subject_Types', {})
        if not isinstance(subject_types, dict):
            subject_types = {}

        btn_style: str = self._get_cv_subject_btn_style()
        dim_color: str = (
            'rgba(255,255,255,0.50)' if self._theme.theme == 'darkcolor'
            else 'rgba(0,0,0,0.50)'
        )

        for cat_name, subjects in subject_types.items():
            # 类别标题（所有类别都显示，包括 "None" 占位类别）
            cat_title: QLabel = QLabel(f"—— {cat_name} ——")
            cat_title.setFont(QFont("Microsoft YaHei", 10))
            cat_title.setStyleSheet(
                f"color: {dim_color}; background: transparent;"
            )
            self._subject_scroll_layout.addWidget(cat_title)

            # "None" 占位类别：仅显示类别名，不显示科目内容
            if not isinstance(subjects, list):
                continue

            # 科目按钮流式布局（每行 4 个，自动补齐空位）
            buttons_per_row: int = 4
            current_row: Optional[QHBoxLayout] = None
            placed: int = 0
            for entry in subjects:
                name, english = parse_subject_entry(entry)
                if not name:
                    continue
                if placed % buttons_per_row == 0:
                    current_row = QHBoxLayout()
                    current_row.setSpacing(6)
                    current_row.setContentsMargins(0, 0, 0, 0)
                    self._subject_scroll_layout.addLayout(current_row)
                assert current_row is not None
                btn: QPushButton = QPushButton(name)
                btn.setFont(QFont("Microsoft YaHei", 11))
                btn.setCursor(Qt.PointingHandCursor)  # type: ignore
                btn.setMinimumHeight(32)
                btn.setMinimumWidth(44)
                btn.setToolTip(
                    f"英文名：{english}" if english else "英文名：（未设置）"
                )
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(
                    lambda checked=False, c=cat_name, n=name:
                        self._on_subject_clicked(c, n)
                )
                self._subject_buttons.append(btn)
                current_row.addWidget(btn, stretch=1)
                placed += 1

            if current_row is not None:
                remaining: int = placed % buttons_per_row
                if remaining > 0:
                    for _ in range(buttons_per_row - remaining):
                        spacer: QWidget = QWidget()
                        spacer.setStyleSheet("background: transparent;")
                        current_row.addWidget(spacer, stretch=1)

        # 卡片高度由 Qt 布局按内容自动撑开（外层页面滚动区负责溢出滚动），
        # 无需手动测量或固定高度，避免重建后控件重叠、类别标题被裁切。
        self._subject_scroll_layout.addStretch()

    # ================================================================
    #  科目编辑 — 事件处理
    # ================================================================
    def _on_subject_clicked(self, category: str, name: str) -> None:
        """点击科目按钮 → 打开科目编辑子窗口（编辑模式）。"""
        found = self._subject_config_manager.find_subject(
            self._subject_config_data, name
        )
        english: str = found[1] if found is not None else ''

        dialog: SubjectEditDialog = SubjectEditDialog(
            theme_manager=self._theme,
            manager=self._subject_config_manager,
            mode='edit',
            category=category,
            name=name,
            english_name=english,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            if dialog.deleted():
                self._delete_subject(category, name)
            else:
                result: dict = dialog.result()
                self._apply_subject_change(category, name, result)

    def _delete_subject(self, category: str, name: str) -> None:
        """从科目配置中删除指定科目（第一类别科目由子窗口禁用删除入口）。"""
        subject_types: Any = self._subject_config_data.get(
            'Subject_Types', {}
        )
        if not isinstance(subject_types, dict):
            return
        old_list: Any = subject_types.get(category)
        if not isinstance(old_list, list):
            return
        # 防御：第一类别（系统保护类别）不允许删除
        all_cats: List[str] = list(subject_types.keys())
        protected: str = all_cats[0] if all_cats else ''
        if category == protected:
            logger.warning(f"第一类别为系统保护类别，禁止删除科目：{name}")
            return
        old_list[:] = [
            e for e in old_list
            if parse_subject_entry(e)[0] != name
        ]
        self._save_subject_config()
        self._replace_deleted_subject_in_curriculum(name)
        self._remove_subject_swap_records(name)
        self._refresh_subject_buttons()
        logger.info(f"已删除科目：{name}（{category}）")

    def _remove_subject_swap_records(self, deleted_name: str) -> None:
        """
        删除科目后，移除换课记录（Config/swap_schedule.json）中
        所有涉及该科目的记录（old_subject 或 new_subject 匹配即删除）。
        """
        if not deleted_name:
            return
        removed: int = SwapManager().remove_subject_swaps(deleted_name)
        if removed:
            logger.info(
                f"删除科目「{deleted_name}」后，已移除 "
                f"{removed} 条相关换课记录"
            )

    def _replace_deleted_subject_in_curriculum(self, deleted_name: str) -> None:
        """
        删除科目后，将课程表中所有出现该科目的位置替换为「语文」。
        ---------------------------------------------------------
        同步更新三处数据（不触发主窗口重建，主窗口保持当前显示不变，
        重启后自然显示替换结果）：
          1. Config/curriculum/ 下所有课程表 JSON 文件（直接落盘）；
          2. 设置页的课程表编辑副本（_editing_curriculum_data）并刷新表格显示；
          3. 主窗口共享的 ScheduleDataManager.curriculum_data。
        """
        replacement: str = '语文'
        if not deleted_name:
            return
        changed_files: List[str] = []

        # 1) 所有课程表 JSON 文件
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        for fname in ScheduleDataManager.get_curriculum_files():
            path: str = os.path.join(script_dir, 'Config', 'curriculum', fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data: Any = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"课程表文件读取失败，跳过：{fname}（{e}）")
                continue
            if not isinstance(data, dict):
                continue
            if _replace_subject_in_curriculum_dict(data, deleted_name, replacement):
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    changed_files.append(fname)
                except OSError as e:
                    logger.error(f"课程表文件写入失败：{fname}（{e}）")

        # 2) 设置页课程表编辑副本 + 刷新显示
        if isinstance(self._editing_curriculum_data, dict):
            if _replace_subject_in_curriculum_dict(
                    self._editing_curriculum_data, deleted_name, replacement):
                self._refresh_curriculum_table()

        # 3) 主窗口共享数据（仅内存，供后续重建/重启使用，不主动触发重建）
        if self._schedule_data is not None:
            _replace_subject_in_curriculum_dict(
                self._schedule_data.curriculum_data,
                deleted_name, replacement,
            )

        if changed_files:
            logger.info(
                f"删除科目「{deleted_name}」后，课程表文件中已替换为"
                f"「{replacement}」：{changed_files}"
            )

    def _on_new_subject(self) -> None:
        """点击「新建科目」→ 打开科目编辑子窗口（新建模式）。"""
        dialog: SubjectEditDialog = SubjectEditDialog(
            theme_manager=self._theme,
            manager=self._subject_config_manager,
            mode='create',
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            result = dialog.result()
            subject_types = self._subject_config_data.setdefault(
                'Subject_Types', {}
            )
            cat: str = result['category']
            # 防御：目标类别必须是列表类别；
            # "None" 占位类别首次加入科目时转为列表（占位符仅为占位）
            if cat in subject_types and \
                    not isinstance(subject_types[cat], list):
                if SubjectConfigManager.is_placeholder(subject_types[cat]):
                    subject_types[cat] = []
                else:
                    logger.warning(f"无法加入科目到非列表类别：{cat}")
                    return
            if cat not in subject_types:
                subject_types[cat] = []
            subject_types[cat].append({
                'name': result['name'],
                'english_name': result['english_name'],
            })
            self._save_subject_config()
            self._refresh_subject_buttons()
            logger.info(
                f"已新建科目：{result['name']} → {cat}（英文名："
                f"{result['english_name'] or '未设置'}）"
            )

    def _on_new_category(self) -> None:
        """点击「新建类别」→ 打开新建类别子窗口。"""
        dialog: NewCategoryDialog = NewCategoryDialog(
            theme_manager=self._theme,
            existing=self._subject_config_manager.category_names(
                self._subject_config_data
            ),
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            cat: str = dialog.result_name()
            subject_types = self._subject_config_data.setdefault(
                'Subject_Types', {}
            )
            if cat not in subject_types:
                subject_types[cat] = []
                self._save_subject_config()
                self._refresh_subject_buttons()
                logger.info(f"已新建类别：{cat}")

    def _apply_subject_change(self, old_category: str, old_name: str,
                              result: dict) -> None:
        """把科目编辑结果写回工作副本（同类别更新 / 跨类别移动）。"""
        subject_types: Any = self._subject_config_data.get(
            'Subject_Types', {}
        )
        if not isinstance(subject_types, dict):
            return
        old_list: Any = subject_types.get(old_category)
        if not isinstance(old_list, list):
            return

        target_cat: str = result['category']
        new_entry: Dict = {
            'name': result['name'],
            'english_name': result['english_name'],
        }

        if target_cat == old_category:
            # 同类别内更新
            for i, entry in enumerate(old_list):
                ename, _e = parse_subject_entry(entry)
                if ename == old_name:
                    old_list[i] = new_entry
                    break
        else:
            # 移动到其他类别（旧类别中移除，新类别中追加）
            # 防御：目标类别必须是列表类别；
            # "None" 占位类别首次移入科目时转为列表（占位符仅为占位）
            if target_cat in subject_types and \
                    not isinstance(subject_types[target_cat], list):
                if SubjectConfigManager.is_placeholder(
                        subject_types[target_cat]):
                    subject_types[target_cat] = []
                else:
                    logger.warning(f"无法移动科目到非列表类别：{target_cat}")
                    return
            old_list[:] = [
                e for e in old_list
                if parse_subject_entry(e)[0] != old_name
            ]
            new_list: Any = subject_types.get(target_cat)
            if not isinstance(new_list, list):
                subject_types[target_cat] = new_list = []
            new_list.append(new_entry)

        self._save_subject_config()
        self._refresh_subject_buttons()
        logger.info(
            f"科目已更新：{old_name}（{old_category}）→ "
            f"{result['name']}（{target_cat}，英文名："
            f"{result['english_name'] or '未设置'}）"
        )

    def _save_subject_config(self) -> bool:
        """保存科目配置：写文件、同步内存主题配置、刷新关联控件。"""
        if not self._subject_config_manager.save(self._subject_config_data):
            return False
        # 同步内存中的主题科目配置（快捷编辑窗口下次打开即生效）
        self._theme.subject_config = copy.deepcopy(self._subject_config_data)
        # 使课程表内联编辑器的科目缓存失效，重新加载后重建按钮
        self._cv_subject_categories = {}
        self._load_cv_subject_categories()
        self._rebuild_cv_subject_buttons()
        # 进入"有未应用修改"状态（与页面内其他编辑策略一致）
        self._has_unsaved_changes = True
        self._refresh_apply_button()
        logger.info("科目配置已保存并同步内存")
        return True

    # ================================================================
    #  刷新表格
    # ================================================================
    def _refresh_table(self) -> None:
        """根据当前 schedule_data 刷新表格内容。"""
        if self._timetable_table is None:
            return

        self._timetable_table.setRowCount(0)

        if self._schedule_data is None:
            if self._status_label:
                self._status_label.setText(self._get_status_text())
            # 仍需刷新课程表（清空显示）
            self._refresh_curriculum_table()
            return

        data: Dict = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else self._schedule_data.timetable_data
        )
        row: int = 0

        for key, value in data.items():
            self._timetable_table.insertRow(row)

            if key.startswith('lesson_'):
                # 课时条目
                lesson_num: str = key.replace('lesson_', '')
                start_time: str = '—'
                end_time: str = '—'
                if isinstance(value, list) and len(value) >= 2:
                    start_time = self._fmt_time(value[0])
                    end_time = self._fmt_time(value[1])

                self._set_table_row(row, lesson_num, '课时', start_time, end_time, key)
            elif key.startswith('dividerline_'):
                # 分隔线条目
                self._set_table_row(row, '—', '分隔线', '—', '—', key)

            row += 1

        if self._status_label:
            self._status_label.setText(self._get_status_text())

        # 根据实际行高和表头高度精确计算表格高度，自适应内容不留空白
        row_count: int = self._timetable_table.rowCount()
        # 表头高度
        h_header: int = self._timetable_table.horizontalHeader().height()
        # 所有数据行高度（逐行累加，适配不同 DPI / 字体下的实际行高）
        h_rows: int = 0
        for r in range(row_count):
            h_rows += self._timetable_table.rowHeight(r)
        # 表格外框宽度（上下边框各 frameWidth px）
        h_frame: int = self._timetable_table.frameWidth() * 2
        exact_h: int = h_header + h_rows + h_frame
        self._timetable_table.setFixedHeight(exact_h)

        # 同步刷新课程表表格（其行结构依赖时间表数据）
        self._refresh_curriculum_table()

    def _set_table_row(self, row: int, seq: str, etype: str,
                       start: str, end: str, key: str) -> None:
        """填充表格的一行数据。"""
        items = [
            (seq, seq),
            (etype, etype),
            (start, start),
            (end, end),
        ]
        fc: str = self._theme.font_color

        for col, (text, _data) in enumerate(items):
            item: QTableWidgetItem = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)  # type: ignore
            item.setForeground(QColor(fc))  # type: ignore
            # 在第一列存储 key 用于编辑时检索
            if col == 0:
                item.setData(Qt.UserRole, key)  # type: ignore
            self._timetable_table.setItem(row, col, item)  # type: ignore

    @staticmethod
    def _fmt_time(time_str: str) -> str:
        """将 '8:00:00' 格式化为 '08:00'。"""
        parts: list = time_str.split(':')
        if len(parts) >= 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return time_str

    # ================================================================
    #  状态卡片样式
    # ================================================================
    def _get_status_card_style(self) -> str:
        """返回状态标签卡片的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.04)'
            card_border: str = 'rgba(255,255,255,0.08)'
        else:
            card_bg = 'rgba(0,0,0,0.03)'
            card_border = 'rgba(0,0,0,0.06)'

        return f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
            }}
        """

    # ================================================================
    #  表格外框样式
    # ================================================================
    def _get_table_frame_style(self) -> str:
        """返回表格外框的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            frame_border: str = 'rgba(255,255,255,0.10)'
        else:
            frame_border = 'rgba(0,0,0,0.10)'

        return f"""
            QFrame {{
                background: transparent;
                border: 1px solid {frame_border};
                border-radius: 8px;
            }}
        """

    # ================================================================
    #  表格样式
    # ================================================================
    def _style_table(self) -> None:
        """根据主题刷新表格样式。"""
        fc: str = self._theme.font_color
        bc: str = self._theme.root_back_color

        if self._theme.theme == 'darkcolor':
            header_bg: str = '#2d2d2d'
            alt_bg: str = '#252525'
            sel_bg: str = 'rgba(255,255,255,0.08)'
            hover_bg: str = 'rgba(255,255,255,0.04)'
        else:
            header_bg = '#f5f5f5'
            alt_bg = '#fafafa'
            sel_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.02)'

        assert self._timetable_table is not None
        # type: ignore  # pyright: ignore[reportOptionalMemberAccess]
        self._timetable_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bc};
                color: {fc};
                border: none;
                border-radius: 7px;
            }}
            QTableWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid transparent;
            }}
            QTableWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTableWidget::item:selected {{
                background-color: {sel_bg};
                color: {fc};
            }}
            QTableWidget::item:alternate {{
                background-color: {alt_bg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {fc};
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 10px 12px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    # ================================================================
    #  按钮样式
    # ================================================================
    def _style_timetable_buttons(self, load_btn: QPushButton,
                                  new_btn: QPushButton) -> None:
        """刷新时间表操作按钮样式。"""
        fc: str = self._theme.font_color
        border: str = self._theme.border_color

        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.04)'
            hover_bg: str = 'rgba(255,255,255,0.08)'
            pressed_bg: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.03)'
            hover_bg = 'rgba(0,0,0,0.06)'
            pressed_bg = 'rgba(0,0,0,0.10)'

        style: str = f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 18px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """
        load_btn.setStyleSheet(style)
        new_btn.setStyleSheet(style)

    def _get_add_btn_style(self) -> str:
        """返回新加条目按钮的样式（实色强调）。"""
        fc: str = self._theme.font_color

        if self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.12)'
            pressed_bg: str = 'rgba(255,255,255,0.16)'
            border: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
            pressed_bg = 'rgba(0,0,0,0.12)'
            border = 'rgba(0,0,0,0.12)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-color: {self._theme.border_color};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """

    # ================================================================
    #  事件：加载时间表
    # ================================================================
    def _on_load_timetable(self) -> None:
        """打开文件对话框选择 JSON 文件加载为当前时间表。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        start_dir: str = os.path.join(script_dir, 'Config', 'timetable')

        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载时间表", start_dir,
            "JSON 文件 (*.json);;所有文件 (*)"
        )

        if not file_path:
            return

        # 计算相对路径
        try:
            rel_path: str = os.path.relpath(file_path, script_dir)
        except ValueError:
            rel_path = file_path

        logger.info(f"加载时间表：{rel_path}")

        # 直接读取文件到编辑副本，不影响共享数据
        try:
            load_path: str = os.path.join(script_dir, rel_path)
            with open(load_path, 'r', encoding='utf-8') as f:
                self._editing_timetable_data = json.load(f)
            self._editing_timetable_path = rel_path
            self._has_unsaved_changes = True
            self._refresh_table()
            self._refresh_status_label()
            self._refresh_apply_button()
            logger.info(f"时间表已加载至编辑副本：{rel_path}")
        except Exception as e:
            logger.error(f"加载时间表到编辑副本失败：{e}")

    # ================================================================
    #  事件：新建时间表
    # ================================================================
    def _on_new_timetable(self) -> None:
        """弹出新建时间表对话框。"""
        dialog: NewTimetableDialog = NewTimetableDialog(
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            new_name: str = dialog.result_name()
            copy_from: str = dialog.result_copy_from()
            self._create_new_timetable_file(new_name, copy_from)

    def _create_new_timetable_file(self, name: str, copy_from: str) -> None:
        """创建新的时间表 JSON 文件并加载。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        timetable_dir: str = os.path.join(script_dir, 'Config', 'timetable')
        os.makedirs(timetable_dir, exist_ok=True)

        new_path: str = os.path.join(timetable_dir, name)

        if copy_from:
            # 从已有文件复制
            src_path: str = os.path.join(timetable_dir, copy_from)
            try:
                with open(src_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"复制时间表模板失败：{e}")
                data = {"lesson_1": ["8:00:00", "8:40:00"]}
        else:
            # 空白模板（默认第一节课 7:00–7:40）
            data = {"lesson_1": ["7:00:00", "7:40:00"]}

        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"创建时间表文件失败：{e}")
            return

        logger.info(f"已创建新时间表：{name}（模板={'复制 ' + copy_from if copy_from else '空白'}）")

        # 加载新文件到编辑副本
        rel_path: str = f"Config/timetable/{name}"
        try:
            with open(new_path, 'r', encoding='utf-8') as f:
                self._editing_timetable_data = json.load(f)
            self._editing_timetable_path = rel_path
            self._has_unsaved_changes = True
            self._refresh_table()
            self._refresh_status_label()
            self._refresh_apply_button()
        except Exception as e:
            logger.error(f"加载新时间表到编辑副本失败：{e}")

    # ================================================================
    #  事件：双击条目 → 编辑
    # ================================================================
    def _on_entry_double_clicked(self, row: int, _col: int) -> None:
        """双击表格行，打开编辑对话框。"""
        item: Optional[QTableWidgetItem] = self._timetable_table.item(row, 0) # type: ignore
        if item is None:
            return

        key: str = item.data(Qt.UserRole)  # type: ignore
        data: Dict = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else self._schedule_data.timetable_data  # type: ignore
        )

        if key not in data:
            return

        is_lesson: bool = key.startswith('lesson_')
        start_time: str = '08:00'
        end_time: str = '08:40'

        if is_lesson:
            val = data[key]
            if isinstance(val, list) and len(val) >= 2:
                start_time = self._fmt_time(val[0])
                end_time = self._fmt_time(val[1])

        dialog: TimetableEntryDialog = TimetableEntryDialog(
            entry_type='lesson' if is_lesson else 'dividerline',
            start_time=start_time,
            end_time=end_time,
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            result: dict = dialog.result()
            if result['type'] == 'lesson':
                # 保存为 HH:MM:SS 格式
                data[key] = [
                    f"{result['start_time']}:00",
                    f"{result['end_time']}:00",
                ]
            else:
                data[key] = "-"

            self._has_unsaved_changes = True
            self._save_editing_timetable_file()
            self._refresh_table()
            self._refresh_status_label()
            self._refresh_apply_button()

    # ================================================================
    #  事件：新加条目
    # ================================================================
    def _calculate_default_times(self) -> tuple:
        """根据上一节课的结束时间计算新条目的默认起止时间。

        规则：
          - 开始时间 = 上一节课结束时间 + 10 分钟
          - 结束时间 = 开始时间 + 40 分钟
          - 若无现有课时，默认 7:00–7:40
        """
        data: Dict = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else self._schedule_data.timetable_data  # type: ignore
        )
        last_end_minutes: Optional[int] = None
        for key in data:
            if key.startswith('lesson_'):
                val = data[key]
                if isinstance(val, list) and len(val) >= 2:
                    try:
                        parts = val[1].split(':')
                        h, m = int(parts[0]), int(parts[1])
                        end_mins = h * 60 + m
                        if last_end_minutes is None or end_mins > last_end_minutes:
                            last_end_minutes = end_mins
                    except (ValueError, IndexError):
                        pass

        if last_end_minutes is None:
            # 无现有课时，默认 7:00–7:40
            return '07:00', '07:40'

        # 开始时间 = 最后结束时间 + 10 分钟
        start_mins: int = last_end_minutes + 10
        start_h: int = (start_mins // 60) % 24
        start_m: int = start_mins % 60

        # 结束时间 = 开始时间 + 40 分钟
        end_mins: int = start_mins + 40
        end_h: int = (end_mins // 60) % 24
        end_m: int = end_mins % 60

        return f"{start_h:02d}:{start_m:02d}", f"{end_h:02d}:{end_m:02d}"

    def _on_add_entry(self) -> None:
        """弹出条目编辑器添加新条目（非模态，可连续添加）。"""
        # 若已有打开的添加对话框，激活它
        if self._add_dialog is not None and self._add_dialog.isVisible():
            self._add_dialog.raise_()
            self._add_dialog.activateWindow()
            return

        # 根据上一节课计算默认时间
        start_time, end_time = self._calculate_default_times()

        dialog: TimetableEntryDialog = TimetableEntryDialog(
            entry_type='lesson',
            start_time=start_time,
            end_time=end_time,
            theme_manager=self._theme,
            parent=self,
            stay_open=True,
        )
        dialog.entry_confirmed.connect(self._on_entry_confirmed)
        self._add_dialog = dialog
        dialog.show()

    def _on_entry_confirmed(self, etype: str,
                            start_time: str, end_time: str) -> None:
        """处理新建条目对话框的确认信号（不关闭对话框）。"""
        data: Dict = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else self._schedule_data.timetable_data  # type: ignore
        )

        if etype == 'lesson':
            lesson_nums: List[int] = []
            for k in data:
                if k.startswith('lesson_'):
                    try:
                        lesson_nums.append(int(k.replace('lesson_', '')))
                    except ValueError:
                        pass
            next_num: int = max(lesson_nums) + 1 if lesson_nums else 1
            new_key: str = f"lesson_{next_num}"
            data[new_key] = [
                f"{start_time}:00",
                f"{end_time}:00",
            ]
        else:
            div_nums: List[int] = []
            for k in data:
                if k.startswith('dividerline_'):
                    try:
                        div_nums.append(int(k.replace('dividerline_', '')))
                    except ValueError:
                        pass
            next_num = max(div_nums) + 1 if div_nums else 1
            new_key = f"dividerline_{next_num}"
            data[new_key] = "-"

        self._has_unsaved_changes = True
        self._save_editing_timetable_file()
        self._refresh_table()
        self._refresh_status_label()
        self._refresh_apply_button()

        # 计算下一次默认时间（结束时间 + 10 分钟开始，+ 40 分钟结束）
        next_start_time, next_end_time = self._calculate_default_times()

        # 在对话框中显示结果
        lesson_label: str = (
            f"第{next_num}节课" if etype == 'lesson'
            else f"分隔线{next_num}"
        )
        if self._add_dialog is not None:
            self._add_dialog.show_result(
                lesson_label, start_time, end_time,
                next_start_time, next_end_time,
            )

    # ================================================================
    #  课程表 — 状态文本
    # ================================================================
    def _get_curriculum_status_text(self) -> str:
        """生成课程表状态标签文字。"""
        if self._schedule_data is None:
            return "状态：未加载数据"
        path: str = self._editing_curriculum_path or self._schedule_data.curriculum_path
        fname: str = os.path.basename(path) if path else "未知"
        # 统计总科目数（所有天的非空科目之和）
        src = (
            self._editing_curriculum_data
            if self._editing_curriculum_data
            else self._schedule_data.curriculum_data
        )
        total_subjects: int = 0
        for day_data in src.values():
            if isinstance(day_data, dict):
                total_subjects += len([
                    v for v in day_data.values()
                    if v and isinstance(v, str) and v.strip()
                ])
        prefix: str = "[编辑中] " if self._has_unsaved_changes else ""
        return f"{prefix}状态：已加载 {fname}（共 {total_subjects} 个科目设置）"

    # ================================================================
    #  课程表 — 刷新表格
    # ================================================================
    def _refresh_curriculum_table(self) -> None:
        """根据 timetable_data 和 curriculum_data 刷新课程表表格。"""
        if self._curriculum_table is None:
            return

        self._curriculum_table.setRowCount(0)

        if self._schedule_data is None:
            if self._curriculum_status_label:
                self._curriculum_status_label.setText(
                    self._get_curriculum_status_text()
                )
            return

        timetable: Dict = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else self._schedule_data.timetable_data
        )
        curriculum: Dict = (
            self._editing_curriculum_data
            if self._editing_curriculum_data
            else self._schedule_data.curriculum_data
        )
        day_names: List[str] = [
            'Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday'
        ]
        fc: str = self._theme.font_color

        row: int = 0
        for key, value in timetable.items():
            self._curriculum_table.insertRow(row)

            if key.startswith('lesson_'):
                # 课时行：第1列为标签，其余7列显示科目
                lesson_num: str = key.replace('lesson_', '')
                # 构建时间范围字符串
                time_str: str = ''
                if isinstance(value, list) and len(value) >= 2:
                    time_str = (
                        f"{self._fmt_time(value[0])}–"
                        f"{self._fmt_time(value[1])}"
                    )
                label_text: str = f"第{lesson_num}节\n{time_str}"

                label_item: QTableWidgetItem = QTableWidgetItem(label_text)
                label_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                label_item.setForeground(QColor(fc))  # type: ignore
                label_item.setData(Qt.UserRole, key)  # type: ignore
                self._curriculum_table.setItem(row, 0, label_item)  # type: ignore

                # 填充每一天的科目
                for day_idx, day_name in enumerate(day_names):
                    day_data: Dict = curriculum.get(day_name, {})
                    subject: str = day_data.get(key, '')
                    cell_text: str = subject if subject else '—'

                    cell_item: QTableWidgetItem = QTableWidgetItem(cell_text)
                    cell_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                    if subject and subject.strip():
                        cell_item.setForeground(QColor(fc))  # type: ignore
                    else:
                        # 空科目用半透明颜色显示 "—"
                        cell_item.setForeground(  # type: ignore
                            QColor(255, 255, 255, 64)
                            if self._theme.theme == 'darkcolor'
                            else QColor(0, 0, 0, 64)
                        )
                    # 存储 (day_name, lesson_key) 用于点击编辑
                    cell_item.setData(
                        Qt.UserRole,  # type: ignore
                        {'day': day_name, 'lesson': key}
                    )
                    self._curriculum_table.setItem(  # type: ignore
                        row, day_idx + 1, cell_item
                    )

            elif key.startswith('dividerline_'):
                # 分隔线行：合并为一整行
                divider_item: QTableWidgetItem = QTableWidgetItem(
                    "————— 分隔线 —————"
                )
                divider_item.setTextAlignment(Qt.AlignCenter)  # type: ignore
                # 暗色模式下使用浅色文字，保证分隔线字样清晰可读
                divider_item.setForeground(  # type: ignore
                    QColor(255, 255, 255, 179)
                    if self._theme.theme == 'darkcolor'
                    else QColor(0, 0, 0, 77)
                )
                divider_item.setData(Qt.UserRole, '__divider__')  # type: ignore
                self._curriculum_table.setItem(row, 0, divider_item)  # type: ignore
                # 其余列留空（透明占位）
                for col in range(1, 8):
                    empty_item: QTableWidgetItem = QTableWidgetItem('')
                    empty_item.setFlags(Qt.NoItemFlags)  # type: ignore
                    self._curriculum_table.setItem(row, col, empty_item)  # type: ignore
                # 合并该行所有列
                self._curriculum_table.setSpan(row, 0, 1, 8)

            row += 1

        if self._curriculum_status_label:
            self._curriculum_status_label.setText(
                self._get_curriculum_status_text()
            )

        # 自适应行高
        row_count: int = self._curriculum_table.rowCount()
        h_header: int = self._curriculum_table.horizontalHeader().height()
        h_rows: int = 0
        for r in range(row_count):
            h_rows += self._curriculum_table.rowHeight(r)
        h_frame: int = self._curriculum_table.frameWidth() * 2
        exact_h: int = h_header + h_rows + h_frame + 50  # +50 for two-line labels
        self._curriculum_table.setMinimumHeight(exact_h)

    # ================================================================
    #  课程表 — 单元格点击 → 启动内联编辑器
    # ================================================================
    def _on_curriculum_cell_clicked(self, row: int, col: int) -> None:
        """点击课程表单元格，启动光标闪烁并显示内联编辑器卡片。"""
        if self._curriculum_table is None:
            return
        # 忽略行标签列（col 0）和分隔线行
        if col == 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is None:
            return
        cell_data = item.data(Qt.UserRole)  # type: ignore
        if not isinstance(cell_data, dict):
            return

        day_name: str = cell_data['day']
        lesson_key: str = cell_data['lesson']

        # 如果已有编辑器在运行，先停止旧光标
        self._stop_cv_blink()

        # 深拷贝当前课程表数据作为待编辑副本（优先使用编辑副本）
        if self._editing_curriculum_data:
            self._pending_curriculum_data = copy.deepcopy(
                self._editing_curriculum_data
            )
        elif self._schedule_data is not None:
            self._pending_curriculum_data = copy.deepcopy(
                self._schedule_data.curriculum_data
            )

        # 记录光标位置
        self._cv_cursor_row = row
        self._cv_cursor_col = col
        self._cv_cursor_day = day_name
        self._cv_cursor_lesson = lesson_key

        # 显示编辑器卡片
        if self._cv_editor_card is not None:
            self._cv_editor_card.setVisible(True)

        # 启动闪烁光标
        self._start_cv_blink()

        # 刷新编辑器状态和高亮
        self._refresh_cv_editor_status()

    # ================================================================
    #  课程表内联编辑器 — 构建卡片
    # ================================================================
    def _build_curriculum_editor_card(self) -> QFrame:
        """构建课程表内联编辑器卡片控件（左7右3布局，参照快捷编辑窗口）。"""
        fc: str = self._theme.font_color

        card: QFrame = QFrame()
        card.setStyleSheet(self._get_cv_card_style())
        card_layout: QVBoxLayout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        # ════════════════════════════════════════════════════════
        #  状态区（消息气泡样式，横跨整个卡片顶部）
        # ════════════════════════════════════════════════════════
        # 状态标签背景色（消息气泡质感）
        if self._theme.theme == 'darkcolor':
            bubble_bg: str = 'rgba(255,255,255,0.06)'
            bubble_border: str = 'rgba(255,255,255,0.10)'
        else:
            bubble_bg = 'rgba(0,0,0,0.04)'
            bubble_border = 'rgba(0,0,0,0.08)'

        status_bubble: QFrame = QFrame()
        status_bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {bubble_bg};
                border: 1px solid {bubble_border};
                border-radius: 10px;
            }}
        """)
        bubble_layout: QVBoxLayout = QVBoxLayout(status_bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)

        self._cv_status_label = QLabel("")
        self._cv_status_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))  # type: ignore
        self._cv_status_label.setStyleSheet(
            f"color: {fc}; background: transparent; border: none;"
        )
        self._cv_status_label.setWordWrap(True)
        bubble_layout.addWidget(self._cv_status_label)

        card_layout.addWidget(status_bubble)

        # ════════════════════════════════════════════════════════
        #  主体区域：左7（科目按钮）+ 竖分割线 + 右3（方向键 + 操作按钮）
        # ════════════════════════════════════════════════════════
        body_row: QHBoxLayout = QHBoxLayout()
        body_row.setSpacing(0)

        # ---- 左侧：科目按钮区（滚动区域，占 70%）----
        self._load_cv_subject_categories()

        subjects_scroll: QScrollArea = QScrollArea()
        subjects_scroll.setWidgetResizable(True)
        subjects_scroll.setMaximumHeight(200)
        subjects_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 0.3);
                border-radius: 3px;
                min-height: 20px;
            }
        """)

        subjects_widget: QWidget = QWidget()
        subjects_widget.setStyleSheet("background: transparent;")
        self._cv_subject_layout = QVBoxLayout(subjects_widget)
        self._cv_subject_layout.setContentsMargins(0, 0, 0, 0)
        self._cv_subject_layout.setSpacing(6)

        self._populate_cv_subject_buttons()

        subjects_scroll.setWidget(subjects_widget)
        body_row.addWidget(subjects_scroll, stretch=7)

        # ---- 竖分割线（区分科目区与操作区）----
        v_sep: QFrame = QFrame()
        v_sep.setFrameShape(QFrame.VLine)  # type: ignore
        v_sep.setStyleSheet(f"""
            border: none;
            border-left: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        body_row.addWidget(v_sep)
        body_row.addSpacing(12)

        # ---- 右侧：操作区（占 30%）----
        right_panel: QWidget = QWidget()
        right_panel.setStyleSheet("background: transparent;")
        right_layout: QVBoxLayout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        nav_style: str = self._get_cv_nav_btn_style()

        # -- D-Pad 方向键（紧凑布局）--
        dpad: QWidget = QWidget()
        dpad.setStyleSheet("background: transparent;")
        dpad_layout: QVBoxLayout = QVBoxLayout(dpad)
        dpad_layout.setContentsMargins(0, 0, 0, 0)
        dpad_layout.setSpacing(4)

        nav_btn_w: int = 120

        # 上
        btn_up: QPushButton = QPushButton("▲ 上一节")
        btn_up.setFont(QFont("Microsoft YaHei", 10))
        btn_up.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_up.setMinimumHeight(36)
        btn_up.setFixedWidth(nav_btn_w)
        btn_up.setStyleSheet(nav_style)
        btn_up.clicked.connect(lambda: self._on_cv_navigate('up'))
        dpad_layout.addWidget(btn_up, alignment=Qt.AlignCenter)  # type: ignore

        # 左 右（紧挨在一起）
        lr_row: QHBoxLayout = QHBoxLayout()
        lr_row.setSpacing(0)
        lr_row.setAlignment(Qt.AlignCenter)  # type: ignore

        btn_left: QPushButton = QPushButton("◀ 前一天")
        btn_left.setFont(QFont("Microsoft YaHei", 10))
        btn_left.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_left.setMinimumHeight(36)
        btn_left.setFixedWidth(nav_btn_w)
        btn_left.setStyleSheet(nav_style)
        btn_left.clicked.connect(lambda: self._on_cv_navigate('left'))
        lr_row.addWidget(btn_left)

        btn_right: QPushButton = QPushButton("后一天 ▶")
        btn_right.setFont(QFont("Microsoft YaHei", 10))
        btn_right.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_right.setMinimumHeight(36)
        btn_right.setFixedWidth(nav_btn_w)
        btn_right.setStyleSheet(nav_style)
        btn_right.clicked.connect(lambda: self._on_cv_navigate('right'))
        lr_row.addWidget(btn_right)

        dpad_layout.addLayout(lr_row)

        # 下
        btn_down: QPushButton = QPushButton("▼ 下一节")
        btn_down.setFont(QFont("Microsoft YaHei", 10))
        btn_down.setCursor(Qt.PointingHandCursor)  # type: ignore
        btn_down.setMinimumHeight(36)
        btn_down.setFixedWidth(nav_btn_w)
        btn_down.setStyleSheet(nav_style)
        btn_down.clicked.connect(lambda: self._on_cv_navigate('down'))
        dpad_layout.addWidget(btn_down, alignment=Qt.AlignCenter)  # type: ignore

        right_layout.addWidget(dpad)

        # 分割线
        sep: QFrame = QFrame()
        sep.setFrameShape(QFrame.HLine)  # type: ignore
        sep.setStyleSheet(f"""
            border: none;
            border-top: 1px solid {self._theme.border_color};
            background: transparent;
        """)
        right_layout.addWidget(sep)

        # -- 操作按钮（垂直排列）--
        action_style: str = self._get_cv_action_btn_style()

        confirm_btn: QPushButton = QPushButton("确认保存")
        confirm_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))  # type: ignore
        confirm_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        confirm_btn.setMinimumHeight(34)
        confirm_btn.setStyleSheet(action_style)
        confirm_btn.clicked.connect(self._on_cv_confirm)
        right_layout.addWidget(confirm_btn)

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 10))
        cancel_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        cancel_btn.setMinimumHeight(32)
        cancel_btn.setStyleSheet(action_style)
        cancel_btn.clicked.connect(self._on_cv_cancel)
        right_layout.addWidget(cancel_btn)

        clear_btn: QPushButton = QPushButton("清除")
        clear_btn.setFont(QFont("Microsoft YaHei", 10))
        clear_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        clear_btn.setMinimumHeight(32)
        clear_btn.setStyleSheet(action_style)
        clear_btn.clicked.connect(self._on_cv_clear)
        right_layout.addWidget(clear_btn)

        right_layout.addStretch()

        body_row.addWidget(right_panel, stretch=3)

        card_layout.addLayout(body_row)

        return card

    # ================================================================
    #  课程表内联编辑器 — 加载科目配置
    # ================================================================
    def _load_cv_subject_categories(self) -> None:
        """从 subject_config.json 加载科目分类到缓存（兼容新旧格式）。"""
        if self._cv_subject_categories:
            return  # 已缓存

        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(
            script_dir, 'Config', 'subject_config.json'
        )
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                subject_types = config_data.get('Subject_Types', {})
                for cat_name, subjects in subject_types.items():
                    if isinstance(subjects, list):
                        names: List[str] = []
                        for entry in subjects:
                            n, _e = parse_subject_entry(entry)
                            if n:
                                names.append(n)
                        self._cv_subject_categories[cat_name] = names
                    elif subjects == 'None' or subjects is None:
                        self._cv_subject_categories[cat_name] = ['None']
            else:
                self._cv_subject_categories = {'Category_1': []}
        except Exception as e:
            logger.error(f"读取科目配置失败：{e}")
            self._cv_subject_categories = {'Category_1': []}

    # ================================================================
    #  课程表内联编辑器 — 科目按钮区填充 / 重建
    # ================================================================
    def _populate_cv_subject_buttons(self) -> None:
        """填充课程表内联编辑器的科目按钮区（按类别分组）。"""
        if self._cv_subject_layout is None:
            return
        btn_style: str = self._get_cv_subject_btn_style()
        dim_color: str = (
            'rgba(255,255,255,0.50)' if self._theme.theme == 'darkcolor'
            else 'rgba(0,0,0,0.50)'
        )

        self._cv_subject_buttons.clear()
        for cat_name, subjects in self._cv_subject_categories.items():
            # 类别标题
            cat_title: QLabel = QLabel(f"—— {cat_name} ——")
            cat_title.setFont(QFont("Microsoft YaHei", 10))
            cat_title.setStyleSheet(
                f"color: {dim_color}; background: transparent;"
            )
            self._cv_subject_layout.addWidget(cat_title)

            # 科目按钮流式布局（自动换行）
            flow_widget: QWidget = QWidget()
            flow_widget.setStyleSheet("background: transparent;")
            flow_layout: QHBoxLayout = QHBoxLayout(flow_widget)
            flow_layout.setContentsMargins(0, 0, 0, 0)
            flow_layout.setSpacing(6)

            for subject in subjects:
                btn: QPushButton = QPushButton(subject)
                btn.setFont(QFont("Microsoft YaHei", 11))
                btn.setCursor(Qt.PointingHandCursor)  # type: ignore
                btn.setMinimumHeight(32)
                btn.setMinimumWidth(44)
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(
                    lambda checked=False, s=subject: self._on_cv_subject_clicked(s)
                )
                self._cv_subject_buttons.append(btn)
                flow_layout.addWidget(btn)

            flow_layout.addStretch()
            self._cv_subject_layout.addWidget(flow_widget)

        self._cv_subject_layout.addStretch()

    def _rebuild_cv_subject_buttons(self) -> None:
        """科目配置变更后重建课程表内联编辑器的科目按钮区。"""
        if self._cv_subject_layout is None:
            return
        # 清空旧按钮
        while self._cv_subject_layout.count():
            item = self._cv_subject_layout.takeAt(0)
            w = item.widget()  # type: ignore
            if w is not None:
                w.deleteLater()
        self._populate_cv_subject_buttons()

    # ================================================================
    #  课程表内联编辑器 — 闪烁光标
    # ================================================================
    def _start_cv_blink(self) -> None:
        """启动单元格闪烁光标。"""
        if self._cv_blink_timer.isActive():
            self._cv_blink_timer.stop()
        self._cv_blink_on = False
        # 禁用交替行颜色和选中，防止 CSS 样式覆盖光标背景
        if self._curriculum_table is not None:
            self._curriculum_table.setAlternatingRowColors(False)
            self._curriculum_table.setSelectionMode(
                QAbstractItemView.NoSelection  # type: ignore
            )
            self._curriculum_table.clearSelection()
        # 立即显示光标（不等定时器首触发），然后由定时器接管闪烁
        self._toggle_cv_blink()
        self._cv_blink_timer.start()

    def _stop_cv_blink(self) -> None:
        """停止闪烁光标，恢复单元格背景，隐藏编辑器卡片。"""
        if self._cv_blink_timer.isActive():
            self._cv_blink_timer.stop()
        # 恢复当前光标单元格背景
        self._restore_cv_cell_bg()
        self._cv_blink_on = False
        # 恢复交替行颜色和选中模式
        if self._curriculum_table is not None:
            self._curriculum_table.setAlternatingRowColors(True)
            self._curriculum_table.setSelectionMode(
                QAbstractItemView.SingleSelection  # type: ignore
            )
        # 隐藏编辑器卡片
        if self._cv_editor_card is not None:
            self._cv_editor_card.setVisible(False)
        # 取消所有科目按钮高亮
        for btn in self._cv_subject_buttons:
            btn.setProperty('selected', 'false')  # type: ignore
            btn.setStyleSheet(self._get_cv_subject_btn_style())
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

    def _toggle_cv_blink(self) -> None:
        """切换光标单元格的闪烁状态（由 QTimer 触发）。"""
        if self._curriculum_table is None:
            return
        row: int = self._cv_cursor_row
        col: int = self._cv_cursor_col
        if row < 0 or col < 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is None:
            return

        if self._cv_blink_on:
            # 恢复常态
            item.setBackground(QColor(0, 0, 0, 0))  # transparent
        else:
            # 蓝色高亮光标
            if self._theme.theme == 'darkcolor':
                item.setBackground(QColor(33, 150, 243, 77))   # ~30% alpha
            else:
                item.setBackground(QColor(33, 150, 243, 77))

        # 强制重绘，确保背景变化立即可见
        self._curriculum_table.viewport().update()  # type: ignore

        self._cv_blink_on = not self._cv_blink_on

    def _restore_cv_cell_bg(self) -> None:
        """恢复当前光标单元格的背景为透明。"""
        if self._curriculum_table is None:
            return
        row: int = self._cv_cursor_row
        col: int = self._cv_cursor_col
        if row < 0 or col < 0:
            return
        item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
        if item is not None:
            item.setBackground(QColor(0, 0, 0, 0))

    # ================================================================
    #  课程表内联编辑器 — 科目点击（直接修改，无需确认）
    # ================================================================
    def _on_cv_subject_clicked(self, subject: str) -> None:
        """科目按钮点击：直接修改当前光标单元格的科目。"""
        day: str = self._cv_cursor_day
        lesson: str = self._cv_cursor_lesson
        if not day or not lesson:
            return

        # "None" 科目等同于清空
        new_subject: str = '' if subject == 'None' else subject

        # 更新待编辑数据
        if day not in self._pending_curriculum_data:
            self._pending_curriculum_data[day] = {}
        if new_subject:
            self._pending_curriculum_data[day][lesson] = new_subject
        else:
            self._pending_curriculum_data[day].pop(lesson, None)

        # 直接更新表格单元格显示
        if self._curriculum_table is not None:
            row: int = self._cv_cursor_row
            col: int = self._cv_cursor_col
            item: Optional[QTableWidgetItem] = self._curriculum_table.item(row, col)
            if item is not None:
                cell_text: str = new_subject if new_subject else '—'
                item.setText(cell_text)
                fc: str = self._theme.font_color
                if new_subject:
                    item.setForeground(QColor(fc))
                else:
                    item.setForeground(
                        QColor(255, 255, 255, 64)
                        if self._theme.theme == 'darkcolor'
                        else QColor(0, 0, 0, 64)
                    )

        # 刷新编辑器状态和高亮按钮
        self._refresh_cv_editor_status()

        # 高亮当前科目按钮
        self._highlight_cv_subject_btn(subject)

        logger.info(
            f"课程表内联编辑：{day} {lesson} → "
            f"{new_subject or '（清除）'}"
        )

    # ================================================================
    #  课程表内联编辑器 — 导航
    # ================================================================
    def _on_cv_navigate(self, direction: str) -> None:
        """移动光标到相邻单元格。"""
        if self._curriculum_table is None:
            return

        day_names: List[str] = [
            'Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday',
        ]

        # 获取当前天在列表中的索引
        try:
            day_idx: int = day_names.index(self._cv_cursor_day)
        except ValueError:
            return

        # 获取所有课时行（跳过非 lesson 行）
        lesson_rows: List[int] = []
        lesson_keys: List[str] = []
        for r in range(self._curriculum_table.rowCount()):
            label_item: Optional[QTableWidgetItem] = (
                self._curriculum_table.item(r, 0)
            )
            if label_item is None:
                continue
            key = label_item.data(Qt.UserRole)  # type: ignore
            if isinstance(key, str) and key.startswith('lesson_'):
                lesson_rows.append(r)
                lesson_keys.append(key)

        if not lesson_rows:
            return

        # 获取当前 lesson 在列表中的索引
        try:
            lesson_idx: int = lesson_keys.index(self._cv_cursor_lesson)
        except ValueError:
            return

        new_day_idx: int = day_idx
        new_lesson_idx: int = lesson_idx

        if direction == 'left':
            new_day_idx = (day_idx - 1) % 7
        elif direction == 'right':
            new_day_idx = (day_idx + 1) % 7
        elif direction == 'up':
            new_lesson_idx = (lesson_idx - 1) % len(lesson_keys)
        elif direction == 'down':
            new_lesson_idx = (lesson_idx + 1) % len(lesson_keys)

        # 停止旧光标
        self._restore_cv_cell_bg()
        self._cv_blink_on = False

        # 更新光标位置
        new_row: int = lesson_rows[new_lesson_idx]
        new_col: int = new_day_idx + 1  # col 0 是行标签
        new_day: str = day_names[new_day_idx]
        new_lesson: str = lesson_keys[new_lesson_idx]

        self._cv_cursor_row = new_row
        self._cv_cursor_col = new_col
        self._cv_cursor_day = new_day
        self._cv_cursor_lesson = new_lesson

        # 刷新状态和按钮高亮
        self._refresh_cv_editor_status()

        # 重启发闪烁
        self._start_cv_blink()

        logger.info(f"课程表光标导航：{direction} → {new_day} {new_lesson}")

    # ================================================================
    #  课程表内联编辑器 — 清除
    # ================================================================
    def _on_cv_clear(self) -> None:
        """清除当前光标单元格的科目。"""
        self._on_cv_subject_clicked('None')

    # ================================================================
    #  课程表内联编辑器 — 确认保存
    # ================================================================
    def _on_cv_confirm(self) -> None:
        """弹出二次确认对话框，确认后直接保存课程表到本地文件并关闭编辑器。"""
        reply: QMessageBox.StandardButton = QMessageBox.question(
            self,
            "确认保存",
            "是否保存课程表修改？\n\n"
            "修改将直接保存到本地文件，"
            "点击「应用修改」后重启软件才会同步到主窗口。",
            QMessageBox.No | QMessageBox.Yes,  # type: ignore
            QMessageBox.Yes,  # type: ignore
        )

        if reply == QMessageBox.Yes:  # type: ignore
            # 将待编辑数据写回课程表编辑副本
            self._editing_curriculum_data = copy.deepcopy(
                self._pending_curriculum_data
            )
            self._has_unsaved_changes = True
            # 直接保存到本地文件（不入缓存）
            self._save_editing_curriculum_file()
            self._refresh_apply_button()
            logger.info("课程表修改已确认（已直接保存到本地文件）")

            # 停止光标并隐藏编辑器
            self._stop_cv_blink()
            # 刷新课程表 UI
            self._refresh_curriculum_table()
            self._refresh_curriculum_status()
        else:
            logger.info("课程表修改：用户取消确认，保持编辑状态")

    # ================================================================
    #  课程表内联编辑器 — 取消
    # ================================================================
    def _on_cv_cancel(self) -> None:
        """取消编辑：丢弃待编辑数据，恢复表格显示，关闭编辑器。"""
        logger.info("课程表修改已取消，丢弃待编辑数据")
        self._stop_cv_blink()
        # 从原始数据刷新表格
        self._refresh_curriculum_table()

    # ================================================================
    #  课程表内联编辑器 — 刷新状态显示
    # ================================================================
    def _refresh_cv_editor_status(self) -> None:
        """刷新编辑器卡片中的状态标签和科目按钮高亮。"""
        if self._cv_status_label is None:
            return

        day_labels: Dict[str, str] = {
            'Monday': '周一', 'Tuesday': '周二', 'Wednesday': '周三',
            'Thursday': '周四', 'Friday': '周五', 'Saturday': '周六',
            'Sunday': '周日',
        }
        day_label: str = day_labels.get(self._cv_cursor_day,
                                        self._cv_cursor_day)
        lesson_num: str = self._cv_cursor_lesson.replace('lesson_', '')

        # 获取时间信息（优先使用编辑副本）
        time_info: str = ''
        timetable_src = (
            self._editing_timetable_data
            if self._editing_timetable_data
            else (self._schedule_data.timetable_data if self._schedule_data else {})
        )
        timetable_val = timetable_src.get(self._cv_cursor_lesson)
        if isinstance(timetable_val, list) and len(timetable_val) >= 2:
                time_info = (
                    f"{self._fmt_time(timetable_val[0])}–"
                    f"{self._fmt_time(timetable_val[1])}"
                )

        # 获取当前科目（从待编辑数据中读取）
        current_subject: str = ''
        day_data: Dict = self._pending_curriculum_data.get(
            self._cv_cursor_day, {}
        )
        if isinstance(day_data, dict):
            current_subject = day_data.get(self._cv_cursor_lesson, '')

        status_text: str = (
            f"📍 {day_label} · 第{lesson_num}节"
        )
        if time_info:
            status_text += f" ({time_info})"
        if current_subject:
            status_text += f"\n当前科目：{current_subject}"
        else:
            status_text += "\n当前科目：（未设置）"

        self._cv_status_label.setText(status_text)

        # 高亮当前科目对应的按钮
        self._highlight_cv_subject_btn(current_subject)

    def _highlight_cv_subject_btn(self, subject: str) -> None:
        """高亮指定科目的按钮（取消其他按钮高亮）。"""
        target: str = subject if subject else 'None'
        for btn in self._cv_subject_buttons:
            if btn.text() == target:
                btn.setProperty('selected', 'true')  # type: ignore
            else:
                btn.setProperty('selected', 'false')  # type: ignore
            btn.setStyleSheet(self._get_cv_subject_btn_style())
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

    # ================================================================
    #  课程表内联编辑器 — 样式方法
    # ================================================================
    def _get_cv_card_style(self) -> str:
        """返回编辑器卡片的 QSS 样式。"""
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.05)'
            card_border: str = 'rgba(33, 150, 243, 0.25)'
        else:
            card_bg = 'rgba(33, 150, 243, 0.03)'
            card_border = 'rgba(33, 150, 243, 0.20)'

        return f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 10px;
            }}
        """

    def _get_cv_nav_btn_style(self) -> str:
        """返回导航按钮的 QSS 样式（与左侧科目按钮一致：暗色模式深底浅字）。"""
        return self._get_cv_subject_btn_style()

    def _get_cv_action_btn_style(self) -> str:
        """返回课程表编辑卡操作按钮（确认保存 / 取消 / 清除）的 QSS 样式。

        与左侧科目按钮保持一致：暗色模式下深色背景 + 浅色字体，
        浅色模式下浅色背景 + 深色字体。
        """
        return self._get_cv_subject_btn_style()

    def _get_cv_subject_btn_style(self) -> str:
        """返回科目按钮的 QSS 样式。"""
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.14)'
            sel_bg: str = 'rgba(76, 175, 80, 0.25)'
            sel_border: str = 'rgba(76, 175, 80, 0.50)'
            border: str = 'rgba(255,255,255,0.10)'
        else:
            bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
            sel_bg = 'rgba(76, 175, 80, 0.15)'
            sel_border = 'rgba(76, 175, 80, 0.40)'
            border = 'rgba(0,0,0,0.10)'

        return f"""
            QPushButton {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton[selected="true"] {{
                background-color: {sel_bg};
                border-color: {sel_border};
            }}
        """

    # ================================================================
    #  课程表 — 加载
    # ================================================================
    def _on_load_curriculum(self) -> None:
        """打开文件对话框选择 JSON 文件加载为当前课程表。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        start_dir: str = os.path.join(script_dir, 'Config', 'curriculum')

        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载课程表", start_dir,
            "JSON 文件 (*.json);;所有文件 (*)"
        )

        if not file_path:
            return

        try:
            rel_path: str = os.path.relpath(file_path, script_dir)
        except ValueError:
            rel_path = file_path

        logger.info(f"加载课程表：{rel_path}")

        # 直接读取文件到课程表编辑副本
        try:
            load_path: str = os.path.join(script_dir, rel_path)
            with open(load_path, 'r', encoding='utf-8') as f:
                self._editing_curriculum_data = json.load(f)
            self._editing_curriculum_path = rel_path
            self._has_unsaved_changes = True
            self._refresh_curriculum_table()
            self._refresh_curriculum_status()
            self._refresh_apply_button()
            logger.info(f"课程表已加载至编辑副本：{rel_path}")
        except Exception as e:
            logger.error(f"加载课程表到编辑副本失败：{e}")

    # ================================================================
    #  课程表 — 新建
    # ================================================================
    def _on_new_curriculum(self) -> None:
        """弹出新建课程表对话框。"""
        dialog: NewCurriculumDialog = NewCurriculumDialog(
            theme_manager=self._theme,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:  # type: ignore
            new_name: str = dialog.result_name()
            copy_from: str = dialog.result_copy_from()
            self._create_new_curriculum_file(new_name, copy_from)

    def _create_new_curriculum_file(self, name: str, copy_from: str) -> None:
        """创建新的课程表 JSON 文件并加载。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        curriculum_dir: str = os.path.join(script_dir, 'Config', 'curriculum')
        os.makedirs(curriculum_dir, exist_ok=True)

        new_path: str = os.path.join(curriculum_dir, name)

        if copy_from:
            src_path: str = os.path.join(curriculum_dir, copy_from)
            try:
                with open(src_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"复制课程表模板失败：{e}")
                data = {
                    "Monday": {}, "Tuesday": {}, "Wednesday": {},
                    "Thursday": {}, "Friday": {}, "Saturday": {},
                    "Sunday": {},
                }
        else:
            # 空白 7 天模板
            data = {
                "Monday": {}, "Tuesday": {}, "Wednesday": {},
                "Thursday": {}, "Friday": {}, "Saturday": {},
                "Sunday": {},
            }

        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"创建课程表文件失败：{e}")
            return

        logger.info(
            f"已创建新课程表：{name}"
            f"（模板={'复制 ' + copy_from if copy_from else '空白'}）"
        )

        rel_path: str = f"Config/curriculum/{name}"
        # 加载到课程表编辑副本
        try:
            with open(new_path, 'r', encoding='utf-8') as f:
                self._editing_curriculum_data = json.load(f)
            self._editing_curriculum_path = rel_path
            self._has_unsaved_changes = True
            self._refresh_curriculum_table()
            self._refresh_curriculum_status()
            self._refresh_apply_button()
        except Exception as e:
            logger.error(f"加载新课程表到编辑副本失败：{e}")

    # ================================================================
    #  课程表 — 表格样式
    # ================================================================
    def _style_curriculum_table(self) -> None:
        """根据主题刷新课程表表格样式。"""
        if self._curriculum_table is None:
            return

        fc: str = self._theme.font_color
        bc: str = self._theme.root_back_color

        if self._theme.theme == 'darkcolor':
            header_bg: str = '#2d2d2d'
            alt_bg: str = '#252525'
            sel_bg: str = 'rgba(255,255,255,0.08)'
            hover_bg: str = 'rgba(255,255,255,0.04)'
            grid_color: str = 'rgba(255,255,255,0.06)'
        else:
            header_bg = '#f5f5f5'
            alt_bg = '#fafafa'
            sel_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.02)'
            grid_color = 'rgba(0,0,0,0.06)'

        self._curriculum_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bc};
                color: {fc};
                border: none;
                border-radius: 7px;
                gridline-color: {grid_color};
            }}
            QTableWidget::item {{
                padding: 8px 6px;
            }}
            QTableWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTableWidget::item:selected {{
                background-color: {sel_bg};
                color: {fc};
            }}
            QTableWidget::item:alternate {{
                background-color: {alt_bg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {fc};
                border: none;
                border-bottom: 2px solid {self._theme.border_color};
                padding: 10px 6px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)

    # ================================================================
    #  课程表 — 刷新状态
    # ================================================================
    def _refresh_curriculum_status(self) -> None:
        """刷新课程表状态标签文字。"""
        if self._curriculum_status_label is not None:
            self._curriculum_status_label.setText(
                self._get_curriculum_status_text()
            )

    # ================================================================
    #  主题刷新（覆盖基类）
    # ================================================================
    def refresh_theme(self) -> None:
        """主题变更后刷新所有样式。"""
        super().refresh_theme()
        self._refresh_nav_styles()
        self._refresh_exit_btn_style()
        # 刷新基础设置 — 字体卡片
        if self._font_card is not None:
            self._font_card.setStyleSheet(self._get_status_card_style())
        if self._font_title_label is not None:
            self._font_title_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._font_hint_label is not None:
            self._font_hint_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none; opacity: 0.6;"
            )
        if self._font_combo is not None:
            self._font_combo.setStyleSheet(self._get_font_combo_style())
        if self._font_preview_title_label is not None:
            self._font_preview_title_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._font_preview_label is not None:
            self._font_preview_label.setStyleSheet(self._get_font_preview_style())
        # 刷新基础设置 — 语言切换卡片
        if self._language_card is not None:
            self._language_card.setStyleSheet(self._get_status_card_style())
        if self._language_title_label is not None:
            self._language_title_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._language_hint_label is not None:
            self._language_hint_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none; opacity: 0.6;"
            )
        if self._language_combo is not None:
            self._language_combo.setStyleSheet(self._get_font_combo_style())
        # 刷新美化 — 明暗模式卡片
        if self._theme_card is not None:
            self._theme_card.setStyleSheet(self._get_status_card_style())
        if self._theme_title_label is not None:
            self._theme_title_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._theme_hint_label is not None:
            self._theme_hint_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none; opacity: 0.6;"
            )
        if self._theme_combo is not None:
            self._theme_combo.setStyleSheet(self._get_font_combo_style())
        # 刷新美化 — 主题色卡片
        if self._color_card is not None:
            self._color_card.setStyleSheet(self._get_status_card_style())
        if self._color_title_label is not None:
            self._color_title_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._color_hint_label is not None:
            self._color_hint_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none; opacity: 0.6;"
            )
        if self._color_confirm_btn is not None:
            self._color_confirm_btn.setStyleSheet(self._get_confirm_btn_style())
        if self._status_card is not None:
            self._status_card.setStyleSheet(self._get_status_card_style())
        if self._status_label is not None:
            self._status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._table_frame is not None:
            self._table_frame.setStyleSheet(self._get_table_frame_style())
        if self._timetable_table is not None:
            self._style_table()
        # 刷新课程表 UI
        if self._curriculum_status_card is not None:
            self._curriculum_status_card.setStyleSheet(
                self._get_status_card_style()
            )
        if self._curriculum_status_label is not None:
            self._curriculum_status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        if self._curriculum_table_frame is not None:
            self._curriculum_table_frame.setStyleSheet(
                self._get_table_frame_style()
            )
        if self._curriculum_table is not None:
            self._style_curriculum_table()
        # 刷新课程表内联编辑器
        if self._cv_editor_card is not None:
            self._cv_editor_card.setStyleSheet(self._get_cv_card_style())
        if self._cv_status_label is not None:
            self._cv_status_label.setStyleSheet(
                f"color: {self._theme.font_color}; background: transparent; border: none;"
            )
        # 重刷科目按钮样式
        btn_style: str = self._get_cv_subject_btn_style()
        for btn in self._cv_subject_buttons:
            btn.setStyleSheet(btn_style)
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore
        # 刷新应用修改按钮样式
        self._refresh_apply_button()
        # 刷新显示规则控件
        if self._rule_list is not None:
            self._rule_list.refresh_theme()
        if self._rule_add_btn is not None:
            self._rule_add_btn.setStyleSheet(self._get_add_btn_style())
        # 刷新科目编辑控件
        if self._subject_card is not None:
            self._subject_card.setStyleSheet(self._get_status_card_style())
        sj_style: str = self._get_cv_subject_btn_style()
        for btn in self._subject_buttons:
            btn.setStyleSheet(sj_style)
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore
        # 刷新事件系统控件
        if self._event_card is not None:
            self._event_card.setStyleSheet(self._get_knotlink_card_style())
        ev_style: str = self._get_event_rule_btn_style()
        for btn in self._event_buttons:
            btn.setStyleSheet(ev_style)
            btn.style().unpolish(btn)  # type: ignore
            btn.style().polish(btn)  # type: ignore

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
            index（int）：目标页面索引（0-4）
        """
        # 首次进入课表编辑页面时初始化编辑副本；之后保留编辑状态（修改已直接落盘）
        if index == 2 and self._schedule_data is not None:
            if not self._editing_initialized:
                self._init_editing_copies()
                self._editing_initialized = True
            self._refresh_table()

        logger.info(f"[SettingsWindow] 导航切换至页面 {index}：{self.NAV_ITEMS[index][1]}")
        self._current_index = index
        self._stack.setCurrentIndex(index)
        self._refresh_nav_styles()

    # ================================================================
    #  退出按钮
    # ================================================================
    def _on_exit_clicked(self) -> None:
        """点击退出按钮：如有未应用修改则弹窗询问是否立即应用，然后隐藏窗口。"""
        if (self._has_unsaved_changes or self._font_is_dirty()
                or self._language_is_dirty() or self._autostart_is_dirty()
                or self._appearance_is_dirty()):
            box: QMessageBox = QMessageBox(self)
            box.setWindowTitle("未应用的修改")
            box.setText(
                "您有未应用的修改。\n\n"
                "是否立即应用修改？"
            )
            apply_btn: QPushButton = box.addButton(
                "应用", QMessageBox.AcceptRole  # type: ignore
            )
            box.addButton("取消", QMessageBox.RejectRole)  # type: ignore
            box.setDefaultButton(apply_btn)  # type: ignore
            box.exec()
            if box.clickedButton() is apply_btn:
                self._on_apply_changes()      # 立即应用 → 重启软件
            else:
                self._on_postpone_changes()   # 暂不应用 → 仅保存文件
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
        如有未应用修改则弹窗询问是否立即应用。
        """
        if (self._has_unsaved_changes or self._font_is_dirty()
                or self._language_is_dirty() or self._autostart_is_dirty()
                or self._appearance_is_dirty()):
            box: QMessageBox = QMessageBox(self)
            box.setWindowTitle("未应用的修改")
            box.setText(
                "您有未应用的修改。\n\n"
                "是否立即应用修改？"
            )
            apply_btn: QPushButton = box.addButton(
                "应用", QMessageBox.AcceptRole  # type: ignore
            )
            box.addButton("取消", QMessageBox.RejectRole)  # type: ignore
            box.setDefaultButton(apply_btn)  # type: ignore
            box.exec()
            if box.clickedButton() is apply_btn:
                self._on_apply_changes()      # 立即应用 → 重启软件
            else:
                self._on_postpone_changes()   # 暂不应用 → 仅保存文件
        logger.info("[SettingsWindow] 关闭事件 → 隐藏窗口")
        event.ignore()
        self.hide()


# ==================== 带主题背景色的对话框基类 ====================


class ThemedDialog(QDialog):
    """
    # ThemedDialog — 带主题背景色的对话框基类

    通过 paintEvent 直接填充背景色（与 ThemedWidget 的思路一致），
    使子窗口在暗色模式下整体呈现深色背景，而不是仅内部控件变暗。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化对话框基类（子类负责在 super().__init__ 后设置 self._theme）。"""
        super().__init__(parent)
        self._theme: Optional[ThemeManager] = None

    def _dialog_bg(self) -> str:
        """返回对话框背景色（暗色模式用次级深色，其余保持浅色）。"""
        if self._theme is not None and self._theme.theme == 'darkcolor':
            return '#252526'
        return '#FAFAFA'

    def _field_style(self) -> str:
        """返回输入框（QLineEdit）的主题 QSS 样式。"""
        fc: str = self._theme.font_color if self._theme else '#212121'
        if self._theme is not None and self._theme.theme == 'darkcolor':
            bg: str = '#2d2d2d'
            border: str = 'rgba(255,255,255,0.14)'
        else:
            bg = '#FFFFFF'
            border = 'rgba(0,0,0,0.14)'
        return f"""
            QLineEdit {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
            }}
        """

    def _combo_style(self) -> str:
        """返回下拉框（QComboBox）的主题 QSS 样式。"""
        fc: str = self._theme.font_color if self._theme else '#212121'
        if self._theme is not None and self._theme.theme == 'darkcolor':
            bg: str = '#2d2d2d'
            border: str = 'rgba(255,255,255,0.14)'
        else:
            bg = '#FFFFFF'
            border = 'rgba(0,0,0,0.14)'
        return f"""
            QComboBox {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QComboBox:hover, QComboBox:focus {{
                border-color: #2196F3;
            }}
            QComboBox QAbstractItemView {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                selection-background-color: rgba(33, 150, 243, 0.25);
                selection-color: {fc};
                outline: 0;
            }}
        """

    def paintEvent(self, event) -> None:  # noqa: ANN001
        """填充对话框背景色，保证暗色模式下整体为深色。"""
        painter: QPainter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._dialog_bg()))


# ==================== KnotLink 接口 / 信号详情对话框 ====================


class KnotLinkDetailDialog(ThemedDialog):
    """
    # KnotLinkDetailDialog — KnotLink 接口 / 信号详情对话框

    点击设置页 KnotLink 标签页中的接口规则或信号规则按钮后弹出。
    接口规则展示：接口通道、参数、返回值、请求与响应示例；
    信号规则展示：信号通道、触发时机、载荷字段与广播示例。
    """

    def __init__(self, item: Dict, is_signal: bool,
                 theme_manager: Optional[ThemeManager] = None,
                 parent: Optional[QWidget] = None) -> None:
        """初始化详情对话框（item 为规则数据，is_signal 标记是否为信号规则）。"""
        super().__init__(parent)
        self._theme: Optional[ThemeManager] = theme_manager
        self._item: Dict = item
        self._is_signal: bool = is_signal

        self.setWindowTitle("信号详情" if is_signal else "接口详情")
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumSize(560, 400)

        self._setup_ui()
        logger.info(
            f"KnotLinkDetailDialog 初始化完成：{item.get('name')}"
            f"（{'信号' if is_signal else '接口'}）"
        )

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造对话框内容（滚动区域 + 底部关闭按钮）。"""
        fc: str = self._theme.font_color if self._theme else '#212121'
        tc: str = self._theme.theme_color if self._theme else '#2196f3'
        item: Dict = self._item
        is_signal: bool = self._is_signal

        root: QVBoxLayout = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        # ---- 滚动内容区 ----
        scroll: QScrollArea = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)  # type: ignore
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore

        content: QWidget = QWidget()
        content.setStyleSheet("background: transparent;")
        lay: QVBoxLayout = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)

        # ---- 名称 ----
        name_label: QLabel = QLabel(str(item.get('name', '')))
        name_label.setFont(QFont("Consolas", 17, QFont.Bold))  # type: ignore
        name_label.setStyleSheet(f"color: {tc}; background: transparent;")
        name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore
        lay.addWidget(name_label)

        # ---- 标题 ----
        title_label: QLabel = QLabel(str(item.get('title', '')))
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))  # type: ignore
        title_label.setStyleSheet(f"color: {fc}; background: transparent;")
        lay.addWidget(title_label)

        # ---- 简介 ----
        intro_label: QLabel = QLabel(str(item.get('intro', '')))
        intro_label.setFont(QFont("Microsoft YaHei", 11))
        intro_label.setWordWrap(True)
        intro_label.setStyleSheet(f"color: {fc}; background: transparent;")
        lay.addWidget(intro_label)

        # ---- 通道信息 ----
        channel: str = (
            f"信号通道：signal（signal_id = {SIGNAL_ID}）"
            if is_signal else
            f"接口通道：openSocket（socket_id = {SOCKET_ID}）"
        )
        channel_label: QLabel = QLabel(channel)
        channel_label.setFont(QFont("Microsoft YaHei", 10))
        channel_label.setStyleSheet(
            f"color: {fc}; background: transparent; opacity: 0.6;"
        )
        lay.addWidget(channel_label)

        if is_signal:
            # ---- 触发时机 ----
            self._add_section_header(lay, "触发时机", tc, fc)
            trigger_label: QLabel = QLabel(str(item.get('trigger', '')))
            trigger_label.setFont(QFont("Microsoft YaHei", 11))
            trigger_label.setWordWrap(True)
            trigger_label.setStyleSheet(f"color: {fc}; background: transparent;")
            lay.addWidget(trigger_label)

            # ---- 载荷字段 ----
            self._add_section_header(lay, "载荷字段", tc, fc)
            fields: List[tuple] = item.get('fields', []) or []
            for fname, ftype, fdesc in fields:
                lay.addWidget(self._make_kv_label(fname, ftype, fdesc, tc, fc))
            if not fields:
                lay.addWidget(self._make_empty_label("无载荷字段", fc))

            # ---- 广播示例 ----
            self._add_section_header(lay, "广播示例", tc, fc)
            lay.addWidget(self._make_code_label(str(item.get('example', ''))))
        else:
            # ---- 参数 ----
            self._add_section_header(lay, "参数", tc, fc)
            params: List[tuple] = item.get('params', []) or []
            for pname, ptype, required, pdesc in params:
                meta: str = f"{ptype} · {'必填' if required else '可选'}"
                lay.addWidget(self._make_kv_label(pname, meta, pdesc, tc, fc))
            if not params:
                lay.addWidget(self._make_empty_label("该接口无需参数", fc))

            # ---- 返回值 ----
            self._add_section_header(lay, "返回值", tc, fc)
            returns: List[tuple] = item.get('returns', []) or []
            for rname, rtype, rdesc in returns:
                lay.addWidget(self._make_kv_label(rname, rtype, rdesc, tc, fc))
            if not returns:
                lay.addWidget(self._make_empty_label("无返回值", fc))

            # ---- 请求示例 / 响应示例 ----
            self._add_section_header(lay, "请求示例", tc, fc)
            lay.addWidget(self._make_code_label(str(item.get('req_example', ''))))
            self._add_section_header(lay, "响应示例", tc, fc)
            lay.addWidget(self._make_code_label(str(item.get('resp_example', ''))))

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ---- 底部关闭按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()
        close_btn: QPushButton = QPushButton("关闭")
        close_btn.setFont(QFont("Microsoft YaHei", 11))
        close_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        close_btn.setMinimumHeight(34)
        close_btn.setMinimumWidth(90)
        close_btn.setStyleSheet(self._dialog_button_style())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ================================================================
    #  辅助构建
    # ================================================================
    def _add_section_header(self, lay: QVBoxLayout, text: str,
                            tc: str, fc: str) -> None:
        """添加小节标题与分隔细线。"""
        header: QLabel = QLabel(text)
        header.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))  # type: ignore
        header.setStyleSheet(f"color: {fc}; background: transparent;")
        header.setContentsMargins(0, 6, 0, 0)
        lay.addWidget(header)

        line: QFrame = QFrame()
        line.setFrameShape(QFrame.HLine)  # type: ignore
        border: str = self._theme.border_color if self._theme else 'rgba(0,0,0,0.08)'
        line.setStyleSheet(
            f"border: none; border-top: 1px solid {border}; background: transparent;"
        )
        lay.addWidget(line)

    def _make_kv_label(self, key: str, meta: str, desc: str,
                       tc: str, fc: str) -> QLabel:
        """构造字段行标签：键名（等宽、主题色）+ 类型 + 说明。"""
        label: QLabel = QLabel()
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)  # type: ignore
        label.setText(
            f'<span style="font-family:Consolas; font-size:10pt; color:{tc};">'
            f'{_html_escape(key)}</span>'
            f'<span style="color:{fc};">&nbsp;&nbsp;{_html_escape(meta)}</span><br/>'
            f'<span style="color:{fc};">{_html_escape(desc)}</span>'
        )
        label.setStyleSheet("background: transparent;")
        return label

    def _make_empty_label(self, text: str, fc: str) -> QLabel:
        """构造"无内容"占位标签。"""
        label: QLabel = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setStyleSheet(f"color: {fc}; background: transparent; opacity: 0.5;")
        return label

    def _make_code_label(self, text: str) -> QLabel:
        """构造代码示例标签（等宽字体 + 底色方框）。"""
        fc: str = self._theme.font_color if self._theme else '#212121'
        if self._theme is not None and self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.05)'
            border: str = 'rgba(255,255,255,0.10)'
        else:
            bg = 'rgba(0,0,0,0.04)'
            border = 'rgba(0,0,0,0.08)'

        label: QLabel = QLabel(text)
        label.setFont(QFont("Consolas", 10))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore
        label.setStyleSheet(
            f"color: {fc}; background-color: {bg}; border: 1px solid {border};"
            f"border-radius: 6px; padding: 10px 12px;"
        )
        return label

    def _dialog_button_style(self) -> str:
        """返回对话框底部按钮样式。"""
        fc: str = self._theme.font_color if self._theme else '#212121'
        border: str = self._theme.border_color if self._theme else 'rgba(0,0,0,0.12)'
        if self._theme is not None and self._theme.theme == 'darkcolor':
            btn_bg: str = 'rgba(255,255,255,0.06)'
            hover_bg: str = 'rgba(255,255,255,0.12)'
        else:
            btn_bg = 'rgba(0,0,0,0.04)'
            hover_bg = 'rgba(0,0,0,0.08)'
        return f"""
            QPushButton {{
                color: {fc};
                background-color: {btn_bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """


# ==================== 时间表条目编辑对话框 ====================


class TimetableEntryDialog(ThemedDialog):
    """
    # TimetableEntryDialog — 时间表条目编辑子窗口

    用于新增或编辑时间表中的一条记录。
    支持两种类型：
      - 课时：需要设置开始和结束时间（内嵌滚轮控件）
      - 分隔线：不需要时间设置

    支持两种模式：
      - 编辑模式（stay_open=False）：模态弹窗，确认后关闭
      - 新建模式（stay_open=True）： 非模态，确认后保持打开，显示反馈
    ---
    """

    # 信号：新建模式下条目确认（类型, 开始时间, 结束时间）
    entry_confirmed = Signal(str, str, str)

    def __init__(self, entry_type: str = 'lesson',
                 start_time: str = '08:00',
                 end_time: str = '08:40',
                 theme_manager: Optional[ThemeManager] = None,
                 parent: Optional[QWidget] = None,
                 stay_open: bool = False) -> None:
        """
        初始化条目编辑对话框。

        参数：
            entry_type    （str）：'lesson' 或 'dividerline'
            start_time    （str）：课时开始时间 HH:MM
            end_time      （str）：课时结束时间 HH:MM
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
            stay_open     （bool）：True=新建模式（不关闭），False=编辑模式
        """
        super().__init__(parent)
        self._theme: Optional[ThemeManager] = theme_manager
        self._entry_type: str = entry_type
        self._start_time: str = start_time
        self._end_time: str = end_time
        self._stay_open: bool = stay_open

        self.setWindowTitle('新建条目' if stay_open else '编辑条目')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(not stay_open)
        self.setMinimumWidth(380)

        # 滚轮控件引用
        self._start_hour: Optional[WheelColumn] = None
        self._start_min: Optional[WheelColumn] = None
        self._end_hour: Optional[WheelColumn] = None
        self._end_min: Optional[WheelColumn] = None
        self._result_label: Optional[QLabel] = None
        self._confirm_btn: Optional[QPushButton] = None

        self._setup_ui()
        logger.info(
            f"TimetableEntryDialog 初始化完成"
            f"（类型={entry_type}, stay_open={stay_open}）"
        )

    # ================================================================
    #  主题颜色获取
    # ================================================================
    def _get_wheel_colors(self) -> tuple:
        """根据主题获取滚轮的背景色和文字色。"""
        if self._theme is not None:
            if self._theme.theme == 'lightcolor':
                return '#FFFFFF', '#212121'
            elif self._theme.theme == 'darkcolor':
                return '#252526', '#E0E0E0'
            else:
                return self._theme.back_color, self._theme.font_color
        return '#FFFFFF', '#212121'

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造对话框布局（内嵌时间滚轮控件）。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color if self._theme else '#212121'

        # ---- 类型选择 ----
        type_label: QLabel = QLabel("条目类型：")
        type_label.setFont(QFont("Microsoft YaHei", 12))
        if self._theme:
            type_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(type_label)

        self._lesson_radio: QRadioButton = QRadioButton("课时")
        self._lesson_radio.setFont(QFont("Microsoft YaHei", 11))
        self._lesson_radio.setStyleSheet(
            f"color: {fc}; background: transparent;"
        )
        self._divider_radio: QRadioButton = QRadioButton("分隔线")
        self._divider_radio.setFont(QFont("Microsoft YaHei", 11))
        self._divider_radio.setStyleSheet(
            f"color: {fc}; background: transparent;"
        )

        radio_layout: QHBoxLayout = QHBoxLayout()
        radio_layout.addWidget(self._lesson_radio)
        radio_layout.addWidget(self._divider_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        # 默认选中
        if self._entry_type == 'dividerline':
            self._divider_radio.setChecked(True)
        else:
            self._lesson_radio.setChecked(True)

        # ---- 时间滚轮区域（内嵌，替代原来的弹窗按钮）----
        self._time_frame: QFrame = QFrame()
        time_layout: QVBoxLayout = QVBoxLayout(self._time_frame)
        time_layout.setContentsMargins(0, 6, 0, 0)
        time_layout.setSpacing(4)

        bg, tc = self._get_wheel_colors()

        # 解析初始时间
        sh_str, sm_str = self._start_time.split(':')
        fh_str, fm_str = self._end_time.split(':')
        sh: int = int(sh_str)
        sm: int = int(sm_str)
        fh: int = int(fh_str)
        fm: int = int(fm_str)

        hour_items: List[str] = [f"{i:02d}" for i in range(24)]
        min_items: List[str] = [f"{i:02d}" for i in range(60)]

        # 滚轮行（4 列滚轮 + 分隔符）
        wheels_row: QHBoxLayout = QHBoxLayout()
        wheels_row.setSpacing(0)
        wheels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        self._start_hour = WheelColumn(
            hour_items, sh, bg_color=bg, text_color=tc
        )
        self._start_hour.setFixedWidth(60)
        wheels_row.addWidget(self._start_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._start_min = WheelColumn(
            min_items, sm, bg_color=bg, text_color=tc
        )
        self._start_min.setFixedWidth(60)
        wheels_row.addWidget(self._start_min)
        wheels_row.addWidget(self._make_sep('—'))

        self._end_hour = WheelColumn(
            hour_items, fh, bg_color=bg, text_color=tc
        )
        self._end_hour.setFixedWidth(60)
        wheels_row.addWidget(self._end_hour)
        wheels_row.addWidget(self._make_sep(':'))

        self._end_min = WheelColumn(
            min_items, fm, bg_color=bg, text_color=tc
        )
        self._end_min.setFixedWidth(60)
        wheels_row.addWidget(self._end_min)

        time_layout.addLayout(wheels_row)

        # 分组标签行（"开始时间" / "结束时间"）
        labels_row: QHBoxLayout = QHBoxLayout()
        labels_row.setSpacing(0)
        labels_row.setAlignment(Qt.AlignCenter)  # type: ignore

        label_alpha: str = (
            "rgba(0,0,0,0.40)" if tc == '#212121'
            else "rgba(255,255,255,0.40)"
        )

        start_lbl: QLabel = QLabel('开始时间')
        start_lbl.setFont(QFont('Microsoft YaHei', 10))
        start_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        start_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        start_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(start_lbl)

        labels_row.addSpacing(16)

        end_lbl: QLabel = QLabel('结束时间')
        end_lbl.setFont(QFont('Microsoft YaHei', 10))
        end_lbl.setStyleSheet(
            f"color: {label_alpha}; background: transparent;"
        )
        end_lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        end_lbl.setFixedWidth(60 + 16 + 60)
        labels_row.addWidget(end_lbl)

        time_layout.addLayout(labels_row)

        layout.addWidget(self._time_frame)

        # ---- 分隔线提示 ----
        self._divider_hint: QLabel = QLabel("分隔线不需要时间设置")
        self._divider_hint.setFont(QFont("Microsoft YaHei", 11))
        self._divider_hint.setStyleSheet(
            f"color: {fc}; background: transparent; opacity: 0.5;"
        )
        self._divider_hint.setVisible(self._entry_type == 'dividerline')
        layout.addWidget(self._divider_hint)

        # ---- 结果反馈标签（新建模式下显示）----
        self._result_label = QLabel("")
        self._result_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))  # type: ignore
        self._result_label.setStyleSheet(
            "color: #4CAF50; background: transparent; padding: 4px 0;"
        )
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        # ---- 联动：radio 切换 ----
        self._lesson_radio.toggled.connect(self._on_type_changed)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        if self._stay_open:
            done_btn: QPushButton = QPushButton("完成")
            done_btn.setFont(QFont("Microsoft YaHei", 11))
            done_btn.setMinimumHeight(32)
            done_btn.clicked.connect(self.reject)
            btn_row.addWidget(done_btn)
        else:
            cancel_btn: QPushButton = QPushButton("取消")
            cancel_btn.setFont(QFont("Microsoft YaHei", 11))
            cancel_btn.setMinimumHeight(32)
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        self._confirm_btn = QPushButton("确认")
        self._confirm_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        self._confirm_btn.setMinimumHeight(32)
        self._confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._confirm_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._update_visibility()
        self.setFixedSize(self.sizeHint())

    # ================================================================
    #  分隔符标签
    # ================================================================
    def _make_sep(self, text: str) -> QLabel:
        """创建分隔符标签（: 或 —）。"""
        _, tc = self._get_wheel_colors()
        sep_alpha: str = (
            "rgba(0,0,0,0.30)" if tc == '#212121'
            else "rgba(255,255,255,0.35)"
        )
        label: QLabel = QLabel(text)
        label.setFont(QFont('Arial', 22))
        label.setStyleSheet(
            f"color: {sep_alpha}; background: transparent;"
        )
        label.setAlignment(Qt.AlignCenter)  # type: ignore
        label.setFixedWidth(16)
        return label

    # ================================================================
    #  事件处理
    # ================================================================
    def _on_type_changed(self, _checked: bool) -> None:
        """课时/分隔线切换时更新可见区域。"""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """根据当前选择显示/隐藏对应区域。"""
        is_lesson: bool = self._lesson_radio.isChecked()
        self._time_frame.setVisible(is_lesson)
        self._divider_hint.setVisible(not is_lesson)
        # 调整窗口大小以适应内容变化
        self.setFixedSize(self.sizeHint())

    def _on_confirm(self) -> None:
        """确认编辑。

        编辑模式：accept() 关闭对话框。
        新建模式：发射 entry_confirmed 信号，不关闭对话框。
        """
        if self._lesson_radio.isChecked() and self._start_hour is not None:
            st: str = (
                f"{self._start_hour.current_index:02d}:"
                f"{self._start_min.current_index:02d}" # type: ignore
            )
            ft: str = (
                f"{self._end_hour.current_index:02d}:" # type: ignore
                f"{self._end_min.current_index:02d}" # type: ignore
            )
            self._start_time = st
            self._end_time = ft
        else:
            st = self._start_time
            ft = self._end_time

        if self._stay_open:
            etype: str = (
                'lesson' if self._lesson_radio.isChecked()
                else 'dividerline'
            )
            logger.info(
                f"TimetableEntryDialog 确认（新建模式）：{etype} {st} — {ft}"
            )
            self.entry_confirmed.emit(etype, st, ft)
        else:
            logger.info("TimetableEntryDialog 确认（编辑模式）")
            self.accept()

    # ================================================================
    #  公开方法
    # ================================================================
    def show_result(self, lesson_label: str,
                    start_time: str, end_time: str,
                    next_start_time: str = '',
                    next_end_time: str = '') -> None:
        """显示新建结果并自动设置下一次的默认时间。

        参数：
            lesson_label    （str）：如 "第3节课" 或 "分隔线2"
            start_time      （str）：本次开始时间 HH:MM
            end_time        （str）：本次结束时间 HH:MM
            next_start_time （str）：下一次默认开始时间 HH:MM
            next_end_time   （str）：下一次默认结束时间 HH:MM
        """
        if self._result_label is not None:
            self._result_label.setText(
                f"✓ {lesson_label} {start_time}到{end_time}新建完成"
            )
            self._result_label.setVisible(True)

        # 自动设置下一次的默认时间
        if next_start_time and next_end_time:
            try:
                sh, sm = next_start_time.split(':')
                eh, em = next_end_time.split(':')
                if self._start_hour:
                    self._start_hour.set_current_index(int(sh))
                if self._start_min:
                    self._start_min.set_current_index(int(sm))
                if self._end_hour:
                    self._end_hour.set_current_index(int(eh))
                if self._end_min:
                    self._end_min.set_current_index(int(em))
            except (ValueError, IndexError):
                pass

    def result(self) -> dict:  # type: ignore
        """返回编辑结果（编辑模式下使用）。"""
        return {
            'type': (
                'lesson' if self._lesson_radio.isChecked()
                else 'dividerline'
            ),
            'start_time': self._start_time,
            'end_time': self._end_time,
        }


# ==================== 新建时间表对话框 ====================


class NewTimetableDialog(ThemedDialog):
    """
    # NewTimetableDialog — 新建时间表子窗口

    用于命名新时间表并可选择从已有时间表复制。
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化新建时间表对话框。

        参数：
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager # type: ignore

        self.setWindowTitle('新建时间表')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(380)

        self._name_input: Optional[QLineEdit] = None
        self._copy_combo: Optional[QComboBox] = None

        self._setup_ui()
        logger.info("NewTimetableDialog 初始化完成")

    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color

        # ---- 名称输入 ----
        name_label: QLabel = QLabel("时间表名称：")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(name_label)

        default_name: str = ScheduleDataManager.get_next_timetable_name()
        self._name_input = QLineEdit(default_name)
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        self._name_input.setStyleSheet(self._field_style())
        layout.addWidget(self._name_input)

        # ---- 复制来源 ----
        copy_label: QLabel = QLabel("从已有时间表复制（可选）：")
        copy_label.setFont(QFont("Microsoft YaHei", 12))
        copy_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(copy_label)

        self._copy_combo = QComboBox()
        self._copy_combo.setFont(QFont("Microsoft YaHei", 11))
        self._copy_combo.setMinimumHeight(32)
        self._copy_combo.setStyleSheet(self._combo_style())
        self._copy_combo.addItem("（空白）", "")
        for fname in ScheduleDataManager.get_timetable_files():
            self._copy_combo.addItem(fname, fname)
        layout.addWidget(self._copy_combo)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn: QPushButton = QPushButton("创建")
        create_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        create_btn.setMinimumHeight(32)
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _on_create(self) -> None:
        """点击创建按钮。"""
        name: str = self._name_input.text().strip() if self._name_input else ''
        if not name:
            logger.warning("新建时间表：名称为空")
            return
        if not name.endswith('.json'):
            name += '.json'
        logger.info(f"新建时间表：名称={name}")
        # 名称验证通过，存储在 result_name 中
        self._result_name: str = name
        self._result_copy_from: str = (
            self._copy_combo.currentData() if self._copy_combo else ''
        )
        self.accept()

    def result_name(self) -> str:
        """返回用户输入的名称。"""
        return getattr(self, '_result_name', 'timetable_1.json')

    def result_copy_from(self) -> str:
        """返回选择的复制来源（空字符串表示空白）。"""
        return getattr(self, '_result_copy_from', '')


# ==================== 新建课程表对话框 ====================


class NewCurriculumDialog(ThemedDialog):
    """
    # NewCurriculumDialog — 新建课程表子窗口

    用于命名新课程表并可选择从已有课程表复制。
    结构与 NewTimetableDialog 一致，仅默认命名和目录不同。
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 parent: Optional[QWidget] = None) -> None:
        """
        初始化新建课程表对话框。

        参数：
            theme_manager （ThemeManager）：主题管理器
            parent        （QWidget | None）：父窗口
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager # type: ignore

        self.setWindowTitle('新建课程表')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(380)

        self._name_input: Optional[QLineEdit] = None
        self._copy_combo: Optional[QComboBox] = None

        self._setup_ui()
        logger.info("NewCurriculumDialog 初始化完成")

    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color

        # ---- 名称输入 ----
        name_label: QLabel = QLabel("课程表名称：")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(name_label)

        default_name: str = ScheduleDataManager.get_next_curriculum_name()
        self._name_input = QLineEdit(default_name)
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        self._name_input.setStyleSheet(self._field_style())
        layout.addWidget(self._name_input)

        # ---- 复制来源 ----
        copy_label: QLabel = QLabel("从已有课程表复制（可选）：")
        copy_label.setFont(QFont("Microsoft YaHei", 12))
        copy_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(copy_label)

        self._copy_combo = QComboBox()
        self._copy_combo.setFont(QFont("Microsoft YaHei", 11))
        self._copy_combo.setMinimumHeight(32)
        self._copy_combo.setStyleSheet(self._combo_style())
        self._copy_combo.addItem("（空白）", "")
        for fname in ScheduleDataManager.get_curriculum_files():
            self._copy_combo.addItem(fname, fname)
        layout.addWidget(self._copy_combo)

        # ---- 按钮 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn: QPushButton = QPushButton("创建")
        create_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        create_btn.setMinimumHeight(32)
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _on_create(self) -> None:
        """点击创建按钮。"""
        name: str = self._name_input.text().strip() if self._name_input else ''
        if not name:
            logger.warning("新建课程表：名称为空")
            return
        if not name.endswith('.json'):
            name += '.json'
        logger.info(f"新建课程表：名称={name}")
        self._result_name: str = name
        self._result_copy_from: str = (
            self._copy_combo.currentData() if self._copy_combo else ''
        )
        self.accept()

    def result_name(self) -> str:
        """返回用户输入的名称。"""
        return getattr(self, '_result_name', 'table_1.json')

    def result_copy_from(self) -> str:
        """返回选择的复制来源（空字符串表示空白）。"""
        return getattr(self, '_result_copy_from', '')


# ==================== 科目编辑子窗口 ====================


class SubjectEditDialog(ThemedDialog):
    """
    # SubjectEditDialog — 科目编辑子窗口（新建 / 编辑共用）

    字段：
      - 中文名（QLineEdit，必填）
      - 英文名（QLineEdit，可空；为空时窗口最下方显示翻译卡片）
      - 所属类别（QComboBox）

    规则：
      - 第一类别（Subject_Types 第一个键）为系统保护类别：
        新建科目时下拉框不提供该类别；编辑其中的科目时下拉框锁定。
      - 未输入中文名或未选择类别时无法创建科目。
      - 中文名不得与其他科目重名。
      - 英文名为空时显示翻译卡片：系统默认网站 + 连接状态 + 翻译状态
        + 翻译结果，可「填入英文名」/ 重新选择网站 / 翻译；
        点击「填入英文名」后翻译卡片保持显示，不会自动关闭。
    """

    def __init__(self, theme_manager: ThemeManager,
                 manager: SubjectConfigManager,
                 mode: str = 'create',
                 category: str = '',
                 name: str = '',
                 english_name: str = '',
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager # type: ignore
        self._manager: SubjectConfigManager = manager
        self._mode: str = mode
        self._initial_category: str = category
        self._initial_name: str = name
        self._initial_english: str = english_name

        # 用于校验的配置快照（从文件加载）
        self._config_data: Dict = manager.load()
        subject_types: Any = self._config_data.get('Subject_Types', {})
        all_cats: List[str] = (
            list(subject_types.keys())
            if isinstance(subject_types, dict) else []
        )
        # 第一类别 = 配置中第一个键（系统保护类别）
        self._protected_category: str = all_cats[0] if all_cats else ''

        self._worker: Optional[TranslateWorker] = None
        self._translate_running: bool = False
        self._result_text: str = ''
        self._result: dict = {}
        # 删除标记（仅编辑模式、非第一类别科目可用）
        self._deleted: bool = False

        self.setWindowTitle('编辑科目' if mode == 'edit' else '新建科目')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(440)

        self._setup_ui()
        logger.info(
            f"SubjectEditDialog 初始化完成（mode={mode}, "
            f"protected={self._protected_category}）"
        )

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        fc: str = self._theme.font_color
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ---- 中文名 ----
        cn_label: QLabel = QLabel("科目中文名：")
        cn_label.setFont(QFont("Microsoft YaHei", 12))
        cn_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(cn_label)

        self._name_input: QLineEdit = QLineEdit(self._initial_name)
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        self._name_input.setStyleSheet(self._field_style())
        layout.addWidget(self._name_input)

        # ---- 英文名 ----
        en_label: QLabel = QLabel("科目英文名：")
        en_label.setFont(QFont("Microsoft YaHei", 12))
        en_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(en_label)

        self._english_input: QLineEdit = QLineEdit(self._initial_english)
        self._english_input.setFont(QFont("Microsoft YaHei", 11))
        self._english_input.setMinimumHeight(32)
        self._english_input.setStyleSheet(self._field_style())
        layout.addWidget(self._english_input)

        # ---- 所属类别 ----
        cat_label: QLabel = QLabel("所属类别：")
        cat_label.setFont(QFont("Microsoft YaHei", 12))
        cat_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(cat_label)

        self._category_combo: QComboBox = QComboBox()
        self._category_combo.setFont(QFont("Microsoft YaHei", 11))
        self._category_combo.setMinimumHeight(32)
        self._category_combo.setStyleSheet(self._combo_style())
        self._populate_categories()
        layout.addWidget(self._category_combo)

        # ---- 翻译卡片（始终显示，便于随时翻译/重翻）----
        self._translation_card: QFrame = self._build_translation_card()
        layout.addWidget(self._translation_card)

        # ---- 按钮行 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)

        # 删除科目（仅编辑模式、且非第一类别保护科目时显示）
        self._delete_btn: QPushButton = QPushButton("删除科目")
        self._delete_btn.setFont(QFont("Microsoft YaHei", 11))
        self._delete_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._delete_btn.setMinimumHeight(32)
        self._delete_btn.setStyleSheet(self._danger_btn_style())
        self._delete_btn.setVisible(
            self._mode == 'edit'
            and bool(self._initial_category)
            and self._initial_category != self._protected_category
        )
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.setStyleSheet(self._normal_btn_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn: QPushButton = QPushButton("确认")
        confirm_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        confirm_btn.setMinimumHeight(32)
        confirm_btn.setStyleSheet(self._primary_btn_style())
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

        # ---- 联动 ----
        self._english_input.textChanged.connect(self._on_english_changed)
        # 输入框失去焦点时自动缩写超长的中 / 英文名
        self._name_input.editingFinished.connect(self._abbreviate_name_field)
        self._english_input.editingFinished.connect(self._abbreviate_english_field)
        # 英文名为空时打开即自动翻译（卡片始终显示，无需再控制显隐）
        if not self._initial_english.strip():
            self._start_translate()

        self.setLayout(layout)
        self.adjustSize()

    # ================================================================
    #  类别下拉框填充（第一类别保护规则）
    # ================================================================
    def _populate_categories(self) -> None:
        subject_types: Any = self._config_data.get('Subject_Types', {})
        if not isinstance(subject_types, dict):
            subject_types = {}
        # 可加入科目的类别：列表类别 + "None" 占位类别
        # （占位类别在首次加入科目时由调用方转为列表）
        selectable_cats: List[str] = [
            c for c, v in subject_types.items()
            if isinstance(v, list)
            or SubjectConfigManager.is_placeholder(v)
        ]

        if self._mode == 'edit' and \
                self._initial_category == self._protected_category:
            # 第一类别中的科目：锁定类别，不能移出
            self._category_combo.addItem(self._protected_category,
                                         self._protected_category)
            self._category_combo.setEnabled(False)
            return

        for cat in selectable_cats:
            if cat == self._protected_category:
                continue  # 任何科目都不能进入第一类别
            self._category_combo.addItem(cat, cat)

        if self._mode == 'edit':
            idx: int = self._category_combo.findData(self._initial_category)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)

    # ================================================================
    #  翻译卡片
    # ================================================================
    def _build_translation_card(self) -> QFrame:
        fc: str = self._theme.font_color
        card: QFrame = QFrame()
        if self._theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255,255,255,0.04)'
            card_border: str = 'rgba(33, 150, 243, 0.30)'
        else:
            card_bg = 'rgba(33, 150, 243, 0.04)'
            card_border = 'rgba(33, 150, 243, 0.25)'
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 10px;
            }}
        """)
        layout: QVBoxLayout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # ---- 翻译网站选择行 ----
        site_row: QHBoxLayout = QHBoxLayout()
        site_row.setSpacing(8)

        site_label: QLabel = QLabel("翻译网站：")
        site_label.setFont(QFont("Microsoft YaHei", 11))
        site_label.setStyleSheet(f"color: {fc}; background: transparent;")
        site_row.addWidget(site_label)

        self._site_combo: QComboBox = QComboBox()
        self._site_combo.setFont(QFont("Microsoft YaHei", 11))
        self._site_combo.setMinimumHeight(30)
        self._site_combo.setStyleSheet(self._combo_style())
        self._sites: List[Dict] = load_sites()
        default_site: str = get_default_site()
        for s in self._sites:
            self._site_combo.addItem(s['name'], s['id'])
        default_idx: int = self._site_combo.findData(default_site)
        if default_idx >= 0:
            self._site_combo.setCurrentIndex(default_idx)
        site_row.addWidget(self._site_combo, 1)

        self._translate_btn: QPushButton = QPushButton("翻译")
        self._translate_btn.setFont(QFont("Microsoft YaHei", 11))
        self._translate_btn.setMinimumHeight(30)
        self._translate_btn.setStyleSheet(self._normal_btn_style())
        self._translate_btn.clicked.connect(self._start_translate)
        site_row.addWidget(self._translate_btn)

        layout.addLayout(site_row)

        # ---- 状态与结果 ----
        self._conn_label: QLabel = QLabel("连接状态：—")
        self._status_label: QLabel = QLabel("翻译状态：—")
        self._result_label: QLabel = QLabel("翻译结果：—")
        for lbl in (self._conn_label, self._status_label, self._result_label):
            lbl.setFont(QFont("Microsoft YaHei", 10))
            lbl.setStyleSheet(f"color: {fc}; background: transparent;")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        # ---- 填入按钮 ----
        fill_row: QHBoxLayout = QHBoxLayout()
        fill_row.addStretch()
        self._fill_btn: QPushButton = QPushButton("填入英文名")
        self._fill_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        self._fill_btn.setMinimumHeight(30)
        self._fill_btn.setEnabled(False)
        self._fill_btn.setStyleSheet(self._primary_btn_style())
        self._fill_btn.clicked.connect(self._on_fill)
        fill_row.addWidget(self._fill_btn)
        layout.addLayout(fill_row)

        return card

    # ================================================================
    #  翻译流程
    # ================================================================
    def _on_english_changed(self, text: str) -> None:
        """英文名被清空时自动翻译；翻译卡片始终显示，不再因输入而隐藏。"""
        if not text.strip():
            self._start_translate()

    def _start_translate(self) -> None:
        """发起一次翻译（防重入）。"""
        if self._translate_running:
            return
        source: str = self._name_input.text().strip()
        if not source:
            self._conn_label.setText("连接状态：—")
            self._status_label.setText("翻译状态：等待输入中文名")
            self._result_label.setText("翻译结果：请先填写科目中文名")
            return
        site_id: str = self._site_combo.currentData() or 'google'
        self._result_text = ''
        self._conn_label.setText("连接状态：连接中…")
        self._status_label.setText("翻译状态：等待…")
        self._result_label.setText("翻译结果：—")
        self._fill_btn.setEnabled(False)
        self._translate_btn.setEnabled(False)
        self._site_combo.setEnabled(False)
        self._translate_running = True

        self._worker = TranslateWorker(source, site_id)
        self._worker.status_changed.connect(self._on_worker_status)
        self._worker.finished_ok.connect(self._on_translate_ok)
        self._worker.finished_fail.connect(self._on_translate_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_status(self, status: str) -> None:
        """工作线程状态信号 → 更新连接 / 翻译状态标签。"""
        if status == 'connecting':
            self._conn_label.setText("连接状态：连接中…")
        elif status == 'connected':
            self._conn_label.setText("连接状态：连接成功")
            self._status_label.setText("翻译状态：翻译中…")
        elif status == 'failed':
            self._conn_label.setText("连接状态：连接失败")

    def _on_translate_ok(self, result: str, duration: float) -> None:
        """翻译成功 → 显示结果并启用填入按钮。"""
        self._result_text = result
        self._status_label.setText("翻译状态：翻译完成")
        self._result_label.setText(
            f"翻译结果：{result}（耗时 {duration:.1f}s）"
        )
        self._fill_btn.setEnabled(True)

    def _on_translate_fail(self, error: str) -> None:
        """翻译失败 → 显示错误信息。"""
        self._status_label.setText("翻译状态：翻译失败")
        self._result_label.setText(f"翻译结果：{error}")

    def _on_worker_finished(self) -> None:
        """工作线程结束 → 恢复控件可用。"""
        self._translate_running = False
        self._translate_btn.setEnabled(True)
        self._site_combo.setEnabled(True)
        if self._worker is not None:
            worker = self._worker
            if worker in _ORPHAN_WORKERS:
                _ORPHAN_WORKERS.remove(worker)
            worker.deleteLater()
        self._worker = None

    def _on_fill(self) -> None:
        """把翻译结果填入英文名输入框，并检测缩写超长英文名（翻译卡片保持显示）。"""
        if self._result_text:
            self._english_input.setText(self._result_text)
            self._abbreviate_english_field()

    # ================================================================
    #  自动缩写（输入框失焦时触发，确认时兜底再执行一次）
    # ================================================================
    def _abbreviate_name_field(self) -> None:
        """中文名超过 7 个字符时自动截断到前 7 个字符。"""
        if self._name_input is None:
            return
        text: str = self._name_input.text().strip()
        abbr: str = abbreviate_chinese_name(text)
        if abbr != text:
            self._name_input.setText(abbr)

    def _abbreviate_english_field(self) -> None:
        """英文名超过 12 个字符（含空格与符号）时自动缩写。"""
        if self._english_input is None:
            return
        text: str = self._english_input.text().strip()
        if len(text) <= SUBJECT_EN_MAX_LEN:
            return
        abbr: str = abbreviate_english_name(text)
        if abbr != text:
            self._english_input.setText(abbr)

    # ================================================================
    #  确认 / 结果
    # ================================================================
    def _on_confirm(self) -> None:
        """校验并确认（需求：中文名与类别必填、不得重名）。"""
        # 直接点击「确认」时输入框可能未触发失焦，这里兜底再缩写一次
        self._abbreviate_name_field()
        self._abbreviate_english_field()

        name: str = self._name_input.text().strip()
        category: str = self._category_combo.currentData() or ''

        if not name:
            QMessageBox.warning(
                self, "无法创建科目", "请输入科目中文名后再创建。"
            )
            return
        if not category:
            QMessageBox.warning(
                self, "无法创建科目", "请选择所属类别后再创建。"
            )
            return

        # 重名检查（编辑自身除外）
        found = self._manager.find_subject(self._config_data, name)
        if found is not None:
            found_cat, _en = found
            is_self: bool = (
                self._mode == 'edit'
                and found_cat == self._initial_category
                and name == self._initial_name
            )
            if not is_self:
                QMessageBox.warning(
                    self, "无法创建科目",
                    f"科目「{name}」已存在于 {found_cat}，"
                    "请使用其他中文名。",
                )
                return

        self._result = {
            'name': name,
            'english_name': self._english_input.text().strip(),
            'category': category,
        }
        logger.info(f"SubjectEditDialog 确认：{self._result}")
        self.accept()

    def result(self) -> dict:  # type: ignore
        """返回编辑结果：{name, english_name, category}。"""
        return self._result

    # ================================================================
    #  删除科目
    # ================================================================
    def _on_delete(self) -> None:
        """确认并删除当前科目（仅编辑模式、非第一类别科目可触发）。"""
        reply: QMessageBox.StandardButton = QMessageBox.question(
            self, "删除科目",
            f"确定要删除科目「{self._initial_name}」吗？",
            QMessageBox.No | QMessageBox.Yes,  # type: ignore
            QMessageBox.No,  # type: ignore
        )
        if reply != QMessageBox.Yes:  # type: ignore
            return
        self._deleted = True
        self.accept()

    def deleted(self) -> bool:
        """返回是否请求删除科目。"""
        return self._deleted

    # ================================================================
    #  样式辅助
    # ================================================================
    def _field_style(self) -> str:
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = '#2d2d2d'
            border: str = 'rgba(255,255,255,0.14)'
        else:
            bg = '#FFFFFF'
            border = 'rgba(0,0,0,0.14)'
        return f"""
            QLineEdit {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
            }}
        """

    def _combo_style(self) -> str:
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = '#2d2d2d'
            border: str = 'rgba(255,255,255,0.14)'
        else:
            bg = '#FFFFFF'
            border = 'rgba(0,0,0,0.14)'
        return f"""
            QComboBox {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QComboBox:focus {{
                border-color: #2196F3;
            }}
            QComboBox QAbstractItemView {{
                color: {fc};
                background-color: {bg};
                selection-background-color: rgba(33, 150, 243, 0.25);
            }}
        """

    def _normal_btn_style(self) -> str:
        fc: str = self._theme.font_color
        if self._theme.theme == 'darkcolor':
            bg: str = 'rgba(255,255,255,0.06)'
            hover: str = 'rgba(255,255,255,0.12)'
        else:
            bg = 'rgba(0,0,0,0.04)'
            hover = 'rgba(0,0,0,0.08)'
        return f"""
            QPushButton {{
                color: {fc};
                background-color: {bg};
                border: 1px solid {self._theme.border_color};
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
        """

    def _primary_btn_style(self) -> str:
        return """
            QPushButton {
                color: white;
                background-color: #2196F3;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
            }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled {
                background-color: rgba(128, 128, 128, 0.4);
            }
        """

    def _danger_btn_style(self) -> str:
        """删除按钮样式：红字、透明底、红边框。"""
        return """
            QPushButton {
                color: #E53935;
                background-color: transparent;
                border: 1px solid #E53935;
                border-radius: 6px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: rgba(229, 57, 53, 0.12);
            }
        """

    # ================================================================
    #  关闭事件：取消进行中的翻译线程
    # ================================================================
    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭时取消翻译工作线程，避免后台线程残留。"""
        if self._worker is not None:
            self._worker.cancel()
            if self._worker.isRunning():
                # 线程仍在后台运行：移交孤儿池持有引用，
                # 防止 QThread 对象销毁时（线程未结束）导致 Qt 崩溃
                _ORPHAN_WORKERS.append(self._worker)
                self._worker.finished.connect(
                    lambda w=self._worker: _cleanup_orphan_worker(w)
                )
            self._worker = None
        super().closeEvent(event)


# ==================== 新建类别子窗口 ====================


class NewCategoryDialog(ThemedDialog):
    """
    # NewCategoryDialog — 新建类别子窗口

    用于为科目配置新增一个类别（初始为空列表）。
    名称要求：非空、不得与现有类别重名、不得为保留名称 "None"。
    """

    def __init__(self, theme_manager: ThemeManager,
                 existing: List[str],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager # type: ignore
        self._existing: List[str] = existing

        self.setWindowTitle('新建类别')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(360)

        self._name_input: Optional[QLineEdit] = None
        self._result_name: str = ''

        self._setup_ui()
        logger.info("NewCategoryDialog 初始化完成")

    def _setup_ui(self) -> None:
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        fc: str = self._theme.font_color

        name_label: QLabel = QLabel("类别名称：")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setStyleSheet(f"color: {fc}; background: transparent;")
        layout.addWidget(name_label)

        self._name_input = QLineEdit("")
        self._name_input.setFont(QFont("Microsoft YaHei", 11))
        self._name_input.setMinimumHeight(32)
        self._name_input.setStyleSheet(self._field_style())
        layout.addWidget(self._name_input)

        hint: QLabel = QLabel("提示：第一类别为系统保护类别，不受新建类别影响。")
        hint_font: QFont = QFont("Microsoft YaHei", 9)
        hint_font.setItalic(True)
        hint.setFont(hint_font)
        hint.setStyleSheet(
            f"color: {fc}; background: transparent; opacity: 0.6;"
        )
        layout.addWidget(hint)

        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn: QPushButton = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft YaHei", 11))
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn: QPushButton = QPushButton("创建")
        create_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))  # type: ignore
        create_btn.setMinimumHeight(32)
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _on_create(self) -> None:
        name: str = self._name_input.text().strip() if self._name_input else ''
        if not name:
            QMessageBox.warning(self, "无法创建类别", "请输入类别名称。")
            return
        if name.lower() == 'none' or name in self._existing:
            QMessageBox.warning(
                self, "无法创建类别",
                f"类别「{name}」已存在或为保留名称，请使用其他名称。",
            )
            return
        self._result_name = name
        self.accept()

    def result_name(self) -> str:
        """返回新建的类别名称。"""
        return self._result_name


# ==================== 显示规则（整合自 schedule_display_rules） ====================

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


def _clamp_int(value: Any, lo: int, hi: int) -> int:
    """把任意值安全转换为 [lo, hi] 区间内的整数；非法时回退到 lo。"""
    try:
        v: int = int(value)
    except (TypeError, ValueError):
        v = lo
    return max(lo, min(hi, v))


def _event_rule_summary(rule: Dict) -> str:
    """
    生成事件规则的可读摘要（用于列表按钮与日志）。
    -------------------------------------------------
    按 type 字段返回：
      daily   → 每天
      weekly  → 每周一 … 每周日
      monthly → 每月1日 … 每月31日
      yearly  → 每年1月1日 … 每年12月31日
      date    → 具体日期（YYYY-MM-DD）；旧格式规则（无 type）也按此处理
    """
    rtype: str = str(rule.get('type', '') or '').strip() or 'date'
    if rtype == 'daily':
        return '每天'
    if rtype == 'weekly':
        return f"每周{_WEEKDAY_SUFFIX[_clamp_int(rule.get('weekday'), 0, 6)]}"
    if rtype == 'monthly':
        return f"每月{_clamp_int(rule.get('day'), 1, 31)}日"
    if rtype == 'yearly':
        return (
            f"每年{_clamp_int(rule.get('month'), 1, 12)}月"
            f"{_clamp_int(rule.get('day'), 1, 31)}日"
        )
    return str(rule.get('date', '') or '')


def _replace_subject_in_curriculum_dict(curriculum: Dict, deleted_name: str,
                                        replacement: str = '语文') -> bool:
    """
    把课程表数据（星期 → 课时 → 科目名）中所有等于 deleted_name 的科目
    替换为 replacement（默认「语文」）。
    ------------------------------------
    参数：
        curriculum   （Dict）：课程表数据（如 {Monday: {lesson_1: "语文", ...}}）
        deleted_name （str）：被删除的科目名
        replacement  （str）：替换科目名，默认「语文」

    返回值：
        bool：是否发生了任何替换
    """
    changed: bool = False
    if not isinstance(curriculum, dict) or not deleted_name:
        return False
    for lessons in curriculum.values():
        if not isinstance(lessons, dict):
            continue
        for key, value in list(lessons.items()):
            if str(value).strip() == deleted_name:
                lessons[key] = replacement
                changed = True
    return changed


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
            arrow_bg: str = 'rgba(255, 255, 255, 0.06)'
            arrow_hover: str = 'rgba(255, 255, 255, 0.12)'
            text_hover: str = 'rgba(255, 255, 255, 0.08)'
        else:
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
                'QFrame { background-color: transparent; border: none; }'
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
        self._year_wheel.setFixedWidth(120)
        self._month_wheel.setFixedWidth(72)
        self._day_wheel.setFixedWidth(90)
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


class DisplayRuleListWidget(QFrame):
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
        self._list_layout.setContentsMargins(10, 10, 10, 10)
        self._list_layout.setSpacing(6)
        self.setObjectName('ruleListCard')
        self.refresh_theme()
        self.refresh()
        logger.info("DisplayRuleListWidget 初始化完成")

    # ================================================================
    #  刷新
    # ================================================================
    def refresh(self) -> None:
        """按优先级升序重建规则行列表。"""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget() # type: ignore
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
            self._list_layout.addStretch()
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
        if dialog.exec() == QDialog.Accepted: # type: ignore
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
        if dialog.exec() == QDialog.Accepted: # type: ignore
            result: dict = dialog.result()
            self._manager.add_rule(
                result['rule_text'],
                result['timetable'],
                result['curriculum'],
            )
            self.refresh()
            self.rules_changed.emit()

    def refresh_theme(self) -> None:
        theme = self._theme
        if theme.theme == 'darkcolor':
            bg: str = 'rgba(255, 255, 255, 0.04)'
            border: str = 'rgba(255, 255, 255, 0.10)'
        else:
            bg = 'rgba(0, 0, 0, 0.03)'
            border = 'rgba(0, 0, 0, 0.08)'
        self.setStyleSheet(
            f'#ruleListCard {{ background-color: {bg};'
            f' border: 1px solid {border}; border-radius: 8px; }}'
        )
        for _, row in self._rows:
            row.refresh_theme()


# ==================== 规则编辑子窗口 ====================


class RuleEditDialog(ThemedDialog):
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
        self._theme: ThemeManager = theme_manager # type: ignore
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


# ==================== 事件规则编辑子窗口 ====================


class EventRuleDialog(ThemedDialog):
    """
    # EventRuleDialog — 事件系统规则编辑子窗口

    用于新增或编辑一条事件规则：
      - 触发日期：每天 / 每周 / 每月 / 每年 / 具体时间点
        （参照显示规则子窗口的规则类型；除「每天」外均使用滚轮控件选择）
      - 时间（时/分滚轮）
      - 名称（文本框）
      - 编辑模式下提供「删除事件」按钮
    ---
    """

    def __init__(self, theme_manager: ThemeManager,
                 rule: Optional[Dict] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager # type: ignore
        self._rule: Optional[Dict] = rule
        self._deleted: bool = False

        self.setWindowTitle('编辑事件' if rule else '新建事件')
        self.setWindowFlags(
            Qt.Window                         # type: ignore
            | Qt.WindowCloseButtonHint        # type: ignore
        )
        self.setModal(True)
        self.setMinimumWidth(500)

        self._setup_ui()
        self._prefill()
        logger.info(
            f"EventRuleDialog 初始化完成（rule={'有' if rule else '无'}）"
        )

    # ================================================================
    #  主题颜色获取
    # ================================================================
    def _get_wheel_colors(self) -> tuple:
        """根据主题获取滚轮的背景色和文字色。"""
        if self._theme.theme == 'lightcolor':
            return '#FFFFFF', '#212121'
        elif self._theme.theme == 'darkcolor':
            return '#2d2d2d', '#E0E0E0'
        else:
            return self._theme.back_color, self._theme.font_color

    # ================================================================
    #  UI 构建
    # ================================================================
    def _setup_ui(self) -> None:
        """构造对话框布局。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        self.setStyleSheet(self._build_qss())
        bg, tc = self._get_wheel_colors()

        # ---- 卡片1：触发日期 ----
        date_card: QVBoxLayout = self._add_card("触发日期", layout)

        # 触发类型单选（参照显示规则子窗口的规则类型）
        self._daily_radio: QRadioButton = QRadioButton("每天")
        self._weekly_radio: QRadioButton = QRadioButton("每周")
        self._monthly_radio: QRadioButton = QRadioButton("每月")
        self._yearly_radio: QRadioButton = QRadioButton("每年")
        self._date_radio: QRadioButton = QRadioButton("具体时间点")
        for r in (self._daily_radio, self._weekly_radio, self._monthly_radio,
                  self._yearly_radio, self._date_radio):
            r.setFont(QFont("Microsoft YaHei", 11))

        radio_row: QHBoxLayout = QHBoxLayout()
        radio_row.setSpacing(16)
        for r in (self._daily_radio, self._weekly_radio, self._monthly_radio,
                  self._yearly_radio, self._date_radio):
            radio_row.addWidget(r)
        radio_row.addStretch()
        date_card.addLayout(radio_row)

        # 每天：无额外选择，仅提示
        self._daily_hint: QLabel = self._make_hint(
            "每天固定时间触发，只需设置下方时间"
        )
        date_card.addWidget(self._daily_hint)

        # 每周：星期滚轮（周一～周日）
        self._weekday_wheel: WheelColumn = WheelColumn(
            list(_WEEKDAY_LABELS), 0, bg_color=bg, text_color=tc,
        )
        self._weekday_wheel.setFixedSize(100, 150)
        date_card.addWidget(self._weekday_wheel, 0, Qt.AlignHCenter)  # type: ignore

        # 每月：日期滚轮（1日～31日）
        self._month_day_wheel: WheelColumn = WheelColumn(
            [f'{d}日' for d in range(1, 32)],
            0, bg_color=bg, text_color=tc,
        )
        self._month_day_wheel.setFixedSize(100, 150)
        date_card.addWidget(self._month_day_wheel, 0, Qt.AlignHCenter)  # type: ignore

        # 每年：月份 + 日期双滚轮（几月几号）
        self._year_month_wheel: WheelColumn = WheelColumn(
            [f'{m}月' for m in range(1, 13)],
            0, bg_color=bg, text_color=tc,
        )
        self._year_month_wheel.setFixedSize(80, 150)
        self._year_day_wheel: WheelColumn = WheelColumn(
            [f'{d}日' for d in range(1, 32)],
            0, bg_color=bg, text_color=tc,
        )
        self._year_day_wheel.setFixedSize(100, 150)

        yearly_row: QHBoxLayout = QHBoxLayout()
        yearly_row.setSpacing(4)
        yearly_row.setAlignment(Qt.AlignCenter)  # type: ignore
        yearly_row.addWidget(self._year_month_wheel)
        yearly_row.addWidget(self._year_day_wheel)
        date_card.addLayout(yearly_row)

        # 具体时间点：年/月/日滚轮
        self._date_wheel: DateWheelPicker = DateWheelPicker(
            self._theme, date.today()
        )
        date_card.addWidget(self._date_wheel, 0, Qt.AlignHCenter)  # type: ignore

        # ---- 卡片2：时间 ----
        time_card: QVBoxLayout = self._add_card("时间", layout)

        hour_items: List[str] = [f"{i:02d}" for i in range(24)]
        min_items: List[str] = [f"{i:02d}" for i in range(60)]
        self._hour_wheel: WheelColumn = WheelColumn(
            hour_items, 8, bg_color=bg, text_color=tc
        )
        self._hour_wheel.setFixedSize(70, 150)
        self._min_wheel: WheelColumn = WheelColumn(
            min_items, 0, bg_color=bg, text_color=tc
        )
        self._min_wheel.setFixedSize(70, 150)

        wheels_row: QHBoxLayout = QHBoxLayout()
        wheels_row.setSpacing(4)
        wheels_row.setAlignment(Qt.AlignCenter)  # type: ignore
        wheels_row.addWidget(self._hour_wheel)
        wheels_row.addWidget(self._make_sep(':'))
        wheels_row.addWidget(self._min_wheel)
        time_card.addLayout(wheels_row)

        # ---- 卡片3：名称 ----
        name_card: QVBoxLayout = self._add_card("名称", layout)
        self._name_edit: QLineEdit = QLineEdit()
        self._name_edit.setFont(QFont("Microsoft YaHei", 11))
        self._name_edit.setMinimumHeight(34)
        self._name_edit.setPlaceholderText("例如：早自习 / 考试 / 班会")
        name_card.addWidget(self._name_edit)

        # ---- 按钮行 ----
        btn_row: QHBoxLayout = QHBoxLayout()
        btn_row.setSpacing(12)

        self._delete_btn: QPushButton = QPushButton("删除事件")
        self._delete_btn.setFont(QFont("Microsoft YaHei", 11))
        self._delete_btn.setCursor(Qt.PointingHandCursor)  # type: ignore
        self._delete_btn.setMinimumHeight(34)
        self._delete_btn.setMinimumWidth(88)
        self._delete_btn.setProperty('class', 'danger')
        self._delete_btn.setVisible(self._rule is not None)
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

        # ---- 联动：类型单选切换可见控件 ----
        for r in (self._daily_radio, self._weekly_radio, self._monthly_radio,
                  self._yearly_radio, self._date_radio):
            r.toggled.connect(self._on_type_changed)

        self._daily_radio.setChecked(True)
        self._on_type_changed()

    # ================================================================
    #  样式 / 卡片辅助
    # ================================================================
    def _make_sep(self, text: str) -> QLabel:
        """创建时间滚轮分隔符标签（:）。"""
        _, tc = self._get_wheel_colors()
        sep_alpha: str = (
            "rgba(0,0,0,0.30)" if tc == '#212121'
            else "rgba(255,255,255,0.35)"
        )
        label: QLabel = QLabel(text)
        label.setFont(QFont('Arial', 22))
        label.setStyleSheet(
            f"color: {sep_alpha}; background: transparent;"
        )
        label.setAlignment(Qt.AlignCenter)  # type: ignore
        label.setFixedWidth(20)
        return label

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
        lbl.setAlignment(Qt.AlignCenter)  # type: ignore
        return lbl

    def _build_qss(self) -> str:
        """构建对话框 QSS 样式。"""
        theme = self._theme
        fc: str = theme.font_color
        if theme.theme == 'darkcolor':
            card_bg: str = 'rgba(255, 255, 255, 0.04)'
            card_border: str = 'rgba(255, 255, 255, 0.08)'
            field_bg: str = '#2d2d2d'
            field_border: str = 'rgba(255, 255, 255, 0.14)'
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
            QLineEdit {{
                background-color: {field_bg};
                color: {fc};
                border: 1px solid {field_border};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: {accent};
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
        """创建带标题的卡片容器，返回卡片内部布局。"""
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

    # ================================================================
    #  预填 / 事件处理
    # ================================================================
    def _prefill(self) -> None:
        """编辑模式下用规则数据预填控件。"""
        if not self._rule:
            return
        rule: Dict = self._rule
        rtype: str = str(rule.get('type', '') or '').strip() or 'date'

        if rtype == 'daily':
            self._daily_radio.setChecked(True)
        elif rtype == 'weekly':
            self._weekly_radio.setChecked(True)
            self._weekday_wheel.set_current_index(
                _clamp_int(rule.get('weekday'), 0, 6)
            )
        elif rtype == 'monthly':
            self._monthly_radio.setChecked(True)
            self._month_day_wheel.set_current_index(
                _clamp_int(rule.get('day'), 1, 31) - 1
            )
        elif rtype == 'yearly':
            self._yearly_radio.setChecked(True)
            self._year_month_wheel.set_current_index(
                _clamp_int(rule.get('month'), 1, 12) - 1
            )
            self._year_day_wheel.set_current_index(
                _clamp_int(rule.get('day'), 1, 31) - 1
            )
        else:
            self._date_radio.setChecked(True)
            date_str: str = str(rule.get('date', '') or '')
            try:
                d: date = date.fromisoformat(date_str)
                self._date_wheel.set_value(d)
            except (ValueError, TypeError):
                pass

        time_str: str = str(rule.get('time', '') or '')
        try:
            h, m = time_str.split(':')
            self._hour_wheel.set_current_index(int(h))
            self._min_wheel.set_current_index(int(m))
        except (ValueError, TypeError):
            pass

        self._name_edit.setText(str(rule.get('name', '') or ''))
        self._on_type_changed()

    def _on_type_changed(self, _checked: bool = False) -> None:
        """按当前选中的触发类型显示对应的日期控件。"""
        daily: bool = self._daily_radio.isChecked()
        weekly: bool = self._weekly_radio.isChecked()
        monthly: bool = self._monthly_radio.isChecked()
        yearly: bool = self._yearly_radio.isChecked()
        specific: bool = self._date_radio.isChecked()

        self._daily_hint.setVisible(daily)
        self._weekday_wheel.setVisible(weekly)
        self._month_day_wheel.setVisible(monthly)
        self._year_month_wheel.setVisible(yearly)
        self._year_day_wheel.setVisible(yearly)
        self._date_wheel.setVisible(specific)

    def _current_type(self) -> str:
        """返回当前选中的触发类型标识。"""
        if self._weekly_radio.isChecked():
            return 'weekly'
        if self._monthly_radio.isChecked():
            return 'monthly'
        if self._yearly_radio.isChecked():
            return 'yearly'
        if self._date_radio.isChecked():
            return 'date'
        return 'daily'

    def _on_confirm(self) -> None:
        """点击确定（校验名称非空）。"""
        if not self._name_edit.text().strip():
            QMessageBox.warning(
                self, "名称为空",
                "请输入事件名称。",
            )
            return
        logger.info("EventRuleDialog 确认")
        self.accept()

    def _on_delete(self) -> None:
        """删除当前事件（编辑模式下）。"""
        reply: QMessageBox.StandardButton = QMessageBox.question(
            self, "删除事件",
            "确定要删除这条事件规则吗？",
            QMessageBox.No | QMessageBox.Yes,  # type: ignore
            QMessageBox.No,  # type: ignore
        )
        if reply != QMessageBox.Yes:  # type: ignore
            return
        self._deleted = True
        self.accept()

    # ================================================================
    #  结果
    # ================================================================
    def result(self) -> dict:  # type: ignore
        """返回事件规则编辑结果（完整规则字典）。"""
        h: int = self._hour_wheel.current_index
        m: int = self._min_wheel.current_index
        rtype: str = self._current_type()
        rule: Dict = {
            'type': rtype,
            'date': '',
            'weekday': 0,
            'month': 1,
            'day': 1,
            'time': f"{h:02d}:{m:02d}",
            'name': self._name_edit.text().strip(),
        }
        if rtype == 'weekly':
            rule['weekday'] = self._weekday_wheel.current_index
        elif rtype == 'monthly':
            rule['day'] = self._month_day_wheel.current_index + 1
        elif rtype == 'yearly':
            rule['month'] = self._year_month_wheel.current_index + 1
            rule['day'] = self._year_day_wheel.current_index + 1
        elif rtype == 'date':
            d: date = self._date_wheel.value()
            rule['date'] = d.strftime('%Y-%m-%d')
        return rule

    def deleted(self) -> bool:
        """返回是否请求删除。"""
        return self._deleted
