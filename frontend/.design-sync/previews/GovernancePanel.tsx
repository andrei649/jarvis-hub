import React from 'react';
import { GovernancePanel } from 'jarvis-hud-v2';

/* GovernancePanel self-fetches GET /api/security/governance (public scorecard) on mount —
   the preview drives the REAL component through a module-scoped fetch stub keyed off the
   harness's ?story= param. */
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
  GatePassing: {
    '/api/security/governance': {
      pass: true, overall_score: 0.93, threshold: 0.85,
      injection: { score: 0.96, passed: 48, n: 50 },
      harm: { score: 0.94, passed: 47, n: 50 },
      owasp: { score: 0.9, passed: 27, n: 30 },
    },
  },
  GateFailing: {
    '/api/security/governance': {
      pass: false, overall_score: 0.71, threshold: 0.85,
      injection: { score: 0.82, passed: 41, n: 50 },
      harm: { score: 0.58, passed: 29, n: 50 },
      owasp: { score: 0.73, passed: 22, n: 30 },
    },
  },
  Offline: {},
}, 'GatePassing');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Suite green — overall 93% over an 85% gate, all three suites passing. */
export function GatePassing() {
  return <div className="hud-root" style={wrap}><GovernancePanel /></div>;
}

/** Gate FAIL — harm suite dragging the overall score under the threshold. */
export function GateFailing() {
  return <div className="hud-root" style={wrap}><GovernancePanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade path. */
export function Offline() {
  return <div className="hud-root" style={wrap}><GovernancePanel /></div>;
}
