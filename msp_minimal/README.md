# MSP 最小调用示例

调用课表程序（MSP 节点 `schedule4`）的最小代码。**每个文件只做一件事，且都自成一体**——
看懂任意一个文件即可，不需要先读公共模块。

## 核心只有三行

```python
from msp import MSPNode, Preset

node = MSPNode("demo_state", preset=Preset.LOCAL_AI)   # 1. 建节点（LOCAL_AI 自带发现能力）
node.start(settle=True, settle_timeout=5.0)             # 2. 启动并等连接落地
r = node.call("schedule4", "get-lesson-state", {})      # 3. 调工具
```

`r.is_error` 判成败，`r.error` 是错误信息，`r.unwrap()` 拿返回的 dict。

## 文件

| 文件 | 做什么 |
|---|---|
| `01_lesson_state.py` | 查询实时上课状态（无参数） |
| `02_today_schedule.py` | 获取当天 / 指定星期的完整课表 |
| `03_swap_course.py` | 临时换课（会写 `Config/swap_schedule.json`） |
| `04_signals.py` | 订阅 `schedule.class.start` / `schedule.class.end` 信号 |
| `05_list_tools.py` | 列出对端的能力清单（tools / signals） |

## 运行

```bash
# 先启动课表程序，MSP 节点随程序一起启动
python main.py

# 另开一个终端
python msp_minimal/01_lesson_state.py
python msp_minimal/02_today_schedule.py Monday
python msp_minimal/04_signals.py
```

## 几个要点

- **node_id 必须唯一**。每个文件用了不同的 id（`demo_state`、`demo_schedule`…），
  所以可以同时运行多个；自己新写文件时记得换一个，且只能是 `[a-z0-9_-]`。
- **`settle=True`** 让 `start()` 等到连接落地再返回，省掉手写等待循环。
  即使没等到，`call()` / `fetch_manifest()` 也会按需自动建连。
- **信号不做缓存**：只发给当时已连上的订阅方。所以 `04_signals.py` 里
  `node.on(...)` 写在 `start()` 之前，避免漏掉开场信号。
- **`schedule4` 是被动节点**（`Preset.LOCAL_TOOL`，accept-only），
  它不会主动来找你，必须由你带着发现能力（`Preset.LOCAL_AI`）连上去。
- `Preset.OBSERVER` 更轻（只订阅、不宣告自己），纯收信号时可以换它。

## 接口速查

| 工具 | 参数 |
|---|---|
| `get-lesson-state` | 无 |
| `get-today-schedule` | `day`：`Monday`~`Sunday`，留空取当天 |
| `swap-course` | `day_name`、`lesson_key`、`old_subject`（留空自动取）、`new_subject`、`swap_date`（留空取该星期下一个匹配日） |

细节见 [`../API文档/KnotLink-API.md`](../API文档/KnotLink-API.md)。
