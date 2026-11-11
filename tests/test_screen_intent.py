from unittest.mock import Mock, patch
import unittest

from bridge.router import route
from bridge.screen_context import attach_screen, screen_candidate, screen_skip_reason


class ScreenIntentTests(unittest.TestCase):
    def decide(self, text, result):
        classifier = Mock(return_value=result)
        decisions = []
        with patch('bridge.router.tools.send_qq_message') as send:
            self.assertIsNone(route(text, classifier, decision_sink=decisions.append))
            send.assert_not_called()
        return classifier, decisions[-1]

    def test_explicit_screen_request_uses_rule_without_model(self):
        model, decision = self.decide('看看屏幕上的题目', None)
        model.assert_not_called()
        self.assertTrue(decision)

    def test_ambiguous_screen_request_uses_the_unified_catalogue(self):
        for question in ('这个怎么弄', '第二问呢', '那这个呢', '该选哪个'):
            model, decision = self.decide(question, ('observe_screen', {}))
            model.assert_called_once()
            self.assertEqual([cap.name for cap in model.call_args.args[1]], ['qq', 'reminders', 'screen'])
            self.assertTrue(decision)

    def test_chat_and_feature_discussion_are_classified_as_chat(self):
        for text in ('今天好累', '你好', '给我讲个故事', '告诉我一个笑话', '现在屏幕识别的逻辑是什么'):
            model, decision = self.decide(text, ('chat', {}))
            model.assert_called_once()
            self.assertFalse(decision)

    def test_invalid_or_confirmation_intents_never_enable_screen_or_send(self):
        for proposed in (None, ('confirm_send', {}), ('observe_screen', {'enable': 'true'})):
            decisions = []
            with patch('bridge.router.tools.send_qq_message') as send:
                result = route('这个怎么弄', Mock(return_value=proposed), decision_sink=decisions.append)
            self.assertIsInstance(result, str)
            self.assertFalse(decisions[-1])
            send.assert_not_called()

    def test_disabled_screen_scope_still_classifies_other_capabilities(self):
        model = Mock(return_value=('chat', {}))
        decisions = []
        route('第二问呢', model, decision_sink=decisions.append, allow_screen=False)
        model.assert_called_once()
        self.assertEqual([cap.name for cap in model.call_args.args[1]], ['qq', 'reminders'])
        self.assertFalse(decisions[-1])

    def test_positive_intent_reaches_permission_gate_without_enabling_it(self):
        fetch = Mock(return_value={'ok': False, 'status': 'disabled'})
        body, status = attach_screen({'messages': [{'role': 'user', 'content': '这个怎么弄'}]},
                                     fetch=fetch, decision=True)
        fetch.assert_called_once()
        self.assertEqual(status, 'disabled')
        self.assertNotIn('image_url', str(body))
        self.assertIn('屏幕开关当前关闭', str(body))

    def test_negative_model_decision_does_not_fetch(self):
        fetch = Mock()
        attach_screen({'messages': [{'role': 'user', 'content': '看看屏幕'}]}, fetch=fetch, decision=False)
        fetch.assert_not_called()

    def test_background_and_existing_image_disable_intent_scope(self):
        self.assertEqual(screen_skip_reason({'messages': [{'role': 'system', 'content': 'Generate a title'},
            {'role': 'user', 'content': '第二问呢'}]}), 'background_task')
        self.assertEqual(screen_skip_reason({'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'provided'}}]}]}), 'provided_image')
        self.assertTrue(screen_candidate('这个怎么弄'))
