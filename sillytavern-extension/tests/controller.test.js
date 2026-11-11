import test from 'node:test';
import assert from 'node:assert/strict';
import { TavernController } from '../controller.js';
import { buildSnapshot } from '../snapshot.js';

function gate() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function fixture() {
    let input = '', epoch = 0, mode = 'off', remaining = 0, serial = 0, draft = null;
    let messages = [{ role: 'assistant', name: '老板', text: '楼上没人。' }];
    const calls = [], sent = [];
    const snapshot = () => ({ chat_id: 'story', fingerprints: messages.map((_, i) => String(i).padStart(64, '0')),
        messages: structuredClone(messages), persona: '调查员', player_name: '玩家', signature: JSON.stringify(messages) });
    const state = () => ({ epoch, mode, remaining, revision: snapshot().signature, draft, comments: [], memory: {} });
    const f = { calls, sent, snapshot, setInput(value) { input = value; },
        change() { messages[0].text = '老板改口了。'; },
        async api(operation, data) {
            calls.push(operation);
            if (operation === 'connect') return { token: 'test', ...state() };
            if (operation === 'mode') { mode = data.mode; remaining = data.turns || 0; epoch++; draft = null; }
            if (operation === 'pause') { mode = 'companion'; epoch++; draft = null; }
            if (operation === 'draft') {
                if (remaining <= 0) throw new Error('No budget');
                if (f.delay) await f.delay.promise;
                draft = { id: String(++serial), text: '我问钥匙在哪里。', revision: snapshot().signature, claimed: false };
            }
            if (operation === 'claim') {
                if (!draft || draft.claimed) throw new Error('Already claimed');
                draft.claimed = true; remaining--;
                if (f.claimDelay) await f.claimDelay.promise;
            }
            if (operation === 'comment') return { skipped: true };
            return state();
        },
        async submit(text, { actionId, guard }) {
            assert.equal(input, ''); assert.equal(guard(), true);
            sent.push(text); messages.push({ role: 'user', name: '玩家', text, action_id: actionId });
            if (!f.noReply) messages.push({ role: 'assistant', name: '老板', text: '钥匙在前台。' });
            draft = null;
        },
    };
    const controller = new TavernController({ api: (...args) => f.api(...args), capture: async () => snapshot(),
        getInput: () => input, isBusy: () => false, submit: (...args) => f.submit(...args) });
    return { f, controller };
}

test('off is passive and generated draft does not submit or overwrite human input', async () => {
    const { f, controller: c } = fixture();
    await c.heartbeat(); await c.observe(); assert.deepEqual(f.calls, []);
    await c.draftOnly('试探老板'); assert.equal(f.sent.length, 0); assert.ok(c.draft);
    await c.submitDraft('我改成问楼上钥匙。'); assert.deepEqual(f.sent, ['我改成问楼上钥匙。']);
    assert.equal(c.mode, 'companion'); assert.equal(c.run, null);
});
test('finite takeover submits exactly the authorized number and returns control', async () => {
    for (const turns of [1, 3, 5]) {
        const { f, controller: c } = fixture();
        await c.runTurns(turns, '问出真相');
        assert.equal(f.sent.length, turns); assert.equal(c.run, null); assert.equal(c.mode, 'companion');
        assert.equal(f.calls.filter(x => x === 'claim').length, turns);
    }
});
test('preexisting human input prevents even starting takeover', async () => {
    const { f, controller: c } = fixture(); f.setInput('我正在写自己的行动');
    await assert.rejects(c.runTurns(3), /不会覆盖/); assert.equal(f.sent.length, 0); assert.deepEqual(f.calls, []);
});
test('pause discards a late draft even if transport ignores abort', async () => {
    const { f, controller: c } = fixture(); f.delay = gate();
    const task = c.runTurns(3).catch(error => error);
    while (!f.calls.includes('draft')) await new Promise(r => setTimeout(r, 1));
    await c.stop(); f.delay.resolve(); await task;
    assert.equal(f.sent.length, 0); assert.equal(c.run, null); assert.equal(c.draft, null);
});
test('editing the scene during action generation prevents stale submission', async () => {
    const { f, controller: c } = fixture(); f.delay = gate();
    const task = c.runTurns(1).catch(error => error);
    while (!f.calls.includes('draft')) await new Promise(r => setTimeout(r, 1));
    f.change(); f.delay.resolve(); await task;
    assert.equal(f.sent.length, 0); assert.equal(c.run, null);
});
test('typing after claim prevents sending and never retries the claimed action', async () => {
    const { f, controller: c } = fixture(); f.claimDelay = gate();
    const task = c.runTurns(3).catch(error => error);
    while (!f.calls.includes('claim')) await new Promise(r => setTimeout(r, 1));
    f.setInput('我自己来'); await c.stop(); f.claimDelay.resolve(); await task;
    assert.equal(f.sent.length, 0); assert.equal(f.calls.filter(x => x === 'claim').length, 1);
});
test('a missing NPC reply stops continuous play after one submission', async () => {
    const { f, controller: c } = fixture(); f.noReply = true;
    await assert.rejects(c.runTurns(3), /未收到/); assert.equal(f.sent.length, 1); assert.equal(c.run, null);
});
test('slash commands cannot be submitted as player actions', async () => {
    const { f, controller: c } = fixture(); await c.draftOnly();
    await assert.rejects(c.submitDraft('/run something'), /斜杠命令/); assert.equal(f.sent.length, 0);
});
test('Tavern macros cannot be executed through generated actions', async () => {
    const { f, controller: c } = fixture(); await c.draftOnly();
    await assert.rejects(c.submitDraft('{{setvar::hidden::x}}'), /或宏/); assert.equal(f.sent.length, 0);
});
test('snapshot excludes system, hidden card fields and reasoning; fingerprints track branch changes', async () => {
    const context = { characterId: 1, chatId: 'one', name1: '玩家', characters: [{ description: 'HIDDEN_CARD_SECRET' }],
        powerUserSettings: { persona_description: '调查员' }, chat: [
            { is_system: true, mes: 'SECRET_SYSTEM' },
            { is_user: false, name: '老板', mes: '可见剧情', swipe_id: 0, extra: { reasoning: 'SECRET_REASONING' } },
        ] };
    const first = await buildSnapshot(context, 'http://localhost:8000');
    assert.equal(first.messages.length, 1); assert.doesNotMatch(JSON.stringify(first), /SECRET/);
    context.chat[1].swipe_id = 1;
    const second = await buildSnapshot(context, 'http://localhost:8000');
    assert.notEqual(first.signature, second.signature);
});
