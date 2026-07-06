import React from 'react';
import { WorkflowsPanel } from 'jarvis-hud-v2';

/* WorkflowsPanel is a live-dashboard panel: zero props, fetches GET
   /api/workflows on mount (HUD-v3 C7 — the 0.34 runtime management surface:
   list registered pipelines, run one, delete a user-defined one). Each story
   serves its own backend payload through a scoped fetch shim keyed off the
   card's ?story= param, so the REAL exported panel renders real data
   end-to-end. Offline has NO stub — the real 404 exercises the documented
   amber degrade row. (The "ran <id> · ok" toast is click-gated behind the run
   button, so it is not statically reachable.) */
const STORIES: Record<string, Record<string, unknown>> = {
  Registered: {
    '/api/workflows': {
      workflows: [
        { id: 'morning-brief', name: 'morning-brief', steps: [{}, {}, {}, {}] },
        { id: 'inbox-triage', name: 'inbox-triage', steps: [{}, {}] },
        { id: 'kpi-weekly', name: 'kpi-weekly', steps: [{}, {}, {}, {}, {}] },
        { id: 'market-scan', name: 'market-scan', steps: [{}, {}, {}] },
        { id: 'backup-nightly', name: 'backup-nightly', steps: [{}] },
      ],
    },
  },
  Empty: {
    '/api/workflows': { workflows: [] },
  },
  Offline: {}, // nothing stubbed — real 404 → designed amber "offline" degrade
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Registered;
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

/** Five registered pipelines (built-in + user-defined) — step-count tags, run and delete per row. */
export function Registered() {
  return <div className="hud-root" style={frame}><WorkflowsPanel /></div>;
}

/** No pipelines registered — "0 pipelines" sub plus the empty "nothing yet" state. */
export function Empty() {
  return <div className="hud-root" style={frame}><WorkflowsPanel /></div>;
}

/** Backend unreachable — the amber offline degrade row (real 404, unstubbed). */
export function Offline() {
  return <div className="hud-root" style={frame}><WorkflowsPanel /></div>;
}
