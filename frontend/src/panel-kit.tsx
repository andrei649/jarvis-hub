/* panel-kit — the shared Console panel primitives, extracted verbatim from gap.tsx.

   gap.tsx had grown to 4.6k lines with every panel and every primitive in one file, so
   two panels could never be written in parallel without colliding. The primitives are
   unchanged here — same markup, same styles, same semantics — they are only exported so a
   panel can live in its own module (the pattern `operator-panel.tsx` already uses) and
   still look identical to the ones that stayed behind.

   The HUD parity gate globs every .tsx under frontend/src, so a panel in its own file
   counts as a real caller exactly like an inline one. */
import React, { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost } from './api/client';

export function useApi(path, auto = true, admin = false) {
  const [d, setD] = useState(null);
  const [e, setE] = useState(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    apiGet(path, admin ? { admin: true } : undefined).then((r) => { setD(r); setE(null); }).catch((err) => setE(err?.message || 'offline')).finally(() => setLoading(false));
  }, [path, admin]);
  useEffect(() => { if (auto) reload(); }, [auto, reload]);
  return { d, e, loading, reload };
}
export const arr = (x, ...k) => (Array.isArray(x) ? x : (k.map((kk) => x && x[kk]).find(Array.isArray) || []));
export const mono = { fontFamily: 'var(--font-mono)', fontSize: 11 };

/* Per-panel LIVE/SEED honesty chip (TASK-2 tail). Distinct from LiveSourceChip
   (mode-level, block-positioned under a header) — this is inline-sized for the
   panel-head flex row. Same color/wording convention: green LIVE = the panel's
   `enabled`-style flag is on (or the surface has no such flag and simply loaded
   real data), amber SEED = present but not collecting yet. Renders nothing until
   the panel has actually loaded (`live` undefined) so it never guesses. */
export const asLive = (loaded: any, enabled?: any): 'live' | 'seed' | undefined => {
  if (!loaded) return undefined;
  if (enabled === undefined) return 'live';
  return enabled ? 'live' : 'seed';
};

export function PanelChip({ live }: { live?: 'live' | 'seed' | null }) {
  if (live !== 'live' && live !== 'seed') return null;
  const isLive = live === 'live';
  const c = isLive ? 'var(--green)' : 'var(--amber)';
  return (
    <span
      title={isLive ? 'Live data from the backend' : 'Seeded/disabled — not live'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '.06em',
        color: c, border: `1px solid ${c}`, borderRadius: 3, padding: '0 5px',
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c }} />
      {isLive ? 'LIVE' : 'SEED'}
    </span>
  );
}

export function Card({ title, sub, live, onReload, children }: { title?: any; sub?: any; live?: any; onReload?: any; children?: any }) {
  return (
    <div className="panel" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <span className="ttl">{title}</span>
        <PanelChip live={live} />
        {sub != null && <span className="st">{sub}</span>}
        {onReload && <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={onReload} title="reload">↻</button>}
      </div>
      <div className="panel-body tight" tabIndex={0}>{children}</div>
    </div>
  );
}
export const State = ({ e, loading, n }) => (loading ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>loading…</div>
  : e ? <div style={{ color: 'var(--amber)', fontSize: 12 }}>offline · {e}</div>
  : n === 0 ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>nothing yet</div> : null);
export const Row = ({ children }) => <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>{children}</div>;
export const Tag = ({ c, children }: { c?: any; children?: any }) => <span style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: c || 'var(--ink-3)' }}>{children}</span>;
export const Btn = ({ onClick, children }) => <button className="tool-btn" onClick={onClick} style={{ marginLeft: 'auto' }}>{children}</button>;
export const act = (p, body, then?, onErr?) => apiPost(p, body)
  .then(then || (() => {}))
  .catch((err) => { if (onErr) onErr(err); });
// `onErr` is OPTIONAL but matters: without it a failed admin action is invisible. Engaging
// the kill-switch is kernel-mediated and answers 403 "kernel denied" without a capability
// token, so the 2026-07-27 QA run pressed HALT ALL, got no error, no state change and no
// hint it had been refused — the card kept reading "ARMED · operational". Any call site
// that drives a safety or governance control MUST pass onErr and show it.
export const actA = (p, body, then, onErr?) => apiPost(p, body, { admin: true })
  .then(then || (() => {}))
  .catch((err) => { if (onErr) onErr(err); });
export const inpS = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11 };
export const taS = { width: '100%', minHeight: 64, background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono };
export const Json = ({ v, max = 220 }) => (v == null ? null
  : <pre style={{ ...mono, fontSize: 10, lineHeight: 1.45, whiteSpace: 'pre-wrap', maxHeight: max, overflow: 'auto', margin: '6px 0 0', padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4, color: 'var(--ink-2)' }}>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</pre>);
