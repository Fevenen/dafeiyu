"""kvmem_proxy.py — 夹在 DSH 和本地 KVMem 之间的"工具调用修复代理"。

为什么需要：
    本地模型（kvmem-polystrata-qwen35）经常把工具调用写成文字：
        「（调用 send_qq_message）给小 z 发消息…」
    而不是真的返回 tool_calls。DSH 就把这段文字显示出来，于是 DSH 里"查不了联系人"。

这个代理做的事：
    1. 转发请求到 KVMem
    2. 如果模型只输出了"（调用 xxx）"文字 → 删掉这些旁白
    3. 如果模型没给 tool_calls，但用户这句话明显是命令 → 替它补上 tool_call
    4. 把结果按 DSH 要的格式返回（流式/非流式都支持）

启动：
    python bridge/kvmem_proxy.py          # 监听 127.0.0.1:18080
DSH 那边把 providers.kvmem.baseURL 改成 http://127.0.0.1:18080/v1
"""

import json
import os
import re
import sys
import time
import uuid

import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("KVMEM_UPSTREAM", "http://127.0.0.1:18200")
PORT = int(os.environ.get("KVMEM_PROXY_PORT", "18080"))
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.path.dirname(HERE), "logs", "kvmem_proxy.log")

FAKE_CALL = re.compile(r"[（(][^）)]{0,160}(?:调用|工具调用|正在调用|确认发送|使用工具)[^）)]{0,160}[）)]")

PET = os.path.dirname(HERE)
KEEP_MESSAGES = int(os.environ.get("KVMEM_KEEP_MESSAGES", "10"))
_LAST_CMD = {"text": None, "ts": 0.0}


def trim_messages(messages, keep=None):
    """只保留 system 提示词 + 最近 keep 条消息（默认 10）。

    目的：DSH 每轮都把整个会话重发一遍（实测 65 条 / 2.2 万字），
    本地模型光读这些就要好几秒。截断后只读最近几轮。
    """
    keep = KEEP_MESSAGES if keep is None else keep
    if not messages or keep <= 0:
        return messages
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if len(rest) <= keep:
        return messages
    tail = rest[-keep:]
    # 别让开头孤零零一条 tool 结果（前面配对的消息被截掉了）
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    return sys_msgs + tail


def _bridge():
    if PET not in sys.path:
        sys.path.insert(0, PET)
    from bridge import fastpath, safety, tools  # noqa: E402

    return fastpath, safety, tools


def _log_router(prompt, action, result):
    try:
        path = os.path.join(HERE, "state", "router_log.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "prompt": (prompt or "")[:120],
                "action": action,
                "result": (result or "")[:200],
                "source": "proxy",
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


VERB_SEND = re.compile(r"^(?:你)?(?:帮我|替我)?\s*(?:喊|叫|通知|告诉|转告)\s*(?:一下|一声|个)?\s*")


def try_verb_send(text):
    """处理"喊/叫/通知/告诉 + 人 + 内容"这类说法，转成 send_qq_message。"""
    m = VERB_SEND.match(text or "")
    if not m:
        return None
    rest = (text or "")[m.end():].strip()
    if not rest:
        return None
    try:
        from bridge import safety, tools

        rows = safety.list_contacts("") or []
        if not rows:
            safety.ensure_contacts(force=True)
            rows = safety.list_contacts("") or []
    except Exception:
        return None
    # 用真实联系人名字匹配开头（长名字优先，避免 "Z" 抢先）
    for r in sorted(rows, key=lambda x: -len(str(x.get("name") or ""))):
        name = str(r.get("name") or "")
        if name and rest.startswith(name):
            content = rest[len(name):].lstrip("，,、 ：:说 ")
            if not content:
                continue
            try:
                return tools.send_qq_message(name, content)
            except Exception as e:
                log("  喊话失败：%s" % e)
                return None
    m2 = re.match(r"([A-Za-z0-9_]{2,20})\s*(?:说|，|,|\s)\s*(.+)", rest)
    if m2:
        try:
            return tools.send_qq_message(m2.group(1), m2.group(2))
        except Exception:
            return None
    return None


CMD_HINT = re.compile(
    r"发|消息|信息|告诉|通知|转告|转达|提醒|喊|叫|让|确认|取消|算了|联系人|好友|待办"
)
CLASSIFY_SYSTEM = (
    "你是指令解析器。把用户的话解析成 JSON，只调用 parse_command 工具，不要输出任何解释。\n"
    "规则：\n"
    "1. 让某人收到消息（给X发消息/告诉X/跟X说/喊X/叫X/让X/通知X/转告X）→ intent=send，"
    "target 填收件人，content 填要说的内容（去掉“说/一下/一声”等词）。\n"
    "2. 让助手自己记住某事（提醒我/到点告诉我/十点叫我）→ intent=remind，time_text 填时间，content 填事情。\n"
    "3. 确认/发吧/嗯/好 → intent=confirm。\n"
    "4. 取消/算了/别发 → intent=cancel。\n"
    "5. 查看联系人/好友列表 → intent=list。\n"
    "6. 其它（闲聊、提问、让你解释）→ intent=chat，其它字段留空。\n"
    "只解析，不执行，不回复用户。"
)
CLASSIFY_TOOL = [{
    "type": "function",
    "function": {
        "name": "parse_command",
        "description": "解析用户指令",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["send", "remind", "confirm", "cancel", "list", "chat"]},
                "target": {"type": "string"},
                "content": {"type": "string"},
                "time_text": {"type": "string"},
            },
            "required": ["intent"],
        },
    },
}]


