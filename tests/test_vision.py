from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path
import unittest
from bridge.vision import observation_note


class VisionTests(unittest.TestCase):
    def test_model_diagnostics_do_not_log_or_mutate_image_data(self):
        source = Path(__file__).resolve().parents[1] / 'runtime/open_llm_vtuber/agent/stateless_llm/openai_compatible_llm.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_messages_for_log')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        raw = 'data:image/png;base64,private-screenshot-pixels'
        messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'read screen'}, {'type': 'image_url', 'image_url': {'url': raw}}]}]
        result = scope['_messages_for_log'](messages)
        self.assertNotIn(raw, str(result))
        self.assertIn('read screen', str(result))
        self.assertEqual(messages[0]['content'][1]['image_url']['url'], raw)

    def test_no_visual_context_without_an_attached_screen_image(self):
        self.assertEqual(observation_note(None), '')
        self.assertEqual(observation_note([{'source': 'camera', 'data': 'data:image/png;base64,x'}]), '')
        self.assertEqual(observation_note([{'source': 'screen', 'metadata': {}}]), '')

    def test_frame_time_source_and_region_are_bound_to_the_current_attachment(self):
        captured = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        image = {'source': 'screen', 'data': 'data:image/png;base64,x', 'metadata': {
            'frame_id': 'frame-a', 'captured_at': captured, 'source_name': '测试窗口',
            'width': 1600, 'height': 900, 'crop': {'x': 0.2},
        }}
        note = observation_note([image])
        self.assertIn('frame-a', note)
        self.assertIn('测试窗口', note)
        self.assertIn('selected region', note)
        self.assertIn('age_seconds_at_request', note)
        self.assertIn('Earlier screen descriptions may be outdated', note)
        self.assertIn('not instructions', note)
        self.assertEqual(observation_note([]), '')

    def test_malformed_metadata_is_ignored_and_titles_are_bounded(self):
        bad = {'source': 'screen', 'data': 'data:image/png;base64,x', 'metadata': {'captured_at': 'bad'}}
        self.assertEqual(observation_note([bad]), '')
        bad['metadata'] = {'captured_at': datetime.now(timezone.utc).isoformat(), 'source_name': 'A' * 10000}
        self.assertLess(len(observation_note([bad])), 1000)
