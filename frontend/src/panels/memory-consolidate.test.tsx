// @ts-nocheck
/* CONSOLIDATE panel — `fetch` is mocked (not api/client) so the REAL client path runs:
   apiPost THROWS on 4xx, so a refusal branch that is never wired would be dead code here.

   Claims pinned:
   · the preview is read from the backend and its rows are rendered, never fabricated;
   · `available:false` renders the backend's reason under an amber chip, not an empty list;
   · with zero existing rows the plan/apply controls are WITHHELD and the card says why
     (a plan against nothing is degenerate) — it never POSTs `existing: []`;
   · the plan POST carries the parsed candidates (`key: text` → {key, text}) and the
     preview's own `existing` rows verbatim;
   · a dry run POSTs `dry_run: true` and renders "nothing written"; a real apply renders the
     snapshot counts AND the persisted counts AND every skipped row with its reason;
   · a 422 refusal reaches the screen with the backend's `reason` verbatim and no success line. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryConsolidatePanel, parseCandidates } from './memory-consolidate';

const PREVIEW = {
  available: true,
  query: '',
  total: 2,
  tainted: false,
  action_origin: 'generated',
  existing: [
    { id: 'mem-1', key: 'home_city', text: 'User lives in Bucharest', source: 'vector', persistable: true, tainted: false },
    { id: 'Rex', key: null, text: 'User has a dog named Rex', source: 'graph', persistable: false, tainted: false },
  ],
};

const PLAN = {
  plan: [
    { op: 'UPDATE', target_id: 'mem-1', text: 'User lives in Cluj', key: 'home_city', reason: 'supersedes prior value' },
    { op: 'ADD', text: 'User works as an architect', key: 'job', reason: 'novel' },
  ],
  summary: { ADD: 1, UPDATE: 1, DELETE: 0, NOOP: 0 },
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const refuse = (status, payload) => ({ ok: false, status, json: async () => payload });

/* route-keyed, most-specific first (String(url).includes) */
function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

const postTo = (fn, path) => fn.mock.calls.find((c) => String(c[0]).includes(path) && c[1] && c[1].method === 'POST');

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('parseCandidates', () => {
  it('splits lines and lifts an optional key prefix', () => {
    expect(parseCandidates('home_city: User lives in Cluj\n\nno key here\n')).toEqual([
      { key: 'home_city', text: 'User lives in Cluj' },
      { text: 'no key here' },
    ]);
  });
});

