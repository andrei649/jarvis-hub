import React from 'react';
import { CommsMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;

/* CommsMode embeds the live RoomsPanel (GET /api/rooms) in the reading pane —
   shimmed with a realistic multi-agent room list so the real panel renders real
   data end-to-end in both stories. */
const ROUTES: Record<string, unknown> = {
  '/api/rooms': {
    rooms: [
      { id: 'ops', name: 'ops-room', agents: ['jarvis', 'pepper', 'stark'] },
      { id: 'research', name: 'research', agents: ['vision', 'athena'] },
      { id: 'family', name: 'family', agents: ['frigga'] },
    ],
  },
};
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(ROUTES, path)) {
    return Promise.resolve(new Response(JSON.stringify(ROUTES[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

/* The DS narrows .comms-body's thread list below its 1300px desktop media query;
   re-assert the 340px desktop column scoped to this 1240px stage (wave-1
   ContextColumn recipe). Suggested config fix: viewport wider than 1300px. */
const DESKTOP_GRID = '.dsx-comms .comms-body{grid-template-columns:340px 1fr;}';
const stage: React.CSSProperties = { width: 1240, height: 760, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.66 } as React.CSSProperties;

/** Unified inbox — channel filters, threads handled per-agent (on-device/outbound tags), reading pane with governed reply controls + live rooms. */
export function UnifiedInbox() {
  return (
    <div className="hud-root dsx-comms" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <CommsMode t={T} />
    </div>
  );
}

/** Email channel focused via the real filter chip; the un-linked email thread shows reply honestly disabled. */
export function EmailFocus() {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;
    // Real DOM events on the real component (wave-1 staging rule) — filter to
    // Email, then select the first (unread Raiffeisen) thread in the filtered list.
    const t1 = setTimeout(() => {
      const chip = Array.from(root.querySelectorAll('.comms-filters .cf'))
        .find((b) => (b.textContent || '').startsWith('Email')) as HTMLElement | undefined;
      if (chip) chip.click();
      setTimeout(() => {
        const row = root.querySelector('.comms-row') as HTMLElement | null;
        if (row) row.click();
      }, 40);
    }, 40);
    return () => clearTimeout(t1);
  }, []);
  return (
    <div ref={ref} className="hud-root dsx-comms" style={stage}>
      <style>{DESKTOP_GRID}</style>
      <CommsMode t={T} />
    </div>
  );
}
