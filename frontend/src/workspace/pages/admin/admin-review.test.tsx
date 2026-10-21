/* Review fixes in the admin console (frontend fixer, QA round 2): the audit trail reads as
   sentences with every recorded detail one click away (UX-05, A11Y-18) and plural-correct
   verification copy announced from a status region that exists before it (UX-08, A11Y-09);
   "Primii pași" checks a pilot's five steps from real data (UX-07); a failed submit moves focus
   to the first invalid field in the invite, department, organisation and email forms
   (A11Y-04); the archived toggle appears only when something is archived (UX-18 g); the
   departments table counts ready documents apart (F10); usage feedback is plural-correct (UX-08). */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render';
import { ADMIN_DEPARTMENTS, makeAdminUser, makeUser, mockFetch, ORG, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';

const SMTP_OK = { host: 'smtp.acme.ro', port: 587, security: 'starttls', username: 'nerva', from_address: 'nerva@acme.ro', from_name: 'Nerva', allowed_domains: [], has_password: true };
const SMTP_NONE = { host: '', port: 0, security: 'starttls', username: '', from_address: '', from_name: '', allowed_domains: [], has_password: false };

function boot(path: string, routes: Record<string, RouteHandler> = {}) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser()),
    ...shellRoutes(),
    'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS },
    'GET /api/workspace/admin/users': { users: [makeAdminUser()] },
    'GET /api/workspace/admin/smtp': SMTP_OK,
    'GET /api/workspace/admin/audit': { items: [], next_before_id: null },
    ...routes,
  });
  renderApp(path);
  return mock;
}

