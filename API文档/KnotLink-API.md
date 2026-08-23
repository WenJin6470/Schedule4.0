# Schedule 4.0 — KnotLink 接口与信号规范

> AppID: `com.github.wenjin6470.schedule4`  
> 版本: 1.0.0  
> 作者: WenJin (温谨WenJin)  
> 桥接实现: `knotlink_bridge.py`（`KnotLinkBridge` 类）

---

## 一、概述

Schedule 4.0（电子课表系统）通过 KnotLink 协议对外开放 **3 个接口** 和 **2 个信号**，供其他节点查询课表状态、执行换课操作，并实时接收上课/下课事件推送。

所有接口和信号均使用 KnotLink 标准 KLKVMap 键值对格式进行序列化传输。

> **依赖说明**：KnotLink SDK 为**可选依赖**。桥接层启动时会尝试导入 SDK，若未安装则静默降级——课表系统本身的所有功能不受任何影响，仅对外接口与信号广播不可用。

---

## 二、接口（openSocket）

### 2.1 get-lesson-state — 查询实时上课状态

- **openSocketID**: `schedule`
- **描述**: 查询当前时间对应的上课状态，包括正在进行的课时、剩余时间、下一节课信息等。

**参数**:

| 参数名 | 类型 | 值/默认值 | 说明 |
|--------|------|----------|------|
| `action` | static | `get-lesson-state` | 命令类型（固定值） |

**返回值**:

| 字段名 | 说明 |
|--------|------|
| `status` | 请求状态（`ok` / `err`） |
| `isInClass` | 是否正在上课（`true` / `false`） |
| `isBreak` | 是否处于课间休息（`true` / `false`） |
| `currentPeriod` | 当前课时序号（从 1 开始，课间/放学时为 `-1`） |
| `currentSubject` | 当前科目名称（课间/放学时为空字符串） |
| `currentStartTime` | 当前课时开始时间（格式 `HH:MM:SS`，无当前课时为空） |
| `currentEndTime` | 当前课时结束时间（格式 `HH:MM:SS`，无当前课时为空） |
| `remainingTime` | 当前课时剩余时间（格式 `HH:MM:SS`，课间/放学时为 `00:00:00`） |
| `nextPeriod` | 下一节课时序号（无下一节时为 `-1`） |
| `nextSubject` | 下一节科目名称（无下一节时为空字符串） |
| `nextStartTime` | 下一节课开始时间（格式 `HH:MM:SS`，无下一节时为空） |
| `message` | 错误信息（仅在 `status=err` 时返回） |

---

### 2.2 get-today-schedule — 获取当天完整课表

- **openSocketID**: `schedule`
- **描述**: 获取当天（或指定星期）全部课时的科目与时间安排。

**参数**:

| 参数名 | 类型 | 值/默认值 | 说明 |
|--------|------|----------|------|
| `action` | static | `get-today-schedule` | 命令类型（固定值） |
| `day` | input | `""` | 目标星期（`Monday`~`Sunday`），留空则取当天 |

**返回值**:

| 字段名 | 说明 |
|--------|------|
| `status` | 请求状态（`ok` / `err`） |
| `day` | 实际返回的星期名称 |
| `lessons` | 课表数据（JSON 数组，每项含 `period` / `key` / `subject` / `startTime` / `endTime`） |
| `dividerIndices` | 分隔线位置（JSON 数组，值为分隔线前的课时索引，0-based） |
| `totalPeriods` | 总课时数 |
| `message` | 错误信息（仅在 `status=err` 时返回） |

**lessons 数组每项结构**:

```json
{
  "period": 1,
  "key": "lesson_1",
  "subject": "语文",
  "startTime": "08:00:00",
  "endTime": "08:45:00"
}
```

---

### 2.3 swap-course — 临时换课

- **openSocketID**: `schedule`
- **描述**: 记录一条临时换课信息。换课数据被保存到 `Config/swap_schedule.json`，在指定日期当天，课表系统会自动将对应课时的科目替换为新科目。换课仅在指定日期生效，过期自动清理。

**换课记录格式**（参照 `SwapManager` 和 `TempSwapWindow`）:

| 字段 | 类型 | 说明 |
|------|------|------|
| `day_name` | string | 星期名称，取值为 `Monday` ~ `Sunday` |
| `lesson_key` | string | 课时键名，格式为 `lesson_N`，如 `lesson_2` |
| `old_subject` | string | 换课之前的原始科目名称 |
| `new_subject` | string | 换课之后的新科目名称 |
| `swap_date` | string | 换课生效日期，格式 `YYYY-MM-DD`（仅当天生效） |

**参数**:

| 参数名 | 类型 | 值/默认值 | 说明 |
|--------|------|----------|------|
| `action` | static | `swap-course` | 命令类型（固定值） |
| `day_name` | input | `""` | 星期名称，如 `Monday` |
| `lesson_key` | input | `""` | 课时键名，如 `lesson_2`（必须是当前时间表中已存在的课时） |
| `old_subject` | input | `""` | 换课前的原始科目名称 |
| `new_subject` | input | `""` | 换课后的新科目名称 |
| `swap_date` | input | `""` | 换课生效日期，格式 `YYYY-MM-DD`，留空则取该星期的下一个匹配日期（若今天恰为该星期则取今天） |

