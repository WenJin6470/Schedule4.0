# Schedule 4.0 — KnotLink 信号目录（自定义事件信号）

> 本文件由程序自动维护：在设置页「KnotLink → 事件系统」中新建事件时，
> 除把信号规则追加写入 `Config/knotlink/signals.json` 外，
> 也会自动把该信号的信息追加到本文档（与 signals.json 保持一致）。
>
> 代码内置信号（`onClassStart` / `onClassEnd`）
> 记录在《KnotLink-API.md》三、信号 章节，不在本文档中。

---

## onAfterSchoolAtNoon — 中午放学

- **信号变量名**: `onAfterSchoolAtNoon`
- **触发时间**: `12:00`
- **描述**: 中午上完第五节课，吃饭和午休时间

**载荷字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `onAfterSchoolAtNoon` | string | 中午放学 |
| `triggerTime` | string | 触发时间（HH:MM） |

**示例**:

```json
{"event": "onAfterSchoolAtNoon", "triggerTime": "12:00"}
```

---

## onAfternoonAfterSchool — 下午放学

- **信号变量名**: `onAfternoonAfterSchool`
- **触发时间**: `23:00`
- **描述**: 第四节晚自习结束，回寝睡觉

**载荷字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `onAfternoonAfterSchool` | string | 下午放学 |
| `triggerTime` | string | 触发时间（HH:MM） |

**示例**:

```json
{"event": "onAfternoonAfterSchool", "triggerTime": "23:00"}
```

---

## onEyerobics — 眼保健操

- **信号变量名**: `onEyerobics`
- **触发时间**: `10:15`
- **描述**: 眼保健操提醒

**载荷字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `onEyerobics` | string | 眼保健操 |
| `triggerTime` | string | 触发时间（HH:MM） |

**示例**:

```json
{"event": "onEyerobics", "triggerTime": "10:15"}
```

---
