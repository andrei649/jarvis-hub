'use strict';
/* HUD v3 · SHELL — command bar (6 trust badges), ticker, rail (≤10 + Life + World + Admin),
   MODE-SWAPPING context column, palette, ambient, admin drawer, honesty banners */
const { useState:uSs, useEffect:uEs, useRef:uRs, useMemo:uMs } = React;
const { Icon:Ics, ICONS:IKs, Glyph:Gls, Reactor:ReactorS, Meter:MeterS, statusClass:scS,
        fmtTime:ftS, fmtTimeShort:ftsS, fmtDate:fdS, renderRich:rrS } = window;

/* primary rail = 10 modes (hotkeys 1-0) + Life group + World (g-chord) + Admin drawer */
const MODES_V3 = [
  { id:'cockpit',  icon:'cockpit',   tkey:'cockpit',      hot:'1', live:true },
  { id:'decisions',icon:'decisions', tkey:'decisionsMode',hot:'2', count:'dec' },
  { id:'agents',   icon:'agents',    tkey:'agentsMode',   hot:'3' },
  { id:'memory',   icon:'memory',    tkey:'memory',       hot:'4' },
  { id:'autonomy', icon:'autonomy',  tkey:'autonomy',     hot:'5' },
  { id:'missions', icon:'missions',  tkey:'missions',     hot:'6', count:'mis' },
  { id:'trust',    icon:'trust',     tkey:'trust',        hot:'7' },
  { id:'build',    icon:'build',     tkey:'build',        hot:'8' },
  { id:'observe',  icon:'observe',   tkey:'observe',      hot:'9' },
  { id:'interop',  icon:'interop',   tkey:'interop',      hot:'0' },
  { sep:true },
  { id:'life',     icon:'life',      tkey:'life',         hot:'gL' },
  { id:'world',    icon:'globe',     tkey:'world',        hot:'gW' },
  { id:'timeline', icon:'clock',     tkey:'timeline',     hot:'gT', count:'tl' },
];

/* ---------- compact trust badge ---------- */
function TBadge({ k, v, cls, dot, onClick, title }){
  return (
    <button className={'tbadge '+(cls||'')+(onClick?' click':'')} onClick={onClick} title={title} disabled={!onClick}>
      <span className="tb-k">{k}</span>
      <span className="tb-v">{dot&&<span className={'sdot '+dot}></span>}{v}</span>
    </button>
  );
}

