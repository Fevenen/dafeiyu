"""Capability registry. Register here to expose a new group to intent routing."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    pattern: str
    tools: tuple


REGISTRY = (
    Capability(
        "qq",
        "给 QQ 好友准备、确认或取消消息，查询联系人",
        r"QQ|qq|发消息|发信息|消息|告诉|通知|转告|跟.+说|喊|叫|联系人|好友|确认|发吧|取消|算了",
        ("list_contacts", "send_qq_message", "confirm_send", "cancel_send"),
    ),
    Capability(
        "reminders",
        "创建、查看、取消定时提醒",
        r"提醒|待办|叫我|喊我",
        ("set_reminder", "list_reminders", "cancel_reminder"),
    ),
)
BRIDGE_TOOLS = frozenset(t for c in REGISTRY for t in c.tools) | {
    "recent_actions",
    "route_command",
    "list_capabilities",
}


def candidates(text):
    return [c for c in REGISTRY if re.search(c.pattern, text or "")]


def select_tools(definitions, text):
    """Keep native DSH tools; include only relevant companion tool schemas."""
    allowed = {t for c in candidates(text) for t in c.tools} | {
        "route_command",
        "list_capabilities",
    }
    result = []
    for item in definitions or []:
        name = (item.get("function") or {}).get("name", "")
        # DSH MCP names may have a server prefix.
        own = next(
            (
                t
                for t in BRIDGE_TOOLS
                if name == t or name.endswith("__" + t) or name.endswith("_" + t)
            ),
            None,
        )
        if own is None or own in allowed:
            result.append(item)
    return result


def describe():
    return [
        {"name": c.name, "description": c.description, "tools": list(c.tools)}
        for c in REGISTRY
    ]
