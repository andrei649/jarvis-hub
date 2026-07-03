// @ts-nocheck
/* 0.39 — the Console WatchlistPanel reads/writes the curated market watchlist
   (GET/POST/DELETE /api/market/watchlist/saved, user-guarded). fetch is mocked
   (route-keyed, like gap-panels.test.tsx). Asserts the read wiring, the add form
   POSTs {symbol,low,high,note}, and remove DELETEs by symbol. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WatchlistPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('WatchlistPanel — the curated market watchlist is live', () => {
  it('GETs /api/market/watchlist/saved and renders watches + band stats', async () => {
    const fn = mockFetch({
      '/api/market/watchlist/saved': {
        watches: [{ symbol: 'AAPL', low: 150, high: 200, note: 'earnings watch' }],
        stats: { total: 1, with_low: 1, with_high: 1 },
      },
    });
    render(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText('AAPL')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/market/watchlist/saved') && (!c[1] || c[1].method === undefined || c[1].method === 'GET'))).toBe(true);
    expect(screen.getByText('1 watched')).toBeTruthy();
    expect(screen.getByText('150–200')).toBeTruthy();
    expect(screen.getByText('LIVE')).toBeTruthy(); // TASK-2 tail: per-panel honesty chip — always-on store, no enabled flag
  });

  it('shows the empty state with no watches', async () => {
    mockFetch({ '/api/market/watchlist/saved': { watches: [], stats: { total: 0, with_low: 0, with_high: 0 } } });
    render(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText('nothing yet')).toBeTruthy());
  });

  it('POSTs {symbol,low,high,note} to add a watch and reloads', async () => {
    const fn = mockFetch({ '/api/market/watchlist/saved': { watches: [], stats: { total: 0, with_low: 0, with_high: 0 } } });
    render(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText('nothing yet')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('symbol'), { target: { value: 'msft' } });
    fireEvent.change(screen.getByPlaceholderText('low'), { target: { value: '50' } });
    fireEvent.change(screen.getByPlaceholderText('high'), { target: { value: '80' } });
    fireEvent.change(screen.getByPlaceholderText('note (optional)'), { target: { value: 'watch dip' } });
    fireEvent.click(screen.getByText('watch'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/market/watchlist/saved') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ symbol: 'msft', low: 50, high: 80, note: 'watch dip' });
    });
  });

  it('DELETEs /api/market/watchlist/saved/{symbol} on remove', async () => {
    const fn = mockFetch({
      '/api/market/watchlist/saved': {
        watches: [{ symbol: 'TSLA', low: null, high: null, note: '' }],
        stats: { total: 1, with_low: 0, with_high: 0 },
      },
    });
    render(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText('TSLA')).toBeTruthy());
    fireEvent.click(screen.getByTitle('remove'));
    await waitFor(() => {
      const del = fn.mock.calls.find((c) => String(c[0]).includes('/api/market/watchlist/saved/TSLA') && c[1]?.method === 'DELETE');
      expect(del).toBeTruthy();
    });
  });
});
