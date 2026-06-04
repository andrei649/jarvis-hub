'use strict';
/* tools.js — the Console: a full-screen overlay that is the discoverable home
   for every backend feature (HUD redesign #6). Opened from the ▦ button / ⌘K.
   Each tool is a compact panel that calls existing endpoints. h/useState etc.
   are global lexical bindings from components.js; api()/adminFetch() from console.js. */

(function () {

  /* ── shared hooks/widgets ──────────────────────────────────────────────── */
  function useApi(url, auto) {
    const _s = useState({ loading: !!auto }), s = _s[0], set = _s[1];
    const reload = useCallback(function () {
      set({ loading: true });
      api(url).then(function (d) { set({ data: d }); }).catch(function (e) { set({ err: String(e) }); });
    }, [url]);
    useEffect(function () { if (auto) reload(); }, [url]);
    return [s, reload];
  }

  function Tool(title, hint, body, actions) {
    return h('div', { className: 'tool' },
      h('div', { className: 'tool-head' },
        h('div', null, h('div', { className: 'tool-title' }, title),
          hint && h('div', { className: 'tool-hint' }, hint)),
        h('div', { className: 'tool-actions' }, actions)),
      h('div', { className: 'tool-body' }, body));
  }
  function Btn(label, onClick, kind) { return h('button', { className: 'tool-btn ' + (kind || ''), onClick: onClick }, label); }
  function Pre(obj) { return h('pre', { className: 'tool-pre' }, typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2)); }
  function Empty(msg) { return h('div', { className: 'tool-empty' }, msg || 'No data yet.'); }
  function Err(e) { return h('div', { className: 'tool-err' }, '⚠ ' + e); }

  /* ── Observability ─────────────────────────────────────────────────────── */
  function HealthPanel() {
    const _ = useApi('/api/health/components', true), s = _[0], reload = _[1];
    let body;
    if (s.err) body = Err(s.err); else if (s.loading) body = Empty('Loading…');
    else body = h('div', null,
      h('div', { className: 'tool-stat' }, s.data.summary),
      h('div', { className: 'tool-grid2' }, Object.entries(s.data.components || {}).map(function (kv) {
        return h('div', { key: kv[0], className: 'tool-chip ' + (kv[1] === 'ok' ? 'ok' : 'bad') }, kv[0] + ' · ' + kv[1]);
      })));
    return Tool('Component Health', 'Which optional components initialized', body, Btn('↻', reload));
  }

  function QualityPanel() {
    const _ = useApi('/api/quality', true), s = _[0], reload = _[1];
    const _t = useState(''), thr = _t[0], setThr = _t[1];
    function setThreshold() {
      adminFetch('/api/quality/threshold', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threshold: parseFloat(thr) }) })
        .then(reload).catch(function (e) { alert(e.message); });
    }
    let body;
    if (s.err) body = Err(s.err); else if (s.loading) body = Empty('Loading…');
    else body = h('div', null, Pre(s.data.stats || {}),
      s.data.alert && s.data.alert.alerting && h('div', { className: 'tool-err' }, 'ALERT: avg below threshold'));
    return Tool('Live Quality Monitor', 'Rolling per-request quality + alert', body,
      h('div', { className: 'tool-actions' },
        h('input', { className: 'tool-input', style: { width: '70px' }, placeholder: 'thr', value: thr, onChange: function (e) { setThr(e.target.value); } }),
        Btn('Set threshold', setThreshold, 'admin'), Btn('↻', reload)));
  }

  function ReviewPanel() {
    const _ = useApi('/api/review/queue?status=pending', true), s = _[0], reload = _[1];
    function vote(id, verdict) {
      api('/api/review/' + id + '/vote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ verdict: verdict }) }).then(reload).catch(function (e) { alert(e); });
    }
    let body;
    if (s.err) body = Err(s.err); else if (s.loading) body = Empty('Loading…');
    else { const items = (s.data.items || []); body = items.length ? items.map(function (it) {
      return h('div', { key: it.id, className: 'tool-card' },
        h('div', { className: 'tool-card-text' }, (it.text_preview || '(no preview)') + ' · score ' + (it.score == null ? '—' : it.score)),
        h('div', { className: 'tool-actions' }, Btn('👍', function () { vote(it.id, 'up'); }), Btn('👎', function () { vote(it.id, 'down'); })));
    }) : Empty('Review queue empty.'); }
    return Tool('Human Review Queue', 'Flagged traces → rubric vote → dataset', body, Btn('↻', reload));
  }

  function ActionsPanel() {
    const _ = useApi('/api/actions/pending', true), s = _[0], reload = _[1];
    function decide(id, ok) {
      adminFetch('/api/actions/' + id + '/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved: ok }) }).then(reload).catch(function (e) { alert(e.message); });
    }
    let body;
    if (s.err) body = Err(s.err); else if (s.loading) body = Empty('Loading…');
    else { const acts = (s.data.actions || []); body = acts.length ? acts.map(function (a) {
      return h('div', { key: a.id, className: 'tool-card' },
        h('div', { className: 'tool-card-text' }, (a.summary || a.tool) + (a.preview && a.preview.irreversible ? ' · ⚠ irreversible' : '')),
        h('div', { className: 'tool-actions' }, Btn('Approve', function () { decide(a.id, true); }, 'ok'), Btn('Reject', function () { decide(a.id, false); }, 'bad')));
    }) : Empty('No pending tool-calls.'); }
    return Tool('Action Approvals', 'Pending tool-calls (admin)', body, Btn('↻', reload));
  }

  /* ── Arena ─────────────────────────────────────────────────────────────── */
  function ArenaPanel(props) {
    const _q = useState(''), q = _q[0], setQ = _q[1];
    const _ag = useState(''), agStr = _ag[0], setAg = _ag[1];
    const _m = useState(null), match = _m[0], setMatch = _m[1];
    const _lb = useApi('/api/arena/leaderboard', true), lb = _lb[0], reloadLb = _lb[1];
    function run() {
      const agentsList = agStr.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
      if (!q || agentsList.length < 2) { alert('Enter a query and ≥2 agent ids (comma-separated).'); return; }
      api('/api/arena/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: q, agents: agentsList }) })
        .then(function (d) { setMatch(d.match); }).catch(function (e) { alert(e); });
    }
    function vote(label) {
      api('/api/arena/vote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ match_id: match.id, winner: label }) })
        .then(function (d) { setMatch(d.match); reloadLb(); }).catch(function (e) { alert(e); });
    }
    const body = h('div', null,
      h('div', { className: 'tool-form' },
        h('input', { className: 'tool-input', placeholder: 'query', value: q, onChange: function (e) { setQ(e.target.value); } }),
        h('input', { className: 'tool-input', placeholder: 'agent ids, comma-sep (≥2)', value: agStr, onChange: function (e) { setAg(e.target.value); } }),
        Btn('Run blind match', run, 'ok')),
      match && h('div', { className: 'tool-card' },
        match.entries.map(function (en) {
          return h('div', { key: en.label, className: 'tool-card' },
            h('b', null, en.label + ': '), h('span', null, (en.response || '').slice(0, 240)),
            !match.voted && h('div', null, Btn('Vote ' + en.label, function () { vote(en.label); })));
        }),
        match.voted && h('div', { className: 'tool-stat' }, 'Winner revealed: ' + (match.winner_model || match.winner_label))),
      h('div', { className: 'tool-group-title' }, 'Leaderboard'),
      lb.data ? Pre((lb.data.leaderboard || []).map(function (r) { return r.model + '  elo ' + r.elo + '  win% ' + (r.win_rate == null ? '—' : r.win_rate); }).join('\n') || '(empty)') : Empty('…'));
    return Tool('Model Arena', 'Blind compare 2+ agents → vote → ELO', body, Btn('↻', reloadLb));
  }

  /* ── Workspace: Notes + Rooms ──────────────────────────────────────────── */
  function NotesPanel() {
    const _ = useApi('/api/notes', true), s = _[0], reload = _[1];
    const _x = useState(null), edit = _x[0], setEdit = _x[1];
    const content = edit == null ? (s.data ? s.data.content : '') : edit;
    function save() { api('/api/notes', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content }) }).then(function () { setEdit(null); reload(); }).catch(function (e) { alert(e); }); }
    function rewrite() { api('/api/notes/rewrite', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ save: true }) }).then(function (d) { setEdit(d.rewritten); reload(); }).catch(function (e) { alert(e); }); }
    const body = s.err ? Err(s.err) : h('textarea', { className: 'tool-input', style: { width: '100%', minHeight: '160px' }, value: content, onChange: function (e) { setEdit(e.target.value); } });
    return Tool('Conversation Notes', 'Persistent context injected into every turn', body,
      h('div', { className: 'tool-actions' }, Btn('Save', save, 'ok'), Btn('Rewrite with AI', rewrite), Btn('↻', reload)));
  }

  function RoomsPanel() {
    const _ = useApi('/api/rooms', true), s = _[0], reload = _[1];
    const _n = useState(''), name = _n[0], setName = _n[1];
    const _sel = useState(null), sel = _sel[0], setSel = _sel[1];
    const _h = useState([]), hist = _h[0], setHist = _h[1];
    const _m = useState(''), msg = _m[0], setMsg = _m[1];
    function create() { if (!name) return; api('/api/rooms', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name }) }).then(function () { setName(''); reload(); }).catch(function (e) { alert(e); }); }
    function openRoom(r) { setSel(r); api('/api/rooms/' + r.id + '/history').then(function (d) { setHist(d.history || []); }).catch(function () {}); }
    function send() { if (!sel || !msg) return; api('/api/rooms/' + sel.id + '/message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) }).then(function () { setMsg(''); openRoom(sel); }).catch(function (e) { alert(e); }); }
    const rooms = s.data ? (s.data.rooms || []) : [];
    const body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'new room name', value: name, onChange: function (e) { setName(e.target.value); } }), Btn('Create', create, 'ok')),
      rooms.length ? rooms.map(function (r) { return h('button', { key: r.id, className: 'console-link ' + (sel && sel.id === r.id ? 'is-active' : ''), onClick: function () { openRoom(r); } }, '# ' + r.name); }) : Empty('No rooms yet.'),
      sel && h('div', { className: 'tool-card' },
        h('div', { className: 'tool-group-title' }, '# ' + sel.name + ' · @mention an agent'),
        hist.map(function (m, i) { return h('div', { key: i, className: 'tool-card-text' }, (m.role === 'user' ? 'you' : (m.agent || 'jarvis')) + ': ' + m.text); }),
        h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'message (@agent …)', value: msg, onChange: function (e) { setMsg(e.target.value); } }), Btn('Send', send, 'ok'))));
    return Tool('Chat Rooms', 'Themed channels · @mention agents', body, Btn('↻', reload));
  }

  /* ── Autonomy: schedule, dry-run, escalation, learning ─────────────────── */
  function SchedulePanel() {
    const _r = useState(null), res = _r[0], setRes = _r[1];
    const _t = useState(''), text = _t[0], setText = _t[1];
    function parse() { fetch('/api/schedule/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text }) }).then(function (r) { return r.json(); }).then(setRes).catch(function (e) { setRes({ error: String(e) }); }); }
    const body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'e.g. every weekday at 7am', value: text, onChange: function (e) { setText(e.target.value); } }), Btn('Parse → cron', parse, 'ok')),
      res && (res.ok ? h('div', { className: 'tool-stat' }, res.cron + '   (' + res.description + ')') : Err(res.error || 'unparseable')));
    return Tool('NL Scheduling', 'Plain language → cron', body, null);
  }

  function DryRunPanel() {
    const _k = useState('send_email'), kind = _k[0], setKind = _k[1];
    const _t = useState('Reply to Bob'), title = _t[0], setTitle = _t[1];
    const _r = useState(null), res = _r[0], setRes = _r[1];
    function preview() { fetch('/api/autonomy/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: kind, title: title, payload: {} }) }).then(function (r) { return r.json(); }).then(setRes).catch(function (e) { setRes({ error: String(e) }); }); }
    const body = h('div', null,
      h('div', { className: 'tool-form' },
        h('input', { className: 'tool-input', placeholder: 'action kind', value: kind, onChange: function (e) { setKind(e.target.value); } }),
        h('input', { className: 'tool-input', placeholder: 'title', value: title, onChange: function (e) { setTitle(e.target.value); } }),
        Btn('Preview', preview, 'ok')),
      res && Pre(res));
    return Tool('Dry-Run Preview', 'What an action WOULD do + irreversibility', body, null);
  }

  function EscalationPanel() {
    const _ = useApi('/api/autonomy/escalation/targets', true), s = _[0], reload = _[1];
    const _m = useState(''), msg = _m[0], setMsg = _m[1];
    function send() { adminFetch('/api/autonomy/escalate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) }).then(function (d) { alert('delivered: ' + ((d.delivered || []).join(', ') || 'none')); }).catch(function (e) { alert(e.message); }); }
    const body = h('div', null,
      s.data && h('div', { className: 'tool-stat' }, 'targets: ' + ((s.data.targets || []).join(', ') || 'none')),
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'escalation message', value: msg, onChange: function (e) { setMsg(e.target.value); } }), Btn('Escalate', send, 'admin')));
    return Tool('Escalation', 'Deliver to governed channels (admin)', body, Btn('↻', reload));
  }

  function LearningPanel() {
    const _r = useState(null), res = _r[0], setRes = _r[1];
    function propose() { adminFetch('/api/learning/propose', { method: 'POST' }).then(setRes).catch(function (e) { alert(e.message); }); }
    const body = h('div', null,
      Btn('Propose promotions now', propose, 'admin'),
      res && h('div', { className: 'tool-card' }, 'Proposed ' + (res.count || 0) + ' promotion(s) → decision inbox.', Pre(res.proposed || [])));
    return Tool('Learning Loop', 'Propose agent promotions → decision inbox (admin)', body, null);
  }

  /* ── Memory ────────────────────────────────────────────────────────────── */
  function KGPanel() {
    const _f = useState(null), facts = _f[0], setFacts = _f[1];
    const _d = useState(''), date = _d[0], setDate = _d[1];
    const _s = useState(''), subj = _s[0], setSubj = _s[1];
    const _p = useState(''), pred = _p[0], setPred = _p[1];
    const _o = useState(''), obj = _o[0], setObj = _o[1];
    function load() { fetch('/api/kg/facts/as-of?date=' + encodeURIComponent(date || '')).then(function (r) { return r.json(); }).then(function (d) { setFacts(d.facts || []); }).catch(function () { setFacts([]); }); }
    useEffect(function () { load(); }, []);
    function add() {
      if (!subj || !pred || !obj) return;
      api('/api/kg/facts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subject: subj, predicate: pred, object: obj }) })
        .then(function () { setSubj(''); setPred(''); setObj(''); load(); }).catch(function (e) { alert(e); });
    }
    const body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'as-of date YYYY-MM-DD (blank = now)', value: date, onChange: function (e) { setDate(e.target.value); } }), Btn('Recall', load, 'ok')),
      h('div', { className: 'tool-form' },
        h('input', { className: 'tool-input', placeholder: 'subject', value: subj, onChange: function (e) { setSubj(e.target.value); } }),
        h('input', { className: 'tool-input', placeholder: 'predicate', value: pred, onChange: function (e) { setPred(e.target.value); } }),
        h('input', { className: 'tool-input', placeholder: 'object', value: obj, onChange: function (e) { setObj(e.target.value); } }),
        Btn('Add fact', add)),
      facts == null ? Empty('…') : (facts.length ? facts.map(function (f, i) { return h('div', { key: i, className: 'tool-card-text' }, f.subject + ' · ' + f.predicate + ' · ' + f.object); }) : Empty('No facts.')));
    return Tool('Knowledge Graph', 'Bi-temporal facts · recall as-of a date', body, null);
  }

  function EntitiesPanel() {
    const _ = useApi('/api/memory/entities', true), s = _[0], reload = _[1];
    let body;
    if (s.err) body = Err(s.err); else if (s.loading) body = Empty('Loading…');
    else { const e = s.data.entities || []; body = e.length ? e.map(function (x, i) { return h('div', { key: i, className: 'tool-card-text' }, x.name + ' · ' + x.type + ' · ' + x.mentions + ' mentions'); }) : Empty('No entities.'); }
    return Tool('Entities', 'People · projects · places · concepts', body, Btn('↻', reload));
  }

  function DecayPanel() {
    const _ = useApi('/api/memory/decay/ranking', true), s = _[0], reload = _[1];
    const body = s.err ? Err(s.err) : (s.loading ? Empty('Loading…') : Pre((s.data.ranking || []).slice(0, 30)));
    return Tool('Decay & Forgetting', 'ACT-R activation ranking (read-only)', body, Btn('↻', reload));
  }

  function MemorySearchPanel() {
    const _q = useState(''), q = _q[0], setQ = _q[1];
    const _r = useState(null), res = _r[0], setRes = _r[1];
    function search() { fetch('/api/memory/search?q=' + encodeURIComponent(q) + '&top_k=8').then(function (r) { return r.json(); }).then(setRes).catch(function (e) { setRes({ error: String(e) }); }); }
    const body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'search memory…', value: q, onChange: function (e) { setQ(e.target.value); } }), Btn('Search', search, 'ok')),
      res && Pre(res));
    return Tool('Memory Search', 'Vector recall over stored memory', body, null);
  }

  /* ── Tools / Dev ───────────────────────────────────────────────────────── */
  function WidgetsPanel() {
    const _d = useState(null), data = _d[0], setData = _d[1];
    const _t = useState(''), title = _t[0], setTitle = _t[1];
    function load() { adminFetch('/api/admin/widgets').then(function (d) { setData(d.widgets || []); }).catch(function (e) { setData({ err: e.message }); }); }
    useEffect(function () { load(); }, []);
    function create() { adminFetch('/api/admin/widgets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title || 'Jarvis' }) }).then(function () { setTitle(''); load(); }).catch(function (e) { alert(e.message); }); }
    function del(tok) { adminFetch('/api/admin/widgets/' + tok, { method: 'DELETE' }).then(load).catch(function (e) { alert(e.message); }); }
    let body;
    if (data && data.err) body = Err(data.err);
    else if (data == null) body = Empty('Loading…');
    else body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'widget title', value: title, onChange: function (e) { setTitle(e.target.value); } }), Btn('Issue token', create, 'admin')),
      data.length ? data.map(function (w) { return h('div', { key: w.token, className: 'tool-card' }, h('span', { className: 'tool-card-text' }, (w.title || 'Jarvis') + ' · embed /api/widget/' + (w.token || '…')), Btn('Revoke', function () { del(w.token); }, 'bad')); }) : Empty('No widgets.'));
    return Tool('Embeddable Widgets', 'Per-site chat widget tokens (admin)', body, Btn('↻', load));
  }

  function GrammarPanel() {
    const _t = useState('{\n  "type": "object",\n  "properties": {"city": {"type": "string"}},\n  "required": ["city"]\n}'), txt = _t[0], setTxt = _t[1];
    const _o = useState(''), out = _o[0], setOut = _o[1];
    function gen() {
      let schema; try { schema = JSON.parse(txt); } catch (e) { setOut('invalid JSON: ' + e); return; }
      fetch('/api/llm/grammar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ schema: schema }) }).then(function (r) { return r.json(); }).then(function (d) { setOut(d.gbnf || d.error || ''); }).catch(function (e) { setOut(String(e)); });
    }
    const body = h('div', null,
      h('textarea', { className: 'tool-input', style: { width: '100%', minHeight: '120px', fontFamily: 'monospace' }, value: txt, onChange: function (e) { setTxt(e.target.value); } }),
      h('div', { style: { margin: '6px 0' } }, Btn('Generate GBNF', gen, 'ok')), out && Pre(out));
    return Tool('Constrained Decoding', 'JSON schema → GBNF grammar', body, null);
  }

  function MCPPanel() {
    const _ = useApi('/api/mcp/server', true), s = _[0], reload = _[1];
    const _t = useState(''), tok = _t[0], setTok = _t[1];
    function issue() { adminFetch('/api/mcp/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scopes: ['mcp'] }) }).then(function (d) { setTok(d.token || ''); }).catch(function (e) { alert(e.message); }); }
    const body = h('div', null,
      s.err ? Err(s.err) : (s.loading ? Empty('…') : Pre(s.data)),
      h('div', { style: { margin: '6px 0' } }, Btn('Issue local token (admin)', issue, 'admin')),
      tok && Pre(tok));
    return Tool('MCP Server', 'Expose agents as governed MCP tools', body, Btn('↻', reload));
  }

  function SecretsPanel() {
    const _n = useState(null), names = _n[0], setNames = _n[1];
    const _k = useState(''), nm = _k[0], setNm = _k[1];
    const _v = useState(''), val = _v[0], setVal = _v[1];
    function load() { adminFetch('/api/secrets/broker').then(function (d) { setNames(d.names || []); }).catch(function (e) { setNames({ err: e.message }); }); }
    useEffect(function () { load(); }, []);
    function add() { if (!nm || !val) return; adminFetch('/api/secrets/broker', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: nm, value: val }) }).then(function () { setNm(''); setVal(''); load(); }).catch(function (e) { alert(e.message); }); }
    function del(name) { adminFetch('/api/secrets/broker/' + encodeURIComponent(name), { method: 'DELETE' }).then(load).catch(function (e) { alert(e.message); }); }
    let body;
    if (names && names.err) body = Err(names.err);
    else if (names == null) body = Empty('Loading…');
    else body = h('div', null,
      h('div', { className: 'tool-form' }, h('input', { className: 'tool-input', placeholder: 'name', value: nm, onChange: function (e) { setNm(e.target.value); } }), h('input', { className: 'tool-input', type: 'password', placeholder: 'value', value: val, onChange: function (e) { setVal(e.target.value); } }), Btn('Store', add, 'admin')),
      h('div', { className: 'tool-hint' }, 'Reference {{secret:NAME}} in agent configs — value injected only at action time, behind approval.'),
      names.length ? names.map(function (name) { return h('div', { key: name, className: 'tool-card' }, h('span', { className: 'tool-card-text' }, '🔑 ' + name), Btn('Delete', function () { del(name); }, 'bad')); }) : Empty('No secrets stored.'));
    return Tool('Secret Broker', 'JIT credential injection — names only, never values', body, Btn('↻', load));
  }

  function WebhooksPanel() {
    const _ = useApi('/api/webhooks', true), s = _[0], reload = _[1];
    const _t = useState('jarvis'), target = _t[0], setTarget = _t[1];
    const _sg = useState(false), signed = _sg[0], setSigned = _sg[1];
    const _c = useState(null), created = _c[0], setCreated = _c[1];
    function create() { api('/api/webhooks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: target, signed: signed }) }).then(function (d) { setCreated(d); reload(); }).catch(function (e) { alert(e); }); }
    function del(id) { fetch('/api/webhooks/' + id, { method: 'DELETE' }).then(reload).catch(function () {}); }
    const hooks = s.data ? (s.data.webhooks || []) : [];
    const body = h('div', null,
      h('div', { className: 'tool-form' },
        h('input', { className: 'tool-input', placeholder: 'target agent', value: target, onChange: function (e) { setTarget(e.target.value); } }),
        h('label', { className: 'tool-hint' }, h('input', { type: 'checkbox', checked: signed, onChange: function (e) { setSigned(e.target.checked); } }), ' HMAC signed'),
        Btn('Create', create, 'ok')),
      created && h('div', { className: 'tool-card' }, 'token: ' + (created.token || '') + (created.signing_secret ? (' · secret: ' + created.signing_secret) : ''), h('div', { className: 'tool-hint' }, '(shown once)')),
      hooks.length ? hooks.map(function (w) { return h('div', { key: w.id, className: 'tool-card' }, h('span', { className: 'tool-card-text' }, (w.name || w.target) + ' → POST /api/webhooks/' + w.id + (w.signed ? ' 🔏' : '')), Btn('Delete', function () { del(w.id); }, 'bad')); }) : Empty('No webhooks.'));
    return Tool('Webhooks', 'Inbound triggers (optionally HMAC-signed)', body, Btn('↻', reload));
  }

  /* ── tool registry ─────────────────────────────────────────────────────── */
  const TOOLS = [
    { id: 'health', group: 'Observability', label: 'Component Health', render: function (p) { return h(HealthPanel, p); } },
    { id: 'quality', group: 'Observability', label: 'Quality Monitor', render: function (p) { return h(QualityPanel, p); } },
    { id: 'review', group: 'Observability', label: 'Review Queue', render: function (p) { return h(ReviewPanel, p); } },
    { id: 'arena', group: 'Quality', label: 'Model Arena', render: function (p) { return h(ArenaPanel, p); } },
    { id: 'actions', group: 'Autonomy', label: 'Action Approvals', render: function (p) { return h(ActionsPanel, p); } },
    { id: 'schedule', group: 'Autonomy', label: 'NL Scheduling', render: function (p) { return h(SchedulePanel, p); } },
    { id: 'dryrun', group: 'Autonomy', label: 'Dry-Run Preview', render: function (p) { return h(DryRunPanel, p); } },
    { id: 'escalation', group: 'Autonomy', label: 'Escalation', render: function (p) { return h(EscalationPanel, p); } },
    { id: 'learning', group: 'Autonomy', label: 'Learning Loop', render: function (p) { return h(LearningPanel, p); } },
    { id: 'notes', group: 'Workspace', label: 'Conversation Notes', render: function (p) { return h(NotesPanel, p); } },
    { id: 'rooms', group: 'Workspace', label: 'Chat Rooms', render: function (p) { return h(RoomsPanel, p); } },
    { id: 'memsearch', group: 'Memory', label: 'Memory Search', render: function (p) { return h(MemorySearchPanel, p); } },
    { id: 'kg', group: 'Memory', label: 'Knowledge Graph', render: function (p) { return h(KGPanel, p); } },
    { id: 'entities', group: 'Memory', label: 'Entities', render: function (p) { return h(EntitiesPanel, p); } },
    { id: 'decay', group: 'Memory', label: 'Decay & Forgetting', render: function (p) { return h(DecayPanel, p); } },
    { id: 'widgets', group: 'Tools', label: 'Embeddable Widgets', render: function (p) { return h(WidgetsPanel, p); } },
    { id: 'grammar', group: 'Tools', label: 'Constrained Decoding', render: function (p) { return h(GrammarPanel, p); } },
    { id: 'mcp', group: 'Tools', label: 'MCP Server', render: function (p) { return h(MCPPanel, p); } },
    { id: 'secrets', group: 'Tools', label: 'Secret Broker', render: function (p) { return h(SecretsPanel, p); } },
    { id: 'webhooks', group: 'Tools', label: 'Webhooks', render: function (p) { return h(WebhooksPanel, p); } },
  ];
  window.JARVIS_TOOLS = TOOLS;

  window.ConsoleOverlay = function ConsoleOverlay(props) {
    if (!props.open) return null;
    const _sel = useState(TOOLS[0].id), sel = _sel[0], setSel = _sel[1];
    const groups = {};
    TOOLS.forEach(function (t) { (groups[t.group] = groups[t.group] || []).push(t); });
    const active = TOOLS.find(function (t) { return t.id === sel; }) || TOOLS[0];
    return h('div', { className: 'console-backdrop', onClick: function (e) { if (e.target.classList.contains('console-backdrop')) props.onClose(); } },
      h('div', { className: 'console', role: 'dialog', 'aria-label': 'Console' },
        h('div', { className: 'console-nav' },
          h('div', { className: 'console-brand' }, '▦ Console',
            h('button', { className: 'console-x', onClick: props.onClose, title: 'Close (Esc)' }, '×')),
          Object.keys(groups).map(function (g) {
            return h('div', { key: g, className: 'console-group' },
              h('div', { className: 'console-group-title' }, g),
              groups[g].map(function (t) {
                return h('button', { key: t.id, className: 'console-link ' + (t.id === sel ? 'is-active' : ''), onClick: function () { setSel(t.id); } }, t.label);
              }));
          })),
        h('div', { className: 'console-content' }, active.render({ agents: props.agents }))));
  };
})();
