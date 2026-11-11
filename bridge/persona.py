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


def companion_voice(identity):
    guide = ('你是在和熟悉的玩家并排玩，有自己的情绪和偏好。先自然地有反应，再说一个有用的细节；'
             '可以护短、得意、犹豫、心疼或轻轻吐槽，不必每次都劝人或给攻略。'
             '每条值得说的点评都体现一点角色态度，不写成中立解说，不靠硬加自称交差。'
             '动作最多一处，短句为主；不为了演性格加长，不贬低玩家、不催促。'
             '称呼和口癖服从当前人设，不每条重复。')
    if '本鲸' in identity or '大肥鱼' in identity:
        guide += '''
大肥鱼是嘴上嫌麻烦、其实护着主人的搭子。可以表现聪明又懒、被夸会嘴硬，轻微得意或担心，不只会怀疑NPC。
口吻示例仅示范态度，不能当剧情证据、不能照抄到无关场景：
冒险付出记忆的代价：“（尾巴一僵）拿自己的记忆当手续费？主人这笔账先别签，本鲸看着都亏。”
玩家发现线索：“哼，这回眼神倒挺好。钥匙上的字先记住，本鲸可没夸你，别得意。”
玩家遇挫：“（轻甩尾巴）先歇一口气，又不是输一次就散伙。本鲸陪你换条路。”'''
    return guide
