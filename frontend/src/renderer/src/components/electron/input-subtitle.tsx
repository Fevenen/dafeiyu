import { LuHand, LuMic, LuMicOff, LuSend, LuX } from 'react-icons/lu';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useInputSubtitle } from '@/hooks/electron/use-input-subtitle';
import { usePetDock } from '@/hooks/electron/use-pet-dock';
import { useForceIgnoreMouse } from '@/hooks/utils/use-force-ignore-mouse';
import { ScreenControls } from '@/components/screen/screen-controls';
import { useScreenCompanion } from '@/hooks/electron/use-screen-companion';
import { speechReadingTime, useSpeechText } from '@/hooks/utils/use-speech-text';
import { petDisplayText } from '@/utils/pet-display-text';
import { PetTavernControls, usePetTavern } from './pet-tavern-controls';
import './pet-dock.css';

const hover = (id: string, inside: boolean) => (window.api as any)?.updateComponentHover?.(id, inside);
const keyboardFocus = (focused: boolean) => window.electron?.ipcRenderer.send('pet-keyboard-focus', focused);
const editable = 'input:not([type=button]):not([type=checkbox]), textarea, select, [contenteditable="true"]';
const chatStatus = { idle: '', 'thinking-speaking': '正在回复', listening: '在听', waiting: '', interrupted: '', loading: '载入中' };
const noComments: NonNullable<ReturnType<typeof usePetTavern>['state']['comments']> = [];

