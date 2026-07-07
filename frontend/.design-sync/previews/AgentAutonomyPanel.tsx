import React from 'react';
import { AgentAutonomyPanel, V2 } from 'jarvis-hud-v2';

/* AgentAutonomyPanel self-fetches GET /autonomy/policy (admin) on mount — the preview
   drives the REAL component through a module-scoped fetch stub keyed off the harness's
   ?story= param. Agent ids come from the repo's own seed roster (V2.AGENTS). */
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

// Real agent ids from the seed roster — ultron (security), veronica (comms), gecko (markets).
const ids: string[] = ((V2 as any)?.AGENTS || []).map((a: any) => a.id);
const pick = (want: string, fb: string) => (ids.includes(want) ? want : fb);

stubFetch({
  PerAgentOverrides: {
    '/autonomy/policy': {
      global: 'ask',
      agents: {
        [pick('ultron', 'ultron')]: 'auto',
        [pick('veronica', 'veronica')]: 'off',
        [pick('gecko', 'gecko')]: 'ask',
      },
    },
  },
  NoOverrides: {
    '/autonomy/policy': { global: 'auto', agents: {} },
  },
  Offline: {},
}, 'PerAgentOverrides');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Global ASK with three per-agent dials — auto/ask/off color-coded, each clearable. */
export function PerAgentOverrides() {
  return <div className="hud-root" style={wrap}><AgentAutonomyPanel /></div>;
}

/** No overrides — every agent follows the global mode; the set-override form below. */
export function NoOverrides() {
  return <div className="hud-root" style={wrap}><AgentAutonomyPanel /></div>;
}

/** Backend unreachable — offline degrade with the override form still composed. */
export function Offline() {
  return <div className="hud-root" style={wrap}><AgentAutonomyPanel /></div>;
}
