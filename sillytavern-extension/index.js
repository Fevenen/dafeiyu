import { TavernController } from './controller.js';
import { buildSnapshot, plainText } from './snapshot.js';

export function mount(getContext = () => globalThis.SillyTavern.getContext(), adapters = {}) {
    if (document.getElementById('dafeiyu-tavern-toolbar')) return;
    const context = getContext();
    const preferences = context.extensionSettings.dafeiyu_tavern ||= { base: 'http://127.0.0.1:12393', voice: true, autoComment: true };
    const toolbar = document.createElement('div');
    toolbar.id = 'dafeiyu-tavern-toolbar';
    toolbar.innerHTML = `<button type="button" role="switch" aria-checked="false" data-companion>
        <span class="pet-switch" aria-hidden="true"></span>🐋 大肥鱼陪玩</button>
        <span data-status role="status">已关闭</span><button type="button" data-stop hidden>我来</button>
        <label data-voice-setting hidden><input data-voice type="checkbox">桌宠播报</label>`;
    const form = document.getElementById('send_form');
    (form?.parentElement || document.body).insertBefore(toolbar, form || null);
    const el = name => toolbar.querySelector(`[data-${name}]`);
    el('voice').checked = preferences.voice !== false;
    let token = '', adapterBusy = false, toggling = false, desktopAction = null;
    const input = () => document.getElementById('send_textarea')?.value || '';
    const isBusy = () => {
        const stop = document.getElementById('mes_stop');
        return adapterBusy || !!(stop && getComputedStyle(stop).display !== 'none');
    };
    function endpoint() {
        const value = new URL(preferences.base || 'http://127.0.0.1:12393');
        if (value.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(value.hostname) || value.username || value.password) throw new Error('请填写本机HTTP桌宠地址');
        return value.origin + '/api/game/sillytavern/';
    }
    async function api(operation, data = {}, signal) {
        if (adapters.api) {
            const result = await adapters.api(operation, data, signal);
            if (operation === 'connect') token = result.token || 'fixture';
            return result;
        }
        const response = await fetch(endpoint() + operation, { method: 'POST', credentials: 'omit', signal,
            headers: { 'Content-Type': 'application/json', ...(token ? { 'X-Pet-Game-Token': token } : {}) }, body: JSON.stringify(data) });
        const result = await response.json();
        if (!response.ok || !result.ok) throw Object.assign(new Error(result.error || '桌宠连接失败'), { status: response.status });
        if (operation === 'connect') token = result.token;
        return result;
    }
    async function appendPetMessage(append, beforeEvent, renderedEvent, isCurrentChat) {
        const chat = document.getElementById('chat');
        if (!chat || !events?.[beforeEvent] || !events?.[renderedEvent]) return append();
        let reading;
        const before = () => {
            const top = chat.scrollTop;
            reading = { top, followsLatest: chat.scrollHeight - chat.clientHeight - top < 24 };
        };
        const rendered = () => {
            if (!reading || !isCurrentChat(getContext())) return;
            const { top, followsLatest } = reading;
            if (followsLatest) {
                chat.scrollTop = chat.scrollHeight;
            } else if (getContext().powerUserSettings?.auto_scroll_chat_to_bottom) {
                // SillyTavern's message renderer queues its scroll before emitting the rendered event.
                requestAnimationFrame(() => { if (isCurrentChat(getContext())) chat.scrollTop = top; });
            }
        };
        source.on(events[beforeEvent], before);
        source.on(events[renderedEvent], rendered);
        try { return await append(); }
        finally {
            source.removeListener(events[beforeEvent], before);
            source.removeListener(events[renderedEvent], rendered);
        }
    }
    async function submit(text, options) {
        if (adapters.submit) return adapters.submit(text, options);
        // Verified against ST 1.19.0. Never place AI text in the user's input box.
        const [{ sendMessageAsUser }, { hasPendingFileAttachment }] = await Promise.all([import('/script.js'), import('/scripts/chats.js')]);
        const current = getContext();
        const currentChatId = current.getCurrentChatId();
        const isCurrentChat = live => live.characterId === current.characterId && !live.groupId && live.getCurrentChatId() === currentChatId;
        const stillInControl = () => options.guard() && !options.signal.aborted && isCurrentChat(getContext());
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
                    && isCurrentChat(live)) live.stopGeneration();
        };
        options.signal.addEventListener('abort', abortOwnGeneration, { once: true });
        try {
            const message = await appendPetMessage(() => sendMessageAsUser(text), 'MESSAGE_SENT', 'USER_MESSAGE_RENDERED', isCurrentChat);
            message.extra ||= {}; message.extra.dafeiyu_tavern = { action_id: options.actionId };
            if (!isCurrentChat(getContext())) return;
            await current.saveChat();
            if (!stillInControl() || input().trim()) return;
            if (getContext().chat.at(-1) !== message) throw new Error('剧情已变化，未请求角色回复');
            // Quiet generation never consumes/clears new human input or runs slash commands.
            generating = true;
            const reply = await current.generate('quiet', { automatic_trigger: true, quietToLoud: true, signal: options.signal });
            generating = false;
            if (!stillInControl()) return;
            if (getContext().chat.at(-1) !== message) throw new Error('剧情已变化，已丢弃旧角色回复');
            if (typeof reply !== 'string' && !(reply instanceof String)) throw new Error('酒馆没有返回角色正文');
            if (!String(reply).trim()) throw new Error('酒馆角色回复为空');
            await appendPetMessage(() => current.saveReply({ type: 'normal', getMessage: String(reply) }),
                'MESSAGE_RECEIVED', 'CHARACTER_MESSAGE_RENDERED', isCurrentChat);
            if (!isCurrentChat(getContext())) return;
            await current.saveChat();
        } finally { generating = false; options.signal.removeEventListener('abort', abortOwnGeneration); adapterBusy = false; }
    }
    const controller = new TavernController({ api, capture: adapters.capture || (() => buildSnapshot(getContext(), location.origin, plainText)),
        getInput: input, isBusy: adapters.isBusy || isBusy, submit, voice: () => preferences.voice !== false,
        canSend: () => getContext().groupId ? '群聊目前支持陪玩；接管请使用单角色聊天' : getContext().onlineStatus === 'no_connection' ? '酒馆主API尚未连接，请先连接' : true,
        onState: state => {
            el('companion').setAttribute('aria-checked', String(state.mode !== 'off'));
            el('status').textContent = state.statusText;
            el('stop').hidden = !state.run && !state.manualSubmitting && !state.granting;
            el('voice-setting').hidden = state.mode === 'off';
        } });
    controller.autoComment = () => preferences.autoComment !== false;
    const report = error => {
        if (error?.name !== 'AbortError') el('status').textContent = error.message || String(error);
    };
    async function setCompanion(enabled) {
        if (toggling && enabled) return;
        toggling = true;
        try {
            if (enabled) await controller.enable();
            else await controller.stop(true);
        } finally { toggling = false; }
    }
    el('companion').onclick = () => { void setCompanion(controller.mode === 'off').catch(report); };
    el('stop').onclick = () => { void controller.stop(false).catch(report); };
    el('voice').onchange = () => {
        preferences.voice = el('voice').checked;
        getContext().saveSettingsDebounced();
    };
    const humanInput = () => {
        if (controller.run || controller.manualSubmitting || controller.granting || ['run', 'submit'].includes(desktopAction?.action)) {
            void controller.stop(false, '你开始输入，控制权已交还').catch(report);
        }
    };
    document.getElementById('send_textarea')?.addEventListener('input', humanInput);
    const source = context.eventSource, events = context.eventTypes || context.event_types;
    const listeners = [];
    const on = (key, fn) => { if (events?.[key]) { source.on(events[key], fn); listeners.push([events[key], fn]); } };
    for (const event of ['CHAT_CHANGED', 'MESSAGE_EDITED', 'MESSAGE_DELETED', 'MESSAGE_SWIPED', 'MESSAGE_UPDATED']) {
        on(event, () => { if (controller.mode !== 'off') void controller.invalidate().catch(report); });
    }
    const observe = () => {
        const last = (getContext().chat || []).filter(row => !row.is_system && row.mes?.trim()).at(-1);
        if (controller.mode !== 'off' && !controller.run) void controller.sceneFinished(
            !!last && !last.is_user && controller.autoComment()).catch(report);
    };
    on('GENERATION_ENDED', () => { setTimeout(observe, 200); });
    on('GENERATION_STOPPED', () => { if (controller.run) void controller.stop(false, '酒馆生成已停止，接管暂停').catch(report); });
    let polling = false;
    const interval = setInterval(async () => {
        if (polling || toggling || controller.mode === 'off') return;
        polling = true; try { await controller.heartbeat(); } catch (error) { report(error); await controller.stop(true).catch(() => {}); } finally { polling = false; }
    }, 2000);
    let desktopPolling = false, desktopReceipts = [], desktopSupported = true, disposed = false;
    async function performDesktop(command) {
        const action = command.action;
        if (action === 'off') return setCompanion(false);
        if (action === 'pause') return controller.stop(false);
        const generation = controller.generation, snapshot = controller.snapshot;
        if (controller.mode === 'off' || command.epoch !== controller.epoch || command.revision !== controller.server?.revision) {
            throw new Error('剧情或控制权已变化，请重试。');
        }
        if (action === 'auto') {
            preferences.autoComment = command.enabled;
            getContext().saveSettingsDebounced();
            return;
        }
        const latest = await controller.capture();
        if (!controller.current(generation) || latest.chat_id !== snapshot?.chat_id || latest.signature !== snapshot.signature) {
            throw new Error('剧情已变化，旧操作已取消。');
        }
        if (action === 'submit') {
            if (controller.draft?.id !== command.draft_id) throw new Error('草稿已经失效。');
            await controller.submitDraft(command.text);
        } else {
            if (controller.run) throw new Error('请先完成当前操作，或点「我来」。');
            if (action === 'draft') await controller.draftOnly(command.goal);
            else await controller.runTurns(command.turns, command.goal);
        }
    }
    async function pollDesktop() {
        if (disposed || !desktopSupported || desktopPolling || controller.mode === 'off'
                || !controller.connected || !controller.snapshot) return;
        desktopPolling = true;
        const receipts = desktopReceipts.slice();
        const connectionToken = token;
        let succeeded = false;
        try {
            const { command } = await api('desktop-poll', { receipts, view: {
                auto: controller.autoComment(), status: controller.statusText, draft: controller.draft?.id,
                run: controller.run, can_send: controller.canSend() === true && !input().trim() && !isBusy(),
            } });
            desktopReceipts.splice(0, receipts.length);
            succeeded = controller.mode !== 'off' && connectionToken === token;
            if (!disposed && connectionToken === token && command) {
                desktopAction = command;
                void performDesktop(command).then(
                    () => { desktopReceipts.push({ done: command.id }); },
                    error => { desktopReceipts.push({ done: command.id, error: error.message }); report(error); },
                ).finally(() => { if (desktopAction === command) desktopAction = null; });
            }
        } catch (error) {
            if (error.status === 404) desktopSupported = false;
            if (error.status === 403) {
                token = ''; controller.connected = false;
                if (controller.mode !== 'off') await controller.stop(true).catch(() => {});
            }
        } finally { desktopPolling = false; }
        if (succeeded) void pollDesktop();
    }
    const desktopInterval = setInterval(pollDesktop, 500);
    void pollDesktop();
    const dispose = () => {
        disposed = true;
        document.removeEventListener('visibilitychange', resume);
        clearInterval(interval); clearInterval(desktopInterval);
        for (const [event, fn] of listeners) source.removeListener(event, fn);
        if (token && !adapters.api) {
            void fetch(endpoint() + 'mode', { method: 'POST', credentials: 'omit', keepalive: true,
                headers: { 'Content-Type': 'application/json', 'X-Pet-Game-Token': token }, body: JSON.stringify({ mode: 'off' }) }).catch(() => {});
        }
        void controller.stop(true).catch(() => {});
    };
    const resume = () => { if (!document.hidden && controller.mode !== 'off') void controller.heartbeat().catch(report); };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('pagehide', dispose, { once: true });
    return { controller, dispose, toolbar };
}

if (globalThis.SillyTavern?.getContext) {
    const context = globalThis.SillyTavern.getContext();
    if (document.getElementById('send_form')) mount();
    else context.eventSource.once(context.eventTypes.APP_READY, () => mount());
}
