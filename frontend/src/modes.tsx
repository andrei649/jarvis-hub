// @ts-nocheck
import React, { useState, useMemo } from 'react';
import { V2, Conversation, InputBar } from './ui';
import { Icon, ICONS, Glyph, statusClass } from './ui';
/* HUD v2 · MODES — Agents, Trust, Memory */

/* ============ AGENTS ============ */
function AgentsMode({ agents, onOpen, t }) {
  const TIERS = V2.TIERS;
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
  const d = V2.DOSSIER[id];
  const a = V2.AGENTS.find(x=>x.id===id);
  if(!d||!a) return null;
  const deps = (V2.COLLAB.filter(([x,y])=>x===id||y===id).map(([x,y])=>x===id?y:x));
  return (
    <>
      <div className="dossier-scrim" onClick={onClose}></div>
      <div className="dossier">
        <div className="dossier-head">
          <span className="big-glyph"><Glyph id={id} size={46}/></span>
          <div><div className="nm">{a.name}</div><div className="ar">{d.archetype} · {a.tier}</div></div>
          <button className="close" onClick={onClose}>✕</button>
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
            <div className="dep-links">{deps.map(dep=>{ const da=V2.AGENTS.find(x=>x.id===dep); return <span key={dep} className="dep-link" onClick={()=>onOpen(dep)}><Glyph id={dep} size={12}/>{da?da.name:dep}</span>; })}</div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ============ TRUST ============ */
function TrustMode({ t }) {
  const [killed,setKilled]=useState(false);
  const D = V2;
  const localPct = 87;
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.trust} size={14}/><span className="ttl">{t.trust} Center</span><span className="st">Merkle-verified</span></div>
      <div className="panel-body">
        <div className="trust-grid">
          {/* left: audit chain */}
          <div>
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>{t.auditTitle}</div>
            <div className="verified-row"><Icon d={ICONS.trust} size={13}/> {t.verified}</div>
            {D.AUDIT_CHAIN.map((b,i)=>(
              <div className="audit-block" key={i}>
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
              <button className={'killbtn'+(killed?' engaged':'')} onClick={()=>setKilled(k=>!k)}>
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
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============ MEMORY + KG ============ */
function MemoryMode({ t }) {
  const D = V2;
  const M = D.MEMORY_STATS;
  const marks = D.KG.marks;
  const [ti,setTi]=useState(marks.length-1);
  const born = ti; // 0..3
  const visNodes = D.KG.nodes.filter(n=>n.born<=born);
  const visIds = new Set(visNodes.map(n=>n.id));
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.memory} size={14}/><span className="ttl">{t.memTitle}</span><span className="st">qdrant · 768d</span></div>
      <div className="panel-body">
        <div className="mem-grid" style={{marginBottom:'var(--gap)'}}>
          {[[M.sessions,'sessions'],[M.vectors,'vectors'],[M.entities,'entities'],[M.relations,'relations']].map(([v,l],i)=>(
            <div className="stat-card" key={i}><div className="sv">{v}</div><div className="sl">{l}</div></div>
          ))}
        </div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'var(--gap)',alignItems:'start'}}>
          <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:8}}>{t.recall}</div>
            {D.RECALLS.map((r,i)=>(
              <div className="recall-row" key={i}><div><div className="rx">{r.rx}</div><div className="rsrc">{r.rsrc}</div></div><span className="recall-score">{r.score}</span></div>
            ))}
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',margin:'16px 0 8px'}}>{t.spaces}</div>
            {D.TOPICS.map((tp,i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'var(--ink-2)'}}><span>{tp.t}</span><span style={{fontFamily:'var(--font-mono)',color:'var(--ink-3)'}}>{100-tp.d}% fresh</span></div>
                <div className="decay-bar"><i style={{width:(100-tp.d)+'%'}}></i></div>
              </div>
            ))}
          </div>
          {/* KG */}
          <div>
            <div className="kg-wrap">
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
                  const on = n.born<=born;
                  const r = n.id==='andrei'?22:15;
                  return <g key={n.id} className={'kg-node'+(on?'':' faded')} transform={`translate(${n.x},${n.y})`}>
                    <circle r={r} style={n.id==='andrei'?{fill:'var(--accent-faint)',stroke:'var(--accent)'}:{}}/>
                    <text y={r+12} textAnchor="middle">{n.label}</text>
                  </g>;
                })}
              </svg>
            </div>
            <div className="timeslider" style={{border:'1px solid var(--panel-line)',borderTop:0,borderRadius:'0 0 var(--radius) var(--radius)'}}>
              <span className="tlab">{t.asof}</span>
              <input type="range" min="0" max={marks.length-1} step="1" value={ti} onChange={e=>setTi(+e.target.value)}/>
              <span className="asof">{marks[ti]}</span>
            </div>
            <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,color:'var(--ink-4)',marginTop:8,textAlign:'center'}}>bitemporal · drag to travel through what Jarvis knew</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export { AgentsMode, Dossier, TrustMode, MemoryMode };
