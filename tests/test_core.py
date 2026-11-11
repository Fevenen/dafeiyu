"""Offline regression tests; no external service or user data access."""

import asyncio
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

REPO = Path(__file__).resolve().parents[1]
if (REPO / "bridge").is_dir():
    sys.path.insert(0, str(REPO))
SCRATCH = tempfile.TemporaryDirectory(prefix="pet-tests-")
os.environ["PET_DATA_DIR"] = str(Path(SCRATCH.name) / "data")
os.environ["PET_CONFIG"] = str(Path(SCRATCH.name) / "missing.json")
from bridge import safety, store
from bridge.context import scope
from bridge.router import route
from bridge.capabilities import select_tools
from bridge._v0 import reminders
from bridge.message_service import confirm


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope(self.id())
        self.scope.__enter__()

    def tearDown(self):
        self.scope.__exit__(None, None, None)

    def test_exact_confirmation(self):
        for text in ("确认", "发吧！", "OK", "好的。"):
            self.assertTrue(safety.is_confirm(text), text)
        for text in (
            "好了吗",
            "可以吗",
            "发送失败",
            "确定不了",
            "好像不对",
            "确认？",
            "不要发送",
        ):
            self.assertFalse(safety.is_confirm(text), text)

    def test_session_isolation(self):
        store.prepare(1, "A", "one")
        with scope("another"):
            self.assertEqual(store.pending(), {})
            self.assertEqual(store.claim(), {})
            store.prepare(2, "B", "two")
        self.assertEqual(store.pending()["uid"], 1)

    def test_atomic_concurrent_confirm(self):
        store.prepare(1, "Mock", "hello")
        calls = []

        def send(*args, **kwargs):
            calls.append(kwargs["action_id"])
            time.sleep(0.04)
            return {"retcode": 0}

        def run(_):
            with scope(self.id(), text="确认"):
                return confirm()

        with patch("bridge.message_service.sender") as sender:
            sender.return_value.send_private.side_effect = send
            with concurrent.futures.ThreadPoolExecutor(8) as pool:
                list(pool.map(run, range(8)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.latest()["status"], "sent")

    def test_cross_process_claim(self):
        store.prepare(1, "Mock", "hello")
        code = "from bridge.context import scope; from bridge import store; import sys;\nwith scope(sys.argv[1]): print(bool(store.claim()))"
        import bridge

        env = dict(
            os.environ,
            PYTHONPATH=str(Path(bridge.__file__).resolve().parent.parent),
            PYTHONDONTWRITEBYTECODE="1",
        )
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", code, self.id()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for _ in range(4)
        ]
        results = [p.communicate(timeout=20) for p in procs]
        self.assertTrue(all(p.returncode == 0 for p in procs), results)
        self.assertEqual(sum(out.strip() == b"True" for out, err in results), 1)

    def test_failed_result_retained(self):
        store.prepare(1, "Mock", "hello")
        with patch("bridge.message_service.sender") as sender:
            sender.return_value.send_private.return_value = {
                "retcode": 1,
                "wording": "offline",
            }
            self.assertIn("发送失败", confirm())
        self.assertEqual(store.latest()["status"], "failed")
        self.assertEqual(store.latest()["text"], "hello")

    def test_unknown_never_retried(self):
        store.prepare(1, "Mock", "hello")
        with patch("bridge.message_service.sender") as sender:
            sender.return_value.send_private.return_value = {"retcode": -2}
            confirm()
            confirm()
            self.assertEqual(sender.return_value.send_private.call_count, 1)
        self.assertEqual(store.latest()["status"], "unknown")

    def test_dry_run_not_success(self):
        store.prepare(1, "Mock", "hello")
        with patch("bridge.message_service.sender") as sender:
            sender.return_value.send_private.return_value = {
                "retcode": 0,
                "dry_run": True,
            }
            self.assertIn("未发送真实消息", confirm())
        self.assertEqual(store.latest()["status"], "dry_run")

    def test_confirmation_cannot_be_classified(self):
        store.prepare(1, "Mock", "hello")
        with patch("bridge.message_service.sender") as sender:
            result = route("请发这个消息", classifier=lambda *a: ("confirm_send", {}))
            self.assertIn("明确回复", result)
            sender.assert_not_called()

    def test_request_retry_caches_result(self):
        with patch("bridge.tools.set_reminder", return_value="created") as call:
            with scope(self.id(), "same-request", text="10分钟后提醒我喝水"):
                self.assertEqual(route("10分钟后提醒我喝水"), "created")
                self.assertEqual(route("10分钟后提醒我喝水"), "created")
            self.assertEqual(call.call_count, 1)

    def test_unmatched_chat_is_classified_without_running_tools(self):
        with patch("bridge.tools.send_qq_message") as send:
            classify = Mock(return_value=('chat', {}))
            self.assertIsNone(route("今天好累", classify))
            send.assert_not_called()
            classify.assert_called_once()

    def test_native_tools_preserved(self):
        def tool(name):
            return {"type": "function", "function": {"name": name}}

        definitions = [
            tool("read_file"),
            tool("send_qq_message"),
            tool("set_reminder"),
            tool("confirm_send"),
        ]
        self.assertEqual(
            [
                t["function"]["name"]
                for t in select_tools(definitions, "十分钟后提醒我喝水")
            ],
            ["read_file", "set_reminder"],
        )

    def test_contacts_not_truncated(self):
        contacts = [
            type(
                "Contact", (), {"remark": "name" + str(i), "nickname": "", "user_id": i}
            )()
            for i in range(35)
        ]
        vault = type("Vault", (), {"contacts": contacts})()
        with patch("bridge.safety.vault", return_value=vault):
            self.assertEqual(len(safety.list_contacts()), 35)

    def test_reminder_channels_independent(self):
        from datetime import datetime, timedelta

        item = reminders.add("water", datetime.now() - timedelta(seconds=1))
        self.assertTrue(reminders.claim(item["id"]))
        self.assertFalse(reminders.claim(item["id"]))
        reminders.delivery(item["id"], "qq", "sent")
        reminders.delivery(item["id"], "pet", "pending")
        reminders.release(item["id"])
        self.assertEqual(reminders.pending()[0]["qq"], "sent")
        self.assertEqual(reminders.pending()[0]["fired"], 0)
        reminders.delivery(item["id"], "pet", "sent")
        reminders.release(item["id"])
        self.assertEqual(reminders.pending(), [])

    def test_reminder_concurrent_writes(self):
        from datetime import datetime

        def add(i):
            with scope(self.id()):
                reminders.add("item" + str(i), datetime.now())

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(add, range(20)))
        self.assertEqual(len(reminders.pending()), 20)

    def test_gateway_context(self):
        from bridge.kvmem_proxy import identity

        body = {"messages": [{"role": "user", "content": "hello"}]}
        self.assertEqual(
            identity(body, {"X-Session-ID": "a", "X-Request-ID": "r"}), ("a", "r")
        )
        self.assertNotEqual(
            identity(body, {"X-Session-ID": "a"}), identity(body, {"X-Session-ID": "b"})
        )

    def test_ambiguous_history_fails_closed(self):
        self.assertTrue(store.bind_history(self.id(), "first", 1, lambda n: "unused"))
        self.assertTrue(store.bind_history(self.id(), "second", 2, lambda n: "first"))
        self.assertFalse(store.bind_history(self.id(), "branch", 2, lambda n: "first"))
        self.assertFalse(store.bind_history(self.id(), "second", 2, lambda n: "first"))

    def test_tool_continuation_trim(self):
        from bridge.kvmem_proxy import trim_messages

        messages = [
            {"role": "system", "content": "persona"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_calls": [{"id": "one"}]},
            {"role": "tool", "tool_call_id": "one", "content": "done"},
            {"role": "user", "content": "next"},
        ]
        self.assertEqual(trim_messages(messages, 3), messages)

    def test_no_author_path_dependency(self):
        from bridge._v0.vault import _norm

        self.assertEqual(_norm("Ａ B"), "ab")
        self.assertFalse(
            any("v0" + os.sep + "assistant" in entry for entry in sys.path)
        )


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_id_cannot_change_text(self):
        from bridge.presentation import SpeechQueue

        async def synth(text):
            return text

        async def play(text, path):
            pass

        queue = SpeechQueue(synth, play, lambda path: None)
        await queue.enqueue("same", "第一句")
        with self.assertRaises(ValueError):
            await queue.enqueue("same", "第二句")
        await queue.queue.join()

    async def test_prefetch_while_playing(self):
        from bridge.presentation import SpeechQueue

        release = asyncio.Event()
        second_ready = asyncio.Event()
        played = []

        async def synth(text):
            if text == "第二句":
                second_ready.set()
            return text

        async def play(text, path):
            played.append(text)
            if text == "第一句":
                await release.wait()

        queue = SpeechQueue(synth, play, lambda path: None)
        await queue.enqueue("a", "第一句")
        await queue.enqueue("b", "第二句")
        await asyncio.wait_for(second_ready.wait(), 1)
        self.assertEqual(played, ["第一句"])
        release.set()
        await asyncio.wait_for(queue.queue.join(), 1)
        self.assertEqual(played, ["第一句", "第二句"])
        self.assertEqual(await queue.enqueue("b", "第二句"), "played")

    async def test_synthesis_error_does_not_stop_queue(self):
        from bridge.presentation import SpeechQueue

        played = []

        async def synth(text):
            if text == "坏":
                raise RuntimeError("bad")
            return text

        async def play(text, path):
            played.append(text)

        queue = SpeechQueue(synth, play, lambda path: None)
        await queue.enqueue("a", "坏")
        await queue.enqueue("b", "好")
        await asyncio.wait_for(queue.queue.join(), 1)
        self.assertEqual(played, ["好"])
        self.assertEqual(queue.jobs["a"]["status"], "failed")


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        SCRATCH.cleanup()