def classify_and_execute(text):
    """规则没认出来时，让本地模型只输出 JSON 意图，再由代码执行。"""
    q = (text or "").strip()
    if not q or len(q) > 80 or not CMD_HINT.search(q):
        return None
    payload = {
        "model": os.environ.get("KVMEM_MODEL", "kvmem-polystrata-qwen35"),
        "stream": False,
        "tools": CLASSIFY_TOOL,
        "tool_choice": {"type": "function", "function": {"name": "parse_command"}},
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": q},
        ],
    }
    try:
        r = requests.post(UPSTREAM + "/v1/chat/completions",
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
                          timeout=30)
        data = r.json()
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        calls = msg.get("tool_calls") or []
        if not calls:
            return None
        args = json.loads(calls[0]["function"]["arguments"] or "{}")
    except Exception as e:
        log("  意图分类失败：%s" % e)
        return None

    intent = (args.get("intent") or "").strip()
    log("  分类结果：%s" % json.dumps(args, ensure_ascii=False)[:120])
    target = (args.get("target") or "").strip()
    content = (args.get("content") or "").strip()
    when = (args.get("time_text") or "").strip()
    log("  意图分类：%s target=%r content=%r time=%r" % (intent, target, content[:30], when))
    if intent == "chat" or not intent:
        return None
    try:
        from bridge import tools

        if intent == "send" and target and content:
            reply = tools.send_qq_message(target, content)
        elif intent == "remind" and when and content:
            reply = tools.set_reminder(when, content)
        elif intent == "confirm":
            reply = tools.confirm_send()
        elif intent == "cancel":
            reply = tools.cancel_send()
        elif intent == "list":
            reply = tools.list_contacts("")
        else:
            return None
    except Exception as e:
        log("  意图执行失败：%s" % e)
        return None
    if reply:
        _log_router(q, "classify_" + intent, reply)
    return reply or None


def execute_command(text):
    """命令直通：能确定是命令就由代码执行，返回要说的文字；否则 None（交给模型）。

    做三件事：确认/取消、发消息、查联系人/提醒。
    去重：同一条话 10 秒内只执行一次（DSH 重试时不会重复发）。
    """
    q = (text or "").strip()
    if not q or len(q) > 80:
        return None
    now = time.time()
    if q == _LAST_CMD["text"] and now - _LAST_CMD["ts"] < 10:
        return None
    try:
        fastpath, safety, tools = _bridge()
    except Exception as e:
        log("  命令直通不可用（导入失败）：%s" % e)
        return None
    try:
        if safety.get_pending():
            if safety.is_confirm(q):
                r = tools.confirm_send()
                _LAST_CMD.update(text=q, ts=now)
                _log_router(q, "confirm_send", r)
                return r
            if safety.is_cancel(q):
                r = tools.cancel_send()
                _LAST_CMD.update(text=q, ts=now)
                _log_router(q, "cancel_send", r)
                return r
        verb = try_verb_send(q)
        if verb:
            _LAST_CMD.update(text=q, ts=now)
            _log_router(q, "verb_send", verb)
            return verb
        handled, reply = fastpath.try_handle(q)
        if handled and reply:
            _LAST_CMD.update(text=q, ts=now)
            _log_router(q, "fastpath", reply)
            return reply
    except Exception as e:
        log("  命令执行失败：%s" % e)
    return None


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        if sys.stdout is not None:
            print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tool_names(tools):
    out = []
    for t in tools or []:
        fn = (t.get("function") or {})
        name = fn.get("name") or ""
        if name:
            out.append(name)
    return out


