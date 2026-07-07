import React from 'react';
import { Palette, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* .pal-scrim is position:fixed inset:0 — the transform makes this stage its containing block */
const stage: React.CSSProperties = {
  position: 'relative', width: 856, height: 600, overflow: 'hidden',
  transform: 'translateZ(0)', background: 'var(--void, #04070e)', borderRadius: 8,
};

/** Command palette open — Go to group, hotkey hints, footer key legend. */
export function Open() {
  return (
    <div className="hud-root" style={stage}>
      <Palette open={true} onClose={noop} onMode={noop} setAccent={noop} setLang={noop}
        onAmbient={noop} ui={{}} t={T} />
    </div>
  );
}

/** Typed query "accent" — list filtered down to the Theme group's accent commands. */
export function FilteredTheme() {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    /* drive the real controlled input the way a user would */
    const input = ref.current && ref.current.querySelector('input');
    if (!input) return;
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, 'accent');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, []);
  return (
    <div ref={ref} className="hud-root" style={stage}>
      <Palette open={true} onClose={noop} onMode={noop} setAccent={noop} setLang={noop}
        onAmbient={noop} ui={{}} t={T} />
    </div>
  );
}
