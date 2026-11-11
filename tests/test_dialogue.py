"""Real route/state transitions; transport is mocked and cannot send to QQ."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge import store, tools
from bridge.context import scope
from bridge.router import route
from bridge.reply_policy import apply_reply_policy


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.session = scope(self.id())
        self.session.__enter__()
        self.contact = SimpleNamespace(user_id=11, remark="Z，", nickname="Z")
        self.candidates = [{"name": "Z，", "uid": 11, "score": 100}, {"name": "other", "uid": 22, "score": 75}]

    def tearDown(self):
        self.session.__exit__(None, None, None)

    def test_choice_prepares_then_requires_separate_confirmation(self):
        from bridge.message_service import confirm

        with patch('bridge.tools.safety.resolve_contact', return_value=(None, '', self.candidates)), \
             patch('bridge.tools.safety.vault') as vault, patch('bridge.message_service.sender') as sender:
            vault.return_value.find_by_id.return_value = self.contact
            first = route('不用啦，你帮我喊小z起个床吧')
            self.assertIn('1. Z，', first)
            self.assertFalse(store.pending())
            self.assertIn('先选联系人', route('确认'))
            selected = route('第一个')
            self.assertIn('准备发给 Z，', selected)
            self.assertEqual(store.pending()['uid'], 11)
            self.assertEqual(store.pending()['text'], '起个床吧')
            sender.return_value.send_private.assert_not_called()
            sender.return_value.send_private.return_value = {'retcode': 0}
            with scope(self.id(), text='确认'):
                self.assertIn('已发送给', confirm())
            sender.return_value.send_private.assert_called_once()

    def test_cancel_and_session_isolation_of_choices(self):
        with patch('bridge.tools.safety.resolve_contact', return_value=(None, '', self.candidates)):
            tools.send_qq_message('小z', '起床')
        with scope('other-' + self.id()):
            self.assertFalse(store.get_dialogue())
            self.assertIn('没有有效', route('第一个'))
        self.assertEqual(route('算了'), '好，不发了。')
        self.assertFalse(store.get_dialogue())

    def test_pronoun_followup_reuses_only_previous_user_request(self):
        history = [
            {'role': 'user', 'content': '不用啦，你帮我喊小z起床吧'},
            {'role': 'assistant', 'content': '（点击发送）已发给别的人'},
            {'role': 'user', 'content': '上qq喊他啊'},
        ]
        with patch('bridge.router.tools.send_qq_message', return_value='准备消息，确认吗？') as send:
            self.assertIn('确认', route(history[-1]['content'], recent_messages=history))
            send.assert_called_once_with(to='小z', text='起床吧')

    def test_vague_delay_asks_then_creates_a_self_reminder(self):
        model = Mock()
        with patch('bridge.router.tools.send_qq_message') as send, patch('bridge.router.tools.set_reminder', return_value='已设置提醒你去喊') as remind:
            self.assertIn('多久后', route('你等下帮我叫下小z起床', model))
            self.assertIn('提醒', route('10分钟后', model))
            remind.assert_called_once_with('10分钟后', '通过QQ喊小z：起床')
            send.assert_not_called()
            model.assert_not_called()

    def test_unknown_command_does_not_become_fake_success(self):
        with patch('bridge.router.safety.list_contacts', return_value=[]):
            self.assertIn('意图判断暂时失败', route('帮我发消息', Mock(return_value=None)))

    def test_acknowledgement_prefixes_do_not_hide_message_requests(self):
        for phrase in ('ok，你帮忙喊小z起床去', 'OK，你帮我喊小z起床去',
                       '好呀，你能不能帮我喊小z起床去', '嗯，请你帮忙喊小z起床去'):
            with self.subTest(phrase=phrase), patch('bridge.router.tools.send_qq_message', return_value='准备消息，确认吗？') as send:
                model = Mock()
                self.assertIn('确认', route(phrase, model))
                send.assert_called_once_with(to='小z', text='起床去')
                model.assert_not_called()

    def test_acknowledgement_prefixes_do_not_turn_chat_into_commands(self):
        for phrase in ('ok，你叫什么名字', '嗯，告诉我一个笑话', '好的，你会发消息吗'):
            with self.subTest(phrase=phrase), patch('bridge.router.safety.list_contacts') as contacts:
                model = Mock(return_value=('chat', {}))
                self.assertIsNone(route(phrase, model))
                model.assert_called_once()
                contacts.assert_not_called()

    def test_policy_reaches_old_sessions_without_cutting_content_or_tools(self):
        body = {'messages': [{'role': 'system', 'content': '老的人设'}, {'role': 'user', 'content': '今天好累'}],
                'tools': [{'function': {'name': 'read_file'}}]}
        updated = apply_reply_policy(body)
        self.assertIn('最多80字', updated['messages'][1]['content'])
        self.assertIn('没有本轮结果', updated['messages'][1]['content'])
        self.assertEqual(updated['messages'][-1], body['messages'][-1])
        self.assertEqual(updated['tools'], body['tools'])
        self.assertEqual(len(body['messages']), 2)
