/* A run or a report that is deleted while its page follows it live (review R4-01).

   useAsync keeps the last copy it read when a reload fails, so a run deleted while its email
   was on the way (or while it was being written) kept its page polling every 2 s forever, still
   showing "se trimite pe email…", and the not-found state never appeared; the report's history
   kept polling every 4 s the same way. A 404 now means the run or the report is gone: the page
   stops polling, drops the stale copy and shows the not-found state, said once in its status
   region. A transient failure (a 503, the network) still keeps the last copy and the polling. */
import { act, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Report, ReportRunDetail } from '../../api/types';
import { renderApp } from '../../test/render';
import { apiError, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { RUN_POLL_MS } from './RunView';

const NOW = Date.now() / 1000;
const HISTORY_POLL_MS = 4000;
const NOT_FOUND = 'Elementul nu mai există sau nu îți este disponibil.';
const SENDING_TITLE = 'Raportul se trimite pe email…';

const REPORT: Report = {
  id: 3, department_id: 1, name: 'Raport lunar contracte', instructions: 'Rezumă contractele lunii.', document_ids: [5],
  schedule_kind: 'manual', schedule_time: null, schedule_weekday: null, timezone: 'Europe/Bucharest',
  delivery_emails: ['sef@acme.ro'], delivery_status: 'approved', owner_id: 1, active: true,
  next_run_at: null, last_run_at: null, created_at: NOW - 100, updated_at: NOW - 100,
  last_run: null, can_edit: true, can_run: true,
};

function run(over: Partial<ReportRunDetail> = {}): ReportRunDetail {
  return {
    id: 40, report_id: 3, status: 'succeeded', trigger: 'manual', triggered_by: 1, model: 'qwen2.5', route: 'local', locality: 'local',
    error_code: null, error_reason: null, error: null, shared_company: false, delivered_to: [], delivery_state: null,
    started_at: NOW - 70, finished_at: NOW - 10, created_at: NOW - 75,
    content_md: '# Raport lunar\n\n## Rezumat\n\nPlata se face în 30 de zile.',
    citations: [], can_share: true, can_email: true, share_pending: false,
    report: { id: 3, name: 'Raport lunar contracte', department_id: 1 }, department_name: 'General', ...over,
  };
}

const SENDING = run({ delivery_state: 'pending' });
const RUNNING = run({ status: 'running', content_md: null, finished_at: null });

function boot(path: string, routes: Record<string, RouteHandler> = {}) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
    ...shellRoutes(),
    'GET /api/workspace/reports': { reports: [REPORT] },
    'GET /api/workspace/reports/3': REPORT,
    'GET /api/workspace/reports/3/runs': { runs: [] },
    'GET /api/workspace/documents': { documents: [] },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

function runStatus(): string {
  return document.querySelector('p.ws-sr-only[role="status"]')?.textContent ?? '';
}

async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

afterEach(() => { vi.useRealTimers(); });

describe('Run view → a run deleted while the page follows it (R4-01)', () => {
  it.each([
    ['while its email is on the way', SENDING, SENDING_TITLE, 'Raportul este gata și se trimite pe email…'],
    ['while it is being written', RUNNING, 'Raportul se scrie din documente. Poate dura câteva minute.', 'Raportul se scrie din documente. Poate dura câteva minute.'],
  ])('%s: stops polling, drops the stale page and says it is gone', async (_when, live, title, said) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': live });
    expect(await screen.findByText(title, { selector: '.ws-notice__title' })).toBeTruthy();
    await waitFor(() => expect(runStatus()).toBe(said));
    await tick(RUN_POLL_MS);

    // The report is deleted: the next read answers 404.
    mock.on('GET /api/workspace/report-runs/40', apiError(404, 'not_found'));
    await tick(RUN_POLL_MS);
    expect(await screen.findByText(NOT_FOUND, { selector: '.ws-empty__title' })).toBeTruthy();
    expect(screen.queryByText(title, { selector: '.ws-notice__title' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Toate rapoartele' }).getAttribute('href')).toBe('/workspace/reports');
    await waitFor(() => expect(runStatus()).toBe(NOT_FOUND));

    // ...and nothing polls it any more.
    const reads = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 10);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(reads);
  });

  it('a transient failure keeps the last copy and keeps polling until the outcome', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': SENDING });
    expect(await screen.findByText(SENDING_TITLE, { selector: '.ws-notice__title' })).toBeTruthy();
    mock.on('GET /api/workspace/report-runs/40', apiError(503, 'workspace_unavailable'));
    await tick(RUN_POLL_MS);
    await tick(RUN_POLL_MS);
    expect(screen.getByText(SENDING_TITLE, { selector: '.ws-notice__title' })).toBeTruthy();
    expect(screen.queryByText(NOT_FOUND, { selector: '.ws-empty__title' })).toBeNull();
    mock.on('GET /api/workspace/report-runs/40', run({ delivery_state: 'sent', delivered_to: ['sef@acme.ro'] }));
    await tick(RUN_POLL_MS);
    expect(await screen.findByText('Trimis pe email către')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText(SENDING_TITLE)).toBeNull());
  });
});

describe('Report detail → a report deleted while its history is followed (R4-01)', () => {
  it.each([
    ['its history and the report answer 404', true],
    ['only its history has been read since', false],
  ])('%s: stops polling and shows the not-found state', async (_case, reportGoneToo) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/reports/3', { 'GET /api/workspace/reports/3/runs': { runs: [SENDING] } });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(table.textContent).toContain('Se trimite pe email');
    await tick(HISTORY_POLL_MS);

    mock.on('GET /api/workspace/reports/3/runs', apiError(404, 'not_found'));
    if (reportGoneToo) mock.on('GET /api/workspace/reports/3', apiError(404, 'not_found'));
    await tick(HISTORY_POLL_MS);
    expect(await screen.findByText(NOT_FOUND, { selector: '.ws-empty__title' })).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Istoricul rulărilor' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Rulează acum' })).toBeNull();

    const reads = mock.find('GET', '/api/workspace/reports/3/runs').length;
    await tick(HISTORY_POLL_MS * 5);
    expect(mock.find('GET', '/api/workspace/reports/3/runs')).toHaveLength(reads);
  });
});
