/* CONSOLIDATE — the sixth memory-hygiene leg (DRA-27), the one deliberately left unwired
   until two questions were answered in the backend. Three user-tier routes, all called here:

     · GET  /api/memory/consolidate/preview   the `existing` memories a plan runs against
     · POST /api/memory/consolidate           the reversible plan (ADD/UPDATE/DELETE/NOOP)
     · POST /api/memory/consolidate/apply     apply — or dry-run — that plan

   (1) WHERE `existing` COMES FROM. The planner takes {candidates, existing} and a plan against
       `existing: []` is degenerate by construction: every candidate reads as "novel" and the
       card would be a fake. The preview route is fused recall over the LIVE store adapted to
       the planner's {id, key, text} shape, scanned like every recall (an injection-flagged
       memory arrives redacted, tagged) and taint-scoped like one. This panel never fabricates
       an `existing` list and never sends an empty one: the plan and apply buttons are
       withheld until the preview returned rows, and the reason is written on the card.
   (2) WHERE APPLY LIVES. The apply route refuses `existing: []` (422 `existing_required`),
       an unknown op, a target not in `existing`, an ADD/UPDATE with no text — each with a
       stable `reason` the card prints verbatim. A dry run touches nothing and says
       `persistence: dry_run`; a real apply merges the snapshot and writes ADD/UPDATE/DELETE
       to the vector store, reporting `persisted` counts AND `skipped` rows with their reason
       (`not_vector_backed` for graph-only memories, `no_embedding` when nothing could be
       embedded). "counts" is what the plan did to the snapshot; "persisted" is what really
       landed. They differ, and the card shows both rather than the flattering one.

   Honesty contract: `available:false` is rendered as the reason the backend gave, under an
   amber chip; a `tainted:true` preview says the recall touched untrusted or flagged memory
   (that is what escalates a later action to the approval queue, SEC-B5); every mutation
   passes onErr so a refusal is never a silent success (panel-kit.tsx:93-97). */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, taS } from '../panel-kit';

const OP_COLOUR = {
  ADD: 'var(--green)',
  UPDATE: 'var(--accent-light)',
  DELETE: 'var(--red)',
  NOOP: 'var(--ink-2)',
};

/* One candidate per line; an optional `key: text` prefix becomes the planner's `key`. */
export function parseCandidates(raw: string): { key?: string; text: string }[] {
  return String(raw || '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const m = /^([A-Za-z0-9_.-]{1,40}):\s+(.+)$/.exec(l);
      return m ? { key: m[1], text: m[2] } : { text: l };
    });
}

const refusalText = (err: any, verb: string) => {
  const reason = err && err.body && (err.body.reason || err.body.error);
  return `${verb} refused (${String((err && err.status) || '?')})${reason ? ` · ${String(reason)}` : ''}`;
};

