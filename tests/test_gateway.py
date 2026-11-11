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
    def test_unmatched_chat_classifies_once_then_forwards_without_bridge_tools(self):
        definitions = [{'type': 'function', 'function': {'name': 'send_qq_message'}}]
        with patch('bridge.kvmem_proxy.classify', return_value=('chat', {})) as model:
            response = requests.post(self.url, json={'metadata': {'session_id': self.id()},
                'messages': [{'role': 'user', 'content': '今天好累'}], 'tools': definitions}, timeout=3)
        self.assertEqual(response.status_code, 200)
        model.assert_called_once()
        self.assertNotIn('tools', Upstream.seen[-1])

    def test_unfamiliar_command_reaches_classifier_without_keyword_gate(self):
        before = len(Upstream.seen)
        with patch('bridge.kvmem_proxy.classify', return_value=('send_qq_message', {'to': '小z', 'text': '起床'})) as model, \
             patch('bridge.tools.send_qq_message', return_value='准备发给小z：起床，确认吗？') as send:
            response = requests.post(self.url, json={'metadata': {'session_id': self.id()},
                'messages': [{'role': 'user', 'content': '拜托把起床这两个字捎给小z吧'}]}, timeout=3)
        self.assertIn('确认', response.json()['choices'][0]['message']['content'])
        model.assert_called_once()
        send.assert_called_once_with(to='小z', text='起床')
        self.assertEqual(len(Upstream.seen), before)

    def test_failed_intent_does_not_fall_back_to_free_chat(self):
        before = len(Upstream.seen)
        with patch('bridge.kvmem_proxy.classify', return_value=None):
            response = requests.post(self.url, json={'metadata': {'session_id': self.id()},
                'messages': [{'role': 'user', 'content': '把刚才那事办一下'}]}, timeout=3)
        self.assertIn('没有执行', response.json()['choices'][0]['message']['content'])
        self.assertEqual(len(Upstream.seen), before)

    def test_background_title_request_cannot_execute_quoted_commands(self):
        with patch('bridge.kvmem_proxy.route') as route, patch('bridge.kvmem_proxy.classify') as model:
            response = requests.post(self.url, json={'messages': [
                {'role': 'system', 'content': 'Generate a title for this conversation'},
                {'role': 'user', 'content': '喊小z起床'}]}, timeout=3)
        self.assertEqual(response.status_code, 200)
        route.assert_not_called()
        model.assert_not_called()

    def test_contact_selection_and_confirmation_stay_in_the_gateway(self):
        from types import SimpleNamespace

        rows = [{'name': 'Z', 'uid': 11, 'score': 100}, {'name': 'other', 'uid': 22, 'score': 75}]
        body = {'stream': False, 'metadata': {'session_id': self.id()}, 'messages': []}
        before = len(Upstream.seen)

        def ask(text):
            body['messages'].append({'role': 'user', 'content': text})
            response = requests.post(self.url, json=body, timeout=3)
            self.assertEqual(response.status_code, 200, response.text)
            message = response.json()['choices'][0]['message']
            body['messages'].append(message)
            return message['content']

        with patch('bridge.tools.safety.resolve_contact', return_value=(None, '', rows)), \
             patch('bridge.tools.safety.vault') as vault, patch('bridge.message_service.sender') as sender:
            vault.return_value.find_by_id.return_value = SimpleNamespace(user_id=11, remark='Z', nickname='Z')
            self.assertIn('1. Z', ask('ok，你帮忙喊小z起床去'))
            self.assertIn('准备发给 Z', ask('第一个'))
            sender.return_value.send_private.assert_not_called()
            sender.return_value.send_private.return_value = {'retcode': 0}
            self.assertIn('已发送给 Z', ask('确认'))
            sender.return_value.send_private.assert_called_once()
        self.assertEqual(len(Upstream.seen), before)

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

    def test_visual_request_reaches_upstream_with_real_image_content(self):
        from test_screen_observer import frame
        with patch('bridge.kvmem_proxy.route', return_value=None), patch(
            'bridge.screen_context.fetch_snapshot', return_value={'ok': True, 'frame': frame()}
        ):
            response = requests.post(self.url, json={'stream': False,
                'messages': [{'role': 'user', 'content': '你看看我这个题目是干啥的'}]}, timeout=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Upstream.seen[-1]['messages'][-1]['content'][-1]['type'], 'image_url')

    def test_ambiguous_screen_request_classifies_once_then_attaches(self):
        from test_screen_observer import frame
        with patch('bridge.kvmem_proxy.classify', return_value=('observe_screen', {})) as classify, patch(
            'bridge.screen_context.fetch_snapshot', return_value={'ok': True, 'frame': frame()}
        ) as capture:
            response = requests.post(self.url, headers={'X-Session-ID': 'screen-intent-fixture'},
                json={'stream': False, 'messages': [{'role': 'user', 'content': '这个怎么弄'}]}, timeout=3)
        self.assertEqual(response.status_code, 200)
        classify.assert_called_once()
        capture.assert_called_once()
        self.assertEqual(Upstream.seen[-1]['messages'][-1]['content'][-1]['type'], 'image_url')


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        TEMP.cleanup()
