import React from 'react';
import { RoomsPanel } from 'jarvis-hud-v2';

/* RoomsPanel self-fetches GET /api/rooms on mount. Room selection (message input +
   history box) is click-gated internal state — not chased per wave-1 calibration; the
   list + create-room row is the panel's resting surface. Offline is the real 404. */
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
  Populated: {
    '/api/rooms': {
      rooms: [
        { id: 'war-room', name: 'war-room', agents: ['jarvis', 'stark', 'vision'] },
        { id: 'raiffeisen-pitch', name: 'raiffeisen-pitch', agents: ['athena', 'stark', 'veronica'] },
        { id: 'garage', name: 'garage', agents: ['hephaestus', 'steve'] },
        { id: 'family', name: 'family', agents: ['frigga', 'pepper'] },
      ],
    },
  },
  Empty: {
    '/api/rooms': { rooms: [] },
  },
  Offline: {},
}, 'Populated');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Four multi-agent rooms with their member rosters; new-room creation row below. */
export function Populated() {
  return <div className="hud-root" style={wrap}><RoomsPanel /></div>;
}

/** No rooms yet — "nothing yet" plus the create-room control. */
export function Empty() {
  return <div className="hud-root" style={wrap}><RoomsPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><RoomsPanel /></div>;
}
