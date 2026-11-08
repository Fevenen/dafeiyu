"""ws_test.py — 通过后端 websocket 和桌宠对话，收集她的回复文本。

回复文本在 audio 消息的 display_text 里（OLV 不发 full-text）。
"""

import asyncio
import json
import sys
import uuid

import websockets


async def talk(text: str, wait: float = 120.0, verbose: bool = False) -> str:
    uid = "test-" + uuid.uuid4().hex[:8]
    url = "ws://127.0.0.1:12393/client-ws?client_uid=" + uid
    parts = []
    async with websockets.connect(url, max_size=None) as ws:
        try:
            await asyncio.wait_for(ws.recv(), timeout=15)
        except Exception:
            pass

        await ws.send(json.dumps({"type": "text-input", "text": text}))

        deadline = asyncio.get_event_loop().time() + wait
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            if verbose:
                print("   [msg]", t, str(msg.get("text", ""))[:40], flush=True)
            if t == "audio":
                dt = msg.get("display_text") or {}
                if isinstance(dt, dict) and dt.get("text"):
                    parts.append(dt["text"])
            elif t == "control" and msg.get("text") == "conversation-chain-end":
                break
            elif t == "backend-synth-complete":
                await asyncio.sleep(0.5)
                break
            elif t == "error":
                parts.append("[错误] " + str(msg.get("message")))
                break
    return "".join(parts)


async def main():
    text = sys.argv[1]
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    verbose = len(sys.argv) > 3 and sys.argv[3] == "-v"
    out = await talk(text, wait, verbose)
    print("你:", text)
    print("她:", out or "（没有回复）")


if __name__ == "__main__":
    asyncio.run(main())
