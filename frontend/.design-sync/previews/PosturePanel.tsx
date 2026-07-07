import React from 'react';
import { PosturePanel } from 'jarvis-hud-v2';

/* PosturePanel self-fetches GET /api/security/posture (admin) on mount — the packaged
   security posture read surface (secrets-at-rest, skill signing, sandbox isolation).
   Stories drive the REAL component through a module-scoped fetch stub keyed off the
   harness's ?story= param; the offline cell leaves the path unstubbed so the panel's
   amber degrade row renders for real. */
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
  Hardened: {
    '/api/security/posture': {
      guardrails: { mode: 'enforce' },
      secrets: { encrypted_at_rest: true, backend: 'keyring' },
      skills: { require_signed: true, trusted: 12, total: 12, untrusted: 0 },
      sandbox: { isolated: true, docker_available: true },
    },
  },
  DevBoxLax: {
    '/api/security/posture': {
      guardrails: { mode: 'monitor' },
      secrets: { encrypted_at_rest: false, backend: 'plain-json' },
      skills: { require_signed: false, trusted: 9, total: 14, untrusted: 5 },
      sandbox: { isolated: false, docker_available: false },
    },
  },
  Offline: {},
}, 'Hardened');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Production posture — keyring-encrypted secrets, all 12 skills signed, Docker isolation. */
export function Hardened() {
  return <div className="hud-root" style={wrap}><PosturePanel /></div>;
}

/** Dev-box posture — plain-text secrets, 5 untrusted skills, host-exec sandbox: every red/amber tag path. */
export function DevBoxLax() {
  return <div className="hud-root" style={wrap}><PosturePanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><PosturePanel /></div>;
}
