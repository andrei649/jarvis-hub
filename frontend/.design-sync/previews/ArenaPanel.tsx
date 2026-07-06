import React from 'react';
import { ArenaPanel } from 'jarvis-hud-v2';

/* ArenaPanel self-fetches GET /api/arena/leaderboard on mount — the preview drives the
   REAL component through a module-scoped fetch stub keyed off the harness's ?story=
   param. Model names follow the repo's seed universe (gemma-4-26b default, claude-haiku
   cloud fallback). */
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
  Leaderboard: {
    '/api/arena/leaderboard': {
      leaderboard: [
        { model: 'gemma-4-26b-a4b', elo: 1128, win_rate: 0.64, games: 47 },
        { model: 'claude-haiku', elo: 1093, win_rate: 0.57, games: 41 },
        { model: 'qwen3-32b', elo: 1004, win_rate: 0.49, games: 35 },
        { model: 'mistral-small-3', elo: 951, win_rate: 0.41, games: 29 },
        { model: 'phi-4-14b', elo: 872, win_rate: 0.28, games: 18 },
      ],
    },
  },
  NoMatchesYet: {
    '/api/arena/leaderboard': { leaderboard: [] },
  },
  Offline: {},
}, 'Leaderboard');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Five ranked models — ELO, win-rate and game counts from real arena matches. */
export function Leaderboard() {
  return <div className="hud-root" style={wrap}><ArenaPanel /></div>;
}

/** No matches yet — the run-a-comparison empty state. */
export function NoMatchesYet() {
  return <div className="hud-root" style={wrap}><ArenaPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade path. */
export function Offline() {
  return <div className="hud-root" style={wrap}><ArenaPanel /></div>;
}
