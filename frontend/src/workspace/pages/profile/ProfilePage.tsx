/* Profile: name, language, theme, password, and the sessions signed in to this account.

   Changing the password revokes every other session on the server, so the sessions list is
   reloaded afterwards to show it. The current session cannot be revoked from the list (that is
   what signing out does); every other one can, one by one or all at once. */
import React, { useId, useState } from 'react';
import { changePassword, listMySessions, revokeMySession, revokeOtherSessions, updateMe } from '../../api/account';
import type { ActiveSession, Locale, Theme } from '../../api/types';
import { describeError, errorCode, errorField } from '../../app/errors';
import { useAsync, type AsyncState } from '../../app/hooks';
import { useSession, useUser } from '../../app/session';
import { summarizeAgent } from '../../app/userAgent';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { ROLE_LABEL } from '../../app/labels';
import { useDocumentTitle } from '../../router';
import { LANGUAGES, THEMES, usePreferenceSaver } from '../../shell/UserMenu';
import { Badge, Button, Card, type Column, ConfirmDialog, EmptyState, Notice, PageHeader, PasswordField, RadioCards, Select, Table, TextField, useInvalidFocus, useToast } from '../../ui';
import { PasswordPolicy, passwordProblemText } from '../auth/PasswordPolicy';

function PersonalCard() {
  const i18n = useI18n();
  const { t } = i18n;
  const user = useUser();
  const { setUser } = useSession();
  const { departments } = useWorkspace();
  const toast = useToast();
  const [name, setName] = useState(user.name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameFormRef = useInvalidFocus(error);
  const mine = departments.filter((d) => user.department_ids.includes(d.id));

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) { setError(t('auth.error.name')); return; }
    setBusy(true);
    setError(null);
    try {
      setUser((await updateMe({ name: name.trim() })).user);
      toast.success(t('profile.saved'));
    } catch (err) {
      setError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t('profile.personal')} description={t('profile.personalDesc')}>
      <form ref={nameFormRef} className="ws-form ws-form--inline" onSubmit={save} noValidate>
        <TextField label={t('field.name')} value={name} onChange={(e) => setName(e.target.value)} error={error} autoComplete="name" maxLength={200} required />
        <Button type="submit" variant="primary" busy={busy} disabled={name.trim() === user.name}>{t('common.save')}</Button>
      </form>
      <dl className="ws-dl ws-dl--grid">
        <dt>{t('field.email')}</dt><dd>{user.email}</dd>
        <dt>{t('field.role')}</dt><dd><Badge tone={user.role === 'admin' ? 'accent' : 'neutral'}>{t(ROLE_LABEL[user.role])}</Badge></dd>
        <dt>{t('field.departments')}</dt>
        <dd>{mine.length ? <span className="ws-badge-list">{mine.map((d) => <Badge key={d.id}>{d.name}</Badge>)}</span> : <span className="ws-muted">{t('profile.noDepartments')}</span>}</dd>
      </dl>
    </Card>
  );
}

function PreferencesCard() {
  const { t } = useI18n();
  const user = useUser();
  const { saveLocale, saveTheme } = usePreferenceSaver();
  return (
    <Card title={t('profile.preferences')} description={t('profile.preferencesDesc')}>
      <div className="ws-stack">
        <Select
          label={t('userMenu.language')} value={user.locale} onChange={(e) => void saveLocale(e.target.value as Locale)}
          options={LANGUAGES.map((l) => ({ value: l, label: t(`language.${l}`), lang: l }))}
        />
        <RadioCards<Theme>
          name="theme" legend={t('userMenu.theme')} value={user.theme} onChange={(v) => void saveTheme(v)}
          options={THEMES.map((theme) => ({ value: theme, label: t(`theme.${theme}`), description: t(`theme.${theme}.desc`) }))}
        />
      </div>
    </Card>
  );
}

function PasswordCard({ onChanged }: { onChanged: () => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const user = useUser();
  const toast = useToast();
  const policyId = `p${useId().replace(/:/g, '')}`;
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const formRef = useInvalidFocus(errors);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!current) found.current = t('auth.error.passwordRequired');
    const weak = passwordProblemText(t, next, user.email);
    if (weak) found.next = weak;
    else if (next === current) found.next = t('profile.password.same');
    if (!confirm) found.confirm = t('password.confirmRequired');
    else if (confirm !== next) found.confirm = t('password.mismatch');
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await changePassword({ current_password: current, new_password: next });
      setCurrent(''); setNext(''); setConfirm('');
      toast.success(t('profile.password.changed'));
      onChanged();
    } catch (err) {
      const code = errorCode(err);
      const message = describeError(i18n, err);
      if (code === 'weak_password' || errorField(err) === 'new_password') setErrors({ next: message });
      else if (code === 'invalid_credentials' || code === 'wrong_password' || errorField(err) === 'current_password') {
        setErrors({ current: t('profile.password.wrongCurrent') });
      } else setFormError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t('profile.password')} description={t('profile.passwordDesc')}>
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form ref={formRef} className="ws-form ws-form--narrow" onSubmit={submit} noValidate>
        <input type="email" value={user.email} autoComplete="username" readOnly hidden />
        <PasswordField label={t('field.currentPassword')} value={current} onChange={(e) => setCurrent(e.target.value)} error={errors.current} autoComplete="current-password" maxLength={256} required />
        <PasswordField
          label={t('field.newPassword')} value={next} onChange={(e) => setNext(e.target.value)} error={errors.next}
          autoComplete="new-password" aria-describedby={policyId} maxLength={256} required
        />
        <PasswordPolicy id={policyId} password={next} email={user.email} />
        <PasswordField label={t('field.confirm')} value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} autoComplete="new-password" maxLength={256} required />
        <div><Button type="submit" variant="primary" busy={busy}>{t('profile.password.submit')}</Button></div>
      </form>
    </Card>
  );
}

