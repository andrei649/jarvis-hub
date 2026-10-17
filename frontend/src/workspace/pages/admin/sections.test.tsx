import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render';
import { ADMIN_DEPARTMENTS, apiError, json, makeAdminUser, makeUser, mockFetch, ORG, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';

function boot(path: string, routes: Record<string, RouteHandler>) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser()),
    ...shellRoutes(),
    'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS },
    'GET /api/workspace/admin/users': { users: [makeAdminUser()] },
    ...routes,
  });
  renderApp(path);
  return mock;
}

describe('Admin → Departments', () => {
  it('creates a department with assistant instructions and refreshes the sidebar list', async () => {
    const mock = boot('/workspace/admin/departments', {
      'POST /api/workspace/admin/departments': json(201, { ...ADMIN_DEPARTMENTS[1], id: 3, slug: 'vanzari', name: 'Vânzări' }),
    });
    await screen.findByText('juridic');
    const sidebarLoads = mock.find('GET', '/api/workspace/departments').length;
    fireEvent.click(screen.getByRole('button', { name: 'Departament nou' }));
    const drawer = await screen.findByRole('dialog', { name: 'Departament nou' });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează departamentul' }));
    expect(await within(drawer).findByText('Introdu numele departamentului.')).toBeTruthy();
    fireEvent.change(within(drawer).getByLabelText(/^Nume/), { target: { value: ' Vânzări ' } });
    fireEvent.change(within(drawer).getByLabelText(/^Instrucțiuni pentru asistent/), { target: { value: 'Răspunde scurt.' } });
    expect(within(drawer).getByText(`15 / ${new Intl.NumberFormat('ro-RO').format(4000)}`)).toBeTruthy();
    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează departamentul' }));
    expect(await screen.findByText('Departamentul „Vânzări” a fost creat.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/admin/departments')[0].body).toEqual({ name: 'Vânzări', description: '', assistant_instructions: 'Răspunde scurt.' });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/departments').length).toBeGreaterThan(sidebarLoads));
  });

  it('explains why a department with content cannot be deleted', async () => {
    const mock = boot('/workspace/admin/departments', {
      'DELETE /api/workspace/admin/departments/2': apiError(409, 'department_not_empty', { member_count: 1, document_count: 3 }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru Juridic' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Șterge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Ștergi definitiv departamentul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Șterge' }));
    expect(await within(confirm).findByText(/Arhivează-l în schimb/)).toBeTruthy();
    expect(mock.find('DELETE', '/api/workspace/admin/departments/2')).toHaveLength(1);
  });

  it('archives a department after confirmation', async () => {
    const mock = boot('/workspace/admin/departments', {
      'PATCH /api/workspace/admin/departments/2': { ...ADMIN_DEPARTMENTS[1], archived: true },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Acțiuni pentru Juridic' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Arhivează' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Arhivezi departamentul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Arhivează' }));
    await waitFor(() => expect(mock.find('PATCH', '/api/workspace/admin/departments/2')[0]?.body).toEqual({ archived: true }));
  });
});

describe('Admin → Organisation', () => {
  it('saves the model policy and runs a real model test', async () => {
    const mock = boot('/workspace/admin/organisation', {
      'GET /api/workspace/admin/org': ORG,
      'PATCH /api/workspace/admin/org': { ...ORG, model_policy: 'allow_cloud' },
      'POST /api/workspace/admin/model/test': { ok: true, latency_ms: 1530, model: 'qwen', locality: 'local', route: 'local' },
    });
    const cloud = await screen.findByLabelText(/^Permite cloud fără antrenare/);
    fireEvent.click(cloud);
    expect(screen.getByText('Politica nouă se aplică imediat tuturor întrebărilor și rapoartelor.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    expect(await screen.findByText('Setările organizației au fost salvate.')).toBeTruthy();
    expect(mock.find('PATCH', '/api/workspace/admin/org')[0].body).toEqual({ name: 'Acme', default_locale: 'ro', model_policy: 'allow_cloud' });

    fireEvent.click(screen.getByRole('button', { name: 'Testează modelul' }));
    expect(await screen.findByText(/Modelul a răspuns în/)).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/admin/model/test')).toHaveLength(1);
  });

  it('shows an unavailable model with its reason and a failed test in plain words', async () => {
    boot('/workspace/admin/organisation', {
      'GET /api/workspace/admin/org': ORG,
      'GET /api/workspace/model': { available: false, backend: null, model: null, route: null, locality: null, policy: 'local_only', reason: 'no_local_model', guardrails_mode: null },
      'POST /api/workspace/admin/model/test': { ok: false, latency_ms: 12, model: 'qwen', locality: 'local', route: 'local', error: 'model_unavailable', reason: 'backend_error', message: 'the model is not available (backend_error)' },
    });
    expect((await screen.findAllByText('Niciun model local nu este configurat sau pornit pe serverul hubului.')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Testează modelul' }));
    expect(await screen.findByText('Modelul nu a răspuns')).toBeTruthy();
    expect(screen.getByText('Modelul AI nu este disponibil acum. Serverul modelului a întâmpinat o eroare.')).toBeTruthy();
    expect(screen.getByText('qwen · local')).toBeTruthy();
    expect(screen.queryByText(/backend_error/)).toBeNull();
  });
});

describe('Admin → Email', () => {
  const SAVED = { host: 'smtp.acme.ro', port: 587, security: 'starttls', username: 'nerva', from_address: 'nerva@acme.ro', from_name: 'Nerva', allowed_domains: ['acme.ro'], has_password: true };

  it('keeps the stored password unless a new one is typed (password: null)', async () => {
    const mock = boot('/workspace/admin/email', { 'GET /api/workspace/admin/smtp': SAVED, 'PUT /api/workspace/admin/smtp': SAVED });
    expect(await screen.findByText('O parolă este salvată. Lasă câmpul gol pentru a o păstra.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Domenii permise/), { target: { value: 'acme.ro, @Filiala.ro\nacme.ro' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    expect(await screen.findByText('Setările de email au fost salvate.')).toBeTruthy();
    expect(mock.find('PUT', '/api/workspace/admin/smtp')[0].body).toEqual({
      host: 'smtp.acme.ro', port: 587, security: 'starttls', username: 'nerva', password: null,
      from_address: 'nerva@acme.ro', from_name: 'Nerva', allowed_domains: ['acme.ro', 'filiala.ro'],
    });
  });

  it('clears the stored password on request (password: "") and validates locally', async () => {
    const mock = boot('/workspace/admin/email', { 'GET /api/workspace/admin/smtp': SAVED, 'PUT /api/workspace/admin/smtp': { ...SAVED, has_password: false } });
    fireEvent.click(await screen.findByLabelText('Șterge parola salvată'));
    expect(screen.getByText('Parola salvată va fi ștearsă la salvare.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Port/), { target: { value: '99999' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    expect(await screen.findByText('Portul trebuie să fie un număr între 1 și 65535.')).toBeTruthy();
    expect(mock.find('PUT', '/api/workspace/admin/smtp')).toHaveLength(0);
    fireEvent.change(screen.getByLabelText(/^Port/), { target: { value: '465' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    await waitFor(() => expect(mock.find('PUT', '/api/workspace/admin/smtp')[0]?.body).toMatchObject({ port: 465, password: '' }));
    expect(await screen.findByText('Nicio parolă salvată.')).toBeTruthy();
  });

  it('turns outgoing email off when the host is left empty', async () => {
    const mock = boot('/workspace/admin/email', {
      'GET /api/workspace/admin/smtp': SAVED,
      'PUT /api/workspace/admin/smtp': { ...SAVED, host: '', from_address: '', configured: false },
    });
    fireEvent.change(await screen.findByLabelText(/^Server/), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText(/^Adresa expeditorului/), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    await waitFor(() => expect(mock.find('PUT', '/api/workspace/admin/smtp')[0]?.body).toMatchObject({ host: '', from_address: '' }));
    expect(await screen.findByText('Neconfigurat')).toBeTruthy();
  });

  it('sends a test message and reports the server verdict', async () => {
    const mock = boot('/workspace/admin/email', {
      'GET /api/workspace/admin/smtp': SAVED,
      'POST /api/workspace/admin/smtp/test': { ok: false, error: 'smtp_failed', reason: 'auth_failed' },
    });
    const send = await screen.findByRole('button', { name: 'Trimite testul' });
    fireEvent.click(send);
    expect(await screen.findByText('Mesajul de test nu a putut fi trimis')).toBeTruthy();
    expect(screen.getByText('Serverul de email a refuzat autentificarea. Verifică utilizatorul și parola.')).toBeTruthy();
    expect(screen.queryByText('smtp_failed')).toBeNull();
    expect(mock.find('POST', '/api/workspace/admin/smtp/test')[0].body).toEqual({ to: 'ana@acme.ro' });
  });
});

describe('Admin → Audit', () => {
  const entry = (id: number) => ({ id, ts: 1_760_000_000 + id, actor_user_id: 1, actor_email: 'ana@acme.ro', actor_name: 'Ana Pop', action: 'user.created', target_type: 'user', target_id: String(id), department_id: null, ip: '10.0.0.1', details: { role: 'member' } });

  it('pages backwards with before_id, filters by action, links the CSV export and verifies the chain', async () => {
    const mock = boot('/workspace/admin/audit', {
      'GET /api/workspace/admin/audit': (call) => {
        const params = new URLSearchParams(call.search);
        if (params.get('before_id') === '51') return { items: [entry(50)], next_before_id: null };
        return { items: [entry(52), entry(51)], next_before_id: 51 };
      },
      'GET /api/workspace/admin/audit/verify': { ok: false, checked: 52, broken_at: 17, keyed: true, key_mismatch: false },
    });
    const table = await screen.findByRole('table', { name: 'Audit' });
    await waitFor(() => expect(within(table).getAllByText('Utilizator creat')).toHaveLength(2));
    expect(within(table).getAllByText('ana@acme.ro')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Mai vechi' }));
    await waitFor(() => expect(within(table).getAllByText('Utilizator creat')).toHaveLength(1));
    expect(mock.find('GET', '/api/workspace/admin/audit').slice(-1)[0]?.search).toBe('?limit=50&before_id=51');
    expect(screen.getByText('Pagina 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Mai noi' }));
    await waitFor(() => expect(within(table).getAllByText('Utilizator creat')).toHaveLength(2));

    fireEvent.change(screen.getByLabelText('Acțiunea', { selector: 'select' }), { target: { value: 'user.created' } });
    fireEvent.click(screen.getByRole('button', { name: 'Aplică filtrele' }));
    await waitFor(() => expect(mock.find('GET', '/api/workspace/admin/audit').slice(-1)[0]?.search).toBe('?action=user.created&limit=50'));
    expect(screen.getByRole('link', { name: 'Exportă CSV' }).getAttribute('href')).toBe('/api/workspace/admin/audit/export?action=user.created');

    fireEvent.click(screen.getByRole('button', { name: 'Verifică lanțul' }));
    expect(await screen.findByText('Lanțul este rupt la intrarea #17')).toBeTruthy();
  });

  it('refuses a reversed date range without calling the server', async () => {
    const mock = boot('/workspace/admin/audit', { 'GET /api/workspace/admin/audit': { items: [], next_before_id: null } });
    expect(await screen.findByText('Jurnalul este gol')).toBeTruthy();
    const calls = mock.find('GET', '/api/workspace/admin/audit').length;
    fireEvent.change(screen.getByLabelText('De la'), { target: { value: '2026-10-10' } });
    fireEvent.change(screen.getByLabelText('Până la'), { target: { value: '2026-10-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Aplică filtrele' }));
    expect(await screen.findByText('Data de început este după data de sfârșit.')).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/admin/audit')).toHaveLength(calls);
  });
});

describe('Admin → Usage', () => {
  it('shows KPIs, a readable chart and the per-department table, and reloads for another period', async () => {
    const stats = {
      days: 7, since: 0,
      totals: { users: 12, active_users_7d: 9, documents: 40, conversations: 31, questions: 120, reports: 4, report_runs: 6, approvals_pending: 2, feedback_up: 30, feedback_down: 10 },
      per_department: [{ department_id: 2, slug: 'juridic', name: 'Juridic', archived: false, members: 3, documents: 10, conversations: 8, questions: 50, reports: 1, report_runs: 2 }],
      daily: [{ date: '2026-10-16', questions: 20, report_runs: 1 }, { date: '2026-10-17', questions: 0, report_runs: 0 }],
    };
    const mock = boot('/workspace/admin/usage', { 'GET /api/workspace/admin/stats': stats });
    expect(await screen.findByText('9 activi în ultimele 7 zile')).toBeTruthy();
    expect(screen.getByText(/^75\s%$/)).toBeTruthy();
    const chart = screen.getByRole('group', { name: /Întrebări: 20 de întrebări/ });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'ArrowLeft' });
    expect(within(chart).getByText(/: 20 de întrebări$/)).toBeTruthy();
    const table = screen.getByRole('table', { name: 'Pe departamente' });
    expect(within(table).getByText('Juridic')).toBeTruthy();
    expect(within(table).getByText('Membri')).toBeTruthy();
    expect(within(table).queryByText('Răspunsuri utile')).toBeNull();

    fireEvent.change(screen.getByLabelText('Perioada'), { target: { value: '90' } });
    await waitFor(() => expect(mock.find('GET', '/api/workspace/admin/stats').slice(-1)[0]?.search).toBe('?days=90'));
  });
});
