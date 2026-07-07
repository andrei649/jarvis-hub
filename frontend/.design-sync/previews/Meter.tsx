import React from 'react';
import { Meter } from 'jarvis-hud-v2';

// Dark-first DS: cards render on a white stage, so every preview brings the void.
const wrap: React.CSSProperties = {
  padding: 16, maxWidth: 260, display: 'grid', gap: 10,
  background: 'var(--void, #04070e)', borderRadius: 8,
};

/** Resource meters as used in the cockpit rail — label, value, unit. */
export function SystemMeters() {
  return (
    <div className="hud-root" style={wrap}>
      <Meter label="VRAM" val={71} />
      <Meter label="CPU" val={23} />
      <Meter label="DISK" val={48} />
    </div>
  );
}

/** Value range sweep incl. clamped overflow and a custom unit. */
export function Range() {
  return (
    <div className="hud-root" style={wrap}>
      <Meter label="IDLE" val={4} />
      <Meter label="STEADY" val={55} />
      <Meter label="HOT" val={92} />
      <Meter label="CLAMPED" val={140} />
      <Meter label="LATENCY" val={38} unit="ms" />
    </div>
  );
}
