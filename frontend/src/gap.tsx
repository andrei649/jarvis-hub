// @ts-nocheck
/* HUD v2 · P4c — the net-new gap surfaces from the §5b/§5c audit, hosted in a
   Console overlay (mirrors v1 tools.js). Each panel fetches its real endpoint and
   degrades to an offline/empty state — never blocks. Admin-guarded calls work on
   localhost; on a network they surface the 401 via the client's token prompt. */
import React, { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiPut, apiDelete } from './api/client';

function useApi(path, auto = true) {
  const [d, setD] = useState(null);
  const [e, setE] = useState(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    setLoading(true);
    apiGet(path).then((r) => { setD(r); setE(null); }).catch((err) => setE(err?.message || 'offline')).finally(() => setLoading(false));
  }, [path]);
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

/* ── Trust / Security ───────────────────────────────────── */
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
      <Btn onClick={() => act('/api/security/kill-switch', { engage: !halted, scope: 'global', reason: 'hud' }, reload)}>{halted ? 'disengage' : 'HALT ALL'}</Btn></Row>
  </Card>;
}
function CapabilitiesPanel() {
  const [caps, setCaps] = useState('fs.read,memory.write'); const [out, setOut] = useState(null);
  return <Card title="CAPABILITY TOKENS">
    <input value={caps} onChange={(e) => setCaps(e.target.value)} style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, ...mono }} />
    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
      <button className="tool-btn" onClick={() => act('/api/security/capabilities/issue', { capabilities: caps.split(',').map((s) => s.trim()) }, (r) => setOut(JSON.stringify(r)))}>issue</button>
    </div>
    {out && <pre style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', whiteSpace: 'pre-wrap', marginTop: 6 }}>{out.slice(0, 200)}</pre>}
  </Card>;
}

/* ── Interop ───────────────────────────────────────────── */
function A2AInboxPanel() {
  const { d, e, loading, reload } = useApi('/api/a2a/inbox');
  const items = arr(d, 'inbox', 'tasks');
  return <Card title="A2A APPROVAL INBOX" sub={items.length} onReload={reload}>
    <State e={e} loading={loading} n={items.length} />
    {items.slice(0, 10).map((it, i) => <Row key={i}><span style={mono}>{it.peer || it.from || '?'}</span><span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{(it.task || it.summary || '').slice(0, 40)}</span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
        <button className="tool-btn" onClick={() => act(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approved: true }, reload)}>✓</button>
        <button className="tool-btn" onClick={() => act(`/api/a2a/inbox/${it.id || it.task_id}/decide`, { approved: false }, reload)}>✕</button>
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
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
        <Tag c={s.signed ? 'var(--green)' : 'var(--amber)'}>{s.signed ? 'signed' : 'unsigned'}</Tag>
        <Tag c={s.review_status === 'approved' ? 'var(--green)' : s.review_status === 'rejected' ? 'var(--red)' : 'var(--amber)'}>{s.review_status || 'pending'}</Tag>
      </span></Row>)}
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>signed + moderated (anti-ClawHub, H12.12)</div>
  </Card>;
}

/* ── Observe / Eval ────────────────────────────────────── */
function EvalPanel() {
  const { d, e, loading, reload } = useApi('/api/eval/datasets');
  const ds = arr(d, 'datasets');
  return <Card title="EVAL DATASETS" sub={ds.length} onReload={reload}>
    <State e={e} loading={loading} n={ds.length} />
    {ds.slice(0, 8).map((x, i) => <Row key={i}><span style={mono}>{x.name}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>v{x.version} · {x.cases ?? x.count ?? '?'}</span><Btn onClick={() => act('/api/eval/datasets/run', { name: x.name }, reload)}>run</Btn></Row>)}
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

/* ── Agents ops ────────────────────────────────────────── */
function LearningPanel() {
  const { d, e, loading, reload } = useApi('/learning');
  const cands = arr(d, 'promotion_candidates', 'candidates');
  return <Card title="LEARNING · BENCH" sub={cands.length} onReload={reload}>
    <State e={e} loading={loading} n={cands.length} />
    {cands.slice(0, 8).map((c, i) => <Row key={i}><span style={mono}>{c.agent || c.id || c}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{c.trigger || c.uses || ''}</span></Row>)}
    <button className="tool-btn" style={{ marginTop: 6 }} onClick={() => act('/api/learning/propose', {}, reload)}>propose promotions</button>
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
  const { d, e, loading, reload } = useApi('/api/admin/prompts/' + agent + '/history');
  const vers = arr(d, 'history', 'versions');
  return <Card title="PROMPT VERSIONS" sub={agent} onReload={reload}>
    <input value={agent} onChange={(ev) => setAgent(ev.target.value)} style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, marginBottom: 6 }} />
    <State e={e} loading={loading} n={vers.length} />
    {vers.slice(0, 8).map((v, i) => <Row key={i}><span style={mono}>v{v.version ?? i}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{(v.message || v.author || '').slice(0, 28)}</span></Row>)}
  </Card>;
}
function RoomsPanel() {
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

const SECTIONS = [
  ['Memory', [DataSpacesPanel, LocalDocsPanel, NotesPanel]],
  ['Trust', [KillSwitchPanel, SecretsPanel, CapabilitiesPanel]],
  ['Interop', [A2AInboxPanel, MarketplacePanel]],
  ['Observe', [EvalPanel, ReviewPanel, APMPanel]],
  ['Autonomy & Agents', [SchedulePanel, LearningPanel, SessionsPanel]],
  ['Admin', [OAuthPanel, SettingsPanel, PromptsPanel, RoomsPanel]],
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
