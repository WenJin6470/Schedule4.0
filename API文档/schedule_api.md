# 📅 电子课表系统 —— 前后端 API 接口说明文档

> **版本**: v2.0（对齐当前代码架构）
> **技术栈**: PySide6 + Python 3.11+
> **架构模式**: 前后端分离（Signal / Slot + 统一动作协议 ActionMessage）
> **入口 / 连接器**: `main.py`

---

## 📌 目录

1. [架构概述](#架构概述)
2. [统一动作协议 —— schedule_actions.py](#统一动作协议--schedule_actionspy)
3. [前端接口](#前端接口)
   - [ScheduleMainWindow —— 课表主窗口](#schedulemainwindow--课表主窗口)
   - [TimeWindow —— 置顶时间窗口](#timewindow--置顶时间窗口)
   - [FullscreenTimeWindow / ExamFullscreenWindow —— 全屏时间窗口](#fullscreentimewindow--examfullscreenwindow--全屏时间窗口)
   - [SubjectSelectWindow / TempSwapWindow —— 快捷编辑模块](#subjectselectwindow--tempswapwindow--快捷编辑模块)
   - [SettingsWindow —— 设置模块](#settingswindow--设置模块)
4. [后端接口 —— schedule_backend.py](#后端接口--schedule_backendpy)
   - [TimeManager 类](#timemanager-类)
   - [ScheduleBackend 类](#schedulebackend-类)
   - [QuickEditHandler 类](#quickedithandler-类)
   - [WindowHelper 类](#windowhelper-类)
   - [LogManager 类](#logmanager-类)
5. [数据 / 配置层 —— schedule_config.py](#数据--配置层--schedule_configpy)
   - [ThemeManager](#thememanager)
   - [ScheduleDataManager](#scheduledatamanager)
   - [SubjectConfigManager](#subjectconfigmanager)
   - [SwapManager](#swapmanager)
   - [DebugConfig](#debugconfig)
   - [DisplayRulesManager](#displayrulesmanager)
   - [ThemedWidget](#themedwidget)
6. [连接器 —— main.py](#连接器--mainpy)
7. [数据流图](#数据流图)
8. [使用示例](#使用示例)

---

## 架构概述

本系统采用**前后端分离 + 发布订阅**架构，将界面显示、业务逻辑与数据配置彻底解耦：

```
┌──────────────────────────────────┐        Signal        ┌──────────────────┐
│          前端窗口模块              │  backend_signal     │                  │
│  schedule_frontend（主窗口）       │ ──────────────────→ │  schedule_backend │
│  schedule_time（时间/全屏窗口）     │   (ActionMessage)   │  TimeManager      │
│  schedule_quick_edit（快捷编辑）   │ ←────────────────── │  ScheduleBackend  │
│  schedule_settings（设置）         │   公开方法 / Signal  │  QuickEditHandler │
└──────────────────────────────────┘                     └────────┬─────────┘
        │ 统一从 ThemeManager 获取主题                              │ 读写
        ▼                                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              schedule_config（数据/配置层）+ knotlink_bridge              │
│  ThemeManager · ScheduleDataManager · SwapManager · DebugConfig · ...   │
└─────────────────────────────────────────────────────────────────────────┘
```

| 层 | 模块 | 职责 |
|----|------|------|
| 🎨 **前端** | `schedule_frontend.py` / `schedule_time.py` / `schedule_quick_edit.py` / `schedule_settings.py` | 创建窗口与控件、捕获用户操作、刷新界面 |
| 📨 **动作协议** | `schedule_actions.py` | `ActionType` 枚举 + 不可变 `ActionMessage`，统一前后端消息格式 |
| 🧠 **后端** | `schedule_backend.py` | 时间广播（TimeManager）、动作分派（ScheduleBackend）、日志管理（LogManager） |
| 📦 **数据层** | `schedule_config.py` | 配置读取、课表/时间表数据、换课、调试时间、显示规则 |
| 🌐 **桥接层** | `knotlink_bridge.py` | KnotLink 协议接口与信号广播 |
| 🔗 **连接器** | `main.py` | 创建所有实例并连接信号与槽 |

**重要原则**：
- 前端不包含业务逻辑：不管理定时器、不直接读写数据文件
- 后端不包含 UI 代码：不创建窗口、不设置样式
- 前后端通信**统一走 `ActionMessage`**，通过 Signal 传递，替代裸字符串 + 手动解析

---

## 统一动作协议 —— schedule_actions.py

### ActionType 枚举

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `CLOSE` | `"close"` | 关闭所有窗口并退出程序 |
| `FULLSCREEN_TIME` | `"fullscreen_time"` | 显示全屏时间窗口（旧版兼容） |
| `FULLSCREEN_TIME_EXAM` | `"fullscreen_time_exam"` | 考试模式全屏时间 |
| `FULLSCREEN_TIME_CREATIVE` | `"fullscreen_time_creative"` | 创意模式全屏时间 |
| `SETTINGS` | `"settings"` | 打开设置窗口 |
| `QUICK_EDIT_OPENED` | `"quick_edit_opened"` | 快捷编辑窗口已打开 |
| `QUICK_EDIT_CLOSED` | `"quick_edit_closed"` | 快捷编辑窗口已关闭 |
| `CONFIRM` | `"confirm"` | 确认编辑操作 |
| `MOVE_UP` | `"move_up"` | 光标向上移动 1 步 |
| `MOVE_DOWN` | `"move_down"` | 光标向下移动 1 步 |
| `MOVE_DOUBLE_UP` | `"move_double_up"` | 光标向上移动 2 步 |
| `MOVE_DOUBLE_DOWN` | `"move_double_down"` | 光标向下移动 2 步 |
| `SUBJECT_SELECTED` | `"subject_selected"` | 用户选择了科目（payload: `name`） |
| `CURSOR_INFO` | `"cursor_info"` | 光标位置信息（payload: `index`, `text`） |
| `WEEK_CHANGED` | `"week_changed"` | 星期滚轮切换（payload: `index`, `week_name`） |
| `TEMP_SWAP_CONFIRMED` | `"temp_swap_confirmed"` | 临时换课确认（payload: `swaps`） |

### ActionMessage

```python
@dataclass(frozen=True)
class ActionMessage:
    type: ActionType                      # 动作类型
    payload: dict[str, Any] = field(default_factory=dict)  # 携带数据
```

- **不可变**（`frozen=True`），可安全地在 Signal 中传递
- 提供工厂方法快速构造：`ActionMessage.close()`、`ActionMessage.settings()`、`ActionMessage.subject_selected(name)`、`ActionMessage.move_up()`、`ActionMessage.temp_swap_confirmed(swaps)` 等

---

## 前端接口

### ScheduleMainWindow —— 课表主窗口

文件：`schedule_frontend.py`，继承 `ThemedWidget`

#### 构造函数

| 参数 | 类型 | 说明 |
|------|------|------|
| `theme_manager` | `ThemeManager` | 全局主题管理器（含配置与颜色） |
| `schedule_data` | `ScheduleDataManager` | 课表数据管理器（时间表 + 课程表） |
| `debug_config` | `DebugConfig` | 调试配置管理器 |

#### 信号

| 信号 | 参数 | 说明 |
|------|------|------|
| `backend_signal` | `ActionMessage` | **统一后端信号**：所有按钮点击、快捷编辑动作均通过此信号发送给后端 |

#### 公开方法

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `get_period_label(index)` | `index: int`（0-based） | `QLabel \| None` | 获取指定课时标签 |
| `get_period_label_by_name(name)` | `name: str` | `QLabel \| None` | 按课时键名（如 `lesson_1`）获取标签 |
| `get_period_count()` | 无 | `int` | 获取课时总数 |
| `get_all_period_labels()` | 无 | `List[QLabel]` | 获取所有课时标签 |
| `update_period_highlight(time_str)` | `time_str: str` | 无 | 按当前时间高亮对应课时标签（由 `TimeManager.time_tick` 驱动） |
| `set_display_week(week_name)` | `week_name: str` | 无 | 切换显示的星期（`Monday`~`Sunday`） |
| `get_display_week()` | 无 | `str` | 获取当前显示的星期 |
| `start_cursor_blink(index)` | `index: int = 0` | `str` | 启动指定课时光标闪烁，返回该课时当前文字 |
| `stop_cursor_blink()` | 无 | 无 | 停止光标闪烁 |
| `move_cursor(steps)` | `steps: int`（正数向下） | `str` | 移动光标并返回新位置文字 |
| `set_cursor_subject(subject_name)` | `subject_name: str` | 无 | 设置光标所在课时的科目 |
| `get_cursor_index()` | 无 | `int` | 获取光标所在课时索引（0-based） |
| `get_cursor_subject()` | 无 | `str` | 获取光标所在课时科目 |

**连接示例**（在 main.py 中）：
```python
main_window.backend_signal.connect(
    lambda msg: backend_handler.handle_action(
        msg, main_window, time_window, fullscreen_window, app,
        exam_window=exam_window,
        subject_window=main_window._subject_window,
    )
)
```

---

### TimeWindow —— 置顶时间窗口

文件：`schedule_time.py`，继承 `ThemedWidget`

屏幕右上角置顶时钟，显示 `HH:MM:SS` 实时时间。窗口属性：无边框、置顶、工具窗口（不在任务栏显示）、半透明。

#### 构造函数

| 参数 | 类型 | 说明 |
|------|------|------|
| `theme_manager` | `ThemeManager` | 全局主题管理器 |

#### 公开方法

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `update_time_display(time_str)` | `time_str: str`（`HH:MM:SS`） | 无 | 更新时间标签文字 |
| `set_always_on_top(enabled)` | `enabled: bool` | 无 | 开启/关闭窗口置顶（进入全屏时取消置顶，退出后恢复） |

---

### FullscreenTimeWindow / ExamFullscreenWindow —— 全屏时间窗口

文件：`schedule_time.py`

| 窗口 | 模式 | 说明 |
|------|------|------|
| `FullscreenTimeWindow` | 创意模式 `creative` | 随机图片背景 + 屏幕中央红色大字实时时钟 |
| `ExamFullscreenWindow` | 考试模式 `exam` | 墨绿色纯色背景 + 可编辑考试起止时间与科目 + 底部实时时间 |

两个窗口默认隐藏，通过快捷按钮或 KnotLink 接口触发显示。

#### 构造函数

| 参数 | 类型 | 说明 |
|------|------|------|
| `theme_manager` | `ThemeManager` | 全局主题管理器 |

#### 信号

| 信号 | 说明 |
|------|------|
| `close_requested` | 用户关闭全屏窗口时发射（main.py 中连接 → 隐藏窗口 + 恢复 TimeWindow 置顶） |

#### 公开方法

| 方法 | 参数 | 用途 |
|------|------|------|
| `show_fullscreen(mode='exam')` | `mode: str` | 显示全屏窗口（仅 FullscreenTimeWindow 支持 `creative` / `exam` 参数） |
| `hide_fullscreen()` | 无 | 隐藏全屏窗口 |
| `update_time_display(time_str)` | `time_str: str` | 更新时间显示（由 `TimeManager.time_tick` 驱动） |
| `set_mode(mode)` | `mode: str` | 切换显示模式（FullscreenTimeWindow） |

---

### SubjectSelectWindow / TempSwapWindow —— 快捷编辑模块

文件：`schedule_quick_edit.py`

#### SubjectSelectWindow（科目选择窗口）

用户点击快捷编辑按钮后弹出。布局：左侧按分类展示科目按钮，右侧移动控制区（倍速上/下、上、下）+ 星期滚轮 + 确定按钮。

**构造函数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `parent_signal` | `SignalInstance` | 父窗口的 `backend_signal`（所有动作回传该信号） |
| `theme_manager` | `ThemeManager` | 全局主题管理器 |
| `initial_week` | `str = 'Monday'` | 初始显示的星期 |
| `main_window` | `ScheduleMainWindow` | 课表主窗口引用（用于临时换课比对） |

**公开方法**：

| 方法 | 参数 | 用途 |
|------|------|------|
| `update_cursor_info(index, subject_text)` | `index: int`, `subject_text: str` | 保留接口（当前状态栏为静态提示） |
| `sync_week(week_name)` | `week_name: str` | 同步星期滚轮到指定星期 |

#### TempSwapWindow（临时换课确认窗口）

确认临时换课后弹出，展示变更列表（原科目 → 新科目、生效日期），支持取消单项、确认全部生效。确认后通过 `TEMP_SWAP_CONFIRMED` 动作回传，由后端 `SwapManager` 写入 `Config/swap_schedule.json`。

---

### SettingsWindow —— 设置模块

文件：`schedule_settings.py`，继承 `ThemedWidget`

多页签设置窗口，左侧导航栏 + 右侧内容面板：

| 页签 | 功能 |
|------|------|
| 基本设置 | 主题（三模式 + 自定义主题色取色器）、字体、语言、开机自启 |
| 时间表编辑 | 课时/课间增删改（滚轮时间选择器）、时间表文件新建/加载/切换 |
| 课程表编辑 | 周一~周日逐格编辑科目（光标闪烁 + 科目按钮点选）、课程表文件管理 |
| 科目管理 | 科目分类增删改、中英文名编辑、在线翻译（多站点自动择优） |
| 显示规则 | 按日期区间/每周几切换时间表课程表，支持优先级排序 |

修改采用**暂存 + 统一应用**策略：点击「应用修改」后统一持久化，部分修改（字体、语言）需重启生效。

---

## 后端接口 —— schedule_backend.py

### TimeManager 类

时间管理类，负责实时时间的获取与广播。内部使用 `QTimer` 每秒触发一次，通过 **`time_tick` Signal** 将当前时间广播给所有订阅者（发布-订阅模式）。

#### 方法列表

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `__init__(debug_config)` | `debug_config: Optional[DebugConfig] = None` | — | 初始化定时器（间隔 1000ms），可注入调试配置 |
| `start()` | 无 | 无 | 启动定时器，立即广播一次时间 |
| `stop()` | 无 | 无 | 停止定时器 |
| `get_current_time()` | 无 | `str` | 手动获取当前时间字符串（调试模式下返回模拟时间） |

#### 信号

| 信号 | 参数 | 说明 |
|------|------|------|
| `time_tick` | `str`（`HH:MM:SS`） | 每秒发射一次，携带当前时间字符串。**多个订阅者可同时连接** |

**行为说明**：
1. `start()` 后**立即发射一次**时间信号（不等 1 秒），确保界面立刻显示时间
2. 支持任意数量订阅者，由 Qt Signal 原生管理
3. `stop()` 仅停止定时器，不自动断开 Signal 连接（订阅者自行管理生命周期）

**示例**：
```python
tm = TimeManager(debug_config=debug_config)
tm.time_tick.connect(time_window.update_time_display)        # 订阅者1
tm.time_tick.connect(fullscreen_window.update_time_display)  # 订阅者2
tm.time_tick.connect(main_window.update_period_highlight)    # 订阅者3
tm.start()
```

---

### ScheduleBackend 类

后端信号处理器：接收前端统一的 `backend_signal`，根据 `ActionMessage.type` 分派给对应业务逻辑。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `__init__()` | 无 | — | 初始化，创建 `QuickEditHandler` 实例 |
| `handle_action(msg, main_window, time_window, fullscreen_window, app, exam_window=None, subject_window=None)` | 见下 | 无 | 处理前端动作消息 |

**handle_action 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `msg` | `ActionMessage` | 结构化动作消息 |
| `main_window` | `ScheduleMainWindow` | 课表主窗口引用 |
| `time_window` | `TimeWindow` | 置顶时间窗口引用 |
| `fullscreen_window` | `FullscreenTimeWindow` | 全屏时间窗口引用（创意模式） |
| `app` | `QApplication` | QApplication 实例 |
| `exam_window` | `ExamFullscreenWindow` | 考试模式全屏窗口引用（可选） |
| `subject_window` | `SubjectSelectWindow` | 快捷编辑窗口引用（可选） |

**动作分派规则**：
- 快捷编辑类（`QUICK_EDIT_*`、`SUBJECT_SELECTED`、`MOVE_*`、`CONFIRM`、`CURSOR_INFO`、`WEEK_CHANGED`、`TEMP_SWAP_CONFIRMED`）→ 委托 `QuickEditHandler`
- `CLOSE` → 停止光标闪烁 + `WindowHelper.close_all()` 关闭所有窗口并退出
- `FULLSCREEN_TIME` → 显示全屏时间窗口（旧版兼容，考试模式）
- `FULLSCREEN_TIME_EXAM` → 考试模式全屏（`ExamFullscreenWindow`）
- `FULLSCREEN_TIME_CREATIVE` → 创意模式全屏（`FullscreenTimeWindow`）

---

### QuickEditHandler 类

快捷编辑专属后端处理器，持有主窗口引用，通过其公开 API 操作课时标签。

| 方法 | 参数 | 用途 |
|------|------|------|
| `handle(msg, main_window, subject_window=None)` | `ActionMessage`, `ScheduleMainWindow`, `Optional[SubjectSelectWindow]` | 分发快捷编辑动作 |

内部处理流程示例：
- `QUICK_EDIT_OPENED` → 启动第 1 节光标闪烁
- `SUBJECT_SELECTED` → 更新光标科目并自动下移光标
- `MOVE_UP / MOVE_DOWN / MOVE_DOUBLE_*` → 移动光标
- `CONFIRM` → 同步标签修改回 `curriculum_data` → `save_curriculum()` 写文件 → 停止闪烁 → 隐藏窗口
- `TEMP_SWAP_CONFIRMED` → `SwapManager.add_swaps()` 写入换课记录并立即应用

---

### WindowHelper 类

辅助功能类，所有方法均为静态方法。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `close_all(widgets, app)` | `widgets: List[Optional[QWidget]]`, `app: QApplication` | 无 | 关闭所有窗口并退出程序 |

**执行流程**：遍历 `widgets` 逐个 `close()`（`None` 自动跳过）→ `app.quit()` 退出事件循环。

```python
WindowHelper.close_all([time_window, main_window, fullscreen_window, exam_window], app)
```

---

### LogManager 类

日志管理类，负责清理过期日志文件。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `cleanup_old_logs(log_dir, retention_days, logger=None)` | `str`, `int`, `Optional[Logger]` | `int` | 清理超过保留天数的 `schedule_YYYY-MM-DD.log` 文件，返回删除数量 |

`retention_days ≤ 0` 时跳过清理。启动时由 main.py 调用。

---

## 数据 / 配置层 —— schedule_config.py

### ThemeManager

全局主题管理器，从 `Config/schedule_config.ini` 读取配置并统一提供给所有窗口。

**对外属性**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `theme` | `str` | 主题名：`lightcolor` / `darkcolor` / `multicolor` |
| `theme_color` | `str` | 彩色模式主题色（`#rrggbb`） |
| `language` | `str` | 显示语言：`Chinese` / `English` |
| `back_color` / `root_back_color` / `main_back_color` | `str` | 各窗口背景色 |
| `font_color` / `main_font_color` / `time_color` / `border_color` | `str` | 各区域文字 / 时间 / 分割线颜色 |
| `subject_font` | `str` | 主窗口科目字体家族名 |
| `window_opacity` | `float` | 窗口透明度 |
| `subject_config` | `Dict` | 科目分类配置 |
| `curriculum_path` / `timetable_path` | `str` | 课程表 / 时间表 JSON 路径 |
| `log_retention_days` | `int` | 日志保留天数 |
| `fullscreen_bg_folder` | `str` | 创意模式背景图片文件夹 |

**公开方法**：

| 方法 | 返回值 | 用途 |
|------|--------|------|
| `get_icon_suffix()` | `str` | 根据主题返回图标后缀（深色主题返回 `-w`） |

### ScheduleDataManager

课表数据管理器，读取课程表与时间表 JSON 到内存。

**对外属性**：`curriculum_data`（`Dict`，星期 → 当日科目）、`timetable_data`（`Dict`，`lesson_N` → `[开始, 结束]`）、`curriculum_path`、`timetable_path`。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `get_lesson_count()` | 无 | `int` | 实际课时数量（不含分隔线） |
| `get_divider_indices()` | 无 | `List[int]` | 分隔线前课时索引（0-based） |
| `get_curriculum_for_day(day_name)` | `str` | `Dict[str, str]` | 指定星期的 `{lesson_key: subject}` |
| `save_curriculum()` | 无 | `bool` | 保存课程表到文件 |
| `save_timetable()` | 无 | `bool` | 保存时间表到文件 |
| `reload_timetable(new_path='')` | `str` | `bool` | 重新加载时间表（可换文件） |
| `reload_curriculum(new_path='')` | `str` | `bool` | 重新加载课程表（可换文件） |
| `get_timetable_files()` / `get_curriculum_files()` | 无 | `List[str]` | 列出可用时间表 / 课程表文件 |

### SubjectConfigManager

科目分类配置管理器，读写 `Config/subject_config.json`。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `load()` | 无 | `Dict` | 加载科目分类数据 |
| `save(data)` | `Dict` | `bool` | 保存科目分类数据 |
| `category_names(data)` | `Dict` | `List[str]` | 分类名称列表 |
| `all_subjects(data)` | `Dict` | `List[Tuple]` | 全部科目（分类, 名称, 英文名） |
| `find_subject(data, name)` | `Dict`, `str` | `Optional[Tuple]` | 按名称查找科目 |

### SwapManager

临时换课管理器，读写 `Config/swap_schedule.json`。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `load_swaps()` | 无 | `List[Dict]` | 加载换课记录 |
| `add_swaps(new_swaps)` | `List[Dict]` | `bool` | 追加换课记录 |
| `process_on_startup(curriculum_data, debug_config=None)` | `Dict`, `Optional[DebugConfig]` | 无 | 启动时应用今日换课、清理过期记录 |

换课记录字段：`day_name`（`Monday`~`Sunday`）、`lesson_key`（`lesson_N`）、`old_subject`、`new_subject`、`swap_date`（`YYYY-MM-DD`，仅当天生效）。

### DebugConfig

调试配置管理器，读取 `Config/debug_config.ini`，可模拟日期 / 时间 / 星期（各参数独立回退）。

| 方法 | 返回值 | 用途 |
|------|--------|------|
| `get_current_datetime()` | `Optional[datetime]` | 模拟（或真实）当前日期时间 |
| `get_current_time_str()` | `Optional[str]` | 模拟（或真实）当前时间字符串 |
| `get_weekday_name()` | `Optional[str]` | 模拟（或真实）星期名称 |

### DisplayRulesManager

显示规则管理器，读写 `Config/Display_Rules.json`，按日期区间 / 每周几自动切换时间表与课程表。

| 方法 | 参数 | 返回值 | 用途 |
|------|------|--------|------|
| `add_rule(rule_text, timetable_path, curriculum_path)` | `str`, `str`, `str` | `bool` | 新增规则 |
| `update_rule(tag, rule_text, timetable_path, curriculum_path)` | `str`, `str`, `str`, `str` | `bool` | 更新规则 |
| `delete_rule(tag)` | `str` | `bool` | 删除规则 |
| `reorder(ordered_tags)` | `List[str]` | `bool` | 调整规则优先级 |
| `ensure_default_rule(curriculum_path, timetable_path)` | `str`, `str` | 无 | 无规则时自动创建默认规则（当天起十年） |
| `resolve_for_today(debug_config=None)` | `Optional[DebugConfig]` | `Optional[Tuple[str, str]]` | 解析今天命中的（timetable, curriculum）路径 |
| `persist_resolved_paths(curriculum_path, timetable_path)` | `str`, `str` | 无 | 将命中路径写回 INI |

### ThemedWidget

所有窗口的基类，自动应用主题背景色。构造函数：`ThemedWidget(theme_manager, bg_color_attr='back_color')`。

| 方法 | 参数 | 用途 |
|------|------|------|
| `set_bg_color(bg_hex)` | `str` | 设置背景色 |
| `refresh_theme()` | 无 | 刷新主题（设置修改后调用） |

---

## 连接器 —— main.py

`main.py` 是程序入口，负责配置日志、创建所有实例并连接前后端。

### 启动流程

```
1. 配置日志系统（文件 + 终端彩色输出）
2. 创建 QApplication
3. 创建 ThemeManager（读取 INI 配置）
3.5 清理过期日志（LogManager.cleanup_old_logs）
3c. 创建 DebugConfig（调试时间）
3d. 解析显示规则（DisplayRulesManager，命中则切换时间表/课程表）
3b. 创建 ScheduleDataManager（读取课程表和时间表）
3e. 处理换课记录（SwapManager.process_on_startup）
4. 创建前端窗口：TimeWindow（优先显示）→ ScheduleMainWindow → FullscreenTimeWindow → ExamFullscreenWindow
5. 创建后端：TimeManager + ScheduleBackend
5.5 启动 TranslationMonitor（翻译网站监测）
6. 连接信号与槽
7. 显示主窗口
6.5 延迟初始化 KnotLinkBridge（QTimer.singleShot(0, ...)）
8. 启动事件循环
```

### 连接关系

```
┌────────────────────────────────────────────────────────────────────────┐
│                         main.py 连接关系                                │
│                                                                        │
│  连接1：时间广播（发布-订阅，多订阅者）                                    │
│  ┌──────────────┐ time_tick(str)  ┌────────────────────────────────┐   │
│  │ TimeManager  │ ──────────────→ │ TimeWindow.update_time_display │   │
│  │   .start()   │                 │ FullscreenTimeWindow.update... │   │
│  │              │                 │ ExamFullscreenWindow.update... │   │
│  │              │                 │ ScheduleMainWindow.update_...  │   │
│  └──────────────┘                 └────────────────────────────────┘   │
│                                                                        │
│  连接2：全屏窗口关闭 → 隐藏 + 恢复置顶                                    │
│  FullscreenTimeWindow.close_requested → (hide(), time_window.set_top)  │
│  ExamFullscreenWindow.close_requested  → (hide(), time_window.set_top) │
│                                                                        │
│  连接3：主窗口统一动作信号 → 后端分派                                     │
│  ┌───────────────────┐  backend_signal  ┌────────────────┐           │
│  │ ScheduleMainWindow│ ───────────────→ │ ScheduleBackend │           │
│  │  .backend_signal  │   (ActionMessage)│ .handle_action  │           │
│  └───────────────────┘                  └────────────────┘           │
│                                                                        │
│  连接4：KnotLinkBridge 订阅 time_tick → 上课/下课事件检测           │
│  TimeManager.time_tick → KnotLinkBridge._on_time_tick                  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流图

### 时间更新流程（每 1 秒）

```
┌──────────┐ timeout(1000ms) ┌──────────────┐ time_tick.emit("14:30:05")
│  QTimer  │ ──────────────→ │ TimeManager  │ ──────────────────────────┐
│  (内部)   │                │  ._on_timeout │                          ▼
└──────────┘                └──────────────┘                ┌──────────────────────┐
                                                             │  多个订阅者（Signal）  │
                                                             │ TimeWindow 时间标签    │
                                                             │ FullscreenTimeWindow  │
                                                             │ ScheduleMainWindow    │
                                                             │  课时高亮              │
                                                             │ KnotLinkBridge        │
                                                             │  状态切换检测          │
                                                             └──────────────────────┘
```

### 按钮操作流程（以关闭为例）

```
┌──────────┐ clicked ┌───────────────────┐ backend_signal.emit ┌────────────────┐
│ 用户点击  │ ──────→ │ ScheduleMainWindow │ ──────────────────→ │ ScheduleBackend│
│ 关闭按钮  │         │ ._on_close_clicked │   (ActionMessage)   │ .handle_action │
└──────────┘         └───────────────────┘                     └───────┬────────┘
                                                                       │ CLOSE 分支
                                                              ┌────────▼────────┐
                                                              │ WindowHelper    │
                                                              │ .close_all(...) │ → app.quit()
                                                              └─────────────────┘
```

### 快捷编辑流程

```
用户点击快捷编辑按钮
      │  ScheduleMainWindow 发射 QUICK_EDIT_OPENED
      ▼
ScheduleBackend.handle_action → QuickEditHandler.handle
      │
      ├─ 打开 SubjectSelectWindow（科目选择 + 星期滚轮 + 移动控制）
      ├─ 科目点选 → SUBJECT_SELECTED → 更新光标标签 + 自动下移光标
      ├─ 临时换课 → TEMP_SWAP_CONFIRMED → SwapManager.add_swaps 写文件 + 立即应用
      └─ 确定 → CONFIRM → 同步课程表 → save_curriculum() → 停止闪烁 → 关闭窗口
```

---

## 使用示例

### 基本运行

```bash
# 在虚拟环境中运行
venv\Scripts\python main.py
```

### 自定义启动（最小接线示例）

```python
import sys
from PySide6.QtWidgets import QApplication
from schedule_config import ThemeManager, ScheduleDataManager, DebugConfig
from schedule_time import TimeWindow, FullscreenTimeWindow, ExamFullscreenWindow
from schedule_frontend import ScheduleMainWindow
from schedule_backend import TimeManager, ScheduleBackend

app = QApplication(sys.argv)

theme_manager = ThemeManager()
schedule_data = ScheduleDataManager(
    curriculum_path=theme_manager.curriculum_path,
    timetable_path=theme_manager.timetable_path,
)
debug_config = DebugConfig()

time_window = TimeWindow(theme_manager)
main_window = ScheduleMainWindow(theme_manager, schedule_data, debug_config)
fullscreen_window = FullscreenTimeWindow(theme_manager)
exam_window = ExamFullscreenWindow(theme_manager)

time_manager = TimeManager(debug_config=debug_config)
backend = ScheduleBackend()

# 连接：时间广播（多订阅者）
time_manager.time_tick.connect(time_window.update_time_display)
time_manager.time_tick.connect(fullscreen_window.update_time_display)
time_manager.time_tick.connect(exam_window.update_time_display)
time_manager.time_tick.connect(main_window.update_period_highlight)
time_manager.start()

# 连接：统一动作信号
main_window.backend_signal.connect(
    lambda msg: backend.handle_action(
        msg, main_window, time_window, fullscreen_window, app,
        exam_window=exam_window,
        subject_window=main_window._subject_window,
    )
)

time_window.show()
main_window.show()
sys.exit(app.exec())
```

### 手动驱动后端动作

```python
from schedule_actions import ActionMessage, ActionType

# 直接向后端发送一个"全屏时间（考试模式）"动作
backend.handle_action(
    ActionMessage.fullscreen_time_exam(),
    main_window, time_window, fullscreen_window, app,
    exam_window=exam_window,
)
```

---

## 与原版本的对应关系

| 原 v1.0 架构 | 当前 v2.0 架构 |
|--------------|----------------|
| `schedule_frontend.py` → `ScheduleClassroomFrontend` | `schedule_frontend.py` → `ScheduleMainWindow`（主窗口）+ `schedule_time.py` → `TimeWindow`（时间窗口） |
| `ScheduleClassroomFrontend` 的 4 个独立 Signal | `ScheduleMainWindow.backend_signal` 统一信号 + `ActionMessage` 动作协议 |
| `TimeManager.start(callback)` 回调式 | `TimeManager.time_tick` Signal 发布-订阅（多订阅者） |
| `WindowHelper.close_all()` | 保留，由 `ScheduleBackend` 在 `CLOSE` 动作中调用 |
| 无数据层 | `schedule_config.py`（ThemeManager / ScheduleDataManager / SwapManager / DebugConfig / DisplayRulesManager） |
| 无外部协议 | `knotlink_bridge.py`（3 接口 + 2 信号） |
| 功能待实现的占位信号 | 已实现：全屏时间（考试/创意）、快捷编辑、设置 |
