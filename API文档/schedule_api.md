# 📅 电子课表系统 —— 前后端 API 接口说明文档

> **版本**: v1.0
> **前端文件**: `schedule_frontend.py`（`ScheduleClassroomFrontend` 类）
> **后端文件**: `schedule_backend.py`（`TimeManager` 类 / `WindowHelper` 类）
> **连接器**: `main.py`
> **技术栈**: PySide6 + Python 3.8+
> **架构模式**: 前后端分离（信号 / 槽 + 回调机制）

---

## 📌 目录

1. [架构概述](#架构概述)
2. [前端接口 —— schedule_frontend.py](#前端接口--schedule_frontendpy)
   - [信号（Signal）—— 前端 → 后端](#信号signal--前端--后端)
   - [公开方法（Public Method）—— 后端 → 前端](#公开方法public-method--后端--前端)
3. [后端接口 —— schedule_backend.py](#后端接口--schedule_backendpy)
   - [TimeManager 类](#timemanager-类)
   - [WindowHelper 类](#windowhelper-类)
4. [连接器 —— main.py](#连接器--mainpy)
5. [数据流图](#数据流图)
6. [使用示例](#使用示例)
7. [界面结构说明](#界面结构说明)

---

## 架构概述

本系统采用**前后端分离**架构，将界面显示与业务逻辑彻底解耦。

```
┌──────────────────────┐         ┌──────────────┐         ┌──────────────────────┐
│ schedule_frontend.py │  信号    │   main.py    │  调用   │ schedule_backend.py  │
│                      │ ──────→ │              │ ──────→ │                      │
│ ScheduleClassroom    │         │  （连接器）   │         │ TimeManager          │
│ Frontend             │ ←────── │              │ ←────── │ WindowHelper         │
│                      │ 公开方法 │              │ 回调    │                      │
└──────────────────────┘         └──────────────┘         └──────────────────────┘
```

| 角色 | 文件 | 职责 |
|------|------|------|
| 🎨 **前端** | `schedule_frontend.py` | 创建窗口和控件、捕获用户操作、刷新界面显示 |
| 🔗 **连接器** | `main.py` | 创建前后端实例、连接信号与回调 |
| 🧠 **后端** | `schedule_backend.py` | 管理实时时间（TimeManager）、处理窗口关闭（WindowHelper） |

**重要原则**：
- 前端不包含业务逻辑：不管理定时器、不判断如何关闭窗口
- 后端不包含 UI 代码：不创建窗口、不设置样式、不画控件

---

## 前端接口 —— schedule_frontend.py

### 信号（Signal）—— 前端 → 后端

信号是前端通知后端的唯一方式。当用户操作界面时，前端发射信号，后端（通过 main.py）监听到信号后处理业务。

#### 信号列表

| 信号名称 | 参数 | 触发时机 | 说明 |
|----------|------|----------|------|
| `close_requested` | 无 | 点击关闭按钮 | 用户点击科目显示窗口底部关闭按钮 |
| `fullscreen_time_requested` | 无 | 点击全屏时间按钮 | 用户点击底部全屏时间按钮（⚠️ 功能待实现） |
| `quick_edit_requested` | 无 | 点击快捷课表编辑按钮 | 用户点击底部快捷课表编辑按钮（⚠️ 功能待实现） |
| `settings_requested` | 无 | 点击设置按钮 | 用户点击底部设置按钮（⚠️ 功能待实现） |

---

#### `close_requested()`

用户点击关闭按钮时发射。无参数。

```
┌─────────────────────────────────────────┐
│  触发流程：                              │
│  1. 用户点击科目窗口右上角的 × 按钮       │
│  2. QPushButton.clicked 信号触发         │
│  3. 前端 _on_close_clicked() 槽函数执行   │
│  4. 发射 close_requested 信号             │
│  5. main.py 中的连接器收到信号             │
│  6. 调用 WindowHelper.close_all()          │
└─────────────────────────────────────────┘
```

**连接示例**（在 main.py 中）：
```python
window.close_requested.connect(
    lambda: window_helper.close_all(
        [window.get_time_window(), window.get_root_window()],
        app
    )
)
```

---

#### `fullscreen_time_requested()`

用户点击底部全屏时间按钮时发射。无参数。

⚠️ **状态：接口已预留，功能待后续实现。** 该信号目前仅在前端定义并发射，main.py 中暂未连接任何处理逻辑。

```
┌─────────────────────────────────────────┐
│  触发流程：                              │
│  1. 用户点击底部全屏时间按钮              │
│  2. QPushButton.clicked 信号触发         │
│  3. 前端 _on_fullscreen_time_clicked()   │
│  4. 发射 fullscreen_time_requested 信号   │
│  5. （待实现）main.py 连接器处理          │
└─────────────────────────────────────────┘
```

**连接示例**（预留，在 main.py 中）：
```python
# TODO: 待后续实现全屏时间功能时取消注释
# window.fullscreen_time_requested.connect(
#     lambda: fullscreen_helper.show_fullscreen_time()
# )
```

---

#### `quick_edit_requested()`

用户点击底部快捷课表编辑按钮时发射。无参数。

⚠️ **状态：接口已预留，功能待后续实现。** 该信号目前仅在前端定义并发射，main.py 中暂未连接任何处理逻辑。

```
┌─────────────────────────────────────────┐
│  触发流程：                              │
│  1. 用户点击底部快捷课表编辑按钮          │
│  2. QPushButton.clicked 信号触发         │
│  3. 前端 _on_quick_edit_clicked()        │
│  4. 发射 quick_edit_requested 信号        │
│  5. （待实现）main.py 连接器处理          │
└─────────────────────────────────────────┘
```

**连接示例**（预留，在 main.py 中）：
```python
# TODO: 待后续实现快捷课表编辑功能时取消注释
# window.quick_edit_requested.connect(
#     lambda: schedule_editor.open_quick_edit()
# )
```

---

#### `settings_requested()`

用户点击底部设置按钮时发射。无参数。

⚠️ **状态：接口已预留，功能待后续实现。** 该信号目前仅在前端定义并发射，main.py 中暂未连接任何处理逻辑。

```
┌─────────────────────────────────────────┐
│  触发流程：                              │
│  1. 用户点击底部设置按钮                  │
│  2. QPushButton.clicked 信号触发         │
│  3. 前端 _on_settings_clicked()          │
│  4. 发射 settings_requested 信号          │
│  5. （待实现）main.py 连接器处理          │
└─────────────────────────────────────────┘
```

**连接示例**（预留，在 main.py 中）：
```python
# TODO: 待后续实现设置功能时取消注释
# window.settings_requested.connect(
#     lambda: settings_dialog.open_settings()
# )
```

---

### 公开方法（Public Method）—— 后端 → 前端

公开方法是后端更新界面的接口。后端处理完业务后，调用这些方法来刷新界面显示。

#### 方法列表

| 方法名称 | 参数 | 返回值 | 用途 |
|----------|------|--------|------|
| `update_time_display(time_str)` | `time_str: str` | 无 | 更新时间标签的显示文字 |
| `get_root_window()` | 无 | `QWidget \| None` | 获取科目显示窗口引用 |
| `get_time_window()` | 无 | `ScheduleClassroomFrontend` | 获取时间窗口引用（self） |

---

#### `update_time_display(time_str: str)`

**调用时机**：TimeManager 定时器每秒触发时，通过 main.py 连接器调用。

**功能**：将时间标签的文字更新为传入的时间字符串。

| 参数 | 类型 | 说明 |
|------|------|------|
| `time_str` | `str` | 时间字符串，格式 `HH:MM:SS`（24小时制），示例: `"14:30:05"` |

**示例**：
```python
# 在 main.py 中通过 TimeManager 回调调用
time_manager.start(lambda t: window.update_time_display(t))

# 或直接调用
window.update_time_display("14:30:05")
```

---

#### `get_root_window()`

**调用时机**：main.py 需要在关闭程序时同时关闭两个窗口。

**功能**：返回科目显示窗口（self.root）的引用。

| 返回值 | 类型 | 说明 |
|--------|------|------|
| root 窗口 | `QWidget \| None` | 科目显示窗口对象；`_setup_ui()` 未调用时返回 `None` |

**示例**：
```python
root = window.get_root_window()
# 在主窗口关闭时需要一并关闭 root 窗口
```

---

#### `get_time_window()`

**调用时机**：main.py 需要在关闭程序时操作时间窗口。

**功能**：返回时间窗口自身的引用。

| 返回值 | 类型 | 说明 |
|--------|------|------|
| self | `ScheduleClassroomFrontend` | 时间窗口对象自身 |

**示例**：
```python
time_win = window.get_time_window()
```

---

### 构造函数参数

`ScheduleClassroomFrontend` 的构造函数接收两个可选参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `language` | `str` | `'chinese'` | 语言类型。不为 `'image'` 时设置 `language_reflect = True` |
| `theme` | `str` | `'multicolour'` | 主题类型。可选值见下表 |

**theme 可选值**：

| 值 | 说明 | 字体颜色 | 背景颜色 |
|----|------|----------|----------|
| `'lightcolour'` | 浅色模式 | 黑色 `#000000` | 白色 `#FFFFFF` |
| `'deepcolour'` | 深色模式 | 白色 `#FFFFFF` | 黑色 `#000000` |
| `'multicolour'` | 彩色自适应 | 根据桌面背景自动选择（黑/白） | 桌面背景色 |

---

## 后端接口 —— schedule_backend.py

### TimeManager 类

时间管理类，负责实时时间的获取与管理。内部使用 `QTimer` 每秒触发一次，通过**回调函数**将当前时间传递给外部。

#### 方法列表

| 方法名称 | 参数 | 返回值 | 用途 |
|----------|------|--------|------|
| `__init__()` | 无 | — | 初始化定时器（间隔 1000ms） |
| `start(callback)` | `callback: Callable[[str], None]` | 无 | 启动定时器，注册时间更新回调 |
| `stop()` | 无 | 无 | 停止定时器，断开信号连接 |
| `get_current_time()` | 无 | `str` | 手动获取当前时间字符串 |

---

#### `__init__()`

初始化时间管理器，创建 `QTimer` 实例并设置间隔为 1000ms（1秒）。

**内部状态**：
- `_timer`：`QTimer` 实例，间隔 1000ms
- `_callback`：初始为 `None`，调用 `start()` 后存储外部回调

```python
tm = TimeManager()  # 创建实例，定时器尚未启动
```

---

#### `start(callback)`

启动定时器，开始每秒更新时间。

| 参数 | 类型 | 说明 |
|------|------|------|
| `callback` | `Callable[[str], None]` | 回调函数，接收一个时间字符串参数 `(time_str: str)` |

**回调函数签名**：
```python
def on_time_update(time_str: str) -> None:
    """
    参数:
        time_str: 当前时间，格式 HH:MM:SS（24小时制），如 "14:30:05"
    """
    pass
```

**行为说明**：
1. 如果之前已启动，会先停止旧定时器再启动新的
2. 调用后**立即触发一次回调**（不等 1 秒），确保界面立刻显示时间
3. 之后每秒触发一次回调

**示例**：
```python
tm = TimeManager()
tm.start(lambda t: print(f"现在时间: {t}"))
# 输出: 现在时间: 14:30:05
# 1秒后输出: 现在时间: 14:30:06
# ...
```

---

#### `stop()`

停止定时器并断开信号连接。

**行为说明**：
- 停止 `QTimer`
- 断开 `timeout` 信号与内部 `_on_timeout` 的连接（防止内存泄漏）
- 清空回调引用
- 多次调用不会出错

**示例**：
```python
tm.stop()  # 停止时间更新
```

---

#### `get_current_time()`

手动获取当前时间字符串，不依赖定时器。

| 返回值 | 类型 | 说明 |
|--------|------|------|
| 当前时间 | `str` | 格式 `HH:MM:SS`（24小时制），示例: `"14:30:05"` |

**示例**：
```python
tm = TimeManager()
print(tm.get_current_time())  # 输出: "14:30:05"
```

---

### WindowHelper 类

辅助功能类，提供窗口相关的辅助操作。所有方法均为静态方法。

#### 方法列表

| 方法名称 | 参数 | 返回值 | 用途 |
|----------|------|--------|------|
| `close_all(widgets, app)` | `widgets: list[QWidget]`, `app: QApplication` | 无 | 关闭所有窗口并退出程序 |

---

#### `close_all(widgets, app)`

**【静态方法】** 关闭所有窗口并退出应用程序。

| 参数 | 类型 | 说明 |
|------|------|------|
| `widgets` | `list[QWidget]` | 需要关闭的 QWidget 列表，每个元素依次调用 `close()` |
| `app` | `QApplication` | QApplication 实例，用于调用 `quit()` 退出事件循环 |

**执行流程**：
1. 遍历 `widgets` 列表，逐个调用 `close()` 关闭每个窗口
2. 调用 `app.quit()` 退出 Qt 事件循环，程序正常结束

**安全说明**：
- 传入 `None` 的 widget 会被自动跳过，不会报错
- `close()` 只发送关闭事件，窗口资源由 Qt 自动管理

**示例**：
```python
# 作为静态方法调用
WindowHelper.close_all([window, root_window], app)

# 或创建实例调用
helper = WindowHelper()
helper.close_all([window, root_window], app)
```

---

## 连接器 —— main.py

`main.py` 是程序入口，负责创建所有实例并连接前后端。

### 连接关系

```
┌──────────────────────────────────────────────────────────────────┐
│                          main.py 连接关系                         │
│                                                                  │
│  连接1: TimeManager 定时器 → 前端时间显示                          │
│  ┌─────────────┐   回调(callback)    ┌──────────────────────┐    │
│  │ TimeManager │ ─────────────────→ │ ScheduleClassroom    │    │
│  │  .start()   │                    │ Frontend             │    │
│  │             │                    │ .update_time_display │    │
│  └─────────────┘                    └──────────────────────┘    │
│                                                                  │
│  连接2: 关闭按钮 → 关闭窗口                                        │
│  ┌──────────────────────┐  信号(Signal)   ┌──────────────┐      │
│  │ ScheduleClassroom    │ ─────────────→ │ WindowHelper │      │
│  │ Frontend             │                │ .close_all() │      │
│  │ .close_requested     │                │              │      │
│  └──────────────────────┘                └──────────────┘      │
│                                                                  │
│  连接3~5: 预留信号（功能待实现）                                    │
│  ┌──────────────────────┐                                        │
│  │ ScheduleClassroom    │  fullscreen_time_requested  → (待实现) │
│  │ Frontend             │  quick_edit_requested       → (待实现) │
│  │                      │  settings_requested         → (待实现) │
│  └──────────────────────┘                                        │
└──────────────────────────────────────────────────────────────────┘
```

### 完整连接代码

```python
# 连接1：TimeManager 定时器 → 前端 update_time_display()
time_manager.start(lambda time_str: window.update_time_display(time_str))

# 连接2：前端 close_requested 信号 → WindowHelper.close_all()
window.close_requested.connect(
    lambda: window_helper.close_all(
        [window.get_time_window(), window.get_root_window()],
        app
    )
)
```

---

## 数据流图

### 时间更新流程（每1秒）

```
┌──────────┐  timeout(1000ms)  ┌──────────────┐  callback("14:30:05")  ┌──────────┐  .setText()  ┌──────────┐
│ QTimer   │ ────────────────→ │ TimeManager  │ ────────────────────→ │ main.py  │ ───────────→ │ QLabel   │
│ (内部)    │                   │ ._on_timeout │                       │ lambda   │              │ 时间标签  │
└──────────┘                   └──────────────┘                       └──────────┘              └──────────┘
                                                                        │
                                                                        │ window.update_time_display(t)
                                                                        ↓
                                                                  ┌──────────────────┐
                                                                  │ ScheduleClassroom │
                                                                  │ Frontend          │
                                                                  └──────────────────┘
```

### 关闭窗口流程

```
┌──────────┐  clicked  ┌──────────────────────┐  close_requested.emit()  ┌──────────┐  .close_all()  ┌──────────────┐
│ 用户点击  │ ────────→ │ ScheduleClassroom    │ ──────────────────────→ │ main.py  │ ─────────────→ │ WindowHelper │
│ × 按钮   │           │ Frontend             │                         │ lambda   │               │              │
└──────────┘           │ ._on_close_clicked() │                         └──────────┘               └──────────────┘
                       └──────────────────────┘                                                          │
                                                                                              .close() + .quit()
                                                                                                         │
                                                                                                  ┌──────▼──────┐
                                                                                                  │ 程序退出     │
                                                                                                  └─────────────┘
```

---

## 使用示例

### 基本运行

```bash
# 在虚拟环境中运行
venv\Scripts\python main.py
```

### main.py 完整代码参考

```python
"""
main.py —— 电子课表系统入口
前后端分离架构 · 中间连接层
"""
import sys
from PySide6.QtWidgets import QApplication

from schedule_frontend import ScheduleClassroomFrontend
from schedule_backend import TimeManager, WindowHelper


def main():
    # 第1步：创建应用程序
    app = QApplication(sys.argv)

    # 第2步：创建前端窗口
    window = ScheduleClassroomFrontend(language='chinese', theme='multicolour')

    # 第3步：创建后端实例
    time_manager = TimeManager()
    window_helper = WindowHelper()

    # 第4步：连接前后端
    # 连接1：定时器 → 更新时间显示
    time_manager.start(lambda t: window.update_time_display(t))

    # 连接2：关闭按钮 → 关闭窗口
    window.close_requested.connect(
        lambda: window_helper.close_all(
            [window.get_time_window(), window.get_root_window()],
            app
        )
    )

    # 连接3~5：预留信号连接（功能待实现）
    # window.fullscreen_time_requested.connect(
    #     lambda: fullscreen_helper.show_fullscreen_time()
    # )
    # window.quick_edit_requested.connect(
    #     lambda: schedule_editor.open_quick_edit()
    # )
    # window.settings_requested.connect(
    #     lambda: settings_dialog.open_settings()
    # )

    # 第5步：显示窗口
    window.show()

    # 第6步：启动事件循环
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## 界面结构说明

### 窗口布局

```
屏幕右上角
┌──────────────────┐
│    14:30:05      │  ← 时间窗口 (ScheduleClassroomFrontend / self)
│   红色大字        │     尺寸: 屏幕宽度×(150/1920) × 屏幕高度/26
│   半透明背景      │     位置: 屏幕右上角 (left=1765/1920×W, top=45/1080×H)
├──────────────────┤
│                  │  ← 科目显示窗口 (self.root)
│                  │     尺寸: 屏幕宽度×(150/1920) × 屏幕高度/13×11
│   科目内容区域    │     位置: 时间窗口正下方 (top=屏幕高度/12)
│                  │
│                  │
│ ⏰  📝  ⚙  ✕   │  ← 底部按钮栏（左→右：全屏时间/快捷编辑/设置/关闭）
└──────────────────┘
```

### 控件对照表

| 控件名称 | 类型 | 所在窗口 | 说明 |
|----------|------|----------|------|
| `time_label` | `QLabel` | 时间窗口（self） | 实时时间显示，红色 Arial 18号字体 |
| `root` | `QWidget` | —（独立窗口） | 科目显示窗口 |
| `fullscreen_btn` | `QPushButton` | root 窗口 | 全屏时间按钮（图标按钮，功能待实现） |
| `edit_btn` | `QPushButton` | root 窗口 | 快捷课表编辑按钮（图标按钮，功能待实现） |
| `settings_btn` | `QPushButton` | root 窗口 | 设置按钮（图标按钮，功能待实现） |
| `close_btn` | `QPushButton` | root 窗口 | 关闭按钮（图标按钮，点击关闭程序） |

### 按钮图标说明

底部 4 个按钮使用 SVG 图标作为按钮前景（无文字），根据当前主题自动切换深色/浅色图标：

| 按钮 | 浅色模式图标 | 深色模式图标 | 对应信号 |
|------|-------------|-------------|----------|
| 全屏时间 | `FullScreenTime.svg` | `FullScreenTime-w.svg` | `fullscreen_time_requested` |
| 快捷课表编辑 | `EDIT_S.svg` | `EDIT_S-w.svg` | `quick_edit_requested` |
| 设置 | `setting.svg` | `setting-w.svg` | `settings_requested` |
| 关闭 | `EXIT.svg` | `EXIT-w.svg` | `close_requested` |

- **浅色模式**（`lightcolor` 主题 / `multicolor` 浅色背景）：使用不带 `-w` 后缀的图标（深色图标，适合浅色背景）
- **深色模式**（`darkcolor` 主题 / `multicolor` 深色背景）：使用带 `-w` 后缀的图标（白色图标，适合深色背景）

图标文件位于 `images/` 目录，由 `_get_icon_suffix()` 方法根据 `self.theme` 和背景色自动判断后缀。

### 主题配色说明

| 主题 | 字体颜色 | 背景颜色 | 适用场景 |
|------|----------|----------|----------|
| `lightcolour` | `#000000`（黑色） | `#FFFFFF`（白色） | 浅色桌面背景 |
| `deepcolour` | `#FFFFFF`（白色） | `#000000`（黑色） | 深色桌面背景 |
| `multicolour` | 自动计算（黑/白） | 桌面背景色 | 自适应，跟随桌面壁纸 |

---

## 与原文件的对应关系

| 原 `schedule_classroom.py` | 新架构 |
|---------------------------|--------|
| `ScheduleClassroom.__init__()` 中的 UI 创建 | `schedule_frontend.py` → `ScheduleClassroomFrontend._setup_ui()` |
| `ScheduleClassroom.__init__()` 中的参数/主题计算 | `schedule_frontend.py` → `ScheduleClassroomFrontend.__init__()` |
| `ScheduleClassroom.update_time()` | `schedule_backend.py` → `TimeManager._on_timeout()` + `get_current_time()` |
| `ScheduleClassroom.close_all()` | `schedule_backend.py` → `WindowHelper.close_all()` |
| `QTimer` 的创建和管理 | `schedule_backend.py` → `TimeManager.__init__()` + `start()` / `stop()` |
| `get_color()` / `RGB_to_Hex()` / `is_color_dark()` | `schedule_frontend.py`（辅助函数，UI 相关） |
| `if __name__ == '__main__'` 入口 | `main.py` → `main()` |
