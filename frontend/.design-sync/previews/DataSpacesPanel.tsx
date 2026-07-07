import React from 'react';
import { DataSpacesPanel } from 'jarvis-hud-v2';

/* DataSpacesPanel self-fetches GET /api/memory/spaces on mount (no data props) — the
   preview drives the REAL component through a module-scoped fetch stub keyed off the
   harness's ?story= param. Agent ids come from the repo's seed universe (V2.AGENTS). */
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

const SPACES = [
  { name: 'personal', sources: ['gmail', 'calendar', 'notes'] },
  { name: 'finance', sources: ['invoices', 'bank-export', 'market'] },
  { name: 'ops', sources: ['n8n', 'homebridge'] },
  { name: 'research', sources: ['web-clips', 'papers'] },
];

stubFetch({
  CuratedSpaces: {
    '/api/memory/spaces': { spaces: SPACES, assignments: {} },
  },
  AgentAssignments: {
    '/api/memory/spaces': {
      spaces: SPACES,
      assignments: { gecko: ['finance'], stark: ['finance', 'ops'], frigga: ['personal'] },
    },
  },
  FirstRun: {
    '/api/memory/spaces': { spaces: [], assignments: {} },
  },
}, 'AgentAssignments');

/* 480: the create row is non-wrapping flex with TWO default-min-width inputs plus the
   "+ add" button — it clips at 380 and 420 (it also clips in the product's own 320px
   console columns; component-level, noted in learnings). 480 is the narrowest stage
   where the full control set is visible. */
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 480 };

/** Four curated spaces with their source lists — no per-agent restrictions yet. */
export function CuratedSpaces() {
  return <div className="hud-root" style={wrap}><DataSpacesPanel /></div>;
}

/** Spaces plus ASSIGNMENTS rows — per-agent read scope with unassign controls. */
export function AgentAssignments() {
  return <div className="hud-root" style={wrap}><DataSpacesPanel /></div>;
}

/** First run — nothing yet, just the create/assign forms and the default-open note. */
export function FirstRun() {
  return <div className="hud-root" style={wrap}><DataSpacesPanel /></div>;
}
