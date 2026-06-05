// @ts-nocheck
/* HUD v2 · SHELL — topbar, nav, ticker, right column, ambient, palette */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Icon, ICONS, Glyph, Reactor, Meter, statusClass, fmtTime, fmtTimeShort, fmtDate } from './primitives';
import { renderRich } from './cockpit';
import { V2 } from './data';

const MODES = [
  { id:'cockpit', icon:'cockpit', tkey:'cockpit', live:true },
  { id:'chat', icon:'chat', tkey:'chat' },
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

function TopBar({ clock, lang, setLang, accent, agents, localPct, live, onPalette, onAmbient, t }){
  return (
    <div className="topbar">
      <div className="brand">
        <Reactor/>
        <div className="brand-tx"><div className="l1">JARVIS</div><div className="l2">{t.sub}</div></div>
        <div className="badges" style={{marginLeft:18}}>
          <div className="badge active"><div className="k">{t.online}</div><div className="v"><span className="sdot active"></span>{agents.filter(a=>a.status!=='idle').length}/{agents.length}</div></div>
          <div className="badge ok"><div className="k">{t.local}</div><div className="v">{localPct}%</div></div>
          <div className={'badge' + (live ? ' ok' : '')} title={live ? 'live backend data' : 'seed data — backend unreachable'}><div className="k">DATA</div><div className="v">{live ? '● LIVE' : '○ SEED'}</div></div>
        </div>
      </div>
      <div className="clock">
        <div className="clock-time">{fmtTime(clock)}</div>
        <div className="clock-date">{fmtDate(clock,lang)}</div>
      </div>
      <div className="badges">
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
function ContextColumn({ decisions, onDecision, weather, calendar, heartbeat, t }){
  const D = { WEATHER: weather || V2.WEATHER, CALENDAR: calendar || V2.CALENDAR, HEARTBEAT: heartbeat || V2.HEARTBEAT };
  return (
    <div className="col scrollcol">
      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.bolt} size={14}/><span className="ttl">{t.decisions}</span><span className="st">{decisions.length}</span></div>
        <div className="panel-body tight">
          {decisions.length===0 && <div style={{color:'var(--ink-3)',fontSize:12,textAlign:'center',padding:'18px 0'}}>queue clear ✓</div>}
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
        <div className="panel-head"><Icon d={ICONS.observe} size={14}/><span className="ttl">{t.weather}</span><span className="st">{D.WEATHER.city}</span></div>
        <div className="panel-body wcard">
          <div style={{display:'flex',alignItems:'flex-end',gap:14}}>
            <div className="temp">{D.WEATHER.temp}°</div>
            <div style={{paddingBottom:6}}><div style={{fontSize:13,color:'var(--ink)'}}>{D.WEATHER.desc}</div><div style={{fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>feels {D.WEATHER.feels}°</div></div>
          </div>
          <div className="wgrid">
            <span className="wk">WIND</span><span className="wv">{D.WEATHER.wind}</span>
            <span className="wk">HUMIDITY</span><span className="wv">{D.WEATHER.humidity}</span>
          </div>
          <div className="wfore" style={{display:'flex',justifyContent:'space-between',marginTop:14}}>
            {D.WEATHER.forecast.map((f,i)=><div key={i} style={{textAlign:'center',fontFamily:'var(--font-mono)',fontSize:10,color:'var(--ink-3)'}}>{f.d}<div style={{color:'var(--ink)',marginTop:4}}>{f.t}</div></div>)}
          </div>
        </div>
      </div>

      <div className="panel">
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.cockpit} size={14}/><span className="ttl">{t.schedule}</span><span className="st">{D.CALENDAR.length}</span></div>
        <div className="panel-body tight">
          {D.CALENDAR.map((c,i)=>(
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
        <div className="panel-body tight">
          {D.HEARTBEAT.map((h,i)=>(
            <div className="hbrow" key={i}><div className={'sev '+h.sev}></div><div><div className="ht"><span className="ag">{h.ag}</span><span>{h.t}</span></div><div className="hx">{h.x}</div></div></div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* LEFT roster column (cockpit only) */
function RosterColumn({ agents, activeId, onSelect, sys, t }){
  const TIERS=V2.TIERS;
  return (
    <div className="col">
      <div className="panel scroll" style={{flex:'1 1 auto'}}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.agents} size={14}/><span className="ttl">{t.roster}</span><span className="st">{agents.filter(a=>a.status!=='idle').length} live</span></div>
        <div className="panel-body tight">
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
        <div className="panel-body tight">
          {(() => { const S = sys || {}; const pct = (u, tot, f) => (tot ? Math.round((u / tot) * 100) : f);
            return (<>
              <Meter label="RAM" val={pct(S.ram_used, S.ram_total, 22)}/>
              <Meter label="VRAM" val={pct(S.vram_used, S.vram_total, 42)}/>
              <Meter label="GPU" val={S.gpu_load != null ? Math.round(S.gpu_load) : 30}/>
              <div className="sysrow"><span className="k">BACKEND</span><span className="v acc">{S.backend ? (S.backend + (S.model ? ' · ' + S.model : '')) : 'llama.cpp · gemma-4-26b'}</span></div>
              <div className="sysrow"><span className="k">LATENCY p50</span><span className="v">{S.latency != null ? S.latency + 's' : '4.2s'}</span></div>
            </>);
          })()}
        </div>
      </div>
    </div>
  );
}

/* COMMAND PALETTE */
function Palette({ open, onClose, onMode, setAccent, setLang, onAmbient, t }){
  const [q,setQ]=useState('');
  const [sel,setSel]=useState(0);
  const inputRef=useRef(null);
  useEffect(()=>{ if(open){ setQ(''); setSel(0); setTimeout(()=>inputRef.current&&inputRef.current.focus(),30);} },[open]);
  const cmds = useMemo(()=>[
    { g:'Go to', items:[
      { name:'Cockpit', hint:'1', act:()=>onMode('cockpit'), icon:'cockpit' },
      { name:'Chat · focus', hint:'9', act:()=>onMode('chat'), icon:'chat' },
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
  ],[onMode,setAccent,setLang,onAmbient]);
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
function Ambient({ onExit, clock, lang, agents, decisions, motion, t }){
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
        <div className="amb-sep"></div>
        <div className="amb-stat"><div className="v">87%</div><div className="l">{t.local}</div></div>
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

export { MODES, TopBar, Ticker, Rail, Tabs, ContextColumn, RosterColumn, Palette, Ambient };
