"""Regressions for prefetched audio ownership and loopback LLM connections."""

import ast
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


RUNTIME = Path(__file__).resolve().parents[1] / "runtime/open_llm_vtuber"


class VoiceFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefetched_audio_keeps_its_own_contents(self):
        source = RUNTIME / "tts/tts_interface.py"
        scope = {}
        with patch.dict(sys.modules, {"loguru": SimpleNamespace(logger=None)}):
            exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), scope)

        class Engine(scope["TTSInterface"]):
            def generate_audio(self, text, file_name_no_ext=None):
                path = self.generate_cache_file_name(file_name_no_ext, "mp3")
                Path(path).write_text(text, encoding="utf-8")
                return path

        original = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                engine = Engine()
                texts = ["first prefetched sentence", "second prefetched sentence"]
                files = await asyncio.gather(
                    *(engine.async_generate_audio(text) for text in texts)
                )
                self.assertEqual(len(set(files)), 2)
                self.assertEqual(
                    [Path(path).read_text(encoding="utf-8") for path in files], texts
                )
                self.assertEqual(
                    engine.generate_cache_file_name("explicit-name", "wav"),
                    os.path.join("cache", "explicit-name.wav"),
                )
                os.chdir(original)
        finally:
            os.chdir(original)


class LoopbackClientTests(unittest.TestCase):
    def initialize(self, endpoint):
        source = RUNTIME / "agent/stateless_llm/openai_compatible_llm.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        initializer = next(
            node for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        captured = {}

        def create_client(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace()

        scope = {
            "urlsplit": urlsplit,
            "DefaultAsyncHttpxClient": lambda **kwargs: SimpleNamespace(**kwargs),
            "AsyncOpenAI": create_client,
            "logger": SimpleNamespace(info=lambda *args: None),
        }
        exec(
            compile(ast.Module(body=[initializer], type_ignores=[]), str(source), "exec"),
            scope,
        )
        scope["__init__"](SimpleNamespace(), "local-model", endpoint)
        return captured

    def test_loopback_bypasses_system_proxy(self):
        for host in ("127.0.0.1", "localhost", "[::1]"):
            with self.subTest(host=host):
                client = self.initialize("http://" + host + ":18200/v1")
                self.assertFalse(client["http_client"].trust_env)

    def test_remote_endpoint_retains_sdk_network_defaults(self):
        client = self.initialize("https://models.example.com/v1")
        self.assertNotIn("http_client", client)


if __name__ == "__main__":
    unittest.main()
