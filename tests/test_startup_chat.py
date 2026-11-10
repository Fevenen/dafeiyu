"""Exercise real module startup, lightweight chat policy and repeated launcher calls."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StartupTests(unittest.TestCase):
    def test_watcher_real_entrypoint_reaches_broadcast(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sessions = root / "sessions"
            sessions.mkdir()
            (sessions / "session-fixture.json").write_text(
                json.dumps(
                    {
                        "record": {
                            "rows": {
                                "turnOutline": {
                                    "val": {
                                        "turns": [
                                            {"turn": 1, "response": "**恢复测试。**"}
                                        ]
                                    }
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            data = root / "data"
            env = dict(
                os.environ,
                PET_CONFIG=str(root / "missing.json"),
                PET_DATA_DIR=str(data),
                PYTHONDONTWRITEBYTECODE="1",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.dsh_watch",
                    "--sessions",
                    str(sessions),
                    "--session",
                    "fixture",
                    "--dry",
                    "--once",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[dry]", result.stdout.decode("utf-8"))
            self.assertFalse((data / "state/dsh_watch.json").exists())

    def test_keyword_questions_do_not_classify_or_lookup_contacts(self):
        from bridge.router import route

        for question in (
            "你叫什么名字",
            "告诉我一个笑话",
            "给我讲个故事",
            "你会发消息吗",
        ):
            with (
                patch("bridge.router.safety.list_contacts") as contacts,
                patch("bridge.router.tools.send_qq_message") as send,
            ):
                classifier = unittest.mock.Mock()
                self.assertIsNone(route(question, classifier))
                classifier.assert_not_called()
                contacts.assert_not_called()
                send.assert_not_called()

    def test_chat_tools_are_lazy_but_work_requests_and_continuations_keep_them(self):
        from bridge.capabilities import model_tools

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "route_command"}},
        ]
        self.assertEqual(model_tools(tools, "今天好累"), [])
        self.assertEqual(model_tools(tools, "你叫什么名字"), [])
        self.assertEqual(model_tools(tools, "查看项目代码"), tools)
        self.assertEqual(model_tools(tools, "刚才的结果", continuation=True), tools)
        self.assertEqual(model_tools(tools, "你好", policy="all"), tools)

    def test_launcher_does_not_restart_running_components(self):
        from bridge import launcher

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "run_server.py").touch()
            client = root / "pet.exe"
            client.touch()

            def get(key, default=None, override=None):
                return {"desktop_client": str(client)}.get(key, default)

            with (
                patch.object(sys, "argv", ["launcher"]),
                patch.object(launcher.settings, "path", return_value=root),
                patch.object(launcher.settings, "get", side_effect=get),
                patch.object(
                    launcher,
                    "health",
                    return_value={"ok": True, "service": "pet-gateway"},
                ),
                patch.object(launcher, "is_running", return_value=True),
                patch.object(launcher, "desktop_running", return_value=True),
                patch.object(launcher, "spawn") as spawn,
            ):
                launcher.main()
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class BackendNamespaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_adapter_uses_actual_backend_namespace(self):
        from types import SimpleNamespace
        from bridge.presentation import enqueue

        for base in ("src.open_llm_vtuber", "open_llm_vtuber"):
            calls = []

            async def speak(*args):
                calls.append(base)

            class Manager:
                def clear(self):
                    pass

            class Engine:
                async def async_generate_audio(self, **kwargs):
                    return None

                def remove_file(self, path):
                    pass

            handler = type("Handler", (), {"__module__": base + ".websocket_handler"})()
            handler.client_connections = {"one": SimpleNamespace(send_text=None)}
            handler.client_contexts = {"one": SimpleNamespace(tts_engine=Engine())}
            handler.current_conversation_tasks = {}
            modules = {
                base + ".conversations.single_conversation": SimpleNamespace(
                    _speak_forced=speak
                ),
                base + ".conversations.tts_manager": SimpleNamespace(
                    TTSTaskManager=Manager
                ),
            }
            with patch.dict(sys.modules, modules):
                self.assertEqual(await enqueue(handler, "测试", "job"), 1)
                await handler._speech_queues["one"].queue.join()
            self.assertEqual(calls, [base])
