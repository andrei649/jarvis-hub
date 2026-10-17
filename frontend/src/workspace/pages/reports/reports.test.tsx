import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Report, ReportRunDetail, WorkspaceDocument } from '../../api/types';
import { renderApp } from '../../test/render';
import { apiError, json, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { RUN_POLL_MS } from './RunView';

const NOW = Date.now() / 1000;

const REPORT: Report = {
  id: 3, department_id: 1, name: 'Raport lunar contracte', instructions: 'Rezumă contractele lunii.', document_ids: [5],
  schedule_kind: 'weekly', schedule_time: '09:30', schedule_weekday: 2, timezone: 'Europe/Bucharest',
  delivery_emails: ['sef@acme.ro'], delivery_status: 'pending', owner_id: 1, active: true,
  next_run_at: NOW + 86_400, last_run_at: null, created_at: NOW - 100, updated_at: NOW - 100,
  last_run: null, can_edit: true, can_run: true,
};

function document(over: Partial<WorkspaceDocument>): WorkspaceDocument {
  return {
    id: 5, title: 'Contract cadru', filename: 'contract.pdf', mime: 'application/pdf', size_bytes: 1000, department_id: 1,
    visibility: 'department', status: 'ready', error: null, page_count: 3, chunk_count: 9, uploader: null, created_at: NOW,
    can_delete: false, can_reindex: false, can_publish: false, ...over,
  };
}

const DOCUMENTS = [
  document({}),
  document({ id: 6, title: 'Regulament intern', visibility: 'company', department_id: null }),
  document({ id: 7, title: 'Contract alt departament', department_id: 2 }),
];

function run(over: Partial<ReportRunDetail> = {}): ReportRunDetail {
  return {
    id: 40, report_id: 3, status: 'succeeded', trigger: 'manual', triggered_by: 1, model: 'qwen2.5', route: 'local', locality: 'local',
    error_code: null, error: null, shared_company: false, delivered_to: [], started_at: NOW - 70, finished_at: NOW - 10, created_at: NOW - 75,
    content_md: '# Raport lunar\n\n## Rezumat\n\nPlata se face în 30 de zile [1].',
    citations: [{ n: 1, document_id: 5, title: 'Contract cadru', chunk_id: 2, page: 1, excerpt: 'Plata în 30 de zile.' }],
    can_share: true, can_email: true, report: { id: 3, name: 'Raport lunar contracte', department_id: 1 }, ...over,
  };
}

function boot(path: string, routes: Record<string, RouteHandler> = {}, role: 'admin' | 'member' = 'admin') {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/reports': { reports: [REPORT] },
    'GET /api/workspace/reports/3': REPORT,
    'GET /api/workspace/reports/3/runs': { runs: [] },
    'GET /api/workspace/documents': { documents: DOCUMENTS },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

afterEach(() => { vi.useRealTimers(); });

async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

describe('Reports → create and edit', () => {
  it('creates a weekly report with chosen documents and recipients, then opens it', async () => {
    const mock = boot('/workspace/reports', {
      'GET /api/workspace/reports': { reports: [] },
      'POST /api/workspace/reports': json(201, REPORT),
    });
    expect(await screen.findByText('Niciun raport încă')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: 'Raport nou' })[0]);
    const drawer = await screen.findByRole('dialog', { name: 'Raport nou' });

    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează raportul' }));
    expect(await within(drawer).findByText('Dă un nume raportului.')).toBeTruthy();
    expect(within(drawer).getByText('Scrie ce trebuie să conțină raportul.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/reports')).toHaveLength(0);

    fireEvent.change(within(drawer).getByLabelText(/^Nume/), { target: { value: 'Raport lunar contracte' } });
    fireEvent.click(within(drawer).getByText('Exemple de instrucțiuni'));
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Folosește acest exemplu' })[0]);
    expect((within(drawer).getByLabelText(/^Ce trebuie să conțină raportul/) as HTMLTextAreaElement).value).toMatch(/^Rezumă contractele încheiate luna aceasta/);

    expect(await within(drawer).findByLabelText('Contract cadru')).toBeTruthy();
    expect(within(drawer).getByLabelText('Regulament intern')).toBeTruthy();
    expect(within(drawer).queryByLabelText('Contract alt departament')).toBeNull();
    fireEvent.click(within(drawer).getByLabelText('Contract cadru'));
    expect(within(drawer).getByText('1 document ales')).toBeTruthy();

    fireEvent.click(within(drawer).getByLabelText(/^Săptămânal/));
    fireEvent.change(within(drawer).getByLabelText('Ora'), { target: { value: '09:30' } });
    fireEvent.change(within(drawer).getByLabelText('Ziua'), { target: { value: '2' } });
    expect((within(drawer).getByLabelText('Fus orar') as HTMLSelectElement).value).toBe('Europe/Bucharest');
    fireEvent.change(within(drawer).getByLabelText(/^Trimite rezultatul pe email/), { target: { value: 'sef@acme.ro, Sef@acme.ro' } });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează raportul' }));

    await waitFor(() => expect(window.location.pathname).toBe('/workspace/reports/3'));
    const body = mock.find('POST', '/api/workspace/reports')[0].body as Record<string, unknown>;
    expect(body).toMatchObject({
      department_id: 1, name: 'Raport lunar contracte', document_ids: [5],
      schedule: { kind: 'weekly', time: '09:30', weekday: 2, timezone: 'Europe/Bucharest' },
      delivery_emails: ['sef@acme.ro'],
    });
    expect(await screen.findByRole('heading', { level: 1, name: 'Raport lunar contracte' })).toBeTruthy();
    expect(screen.getByText('În fiecare miercuri, la 09:30')).toBeTruthy();
    expect(screen.getByText('Așteaptă aprobarea')).toBeTruthy();
    expect(screen.getByText('Raportul nu a rulat încă')).toBeTruthy();
  });

  it('puts a refused delivery next to the recipients field', async () => {
    boot('/workspace/reports', { 'POST /api/workspace/reports': apiError(409, 'no_eligible_approver') });
    fireEvent.click(await screen.findByRole('button', { name: 'Raport nou' }));
    const drawer = await screen.findByRole('dialog', { name: 'Raport nou' });
    fireEvent.change(within(drawer).getByLabelText(/^Nume/), { target: { value: 'R' } });
    fireEvent.change(within(drawer).getByLabelText(/^Ce trebuie să conțină raportul/), { target: { value: 'Ceva' } });
    fireEvent.change(within(drawer).getByLabelText(/^Trimite rezultatul pe email/), { target: { value: 'a@acme.ro' } });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Creează raportul' }));
    const field = within(drawer).getByLabelText(/^Trimite rezultatul pe email/);
    await waitFor(() => expect(field.getAttribute('aria-invalid')).toBe('true'));
    expect(within(drawer).getByText('Nu există nicio persoană care să poată aproba această cerere.')).toBeTruthy();
  });

  it('disables email delivery honestly when outgoing email is not configured', async () => {
    boot('/workspace/reports', { 'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: false } });
    fireEvent.click(await screen.findByRole('button', { name: 'Raport nou' }));
    const drawer = await screen.findByRole('dialog', { name: 'Raport nou' });
    expect(await within(drawer).findByText(/Trimiterea de emailuri nu este configurată/)).toBeTruthy();
    expect((within(drawer).getByLabelText(/^Trimite rezultatul pe email/) as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('lists reports with schedule, last run and delivery state, and deletes after confirmation', async () => {
    const mock = boot('/workspace/reports', {
      'GET /api/workspace/reports': { reports: [{ ...REPORT, last_run: { id: 39, status: 'failed', finished_at: NOW - 3600 } }] },
      'DELETE /api/workspace/reports/3': json(204),
    });
    const table = await screen.findByRole('table', { name: 'Rapoarte' });
    expect((await within(table).findByRole('link', { name: 'Raport lunar contracte' })).getAttribute('href')).toBe('/workspace/reports/3');
    expect(within(table).getByText('În fiecare miercuri, la 09:30')).toBeTruthy();
    expect(within(table).getByText('Eșuat')).toBeTruthy();
    expect(within(table).getByText('Așteaptă aprobarea')).toBeTruthy();
    fireEvent.click(within(table).getByRole('button', { name: 'Acțiuni pentru „Raport lunar contracte”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Șterge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Ștergi raportul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Șterge' }));
    expect(await screen.findByText('Raportul a fost șters.')).toBeTruthy();
    expect(mock.find('DELETE', '/api/workspace/reports/3')).toHaveLength(1);
  });
});

describe('Reports → runs', () => {
  it('runs a report now, follows it live until it finishes, renders it, and stops polling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const sequence = [run({ status: 'queued', content_md: null, started_at: null, finished_at: null }), run({ status: 'running', content_md: null, finished_at: null }), run()];
    let reads = 0;
    const mock = boot('/workspace/reports', {
      'POST /api/workspace/reports/3/run': json(202, { run: sequence[0] }),
      'GET /api/workspace/report-runs/40': () => { const answer = sequence[Math.min(reads, sequence.length - 1)]; reads += 1; return answer; },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Rulează acum „Raport lunar contracte”' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/report-runs/40'));
    expect(await screen.findByText(/Raportul (așteaptă să înceapă|se scrie din documente)/)).toBeTruthy();

    await tick(RUN_POLL_MS);
    await tick(RUN_POLL_MS);
    expect(await screen.findByRole('heading', { name: 'Rezumat' })).toBeTruthy();
    expect(screen.getByText('Raportul este gata.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Exportă Markdown' }).getAttribute('href')).toBe('/api/workspace/report-runs/40/export?format=md');
    expect(screen.getByRole('link', { name: 'Exportă HTML' }).getAttribute('href')).toBe('/api/workspace/report-runs/40/export?format=html');
    expect(screen.getAllByText('qwen2.5').length).toBeGreaterThan(0);

    const settled = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 4);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(settled);

    fireEvent.click(screen.getByRole('button', { name: 'Sursa 1: Contract cadru' }));
    expect(await screen.findByRole('dialog', { name: 'Sursa [1]' })).toBeTruthy();
  });

  it('opens the run already in progress instead of reporting run_in_progress', async () => {
    const mock = boot('/workspace/reports', {
      'POST /api/workspace/reports/3/run': apiError(409, 'run_in_progress', { run_id: 40 }),
      'GET /api/workspace/report-runs/40': run({ status: 'running', content_md: null, finished_at: null }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Rulează acum „Raport lunar contracte”' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/report-runs/40'));
    expect(await screen.findByText('Raportul rula deja, așa că am deschis rularea în curs.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/reports/3/run')).toHaveLength(1);
  });

  it('still explains other refusals to run (rate limit with the wait)', async () => {
    boot('/workspace/reports/3', { 'POST /api/workspace/reports/3/run': apiError(429, 'rate_limited', { retry_after_seconds: 120 }) });
    fireEvent.click(await screen.findByRole('button', { name: 'Rulează acum' }));
    expect(await screen.findByText('Prea multe cereri într-un timp scurt. Poți încerca din nou peste 2 minute.')).toBeTruthy();
    expect(window.location.pathname).toBe('/workspace/reports/3');
  });

  it('shows the next scheduled run in the report\'s own time zone', async () => {
    const at = Date.UTC(2026, 9, 21, 6, 30) / 1000;
    boot('/workspace/reports/3', { 'GET /api/workspace/reports/3': { ...REPORT, next_run_at: at } });
    const expected = new Intl.DateTimeFormat('ro-RO', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Bucharest' }).format(new Date(at * 1000));
    expect(await screen.findByText(expected)).toBeTruthy();
  });

  it('stops polling a running report when the page is left', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ status: 'running', content_md: null, finished_at: null }) });
    expect(await screen.findByText('Raportul se scrie din documente. Poate dura câteva minute.')).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: 'Înapoi la raport' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Raport lunar contracte' })).toBeTruthy();
    const before = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 5);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(before);
  });

  it('explains a failed run and runs it again', async () => {
    const mock = boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': run({ status: 'failed', error_code: 'no_documents', content_md: null }),
      'POST /api/workspace/reports/3/run': json(202, { run: run({ id: 41, status: 'queued' }) }),
      'GET /api/workspace/report-runs/41': run({ id: 41 }),
    });
    expect(await screen.findByText('Raportul nu are niciun document gata din care să lucreze. Încarcă documente sau alege altele în raport.')).toBeTruthy();
    // A finished failure is not "loading": the document area says there is no report.
    expect(screen.getByText('Această rulare nu a produs un raport. Motivul este descris mai sus.')).toBeTruthy();
    expect(window.document.querySelector('.ws-run__doc .ws-skeleton')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Rulează din nou' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/report-runs/41'));
    expect(mock.find('POST', '/api/workspace/reports/3/run')).toHaveLength(1);
  });

  it('prints, shares with the company at once as an admin, and requests an email of the run', async () => {
    const print = vi.fn();
    vi.stubGlobal('print', print);
    const mock = boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': run(),
      'POST /api/workspace/approvals': (call) => {
        const kind = (call.body as { kind: string }).kind;
        return json(201, { id: kind === 'email.send' ? 51 : 50, kind, status: kind === 'email.send' ? 'pending' : 'approved', error_code: null });
      },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Tipărește' }));
    expect(print).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Partajează în companie' }));
    const share = await screen.findByRole('dialog', { name: 'Partajezi raportul cu toată compania?' });
    fireEvent.click(within(share).getByRole('button', { name: 'Partajează acum' }));
    expect(await screen.findByText('Raportul este acum vizibil pentru toată compania.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals')[0].body).toEqual({ kind: 'report.share_company', payload: { run_id: 40 } });

    fireEvent.click(screen.getByRole('button', { name: 'Trimite pe email' }));
    const email = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    expect((within(email).getByLabelText(/^Subiect/) as HTMLInputElement).value).toMatch(/^Raport lunar contracte — /);
    fireEvent.change(within(email).getByLabelText(/^Destinatari/), { target: { value: 'board@acme.ro' } });
    await within(email).findByText('1 persoană poate aproba această cerere.');
    fireEvent.click(within(email).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await screen.findByRole('dialog', { name: 'Cererea a fost trimisă' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals')[1].body).toMatchObject({
      kind: 'email.send', payload: { to: ['board@acme.ro'], body_markdown: run().content_md, source: { type: 'report_run', id: 40 } },
    });
  });

  it('shows the run history of a report with live refresh for a run in progress', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let reads = 0;
    const mock = boot('/workspace/reports/3', {
      'GET /api/workspace/reports/3/runs': () => {
        reads += 1;
        return { runs: [run({ status: reads > 2 ? 'succeeded' : 'running', content_md: undefined })] };
      },
    });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(await within(table).findByText('Rulează')).toBeTruthy();
    await tick(4000);
    expect(await within(table).findByText('Gata')).toBeTruthy();
    const settled = mock.find('GET', '/api/workspace/reports/3/runs').length;
    await tick(12_000);
    expect(mock.find('GET', '/api/workspace/reports/3/runs')).toHaveLength(settled);
  });
});

