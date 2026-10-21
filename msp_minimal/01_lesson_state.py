# -*- coding: utf-8 -*-
"""最小示例 1：查询课表实时上课状态。运行前先启动课表程序 python main.py。

用法：python msp_minimal/01_lesson_state.py
"""
from msp import MSPNode, Preset

node = MSPNode("demo_state", preset=Preset.LOCAL_AI)
node.start(settle=True, settle_timeout=5.0)   # settle：等连接落地，之后可直接 call

r = node.call("schedule4", "get-lesson-state", {}, timeout=10.0)
if r.is_error:
    print("调用失败：", r.error)
else:
    print(r.unwrap())

node.stop()
