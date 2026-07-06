import React from 'react';
import { HealthMode, V2 } from 'jarvis-hud-v2';

/* HealthMode (Hercules' home) is pure seed data (V2.HEALTH) — no fetches. The activity
   Ring internals are not exported; they render inside the mode (rings card, top-left). */
const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.65 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1300, height: 490, display: 'flex' };
/* 900px capture viewport < the 1300px breakpoint collapsing .admin-grid (styles.css:544)
   — scoped desktop re-assert; config-level fix needs viewport ≥1301px (see learnings). */
const Wide = () => <style>{'.w2wide .admin-grid{grid-template-columns:1fr 1fr;gap:var(--gap) 28px}'}</style>;

/** Hercules' daily board — three activity rings, sleep/HR/HRV/weight stat cards, week bars with a rest day, plan with the on-device sync badge. */
export function HerculesDaily() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><HealthMode t={T} /></div>
    </div>
  );
}

/** The same board at compact density — the DS density axis on the most data-dense personal mode. */
export function CompactDensity() {
  return (
    <div className="hud-root w2wide" data-density="compact" style={wrap}>
      <Wide />
      <div style={stage}><HealthMode t={T} /></div>
    </div>
  );
}
