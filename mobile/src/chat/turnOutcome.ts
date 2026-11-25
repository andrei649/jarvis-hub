export type ToolActivity = { proposed: number; queued: number; executed: number | null;
  failures: number | null; basis: 'observed' | 'unknown' };
export type TurnOutcome = { latency_ms?: number; tools?: ToolActivity };

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 1_000_000;
}

/** The hub counts agent tool invocations; individual external effects have separate receipts. */
export function toolActivity(value: unknown): ToolActivity | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).sort().join(',') !== 'basis,executed,failures,proposed,queued') return;
  const { proposed, queued, executed, failures, basis } = value as Record<string, unknown>;
  if (!count(proposed) || !count(queued)) return;
  if (basis === 'observed' && count(executed) && count(failures)) return { proposed, queued, executed, failures, basis };
  if (basis === 'unknown' && (executed === null || count(executed)) && failures === null)
    return { proposed, queued, executed, failures, basis };
}

export function normalizeTurnOutcome(value: unknown): TurnOutcome | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const tools = toolActivity(raw.tools);
  const milliseconds = raw.latency_ms;
  const outcome: TurnOutcome = tools ? { tools } : {};
  if (Object.prototype.hasOwnProperty.call(value, 'latency_ms') && typeof milliseconds === 'number'
    && Number.isSafeInteger(milliseconds) && milliseconds >= 0) outcome.latency_ms = milliseconds;
  return Object.keys(outcome).length ? outcome : null;
}
