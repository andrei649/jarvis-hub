import React from 'react';
import { AgentsMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* Full-screen mode: the .panel{flex:1} root collapses without a definite-height
   flex stage. Staged as a desktop-width layout, zoomed into the 900x680 capture
   viewport (never squeeze width — the tier grid reflows honestly by design). */
const stage = (w: number, h: number, zoom: number): React.CSSProperties =>
  ({ width: w, height: h, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16,
     display: 'flex', flexDirection: 'column', zoom } as React.CSSProperties);

/** Canonical roster — all 15 agents grouped by tier (CNS/BIZ/SEC/FND), live/busy/idle status dots, model + policy tags. */
export function FullRoster() {
  return (
    <div className="hud-root" style={stage(1240, 620, 0.66)}>
      <AgentsMode agents={V2.AGENTS} onOpen={noop} t={T} />
    </div>
  );
}

/** Fresh install — only the always-on CNS orchestration core is registered yet. */
export function CoreTierOnly() {
  return (
    <div className="hud-root" style={stage(900, 340, 0.9)}>
      <AgentsMode agents={V2.AGENTS.filter((a) => a.tier === 'CNS')} onOpen={noop} t={T} />
    </div>
  );
}
