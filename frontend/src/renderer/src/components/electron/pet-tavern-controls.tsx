import { useEffect, useRef, useState } from 'react';
import { LuChevronDown, LuLogOut, LuPencil, LuPlay } from 'react-icons/lu';
import { useWebSocket } from '@/context/websocket-context';

type TavernState = {
  ok: boolean; connected: boolean; available?: boolean; waiting?: boolean; session?: string;
  mode?: 'off' | 'companion' | 'takeover';
  epoch?: number; revision?: string; auto?: boolean; status?: string; can_send?: boolean;
  run?: { total: number; completed: number; automatic: boolean } | null;
  draft?: { id: string; text: string } | null;
  command?: string; result?: { id: string; error: string };
  comments?: { id: string; text: string; kind?: 'comment' | 'answer' }[];
};

export function usePetTavern() {
  const { baseUrl } = useWebSocket();
  const [state, setState] = useState<TavernState>({ ok: false, connected: false });
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const requestPending = useRef(false);
  const requested = useRef('');
  const update = useRef<() => void>();

  useEffect(() => {
    const ipc = window.electron?.ipcRenderer;
    if (!ipc) return undefined;
    let closed = false, polling = false;
    const poll = async () => {
      if (closed || polling) return;
      polling = true;
      try {
        const value: TavernState = await ipc.invoke('pet-tavern-controls', baseUrl, 'state');
        if (closed) return;
        setState(value);
        if (requested.current && value.result?.id === requested.current) {
          setError(value.result.error);
          requested.current = '';
        }
      } catch {
        if (!closed) setState({ ok: false, connected: false });
      } finally { polling = false; }
    };
    update.current = poll;
    void poll();
    const timer = window.setInterval(poll, 750);
    return () => { closed = true; window.clearInterval(timer); update.current = undefined; };
  }, [baseUrl]);

  const command = async (action: string, values = {}) => {
    const ipc = window.electron?.ipcRenderer;
    if (!ipc || requestPending.current || !state.connected) return false;
    requestPending.current = true;
    setSending(true);
    setError('');
    try {
      const result = await ipc.invoke('pet-tavern-controls', baseUrl, 'command', {
        action, session: state.session, epoch: state.epoch, revision: state.revision, ...values,
      });
      if (!result.ok) throw new Error(result.error);
      requested.current = result.id;
      setState(previous => previous.session === state.session ? { ...previous, command: action } : previous);
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : '酒馆操作未完成。');
      return false;
    } finally {
      requestPending.current = false;
      setSending(false);
      update.current?.();
    }
  };
  return { state, error, sending, command };
}

export function PetTavernControls({ state, error, sending, command }: ReturnType<typeof usePetTavern>) {
  const [form, setForm] = useState<'draft' | 'run' | null>(null);
  const [turns, setTurns] = useState(1);
  const [goal, setGoal] = useState('');
  const [action, setAction] = useState('');
  const busy = sending || !!state.command || !!state.run || state.mode === 'takeover';
  const running = !!state.run || state.mode === 'takeover' || ['run', 'submit', 'pause'].includes(state.command || '');
  const draftId = state.draft?.id;
  const draftText = state.draft?.text;

  useEffect(() => { setAction(draftText || ''); }, [draftId, draftText]);
  useEffect(() => { setForm(null); setGoal(''); setTurns(1); }, [state.session, state.revision, state.connected]);

  return (
    <section className="pet-tavern" aria-label="酒馆陪玩">
      <div className="pet-tavern-row pet-tavern-actions">
        <span className="pet-tavern-label">酒馆</span>
        <button type="button" className="pet-pill" disabled={busy} aria-expanded={form === 'draft' && !busy}
          onClick={() => setForm(form === 'draft' ? null : 'draft')}><LuPencil /> 草稿</button>
        <button type="button" className="pet-pill pet-primary" disabled={busy || !state.can_send} aria-expanded={form === 'run' && !busy}
          onClick={() => { setTurns(1); setForm(form === 'run' ? null : 'run'); }}><LuPlay />代玩 <LuChevronDown /></button>
        {running && <button type="button" className="pet-pill pet-stop" disabled={sending || state.command === 'pause'}
          onClick={() => { setForm(null); void command('pause'); }}>我来</button>}
        <button type="button" className="pet-pill pet-exit" aria-label="退出酒馆陪玩" title="退出酒馆陪玩"
          disabled={sending || state.command === 'off'} onClick={() => { void command('off'); }}><LuLogOut /></button>
      </div>
      <div className="pet-tavern-status" data-tone={error ? 'error' : running ? 'running' : 'ready'} role="status">
        {error || (state.command === 'draft' ? '正在生成草稿…' :
          (state.run ? `${state.run.completed}/${state.run.total} 轮 · ` : '') + (state.status || '酒馆陪玩中'))}
      </div>
      {form && !busy && <div className="pet-tavern-form">
        <label className="pet-tavern-goal">
          <span>接管目标 <small>（可不填）</small></span>
          <textarea value={goal} maxLength={1000} onChange={e => setGoal(e.target.value)} />
        </label>
        {form === 'run' && <label>轮数 <select value={turns} onChange={e => setTurns(Number(e.target.value))}>
          {[1, 2, 3, 4, 5].map(n => <option key={n}>{n}</option>)}
        </select></label>}
        <button type="button" className="pet-pill pet-primary" onClick={async () => {
          if (await command(form, { goal, turns })) setForm(null);
        }}>{form === 'draft' ? '生成草稿' : '开始代玩'}</button>
      </div>}
      {state.draft && <div className="pet-tavern-form">
        <textarea aria-label="玩家行动草稿" value={action} maxLength={2000} onChange={e => setAction(e.target.value)} />
        <button type="button" className="pet-pill pet-primary" disabled={!action.trim() || sending || !!state.command || !state.can_send}
          onClick={() => { void command('submit', { text: action, draft_id: state.draft?.id }); }}>提交草稿</button>
        <button type="button" className="pet-pill" disabled={sending || state.command === 'pause'} onClick={() => { void command('pause'); }}>取消</button>
      </div>}
    </section>
  );
}
