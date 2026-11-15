"""Deliver desktop clicks once to the active Tavern page's existing controller."""

from secrets import token_hex

from .sillytavern import GameError


class DesktopControls:
    def __init__(self, game):
        self.game = game
        self.page = {}
        self.token = None
        self.command = None
        self.result = None

    def active(self):
        session = self.game.sessions.get(self.game.active)
        if session and self.game._get(session['token'], session['origin'])['mode'] != 'off':
            return session

    def expire(self):
        command = self.command
        if command and not command['claimed'] and self.game.clock() > command['expires']:
            self.result = {'id': command['id'], 'error': '酒馆页面没有接到操作，请切回酒馆检查。'}
            self.command = None

    def status(self):
        session = self.active()
        if not session or session['token'] != self.token or not self.page or not session['context']:
            return {'connected': False, 'available': False, 'waiting': bool(session),
                    'status': ('等待酒馆同步' if session else '请先打开酒馆并进入一段剧情。')}
        if self.game.clock() - self.page['updated'] > 8:
            return {'connected': False, 'available': False, 'waiting': True}
        self.expire()
        page = self.page
        context = session['context']
        draft = session['draft']
        return {'connected': True, 'available': True, 'session': page['session'], 'mode': session['mode'],
                'epoch': session['epoch'], 'revision': context.get('revision'), 'auto': page['auto'],
                'status': page['status'], 'run': page['run'], 'can_send': page['can_send'],
                'draft': {'id': draft['id'], 'text': draft['text']} if draft and not draft['claimed']
                and page['draft'] == draft['id'] else None,
                'comments': session['comments'][-8:], 'command': (self.command or {}).get('action'),
                'result': self.result}

    def enqueue(self, payload):
        state = self.status()
        action = payload.get('action')
        if action not in ('auto', 'draft', 'run', 'submit', 'pause', 'off'):
            raise GameError(400, '未知桌宠操作。')
        if not state['connected']:
            raise GameError(409, '请先在酒馆开启陪玩。')
        if payload.get('session') != state['session']:
            raise GameError(409, '酒馆连接已切换，请刷新状态。')
        urgent = action in ('pause', 'off')
        if not urgent and (payload.get('epoch') != state['epoch'] or payload.get('revision') != state['revision']):
            raise GameError(409, '剧情或控制权已变化，请重试。')
        if not urgent and self.command:
            raise GameError(409, '还有一个桌宠操作正在处理。')
        if action == 'run' and (not state['can_send'] or state['mode'] != 'companion'):
            raise GameError(409, '酒馆正在生成、有人在输入，或接管尚未结束。')
        if action == 'draft' and state['mode'] != 'companion':
            raise GameError(409, '请先结束接管，再生成草稿。')
        if action == 'auto' and type(payload.get('enabled')) is not bool:
            raise GameError(400, '自动点评开关参数无效。')
        goal, turns = payload.get('goal', ''), payload.get('turns', 1)
        if not isinstance(goal, str) or len(goal) > 1000:
            raise GameError(400, '接管目标最多1000字。')
        if action == 'run' and (type(turns) is not int or not 1 <= turns <= 5):
            raise GameError(400, '代玩请选择1到5轮。')
        if action == 'submit' and (not state['can_send'] or not state['draft'] or payload.get('draft_id') != state['draft']['id']
                                   or not isinstance(payload.get('text'), str) or not 0 < len(payload['text'].strip()) <= 2000):
            raise GameError(409, '草稿已变化，或行动文字不符合要求。')
        self.result = None
        self.command = {key: payload[key] for key in ('enabled', 'draft_id', 'text') if key in payload}
        self.command.update(action=action, id=token_hex(12), epoch=state['epoch'], revision=state['revision'],
                            goal=goal, turns=turns, expires=self.game.clock() + 5, claimed=False)
        return {'id': self.command['id']}

    def poll(self, token, origin, payload):
        session = self.game._get(token, origin)
        if self.game.active != token or session['mode'] == 'off' or not session['context']:
            return {'command': None}
        view = payload.get('view')
        if not isinstance(view, dict):
            raise GameError(400, '桌宠状态格式无效。')
        if self.game.clock() - session['touched'] >= 2:
            session['touched'] = self.game.clock()
            self.game._publish()
        run = view.get('run')
        if not (isinstance(run, dict) and type(run.get('total')) is int and type(run.get('completed')) is int
                and 0 <= run['completed'] <= run['total'] <= 5):
            run = None
        if self.token != token:
            self.token, self.command, self.result = token, None, None
            self.page = {'session': token_hex(12)}
        self.page.update(updated=self.game.clock(), auto=view.get('auto') is True,
                          status=str(view.get('status', ''))[:200], can_send=view.get('can_send') is True,
                          draft=view.get('draft'), run=run and {'total': run['total'], 'completed': run['completed'],
                                                               'automatic': run.get('automatic') is True})
        self.expire()
        command = self.command
        receipts = payload.get('receipts')
        if command and command['claimed'] and isinstance(receipts, list):
            for receipt in receipts[:10]:
                if isinstance(receipt, dict) and receipt.get('done') == command['id']:
                    self.result = {'id': command['id'], 'error': str(receipt.get('error') or '')[:200]}
                    self.command = command = None
                    break
        if not command or command['claimed']:
            return {'command': None}
        context = session['context'] or {}
        if command['action'] not in ('pause', 'off') and (session['epoch'] != command['epoch']
                or context.get('revision') != command['revision']):
            self.result = {'id': command['id'], 'error': '剧情或控制权已变化，旧操作已取消。'}
            self.command = None
            return {'command': None}
        command['claimed'] = True
        return {'command': command}

    def stopping(self, token):
        return self.token == token and self.command and self.command['action'] in ('pause', 'off')

    def disconnect(self, token):
        if self.token == token:
            self.token, self.command, self.result = None, None, None
            self.page = {}
