/* Restart / update — restart Nerva and check whether it is behind (G21 · H160/H173).

   The hub reads its own checkout (agents/core/hub_update.py): version, branch, commit,
   whether the tree has uncommitted changes, and how far behind its upstream it is as of the
   last fetch, with the fetch's age. "Check now" fetches the upstream and shows the log as
   it runs. Applying an update is not offered here: the hub says why, and the steps are in
   docs/UPGRADE.md. "Restart" asks the hub to restart itself, then waits until it answers
   again; a hub that was not started by serve.py says it cannot. */
import React, { useEffect, useRef, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { Card, Tag, mono, refusalReason, useApi } from '../panel-kit';

export const OPS_UPDATE_PATH = '/api/admin/ops/update';

type Check = { version: string; install: string; restart: 'self' | 'manual'; branch: string | null; commit: string | null;
  upstream: string | null; behind: number | null; ahead: number | null; fetched_seconds_ago: number | null;
  dirty: boolean | null; can_apply: boolean; apply_refused: string[]; manual_steps: string };
type Action = { id: string; kind: string; status: 'running' | 'ok' | 'failed'; lines: string[] };
type Receipt = { id: string; kind: string; from: string | null; to: string | null; phase?: string; result?: string | null;
  reason?: string | null; action_id?: string | null; log?: string[] };
type Trust = { configured: boolean; mode: string | null; fingerprints?: string[]; commit?: string };
type Plan = { can_apply: boolean; refused: string[]; from: string | null; to: string | null; from_version: string | null;
  to_version: string | null; commit_count: number; file_count: number; migrations: string[];
  dependencies: { changed: boolean; command: string | null }; commits: { sha: string; subject?: string }[] };
type UpdateCheck = Check & { trust?: Trust; in_progress?: Receipt | null; last_receipt?: Receipt | null };
const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : '—');

