import React from 'react';
import { ConsoleOverlay } from 'jarvis-hud-v2';

/* ConsoleOverlay is the full-screen console scrim hosting every gap.tsx panel (each
   self-fetching its own endpoint on mount — "live + mock-tolerant" by design). The
   preview stubs the endpoints of the above-the-fold sections (Memory + top of Trust)
   so the visible console is alive; everything below the fold degrades to each panel's
   own offline state, which is the surface's documented behavior. The scrim is
   position:fixed, so the card's transformed story wrapper contains it — the tall
   hud-root wrapper reserves the stage. Esc/close is a no-op callback. */
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

const LIVE_ROUTES: Record<string, unknown> = {
  // ── Memory section (above the fold) ──
  '/api/memory/spaces': {
    spaces: [
      { name: 'personal', sources: ['gmail', 'calendar', 'notes'] },
      { name: 'finance', sources: ['invoices', 'bank-export', 'market'] },
      { name: 'ops', sources: ['n8n', 'homebridge'] },
    ],
    assignments: { gecko: ['finance'], frigga: ['personal'] },
  },
  '/api/local-docs': { folders: [{ key: '~/Documents/notes' }, { key: '~/Documents/manuals' }, { key: '~/Projects/jarvis-hub/docs' }], indexed: 132 },
  '/api/notes': { content: '- Frigga: dentist Thursday 09:30\n- Steve: flash new HUD build to wall display\n- hold LinkedIn post until Ultron clears the client name' },
  '/api/kg/entities': {
    entities: [
      { name: 'Q3 roadmap', type: 'project', mentions: 14 },
      { name: 'Meridian Ltd', type: 'org', mentions: 9 },
      { name: 'Veronica draft', type: 'artifact', mentions: 6 },
      { name: 'wall display', type: 'device', mentions: 4 },
    ],
  },
  '/api/capture/status': { enabled: true },
  '/api/capture': {
    records: [
      { id: 'cap-91', preview: 'clipboard · "Q3 roadmap sync — action items for ▓▓▓▓▓"', surface: 'clipboard' },
      { id: 'cap-90', preview: 'screen · Figma — HUD v2 console overlay (title only)', surface: 'screen' },
      { id: 'cap-89', preview: 'mic · 14s ambient — transcript redacted (2 names)', surface: 'mic' },
    ],
  },
  '/api/reflection/status': { enabled: true, last_run: '2024-05-15 03:10' },
  '/api/ingestion/provenance': {
    enabled: true,
    stats: { total: 128, runs: 12, by_source: { gmail: 64, telegram: 41, web: 23 } },
    records: [
      { id: 'p1', source: 'gmail', phase: 'ingest', content_hash: '9f31c2ab55d0' },
      { id: 'p2', source: 'telegram', phase: 'chunk', content_hash: 'b04e77d19c22' },
      { id: 'p3', source: 'web', phase: 'embed', content_hash: '4cd2a9ee0187' },
    ],
  },
  // ── Trust section (fold boundary) ──
  '/api/security/kill-switch': { halted: false },
  '/api/metrics/kernel': {
    total: 412, by_verdict: { grant: 361, queue: 44, deny: 7 },
    recent_denials: [
      { kind: 'social.post', reason: 'client name flagged sensitive' },
      { kind: 'fs.delete', reason: 'outside sandbox root' },
    ],
  },
  '/api/metrics/capabilities': {
    total: 24, by_state: { seam: 6, wired: 9, verified: 7, ga: 2 }, harness_pending: true,
    capabilities: [
      { id: 'mail.send', state: 'verified' },
      { id: 'calendar.write', state: 'wired' },
      { id: 'market.watch', state: 'ga' },
    ],
  },
  '/api/security/loop-breaker': { tripped: false, max_repeats: 6, window_seconds: 120 },
  '/api/security/governance': {
    pass: true, overall_score: 0.93, threshold: 0.85,
    injection: { score: 0.96, passed: 48, n: 50 },
    harm: { score: 0.94, passed: 47, n: 50 },
    owasp: { score: 0.9, passed: 27, n: 30 },
  },
};

stubFetch({
  OpenConsole: LIVE_ROUTES,
  // OfflineDegraded: no routes — every panel exercises its own offline/empty degrade.
  OfflineDegraded: {},
}, 'OpenConsole');

const stage: React.CSSProperties = {
  background: 'var(--void,#04070e)', borderRadius: 8, padding: 16,
  width: '100%', minWidth: 820, height: 620, position: 'relative', overflow: 'hidden',
};

/** The console open over the HUD — Memory section live, sections columned, esc to close. */
export function OpenConsole() {
  return <div className="hud-root" style={stage}><ConsoleOverlay onClose={() => {}} /></div>;
}

/** Backend gone — every panel degrades to its own offline/empty state, never blocking. */
export function OfflineDegraded() {
  return <div className="hud-root" style={stage}><ConsoleOverlay onClose={() => {}} /></div>;
}
