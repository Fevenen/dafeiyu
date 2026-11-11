import { TavernController } from './controller.js';
import { buildSnapshot, plainText } from './snapshot.js';

export function mount(getContext = () => globalThis.SillyTavern.getContext(), adapters = {}) {
    if (document.getElementById('dafeiyu-tavern-panel')) return;
    const context = getContext();
    const preferences = context.extensionSettings.dafeiyu_tavern ||= { base: 'http://127.0.0.1:12393', voice: true, autoComment: true };
    const panel = document.createElement('section'); panel.id = 'dafeiyu-tavern-panel'; panel.hidden = true;
    panel.innerHTML = `<header><strong>🐋 大肥鱼酒馆</strong><button data-close aria-label="收起面板">×</button></header>
      <p class="pet-notice">开启后同步当前聊天正文。陪玩不写入剧情；接管只在指定轮数内行动，随时可点“我来”。</p>
      <label>本机桌宠地址 <input data-base type="url" spellcheck="false"></label>
      <div class="pet-row"><button data-enable>开启陪玩</button><button data-off>关闭</button><button data-stop>我来 · 暂停接管</button></div>
      <p data-status role="status">已关闭</p><small data-voice-status></small>
      <div class="pet-row"><label><input data-auto type="checkbox">自动点评</label><label><input data-voice type="checkbox">桌宠播报</label><button data-observe>点评当前剧情</button></div>
      <div data-comments class="pet-comments" aria-live="polite"></div>
      <label>问大肥鱼 <textarea data-question rows="2" placeholder="比如：你觉得这次该怎么选？"></textarea></label><button data-ask>问她</button>
      <hr><label>接管目标 <textarea data-goal rows="2" placeholder="比如：试探老板，暂时不要暴露脚印线索"></textarea></label>
      <div class="pet-row"><button data-draft>生成行动草稿</button><button data-single>直接代玩一轮</button></div>
      <div class="pet-row"><label>连续轮数 <select data-turns><option>2</option><option selected>3</option><option>4</option><option>5</option></select></label><button data-run>开始有限接管</button></div><small>接管支持单角色聊天，每次最多5轮、5分钟；角色回复完整生成后显示。</small>
      <label>玩家行动草稿 <textarea data-action rows="4" placeholder="草稿在这里，你可以先修改"></textarea></label><button data-submit disabled>提交这份草稿</button>
      <details><summary>剧情笔记</summary><pre data-memory>暂无笔记</pre><button data-clear>清除当前聊天笔记</button></details>`;
    document.body.append(panel);
    const toolbar = document.createElement('div'); toolbar.id = 'dafeiyu-tavern-toolbar';
    toolbar.innerHTML = '<button data-open>🐋 大肥鱼陪玩</button><span data-badge>关闭</span><button data-stop>我来</button>';
    const form = document.getElementById('send_form');
    (form?.parentElement || document.body).insertBefore(toolbar, form || null);
    const el = name => panel.querySelector(`[data-${name}]`);
    el('base').value = preferences.base; el('voice').checked = preferences.voice; el('auto').checked = preferences.autoComment;
    let token = '', draftId = '', lastComment = '', adapterBusy = false;
    const input = () => document.getElementById('send_textarea')?.value || '';
    const isBusy = () => {
        const stop = document.getElementById('mes_stop');
        return adapterBusy || !!(stop && getComputedStyle(stop).display !== 'none');
    };
    function endpoint() {
        const value = new URL(el('base').value);
        if (value.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(value.hostname) || value.username || value.password) throw new Error('请填写本机HTTP桌宠地址');
        return value.origin + '/api/game/sillytavern/';
    }
    async function api(operation, data = {}, signal) {
        if (adapters.api) return adapters.api(operation, data, signal);
        const response = await fetch(endpoint() + operation, { method: 'POST', credentials: 'omit', signal,
            headers: { 'Content-Type': 'application/json', ...(token ? { 'X-Pet-Game-Token': token } : {}) }, body: JSON.stringify(data) });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || '桌宠连接失败');
        if (operation === 'connect') token = result.token;
        return result;
    }
    async function submit(text, options) {
        if (adapters.submit) return adapters.submit(text, options);
        // Verified against ST 1.19.0. Never place AI text in the user's input box.
        const [{ sendMessageAsUser }, { hasPendingFileAttachment }] = await Promise.all([import('/script.js'), import('/scripts/chats.js')]);
        const current = getContext();
        const currentChatId = current.getCurrentChatId();
        if (!options.guard() || options.signal.aborted || input().trim()) throw new Error('控制权或输入已变化，未提交');
        if (current.groupId) throw new Error('群聊目前支持陪玩；接管请使用单角色聊天');
        if (current.onlineStatus === 'no_connection') throw new Error('酒馆主API尚未连接');
        if (hasPendingFileAttachment()) throw new Error('酒馆有待发送附件，请先处理，避免附到接管行动中');
        if (!sendMessageAsUser || !current.generate || !current.saveReply) throw new Error('当前酒馆版本不支持此接管接口');
        adapterBusy = true;
        let generating = false;
        const abortOwnGeneration = () => {
            const live = getContext(), lastPlayer = (live.chat || []).filter(row => row.is_user).at(-1);
            if (generating && lastPlayer?.extra?.dafeiyu_tavern?.action_id === options.actionId
                    && live.getCurrentChatId() === currentChatId) live.stopGeneration();
        };
        options.signal.addEventListener('abort', abortOwnGeneration, { once: true });
        try {
            const message = await sendMessageAsUser(text);
            message.extra ||= {}; message.extra.dafeiyu_tavern = { action_id: options.actionId };
            await current.saveChat();
            if (!options.guard() || options.signal.aborted || input().trim()) return;
            // Quiet generation never consumes/clears new human input or runs slash commands.
            generating = true;
            const reply = await current.generate('quiet', { automatic_trigger: true, quietToLoud: true, signal: options.signal });
            generating = false;
            if (!options.guard() || options.signal.aborted) return;
            if (typeof reply !== 'string' && !(reply instanceof String)) throw new Error('酒馆没有返回角色正文');
            if (!String(reply).trim()) throw new Error('酒馆角色回复为空');
            await current.saveReply({ type: 'normal', getMessage: String(reply) });
            await current.saveChat();
        } finally { generating = false; options.signal.removeEventListener('abort', abortOwnGeneration); adapterBusy = false; }
    }
    const controller = new TavernController({ api, capture: adapters.capture || (() => buildSnapshot(getContext(), location.origin, plainText)),
        getInput: input, isBusy: adapters.isBusy || isBusy, submit, voice: () => el('voice').checked,
        canSend: () => getContext().groupId ? '群聊目前支持陪玩；接管请使用单角色聊天' : getContext().onlineStatus === 'no_connection' ? '酒馆主API尚未连接，请先连接' : true,
        onState: state => {
            el('status').textContent = state.statusText + (state.snapshot?.trimmed ? ' · 使用最近剧情（上下文有上限）' : '');
            toolbar.querySelector('[data-badge]').textContent = state.mode === 'off' ? '关闭' : state.mode === 'takeover' ? `接管 ${state.run?.completed || 0}/${state.run?.total || 1}` : '陪玩';
            el('submit').disabled = !state.draft || !!state.run?.automatic;
            if (state.draft && draftId !== state.draft.id) { draftId = state.draft.id; el('action').value = state.draft.text; }
            const comments = state.server?.comments || [], latest = comments.at(-1)?.id;
            if (latest !== lastComment) { lastComment = latest; el('comments').textContent = comments.map(item => item.text).join('\n\n'); }
            el('memory').textContent = state.server?.memory_review ? '剧情已修改，旧笔记已清除，等待重新整理。' : JSON.stringify(state.server?.memory || {}, null, 2);
            for (const name of ['draft', 'single', 'run']) el(name).disabled = !!state.run;
            el('base').disabled = state.mode !== 'off';
            el('voice-status').textContent = ({ queued: '点评已加入桌宠语音队列', busy: '桌宠正在处理你的对话，本次先显示文字',
                no_client: '桌宠未连接，当前只显示文字', multiple_clients: '连接了多个桌宠，暂不自动选择播报对象' })[state.server?.voice_status] || '';
        } });
    const report = error => { if (error?.name !== 'AbortError') { el('status').textContent = error.message || String(error); } };
    const act = fn => () => { Promise.resolve().then(fn).catch(report); };
    const stop = act(() => controller.stop(false));
    toolbar.querySelector('[data-open]').onclick = () => { panel.hidden = !panel.hidden; };
    toolbar.querySelector('[data-stop]').onclick = stop; el('stop').onclick = stop;
    el('close').onclick = () => { panel.hidden = true; };
    el('enable').onclick = act(() => controller.enable()); el('off').onclick = act(() => controller.stop(true));
    el('observe').onclick = act(async () => { if (controller.mode === 'off') await controller.enable(); await controller.observe(true); });
    el('ask').onclick = act(() => controller.ask(el('question').value));
    el('draft').onclick = act(() => controller.draftOnly(el('goal').value));
    el('submit').onclick = act(() => controller.submitDraft(el('action').value));
    el('single').onclick = act(() => controller.runTurns(1, el('goal').value));
    el('run').onclick = act(() => controller.runTurns(Number(el('turns').value), el('goal').value));
    el('clear').onclick = act(async () => {
        await controller.stop(false); const state = await controller.rpc('clear-memory'); controller.accept(state);
    });
    for (const name of ['voice', 'auto', 'base']) el(name).onchange = () => {
        preferences.base = el('base').value; preferences.voice = el('voice').checked; preferences.autoComment = el('auto').checked;
        getContext().saveSettingsDebounced();
        if (name === 'base') { controller.connected = false; token = ''; }
    };
    const humanInput = () => { if (controller.run || controller.draft) void controller.stop(false, '你开始输入，控制权已交还').catch(report); };
    document.getElementById('send_textarea')?.addEventListener('input', humanInput);
    const source = context.eventSource, events = context.eventTypes || context.event_types;
    const listeners = [];
    const on = (key, fn) => { if (events?.[key]) { source.on(events[key], fn); listeners.push([events[key], fn]); } };
    for (const event of ['CHAT_CHANGED', 'MESSAGE_EDITED', 'MESSAGE_DELETED', 'MESSAGE_SWIPED', 'MESSAGE_UPDATED']) {
        on(event, () => { if (controller.mode !== 'off') void controller.invalidate().catch(report); });
    }
    const observe = () => {
        const last = (getContext().chat || []).filter(row => !row.is_system && row.mes?.trim()).at(-1);
        if (last && !last.is_user && controller.mode !== 'off' && !controller.run && el('auto').checked) void controller.observe(false).catch(report);
    };
    on('GENERATION_ENDED', () => { setTimeout(observe, 200); });
    on('GENERATION_STOPPED', () => { if (controller.run) void controller.stop(false, '酒馆生成已停止，接管暂停').catch(report); });
    let polling = false;
    const interval = setInterval(async () => {
        if (polling || controller.mode === 'off') return;
        polling = true; try { await controller.heartbeat(); } catch (error) { report(error); await controller.stop(true).catch(() => {}); } finally { polling = false; }
    }, 2000);
    const dispose = () => {
        clearInterval(interval); for (const [event, fn] of listeners) source.removeListener(event, fn);
        if (token && !adapters.api) {
            void fetch(endpoint() + 'mode', { method: 'POST', credentials: 'omit', keepalive: true,
                headers: { 'Content-Type': 'application/json', 'X-Pet-Game-Token': token }, body: JSON.stringify({ mode: 'off' }) }).catch(() => {});
        }
        void controller.stop(true).catch(() => {});
    };
    window.addEventListener('pagehide', dispose, { once: true });
    return { controller, dispose, panel, toolbar };
}

if (globalThis.SillyTavern?.getContext) {
    const context = globalThis.SillyTavern.getContext();
    if (document.getElementById('send_form')) mount();
    else context.eventSource.once(context.eventTypes.APP_READY, () => mount());
}
