/* HUD v2 · COCKPIT — conversation + cognition trace + input */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Icon, ICONS, Glyph } from './primitives';
import { V2 } from './data';
import { playTts } from './api/actions';
import { SaveArtifactButton } from './artifacts';
import { VoiceOrb } from './orb';

/* Per-message TTS replay (🔊) — POST /tts {text,lang} → audio. Honest states: while
   speaking shows ◼ (stop is best-effort via re-click), errors fall back silently to
   the icon. voice.ts owns the live mic loop; this is just on-demand playback of a
   single past reply, which the prototype was missing. */
function TtsButton({ text, lang }) {
  const [state, setState] = useState('idle'); // idle | playing | err
  const play = () => {
    if (state === 'playing' || !text) return;
    setState('playing');
    playTts(text, lang || 'en').then(() => setState('idle')).catch(() => setState('err'));
  };
  return (
    <button className="mic" onClick={play} title={state==='err'?'TTS unavailable':'replay aloud'}
      style={{ width: 22, height: 22, opacity: state==='playing'?1:.6, fontSize: 12, lineHeight: 1, color: state==='err'?'var(--amber)':undefined }}>
      {state==='playing' ? '◼' : '🔊'}
    </button>
  );
}

function Conversation({ messages, thinking, onStop, onProv, onArtifactSaved, lang, t }: any) {
  const endRef = useRef(null);
  useEffect(()=>{ if(endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; }, [messages, thinking]);
  // Explicit save-to-artifacts (never auto): only completed, non-system, non-empty
  // assistant replies get the control — while a turn streams, its (last) message is
  // still in flight — and only on surfaces that opt in by passing onArtifactSaved
  // (the cockpit does; ChatMode doesn't).
  const canSave = (m, i) => !!onArtifactSaved && !!m.text && m.who !== 'system'
    && !(thinking && i === messages.length - 1);
  /* The transcript is `overflow-y:auto` (styles.css `.convo`), so it is a scrollable
     region — and a scrollable region a keyboard user cannot enter is a WCAG 2.1.1
     failure. It has no focusable children of its own: the ⧉/🔊 controls live on AGENT
     bubbles only, so a run of user turns with no reply (an unreachable model, an
     aborted turn) leaves the region overflowing with nothing to tab to. axe reports
     `serious · scrollable-region-focusable` in exactly that state.

     Two facts that are easy to conflate, so stated apart. (1) Chromium makes overflow
     scrollers focusable on its own, so an unfixed `.convo` IS tab-reachable there —
     measured, reached at the 39th Tab with `tabIndex === -1`, and at the 28th with the
     fix. That is why a tab-walk assertion proves nothing and e2e/a11y.spec.ts asserts
     the axe rule and `tabIndex` instead. (2) It does NOT mask the axe rule: Chromium's
     axe reports the violation on an overflowing unfixed transcript just as webkit does.
     Chromium was 0/3 in the nightly for the other reason — the existing scans run
     against an EMPTY transcript, where the rule cannot apply at all.

     `role="log"` is the ARIA APG role for a chat transcript and is what gives the
     focused region an accessible name (`aria-label` alone would sit on a `generic`
     element, which prohibits naming). It also makes the region `aria-live="polite"` by
     default. Known trade, only half of it measured: the `.thinking` block below is
     inside the region and its label churns several times per turn, so it carries an
     explicit `aria-live="off"`. Not addressed, and not measured with a real screen
     reader: the `GET /memory` rehydration (app.tsx) injects a whole restored transcript
     into an already-mounted live region, which an AT may announce in bulk. Scoping the
     live region to a messages-only wrapper is the fix if that turns out to matter — it
     is a DOM restructure inside a flex column, so it belongs in its own change. */
  return (
    <div className="convo" ref={endRef} tabIndex={0} role="log"
         aria-label={(t && t.convoRegion) || 'Conversation transcript'}>
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
              {m.text && m.who!=='system' && (
                <span style={{marginLeft:'auto',display:'inline-flex',alignItems:'center',gap:5}}>
                  {canSave(m, i) && <SaveArtifactButton message={m} onSaved={onArtifactSaved} lang={lang} />}
                  <TtsButton text={m.text} lang={lang} />
                </span>
              )}
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
        /* aria-live="off" overrides the `role="log"` region above: the label cycles
           classify -> route -> gather -> synthesize within a single turn, and a polite
           live region would announce every step. The finished reply is the thing worth
           announcing, and it arrives as a `.msg.agent` addition. */
        <div className="thinking" aria-live="off">
          <div className="tl"><span className="ar">▸</span> {thinking.label}
            {thinking.route && <span className="route-pill">→ {thinking.route.join(' · ')}</span>}
            <span className="dots"><span></span><span></span><span></span></span>
            {onStop && (
              <button className="route-pill stop-gen" style={{ marginLeft: 'auto', cursor: 'pointer' }}
                      onClick={onStop} title="Stop generating" aria-label="Stop generating">■ stop</button>
            )}
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
  const agentScore: Record<string, number> = {};
  hits.forEach(h => h.agents.forEach(a => { agentScore[a]=Math.max(agentScore[a]||0, h.weight); }));
  let scored = Object.entries(agentScore).map(([id,v])=>({id,v} as {id:string; v:number; win?:boolean})).sort((a,b)=>b.v-a.v);
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
      { name:'SYNTHESIZE', dur:'890ms', body:`Nerva composed the reply locally · 234 tokens · 100% on-device, no cloud egress.` },
    ],
  };
}

