/* HUD v2 · SHELL — topbar, nav, ticker, right column, ambient, palette */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Icon, ICONS, Glyph, Reactor, Meter, statusClass, fmtTime, fmtTimeShort, fmtDate } from './primitives';
import { renderRich } from './cockpit';
import { isExecutingAgent, NeuralMesh } from './mesh';
import { VoiceOrb } from './orb';
import { BriefingWall } from './wall';
import { runningTasks } from './task-state';
import { V2 } from './data';

const MODES: Array<{ id?: string; icon?: string; tkey?: string; live?: boolean; sep?: boolean; locked?: boolean }> = [
  { id:'cockpit', icon:'cockpit', tkey:'cockpit', live:true },
  { id:'chat', icon:'chat', tkey:'chat' },
  { id:'projects', icon:'projects', tkey:'projects' },
  { id:'agents', icon:'agents', tkey:'agentsMode' },
  { id:'trust', icon:'trust', tkey:'trust' },
  { id:'memory', icon:'memory', tkey:'memory' },
  { sep:true },
  { id:'autonomy', icon:'autonomy', tkey:'autonomy' },
  { id:'build', icon:'build', tkey:'build' },
  { id:'observe', icon:'observe', tkey:'observe' },
  { id:'interop', icon:'interop', tkey:'interop' },
  { sep:true },
  { id:'finance', icon:'finance', tkey:'finance' },
  { id:'health', icon:'health', tkey:'health' },
  { id:'knowledge', icon:'knowledge', tkey:'knowledge' },
  { id:'family', icon:'family', tkey:'family' },
  { sep:true },
  { id:'comms', icon:'comms', tkey:'comms' },
  { id:'admin', icon:'admin', tkey:'admin' },
];

function TopBar({ clock, lang, setLang, accent, agents, localPct, live, trust, llm, demo, setDemo, serverUp, onPalette, onAmbient, t }){
  const tr = trust || { mic:'on', strict_local:false };
  const lm = llm || { state:'unknown', model:null };
  const enabled = agents.length;
  const running = agents.filter(isExecutingAgent).length;
  const LLM = ({
    ready:    { v:'● READY',    c:'var(--green)', t:'model loaded' + (lm.model ? ': ' + lm.model : '') },
    no_model: { v:'○ NO MODEL', c:'var(--amber)', t:'LM Studio reachable but no model is loaded' },
    offline:  { v:'○ OFFLINE',  c:'var(--ink-3)', t:'no local LLM backend reachable' },
  })[lm.state] || { v:'○ —', c:'var(--ink-3)', t:'LLM state unknown' };
  const DATA = demo ? { v:'◐ DEMO', c:'var(--amber)', t:'demo data — seeded sample, not your live backend' }
    : !serverUp ? { v:'○ OFFLINE', c:'var(--ink-3)', t:'server unreachable' }
    : live ? { v:'● LIVE', c:'var(--green)', t:'live backend data' }
    : { v:'○ EMPTY', c:'var(--ink-3)', t:'server up — no live data yet (connect plugins / load a model)' };
  return (
    <div className="topbar">
      <div className="brand">
        <Reactor/>
        <div className="brand-tx"><div className="l1">JARVIS</div><div className="l2">{t.sub}</div></div>
        <div className="badges" style={{marginLeft:18}}>
          <div className="badge" title="agents enabled · actually running"><div className="k">AGENTS</div><div className="v">{enabled} en{running>0 ? ' · '+running+' ▶' : ''}</div></div>
          <div className="badge" title={LLM.t}><div className="k">LLM</div><div className="v" style={{color:LLM.c}}>{LLM.v}</div></div>
          <div className="badge" title={DATA.t}><div className="k">DATA</div><div className="v" style={{color:DATA.c}}>{DATA.v}</div></div>
          {localPct!=null && <div className={'badge' + (localPct===100 ? ' ok' : '')} title="share of processing kept on-device"><div className="k">{t.local}</div><div className="v">{localPct}%</div></div>}
          <div className={'badge' + (tr.strict_local ? ' ok' : '')} title={tr.strict_local ? 'strict-local — no cloud egress path; nothing leaves the machine' : 'hybrid — a cloud backend is reachable'}><div className="k">EGRESS</div><div className="v">{tr.strict_local ? '⊘ SEALED' : '↗ HYBRID'}</div></div>
          <div className={'badge' + (tr.mic === 'off' ? ' ok' : '')} title={tr.mic === 'off' ? 'microphone muted (JARVIS_MIC_MUTED)' : 'microphone live'}><div className="k">MIC</div><div className="v">{tr.mic === 'off' ? '⊘ MUTED' : '● ON'}</div></div>
        </div>
      </div>
      <div className="clock">
        <div className="clock-time">{fmtTime(clock)}</div>
        <div className="clock-date">{fmtDate(clock,lang)}</div>
      </div>
      <div className="badges">
        <button className="tool-btn" onClick={()=>setDemo&&setDemo(!demo)} title="toggle demo data (seeded sample vs live-only)" style={demo?{color:'var(--amber)',borderColor:'var(--amber)'}:undefined}>{demo?'◐ demo':'○ demo'}</button>
        <button className="tool-btn" onClick={()=>setLang(lang==='en'?'ro':'en')} title="language"><Icon d={ICONS.globe} size={13}/>{t.langName}</button>
        <button className="tool-btn" onClick={onAmbient} title="ambient"><Icon d={ICONS.ambient} size={13}/>{t.enterAmbient}</button>
        <button className="tool-btn" onClick={onPalette} title="command palette">⌘K</button>
      </div>
    </div>
  );
}

