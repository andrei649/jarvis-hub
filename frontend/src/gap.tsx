// @ts-nocheck
/* HUD v2 · P4c — the net-new gap surfaces from the §5b/§5c audit, hosted in a
   Console overlay (mirrors v1 tools.js). Each panel fetches its real endpoint and
   degrades to an offline/empty state — never blocks. Admin-guarded calls work on
   localhost; on a network they surface the 401 via the client's token prompt. */
import React, { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiPut, apiDelete } from './api/client';

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

function Card({ title, sub, onReload, children }) {
  return (
    <div className="panel" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <span className="ttl">{title}</span>
        {sub != null && <span className="st">{sub}</span>}
        {onReload && <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={onReload} title="reload">↻</button>}
      </div>
      <div className="panel-body tight">{children}</div>
    </div>
  );
}
const State = ({ e, loading, n }) => (loading ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>loading…</div>
  : e ? <div style={{ color: 'var(--amber)', fontSize: 12 }}>offline · {e}</div>
  : n === 0 ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>nothing yet</div> : null);
const Row = ({ children }) => <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--panel-line)' }}>{children}</div>;
const Tag = ({ c, children }) => <span style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: c || 'var(--ink-3)' }}>{children}</span>;
const Btn = ({ onClick, children }) => <button className="tool-btn" onClick={onClick} style={{ marginLeft: 'auto' }}>{children}</button>;
const act = (p, body, then) => apiPost(p, body).then(then || (() => {})).catch(() => {});
const actA = (p, body, then) => apiPost(p, body, { admin: true }).then(then || (() => {})).catch(() => {});
const inpS = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11 };
const taS = { width: '100%', minHeight: 64, background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono };
const Json = ({ v, max = 220 }) => (v == null ? null
  : <pre style={{ ...mono, fontSize: 10, lineHeight: 1.45, whiteSpace: 'pre-wrap', maxHeight: max, overflow: 'auto', margin: '6px 0 0', padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4, color: 'var(--ink-2)' }}>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</pre>);
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
function DataSpacesPanel() {
  const { d, e, loading, reload } = useApi('/api/memory/spaces');
  const spaces = arr(d, 'spaces');
  const [name, setName] = useState(''); const [src, setSrc] = useState('');
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11, flex: 1 };
  const create = () => { if (!name.trim()) return; apiPost('/api/memory/spaces', { name: name.trim(), sources: src.split(',').map((s) => s.trim()).filter(Boolean) }, { admin: true }).then(() => { setName(''); setSrc(''); reload(); }).catch(() => {}); };
  return <Card title="DATA SPACES" sub={spaces.length} onReload={reload}>
    <State e={e} loading={loading} n={spaces.length} />
    {spaces.slice(0, 12).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{s.name || s}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{(s.sources || s.categories || []).join?.(', ')}</span><Btn onClick={() => apiDelete('/api/memory/spaces/' + (s.name || s), { admin: true }).then(reload).catch(() => {})}>✕</Btn></Row>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
      <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="space name" style={inp} />
      <input value={src} onChange={(ev) => setSrc(ev.target.value)} placeholder="sources, csv" style={inp} />
      <button className="tool-btn" onClick={create}>+ add</button>
    </div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>per-agent read scope (H10.26) · default-open</div>
  </Card>;
}
function LocalDocsPanel() {
  const { d, e, loading, reload } = useApi('/api/local-docs');
  const keys = arr(d, 'folders', 'keys'); const docs = d?.indexed || d?.docs;
  return <Card title="LOCAL DOCS" sub={docs != null ? docs : keys.length} onReload={reload}>
    <State e={e} loading={loading} n={keys.length} />
    {keys.slice(0, 8).map((k, i) => <Row key={i}><span style={mono}>{k.key || k}</span><Btn onClick={() => act('/api/local-docs/index', { key: k.key || k }, reload)}>index</Btn></Row>)}
  </Card>;
}
function NotesPanel() {
  const { d, reload } = useApi('/api/notes');
  const [v, setV] = useState(null);
  const cur = v != null ? v : (d?.content || d?.notes || '');
  return <Card title="NOTES" onReload={reload}>
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
  return <Card title="NIGHTLY REFLECTION" onReload={reload}>
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
  return <Card title="SENDER PAIRING" sub={d?.summary ? (d.summary.pending ?? senders.length) + ' pending' : senders.length} onReload={reload}>
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
  return <Card title="INJECTION SCAN">
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
  return <Card title="SECRET BROKER" sub={names.length} onReload={reload}>
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
function KillSwitchPanel() {
  const { d, e, loading, reload } = useApi('/api/security/kill-switch');
  const halted = d?.halted ?? d?.engaged;
  return <Card title="KILL-SWITCH" onReload={reload}>
    <State e={e} loading={loading} n={1} />
    <Row><span style={{ color: halted ? 'var(--red)' : 'var(--green)' }}>{halted ? 'ENGAGED · all agents halted' : 'ARMED · operational'}</span>
      <Btn onClick={() => actA('/api/security/kill-switch', { engage: !halted, scope: 'global', reason: 'hud' }, reload)}>{halted ? 'disengage' : 'HALT ALL'}</Btn></Row>
  </Card>;
}
function CapabilitiesPanel() {
  const [caps, setCaps] = useState('fs.read,memory.write'); const [out, setOut] = useState(null);
  return <Card title="CAPABILITY TOKENS">
    <input value={caps} onChange={(e) => setCaps(e.target.value)} style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono }} />
    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
      <button className="tool-btn" onClick={() => actA('/api/security/capabilities/issue', { capabilities: caps.split(',').map((s) => s.trim()) }, (r) => setOut(JSON.stringify(r)))}>issue</button>
    </div>
    {out && <pre style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', whiteSpace: 'pre-wrap', marginTop: 6 }}>{out.slice(0, 200)}</pre>}
  </Card>;
}

