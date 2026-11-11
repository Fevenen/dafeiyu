"""Capability registry. Register here to expose a new group to intent routing."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    pattern: str
    tools: tuple
    intent_actions: tuple = ()


SCREEN_PATTERN = (
    r'屏幕|画面|截图|窗口'
    r'|^(?:那|所以|请|帮我|你再|再)?\s*(?:这(?:个|道|题|张|里|一问)?|那个|那里|它|第二问|下一问|上一问|上面|下面|左边|右边)'
    r'.{0,50}(?:怎么|什么|啥|意思|选|做|看|不懂|呢|对不对|为什么)'
    r'|^(?:我)?(?:该|应该)?选哪个[？?。！!]*$'
)


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
    Capability('screen', '读取用户已授权的当前屏幕，理解题目、报错、界面或含糊的画面指代',
               SCREEN_PATTERN, (), ('observe_screen',)),
)
BRIDGE_TOOLS = frozenset(t for c in REGISTRY for t in c.tools) | {
    "recent_actions",
    "route_command",
    "list_capabilities",
}


def candidates(text):
    return [c for c in REGISTRY if re.search(c.pattern, text or "")]


def command_text(text):
    q = (text or "").strip()
    # Strip conversational lead-ins before both rule parsing and classifier gating.
    # Never strip a standalone confirmation or search inside arbitrary prose.
    for _ in range(3):
        previous = q
        q = re.sub(r"^(?:ok(?:ay)?|嗯嗯?|好[的啦呀]?|行|不用啦|不用了|那就|那)[，,、：:\s]+(?=\S)", "", q, flags=re.I)
        q = re.sub(r"^(?:你)?(?:(?:能不能|可以|能)\s*)?(?:请)?(?:帮我|替我|麻烦你|请你|帮忙)\s*", "", q)
        q = re.sub(r"^(?:你)?(?:请)?\s*", "", q)
        q = re.sub(r"^(?:在|上|通过)?QQ(?:上|里)?\s*", "", q, flags=re.I)
        if q == previous:
            break
    return q



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
    if policy == "all":
        return selected
    # Companion actions are owned by the semantic dispatcher, never re-issued by chat.
    if continuation or native_task(text):
        return [item for item in selected if not any(
            (item.get('function') or {}).get('name', '') == name
            or (item.get('function') or {}).get('name', '').endswith('_' + name)
            for name in BRIDGE_TOOLS)]
    return []


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
        {"name": c.name, "description": c.description, "tools": list(c.tools),
         **({'intent_actions': list(c.intent_actions)} if c.intent_actions else {})}
        for c in REGISTRY
    ]
