/* H262 — retention asks a person before it deletes deeper.

   A settings write that would make retention delete more than the last approved setting
   is not written: the hub sends its retention keys to the approval queue as an
   irreversible (tier 3) task and answers 202 with the task id and the gated keys. The
   Settings panel says so ("sent to Approvals"), never "saved".

   - RetentionBanner sits in the Retention category. Retention switched on with nothing
     approved yet deletes nothing (the sweep clamps to the approved snapshot, and there is
     none), so the banner says that and offers Confirm: the stored retention values sent
     again, which queues them for a person to accept (GET /api/admin/retention says
     whether one is awaited). A card already waiting (`pending_task`) replaces Confirm with
     a pointer to Approvals, so a reload never queues a second one.
   - RetentionCard is the Decision Inbox's view of such a task: the horizons before and
     after, the kinds of data it deepens, and what it would delete per kind — a count that
     reached the hub's limit is a lower bound ("500+"), a kind the hub cannot count says so.
     Every archived chat past the new horizon counts, however recently it was archived: the
     sweeps of the next 7 days (the grace) delete them all.
   - saveOrder puts `retention` before `memory` in a Settings save (review round 2). */
import React, { useEffect, useState } from 'react';
import { apiPut } from '../api/client';
import { mono, refusalReason, useApi } from '../panel-kit';

export const RETENTION_STATE_PATH = '/api/admin/retention';
export const RETENTION_SETTINGS_PATH = '/api/admin/settings/retention';
/** The approval-queue kind a deeper retention write becomes (agents/core/retention.py). */
export const RETENTION_KIND = 'settings.retention';

/** The retention category's own retention keys as the hub stores them (`current` of the
    state route, `{"retention.enabled": true, …}`), as a PUT body's values. */
export function retentionConfirmValues(current: any): Record<string, any> {
  const out: Record<string, any> = {};
  if (!current || typeof current !== 'object') return out;
  for (const [name, value] of Object.entries(current)) {
    if (name.startsWith('retention.')) out[name.slice('retention.'.length)] = value;
  }
  return out;
}

/** The order a save sends its dirty categories in: `retention` before `memory` (review
    round 2). The hub judges each write against what is stored, never a waiting card, so
    a memory write (archiving on) that goes to Approvals must come after the retention
    write it depends on — its card then previews the horizons that will be in force, and
    an accept applies instead of being refused as changed since the request. */
export function saveOrder(cats: string[]): string[] {
  const rank = (c: string) => (c === 'retention' ? 0 : c === 'memory' ? 1 : 2);
  return cats.map((c, i) => [c, i] as [string, number])
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([c]) => c);
}

/** "sent to Approvals · a, b · task 42": what a 202 queued, and where to decide it. */
export function approvalNote(r: any): string {
  const gated = Array.isArray(r?.gated) ? r.gated.map(String) : [];
  return `sent to Approvals · ${gated.join(', ') || 'retention settings'}${r?.pending != null ? ` · task ${r.pending}` : ''}`
    + ' — a person accepts it in the Decision Inbox';
}

/** A refusal as a person reads it: the body's `reason` (why the queue could not take it,
    what a refused undo needs), then its `error`, then the generic fallback. */
