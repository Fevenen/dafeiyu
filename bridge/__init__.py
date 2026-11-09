"""把 v0（消息助手）的现成能力接进桌宠。

这个包里所有模块都复用 D:\\project\\MP\\v0\\assistant 下的代码：
  config / vault / sender / reminders / when / name_match
不重新实现发送、解析、匹配逻辑。
"""

import os
import sys

V0_ASSISTANT = r"D:\project\MP\v0\assistant"
BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BRIDGE_DIR, "state")

os.makedirs(STATE_DIR, exist_ok=True)

if V0_ASSISTANT not in sys.path:
    sys.path.insert(0, V0_ASSISTANT)
