"""KVMem gateway: scoped capability routing and lossless SSE passthrough."""

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import settings
from bridge.context import scope
from bridge.router import route
from bridge.capabilities import model_tools
from bridge.net import request as http_request
from bridge import store
from bridge.screen_context import attach_screen, screen_skip_reason
from bridge.reply_policy import apply_reply_policy
from bridge.intent import classify as classify_intent
from bridge.game_context import attach_game

UPSTREAM = str(settings.get("kvmem_upstream", "http://127.0.0.1:18200")).rstrip("/")
PORT = int(settings.get("kvmem_proxy_port", 18080))


def log(message):
    settings.ensure_dirs()
    with (settings.LOG_DIR / "kvmem_proxy.log").open("a", encoding="utf-8") as stream:
        stream.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")


def last_user_text(messages):
    for item in reversed(messages or []):
        if item.get("role") == "user":
            content = item.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    x.get("text", "") for x in content if x.get("type") == "text"
                )
    return ""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def identity(body, headers):
    metadata = body.get("metadata") or {}
    explicit = (
        headers.get("X-Session-ID")
        or metadata.get("session_id")
        or settings.get("bridge_session_id")
    )
    # Fallback is a conversation fingerprint, not a guaranteed DSH session identity.
    # Explicit IDs are required when different sessions start with identical content.
    first = next((x for x in body.get("messages", []) if x.get("role") == "user"), {})
    session = str(explicit or "dsh:" + digest(first))
    rid = (
        headers.get("X-Request-ID")
        or metadata.get("request_id")
        or digest(body.get("messages", []))
    )
    return session, str(rid)


def trim_messages(messages, keep=None):
    keep = int(settings.get("kvmem_keep_messages", 10)) if keep is None else keep
    if keep <= 0 or len(messages) <= keep:
        return messages
    system = [x for x in messages if x.get("role") in ("system", "developer")]
    rest = [x for x in messages if x.get("role") not in ("system", "developer")]
    start = max(0, len(rest) - keep)
    # Start at a user boundary; do not split assistant/tool result groups.
    while start > 0 and rest[start].get("role") != "user":
        start -= 1
    return system + rest[start:]


