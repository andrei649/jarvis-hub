import React from 'react';
import { FeedbackPanel } from 'jarvis-hud-v2';

/* FeedbackPanel self-fetches GET /api/feedback/summary (admin) on mount — the preview
   drives the REAL component through a module-scoped fetch stub keyed off the harness's
   ?story= param. The NPS submit row renders from initial state in every story. */
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
  HealthyNps: {
    '/api/feedback/summary': {
      nps: 38, promoters: 11, detractors: 3,
      by_kind: { nps: 18, bug: 5, idea: 7 },
      recent: [
        { kind: 'nps', score: 9, message: 'morning brief is scary good now' },
        { kind: 'idea', message: 'let Gecko annotate watchlist moves' },
        { kind: 'bug', message: 'ticker overlaps clock on ultrawide' },
        { kind: 'nps', score: 6, message: 'voice replies still cut off mid-word' },
      ],
    },
  },
  NoScoresYet: {
    '/api/feedback/summary': { nps: null, promoters: 0, detractors: 0, by_kind: {}, recent: [] },
  },
  Offline: {},
}, 'HealthyNps');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** NPS 38 — promoter/detractor split, by-kind counts and recent verbatims. */
export function HealthyNps() {
  return <div className="hud-root" style={wrap}><FeedbackPanel /></div>;
}

/** No scores yet — zeroed summary with the NPS submit row ready. */
export function NoScoresYet() {
  return <div className="hud-root" style={wrap}><FeedbackPanel /></div>;
}

/** Backend unreachable — offline degrade; feedback entry still visible. */
export function Offline() {
  return <div className="hud-root" style={wrap}><FeedbackPanel /></div>;
}
