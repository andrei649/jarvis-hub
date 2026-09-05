/* HUD v2 · P4c — the net-new gap surfaces from the §5b/§5c audit, hosted in a
   Console overlay (mirrors v1 tools.js). Each panel fetches its real endpoint and
   degrades to an offline/empty state — never blocks. Admin-guarded calls work on
   localhost; on a network they surface the 401 via the client's token prompt. */
import React, { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiPut, apiPatch, apiDelete, actionFailures, onActionFailure, clearActionFailures } from './api/client';
import { localModelStatus } from './api/live';
import { OperatorPanel } from './operator-panel';
import { CoachPanel } from './panels/coach';
import { CodeIntelPanel } from './panels/codeintel';
import { CreativePanel } from './panels/creative';
import { OsintPanel } from './panels/osint';
import { MarketplaceAdminPanel } from './panels/marketplace-admin';
import { SecuritySkillsMapPanel } from './panels/security-skills-map';
import { PaymentsPanel } from './panels/payments';
import { SignalGovernancePanel } from './panels/signals-governance';
import { AutonomyControlPanel } from './panels/autonomy-legacy';
import { DesktopAllowlistPanel } from './panels/desktop-allowlist';
import { LlmRoutingPanel } from './panels/llm-routing';
import { WorkflowTracesPanel } from './panels/workflows-advanced';
import { PresenceInboxPanel } from './panels/presence-inbox';
import { ReviewQualityPanel } from './panels/review-quality';
import { TrustOpsPanel } from './panels/trust-ops';
import { WritebackDigestPanel } from './panels/writeback-digest';
import { SupportVoicePanel } from './panels/support-voice';
import { AgentsArenaPanel } from './panels/agents-arena';
import { MissionCanvasPanel } from './panels/mission-canvas';
import { SkillsImportPanel } from './panels/skills-import';

import { useApi, arr, mono, asLive, PanelChip, Card, State, Row, Tag, Btn, act, actA, inpS, taS, Json } from './panel-kit';

