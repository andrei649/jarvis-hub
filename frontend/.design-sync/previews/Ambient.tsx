import React from 'react';
import { Ambient, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
const CLOCK = new Date(2026, 6, 6, 8, 2, 0);
/* .ambient is position:fixed inset:0 — the transform makes this stage its containing block */
const stage: React.CSSProperties = {
  position: 'relative', width: 856, height: 620, overflow: 'hidden',
  transform: 'translateZ(0)', background: 'var(--void, #04070e)', borderRadius: 8,
};
const DECISIONS = V2.DECISIONS.map((d: any, i: number) => ({ ...d, _id: 'd' + i }));

/** Ambient wall-display — big clock, EKG, live stats, pending decisions listed. */
export function PendingDecisions() {
  return (
    <div className="hud-root" style={stage}>
      <Ambient onExit={noop} clock={CLOCK} lang="en" agents={V2.AGENTS}
        decisions={DECISIONS} motion="calm" localPct={87} t={T} />
    </div>
  );
}

/** All clear — zero pending, fully local; just the heartbeat stats. */
export function AllClear() {
  return (
    <div className="hud-root" style={stage}>
      <Ambient onExit={noop} clock={CLOCK} lang="en" agents={V2.AGENTS}
        decisions={[]} motion="calm" localPct={100} t={T} />
    </div>
  );
}
