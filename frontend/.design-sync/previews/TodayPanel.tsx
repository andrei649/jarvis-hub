import React from 'react';
import { TodayPanel } from 'jarvis-hud-v2';

/* TodayPanel self-fetches GET /api/dashboard/today on mount — "Today in Jarvis": what
   it did (autonomy actions) + learned (memory facts) in one feed. Offline is the real
   404 degrade row. */
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
  BusyDay: {
    '/api/dashboard/today': {
      counts: { actions: 5, learnings: 3 },
      items: [
        { kind: 'action', id: 418, title: 'Filed weekly market brief (gecko)', ts: '2026-07-06 11:30:00' },
        { kind: 'learning', key: 'bmw.parts', value: 'E46 valve cover gasket ordered', ts: '2026-07-06 10:11:00' },
        { kind: 'action', id: 415, title: 'Rescheduled Digitaholic sync to 14:00', ts: '2026-07-06 09:02:00' },
        { kind: 'action', id: 414, title: 'Sent Raiffeisen KPI digest to Stark', ts: '2026-07-06 08:15:00' },
        { kind: 'learning', key: 'gym.schedule', value: 'Andrei trains Mon/Wed/Fri 07:00', ts: '2026-07-06 07:48:00' },
        { kind: 'action', id: 411, title: 'Morning intel brief delivered (friday)', ts: '2026-07-06 07:05:00' },
        { kind: 'learning', key: 'family.max', value: 'Max school recital on Friday 18:00', ts: '2026-07-06 06:58:00' },
        { kind: 'action', id: 409, title: 'Archived 14 newsletter emails (pepper)', ts: '2026-07-06 06:40:00' },
      ],
    },
  },
  QuietDay: {
    '/api/dashboard/today': { counts: { actions: 0, learnings: 0 }, items: [] },
  },
  Offline: {},
}, 'BusyDay');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** A working morning — 5 did / 3 learned, interleaved with per-item timestamps. */
export function BusyDay() {
  return <div className="hud-root" style={wrap}><TodayPanel /></div>;
}

/** Nothing yet today — zero counts in the sub, "nothing yet" body. */
export function QuietDay() {
  return <div className="hud-root" style={wrap}><TodayPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><TodayPanel /></div>;
}
