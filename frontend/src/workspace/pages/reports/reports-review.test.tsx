/* Review fixes on Reports (frontend fixer, QA round 2): a failed email delivery is said on the
   run and in the history (F1); a share request already waiting is not offered again (F8);
   saving a report whose chosen documents are all gone asks before it widens to every document
   (F7); the report re-reads its last/next run when a polled run finishes (F11); a half-written
   report survives the session ending (F3); after navigating to a report or a run, focus lands
   on the final h1 even though a loading heading came first (A11Y-03); the run's h1 is the
   report's name and the report's own headings sit under it (UX-12, A11Y-13); a cited table
   reads as a table in the source drawer (UX-06). Round 3: the run says where it was produced in
   words and shows the model id to admins only (UX-13); a citation chip that starts its table
   cell or list item is a full 24 px target, one inside a sentence stays compact (A11Y-15). */
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Report, ReportRun, ReportRunDetail, WorkspaceDocument } from '../../api/types';
import { renderApp } from '../../test/render';
import { makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';

const NOW = Date.now() / 1000;

const REPORT: Report = {
  id: 3, department_id: 1, name: 'Raport lunar contracte', instructions: 'Rezumă contractele lunii.', document_ids: [5],
  schedule_kind: 'manual', schedule_time: null, schedule_weekday: null, timezone: 'Europe/Bucharest',
  delivery_emails: [], delivery_status: 'none', owner_id: 1, active: true,
  next_run_at: null, last_run_at: null, created_at: NOW - 100, updated_at: NOW - 100,
  last_run: null, can_edit: true, can_run: true,
};

function doc(over: Partial<WorkspaceDocument>): WorkspaceDocument {
  return {
    id: 5, title: 'Contract cadru', filename: 'contract.pdf', mime: 'application/pdf', size_bytes: 1000, department_id: 1,
    visibility: 'department', status: 'ready', error: null, page_count: 3, chunk_count: 9, uploader: null, created_at: NOW,
    can_delete: false, can_reindex: false, can_publish: false, ...over,
  };
}

function run(over: Partial<ReportRunDetail> = {}): ReportRunDetail {
  return {
    id: 40, report_id: 3, status: 'succeeded', trigger: 'schedule', triggered_by: null, model: 'qwen2.5', route: 'local', locality: 'local',
    error_code: null, error: null, shared_company: false, delivered_to: [], started_at: NOW - 70, finished_at: NOW - 10, created_at: NOW - 75,
    content_md: '# Raport lunar\n\n## Rezumat\n\nPlata se face în 30 de zile [1].',
    citations: [{ n: 1, document_id: 5, title: 'Contract cadru', chunk_id: 2, page: 1, excerpt: 'Plata în 30 de zile. | Termen | Penalitate | | --- | --- | | 30 de zile | 0,1% pe zi |' }],
    can_share: true, can_email: true, share_pending: false, report: { id: 3, name: 'Raport lunar contracte', department_id: 1 },
    department_name: 'General', ...over,
  };
}

function boot(path: string, routes: Record<string, RouteHandler> = {}, role: 'admin' | 'member' = 'member') {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/reports': { reports: [REPORT] },
    'GET /api/workspace/reports/3': REPORT,
    'GET /api/workspace/reports/3/runs': { runs: [] },
    'GET /api/workspace/documents': { documents: [doc({})] },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

afterEach(() => { vi.useRealTimers(); });

describe('Run view', () => {
  it('says the report is ready but its email was not sent, with the cause in words (F1)', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ error: 'delivery_failed', error_code: 'smtp_failed' }) });
    const notice = (await screen.findByText('Raportul este gata, dar emailul nu a fost trimis')).closest('.ws-notice') as HTMLElement;
    expect(within(notice).getByText('Serverul de email a refuzat mesajul sau nu a putut fi contactat.')).toBeTruthy();
    expect(within(notice).getByText(/Destinatarii nu au primit această rulare/)).toBeTruthy();
    expect(screen.queryByText(/smtp_failed/)).toBeNull();
  });

  it('withdraws "share" while a share request waits, and says it waits (F8)', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ can_share: false, share_pending: true }) });
    expect(await screen.findByText('Partajarea în companie așteaptă aprobarea')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Partajează în companie' })).toBeNull();
  });

  it('is headed by the report name, with the report\'s own title one level down (UX-12, A11Y-13)', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run() });
    expect(await screen.findByRole('heading', { level: 1, name: 'Raport lunar contracte' })).toBeTruthy();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const article = screen.getByRole('article');
    expect(within(article).getByRole('heading', { level: 2, name: 'Raport lunar' })).toBeTruthy();
    expect(within(article).getByRole('heading', { level: 3, name: 'Rezumat' })).toBeTruthy();
    expect(screen.getByText(/^Rularea din .+ · Gata$/)).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Exportă' })).toBeTruthy();
  });

  it('shows a cited table as a table in the source drawer, not as pipes (UX-06)', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run() });
    const article = await screen.findByRole('article');
    fireEvent.click(within(article).getByRole('button', { name: 'Sursa 1: Contract cadru' }));
    const drawer = await screen.findByRole('dialog', { name: 'Sursa [1]' });
    const table = within(drawer).getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Penalitate' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '0,1% pe zi' })).toBeTruthy();
    expect(within(drawer).queryByText(/\| --- \|/)).toBeNull();
    expect(within(drawer).getByText('Plata în 30 de zile.')).toBeTruthy();
  });

  it('after navigating to a run, focus ends on its final h1, not on <body> (A11Y-03)', async () => {
    let answer: ((value: ReportRunDetail) => void) | null = null;
    const runs: ReportRun[] = [run()];
    boot('/workspace/reports/3', {
      'GET /api/workspace/reports/3/runs': { runs },
      'GET /api/workspace/report-runs/40': () => new Promise<ReportRunDetail>((resolve) => { answer = resolve; }),
    });
    const link = await screen.findByRole('link', { name: /oct|nov|dec|ian|feb|mar|apr|mai|iun|iul|aug|sept/ });
    link.focus();
    fireEvent.click(link);
    await waitFor(() => expect(answer).not.toBeNull());
    await waitFor(() => expect(document.activeElement?.getAttribute('data-page-heading')).toBe('true'));
    await act(async () => { answer?.(run()); });
    const heading = await screen.findByRole('heading', { level: 1, name: 'Raport lunar contracte' });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });
});

