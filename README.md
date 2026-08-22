# 📅 Schedule 4.0 — 电子课表系统

> 从原版电子课表重构升级，基于 PySide6 的前后端分离桌面悬浮课表，支持 KnotLink 协议接入

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.x-green.svg)](https://pypi.org/project/PySide6/)
[![KnotLink](https://img.shields.io/badge/KnotLink-2.0-orange.svg)](https://github.com/KnotLink-Protocol/KnotLinkSDK)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 项目简介

Schedule 4.0 是一款**桌面悬浮电子课表**应用。它在屏幕右上角显示实时时间和每日课时安排，以半透明悬浮窗的形式呈现，不影响正常使用电脑。

**核心特点：**

- 🪟 **多窗口悬浮** — 置顶时间窗口 + 课表主窗口 + 全屏时间窗口，无边框、始终置顶
- 🎨 **三种主题** — 浅色 / 深色 / 彩色模式，彩色模式支持自定义主题色
- ⚙️ **配置文件驱动** — 主题、语言、字体、时间表/课程表路径等全部通过 INI/JSON 配置
- 🔗 **前后端分离** — 基于 PySide6 Signal/Slot + 统一动作协议（ActionMessage）的解耦架构
- 🌐 **KnotLink 接入** — 对外提供 5 个接口 + 3 个事件信号，SDK 缺失时静默降级
- 📝 **完整日志系统** — 按天生成日志文件，终端彩色输出，支持保留天数自动清理
- ⚡ **启动优化** — 时间窗口优先渲染，用户可立即看到时间，无需等待主窗口构造
- 🏷️ **完整类型注解** — 所有函数签名、实例变量均标注类型

---

## 🏗️ 架构设计

系统采用**前后端分离 + 发布订阅**架构，`main.py` 作为连接器负责实例创建与信号接线：

```
┌──────────────────────┐   Signal    ┌──────────────┐   方法调用   ┌──────────────────────┐
│     前端窗口模块       │ ──────────→ │   main.py    │ ──────────→ │      后端模块         │
│  schedule_frontend   │             │              │             │  schedule_backend    │
│  schedule_time       │ ←────────── │  （连接器）   │ ←────────── │  schedule_config     │
│  schedule_quick_edit │   公开方法   │              │    Signal   │  knotlink_bridge     │
│  schedule_settings   │             └──────────────┘             └──────────────────────┘
└──────────────────────┘
```

### 模块一览

| 模块 | 文件 | 职责 |
|------|------|------|
| 🎨 **主窗口前端** | `schedule_frontend.py` | `ScheduleMainWindow`：课表科目显示 + 四按钮入口（全屏/快捷编辑/设置/关闭） |
| ⏰ **时间模块** | `schedule_time.py` | `TimeWindow`（置顶时钟）、`FullscreenTimeWindow`（创意模式全屏）、`ExamFullscreenWindow`（考试模式全屏） |
| ✏️ **快捷编辑模块** | `schedule_quick_edit.py` | `SubjectSelectWindow`（滚轮选星期 + 科目点选）、`TempSwapWindow`（临时换课确认） |
| ⚙️ **设置模块** | `schedule_settings.py` | `SettingsWindow`：外观、字体、语言、时间表/课程表编辑、科目管理、显示规则、开机自启 |
| 🧠 **后端逻辑** | `schedule_backend.py` | `TimeManager`（时间广播）、`ScheduleBackend`（动作分派）、`WindowHelper`、`LogManager`、`QuickEditHandler` |
| 📦 **数据/配置层** | `schedule_config.py` | `ThemeManager`、`ScheduleDataManager`、`SubjectConfigManager`、`SwapManager`、`DebugConfig`、`DisplayRulesManager`、`ThemedWidget` |
| 📨 **动作协议** | `schedule_actions.py` | `ActionType` 枚举 + 不可变 `ActionMessage`（统一消息格式，替代 magic string） |
| 🌐 **KnotLink 桥接** | `knotlink_bridge.py` | `KnotLinkBridge`：5 个 openSocket 接口 + 3 个事件信号广播 |
| 🔤 **翻译监测** | `schedule_translate.py` | 候选翻译网站可用性测试 + `TranslationMonitor`（每 2.5 小时自测） |

> **设计原则：** 前端不写业务逻辑，后端不画 UI；前端通过 `backend_signal`（携带 `ActionMessage`）通知后端，后端通过公开方法 / Signal 更新界面。

---

## 📁 项目结构

```
Schedule4.0/
├── main.py                     # 程序入口 + 前后端连接器
├── schedule_config.py          # 配置 / 数据层（主题、课表数据、换课、调试、显示规则）
├── schedule_time.py            # 时间窗口（置顶时钟 + 两种全屏模式）
├── schedule_frontend.py        # 课表主窗口（UI 层）
├── schedule_quick_edit.py      # 快捷编辑模块（科目选择 + 临时换课）
├── schedule_settings.py        # 设置模块（多页签设置窗口 + 各编辑对话框）
├── schedule_backend.py         # 后端逻辑（时间广播 + 动作分派 + 日志管理）
├── schedule_actions.py         # 统一动作协议（ActionType + ActionMessage）
├── schedule_translate.py       # 翻译网站监测（自动选优）
├── knotlink_bridge.py          # KnotLink 协议桥接
│
├── Config/                     # 配置文件目录
│   ├── schedule_config.ini     # 主配置（主题、语言、时间表/课程表路径等）
│   ├── debug_config.ini        # 调试模式配置（模拟日期/时间/星期）
│   ├── subject_config.json     # 科目分类定义（含中英文名）
│   ├── Display_Rules.json      # 显示规则（按日期/星期切换时间表课程表）
│   ├── swap_schedule.json      # 临时换课记录（自动生成）
│   ├── curriculum/             # 课程表数据（table_1.json、table_2.json …）
│   ├── timetable/              # 时间表数据（timetable_1.json …）
│   └── TranslationTest/        # 翻译测试数据（站点列表、测试结果）
│
├── images/                     # 图标与全屏背景资源
│   ├── Icons/                  # 按钮图标（EDIT_S、EXIT、FullScreenTime、setting 等，含深色 -w 版本）
│   └── FullScreenBackgrounds/  # 创意模式全屏背景图片
│
├── log/                        # 日志文件目录（自动创建，已 gitignore）
├── 其他文件/                    # 参考资料与开发记录（已 gitignore）
├── venv/                       # Python 虚拟环境（已 gitignore）
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- **Python** 3.11+（代码使用 `StrEnum` 与 `X | None` 联合类型语法）
- **PySide6** ≥ 6.x（开发环境实测 6.11.x）
- **KnotLink SDK**（可选，`knotlink_bridge.py` 会尝试导入，缺失时静默降级，课表功能不受影响）
- **Windows**（悬浮窗使用 Windows 特定行为，macOS/Linux 可能需要调整）

### 安装与运行

```bash
# 1. 克隆项目
git clone <repo-url>
cd Schedule4.0

# 2. 创建虚拟环境（Python 3.11+）
python -m venv venv

# 3. 激活虚拟环境
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 4. 安装依赖
pip install -r requirements.txt

# 5. 运行程序
python main.py
```

---

## ⚙️ 配置说明

所有可调节参数集中在 `Config/schedule_config.ini` 中，修改后重新运行即可生效。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | str | `lightcolor` | 主题：`lightcolor` / `darkcolor` / `multicolor` |
| `theme_color` | str | `#2196f3` | 彩色模式主题色（`#RRGGBB`，仅 `multicolor` 生效） |
| `language` | str | `Chinese` | 显示语言：`Chinese` / `English` |
| `timetable` | str | `Config/timetable/timetable_1.json` | 时间表 JSON 路径（每节课起止时间 + 分隔线） |
| `table` | str | `Config/curriculum/table_1.json` | 课程表 JSON 路径（周一~周日每节课科目） |
| `fullscreen_bg_folder` | str | `images/FullScreenBackgrounds/default` | 创意模式全屏背景图片文件夹 |
| `log_retention_days` | int | `7` | 日志保留天数（0~365，启动时自动清理过期日志） |
| `translation_site` | str | `google` | 默认翻译网站 id（自动择优后写回） |
| `subject_font` | str | `Arial` | 主窗口科目显示字体家族名 |

### 科目配置

`Config/subject_config.json` 定义科目分类，每项包含中英文名（英文名用于翻译显示与自动缩写）：

```json
{
    "Subject_Types": {
        "Category_1": [
            { "name": "语文", "english_name": "Chinese" },
            { "name": "数学", "english_name": "Mathematics" }
        ],
        "Category_2": [
            { "name": "体育", "english_name": "Physical Education" }
        ]
    }
}
```

### 调试模式

`Config/debug_config.ini` 可模拟任意日期 / 时间 / 星期，用于测试不同时段的课表显示效果（`enabled = true` 启用）。各参数独立回退——只填 `time` 则仅时间使用模拟值，其余使用系统真实值。调试模式同样影响 KnotLink 接口的状态计算与事件推送。

### 显示规则

`Config/Display_Rules.json` 支持按**日期区间 / 每周几**自动切换时间表与课程表文件，规则带优先级（数值越小越优先），未命中时回退到 INI 中配置的默认文件。

---

## 🎨 主题说明

| 主题 | 值 | 说明 |
|------|-----|------|
| 浅色模式 | `lightcolor` | 白底深字，所有窗口 |
| 深色模式 | `darkcolor` | 深灰底浅字，所有窗口 |
| 彩色模式 | `multicolor` | 课表主窗口与置顶时间窗口使用主题色，其余窗口保持浅色，可通过 `theme_color` 自定义主题色 |

图标自动适配：深色主题下使用 `-w` 后缀的白色图标，浅色主题下使用深色图标（由 `ThemeManager.get_icon_suffix()` 决定）。

---

## 🌐 KnotLink 接入

Schedule 4.0 通过 KnotLink 协议对外开放 **5 个接口** 与 **3 个事件信号**：

| 接口（openSocket） | 说明 |
|---------------------|------|
| `get-lesson-state` | 查询实时上课状态（是否上课 / 当前课时 / 剩余时间 / 下一节课） |
| `get-today-schedule` | 获取当天（或指定星期）完整课表 |
| `swap-course` | 记录临时换课（按日期生效，过期自动清理） |
| `enter-fullscreen` | 进入全屏模式（`exam` 考试模式 / `creative` 创意模式） |
| `exit-fullscreen` | 退出全屏模式，恢复悬浮窗口 |

| 信号（signal） | 触发时机 |
|----------------|----------|
| `onClassStart` | 新一节课开始时 |
| `onClassEnd` | 一节课结束进入课间时（附带下一节预告） |
| `onDayEnd` | 当天最后一节课结束（放学）时 |

> AppID: `com.github.wenjin6470.schedule4`，详细协议见 **[API 文档](./API文档/KnotLink-API.md)**。

---

## 📝 日志系统

程序启动时自动在 `log/` 目录下创建按天命名的日志文件，并按 `log_retention_days` 清理过期文件：

```
log/
└── schedule_2026-07-18.log
```

- **双输出**：日志同时写入文件和终端（终端按级别着色）
- **日志级别**：INFO（应用流程）、DEBUG（每秒时间更新，默认关闭）、WARNING（可恢复问题）、ERROR（严重错误）
- **格式**：`2026-07-18 16:30:05 [INFO   ] schedule_backend: TimeManager 初始化完成`

---

## 📖 API 文档

- 👉 **[schedule_api.md](./API文档/schedule_api.md)** — 前后端模块接口、信号/动作协议、连接方式与数据流
- 👉 **[KnotLink-API.md](./API文档/KnotLink-API.md)** — KnotLink 接口与信号规范（对外协议）

---

## 🔧 技术栈

| 技术 | 用途 |
|------|------|
| [PySide6](https://pypi.org/project/PySide6/) | Qt for Python，GUI 框架 |
| `QTimer` / `Signal` / `Slot` | 定时驱动 + 信号槽解耦通信（发布订阅） |
| [KnotLink SDK](https://github.com/KnotLink-Protocol/KnotLinkSDK) | 节点网络接入（openSocket 接口 + 信号广播） |
| `logging` | Python 标准日志库，按天滚动 + 终端彩色输出 + 自动清理 |
| `configparser` / `json` | INI / JSON 配置解析 |
| `QThread` | 翻译测试、翻译请求等耗时操作的线程化 |
| `QPainter` | 自定义控件绘制（滚轮选择器、开关、取色器等） |

---

## 📋 开发日志

- **v4.0** (2026-07) — 从原版重构：前后端分离架构、三主题模式、配置文件驱动、完整日志系统、类型注解全覆盖
  - 接入 KnotLink（5 接口 + 3 信号）
  - 设置页：外观 / 字体 / 语言 / 时间表编辑 / 课程表编辑 / 科目管理 / 显示规则 / 开机自启
  - 快捷编辑（光标闪烁 + 科目点选 + 临时换课）、考试/创意双全屏模式
  - 翻译网站自动择优、中英文切换与字号自适应
- 详细变更记录见 `其他文件/git使用记录报告/`

---

## 📄 许可证

MIT License
