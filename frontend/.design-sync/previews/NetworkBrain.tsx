import React from 'react';
import { NetworkBrain, V2 } from 'jarvis-hud-v2';

/* NetworkBrain (HUD v2) — the signature SVG visualizer: jarvis glyph core,
   four concentric tier rings (CNS full circle, BIZ left arc, SEC right arc,
   FND outer), V2.COLLAB bezier links, live packets on edges touching
   active/busy agents, and the V1-parity task fan from /tasks rows.
   `.net-wrap` is flex:1/min-height:0 — staged in a definite 640×460 flex
   column matching the SVG viewBox. t comes from V2.I18N.en (t.network /
   t.agents / t.focusHint drive the overlay + hint). Hover tooltip is
   pointer-gated (not statically reachable). */
const TASKS = [
  { owner: 'stark', title: 'KPI delta sweep', state: 'running' },
  { owner: 'stark', title: 'Raiffeisen deck refresh', state: 'pending' },
  { owner: 'stark', title: 'invoice chase', state: 'done' },
  { owner: 'vision', title: 'competitor pricing scan', state: 'running' },
  { owner: 'vision', title: 'OSINT source audit', state: 'pending' },
  { owner: 'gecko', title: 'EUR/RON band watch', state: 'running' },
  { owner: 'ultron', title: 'outbound PII rescan', state: 'error' },
  { owner: 'pepper', title: 'calendar reconcile', state: 'done' },
];

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 672 };
const stage: React.CSSProperties = { width: 640, height: 460, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' };

function Net(props: any) {
  return (
    <div className="hud-root" style={frame}>
      <div style={stage}>
        <NetworkBrain agents={V2.AGENTS} onSelect={() => {}} focusId={null} setFocusId={() => {}} t={V2.I18N.en} {...props} />
      </div>
    </div>
  );
}

/** The tiered constellation — hex nodes on their rings, collab beziers, spokes, live packets on active links. */
export function Constellation() {
  return <Net />;
}

/** Real /tasks on the outer ring — state-coloured task nodes spoked to their owning agents, counts in the overlay. */
export function TaskRing() {
  return <Net tasks={TASKS} />;
}

/** Stark focused — neighbours stay lit, the rest dims, Stark's three tasks fan out with labels. */
export function FocusStark() {
  return <Net tasks={TASKS} focusId="stark" activeId="stark" />;
}
