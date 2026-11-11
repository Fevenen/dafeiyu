"""Apply the current pet response rules even to already-open DSH sessions."""

from .screen_context import screen_skip_reason

POLICY = (
    "【本轮桌宠回复要求】默认只回复1到2句，共20到60个汉字，最多80字；说完就停。"
    "不要复述问题、长篇动作旁白、列建议清单、追加多个问题；动作最多一处。"
    "只有用户明确要求详细解释、展开、完整步骤/清单/代码时才增加篇幅，事实与必要代码必须完整。"
    "本桌宠服务已接入QQ联系人、消息准备/确认和定时提醒，不要因本轮没附工具而声称这些能力不存在。"
    "定时提醒是提醒用户，不等于自动给好友定时发QQ；时间含糊时只问清时间。"
    "操作先取得真实工具结果，准确转述收件人、内容、状态和确认要求；没有本轮结果，"
    "绝不演示点击发送、声称消息已发送/已记下提醒/已设置闹钟。"
)


def apply_reply_policy(body):
    if screen_skip_reason(body) == "background_task":
        return body
    updated = dict(body)
    messages = list(body.get("messages") or [])
    index = next((i for i, row in enumerate(messages) if row.get("role") not in ("system", "developer")), len(messages))
    messages.insert(index, {"role": "system", "content": POLICY})
    updated["messages"] = messages
    return updated
