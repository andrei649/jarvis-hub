import React from 'react';
import { KgPanel } from 'jarvis-hud-v2';

/* KgPanel is a live-dashboard panel: zero props, fetches GET /api/kg/entities on
   mount. Each story serves its own backend payload through a scoped fetch shim
   keyed off the card's ?story= param, so the REAL exported panel renders real
   data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  Populated: {
    '/api/kg/entities': {
      entities: [
        { name: 'Andrei', type: 'person', mentions: 132 },
        { name: 'Digitaholic', type: 'org', mentions: 57 },
        { name: 'Raiffeisen', type: 'client', mentions: 41 },
        { name: 'Cosmina', type: 'person', mentions: 28 },
        { name: 'BMW build', type: 'project', mentions: 23 },
        { name: 'Max', type: 'family', mentions: 19 },
        { name: 'Savings ladder', type: 'plan', mentions: 9 },
        { name: 'Gym plan', type: 'routine', mentions: 7 },
      ],
    },
  },
  Empty: {
    '/api/kg/entities': { entities: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Populated;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Two months of use — extracted entities with types and mention counts, each deletable. */
export function Populated() {
  return <div className="hud-root" style={frame}><KgPanel /></div>;
}

/** Fresh install — nothing extracted yet; the forget-by-id control is still offered. */
export function Empty() {
  return <div className="hud-root" style={frame}><KgPanel /></div>;
}
