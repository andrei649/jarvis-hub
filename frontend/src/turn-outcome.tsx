import React from 'react';

/** Optional, per-turn metrics delivered with a completed chat response. */
export type TurnOutcome = { latency_ms: number };

/** Treat an untrusted SSE projection as unavailable unless its duration is measured. */
export function turnOutcome(value: unknown): TurnOutcome | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const duration = (value as Record<string, unknown>).latency_ms;
  return typeof duration === 'number' && Number.isFinite(duration) && duration >= 0
    ? { latency_ms: duration } : null;
}

function durationText(ms: number): string {
  if (ms === 0) return '0 ms';
  if (ms < 1000) return `${Math.max(1, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(2).replace(/\.?0+$/, '')} s`;
}

/** This is whole-turn wall time, including orchestration; it is not model speed. */
export function StatusStrip({ outcome }: { outcome?: TurnOutcome | null }) {
  if (!outcome) return null;
  return <output aria-label="Turn duration" style={{ display: 'block', padding: '4px 8px',
    color: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
    Turn duration: {durationText(outcome.latency_ms)}
  </output>;
}
