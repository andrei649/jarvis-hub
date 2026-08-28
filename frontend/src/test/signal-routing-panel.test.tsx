// @ts-nocheck
/* T-0.41 — the Console SignalRoutingPanel reads the live routed World Signal
   feed (GET /api/signals/routed, user-guarded). fetch is mocked. Asserts the
   read wiring, the per-domain/per-agent chips, that unclassifiable signals are
   surfaced rather than hidden, and the honest no-sidecar state. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SignalRoutingPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SignalRoutingPanel — the routed world-signal feed is live', () => {
  it('GETs /api/signals/routed and renders domain + agent slices', async () => {
    const fn = mockFetch({
      available: true, reason: null, freshness: { age_s: 12 },
      signals: [
        { title: 'Missile strike near border', severity: 4 },
        { title: 'Ransomware breach at bank', severity: 5 },
      ],
      by_domain: { conflict: [0], cyber: [1] },
      by_agent: { argus: [0, 1], ultron: [1] },
      unrouted: [],
      counts: { signals: 2, routed: 2, unrouted: 0 },
    });
    render(<SignalRoutingPanel />);
    await waitFor(() => expect(screen.getByText('Missile strike near border')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/signals/routed'))).toBe(true);
    expect(screen.getByText('2/2 routed')).toBeTruthy();
    expect(screen.getByText('conflict 1')).toBeTruthy();
    expect(screen.getByText('ultron 1')).toBeTruthy();
    expect(screen.getByText('sev 5')).toBeTruthy();
  });

  it('surfaces unclassified signals instead of hiding them', async () => {
    mockFetch({
      available: true, reason: null, freshness: {},
      signals: [{ title: 'Something odd', severity: 1 }],
      by_domain: {}, by_agent: {}, unrouted: [0],
      counts: { signals: 1, routed: 0, unrouted: 1 },
    });
    render(<SignalRoutingPanel />);
    await waitFor(() => expect(screen.getByText(/1 unclassified/)).toBeTruthy());
    expect(screen.getByText(/never guessed/)).toBeTruthy();
  });

  it('is honest when no sidecar is configured', async () => {
    mockFetch({
      available: false, reason: 'signal_layer_plugin_unavailable', freshness: {},
      signals: [], by_domain: {}, by_agent: {}, unrouted: [],
      counts: { signals: 0, routed: 0, unrouted: 0 },
    });
    render(<SignalRoutingPanel />);
    await waitFor(() => expect(screen.getByText(/signal layer unavailable/)).toBeTruthy());
    expect(screen.getByText(/signal_layer_plugin_unavailable/)).toBeTruthy();
  });
});
