"""Leased, versioned SillyTavern sessions. This module cannot execute real-world tools."""

import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path

import httpx
from .. import settings
from ..persona import core_persona, default_persona
from ..game_memory import GameMemory
from .prompts import build_prompt


class GameError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


async def generate(kind, data):
    data = dict(data)
    companion = data.pop('companion_persona', '')
    prompt = build_prompt(kind, companion)
    body = {'model': settings.get('kvmem_model', 'kvmem-polystrata-qwen35'), 'stream': False,
            'temperature': .6, 'max_tokens': 650 if kind == 'comment' else 400,
            'messages': [{'role': 'system', 'content': prompt},
                         {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
    base = str(settings.get('kvmem_upstream', 'http://127.0.0.1:18200')).rstrip('/')
    async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60, connect=3)) as client:
        response = await client.post(base + '/v1/chat/completions', json=body,
                                     headers={'Authorization': 'Bearer local'})
        response.raise_for_status()
        text = response.json()['choices'][0]['message'].get('content', '').strip()
    if not text:
        raise GameError(502, '游戏模型没有返回正文，请重试。')
    return text


class TavernService:
    def __init__(self, root=None, model=generate, speak=None, busy=None, clock=time.time, persona=None):
        self.root = Path(root) if root else settings.DATA_DIR / 'games/sillytavern'
        self.model, self.speak, self.busy, self.clock = model, speak, busy, clock
        self.persona = persona or default_persona
        self.shared = GameMemory(self.root, clock)
        self.shared.close('disconnected')
        self.sessions = {}
        self.active = None
        self.model_lock = asyncio.Lock()
        if (self.root / 'active.json').exists():
            (self.root / 'active.json').unlink()  # Restart never restores observation authority.

    def connect(self, origin):
        for token, session in list(self.sessions.items()):
            if self.clock() - session['touched'] > 120:
                self._stop(session, off=True)
                del self.sessions[token]
        if len(self.sessions) >= 16:
            raise GameError(429, '酒馆连接过多，请关闭不用的页面。')
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {'token': token, 'origin': origin, 'mode': 'off', 'epoch': 0,
                                'touched': self.clock(), 'context': None, 'draft': None,
                                'jobs': set(), 'comments': [], 'memory': {}, 'covered': [],
                                'last_comment': -1e12, 'observations': 0, 'seen': '', 'memory_review': False,
                                'remaining': 0, 'deadline': 0, 'drafting': False, 'synced_at': 0}
        self.sessions[token]['voice_status'] = 'off'
        self.sessions[token]['voice_job'] = None
        return {'token': token, 'lease_seconds': 30, **self.status(token, origin)}

    def _get(self, token, origin):
        session = self.sessions.get(token)
        if not session or session['origin'] != origin:
            raise GameError(403, '酒馆连接已失效，请重新连接。')
        if session['mode'] != 'off' and self.clock() - session['touched'] > 30:
            self._stop(session, off=True)
            self.shared.close('disconnected')
        if session['mode'] == 'takeover' and self.clock() > session['deadline']:
            self._stop(session)
        return session

    def check_epoch(self, token, origin, epoch):
        if type(epoch) is not int or self._get(token, origin)['epoch'] != epoch:
            raise GameError(409, '控制权已变化，旧请求已作废。')

    def _stop(self, session, off=False):
        session['epoch'] += 1
        session['draft'] = None
        session['remaining'] = 0
        session['voice_status'] = 'off'
        session['voice_job'] = None
        for task in list(session['jobs']):
            task.cancel()
        session['mode'] = 'off' if off else 'companion'
        if off and self.active == session['token']:
            self.active = None
        self._publish()

    def _publish(self):
        path = self.root / 'active.json'
        session = self.sessions.get(self.active)
        if session and session['mode'] != 'off' and session['context']:
            public = {key: value for key, value in session['context'].items() if key != 'fingerprints'}
            atomic_json(path, {'expires': session['touched'] + 30, 'context': public,
                               'memory': session['memory']})
            self.shared.publish(session['context'], session['memory'], session['mode'],
                                session['touched'] + 30, session['synced_at'])
        elif path.exists():
            path.unlink()
            self.shared.close()
        else:
            self.shared.close()

    def set_mode(self, token, origin, mode, turns=1):
        session = self._get(token, origin)
        if mode not in ('off', 'companion', 'takeover'):
            raise GameError(400, '未知模式。')
        if type(turns) is not int or not 1 <= turns <= 5:
            raise GameError(400, '接管轮数必须在1到5之间。')
        if mode != 'off':
            other = self.sessions.get(self.active)
            if other and other is not session:
                self._get(other['token'], other['origin'])
                if other['mode'] != 'off':
                    raise GameError(409, '另一个酒馆页面正在陪玩，请先在那里关闭。')
            self.active = token
        self._stop(session, off=mode == 'off')
        session['mode'] = mode
        session['remaining'] = turns if mode == 'takeover' else 0
        session['deadline'] = self.clock() + 300 if mode == 'takeover' else 0
        session['touched'] = self.clock()
        self._publish()
        return self.status(token, origin)

    def pause(self, token, origin, clear=False):
        session = self._get(token, origin)
        self._stop(session, off=session['mode'] == 'off')
        if clear:
            session['context'], session['memory'], session['covered'] = None, {}, []
            self._publish()
        return self.status(token, origin)

    def _memory_path(self, context):
        return self.root / 'memory' / (digest(context['chat_id']) + '.json')

    def sync(self, token, origin, payload):
        session = self._get(token, origin)
        if session['mode'] == 'off':
            raise GameError(409, '陪玩已关闭，没有读取剧情。')
        chat_id = payload.get('chat_id')
        messages, fingerprints = payload.get('messages'), payload.get('fingerprints')
        if (not isinstance(chat_id, str) or not 0 < len(chat_id) <= 300
                or not isinstance(messages, list) or not 0 < len(messages) <= 40
                or not isinstance(fingerprints, list) or not 0 < len(fingerprints) <= 4000
                or any(not isinstance(x, str) or len(x) != 64 for x in fingerprints)):
            raise GameError(400, '剧情快照格式或长度不正确。')
        clean = []
        for message in messages:
            if (not isinstance(message, dict) or message.get('role') not in ('user', 'assistant')
                    or not isinstance(message.get('text'), str) or not isinstance(message.get('name'), str)):
                raise GameError(400, '剧情消息格式不正确。')
            clean.append({'role': message['role'], 'name': message['name'][:80], 'text': message['text']})
        if sum(len(message['text']) for message in clean) > 16000:
            raise GameError(400, '剧情正文过长，请缩小历史窗口。')
        persona = str(payload.get('persona', ''))[:2000]
        context = {'chat_id': chat_id, 'messages': clean, 'fingerprints': fingerprints, 'persona': persona,
                   'player_name': str(payload.get('player_name', '玩家'))[:80]}
        context['revision'] = digest(context)
        previous = session['context']
        if previous and previous['revision'] != context['revision']:
            session['draft'] = None
        if not previous or previous['chat_id'] != chat_id:
            self._stop(session)
            try:
                saved = json.loads(self._memory_path(context).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            session['memory'], session['covered'] = saved.get('memory', {}), saved.get('covered', [])
            if not isinstance(session['memory'], dict) or not isinstance(session['covered'], list):
                session['memory'], session['covered'] = {}, []
            session['seen'], session['observations'] = '', 0
            session['comments'], session['last_comment'] = [], -1e12
        if session['covered'] and session['covered'] != fingerprints[:len(session['covered'])]:
            session['memory'], session['covered'], session['memory_review'] = {}, [], True
            atomic_json(self._memory_path(context), {'memory': {}, 'covered': []})
        session['context'] = context
        session['synced_at'] = self.clock()
        session['touched'] = self.clock()
        self._publish()
        return self.status(token, origin)

    def status(self, token, origin, heartbeat=False):
        session = self._get(token, origin)
        if heartbeat and session['mode'] != 'off':
            session['touched'] = self.clock()
            self._publish()
        context = session['context'] or {}
        shared = self.shared.read() or {}
        return {'mode': session['mode'], 'epoch': session['epoch'], 'revision': context.get('revision'),
                'remaining': session['remaining'],
                'voice_status': session['voice_status'],
                'voice_job': session['voice_job'],
                'chat_id': context.get('chat_id'), 'draft': session['draft'], 'comments': session['comments'][-8:],
                'memory': session['memory'], 'memory_review': session['memory_review'],
                'synced_at': session['synced_at'], 'shared_chat': shared.get('exchanges', [])
                if shared.get('context', {}).get('chat_id') == context.get('chat_id') else []}

    def _snapshot(self, session):
        if session['mode'] == 'off' or not session['context']:
            raise GameError(409, '请先开启陪玩并同步当前剧情。')
        return session['epoch'], session['context']['revision']

    def _valid(self, session, stamp):
        return (session['mode'] != 'off' and self.clock() - session['touched'] <= 30
                and session['context'] and (session['epoch'], session['context']['revision']) == stamp)

    async def _complete(self, session, stamp, kind, extra):
        task = asyncio.current_task()
        session['jobs'].add(task)
        try:
            async with self.model_lock:
                if not self._valid(session, stamp):
                    raise GameError(409, '剧情或控制权已变化，旧请求已作废。')
                data = {'visible_scene': session['context']['messages'], 'persona': session['context']['persona'],
                        'player_name': session['context']['player_name'], 'memory': session['memory'], **extra}
                if kind in ('comment', 'question'):
                    data['companion_persona'] = core_persona(self.persona()) or default_persona()
                shared = self.shared.read() or {}
                data['recent_companion_chat'] = shared.get('exchanges', [])
                result = await self.model(kind, data)
            if not self._valid(session, stamp):
                raise GameError(409, '剧情或控制权已变化，旧结果已丢弃。')
            return result
        except asyncio.CancelledError:
            raise GameError(409, '已暂停，未提交旧结果。') from None
        except GameError:
            raise
        except Exception:
            raise GameError(502, '游戏模型请求失败，没有提交行动。') from None
        finally:
            session['jobs'].discard(task)

    async def _say(self, session, stamp, text, enabled):
        session['voice_status'] = 'off'
        session['voice_job'] = None
        if enabled and text and self.speak and self._valid(session, stamp):
            key = secrets.token_hex(12)
            status = await self.speak(text, key, lambda: self._valid(session, stamp))
            session['voice_status'] = status if isinstance(status, str) else 'queued'
            if session['voice_status'] == 'queued':
                session['voice_job'] = 'game-' + key

    async def comment(self, token, origin, voice=False, force=False):
        session = self._get(token, origin)
        stamp = self._snapshot(session)
        if not force and (session['seen'] == stamp[1] or self.clock() - session['last_comment'] < 30
                          or self.model_lock.locked() or (self.busy and self.busy())):
            return {'skipped': True}
        session['seen'], session['last_comment'] = stamp[1], self.clock()
        session['observations'] += 1
        update = not session['memory'] or session['observations'] % 3 == 0
        recent = [item['text'] for item in session['comments'] if item['kind'] == 'comment'][-3:]
        result = await self._complete(session, stamp, 'comment', {
            'update_memory': update, 'comment_mode': 'manual' if force else 'automatic',
            'recent_comments': recent,
        })
        try:
            parsed = json.loads(result.strip().removeprefix('```json').removesuffix('```').strip())
            text = str(parsed.get('comment', '')).strip()
            memory = parsed.get('memory')
            if not force and parsed.get('scene_phase') == 'setup':
                text = ''
            if len(text) > 120:
                raise ValueError('Comment too long')
            if update and isinstance(memory, dict):
                keys = ('facts', 'suspicions', 'goals', 'relations', 'open_threads')
                session['memory'] = {key: str(memory.get(key, ''))[:600] for key in keys}
                session['covered'] = list(session['context']['fingerprints'])
                session['memory_review'] = False
                atomic_json(self._memory_path(session['context']), {'memory': session['memory'], 'covered': session['covered']})
        except (ValueError, TypeError, AttributeError):
            raise GameError(502, '点评格式不正确，没有播报或提交行动。') from None
        if text:
            session['comments'].append({'id': secrets.token_hex(8), 'text': text, 'kind': 'comment'})
        self._publish()
        if text:
            self.shared.remember(self.shared.read(), '', text, 'comment')
        await self._say(session, stamp, text, voice)
        return {'text': text, **self.status(token, origin)}

    async def question(self, token, origin, text, voice=False):
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 2000:
            raise GameError(400, '问题不能为空或超过2000字。')
        session = self._get(token, origin)
        stamp = self._snapshot(session)
        result = await self._complete(session, stamp, 'question', {'question': text})
        if len(result) > 1000:
            raise GameError(502, '回答过长，请重试。')
        session['comments'].append({'id': secrets.token_hex(8), 'text': result, 'kind': 'answer'})
        self.shared.remember(self.shared.read(), text, result, 'tavern')
        await self._say(session, stamp, result, voice)
        return {'text': result, **self.status(token, origin)}

    async def draft(self, token, origin, revision, goal):
        session = self._get(token, origin)
        if session['mode'] != 'takeover' or session['remaining'] <= 0:
            raise GameError(403, '陪玩模式没有接管权限，请先选择接管。')
        stamp = self._snapshot(session)
        if revision != stamp[1] or not isinstance(goal, str) or len(goal) > 1000:
            raise GameError(409, '剧情版本已变化，请重新同步。')
        if session['draft']:
            if not session['draft']['claimed']:
                return self.status(token, origin)
            raise GameError(409, '本轮草稿已领取，不能重复提交。')
        if session['drafting']:
            raise GameError(409, '行动正在生成，请稍候。')
        session['drafting'] = True
        try:
            result = await self._complete(session, stamp, 'action', {'goal': goal})
        finally:
            session['drafting'] = False
        if not 0 < len(result.strip()) <= 2000:
            raise GameError(502, '行动内容为空或过长，没有提交。')
        session['draft'] = {'id': secrets.token_hex(16), 'revision': revision, 'text': result.strip(), 'claimed': False}
        return self.status(token, origin)

    def claim(self, token, origin, draft_id, revision):
        session = self._get(token, origin)
        draft = session['draft']
        if (session['mode'] != 'takeover' or not draft or draft['id'] != draft_id or draft['claimed']
                or revision != session['context']['revision'] or draft['revision'] != revision):
            raise GameError(409, '草稿已失效或已提交，不能重复使用。')
        draft['claimed'] = True
        session['remaining'] -= 1
        return {'ok': True, 'draft_id': draft_id}

    def clear_memory(self, token, origin):
        session = self._get(token, origin)
        self._stop(session, off=session['mode'] == 'off')
        session['memory'], session['covered'], session['memory_review'] = {}, [], False
        self.shared.clear((session['context'] or {}).get('chat_id', ''))
        if session['context']:
            atomic_json(self._memory_path(session['context']), {'memory': {}, 'covered': []})
        self._publish()
        return self.status(token, origin)
