"""run_suite.py — 跑一轮回归测试，结果写到 logs/suite.log（UTF-8）。"""

import asyncio
import io
import sys

sys.path.insert(0, r"D:\project\MP\pet\bridge")

from ws_test import talk  # noqa: E402

CASES = [
    ("QQ联系人有哪些", "应该列出 6 个联系人"),
    ("1分钟后提醒我喝水", "应该确认 1 分钟后提醒"),
    ("我有什么提醒", "应该列出喝水那条"),
    ("给feven发消息说这是一条测试消息", "应该挂起待确认"),
    ("算了", "应该取消，不发送"),
    ("给王五发消息说你好", "应该提示没找到"),
    ("今天好累", "应该正常聊天，不调工具"),
]


async def main():
    out = io.open(r"D:\project\MP\pet\logs\suite.log", "w", encoding="utf-8")
    for i, (text, expect) in enumerate(CASES, 1):
        try:
            reply = await talk(text, wait=100.0)
        except Exception as e:
            reply = "[异常] %s: %s" % (type(e).__name__, e)
        line = "%d. 你：%s\n   预期：%s\n   她：%s\n" % (i, text, expect, reply or "（没回复）")
        print(line, flush=True)
        out.write(line + "\n")
        out.flush()
    out.close()


asyncio.run(main())
