"""Shared game context across companion, desktop voice and DSH; no live services."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from bridge import settings
from bridge.game_context import active_context, attach_game, conversation_context, game_turn, remember_reply
from bridge.games.sillytavern import GameError, TavernService, digest
from bridge.intent import classify

ORIGIN = 'http://127.0.0.1:8000'


def scene(text='终端提示：清除追踪需要删除一段记忆。K催你确认。', chat='shared-test'):
    messages = [{'role': 'assistant', 'name': '主持人', 'text': text}]
    return {'chat_id': chat, 'messages': messages, 'fingerprints': [digest(messages[0])],
            'persona': '调查员', 'player_name': '玩家'}


class SharedGameTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pet-shared-game-')
        self.addCleanup(temporary.cleanup)
        self.now = [time.time()]
        clock = patch('bridge.game_context.time.time', side_effect=lambda: self.now[0])
        clock.start(); self.addCleanup(clock.stop)
        data = patch.object(settings, 'DATA_DIR', Path(temporary.name))
        data.start(); self.addCleanup(data.stop)
        self.model = AsyncMock(return_value='先问清楚删哪段记忆。')
        self.service = TavernService(model=self.model, clock=lambda: self.now[0])
        self.token = self.service.connect(ORIGIN)['token']
        self.service.set_mode(self.token, ORIGIN, 'companion')
        self.service.sync(self.token, ORIGIN, scene())

    async def test_tavern_desktop_and_dsh_share_recent_exchanges_bidirectionally(self):
        await self.service.question(self.token, ORIGIN, '现在先不要确认，先问代价。')
        body = {'messages': [{'role': 'user', 'content': '我后面该怎么做？'}]}
        with game_turn('desktop'):
            updated = attach_game(body)
            note = updated['messages'][-2]['content']
            self.assertIn('删除一段记忆', note)
            self.assertIn('现在先不要确认', note)
            remember_reply('我后面该怎么做？', '主人先问删哪段，本鲸不想你吃亏。')
        with game_turn('dsh'):
            note = attach_game(body)['messages'][-2]['content']
            self.assertIn('主人先问删哪段', note)
            remember_reply('我们先别冒险。', '那就先问清楚。')
        await self.service.question(self.token, ORIGIN, '你刚才建议什么？')
        recent = self.model.call_args.args[1]['recent_companion_chat']
        self.assertEqual([row['source'] for row in recent], ['tavern', 'desktop', 'dsh'])
        self.assertIn('我们先别冒险', recent[-1]['user'])
        self.assertTrue(self.service.status(self.token, ORIGIN)['shared_chat'])

    def test_expiry_stops_actions_but_keeps_explicitly_historical_context(self):
        self.now[0] += 31
        self.assertEqual(self.service.status(self.token, ORIGIN)['mode'], 'off')
        self.assertIsNone(active_context())
        context = conversation_context()
        self.assertFalse(context['connected'])
        self.assertEqual(context['status'], 'disconnected')
        self.assertIn('删除', context['messages'][0]['text'])
        with self.assertRaises(GameError):
            self.service.sync(self.token, ORIGIN, scene('未获授权的新剧情'))
        self.now[0] += 1800
        self.assertIsNone(conversation_context())

    def test_shutdown_and_restart_keep_memory_without_restoring_authority(self):
        self.service.set_mode(self.token, ORIGIN, 'off')
        self.assertFalse(conversation_context()['connected'])
        replacement = TavernService(root=self.service.root)
        self.assertIsNone(replacement.active)
        self.assertIsNone(active_context())
        self.assertEqual(conversation_context()['status'], 'disconnected')

    def test_intent_and_answer_use_one_snapshot_and_late_history_cannot_return(self):
        reply = type('Reply', (), {'raise_for_status': lambda _: None, 'json': lambda _: {
            'choices': [{'message': {'content': '{"action":"chat","args":{}}'}}]}})()
        with game_turn('desktop'):
            original = conversation_context()
            self.service.sync(self.token, ORIGIN, scene('新剧情：玩家已经走出终端室。'))
            with patch('bridge.intent.http_request', return_value=reply) as request:
                self.assertEqual(classify('我后面该怎么做？', []), ('chat', {}))
                payload = json.loads(request.call_args.kwargs['json']['messages'][-1]['content'])
                self.assertEqual(payload['current_game']['revision'], original['revision'])
            self.assertIn('删除一段记忆', attach_game({'messages': [{'role': 'user', 'content': '接着说'}]})['messages'][-2]['content'])
            remember_reply('接着说', '这是旧版本的回答，不应混回新剧情。')
        self.assertNotIn('旧版本', json.dumps(conversation_context(), ensure_ascii=False))
        self.assertIn('走出终端室', str(conversation_context()))

    def test_switch_and_clear_remove_shared_exchanges_and_invalidate_late_writes(self):
        with game_turn('desktop'):
            attach_game({'messages': [{'role': 'user', 'content': '记住刚才建议'}]})
            remember_reply('记住', '先问清楚记忆代价。')
        self.assertTrue(conversation_context()['recent_companion_chat'])
        stale = self.service.shared.read()
        self.service.clear_memory(self.token, ORIGIN)
        self.service.shared.remember(stale, '旧问题', '旧回答', 'desktop')
        self.assertEqual(conversation_context()['recent_companion_chat'], [])
        self.service.sync(self.token, ORIGIN, scene('另一桌的森林探险。', 'another-chat'))
        self.assertNotIn('记忆代价', str(conversation_context()))

    def test_background_tool_turns_and_disabled_feature_do_not_share_or_record(self):
        for body in ({'messages': [{'role': 'tool', 'content': 'result'}]},
                     {'messages': [{'role': 'system', 'content': 'Generate a title'},
                                   {'role': 'user', 'content': '后面怎么做'}]}):
            with game_turn('desktop'):
                self.assertIs(attach_game(body), body)
                remember_reply('题目', '内部标题不应分享')
        self.assertEqual(conversation_context()['recent_companion_chat'], [])
        with patch.dict(settings.CONFIG, {'sillytavern_enabled': False}):
            with game_turn('desktop'):
                body = {'messages': [{'role': 'user', 'content': '你好'}]}
                self.assertIs(attach_game(body), body)

    def test_multi_entry_writes_are_bounded_and_context_injection_is_idempotent(self):
        snapshot = conversation_context()
        def write(index):
            self.service.shared.remember(snapshot, str(index), '回答' * 900, 'desktop', event_id=str(index))
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(write, range(20)))
        self.assertLessEqual(len(conversation_context()['recent_companion_chat']), 12)
        self.assertLessEqual(sum(len(row['user']) + len(row['assistant'])
                                 for row in conversation_context()['recent_companion_chat']), 4000)
        with self.service.shared.database() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM exchanges').fetchone()[0], 12)
        self.assertTrue(all(len(row['assistant']) <= 1200 for row in conversation_context()['recent_companion_chat']))
        body = {'messages': [{'role': 'user', 'content': '我后面该怎么做？'}]}
        with game_turn('desktop'):
            twice = attach_game(attach_game(body))
        self.assertEqual(len(twice['messages']), 2)
        self.assertEqual(twice['messages'][-1], body['messages'][-1])

    def test_heartbeat_can_keep_an_unchanged_scene_available_beyond_history_window(self):
        context = self.service.sessions[self.token]['context']
        self.service.shared.publish(context, {}, 'companion', self.now[0] + 4000, self.now[0])
        self.now[0] += 2000
        self.assertTrue(conversation_context()['connected'])

    def test_an_old_tab_cannot_clear_the_new_active_chats_exchanges(self):
        self.service.set_mode(self.token, ORIGIN, 'off')
        current = self.service.connect(ORIGIN)['token']
        self.service.set_mode(current, ORIGIN, 'companion')
        self.service.sync(current, ORIGIN, scene('新聊天的公开剧情。', 'current-chat'))
        snapshot = conversation_context()
        self.service.shared.remember(snapshot, '新聊天的问题', '新聊天的回答', 'desktop')
        self.service.clear_memory(self.token, ORIGIN)
        self.assertEqual(conversation_context()['recent_companion_chat'][-1]['assistant'], '新聊天的回答')
