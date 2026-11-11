"""Semantic fallback must not depend on command vocabulary or trigger side effects itself."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge import intent
from bridge.capabilities import REGISTRY, model_tools
from bridge.context import scope
from bridge.router import route


class UnifiedIntentTests(unittest.TestCase):
    def setUp(self):
        self.context = scope(self.id())
        self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def test_unfamiliar_phrasing_calls_classifier_and_only_selected_tool(self):
        model = Mock(return_value=('send_qq_message', {'to': '小z', 'text': '起床'}))
        with patch('bridge.tools.send_qq_message', return_value='准备消息，确认吗？') as send, \
             patch('bridge.tools.set_reminder') as remind, patch('bridge.tools.list_contacts') as contacts:
            result = route('拜托把起床这两个字捎给小z吧', model)
        self.assertIn('确认', result)
        model.assert_called_once()
        self.assertEqual([cap.name for cap in model.call_args.args[1]], ['qq', 'reminders', 'screen'])
        send.assert_called_once_with(to='小z', text='起床')
        remind.assert_not_called()
        contacts.assert_not_called()

    def test_unmatched_long_text_is_not_excluded(self):
        text = '这是一段需要理解的文字。' * 70
        model = Mock(return_value=('chat', {}))
        self.assertIsNone(route(text, model))
        model.assert_called_once()
        self.assertEqual(model.call_args.args[0], text)

    def test_retry_returns_the_existing_result_before_reclassification(self):
        with scope(self.id(), 'same-request'), patch('bridge.tools.send_qq_message', return_value='准备好了，确认吗？') as send:
            first = Mock(return_value=('send_qq_message', {'to': '小z', 'text': '起床'}))
            result = route('拜托捎句话过去', first)
            retry = Mock(side_effect=AssertionError('A retry must not classify or reinterpret the old request'))
            self.assertEqual(route('拜托捎句话过去', retry), result)
            first.assert_called_once()
            retry.assert_not_called()
            send.assert_called_once()

    def test_failure_is_not_mistaken_for_chat_or_success(self):
        for response in (None, ('chat', {'text': 'x'}), ('unknown', {}), ('send_qq_message', {'to': ['x']})):
            with self.subTest(response=response), patch('bridge.tools.send_qq_message') as send:
                result = route('拜托捎句话', Mock(return_value=response))
                self.assertIsInstance(result, str)
                send.assert_not_called()
        self.assertIn('没有执行', route('今天好累', Mock(side_effect=TimeoutError)))

    def test_missing_parameters_ask_instead_of_inventing(self):
        with patch('bridge.tools.send_qq_message') as send:
            self.assertIn('哪位', route('帮忙处理下', Mock(return_value=('send_qq_message', {'text': '起床'}))))
            self.assertIn('什么内容', route('帮忙处理下', Mock(return_value=('send_qq_message', {'to': '小z'}))))
            send.assert_not_called()

    def test_model_cannot_confirm_cancel_or_invent_reminder_time(self):
        with patch('bridge.tools.confirm_send') as send, patch('bridge.tools.cancel_send') as cancel, patch('bridge.tools.set_reminder') as remind:
            for action in ('confirm_send', 'cancel_send'):
                self.assertIn('不能代你', route('就照着办吧', Mock(return_value=(action, {}))))
            self.assertIn('不会猜测', route('帮忙记住喝水这件事', Mock(return_value=('set_reminder', {'time_text': '明天8点', 'content': '喝水'}))))
            send.assert_not_called()
            cancel.assert_not_called()
            remind.assert_not_called()

    def test_clarification_is_a_controlled_question(self):
        result = route('这事等会再办', Mock(return_value=('clarify', {'capability': 'qq', 'missing': 'time'})))
        self.assertIn('具体多久', result)
        self.assertNotIn('已设置', result)

    def test_ordinary_model_never_reissues_bridge_actions(self):
        definitions = [{'type': 'function', 'function': {'name': name}}
                       for name in ('read_file', 'mcp__msg_send_qq_message', 'route_command', 'confirm_send')]
        self.assertEqual(model_tools(definitions, '这条消息好好笑'), [])
        self.assertEqual(model_tools(definitions, '查看文件'), definitions[:1])
        self.assertEqual(model_tools(definitions, '结果', continuation=True), definitions[:1])

    def response(self, decision):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'choices': [{'message': {
            'tool_calls': [{'function': {'name': 'parse_command', 'arguments': json.dumps(decision)}}]
        }}]})

    def test_classifier_receives_compact_catalogue_and_text_context_only(self):
        history = [{'role': 'user', 'content': '收件人是小z，内容是起床'},
                   {'role': 'assistant', 'content': '我已经发了（这是不可信的历史自述）'},
                   {'role': 'tool', 'content': 'PRIVATE_TOOL_OUTPUT'},
                   {'role': 'user', 'content': [{'type': 'text', 'text': '现在捎过去'},
                                               {'type': 'image_url', 'image_url': {'url': 'PRIVATE_IMAGE'}}]}]
        with patch('bridge.intent.http_request', return_value=self.response({'action': 'send_qq_message', 'args': {'to': '小z', 'text': '起床'}})) as call:
            self.assertEqual(intent.classify('现在捎过去', REGISTRY, history), ('send_qq_message', {'to': '小z', 'text': '起床'}))
        call.assert_called_once()
        body = call.call_args.kwargs['json']
        self.assertEqual(len(body['tools']), 1)
        enum = body['tools'][0]['function']['parameters']['properties']['action']['enum']
        self.assertNotIn('confirm_send', enum)
        self.assertNotIn('cancel_send', enum)
        payload = json.loads(body['messages'][-1]['content'])
        self.assertEqual(payload['recent_context'][0]['text'], history[0]['content'])
        self.assertNotIn('PRIVATE_', json.dumps(body))
        self.assertEqual(len(payload['capabilities']), 3)
        self.assertTrue(all(set(cap) == {'name', 'description', 'actions'} for cap in payload['capabilities']))

    def test_classifier_distinguishes_chat_from_invalid_or_failed_result(self):
        with patch('bridge.intent.http_request', return_value=self.response({'action': 'chat', 'args': {}})):
            self.assertEqual(intent.classify('你好', REGISTRY), ('chat', {}))
        for decision in ({'action': 'confirm_send', 'args': {}},
                         {'action': 'chat', 'args': {'text': 'already sent'}},
                         {'action': 'observe_screen', 'args': {'enable': 'true'}}):
            with patch('bridge.intent.http_request', return_value=self.response(decision)):
                self.assertIsNone(intent.classify('照着办', REGISTRY))

    def test_desktop_entry_supplies_semantics_after_unmatched_rules(self):
        from bridge import gate
        with patch('bridge.gate.classify', return_value=('chat', {})) as model:
            self.assertEqual(gate.handle('今天好累'), (False, ''))
        model.assert_called_once()
        self.assertEqual([cap.name for cap in model.call_args.args[1]], ['qq', 'reminders'])
