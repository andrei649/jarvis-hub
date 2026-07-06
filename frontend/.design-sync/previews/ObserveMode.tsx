import React from 'react';
import { ObserveMode, V2 } from 'jarvis-hud-v2';

/* ObserveMode composes two self-fetching pieces: NorthStarMeter (GET
   /api/metrics/north-star?days=7) and WorldIntelligencePanel (absolute-URL fetches to
   the signal layer at http://localhost:8787/{healthz,briefs/world,signals…}). Both are
   stubbed per story with full-URL keys (query strings matter). OfflineDegrade stubs
   nothing: north-star renders "unavailable" + em-dashes, the signal layer renders its
   designed amber "Signal Layer unavailable" setup row. */
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

const SL = 'http://localhost:8787';
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
  [SL + '/healthz']: { ok: true, mode: 'replay', provider: { provider: 'worldmonitor', status: 'ok', mode: 'replay' } },
  [SL + '/briefs/world']: {
    title: 'Global Intelligence Brief — Mon 06:00',
    executiveSummary: 'Quiet weekend globally. ECB held rates — EUR/RON sits mid-band at 4.97, no FX action needed. One high-severity npm supply-chain advisory overlaps a transitive dependency in the jarvis-hub build; a version bump is queued for Steve.',
    globalStatus: 'stable',
    provider: 'worldmonitor',
    freshness: { stale: false },
    recommendations: [
      { label: 'Bump the pinned npm dependency flagged by the CISA advisory', requiresApproval: true },
      { label: 'No FX action — EUR/RON well inside the 4.92–5.02 band', requiresApproval: false },
    ],
  },
  [SL + '/signals?limit=8&relevantOnly=true']: {
    signals: [
      { id: 'sg-1', type: 'cyber', title: 'npm supply-chain advisory — transitive dep in jarvis-hub build', severity: 'high', confidence: '0.87', summary: 'Compromised maintainer account; the affected version range overlaps one transitive dependency in the build pipeline.', claimStatus: 'corroborated', relevance: { score: 81, reasons: ['jarvis-hub dependency graph'] }, evidenceIds: ['ev-1'] },
      { id: 'sg-2', type: 'markets', title: 'ECB holds — RON stable, watch band intact', severity: 'low', confidence: '0.82', summary: 'Rates unchanged; EUR/RON 4.97 sits mid-band, so Gecko’s sweep proposal is unaffected.', claimStatus: 'reported', relevance: { score: 62, reasons: ['EUR/RON 4.92–5.02 watch'] }, evidenceIds: ['ev-2'] },
    ],
    evidence: [
      { id: 'ev-1', sourceFamily: 'cisa', stale: false },
      { id: 'ev-2', sourceFamily: 'reuters', stale: false },
    ],
  },
};

stubFetch({ LiveNorthStar: LIVE, WorldBrief: LIVE, OfflineDegrade: {} }, 'LiveNorthStar');

/* The mode is one tall scrolling panel (taller than any honest zoom allows in 900×680).
   WorldBrief photographs its middle section by scrolling the REAL panel body to the
   WORLD INTELLIGENCE sub-head after the stubbed fetches settle (wave-1 real-DOM-event
   staging — scroll the component, never excerpt its markup). */
function ScrollToSubH({ text }: { text: string }) {
  React.useEffect(() => {
    let tries = 0;
    const id = window.setInterval(() => {
      tries++;
      const el = Array.from(document.querySelectorAll('.sub-h')).find(e => (e.textContent || '').includes(text));
      if (el && tries > 2) { el.scrollIntoView({ block: 'start' }); window.clearInterval(id); }
      else if (tries > 25) window.clearInterval(id);
    }, 120);
    return () => window.clearInterval(id);
  }, [text]);
  return null;
}

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

/** Scrolled to the Signal Layer section — global brief, two relevant signals with evidence pills, approval-gated recommendations, provider health. */
export function WorldBrief() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <ScrollToSubH text="WORLD INTELLIGENCE" />
      <div style={stage}><ObserveMode t={T} /></div>
    </div>
  );
}

/** Everything unreachable — north-star "unavailable" with honest em-dashes and the amber Signal Layer setup row (START.bat / replay guidance). */
export function OfflineDegrade() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><ObserveMode t={T} /></div>
    </div>
  );
}
