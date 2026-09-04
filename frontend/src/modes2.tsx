import React, { useState as uS2, useEffect as uE2 } from 'react';
import { V2, Conversation, InputBar } from './ui';
import { Icon as Ic, ICONS as IK, Glyph as Gl } from './ui';
import { installSkill, getAutonomyMode, setAutonomyMode, getNorthStar } from './api/actions';
import { getToken } from './api/client';
import { WorldIntelligencePanel } from './world-intelligence';
/* HUD v2 · MODES II — Autonomy, Build, Observe, Interop */

function ModePanel({ icon, title, status, children }){
  return (
    <div className="panel scroll" style={{flex:1}}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Ic d={IK[icon]} size={14}/><span className="ttl">{title}</span>{status&&<span className="st">{status}</span>}</div>
      <div className="panel-body">{children}</div>
    </div>
  );
}
function SubH({ children, style }: { children?: any; style?: any }){ return <div className="sub-h" style={style}>{children}</div>; }

/* ============ AUTONOMY ============ */
function AutonomyMode({ t }){
  const A = V2.AUTONOMY;
  const policies = A.policies;
  // LIVE global autonomy mode (AUTO/ASK/OFF) ↔ GET/POST /autonomy/mode. AUTO =
  // balanced; ASK = side-effects wait for approval; OFF = nothing auto-runs +
  // the proactive loop is paused. Per-agent rows below are informational.
  const [mode, setMode] = uS2(null);     // null until loaded
  const [busy, setBusy] = uS2(false);
  uE2(()=>{ let ok=true; getAutonomyMode().then(r=>{ if(ok&&r&&r.mode) setMode(String(r.mode).toLowerCase()); }).catch(()=>{}); return ()=>{ok=false;}; }, []);
  const choose = async (m)=>{
    if(busy||m===mode) return;
    const prev = mode; setMode(m); setBusy(true);
    try { const r = await setAutonomyMode(m) as { mode?: string } | null; if(r&&r.mode) setMode(String(r.mode).toLowerCase()); }
    catch { setMode(prev); }   // revert on failure (e.g. needs admin token)
    finally { setBusy(false); }
  };
  const MODES = ['auto','ask','off'];
  // "Speak brief" — read the morning brief aloud: server /tts (cloned-voice
  // chain) with the fully-local speechSynthesis fallback, mirroring the voice
  // loop's honest degradation. Never fakes playback: server down + no local
  // synth = silent no-op with the button re-enabled.
  const [speaking, setSpeaking] = uS2(false);
  const speakBrief = async () => {
    if (speaking || !A.brief.length) return;
    setSpeaking(true);
    const text = A.brief.map(b => `${b.title}. ${b.detail}`.trim()).filter(Boolean).join(' ');
    try {
      const h: Record<string, string> = { 'Content-Type': 'application/json' };
      const tk = getToken(); if (tk) h['X-User-Token'] = tk;
      const res = await fetch('/tts', { method: 'POST', headers: h, body: JSON.stringify({ text }) });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        await new Promise(done => { const a = new Audio(url); a.onended = () => done(null); a.onerror = () => done(null); a.play().catch(() => done(null)); });
        URL.revokeObjectURL(url);
      } else if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        await new Promise(done => { const u = new SpeechSynthesisUtterance(text); u.onend = () => done(null); u.onerror = () => done(null); window.speechSynthesis.speak(u); });
      }
    } catch { /* server unreachable — no fake playback */ }
    finally { setSpeaking(false); }
  };
  return (
    <ModePanel icon="autonomy" title={t.autonomy} status="observer running">
      <div className="auto-grid">
        <div>
          <SubH style={{display:'flex',alignItems:'center',gap:8}}>MORNING BRIEF · {A.brief.length} items
            <button className="pmode" style={{marginLeft:'auto'}} aria-label="speak brief" disabled={speaking||!A.brief.length}
              title="Read the brief aloud — server TTS (cloned voice), local speechSynthesis fallback" onClick={speakBrief}>
              {speaking?'SPEAKING…':'🔊 SPEAK'}</button>
          </SubH>
          {A.brief.map((b,i)=>(
            <div className="brief-row" key={i}>
              <span className="brank">{b.rank}</span>
              <div><div className="bt">{b.title}</div><div className="bd">{b.detail}</div></div>
              <span className="bag"><Gl id={b.agent.toLowerCase()} size={12}/>{b.agent}</span>
            </div>
          ))}
          <SubH style={{marginTop:16}}>OBSERVER LOG</SubH>
          {A.observer.map((o,i)=>(
            <div className="hbrow" key={i}><div className={'sev '+(o.result==='denied'?'alert':o.result==='held'?'warn':'ok')}></div>
              <div><div className="ht"><span className="ag">{o.agent}</span><span>{o.ts}</span><span style={{marginLeft:'auto'}}>{o.result}</span></div><div className="hx">{o.action}</div></div></div>
          ))}
        </div>
        <div>
          <SubH>AUTONOMY MODE · global · {mode==null?'…':mode.toUpperCase()}</SubH>
          <div className="amode-row" role="group" aria-label="autonomy mode" style={{display:'flex',gap:6,marginBottom:6}}>
            {MODES.map(m=>(
              <button key={m} className={'pmode '+m+(mode===m?' on':'')} aria-pressed={mode===m}
                disabled={busy||mode==null} onClick={()=>choose(m)}
                title={m==='auto'?'balanced — low-risk acts, risky asks':m==='ask'?'everything with a side-effect waits for approval':'nothing auto-runs; proactive loop paused'}
                style={mode===m?{}:{opacity:.7}}>{m.toUpperCase()}</button>
            ))}
          </div>
          <div className="pol-note">Global <b>AUTO / ASK / OFF</b> (live). Per-task approvals run via the Console (accept / edit / reject / defer).</div>
          <SubH style={{marginTop:14}}>PER-AGENT SCOPE · reference</SubH>
          {policies.map((p,i)=>(
            <div className="pol-row" key={i}>
              <span className="pag"><Gl id={p.agent} size={14}/>{p.agent}</span>
              <div className="pscope"><div>{p.scope}</div><div className="pbud">{p.budget} · {p.used}</div></div>
              <span className={'pmode '+p.mode} style={{opacity:.55}}>{p.mode.toUpperCase()}</span>
            </div>
          ))}
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ BUILD ============ */
function BuildMode({ t }){
  const B = V2.BUILD;
  const W = B.workflow;
  const [skills,setSkills]=uS2(B.skills);
  const [pending,setPending]=uS2(null); // index currently installing
  // INSTALL is REAL: POST /api/skills/marketplace/install {name} (admin, signed +
  // moderated, H12.12). On success we flip the row to INSTALLED; on failure (404 not
  // in registry / 403 blocked by moderation) we revert and surface an honest tag so
  // the seeded demo skill names that aren't in the live registry don't fake success.
  const [errIdx,setErrIdx]=uS2(null);
  const install = i => {
    const s = skills[i];
    if (s.installed || pending != null) return;
    setPending(i); setErrIdx(null);
    installSkill(s.name)
      .then(() => setSkills(ss=>ss.map((x,j)=>j===i?{...x,installed:true}:x)))
      .catch(() => setErrIdx(i))
      .finally(() => setPending(null));
  };
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
      <div className="build-grid">
        <div>
          <SubH>SKILLS · {skills.filter(s=>s.installed).length} installed</SubH>
          {skills.map((s,i)=>(
            <div className="skill-row" key={i}>
              <div><div className="skn">{s.name}</div><div className="skd">{s.desc}</div>
                <div className="skmeta"><span className="skby"><Gl id={s.author} size={11}/>{s.author}</span>{s.installed&&<span className="skruns">{s.runs} runs</span>}{errIdx===i&&<span className="skruns" style={{color:'var(--amber)'}}>not in registry</span>}</div></div>
              <button className={'skbtn '+(s.installed?'on':'')} disabled={s.installed||pending!=null} onClick={()=>install(i)} title={s.installed?'installed':'install via signed marketplace'}>{s.installed?'INSTALLED':pending===i?'…':'INSTALL'}</button>
            </div>
          ))}
        </div>
        <div>
          <SubH>SANDBOX · dry-run the router</SubH>
          <div className="sandbox">
            {B.sandbox.map((s,i)=>(
              <div key={i} className="sb-line"><div className="sb-in"><span className="sb-pre">›</span> {s.in}</div><div className="sb-out">{s.out}</div></div>
            ))}
            <div className="sb-line"><div className="sb-in"><span className="sb-pre" style={{animation:'blink 1.4s infinite'}}>›</span> <span style={{color:'var(--ink-2)'}}>type a call to simulate…</span></div></div>
          </div>
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ OBSERVE ============ */
/* MOONSHOT §6 north-star meter — the 1.0-gating metric, live from
   /api/metrics/north-star. Single-user honesty: null sources render as "—",
   never a fabricated 0; the interrupt counter flags when it breaches the ≤4/day
   budget. This was the missing HUD consumer — the endpoint existed, nothing
   surfaced it. */
function NorthStarMeter(){
  const [d,setD] = uS2(null);
  const [st,setSt] = uS2('loading');
  uE2(()=>{
    let alive = true;
    getNorthStar(7)
      .then(r=>{ if(alive){ setD(r||null); setSt(r ? 'live' : 'empty'); } })
      .catch(()=>{ if(alive) setSt('error'); });
    return ()=>{ alive = false; };
  },[]);
  const ns = (d && d.north_star) || {};
  const cm = (d && d.counter_metrics) || {};
  const nsh = (d && d.night_shift) || {};        // P1 — "works while you sleep"
  const pf = (d && d.proposal_funnel) || {};     // P1 — where proposals drop off
  const has = v => v !== null && v !== undefined;
  const n  = (v,suf='') => has(v) ? (v+suf) : '—';            // plain number
  const p1 = v => has(v) ? (Math.round(v)+'%') : '—';          // already 0–100
  const p100 = v => has(v) ? (Math.round(v*100)+'%') : '—';    // ratio 0–1 → %
  const budget = cm.interrupt_rate_per_day;
  const overBudget = has(budget) && budget > 4;                // MOONSHOT budget ≤4/day
  const statusLabel = st==='live' ? '7-day · live'
                     : st==='loading' ? 'loading…'
                     : st==='error' ? 'unavailable' : 'no data';
  return (
    <div style={{marginBottom:'var(--gap)'}}>
      <SubH>NORTH-STAR · weekly accepted actions / active user
        <span className="st" style={{marginLeft:8,opacity:.7}}>{statusLabel}</span></SubH>
      <div className="mem-grid">
        <div className="stat-card"><div className="sv">{n(ns.accepted_per_active_user)}</div><div className="sl">accepted / user · wk</div></div>
        <div className="stat-card"><div className="sv">{n(ns.total_accepted)}</div><div className="sl">total accepted</div></div>
        <div className="stat-card"><div className="sv">{n(ns.active_users)}</div><div className="sl">active users</div></div>
        <div className="stat-card"><div className="sv" style={overBudget?{color:'var(--red)'}:undefined}>{n(budget)}</div><div className="sl">interrupts / day {overBudget?'⚠':''}</div></div>
      </div>
      <div className="mem-grid" style={{marginTop:'var(--gap)'}}>
        <div className="stat-card"><div className="sv">{p100(cm.reject_rate)}</div><div className="sl">reject rate</div></div>
        <div className="stat-card"><div className="sv">{p1(cm.local_pct)}</div><div className="sl">% served local</div></div>
        <div className="stat-card"><div className="sv">{n(cm.p95_latency_ms,'ms')}</div><div className="sl">p95 turn latency</div></div>
        <div className="stat-card"><div className="sv">{has(ns.active_users)&&ns.active_users===0?'idle':n((d&&d.raw)?d.raw.decisions:undefined)}</div><div className="sl">decisions · window</div></div>
      </div>
      <SubH>PROACTIVE · works-while-you-sleep + proposal funnel</SubH>
      <div className="mem-grid">
        <div className="stat-card"><div className="sv">{n(nsh.done)}</div><div className="sl">done overnight</div></div>
        <div className="stat-card"><div className="sv">{p100(nsh.pct)}</div><div className="sl">night share</div></div>
        <div className="stat-card"><div className="sv">{p100(pf.surface_rate)}</div><div className="sl">surfaced / proposed</div></div>
        <div className="stat-card"><div className="sv">{p100(pf.accept_rate)}</div><div className="sl">accept rate</div></div>
      </div>
    </div>
  );
}

// A metric the backend did not supply arrives as null. Render it "—", never as a
// number: OBSERVE's seed is a complete, plausible picture (91% success, 847
// interactions, 99.97% uptime, 0 errors), and every un-hydrated field used to fall
// back to it — under a green LIVE badge. `Math.round(null*100)` is 0, so a missing
// success rate would otherwise read as a confident 0%.
function _obs(v: any, suffix = ''){ return (v === null || v === undefined) ? '—' : `${v}${suffix}`; }
function _pct(v: any){ return (v === null || v === undefined) ? '—' : `${Math.round(v * 100)}%`; }

// List-shaped sections (traces/arena/by_agent) start each live cycle empty; a
// silent endpoint renders this, never the demo corpus rows.
function ObsEmpty({ what }: { what?: string }){
  return <div style={{ fontFamily:'var(--font-mono)', fontSize:9, letterSpacing:'.08em', color:'var(--ink-3)', padding:'3px 0' }}>not connected{what ? ` · ${what}` : ''}</div>;
}

function ObserveMode({ t }){
  const O = V2.OBSERVE;
  const maxLat = O.by_agent.length ? Math.max(...O.by_agent.map(a=>a.v)) : 0;
  return (
    <ModePanel icon="observe" title={t.observe} status="world · north-star · traces · eval">
      <NorthStarMeter />
      <WorldIntelligencePanel />
      <div className="mem-grid" style={{marginBottom:'var(--gap)'}}>
        <div className="stat-card"><div className="sv">{_pct(O.quality.success_rate)}</div><div className="sl">success rate</div></div>
        <div className="stat-card"><div className="sv">{_obs(O.quality.interactions)}</div><div className="sl">interactions</div></div>
        <div className="stat-card"><div className="sv">{_obs(O.bench.p50, 's')}</div><div className="sl">latency p50</div></div>
        <div className="stat-card"><div className="sv">{_obs(O.resilience.uptime)}</div><div className="sl">uptime</div></div>
      </div>
      <div className="obs-grid">
        <div>
          <SubH>RECENT TRACES</SubH>
          {O.traces.length ? O.traces.map((tr,i)=>(
            <div className="trace-row" key={i}>
              <div className="tr-top"><span className="tr-id">{tr.id}</span><span className="tr-q">{tr.query}</span><span className={'tr-status '+tr.status}>{tr.status}</span><span className="tr-tot">{tr.total}ms</span></div>
              <div className="tr-bar">
                {tr.stages.map((s,j)=><span key={j} className={'tr-seg seg-'+s.s} style={{flex:s.ms}} title={s.s+' '+s.ms+'ms'}></span>)}
              </div>
              <div className="tr-agents">{tr.agents.map(a=><span key={a} className="topic-pill"><Gl id={a} size={10}/>{a}</span>)}</div>
            </div>
          )) : <ObsEmpty what="no traces yet"/>}
          <SubH style={{marginTop:16}}>MODEL ARENA</SubH>
          {O.arena.length ? O.arena.map((m,i)=>(
            <div className={'arena-row'+(m.pick?' pick':'')} key={i}>
              <span className="arn">{m.model}{m.pick&&<span className="arpick">DEFAULT</span>}</span>
              <span className="arw">{m.wins}% wins</span><span className="arl">{m.latency}</span><span className="arc">{m.cost}</span>
            </div>
          )) : <ObsEmpty what="no arena runs"/>}
        </div>
        <div>
          <SubH>LATENCY BY AGENT</SubH>
          {O.by_agent.length ? O.by_agent.map((a,i)=>(
            <div className="meter" key={i}>
              <div className="ml"><span style={{display:'flex',gap:6,alignItems:'center'}}><Gl id={a.id} size={11}/>{a.id}</span><span>{a.v}s</span></div>
              <div className="mt"><div className="mf" style={{width:(a.v/maxLat*100)+'%'}}></div></div>
            </div>
          )) : <ObsEmpty what="no agent stats"/>}
          <SubH style={{marginTop:16}}>RESILIENCE</SubH>
          <div className="cap-row"><div className="cn">Network guard</div><span className="cap-tag allow">{_obs(O.resilience.ssrf_blocked)}</span></div>
          <div className="cap-row"><div className="cn">Errors · 24h</div><span className="cap-tag allow">{_obs(O.resilience.errors_24h)}</span></div>
          <div className="cap-row"><div className="cn">PII redactions</div><span className="cap-tag gated">{_obs(O.resilience.redactions)}</span></div>
          <div className="cap-row"><div className="cn">Escalations</div><span className="cap-tag scoped">{_obs(O.quality.escalations)}</span></div>
        </div>
      </div>
    </ModePanel>
  );
}

/* ============ INTEROP ============ */
function InteropMode({ t }){
  const N = V2.INTEROP;
  return (
    <ModePanel icon="interop" title={t.interop} status="A2A · MCP · widgets · webhooks">
      <div className="obs-grid">
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

export { AutonomyMode, BuildMode, ObserveMode, InteropMode };
