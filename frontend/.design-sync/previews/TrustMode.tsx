import React from 'react';
import { TrustMode, V2 } from 'jarvis-hud-v2';

/* TrustMode self-fetches GET /api/security/kill-switch + /api/security/audit/verify on
   mount (modes.tsx) — the preview drives the REAL component through a module-scoped
   fetch stub keyed off the harness's ?story= param. Offline stubs nothing: the real
   404s exercise the designed "audit unavailable" / "kill-switch unavailable" degrade. */
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
  VerifiedLocal: {
    '/api/security/kill-switch': { halted: false },
    '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 1284 },
  },
  TamperHalted: {
    '/api/security/kill-switch': { halted: true },
    '/api/security/audit/verify': { valid: false, first_invalid_id: 412, entries: 1284 },
  },
  Offline: {},
}, 'VerifiedLocal');

/* live.ts attaches broker ids to PAYMENTS rows when /api/payments is live; TrustMode
   only renders lifecycle controls (approve ✓ / reject ✕) on rows carrying a real id.
   Emulate live.ts for the live story so the governed-payment path is photographed. */
if (STORY === 'VerifiedLocal' || STORY === '') {
  (V2.PAYMENTS as any[]).forEach((p, i) => { p.id = 'pay-b' + i; });
}

const T = V2.I18N.en;
/* Full-screen mode: definite-height flex stage (panel is flex:1) + zoom on the hud-root
   to fit the desktop composition into the 900×680 capture. .trust-grid has no responsive
   breakpoint, so no viewport fix is needed here. */
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.58 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1360, height: 1080, display: 'flex' };

/** Chain Merkle-verified live (1284 sealed entries), kill-switch armed, 100% local compute, pending €4.2k sweep with live approve/reject. */
export function VerifiedLocal() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}><TrustMode t={T} localPct={100} /></div>
    </div>
  );
}

/** Tamper detected — chain broken at row #412 (red header + red chain row) and the kill-switch ENGAGED: all agents halted. */
export function TamperHalted() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}><TrustMode t={T} /></div>
    </div>
  );
}

/** Backend unreachable — the honest degrade: "audit unavailable", static verified copy, "kill-switch unavailable" under the STOP control. */
export function Offline() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}><TrustMode t={T} /></div>
    </div>
  );
}