export function InputSubtitle() {
  const chat = useInputSubtitle();
  const tavern = usePetTavern();
  const speechText = useSpeechText();
  const { forceIgnoreMouse } = useForceIgnoreMouse();
  const [chatEnabled, setChatEnabled] = useState(true);
  const [chatVisible, setChatVisible] = useState(false);
  const [chatHover, setChatHover] = useState(false);
  const [chatFocus, setChatFocus] = useState(false);
  const [commentBubble, setCommentBubble] = useState<{ id: string; text: string } | null>(null);
  const seenComments = useRef<{ session?: string; ids: string[] }>({ ids: [] });
  const { placement, modelHover } = usePetDock();
  const dockRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const expanded = chatHover || chatFocus;
  const chatMessages = chat.messages.filter(message => message.type !== 'tool_call_status')
    .map(message => message.role === 'ai' ? { ...message, content: petDisplayText(message.content) } : message)
    .filter(message => message.content.trim());
  const speaking = chat.aiState === 'thinking-speaking';
  const latest = [...chatMessages].reverse().find((message, index) => message.role === 'ai' && (!speaking || index > 0));
  const preview = latest?.content.trim().split(/\r?\n(?:[^\S\r\n]*\r?\n)+/).at(-1)?.trim();
  const companion = tavern.state.connected;
  const screenCompanion = useScreenCompanion(!companion && !tavern.state.waiting && chat.aiState === 'idle' && !chat.inputValue.trim() && !chatFocus);
  const autoComment = companion ? tavern.state.auto === true : screenCompanion.enabled;
  const comments = companion ? tavern.state.comments || noComments : noComments;
  const commentSession = companion ? tavern.state.session : undefined;
  const gameNotes = comments.map(note => ({ ...note, text: petDisplayText(note.text) }))
    .filter(note => note.text && !chatMessages.some(message => message.role === 'ai' && message.content.includes(note.text)));
  const bubble = speechText || commentBubble?.text;
  const status = speechText ? '正在说话' : chatStatus[chat.aiState];

  useEffect(() => {
    const previous = seenComments.current;
    seenComments.current = { session: commentSession, ids: comments.map(note => note.id) };
    if (previous.session !== commentSession) {
      setCommentBubble(null);
      return;
    }
    const latestComment = comments.filter(note => note.kind === 'comment' && !previous.ids.includes(note.id)).at(-1);
    if (!latestComment) return;
    const text = petDisplayText(latestComment.text);
    if (text && !chat.messages.some(message => message.role === 'ai' && petDisplayText(message.content).includes(text))) {
      setCommentBubble({ id: latestComment.id, text });
    }
  }, [commentSession, comments, chat.messages]);

  useEffect(() => {
    if (!commentBubble) return;
    if (speechText && commentBubble.text.includes(speechText)) {
      setCommentBubble(null);
      return;
    }
    const timer = window.setTimeout(() => setCommentBubble(null), speechReadingTime(commentBubble.text));
    return () => window.clearTimeout(timer);
  }, [commentBubble, speechText]);

  useEffect(() => {
    if (!chatEnabled || forceIgnoreMouse) {
      setChatVisible(false);
      setChatHover(false);
      setChatFocus(false);
      hover('input-subtitle', false);
      return undefined;
    }
    if (modelHover || chatHover || chatFocus) {
      setChatVisible(true);
      return undefined;
    }
    const hide = window.setTimeout(() => setChatVisible(false), 300);
    return () => window.clearTimeout(hide);
  }, [chatEnabled, forceIgnoreMouse, modelHover, chatHover, chatFocus]);

  useEffect(() => {
    const requestKeyboard = (event: PointerEvent) => {
      if (event.button !== 0 || !(event.target instanceof Element)) return;
      const field = event.target.closest(editable);
      if (field && (dockRef.current?.contains(field) || field.closest('[data-pet-dock-popover]'))) keyboardFocus(true);
    };
    const loseKeyboard = () => {
      if (document.activeElement instanceof HTMLElement && document.activeElement.matches(editable)) document.activeElement.blur();
      setChatFocus(false);
    };
    const releaseKeyboard = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement && event.target.matches(editable)
        && (dockRef.current?.contains(event.target) || event.target.closest('[data-pet-dock-popover]'))) {
        // Allow a click on Send or a select option to finish before releasing activation.
        window.setTimeout(() => {
          if (!(document.activeElement instanceof HTMLElement) || !document.activeElement.matches(editable)) keyboardFocus(false);
        }, 150);
      }
    };
    document.addEventListener('pointerdown', requestKeyboard, true);
    document.addEventListener('focusout', releaseKeyboard);
    window.addEventListener('blur', loseKeyboard);
    return () => {
      document.removeEventListener('pointerdown', requestKeyboard, true);
      document.removeEventListener('focusout', releaseKeyboard);
      window.removeEventListener('blur', loseKeyboard);
      keyboardFocus(false);
    };
  }, []);

  const dismiss = useCallback(() => {
    hover('input-subtitle', false);
    keyboardFocus(false);
    setChatHover(false);
    setChatFocus(false);
    setChatVisible(false);
  }, []);
  useEffect(() => {
    const open = () => { setChatEnabled(true); setChatVisible(true); };
    const close = () => { setChatEnabled(false); dismiss(); };
    const toggle = (window.api as any)?.onToggleInputSubtitle(chatEnabled ? close : open);
    (window as any).inputSubtitle = { open, close };
    return () => { toggle?.(); delete (window as any).inputSubtitle; };
  }, [chatEnabled, dismiss]);

  useEffect(() => () => {
    hover('input-subtitle', false);
    hover('pet-toolbar', false);
  }, []);

  useLayoutEffect(() => { followLatest.current = true; }, [expanded, chat.currentHistoryUid]);
  useLayoutEffect(() => {
    const history = historyRef.current;
    if (history && followLatest.current) history.scrollTop = history.scrollHeight;
  }, [expanded, chat.currentHistoryUid, chat.messages, comments.length, placement.maxHeight]);

  const { left, width, anchor, up, align, maxHeight, speech } = placement;
  return <>
    {bubble && speech.maxHeight > 28 && <div className="pet-speech-bubble" data-side={speech.side} role="status"
      aria-label="大肥鱼正在说" style={{ left: speech.left, top: speech.top, maxWidth: speech.maxWidth }}>
      <div className="pet-speech-text" style={{ maxHeight: speech.maxHeight }}>{bubble}</div>
    </div>}
    <div ref={dockRef} data-align={align} className={`pet-dock${up ? ' pet-dock-up' : ''}${forceIgnoreMouse ? ' pet-dock-passthrough' : ''}`} style={{
      left, width, top: up ? undefined : anchor, bottom: up ? window.innerHeight - anchor : undefined,
      maxHeight,
    }}>
      <div className={`pet-toolbar pet-dock-interactive${companion ? ' pet-toolbar-tavern' : ''}`}
        onMouseEnter={() => hover('pet-toolbar', true)}
        onMouseLeave={() => hover('pet-toolbar', false)}>
        <div className="pet-tavern-row pet-toolbar-main">
          <ScreenControls compact companion onDescribe={chat.describeScreen} />
          <button type="button" className="pet-pill" role="switch" aria-checked={autoComment}
            title={companion ? '自动点评酒馆剧情' : '开启屏幕陪玩后，画面明显变化时自动点评'}
            disabled={companion && (tavern.sending || !!tavern.state.command)}
            onClick={() => {
              if (companion) void tavern.command('auto', { enabled: !autoComment });
              else screenCompanion.setEnabled(!autoComment);
            }}><span className="pet-switch" aria-hidden="true" />自动点评</button>
        </div>
        {companion && <PetTavernControls {...tavern} />}
      </div>
      {chatEnabled && chatVisible && !forceIgnoreMouse && <div className="pet-chat pet-dock-interactive"
        aria-label="桌宠聊天"
        onMouseEnter={() => { hover('input-subtitle', true); setChatHover(true); }}
        onMouseLeave={() => { hover('input-subtitle', false); setChatHover(false); }}
        onFocus={e => { if ((e.target as HTMLElement).matches(editable)) setChatFocus(true); }}
        onBlur={e => { if (!(e.relatedTarget instanceof HTMLElement) || !e.relatedTarget.matches(editable)) setChatFocus(false); }}
        onKeyDown={e => {
          if (e.key === 'Escape' && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            (e.target as HTMLElement).blur(); dismiss();
          }
        }}>
        {expanded ? <>
          <header className="pet-chat-header">
            <div className="pet-chat-title"><strong>大肥鱼</strong>{status && <span>{status}</span>}</div>
            <div className="pet-chat-tools">
              <button type="button" className="pet-icon-button" aria-label="切换麦克风" aria-pressed={chat.micOn} title="切换麦克风" onClick={chat.handleMicToggle}>
                {chat.micOn ? <LuMic size={15} /> : <LuMicOff size={15} />}
              </button>
              <button type="button" className="pet-icon-button" aria-label="打断大肥鱼" title="打断大肥鱼" onClick={chat.handleInterrupt}><LuHand size={15} /></button>
              <button type="button" className="pet-icon-button" aria-label="收起聊天" title="收起聊天" onClick={dismiss}><LuX size={16} /></button>
            </div>
          </header>
          <div ref={historyRef} className="pet-chat-history" aria-label="桌宠聊天记录" tabIndex={0}
            onScroll={() => {
              const history = historyRef.current;
              if (history) followLatest.current = history.scrollHeight - history.clientHeight - history.scrollTop < 28;
            }}>
            {chatMessages.map((message, index) => <div className={`pet-chat-message pet-chat-${message.role}`} key={message.id || index}>
              <strong>{message.role === 'human' ? '你' : message.name || '大肥鱼'}</strong>
              <div>{message.content}</div>
            </div>)}
            {gameNotes.length > 0 && <section className="pet-chat-notes" aria-label="近期酒馆点评">
              <strong>近期酒馆点评</strong>
              {gameNotes.map(note => <div key={note.id}>{note.text}</div>)}
            </section>}
          </div>
          <div className="pet-chat-composer">
            <input aria-label="发给大肥鱼" value={chat.inputValue} onChange={chat.handleInputChange} onKeyDown={chat.handleKeyPress}
              onCompositionStart={chat.handleCompositionStart} onCompositionEnd={chat.handleCompositionEnd} placeholder="和大肥鱼聊聊…" />
            <button type="button" className="pet-icon-button pet-chat-send" aria-label="发送" title="发送" onClick={chat.handleSend}><LuSend size={16} /></button>
          </div>
        </> : <div className="pet-chat-preview">{preview || '和大肥鱼聊聊…'}</div>}
      </div>}
    </div>
  </>;
}
