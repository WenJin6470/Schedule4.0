"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_countdown.py（高考倒计时模块）         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
实现「高考倒计时」无边框悬浮窗口：
  ✅ 白底半透明无边框小窗，展示「距离 XXXX 年高考还有 N 天」
  ✅ 年级 / 班级来源优先级：本机注册表（Digital Class 客户端写入）
     → 失败时回退到调用方传入的 ini 配置（默认高一一班）
  ✅ 支持鼠标拖拽移动、Esc 关闭

🔌 适配说明（临时加入课表项目，后期会单独分出去）
═══════════════════════════════════════════════════════════════════════════
本模块刻意保持独立：
  - 不 import 课表项目任何内部模块，仅依赖 PySide6 与标准库；
  - 年级 / 班级 / 屏幕尺寸均以参数方式传入，由调用方从主配置读取；
  - 提供 open_countdown_window() 便捷入口与 main() 独立运行入口，
    后期可直接将本文件整体拷贝为独立小工具。
"""

import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QLabel, QVBoxLayout, QWidget,
)

# 注册表路径：Digital Class 客户端写入年级/班级的位置（与旧版 tkinter 参考代码一致）
REGISTRY_ROOT_PATH = r'Software\Combox\Digital Class\Frile\Friles'


# ================================================================
#  注册表读取
# ================================================================
def read_grade_class_from_registry():
    """
    从本机注册表读取年级 / 班级。
    ---------------------------------
    返回值：
        (grade, class_) 读取成功返回整数元组；失败或非 Windows 返回 (None, None)
    """
    try:
        import winreg
    except ImportError:
        return None, None

    grade = None
    cls = None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_ROOT_PATH, 0, winreg.KEY_READ
        ) as key:
            i: int = 0
            while True:
                try:
                    value_name, value_data, _ = winreg.EnumValue(key, i)
                    if value_name == 'Grade':
                        grade = value_data
                    elif value_name == 'Class':
                        cls = value_data
                    i += 1
                except OSError:
                    break
    except (FileNotFoundError, OSError):
        pass

    try:
        grade = int(grade) if grade is not None else None
    except (TypeError, ValueError):
        grade = None
    try:
        cls = int(cls) if cls is not None else None
    except (TypeError, ValueError):
        cls = None

    return grade, cls


# ================================================================
#  高考年份计算
# ================================================================
def compute_gk_year(grade: int) -> int:
    """
    根据当前年级计算对应的高考年份。
    ---------------------------------
    参数：
        grade（int）：当前年级（1=高一，2=高二，3=高三）

    规则（与旧版参考代码一致）：
      - 高一/高二：8 月前（暑假前）按当年算，8 月后（升年级后）按下一学年算；
      - 高三：6 月 12 日前为当年高考，之后为次年高考。
    """
    now = datetime.now()
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        grade = 1

    if grade in (1, 2):
        if now.month < 8:
            return now.year + (3 - grade)
        return now.year + (4 - grade)

    if grade == 3:
        june_12 = datetime(now.year, 6, 12)
        if now < june_12:
            return now.year + (3 - 3)   # 当年高考
        return now.year + (4 - 3)       # 次年高考

    # 非法年级兜底：按高一一班处理
    if now.month < 8:
        return now.year + 2
    return now.year + 3


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
        grade（int）：  年级（1=高一 2=高二 3=高三），注册表读取失败时使用
        class_（int）： 班级，注册表读取失败时使用
        screen_width / screen_height（int）：屏幕分辨率（用于按比例定位）
        opacity（float）：窗口透明度（默认 0.7，与旧版一致）
        use_registry（bool）：是否优先从注册表读取年级/班级（默认 True）
    """

    def __init__(
        self,
        grade: int = 1,
        class_: int = 1,
        screen_width: int = 1920,
        screen_height: int = 1080,
        opacity: float = 0.7,
        use_registry: bool = True,
        parent: QWidget = None,  # type: ignore
    ) -> None:
        super().__init__(parent)

        self._grade: int = grade
        self._class: int = class_

        # 优先从注册表读取年级/班级，失败则使用传入值（ini 配置兜底）
        if use_registry:
            reg_grade, reg_class = read_grade_class_from_registry()
            if reg_grade is not None:
                self._grade = reg_grade
            if reg_class is not None:
                self._class = reg_class

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
        """设置无边框 / 半透明 / 白底 / 置顶等窗口属性。"""
        self.setWindowFlags(
            Qt.FramelessWindowHint  # type: ignore
            | Qt.WindowStaysOnTopHint  # type: ignore
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
    #  构建界面（与参考代码三标签布局一致）
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        """构建窗口内容：占位标签 + 标题标签 + 天数标签（占满剩余空间）。"""
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 占位标签（顶部留白，参考代码 label0）
        self._label_placeholder = QLabel('', self)
        self._label_placeholder.setFont(QFont('微软雅黑', 10))
        self._label_placeholder.setAlignment(
            Qt.AlignCenter  # type: ignore
        )
        layout.addWidget(self._label_placeholder)

        # 标题标签：距离 XXXX 年高考还有
        self._label_title = QLabel('', self)
        self._label_title.setFont(QFont('微软雅黑', 25))
        self._label_title.setStyleSheet(
            "color: black; background: transparent;"
        )
        self._label_title.setAlignment(
            Qt.AlignCenter  # type: ignore
        )
        layout.addWidget(self._label_title)

        # 天数标签：N 天（红色，占满剩余空间，对应 fill=BOTH expand=True）
        self._label_days = QLabel('', self)
        self._label_days.setFont(QFont('微软雅黑', 40))
        self._label_days.setStyleSheet(
            "color: red; background: transparent;"
        )
        self._label_days.setAlignment(
            Qt.AlignCenter  # type: ignore
        )
        layout.addWidget(self._label_days, 1)

    # ----------------------------------------------------------------
    #  刷新内容
    # ----------------------------------------------------------------
    def set_grade_class(self, grade: int, class_: int) -> None:
        """更新年级/班级（注册表读取失败回退时使用），下次刷新内容生效。"""
        try:
            self._grade = int(grade)
        except (TypeError, ValueError):
            self._grade = 1
        try:
            self._class = int(class_)
        except (TypeError, ValueError):
            self._class = 1

    def _update_content(self) -> None:
        """根据年级计算高考年份与剩余天数并刷新标签。"""
        gk_year: int = compute_gk_year(self._grade)
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
_ACTIVE_WINDOW = None  # type: Optional[GaokaoCountdownWindow]


def show_countdown_window(
    grade: int = 1,
    class_: int = 1,
    screen_width: int = 1920,
    screen_height: int = 1080,
    opacity: float = 0.7,
    use_registry: bool = True,
) -> GaokaoCountdownWindow:
    """
    打开高考倒计时窗口（单例）。
    ----------------------------
    若窗口实例已存在则更新参数并重新显示，否则创建新实例。
    参数见 GaokaoCountdownWindow；返回窗口实例。
    """
    global _ACTIVE_WINDOW
    if _ACTIVE_WINDOW is not None:
        _ACTIVE_WINDOW.set_grade_class(grade, class_)
        _ACTIVE_WINDOW._update_content()
        _ACTIVE_WINDOW.show()
        _ACTIVE_WINDOW.raise_()
        _ACTIVE_WINDOW.activateWindow()
        return _ACTIVE_WINDOW

    win = GaokaoCountdownWindow(
        grade=grade,
        class_=class_,
        screen_width=screen_width,
        screen_height=screen_height,
        opacity=opacity,
        use_registry=use_registry,
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
    grade: int = 1,
    class_: int = 1,
    screen_width: int = 1920,
    screen_height: int = 1080,
    opacity: float = 0.7,
    use_registry: bool = True,
) -> GaokaoCountdownWindow:
    """
    创建并显示高考倒计时窗口（兼容旧入口，转发到单例实现）。
    -------------------------
    参数见 GaokaoCountdownWindow；返回窗口实例供调用方持有（防止被回收）。
    """
    return show_countdown_window(
        grade=grade,
        class_=class_,
        screen_width=screen_width,
        screen_height=screen_height,
        opacity=opacity,
        use_registry=use_registry,
    )


# ================================================================
#  独立运行入口（便于后期单独分出去调试/使用）
# ================================================================
def main() -> None:
    """独立运行：从注册表读取年级/班级，失败回退到默认高一一班。"""
    app: QApplication = QApplication(sys.argv)
    screen = app.primaryScreen()
    sw: int = screen.size().width() if screen is not None else 1920
    sh: int = screen.size().height() if screen is not None else 1080
    win = open_countdown_window(
        grade=1, class_=1,
        screen_width=sw, screen_height=sh,
        use_registry=True,
    )
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
