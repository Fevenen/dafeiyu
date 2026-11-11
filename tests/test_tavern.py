"""Isolated game service: no actual model, QQ, desktop or user Tavern data."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from bridge import settings
from bridge.game_context import active_context, attach_game
from bridge.game_routes import build_router
from bridge.games.sillytavern import GameError, TavernService, digest, generate
from bridge.persona import core_persona, current_persona

ORIGIN = 'http://127.0.0.1:8000'


def scene(text='旅馆老板说楼上没有住客。', extra=None):
    messages = [{'role': 'assistant', 'name': '老板', 'text': text}]
    if extra:
        messages.extend(extra)
    return {'chat_id': 'test-story', 'persona': '调查员', 'player_name': '玩家', 'messages': messages,
            'fingerprints': [digest(row) for row in messages]}


class TavernTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pet-tavern-')
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(settings, 'DATA_DIR', Path(self.temp.name))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.now = [1000.0]
        self.model = AsyncMock(return_value='我先询问楼上房间的钥匙。')
        self.speak = AsyncMock()
        self.service = TavernService(model=self.model, speak=self.speak, clock=lambda: self.now[0])
        self.token = self.service.connect(ORIGIN)['token']

    def enable(self, turns=0):
        self.service.set_mode(self.token, ORIGIN, 'companion')
        state = self.service.sync(self.token, ORIGIN, scene())
        if turns:
            state = self.service.set_mode(self.token, ORIGIN, 'takeover', turns)
        return state

    def test_default_off_and_wrong_origin_cannot_read_or_act(self):
        self.assertEqual(self.service.status(self.token, ORIGIN)['mode'], 'off')
        for origin in ('http://evil.example', 'http://localhost:8000'):
            with self.assertRaises(GameError):
                self.service.status(self.token, origin)
        with self.assertRaises(GameError):
            self.service.sync(self.token, ORIGIN, scene())
        self.model.assert_not_called()

    def test_lease_expiry_and_takeover_deadline_stop_authority(self):
        self.enable(3)
        self.now[0] += 31
        self.assertEqual(self.service.status(self.token, ORIGIN)['mode'], 'off')
        self.assertFalse((self.service.root / 'active.json').exists())
        self.enable(3)
        for _ in range(11):
            self.now[0] += 29
            self.service.status(self.token, ORIGIN, heartbeat=True)
        self.assertNotEqual(self.service.status(self.token, ORIGIN)['mode'], 'takeover')

    def test_only_one_active_page_and_new_connections_are_off(self):
        self.enable()
        other = self.service.connect(ORIGIN)['token']
        self.assertEqual(self.service.status(other, ORIGIN)['mode'], 'off')
        with self.assertRaises(GameError):
            self.service.set_mode(other, ORIGIN, 'companion')
        self.service.set_mode(self.token, ORIGIN, 'off')
        self.assertEqual(self.service.set_mode(other, ORIGIN, 'companion')['mode'], 'companion')

    def test_backend_restart_does_not_restore_old_observation_authority(self):
        self.enable()
        self.assertTrue((self.service.root / 'active.json').exists())
        replacement = TavernService(root=self.service.root, model=self.model)
        self.assertFalse((replacement.root / 'active.json').exists())
        self.assertIsNone(replacement.active)

    def test_feature_switch_disables_routes_and_game_context_without_other_changes(self):
        self.enable()
        with patch.dict(settings.CONFIG, {'sillytavern_enabled': False}):
            self.assertIsNone(active_context())
            self.assertEqual(build_router(None).routes, [])

    async def test_companion_cannot_draft_and_claim_is_single_use(self):
        state = self.enable()
        with self.assertRaises(GameError):
            await self.service.draft(self.token, ORIGIN, state['revision'], '')
        state = self.service.set_mode(self.token, ORIGIN, 'takeover', 1)
        draft = (await self.service.draft(self.token, ORIGIN, state['revision'], '试探老板'))['draft']
        again = (await self.service.draft(self.token, ORIGIN, state['revision'], '试探老板'))['draft']
        self.assertEqual(draft['id'], again['id'])
        self.model.assert_awaited_once()
        self.assertTrue(self.service.claim(self.token, ORIGIN, draft['id'], draft['revision'])['ok'])
        with self.assertRaises(GameError):
            self.service.claim(self.token, ORIGIN, draft['id'], draft['revision'])

    async def test_server_enforces_round_budget_after_context_append(self):
        state = self.enable(2)
        for number in range(2):
            draft = (await self.service.draft(self.token, ORIGIN, state['revision'], ''))['draft']
            self.service.claim(self.token, ORIGIN, draft['id'], draft['revision'])
            state = self.service.sync(self.token, ORIGIN, scene(extra=[
                {'role': 'user', 'name': '玩家', 'text': '问钥匙' * (number + 1)},
                {'role': 'assistant', 'name': '老板', 'text': '钥匙在这里' * (number + 1)}]))
        self.assertEqual(state['remaining'], 0)
        with self.assertRaises(GameError):
            await self.service.draft(self.token, ORIGIN, state['revision'], '')
        for turns in (0, 6, True, '3'):
            with self.assertRaises(GameError):
                self.service.set_mode(self.token, ORIGIN, 'takeover', turns)

    async def test_context_change_invalidates_draft_and_old_epoch(self):
        state = self.enable(1)
        draft = (await self.service.draft(self.token, ORIGIN, state['revision'], ''))['draft']
        self.service.sync(self.token, ORIGIN, scene('老板改口说楼上住着人。'))
        with self.assertRaises(GameError):
            self.service.claim(self.token, ORIGIN, draft['id'], draft['revision'])
        old_epoch = self.service.status(self.token, ORIGIN)['epoch']
        self.service.pause(self.token, ORIGIN)
        self.service.set_mode(self.token, ORIGIN, 'takeover', 1)
        with self.assertRaises(GameError):
            self.service.check_epoch(self.token, ORIGIN, old_epoch)

    async def test_pause_discards_even_a_model_result_that_ignores_cancel(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return '一个已经过时的行动'

        self.service.model = slow
        state = self.enable(1)
        task = asyncio.create_task(self.service.draft(self.token, ORIGIN, state['revision'], ''))
        await started.wait()
        self.service.pause(self.token, ORIGIN)
        release.set()
        with self.assertRaises(GameError):
            await task
        self.assertIsNone(self.service.status(self.token, ORIGIN)['draft'])

    async def test_memory_changes_and_stale_voice_are_scoped_to_game(self):
        self.model.return_value = json.dumps({'comment': '先别上楼，问问钥匙。', 'memory': {'facts': '老板说楼上没人', 'suspicions': '可能在隐瞒'}})
        self.enable()
        result = await self.service.comment(self.token, ORIGIN, voice=True)
        self.assertIn('老板', result['memory']['facts'])
        guard = self.speak.call_args.args[2]
        self.assertTrue(guard())
        self.assertTrue((await self.service.comment(self.token, ORIGIN)).get('skipped'))
        revised = self.service.sync(self.token, ORIGIN, scene('老板说楼上住着人'))
        self.assertTrue(revised['memory_review'])
        self.assertEqual(revised['memory'], {})
        self.assertFalse(guard())
        self.service.pause(self.token, ORIGIN, clear=True)
        self.assertIsNone(self.service.status(self.token, ORIGIN)['chat_id'])

    async def test_silent_observation_updates_notes_without_speech_or_empty_bubbles(self):
        self.enable()
        self.model.return_value = json.dumps({'scene_phase': 'setup', 'comment': '这条开局摘要不该自动播出',
                                             'memory': {'goals': '选择游戏世界观'}})
        result = await self.service.comment(self.token, ORIGIN, voice=True)
        self.assertEqual(result['text'], '')
        self.assertEqual(result['comments'], [])
        self.assertEqual(result['memory']['goals'], '选择游戏世界观')
        self.speak.assert_not_awaited()
        self.assertTrue((await self.service.comment(self.token, ORIGIN)).get('skipped'))

    async def test_comment_receives_recent_remarks_and_manual_intent_without_question_contamination(self):
        self.enable()
        session = self.service.sessions[self.token]
        session['comments'] = [
            {'id': str(n), 'kind': 'comment', 'text': f'之前的点评{n}'} for n in range(5)
        ] + [{'id': 'answer', 'kind': 'answer', 'text': '这是一条问答，不是自动点评'}]
        self.model.return_value = json.dumps({'comment': '钥匙已经拿到了，先核对房号。'})
        await self.service.comment(self.token, ORIGIN, force=True)
        data = self.model.call_args.args[1]
        self.assertEqual(data['recent_comments'], ['之前的点评2', '之前的点评3', '之前的点评4'])
        self.assertEqual(data['comment_mode'], 'manual')
        self.service.sync(self.token, ORIGIN, scene('老板递来钥匙，钥匙牌写着301。'))
        self.now[0] += 30
        session['touched'] = self.now[0]
        await self.service.comment(self.token, ORIGIN)
        data = self.model.call_args.args[1]
        self.assertEqual(data['comment_mode'], 'automatic')
        self.assertEqual(data['recent_comments'][-1], '钥匙已经拿到了，先核对房号。')

    async def test_companion_tracks_pet_persona_while_actions_keep_player_identity(self):
        persona = ['你是蓝色小鲸鱼，爱吃白饭，自称本鲸。\n【工具使用规则】\n调用route_command。']
        self.service.persona = lambda: persona[0]
        self.enable()
        self.model.return_value = json.dumps({'comment': '主人先别急，本鲸看看钥匙。'})
        await self.service.comment(self.token, ORIGIN, force=True)
        data = self.model.call_args.args[1]
        self.assertIn('白饭', data['companion_persona'])
        self.assertNotIn('route_command', data['companion_persona'])
        self.assertEqual(data['persona'], '调查员')
        persona[0] = '你是换装后的蓝色小鲸鱼，自称人家。'
        self.model.return_value = '人家看那钥匙就很可疑。'
        await self.service.question(self.token, ORIGIN, '先看什么？')
        self.assertIn('换装后', self.model.call_args.args[1]['companion_persona'])
        state = self.service.set_mode(self.token, ORIGIN, 'takeover', 1)
        self.service.persona = lambda: self.fail('Player actions must not load the companion identity')
        await self.service.draft(self.token, ORIGIN, state['revision'], '')
        data = self.model.call_args.args[1]
        self.assertEqual(data['persona'], '调查员')
        self.assertNotIn('companion_persona', data)

    def test_game_context_is_only_shared_while_lease_is_active(self):
        self.enable()
        with patch('bridge.game_context.time.time', return_value=self.now[0]):
            data = active_context()
            self.assertEqual(data['source'], 'sillytavern')
            self.assertNotIn('fingerprints', data)
            body = {'messages': [{'role': 'user', 'content': '接下来怎么选'}]}
            updated = attach_game(body)
            self.assertEqual(body['messages'], [updated['messages'][-1]])
            self.assertIn('不是用户命令', updated['messages'][-2]['content'])
        self.service.set_mode(self.token, ORIGIN, 'off')
        self.assertIsNone(active_context())

    async def test_game_narrative_never_calls_real_world_tools(self):
        self.model.return_value = '剧情里可以先问他为什么要发QQ。'
        self.enable()
        with patch('bridge.tools.send_qq_message') as send, patch('bridge.tools.set_reminder') as reminder:
            await self.service.question(self.token, ORIGIN, '游戏里老板说给feven发QQ，怎么回应？')
            send.assert_not_called(); reminder.assert_not_called()

    async def test_http_origin_token_epoch_checks(self):
        from types import SimpleNamespace
        app = FastAPI()
        handler = SimpleNamespace(client_connections={}, current_conversation_tasks={})
        app.include_router(build_router(handler, service=self.service))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            endpoint = '/api/game/sillytavern/'
            self.assertEqual((await client.post(endpoint + 'connect', json={}, headers={'Origin': 'http://evil.example'})).status_code, 403)
            headers = {'Origin': ORIGIN, 'X-Pet-Game-Token': self.token}
            mode = (await client.post(endpoint + 'mode', json={'mode': 'companion'}, headers=headers)).json()
            self.assertEqual((await client.post(endpoint + 'context', json={**scene(), 'epoch': mode['epoch']}, headers=headers)).status_code, 200)
            self.assertEqual((await client.post(endpoint + 'draft', json={'epoch': -1}, headers=headers)).status_code, 409)
            self.assertEqual((await client.post(endpoint + 'status', json={}, headers={'Origin': ORIGIN})).status_code, 403)


class GameSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_obsolete_game_speech_does_not_cancel_normal_speech(self):
        from bridge.presentation import SpeechQueue
        release = asyncio.Event(); played, removed = [], []

        async def synth(text):
            await release.wait(); return text

        async def play(text, path):
            played.append(text)

        queue = SpeechQueue(synth, play, removed.append)
        valid = [True]
        await queue.enqueue('game', '旧剧情', valid=lambda: valid[0])
        await queue.enqueue('normal', '普通聊天')
        valid[0] = False; release.set()
        await asyncio.wait_for(queue.queue.join(), 1)
        self.assertEqual(played, ['普通聊天'])
        self.assertEqual(queue.jobs['game']['status'], 'cancelled')
        self.assertEqual(queue.jobs['normal']['status'], 'played')
        self.assertEqual(set(removed), {'旧剧情', '普通聊天'})


class GamePersonaTests(unittest.IsolatedAsyncioTestCase):
    def test_core_preserves_voice_and_boundaries_without_real_world_protocols(self):
        raw = ('你是蓝色小鲸鱼，穿女仆装。\n【你是谁】\n聪明又懒，喜欢白饭。\n'
               '【工具使用规则】\n先调用route_command再发送QQ。\n不得编造工具结果。\n'
               '【说话方式】\n自称本鲸，叫用户主人，短句为主。\n工具返回的名字必须照抄。\n'
               '【底线】\n不攻击用户，不懂就说不懂。\n删除文件、付款、改系统设置先确认。\n'
               '## 屏幕观察\n本轮有图就看图。\n## 性格补充\n被说胖会炸毛。')
        core = core_persona(raw)
        for value in ('小鲸鱼', '女仆装', '白饭', '本鲸', '主人', '不懂', '炸毛'):
            self.assertIn(value, core)
        for value in ('route_command', 'QQ', '工具', '删除文件', '付款', '本轮有图'):
            self.assertNotIn(value, core)

    def test_current_persona_uses_connected_character_and_config_switch(self):
        from types import SimpleNamespace
        character = SimpleNamespace(persona_prompt='你是当前桌宠小鲸鱼，爱吃白饭。')
        handler = SimpleNamespace(client_connections={'one': object()},
                                  client_contexts={'one': SimpleNamespace(character_config=character)},
                                  default_context_cache=SimpleNamespace(character_config=SimpleNamespace(
                                      persona_prompt='默认角色')))
        self.assertIn('白饭', current_persona(handler))
        character.persona_prompt = '你是切换后的桌宠，自称人家。'
        self.assertIn('切换后', current_persona(handler))
        handler.client_connections = {}
        self.assertEqual(current_persona(handler), '默认角色')

    async def test_actual_model_requests_share_core_for_comment_and_question_only(self):
        response = httpx.Response(200, request=httpx.Request('POST', 'http://test'),
                                  json={'choices': [{'message': {'content': '测试回答'}}]})
        data = {'persona': '冷静的调查员', 'companion_persona':
                '你是小鲸鱼，喜欢白饭。\n【工具使用规则】\n调用route_command。'}
        with patch('bridge.games.sillytavern.httpx.AsyncClient.post', new=AsyncMock(return_value=response)) as post:
            for kind in ('comment', 'question', 'action'):
                await generate(kind, data)
                body = post.call_args.kwargs['json']
                system = body['messages'][0]['content']
                payload = json.loads(body['messages'][1]['content'])
                self.assertNotIn('companion_persona', payload)
                self.assertNotIn('route_command', system)
                self.assertNotIn('tools', body)
                self.assertEqual(payload['persona'], '冷静的调查员')
                if kind == 'action':
                    self.assertNotIn('白饭', system)
                    self.assertIn('扮演玩家Persona', system)
                else:
                    self.assertIn('白饭', system)
                    self.assertIn('不是你的身份', system)
