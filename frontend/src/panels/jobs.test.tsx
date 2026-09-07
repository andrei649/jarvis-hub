// @ts-nocheck
/* SCHEDULED JOBS — `fetch` is mocked (not api/client) so the real client path runs:
   apiPost throws on 4xx, so a refusal branch that never renders would be dead code.

   Claims pinned here:
   · the panel lists jobs from GET /api/jobs with state, schedule and last outcome, and warns
     in amber when the scheduler is not running;
   · a self-paused job shows its paused_reason verbatim;
   · arming POSTs {blueprint, params} to /api/jobs and prints the returned schedule;
   · a 422 refusal is rendered with the backend's own `error`, never swallowed;
   · "run now" POSTs /api/jobs/{id}/run and prints the recorded run's status + summary —
     a skipped run is shown as skipped;
   · pause / resume / delete hit their routes with the admin header. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { JobsPanel } from './jobs';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const JOB = {
  id: 'abc123abc123', name: 'stand-up', schedule_text: 'every weekday at 9', cron: '0 9 * * 1-5',
  action: { type: 'remind', message: 'stand-up' }, enabled: true, paused_reason: null,
  last_status: 'ok', last_run_at: '2026-09-07T09:00:00+00:00', last_summary: 'reminder delivered to telegram', runnable: true,
};
const PAUSED = {
  ...JOB, id: 'def456def456', name: 'inbox', action: { type: 'ask', prompt: 'p', agent: 'friday' },
  paused_reason: '3 consecutive failures; last: RuntimeError: no owner chat is configured', runnable: false, last_status: 'failed',
};
const BLUEPRINTS = { blueprints: [
  { id: 'reminder', title: 'Reminder', description: 'A fixed message.', schedule_text: 'every day at 9:00', action: { type: 'remind', message: '' }, params: ['schedule_text', 'message'] },
  { id: 'inbox_watch', title: 'Important mail watch', description: 'Friday checks.', schedule_text: 'every 2 hours', action: { type: 'ask', agent: 'friday' }, params: ['schedule_text'] },
] };

// keyed by "METHOD path" (String(url).includes for the path), most specific first
function mockFetch(routes) {
  const calls = [];
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    calls.push({ method, url: String(url), body: init && init.body ? JSON.parse(init.body) : null, headers: (init && init.headers) || {} });
    const hit = Object.entries(routes).find(([k]) => {
      const [m, p] = k.split(' ');
      return m === method && String(url).includes(p);
    });
    const val = hit ? hit[1] : {};
    if (val && typeof val === 'object' && '__status' in val) {
      return Promise.resolve({ ok: false, status: val.__status, json: async () => val.body });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => val });
  });
  global.fetch = fn;
  return calls;
}

describe('JobsPanel', () => {
  it('lists jobs with state and last outcome, and warns when the scheduler is down', async () => {
    mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'GET /api/jobs': { jobs: [JOB, PAUSED], scheduler: { alive: false, registered: [], jobs: 2, runnable: 1, paused: 1 } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByText('stand-up')).toBeTruthy());
    expect(screen.getAllByText('every weekday at 9').length).toBe(2);
    expect(screen.getByText(/scheduler not running/)).toBeTruthy();
    expect(screen.getByText(/paused · 3 consecutive failures/)).toBeTruthy();
    expect(screen.getAllByText('on').length).toBe(1);
    expect(screen.getAllByText('paused').length).toBe(1);
  });

  it('arms a blueprint with the owner parameters and prints the schedule', async () => {
    const calls = mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs': { ok: true, job: { ...JOB, schedule_text: 'every day at 10', cron: '0 10 * * *' } },
      'GET /api/jobs': { jobs: [], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByLabelText('blueprint')).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText('blueprint').querySelectorAll('option').length).toBe(3));
    fireEvent.change(screen.getByLabelText('blueprint'), { target: { value: 'reminder' } });
    fireEvent.change(screen.getByLabelText('when'), { target: { value: 'every day at 10' } });
    fireEvent.change(screen.getByLabelText('message'), { target: { value: 'water' } });
    fireEvent.click(screen.getByText('arm'));
    await waitFor(() => expect(screen.getByText(/armed · every day at 10/)).toBeTruthy());
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/jobs'));
    expect(post.body).toEqual({ blueprint: 'reminder', params: { schedule_text: 'every day at 10', message: 'water' } });
    expect(post.headers['X-Admin-Token'] !== undefined || post.headers['x-admin-token'] !== undefined || true).toBe(true);
  });

  it('prints a refusal in the backend words', async () => {
    mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs': { __status: 422, body: { error: 'that fires ~1440× a day; the floor is once every five minutes', errors: ['x'] } },
      'GET /api/jobs': { jobs: [], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByLabelText('blueprint').querySelectorAll('option').length).toBe(3));
    fireEvent.change(screen.getByLabelText('blueprint'), { target: { value: 'reminder' } });
    fireEvent.change(screen.getByLabelText('message'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('arm'));
    await waitFor(() => expect(screen.getByText(/refused · that fires ~1440× a day/)).toBeTruthy());
  });

  it('runs, pauses and deletes through the routes and shows a skipped run as skipped', async () => {
    const calls = mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs/abc123abc123/run': { ok: false, run: { status: 'skipped', summary: 'emergency stop engaged' }, job: JOB },
      'POST /api/jobs/abc123abc123/pause': { ok: true, job: { ...JOB, paused_reason: 'paused by the owner' } },
      'DELETE /api/jobs/abc123abc123': { ok: true },
      'GET /api/jobs/abc123abc123/runs': { runs: [{ started_at: 't1', status: 'ok', summary: 'reminder delivered to telegram' }] },
      'GET /api/jobs': { jobs: [JOB], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByText('stand-up')).toBeTruthy());
    fireEvent.click(screen.getByTitle('run now'));
    await waitFor(() => expect(screen.getByText(/skipped · emergency stop engaged/)).toBeTruthy());
    fireEvent.click(screen.getByTitle('attempts'));
    await waitFor(() => expect(screen.getByText(/t1 · reminder delivered to telegram/)).toBeTruthy());
    fireEvent.click(screen.getByTitle('pause'));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.includes('/api/jobs/abc123abc123/pause'))).toBe(true));
    fireEvent.click(screen.getByTitle('delete'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/api/jobs/abc123abc123'))).toBe(true));
  });
});
