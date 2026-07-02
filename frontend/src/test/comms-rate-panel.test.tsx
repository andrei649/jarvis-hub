// @ts-nocheck
/* 0.44 — the Console CommsRatePanel reads the per-channel outbound send rate-limiter
   status (GET /api/channels/send-rate-limit, admin) and renders configured caps + live
   usage. fetch is mocked (like provenance-panel.test.tsx). Asserts the wiring, channel
   rows, and the honesty banner when no cap is configured (limiter disabled / unlimited). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { CommsRatePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('CommsRatePanel — the send rate-limit status surface is live', () => {
  it('GETs /api/channels/send-rate-limit and renders per-channel usage', async () => {
    const fn = mockFetch({
      enabled: true,
      global_cap: 20,
      window_seconds: 60,
      channels: [
        { channel: 'whatsapp', cap: 3, used: 2, remaining: 1 },
        { channel: 'teams', cap: 0, used: 5, remaining: null },
      ],
    });
    render(<CommsRatePanel />);
    await waitFor(() => expect(screen.getByText('whatsapp')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/channels/send-rate-limit'))).toBe(true);
    expect(screen.getByText('2/3')).toBeTruthy();      // capped channel: used/cap
    expect(screen.getByText('5/∞')).toBeTruthy();       // unlimited channel: used/∞
    expect(screen.getByText('LIVE')).toBeTruthy();      // TASK-2 tail: per-panel honesty chip
  });

  it('shows the honesty banner when no cap is configured (limiter disabled)', async () => {
    mockFetch({ enabled: false, global_cap: 0, window_seconds: 60, channels: [] });
    render(<CommsRatePanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_CHANNEL_SEND_RATE/)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
  });
});
