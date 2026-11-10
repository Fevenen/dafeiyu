"""acp_client.py — 用 Agent Client Protocol 跟 DSH 对话（流式）。

原理：
    起一个子进程：DeepSeek Harness.exe（以 Node 模式）+ dsh lib/bin.js --profile acp
    通过 stdin/stdout 走 JSON-RPC 2.0（ACP v1）
    session/prompt 之后，DSH 会推送 session/update（agent_message_chunk）逐段文字

用法：
    python acp_client.py "你好"               # 打印流式片段
    python acp_client.py --json "你好"        # 打印原始事件

被 dsh_watch.py 调用时，用 ACPClient 的 on_chunk 回调把文字送进 /api/say。
"""

import json
import os
import subprocess
import sys
import threading
import time

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import settings

EXE = str(settings.get("dsh_exe", ""))
BIN = str(settings.get("dsh_bin", ""))


class ACPError(Exception):
    pass


class ACPClient:
    """一个 ACP 会话的生命周期包装。"""

    def __init__(self, cwd: str, profile: str = "acp", extra_patch: str = ""):
        self.cwd = cwd
        self.profile = profile
        self.extra_patch = extra_patch
        self.proc = None
        self._next_id = 1
        self._pending = {}
        self._lock = threading.Lock()
        self.session_id = None
        self.on_chunk = None  # callable(text)
        self.on_event = None  # callable(kind, payload)
        self._reader = None
        self._stderr_lines = []

    # ---------- 进程 ----------
    def start(self, timeout: float = 20.0):
        if not EXE or not BIN:
            raise ACPError(
                "Configure DSH_EXE and DSH_BIN before using experimental ACP"
            )
        env = dict(os.environ)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        args = [EXE, BIN, "--profile", self.profile]
        if self.extra_patch:
            args += ["--patch", self.extra_patch]
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

        init = self.request(
            "initialize",
            {"protocolVersion": 1, "clientCapabilities": {}},
            timeout=timeout,
        )
        agent = (init.get("agentInfo") or {}).get("name", "?")
        proto = init.get("protocolVersion")
        return agent, proto

    def _stderr_loop(self):
        try:
            for line in self.proc.stderr:
                self._stderr_lines.append(line.rstrip())
                if len(self._stderr_lines) > 50:
                    self._stderr_lines.pop(0)
        except Exception:
            pass

    def stderr_tail(self, n: int = 5):
        return "\n".join(self._stderr_lines[-n:])

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                self._dispatch(msg)
        except Exception:
            pass

    def _dispatch(self, msg):
        if "id" in msg and msg["id"] is not None and msg.get("method") is None:
            with self._lock:
                box = self._pending.get(msg["id"])
            if box is not None and not box["done"]:
                box["result"] = msg
                box["done"] = True
                box["event"].set()
            return

        method = msg.get("method")
        if method == "session/update":
            upd = (msg.get("params") or {}).get("update") or {}
            kind = upd.get("sessionUpdate")
            if kind == "agent_message_chunk":
                text = (upd.get("content") or {}).get("text") or ""
                if self.on_chunk:
                    self.on_chunk(text)
            if self.on_event:
                self.on_event(kind, upd)
            return

        if method == "session/request_permission":
            req_id = msg.get("id")
            self._answer_permission(req_id, msg.get("params") or {})
            return

    def _answer_permission(self, req_id, params):
        """默认拒绝：桌宠场景不需要 agent 跑命令。"""
        try:
            options = params.get("options") or []
            chosen = None
            for opt in options:
                if str(opt.get("kind", "")).lower() in (
                    "reject",
                    "reject_once",
                    "deny",
                ):
                    chosen = opt.get("optionId")
                    break
            if chosen is None:
                chosen = options[0].get("optionId") if options else None
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"outcome": {"outcome": "selected", "optionId": chosen}},
            }
            self.proc.stdin.write(json.dumps(resp) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    # ---------- 请求 ----------
    def request(self, method, params, timeout: float = 30.0):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            box = {"done": False, "result": None, "event": threading.Event()}
            self._pending[rid] = box
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        if not box["event"].wait(timeout):
            raise ACPError("请求超时：%s" % method)
        msg = box["result"] or {}
        if "error" in msg:
            raise ACPError(
                "%s 出错：%s" % (method, json.dumps(msg["error"], ensure_ascii=False))
            )
        return msg.get("result") or {}

    def new_session(self):
        res = self.request(
            "session/new", {"cwd": self.cwd, "mcpServers": []}, timeout=30
        )
        self.session_id = res.get("sessionId")
        if not self.session_id:
            raise ACPError(
                "没拿到 sessionId：%s" % json.dumps(res, ensure_ascii=False)[:200]
            )
        return self.session_id

    def prompt(self, text: str, timeout: float = 120.0):
        if not self.session_id:
            self.new_session()
        return self.request(
            "session/prompt",
            {"sessionId": self.session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=timeout,
        )

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "用一句话打个招呼"
    raw = "--json" in sys.argv
    client = ACPClient(
        cwd=str(
            settings.path(
                "workspace", settings.BRIDGE_ROOT.parent.parent / "pet_workspace"
            )
        )
    )
    agent, proto = client.start()
    print("  agent:", agent, " protocol:", proto, flush=True)
    sid = client.new_session()
    print("  session:", sid, flush=True)

    chunks = []

    def on_chunk(t):
        chunks.append(t)
        if raw:
            print("   raw:", json.dumps(t, ensure_ascii=False), flush=True)
        else:
            print("   +%.2fs %r" % (time.time() - t0, t[:60]), flush=True)

    client.on_chunk = on_chunk
    t0 = time.time()
    try:
        res = client.prompt(text, timeout=90)
        print(
            "  完成 %.1fs  stopReason=%s" % (time.time() - t0, res.get("stopReason")),
            flush=True,
        )
    except Exception as e:
        print("  失败:", e, flush=True)
        print("  stderr:", client.stderr_tail(), flush=True)
    print("  全文:", "".join(chunks)[:200], flush=True)
    client.close()


if __name__ == "__main__":
    main()
