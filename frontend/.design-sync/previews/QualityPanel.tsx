import React from 'react';
import { QualityPanel } from 'jarvis-hud-v2';

/* QualityPanel self-fetches GET /api/quality (open) on mount — the answer-quality gate
   with the admin set-threshold control. The alerting story flips the red ALERTING tag;
   offline leaves the path unstubbed for the real 404 degrade row. */
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
  Healthy: {
    '/api/quality': { stats: { avg_score: 0.87, n: 412, alerting: false, threshold: 0.6 } },
  },
  Alerting: {
    '/api/quality': { stats: { avg_score: 0.52, n: 38, alerting: true, threshold: 0.6 } },
  },
  Offline: {},
}, 'Healthy');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Gate healthy — avg 0.87 across 412 scored answers, green ok tag against the 0.60 threshold. */
export function Healthy() {
  return <div className="hud-root" style={wrap}><QualityPanel /></div>;
}

/** Quality dipped below the gate — red ALERTING tag, avg 0.52 vs the 0.60 threshold. */
export function Alerting() {
  return <div className="hud-root" style={wrap}><QualityPanel /></div>;
}

/** Backend unreachable — amber offline row; the set-threshold control stays offered. */
export function Offline() {
  return <div className="hud-root" style={wrap}><QualityPanel /></div>;
}
