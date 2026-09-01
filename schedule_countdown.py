"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_countdown.py（高考倒计时模块）         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
实现「高考倒计时」无边框悬浮窗口：
  ✅ 白底半透明无边框小窗，展示「距离 XXXX 年高考还有 N 天」
  ✅ 高考年份：由设置页 / 主配置直接指定（不再从注册表读取年级/班级）
  ✅ 每年 8 月 1 日自动把选中的高考年份向后推一年，且当天只推一次
  ✅ 支持鼠标拖拽移动、Esc 关闭
  ✅ 适配 2K 等高分屏：按屏幕分辨率等比放大字号，并使两行文字垂直居中

🔌 适配说明（临时加入课表项目，后期会单独分出去）
═══════════════════════════════════════════════════════════════════════════
本模块刻意保持独立：
  - 不 import 课表项目任何内部模块，仅依赖 PySide6 与标准库；
  - 高考年份 / 屏幕尺寸均以参数方式传入，由调用方从主配置读取；
  - 提供 open_countdown_window() 便捷入口与 main() 独立运行入口，
    后期可直接将本文件整体拷贝为独立小工具。
"""

import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QLabel, QVBoxLayout, QWidget,
)


# ================================================================
#  高考年份范围
# ================================================================
# 设置页可选的高考年份：从 2026 年开始，向后共 50 年（2026 ~ 2075）
GK_YEAR_START: int = 2026
GK_YEAR_COUNT: int = 50
GK_YEAR_END: int = GK_YEAR_START + GK_YEAR_COUNT - 1  # 2075


def gk_year_options():
    """返回可选的高考年份列表（2026 ~ 2075，共 50 年）。"""
    return list(range(GK_YEAR_START, GK_YEAR_END + 1))


def default_gk_year() -> int:
    """返回默认高考年份：最近一个尚未到来的高考年份（6 月 7 日）。

    若今年的 6 月 7 日已过（或在当天之前），则指向下一年；结果会被
    夹取到可选范围 [GK_YEAR_START, GK_YEAR_END] 内。
    """
    today = datetime.now()
    year: int = today.year
    if today > datetime(year, 6, 7):
        year += 1
    return max(GK_YEAR_START, min(year, GK_YEAR_END))


# ================================================================
#  高考年份自动滚动（每年 8 月 1 日 +1，当天只推一次）
# ================================================================
def resolve_gk_year(
    stored_year: int,
    last_modified: str = '',
    today: datetime = None,
):  # type: ignore
    """
    应用「每年 8 月 1 日自动把高考年份向后推一年」规则。
    ------------------------------------------------
    参数：
        stored_year（int）：  当前存储的高考年份
        last_modified（str）：最后一次「修改年份」的日期（YYYY-MM-DD），
                          既包含用户的主动修改，也包含本规则的自动修改；
                          用于保证在 8 月 1 日当天只能推一年。
        today（datetime）：   当前日期（可注入以便测试，默认 datetime.now()）

    规则：
      - 仅当 today 为 8 月 1 日且 last_modified 不等于 today 时，把年份 +1；
      - 超过可选范围上限（GK_YEAR_END）时封顶，不再继续增大；
      - 其余情况保持原值不变。

    返回值：
        (resolved_year, new_last_modified)
    """
    if today is None:
        today = datetime.now()
    try:
        stored_year = int(stored_year)
    except (TypeError, ValueError):
        stored_year = GK_YEAR_START

    # 先夹取到合法范围内，避免异常配置导致越界
    stored_year = max(GK_YEAR_START, min(stored_year, GK_YEAR_END))

    if today.month == 8 and today.day == 1:
        today_str: str = today.strftime('%Y-%m-%d')
        if last_modified != today_str:
            new_year: int = min(stored_year + 1, GK_YEAR_END)
            return new_year, today_str

    return stored_year, last_modified


# ================================================================
#  高考剩余天数计算
# ================================================================
def compute_countdown_days(gk_year: int) -> int:
    """计算距离 gk_year 年 6 月 7 日（高考首日）的天数；已过则为 0。"""
    today = datetime.now()
    target = datetime(gk_year, 6, 7)
    days: int = (target - today).days
    return max(days, 0)


# ================================================================
#  高考倒计时窗口
# ================================================================
class GaokaoCountdownWindow(QWidget):
    """
    高考倒计时无边框悬浮窗口（PySide6 版）。
    ---------------------------------------
    参数：
        gk_year（int）：      高考年份（如 2026 ~ 2075），由调用方从主配置读取
        screen_width / screen_height（int）：屏幕分辨率（用于按比例定位与放大字号）
        opacity（float）：窗口透明度（默认 0.7，与旧版一致）
    """

    def __init__(
        self,
        gk_year: int = GK_YEAR_START,
        screen_width: int = 1920,
        screen_height: int = 1080,
        opacity: float = 0.7,
        parent: QWidget = None,  # type: ignore
    ) -> None:
        super().__init__(parent)

        self._gk_year: int = gk_year
        self._screen_width: int = screen_width
        self._screen_height: int = screen_height
        self._opacity: float = opacity
        self._drag_offset = None  # type: ignore

        self._setup_window()
        self._build_ui()
        self._update_content()

    # ----------------------------------------------------------------
    #  窗口属性
    # ----------------------------------------------------------------
    def _setup_window(self) -> None:
        """设置无边框 / 半透明 / 白底 / 不进任务栏等窗口属性。"""
        self.setWindowFlags(
            Qt.FramelessWindowHint  # type: ignore
            | Qt.Tool  # type: ignore   # Tool 窗口不显示在任务栏
        )
        self.setWindowOpacity(self._opacity)
        self.setAttribute(Qt.WA_TranslucentBackground, False)  # type: ignore
        self.setAutoFillBackground(True)
        self.setStyleSheet("background-color: white;")

        # 尺寸与位置：按参考代码的比例（以 1920 宽为基准）
        win_w: int = int(self._screen_width * (635 / 1920))
        win_h: int = int(self._screen_height * (400 / 1920))
        pos_x: int = int(self._screen_width * (1105 / 1920))
        pos_y: int = int(self._screen_height * (200 / 1920))
        self.setGeometry(pos_x, pos_y, win_w, win_h)

    # ----------------------------------------------------------------
    #  构建界面（两个标签在窗口内垂直居中，字号随屏幕分辨率等比放大）
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        """构建窗口内容：标题标签 + 天数标签，并整体垂直居中。

        说明：以 1920×1080 为基准，按屏幕分辨率等比放大字号（2K 2560×1440
        ≈ 1.33 倍，4K ≈ 2 倍），从而保证高分屏下文字相对窗口不再偏小；
        上下各放一个伸缩项，使两行文字作为一个整体在窗口内垂直居中。
        """
        # 缩放系数：以 1920×1080 为基准，随屏幕分辨率等比放大（限制在 [1.0, 2.0]）
        scale: float = min(
            self._screen_width / 1920.0,
            self._screen_height / 1080.0,
        )
        scale = max(1.0, min(scale, 2.0))

        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(8 * scale))

        # 顶部伸缩项：与底部伸缩项等大，使中间内容整体垂直居中
        layout.addStretch(1)

        # 标题标签：距离 XXXX 年高考还有
        self._label_title = QLabel('', self)
        self._label_title.setFont(QFont('微软雅黑', int(25 * scale)))
        self._label_title.setStyleSheet(
            "color: black; background: transparent;"
        )
        self._label_title.setAlignment(
            Qt.AlignCenter  # type: ignore
        )
        layout.addWidget(self._label_title, 0, Qt.AlignCenter)  # type: ignore

        # 天数标签：N 天（红色）
        self._label_days = QLabel('', self)
        self._label_days.setFont(QFont('微软雅黑', int(40 * scale)))
        self._label_days.setStyleSheet(
            "color: red; background: transparent;"
        )
        self._label_days.setAlignment(
            Qt.AlignCenter  # type: ignore
        )
        layout.addWidget(self._label_days, 0, Qt.AlignCenter)  # type: ignore

        # 底部伸缩项：与顶部伸缩项等大
        layout.addStretch(1)

    # ----------------------------------------------------------------
    #  刷新内容
    # ----------------------------------------------------------------
    def set_gk_year(self, gk_year: int) -> None:
        """更新高考年份，下次刷新内容生效。"""
        try:
            self._gk_year = int(gk_year)
        except (TypeError, ValueError):
            self._gk_year = GK_YEAR_START

    def _update_content(self) -> None:
        """根据高考年份计算剩余天数并刷新标签。"""
        gk_year: int = self._gk_year
        days: int = compute_countdown_days(gk_year)
        self._label_title.setText(f'距离{gk_year}年高考还有')
        self._label_days.setText(f'{days}天')

    # ----------------------------------------------------------------
    #  交互：拖拽移动 + Esc 关闭
    # ----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # type: ignore
        """记录拖拽起点（左键）。"""
        if event.button() == Qt.LeftButton:  # type: ignore
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore
        """按住左键拖动窗口。"""
        if self._drag_offset is not None and (
            event.buttons() & Qt.LeftButton  # type: ignore
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore
        """释放拖拽。"""
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore
        """Esc 关闭窗口。"""
        if event.key() == Qt.Key_Escape:  # type: ignore
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore
        """关闭时清理模块级单例引用，保证再次打开时重建。"""
        global _ACTIVE_WINDOW
        if _ACTIVE_WINDOW is self:
            _ACTIVE_WINDOW = None
        super().closeEvent(event)


# ================================================================
#  便捷入口（单例管理，全局只有一个倒计时窗口实例）
# ================================================================
# 模块级单例引用：避免 main.py 启动实例与设置页开关实例重复创建
_ACTIVE_WINDOW = None  # type: ignore


def show_countdown_window(
    gk_year: int = GK_YEAR_START,
    screen_width: int = 1920,
    screen_height: int = 1080,
    opacity: float = 0.7,
) -> GaokaoCountdownWindow:
    """
    打开高考倒计时窗口（单例）。
    ----------------------------
    若窗口实例已存在则更新参数并重新显示，否则创建新实例。
    参数见 GaokaoCountdownWindow；返回窗口实例。
    """
    global _ACTIVE_WINDOW
    if _ACTIVE_WINDOW is not None:
        _ACTIVE_WINDOW.set_gk_year(gk_year)
        _ACTIVE_WINDOW._update_content()
        _ACTIVE_WINDOW.show()
        _ACTIVE_WINDOW.raise_()
        _ACTIVE_WINDOW.activateWindow()
        return _ACTIVE_WINDOW

    win = GaokaoCountdownWindow(
        gk_year=gk_year,
        screen_width=screen_width,
        screen_height=screen_height,
        opacity=opacity,
    )
    _ACTIVE_WINDOW = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def hide_countdown_window() -> None:
    """关闭高考倒计时窗口（单例）：隐藏并释放实例。"""
    global _ACTIVE_WINDOW
    if _ACTIVE_WINDOW is not None:
        _ACTIVE_WINDOW.close()
        _ACTIVE_WINDOW = None


def get_countdown_window():
    """返回当前倒计时窗口实例（可能为 None）。"""
    return _ACTIVE_WINDOW


def open_countdown_window(
    gk_year: int = GK_YEAR_START,
    screen_width: int = 1920,
    screen_height: int = 1080,
    opacity: float = 0.7,
) -> GaokaoCountdownWindow:
    """
    创建并显示高考倒计时窗口（兼容旧入口，转发到单例实现）。
    -------------------------
    参数见 GaokaoCountdownWindow；返回窗口实例供调用方持有（防止被回收）。
    """
    return show_countdown_window(
        gk_year=gk_year,
        screen_width=screen_width,
        screen_height=screen_height,
        opacity=opacity,
    )


# ================================================================
#  独立运行入口（便于后期单独分出去调试/使用）
# ================================================================
def main() -> None:
    """独立运行：默认显示当前可用的高考年份，并在 8 月 1 日自动 +1。"""
    app: QApplication = QApplication(sys.argv)
    screen = app.primaryScreen()
    sw: int = screen.size().width() if screen is not None else 1920
    sh: int = screen.size().height() if screen is not None else 1080
    gk_year, _ = resolve_gk_year(default_gk_year(), '', datetime.now())
    win = open_countdown_window(
        gk_year=gk_year,
        screen_width=sw,
        screen_height=sh,
    )
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
