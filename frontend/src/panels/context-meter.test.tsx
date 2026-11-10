// @ts-nocheck
/* CONTEXT METER panel (H412) — `fetch` is mocked so the real api client runs.
   Pins: the meter reads GET /sessions/{id}/context for the newest session; the bar's
   segments are the categories the hub answered (they add up to `used`); the compaction
   tier is the hub's own word; with no session the panel calls nothing and says so. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ContextMeterPanel } from './context-meter';

const METER = {
  session_id: 's-1', model: 'qwen2.5', window: 32000, used: 9000, free: 23000, percent: 28.1,
  categories: [
    { name: 'system', tokens: 2000, share: 0.0625 },
    { name: 'tools', tokens: 3000, share: 0.0938 },
    { name: 'skills', tokens: 500, share: 0.0156 },
    { name: 'memory', tokens: 500, share: 0.0156 },
    { name: 'history', tokens: 2500, share: 0.0781, turns: 12 },
    { name: 'attachments', tokens: 500, share: 0.0156, images: 0, attached_blocks: 1 },
  ],
  thresholds: { soft: 19200, hard: 27200, soft_ratio: 0.6, hard_ratio: 0.85 },
  compaction_tier: 'none', grid: [], measured: 8800, estimated: true, note: 'Estimates.',
};

function mockRoutes(map) {
  const fn = vi.fn(async (url) => {
    const res = map[String(url)];
    if (!res) throw new Error('unexpected fetch ' + url);
    return { ok: true, status: 200, json: async () => res };
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => { vi.restoreAllMocks(); });

describe('ContextMeterPanel', () => {
  it("reads the newest session's meter and draws every category", async () => {
    const fn = mockRoutes({ '/sessions': { sessions: [{ session_id: 's-1' }] }, '/sessions/s-1/context': METER });
    render(<ContextMeterPanel />);
    await waitFor(() => expect(screen.getByText(/9,000 of 32,000 tokens/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/sessions/s-1/context')).toBe(true);
    const segments = Array.from(document.querySelectorAll('[data-cat]'));
    expect(segments.map((s) => s.getAttribute('data-cat'))).toEqual(
      ['system', 'tools', 'skills', 'memory', 'history', 'attachments']);
    const total = METER.categories.reduce((n, c) => n + c.tokens, 0);
    expect(total).toBe(METER.used);
    expect(screen.getByTestId('tier').textContent).toMatch(/none/);
    expect(screen.getByText(/measured the last request at 8,800/)).toBeTruthy();
  });

  it('with no conversation calls no meter and says so', async () => {
    const fn = mockRoutes({ '/sessions': { sessions: [] } });
    render(<ContextMeterPanel />);
    await waitFor(() => expect(screen.getByText('No conversation to measure yet.')).toBeTruthy());
    expect(fn.mock.calls.every((c) => !String(c[0]).includes('/context'))).toBe(true);
  });
});
