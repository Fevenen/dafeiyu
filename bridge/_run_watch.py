"""_run_watch.py — 后台启动监听器（脱离 DSH 进程树，不需要 cmd.exe 包一层）。

做法：
    1. 自己把 stdout/stderr 重定向到 logs/watch.out / watch.err
    2. 再调用 dsh_watch.py 的 main()

由 WMI（Win32_Process.Create）或任务计划启动，父进程不是 DSH，所以 DSH 关了它也能活。
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.dirname(HERE)
sys.path.insert(0, PET)
from bridge import settings

LOGS = str(settings.LOG_DIR)
os.makedirs(LOGS, exist_ok=True)

_out = open(os.path.join(LOGS, "watch.out"), "a", encoding="utf-8", buffering=1)
_err = open(os.path.join(LOGS, "watch.err"), "a", encoding="utf-8", buffering=1)
sys.stdout = _out
sys.stderr = _err

if __name__ == "__main__":
    workspace = str(
        settings.path("workspace", os.path.join(os.path.dirname(PET), "pet_workspace"))
    )
    sys.argv = [
        os.path.join(HERE, "dsh_watch.py"),
        "--dir",
        workspace,
    ]
    runpy.run_path(os.path.join(HERE, "dsh_watch.py"), run_name="__main__")
