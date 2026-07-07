import React from 'react';
import { LoopBreakerPanel } from 'jarvis-hud-v2';

/* LoopBreakerPanel is a live-dashboard panel: zero props, fetches
   GET /api/security/loop-breaker on mount. Each story serves its own backend
   payload through a scoped fetch shim keyed off the card's ?story= param, so
   the REAL exported panel renders real data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  Closed: {
    '/api/security/loop-breaker': { tripped: false, max_repeats: 6, window_seconds: 120 },
  },
  Tripped: {
    '/api/security/loop-breaker': { tripped: true, max_repeats: 6, window_seconds: 120 },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Closed;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Normal operation — breaker closed, showing the repeats/window trip threshold. */
export function Closed() {
  return <div className="hud-root" style={frame}><LoopBreakerPanel /></div>;
}

/** A runaway agent loop was halted — breaker open, admin reset offered. */
export function Tripped() {
  return <div className="hud-root" style={frame}><LoopBreakerPanel /></div>;
}
