import React from 'react';
import { DecisionInboxPanel } from 'jarvis-hud-v2';

/* DecisionInboxPanel self-fetches GET /autonomy/tasks?status=blocked + /autonomy/interrupts
   (admin) on mount — the preview drives the REAL component through a module-scoped fetch
   stub keyed off the harness's ?story= param. Note the tasks route is keyed with its
   query string (the stub matches full URL before pathname). */
const STORY = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
function stubFetch(routesByStory: Record<string, Record<string, unknown>>, fallback: string) {
  const routes = routesByStory[STORY] || routesByStory[fallback] || {};
  const real = window.fetch.bind(window);
  (window as any).fetch = (input: any, init?: any) => {
    const url = typeof input === 'string' ? input : ((input && (input as any).url) || '');
    const path = String(url).split('?')[0];
    const hit = Object.prototype.hasOwnProperty.call(routes, url) ? routes[url]
      : Object.prototype.hasOwnProperty.call(routes, path) ? routes[path] : undefined;
    if (hit === undefined) return real(input as any, init);
    return Promise.resolve(new Response(JSON.stringify(hit), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  };
}

stubFetch({
  BlockedDecisions: {
    '/autonomy/tasks?status=blocked': {
      tasks: [
        { id: 't-482', title: 'Send weekly investor digest (email · 3 recipients)', risk_tier: 2, payload: { channel: 'email', to: 3 } },
        { id: 't-479', title: 'Publish LinkedIn draft — client name redacted', risk_tier: 3, payload: { platform: 'linkedin' } },
        { id: 't-475', title: 'Prune 1.2GB stale embeddings cache', risk_tier: 1, payload: { path: 'store/embeddings' } },
      ],
    },
    '/autonomy/interrupts': { per_day: 6, used: 2 },
  },
  AllClear: {
    '/autonomy/tasks?status=blocked': { tasks: [] },
    '/autonomy/interrupts': { per_day: 6, used: 1 },
  },
  Offline: {},
}, 'BlockedDecisions');

/* 440: each blocked row carries a five-control action cluster (tier · preview ✓ edit ✕
   defer) — at 380 the trailing "defer" clips at the panel edge. */
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 440 };

/** Three blocked decisions with risk tiers and the interrupt budget in the header. */
export function BlockedDecisions() {
  return <div className="hud-root" style={wrap}><DecisionInboxPanel /></div>;
}

/** All clear — the green nothing-waiting state, budget barely touched. */
export function AllClear() {
  return <div className="hud-root" style={wrap}><DecisionInboxPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade path. */
export function Offline() {
  return <div className="hud-root" style={wrap}><DecisionInboxPanel /></div>;
}
