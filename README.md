# 📅 Schedule 4.0 — 电子课表系统

> 从原版电子课表重构升级，基于 PySide6 的前后端分离桌面悬浮课表

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.x-green.svg)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 项目简介

Schedule 4.0 是一款**桌面悬浮电子课表**应用。它在屏幕右上角显示实时时间和每日课时安排，以半透明悬浮窗的形式呈现，不影响正常使用电脑。

**核心特点：**
- 🪟 **双窗口悬浮** — 时间窗口 + 科目窗口，始终置顶，无边框，不在任务栏显示
- 🎨 **三种主题** — 浅色模式 / 深色模式 / 彩色自适应，适配不同桌面壁纸
- ⚙️ **配置文件驱动** — 课时数量、主题、语言全部通过 INI 文件配置，无需改代码
- 🔗 **前后端分离** — 基于 PySide6 Signal/Slot 的解耦架构，职责清晰
- 📝 **完整日志系统** — 按天生成日志文件，终端同步输出，方便排查问题
- 🏷️ **完整类型注解** — 所有函数签名、实例变量均标注类型

---

## 🏗️ 架构设计

```
┌──────────────────────┐     Signal      ┌──────────────┐   方法调用   ┌──────────────────────┐
│ schedule_frontend.py │ ──────────────→ │   main.py    │ ──────────→ │ schedule_backend.py  │
│                      │                 │              │             │                      │
│ ScheduleClassroom    │ ←────────────── │  （连接器）   │ ←────────── │ TimeManager          │
│ Frontend             │   公开方法调用   │              │   回调函数   │ WindowHelper         │
└──────────────────────┘                 └──────────────┘             └──────────────────────┘
```

| 角色 | 文件 | 职责 |
|------|------|------|
| 🎨 **前端** | `schedule_frontend.py` | 创建窗口和控件、捕获用户操作、刷新界面 |
| 🔗 **连接器** | `main.py` | 配置日志系统、创建前后端实例、连接 Signal 与回调 |
| 🧠 **后端** | `schedule_backend.py` | 管理实时时间（QTimer）、处理窗口关闭 |

> **设计原则：** 前端不写业务逻辑，后端不画 UI —— 所有跨层通信通过 Signal/Slot 和回调函数完成。

---

## 📁 项目结构

```
Schedule4.0/
├── main.py                   # 程序入口 + 前后端连接器
├── schedule_frontend.py      # 前端窗口（UI 层）
├── schedule_backend.py       # 后端逻辑（时间管理 + 窗口辅助）
├── schedule_api.md           # API 接口说明文档（详细）
│
├── Config/                   # 配置文件目录
│   ├── schedule_config.ini   # 主配置（课时数、主题、语言）
│   └── subject_config.json   # 科目类型定义
│
├── images/                   # 图标资源（SVG）
│   ├── EDIT_S.svg            # 编辑图标（浅色）
│   ├── EDIT_S-w.svg          # 编辑图标（深色）
│   ├── EXIT.svg              # 退出图标（浅色）
│   ├── EXIT-w.svg            # 退出图标（深色）
│   ├── FullScreenTime.svg    # 全屏时间图标（浅色）
│   ├── FullScreenTime-w.svg  # 全屏时间图标（深色）
│   ├── setting.svg           # 设置图标（浅色）
│   └── setting-w.svg         # 设置图标（深色）
│
├── log/                      # 日志文件目录（自动创建，已 gitignore）
│   └── schedule_YYYY-MM-DD.log
│
├── 其他文件/                  # 参考资料和记录
│   ├── 参考文件/
│   │   └── Qt 深色主题（Dark Theme）完整实现.md
│   └── git使用记录报告/
│
├── venv/                     # Python 虚拟环境（已 gitignore）
├── .gitignore
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- **Python** 3.8+
- **PySide6** ≥ 6.x
- **Windows**（悬浮窗使用 Windows 特定行为，macOS/Linux 可能需要调整）

### 安装与运行

```bash
# 1. 克隆项目
git clone <repo-url>
cd Schedule4.0

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 4. 安装依赖
pip install PySide6

# 5. 运行程序
python main.py
```

---

## ⚙️ 配置说明

所有可调节参数集中在 `Config/schedule_config.ini` 中，修改后重新运行即可生效。

```ini
[Schedule]
; 每日课时数量，范围 1~15
period_count = 7

; 软件主题：lightcolor / darkcolor / multicolor
theme = lightcolor

; 显示语言：Chinese / English
language = Chinese
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `period_count` | int | `7` | 每日课时数（1~15），决定科目窗口显示的标签行数 |
| `theme` | str | `lightcolor` | 主题模式，见下方主题说明 |
| `language` | str | `Chinese` | 显示语言（当前版本预置，后续扩展） |

### 科目配置

`Config/subject_config.json` 定义了科目分类：

```json
{
    "Subject_Types": {
        "Category_1": ["语文","数学","英语","物理","化学","生物","历史","政治","地理"],
        "Category_2": ["活动","体育","信息","音乐","美术","通用技术","自习","生涯"],
        "Category_3": "None"
    }
}
```

---

## 🎨 主题说明

| 主题 | 值 | 时间窗背景 | 科目窗背景 | 字体颜色 | 透明度 |
|------|-----|-----------|-----------|----------|--------|
| 浅色模式 | `lightcolor` | `#FFFFFF` | `#FAFAFA` | `#212121` | 0.70 |
| 深色模式 | `darkcolor` | `#252526` | `#1E1E1E` | `#E0E0E0` | 0.85 |
| 彩色自适应 | `multicolor` | 桌面取色 | 桌面取色 | 自动黑白 | 0.70 |

> **深色模式**透明度更高（0.85），避免桌面壁纸过度冲淡深色效果。
> **彩色自适应**当前为临时实现，取桌面单像素颜色；后续将支持多区域采样和预定义调色板。

---

## 📝 日志系统

程序启动时自动在 `log/` 目录下创建按天命名的日志文件：

```
log/
└── schedule_2026-07-18.log
```

- **双输出**：日志同时写入文件和终端
- **日志级别**：INFO（应用流程）、DEBUG（每秒时间更新，默认关闭）、WARNING（可恢复问题）、ERROR（严重错误）
- **格式**：`2026-07-18 16:30:05 [INFO   ] schedule_backend: TimeManager 初始化完成`

---

## 📖 API 文档

详细的 API 接口说明（Signal、公开方法、回调函数、使用示例）请参阅：

👉 **[schedule_api.md](./schedule_api.md)**

---

## 🔧 技术栈

| 技术 | 用途 |
|------|------|
| [PySide6](https://pypi.org/project/PySide6/) | Qt for Python，GUI 框架 |
| `QTimer` | 每秒定时器，驱动实时时间更新 |
| `Signal` / `Slot` | Qt 信号槽机制，实现前后端解耦通信 |
| `logging` | Python 标准日志库，按天滚动 + 终端输出 |
| `configparser` | INI 配置文件解析 |
| `json` | JSON 配置文件解析 |

---

## 📋 开发日志

- **v4.0** (2026-07) — 从原版重构：前后端分离架构、三种主题模式、配置文件驱动、完整日志系统、类型注解全覆盖
- 详细变更记录见 `其他文件/git使用记录报告/`

---

## 📄 许可证

MIT License

