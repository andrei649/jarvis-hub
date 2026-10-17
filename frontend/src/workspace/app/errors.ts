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

export function describeError(i18n: I18n, err: unknown): string {
  if (isAbort(err)) return '';
  if (!(err instanceof WorkspaceApiError)) return i18n.t('error.unexpected');
  const { code, extra, status } = err;
  if (code === 'weak_password' && typeof extra.reason === 'string') {
    const key = `error.weak_password.${extra.reason}`;
    if (i18n.has(key)) return i18n.t(key);
  }
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
