r"""server.py — MCP stdio 服务：把消息助手的能力暴露给桌宠的模型。

启动方式（由 pet\mcp_servers.json 指定）：
    python -m bridge.server
"""

import os
import sys
import uuid

# 让 `import bridge.xxx` 能找到本文件所在的上一级目录（pet\）
_HERE = os.path.dirname(os.path.abspath(__file__))
_PET = os.path.dirname(_HERE)
if _PET not in sys.path:
    sys.path.insert(0, _PET)

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from bridge import tools  # noqa: E402
from bridge.context import scope, session_id

# Each stdio process owns a scope unless the installer/client sets an explicit ID.
os.environ.setdefault("BRIDGE_SESSION_ID", "mcp:" + uuid.uuid4().hex)

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


@server.tool(
    description="取消提醒。keyword 是要取消的提醒内容里的关键词（留空则先列出全部）。"
)
def cancel_reminder(keyword: str = "") -> str:
    return tools.cancel_reminder(keyword)


@server.tool(
    description=(
        "确认发送之前挂起的那条消息。用户说「确认 / 发吧 / 好 / 嗯」时调用。"
        "只有刚调用过 send_qq_message 之后才有效。"
    )
)
def confirm_send(confirmation: str) -> str:
    """confirmation 必须原样填写用户本轮的确认文字，不得自行编写。"""
    with scope(session_id(), text=confirmation):
        return tools.confirm_send()


@server.tool(
    description=(
        "取消之前挂起的那条消息。用户说「算了 / 取消 / 别发 / 不用了」时调用。"
    )
)
def cancel_send() -> str:
    return tools.cancel_send()


@server.tool(
    description=(
        "查看最近几条「代码已经替用户执行过」的动作（发消息 / 确认 / 提醒）。"
        "只在需要核对执行状态时调用；普通聊天无需查询。不要把历史结果当作本轮请求的结果。"
    )
)
def recent_actions(limit: int = 3) -> str:
    return tools.recent_actions(limit)


@server.tool(description="列出已注册的桌宠能力及其用途，不执行任何动作。")
def list_capabilities() -> str:
    import json
    from bridge.capabilities import describe

    return json.dumps(describe(), ensure_ascii=False)


@server.tool(
    description="统一处理桌宠命令。text 原样填写本轮用户的话；request_id 同一轮重试保持相同，不同轮必须不同。"
)
def route_command(text: str, request_id: str = "") -> str:
    from bridge.router import route
    from bridge.intent import classify

    with scope(session_id(), request_id or None, text):
        result = route(text, classifier=classify, allow_screen=False)
    return (
        result
        if result is not None
        else "未识别出明确命令；请正常回答或询问用户所需操作。"
    )


if __name__ == "__main__":
    server.run("stdio")
