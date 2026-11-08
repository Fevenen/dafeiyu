"""gate.py — 确认闸门。

"确认 / 取消" 必须由代码判断，不能交给模型：
模型可能把"算了别发"理解成确认，或者没调工具就说"已经发了"。
"""

from . import safety, tools
from .v0_load import sender  # noqa: F401  （确保 v0 路径已加载）


def handle(text: str):
    """返回 (handled, reply)。

    handled=True  → reply 是给她说的话，直接播报，不进模型
    handled=False → 放行给模型（reply 忽略）
    """
    pending = safety.get_pending()
    if not pending:
        return False, ""

    if safety.is_cancel(text):
        safety.clear_pending()
        return True, "行吧，不发了。"

    if safety.is_confirm(text):
        uid = int(pending.get("uid") or 0)
        content = str(pending.get("text") or "")
        name = pending.get("name") or ""
        safety.clear_pending()
        if not uid or not content:
            return True, "那条待发的消息丢了，再说一次要发什么吧。"
        result = tools.do_send(uid, content)
        if result.startswith("已发送"):
            return True, "（点头）发出去了，%s 应该收到了。" % name
        return True, "没发出去：%s" % result

    # 其它内容：这条待确认作废，正常聊天
    safety.clear_pending()
    return False, ""
