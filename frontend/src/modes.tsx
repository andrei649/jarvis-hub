import React, { useState, useMemo, useEffect } from 'react';
import { V2 } from './ui';
import { Glyph, statusClass } from './ui';
import { getAgentSoul, getAgentHistory, memorySearch } from './api/actions';
import { MemoryNeighborhood } from './panels/memory-neighborhood';
import { SavedFacts } from './panels/saved-facts';
import { SoulEditor } from './soul-edit';
import { AgentProfileControls, NewAgentDialog, RetiredAgents } from './agent-roster';
import { LABEL } from './theme/type';
import { PageSection } from './pages/PageSection';
import { fmt } from './frame/strings';
import { talkStrings } from './home/talk/strings';
/* HUD v2 · MODES — Agents, Memory. (Trust, TrustMode, was deleted at the Phase B cleanup: /v2/trust
   is pages/TrustOverview.tsx, with the typed resume and the graded payment decisions.) */

// Bolt Optimization: Precompute O(1) agent map for Dossier lookups
const V2_AGENTS_MAP = new Map(V2.AGENTS.map((a: any) => [a.id, a]));

/* ============ AGENTS ============ */
function AgentsMode({ agents, onOpen, t, onChanged = undefined }) {
  const TIERS = V2.TIERS;
  // H202: the owner's roster — a new agent (kept across restarts) and the retired ones.
  const [creating, setCreating] = useState(false);
  const [rosterTick, setRosterTick] = useState(0);
  const [createdNote, setCreatedNote] = useState('');

  // Bolt Optimization: Pre-group agents by tier and count live agents in a single pass to eliminate O(N) filtering per tier
  const { agentsByTier, liveCount } = useMemo(() => {
    const map = new Map<string, any[]>();
    let count = 0;
    for (let i = 0; i < agents.length; i++) {
      const a = agents[i];
      if (a.status !== 'idle') count++;
      let list = map.get(a.tier);
      if (!list) {
        list = [];
        map.set(a.tier, list);
      }
      list.push(a);
    }
    return { agentsByTier: map, liveCount: count };
  }, [agents]);

  return (
    <PageSection title={t.roster} meta={<>{agents.length} agents · {liveCount} live</>}
      headExtra={!creating && <button className="tool-btn" onClick={()=>{ setCreating(true); setCreatedNote(''); }}>+ New agent</button>}
      lead={<>
        {creating && <div style={{padding:'0 14px'}}><NewAgentDialog
          onCreated={(a)=>{ setCreating(false); setCreatedNote(`created ${a.name || a.id} · kept across restarts`); setRosterTick((n)=>n+1); onChanged?.(); }}
          onCancel={()=>setCreating(false)}/></div>}
        {createdNote && <div role="status" style={{padding:'4px 14px',fontSize:'var(--n-fs-meta)',color:'var(--green)'}}>{createdNote}</div>}
      </>}
      bodyProps={{ tabIndex: 0, role: 'group', 'aria-label': t.roster }}>
      {/* `overflow-y:auto` with no focusable child is WCAG 2.1.1: the agent cards are
          `<div className="acard" onClick=…>`, so there is nothing to tab to and the roster
          scrolls past the fold unreachable by keyboard (measured 774px of content in a
          670px box). `tabIndex={0}` is what the rest of the HUD already does for exactly
          this — panel-kit.tsx:69, shell.tsx:137/152/172/186/205/225. */}
      {/* `role="group"` is not decoration: `aria-label` on a role-less <div> is axe
          `serious · aria-prohibited-attr` ("cannot be used on a div with no valid role"), so the
          fix that added the name traded one serious finding for another. It went unnoticed because
          axe files that rule under `incomplete` here, and the mode walk gates on `violations` —
          the same blind spot the painted-contrast lane exists for, in a second rule. `group` is
          the minimal role that PERMITS a name (unlike `region` it adds no landmark), and it is the
          same shape as the `.convo` fix one commit earlier, which paired `role="log"` with its
          label for exactly this reason. */}
      {/* (the body's tabIndex, role and name are the PageSection's bodyProps above) */}
      <>
        {TIERS.map(tier=>{
          const list = agentsByTier.get(tier.id) || [];
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
        <RetiredAgents refresh={rosterTick} onRestored={()=>{ setRosterTick((n)=>n+1); onChanged?.(); }}/>
      </>
    </PageSection>
  );
}

/* `onWriteTo` (PHASE_B_PLAN.md §2.1, §6): App passes it only for an agent it takes as the recipient.
   "Write to <Agent>" makes that agent the one the owner writes to and closes the Dossier; opening
   the Dossier itself never changes the recipient. Its words are the conversation's own
   (home/talk/strings.ts `writeTo`), in the owner's language (`lang`). */
function Dossier({ id, onClose, onOpen, agents = undefined, onChanged = undefined, onWriteTo = undefined, lang = 'en' }) {
  // Soul + run-history are LIVE (as v1 does): GET /api/agents/{id}/soul reads the
  // on-disk SOUL.md, /api/agents/{id}/history rolls up recent runs. The seed dossier
  // (archetype/personality/runtime) is the static fallback for fields with no single
  // backend source; the real SOUL.md overrides the seeded soul blurb when it loads.
  const d = V2.DOSSIER[id] || {};
  // Bolt Optimization: O(1) Map lookup for agent details instead of O(N) array search
  // H202: the live roster row wins (a renamed agent's name), and an agent the owner
  // created — which the seed corpus never knew — still has a dossier.
  const live = Array.isArray(agents) ? agents.find((x) => x && x.id === id) : undefined;
  const seed = V2_AGENTS_MAP.get(id);
  const a = live ? { ...(seed || {}), ...live } : seed;
  const [soul,setSoul]=useState(null);   // real SOUL.md text (null = not loaded → seed)
  const [description,setDescription]=useState('');   // H156: the front-matter description
  const [editing,setEditing]=useState(false);        // H156: the persona editor is open
  const [runs,setRuns]=useState(null);   // real run history ([] = none, null = unloaded)
  const [renamed,setRenamed]=useState('');           // H202: the name a rename just saved
  useEffect(() => {
    if(!id) return;
    let alive = true;
    setEditing(false);
    setRenamed('');
    getAgentSoul(id).then((r) => { if(alive && r && r.soul) { setSoul(r.soul); setDescription(r.description || ''); } }).catch(() => {});
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
          <div><div className="nm">{renamed || a.name}</div><div className="ar">{d.archetype || a.role} · {a.tier}</div></div>
          {onWriteTo && <button type="button" className="tool-btn" data-dossier="write-to" style={{ marginLeft: 'auto' }}
            onClick={() => { onWriteTo(id); onClose(); }}>{fmt(talkStrings(lang).writeTo, { agent: renamed || a.name })}</button>}
          <button className="close" onClick={onClose} aria-label="Close dossier" style={onWriteTo ? { marginLeft: 0 } : undefined}>✕</button>
        </div>
        <div className="dossier-body">
          {/* H202: rename for good, or retire (nothing deleted), beside the persona editor. */}
          <div className="dsec"><div className="dl">Profile · {id}</div>
            <AgentProfileControls id={id} name={renamed || a.name}
              onRenamed={(n)=>{ setRenamed(n); onChanged?.(); }}
              onRetired={()=>{ onChanged?.(); onClose(); }}/>
          </div>
          {description && <div className="dsec"><div className="dl">Description</div><div className="dtx">{description}</div></div>}
          <div className="dsec"><div className="dl">Soul{soul!=null?' · SOUL.md':''}
            {soul!=null && !editing && <button className="tool-btn" style={{marginLeft:8}} onClick={()=>setEditing(true)}>Edit persona</button>}</div>
            {editing
              ? <SoulEditor id={id} live={soul || ''} onApplied={(t)=>{ setSoul(t); getAgentSoul(id).then((r)=>{ if(r && r.soul){ setSoul(r.soul); setDescription(r.description || ''); } }).catch(()=>{}); }} onCancel={()=>setEditing(false)}/>
              : <div className="dtx soul">{soulText}</div>}
          </div>
          {d.personality && <div className="dsec"><div className="dl">Personality</div><div className="dtx">{d.personality}</div></div>}
          <div className="dsec"><div className="dl">Runtime</div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px 16px'}}>
              {[['Model',d.model||a.model],['Channel',d.channel],['Heartbeat',d.heartbeat],['Policy',d.policy||a.policy],['Skills',d.skills],['Memory facts',d.memory_facts]].map(([k,v])=>(
                <div key={k} style={{fontFamily:'var(--font-mono)',fontSize:'var(--n-fs-label)'}}>
                  <span style={{...LABEL, color:'var(--ink-2)',fontSize:'var(--n-fs-meta)',display:'block'}}>{k}</span>
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
                <div key={i} style={{display:'flex',justifyContent:'space-between',fontFamily:'var(--font-mono)',fontSize:'var(--n-fs-meta)',color:'var(--ink-2)',padding:'3px 0',borderBottom:'1px solid var(--panel-line)'}}>
                  <span>{r.kind || r.title || r.action || 'run'}</span>
                  <span style={{color:(r.ok===false||r.status==='error')?'var(--red)':'var(--green)'}}>{r.status || (r.ok===false?'fail':'ok')}{r.latency_ms!=null?' · '+r.latency_ms+'ms':''}</span>
                </div>
              ))}
            </div>
          )}
          {plugins.length>0 && <div className="dsec"><div className="dl">Plugins</div><div className="dep-links">{plugins.map(p=><span key={p} className="dep-link" style={{cursor:'default'}}>{p}</span>)}</div></div>}
          <div className="dsec"><div className="dl">Collaborates with</div>
            <div className="dep-links">{deps.map(dep=>{ const da=V2_AGENTS_MAP.get(dep); return <span key={dep} className="dep-link" onClick={()=>onOpen(dep)}><Glyph id={dep} size={12}/>{da?da.name:dep}</span>; })}</div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ============ MEMORY + KG ============ */
function MemoryMode({ t, demo = false }) {
  const D = V2;
  const M = D.MEMORY_STATS;
  const marks = D.KG.marks;
  const [ti,setTi]=useState(marks.length-1);
  // LIVE recalls: GET /api/memory/search returns the user's actual top hits. We map
  // the backend {score,payload,sources} → the seed's {rx,rsrc,score} row shape and
  // use real results in live mode; samples belong only to explicit Demo mode.
  const [recalls,setRecalls]=useState(null);
  const [recallState,setRecallState]=useState('Loading recalls…');
  useEffect(() => {
    let alive = true;
    setRecalls(null);
    if (demo) return () => { alive = false; };
    setRecallState('Loading recalls…');
    // A neutral query surfaces the most salient memories for the "recent recalls" panel.
    memorySearch('recent').then((r) => {
      if (!alive) return;
      if (!r || ('error' in r && r.error) || !Array.isArray(r.results)) throw new Error('Memory recall unavailable');
      const res = r.results;
      setRecallState(res.length ? '' : 'No matching memories.');
      setRecalls(res.slice(0,6).map((h: any) => {
        const p = h.payload || {};
        const text = p.text || p.content || p.summary || (typeof h.payload === 'string' ? h.payload : '') || h.id || '';
        const src = (Array.isArray(h.sources) ? h.sources.join('+') : (h.sources || '')) || 'memory';
        const sc = h.score != null ? Number(h.score).toFixed(2) : '';
        return { rx: String(text).slice(0,90), rsrc: src + (sc?' · '+sc:''), score: sc };
      }));
    }).catch(() => { if (alive) { setRecalls([]); setRecallState('Memory recall unavailable.'); } });
    return () => { alive = false; };
  }, [demo]);
  const RECALLS = demo ? D.RECALLS : (recalls || []);
  const born = ti; // 0..3
  const visNodes = D.KG.nodes.filter(n=>n.born<=born);
  const visIds = new Set(visNodes.map(n=>n.id));
  return (
    <PageSection title={t.memTitle} meta={demo ? 'DEMO · sample memory' : 'stored memory'}>
      <>
        {!demo && <SavedFacts />}
        <div className="mem-grid" style={{marginBottom:'var(--gap)'}}>
          {[[M.sessions,'sessions'],[M.vectors,'vectors'],[M.entities,'entities'],[M.relations,'relations']].map(([v,l],i)=>(
            <div className="stat-card" key={i}><div className="sv">{v}</div><div className="sl">{l}</div></div>
          ))}
        </div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'var(--gap)',alignItems:'start'}}>
          <div style={{border:'1px solid var(--panel-line)',borderRadius:'var(--radius)',padding:14,background:'var(--surface-2)'}}>
            <div className="dl" style={{...LABEL,fontSize:'var(--n-fs-meta)',color:'var(--ink-2)',marginBottom:8}}>{t.recall}</div>
            {!demo && <div role="status" style={{fontSize:'var(--n-fs-label)',color:'var(--ink-2)'}}>{recallState}</div>}
            {RECALLS.map((r,i)=>(
              <div className="recall-row" key={i}><div><div className="rx">{r.rx}</div><div className="rsrc">{r.rsrc}</div></div><span className="recall-score">{r.score}</span></div>
            ))}
            {demo && <><div className="dl" style={{...LABEL,fontSize:'var(--n-fs-meta)',color:'var(--ink-2)',margin:'16px 0 8px'}}>{t.spaces}</div>
            {D.TOPICS.map((tp,i)=>(
              <div key={i} style={{marginBottom:8}}>
                <div style={{display:'flex',justifyContent:'space-between',fontSize:'var(--n-fs-meta)',color:'var(--ink-2)'}}><span>{tp.t}</span><span style={{fontFamily:'var(--font-mono)',color:'var(--ink-2)'}}>{100-tp.d}% fresh</span></div>
                <div className="decay-bar"><i style={{width:(100-tp.d)+'%'}}></i></div>
              </div>
            ))}</>}
          </div>
          {/* KG */}
          {demo ? (() => {
            // Bolt Optimization: Precompute O(1) node Map for Knowledge Graph edge endpoint lookups
            // to avoid 2x O(N) array scans per edge during time-slider interactions
            const kgNodeMap = new Map(D.KG.nodes.map((n: any) => [n.id, n]));
            return (
            <div>
            <div className="kg-wrap">
              <svg className="kg-svg" viewBox="0 0 640 380" preserveAspectRatio="xMidYMid meet">
                {D.KG.edges.map((e,i)=>{
                  const on = e.born<=born && visIds.has(e.a) && visIds.has(e.b);
                  const A=kgNodeMap.get(e.a) as any, B=kgNodeMap.get(e.b) as any;
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
            <div style={{fontSize:'var(--n-fs-meta)',color:'var(--ink-2)',marginTop:8,textAlign:'center'}}>bitemporal · drag to travel through what Nerva knew</div>
          </div>);
          })() : <MemoryNeighborhood />}
        </div>
      </>
    </PageSection>
  );
}

export { AgentsMode, Dossier, MemoryMode };
