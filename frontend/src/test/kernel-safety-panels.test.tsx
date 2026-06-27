// @ts-nocheck
/* Track-K — the Console KernelMetrics + LoopBreaker panels read the kernel decision
   meter (GET /api/metrics/kernel) and the loop-breaker endpoint (GET /api/security/
   loop-breaker) and render the operator surface. fetch is mocked, like
   network-monitor.test.tsx — this asserts the wiring + the display/conditional controls. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { KernelMetricsPanel, LoopBreakerPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('KernelMetricsPanel — the Action-Kernel decision meter is live', () => {
  it('GETs /api/metrics/kernel and shows verdict tallies + a recent denial', async () => {
    const fn = mockFetch({
      total: 3, by_verdict: { grant: 1, queue: 1, deny: 1 }, deny_rate: 0.3333,
      by_kind: {}, recent_denials: [{ kind: 'payment', reason: "kill-switch engaged for scope 'global'" }],
    });
    render(<KernelMetricsPanel />);
    await waitFor(() => expect(screen.getByText('1 grant')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/metrics/kernel'))).toBe(true);
    expect(screen.getByText('1 deny')).toBeTruthy();
    expect(screen.getByText('payment')).toBeTruthy();
  });

  it('shows the default-off hint when the meter is empty', async () => {
    mockFetch({ total: 0, by_verdict: { grant: 0, queue: 0, deny: 0 }, deny_rate: 0, by_kind: {}, recent_denials: [] });
    render(<KernelMetricsPanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_ACTION_KERNEL/)).toBeTruthy());
  });
});

describe('LoopBreakerPanel — breaker status + operator reset', () => {
  it('surfaces a tripped breaker AND offers reset', async () => {
    mockFetch({ tripped: true, max_repeats: 10, window_seconds: 60, recent_events: 3 });
    render(<LoopBreakerPanel />);
    await waitFor(() => expect(screen.getByText(/runaway halted/)).toBeTruthy());
    expect(screen.getByText('reset')).toBeTruthy();
  });

  it('shows closed/normal with NO reset button when healthy', async () => {
    mockFetch({ tripped: false, max_repeats: 10, window_seconds: 60, recent_events: 0 });
    render(<LoopBreakerPanel />);
    await waitFor(() => expect(screen.getByText(/closed · normal/)).toBeTruthy());
    expect(screen.queryByText('reset')).toBeNull();
  });
});
