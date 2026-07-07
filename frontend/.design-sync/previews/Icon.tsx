import React from 'react';
import { Icon, ICONS } from 'jarvis-hud-v2';

// Dark-first DS: cards render on a white stage, so every preview brings the void.
const wrap: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: 18, padding: 16,
  background: 'var(--void, #04070e)', borderRadius: 8,
  color: 'var(--ink, #cfe6f5)', fontFamily: 'var(--font-mono, monospace)', fontSize: 10,
};
const cell: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, width: 64,
};

/** The full HUD line-icon set at default size, labeled by ICONS key. */
export function IconSet() {
  return (
    <div className="hud-root" style={wrap}>
      {Object.entries(ICONS).map(([key, d]) => (
        <div key={key} style={cell}>
          <Icon d={d} size={20} />
          <span style={{ opacity: 0.7 }}>{key}</span>
        </div>
      ))}
    </div>
  );
}

/** Size + stroke-weight sweep on one icon. */
export function Sizes() {
  return (
    <div className="hud-root" style={{ ...wrap, alignItems: 'center' }}>
      <Icon d={ICONS.shield} size={12} />
      <Icon d={ICONS.shield} size={16} />
      <Icon d={ICONS.shield} size={24} />
      <Icon d={ICONS.shield} size={32} />
      <Icon d={ICONS.shield} size={32} sw={1} />
      <Icon d={ICONS.shield} size={32} sw={2.4} />
    </div>
  );
}

/** Icons pick up currentColor — accent / status coloring comes from context. */
export function Colored() {
  return (
    <div className="hud-root" style={{ ...wrap, alignItems: 'center' }}>
      <span style={{ color: 'var(--accent, #2bb8f0)' }}><Icon d={ICONS.autonomy} size={24} /></span>
      <span style={{ color: 'var(--green, #41f59b)' }}><Icon d={ICONS.trust} size={24} /></span>
      <span style={{ color: 'var(--amber, #ffc24d)' }}><Icon d={ICONS.observe} size={24} /></span>
      <span style={{ color: 'var(--red, #ff5a52)' }}><Icon d={ICONS.bolt} size={24} /></span>
    </div>
  );
}
