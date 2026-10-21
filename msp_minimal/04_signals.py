# -*- coding: utf-8 -*-
"""最小示例 4：订阅课表的上下课信号（schedule.class.start / schedule.class.end）。

用法：python msp_minimal/04_signals.py      然后用 Ctrl+C 退出
注意：信号只发给「当时已连上」的订阅方，未连上时会丢。
"""
import time

from msp import MSPNode, Preset

node = MSPNode("demo_signals", preset=Preset.LOCAL_AI)
node.on("schedule.**")(lambda sig: print(sig.path, sig.payload, flush=True))  # 先订阅
node.start(settle=True, settle_timeout=5.0)

print("已连接：", node.connections(), "—— 等待信号，Ctrl+C 退出", flush=True)
try:
    while True:
        time.sleep(1)
finally:
    node.stop()
