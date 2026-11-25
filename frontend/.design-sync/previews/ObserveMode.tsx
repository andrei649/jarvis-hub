import React from 'react';
import { ObserveMode, V2 } from 'jarvis-hud-v2';

/* ObserveMode has one self-fetching piece: NorthStarMeter (GET
   /api/metrics/north-star?days=7), stubbed per story with full-URL keys (query strings
   matter). OfflineDegrade stubs nothing: north-star renders "unavailable" + em-dashes. */
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

const LIVE: Record<string, unknown> = {
  '/api/metrics/north-star?days=7': {
    days: 7,
    north_star: { accepted_per_active_user: 23, total_accepted: 23, active_users: 1 },
    counter_metrics: { interrupt_rate_per_day: 2.1, reject_rate: 0.08, local_pct: 87, p95_latency_ms: 7800 },
    night_shift: { done: 9, pct: 0.39, window: [0, 6] },
    proposal_funnel: { proposed: 41, surfaced: 31, accepted: 23, rejected: 3, pending: 5, surface_rate: 0.76, accept_rate: 0.74 },
    interrupt_budget: { per_day: 4, remaining: 2 },
    raw: { decisions: 41 },
  },
};

stubFetch({ LiveNorthStar: LIVE, OfflineDegrade: {} }, 'LiveNorthStar');

const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.6 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1400, height: 1040, display: 'flex' };
/* Capture viewport (900px) < the 1300px breakpoint that collapses .obs-grid to one
   column (styles.css:493) — scoped re-assert of the desktop base rule so the two-column
   composition is photographed. Config-level fix needs viewport ≥1301px wide (recorded
   in learnings/wave2-modes2.md; 1280x720 is NOT sufficient for the modes). */
const Wide = () => <style>{'.w2wide .obs-grid{grid-template-columns:1fr 1fr;gap:var(--gap) 28px}'}</style>;

/** North-star meter live from /api/metrics/north-star — 23 accepted/wk, interrupts inside the ≤4/day budget, night-shift + funnel filled. */
export function LiveNorthStar() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><ObserveMode t={T} /></div>
    </div>
  );
}

/** Everything unreachable — north-star "unavailable" with honest em-dashes. */
export function OfflineDegrade() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><ObserveMode t={T} /></div>
    </div>
  );
}
