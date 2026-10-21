/* Review fixes in the admin console (frontend fixer, QA round 3).

   F3: the invite and edit-user dialogs, the department drawer and the organisation and SMTP
   forms keep what was typed when the session ends under the admin (the shell unmounts, as the
   sign-in screen replaces it) and give it back after signing in again, with a note; the draft
   is dropped once saved or cancelled, and the SMTP password is never written to storage.
   UX-13: the audit drawer translates the codes a detail records (`via: password`, a login
   failure's reason, a role change's before / after) and names the scheduler.
   OPS2-01 follow-up: a verified chain says how many rows a re-key left unverifiable, the
   `audit.rekeyed` action has a label, and `audit_key_mismatch` reads as a sentence. */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkspaceApiError } from '../../api/client';
import { describeError } from '../../app/errors';
import { DICTIONARIES, makeFormatters, translate, translatePlural, type I18n, type MessageKey } from '../../i18n';
import { renderApp } from '../../test/render';
import { ADMIN_DEPARTMENTS, apiError, json, makeAdminUser, makeUser, mockFetch, ORG, shellRoutes, SIGNED_OUT, signedIn, type RouteHandler } from '../../test/mockApi';

const SMTP_OK = { host: 'smtp.acme.ro', port: 587, security: 'starttls', username: 'nerva', from_address: 'nerva@acme.ro', from_name: 'Nerva', allowed_domains: [], has_password: true };
const COLLEAGUE = makeAdminUser({ id: 2, email: 'ion@acme.ro', name: 'Ion Ionescu', role: 'member', department_ids: [2] });
const NOTE = /Am păstrat ce scriseseși și nu salvaseși/;

function boot(path: string, routes: Record<string, RouteHandler> = {}, user = makeUser()) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(user),
    ...shellRoutes(),
    'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS },
    'GET /api/workspace/admin/users': { users: [makeAdminUser(), COLLEAGUE] },
    'GET /api/workspace/admin/smtp': SMTP_OK,
    'GET /api/workspace/admin/org': ORG,
    'GET /api/workspace/admin/audit': { items: [], next_before_id: null },
    ...routes,
  });
  renderApp(path);
  return mock;
}

/** The session ends (the shell unmounts as the sign-in screen replaces it), then comes back. */
function sessionEndsAndReturns(path: string, routes: Record<string, RouteHandler> = {}, user = makeUser()) {
  cleanup();
  return boot(path, routes, user);
}

async function openInvite() {
  const button = await screen.findByRole('button', { name: 'Invită utilizator' }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  return screen.findByRole('dialog', { name: 'Invită un utilizator' });
}

async function openEdit(name: string) {
  fireEvent.click(await screen.findByRole('button', { name: `Acțiuni pentru ${name}` }));
  fireEvent.click(within(screen.getByRole('menu', { name: `Acțiuni pentru ${name}` })).getByRole('menuitem', { name: 'Editează' }));
  return screen.findByRole('dialog', { name: 'Editează utilizatorul' });
}

function storedDrafts(): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < window.sessionStorage.length; i += 1) {
    const key = window.sessionStorage.key(i) as string;
    if (key.startsWith('nerva.workspace.draft.')) out[key] = window.sessionStorage.getItem(key) as string;
  }
  return out;
}

