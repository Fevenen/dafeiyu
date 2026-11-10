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


def action_request(text):
    """Only ambiguous commands need a classifier; mentioning a tool is not a command."""
    if re.search(
        r"^(?:请)?(?:告诉我|跟我说|给我讲|你叫|叫什么|叫啥|为什么|怎么|什么是|解释)",
        (text or "").strip(),
    ):
        return False
    return bool(
        re.search(
            r"^(?:请|你)?(?:帮我|替我|麻烦你|帮忙)?\s*(?:给|跟|和|发|发送|喊|叫|让|通知|告诉|转告|设置|设个|设一|提醒|取消|删除|查看|查询|列出)|(?:后|点|分钟|小时).*提醒我",
            (text or "").strip(),
        )
    )


def native_task(text):
    """Expose native tools for explicit work, not casual questions/persona chat."""
    return bool(
        re.search(
            r"读(?:取)?文件|查看文件|打开|运行|执行|搜索|搜一下|检索|查一下|上网|浏览器|网页|网站|仓库|项目|代码|终端|命令|脚本|目录|文件夹|保存|下载|安装|修改|修复|创建|删除文件|read\s+|run\s+|search\s+|https?://|[A-Za-z]:[\\/]|\.(?:py|js|tsx?|json|md)\b",
            text or "",
            re.I,
        )
    )


def model_tools(definitions, text, continuation=False, policy="auto"):
    selected = select_tools(definitions, text)
    if continuation or policy == "all" or native_task(text):
        return selected
    # Recognized commands have already executed in the router; generic chat is light.
    if not action_request(text):
        return []
    return [
        item
        for item in selected
        if any(
            (item.get("function") or {}).get("name", "") == name
            or (item.get("function") or {}).get("name", "").endswith("_" + name)
            for name in BRIDGE_TOOLS
        )
    ]


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
