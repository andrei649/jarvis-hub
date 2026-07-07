import React from 'react';
import { SystemProfilePanel } from 'jarvis-hud-v2';

/* SystemProfilePanel self-fetches GET /api/system/profiles on mount — the 0.62
   usage-mode posture surface (balanced/gaming/ai/multimedia/admin, read-only, selected
   via JARVIS_SYSTEM_PROFILE). Offline is the real 404 degrade row. */
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

const PROFILES = {
  balanced: { model_tier: 'standard', heavy_features: true, background_autonomy: true },
  gaming: { model_tier: 'lite', heavy_features: false, background_autonomy: false },
  ai: { model_tier: 'max', heavy_features: true, background_autonomy: true },
  multimedia: { model_tier: 'standard', heavy_features: true, background_autonomy: false },
  admin: { model_tier: 'standard', heavy_features: false, background_autonomy: false },
};

stubFetch({
  BalancedDefault: {
    '/api/system/profiles': { active: 'balanced', default: 'balanced', profiles: PROFILES },
  },
  GamingActive: {
    '/api/system/profiles': { active: 'gaming', default: 'balanced', profiles: PROFILES },
  },
  Offline: {},
}, 'BalancedDefault');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Balanced posture active (and default) — all five profiles with their model-tier/feature knobs. */
export function BalancedDefault() {
  return <div className="hud-root" style={wrap}><SystemProfilePanel /></div>;
}

/** Gaming override active — lite tier, no-heavy + no-bg tags mark what the posture gates. */
export function GamingActive() {
  return <div className="hud-root" style={wrap}><SystemProfilePanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><SystemProfilePanel /></div>;
}
