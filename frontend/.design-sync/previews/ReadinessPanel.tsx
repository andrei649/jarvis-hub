import React from 'react';
import { ReadinessPanel } from 'jarvis-hud-v2';

/* ReadinessPanel self-fetches GET /api/metrics/capabilities on mount — the Verification
   Fabric board (SEAM→WIRED→VERIFIED→GA ladder). The harness-pending story exercises the
   honesty banner ("wired, not yet proven"); offline is the real 404 degrade row. */
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
  MixedLadder: {
    '/api/metrics/capabilities': {
      total: 18,
      by_state: { seam: 4, wired: 9, verified: 4, ga: 1 },
      harness_pending: false,
      capabilities: [
        { id: 'channels.telegram', state: 'ga' },
        { id: 'memory.kg', state: 'verified' },
        { id: 'sandbox.docker', state: 'verified' },
        { id: 'skills.signing', state: 'verified' },
        { id: 'oracle.sync', state: 'wired' },
        { id: 'a2a.mesh', state: 'wired' },
        { id: 'market.watchlist', state: 'wired' },
        { id: 'media.catalog', state: 'seam' },
      ],
    },
  },
  HarnessPending: {
    '/api/metrics/capabilities': {
      total: 18,
      by_state: { seam: 6, wired: 12, verified: 0, ga: 0 },
      harness_pending: true,
      capabilities: [
        { id: 'channels.telegram', state: 'wired' },
        { id: 'memory.kg', state: 'wired' },
        { id: 'sandbox.docker', state: 'wired' },
        { id: 'a2a.mesh', state: 'wired' },
        { id: 'satellites.pairing', state: 'seam' },
        { id: 'media.catalog', state: 'seam' },
      ],
    },
  },
  Offline: {},
}, 'MixedLadder');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Mature fabric — 18 capabilities spread across the whole ladder, telegram at GA. */
export function MixedLadder() {
  return <div className="hud-root" style={wrap}><ReadinessPanel /></div>;
}

/** Fresh wiring, no green harness yet — the amber "wired, not yet proven" honesty banner. */
export function HarnessPending() {
  return <div className="hud-root" style={wrap}><ReadinessPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><ReadinessPanel /></div>;
}
