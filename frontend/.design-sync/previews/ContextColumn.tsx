import React from 'react';
import { ContextColumn, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* zoom buys a taller virtual column (the app gives it a full workzone row) inside the ~650px capture viewport */
const wrap: React.CSSProperties = { width: 420, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, zoom: 0.8 } as React.CSSProperties;
/* the app's workzone grid gives this column a definite height — recreate it with a single-cell grid */
const stage = (h: number): React.CSSProperties => ({ height: h, display: 'grid' });
/* The capture viewport (900px) sits below the DS's 1100px desktop breakpoint, where
   `.col.scrollcol { display:none }` (styles.css:583) hides this column entirely.
   Re-assert the DS base rule (`.col` is display:flex, styles.css:166) scoped to this
   stage so the desktop composition can be photographed. Proper fix is config-level:
   cfg.overrides.ContextColumn.viewport = "1280x720" — recorded in learnings/wave1-shell.md. */
const DesktopViewportFix = () => <style>{'.ctx-desktop .col.scrollcol{display:flex}'}</style>;
/* seed decisions lack the runtime _id the column keys on */
const DECISIONS = V2.DECISIONS.map((d: any, i: number) => ({ ...d, _id: 'd' + i }));

/** Canonical morning context — decision queue, weather, schedule, heartbeat. */
export function MorningContext() {
  return (
    <div className="hud-root ctx-desktop" style={wrap}>
      <DesktopViewportFix />
      <div style={stage(760)}>
        <ContextColumn decisions={DECISIONS.slice(0, 2)} onDecision={noop} weather={V2.WEATHER}
          calendar={V2.CALENDAR.slice(0, 4)} heartbeat={V2.HEARTBEAT.slice(0, 3)} demo={false} t={T} />
      </div>
    </div>
  );
}

/** Nothing connected yet — every panel shows its honest empty state. */
export function EmptyStates() {
  return (
    <div className="hud-root ctx-desktop" style={wrap}>
      <DesktopViewportFix />
      <div style={stage(420)}>
        <ContextColumn decisions={[]} onDecision={noop} weather={null}
          calendar={[]} heartbeat={[]} demo={false} t={T} />
      </div>
    </div>
  );
}
