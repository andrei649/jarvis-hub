// @ts-nocheck
/* Regressions for the 2026-08-01 honesty fixes (test-manual ch04/ch10 findings):
   PNL-106 — A2A decide body is {approve}, not {approved} (422'd invisibly);
   dead-fallback — OAuth/auth-profile panels render the API's bare object maps;
   PNL-059 — a down KG store must not render as a clean empty graph;
   WFL-078/PNB-018 — EVAL compare reads the API's `regressed`/`improved` keys. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import gapSource from '../gap.tsx?raw';
import { A2AInboxPanel, AuthProfilesPanel, KgPanel, OAuthPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('A2AInboxPanel (PNL-106) — the only peer-task governance surface works', () => {
  it('POSTs {approve: true} to the decide endpoint', async () => {
    const fn = mockFetch({
      '/api/a2a/inbox': { inbox: [{ id: 't1', peer: 'peer-a', task: 'sync notes' }] },
    });
    render(<A2AInboxPanel />);
    await waitFor(() => expect(screen.getByText('peer-a')).toBeTruthy());
    fireEvent.click(screen.getAllByText('✓')[0]);
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/a2a/inbox/t1/decide') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ approve: true });
    });
  });
});

describe('OAuthPanel — bare {service: status} map renders (dead-fallback fix)', () => {
  it('shows each service with its connected state', async () => {
    mockFetch({
      '/api/oauth/status': {
        gmail: { connected: true, label: 'Gmail', auth_url: null },
        spotify: { connected: false, label: 'Spotify', auth_url: 'https://x/auth' },
      },
    });
    render(<OAuthPanel />);
    await waitFor(() => expect(screen.getByText('gmail')).toBeTruthy());
    expect(screen.getByText('spotify')).toBeTruthy();
    expect(screen.getByText('connected')).toBeTruthy();
    expect(screen.getByText('disconnected')).toBeTruthy();
  });
});

describe('AuthProfilesPanel — {pools: {provider: status}} renders (dead-fallback fix)', () => {
  it('lists each provider pool', async () => {
    mockFetch({
      '/api/llm/auth-profiles': { pools: { anthropic: { keys: 2, healthy: true }, gemini: { keys: 1, healthy: false } } },
    });
    render(<AuthProfilesPanel />);
    await waitFor(() => expect(screen.getByText('anthropic')).toBeTruthy());
    expect(screen.getByText('gemini')).toBeTruthy();
  });
});

describe('KgPanel (PNL-059) — a down store is not a clean empty graph', () => {
  it('surfaces the 200-with-error body instead of rendering silence', async () => {
    mockFetch({
      '/api/kg/entities': { entities: [], stats: {}, error: 'entity store not available' },
    });
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText(/entity store not available/)).toBeTruthy());
  });
});

describe('EvalPanel compare keys (WFL-078/PNB-018) — source-level pin', () => {
  it('reads regressed/improved (the API keys), not regressions/improvements', () => {
    expect(gapSource).toMatch(/cmp\.regressed/);
    expect(gapSource).toMatch(/cmp\.improved/);
    expect(gapSource).not.toMatch(/cmp\.regressions/);
    expect(gapSource).not.toMatch(/cmp\.improvements/);
  });
});