def last_user_text(messages):
    for m in reversed(messages or []):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def strip_fake_calls(text):
    if not text:
        return text
    t = FAKE_CALL.sub("", text)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def guess_tool_call(user_text, names, model):
    """根据用户这句话猜该调哪个工具（只在模型没给 tool_calls 时用）。"""
    q = (user_text or "").strip()
    if not q:
        return None

    def make(fn, args):
        return {
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": fn, "arguments": json.dumps(args, ensure_ascii=False)},
        }

    m = re.search(r"给\s*(.+?)\s*发(?:个)?消息(?:说|：|:)?\s*(.+)", q)
    if m and "send_qq_message" in names:
        to = m.group(1).strip(" ，,、。")
        text = m.group(2).strip(" 。")
        if to and text:
            return make("send_qq_message", {"to": to, "text": text})

    if re.fullmatch(r"(确认|发吧|发送|好|嗯|行|可以)[。！!]?", q) and "confirm_send" in names:
        return make("confirm_send", {})

    if re.fullmatch(r"(取消|算了|别发|不用了)[。！!]?", q) and "cancel_send" in names:
        return make("cancel_send", {})

    if ("联系人" in q or "好友列表" in q) and "list_contacts" in names:
        return make("list_contacts", {"query": ""})

    m = re.search(r"提醒我\s*(.+?)\s*(?:去|要)?\s*(.+)", q)
    if m and "set_reminder" in names:
        when = m.group(1).strip(" ，,。")
        what = m.group(2).strip(" 。")
        if when and what:
            return make("set_reminder", {"time_text": when, "content": what})

    return None


