// @ts-nocheck
/* HUD v2 · Trust + Analytics panels.
   - ObserveMode renders the MOONSHOT §6 north-star meter live from
     /api/metrics/north-star, showing "—" (never a fabricated 0) for null sources
     and flagging the ≤4/day interrupt budget breach.
   - TrustMode verifies the audit chain live via /api/security/audit/verify and
     reflects a real {valid, entries} / tamper result instead of a static badge.
   Exercises component → api/actions → client → fetch. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ObserveMode } from '../modes2';
import { TrustMode } from '../modes';
import { V2 } from '../data';

const t = V2.I18N.en;

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockJson(routes: Record<string, any>) {
  const fn = vi.fn().mockImplementation((url: string) => {
    const path = String(url);
    const hit = Object.keys(routes).find((k) => path.includes(k));
    return Promise.resolve({
      ok: true, status: 200,
      json: async () => (hit ? routes[hit] : {}),
      blob: async () => new Blob([]),
    });
  });
  global.fetch = fn as any;
  return fn;
}

describe('ObserveMode — north-star meter is live', () => {
  it('GETs /api/metrics/north-star and renders honest "—" for null metrics', async () => {
    const fetchMock = mockJson({
      '/api/metrics/north-star': {
        days: 7,
        north_star: { accepted_per_active_user: 0, total_accepted: 0, active_users: 0 },
        counter_metrics: { interrupt_rate_per_day: 0, reject_rate: null, local_pct: null, p95_latency_ms: null },
        raw: { decisions: 0 },
      },
    });

    render(<ObserveMode t={t} />);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/metrics/north-star'));
      expect(call).toBeTruthy();
    });
    // Null counter-metrics (reject_rate, local_pct, p95) must show as em-dash, not "0".
    await waitFor(() => {
      expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
    });
    expect(screen.getByText('accepted / user · wk')).toBeTruthy();
    expect(screen.getByText('% served local')).toBeTruthy();
  });

  it('flags the interrupt rate when it breaches the ≤4/day budget', async () => {
    mockJson({
      '/api/metrics/north-star': {
        days: 7,
        north_star: { accepted_per_active_user: 3.5, total_accepted: 7, active_users: 2 },
        counter_metrics: { interrupt_rate_per_day: 6, reject_rate: 0.25, local_pct: 100, p95_latency_ms: 12 },
        raw: { decisions: 9 },
      },
    });

    render(<ObserveMode t={t} />);
    // Over-budget interrupt counter renders the ⚠ marker in its label.
    await waitFor(() => {
      expect(screen.getByText(/interrupts \/ day ⚠/)).toBeTruthy();
    });
    // Ratio reject_rate 0.25 → "25%"; local_pct 100 → "100%".
    expect(screen.getByText('25%')).toBeTruthy();
    expect(screen.getByText('100%')).toBeTruthy();
  });
});

describe('TrustMode — audit chain is verified live', () => {
  it('reflects a real {valid, entries} result from /api/security/audit/verify', async () => {
    mockJson({
      '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 42 },
      '/api/security/kill-switch': { halted: false },
    });

    render(<TrustMode t={t} localPct={100} />);
    await waitFor(() => {
      expect(screen.getByText(/42 sealed entries/)).toBeTruthy();
    });
  });

  it('surfaces a tamper result when the chain is broken', async () => {
    mockJson({
      '/api/security/audit/verify': { valid: false, first_invalid_id: 17, entries: 30 },
      '/api/security/kill-switch': { halted: false },
    });

    render(<TrustMode t={t} localPct={100} />);
    await waitFor(() => {
      expect(screen.getByText(/TAMPER DETECTED · first bad row #17/)).toBeTruthy();
    });
  });
});
