'use strict';
/* HUD v2 · MODES II — Autonomy, Build, Observe, Interop */
const { useState:uS2 } = React;
const { Icon:Ic, ICONS:IK, Glyph:Gl } = window;

function ModePanel({ icon, title, status, children }){
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ic d={IK[icon]} size={14}/><span className="ttl">{title}</span>{status&&<span className="st">{status}</span>}</div>
      <div className="panel-body">{children}</div>
    </div>
  );
}
function SubH({ children }){ return <div className="sub-h">{children}</div>; }

/* ============ AUTONOMY ============ */
function AutonomyMode({ t }){
  const A = window.V2.AUTONOMY;
  const [policies,setPolicies]=uS2(A.policies);
  const cycle = i => setPolicies(ps=>{ const np = ps.map((p,j)=> j===i ? {...p, mode: p.mode==='auto'?'ask':p.mode==='ask'?'off':'auto'} : p); try{ window.JarvisClient && window.JarvisClient.post('/autonomy/policy',{agent:np[i].agent,mode:np[i].mode}).catch(()=>{}); }catch(e){} return np; });
  return (
    <ModePanel icon="autonomy" title={t.autonomy} status="observer running">
      <div className="pref-banner">
        <span className="pb-dot"></span>
        <span className="pb-tx"><b>Autonomy-raise suggestion:</b> Pepper ran 14 calendar reconciles this week with 0 rejects — raise her from <b>ASK</b> to <b>AUTO</b>?</span>
        <button className="pb-btn">Raise</button>
        <button className="pb-btn ghost">Dismiss</button>
      </div>
      <div className="auto-grid">
        <div>
          <SubH>MORNING BRIEF · {A.brief.length} items</SubH>
          {A.brief.map((b,i)=>(
            <div className="brief-row" key={i}>
              <span className="brank">{b.rank}</span>
              <div><div className="bt">{b.title}</div><div className="bd">{b.detail}</div></div>
              <span className="bag"><Gl id={b.agent.toLowerCase()} size={12}/>{b.agent}</span>
            </div>
          ))}
          <div className="subh-row"><SubH>OBSERVER LOG</SubH><button className="run-now" title="run the proactive observer now">▸ run now</button></div>
          {A.observer.map((o,i)=>(
            <div className="hbrow" key={i}><div className={'sev '+(o.result==='denied'?'alert':o.result==='held'?'warn':'ok')}></div>
              <div><div className="ht"><span className="ag">{o.agent}</span><span>{o.ts}</span><span style={{marginLeft:'auto'}}>{o.result}</span></div><div className="hx">{o.action}</div></div></div>
          ))}
        </div>
        <div>
          <SubH>AUTONOMY POLICIES · what each agent may do unattended</SubH>
          {policies.map((p,i)=>(
            <div className="pol-row" key={i}>
              <span className="pag"><Gl id={p.agent} size={14}/>{p.agent}</span>
              <div className="pscope"><div>{p.scope}</div><div className="pbud">{p.budget} · {p.used}</div></div>
              <button className={'pmode '+p.mode} onClick={()=>cycle(i)} title="click to change">{p.mode.toUpperCase()}</button>
            </div>
          ))}
          <div className="pol-note">Tap a mode to cycle <b>AUTO → ASK → OFF</b>. Budgeted actions log to the audit chain.</div>
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ BUILD ============ */
function BuildMode({ t }){
  const B = window.V2.BUILD;
  const W = B.workflow;
  const [skills,setSkills]=uS2(B.skills);
  const toggle = i => setSkills(ss=>ss.map((s,j)=>j===i?{...s,installed:!s.installed}:s));
  const kindColor = k => k==='trigger'?'var(--amber)':k==='plugin'?'var(--accent-light)':k==='agent'?'var(--accent)':'var(--green)';
  return (
    <ModePanel icon="build" title={t.build} status="workflow canvas">
      <SubH>WORKFLOW · {W.name} <span className="wf-status">{W.status}</span></SubH>
      <div className="wf-canvas">
        <svg viewBox="0 0 860 240" preserveAspectRatio="xMidYMid meet" style={{width:'100%',height:240}}>
          {W.edges.map((e,i)=>{ const a=W.nodes.find(n=>n.id===e[0]), b=W.nodes.find(n=>n.id===e[1]);
            return <path key={i} className="wf-edge flow-edge" d={`M${a.x+58},${a.y+16} C${a.x+110},${a.y+16} ${b.x-50},${b.y+16} ${b.x},${b.y+16}`} fill="none"/>; })}
          {W.nodes.map(n=>(
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              <rect width="116" height="32" rx="5" fill="var(--surface-2)" stroke={kindColor(n.kind)} strokeWidth="1.2"/>
              <circle cx="13" cy="16" r="3" fill={kindColor(n.kind)}/>
              <text x="26" y="20" className="wf-label">{n.label}</text>
            </g>
          ))}
        </svg>
      </div>
      <div className="obs-controls" style={{margin:'4px 0 14px'}}>
        <button className="run-now">+ New agent · from template</button>
        <button className="run-now">▣ Canvas · shared scratch</button>
        <button className="run-now">▸ Sandbox execute (DEV_MODE)</button>
      </div>
      <div className="build-grid">
        <div>
          <SubH>SKILLS · {skills.filter(s=>s.installed).length} installed</SubH>
          {skills.map((s,i)=>(
            <div className="skill-row" key={i}>
              <div><div className="skn">{s.name}</div><div className="skd">{s.desc}</div>
                <div className="skmeta"><span className="skby"><Gl id={s.author} size={11}/>{s.author}</span>{s.installed&&<span className="skruns">{s.runs} runs</span>}</div></div>
              <button className={'skbtn '+(s.installed?'on':'')} onClick={()=>toggle(i)}>{s.installed?'INSTALLED':'INSTALL'}</button>
            </div>
          ))}
        </div>
        <div>
          <SubH>SANDBOX · dry-run the router</SubH>
          <div className="sandbox">
            {B.sandbox.map((s,i)=>(
              <div key={i} className="sb-line"><div className="sb-in"><span className="sb-pre">›</span> {s.in}</div><div className="sb-out">{s.out}</div></div>
            ))}
            <div className="sb-line"><div className="sb-in"><span className="sb-pre" style={{animation:'blink 1.4s infinite'}}>›</span> <span style={{color:'var(--ink-3)'}}>type a call to simulate…</span></div></div>
          </div>
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ OBSERVE ============ */
function ObserveMode({ t }){
  const O = window.V2.OBSERVE;
  const [thr,setThr]=uS2(80);
  const maxLat = Math.max(...O.by_agent.map(a=>a.v));
  return (
    <ModePanel icon="observe" title={t.observe} status="traces · eval · resilience">
      <div className="mem-grid" style={{marginBottom:'var(--gap)'}}>
        <div className="stat-card"><div className="sv">{Math.round(O.quality.success_rate*100)}%</div><div className="sl">success rate</div></div>
        <div className="stat-card"><div className="sv">{O.quality.interactions}</div><div className="sl">interactions</div></div>
        <div className="stat-card"><div className="sv">{O.bench.p50}s</div><div className="sl">latency p50</div></div>
        <div className="stat-card"><div className="sv">{O.resilience.uptime}</div><div className="sl">uptime</div></div>
      </div>
      <div className="obs-controls">
        <div className="oc-item"><span className="oc-k">quality threshold</span><input type="range" min="50" max="99" value={thr} onChange={e=>setThr(+e.target.value)}/><span className="oc-v">{(thr/100).toFixed(2)}</span></div>
        <button className="run-now">▸ Run eval set</button>
        <button className="run-now">⇄ Compare regressions</button>
        <button className="run-now">⚑ Review queue · 4</button>
        <button className="run-now">▶ Arena · run + vote</button>
      </div>
      <div className="obs-grid">
        <div>
          <SubH>RECENT TRACES</SubH>
          {O.traces.map((tr,i)=>(
            <div className="trace-row" key={i}>
              <div className="tr-top"><span className="tr-id">{tr.id}</span><span className="tr-q">{tr.query}</span><span className={'tr-status '+tr.status}>{tr.status}</span><span className="tr-tot">{tr.total}ms</span></div>
              <div className="tr-bar">
                {tr.stages.map((s,j)=><span key={j} className={'tr-seg seg-'+s.s} style={{flex:s.ms}} title={s.s+' '+s.ms+'ms'}></span>)}
              </div>
              <div className="tr-agents">{tr.agents.map(a=><span key={a} className="topic-pill"><Gl id={a} size={10}/>{a}</span>)}</div>
            </div>
          ))}
          <SubH style={{marginTop:16}}>MODEL ARENA</SubH>
          {O.arena.map((m,i)=>(
            <div className={'arena-row'+(m.pick?' pick':'')} key={i}>
              <span className="arn">{m.model}{m.pick&&<span className="arpick">DEFAULT</span>}</span>
              <span className="arw">{m.wins}% wins</span><span className="arl">{m.latency}</span><span className="arc">{m.cost}</span>
            </div>
          ))}
        </div>
        <div>
          <SubH>LATENCY BY AGENT</SubH>
          {O.by_agent.map((a,i)=>(
            <div className="meter" key={i}>
              <div className="ml"><span style={{display:'flex',gap:6,alignItems:'center'}}><Gl id={a.id} size={11}/>{a.id}</span><span>{a.v}s</span></div>
              <div className="mt"><div className="mf" style={{width:(a.v/maxLat*100)+'%'}}></div></div>
            </div>
          ))}
          <SubH style={{marginTop:16}}>RESILIENCE</SubH>
          <div className="cap-row"><div className="cn">SSRF blocked</div><span className="cap-tag allow">{O.resilience.ssrf_blocked}</span></div>
          <div className="cap-row"><div className="cn">Errors · 24h</div><span className="cap-tag allow">{O.resilience.errors_24h}</span></div>
          <div className="cap-row"><div className="cn">PII redactions</div><span className="cap-tag gated">{O.resilience.redactions}</span></div>
          <div className="cap-row"><div className="cn">Escalations</div><span className="cap-tag scoped">{O.quality.escalations}</span></div>
        </div>
      </div>
      <div className="aios">
        <div className="aios-head"><Ic d={IK.admin} size={14}/><span className="aios-t">AI-OS · ORIZONT 24</span><span className="aios-tag">roadmap · the OS metaphor, made literal</span></div>
        <div className="aios-grid">
          <div className="aios-card">
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)'}}>ACTION KERNEL · syscall table</div>
            <div className="aios-sub">every privileged action → kernel.authorize(action, capability, budget) → grant / deny / queue</div>
            <div className="ksys-head"><span>kind</span><span>grant</span><span>deny</span><span>queue</span><span>budget</span></div>
            {window.V2.KERNEL_SYSCALLS.map((k,i)=>(
              <div className="ksys-row" key={i}><span className="ksys-k">{k.kind}</span><span className="ksys-g">{k.grant}</span><span className="ksys-d">{k.deny}</span><span className="ksys-q">{k.queue}</span><span className="ksys-b">{k.budget}</span></div>
            ))}
          </div>
          <div className="aios-card">
            <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)'}}>VERIFICATION FABRIC · readiness</div>
            <div className="aios-sub">nothing reaches VERIFIED without a green reality-harness · {window.V2.VFABRIC.harness}</div>
            <div className="vf-counts"><span className="vf-c ga">{window.V2.VFABRIC.ga} GA</span><span className="vf-c ver">{window.V2.VFABRIC.verified} VERIFIED</span><span className="vf-c wir">{window.V2.VFABRIC.wired} WIRED</span><span className="vf-c seam">{window.V2.VFABRIC.seam} SEAM</span></div>
            {window.V2.VFABRIC.caps.map((c,i)=>(<div className="vf-row" key={i}><span className="vf-n">{c.id}</span><span className={'vf-state '+c.state.toLowerCase()}>{c.state}</span></div>))}
          </div>
        </div>
        <div className="dl" style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.16em',textTransform:'uppercase',color:'var(--ink-3)',margin:'16px 0 0'}}>LIVE CAPABILITY PACKS · breadth on the substrate</div>
        <div className="packs">
          {window.V2.LIVE_PACKS.map((p,i)=>(
            <div className={'pack '+p.state.toLowerCase()} key={i}>
              <div className="pk-top"><span className="pk-n">{p.name}</span><span className={'vf-state '+p.state.toLowerCase()}>{p.state}</span></div>
              <div className="pk-agents">{p.agents.map(a=><span key={a} className="gx"><Gl id={a} size={13}/></span>)}</div>
              <div className="pk-note">{p.note}</div>
            </div>
          ))}
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ INTEROP ============ */
const A2A_INBOX = [
  { peer:'vision-mesh.local', req:'read calendar (next 7 days)', risk:'scoped', verified:true },
  { peer:'partner-agent.eu', req:'POST summary to external webhook', risk:'gated', verified:false },
  { peer:'research-swarm.cloud', req:'delegate 1 search task', risk:'scoped', verified:true },
];
function InteropMode({ meshRes, t }){
  const N = window.V2.INTEROP;
  const MESH = (meshRes && meshRes.data) || window.V2.MESH;
  const [inbox,setInbox]=uS2(A2A_INBOX);
  const resolve=(i)=>setInbox(x=>x.filter((_,j)=>j!==i));
  return (
    <ModePanel icon="interop" title={t.interop} status="Mesh · A2A · MCP · widgets">
      <SubH>{t.meshTitle} · pair devices, register nodes, delegate sub-agents</SubH>
      <div className="mesh-bar">
        <span className="mesh-sync"><span className="sdot active"></span>{MESH.sync.state}</span>
        <span className="mesh-sync-d">vector-lag {MESH.sync.vector_lag} · last full {MESH.sync.last_full} · {MESH.sync.conflicts} conflicts</span>
        <button className="da-btn" style={{marginLeft:'auto'}}><Ic d={IK.plus} size={12}/> Pair device</button>
      </div>
      <div className="mesh-grid">
        {MESH.devices.map((dv,i)=>(
          <div className={'mesh-card '+dv.kind} key={i}>
            <div className="mesh-ktop"><Ic d={dv.kind==='satellite'?IK.device:dv.kind==='sub-agent'?IK.mesh:IK.observe} size={14}/><span className="mesh-kind">{dv.kind}</span><span className={'sdot '+(dv.status==='idle'?'idle':'active')}></span></div>
            <div className="mesh-name">{dv.name}</div>
            <div className="mesh-role">{dv.role}</div>
            <div className="mesh-foot"><span>{dv.host}</span><span className="mesh-last">{dv.last}</span></div>
          </div>
        ))}
      </div>
      <div className="a2a-inbox">
        <SubH>A2A APPROVAL INBOX · incoming agent requests (verified peers never auto-execute)</SubH>
        {inbox.length===0 && <div className="ai-empty">Inbox clear — no pending peer requests.</div>}
        {inbox.map((r,i)=>(
          <div className="ai-row" key={i}>
            <span className={'sdot '+(r.verified?'active':'idle')}></span>
            <div className="ai-main"><div className="ai-peer">{r.peer}{r.verified&&<span className="ai-vfd">verified</span>}</div><div className="ai-req">{r.req}</div></div>
            <span className={'pf-risk '+(r.risk==='scoped'?'allow':'gated')}>{r.risk}</span>
            <div className="ai-acts"><button className="mq-btn primary" onClick={()=>resolve(i)}>approve</button><button className="mq-btn" onClick={()=>resolve(i)}>reject</button></div>
          </div>
        ))}
      </div>
      <div className="obs-grid" style={{marginTop:18}}>
        <div>
          <SubH>AGENT-TO-AGENT (A2A)</SubH>
          {N.a2a.map((a,i)=>(
            <div className="io-row" key={i}>
              <span className={'sdot '+(a.status==='connected'?'active':'idle')}></span>
              <div><div className="ion">{a.peer}</div><div className="iod">{a.protocol}</div></div>
              <div className="io-agents">{a.agents.map(x=><Gl key={x} id={x} size={12}/>)}</div>
              <span className={'io-status '+a.status}>{a.status}</span>
            </div>
          ))}
          <SubH style={{marginTop:16}}>MCP SERVERS</SubH>
          {N.mcp.map((m,i)=>(
            <div className="io-row" key={i}>
              <span className={'sdot '+(m.status==='up'?'active':m.status==='degraded'?'busy':'err')}></span>
              <div><div className="ion">{m.server}</div><div className="iod">{m.scope}</div></div>
              <span className="io-tools">{m.tools} tools</span>
              <span className={'io-status '+(m.status==='up'?'connected':'degraded')}>{m.status}</span>
            </div>
          ))}
        </div>
        <div>
          <SubH>WIDGETS</SubH>
          {N.widgets.map((w,i)=>(
            <div className="cap-row" key={i}><div><div className="cn">{w.name}</div><div className="cd">{w.surface}</div></div>
              <span className={'cap-tag '+(w.enabled?'allow':'scoped')}>{w.enabled?'LIVE':'OFF'}</span></div>
          ))}
          <SubH style={{marginTop:16}}>WEBHOOKS</SubH>
          {N.webhooks.map((h,i)=>(
            <div className="io-row" key={i}>
              <span className={'io-dir '+h.dir}>{h.dir==='in'?'IN':'OUT'}</span>
              <div><div className="ion" style={{fontFamily:'var(--font-mono)',fontSize:11}}>{h.event}</div><div className="iod">{h.url}</div></div>
              <span className={'io-status '+(h.status==='active'?'connected':'degraded')}>{h.status}</span>
            </div>
          ))}
        </div>
      </div>
    </ModePanel>
  );
}

Object.assign(window, { AutonomyMode, BuildMode, ObserveMode, InteropMode });
