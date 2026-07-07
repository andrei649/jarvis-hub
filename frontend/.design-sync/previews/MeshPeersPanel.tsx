import React from 'react';
import { MeshPeersPanel } from 'jarvis-hud-v2';

/* MeshPeersPanel is a live-dashboard panel: zero props, fetches the
   admin-guarded GET /api/a2a/peers on mount. Each story serves its own backend
   payload through a scoped fetch shim keyed off the card's ?story= param, so
   the REAL exported panel renders real data end-to-end — nothing is hand-drawn.
   (The shown-once shared-secret banner only exists after an add-peer POST, so
   it is not statically reachable.) */
const STORIES: Record<string, Record<string, unknown>> = {
  Allowlisted: {
    '/api/a2a/peers': {
      peers: [
        { peer_id: 'hub-cluj', name: 'Cluj homelab', secret_hint: '…9f2c' },
        { peer_id: 'office-digitaholic', name: 'Digitaholic office', secret_hint: '…41ab' },
        { peer_id: 'edge-cabin', name: 'Mountain cabin edge', secret_hint: '…77de' },
      ],
    },
  },
  Empty: {
    '/api/a2a/peers': { peers: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Allowlisted;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

/* 460 not 380: the add-peer row is two min-content text inputs plus the add
   button — at 380 the button clips off the panel's right edge. */
const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 460 };

/** Three allowlisted A2A peers with masked secret hints, each removable. */
export function Allowlisted() {
  return <div className="hud-root" style={frame}><MeshPeersPanel /></div>;
}

/** No peers yet — just the add-peer flow (peer_id + name). */
export function Empty() {
  return <div className="hud-root" style={frame}><MeshPeersPanel /></div>;
}
