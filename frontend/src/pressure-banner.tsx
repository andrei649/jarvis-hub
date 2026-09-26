/* H161 — the box is running out of memory or disk. The hub ranks five conditions
   (disk critical, memory critical, a suspected out-of-memory restart, disk elevated,
   memory elevated) and answers the worst one the owner has not dismissed; this banner
   shows only that one, with a dismiss that lasts for this boot of the machine (a new
   boot, or the condition clearing and coming back, raises it again). The state comes
   from GET /api/system/pressure, polled. */
import React, { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost } from './api/client';

export interface PressurePath { path: string; percent: number }
export interface PressureCondition { condition: string; percent: number | null; paths: PressurePath[] }
export interface PressureState { bootId: string | null; worst: PressureCondition | null }

export const PRESSURE_NONE: PressureState = { bootId: null, worst: null };

const KNOWN = new Set(['disk_critical', 'memory_critical', 'oom_restart_suspected', 'disk_elevated', 'memory_elevated']);
const POLL_MS = 60_000;

const pct = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : null;

/** The hub's answer as the HUD holds it; anything malformed is "nothing to say". */
export function readPressure(raw: unknown): PressureState {
  if (!raw || typeof raw !== 'object') return PRESSURE_NONE;
  const r = raw as { boot_id?: unknown; worst?: unknown };
  const w = r.worst as { condition?: unknown; percent?: unknown; paths?: unknown } | null | undefined;
  if (typeof r.boot_id !== 'string' || !w || typeof w !== 'object'
      || typeof w.condition !== 'string' || !KNOWN.has(w.condition)) return PRESSURE_NONE;
  const paths = Array.isArray(w.paths)
    ? w.paths.flatMap((p: any) => (p && typeof p.path === 'string' && pct(p.percent) !== null
      ? [{ path: p.path.slice(0, 120), percent: pct(p.percent) as number }] : [])).slice(0, 4)
    : [];
  return { bootId: r.boot_id.slice(0, 80), worst: { condition: w.condition, percent: pct(w.percent), paths } };
}

function where(c: PressureCondition): string {
  const first = c.paths[0];
  return first ? `${first.path} at ${first.percent}%` : `${c.percent ?? '?'}% used`;
}

/** One sentence for the condition. */
export function pressureText(c: PressureCondition): string {
  switch (c.condition) {
    case 'disk_critical':
      return `Disk almost full: ${where(c)}. Free some space, or the hub may stop saving your data.`;
    case 'memory_critical':
      return `Memory almost exhausted: ${c.percent ?? '?'}% in use. The local model or the hub may be stopped by the system.`;
    case 'oom_restart_suspected':
      return 'The hub restarted after running short of memory (suspected out-of-memory stop).';
    case 'disk_elevated':
      return `Disk filling up: ${where(c)}.`;
    default:
      return `Memory running high: ${c.percent ?? '?'}% in use.`;
  }
}

export function PressureBanner({ state, onDismiss }: {
  state: PressureState; onDismiss: (condition: string, bootId: string) => void;
}) {
  const w = state.worst;
  if (!w || !state.bootId) return null;
  const alarm = w.condition !== 'disk_elevated' && w.condition !== 'memory_elevated';
  const bootId = state.bootId;
  return (
    <div role={alarm ? 'alert' : 'status'} data-testid="pressure-banner"
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, flexWrap: 'wrap', padding: '4px 12px',
        borderBottom: `1px solid ${alarm ? 'rgba(239,68,68,.5)' : 'rgba(245,158,11,.45)'}`,
        fontFamily: 'var(--font-mono)', fontSize: 10.5, letterSpacing: '.04em',
        color: alarm ? 'var(--red, #ef4444)' : 'var(--amber, #f59e0b)' }}>
      <span>{pressureText(w)}</span>
      <button className="tool-btn" onClick={() => onDismiss(w.condition, bootId)}>Dismiss</button>
    </div>
  );
}

/** The live pressure state, polled, and a dismiss that answers with the new state. */
export function usePressure(demo: boolean): [PressureState, (condition: string, bootId: string) => void] {
  const [state, setState] = useState<PressureState>(PRESSURE_NONE);
  useEffect(() => {
    if (demo) { setState(PRESSURE_NONE); return undefined; }
    let live = true;
    const load = () => {
      apiGet<unknown>('/api/system/pressure')
        .then((raw) => { if (live) setState(readPressure(raw)); })
        .catch(() => { /* hub down or refused: keep the last state */ });
    };
    load();
    const iv = setInterval(load, POLL_MS);
    return () => { live = false; clearInterval(iv); };
  }, [demo]);
  const dismiss = useCallback((condition: string, bootId: string) => {
    setState((s) => (s.worst && s.worst.condition === condition ? PRESSURE_NONE : s));
    apiPost<unknown>('/api/system/pressure/dismiss', { condition, boot_id: bootId })
      .then((raw) => setState(readPressure(raw)))
      .catch(() => { /* refused (another boot, already clear): the next poll says what is true */ });
  }, []);
  return [state, dismiss];
}