function MediaOutcome({ value }) {
  if (!value) return null;
  if (value.output && value.output.ok === false) {
    return <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 8 }}>
      refused · {value.output.reason || value.reason || 'media_action_failed'}
    </div>;
  }
  if (value.status === 'completed' && value.output?.ok === true && value.output?.verified === true) {
    return <div role="status" style={{ ...mono, color: 'var(--green)', marginTop: 8 }}>
      verified success · {value.output.device || 'device'} · {value.output.verification || 'verified'}
    </div>;
  }
  if (value.status === 'completed' && value.output?.ok === true) {
    return <div role="alert" style={{ ...mono, color: 'var(--amber)', marginTop: 8 }}>
      unverified · success not claimed
    </div>;
  }
  if (value.status === 'queued') {
    return <div role="status" style={{ ...mono, color: 'var(--amber)', marginTop: 8 }}>
      queued for approval · {value.reason || 'approval_required'}
    </div>;
  }
  if (value.status === 'refused' || value.status === 'disabled' || value.status === 'failed') {
    return <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 8 }}>
      {value.status} · {value.reason || 'request_failed'}
    </div>;
  }
  return <Json v={value} max={120} />;
}
function HouseOutcome({ value }) {
  if (!value) return null;
  if (value.status === 'sending') {
    return <div role="status" style={{ ...mono, color: 'var(--ink-3)', marginTop: 8 }}>submitting governed proposal…</div>;
  }
  if (value.status === 'queued' && value.strong_confirmation_required) {
    return <div role="status" style={{ ...mono, color: 'var(--amber)', marginTop: 8 }}>
      strong confirmation required · task {value.task_id || 'pending'}
    </div>;
  }
  if (value.status === 'queued') {
    return <div role="status" style={{ ...mono, color: 'var(--amber)', marginTop: 8 }}>
      queued for approval · task {value.task_id || 'pending'}
    </div>;
  }
  if (value.status === 'verified') {
    return <div role="status" style={{ ...mono, color: 'var(--green)', marginTop: 8 }}>
      verified success · {value.reason || 'state_verified'}
    </div>;
  }
  if (value.status === 'unverified') {
    return <div role="alert" style={{ ...mono, color: 'var(--amber)', marginTop: 8 }}>
      unverified · no action claimed · {value.reason || 'verification_missing'}
    </div>;
  }
  return <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 8 }}>
    denied · {value.reason || 'request_refused'}
  </div>;
}
function DiffView({ text }) {
  if (text == null) return null;
  if (text === '') return <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6 }}>identical · no changes</div>;
  const color = (l) => l.startsWith('@@') ? 'var(--accent-light)'
    : (l.startsWith('+') && !l.startsWith('+++')) ? 'var(--green)'
    : (l.startsWith('-') && !l.startsWith('---')) ? 'var(--red)' : 'var(--ink-3)';
  return <pre style={{ ...mono, fontSize: 10.5, lineHeight: 1.45, whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto', margin: '6px 0 0', padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4 }}>
    {text.split('\n').map((l, i) => <div key={i} style={{ color: color(l) }}>{l || ' '}</div>)}
  </pre>;
}

/* ── Memory / Knowledge ─────────────────────────────────── */
/* HUD-v3 C3 (KG edit/delete + memory forget). The Memory cluster had spaces/docs/notes
   but no knowledge-graph control: this lists/searches entities, deletes one, and forgets
   a memory item by id (ACT-R decay, transitive). All user-guarded. */
/* HUD-v3 §4.3 — Ambient Capture, the privacy promise made visible. The opt-in passive
   capture backend (redacted previews, local) had no UI: this shows the captured stream
   with each item INDIVIDUALLY DELETABLE (DELETE /api/capture/{id}) + clear-all. All
   user-guarded; the redacted `preview` is shown, never raw content. */
export function CapturePanel() {
  const { d, e, loading, reload } = useApi('/api/capture');
  const status = useApi('/api/capture/status');
  const recs = arr(d, 'records');
  const enabled = status.d && status.d.enabled;
  const del = (id) => apiDelete('/api/capture/' + encodeURIComponent(id)).then(reload).catch(() => {});
  const clearAll = () => act('/api/capture/clear', {}, reload);
  return (
    <Card title="AMBIENT CAPTURE" live={asLive(status.d, enabled)} sub={status.d ? (enabled ? 'on' : 'off') + ' · ' + recs.length : null} onReload={() => { reload(); status.reload(); }}>
      <State e={e} loading={loading} n={recs.length} />
      {recs.slice(0, 10).map((r, i) => (
        <Row key={r.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{r.preview || r.surface}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {r.surface && <Tag>{r.surface}</Tag>}
            <button className="tool-btn" title="delete" onClick={() => del(r.id)}>✕</button>
          </span>
        </Row>
      ))}
      {recs.length > 0 && <div style={{ marginTop: 8 }}><button className="tool-btn" onClick={clearAll}>clear all</button></div>}
      {recs.length === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>nothing captured · opt-in surfaces stream here, each deletable</div>}
    </Card>
  );
}
export function KgPanel() {
  const { d, e, loading, reload } = useApi('/api/kg/entities');
  const ents = arr(d, 'entities');
  const [forgetId, setForgetId] = useState('');
  const [msg, setMsg] = useState(null);
  /* DRA-27 (write legs) — the graph was read-only from the HUD: nothing in any client ever
     posted `/api/kg/relations` or `/api/kg/ingest`. Both are contract- AND kernel-mediated
     and answer 403 "kernel denied: …", plus add-relation answers 400 for a relation type
     that is not a bare identifier (it is interpolated into Cypher). Both refusals are
     rendered — apiPost throws, so a control without onErr reads as a silent success. */
  const [relSrc, setRelSrc] = useState('');
  const [relRel, setRelRel] = useState('');
  const [relTgt, setRelTgt] = useState('');
  const [ingestText, setIngestText] = useState('');
  const [triples, setTriples] = useState([]);
  const writeErr = (err) => setMsg(err?.status === 400 ? 'invalid relation type'
    : err?.status === 503 ? 'refused · 503 · graph unavailable'
    : `refused · ${err?.status || 'error'}`);
  const addRelation = () => {
    const source = relSrc.trim(); const relation = relRel.trim(); const target = relTgt.trim();
    if (!source || !relation || !target) return;
    act('/api/kg/relations', { source, relation, target },
      () => { setRelSrc(''); setRelRel(''); setRelTgt(''); setMsg(`relation added · ${source} ${relation} ${target}`); reload(); },
      writeErr);
  };
  const ingest = () => {
    const text = ingestText.trim();
    if (!text) return;
    act('/api/kg/ingest', { text },
      (r) => { setMsg(`added ${r?.added ?? 0} triple(s)`); setTriples(arr(r, 'triples')); setIngestText(''); reload(); },
      writeErr);
  };
  const del = (name) => apiDelete('/api/kg/entities/' + encodeURIComponent(name)).then(reload).catch(() => {});
  /* The old `r.error ? 'not found'` branch here was DEAD: apiPost throws on the route's 404
     and act's `.catch(() => {})` ate it, so a bad id silently cleared the box and looked like
     a successful forget. onErr (added with DRA-52) is what makes the refusal reachable. */
  const forget = () => {
    if (!forgetId.trim()) return;
    const id = forgetId.trim();
    act('/api/memory/decay/forget', { id },
      () => { setMsg('forgotten · ' + id); setForgetId(''); reload(); },
      (err) => setMsg(err?.status === 404 ? 'not found · ' + id : `forget refused · ${err?.status || 'error'}`));
  };
  /* PNL-059: the route answers 200 with {entities: [], error} when the store is
     down — reading only `entities` rendered a dead graph as a clean empty one
     under a green LIVE chip. */
  const kgError = (d as any)?.error;
  return (
    <Card title="KNOWLEDGE GRAPH" live={asLive(d, !kgError)} sub={d ? `${ents.length} entities` : null} onReload={reload}>
      <State e={e} loading={loading} n={ents.length} />
      {kgError && <Row><span style={{ ...mono, color: 'var(--amber)' }}>{String(kgError)} — graph unavailable, not empty</span></Row>}
      {ents.slice(0, 12).map((en, i) => (
        <Row key={en.name ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{en.name}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {en.type && <Tag>{en.type}</Tag>}
            {typeof en.mentions === 'number' && <Tag>{en.mentions}×</Tag>}
            <button className="tool-btn" title="delete entity" onClick={() => del(en.name)}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={forgetId} onChange={(ev) => setForgetId(ev.target.value)} placeholder="memory item id to forget" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={forget}>forget</button>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={relSrc} onChange={(ev) => setRelSrc(ev.target.value)} placeholder="source" style={{ ...inpS, flex: 1, minWidth: 0 }} />
        <input value={relRel} onChange={(ev) => setRelRel(ev.target.value)} placeholder="relation" style={{ ...inpS, flex: 1, minWidth: 0 }} />
        <input value={relTgt} onChange={(ev) => setRelTgt(ev.target.value)} placeholder="target" style={{ ...inpS, flex: 1, minWidth: 0 }} />
        <button className="tool-btn" onClick={addRelation}>add relation</button>
      </div>
      <div style={{ marginTop: 8 }}>
        <textarea value={ingestText} onChange={(ev) => setIngestText(ev.target.value)} placeholder="text to extract triples from…" style={{ ...taS, minHeight: 48 }} />
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <button className="tool-btn" onClick={ingest}>ingest</button>
          <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>extraction is heuristic — the written triples are listed below, not just counted</span>
        </div>
      </div>
      {triples.slice(0, 10).map((t, i) => (
        <Row key={i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>
            {Array.isArray(t) ? t.join(' · ') : [t?.source ?? t?.subject, t?.relation ?? t?.predicate, t?.target ?? t?.object].filter(Boolean).join(' · ')}
          </span>
        </Row>
      ))}
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
/* DRA-27 (write legs) — `POST /api/memory/remember` had no client caller anywhere, so the
   HUD could forget a memory but never make one. Placed beside MEMORY HYGIENE on purpose:
   they are the two halves of the same loop.

   Honesty: the route answers **200 `{ok:false, id:null}`** when the embedder is unavailable
   — the write is accepted and then silently not stored. Printing "stored" for that would be
   the exact lie this panel exists to avoid, so `ok:false` gets its own copy, and a 4xx/5xx
   refusal (apiPost throws) reaches `onErr` and is rendered rather than swallowed. */
export function MemoryWritePanel() {
  const [text, setText] = useState('');
  const [source, setSource] = useState('');
  const [msg, setMsg] = useState(null);
  const [last, setLast] = useState(null);
  const remember = () => {
    const t = text.trim();
    if (!t) return;
    setMsg(null);
    act('/api/memory/remember', { text: t, metadata: { source: source.trim() || 'hud' } },
      (r) => {
        setLast(r);
        if (r?.ok) { setMsg(`stored · ${r.id}`); setText(''); }
        else setMsg('not stored — the write was accepted but no embedding was produced');
      },
      (err) => { setLast(null); setMsg(`refused · ${err?.status || 'error'}`); });
  };
  return (
    <Card title="REMEMBER" live={asLive(last, last?.ok)} sub={last ? (last.ok ? 'stored' : 'not stored') : null}>
      <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="fact to remember, in plain language…" style={taS} />
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <input value={source} onChange={(ev) => setSource(ev.target.value)} placeholder="source (optional)" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={remember}>remember</button>
      </div>
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
        Long-term vector memory. Without an embedder the route still answers 200 — this card says
        "not stored" for that case rather than claiming a write that did not happen.
      </div>
    </Card>
  );
}
/* DRA-27 (hygiene cut) — `GET /api/memory/decay/candidates` had no client caller, which left
   the forget loop half-built: KgPanel could already forget an item BY ID, but nothing told the
   operator which ids had decayed far enough to be worth forgetting. This lists them at an
   adjustable threshold and forgets from the row.

   Forgetting is transitive by design (`decay.forget` removes an item AND its dependents, the
   anti-recontamination rule), so the row says so rather than presenting it as a single delete. */
export function MemoryHygienePanel() {
  const [threshold, setThreshold] = useState(0.3);
  const { d, e, loading, reload } = useApi(`/api/memory/decay/candidates?threshold=${threshold}`);
  const cands = arr(d, 'candidates');
  const [msg, setMsg] = useState(null);
  const forget = (id) => act('/api/memory/decay/forget', { id },
    (r) => { setMsg(`forgot ${id} · ${arr(r, 'removed').length || 1} item(s)`); reload(); },
    (err) => setMsg(err?.status === 404 ? `not found · ${id}` : `forget refused · ${err?.status || 'error'}`));
  return (
    <Card title="MEMORY HYGIENE" live={asLive(d)} sub={d ? `${cands.length} below ${threshold}` : null} onReload={reload}>
      <State e={e} loading={loading} n={cands.length} />
      {cands.slice(0, 12).map((c, i) => (
        <Row key={c.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.label || c.id}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--amber)">{c.activation}</Tag>
            <button className="tool-btn" title="forget this item and its dependents" onClick={() => forget(c.id)}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>threshold</span>
        <input
          type="number" step="0.1" min="0" value={threshold}
          onChange={(ev) => setThreshold(Number(ev.target.value) || 0)}
          style={{ ...inpS, width: 70 }}
        />
      </div>
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
        ACT-R activation below the threshold — ✕ forgets the item AND its dependents.
      </div>
    </Card>
  );
}
/* DRA-27 (eval legs) — the memory harness (`/api/memory/eval/corpus` + `/run`) existed with
   no way to run it outside pytest. Named MemoryEvalPanel, not EvalPanel: that name is already
   taken by the Observe dataset panel.

   The two modes are NOT interchangeable and the card says so: `keyword` scores a pure string
   answerer over the corpus facts (no store touched), while `recall` really calls
   `MemoryManager.remember()` for every case fact — it WRITES the corpus into the vector store
   under deterministic ids. A run button with a side effect that big has to name it. */
export function MemoryEvalPanel() {
  const { d, e, loading, reload } = useApi('/api/memory/eval/corpus');
  const cases = arr(d, 'cases');
  const abilities = arr(d, 'abilities');
  const [run, setRun] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = (mode) => {
    setBusy(true); setMsg(null);
    const done = () => setBusy(false);
    if (mode === 'keyword') {
      act('/api/memory/eval/run?mode=keyword', {},
        (r) => { setRun(r); done(); },
        (err) => { setMsg(`refused · ${err?.status || 'error'}`); done(); });
    } else {
      act('/api/memory/eval/run?mode=recall', {},
        (r) => { setRun(r); done(); },
        (err) => { setMsg(`refused · ${err?.status || 'error'}`); done(); });
    }
  };
  const overall = run?.overall;
  const byAbility = (run && (run.by_ability || run.per_ability)) || {};
  return (
    <Card title="MEMORY EVAL" live={asLive(d)} sub={d ? `${cases.length} cases` : null} onReload={reload}>
      <State e={e} loading={loading} n={cases.length} />
      {abilities.length > 0 && <Row><span style={{ ...mono, color: 'var(--ink-2)' }}>{abilities.join(' · ')}</span></Row>}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        <button className="tool-btn" disabled={busy} onClick={() => go('keyword')}>run keyword</button>
        <button className="tool-btn" disabled={busy} onClick={() => go('recall')}>run recall</button>
      </div>
      <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
        recall writes the corpus into the vector store (one remembered record per case fact) — keyword does not.
      </div>
      {overall && <Row>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>{`${overall.passed}/${overall.n} passed`}</span>
        <span style={{ marginLeft: 'auto' }}><Tag c={overall.score >= 0.8 ? 'var(--green)' : 'var(--amber)'}>{run?.mode || 'keyword'}</Tag></span>
      </Row>}
      {Object.entries(byAbility).map(([name, b]: any) => (
        <Row key={name}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{name}</span>
          <span style={{ marginLeft: 'auto' }}><Tag c={b?.score === 1 ? 'var(--green)' : 'var(--amber)'}>{`${b?.passed ?? 0}/${b?.n ?? 0} · ${b?.score}`}</Tag></span>
        </Row>
      ))}
      {msg && <div style={{ fontSize: 10, color: 'var(--red)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
export function DataSpacesPanel() {
  const { d, e, loading, reload } = useApi('/api/memory/spaces');
  const spaces = arr(d, 'spaces');
  const assignments = d?.assignments || {};
  const assignmentRows = Object.entries(assignments).flatMap(([agent, names]: any) =>
    (Array.isArray(names) ? names : []).map((space) => ({ agent, space })),
  );
  const spaceName = (s) => s?.name || s?.space || s;
  const [name, setName] = useState(''); const [src, setSrc] = useState('');
  const [agent, setAgent] = useState(''); const [assignSpace, setAssignSpace] = useState('');
  const [msg, setMsg] = useState('');
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11, flex: 1 };
  const create = () => { if (!name.trim()) return; apiPost('/api/memory/spaces', { name: name.trim(), sources: src.split(',').map((s) => s.trim()).filter(Boolean) }, { admin: true }).then(() => { setName(''); setSrc(''); reload(); }).catch(() => {}); };
  const assign = () => {
    const a = agent.trim(); const sp = assignSpace.trim();
    if (!a || !sp) return;
    apiPost('/api/memory/spaces/assign', { agent: a, space: sp }, { admin: true })
      .then(() => { setMsg(`${a} -> ${sp}`); reload(); })
      .catch(() => setMsg('assign failed'));
  };
  const unassign = (a, sp) => apiPost('/api/memory/spaces/unassign', { agent: a, space: sp }, { admin: true })
    .then(() => { setMsg(`${a} unrestricted from ${sp}`); reload(); })
    .catch(() => setMsg('unassign failed'));
  const optionSpaces = spaces.map(spaceName).filter(Boolean);
  return <Card title="DATA SPACES" live={asLive(d)} sub={spaces.length} onReload={reload}>
    <State e={e} loading={loading} n={spaces.length} />
    {spaces.slice(0, 12).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{spaceName(s)}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{(s.sources || s.categories || []).join?.(', ')}</span><Btn onClick={() => apiDelete('/api/memory/spaces/' + spaceName(s), { admin: true }).then(reload).catch(() => {})}>✕</Btn></Row>)}
    {assignmentRows.length > 0 && <div style={{ marginTop: 8 }}>
      <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, marginBottom: 4 }}>ASSIGNMENTS</div>
      {assignmentRows.slice(0, 16).map((r, i) => <Row key={`${r.agent}:${r.space}:${i}`}>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>{r.agent}</span>
        <Tag c="var(--accent-light)">{r.space}</Tag>
        <button className="tool-btn" title={`unassign ${r.agent} from ${r.space}`} onClick={() => unassign(r.agent, r.space)}>unassign</button>
      </Row>)}
    </div>}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="space name" style={inp} />
      <input value={src} onChange={(ev) => setSrc(ev.target.value)} placeholder="sources, csv" style={inp} />
      <button className="tool-btn" onClick={create}>+ add</button>
    </div>
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder="agent id" style={inp} />
      <select aria-label="space to assign" value={assignSpace} onChange={(ev) => setAssignSpace(ev.target.value)} style={{ ...inp, minWidth: 120 }}>
        <option value="">choose space</option>
        {optionSpaces.map((sp) => <option key={sp} value={sp}>{sp}</option>)}
      </select>
      <button className="tool-btn" onClick={assign}>assign</button>
    </div>
    {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>per-agent read scope (H10.26) · default-open</div>
  </Card>;
}
function LocalDocsPanel() {
  const { d, e, loading, reload } = useApi('/api/local-docs');
  const keys = arr(d, 'folders', 'keys'); const docs = d?.indexed || d?.docs;
  return <Card title="LOCAL DOCS" live={asLive(d)} sub={docs != null ? docs : keys.length} onReload={reload}>
    <State e={e} loading={loading} n={keys.length} />
    {keys.slice(0, 8).map((k, i) => <Row key={i}><span style={mono}>{k.key || k}</span><Btn onClick={() => act('/api/local-docs/index', { key: k.key || k }, reload)}>index</Btn></Row>)}
  </Card>;
}
function NotesPanel() {
  const { d, reload } = useApi('/api/notes');
  const [v, setV] = useState(null);
  const cur = v != null ? v : (d?.content || d?.notes || '');
  return <Card title="NOTES" live={asLive(d)} onReload={reload}>
    <textarea value={cur} onChange={(ev) => setV(ev.target.value)} placeholder="session notes injected into every turn…" style={{ width: '100%', minHeight: 70, background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono }} />
    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
      <button className="tool-btn" onClick={() => apiPut('/api/notes', { content: cur }).catch(() => {})}>save</button>
      <button className="tool-btn" onClick={() => act('/api/notes/rewrite', { save: true }, reload)}>rewrite with AI</button>
    </div>
  </Card>;
}

/* DRA-53 — NOTE DOCS: the block-tree document store (agents/core/notes_store.py, H22.10)
   adopted behind real routes. It shipped fully tested and reachable by NOTHING — no route,
   no caller — which is why the roadmap framed it as "adopt it behind a route or delete it".

   Sibling of NOTES above, not a replacement: `/api/notes` is the free-text session note
   injected into every turn; this is the structured tree whose blocks carry STABLE ids, so a
   memory reference survives edits and reordering. That stability is also why the listing
   exists — without `GET /api/notes/docs` the panel could create a doc and immediately lose
   its id, which would be a write-only surface pretending to be a store. */
const NoteBlockRows = ({ nodes, depth = 0, onEdit, onDelete }: any) => (
  <>
    {(nodes || []).map((n) => (
      <React.Fragment key={n.id}>
        <Row>
          <span style={{ width: depth * 12 }} />
          <Tag>{n.type}</Tag>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{n.text}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
            <button className="tool-btn" title="edit this block" onClick={() => onEdit(n)}>edit</button>
            <button className="tool-btn" title="delete this block and its children" onClick={() => onDelete(n)}>✕</button>
          </span>
        </Row>
        <NoteBlockRows nodes={n.children} depth={depth + 1} onEdit={onEdit} onDelete={onDelete} />
      </React.Fragment>
    ))}
  </>
);
export function NoteDocsPanel() {
  const { d, e, loading, reload } = useApi('/api/notes/docs');
  const docs = arr(d, 'docs');
  const [title, setTitle] = useState('');
  const [openId, setOpenId] = useState(null);
  const [tree, setTree] = useState(null);
  const [newBlock, setNewBlock] = useState('');
  const [editing, setEditing] = useState(null);
  const [blockText, setBlockText] = useState('');
  const [msg, setMsg] = useState(null);
  /* Every mutation here can legitimately refuse: the store answers 400 for a missing doc or
     block, a cross-doc parent, or a move that would make a cycle, and apiPost/apiPatch/
     apiDelete THROW on 4xx. A control without this reads as a silent success. */
  const refused = (err) => setMsg(`refused · ${err?.status || 'error'}`);
  /* `keepMsg` matters: every mutation re-reads the tree afterwards, and a refresh that
     cleared the message would erase the outcome it was just told to report ("deleted 2
     block(s)") a frame after painting it. */
  const openDoc = (id, keepMsg = false) => {
    setOpenId(id); setEditing(null);
    apiGet(`/api/notes/docs/${id}`).then((t) => { setTree(t); if (!keepMsg) setMsg(null); })
      .catch((err) => { setTree(null); setMsg(`could not open · ${err?.status || 'offline'}`); });
  };
  const create = () => act('/api/notes/docs', { title: title.trim() },
    (r) => { setTitle(''); setMsg(`created · ${r?.id || ''}`); reload(); }, refused);
  const delDoc = (id) => apiDelete(`/api/notes/docs/${id}`)
    .then((r: any) => { if (id === openId) { setOpenId(null); setTree(null); } setMsg(`deleted doc · ${r?.deleted ?? 0} block(s)`); reload(); })
    .catch(refused);
  const addBlock = () => {
    const text = newBlock.trim();
    if (!openId || !text) return;
    act(`/api/notes/docs/${openId}/blocks`, { type: 'paragraph', text },
      () => { setNewBlock(''); setMsg('block added'); openDoc(openId, true); }, refused);
  };
  const saveBlock = () => {
    if (!editing) return;
    apiPatch(`/api/notes/blocks/${editing}`, { text: blockText })
      .then(() => { setEditing(null); setMsg('block saved'); openDoc(openId, true); })
      .catch(refused);
  };
  const delBlock = (n) => apiDelete(`/api/notes/blocks/${n.id}`)
    .then((r: any) => { setMsg(`deleted ${r?.deleted ?? 1} block(s)`); openDoc(openId, true); })
    .catch(refused);
  return (
    <Card title="NOTE DOCS" live={asLive(d)} sub={d ? `${docs.length} docs` : null} onReload={reload}>
      <State e={e} loading={loading} n={docs.length} />
      {docs.slice(0, 12).map((doc) => (
        <Row key={doc.id}>
          <button
            className="tool-btn"
            title="open this doc"
            style={{ ...mono, color: doc.id === openId ? 'var(--accent-light)' : 'var(--ink-2)' }}
            onClick={() => openDoc(doc.id)}
          >{doc.title || doc.id}</button>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag>{String(doc.updated_at || '').slice(0, 16).replace('T', ' ')}</Tag>
            <button className="tool-btn" title="delete this doc and every block in it" onClick={() => delDoc(doc.id)}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={title} onChange={(ev) => setTitle(ev.target.value)} placeholder="doc title" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={create}>new doc</button>
      </div>
      {tree && <div style={{ marginTop: 8 }}>
        <NoteBlockRows nodes={tree.children} onEdit={(n) => { setEditing(n.id); setBlockText(n.text || ''); }} onDelete={delBlock} />
        {editing && <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input value={blockText} onChange={(ev) => setBlockText(ev.target.value)} placeholder="block text" style={{ ...inpS, flex: 1 }} />
          <button className="tool-btn" onClick={saveBlock}>save block</button>
          <button className="tool-btn" onClick={() => setEditing(null)}>cancel</button>
        </div>}
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input value={newBlock} onChange={(ev) => setNewBlock(ev.target.value)} placeholder="new block…" style={{ ...inpS, flex: 1 }} />
          <button className="tool-btn" onClick={addBlock}>add block</button>
        </div>
      </div>}
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
        Stable block ids · ✕ on a block removes its whole subtree · inserting never renumbers siblings.
      </div>
    </Card>
  );
}

/* T-0.20 — the encrypted personal blob vault (GET/POST/DELETE /api/vault[/{id}],
   user-guarded). Text is stored via the textarea; binary via the file picker.
   Content is fetched only on an explicit "get" (never in the listing) and
   downloaded client-side as a Blob — the list/put responses never carry
   plaintext, mirroring the router's own no-leak contract. */
export function VaultPanel() {
  const { d, e, loading, reload } = useApi('/api/vault');
  const items = arr(d, 'items');
  const stats = (d && d.stats) || {};
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [note, setNote] = useState('');

  const putB64 = (dataB64, itemName, kind) => act('/api/vault', { name: itemName, kind, data_base64: dataB64 }, () => { setNote('stored'); reload(); });
  const storeText = () => {
    if (!text.trim()) return;
    putB64(btoa(unescape(encodeURIComponent(text))), name || 'note', 'note');
    setText(''); setName('');
  };
  const storeFile = () => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      putB64(result.slice(result.indexOf(',') + 1), file.name, 'file');
      setFile(null);
    };
    reader.readAsDataURL(file);
  };
  const download = (id, itemName) => {
    apiGet('/api/vault/' + encodeURIComponent(id)).then((r: any) => {
      if (!r || !r.data_base64) { setNote('fetch failed'); return; }
      const bin = atob(r.data_base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes]));
      const a = document.createElement('a');
      a.href = url; a.download = itemName || id;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    }).catch(() => setNote('fetch failed'));
  };
  const del = (id) => apiDelete('/api/vault/' + encodeURIComponent(id)).then(reload).catch(() => {});

  return (
    <Card title="VAULT" live={asLive(d)} sub={d ? `${stats.items || 0} items · ${Math.round((stats.bytes || 0) / 1024)} KB` : null} onReload={reload}>
      <State e={e} loading={loading} n={items.length} />
      {items.slice(0, 10).map((it) => (
        <Row key={it.id}>
          <span style={{ color: 'var(--accent-light)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.name || it.id}</span>
          <Tag>{it.kind}</Tag>
          <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{it.bytes}B</span>
          <button className="tool-btn" onClick={() => download(it.id, it.name)}>get</button>
          <button className="tool-btn" onClick={() => del(it.id)}>del</button>
        </Row>
      ))}
      <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="text to encrypt and store…" style={{ ...taS, marginTop: 6, minHeight: 50 }} />
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="name" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" disabled={!text.trim()} onClick={storeText}>store text</button>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
        <input type="file" onChange={(ev) => setFile(ev.target.files && ev.target.files[0])} style={{ fontSize: 10, flex: 1 }} />
        <button className="tool-btn" disabled={!file} onClick={storeFile}>store file</button>
      </div>
      {note && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>{note}</div>}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>encrypted at rest · included in your own data export, erased on forget</div>
    </Card>
  );
}

function ReflectionPanel() {
  const { d, e, loading, reload } = useApi('/api/reflection/status');
  const [out, setOut] = useState(null);
  const run = () => { setOut('running…'); act('/api/reflection/run', {}, (r) => { setOut(r?.ok ? (r.result || 'done') : (r?.error || 'failed')); reload(); }); };
  return <Card title="NIGHTLY REFLECTION" live={asLive(d, d?.enabled)} onReload={reload}>
    <State e={e} loading={loading} n={d ? 1 : 0} />
    {d && <div style={{ ...mono, fontSize: 11 }}>
      <Row><span>enabled</span><span style={{ marginLeft: 'auto', color: d.enabled ? 'var(--green)' : 'var(--ink-3)' }}>{String(!!d.enabled)}</span></Row>
      <Row><span>last run</span><span style={{ marginLeft: 'auto', color: 'var(--ink-3)' }}>{d.last_run || 'never'}</span></Row>
    </div>}
    <button className="tool-btn" style={{ marginTop: 6 }} onClick={run}>run now</button>
    {out != null && <Json v={out} max={120} />}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>last 60 turns → entities/relations/lessons → KG (H5.15)</div>
  </Card>;
}

/* ── Trust / Security ───────────────────────────────────── */
export function PairingPanel() {
  const { d, e, loading, reload } = useApi('/api/channels/pairing', true, true);
  const senders = arr(d, 'senders');
  const [code, setCode] = useState('');
  const decide = (s, action) => actA('/api/channels/pairing/decide', { channel: s.channel, sender_id: s.sender_id || s.id, action }, reload);
  return <Card title="SENDER PAIRING" live={asLive(d)} sub={d?.summary ? (d.summary.pending ?? senders.length) + ' pending' : senders.length} onReload={reload}>
    <State e={e} loading={loading} n={senders.length} />
    {senders.slice(0, 10).map((s, i) => <Row key={i}>
      <span style={mono}>{s.name || s.sender_id || s.id}</span>
      <Tag>{s.channel}</Tag>
      <Tag c={s.status === 'paired' ? 'var(--green)' : s.status === 'blocked' ? 'var(--red)' : 'var(--amber)'}>{s.status || 'pending'}</Tag>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
        {s.status !== 'paired' && <button className="tool-btn" title="approve" onClick={() => decide(s, 'approve')}>✓</button>}
        {s.status !== 'blocked' && <button className="tool-btn" title="block" onClick={() => decide(s, 'block')}>⛔</button>}
        {s.status === 'paired' ? <button className="tool-btn" title="unpair" onClick={() => decide(s, 'unpair')}>✕</button>
          : <button className="tool-btn" title="reject" onClick={() => decide(s, 'reject')}>✕</button>}
      </span></Row>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={code} onChange={(ev) => setCode(ev.target.value)} placeholder="pairing code (empty = clear)" style={{ ...inpS, flex: 1 }} />
      <button className="tool-btn" onClick={() => actA('/api/channels/pairing/code', { code: code || null }, () => { setCode(''); reload(); })}>set code</button>
    </div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>unknown senders are held until you decide (H12.19)</div>
  </Card>;
}
function InjectionScanPanel() {
  const [text, setText] = useState('');
  const [out, setOut] = useState(null);
  const scan = () => act('/api/security/scan-injection', { text }, setOut);
  return <Card title="INJECTION SCAN" live={'live'}>
    <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="paste suspect text — emails, skill output, web content…" style={taS} />
    <button className="tool-btn" style={{ marginTop: 6 }} onClick={scan}>scan</button>
    {out && <div style={{ ...mono, fontSize: 11, marginTop: 6, color: out.suspicious ? 'var(--red)' : 'var(--green)' }}>
      {out.suspicious ? '⚠ ' + (out.flags || []).length + ' pattern(s): ' + (out.flags || []).join(', ') : '✓ clean — no injection patterns'}
    </div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>prompt-injection detector (H17.1) — same engine as the quarantine gate</div>
  </Card>;
}
function SecretsPanel() {
  const { d, e, loading, reload } = useApi('/api/secrets/broker');
  const names = arr(d, 'names', 'secrets');
  const [nm, setNm] = useState(''); const [vl, setVl] = useState('');
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11 };
  const store = () => { if (!nm.trim()) return; apiPost('/api/secrets/broker', { name: nm.trim(), value: vl }, { admin: true }).then(() => { setNm(''); setVl(''); reload(); }).catch(() => {}); };
  return <Card title="SECRET BROKER" live={asLive(d)} sub={names.length} onReload={reload}>
    <State e={e} loading={loading} n={names.length} />
    {names.slice(0, 12).map((n, i) => <Row key={i}><span style={mono}>{n.name || n}</span><Btn onClick={() => apiDelete('/api/secrets/broker/' + (n.name || n), { admin: true }).then(reload).catch(() => {})}>✕</Btn></Row>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={nm} onChange={(ev) => setNm(ev.target.value)} placeholder="NAME" style={{ ...inp, flex: '0 0 38%' }} />
      <input value={vl} onChange={(ev) => setVl(ev.target.value)} placeholder="value" type="password" style={{ ...inp, flex: 1 }} />
      <button className="tool-btn" onClick={store}>store</button>
    </div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>just-in-time {'{{secret:NAME}}'} injection at approval time</div>
  </Card>;
}
export function KillSwitchPanel() {
  const { d, e, loading, reload } = useApi('/api/security/kill-switch');
  // /api/security/kill-switch returns {global: bool, halted: {agent: reason}}. `halted`
  // is a MAP, not a bool — `d?.halted ?? d?.engaged` returned {} (truthy) and showed a
  // false "ENGAGED · all agents halted" alarm (2026-07-24 QA finding). Derive it: engaged
  // iff the global switch is on OR at least one agent is in the halted map.
  const halted = !!(d?.global || Object.keys(d?.halted || {}).length || d?.engaged);
  // Whether we actually READ the state. Without this, `halted` is false while the
  // status is still in flight or the read failed outright, and the row below
  // rendered a green "ARMED · operational" — telling the operator the safety
  // system is fine on the strength of a request that never came back. For a
  // kill-switch that is the worst possible default.
  const known = !!d && !e;
  // A halt that silently fails is worse than no button: the operator believes the system
  // is stopped. Always re-read state after the attempt, and say so loudly if it was refused.
  const [actErr, setActErr] = useState('');
  const toggle = () => {
    setActErr('');
    actA('/api/security/kill-switch', { engage: !halted, scope: 'global', reason: 'hud' },
      reload,
      (err) => { setActErr(String(err?.message || err || 'request failed')); reload(); });
  };
  return <Card title="KILL-SWITCH" live={asLive(d)} onReload={reload}>
    <State e={e} loading={loading} n={known ? 1 : 0} />
    <Row><span style={{ color: !known ? 'var(--amber)' : halted ? 'var(--red)' : 'var(--green)' }}>
      {!known ? 'UNKNOWN · could not read kill-switch state'
        : halted ? 'ENGAGED · all agents halted' : 'ARMED · operational'}</span>
      {/* The button stays live even when the state is unknown: with `halted` false
          it sends engage=true, and halting on an unknown state is the safe
          direction. Only the claim about current state is withheld. */}
      <Btn onClick={toggle}>{halted ? 'disengage' : 'HALT ALL'}</Btn></Row>
    {actErr && <Row><span role="alert" style={{ ...mono, color: 'var(--red)' }}>
      {halted ? 'DISENGAGE' : 'HALT'} REFUSED · {actErr} · the switch did NOT change state
    </span></Row>}
  </Card>;
}
/* HUD-v3 (0.42 Security Skills pack) — browse the curated, offline ATT&CK knowledge.
   The pack (frameworks/tactics/techniques, all read-only + clearly curated) had no UI;
   this is a Trust-surface knowledge browser: ATT&CK tactics, each expandable to its
   curated techniques. Read-only, user-guarded; nothing is fabricated (the pack carries
   its own DISCLAIMER + SOURCES). */
export function SecuritySkillsPanel() {
  const { d, e, loading, reload } = useApi('/api/security-skills/tactics');
  const tactics = arr(d, 'tactics');
  const [open, setOpen] = useState(null);   // expanded tactic id
  const [techs, setTechs] = useState([]);
  const toggle = (tid) => {
    if (open === tid) { setOpen(null); return; }
    setOpen(tid); setTechs([]);
    apiGet('/api/security-skills/techniques?tactic=' + encodeURIComponent(tid))
      .then((r) => setTechs(arr(r, 'techniques'))).catch(() => setTechs([]));
  };
  return (
    <Card title="SECURITY SKILLS" live={asLive(d)} sub={d ? `${tactics.length} ATT&CK tactics` : null} onReload={reload}>
      <State e={e} loading={loading} n={tactics.length} />
      {tactics.slice(0, 14).map((t, i) => (
        <div key={t.id ?? i}>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)', cursor: 'pointer' }} onClick={() => toggle(t.id)}>{t.id} · {t.name}</span>
            <span style={{ marginLeft: 'auto' }}><Tag>{open === t.id ? '▾' : '▸'}</Tag></span>
          </Row>
          {open === t.id && techs.slice(0, 10).map((tech, j) => (
            <div key={tech.id ?? j} style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', padding: '2px 0 2px 14px' }}>{tech.id} · {tech.name}</div>
          ))}
          {open === t.id && techs.length === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', padding: '2px 0 2px 14px' }}>no curated techniques for this tactic</div>}
        </div>
      ))}
    </Card>
  );
}
export function CapabilitiesPanel() {
  const [caps, setCaps] = useState('fs.read,memory.write'); const [out, setOut] = useState(null);
  const [issued, setIssued] = useState([]);
  const [checkToken, setCheckToken] = useState(''); const [checkCap, setCheckCap] = useState('memory.write');
  const [checkOut, setCheckOut] = useState(null);
  const issue = () => {
    const parsed = caps.split(',').map((s) => s.trim()).filter(Boolean);
    if (!parsed.length) return;
    actA('/api/security/capabilities/issue', { capabilities: parsed }, (r) => {
      setOut(JSON.stringify(r));
      if (r?.token) {
        setIssued((prev) => [r.token, ...prev.filter((t) => t.id !== r.token.id)].slice(0, 5));
        setCheckToken(r.token.id || '');
        setCheckCap((r.token.capabilities || [checkCap])[0] || checkCap);
      }
    });
  };
  const check = () => {
    const token = checkToken.trim(); const cap = checkCap.trim();
    if (!token || !cap) return;
    apiGet('/api/security/capabilities/check?token=' + encodeURIComponent(token) + '&capability=' + encodeURIComponent(cap))
      .then(setCheckOut)
      .catch((err) => setCheckOut({ allowed: false, reason: err?.message || 'check failed' }));
  };
  return <Card title="CAPABILITY TOKENS" live={'live'}>
    <input value={caps} onChange={(e) => setCaps(e.target.value)} placeholder="capabilities csv" style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono }} />
    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
      <button className="tool-btn" onClick={issue}>issue</button>
    </div>
    {issued.length > 0 && <div style={{ marginTop: 8 }}>
      <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, marginBottom: 4 }}>RECENT GRANTS</div>
      {issued.map((t, i) => <Row key={t.id || i}>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>{t.id}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {(t.capabilities || []).map((c) => <Tag key={c} c="var(--accent-light)">{c}</Tag>)}
        </span>
      </Row>)}
    </div>}
    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
      <input value={checkToken} onChange={(e) => setCheckToken(e.target.value)} placeholder="token id" style={{ ...inpS, flex: 1, minWidth: 120 }} />
      <input value={checkCap} onChange={(e) => setCheckCap(e.target.value)} placeholder="capability to check" style={{ ...inpS, flex: 1, minWidth: 120 }} />
      <button className="tool-btn" onClick={check}>check</button>
    </div>
    {checkOut && <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
      <Tag c={checkOut.allowed ? 'var(--green)' : 'var(--red)'}>{checkOut.allowed ? 'allowed' : 'blocked'}</Tag>
      <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>{checkOut.reason || 'token grants capability'}</span>
    </div>}
    {out && <pre style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', whiteSpace: 'pre-wrap', marginTop: 6 }}>{out.slice(0, 200)}</pre>}
  </Card>;
}

export function KernelMetricsPanel() {
  const { d, e, loading, reload } = useApi('/api/metrics/kernel');
  const v = (d && d.by_verdict) || {};
  const denials = (d && d.recent_denials) || [];
  return (
    <Card title="ACTION KERNEL" live={asLive(d, d?.enabled ?? d?.total > 0)} sub={d ? `${d.total} decisions` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? d.total : 0} />
      {d && (
        <Row>
          <span style={mono}>verdicts</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--green)">{v.grant || 0} grant</Tag>
            <Tag c="var(--amber)">{v.queue || 0} queue</Tag>
            <Tag c={(v.deny || 0) > 0 ? 'var(--red)' : 'var(--ink-3)'}>{v.deny || 0} deny</Tag>
          </span>
        </Row>
      )}
      {denials.slice(0, 8).map((dn, i) => (
        <Row key={i}>
          <span style={{ ...mono, color: 'var(--red)' }}>{dn.kind}</span>
          <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(dn.reason || '').slice(0, 48)}</span>
        </Row>
      ))}
      {d && d.total === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_ACTION_KERNEL is on</div>}
    </Card>
  );
}
/* HUD-v3 B3 / H27.8 — Capability Registry board. Reads the canonical user-facing registry
   (GET /api/capabilities): the SEAM→WIRED→VERIFIED→GA ladder. Honesty contract —
   nothing is VERIFIED until a green reality-harness promotes it, so `harness_pending`
   renders "wired, not yet proven" rather than implying verification we can't back. */
export function ReadinessPanel() {
  const { d, e, loading, reload } = useApi('/api/capabilities');
  const bs = (d && d.by_state) || {};
  const caps = (d && d.capabilities) || [];
  const pending = d && d.harness_pending;
  const stateColor = (s) => (s === 'verified' || s === 'ga') ? 'var(--green)' : s === 'wired' ? 'var(--accent-light)' : 'var(--ink-3)';
  return (
    <Card title="VERIFICATION FABRIC" live={asLive(d)} sub={d ? `${d.total} capabilities` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? d.total : 0} />
      {d && (
        <Row>
          <span style={mono}>readiness</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--ink-3)">{bs.seam || 0} seam</Tag>
            <Tag c="var(--accent-light)">{bs.wired || 0} wired</Tag>
            <Tag c={(bs.verified || 0) > 0 ? 'var(--green)' : 'var(--ink-3)'}>{bs.verified || 0} verified</Tag>
            <Tag c={(bs.ga || 0) > 0 ? 'var(--green)' : 'var(--ink-3)'}>{bs.ga || 0} ga</Tag>
          </span>
        </Row>
      )}
      {pending && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>harness pending · wired, not yet proven — nothing is VERIFIED until a green reality-harness promotes it</div>}
      {caps.slice(0, 8).map((c, i) => {
        const confidence = typeof c.confidence === 'number'
          ? Math.round(Math.max(0, Math.min(1, c.confidence)) * 100) + '%' : '—';
        const supports = Array.isArray(c.supports) && c.supports.length
          ? c.supports.slice(0, 3).join(' · ') : '—';
        return <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>
          <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.id}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              <Tag c={c.risk === 'irreversible_or_money' ? 'var(--red)' : c.risk === 'sensitive' ? 'var(--amber)' : 'var(--ink-3)'}>{c.risk || 'read_only'}</Tag>
              <Tag c={stateColor(c.state)}>{c.state}</Tag>
              <Tag c={Number(c.confidence) > 0 ? 'var(--green)' : 'var(--ink-3)'}>{confidence}</Tag>
            </span>
          </div>
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)', marginTop: 3 }}>{supports}</div>
        </div>;
      })}
    </Card>
  );
}
export function LoopBreakerPanel() {
  const { d, e, loading, reload } = useApi('/api/security/loop-breaker');
  const tripped = d?.tripped;
  return (
    <Card title="LOOP BREAKER" live={asLive(d)} sub={d ? (tripped ? 'TRIPPED' : 'closed') : null} onReload={reload}>
      <State e={e} loading={loading} n={1} />
      {d && (
        <Row>
          <span style={{ color: tripped ? 'var(--red)' : 'var(--green)' }}>{tripped ? 'OPEN · runaway halted' : 'closed · normal'}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag>{d.max_repeats}/{d.window_seconds}s</Tag>
            {tripped && <button className="tool-btn" onClick={() => actA('/api/security/loop-breaker/reset', {}, reload)}>reset</button>}
          </span>
        </Row>
      )}
    </Card>
  );
}

/* HUD-v3 C6 (governance + posture half; loop-breaker already shipped). Two read-only
   Trust panels surfacing the security scorecard + packaged posture — neither had a
   control surface. Honesty: every number is the real suite/registry result. */
export function GovernancePanel() {
  const { d, e, loading, reload } = useApi('/api/security/governance');  // open (public scorecard)
  const suites = d ? [['injection', d.injection], ['harm', d.harm], ['owasp', d.owasp]].filter((x) => x[1]) : [];
  const pct = (s) => s && typeof s.score === 'number' ? Math.round(s.score * 100) + '%' : '—';
  return (
    <Card title="GOVERNANCE SCORECARD" live={asLive(d)} sub={d ? (d.pass ? 'gate: pass' : 'gate: FAIL') : null} onReload={reload}>
      <State e={e} loading={loading} n={suites.length} />
      {d && (
        <Row>
          <span style={mono}>overall</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={d.pass ? 'var(--green)' : 'var(--red)'}>{typeof d.overall_score === 'number' ? Math.round(d.overall_score * 100) + '%' : '—'}</Tag>
            <Tag>≥ {typeof d.threshold === 'number' ? Math.round(d.threshold * 100) + '%' : '—'}</Tag>
          </span>
        </Row>
      )}
      {suites.map((x) => (
        <Row key={x[0]}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{x[0]}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={(x[1].passed === x[1].n) ? 'var(--green)' : 'var(--amber)'}>{x[1].passed}/{x[1].n}</Tag>
            <Tag>{pct(x[1])}</Tag>
          </span>
        </Row>
      ))}
    </Card>
  );
}
export function PosturePanel() {
  const { d, e, loading, reload } = useApi('/api/security/posture', true, true);  // admin-guarded
  const sec = (d && d.secrets) || {};
  const sk = (d && d.skills) || {};
  const sb = (d && d.sandbox) || {};
  return (
    <Card title="SECURITY POSTURE" live={asLive(d)} sub={d && d.guardrails ? `guardrails: ${d.guardrails.mode}` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>secrets at rest</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {/* Three states. `encrypted_at_rest` is null when the secret store
                  could not be opened — rendering that as "plain" would be its own
                  false claim (we do not know the secrets are in plaintext, we know
                  we could not look). It used to be neither: the endpoint returned a
                  hardcoded `true`, so this tag was always green. */}
              <Tag c={sec.encrypted_at_rest == null ? 'var(--amber)'
                      : sec.encrypted_at_rest ? 'var(--green)' : 'var(--red)'}>
                {sec.encrypted_at_rest == null ? 'unknown'
                  : sec.encrypted_at_rest ? 'encrypted' : 'plain'}
              </Tag>
              <Tag>{sec.backend || '—'}</Tag>
            </span>
          </Row>
          <Row><span style={mono}>skill signing</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={sk.require_signed ? 'var(--green)' : 'var(--ink-3)'}>{sk.require_signed ? 'required' : 'optional'}</Tag>
              <Tag c={(sk.untrusted ?? 0) > 0 ? 'var(--amber)' : 'var(--green)'}>{sk.trusted ?? 0}/{sk.total ?? 0} trusted</Tag>
            </span>
          </Row>
          <Row><span style={mono}>sandbox</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={sb.isolated ? 'var(--green)' : 'var(--amber)'}>{sb.isolated ? 'isolated' : 'host'}</Tag>
              {sb.docker_available && <Tag>docker</Tag>}
            </span>
          </Row>
        </>
      )}
    </Card>
  );
}

/* DRA-36 (H17.4) — the transparency-anchor half of the tamper-evidence story. The Trust
   Center already renders the sibling `/api/security/audit/verify` badge, but
   `GET /api/security/audit/anchors` and `POST /api/security/audit/anchor` had no caller in
   any client: the receipts that let the audit chain be checked from OUTSIDE the process
   existed only as a file on disk.

   Honesty contract: `TransparencyAnchor.verify()` returns ok:true over an EMPTY log (zero
   rows chain trivially), so an empty anchor log renders "nothing anchored yet" and the amber
   SEED chip — never a green verified chain. "Nothing to check" is not "checked". */
export function AuditAnchorsPanel() {
  const { d, e, loading, reload } = useApi('/api/security/audit/anchors');  // user-guarded read
  const anchors = arr(d, 'anchors');
  const v = (d && d.verify) || {};
  const n = v.n ?? anchors.length;
  const [note, setNote] = useState(null);
  const short = (h) => (h ? String(h).slice(0, 12) : '—');
  const when = (ts) => {
    const t = Number(ts);
    if (!Number.isFinite(t) || t <= 0) return '—';
    try { return new Date(t * 1000).toISOString().replace('T', ' ').slice(0, 19); } catch { return '—'; }
  };
  return (
    <Card title="AUDIT ANCHORS" live={asLive(d, n > 0)} sub={d ? `${n} receipt(s)` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>chain</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {n === 0
                ? <Tag c="var(--ink-3)">nothing anchored yet</Tag>
                : v.ok === false
                  ? <Tag c="var(--red)">chain broken @ #{v.bad_seq ?? '?'}</Tag>
                  : <Tag c="var(--green)">anchor chain intact · {n} receipt(s)</Tag>}
            </span>
          </Row>
          {anchors.slice(0, 10).map((a, i) => (
            <Row key={a.anchor_hash || i}>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>#{a.seq}</span>
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{when(a.ts)}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag>{a.source || '—'}</Tag>
                <Tag>root {short(a.root)}</Tag>
                <Tag>anchor {short(a.anchor_hash)}</Tag>
              </span>
            </Row>
          ))}
          <Row>
            <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>anchor the current chain head into the transparency log</span>
            <button
              className="tool-btn" style={{ marginLeft: 'auto' }} title="anchor now (admin)"
              onClick={() => actA('/api/security/audit/anchor', {},
                (r) => { setNote(`anchored · receipt #${(r && r.receipt && r.receipt.seq) ?? '?'}`); reload(); },
                (err) => setNote(`refused · ${err?.message || 'anchor failed'}`))}
            >anchor now</button>
          </Row>
          {note && <div role="alert" style={{ ...mono, marginTop: 6, color: note.startsWith('refused') ? 'var(--red)' : 'var(--green)' }}>{note}</div>}
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
            Receipts are hash-linked, so a rewritten anchor log is detectable — but the log is
            local: anchoring pins ordering, it does not publish to a third party (H17.4).
          </div>
        </>
      )}
    </Card>
  );
}

/* Self-Improvement dashboard — read-only aggregation of subsystems that already
   exist (error diagnostics, the resource/service Observer, H32 Capability
   Acquisition, H33 Ambient Intelligence, the Proactive Technology Scout), plus a
   one-button convenience toggle for the documented enable-bundle (each flag it
   flips already exists and is individually admin-settable; see
   docs/OWNER_TASKS.md). Admin-guarded like PosturePanel — the aggregation can
   surface internal diagnostic detail. */
export function SelfImprovementPanel() {
  const { d, e, loading, reload } = useApi('/api/self-improvement/status', true, true);  // admin-guarded
  const errors = (d && d.errors) || {};
  const observer = (d && d.observer) || {};
  const acquisition = (d && d.acquisition) || {};
  const ambient = (d && d.ambient) || {};
  const techScout = (d && d.tech_scout) || {};
  const allOn = observer.enabled && acquisition.enabled && ambient.enabled && techScout.enabled;
  return (
    <Card title="SELF-IMPROVEMENT" live={asLive(d)} sub={d ? `${errors.active_groups ?? 0} active error group(s)` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>errors (48h)</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={(errors.active_groups ?? 0) > 0 ? 'var(--amber)' : 'var(--green)'}>{errors.active_groups ?? 0} groups</Tag>
            </span>
          </Row>
          <Row><span style={mono}>observer</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={observer.enabled ? 'var(--green)' : 'var(--ink-3)'}>{observer.enabled ? 'on' : 'off'}</Tag>
              <Tag>{(observer.unhealthy || []).length} unhealthy</Tag>
            </span>
          </Row>
          <Row><span style={mono}>capability acquisition</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={acquisition.enabled ? 'var(--green)' : 'var(--ink-3)'}>{acquisition.enabled ? 'on' : 'off'}</Tag>
              <Tag>{acquisition.status || '—'}</Tag>
            </span>
          </Row>
          <Row><span style={mono}>ambient monitors</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={ambient.enabled ? 'var(--green)' : 'var(--ink-3)'}>{ambient.enabled ? 'on' : 'off'}</Tag>
              <Tag>{ambient.monitors ?? 0} monitor(s)</Tag>
            </span>
          </Row>
          <Row><span style={mono}>tech scout</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={techScout.enabled ? 'var(--green)' : 'var(--ink-3)'}>{techScout.enabled ? 'on' : 'off'}</Tag>
              <Tag>{techScout.last_run ? 'ran' : 'never run'}</Tag>
            </span>
          </Row>
          {!allOn && (
            <Row><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>flip the documented owner opt-ins</span>
              <Btn onClick={() => actA('/api/self-improvement/enable', {}, reload)}>enable bundle</Btn></Row>
          )}
        </>
      )}
    </Card>
  );
}

/* DRA-17 — CDX-8: the owner-approval gate for LLM-authored skill code was backend-only.
   `GET /api/skills/pending` + `POST /api/skills/{name}/approve` (both admin) shipped with no
   client caller at all, so the tail of the self-improvement loop terminated in a directory
   nobody could see. A quarantined skill IS registered — visible and reviewable — but
   `loader.py` never exec's its module in-process while `PENDING_REVIEW` exists, so nothing
   here is running code; approving is what promotes it.

   Approve-only, deliberately. There is no reject endpoint and this does not invent one:
   quarantine is already the fail-closed state, so leaving a skill unapproved IS the reject.
   Sits beside SELF-IMPROVEMENT rather than the marketplace panels — the marketplace has its
   own `review_status` path for third-party skills, and merging the two surfaces would imply
   they share a mechanism they do not. */
export function PendingSkillsPanel() {
  const { d, e, loading, reload } = useApi('/api/skills/pending', true, true);  // admin-guarded
  const pending = arr(d, 'pending');
  return (
    <Card title="GENERATED SKILLS — PENDING REVIEW" live={asLive(d)} sub={pending.length} onReload={reload}>
      <State e={e} loading={loading} n={pending.length} />
      {pending.slice(0, 10).map((s, i) => (
        <Row key={i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{s.name}</span>
          <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(s.description || '').slice(0, 40)}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--amber)">quarantined</Tag>
            {arr(s, 'agents').length > 0 && <Tag c="var(--ink-3)">{arr(s, 'agents').length} agent(s)</Tag>}
            <button
              className="tool-btn"
              title="approve — sign and activate this generated skill"
              onClick={() => actA(`/api/skills/${encodeURIComponent(s.name)}/approve`, {}, reload)}
            >✓</button>
          </span>
        </Row>
      ))}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
        LLM-authored code, never exec&apos;d in-process until approved — ✓ signs and activates it (CDX-8).
        No reject action: leaving a skill here is the safe outcome.
      </div>
    </Card>
  );
}

/* Per-module row for COGNITION. A module answering `available: false` is rendered as
   "unavailable" and never as a zero — "the module is not there" and "the module reports
   nothing yet" are different facts, and collapsing them is how a dead subsystem comes to
   look merely idle. */
const CogModule = ({ label, s, children }: { label: any; s: any; children?: any }) => (
  <Row>
    <span style={mono}>{label}</span>
    <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
      {s == null ? <Tag>loading…</Tag>
        : s.available === false ? <Tag c="var(--amber)">unavailable</Tag>
        : children}
    </span>
  </Row>
);

/* DRA-15 (H21 cognition cut) — the six user-tier cognition reads
   (/api/cognition/status | honesty | personality | memory | learning | ensemble) shipped
   with no client caller anywhere, so the whole H21 subsystem was a backend with no window.
   This is the window; it is read-only.

   Two deliberate honesty properties. (1) The flags gate cognition BEHAVIOUR, not these
   reads — every registered module reports even while the master flag is off, so the panel
   wears the amber SEED chip when cognition is off rather than pretending the reads are
   meaningless or hiding them. (2) There is no enable button: the cognition flags are admin
   *settings* (`cognition.*`), not a route, so unlike /api/self-improvement/enable there is
   nothing honest to POST here. Sits beside SELF-IMPROVEMENT (the other "what is the
   self-improving half actually doing" read), not beside the /learning bench-promotion
   panel, which is an unrelated mechanism. */
export function CognitionPanel() {
  const st = useApi('/api/cognition/status');
  const hon = useApi('/api/cognition/honesty');
  const per = useApi('/api/cognition/personality');
  const mem = useApi('/api/cognition/memory');
  const lrn = useApi('/api/cognition/learning');
  const ens = useApi('/api/cognition/ensemble');
  const flags = (st.d && st.d.flags) || {};
  const flagKeys = Object.keys(flags);
  const onCount = flagKeys.filter((k) => flags[k]).length;
  const reloadAll = () => { st.reload(); hon.reload(); per.reload(); mem.reload(); lrn.reload(); ens.reload(); };
  const num = (x) => (x == null ? '—' : Number(x).toFixed(2));
  return (
    <Card
      title="COGNITION (H21)"
      live={asLive(st.d, st.d && st.d.enabled)}
      sub={st.d ? `${onCount}/${flagKeys.length || 6} on` : null}
      onReload={reloadAll}
    >
      <State e={st.e} loading={st.loading} n={st.d ? 1 : 0} />
      {st.d && (
        <>
          <Row><span style={mono}>master</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={st.d.enabled ? 'var(--green)' : 'var(--ink-3)'}>{st.d.enabled ? 'on' : 'off'}</Tag>
              <Tag>{arr(st.d, 'modules').length} module(s) registered</Tag>
            </span>
          </Row>
          {flagKeys.map((k) => (
            <Row key={k}>
              <span style={mono}>{k.replace(/_enabled$/, '')}</span>
              <span style={{ marginLeft: 'auto' }}>
                <Tag c={flags[k] ? 'var(--green)' : 'var(--ink-3)'}>{flags[k] ? 'on' : 'off'}</Tag>
              </span>
            </Row>
          ))}
          <CogModule label="honesty index" s={hon.d}>
            <Tag c={hon.d && hon.d.alerting ? 'var(--amber)' : 'var(--ink-3)'}>sycophancy {num(hon.d && hon.d.sycophancy_index)}</Tag>
            {hon.d && hon.d.alerting ? <Tag c="var(--red)">alerting</Tag> : null}
            <Tag>{(hon.d && hon.d.n) ?? 0} sample(s)</Tag>
          </CogModule>
          <CogModule label="personality" s={per.d}>
            <Tag>{arr(per.d, 'agents').length} persona(s)</Tag>
          </CogModule>
          <CogModule label="living memory" s={mem.d}>
            <Tag>core {(mem.d && mem.d.core) ?? 0} · user {(mem.d && mem.d.user_core) ?? 0}</Tag>
            <Tag>embed {(mem.d && mem.d.embed_version) || '—'}</Tag>
          </CogModule>
          <CogModule label="governed learning" s={lrn.d}>
            <Tag>{(lrn.d && lrn.d.kc_count) ?? 0} kc</Tag>
            <Tag>{(lrn.d && lrn.d.corrections) ?? 0} correction(s)</Tag>
            {lrn.d && lrn.d.review ? <Tag>review loop</Tag> : null}
            {lrn.d && lrn.d.curator ? <Tag>curator</Tag> : null}
            {lrn.d && lrn.d.skill_proposals ? <Tag>skill proposals</Tag> : null}
          </CogModule>
          <CogModule label="ensemble" s={ens.d}>
            <Tag>{arr(ens.d, 'agents').length} agent(s)</Tag>
            <Tag>diversity {num(ens.d && ens.d.diversity)}</Tag>
          </CogModule>
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
            The modules are registered and reporting even while the flags are off — the flags
            gate cognition behaviour, not these reads. No toggle here: the cognition flags are
            admin settings (cognition.*), not an endpoint.
          </div>
        </>
      )}
    </Card>
  );
}

/* H34.4 — SwarmPanel: a compact read-only Console/Observe view over the H34.1
   swarm feed (`GET /api/swarm/summary`, open/user-tier), so the cabinet, the
   autonomy funnel and the *dev* swarm (Claude/Codex/opencode/Antigravity via
   `lock.py`) are one keystroke from chat. Pure read — no new route, no
   mutating control; the full HITL cockpit stays the standalone
   `/mission-control` page this panel links out to. */
export function SwarmPanel() {
  const { d, e, loading, reload } = useApi('/api/swarm/summary');  // open
  const agents = arr(d, 'agents');
  const activeAgents = agents.filter((a) => (a.events || 0) > 0).length;
  const autonomy = (d && d.autonomy) || {};
  const missions = arr(d, 'missions');
  const runs = arr((d && d.workflows) || {}, 'runs');
  const subagents = (d && d.subagents) || {};
  const a2a = (d && d.a2a) || {};
  const locks = (d && d.dev_locks) || {};
  const lockedAgents = arr(locks, 'agents');
  const knownDev = arr(locks, 'known');
  return (
    <Card
      title="MISSION CONTROL"
      live={asLive(d, d && d.initialized)}
      sub={d ? `${autonomy.pending_count ?? 0} pending decision${(autonomy.pending_count ?? 0) === 1 ? '' : 's'}` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>kernel</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={d.halted === true ? 'var(--red)' : d.halted === false ? 'var(--green)' : undefined}>
                {d.halted === true ? 'HALTED' : d.halted === false ? 'armed' : '—'}
              </Tag>
              <Tag>{activeAgents}/{agents.length} agents active</Tag>
            </span>
          </Row>
          <Row><span style={mono}>autonomy</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag>{autonomy.mode || '—'}</Tag>
              <Tag c={(autonomy.pending_count ?? 0) > 0 ? 'var(--amber)' : 'var(--green)'}>{autonomy.pending_count ?? 0} pending</Tag>
            </span>
          </Row>
          <Row><span style={mono}>workspaces</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag>{missions.length} missions</Tag>
              <Tag>{runs.length} workflow runs</Tag>
              <Tag>{subagents.spawns ?? 0} sub-agents</Tag>
            </span>
          </Row>
          {a2a.enabled && (
            <Row><span style={mono}>a2a inbox</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag c={(a2a.pending ?? 0) > 0 ? 'var(--amber)' : 'var(--green)'}>{a2a.pending ?? 0} pending</Tag>
              </span>
            </Row>
          )}
          <Row><span style={mono}>dev swarm</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              {locks.available ? knownDev.map((name) => {
                const on = lockedAgents.some((l) => l.agent === name && !l.stale);
                return <Tag key={name} c={on ? 'var(--green)' : 'var(--ink-3)'}>{name}</Tag>;
              }) : <Tag>no lock data</Tag>}
            </span>
          </Row>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <a className="tool-btn" href="/mission-control" target="_blank" rel="noopener noreferrer">open full cockpit →</a>
          </div>
        </>
      )}
    </Card>
  );
}

/* DRA-36 (H20.6) — the sub-agent spawn register. `GET /api/subagents` and
   `POST /api/subagents/spawn` had no caller: MISSION CONTROL rendered `subagents.spawns` as
   a bare integer, so a register with concurrency, recursion-depth and budget caps could be
   neither listed nor used.

   The spawn control is deliberately NOT presented as instant. `SubAgentManager.spawn`
   awaits the sub-agent's ENTIRE turn inside the POST, so the request stays open for as long
   as that turn runs (minutes, for a long task); the button locks while it is in flight and
   the panel says why. Every cap refusal answers 429 and `apiPost` throws on 4xx, so the call
   passes an `onErr` — without it a refused spawn would silently read as a success, which is
   the swallowed-mutation bug the note at the top of this file warns about. */
export function SubAgentsPanel() {
  const { d, e, loading, reload } = useApi('/api/subagents');  // user-guarded
  const spawns = arr(d, 'spawns');
  const stats = (d && d.stats) || {};
  const [task, setTask] = useState('');
  const [agent, setAgent] = useState('');
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState(null);
  const atCap = stats.cap != null && (stats.active ?? 0) >= stats.cap;
  const statusColor = (s) => (s === 'done' ? 'var(--green)' : s === 'failed' ? 'var(--red)' : 'var(--amber)');
  const spawn = () => {
    const t = task.trim();
    if (!t || pending) return;
    setPending(true);
    setNote(null);
    act('/api/subagents/spawn', { task: t, agent: agent.trim() },
      (r) => {
        setPending(false);
        setNote(r && r.ok === false
          ? `refused · ${r.reason || 'spawn_failed'}`
          : `spawned ${(r && r.id) || ''} · ${(r && r.status) || 'done'}`);
        setTask('');
        reload();
      },
      (err) => { setPending(false); setNote(`refused · ${err?.message || 'spawn failed'}`); reload(); });
  };
  return (
    <Card title="SUB-AGENTS" live={asLive(d)} sub={d ? `${stats.total ?? spawns.length} spawn(s)` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>capacity</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={atCap ? 'var(--amber)' : 'var(--green)'}>{stats.active ?? 0}/{stats.cap ?? '—'} active</Tag>
              {atCap && <Tag c="var(--amber)">at cap</Tag>}
              <Tag>depth ≤ {stats.max_depth ?? '—'}</Tag>
              <Tag>{stats.total ?? spawns.length} total</Tag>
            </span>
          </Row>
          {spawns.slice(0, 10).map((s, i) => (
            <Row key={s.id || i}>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{s.id}</span>
              <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{String(s.task || '').slice(0, 40)}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag>{s.agent || 'sub'}</Tag>
                <Tag c={statusColor(s.status)}>{s.status || '—'}</Tag>
              </span>
            </Row>
          ))}
          <Row>
            <input
              style={{ ...inpS, flex: 1 }} placeholder="task for the sub-agent" value={task}
              disabled={pending} onChange={(ev) => setTask(ev.target.value)}
            />
            <input
              style={{ ...inpS, width: 120 }} placeholder="agent (optional)" value={agent}
              disabled={pending} onChange={(ev) => setAgent(ev.target.value)}
            />
            <button
              className="tool-btn" title="spawn a sub-agent (long-running)"
              disabled={pending || !task.trim()} onClick={spawn}
            >spawn</button>
          </Row>
          {pending && <div role="status" style={{ ...mono, marginTop: 6, color: 'var(--amber)' }}>spawning… the connection is held for the whole turn</div>}
          {note && <div role="alert" style={{ ...mono, marginTop: 6, color: note.startsWith('refused') ? 'var(--red)' : 'var(--green)' }}>{note}</div>}
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
            Spawning is long-running, not fire-and-forget: the POST runs the sub-agent inline and
            the request stays open until the sub-agent&apos;s turn finishes. Cap, recursion-depth and
            budget refusals all answer 429 — the capacity row above says which limit is tight.
          </div>
        </>
      )}
    </Card>
  );
}

/* H34.7 — SystemMapPanel: the Live System Map in the Console (Observe). Renders
   the checked-in topology (served inside /api/system-map) as an inline SVG and
   lights each subsystem with its live reduced status — ok / degraded / attention /
   off / unknown, where unknown never renders green. Edges carry real counters and
   stay static when a counter is absent; nothing here synthesizes motion. Read-only;
   the wall-screen version is the standalone /map page this panel links out to. */
const MAP_STATUS_COLOR = {
  ok: 'var(--green)', degraded: 'var(--amber)', attention: 'var(--red)',
  off: 'var(--ink-3)', unknown: 'var(--ink-3)',
};
function mapCenter(n) { return [n.pos[0] + n.size[0] / 2, n.pos[1] + n.size[1] / 2]; }
function mapEdgePath(a, b) {
  const [ax, ay] = mapCenter(a); const [bx, by] = mapCenter(b);
  if (Math.abs(ay - by) < 6) return `M ${a.pos[0] + a.size[0]} ${ay} L ${b.pos[0]} ${by}`;
  if (Math.abs(ax - bx) < 6) {
    const down = ay < by;
    return `M ${ax} ${down ? a.pos[1] + a.size[1] : a.pos[1]} L ${bx} ${down ? b.pos[1] : b.pos[1] + b.size[1]}`;
  }
  const yExit = ay < by ? a.pos[1] + a.size[1] : a.pos[1];
  const xEnter = bx > ax ? b.pos[0] : b.pos[0] + b.size[0];
  return `M ${ax} ${yExit} L ${ax} ${by} L ${xEnter} ${by}`;
}
export function SystemMapPanel() {
  const { d, e, loading, reload } = useApi('/api/system-map');  // user
  const topo = (d && d.topology) || null;
  const nodes = (d && d.nodes) || {};
  const edges = (d && d.edges) || {};
  const topoNodes = topo ? topo.nodes : [];
  const byId = {};
  topoNodes.forEach((n) => { byId[n.id] = n; });
  const attention = topoNodes.filter((n) => (nodes[n.id] || {}).status === 'attention').length;
  const okCount = topoNodes.filter((n) => (nodes[n.id] || {}).status === 'ok').length;
  return (
    <Card
      title="SYSTEM MAP"
      live={asLive(d, d && d.initialized)}
      sub={d ? `${okCount}/${topoNodes.length} ok${attention ? ` · ${attention} attention` : ''}` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={topo ? 1 : 0} />
      {topo && (
        <>
          <svg viewBox={topo.view_box.join(' ')} style={{ width: '100%', height: 'auto', display: 'block' }}>
            {topo.edges.map((ed) => {
              const act = edges[ed.id];
              const hot = act && act.count > 0;
              const [ax, ay] = mapCenter(byId[ed.from]); const [bx, by] = mapCenter(byId[ed.to]);
              return (
                <g key={ed.id}>
                  <path d={mapEdgePath(byId[ed.from], byId[ed.to])} fill="none"
                    stroke={hot ? 'var(--accent-light)' : 'var(--line)'} strokeWidth={1.6} />
                  {act && (
                    <text x={(ax + bx) / 2} y={(ay === by ? ay : (ay + by) / 2) - 7}
                      textAnchor="middle" fill={hot ? 'var(--accent-light)' : 'var(--ink-3)'}
                      style={{ font: '11px var(--font-mono)' }}>{act.count}</text>
                  )}
                </g>
              );
            })}
            {topoNodes.map((n) => {
              const info = nodes[n.id] || { status: 'unknown', stats: {} };
              const stroke = MAP_STATUS_COLOR[info.status] || 'var(--ink-3)';
              return (
                <g key={n.id} style={{ cursor: n.href ? 'pointer' : 'default' }}
                  opacity={info.status === 'off' ? 0.55 : 1}
                  onClick={() => { if (n.href) window.open(n.href, '_blank', 'noopener'); }}>
                  <title>{`${n.label} — ${info.status}\n${Object.entries(info.stats || {}).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join('\n')}`}</title>
                  <rect x={n.pos[0]} y={n.pos[1]} width={n.size[0]} height={n.size[1]} rx={6}
                    fill="var(--panel, rgba(255,255,255,0.03))" stroke={stroke} strokeWidth={1.6}
                    strokeDasharray={info.status === 'unknown' ? '4 3' : undefined} />
                  <text x={n.pos[0] + n.size[0] / 2} y={n.pos[1] + 27} textAnchor="middle"
                    fill="var(--ink-1, var(--ink-2))" style={{ font: '600 13px var(--font-mono)' }}>{n.label}</text>
                  <text x={n.pos[0] + n.size[0] / 2} y={n.pos[1] + 45} textAnchor="middle"
                    fill={stroke} style={{ font: '11px var(--font-mono)' }}>{info.status}</text>
                </g>
              );
            })}
          </svg>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
            <span style={{ ...mono, color: 'var(--ink-3)', fontSize: 10 }}>topology {topo.version} · unknown never renders green</span>
            <a className="tool-btn" href="/map" target="_blank" rel="noopener noreferrer">open wall map →</a>
          </div>
        </>
      )}
    </Card>
  );
}

/* HUD-v3 C8 (arena + quality-threshold; evals/review already shipped). Two Observe
   panels: the model arena leaderboard (read-only) + the answer-quality gate (read +
   admin set-threshold). Honesty: real ELO/scores; empty-state when no matches yet. */
export function ArenaPanel() {
  const { d, e, loading, reload } = useApi('/api/arena/leaderboard');  // open
  const rows = arr(d, 'leaderboard');
  return (
    <Card title="MODEL ARENA" live={asLive(d)} sub={d ? `${rows.length} models` : null} onReload={reload}>
      <State e={e} loading={loading} n={rows.length} />
      {rows.slice(0, 10).map((m, i) => (
        <Row key={m.model ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{i + 1}. {m.model}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--accent-light)">{Math.round(m.elo)} elo</Tag>
            <Tag c={(m.win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--ink-3)'}>{Math.round((m.win_rate || 0) * 100)}%</Tag>
            <Tag>{m.games ?? ((m.wins || 0) + (m.losses || 0))} games</Tag>
          </span>
        </Row>
      ))}
      {rows.length === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>no matches yet · run an arena comparison to rank models</div>}
    </Card>
  );
}
export function QualityPanel() {
  const { d, e, loading, reload } = useApi('/api/quality');  // open
  const st = (d && d.stats) || {};
  const [thr, setThr] = useState('');
  const apply = () => { const v = parseFloat(thr); if (!isNaN(v)) actA('/api/quality/threshold', { threshold: v }, () => { setThr(''); reload(); }); };
  return (
    <Card title="ANSWER QUALITY" live={asLive(d)} sub={typeof st.avg_score === 'number' ? `avg ${st.avg_score.toFixed(2)}` : null} onReload={reload}>
      <State e={e} loading={loading} n={typeof st.n === 'number' ? st.n : (d ? 1 : 0)} />
      {d && (
        <Row>
          <span style={mono}>alert threshold</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={st.alerting ? 'var(--red)' : 'var(--green)'}>{st.alerting ? 'ALERTING' : 'ok'}</Tag>
            <Tag>{typeof st.threshold === 'number' ? st.threshold.toFixed(2) : '—'}</Tag>
          </span>
        </Row>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={thr} onChange={(ev) => setThr(ev.target.value)} placeholder="0.0–1.0" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={apply}>set threshold</button>
      </div>
    </Card>
  );
}

/* ── Interop ───────────────────────────────────────────── */
/* HUD-v3 C10 — Mesh peers. The A2A peer registry (allowlist + one-time shared secret)
   is admin-guarded and had no control surface (only the inbox did). Surfaces the
   allowlisted peers (secret masked to a hint), a remove control, and an add-peer flow
   that shows the shared secret ONCE (mirrors the backend's return-once contract). */
export function MeshPeersPanel() {
  const { d, e, loading, reload } = useApi('/api/a2a/peers', true, true);  // admin-guarded
  const peers = arr(d, 'peers');
  const [pid, setPid] = useState('');
  const [name, setName] = useState('');
  const [secret, setSecret] = useState(null);
  const add = () => {
    if (!pid.trim()) return;
    actA('/api/a2a/peers', { peer_id: pid.trim(), name: name.trim() }, (r) => {
      setSecret(r && r.secret ? r.secret : null); setPid(''); setName(''); reload();
    });
  };
  return (
    <Card title="MESH PEERS" live={asLive(d)} sub={d ? `${peers.length} allowlisted` : null} onReload={reload}>
      <State e={e} loading={loading} n={peers.length} />
      {peers.slice(0, 12).map((p, i) => (
        <Row key={p.peer_id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{p.name || p.peer_id}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {p.secret_hint && <Tag>{p.secret_hint}</Tag>}
            <button className="tool-btn" title="remove" onClick={() => apiDelete('/api/a2a/peers/' + encodeURIComponent(p.peer_id), { admin: true }).then(reload).catch(() => {})}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={pid} onChange={(ev) => setPid(ev.target.value)} placeholder="peer_id" style={{ ...inpS, flex: 1 }} />
        <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="name" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={add}>add</button>
      </div>
      {secret && <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>shared secret (shown once): <span style={mono}>{secret}</span></div>}
    </Card>
  );
}
/* HUD-v3 (Oracle bridge) — truth-sync reconciler. The Oracle keeps the repo's "truth"
   docs synced from GitHub and flags local/remote conflicts; it had no UI. This shows the
   watcher status + conflict list, with sync-now and clear-resolved. GET status/conflicts
   open · sync + resolve admin. */
export function OraclePanel() {
  const { d, e, loading, reload } = useApi('/api/oracle/status');
  const conflicts = arr(d, 'conflicts');
  const syncNow = () => actA('/api/oracle/sync', {}, reload);
  const clearResolved = () => actA('/api/oracle/conflicts/resolve', {}, reload);
  return (
    <Card title="ORACLE SYNC" live={asLive(d)} sub={d ? (d.watcher_running ? 'watching' : 'idle') + (d.last_checked ? ' · ' + d.last_checked : '') : null} onReload={reload}>
      <State e={e} loading={loading} n={conflicts.length} />
      {conflicts.slice(0, 10).map((c, i) => (
        <Row key={c.file_path ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.file_path}</span>
          <span style={{ marginLeft: 'auto' }}><Tag c={c.resolved ? 'var(--green)' : 'var(--amber)'}>{c.resolved ? 'resolved' : 'conflict'}</Tag></span>
        </Row>
      ))}
      {conflicts.length === 0 && <div style={{ fontSize: 10, color: 'var(--green)', marginTop: 6 }}>in sync · no conflicts</div>}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button className="tool-btn" onClick={syncNow}>sync now</button>
        {conflicts.length > 0 && <button className="tool-btn" onClick={clearResolved}>clear resolved</button>}
      </div>
    </Card>
  );
}

/* HUD-v3 §4.4 — Mic Satellites. The H12.8 satellite hub ("pair a phone/device as a mic
   satellite", shared-GPU inference) had no UI — pairing was a stub. This is the real
   flow: list paired satellites, pair a new one, unpair. All user-guarded. */
export function SatellitesPanel() {
  const { d, e, loading, reload } = useApi('/api/satellites');  // user-guard
  const sats = arr(d, 'satellites');
  const [sid, setSid] = useState('');
  const pair = () => { if (!sid.trim()) return; act('/api/satellites/register', { satellite_id: sid.trim(), meta: {} }, () => { setSid(''); reload(); }); };
  const unpair = (id) => apiDelete('/api/satellites/' + encodeURIComponent(id)).then(reload).catch(() => {});
  return (
    <Card title="MIC SATELLITES" live={asLive(d)} sub={d ? `${sats.length} paired` : null} onReload={reload}>
      <State e={e} loading={loading} n={sats.length} />
      {sats.slice(0, 10).map((s, i) => (
        <Row key={s.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{s.id}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {s.kind && <Tag>{s.kind}</Tag>}
            <button className="tool-btn" title="unpair" onClick={() => unpair(s.id)}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={sid} onChange={(ev) => setSid(ev.target.value)} placeholder="device id (pair a phone as a mic)" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={pair}>pair</button>
      </div>
      {sats.length === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>no satellites · pair a phone/device to use it as a mic</div>}
    </Card>
  );
}
export function A2AInboxPanel() {
  const { d, e, loading, reload } = useApi('/api/a2a/inbox');
  const items = arr(d, 'inbox', 'tasks');
  return <Card title="A2A APPROVAL INBOX" live={asLive(d)} sub={items.length} onReload={reload}>
    <State e={e} loading={loading} n={items.length} />
    {items.slice(0, 10).map((it, i) => <Row key={i}><span style={mono}>{it.peer || it.from || '?'}</span><span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(it.task || it.summary || '').slice(0, 40)}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
        {/* PNL-106: the API body is {approve} — {approved} 422'd invisibly */}
        <button className="tool-btn" onClick={() => actA(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approve: true }, reload)}>✓</button>
        <button className="tool-btn" onClick={() => actA(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approve: false }, reload)}>✕</button>
      </span></Row>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>verified peer tasks land here; never auto-execute (H16.2)</div>
  </Card>;
}
/* DRA-37 — package rollback lives HERE, not in SkillHistoryPanel. Rollback reads the
   `marketplace_skill_versions` archive, which every publish populates in a default install,
   whereas the history ledger is gated on JARVIS_SKILL_HISTORY and renders zero rows when it
   is unset — a control hung off that panel would disappear exactly when rollback is still
   perfectly usable. The refusal path is the COMMON case here ("no prior version archived"
   answers 422), which is why the caller passes an `onErr`: apiPost throws on 4xx, so without
   it the button would silently read as a success. */
export function MarketplacePanel() {
  // GET /api/skills/marketplace is admin_guard'ed like the mutations below it: without
  // the admin flag the list 401s on a token-configured install and the rollback control
  // has nothing to hang off.
  const { d, e, loading, reload } = useApi('/api/skills/marketplace', true, true);
  const skills = arr(d, 'skills');
  const [note, setNote] = useState(null);
  return <Card title="SKILLS MARKETPLACE" live={asLive(d)} sub={skills.length} onReload={reload}>
    <State e={e} loading={loading} n={skills.length} />
    {skills.slice(0, 10).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{s.name}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
        <Tag>{s.version || '—'}</Tag>
        <Tag c={s.signed ? 'var(--green)' : 'var(--amber)'}>{s.signed ? 'signed' : 'unsigned'}</Tag>
        <Tag c={s.review_status === 'approved' ? 'var(--green)' : s.review_status === 'rejected' ? 'var(--red)' : 'var(--amber)'}>{s.review_status || 'pending'}</Tag>
        {s.review_status !== 'approved' && <button className="tool-btn" title="approve skill" onClick={() => actA('/api/skills/marketplace/review', { name: s.name, status: 'approved' }, reload)}>✓</button>}
        {s.review_status !== 'rejected' && <button className="tool-btn" title="reject skill" onClick={() => actA('/api/skills/marketplace/review', { name: s.name, status: 'rejected' }, reload)}>✕</button>}
        <button className="tool-btn" title="roll back to the previous package" onClick={() => actA(`/api/skills/marketplace/${encodeURIComponent(s.name)}/rollback`, {}, (r) => { setNote(`${s.name} · restored ${(r && r.restored_version) || '?'} ← ${(r && r.previous_version) || '?'}`); reload(); }, (err) => setNote(`refused · ${err?.message || 'rollback failed'}`))}>⟲</button>
      </span></Row>)}
    {note && <div role="alert" style={{ ...mono, marginTop: 6, color: note.startsWith('refused') ? 'var(--red)' : 'var(--green)' }}>{note}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>signed + moderated — ✓/✕ sets review status (anti-ClawHub, H12.12).
      ⟲ reverts the registry package to its archived prior version and is itself reversible; the
      installed skill is unchanged until it is re-installed through the moderation gate.</div>
  </Card>;
}

/* ── Observe / Eval ────────────────────────────────────── */
function EvalPanel() {
  const { d, e, loading, reload } = useApi('/api/eval/datasets');
  const ds = arr(d, 'datasets');
  const [open, setOpen] = useState(null);   // dataset name whose runs are expanded
  const [runs, setRuns] = useState([]);
  const [cmp, setCmp] = useState(null);
  const showRuns = (name) => {
    if (open === name) { setOpen(null); setCmp(null); return; }
    setOpen(name); setCmp(null);
    apiGet('/api/eval/datasets/' + encodeURIComponent(name) + '/runs?limit=6').then((r) => setRuns(arr(r, 'runs'))).catch(() => setRuns([]));
  };
  const compare = () => {
    if (!open || runs.length < 2) return;
    const idOf = (r) => r.run_id || r.id || r.ts;
    apiGet(`/api/eval/datasets/${encodeURIComponent(open)}/compare?a=${encodeURIComponent(idOf(runs[1]))}&b=${encodeURIComponent(idOf(runs[0]))}`).then(setCmp).catch(() => setCmp(null));
  };
  return <Card title="EVAL DATASETS" live={asLive(d)} sub={ds.length} onReload={reload}>
    <State e={e} loading={loading} n={ds.length} />
    {ds.slice(0, 8).map((x, i) => <Row key={i}>
      <span style={{ ...mono, cursor: 'pointer', color: open === x.name ? 'var(--accent)' : 'var(--ink)' }} onClick={() => showRuns(x.name)} title="show recent runs">{x.name}</span>
      <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>v{x.latest_version ?? x.version ?? '?'} · {x.cases ?? x.count ?? '?'}</span>
      <Btn onClick={() => act('/api/eval/datasets/run', { name: x.name }, reload)}>run</Btn></Row>)}
    {open && <div style={{ marginTop: 6 }}>
      <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)' }}>{open.toUpperCase()} · RECENT RUNS</div>
      {runs.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>no recorded runs</div>}
      {runs.map((r, i) => <Row key={i}><span style={mono}>{(r.run_id || r.id || r.ts || '').toString().slice(0, 19)}</span>
        <span style={{ marginLeft: 'auto', ...mono, fontSize: 10, color: 'var(--accent-light)' }}>μ {r.mean_score ?? r.score ?? '—'}</span></Row>)}
      {runs.length >= 2 && <button className="tool-btn" style={{ marginTop: 6 }} onClick={compare}>compare last two</button>}
      {cmp && <div style={{ ...mono, fontSize: 10.5, marginTop: 6 }}>
        {/* WFL-078/PNB-018: the API emits `regressed`/`improved` (lists of case
            names) — the old `regressions`/`improvements` keys made a real
            regression render as "0 regression(s)". */}
        <span style={{ color: (cmp.score_delta ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>Δ score {cmp.score_delta ?? '—'}</span>
        <span style={{ color: 'var(--ink-3)' }}> · {(cmp.regressed || []).length} regression(s) · {(cmp.improved || []).length} improvement(s)</span>
        {(cmp.regressed || []).slice(0, 4).map((g, i) => <div key={i} style={{ color: 'var(--red)' }}>− {(typeof g === 'string' ? g : g.case || g.prompt || g.id || '').toString().slice(0, 48)}</div>)}
      </div>}
    </div>}
  </Card>;
}
export function ReviewPanel() {
  const { d, e, loading, reload } = useApi('/api/review/queue?status=pending');
  const q = arr(d, 'queue', 'items');
  /* DRA-52 — `POST /api/review/{item_id}/dataset` (H9.3b) shipped with no caller anywhere, so
     a reviewed turn could be voted on but never promoted into an eval dataset. */
  const [note, setNote] = useState(null);   // {id, ok, text} — last promotion outcome
  /* The refusal has to be shown, not swallowed. This route really does refuse: WFL-088 rejects
     an item with no prompt rather than minting a case that replays empty and scores a fabricated
     1.0. `apiPost` throws on a 4xx (failMutation is `: never`), so without the onErr arg `act`'s
     own `.catch(() => {})` eats it and the button reads as success — precisely the swallowed
     mutation this file warns about at the `act`/`actA` definitions. */
  const promote = (id) => act(
    `/api/review/${id}/dataset`, {},
    (r) => { setNote({ id, ok: true, text: `→ ${r?.dataset || 'dataset'} v${r?.version ?? '?'}` }); reload(); },
    (err) => setNote({ id, ok: false, text: `refused · ${err?.status || 'error'}` }),
  );
  return <Card title="REVIEW QUEUE" live={asLive(d)} sub={q.length} onReload={reload}>
    <State e={e} loading={loading} n={q.length} />
    {q.slice(0, 10).map((it, i) => {
      const id = it.id || it.trace_id;
      return <Row key={i}><span style={{ fontSize: 11 }}>{(it.text_preview || it.preview || it.text || '').slice(0, 38)}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          {note && note.id === id && <span style={{ fontSize: 10, color: note.ok ? 'var(--green)' : 'var(--red)' }}>{note.text}</span>}
          {it.in_dataset
            ? <Tag c="var(--green)">in dataset</Tag>
            : <button className="tool-btn" title="promote to eval dataset" onClick={() => promote(id)}>⇪</button>}
          <button className="tool-btn" onClick={() => act(`/api/review/${id}/vote`, { verdict: 'up' }, reload)}>👍</button>
          <button className="tool-btn" onClick={() => act(`/api/review/${id}/vote`, { verdict: 'down' }, reload)}>👎</button>
        </span></Row>;
    })}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
      ⇪ promotes a reviewed turn into the `review_flagged` eval dataset (H9.3b). An item with no
      prompt is refused rather than replayed empty (WFL-088); a refusal shows on its own row.
    </div>
  </Card>;
}
function APMPanel() {
  const { d, e, loading, reload } = useApi('/api/admin/apm');
  return <Card title="APM" live={asLive(d)} onReload={reload}>
    <State e={e} loading={loading} n={d ? 1 : 0} />
    {d && <div style={{ ...mono, fontSize: 11 }}>
      <Row><span>runs</span><span style={{ marginLeft: 'auto' }}>{d.runs ?? d.total_runs ?? '—'}</span></Row>
      <Row><span>tokens</span><span style={{ marginLeft: 'auto' }}>{d.tokens ?? d.total_tokens ?? '—'}</span></Row>
      <Row><span>cost $</span><span style={{ marginLeft: 'auto' }}>{d.cost ?? d.total_cost ?? '—'}</span></Row>
    </div>}
  </Card>;
}

/* ── Autonomy ──────────────────────────────────────────── */
function SchedulePanel() {
  const [text, setText] = useState('every weekday at 7am'); const [out, setOut] = useState(null);
  return <Card title="NL SCHEDULING" live={'live'}>
    <input value={text} onChange={(e) => setText(e.target.value)} style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono }} />
    <button className="tool-btn" style={{ marginTop: 6 }} onClick={() => act('/api/schedule/parse', { text }, (r) => setOut(r))}>parse → cron</button>
    {out && <div style={{ ...mono, fontSize: 11, color: 'var(--accent-light)', marginTop: 6 }}>{out.cron || out.error || JSON.stringify(out)}</div>}
  </Card>;
}

function HeartbeatPanel() {
  const { d, e, loading, reload } = useApi('/heartbeat/status');
  const hbs = arr(d, 'heartbeats', 'agents') || Object.entries(d || {}).map(([k, v]) => ({ agent_id: k, ...(typeof v === 'object' ? v : { status: v }) }));
  const list = Array.isArray(hbs) ? hbs : [];
  const hb = (id, op) => act('/heartbeat/' + encodeURIComponent(id) + '/' + op, {}, reload);
  return <Card title="HEARTBEATS" live={asLive(d)} sub={list.length} onReload={reload}>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 12).map((h, i) => { const id = h.agent_id || h.agent || h.id; const on = h.running ?? h.active ?? (h.status === 'running' || h.status === 'started'); return <Row key={i}>
      <span style={mono}>{id}</span>
      <Tag c={on ? 'var(--green)' : 'var(--ink-3)'}>{on ? 'running' : 'stopped'}</Tag>
      <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{h.schedule || h.interval || ''}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
        <button className="tool-btn" title="run once now" onClick={() => hb(id, 'run')}>▶ now</button>
        {on ? <button className="tool-btn" title="stop schedule" onClick={() => hb(id, 'stop')}>⏹</button>
          : <button className="tool-btn" title="start schedule" onClick={() => hb(id, 'start')}>⏵</button>}
      </span></Row>; })}
  </Card>;
}
function TranscriptPanel() {
  const [text, setText] = useState('');
  const [src, setSrc] = useState('');
  const [out, setOut] = useState(null);
  const ingest = () => { if (!text.trim()) return; setOut('extracting…'); act('/api/transcripts/ingest', { transcript: text, source: src }, (r) => { setOut(r); setText(''); }); };
  return <Card title="TRANSCRIPT → TASKS" live={'live'}>
    <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="paste a meeting transcript — action items land in the approval queue, nothing executes" style={taS} />
    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <input value={src} onChange={(ev) => setSrc(ev.target.value)} placeholder="source (optional)" style={{ ...inpS, flex: 1 }} />
      <button className="tool-btn" onClick={ingest}>ingest</button>
    </div>
    {out != null && (typeof out === 'string' ? <div style={{ ...mono, fontSize: 11, color: 'var(--ink-3)', marginTop: 6 }}>{out}</div>
      : <div style={{ ...mono, fontSize: 11, color: 'var(--accent-light)', marginTop: 6 }}>
        {(out.items || out.tasks || []).length} action item(s) {out.enqueued != null ? `· ${out.enqueued} queued for approval` : '· preview only (queue offline)'}
        {(out.items || out.tasks || []).slice(0, 5).map((it, i) => <div key={i} style={{ color: 'var(--ink-2)' }}>· {(it.title || it.text || it).toString().slice(0, 60)}</div>)}
      </div>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>governed — every item is an ask-tier task you approve (H12.25)</div>
  </Card>;
}
function EscalationPanel() {
  const { d, e, loading, reload } = useApi('/api/autonomy/escalation/targets');
  const targets = arr(d, 'targets');
  const [msg, setMsg] = useState('');
  const [out, setOut] = useState(null);
  const send = () => { if (!msg.trim()) return; actA('/api/autonomy/escalate', { message: msg.trim() }, (r) => { setOut(r); setMsg(''); }); };
  return <Card title="ESCALATION" live={asLive(d)} sub={targets.length + ' ch'} onReload={reload}>
    <State e={e} loading={loading} n={targets.length} />
    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>{targets.map((tg, i) => <Tag key={i} c="var(--accent-light)">{tg.channel || tg}</Tag>)}</div>
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={msg} onChange={(ev) => setMsg(ev.target.value)} placeholder="escalation message" onKeyDown={(ev) => { if (ev.key === 'Enter') send(); }} style={{ ...inpS, flex: 1 }} />
      <button className="tool-btn" onClick={send}>send</button>
    </div>
    {out && <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6 }}>{JSON.stringify(out).slice(0, 140)}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>governed channels only (H12.11) · admin</div>
  </Card>;
}
function TemplatesPanel() {
  const { d, e, loading, reload } = useApi('/api/agent-templates');
  const tpls = arr(d, 'templates');
  const [name, setName] = useState('');
  const [out, setOut] = useState(null);
  const inst = (tpl) => act('/api/agent-templates/instantiate', { template: tpl.id || tpl.name || tpl, name: name || undefined }, (r) => setOut(r.config || r));
  return <Card title="AGENT TEMPLATES" live={asLive(d)} sub={tpls.length} onReload={reload}>
    <State e={e} loading={loading} n={tpls.length} />
    {tpls.slice(0, 8).map((tp, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{tp.id || tp.name || tp}</span><span style={{ fontSize: 10, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(tp.description || tp.role || '').slice(0, 36)}</span><Btn onClick={() => inst(tp)}>instantiate</Btn></Row>)}
    <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="new agent name (optional)" style={{ ...inpS, width: '100%', marginTop: 8 }} />
    {out && <Json v={out} />}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>renders an agents.yaml config + SOUL skeleton — save via the normal agent flow (H10.29)</div>
  </Card>;
}

/* ── Build ─────────────────────────────────────────────── */
/* HUD-v3 C7 (workflow runtime management). WorkflowBuilderPanel covers create/edit;
   this is the missing management surface for the 0.34 runtime: list registered
   pipelines (built-in + user-defined), run one, delete a user-defined one.
   GET open · run user-guard · delete admin. */
export function WorkflowsPanel() {
  const { d, e, loading, reload } = useApi('/api/workflows');
  const rows = arr(d, 'workflows');
  const [out, setOut] = useState(null);
  const run = (id) => { setOut('running ' + id + '…'); act('/api/workflows/run', { pipeline_id: id, input: '' }, (r) => setOut(r && r.ok !== false ? 'ran ' + id + ' · ok' : 'run failed')); };
  const del = (id) => apiDelete('/api/workflows/' + encodeURIComponent(id), { admin: true }).then(reload).catch(() => {});
  return (
    <Card title="WORKFLOWS" live={asLive(d)} sub={d ? `${rows.length} pipelines` : null} onReload={reload}>
      <State e={e} loading={loading} n={rows.length} />
      {rows.slice(0, 12).map((w, i) => (
        <Row key={w.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{w.name || w.id}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag>{(w.steps || []).length} steps</Tag>
            <button className="tool-btn" onClick={() => run(w.id)}>run</button>
            <button className="tool-btn" title="delete" onClick={() => del(w.id)}>✕</button>
          </span>
        </Row>
      ))}
      {out && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{out}</div>}
    </Card>
  );
}
/* DRA-28 — this replaces the read-only `StepGenPanel`, whose caption told the
   owner to "paste into the workflow builder": a builder that only existed in the
   legacy v1 surface (agents/web/static/workflows.js), never in the default v2
   HUD. NOTE for the next reader: the route-parity gate is blind to this gap —
   `/api/workflows` and `/api/workflows/{id}` already had GET/run/delete callers,
   and the legacy v1 file counts as a client, so nothing flagged the missing
   create/edit path. Generate → add to draft → save closes it. */
const stepFromCfg = (cfg, steps) => {
  const n = steps.length;
  const step: any = {
    id: 's' + (n + 1),
    // `WorkflowStep.from_dict` does d["agent_id"] — a missing key is a 422, so it is always present.
    agent_id: cfg.agent || '',
    prompt_template: cfg.prompt || '{_input}',
    // chain onto the previous step so the DAG is valid on the very first save
    depends_on: n ? [steps[n - 1].id] : [],
  };
  if (cfg.kind && cfg.kind !== 'agent') step.kind = cfg.kind;   // to_dict omits kind==='agent'
  if (cfg.kind === 'transform') step.transform = { op: cfg.transform || 'summarize' };
  return step;
};
export function WorkflowBuilderPanel() {
  const { d, e, loading, reload } = useApi('/api/workflows');
  const rows = arr(d, 'workflows');
  const [desc, setDesc] = useState('');
  const [gen, setGen] = useState(null);
  const [wid, setWid] = useState('');
  const [name, setName] = useState('');
  const [desc2, setDesc2] = useState('');
  const [stepsText, setStepsText] = useState('[]');
  const [existing, setExisting] = useState(false);
  const [note, setNote] = useState('');

  const parseSteps = () => {
    let parsed;
    try { parsed = JSON.parse(stepsText); } catch { return null; }
    return Array.isArray(parsed) ? parsed : null;
  };
  const generate = () => {
    if (!desc.trim()) return;
    setNote('generating…');
    act('/api/workflows/step/generate', { description: desc },
      (r) => { setGen((r && r.step) || r); setNote(''); },
      (err) => setNote(`refused · ${err?.message || 'generate_failed'}`));
  };
  const addStep = () => {
    if (!gen) return;
    const steps = parseSteps();
    if (steps === null) { setNote('steps must be a JSON array'); return; }
    setStepsText(JSON.stringify(steps.concat([stepFromCfg(gen, steps)]), null, 2));
    setNote('');
  };
  const pick = (id) => {
    const w = rows.find((row) => String(row.id) === id);
    if (!w) { setWid(''); setName(''); setDesc2(''); setStepsText('[]'); setExisting(false); setNote(''); return; }
    setWid(w.id); setName(w.name || ''); setDesc2(w.description || '');
    setStepsText(JSON.stringify(w.steps || [], null, 2)); setExisting(true); setNote('');
  };
  const save = () => {
    const steps = parseSteps();
    if (steps === null) { setNote('steps must be a JSON array'); return; }
    const id = wid.trim();
    if (!id) { setNote('an id is required'); return; }
    const body = { id, name, description: desc2, steps };
    setNote('saving…');
    // apiPost/apiPut THROW on 4xx — a silent admin write is exactly the bug this
    // catch exists to prevent (422 invalid workflow definition / 401 no token).
    const sent = existing
      ? apiPut('/api/workflows/' + encodeURIComponent(id), body, { admin: true })
      : apiPost('/api/workflows', body, { admin: true });
    sent
      .then((r: any) => { setNote(`saved · ${(r && r.id) || id}`); setExisting(true); reload(); })
      .catch((err) => setNote(`refused · ${err?.message || 'save_failed'}`));
  };

  return <Card title="WORKFLOW BUILDER" live={asLive(d)} sub={d ? `${rows.length} pipelines` : null} onReload={reload}>
    <State e={e} loading={loading} n={undefined} />
    <textarea
      aria-label="workflow step description"
      value={desc}
      onChange={(ev) => setDesc(ev.target.value)}
      placeholder="describe the workflow step — e.g. 'have vision summarize the week's research and hand it to veronica'"
      style={{ ...taS, minHeight: 48 }}
    />
    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
      <button className="tool-btn" type="button" onClick={generate}>generate step</button>
      <button className="tool-btn" type="button" disabled={!gen} onClick={addStep} aria-label="add step to draft">add step to draft</button>
    </div>
    {gen != null && <Json v={gen} max={110} />}
    <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>DRAFT</div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
      <select aria-label="workflow to edit" value={existing ? wid : ''} onChange={(ev) => pick(ev.target.value)} style={inpS}>
        <option value="">new workflow…</option>
        {rows.map((w, i) => <option key={w.id ?? i} value={w.id}>{w.name || w.id}</option>)}
      </select>
      <input aria-label="workflow draft id" value={wid} onChange={(ev) => setWid(ev.target.value)} placeholder="id" style={inpS} />
      <input aria-label="workflow draft name" value={name} onChange={(ev) => setName(ev.target.value)} placeholder="name" style={inpS} />
      <input aria-label="workflow draft description" value={desc2} onChange={(ev) => setDesc2(ev.target.value)} placeholder="description" style={inpS} />
    </div>
    <textarea
      aria-label="workflow draft steps"
      value={stepsText}
      onChange={(ev) => setStepsText(ev.target.value)}
      spellCheck={false}
      style={{ ...taS, marginTop: 6 }}
    />
    <button className="tool-btn" style={{ marginTop: 6 }} type="button" onClick={save} aria-label="save workflow">
      {existing ? 'save workflow (update)' : 'save workflow'}
    </button>
    {note && <div role="status" style={{ ...mono, fontSize: 10, color: note.startsWith('refused') || note.startsWith('steps must') ? 'var(--red)' : 'var(--accent-light)', marginTop: 6 }}>{note}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>generate → add to draft → save (admin) · the steps JSON is the editor of record for router/critic/loop/subflow configs (H10.7)</div>
  </Card>;
}
export function SandboxPanel() {
  const { d: st, reload } = useApi('/sandbox/status');
  const [code, setCode] = useState('');
  const [lang, setLang] = useState('python');
  const [out, setOut] = useState(null);
  const run = () => {
    if (!code.trim()) return;
    setOut('running…');
    apiPost('/sandbox/execute', { code, language: lang })
      .then(setOut)
      .catch((err) => setOut(err?.status === 403 ? 'sandbox disabled — set DEV_MODE=1 on the server' : 'offline · ' + (err?.message || '')));
  };
  const insecure = st?.insecure_host_exec;
  return <Card title="SANDBOX" live={asLive(st)} sub={st ? (st.backend || st.active_backend || (st.docker ? 'docker' : 'subprocess')) : null} onReload={reload}>
    {insecure && <div style={{ ...mono, fontSize: 10, color: 'var(--red)', marginBottom: 6 }}>⚠ host-exec fallback active — code runs WITHOUT isolation</div>}
    <textarea value={code} onChange={(ev) => setCode(ev.target.value)} placeholder={lang === 'python' ? 'print("hello from the sandbox")' : 'echo hello'} style={taS} spellCheck={false} />
    <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
      <select value={lang} onChange={(ev) => setLang(ev.target.value)} style={inpS}><option value="python">python</option><option value="shell">shell</option></select>
      <button className="tool-btn" onClick={run}>execute</button>
    </div>
    {out != null && (typeof out === 'string' ? <div style={{ ...mono, fontSize: 11, color: 'var(--amber)', marginTop: 6 }}>{out}</div>
      : <Json v={(out.stdout || out.output || '') + (out.stderr ? '\n[stderr] ' + out.stderr : '') || out} />)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>Docker-isolated execution, audited (DEV_MODE gate)</div>
  </Card>;
}

/* DRA-06 — 0.65 screen reflex, console half. The capture-to-answer core
   (agents/core/screen_reflex.py) had no product caller at all; POST
   /api/screen/reflex is its first one. Honest scope: the OS-level screen grab
   and the 0.64 global hotkey that fires it are host-gated and NOT shipped here —
   the panel says so instead of faking a hotkey. What the console can really
   produce is bytes: a picked file, a pasted screenshot, or getDisplayMedia where
   the browser offers it. The route refuses a non-loopback VLM with a 503, so the
   screen never leaves the host; this panel shows that posture up front. */
export function ScreenReflexPanel() {
  const vlm = useApi('/api/vlm/status');
  const [img, setImg] = useState('');
  const [imgName, setImgName] = useState('');
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState('answer');
  const [out, setOut] = useState(null);
  const [note, setNote] = useState('');
  // Feature-detect: absent in jsdom and on a non-secure-context LAN load.
  const canCapture = typeof navigator !== 'undefined' && !!(navigator as any).mediaDevices?.getDisplayMedia;
  const configured = !!vlm.d && vlm.d.configured === true;
  const isLocal = configured && vlm.d.local === true;

  const readBlob = (blob, label) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      setImg(result.slice(result.indexOf(',') + 1));   // strip the data: prefix — bytes only
      setImgName(label || 'screenshot');
      setOut(null);
      setNote('');
    };
    reader.readAsDataURL(blob);
  };
  const onPaste = (ev) => {
    const f = ev.clipboardData && ev.clipboardData.files && ev.clipboardData.files[0];
    if (f) readBlob(f, f.name || 'pasted screenshot');
  };
  const capture = async () => {
    let stream = null;
    try {
      stream = await (navigator as any).mediaDevices.getDisplayMedia({ video: true });
      const video = document.createElement('video');
      (video as any).srcObject = stream;
      await video.play();
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      await new Promise((done) => canvas.toBlob((b) => { if (b) readBlob(b, 'screen capture'); done(null); }, 'image/png'));
    } catch (err: any) {
      setNote(`refused · screen capture unavailable (${err?.message || 'denied'})`);
    } finally {
      try { ((stream as any)?.getTracks?.() || []).forEach((t) => t.stop()); } catch { /* already stopped */ }
    }
  };
  const observe = () => {
    if (!img) return;
    setOut(null);
    setNote('observing…');
    // apiPost THROWS on the route's 503s (no VLM / non-loopback VLM) — without
    // this catch the button would read as a silent success.
    apiPost('/api/screen/reflex', { image_base64: img, question, mode })
      .then((r) => { setOut(r); setNote(''); })
      .catch((err) => setNote(`refused · ${err?.message || 'reflex_failed'}`));
  };

  const elements = arr(out, 'elements');
  return <Card
    title="SCREEN REFLEX"
    live={asLive(vlm.d, configured && isLocal)}
    sub={vlm.d ? (configured ? `${vlm.d.backend} · ${vlm.d.default_model || 'model unset'}` : 'no VLM') : null}
    onReload={vlm.reload}
  >
    {vlm.d && !configured && (
      <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginBottom: 6 }}>
        no VLM configured · {vlm.d.reason || 'set JARVIS_VLM_BACKEND'} — the reflex will refuse rather than guess
      </div>
    )}
    {configured && !isLocal && (
      <div role="alert" style={{ ...mono, fontSize: 10, color: 'var(--red)', marginBottom: 6 }}>
        {vlm.d.base_url} is not loopback — the route refuses it (screen bytes must never leave the host)
      </div>
    )}
    <div onPaste={onPaste}>
      <input
        aria-label="screenshot image file"
        type="file"
        accept="image/*"
        onChange={(ev) => { const f = ev.target.files && ev.target.files[0]; if (f) readBlob(f, f.name); }}
        style={{ ...inpS, width: '100%' }}
      />
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
        {img ? `loaded · ${imgName}` : 'pick a screenshot, or paste one here (⌘/Ctrl+V)'}
      </div>
    </div>
    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
      {canCapture && <button className="tool-btn" type="button" onClick={capture} aria-label="capture screen">capture screen</button>}
      <select aria-label="reflex mode" value={mode} onChange={(ev) => setMode(ev.target.value)} style={inpS}>
        <option value="answer">answer</option>
        <option value="ground">ground</option>
      </select>
      <button className="tool-btn" type="button" disabled={!img} onClick={observe} aria-label="observe screen">observe screen</button>
    </div>
    <input
      aria-label="reflex question"
      value={question}
      onChange={(ev) => setQuestion(ev.target.value)}
      placeholder="question (optional) — e.g. what is this error asking me to do?"
      style={{ ...inpS, width: '100%', marginTop: 6 }}
    />
    {out && out.ok && out.generated && (
      <div style={{ ...mono, fontSize: 11, color: 'var(--ink)', marginTop: 8, whiteSpace: 'pre-wrap' }}>{out.answer}</div>
    )}
    {out && out.ok && out.generated && out.mode === 'ground' && elements.map((el, i) => (
      <Row key={`${el.label}:${i}`}>
        <span style={{ ...mono, color: 'var(--accent-light)' }}>{`${el.label} · (${el.x}, ${el.y})`}</span>
        <span style={{ marginLeft: 'auto' }}><Tag>{el.source || 'vlm'}</Tag></span>
      </Row>
    ))}
    {out && out.ok !== true && (
      <div role="alert" style={{ ...mono, fontSize: 11, color: 'var(--ink-3)', marginTop: 8 }}>{out.reason || 'no answer'}</div>
    )}
    {note && <div role="status" style={{ ...mono, fontSize: 10, color: note.startsWith('refused') ? 'var(--red)' : 'var(--amber)', marginTop: 6 }}>{note}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
      screen bytes are held in memory and sent only to the loopback VLM · the global hotkey + OS-level grab stay host-gated
    </div>
  </Card>;
}

/* ── Agents ops ────────────────────────────────────────── */
export function LearningPanel() {
  const { d, e, loading, reload } = useApi('/learning');
  const cands = arr(d, 'promotion_suggestions', 'promotion_candidates', 'candidates');
  const [agent, setAgent] = useState('');
  const [note, setNote] = useState('');
  /* DRA-41 — the H20.4 self-evolution trigger, beside its promotion twin: the
     trajectory→prompt-optimization mechanism had no caller anywhere in the
     product. Both halves land in the same gated decision inbox; approval routes
     the owner to the prompt-VC commit, it does not hot-swap a live prompt. */
  const [evolveNote, setEvolveNote] = useState('');
  const promote = (id) => { if (!id) return; actA('/learning/promote', { bench_agent: id }, (r) => { setNote(r?.promoted ? 'promoted ' + id : 'not promoted'); setAgent(''); reload(); }); };
  return <Card title="LEARNING · BENCH" live={asLive(d)} sub={cands.length} onReload={reload}>
    <State e={e} loading={loading} n={cands.length} />
    {cands.slice(0, 8).map((c, i) => { const id = c.agent || c.bench_agent || c.id || (typeof c === 'string' ? c : ''); return <Row key={i}><span style={mono}>{id}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{c.trigger || c.reason || c.uses || ''}</span><Btn onClick={() => promote(id)}>promote</Btn></Row>; })}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder="bench agent id (e.g. bruce)" style={{ ...inpS, flex: 1 }} />
      <button className="tool-btn" onClick={() => promote(agent.trim().toLowerCase())}>promote</button>
    </div>
    <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
      <button className="tool-btn" onClick={() => actA('/api/learning/propose', {}, reload)}>propose promotions</button>
      <button
        className="tool-btn"
        onClick={() => {
          setEvolveNote('proposing…');
          // apiPost THROWS on the route's 503 (no orchestrator) — without onErr
          // this button would read as a silent success.
          actA('/api/learning/evolve', {},
            (r) => { setEvolveNote(`${r?.count ?? 0} prompt optimization(s) proposed`); reload(); },
            (err) => {
              const status = Number(err?.status);
              setEvolveNote(`refused${Number.isFinite(status) ? ` · HTTP ${status}` : ''}`);
            });
        }}
      >propose prompt optimizations</button>
      {note && <span style={{ fontSize: 10, color: 'var(--green)' }}>{note}</span>}
      {evolveNote && <span role="status" style={{ fontSize: 10, color: evolveNote.startsWith('refused') ? 'var(--red)' : 'var(--ink-3)' }}>{evolveNote}</span>}
    </div>
  </Card>;
}
function SessionsPanel() {
  const { d, e, loading, reload } = useApi('/sessions');
  const list = arr(d, 'sessions');
  return <Card title="SESSIONS" live={asLive(d)} sub={list.length} onReload={reload}>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 12).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{s.session_id || s.id || s}</span><span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{s.turns ?? s.count ?? ''}</span>{(s.session_id || s.id) && <button className="tool-btn" onClick={() => act('/sessions/resume', { session_id: s.session_id || s.id })}>resume</button>}</Row>)}
  </Card>;
}

/* ── Admin ─────────────────────────────────────────────── */
export function LMStudioPanel() {
  const { d, e, loading, reload } = useApi('/api/models/local', true, true);
  /* VLM leg of the local-model surface: user-guarded GET /api/vlm/status. The
     backend deliberately reports reachable:null (no probe) — render "not probed",
     never up/down. */
  const vlm = useApi('/api/vlm/status');
  const vlmD = vlm.d;
  const models = arr(d, 'models');
  const [note, setNote] = useState('');
  const say = (r) => { setNote(typeof r === 'object' ? (r.detail || r.status || (r.ok ? 'ok' : JSON.stringify(r).slice(0, 60))) : String(r)); reload(); };
  const runAction = (label, path, id, provider = '') => {
    setNote(`${label}…`);
    const body = provider ? { model: id, provider } : { model: id };
    apiPost(path, body, { admin: true }).then(say).catch((err) => {
      const status = Number(err?.status);
      setNote(`${label} failed${Number.isFinite(status) ? ` · HTTP ${status}` : ''}`.slice(0, 80));
      reload();
    });
  };
  return <Card title="LOCAL MODELS" live={asLive(d)} sub={models.length + ' models'} onReload={reload}>
    <State e={e} loading={loading} n={models.length} />
    {models.slice(0, 20).map((m) => {
      const id = String(m.id || m.name || '');
      const provider = String(m.provider || 'unknown');
      const lmStudioLifecycle = provider.trim().toLowerCase() === 'lm-studio';
      const key = `${provider}:${id}`;
      const status = localModelStatus(m);
      const statusColor = status === 'loaded' ? 'var(--green)'
        : status.includes('unknown') ? 'var(--amber)'
          : 'var(--ink-3)';
      const controls = m.controls || {};
      return <Row key={key}>
        <span style={{ ...mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{id}</span>
        <Tag>{provider}</Tag>
        <Tag c={statusColor}>{status}</Tag>
        {m.configured === true && <Tag c="var(--accent-light)">configured</Tag>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          {controls.can_configure === true && m.configured !== true && <button
            className="tool-btn"
            title={`configure ${key}`}
            onClick={() => runAction('configure', '/api/models/local/switch', id, provider)}
          >set default</button>}
          {lmStudioLifecycle && controls.can_load === true && <button
            className="tool-btn"
            title={`load ${key}`}
            onClick={() => runAction('load', '/api/llm/load', id)}
          >▶</button>}
          {lmStudioLifecycle && controls.can_unload === true && <button
            className="tool-btn"
            title={`unload ${key}`}
            onClick={() => runAction('unload', '/api/llm/unload', id)}
          >⏏</button>}
        </span>
      </Row>;
    })}
    {note && <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6 }}>{note}</div>}
    {vlmD && <div role="status" style={{ ...mono, fontSize: 10, color: vlmD.configured ? 'var(--ink-2)' : 'var(--ink-3)', marginTop: 6 }}>
      VLM · {vlmD.configured
        ? `${vlmD.backend} · ${vlmD.default_model || 'no default model'} · ${vlmD.local ? 'local' : 'remote'} · reachable not probed`
        : `off · ${vlmD.reason || 'not configured'}`}
    </div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>configured routing is independent from provider-reported residency · lifecycle actions follow backend capabilities</div>
  </Card>;
}
/* DRA-29 — the VLM *input* leg. The multimodal surface was output-only: the HUD
   read `GET /api/vlm/status` (the LOCAL MODELS config line) but nothing in the
   product ever called `POST /api/vlm/describe`. Images are read in the browser
   into `data:` URIs; `encode_image_block` rejects filesystem paths by design, so
   this control cannot smuggle a host file to the model.

   EGRESS DISCLOSURE — why this panel is not a bare form. Unlike
   `POST /api/screen/reflex`, `/api/vlm/describe` carries NO `is_local` gate, and
   that is deliberate on the backend: `resolve_vlm_config` supports a `custom`
   backend at an arbitrary URL and computes `is_local` as a *label*, and
   `_is_loopback_base` counts a LAN address as non-local — so a hard route-level
   gate would also refuse the owner's own second box, and would break an existing
   documented, snapshot-frozen contract for every caller. What must not happen is
   the HUD silently shipping owner-picked images off-host: so when the resolved
   VLM is not loopback this panel names the exact destination and refuses to
   upload until the owner ticks an explicit acknowledgement. This is a CONSENT
   gate on files the owner chose one by one, not a security boundary — the route
   is unchanged and behaves for curl exactly as it always has. A screen grab (which
   the owner cannot review before it is sent) keeps its hard route-level refusal;
   the asymmetry is the point. */
export const VLM_MAX_IMAGES = 8;
const VLM_MAX_IMAGE_BYTES = 4 * 1024 * 1024;
export function VlmDescribePanel() {
  const { d: vlmD, e, loading, reload } = useApi('/api/vlm/status');
  const [prompt, setPrompt] = useState('');
  const [images, setImages] = useState<Array<{ name: string; data: string }>>([]);
  const [out, setOut] = useState(null);
  const [note, setNote] = useState('');
  const [ack, setAck] = useState(false);
  const configured = !!vlmD && vlmD.configured === true;
  const isLocal = configured && vlmD.local === true;
  const destination = configured ? String(vlmD.base_url || 'an unnamed endpoint') : '';
  const needsAck = configured && !isLocal;

  const addFiles = (files) => {
    const picked = Array.from(files || []);
    if (!picked.length) return;
    const skipped: string[] = [];
    const taking: any[] = [];
    picked.forEach((f: any) => {
      if (f.size > VLM_MAX_IMAGE_BYTES) { skipped.push(`${f.name} · over 4 MB`); return; }
      if (images.length + taking.length >= VLM_MAX_IMAGES) { skipped.push(`${f.name} · over the ${VLM_MAX_IMAGES}-image limit`); return; }
      taking.push(f);
    });
    setNote(skipped.length ? `skipped · ${skipped.join(' · ')}` : '');
    taking.forEach((f: any) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || '');
        if (!result.startsWith('data:')) return;
        setImages((prev) => (prev.length >= VLM_MAX_IMAGES ? prev : prev.concat([{ name: f.name || 'image', data: result }])));
      };
      reader.readAsDataURL(f);
    });
  };

  const describe = () => {
    if (!configured || !prompt.trim() || !images.length) return;
    if (needsAck && !ack) {
      // Not a network call: nothing leaves the host until the destination is acknowledged.
      setNote(`refused · ${destination} is not loopback — acknowledge the destination before any image is uploaded`);
      return;
    }
    setOut(null);
    setNote('describing…');
    apiPost('/api/vlm/describe', { prompt, images: images.map((i) => i.data), model: '' })
      .then((r) => { setOut(r); setNote(''); })
      .catch((err) => {
        const status = Number(err?.status);
        setOut(null);
        setNote(`describe failed${Number.isFinite(status) ? ` · HTTP ${status}` : ''}`);
      });
  };

  return <Card
    title="VLM · DESCRIBE"
    live={asLive(vlmD, configured)}
    sub={vlmD ? (configured ? `${vlmD.backend} · ${vlmD.default_model || 'model unset'}` : 'no VLM') : null}
    onReload={reload}
  >
    <State e={e} loading={loading} n={null} />
    {vlmD && !configured && (
      <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginBottom: 6 }}>
        VLM off · {vlmD.reason || 'not configured'} — configure JARVIS_VLM_BACKEND / JARVIS_VLM_URL
      </div>
    )}
    {configured && isLocal && (
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginBottom: 6 }}>
        {destination} · loopback · reachable not probed
      </div>
    )}
    {needsAck && (
      <div role="alert" style={{ ...mono, fontSize: 10, color: 'var(--red)', marginBottom: 6 }}>
        <div>{destination} is NOT loopback — every image you pick would be uploaded to that host.</div>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, color: 'var(--amber)' }}>
          <input
            type="checkbox"
            aria-label={`acknowledge that images are uploaded to ${destination}`}
            checked={ack}
            onChange={(ev) => setAck(ev.target.checked)}
          />
          <span>I acknowledge these images leave this host</span>
        </label>
      </div>
    )}
    <input
      aria-label="image files to describe"
      type="file"
      accept="image/*"
      multiple
      onChange={(ev) => { addFiles(ev.target.files); }}
      style={{ ...inpS, width: '100%' }}
    />
    {images.map((im, i) => (
      <Row key={`${im.name}:${i}`}>
        <span style={{ ...mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{im.name}</span>
        <Btn onClick={() => setImages(images.filter((_, j) => j !== i))}>remove</Btn>
      </Row>
    ))}
    <input
      aria-label="describe prompt"
      value={prompt}
      maxLength={4000}
      onChange={(ev) => setPrompt(ev.target.value)}
      placeholder="prompt — e.g. what does this receipt total?"
      style={{ ...inpS, width: '100%', marginTop: 6 }}
    />
    <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
      <button
        className="tool-btn"
        type="button"
        disabled={!configured || !prompt.trim() || !images.length}
        onClick={describe}
        title={needsAck && !ack ? `acknowledge the ${destination} destination first` : 'describe the picked image(s)'}
      >describe</button>
      <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>{images.length}/{VLM_MAX_IMAGES} image(s)</span>
    </div>
    {out && out.ok === true && (
      <>
        <div style={{ ...mono, fontSize: 11, color: 'var(--ink)', marginTop: 8, whiteSpace: 'pre-wrap' }}>{out.response}</div>
        <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>model · {out.model || 'unnamed'}</div>
      </>
    )}
    {note && <div role="status" style={{ ...mono, fontSize: 10, color: /^(refused|describe failed)/.test(note) ? 'var(--red)' : 'var(--amber)', marginTop: 6 }}>{note}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
      images are read in the browser into data: URIs — the backend rejects file paths, so no host file can be smuggled through this control
    </div>
  </Card>;
}
export function AuthProfilesPanel() {
  const { d, e, loading, reload } = useApi('/api/llm/auth-profiles', true, true);
  /* arr() is always truthy, so the old `|| Object.entries(...)` fallback was dead
     and this panel rendered permanently empty: the API shape is {pools: {provider: status}}. */
  const fromArr = arr(d, 'profiles', 'pools');
  const list = fromArr.length ? fromArr : Object.entries((d as any)?.pools || {}).map(([k, v]) => ({ provider: k, ...(typeof v === 'object' ? v : {}) }));
  return <Card title="CLOUD AUTH PROFILES" live={asLive(d)} sub={list.length} onReload={reload}>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 8).map((p, i) => <Row key={i}>
      <span style={mono}>{p.provider || p.name || '?'}</span>
      <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{p.active || p.current || ''}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
        <Tag c={(p.healthy ?? p.ok ?? true) ? 'var(--green)' : 'var(--red)'}>{p.keys != null ? p.keys + ' key(s)' : (p.healthy ?? p.ok ?? true) ? 'healthy' : 'failing'}</Tag>
        {p.cooldown ? <Tag c="var(--amber)">cooldown</Tag> : null}
      </span></Row>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>masked rotation/failover pools (H12.20) · keys never shown</div>
  </Card>;
}
export function OAuthPanel() {
  const { d, e, loading, reload } = useApi('/api/oauth/status');
  /* same dead-fallback bug: /api/oauth/status returns a bare {service: {...}} map */
  const fromArr = arr(d, 'services');
  const svcs = fromArr.length ? fromArr : Object.entries(d || {}).filter(([, v]) => v && typeof v === 'object').map(([k, v]: [string, any]) => ({ service: k, ...(v || {}) }));
  return <Card title="OAUTH" live={asLive(d)} sub={svcs.length} onReload={reload}>
    <State e={e} loading={loading} n={svcs.length} />
    {svcs.slice(0, 8).map((s, i) => <Row key={i}><span style={mono}>{s.service || s.label || s.key}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
        <Tag c={s.connected ? 'var(--green)' : 'var(--ink-3)'}>{s.connected ? 'connected' : 'disconnected'}</Tag>
        {s.connected ? <button className="tool-btn" onClick={() => act('/api/oauth/refresh?service=' + (s.service || s.key), {}, reload)}>refresh</button>
          : s.auth_url ? <button className="tool-btn" onClick={() => window.open(s.auth_url, '_blank')}>connect</button> : null}
      </span></Row>)}
  </Card>;
}
function settingsField(it, val, on) {
  const ip = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: '3px 6px', ...mono, fontSize: 11 };
  switch (it.kind) {
    case 'toggle': return <input type="checkbox" checked={!!val} onChange={(e) => on(e.target.checked)} />;
    case 'select': return <select value={val} onChange={(e) => on(e.target.value)} style={ip}>{(it.opts || []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
    case 'number': case 'slider': return <input type="number" value={val} onChange={(e) => on(e.target.value === '' ? '' : Number(e.target.value))} style={{ ...ip, width: 84 }} />;
    case 'tags': return <input value={Array.isArray(val) ? val.join(', ') : (val || '')} onChange={(e) => on(e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} style={{ ...ip, width: 150 }} />;
    default: return <input value={val == null ? '' : val} onChange={(e) => on(e.target.value)} style={{ ...ip, width: 150 }} />;
  }
}
function SettingsPanel() {
  const { d, e, loading, reload } = useApi('/api/admin/settings');
  const [dirty, setDirty] = useState<Record<string, any>>({});
  const [saved, setSaved] = useState(null);
  const cats = d && typeof d === 'object' ? d : {};
  const setVal = (cat, key, v) => setDirty((p) => ({ ...p, [cat]: { ...(p[cat] || {}), [key]: v } }));
  const valOf = (cat, it) => (dirty[cat] && it.key in dirty[cat]) ? dirty[cat][it.key] : it.value;
  const nDirty = Object.values(dirty).reduce((a, o) => a + Object.keys(o).length, 0);
  const save = async () => {
    let n = 0;
    for (const cat of Object.keys(dirty)) {
      try { const r: any = await apiPut('/api/admin/settings/' + cat, { values: dirty[cat] }, { admin: true }); n += (r && r.updated) || 0; } catch { /* offline */ }
    }
    setSaved(n); setDirty({}); reload();
  };
  return <Card title="SETTINGS DB" live={asLive(d)} sub={Object.keys(cats).length + ' cat'} onReload={reload}>
    <State e={e} loading={loading} n={Object.keys(cats).length} />
    <div style={{ maxHeight: 300, overflow: 'auto' }}>
      {Object.entries(cats).map(([cat, items]: [string, any]) => (
        <div key={cat} style={{ marginBottom: 6 }}>
          <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-3)', margin: '6px 0 2px' }}>{String(cat).toUpperCase()}</div>
          {(items || []).map((it) => (
            <Row key={it.key}>
              <span style={{ fontSize: 11, color: 'var(--ink-2)', flex: '0 0 46%' }} title={it.key}>{it.label || it.key}</span>
              <span style={{ marginLeft: 'auto' }}>{settingsField(it, valOf(cat, it), (v) => setVal(cat, it.key, v))}</span>
            </Row>
          ))}
        </div>
      ))}
    </div>
    {nDirty > 0 && <button className="tool-btn" style={{ marginTop: 8 }} onClick={save}>💾 save {nDirty} change{nDirty === 1 ? '' : 's'}</button>}
    {saved != null && <span style={{ fontSize: 10, color: 'var(--green)', marginLeft: 8 }}>updated {saved}</span>}
  </Card>;
}
function PromptsPanel() {
  const [agent, setAgent] = useState('jarvis');
  const { d, e, loading, reload } = useApi('/api/admin/prompts/' + agent + '/history', true, true);
  const vers = arr(d, 'history', 'versions');
  const [pick, setPick] = useState([]);          // up to 2 selected versions → [A, B]
  const [diff, setDiff] = useState(null);
  const [ab, setAb] = useState(null);
  const [edit, setEdit] = useState(null);        // { version, content, message }
  const [preview, setPreview] = useState(null);
  const [note, setNote] = useState('');
  const a = pick[0], b = pick[1];
  const base = '/api/admin/prompts/' + agent;
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11 };

  const onAgent = (v) => { setAgent(v); setPick([]); setDiff(null); setAb(null); setEdit(null); setPreview(null); setNote(''); };
  const toggle = (vn) => setPick((p) => p.includes(vn) ? p.filter((x) => x !== vn) : [...p, vn].slice(-2));
  const loadAB = () => apiGet(base + '/ab', { admin: true }).then((r: any) => setAb(r.ab || null)).catch(() => setAb(null));
  const doDiff = () => { if (a == null || b == null) return; setDiff('…'); apiGet(`${base}/diff?a=${a}&b=${b}`, { admin: true }).then((r: any) => setDiff(r.diff ?? '')).catch(() => setDiff(null)); };
  const doAB = () => { if (a == null || b == null) return; apiPost(`${base}/ab`, { a, b, split: 0.5 }, { admin: true }).then(loadAB).catch(() => {}); };
  const rollback = (vn) => apiPost(`${base}/rollback`, { version: vn }, { admin: true }).then(() => { setNote('rolled back to v' + vn); reload(); }).catch(() => {});
  const loadEdit = (vn) => apiGet(`${base}/version/${vn}`, { admin: true }).then((v: any) => { setEdit({ version: vn, content: v.content || '', message: '' }); setPreview(null); }).catch(() => {});
  const doPreview = () => { if (!edit) return; apiPost(`${base}/preview`, { proposed: edit.content }, { admin: true }).then(setPreview).catch(() => {}); };
  const doCommit = () => { if (!edit) return; apiPost(`${base}/commit`, { content: edit.content, message: edit.message || ('edit of v' + edit.version) }, { admin: true }).then((r: any) => { setNote('committed v' + (r.version?.version ?? '?')); setEdit(null); setPreview(null); setPick([]); reload(); }).catch(() => {}); };

  useEffect(() => { loadAB(); }, [agent]); // eslint-disable-line

  return <Card title="PROMPT VERSIONS" live={asLive(d)} sub={agent + ' · ' + vers.length} onReload={reload}>
    <input value={agent} onChange={(ev) => onAgent(ev.target.value)} placeholder="agent id" style={{ ...inp, width: '100%', marginBottom: 6 }} />
    <State e={e} loading={loading} n={vers.length} />
    {vers.slice(0, 10).map((v, i) => {
      const vn = v.version ?? i;
      const slot = a === vn ? 'A' : b === vn ? 'B' : null;
      return <Row key={i}>
        <span onClick={() => toggle(vn)} style={{ ...mono, cursor: 'pointer', color: slot ? 'var(--accent)' : 'var(--accent-light)' }} title="pick A/B">v{vn}</span>
        {slot && <Tag c="var(--accent)">{slot}</Tag>}
        {v.is_current && <Tag c="var(--green)">current</Tag>}
        <span style={{ fontSize: 10, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v.message}>{(v.message || v.author || v.hash || '').slice(0, 22)}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          <button className="tool-btn" onClick={() => loadEdit(vn)} title="edit → new version">✎</button>
          {!v.is_current && <button className="tool-btn" onClick={() => rollback(vn)} title="rollback to this">⟲</button>}
        </span>
      </Row>;
    })}
    <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <button className="tool-btn" onClick={doDiff} disabled={a == null || b == null}>diff {a ?? '·'}↔{b ?? '·'}</button>
      <button className="tool-btn" onClick={doAB} disabled={a == null || b == null}>A/B {a ?? '·'}↔{b ?? '·'}</button>
      {note && <span style={{ fontSize: 10, color: 'var(--green)' }}>{note}</span>}
    </div>
    {diff != null && <DiffView text={diff === '…' ? '' : diff} />}
    {ab && <div style={{ ...mono, fontSize: 10.5, marginTop: 8, padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4 }}>
      <div style={{ color: 'var(--ink-3)', letterSpacing: '.1em' }}>A/B · v{ab.a} vs v{ab.b} · split {Math.round((ab.split ?? 0.5) * 100)}% → B</div>
      {[ab.a, ab.b].map((ver) => { const r = (ab.results || {})[ver] || {}; const m = (ab.means || {})[ver]; return <Row key={ver}><span>v{ver}{ab.winner === ver ? ' ★' : ''}</span><span style={{ marginLeft: 'auto', color: 'var(--ink-3)' }}>n={r.n ?? 0} · μ={m == null ? '—' : m}</span></Row>; })}
    </div>}
    {edit && <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginBottom: 4 }}>editing from v{edit.version} → commits a NEW version (non-destructive)</div>
      <textarea value={edit.content} onChange={(ev) => setEdit({ ...edit, content: ev.target.value })} style={{ width: '100%', minHeight: 110, ...inp }} />
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <input value={edit.message} onChange={(ev) => setEdit({ ...edit, message: ev.target.value })} placeholder="commit message" style={{ ...inp, flex: 1, minWidth: 120 }} />
        <button className="tool-btn" onClick={doPreview}>preview</button>
        <button className="tool-btn" onClick={doCommit}>commit</button>
        <button className="tool-btn" onClick={() => { setEdit(null); setPreview(null); }}>✕</button>
      </div>
      {preview && <div style={{ marginTop: 6 }}>
        <div style={{ ...mono, fontSize: 10, color: preview.valid ? 'var(--green)' : 'var(--amber)' }}>+{preview.added_lines} −{preview.removed_lines} · {preview.valid ? 'valid' : 'warn: ' + (preview.warnings || []).join('; ')}</div>
        <DiffView text={preview.diff} />
      </div>}
    </div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>click v# to pick A/B · ✎ edit · ⟲ rollback · A/B + diff + rollback (H10.22)</div>
  </Card>;
}
export function RoomsPanel() {
  const { d, e, loading, reload } = useApi('/api/rooms');
  const rooms = arr(d, 'rooms');
  const [name, setName] = useState(''); const [sel, setSel] = useState(''); const [msg, setMsg] = useState('');
  const hist = useApi(sel ? '/api/rooms/' + encodeURIComponent(sel) + '/history' : '/api/rooms', Boolean(sel));
  const turns = arr(hist.d, 'history');
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11, flex: 1 };
  const create = () => { if (!name.trim()) return; apiPost('/api/rooms', { name: name.trim() }).then(() => { setName(''); reload(); }).catch(() => {}); };
  const send = () => {
    if (!sel || !msg.trim()) return;
    apiPost('/api/rooms/' + encodeURIComponent(sel) + '/message', { message: msg.trim() })
      .then(() => { setMsg(''); hist.reload(); })
      .catch(() => {});
  };
  return <Card title="ROOMS" live={asLive(d)} sub={rooms.length} onReload={reload}>
    <State e={e} loading={loading} n={rooms.length} />
    {rooms.slice(0, 10).map((r, i) => <Row key={i}><span style={{ ...mono, color: sel === (r.id || r.name) ? 'var(--accent)' : 'var(--accent-light)', cursor: 'pointer' }} onClick={() => setSel(r.id || r.name)}>{r.name || r.id}</span><span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{(r.agents || []).join(', ')}</span></Row>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="new room" style={inp} />
      <button className="tool-btn" onClick={create}>+ room</button>
    </div>
    {sel && <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <input value={msg} onChange={(ev) => setMsg(ev.target.value)} placeholder={'message ' + sel + ' (@agent)'} onKeyDown={(ev) => { if (ev.key === 'Enter') send(); }} style={inp} />
      <button className="tool-btn" onClick={send}>send</button>
    </div>}
    {sel && <div style={{ marginTop: 8, padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)' }}>HISTORY · {sel}</span>
        <button className="tool-btn" style={{ marginLeft: 'auto' }} title="reload room history" onClick={hist.reload}>↻</button>
      </div>
      <State e={hist.e} loading={hist.loading} n={turns.length} />
      {turns.slice(-8).map((t, i) => {
        const label = t.agent || t.role || 'turn';
        const text = t.content || t.message || t.text || '';
        const ts = t.at || t.created_at || t.ts || '';
        return <Row key={i}>
          <Tag c={t.role === 'assistant' ? 'var(--accent-light)' : 'var(--ink-3)'}>{label}</Tag>
          <span style={{ ...mono, color: 'var(--ink-2)', flex: 1, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{text}</span>
          {ts && <span style={{ ...mono, marginLeft: 'auto', fontSize: 9.5, color: 'var(--ink-3)' }}>{String(ts).slice(0, 19)}</span>}
        </Row>;
      })}
    </div>}
  </Card>;
}

// "What it did" — a chronological view over the hash-chained audit log (every real
// action) merged with the autonomy task queue. Answers the owner's "show me what it
// did, visually" ask. Honest: empty state when there's no activity, never fabricated.
export function ActivityTimelinePanel() {
  const audit = useApi('/api/admin/audit?limit=40', true, true);
  const tasks = useApi('/tasks?view=history');
  const [flt, setFlt] = useState<'all' | 'audit' | 'task'>('all');
  const rows = arr(audit.d, 'rows');
  const tks = arr(tasks.d, 'tasks');
  const all = [
    ...rows.map((r: any) => ({ ts: r.timestamp || r.ts || '', kind: r.event_type || 'event', text: r.summary || r.content_preview || '', src: 'audit' })),
    ...tks.map((t: any) => ({ ts: t.created_at || t.updated_at || '', kind: t.kind || 'task', text: (t.title || '') + (t.decision ? ' · ' + t.decision : (t.status ? ' · ' + t.status : '')), src: 'task' })),
  ].filter((x) => x.ts).sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  const items = (flt === 'all' ? all : all.filter((x) => x.src === flt)).slice(0, 40);
  const fbtn = (id: 'all' | 'audit' | 'task', label: string) => <button className="tool-btn"
    style={{ borderColor: flt === id ? 'var(--accent-light)' : undefined, color: flt === id ? 'var(--accent-light)' : undefined }}
    onClick={() => setFlt(id)}>{label}</button>;
  return <Card title="ACTIVITY · what it did" live={asLive(audit.d)} sub={items.length} onReload={() => { audit.reload(); tasks.reload(); }}>
    <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>{fbtn('all', 'all')}{fbtn('audit', 'audit')}{fbtn('task', 'tasks')}</div>
    <State e={audit.e} loading={audit.loading} n={items.length} />
    {items.length === 0 && !audit.loading && <Row><span style={{ ...mono, color: 'var(--ink-3)' }}>no activity yet — actions and decisions will appear here</span></Row>}
    {items.map((it, i) => <Row key={i}>
      <Tag c={it.src === 'task' ? 'var(--accent-light)' : 'var(--ink-3)'}>{it.kind}</Tag>
      <span style={{ ...mono, color: 'var(--ink-2)', flex: 1, whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{it.text}</span>
      <span style={{ ...mono, marginLeft: 'auto', fontSize: 9.5, color: 'var(--ink-3)' }}>{String(it.ts).slice(0, 19)}</span>
    </Row>)}
  </Card>;
}

// PROJECTS — unifies Rooms (topic threads with persistent history + @mention roster)
// and Missions (governed workspaces) into one surface, plus session history and the
// activity timeline, so the owner can run multiple subjects in parallel with history.
// Reuses the existing panels (their data layer already works); this is the layout.
export function ProjectsMode(_props: any) {
  return <div style={{ padding: '16px 20px', maxWidth: 1440, margin: '0 auto' }}>
    <div style={{ ...mono, fontSize: 11, letterSpacing: '.16em', color: 'var(--ink-3)', marginBottom: 12 }}>PROJECTS · rooms = topic threads with history · missions = governed workspaces · sessions = reopen a past chat</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, alignItems: 'start' }}>
      <RoomsPanel />
      <MissionsPanel />
      <SessionsPanel />
      <ActivityTimelinePanel />
    </div>
  </div>;
}

// H23.16 — network monitor: reads the egress ledger (GET /api/admin/network/calls)
// and proves LOCAL_ONLY plugins make zero outbound calls. `clean` is the headline:
// green when no local-only plugin ever made an allowed external call.
export function NetworkMonitorPanel() {
  const { d, e, loading, reload } = useApi('/api/admin/network/calls', true, true);
  const plugins = (d && d.plugins) || {};
  const names = Object.keys(plugins);
  const ext = d ? d.external_egress_total : 0;
  const violations = (d && d.local_only_violations) || [];
  const clean = d ? d.clean : true;
  return (
    <Card title="network monitor" live={asLive(d)} sub={d ? (clean ? 'local-only ✓' : 'VIOLATION') : null} onReload={reload}>
      <State e={e} loading={loading} n={names.length} />
      {d && (
        <Row>
          <span style={mono}>egress</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={ext > 0 ? 'var(--amber)' : 'var(--green)'}>{ext} external</Tag>
            <Tag c={clean ? 'var(--green)' : 'var(--red)'}>{clean ? 'clean' : 'violation'}</Tag>
          </span>
        </Row>
      )}
      {violations.length > 0 && (
        <Row><span style={{ ...mono, color: 'var(--red)' }}>⚠ local-only egress: {violations.join(', ')}</span></Row>
      )}
      {names.map((name) => {
        const p = plugins[name];
        return (
          <Row key={name}>
            <span style={mono}>{name}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {p.external > 0 && <Tag c="var(--amber)">{p.external} ext</Tag>}
              {p.blocked > 0 && <Tag c="var(--red)">{p.blocked} blocked</Tag>}
              <Tag c="var(--green)">{p.allowed} ok</Tag>
            </span>
          </Row>
        );
      })}
    </Card>
  );
}

export function FeedbackPanel() {
  const { d, e, loading, reload } = useApi('/api/feedback/summary', true, true);  // admin summary
  const [score, setScore] = useState(9);
  const [msg, setMsg] = useState('');
  const [sent, setSent] = useState(false);
  const submit = () => act('/api/feedback', { kind: 'nps', score, message: msg }, () => { setSent(true); setMsg(''); reload(); });
  const nps = d ? d.nps : null;
  const byKind = (d && d.by_kind) || {};
  const recent = (d && d.recent) || [];
  return (
    <Card title="FEEDBACK · NPS" live={asLive(d)} sub={d ? (nps == null ? 'no scores' : `NPS ${nps}`) : null} onReload={reload}>
      <State e={e} loading={loading} n={recent.length} />
      {d && (
        <Row>
          <span style={mono}>nps</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c="var(--green)">{d.promoters || 0} prom</Tag>
            <Tag c="var(--red)">{d.detractors || 0} detr</Tag>
            <Tag c={nps == null ? 'var(--ink-3)' : (nps >= 0 ? 'var(--green)' : 'var(--red)')}>{nps == null ? '—' : nps}</Tag>
          </span>
        </Row>
      )}
      {Object.keys(byKind).length > 0 && (
        <Row><span style={mono}>by kind</span><span style={{ marginLeft: 'auto', ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{Object.entries(byKind).map(([k, v]) => `${k}:${v}`).join('  ')}</span></Row>
      )}
      {recent.slice(0, 6).map((r, i) => (
        <Row key={i}><Tag>{r.kind}{r.score != null ? ` ${r.score}` : ''}</Tag><span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(r.message || '').slice(0, 40)}</span></Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <span style={{ ...mono, fontSize: 10 }}>NPS</span>
        <input type="number" min={0} max={10} value={score} onChange={(ev) => setScore(Number(ev.target.value))} style={{ ...inpS, width: 48 }} />
        <input value={msg} onChange={(ev) => setMsg(ev.target.value)} placeholder="comment…" style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={submit}>send</button>
      </div>
      {sent && <div style={{ fontSize: 10, color: 'var(--green)', marginTop: 4 }}>thanks — recorded locally</div>}
    </Card>
  );
}

export function OnboardingPanel() {
  const { d, e, loading, reload } = useApi('/api/onboarding/wizard');
  const steps = (d && d.steps) || [];
  const done = new Set((d && d.completed) || []);
  return (
    <Card title="ONBOARDING" live={asLive(d)} sub={d ? (d.complete ? 'complete ✓' : `${done.size}/${steps.length}`) : null} onReload={reload}>
      <State e={e} loading={loading} n={steps.length} />
      {d && d.hint && <Row><span style={{ color: 'var(--amber)', fontSize: 11 }}>⚠ {d.hint}</span></Row>}
      {steps.map((s) => {
        const ok = done.has(s.key);
        return (
          <Row key={s.key}>
            <span style={{ color: ok ? 'var(--green)' : 'var(--ink-2)' }}>{ok ? '✓' : '○'} {s.title}</span>
            {!ok && <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => act('/api/onboarding/funnel', { step: s.key, event: 'complete' }, reload)}>done</button>}
          </Row>
        );
      })}
    </Card>
  );
}

/* HUD-v3 B1 — the DECISION INBOX (the product north-star). The frontend READ /tasks (the
   autonomy queue, drawn as a network fan) but had NO control to resolve a blocked
   decision. This is it: the blocked queue (GET /autonomy/tasks?status=blocked) with
   accept / reject / defer, each → POST /autonomy/tasks/{id}/decision {action} (admin). */
export function DecisionInboxPanel() {
  const { d, e, loading, reload } = useApi('/autonomy/tasks?status=blocked', true, true);  // admin
  const pending = arr(d, 'tasks');
  const interrupts = useApi('/autonomy/interrupts', true, true);   // admin — the calm-by-the-numbers budget
  const ib = interrupts.d;
  const [editing, setEditing] = useState(null);   // task id whose payload is being edited
  const [draft, setDraft] = useState('');
  const decide = (id, action, payload?) => actA('/autonomy/tasks/' + id + '/decision',
    payload !== undefined ? { action, payload } : { action }, () => { setEditing(null); reload(); });
  const startEdit = (t) => { setEditing(t.id); setDraft(JSON.stringify(t.payload || {}, null, 2)); };
  const saveEdit = (id) => { let p; try { p = JSON.parse(draft); } catch { return; } decide(id, 'edit', p); };
  // dry-run preview (H12.5) — "see what it'll do before you approve" (the open preview endpoint)
  const [preview, setPreview] = useState(null);   // { id, data }
  const loadPreview = (id) => {
    if (preview && preview.id === id) { setPreview(null); return; }
    setPreview({ id, data: null });
    apiGet('/api/autonomy/tasks/' + id + '/preview', { admin: true })
      .then((r) => setPreview({ id, data: r || {} }))
      .catch(() => setPreview({ id, data: { error: 'preview unavailable' } }));
  };
  const tierColor = (n) => n >= 3 ? 'var(--red)' : n === 2 ? 'var(--amber)' : 'var(--ink-3)';
  return (
    <Card title="DECISION INBOX" live={asLive(d)}
      sub={d ? `${pending.length} awaiting you` + (ib && ib.per_day != null ? ` · ${ib.used ?? 0}/${ib.per_day} interrupts today` : '') : null}
      onReload={() => { reload(); interrupts.reload(); }}>
      <State e={e} loading={loading} n={pending.length} />
      {pending.slice(0, 10).map((t, i) => (
        <div key={t.id ?? i}>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{t.title || t.kind || ('task ' + t.id)}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {typeof t.risk_tier === 'number' && <Tag c={tierColor(t.risk_tier)}>tier {t.risk_tier}</Tag>}
              <button className="tool-btn" title="dry-run preview" onClick={() => loadPreview(t.id)}>preview</button>
              <button className="tool-btn" title="accept" onClick={() => decide(t.id, 'accept')}>✓</button>
              <button className="tool-btn" title="edit" onClick={() => startEdit(t)}>edit</button>
              <button className="tool-btn" title="reject" onClick={() => decide(t.id, 'reject')}>✕</button>
              <button className="tool-btn" title="defer" onClick={() => decide(t.id, 'defer')}>defer</button>
            </span>
          </Row>
          {t.rollback && <div style={{ margin: '3px 0 7px 12px', fontSize: 10, color: 'var(--ink-2)' }}>
            <div><span style={{ ...mono, color: 'var(--accent-light)' }}>rollback · </span>{t.rollback.description}</div>
            {t.rollback.limitations && <div style={{ color: 'var(--amber)', marginTop: 2 }}>{t.rollback.limitations}</div>}
          </div>}
          {preview && preview.id === t.id && (
            <div style={{ margin: '4px 0 8px 12px', fontSize: 10 }}>
              {preview.data === null ? <span style={{ color: 'var(--ink-3)' }}>previewing…</span>
                : preview.data.error ? <span style={{ color: 'var(--amber)' }}>{preview.data.error}</span>
                : (
                  <>
                    <div style={{ color: 'var(--ink-2)' }}>{preview.data.summary || preview.data.title || 'dry run'}</div>
                    <div style={{ display: 'flex', gap: 5, marginTop: 3, flexWrap: 'wrap', alignItems: 'center' }}>
                      {preview.data.irreversible && <Tag c="var(--red)">irreversible</Tag>}
                      <Tag c={preview.data.would_execute ? 'var(--green)' : 'var(--ink-3)'}>{preview.data.would_execute ? 'would execute' : 'would queue'}</Tag>
                      {(preview.data.effects || []).slice(0, 4).map((ef, k) => (
                        <Tag key={k}>{typeof ef === 'string' ? ef : (ef.field || ef.summary || 'effect')}</Tag>
                      ))}
                    </div>
                  </>
                )}
            </div>
          )}
          {editing === t.id && (
            <div style={{ margin: '6px 0' }}>
              <textarea value={draft} onChange={(ev) => setDraft(ev.target.value)} style={{ ...taS, minHeight: 80 }} />
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                <button className="tool-btn" onClick={() => saveEdit(t.id)}>save &amp; approve</button>
                <button className="tool-btn" onClick={() => setEditing(null)}>cancel</button>
              </div>
            </div>
          )}
        </div>
      ))}
      {pending.length === 0 && <div style={{ fontSize: 10, color: 'var(--green)', marginTop: 6 }}>all clear · no decisions waiting</div>}
    </Card>
  );
}

/* HUD-v3 C1 — Missions board. The 0.32 Mission Workspaces backend (long-horizon
   governed work) + its data-layer fetch existed, but no control surface did. Surfaces
   the board with contextual governed-action controls (start/pause/resume/complete/
   cancel) wired to the real user-guarded /api/missions/{id}/{action} routes. */
export function MissionsPanel() {
  const { d, e, loading, reload } = useApi('/api/missions');
  const missions = arr(d, 'missions');
  const statusColor = (s) => s === 'active' ? 'var(--green)' : s === 'paused' ? 'var(--amber)' : s === 'failed' ? 'var(--red)' : s === 'done' ? 'var(--accent-light)' : 'var(--ink-3)';
  // contextual transitions, matching the missions state machine (planned→active→paused→done)
  const actionsFor = (s) => s === 'planned' ? ['start'] : s === 'active' ? ['pause', 'complete', 'cancel'] : s === 'paused' ? ['resume', 'cancel'] : [];
  return (
    <Card title="MISSIONS" live={asLive(d)} sub={d ? `${missions.length} workspaces` : null} onReload={reload}>
      <State e={e} loading={loading} n={missions.length} />
      {missions.slice(0, 12).map((m, i) => (
        <Row key={m.id ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{m.title || '(untitled)'}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={statusColor(m.status)}>{m.status}</Tag>
            <Tag>{m.steps_used ?? 0}/{m.max_steps ?? '—'}</Tag>
            {actionsFor(m.status).map((a) => (
              <button key={a} className="tool-btn" onClick={() => act('/api/missions/' + m.id + '/' + a, {}, reload)}>{a}</button>
            ))}
          </span>
        </Row>
      ))}
    </Card>
  );
}

/* HUD-v3 C2 (per-agent half) — the per-agent autonomy dial. PR 0 (#418) made
   AutonomyPolicy.agent_modes enforceable (one agent AUTO/ASK/OFF while the rest follow
   the global mode) but there was no control surface. This is it: GET /autonomy/policy
   shows the global mode + each per-agent override; POST sets one; mode=default clears it
   (falls back to global). Admin-guarded. Complements the global AutonomyMode in modes2. */
export function AgentAutonomyPanel() {
  const { d, e, loading, reload } = useApi('/autonomy/policy', true, true);  // admin-guarded
  const globalMode = (d && d.global) || '—';
  const agents = (d && d.agents) || {};
  const entries = Object.keys(agents).map((k) => [k, agents[k]]);
  const [agent, setAgent] = useState('');
  const [mode, setMode] = useState('ask');
  const setPolicy = (ag, m) => actA('/autonomy/policy', { agent: ag, mode: m }, reload);
  const modeColor = (m) => m === 'auto' ? 'var(--green)' : m === 'ask' ? 'var(--amber)' : m === 'off' ? 'var(--red)' : 'var(--ink-3)';
  return (
    <Card title="PER-AGENT AUTONOMY" live={asLive(d)} sub={d ? `global: ${globalMode}` : null} onReload={reload}>
      <State e={e} loading={loading} n={entries.length} />
      {entries.map(([ag, m]) => (
        <Row key={ag}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{ag}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag c={modeColor(m)}>{m}</Tag>
            <button className="tool-btn" title="clear (follow global)" onClick={() => setPolicy(ag, 'default')}>✕</button>
          </span>
        </Row>
      ))}
      {entries.length === 0 && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>no overrides · every agent follows the global mode ({globalMode})</div>}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder="agent" style={{ ...inpS, flex: 1 }} />
        <select value={mode} onChange={(ev) => setMode(ev.target.value)} style={{ ...inpS }}>
          <option value="auto">auto</option><option value="ask">ask</option><option value="off">off</option>
        </select>
        <button className="tool-btn" onClick={() => { if (agent.trim()) { setPolicy(agent.trim(), mode); setAgent(''); } }}>set</button>
      </div>
    </Card>
  );
}

/* HUD-v3 C9 (data controls) — Backup & Export. The 0.14/H23.8 backup + H23.9 export
   backend (consistent SQLite snapshots, restore-drill, portable JSON takeout) had no
   control surface. This is the data-sovereignty front door: list snapshots, back up
   now, restore-drill verify, export-my-data. All admin-guarded. */
export function BackupPanel() {
  const { d, e, loading, reload } = useApi('/api/admin/backup', true, true);  // admin-guarded
  const backups = arr(d, 'backups');
  const [msg, setMsg] = useState(null);
  const sz = (b) => typeof b === 'number' ? (b >= 1e6 ? (b / 1e6).toFixed(1) + 'MB' : Math.max(1, Math.round(b / 1024)) + 'KB') : '—';
  const create = () => actA('/api/admin/backup', {}, (r) => { setMsg(r && r.bytes ? 'backup created · ' + sz(r.bytes) : 'backup created'); reload(); });
  const verify = () => actA('/api/admin/backup/verify', {}, (r) => setMsg(r && r.ok ? 'restore-drill OK · ' + (r.file_count || 0) + ' files' : 'verify failed'));
  const exportMe = () => actA('/api/admin/export', {}, (r) => setMsg(r && r.bytes ? 'export written · ' + sz(r.bytes) : 'export written'));
  // forget-me (C9, destructive) — the backend requires {"confirm":"FORGET"}; the UI mirrors
  // that hard-to-fat-finger acknowledgement with a typed-confirmation reveal. Backup-first.
  const [armed, setArmed] = useState(false);
  const [confirm, setConfirm] = useState('');
  const forget = () => {
    if (confirm !== 'FORGET') return;
    actA('/api/admin/forget', { confirm: 'FORGET' }, (r) => {
      setMsg(r && r.ok !== false ? 'forgotten · backup-first purge complete' : 'forget failed');
      setArmed(false); setConfirm(''); reload();
    });
  };
  return (
    <Card title="BACKUP · EXPORT · FORGET" live={asLive(d)} sub={d ? `${backups.length} snapshots` : null} onReload={reload}>
      <State e={e} loading={loading} n={backups.length} />
      {backups.slice(0, 8).map((b, i) => (
        <Row key={b.name ?? i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{b.name}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {b.encrypted && <Tag c="var(--green)">enc</Tag>}
            <Tag>{sz(b.bytes)}</Tag>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button className="tool-btn" onClick={create}>back up now</button>
        <button className="tool-btn" onClick={verify}>verify</button>
        <button className="tool-btn" onClick={exportMe}>export my data</button>
      </div>
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
      {!armed
        ? <button className="tool-btn" style={{ marginTop: 8, color: 'var(--red)' }} onClick={() => setArmed(true)}>forget me…</button>
        : (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--red)' }}>type FORGET to erase all content (backup-first):</span>
            <input value={confirm} onChange={(ev) => setConfirm(ev.target.value)} placeholder="FORGET" style={{ ...inpS, width: 90 }} />
            <button className="tool-btn" disabled={confirm !== 'FORGET'} style={{ color: confirm === 'FORGET' ? 'var(--red)' : 'var(--ink-3)' }} onClick={forget}>confirm erase</button>
            <button className="tool-btn" onClick={() => { setArmed(false); setConfirm(''); }}>cancel</button>
          </div>
        )}
    </Card>
  );
}

export function TodayPanel() {
  // P1 G1 — "Today in Jarvis": what Jarvis *did* (autonomy) + *learned* (memory) in one feed.
  const { d, e, loading, reload } = useApi('/api/dashboard/today');
  const items = (d && d.items) || [];
  const c = (d && d.counts) || {};
  const fmt = (ts) => {
    if (!ts) return '—';
    const t = new Date(String(ts).replace(' ', 'T'));
    return isNaN(t.getTime()) ? String(ts) : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };
  return (
    <Card title="TODAY" live={asLive(d)} sub={d ? `${c.actions || 0} did · ${c.learnings || 0} learned` : null} onReload={reload}>
      <State e={e} loading={loading} n={items.length} />
      {items.slice(0, 12).map((it, i) => (
        <Row key={i}>
          <Tag c={it.kind === 'action' ? 'var(--green)' : 'var(--accent-light)'}>{it.kind === 'action' ? 'did' : 'learned'}</Tag>
          <span style={{ fontSize: 11, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {it.kind === 'action' ? (it.title || `#${it.id}`) : `${it.key}: ${it.value}`}
          </span>
          <span style={{ marginLeft: 'auto', ...mono, fontSize: 9.5, color: 'var(--ink-3)' }}>{fmt(it.ts)}</span>
        </Row>
      ))}
    </Card>
  );
}

/* 0.58 — the skill version-history read surface (GET /api/skills/marketplace/history,
   admin). Renders publish/install/uninstall events + per-action stats. Honesty contract:
   when JARVIS_SKILL_HISTORY is off the endpoint reports enabled:false and the panel says
   so plainly rather than implying history is being kept. */
export function SkillHistoryPanel() {
  const { d, e, loading, reload } = useApi('/api/skills/marketplace/history', true, true);
  const enabled = !!(d && d.enabled);
  const events = arr(d && d.events);
  const byAction = (d && d.stats && d.stats.by_action) || {};
  return (
    <Card title="SKILL HISTORY" live={d ? (enabled ? 'live' : 'seed') : undefined} sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} events` : 'disabled') : null} onReload={reload}>
      <State e={e} loading={loading} n={events.length} />
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_SKILL_HISTORY is on — rollback does not depend on this ledger; its control is in SKILLS MARKETPLACE</div>}
      {enabled && Object.keys(byAction).length > 0 && (
        <Row>
          <span style={mono}>actions</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {Object.entries(byAction).map(([a, n]) => <Tag key={a}>{String(n)} {a}</Tag>)}
          </span>
        </Row>
      )}
      {events.slice(0, 8).map((ev, i) => (
        <Row key={ev.id || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{ev.name}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{ev.action} · {ev.version}</span>
        </Row>
      ))}
    </Card>
  );
}

/* 0.46 — the generated-media catalog read surface (GET /api/media/catalog). Renders
   recent items + per-kind stats. Honesty contract: when JARVIS_MEDIA_CATALOG is off the
   endpoint reports enabled:false and the panel says so (prompts are sensitive, so nothing
   is recorded by default). */
export function MediaGalleryPanel() {
  const { d, e, loading, reload } = useApi('/api/media/catalog');
  const enabled = !!(d && d.enabled);
  const items = arr(d && d.items);
  const byKind = (d && d.stats && d.stats.by_kind) || {};
  return (
    <Card title="MEDIA GALLERY" live={d ? (enabled ? 'live' : 'seed') : undefined} sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} items` : 'disabled') : null} onReload={reload}>
      <State e={e} loading={loading} n={items.length} />
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_MEDIA_CATALOG is on</div>}
      {enabled && Object.keys(byKind).length > 0 && (
        <Row>
          <span style={mono}>kinds</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {Object.entries(byKind).map(([k, n]) => <Tag key={k}>{String(n)} {k}</Tag>)}
          </span>
        </Row>
      )}
      {items.slice(0, 8).map((it, i) => (
        <Row key={it.id || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{it.kind}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{(it.prompt || '').slice(0, 40)}</span>
        </Row>
      ))}
    </Card>
  );
}

/* H29 — governed presentation across owner-curated media devices. This panel is
   deliberately metadata-only: it lists registry/session state but never embeds
   remote media in the HUD. */
export function MediaDirectorPanel() {
  const devicesApi = useApi('/api/media/devices');
  const sessionsApi = useApi('/api/media/session');
  const devices = arr(devicesApi.d, 'devices');
  const sessions = arr(sessionsApi.d, 'sessions');
  const loaded = !!(devicesApi.d && sessionsApi.d);
  const enabled = loaded && !!devicesApi.d.enabled && !!sessionsApi.d.enabled;
  const [contentType, setContentType] = useState('url');
  const [contentValue, setContentValue] = useState('');
  const [target, setTarget] = useState('');
  const [mode, setMode] = useState('play');
  const [privacy, setPrivacy] = useState('household');
  const [urgency, setUrgency] = useState('normal');
  const [duration, setDuration] = useState('');
  const [outcome, setOutcome] = useState(null);
  const [deviceId, setDeviceId] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [deviceKind, setDeviceKind] = useState('local');
  const [deviceRoom, setDeviceRoom] = useState('');
  const [deviceSupports, setDeviceSupports] = useState('play');
  const [adminMessage, setAdminMessage] = useState('');
  const contentLimit = contentType === 'query' ? 256 : 2048;
  const allMediaModes = ['play', 'show', 'announce'];
  const selectedDevice = devices.find((device) => device.id === target);
  const availableModes = selectedDevice
    ? (Array.isArray(selectedDevice.supports) ? selectedDevice.supports : []).filter((value) => allMediaModes.includes(value))
    : allMediaModes;
  const present = (ev) => {
    ev.preventDefault();
    if (!contentValue.trim() || !target || !availableModes.includes(mode)) return;
    const body = {
      content: { type: contentType, value: contentValue.trim() },
      target,
      mode,
      privacy,
      urgency,
      ...(duration ? { duration_seconds: Number(duration) } : {}),
    };
    setOutcome({ status: 'sending' });
    apiPost('/api/media/present', body)
      .then((result) => { setOutcome(result); sessionsApi.reload(); })
      .catch((err) => setOutcome({ status: 'failed', reason: err?.message || 'request_failed' }));
  };
  const restore = (deviceId) => {
    setOutcome({ status: 'sending' });
    apiPost('/api/media/restore/' + encodeURIComponent(deviceId))
      .then((result) => { setOutcome(result); sessionsApi.reload(); })
      .catch((err) => setOutcome({ status: 'failed', reason: err?.message || 'request_failed' }));
  };
  const registerDevice = (ev) => {
    ev.preventDefault();
    if (!deviceId.trim() || !deviceName.trim()) return;
    const supports = deviceSupports.split(',').map((value) => value.trim()).filter(Boolean).slice(0, 16);
    if (!supports.length) return;
    apiPost('/api/media/devices', {
      id: deviceId.trim(), name: deviceName.trim(), kind: deviceKind,
      room: deviceRoom.trim(), supports,
    }, { admin: true })
      .then(() => { setAdminMessage('device registered'); devicesApi.reload(); })
      .catch((err) => setAdminMessage(err?.message || 'device registration failed'));
  };
  const removeDevice = (id) => apiDelete('/api/media/devices/' + encodeURIComponent(id), { admin: true })
    .then(() => { setAdminMessage(`removed ${id}`); devicesApi.reload(); })
    .catch((err) => setAdminMessage(err?.message || 'device removal failed'));

  return (
    <Card
      title="MEDIA DIRECTOR"
      live={loaded ? (enabled ? 'live' : 'seed') : undefined}
      sub={loaded ? (enabled ? `${devices.length} devices · ${sessions.length} sessions` : 'disabled') : null}
      onReload={() => { devicesApi.reload(); sessionsApi.reload(); }}
    >
      <State
        e={devicesApi.e || sessionsApi.e}
        loading={devicesApi.loading || sessionsApi.loading}
        n={loaded && !enabled ? undefined : devices.length + sessions.length}
      />
      {loaded && !enabled && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          off by default · set JARVIS_MEDIA_DIRECTOR=1 to enable governed presentation
        </div>
      )}
      {enabled && <>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '4px 0' }}>DEVICES</div>
        {devices.map((device, i) => (
          <Row key={device.id || i}>
            <span style={{ ...mono, color: 'var(--accent-light)' }}>{device.name || device.id}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              {device.room && <Tag>{device.room}</Tag>}
              <Tag>{device.kind}</Tag>
            </span>
          </Row>
        ))}
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>SESSIONS</div>
        {sessions.map((session, i) => (
          <Row key={session.device_id || i}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{session.device_id}</span>
            <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>
              {session.state || 'unknown'} · {session.content?.type || 'content'}:{String(session.content?.value || '').slice(0, 80)}
            </span>
            <button className="tool-btn" aria-label={`restore ${session.device_id}`} onClick={() => restore(session.device_id)}>restore</button>
          </Row>
        ))}
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>USER · PRESENT</div>
        <form onSubmit={present} style={{ display: 'grid', gap: 6 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 6 }}>
            <select aria-label="content type" value={contentType} onChange={(ev) => { setContentType(ev.target.value); setContentValue(''); }} style={inpS}>
              {['url', 'local', 'catalog', 'query'].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <input aria-label="content reference" value={contentValue} onChange={(ev) => setContentValue(ev.target.value)} maxLength={contentLimit} placeholder="URL, local path, catalog id, or query" style={inpS} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 110px', gap: 6 }}>
            <select aria-label="target device" value={target} onChange={(ev) => {
              const nextTarget = ev.target.value;
              const nextDevice = devices.find((device) => device.id === nextTarget);
              const nextModes = nextDevice && Array.isArray(nextDevice.supports)
                ? nextDevice.supports.filter((value) => allMediaModes.includes(value)) : allMediaModes;
              setTarget(nextTarget);
              if (!nextModes.includes(mode)) setMode(nextModes[0] || '');
            }} style={inpS}>
              <option value="">choose device</option>
              {devices.map((device) => <option key={device.id} value={device.id}>{device.name || device.id}</option>)}
            </select>
            <select aria-label="mode" value={mode} onChange={(ev) => setMode(ev.target.value)} style={inpS}>
              {availableModes.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select aria-label="privacy" value={privacy} onChange={(ev) => setPrivacy(ev.target.value)} style={inpS}>
              {['ambient', 'household', 'private'].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr auto', gap: 6 }}>
            <select aria-label="urgency" value={urgency} onChange={(ev) => setUrgency(ev.target.value)} style={inpS}>
              {['low', 'normal', 'high'].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <input aria-label="duration seconds" type="number" min="1" max="86400" step="1" value={duration} onChange={(ev) => setDuration(ev.target.value)} placeholder="duration (optional)" style={inpS} />
            <button className="tool-btn" type="submit" disabled={!contentValue.trim() || !target || !availableModes.includes(mode)}>present</button>
          </div>
        </form>
        <MediaOutcome value={outcome} />
        <section aria-label="media admin controls">
          <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '12px 0 4px' }}>ADMIN · DEVICE REGISTRY</div>
          {devices.map((device, i) => (
            <Row key={`admin:${device.id || i}`}>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{device.id}</span>
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{device.name}</span>
              <button className="tool-btn" aria-label={`remove ${device.id}`} onClick={() => removeDevice(device.id)}>remove</button>
            </Row>
          ))}
          <form onSubmit={registerDevice} style={{ display: 'grid', gap: 6 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr 120px', gap: 6 }}>
              <input aria-label="admin device id" value={deviceId} onChange={(ev) => setDeviceId(ev.target.value)} maxLength={64} placeholder="device id" style={inpS} />
              <input aria-label="admin device name" value={deviceName} onChange={(ev) => setDeviceName(ev.target.value)} maxLength={120} placeholder="display name" style={inpS} />
              <select aria-label="admin device kind" value={deviceKind} onChange={(ev) => setDeviceKind(ev.target.value)} style={inpS}>
                {['chromecast', 'spotify_connect', 'browser_tab', 'local', 'speaker', 'tv'].map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6 }}>
              <input aria-label="admin device room" value={deviceRoom} onChange={(ev) => setDeviceRoom(ev.target.value)} maxLength={64} placeholder="room (optional)" style={inpS} />
              <input aria-label="admin device supports" value={deviceSupports} onChange={(ev) => setDeviceSupports(ev.target.value)} maxLength={128} placeholder="play,show,announce" style={inpS} />
              <button className="tool-btn" type="submit" disabled={!deviceId.trim() || !deviceName.trim()}>register device</button>
            </div>
          </form>
          {adminMessage && <div role="status" style={{ ...mono, color: 'var(--ink-3)', marginTop: 6 }}>{adminMessage}</div>}
        </section>
      </>}
    </Card>
  );
}

/* H30.5 — the House Brain surface is topology- and metadata-only. It never
   exposes raw occupant identities, camera frames, HA credentials, or a direct
   service-call seam. Every control below creates a governed proposal. */
export function HousePanel() {
  const house = useApi('/api/house/state');
  const data = house.d || {};
  const loaded = !!house.d;
  const enabled = loaded && !!data.enabled;
  const live = enabled && data.status === 'live';
  const rooms = arr(data, 'rooms').slice(0, 500);
  const devices = arr(data, 'devices').slice(0, 500);
  const presence = arr(data, 'presence').slice(0, 500);
  const lights = devices.filter((device) => device.domain === 'light');
  const climates = devices.filter((device) => device.domain === 'climate');
  const securityDevices = devices.filter((device) => ['lock', 'alarm_control_panel', 'cover'].includes(device.domain));
  const [lightTarget, setLightTarget] = useState('');
  const [lightState, setLightState] = useState('on');
  const [brightness, setBrightness] = useState('');
  const [climateTarget, setClimateTarget] = useState('');
  const [climateAction, setClimateAction] = useState('set_temperature');
  const [climateValue, setClimateValue] = useState('21');
  const [securityTarget, setSecurityTarget] = useState('');
  const [securityAction, setSecurityAction] = useState('lock');
  const [outcome, setOutcome] = useState(null);
  const [securityTaskId, setSecurityTaskId] = useState('');
  const [challenge, setChallenge] = useState(null);
  const [confirmationText, setConfirmationText] = useState('');
  const [confirmationMessage, setConfirmationMessage] = useState('');
  let hasAdmin = false;
  try { hasAdmin = !!localStorage.getItem('hud.admin_token'); } catch { /* unavailable */ }

  const selectedLight = lightTarget || lights[0]?.entity_id || '';
  const selectedClimate = climateTarget || climates[0]?.entity_id || '';
  const selectedSecurity = securityTarget || securityDevices[0]?.entity_id || '';
  const selectedSecurityDevice = securityDevices.find((device) => device.entity_id === selectedSecurity);
  const securityActions = selectedSecurityDevice?.domain === 'lock' ? ['lock', 'unlock']
    : selectedSecurityDevice?.domain === 'alarm_control_panel' ? ['arm_home', 'arm_away', 'disarm']
      : selectedSecurityDevice?.domain === 'cover' ? ['open', 'close'] : [];
  const effectiveSecurityAction = securityActions.includes(securityAction) ? securityAction : (securityActions[0] || '');

  const submit = (path, body) => {
    setOutcome({ status: 'sending' });
    apiPost(path, body)
      .then(setOutcome)
      .catch((err) => setOutcome({ status: 'denied', reason: err?.message || 'request_failed' }));
  };
  const proposeLight = (event) => {
    event.preventDefault();
    if (!selectedLight) return;
    const value = brightness.trim() ? Number(brightness) : null;
    submit('/api/house/control/light', {
      entity_id: selectedLight,
      state: lightState,
      ...(value == null ? {} : { brightness_pct: value }),
    });
  };
  const proposeClimate = (event) => {
    event.preventDefault();
    if (!selectedClimate) return;
    submit('/api/house/control/climate', {
      entity_id: selectedClimate,
      action: climateAction,
      value: climateAction === 'set_temperature' ? Number(climateValue) : climateValue.trim(),
    });
  };
  const proposeSecurity = (event) => {
    event.preventDefault();
    if (!selectedSecurity) return;
    submit('/api/house/control/security', {
      entity_id: selectedSecurity,
      action: effectiveSecurityAction,
    });
  };
  const mintChallenge = () => {
    const taskId = Number(securityTaskId);
    if (!Number.isSafeInteger(taskId) || taskId < 1) return;
    setChallenge(null);
    setConfirmationText('');
    setConfirmationMessage('');
    apiPost(`/api/house/security/${taskId}/challenge`, {}, { admin: true })
      .then(setChallenge)
      .catch((err) => setConfirmationMessage(err?.message || 'challenge refused'));
  };
  const confirmChallenge = () => {
    if (!challenge || confirmationText.trim() !== challenge.intended_state) return;
    apiPost(`/api/house/security/${challenge.task_id}/confirm`, {
      challenge_token: challenge.token,
    }, { admin: true })
      .then((result: any) => {
        setConfirmationMessage(result.status === 'confirmed' ? 'owner confirmation recorded' : (result.reason || 'confirmation refused'));
        setChallenge(null);
        setConfirmationText('');
      })
      .catch((err) => setConfirmationMessage(err?.message || 'confirmation refused'));
  };

  return (
    <Card
      title="HOUSE BRAIN"
      live={asLive(loaded, live)}
      sub={loaded ? `${data.status || 'unknown'} · ${rooms.length} rooms · ${devices.length} devices` : null}
      onReload={house.reload}
    >
      <State e={house.e} loading={house.loading} n={loaded && !enabled ? undefined : rooms.length + devices.length + presence.length} />
      {loaded && !enabled && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          House Brain is off · owner opt-in is required on the hub
        </div>
      )}
      {enabled && !live && (
        <div role="alert" style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          degraded · {data.reason || 'live Home Assistant state unavailable'} · controls paused
        </div>
      )}
      {enabled && <>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '4px 0' }}>ROOMS & DEVICES</div>
        {rooms.map((room) => (
          <Row key={room.room_id}>
            <span style={{ ...mono, color: 'var(--accent-light)' }}>{room.name || room.room_id}</span>
            <span style={{ marginLeft: 'auto' }}><Tag>{room.room_id}</Tag></span>
          </Row>
        ))}
        {devices.map((device) => (
          <Row key={device.entity_id}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{device.entity_id}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              {device.room_id && <Tag>{device.room_id}</Tag>}<Tag>{device.state || 'unknown'}</Tag>
            </span>
          </Row>
        ))}
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>PRESENCE · PSEUDONYMOUS</span>
          <Tag c={data.presence_status === 'live' ? 'var(--green)' : data.presence_status === 'degraded' ? 'var(--amber)' : undefined}>
            {data.presence_status || 'unknown'}
          </Tag>
        </div>
        {data.presence_status === 'off' && (
          <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>presence writer is off · owner opt-in via house.presence_enabled / JARVIS_HOUSE_PRESENCE</div>
        )}
        {data.presence_status === 'unavailable' && (
          <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>presence writer idle · live house state unavailable</div>
        )}
        {data.presence_status === 'degraded' && (
          <div role="alert" style={{ fontSize: 10, color: 'var(--amber)' }}>presence write failed · list may be stale</div>
        )}
        {data.presence_status === 'live' && presence.length === 0 && (
          <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>no occupants detected</div>
        )}
        {presence.map((item) => (
          <Row key={item.occupant_id}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>…{String(item.occupant_id || '').slice(-8)}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              <Tag>{item.status || 'unknown'}</Tag>
              {item.room_id && <Tag>{item.room_id}</Tag>}
              <Tag>{item.privacy || 'household'}</Tag>
            </span>
          </Row>
        ))}
      </>}
      {live && <>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '12px 0 4px' }}>GOVERNED CONTROLS · PROPOSALS</div>
        {lights.length > 0 && <form onSubmit={proposeLight} style={{ display: 'grid', gridTemplateColumns: '1fr 80px 100px auto', gap: 6, marginBottom: 6 }}>
          <select aria-label="light target" value={selectedLight} onChange={(event) => setLightTarget(event.target.value)} style={inpS}>
            {lights.map((device) => <option key={device.entity_id} value={device.entity_id}>{device.entity_id}</option>)}
          </select>
          <select aria-label="light state" value={lightState} onChange={(event) => setLightState(event.target.value)} style={inpS}>
            <option value="on">on</option><option value="off">off</option>
          </select>
          <input aria-label="light brightness" type="number" min="1" max="100" value={brightness} onChange={(event) => setBrightness(event.target.value)} placeholder="brightness" style={inpS} />
          <button className="tool-btn" type="submit" aria-label="Propose light control">propose</button>
        </form>}
        {climates.length > 0 && <form onSubmit={proposeClimate} style={{ display: 'grid', gridTemplateColumns: '1fr 130px 100px auto', gap: 6, marginBottom: 6 }}>
          <select aria-label="climate target" value={selectedClimate} onChange={(event) => setClimateTarget(event.target.value)} style={inpS}>
            {climates.map((device) => <option key={device.entity_id} value={device.entity_id}>{device.entity_id}</option>)}
          </select>
          <select aria-label="climate action" value={climateAction} onChange={(event) => setClimateAction(event.target.value)} style={inpS}>
            <option value="set_temperature">temperature</option><option value="set_mode">mode</option>
          </select>
          <input aria-label="climate value" value={climateValue} onChange={(event) => setClimateValue(event.target.value)} maxLength={16} style={inpS} />
          <button className="tool-btn" type="submit" aria-label="Propose climate control">propose</button>
        </form>}
        {securityDevices.length > 0 && <form onSubmit={proposeSecurity} style={{ display: 'grid', gridTemplateColumns: '1fr 120px auto', gap: 6 }}>
          <select aria-label="security target" value={selectedSecurity} onChange={(event) => setSecurityTarget(event.target.value)} style={inpS}>
            {securityDevices.map((device) => <option key={device.entity_id} value={device.entity_id}>{device.entity_id}</option>)}
          </select>
          <select aria-label="security action" value={effectiveSecurityAction} onChange={(event) => setSecurityAction(event.target.value)} style={inpS}>
            {securityActions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <button className="tool-btn" type="submit" aria-label="Propose security control">propose · strong confirm</button>
        </form>}
        <HouseOutcome value={outcome} />
        {hasAdmin && <section aria-label="owner security confirmation">
          <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '12px 0 4px' }}>ADMIN · STRONG CONFIRMATION</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6 }}>
            <input aria-label="security task id" type="number" min="1" value={securityTaskId} onChange={(event) => setSecurityTaskId(event.target.value)} placeholder="durable task id" style={inpS} />
            <button className="tool-btn" type="button" onClick={mintChallenge} aria-label="Mint owner challenge">mint owner challenge</button>
          </div>
          {challenge && <div style={{ marginTop: 8 }}>
            <div style={{ ...mono, color: 'var(--amber)' }}>{challenge.target} → {challenge.intended_state}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, marginTop: 6 }}>
              <input aria-label="type intended state" value={confirmationText} onChange={(event) => setConfirmationText(event.target.value)} maxLength={128} placeholder={`type ${challenge.intended_state}`} style={inpS} />
              <button className="tool-btn" type="button" disabled={confirmationText.trim() !== challenge.intended_state} onClick={confirmChallenge} aria-label="Confirm exact security action">confirm exact security action</button>
            </div>
          </div>}
          {confirmationMessage && <div role="status" style={{ ...mono, color: 'var(--amber)', marginTop: 6 }}>{confirmationMessage}</div>}
        </section>}
      </>}
    </Card>
  );
}

/* H33.6 — owner transparency over the real ambient runtime. The endpoint is a
   deliberately redacted projection: no predicates, subjects, event ids, raw
   attributes, recipients, or delivery ids are rendered here. */
export function AmbientWatchPanel() {
  const ambient = useApi('/api/ambient/monitors');
  const data = ambient.d || {};
  const loaded = !!ambient.d;
  const enabled = loaded && !!data.enabled;
  const live = enabled && data.status === 'live';
  const monitors = arr(data, 'monitors').slice(0, 200);
  const sources = arr(data, 'sources').slice(0, 3);
  const attention = data.attention || {};
  const rungCounts = data.rung_counts || {};
  const last = data.last_decision || null;

  return (
    <Card
      title="AMBIENT WATCH"
      live={asLive(loaded, live)}
      sub={loaded ? `${data.status || 'unknown'} · ${monitors.length} monitors` : null}
      onReload={ambient.reload}
    >
      <State e={ambient.e} loading={ambient.loading} n={loaded && !enabled ? undefined : monitors.length} />
      {loaded && !enabled && (
        <div style={{ fontSize: 10, color: data.status === 'degraded' ? 'var(--amber)' : 'var(--ink-3)', marginTop: 6 }}>
          {data.status === 'degraded' ? 'Ambient runtime degraded' : 'Ambient intelligence is off'} · {data.reason || 'owner opt-in required'}
        </div>
      )}
      {enabled && <>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '4px 0 8px' }}>
          REDACTED TRANSPARENCY · subjects and event content stay private
        </div>
        <Row>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>GLOBAL ATTENTION</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
            <Tag c={attention.status === 'ready' ? 'var(--green)' : 'var(--amber)'}>{attention.status || 'degraded'}</Tag>
            <Tag>{Number(attention.remaining || 0)} / {Number(attention.limit || 0)} left</Tag>
          </span>
        </Row>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, margin: '8px 0' }}>
          {['ignore', 'remember', 'monitor', 'act_silently', 'ask', 'interrupt'].map((rung) => (
            <Tag key={rung}>{rung} · {Number(rungCounts[rung] || 0)}</Tag>
          ))}
        </div>
        {sources.map((source) => (
          <Row key={source.source}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{source.source}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              <Tag c={source.status === 'live' ? 'var(--green)' : 'var(--amber)'}>{source.status || 'waiting'}</Tag>
              {Number(source.queued || 0) > 0 && <Tag>{source.queued} queued</Tag>}
            </span>
          </Row>
        ))}
        {monitors.map((monitor) => {
          const decision = monitor.last_decision || null;
          return (
            <Row key={monitor.monitor_id}>
              <div style={{ minWidth: 0 }}>
                <div style={{ ...mono, color: 'var(--accent-light)' }}>{monitor.monitor_id}</div>
                <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 3 }}>
                  {monitor.source} · {monitor.schema} · v{monitor.version} · {monitor.state || 'waiting'}
                </div>
                {decision && <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 4 }}>
                  last · {decision.transition} → {decision.rung} · {String(decision.policy_reason || '').split('_').join(' ')}
                </div>}
              </div>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
                <Tag>{monitor.alert_rung}</Tag>
                {!monitor.enabled && <Tag c="var(--amber)">paused</Tag>}
              </span>
            </Row>
          );
        })}
        {!monitors.length && <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>No owner-defined monitors yet.</div>}
        {last && <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 9, marginTop: 8 }}>
          LAST DECISION · {last.monitor_id} · {last.rung} · {last.attention_mode}
        </div>}
      </>}
    </Card>
  );
}

