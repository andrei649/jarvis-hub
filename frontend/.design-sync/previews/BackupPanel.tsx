import React from 'react';
import { BackupPanel } from 'jarvis-hud-v2';

/* BackupPanel self-fetches GET /api/admin/backup (admin) on mount — the preview drives
   the REAL component through a module-scoped fetch stub keyed off the harness's ?story=
   param. The armed forget-me confirmation is click-gated internal state, so the story
   set covers the reachable static states (snapshots / first-run / offline). */
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
  SnapshotHistory: {
    '/api/admin/backup': {
      backups: [
        { name: 'jarvis-20240515-0300.tar.zst', bytes: 48200000, encrypted: true },
        { name: 'jarvis-20240514-0300.tar.zst', bytes: 47800000, encrypted: true },
        { name: 'jarvis-20240513-0300.tar.zst', bytes: 47100000, encrypted: true },
        { name: 'jarvis-20240512-0300.tar.zst', bytes: 46600000, encrypted: false },
      ],
    },
  },
  FirstBackupPending: {
    '/api/admin/backup': { backups: [] },
  },
  Offline: {},
}, 'SnapshotHistory');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Nightly snapshots — sizes, enc badges, and the backup/verify/export/forget controls. */
export function SnapshotHistory() {
  return <div className="hud-root" style={wrap}><BackupPanel /></div>;
}

/** No snapshots yet — nothing-yet state with the data-sovereignty controls ready. */
export function FirstBackupPending() {
  return <div className="hud-root" style={wrap}><BackupPanel /></div>;
}

/** Backend unreachable — offline degrade; controls remain composed. */
export function Offline() {
  return <div className="hud-root" style={wrap}><BackupPanel /></div>;
}
