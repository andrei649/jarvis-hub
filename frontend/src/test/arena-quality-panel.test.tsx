// @ts-nocheck
/* HUD-v3 C8 — the Console Model Arena leaderboard + Answer Quality panels read the
   real observability endpoints (/api/arena/leaderboard · /api/quality) and the quality
   panel sets the alert threshold (POST /api/quality/threshold, admin). fetch is mocked,
   like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ArenaPanel, QualityPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('ArenaPanel — the model ELO leaderboard is live', () => {
  it('GETs /api/arena/leaderboard and ranks models with ELO + win-rate', async () => {
    const fn = mockFetch({ leaderboard: [
      { model: 'qwen2.5-coder', elo: 1240, wins: 8, losses: 2, games: 10, win_rate: 0.8 },
      { model: 'llama3.1', elo: 1110, wins: 4, losses: 6, games: 10, win_rate: 0.4 },
    ] });
    render(<ArenaPanel />);
    await waitFor(() => expect(screen.getByText('1. qwen2.5-coder')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/arena/leaderboard'))).toBe(true);
    expect(screen.getByText('1240 elo')).toBeTruthy();
    expect(screen.getByText('80%')).toBeTruthy();
    expect(screen.getByText('2. llama3.1')).toBeTruthy();
  });

  it('shows the honest empty-state when no matches have run', async () => {
    mockFetch({ leaderboard: [] });
    render(<ArenaPanel />);
    await waitFor(() => expect(screen.getByText(/no matches yet/)).toBeTruthy());
  });
});

describe('QualityPanel — the answer-quality gate is live', () => {
  it('GETs /api/quality and shows avg + threshold + alert state', async () => {
    const fn = mockFetch({ stats: { n: 42, avg_score: 0.81, threshold: 0.6, alerting: false } });
    render(<QualityPanel />);
    await waitFor(() => expect(screen.getByText('avg 0.81')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/quality'))).toBe(true);
    expect(screen.getByText('ok')).toBeTruthy();
    expect(screen.getByText('0.60')).toBeTruthy();
  });

  it('POSTs a new threshold via /api/quality/threshold', async () => {
    const fn = mockFetch({ stats: { n: 5, avg_score: 0.7, threshold: 0.5, alerting: false } });
    render(<QualityPanel />);
    await waitFor(() => expect(screen.getByText('set threshold')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('0.0–1.0'), { target: { value: '0.75' } });
    fireEvent.click(screen.getByText('set threshold'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/quality/threshold')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('0.75'))
    ).toBe(true));
  });
});