/* H31.5 — camera intelligence is a metadata-only household sensor surface.
   It never renders or fetches a frame, snapshot, clip, stream, or private URL. */
export function CameraPanel() {
  const status = useApi('/api/cameras/status');
  const recent = useApi('/api/cameras/events');
  const data = status.d || {};
  const loaded = !!status.d;
  const enabled = loaded && !!data.enabled;
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState(null);
  const [searchError, setSearchError] = useState('');
  const [searching, setSearching] = useState(false);
  const [discovery, setDiscovery] = useState(null);
  const [discoveryError, setDiscoveryError] = useState('');
  let hasAdmin = false;
  try { hasAdmin = !!localStorage.getItem('hud.admin_token'); } catch { /* unavailable */ }

  const source = searchResult || recent.d || {};
  const events = arr(source, 'events').slice(0, 100);
  const search = (event) => {
    event.preventDefault();
    const text = query.trim();
    if (!text) return;
    setSearching(true);
    setSearchError('');
    apiPost('/api/cameras/search', { query: text, limit: 100 })
      .then(setSearchResult)
      .catch((err) => setSearchError(err?.message || 'camera search failed'))
      .finally(() => setSearching(false));
  };
  const discover = () => {
    setDiscovery(null);
    setDiscoveryError('');
    apiPost('/api/cameras/onvif/discover', {}, { admin: true })
      .then(setDiscovery)
      .catch((err) => setDiscoveryError(err?.message || 'ONVIF discovery failed'));
  };
  const reload = () => {
    status.reload();
    recent.reload();
    setSearchResult(null);
  };

  return (
    <Card
      title="CAMERA INTELLIGENCE"
      live={asLive(loaded, enabled && data.status === 'healthy')}
      sub={loaded ? `${data.status || 'unknown'} · ${events.length} events` : null}
      onReload={reload}
    >
      <State e={status.e || recent.e} loading={status.loading || recent.loading} n={loaded && !enabled ? undefined : events.length} />
      {loaded && !enabled && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          Camera Intelligence is off · {data.reason || 'owner opt-in and household consent are required'}
        </div>
      )}
      {enabled && <>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '4px 0' }}>
          METADATA ONLY · {data.source?.status || 'source unavailable'} · {Number(data.source?.camera_count || 0)} cameras
        </div>
        <form onSubmit={search} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, marginBottom: 8 }}>
          <input
            aria-label="camera search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={256}
            placeholder="courier yesterday · package last 2 hours"
            style={inpS}
          />
          <button className="tool-btn" type="submit" disabled={!query.trim() || searching} aria-label="Search camera events">
            {searching ? 'searching…' : 'search'}
          </button>
        </form>
        {searchError && <div role="alert" style={{ ...mono, color: 'var(--danger)' }}>{searchError}</div>}
        {searchResult && events.length === 0 && (
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginBottom: 6 }}>No matching camera events.</div>
        )}
        {events.map((item) => {
          const occurred = Number(item.occurred_at);
          const when = Number.isFinite(occurred) ? new Date(occurred * 1000).toLocaleString() : 'unknown time';
          const confidence = Math.round(Math.max(0, Math.min(1, Number(item.confidence) || 0)) * 100);
          return (
            <Row key={`${item.camera_id}:${item.event_id}`}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
                  <span style={{ ...mono, color: 'var(--accent-light)' }}>{item.camera_id}</span>
                  <Tag>{item.label}</Tag>
                  {item.zone && <Tag>{item.zone}</Tag>}
                  {item.room_id && <Tag>{item.room_id}</Tag>}
                  <Tag>{confidence}%</Tag>
                </div>
                <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 3 }}>{when}</div>
                {item.description && <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{item.description}</div>}
                {item.description_provenance && (
                  <div style={{ ...mono, fontSize: 9, color: 'var(--ink-3)', marginTop: 2 }}>
                    {String(item.description_provenance).split('_').join(' ')}
                  </div>
                )}
              </div>
            </Row>
          );
        })}
        {hasAdmin && <section aria-label="admin ONVIF discovery" style={{ marginTop: 10 }}>
          <button className="tool-btn" type="button" onClick={discover} aria-label="Discover ONVIF cameras">discover ONVIF cameras</button>
          {discoveryError && <div role="alert" style={{ ...mono, color: 'var(--danger)', marginTop: 5 }}>{discoveryError}</div>}
          {/* Refusals arrive as HTTP-200 bodies (dependency missing, disabled, timeout) — they
              land here through setDiscovery, never through discoveryError, so an empty device
              list must say why instead of leaving the button looking dead. */}
          {discovery && arr(discovery, 'devices').length === 0 && (
            discovery.status === 'unavailable' || discovery.status === 'disabled' || discovery.enabled === false ? (
              <div role="alert" style={{ ...mono, fontSize: 10, color: 'var(--danger)', marginTop: 5 }}>
                {discovery.status || 'unavailable'} · {discovery.reason || 'discovery refused'}
                {discovery.detail && <div style={{ color: 'var(--ink-2)', marginTop: 2 }}>{discovery.detail}</div>}
              </div>
            ) : discovery.status === 'degraded' ? (
              <div role="alert" style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginTop: 5 }}>
                degraded · {discovery.reason || 'discovery_failed'}
              </div>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 5 }}>no ONVIF devices found</div>
            )
          )}
          {arr(discovery, 'devices').slice(0, 64).map((device) => (
            <Row key={device.device_id}>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{device.name}</span>
              <span style={{ marginLeft: 'auto' }}><Tag>{device.host}:{device.port}</Tag>{device.mapped && <Tag>mapped</Tag>}</span>
            </Row>
          ))}
        </section>}
      </>}
    </Card>
  );
}

