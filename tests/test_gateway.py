"""Loopback integration tests of SSE framing, errors and tool continuation."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import requests

os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="pet-http-")
os.environ.setdefault("PET_DATA_DIR", TEMP.name)
os.environ.setdefault("PET_CONFIG", str(Path(TEMP.name) / "config.json"))
from bridge import kvmem_proxy as gateway


class Upstream(BaseHTTPRequestHandler):
    seen = []
    release = threading.Event()

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        if body.get("model") == "error":
            data = b'{"error":"busy"}'
            self.send_response(429)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"first":true}\n\n')
            self.wfile.flush()
            self.release.wait(5)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            data = b'{"choices":[{"message":{"role":"assistant","content":"ok"}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        cls.original = gateway.UPSTREAM
        gateway.UPSTREAM = "http://127.0.0.1:" + str(cls.up.server_port)
        for server in (cls.up, cls.server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.url = (
            "http://127.0.0.1:" + str(cls.server.server_port) + "/v1/chat/completions"
        )

    @classmethod
    def tearDownClass(cls):
        Upstream.release.set()
        for server in (cls.up, cls.server):
            server.shutdown()
            server.server_close()
        gateway.UPSTREAM = cls.original

    def test_stream_delivers_before_completion(self):
        Upstream.release.clear()
        try:
            with patch("bridge.kvmem_proxy.route", return_value=None):
                with requests.post(
                    self.url,
                    json={
                        "stream": True,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                    stream=True,
                    timeout=3,
                ) as response:
                    lines = response.iter_lines(chunk_size=1)
                    self.assertEqual(
                        response.status_code,
                        200,
                        response.text if response.status_code != 200 else "",
                    )
                    self.assertEqual(next(lines), b'data: {"first":true}')
                    self.assertEqual(next(lines), b"")
                    self.assertFalse(Upstream.release.is_set())
                    Upstream.release.set()
                    self.assertEqual(list(lines), [b"data: [DONE]", b""])
        finally:
            Upstream.release.set()

    def test_native_tool_and_tool_results_survive(self):
        body = {
            "stream": False,
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
            "messages": [
                {"role": "user", "content": "read it"},
                {"role": "assistant", "tool_calls": [{"id": "a"}]},
                {"role": "tool", "tool_call_id": "a", "content": "file"},
            ],
        }
        with patch("bridge.kvmem_proxy.route") as route:
            response = requests.post(self.url, json=body, timeout=3)
            self.assertEqual(response.status_code, 200)
            route.assert_not_called()
        self.assertEqual(Upstream.seen[-1]["tools"], body["tools"])

    def test_upstream_error_status_preserved(self):
        with patch("bridge.kvmem_proxy.route", return_value=None):
            response = requests.post(
                self.url,
                json={
                    "model": "error",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=3,
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"error": "busy"})


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        TEMP.cleanup()
