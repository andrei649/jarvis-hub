// @ts-nocheck
/* H23.21 — the Console FeedbackPanel reads the NPS summary (GET /api/feedback/summary,
   admin) and offers a submit form (POST /api/feedback). fetch is mocked, like
   network-monitor.test.tsx — asserts the wiring + the NPS display + the submit control. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { FeedbackPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('FeedbackPanel (H23.21) — NPS summary + submit', () => {
  it('GETs /api/feedback/summary and shows NPS, promoters/detractors, a recent item, and the submit form', async () => {
    const fn = mockFetch({
      nps: 33, promoters: 2, detractors: 1, by_kind: { nps: 3, comment: 1, bug: 0 },
      recent: [{ kind: 'nps', score: 9, message: 'love it' }],
    });
    render(<FeedbackPanel />);
    await waitFor(() => expect(screen.getByText('NPS 33')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/feedback/summary'))).toBe(true);
    expect(screen.getByText('2 prom')).toBeTruthy();
    expect(screen.getByText('1 detr')).toBeTruthy();
    expect(screen.getByText('love it')).toBeTruthy();
    expect(screen.getByText('send')).toBeTruthy();   // the submit control is present
  });

  it('renders cleanly when there are no scores yet', async () => {
    mockFetch({ nps: null, promoters: 0, detractors: 0, by_kind: {}, recent: [] });
    render(<FeedbackPanel />);
    await waitFor(() => expect(screen.getByText('no scores')).toBeTruthy());
  });
});
