"""
╔══════════════════════════════════════════════════════════════════════════╗
║       📅 电子课表系统 —— schedule_config.py（配置管理 + 基础控件）         ║
║                  （统一的配置读取、课表数据管理与共享基类）                   ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件为整个前端提供统一的配置管理和基础控件，包括：
  ✅ ThemeManager       — 集中管理所有颜色、字体、透明度等主题参数
  ✅ ScheduleDataManager — 读取课表数据和时间表配置
  ✅ ThemedWidget       — 所有窗口的基类，提供 paintEvent 背景填充
  ✅ 工具函数           — get_color / RGB_to_Hex / is_color_dark

所有前端窗口类（主窗口、时间窗口、快捷编辑、设置）均通过
ThemeManager 获取主题颜色，确保全局一致性。
"""

import json
import logging
import os
import re
from configparser import ConfigParser
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QColor, QPainter, QPaintEvent

logger: logging.Logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================

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

    geo = screen.geometry()
    x = max(0, min(x, geo.width() - 1))
    y = max(0, min(y, geo.height() - 1))

    pixmap = screen.grabWindow(0)
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


# ==================== 主题管理器 ====================

class ThemeManager:
    """
    # ThemeManager — 全局主题管理器

    集中管理所有主题相关参数，从配置文件读取并统一提供给所有窗口。
    ---

    对外属性（颜色）：
      - back_color       — 主背景色
      - root_back_color  — 次要背景色（科目窗口等）
      - font_color       — 字体颜色
      - time_color       — 时间标签颜色
      - border_color     — 分割线颜色
      - window_opacity   — 窗口透明度
      - theme            — 主题名称
      - language         — 显示语言
      - subject_config   — 科目分类配置
      - curriculum_path  — 课程表 JSON 文件路径（由 INI 的 table 参数指定）
      - timetable_path   — 时间表 JSON 文件路径（由 INI 的 timetable 参数指定）

    对外方法：
      - get_icon_suffix() → str  根据主题返回图标后缀
    """

    def __init__(self, fallback_theme: str = 'lightcolor',
                 fallback_language: str = 'Chinese') -> None:
        """
        初始化主题管理器，从配置文件读取参数。
        ------------------------------------
        参数：
            fallback_theme    （str）：配置文件读取失败时的兜底主题
            fallback_language （str）：配置文件读取失败时的兜底语言
        """
        logger.info("ThemeManager 初始化开始")

        # ---- 屏幕尺寸 ----
        screen = QApplication.primaryScreen()
        if screen is None:
            self.screen_width: int = 1920
            self.screen_height: int = 1080
        else:
            self.screen_width: int = screen.size().width()
            self.screen_height: int = screen.size().height()
        logger.info(f"屏幕分辨率：{self.screen_width}×{self.screen_height}")

        # ---- 默认值 ----
        self.theme: str = fallback_theme
        self.language: str = fallback_language

        # ---- 颜色属性（兜底默认白色主题）----
        self.back_color: str = '#FFFFFF'
        self.root_back_color: str = '#FAFAFA'
        self.font_color: str = '#212121'
        self.time_color: str = '#D32F2F'
        self.border_color: str = 'rgba(0, 0, 0, 0.08)'
        self.window_opacity: float = 0.70

        # ---- 科目配置 ----
        self.subject_config: Dict = {}

        # ---- 数据文件路径（由 INI 配置指定）----
        self.curriculum_path: str = ''
        self.timetable_path: str = ''

        # ---- 日志保留天数 ----
        self.log_retention_days: int = 7

        # ---- 全屏时间创意模式背景图片文件夹 ----
        self.fullscreen_bg_folder: str = 'images/FullScreenBackgrounds/default'

        # ---- 加载配置 ----
        self._load_config()
        self._load_subject_config()

        logger.info(f"ThemeManager 初始化完成：theme={self.theme}, "
                    f"curriculum={self.curriculum_path}, "
                    f"timetable={self.timetable_path}, "
                    f"fullscreen_bg_folder={self.fullscreen_bg_folder}, "
                    f"log_retention_days={self.log_retention_days}")

    # ================================================================
    #  读取主配置文件
    # ================================================================
    def _load_config(self) -> None:
        """从 Config/schedule_config.ini 读取配置参数。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'schedule_config.ini')

        default_theme: str = 'lightcolor'
        default_language: str = 'Chinese'
        default_curriculum: str = 'Config/curriculum/table_1.json'
        default_timetable: str = 'Config/timetable/timetable_1.json'

        try:
            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在：{config_path}，使用默认值")
                self.theme = default_theme
                self.language = default_language
                self.curriculum_path = default_curriculum
                self.timetable_path = default_timetable
                self.fullscreen_bg_folder = 'images/FullScreenBackgrounds/default'
                self.log_retention_days = 7
                self._apply_theme()
                return

            logger.info(f"找到配置文件：{config_path}")
            parser: ConfigParser = ConfigParser()
            parser.read(config_path, encoding='utf-8')

            # --- theme ---
            theme_str: str = parser.get('Schedule', 'theme', fallback=default_theme)
            theme_str = theme_str.strip().lower()
            if theme_str in ('lightcolor', 'darkcolor', 'multicolor'):
                self.theme = theme_str
            else:
                logger.warning(f"theme='{theme_str}' 无效，使用默认值 '{default_theme}'")
                self.theme = default_theme

            # --- language ---
            lang_str: str = parser.get('Schedule', 'language', fallback=default_language)
            lang_str = lang_str.strip()
            if lang_str in ('Chinese', 'English'):
                self.language = lang_str
            else:
                self.language = default_language

            # --- table（课程表 JSON 文件路径）---
            default_curriculum: str = 'Config/curriculum/table_1.json'
            table_str: str = parser.get('Schedule', 'table', fallback=default_curriculum)
            self.curriculum_path = table_str.strip()

            # --- timetable（时间表 JSON 文件路径）---
            default_timetable: str = 'Config/timetable/timetable_1.json'
            timetable_str: str = parser.get('Schedule', 'timetable', fallback=default_timetable)
            self.timetable_path = timetable_str.strip()

            # --- log_retention_days（日志保留天数）---
            default_log_retention: int = 7
            log_retention_str: str = parser.get('Schedule', 'log_retention_days',
                                                 fallback=str(default_log_retention))
            try:
                log_retention: int = int(log_retention_str)
                if 0 <= log_retention <= 365:
                    self.log_retention_days = log_retention
                else:
                    logger.warning(f"log_retention_days={log_retention} 超出范围，使用默认值 {default_log_retention}")
                    self.log_retention_days = default_log_retention
            except ValueError:
                logger.warning(f"log_retention_days='{log_retention_str}' 格式无效，使用默认值 {default_log_retention}")
                self.log_retention_days = default_log_retention

            # --- fullscreen_bg_folder（全屏时间创意模式背景图片文件夹）---
            default_bg_folder: str = 'images/FullScreenBackgrounds/default'
            bg_folder_str: str = parser.get('Schedule', 'fullscreen_bg_folder',
                                             fallback=default_bg_folder)
            self.fullscreen_bg_folder = bg_folder_str.strip()

            self._apply_theme()

            logger.info(f"配置加载完成：theme={self.theme}, language={self.language}, "
                        f"curriculum={self.curriculum_path}, "
                        f"timetable={self.timetable_path}, "
                        f"log_retention_days={self.log_retention_days}")

        except (ValueError, TypeError) as e:
            logger.warning(f"配置文件参数格式错误：{e}，使用默认值")
            self.theme = default_theme
            self.language = default_language
            self.curriculum_path = default_curriculum
            self.timetable_path = default_timetable
            self.fullscreen_bg_folder = 'images/FullScreenBackgrounds/default'
            self.log_retention_days = 7
            self._apply_theme()
        except Exception as e:
            logger.error(f"读取配置文件失败：{e}，使用默认值")
            self.theme = default_theme
            self.language = default_language
            self.curriculum_path = default_curriculum
            self.timetable_path = default_timetable
            self.fullscreen_bg_folder = 'images/FullScreenBackgrounds/default'
            self.log_retention_days = 7
            self._apply_theme()

    # ================================================================
    #  应用主题颜色
    # ================================================================
    def _apply_theme(self) -> None:
        """
        根据 self.theme 的值设置所有颜色属性。
        -----------------------------------
        主题说明：
          lightcolor — 浅色模式（白底深字）
          darkcolor  — 深色模式（深灰底浅字）
          multicolor — 自适应桌面背景色
        """
        logger.info(f"应用主题：{self.theme}")

        if self.theme == 'lightcolor':
            self.back_color = '#FFFFFF'
            self.root_back_color = '#FAFAFA'
            self.font_color = '#212121'
            self.time_color = '#D32F2F'
            self.border_color = 'rgba(0, 0, 0, 0.08)'
            self.window_opacity = 0.70

        elif self.theme == 'darkcolor':
            self.back_color = '#252526'
            self.root_back_color = '#1E1E1E'
            self.font_color = '#E0E0E0'
            self.time_color = '#EF5350'
            self.border_color = 'rgba(62, 62, 66, 0.25)'
            self.window_opacity = 0.85

        elif self.theme == 'multicolor':
            # 屏幕右上角采样（与时间窗口位置一致）
            sample_x = int(self.screen_width * (1765 / 1920)) - 1
            sample_y = int(self.screen_height * (45 / 1080)) - 1
            gca = get_color(sample_x, sample_y)
            self.back_color = RGB_to_Hex((int(gca[0]), int(gca[1]), int(gca[2])))
            self.root_back_color = self.back_color
            self.border_color = 'rgba(128, 128, 128, 0.15)'
            self.window_opacity = 0.70
            self.time_color = '#FF0000'

            if is_color_dark(self.back_color):
                self.font_color = 'white'
            else:
                self.font_color = 'black'

        logger.info(f"主题配置完成：back_color={self.back_color}, "
                    f"font_color={self.font_color}, opacity={self.window_opacity}")

    # ================================================================
    #  读取科目配置文件
    # ================================================================
    def _load_subject_config(self) -> None:
        """从 Config/subject_config.json 读取科目分类配置。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'subject_config.json')

        default_config: Dict = {"Subject_Types": {}}

        try:
            if not os.path.exists(config_path):
                logger.warning(f"科目配置文件不存在：{config_path}")
                self.subject_config = default_config
                return

            logger.info(f"找到科目配置文件：{config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                self.subject_config = json.load(f)

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
    #  公开方法：获取图标后缀
    # ================================================================
    def get_icon_suffix(self) -> str:
        """
        根据当前主题返回按钮图标文件名的后缀。
        ------------------------------------
        -w 后缀代表白色（white）图标，适合深色背景上显示。
        无后缀的是深色图标，适合浅色背景上显示。

        返回值：
            str：'-w' — 白色图标（深色背景）
                 ''  — 深色图标（浅色背景）
        """
        if self.theme == 'lightcolor':
            return ''
        elif self.theme == 'darkcolor':
            return '-w'
        elif self.theme == 'multicolor':
            if is_color_dark(self.back_color):
                return '-w'
            else:
                return ''
        return ''

# ==================== 课表数据管理器 ====================


class ScheduleDataManager:
    """
    # ScheduleDataManager — 课表数据管理器

    负责读取课表课程数据和时间表配置，将 JSON 原始数据加载到内存中。
    数据文件路径由 ThemeManager 从 INI 配置中读取后传入。
    ---

    对外属性：
      - curriculum_data — 课表课程数据（dict），键为星期几，值为当日课时科目
      - timetable_data  — 课时时间配置（dict），键为 lesson_N，值为 [开始, 结束]
      - curriculum_path — 实际使用的课程表文件路径
      - timetable_path  — 实际使用的时间表文件路径
    """

    def __init__(self, curriculum_path: str = 'Config/curriculum/table_1.json',
                 timetable_path: str = 'Config/timetable/timetable_1.json') -> None:
        """
        初始化课表数据管理器，从 JSON 文件读取原始数据。
        --------------------------------------------
        参数：
            curriculum_path （str）：课程表 JSON 文件相对路径（相对于脚本目录）
            timetable_path  （str）：时间表 JSON 文件相对路径（相对于脚本目录）
        """
        logger.info("ScheduleDataManager 初始化开始")

        # ---- 记录路径 ----
        self.curriculum_path: str = curriculum_path
        self.timetable_path: str = timetable_path

        # ---- 课表课程数据 ----
        self.curriculum_data: Dict = {}

        # ---- 课时时间配置 ----
        self.timetable_data: Dict = {}

        # ---- 加载数据 ----
        self._load_curriculum()
        self._load_timetable()

        logger.info("ScheduleDataManager 初始化完成")

    # ================================================================
    #  读取课表课程数据
    # ================================================================
    def _load_curriculum(self) -> None:
        """根据 self.curriculum_path 读取每周课表数据。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, self.curriculum_path)

        try:
            if not os.path.exists(config_path):
                logger.warning(f"课表数据文件不存在：{config_path}")
                self.curriculum_data = {}
                return

            logger.info(f"找到课表数据文件：{config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                self.curriculum_data = json.load(f)

            days = list(self.curriculum_data.keys())
            logger.info(f"课表数据加载完成：{len(days)} 天（{', '.join(days)}）")

        except json.JSONDecodeError as e:
            logger.error(f"课表数据 JSON 解析失败：{e}")
            self.curriculum_data = {}
        except Exception as e:
            logger.error(f"读取课表数据文件失败：{e}")
            self.curriculum_data = {}

    # ================================================================
    #  读取课时时间配置
    # ================================================================
    def _load_timetable(self) -> None:
        """根据 self.timetable_path 读取课时时间配置。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, self.timetable_path)

        try:
            if not os.path.exists(config_path):
                logger.warning(f"课时配置文件不存在：{config_path}")
                self.timetable_data = {}
                return

            logger.info(f"找到课时配置文件：{config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                self.timetable_data = json.load(f)

            lesson_count = len([
                k for k in self.timetable_data.keys()
                if k.startswith('lesson_')
            ])
            logger.info(f"课时配置加载完成：{lesson_count} 节课")

        except json.JSONDecodeError as e:
            logger.error(f"课时配置 JSON 解析失败：{e}")
            self.timetable_data = {}
        except Exception as e:
            logger.error(f"读取课时配置文件失败：{e}")
            self.timetable_data = {}

    # ================================================================
    #  公开方法：获取课时数量
    # ================================================================
    def get_lesson_count(self) -> int:
        """
        返回时间表中实际课时数量（不包含分隔线）。
        ---------------------------------------
        通过统计 timetable_data 中以 lesson_ 开头的键来计算。

        返回值：
            int：实际课时数量
        """
        return len([k for k in self.timetable_data if k.startswith('lesson_')])

    # ================================================================
    #  公开方法：获取分隔线位置
    # ================================================================
    def get_divider_indices(self) -> List[int]:
        """
        返回分隔线应插入的位置列表（0-based 课时索引）。
        --------------------------------------------
        遍历 timetable_data 的键顺序（保持 JSON 原始顺序），
        每当遇到 dividerline_ 键时，记录其前面最后一个 lesson 的索引。

        例如时间表结构为：
          lesson_1, lesson_2, lesson_3, lesson_4, dividerline_1,
          lesson_5, lesson_6, lesson_7, lesson_8, dividerline_2,
          lesson_9, lesson_10, lesson_11, lesson_12
        则返回 [3, 7]，表示在第3节和第7节之后各有一条分隔线。

        返回值：
            List[int]：分隔线前的课时索引列表（0-based）
        """
        indices: List[int] = []
        lesson_counter: int = 0
        for key in self.timetable_data:
            if key.startswith('lesson_'):
                lesson_counter += 1
            elif key.startswith('dividerline_'):
                # 分隔线出现在当前已计数的课时之后
                indices.append(lesson_counter - 1)
        return indices

    # ================================================================
    #  公开方法：获取指定日的课程表
    # ================================================================
    def get_curriculum_for_day(self, day_name: str) -> Dict[str, str]:
        """
        返回指定星期几的课程表数据。
        -------------------------
        参数：
            day_name（str）：星期名称，如 'Monday', 'Tuesday' 等

        返回值：
            Dict[str, str]：{lesson_key: subject_name} 映射
                           若无数据则返回空字典
        """
        return self.curriculum_data.get(day_name, {})

    # ================================================================
    #  公开方法：保存课程表到文件
    # ================================================================
    def save_curriculum(self) -> bool:
        """
        将当前内存中的 curriculum_data 写回到 JSON 文件。
        ------------------------------------------------
        保持 JSON 键的顺序（Monday → Sunday），使用 UTF-8 编码，
        缩进 4 空格，ensure_ascii=False 保证中文正常显示。

        返回值：
            bool：True 表示保存成功，False 表示保存失败
        """
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, self.curriculum_path)

        # 确保目标目录存在
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        # 按星期顺序排列的键
        day_order: List[str] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                                'Friday', 'Saturday', 'Sunday']
        ordered_data: Dict[str, Any] = {}
        for day in day_order:
            if day in self.curriculum_data:
                ordered_data[day] = self.curriculum_data[day]

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(ordered_data, f, ensure_ascii=False, indent=4)
            logger.info(f"课程表已保存至：{config_path}（共 {len(ordered_data)} 天）")
            return True
        except Exception as e:
            logger.error(f"保存课程表失败：{e}")
            return False

    # ================================================================
    #  公开方法：保存时间表到文件
    # ================================================================
    def save_timetable(self) -> bool:
        """
        将当前内存中的 timetable_data 写回到 JSON 文件。
        ------------------------------------------------
        保持 JSON 键的插入顺序（Python 3.7+ dict 保证），
        使用 UTF-8 编码，缩进 4 空格，ensure_ascii=False。

        返回值：
            bool：True 表示保存成功，False 表示保存失败
        """
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, self.timetable_path)

        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.timetable_data, f, ensure_ascii=False, indent=4)
            entry_count = len(self.timetable_data)
            logger.info(f"时间表已保存至：{config_path}（共 {entry_count} 个条目）")
            return True
        except Exception as e:
            logger.error(f"保存时间表失败：{e}")
            return False

    # ================================================================
    #  公开方法：重新加载或切换时间表
    # ================================================================
    def reload_timetable(self, new_path: str = '') -> bool:
        """
        重新加载或切换到新的时间表文件。
        -----------------------------
        参数：
            new_path（str）：新的时间表文件相对路径，为空则重新加载当前文件

        返回值：
            bool：True 表示加载成功，False 表示加载失败
        """
        if new_path:
            self.timetable_path = new_path
        self.timetable_data = {}
        self._load_timetable()
        return len(self.timetable_data) > 0

    # ================================================================
    #  公开方法：重新加载或切换课程表
    # ================================================================
    def reload_curriculum(self, new_path: str = '') -> bool:
        """
        重新加载或切换到新的课程表文件。
        -----------------------------
        参数：
            new_path（str）：新的课程表文件相对路径，为空则重新加载当前文件

        返回值：
            bool：True 表示加载成功，False 表示加载失败
        """
        if new_path:
            self.curriculum_path = new_path
        self.curriculum_data = {}
        self._load_curriculum()
        return len(self.curriculum_data) > 0

    # ================================================================
    #  静态方法：获取下一个可用的时间表名称
    # ================================================================
    @staticmethod
    def get_next_timetable_name() -> str:
        """
        扫描 timetable 目录，返回下一个可用的 timetable_N.json 名称。
        -----------------------------------------------------------
        返回值：
            str：形如 "timetable_2.json" 的文件名
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        timetable_dir = os.path.join(script_dir, 'Config', 'timetable')
        os.makedirs(timetable_dir, exist_ok=True)

        existing: List[int] = []
        try:
            for f in os.listdir(timetable_dir):
                if f.startswith('timetable_') and f.endswith('.json'):
                    try:
                        num = int(f[len('timetable_'):-len('.json')])
                        existing.append(num)
                    except ValueError:
                        pass
        except OSError:
            pass

        return f"timetable_{max(existing) + 1 if existing else 1}.json"

    # ================================================================
    #  静态方法：获取时间表目录中的所有文件
    # ================================================================
    @staticmethod
    def get_timetable_files() -> List[str]:
        """
        返回时间表目录中所有 JSON 文件的文件名列表。
        -----------------------------------------
        返回值：
            List[str]：文件名列表（仅文件名不含路径）
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        timetable_dir = os.path.join(script_dir, 'Config', 'timetable')
        os.makedirs(timetable_dir, exist_ok=True)

        files: List[str] = []
        try:
            for f in sorted(os.listdir(timetable_dir)):
                if f.endswith('.json'):
                    files.append(f)
        except OSError:
            pass

        return files

    # ================================================================
    #  静态方法：获取课程表目录中的所有文件
    # ================================================================
    @staticmethod
    def get_curriculum_files() -> List[str]:
        """
        返回课程表目录中所有 JSON 文件的文件名列表。
        -----------------------------------------
        返回值：
            List[str]：文件名列表（仅文件名不含路径）
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        curriculum_dir = os.path.join(script_dir, 'Config', 'curriculum')
        os.makedirs(curriculum_dir, exist_ok=True)

        files: List[str] = []
        try:
            for f in sorted(os.listdir(curriculum_dir)):
                if f.endswith('.json'):
                    files.append(f)
        except OSError:
            pass

        return files

    # ================================================================
    #  静态方法：获取下一个可用的课程表名称
    # ================================================================
    @staticmethod
    def get_next_curriculum_name() -> str:
        """
        扫描 curriculum 目录，返回下一个可用的 table_N.json 名称。
        -------------------------------------------------------
        返回值：
            str：形如 "table_2.json" 的文件名
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        curriculum_dir = os.path.join(script_dir, 'Config', 'curriculum')
        os.makedirs(curriculum_dir, exist_ok=True)

        existing: List[int] = []
        try:
            for f in os.listdir(curriculum_dir):
                if f.startswith('table_') and f.endswith('.json'):
                    try:
                        num = int(f[len('table_'):-len('.json')])
                        existing.append(num)
                    except ValueError:
                        pass
        except OSError:
            pass

        return f"table_{max(existing) + 1 if existing else 1}.json"


