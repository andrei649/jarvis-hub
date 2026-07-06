import React from 'react';
import { CinemaMesh, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* .cinema is position:fixed inset:0 — the transform makes this stage its containing block */
const stage: React.CSSProperties = {
  position: 'relative', width: 856, height: 600, overflow: 'hidden',
  transform: 'translateZ(0)', background: 'var(--void, #04070e)', borderRadius: 8,
};

/** Cinema showcase — full cabinet on the neural mesh, live count + on-device share. */
export function Showcase() {
  return (
    <div className="hud-root" style={stage}>
      <CinemaMesh agents={V2.AGENTS} localPct={87} onExit={noop} t={T} />
    </div>
  );
}

/** Lean crew — CNS tier only, no locality figure yet (stat honestly omitted). */
export function CoreCrew() {
  const cns = V2.AGENTS.filter((a: any) => a.tier === 'CNS');
  return (
    <div className="hud-root" style={stage}>
      <CinemaMesh agents={cns} localPct={null} onExit={noop} t={T} />
    </div>
  );
}
