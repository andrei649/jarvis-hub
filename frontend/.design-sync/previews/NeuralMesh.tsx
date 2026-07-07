import React from 'react';
import { NeuralMesh, V2 } from 'jarvis-hud-v2';

/* NeuralMesh (HUD v3) — the cinematic canvas brain: arc-reactor core,
   cost-sized model shell (gemma local + claude/gemini cloud), tier-coloured
   agent constellation, comet token-flow, auto-choreographed cascades. It
   paints from the first rAF frames, but `.nmesh` is flex:1/min-height:0 —
   staged in a definite-size 640×420 flex column so the canvas gets a real
   box. Real roster from V2.AGENTS; tasks use the /tasks row shape
   ({owner|agent_id, title, state}). Hover tooltips are pointer-gated (not
   statically reachable). */
const TASKS = [
  { owner: 'stark', title: 'KPI delta sweep', state: 'running' },
  { owner: 'stark', title: 'Raiffeisen deck refresh', state: 'pending' },
  { owner: 'vision', title: 'competitor pricing scan', state: 'running' },
  { owner: 'vision', title: 'OSINT source audit', state: 'pending' },
  { owner: 'vision', title: 'summarize research week', state: 'done' },
  { owner: 'gecko', title: 'EUR/RON band watch', state: 'running' },
  { owner: 'ultron', title: 'outbound PII rescan', state: 'error' },
  { owner: 'pepper', title: 'calendar reconcile', state: 'done' },
  { owner: 'jarvis', title: 'route morning brief', state: 'running' },
];

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 672 };
const stage: React.CSSProperties = { width: 640, height: 420, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' };

function Mesh(props: any) {
  return (
    <div className="hud-root" style={frame}>
      <div style={stage}>
        <NeuralMesh agents={V2.AGENTS} onSelect={() => {}} t={V2.I18N.en} {...props} />
      </div>
    </div>
  );
}

/** The full 15-agent constellation orbiting the core — model shell, tier colours, ambient cascades, legend. */
export function Constellation() {
  return <Mesh />;
}

/** Live /tasks fanned to the outer ring — state-coloured task dots per owning agent, task count in the legend. */
export function TaskFan() {
  return <Mesh tasks={TASKS} />;
}

/** Stark focused (activeId) — its tasks fan close with labels, unrelated agents and edges dim.
    (Stark sits on the ring's right flank, so the fan labels stay inside the canvas; vision sits
    at the bottom and its fan clipped below the stage.) */
export function FocusStark() {
  return <Mesh tasks={TASKS} activeId="stark" />;
}

/** Calm motion preference — rotation, comets and cascades stilled; structure fully legible. */
export function Calm() {
  return <Mesh tasks={TASKS} motion="calm" />;
}
