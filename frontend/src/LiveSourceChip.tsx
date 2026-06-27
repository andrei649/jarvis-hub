// @ts-nocheck
/* CDX-9 — make LIVE vs SEED visible.

   The HUD modes stream real backend data when a source responds (useLiveModes() marks the
   key live) but fall back to a seeded mock otherwise — and nothing told the user which they
   were looking at, so live-wiring quietly hid shape drift. This chip, rendered once per mode,
   labels the current view LIVE (real backend) or SEED (demo/mock). Pure + unit-tested; the
   live-pixel placement is owner-verified (the CDX-9 live surface). */
import React from 'react';

/**
 * Resolve a mode's data provenance from the live-flag map + the demo toggle.
 *   'live' — at least one of the mode's source keys reported live (real backend data)
 *   'seed' — demo is on but no source is live (showing the seeded mock)
 *   null   — the mode has no backend-source mapping, or nothing is showing (ModeEmpty)
 */
export function liveSourceState(mode, demo, live, keys) {
  const k = (keys || {})[mode];
  if (!k) return null;
  if (live && k.some((key) => live[key])) return 'live';
  return demo ? 'seed' : null;
}

export function LiveSourceChip({ state }) {
  if (state !== 'live' && state !== 'seed') return null;
  const isLive = state === 'live';
  const c = isLive ? 'var(--green)' : 'var(--amber)';
  return (
    <div
      title={isLive ? 'Live data from the backend' : 'Seeded demo data — not live'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, alignSelf: 'flex-start',
        margin: '0 0 8px', fontFamily: 'var(--font-mono)', fontSize: 9.5,
        letterSpacing: '.08em', color: c, border: `1px solid ${c}`,
        borderRadius: 3, padding: '1px 6px',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: c }} />
      {isLive ? 'LIVE' : 'SEED'}
    </div>
  );
}