describe('Admin → unsaved text survives the session ending (F3)', () => {
  it('invite dialog: restored with a note after signing in again, dropped once the invitation exists', async () => {
    boot('/workspace/admin/users');
    let dialog = await openInvite();
    expect(within(dialog).queryByText(NOTE)).toBeNull();
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: 'maria@acme.ro' } });
    fireEvent.change(within(dialog).getByLabelText(/^Nume/), { target: { value: 'Maria Pop' } });
    fireEvent.change(within(dialog).getByLabelText(/^Rol/), { target: { value: 'approver' } });
    fireEvent.click(within(dialog).getByLabelText('Juridic'));

    const mock = sessionEndsAndReturns('/workspace/admin/users');
    mock.on('POST /api/workspace/admin/users', json(201, {
      user: makeAdminUser({ id: 9, email: 'maria@acme.ro', name: 'Maria Pop', role: 'approver', status: 'invited', department_ids: [2] }),
      invite_url: 'https://hub/workspace/invite#t=abc', emailed: true,
    }));
    dialog = await openInvite();
    expect(within(dialog).getByText(NOTE)).toBeTruthy();
    expect((within(dialog).getByLabelText(/^Email/) as HTMLInputElement).value).toBe('maria@acme.ro');
    expect((within(dialog).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('Maria Pop');
    expect((within(dialog).getByLabelText(/^Rol/) as HTMLSelectElement).value).toBe('approver');
    expect((within(dialog).getByLabelText('Juridic') as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Trimite invitația' }));
    const done = await screen.findByRole('dialog', { name: 'Invitație creată' });
    expect(mock.find('POST', '/api/workspace/admin/users')[0].body).toEqual({
      email: 'maria@acme.ro', name: 'Maria Pop', role: 'approver', department_ids: [2], send_email: true,
    });
    fireEvent.click(within(done).getByRole('button', { name: 'Gata' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Invitație creată' })).toBeNull());

    dialog = await openInvite();
    expect(within(dialog).queryByText(NOTE)).toBeNull();
    expect((within(dialog).getByLabelText(/^Email/) as HTMLInputElement).value).toBe('');
    expect(storedDrafts()).toEqual({});
  });

  it('edit-user dialog: restored after signing in again, dropped on cancel; an unchanged form keeps nothing', async () => {
    boot('/workspace/admin/users');
    let dialog = await openEdit('Ion Ionescu');
    expect(storedDrafts()).toEqual({});
    fireEvent.change(within(dialog).getByLabelText(/^Nume/), { target: { value: 'Ion C. Ionescu' } });
    fireEvent.click(within(dialog).getByLabelText('General'));

    sessionEndsAndReturns('/workspace/admin/users');
    dialog = await openEdit('Ion Ionescu');
    expect(within(dialog).getByText(NOTE)).toBeTruthy();
    expect((within(dialog).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('Ion C. Ionescu');
    expect((within(dialog).getByLabelText('General') as HTMLInputElement).checked).toBe(true);
    expect((within(dialog).getByLabelText('Juridic') as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Renunță' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Editează utilizatorul' })).toBeNull());
    expect(storedDrafts()).toEqual({});

    dialog = await openEdit('Ion Ionescu');
    expect(within(dialog).queryByText(NOTE)).toBeNull();
    expect((within(dialog).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('Ion Ionescu');
  });

  it('department drawer: the assistant instructions come back after signing in again and go once saved', async () => {
    const mock = boot('/workspace/admin/departments');
    fireEvent.click(await screen.findByRole('button', { name: 'Departament nou' }));
    let drawer = await screen.findByRole('dialog', { name: 'Departament nou' });
    fireEvent.change(within(drawer).getByLabelText(/^Nume/), { target: { value: 'Vânzări' } });
    fireEvent.change(within(drawer).getByLabelText(/^Instrucțiuni pentru asistent/), { target: { value: 'Răspunde scurt, cu cifre.' } });

    const again = sessionEndsAndReturns('/workspace/admin/departments');
    again.on('POST /api/workspace/admin/departments', json(201, { ...ADMIN_DEPARTMENTS[0], id: 3, slug: 'vanzari', name: 'Vânzări' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Departament nou' }));
    drawer = await screen.findByRole('dialog', { name: 'Departament nou' });
    expect(within(drawer).getByText(NOTE)).toBeTruthy();
    expect((within(drawer).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('Vânzări');
    expect((within(drawer).getByLabelText(/^Instrucțiuni pentru asistent/) as HTMLTextAreaElement).value).toBe('Răspunde scurt, cu cifre.');
    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează departamentul' }));
    await waitFor(() => expect(again.find('POST', '/api/workspace/admin/departments')).toHaveLength(1));
    expect(again.find('POST', '/api/workspace/admin/departments')[0].body).toEqual({ name: 'Vânzări', description: '', assistant_instructions: 'Răspunde scurt, cu cifre.' });
    await waitFor(() => expect(storedDrafts()).toEqual({}));
    expect(mock.find('POST', '/api/workspace/admin/departments')).toHaveLength(0);
  });

  it('organisation form: unsaved changes come back with a note, and „Renunță la modificări” restores the saved values', async () => {
    boot('/workspace/admin/organisation');
    fireEvent.change(await screen.findByLabelText(/^Numele organizației/), { target: { value: 'Acme Distribuție SRL' } });

    sessionEndsAndReturns('/workspace/admin/organisation');
    const name = await screen.findByLabelText(/^Numele organizației/) as HTMLInputElement;
    expect(name.value).toBe('Acme Distribuție SRL');
    expect(screen.getByText(/Am păstrat modificările pe care nu le salvaseși/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Renunță la modificări' }));
    await waitFor(() => expect((screen.getByLabelText(/^Numele organizației/) as HTMLInputElement).value).toBe('Acme'));
    expect(screen.queryByText(/Am păstrat modificările/)).toBeNull();
    expect(storedDrafts()).toEqual({});

    sessionEndsAndReturns('/workspace/admin/organisation');
    expect(((await screen.findByLabelText(/^Numele organizației/)) as HTMLInputElement).value).toBe('Acme');
    expect(screen.queryByText(/Am păstrat modificările/)).toBeNull();
  });

  it('SMTP form: every field but the password comes back; the password is never written to browser storage', async () => {
    boot('/workspace/admin/email');
    fireEvent.change(await screen.findByLabelText(/^Server SMTP/), { target: { value: 'mail.acme.ro' } });
    fireEvent.change(screen.getByLabelText(/^Parolă/), { target: { value: 'parola-smtp-secreta' } });
    expect(Object.values(storedDrafts()).join('')).not.toContain('parola-smtp-secreta');
    expect(Object.values(storedDrafts()).join('')).toContain('mail.acme.ro');

    sessionEndsAndReturns('/workspace/admin/email');
    expect(((await screen.findByLabelText(/^Server SMTP/)) as HTMLInputElement).value).toBe('mail.acme.ro');
    expect((screen.getByLabelText(/^Parolă/) as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/Parola nu se păstrează niciodată/)).toBeTruthy();
  });

  it('keeps one admin’s draft from another user signing in on the same tab', async () => {
    boot('/workspace/admin/users');
    const dialog = await openInvite();
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: 'secret@acme.ro' } });
    sessionEndsAndReturns('/workspace/admin/users', {}, makeUser({ id: 7, email: 'alt@acme.ro', name: 'Alt Admin' }));
    const other = await openInvite();
    expect((within(other).getByLabelText(/^Email/) as HTMLInputElement).value).toBe('');
    expect(within(other).queryByText(NOTE)).toBeNull();
  });
});

describe('Admin → Audit details read as words (UX-13)', () => {
  const login = { id: 21, ts: 1_760_000_300, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'auth.login', target_type: 'user', target_id: '1', department_id: null, ip: '10.0.0.5', details: { via: 'password' } };
  const failed = { id: 22, ts: 1_760_000_200, actor_user_id: null, actor_email: 'x@acme.ro', actor_name: null, action: 'auth.login_failed', target_type: 'user', target_id: '', department_id: null, ip: '10.0.0.6', details: { via: 'sso', reason: 'unknown_user' } };
  const promoted = { id: 23, ts: 1_760_000_100, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'user.updated', target_type: 'user', target_id: '2', department_id: null, ip: '', details: { fields: ['role'], from: 'member', to: 'approver' } };
  const run = { id: 24, ts: 1_760_000_000, actor_user_id: null, actor_email: 'scheduler', actor_name: null, action: 'report.run_started', target_type: 'report_run', target_id: '4', department_id: 2, ip: '', details: { report_id: 3, trigger: 'schedule' } };
  const smtp = { id: 26, ts: 1_759_999_800, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'smtp.updated', target_type: 'org', target_id: '1', department_id: null, ip: '', details: { host: 'smtp.acme.ro', security: 'none', credential: 'kept' } };
  const immediate = { id: 27, ts: 1_759_999_700, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'approval.approved', target_type: 'approval', target_id: '3', department_id: null, ip: '', details: { kind: 'document.company_publish', immediate: true, note: 'admin action' } };
  const emailed = { id: 25, ts: 1_759_999_900, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'email.sent', target_type: 'approval', target_id: '9', department_id: 1, ip: '', details: { source: { type: 'message', id: 12 }, to: ['ion@client.ro'] } };

  async function openEntry(id: number, label: RegExp) {
    const table = await screen.findByRole('table', { name: 'Audit' });
    fireEvent.click(await within(table).findByRole('button', { name: label }));
    return screen.findByRole('dialog', { name: `Intrarea #${id} din jurnal` });
  }

  it('translates the sign-in method, a failure’s reason, a role change, the trigger and the email’s source', async () => {
    boot('/workspace/admin/audit', {
      'GET /api/workspace/admin/users': { users: [makeAdminUser(), COLLEAGUE] },
      'GET /api/workspace/admin/audit': { items: [login, failed, promoted, run, emailed, smtp, immediate], next_before_id: null },
    });
    let drawer = await openEntry(21, /^Detaliile intrării „Conectare”/);
    expect(within(drawer).getByText('Mod de conectare')).toBeTruthy();
    expect(within(drawer).getByText('Parolă')).toBeTruthy();
    expect(within(drawer).queryByText('password')).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    drawer = await openEntry(22, /^Detaliile intrării „Conectare eșuată”/);
    expect(within(drawer).getByText('Contul companiei (SSO)')).toBeTruthy();
    expect(within(drawer).getByText('Nu există un cont cu această adresă')).toBeTruthy();
    expect(within(drawer).queryByText('unknown_user')).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    drawer = await openEntry(23, /^Detaliile intrării „Utilizator modificat”/);
    expect(within(drawer).getByText('Înainte')).toBeTruthy();
    expect(within(drawer).getByText('Membru')).toBeTruthy();
    expect(within(drawer).getByText('După')).toBeTruthy();
    expect(within(drawer).getByText('Aprobator')).toBeTruthy();
    expect(within(drawer).queryByText('Expeditor')).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    const table = screen.getByRole('table', { name: 'Audit' });
    expect(within(table).getByText('Planificatorul automat')).toBeTruthy();
    expect(within(table).queryByText('scheduler')).toBeNull();
    drawer = await openEntry(24, /^Detaliile intrării „Rulare de raport pornită”/);
    expect(within(drawer).getByText('Programată')).toBeTruthy();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    drawer = await openEntry(25, /^Detaliile intrării „Email trimis”/);
    expect(within(drawer).getByText('Mesajul #12')).toBeTruthy();
    expect(within(drawer).getByText('Către')).toBeTruthy();
    expect(within(drawer).getByText('ion@client.ro')).toBeTruthy();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    drawer = await openEntry(26, /^Detaliile intrării „Setări de email modificate”/);
    expect(within(drawer).getByText('Fără criptare')).toBeTruthy();
    expect(within(drawer).getByText('Parola a rămas neschimbată')).toBeTruthy();
    expect(within(drawer).queryByText('kept')).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);

    drawer = await openEntry(27, /^Detaliile intrării „Cerere aprobată”/);
    expect(within(drawer).getByText('Aplicată imediat: cererea unui administrator')).toBeTruthy();
    expect(within(drawer).queryByText('admin action')).toBeNull();
  });
});

describe('Admin → Audit after a re-key (OPS2-01 follow-up)', () => {
  it('says how many earlier rows a re-key left unverifiable, in the notice and the status region', async () => {
    boot('/workspace/admin/audit', {
      'GET /api/workspace/admin/audit/verify': { ok: true, checked: 2, broken_at: null, keyed: true, key_mismatch: false, unverified: 3, rekeyed_at: 4 },
    });
    await screen.findByText('Jurnalul este gol');
    const region = screen.getAllByRole('status').find((el) => el.classList.contains('ws-sr-only') && el.textContent === '') as HTMLElement;
    fireEvent.click(screen.getByRole('button', { name: 'Verifică lanțul' }));
    const line = '3 intrări de dinaintea schimbării cheii de audit (intrarea #4) au fost semnate cu cheia pierdută și nu mai pot fi verificate; o modificare ulterioară a lor tot s-ar observa.';
    expect(await screen.findByText(line)).toBeTruthy();
    expect(screen.getByText('Lanțul de audit este intact')).toBeTruthy();
    await waitFor(() => expect(region.textContent).toContain(line));
  });

  it('says nothing more for a trail that was never re-keyed, or an older server without the fields', async () => {
    boot('/workspace/admin/audit', { 'GET /api/workspace/admin/audit/verify': { ok: true, checked: 5, broken_at: null, keyed: true, key_mismatch: false } });
    await screen.findByText('Jurnalul este gol');
    fireEvent.click(screen.getByRole('button', { name: 'Verifică lanțul' }));
    expect(await screen.findByText('Am verificat 5 intrări; niciuna nu a fost modificată.')).toBeTruthy();
    expect(screen.queryByText(/schimbării cheii de audit/)).toBeNull();
  });

  it('labels the re-key row and names the server command line as its actor', async () => {
    const rekeyed = {
      id: 4, ts: 1_760_000_400, actor_user_id: null, actor_email: 'cli', actor_name: null, action: 'audit.rekeyed', target_type: 'audit', target_id: '3', department_id: null, ip: '',
      details: { from_key_fp: 'aaaa1111', to_key_fp: 'bbbb2222', through_id: 3, rows: 3, unverified: 3, digest: 'c0ffee' },
    };
    boot('/workspace/admin/audit', { 'GET /api/workspace/admin/audit': { items: [rekeyed], next_before_id: null } });
    const table = await screen.findByRole('table', { name: 'Audit' });
    expect(await within(table).findByText('Cheia de audit înlocuită (din linia de comandă)')).toBeTruthy();
    expect(within(table).getByText('Jurnalul de audit, până la intrarea #3')).toBeTruthy();
    expect(within(table).getByText('Linia de comandă a serverului')).toBeTruthy();
    fireEvent.click(within(table).getByRole('button', { name: /^Detaliile intrării „Cheia de audit înlocuită/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Intrarea #4 din jurnal' });
    expect(within(drawer).getByText('Cheia veche (amprentă)')).toBeTruthy();
    expect(within(drawer).getByText('Intrări care nu mai pot fi verificate')).toBeTruthy();
  });
});

describe('audit_key_mismatch (OPS2-01 follow-up)', () => {
  const i18nFor = (locale: 'ro' | 'en'): I18n => ({
    locale, setLocale: () => undefined, t: (key, vars) => translate(locale, key, vars),
    tn: (key, count, vars) => translatePlural(locale, key, count, vars),
    has: (key): key is MessageKey => key in DICTIONARIES[locale], fmt: makeFormatters(locale),
  });

  it('reads as a sentence in both languages, never as a bare code', () => {
    const err = new WorkspaceApiError('audit_key_mismatch', 'the audit key does not match the trail', 503);
    expect(describeError(i18nFor('ro'), err)).toMatch(/^Jurnalul de audit nu poate fi scris: serverul folosește altă cheie de audit/);
    expect(describeError(i18nFor('en'), err)).toMatch(/^The audit log cannot be written: the server is using a different audit key/);
  });

  it('is shown on the sign-in page when the server refuses the sign-in for it', async () => {
    mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/login': apiError(503, 'audit_key_mismatch'),
    });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: 'ana@acme.ro' } });
    fireEvent.change(screen.getByLabelText(/^Parolă/), { target: { value: 'o-parola-buna-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Conectează-te' }));
    expect(await screen.findByText(/serverul folosește altă cheie de audit decât cea cu care a fost scris jurnalul/)).toBeTruthy();
  });
});
