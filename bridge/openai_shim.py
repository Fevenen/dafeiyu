"""openai_shim.py — 把桌宠包装成一个"OpenAI 兼容模型"。

DSH 里添加一个自定义模型提供商：
    地址  http://127.0.0.1:18201/v1
    模型  dafeiyu
    密钥  随便填（本地不校验）

效果：
    你在 DSH 聊天框打一句话
      → 这个服务收到 → 转给桌宠（/api/chat）
      → 她思考、出声、显示
      → 回复文字原样返回给 DSH

启动：
    .venv\\Scripts\\python.exe bridge\\openai_shim.py
"""

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PET_API = "http://127.0.0.1:12393"
PORT = 18201
MODEL_ID = "dafeiyu"
LOG = os.path.join(PET, "logs", "shim.log")


def log(msg: str) -> None:
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _get(path: str, timeout: float = 20):
    with urllib.request.urlopen(PET_API + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, payload: dict, timeout: float = 30):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PET_API + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def extract_text(content) -> str:
    """OpenAI 的 content 可能是字符串，也可能是 [{type:text,text:...}] 列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def ask_pet(text: str, timeout: float = 120.0) -> str:
    before = _get("/api/transcript?limit=200").get("messages", [])
    seen = len(before)
    _post("/api/chat", {"text": text})
    log("已发给桌宠：%s" % text[:60])

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.6)
        try:
            msgs = _get("/api/transcript?limit=200").get("messages", [])
        except Exception:
            continue
        new = msgs[seen:]
        reply = [m.get("content", "") for m in new if m.get("role") == "ai"]
        if reply:
            out = "".join(reply).strip()
            log("桌宠回复：%s" % out[:60])
            return out
    return "（桌宠 %.0f 秒内没有回复，检查桌宠窗口是否开着）" % timeout


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL_ID,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "pet",
                        }
                    ],
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/v1/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"error": "bad json"})
            return

        messages = req.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = extract_text(m.get("content"))
                break
        if not user_text.strip():
            user_text = "（空消息）"

        stream = bool(req.get("stream"))
        model = req.get("model") or MODEL_ID
        reply = ask_pet(user_text)

        cid = "chatcmpl-" + str(int(time.time() * 1000))
        created = int(time.time())

        if not stream:
            self._json(
                200,
                {
                    "id": cid,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": reply},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": len(user_text),
                        "completion_tokens": len(reply),
                        "total_tokens": len(user_text) + len(reply),
                    },
                },
            )
            return

        # 流式：按小块吐出去，DSH 会逐字显示
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def chunk(delta: dict, finish=None):
            payload = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish}
                ],
            }
            self.wfile.write(
                ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
            )
            self.wfile.flush()

        try:
            chunk({"role": "assistant", "content": ""})
            step = 6
            for i in range(0, len(reply), step):
                chunk({"content": reply[i : i + step]})
                time.sleep(0.02)
            chunk({}, "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception as e:
            log("流式发送失败：%s" % e)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log("桌宠模型接口启动：http://127.0.0.1:%d/v1  模型 %s" % (PORT, MODEL_ID))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
