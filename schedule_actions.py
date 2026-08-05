"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_actions.py（统一动作协议）             ║
║                 （Action 枚举 + 结构化 ActionMessage）                    ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
  定义课表系统中所有动作的类型枚举和结构化消息格式，
  替代分散在各文件中的 magic string，提供编译期类型检查。

📌 设计决策
═══════════════════════════════════════════════════════════════════════════
  - ActionType 使用 StrEnum：同时兼容字符串比较和枚举值比较
  - ActionMessage 使用 frozen dataclass：不可变，安全传递
  - 工厂方法：统一消息构造逻辑，避免手动拼接字符串
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ==================== 动作类型枚举 ====================

class ActionType(StrEnum):
    """课表系统统一动作枚举。StrEnum 继承 str，可直接用于字符串比较。"""

    # ---- 系统操作 ----
    CLOSE                     = "close"
    FULLSCREEN_TIME           = "fullscreen_time"
    FULLSCREEN_TIME_EXAM      = "fullscreen_time_exam"
    FULLSCREEN_TIME_CREATIVE  = "fullscreen_time_creative"
    SETTINGS                  = "settings"

    # ---- 快捷编辑 ----
    QUICK_EDIT_OPENED  = "quick_edit_opened"
    QUICK_EDIT_CLOSED  = "quick_edit_closed"
    CONFIRM            = "confirm"
    MOVE_UP            = "move_up"
    MOVE_DOWN          = "move_down"
    MOVE_DOUBLE_UP     = "move_double_up"
    MOVE_DOUBLE_DOWN   = "move_double_down"

    # ---- 数据操作 ----
    SUBJECT_SELECTED     = "subject_selected"
    CURSOR_INFO          = "cursor_info"
    WEEK_CHANGED         = "week_changed"
    TEMP_SWAP_CONFIRMED  = "temp_swap_confirmed"


# ==================== 结构化动作消息 ====================

@dataclass(frozen=True)
class ActionMessage:
    """
    结构化动作消息 —— 替代裸字符串 + 手动解析。

    frozen=True 确保消息不可变，安全地在 Signal 中传递。
    ---

    字段：
      type    （ActionType）：动作类型
      payload （dict）：      携带的数据（可选）
    """

    type: ActionType
    payload: dict[str, Any] = field(default_factory=dict)

    # ================================================================
    #  工厂方法：快捷构造常用消息
    # ================================================================

    @classmethod
    def close(cls) -> "ActionMessage":
        """关闭所有窗口并退出程序。"""
        return cls(ActionType.CLOSE)

    @classmethod
    def fullscreen_time(cls) -> "ActionMessage":
        """显示全屏时间窗口（旧版，无模式选择）。"""
        return cls(ActionType.FULLSCREEN_TIME)

    @classmethod
    def fullscreen_time_exam(cls) -> "ActionMessage":
        """考试模式全屏时间 — 纯色背景 + 实时时间。"""
        return cls(ActionType.FULLSCREEN_TIME_EXAM)

    @classmethod
    def fullscreen_time_creative(cls) -> "ActionMessage":
        """创意模式全屏时间 — 随机图片背景 + 红色实时时间。"""
        return cls(ActionType.FULLSCREEN_TIME_CREATIVE)

    @classmethod
    def settings(cls) -> "ActionMessage":
        """打开设置窗口。"""
        return cls(ActionType.SETTINGS)

    @classmethod
    def quick_edit_opened(cls) -> "ActionMessage":
        """快捷编辑窗口已打开。"""
        return cls(ActionType.QUICK_EDIT_OPENED)

    @classmethod
    def quick_edit_closed(cls) -> "ActionMessage":
        """快捷编辑窗口已关闭。"""
        return cls(ActionType.QUICK_EDIT_CLOSED)

    @classmethod
    def confirm(cls) -> "ActionMessage":
        """确认编辑操作。"""
        return cls(ActionType.CONFIRM)

    @classmethod
    def move_up(cls) -> "ActionMessage":
        """光标向上移动 1 步。"""
        return cls(ActionType.MOVE_UP)

    @classmethod
    def move_down(cls) -> "ActionMessage":
        """光标向下移动 1 步。"""
        return cls(ActionType.MOVE_DOWN)

    @classmethod
    def move_double_up(cls) -> "ActionMessage":
        """光标向上移动 2 步。"""
        return cls(ActionType.MOVE_DOUBLE_UP)

    @classmethod
    def move_double_down(cls) -> "ActionMessage":
        """光标向下移动 2 步。"""
        return cls(ActionType.MOVE_DOUBLE_DOWN)

    @classmethod
    def subject_selected(cls, name: str) -> "ActionMessage":
        """
        用户选择了一个科目。
        ------------------
        参数：
            name（str）：科目名称
        """
        return cls(ActionType.SUBJECT_SELECTED, {"name": name})

    @classmethod
    def cursor_info(cls, index: int, text: str) -> "ActionMessage":
        """
        光标位置信息。
        ------------
        参数：
            index（int）：光标所在课时索引（0-based）
            text （str）：课时当前显示的科目文字
        """
        return cls(ActionType.CURSOR_INFO, {"index": index, "text": text})

    @classmethod
    def week_changed(cls, index: int, week_name: str) -> "ActionMessage":
        """
        星期滚轮切换到了新的星期。
        ------------------------
        参数：
            index     （int）：星期索引（0=Monday, ..., 6=Sunday）
            week_name （str）：星期名称，如 'Monday'
        """
        return cls(ActionType.WEEK_CHANGED, {"index": index, "week_name": week_name})

    @classmethod
    def temp_swap_confirmed(cls, swaps: list) -> "ActionMessage":
        """
        用户确认了临时换课。
        -----------------
        参数：
            swaps（list[dict]）：换课数据列表，每项包含
                                day_name, lesson_key, old_subject,
                                new_subject, swap_date
        """
        return cls(ActionType.TEMP_SWAP_CONFIRMED, {"swaps": swaps})
