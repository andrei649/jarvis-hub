import { resumeSession, streamChat, validVaultExcerpts, type HistoryTurn, type SessionTransition,
  type StreamErrorDetail, type StreamHandlers, type VaultExcerpt } from '../api/client';
import { loadConversation, saveConversation, type SavedConversation } from '../storage/chat';
import type { ServerConfig } from '../storage/settings';
import type { ChatMessage } from './types';
import { toolActivity, type TurnOutcome } from './turnOutcome';
import { modelCalls } from '../api/modelCallProvenance';
import { projectSavedChatNote } from '../api/chatNote';
import { historyRequiresCloudConsent, historySourceReceipt, validHistoryReference, type HistorySelection } from '../api/sessionTranscript';

export type ConversationState = SavedConversation & {
  ready: boolean;
  sending: boolean;
  turnOutcome: TurnOutcome | null;
  missingSessionId: string | null;
  recoveryPrompt: string | null;
};
let sequence = 0;
const nextId = () => `m${Date.now()}_${sequence++}`;
const validId = (id: unknown): id is string => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id);

function visibleTurns(turns: HistoryTurn[]): ChatMessage[] {
  return turns.filter(t => t && (t.role === 'user' || t.role === 'assistant') && typeof t.content === 'string')
    .map((t, index, visible) => {
      const nativeReply = t.role === 'assistant' && !Object.prototype.hasOwnProperty.call(t, 'foreign_origin')
        && !Object.prototype.hasOwnProperty.call(t, 'tainted');
      const calls = nativeReply ? modelCalls(t.model_calls) : [];
      const completed = nativeReply && !!t.content.trim() && t.agent_id !== 'system'
        && !(visible[index - 1]?.role === 'user' && visible[index - 1].content.trimStart().startsWith('/'));
      const activity = completed ? toolActivity(t.tool_activity) : undefined;
      const source = t.role === 'user' && !Object.prototype.hasOwnProperty.call(t, 'foreign_origin')
        && !Object.prototype.hasOwnProperty.call(t, 'tainted') ? historySourceReceipt(t.history_source) : null;
      return { id: nextId(), role: t.role as ChatMessage['role'], text: t.content,
        ...(typeof t.agent_id === 'string' ? { agent: t.agent_id } : {}),
        ...(completed ? { completed: true as const } : {}),
        ...(activity ? { toolActivity: activity } : {}),
        ...(calls.length ? { modelCalls: calls } : {}),
        ...(source ? { historySource: source } : {}) };
    });
}

/** One mounted connection owns hydration, selection and all its in-flight callbacks. */
export class Conversation {
  state: ConversationState = { sessionId: null, messages: [], ready: false, sending: false,
    turnOutcome: null, missingSessionId: null, recoveryPrompt: null };
  private epoch = 0;
  private metricGeneration = 0;
  private active = true;
  private cancel: (() => void) | null = null;
  private pendingHistoryResult: ((accepted: boolean) => void) | null = null;
  private pendingHistoryIds: { user: string; bot: string } | null = null;

  get revision(): number { return this.epoch; }

  constructor(private config: ServerConfig, private scope: string,
    private changed: (state: ConversationState) => void) {}

  private publish(update: Partial<ConversationState>, persist = false) {
    if (!this.active) return;
    this.state = { ...this.state, ...update };
    this.changed(this.state);
    if (persist && this.state.ready) void saveConversation(this.scope, {
      sessionId: this.state.sessionId, messages: this.state.messages,
      ...(this.state.recoveryPrompt !== null ? { recoveryPrompt: this.state.recoveryPrompt } : {}),
    });
  }

  async hydrate() {
    const epoch = this.epoch;
    const saved = await loadConversation(this.scope);
    if (this.active && epoch === this.epoch) this.publish({ ...saved, recoveryPrompt: saved.recoveryPrompt ?? null,
      missingSessionId: null, ready: true, turnOutcome: null });
  }

  resume(sessionId: string, turns: HistoryTurn[]) {
    if (!this.active || !validId(sessionId) || !Array.isArray(turns)) return;
    this.invalidate();
    this.publish({ sessionId, messages: visibleTurns(turns), ready: true, sending: false,
      turnOutcome: null, missingSessionId: null }, true);
  }

  private invalidate() {
    ++this.epoch;
    const pendingResult = this.pendingHistoryResult;
    this.pendingHistoryResult = null;
    this.pendingHistoryIds = null;
    pendingResult?.(false);
    const cancel = this.cancel;
    this.cancel = null;
    cancel?.();
  }

