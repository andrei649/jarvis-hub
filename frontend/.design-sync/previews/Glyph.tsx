import React from 'react';
import { Glyph } from 'jarvis-hud-v2';

// Dark-first DS: cards render on a white stage, so every preview brings the void.
const wrap: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: 18, padding: 16, alignItems: 'center',
  background: 'var(--void, #04070e)', borderRadius: 8,
  color: 'var(--accent-light, #8fe0ff)', fontFamily: 'var(--font-mono, monospace)', fontSize: 10,
};

/** Agent dossier glyphs — one per core agent id. */
export function AgentGlyphs() {
  const ids = ['jarvis', 'friday', 'pepper', 'jerome', 'athena', 'stark'];
  return (
    <div className="hud-root" style={wrap}>
      {ids.map((id) => (
        <div key={id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
          <Glyph id={id} size={28} />
          <span style={{ opacity: 0.7 }}>{id}</span>
        </div>
      ))}
    </div>
  );
}

/** Size sweep on one glyph. */
export function Sizes() {
  return (
    <div className="hud-root" style={wrap}>
      <Glyph id="jarvis" size={16} />
      <Glyph id="jarvis" size={24} />
      <Glyph id="jarvis" size={40} />
      <Glyph id="jarvis" size={64} />
    </div>
  );
}
