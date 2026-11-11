"""Additive game-only routes; existing chat, QQ, reminder and screen routes are unchanged."""

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from . import settings
from .games.sillytavern import GameError, TavernService
from .game_context import enabled
from .persona import current_persona


def build_router(handler, service=None, origins=None):
    router = APIRouter(prefix='/api/game/sillytavern')
    if not enabled():
        return router
    configured = settings.get('game_origins', ['http://127.0.0.1:8000', 'http://localhost:8000'])
    allowed = set(origins or (configured.split(',') if isinstance(configured, str) else configured))

    def busy():
        return any(not task.done() for task in handler.current_conversation_tasks.values())

    async def speak(text, key, valid):
        if len(handler.client_connections) != 1:
            return 'no_client' if not handler.client_connections else 'multiple_clients'
        if busy():
            return 'busy'
        from .presentation import enqueue
        await enqueue(handler, text, 'game-' + key, valid=valid)
        return 'queued'

    game = service or TavernService(speak=speak, busy=busy, persona=lambda: current_persona(handler))

    def credentials(request):
        origin = request.headers.get('origin', '')
        if origin not in allowed or request.client.host not in ('127.0.0.1', '::1', 'localhost', 'testclient'):
            raise GameError(403, '只允许配置的本机酒馆页面连接。')
        token = request.headers.get('x-pet-game-token', '')
        return token, origin

    @router.post('/{operation}')
    async def dispatch(operation: str, request: Request, payload: dict):
        try:
            token, origin = credentials(request)
            if operation in ('context', 'comment', 'question', 'draft', 'claim', 'clear-memory'):
                game.check_epoch(token, origin, payload.get('epoch'))
            if operation == 'connect':
                result = game.connect(origin)
            elif operation == 'mode':
                result = game.set_mode(token, origin, payload.get('mode'), payload.get('turns', 1))
            elif operation == 'pause':
                result = game.pause(token, origin, clear=payload.get('clear') is True)
            elif operation == 'context':
                result = game.sync(token, origin, payload)
            elif operation == 'status':
                result = game.status(token, origin, heartbeat=True)
            elif operation == 'comment':
                result = await game.comment(token, origin, voice=payload.get('voice') is True,
                                            force=payload.get('force') is True)
            elif operation == 'question':
                result = await game.question(token, origin, payload.get('text'), payload.get('voice') is True)
            elif operation == 'draft':
                result = await game.draft(token, origin, payload.get('revision'), payload.get('goal', ''))
            elif operation == 'claim':
                result = game.claim(token, origin, payload.get('draft_id'), payload.get('revision'))
            elif operation == 'clear-memory':
                result = game.clear_memory(token, origin)
            else:
                raise GameError(404, '未知游戏接口。')
            return {'ok': True, **result}
        except GameError as exc:
            return JSONResponse({'ok': False, 'error': exc.message}, status_code=exc.status)

    return router