describe('Shared reports', () => {
  it('lists company-shared runs and opens one read-only', async () => {
    boot('/workspace/shared-reports', {
      'GET /api/workspace/shared-reports': { runs: [run({ shared_company: true, can_share: false, can_email: false })] },
      'GET /api/workspace/report-runs/40': run({ shared_company: true, can_share: false, can_email: false }),
    }, 'member');
    const table = await screen.findByRole('table', { name: 'Rapoarte partajate' });
    fireEvent.click(await within(table).findByRole('link', { name: 'Raport lunar contracte' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/shared-reports/40'));
    expect(await screen.findByRole('heading', { name: 'Rezumat' })).toBeTruthy();
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Rapoarte partajate' }).getAttribute('href')).toBe('/workspace/shared-reports');
    expect(screen.queryByRole('button', { name: 'Partajează în companie' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Trimite pe email' })).toBeNull();
    expect(screen.getByText('Partajat în companie')).toBeTruthy();
  });

  it('sends an email request about a shared run of another department to the admins', async () => {
    const foreign = run({ shared_company: true, can_share: false, can_email: true, department_id: 9, report: { id: 3, name: 'Raport lunar contracte', department_id: 9 } });
    const mock = boot('/workspace/shared-reports/40', {
      'GET /api/workspace/report-runs/40': foreign,
      'GET /api/workspace/approvals/eligible': { count: 0, smtp_configured: true },
    }, 'member');
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const email = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    expect(await within(email).findByText(/Doar un administrator poate aproba această cerere/)).toBeTruthy();
    const probes = mock.find('GET', '/api/workspace/approvals/eligible');
    expect(probes.length).toBeGreaterThan(0);
    for (const probe of probes) expect(probe.search).toBe('?kind=email.send');
    expect((within(email).getByRole('button', { name: 'Cere aprobarea' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('teaches what shared reports are when there are none', async () => {
    boot('/workspace/shared-reports', { 'GET /api/workspace/shared-reports': { runs: [] } });
    expect(await screen.findByText('Niciun raport partajat încă')).toBeTruthy();
  });
});