export function ago(s: number | null | undefined): string {
  if (s == null) return 'never fetched';
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

const why = (err: any) => {
  const body = err?.body;
  if (body && typeof body === 'object' && typeof body.detail === 'string') return body.detail;
  return refusalReason(err, String(err?.status || 'error'));
};

export function SystemUpdatePanel({ pollMs = 1000 }: { pollMs?: number }) {
  const { d, e, reload } = useApi(OPS_UPDATE_PATH, true, true);
  const c = d as UpdateCheck | null;
  const [plan, setPlan] = useState<Plan | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef<any>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const follow = (id: string) => {
    apiGet<Action>(`/api/admin/ops/actions/${id}`, { admin: true })
      .then((a) => {
        setLog(a.lines);
        if (a.status === 'running') { timer.current = setTimeout(() => follow(id), pollMs); return; }
        setBusy(false);
        setNote(a.status === 'ok' ? 'checked' : 'the check failed (see the log)');
        reload();
      })
      .catch((x: any) => { setBusy(false); setNote(`lost the check · ${why(x)}`); });
  };
  const fetchNow = () => {
    setBusy(true); setNote(null); setLog([]);
    apiPost<Action>('/api/admin/ops/update/fetch', {}, { admin: true })
      .then((a) => { setLog(a.lines); follow(a.id); })
      .catch((x: any) => { setBusy(false); setNote(`not checked · ${why(x)}`); });
  };
  const waitBack = (tries: number) => {
    apiGet<{ ready: boolean }>('/readyz')
      .then((r) => {
        if (r?.ready) { setLog((l) => [...l, 'Nerva is back']); setBusy(false); reload(); return; }
        throw new Error('not ready');
      })
      .catch(() => {
        if (tries <= 0) { setLog((l) => [...l, 'Nerva has not answered yet; reload the page in a moment']); setBusy(false); return; }
        timer.current = setTimeout(() => waitBack(tries - 1), pollMs * 2);
      });
  };
  const restart = () => {
    setConfirming(false); setBusy(true); setNote(null);
    apiPost<Action>('/api/admin/ops/restart', { confirm: 'restart' }, { admin: true })
      .then((a) => { setLog([...a.lines, 'waiting for Nerva to answer again…']); timer.current = setTimeout(() => waitBack(60), pollMs * 2); })
      .catch((x: any) => { setBusy(false); setNote(`not restarted · ${why(x)}`); });
  };

  const showPlan = () => {
    setBusy(true); setNote(null);
    apiGet<Plan>('/api/admin/ops/update/plan', { admin: true })
      .then((p) => { setPlan(p); setBusy(false); })
      .catch((x: any) => { setBusy(false); setNote(`no plan · ${why(x)}`); });
  };
  const queueCard = (path: string, body: object, what: string) => {
    setBusy(true); setNote(null);
    apiPost<{ task_id: number }>(path, body, { admin: true })
      .then((r) => { setBusy(false); setNote(`approval card #${r.task_id} queued: ${what} — accept it in the approval queue`); reload(); })
      .catch((x: any) => { setBusy(false); setNote(`not queued · ${why(x)}`); });
  };
  const flight = c?.in_progress || null;
  const last = c?.last_receipt || null;

  return (
    <Card title="RESTART / UPDATE" live={c ? 'live' : undefined} onReload={reload}
      sub={c ? `v${c.version}${c.commit ? ` · ${c.commit}` : ''}` : null}>
      {e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(e)}</div>}
      {c && (
        <dl style={{ margin: 0, fontSize: 11, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 8px' }}>
          <dt>Install</dt><dd style={{ margin: 0 }}>{c.install}</dd>
          <dt>Branch</dt><dd style={{ margin: 0, ...mono }}>{c.branch || '—'}{c.upstream ? ` → ${c.upstream}` : ''}</dd>
          <dt>Behind</dt><dd style={{ margin: 0 }}>{c.behind == null ? 'unknown' : `${c.behind} commit(s)`}{c.ahead ? ` · ${c.ahead} ahead` : ''} · as of the last fetch, {ago(c.fetched_seconds_ago)}</dd>
          <dt>Working tree</dt><dd style={{ margin: 0 }}>{c.dirty == null ? 'unknown' : c.dirty ? <Tag c="var(--amber)">uncommitted changes</Tag> : 'clean'}</dd>
          <dt>Restart</dt><dd style={{ margin: 0 }}>{c.restart === 'self' ? 'Nerva can restart itself' : 'restart it the way it was started'}</dd>
          <dt>Trust</dt><dd style={{ margin: 0, ...mono }}>{c.trust?.configured ? `${c.trust.mode} · ${c.trust.commit ? short(c.trust.commit) : (c.trust.fingerprints || []).join(', ')}` : 'none pinned (nerva update trust)'}</dd>
          {flight && <><dt>In progress</dt><dd style={{ margin: 0 }}><Tag c="var(--amber)">{flight.kind} {flight.phase}</Tag> {short(flight.from)} → {short(flight.to)}</dd></>}
          {last && <><dt>Last</dt><dd style={{ margin: 0 }}>{last.kind} {short(last.from)} → {short(last.to)} · {last.result || last.phase}{last.reason ? ` (${last.reason})` : ''}</dd></>}
        </dl>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        <button className="tool-btn" disabled={busy || c?.install !== 'git'} onClick={fetchNow}>check now</button>
        {!confirming
          ? <button className="tool-btn" disabled={busy || c?.restart !== 'self'} onClick={() => setConfirming(true)}>restart…</button>
          : (
            <span role="alertdialog" aria-label="confirm restart" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 11 }}>Restart Nerva now? Chats in progress are interrupted.</span>
              <button className="tool-btn" onClick={restart}>restart now</button>
              <button className="tool-btn" onClick={() => setConfirming(false)}>cancel</button>
            </span>
          )}
      </div>
      {c?.can_apply && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
          <button className="tool-btn" disabled={busy} onClick={showPlan}>plan</button>
          {plan?.can_apply && <button className="tool-btn" disabled={busy} onClick={() => queueCard('/api/admin/ops/update/apply', {}, `update to ${short(plan.to)}`)}>request update</button>}
        </div>
      )}
      {last?.kind === 'update' && last.result === 'verified' && !flight && (
        <button className="tool-btn" style={{ marginTop: 6 }} disabled={busy} onClick={() => queueCard('/api/admin/ops/update/rollback', {}, `roll back to ${short(last.from)}`)}>request rollback</button>
      )}
      {plan && (
        <div aria-label="update plan" style={{ fontSize: 11, marginTop: 6 }}>
          <div>{short(plan.from)} ({plan.from_version || '?'}) → {short(plan.to)} ({plan.to_version || '?'}) · {plan.commit_count} commit(s), {plan.file_count} file(s)</div>
          <div>dependencies: {plan.dependencies.command || 'lock unchanged'} · migrations: {plan.migrations.join(', ') || 'none expected'}</div>
          {plan.commits.slice(0, 10).map((x) => <div key={x.sha} style={mono}>{short(x.sha)} {x.subject}</div>)}
          {plan.refused.length > 0 && <div style={{ color: 'var(--amber)' }}>refused: {plan.refused.join(', ')}</div>}
        </div>
      )}
      {flight?.log && flight.log.length > 0 && log.length === 0 && (
        <pre aria-label="update log" style={{ ...mono, fontSize: 10.5, maxHeight: 220, overflow: 'auto', background: 'var(--surface)', padding: 6, marginTop: 6 }}>{flight.log.join('\n')}</pre>
      )}
      {note && <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{note}</div>}
      {log.length > 0 && (
        <pre aria-label="action log" style={{ ...mono, fontSize: 10.5, maxHeight: 220, overflow: 'auto', background: 'var(--surface)', padding: 6, marginTop: 6 }}>{log.join('\n')}</pre>
      )}
      {c && !c.can_apply && (
        <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 6 }}>
          Updating from here is not available: {c.apply_refused.join('; ')}.
        </div>
      )}
    </Card>
  );
}