export function MemoryConsolidatePanel() {
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const path = '/api/memory/consolidate/preview?q=' + encodeURIComponent(query) + '&top_k=20';
  const { d, e, loading, reload } = useApi(path);
  const existing = arr(d, 'existing');
  const available = !!(d && d.available);
  const raw: any = d;

  const [cands, setCands] = useState('');
  const [plan, setPlan] = useState(null);
  const [summary, setSummary] = useState(null);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const candidates = parseCandidates(cands);
  const canPlan = available && existing.length > 0 && candidates.length > 0;
  const canApply = !!plan && Array.isArray(plan) && plan.length > 0 && existing.length > 0;

  const makePlan = () => {
    setErr(null); setResult(null);
    act('/api/memory/consolidate', { candidates, existing },
      (r: any) => { setPlan(arr(r, 'plan')); setSummary(r && r.summary ? r.summary : null); },
      (ex) => { setPlan(null); setSummary(null); setErr(refusalText(ex, 'plan')); });
  };

  const apply = (dryRun: boolean) => {
    setErr(null); setResult(null);
    act('/api/memory/consolidate/apply', { plan, existing, dry_run: dryRun },
      (r: any) => { setResult(r); if (!dryRun) reload(); },
      (ex) => setErr(refusalText(ex, dryRun ? 'dry run' : 'apply')));
  };

  const counts = (c: any) => (c ? ['ADD', 'UPDATE', 'DELETE', 'NOOP'].map((k) => `${k} ${Number(c[k] || 0)}`).join(' · ') : '');

  return (
    <Card title="CONSOLIDATE" live={asLive(d, available)}
      sub={d ? (available ? `${existing.length} existing` : 'unavailable') : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />

      {d && !available && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          {'no memory manager' + (raw.reason ? ` · ${String(raw.reason)}` : '')} — no existing memories to plan against
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <input value={draft} placeholder="recall query for existing memories" aria-label="recall query"
          onChange={(ev) => setDraft(ev.target.value)}
          onKeyDown={(ev) => { if (ev.key === 'Enter') setQuery(draft); }}
          style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={() => setQuery(draft)}>recall</button>
      </div>

      {d && available && existing.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          nothing recalled — a plan against no existing memories is degenerate (every candidate reads as novel), so plan and apply are withheld
        </div>
      )}
      {d && available && raw.tainted && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          recall touched untrusted or injection-flagged memory · an action born of it queues for approval
        </div>
      )}

      {existing.slice(0, 12).map((m, i) => (
        <Row key={m.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)', minWidth: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.key || m.id}</span>
          <span style={{ color: m.injection_flagged ? 'var(--amber)' : 'var(--ink)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.text}</span>
          <Tag>{m.source || 'memory'}</Tag>
          {!m.persistable && <Tag c="var(--amber)">graph-only</Tag>}
          {m.tainted && <Tag c="var(--amber)">tainted</Tag>}
        </Row>
      ))}

      <div style={{ marginTop: 8 }}>
        <textarea value={cands} placeholder={'candidate memories, one per line · optional "key: text"'}
          aria-label="candidate memories"
          onChange={(ev) => setCands(ev.target.value)} style={taS} />
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
        <button className="tool-btn" disabled={!canPlan} onClick={makePlan}>plan</button>
        <button className="tool-btn" disabled={!canApply} onClick={() => apply(true)}>dry run</button>
        <button className="tool-btn" disabled={!canApply} onClick={() => apply(false)}>apply</button>
        {summary && <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{counts(summary)}</span>}
      </div>

      {Array.isArray(plan) && plan.map((op, i) => (
        <Row key={i}>
          <Tag c={OP_COLOUR[op.op] || 'var(--ink-2)'}>{op.op}</Tag>
          <span style={{ color: 'var(--ink)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {op.text || (op.target_id ? `→ ${op.target_id}` : '')}
          </span>
          <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>{op.reason || ''}</span>
        </Row>
      ))}

      {result && (
        <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }} data-testid="apply-result">
          <div style={{ color: result.dry_run ? 'var(--amber)' : 'var(--green)' }}>
            {result.dry_run ? 'dry run · nothing written' : 'applied'} · snapshot {counts(result.counts)}
          </div>
          {!result.dry_run && (
            <div>
              {'persisted ' + ['ADD', 'UPDATE', 'DELETE'].map((k) => `${k} ${Number((result.persisted || {})[k] || 0)}`).join(' · ')}
              {' · '}{String(result.persistence || '')}
            </div>
          )}
          {arr(result, 'skipped').map((s, i) => (
            <div key={i} style={{ color: 'var(--amber)' }}>{`skipped ${s.op || ''} #${s.index ?? '?'} · ${s.reason || 'unknown'}`}</div>
          ))}
          {arr(result, 'errors').map((s, i) => (
            <div key={i} style={{ color: 'var(--red)' }}>{`error ${s.op || ''} #${s.index ?? '?'} · ${s.reason || 'unknown'}`}</div>
          ))}
        </div>
      )}

      {err && <div role="alert" style={{ fontSize: 10, color: 'var(--red)', marginTop: 6 }}>{err}</div>}

      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>
        Mem0-style plan over what the store really holds: a dry run never writes; apply merges the snapshot and persists vector-backed rows only — graph-only rows are skipped and named.
      </div>
    </Card>
  );
}
