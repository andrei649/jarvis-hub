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
                <span><b>{m.prov.agents.length}</b> agents · <b>{m.prov.plugins.length}</b> plugins · {m.prov.local?'local':'cloud'} · conf <b>{m.prov.conf}</b></span>
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

/* input bar */
function InputBar({ onSubmit, mic, setMic, t }) {
  const [val,setVal]=useState('');
  const submit=()=>{ if(!val.trim())return; onSubmit(val.trim()); setVal(''); };
  return (
    <div className="inputbar">
      <span className="pre">▸</span>
      <span className="chan">{t.channel}</span>
      <div className="field">
        <input value={val} onChange={e=>setVal(e.target.value)} placeholder={t.placeholder}
          onKeyDown={e=>{ if(e.key==='Enter') submit(); }}/>
        <button className={'mic'+(mic?' on':'')} onClick={()=>setMic(m=>!m)} title="voice"><Icon d={ICONS.mic} size={15}/></button>
      </div>
      <button className="transmit" onClick={submit}><Icon d={ICONS.send} size={13}/>{t.transmit}</button>
    </div>
  );
}

export { Conversation, CognitionStream, buildTrace, InputBar, renderRich };
