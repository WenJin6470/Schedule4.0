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
from configparser import ConfigParser
from datetime import datetime
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
      - period_count     — 课时数量
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
        self.period_count: int = 7

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
                    f"period_count={self.period_count}, "
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

        default_period_count: int = 7
        default_theme: str = 'lightcolor'
        default_language: str = 'Chinese'
        default_curriculum: str = 'Config/curriculum/table_1.json'
        default_timetable: str = 'Config/timetable/timetable_1.json'

        try:
            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在：{config_path}，使用默认值")
                self.period_count = default_period_count
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

            # --- period_count ---
            period_count_str: str = parser.get('Schedule', 'period_count',
                                               fallback=str(default_period_count))
            period_count: int = int(period_count_str)
            if 1 <= period_count <= 15:
                self.period_count = period_count
            else:
                logger.warning(f"period_count={period_count} 超出范围，使用默认值 {default_period_count}")
                self.period_count = default_period_count

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

            logger.info(f"配置加载完成：period_count={self.period_count}, "
                        f"theme={self.theme}, language={self.language}, "
                        f"curriculum={self.curriculum_path}, "
                        f"timetable={self.timetable_path}, "
                        f"log_retention_days={self.log_retention_days}")

        except (ValueError, TypeError) as e:
            logger.warning(f"配置文件参数格式错误：{e}，使用默认值")
            self.period_count = default_period_count
            self.theme = default_theme
            self.language = default_language
            self.curriculum_path = default_curriculum
            self.timetable_path = default_timetable
            self.fullscreen_bg_folder = 'images/FullScreenBackgrounds/default'
            self.log_retention_days = 7
            self._apply_theme()
        except Exception as e:
            logger.error(f"读取配置文件失败：{e}，使用默认值")
            self.period_count = default_period_count
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
