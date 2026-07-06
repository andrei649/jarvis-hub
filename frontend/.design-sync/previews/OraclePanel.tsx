import React from 'react';
import { OraclePanel } from 'jarvis-hud-v2';

/* OraclePanel is a live-dashboard panel: zero props, fetches
   GET /api/oracle/status on mount. Each story serves its own backend payload
   through a scoped fetch shim keyed off the card's ?story= param, so the REAL
   exported panel renders real data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  InSync: {
    '/api/oracle/status': { watcher_running: true, last_checked: '2026-07-06 08:15', conflicts: [] },
  },
  Conflicts: {
    '/api/oracle/status': {
      watcher_running: true,
      last_checked: '2026-07-06 08:15',
      conflicts: [
        { file_path: 'truth/roster.md', resolved: false },
        { file_path: 'truth/autonomy-policy.md', resolved: false },
        { file_path: 'truth/capabilities.md', resolved: true },
      ],
    },
  },
  WatcherIdle: {
    '/api/oracle/status': { watcher_running: false, conflicts: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.InSync;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 400 };

/** Watching and clean — green "in sync", sync-now on hand. */
export function InSync() {
  return <div className="hud-root" style={frame}><OraclePanel /></div>;
}

/** Local/remote truth-doc conflicts — two open, one already resolved, clear-resolved offered. */
export function Conflicts() {
  return <div className="hud-root" style={frame}><OraclePanel /></div>;
}

/** Watcher not running — idle header, manual sync still available. */
export function WatcherIdle() {
  return <div className="hud-root" style={frame}><OraclePanel /></div>;
}
