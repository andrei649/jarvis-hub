import React from 'react';
import { SkillHistoryPanel } from 'jarvis-hud-v2';

/* SkillHistoryPanel self-fetches GET /api/skills/marketplace/history (admin) on mount —
   the 0.58 skill version-history read surface. Disabled story exercises the honesty
   contract (SEED chip + "empty until JARVIS_SKILL_HISTORY is on"); offline is the
   real 404 degrade row. */
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
  Recording: {
    '/api/skills/marketplace/history': {
      enabled: true,
      stats: { total: 23, by_action: { publish: 6, install: 14, uninstall: 3 } },
      events: [
        { id: 1, name: 'market-brief', action: 'install', version: '1.2.0' },
        { id: 2, name: 'gym-coach', action: 'publish', version: '0.3.1' },
        { id: 3, name: 'kpi-digest', action: 'install', version: '2.0.0' },
        { id: 4, name: 'bmw-parts-tracker', action: 'install', version: '0.9.2' },
        { id: 5, name: 'rss-digest', action: 'uninstall', version: '1.0.0' },
        { id: 6, name: 'family-reminders', action: 'publish', version: '1.1.0' },
      ],
    },
  },
  Disabled: {
    '/api/skills/marketplace/history': { enabled: false, events: [], stats: { total: 0, by_action: {} } },
  },
  Offline: {},
}, 'Recording');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** History on — 23 events, publish/install/uninstall action tags + recent event rows. */
export function Recording() {
  return <div className="hud-root" style={wrap}><SkillHistoryPanel /></div>;
}

/** JARVIS_SKILL_HISTORY off (the default) — SEED chip + plain "disabled" wording. */
export function Disabled() {
  return <div className="hud-root" style={wrap}><SkillHistoryPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><SkillHistoryPanel /></div>;
}