function Ticker({ items, t, hidden }){
  if(hidden) return null;
  const list = [...items, ...items];
  return (
    <div className="ticker">
      <div className="ticker-head">
        <span className="dot"></span><span className="lab">{t.situation}</span>
        <span className="sit">{t.allnominal}</span>
      </div>
      <div className="ticker-marq">
        <div className="ticker-track">
          {list.map((it,i)=>(
            <span className={'ticker-item '+(it.cls||'')} key={i}>
              <span className="agent">{it.agent}</span>
              <span className="verb">{it.verb}</span>
              <span>{it.text}</span>
              <span className="bar"><i style={{width:it.bar+'%'}}></i></span>
              <span className="ticker-sep">│</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Rail({ mode, setMode, t }){
  return (
    <div className="rail">
      {MODES.map((m,i)=> m.sep
        ? <div className="rail-sep" key={i}></div>
        : <button key={m.id} className={'rail-btn'+(mode===m.id?' active':'')+(m.locked?' locked':'')}
            onClick={()=>!m.locked&&setMode(m.id)} title={t[m.tkey]+(m.locked?' (soon)':'')}>
            <Icon d={ICONS[m.icon]} size={19}/><span className="rl">{t[m.tkey]}</span>
          </button>
      )}
    </div>
  );
}

function Tabs({ mode, setMode, t }){
  return (
    <div className="tabs">
      {MODES.filter(m=>!m.sep).map(m=>(
        <button key={m.id} className={'tab-btn'+(mode===m.id?' active':'')+(m.locked?' locked':'')}
          onClick={()=>!m.locked&&setMode(m.id)}>
          <Icon d={ICONS[m.icon]} size={14}/>{t[m.tkey]}{m.locked?' ·':''}
        </button>
      ))}
    </div>
  );
}

/* RIGHT CONTEXT COLUMN */
function ContextColumn({ decisions, onDecision, weather, calendar, heartbeat, demo, t }){
  const W = weather; const CAL = calendar || []; const HB = heartbeat || [];
  const empty = (msg) => <div style={{color:'var(--ink-3)',fontSize:11,textAlign:'center',padding:'16px 0',fontFamily:'var(--font-mono)',letterSpacing:'.05em'}}>{msg}</div>;
  return (
    <div className="col scrollcol">
      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.bolt} size={14}/><span className="ttl">{t.decisions}</span><span className="st">{decisions.length}</span></div>
        <div className="panel-body tight" tabIndex={0}>
          {decisions.length===0 && empty('queue clear ✓')}
          {decisions.map((d,i)=>(
            <div className="dcard" key={d._id}>
              <div className="dh"><span className="who">{d.who}</span><span className={'kind '+d.kind}>{d.kindLabel}</span></div>
              <div className="db">{renderRich(d.body)}</div>
              <div className="da">{d.actions.map((a,j)=><button key={j} className={a.primary?'primary':''} onClick={()=>onDecision(d._id)}>{a.l}</button>)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.observe} size={14}/><span className="ttl">{t.weather}</span>{W && <span className="st">{W.city}</span>}</div>
        <div className="panel-body wcard" tabIndex={0}>
          {W ? (<>
            <div style={{display:'flex',alignItems:'flex-end',gap:14}}>
              <div className="temp">{W.temp}°</div>
              <div style={{paddingBottom:6}}><div style={{fontSize:13,color:'var(--ink)'}}>{W.desc}</div><div style={{fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>feels {W.feels}°</div></div>
            </div>
            <div className="wgrid">
              <span className="wk">WIND</span><span className="wv">{W.wind}</span>
              <span className="wk">HUMIDITY</span><span className="wv">{W.humidity}</span>
            </div>
            <div className="wfore" style={{display:'flex',justifyContent:'space-between',marginTop:14}}>
              {(W.forecast||[]).map((f,i)=><div key={i} style={{textAlign:'center',fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>{f.d}<div style={{color:'var(--ink)',marginTop:4}}>{f.t}</div></div>)}
            </div>
          </>) : empty('weather not connected')}
        </div>
      </div>

      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.cockpit} size={14}/><span className="ttl">{t.schedule}</span><span className="st">{CAL.length}</span></div>
        <div className="panel-body tight" tabIndex={0}>
          {CAL.length===0 && empty('calendar not connected')}
          {CAL.map((c,i)=>(
            <div className={'cal-row '+(c.state||'')} key={i}>
              <span className="tm">{c.tm}</span>
              <div><div className="ti">{c.ti}</div><div className="vw">{c.vw}</div></div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.autonomy} size={14}/><span className="ttl">{t.heartbeat}</span></div>
        <div className="panel-body tight" tabIndex={0}>
          {HB.length===0 && empty('no activity yet')}
          {HB.map((h,i)=>(
            <div className="hbrow" key={i}><div className={'sev '+h.sev}></div><div><div className="ht"><span className="ag">{h.ag}</span><span>{h.t}</span></div><div className="hx">{h.x}</div></div></div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* LEFT roster column (cockpit only) */
function RosterColumn({ agents, activeId, onSelect, sys, llm, demo, t }){
  const TIERS=V2.TIERS;
  return (
    <div className="col">
      <div className="panel scroll" style={{flex:'1 1 auto'}}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.agents} size={14}/><span className="ttl">{t.roster}</span><span className="st">{agents.length} enabled</span></div>
        <div className="panel-body tight" tabIndex={0}>
          {agents.length===0 && <div style={{color:'var(--ink-3)',fontSize:11,textAlign:'center',padding:'16px 0',fontFamily:'var(--font-mono)'}}>roster offline — server unreachable</div>}
          {TIERS.map(tier=>{
            const list=agents.filter(a=>a.tier===tier.id); if(!list.length)return null;
            return <div className="tier-group" key={tier.id}>
              <div className="tier-head"><span className="tier-tag">{tier.id}</span><span className="tier-lab">{tier.label}</span></div>
              {list.map(a=>(
                <div className={'agent-row'+(activeId===a.id?' active':'')} key={a.id} onClick={()=>onSelect(a.id)}>
                  <span className="gx"><Glyph id={a.id} size={15}/></span>
                  <div><div className="nm">{a.name}</div><div className="rl">{a.role}</div></div>
                  <span className={'sdot '+statusClass(a.status)}></span>
                </div>
              ))}
            </div>;
          })}
        </div>
      </div>
      <div className="panel" style={{flex:'none'}}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.admin} size={14}/><span className="ttl">{t.system}</span></div>
        <div className="panel-body tight" tabIndex={0}>
          {(() => { const S = sys || {}; const lm = llm || {}; const pct = (u, tot) => (tot ? Math.round((u / tot) * 100) : 0);
            const model = lm.state==='ready' ? (lm.model || 'loaded') : lm.state==='no_model' ? 'no model loaded' : lm.state==='offline' ? 'backend offline' : '—';
            const mcol = lm.state==='ready' ? 'var(--accent-light)' : (lm.state==='no_model' || lm.state==='offline') ? 'var(--amber)' : 'var(--ink-3)';
            return (<>
              <Meter label="RAM" val={pct(S.ram_used, S.ram_total)}/>
              <Meter label="VRAM" val={pct(S.vram_used, S.vram_total)}/>
              <Meter label="GPU" val={S.gpu_load != null ? Math.round(S.gpu_load) : 0}/>
              <div className="sysrow"><span className="k">BACKEND</span><span className="v" style={{color:mcol}}>{(S.backend || 'LM Studio') + ' · ' + model}</span></div>
              <div className="sysrow"><span className="k">LATENCY p50</span><span className="v">{S.latency != null && S.latency > 0 ? S.latency + 's' : '—'}</span></div>
            </>);
          })()}
        </div>
      </div>
    </div>
  );
}

/* COMMAND PALETTE */
function Palette({ open, onClose, onMode, setAccent, setLang, onAmbient, ui, t }){
  const [q,setQ]=useState('');
  const [sel,setSel]=useState(0);
  const inputRef=useRef(null);
  useEffect(()=>{ if(open){ setQ(''); setSel(0); setTimeout(()=>inputRef.current&&inputRef.current.focus(),30);} },[open]);
  // ui = { look, setLook, density, setDensity, motion, setMotion, scanline, setScanline, dotgrid, setDotgrid }
  // Client-only display prefs (persisted to localStorage by App); toggled here.
  const u = ui || {};
  const cmds = useMemo(()=>[
    { g:'Go to', items:[
      { name:'Cockpit', hint:'1', act:()=>onMode('cockpit'), icon:'cockpit' },
      { name:'Chat · focus', hint:'9', act:()=>onMode('chat'), icon:'chat' },
      { name:'Projects · rooms & missions', hint:'', act:()=>onMode('projects'), icon:'projects' },
      { name:'Agents', hint:'2', act:()=>onMode('agents'), icon:'agents' },
      { name:'Trust Center', hint:'3', act:()=>onMode('trust'), icon:'trust' },
      { name:'Memory & Knowledge', hint:'4', act:()=>onMode('memory'), icon:'memory' },
      { name:'Autonomy', hint:'5', act:()=>onMode('autonomy'), icon:'autonomy' },
      { name:'Build', hint:'6', act:()=>onMode('build'), icon:'build' },
      { name:'Observe', hint:'7', act:()=>onMode('observe'), icon:'observe' },
      { name:'Interop', hint:'8', act:()=>onMode('interop'), icon:'interop' },
      { name:'Finance', hint:'', act:()=>onMode('finance'), icon:'finance' },
      { name:'Health', hint:'', act:()=>onMode('health'), icon:'health' },
      { name:'Knowledge', hint:'', act:()=>onMode('knowledge'), icon:'knowledge' },
      { name:'Family · local', hint:'', act:()=>onMode('family'), icon:'family' },
      { name:'Comms · inbox', hint:'0', act:()=>onMode('comms'), icon:'comms' },
      { name:'Admin · settings', hint:'', act:()=>onMode('admin'), icon:'admin' },
      { name:'Ambient mode', hint:'', act:onAmbient, icon:'ambient' },
    ]},
    { g:'Theme', items:[
      { name:'Accent · Cyan', act:()=>setAccent('cyan'), icon:'bolt' },
      { name:'Accent · Amber', act:()=>setAccent('amber'), icon:'bolt' },
      { name:'Accent · Green', act:()=>setAccent('green'), icon:'bolt' },
      { name:'Accent · Violet', act:()=>setAccent('violet'), icon:'bolt' },
      { name:'Toggle language EN / RO', act:()=>setLang(l=>l==='en'?'ro':'en'), icon:'globe' },
    ]},
    { g:'Display', items:[
      { name:'Look · '+(u.look==='obsidian'||!u.look?'Obsidian ✓':'Obsidian'), act:()=>u.setLook&&u.setLook('obsidian'), icon:'bolt' },
      { name:'Look · '+(u.look==='graphite'?'Graphite ✓':'Graphite'), act:()=>u.setLook&&u.setLook('graphite'), icon:'bolt' },
      { name:'Density · '+(u.density==='compact'?'Compact ✓':'Compact'), act:()=>u.setDensity&&u.setDensity('compact'), icon:'bolt' },
      { name:'Density · '+(u.density==='normal'||!u.density?'Normal ✓':'Normal'), act:()=>u.setDensity&&u.setDensity('normal'), icon:'bolt' },
      { name:'Density · '+(u.density==='comfy'?'Comfy ✓':'Comfy'), act:()=>u.setDensity&&u.setDensity('comfy'), icon:'bolt' },
      { name:'Motion · '+(u.motion==='lively'||!u.motion?'Lively ✓':'Lively'), act:()=>u.setMotion&&u.setMotion('lively'), icon:'bolt' },
      { name:'Motion · '+(u.motion==='calm'?'Calm ✓':'Calm'), act:()=>u.setMotion&&u.setMotion('calm'), icon:'bolt' },
      { name:'Scanline · '+(u.scanline==='off'?'On':'Off'), act:()=>u.setScanline&&u.setScanline(u.scanline==='off'?'on':'off'), icon:'bolt' },
      { name:'Dot grid · '+(u.dotgrid==='on'?'Off':'On'), act:()=>u.setDotgrid&&u.setDotgrid(u.dotgrid==='on'?'off':'on'), icon:'bolt' },
    ]},
  ],[onMode,setAccent,setLang,onAmbient,u.look,u.density,u.motion,u.scanline,u.dotgrid]);
  const flat = useMemo(()=>{
    const f=[]; cmds.forEach(grp=>grp.items.forEach(it=>{ if(!q||it.name.toLowerCase().includes(q.toLowerCase())) f.push({...it,g:grp.g}); })); return f;
  },[cmds,q]);
  useEffect(()=>{ setSel(0); },[q]);
  if(!open) return null;
  const run=it=>{ it.act(); onClose(); };
  const onKey=e=>{
    if(e.key==='ArrowDown'){e.preventDefault();setSel(s=>Math.min(flat.length-1,s+1));}
    else if(e.key==='ArrowUp'){e.preventDefault();setSel(s=>Math.max(0,s-1));}
    else if(e.key==='Enter'){e.preventDefault(); if(flat[sel])run(flat[sel]);}
    else if(e.key==='Escape'){onClose();}
  };
  let gi=-1, lastG=null;
  return (
    <div className="pal-scrim" onClick={onClose}>
      <div className="pal" onClick={e=>e.stopPropagation()}>
        <div className="pal-input"><span className="pc">⌘</span>
          <input ref={inputRef} value={q} onChange={e=>setQ(e.target.value)} onKeyDown={onKey} placeholder={t.cmd+'…'}/>
        </div>
        <div className="pal-list">
          {flat.length===0 && <div className="pal-group">no matches</div>}
          {flat.map((it,i)=>{ gi++; const head = it.g!==lastG; lastG=it.g; return (
            <React.Fragment key={i}>
              {head && <div className="pal-group">{it.g}</div>}
              <div className={'pal-item'+(i===sel?' sel':'')} onMouseEnter={()=>setSel(i)} onClick={()=>run(it)}>
                <Icon d={ICONS[it.icon]} size={16}/><span className="pi-name">{it.name}</span>{it.hint&&<span className="pi-hint">{it.hint}</span>}
              </div>
            </React.Fragment>
          );})}
        </div>
        <div className="pal-foot"><span><kbd>↑↓</kbd> navigate</span><span><kbd>↵</kbd> run</span><span><kbd>esc</kbd> close</span></div>
      </div>
    </div>
  );
}

/* AMBIENT */
function Ambient({ onExit, clock, lang, agents, decisions, motion, localPct, t }){
  useEffect(()=>{
    const h=e=>{ if(e.key==='Escape')onExit(); };
    window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h);
  },[onExit]);
  return (
    <div className="ambient" onClick={onExit}>
      <div className="amb-clock">{fmtTimeShort(clock)}</div>
      <div className="amb-date">{fmtDate(clock,lang)}</div>
      <svg className="ambient-ekg" viewBox="0 0 340 60" preserveAspectRatio="none">
        <path className={motion!=='calm'?'ambient-anim':''} d="M0,30 L80,30 L92,30 L100,10 L110,50 L120,30 L160,30 L172,22 L180,38 L190,30 L340,30"
          style={motion!=='calm'?{strokeDasharray:600,strokeDashoffset:0,animation:'none'}:{}}/>
      </svg>
      <div className="amb-heart">
        <div className="amb-stat"><div className="v">{agents.filter(a=>a.status!=='idle').length}/{agents.length}</div><div className="l">{t.agents}</div></div>
        {localPct != null && <><div className="amb-sep"></div>
        <div className="amb-stat"><div className="v">{localPct}%</div><div className="l">{t.local}</div></div></>}
        <div className="amb-sep"></div>
        <div className="amb-stat"><div className="v">{decisions.length}</div><div className="l">{t.pending}</div></div>
      </div>
      {decisions.length>0 && (
        <div className="amb-pending">
          {decisions.slice(0,3).map(d=><div className="ap" key={d._id}><span className="dot"></span><span style={{color:'var(--accent-light)'}}>{d.who}</span> {stripTags(d.body)}</div>)}
        </div>
      )}
      <div className="amb-exit">{t.exitAmbient}</div>
    </div>
  );
}
function stripTags(s){ return String(s).replace(/<[^>]+>/g,'').replace(/\*\*/g,''); }

/* Cinema stage switcher — mesh (who is working) · orb (voice state) · brain (the
   full briefing wall). Rendered inside the cinema frame, or floating over the wall. */
function StagePicker({ stage, setStage, floating = false }: any) {
  return (
    <div className={'cin-stage-pick' + (floating ? ' wl-pick' : '')}>
      <button className={stage === 'mesh' ? 'on' : ''} onClick={() => setStage('mesh')} title="neural mesh (n)">mesh</button>
      <button className={stage === 'orb' ? 'on' : ''} onClick={() => setStage('orb')} title="voice orb (o)">orb</button>
      <button className={stage === 'brain' ? 'on' : ''} onClick={() => setStage('brain')} title="briefing wall (b)">brain</button>
    </div>
  );
}

/* HUD v3 · CINEMA MODE — full-bleed Neural Mesh framed as a shareable demo (handover §4).
   Port of v3-shell.jsx CinemaMesh; reuses the native NeuralMesh (cinema=true). Esc exits.
   Honesty contract: the prototype hardcoded "87% on-device / 0 cloud leaks" — we show only
   REAL figures (live agent count from the roster, %-local from /api/analytics/locality),
   never a fabricated split. */
export function CinemaMesh({ agents = [], tasks = [], llm, trust, sources, demo = false, localPct, voice, decisions, calendar, heartbeat, serverUp = false, clock, motion = 'lively', localPctSource = null, onExit, t }: any) {
  const [tag, setTag] = useState(0);
  // Two stages share the cinema frame: the mesh (who is working) and the voice orb
  // (is Jarvis listening / speaking). Mesh stays the default so an existing demo
  // opens exactly as before; `o` flips to the orb, `n` back.
  const [stage, setStage] = useState('mesh');
  useEffect(() => { const iv = setInterval(() => setTag((x) => x + 1), 4200); return () => clearInterval(iv); }, []);
  useEffect(() => {
    const h = (e) => {
      if (e.key === 'Escape') onExit();
      else if (e.key === 'o' || e.key === 'O') setStage('orb');
      else if (e.key === 'n' || e.key === 'N') setStage('mesh');
      else if (e.key === 'b' || e.key === 'B') setStage('brain');
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onExit]);
  const trustEvidence = sources?.trust === true;
  const cloudReported = trustEvidence
    && (trust?.cloud_available === true || trust?.claude_available === true);
  const TAGS = demo
    ? [
      'DEMO · seeded sample data',
      'DEMO · illustrative constellation',
      'DEMO · simulated choreography',
    ]
    : [
      'Governed operator view',
      'Current evidence only',
      !trustEvidence
        ? 'Trust evidence unavailable'
        : cloudReported ? 'Cloud lane reported by trust status' : 'Trust status connected',
    ];
  const live = agents.filter(isExecutingAgent).length;
  const running = runningTasks(tasks).length;
  // The briefing wall owns the whole screen (its own chrome, cards and status rail), so
  // it replaces the cinema frame rather than sitting inside the mesh stage.
  if (stage === 'brain') {
    return (
      <>
        <BriefingWall
          agents={agents} tasks={tasks} decisions={decisions} calendar={calendar} heartbeat={heartbeat}
          llm={llm} trust={trust} sources={sources} localPct={localPct} voice={voice}
          serverUp={serverUp} demo={demo} clock={clock} motion={motion} localPctSource={localPctSource} onExit={onExit} />
        <StagePicker stage={stage} setStage={setStage} floating />
      </>
    );
  }
  return (
    <div className="cinema">
      <div className="cin-top">
        <div className="cin-mark"><Reactor /><span className="cin-word">JARVIS</span></div>
        <div className="cin-tag" key={tag}>{TAGS[tag % TAGS.length]}</div>
      </div>
      <div className="cin-stage">
        <StagePicker stage={stage} setStage={setStage} />
        {stage === 'orb'
          ? <VoiceOrb status={(voice && voice.error) ? 'error' : (voice && voice.status) || 'off'} level={(voice && voice.level) || 0} motion={motion} />
          : <NeuralMesh agents={agents} tasks={tasks} llm={llm} trust={trust} sources={sources} demo={demo} cinema={true} motion={motion} onSelect={() => {}} t={t} />}
      </div>
      <div className="cin-bottom">
        <div className="cin-feed"><div className="cin-frow"><span className="cin-dot"></span>{live > 0 || running > 0 ? 'the Cabinet is working…' : 'no live activity'}</div></div>
        <div className="cin-stats">
          <span><b>{live}</b> agents live</span>
          {localPct != null && <span><b>{localPct}%</b> on-device</span>}
        </div>
      </div>
      <button className="cin-exit" onClick={onExit}>Esc</button>
    </div>
  );
}

export { MODES, TopBar, Ticker, Rail, Tabs, ContextColumn, RosterColumn, Palette, Ambient };
