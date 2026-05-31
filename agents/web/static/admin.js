'use strict';
/* admin.js — Jarvis Hub Admin Panel (Apple Settings style) */

/* h, useState, useEffect, useRef, useMemo, useCallback — from components.js */

/* ── SVG icons per category ─────────────────────────────────── */

const ICONS = {
  general: h('svg', {viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:10,cy:10,r:7}),
    h('circle',{cx:10,cy:10,r:3}),
    h('line',{x1:10,y1:1,x2:10,y2:4}),
    h('line',{x1:10,y1:16,x2:10,y2:19}),
    h('line',{x1:1,y1:10,x2:4,y2:10}),
    h('line',{x1:16,y1:10,x2:19,y2:10}),
  ),
  llm: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:3,y:3,width:14,height:14,rx:3}),
    h('circle',{cx:10,cy:10,r:3}),
    h('path',{d:'M10 13v4M10 3v4M13 10h4M3 10h4'}),
  ),
  agents: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:7,cy:7,r:3}),
    h('circle',{cx:13,cy:7,r:3}),
    h('circle',{cx:7,cy:14,r:3}),
    h('circle',{cx:13,cy:14,r:3}),
  ),
  plugins: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M5 10h10M10 5v10'}),
    h('circle',{cx:10,cy:10,r:8}),
  ),
  voice: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:8,y:1,width:4,height:11,rx:2}),
    h('path',{d:'M4 9a6 6 0 0 0 12 0'}),
    h('line',{x1:10,y1:12,x2:10,y2:19}),
    h('line',{x1:7,y1:19,x2:13,y2:19}),
  ),
  channels: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M1 5h18M1 10h18M1 15h18'}),
    h('circle',{cx:5,cy:5,r:2}),
    h('circle',{cx:15,cy:10,r:2}),
    h('circle',{cx:5,cy:15,r:2}),
  ),
  security: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 1l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V4z'}),
    h('path',{d:'M8 10l1.5 1.5L12 8'}),
  ),
  memory: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:3,y:2,width:14,height:16,rx:2}),
    h('line',{x1:7,y1:6,x2:13,y2:6}),
    h('line',{x1:7,y1:10,x2:13,y2:10}),
    h('line',{x1:7,y1:14,x2:11,y2:14}),
  ),
  skills: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 2a4 4 0 0 0-4 4v2H4v8h12V8h-2V6a4 4 0 0 0-4-4z'}),
    h('circle',{cx:10,cy:12,r:2}),
  ),
  system: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:10,cy:8,r:5}),
    h('path',{d:'M3 17c1-3 4-5 7-5s6 2 7 5'}),
  ),
  oracle: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:5,cy:5,r:2}),
    h('circle',{cx:15,cy:5,r:2}),
    h('circle',{cx:5,cy:15,r:2}),
    h('circle',{cx:15,cy:15,r:2}),
    h('path',{d:'M7 7l6 6M13 7l-6 6'}),
  ),
  mcp: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:2,y:5,width:6,height:10,rx:1}),
    h('rect',{x:12,y:5,width:6,height:10,rx:1}),
    h('path',{d:'M8 10h4'}),
  ),
  charts: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:2,y:12,width:4,height:6,rx:1}),
    h('rect',{x:8,y:7,width:4,height:11,rx:1}),
    h('rect',{x:14,y:2,width:4,height:16,rx:1}),
  ),
};

/* ── category metadata ──────────────────────────────────────── */

const CATEGORIES = [
  { id:'general',  label:_t('cat.general'),  icon:'general' },
  { id:'llm',      label:_t('cat.llm'),      icon:'llm' },
  { id:'agents',   label:_t('cat.agents'),   icon:'agents' },
  { id:'plugins',  label:_t('cat.plugins'),  icon:'plugins' },
  { id:'voice',    label:_t('cat.voice'),    icon:'voice' },
  { id:'channels', label:_t('cat.channels'), icon:'channels' },
  { id:'mcp',      label:_t('cat.mcp'),      icon:'mcp' },
  { id:'security', label:_t('cat.security'), icon:'security' },
  { id:'memory',   label:_t('cat.memory'),   icon:'memory' },
  { id:'skills',   label:_t('cat.skills'),   icon:'skills' },
  { id:'system',   label:_t('cat.system'),   icon:'system' },
  { id:'oracle',   label:_t('cat.oracle'),   icon:'oracle' },
  { id:'charts',   label:_t('cat.charts'),   icon:'charts' },
];