describe('Admin → Audit, readable', () => {
  const prefs = { id: 9, ts: 1_760_000_100, actor_user_id: 2, actor_email: 'ion@acme.ro', actor_name: 'Ion Ionescu', action: 'user.updated', target_type: 'user', target_id: '2', department_id: null, ip: '10.0.0.7', details: { fields: ['theme'], self: true } };
  const run = { id: 8, ts: 1_760_000_000, actor_user_id: null, actor_email: 'scheduler', actor_name: null, action: 'report.run_failed', target_type: 'report_run', target_id: '1', department_id: 2, ip: '', details: { report_id: 3, error_code: 'model_unavailable' } };

  it('names the object and the department in words, with details and IP in a drawer per entry (UX-05, A11Y-18)', async () => {
    boot('/workspace/admin/audit', {
      'GET /api/workspace/admin/users': { users: [makeAdminUser(), makeAdminUser({ id: 2, name: 'Ion Ionescu', email: 'ion@acme.ro' })] },
      'GET /api/workspace/admin/audit': { items: [prefs, run], next_before_id: null },
    });
    const table = await screen.findByRole('table', { name: 'Audit' });
    expect(await within(table).findByText('Preferințe schimbate (temă sau limbă)')).toBeTruthy();
    expect(within(table).getByText('Rularea de raport #1')).toBeTruthy();
    expect(within(table).getByText('Juridic')).toBeTruthy();
    // No raw codes, English types or key=value dumps in the table.
    expect(within(table).queryByText('report.run_failed')).toBeNull();
    expect(within(table).queryByText(/report_run/)).toBeNull();
    expect(within(table).queryByText(/error_code=/)).toBeNull();
    expect(within(table).queryByText('10.0.0.7')).toBeNull();

    fireEvent.click(within(table).getByRole('button', { name: /^Detaliile intrării „Rulare de raport eșuată”/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Intrarea #8 din jurnal' });
    expect(within(drawer).getByText('Motivul eșecului')).toBeTruthy();
    expect(within(drawer).getByText('Modelul AI nu este disponibil acum.')).toBeTruthy();
    expect(within(drawer).getByText('Codul tehnic al acțiunii')).toBeTruthy();
    expect(within(drawer).getByText('report.run_failed')).toBeTruthy();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Intrarea #8 din jurnal' })).toBeNull());

    fireEvent.click(within(table).getByRole('button', { name: /^Detaliile intrării „Preferințe schimbate/ }));
    const second = await screen.findByRole('dialog', { name: 'Intrarea #9 din jurnal' });
    expect(within(second).getByText('10.0.0.7')).toBeTruthy();
    expect(within(second).getByText('Câmpuri modificate')).toBeTruthy();
    expect(within(second).getByText('Temă')).toBeTruthy();
    expect(within(second).getByText('Da')).toBeTruthy();
  });

  it('counts verified entries with the right Romanian plural, announced from a standing status region (UX-08, A11Y-09)', async () => {
    let checked = 39;
    boot('/workspace/admin/audit', { 'GET /api/workspace/admin/audit/verify': () => ({ ok: true, checked, broken_at: null, keyed: true, key_mismatch: false }) });
    await screen.findByText('Jurnalul este gol');
    const region = screen.getAllByRole('status').find((el) => el.classList.contains('ws-sr-only') && el.textContent === '') as HTMLElement;
    fireEvent.click(screen.getByRole('button', { name: 'Verifică lanțul' }));
    await waitFor(() => expect(region.textContent).toBe('Lanțul de audit este intact. Am verificat 39 de intrări; niciuna nu a fost modificată.'));
    const notice = screen.getAllByText('Am verificat 39 de intrări; niciuna nu a fost modificată.').map((el) => el.closest('.ws-notice')).find(Boolean) as HTMLElement;
    expect(notice.getAttribute('role')).toBeNull();
    checked = 1;
    fireEvent.click(screen.getByRole('button', { name: 'Verifică lanțul' }));
    await waitFor(() => expect(region.textContent).toContain('Am verificat 1 intrare; nu a fost modificată.'));
  });
});

describe('Admin → Users, getting started (UX-07)', () => {
  it('lists what is left, each step checked from real data, and hides once asked', async () => {
    boot('/workspace/admin/users', {
      'GET /api/workspace/admin/smtp': SMTP_NONE,
      'GET /api/workspace/admin/departments': { departments: [{ ...ADMIN_DEPARTMENTS[0], ready_document_count: 0, document_count: 0 }] },
      'GET /api/workspace/admin/audit': { items: [], next_before_id: null },
    });
    const card = (await screen.findByRole('heading', { name: 'Primii pași' })).closest('.ws-card') as HTMLElement;
    expect(within(card).getByText('Mai sunt 5 pași până când pilotul e gata pentru colegi.')).toBeTruthy();
    expect(within(card).getByRole('link', { name: 'Configurează emailul' }).getAttribute('href')).toBe('/workspace/admin/email');
    expect(within(card).getByRole('link', { name: 'Testează modelul' }).getAttribute('href')).toBe('/workspace/admin/organisation');
    fireEvent.click(within(card).getByRole('button', { name: 'Ascunde' }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Primii pași' })).toBeNull());
  });

  it('marks done steps and disappears when all five are done', async () => {
    const done = {
      'GET /api/workspace/admin/users': { users: [makeAdminUser(), makeAdminUser({ id: 2, name: 'Ion', email: 'ion@acme.ro' })] },
      'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS.map((d) => ({ ...d, ready_document_count: 2, document_count: 2 })) },
    };
    boot('/workspace/admin/users', {
      ...done,
      'GET /api/workspace/admin/audit': { items: [{ id: 3, ts: 1, actor_user_id: 1, actor_email: 'ana@acme.ro', action: 'model.tested', target_type: 'model', target_id: 'qwen', department_id: null, ip: '', details: { ok: false } }], next_before_id: null },
    });
    const card = (await screen.findByRole('heading', { name: 'Primii pași' })).closest('.ws-card') as HTMLElement;
    expect(within(card).getByText('Mai este 1 pas până când pilotul e gata pentru colegi.')).toBeTruthy();
    expect(within(card).queryByRole('link', { name: 'Configurează emailul' })).toBeNull();
    expect(within(card).getByText(/Configurează emailul/).textContent).toContain('făcut');
  });
});

describe('Admin forms move focus to the first invalid field (A11Y-04)', () => {
  it('invite dialog', async () => {
    boot('/workspace/admin/users');
    const open = await screen.findByRole('button', { name: 'Invită utilizator' }) as HTMLButtonElement;
    await waitFor(() => expect(open.disabled).toBe(false));
    fireEvent.click(open);
    const dialog = await screen.findByRole('dialog', { name: 'Invită un utilizator' });
    const submit = within(dialog).getByRole('button', { name: 'Trimite invitația' });
    submit.focus();
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByLabelText(/^Email/)));
  });

  it('department drawer', async () => {
    boot('/workspace/admin/departments');
    fireEvent.click(await screen.findByRole('button', { name: 'Departament nou' }));
    const drawer = await screen.findByRole('dialog', { name: 'Departament nou' });
    const submit = within(drawer).getByRole('button', { name: 'Creează departamentul' });
    submit.focus();
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(within(drawer).getByLabelText(/^Nume/)));
  });

  it('organisation form', async () => {
    boot('/workspace/admin/organisation', { 'GET /api/workspace/admin/org': ORG });
    const name = await screen.findByLabelText(/^Numele organizației/);
    fireEvent.change(name, { target: { value: ' ' } });
    const save = screen.getByRole('button', { name: 'Salvează' });
    save.focus();
    fireEvent.click(save);
    await waitFor(() => expect(document.activeElement).toBe(name));
  });

  it('email settings and the test form', async () => {
    boot('/workspace/admin/email');
    const port = await screen.findByLabelText(/^Port/);
    fireEvent.change(port, { target: { value: '99999' } });
    const save = screen.getAllByRole('button', { name: 'Salvează' })[0];
    save.focus();
    fireEvent.click(save);
    await waitFor(() => expect(document.activeElement).toBe(port));
    const to = screen.getByLabelText(/^Trimite la/);
    fireEvent.change(to, { target: { value: 'nu-e-email' } });
    const send = screen.getByRole('button', { name: 'Trimite testul' });
    send.focus();
    fireEvent.click(send);
    await waitFor(() => expect(document.activeElement).toBe(to));
  });
});

describe('Admin → Departments and Usage details', () => {
  it('offers the archived toggle only when a department is archived (UX-18 g), and counts ready documents apart (F10)', async () => {
    boot('/workspace/admin/departments', {
      'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS.map((d) => ({ ...d, document_count: 8, ready_document_count: 7 })) },
    });
    const table = await screen.findByRole('table', { name: 'Departamente' });
    expect(screen.queryByRole('switch', { name: /Arată și arhivate/ })).toBeNull();
    expect((await within(table).findAllByText('7 gata din 8')).length).toBeGreaterThan(0);
  });

  it('pluralizes the feedback split (UX-08)', async () => {
    boot('/workspace/admin/usage', {
      'GET /api/workspace/admin/stats': {
        days: 30, totals: { users: 2, active_users_7d: 1, documents: 1, conversations: 1, questions: 1, reports: 0, report_runs: 0, approvals_pending: 0, feedback_up: 1, feedback_down: 0 },
        per_department: [], daily: [], timezone: 'Europe/Bucharest',
      },
    });
    expect(await screen.findByText('1 util · 0 nefolositoare')).toBeTruthy();
  });
});