  stop() {
    const historyIds = this.pendingHistoryIds;
    this.invalidate();
    this.publish({ sending: false, turnOutcome: null, messages: this.state.messages
      .filter(m => !historyIds || (m.id !== historyIds.user && m.id !== historyIds.bot))
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

  attachSavedNote(id: string, text: string, saved: unknown): boolean {
    const note = projectSavedChatNote(saved);
    const message = this.state.messages.find(m => m.id === id);
    if (!this.active || !note || !message || message.role !== 'assistant' || message.completed !== true
      || message.pending || message.error || message.text !== text) return false;
    this.publish({ messages: this.state.messages.map(m => m.id === id ? { ...m, savedNote: note } : m) }, true);
    return true;
  }

  /** Explicitly discard the retained prompt after the user has copied or dismissed it. */
  dismissRecoveryPrompt() {
    if (!this.active || this.state.recoveryPrompt === null) return;
    this.publish({ recoveryPrompt: null }, true);
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
        { id: nextId(), role: 'assistant', text: answer, agent, completed: true }] }, true);
      return true;
    };
    const cancel = () => { if (current()) this.stop(); };
    return { signal: controller.signal, current, release, cancel, commit };
  }

  send(message: string, agent: string, reasoning?: 'none', excerpts?: VaultExcerpt[],
    history?: HistorySelection, onHistoryResult?: (accepted: boolean) => void): boolean {
    const reject = () => { if (history !== undefined) onHistoryResult?.(false); return false; };
    if (this.state.missingSessionId !== null) return reject();
    if (this.state.recoveryPrompt !== null && !['/new', '/reset', '/undo'].includes(message.trim())) return reject();
    if (excerpts !== undefined && (!validVaultExcerpts(excerpts)?.length || message.trimStart().startsWith('/'))) return reject();
    if (history !== undefined && (excerpts !== undefined || !history || !validHistoryReference(history.reference)
      || (history.role !== 'user' && history.role !== 'assistant') || message.trimStart().startsWith('/')
      || !this.config.adminToken.trim()
      || (historyRequiresCloudConsent(agent) && !history.reference.allow_cloud))) return reject();
    if (!this.active || !this.state.ready || this.state.sending || !message.trim()) return reject();
    return this.sendInternal(message, agent, this.state.sessionId, null, reasoning, excerpts, history, onHistoryResult);
  }

  /** Start a fresh governed session only after the selected server session was proven missing. */
  recoverWithNewSession(agent: string): boolean {
    const missing = this.state.missingSessionId;
    if (!validId(missing) || this.state.sessionId !== missing) return false;
    return this.sendInternal('/new', agent, null, missing);
  }

  private sendInternal(message: string, agent: string, requestedSessionId: string | null,
    recoveringMissingSession: string | null, reasoning?: 'none', excerpts?: VaultExcerpt[],
    history?: HistorySelection, onHistoryResult?: (accepted: boolean) => void): boolean {
    const text = message.trim();
    if (!this.active || !this.state.ready || this.state.sending || !text) return false;
    this.invalidate();
    const epoch = this.epoch;
    const metricGeneration = this.metricGeneration;
    const botId = nextId();
    const userId = nextId();
    const selected = this.state.sessionId;
    const source = history ? historySourceReceipt({ ...history.reference, role: history.role }) : null;
    const missingAtStart = recoveringMissingSession;
    const current = () => this.active && epoch === this.epoch;
    const patch = (update: (m: ChatMessage) => ChatMessage) => {
      if (current()) this.publish({ messages: this.state.messages.map(m => m.id === botId ? update(m) : m) });
    };
    if (history) {
      this.pendingHistoryResult = onHistoryResult ?? null;
      this.pendingHistoryIds = { user: userId, bot: botId };
    }
    this.publish({ sending: true, turnOutcome: null, messages: [...this.state.messages,
      { id: userId, role: 'user', text }, { id: botId, role: 'assistant', text: '', pending: true, agent }] });
    const handlers: StreamHandlers = {
      onStart: responder => patch(m => ({ ...m, agent: responder || agent })),
      onToken: token => patch(m => ({ ...m, text: m.text + token })),
      onDone: (full, sessionId, outcome, transition?: SessionTransition, receipt?, historyUsed?) => {
        if (!current()) return;
        this.cancel = null;
        let acceptedHistoryReport: ((accepted: boolean) => void) | null = null;
        if (history) {
          const accepted = historyUsed === true && !!source && validId(sessionId)
            && (selected === null || sessionId === selected);
          const report = this.pendingHistoryResult;
          this.pendingHistoryResult = null;
          this.pendingHistoryIds = null;
          if (!accepted) {
            this.publish({ sending: false, turnOutcome: null,
              messages: this.state.messages.filter(m => m.id !== userId && m.id !== botId) }, true);
            report?.(false);
            return;
          }
          this.publish({ messages: this.state.messages.map(m => m.id === userId
            ? { ...m, historySource: source } : m) });
          acceptedHistoryReport = report;
        }
        const changed = validId(sessionId) && sessionId !== selected;
        const transitionSessionId = transition?.command === 'new' && validId(transition.sessionId)
          && transition.sessionId === sessionId ? transition.sessionId : null;
        const confirmedRecovery = missingAtStart !== null && selected === missingAtStart && text === '/new'
          && transitionSessionId !== null && transitionSessionId !== missingAtStart;
        const rollover = changed && ['/new', '/reset', '/undo'].includes(text)
          && (missingAtStart === null || confirmedRecovery);
        const resolvedMissing = (confirmedRecovery || (missingAtStart === null && validId(sessionId)))
          ? null : this.state.missingSessionId;
        const recoveryPrompt = this.state.recoveryPrompt;
        const nextSessionId = missingAtStart !== null && !confirmedRecovery
          ? selected : validId(sessionId) ? sessionId : selected;
        const unconfirmedRecovery = missingAtStart !== null && text === '/new' && !confirmedRecovery;
        const displayedFull = unconfirmedRecovery
          ? `The hub did not confirm a new conversation. Your previous chat remains selected. `
            + `Select a saved chat or update the hub before trying again.${full ? `\nHub response: ${full}` : ''}`
          : full;
        const calls = unconfirmedRecovery ? [] : modelCalls(receipt);
        const messages = this.state.messages.map(m => m.id === botId
          ? { ...m, text: displayedFull || m.text, pending: false,
            ...(!text.startsWith('/') && !unconfirmedRecovery && m.agent !== 'system'
              && (!!full.trim() || (validId(sessionId) && !!m.text.trim())) ? { completed: true as const,
                ...(outcome?.tools ? { toolActivity: outcome.tools } : {}) } : {}),
            ...(calls.length ? { modelCalls: calls } : {}) } : m);
        this.publish({ sending: false, sessionId: nextSessionId,
          messages: rollover ? messages.filter(m => m.id === botId) : messages,
          missingSessionId: resolvedMissing, recoveryPrompt,
          turnOutcome: !rollover && metricGeneration === this.metricGeneration ? outcome ?? null : null }, true);
        acceptedHistoryReport?.(true);
        if (rollover && text === '/undo') {
          void resumeSession(this.config, sessionId).then(result => {
            if (current() && result.ok && result.session === this.state.sessionId && Array.isArray(result.turns)) {
              this.publish({ messages: visibleTurns(result.turns) }, true);
            }
          }).catch(() => { /* Keep the acknowledgement when the transcript cannot be fetched. */ });
        }
      },
      onError: (error, detail?: StreamErrorDetail) => {
        if (!current()) return;
        this.cancel = null;
        if (history) {
          const report = this.pendingHistoryResult;
          this.pendingHistoryResult = null;
          this.pendingHistoryIds = null;
          this.publish({ sending: false, turnOutcome: null,
            messages: this.state.messages.filter(m => m.id !== userId && m.id !== botId) }, true);
          report?.(false);
          return;
        }
        patch(m => ({ ...m, text: m.text || `⚠ ${error}`, pending: false, error: !m.text }));
        const provesMissing = recoveringMissingSession === null && selected !== null
          && this.state.sessionId === selected && detail?.kind === 'session_missing'
          && detail.sessionId === selected;
        this.publish({ sending: false, turnOutcome: null,
          ...(provesMissing ? { missingSessionId: selected, recoveryPrompt: this.state.recoveryPrompt ?? text } : {}) }, true);
      },
    };
    const attachmentArg: [] | [VaultExcerpt[]] = excerpts === undefined ? [] : [excerpts];
    let cancel: () => void;
    try {
      cancel = history ? streamChat(this.config, text, agent, handlers, requestedSessionId, reasoning,
        undefined, history.reference) : streamChat(this.config, text, agent, handlers, requestedSessionId,
        reasoning, ...attachmentArg);
    } catch {
      handlers.onError('Could not start the chat stream');
      return false;
    }
    // Missing configuration can report an error synchronously before streamChat returns.
    if (current() && this.state.sending) this.cancel = cancel;
    return true;
  }
}