const CATEGORY_DESC = {
  general:   _t('desc.general'),
  llm:       _t('desc.llm'),
  agents:    _t('desc.agents'),
  plugins:   _t('desc.plugins'),
  voice:     _t('desc.voice'),
  channels:  _t('desc.channels'),
  mcp:       _t('desc.mcp'),
  security:  _t('desc.security'),
  memory:    _t('desc.memory'),
  skills:    _t('desc.skills'),
  system:    _t('desc.system'),
  oracle:    _t('desc.oracle'),
  charts:    _t('desc.charts'),
};

/* ── agent glyph map — single source of truth in data.js ───── */
/* data.js loads before admin.js, so window.JARVIS_GLYPHS exists. */

const AGENT_GLYPHS = window.JARVIS_GLYPHS || {};

/* ── Row components ─────────────────────────────────────────── */

function ToggleRow({ label, value, onChange }) {
  return h('div', {className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('label',{className:'admin-toggle'},
        h('input',{type:'checkbox', checked:value, onChange:e=>onChange(e.target.checked)}),
        h('div',{className:'admin-toggle-track'}),
      ),
    ),
  );
}

function InputRow({ label, value, onChange, kind, placeholder }) {
  const tag = kind === 'number' ? 'number' : 'text';
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('input',{
        className:'admin-input', type:tag,
        value, placeholder: placeholder||'',
        onChange:e=>onChange(tag==='number'?Number(e.target.value):e.target.value),
      }),
    ),
  );
}

function SelectRow({ label, value, onChange, opts }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('select',{className:'admin-select', value, onChange:e=>onChange(e.target.value)},
        opts.map(o=>h('option',{key:o,value:o}, o)),
      ),
    ),
  );
}

function SliderRow({ label, value, onChange, min, max, step }) {
  min = min ?? 0; max = max ?? 1; step = step ?? 0.01;
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control', style:{display:'flex',alignItems:'center',gap:10}},
      h('input',{className:'admin-slider', type:'range', min, max, step,
        value, onChange:e=>onChange(Number(e.target.value))}),
      h('span',{className:'admin-slider-value'}, value),
    ),
  );
}

function TagInputRow({ label, value, onChange }) {
  const [draft, setDraft] = useState('');
  const tags = Array.isArray(value) ? value : [];
  const addTag = () => {
    const t = draft.trim().toLowerCase();
    if (t && !tags.includes(t)) { onChange([...tags, t]); setDraft(''); }
  };
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('div',{className:'admin-tags'},
        tags.map((t,i)=>h('span',{key:i,className:'admin-tag'},
          t,
          h('span',{className:'admin-tag-remove', onClick:()=>onChange(tags.filter((_,j)=>j!==i))},'×'),
        )),
        h('input',{className:'admin-tag-input', value:draft,
          placeholder:_t('admin.tag_placeholder'),
          onChange:e=>setDraft(e.target.value),
          onKeyDown:e=>{if(e.key==='Enter'){e.preventDefault();addTag();}if(e.key==='Backspace'&&!draft&&tags.length){onChange(tags.slice(0,-1));}},
          onBlur:addTag,
        }),
      ),
    ),
  );
}

function ButtonRow({ label, buttonLabel, onClick, variant }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('button',{className:`admin-btn ${variant?'is-'+variant:''}`, onClick}, buttonLabel),
    ),
  );
}

function InfoRow({ label, value }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control', style:{fontFamily:'var(--font-mono)',fontSize:12,color:'var(--text-dim)'}},
      String(value),
    ),
  );
}

function Group({ title, children }) {
  if (!children || (Array.isArray(children) && children.every(c=>!c))) return null;
  return h('div',{className:'admin-group'},
    h('div',{className:'admin-group-header'}, title),
    children,
  );
}

/* ── Settings row renderer ──────────────────────────────────── */

function renderRow(s, i, onUpdate, onAction) {
  const update = (val) => onUpdate(s.key, val);
  switch (s.kind) {
    case 'toggle': return h(ToggleRow,{key:i,label:s.label,value:!!s.value,onChange:update});
    case 'select': return h(SelectRow,{key:i,label:s.label,value:s.value,onChange:update,opts:s.opts});
    case 'slider': return h(SliderRow,{key:i,label:s.label,value:s.value,onChange:update});
    case 'tags':   return h(TagInputRow,{key:i,label:s.label,value:s.value,onChange:update});
    case 'number': return h(InputRow,{key:i,label:s.label,value:s.value,onChange:update,kind:'number'});
    case 'info':   return h(InfoRow,{key:i,label:s.label,value:s.value});
    case 'button': return h(ButtonRow,{key:i,label:s.label,buttonLabel:s.opts[0]||'Action',onClick:()=>onAction&&onAction(s.key),variant:s.opts[1]});
    default:       return h(InputRow,{key:i,label:s.label,value:s.value,onChange:update});
  }
}

/* ── Agent card for Agents page ─────────────────────────────── */