def classify(text, capabilities, recent_messages=None):
    return classify_intent(text, capabilities, recent_messages=recent_messages, upstream=UPSTREAM)

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            try:
                response = http_request(
                    "GET",
                    UPSTREAM + "/v1/models",
                    headers={
                        "Authorization": self.headers.get(
                            "Authorization", "Bearer local"
                        )
                    },
                    timeout=10,
                )
                return self._send_json(response.json(), response.status_code)
            except (requests.RequestException, ValueError):
                return self._send_json({"error": "upstream unavailable"}, 502)
        self._send_json({"ok": True, "service": "pet-gateway", "version": "0.2.1", "screen_context": True, "screen_intent_model": True,
                         "short_reply_policy": True, "contact_choices": True, "command_prefixes": True,
                         "unmatched_intent": "all", "intent_catalogue": "compact"})

    def _reply(self, want_stream, model, content, usage=None):
        """直接返回一句"助手回复"（不经过模型）。"""
        created = int(time.time())
        cid = "chatcmpl-proxy-" + uuid.uuid4().hex[:16]
        if not want_stream:
            return self._send_json(
                {
                    "id": cid,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": usage
                    or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        }
        self.wfile.write(
            ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8")
        )
        done = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": usage
            or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self.wfile.write(
            ("data: " + json.dumps(done, ensure_ascii=False) + "\n\n").encode("utf-8")
        )
        self.wfile.write(b"data: [DONE]\n\n")
        try:
            self.wfile.flush()
        except Exception:
            pass

    def _forward(self, body, want_stream, screen_decision=None):
        started = time.perf_counter()
        body = dict(body)
        messages = body.get("messages") or []
        body["messages"] = trim_messages(messages)
        body = attach_game(body)
        body, screen_status = attach_screen(body, decision=screen_decision)
        body = apply_reply_policy(body)
        if screen_status not in ('skipped', 'background_task', 'provided_image'):
            log('screen context: ' + screen_status)
        selected = model_tools(
            body.get("tools"),
            last_user_text(messages),
            continuation=bool(messages and messages[-1].get("role") == "tool"),
            policy=str(settings.get("native_tools_policy", "auto")),
        )
        log(
            "chat payload: messages=%d tools=%d->%d chars=%d"
            % (
                len(body["messages"]),
                len(body.get("tools") or []),
                len(selected),
                sum(len(json.dumps(m, ensure_ascii=False)) for m in body["messages"]),
            )
        )
        if selected:
            body["tools"] = selected
        else:
            body.pop("tools", None)
            body.pop("tool_choice", None)
        choice = body.get("tool_choice")
        if isinstance(choice, dict) and choice.get("function", {}).get("name") not in {
            t.get("function", {}).get("name") for t in selected
        }:
            body.pop("tool_choice", None)
        body["stream"] = want_stream
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.headers.get("Authorization", "Bearer local"),
        }
        try:
            upstream = http_request(
                "POST",
                UPSTREAM + "/v1/chat/completions",
                json=body,
                headers=headers,
                stream=want_stream,
                timeout=(10, 600),
            )
        except requests.RequestException:
            return self._send_json({"error": "upstream unavailable"}, 502)
        with upstream:
            if not want_stream or upstream.status_code >= 400:
                try:
                    return self._send_json(upstream.json(), upstream.status_code)
                except ValueError:
                    return self._send_json({"error": "invalid upstream response"}, 502)
            self.send_response(upstream.status_code)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                # Preserve empty lines: SSE events may contain multiple data lines.
                first = True
                for line in upstream.iter_lines(chunk_size=1):
                    if first and line.startswith(b"data:"):
                        log(
                            "upstream first event: %.3fs"
                            % (time.perf_counter() - started)
                        )
                        first = False
                    self.wfile.write(line + b"\n")
                    self.wfile.flush()
            except (requests.RequestException, BrokenPipeError, ConnectionResetError):
                return

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            return self._send_json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16 * 1024 * 1024:
                return self._send_json({"error": "invalid request size"}, 400)
            body = json.loads(self.rfile.read(length))
            messages = body.get("messages") or []
            if not isinstance(messages, list):
                raise ValueError("messages must be a list")
            want_stream = bool(body.get("stream"))
            screen_decisions = []
            # A follow-up with tool results must not re-execute the previous user turn.
            if (messages and messages[-1].get("role") == "user"
                    and screen_skip_reason(body) != 'background_task'):
                text = last_user_text(messages)
                session, rid = identity(body, self.headers)
                metadata = body.get("metadata") or {}
                explicit = (
                    self.headers.get("X-Session-ID")
                    or metadata.get("session_id")
                    or settings.get("bridge_session_id")
                )
                if not explicit and not store.bind_history(
                    session,
                    digest(messages),
                    len(messages),
                    lambda length: digest(messages[:length]),
                ):
                    return self._reply(
                        want_stream,
                        body.get("model"),
                        "检测到无法区分的会话分支，未执行动作。请为会话配置不同的 X-Session-ID 或使用独立网关配置。",
                    )
                with scope(session, rid, text):
                    result = route(text, classifier=lambda value, relevant:
                                   classify(value, relevant, recent_messages=messages),
                                   decision_sink=screen_decisions.append,
                                   allow_screen=screen_skip_reason(body) is None,
                                   recent_messages=messages)
                if result is not None:
                    return self._reply(want_stream, body.get("model"), result)
            return self._forward(body, want_stream,
                                 screen_decisions[-1] if screen_decisions else None)
        except (ValueError, TypeError, KeyError):
            return self._send_json({"error": "invalid request"}, 400)
        except Exception:
            log("Gateway request failed; check local execution state before retrying.")
            return self._send_json(
                {"error": "request failed; inspect execution state"}, 500
            )


def main():
    global UPSTREAM
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--upstream", default=UPSTREAM)
    args = parser.parse_args()
    UPSTREAM = args.upstream.rstrip("/")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
