import React from 'react';
import { InteropMode, V2 } from 'jarvis-hud-v2';

/* InteropMode is pure seed data (V2.INTEROP) — no fetches. Two cells: the canonical
   board, and the graphite/violet theme axis (data-* on .hud-root) that the DS ships. */
const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.65 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1300, height: 700, display: 'flex' };
/* 900px capture viewport < the 1300px breakpoint collapsing .obs-grid (styles.css:493)
   — scoped desktop re-assert; config-level fix needs viewport ≥1301px (see learnings). */
const Wide = () => <style>{'.w2wide .obs-grid{grid-template-columns:1fr 1fr;gap:var(--gap) 28px}'}</style>;

/** The full integration board — A2A peers, five MCP servers (one degraded), surface widgets, in/out webhooks. */
export function IntegrationBoard() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><InteropMode t={T} /></div>
    </div>
  );
}

/** Same board on the graphite look with the violet accent family — the DS theme axes exercised on a dense mode. */
export function GraphiteViolet() {
  return (
    <div className="hud-root w2wide" data-look="graphite" data-accent="violet" style={wrap}>
      <Wide />
      <div style={stage}><InteropMode t={T} /></div>
    </div>
  );
}