function AgentCard({ agent, onUpdate }) {
  const [open, setOpen] = useState(false);
  const glyph = AGENT_GLYPHS[agent.id] || '';
  return h('div',{className:'admin-agent-card'},
    h('button',{className:'admin-agent-head', onClick:()=>setOpen(!open)},
      glyph && h('svg',{viewBox:'-12 -12 24 24',width:16,height:16,style:{flexShrink:0}},
        h('path',{d:glyph,fill:'none',stroke:'currentColor',strokeWidth:1.2,strokeLinejoin:'round'}),
      ),
      h('span',{className:`admin-agent-dot is-${agent.status||'idle'}`}),
      h('span',{className:'admin-agent-name'}, agent.name || agent.id),
      h('span',{className:'admin-agent-role'}, agent.role || ''),
      h('span',{className:'admin-agent-tier'}, agent.tier || 'FND'),
      h('span',{style:{marginLeft:'auto',color:'var(--text-dim)',fontSize:12}}, open?'▲':'▼'),
    ),
    open && h('div',{className:'admin-agent-body'},
      h(ToggleRow,{label:'Status (active)',value:agent.status==='active',onChange:v=>onUpdate(agent.id,'status',v?'active':'paused')}),
      h(InputRow,{label:'Model',value:agent.model||'',onChange:v=>onUpdate(agent.id,'model',v)}),
      h(SelectRow,{label:'Channel',value:agent.channel||'voice',onChange:v=>onUpdate(agent.id,'channel',v),opts:['voice','web','telegram','discord','email','slack']}),
      h(SelectRow,{label:'Tier',value:agent.tier||'FND',onChange:v=>onUpdate(agent.id,'tier',v),opts:['CNS','BIZ','SEC','FND']}),
    ),
  );
}

/* ── Toast ───────────────────────────────────────────────────── */

function Toast({ message }) {
  if (!message) return null;
  return h('div',{className:'admin-toast', key:message}, message);
}

/* ── System page ─────────────────────────────────────────────── */