describe('MemoryConsolidatePanel — the sixth hygiene leg, wired honestly', () => {
  it('GETs the preview and renders the existing rows with their provenance', async () => {
    const fn = mockFetch({ '/api/memory/consolidate/preview': ok(PREVIEW) });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText('User lives in Bucharest')).toBeTruthy());
    expect(screen.getByText('User has a dog named Rex')).toBeTruthy();
    expect(screen.getByText('graph-only')).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/memory/consolidate/preview'))).toBe(true);
  });

  it('renders the backend reason when no memory manager is available', async () => {
    mockFetch({ '/api/memory/consolidate/preview': ok({ available: false, reason: 'memory_unavailable', existing: [], total: 0, query: '', tainted: false }) });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText(/memory_unavailable/)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
  });

  it('withholds plan and apply when nothing was recalled and says why', async () => {
    const fn = mockFetch({ '/api/memory/consolidate/preview': ok({ ...PREVIEW, existing: [], total: 0 }) });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText(/degenerate/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('candidate memories'), { target: { value: 'User lives in Cluj' } });
    const plan = screen.getByText('plan');
    expect(plan.disabled).toBe(true);
    fireEvent.click(plan);
    expect(postTo(fn, '/api/memory/consolidate')).toBeUndefined();   // never `existing: []`
  });

  it('POSTs the plan with parsed candidates and the preview rows verbatim, then renders the ops', async () => {
    const fn = mockFetch({
      '/api/memory/consolidate/preview': ok(PREVIEW),
      '/api/memory/consolidate': ok(PLAN),
    });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText('User lives in Bucharest')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('candidate memories'), {
      target: { value: 'home_city: User lives in Cluj\nUser works as an architect' },
    });
    fireEvent.click(screen.getByText('plan'));
    await waitFor(() => expect(screen.getByText('UPDATE')).toBeTruthy());
    const post = postTo(fn, '/api/memory/consolidate');
    expect(JSON.parse(post[1].body)).toEqual({
      candidates: [{ key: 'home_city', text: 'User lives in Cluj' }, { text: 'User works as an architect' }],
      existing: PREVIEW.existing,
    });
    expect(screen.getByText('supersedes prior value')).toBeTruthy();
    expect(screen.getByText('ADD 1 · UPDATE 1 · DELETE 0 · NOOP 0')).toBeTruthy();
  });

  it('dry run POSTs dry_run:true and renders that nothing was written', async () => {
    const fn = mockFetch({
      '/api/memory/consolidate/preview': ok(PREVIEW),
      '/api/memory/consolidate/apply': ok({
        ok: true, dry_run: true, counts: { ADD: 1, UPDATE: 1, DELETE: 0, NOOP: 0 }, errors: [],
        memories: PREVIEW.existing, persisted: { ADD: 0, UPDATE: 0, DELETE: 0 }, skipped: [], persistence: 'dry_run',
      }),
      '/api/memory/consolidate': ok(PLAN),
    });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText('User lives in Bucharest')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('candidate memories'), { target: { value: 'User lives in Cluj' } });
    fireEvent.click(screen.getByText('plan'));
    await waitFor(() => expect(screen.getByText('UPDATE')).toBeTruthy());
    fireEvent.click(screen.getByText('dry run'));
    await waitFor(() => expect(screen.getByText(/nothing written/)).toBeTruthy());
    const post = postTo(fn, '/api/memory/consolidate/apply');
    expect(JSON.parse(post[1].body)).toEqual({ plan: PLAN.plan, existing: PREVIEW.existing, dry_run: true });
    expect(screen.queryByText(/^persisted/)).toBeNull();
  });

  it('apply renders the snapshot counts, the persisted counts and every skipped row with its reason', async () => {
    mockFetch({
      '/api/memory/consolidate/preview': ok(PREVIEW),
      '/api/memory/consolidate/apply': ok({
        ok: true, dry_run: false, counts: { ADD: 1, UPDATE: 1, DELETE: 1, NOOP: 0 }, errors: [],
        memories: [], persisted: { ADD: 1, UPDATE: 1, DELETE: 0 },
        skipped: [{ index: 2, op: 'DELETE', reason: 'not_vector_backed' }], persistence: 'vector_store',
      }),
      '/api/memory/consolidate': ok(PLAN),
    });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText('User lives in Bucharest')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('candidate memories'), { target: { value: 'User lives in Cluj' } });
    fireEvent.click(screen.getByText('plan'));
    await waitFor(() => expect(screen.getByText('UPDATE')).toBeTruthy());
    fireEvent.click(screen.getByText('apply'));
    await waitFor(() => expect(screen.getByTestId('apply-result')).toBeTruthy());
    const text = screen.getByTestId('apply-result').textContent;
    expect(text).toContain('applied · snapshot ADD 1 · UPDATE 1 · DELETE 1 · NOOP 0');
    expect(text).toContain('persisted ADD 1 · UPDATE 1 · DELETE 0 · vector_store');
    expect(text).toContain('skipped DELETE #2 · not_vector_backed');
  });

  it('renders a 422 refusal with the backend reason verbatim and no success line', async () => {
    mockFetch({
      '/api/memory/consolidate/preview': ok(PREVIEW),
      '/api/memory/consolidate/apply': refuse(422, { error: 'plan not admissible', reason: 'unknown_target:0', reasons: ['unknown_target:0'] }),
      '/api/memory/consolidate': ok(PLAN),
    });
    render(<MemoryConsolidatePanel />);
    await waitFor(() => expect(screen.getByText('User lives in Bucharest')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('candidate memories'), { target: { value: 'User lives in Cluj' } });
    fireEvent.click(screen.getByText('plan'));
    await waitFor(() => expect(screen.getByText('UPDATE')).toBeTruthy());
    fireEvent.click(screen.getByText('apply'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('apply refused (422)'));
    expect(screen.getByRole('alert').textContent).toContain('unknown_target:0');
    expect(screen.queryByTestId('apply-result')).toBeNull();
  });
});
