/* One message of the conversation.

   A question is shown as the person typed it (plain text). An answer is rendered through the
   shared Markdown renderer with citation chips, its headings one level under the chat's h2.
   Message bodies are not live regions: while an answer streams it is only aria-busy, and the
   chat's single status region says when it is ready, so a screen reader never reads it token
   by token or several times over. A failed answer shows no partial text (spec §8): it says what
   went wrong, what the person — or, for admins, the admin — can do about it, and offers to ask
   again when it is the latest answer. A cancelled answer says "you stopped it" only when this
   page saw the person press Stop; otherwise (a reload, leaving the conversation) it says
   neutrally that the answer was interrupted. Under a saved answer the meta line says where it
   was produced in plain words; the model id is shown to admins only (review UX-13). */
import React from 'react';
import type { Citation, ChatMessage } from '../../api/types';
import { ADMIN_FIXABLE_CODES, describeCode, hintKey } from '../../app/errors';
import { useUser } from '../../app/session';
import { useI18n } from '../../i18n';
import { Avatar, Button, IconButton, Notice, Spinner } from '../../ui';
import { ButtonLink } from '../shared/ButtonLink';
import { CitedMarkdown, SourcesList } from '../shared/CitedMarkdown';
import { LocalityChip } from '../shared/LocalityChip';

export interface LocalMessage extends ChatMessage {
  /** Stable React key: optimistic rows get a server id later. */
  key: string;
  streaming?: boolean;
  /** Why the model failed, when the live stream said so (stored rows keep only the code). */
  error_reason?: string;
  /** The person pressed Stop on this page (a stored "cancelled" may also be a disconnect). */
  stopped_by_user?: boolean;
}

export function UserMessage({ message }: { message: LocalMessage }) {
  const { t } = useI18n();
  const user = useUser();
  return (
    <li className="ws-msg ws-msg--user">
      <span className="ws-sr-only">{t('chat.you')}:</span>
      <div className="ws-msg__bubble">{message.content}</div>
      <Avatar name={user.name} size={28} />
    </li>
  );
}

function FailedAnswer({ code, reason, stoppedByUser, canRetry, onRetry }: { code: string | null; reason?: string; stoppedByUser: boolean; canRetry: boolean; onRetry: () => void }) {
  const i18n = useI18n();
  const { t, has } = i18n;
  const isAdmin = useUser().role === 'admin';
  const cancelled = code === 'cancelled';
  // The most precise hint: per code and reason, then per code, then generic (shared with report runs).
  const hint = cancelled && !stoppedByUser ? 'chat.hint.disconnected' : hintKey(i18n, 'chat.hint', code, reason);
  const adminKey = hintKey(i18n, 'chat.hint.admin', code, reason);
  const adminFixable = isAdmin && code !== null && ADMIN_FIXABLE_CODES.has(code);
  const title = cancelled ? t(stoppedByUser ? 'chat.stopped' : 'chat.interrupted') : t('chat.error.title');
  return (
    <Notice tone={cancelled ? 'accent' : 'danger'} title={title}>
      {!cancelled && <p>{describeCode(i18n, code, reason)}</p>}
      <p className="ws-small">{hint && has(hint) ? t(hint) : t('chat.hint.generic')}</p>
      {adminFixable && adminKey !== null && <p className="ws-small">{t(adminKey)}</p>}
      {(canRetry || adminFixable) && (
        <div className="ws-msg__fix">
          {canRetry && <Button size="sm" icon="refresh" onClick={onRetry}>{t('chat.retry')}</Button>}
          {adminFixable && <ButtonLink to="/admin/organisation" variant="ghost" size="sm">{t('chat.adminLink')}</ButtonLink>}
        </div>
      )}
    </Notice>
  );
}

export interface AssistantMessageProps {
  message: LocalMessage;
  isLast: boolean;
  onCite: (citation: Citation) => void;
  onRetry: () => void;
  onReload: () => void;
  onCopy: () => void;
  onRate: (value: 1 | -1) => void;
  onNote: () => void;
  /** Absent when email delivery is known to be unavailable. */
  onEmail?: () => void;
}

export function AssistantMessage({ message, isLast, onCite, onRetry, onReload, onCopy, onRate, onNote, onEmail }: AssistantMessageProps) {
  const { t, fmt } = useI18n();
  const isAdmin = useUser().role === 'admin';
  const saved = message.id > 0 && message.status === 'complete' && !message.streaming;
  const waiting = message.streaming && message.content === '';
  return (
    <li className="ws-msg ws-msg--assistant">
      <span className="ws-msg__mark" aria-hidden="true">N</span>
      <div className="ws-msg__body">
        <span className="ws-sr-only">{t('chat.assistant')}:</span>
        {message.status === 'error' && <FailedAnswer code={message.error_code} reason={message.error_reason} stoppedByUser={Boolean(message.stopped_by_user)} canRetry={isLast} onRetry={onRetry} />}
        {message.status === 'pending' && !message.streaming && (
          <Notice tone="accent" action={<Button size="sm" icon="refresh" onClick={onReload}>{t('common.refresh')}</Button>}>{t('chat.pending')}</Notice>
        )}
        {message.status !== 'error' && (message.status !== 'pending' || message.streaming) && (
          <div className="ws-msg__answer" aria-busy={message.streaming || undefined}>
            {waiting
              ? <span className="ws-msg__typing"><Spinner size={14} /> {t('chat.thinking')}</span>
              : <CitedMarkdown text={message.content} citations={message.citations} onCite={onCite} breaks headingOffset={2} />}
          </div>
        )}
        {saved && <SourcesList citations={message.citations} onCite={onCite} />}
        {saved && (
          <div className="ws-msg__foot">
            <span className="ws-msg__meta">
              <LocalityChip locality={message.locality} />
              {isAdmin && message.model && <span className="ws-mono">{message.model}</span>}
              {message.latency_ms !== null && message.latency_ms !== undefined && <span>{t('chat.meta.latency', { duration: fmt.durationMs(message.latency_ms) })}</span>}
            </span>
            <span className="ws-msg__actions">
              <IconButton size="sm" icon="copy" label={t('chat.action.copy')} onClick={onCopy} />
              <IconButton size="sm" icon="thumbsUp" label={t('chat.action.helpful')} aria-pressed={message.feedback === 1} onClick={() => onRate(1)} className={message.feedback === 1 ? 'is-on' : undefined} />
              <IconButton size="sm" icon="thumbsDown" label={t('chat.action.notHelpful')} aria-pressed={message.feedback === -1} onClick={() => onRate(-1)} className={message.feedback === -1 ? 'is-on' : undefined} />
              {message.feedback ? <Button size="sm" variant="ghost" onClick={onNote}>{t('chat.feedback.addNote')}</Button> : null}
              {onEmail && <Button size="sm" variant="ghost" icon="mail" onClick={onEmail}>{t('chat.action.email')}</Button>}
            </span>
          </div>
        )}
      </div>
    </li>
  );
}
