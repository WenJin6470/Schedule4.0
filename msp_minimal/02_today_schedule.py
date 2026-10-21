# -*- coding: utf-8 -*-
"""最小示例 2：获取当天或指定星期的课表。

用法：python msp_minimal/02_today_schedule.py            # 当天
      python msp_minimal/02_today_schedule.py Monday     # 指定星期
"""
import sys

from msp import MSPNode, Preset

node = MSPNode("demo_schedule", preset=Preset.LOCAL_AI)
node.start(settle=True, settle_timeout=5.0)

day = sys.argv[1] if len(sys.argv) > 1 else ""     # 空字符串 = 取当天
r = node.call("schedule4", "get-today-schedule", {"day": day}, timeout=10.0)
if r.is_error:
    print("调用失败：", r.error)
else:
    print(r.unwrap())

node.stop()
