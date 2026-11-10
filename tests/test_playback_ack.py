"""Exercise the actual runtime finalizer with a frontend that acknowledges instantly."""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import unittest


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_command_targets_one_client(self):
        import sys
        from unittest.mock import patch

        source = (
            Path(__file__).resolve().parents[1]
            / "runtime/open_llm_vtuber/websocket_handler.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "WebSocketHandler"
        )
        node = next(
            n
            for n in cls.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "proactive_speak"
        )
        called = []

        async def trigger(**kwargs):
            called.append(kwargs["client_uid"])

        module = SimpleNamespace(handle_conversation_trigger=trigger)
        context = {"a": object(), "b": object()}
        handler = SimpleNamespace(
            client_connections={"a": object(), "b": object()},
            client_contexts=context,
            current_conversation_tasks={},
            chat_group_manager=object(),
            received_data_buffers={},
            broadcast_to_group=None,
        )
        scope = {"__package__": "open_llm_vtuber", "__name__": "open_llm_vtuber.websocket_handler"}
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
            scope,
        )
        with patch.dict(
            sys.modules, {"open_llm_vtuber.conversations.conversation_handler": module}
        ):
            self.assertEqual(await scope["proactive_speak"](handler, "hello"), 1)
            self.assertEqual(await scope["proactive_speak"](handler, "hello", "b"), 1)
        self.assertEqual(called, ["a", "b"])

    async def test_waiter_is_registered_before_frontend_notification(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "runtime/open_llm_vtuber/conversations/conversation_utils.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "finalize_conversation_turn"
        )
        events = []
        ack = asyncio.Event()

        async def wait(*args, **kwargs):
            events.append("waiter")
            await ack.wait()
            return {"type": "frontend-playback-complete"}

        async def send(data):
            if json.loads(data)["type"] == "backend-synth-complete":
                events.append("notify")
                ack.set()

        async def end(*args):
            pass

        async def join():
            events.append("payloads_sent")

        scope = {
            "asyncio": asyncio,
            "json": json,
            "TTSTaskManager": object,
            "WebSocketSend": object,
            "Optional": Optional,
            "BroadcastContext": object,
            "message_handler": SimpleNamespace(wait_for_response=wait),
            "send_conversation_end_signal": end,
        }
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
            scope,
        )
        manager = SimpleNamespace(
            task_list=[asyncio.create_task(asyncio.sleep(0))],
            _payload_queue=SimpleNamespace(join=join),
        )
        await asyncio.wait_for(
            scope["finalize_conversation_turn"](manager, send, "fake-client"), 1
        )
        self.assertEqual(events, ["payloads_sent", "waiter", "notify"])


if __name__ == "__main__":
    unittest.main()
