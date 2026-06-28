'use strict';
/* HUD v3 · DECISIONS (north-star) + MISSIONS — the two new P0/P1 canvases */
const { useState:uSd, useMemo:uMd } = React;
const { Icon:Icd, ICONS:IKd, Glyph:Gld, renderRich:rrD } = window;

/* kind → tag class (reuse .dcard .kind colors) */
const KIND_TAG = { ACT:'anticip', NOTIFY:'signal', ASK:'alert' };
const RISK_CLS = { allow:'allow', reversible:'allow', flag:'gated', gated:'gated', approval:'gated', deny:'alert' };

function AgentName({ id }){
  const a = (window.V2.AGENTS.find(x=>x.id===id))||{name:id,role:''};
  return <span className="dec-agent"><span className="gx"><Gld id={id} size={15}/></span><b>{a.name}</b><span className="dec-role">{a.role}</span></span>;
}

/* ---------- one decision card ---------- */
function DecisionCard({ d, onResolve, pending, t }){
  const [open,setOpen]=uSd(false);
  const [confirm,setConfirm]=uSd(false);
  const [editing,setEditing]=uSd(false);
  const [editTxt,setEditTxt]=uSd('');
  const [replan,setReplan]=uSd(-1);
  const REPLAN_STAGES=['classify','route','synthesize','commit'];
  const startReplan=()=>{
    setReplan(0);
    [620,1240,1960,2700].forEach((ms,i)=>setTimeout(()=>{ i<3?setReplan(i+1):onResolve(d.id,'edit',{patch:editTxt}); },ms));
  };
  const irreversible = d.bucket==='irreversible';
  const tag = KIND_TAG[d.kind]||'anticip';
  return (
    <div className={'panel dec-card'+(d.urgent?' urgent':'')+(pending?' committing':'')+(d._new?' arrived':'')}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="dec-top">
        <AgentName id={d.agent}/>
        <span className="dec-meta">
          <span className={'dcard-kind kind '+tag}>{d.kind}</span>
          <span className={'dec-bucket '+(irreversible?'irr':'rev')}>{irreversible?t.irreversible:t.reversible}</span>
          <span className="dec-ts">{d.ts}</span>
        </span>
      </div>
      <div className="dec-title">{d.title}</div>
      <div className="dec-why">{rrD(d.why)}</div>

      <div className="dec-dry"><span className="dry-k">DRY RUN</span><span>{d.dryRun}</span></div>

      {d.preflight.length>0 && (
        <button className={'pf-toggle'+(open?' open':'')} onClick={()=>setOpen(o=>!o)}>
          <Icd d={IKd.flow} size={13}/> {t.preflight} · {d.preflight.length} {open?'▾':'▸'}
        </button>
      )}
      {open && (
        <div className="pf-list">
          {d.preflight.map((p,i)=>(
            <div className="pf-row" key={i}>
              <span className="pf-tool">{p.tool}</span>
              <span className="pf-scope">{p.scope}</span>
              <span className="pf-prev">{p.preview}</span>
              <span className={'pf-risk '+(RISK_CLS[p.risk]||'gated')}>{p.risk}</span>
            </div>
          ))}
        </div>
      )}

      {pending ? (
        <div className="dec-committing"><span className="replan-spin"></span>{t.committing||'committing…'}</div>
      ) : editing ? (
        <div className="dec-edit">
          {replan<0 ? (
            <>
              <div className="dec-edit-l">edit the action before approving — Jarvis re-plans your change before it commits</div>
              <textarea value={editTxt} onChange={e=>setEditTxt(e.target.value)} autoFocus/>
              <div className="dec-actions">
                <button className="da-btn primary" onClick={startReplan}><Icd d={IKd.flow} size={13}/> {t.commitEdit}</button>
                <button className="da-btn ghost" onClick={()=>setEditing(false)}>cancel</button>
              </div>
            </>
          ) : (
            <div className="replan">
              <div className="replan-l"><span className="replan-spin"></span>{t.replanning} · validating your edit through the cognition graph</div>
              <div className="replan-steps">
                {REPLAN_STAGES.map((s,i)=>(
                  <div className={'rps'+(i<replan?' done':i===replan?' on':'')} key={i}>
                    <span className="rps-dot">{i<replan?<Icd d={IKd.check} size={9}/>:''}</span><span className="rps-l">{s}</span>
                    {i<REPLAN_STAGES.length-1&&<span className="rps-line"></span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : !confirm ? (
        <div className="dec-actions">
          <button className="da-btn primary" onClick={()=> irreversible ? setConfirm(true) : onResolve(d.id,'accept')}>
            <Icd d={IKd.check} size={13}/> {irreversible?t.confirm:t.accept}
          </button>
          <button className="da-btn" onClick={()=>{setEditing(true); setEditTxt(d.dryRun);}}>{t.edit}</button>
          <button className="da-btn" onClick={()=>onResolve(d.id,'reject')}><Icd d={IKd.x} size={12}/> {t.reject}</button>
          <button className="da-btn ghost" onClick={()=>onResolve(d.id,'defer')}>{t.defer}</button>
        </div>
      ) : (
        <div className="dec-confirm">
          <span className="dc-warn"><Icd d={IKd.lock} size={13}/> Irreversible — {d.dryRun.split('·')[0].trim()}</span>
          <div className="dec-actions">
            <button className="da-btn danger" onClick={()=>onResolve(d.id,'accept')}>{t.confirm}</button>
            <button className="da-btn ghost" onClick={()=>setConfirm(false)}>cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- skeleton while the queue loads ---------- */
function DecSkeleton(){
  return (
    <div className="panel dec-card skel">
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="sk-line w30"></div>
      <div className="sk-line w70" style={{marginTop:12,height:14}}></div>
      <div className="sk-line w90" style={{marginTop:8}}></div>
      <div className="sk-line w50" style={{marginTop:8}}></div>
      <div className="sk-row" style={{marginTop:14}}><span className="sk-btn"></span><span className="sk-btn"></span><span className="sk-btn"></span></div>
    </div>
  );
}

/* ---------- Decisions canvas (north-star) — wired to the live data layer ---------- */
function DecisionsMode({ res, onResolve, pending, conn, interrupts, onOpenNet, t }){
  const [filter,setFilter]=uSd('all');
  const decisions = res.data || [];
  const list = uMd(()=> decisions.filter(d=> filter==='all' ? true : filter==='ask' ? d.kind==='ASK' : d.kind!=='ASK'), [decisions,filter]);
  const I = interrupts || window.V2.INTERRUPTS;
  const urgent = decisions.filter(d=>d.urgent).length;
  const Strip = window.TelemetryStrip;
  const staleSecs = res.lastOk ? Math.round((Date.now()-res.lastOk)/1000) : 0;
  const showSkeleton = res.loading && !res.data;
  const hardError = res.error && !res.data;

  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <Icd d={IKd.decisions} size={14}/><span className="ttl">{t.decTitle}</span>
        <span className="st">{showSkeleton?'loading…':`${decisions.length} open${urgent>0?` · ${urgent} urgent`:''}`}</span>
        {Strip && <span style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:10}}>
          <Strip conn={conn}/>
          <button className="net-btn" onClick={onOpenNet} title="open network inspector & chaos console"><Icd d={IKd.flow} size={13}/></button>
        </span>}
      </div>
      <div className="dec-subbar">
        <div className="dec-filters">
          {[['all','All'],['ask','Needs you'],['fyi','FYI / auto']].map(([k,lab])=>(
            <button key={k} className={'cf'+(filter===k?' on':'')} onClick={()=>setFilter(k)}>{lab}</button>
          ))}
        </div>
        <div className="dec-budget-inline">
          <span className="dbi-k">interrupts {t.budgetTitle.toLowerCase().includes('buget')?'azi':'today'}</span>
          <span className="dbi-pips">
            {Array.from({length:I.cap}).map((_,i)=><span key={i} className={'pip-i'+(i<I.used?' used':'')}></span>)}
          </span>
          <span className="dbi-v">{I.used}/{I.cap}</span>
        </div>
      </div>

      {res.stale && (
        <div className="stale-banner">
          <span className="sb-dot"></span>
          <span>Showing last-good from {staleSecs}s ago — couldn't refresh ({res.error&&res.error.timeout?'timeout':res.error&&res.error.offline?'unreachable':'error'}).</span>
          <button className="sb-btn" onClick={res.refetch}>Retry now</button>
        </div>
      )}

      <div className="panel-body" style={{paddingTop:12}}>
        {showSkeleton ? (
          <div className="dec-stack"><DecSkeleton/><DecSkeleton/><DecSkeleton/></div>
        ) : hardError ? (
          <div className="empty-state error-state">
            <Icd d={IKd.x} size={26}/>
            <div className="es-big">Couldn't reach the decision queue</div>
            <div className="es-sub">{res.error.timeout?'The request timed out.':res.error.offline?'The backend is unreachable.':('Server returned '+(res.error.status||'an error')+'.')} Your decisions are safe on the server — nothing was lost.</div>
            <div className="es-actions">
              <button className="da-btn primary" onClick={res.refetch}>Retry</button>
              <button className="da-btn" onClick={onOpenNet}>Open inspector</button>
            </div>
          </div>
        ) : list.length===0 ? (
          <div className="empty-state"><Icd d={IKd.check} size={26}/><div className="es-big">{t.queueClear}</div><div className="es-sub">The Cabinet is acting inside policy. You'll be pulled in only when it matters.</div></div>
        ) : (
          <div className="dec-stack">
            {list.map(d=><DecisionCard key={d.id} d={d} onResolve={onResolve} pending={!!(pending&&pending[d.id])} t={t}/>)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============ MISSIONS — wired to the live layer + event stream ============ */
const MSTATUS = { running:{c:'run',l:'running'}, review:{c:'rev',l:'needs review'}, paused:{c:'pause',l:'paused'}, done:{c:'done',l:'done'} };

function MisSkeleton(){
  return <div className="mcard skel"><div className="sk-line w50"></div><div className="sk-line w90" style={{marginTop:11,height:13}}></div><div className="sk-line" style={{marginTop:13,height:5}}></div><div className="sk-row" style={{marginTop:11}}><span className="sk-btn" style={{width:70,height:13}}></span></div></div>;
}

function MissionsMode({ res, onOpen, onAction, pending, onOpenNet, conn, t }){
  const missions = res.data || [];
  const active = missions.filter(m=>m.status!=='done').length;
  const showSkeleton = res.loading && !res.data;
  const hardError = res.error && !res.data;
  const Strip = window.TelemetryStrip;
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head">
        <Icd d={IKd.missions} size={14}/><span className="ttl">{t.missionsTitle}</span>
        <span className="st">{showSkeleton?'loading…':`${active} active`}</span>
        <span style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:10}}>
          <span className="mis-live" title="live event stream open"><span className="ml-dot"></span>streaming</span>
          {Strip && <Strip conn={conn}/>}
          <button className="net-btn" onClick={onOpenNet} title="network inspector & chaos"><Icd d={IKd.flow} size={13}/></button>
        </span>
      </div>
      {res.stale && (
        <div className="stale-banner"><span className="sb-dot"></span><span>Showing last-good — couldn't refresh missions.</span><button className="sb-btn" onClick={res.refetch}>Retry</button></div>
      )}
      <div className="panel-body">
        <div className="sub-h">LONG-RUNNING WORK · governed, budgeted, resumable · progress streams live</div>
        {showSkeleton ? (
          <div className="mission-board"><MisSkeleton/><MisSkeleton/><MisSkeleton/></div>
        ) : hardError ? (
          <div className="empty-state error-state"><Icd d={IKd.x} size={26}/><div className="es-big">Couldn't reach missions</div><div className="es-sub">{res.error.offline?'The backend is unreachable.':res.error.timeout?'The request timed out.':'Server error.'} Work continues on the server.</div><div className="es-actions"><button className="da-btn primary" onClick={res.refetch}>Retry</button><button className="da-btn" onClick={onOpenNet}>Open inspector</button></div></div>
        ) : missions.length===0 ? (
          <div className="empty-state"><Icd d={IKd.check} size={26}/><div className="es-big">No missions running</div><div className="es-sub">Long-running work appears here with its budget, plan, and sealed audit.</div></div>
        ) : (
          <div className="mission-board">
            {missions.map(m=>{
              const st=MSTATUS[m.status]||MSTATUS.running; const steps=m.steps.filter(s=>s.done).length;
              const busy=!!(pending&&pending[m.id]);
              return (
                <div className={'mcard'+(m.status==='running'?' live':'')} key={m.id} onClick={()=>onOpen(m.id)}>
                  <div className="mc-top"><span className="gx"><Gld id={m.agent} size={16}/></span><span className={'mc-status '+st.c}>{st.l}</span></div>
                  <div className="mc-title">{m.title}</div>
                  <div className="mc-prog"><div className="mc-pf" style={{width:m.progress+'%'}}></div></div>
                  <div className="mc-meta">
                    <span>{steps}/{m.steps.length} steps</span>
                    <span className="mc-bud">{m.budget.label}</span>
                    <span className="mc-eta">{m.status==='running'?Math.round(m.progress)+'%':m.eta}</span>
                  </div>
                  {m.status!=='done' && (
                    <div className="mc-quick" onClick={e=>e.stopPropagation()}>
                      {m.status==='paused'
                        ? <button className="mq-btn" disabled={busy} onClick={()=>onAction(m.id,'resume')}><Icd d={IKd.play} size={11}/> resume</button>
                        : <button className="mq-btn" disabled={busy} onClick={()=>onAction(m.id,'pause')}><Icd d={IKd.pause} size={11}/> pause</button>}
                      {m.status==='review' && <button className="mq-btn primary" disabled={busy} onClick={()=>onAction(m.id,'accept')}><Icd d={IKd.check} size={11}/> accept</button>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function MissionDrawer({ mission, onClose, onAction, pending, t }){
  const m = mission; if(!m) return null;
  const a = window.V2.AGENTS.find(x=>x.id===m.agent)||{name:m.agent,role:''};
  const st = MSTATUS[m.status]||MSTATUS.running;
  const pct = m.budget.cap>0 ? Math.round(m.budget.used/m.budget.cap*100) : 0;
  const busy = !!(pending&&pending[m.id]);
  return (
    <>
      <div className="dossier-scrim" onClick={onClose}></div>
      <div className="dossier" role="dialog" aria-modal="true" aria-label={m.title}>
        <div className="dossier-head">
          <span className="big-glyph"><Gld id={m.agent} size={44}/></span>
          <div style={{flex:1}}>
            <div className="nm" style={{fontSize:18,lineHeight:1.25}}>{m.title}</div>
            <div className="ar">{a.name} · {a.role} <span className={'mc-status '+st.c} style={{marginLeft:8}}>{st.l}</span></div>
          </div>
          <button className="close" aria-label="Close" onClick={onClose}><Icd d={IKd.x} size={16}/></button>
        </div>
        <div className="dossier-body">
          <div className="dsec">
            <div className="dl">{t.plan} · {m.steps.filter(s=>s.done).length}/{m.steps.length}{m.status==='running'?` · ${Math.round(m.progress)}%`:''}</div>
            <div className="mplan">
              {m.steps.map((s,i)=>(
                <div className={'mstep'+(s.done?' done':'')} key={i}>
                  <span className="ms-box">{s.done?<Icd d={IKd.check} size={11}/>:i+1}</span>
                  <span className="ms-t">{s.s}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="dsec">
            <div className="dl">{t.resources}</div>
            <div className="meter"><div className="ml"><span>{m.budget.unit==='local'?'compute':'cloud budget'}</span><span>{m.budget.label}</span></div>
              <div className="mt"><div className="mf" style={{width:pct+'%',background: m.budget.unit==='local'?'linear-gradient(90deg,var(--green-dim),var(--green))':undefined}}></div></div></div>
            <div className="sysrow"><span className="k">STARTED</span><span className="v">{m.started}</span></div>
            <div className="sysrow"><span className="k">ETA</span><span className="v acc">{m.eta}</span></div>
          </div>
          <div className="dsec">
            <div className="dl">{t.artifacts}</div>
            <div className="dep-links">{m.artifacts.map((f,i)=><span className="dep-link" key={i} style={{cursor:'default'}}><Icd d={IKd.note} size={12}/>{f.name}</span>)}</div>
          </div>
          <div className="dsec">
            <div className="dl">{t.auditTrail} · sealed</div>
            {m.audit.map((e,i)=>(
              <div className="audit-block" key={i}>
                <div className="anchor"><span className="hash-dot"></span><span className="vline"></span></div>
                <div className="audit-card"><div className="at"><span className="verb">{e.t}</span><span className="ok">✓</span></div><div className="ax">{e.x}</div></div>
              </div>
            ))}
          </div>
          <div className="dec-actions" style={{marginTop:4}}>
            {m.status==='paused'
              ? <button className="da-btn primary" disabled={busy} onClick={()=>onAction(m.id,'resume')}><Icd d={IKd.play} size={12}/> {t.resume}</button>
              : m.status!=='done' && <button className="da-btn" disabled={busy} onClick={()=>onAction(m.id,'pause')}><Icd d={IKd.pause} size={12}/> {t.pause}</button>}
            {m.status==='review' && <button className="da-btn primary" disabled={busy} onClick={()=>onAction(m.id,'accept')}><Icd d={IKd.check} size={12}/> {t.accept}</button>}
          </div>
        </div>
      </div>
    </>
  );
}

Object.assign(window, { DecisionsMode, DecisionCard, MissionsMode, MissionDrawer });
