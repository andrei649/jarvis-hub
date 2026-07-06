import React from 'react';
import { SatellitesPanel } from 'jarvis-hud-v2';

/* SatellitesPanel self-fetches GET /api/satellites on mount — the H12.8 mic-satellite
   hub (pair a phone/device as a mic). Stories: paired devices / none yet (hint copy) /
   offline (real 404, unstubbed). */
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
  Paired: {
    '/api/satellites': {
      satellites: [
        { id: 'andrei-pixel9', kind: 'phone' },
        { id: 'office-macbook', kind: 'laptop' },
        { id: 'kitchen-tablet', kind: 'tablet' },
      ],
    },
  },
  NonePaired: {
    '/api/satellites': { satellites: [] },
  },
  Offline: {},
}, 'Paired');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Three paired mic satellites with kind tags and unpair controls. */
export function Paired() {
  return <div className="hud-root" style={wrap}><SatellitesPanel /></div>;
}

/** Nothing paired — "pair a phone/device to use it as a mic" hint + pair row. */
export function NonePaired() {
  return <div className="hud-root" style={wrap}><SatellitesPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><SatellitesPanel /></div>;
}
