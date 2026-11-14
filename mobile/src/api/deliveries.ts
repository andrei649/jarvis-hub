import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

export const DELIVERY_PATH = '/api/channels/deliveries?limit=50';
export const DELIVERY_STATES = ['sent', 'failed', 'partial', 'unknown', 'pending', 'attempting', 'skipped'] as const;
export type DeliveryState = typeof DELIVERY_STATES[number];
export type DeliveryReceipt = { id: string; channel: string; target: string; state: DeliveryState;
  attempt: number; chars: number; created: number; updated: number; keyed: boolean };
export type DeliverySnapshot = { stats: { byState: Record<DeliveryState, number>; deadTargets: number };
  deliveries: DeliveryReceipt[]; deadTargetsTruncated: boolean;
  retention: { windowSeconds: number; protectedLimit: number; protectedCount: number;
    retentionSeconds: number; ordinaryRowLimit: number } };

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const label = (value: unknown, max: number): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max;
const stamp = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0
  && Number.isFinite(value * 1000) && value * 1000 <= 8_640_000_000_000_000;

function checkedSnapshot(value: unknown): DeliverySnapshot | null {
  if (!object(value) || !object(value.stats) || !object(value.stats.by_state)
    || !object(value.retention) || !Array.isArray(value.deliveries)
    || value.deliveries.length > 50 || typeof value.dead_targets_truncated !== 'boolean') return null;
  const byState = {} as Record<DeliveryState, number>;
  for (const state of DELIVERY_STATES) {
    const number = value.stats.by_state[state];
    if (!count(number)) return null;
    byState[state] = number;
  }
  const retention = value.retention;
  if (!count(value.stats.dead_targets)
    || !count(retention.window_seconds) || retention.window_seconds === 0
    || !count(retention.protected_limit) || !count(retention.protected_count)
    || !count(retention.retention_seconds) || retention.retention_seconds === 0
    || !count(retention.ordinary_row_limit)) return null;
  const ids = new Set<string>();
  const deliveries: DeliveryReceipt[] = [];
  for (const raw of value.deliveries) {
    if (!object(raw) || !label(raw.id, 64) || ids.has(raw.id)
      || !label(raw.channel, 32) || !label(raw.target, 128)
      || !DELIVERY_STATES.includes(raw.state as DeliveryState)
      || !count(raw.attempt) || raw.attempt === 0
      || (raw.error !== null && raw.error !== undefined && !label(raw.error, 40))
      || !count(raw.chars) || !stamp(raw.created) || !stamp(raw.updated)
      || typeof raw.keyed !== 'boolean') return null;
    ids.add(raw.id);
    deliveries.push({ id: raw.id, channel: raw.channel, target: raw.target,
      state: raw.state as DeliveryState, attempt: raw.attempt, chars: raw.chars,
      created: raw.created, updated: raw.updated, keyed: raw.keyed });
  }
  return { stats: { byState, deadTargets: value.stats.dead_targets }, deliveries,
    deadTargetsTruncated: value.dead_targets_truncated,
    retention: { windowSeconds: retention.window_seconds, protectedLimit: retention.protected_limit,
      protectedCount: retention.protected_count, retentionSeconds: retention.retention_seconds,
      ordinaryRowLimit: retention.ordinary_row_limit } };
}

/** One owner-scoped, read-only snapshot. No retry or response body is exposed on failure. */
export async function fetchDeliveries(config: ServerConfig, signal: AbortSignal): Promise<DeliverySnapshot> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No hub connected');
  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) abort.abort();
  if (abort.signal.aborted) {
    signal.removeEventListener('abort', cancel);
    throw new ApiError('Delivery receipt request cancelled or timed out');
  }
  const timer = setTimeout(cancel, 15000);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
    if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
    const response = await fetch(base + DELIVERY_PATH, { method: 'GET', headers,
      signal: abort.signal, cache: 'no-store', redirect: 'error' });
    if (abort.signal.aborted) throw new ApiError('Delivery receipt request cancelled or timed out');
    if (!response.ok) throw new ApiError('Delivery receipts unavailable', response.status);
    const data = await response.json();
    if (abort.signal.aborted) throw new ApiError('Delivery receipt request cancelled or timed out');
    const snapshot = checkedSnapshot(data);
    if (!snapshot) throw new ApiError('Invalid delivery receipts');
    return snapshot;
  } catch (error) {
    if (abort.signal.aborted) throw new ApiError('Delivery receipt request cancelled or timed out');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Delivery receipts unavailable');
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}
