import React from 'react';
import { Rail, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* the full 15-mode rail is ~810px tall; zoom keeps it inside the ~680px capture viewport */
const wrap: React.CSSProperties = { width: 92, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, zoom: 0.75 } as React.CSSProperties;

/** Canonical nav rail — Cockpit active, tier separators between mode groups. */
export function CockpitActive() {
  return (
    <div className="hud-root" style={wrap}>
      <Rail mode="cockpit" setMode={noop} t={T} />
    </div>
  );
}

/** Active state further down the rail — Finance selected in the life-domain group. */
export function FinanceActive() {
  return (
    <div className="hud-root" style={wrap}>
      <Rail mode="finance" setMode={noop} t={T} />
    </div>
  );
}
