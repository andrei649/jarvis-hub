import React from 'react';
import { AdminMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;

/* AdminMode renders V2.ADMIN (models/keys/backups | plugins/channels/host); the
   plugin toggle PUT only fires on click for rows with a real id — no shim needed.
   The DS collapses .admin-grid to one column below its 1300px desktop media
   query; re-assert the desktop rule scoped to this 1240px stage (wave-1
   ContextColumn recipe). Suggested config fix: viewport wider than 1300px. */
const DESKTOP_GRID = '.dsx-admin .admin-grid{grid-template-columns:1fr 1fr;}';
const stage: React.CSSProperties = { width: 1240, height: 960, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.6 } as React.CSSProperties;

/** Full settings surface — model backends, masked keys with rotation age, backups, plugin registry toggles, channels, host stats. */
export function FullRegistry() {
  return (
    <div className="hud-root dsx-admin" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <AdminMode t={T} />
    </div>
  );
}

/** Same registry under data-density="compact" — the DS density axis on a data-heavy mode. */
export function CompactDensity() {
  return (
    <div className="hud-root dsx-admin" data-density="compact" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <AdminMode t={T} />
    </div>
  );
}
