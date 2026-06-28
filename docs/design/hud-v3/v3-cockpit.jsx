'use strict';
/* HUD v2 · COCKPIT — conversation + cognition trace + input */
const { useState, useEffect, useRef, useMemo } = React;
const { Icon, ICONS, Glyph } = window;

function Conversation({ messages, thinking, onProv, onFeedback, t }) {
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
            <div className="bubble">{renderRich(m.text)}{m.streaming && <span className="type-cursor" aria-hidden="true">▋</span>}</div>
            {m.prov && (
              <div className="prov-chip" onClick={()=>onProv(m.prov)}>
                <Icon d={ICONS.shield} size={12}/>
                <span><b>{m.prov.agents.length}</b> agents · <b>{m.prov.plugins.length}</b> plugins · {m.prov.local?'local':'cloud'} · conf <b>{m.prov.conf}</b></span>
              </div>
            )}
            {m.prov && !m.streaming && onFeedback && (
              <div className="msg-fb">
                <button className={'fb-btn'+(m.fb==='up'?' on':'')} onClick={()=>onFeedback(i,'up')} aria-label="helpful" title="helpful"><Icon d={ICONS.thumbUp} size={13}/></button>
                <button className={'fb-btn'+(m.fb==='down'?' down':'')} onClick={()=>onFeedback(i,'down')} aria-label="not helpful" title="not helpful"><Icon d={ICONS.thumbDown} size={13}/></button>
                {m.fb && <span className="fb-thanks">thanks — logged</span>}
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
  const SC = window.V2.COGNITION_SCORING;
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
  const [voiceOpen,setVoiceOpen]=useState(false);
  const submit=()=>{ if(!val.trim())return; onSubmit(val.trim()); setVal(''); };
  return (
    <div className="inputbar">
      <span className="pre">▸</span>
      <span className="chan">{t.channel}</span>
      <div className="field">
        <button className="img-attach" onClick={()=>onSubmit('[image attached] describe what you see in this screenshot')} title="attach image → describe (VLM)" aria-label="attach image"><Icon d={ICONS.image} size={14}/></button>
        <input value={val} onChange={e=>setVal(e.target.value)} placeholder={t.placeholder}
          onKeyDown={e=>{ if(e.key==='Enter') submit(); }}/>
        <button className={'mic'+(mic?' on':'')} onClick={()=>setMic(m=>!m)} title="mic mute/unmute" aria-label="microphone"><Icon d={ICONS.mic} size={15}/></button>
        <button className="mic-cfg" onClick={()=>setVoiceOpen(o=>!o)} title="voice settings" aria-label="voice settings"><Icon d={ICONS.mic2} size={13}/></button>
        {voiceOpen && (
          <div className="voice-pop" role="dialog" aria-label="Voice settings">
            <div className="vp-h">VOICE · /api/voice/capabilities</div>
            <div className="vp-row"><span>STT engine</span><span className="vp-v">whisper-local</span></div>
            <div className="vp-row"><span>TTS voice</span><span className="vp-v">piper · ro/en</span></div>
            <label className="vp-row"><span>Push-to-talk</span><input type="checkbox" defaultChecked/></label>
            <label className="vp-row"><span>Barge-in (interrupt)</span><input type="checkbox" defaultChecked/></label>
            <label className="vp-row"><span>Hands-free auto-speak</span><input type="checkbox"/></label>
            <div className="vp-foot">mic badge reflects mute · gated honestly</div>
          </div>
        )}
      </div>
      <button className="transmit" onClick={submit}><Icon d={ICONS.send} size={13}/>{t.transmit}</button>
    </div>
  );
}

Object.assign(window, { Conversation, CognitionStream, buildTrace, InputBar, renderRich });
