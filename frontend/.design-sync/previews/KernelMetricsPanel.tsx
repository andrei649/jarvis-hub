import React from 'react';
import { KernelMetricsPanel } from 'jarvis-hud-v2';

/* KernelMetricsPanel is a live-dashboard panel: zero props, fetches
   GET /api/metrics/kernel on mount. Each story serves its own backend payload
   through a scoped fetch shim keyed off the card's ?story= param, so the REAL
   exported panel renders real data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  Enforcing: {
    '/api/metrics/kernel': {
      enabled: true,
      total: 412,
      by_verdict: { grant: 361, queue: 38, deny: 13 },
      recent_denials: [
        { kind: 'net.outbound', reason: 'SSRF attempt to 10.0.0.x from web-fetch' },
        { kind: 'shell.exec', reason: 'rm outside /work sandbox — no capability' },
        { kind: 'payments.execute', reason: '€4,200 sweep above tier-2 auto ceiling' },
      ],
    },
  },
  CleanDay: {
    '/api/metrics/kernel': {
      enabled: true,
      total: 57,
      by_verdict: { grant: 55, queue: 2, deny: 0 },
      recent_denials: [],
    },
  },
  Disabled: {
    '/api/metrics/kernel': { enabled: false, total: 0, by_verdict: {}, recent_denials: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Enforcing;
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

/** A working kernel — verdict split plus the recent denials it actually blocked. */
export function Enforcing() {
  return <div className="hud-root" style={frame}><KernelMetricsPanel /></div>;
}

/** Quiet day — everything granted or queued, zero denials. */
export function CleanDay() {
  return <div className="hud-root" style={frame}><KernelMetricsPanel /></div>;
}

/** JARVIS_ACTION_KERNEL off — SEED chip and the honest empty-until hint. */
export function Disabled() {
  return <div className="hud-root" style={frame}><KernelMetricsPanel /></div>;
}
