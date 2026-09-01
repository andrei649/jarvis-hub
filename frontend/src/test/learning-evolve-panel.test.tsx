// @ts-nocheck
/* DRA-41 — the self-evolution trigger next to its promotion twin. LEARNING ·
   BENCH already drives POST /api/learning/propose; the H20.4 prompt-optimization
   half had no surface at all. The 503 case is the load-bearing one: apiPost
   throws on 4xx/5xx, so a button without an onErr branch reads as success. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { LearningPanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'sekret'); } catch { /* ignore */ }
});

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation(async (url) => {
    const u = String(url);
    const hit = Object.keys(routes).find((k) => u.includes(k));
    const r = hit ? routes[hit] : { payload: {} };
    const status = r.status || 200;
    return { ok: status < 400, status, json: async () => r.payload };
  });
  global.fetch = fn;
  return fn;
}

const evolveCalls = (fn) => fn.mock.calls.filter((c) => String(c[0]).includes('/api/learning/evolve'));

describe('LearningPanel — the prompt-evolution trigger', () => {
  it('POSTs /api/learning/evolve with the admin header and reports the count', async () => {
    const fn = mockFetch({
      '/api/learning/evolve': { payload: { ok: true, count: 2, proposed: [{ agent: 'ana' }, { agent: 'bruce' }] } },
      '/learning': { payload: { promotion_suggestions: [] } },
    });
    render(<LearningPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'propose prompt optimizations' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'propose prompt optimizations' }));
    await waitFor(() => expect(screen.getByText(/2 prompt optimization/)).toBeTruthy());
    const call = evolveCalls(fn)[0];
    expect(call[1].method).toBe('POST');
    expect(call[1].headers['X-Admin-Token']).toBe('sekret');
  });

  it('renders a refusal when the route answers 503 instead of reading as success', async () => {
    mockFetch({
      '/api/learning/evolve': { status: 503, payload: { error: 'not available' } },
      '/learning': { payload: { promotion_suggestions: [] } },
    });
    render(<LearningPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'propose prompt optimizations' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'propose prompt optimizations' }));
    await waitFor(() => expect(screen.getByText(/refused/)).toBeTruthy());
    expect(screen.getByText(/503/)).toBeTruthy();
    expect(screen.queryByText(/prompt optimization\(s\) proposed/)).toBeNull();
  });
});
