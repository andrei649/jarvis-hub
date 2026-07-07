import React from 'react';
import { LiveSourceChip } from 'jarvis-hud-v2';

/* LiveSourceChip (CDX-9) is the per-mode data-provenance label: green LIVE
   when the mode's backend source is streaming real data, amber SEED when the
   demo fallback is showing. It renders once under a mode header, block-level,
   above the mode content — the stage mirrors that placement with a real
   panel-head so the chip is judged in situ. state anything other than
   'live'/'seed' renders nothing (not a visual state — skipped). */
const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 340 };

function ModeStage({ state, caption }: { state: string; caption: string }) {
  return (
    <div className="hud-root" style={frame}>
      <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><span className="ttl">COCKPIT</span><span className="st">{caption}</span></div>
        <div className="panel-body" style={{ display: 'flex', flexDirection: 'column' }}>
          <LiveSourceChip state={state} />
          <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.5 }}>mode content renders below the provenance chip</div>
        </div>
      </div>
    </div>
  );
}

/** Green LIVE — at least one of the mode's backend sources is streaming real data. */
export function Live() {
  return <ModeStage state="live" caption="backend streaming" />;
}

/** Amber SEED — demo mode is on and the mode is showing the seeded mock, honestly labelled. */
export function Seed() {
  return <ModeStage state="seed" caption="demo fallback" />;
}
