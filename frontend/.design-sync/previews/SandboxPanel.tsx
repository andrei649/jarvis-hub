import React from 'react';
import { SandboxPanel } from 'jarvis-hud-v2';

/* SandboxPanel self-fetches GET /sandbox/status on mount (code editor + execute are
   click-gated — not chased). Stories: docker backend / insecure host-exec warning /
   status unreachable (unstubbed — panel renders without sub or warning; it has no
   State row, so no amber line here by design). */
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
  DockerIsolated: {
    '/sandbox/status': { backend: 'docker', docker: true, insecure_host_exec: false },
  },
  HostExecWarning: {
    '/sandbox/status': { backend: 'subprocess', docker: false, insecure_host_exec: true },
  },
  StatusUnknown: {},
}, 'DockerIsolated');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Docker backend up — LIVE chip, "docker" sub, python/shell picker and execute. */
export function DockerIsolated() {
  return <div className="hud-root" style={wrap}><SandboxPanel /></div>;
}

/** Host-exec fallback — the red "code runs WITHOUT isolation" warning banner. */
export function HostExecWarning() {
  return <div className="hud-root" style={wrap}><SandboxPanel /></div>;
}

/** Status endpoint unreachable — editor still offered, no chip/sub (fails open, DEV_MODE gate catches execution). */
export function StatusUnknown() {
  return <div className="hud-root" style={wrap}><SandboxPanel /></div>;
}
