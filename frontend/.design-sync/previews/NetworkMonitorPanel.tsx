import React from 'react';
import { NetworkMonitorPanel } from 'jarvis-hud-v2';

/* NetworkMonitorPanel is a live-dashboard panel: zero props, fetches the
   admin-guarded GET /api/admin/network/calls on mount. Each story serves its
   own backend payload through a scoped fetch shim keyed off the card's ?story=
   param, so the REAL exported panel renders real data end-to-end — nothing is
   hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  AllLocal: {
    '/api/admin/network/calls': {
      clean: true,
      external_egress_total: 0,
      local_only_violations: [],
      plugins: {
        'whatsapp-bridge': { allowed: 12, external: 0, blocked: 0 },
        'apple-health': { allowed: 9, external: 0, blocked: 0 },
        homebridge: { allowed: 5, external: 0, blocked: 0 },
      },
    },
  },
  RoutineEgress: {
    '/api/admin/network/calls': {
      clean: true,
      external_egress_total: 12,
      local_only_violations: [],
      plugins: {
        'google-calendar': { allowed: 44, external: 8, blocked: 0 },
        gmail: { allowed: 31, external: 4, blocked: 0 },
        'telegram-bot': { allowed: 26, external: 0, blocked: 0 },
        'whatsapp-bridge': { allowed: 12, external: 0, blocked: 0 },
      },
    },
  },
  Violation: {
    '/api/admin/network/calls': {
      clean: false,
      external_egress_total: 3,
      local_only_violations: ['whatsapp-bridge'],
      plugins: {
        'whatsapp-bridge': { allowed: 12, external: 2, blocked: 1 },
        gmail: { allowed: 31, external: 1, blocked: 0 },
        'apple-health': { allowed: 9, external: 0, blocked: 0 },
      },
    },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.AllLocal;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 400 };

/** The LOCAL_ONLY proof — zero external egress across every bridge plugin. */
export function AllLocal() {
  return <div className="hud-root" style={frame}><NetworkMonitorPanel /></div>;
}

/** Normal mixed day — cloud plugins make allowed external calls, ledger still clean. */
export function RoutineEgress() {
  return <div className="hud-root" style={frame}><NetworkMonitorPanel /></div>;
}

/** A local-only plugin egressed — headline flips red with the violating plugin named. */
export function Violation() {
  return <div className="hud-root" style={frame}><NetworkMonitorPanel /></div>;
}
