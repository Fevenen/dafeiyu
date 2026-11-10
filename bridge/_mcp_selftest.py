"""_mcp_selftest.py — 用 MCP 客户端连上 bridge/server.py，验证 7 个工具。"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CMD = sys.executable
SCRIPT = str(__import__("pathlib").Path(__file__).with_name("server.py"))


async def main():
    params = StdioServerParameters(command=CMD, args=[SCRIPT], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("  工具数: %d" % len(names))
            print("  工具: %s" % ", ".join(names))

            async def call(name, args=None):
                r = await session.call_tool(name, args or {})
                text = ""
                for c in r.content:
                    if getattr(c, "type", "") == "text":
                        text += c.text
                return text

            def short(s, n=60):
                return s.replace("\n", " ")[:n]

            print("  1) list_contacts:", short(await call("list_contacts", {})))
            print(
                "  2) send:",
                short(
                    await call("send_qq_message", {"to": "Z", "text": "自测，请勿确认"})
                ),
            )
            print("  3) cancel_send:", short(await call("cancel_send", {})))
            print(
                "  4) set_reminder:",
                short(
                    await call(
                        "set_reminder", {"time_text": "1小时后", "content": "自测"}
                    )
                ),
            )
            print("  5) list_reminders:", short(await call("list_reminders", {})))
            print(
                "  6) cancel_reminder:",
                short(await call("cancel_reminder", {"keyword": "自测"})),
            )


asyncio.run(main())
