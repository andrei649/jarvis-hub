/* Server error codes → the user's language.

   The server answers stable codes (`{"error": "last_admin", ...}`, spec §7); its `message` is
   developer prose and is never shown, so a Romanian screen never flashes English. Codes with a
   parameter get it interpolated: `weak_password` names the failed rule through `reason`,
   throttling answers carry `retry_after_seconds`, and `invalid_request` names the `field`. */
import { useCallback } from 'react';
import { isAbort, WorkspaceApiError } from '../api/client';
import { useI18n, type I18n, type MessageKey } from '../i18n';

/** The form field a validation error points at, when the server named one. */
export function errorField(err: unknown): string | null {
  if (err instanceof WorkspaceApiError && typeof err.extra.field === 'string') return err.extra.field;
  return null;
}

export function errorCode(err: unknown): string | null {
  return err instanceof WorkspaceApiError ? err.code : null;
}

function retryText(i18n: I18n, seconds: number): string {
  if (seconds < 60) return i18n.tn('error.retry_seconds', Math.max(1, Math.ceil(seconds)));
  return i18n.tn('error.retry_minutes', Math.ceil(seconds / 60));
}

/** Codes whose `reason` names the model problem; the reason sentence follows the headline. */
const MODEL_CODES: ReadonlySet<string> = new Set(['model_unavailable', 'model_policy_blocked']);

/**
 * A failure reported as a code plus an optional machine `reason` — the shape of SSE error
 * events, the admin model and SMTP tests, and error bodies alike — in plain words.
 * `smtp_failed` names the cause the mail server gave; model codes add why the model is out.
 */
export function describeCode(i18n: I18n, code: string | null | undefined, reason?: unknown): string {
  if (!code) return i18n.t('error.unexpected');
  const why = typeof reason === 'string' && reason ? reason : null;
  const smtpKey = `error.smtp_failed.${why}`;
  if (why && code === 'smtp_failed' && i18n.has(smtpKey)) return i18n.t(smtpKey);
  const codeKey = `error.${code}`;
  const base = i18n.has(codeKey) ? i18n.t(codeKey) : i18n.t('error.unknown', { code });
  const reasonKey = `model.reason.${why}`;
  if (why && MODEL_CODES.has(code) && i18n.has(reasonKey)) return `${base} ${i18n.t(reasonKey)}`;
  return base;
}

/** Model codes whose fix is on the admin's side (the model settings): admins get a direct link. */
export const ADMIN_FIXABLE_CODES: ReadonlySet<string> = new Set(['model_unavailable', 'model_policy_blocked']);

/**
 * The most precise next-step key the dictionary has under *base* (`chat.hint`,
 * `chat.hint.admin`): per code and reason, then per code; null when there is neither. The chat
 * and a failed report run share these keys, so both say the same thing for the same failure.
 */
export function hintKey(i18n: Pick<I18n, 'has'>, base: string, code: string | null | undefined, reason?: string | null): MessageKey | null {
  const keys = [reason ? `${base}.${code ?? ''}.${reason}` : null, `${base}.${code ?? ''}`];
  for (const key of keys) if (key !== null && i18n.has(key)) return key;
  return null;
}

export function describeError(i18n: I18n, err: unknown): string {
  if (isAbort(err)) return '';
  if (!(err instanceof WorkspaceApiError)) return i18n.t('error.unexpected');
  const { code, extra, status } = err;
  if (code === 'weak_password' && typeof extra.reason === 'string') {
    const key = `error.weak_password.${extra.reason}`;
    if (i18n.has(key)) return i18n.t(key);
  }
  if ((code === 'smtp_failed' || MODEL_CODES.has(code)) && typeof extra.reason === 'string') {
    return describeCode(i18n, code, extra.reason);
  }
  if (code === 'file_too_large' && Number(extra.max_bytes) > 0) {
    return i18n.t('error.file_too_large.max', { max: i18n.fmt.bytes(Number(extra.max_bytes)) });
  }
  if (code === 'unsupported_file_type' && extra.reason === 'content') return i18n.t('error.unsupported_file_type.content');
  if (code === 'invalid_request' && typeof extra.field === 'string') {
    const label = `field.${extra.field}`;
    if (i18n.has(label)) return i18n.t('error.invalid_field', { field: i18n.t(label) });
  }
  const base = i18n.has(`error.${code}`) ? i18n.t(`error.${code}` as MessageKey) : null;
  const wait = Number(extra.retry_after_seconds);
  if ((code === 'too_many_attempts' || code === 'rate_limited') && wait > 0) {
    return `${base ?? i18n.t('error.rate_limited')} ${retryText(i18n, wait)}`;
  }
  if (base) return base;
  if (status >= 500) return i18n.t('error.server_error');
  return i18n.t('error.unknown', { code });
}

/** `const errorText = useErrorText(); setError(errorText(err))` */
export function useErrorText(): (err: unknown) => string {
  const i18n = useI18n();
  return useCallback((err: unknown) => describeError(i18n, err), [i18n]);
}
