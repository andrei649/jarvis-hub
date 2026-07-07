import React from 'react';
import { Reactor } from 'jarvis-hud-v2';

/** The reactor logo — sized by its container, drawn in currentColor. */
export function Sizes() {
  return (
    <div
      className="hud-root"
      style={{ display: 'flex', gap: 24, alignItems: 'center', padding: 16, color: 'var(--accent, #2bb8f0)',
               background: 'var(--void, #04070e)', borderRadius: 8 }}
    >
      <span style={{ width: 24, height: 24, display: 'inline-block' }}><Reactor /></span>
      <span style={{ width: 40, height: 40, display: 'inline-block' }}><Reactor /></span>
      <span style={{ width: 72, height: 72, display: 'inline-block' }}><Reactor /></span>
    </div>
  );
}

/** Accent variants — the reactor inherits whatever ink surrounds it. */
export function Accents() {
  const colors = ['var(--accent, #2bb8f0)', 'var(--green, #41f59b)', 'var(--amber, #ffc24d)', 'var(--violet, #a78bfa)'];
  return (
    <div className="hud-root" style={{ display: 'flex', gap: 24, padding: 16,
         background: 'var(--void, #04070e)', borderRadius: 8 }}>
      {colors.map((c) => (
        <span key={c} style={{ width: 48, height: 48, display: 'inline-block', color: c }}>
          <Reactor />
        </span>
      ))}
    </div>
  );
}
