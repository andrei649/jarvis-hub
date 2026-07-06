import React from 'react';
import { MissionsPanel } from 'jarvis-hud-v2';

/* MissionsPanel is a live-dashboard panel: zero props, fetches GET /api/missions
   on mount. Each story serves its own backend payload through a scoped fetch
   shim keyed off the card's ?story= param, so the REAL exported panel renders
   real data end-to-end — nothing is hand-drawn. The board exercises every
   status color and its contextual state-machine controls. */
const STORIES: Record<string, Record<string, unknown>> = {
  Board: {
    '/api/missions': {
      missions: [
        { id: 'ms-12', title: 'Raiffeisen QBR deck', status: 'active', steps_used: 14, max_steps: 40 },
        { id: 'ms-11', title: 'BMW part sourcing', status: 'paused', steps_used: 9, max_steps: 25 },
        { id: 'ms-13', title: 'Savings rebalance', status: 'planned', steps_used: 0, max_steps: 12 },
        { id: 'ms-09', title: 'July content batch', status: 'done', steps_used: 18, max_steps: 20 },
        { id: 'ms-08', title: 'GPU driver bump', status: 'failed', steps_used: 7, max_steps: 10 },
      ],
    },
  },
  Empty: {
    '/api/missions': { missions: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Board;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 440 };

/** Every state of the missions state machine — planned/active/paused/done/failed with their governed controls. */
export function Board() {
  return <div className="hud-root" style={frame}><MissionsPanel /></div>;
}

/** No workspaces yet. */
export function Empty() {
  return <div className="hud-root" style={frame}><MissionsPanel /></div>;
}
