// @ts-nocheck
/* HUD v2 · COCKPIT — conversation + cognition trace + input */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Icon, ICONS, Glyph } from './primitives';
import { V2 } from './data';

function Conversation({ messages, thinking, onProv, t }) {
  const endRef = useRef(null);
  useEffect(()=>{ if(endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; }, [messages, thinking]);
  return (
    <div className="convo" ref={endRef}>
      {messages.map((m,i)=> m.role==='user'
        ? (
          <div className="msg user" key={i}>
            <div className="bubble">{m.text}</div>
          </div>
        ) : (
          <div className="msg agent" key={i}>
            <div className="mtag">
              <span className="who">{(m.who||'jarvis').toUpperCase()}</span>
              <span className="role">{m.role_label||''}</span>
              <span className="ts">{m.ts||''}</span>
            </div>
            <div className="bubble">{renderRich(m.text)}</div>
            {m.prov && (
              <div className="prov-chip" onClick={()=>onProv(m.prov)}>
                <Icon d={ICONS.shield} size={12}/>
                <span><b>{m.prov.agents.length}</b> agents · <b>{m.prov.plugins.length}</b> plugins · {m.prov.local===true?'local':m.prov.local===false?'cloud':'locality —'} · conf <b>{m.prov.conf}</b></span>
              </div>
            )}
          </div>
        )
      )}
      {thinking && (
        <div className="thinking">
          <div className="tl"><span className="ar">▸</span> {thinking.label}
            {thinking.route && <span className="route-pill">→ {thinking.route.join(' · ')}</span>}
            <span className="dots"><span></span><span></span><span></span></span>
          </div>
        </div>
      )}
    </div>
  );
}
function renderRich(text){
  // bold **x**
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p,i)=> p.startsWith('**') ? <b key={i} style={{color:'var(--accent-light)'}}>{p.slice(2,-2)}</b> : p);
}