describe('Report detail', () => {
  it('flags a run whose email delivery failed in the history (F1)', async () => {
    boot('/workspace/reports/3', { 'GET /api/workspace/reports/3/runs': { runs: [run({ error: 'delivery_failed', error_code: 'smtp_failed' })] } });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(await within(table).findByText('Email netrimis')).toBeTruthy();
  });

  it('re-reads last and next run when a polled run finishes (F11)', async () => {
    let finished = false;
    const mock = boot('/workspace/reports/3', {
      'GET /api/workspace/reports/3/runs': () => ({ runs: [run({ status: finished ? 'succeeded' : 'running', finished_at: finished ? NOW : null })] }),
      'GET /api/workspace/reports/3': () => (finished ? { ...REPORT, last_run_at: NOW } : REPORT),
    });
    expect(await screen.findByText('Niciodată')).toBeTruthy();
    const reads = mock.find('GET', '/api/workspace/reports/3').length;
    finished = true;
    await waitFor(() => expect(mock.find('GET', '/api/workspace/reports/3').length).toBeGreaterThan(reads), { timeout: 8000 });
    await waitFor(() => expect(screen.queryByText('Niciodată')).toBeNull());
  }, 15_000);
});

describe('Report form', () => {
  it('does not silently widen a report whose chosen documents are all gone (F7)', async () => {
    const mock = boot('/workspace/reports/3', {
      'GET /api/workspace/reports/3': { ...REPORT, document_ids: [12] },
      'GET /api/workspace/documents': { documents: [doc({})] },
      'PATCH /api/workspace/reports/3': { ...REPORT, document_ids: [] },
    });
    fireEvent.click(await screen.findByRole('button', { name: /Acțiuni pentru/ }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Editează' }));
    const drawer = await screen.findByRole('dialog', { name: 'Editează raportul' });
    expect(await within(drawer).findByText('Raportul nu mai are documente alese')).toBeTruthy();
    fireEvent.click(within(drawer).getByRole('button', { name: 'Salvează' }));
    expect(await within(drawer).findByText('Alege cel puțin un document sau confirmă că raportul poate folosi toate documentele.')).toBeTruthy();
    expect(mock.find('PATCH', '/api/workspace/reports/3')).toHaveLength(0);
    const confirm = within(drawer).getByLabelText('Da, raportul poate folosi toate documentele');
    expect(document.activeElement).toBe(confirm);
    fireEvent.click(confirm);
    fireEvent.click(within(drawer).getByRole('button', { name: 'Salvează' }));
    await waitFor(() => expect(mock.find('PATCH', '/api/workspace/reports/3')).toHaveLength(1));
    expect((mock.find('PATCH', '/api/workspace/reports/3')[0].body as { document_ids: number[] }).document_ids).toEqual([]);
  });

  it('keeps a half-written report when the session ends, and drops it on cancel (F3)', async () => {
    boot('/workspace/reports');
    fireEvent.click((await screen.findAllByRole('button', { name: 'Raport nou' }))[0]);
    let drawer = await screen.findByRole('dialog', { name: 'Raport nou' });
    fireEvent.change(within(drawer).getByLabelText(/^Nume/), { target: { value: 'Sinteză comercială' } });
    fireEvent.change(within(drawer).getByLabelText(/^Ce trebuie să conțină raportul/), { target: { value: 'Rezumă vânzările săptămânii.' } });
    cleanup();
    boot('/workspace/reports');
    fireEvent.click((await screen.findAllByRole('button', { name: 'Raport nou' }))[0]);
    drawer = await screen.findByRole('dialog', { name: 'Raport nou' });
    expect((within(drawer).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('Sinteză comercială');
    expect((within(drawer).getByLabelText(/^Ce trebuie să conțină raportul/) as HTMLTextAreaElement).value).toBe('Rezumă vânzările săptămânii.');
    expect(within(drawer).getByText(/Am păstrat ce scriseseși/)).toBeTruthy();
    fireEvent.click(within(drawer).getByRole('button', { name: 'Renunță' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Raport nou' })).toBeNull());
    fireEvent.click(screen.getAllByRole('button', { name: 'Raport nou' })[0]);
    drawer = await screen.findByRole('dialog', { name: 'Raport nou' });
    expect((within(drawer).getByLabelText(/^Nume/) as HTMLInputElement).value).toBe('');
  });
});

describe('Run view → how it was produced, in words (UX-13)', () => {
  it('tells a member where the run was produced, without the model id, here and in the run history', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run() });
    const meta = (await screen.findByText('Unde a fost generat')).closest('dl') as HTMLElement;
    expect(within(meta).getByText('Pe serverul companiei')).toBeTruthy();
    expect(within(meta).queryByText('Model')).toBeNull();
    expect(screen.queryByText('qwen2.5')).toBeNull();
    expect(screen.queryByText('local')).toBeNull();

    cleanup();
    boot('/workspace/reports/3', { 'GET /api/workspace/reports/3/runs': { runs: [run()] } });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(within(table).getByRole('columnheader', { name: 'Unde a fost generat' })).toBeTruthy();
    expect(within(table).getByText('Pe serverul companiei')).toBeTruthy();
    expect(within(table).queryByText('qwen2.5')).toBeNull();
  });

  it('shows an admin the model id next to the same words', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ locality: 'cloud' }) }, 'admin');
    const meta = (await screen.findByText('Unde a fost generat')).closest('dl') as HTMLElement;
    expect(within(meta).getByText('La un furnizor cloud aprobat')).toBeTruthy();
    expect(within(meta).getByText('Model')).toBeTruthy();
    expect(within(meta).getByText('qwen2.5')).toBeTruthy();
  });

  it('heads the shared reports column with the question it answers', async () => {
    boot('/workspace/shared-reports', { 'GET /api/workspace/shared-reports': { runs: [run({ shared_company: true })] } });
    const table = await screen.findByRole('table', { name: 'Rapoarte partajate' });
    expect(within(table).getByRole('columnheader', { name: 'Unde a fost generat' })).toBeTruthy();
    expect(await within(table).findByText('Pe serverul companiei')).toBeTruthy();
  });
});

