/* Accept an invitation or reset a password: <base>/workspace/invite#t=<token>.

   The token travels in the URL fragment so it never reaches a server log (spec §6). The page
   reads it, looks it up, then removes the fragment from the address bar with replaceState so it
   does not linger in history or get copied along; the token stays in memory for the accept call.
   A lookup that fails on the network keeps the fragment, so a reload can retry. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { acceptInvite, lookupInvite } from '../../api/account';
import type { InviteLookup } from '../../api/types';
import { describeError, errorCode } from '../../app/errors';
import { useSession } from '../../app/session';
import { useI18n } from '../../i18n';
import { navigate } from '../../router';
import { Button, LoadingBlock, Notice, PasswordField, TextField } from '../../ui';
import { AuthLayout } from './AuthLayout';
import { PasswordPolicy, passwordProblemText } from './PasswordPolicy';

type State =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'failed'; message: string }
  | { kind: 'ready'; invite: InviteLookup };

export function tokenFromHash(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, '')).get('t');
  return token && /^[A-Za-z0-9_-]{16,128}$/.test(token) ? token : null;
}

function clearFragment(): void {
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
}

export function InvitePage() {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const { signIn, user } = useSession();
  const policyId = `p${useId().replace(/:/g, '')}`;
  const token = useRef<string | null>(tokenFromHash(window.location.hash));
  const [state, setState] = useState<State>(token.current ? { kind: 'loading' } : { kind: 'invalid' });
  const [attempt, setAttempt] = useState(0);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ name?: string; password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const current = token.current;
    if (!current) { clearFragment(); return undefined; }
    let live = true;
    setState({ kind: 'loading' });
    lookupInvite(current).then((invite) => {
      clearFragment();
      if (!live) return;
      setName(invite.name || '');
      setState({ kind: 'ready', invite });
    }).catch((err) => {
      if (errorCode(err) === 'invite_invalid') clearFragment();
      if (!live) return;
      setState(errorCode(err) === 'invite_invalid' ? { kind: 'invalid' } : { kind: 'failed', message: describeError(i18n, err) });
    });
    return () => { live = false; };
    // Only a retry re-runs the lookup; a language switch must not spend another lookup attempt.
  }, [attempt]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (state.kind !== 'ready' || !token.current) return;
    const isInvite = state.invite.purpose === 'invite';
    const next: typeof errors = {};
    if (isInvite && !name.trim()) next.name = t('auth.error.name');
    const weak = passwordProblemText(t, password, state.invite.email);
    if (weak) next.password = weak;
    if (confirm !== password) next.confirm = t('password.mismatch');
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      const result = await acceptInvite({ token: token.current, password, ...(isInvite ? { name: name.trim() } : {}) });
      token.current = null;
      signIn(result);
      navigate('/', { replace: true });
    } catch (err) {
      setBusy(false);
      const code = errorCode(err);
      if (code === 'invite_invalid') { setState({ kind: 'invalid' }); return; }
      if (code === 'weak_password') { setErrors({ password: describeError(i18n, err) }); return; }
      setFormError(describeError(i18n, err));
    }
  };

  if (state.kind === 'loading') {
    return <AuthLayout title={t('invite.loadingTitle')}><LoadingBlock label={t('invite.checking')} /></AuthLayout>;
  }
  if (state.kind === 'invalid') {
    return (
      <AuthLayout title={t('invite.invalidTitle')}>
        <Notice tone="warning">{t('invite.invalidBody')}</Notice>
      </AuthLayout>
    );
  }
  if (state.kind === 'failed') {
    return (
      <AuthLayout title={t('invite.loadingTitle')}>
        <Notice tone="danger" live="assertive">{state.message}</Notice>
        <Button icon="refresh" onClick={() => setAttempt((n) => n + 1)}>{t('common.retry')}</Button>
      </AuthLayout>
    );
  }

  const { invite } = state;
  const isInvite = invite.purpose === 'invite';
  return (
    <AuthLayout
      title={isInvite ? t('invite.title', { org: invite.org_name }) : t('invite.resetTitle')}
      description={isInvite ? t('invite.desc', { email: invite.email }) : t('invite.resetDesc', { email: invite.email })}
    >
      {user && user.email.toLocaleLowerCase() !== invite.email.toLocaleLowerCase() && (
        <Notice tone="warning">{t('invite.otherAccount', { email: user.email })}</Notice>
      )}
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form className="ws-form" onSubmit={submit} noValidate>
        <input type="email" value={invite.email} autoComplete="username" readOnly hidden />
        {isInvite && (
          <TextField label={t('field.name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} autoComplete="name" maxLength={200} required />
        )}
        <PasswordField
          label={t('field.newPassword')} value={password} onChange={(e) => setPassword(e.target.value)} error={errors.password}
          autoComplete="new-password" aria-describedby={policyId} maxLength={256} autoFocus={!isInvite} required
        />
        <PasswordPolicy id={policyId} password={password} email={invite.email} />
        <PasswordField label={t('field.confirm')} value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} autoComplete="new-password" maxLength={256} required />
        <p className="ws-muted ws-small">{t('invite.expires', { date: fmt.dateTime(invite.expires_at) })}</p>
        <Button type="submit" variant="primary" block busy={busy}>{isInvite ? t('invite.submit') : t('invite.resetSubmit')}</Button>
      </form>
    </AuthLayout>
  );
}
