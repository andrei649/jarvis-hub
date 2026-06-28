'use strict';
/* HUD v2 · WORLDVIEW — the system's model of YOU.
   Constellation: self at center, domains as orbits, entities clustered,
   inferred beliefs (confirm/correct/forget), provenance, time-travel, filter, search. */
const { useState:uW, useMemo:uWM } = React;
const { Icon:IcW, ICONS:IKW, Glyph:GlW } = window;

function WorldviewMode({ t, onAsk }){
  const W = window.V2.WORLDVIEW;
  const [sel,setSel]=uW(null);
  const [domain,setDomain]=uW('all');
  const [q,setQ]=uW('');
  const [ti,setTi]=uW(W.marks.length-1);
  const [beliefState,setBeliefState]=uW(()=>Object.fromEntries(W.beliefs.map(b=>[b.id,b.status])));

  const CX=380, CY=300, R=205;
  // domain anchor positions
  const domainPos = uWM(()=>Object.fromEntries(W.domains.map(d=>{
    const a=d.angle*Math.PI/180; return [d.id,{x:CX+Math.cos(a)*R*0.62, y:CY+Math.sin(a)*R*0.62, color:d.color, ...d}];
  })),[]);
  // entity positions: clustered around their domain anchor
  const ePos = uWM(()=>{
    const byD={}; W.entities.forEach(e=>{ (byD[e.domain]=byD[e.domain]||[]).push(e); });
    const pos={};
    Object.entries(byD).forEach(([d,list])=>{
      const anc=domainPos[d];
      list.forEach((e,i)=>{
        const spread=(i-(list.length-1)/2);
        const a=(domainPos[d].angle+spread*22)*Math.PI/180;
        const r=R*(0.92+ (i%2)*0.12);
        pos[e.id]={x:CX+Math.cos(a)*r, y:CY+Math.sin(a)*r, e};
      });
    });
    return pos;
  },[domainPos]);

  const born=ti;
  const visE = W.entities.filter(e=>e.born<=born && (domain==='all'||e.domain===domain) && (!q||e.label.toLowerCase().includes(q.toLowerCase())||e.sub.toLowerCase().includes(q.toLowerCase())));
  const visIds=new Set(visE.map(e=>e.id));
  const beliefs=W.beliefs.filter(b=>b.born<=born && (domain==='all'||b.domain===domain) && (!q||b.text.toLowerCase().includes(q.toLowerCase())));

  const selEntity = sel&&sel.kind==='entity' ? W.entities.find(e=>e.id===sel.id):null;
  const selBelief = sel&&sel.kind==='belief' ? W.beliefs.find(b=>b.id===sel.id):null;
  const relatedBeliefs = selEntity ? W.beliefs.filter(b=>b.domain===selEntity.domain) : [];

  const setStatus=(id,s)=>setBeliefState(st=>({...st,[id]:s}));
  const confColor=c=>c>=0.9?'var(--green)':c>=0.75?'var(--accent-light)':c>=0.6?'var(--amber)':'var(--red)';

  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><IcW d={IKW.globe} size={14}/><span className="ttl">{t.wvTitle}</span>
        <span className="st">{W.stats.entities} entities · {W.stats.beliefs} beliefs · avg conf {W.stats.avg_conf}</span></div>
      <div className="wv-body">
        {/* LEFT: constellation */}
        <div className="wv-stage">
          <div className="wv-toolbar">
            <div className="wv-search"><IcW d={IKW.search} size={13}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder={t.wvSearch}/></div>
            <div className="wv-filters">
              <button className={'cf'+(domain==='all'?' on':'')} onClick={()=>setDomain('all')}>{t.wvAll}</button>
              {W.domains.map(d=><button key={d.id} className={'cf'+(domain===d.id?' on':'')} onClick={()=>setDomain(d.id)}>{d.label}</button>)}
            </div>
          </div>
          <div className="wv-canvas">
            <svg viewBox="0 0 760 600" preserveAspectRatio="xMidYMid meet" className="wv-svg"
              onClick={()=>setSel(null)}>
              <defs>
                <radialGradient id="wvcore" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity=".5"/>
                  <stop offset="60%" stopColor="var(--accent)" stopOpacity=".06"/>
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
                </radialGradient>
              </defs>
              {/* orbit rings */}
              {[R*0.62,R*0.95].map((r,i)=><circle key={i} cx={CX} cy={CY} r={r} fill="none" stroke="var(--panel-line)" strokeWidth=".6" strokeDasharray="1 6"/>)}
              {/* domain spokes + labels */}
              {W.domains.map(d=>{ const p=domainPos[d.id]; const dim=domain!=='all'&&domain!==d.id; return (
                <g key={d.id} opacity={dim?0.2:1} style={{cursor:'pointer'}} onClick={e=>{e.stopPropagation();setDomain(domain===d.id?'all':d.id);}}>
                  <line x1={CX} y1={CY} x2={p.x} y2={p.y} stroke={d.color} strokeWidth=".7" opacity=".3"/>
                  <text x={p.x} y={p.y-14} textAnchor="middle" className="wv-domain-label" fill={d.color}>{d.label.toUpperCase()}</text>
                </g>
              );})}
              {/* entity links */}
              {W.links.map((l,i)=>{ const a=ePos[l[0]],b=ePos[l[1]]; if(!a||!b)return null;
                const on=visIds.has(l[0])&&visIds.has(l[1]);
                return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--accent)" strokeWidth=".6" opacity={on?0.22:0.04}/>; })}
              {/* core glow + self */}
              <circle cx={CX} cy={CY} r="64" fill="url(#wvcore)"/>
              <g onClick={e=>{e.stopPropagation();setSel(null);}} style={{cursor:'pointer'}}>
                <circle cx={CX} cy={CY} r="30" fill="var(--void-2)" stroke="var(--accent)" strokeWidth="1.5"/>
                <circle cx={CX} cy={CY} r="30" fill="none" stroke="var(--accent)" strokeWidth=".6" opacity=".4" strokeDasharray="3 4"
                  style={{transformOrigin:`${CX}px ${CY}px`,animation:'spin 40s linear infinite'}}/>
                <path d={window.V2.GLYPHS.jarvis} transform={`translate(${CX},${CY}) scale(1.5)`} className="net-glyph" stroke="var(--accent-light)"/>
                <text x={CX} y={CY+48} textAnchor="middle" className="wv-self-label">{t.wvSelf} · ANDREI</text>
              </g>
              {/* entities */}
              {W.entities.map(e=>{ const p=ePos[e.id]; if(!p)return null;
                const vis=visIds.has(e.id); const isSel=sel&&sel.kind==='entity'&&sel.id===e.id;
                return (
                  <g key={e.id} transform={`translate(${p.x},${p.y})`} className="wv-node" opacity={vis?1:0.12}
                    style={{cursor:'pointer'}} onClick={ev=>{ev.stopPropagation(); setSel({kind:'entity',id:e.id});}}>
                    <circle r={isSel?13:10} fill="var(--surface-2)" stroke={isSel?'var(--accent)':domainPos[e.domain].color}
                      strokeWidth={isSel?2:1.3} style={isSel?{filter:'drop-shadow(0 0 6px var(--accent-glow))'}:{}}/>
                    <circle r="3.4" fill={domainPos[e.domain].color} opacity={e.conf}/>
                    <text y="22" textAnchor="middle" className="wv-node-label" fill={isSel?'var(--accent-light)':'var(--ink-2)'}>{e.label}</text>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="timeslider" style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',marginTop:10}}>
            <span className="tlab">{t.asof}</span>
            <input type="range" min="0" max={W.marks.length-1} step="1" value={ti} onChange={e=>setTi(+e.target.value)}/>
            <span className="asof">{W.marks[ti]}</span>
          </div>
        </div>

        {/* RIGHT: detail / beliefs */}
        <div className="wv-side">
          {!sel && (
            <div className="wv-beliefs">
              <div className="sub-h">{t.wvBeliefs} · {beliefs.length}</div>
              {beliefs.map(b=>{ const st=beliefState[b.id]; return (
                <div className={'belief-card '+st} key={b.id} onClick={()=>setSel({kind:'belief',id:b.id})}>
                  <div className="bc-top"><span className="bc-agent"><GlW id={b.agent} size={11}/>{b.agent}</span>
                    <span className="bc-conf" style={{color:confColor(b.conf)}}>{Math.round(b.conf*100)}%</span></div>
                  <div className="bc-text">{b.text}</div>
                  <div className="bc-foot"><span className={'bc-status '+st}>{t['wv'+st.charAt(0).toUpperCase()+st.slice(1)]||st}</span>
                    <span className="bc-conf-bar"><i style={{width:`${b.conf*100}%`,background:confColor(b.conf)}}></i></span></div>
                </div>
              );})}
            </div>
          )}
          {selEntity && (
            <div className="wv-detail">
              <button className="wv-back" onClick={()=>setSel(null)}>← {t.wvBeliefs}</button>
              <div className="wv-d-head">
                <span className="wv-d-dot" style={{background:domainPos[selEntity.domain].color}}></span>
                <div><div className="wv-d-name">{selEntity.label}</div><div className="wv-d-type">{selEntity.type} · {selEntity.domain}</div></div>
                <span className="wv-d-conf" style={{color:confColor(selEntity.conf)}}>{Math.round(selEntity.conf*100)}%</span>
              </div>
              <div className="wv-d-sub">{selEntity.sub}</div>
              <button className="wv-ask" onClick={()=>onAsk&&onAsk(selEntity.label)}><IcW d={IKW.chat} size={13}/> Ask Jarvis about {selEntity.label}</button>
              <div className="sub-h" style={{marginTop:16}}>RELATED BELIEFS · {relatedBeliefs.length}</div>
              {relatedBeliefs.map(b=>(
                <div className="belief-card mini" key={b.id} onClick={()=>setSel({kind:'belief',id:b.id})}>
                  <div className="bc-text">{b.text}</div>
                  <div className="bc-foot"><span className="bc-agent"><GlW id={b.agent} size={10}/>{b.agent}</span><span className="bc-conf" style={{color:confColor(b.conf)}}>{Math.round(b.conf*100)}%</span></div>
                </div>
              ))}
            </div>
          )}
          {selBelief && (
            <div className="wv-detail">
              <button className="wv-back" onClick={()=>setSel(null)}>← {t.wvBeliefs}</button>
              <div className="sub-h">{t.wvProvenance}</div>
              <div className="belief-hero">
                <div className="bh-text">"{selBelief.text}"</div>
                <div className="bh-meta"><span className="bc-agent"><GlW id={selBelief.agent} size={12}/>inferred by {selBelief.agent}</span>
                  <span className="bc-conf" style={{color:confColor(selBelief.conf)}}>{Math.round(selBelief.conf*100)}% confident</span></div>
              </div>
              <div className="sub-h" style={{marginTop:14}}>{t.wvEvidence}</div>
              {selBelief.ev.map((e,i)=><div className="ev-row" key={i}><span className="ev-dot"></span>{e}</div>)}
              <div className="wv-actions">
                <button className={'wv-act confirm'+(beliefState[selBelief.id]==='confirmed'?' on':'')} onClick={()=>setStatus(selBelief.id,'confirmed')}>✓ {t.wvConfirm}</button>
                <button className={'wv-act correct'+(beliefState[selBelief.id]==='disputed'?' on':'')} onClick={()=>setStatus(selBelief.id,'disputed')}>✎ {t.wvCorrect}</button>
                <button className="wv-act forget" onClick={()=>setStatus(selBelief.id,'forgotten')}>✕ {t.wvForget}</button>
              </div>
              {beliefState[selBelief.id]==='forgotten' && <div className="wv-forgotten">Belief marked for removal — Jarvis will stop acting on this.</div>}
              {beliefState[selBelief.id]==='confirmed' && <div className="wv-confirmed">Confirmed — confidence locked, weighted higher in routing.</div>}
              {beliefState[selBelief.id]==='disputed' && <div className="wv-disputed">Flagged for correction — tell Jarvis what's right in Chat.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
window.WorldviewMode = WorldviewMode;
