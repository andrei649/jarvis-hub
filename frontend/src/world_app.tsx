import { logicalPath } from './base-path';
import React, { useEffect, useCallback, lazy } from 'react';
import App from './app';
import { V2 } from './data';
import { Icon, ICONS } from './ui';
import { useHudRoute, navigateHud, closeHudOverlay } from './hud-routing';
import { RouteBoundary } from './route-boundary';
import { bindings, loadOverrides, matchAction } from './shortcuts';
const WorldIntelligenceMode = lazy(() => import('./modes_world').then(m => ({ default: m.WorldIntelligenceMode })));

/* The bottom-left WORLD button's geometry, and the strip the mode rail gives up for it.
   Exported so the reservation can be proved as arithmetic: jsdom performs no layout, so
   an overlap assertion there would compare two zero-sized rectangles and pass whatever
   the CSS said. What IS checkable, and is what actually prevents the overlap, is that
   the reserved strip is at least as tall as the button plus both its insets. */
export const WORLD_BUTTON_INSET = 16;
/* Pinned rather than measured, and the button is given this height explicitly: a
   reservation computed from a height the CSS is free to change is not a reservation.
   30px is `.tool-btn`'s own box at this font size (10px text, 7px padding, 1px border),
   and the label is the literal string "WORLD" — not translated, so it cannot wrap and
   grow past what is reserved. */
export const WORLD_BUTTON_HEIGHT = 30;
export const RAIL_RESERVED_PX = WORLD_BUTTON_INSET * 2 + WORLD_BUTTON_HEIGHT;

function WorldAwareApp() {
  const { route } = useHudRoute();
  const open = route.mode === 'world';
  const setOpen = useCallback((next: boolean) => {
    if (next) navigateHud('/v2/world');
    else closeHudOverlay();
  }, []);

  useEffect(() => {
    function onKey(e) {
      const tag = (e.target && e.target.tagName ? e.target.tagName : '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;
      if (matchAction(e, bindings(loadOverrides()), 'global')?.id === 'view.world') setOpen(true);   // H209
      if (e.key === 'Escape' && logicalPath(window.location.pathname) === '/v2/world') setOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => { const handoff = () => navigateHud('/v2/chat'); window.addEventListener('nerva-desktop-handoff', handoff); return () => window.removeEventListener('nerva-desktop-handoff', handoff); }, []);

  const t = V2.I18N.en;

  return (
    <>
      {/* The WORLD button is `position: fixed` in the bottom-left corner, and the mode
          rail is a column of 46px buttons down that same left edge (styles.css `.rail`).
          On a 1440x900 laptop the rail's sixteen buttons reach the bottom of the
          viewport, so the button was painting ON TOP of the last one or two rail
          entries — `comms` and `admin` — and taking their clicks. A fixed element cannot
          be laid out around; the only fix that actually frees the pixels is to RESERVE
          them, so the rail is given a bottom pad at least as tall as the button's own
          footprint and the button sits inside that reserved strip.

          Injected here rather than added to styles.css because the strip exists only
          because THIS entry point renders that button: a HUD built without it should not
          carry a gap for a control it does not have. Scoped to `.rail` — `ia` is a
          `const 'rail'` in app.tsx, so the tabs layout is unreachable today; if it ever
          becomes reachable this reservation has to grow a `.tabs` case, and the test
          pins the arithmetic rather than the selector so that stays a visible decision. */}
      <style>{`.rail { padding-bottom: ${RAIL_RESERVED_PX}px; }`}</style>
      <App />
      <button
        className="tool-btn"
        onClick={() => setOpen(true)}
        title="World Intelligence (W)"
        style={{ position: 'fixed', left: WORLD_BUTTON_INSET, bottom: WORLD_BUTTON_INSET, zIndex: 60, height: WORLD_BUTTON_HEIGHT, borderColor: 'var(--accent-dim)', color: 'var(--accent-light)' }}
      >
        <Icon d={ICONS.globe} size={13}/> WORLD
      </button>
      {open && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(4,7,14,.96)', padding: 'var(--gap)', display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}
        >
          <div className="panel" style={{ flex: '0 0 auto' }}>
            <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
            <div className="panel-head">
              <Icon d={ICONS.globe} size={14}/><span className="ttl">WORLD INTELLIGENCE</span>
              <span className="st">Signal Layer · WorldView · Argus</span>
              <button className="tool-btn" style={{ marginLeft: 10 }} onClick={() => setOpen(false)}>close · esc</button>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <RouteBoundary routeKey={`${route.path}:${window.location.search}`}><WorldIntelligenceMode t={t} /></RouteBoundary>
          </div>
        </div>
      )}
    </>
  );
}

export default WorldAwareApp;
