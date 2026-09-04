import React, { useState, useMemo, useEffect } from 'react';
import { V2, Conversation, InputBar } from './ui';
import { Icon, ICONS, Glyph, statusClass } from './ui';
import { getKillSwitch, setKillSwitch, getAgentSoul, getAgentHistory, memorySearch, decidePayment, getAuditVerify } from './api/actions';
/* HUD v2 · MODES — Agents, Trust, Memory */

/* ============ AGENTS ============ */
function AgentsMode({ agents, onOpen, t }) {
  const TIERS = V2.TIERS;
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.agents} size={14}/><span className="ttl">{t.roster}</span><span className="st">{agents.length} agents · {agents.filter(a=>a.status!=='idle').length} live</span></div>
      {/* `overflow-y:auto` with no focusable child is WCAG 2.1.1: the agent cards are
          `<div className="acard" onClick=…>`, so there is nothing to tab to and the roster
          scrolls past the fold unreachable by keyboard (measured 774px of content in a
          670px box). `tabIndex={0}` is what the rest of the HUD already does for exactly
          this — panel-kit.tsx:69, shell.tsx:137/152/172/186/205/225. */}
      <div className="panel-body" tabIndex={0}>
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
  // Soul + run-history are LIVE (as v1 does): GET /api/agents/{id}/soul reads the
  // on-disk SOUL.md, /api/agents/{id}/history rolls up recent runs. The seed dossier
  // (archetype/personality/runtime) is the static fallback for fields with no single
  // backend source; the real SOUL.md overrides the seeded soul blurb when it loads.
  const d = V2.DOSSIER[id] || {};
  const a = V2.AGENTS.find(x=>x.id===id);
  const [soul,setSoul]=useState(null);   // real SOUL.md text (null = not loaded → seed)
  const [runs,setRuns]=useState(null);   // real run history ([] = none, null = unloaded)
  useEffect(() => {
    if(!id) return;
    let alive = true;
    getAgentSoul(id).then((r) => { if(alive && r && r.soul) setSoul(r.soul); }).catch(() => {});
    getAgentHistory(id).then((r) => { if(alive && r && Array.isArray(r.runs)) setRuns(r.runs); }).catch(() => {});
    return () => { alive = false; };
  }, [id]);
  if(!a) return null;
  const deps = (V2.COLLAB.filter(([x,y])=>x===id||y===id).map(([x,y])=>x===id?y:x));
  const soulText = soul != null ? soul : (d.soul || '');
  const plugins = d.plugins || [];
  return (
    <>
      <div className="dossier-scrim" onClick={onClose}></div>
      <div className="dossier">
        <div className="dossier-head">
          <span className="big-glyph"><Glyph id={id} size={46}/></span>
          <div><div className="nm">{a.name}</div><div className="ar">{d.archetype || a.role} · {a.tier}</div></div>
          <button className="close" onClick={onClose}>✕</button>
        </div>
        <div className="dossier-body">
          <div className="dsec"><div className="dl">Soul{soul!=null?' · SOUL.md':''}</div><div className="dtx soul">{soulText}</div></div>
          {d.personality && <div className="dsec"><div className="dl">Personality</div><div className="dtx">{d.personality}</div></div>}
          <div className="dsec"><div className="dl">Runtime</div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px 16px'}}>
              {[['Model',d.model||a.model],['Channel',d.channel],['Heartbeat',d.heartbeat],['Policy',d.policy||a.policy],['Skills',d.skills],['Memory facts',d.memory_facts]].map(([k,v])=>(
                <div key={k} style={{fontFamily:'var(--font-mono)',fontSize:12}}>
                  <span style={{color:'var(--ink-3)',fontSize:9,letterSpacing:'.1em',textTransform:'uppercase',display:'block'}}>{k}</span>
                  <span style={{color:'var(--accent-light)'}}>{v != null && v !== '' ? v : '—'}</span>
                </div>
              ))}
            </div>
          </div>
          {/* Recent runs — REAL data from /api/agents/{id}/history. Shown only when the
              backend actually returns runs (empty/unreachable → section hidden). */}
          {runs != null && runs.length > 0 && (
            <div className="dsec"><div className="dl">Recent runs · {runs.length}</div>
              {runs.slice(0,5).map((r,i)=>(
                <div key={i} style={{display:'flex',justifyContent:'space-between',fontFamily:'var(--font-mono)',fontSize:11,color:'var(--ink-2)',padding:'3px 0',borderBottom:'1px solid var(--panel-line)'}}>
                  <span>{r.kind || r.title || r.action || 'run'}</span>
                  <span style={{color:(r.ok===false||r.status==='error')?'var(--red)':'var(--green)'}}>{r.status || (r.ok===false?'fail':'ok')}{r.latency_ms!=null?' · '+r.latency_ms+'ms':''}</span>
                </div>
              ))}
            </div>
          )}
          {plugins.length>0 && <div className="dsec"><div className="dl">Plugins</div><div className="dep-links">{plugins.map(p=><span key={p} className="dep-link" style={{cursor:'default'}}>{p}</span>)}</div></div>}
          <div className="dsec"><div className="dl">Collaborates with</div>
            <div className="dep-links">{deps.map(dep=>{ const da=V2.AGENTS.find(x=>x.id===dep); return <span key={dep} className="dep-link" onClick={()=>onOpen(dep)}><Glyph id={dep} size={12}/>{da?da.name:dep}</span>; })}</div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ============ TRUST ============ */
function TrustMode({ t, localPct = null }) {
  // Kill-switch is a REAL operator control: GET /api/security/kill-switch reflects
  // live state, POST engages/disengages (admin-guarded). Optimistic flip with a
  // re-sync from the server response so the UI never lies about halt state.
  const [killed,setKilled]=useState(false);
  const [busy,setBusy]=useState(false);
  const [killErr,setKillErr]=useState(false);
  const [,payTick]=useState(0);
  // Live tamper-evidence: GET /api/security/audit/verify actually re-checks the
  // Merkle chain, so the "verified" badge reflects a real result instead of a
  // static claim. {valid, first_invalid_id, entries} — null while loading.
  const [audit,setAudit]=useState(null);
  const [auditErr,setAuditErr]=useState(false);
  useEffect(()=>{
    let alive=true;
    getAuditVerify().then(r=>{ if(alive&&r) setAudit(r); }).catch(()=>{ if(alive) setAuditErr(true); });
    return ()=>{ alive=false; };
  },[]);
  const D = V2;
  // Payment lifecycle (H16.3): act on the broker, then reflect its returned state in
  // the shared ledger — live.ts re-syncs from /api/payments on its next poll.
  const payAct = (p, action) => {
    if (!p.id) return;
    decidePayment(p.id, action)
      .then((r: any) => { p.state = (r && (r.state || r.status)) || (action === 'approve' ? 'approved' : action === 'reject' ? 'rejected' : 'cleared'); payTick((n) => n + 1); })
      .catch(() => {});
  };
  useEffect(() => {
    let alive = true;
    // `halted` is a MAP {agent: reason}, not a bool — `s.halted ?? s.engaged` was {} (truthy)
    // and falsely showed the kill-switch engaged (2026-07-24 QA finding). Engaged iff the
    // global switch is on OR any agent is in the halted map.
    getKillSwitch().then((s) => { if (alive && s) setKilled(!!(s.global || Object.keys(s.halted || {}).length || s.engaged)); }).catch(() => { if (alive) setKillErr(true); });
    return () => { alive = false; };
  }, []);
  const toggleKill = () => {
    if (busy) return;
    const next = !killed;
    setBusy(true); setKilled(next); // optimistic
    setKillSwitch(next)
      .then((r: any) => { if (r) setKilled(!!(r.engaged ?? next)); })
      .catch(() => { setKilled(!next); setKillErr(true); }) // revert on failure — honest
      .finally(() => setBusy(false));
  };
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS.trust} size={14}/><span className="ttl">{t.trust} Center</span>
        <span className="st" style={audit&&!audit.valid?{color:'var(--red)'}:undefined}>{
          auditErr ? 'audit unavailable'
          : audit==null ? 'verifying…'
          : audit.valid ? `Merkle-verified · ${audit.entries} entries`
          : `chain broken @ #${audit.first_invalid_id}`
        }</span></div>
      <div className="panel-body">
        <div className="trust-grid">
          {/* left: audit chain */}
          <div>
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>{t.auditTitle}</div>
            {/* Live chain-verification result (real GET /api/security/audit/verify),
                replacing the static badge. Falls back to the demo chain visual below. */}
            <div className="verified-row" style={audit&&!audit.valid?{color:'var(--red)'}:undefined}>
              <Icon d={ICONS.trust} size={13}/> {
                auditErr ? t.verified
                : audit==null ? 'verifying chain…'
                : audit.valid ? `chain intact · ${audit.entries} sealed entries`
                : `TAMPER DETECTED · first bad row #${audit.first_invalid_id}`
              }</div>
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
              <button className={'killbtn'+(killed?' engaged':'')} onClick={toggleKill} disabled={busy} title={busy?'updating…':killed?'disengage kill-switch':'halt all agents'}>
                <Icon d={ICONS.shield} size={26}/>
                <span className="kt">{killed?'HALTED':'STOP'}</span>
                <span className="ks">{t.killSub}</span>
              </button>
              <div className={'kill-status '+(killed?'engaged':'armed')}>{killErr?'kill-switch unavailable':killed?t.engaged:t.armed}</div>
            </div>

            {/* Locality is shown ONLY when a real source backs it (strict-local proof
                → 100%, or DEMO sample). Unknown → the whole block is hidden, never a
                fabricated split. localPct comes from /api/trust/status via app.tsx. */}
            {localPct != null && (
            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:10}}>{t.locality}</div>
              <div className="loc-ring-wrap">
                <div className="loc-pct">{localPct}%</div>
                <div className="loc-legend">
                  <div className="ll"><span className="sw" style={{background:'var(--green)'}}></span> on-device · {localPct}%</div>
                  <div className="ll"><span className="sw" style={{background:'var(--violet)'}}></span> cloud · {100-localPct}%</div>
                </div>
              </div>
              <div className="loc-bar"><div className="seg local" style={{width:localPct+'%'}}></div><div className="seg cloud" style={{width:(100-localPct)+'%'}}></div></div>
            </div>
            )}

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:6}}>{t.capsTitle}</div>
              {D.CAPABILITIES.map((c,i)=>(
                <div className="cap-row" key={i}><div><div className="cn">{c.cn}</div><div className="cd">{c.cd}</div></div><span className={'cap-tag '+c.tag}>{c.tagLabel}</span></div>
              ))}
            </div>

            <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
              <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',marginBottom:6}}>{t.payTitle}</div>
              {D.PAYMENTS.map((p: { pcap: string; desc: string; amt: string; state: string; id?: string }, i)=>(
                <div className="pay-row" key={i}><span className="pcap">{p.pcap}</span><span style={{color:'var(--ink-2)'}}>{p.desc}</span>
                  <span style={{textAlign:'right',color:p.state==='pending'?'var(--amber)':p.state==='cleared'?'var(--green)':'var(--ink-3)'}}>{p.amt}</span>
                  {/* Lifecycle controls only when the row carries a real broker id (live data). */}
                  {p.id && p.state==='pending' && (
                    <span style={{display:'flex',gap:4,marginLeft:6}}>
                      <button className="tool-btn" title="approve payment" onClick={()=>payAct(p,'approve')}>✓</button>
                      <button className="tool-btn" title="reject payment" onClick={()=>payAct(p,'reject')}>✕</button>
                    </span>
                  )}
                  {p.id && p.state==='approved' && (
                    <button className="tool-btn" style={{marginLeft:6}} title="settle approved payment" onClick={()=>payAct(p,'settle')}>settle</button>
                  )}
                </div>
              ))}
              {/* Pending count is computed from the REAL ledger (PAYMENTS ← /api/payments),
                  not a hardcoded "€4,200 sweep" claim. Hidden when nothing is pending. */}
              {D.PAYMENTS.filter(p=>p.state==='pending').length>0 && (
                <div className="pay-pending"><span style={{color:'var(--amber)',fontFamily:'var(--font-mono)',fontSize:11}}>⏳ {D.PAYMENTS.filter(p=>p.state==='pending').length} payment{D.PAYMENTS.filter(p=>p.state==='pending').length===1?'':'s'} awaiting your approval</span></div>
              )}
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
  // LIVE recalls: GET /api/memory/search returns the user's actual top hits. We map
  // the backend {score,payload,sources} → the seed's {rx,rsrc,score} row shape and
  // replace the mock list when real results arrive (empty/offline → keep seed corpus).
  const [recalls,setRecalls]=useState(null);
  useEffect(() => {
    let alive = true;
    // A neutral query surfaces the most salient memories for the "recent recalls" panel.
    memorySearch('recent').then((r) => {
      const res = r && Array.isArray(r.results) ? r.results : [];
      if (!alive || !res.length) return;
      setRecalls(res.slice(0,6).map((h: any) => {
        const p = h.payload || {};
        const text = p.text || p.content || p.summary || (typeof h.payload === 'string' ? h.payload : '') || h.id || '';
        const src = (Array.isArray(h.sources) ? h.sources.join('+') : (h.sources || '')) || 'memory';
        const sc = h.score != null ? Number(h.score).toFixed(2) : '';
        return { rx: String(text).slice(0,90), rsrc: src + (sc?' · '+sc:''), score: sc };
      }));
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const RECALLS = recalls || D.RECALLS;
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
            {RECALLS.map((r,i)=>(
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
              {/* An unlabelled input is `critical · label`: a screen reader announced this
                  only as "slider". The visible "AS OF" text is a sibling, not a label. */}
              <input type="range" min="0" max={marks.length-1} step="1" value={ti}
                     aria-label={t.timeTravel} onChange={e=>setTi(+e.target.value)}/>
              <span className="asof">{marks[ti]}</span>
            </div>
            <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,color:'var(--ink-4)',marginTop:8,textAlign:'center'}}>bitemporal · drag to travel through what Nerva knew</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export { AgentsMode, Dossier, TrustMode, MemoryMode };
