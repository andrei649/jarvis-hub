import React from 'react';
import { CapturePanel } from 'jarvis-hud-v2';

/* CapturePanel self-fetches GET /api/capture + /api/capture/status on mount (no data
   props), so the preview drives the REAL component through a module-scoped fetch stub,
   scenario-keyed off the capture harness's ?story= param (each story renders on its own
   page). Unstubbed stories fall through to real fetch → 404 → the panel's own offline
   degrade path. */
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
  CapturingActive: {
    '/api/capture/status': { enabled: true },
    '/api/capture': {
      records: [
        { id: 'cap-91', preview: 'clipboard · "Q3 roadmap sync — action items for ▓▓▓▓▓"', surface: 'clipboard' },
        { id: 'cap-90', preview: 'screen · Figma — HUD v2 console overlay (title only)', surface: 'screen' },
        { id: 'cap-89', preview: 'mic · 14s ambient — transcript redacted (2 names)', surface: 'mic' },
        { id: 'cap-88', preview: 'clipboard · "invoice #A-1042 · ▓▓▓▓▓▓ Ltd"', surface: 'clipboard' },
        { id: 'cap-87', preview: 'screen · Gmail — subject line only, body withheld', surface: 'screen' },
      ],
    },
  },
  OptedOut: {
    '/api/capture/status': { enabled: false },
    '/api/capture': { records: [] },
  },
  // Offline: no routes — real fetch 404s and the panel renders its degrade path.
  Offline: {},
}, 'CapturingActive');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Capture on — redacted previews stream in, each individually deletable. */
export function CapturingActive() {
  return <div className="hud-root" style={wrap}><CapturePanel /></div>;
}

/** Opt-in not taken — SEED chip, off · 0, and the privacy-promise empty state. */
export function OptedOut() {
  return <div className="hud-root" style={wrap}><CapturePanel /></div>;
}

/** Backend unreachable — the panel's documented offline degrade (never blocks). */
export function Offline() {
  return <div className="hud-root" style={wrap}><CapturePanel /></div>;
}
