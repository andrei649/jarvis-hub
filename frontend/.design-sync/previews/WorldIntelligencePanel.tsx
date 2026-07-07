import React from 'react';
import { WorldIntelligencePanel } from 'jarvis-hud-v2';

/* WorldIntelligencePanel self-fetches the external Signal Layer
   (http://localhost:8787) via loadWorldIntelligence(): GET /healthz,
   /briefs/world and /signals?limit=8&relevantOnly=true, each individually
   degradable (Promise.allSettled). The shim matches on pathname so the
   cross-origin :8787 URLs are served per story:
   - LiveSignals    — all three healthy, ranked signals + evidence pills.
   - ReplayPartial  — health+brief ok (replay, stale freshness) but /signals
     unreachable → the PARTIAL notice + brief.topSignals fallback (both real
     designed states; the /signals failure is a REAL network error, unstubbed).
   - LayerDown      — nothing stubbed → the full SignalLayerDown guidance row.
   Stage: the WorldIntelligenceMode panel chrome (1:1 from source). obs-grid
   collapses to one column under the 1300px media query — the capture viewport
   is 900px, so the stage scope-asserts the two-column desktop rule; suggested
   cfg override recorded in learnings/wave2-misc.md. */
const EVIDENCE = [
  { id: 'ev-1', sourceFamily: 'gdelt', sourceName: 'GDELT event stream', reliability: 'high', stale: false },
  { id: 'ev-2', sourceFamily: 'rss', sourceName: 'Reuters energy wire', reliability: 'high', stale: false },
  { id: 'ev-3', sourceFamily: 'marketdata', sourceName: 'ECB FX reference', reliability: 'medium', stale: true },
];
/* Copy kept tight on purpose: the capture viewport is 680px tall and each
   trace-row costs ~100px — LiveSignals serves 2 signals (3 clipped the last
   pills row); the fx signal still appears via ReplayPartial's cached pair. */
const SIGNALS = [
  { id: 'sig-1', type: 'shipping', title: 'Black Sea war-risk premiums jump 18%', severity: 'high', confidence: 'high', summary: 'Constanța-bound routes repriced overnight.', claimStatus: 'corroborated', relevance: { score: 0.91, reasons: ['Constanța exposure on your watchlist'] }, evidenceIds: ['ev-1', 'ev-2'] },
  { id: 'sig-2', type: 'cyber', title: 'Phishing wave hits EU fintech payroll', severity: 'elevated', confidence: 'medium', summary: 'Kit reuse across three campaigns; CERT-RO pending.', claimStatus: 'developing', relevance: { score: 0.62, reasons: ['Digitaholic payroll runs Thursday'] }, evidenceIds: ['ev-1'] },
  { id: 'sig-3', type: 'fx', title: 'RON holds the 4.97 band on risk-off', severity: 'low', confidence: 'high', summary: 'BNR seen smoothing; implied vols stable.', claimStatus: 'corroborated', relevance: { score: 0.68, reasons: ['Gecko watches EUR/RON 4.90–5.02'] }, evidenceIds: ['ev-3'] },
];
const BRIEF_LIVE = {
  title: 'Global Intelligence Brief — Mon 06:00 EEST',
  executiveSummary: 'Elevated but stable: Black Sea repricing touches your exposure; one cyber campaign merits a payroll heads-up.',
  globalStatus: 'ELEVATED',
  provider: 'worldmonitor',
  freshness: { stale: false },
  recommendations: [
    { label: 'Re-check Constanța freight exposure', requiresApproval: true },
    { label: 'Note TTF move in the energy model', requiresApproval: false },
    { label: 'Warn Digitaholic ops re: phishing', requiresApproval: true },
  ],
  topSignals: [],
};
const STORIES: Record<string, Record<string, unknown>> = {
  LiveSignals: {
    '/healthz': { ok: true, mode: 'live', provider: { provider: 'worldmonitor', status: 'connected', mode: 'live' } },
    '/briefs/world': BRIEF_LIVE,
    '/signals': { signals: SIGNALS.slice(0, 2), evidence: EVIDENCE },
  },
  ReplayPartial: {
    '/healthz': { ok: true, mode: 'replay', provider: { provider: 'worldmonitor', status: 'replay cache', mode: 'replay' } },
    '/briefs/world': {
      ...BRIEF_LIVE,
      title: 'Global Intelligence Brief — replay cache',
      executiveSummary: 'Replaying Sunday’s cached brief; the live signal feed is unreachable.',
      globalStatus: 'GUARDED',
      freshness: { stale: true },
      topSignals: [SIGNALS[0], SIGNALS[2]].map((s) => ({ ...s, claimStatus: 'cached' })),
    },
    // /signals intentionally unstubbed → real network failure → PARTIAL notice
  },
  LayerDown: {}, // nothing stubbed — full Signal Layer down guidance state
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.LiveSignals;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 840 };

function Stage({ children }: { children?: any }) {
  return (
    <div className="hud-root wi-two-col" style={frame}>
      <style>{'.wi-two-col .obs-grid{grid-template-columns:1fr 1fr;}'}</style>
      <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><span className="ttl">World Intelligence</span><span className="st">Signal Layer · Argus</span></div>
        <div className="panel-body">{children}</div>
      </div>
    </div>
  );
}

/** Live provider — four ranked signals with severity/claim pills, evidence freshness, gated recommendations. */
export function LiveSignals() {
  return <Stage><WorldIntelligencePanel /></Stage>;
}

/** Replay cache with the signal feed down — PARTIAL notice, stale-freshness pill, topSignals fallback. */
export function ReplayPartial() {
  return <Stage><WorldIntelligencePanel /></Stage>;
}

/** Signal Layer fully unreachable — OFF stat, start/port guidance row, empty-state caps. */
export function LayerDown() {
  return <Stage><WorldIntelligencePanel /></Stage>;
}
