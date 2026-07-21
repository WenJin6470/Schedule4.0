"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_theme.py（主题管理 + 基础控件）        ║
║                     （统一的主题配置与共享基类）                            ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
本文件为整个前端提供统一的主题管理和基础控件，包括：
  ✅ ThemeManager — 集中管理所有颜色、字体、透明度等主题参数
  ✅ ThemedWidget — 所有窗口的基类，提供 paintEvent 背景填充
  ✅ 工具函数 — get_color / RGB_to_Hex / is_color_dark

所有前端窗口类（主窗口、时间窗口、快捷编辑、设置）均通过
ThemeManager 获取主题颜色，确保全局一致性。
"""

import json
import logging
import os
from configparser import ConfigParser
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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

        # ---- 课表数据 ----
        self.schedule_data: Dict = {}
        self.time_schedules: Dict[str, List[dict]] = {}
        self.active_time_schedule: str = ""
        self.period_times: List[dict] = []
        self.weekly_schedule: Dict[str, List[str]] = {}
        self.current_day_index: int = 0
        self.DAY_ORDER: List[str] = [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
        ]
        self.DAY_NAMES: Dict[str, str] = {
            "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
            "Thursday": "周四", "Friday": "周五",
        }

        # ---- 加载配置 ----
        self._load_config()
        self._load_subject_config()
        self._load_schedule_data()
        self._set_current_day_from_today()

        logger.info(f"ThemeManager 初始化完成：theme={self.theme}, "
                    f"period_count={self.period_count}")

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

        try:
            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在：{config_path}，使用默认值")
                self.period_count = default_period_count
                self.theme = default_theme
                self.language = default_language
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

    # ================================================================
    #  课表数据：加载 / 保存 / 访问
    # ================================================================

    def _load_schedule_data(self) -> None:
        """从 Config/schedule_data.json 读取课表和时间表。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'schedule_data.json')

        try:
            if not os.path.exists(config_path):
                logger.info(f"课表数据文件不存在，生成默认模板：{config_path}")
                self.schedule_data = self._generate_default_schedule_data()
                # 先从 schedule_data 提取到实例变量，再保存
                self._extract_schedule_from_data()
                self._save_schedule_data_to_file()
            else:
                logger.info(f"找到课表数据文件：{config_path}")
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.schedule_data = json.load(f)
                # 从文件加载后提取到实例变量
                self._extract_schedule_from_data()

            # 确保 5 天都存在
            for day in self.DAY_ORDER:
                if day not in self.weekly_schedule:
                    self.weekly_schedule[day] = []

            # ---- period_count 迁移 ----
            stored_count = self.schedule_data.get("period_count", self.period_count)
            if stored_count != self.period_count:
                logger.warning(
                    f"period_count 变化：{stored_count} → {self.period_count}，"
                    f"执行数据迁移"
                )
                self._migrate_period_count(stored_count, self.period_count)

            # ---- 设置活跃时间表 ----
            if (self.active_time_schedule
                    and self.active_time_schedule in self.time_schedules):
                self.period_times = self.time_schedules[self.active_time_schedule]
            elif self.time_schedules:
                self.active_time_schedule = list(self.time_schedules.keys())[0]
                self.period_times = self.time_schedules[self.active_time_schedule]
                self.schedule_data["active_time_schedule"] = self.active_time_schedule
            else:
                self.period_times = []
                self.active_time_schedule = ""

            total_subjects = sum(
                len(v) for v in self.weekly_schedule.values()
            )
            logger.info(
                f"课表数据加载完成：{len(self.time_schedules)} 套时间表，"
                f"活跃='{self.active_time_schedule}'，"
                f"共 {total_subjects} 个科目条目"
            )

        except json.JSONDecodeError as e:
            logger.error(f"课表数据文件 JSON 解析失败：{e}，使用默认模板")
            self.schedule_data = self._generate_default_schedule_data()
            self._extract_schedule_from_data()
            self._save_schedule_data_to_file()
        except Exception as e:
            logger.error(f"读取课表数据文件失败：{e}，使用默认模板")
            self.schedule_data = self._generate_default_schedule_data()
            self._extract_schedule_from_data()

    def _extract_schedule_from_data(self) -> None:
        """从 self.schedule_data 提取所有内部属性（fallback 用）。"""
        self.time_schedules = self.schedule_data.get("time_schedules", {})
        self.active_time_schedule = self.schedule_data.get(
            "active_time_schedule", ""
        )
        self.weekly_schedule = self.schedule_data.get("weekly_schedule", {})
        for day in self.DAY_ORDER:
            if day not in self.weekly_schedule:
                self.weekly_schedule[day] = []
        if (self.active_time_schedule
                and self.active_time_schedule in self.time_schedules):
            self.period_times = self.time_schedules[self.active_time_schedule]
        elif self.time_schedules:
            first_key = list(self.time_schedules.keys())[0]
            self.active_time_schedule = first_key
            self.period_times = self.time_schedules[first_key]
            self.schedule_data["active_time_schedule"] = first_key
        else:
            self.period_times = []
            self.active_time_schedule = ""

    def _set_current_day_from_today(self) -> None:
        """根据系统日期设置 current_day_index，周末默认周一。"""
        weekday = datetime.now().weekday()  # 0=Monday, 6=Sunday
        if weekday >= 5:
            self.current_day_index = 0
            logger.info(f"今天是周末，默认显示周一")
        else:
            self.current_day_index = weekday
        logger.info(
            f"当前显示星期：{self.DAY_NAMES[self.DAY_ORDER[self.current_day_index]]}"
        )

    def _generate_default_schedule_data(self) -> Dict:
        """生成默认模板：三套时间表 + 空白课表。"""
        pc = self.period_count

        def _make_times(start_h: int, start_m: int,
                        period_min: int = 45,
                        break_min: int = 10) -> List[dict]:
            times = []
            h, m = start_h, start_m
            for idx in range(pc):
                end_m = m + period_min
                end_h = h + end_m // 60
                end_m = end_m % 60
                times.append({
                    "start": f"{h:02d}:{m:02d}",
                    "end": f"{end_h:02d}:{end_m:02d}",
                })
                # 午休：第 4 节后间隔 2.5 小时
                if idx == 3:
                    h = 14
                    m = 0
                else:
                    m = end_m + break_min
                    h = end_h + m // 60
                    m = m % 60
            return times

        weekly = {}
        for day in self.DAY_ORDER:
            weekly[day] = [""] * pc

        return {
            "version": 1,
            "period_count": pc,
            "active_time_schedule": "默认",
            "time_schedules": {
                "默认": _make_times(8, 0, 45, 10),
                "夏令时": _make_times(8, 0, 40, 10),
                "冬令时": _make_times(8, 30, 40, 10),
            },
            "weekly_schedule": weekly,
        }

    def _migrate_period_count(self, old_count: int, new_count: int) -> None:
        """period_count 变化时对所有时间表和课表做截断/补齐。"""
        # 迁移所有时间表
        for name, times in self.time_schedules.items():
            if len(times) < new_count:
                # 补齐：按最后一条的时间规律追加
                last = times[-1] if times else {"start": "08:00", "end": "08:45"}
                for i in range(len(times), new_count):
                    times.append({"start": last["start"], "end": last["end"]})
            elif len(times) > new_count:
                self.time_schedules[name] = times[:new_count]
            logger.info(f"时间表 '{name}'：{len(times)} → {new_count} 节")

        # 迁移课表
        for day in self.DAY_ORDER:
            subjects = self.weekly_schedule.get(day, [])
            if len(subjects) < new_count:
                self.weekly_schedule[day] = subjects + (
                    [""] * (new_count - len(subjects))
                )
            elif len(subjects) > new_count:
                self.weekly_schedule[day] = subjects[:new_count]

        # 更新 period_times
        if (self.active_time_schedule
                and self.active_time_schedule in self.time_schedules):
            self.period_times = self.time_schedules[self.active_time_schedule]

        self.schedule_data["period_count"] = new_count
        self.schedule_data["time_schedules"] = self.time_schedules
        self.schedule_data["weekly_schedule"] = self.weekly_schedule
        logger.info(f"period_count 迁移完成：{old_count} → {new_count}")

    def _save_schedule_data_to_file(self) -> None:
        """将 self.schedule_data 写入 JSON 文件（内部方法）。"""
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        config_path: str = os.path.join(script_dir, 'Config', 'schedule_data.json')

        # 同步最新数据到 schedule_data
        self.schedule_data["period_count"] = self.period_count
        self.schedule_data["active_time_schedule"] = self.active_time_schedule
        self.schedule_data["time_schedules"] = self.time_schedules
        self.schedule_data["weekly_schedule"] = self.weekly_schedule
        self.schedule_data["version"] = 1

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.schedule_data, f, ensure_ascii=False, indent=4)
            logger.debug(f"课表数据已写入：{config_path}")
        except IOError as e:
            logger.error(f"写入课表数据文件失败：{e}")

    # ================================================================
    #  公开方法：课表数据访问
    # ================================================================

    def save_schedule_data(self) -> None:
        """公开方法：将当前课表数据写入 JSON 文件。"""
        self._save_schedule_data_to_file()

    def switch_time_schedule(self, name: str) -> bool:
        """
        切换到指定时间表，验证节数一致性。
        返回 True 表示成功，False 表示失败。
        """
        # 1. 存在性检查
        if name not in self.time_schedules:
            logger.error(
                f"时间表 '{name}' 不存在，"
                f"可用：{list(self.time_schedules.keys())}"
            )
            return False

        # 2. 节数一致性检查
        target = self.time_schedules[name]
        if len(target) != self.period_count:
            logger.error(
                f"无法切换时间表：'{name}' 为 {len(target)} 节，"
                f"当前 period_count={self.period_count}，节数不匹配"
            )
            return False

        # 3. 切换
        self.active_time_schedule = name
        self.period_times = target
        self._save_schedule_data_to_file()
        logger.info(f"时间表已切换为 '{name}'（{len(target)} 节）")
        return True

    def get_active_time_schedule_name(self) -> str:
        """返回当前活跃时间表名称。"""
        return self.active_time_schedule

    def get_time_schedule_names(self) -> List[str]:
        """返回所有可用时间表名称列表。"""
        return list(self.time_schedules.keys())

    def get_current_day_name(self) -> str:
        """获取当前选中星期的英文名。"""
        if 0 <= self.current_day_index < len(self.DAY_ORDER):
            return self.DAY_ORDER[self.current_day_index]
        return "Monday"

    def get_current_day_subjects(self) -> List[str]:
        """获取当前选中星期的科目列表。"""
        day_name = self.get_current_day_name()
        subjects = self.weekly_schedule.get(day_name, [])
        while len(subjects) < self.period_count:
            subjects.append("")
        return subjects[:self.period_count]

    def get_period_times(self) -> List[dict]:
        """返回当前活跃时间表。"""
        return self.period_times

    def set_subject(self, day_index: int, period_index: int,
                    subject_name: str) -> None:
        """设置指定星期、指定课时的科目并立即保存。"""
        if 0 <= day_index < len(self.DAY_ORDER):
            day_name = self.DAY_ORDER[day_index]
            if day_name not in self.weekly_schedule:
                self.weekly_schedule[day_name] = [""] * self.period_count
            subjects = self.weekly_schedule[day_name]
            while len(subjects) <= period_index:
                subjects.append("")
            subjects[period_index] = subject_name
            self.weekly_schedule[day_name] = subjects[:self.period_count]
            self._save_schedule_data_to_file()
            logger.debug(
                f"科目已设置：{self.DAY_NAMES.get(day_name, day_name)} "
                f"第{period_index + 1}节 → '{subject_name}'"
            )

    def set_period_time(self, period_index: int, field: str,
                        value: str) -> None:
        """设置指定课时的时间（start 或 end）并同步到命名时间表。"""
        if 0 <= period_index < len(self.period_times):
            self.period_times[period_index][field] = value
            # 同步到命名时间表
            if (self.active_time_schedule
                    and self.active_time_schedule in self.time_schedules):
                if period_index < len(
                    self.time_schedules[self.active_time_schedule]
                ):
                    self.time_schedules[self.active_time_schedule][
                        period_index
                    ][field] = value
            self._save_schedule_data_to_file()
            logger.debug(f"时间已设置：第{period_index + 1}节 {field} = {value}")

    def navigate_day(self, delta: int) -> str:
        """切换星期，delta 为正向后、负向前。返回新星期英文名。"""
        total = len(self.DAY_ORDER)
        self.current_day_index = (self.current_day_index + delta) % total
        new_day = self.DAY_ORDER[self.current_day_index]
        logger.info(f"星期切换：{self.DAY_NAMES[new_day]}")
        return new_day

    def set_display_day(self, day_index: int) -> str:
        """设置显示星期（绝对索引）。返回新星期英文名。"""
        if 0 <= day_index < len(self.DAY_ORDER):
            self.current_day_index = day_index
        day_name = self.DAY_ORDER[self.current_day_index]
        logger.info(f"星期设置为：{self.DAY_NAMES[day_name]}")
        return day_name


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
                 bg_color_attr: str = 'back_color') -> None:
        """
        初始化基础窗口。
        ---------------
        参数：
            theme_manager （ThemeManager）：全局主题管理器
            bg_color_attr （str）：         用于背景的颜色属性名
                                            可选：'back_color' / 'root_back_color'
        """
        super().__init__()
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
