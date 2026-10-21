/* The password policy, shown live under a new-password field.

   It mirrors the server rules that can be checked locally (12–256 characters, must not contain
   the name part of the email) so people fix a password before submitting. The common-password
   list lives only on the server; its verdict arrives as `weak_password / too_common` and is
   shown on the field like any other error. */
import React from 'react';
import { useI18n, type MessageKey } from '../../i18n';
import { Icon } from '../../ui';

export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 256;
/** Very short local parts ("ab@…") would forbid half the alphabet; the server stays authoritative. */
const MIN_LOCAL_PART = 3;

export type PasswordProblem = 'too_short' | 'too_long' | 'contains_email';

function emailLocalPart(email: string): string {
  const at = email.indexOf('@');
  return (at > 0 ? email.slice(0, at) : '').trim().toLocaleLowerCase();
}

export function passwordProblems(password: string, email: string): PasswordProblem[] {
  const problems: PasswordProblem[] = [];
  const length = [...password].length;
  if (length < PASSWORD_MIN) problems.push('too_short');
  if (length > PASSWORD_MAX) problems.push('too_long');
  const local = emailLocalPart(email);
  if (local.length >= MIN_LOCAL_PART && password.toLocaleLowerCase().includes(local)) problems.push('contains_email');
  return problems;
}

/** The first local problem as translated text, for the field error on submit ("choose a
    password" when the field is still empty, not the length rule). */
export function passwordProblemText(t: (key: MessageKey) => string, password: string, email: string): string | null {
  if (!password) return t('password.required');
  const [first] = passwordProblems(password, email);
  return first ? t(`error.weak_password.${first}`) : null;
}

export function PasswordPolicy({ id, password, email }: { id: string; password: string; email: string }) {
  const { t } = useI18n();
  const problems = passwordProblems(password, email);
  const rules: { key: MessageKey; ok: boolean | null }[] = [
    { key: 'password.rule.length', ok: password ? !problems.includes('too_short') && !problems.includes('too_long') : null },
    { key: 'password.rule.email', ok: password && email ? !problems.includes('contains_email') : null },
    { key: 'password.rule.common', ok: null },
  ];
  return (
    <ul className="ws-policy" id={id}>
      {rules.map((rule) => (
        <li key={rule.key} className={rule.ok === null ? '' : rule.ok ? 'is-ok' : 'is-bad'}>
          <Icon name={rule.ok === false ? 'xCircle' : rule.ok ? 'checkCircle' : 'info'} size={16} />
          <span>{t(rule.key)}</span>
          {rule.ok !== null && <span className="ws-sr-only"> — {t(rule.ok ? 'password.rule.met' : 'password.rule.unmet')}</span>}
        </li>
      ))}
    </ul>
  );
}
