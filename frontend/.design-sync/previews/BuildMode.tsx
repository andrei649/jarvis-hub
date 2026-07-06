import React from 'react';
import { BuildMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;

/* BuildMode renders the seeded workflow canvas + skills marketplace + router
   sandbox from V2.BUILD (install POSTs only fire on click — no shim needed).
   The DS collapses .build-grid to one column below its 1300px desktop media
   query; re-assert the desktop rule scoped to this 1240px stage (wave-1
   ContextColumn recipe). Suggested config fix: viewport wider than 1300px. */
const DESKTOP_GRID = '.dsx-build .build-grid{grid-template-columns:1fr 1fr;}';
const stage: React.CSSProperties = { width: 1240, height: 870, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.64 } as React.CSSProperties;

/** Workflow canvas (cron → plugins → agents → delivery), skills marketplace with install states, router dry-run sandbox. */
export function MorningBriefPipeline() {
  return (
    <div className="hud-root dsx-build" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <BuildMode t={T} />
    </div>
  );
}

/** Same canvas under the graphite look + amber accent — the DS theme axes on a full mode. */
export function GraphiteAmber() {
  return (
    <div className="hud-root dsx-build" data-look="graphite" data-accent="amber" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <BuildMode t={T} />
    </div>
  );
}
