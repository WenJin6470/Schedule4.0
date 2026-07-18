"""
╔══════════════════════════════════════════════════════════════════════════╗
║            📅 电子课表系统 —— schedule_frontend.py（前端窗口）            ║
║                      （前后端分离架构 · 前端部分）                         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件是前后端分离架构中的【前端部分】，负责：
  ✅ 从 Config/schedule_config.ini 读取课时数量配置
  ✅ 画出时间窗口和科目显示窗口
  ✅ 根据配置动态创建对应数量的课时标签控件
  ✅ 创建关闭按钮（位于所有标签下方）并捕获用户点击
  ✅ 提供公开方法供后端调用来更新时间显示和修改特定标签内容

本文件不包含任何业务逻辑（不管理定时器、不判断何时关闭），
所有业务判断都交给 schedule_backend.py 处理。

📌 设计理念
═══════════════════════════════════════════════════════════════════════════
  前端 ≈ 餐厅的服务员
  - 服务员只负责：递菜单、记菜名、端菜上桌
  - 服务员不管：菜怎么做、火候多少、放多少盐（那是厨师的事）

  【信号 Signal】≈ 服务员喊"客人要关窗了！"
  【公开方法】  ≈ 厨师喊"时间到了，把钟调一下！"
"""

import logging
import os
from configparser import ConfigParser
from typing import List, Optional, Tuple

from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent

# 获取本模块的 logger，日志将传播到 main.py 配置的根 logger
logger: logging.Logger = logging.getLogger(__name__)


# ==================== 辅助函数 ====================

def get_color(x: int, y: int) -> Tuple[int, int, int]:
    """
    获取屏幕上 (x, y) 坐标处像素的 RGB 颜色。
    ---------------------------------------
    通过截取整个屏幕后取指定坐标的像素颜色，
    比 grabWindow(0, x, y, 1, 1) 更可靠，避免高 DPI 或
    多屏幕时的坐标偏移问题。

    参数：
        x（int）：屏幕 X 坐标
        y（int）：屏幕 Y 坐标

    返回值：
        Tuple[int, int, int]：（R, G, B）颜色值，范围 0-255
    """
    screen = QApplication.primaryScreen()
    if screen is None:
        return (128, 128, 128)

    # 确保坐标在有效范围内
    geo = screen.geometry()
    x = max(0, min(x, geo.width() - 1))
    y = max(0, min(y, geo.height() - 1))

    pixmap = screen.grabWindow(0)  # 截取整个桌面
    image = pixmap.toImage()
    color = image.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


def RGB_to_Hex(rgb: Tuple[int, int, int]) -> str:
    """
    将 RGB 元组转换为十六进制颜色字符串。
    ----------------------------------
    参数：
        rgb（Tuple[int, int, int]）：RGB 颜色元组

    返回值：
        str：十六进制颜色字符串，格式 #RRGGBB
    """
    return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])


def is_color_dark(hex_color: str) -> bool:
    """
    判断一个十六进制颜色是否为深色。
    -----------------------------
    使用亮度公式：brightness = (R*299 + G*587 + B*114) / 1000
    亮度 < 128 视为深色，字体应使用白色；否则使用黑色。

    参数：
        hex_color（str）：十六进制颜色字符串，如 "#1a2b3c"

    返回值：
        bool：True 表示深色，False 表示浅色
    """
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    return brightness < 128


# ==================== 辅助窗口类（paintEvent 背景填充）====================

class _RootWindow(QWidget):
    """
    科目显示窗口 — 通过 paintEvent 直接绘制背景色。
    比样式表/QPalette 更可靠，不受平台/主题影响。
    """

    def __init__(self, bg_hex: str = '#ffffff') -> None:
        super().__init__()
        self._bg_color: QColor = QColor(bg_hex)

    def set_bg_color(self, bg_hex: str) -> None:
        """动态更新背景颜色并立即重绘。"""
        self._bg_color = QColor(bg_hex)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """直接填充背景色 —— 最可靠的 QWidget 背景实现方式。"""
        painter: QPainter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)


# ==================== 前端窗口类 ====================

