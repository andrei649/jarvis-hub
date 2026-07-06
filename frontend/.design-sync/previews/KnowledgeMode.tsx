import React from 'react';
import { KnowledgeMode, V2 } from 'jarvis-hud-v2';

/* KnowledgeMode (Vision's OSINT home) is pure seed data (V2.KNOWLEDGE) — no fetches.
   Research queue with per-item status, daily digest, cited saved sources. */
const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.65 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1300, height: 500, display: 'flex' };
/* 900px capture viewport < the 1300px breakpoint collapsing .admin-grid (styles.css:544)
   — scoped desktop re-assert; config-level fix needs viewport ≥1301px (see learnings). */
const Wide = () => <style>{'.w2wide .admin-grid{grid-template-columns:1fr 1fr;gap:var(--gap) 28px}'}</style>;

/** Vision's research desk — queue with indexing/ready states, the daily digest, and cited saves with topic pills. */
export function VisionResearchDesk() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><KnowledgeMode t={T} /></div>
    </div>
  );
}

/** The same desk on the violet accent family — Vision's OSINT accent variant of the DS theme axis. */
export function VioletAccent() {
  return (
    <div className="hud-root w2wide" data-accent="violet" style={wrap}>
      <Wide />
      <div style={stage}><KnowledgeMode t={T} /></div>
    </div>
  );
}
