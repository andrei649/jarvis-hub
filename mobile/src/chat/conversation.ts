import { resumeSession, streamChat, type HistoryTurn } from '../api/client';
import { loadConversation, saveConversation, type SavedConversation } from '../storage/chat';
import type { ServerConfig } from '../storage/settings';
import type { ChatMessage } from './types';
import type { TurnOutcome } from './turnOutcome';

export type ConversationState = SavedConversation & { ready: boolean; sending: boolean; turnOutcome: TurnOutcome | null };
let sequence = 0;
const nextId = () => `m${Date.now()}_${sequence++}`;
const validId = (id: unknown): id is string => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id);

function visibleTurns(turns: HistoryTurn[]): ChatMessage[] {
  return turns.filter(t => t && (t.role === 'user' || t.role === 'assistant') && typeof t.content === 'string')
    .map(t => ({ id: nextId(), role: t.role as ChatMessage['role'], text: t.content,
      ...(typeof t.agent_id === 'string' ? { agent: t.agent_id } : {}) }));
}

/** One mounted connection owns hydration, selection and all its in-flight callbacks. */
export class Conversation {
  state: ConversationState = { sessionId: null, messages: [], ready: false, sending: false, turnOutcome: null };
  private epoch = 0;
  private metricGeneration = 0;
  private active = true;
  private cancel: (() => void) | null = null;

  get revision(): number { return this.epoch; }

  constructor(private config: ServerConfig, private scope: string,
    private changed: (state: ConversationState) => void) {}

  private publish(update: Partial<ConversationState>, persist = false) {
    if (!this.active) return;
    this.state = { ...this.state, ...update };
    this.changed(this.state);
    if (persist && this.state.ready) void saveConversation(this.scope,
      { sessionId: this.state.sessionId, messages: this.state.messages });
  }

  async hydrate() {
    const epoch = this.epoch;
    const saved = await loadConversation(this.scope);
    if (this.active && epoch === this.epoch) this.publish({ ...saved, ready: true, turnOutcome: null });
  }

  resume(sessionId: string, turns: HistoryTurn[]) {
    if (!this.active || !validId(sessionId) || !Array.isArray(turns)) return;
    this.invalidate();
    this.publish({ sessionId, messages: visibleTurns(turns), ready: true, sending: false, turnOutcome: null }, true);
  }

  private invalidate() {
    ++this.epoch;
    const cancel = this.cancel;
    this.cancel = null;
    cancel?.();
  }

  stop() {
    this.invalidate();
    this.publish({ sending: false, turnOutcome: null, messages: this.state.messages
      .map(m => m.pending ? { ...m, pending: false } : m) }, true);
  }

  dispose() {
    this.active = false;
    this.invalidate();
    this.state = { ...this.state, turnOutcome: null };
  }

  /** Agent selection revokes only the readout, preserving in-flight text settlement. */
  clearTurnOutcome() {
    if (!this.active) return;
    ++this.metricGeneration;
    this.publish({ turnOutcome: null });
  }

  /** The selected-image sender shares the text turn lock and epoch. No image bytes enter state. */
  beginSelectedImage(sessionId: string, expectedRevision: number): {
    signal: AbortSignal; current: () => boolean; release: () => void; cancel: () => void;
    commit: (prompt: string, agent: string, count: number, model: string, answer: string) => boolean;
  } | null {
    if (!this.active || !this.state.ready || this.state.sending || !validId(sessionId)
      || this.state.sessionId !== sessionId || this.epoch !== expectedRevision) return null;
    this.invalidate();
    const epoch = this.epoch;
    const controller = new AbortController();
    this.cancel = () => controller.abort();
    const current = () => this.active && this.epoch === epoch && this.state.sessionId === sessionId;
    this.publish({ sending: true, turnOutcome: null });
    const release = () => {
      if (!current()) return;
      this.cancel = null;
      this.publish({ sending: false });
    };
    const commit = (prompt: string, agent: string, count: number, _model: string, answer: string) => {
      if (!current() || !this.state.sending || !prompt.trim() || !answer.trim()
        || !Number.isInteger(count) || count < 1 || count > 8) return false;
      this.cancel = null;
      const marker = count === 1 ? 'image' : 'images';
      this.publish({ sending: false, messages: [...this.state.messages,
        { id: nextId(), role: 'user', text: `${prompt}\n[${count} ${marker} attached]` },
        { id: nextId(), role: 'assistant', text: answer, agent }] }, true);
      return true;
    };
    const cancel = () => { if (current()) this.stop(); };
    return { signal: controller.signal, current, release, cancel, commit };
  }

  send(message: string, agent: string): boolean {
    const text = message.trim();
    if (!this.active || !this.state.ready || this.state.sending || !text) return false;
    this.invalidate();
    const epoch = this.epoch;
    const metricGeneration = this.metricGeneration;
    const botId = nextId();
    const selected = this.state.sessionId;
    const current = () => this.active && epoch === this.epoch;
    const patch = (update: (m: ChatMessage) => ChatMessage) => {
      if (current()) this.publish({ messages: this.state.messages.map(m => m.id === botId ? update(m) : m) });
    };
    this.publish({ sending: true, turnOutcome: null, messages: [...this.state.messages,
      { id: nextId(), role: 'user', text }, { id: botId, role: 'assistant', text: '', pending: true, agent }] });
    const cancel = streamChat(this.config, text, agent, {
      onStart: responder => patch(m => ({ ...m, agent: responder || agent })),
      onToken: token => patch(m => ({ ...m, text: m.text + token })),
      onDone: (full, sessionId, outcome) => {
        if (!current()) return;
        this.cancel = null;
        const changed = validId(sessionId) && sessionId !== selected;
        const rollover = changed && ['/new', '/reset', '/undo'].includes(text);
        const messages = this.state.messages.map(m => m.id === botId ? { ...m, text: full || m.text, pending: false } : m);
        this.publish({ sending: false, sessionId: validId(sessionId) ? sessionId : selected,
          messages: rollover ? messages.filter(m => m.id === botId) : messages,
          turnOutcome: !rollover && metricGeneration === this.metricGeneration ? outcome ?? null : null }, true);
        if (rollover && text === '/undo') {
          void resumeSession(this.config, sessionId).then(result => {
            if (current() && result.ok && result.session === this.state.sessionId && Array.isArray(result.turns)) {
              this.publish({ messages: visibleTurns(result.turns) }, true);
            }
          }).catch(() => { /* Keep the acknowledgement when the transcript cannot be fetched. */ });
        }
      },
      onError: error => {
        if (!current()) return;
        this.cancel = null;
        patch(m => ({ ...m, text: m.text || `⚠ ${error}`, pending: false, error: !m.text }));
        this.publish({ sending: false, turnOutcome: null }, true);
      },
    }, selected);
    // Missing configuration can report an error synchronously before streamChat returns.
    if (current() && this.state.sending) this.cancel = cancel;
    return true;
  }
}
