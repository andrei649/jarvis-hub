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

/* H381 — the ledger survives a restart: the route serves rows recorded before this hub
   started (`origin: restored`) next to live ones, and the panel must show both and say
   since when the proof is kept — or that it is memory-only. */
describe('NetworkMonitorPanel (H381) — persisted + live egress rows', () => {
  const persisted = (over = {}) => ({
    plugins: { 'llm:anthropic': { total: 2, allowed: 2, blocked: 0, external: 2, last_host: 'api.anthropic.com' } },
    recent: [
      { ts: '2026-11-02T09:15:00.000000+00:00', plugin: 'llm:anthropic', host: 'api.anthropic.com', method: 'POST', allowed: true, local: false, reason: '', origin: 'live' },
      { ts: '2026-11-01T22:40:00.000000+00:00', plugin: 'llm:anthropic', host: 'api.anthropic.com', method: 'POST', allowed: true, local: false, reason: '', origin: 'restored' },
      { ts: '2026-11-01T22:39:00.000000+00:00', plugin: 'weather', host: 'wttr.in', method: 'GET', allowed: true, local: false, reason: '', origin: 'restored' },
    ],
    external_egress_total: 2, model_egress_total: 2, local_only_violations: [], clean: true, events_kept: 3,
    ledger: { persistent: true, store: 'egress_ledger.db', since: '2026-10-30T08:00:00.000000+00:00',
      stored_events: 3, restored_events: 2, live_events: 1, unsaved_events: 0, max_events: 1000, error: '' },
    ...over,
  });

  it('shows since when the proof is kept and the restored + live model rows by host', async () => {
    mockFetch(persisted());
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('saved since 2026-10-30')).toBeTruthy());
    expect(screen.getByText('2 restored')).toBeTruthy();
    expect(screen.getByText('1 live')).toBeTruthy();
    expect(screen.getByText('where model calls went')).toBeTruthy();
    const rows = screen.getAllByText('llm:anthropic → api.anthropic.com');
    expect(rows.length).toBe(2);                       // plugin rows are not listed as prompts
    expect(screen.queryByText('weather → wttr.in')).toBeNull();
    expect(screen.getByText('restored')).toBeTruthy();
    expect(screen.getByText('live')).toBeTruthy();
  });

  it('says the ledger is memory-only — and why — instead of implying it is kept', async () => {
    mockFetch(persisted({
      recent: [{ ts: '2026-11-02T09:15:00.000000+00:00', plugin: 'llm:gemini', host: 'generativelanguage.googleapis.com', method: 'POST', allowed: true, local: false, reason: '', origin: 'live' }],
      ledger: { persistent: false, store: 'egress_ledger.db', since: null, stored_events: 0, restored_events: 0,
        live_events: 1, unsaved_events: 1, max_events: 1000, error: 'read failed: OperationalError' },
    }));
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('memory only — lost on restart')).toBeTruthy());
    expect(screen.getByText('1 unsaved')).toBeTruthy();
    expect(screen.getByText(/ledger store: read failed: OperationalError/)).toBeTruthy();
    expect(screen.queryByText(/saved since/)).toBeNull();
    expect(screen.getByText('llm:gemini → generativelanguage.googleapis.com')).toBeTruthy();
  });

  it('a refused model call is listed as refused, with its origin', async () => {
    mockFetch(persisted({
      recent: [{ ts: '2026-11-01T22:40:00.000000+00:00', plugin: 'llm:openrouter', host: 'api.anthropic.com', method: 'POST', allowed: false, local: false, reason: 'refused', origin: 'restored' }],
    }));
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('llm:openrouter → api.anthropic.com')).toBeTruthy());
    expect(screen.getByText('refused')).toBeTruthy();
  });

  it('an older backend with no ledger block makes no persistence claim', async () => {
    const older = persisted();
    delete older.ledger;
    mockFetch(older);
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('llm:anthropic')).toBeTruthy());
    expect(screen.queryByText(/saved since/)).toBeNull();
    expect(screen.queryByText(/memory only/)).toBeNull();
  });
});
