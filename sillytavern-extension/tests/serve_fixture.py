"""Only synthetic games and model responses, on a dedicated loopback port."""
import json
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from bridge.game_routes import build_router
from bridge.games.sillytavern import TavernService

root = Path(os.environ['PET_TEST_DIR'])
records = []
delays = {'action': 0, 'npc': 0}


def record(kind, data):
    records.append({'kind': kind, 'data': data})
    (root / 'requests.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')


async def model(kind, data):
    assert 'TEST_HIDDEN_CARD_SECRET' not in json.dumps(data), 'Hidden character information leaked to the companion'
    record(kind, data)
    await asyncio.sleep(delays.get(kind, 0) / 1000)
    if kind == 'action':
        return '我先问老板，二楼的钥匙放在哪里。'
    if kind == 'question':
        return '（眯眼）先问钥匙，再核对楼上的脚步声。'
    return json.dumps({'comment': '（甩尾巴）老板的话有矛盾，先问清楚钥匙。',
                       'memory': {'facts': '老板说楼上没有住客', 'suspicions': '可能在隐瞒'}}, ensure_ascii=False)


async def speak(text, key, valid):
    record('voice', {'text': text, 'valid': valid()})


from types import SimpleNamespace
service = TavernService(root=root / 'game', model=model, speak=speak)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:8123'], allow_methods=['*'], allow_headers=['*'])
app.include_router(build_router(SimpleNamespace(client_connections={}, current_conversation_tasks={}),
                                service=service, origins=['http://127.0.0.1:8123']))


@app.get('/v1/models')
async def models():
    return {'object': 'list', 'data': [{'id': 'fixture-model', 'object': 'model'}]}


@app.post('/v1/chat/completions')
async def npc(payload: dict):
    record('npc', {'model': payload.get('model')})
    await asyncio.sleep(delays['npc'] / 1000)
    return {'id': 'fixture-reply', 'object': 'chat.completion', 'created': 1, 'model': 'fixture-model',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '老板把钥匙放在桌上：“你可以先问清楚上楼的规则。”'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}


@app.get('/test/status')
async def status():
    return {'ok': True, 'counts': {kind: sum(row['kind'] == kind for row in records) for kind in ('action', 'npc', 'comment', 'question', 'voice')}}


@app.post('/test/control')
async def control(payload: dict):
    for key in delays:
        delays[key] = max(0, min(3000, int(payload.get(key, 0))))
    return {'ok': True}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18424, log_level='warning')