/* H32.6 — owner-visible acquisition lifecycle and hash-only audit projection.
   Raw goals, research extracts, package paths, and receipt bodies never reach the HUD. */
export function AcquisitionPanel() {
  let hasAdmin = false;
  try { hasAdmin = !!localStorage.getItem('hud.admin_token'); } catch { /* unavailable */ }
  const status = useApi('/api/acquisition/status');
  const audit = useApi('/api/acquisition/events?limit=100');
  // The drive control below needs a real request_id, and this list is the ONLY place
  // the product ever hands one out — the ledger exposes hashes, the status snapshot
  // per-state counts. So it is read unconditionally (with the admin header when a token
  // is stored): admin routes are localhost-exempt, and gating the read on a locally
  // stored token hid the whole control on the default posture where it works. On a
  // token-configured install without the token the read simply degrades to a visible
  // "offline · GET … -> 401", like every sibling admin panel.
  const requests = useApi('/api/acquisition/requests', true, true);
  const data = status.d || {};
  const loaded = !!status.d;
  const enabled = loaded && !!data.enabled;
  const packages = arr(data, 'packages').slice(0, 256);
  const events = arr(audit.d, 'events').slice(0, 100);
  const states = data.states || {};
  const reuse = data.reuse || {};
  const reuseRate = Math.round(Math.max(0, Math.min(1, Number(reuse.reuse_rate) || 0)) * 100);
  const [outcome, setOutcome] = useState('');
  const [purgeConfirmation, setPurgeConfirmation] = useState('');
  const [entrypoint, setEntrypoint] = useState('run');
  const [cases, setCases] = useState('[{"input": {}, "expected": null}]');
  const gaps = arr(requests.d, 'requests').slice(0, 50);

  const reload = () => { status.reload(); audit.reload(); };
  const lifecycle = (name, action) => {
    setOutcome('sending…');
    apiPost(`/api/acquisition/${encodeURIComponent(name)}/${action}`, {}, { admin: true })
      .then((result: any) => {
        setOutcome(`${result.status || action} · ${result.name || name}`);
        reload();
      })
      .catch((error) => setOutcome(`refused · ${error?.message || `${action}_failed`}`));
  };
  const exportLedger = () => {
    setOutcome('exporting…');
    apiGet('/api/acquisition/ledger/export', { admin: true })
      .then((result: any) => setOutcome(`export ready · ${Number(result.summary?.count || 0)} summarized events`))
      .catch((error) => setOutcome(`refused · ${error?.message || 'export_failed'}`));
  };
  const purgeLedger = () => {
    if (purgeConfirmation !== 'PURGE ACQUISITION DETAIL') return;
    apiPost('/api/acquisition/ledger/purge', { confirm: purgeConfirmation }, { admin: true })
      .then((result: any) => {
        setOutcome(`purged · ${Number(result.purged || 0)} detailed events`);
        setPurgeConfirmation('');
        reload();
      })
      .catch((error) => setOutcome(`refused · ${error?.message || 'purge_failed'}`));
  };
  // The goal stays system-owned (it comes from the captured request); only the
  // entrypoint and the contract cases are caller-supplied, exactly as the route
  // accepts them. Every missing precondition comes back as an explicit 409.
  const drive = (requestId) => {
    let parsed;
    try { parsed = JSON.parse(cases); } catch { setOutcome('refused · cases must be valid JSON'); return; }
    if (!Array.isArray(parsed) || parsed.length < 1 || parsed.length > 16) {
      setOutcome('refused · 1–16 contract cases required');
      return;
    }
    setOutcome('driving…');
    apiPost(`/api/acquisition/${encodeURIComponent(requestId)}/drive`, { entrypoint, cases: parsed }, { admin: true })
      .then((result: any) => {
        setOutcome(`${result.status || 'driven'} · ${result.name || result.reason || requestId.slice(0, 8)}`);
        reload();
        requests.reload();
      })
      // The route answers with its OWN reason (reuse_available, acquisition_disabled,
      // promotion_unavailable, local_llm_required, searxng_backend_required,
      // synthesis_failed, …). Print that verbatim — naming one fixed precondition list
      // for every refusal told the operator a cause the server never gave.
      .catch((error) => {
        const body = error?.body || {};
        const reason = body.reason || error?.message || 'drive_failed';
        const needs = arr(body._degraded?.needs);
        setOutcome(`refused · ${error?.status ? `${error.status} · ` : ''}${reason}${needs.length ? ` · needs ${needs.join(', ')}` : ''}`);
      });
  };

  return (
    <Card
      title="CAPABILITY ACQUISITION"
      live={asLive(loaded, enabled && data.status === 'ready')}
      sub={loaded ? `${data.status || 'unknown'} · reuse ${reuseRate}%` : null}
      onReload={reload}
    >
      <State e={status.e || audit.e} loading={status.loading || audit.loading} n={loaded && !enabled ? undefined : packages.length + events.length} />
      {loaded && !enabled && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          Capability Acquisition is off · {data.reason || 'owner enablement is required'}
        </div>
      )}
      {enabled && <>
        {data.status !== 'ready' && (
          <div role="alert" style={{ ...mono, color: 'var(--amber)', marginBottom: 7 }}>
            {data.status} · {data.reason || 'acquisition is not ready'}
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
          {Object.entries(states).map(([name, count]) => <Tag key={name}>{name} · {Number(count)}</Tag>)}
          <Tag>reused · {Number(reuse.reused || 0)}</Tag>
          <Tag>generated · {Number(reuse.generated || 0)}</Tag>
          <Tag c={data.audit?.chain_valid ? 'var(--green)' : 'var(--red)'}>
            {data.audit?.chain_valid ? 'chain verified' : 'chain degraded'}
          </Tag>
        </div>
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '4px 0' }}>SIGNED · SANDBOX-ONLY PACKAGES</div>
        {packages.map((item) => (
          <Row key={item.name}>
            <span style={{ ...mono, color: 'var(--accent-light)' }}>{item.name}</span>
            <span style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginLeft: 'auto', alignItems: 'center' }}>
              <Tag>{item.version}</Tag><Tag>{item.status}</Tag><Tag>{Math.round(Number(item.confidence || 0) * 100)}% evidence</Tag>
              {hasAdmin && <>
                <button className="tool-btn" type="button" onClick={() => lifecycle(item.name, 'revoke')} aria-label={`Revoke ${item.name}`}>revoke</button>
                <button className="tool-btn" type="button" onClick={() => lifecycle(item.name, 'rollback')} aria-label={`Rollback ${item.name}`}>rollback</button>
              </>}
            </span>
          </Row>
        ))}
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>HASH-ONLY AUDIT · LATEST</div>
        {events.map((item) => (
          <Row key={`${item.sequence}:${item.event_hash || item.event_type}`}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>#{Number(item.sequence || 0)} · {item.event_type}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}><Tag>{item.status || 'recorded'}</Tag><Tag>{item.actor || 'system'}</Tag></span>
          </Row>
        ))}
        <section aria-label="admin acquisition lifecycle" style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            <button className="tool-btn" type="button" onClick={exportLedger} aria-label="Export acquisition ledger">export ledger</button>
          </div>
          <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>OPEN CAPABILITY GAPS</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 6, marginBottom: 6 }}>
            <input
              aria-label="acquisition drive entrypoint"
              value={entrypoint}
              onChange={(event) => setEntrypoint(event.target.value)}
              maxLength={64}
              placeholder="entrypoint"
              style={inpS}
            />
            <textarea
              aria-label="acquisition drive contract cases"
              value={cases}
              onChange={(event) => setCases(event.target.value)}
              style={{ ...taS, minHeight: 50 }}
            />
          </div>
          {requests.e
            ? <div role="alert" style={{ ...mono, color: 'var(--red)', fontSize: 10 }}>offline · {requests.e}</div>
            : gaps.length === 0
            ? <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10 }}>no open capability gaps</div>
            : gaps.map((item) => (
              <Row key={item.request_id}>
                <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(item.request_id || '').slice(0, 8)}</span>
                <span style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginLeft: 'auto', alignItems: 'center' }}>
                  <Tag>{item.status}</Tag><Tag>{item.agent_id}</Tag><Tag>{item.reason}</Tag><Tag>×{Number(item.occurrences || 1)}</Tag>
                  <button
                    className="tool-btn"
                    type="button"
                    aria-label={`Drive ${item.request_id}`}
                    onClick={() => drive(item.request_id)}
                  >drive</button>
                </span>
              </Row>
            ))}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, marginTop: 10 }}>
            <input
              aria-label="acquisition purge confirmation"
              value={purgeConfirmation}
              onChange={(event) => setPurgeConfirmation(event.target.value)}
              maxLength={64}
              placeholder="type PURGE ACQUISITION DETAIL"
              style={inpS}
            />
            <button
              className="tool-btn"
              type="button"
              disabled={purgeConfirmation !== 'PURGE ACQUISITION DETAIL'}
              onClick={purgeLedger}
              aria-label="Purge acquisition detail"
            >purge detail</button>
          </div>
        </section>
        {outcome && <div role="status" style={{ ...mono, color: outcome.startsWith('refused') ? 'var(--red)' : 'var(--amber)', marginTop: 7 }}>{outcome}</div>}
      </>}
    </Card>
  );
}

