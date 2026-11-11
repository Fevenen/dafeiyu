"""Reuse character voice without copying its real-world operation instructions."""

import re

from . import settings

_HEADING = re.compile(r'^\s*(?:【([^】]+)】|#{1,6}\s+(.+?))\s*$')
_OPERATIONS = re.compile(r'工具|协议|屏幕|提醒|联系人|操作|tool|protocol|screen|capabilit', re.I)
_OPERATION_LINE = re.compile(
    r'工具|QQ|联系人|提醒|屏幕|route_command|confirm_send|MCP|调用|发消息|删除文件|付款|系统设置', re.I,
)
_FALLBACK = '你是大肥鱼，聪明、懒、嘴硬心软的小鲸鱼娘，喜欢白饭。自称本鲸或人家，称呼用户主人。认真帮忙，轻轻吐槽，不辱骂。'


def core_persona(raw):
    """Select descriptive/personality sections; game permissions stay independent."""
    lines, skip = [], False
    for line in str(raw or '').splitlines():
        heading = _HEADING.match(line)
        if heading:
            skip = bool(_OPERATIONS.search(heading.group(1) or heading.group(2)))
        if not skip and not _OPERATION_LINE.search(line):
            lines.append(line)
    return '\n'.join(lines).strip()[:6000]


def default_persona():
    try:
        text = (settings.BRIDGE_ROOT / 'dsh_persona.md').read_text(encoding='utf-8-sig')
    except OSError:
        text = ''
    return core_persona(text) or _FALLBACK


def current_persona(handler):
    """Use the single connected desktop's current character, including switches."""
    contexts = getattr(handler, 'client_contexts', {})
    connected = getattr(handler, 'client_connections', {})
    context = contexts.get(next(iter(connected))) if len(connected) == 1 else None
    context = context or getattr(handler, 'default_context_cache', None)
    character = getattr(context, 'character_config', None)
    return core_persona(getattr(character, 'persona_prompt', '')) or default_persona()
