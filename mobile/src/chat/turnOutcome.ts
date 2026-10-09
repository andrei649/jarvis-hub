/** One completed native chat turn's server-selected duration. Never persisted. */
export type TurnOutcome = { latency_ms: number };

/** Project only an exact, JSON-safe duration from an untrusted SSE end value. */
export function normalizeTurnOutcome(value: unknown): TurnOutcome | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)
    || !Object.prototype.hasOwnProperty.call(value, 'latency_ms')) return null;
  const milliseconds = (value as Record<string, unknown>).latency_ms;
  return typeof milliseconds === 'number' && Number.isSafeInteger(milliseconds) && milliseconds >= 0
    ? { latency_ms: milliseconds } : null;
}