# ==================== 换课记录管理器 ====================


class SwapManager:
    """
    # SwapManager — 换课记录管理器

    负责管理临时换课记录的持久化、应用和清理。
    ---

    换课记录文件路径：
      Config/swap_schedule.json

    记录格式：
      [
        {
          "day_name": "Tuesday",
          "lesson_key": "lesson_2",
          "old_subject": "数学",
          "new_subject": "体育",
          "swap_date": "2026-08-11"
        }
      ]

    生命周期：
      1. 用户在快捷编辑窗口确认换课 → 记录追加到文件
      2. 软件启动时 → 检查换课记录：
         - swap_date == 今天 → 将 curriculum_data 中对应科目修改为新科目
         - swap_date < 今天   → 删除该条换课记录（已过期）
         - swap_date > 今天   → 保留该记录（尚未到换课日期）
    ---

    对外接口：
      - process_on_startup(curriculum_data) → 处理换课并返回修改后的数据
      - add_swaps(swaps)                     → 追加换课记录到文件
      - load_swaps()                         → 读取所有换课记录
    """

    # 换课记录文件路径（相对于脚本目录）
    SWAP_FILE_PATH: str = 'Config/swap_schedule.json'

    def __init__(self) -> None:
        """初始化换课记录管理器。"""
        self._script_dir: str = os.path.dirname(os.path.abspath(__file__))
        self._swap_file_path: str = os.path.join(
            self._script_dir, self.SWAP_FILE_PATH
        )
        logger.info("SwapManager 初始化完成")

    # ================================================================
    #  公开方法：读取所有换课记录
    # ================================================================
    def load_swaps(self) -> List[Dict]:
        """
        从换课记录文件中读取所有记录。
        ---------------------------
        返回值：
            List[Dict]：换课记录列表，文件不存在或为空时返回空列表
        """
        try:
            if not os.path.exists(self._swap_file_path):
                logger.info("换课记录文件不存在，返回空列表")
                return []
            with open(self._swap_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                logger.debug(f"已加载 {len(data)} 条换课记录")
                return data
            logger.warning("换课记录文件格式异常（非列表），返回空列表")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"换课记录 JSON 解析失败：{e}")
            return []
        except Exception as e:
            logger.error(f"读取换课记录文件失败：{e}")
            return []

    # ================================================================
    #  公开方法：保存换课记录（全量覆盖）
    # ================================================================
    def _save_swaps(self, swaps: List[Dict]) -> bool:
        """
        将换课记录列表完整写入文件（内部方法）。
        ------------------------------------
        参数：
            swaps（List[Dict]）：要保存的换课记录列表

        返回值：
            bool：True 表示保存成功
        """
        try:
            os.makedirs(os.path.dirname(self._swap_file_path), exist_ok=True)
            with open(self._swap_file_path, 'w', encoding='utf-8') as f:
                json.dump(swaps, f, ensure_ascii=False, indent=4)
            logger.info(f"换课记录已保存：{len(swaps)} 条")
            return True
        except Exception as e:
            logger.error(f"保存换课记录失败：{e}")
            return False

    # ================================================================
    #  公开方法：追加换课记录
    # ================================================================
    def add_swaps(self, new_swaps: List[Dict]) -> bool:
        """
        追加新的换课记录到文件中。
        -----------------------
        参数：
            new_swaps（List[Dict]）：要追加的换课记录列表，每项包含
                                    day_name, lesson_key, old_subject,
                                    new_subject, swap_date

        返回值：
            bool：True 表示追加成功
        """
        existing: List[Dict] = self.load_swaps()
        existing.extend(new_swaps)
        success: bool = self._save_swaps(existing)
        if success:
            logger.info(
                f"已追加 {len(new_swaps)} 条换课记录，"
                f"当前共 {len(existing)} 条"
            )
        return success

    # ================================================================
    #  静态方法：获取生效的"今天"日期
    # ================================================================
    @staticmethod
    def _get_effective_today(debug_config=None) -> str:
        """
        获取生效的"今天"日期字符串，优先使用调试配置中的模拟日期。
        -------------------------------------------------------
        参数：
            debug_config（DebugConfig | None）：调试配置管理器，为 None 时使用系统日期

        返回值：
            str：YYYY-MM-DD 格式的日期字符串
        """
        if debug_config is not None and debug_config.enabled:
            debug_dt = debug_config.get_current_datetime()
            if debug_dt is not None:
                return debug_dt.strftime('%Y-%m-%d')
        return datetime.now().strftime('%Y-%m-%d')

    # ================================================================
    #  公开方法：启动时处理换课记录
    # ================================================================
    def process_on_startup(self, curriculum_data: Dict,
                           debug_config=None) -> Dict:
        """
        软件启动时调用：应用今日换课并清理过期记录。
        -----------------------------------------
        处理逻辑：
          1. 读取所有换课记录
          2. 遍历每条记录：
             - swap_date == 今天 → 将 curriculum_data 中对应位置修改为新科目
             - swap_date < 今天   → 标记为待删除
             - swap_date > 今天   → 保留（未来换课）
          3. 移除待删除记录并写回文件
          4. 返回修改后的 curriculum_data

        参数：
            curriculum_data（Dict）：当前内存中的课表数据
            debug_config（DebugConfig | None）：调试配置，传入后使用模拟日期

        返回值：
            Dict：应用了今日换课后的课表数据（可能未被修改）
        """
        swaps: List[Dict] = self.load_swaps()
        if not swaps:
            logger.info("无换课记录需要处理")
            return curriculum_data

        today_str: str = self._get_effective_today(debug_config)
        logger.info(
            f"开始处理换课记录：共 {len(swaps)} 条，今天={today_str}"
        )

        kept_swaps: List[Dict] = []
        applied_count: int = 0
        removed_count: int = 0

        for swap in swaps:
            swap_date: str = swap.get('swap_date', '')

            if swap_date == today_str:
                # 今天需要换课 → 应用到 curriculum_data
                self._apply_swap(curriculum_data, swap)
                applied_count += 1
                # 今天换课后，记录保留到明天再删除
                kept_swaps.append(swap)

            elif swap_date < today_str:
                # 已过期的换课 → 删除记录
                logger.info(
                    f"清理过期换课记录：{swap.get('day_name', '')} "
                    f"{swap.get('lesson_key', '')} "
                    f"'{swap.get('old_subject', '')}' → "
                    f"'{swap.get('new_subject', '')}' "
                    f"({swap_date})"
                )
                removed_count += 1

            else:
                # 未来换课 → 保留
                kept_swaps.append(swap)

        # 如果有删除，写回文件
        if removed_count > 0 or applied_count > 0:
            self._save_swaps(kept_swaps)

        logger.info(
            f"换课处理完成：应用 {applied_count} 条，"
            f"清理 {removed_count} 条，保留 {len(kept_swaps) - applied_count} 条未来换课"
        )

        return curriculum_data

    # ================================================================
    #  私有方法：将单条换课应用到 curriculum_data
    # ================================================================
    @staticmethod
    def _apply_swap(curriculum_data: Dict, swap: Dict) -> None:
        """
        将一条换课记录应用到课表数据中（直接修改 dict）。
        ----------------------------------------------
        参数：
            curriculum_data（Dict）：课表数据
            swap           （Dict）：换课记录
        """
        day_name: str = swap.get('day_name', '')
        lesson_key: str = swap.get('lesson_key', '')
        new_subject: str = swap.get('new_subject', '')

        if not day_name or not lesson_key:
            logger.warning(f"换课记录缺少必要字段：{swap}")
            return

        if day_name in curriculum_data:
            old_value: str = curriculum_data[day_name].get(lesson_key, '')
            curriculum_data[day_name][lesson_key] = new_subject
            logger.info(
                f"已应用换课：{day_name} {lesson_key} "
                f"'{old_value}' → '{new_subject}'"
            )
        else:
            logger.warning(
                f"课表数据中不存在 {day_name}，无法应用换课"
            )


