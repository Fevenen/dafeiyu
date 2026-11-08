r"""server.py — MCP stdio 服务：把消息助手的能力暴露给桌宠的模型。

启动方式（由 pet\mcp_servers.json 指定）：
    D:\coding\python\python.exe D:\project\MP\pet\bridge\server.py
"""

import os
import sys

# 让 `import bridge.xxx` 能找到本文件所在的上一级目录（pet\）
_HERE = os.path.dirname(os.path.abspath(__file__))
_PET = os.path.dirname(_HERE)
if _PET not in sys.path:
    sys.path.insert(0, _PET)

from mcp.server.mcpserver import MCPServer  # noqa: E402

from bridge import tools  # noqa: E402

server = MCPServer("msg-bridge")


@server.tool(
    description=(
        "查询主人 QQ 的好友名单。只在用户明确提到「QQ / 好友 / 联系人 / 名单」时才调用"
        "（例如「QQ 联系人有哪些」「我好友里都有谁」）。"
        "用户只说「都有谁」「还有谁」这种模糊说法时不要调用，先反问他是不是要看 QQ 联系人。"
    )
)
def list_contacts(query: str = "") -> str:
    return tools.list_contacts(query)


@server.tool(
    description=(
        "给 QQ 好友发消息。参数 to 是好友名字（原样抄用户说的），text 是要发的内容。"
        "调用后不会立刻发送，而是先生成一条待确认；用户说「确认」才会真正发出。"
    )
)
def send_qq_message(to: str, text: str) -> str:
    return tools.send_qq_message(to, text)


@server.tool(
    description=(
        "设置提醒。time_text 原样抄用户说的时间（例如「10分钟后」「明天早上8点」），"
        "不要自己换算成日期；content 是要提醒的事。"
    )
)
def set_reminder(time_text: str, content: str) -> str:
    return tools.set_reminder(time_text, content)


@server.tool(description="查看当前所有待办提醒。")
def list_reminders() -> str:
    return tools.list_reminders()


@server.tool(description="取消提醒。keyword 是要取消的提醒内容里的关键词（留空则先列出全部）。")
def cancel_reminder(keyword: str = "") -> str:
    return tools.cancel_reminder(keyword)


@server.tool(
    description=(
        "确认发送之前挂起的那条消息。用户说「确认 / 发吧 / 好 / 嗯」时调用。"
        "只有刚调用过 send_qq_message 之后才有效。"
    )
)
def confirm_send() -> str:
    return tools.confirm_send()


@server.tool(
    description=(
        "取消之前挂起的那条消息。用户说「算了 / 取消 / 别发 / 不用了」时调用。"
    )
)
def cancel_send() -> str:
    return tools.cancel_send()


if __name__ == "__main__":
    server.run("stdio")
