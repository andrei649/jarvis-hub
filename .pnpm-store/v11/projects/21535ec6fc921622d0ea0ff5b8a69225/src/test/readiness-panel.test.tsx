// @ts-nocheck
/* HUD-v3 B3 — the Console Verification Fabric / Readiness panel reads the capability
   registry (GET /api/metrics/capabilities) and renders the SEAM→WIRED→VERIFIED→GA
   ladder. fetch is mocked, like kernel-safety-panels.test.tsx — asserts the wiring,
   the roll-up tags, the per-capability state, and the honesty contract (the
   harness-pending banner that refuses to imply verification we can't back). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ReadinessPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('ReadinessPanel — the Verification Fabric board is live', () => {
  it('GETs /api/metrics/capabilities and shows the readiness ladder + a capability', async () => {
    const fn = mockFetch({
      total: 33,
      by_state: { seam: 2, wired: 31, verified: 0, ga: 0 },
      by_kind: { plugin: 20, component: 8, skill: 5 },
      harness_pending: true,
      capabilities: [{ id: 'plugin:analytics', kind: 'plugin', state: 'wired' }],
    });
    render(<ReadinessPanel />);
    await waitFor(() => expect(screen.getByText('31 wired')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/metrics/capabilities'))).toBe(true);
    expect(screen.getByText('2 seam')).toBeTruthy();
    expect(screen.getByText('0 verified')).toBeTruthy();
    expect(screen.getByText('plugin:analytics')).toBeTruthy();
  });

  it('renders the honesty banner while the harness has proven nothing (harness_pending)', async () => {
    mockFetch({
      total: 5, by_state: { seam: 0, wired: 5, verified: 0, ga: 0 },
      by_kind: {}, harness_pending: true, capabilities: [],
    });
    render(<ReadinessPanel />);
    await waitFor(() => expect(screen.getByText(/not yet proven/)).toBeTruthy());
  });

  it('does NOT show the harness-pending banner once something is VERIFIED', async () => {
    mockFetch({
      total: 4, by_state: { seam: 0, wired: 2, verified: 2, ga: 0 },
      by_kind: {}, harness_pending: false,
      capabilities: [{ id: 'component:router', kind: 'component', state: 'verified' }],
    });
    render(<ReadinessPanel />);
    await waitFor(() => expect(screen.getByText('2 verified')).toBeTruthy());
    expect(screen.queryByText(/not yet proven/)).toBeNull();
  });
});
