// @ts-nocheck
/* AGENTS & ARENA panel — GET /api/agents/history (fleet rollup) + GET
   /api/arena/match/{id} (blind match detail). fetch is mocked per-URL, like
   src/test/arena-quality-panel.test.tsx.

   The assertions that carry the honesty burden, not the rendering ones:
   · the SAME empty rollup must produce DIFFERENT sentences depending on what
     /api/health/components says about the run_history component — the route answers 200
     {agents: []} for "no orchestrator", "component failed" and "genuinely idle" alike;
   · total_cost === 0 must never reach the screen as a spend figure;
   · a 503 and a 404 on the match read must be two visibly different, non-empty states;
   · apiPost throws on 4xx, so the run/vote refusals must render via onErr, VERBATIM, and
     "invalid vote" must not be expanded into "already voted";
   · an entry whose response starts with "[error:" is a stored exception, not an answer,
     and must not be votable. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AgentsArenaPanel } from './agents-arena';

/* handlers: [{ match, method?, status?, body }] — first match wins. */
function mockRoutes(handlers) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    for (const h of handlers) {
      if (u.includes(h.match) && (!h.method || h.method === method)) {
        const status = h.status || 200;
        return { ok: status < 400, status, json: async () => h.body };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  global.fetch = fn;
  return fn;
}

const HISTORY = {
  agents: [
    { agent_id: 'planner', runs: 13, last_ts: Date.now() / 1000 - 120, ok_rate: 0.923, avg_latency_ms: 812.4, total_cost: 0.0 },
    { agent_id: 'coder', runs: 4, last_ts: Date.now() / 1000 - 7200, ok_rate: 0.5, avg_latency_ms: 1904.0, total_cost: 0.0 },
  ],
};
const HEALTH_OK = { components: { run_history: 'ok', arena: 'ok' }, failed: [], summary: '2/2 components ok' };

const MATCH_BLIND = {
  id: 'm1',
  query: 'summarize the changelog',
  entries: [{ label: 'A', response: 'first answer' }, { label: 'B', response: 'second answer' }],
  voted: false,
  winner_label: null,
  winner_model: null,
  created_at: 1756700000,
};

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.user_token', 'u-tok'); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('AgentsArenaPanel — the fleet run-history rollup', () => {
  it('GETs /api/agents/history and renders runs / ok-rate / avg latency without inventing a spend figure', async () => {
    const fn = mockRoutes([
      { match: '/api/agents/history', body: HISTORY },
      { match: '/api/health/components', body: HEALTH_OK },
    ]);
    render(<AgentsArenaPanel />);

    await waitFor(() => expect(screen.getByText('13 runs')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/agents/history'))).toBe(true);
    expect(screen.getByText('92% ok')).toBeTruthy();
    expect(screen.getByText('812.4 ms avg')).toBeTruthy();
    expect(screen.getByText('50% ok')).toBeTruthy();

    // total_cost is structurally 0.0 (the recorder never passes `cost`) — never a figure.
    expect(screen.getAllByText('cost —').length).toBe(2);
    expect(screen.queryByText(/\$/)).toBeNull();
    // and the numbers are never called all-time
    expect(screen.getByText(/last ≤100 retained runs/)).toBeTruthy();
  });

  it('says "component failed" for an empty rollup when the health read reports run_history failed', async () => {
    mockRoutes([
      { match: '/api/agents/history', body: { agents: [] } },
      { match: '/api/health/components', body: { components: { run_history: 'failed' }, failed: ['run_history'], summary: '0/1 components ok; failed: run_history' } },
    ]);
    render(<AgentsArenaPanel />);

    await waitFor(() => expect(screen.getByText(/run-history component failed to initialize/)).toBeTruthy());
    expect(screen.getByText(/this is not zero runs/)).toBeTruthy();
    expect(screen.queryByText(/genuinely empty/)).toBeNull();
  });

  it('says "no runs recorded yet" for the SAME empty rollup when the component reports ok', async () => {
    mockRoutes([
      { match: '/api/agents/history', body: { agents: [] } },
      { match: '/api/health/components', body: HEALTH_OK },
    ]);
    render(<AgentsArenaPanel />);

    await waitFor(() => expect(screen.getByText(/no runs recorded yet/)).toBeTruthy());
    expect(screen.queryByText(/failed to initialize/)).toBeNull();
  });

  it('refuses to guess when the health read cannot confirm run_history at all', async () => {
    mockRoutes([
      { match: '/api/agents/history', body: { agents: [] } },
      { match: '/api/health/components', body: { components: {}, summary: 'registry unavailable' } },
    ]);
    render(<AgentsArenaPanel />);

    await waitFor(() => expect(screen.getByText(/component registry unavailable/)).toBeTruthy());
    expect(screen.getByText(/is NOT "zero runs"/)).toBeTruthy();
  });
});

describe('AgentsArenaPanel — the blind match detail read', () => {
  async function loadMatch(handlers, id = 'm1') {
    const fn = mockRoutes([
      { match: '/api/agents/history', body: HISTORY },
      { match: '/api/health/components', body: HEALTH_OK },
      ...handlers,
    ]);
    render(<AgentsArenaPanel />);
    await waitFor(() => expect(screen.getByText('LOAD')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/paste a match id/), { target: { value: id } });
    fireEvent.click(screen.getByText('LOAD'));
    return fn;
  }

  it('GETs /api/arena/match/<id> and renders the entries blind', async () => {
    const fn = await loadMatch([{ match: '/api/arena/match/', body: MATCH_BLIND }]);
    await waitFor(() => expect(screen.getByText('query: summarize the changelog')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/arena/match/m1')).toBe(true);
    expect(screen.getByText('BLIND')).toBeTruthy();
    expect(screen.getByText(/model identities are hidden until a vote/)).toBeTruthy();
    expect(screen.getByText('VOTE A')).toBeTruthy();
  });

  it('renders a 503 as a component outage — never as an empty match', async () => {
    await loadMatch([{ match: '/api/arena/match/', status: 503, body: { error: 'arena not available' } }]);
    await waitFor(() => expect(screen.getByText(/arena component not available \(503\)/)).toBeTruthy());
    expect(screen.getByText('GET /api/arena/match/m1 -> 503')).toBeTruthy();
    expect(screen.getByText(/This is a component outage/)).toBeTruthy();
    // the other cause must not be on screen, and nothing may read as an empty match
    expect(screen.queryByText(/no match with that id/)).toBeNull();
    expect(screen.queryByText('BLIND')).toBeNull();
  });

  it('renders a 404 as an unknown id — a different sentence from the 503', async () => {
    await loadMatch([{ match: '/api/arena/match/', status: 404, body: { error: 'not found' } }]);
    await waitFor(() => expect(screen.getByText(/no match with that id \(404\)/)).toBeTruthy());
    expect(screen.getByText('GET /api/arena/match/m1 -> 404')).toBeTruthy();
    expect(screen.queryByText(/component not available/)).toBeNull();
    expect(screen.queryByText(/BLIND/)).toBeNull();
  });

  it('flags an entry whose response is a stored exception and disables its vote', async () => {
    await loadMatch([{
      match: '/api/arena/match/',
      body: {
        ...MATCH_BLIND,
        entries: [{ label: 'A', response: '[error:TimeoutError()]' }, { label: 'B', response: 'a real answer' }],
      },
    }]);
    await waitFor(() => expect(screen.getByText('RUN FAILED')).toBeTruthy());
    expect(screen.getByText(/stored the exception\s+text as this candidate's answer/)).toBeTruthy();
    expect((screen.getByText('VOTE A') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('VOTE B') as HTMLButtonElement).disabled).toBe(false);
  });

  it("renders the vote refusal VERBATIM and never expands 'invalid vote' into 'already voted'", async () => {
    await loadMatch([
      { match: '/api/arena/vote', method: 'POST', status: 400, body: { error: 'invalid vote' } },
      { match: '/api/arena/match/', body: MATCH_BLIND },
    ]);
    await waitFor(() => expect(screen.getByText('VOTE A')).toBeTruthy());
    fireEvent.click(screen.getByText('VOTE A'));

    await waitFor(() => expect(screen.getByText(/vote refused · POST \/api\/arena\/vote · invalid vote/)).toBeTruthy());
    expect(screen.queryByText(/already voted/)).toBeNull();
    expect(screen.queryByText('VOTED')).toBeNull();
  });
});

describe('AgentsArenaPanel — the run that produces a match id', () => {
  async function setupRun(handlers) {
    const fn = mockRoutes([
      { match: '/api/agents/history', body: HISTORY },
      { match: '/api/health/components', body: HEALTH_OK },
      ...handlers,
    ]);
    render(<AgentsArenaPanel />);
    await waitFor(() => expect(screen.getAllByTitle(/add\/remove this agent/).length).toBe(2));
    const picks = screen.getAllByTitle(/add\/remove this agent/);
    fireEvent.click(picks[0]);
    fireEvent.click(picks[1]);
    fireEvent.change(screen.getByPlaceholderText(/the prompt to compare/), { target: { value: 'which is faster' } });
    fireEvent.click(screen.getByText('RUN MATCH'));
    return fn;
  }

  it('POSTs {query, agents:[…]} — never a hand-typed candidates map — then loads the returned id', async () => {
    const fn = await setupRun([
      { match: '/api/arena/run', method: 'POST', body: { ok: true, match: { id: 'abc123def456' } } },
      { match: '/api/arena/match/', body: { ...MATCH_BLIND, id: 'abc123def456' } },
    ]);

    await waitFor(() => expect(fn.mock.calls.some((c) => String(c[0]) === '/api/arena/match/abc123def456')).toBe(true));
    const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/arena/run'));
    expect(post).toBeTruthy();
    expect(String(post[1].method).toUpperCase()).toBe('POST');
    const body = JSON.parse(post[1].body);
    expect(body).toEqual({ query: 'which is faster', agents: ['planner', 'coder'] });
    expect(body.candidates).toBeUndefined();
    await waitFor(() => expect(screen.getByText('query: summarize the changelog')).toBeTruthy());
  });

  it('renders a refused run through onErr, verbatim, with no match state (the dead-branch guard)', async () => {
    await setupRun([
      { match: '/api/arena/run', method: 'POST', status: 503, body: { error: 'arena not available' } },
      { match: '/api/arena/match/', body: MATCH_BLIND },
    ]);

    await waitFor(() => expect(screen.getByText(/run refused · POST \/api\/arena\/run · arena not available/)).toBeTruthy());
    expect(screen.getByText(/no match loaded/)).toBeTruthy();
    expect(screen.queryByText('BLIND')).toBeNull();
    expect(screen.queryByText('VOTE A')).toBeNull();
  });
});
