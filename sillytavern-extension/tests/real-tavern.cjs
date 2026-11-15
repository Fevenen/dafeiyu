const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.env.PET_TEST_DIR;
app.setPath('userData', path.join(root, 'browser-profile'));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
    const win = new BrowserWindow({ show: false, width: 1320, height: 1000, webPreferences: { sandbox: false, contextIsolation: true, backgroundThrottling: false, offscreen: true } });
    const errors = [];
    win.webContents.on('console-message', (_, level, message) => { if (level === 3) errors.push(message.slice(0, 250)); });
    const js = code => win.webContents.executeJavaScript(code, true);
    async function until(code, label, milliseconds = 45000) {
        const end = Date.now() + milliseconds;
        while (Date.now() < end) { try { if (await js(code)) return; } catch {} await wait(100); }
        throw new Error('Timed out: ' + label + ' ' + await js('document.querySelector("#dafeiyu-tavern-toolbar [data-status]")?.textContent'));
    }
    const originalApi = 'http://127.0.0.1:12393/api/game/sillytavern/';
    win.webContents.session.webRequest.onBeforeRequest({ urls: [originalApi + '*'] }, (details, callback) => {
        callback({ redirectURL: details.url.replace(originalApi, 'http://127.0.0.1:18424/api/game/sillytavern/') });
    });
    await win.loadURL('http://127.0.0.1:8123');
    await until('!!globalThis.SillyTavern?.getContext && !!document.getElementById("dafeiyu-tavern-toolbar")', 'extension loaded');
    await js('document.querySelectorAll("dialog[open] .popup-button-ok").forEach(button=>button.click())');
    await js(`(async()=>{
        document.querySelector('#dialogue_popup_ok')?.click();
        const c=SillyTavern.getContext();
        const response=await fetch('/api/characters/create',{method:'POST',headers:c.getRequestHeaders(),body:JSON.stringify({ch_name:'Fixture Innkeeper',description:'TEST_HIDDEN_CARD_SECRET: the owner is a ghost.',first_mes:'老板说：“楼上没有住客，但夜里别上去。”',personality:'谨慎',scenario:'旅馆前台'})});
        if(!response.ok)throw new Error(await response.text());
        await c.getCharacters();
        const id=SillyTavern.getContext().characters.findLastIndex(x=>x.name==='Fixture Innkeeper');
        if(id<0)throw new Error('Fixture character missing');
        await c.selectCharacterById(id);
        document.querySelector('#dialogue_popup_ok')?.click();
        $('#main_api').val('openai').trigger('change');
        $('#chat_completion_source').val('custom').trigger('change');
        $('#custom_api_url_text').val('http://127.0.0.1:18424/v1').trigger('input');
        $('#custom_model_id').val('fixture-model').trigger('input');
        const settings=SillyTavern.getContext().chatCompletionSettings;
        Object.assign(settings,{chat_completion_source:'custom',custom_url:'http://127.0.0.1:18424/v1',custom_model:'fixture-model',stream_openai:false});
        await fetch('/api/secrets/write',{method:'POST',headers:c.getRequestHeaders(),body:JSON.stringify({key:'api_key_custom',value:'fixture-only-key',label:'Test fixture'})});
        const secrets=await import('/scripts/secrets.js');await secrets.readSecretState();
        SillyTavern.getContext().powerUserSettings.persona_description='一个调查员，只知道可见剧情。';
        $('#api_button_openai').trigger('click');
        c.extensionSettings.dafeiyu_tavern.base='http://127.0.0.1:18424';
    })()`);
    const desktop = async (endpoint, payload = {}) => (await fetch('http://127.0.0.1:18424/api/game/sillytavern/desktop-' + endpoint, {
        method: 'POST', headers: { Origin: 'dafeiyu://desktop', 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })).json();
    async function desktopState(predicate) {
        const end = Date.now() + 25000;
        while (Date.now() < end) {
            const state = await desktop('state');
            if (predicate(state)) return state;
            await wait(120);
        }
        throw new Error('Desktop state timeout: ' + JSON.stringify(await desktop('state')));
    }
    async function command(action, extra = {}) {
        const state = await desktopState(s => s.available);
        const result = await desktop('command', { action, session: state.session, epoch: state.epoch, revision: state.revision, ...extra });
        assert.equal(result.ok, true, JSON.stringify(result));
        return result.id;
    }
    const toggle = 'document.querySelector("#dafeiyu-tavern-toolbar [data-companion]")';
    await until('SillyTavern.getContext().chat.length>0', 'fixture chat ready');
    await js('document.querySelectorAll("dialog[open] .popup-button-ok").forEach(button=>button.click())');
    await until('SillyTavern.getContext().onlineStatus!=="no_connection"', 'mock model connection ready');
    await until(toggle + '?.getAttribute("aria-checked")==="false"', 'switch default off');
    const initial = await js('SillyTavern.getContext().chat.length');
    // Start at the newest message, with native auto-scroll disabled.
    await js(`{
        SillyTavern.getContext().powerUserSettings.auto_scroll_chat_to_bottom = false;
        const chat = document.getElementById('chat');
        chat.querySelector('.mes').style.minHeight = (chat.clientHeight + 100) + 'px';
        chat.scrollTop = chat.scrollHeight;
    }`);
    async function assertVisibleMessage(index, text) {
        const view = await js(`(() => {
            const chat = document.getElementById('chat');
            const message = chat.querySelector('.mes[mesid="${index}"] .mes_text');
            const viewport = chat.getBoundingClientRect();
            const row = message?.getBoundingClientRect();
            return { text: message?.textContent.trim(), visible: !!row && row.bottom > viewport.top && row.top < viewport.bottom };
        })()`);
        assert.equal(view.text, text);
        assert.equal(view.visible, true, `Message ${index} is outside the chat viewport`);
    }
    const npcText = '老板把钥匙放在桌上：“你可以先问清楚上楼的规则。”';
    assert.equal(await js('!!document.getElementById("dafeiyu-tavern-panel")'), false);
    const off = await desktopState(s => !s.connected);
    assert.equal(off.available, false);
    assert.equal((await (await fetch('http://127.0.0.1:18424/test/status')).json()).shared_text, '{}');
    await js(toggle + '.click()');
    await desktopState(s => s.connected);
    assert.equal(await js(toggle + '.getAttribute("aria-checked")'), 'true');
    const switched = await command('auto', { enabled: false });
    await desktopState(s => s.result?.id === switched && s.auto === false);
    const input = 'document.getElementById("send_textarea")';
    await js(input + '.value="我正在写自己的行动";' + input + '.dispatchEvent(new Event("input",{bubbles:true}))');
    const drafted = await command('draft', { goal: '先问钥匙' });
    const draftState = await desktopState(s => s.result?.id === drafted && s.draft);
    assert.equal(draftState.mode, 'companion');
    assert.equal(draftState.run, null);
    assert.equal(await js('SillyTavern.getContext().chat.length'), initial);
    assert.equal(await js(input + '.value'), '我正在写自己的行动');
    const blocked = await desktop('command', { action: 'submit', session: draftState.session, epoch: draftState.epoch,
        revision: draftState.revision, draft_id: draftState.draft.id, text: '这条不应提交' });
    assert.equal(blocked.ok, false);
    await js(input + '.value="";' + input + '.dispatchEvent(new Event("input",{bubbles:true}))');
    await desktopState(s => s.can_send);
    await fetch('http://127.0.0.1:18424/test/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ npc: 2500 }) });
    const editedDraft = '我先观察钥匙的形状，再问老板。';
    const submitted = await command('submit', { draft_id: draftState.draft.id, text: editedDraft });
    await until(`!!document.querySelector('#chat .mes[mesid="${initial}"] .mes_text')`, 'player action rendered before character reply');
    assert.equal(await js('SillyTavern.getContext().chat.length'), initial + 1);
    await assertVisibleMessage(initial, editedDraft);
    await until('document.body.dataset.generating === "true"', 'native character generation started');
    const scrollPosition = () => js('document.getElementById("chat").scrollTop');
    const chatPoint = await js(`(() => {
        const rect = document.getElementById('chat').getBoundingClientRect();
        return { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) };
    })()`);
    win.webContents.debugger.attach('1.3');
    await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', {
        type: 'mouseWheel', ...chatPoint, deltaY: -1200, deltaX: 0,
    });
    await until('document.getElementById("chat").scrollTop === 0', 'wheel scrolls while the model is generating');
    assert.equal(await js('document.body.dataset.generating'), 'true');
    await desktopState(s => s.result?.id === submitted && s.mode === 'companion');
    const afterSingle = await js('SillyTavern.getContext().chat.length');
    assert.equal(afterSingle, initial + 2);
    assert.equal(await scrollPosition(), 0);
    await fetch('http://127.0.0.1:18424/test/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ npc: 0 }) });
    await js('SillyTavern.getContext().powerUserSettings.auto_scroll_chat_to_bottom = true');
    const run = await command('run', { turns: 1 });
    await desktopState(s => s.result?.id === run && s.mode === 'companion');
    assert.equal(await js('SillyTavern.getContext().chat.length'), afterSingle + 2);
    await wait(100);
    assert.equal(await scrollPosition(), 0, 'native auto-scroll should not pull a reader away');
    await js('document.getElementById("chat").scrollTop = document.getElementById("chat").scrollHeight');
    const continuous = await command('run', { turns: 2, goal: '问出规则' });
    await desktopState(s => s.result?.id === continuous && s.mode === 'companion');
    const beforeInput = await js('SillyTavern.getContext().chat.length');
    assert.equal(beforeInput, afterSingle + 6);
    await assertVisibleMessage(beforeInput - 2, '我先问老板，二楼的钥匙放在哪里。');
    await assertVisibleMessage(beforeInput - 1, npcText);
    await fetch('http://127.0.0.1:18424/test/control', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:1800}) });
    await command('run', { turns: 3 });
    await desktopState(s => s.mode === 'takeover');
    const paused = await command('pause');
    await desktopState(s => s.result?.id === paused && s.mode === 'companion');
    await wait(2000);
    assert.equal(await js('SillyTavern.getContext().chat.length'), beforeInput);
    await js(toggle + '.click()');
    await desktopState(s => !s.connected);
    await js(toggle + '.click()');
    await desktopState(s => s.connected);
    await command('off');
    await desktopState(s => !s.connected);
    assert.equal(await js(toggle + '.getAttribute("aria-checked")'), 'false');
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.join(root, 'tavern-ui.png'), image.toPNG());
    await new Promise(resolve => { win.webContents.once('did-finish-load', resolve); win.reload(); });
    await until(toggle + '?.getAttribute("aria-checked")==="false"', 'reload stays off');
    const counts = await (await fetch('http://127.0.0.1:18424/test/status')).json();
    assert.equal(counts.counts.npc, 4);
    assert.equal(counts.counts.comment, 0);
    const report = { passed: true, initial, afterSingle, finalMessages: beforeInput, counts: counts.counts, errors };
    fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report)); win.destroy(); app.exit(0);
}
app.whenReady().then(main).catch(error => { fs.writeFileSync(path.join(root, 'failure.txt'), error.stack); console.error(error.stack); app.exit(1); });
