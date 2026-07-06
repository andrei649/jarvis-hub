import React from 'react';
import { PairingPanel } from 'jarvis-hud-v2';

/* PairingPanel is a live-dashboard panel: zero props, fetches the admin-guarded
   GET /api/channels/pairing on mount. Each story serves its own backend payload
   through a scoped fetch shim keyed off the card's ?story= param, so the REAL
   exported panel renders real data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  PendingRequests: {
    '/api/channels/pairing': {
      summary: { pending: 2 },
      senders: [
        { name: '+40 722 314 559', sender_id: 'wa:40722314559', channel: 'whatsapp', status: 'pending' },
        { name: '@relu_dm', sender_id: 'tg:88231907', channel: 'telegram', status: 'pending' },
        { name: 'Cosmina', sender_id: 'tg:1290443', channel: 'telegram', status: 'paired' },
        { name: 'Max', sender_id: 'wa:40733001122', channel: 'whatsapp', status: 'paired' },
        { name: 'promo-blast-4412', sender_id: 'tg:99120034', channel: 'telegram', status: 'blocked' },
      ],
    },
  },
  AllPaired: {
    '/api/channels/pairing': {
      summary: { pending: 0 },
      senders: [
        { name: 'Cosmina', sender_id: 'tg:1290443', channel: 'telegram', status: 'paired' },
        { name: 'Max', sender_id: 'wa:40733001122', channel: 'whatsapp', status: 'paired' },
        { name: 'Mama', sender_id: 'wa:40744556677', channel: 'whatsapp', status: 'paired' },
      ],
    },
  },
  Empty: {
    '/api/channels/pairing': { summary: { pending: 0 }, senders: [] },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.PendingRequests;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 420 };

/** Two unknown senders held for a decision alongside paired family and a blocked spammer. */
export function PendingRequests() {
  return <div className="hud-root" style={frame}><PairingPanel /></div>;
}

/** Steady state — the household is paired, nothing pending. */
export function AllPaired() {
  return <div className="hud-root" style={frame}><PairingPanel /></div>;
}

/** No senders seen yet — just the pairing-code control and the hold-until-decided promise. */
export function Empty() {
  return <div className="hud-root" style={frame}><PairingPanel /></div>;
}