export function refusedWhy(err: any, fallback = 'refused'): string {
  for (const key of ['reason', 'error']) {
    const v = err?.body?.[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return refusalReason(err, fallback);
}

export function RetentionBanner({ refresh = 0 }: { refresh?: number }) {
  const { d, reload } = useApi(RETENTION_STATE_PATH, true, true);
  const [sent, setSent] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (refresh) reload(); }, [refresh]); // eslint-disable-line
  if (!d || (d as any).awaiting_approval !== true) return null;
  const waiting = (d as any).pending_task;
  const confirm = () => {
    setBusy(true); setError('');
    apiPut(RETENTION_SETTINGS_PATH, { values: retentionConfirmValues((d as any).current) }, { admin: true })
      .then((r: any) => { if (r?.pending != null) setSent(approvalNote(r)); else reload(); })
      .catch((err) => setError(`not sent · ${refusedWhy(err)}`))
      .finally(() => setBusy(false));
  };
  return <div data-testid="retention-unconfirmed" style={{ fontSize: 11, color: 'var(--ink-2)', margin: '2px 0 6px',
    padding: '5px 7px', border: '1px solid var(--amber)', borderRadius: 4 }}>
    <div><span style={{ color: 'var(--amber)' }}>Retention is on but not confirmed</span>: it deletes nothing until a
      person approves these settings once. Confirming sends them to Approvals.</div>
    {!sent && waiting != null
      ? <div data-testid="retention-confirm-waiting" role="status" style={{ ...mono, fontSize: 10, marginTop: 4 }}>
          waiting in Approvals · task {String(waiting)} — a person accepts it in the Decision Inbox</div>
      : sent
      ? <div data-testid="retention-confirm-sent" role="status" style={{ ...mono, fontSize: 10, marginTop: 4 }}>{sent}</div>
      : <button className="tool-btn" style={{ marginTop: 4 }} disabled={busy} aria-label="confirm retention settings"
          onClick={confirm}>{busy ? 'sending…' : 'confirm'}</button>}
    {error && <div data-testid="retention-confirm-refused" role="alert" style={{ ...mono, fontSize: 10, color: 'var(--red)', marginTop: 4 }}>{error}</div>}
  </div>;
}

const days = (n: any) => (typeof n === 'number' ? `${n} days` : 'kept forever');
/** One would-delete count: `{count, more}` (more: the hub stopped at its limit, so "N+"),
    `{counted: false}` (the hub cannot count this kind), or an older card's plain number. */
const count = (n: any, one: string, many: string) => {
  if (n && typeof n === 'object') {
    if (n.counted === false) return `${many}: not counted`;
    if (typeof n.count === 'number') return `${n.count}${n.more ? '+' : ''} ${n.count === 1 && !n.more ? one : many}`;
    return `${many}: unknown`;
  }
  return typeof n === 'number' ? `${n} ${n === 1 ? one : many}` : `${many}: unknown`;
};

/** The Decision Inbox card of a `settings.retention` task, from the preview it carries. */
export function RetentionCard({ task }: { task: any }) {
  const preview = task?.payload?.preview;
  if (!preview || typeof preview !== 'object') return null;
  const after = preview.horizons && typeof preview.horizons === 'object' ? preview.horizons : {};
  const approved = preview.approved && typeof preview.approved === 'object' ? preview.approved : null;
  const widened: string[] = Array.isArray(preview.widened) ? preview.widened.map(String) : [];
  const gone = preview.would_delete || {};
  return <div data-testid="retention-card" style={{ margin: '3px 0 7px 12px', fontSize: 10, color: 'var(--ink-2)' }}>
    {!approved && <div style={{ color: 'var(--amber)' }}>nothing approved yet: retention deletes nothing until this is accepted</div>}
    {Object.keys(after).map((name) => <div key={name} style={mono}>
      {name}: {days(approved ? approved[name] : null)} → {days(after[name])}
      {widened.includes(name) && <span style={{ color: 'var(--red)' }}> · deeper</span>}
    </div>)}
    <div style={{ marginTop: 2 }}>would delete: {count(gone.archived_chats, 'archived chat', 'archived chats')} deleted by the sweeps of the next 7 days
      {gone.chats_to_archive !== undefined && <>{' · '}{count(gone.chats_to_archive, 'chat', 'chats')} archived by the next sweep, deleted 7 days later</>}
      {' · '}{count(gone.audit_rows, 'audit row', 'audit rows')}
      {gone.ingestion !== undefined && <>{' · '}{count(gone.ingestion, 'ingestion root', 'ingestion')}</>}
      {gone.attachments !== undefined && <>{' · '}{count(gone.attachments, 'attachment', 'attachments')}</>}</div>
    <div style={{ color: 'var(--red)', marginTop: 2 }}>accepting lets the sweep delete this data; what it deletes cannot be undone</div>
  </div>;
}
