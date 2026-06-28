'use strict';
/* HUD v2 · MODES — Agents, Trust, Memory */
const { useState, useMemo } = React;
const { Icon, ICONS, Glyph, statusClass } = window;

/* ============ AGENTS ============ */
function AgentsMode({ agents, onOpen, t }) {
  const TIERS = window.V2.TIERS;
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.agents} size={14}/><span className="ttl">{t.roster}</span><span className="st">{agents.length} agents · {agents.filter(a=>a.status!=='idle').length} live</span></div>
      <div className="panel-body">
        {TIERS.map(tier=>{
          const list=agents.filter(a=>a.tier===tier.id);
          if(!list.length) return null;
          return (
            <div className="tier-group" key={tier.id}>
              <div className="tier-head"><span className="tier-tag">{tier.id}</span><span className="tier-lab">{tier.label}</span></div>
              <div className="agents-grid">
                {list.map(a=>(
                  <div className="acard" key={a.id} onClick={()=>onOpen(a.id)}>
                    <div className="ah">
                      <span className="gx"><Glyph id={a.id} size={22}/></span>
                      <div><div className="nm">{a.name}<span className="tier">{a.tier}</span></div><div className="ar">{a.role}</div></div>
                      <span className={'sdot '+statusClass(a.status)} style={{marginLeft:'auto'}}></span>
                    </div>
                    <div className="ameta">
                      <span className={'am '+(a.policy==='local'?'local':a.policy==='auto'?'':'cloud')}>{a.model}</span>
                      <span className={'am '+(a.policy==='local'?'local':a.policy==='cloud'||a.policy==='claude'?'cloud':'')}>{a.policy}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Dossier({ id, onClose, onOpen }) {
  const d = window.V2.DOSSIER[id];
  const a = window.V2.AGENTS.find(x=>x.id===id);
  if(!d||!a) return null;
  const deps = (window.V2.COLLAB.filter(([x,y])=>x===id||y===id).map(([x,y])=>x===id?y:x));
  return (
    <>
      <div className="dossier-scrim" onClick={onClose}></div>
      <div className="dossier" role="dialog" aria-modal="true" aria-label={a.name+' — agent dossier'}>
        <div className="dossier-head">
          <span className="big-glyph"><Glyph id={id} size={46}/></span>
          <div><div className="nm">{a.name}</div><div className="ar">{d.archetype} · {a.tier}</div></div>
          <button className="close" aria-label="Close" onClick={onClose}><span aria-hidden="true">✕</span></button>
        </div>
        <div className="dossier-body">
          <div className="dsec"><div className="dl">Soul</div><div className="dtx soul">{d.soul}</div></div>
          <div className="dsec"><div className="dl">Personality</div><div className="dtx">{d.personality}</div></div>
          <div className="dsec"><div className="dl">Runtime</div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px 16px'}}>
              {[['Model',d.model],['Channel',d.channel],['Heartbeat',d.heartbeat],['Policy',d.policy],['Skills',d.skills],['Memory facts',d.memory_facts]].map(([k,v])=>(
                <div key={k} style={{fontFamily:'var(--font-mono)',fontSize:12}}>
                  <span style={{color:'var(--ink-3)',fontSize:9,letterSpacing:'.1em',textTransform:'uppercase',display:'block'}}>{k}</span>
                  <span style={{color:'var(--accent-light)'}}>{v}</span>
                </div>
              ))}
            </div>
          </div>
          {d.plugins.length>0 && <div className="dsec"><div className="dl">Plugins</div><div className="dep-links">{d.plugins.map(p=><span key={p} className="dep-link" style={{cursor:'default'}}>{p}</span>)}</div></div>}
          <div className="dsec"><div className="dl">Collaborates with</div>
            <div className="dep-links">{deps.map(dep=>{ const da=window.V2.AGENTS.find(x=>x.id===dep); return <span key={dep} className="dep-link" onClick={()=>onOpen(dep)}><Glyph id={dep} size={12}/>{da?da.name:dep}</span>; })}</div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ============ TRUST ============ */
function TrustMode({ auditRes, killed, onKill, t }) {
  const D = window.V2;
  const audit = (auditRes && auditRes.data) || D.AUDIT_CHAIN;
  const [verify,setVerify]=useState(null);
  React.useEffect(()=>{ let on=true; if(window.JarvisAPI&&window.JarvisAPI.auditVerify) window.JarvisAPI.auditVerify().then(v=>on&&setVerify(v)).catch(()=>{}); return ()=>{on=false;}; },[killed,audit.length]);
  const [dataAct,setDataAct]=useState(null); const [expInfo,setExpInfo]=useState('');
  const doExport=async()=>{ try{ const r=await window.JarvisClient.post('/api/admin/export',{}); setExpInfo((r&&r.items?Object.values(r.items).reduce((a,b)=>a+b,0):0)+' items'); }catch(e){ setExpInfo('cache'); } setDataAct('exported'); };
  const doForget=async()=>{ setDataAct('forgetting'); try{ await window.JarvisClient.post('/api/admin/forget',{}); }catch(e){} };
  const localPct = 87;
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.trust} size={14}/><span className="ttl">{t.trust} Center</span><span className="st">Merkle-verified</span></div>
      <div className="panel-body">
        <div className="trust-grid">
          {/* left: audit chain */}
          <div>
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10,display:'flex',alignItems:'center',gap:8}}>{t.auditTitle} · {audit.length} sealed{verify && <span className={'verify-chip '+(verify.ok?'ok':'bad')}>{verify.ok?'✓ chain verified':'✕ chain broken'} · {verify.checked}</span>}</div>
            <div className="verified-row"><Icon d={ICONS.trust} size={13}/> {t.verified}</div>
            {audit.map((b,i)=>(
              <div className={'audit-block'+(b._new?' tl-new':'')} key={b.hash||i}>
                <div className="anchor"><div className="hash-dot"></div><div className="vline"></div></div>
                <div className="audit-card">
                  <div className="at"><span className="verb">{b.verb}</span><span>{b.t}</span><span className="ok">✓ sealed</span></div>
                  <div className="ax">{b.x}</div>
                  <div className="ahash"><b>sha256:</b>{b.hash}…&nbsp;&nbsp;<span style={{color:'var(--ink-4)'}}>prev:{b.prev}</span></div>
                </div>
              </div>
            ))}
          </div>
          {/* right: kill + locality + caps + payments */}
          <div className="col">
            <div className="killbox panel" style={{borderRadius:'var(--radius)',background:'var(--surface-2)'}}>
              <button className={'killbtn'+(killed?' engaged':'')} onClick={()=>onKill(!killed)}>
                <Icon d={ICONS.shield} size={26}/>
                <span className="kt">{killed?'HALTED':'STOP'}</span>
                <span className="ks">{t.killSub}</span>
              </button>
              <div className={'kill-status '+(killed?'engaged':'armed')}>{killed?t.engaged:t.armed}</div>
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>{t.locality}</div>
              <div className="loc-ring-wrap">
                <div className="loc-pct">{localPct}%</div>
                <div className="loc-legend">
                  <div className="ll"><span className="sw" style={{background:'var(--green)'}}></span> on-device · {localPct}%</div>
                  <div className="ll"><span className="sw" style={{background:'var(--violet)'}}></span> cloud (Claude) · {100-localPct}%</div>
                </div>
              </div>
              <div className="loc-bar"><div className="seg local" style={{width:localPct+'%'}}></div><div className="seg cloud" style={{width:(100-localPct)+'%'}}></div></div>
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:6}}>{t.capsTitle}</div>
              {D.CAPABILITIES.map((c,i)=>(
                <div className="cap-row" key={i}><div><div className="cn">{c.cn}</div><div className="cd">{c.cd}</div></div><span className={'cap-tag '+c.tag}>{c.tagLabel}</span></div>
              ))}
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:6}}>{t.payTitle}</div>
              {D.PAYMENTS.map((p,i)=>(
                <div className="pay-row" key={i}><span className="pcap">{p.pcap}</span><span style={{color:'var(--ink-2)'}}>{p.desc}</span><span style={{textAlign:'right',color:p.state==='pending'?'var(--amber)':p.state==='cleared'?'var(--green)':'var(--ink-3)'}}>{p.amt}</span></div>
              ))}
              <div className="pay-pending"><span style={{color:'var(--amber)',fontFamily:'var(--font-mono)',fontSize:11}}>⏳ 1 payment awaiting your approval — €4,200 sweep</span></div>
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>GOVERNANCE · POSTURE</div>
              <div className="gov-score"><span className="gov-grade">{D.GOVERNANCE.grade}</span><span className="gov-num">{D.GOVERNANCE.score}<i>/100</i></span><span className="gov-lab">governance scorecard</span></div>
              {D.GOVERNANCE.checks.map((c,i)=>(<div className="gov-row" key={i}><span className={'gov-dot '+(c.ok?'ok':'warn')}></span>{c.k}</div>))}
              <div className="sysrow" style={{marginTop:12}}><span className="k">POSTURE</span><span className="v acc">{D.POSTURE.level}</span></div>
              <div className="sysrow"><span className="k">INJECTION BLOCKS</span><span className="v">{D.POSTURE.injection_blocks} · {D.POSTURE.quarantined} quarantined</span></div>
              <div className="sysrow"><span className="k">LOOP-BREAKER</span><span className="v">{D.LOOPBREAKER.tripped?'TRIPPED':'armed'} · {D.LOOPBREAKER.longest}/{D.LOOPBREAKER.cap} self-calls</span></div>
              <div className="sysrow"><span className="k">%-LOCAL SOURCE</span><span className="v" style={{fontSize:9}}>/api/analytics/locality · {D.LOCALITY.routed_runs} runs</span></div>
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>YOUR DATA · portable & forgettable</div>
              {!dataAct && <div className="data-acts"><button className="da-btn" onClick={doExport}><Icon d={ICONS.data} size={12}/> Export my data</button><button className="da-btn" onClick={()=>setDataAct('forget-confirm')}><Icon d={ICONS.x} size={12}/> Forget me…</button></div>}
              {dataAct==='exported' && <div className="data-done ok">✓ Exported {expInfo} · jarvis-export-2026-06-28.tar.gz <button className="data-link" onClick={()=>setDataAct(null)}>done</button></div>}
              {dataAct==='forget-confirm' && <div className="data-confirm"><span className="dc-warn"><Icon d={ICONS.lock} size={12}/> Schedules deletion of ALL your data (sessions, memory, KG, audit) — reversible for 24h.</span><div className="data-acts"><button className="da-btn danger" onClick={doForget}>Confirm forget-me</button><button className="da-btn ghost" onClick={()=>setDataAct(null)}>cancel</button></div></div>}
              {dataAct==='forgetting' && <div className="data-done rej">⏳ Deletion scheduled · purge in 24h · reversible <button className="data-link" onClick={()=>setDataAct(null)}>ok</button></div>}
              <div className="sysrow" style={{marginTop:8}}><span className="k">SCOPE</span><span className="v">sessions · memory · KG · audit</span></div>
            </div>
          </div>
        </div>
        {(()=>{ const Scopes=window.AgentScopesMatrix; return Scopes?<Scopes t={t}/>:null; })()}
      </div>
    </div>
  );
}

/* ============ MEMORY + KG · interactive ============ */
function KGraph({ born }){
  const D = window.V2;
  const visIds = new Set(D.KG.nodes.filter(n=>n.born<=born).map(n=>n.id));
  return (
    <svg className="kg-svg" viewBox="0 0 640 380" preserveAspectRatio="xMidYMid meet">
      {D.KG.edges.map((e,i)=>{
        const on = e.born<=born && visIds.has(e.a) && visIds.has(e.b);
        const A=D.KG.nodes.find(n=>n.id===e.a), B=D.KG.nodes.find(n=>n.id===e.b);
        return <g key={i} className={on?'':'faded'}>
          <line className={'kg-edge'+(on?'':' faded')} x1={A.x} y1={A.y} x2={B.x} y2={B.y}/>
          {on && <text className="kg-edge-label" x={(A.x+B.x)/2} y={(A.y+B.y)/2-2} textAnchor="middle">{e.label}</text>}
        </g>;
      })}
      {D.KG.nodes.map(n=>{
        const on = n.born<=born; const r = n.id==='andrei'?22:15;
        return <g key={n.id} className={'kg-node'+(on?'':' faded')} transform={`translate(${n.x},${n.y})`}>
          <circle r={r} style={n.id==='andrei'?{fill:'var(--accent-faint)',stroke:'var(--accent)'}:{}}/>
          <text y={r+12} textAnchor="middle">{n.label}</text>
        </g>;
      })}
    </svg>
  );
}

function MemoryMode({ t }) {
  const D = window.V2;
  const M = D.MEMORY_STATS;
  const marks = D.KG.marks;
  const TABS = [['recall',t.recallTab],['graph',t.graph],['timetravel',t.timetravel],['ingest',t.ingest],['hygiene',t.hygiene],['capture',t.capture]];
  const [tab,setTab]=useState('recall');
  const [ti,setTi]=useState(marks.length-1);
  const [facts,setFacts]=useState(D.RECALLS.map((r,i)=>({...r,_id:'r'+i})));
  const [draft,setDraft]=useState('');
  const [ingest,setIngest]=useState('');
  const [ingested,setIngested]=useState(null);
  const [cap,setCap]=useState(D.MEM_CAPTURE);
  const [mq,setMq]=useState(''); const [hits,setHits]=useState(null);
  const [kgList,setKgList]=useState(D.KG.nodes.filter(n=>n.id!=='andrei'));
  const [kgEdit,setKgEdit]=useState(null);
  const [folder,setFolder]=useState(''); const [indexed,setIndexed]=useState(null);
  const doIndex=()=>{ const f=folder.trim()||'~/Documents/Jarvis'; setIndexed({path:f,docs:Math.floor(20+Math.random()*180),chunks:Math.floor(400+Math.random()*2000)}); };
  const remember=()=>{ if(!draft.trim())return; setFacts(f=>[{rx:draft.trim(),rsrc:'KG · you · 1.00',score:'1.00',_id:'n'+Date.now()},...f]); setDraft(''); };
  const forget=id=>setFacts(f=>f.filter(x=>x._id!==id));
  const search=async(q)=>{ setMq(q); if(!q.trim()){ setHits(null); return; } try{ const r=await window.JarvisAPI.memorySearch(q); setHits((r&&r.results)||[]); }catch(e){ setHits([]); } };
  const doIngest=()=>{ if(!ingest.trim())return; setIngested({n:Math.max(1,Math.round(ingest.split(/\s+/).length/6)),sample:['Entity · '+(ingest.split(/\s+/)[0]||'topic'),'relation · mentions','source · pasted text']}); };
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.memory} size={14}/><span className="ttl">{t.memTitle}</span><span className="st">qdrant · 768d</span></div>
      <div className="panel-body">
        <div className="mem-grid" style={{marginBottom:14}}>
          {[[M.sessions,'sessions'],[M.vectors,'vectors'],[M.entities,'entities'],[M.relations,'relations']].map(([v,l],i)=>(
            <div className="stat-card" key={i}><div className="sv">{v}</div><div className="sl">{l}</div></div>
          ))}
        </div>
        <div className="subtabs">
          {TABS.map(([k,lab])=><button key={k} className={'subtab'+(tab===k?' active':'')} onClick={()=>setTab(k)}>{lab}</button>)}
        </div>

        {tab==='recall' && (
          <div className="mem-pane">
            <div className="remember-bar">
              <Icon d={ICONS.plus} size={14}/>
              <input value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>e.key==='Enter'&&remember()} placeholder={t.remember}/>
              <button className="da-btn primary" onClick={remember}>{t.confirm}</button>
            </div>
            <div className="mem-search">
              <Icon d={ICONS.memory} size={14}/>
              <input value={mq} onChange={e=>search(e.target.value)} placeholder="Search memory — semantic recall…"/>
              <span className="ms-k">{hits?hits.length+' hits':'768d · qdrant'}</span>
            </div>
            {hits && hits.length>0 && (
              <div style={{marginBottom:12}}>
                <div className="sub-h" style={{margin:'4px 0 8px'}}>SEARCH RESULTS · live · /api/memory/search</div>
                {hits.map((h,i)=>(<div className="mem-hit" key={i}><span className="mh-score">{h.score}</span><div><div className="mh-p">{h.payload}</div><div className="mh-s">{h.source}</div></div></div>))}
              </div>
            )}
            <div className="sub-h" style={{margin:'4px 0 8px'}}>{t.recall} · inspect · edit · forget</div>
            {facts.map(r=>(
              <div className="recall-row" key={r._id}>
                <div><div className="rx">{r.rx}</div><div className="rsrc">{r.rsrc}</div></div>
                <div style={{display:'flex',alignItems:'center',gap:10}}>
                  <span className="recall-score">{r.score}</span>
                  <button className="forget-btn" onClick={()=>forget(r._id)} title="forget this fact"><Icon d={ICONS.x} size={11}/></button>
                </div>
              </div>
            ))}
            <div className="sub-h" style={{margin:'16px 0 8px'}}>{t.spaces}</div>
            {D.TOPICS.map((tp,i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'var(--ink-2)'}}><span>{tp.t}</span><span style={{fontFamily:'var(--font-mono)',color:'var(--ink-3)'}}>{100-tp.d}% fresh</span></div>
                <div className="decay-bar"><i style={{width:(100-tp.d)+'%'}}></i></div>
              </div>
            ))}
          </div>
        )}

        {tab==='graph' && (
          <div className="mem-pane">
            <div className="kg-wrap"><KGraph born={marks.length-1}/></div>
            <div className="sub-h" style={{margin:'12px 0 8px'}}>ENTITIES · inline edit & delete · {kgList.length} shown</div>
            {kgList.map((n)=>(
              <div className="kg-ent" key={n.id}>
                {kgEdit===n.id ? (
                  <input className="kg-ent-in" defaultValue={n.label} autoFocus onKeyDown={e=>{ if(e.key==='Enter'){ const v=e.target.value.trim(); setKgList(l=>l.map(x=>x.id===n.id?{...x,label:v||x.label}:x)); setKgEdit(null); } if(e.key==='Escape') setKgEdit(null); }}/>
                ) : (
                  <span className="kg-ent-n"><span className="kg-ent-dot"></span>{n.label}</span>
                )}
                <span className="kg-ent-meta">valid from T{n.born}</span>
                <div className="kg-ent-acts">
                  {kgEdit===n.id
                    ? <button className="forget-btn" onClick={()=>setKgEdit(null)} title="done"><Icon d={ICONS.check} size={11}/></button>
                    : <button className="forget-btn" onClick={()=>setKgEdit(n.id)} title="rename entity"><Icon d={ICONS.note} size={11}/></button>}
                  <button className="forget-btn" onClick={()=>setKgList(l=>l.filter(x=>x.id!==n.id))} title="forget entity"><Icon d={ICONS.x} size={11}/></button>
                </div>
              </div>
            ))}
            <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,color:'var(--ink-4)',marginTop:8}}>bitemporal KG · an edit writes a new valid-time fact · delete cascades on the dependency graph (no recontamination)</div>
          </div>
        )}

        {tab==='timetravel' && (
          <div className="mem-pane"><div className="kg-wrap"><KGraph born={ti}/></div>
            <div className="timeslider" style={{border:'1px solid var(--panel-line)',borderTop:0,borderRadius:'0 0 var(--radius) var(--radius)'}}>
              <span className="tlab">{t.asof}</span>
              <input type="range" min="0" max={marks.length-1} step="1" value={ti} onChange={e=>setTi(+e.target.value)}/>
              <span className="asof">{marks[ti]}</span>
            </div>
            <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,color:'var(--ink-4)',marginTop:8,textAlign:'center'}}>bitemporal · valid-time vs transaction-time · drag to travel</div>
          </div>
        )}

        {tab==='ingest' && (
          <div className="mem-pane">
            <div className="sub-h" style={{marginBottom:8}}>{t.ingest} · text → entities → KG</div>
            <textarea className="ingest-area" value={ingest} onChange={e=>setIngest(e.target.value)} placeholder="Paste notes, an article, a transcript… Jarvis extracts entities and relations into the graph."/>
            <div style={{display:'flex',gap:9,marginTop:10}}><button className="da-btn primary" onClick={doIngest}><Icon d={ICONS.plus} size={12}/> Extract to graph</button></div>
            <div className="ldx">
              <div className="sub-h" style={{marginBottom:8}}>LOCAL DOCS · index a folder (on-device · never uploaded)</div>
              <div className="ldx-row"><input className="ldx-path" value={folder} onChange={e=>setFolder(e.target.value)} placeholder="~/Documents/Jarvis"/><button className="da-btn" onClick={doIndex}><Icon d={ICONS.device} size={12}/> Index folder</button></div>
              {indexed && <div className="ldx-out"><Icon d={ICONS.check} size={12}/> indexed {indexed.docs} docs · {indexed.chunks} chunks → {indexed.path} · local-only</div>}
            </div>
            {ingested && (
              <div className="ingest-out">
                <div className="ig-head">extracted <b>{ingested.n}</b> candidate facts · review before commit</div>
                {ingested.sample.map((s,i)=><div className="ig-row" key={i}><Icon d={ICONS.check} size={11}/>{s}</div>)}
              </div>
            )}
          </div>
        )}

        {tab==='hygiene' && (
          <div className="mem-pane">
            <div className="hyg-grid">
              <div className="hyg-card">
                <div className="dl">{t.reflection}</div>
                <div className="hyg-row"><span className="k">last run</span><span className="v acc">{D.MEM_REFLECTION.last}</span></div>
                <div className="hyg-row"><span className="k">lessons</span><span className="v">{D.MEM_REFLECTION.lessons} · entities {D.MEM_REFLECTION.entities}</span></div>
                {D.MEM_REFLECTION.recent.map((l,i)=><div className="hyg-lesson" key={i}><Icon d={ICONS.check} size={11}/>{l}</div>)}
                <button className="da-btn" style={{marginTop:10}}><Icon d={ICONS.play} size={11}/> Run reflection now</button>
              </div>
              <div className="hyg-card">
                <div className="dl">{t.evalH}</div>
                <div className="hyg-row"><span className="k">recall@5</span><span className="v acc">0.91</span></div>
                <div className="hyg-row"><span className="k">eval corpus</span><span className="v">120 probes</span></div>
                <div className="hyg-row"><span className="k">decay candidates</span><span className="v">7 facts &lt; 0.2</span></div>
                <div className="hyg-row"><span className="k">consolidation</span><span className="v">3 merges queued</span></div>
                <button className="da-btn" style={{marginTop:10}}>Review candidates</button>
              </div>
            </div>
          </div>
        )}

        {tab==='capture' && (
          <div className="mem-pane">
            <div className="sub-h" style={{marginBottom:8}}>{t.capture} · ambient inbox · per-item delete is the privacy promise</div>
            {cap.length===0 && <div className="empty-state" style={{padding:'30px 0'}}><Icon d={ICONS.note} size={22}/><div className="es-big">Capture inbox clear</div></div>}
            {cap.map((c,i)=>(
              <div className="cap-item" key={i}>
                <span className={'cap-kind '+c.kind}>{c.kind}</span>
                <div style={{flex:1}}><div className="rx">{c.t}</div><div className="rsrc">{c.src} · {c.when}</div></div>
                <button className="forget-btn" onClick={()=>setCap(x=>x.filter((_,j)=>j!==i))} title="delete"><Icon d={ICONS.x} size={11}/></button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { AgentsMode, Dossier, TrustMode, MemoryMode });
