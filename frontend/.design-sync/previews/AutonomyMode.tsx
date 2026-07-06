import React from 'react';
import { AutonomyMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;

/* AutonomyMode loads the global AUTO/ASK/OFF switch live (GET /autonomy/mode) on
   mount. Story-keyed fetch shim serves each card its own backend state; the
   BackendUnreachable story leaves the endpoint unstubbed so the REAL 404 exercises
   the honest degrade (status "…", switch disabled) — nothing is faked. */
const STORIES: Record<string, Record<string, unknown>> = {
  GlobalAuto: { '/autonomy/mode': { mode: 'auto' } },
  GlobalAsk: { '/autonomy/mode': { mode: 'ask' } },
  BackendUnreachable: {},
};
const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.GlobalAuto;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

/* The DS collapses .auto-grid to one column below its 1300px desktop media query.
   The capture viewport is 900px, so re-assert the desktop rule scoped to this
   1240px-wide stage (same recipe as wave-1 ContextColumn). Suggested config fix:
   overrides.AutonomyMode.viewport > 1300px wide. */
const DESKTOP_GRID = '.dsx-autonomy .auto-grid{grid-template-columns:1fr 1fr;}';
const stage: React.CSSProperties = { width: 1240, height: 690, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.66 } as React.CSSProperties;

function Stage({ children }: { children?: React.ReactNode }) {
  return (
    <div className="hud-root dsx-autonomy" style={stage}>
      <style>{DESKTOP_GRID}</style>
      {children}
    </div>
  );
}

/** Global switch on AUTO (balanced) — morning brief, observer log, per-agent scope reference. */
export function GlobalAuto() {
  return <Stage><AutonomyMode t={T} /></Stage>;
}

/** Global switch on ASK — every side-effect waits for approval. */
export function GlobalAsk() {
  return <Stage><AutonomyMode t={T} /></Stage>;
}

/** Mode endpoint unreachable — honest degrade: status "…", switch disabled until the backend answers. */
export function BackendUnreachable() {
  return <Stage><AutonomyMode t={T} /></Stage>;
}
