/* H182 — the machine's power state in the HUD: on battery (and whether the heavy
   background jobs are being deferred), a recent resume from sleep, and the keep-awake
   hold (JARVIS_KEEP_AWAKE: holding, ready, or refused and why). A plugged-in machine
   with keep-awake off shows nothing. The state comes from GET /api/power, polled, and
   GET /api/power/stream where the browser can attach to it (EventSource sends no token,
   so that only works where the guard exempts localhost; the poll covers the rest). */
import React, { useEffect, useState } from 'react';
import { apiGet } from './api/client';
import { appUrl } from './base-path';

export interface KeepAwakeState {
  enabled: boolean;
  active: boolean;
  refused: string | null;
  error: string | null;
}

export interface PowerState {
  onBattery: boolean;
  percent: number | null;
  deferred: boolean;
  resumedAt: number | null;   // epoch seconds
  keepAwake: KeepAwakeState;
}

export const POWER_UNKNOWN: PowerState = {
  onBattery: false, percent: null, deferred: false, resumedAt: null,
  keepAwake: { enabled: false, active: false, refused: null, error: null },
};

const POLL_MS = 60_000;

const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 200) : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The hub's `/api/power` payload (or a stream frame) as the HUD holds it; anything
 *  malformed reads as "nothing to say". */
export function readPower(raw: unknown): PowerState {
  if (!raw || typeof raw !== 'object') return POWER_UNKNOWN;
  const r = raw as any;
  const p = r.power && typeof r.power === 'object' ? r.power : {};
  const k = r.keep_awake && typeof r.keep_awake === 'object' ? r.keep_awake : {};
  const percent = num(p.percent);
  return {
    onBattery: p.on_battery === true,
    percent: percent === null ? null : Math.max(0, Math.min(100, Math.round(percent))),
    deferred: r.background_deferred === true,
    resumedAt: num(p.resumed_at),
    keepAwake: {
      enabled: k.enabled === true,
      active: k.active === true,
      refused: text(k.refused),
      error: text(k.error),
    },
  };
}

function clock(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** What the chip says, piece by piece; empty when there is nothing to say. */
export function powerLabels(s: PowerState): string[] {
  const out: string[] = [];
  if (s.onBattery) {
    out.push(`on battery${s.percent === null ? '' : ` ${s.percent}%`}`
      + (s.deferred ? ' · background jobs deferred' : ''));
  }
  if (s.resumedAt !== null) out.push(`woke from sleep at ${clock(s.resumedAt)}`);
  const k = s.keepAwake;
  if (k.enabled) {
    if (k.refused) out.push(`keep-awake off: ${k.refused}`);
    else if (k.error) out.push(`keep-awake: ${k.error}`);
    else out.push(k.active ? 'keeping the machine awake' : 'keep-awake ready');
  }
  return out;
}

export function PowerChip({ state }: { state: PowerState }) {
  const labels = powerLabels(state);
  if (!labels.length) return null;
  const warn = state.deferred || !!state.keepAwake.refused || !!state.keepAwake.error;
  return (
    <div role="status" data-testid="power-chip"
      style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap', padding: '2px 12px',
        fontFamily: 'var(--font-mono)', fontSize: 10.5, letterSpacing: '.06em',
        color: warn ? 'var(--amber, #f59e0b)' : 'var(--dim, #94a3b8)' }}>
      {labels.map((label) => <span key={label}>{label}</span>)}
    </div>
  );
}

/** The live power state: polled, and pushed by the stream where it attaches. */
export function usePower(demo: boolean): PowerState {
  const [state, setState] = useState<PowerState>(POWER_UNKNOWN);
  useEffect(() => {
    if (demo) { setState(POWER_UNKNOWN); return undefined; }
    let live = true;
    const load = () => {
      apiGet<unknown>('/api/power')
        .then((raw) => { if (live) setState(readPower(raw)); })
        .catch(() => { /* hub down or refused: keep the last state */ });
    };
    load();
    const iv = setInterval(load, POLL_MS);
    let es: EventSource | null = null;
    if (typeof EventSource !== 'undefined') {
      try { es = new EventSource(appUrl('/api/power/stream')); } catch { es = null; }
      if (es) {
        es.onmessage = (ev) => {
          try {
            const frame = JSON.parse(ev.data);
            if (live && frame && frame.type === 'power') setState(readPower(frame));
          } catch { /* malformed frame — ignore */ }
        };
        es.onerror = () => { try { es?.close(); } catch { /* ignore */ } };
      }
    }
    return () => { live = false; clearInterval(iv); try { es?.close(); } catch { /* ignore */ } };
  }, [demo]);
  return state;
}
