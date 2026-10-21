# -*- coding: utf-8 -*-
"""最小示例 3：临时换课（写换课记录，生效日当天自动替换科目）。

用法：python msp_minimal/03_swap_course.py
注意：会真的写入 Config/swap_schedule.json。
"""
from msp import MSPNode, Preset

node = MSPNode("demo_swap", preset=Preset.LOCAL_AI)
node.start(settle=True, settle_timeout=5.0)

args = {
    "day_name": "Monday",        # Monday ~ Sunday
    "lesson_key": "lesson_2",    # 必须是当前时间表里存在的课时键
    "new_subject": "数学",
    "swap_date": "2026-10-20",   # 留空 = 该星期的下一个匹配日
}
r = node.call("schedule4", "swap-course", args, timeout=10.0)
if r.is_error:
    print("调用失败：", r.error)
else:
    print(r.unwrap())

node.stop()
