/* Owner receipt history. The server records metadata, never message bodies. */
import React from 'react';
import { mono, useApi } from '../panel-kit';

export const CHANNEL_DELIVERIES_PATH = '/api/channels/deliveries?limit=50';

const STATES = ['sent', 'failed', 'partial', 'unknown', 'pending', 'attempting', 'skipped'] as const;
type DeliveryState = typeof STATES[number];
type Receipt = { id: string; channel: string; target: string; state: DeliveryState;
  attempt: number; error: string | null; chars: number; created: number; updated: number; keyed: boolean };
type View = { stats: { by_state: Record<DeliveryState, number>; dead_targets: number };
  deliveries: Receipt[]; dead_targets_truncated: boolean;
  retention: { window_seconds: number; protected_limit: number; protected_count: number;
    retention_seconds: number; ordinary_row_limit: number } };

const DESCRIPTION: Record<DeliveryState, string> = {
  sent: 'Platform acknowledged all parts; recipient reading is not confirmed.',
  failed: 'Platform refused the send, or transport never started.',
  partial: 'Some parts may have been accepted.',
  unknown: 'May have arrived; automatic resend is off.',
  pending: 'Recorded before sending; later status may be unavailable.',
  attempting: 'Attempt recorded; delivery may be in progress or uncertain.',
  skipped: 'No send for this row: a duplicate, dead target, or exhausted attempts.',
};

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const text = (value: unknown, max: number): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max;
const stamp = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 8_640_000_000_000;

function checkedView(value: unknown): View | null {
  if (!record(value) || !record(value.stats) || !record(value.stats.by_state)
      || !record(value.retention) || !Array.isArray(value.deliveries)
      || value.deliveries.length > 50 || typeof value.dead_targets_truncated !== 'boolean') return null;
  const stats = value.stats;
  const retention = value.retention;
  if (!count(stats.dead_targets) || !STATES.every((state) => count((stats.by_state as Record<string, unknown>)[state]))) return null;
  if (!count(retention.window_seconds) || retention.window_seconds === 0
      || !count(retention.protected_limit) || !count(retention.protected_count)
      || !count(retention.retention_seconds) || retention.retention_seconds === 0
      || !count(retention.ordinary_row_limit)) return null;
  const ids = new Set<string>();
  for (const row of value.deliveries) {
    if (!record(row) || !text(row.id, 64) || ids.has(row.id)
        || !text(row.channel, 32) || !text(row.target, 128)
        || !STATES.includes(row.state as DeliveryState)
        || !count(row.attempt) || row.attempt === 0
        || (row.error !== null && row.error !== undefined && !text(row.error, 40))
        || !count(row.chars) || !stamp(row.created) || !stamp(row.updated)
        || typeof row.keyed !== 'boolean') return null;
    ids.add(row.id);
  }
  return value as View;
}

function duration(seconds: number): string {
  if (seconds % 86_400 === 0) return `${seconds / 86_400} day${seconds === 86_400 ? '' : 's'}`;
  if (seconds % 3_600 === 0) return `${seconds / 3_600} hour${seconds === 3_600 ? '' : 's'}`;
  return `${seconds} seconds`;
}

export function ChannelDeliveriesPanel() {
  const { d, e, status, loading, reload } = useApi(CHANNEL_DELIVERIES_PATH, true, true);
  // useApi retains the previous payload after a failed refresh. Never show it once
  // the current read failed (especially after an owner credential is revoked).
  const view = !e && !loading ? checkedView(d) : null;
  const failure = e && (status === 401 || status === 403 ? 'owner access required'
    : status === 503 ? 'delivery ledger unavailable' : 'delivery receipts unavailable');

  return (
    <section aria-label="Delivery receipts" style={{ marginTop: 12, borderTop: '1px solid var(--panel-line)', paddingTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ ...mono, fontSize: 11 }}>DELIVERY RECEIPTS</strong>
        <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={reload}>refresh receipts</button>
      </div>
      {loading && <div role="status">Checking delivery receipts…</div>}
      {failure && <div role="status" style={{ color: 'var(--amber)' }}>{failure}</div>}
      {!loading && !e && d !== null && !view && (
        <div role="status" style={{ color: 'var(--amber)' }}>Delivery receipts could not be checked from this response.</div>
      )}
      {view && <>
        <p style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>
          Recent 50 receipt rows only; counts describe retained rows, not all sends. Duplicate-protection records:
          {' '}{view.retention.protected_count} of {view.retention.protected_limit} occupied; when full, new sends
          requiring this protection are withheld. The ordinary row budget is {view.retention.ordinary_row_limit};
          protected and open attempts can extend the total. Ordinary retention is
          {' '}{duration(view.retention.retention_seconds)}; keyed duplicate protection lasts
          {' '}{duration(view.retention.window_seconds)}. Records can expire or be refused at capacity.
          No message bodies are stored here.
        </p>
        <ul aria-label="retained delivery states" style={{ listStyle: 'none', padding: 0, margin: '7px 0' }}>
          {STATES.map((state) => <li key={state} style={{ fontSize: 10.5, padding: '2px 0' }}>
            <span style={mono}>{state}</span> {view.stats.by_state[state]} · {DESCRIPTION[state]}
          </li>)}
        </ul>
        <div style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>
          {view.stats.dead_targets} dead targets{view.dead_targets_truncated ? ' (server list truncated)' : ''}.
          Receipts never trigger automatic redelivery.
        </div>
        {view.deliveries.length === 0
          ? <p>No receipt rows returned for this read.</p>
          : <ol aria-label="recent delivery receipts" style={{ paddingLeft: 20, margin: '8px 0' }}>
              {view.deliveries.map((row) => <li key={row.id} style={{ fontSize: 10.5, padding: '3px 0' }}>
                <span style={mono}>{row.id}</span> · {row.channel} → {row.target} · {row.state}
                {' · '}attempt {row.attempt} · {row.chars} characters · {new Date(row.updated * 1000).toLocaleString()}
                {row.error ? ` · ${row.error}` : ''}
              </li>)}
            </ol>}
      </>}
    </section>
  );
}
