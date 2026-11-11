import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import zstandard
from bridge.dsh_history import HistoryReader


class HistoryTests(unittest.TestCase):
    def fixture(self, root, text, complete=True):
        summaries = root / 'summaries'
        summaries.mkdir()
        summary = summaries / 'session-fixture.json'
        summary.write_text(json.dumps({'record': {'rows': {'turnOutline': {'val': {'turns': [
            {'turn': 1, 'response': text[:118] + '…'}
        ]}}}}}), encoding='utf-8')
        history = root / 'full'
        journal = history / 'workspace/session-fixture/session.v4.jsonl.zstd'
        journal.parent.mkdir(parents=True)
        events = [
            {'type': 'turn/start', 'data': {'turn': 1}},
            {'type': 'assistant/message', 'data': {'turn': 1, 'message': {'content': [
                {'type': 'thinking', 'thinking': 'never read this aloud'}, {'type': 'text', 'text': text}
            ]}}},
        ]
        if complete:
            events.append({'type': 'turn/end', 'data': {'turn': 1, 'reason': {'kind': 'completed'}}})
        journal.write_bytes(b''.join(zstandard.ZstdCompressor().compress((json.dumps(event) + '\n').encode()) for event in events))
        return summary, history, journal

    def test_full_reply_survives_outline_limit_and_multiple_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            text = '完整内容。' * 40 + '最后一句没有标点也必须保留'
            summary, history, _ = self.fixture(Path(temporary), text)
            turns = HistoryReader(history).turns(summary)
            self.assertEqual(turns[0]['response'], text)
            self.assertTrue(turns[0]['complete'])

    def test_unfinished_reply_waits_for_completion_and_cache_refreshes(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary, history, journal = self.fixture(Path(temporary), '暂未完成', complete=False)
            reader = HistoryReader(history)
            self.assertFalse(reader.turns(summary)[0]['complete'])
            event = {'type': 'turn/end', 'data': {'turn': 1, 'reason': {'kind': 'completed'}}}
            with journal.open('ab') as stream:
                stream.write(zstandard.ZstdCompressor().compress((json.dumps(event) + '\n').encode()))
            self.assertTrue(reader.turns(summary)[0]['complete'])

    def test_real_watcher_reads_the_full_tail_once_without_outline_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = 'first sentence. ' * 20 + 'COMPLETEFINALTAIL'
            summary, history, journal = self.fixture(root, text)
            command = [sys.executable, '-m', 'bridge.dsh_watch', '--sessions', str(summary.parent),
                       '--history', str(history), '--session', 'fixture', '--dry', '--once']
            env = dict(os.environ, PET_DATA_DIR=str(root / 'data'), PET_CONFIG=str(root / 'missing.json'), PYTHONIOENCODING='utf-8')
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'COMPLETEFINALTAIL', result.stdout)
            self.assertNotIn('…'.encode(), result.stdout)
            # A legacy cursor from a different turn must not swallow the first new reply.
            state = root / 'data/state/dsh_watch.json'
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({'another-session:1': 'old preview…'}), encoding='utf-8')
            new_turn = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, timeout=10)
            self.assertIn(b'COMPLETEFINALTAIL', new_turn.stdout)
            journal.unlink()
            missing = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, timeout=10)
            self.assertNotIn(b'[dry]', missing.stdout)
            self.assertIn(b'outline previews are not spoken', missing.stdout)