# ==================== 调试配置管理器 ====================


class DebugConfig:
    """
    # DebugConfig — 调试配置管理器

    读取 Config/debug_config.ini，提供模拟时间覆盖功能。
    启用后各参数独立生效：有值则覆盖系统值，留空则回退到系统真实值。
    ---

    ★ 时间流动机制：
      加载配置时记录两个锚点：
        - _anchor_real：当前真实系统时间
        - _debug_start：由调试参数组合的起始时间
      之后每次获取当前时间时：
        当前调试时间 = _debug_start + (真实现在 - _anchor_real)
      这样调试时间会像真实时间一样自然流逝。

    对外属性：
      - enabled   — 调试模式是否启用
      - year      — 模拟年份（None 表示使用真实年份）
      - month     — 模拟月份（None 表示使用真实月份）
      - day       — 模拟日期（None 表示使用真实日期）
      - time_str  — 模拟时间字符串 "HH:MM:SS"（None 表示使用真实时间）
      - weekday   — 模拟星期（None 表示使用真实星期或由日期推算）

    对外方法：
      - get_current_datetime() → Optional[datetime]  流动的当前调试时间
      - get_current_time_str()  → Optional[str]      流动的当前时间 "HH:MM:SS"
      - get_weekday_name()      → Optional[str]      当前英文星期名
    """

    # 合法的英文星期名集合
    _VALID_WEEKDAYS: set = {
        'Monday', 'Tuesday', 'Wednesday', 'Thursday',
        'Friday', 'Saturday', 'Sunday',
    }

    def __init__(self) -> None:
        """初始化调试配置管理器，从 INI 文件读取参数并建立时间锚点。"""
        logger.info("DebugConfig 初始化开始")

        # ---- 默认值（调试禁用）----
        self.enabled: bool = False
        self.year: Optional[int] = None
        self.month: Optional[int] = None
        self.day: Optional[int] = None
        self.time_str: Optional[str] = None
        self.weekday: Optional[str] = None

        # ---- 时间流动锚点 ----
        self._anchor_real: datetime = datetime.now()
        self._debug_start: Optional[datetime] = None

        # ---- 加载配置 ----
        self._load()

        # ---- 构建调试起始时间 ----
        if self.enabled:
            self._build_debug_start()

        logger.info(f"DebugConfig 初始化完成：enabled={self.enabled}, "
                    f"year={self.year}, month={self.month}, day={self.day}, "
                    f"time={self.time_str}, weekday={self.weekday}, "
                    f"debug_start={self._debug_start}")

    # ================================================================
    #  读取调试配置文件
    # ================================================================
    def _load(self) -> None:
        """从 Config/debug_config.ini 读取调试参数。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'debug_config.ini')

        try:
            if not os.path.exists(config_path):
                logger.info(f"调试配置文件不存在：{config_path}，调试模式保持禁用")
                return

            logger.info(f"找到调试配置文件：{config_path}")
            parser: ConfigParser = ConfigParser()
            parser.read(config_path, encoding='utf-8')

            # --- enabled ---
            enabled_str: str = parser.get('Debug', 'enabled', fallback='false')
            self.enabled = enabled_str.strip().lower() == 'true'

            if not self.enabled:
                logger.info("调试模式未启用，使用系统真实时间")
                return

            logger.info("调试模式已启用，读取时间覆盖参数...")

            # --- year ---
            year_str: str = parser.get('Debug', 'year', fallback='').strip()
            if year_str:
                try:
                    y = int(year_str)
                    if 2024 <= y <= 2099:
                        self.year = y
                    else:
                        logger.warning(f"year={y} 超出范围，回退到系统年份")
                except ValueError:
                    logger.warning(f"year='{year_str}' 格式无效，回退到系统年份")

            # --- month ---
            month_str: str = parser.get('Debug', 'month', fallback='').strip()
            if month_str:
                try:
                    m = int(month_str)
                    if 1 <= m <= 12:
                        self.month = m
                    else:
                        logger.warning(f"month={m} 超出范围，回退到系统月份")
                except ValueError:
                    logger.warning(f"month='{month_str}' 格式无效，回退到系统月份")

            # --- day ---
            day_str: str = parser.get('Debug', 'day', fallback='').strip()
            if day_str:
                try:
                    d = int(day_str)
                    if 1 <= d <= 31:
                        self.day = d
                    else:
                        logger.warning(f"day={d} 超出范围，回退到系统日期")
                except ValueError:
                    logger.warning(f"day='{day_str}' 格式无效，回退到系统日期")

            # --- time ---
            time_val: str = parser.get('Debug', 'time', fallback='').strip()
            if time_val:
                parts = time_val.split(':')
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
                        self.time_str = time_val
                    else:
                        logger.warning(f"time='{time_val}' 值超出范围，回退到系统时间")
                else:
                    logger.warning(f"time='{time_val}' 格式无效（需 HH:MM:SS），回退到系统时间")

            # --- weekday ---
            weekday_val: str = parser.get('Debug', 'weekday', fallback='').strip()
            if weekday_val:
                if weekday_val in self._VALID_WEEKDAYS:
                    self.weekday = weekday_val
                else:
                    logger.warning(
                        f"weekday='{weekday_val}' 无效"
                        f"（需为 Monday~Sunday），回退到系统星期"
                    )

        except Exception as e:
            logger.error(f"读取调试配置文件失败：{e}，调试模式保持禁用")
            self.enabled = False

    # ================================================================
    #  构建调试起始时间
    # ================================================================
    def _build_debug_start(self) -> None:
        """
        根据调试参数构建起始 datetime，并重新记录锚点。
        ---------------------------------------------
        各参数独立回退：有调试值用调试值，无则用真实系统值。
        构建后立即更新锚点，确保流逝计算从此刻开始。
        """
        now: datetime = datetime.now()
        self._anchor_real = now

        y: int = self.year if self.year is not None else now.year
        m: int = self.month if self.month is not None else now.month
        d: int = self.day if self.day is not None else now.day

        if self.time_str:
            h, mi, s = map(int, self.time_str.split(':'))
        else:
            h, mi, s = now.hour, now.minute, now.second

        try:
            self._debug_start = datetime(y, m, d, h, mi, s)
        except ValueError:
            logger.warning(f"调试日期无效：{y}-{m:02d}-{d:02d}，回退到系统日期")
            self._debug_start = datetime(now.year, now.month, now.day, h, mi, s)

        logger.info(f"调试时间锚点已建立：start={self._debug_start}, "
                    f"anchor_real={self._anchor_real}")

    # ================================================================
    #  公开方法：获取流动的当前调试时间
    # ================================================================
    def get_current_datetime(self) -> Optional[datetime]:
        """
        返回流动的当前调试 datetime。
        ----------------------------
        计算公式：_debug_start + (datetime.now() - _anchor_real)

        若调试禁用返回 None，调用方应使用系统真实时间。

        返回值：
            Optional[datetime]：流动的当前调试时间；None 表示不使用
        """
        if not self.enabled or self._debug_start is None:
            return None
        elapsed = datetime.now() - self._anchor_real
        return self._debug_start + elapsed

    # ================================================================
    #  公开方法：获取流动的当前时间字符串
    # ================================================================
    def get_current_time_str(self) -> Optional[str]:
        """
        返回流动的当前调试时间字符串 "HH:MM:SS"。
        -----------------------------------------
        若调试禁用返回 None，调用方应使用系统真实时间。

        返回值：
            Optional[str]：当前时间字符串；None 表示不使用
        """
        dt: Optional[datetime] = self.get_current_datetime()
        return dt.strftime('%H:%M:%S') if dt else None

    # ================================================================
    #  公开方法：获取当前英文星期名
    # ================================================================
    def get_weekday_name(self) -> Optional[str]:
        """
        返回当前英文星期名（如 'Monday'）。
        -----------------------------------
        优先级：
          1. weekday 参数显式设置 → 直接返回（静态，不随流动时间变化）
          2. 由流动的当前时间推算 → 可跨越午夜自动切换
          3. 调试禁用 → 返回 None（调用方使用系统真实星期）

        返回值：
            Optional[str]：英文星期名；None 表示不使用调试时间
        """
        if not self.enabled:
            return None

        # weekday 显式设置时优先使用
        if self.weekday is not None:
            return self.weekday

        # 否则由流动的当前时间推算
        dt: Optional[datetime] = self.get_current_datetime()
        return dt.strftime('%A') if dt else None


# ==================== 显示规则管理器 ====================


# 中文星期（一~日）到 ISO 星期（0=周一 .. 6=周日）的映射
_WEEKDAY_CN_TO_INT: Dict[str, int] = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6,
}

# 中文日期片段正则：YYYY年M月D日
_DATE_PATTERN: str = r'(\d{4})年(\d{1,2})月(\d{1,2})日'


def parse_display_rule(text: str) -> Optional[Tuple]:
    """
    解析显示规则文本，返回结构化结果。
    --------------------------------
    参数：
        text（str）：规则文本，例如 '每周一'、'每月15日'、
                     '每年8月17日'、'2026年8月17日到2026年9月17日'

    返回值：
        ('weekly', weekday)        — 每周X，weekday 0=周一..6=周日
        ('monthly', day)           — 每月X日，day 1..31
        ('yearly', month, day)     — 每年X月X日
        ('range', start, end)      — 时间段（date 对象，start != end）
        None                       — 无法解析
    """
    if not text:
        return None
    text = text.strip()

    # 每周X
    m = re.fullmatch(r'每周([一二三四五六日])', text)
    if m:
        return ('weekly', _WEEKDAY_CN_TO_INT[m.group(1)])

    # 每月X日
    m = re.fullmatch(r'每月(\d{1,2})日', text)
    if m:
        day: int = int(m.group(1))
        if 1 <= day <= 31:
            return ('monthly', day)

    # 每年X月X日
    m = re.fullmatch(r'每年(\d{1,2})月(\d{1,2})日', text)
    if m:
        month: int = int(m.group(1))
        day = int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return ('yearly', month, day)

    # 时间段（含单日 → 单日视作每年）
    def _parse_date(s: str) -> Optional[date]:
        """解析 'YYYY年M月D日' 为 date，失败返回 None。"""
        mm = re.fullmatch(_DATE_PATTERN, s.strip())
        if not mm:
            return None
        try:
            return date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
        except ValueError:
            return None

    parts: List[str] = [p.strip() for p in text.split('到')]
    if not parts or len(parts) > 2:
        return None

    if len(parts) == 2:
        start: Optional[date] = _parse_date(parts[0])
        end: Optional[date] = _parse_date(parts[1])
        if start is None or end is None:
            return None
        if start == end:
            return ('yearly', start.month, start.day)
        return ('range', start, end)

    # 单日 → 每年
    d: Optional[date] = _parse_date(parts[0])
    if d is None:
        return None
    return ('yearly', d.month, d.day)


class DisplayRulesManager:
    """
    # DisplayRulesManager — 显示规则管理器

    负责显示规则的持久化、优先级维护与当天规则解析。
    ---

    文件路径：
      Config/Display_Rules.json

    数据格式（dict，键 = 系统分配标签，值 = 4 项列表）：
      {
        "rule_1": [1, "每周",
                   "Config/timetable/timetable_1.json",
                   "Config/curriculum/table_1.json"],
        "rule_2": [2, "2026年8月17日到2026年9月17日",
                   "Config/timetable/timetable_2.json",
                   "Config/curriculum/table_2.json"]
      }
      value[0] 优先级（数字越小越优先）
      value[1] 显示规则文本（每周/每月/每年，或时间段）
      value[2] 时间表路径
      value[3] 课程表路径
    ---

    对外接口：
      - load_rules()                    → 读取所有规则
      - add_rule(rule_text, tt, cv)     → 新增规则，返回标签
      - update_rule(tag, rule_text, tt, cv)
      - delete_rule(tag)
      - reorder(ordered_tags)           → 按新顺序重编优先级
      - resolve_for_today(debug_config) → 解析当天应使用的规则
      - persist_resolved_paths(cv, tt)  → 把解析路径写回 schedule_config.ini
    """

    FILE_PATH: str = 'Config/Display_Rules.json'
    INI_PATH: str = 'Config/schedule_config.ini'

    def __init__(self) -> None:
        """初始化显示规则管理器。"""
        self._script_dir: str = os.path.dirname(os.path.abspath(__file__))
        self._file_path: str = os.path.join(self._script_dir, self.FILE_PATH)
        self._ini_path: str = os.path.join(self._script_dir, self.INI_PATH)
        logger.info("DisplayRulesManager 初始化完成")

    # ================================================================
    #  读取 / 保存
    # ================================================================
    def load_rules(self) -> Dict[str, list]:
        """
        读取所有显示规则。
        ----------------
        返回值：
            Dict[str, list]：{标签: [优先级, 规则文本, 时间表, 课程表]}，
                            文件缺失 / 为空 / 非法时返回空字典
        """
        try:
            if not os.path.exists(self._file_path):
                logger.info("显示规则文件不存在，返回空字典")
                return {}
            with open(self._file_path, 'r', encoding='utf-8') as f:
                content: str = f.read()
            if not content.strip():
                logger.info("显示规则文件为空，返回空字典")
                return {}
            data = json.loads(content)
            if isinstance(data, dict):
                logger.debug(f"已加载 {len(data)} 条显示规则")
                return data
            logger.warning("显示规则文件格式异常（非对象），返回空字典")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"显示规则 JSON 解析失败：{e}")
            return {}
        except Exception as e:
            logger.error(f"读取显示规则文件失败：{e}")
            return {}

    def _save_rules(self, rules: Dict[str, list]) -> bool:
        """将规则完整写入文件（内部方法，全量覆盖）。"""
        try:
            os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(rules, f, ensure_ascii=False, indent=4)
            logger.info(f"显示规则已保存：{len(rules)} 条")
            return True
        except Exception as e:
            logger.error(f"保存显示规则失败：{e}")
            return False

    @staticmethod
    def _next_tag(rules: Dict[str, list]) -> str:
        """生成下一个标签 rule_<n>，n = 1 + max(现有编号)。"""
        max_n: int = 0
        for key in rules:
            if key.startswith('rule_'):
                try:
                    max_n = max(max_n, int(key[len('rule_'):]))
                except ValueError:
                    continue
        return f"rule_{max_n + 1}"

    @staticmethod
    def _normalize_priorities(rules: Dict[str, list]) -> Dict[str, list]:
        """按 value[0] 升序重编优先级为 1..N，返回有序新字典。"""
        items = sorted(rules.items(), key=lambda kv: kv[1][0])
        new_rules: Dict[str, list] = {}
        for idx, (tag, rule) in enumerate(items, start=1):
            new_rule = list(rule)
            new_rule[0] = idx
            new_rules[tag] = new_rule
        return new_rules

    # ================================================================
    #  增删改
    # ================================================================
    def add_rule(self, rule_text: str, timetable_path: str,
                 curriculum_path: str) -> str:
        """
        新增一条显示规则（优先级自动追加到末尾）。
        --------------------------------------
        参数：
            rule_text（str）：显示规则文本
            timetable_path（str）：时间表路径
            curriculum_path（str）：课程表路径

        返回值：
            str：系统分配的新标签
        """
        rules: Dict[str, list] = self._normalize_priorities(self.load_rules())
        tag: str = self._next_tag(rules)
        rules[tag] = [len(rules) + 1, rule_text, timetable_path, curriculum_path]
        if self._save_rules(rules):
            logger.info(f"新增显示规则：{tag} '{rule_text}'")
            return tag
        return ''

    def update_rule(self, tag: str, rule_text: str, timetable_path: str,
                    curriculum_path: str) -> bool:
        """更新指定标签的规则（优先级保持不变）。"""
        rules: Dict[str, list] = self.load_rules()
        if tag not in rules:
            logger.warning(f"显示规则标签不存在：{tag}")
            return False
        rule: list = list(rules[tag])
        rule[1] = rule_text
        rule[2] = timetable_path
        rule[3] = curriculum_path
        rules[tag] = rule
        return self._save_rules(rules)

    def delete_rule(self, tag: str) -> bool:
        """删除指定标签的规则，并重编剩余优先级保持连续。"""
        rules: Dict[str, list] = self.load_rules()
        if tag not in rules:
            logger.warning(f"显示规则标签不存在：{tag}")
            return False
        del rules[tag]
        normalized: Dict[str, list] = self._normalize_priorities(rules)
        return self._save_rules(normalized)

    def reorder(self, ordered_tags: List[str]) -> bool:
        """按给定标签顺序重排，并重编优先级 1..N。"""
        rules: Dict[str, list] = self.load_rules()
        new_rules: Dict[str, list] = {}
        idx: int = 1
        for tag in ordered_tags:
            if tag in rules:
                rule: list = list(rules[tag])
                rule[0] = idx
                new_rules[tag] = rule
                idx += 1
        # 防御：不在 ordered_tags 中的规则追加到末尾
        for tag, rule in rules.items():
            if tag not in new_rules:
                rule = list(rule)
                rule[0] = idx
                new_rules[tag] = rule
                idx += 1
        return self._save_rules(new_rules)

    def ensure_default_rule(self, curriculum_path: str,
                            timetable_path: str) -> bool:
        """
        若没有任何显示规则，自动创建一条默认规则：
        从启动当天到未来十年的同一天，使用当前配置的时间表/课程表。
        ---------------------------------------------------------
        参数：
            curriculum_path（str）：当前课程表路径
            timetable_path（str）：当前时间表路径

        返回值：
            bool：True 表示已创建默认规则，False 表示已有规则无需创建
        """
        rules: Dict[str, list] = self.load_rules()
        if rules:
            return False

        today: date = date.today()
        end_year: int = today.year + 10
        end_day: int = min(today.day, self._days_in_month(end_year, today.month))
        end: date = date(end_year, today.month, end_day)
        rule_text: str = (
            f"{today.year}年{today.month}月{today.day}日到"
            f"{end.year}年{end.month}月{end.day}日"
        )
        tag: str = self.add_rule(rule_text, timetable_path, curriculum_path)
        if tag:
            logger.info(f"未检测到显示规则，已自动创建默认规则 {tag}：{rule_text}")
            return True
        return False

    # ================================================================
    #  当天规则解析
    # ================================================================
    @staticmethod
    def _get_effective_today(debug_config=None) -> date:
        """获取生效的「今天」日期，优先调试模拟日期。"""
        if debug_config is not None and debug_config.enabled:
            debug_dt = debug_config.get_current_datetime()
            if debug_dt is not None:
                return debug_dt.date()
        return datetime.now().date()

    @staticmethod
    def _days_in_month(year: int, month: int) -> int:
        """返回指定年月的天数。"""
        if month == 12:
            nxt = date(year + 1, 1, 1)
        else:
            nxt = date(year, month + 1, 1)
        return (nxt - date(year, month, 1)).days

    @staticmethod
    def _last_monthly_date(day_of_month: int, today: date) -> date:
        """返回 today 当天或之前最近的一个「每月X日」日期。"""
        ld = DisplayRulesManager._days_in_month(today.year, today.month)
        d = min(day_of_month, ld)
        candidate = date(today.year, today.month, d)
        if candidate <= today:
            return candidate
        if today.month == 1:
            y, m = today.year - 1, 12
        else:
            y, m = today.year, today.month - 1
        ld = DisplayRulesManager._days_in_month(y, m)
        d = min(day_of_month, ld)
        return date(y, m, d)

    @staticmethod
    def _last_yearly_date(month: int, day_of_month: int, today: date) -> date:
        """返回 today 当天或之前最近的一个「每年X月X日」日期。"""
        ld = DisplayRulesManager._days_in_month(today.year, month)
        d = min(day_of_month, ld)
        candidate = date(today.year, month, d)
        if candidate <= today:
            return candidate
        ld = DisplayRulesManager._days_in_month(today.year - 1, month)
        d = min(day_of_month, ld)
        return date(today.year - 1, month, d)

    @staticmethod
    def _last_active_date(parsed: Tuple, today: date) -> Optional[date]:
        """返回某规则在 today 当天或之前最近的生效日期（未来规则返回 None）。"""
        kind = parsed[0]
        if kind == 'weekly':
            weekday: int = parsed[1]
            delta: int = (today.weekday() - weekday) % 7
            return today - timedelta(days=delta)
        if kind == 'monthly':
            return DisplayRulesManager._last_monthly_date(parsed[1], today)
        if kind == 'yearly':
            return DisplayRulesManager._last_yearly_date(parsed[1], parsed[2], today)
        if kind == 'range':
            start: date = parsed[1]
            end: date = parsed[2]
            if start > today:
                return None  # 未来规则
            if end < today:
                return end
            return today  # 在区间内
        return None

    def resolve_for_today(self, debug_config=None) -> Optional[Tuple[str, str]]:
        """
        解析当天应使用的显示规则。
        -----------------------
        规则：
          1. 每周X / 每月X日 / 每年X月X日 在匹配当天时可用；
             时间段规则 start <= today <= end 时可用。
          2. 多条可用 → 取优先级数字最小者。
          3. 无可用 → 向过去查找，取「最近一条刚生效过」的规则。
          4. 仍无 → 返回 None（沿用默认配置，不写回 INI）。

        参数：
            debug_config（DebugConfig | None）：调试配置

        返回值：
            Optional[Tuple[str, str]]：(timetable_path, curriculum_path)，
                                       无结果时返回 None
        """
        rules: Dict[str, list] = self.load_rules()
        if not rules:
            logger.info("无显示规则，沿用默认配置")
            return None

        today: date = self._get_effective_today(debug_config)
        available: List[Tuple[int, str, list]] = []
        past: List[Tuple[date, int, str, list]] = []

        for tag, rule in rules.items():
            if not isinstance(rule, list) or len(rule) < 4:
                logger.warning(f"显示规则 {tag} 格式非法，已跳过：{rule}")
                continue
            try:
                priority: int = int(rule[0])
            except (ValueError, TypeError):
                logger.warning(f"显示规则 {tag} 优先级非法，已跳过：{rule[0]}")
                continue
            parsed: Optional[Tuple] = parse_display_rule(
                rule[1] if isinstance(rule[1], str) else ''
            )
            if parsed is None:
                logger.warning(f"显示规则 {tag} 文本无法解析：{rule[1]}")
                continue

            last: Optional[date] = self._last_active_date(parsed, today)
            if last is None:
                continue  # 未来规则
            if last == today:
                available.append((priority, tag, rule))
            else:
                past.append((last, priority, tag, rule))

        if available:
            available.sort(key=lambda x: x[0])
            _, tag, rule = available[0]
            logger.info(
                f"命中当天可用显示规则：{tag}（优先级 {rule[0]}）"
            )
            return (rule[2], rule[3])

        if past:
            # 取最近生效日期，并列时取优先级数字最小（更高优先级）
            last_date, _, tag, rule = max(
                past, key=lambda x: (x[0].toordinal(), -x[1])
            )
            logger.info(
                f"当天无可用规则，向过去查找命中：{tag}"
                f"（最近生效于 {last_date.isoformat()}）"
            )
            return (rule[2], rule[3])

        logger.info("无任何可用显示规则（含向过去查找），沿用默认配置")
        return None

    # ================================================================
    #  写回 schedule_config.ini
    # ================================================================
    def persist_resolved_paths(self, curriculum_path: str,
                               timetable_path: str) -> bool:
        """
        把解析出的课程表 / 时间表路径写回 schedule_config.ini。
        ---------------------------------------------------
        采用逐行替换（非 ConfigParser.write），以保留 INI 中原有的注释。

        参数：
            curriculum_path（str）：课程表路径（写入 table 键）
            timetable_path（str）：时间表路径（写入 timetable 键）

        返回值：
            bool：True 表示写回成功
        """
        try:
            if not os.path.exists(self._ini_path):
                logger.warning(f"配置文件不存在，无法写回：{self._ini_path}")
                return False
            with open(self._ini_path, 'r', encoding='utf-8') as f:
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
                    if key == 'table' and not updated['table']:
                        out.append(f"table = {curriculum_path}\n")
                        updated['table'] = True
                        continue
                    if key == 'timetable' and not updated['timetable']:
                        out.append(f"timetable = {timetable_path}\n")
                        updated['timetable'] = True
                        continue
                out.append(line)

            if not updated['table']:
                out.append(f"table = {curriculum_path}\n")
            if not updated['timetable']:
                out.append(f"timetable = {timetable_path}\n")

            with open(self._ini_path, 'w', encoding='utf-8') as f:
                f.writelines(out)
            logger.info(
                f"已将解析路径写回 schedule_config.ini："
                f"table={curriculum_path}, timetable={timetable_path}"
            )
            return True
        except Exception as e:
            logger.error(f"写回 schedule_config.ini 失败：{e}")
            return False


# ==================== 带主题的基础窗口控件 ====================

class ThemedWidget(QWidget):
    """
    # ThemedWidget — 带背景色的基础窗口

    所有前端窗口的基类，通过 paintEvent 直接绘制背景色。
    比样式表 / QPalette 更可靠，不受平台 / 主题影响。
    ---

    使用方式：
        class MyWindow(ThemedWidget):
            def __init__(self, theme_manager: ThemeManager):
                super().__init__(theme_manager, bg_color_attr='back_color')
    """

    def __init__(self, theme_manager: ThemeManager,
                 bg_color_attr: str = 'back_color',
                 parent: QWidget | None = None) -> None:
        """
        初始化基础窗口。
        ---------------
        参数：
            theme_manager （ThemeManager）：全局主题管理器
            bg_color_attr （str）：         用于背景的颜色属性名
                                            可选：'back_color' / 'root_back_color'
            parent        （QWidget | None）：父控件
        """
        super().__init__(parent)
        self._theme: ThemeManager = theme_manager
        self._bg_color_attr: str = bg_color_attr
        self._bg_color: QColor = QColor(getattr(self._theme, bg_color_attr, '#FFFFFF'))

    def set_bg_color(self, bg_hex: str) -> None:
        """动态更新背景颜色并立即重绘。"""
        self._bg_color = QColor(bg_hex)
        self.update()

    def set_bg_color_attr(self, attr: str) -> None:
        """切换背景颜色源属性。"""
        self._bg_color_attr = attr
        self._bg_color = QColor(getattr(self._theme, attr, '#FFFFFF'))
        self.update()

    def refresh_theme(self) -> None:
        """刷新背景色（主题变更后调用）。"""
        self._bg_color = QColor(getattr(self._theme, self._bg_color_attr, '#FFFFFF'))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """直接填充背景色 —— 最可靠的 QWidget 背景实现方式。"""
        painter: QPainter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)
