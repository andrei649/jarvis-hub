/* Admin → Users: list, invite, edit, invite/reset links, disable and enable.

   Links: the server returns an invite URL only when it issues one (on create, or on request);
   issuing a new one revokes the person's older unused links, so "copy link" always means
   "issue a fresh link" and the dialog says so before doing it. Email delivery is offered only
   when SMTP is configured; otherwise the admin copies the link and sends it themselves. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createUser, getSmtp, issueInvite, listAdminDepartments, listUsers, smtpConfigured, updateUser } from '../../api/admin';
import type { AdminDepartment, AdminUser, CreateUserResponse, IssueInviteResponse, Role } from '../../api/types';
import { describeCode, describeError, errorCode, errorField } from '../../app/errors';
import { copyText, useAsync } from '../../app/hooks';
import { ROLE_HINT, ROLE_LABEL, ROLES, STATUS_LABEL } from '../../app/labels';
import { getMe } from '../../api/account';
import { useSession, useUser } from '../../app/session';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import {
  Avatar, Badge, Button, Checkbox, ConfirmDialog, Dialog, EmptyState, IconButton, Menu, Notice, Select, Table,
  TextField, useToast, type Column, type MenuEntry, type Tone,
} from '../../ui';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STATUS_TONE: Record<AdminUser['status'], Tone> = { active: 'success', invited: 'warning', disabled: 'neutral' };

type StatusFilter = 'all' | AdminUser['status'];

/** The link panel shown after a link is issued: copy button, delivery outcome. */
function InviteLinkResult({ url, emailed, emailError, email }: { url: string; emailed: boolean; emailError?: string; email: string }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const copyButton = useRef<HTMLButtonElement>(null);
  // The panel replaces the form that held focus; put focus on the next useful control.
  useEffect(() => { copyButton.current?.focus(); }, []);
  const copy = async () => {
    if (await copyText(url)) toast.success(t('users.link.copied'));
    else { input.current?.select(); toast.info(t('users.link.copyManual')); }
  };
  return (
    <div className="ws-stack">
      <div className="ws-copy-row">
        <TextField ref={input} label={t('users.link.label')} value={url} readOnly inputClassName="ws-mono" onFocus={(e) => e.currentTarget.select()} />
        <Button ref={copyButton} icon="copy" onClick={copy}>{t('common.copy')}</Button>
      </div>
      {emailed
        ? <Notice tone="success">{t('users.link.emailed', { email })}</Notice>
        : <Notice tone={emailError ? 'warning' : 'accent'}>
            {emailError ? t('users.link.emailFailed') : t('users.link.manual')}
            {emailError && <p className="ws-small">{describeCode(i18n, emailError)}</p>}
          </Notice>}
      <p className="ws-muted ws-small">{t('users.link.validity')}</p>
    </div>
  );
}

function DepartmentChecklist({ departments, value, onChange, error }: {
  departments: AdminDepartment[];
  value: number[];
  onChange: (ids: number[]) => void;
  error?: string;
}) {
  const { t } = useI18n();
  const active = departments.filter((d) => !d.archived || value.includes(d.id));
  return (
    <fieldset className={['ws-fieldset', 'ws-checklist', error && 'has-error'].filter(Boolean).join(' ')} aria-describedby={error ? 'dept-error' : undefined}>
      <legend className="ws-field__label">{t('field.departments')}</legend>
      {active.length === 0 && <p className="ws-muted">{t('users.form.noDepartments')}</p>}
      <div className="ws-checklist__grid">
        {active.map((d) => (
          <Checkbox
            key={d.id} label={d.name} checked={value.includes(d.id)}
            onChange={(e) => onChange(e.target.checked ? [...value, d.id] : value.filter((id) => id !== d.id))}
          />
        ))}
      </div>
      {error && <p className="ws-field__error" id="dept-error">{error}</p>}
    </fieldset>
  );
}

function RoleSelect({ value, onChange }: { value: Role; onChange: (role: Role) => void }) {
  const { t } = useI18n();
  return (
    <Select
      label={t('field.role')} value={value} hint={t(ROLE_HINT[value])} onChange={(e) => onChange(e.target.value as Role)}
      options={ROLES.map((role) => ({ value: role, label: t(ROLE_LABEL[role]) }))}
    />
  );
}

