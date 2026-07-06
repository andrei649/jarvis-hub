import React from 'react';
import { SecuritySkillsPanel } from 'jarvis-hud-v2';

/* SecuritySkillsPanel self-fetches GET /api/security-skills/tactics on mount — the
   curated offline ATT&CK knowledge browser (0.42 pack). Tactic expansion (techniques
   fetch) is click-gated internal state — not chased per wave-1 calibration. Offline
   is the real 404 degrade row. */
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
  PackLoaded: {
    '/api/security-skills/tactics': {
      tactics: [
        { id: 'TA0001', name: 'Initial Access' },
        { id: 'TA0002', name: 'Execution' },
        { id: 'TA0003', name: 'Persistence' },
        { id: 'TA0004', name: 'Privilege Escalation' },
        { id: 'TA0005', name: 'Defense Evasion' },
        { id: 'TA0006', name: 'Credential Access' },
        { id: 'TA0007', name: 'Discovery' },
        { id: 'TA0008', name: 'Lateral Movement' },
        { id: 'TA0010', name: 'Exfiltration' },
        { id: 'TA0011', name: 'Command and Control' },
      ],
    },
  },
  Offline: {},
}, 'PackLoaded');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** The curated pack loaded — ten ATT&CK tactics, each an expandable row (▸). */
export function PackLoaded() {
  return <div className="hud-root" style={wrap}><SecuritySkillsPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row. */
export function Offline() {
  return <div className="hud-root" style={wrap}><SecuritySkillsPanel /></div>;
}
