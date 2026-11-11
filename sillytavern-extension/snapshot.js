export async function sha(value) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function buildSnapshot(context, origin, plain = text => text) {
    const id = context.getCurrentChatId?.() ?? context.chatId;
    if (!id || (!context.groupId && context.characterId === undefined)) throw new Error('请先打开一个酒馆角色聊天');
    const visible = (context.chat || []).filter(message => !message.is_system && typeof message.mes === 'string' && message.mes.trim());
    if (!visible.length) throw new Error('当前聊天没有可读取的剧情');
    if (visible.length > 4000) throw new Error('当前聊天超过4000条，请使用较短的聊天分支');
    const rows = visible.map(message => ({ role: message.is_user ? 'user' : 'assistant',
        name: String(message.name || (message.is_user ? context.name1 : context.name2) || ''),
        text: plain(message.mes), action_id: message.extra?.dafeiyu_tavern?.action_id || '',
        swipe: message.swipe_id ?? 0, date: message.send_date ?? '' }));
    const fingerprints = await Promise.all(rows.map(row => sha(JSON.stringify(row))));
    const messages = []; let budget = 16000, trimmed = rows.length > 40;
    for (const row of [...rows].reverse().slice(0, 40)) {
        const limit = Math.min(8000, budget), text = row.text.slice(-limit);
        trimmed ||= row.text.length > limit;
        if (text) { messages.unshift({ role: row.role, name: row.name, text, action_id: row.action_id }); budget -= text.length; }
        if (budget <= 0) { trimmed = true; break; }
    }
    const chat_id = JSON.stringify([origin, context.groupId || null, context.characterId ?? null, String(id)]);
    const persona = String(context.powerUserSettings?.persona_description || '').slice(0, 2000);
    const player_name = String(context.name1 || '玩家');
    const signature = await sha(JSON.stringify([chat_id, fingerprints, persona, player_name]));
    return { chat_id, fingerprints, messages, persona, player_name, signature, trimmed };
}

export function plainText(text) {
    const html = new DOMParser().parseFromString(text, 'text/html');
    html.querySelectorAll('script,style,template,[hidden],[style*="display:none"],[style*="display: none"]').forEach(node => node.remove());
    html.querySelectorAll('br').forEach(node => node.replaceWith('\n'));
    return html.body.textContent || '';
}
