/* HUD v2 · P4c — the net-new gap surfaces from the §5b/§5c audit, hosted in a
   Console overlay (mirrors v1 tools.js). Each panel fetches its real endpoint and
   degrades to an offline/empty state — never blocks. Admin-guarded calls work on
   localhost; on a network they surface the 401 via the client's token prompt. */
import React, { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiPut, apiDelete, actionFailures, onActionFailure, clearActionFailures } from './api/client';
import { localModelStatus } from './api/live';
import { OperatorPanel } from './operator-panel';

function useApi(path, auto = true, admin = false) {
  const [d, setD] = useState(null);
  const [e, setE] = useState(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    apiGet(path, admin ? { admin: true } : undefined).then((r) => { setD(r); setE(null); }).catch((err) => setE(err?.message || 'offline')).finally(() => setLoading(false));
  }, [path, admin]);
  useEffect(() => { if (auto) reload(); }, [auto, reload]);
  return { d, e, loading, reload };
}
const arr = (x, ...k) => (Array.isArray(x) ? x : (k.map((kk) => x && x[kk]).find(Array.isArray) || []));
const mono = { fontFamily: 'var(--font-mono)', fontSize: 11 };

/* Per-panel LIVE/SEED honesty chip (TASK-2 tail). Distinct from LiveSourceChip
   (mode-level, block-positioned under a header) — this is inline-sized for the
   panel-head flex row. Same color/wording convention: green LIVE = the panel's
   `enabled`-style flag is on (or the surface has no such flag and simply loaded
   real data), amber SEED = present but not collecting yet. Renders nothing until
   the panel has actually loaded (`live` undefined) so it never guesses. */
const asLive = (loaded: any, enabled?: any): 'live' | 'seed' | undefined => {
  if (!loaded) return undefined;
  if (enabled === undefined) return 'live';
  return enabled ? 'live' : 'seed';
};

function PanelChip({ live }: { live?: 'live' | 'seed' | null }) {
  if (live !== 'live' && live !== 'seed') return null;
  const isLive = live === 'live';
  const c = isLive ? 'var(--green)' : 'var(--amber)';
  return (
    <span
      title={isLive ? 'Live data from the backend' : 'Seeded/disabled — not live'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '.06em',
        color: c, border: `1px solid ${c}`, borderRadius: 3, padding: '0 5px',
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c }} />
      {isLive ? 'LIVE' : 'SEED'}
    </span>
  );
}

function Card({ title, sub, live, onReload, children }: { title?: any; sub?: any; live?: any; onReload?: any; children?: any }) {
  return (
    <div className="panel" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <span className="ttl">{title}</span>
        <PanelChip live={live} />
        {sub != null && <span className="st">{sub}</span>}
        {onReload && <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={onReload} title="reload">↻</button>}
      </div>
      <div className="panel-body tight" tabIndex={0}>{children}</div>
    </div>
  );
}
const State = ({ e, loading, n }) => (loading ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>loading…</div>
  : e ? <div style={{ color: 'var(--amber)', fontSize: 12 }}>offline · {e}</div>
  : n === 0 ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>nothing yet</div> : null);
const Row = ({ children }) => <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>{children}</div>;
const Tag = ({ c, children }: { c?: any; children?: any }) => <span style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: c || 'var(--ink-3)' }}>{children}</span>;
const Btn = ({ onClick, children }) => <button className="tool-btn" onClick={onClick} style={{ marginLeft: 'auto' }}>{children}</button>;
const act = (p, body, then?) => apiPost(p, body).then(then || (() => {})).catch(() => {});
// `onErr` is OPTIONAL but matters: without it a failed admin action is invisible. Engaging
// the kill-switch is kernel-mediated and answers 403 "kernel denied" without a capability
// token, so the 2026-07-27 QA run pressed HALT ALL, got no error, no state change and no
// hint it had been refused — the card kept reading "ARMED · operational". Any call site
// that drives a safety or governance control MUST pass onErr and show it.
const actA = (p, body, then, onErr?) => apiPost(p, body, { admin: true })
  .then(then || (() => {}))
  .catch((err) => { if (onErr) onErr(err); });
const inpS = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11 };
const taS = { width: '100%', minHeight: 64, background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono };
const Json = ({ v, max = 220 }) => (v == null ? null
  : <pre style={{ ...mono, fontSize: 10, lineHeight: 1.45, whiteSpace: 'pre-wrap', maxHeight: max, overflow: 'auto', margin: '6px 0 0', padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4, color: 'var(--ink-2)' }}>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</pre>);
