// @ts-nocheck
/* P1 G1 — the Console TodayPanel reads the unified "Today in Jarvis" feed
   (GET /api/dashboard/today) and renders did/learned items newest-first with a
   "N did · M learned" summary. fetch is mocked, like onboarding-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { TodayPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('TodayPanel (P1 G1) — unified "Today in Jarvis" feed', () => {
  it('GETs the feed and renders did/learned items with the summary', async () => {
    const fn = mockFetch({
      period: 'today', days: 1,
      counts: { actions: 1, learnings: 1, total: 2 },
      items: [
        { ts: '2026-06-27T11:00:00+00:00', kind: 'learning', category: 'fact', key: 'city', value: 'Bucharest' },
        { ts: '2026-06-27T09:00:00+00:00', kind: 'action', title: 'synced calendar', id: 7, tier: 1 },
      ],
    });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText(/synced calendar/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/dashboard/today'))).toBe(true);
    expect(screen.getByText('1 did · 1 learned')).toBeTruthy();   // summary
    expect(screen.getByText(/city: Bucharest/)).toBeTruthy();      // learning rendered
    expect(screen.getByText('did')).toBeTruthy();                  // action tag
    expect(screen.getByText('learned')).toBeTruthy();              // learning tag
  });

  it('shows the empty state when nothing happened yet', async () => {
    mockFetch({ period: 'today', days: 1, counts: { actions: 0, learnings: 0, total: 0 }, items: [] });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText(/nothing yet/)).toBeTruthy());
  });
});
