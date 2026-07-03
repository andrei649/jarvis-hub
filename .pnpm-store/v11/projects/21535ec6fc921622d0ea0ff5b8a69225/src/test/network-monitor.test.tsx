// @ts-nocheck
/* H23.16 — the Console network-monitor panel reads the egress ledger
   (GET /api/admin/network/calls) and renders the local-only proof. fetch is mocked,
   like gap-panels.test.tsx — this asserts the wiring + the clean/violation display. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { NetworkMonitorPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('NetworkMonitorPanel (H23.16) — egress ledger is live', () => {
  it('GETs /api/admin/network/calls and shows the clean local-only proof', async () => {
    const fn = mockFetch({
      plugins: { worldview: { total: 2, allowed: 2, blocked: 0, external: 0, last_host: '127.0.0.1' } },
      recent: [], external_egress_total: 0, local_only_violations: [], clean: true, events_kept: 0,
    });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('worldview')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/admin/network/calls'))).toBe(true);
    expect(screen.getByText('clean')).toBeTruthy();
    expect(screen.getByText('0 external')).toBeTruthy();
  });

  it('surfaces a local-only violation in red instead of hiding it', async () => {
    mockFetch({
      plugins: { 'system-control': { total: 1, allowed: 1, blocked: 0, external: 1, last_host: '8.8.8.8' } },
      recent: [], external_egress_total: 1, local_only_violations: ['system-control'], clean: false, events_kept: 0,
    });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText(/local-only egress: system-control/)).toBeTruthy());
    expect(screen.getByText('violation')).toBeTruthy();
  });
});
