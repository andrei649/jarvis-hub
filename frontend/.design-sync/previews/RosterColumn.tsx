import React from 'react';
import { RosterColumn, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
const wrap: React.CSSProperties = { width: 340, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16 };
/* the app's workzone grid gives this column a definite height — recreate it with a single-cell grid */
const stage: React.CSSProperties = { height: 600, display: 'grid' };
const SYS = { ram_used: 118, ram_total: 192, vram_used: 19.5, vram_total: 24, gpu_load: 62, backend: 'LM Studio', latency: 4.2 };

/** Canonical roster — tiered agent list (scrolls past the fold), Jarvis selected, meters live. */
export function FullRoster() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}>
        <RosterColumn agents={V2.AGENTS} activeId="jarvis" onSelect={noop}
          sys={SYS} llm={{ state: 'ready', model: 'gemma-4-26b-a4b' }} demo={false} t={T} />
      </div>
    </div>
  );
}

/** Server unreachable — roster offline note, meters zeroed, backend amber. */
export function ServerUnreachable() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}>
        <RosterColumn agents={[]} activeId={null} onSelect={noop}
          sys={{}} llm={{ state: 'offline', model: null }} demo={false} t={T} />
      </div>
    </div>
  );
}