**返回值**:

| 字段名 | 说明 |
|--------|------|
| `status` | 请求状态（`ok` / `err`） |
| `swap_date` | 实际生效日期（`YYYY-MM-DD`） |
| `message` | 错误信息（仅在 `status=err` 时返回） |

**生命周期**:
1. 调用方传入换课数据 → 记录追加写入 `Config/swap_schedule.json`
2. 软件启动时自动检查换课记录：
   - `swap_date == 今天` → 将 `curriculum_data` 中对应位置替换为新科目
   - `swap_date < 今天` → 删除过期记录
   - `swap_date > 今天` → 保留记录等待生效
3. **立即生效**：若 `swap_date` 为今天且主窗口当前正显示 `day_name` 对应星期，换课会立即应用到当前显示界面（无需重启）

---

## 三、信号（signal）

所有信号共用 `signalID: "events"`，通过返回值中的 `event` 字段区分具体事件类型。

信号由桥接层订阅 `TimeManager.time_tick`（每秒一次）进行**状态切换检测**后广播：仅当状态发生切换（如"非上课 → 上课"、"上课 → 课间"）时才发射，同一状态持续期间不重复推送。

> **注意**：本节仅记录**代码内置实现**的信号。用户在设置页「KnotLink → 事件系统」中新建自定义事件时，还会生成新的信号条目并写入 `Config/knotlink/signals.json`；这些自定义信号单独记录在《KnotLink 信号目录》（`KnotLink-Signals.md`）文档中，由程序在新建事件时自动维护。

### 3.1 onClassStart — 上课事件

- **signalID**: `events`
- **描述**: 当状态从"非上课"切换为"上课"时触发推送（即系统时间——含调试模拟时间——进入某节课的起止区间）。检测逻辑基于时间表 JSON 中的课时起止时间。

**返回值**:

| 字段名 | 说明 |
|--------|------|
| `event` | 事件标识（固定值 `onClassStart`），用于鉴别信号类型 |
| `period` | 课时序号（从 1 开始） |
| `subject` | 当前科目名称 |
| `startTime` | 课时开始时间（`HH:MM:SS`） |
| `endTime` | 课时结束时间（`HH:MM:SS`） |

---

### 3.2 onClassEnd — 下课事件

- **signalID**: `events`
- **描述**: 当一节课结束时触发推送。此时进入课间休息状态，附带下一节课的预告信息。

**返回值**:

| 字段名 | 说明 |
|--------|------|
| `event` | 事件标识（固定值 `onClassEnd`），用于鉴别信号类型 |
| `nextPeriod` | 下一节课时序号（若无下一节则为 `-1`） |
| `nextSubject` | 下一节科目名称（若无下一节则为空字符串） |
| `nextStartTime` | 下一节课开始时间（`HH:MM:SS`，若无下一节则为空） |
| `leftTime` | 课间剩余时间（`HH:MM:SS` 格式，即距下一节课还有多久） |

---

## 四、数据格式约定

### 星期名称

使用英文全称，首字母大写：

| 中文 | 英文 |
|------|------|
| 周一 | `Monday` |
| 周二 | `Tuesday` |
| 周三 | `Wednesday` |
| 周四 | `Thursday` |
| 周五 | `Friday` |
| 周六 | `Saturday` |
| 周日 | `Sunday` |

### 时间格式

统一使用 `HH:MM:SS`（24 小时制），例如 `08:00:00`、`14:30:00`。

### 日期格式

统一使用 `YYYY-MM-DD`，例如 `2026-08-11`。

### 课时键名

统一使用 `lesson_N` 格式，`N` 从 1 开始递增，例如 `lesson_1`、`lesson_3`。

---

## 五、调试模式说明

Schedule 4.0 支持调试模式（通过 `Config/debug_config.ini` 配置），可模拟任意日期/时间/星期。调试模式启用后：

- `get-lesson-state` 返回的状态基于模拟时间计算
- `get-today-schedule` 的"当天"使用模拟日期对应的星期
- `swap-course` 的换课日期判断以模拟日期为基准
- 信号 `onClassStart` / `onClassEnd` 按模拟时间流动触发

调试模式仅影响时间相关计算，不影响数据持久化逻辑。

---

## 六、错误处理

所有接口返回值中均包含 `status` 字段：

- `status=ok`：操作成功，业务数据在对应字段中
- `status=err`：操作失败，具体原因在 `message` 字段中

常见错误场景：
- `get-today-schedule` 中 `day` 不是合法星期名（`Monday`~`Sunday`）
- 换课操作中 `day_name` 不是合法星期名
- 换课操作中 `lesson_key` 格式无效（非 `lesson_N` 格式）
- 换课操作中 `lesson_key` 在当前时间表中不存在
- 换课操作中 `swap_date` 格式无效（非 `YYYY-MM-DD` 格式）
- 时间表数据为空时查询 `get-lesson-state`（返回 `status=err`）