def fix_message(msg, tools, messages):
    """返回 (message, 是否补了 tool_call)"""
    names = tool_names(tools)
    content = msg.get("content") or ""
    cleaned = strip_fake_calls(content)
    if cleaned != content:
        log("  删掉旁白：%r -> %r" % (content[:40], cleaned[:40]))
    msg["content"] = cleaned

    if msg.get("tool_calls"):
        return msg, False

    guess = guess_tool_call(last_user_text(messages), names, msg.get("role"))
    if guess:
        msg["tool_calls"] = [guess]
        msg["content"] = ""
        log("  补工具调用：%s %s" % (guess["function"]["name"], guess["function"]["arguments"][:60]))
        return msg, True
    return msg, False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            try:
                r = requests.get(UPSTREAM + "/v1/models", timeout=20,
                                 headers={"Authorization": self.headers.get("Authorization", "")})
                return self._send_json(r.json(), r.status_code)
            except Exception as e:
                return self._send_json({"data": []})
        self._send_json({"ok": True, "proxy": "kvmem", "upstream": UPSTREAM})

    def _reply(self, want_stream, model, content, usage=None):
        """直接返回一句"助手回复"（不经过模型）。"""
        created = int(time.time())
        cid = "chatcmpl-proxy-" + uuid.uuid4().hex[:16]
        if not want_stream:
            return self._send_json({
                "id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                              "finish_reason": None}]}
        self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
        done = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        self.wfile.write(("data: " + json.dumps(done, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        try:
            self.wfile.flush()
        except Exception:
            pass

    def _passthrough_stream(self, req_body):
        """聊天请求：原样透传 KVMem 的 SSE，边生成边给 DSH（不攒整段）。"""
        body = dict(req_body)
        body["stream"] = True
        body["messages"] = trim_messages(body.get("messages") or [])
        # 聊天不需要工具：去掉工具定义，提示词从 ~7.3k 降到几百 token，预填充快很多
        body.pop("tools", None)
        body.pop("tool_choice", None)
        # 不限制输出长度（由模型自己决定；用户要求正常聊天 1~2 句，复杂问题多解释）
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.headers.get("Authorization", "Bearer local"),
        }
        try:
            up = requests.post(UPSTREAM + "/v1/chat/completions",
                               data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                               headers=headers, stream=True, timeout=600)
        except Exception as e:
            log("上游流式失败：%s" % e)
            self._send_json({"error": {"message": "upstream failed: %s" % e}}, 502)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for line in up.iter_lines(decode_unicode=False):
                if line:
                    self.wfile.write(line + b"\n\n")
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            try:
                up.close()
            except Exception:
                pass

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req_body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "bad json"}, 400)
            return

        want_stream = bool(req_body.get("stream"))
        try:
            _msgs = req_body.get("messages") or []
            _chars = sum(len(m.get("content") or "") for m in _msgs if isinstance(m.get("content"), str))
            log("请求：msgs=%d chars=%d tools=%d max_tokens=%s stream=%s"
                % (len(_msgs), _chars, len(req_body.get("tools") or []),
                   req_body.get("max_tokens"), want_stream))
        except Exception:
            pass
        tools = req_body.get("tools") or []
        messages = req_body.get("messages") or []
        model = req_body.get("model")

        # 命令直通：不叫模型，代码直接执行，再把结果当成助手回复返回
        user_text = last_user_text(messages)
        cmd_reply = execute_command(user_text)
        if cmd_reply is not None:
            log("  命令直通：%r -> %r" % (user_text[:20], cmd_reply[:40]))
            return self._reply(want_stream, model, cmd_reply)

        # 规则没认出来 → 让本地模型只输出 JSON 意图，再由代码执行
        classified = classify_and_execute(user_text)
        if classified is not None:
            log("  分类直通：%r -> %r" % (user_text[:20], classified[:40]))
            return self._reply(want_stream, model, classified)

        # 聊天：流式请求直接透传（保证边生成边显示，不攒完整段）
        if want_stream:
            return self._passthrough_stream(req_body)

        upstream_body = dict(req_body)
        upstream_body["stream"] = False  # 先拿到完整结果再修
        upstream_body["messages"] = trim_messages(upstream_body.get("messages") or [])

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.headers.get("Authorization", "Bearer local"),
        }
        try:
            r = requests.post(UPSTREAM + "/v1/chat/completions",
                              data=json.dumps(upstream_body, ensure_ascii=False).encode("utf-8"),
                              headers=headers, timeout=600)
            data = r.json()
        except Exception as e:
            log("上游失败：%s" % e)
            self._send_json({"error": {"message": "upstream failed: %s" % e}}, 502)
            return

        try:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            msg, patched = fix_message(msg, tools, messages)
            choice["message"] = msg
            choice["finish_reason"] = "tool_calls" if msg.get("tool_calls") else (choice.get("finish_reason") or "stop")
        except Exception as e:
            log("修正失败：%s" % e)

        if not want_stream:
            return self._send_json(data)

        # 转成 SSE：把完整结果当成一个 delta 发出去
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        delta = {"role": "assistant"}
        if msg.get("tool_calls"):
            delta["tool_calls"] = [
                {"index": i, "id": t.get("id"), "type": "function", "function": t.get("function")}
                for i, t in enumerate(msg["tool_calls"])
            ]
        if msg.get("content"):
            delta["content"] = msg["content"]
        chunk = {
            "id": data.get("id") or "chatcmpl-proxy",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": data.get("model") or req_body.get("model"),
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
        done = {
            "id": chunk["id"], "object": "chat.completion.chunk", "created": chunk["created"],
            "model": chunk["model"],
            "choices": [{"index": 0, "delta": {}, "finish_reason": chunk and ("tool_calls" if msg.get("tool_calls") else "stop")}],
            "usage": data.get("usage") or {},
        }
        self.wfile.write(("data: " + json.dumps(done, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        try:
            self.wfile.flush()
        except Exception:
            pass


def main():
    log("KVMem 修复代理启动：127.0.0.1:%d -> %s" % (PORT, UPSTREAM))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