function TopBar({ clock, lang, setLang, agents, localPct, egress, setEgress, mic, setMic, dataState, cycleData, onPalette, onAmbient, onAdmin, onHelp, t }){
  const live = agents.filter(a=>a.status!=='idle').length;
  const dataCls = dataState==='live'?'active':dataState==='demo'?'warn':'alert';
  const dataV = dataState==='live'?t.live:dataState==='demo'?t.demo:t.offline;
  return (
    <div className="topbar v3">
      <div className="brand">
        <ReactorS/>
        <div className="brand-tx"><div className="l1">JARVIS</div><div className="l2">{t.sub}</div></div>
        <div className="badges" style={{marginLeft:16}}>
          <TBadge k={t.agents} v={`${live}/${agents.length}`} cls="active" dot="active" title="agents online"/>
          <TBadge k={t.llm} v="gemma·local" cls="ok" title="active model"/>
          <TBadge k={t.local} v={localPct+'%'} cls="ok" title="local compute share"/>
        </div>
      </div>
      <div className="clock">
        <div className="clock-time">{ftS(clock)}</div>
        <div className="clock-date">{fdS(clock,lang)}</div>
      </div>
      <div className="topbar-right">
        <div className="badges">
          <TBadge k={t.egress} v={egress==='sealed'?t.sealed:t.hybrid} cls={egress==='sealed'?'active':'violet'} dot={egress==='sealed'?'active':'cloud'} onClick={()=>setEgress(e=>e==='sealed'?'hybrid':'sealed')} title="egress policy — click to toggle"/>
          <TBadge k={t.mic} v={mic?t.micOn:t.micOff} cls={mic?'active':'dim'} onClick={()=>setMic(m=>!m)} title="microphone — click to toggle"/>
          <TBadge k={t.dataK} v={dataV} cls={dataCls} onClick={cycleData} title="data honesty — click to cycle live/demo/offline"/>
        </div>
        <div className="topbar-tools">
          <button className="tool-btn" onClick={()=>setLang(lang==='en'?'ro':'en')} title="language"><Ics d={IKs.globe} size={13}/>{t.langName}</button>
          <button className="tool-btn" onClick={onAmbient} title="ambient (A)"><Ics d={IKs.ambient} size={13}/></button>
          <button className="tool-btn" onClick={onHelp} title="keyboard shortcuts (?)">?</button>
          <button className="tool-btn" onClick={onPalette} title="command palette (⌘K)">⌘K</button>
          <button className="ident-slot" onClick={onAdmin} title="owner · admin console">
            <span className="id-ring"></span><span className="id-nm">{t.identity||'Andrei'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function Ticker({ items, t, hidden }){
  if(hidden) return null;
  const list = [...items, ...items];
  return (
    <div className="ticker">
      <div className="ticker-head"><span className="dot"></span><span className="lab">{t.situation}</span><span className="sit">{t.allnominal}</span></div>
      <div className="ticker-marq"><div className="ticker-track">
        {list.map((it,i)=>(
          <span className={'ticker-item '+(it.cls||'')} key={i}>
            <span className="agent">{it.agent}</span><span className="verb">{it.verb}</span><span>{it.text}</span>
            <span className="bar"><i style={{width:it.bar+'%'}}></i></span><span className="ticker-sep">│</span>
          </span>
        ))}
      </div></div>
    </div>
  );
}

function Rail({ mode, setMode, counts, onAdmin, t }){
  return (
    <div className="rail" role="navigation" aria-label="Primary modes">
      {MODES_V3.map((m,i)=> m.sep
        ? <div className="rail-sep" key={i}></div>
        : <button key={m.id} className={'rail-btn'+(mode===m.id?' active':'')} onClick={()=>setMode(m.id)} aria-current={mode===m.id?'page':undefined} title={t[m.tkey]+'  ·  '+m.hot}>
            <Ics d={IKs[m.icon]} size={19}/><span className="rl">{t[m.tkey]}</span>
            <span className="rail-hot">{m.hot}</span>
            {m.count && counts[m.count]>0 && <span className={'rail-count'+(m.count==='dec'&&counts.urgent?' urgent':'')}>{counts[m.count]}</span>}
          </button>
      )}
      <div className="rail-spacer"></div>
      <button className={'rail-btn admin'} onClick={onAdmin} title={t.adminConsole+'  ·  gD'}>
        <Ics d={IKs.admin} size={19}/><span className="rl">{t.admin}</span><span className="rail-hot">gD</span>
      </button>
    </div>
  );
}

/* ============================================================
   MODE-SWAPPING CONTEXT COLUMN — ≤4 cards, swaps per mode,
   never mirrors the active canvas (brief §4 + §9)
   ============================================================ */
function CtxCard({ icon, title, st, children, cls }){
  return (
    <div className={'panel'+(cls?' '+cls:'')}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ics d={IKs[icon]} size={14}/><span className="ttl">{title}</span>{st!=null&&<span className="st">{st}</span>}</div>
      <div className="panel-body tight">{children}</div>
    </div>
  );
}

function NotesCard({ notes, setNotes, t }){
  const [v,setV]=uSs('');
  const add=()=>{ if(!v.trim())return; setNotes(n=>[{text:v.trim(),by:'you'},...n]); setV(''); };
  return (
    <CtxCard icon="note" title={t.notesTitle} st={notes.length}>
      <div className="note-add"><input value={v} onChange={e=>setV(e.target.value)} onKeyDown={e=>e.key==='Enter'&&add()} placeholder="Add standing context…"/><button onClick={add}><Ics d={IKs.plus} size={13}/></button></div>
      {notes.map((n,i)=>(
        <div className="note-row" key={i}><span className={'note-by '+(n.ai?'ai':'')}>{n.by}</span><span className="note-tx">{n.text}</span></div>
      ))}
      <div className="note-foot">injected into every turn</div>
    </CtxCard>
  );
}

function WeatherCard({ t }){
  const W=window.V2.WEATHER;
  return (
    <CtxCard icon="observe" title={t.weather} st={W.city}>
      <div className="wcard">
        <div style={{display:'flex',alignItems:'flex-end',gap:14}}>
          <div className="temp">{W.temp}°</div>
          <div style={{paddingBottom:6}}><div style={{fontSize:13,color:'var(--ink)'}}>{W.desc}</div><div style={{fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>feels {W.feels}°</div></div>
        </div>
        <div className="wfore" style={{display:'flex',justifyContent:'space-between',marginTop:14}}>
          {W.forecast.map((f,i)=><div key={i} style={{textAlign:'center',fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>{f.d}<div style={{color:'var(--ink)',marginTop:4}}>{f.t}</div></div>)}
        </div>
      </div>
    </CtxCard>
  );
}
function ScheduleCard({ t }){
  return (
    <CtxCard icon="cockpit" title={t.schedule} st={window.V2.CALENDAR.length}>
      {window.V2.CALENDAR.map((c,i)=>(
        <div className={'cal-row '+(c.state||'')} key={i}><span className="tm">{c.tm}</span><div><div className="ti">{c.ti}</div><div className="vw">{c.vw}</div></div></div>
      ))}
    </CtxCard>
  );
}
function HeartbeatCard({ t }){
  return (
    <CtxCard icon="autonomy" title={t.heartbeat}>
      {window.V2.HEARTBEAT.map((h,i)=>(
        <div className="hbrow" key={i}><div className={'sev '+h.sev}></div><div><div className="ht"><span className="ag">{h.ag}</span><span>{h.t}</span></div><div className="hx">{h.x}</div></div></div>
      ))}
    </CtxCard>
  );
}
function DecisionMiniCard({ decisions, onMode, t }){
  return (
    <CtxCard icon="decisions" title={t.decisions} st={decisions.length} cls={decisions.some(d=>d.urgent)?'pulse-border':''}>
      {decisions.length===0 && <div className="ctx-empty">queue clear ✓</div>}
      {decisions.slice(0,3).map(d=>(
        <button className="dmini" key={d.id} onClick={()=>onMode('decisions')}>
          <span className={'dmini-k kind '+({ACT:'anticip',NOTIFY:'signal',ASK:'alert'}[d.kind])}>{d.kind}</span>
          <span className="dmini-who">{(window.V2.AGENTS.find(a=>a.id===d.agent)||{}).name}</span>
          <span className="dmini-t">{d.title}</span>
        </button>
      ))}
      {decisions.length>3 && <button className="ctx-more" onClick={()=>onMode('decisions')}>+{decisions.length-3} more in Decisions →</button>}
    </CtxCard>
  );
}
function BudgetCard({ t }){
  const I=window.V2.INTERRUPTS;
  return (
    <CtxCard icon="autonomy" title={t.budgetTitle} st={`${I.used}/${I.cap}`}>
      <div className="budget-pips">{Array.from({length:I.cap}).map((_,i)=><span key={i} className={'pip-i big'+(i<I.used?' used':'')}></span>)}</div>
      <div className="budget-note">{I.note}</div>
    </CtxCard>
  );
}
function EscalationsCard({ t }){
  return (
    <CtxCard icon="missions" title={t.escTitle} st={window.V2.ESCALATIONS.length}>
      {window.V2.ESCALATIONS.map((e,i)=>(
        <div className="esc-row" key={i}>
          <span className="gx"><Gls id={e.agent} size={13}/></span>
          <div><div className="esc-r">{e.reason}</div><div className="esc-to">→ {e.to} · {e.budget}</div></div>
          <span className={'esc-st '+(e.status==='auto'?'auto':'q')}>{e.status}</span>
        </div>
      ))}
    </CtxCard>
  );
}
function LocalityCard({ t, egress }){
  return (
    <CtxCard icon="trust" title={t.locality} st="87%">
      <div style={{display:'flex',alignItems:'center',gap:14,marginBottom:8}}>
        <div className="loc-pct" style={{fontSize:30}}>87%</div>
        <div className="loc-legend"><span className="ll"><span className="sw" style={{background:'var(--green)'}}></span>on-device 87%</span><span className="ll"><span className="sw" style={{background:'var(--violet)'}}></span>cloud 13%</span></div>
      </div>
      <div className="loc-bar"><div className="seg local" style={{width:'87%'}}></div><div className="seg cloud" style={{width:'13%'}}></div></div>
      <div className="egress-proof"><Ics d={IKs[egress==='sealed'?'lock':'egress']} size={12}/>{egress==='sealed'?'EGRESS SEALED · LOCAL_ONLY proof: 0 external calls':'HYBRID · cloud hops logged & badged'}</div>
    </CtxCard>
  );
}
function MissionResCard({ onMode, missions, t }){
  const M=(missions||window.V2.MISSIONS).filter(m=>m.status!=='done');
  return (
    <CtxCard icon="missions" title={t.resources} st={M.length+' active'}>
      {M.map((m,i)=>(
        <div className="mres-row" key={i}><span className="gx"><Gls id={m.agent} size={13}/></span><div style={{flex:1}}><div className="mres-t">{m.title}</div><div className="mres-b">{m.budget.label}</div></div><span className="mres-p">{m.progress}%</span></div>
      ))}
    </CtxCard>
  );
}
function NorthStarCard({ t }){
  return (
    <CtxCard icon="observe" title="NORTH STAR" st="weekly">
      <div className="ns-hero"><span className="ns-v">23</span><span className="ns-l">accepted autonomous<br/>actions / week</span></div>
      <div className="ns-guards">
        <div className="ns-g"><span>interrupts</span><span className="ok">1/4 day</span></div>
        <div className="ns-g"><span>%-local</span><span className="ok">87%</span></div>
        <div className="ns-g"><span>p95 latency</span><span>7.8s</span></div>
        <div className="ns-g"><span>reject rate</span><span className="ok">6%</span></div>
      </div>
    </CtxCard>
  );
}
function PeersCard({ t }){
  const N=window.V2.INTEROP, MESH=window.V2.MESH;
  return (
    <CtxCard icon="mesh" title="MESH · PEERS" st={MESH.devices.length}>
      <div className="sysrow"><span className="k">SYNC</span><span className="v acc">{MESH.sync.state}</span></div>
      <div className="sysrow"><span className="k">A2A PEERS</span><span className="v">{N.a2a.length} · {N.a2a.filter(a=>a.status==='connected').length} live</span></div>
      <div className="sysrow"><span className="k">MCP SERVERS</span><span className="v">{N.mcp.length}</span></div>
      <div className="sysrow"><span className="k">CONFLICTS</span><span className="v">{MESH.sync.conflicts}</span></div>
    </CtxCard>
  );
}

function ContextColumn({ mode, decisions, notes, setNotes, onMode, egress, dataState, missions, t }){
  if(dataState==='offline'){
    return <div className="col scrollcol ctx-col">
      <CtxCard icon="egress" title="CONNECTION" st="offline">
        <div className="ofc-note">No live signal from the local API. The badges below reflect <b>last-known</b> state, not current truth.</div>
        <div className="sysrow"><span className="k">API</span><span className="v" style={{color:'var(--red)'}}>unreachable</span></div>
        <div className="sysrow"><span className="k">LAST SYNC</span><span className="v">02:30 today</span></div>
        <div className="sysrow"><span className="k">CACHE</span><span className="v">read-only</span></div>
      </CtxCard>
    </div>;
  }
  let cards;
  switch(mode){
    case 'decisions': cards=[<BudgetCard key="b" t={t}/>,<EscalationsCard key="e" t={t}/>,<NotesCard key="n" notes={notes} setNotes={setNotes} t={t}/>]; break;
    case 'memory':    cards=[<NotesCard key="n" notes={notes} setNotes={setNotes} t={t}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'autonomy':  cards=[<BudgetCard key="b" t={t}/>,<DecisionMiniCard key="d" decisions={decisions} onMode={onMode} t={t}/>,<NotesCard key="n" notes={notes} setNotes={setNotes} t={t}/>]; break;
    case 'missions':  cards=[<MissionResCard key="m" onMode={onMode} missions={missions} t={t}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'trust':     cards=[<LocalityCard key="l" t={t} egress={egress}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'observe':   cards=[<NorthStarCard key="ns" t={t}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'interop':   cards=[<PeersCard key="p" t={t}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'agents':    cards=[<DecisionMiniCard key="d" decisions={decisions} onMode={onMode} t={t}/>,<HeartbeatCard key="h" t={t}/>]; break;
    case 'life': case 'world': cards=[<NotesCard key="n" notes={notes} setNotes={setNotes} t={t}/>,<ScheduleCard key="s" t={t}/>,<WeatherCard key="w" t={t}/>]; break;
    default: /* cockpit */ cards=[<DecisionMiniCard key="d" decisions={decisions} onMode={onMode} t={t}/>,<WeatherCard key="w" t={t}/>,<ScheduleCard key="s" t={t}/>,<HeartbeatCard key="h" t={t}/>];
  }
  return <div className="col scrollcol ctx-col">{cards}</div>;
}

/* ---------- Admin Console drawer (owner-gated; replaces hidden console) ---------- */
function AdminDrawer({ open, onClose, t }){
  if(!open) return null;
  const AdminMode = window.AdminMode;
  return (
    <>
      <div className="dossier-scrim" onClick={onClose}></div>
      <div className="dossier admin-drawer" role="dialog" aria-modal="true" aria-label={t.adminConsole}>
        <div className="dossier-head">
          <span className="big-glyph"><Ics d={IKs.admin} size={36}/></span>
          <div style={{flex:1}}><div className="nm" style={{fontSize:18}}>{t.adminConsole}</div><div className="ar">owner-gated · not on the end-user rail</div></div>
          <button className="close" aria-label="Close" onClick={onClose}><Ics d={IKs.x} size={16}/></button>
        </div>
        <div className="dossier-body"><AdminMode t={t}/></div>
      </div>
    </>
  );
}

/* ---------- Honesty banners ---------- */
function HonestyBanner({ dataState, onLive, t }){
  if(dataState==='live') return null;
  const demo = dataState==='demo';
  return (
    <div className={'honesty '+(demo?'demo':'offline')}>
      <span className="hb-dot"></span>
      <span className="hb-tx">{demo?t.demoBanner:t.offlineBanner}</span>
      <button className="hb-btn" onClick={onLive}>{t.live} →</button>
    </div>
  );
}

/* ---------- Command palette (full IA + actions + g-chords) ---------- */
function Palette({ open, onClose, onMode, setAccent, setLang, onAmbient, onAdmin, cycleData, setEgress, t }){
  const [q,setQ]=uSs(''); const [sel,setSel]=uSs(0); const inputRef=uRs(null);
  uEs(()=>{ if(open){ setQ(''); setSel(0); setTimeout(()=>inputRef.current&&inputRef.current.focus(),30);} },[open]);
  const cmds = uMs(()=>[
    { g:'Go to', items:[
      { name:'Cockpit', hint:'1', act:()=>onMode('cockpit'), icon:'cockpit' },
      { name:'Decision Inbox', hint:'2', act:()=>onMode('decisions'), icon:'decisions' },
      { name:'Agents · the Cabinet', hint:'3', act:()=>onMode('agents'), icon:'agents' },
      { name:'Memory & Knowledge', hint:'4', act:()=>onMode('memory'), icon:'memory' },
      { name:'Autonomy', hint:'5', act:()=>onMode('autonomy'), icon:'autonomy' },
      { name:'Missions', hint:'6', act:()=>onMode('missions'), icon:'missions' },
      { name:'Trust Center', hint:'7', act:()=>onMode('trust'), icon:'trust' },
      { name:'Build', hint:'8', act:()=>onMode('build'), icon:'build' },
      { name:'Observe', hint:'9', act:()=>onMode('observe'), icon:'observe' },
      { name:'Interop + Mesh', hint:'0', act:()=>onMode('interop'), icon:'interop' },
      { name:'Life · Finance / Health / Family / Knowledge', hint:'gL', act:()=>onMode('life'), icon:'life' },
      { name:'World · Argus signal layer', hint:'gW', act:()=>onMode('world'), icon:'globe' },
      { name:'Today in Jarvis · activity timeline', hint:'gT', act:()=>onMode('timeline'), icon:'clock' },
      { name:'Comms · unified inbox', hint:'gC', act:()=>onMode('comms'), icon:'comms' },
      { name:'Ambient display', hint:'A', act:onAmbient, icon:'ambient' },
      { name:'Admin Console · owner', hint:'gD', act:onAdmin, icon:'admin' },
    ]},
    { g:'Actions', items:[
      { name:'New session', act:()=>onMode('cockpit'), icon:'chat' },
      { name:'Remember a fact…', act:()=>onMode('memory'), icon:'plus' },
      { name:'Ingest transcript → governed tasks', act:()=>onMode('decisions'), icon:'note' },
      { name:'Parse schedule (phrase → cron)', act:()=>onMode('autonomy'), icon:'autonomy' },
      { name:'Run digest now', act:()=>onMode('autonomy'), icon:'bolt' },
      { name:'Browser-plan preview (consent)', act:()=>onMode('decisions'), icon:'flow' },
      { name:'Scan untrusted text (spotlight)', act:()=>onMode('trust'), icon:'shield' },
      { name:'Run eval', act:()=>onMode('observe'), icon:'observe' },
      { name:'Go LIVE (data)', act:cycleData, icon:'data' },
      { name:'Toggle egress · sealed / hybrid', act:()=>setEgress(e=>e==='sealed'?'hybrid':'sealed'), icon:'egress' },
    ]},
    { g:'Theme', items:[
      { name:'Accent · Cyan', act:()=>setAccent('cyan'), icon:'bolt' },
      { name:'Accent · Amber', act:()=>setAccent('amber'), icon:'bolt' },
      { name:'Accent · Green', act:()=>setAccent('green'), icon:'bolt' },
      { name:'Accent · Violet', act:()=>setAccent('violet'), icon:'bolt' },
      { name:'Toggle language EN / RO', act:()=>setLang(l=>l==='en'?'ro':'en'), icon:'globe' },
    ]},
  ],[onMode,setAccent,setLang,onAmbient,onAdmin,cycleData,setEgress]);
  const flat = uMs(()=>{ const f=[]; cmds.forEach(grp=>grp.items.forEach(it=>{ if(!q||it.name.toLowerCase().includes(q.toLowerCase())) f.push({...it,g:grp.g}); })); return f; },[cmds,q]);
  uEs(()=>{ setSel(0); },[q]);
  if(!open) return null;
  const run=it=>{ it.act(); onClose(); };
  const onKey=e=>{
    if(e.key==='ArrowDown'){e.preventDefault();setSel(s=>Math.min(flat.length-1,s+1));}
    else if(e.key==='ArrowUp'){e.preventDefault();setSel(s=>Math.max(0,s-1));}
    else if(e.key==='Enter'){e.preventDefault(); if(flat[sel])run(flat[sel]);}
    else if(e.key==='Escape'){onClose();}
  };
  let lastG=null;
  return (
    <div className="pal-scrim" onClick={onClose}>
      <div className="pal" onClick={e=>e.stopPropagation()}>
        <div className="pal-input"><span className="pc">⌘</span><input ref={inputRef} value={q} onChange={e=>setQ(e.target.value)} onKeyDown={onKey} placeholder={t.cmd+'…'}/></div>
        <div className="pal-list">
          {flat.length===0 && <div className="pal-group">no matches</div>}
          {flat.map((it,i)=>{ const head=it.g!==lastG; lastG=it.g; return (
            <React.Fragment key={i}>
              {head && <div className="pal-group">{it.g}</div>}
              <div className={'pal-item'+(i===sel?' sel':'')} onMouseEnter={()=>setSel(i)} onClick={()=>run(it)}>
                <Ics d={IKs[it.icon]} size={16}/><span className="pi-name">{it.name}</span>{it.hint&&<span className="pi-hint">{it.hint}</span>}
              </div>
            </React.Fragment>
          );})}
        </div>
        <div className="pal-foot"><span><kbd>↑↓</kbd> navigate</span><span><kbd>↵</kbd> run</span><span><kbd>esc</kbd> close</span><span style={{marginLeft:'auto'}}>1–0 modes · g+L/W/C/D · A ambient</span></div>
      </div>
    </div>
  );
}

function Ambient({ onExit, clock, lang, agents, decisions, motion, egress, t }){
  uEs(()=>{ const h=e=>{ if(e.key==='Escape')onExit(); }; window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h); },[onExit]);
  const strip=s=>String(s).replace(/<[^>]+>/g,'').replace(/\*\*/g,'');
  return (
    <div className="ambient" onClick={onExit}>
      <div className="amb-clock">{ftsS(clock)}</div>
      <div className="amb-date">{fdS(clock,lang)}</div>
      <svg className="ambient-ekg" viewBox="0 0 340 60" preserveAspectRatio="none"><path className={motion!=='calm'?'ambient-anim':''} d="M0,30 L80,30 L92,30 L100,10 L110,50 L120,30 L160,30 L172,22 L180,38 L190,30 L340,30"/></svg>
      <div className="amb-heart">
        <div className="amb-stat"><div className="v">{agents.filter(a=>a.status!=='idle').length}/{agents.length}</div><div className="l">{t.agents}</div></div>
        <div className="amb-sep"></div><div className="amb-stat"><div className="v">87%</div><div className="l">{t.local}</div></div>
        <div className="amb-sep"></div><div className="amb-stat"><div className="v">{decisions.length}</div><div className="l">{t.pending}</div></div>
        <div className="amb-sep"></div><div className="amb-stat"><div className="v" style={{color:egress==='sealed'?'var(--green)':'var(--violet)'}}>{egress==='sealed'?'SEALED':'HYBRID'}</div><div className="l">{t.egress}</div></div>
      </div>
      {decisions.length>0 && (
        <div className="amb-pending">{decisions.slice(0,3).map(d=><div className="ap" key={d.id}><span className="dot"></span><span style={{color:'var(--accent-light)'}}>{(window.V2.AGENTS.find(a=>a.id===d.agent)||{}).name}</span> {strip(d.title)}</div>)}</div>
      )}
      <div className="amb-exit">{t.exitAmbient}</div>
    </div>
  );
}

/* ---------- keyboard help overlay (discoverable shortcut contract) ---------- */
function HelpOverlay({ open, onClose, t }){
  uEs(()=>{ const h=e=>{ if(e.key==='Escape')onClose(); }; if(open) window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h); },[open,onClose]);
  if(!open) return null;
  const groups=[
    { g:t.help_primary||'Primary modes', items:[['1','Cockpit'],['2','Decision Inbox'],['3','Agents'],['4','Memory'],['5','Autonomy'],['6','Missions'],['7','Trust'],['8','Build'],['9','Observe'],['0','Interop + Mesh']] },
    { g:t.help_cluster||'Clusters · press g, then…', items:[['g L','Life · Fin/Health/Family/Know'],['g W','World · Argus'],['g T','Today in Jarvis'],['g C','Comms'],['g N','Network · data layer'],['g D','Admin Console']] },
    { g:t.help_global||'Global', items:[['⌘K','Command palette'],['A','Ambient display'],['?','This help'],['esc','Close / clear']] },
  ];
  return (
    <div className="pal-scrim" onClick={onClose} style={{alignItems:'center',paddingTop:0}}>
      <div className="help-card" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={e=>e.stopPropagation()}>
        <div className="help-head"><Ics d={IKs.bolt} size={15}/><span>{t.help_title||'KEYBOARD'}</span><span className="help-sub">{t.help_sub||'every mode & overlay is reachable without the mouse'}</span><button className="close" aria-label="Close" onClick={onClose}><Ics d={IKs.x} size={15}/></button></div>
        <div className="help-grid">
          {groups.map((grp,i)=>(
            <div className="help-col" key={i}>
              <div className="help-g">{grp.g}</div>
              {grp.items.map(([k,lab],j)=><div className="help-row" key={j}><kbd>{k}</kbd><span>{lab}</span></div>)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- honest OFFLINE state (per brief §9: prefer "offline, here's what to do" over silent empty) ---------- */
function OfflineState({ mode, onDemo, onRetry, t }){
  const map={ cockpit:'the conversation & cognition stream', decisions:'the decision queue', agents:'the Cabinet roster', memory:'memory & the knowledge graph', autonomy:'autonomy policies & briefs', missions:'mission workspaces', trust:'the audit chain & locality proof', build:'workflows & skills', observe:'metrics & traces', interop:'peers, MCP servers & mesh', life:'your Life views', world:'the world signal layer', comms:'the unified inbox' };
  return (
    <div className="panel offline-state" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="offline-wrap">
        <div className="offline-ico"><Ics d={IKs.egress} size={32}/></div>
        <div className="offline-h">BACKEND OFFLINE</div>
        <div className="offline-sub">{map[mode]||'this view'} needs the local API. Jarvis is showing <b>nothing</b> rather than stale data — that’s the honesty rule, not a bug.</div>
        <div className="offline-steps">
          <div className="ofs"><span className="ofs-k">1</span><span>Start the API · <code>localhost:4000</code></span></div>
          <div className="ofs"><span className="ofs-k">2</span><span>or run the demo feed for synthetic data</span></div>
        </div>
        <div className="offline-actions">
          <button className="da-btn primary" onClick={onRetry}><Ics d={IKs.check} size={13}/> Retry connection</button>
          <button className="da-btn" onClick={onDemo}>Use demo data</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- first-run onboarding (H23.20 — the first ten minutes) ---------- */
function Onboarding({ onDone, t }){
  const [step,setStep]=uSs(0);
  const [data,setData]=uSs('');
  const [model,setModel]=uSs('gemma'); const [pulled,setPulled]=uSs(0);
  const [caps,setCaps]=uSs({calendar:true, email:true, finance:false, family:true});
  const [notes,setNotes]=uSs(['Protect mornings before 09:00 for deep work']);
  const [draft,setDraft]=uSs('');
  const MODELS=[{id:'gemma',n:'gemma-4-26b',d:'balanced · 26B MoE · Apache-2.0',rec:true},{id:'qwen',n:'Qwen3-30B-A3B',d:'reasoning · hybrid thinking'},{id:'llama',n:'Llama-3.3-8B',d:'fast · lightweight'}];
  const pull=()=>{ setPulled(1); let p=1; const iv=setInterval(()=>{ p+=6+Math.random()*16; if(p>=100){p=100;clearInterval(iv);} setPulled(Math.round(p)); },170); };
  const STEPS=4; const last=step===STEPS-1;
  const finish=()=>{ try{ localStorage.setItem('jarvis_onb',JSON.stringify({data,model,caps,notes})); }catch(e){} onDone(data); };
  const next=()=> last?finish():setStep(s=>s+1);
  return (
    <div className="pal-scrim" style={{alignItems:'center',paddingTop:0}}>
      <div className="onb wiz" role="dialog" aria-modal="true" aria-label="Set up Jarvis">
        <div className="onb-prog"><div className="onb-progf" style={{width:((step+1)/STEPS*100)+'%'}}></div></div>
        <div className="onb-stepn">SET UP · STEP {step+1} / {STEPS}</div>

        {step===0 && (<React.Fragment>
          <div className="onb-ic"><Ics d={IKs.egress} size={28}/></div>
          <div className="onb-h">Connect to your Jarvis</div>
          <div className="onb-b">Run it locally and go live, or explore with watermarked demo data first. Either way, everything stays on your machine.</div>
          <div className="wiz-choice">
            <button className={'wc'+(data==='live'?' on':'')} onClick={()=>setData('live')}><b>Connect live</b><span>localhost:4000 · your backend</span></button>
            <button className={'wc'+(data==='demo'?' on':'')} onClick={()=>setData('demo')}><b>Explore demo</b><span>synthetic · watermarked</span></button>
          </div>
        </React.Fragment>)}

        {step===1 && (<React.Fragment>
          <div className="onb-ic"><Ics d={IKs.data} size={28}/></div>
          <div className="onb-h">Choose a local model</div>
          <div className="onb-b">Inference runs on your hardware — $0 cloud, fully private. Pick a default; switch any time in Admin.</div>
          <div className="wiz-models">
            {MODELS.map(m=>(<button key={m.id} className={'wm'+(model===m.id?' on':'')} onClick={()=>{setModel(m.id);setPulled(0);}}><div className="wm-n">{m.n}{m.rec&&<span className="wm-rec">recommended</span>}</div><div className="wm-d">{m.d}</div></button>))}
          </div>
          {pulled===0 ? <button className="da-btn primary" onClick={pull}><Ics d={IKs.data} size={12}/> Pull model</button>
            : pulled<100 ? <div className="wiz-pull"><div className="wiz-pullf" style={{width:pulled+'%'}}></div><span>pulling · {pulled}%</span></div>
            : <div className="wiz-ready"><Ics d={IKs.check} size={13}/> ready · loaded on-device</div>}
        </React.Fragment>)}

        {step===2 && (<React.Fragment>
          <div className="onb-ic"><Ics d={IKs.shield} size={28}/></div>
          <div className="onb-h">Grant first capabilities</div>
          <div className="onb-b">Least-privilege by default — turn on what the Cabinet may reach. Every grant is revocable and audited.</div>
          <div className="wiz-caps">
            {[['calendar','Calendar','Pepper schedules & protects time'],['email','Email','Veronica drafts; held for review'],['finance','Finance','Gecko watches markets (read-only)'],['family','Family · local-only','Frigga — never leaves device']].map(([k,n,d])=>(
              <label className="wcap" key={k}><input type="checkbox" checked={caps[k]} onChange={e=>setCaps(c=>({...c,[k]:e.target.checked}))}/><div><div className="wcap-n">{n}</div><div className="wcap-d">{d}</div></div></label>
            ))}
          </div>
        </React.Fragment>)}

        {step===3 && (<React.Fragment>
          <div className="onb-ic"><Ics d={IKs.note} size={28}/></div>
          <div className="onb-h">Seed your standing context</div>
          <div className="onb-b">Notes Jarvis injects into every turn — your preferences, boundaries, the way you like things done.</div>
          <div className="wiz-notes">
            {notes.map((n,i)=><div className="wiz-note" key={i}><span>{n}</span><button onClick={()=>setNotes(x=>x.filter((_,j)=>j!==i))} aria-label="remove"><Ics d={IKs.x} size={11}/></button></div>)}
            <div className="wiz-noteadd"><Ics d={IKs.plus} size={13}/><input value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{ if(e.key==='Enter'&&draft.trim()){ setNotes(x=>[...x,draft.trim()]); setDraft(''); } }} placeholder="Add a standing note…"/></div>
          </div>
        </React.Fragment>)}

        <div className="onb-dots">{[0,1,2,3].map(i=><span key={i} className={'onb-dot'+(i===step?' on':'')}></span>)}</div>
        <div className="onb-acts">
          <button className="onb-skip" onClick={()=>onDone(data)}>Skip setup</button>
          <div style={{display:'flex',gap:8}}>
            {step>0 && <button className="onb-skip" onClick={()=>setStep(s=>s-1)}>Back</button>}
            <button className="onb-next" disabled={step===0&&!data} onClick={next}>{last?'Enter the HUD →':'Next'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- cinema mode — full-bleed mesh, framed for a vertical social demo ---------- */
function CinemaMesh({ agents, onExit, t }){
  const [tag,setTag]=uSs(0); const [feed,setFeed]=uSs([]);
  uEs(()=>{ const iv=setInterval(()=>setTag(x=>x+1),4200); return ()=>clearInterval(iv); },[]);
  uEs(()=>{ const h=e=>{ if(e.key==='Escape')onExit(); }; window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h); },[onExit]);
  uEs(()=>{ if(!window.JarvisMock) return; return window.JarvisMock.streamSub(evt=>{ const row=window.eventToTimelineRow&&window.eventToTimelineRow(evt); if(row) setFeed(f=>[{who:row.agent,title:row.title},...f].slice(0,3)); }); },[]);
  const TAGS=['Your governed AI cabinet','17 agents · on-device · always-on','Proactive. Private. Provable.','The most capable local AI on earth'];
  const NM=window.NeuralMesh; const live=agents.filter(a=>a.status!=='idle').length;
  return (
    <div className="cinema">
      <div className="cin-top">
        <div className="cin-mark"><ReactorS/><span className="cin-word">JARVIS</span></div>
        <div className="cin-tag" key={tag}>{TAGS[tag%TAGS.length]}</div>
      </div>
      <div className="cin-stage">{NM && <NM agents={agents} cinema={true} motion="lively" onSelect={()=>{}} t={t}/>}</div>
      <div className="cin-bottom">
        <div className="cin-feed">
          {feed.length===0 && <div className="cin-frow"><span className="cin-dot"></span>the Cabinet is working…</div>}
          {feed.map((r,i)=><div className="cin-frow" key={i}><span className="cin-dot"></span><b>{(window.V2.AGENTS.find(a=>a.id===r.who)||{}).name||r.who}</b> {r.title}</div>)}
        </div>
        <div className="cin-stats"><span><b>{live}</b> agents live</span><span><b>87%</b> on-device</span><span className="cin-ok">EGRESS SEALED</span><span><b>0</b> cloud leaks</span></div>
      </div>
      <button className="cin-exit" onClick={onExit}>Esc</button>
    </div>
  );
}

Object.assign(window, { MODES_V3, TopBar, Ticker, Rail, ContextColumn, Palette, Ambient, AdminDrawer, HonestyBanner, HelpOverlay, OfflineState, Onboarding, CinemaMesh });