/* 0.37 — the ingestion-provenance read surface (GET /api/ingestion/provenance, admin).
   Renders recent provenance records + by-source stats. Honesty contract: when
   JARVIS_PROVENANCE is off the endpoint reports enabled:false and the panel says so
   (records carry conversation ids, so nothing is recorded by default). */
export function ProvenancePanel() {
  const { d, e, loading, reload } = useApi('/api/ingestion/provenance', true, true);
  const enabled = !!(d && d.enabled);
  const records = arr(d && d.records);
  const bySource = (d && d.stats && d.stats.by_source) || {};
  return (
    <Card title="PROVENANCE" live={d ? (enabled ? 'live' : 'seed') : undefined} sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} recs · ${(d.stats && d.stats.runs) || 0} runs` : 'disabled') : null} onReload={reload}>
      <State e={e} loading={loading} n={records.length} />
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_PROVENANCE is on</div>}
      {enabled && Object.keys(bySource).length > 0 && (
        <Row>
          <span style={mono}>sources</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {Object.entries(bySource).map(([s, n]) => <Tag key={s}>{String(n)} {s}</Tag>)}
          </span>
        </Row>
      )}
      {records.slice(0, 8).map((r, i) => (
        <Row key={r.id || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{r.source}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{r.phase} · {(r.content_hash || '').slice(0, 8)}</span>
        </Row>
      ))}
    </Card>
  );
}

/* 0.44 — the per-channel OUTBOUND send rate-limiter status (GET /api/channels/send-rate-limit,
   admin). Renders configured caps + current in-window usage. Honesty contract: when no cap is
   set (the default) the endpoint reports enabled:false and the panel says so (sends are
   unlimited and nothing is recorded until an operator opts in). Sibling of the egress monitor. */
export function CommsRatePanel() {
  const { d, e, loading, reload } = useApi('/api/channels/send-rate-limit', true, true);
  const enabled = !!(d && d.enabled);
  const channels = arr(d && d.channels);
  return (
    <Card title="SEND RATE LIMITS" live={d ? (enabled ? 'live' : 'seed') : undefined} sub={d ? (enabled ? `cap ${(d && d.global_cap) || 0}/${(d && d.window_seconds) || 60}s` : 'unlimited') : null} onReload={reload}>
      <State e={e} loading={loading} n={channels.length} />
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>unlimited until JARVIS_CHANNEL_SEND_RATE(S) is set</div>}
      {channels.slice(0, 10).map((c, i) => (
        <Row key={c.channel || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{c.channel}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{c.used}/{c.cap > 0 ? c.cap : '∞'}</span>
        </Row>
      ))}
    </Card>
  );
}

/* 0.44 — draft-before-send UI for governed social writes. This is deliberately
   a queue/preview surface over /api/integrations/social; actual per-channel inbox
   reply transport remains a separate plugin/channel bridge. */
export function SafeCommsDraftPanel() {
  const { d, e, loading, reload } = useApi('/api/integrations/social');
  const targets = arr(d, 'targets');
  const [choice, setChoice] = useState('');
  const [text, setText] = useState('');
  const [dest, setDest] = useState('');
  const [agent, setAgent] = useState('pepper');
  const [out, setOut] = useState(null);
  const selectedKey = choice || (targets[0] ? `${targets[0].platform}:${targets[0].action}` : '');
  const selected = targets.find((t) => `${t.platform}:${t.action}` === selectedKey) || targets[0];
  const queue = () => {
    if (!selected || !text.trim()) return;
    const fields: Record<string, any> = { text: text.trim() };
    if (selected.required?.includes?.('reply_to')) fields.reply_to = dest.trim();
    if (selected.required?.includes?.('recipient')) fields.recipient = dest.trim();
    apiPost('/api/integrations/social', {
      platform: selected.platform,
      action: selected.action,
      fields,
      agent: agent.trim() || 'pepper',
      source: 'hud.safe_comms_draft',
    }).then((r: any) => {
      setOut(r);
      if (r && r.ok !== false) { setText(''); setDest(''); }
      reload();
    }).catch((err) => setOut({ ok: false, reason: err?.message || 'request failed' }));
  };
  const note = out
    ? out.ok === false
      ? `held: ${out.reason || 'validation failed'}`
      : out.task_id
        ? `queued for approval · ${out.task_id}`
        : (out.status || 'preview ready')
    : null;
  return (
    <Card title="SAFE COMMS DRAFTS" live={asLive(d)} sub={d ? `${targets.length} actions` : null} onReload={reload}>
      <State e={e} loading={loading} n={targets.length} />
      {targets.slice(0, 6).map((t, i) => (
        <Row key={t.kind || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{t.label || `${t.platform}.${t.action}`}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag>{t.kind || `${t.platform}.${t.action}`}</Tag>
            {t.credential && <Tag c="var(--ink-3)">{t.credential}</Tag>}
          </span>
        </Row>
      ))}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(120px,1fr) minmax(100px,1fr) minmax(70px,.6fr)', gap: 6, marginTop: 8 }}>
        <select aria-label="social action" value={selectedKey} onChange={(ev) => setChoice(ev.target.value)} style={inpS}>
          {targets.map((t) => <option key={t.kind || `${t.platform}:${t.action}`} value={`${t.platform}:${t.action}`}>{t.label || `${t.platform}.${t.action}`}</option>)}
        </select>
        <input value={dest} onChange={(ev) => setDest(ev.target.value)} placeholder="reply_to / recipient" style={inpS} />
        <input value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder="agent" style={inpS} />
      </div>
      <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="draft text" style={{ ...taS, marginTop: 6, minHeight: 58 }} />
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
        <button className="tool-btn" disabled={!selected || !text.trim()} onClick={queue}>queue draft</button>
        <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>approval queue · no direct send</span>
      </div>
      {note && <div style={{ ...mono, fontSize: 10.5, color: out?.ok === false ? 'var(--amber)' : 'var(--green)', marginTop: 6 }}>{note}</div>}
    </Card>
  );
}

/* H23.2 — recorded model fingerprints (GET /api/models/info, admin): the {id, version,
   quant, sha256} of each model build seen, so a run is reproducible to the exact model.
   Honesty contract: when JARVIS_MODEL_INFO is off the endpoint reports enabled:false and
   the panel says so (nothing is recorded by default). */
export function ModelInfoPanel() {
  const { d, e, loading, reload } = useApi('/api/models/info', true, true);
  const enabled = !!(d && d.enabled);
  const models = arr(d && d.models);
  return (
    <Card title="MODEL FINGERPRINTS" live={asLive(d, enabled)} sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} models` : 'disabled') : null} onReload={reload}>
      <State e={e} loading={loading} n={models.length} />
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_MODEL_INFO is on</div>}
      {models.slice(0, 10).map((m, i) => (
        <Row key={m.id || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{m.id}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{[m.quant, (m.sha256 || '').slice(0, 8)].filter(Boolean).join(' · ')}</span>
        </Row>
      ))}
    </Card>
  );
}

