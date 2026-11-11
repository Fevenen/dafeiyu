"""Give explicit DSH screen questions a fresh frame from the pet's opt-in switch."""

import re
from . import settings
from .net import request
from .vision import observation_note
from .capabilities import SCREEN_PATTERN


def screen_discussion(text):
    return bool(re.search(r'屏幕(?:识别|视觉|捕获|观察)?.{0,6}(?:机制|流程|原理|实现|逻辑|功能怎么|怎么走|如何实现)', text))


def screen_candidate(text):
    text = text.strip()
    return len(text) <= 500 and not screen_discussion(text) and (
        wants_screen(text) or bool(re.search(SCREEN_PATTERN, text)))


def wants_screen(text):
    text = text.strip()
    if len(text) > 500 or screen_discussion(text):
        return False
    return bool(re.search(
        r'(?:看(?:看|一下|一眼)?|识别|读一下).{0,16}(?:屏幕|画面|截图|窗口|题目|这道题|这题|报错|这个|这里|这张)'
        r'|(?:屏幕|画面|窗口).{0,8}(?:上|里|中|显示|写着|内容)'
        r'|你.{0,4}看(?:不见|不到|得到|得见|见了吗)'
        r'|我.{0,6}(?:在干|在做|正在).{0,5}(?:啥|什么)'
        r'|(?:这道题|这个题目|这题).{0,12}(?:做|解|意思|干啥)', text))


def fetch_snapshot(client_uid=None):
    try:
        payload = {'client_uid': client_uid} if client_uid else {}
        response = request('POST', settings.PET_API + '/api/vision/snapshot', json=payload, timeout=(1, 5))
        response.raise_for_status()
        return response.json()
    except Exception:
        return {'ok': False, 'status': 'unavailable'}


def screen_skip_reason(body):
    messages = body.get('messages') or []
    if not messages or messages[-1].get('role') != 'user':
        return 'skipped'
    content = messages[-1].get('content', '')
    if isinstance(content, list):
        if any(isinstance(part, dict) and part.get('type') == 'image_url' for part in content):
            return 'provided_image'
    # Provider-side title/summary jobs must not request the desktop screen.
    system = ' '.join(str(message.get('content', '')) for message in messages
                      if message.get('role') in ('system', 'developer'))
    if re.search(r'(?:generate|create|write).{0,30}(?:title|summary)|标题生成|会话标题|生成.{0,8}标题', system, re.I):
        return 'background_task'
    return None


def attach_screen(body, fetch=None, decision=None):
    reason = screen_skip_reason(body)
    if reason:
        return body, reason
    messages = body['messages']
    last = messages[-1]
    content = last.get('content', '')
    if isinstance(content, list):
        text = ''.join(part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') == 'text')
    elif isinstance(content, str):
        text = content
    else:
        return body, 'skipped'
    if decision is False or (decision is None and not wants_screen(text)):
        return body, 'skipped'
    metadata = body.get('metadata') or {}
    target = metadata.get('pet_client_uid') if isinstance(metadata, dict) else None
    snapshot = fetch() if fetch else fetch_snapshot(client_uid=target)
    parts = list(content) if isinstance(content, list) else [{'type': 'text', 'text': content}]
    frame = snapshot.get('frame')
    if snapshot.get('ok') and isinstance(frame, dict) and observation_note([frame]):
        parts.append({'type': 'text', 'text':
            '本轮已附上通过桌宠屏幕开关取得的新截图。请根据这张图回答；此前说“不能看屏幕”的回复已经过时。\n'
            + observation_note([frame])})
        parts.append({'type': 'image_url', 'image_url': {'url': frame['data']}})
        status = 'attached'
    else:
        status = str(snapshot.get('status', 'unavailable'))
        reason = {'disabled': '桌宠屏幕开关当前关闭，或没有已授权的在线桌宠',
                  'ambiguous': '有多个桌宠同时开启屏幕，需要只保留一个观察目标',
                  'timeout': '本次截图超时', 'capture_failed': '本次截图失败'}.get(status, '桌宠屏幕连接暂不可用')
        parts.append({'type': 'text', 'text': '[本轮屏幕状态：' + reason
                      + '。本轮没有取得新截图，不能凭旧描述猜当前画面。请简短提示主人开启桌宠的显示器按钮后重试；不要声称自己天生不能看屏幕。]'})
    updated = {**body, 'messages': [*messages[:-1], {**last, 'content': parts}]}
    return updated, status