function SystemPage({ envData, onRefresh }) {
  const entries = envData ? Object.entries(envData) : [];
  return h('div',null,
    h(Group,{title:_t('admin.env_title')},
      entries.length === 0 && h('div',{style:{padding:12,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading')),
      entries.map(([k,v],i)=>h(InfoRow,{key:i,label:k,value:v})),
    ),
    h('div',{style:{marginTop:16}},
      h('button',{className:'admin-btn', onClick:onRefresh}, _t('admin.reload')),
    ),
  );
}

/* ── Agents page ─────────────────────────────────────────────── */

function AgentsPage({ onUpdate }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/agents').then(r=>r.json()).then(d=>{
      if (d.agents) setList(d.agents);
      setLoading(false);
    }).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading'));
  return h('div',null,
    list.map((a,i)=>h(AgentCard,{key:i,agent:a,onUpdate})),
  );
}

/* ── Audit log (in Security page) ────────────────────────────── */

function AuditLog() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/admin/audit?limit=30').then(r=>r.json()).then(d=>{setRows(d.rows||[]);setLoading(false)}).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:8,fontSize:11,color:'var(--text-dim)'}}, _t('admin.loading'));
  if (!rows.length) return h('div',{style:{padding:8,fontSize:11,color:'var(--text-dim)'}}, _t('admin.no_audit'));
  return h('div',{style:{marginTop:8}},
    rows.slice(0,20).map((r,i)=>h('div',{key:i,style:{
      display:'flex',gap:12,padding:'4px 0',fontFamily:'var(--font-mono)',fontSize:10,
      borderBottom:'1px solid var(--border-glass)',color:'var(--text-secondary)',
    }},
      h('span',{style:{width:80,flexShrink:0}}, r.timestamp ? r.timestamp.slice(11,19) : '--'),
      h('span',{style:{width:80,flexShrink:0,color:'var(--accent)'}}, r.event_type||'--'),
      h('span',{style:{width:60,flexShrink:0}}, r.agent_id||'--'),
      h('span',{style:{flex:1,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}, r.summary||''),
    )),
  );
}

/* ── LLM test button ─────────────────────────────────────────── */

function LLMTest() {
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const test = () => {
    setBusy(true);
    fetch('/api/admin/llm/test',{method:'POST'}).then(r=>r.json()).then(d=>{setResults(d.results);setBusy(false)}).catch(()=>setBusy(false));
  };
  return h('div',null,
    h('button',{className:'admin-btn is-primary', onClick:test, disabled:busy}, busy ? _t('admin.test_busy') : _t('admin.test_btn')),
    results && h('div',{style:{marginTop:10,display:'flex',flexDirection:'column',gap:4}},
      results.map((r,i)=>h('div',{key:i,style:{display:'flex',gap:12,fontFamily:'var(--font-mono)',fontSize:11,alignItems:'center'}},
        h('span',{style:{width:100}}, r.name),
        r.ok
          ? h('span',{style:{color:'var(--green-active)'}}, '✓ Online')
          : h('span',{style:{color:'var(--red-alert)'}}, '✗ Offline'),
        h('span',{style:{color:'var(--text-dim)',fontSize:10}}, r.status ? `HTTP ${r.status}` : (r.error||'')),
      )),
    ),
  );
}

/* ── Memory clear button ─────────────────────────────────────── */

function MemoryClear({ onToast }) {
  const clear = () => {
    if (!confirm(_t('admin.confirm_clear'))) return;
    fetch('/api/admin/memory/clear',{method:'POST'}).then(r=>r.json()).then(d=>{onToast(d.message||_t('admin.btn_clear'))}).catch(()=>onToast(_t('admin.error_unknown')));
  };
  return h('button',{className:'admin-btn is-danger', onClick:clear}, _t('admin.btn_clear'));
}

/* ── Oracle Pipeline Weaver panel ───────────────────────────── */

function OraclePage() {
  const [data, setData] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState('status');

  const fetchData = () => {
    fetch('/api/oracle/status').then(r=>r.json()).then(d=>setData(d)).catch(()=>{});
    fetch('/api/oracle/conflicts').then(r=>r.json()).then(d=>setConflicts(d.conflicts||[])).catch(()=>{});
  };

  useEffect(() => { fetchData(); const id = setInterval(fetchData, 15000); return ()=>clearInterval(id); }, []);

  const doSync = () => {
    setSyncing(true);
    fetch('/api/oracle/sync', {method:'POST'}).then(r=>r.json()).then(()=>{ fetchData(); setSyncing(false); }).catch(()=>setSyncing(false));
  };

  const resolveConflicts = () => {
    fetch('/api/oracle/conflicts/resolve', {method:'POST'}).then(r=>r.json()).then(()=>fetchData()).catch(()=>{});
  };

  if (!data) return h('div',{className:'oracle-loading'}, _t('admin.loading'));

  return h('div',{className:'oracle-wrap'},
    h('div',{className:'oracle-tabs'},
      h('button',{className:`oracle-tab ${tab==='status'?'is-active':''}`, onClick:()=>setTab('status')}, _t('oracle.tab.status')),
      h('button',{className:`oracle-tab ${tab==='sessions'?'is-active':''}`, onClick:()=>setTab('sessions')}, _t('oracle.tab.sessions')),
      h('button',{className:`oracle-tab ${tab==='conflicts'?'is-active':''}`, onClick:()=>setTab('conflicts')}, _t('oracle.tab.conflicts'), conflicts.length ? ` (${conflicts.length})` : ''),
    ),

    tab === 'status' && h('div',{className:'oracle-status'},
      h('div',{className:'oracle-watcher'}, data.watcher_running ? _t('oracle.watcher_on') : _t('oracle.watcher_off')),
      h('div',{className:'oracle-meta'}, `Last checked: ${data.last_checked || '—'} · Total sessions: ${data.total_sessions}`),

      data.current_session
        ? h('div',{className:'oracle-session-card'},
            h('div',{className:'oracle-session-header'}, `Session: ${data.current_session.session_id}`),
            h('div',{className:'oracle-session-status'}, `Status: ${data.current_session.status} · Commit: ${data.current_session.commit_sha||'—'}`),
            data.current_session.commit_msg && h('div',{className:'oracle-commit-msg'}, data.current_session.commit_msg),
            data.current_session.tasks_completed?.length
              ? h('div',{className:'oracle-tasks'}, `Tasks: ${data.current_session.tasks_completed.join(', ')}`)
              : null,
            data.current_session.tests_total > 0
              ? h('div',{className:`oracle-tests ${data.current_session.tests_failed > 0 ? 'is-fail' : 'is-pass'}`},
                  `Tests: ${data.current_session.tests_passed}/${data.current_session.tests_total} passed` +
                  (data.current_session.tests_failed ? ` · ${data.current_session.tests_failed} failed` : ''))
              : null,
            data.current_session.error && h('div',{className:'oracle-error'}, data.current_session.error),
          )
        : h('div',{className:'oracle-empty'}, _t('oracle.no_session')),

      h('button',{className:'admin-btn is-primary', onClick:doSync, disabled:syncing},
        syncing ? _t('oracle.syncing') : _t('oracle.sync_btn')),
    ),

    tab === 'sessions' && h('div',{className:'oracle-sessions'},
      (data.sessions || []).length === 0
        ? h('div',{className:'oracle-empty'}, _t('oracle.no_session'))
        : (data.sessions || []).slice().reverse().map(s => h('div',{key:s.session_id, className:'oracle-session-row'},
            h('span',{className:'oracle-ses-id'}, s.session_id),
            h('span',{className:`oracle-ses-status oracle-ses-${s.status}`}, s.status),
            h('span',{className:'oracle-ses-commit'}, s.commit_sha ? s.commit_sha.slice(0,8) : '—'),
            h('span',{className:'oracle-ses-tasks'}, (s.tasks_completed||[]).join(', ')),
            h('span',{className:`oracle-ses-tests ${s.tests_failed > 0 ? 'is-fail' : 'is-pass'}`},
              s.tests_total ? `${s.tests_passed}/${s.tests_total}` : '—'),
          ))
    ),

    tab === 'conflicts' && h('div',{className:'oracle-conflicts'},
      conflicts.length === 0
        ? h('div',{className:'oracle-empty'}, _t('oracle.conflict_none'))
        : h('div',null,
            h('p',{className:'oracle-warn'}, _t('oracle.conflict_found')),
            conflicts.map(c => h('div',{key:c.file_path, className:'oracle-conflict-row'},
              h('span',{className:'oracle-conflict-file'}, c.file_path),
              h('span',{className:'oracle-conflict-hash'}, `local:${c.local_hash.slice(0,6)} remote:${c.remote_hash.slice(0,6)}`),
            )),
            h('button',{className:'admin-btn is-success', onClick:resolveConflicts}, _t('oracle.resolve_btn')),
          ),
    ),
  );
}

/* ── MCP Server Management panel ────────────────────────────── */

function MCPPage({ onToast }) {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:'', transport:'stdio', command:'', url:'' });

  const fetchServers = () => {
    setLoading(true);
    fetch('/api/admin/mcp').then(r=>r.json()).then(d=>{setServers(d.servers||[]);setLoading(false)}).catch(()=>setLoading(false));
  };
  useEffect(()=>{fetchServers();},[]);

  const addServer = (e) => {
    e.preventDefault();
    if (!form.name) return;
    const body = { name:form.name, transport:form.transport };
    if (form.transport === 'stdio') body.command = form.command;
    else body.url = form.url;
    fetch('/api/admin/mcp', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
      .then(r=>{if (!r.ok) return r.json().then(d=>{throw new Error(d.error)}); return r.json()})
      .then(()=>{ onToast(_t('mcp.add_success')); setShowForm(false); setForm({name:'',transport:'stdio',command:'',url:''}); fetchServers(); })
      .catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  const removeServer = (name) => {
    if (!confirm(_t('mcp.remove_confirm')+name+'?')) return;
    fetch(`/api/admin/mcp/${encodeURIComponent(name)}`, {method:'DELETE'})
      .then(r=>r.json()).then(()=>{ onToast(_t('mcp.remove_success')); fetchServers(); })
      .catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  const toggleConnect = (srv) => {
    const action = srv.connected ? 'disconnect' : 'connect';
    fetch(`/api/admin/mcp/${encodeURIComponent(srv.name)}/${action}`, {method:'POST'})
      .then(r=>r.json()).then(d=>{
        if (action === 'connect') onToast(d.ok ? _t('mcp.connect_success') : (d.error||'Connect failed'));
        else onToast(_t('mcp.disconnect_success'));
        fetchServers();
      }).catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading'));

  return h('div',null,
    servers.length === 0
      ? h('p',{style:{padding:12,fontSize:12,color:'var(--text-dim)'}}, _t('mcp.no_servers'))
      : h('div',{style:{display:'flex',flexDirection:'column',gap:8,marginBottom:16}},
          h('div',{style:{fontSize:11,color:'var(--text-dim)',marginBottom:4}}, _t('mcp.total')+servers.length),
          servers.map(srv => h('div',{key:srv.name,style:{
            display:'flex',alignItems:'center',gap:10,padding:'8px 12px',
            background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',
          }},
            h('div',{style:{
              width:8,height:8,borderRadius:'50%',flexShrink:0,
              background: srv.connected ? 'var(--green-active)' : 'var(--text-dim)',
            }}),
            h('div',{style:{flex:1,minWidth:0}},
              h('div',{style:{fontSize:13,fontWeight:600}}, srv.name),
              h('div',{style:{fontSize:10,color:'var(--text-dim)'}},
                srv.transport === 'stdio' ? srv.command : srv.url,
                ' · ', srv.tools_count, _t('mcp.tools'),
              ),
            ),
            srv.tools_count > 0 && h('div',{style:{fontSize:10,color:'var(--text-secondary)',maxWidth:200,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},
              srv.tools.map(t=>t.name).join(', ')
            ),
            h('button',{className:'admin-btn', style:{fontSize:11,padding:'3px 8px'},
              onClick:()=>toggleConnect(srv)},
              srv.connected ? _t('mcp.disconnect') : _t('mcp.connect')
            ),
            h('button',{className:'admin-btn is-danger', style:{fontSize:11,padding:'3px 8px'},
              onClick:()=>removeServer(srv.name)},
              _t('mcp.remove')
            ),
          )),
        ),

    showForm
      ? h('form',{onSubmit:addServer, style:{background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',padding:12}},
          h('div',{style:{fontSize:12,fontWeight:600,marginBottom:8}}, _t('mcp.add_title')),
          h(InputRow,{label:_t('mcp.name'), value:form.name, onChange:v=>setForm({...form,name:v})}),
          h(SelectRow,{label:_t('mcp.transport'), value:form.transport, onChange:v=>setForm({...form,transport:v}), opts:['stdio','sse']}),
          form.transport === 'stdio'
            ? h(InputRow,{label:_t('mcp.command'), value:form.command, onChange:v=>setForm({...form,command:v})})
            : h(InputRow,{label:_t('mcp.url'), value:form.url, onChange:v=>setForm({...form,url:v})}),
          h('div',{style:{display:'flex',gap:8,marginTop:8}},
            h('button',{type:'submit',className:'admin-btn is-primary'}, _t('mcp.add_submit')),
            h('button',{type:'button',className:'admin-btn', onClick:()=>setShowForm(false)}, _t('oracle.sync_btn') ? 'Anulează' : 'Anulează'),
          ),
        )
      : h('button',{className:'admin-btn is-primary', onClick:()=>setShowForm(true)}, _t('mcp.add_btn')),
  );
}

/* ── SVG Chart components ───────────────────────────────────── */

function StatsCard({ label, value, color }) {
  return h('div', {style:{
    background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',
    padding:'16px',flex:1,textAlign:'center',minWidth:120,
  }},
    h('div',{style:{fontSize:28,fontWeight:700,color:color||'var(--accent)'}}, value),
    h('div',{style:{fontSize:11,color:'var(--text-dim)',marginTop:4}}, label),
  );
}

function BarChart({ data, valueKey, labelKey, maxValue, colorFn, unit }) {
  if (!data || !data.length) return null;
  const max = maxValue || Math.max(...data.map(d => d[valueKey]), 0.01);
  const barH = 18;
  const gap = 4;
  const h = data.length * (barH + gap);
  const lw = 80;
  const cw = 260;
  const tw = lw + cw + 70;
  return h('svg',{viewBox:`0 0 ${tw} ${h}`,width:'100%',style:{maxWidth:tw,maxHeight:h}},
    data.map((d,i)=>{
      const y = i * (barH + gap);
      const ratio = Math.min(d[valueKey] / max, 1);
      const bw = Math.max(ratio * cw, 2);
      const c = typeof colorFn === 'function' ? colorFn(ratio) : 'var(--accent)';
      return [
        h('text',{key:`l${i}`,x:0,y:y+barH-4,fontSize:10,fill:'var(--text-secondary)'}, d[labelKey]||''),
        h('rect',{key:`b${i}`,x:lw,y:y,width:bw,height:barH-2,rx:2,fill:c,opacity:0.85}),
        h('text',{key:`v${i}`,x:lw+bw+4,y:y+barH-4,fontSize:9,fill:'var(--text-dim)'}, `${d[valueKey]}${unit||''}`),
      ];
    })
  );
}

function Sparkline({ data, width, height, color }) {
  if (!data || data.length < 2) return h('div',{style:{padding:12,fontSize:11,color:'var(--text-dim)'}},'—');
  const pad = {top:8,right:8,bottom:18,left:8};
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const vals = data.map(d=>d.value);
  const mx = Math.max(...vals,1);
  const mn = Math.min(...vals,0);
  const rng = mx - mn || 1;
  const pts = data.map((d,i)=>{
    const x = pad.left + (i/(data.length-1))*w;
    const y = pad.top + h - ((d.value-mn)/rng)*h;
    return `${x},${y}`;
  }).join(' ');
  const xLabels = data.map((d,i)=>{
    if (data.length>8 && i%Math.ceil(data.length/8)!==0 && i!==data.length-1) return null;
    return h('text',{key:`x${i}`,x:pad.left+(i/(data.length-1))*w,y:height-2,fontSize:8,fill:'var(--text-dim)',textAnchor:'middle'},d.label);
  });
  return h('svg',{viewBox:`0 0 ${width} ${height}`,width:'100%',style:{maxWidth:width,maxHeight:height}},
    h('text',{key:'ymx',x:0,y:pad.top+8,fontSize:9,fill:'var(--text-dim)'}, mx),
    ...xLabels,
    h('polyline',{key:'pl',points:pts,fill:'none',stroke:color||'var(--accent)',strokeWidth:1.5,strokeLinejoin:'round'}),
    h('polygon',{key:'pg',points:pts+` ${pad.left+w},${height-pad.bottom} ${pad.left},${height-pad.bottom}`,fill:color||'var(--accent)',opacity:0.06}),
  );
}

/* ── Charts page ────────────────────────────────────────────── */

function ChartsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/admin/stats').then(r=>r.json()).then(d=>{setData(d);setLoading(false)}).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('admin.loading'));
  if (!data || !data.overview) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('charts.no_data'));

  const ov = data.overview;
  const agents = (data.agents||[]).sort((a,b)=>b.success_rate - a.success_rate);
  const latencyAgents = (data.agents||[]).sort((a,b)=>b.p95_latency - a.p95_latency);
  const daily = (data.daily||[]).slice(-14).map(d=>({label:d.date.slice(5),value:d.total}));
  const channels = Object.entries(data.channels||{});
  const chMax = Math.max(...channels.map(c=>c[1]),1);
  const errors = data.error_types||[];

  const greenYellow = (r) => r > 0.8 ? '#4ade80' : r > 0.5 ? '#facc15' : '#f87171';

  return h('div',null,
    h('div',{style:{display:'flex',gap:12,marginBottom:20,flexWrap:'wrap'}},
      h(StatsCard,{label:_t('charts.total_int'),value:ov.total_interactions,color:'var(--accent)'}),
      h(StatsCard,{label:_t('charts.success_rate'),value:(ov.success_rate*100).toFixed(0)+'%',color:greenYellow(ov.success_rate)}),
      h(StatsCard,{label:_t('charts.avg_latency'),value:ov.avg_latency.toFixed(1)+'s',color:'#60a5fa'}),
      h(StatsCard,{label:_t('charts.agents'),value:ov.agents_tracked,color:'#a78bfa'}),
    ),

    agents.length > 0 && h('div',{className:'admin-group'},
      h('div',{className:'admin-group-header'}, _t('charts.success')),
      h(BarChart,{data:agents.map(a=>({label:a.agent_id,value:a.success_rate*100})),
        valueKey:'value',labelKey:'label',maxValue:100,unit:'%',
        colorFn:(r)=>r>0.8?'#4ade80':r>0.5?'#facc15':'#f87171'}),
    ),

    latencyAgents.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.latency')),
      h(BarChart,{data:latencyAgents.map(a=>({label:a.agent_id,value:a.p95_latency||a.avg_latency})),
        valueKey:'value',labelKey:'label',unit:'s',colorFn:()=>'#60a5fa'}),
    ),

    daily.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.daily_vol')),
      h(Sparkline,{data:daily,width:500,height:80,color:'var(--accent)'}),
    ),

    channels.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.channel')),
      channels.map(([ch,count],i)=>h('div',{key:i,style:{display:'flex',alignItems:'center',gap:8,padding:'4px 0'}},
        h('span',{style:{width:80,fontSize:11,color:'var(--text-secondary)'}}, ch),
        h('div',{style:{flex:1,height:14,background:'var(--bg-glass)',borderRadius:7,overflow:'hidden'}},
          h('div',{style:{width:`${(count/chMax)*100}%`,height:'100%',background:'var(--accent)',opacity:0.7,borderRadius:7}}),
        ),
        h('span',{style:{fontSize:10,color:'var(--text-dim)',width:40,textAlign:'right'}}, count),
      )),
    ),

    errors.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.errors')),
      errors.map(([err,count],i)=>h('div',{key:i,style:{display:'flex',gap:8,padding:'3px 0',fontSize:11}},
        h('span',{style:{color:'var(--text-secondary)'}}, err),
        h('span',{style:{color:'#f87171',fontWeight:600}}, count),
      )),
    ),
  );
}

