import React from 'react';
import { FamilyMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;

/* FamilyMode is the local-only Frigga home (V2.FAMILY, no fetches). It lays out
   on .admin-grid, which the DS collapses below its 1300px desktop media query —
   re-assert the desktop rule scoped to this stage (wave-1 ContextColumn recipe). */
const DESKTOP_GRID = '.dsx-family .admin-grid{grid-template-columns:1fr 1fr;}';
const stage: React.CSSProperties = { width: 1100, height: 480, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.74 } as React.CSSProperties;

/** Local-only family space — privacy banner, members with notes, reminders, upcoming events. */
export function LocalOnlyHome() {
  return (
    <div className="hud-root dsx-family" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <FamilyMode t={T} />
    </div>
  );
}

/** The same home under the violet accent — the DS accent axis on an agent-home mode. */
export function VioletAccent() {
  return (
    <div className="hud-root dsx-family" data-accent="violet" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <FamilyMode t={T} />
    </div>
  );
}