/** Mounted only while open, so every invitation starts from an empty form. */
function InviteDialog({ onClose, departments, smtpReady, onCreated }: {
  onClose: () => void;
  departments: AdminDepartment[];
  smtpReady: boolean;
  onCreated: () => void;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('member');
  const [deptIds, setDeptIds] = useState<number[]>([]);
  const [sendEmail, setSendEmail] = useState(smtpReady);
  const [errors, setErrors] = useState<{ email?: string; name?: string; departments?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CreateUserResponse | null>(null);
  const close = onClose;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!EMAIL_PATTERN.test(email.trim())) found.email = t('auth.error.email');
    if (!name.trim()) found.name = t('auth.error.name');
    if (deptIds.length === 0) found.departments = t('users.form.pickDepartment');
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const created = await createUser({ email: email.trim(), name: name.trim(), role, department_ids: deptIds, send_email: smtpReady && sendEmail });
      setResult(created);
      onCreated();
    } catch (err) {
      const field = errorField(err);
      const message = describeError(i18n, err);
      if (field === 'email' || errorCode(err) === 'email_taken') setErrors({ email: message });
      else if (field === 'name') setErrors({ name: message });
      else if (field === 'department_ids') setErrors({ departments: message });
      else setFormError(message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <Dialog open onClose={close} title={t('users.invite.doneTitle')} description={t('users.invite.doneDesc', { name: result.user.name })}
        footer={<Button variant="primary" onClick={close}>{t('common.done')}</Button>}>
        <InviteLinkResult url={result.invite_url} emailed={result.emailed} emailError={result.email_error} email={result.user.email} />
      </Dialog>
    );
  }

  return (
    <Dialog
      open onClose={close} title={t('users.invite.title')} description={t('users.invite.desc')} busy={busy} size="lg"
      footer={(
        <>
          <Button onClick={close} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-invite-form" busy={busy} icon="userPlus">{t('users.invite.submit')}</Button>
        </>
      )}
    >
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form id="ws-invite-form" className="ws-form" onSubmit={submit} noValidate>
        <div className="ws-grid ws-grid--2 ws-grid--tight">
          <TextField label={t('field.email')} type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} maxLength={254} required autoComplete="off" />
          <TextField label={t('field.name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={200} required autoComplete="off" />
        </div>
        <RoleSelect value={role} onChange={setRole} />
        <DepartmentChecklist departments={departments} value={deptIds} onChange={setDeptIds} error={errors.departments} />
        <Checkbox
          label={t('users.invite.sendEmail')} checked={smtpReady && sendEmail} disabled={!smtpReady}
          onChange={(e) => setSendEmail(e.target.checked)}
          description={smtpReady ? t('users.invite.sendEmailDesc') : t('users.invite.smtpMissing')}
        />
      </form>
    </Dialog>
  );
}

function EditDialog({ user, onClose, departments, onSaved }: {
  user: AdminUser;
  onClose: () => void;
  departments: AdminDepartment[];
  onSaved: () => void;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [name, setName] = useState(user.name);
  const [role, setRole] = useState<Role>(user.role);
  const [deptIds, setDeptIds] = useState<number[]>(user.department_ids);
  const [errors, setErrors] = useState<{ name?: string; departments?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const close = onClose;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!name.trim()) found.name = t('auth.error.name');
    if (deptIds.length === 0) found.departments = t('users.form.pickDepartment');
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await updateUser(user.id, { name: name.trim(), role, department_ids: deptIds });
      toast.success(t('users.edit.saved'));
      onSaved();
      close();
    } catch (err) {
      setFormError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open onClose={close} title={t('users.edit.title')} description={user.email} busy={busy} size="lg"
      footer={(
        <>
          <Button onClick={close} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-edit-user-form" busy={busy}>{t('common.save')}</Button>
        </>
      )}
    >
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form id="ws-edit-user-form" className="ws-form" onSubmit={submit} noValidate>
        <TextField label={t('field.name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={200} required />
        <RoleSelect value={role} onChange={setRole} />
        {role !== user.role && <Notice tone="warning">{t('users.edit.roleChange')}</Notice>}
        <DepartmentChecklist departments={departments} value={deptIds} onChange={setDeptIds} error={errors.departments} />
      </form>
    </Dialog>
  );
}

function LinkDialog({ user, onClose, smtpReady, onIssued }: { user: AdminUser; onClose: () => void; smtpReady: boolean; onIssued: () => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const [sendEmail, setSendEmail] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IssueInviteResponse | null>(null);
  const isReset = user.status === 'active';
  const close = onClose;

  const issue = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await issueInvite(user.id, smtpReady && sendEmail));
      onIssued();
    } catch (err) {
      setError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open onClose={close} busy={busy}
      title={isReset ? t('users.link.resetTitle') : t('users.link.inviteTitle')}
      description={t('users.link.for', { name: user.name, email: user.email })}
      footer={result
        ? <Button variant="primary" onClick={close}>{t('common.done')}</Button>
        : (
          <>
            <Button onClick={close} disabled={busy}>{t('common.cancel')}</Button>
            <Button variant="primary" icon="link" busy={busy} onClick={issue}>{t('users.link.issue')}</Button>
          </>
        )}
    >
      {result ? (
        <InviteLinkResult url={result.invite_url} emailed={result.emailed} emailError={result.email_error} email={user.email} />
      ) : (
        <div className="ws-stack">
          <p>{isReset ? t('users.link.resetExplain') : t('users.link.inviteExplain')}</p>
          <Checkbox
            label={t('users.invite.sendEmail')} checked={smtpReady && sendEmail} disabled={!smtpReady}
            onChange={(e) => setSendEmail(e.target.checked)}
            description={smtpReady ? undefined : t('users.invite.smtpMissing')}
          />
          {error && <p className="ws-inline-error" role="alert">{error}</p>}
        </div>
      )}
    </Dialog>
  );
}

function pendingInviteText(user: AdminUser, fmt: ReturnType<typeof useI18n>['fmt'], t: ReturnType<typeof useI18n>['t']): string | null {
  const invite = user.pending_invite;
  if (!invite) return null;
  if (typeof invite === 'object' && invite.expires_at) return t('users.pendingUntil', { date: fmt.date(invite.expires_at) });
  return t('users.pending');
}

export function UsersSection() {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const me = useUser();
  const toast = useToast();
  const { refreshDepartments } = useWorkspace();
  const users = useAsync(listUsers, []);
  const departments = useAsync(listAdminDepartments, []);
  const smtp = useAsync(getSmtp, []);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [linkFor, setLinkFor] = useState<AdminUser | null>(null);
  const [toggling, setToggling] = useState<AdminUser | null>(null);

  const smtpReady = Boolean(smtp.data && smtpConfigured(smtp.data));
  const deptName = useMemo(() => new Map((departments.data ?? []).map((d) => [d.id, d.name])), [departments.data]);

  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return (users.data ?? []).filter((u) => (status === 'all' || u.status === status)
      && (!needle || u.name.toLocaleLowerCase().includes(needle) || u.email.toLocaleLowerCase().includes(needle)));
  }, [users.data, search, status]);

  const { setUser } = useSession();
  /** After any change: reload the list and the sidebar; when the admin edited their own
      account (name, departments), refresh the signed-in user so the shell shows it too. */
  const afterChange = (changedId?: number) => {
    void users.reload();
    void refreshDepartments();
    // A failed refresh only delays the shell update to the next session read; the save itself succeeded.
    if (changedId === me.id) getMe().then(({ user }) => setUser(user)).catch(() => undefined);
  };

  const rowMenu = (user: AdminUser): MenuEntry[] => {
    const entries: MenuEntry[] = [{ id: 'edit', label: t('users.action.edit'), icon: 'edit', onSelect: () => setEditing(user) }];
    if (user.status === 'invited') entries.push({ id: 'link', label: t('users.action.inviteLink'), icon: 'link', onSelect: () => setLinkFor(user) });
    if (user.status === 'active') entries.push({ id: 'reset', label: t('users.action.resetLink'), icon: 'key', onSelect: () => setLinkFor(user) });
    entries.push({ kind: 'separator', id: 'sep' });
    if (user.status === 'disabled') entries.push({ id: 'enable', label: t('users.action.enable'), icon: 'restore', onSelect: () => setToggling(user) });
    else entries.push({ id: 'disable', label: t('users.action.disable'), icon: 'ban', danger: true, disabled: user.id === me.id, onSelect: () => setToggling(user) });
    return entries;
  };

  const columns: Column<AdminUser>[] = [
    {
      key: 'user', header: t('users.col.user'),
      render: (u) => (
        <span className="ws-person">
          <Avatar name={u.name} size={32} />
          <span className="ws-cell-stack">
            <span className="ws-strong">{u.name}{u.id === me.id && <span className="ws-muted"> {t('users.you')}</span>}</span>
            <span className="ws-muted ws-small">{u.email}</span>
          </span>
        </span>
      ),
    },
    { key: 'role', header: t('field.role'), render: (u) => <Badge tone={u.role === 'admin' ? 'accent' : 'neutral'}>{t(ROLE_LABEL[u.role])}</Badge> },
    {
      key: 'departments', header: t('field.departments'), secondary: true,
      render: (u) => (u.department_ids.length
        ? <span className="ws-badge-list">{u.department_ids.map((id) => <Badge key={id}>{deptName.get(id) ?? `#${id}`}</Badge>)}</span>
        : <span className="ws-muted">—</span>),
    },
    {
      key: 'status', header: t('users.col.status'),
      render: (u) => (
        <span className="ws-cell-stack">
          <Badge tone={STATUS_TONE[u.status]} dot>{t(STATUS_LABEL[u.status])}</Badge>
          {u.status === 'invited' && pendingInviteText(u, fmt, t) && <span className="ws-muted ws-small">{pendingInviteText(u, fmt, t)}</span>}
        </span>
      ),
    },
    {
      key: 'login', header: t('users.col.lastLogin'), secondary: true,
      render: (u) => (u.last_login_at ? <span title={fmt.dateTime(u.last_login_at)}>{fmt.relative(u.last_login_at)}</span> : <span className="ws-muted">{t('users.never')}</span>),
    },
    {
      key: 'actions', header: '', srHeader: t('common.actions'), align: 'end', width: '56px',
      render: (u) => (
        <Menu
          label={t('users.actionsFor', { name: u.name })} items={rowMenu(u)}
          trigger={(props) => <IconButton icon="more" label={t('users.actionsFor', { name: u.name })} {...props} />}
        />
      ),
    },
  ];

  const loadError = users.error ?? departments.error;
  return (
    <>
      <div className="ws-toolbar">
        <TextField
          className="ws-toolbar__search" label={t('users.search')} type="search" value={search}
          onChange={(e) => setSearch(e.target.value)} placeholder={t('users.searchPlaceholder')}
        />
        <Select
          className="ws-toolbar__filter" label={t('users.col.status')} value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}
          options={[
            { value: 'all', label: t('users.filter.all') }, { value: 'active', label: t('status.active') },
            { value: 'invited', label: t('status.invited') }, { value: 'disabled', label: t('status.disabled') },
          ]}
        />
        <div className="ws-toolbar__end">
          <Button variant="primary" icon="userPlus" onClick={() => setInviting(true)} disabled={!departments.data}>{t('users.invite.open')}</Button>
        </div>
      </div>
      {smtp.data && !smtpReady && <Notice tone="accent">{t('users.smtpNotice')}</Notice>}
      {loadError ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => { void users.reload(); void departments.reload(); }}>{t('common.retry')}</Button>}>
          {describeError(i18n, loadError)}
        </Notice>
      ) : (
        <Table
          caption={t('admin.users')} columns={columns} rows={users.data ? visible : null} rowKey={(u) => u.id}
          loading={users.loading} rowClassName={(u) => (u.status === 'disabled' ? 'is-muted' : undefined)}
          empty={(users.data?.length ?? 0) > 0
            ? <EmptyState compact icon="search" title={t('users.noMatch')} />
            : <EmptyState icon="users" title={t('users.empty')} body={t('users.emptyBody')} />}
        />
      )}
      {inviting && <InviteDialog onClose={() => setInviting(false)} departments={departments.data ?? []} smtpReady={smtpReady} onCreated={() => afterChange()} />}
      {editing && <EditDialog key={editing.id} user={editing} onClose={() => setEditing(null)} departments={departments.data ?? []} onSaved={() => afterChange(editing.id)} />}
      {linkFor && <LinkDialog key={linkFor.id} user={linkFor} onClose={() => setLinkFor(null)} smtpReady={smtpReady} onIssued={() => void users.reload()} />}
      <ConfirmDialog
        open={toggling !== null} onClose={() => setToggling(null)}
        title={toggling?.status === 'disabled' ? t('users.enable.title') : t('users.disable.title')}
        body={toggling ? t(toggling.status === 'disabled' ? 'users.enable.body' : 'users.disable.body', { name: toggling.name }) : ''}
        confirmLabel={toggling?.status === 'disabled' ? t('users.action.enable') : t('users.action.disable')}
        tone={toggling?.status === 'disabled' ? 'primary' : 'danger'}
        onConfirm={async () => {
          if (!toggling) return;
          const enabling = toggling.status === 'disabled';
          await updateUser(toggling.id, { status: enabling ? 'active' : 'disabled' });
          toast.success(t(enabling ? 'users.enable.done' : 'users.disable.done', { name: toggling.name }));
          afterChange(toggling.id);
        }}
      />
    </>
  );
}
