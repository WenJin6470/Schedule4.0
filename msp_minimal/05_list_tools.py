# -*- coding: utf-8 -*-
"""最小示例 5：列出课表节点对外提供的能力（工具与信号）。

用法：python msp_minimal/05_list_tools.py
"""
from msp import MSPNode, Preset

node = MSPNode("demo_tools", preset=Preset.LOCAL_AI)
node.start(settle=True, settle_timeout=5.0)

m = node.fetch_manifest("schedule4")     # 未连接时会按需连接
print("tools   =", [t["name"] for t in m.get("tools") or []])
print("signals =", [s["path"] for s in m.get("signals") or []])

node.stop()
