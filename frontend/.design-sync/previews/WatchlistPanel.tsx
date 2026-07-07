import React from 'react';
import { WatchlistPanel } from 'jarvis-hud-v2';

/* WatchlistPanel is a live-dashboard panel: zero props, fetches the
   user-guarded GET /api/market/watchlist/saved on mount (0.39 — the curated
   {symbol, low, high, note} list the market alert/brief evaluators run
   against). Each story serves its own backend payload through a scoped fetch
   shim keyed off the card's ?story= param, so the REAL exported panel renders
   real data end-to-end. Offline has NO stub — the real 404 exercises the
   documented amber degrade row. */
const STORIES: Record<string, Record<string, unknown>> = {
  Curated: {
    '/api/market/watchlist/saved': {
      watches: [
        { symbol: 'EURRON', low: 4.9, high: 5.02, note: 'FX band — Gecko alerts' },
        { symbol: 'NVDA', low: 95, high: 140, note: 'trim above band' },
        { symbol: 'BTC', low: 52000, high: null, note: 'accumulate under' },
        { symbol: 'MSFT', low: null, high: 520, note: '' },
        { symbol: 'XAUUSD', low: 2280, high: 2450, note: 'hedge sleeve rebalance trigger' },
      ],
      stats: { total: 5, with_low: 4, with_high: 3 },
    },
  },
  Empty: {
    '/api/market/watchlist/saved': { watches: [], stats: { total: 0, with_low: 0, with_high: 0 } },
  },
  Offline: {}, // nothing stubbed — real 404 → designed amber "offline" degrade
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Curated;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

/* 460: the add row is four inputs (symbol/low/high/note) + the watch button —
   at 380 the tail wraps awkwardly under the note field. */
const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 460 };

/** Five curated watches — band tags (incl. open-ended −∞/+∞ sides), notes, stats row, per-symbol remove. */
export function Curated() {
  return <div className="hud-root" style={frame}><WatchlistPanel /></div>;
}

/** Nothing watched yet — "nothing yet" plus the symbol/low/high/note add flow. */
export function Empty() {
  return <div className="hud-root" style={frame}><WatchlistPanel /></div>;
}

/** Backend unreachable — the amber offline degrade row (real 404, unstubbed). */
export function Offline() {
  return <div className="hud-root" style={frame}><WatchlistPanel /></div>;
}
