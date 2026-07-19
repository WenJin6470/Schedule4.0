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
  ✅ 创建底部按钮栏（全屏时间/快捷编辑/设置/关闭）并捕获用户点击
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

import json
import logging
import os
from configparser import ConfigParser
from typing import Dict, List, Optional, Tuple, Union

from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                                   QPushButton, QScrollArea, QSizePolicy,
                                   QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, QSize, Signal, SignalInstance
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPaintEvent

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


# ==================== 科目选择子窗口类 ====================

class SubjectSelectWindow(QWidget):
    """
    # SubjectSelectWindow — 快捷课表编辑科目选择窗口

    在用户点击快捷编辑按钮后弹出，提供科目选择和移动控制功能。
    ---

    窗口布局（左:右 = 8:2）：
      ┌──────────────────────────┬──────────┐
      │  Category_1 标题         │ 倍速向上  │
      │  [语文] [数学] [英语]... │          │
      │  ─── 分割线 ───         │  向上    │
      │  Category_2 标题         │          │
      │  [活动] [体育] [信息]... │  向下    │
      │  ─── 分割线 ───         │          │
      │  Category_3 标题         │ 倍速向下  │
      │  [None]                  │          │
      │                          │  确定    │
      └──────────────────────────┴──────────┘

    所有按钮点击均通过 parent_signal 发射统一的 backend_signal，
    动作标识符由后端解析处理。
    """

    def __init__(self, parent_signal: SignalInstance, subject_config: Dict,
                 back_color: str, font_color: str, border_color: str,
                 root_back_color: str, theme: str) -> None:
        """
        初始化科目选择窗口。
        -----------------
        参数：
            parent_signal  （Signal）：父窗口的 backend_signal，用于发射动作信号
            subject_config （Dict）：  科目配置数据（从 subject_config.json 加载）
            back_color     （str）：   时间窗口背景色
            font_color     （str）：   字体颜色
            border_color   （str）：   分割线颜色
            root_back_color（str）：   科目窗口背景色（本窗口使用此颜色）
            theme          （str）：   当前主题名称
        """
        super().__init__()
        self._parent_signal: SignalInstance = parent_signal
        self._subject_config: Dict = subject_config
        self._back_color: str = root_back_color       # 使用科目窗口背景色
        self._font_color: str = font_color
        self._border_color: str = border_color
        self._theme: str = theme
        self._bg_color: QColor = QColor(self._back_color)

        # 获取屏幕尺寸用于窗口定位
        screen = QApplication.primaryScreen()
        if screen is None:
            self._screen_w: int = 1920
            self._screen_h: int = 1080
        else:
            self._screen_w = screen.size().width()
            self._screen_h = screen.size().height()

        logger.info("SubjectSelectWindow 初始化开始")
        self._setup_ui()
        logger.info("SubjectSelectWindow 初始化完成")

    # ================================================================
    #  paintEvent：直接绘制背景色
    # ================================================================
    def paintEvent(self, event: QPaintEvent) -> None:
        """直接填充背景色。"""
        painter: QPainter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)

    # ================================================================
    #  私有方法：创建 UI 元素
    # ================================================================
    def _setup_ui(self) -> None:
        """创建科目选择窗口的所有 UI 元素。"""

        # ----- 窗口属性 -----
        self.setWindowFlags(
            Qt.FramelessWindowHint           # type: ignore
            | Qt.WindowStaysOnTopHint        # type: ignore
            | Qt.Tool                        # type: ignore
        )
        self.setAutoFillBackground(True)
        self.setWindowOpacity(0.9)

        # 窗口大小和位置（居中偏左，避免遮挡主窗口）
        win_w: int = int(self._screen_w * 0.35)
        win_h: int = int(self._screen_h * 0.65)
        self.setFixedSize(win_w, win_h)
        # 放置在屏幕中央偏左
        pos_x: int = (self._screen_w - win_w) // 2 - int(self._screen_w * 0.08)
        pos_y: int = (self._screen_h - win_h) // 2
        self.move(pos_x, pos_y)

        # ----- 主布局：左右 8:2 -----
        main_layout: QHBoxLayout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ===== 左侧面板（80%）：科目按钮区域 =====
        left_panel: QWidget = self._build_left_panel()
        main_layout.addWidget(left_panel, stretch=8)

        # ===== 右侧面板（20%）：控制按钮区域 =====
        right_panel: QWidget = self._build_right_panel()
        main_layout.addWidget(right_panel, stretch=2)

        logger.info(f"SubjectSelectWindow UI 创建完成：{win_w}×{win_h}")

    # ================================================================
    #  构建左侧面板：科目按钮（分组 + 分割线）
    # ================================================================
    def _build_left_panel(self) -> QWidget:
        """
        构建左侧科目按钮面板。
        -------------------
        包含一个可滚动的区域，内部按 subject_config.json 的分类
        将科目按钮分为三组，每组之间用分割线隔开。
        """

        # 滚动区域
        scroll_area: QScrollArea = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: {self._border_color};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        # 滚动区域内部容器
        inner_widget: QWidget = QWidget()
        inner_widget.setStyleSheet("background: transparent;")
        inner_layout: QVBoxLayout = QVBoxLayout(inner_widget)
        inner_layout.setContentsMargins(4, 4, 4, 4)
        inner_layout.setSpacing(4)

        # 按钮样式
        btn_style: str = f"""
            QPushButton {{
                color: {self._font_color};
                background: rgba(128, 128, 128, 0.08);
                border: 1px solid {self._border_color};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.25);
                border: 1px solid rgba(128, 128, 128, 0.4);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.35);
            }}
        """

        # 分割线样式
        separator_style: str = f"""
            QFrame {{
                border: none;
                border-top: 1px solid {self._border_color};
                margin: 6px 0px;
                max-height: 1px;
            }}
        """

        # 分类标题样式
        category_label_style: str = f"""
            QLabel {{
                color: {self._font_color};
                font-size: 11px;
                font-weight: bold;
                padding: 4px 0px 2px 2px;
                background: transparent;
            }}
        """

        # 分类名称映射（中文显示）
        category_names: Dict[str, str] = {
            "Category_1": "文化课",
            "Category_2": "活动课",
            "Category_3": "其他",
        }

        subject_types: Dict = self._subject_config.get("Subject_Types", {})
        category_keys: List[str] = list(subject_types.keys())

        for idx, category_key in enumerate(category_keys):
            # 添加分割线（第一个分类之前不加）
            if idx > 0:
                sep: QFrame = QFrame()
                sep.setStyleSheet(separator_style)
                sep.setFrameShape(QFrame.HLine)  # type: ignore
                inner_layout.addWidget(sep)

            # 分类标题
            cat_display_name: str = category_names.get(category_key, category_key)
            cat_label: QLabel = QLabel(cat_display_name)
            cat_label.setStyleSheet(category_label_style)
            inner_layout.addWidget(cat_label)

            # 科目按钮流式布局（使用 WrapLayout 效果：多行排列）
            subjects = subject_types[category_key]

            if isinstance(subjects, str):
                # Category_3 可能是字符串 "None"
                if subjects.lower() != "none":
                    btn: QPushButton = self._create_subject_button(subjects, btn_style)
                    inner_layout.addWidget(btn)
                else:
                    # "None" 显示为灰色不可用按钮
                    btn = QPushButton("无")
                    btn.setEnabled(False)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            color: rgba(128, 128, 128, 0.5);
                            background: rgba(128, 128, 128, 0.05);
                            border: 1px solid rgba(128, 128, 128, 0.1);
                            border-radius: 4px;
                            padding: 6px 10px;
                            font-size: 13px;
                        }}
                    """)
                    inner_layout.addWidget(btn)
            elif isinstance(subjects, list):
                # 流式按钮布局：用 QVBoxLayout 嵌套 QHBoxLayout 模拟
                # 每行放尽可能多的按钮
                buttons_per_row: int = 4  # 每行最多 4 个按钮
                current_row: Optional[QHBoxLayout] = None

                for i, subject_name in enumerate(subjects):
                    if i % buttons_per_row == 0:
                        # 开始新的一行
                        current_row = QHBoxLayout()
                        current_row.setSpacing(4)
                        current_row.setContentsMargins(0, 0, 0, 0)
                        inner_layout.addLayout(current_row)

                    btn = self._create_subject_button(subject_name, btn_style)
                    if current_row is not None:
                        current_row.addWidget(btn, stretch=1)

                # 如果最后一行不满，添加空白占位
                remaining: int = len(subjects) % buttons_per_row
                if remaining > 0 and current_row is not None:
                    for _ in range(buttons_per_row - remaining):
                        spacer: QWidget = QWidget()
                        spacer.setStyleSheet("background: transparent;")
                        current_row.addWidget(spacer, stretch=1)

        # 底部弹簧，将按钮组推到顶部
        inner_layout.addStretch()

        scroll_area.setWidget(inner_widget)
        return scroll_area

    # ================================================================
    #  创建单个科目按钮
    # ================================================================
    def _create_subject_button(self, subject_name: str, style: str) -> QPushButton:
        """
        创建一个科目按钮并连接点击信号。
        -------------------------------
        参数：
            subject_name（str）：科目名称（按钮文字）
            style       （str）：按钮的 Qt 样式表

        返回值：
            QPushButton：已连接信号的按钮控件
        """
        btn: QPushButton = QPushButton(subject_name)
        btn.setStyleSheet(style)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        btn.setMinimumHeight(32)
        btn.clicked.connect(
            lambda checked=False, name=subject_name: self._emit_action(f"subject:{name}")
        )
        return btn

    # ================================================================
    #  构建右侧面板：控制按钮
    # ================================================================
    def _build_right_panel(self) -> QWidget:
        """
        构建右侧控制按钮面板。
        -------------------
        包含 5 个垂直排列的按钮：
          倍速向上  — 相当于点击 2 次"向上"
          向上      — 光标向上移动
          向下      — 光标向下移动
          倍速向下  — 相当于点击 2 次"向下"
          确定      — 确认并关闭窗口
        """

        panel: QWidget = QWidget()
        panel.setStyleSheet("background: transparent;")
        layout: QVBoxLayout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(6)

        # 控制按钮样式
        ctrl_btn_style: str = f"""
            QPushButton {{
                color: {self._font_color};
                background: rgba(128, 128, 128, 0.12);
                border: 1px solid {self._border_color};
                border-radius: 4px;
                padding: 8px 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(128, 128, 128, 0.3);
                border: 1px solid rgba(128, 128, 128, 0.5);
            }}
            QPushButton:pressed {{
                background: rgba(128, 128, 128, 0.4);
            }}
        """

        # 确定按钮特殊样式（更醒目）
        confirm_btn_style: str = f"""
            QPushButton {{
                color: {'#FFFFFF' if self._theme == 'darkcolor' else '#FFFFFF'};
                background: rgba(33, 150, 243, 0.7);
                border: 1px solid rgba(33, 150, 243, 0.5);
                border-radius: 4px;
                padding: 8px 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(33, 150, 243, 0.9);
            }}
            QPushButton:pressed {{
                background: rgba(33, 150, 243, 1.0);
            }}
        """

        # 控制按钮配置：(文字, 动作标识符, 样式)
        control_buttons = [
            ("倍速向上", "move_double_up", ctrl_btn_style),
            ("向上",     "move_up",       ctrl_btn_style),
            ("向下",     "move_down",     ctrl_btn_style),
            ("倍速向下", "move_double_down", ctrl_btn_style),
        ]

        # 顶部弹簧 — 让按钮组在垂直方向居中
        layout.addStretch()

        for text, action, style in control_buttons:
            btn: QPushButton = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
            btn.clicked.connect(
                lambda checked=False, a=action: self._emit_action(a)
            )
            layout.addWidget(btn)

        # 按钮组之间的间距
        layout.addSpacing(10)

        # 确定按钮
        confirm_btn: QPushButton = QPushButton("确定")
        confirm_btn.setStyleSheet(confirm_btn_style)
        confirm_btn.setMinimumHeight(40)
        confirm_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # type: ignore
        confirm_btn.clicked.connect(lambda: self._emit_action("confirm"))
        layout.addWidget(confirm_btn)

        # 底部弹簧
        layout.addStretch()

        return panel

    # ================================================================
    #  发射动作信号
    # ================================================================
    def _emit_action(self, action: str) -> None:
        """
        通过父窗口的 backend_signal 发射动作信号。
        ----------------------------------------
        参数：
            action（str）：动作标识符，如 "subject:数学"、"move_up" 等
        """
        logger.info(f"[SubjectSelectWindow] 发射动作: {action}")
        self._parent_signal.emit(action)


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

    # 统一后端信号 —— 所有按钮点击事件通过此信号发送给后端处理
    # 参数：action（str）—— 动作标识符，后端据此分派业务逻辑
    backend_signal = Signal(str)

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
        self.edit_btn: Optional[QPushButton] = None
        self.time_label: Optional[QLabel] = None

        # 科目选择子窗口引用
        self._subject_window: Optional[QWidget] = None

        # 科目配置数据（从 subject_config.json 加载）
        self.subject_config: Dict = {}

        # ===== 课时标签列表 =====
        # 每个标签控件按索引存储在列表中，通过 get_period_label(index) 获取
        self.period_labels: List[QLabel] = []
        self.period_count: int = 0  # 从配置文件读取，在 _load_config 中赋值

        # ===== 第3步：读取配置文件 =====
        logger.info("开始读取配置文件...")
        self._load_config()

        # ===== 第3.5步：读取科目配置文件 =====
        logger.info("开始读取科目配置文件...")
        self._load_subject_config()

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
    #  私有方法：读取科目配置文件
    # ================================================================
    def _load_subject_config(self) -> None:
        """
        从 Config/subject_config.json 读取科目分类配置。
        ------------------------------------------------
        读取的数据结构：
          {
            "Subject_Types": {
              "Category_1": ["语文", "数学", ...],
              "Category_2": ["活动", "体育", ...],
              "Category_3": "None"
            }
          }

        读取失败时使用空字典作为兜底。
        """
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'subject_config.json')

        # 默认空配置
        default_config: Dict = {"Subject_Types": {}}

        try:
            if not os.path.exists(config_path):
                logger.warning(f"科目配置文件不存在：{config_path}")
                self.subject_config = default_config
                return

            logger.info(f"找到科目配置文件：{config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                self.subject_config = json.load(f)

            # 统计科目数量
            subject_types = self.subject_config.get("Subject_Types", {})
            total_subjects = 0
            for _category, subjects in subject_types.items():
                if isinstance(subjects, list):
                    total_subjects += len(subjects)
            logger.info(f"科目配置加载完成：{len(subject_types)} 个分类，共 {total_subjects} 个科目")

        except json.JSONDecodeError as e:
            logger.error(f"科目配置文件 JSON 解析失败：{e}")
            self.subject_config = default_config
        except Exception as e:
            logger.error(f"读取科目配置文件失败：{e}")
            self.subject_config = default_config

    # ================================================================
    #  私有方法：根据当前主题确定按钮图标后缀
    # ================================================================
    def _get_icon_suffix(self) -> str:
        """
        根据当前主题返回按钮图标文件名的后缀。
        ------------------------------------
        -w 后缀代表白色（white）图标，适合深色背景上显示。
        无后缀的是深色图标，适合浅色背景上显示。

        返回值：
            str：'-w'  — 白色图标（如 FullScreenTime-w.svg），用于深色背景
                 ''    — 深色图标（如 FullScreenTime.svg），用于浅色背景

        调用时机：_setup_ui() 创建按钮时自动调用。
        """
        if self.theme == 'lightcolor':
            return ''       # 浅色背景 → 深色图标
        elif self.theme == 'darkcolor':
            return '-w'     # 深色背景 → 白色图标
        elif self.theme == 'multicolor':
            # multicolor 模式：根据实际背景色判断深浅
            if is_color_dark(self.back_color):
                return '-w'     # 深色背景 → 白色图标
            else:
                return ''       # 浅色背景 → 深色图标
        return ''

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
          │ ⏰ 📝 ⚙ ✕  │  ← 底部按钮栏（左→右：全屏时间/快捷编辑/设置/关闭）
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

        close_btn_height: int = 36           # 底部按钮栏区域高度（含上下间距）
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

        # ========== 底部按钮栏（2 个图标按钮，置于所有标签下方）==========
        # 从左到右：快捷课表编辑 → 关闭
        # 根据主题自动选择深色/浅色图标（通过 _get_icon_suffix() 判断）

        images_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images')
        icon_suffix: str = self._get_icon_suffix()

        logger.info(f"图标后缀：'{icon_suffix}'（主题={self.theme}，背景色={self.back_color}）")

        # 按钮配置列表：(属性名, 图片基础名, 点击处理函数)
        button_configs = [
            ('edit_btn',  'EDIT_S', self._on_quick_edit_clicked),
            ('close_btn', 'EXIT',   self._on_close_clicked),
        ]

        btn_size: int = 20                               # 每个按钮的宽高（正方形）
        total_btn_width: int = 2 * btn_size              # 所有按钮占用的总宽度
        spacing: int = (int(self.win_width) - total_btn_width) // 3  # 等分间距（3个间隔）
        btn_y: int = self.period_count * label_height + (close_btn_height - btn_size) // 2

        for i, (attr_name, image_base, handler) in enumerate(button_configs):
            icon_path: str = os.path.join(images_dir, f"{image_base}{icon_suffix}.svg")

            btn: QPushButton = QPushButton(self.root)
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(btn_size, btn_size))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background: rgba(128, 128, 128, 0.25);
                    border-radius: 4px;
                }}
            """)
            btn.setFixedSize(btn_size, btn_size)

            # 等间距水平排列：spacing + i × (btn_size + spacing)
            btn_x: int = spacing + i * (btn_size + spacing)
            btn.move(btn_x, btn_y)

            # 连接点击信号 → 发射对应的自定义信号
            btn.clicked.connect(handler)

            # 保存按钮引用到实例属性
            setattr(self, attr_name, btn)

        logger.info(f"底部按钮栏创建完成：2 个图标按钮，图标后缀='{icon_suffix}'，间距={spacing}px")

        # 显示科目窗口
        self.root.show()
        logger.info(f"科目窗口创建完成：位置({self.left_root}, {self.top_root})，"
                    f"大小 {int(self.win_width)}×{int(self.height_root)}，"
                    f"课时标签 {self.period_count} 个，底部按钮栏 2 个已连接")

    # ================================================================
    #  ★★★  前端 → 后端：按钮点击槽函数（私有方法）  ★★★
    #  --------------------------------------------
    #  这些方法在用户点击按钮时被调用。
    #  它们只做一件事：发射（emit）统一后端信号，把事件通知给后端。
    #
    #  打个比方：服务员听到客人喊"买单！"，然后对着后厨喊一嗓子。
    #  具体怎么买单，是老板（main.py）和收银员（后端）的事。
    # ================================================================

    def _on_close_clicked(self) -> None:
        """
        关闭按钮点击处理。
        ----------------
        发射统一 backend_signal 信号，由 main.py 中的连接器
        转发给 ScheduleBackend.handle_action() 处理。
        """
        logger.info("用户点击了关闭按钮，发射 backend_signal('close')")
        # 如果快捷编辑面板已打开，先关闭它
        if self._subject_window is not None:
            logger.info("先关闭快捷编辑面板")
            self._subject_window.close()
            self._subject_window = None
        self.backend_signal.emit("close")

    def _on_quick_edit_clicked(self) -> None:
        """
        快捷课表编辑按钮点击处理。
        ----------------------
        发射统一 backend_signal 信号，然后创建并显示科目选择子窗口。
        """
        logger.info("用户点击了快捷课表编辑按钮")
        self.backend_signal.emit("quick_edit_opened")
        self._show_subject_window()

    # ================================================================
    #  私有方法：显示科目选择子窗口
    # ================================================================
    def _show_subject_window(self) -> None:
        """
        创建并显示快捷课表编辑科目选择子窗口。
        -----------------------------------
        如果已有子窗口打开，先关闭旧的再创建新的。
        """
        if self._subject_window is not None:
            logger.info("检测到已有科目选择窗口打开，先关闭")
            self._subject_window.close()
            self._subject_window = None

        logger.info("创建科目选择子窗口...")
        self._subject_window = SubjectSelectWindow(
            parent_signal=self.backend_signal,
            subject_config=self.subject_config,
            back_color=self.back_color,
            font_color=self.font_color,
            border_color=self.border_color,
            root_back_color=self.root_back_color,
            theme=self.theme,
        )
        self._subject_window.show()
        logger.info("科目选择子窗口已显示")

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