function MediaOutcome({ value }) {
  if (!value) return null;
  if (value.output && value.output.ok === false) {
    return <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 8 }}>
      refused · {value.output.reason || value.reason || 'media_action_failed'}
    </div>;
  }
  if (value.status === 'completed' && value.output?.ok === true && value.output?.verified === true) {
    return <div role="status" style={{ ...mono, color: 'var(--green)', marginTop: 8 }}>
      verified success · {value.output.device_id || 'device'} · {value.output.state || 'verified'}
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
  const del = (name) => apiDelete('/api/kg/entities/' + encodeURIComponent(name)).then(reload).catch(() => {});
  const forget = () => { if (!forgetId.trim()) return; act('/api/memory/decay/forget', { id: forgetId.trim() }, (r) => { setMsg(r && r.error ? 'not found' : 'forgotten · ' + forgetId.trim()); setForgetId(''); reload(); }); };
  return (
    <Card title="KNOWLEDGE GRAPH" live={asLive(d)} sub={d ? `${ents.length} entities` : null} onReload={reload}>
      <State e={e} loading={loading} n={ents.length} />
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
      {msg && <div style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
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
function A2AInboxPanel() {
  const { d, e, loading, reload } = useApi('/api/a2a/inbox');
  const items = arr(d, 'inbox', 'tasks');
  return <Card title="A2A APPROVAL INBOX" live={asLive(d)} sub={items.length} onReload={reload}>
    <State e={e} loading={loading} n={items.length} />
    {items.slice(0, 10).map((it, i) => <Row key={i}><span style={mono}>{it.peer || it.from || '?'}</span><span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(it.task || it.summary || '').slice(0, 40)}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
        <button className="tool-btn" onClick={() => actA(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approved: true }, reload)}>✓</button>
        <button className="tool-btn" onClick={() => actA(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approved: false }, reload)}>✕</button>
      </span></Row>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>verified peer tasks land here; never auto-execute (H16.2)</div>
  </Card>;
}
function MarketplacePanel() {
  const { d, e, loading, reload } = useApi('/api/skills/marketplace');
  const skills = arr(d, 'skills');
  return <Card title="SKILLS MARKETPLACE" live={asLive(d)} sub={skills.length} onReload={reload}>
    <State e={e} loading={loading} n={skills.length} />
    {skills.slice(0, 10).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{s.name}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
        <Tag c={s.signed ? 'var(--green)' : 'var(--amber)'}>{s.signed ? 'signed' : 'unsigned'}</Tag>
        <Tag c={s.review_status === 'approved' ? 'var(--green)' : s.review_status === 'rejected' ? 'var(--red)' : 'var(--amber)'}>{s.review_status || 'pending'}</Tag>
        {s.review_status !== 'approved' && <button className="tool-btn" title="approve skill" onClick={() => actA('/api/skills/marketplace/review', { name: s.name, status: 'approved' }, reload)}>✓</button>}
        {s.review_status !== 'rejected' && <button className="tool-btn" title="reject skill" onClick={() => actA('/api/skills/marketplace/review', { name: s.name, status: 'rejected' }, reload)}>✕</button>}
      </span></Row>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>signed + moderated — ✓/✕ sets review status (anti-ClawHub, H12.12)</div>
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
      <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>v{x.version} · {x.cases ?? x.count ?? '?'}</span>
      <Btn onClick={() => act('/api/eval/datasets/run', { name: x.name }, reload)}>run</Btn></Row>)}
    {open && <div style={{ marginTop: 6 }}>
      <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)' }}>{open.toUpperCase()} · RECENT RUNS</div>
      {runs.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>no recorded runs</div>}
      {runs.map((r, i) => <Row key={i}><span style={mono}>{(r.run_id || r.id || r.ts || '').toString().slice(0, 19)}</span>
        <span style={{ marginLeft: 'auto', ...mono, fontSize: 10, color: 'var(--accent-light)' }}>μ {r.mean_score ?? r.score ?? '—'}</span></Row>)}
      {runs.length >= 2 && <button className="tool-btn" style={{ marginTop: 6 }} onClick={compare}>compare last two</button>}
      {cmp && <div style={{ ...mono, fontSize: 10.5, marginTop: 6 }}>
        <span style={{ color: (cmp.score_delta ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>Δ score {cmp.score_delta ?? '—'}</span>
        <span style={{ color: 'var(--ink-3)' }}> · {(cmp.regressions || []).length} regression(s) · {(cmp.improvements || []).length} improvement(s)</span>
        {(cmp.regressions || []).slice(0, 4).map((g, i) => <div key={i} style={{ color: 'var(--red)' }}>− {(g.case || g.prompt || g.id || '').toString().slice(0, 48)}</div>)}
      </div>}
    </div>}
  </Card>;
}
function ReviewPanel() {
  const { d, e, loading, reload } = useApi('/api/review/queue?status=pending');
  const q = arr(d, 'queue', 'items');
  return <Card title="REVIEW QUEUE" live={asLive(d)} sub={q.length} onReload={reload}>
    <State e={e} loading={loading} n={q.length} />
    {q.slice(0, 10).map((it, i) => <Row key={i}><span style={{ fontSize: 11 }}>{(it.preview || it.text || '').slice(0, 38)}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
        <button className="tool-btn" onClick={() => act(`/api/review/${it.id || it.trace_id}/vote`, { verdict: 'up' }, reload)}>👍</button>
        <button className="tool-btn" onClick={() => act(`/api/review/${it.id || it.trace_id}/vote`, { verdict: 'down' }, reload)}>👎</button>
      </span></Row>)}
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
/* HUD-v3 C7 (workflow runtime management). StepGenPanel covers the AI step-BUILDER;
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
function StepGenPanel() {
  const [desc, setDesc] = useState('');
  const [out, setOut] = useState(null);
  const gen = () => { if (!desc.trim()) return; setOut('generating…'); act('/api/workflows/step/generate', { description: desc }, (r) => setOut(r.step || r)); };
  return <Card title="AI STEP BUILDER" live={'live'}>
    <textarea value={desc} onChange={(ev) => setDesc(ev.target.value)} placeholder="describe the workflow step — e.g. 'have vision summarize the week's research and hand it to veronica'" style={taS} />
    <button className="tool-btn" style={{ marginTop: 6 }} onClick={gen}>generate step</button>
    {out != null && <Json v={out} />}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>description → validated WorkflowStep config (H10.7) · paste into the workflow builder</div>
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

/* ── Agents ops ────────────────────────────────────────── */
function LearningPanel() {
  const { d, e, loading, reload } = useApi('/learning');
  const cands = arr(d, 'promotion_suggestions', 'promotion_candidates', 'candidates');
  const [agent, setAgent] = useState('');
  const [note, setNote] = useState('');
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
      {note && <span style={{ fontSize: 10, color: 'var(--green)' }}>{note}</span>}
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
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>configured routing is independent from provider-reported residency · lifecycle actions follow backend capabilities</div>
  </Card>;
}
function AuthProfilesPanel() {
  const { d, e, loading, reload } = useApi('/api/llm/auth-profiles', true, true);
  const pools = arr(d, 'profiles', 'pools') || Object.entries(d || {}).map(([k, v]) => ({ provider: k, ...(typeof v === 'object' ? v : {}) }));
  const list = Array.isArray(pools) ? pools : [];
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
function OAuthPanel() {
  const { d, e, loading, reload } = useApi('/api/oauth/status');
  const svcs = arr(d, 'services') || Object.entries(d || {}).map(([k, v]: [string, any]) => ({ service: k, ...(v || {}) }));
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
    apiGet('/api/autonomy/tasks/' + id + '/preview')
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
      {d && !enabled && <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>empty until JARVIS_SKILL_HISTORY is on</div>}
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
        <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10, margin: '10px 0 4px' }}>PRESENCE · PSEUDONYMOUS</div>
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
  const status = useApi('/api/acquisition/status');
  const audit = useApi('/api/acquisition/events?limit=100');
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
  let hasAdmin = false;
  try { hasAdmin = !!localStorage.getItem('hud.admin_token'); } catch { /* unavailable */ }

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
        {hasAdmin && <section aria-label="admin acquisition lifecycle" style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            <button className="tool-btn" type="button" onClick={exportLedger} aria-label="Export acquisition ledger">export ledger</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6 }}>
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
        </section>}
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
  const active = d && d.active;
  const profiles = (d && d.profiles) || {};
  const names = Object.keys(profiles);
  return (
    <Card title="SYSTEM PROFILE" live={asLive(d)} sub={d ? `${active || '—'}${active === (d && d.default) ? ' (default)' : ''}` : null} onReload={reload}>
      <State e={e} loading={loading} n={names.length} />
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
          <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.12em', color: 'var(--ink-3)', marginBottom: 3 }}>
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
          <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>let's get you to a working assistant</span>
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
  ['Home', [AmbientWatchPanel, HousePanel, CameraPanel]],
  ['Memory', [DataSpacesPanel, LocalDocsPanel, NotesPanel, KgPanel, CapturePanel, ReflectionPanel, ProvenancePanel]],
  ['Trust', [KillSwitchPanel, KernelMetricsPanel, ReadinessPanel, LoopBreakerPanel, GovernancePanel, PosturePanel, SecuritySkillsPanel, NetworkMonitorPanel, CommsRatePanel, SafeCommsDraftPanel, SecretsPanel, CapabilitiesPanel, PairingPanel, InjectionScanPanel]],
  ['Interop', [A2AInboxPanel, MeshPeersPanel, SatellitesPanel, OraclePanel, MarketplacePanel, SkillHistoryPanel, WatchlistPanel]],
  ['Observe', [OnboardingPanel, EvalPanel, ReviewPanel, ArenaPanel, QualityPanel, APMPanel, ModelInfoPanel, FeedbackPanel, SelfImprovementPanel]],
  ['Build', [WorkflowsPanel, StepGenPanel, SandboxPanel, TemplatesPanel, AcquisitionPanel, MediaDirectorPanel, MediaGalleryPanel, OperatorPanel]],
  ['Autonomy & Agents', [DecisionInboxPanel, MissionsPanel, AgentAutonomyPanel, TodayPanel, SchedulePanel, LearningPanel, SessionsPanel, HeartbeatPanel, TranscriptPanel, EscalationPanel]],
  ['Admin', [BackupPanel, OAuthPanel, SettingsPanel, PromptsPanel, RoomsPanel, LMStudioPanel, AuthProfilesPanel, SystemProfilePanel]],
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