/* segmented toggle for the voice settings popover */
function Seg({ cur, opts, on }) {
  return (
    <span style={{display:'inline-flex',gap:3}}>
      {opts.map(o=>(
        <button key={o.v} onClick={()=>on(o.v)}
          style={{padding:'3px 8px',borderRadius:6,border:'1px solid '+(cur===o.v?'var(--accent)':'var(--panel-line)'),background:cur===o.v?'var(--accent)':'transparent',color:cur===o.v?'#021a1f':'var(--ink-2)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.04em',cursor:'pointer'}}>{o.l}</button>
      ))}
    </span>
  );
}

/* input bar — text + voice (mic toggles the useVoice loop; ⚙ opens voice settings) */
function InputBar({ onSubmit, mic, setMic, voice, cfg, onCfg, micMuted, motion, t }: { onSubmit?: any; mic?: any; setMic?: any; voice?: any; cfg?: any; onCfg?: any; micMuted?: any; motion?: any; t?: any }) {
  const [val,setVal]=useState('');
  const [cfgOpen,setCfgOpen]=useState(false);
  const submit=()=>{ if(!val.trim())return; onSubmit(val.trim()); setVal(''); };
  const showPill = voice && (voice.active || voice.error);
  const label = voice && voice.error ? voice.error
    : voice && voice.status==='listening' ? 'listening…'
    : voice && voice.status==='transcribing' ? 'transcribing…'
    : voice && voice.status==='speaking' ? 'speaking…' : 'voice on';
  const row = (lbl,node) => (
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,padding:'4px 0'}}>
      <span style={{color:'var(--ink-3)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.1em'}}>{lbl}</span>{node}
    </div>
  );
  return (
    <div style={{position:'relative'}}>
      {showPill && (
        <div style={{display:'flex',alignItems:'center',gap:8,padding:'5px 10px',marginBottom:6,borderRadius:8,fontFamily:'var(--font-mono)',fontSize:11,letterSpacing:'.04em',background:'rgba(0,0,0,.18)',border:'1px solid var(--panel-line)',color:voice.error?'var(--amber)':'var(--accent-light)'}}>
          {!voice.error && <VoiceOrb status={voice.status} level={voice.level||0} motion={motion} density="compact" showLabel={false} className="vorb-inline" />}
          <span style={{flex:'none'}}>{voice.error ? '⚠ ' : ''}{label}</span>
          {!voice.error && voice.status==='listening' && (
            <span style={{flex:1,height:4,borderRadius:4,background:'var(--panel-line)',overflow:'hidden'}}>
              <span style={{display:'block',height:'100%',width:Math.min(100,Math.round((voice.level||0)*400))+'%',background:'var(--green)',transition:'width .08s'}}/>
            </span>
          )}
          {!voice.error && voice.transcript && <span style={{color:'var(--ink-2)',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',maxWidth:220}}>“{voice.transcript}”</span>}
        </div>
      )}
      {cfgOpen && cfg && onCfg && (
        <div style={{position:'absolute',bottom:'100%',right:0,marginBottom:8,zIndex:30,minWidth:262,padding:'10px 12px',borderRadius:10,background:'rgba(10,18,24,.98)',border:'1px solid var(--panel-line)',boxShadow:'0 10px 30px rgba(0,0,0,.45)'}}>
          <div style={{color:'var(--accent-light)',fontFamily:'var(--font-mono)',fontSize:10,letterSpacing:'.14em',marginBottom:6}}>VOICE</div>
          {row('MODE', <Seg cur={cfg.mode} opts={[{v:'hands-free',l:'HANDS-FREE'},{v:'ptt',l:'PUSH-TO-TALK'}]} on={(v)=>onCfg({mode:v})} />)}
          {row('SPEAK', <Seg cur={cfg.tts} opts={[{v:'server',l:'SERVER'},{v:'browser',l:'LOCAL'},{v:'off',l:'OFF'}]} on={(v)=>onCfg({tts:v})} />)}
          {row('LANG', <Seg cur={cfg.lang} opts={[{v:'auto',l:'AUTO'},{v:'ro',l:'RO'},{v:'en',l:'EN'}]} on={(v)=>onCfg({lang:v})} />)}
          {row('BARGE-IN', <Seg cur={cfg.barge||'off'} opts={[{v:'off',l:'OFF'},{v:'on',l:'ON'}]} on={(v)=>onCfg({barge:v})} />)}
          {cfg.barge==='on' && <div style={{marginTop:4,color:'var(--ink-3)',fontSize:9,fontFamily:'var(--font-mono)'}}>experimental — talk over the reply to interrupt; needs echo cancellation</div>}
          {voice && voice.caps && voice.caps.stt===false && <div style={{marginTop:6,color:'var(--amber)',fontSize:10,fontFamily:'var(--font-mono)'}}>local STT not installed — pip install faster-whisper</div>}
        </div>
      )}
      <div className="inputbar">
        <span className="pre">▸</span>
        <span className="chan">{t.channel}</span>
        <div className="field">
          <input value={val} onChange={e=>setVal(e.target.value)} placeholder={voice && voice.active ? (cfg && cfg.mode==='ptt' ? 'listening — speak now' : 'listening — just speak (or type)') : t.placeholder}
            onKeyDown={e=>{ if(e.key==='Enter') submit(); }}/>
          <button className={'mic'+(mic?' on':'')} onClick={()=>setMic && setMic()}
            title={micMuted ? 'mic muted — unmute NERVA' : (voice && voice.supported===false ? 'voice not supported in this browser' : (cfg && cfg.mode==='ptt' ? 'push-to-talk' : 'hands-free voice'))}
            style={micMuted?{opacity:.4}:undefined}><Icon d={ICONS.mic} size={15}/></button>
          {cfg && onCfg && <button className="mic" onClick={()=>setCfgOpen(o=>!o)} title="voice settings" style={{opacity:cfgOpen?1:.6,fontSize:13,lineHeight:1}}>⚙</button>}
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
      { name: 'ROUTE', dur: (timing.route != null ? timing.route : 0) + 'ms', kind: 'score', scores, body: `Routing to ${sel.map(s => String(s).toUpperCase()).join(' + ')} \u00b7 source ${dec.source || '\u2014'}.`, esc: conf < 0.6 ? 'Low confidence \u2014 Nerva handling directly.' : null },
      { name: 'GATHER', dur: '\u2014', body: gatherBody(cog) },
      { name: 'SYNTHESIZE', dur: (timing.total != null ? timing.total : 0) + 'ms', body: 'Reply composed on-device \u00b7 streamed token-by-token.' },
    ],
  };
}

export { Conversation, CognitionStream, buildTrace, traceFromCognition, InputBar, renderRich };
