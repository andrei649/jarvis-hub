import React from 'react';
import { TopBar, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const CLOCK = new Date(2026, 6, 6, 8, 2, 11);
const noop = () => {};
/* the bar needs its natural ~1160px; zoom keeps it inside the ~900px capture viewport */
const wrap: React.CSSProperties = { width: 1160, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, zoom: 0.72 } as React.CSSProperties;

/** Canonical: server up, model loaded, live data, hybrid egress, mic on. */
export function LiveOperational() {
  return (
    <div className="hud-root" style={wrap}>
      <TopBar clock={CLOCK} lang="en" setLang={noop} accent="cyan" agents={V2.AGENTS} localPct={87}
        live={true} trust={{ mic: 'on', strict_local: false }} llm={{ state: 'ready', model: 'gemma-4-26b-a4b' }}
        demo={false} setDemo={noop} serverUp={true} onPalette={noop} onAmbient={noop} t={T} />
    </div>
  );
}

/** Demo data + strict-local egress + muted mic — the amber/sealed badge states. */
export function DemoSealed() {
  return (
    <div className="hud-root" style={wrap}>
      <TopBar clock={CLOCK} lang="en" setLang={noop} accent="cyan" agents={V2.AGENTS} localPct={100}
        live={false} trust={{ mic: 'off', strict_local: true }} llm={{ state: 'no_model', model: null }}
        demo={true} setDemo={noop} serverUp={true} onPalette={noop} onAmbient={noop} t={T} />
    </div>
  );
}

/** Server unreachable — everything degrades to the dimmed offline states. */
export function Offline() {
  return (
    <div className="hud-root" style={wrap}>
      <TopBar clock={CLOCK} lang="en" setLang={noop} accent="cyan" agents={[]} localPct={null}
        live={false} trust={{ mic: 'on', strict_local: false }} llm={{ state: 'offline', model: null }}
        demo={false} setDemo={noop} serverUp={false} onPalette={noop} onAmbient={noop} t={T} />
    </div>
  );
}
