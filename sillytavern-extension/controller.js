/** Control ownership and round limits; no SillyTavern globals or real-world tools. */
export class TavernController {
    constructor({ api, capture, getInput, isBusy, submit, onState = () => {}, voice = () => false, canSend = () => true, timeout = 90000 }) {
        Object.assign(this, { api, capture, getInput, isBusy, submit, onState, voice, canSend, timeout });
        this.mode = 'off'; this.epoch = 0; this.generation = 0; this.connected = false;
        this.requests = new Set(); this.controls = Promise.resolve(); this.syncs = Promise.resolve();
        this.draft = null; this.run = null; this.snapshot = null; this.statusText = '已关闭';
    }
    emit() { this.onState(this); }
    current(g) { return g === this.generation && this.mode !== 'off'; }
    accept(state) { this.epoch = state.epoch; this.server = state; this.emit(); return state; }
    control(operation, data = {}) {
        const next = this.controls.catch(() => {}).then(() => this.api(operation, data));
        this.controls = next; return next;
    }
    async rpc(operation, data = {}) {
        const aborter = new AbortController(); this.requests.add(aborter);
        try { return await this.api(operation, { epoch: this.epoch, ...data }, aborter.signal); }
        finally { this.requests.delete(aborter); }
    }
    async enable() {
        await this.capture(); // A missing chat never enables observation.
        const g = ++this.generation;
        this.mode = 'companion'; this.statusText = '正在连接'; this.emit();
        try {
            if (!this.connected) { await this.control('connect'); this.connected = true; }
            if (!this.current(g)) return;
            const state = await this.control('mode', { mode: 'companion' });
            if (!this.current(g)) return;
            this.accept(state); await this.sync();
            if (this.current(g)) { this.statusText = '陪玩中'; this.emit(); }
        } catch (error) { if (this.current(g)) { this.mode = 'off'; this.emit(); } throw error; }
    }
    async stop(off = false, reason = '控制权已交还', clear = false) {
        const g = ++this.generation;
        this.run = null; this.draft = null;
        for (const request of this.requests) request.abort();
        this.actionAbort?.abort();
        this.mode = off ? 'off' : (this.connected ? 'companion' : 'off');
        this.statusText = off ? '已关闭' : reason; this.emit();
        if (!this.connected) return;
        try {
            const state = await this.control(off ? 'mode' : 'pause', off ? { mode: 'off' } : { clear });
            if (g === this.generation) this.accept(state);
        } finally { if (off && g === this.generation) this.connected = false; }
    }
    async invalidate(reason = '剧情已变化，接管已暂停') {
        if (this.mode === 'off') return;
        await this.stop(false, reason, true);
        await this.sync();
    }
    sync() {
        const g = this.generation;
        const next = this.syncs.catch(() => {}).then(async () => {
            if (!this.current(g)) throw new Error('陪玩已暂停');
            const snapshot = await this.capture();
            if (!this.current(g)) throw new Error('陪玩已暂停');
            const state = await this.rpc('context', snapshot);
            if (!this.current(g)) throw new Error('旧剧情结果已丢弃');
            this.snapshot = snapshot; this.accept(state); return snapshot;
        });
        this.syncs = next; return next;
    }
    async heartbeat() {
        if (this.mode === 'off' || !this.connected) return;
        const g = this.generation, state = await this.rpc('status');
        if (!this.current(g)) return;
        if (state.mode === 'off' || (this.mode === 'takeover' && state.mode !== 'takeover')) {
            await this.stop(state.mode === 'off', '连接或接管已到期，请重新开启'); return;
        }
        this.accept(state);
        if (!this.run && !this.draft && !this.isBusy()) await this.syncIfChanged();
    }
    async syncIfChanged() {
        if (this.mode === 'off') return;
        const g = this.generation, latest = await this.capture();
        if (this.current(g) && (!this.snapshot || latest.chat_id !== this.snapshot.chat_id ||
            latest.signature !== this.snapshot.signature)) await this.sync();
    }
    async sceneFinished(autoComment = false) {
        if (this.mode === 'off' || this.run) return;
        await this.sync(); // Synchronization never depends on whether the fish speaks.
        if (autoComment) await this.observe(false);
    }
    async observe(force = false) {
        if (this.mode === 'off') return;
        const g = this.generation;
        await this.sync();
        if (!this.current(g) || this.isBusy()) return;
        const result = await this.rpc('comment', { voice: this.voice(), force });
        if (this.current(g) && !result.skipped) this.accept(result);
    }
    async ask(text) {
        if (this.mode === 'off') await this.enable();
        const g = this.generation;
        await this.sync();
        const result = await this.rpc('question', { text, voice: this.voice() });
        if (this.current(g)) this.accept(result);
    }
    assertReady() {
        const reason = this.canSend();
        if (reason !== true) throw new Error(reason || '酒馆暂不能提交行动');
        if (this.getInput().trim()) throw new Error('酒馆输入框已有你的文字，请先处理；大肥鱼不会覆盖。');
        if (this.isBusy()) throw new Error('酒馆正在生成，请等待结束。');
    }
    async grant(turns) {
        if (!Number.isInteger(turns) || turns < 1 || turns > 5) throw new Error('接管轮数必须在1到5之间');
        this.assertReady();
        if (this.mode === 'off') await this.enable();
        if (this.run || this.draft) await this.stop();
        await this.sync();
        const g = this.generation, state = await this.control('mode', { mode: 'takeover', turns });
        if (!this.current(g)) throw new Error('接管已取消');
        this.mode = 'takeover'; this.accept(state);
        this.run = { total: turns, completed: 0, goal: '', automatic: false };
        return g;
    }
    async generateDraft(goal, g) {
        this.assertReady();
        await this.sync();
        if (!this.current(g)) throw new Error('接管已暂停');
        const snapshot = this.snapshot;
        this.statusText = `正在准备第${this.run.completed + 1}/${this.run.total}轮`; this.emit();
        const state = await this.rpc('draft', { revision: this.server.revision, goal });
        if (!this.current(g)) throw new Error('旧行动已丢弃');
        const latest = await this.capture();
        if (!this.current(g) || latest.signature !== snapshot.signature || this.getInput().trim()) {
            await this.stop(false, '剧情或输入已变化，旧行动已丢弃'); throw new Error('行动已过时，请重新生成');
        }
        this.draft = { ...state.draft, signature: snapshot.signature, chat_id: snapshot.chat_id };
        this.accept(state); this.statusText = '行动草稿已就绪，可修改后提交'; this.emit();
    }
    async draftOnly(goal = '') {
        const g = await this.grant(1);
        this.run.goal = goal;
        try { await this.generateDraft(goal, g); }
        catch (error) { if (this.current(g)) await this.stop(false, '生成失败，已交还控制权'); throw error; }
    }
    async submitDraft(text = this.draft?.text) {
        if (this.manualSubmitting) return;
        if (!this.draft || !this.run) throw new Error('没有可提交的草稿');
        if (this.run.automatic) throw new Error('自动接管进行中，请先点“我来”');
        this.manualSubmitting = true;
        const g = this.generation;
        try { await this.commit(text, g); if (this.current(g)) await this.stop(false, '本轮结束，控制权已交还'); }
        catch (error) { if (this.current(g)) await this.stop(false, '提交未完成，已暂停；不会自动重发'); throw error; }
        finally { this.manualSubmitting = false; }
    }
    async commit(text, g) {
        this.assertReady();
        if (typeof text !== 'string' || !text.trim() || text.length > 2000 || text.trimStart().startsWith('/') || /\{\{|\}\}/.test(text)) {
            throw new Error('行动应为1到2000字的剧情文字，不能是酒馆斜杠命令或宏');
        }
        const draft = this.draft, before = await this.capture();
        if (!this.current(g) || before.signature !== draft.signature) throw new Error('剧情已变化，不能提交旧行动');
        await this.rpc('claim', { draft_id: draft.id, revision: draft.revision });
        const latest = await this.capture();
        if (!this.current(g) || latest.signature !== draft.signature || this.getInput().trim()) throw new Error('提交前剧情或输入发生变化，未发送行动');
        this.draft = null; this.statusText = `接管第${this.run.completed + 1}/${this.run.total}轮，等待角色回复`; this.emit();
        this.actionAbort = new AbortController();
        let timer;
        try {
            await Promise.race([
                this.submit(text.trim(), { actionId: draft.id, guard: () => this.current(g), signal: this.actionAbort.signal }),
                new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('等待酒馆回复超时，已暂停')), this.timeout); }),
            ]);
        } finally { clearTimeout(timer); }
        if (!this.current(g)) return;
        const after = await this.capture();
        const index = after.messages.findIndex(message => message.action_id === draft.id);
        if (after.chat_id !== before.chat_id || index < 0 || !after.messages.slice(index + 1).some(message => message.role === 'assistant')) {
            throw new Error('未收到本轮对应的角色回复，已暂停；不会重复发送');
        }
        this.run.completed += 1;
        await this.sync();
    }
    async runTurns(turns, goal = '') {
        const g = await this.grant(turns);
        this.run.goal = goal;
        this.run.automatic = true;
        try {
            while (this.current(g) && this.run && this.run.completed < this.run.total) {
                await this.generateDraft(goal, g);
                if (!this.current(g)) return;
                await this.commit(this.draft.text, g);
            }
            if (this.current(g)) { await this.stop(false, '授权轮数已完成，控制权已交还'); await this.observe(false); }
        } catch (error) { if (this.current(g)) await this.stop(false, '接管已暂停；不会自动重发'); throw error; }
    }
}
