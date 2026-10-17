/* The chat pane: the open conversation, the answer streaming in, and the composer.

   Streaming (spec §8): the question and an empty answer appear at once; `start` swaps in the
   stored rows, `sources` attaches the numbered citations, `token` appends text, `done`
   replaces the answer with the stored message (citations filtered to the ones used), and
   `error` turns it into an explained failure with no partial text. Stop aborts the request —
   the server records that answer as cancelled — and so does leaving the conversation. A
   refusal before the first event (busy conversation, rate limit) puts the question back in
   the composer, since nothing was stored; a rotated CSRF token is refreshed and the question
   re-sent once, as the JSON client does for its own requests.

   A new conversation is created on the first question, so opening the Assistant never leaves
   an empty conversation behind; the page then gives it its URL without moving focus. */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createConversation, getConversation, sendFeedback, streamAnswer } from '../../api/chat';
import { isAbort } from '../../api/client';
import { eventJson } from '../../api/sse';
import type { ChatMessage, ChatStreamEvents, Citation, Conversation, Department, ModelPosture } from '../../api/types';
import { describeCode, describeError, errorCode, useErrorText } from '../../app/errors';
import { copyText } from '../../app/hooks';
import { useSession, useUser } from '../../app/session';
import { useI18n } from '../../i18n';
import { modelState, useModelReason } from '../../shell/ModelChip';
import { Button, Dialog, EmptyState, LoadingBlock, Notice, TextArea, useToast } from '../../ui';
import { EmailRequestDialog } from '../shared/ApprovalDialogs';
import { ButtonLink } from '../shared/ButtonLink';
import { SourceDrawer } from '../shared/SourceDrawer';
import { useApprovalReadiness } from '../shared/useApprovalReadiness';
import { Composer, MAX_QUESTION } from './Composer';
import { AssistantMessage, UserMessage, type LocalMessage } from './MessageItem';
import { suggestedPrompts } from './prompts';

const GUARDED_MODES = new Set(['redact', 'block']);
const NOTE_MAX = 1000;
const STICK_DISTANCE = 120;

type Phase = 'idle' | 'creating' | 'streaming';
type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function draft(key: string, role: ChatMessage['role'], content: string, id: number): LocalMessage {
  return {
    key, id, role, content, citations: [], status: 'complete', error_code: null, model: null, locality: null,
    latency_ms: null, feedback: null, created_at: Date.now() / 1000,
  };
}

/** The answer as plain Markdown for an email, with its sources listed (the chips do not travel). */
function emailBody(message: LocalMessage, sourcesHeading: string, pageLabel: (page: number) => string): string {
  if (message.citations.length === 0) return message.content;
  const lines = message.citations.map((c) => `${c.n}. ${c.title}${c.page !== null && c.page !== undefined ? `, ${pageLabel(c.page)}` : ''}`);
  return `${message.content}\n\n**${sourcesHeading}**\n\n${lines.join('\n')}`;
}

function FeedbackNoteDialog({ message, onClose, onSaved }: { message: LocalMessage; onClose: () => void; onSaved: (saved: ChatMessage) => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (note.length > NOTE_MAX) { setError(t('common.tooLong', { max: NOTE_MAX })); return; }
    setBusy(true);
    setError(null);
    try {
      onSaved(await sendFeedback(message.id, { value: message.feedback === -1 ? -1 : 1, note: note.trim() }));
      toast.success(t('chat.feedback.saved'));
      onClose();
    } catch (err) {
      setError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open onClose={onClose} title={t('chat.feedback.noteTitle')} description={t('chat.feedback.noteDesc')} busy={busy}
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-feedback-note" busy={busy} disabled={!note.trim()}>{t('common.save')}</Button>
        </>
      )}
    >
      <form id="ws-feedback-note" className="ws-form" onSubmit={save} noValidate>
        <TextArea
          label={t('chat.feedback.note')} value={note} rows={4} error={error} onChange={(e) => setNote(e.target.value)}
          aside={t('common.charCount', { count: note.length, max: NOTE_MAX })} data-autofocus="true"
        />
      </form>
    </Dialog>
  );
}

