import React from 'react';
import { ProvenancePanel } from 'jarvis-hud-v2';

/* ProvenancePanel self-fetches GET /api/ingestion/provenance (admin) on mount. The
   disabled story exercises the honesty contract (SEED chip + "empty until
   JARVIS_PROVENANCE is on"); offline leaves the path unstubbed for the real 404. */
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
  Recording: {
    '/api/ingestion/provenance': {
      enabled: true,
      stats: { total: 342, runs: 57, by_source: { telegram: 148, gmail: 96, capture: 61, rss: 37 } },
      records: [
        { id: 1, source: 'gmail', phase: 'ingest', content_hash: 'a3f8c1d92e4b7f01' },
        { id: 2, source: 'telegram', phase: 'normalize', content_hash: '5e02bb47c9d1a8e3' },
        { id: 3, source: 'gmail', phase: 'embed', content_hash: 'f14a90cd22e7b6a5' },
        { id: 4, source: 'rss', phase: 'ingest', content_hash: '7cd3e58f10b942aa' },
        { id: 5, source: 'capture', phase: 'normalize', content_hash: '0b96f2317dce54e8' },
        { id: 6, source: 'telegram', phase: 'embed', content_hash: 'c821d4a6f39e0b57' },
      ],
    },
  },
  Disabled: {
    '/api/ingestion/provenance': { enabled: false, records: [], stats: { total: 0, runs: 0, by_source: {} } },
  },
  Offline: {},
}, 'Recording');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Provenance on — 342 records over 57 runs, by-source tags + recent record hashes. */
export function Recording() {
  return <div className="hud-root" style={wrap}><ProvenancePanel /></div>;
}

/** JARVIS_PROVENANCE off (the default) — SEED chip, records carry conversation ids so nothing is kept. */
export function Disabled() {
  return <div className="hud-root" style={wrap}><ProvenancePanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><ProvenancePanel /></div>;
}