export function KernelMetricsPanel() {
  const { d, e, loading, reload } = useApi('/api/metrics/kernel');
  const v = (d && d.by_verdict) || {};
  const denials = (d && d.recent_denials) || [];
  return (
    <Card title="ACTION KERNEL" sub={d ? `${d.total} decisions` : null} onReload={reload}>
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
export function LoopBreakerPanel() {
  const { d, e, loading, reload } = useApi('/api/security/loop-breaker');
  const tripped = d?.tripped;
  return (
    <Card title="LOOP BREAKER" sub={d ? (tripped ? 'TRIPPED' : 'closed') : null} onReload={reload}>
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

/* ── Interop ───────────────────────────────────────────── */
function A2AInboxPanel() {
  const { d, e, loading, reload } = useApi('/api/a2a/inbox');
  const items = arr(d, 'inbox', 'tasks');
  return <Card title="A2A APPROVAL INBOX" sub={items.length} onReload={reload}>
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
  return <Card title="SKILLS MARKETPLACE" sub={skills.length} onReload={reload}>
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
  return <Card title="EVAL DATASETS" sub={ds.length} onReload={reload}>
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
  return <Card title="REVIEW QUEUE" sub={q.length} onReload={reload}>
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
  return <Card title="APM" onReload={reload}>
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
  return <Card title="NL SCHEDULING">
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
  return <Card title="HEARTBEATS" sub={list.length} onReload={reload}>
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
  return <Card title="TRANSCRIPT → TASKS">
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
  return <Card title="ESCALATION" sub={targets.length + ' ch'} onReload={reload}>
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
  return <Card title="AGENT TEMPLATES" sub={tpls.length} onReload={reload}>
    <State e={e} loading={loading} n={tpls.length} />
    {tpls.slice(0, 8).map((tp, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{tp.id || tp.name || tp}</span><span style={{ fontSize: 10, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(tp.description || tp.role || '').slice(0, 36)}</span><Btn onClick={() => inst(tp)}>instantiate</Btn></Row>)}
    <input value={name} onChange={(ev) => setName(ev.target.value)} placeholder="new agent name (optional)" style={{ ...inpS, width: '100%', marginTop: 8 }} />
    {out && <Json v={out} />}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>renders an agents.yaml config + SOUL skeleton — save via the normal agent flow (H10.29)</div>
  </Card>;
}

/* ── Build ─────────────────────────────────────────────── */
function StepGenPanel() {
  const [desc, setDesc] = useState('');
  const [out, setOut] = useState(null);
  const gen = () => { if (!desc.trim()) return; setOut('generating…'); act('/api/workflows/step/generate', { description: desc }, (r) => setOut(r.step || r)); };
  return <Card title="AI STEP BUILDER">
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
  return <Card title="SANDBOX" sub={st ? (st.backend || st.active_backend || (st.docker ? 'docker' : 'subprocess')) : null} onReload={reload}>
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
  return <Card title="LEARNING · BENCH" sub={cands.length} onReload={reload}>
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
  return <Card title="SESSIONS" sub={list.length} onReload={reload}>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 12).map((s, i) => <Row key={i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{s.session_id || s.id || s}</span><span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{s.turns ?? s.count ?? ''}</span>{(s.session_id || s.id) && <button className="tool-btn" onClick={() => act('/sessions/resume', { session_id: s.session_id || s.id })}>resume</button>}</Row>)}
  </Card>;
}

/* ── Admin ─────────────────────────────────────────────── */
function LMStudioPanel() {
  const { d, e, loading, reload } = useApi('/api/models/local');
  const models = arr(d, 'models');
  const [model, setModel] = useState('');
  const [note, setNote] = useState('');
  const say = (r) => { setNote(typeof r === 'object' ? (r.detail || r.status || (r.ok ? 'ok' : JSON.stringify(r).slice(0, 60))) : String(r)); reload(); };
  return <Card title="LM STUDIO" sub={models.length + ' models'} onReload={reload}>
    <State e={e} loading={loading} n={models.length} />
    {models.slice(0, 8).map((m, i) => <Row key={i}>
      <span style={{ ...mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name || m.id}</span>
      <Tag c={m.status === 'loaded' || m.active ? 'var(--green)' : 'var(--ink-3)'}>{m.status || (m.active ? 'loaded' : 'ready')}</Tag>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
        {(m.status === 'loaded' || m.active)
          ? <button className="tool-btn" title="unload" onClick={() => actA('/api/llm/unload', { model: m.id || m.name }, say)}>⏏</button>
          : <button className="tool-btn" title="load" onClick={() => actA('/api/llm/load', { model: m.id || m.name }, say)}>▶</button>}
      </span></Row>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
      <button className="tool-btn" onClick={() => actA('/api/llm/server/start', {}, say)}>start server</button>
      <input value={model} onChange={(ev) => setModel(ev.target.value)} placeholder="model id" style={{ ...inpS, flex: 1, minWidth: 110 }} />
      <button className="tool-btn" onClick={() => model.trim() && actA('/api/llm/load', { model: model.trim() }, say)}>load</button>
      <button className="tool-btn" onClick={() => actA('/api/llm/unload', model.trim() ? { model: model.trim() } : {}, say)}>unload</button>
    </div>
    {note && <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6 }}>{note}</div>}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>lms server/load/unload — kill-switch: llm.control_enabled</div>
  </Card>;
}
function AuthProfilesPanel() {
  const { d, e, loading, reload } = useApi('/api/llm/auth-profiles', true, true);
  const pools = arr(d, 'profiles', 'pools') || Object.entries(d || {}).map(([k, v]) => ({ provider: k, ...(typeof v === 'object' ? v : {}) }));
  const list = Array.isArray(pools) ? pools : [];
  return <Card title="CLOUD AUTH PROFILES" sub={list.length} onReload={reload}>
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
  const svcs = arr(d, 'services') || Object.entries(d || {}).map(([k, v]) => ({ service: k, ...(v || {}) }));
  return <Card title="OAUTH" sub={svcs.length} onReload={reload}>
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
  const [dirty, setDirty] = useState({});
  const [saved, setSaved] = useState(null);
  const cats = d && typeof d === 'object' ? d : {};
  const setVal = (cat, key, v) => setDirty((p) => ({ ...p, [cat]: { ...(p[cat] || {}), [key]: v } }));
  const valOf = (cat, it) => (dirty[cat] && it.key in dirty[cat]) ? dirty[cat][it.key] : it.value;
  const nDirty = Object.values(dirty).reduce((a, o) => a + Object.keys(o).length, 0);
  const save = async () => {
    let n = 0;
    for (const cat of Object.keys(dirty)) {
      try { const r = await apiPut('/api/admin/settings/' + cat, { values: dirty[cat] }, { admin: true }); n += (r && r.updated) || 0; } catch { /* offline */ }
    }
    setSaved(n); setDirty({}); reload();
  };
  return <Card title="SETTINGS DB" sub={Object.keys(cats).length + ' cat'} onReload={reload}>
    <State e={e} loading={loading} n={Object.keys(cats).length} />
    <div style={{ maxHeight: 300, overflow: 'auto' }}>
      {Object.entries(cats).map(([cat, items]) => (
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
  const loadAB = () => apiGet(base + '/ab', { admin: true }).then((r) => setAb(r.ab || null)).catch(() => setAb(null));
  const doDiff = () => { if (a == null || b == null) return; setDiff('…'); apiGet(`${base}/diff?a=${a}&b=${b}`, { admin: true }).then((r) => setDiff(r.diff ?? '')).catch(() => setDiff(null)); };
  const doAB = () => { if (a == null || b == null) return; apiPost(`${base}/ab`, { a, b, split: 0.5 }, { admin: true }).then(loadAB).catch(() => {}); };
  const rollback = (vn) => apiPost(`${base}/rollback`, { version: vn }, { admin: true }).then(() => { setNote('rolled back to v' + vn); reload(); }).catch(() => {});
  const loadEdit = (vn) => apiGet(`${base}/version/${vn}`, { admin: true }).then((v) => { setEdit({ version: vn, content: v.content || '', message: '' }); setPreview(null); }).catch(() => {});
  const doPreview = () => { if (!edit) return; apiPost(`${base}/preview`, { proposed: edit.content }, { admin: true }).then(setPreview).catch(() => {}); };
  const doCommit = () => { if (!edit) return; apiPost(`${base}/commit`, { content: edit.content, message: edit.message || ('edit of v' + edit.version) }, { admin: true }).then((r) => { setNote('committed v' + (r.version?.version ?? '?')); setEdit(null); setPreview(null); setPick([]); reload(); }).catch(() => {}); };

  useEffect(() => { loadAB(); }, [agent]); // eslint-disable-line

  return <Card title="PROMPT VERSIONS" sub={agent + ' · ' + vers.length} onReload={reload}>
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
  const inp = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 11, flex: 1 };
  const create = () => { if (!name.trim()) return; apiPost('/api/rooms', { name: name.trim() }).then(() => { setName(''); reload(); }).catch(() => {}); };
  const send = () => { if (!sel || !msg.trim()) return; apiPost('/api/rooms/' + sel + '/message', { message: msg.trim() }).then(() => setMsg('')).catch(() => {}); };
  return <Card title="ROOMS" sub={rooms.length} onReload={reload}>
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
  </Card>;
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
    <Card title="network monitor" sub={d ? (clean ? 'local-only ✓' : 'VIOLATION') : null} onReload={reload}>
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
    <Card title="FEEDBACK · NPS" sub={d ? (nps == null ? 'no scores' : `NPS ${nps}`) : null} onReload={reload}>
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

const SECTIONS = [
  ['Memory', [DataSpacesPanel, LocalDocsPanel, NotesPanel, ReflectionPanel]],
  ['Trust', [KillSwitchPanel, KernelMetricsPanel, LoopBreakerPanel, NetworkMonitorPanel, SecretsPanel, CapabilitiesPanel, PairingPanel, InjectionScanPanel]],
  ['Interop', [A2AInboxPanel, MarketplacePanel]],
  ['Observe', [EvalPanel, ReviewPanel, APMPanel, FeedbackPanel]],
  ['Build', [StepGenPanel, SandboxPanel, TemplatesPanel]],
  ['Autonomy & Agents', [SchedulePanel, LearningPanel, SessionsPanel, HeartbeatPanel, TranscriptPanel, EscalationPanel]],
  ['Admin', [OAuthPanel, SettingsPanel, PromptsPanel, RoomsPanel, LMStudioPanel, AuthProfilesPanel]],
];

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
