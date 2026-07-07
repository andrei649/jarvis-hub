import React from 'react';
import { Tabs, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* all 15 tabs need ~1280px; zoom keeps the strip inside the ~900px capture viewport */
const wrap: React.CSSProperties = { width: 1280, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, zoom: 0.66 } as React.CSSProperties;

/** Canonical horizontal mode tabs (narrow-viewport nav) — Cockpit active. */
export function CockpitActive() {
  return (
    <div className="hud-root" style={wrap}>
      <Tabs mode="cockpit" setMode={noop} t={T} />
    </div>
  );
}

/** Strip scrolled to its tail (the component scrolls horizontally by design) — Observe active. */
export function ObserveActive() {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const strip = ref.current && ref.current.querySelector('.tabs');
    if (strip) strip.scrollLeft = strip.scrollWidth;
  }, []);
  return (
    <div ref={ref} className="hud-root" style={wrap}>
      <Tabs mode="observe" setMode={noop} t={T} />
    </div>
  );
}