function AdminApp() {
  const [active, setActive] = useState('general');
  const [settings, setSettings] = useState({});
  const [search, setSearch] = useState('');
  const [dirty, setDirty] = useState({});
  const [toast, setToast] = useState('');
  const [envData, setEnvData] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(()=>{
    fetch('/api/admin/settings').then(r=>r.json()).then(d=>setSettings(d));
    fetch('/api/admin/env').then(r=>r.json()).then(d=>setEnvData(d)).catch(()=>{});
  },[refreshKey]);

  const showToast = (msg) => { setToast(msg); setTimeout(()=>setToast(''), 2500); };

  const onUpdate = (key, value) => {
    setDirty(prev => ({...prev, [key]: value}));
  };

  const onAgentUpdate = (agentId, key, value) => {
    fetch(`/api/admin/agents/${agentId}`, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({updates:{[key]:value}}),
    }).then(r=>r.json()).then(d=>{
      if (d.saved) showToast(`${agentId}.${key} → ${JSON.stringify(value)}`);
      else showToast(`${_t('admin.error_prefix')}${d.error||_t('admin.error_unknown')}`);
    }).catch(e=>showToast(`${_t('admin.error_network')}${e.message}`));
  };

  const saveCategory = () => {
    const keys = Object.keys(dirty);
    if (!keys.length) return;
    const body = {};
    keys.forEach(k => { body[k] = dirty[k]; });
    fetch(`/api/admin/settings/${active}`, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({values:body}),
    }).then(r=>r.json()).then(d=>{
      setDirty({});
      showToast(`${_t('admin.saved')}${d.updated}${_t('admin.saved_suffix')}`);
      // Refresh settings
      fetch('/api/admin/settings').then(r=>r.json()).then(s=>setSettings(s));
    }).catch(()=>showToast(_t('admin.save_error')));
  };

  const catSettings = settings[active] || [];
  const mergedSettings = catSettings.map(s => ({
    ...s,
    value: dirty.hasOwnProperty(s.key) ? dirty[s.key] : s.value,
  }));

  // Filter by search
  const filtered = mergedSettings.filter(s =>
    !search || s.label.toLowerCase().includes(search.toLowerCase()) || s.key.toLowerCase().includes(search.toLowerCase())
  );

  const cat = CATEGORIES.find(c=>c.id===active);

  // Check if any change in current category
  const hasChanges = catSettings.some(s => dirty.hasOwnProperty(s.key) && dirty[s.key] !== s.value);

  // Special page for agents
  const isAgents = active === 'agents';
  const isSystem = active === 'system';
  const isSecurity = active === 'security';
  const isOracle = active === 'oracle';
  const isMCP = active === 'mcp';
  const isCharts = active === 'charts';

  return h('div',{className:'admin-wrap'},
    h('div',{className:'admin-sidebar'},
      h('div',{className:'admin-sidebar-head'},
        ICONS.system,
        _t('admin.brand'),
      ),
      h('input',{className:'admin-sidebar-search', type:'text', placeholder:_t('admin.search'),
        value:search, onChange:e=>setSearch(e.target.value)}),
      h('nav',{className:'admin-nav'},
        CATEGORIES.map(c=>h('button',{
          key:c.id,
          className:`admin-nav-item ${active===c.id?'is-active':''}`,
          onClick:()=>{setActive(c.id);setSearch('');},
        }, ICONS[c.icon], c.label)),
      ),
    ),

    h('div',{className:'admin-content'},
      h('h1',null, cat ? cat.label : ''),
      h('p',{className:'admin-page-desc'}, cat ? (CATEGORY_DESC[cat.id]||'') : ''),

      isAgents
        ? h(AgentsPage,{onUpdate:onAgentUpdate})

        : isSystem
          ? h(SystemPage,{envData, onRefresh:()=>fetch('/api/admin/env').then(r=>r.json()).then(d=>setEnvData(d))})

          : isOracle
            ? h(OraclePage)

            : isMCP
              ? h(MCPPage,{onToast:showToast})

              : isCharts
                ? h(ChartsPage)

                : h('div',null,
                filtered.map(s => renderRow(s, s.key, onUpdate, (key)=>showToast(`${_t('admin.action')}${key}`) )),
                isSecurity && h(AuditLog),
              ),

      // LLM test button on LLM page
      active === 'llm' && h('div',{style:{marginTop:20}}, h(LLMTest)),

      // Memory clear button on Memory page
      active === 'memory' && h('div',{style:{marginTop:20}}, h(MemoryClear,{onToast:showToast})),

      // Reseed settings button on System page
      active === 'system' && h('div',{style:{marginTop:20}},
        h('button',{className:'admin-btn is-warning',
          onClick:()=>{
            if (!confirm('Reseed all settings to defaults? Custom values will be lost.')) return;
            fetch('/api/admin/settings/reseed',{method:'POST'}).then(r=>r.json()).then(d=>{
              showToast(d.message||'Reseeded');
              setDirty({});
              setRefreshKey(k=>k+1);
            }).catch(()=>showToast('Reseed failed'));
          }
        }, '🔄 Reseed defaults'),
      ),

      // Save button
      hasChanges && h('div',{style:{position:'sticky',bottom:0,padding:'12px 0',background:'var(--bg-void)'}},
        h('button',{className:'admin-btn is-primary', onClick:saveCategory}, _t('admin.save')),
      ),
    ),

    h(Toast,{message:toast}),
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(h(AdminApp));