function SessionsCard({ sessions }: { sessions: AsyncState<ActiveSession[]> }) {
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  const toast = useToast();
  const [revoking, setRevoking] = useState<ActiveSession | null>(null);
  const [revokeAll, setRevokeAll] = useState(false);
  const others = (sessions.data ?? []).filter((s) => !s.current).length;

  const deviceLabel = (session: ActiveSession) => {
    const { browser, os } = summarizeAgent(session.user_agent);
    if (browser && os) return t('profile.sessions.device', { browser, os });
    return browser ?? os ?? t('profile.sessions.unknownDevice');
  };

  const columns: Column<ActiveSession>[] = [
    {
      key: 'device', header: t('profile.sessions.colDevice'),
      render: (s) => (
        <span className="ws-cell-stack">
          <span className="ws-strong">{deviceLabel(s)} {s.current && <Badge tone="success">{t('profile.sessions.current')}</Badge>}</span>
          <span className="ws-muted ws-small">{t(`via.${s.via}`)}</span>
        </span>
      ),
    },
    { key: 'ip', header: t('profile.sessions.colIp'), render: (s) => <span className="ws-mono">{s.ip || '—'}</span>, secondary: true },
    { key: 'created', header: t('profile.sessions.colCreated'), render: (s) => <span className="ws-mono ws-small">{fmt.dateTime(s.created_at)}</span>, secondary: true },
    { key: 'seen', header: t('profile.sessions.colSeen'), render: (s) => fmt.relative(s.last_seen_at) },
    {
      key: 'actions', header: '', srHeader: t('common.actions'), align: 'end',
      render: (s) => (s.current ? null : (
        <Button size="sm" variant="danger-ghost" onClick={() => setRevoking(s)}>{t('profile.sessions.revoke')}</Button>
      )),
    },
  ];

  return (
    <Card
      title={t('profile.sessions')}
      description={t('profile.sessionsDesc')}
      actions={<Button size="sm" variant="secondary" icon="logout" disabled={others === 0} onClick={() => setRevokeAll(true)}>{t('profile.sessions.revokeOthers')}</Button>}
    >
      {sessions.error ? (
        <Notice tone="danger" action={<Button size="sm" icon="refresh" onClick={() => void sessions.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, sessions.error)}
        </Notice>
      ) : (
        <Table
          caption={t('profile.sessions')} columns={columns} rows={sessions.data} rowKey={(s) => s.id} loading={sessions.loading}
          empty={<EmptyState compact icon="lock" title={t('profile.sessions.empty')} />}
        />
      )}
      <ConfirmDialog
        open={revoking !== null} onClose={() => setRevoking(null)} title={t('profile.sessions.revokeTitle')}
        body={revoking ? t('profile.sessions.revokeBody', { device: deviceLabel(revoking) }) : ''}
        confirmLabel={t('profile.sessions.revoke')}
        onConfirm={async () => {
          if (!revoking) return;
          await revokeMySession(revoking.id);
          toast.success(t('profile.sessions.revoked'));
          await sessions.reload();
        }}
      />
      <ConfirmDialog
        open={revokeAll} onClose={() => setRevokeAll(false)} title={t('profile.sessions.revokeOthersTitle')}
        body={tn('profile.sessions.revokeOthersBody', others)} confirmLabel={t('profile.sessions.revokeOthers')}
        onConfirm={async () => {
          const { revoked } = await revokeOtherSessions();
          toast.success(tn('profile.sessions.revokedMany', revoked));
          await sessions.reload();
        }}
      />
    </Card>
  );
}

export function ProfilePage() {
  const { t } = useI18n();
  useDocumentTitle(t('profile.title'));
  const sessions = useAsync(async () => (await listMySessions()).sessions, []);
  return (
    <>
      <PageHeader title={t('profile.title')} description={t('profile.desc')} />
      <div className="ws-grid ws-grid--2">
        <PersonalCard />
        <PreferencesCard />
      </div>
      <PasswordCard onChanged={() => void sessions.reload()} />
      <SessionsCard sessions={sessions} />
    </>
  );
}
