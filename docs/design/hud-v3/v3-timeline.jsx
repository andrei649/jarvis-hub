'use strict';
/* HUD v3 · TIMELINE ("Today in Jarvis") + per-agent capability SCOPES matrix */
const { useState:uSt, useMemo:uMt } = React;
const { Icon:Ict, ICONS:IKt, Glyph:Glt } = window;

/* ============ TODAY IN JARVIS · live activity tail ============ */
function TimelineMode({ res, live, onMode, conn, onOpenNet, t }){
  const K = window.V2.TIMELINE_KINDS;
  const [filter,setFilter]=uSt('all');
  const base = res && res.data ? res.data : [];
  const merged = uMt(()=> [...(live||[]), ...base.slice().reverse()], [live, base]);
  const FILTERS = [['all',t.tlAll],['action',t.tlActions],['decision',t.tlDecisions],['lesson',t.tlLearned],['guard',t.tlGuarded]];
  const list = uMt(()=> filter==='all'?merged:merged.filter(e=>e.kind===filter), [merged,filter]);
  const counts = merged.reduce((m,e)=>{ m[e.kind]=(m[e.kind]||0)+1; return m; },{});
  const showSkeleton = res && res.loading && !res.data;
  const hardError = res && res.error && !res.data;
  const Strip = window.TelemetryStrip;

  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <Ict d={IKt.clock} size={14}/><span className="ttl">{t.timelineTitle}</span>
        <span className="st">{showSkeleton?'loading…':`${merged.length} events`}</span>
        <span style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:10}}>
          <span className="mis-live" title="streaming the live activity tail"><span className="ml-dot"></span>live tail</span>
          {Strip && <Strip conn={conn}/>}
          {onOpenNet && <button className="net-btn" onClick={onOpenNet} title="network inspector"><Ict d={IKt.flow} size={13}/></button>}
        </span>
      </div>
      <div className="dec-subbar">
        <div className="dec-filters">
          {FILTERS.map(([k,lab])=>(
            <button key={k} className={'cf'+(filter===k?' on':'')} onClick={()=>setFilter(k)}>
              {lab}{k!=='all'&&counts[k]?<span className="cf-n">{counts[k]}</span>:''}
            </button>
          ))}
        </div>
        <div className="dec-budget-inline"><span className="dbi-k">{t.timelineSub}</span></div>
      </div>
      {res&&res.stale && (
        <div className="stale-banner"><span className="sb-dot"></span><span>Showing last-good ledger — couldn't refresh. Live tail still active.</span><button className="sb-btn" onClick={res.refetch}>Retry</button></div>
      )}
      <div className="panel-body" style={{paddingTop:14}}>
        {showSkeleton ? (
          <div className="tl-wrap"><div className="tl-spine"></div>{[0,1,2,3].map(i=>(
            <div className="tl-row" key={i} style={{opacity:.5}}><div className="tl-time"></div><div className="tl-node"></div><div className="tl-card"><div className="sk-line w50"></div><div className="sk-line w90" style={{marginTop:8}}></div></div></div>
          ))}</div>
        ) : hardError ? (
          <div className="empty-state error-state"><Ict d={IKt.x} size={26}/><div className="es-big">Couldn't load the activity ledger</div><div className="es-sub">{res.error.offline?'The backend is unreachable.':'Server error.'} The live tail resumes when the connection returns.</div><div className="es-actions"><button className="da-btn primary" onClick={res.refetch}>Retry</button>{onOpenNet&&<button className="da-btn" onClick={onOpenNet}>Open inspector</button>}</div></div>
        ) : (
        <div className="tl-wrap" role="log" aria-label="Live activity" aria-live="polite" aria-relevant="additions">
          <div className="tl-spine"></div>
          <div className="tl-row now">
            <div className="tl-time">{t.now}</div>
            <div className="tl-node now"><span className="now-pulse"></span></div>
            <div className="tl-card now-card"><div className="tl-title">Live — watching the Cabinet</div><div className="tl-detail">Decisions, missions, and lessons appear here the moment they happen.</div></div>
          </div>
          {list.map((e,i)=>{
            const k=K[e.kind]||K.action; const a=window.V2.AGENTS.find(x=>x.id===e.agent)||{name:e.agent,role:''};
            return (
              <div className={'tl-row '+k.c+(e._live?' tl-new':'')} key={(e._live?'l':'b')+'-'+i+'-'+(e.title||'').slice(0,8)}>
                <div className="tl-time">{e.t}</div>
                <div className="tl-node"><Ict d={IKt[k.ic]} size={12}/></div>
                <div className="tl-card">
                  <div className="tl-top">
                    <span className="tl-glyph"><Glt id={e.agent} size={14}/></span>
                    <span className="tl-agent">{a.name}</span>
                    <span className={'tl-kind '+k.c}>{k.l}</span>
                    {e._live && <span className="tl-livetag">live</span>}
                    <span className={'tl-loc '+(e.local?'local':'cloud')}>{e.local?'on-device':'cloud'}</span>
                  </div>
                  <div className="tl-title">{e.title}</div>
                  <div className="tl-detail">{e.detail}</div>
                  {e.kind==='decision' && <button className="tl-jump" onClick={()=>onMode('decisions')}>open in Decisions →</button>}
                  {e.kind==='mission' && <button className="tl-jump" onClick={()=>onMode('missions')}>open in Missions →</button>}
                  {e.kind==='lesson' && <button className="tl-jump" onClick={()=>onMode('memory')}>view in Memory →</button>}
                </div>
              </div>
            );
          })}
        </div>
        )}
      </div>
    </div>
  );
}

/* ============ PER-AGENT SCOPES · least-privilege matrix ============ */
function AgentScopesMatrix({ t }){
  const CAPS=window.V2.SCOPE_CAPS, ROWS=window.V2.AGENT_SCOPES, LV=window.V2.SCOPE_LEVELS;
  return (
    <div className="scopes-card">
      <div className="dl scopes-dl">{t.scopesTitle}</div>
      <div className="scopes-sub">{t.scopesSub}</div>
      <div className="scopes-table" style={{gridTemplateColumns:`128px repeat(${CAPS.length},1fr)`}}>
        <div className="sc-h sc-corner">agent</div>
        {CAPS.map(c=><div className="sc-h" key={c.id} title={c.hint}>{c.label}</div>)}
        {ROWS.map(r=>{
          const a=window.V2.AGENTS.find(x=>x.id===r.id)||{name:r.id,role:''};
          return (
            <React.Fragment key={r.id}>
              <div className="sc-agent"><span className="gx"><Glt id={r.id} size={13}/></span><span className="sc-nm">{a.name}</span></div>
              {CAPS.map(c=>{ const lv=LV[r[c.id]]||LV.deny; return <div className="sc-cell" key={c.id}><span className={'sc-chip '+lv.c}>{lv.l}</span></div>; })}
            </React.Fragment>
          );
        })}
      </div>
      <div className="scopes-legend">
        {[['allow','allow · always'],['scoped','scoped · bounded'],['ask','ask · needs you'],['deny','— · denied']].map(([c,lab])=>(
          <span className="scl" key={c}><span className={'sc-chip '+c} style={{minWidth:0,padding:'1px 7px'}}>{c==='deny'?'—':c}</span>{lab.split('·')[1]}</span>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { TimelineMode, AgentScopesMatrix });