/* T-0.53 — the design-system manifest (GET /api/design-manifest, open like the
   sibling meters): tokens + component-class inventory parsed live from
   frontend/src/styles.css, so drift is visible instead of only inspectable by
   reading the stylesheet. Figma token sync stays a separate owner-gated
   follow-up (needs a Figma API token) — this panel is the read side. */
export function DesignManifestPanel() {
  const { d, e, loading, reload } = useApi('/api/design-manifest');
  const ok = !!(d && !d.error);
  const counts = (ok && d.counts) || {};
  const variants = ok ? Object.keys((d.tokens && d.tokens.variants) || {}) : [];
  return (
    <Card title="DESIGN MANIFEST" live={asLive(d, ok)} sub={ok ? `${counts.base_tokens || 0} tokens · ${counts.components || 0} components` : null} onReload={reload}>
      <State e={e || (d && d.error) || null} loading={loading} n={ok ? 1 : 0} />
      {ok && (
        <>
          <Row>
            <span style={mono}>source</span>
            <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{d.source}</span>
          </Row>
          <Row>
            <span style={mono}>variants</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {variants.length ? variants.map((v) => <Tag key={v}>{v}</Tag>) : <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>none</span>}
            </span>
          </Row>
        </>
      )}
    </Card>
  );
}