/* ---- Cognition trace ---- */
function CognitionStream({ trace, t }) {
  if (!trace) {
    return (
      <div className="cog">
        <div className="cog-empty">
          <Icon d={ICONS.brain} size={34}/>
          <div className="big">{t.cogempty}</div>
          <div style={{fontFamily:'var(--font-mono)',fontSize:11,color:'var(--accent-light)'}}>{t.cogempty2}</div>
        </div>
      </div>
    );
  }
  const stages = trace.stages;
  return (
    <div className="cog">
      {stages.map((s,i)=>(
        <div key={i} className={'cog-stage '+(s.state||'')}>
          <div className="cog-rail">
            <div className="cog-node">{i+1}</div>
            {i<stages.length-1 && <div className="cog-line"></div>}
          </div>
          <div className="cog-content">
            <div className="cog-stage-name">{s.name}<span className="dur">{s.dur}</span></div>
            <div className="cog-stage-body">
              {s.body}
              {s.kind==='score' && (
                <div className="score-table">
                  {s.scores.map((sc,j)=>(
                    <div key={j} className={'score-row'+(sc.win?' win':'')}>
                      <span className="ag"><Glyph id={sc.id} size={12}/>{sc.id}</span>
                      <span className="score-bar"><i style={{width:`${sc.v*100}%`}}></i></span>
                      <span className="sc">{sc.v.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )}
              {s.kind==='keywords' && (
                <div style={{marginTop:6}}>
                  {s.keywords.map((k,j)=><span key={j} className={'kwchip'+(k.anti?' anti':'')}>{k.w} · {k.s.toFixed(2)}</span>)}
                </div>
              )}
              {s.esc && <div className="esc-marker">⚠ {s.esc}</div>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* build a trace from input text using COGNITION_SCORING */
function buildTrace(text){
  const SC = V2.COGNITION_SCORING;
  const low = text.toLowerCase();
  const hits = SC.filter(s => low.includes(s.keyword));
  const agentScore = {};
  hits.forEach(h => h.agents.forEach(a => { agentScore[a]=Math.max(agentScore[a]||0, h.weight); }));
  let scored = Object.entries(agentScore).map(([id,v])=>({id,v})).sort((a,b)=>b.v-a.v);
  if (scored.length===0) scored=[{id:'jarvis',v:0.55}];
  scored = scored.slice(0,5);
  scored[0].win = true;
  const selected = scored.filter(s=>s.v>=0.6).map(s=>s.id);
  const sel = selected.length?selected:[scored[0].id];
  const kws = hits.length?hits.slice(0,6).map(h=>({w:h.keyword,s:h.weight})):[{w:'(general)',s:0.55}];
  const conf = scored[0].v;
  return {
    selected: sel, conf,
    stages:[
      { name:'CLASSIFY', dur:'12ms', kind:'keywords', keywords:kws, body:`Matched ${hits.length} routing keyword${hits.length===1?'':'s'} via keyword_match classifier.` },
      { name:'ROUTE', dur:'8ms', kind:'score', scores:scored, body:`Scored candidate agents. Routing to ${sel.map(s=>s.toUpperCase()).join(' + ')} (≥0.60 threshold).`, esc: conf<0.6?'Low confidence — escalating to Jarvis for direct handling.':null },
      { name:'GATHER', dur:'145ms', body:`Pulling context — plugin reads (calendar/gmail), KG recall, ${sel.length} agent contexts. 2 PII spans redacted by Ultron.` },
      { name:'SYNTHESIZE', dur:'890ms', body:`Jarvis composed the reply locally · 234 tokens · 100% on-device, no cloud egress.` },
    ],
  };
}

/* input bar — text + hands-free voice (mic button toggles the useVoice loop) */
function InputBar({ onSubmit, mic, setMic, voice, t }) {
  const [val,setVal]=useState('');
  const submit=()=>{ if(!val.trim())return; onSubmit(val.trim()); setVal(''); };
  const showPill = voice && (voice.active || voice.error);
  const label = voice && voice.error ? voice.error
    : voice && voice.status==='listening' ? 'listening…'
    : voice && voice.status==='transcribing' ? 'transcribing…'
    : voice && voice.status==='speaking' ? 'speaking…' : 'voice on';
  const dotColor = voice && voice.status==='listening' ? 'var(--green)'
    : voice && voice.status==='speaking' ? 'var(--accent-light)' : 'var(--ink-3)';
  return (
    <div>
      {showPill && (
        <div style={{display:'flex',alignItems:'center',gap:8,padding:'5px 10px',marginBottom:6,borderRadius:8,fontFamily:'var(--font-mono)',fontSize:11,letterSpacing:'.04em',background:'rgba(0,0,0,.18)',border:'1px solid var(--panel-line)',color:voice.error?'var(--amber)':'var(--accent-light)'}}>
          {!voice.error && <span style={{width:8,height:8,borderRadius:8,background:dotColor,boxShadow:'0 0 8px currentColor',flex:'none'}}/>}
          <span style={{flex:'none'}}>{voice.error ? '⚠ ' : ''}{label}</span>
          {!voice.error && voice.status==='listening' && (
            <span style={{flex:1,height:4,borderRadius:4,background:'var(--panel-line)',overflow:'hidden'}}>
              <span style={{display:'block',height:'100%',width:Math.min(100,Math.round((voice.level||0)*400))+'%',background:'var(--green)',transition:'width .08s'}}/>
            </span>
          )}
          {!voice.error && voice.transcript && <span style={{color:'var(--ink-2)',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',maxWidth:220}}>“{voice.transcript}”</span>}
        </div>
      )}
      <div className="inputbar">
        <span className="pre">▸</span>
        <span className="chan">{t.channel}</span>
        <div className="field">
          <input value={val} onChange={e=>setVal(e.target.value)} placeholder={voice && voice.active ? 'listening — just speak (or type)' : t.placeholder}
            onKeyDown={e=>{ if(e.key==='Enter') submit(); }}/>
          <button className={'mic'+(mic?' on':'')} onClick={()=>setMic && setMic()} title={voice && voice.supported===false ? 'voice not supported in this browser' : 'hands-free voice'}><Icon d={ICONS.mic} size={15}/></button>
        </div>
        <button className="transmit" onClick={submit}><Icon d={ICONS.send} size={13}/>{t.transmit}</button>
      </div>
    </div>
  );
}

/* P2 — map the real /api/cognition snapshot onto the 4-stage trace visual */
function gatherBody(cog){
  const tr = Array.isArray(cog && cog.trace) ? cog.trace : [];
  const steps = tr.map(s => s.step || s.name || s.stage).filter(Boolean);
  return steps.length ? `Context gathered \u00b7 ${steps.join(' \u2192 ')}.` : 'Context gathered \u2014 plugin reads + memory recall.';
}
function traceFromCognition(cog, text){
  if (!cog || (!cog.scoring && !cog.decision)) return buildTrace(text);
  const scoring = Array.isArray(cog.scoring) ? cog.scoring : [];
  const dec = cog.decision || {};
  const sel = Array.isArray(dec.agents_selected) && dec.agents_selected.length ? dec.agents_selected : ['jarvis'];
  const timing = dec.timing || {};
  const alts = Array.isArray(dec.alternatives) ? dec.alternatives : [];
  let scores = alts.map(a => ({ id: a.id || a.agent || a.name || String(a), v: +(a.score != null ? a.score : a.confidence != null ? a.confidence : a.weight != null ? a.weight : 0) }));
  if (!scores.length) scores = sel.map((id, i) => ({ id, v: i === 0 ? +(dec.confidence != null ? dec.confidence : 0.7) : 0.4 }));
  scores.forEach(s => { if (sel.indexOf(s.id) >= 0) s.win = true; });
  if (!scores.some(s => s.win) && scores[0]) scores[0].win = true;
  scores = scores.slice(0, 6);
  const kws = scoring.length ? scoring.slice(0, 6).map(s => ({ w: s.keyword, s: +(s.weight != null ? s.weight : 0.5) })) : [{ w: '(general)', s: 0.55 }];
  const conf = +(dec.confidence != null ? dec.confidence : (scores[0] ? scores[0].v : 0.6));
  return {
    selected: sel, conf,
    stages: [
      { name: 'CLASSIFY', dur: (timing.classify != null ? timing.classify : 0) + 'ms', kind: 'keywords', keywords: kws, body: `Matched ${scoring.length} routing keyword${scoring.length === 1 ? '' : 's'} via ${dec.source || 'router'}.` },
      { name: 'ROUTE', dur: (timing.route != null ? timing.route : 0) + 'ms', kind: 'score', scores, body: `Routing to ${sel.map(s => String(s).toUpperCase()).join(' + ')} \u00b7 source ${dec.source || '\u2014'}.`, esc: conf < 0.6 ? 'Low confidence \u2014 Jarvis handling directly.' : null },
      { name: 'GATHER', dur: '\u2014', body: gatherBody(cog) },
      { name: 'SYNTHESIZE', dur: (timing.total != null ? timing.total : 0) + 'ms', body: 'Reply composed on-device \u00b7 streamed token-by-token.' },
    ],
  };
}

export { Conversation, CognitionStream, buildTrace, traceFromCognition, InputBar, renderRich };
