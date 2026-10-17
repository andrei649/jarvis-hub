/* Sign-in: email + password, or the company proxy SSO when the server offers it.

   Failures are deliberately generic (the server never says whether an email exists); the page
   adds what helps: throttling tells the user when to retry, an ended session explains why they
   are here, and a forgotten password points to the admin, who issues reset links. */
import React, { useState } from 'react';
import { login, loginSso } from '../../api/account';
import { describeError } from '../../app/errors';
import { useSession } from '../../app/session';
import { useI18n } from '../../i18n';
import { Button, Notice, PasswordField, TextField } from '../../ui';
import { AuthLayout } from './AuthLayout';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function LoginPage() {
  const i18n = useI18n();
  const { t } = i18n;
  const { session, org, signIn, expired, ssoError } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'password' | 'sso' | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const next: typeof errors = {};
    if (!EMAIL_PATTERN.test(email.trim())) next.email = t('auth.error.email');
    if (!password) next.password = t('auth.error.passwordRequired');
    setErrors(next);
    setFormError(null);
    if (next.email || next.password) return;
    setBusy('password');
    try {
      signIn(await login({ email: email.trim(), password }));
    } catch (err) {
      setFormError(describeError(i18n, err));
      setPassword('');
      setBusy(null);
    }
  };

  const sso = async () => {
    setBusy('sso');
    setFormError(null);
    try {
      signIn(await loginSso());
    } catch (err) {
      setFormError(describeError(i18n, err));
      setBusy(null);
    }
  };

  return (
    <AuthLayout title={t('auth.login.title')} description={org?.name ? t('auth.login.descOrg', { org: org.name }) : t('auth.login.desc')}>
      {expired && <Notice tone="warning" live="polite">{t('auth.login.expired')}</Notice>}
      {ssoError && !formError && <Notice tone="warning" live="polite">{describeError(i18n, ssoError)}</Notice>}
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form className="ws-form" onSubmit={submit} noValidate>
        <TextField
          label={t('field.email')} type="email" autoComplete="username" inputMode="email" autoFocus
          value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} maxLength={254} required
        />
        <PasswordField
          label={t('field.password')} autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} error={errors.password} maxLength={256} required
        />
        <Button type="submit" variant="primary" block busy={busy === 'password'} disabled={busy === 'sso'}>{t('auth.login.submit')}</Button>
      </form>
      {session?.sso_available && (
        <>
          <div className="ws-divider"><span>{t('auth.login.or')}</span></div>
          <Button block icon="building" onClick={sso} busy={busy === 'sso'} disabled={busy === 'password'}>{t('auth.login.sso')}</Button>
        </>
      )}
      <p className="ws-auth__help">{t('auth.login.forgot')}</p>
    </AuthLayout>
  );
}