describe('Run view → citation chips as targets (A11Y-15)', () => {
  const content = [
    '# Raport', '', '## Constatări', '', '- Plata se face în 30 de zile. [1]', '', '## Date cheie', '',
    '| Nr. | Document | Extras |', '| --- | --- | --- |', '| [1] | Contract cadru | Plata în 30 de zile [1] |', '',
    '## Surse', '', '1. [1] Contract cadru',
  ].join('\n');

  it('gives a chip that starts its cell or list item the full size, and keeps the ones inside a sentence compact', async () => {
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ content_md: content }) });
    const article = await screen.findByRole('article');
    const chips = within(article).getAllByRole('button', { name: 'Sursa 1: Contract cadru' });
    expect(chips).toHaveLength(4);
    const lead = (chip: HTMLElement) => chip.classList.contains('ws-cite--lead');
    const inCell = (chip: HTMLElement) => chip.parentElement?.tagName;
    // The "Nr." cell and the head of the "Surse" item: targets on their own.
    expect(chips.filter((c) => inCell(c) === 'TD' && lead(c))).toHaveLength(1);
    expect(chips.filter((c) => inCell(c) === 'LI' && lead(c))).toHaveLength(1);
    // After a finding and inside the excerpt cell: part of the sentence.
    expect(chips.filter((c) => !lead(c))).toHaveLength(2);
    expect(chips.filter((c) => !lead(c)).map((c) => c.parentElement?.textContent?.trim().startsWith('['))).toEqual([false, false]);
  });
});
