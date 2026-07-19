// @ts-nocheck
/* The World tab's WorldView surface row used to be a dead <a> link. It now polls
   our own GET /api/worldview/overview and renders a real connected/not-connected
   badge PLUS the flagship read data (recon windows / due alerts) when connected —
   independent of the (unrelated) Signal Layer service the rest of the tab depends
   on, so one being down must not hide the other's state. Never fabricates a
   connection or a recon pass. fetch is mocked, like network-monitor.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { WorldIntelligenceMode } from '../modes_world';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(map: Record<string, any>) {
  const fn = vi.fn(async (url: any) => {
    const key = Object.keys(map).find((k) => String(url).includes(k));
    if (key === undefined) return { ok: false, status: 404, json: async () => ({}) };
    const v = map[key];
    if (v === 'FAIL') return { ok: false, status: 500, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => v };
  });
  global.fetch = fn;
  return fn;
}

const SIGNAL_LAYER_UP = {
  '/provider-health/worldmonitor': { status: 'ok', provider: 'worldmonitor', mode: 'replay' },
  '/briefs/world': { title: 'Brief', executiveSummary: 'sum', globalStatus: 'NOMINAL', recommendations: [], sources: [] },
  '/signals': { signals: [], evidence: [] },
};

describe('World tab — real WorldView connectivity + read data', () => {
  it('shows WorldView connected + recon read data even when the (unrelated) Signal Layer is down', async () => {
    mockFetch({
      '/provider-health/worldmonitor': 'FAIL',
      '/briefs/world': 'FAIL',
      '/signals': 'FAIL',
      '/api/worldview/overview': {
        connected: true,
        api_url: 'http://localhost:4000',
        recon: {
          status: 'ok',
          upcoming_windows: [
            { norad_id: 40115, aoi_id: 'hormuz', sensor_type: 'sar', t_ingress: 1789000000 },
            { norad_id: 40115, aoi_id: 'hormuz', sensor_type: 'sar', t_ingress: 1789007200 },
          ],
          due_alerts: [{ norad_id: 40115, aoi_id: 'hormuz', t_ingress: 1789000000 }],
        },
      },
    });
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('SIGNAL LAYER UNAVAILABLE')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('connected')).toBeTruthy());
    expect(screen.getByText('2 recon windows · 1 due alert')).toBeTruthy();
    expect(screen.getAllByText(/sat 40115 · sar over hormuz @/).length).toBe(2);
  });

  it('degrades to "not connected" + a quickstart hint (never fabricates) when the overview fetch fails', async () => {
    mockFetch({
      ...SIGNAL_LAYER_UP,
      // '/api/worldview/overview' deliberately absent -> 404 -> apiGet throws -> catch branch
    });
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('not connected')).toBeTruthy());
    expect(screen.getByText(/quickstart\.sh/)).toBeTruthy();
    expect(screen.queryByText(/recon window/)).toBeNull();
  });

  it('is honest when connected but recon data is unavailable', async () => {
    mockFetch({
      ...SIGNAL_LAYER_UP,
      '/api/worldview/overview': {
        connected: true,
        api_url: 'http://localhost:4000',
        recon: { status: 'unavailable', error: 'recon' },
      },
    });
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('connected · no recon data')).toBeTruthy());
    expect(screen.queryByText(/due alert/)).toBeNull();
  });
});
