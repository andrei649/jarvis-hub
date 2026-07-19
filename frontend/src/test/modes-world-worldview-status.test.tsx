// @ts-nocheck
/* The World tab's WorldView surface row used to be a dead <a> link with no signal
   of whether the standalone WorldView backend (:4000) was actually running. It now
   polls our own GET /api/worldview/status and renders a real connected/not-connected
   badge — independent of the (unrelated) Signal Layer service the rest of the tab
   depends on, so one being down must not hide the other's state. fetch is mocked,
   like network-monitor.test.tsx. */
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

describe('World tab — real WorldView connectivity badge', () => {
  it('shows WorldView connected even when the (unrelated) Signal Layer is down', async () => {
    mockFetch({
      '/provider-health/worldmonitor': 'FAIL',
      '/briefs/world': 'FAIL',
      '/signals': 'FAIL',
      '/api/worldview/status': { connected: true, api_url: 'http://localhost:4000' },
    });
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('SIGNAL LAYER UNAVAILABLE')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('connected')).toBeTruthy());
  });

  it('degrades to "not connected" (never fabricates) when the status fetch itself fails', async () => {
    mockFetch({
      '/provider-health/worldmonitor': { status: 'ok', provider: 'worldmonitor', mode: 'replay' },
      '/briefs/world': { title: 'Brief', executiveSummary: 'sum', globalStatus: 'NOMINAL', recommendations: [], sources: [] },
      '/signals': { signals: [], evidence: [] },
      // '/api/worldview/status' deliberately absent -> mockFetch 404s -> apiGet throws -> catch branch
    });
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('not connected')).toBeTruthy());
  });
});
