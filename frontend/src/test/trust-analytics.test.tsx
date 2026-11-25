// @ts-nocheck
/* HUD v2 · Trust + Analytics panels.
   - ObserveMode renders the MOONSHOT §6 north-star meter live from
     /api/metrics/north-star, showing "—" (never a fabricated 0) for null sources
     and flagging the ≤4/day interrupt budget breach.
   - The Trust overview (pages/TrustOverview.tsx, which replaced TrustMode at the Ledger cutover;
     PHASE_B_PLAN.md §6, §8.3) verifies the audit chain live via /api/security/audit/verify and
     reflects a real {valid, entries} / tamper result, and drives the emergency stop through
     frame/useKillSwitch: one click to stop, a typed DISENGAGE to resume, an unknown state that
     still offers the stop.
   Exercises component → hooks/api/actions → client → fetch (useKillSwitch is not mocked here). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { act, cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ObserveMode } from '../modes2';
import { TrustOverview } from '../pages/TrustOverview';
import { hubFixture } from '../pages/testkit';
import { resetPolling } from '../signals/poll';
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

  it('surfaces the P1 proactive row — night-shift share + proposal funnel', async () => {
    mockJson({
      '/api/metrics/north-star': {
        days: 7,
        north_star: { accepted_per_active_user: 3, total_accepted: 6, active_users: 2 },
        counter_metrics: { interrupt_rate_per_day: 1, reject_rate: 0.2, local_pct: 80, p95_latency_ms: 20 },
        night_shift: { done: 4, pct: 0.5, window: [23, 6] },
        proposal_funnel: { proposed: 8, surfaced: 6, accepted: 4, rejected: 2, pending: 2, surface_rate: 0.75, accept_rate: 0.6667 },
        raw: { decisions: 8 },
      },
    });

    render(<ObserveMode t={t} />);
    await waitFor(() => expect(screen.getByText('done overnight')).toBeTruthy());
    expect(screen.getByText('night share')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();          // night_shift.done
    expect(screen.getByText('50%')).toBeTruthy();         // night_shift.pct → 50%
    expect(screen.getByText('75%')).toBeTruthy();         // surface_rate → 75%
    expect(screen.getByText('67%')).toBeTruthy();         // accept_rate 0.6667 → 67%
    expect(screen.getByText('surfaced / proposed')).toBeTruthy();
    expect(screen.getByText('accept rate')).toBeTruthy();
  });

  it('renders the proactive row honestly as "—" when those blocks are absent', async () => {
    mockJson({
      '/api/metrics/north-star': {
        days: 7,
        north_star: { accepted_per_active_user: 0, total_accepted: 0, active_users: 0 },
        counter_metrics: { interrupt_rate_per_day: 0, reject_rate: null, local_pct: null, p95_latency_ms: null },
        night_shift: { done: 0, pct: null, window: [23, 6] },
        proposal_funnel: null,
        raw: { decisions: 0 },
      },
    });

    render(<ObserveMode t={t} />);
    await waitFor(() => expect(screen.getByText('night share')).toBeTruthy());
    // pct null + funnel null → em-dash, never a fabricated 0%
    expect(screen.getByText('surfaced / proposed')).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });
});

describe('Trust overview — the stop and the audit chain, live', () => {
  beforeEach(() => { resetPolling(); });
  afterEach(() => { cleanup(); resetPolling(); });
  const trust = () => render(<TrustOverview hub={hubFixture()} lang="en" demo={false} navigate={vi.fn()} />);
  const stopState = () => document.querySelector('#stop')?.getAttribute('data-stop-state');
  const posts = (fn) => fn.mock.calls.filter(([, init]) => init?.method === 'POST');

  it('offers the global stop again when the resume was accepted but the state could not be read back', async () => {
    let reads = 0;
    const fetcher = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/api/security/kill-switch')) {
        if (init?.method === 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => ({ engaged: false }) });
        reads += 1;
        return Promise.resolve(reads === 1
          ? { ok: true, status: 200, json: async () => ({ global: true, any_halted: true, halted_count: 1 }) }
          : { ok: false, status: 503, json: async () => ({ error: 'unavailable' }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ valid: true, first_invalid_id: null, entries: 1 }) });
    });
    global.fetch = fetcher as any;
    trust();
    await waitFor(() => expect(stopState()).toBe('halted'));
    // resuming is typed (DISENGAGE), never one click
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    fireEvent.change(screen.getByLabelText('Type DISENGAGE to resume the agents'), { target: { value: 'DISENGAGE' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Resume all agents' })); });
    // the hub took the resume, but the stop's state could not be read back: unknown, never "Armed"
    await waitFor(() => expect(stopState()).toBe('unknown'));
    expect(screen.queryByText('Armed')).toBeNull();
    const stop = screen.getByRole('button', { name: 'Stop all agents' });
    expect(stop.disabled).toBe(false);
    await act(async () => { fireEvent.click(stop); });
    await waitFor(() => expect(posts(fetcher)).toHaveLength(2));
    expect(posts(fetcher).map(([, init]) => JSON.parse(init.body).engage)).toEqual([false, true]);
    // the stop's own state is read again, and still unknown: said, not taken for success
    expect(await screen.findByText(/The stop was not confirmed/)).toBeTruthy();
  });

  it('says an agent-scoped halt while the global switch is off, and the stop still engages global', async () => {
    const fn = mockJson({
      '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 1 },
      '/api/security/kill-switch': { global: false, any_halted: true, halted_count: 1 },
    });
    trust();
    await waitFor(() => expect(screen.getByText('1 agent-scoped halt is in force; the global stop is armed and halts everything.')).toBeTruthy());
    expect(stopState()).toBe('armed');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Stop all agents' })); });
    await waitFor(() => expect(posts(fn)).toHaveLength(1));
    expect(JSON.parse(posts(fn)[0][1].body)).toMatchObject({ engage: true, scope: 'global' });
  });

  it('reflects a real {valid, entries} result from /api/security/audit/verify', async () => {
    mockJson({
      '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 42 },
      '/api/security/kill-switch': { global: false, any_halted: false, halted_count: 0 },
    });
    trust();
    await waitFor(() => expect(screen.getByText('Chain intact: 42 sealed entries')).toBeTruthy());
    expect(document.querySelector('[data-chain-state]')?.getAttribute('data-chain-state')).toBe('intact');
  });

  it('surfaces a tamper result when the chain is broken', async () => {
    mockJson({
      '/api/security/audit/verify': { valid: false, first_invalid_id: 17, entries: 30 },
      '/api/security/kill-switch': { global: false, any_halted: false, halted_count: 0 },
    });
    trust();
    await waitFor(() => expect(screen.getByText('Chain broken at entry 17')).toBeTruthy());
    expect(document.querySelector('[data-chain-state]')?.getAttribute('data-chain-state')).toBe('broken');
    expect(screen.queryByText(/Chain intact/)).toBeNull();
  });
});
