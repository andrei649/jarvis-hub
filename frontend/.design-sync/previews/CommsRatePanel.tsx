import React from 'react';
import { CommsRatePanel } from 'jarvis-hud-v2';

/* CommsRatePanel self-fetches GET /api/channels/send-rate-limit (admin) on mount — the
   preview drives the REAL component through a module-scoped fetch stub keyed off the
   harness's ?story= param. The disabled state exercises the panel's honesty contract
   (SEED chip + "unlimited" wording, nothing implied to be recorded). */
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
  CapsConfigured: {
    '/api/channels/send-rate-limit': {
      enabled: true, global_cap: 30, window_seconds: 60,
      channels: [
        { channel: 'telegram', used: 12, cap: 30 },
        { channel: 'email', used: 3, cap: 10 },
        { channel: 'discord', used: 5, cap: 20 },
        { channel: 'sms', used: 0, cap: 5 },
      ],
    },
  },
  Unlimited: {
    '/api/channels/send-rate-limit': { enabled: false, channels: [] },
  },
  Offline: {},
}, 'CapsConfigured');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Outbound caps live — per-channel in-window usage against the 30/60s global cap. */
export function CapsConfigured() {
  return <div className="hud-root" style={wrap}><CommsRatePanel /></div>;
}

/** No cap set (the default) — SEED chip, "unlimited", nothing recorded until opt-in. */
export function Unlimited() {
  return <div className="hud-root" style={wrap}><CommsRatePanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade path. */
export function Offline() {
  return <div className="hud-root" style={wrap}><CommsRatePanel /></div>;
}
