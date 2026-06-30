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

function Card({ title, sub, onReload, children }: { title?: any; sub?: any; onReload?: any; children?: any }) {
  return (
    <div className="panel" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <span className="ttl">{title}</span>
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
    <Card title="AMBIENT CAPTURE" sub={status.d ? (enabled ? 'on' : 'off') + ' · ' + recs.length : null} onReload={() => { reload(); status.reload(); }}>
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
    <Card title="KNOWLEDGE GRAPH" sub={d ? `${ents.length} entities` : null} onReload={reload}>
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
    <Card title="SECURITY SKILLS" sub={d ? `${tactics.length} ATT&CK tactics` : null} onReload={reload}>
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
/* HUD-v3 B3 — Verification Fabric readiness board. Reads the real capability registry
   (GET /api/metrics/capabilities): the SEAM→WIRED→VERIFIED→GA ladder. Honesty contract —
   nothing is VERIFIED until a green reality-harness promotes it, so `harness_pending`
   renders "wired, not yet proven" rather than implying verification we can't back. */
export function ReadinessPanel() {
  const { d, e, loading, reload } = useApi('/api/metrics/capabilities');
  const bs = (d && d.by_state) || {};
  const caps = (d && d.capabilities) || [];
  const pending = d && d.harness_pending;
  const stateColor = (s) => (s === 'verified' || s === 'ga') ? 'var(--green)' : s === 'wired' ? 'var(--accent-light)' : 'var(--ink-3)';
  return (
    <Card title="VERIFICATION FABRIC" sub={d ? `${d.total} capabilities` : null} onReload={reload}>
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
      {caps.slice(0, 8).map((c, i) => (
        <Row key={i}>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{c.id}</span>
          <span style={{ marginLeft: 'auto' }}><Tag c={stateColor(c.state)}>{c.state}</Tag></span>
        </Row>
      ))}
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

/* HUD-v3 C6 (governance + posture half; loop-breaker already shipped). Two read-only
   Trust panels surfacing the security scorecard + packaged posture — neither had a
   control surface. Honesty: every number is the real suite/registry result. */
export function GovernancePanel() {
  const { d, e, loading, reload } = useApi('/api/security/governance');  // open (public scorecard)
  const suites = d ? [['injection', d.injection], ['harm', d.harm], ['owasp', d.owasp]].filter((x) => x[1]) : [];
  const pct = (s) => s && typeof s.score === 'number' ? Math.round(s.score * 100) + '%' : '—';
  return (
    <Card title="GOVERNANCE SCORECARD" sub={d ? (d.pass ? 'gate: pass' : 'gate: FAIL') : null} onReload={reload}>
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
    <Card title="SECURITY POSTURE" sub={d && d.guardrails ? `guardrails: ${d.guardrails.mode}` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row><span style={mono}>secrets at rest</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={sec.encrypted_at_rest ? 'var(--green)' : 'var(--red)'}>{sec.encrypted_at_rest ? 'encrypted' : 'plain'}</Tag>
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

/* HUD-v3 C8 (arena + quality-threshold; evals/review already shipped). Two Observe
   panels: the model arena leaderboard (read-only) + the answer-quality gate (read +
   admin set-threshold). Honesty: real ELO/scores; empty-state when no matches yet. */
export function ArenaPanel() {
  const { d, e, loading, reload } = useApi('/api/arena/leaderboard');  // open
  const rows = arr(d, 'leaderboard');
  return (
    <Card title="MODEL ARENA" sub={d ? `${rows.length} models` : null} onReload={reload}>
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
    <Card title="ANSWER QUALITY" sub={typeof st.avg_score === 'number' ? `avg ${st.avg_score.toFixed(2)}` : null} onReload={reload}>
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
    <Card title="MESH PEERS" sub={d ? `${peers.length} allowlisted` : null} onReload={reload}>
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
    <Card title="ORACLE SYNC" sub={d ? (d.watcher_running ? 'watching' : 'idle') + (d.last_checked ? ' · ' + d.last_checked : '') : null} onReload={reload}>
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
    <Card title="MIC SATELLITES" sub={d ? `${sats.length} paired` : null} onReload={reload}>
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
    <Card title="WORKFLOWS" sub={d ? `${rows.length} pipelines` : null} onReload={reload}>
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
  const svcs = arr(d, 'services') || Object.entries(d || {}).map(([k, v]: [string, any]) => ({ service: k, ...(v || {}) }));
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
  return <Card title="SETTINGS DB" sub={Object.keys(cats).length + ' cat'} onReload={reload}>
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

export function OnboardingPanel() {
  const { d, e, loading, reload } = useApi('/api/onboarding/wizard');
  const steps = (d && d.steps) || [];
  const done = new Set((d && d.completed) || []);
  return (
    <Card title="ONBOARDING" sub={d ? (d.complete ? 'complete ✓' : `${done.size}/${steps.length}`) : null} onReload={reload}>
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
    <Card title="DECISION INBOX"
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
    <Card title="MISSIONS" sub={d ? `${missions.length} workspaces` : null} onReload={reload}>
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
    <Card title="PER-AGENT AUTONOMY" sub={d ? `global: ${globalMode}` : null} onReload={reload}>
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
    <Card title="BACKUP · EXPORT · FORGET" sub={d ? `${backups.length} snapshots` : null} onReload={reload}>
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
    <Card title="TODAY" sub={d ? `${c.actions || 0} did · ${c.learnings || 0} learned` : null} onReload={reload}>
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
    <Card title="SKILL HISTORY" sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} events` : 'disabled') : null} onReload={reload}>
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
    <Card title="MEDIA GALLERY" sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} items` : 'disabled') : null} onReload={reload}>
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
    <Card title="PROVENANCE" sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} recs · ${(d.stats && d.stats.runs) || 0} runs` : 'disabled') : null} onReload={reload}>
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
    <Card title="SEND RATE LIMITS" sub={d ? (enabled ? `cap ${(d && d.global_cap) || 0}/${(d && d.window_seconds) || 60}s` : 'unlimited') : null} onReload={reload}>
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

/* H23.2 — recorded model fingerprints (GET /api/models/info, admin): the {id, version,
   quant, sha256} of each model build seen, so a run is reproducible to the exact model.
   Honesty contract: when JARVIS_MODEL_INFO is off the endpoint reports enabled:false and
   the panel says so (nothing is recorded by default). */
export function ModelInfoPanel() {
  const { d, e, loading, reload } = useApi('/api/models/info', true, true);
  const enabled = !!(d && d.enabled);
  const models = arr(d && d.models);
  return (
    <Card title="MODEL FINGERPRINTS" sub={d ? (enabled ? `${(d.stats && d.stats.total) || 0} models` : 'disabled') : null} onReload={reload}>
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

const SECTIONS: Array<[string, Array<() => any>]> = [
  ['Memory', [DataSpacesPanel, LocalDocsPanel, NotesPanel, KgPanel, CapturePanel, ReflectionPanel, ProvenancePanel]],
  ['Trust', [KillSwitchPanel, KernelMetricsPanel, ReadinessPanel, LoopBreakerPanel, GovernancePanel, PosturePanel, SecuritySkillsPanel, NetworkMonitorPanel, CommsRatePanel, SecretsPanel, CapabilitiesPanel, PairingPanel, InjectionScanPanel]],
  ['Interop', [A2AInboxPanel, MeshPeersPanel, SatellitesPanel, OraclePanel, MarketplacePanel, SkillHistoryPanel]],
  ['Observe', [OnboardingPanel, EvalPanel, ReviewPanel, ArenaPanel, QualityPanel, APMPanel, ModelInfoPanel, FeedbackPanel]],
  ['Build', [WorkflowsPanel, StepGenPanel, SandboxPanel, TemplatesPanel, MediaGalleryPanel]],
  ['Autonomy & Agents', [DecisionInboxPanel, MissionsPanel, AgentAutonomyPanel, TodayPanel, SchedulePanel, LearningPanel, SessionsPanel, HeartbeatPanel, TranscriptPanel, EscalationPanel]],
  ['Admin', [BackupPanel, OAuthPanel, SettingsPanel, PromptsPanel, RoomsPanel, LMStudioPanel, AuthProfilesPanel]],
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
