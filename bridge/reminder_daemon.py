"""reminder_daemon.py — 提醒调度守护进程。

每 15 秒查一次待办：
  到点了 → ① 发 QQ 给自己  ② 让桌宠主动说一句
由 启动桌宠客户端.cmd 自动拉起（已在跑就跳过）。

用 v0 的 python 跑（需要 v0 的依赖）：
  <python> <桌宠目录>\\bridge\\reminder_daemon.py
"""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.dirname(HERE)
if PET not in sys.path:
    sys.path.insert(0, PET)

from bridge import STATE_DIR  # noqa: E402
from bridge.v0_load import reminders, sender  # noqa: E402

API = "http://127.0.0.1:12393/api/proactive"
PID_FILE = os.path.join(STATE_DIR, "scheduler.pid")
LOG_FILE = os.path.join(PET, "logs", "scheduler.log")


def log(msg: str) -> None:
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def already_running() -> bool:
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def self_uid():
    try:
        data = sender().get_login_info().get("data") or {}
        return data.get("user_id")
    except Exception:
        return None


def notify_pet(text: str) -> bool:
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:
        log("让桌宠说话失败：%s" % str(e)[:80])
        return False


def main() -> None:
    if already_running():
        log("已有调度进程在跑，退出")
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    log("提醒调度启动 pid=%d" % os.getpid())

    while True:
        try:
            due = reminders().due_now()
        except Exception as e:
            log("读提醒失败：%s" % str(e)[:80])
            due = []

        for item in due:
            text = str(item.get("text") or "").strip()
            rid = item.get("id")
            if not text or not rid:
                continue
            uid = self_uid()
            if uid:
                try:
                    res = sender().send_private(int(uid), "⏰ 提醒：%s" % text)
                    if res.get("retcode") != 0:
                        log("QQ 发送失败：%s" % str(res)[:100])
                except Exception as e:
                    log("QQ 发送异常：%s" % str(e)[:80])
            else:
                log("拿不到自己的 QQ 号，跳过 QQ 通知")

            reminders().mark_fired([rid])
            notify_pet("（系统通知）提醒时间到了：%s。用一句话提醒主人。" % text)
            log("已提醒：%s" % text)

        time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