class ScheduleClassroomFrontend(QWidget):
    """
    # ScheduleClassroomFrontend — 电子课表前端窗口类

    继承自 QWidget，负责创建和显示所有 UI 元素。
    ---

    包含两个窗口：
      1. 时间窗口（self）  —— 显示实时时间，位于屏幕右上角
      2. 科目显示窗口（self.root）—— 显示科目信息，位于时间窗口下方

    对外提供两类接口：
      1. 【信号（Signal）】   —— 用户做了什么 → 通知后端
      2. 【公开方法（Method）】—— 后端想更新什么 → 前端刷新界面

    参数：
        language（str）：语言类型（兜底默认值，会被配置文件覆盖）
        theme   （str）：主题类型（兜底默认值，会被配置文件覆盖）

    注意：
        实际生效的 language 和 theme 由 Config/schedule_config.ini
        中的配置决定。构造函数参数仅在配置文件读取失败时作为兜底。
    """

    # ================================================================
    #  信号定义区（Signal）
    #  ------------------
    #  信号是 PySide6 的核心通信机制，可以理解为"广播"。
    #  前端只负责"发射"信号，不关心谁在听、听了之后干什么。
    #  后端通过 main.py 连接这些信号，收到信号后执行业务逻辑。
    #
    #  打个比方：信号就像餐厅服务员对着后厨喊的单子
    #  "客人点了关闭！"——喊完就完了，怎么关窗是后面的事。
    # ================================================================

    # 信号：关闭请求 —— 用户点击了关闭（×）按钮
    # 参数：无
    close_requested = Signal()

    # ================================================================
    #  构造函数（初始化窗口）
    # ================================================================
    def __init__(self, language: str = 'chinese', theme: str = 'multicolor') -> None:
        """
        初始化电子课表前端窗口。
        -----------------------
        执行顺序：
          1. 获取屏幕尺寸，计算窗口大小和位置
          2. 设置默认主题和语言（由配置文件覆盖）
          3. 读取 Config/schedule_config.ini 配置文件
             └─ _apply_theme() 根据 theme 参数决定窗口背景色
          4. 创建所有 UI 元素（时间窗口、课时标签、关闭按钮）

        参数：
            language（str）：语言兜底默认值，会被配置文件中的 language 覆盖
            theme   （str）：主题兜底默认值，会被配置文件中的 theme 覆盖
                            配置文件可选值：'lightcolor' / 'darkcolor' / 'multicolor'
        """
        super().__init__()

        logger.info("=" * 50)
        logger.info("ScheduleClassroomFrontend 初始化开始")
        logger.info(f"  兜底参数：language={language}, theme={theme}")

        # ===== 第1步：获取屏幕尺寸 =====
        screen = QApplication.primaryScreen()
        if screen is None:
            # 极端情况：没有检测到屏幕，使用默认值
            logger.warning("未检测到屏幕，使用默认分辨率 1920×1080")
            self.screenWidth: int = 1920
            self.screenHeight: int = 1080
        else:
            self.screenWidth: int = screen.size().width()
            self.screenHeight: int = screen.size().height()
            logger.info(f"屏幕分辨率：{self.screenWidth}×{self.screenHeight}")

        # 注意：不能命名为 self.width，否则会覆盖 QWidget.width() 方法
        self.win_width: float = self.screenWidth * (150 / 1920)       # 两个窗口的宽度
        self.height_time: float = self.screenHeight / 26              # 时间窗口高度
        self.height_root: float = self.screenHeight / 13 * 11         # 科目显示窗口高度

        # 时间窗口位置（屏幕右上角区域）
        self.left_time: int = int(self.screenWidth * (1765 / 1920))
        self.top_time: int = int(self.screenHeight * (45 / 1080))

        # 科目显示窗口位置（时间窗口下方）
        self.left_root: int = int(self.screenWidth * (1765 / 1920))
        self.top_root: int = int(self.screenHeight / 12)

        logger.info(f"窗口尺寸计算完成：时间窗口 {self.win_width:.0f}×{self.height_time:.0f}，"
                    f"科目窗口 {self.win_width:.0f}×{self.height_root:.0f}")

        # ===== 第2步：初始化默认主题和语言（由配置文件覆盖）=====
        # 以下默认值会在 _load_config() 中被配置文件的值覆盖
        # 仅在配置文件不存在或读取失败时作为兜底
        self.language: str = language       # 语言：构造函数参数 → 配置文件覆盖
        self.theme: str = theme             # 主题：构造函数参数 → 配置文件覆盖
        self.back_color: str = 'white'             # 时间窗口背景颜色（兜底默认：白色）
        self.root_back_color: str = 'white'      # 科目窗口背景颜色（兜底默认：白色；深色模式下比时间窗口更深一层）
        self.font_color: str = 'black'           # 字体颜色（兜底默认：黑色）
        self.time_color: str = '#FF0000'         # 时间标签文字颜色（兜底默认：红色）
        self.border_color: str = 'rgba(128, 128, 128, 0.15)'  # 课时标签分割线颜色
        self.window_opacity: float = 0.7         # 窗口透明度（深色模式下提高至 0.85）

        # 语言反射标志（保留兼容）
        self.language_reflect: bool = True

        # 控件引用（初始为 None，在 _setup_ui 中创建）
        self.root: Optional[QWidget] = None
        self.close_btn: Optional[QPushButton] = None
        self.time_label: Optional[QLabel] = None

        # ===== 课时标签列表 =====
        # 每个标签控件按索引存储在列表中，通过 get_period_label(index) 获取
        self.period_labels: List[QLabel] = []
        self.period_count: int = 0  # 从配置文件读取，在 _load_config 中赋值

        # ===== 第3步：读取配置文件 =====
        logger.info("开始读取配置文件...")
        self._load_config()

        # ===== 第4步：创建所有 UI 元素 =====
        logger.info("开始创建 UI 元素...")
        self._setup_ui()
        logger.info("ScheduleClassroomFrontend 初始化完成")
        logger.info("=" * 50)

    # ================================================================
    #  私有方法：读取配置文件
    # ================================================================
    def _load_config(self) -> None:
        """
        从 Config/schedule_config.ini 读取配置参数。
        ------------------------------------------------
        读取的参数：
          - period_count（int）：每日课时数量，范围 1~15
          - theme       （str）：软件主题，可选 'lightcolor' / 'darkcolor' / 'multicolor'
          - language    （str）：显示语言，可选 'Chinese' / 'English'

        配置文件不存在或参数无效时使用默认值。
        """
        # 构建配置文件路径（相对于本脚本所在目录）
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')

        # ===== 默认值 =====
        default_period_count: int = 7
        default_theme: str = 'lightcolor'
        default_language: str = 'Chinese'

        try:
            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在：{config_path}")
                logger.warning(f"使用默认值：period_count={default_period_count}, "
                               f"theme={default_theme}, language={default_language}")
                self.period_count = default_period_count
                self.theme = default_theme
                self.language = default_language
                self._apply_theme()
                return

            logger.info(f"找到配置文件：{config_path}")
            parser: ConfigParser = ConfigParser()
            parser.read(config_path, encoding='utf-8')

            # ----------------------------------------------------------
            #  读取 period_count（课时数量）
            # ----------------------------------------------------------
            period_count_str: str = parser.get('Schedule', 'period_count',
                                          fallback=str(default_period_count))
            period_count: int = int(period_count_str)

            if period_count < 1 or period_count > 15:
                logger.warning(f"period_count={period_count} 超出范围 (1~15)，"
                               f"使用默认值 {default_period_count}")
                self.period_count = default_period_count
            else:
                self.period_count = period_count
                logger.info(f"period_count = {self.period_count}")

            # ----------------------------------------------------------
            #  读取 theme（软件主题）
            #  取值：lightcolor（浅色）、darkcolor（深色）、multicolor（彩色自适应）
            # ----------------------------------------------------------
            theme_str: str = parser.get('Schedule', 'theme', fallback=default_theme)
            theme_str = theme_str.strip().lower()

            if theme_str in ('lightcolor', 'darkcolor', 'multicolor'):
                self.theme = theme_str
                logger.info(f"theme = {self.theme}")
            else:
                logger.warning(f"theme='{theme_str}' 无效，使用默认值 '{default_theme}'")
                self.theme = default_theme

            # ----------------------------------------------------------
            #  读取 language（显示语言）
            #  取值：Chinese（中文）、English（英文）
            #  当前暂不做任何处理，仅存储字段供后续使用
            # ----------------------------------------------------------
            lang_str: str = parser.get('Schedule', 'language', fallback=default_language)
            lang_str = lang_str.strip()
            if lang_str in ('Chinese', 'English'):
                self.language = lang_str
                logger.info(f"language = {self.language}")
            else:
                logger.warning(f"language='{lang_str}' 无效，使用默认值 '{default_language}'")
                self.language = default_language

            # ===== 根据主题设置窗口颜色 =====
            self._apply_theme()

            logger.info(f"配置加载完成：period_count={self.period_count}, "
                        f"theme={self.theme}, language={self.language}")

        except (ValueError, TypeError) as e:
            logger.warning(f"配置文件参数格式错误：{e}，使用默认值")
            self.period_count = default_period_count
            self.theme = default_theme
            self.language = default_language
            self._apply_theme()
        except Exception as e:
            logger.error(f"读取配置文件失败：{e}，使用默认值")
            self.period_count = default_period_count
            self.theme = default_theme
            self.language = default_language
            self._apply_theme()

    # ================================================================
    #  私有方法：根据主题参数设置背景颜色和字体颜色
    # ================================================================
    def _apply_theme(self) -> None:
        """
        根据 self.theme 的值设置窗口背景色、字体色、分割线色和透明度。
        ------------------------------------------------------------------
        主题映射（参考《Qt 深色主题完整实现》配色方案，双向推导）：
          lightcolor    → 极浅灰底深灰字，时间窗 #FFFFFF / 科目窗 #FAFAFA，
                          透明度 0.70
          darkcolor     → 深灰底浅灰字，时间窗 #252526 / 科目窗 #1E1E1E，
                          透明度 0.85
          multicolor    → 自适应桌面背景色（TODO：待后期实现完整逻辑）

        设计原则：
          lightcolor — 背景不用纯白，用 #FAFAFA 减少眩光；
                       文字不用纯黑，用 #212121 降低对比度冲击；
                       时间窗略亮于科目窗，模拟纸张层次感。
          darkcolor  — 背景不用纯黑，用 #1E1E1E 减少光晕效应；
                       文字不用纯白，用 #E0E0E0 降低刺眼感；
                       时间窗略亮于科目窗，越靠前越亮。

        调用时机：_load_config() 读取配置后自动调用。
        """
        logger.info(f"应用主题：{self.theme}")

        if self.theme == 'lightcolor':
            # 参考《Qt 深色主题完整实现》配色方案反向推导
            # 时间窗口：纯白 #FFFFFF（上层"纸面"，略亮于科目窗）
            self.back_color = '#FFFFFF'
            # 科目窗口：极浅灰 #FAFAFA（主背景，比纯白柔和）
            self.root_back_color = '#FAFAFA'
            # 主文字：深灰 #212121（比纯黑舒适）
            self.font_color = '#212121'
            # 时间文字：Material Red 700，沉稳不刺眼
            self.time_color = '#D32F2F'
            # 分割线：黑色 8% 透明度，在浅色背景上≈#EEEEEE
            self.border_color = 'rgba(0, 0, 0, 0.08)'
            self.window_opacity = 0.70

        elif self.theme == 'darkcolor':
            # 参考《Qt 深色主题完整实现》配色方案
            # 时间窗口：次级背景 #252526（稍亮，形成层级感）
            self.back_color = '#252526'
            # 科目窗口：主背景 #1E1E1E（最暗底层）
            self.root_back_color = '#1E1E1E'
            # 主文字：浅灰 #E0E0E0（避免纯白刺激眼睛）
            self.font_color = '#E0E0E0'
            # 时间文字：Material Red 300，暗色背景下保持可读
            self.time_color = '#EF5350'
            # 分割线：#3E3E42 为基底，25% 透明度（深色背景下可见的分隔）
            self.border_color = 'rgba(62, 62, 66, 0.25)'
            # 透明度 0.85 —— 比浅色模式更不透明，确保深色效果不被桌面壁纸过度冲淡
            self.window_opacity = 0.85

        elif self.theme == 'multicolor':
            # ================================================================
            #  TODO: multicolor 主题 — 彩色自适应模式（待后期完善）
            #  ----------------------------------------------------------------
            #  当前为临时实现：沿用旧版的桌面像素颜色检测逻辑。
            #  后期需要改进的方向：
            #    1. 支持多区域采样取平均值（避免单像素颜色不具代表性）
            #    2. 支持预定义调色板选择（如 Material Design 色系）
            #    3. 支持用户自定义背景颜色
            #    4. 根据背景色自动选择对比度足够的字体颜色
            #    5. 透明度的自适应调整
            #  ================================================================
            gca = get_color(self.left_time - 1, self.top_time - 1)
            self.back_color = RGB_to_Hex((int(gca[0]), int(gca[1]), int(gca[2])))

            # multicolor 下时间窗与科目窗同色
            self.root_back_color = self.back_color
            self.border_color = 'rgba(128, 128, 128, 0.15)'
            self.window_opacity = 0.70
            self.time_color = '#FF0000'

            if is_color_dark(self.back_color):
                self.font_color = 'white'
            else:
                self.font_color = 'black'

        else:
            # 兜底：未知主题值，使用浅色模式
            self.back_color = '#FFFFFF'
            self.root_back_color = '#FAFAFA'
            self.font_color = '#212121'
            self.time_color = '#D32F2F'
            self.border_color = 'rgba(0, 0, 0, 0.08)'
            self.window_opacity = 0.70

        logger.info(f"主题配置完成：back_color={self.back_color}, "
                    f"root_back_color={self.root_back_color}, "
                    f"font_color={self.font_color}, opacity={self.window_opacity}")

    # ================================================================
    #  重写 paintEvent：直接绘制背景色（绕过样式表/QPalette 的不确定性）
    # ================================================================
    def paintEvent(self, event: QPaintEvent) -> None:
        """直接填充 self.back_color 作为窗口背景。"""
        painter: QPainter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.back_color))

    def _refresh_background(self) -> None:
        """
        触发背景重绘。
        当外部在 _setup_ui 之后修改 back_color 时，调用此方法刷新显示。
        """
        self.update()
        if self.root is not None:
            self.root.update()

    # ================================================================
    #  私有方法：创建所有 UI 元素
    # ================================================================
    def _setup_ui(self) -> None:
        """
        创建电子课表的两个窗口及其内部控件。
        ---------------------------------
        窗口结构：
          ┌──────────────┐
          │  14:30:05    │  ← 时间窗口（self），显示实时时间
          ├──────────────┤
          │   第1节       │  ← 科目显示窗口（self.root）
          │   第2节       │     包含 period_count 个课时标签
          │   第3节       │     每个标签通过 objectName 唯一标识
          │   ...        │     （period_label_0 ~ period_label_N）
          │   第7节       │
          │              │
          │     [×]      │  ← 关闭按钮（所有标签下方居中）
          └──────────────┘
        """

        # ========== 时间窗口（self）==========
        logger.info("创建时间窗口（self）...")

        # 设置窗口标志：
        #   FramelessWindowHint  — 无边框窗口
        #   WindowStaysOnTopHint — 始终置顶
        #   Tool                 — 不在任务栏显示
        self.setWindowFlags(
            Qt.FramelessWindowHint          # 去除窗口边框 → 对应 tkinter 的 overrideredirect(True)  # type: ignore
            | Qt.WindowStaysOnTopHint       # 窗口置顶  # type: ignore
            | Qt.Tool                       # 不在任务栏显示  # type: ignore
        )

        # 设置窗口大小和位置
        self.setFixedSize(int(self.win_width), int(self.height_time))
        self.move(self.left_time, self.top_time)

        # ★ paintEvent 已重写，直接由 self.back_color 决定背景色
        #    设置 autoFillBackground 防止系统绘制默认背景
        self.setAutoFillBackground(True)

        # 设置透明度（主题决定，darkcolor 模式为 0.85，其余为 0.70）
        self.setWindowOpacity(self.window_opacity)

        # 实时时间标签
        self.time_label = QLabel(self)
        self.time_label.setFont(QFont("Arial", 18))
        self.time_label.setStyleSheet(f"color: {self.time_color}; background: transparent;")
        self.time_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self.time_label.setGeometry(0, 0, int(self.win_width), int(self.height_time))

        # 设置初始显示文字
        self.time_label.setText("--:--:--")
        logger.info(f"时间窗口创建完成：位置({self.left_time}, {self.top_time})，"
                    f"大小 {int(self.win_width)}×{int(self.height_time)}")

        # ========== 科目显示窗口（self.root）==========
        logger.info("创建科目显示窗口（self.root）...")

        # ★ 使用 _RootWindow（内部通过 paintEvent 填充背景）
        #    科目窗口使用 root_back_color，深色模式下比时间窗口更深一层
        self.root = _RootWindow(self.root_back_color)
        self.root.setWindowFlags(
            Qt.FramelessWindowHint  # type: ignore
            | Qt.WindowStaysOnTopHint  # type: ignore
            | Qt.Tool  # type: ignore
        )

        # 设置窗口大小和位置
        self.root.setFixedSize(int(self.win_width), int(self.height_root))
        self.root.move(self.left_root, self.top_root)

        # 设置透明度（与时间窗口一致）
        self.root.setWindowOpacity(self.window_opacity)

        # ========== 课时标签区域 ==========
        # 根据配置文件中的 period_count 动态创建对应数量的标签控件
        # 每个标签命名规则：period_label_{index}（index 从 0 开始）
        # 通过 get_period_label(index) 可获取特定标签供后端修改

        close_btn_height: int = 36           # 关闭按钮区域高度（含上下间距）
        available_height: int = int(self.height_root) - close_btn_height
        label_height: int = available_height // self.period_count if self.period_count > 0 else available_height

        logger.info(f"创建 {self.period_count} 个课时标签（每个高度 {label_height}px）...")
        for i in range(self.period_count):
            label: QLabel = QLabel(self.root)
            # 每个标签设置唯一的 objectName，供后端精确定位
            label.setObjectName(f"period_label_{i}")
            label.setFont(QFont("Arial", 12))
            label.setStyleSheet(f"""
                color: {self.font_color};
                background: transparent;
                border-bottom: 1px solid {self.border_color};
            """)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
            # 垂直排列：第 i 个标签放在 i * label_height 处
            label.setGeometry(0, i * label_height, int(self.win_width), label_height)
            # 初始占位文字，显示课节序号
            label.setText(f"  第{i + 1}节")
            self.period_labels.append(label)

        # ========== 关闭按钮（置于所有标签下方）==========

        self.close_btn = QPushButton("×", self.root)
        self.close_btn.setFont(QFont("Arial", 14, QFont.Bold))  # type: ignore

        # 按钮样式：平时完全透明，悬停时显示红色文字和半透明背景
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {self.font_color};
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: #ff4444;
                background: rgba(128, 128, 128, 0.25);
                border-radius: 4px;
            }}
        """)
        self.close_btn.setFixedSize(28, 28)
        # 放在标签区域下方居中
        btn_x: int = (int(self.win_width) - 28) // 2
        btn_y: int = self.period_count * label_height + (close_btn_height - 28) // 2
        self.close_btn.move(btn_x, btn_y)

        # 连接关闭按钮点击 → 发射信号（不再直接关闭窗口）
        self.close_btn.clicked.connect(self._on_close_clicked)

        # 显示科目窗口
        self.root.show()
        logger.info(f"科目窗口创建完成：位置({self.left_root}, {self.top_root})，"
                    f"大小 {int(self.win_width)}×{int(self.height_root)}，"
                    f"课时标签 {self.period_count} 个，关闭按钮已连接")

    # ================================================================
    #  ★★★  前端 → 后端：按钮点击槽函数（私有方法）  ★★★
    #  --------------------------------------------
    #  这些方法在用户点击按钮时被调用。
    #  它们只做一件事：发射（emit）信号，把事件通知给后端。
    #
    #  打个比方：服务员听到客人喊"买单！"，然后对着后厨喊一嗓子。
    #  具体怎么买单，是老板（main.py）和收银员（后端）的事。
    # ================================================================

    def _on_close_clicked(self) -> None:
        """
        关闭按钮点击处理。
        ----------------
        发射 close_requested 信号，由 main.py 中的连接器
        转发给 WindowHelper.close_all() 处理。
        """
        logger.info("用户点击了关闭按钮，发射 close_requested 信号")
        self.close_requested.emit()

    # ================================================================
    #  ★★★  后端 → 前端：公开方法（Public API）  ★★★
    #  -----------------------------------------
    #  以下方法是供后端调用的公开接口。
    #  后端处理完业务逻辑后，调用这些方法来更新界面显示。
    #
    #  打个比方：厨师做好菜后喊"时间到了，把钟调一下！"，
    #  服务员就过来更新钟表显示。
    # ================================================================

    def update_time_display(self, time_str: str) -> None:
        """
        【公开方法】更新时间标签的显示文字。
        ---------------------------------
        参数：
            time_str（str）：时间字符串，格式为 HH:MM:SS（24 小时制）
                            示例："14:30:05"

        调用时机：
          - TimeManager 定时器每秒触发时，通过 main.py 的连接器调用此方法

        使用示例：
            # 在 main.py 中：
            time_manager.start(lambda t: window.update_time_display(t))
        """
        if self.time_label is not None:
            logger.debug(f"更新时间显示：{time_str}")
            self.time_label.setText(time_str)

    def get_root_window(self) -> Optional[QWidget]:
        """
        【公开方法】获取科目显示窗口的引用。
        --------------------------------
        返回值：
            Optional[QWidget]：root 窗口对象。如果 _setup_ui() 尚未调用则返回 None

        调用时机：
          - main.py 需要在关闭程序时同时关闭时间窗口和科目窗口
          - 外部需要操作科目窗口时

        使用示例：
            # 在 main.py 中：
            window_helper.close_all(
                [window, window.get_root_window()], app
            )
        """
        return self.root

    def get_time_window(self) -> 'ScheduleClassroomFrontend':
        """
        【公开方法】获取时间窗口的引用（即 self）。
        ---------------------------------------
        返回值：
            ScheduleClassroomFrontend：时间窗口对象（self）

        调用时机：
          - main.py 需要在关闭程序时操作时间窗口

        使用示例：
            # 在 main.py 中：
            widgets_to_close = [
                window.get_time_window(),
                window.get_root_window()
            ]
        """
        return self

    # ================================================================
    #  课时标签相关公开方法（供后端调用）
    # ================================================================

    def get_period_label(self, index: int) -> Optional[QLabel]:
        """
        【公开方法】根据索引获取指定的课时标签控件。
        -----------------------------------------
        参数：
            index（int）：课时标签的索引，从 0 开始（0 = 第1节）

        返回值：
            Optional[QLabel]：对应索引的 QLabel 对象；索引越界时返回 None

        调用时机：
          - 后端需要修改某个特定课时的显示内容时
          - 例如：set_period_text(2, "数学") 的底层实现

        使用示例：
            # 后端代码：
            label = frontend.get_period_label(2)  # 获取第3节课的标签
            if label is not None:
                label.setText("数学")
        """
        if 0 <= index < len(self.period_labels):
            return self.period_labels[index]
        logger.warning(f"get_period_label: 索引 {index} 越界 (共 {len(self.period_labels)} 个标签)")
        return None

    def get_period_label_by_name(self, name: str) -> Optional[QLabel]:
        """
        【公开方法】根据 objectName 获取指定的课时标签控件。
        ------------------------------------------------
        参数：
            name（str）：标签的 objectName，格式为 "period_label_{index}"
                        例如："period_label_0" 表示第1节课

        返回值：
            Optional[QLabel]：匹配的 QLabel 对象；未找到时返回 None

        调用时机：
          - 后端按名称精确查找某个标签时

        使用示例：
            # 后端代码：
            label = frontend.get_period_label_by_name("period_label_3")
            if label is not None:
                label.setStyleSheet("color: red;")
        """
        for label in self.period_labels:
            if label.objectName() == name:
                return label
        logger.warning(f"get_period_label_by_name: 未找到名称为 '{name}' 的标签")
        return None

    def get_period_count(self) -> int:
        """
        【公开方法】获取当前课时数量。
        ---------------------------
        返回值：
            int：课时总数（从配置文件读取的 period_count）

        调用时机：
          - 后端需要知道总共有多少课时时

        使用示例：
            # 后端代码：
            total = frontend.get_period_count()
            for i in range(total):
                frontend.get_period_label(i).setText(f"第{i+1}节已更新")
        """
        return self.period_count

    def get_all_period_labels(self) -> List[QLabel]:
        """
        【公开方法】获取所有课时标签控件的列表。
        -------------------------------------
        返回值：
            List[QLabel]：所有课时标签的列表（按索引顺序排列）

        调用时机：
          - 后端需要批量操作所有标签时
          - 例如：清空所有标签、统一修改样式等

        使用示例：
            # 后端代码：
            for label in frontend.get_all_period_labels():
                label.setText("")
        """
        return self.period_labels
