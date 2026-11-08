"""桌宠消息/提醒桥接。

不再依赖外部的 v0 项目：需要的模块已经内置在 _v0\ 里。
"""

import os

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
PET_ROOT = os.path.dirname(BRIDGE_DIR)
STATE_DIR = os.path.join(BRIDGE_DIR, "state")
LOG_DIR = os.path.join(BRIDGE_DIR, "logs")

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)