/* T-0.50 — publish readiness for a finished asset (POST /api/creative/publish/*,
   user-guarded). This surface NEVER publishes: it shows the automatic checks and
   the manual confirmations an owner must tick, and the release payload stays
   withheld until all of them pass. The terminal upload is owner-gated
   (per-platform OAuth) and stays approval-held — the panel says so. */
export function PublishReadinessPanel() {
  const [platform, setPlatform] = useState('youtube');
  const [meta, setMeta] = useState('{\n  "title": "",\n  "description": "",\n  "thumbnail": ""\n}');
  const [confirm, setConfirm] = useState({ disclosure: false, rights: false, preview: false });
  const [out, setOut] = useState(null);
  const run = (path) => {
    let parsed = null;
    try { parsed = JSON.parse(meta); } catch { setOut({ error: 'metadata is not valid JSON' }); return; }
    act(path, { platform, meta: parsed, confirmations: confirm }, setOut);
  };
  const toggle = (k) => setConfirm((c) => ({ ...c, [k]: !c[k] }));
  const checks = arr(out, 'checklist');
  return (
    <Card title="PUBLISH READINESS" live={'live'}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
        {['youtube', 'instagram', 'readme'].map((p) => (
          <button key={p} className="tool-btn" style={{ opacity: platform === p ? 1 : 0.5 }} onClick={() => setPlatform(p)}>{p}</button>
        ))}
      </div>
      <textarea value={meta} onChange={(ev) => setMeta(ev.target.value)} placeholder="metadata JSON" style={{ ...taS, minHeight: 70 }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
        {['disclosure', 'rights', 'preview'].map((k) => (
          <label key={k} style={{ ...mono, fontSize: 10.5, display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={confirm[k]} onChange={() => toggle(k)} />{k}
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button className="tool-btn" onClick={() => run('/api/creative/publish/checklist')}>check</button>
        <button className="tool-btn" onClick={() => run('/api/creative/publish/package')}>package</button>
      </div>
      {out && out.error && <div style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 6 }}>{out.error}</div>}
      {checks.map((c, i) => (
        <Row key={i}>
          <span style={mono}>{c.id}</span>
          <span style={{ marginLeft: 'auto', color: c.ok ? 'var(--green)' : 'var(--amber)' }}>{c.ok ? 'ok' : 'pending'}</span>
        </Row>
      ))}
      {out && arr(out, 'violations').length > 0 && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>{arr(out, 'violations').join(' · ')}</div>
      )}
      {out && out.ready_for_approval != null && (
        <div style={{ fontSize: 10.5, marginTop: 6, color: out.ready_for_approval ? 'var(--green)' : 'var(--ink-3)' }}>
          {out.ready_for_approval
            ? 'ready to REQUEST approval — still not published'
            : 'not ready · release payload withheld'}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>never uploads · publishing stays approval-held (owner-gated OAuth)</div>
    </Card>
  );
}

/* T-0.58 — the typed Pack Manager inventory (GET /api/packs, user-guarded).
   Unifies skill packs (marketplace) and knowledge packs (manifested drop
   folders) under one view, and shows unsupported types honestly rather than
   hiding them — `model` reads as unsupported with its reason, not as absent. */
export function PacksPanel() {
  const { d, e, loading, reload } = useApi('/api/packs');
  const packs = arr(d, 'packs');
  const types = arr(d, 'types');
  const counts = (d && d.counts) || {};
  const unmanifested = arr(d, 'unmanifested');
  const [check, setCheck] = useState(null);
  const verify = (key) => {
    setCheck({ key, loading: true });
    apiGet('/api/packs/' + encodeURIComponent(key) + '/verify')
      .then((r: any) => setCheck({ key, loading: false, ok: !!(r && r.ok), reason: r && r.reason, v: (r && r.verify) || {} }))
      .catch(() => setCheck({ key, loading: false, ok: false, reason: 'request failed' }));
  };
  return (
    <Card title="PACKS" live={asLive(d, d && d.available)} sub={d ? `${counts.total || 0} packs` : null} onReload={reload}>
      <State e={e} loading={loading} n={packs.length} />
      <Row>
        <span style={mono}>types</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {types.map((t) => (
            <Tag key={t.type} c={t.supported ? 'var(--accent-light)' : undefined}>
              {t.type}{t.supported ? '' : ' · n/a'}
            </Tag>
          ))}
        </span>
      </Row>
      {types.filter((t) => !t.supported && t.reason).map((t) => (
        <div key={t.type} style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>{t.type}: {t.reason}</div>
      ))}
      {packs.slice(0, 12).map((p, i) => (
        <Row key={i}>
          <Tag>{p.pack_type}</Tag>
          <span style={{ color: 'var(--accent-light)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
          {p.version && <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>v{p.version}</span>}
          {p.pack_type === 'knowledge' && <button className="tool-btn" onClick={() => verify(p.key)}>verify</button>}
        </Row>
      ))}
      {check && (
        <div style={{ fontSize: 10, marginTop: 6, color: check.loading ? 'var(--ink-3)' : check.ok ? 'var(--green)' : 'var(--amber)' }}>
          {check.loading ? `verifying ${check.key}…`
            : check.ok ? `${check.key}: intact (${check.v.checked} file(s) checked)`
            : `${check.key}: ${check.reason || 'discrepancies'} — ${[
                (check.v?.missing || []).length + ' missing',
                (check.v?.modified || []).length + ' modified',
                (check.v?.unexpected || []).length + ' unexpected',
              ].join(' · ')}`}
        </div>
      )}
      {unmanifested.length > 0 && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          {unmanifested.length} configured folder(s) without a manifest — drop-folders, not packs
        </div>
      )}
    </Card>
  );
}

/* T-0.41 — the live World Signal feed routed per domain/agent
   (GET /api/signals/routed, user-guarded). The routing layer classifies the
   sidecar's signals into domains and slices them per subscribing agent; an
   unclassifiable signal stays visible in `unrouted` rather than being
   force-labeled. Honest when no sidecar is configured — says so, shows nothing. */
export function SignalRoutingPanel() {
  const { d, e, loading, reload } = useApi('/api/signals/routed');
  const available = !!(d && d.available);
  const counts = (d && d.counts) || {};
  const byDomain = (available && d.by_domain) || {};
  const byAgent = (available && d.by_agent) || {};
  const signals = arr(d, 'signals');
  // Clicking an agent chip pulls that agent's OWN slice from the dedicated
  // endpoint (the same one an agent's digest consumes), rather than filtering
  // client-side — so the per-agent route has a real caller and the slice shown
  // is exactly what the agent would receive.
  const [slice, setSlice] = useState(null);
  const showAgent = (ag) => {
    setSlice({ agent: ag, loading: true, signals: [] });
    apiGet('/api/signals/agent/' + encodeURIComponent(ag))
      .then((r: any) => setSlice({ agent: ag, loading: false, signals: arr(r, 'signals'), domains: (r && r.domains) || [] }))
      .catch(() => setSlice({ agent: ag, loading: false, signals: [], error: true }));
  };
  return (
    <Card title="WORLD SIGNALS" live={asLive(d, available)} sub={available ? `${counts.routed || 0}/${counts.signals || 0} routed` : (d ? 'no sidecar' : null)} onReload={reload}>
      <State e={e} loading={loading} n={available ? signals.length : 0} />
      {d && !available && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
          signal layer unavailable{d.reason ? ` · ${d.reason}` : ''} — configure the sidecar to populate this feed
        </div>
      )}
      {available && Object.keys(byDomain).length > 0 && (
        <Row>
          <span style={mono}>domains</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {Object.entries(byDomain).map(([dom, idx]) => <Tag key={dom}>{dom} {(idx as any[]).length}</Tag>)}
          </span>
        </Row>
      )}
      {available && Object.keys(byAgent).length > 0 && (
        <Row>
          <span style={mono}>agents</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {Object.entries(byAgent).map(([ag, idx]) => (
              <button key={ag} className="tool-btn" style={{ fontSize: 9.5, padding: '1px 5px' }} onClick={() => showAgent(ag)}>
                {ag} {(idx as any[]).length}
              </button>
            ))}
          </span>
        </Row>
      )}
      {slice && (
        <Row>
          <span style={mono}>{slice.agent}</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>
            {slice.loading ? 'loading…' : slice.error ? 'slice unavailable'
              : `${slice.signals.length} signal(s) · ${(slice.domains || []).join(', ') || 'no domains'}`}
          </span>
        </Row>
      )}
      {available && (d.unrouted || []).length > 0 && (
        <Row>
          <span style={mono}>unrouted</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--amber)' }}>
            {d.unrouted.length} unclassified — shown, never guessed
          </span>
        </Row>
      )}
      {available && signals.slice(0, 6).map((s, i) => (
        <Row key={i}>
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title || '—'}</span>
          {s.severity != null && <Tag>sev {s.severity}</Tag>}
        </Row>
      ))}
    </Card>
  );
}

/* 0.39 — the curated market watchlist (GET/POST/DELETE /api/market/watchlist/saved,
   user-guarded). The owner curates a small {symbol, low, high, note} list once;
   routers/market.py's alert/brief evaluators run against it. Read/write, but pure
   storage — no quotes are fetched and no trade is ever proposed here (acting on a
   signal stays a kernel-gated, approval-held action). */
export function WatchlistPanel() {
  const { d, e, loading, reload } = useApi('/api/market/watchlist/saved');
  const watches = arr(d, 'watches');
  const stats = (d && d.stats) || {};
  const [symbol, setSymbol] = useState('');
  const [low, setLow] = useState('');
  const [high, setHigh] = useState('');
  const [note, setNote] = useState('');
  const add = () => {
    if (!symbol.trim()) return;
    const body = {
      symbol: symbol.trim(),
      low: low.trim() === '' ? null : Number(low),
      high: high.trim() === '' ? null : Number(high),
      note: note.trim(),
    };
    act('/api/market/watchlist/saved', body, () => { setSymbol(''); setLow(''); setHigh(''); setNote(''); reload(); });
  };
  const del = (sym) => apiDelete('/api/market/watchlist/saved/' + encodeURIComponent(sym)).then(reload).catch(() => {});
  return (
    <Card title="MARKET WATCHLIST" live={d ? 'live' : undefined} sub={d ? `${stats.total || 0} watched` : null} onReload={reload}>
      <State e={e} loading={loading} n={watches.length} />
      {watches.length > 0 && (
        <Row>
          <span style={mono}>bands</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <Tag>{stats.with_low || 0} low</Tag>
            <Tag>{stats.with_high || 0} high</Tag>
          </span>
        </Row>
      )}
      {watches.slice(0, 12).map((w, i) => (
        <Row key={w.symbol || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{w.symbol}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {(w.low != null || w.high != null) && <Tag>{w.low ?? '−∞'}–{w.high ?? '+∞'}</Tag>}
            {w.note && <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{String(w.note).slice(0, 24)}</span>}
            <button className="tool-btn" title="remove" onClick={() => del(w.symbol)}>✕</button>
          </span>
        </Row>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        <input value={symbol} onChange={(ev) => setSymbol(ev.target.value)} placeholder="symbol" style={{ ...inpS, flex: '0 0 70px' }} />
        <input value={low} onChange={(ev) => setLow(ev.target.value)} placeholder="low" style={{ ...inpS, width: 56 }} />
        <input value={high} onChange={(ev) => setHigh(ev.target.value)} placeholder="high" style={{ ...inpS, width: 56 }} />
        <input value={note} onChange={(ev) => setNote(ev.target.value)} placeholder="note (optional)" style={{ ...inpS, flex: 1, minWidth: 90 }} />
        <button className="tool-btn" onClick={add}>watch</button>
      </div>
    </Card>
  );
}

/* 0.62 — the usage-mode system profile (GET /api/system/profiles): which posture is
   active (balanced/gaming/ai/multimedia/admin) and each profile's knobs. The active
   profile actually bites now — heavy_features gates media-gen, model_tier governs
   cloud escalation. Read-only (selected via JARVIS_SYSTEM_PROFILE). */
export function SystemProfilePanel() {
  const { d, e, loading, reload } = useApi('/api/system/profiles');
  /* DRA-44 — the hardware leg. `/api/system/profiles` is an env-only read (support
     bundles consume it too), so the nvidia-smi/psutil probe lives on its own route
     and this panel joins them: what the box scores, what that suggests, and what is
     actually selected. A component the probe never measured prints `not measured` —
     never 0 and never a dash, which would both read as a measured number. */
  const hwq = useApi('/api/system/hardware');
  const hw = hwq.d && hwq.d.score ? hwq.d : null;
  const detected = (hw && hw.detected) || {};
  const comps = (hw && hw.score && hw.score.components) || {};
  const gpu = detected.gpu || {};
  const active = d && d.active;
  const profiles = (d && d.profiles) || {};
  const names = Object.keys(profiles);
  const part = (label, measured, value) => (
    <Tag c={measured ? 'var(--ink-2)' : 'var(--amber)'}>{label} · {measured ? value : 'not measured'}</Tag>
  );
  return (
    <Card title="SYSTEM PROFILE" live={asLive(d)} sub={d ? `${active || '—'}${active === (d && d.default) ? ' (default)' : ''}` : null} onReload={reload}>
      <State e={e} loading={loading} n={names.length} />
      {hw && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>
            score {hw.score.score}/100 · {hw.score.tier} · recommended · {hw.recommended_profile} · active · {hw.active_profile}
          </div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 4 }}>
            {part('gpu', comps.gpu === 'measured', `${gpu.name || 'gpu'} · ${gpu.vram_total_mb} MB`)}
            {part('cpu', comps.cpu === 'measured', `${detected.cpu_threads} threads`)}
            {part('ram', comps.ram === 'measured', `${detected.ram_total_gb} GB`)}
          </div>
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
            spec-based score (VRAM/threads/RAM as reported) — not a throughput benchmark · the recommendation is advisory, selection stays JARVIS_SYSTEM_PROFILE
          </div>
        </div>
      )}
      {names.map((name) => {
        const p = profiles[name] || {};
        const isActive = name === active;
        return (
          <Row key={name}>
            <span style={{ ...mono, color: isActive ? 'var(--accent-light)' : 'var(--ink-2)' }}>{isActive ? '▸ ' : ''}{name}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <Tag>{p.model_tier}</Tag>
              {!p.heavy_features && <Tag>no-heavy</Tag>}
              {!p.background_autonomy && <Tag>no-bg</Tag>}
            </span>
          </Row>
        );
      })}
    </Card>
  );
}

/* 0.19 — the FIRST-RUN COMMAND CENTER: install health + model + first actions in ONE
   surface (GET /api/onboarding/command-center — the screen's single fetch). Honesty
   contract: every first action carries a backend-derived `ready` flag with the reason
   when held — nothing is presented runnable that can't actually run. "Say hello" drives
   a real /chat turn and records the wizard's test_chat funnel step on success. */
export function CommandCenterPanel() {
  const { d, e, loading, reload } = useApi('/api/onboarding/command-center');
  const install = (d && d.install) || {};
  const model = (d && d.model) || {};
  const wizard = (d && d.wizard) || {};
  const actions = arr(d && d.first_actions);
  const outcomes = arr(d && d.starter_outcomes);
  const safeModelId = (value) => {
    const modelId = typeof value === 'string' ? value.trim() : '';
    return modelId.toLowerCase() === 'none' ? '' : modelId;
  };
  const providerKey = (value) => (
    typeof value === 'string' ? value.trim().toLowerCase().replace(/[^a-z0-9]/g, '') : ''
  );
  const activeModel = safeModelId(model.active_model);
  const configuredModel = safeModelId(model.configured_model);
  const activeProvider = typeof model.active_provider === 'string'
    && model.active_provider.trim().toLowerCase() !== 'none'
    ? model.active_provider.trim()
    : '';
  const backendLabel = typeof model.backend === 'string' ? model.backend.trim() : '';
  const routedProviderKey = providerKey(activeProvider || backendLabel);
  const residentModels = arr(model.resident_models).slice(0, 64).filter((entry) => (
    entry && safeModelId(entry.id) && providerKey(entry.provider)
  ));
  const residencyUnknown = model.residency_state === 'unknown' || model.ready === null;
  const route = typeof model.route === 'string' ? model.route.trim().toLowerCase() : '';
  const cloudRoute = (routedProviderKey === 'gemini'
      && ['cloud', 'cloud-fallback', 'cloud-flash', 'cloud-pro'].includes(route))
    || (routedProviderKey === 'claude' && route === 'claude');
  const localRoute = ['local', 'local-deep', 'local-fallback'].includes(route);
  const exactResident = residentModels.some((entry) => (
    providerKey(entry.provider) === routedProviderKey && safeModelId(entry.id) === activeModel
  ));
  const modelRouteReady = model.ready === true
    && Boolean(activeModel)
    && (cloudRoute || (localRoute && exactResident));
  const candidateModel = configuredModel || activeModel;
  const modelLabel = modelRouteReady
    ? `${activeModel} · ${cloudRoute ? 'cloud ready' : 'loaded'}`
    : candidateModel
      ? `${candidateModel} · ${residencyUnknown ? 'residency unknown' : 'configured, not loaded'}`
      : (model.ready === null ? 'model readiness unknown' : 'no runnable model');
  const modelSource = activeProvider
    || (backendLabel && backendLabel.toLowerCase() !== 'none' ? backendLabel : 'no route');
  const [hello, setHello] = useState(null);
  const sayHello = () => {
    setHello('…');
    apiPost('/chat', { message: 'Hello Nerva — first-run check.' })
      .then((r: any) => {
        const reply = (r && r.reply) ? String(r.reply) : '';
        // A degraded reply (⚠ / ⚠️ prefix from the local-backend-down path) is a
        // FAILED hello, not a completed step — show it, but don't tick test_chat,
        // or the wizard would claim "Say hello ✓" on a hello that never reached a
        // model (real-world 2026-07-08: model 400s while the server is reachable).
        const degraded = reply.trim().startsWith('⚠');
        setHello(reply ? reply.slice(0, 140) : 'ok');
        if (!degraded) {
          act('/api/onboarding/funnel', { step: 'test_chat', event: 'complete' }, reload);
        }
      })
      .catch(() => setHello('chat failed — is a model running?'));
  };
  const done = new Set((wizard.completed) || []);
  const steps = wizard.steps || [];
  return (
    <Card title="COMMAND CENTER" live={asLive(d)}
      sub={d ? `${install.ready ? 'ready' : 'starting'} · ${modelSource}${wizard.complete ? ' · onboarded ✓' : ''}` : null}
      onReload={reload}>
      <State e={e} loading={loading} n={actions.length} />
      <Row>
        <span style={mono}>install</span>
        <span style={{ marginLeft: 'auto', color: install.ready ? 'var(--green)' : 'var(--amber)' }}>
          {install.ready ? '✓ ready' : '○ starting'}{install.version ? ` · v${install.version}` : ''}
        </span>
      </Row>
      <Row>
        <span style={mono}>model</span>
        <span style={{ marginLeft: 'auto', color: modelRouteReady ? 'var(--green)' : 'var(--amber)' }}>
          {modelLabel}
        </span>
      </Row>
      {d && wizard.hint && <Row><span style={{ color: 'var(--amber)', fontSize: 11 }}>⚠ {wizard.hint}</span></Row>}
      {steps.length > 0 && (
        <Row>
          <span style={mono}>onboarding</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-2)' }}>
            {steps.map((s) => (done.has(s.key) ? '●' : '○')).join(' ')} {done.size}/{steps.length}
          </span>
        </Row>
      )}
      {outcomes.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.12em', color: 'var(--ink-2)', marginBottom: 3 }}>
            WHAT NERVA CAN DO FOR YOU
          </div>
          {outcomes.map((o) => {
            const live = o.status === 'live';
            const privacy = {
              local_only: 'stays local',
              local_storage_cloud_model: 'stored locally · cloud model may receive context',
              third_party_account: 'connected account',
              third_party_account_cloud_model: 'connected account · cloud model may receive context',
              public_web: 'external websites',
            }[o.privacy] || o.privacy;
            const changes = {
              none: 'read-only',
            }[o.changes] || o.changes;
            return (
              <div key={o.key} style={{ padding: '7px 0', borderBottom: '1px solid var(--panel-line)' }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ color: live ? 'var(--ink-1)' : 'var(--ink-2)' }}>{o.title}</span>
                  <Tag c={live ? 'var(--green)' : 'var(--amber)'}>{live ? 'READY NOW' : 'NEEDS SETUP'}</Tag>
                </div>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 4 }}>
                  <Tag>{privacy}</Tag>
                  <Tag>{changes}</Tag>
                </div>
                {!live && o.setup && (
                  <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{o.setup}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {actions.map((a) => (
        <Row key={a.key}>
          <span style={{ color: a.ready ? 'var(--ink-1)' : 'var(--ink-2)' }}>{a.title}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            {a.ready && a.key === 'say_hello'
              && <button className="tool-btn" onClick={sayHello}>run</button>}
            {!a.ready && a.reason
              && <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{a.reason}</span>}
          </span>
        </Row>
      ))}
      {hello && <Row><span style={{ fontSize: 11, color: 'var(--accent-light)' }}>↳ {hello}</span></Row>}
    </Card>
  );
}

/* Owner B0 finding: onboarding you have to FIND is not onboarding. The gate makes
   the Command Center the LANDING surface on first run — shown whenever the install
   isn't usable yet (no reachable model, or the wizard incomplete) and not yet
   dismissed. Dismiss persists; a data error never blocks the cockpit. */
export const FIRST_RUN_DISMISS_KEY = 'hud.firstrun.dismissed';

export function shouldShowFirstRun(cc: any): boolean {
  if (!cc || !cc.model || !cc.wizard) return false;
  return cc.model.ready !== true || cc.wizard.complete !== true;
}

export function FirstRunGate({ onClose }) {
  const dismiss = () => {
    try { localStorage.setItem(FIRST_RUN_DISMISS_KEY, '1'); } catch { /* ignore */ }
    onClose();
  };
  return (
    <div className="pal-scrim" style={{ alignItems: 'flex-start', paddingTop: '8vh' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 'min(560px,95vw)', maxHeight: '84vh', overflow: 'auto', background: 'var(--void-2)', border: '1px solid var(--border-active, var(--panel-line))', borderRadius: 'var(--radius)', padding: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12, gap: 12 }}>
          <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '.14em', color: 'var(--accent-light)' }}>FIRST RUN</span>
          <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>let's get you to a working assistant</span>
        </div>
        <CommandCenterPanel />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
          <button className="tool-btn" onClick={dismiss}>continue to cockpit →</button>
        </div>
      </div>
    </div>
  );
}

const SECTIONS: Array<[string, Array<() => any>]> = [
  ['Start', [CommandCenterPanel]],
  ['Home', [PresenceInboxPanel, AmbientWatchPanel, HousePanel, CameraPanel]],
  ['Memory', [DataSpacesPanel, LocalDocsPanel, NotesPanel, NoteDocsPanel, VaultPanel, KgPanel, MemoryWritePanel, MemoryHygienePanel, MemoryEvalPanel, CapturePanel, ReflectionPanel, ProvenancePanel]],
  ['Trust', [SecuritySkillsMapPanel, PaymentsPanel, SignalGovernancePanel, TrustOpsPanel, KillSwitchPanel, KernelMetricsPanel, ReadinessPanel, LoopBreakerPanel, GovernancePanel, PosturePanel, AuditAnchorsPanel, SecuritySkillsPanel, NetworkMonitorPanel, CommsRatePanel, SafeCommsDraftPanel, SecretsPanel, CapabilitiesPanel, PairingPanel, InjectionScanPanel]],
  ['Interop', [OsintPanel, MarketplaceAdminPanel, SkillsImportPanel, WritebackDigestPanel, A2AInboxPanel, MeshPeersPanel, SatellitesPanel, OraclePanel, MarketplacePanel, SkillHistoryPanel, PacksPanel, SignalRoutingPanel, WatchlistPanel]],
  ['Observe', [OnboardingPanel, CodeIntelPanel, CoachPanel, ReviewQualityPanel, AgentsArenaPanel, EvalPanel, ReviewPanel, ArenaPanel, QualityPanel, APMPanel, ModelInfoPanel, DesignManifestPanel, FeedbackPanel, SelfImprovementPanel, PendingSkillsPanel, CognitionPanel, SwarmPanel, SubAgentsPanel, SystemMapPanel]],
  ['Build', [CreativePanel, DesktopAllowlistPanel, WorkflowTracesPanel, WorkflowsPanel, WorkflowBuilderPanel, SandboxPanel, TemplatesPanel, AcquisitionPanel, MediaDirectorPanel, MediaGalleryPanel, PublishReadinessPanel, OperatorPanel, ScreenReflexPanel]],
  ['Autonomy & Agents', [AutonomyControlPanel, MissionCanvasPanel, DecisionInboxPanel, MissionsPanel, AgentAutonomyPanel, TodayPanel, SchedulePanel, LearningPanel, SessionsPanel, HeartbeatPanel, TranscriptPanel, EscalationPanel]],
  ['Admin', [LlmRoutingPanel, SupportVoicePanel, BackupPanel, OAuthPanel, SettingsPanel, PromptsPanel, RoomsPanel, LMStudioPanel, VlmDescribePanel, AuthProfilesPanel, SystemProfilePanel]],
];

/* Renders the failed-mutation sink from api/client.ts. This is the one place that makes
   a swallowed admin action visible: the HUD has 27 `.catch(() => {})` sites, so a fix at
   any single call site would leave the rest silent. Empty (renders nothing) until a
   mutation actually fails, so it costs nothing on the happy path. */
export function ActionFailureBanner() {
  const [fails, setFails] = useState(actionFailures());
  useEffect(() => onActionFailure(setFails), []);
  if (!fails.length) return null;
  return (
    <div role="alert" style={{ border: '1px solid var(--red)', borderRadius: 4, padding: '8px 10px', marginBottom: 12, background: 'rgba(255,0,0,.06)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: fails.length ? 6 : 0 }}>
        <span style={{ ...mono, color: 'var(--red)' }}>
          {fails.length} action{fails.length > 1 ? 's' : ''} FAILED — the change did not happen
        </span>
        <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => { clearActionFailures(); setFails([]); }}>dismiss</button>
      </div>
      {fails.slice(0, 5).map((f, i) => (
        <div key={i} style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>
          {f.method} {f.path} → <span style={{ color: 'var(--red)' }}>{f.status}</span>
          {f.status === 403 ? ' · refused (kernel denial or missing admin token)' : ''}
          {f.status === 401 ? ' · not authorised' : ''}
        </div>
      ))}
    </div>
  );
}

export function ConsoleOverlay({ onClose }) {
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);
  return (
    <div className="pal-scrim" onClick={onClose} style={{ alignItems: 'flex-start', paddingTop: '5vh' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 'min(1120px,95vw)', maxHeight: '90vh', overflow: 'auto', background: 'var(--void-2)', border: '1px solid var(--border-active, var(--panel-line))', borderRadius: 'var(--radius)', padding: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14, gap: 12 }}>
          <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '.14em', color: 'var(--accent-light)' }}>CONSOLE</span>
          <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>net-new capability surfaces (P4c) · live + mock-tolerant</span>
          <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={onClose}>esc ✕</button>
        </div>
        <ActionFailureBanner />
        {SECTIONS.map(([label, panels]) => (
          <div key={label} style={{ marginBottom: 18 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.18em', color: 'var(--ink-3)', margin: '0 0 8px' }}>{String(label).toUpperCase()}</div>
            <div style={{ columns: '3 320px', columnGap: 'var(--gap)' }}>
              {panels.map((P, i) => <P key={i} />)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