export interface ChatPaneProps {
  conversationId: number | null;
  /** The department a new conversation is created in (the sidebar's current one). */
  department: Department;
  posture: ModelPosture | null;
  /** The pane's header row (title and conversation actions, owned by the page). */
  header: React.ReactNode;
  onCreated: (conversation: Conversation) => void;
  onLoaded: (conversation: Conversation) => void;
  /** Something changed server-side (new message, new title): the page refreshes its list. */
  onActivity: () => void;
}

export function ChatPane({ conversationId, department, posture, header, onCreated, onLoaded, onActivity }: ChatPaneProps) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const errorText = useErrorText();
  const reasonText = useModelReason();
  const isAdmin = useUser().role === 'admin';
  const { refresh: refreshSession } = useSession();
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [loadState, setLoadState] = useState<LoadState>('idle');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [question, setQuestion] = useState('');
  const [composerError, setComposerError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [announcement, setAnnouncement] = useState('');
  const [citation, setCitation] = useState<Citation | null>(null);
  const [emailFor, setEmailFor] = useState<LocalMessage | null>(null);
  const [noteFor, setNoteFor] = useState<LocalMessage | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const createdIdRef = useRef<number | null>(null);
  const keySeq = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  const nextKey = () => { keySeq.current += 1; return `m${keySeq.current}`; };
  const withKeys = (list: ChatMessage[]): LocalMessage[] => list.map((m) => ({ ...m, key: `s${m.id}` }));

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (conversationId !== null && conversationId === createdIdRef.current) return undefined;
    abortRef.current?.abort();
    createdIdRef.current = null;
    setComposerError(null);
    if (conversationId === null) {
      setMessages([]);
      setConversation(null);
      setLoadState('idle');
      return undefined;
    }
    let alive = true;
    setLoadState('loading');
    getConversation(conversationId).then((detail) => {
      if (!alive) return;
      setConversation(detail.conversation);
      setMessages(withKeys(detail.messages ?? []));
      setLoadState('ready');
      stickToBottom.current = true;
      onLoadedRef.current(detail.conversation);
    }).catch((err) => {
      if (!alive) return;
      setLoadError(err);
      setLoadState('error');
    });
    return () => { alive = false; };
  }, [conversationId, reloadTick]);

  // Follow the conversation downwards; an empty chat reads from its top (greeting first).
  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    if (messages.length === 0) node.scrollTop = 0;
    else if (stickToBottom.current) node.scrollTop = node.scrollHeight;
  }, [messages]);

  const departmentId = conversation?.department_id ?? department.id;
  const hasAnswers = messages.some((m) => m.role === 'assistant' && m.status === 'complete' && m.id > 0);
  const email = useApprovalReadiness('email.send', departmentId, hasAnswers);

  const patch = (key: string, change: Partial<LocalMessage> | ((m: LocalMessage) => Partial<LocalMessage>)) => {
    setMessages((list) => list.map((m) => (m.key === key ? { ...m, ...(typeof change === 'function' ? change(m) : change) } : m)));
  };

  const stream = async (id: number, text: string, retried = false): Promise<void> => {
    const userKey = nextKey();
    const replyKey = nextKey();
    stickToBottom.current = true;
    setMessages((list) => [...list, draft(userKey, 'user', text, -1), { ...draft(replyKey, 'assistant', '', -2), status: 'pending', streaming: true }]);
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase('streaming');
    setAnnouncement(t('chat.streaming'));
    let started = false;
    let settled = false;
    const fail = (code: string, reason?: string) => {
      settled = true;
      patch(replyKey, { status: 'error', error_code: code, error_reason: reason, content: '', citations: [], streaming: false });
      setAnnouncement(code === 'cancelled' ? t('chat.stopped') : `${t('chat.error.title')}: ${describeCode(i18n, code, reason)}`);
    };
    try {
      for await (const event of streamAnswer(id, text, controller.signal)) {
        started = true;
        if (event.event === 'start') {
          const data = eventJson<ChatStreamEvents['start']>(event);
          setMessages((list) => list.map((m) => {
            if (m.key === userKey && data.user_message) return { ...data.user_message, key: userKey };
            if (m.key === replyKey) return { ...m, id: data.assistant_message_id };
            return m;
          }));
        } else if (event.event === 'sources') {
          patch(replyKey, { citations: eventJson<ChatStreamEvents['sources']>(event).citations ?? [] });
        } else if (event.event === 'token') {
          const piece = eventJson<ChatStreamEvents['token']>(event).t ?? '';
          patch(replyKey, (m) => ({ content: m.content + piece }));
        } else if (event.event === 'done') {
          const final = eventJson<ChatStreamEvents['done']>(event).assistant_message;
          settled = true;
          patch(replyKey, { ...final, citations: final.citations ?? [], streaming: false });
          setAnnouncement('');
        } else if (event.event === 'error') {
          const failure = eventJson<ChatStreamEvents['error']>(event);
          fail(failure.error, failure.reason);
        }
      }
      if (!settled) fail(controller.signal.aborted ? 'cancelled' : 'network_error');
    } catch (err) {
      if (isAbort(err)) {
        fail('cancelled');
      } else if (!started) {
        // Refused before anything was stored: re-send once on a rotated token, else the
        // question goes back to the composer.
        setMessages((list) => list.filter((m) => m.key !== userKey && m.key !== replyKey));
        if (!retried && errorCode(err) === 'csrf_failed' && await refreshSession()) {
          if (abortRef.current === controller) abortRef.current = null;
          await stream(id, text, true);
          return;
        }
        setQuestion(text);
        setComposerError(errorText(err));
        setAnnouncement('');
      } else {
        fail(errorCode(err) ?? 'network_error');
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setPhase('idle');
      onActivity();
    }
  };

  const ask = async (content: string) => {
    const text = content.trim();
    if (!text || phase !== 'idle') return;
    if (text.length > MAX_QUESTION) { setComposerError(t('common.tooLong', { max: MAX_QUESTION })); return; }
    setComposerError(null);
    setQuestion('');
    let id = conversationId;
    if (id === null) {
      setPhase('creating');
      try {
        const created = await createConversation(department.id);
        id = created.id;
        createdIdRef.current = created.id;
        setConversation(created);
        setLoadState('ready');
        onCreated(created);
      } catch (err) {
        setPhase('idle');
        setQuestion(text);
        setComposerError(errorText(err));
        return;
      }
    }
    await stream(id, text);
  };

  const retry = (index: number) => {
    const asked = [...messages.slice(0, index)].reverse().find((m) => m.role === 'user');
    if (asked) void ask(asked.content);
  };

  const replace = (saved: ChatMessage) => {
    setMessages((list) => list.map((m) => (m.id === saved.id ? { ...m, ...saved, key: m.key } : m)));
  };

  const rate = async (message: LocalMessage, value: 1 | -1) => {
    const next = message.feedback === value ? 0 : value;
    patch(message.key, { feedback: next });
    try {
      replace(await sendFeedback(message.id, { value: next }));
      if (next !== 0) toast.success(t('chat.feedback.thanks'));
    } catch (err) {
      patch(message.key, { feedback: message.feedback });
      toast.error(errorText(err));
    }
  };

  const copy = async (message: LocalMessage) => {
    if (await copyText(message.content)) toast.success(t('chat.copied'));
    else toast.info(t('chat.copyFailed'));
  };

  const questionBefore = (message: LocalMessage): string => {
    const index = messages.findIndex((m) => m.key === message.key);
    return [...messages.slice(0, index)].reverse().find((m) => m.role === 'user')?.content ?? '';
  };

  const stop = useCallback(() => abortRef.current?.abort(), []);
  /** Re-reads the conversation from the server, including one this pane created. */
  const reload = () => { createdIdRef.current = null; setReloadTick((n) => n + 1); };

  const guarded = Boolean(posture?.guardrails_mode && GUARDED_MODES.has(posture.guardrails_mode.toLowerCase()));
  const unavailable = posture !== null && modelState(posture) === 'unavailable';
  const showEmpty = loadState !== 'loading' && loadState !== 'error' && messages.length === 0;
  const lastIndex = messages.length - 1;

  return (
    <section className="ws-chat" aria-labelledby="ws-chat-title">
      <header className="ws-chat__head">{header}</header>
      <div
        ref={scroller} className="ws-chat__scroll"
        onScroll={(event) => {
          const node = event.currentTarget;
          stickToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < STICK_DISTANCE;
        }}
      >
        {loadState === 'loading' && <LoadingBlock label={t('common.loading')} lines={4} />}
        {loadState === 'error' && (errorCode(loadError) === 'not_found'
          ? <EmptyState icon="chat" title={t('chat.notFound.title')} body={t('chat.notFound.body')} action={<ButtonLink to="/assistant" variant="primary" icon="plus">{t('assistant.list.new')}</ButtonLink>} />
          : <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={reload}>{t('common.retry')}</Button>}>{describeError(i18n, loadError)}</Notice>)}
        {showEmpty && (
          <div className="ws-chat-empty">
            <span className="ws-chat-empty__mark" aria-hidden="true">N</span>
            <p className="ws-chat-empty__title">{t('chat.empty.title')}</p>
            <p className="ws-chat-empty__body">{t('chat.empty.body', { department: department.name })}</p>
            {department.document_count === 0 && (
              <Notice tone="warning" action={<ButtonLink to="/documents" size="sm">{t('chat.empty.uploadLink')}</ButtonLink>}>
                {t('chat.empty.noDocuments', { department: department.name })}
              </Notice>
            )}
            <p className="ws-chat-empty__label" id="ws-prompts-label">{t('chat.empty.prompts')}</p>
            <ul className="ws-prompts" aria-labelledby="ws-prompts-label">
              {suggestedPrompts(department).map((key) => (
                <li key={key}>
                  <button type="button" className="ws-prompt" disabled={phase !== 'idle'} onClick={() => void ask(t(key))}>
                    <span>{t(key)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.length > 0 && (
          <ol className="ws-chat__list" aria-label={t('chat.label')}>
            {messages.map((message, index) => (message.role === 'user'
              ? <UserMessage key={message.key} message={message} />
              : (
                <AssistantMessage
                  key={message.key} message={message} isLast={index === lastIndex}
                  onCite={setCitation} onRetry={() => retry(index)} onReload={reload}
                  onCopy={() => void copy(message)} onRate={(value) => void rate(message, value)} onNote={() => setNoteFor(message)}
                  onEmail={email.smtpReady === false ? undefined : () => setEmailFor(message)}
                />
              )))}
          </ol>
        )}
      </div>
      <div className="ws-chat__foot">
        {unavailable && posture && (
          <Notice
            tone="warning"
            action={isAdmin ? <ButtonLink to="/admin/organisation" size="sm">{t('chat.adminLink')}</ButtonLink> : undefined}
          >
            {t('chat.modelUnavailable', { reason: reasonText(posture.reason) })}
          </Notice>
        )}
        {guarded && !unavailable && <p className="ws-chat__note"><span aria-hidden="true">ⓘ</span> {t('chat.guardrails')}</p>}
        <Composer
          value={question} onChange={(value) => { setQuestion(value); if (composerError) setComposerError(null); }}
          onSubmit={() => void ask(question)} onStop={stop} phase={phase} error={composerError}
          placeholder={t('chat.composer.placeholder')}
        />
      </div>
      <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
      <SourceDrawer citation={citation} context="answer" onClose={() => setCitation(null)} />
      {emailFor && (
        <EmailRequestDialog
          onClose={() => setEmailFor(null)} departmentId={departmentId} departmentName={department.name}
          source={{ type: 'message', id: emailFor.id }}
          defaultSubject={t('chat.email.subject', { title: questionBefore(emailFor).replace(/\s+/g, ' ').slice(0, 120) })}
          defaultBody={emailBody(emailFor, t('chat.sources'), (page) => t('source.page', { page: String(page) }))}
        />
      )}
      {noteFor && <FeedbackNoteDialog message={noteFor} onClose={() => setNoteFor(null)} onSaved={replace} />}
    </section>
  );
}
