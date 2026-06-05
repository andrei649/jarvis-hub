'use strict';
/* HUD v2 · APP ROOT */
const { useState:uS, useEffect:uE, useRef:uR, useCallback:uC } = React;
const {
  TopBar, Ticker, Rail, Tabs, RosterColumn, ContextColumn,
  NetworkBrain, Conversation, CognitionStream, InputBar, buildTrace,
  AgentsMode, Dossier, TrustMode, MemoryMode, Palette, Ambient,
  AutonomyMode, BuildMode, ObserveMode, InteropMode,
  ChatMode, CommsMode, AdminMode,
  FinanceMode, HealthMode, KnowledgeMode, FamilyMode,
  useClock, fmtTimeShort, Icon, ICONS, Glyph,
  TweaksPanel, TweakSection, TweakRadio, TweakColor, TweakSelect, TweakToggle,
} = window;

function App(){
  // tweakable settings
  const [look,setLook]=uS('obsidian');
  const [accent,setAccent]=uS('cyan');
  const [density,setDensity]=uS('normal');
  const [motion,setMotion]=uS('lively');
  const [ia,setIa]=uS('rail');
  const [lang,setLang]=uS('en');
  const [scanline,setScanline]=uS('on');
  const [dotgrid,setDotgrid]=uS('off');

  const [mode,setMode]=uS('cockpit');
  const [agents,setAgents]=uS(window.V2.AGENTS);
  const [activeId,setActiveId]=uS('jarvis');
  const [focusId,setFocusId]=uS(null);
  const [messages,setMessages]=uS(window.V2.SEED_MESSAGES);
  const [thinking,setThinking]=uS(null);
  const [trace,setTrace]=uS(null);
  const [centerTab,setCenterTab]=uS('conversation');
  const [mic,setMic]=uS(false);
  const [palette,setPalette]=uS(false);
  const [ambient,setAmbient]=uS(false);
  const [dossier,setDossier]=uS(null);
  const [provModal,setProvModal]=uS(null);
  const [decisions,setDecisions]=uS(()=>window.V2.DECISIONS.map((d,i)=>({...d,_id:'d'+i})));

  const clock = useClock();
  const t = window.V2.I18N[lang];
  const localPct = 87;

  // hotkeys
  uE(()=>{
    function onKey(e){
      if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); setPalette(p=>!p); return; }
      if(ambient) return;
      const tag=(e.target.tagName||'').toLowerCase();
      if(tag==='input'||tag==='textarea') return;
      if(e.key==='1')setMode('cockpit');
      else if(e.key==='2')setMode('agents');
      else if(e.key==='3')setMode('trust');
      else if(e.key==='4')setMode('memory');
      else if(e.key==='5')setMode('autonomy');
      else if(e.key==='6')setMode('build');
      else if(e.key==='7')setMode('observe');
      else if(e.key==='8')setMode('interop');
      else if(e.key==='9')setMode('chat');
      else if(e.key==='0')setMode('comms');
      else if(e.key.toLowerCase()==='a')setAmbient(true);
    }
    window.addEventListener('keydown',onKey);
    return ()=>window.removeEventListener('keydown',onKey);
  },[ambient]);

  // submit → cognition flow
  const timers = uR([]);
  const submit = uC((text)=>{
    timers.current.forEach(clearTimeout); timers.current=[];
    setMessages(m=>[...m,{role:'user',text,ts:fmtTimeShort(new Date())}]);
    const tr = buildTrace(text);
    setTrace({stages:tr.stages.map(s=>({...s,state:''}))});
    setCenterTab('cognition');
    // light up selected agents
    setAgents(prev=>prev.map(a=> tr.selected.includes(a.id)?{...a,status:'busy'}:a));
    setThinking({label:t.think+' · classify', route:null});
    const seq=[
      [250, ()=>{ setTrace(p=>mark(p,0,'on')); }],
      [700, ()=>{ setTrace(p=>mark(p,0,'done',1,'on')); setThinking({label:t.think+' · route', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [1400,()=>{ setTrace(p=>mark(p,1,'done',2,'on')); setThinking({label:t.think+' · gather', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [2300,()=>{ setTrace(p=>mark(p,2,'done',3,'on')); setThinking({label:t.think+' · synthesize', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [3300,()=>{
        setTrace(p=>mark(p,3,'done'));
        setThinking(null);
        setMessages(m=>[...m,{role:'agent',who:'jarvis',role_label:'Prime Orchestrator',ts:fmtTimeShort(new Date()),
          text: replyFor(text, tr),
          prov:{ agents:tr.selected, plugins:pluginsFor(text), local:true, conf:+tr.conf.toFixed(2) }}]);
        setAgents(window.V2.AGENTS);
      }],
    ];
    seq.forEach(([ms,fn])=>timers.current.push(setTimeout(fn,ms)));
  },[t]);

  uE(()=>()=>timers.current.forEach(clearTimeout),[]);

  const dismissDecision = id=>setDecisions(ds=>ds.filter(d=>d._id!==id));

  const rootAttrs = {
    className:'hud-root',
    'data-look':look,'data-accent':accent,'data-density':density,
    'data-motion':motion,'data-scanline':scanline,'data-dotgrid':dotgrid,
  };

  return (
    <div {...rootAttrs}>
      <div className="tex-layer tex-glow"></div>
      <div className="tex-layer tex-dotgrid"></div>
      <div className="tex-layer tex-scan"></div>
      <div className="tex-scanbar"></div>

      <div className="shell">
        <TopBar clock={clock} lang={lang} setLang={setLang} accent={accent} agents={agents} localPct={localPct}
          onPalette={()=>setPalette(true)} onAmbient={()=>setAmbient(true)} t={t}/>
        <Ticker items={window.V2.TICKER} t={t} hidden={mode==='chat'}/>

        <div className="main" data-ia={ia}>
          {ia==='rail' && <Rail mode={mode} setMode={setMode} t={t}/>}
          <div style={{minHeight:0,display:'flex',flexDirection:'column',gap:'var(--gap)'}}>
            {ia==='tabs' && <Tabs mode={mode} setMode={setMode} t={t}/>}

            {mode==='cockpit' && (
              <div className="workzone cockpit" style={{flex:1,minHeight:0}}>
                <RosterColumn agents={agents} activeId={activeId} onSelect={id=>{setActiveId(id);setDossier(id);}} t={t}/>
                <div className="col" style={{minHeight:0}}>
                  <div className="panel" style={{flex:'1.3 1 0',minHeight:0}}>
                    <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
                    <div className="panel-head"><Icon d={ICONS.brain} size={14}/><span className="ttl">{t.network}</span><span className="st">focus mode</span></div>
                    <NetworkBrain agents={agents} activeId={activeId} onSelect={id=>setActiveId(id)}
                      focusId={focusId} setFocusId={setFocusId} motion={motion} t={t}/>
                  </div>
                  <div className="panel" style={{flex:'1 1 0',minHeight:0}}>
                    <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
                    <div className="center-tabs">
                      <button className={'center-tab'+(centerTab==='conversation'?' active':'')} onClick={()=>setCenterTab('conversation')}>{t.conversation}{thinking&&<span className="pip"></span>}</button>
                      <button className={'center-tab'+(centerTab==='cognition'?' active':'')} onClick={()=>setCenterTab('cognition')}>{t.cognition}{trace&&!thinking&&<span className="pip"></span>}</button>
                    </div>
                    {centerTab==='conversation'
                      ? <Conversation messages={messages} thinking={thinking} onProv={setProvModal} t={t}/>
                      : <CognitionStream trace={trace} t={t}/>}
                    <InputBar onSubmit={submit} mic={mic} setMic={setMic} t={t}/>
                  </div>
                </div>
                <ContextColumn decisions={decisions} onDecision={dismissDecision} t={t}/>
              </div>
            )}

            {mode==='agents' && (
              <div className="workzone wide" style={{flex:1,minHeight:0}}>
                <AgentsMode agents={agents} onOpen={id=>{setActiveId(id);setDossier(id);}} t={t}/>
                <ContextColumn decisions={decisions} onDecision={dismissDecision} t={t}/>
              </div>
            )}

            {mode==='trust' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><TrustMode t={t}/></div>
            )}

            {mode==='memory' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><MemoryMode t={t}/></div>
            )}

            {mode==='autonomy' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><AutonomyMode t={t}/></div>
            )}
            {mode==='build' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><BuildMode t={t}/></div>
            )}
            {mode==='observe' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><ObserveMode t={t}/></div>
            )}
            {mode==='interop' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><InteropMode t={t}/></div>
            )}

            {mode==='chat' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}>
                <ChatMode messages={messages} thinking={thinking} onSubmit={submit} onProv={setProvModal} mic={mic} setMic={setMic} t={t}/>
              </div>
            )}
            {mode==='comms' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><CommsMode t={t}/></div>
            )}
            {mode==='admin' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><AdminMode t={t}/></div>
            )}

            {mode==='finance' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><FinanceMode t={t}/></div>
            )}
            {mode==='health' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><HealthMode t={t}/></div>
            )}
            {mode==='knowledge' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><KnowledgeMode t={t}/></div>
            )}
            {mode==='family' && (
              <div className="workzone full" style={{flex:1,minHeight:0}}><FamilyMode t={t}/></div>
            )}
          </div>
        </div>
      </div>

      {dossier && <Dossier id={dossier} onClose={()=>setDossier(null)} onOpen={setDossier}/>}
      {provModal && <ProvModal prov={provModal} onClose={()=>setProvModal(null)}/>}
      <Palette open={palette} onClose={()=>setPalette(false)} onMode={setMode}
        setAccent={setAccent} setLang={setLang} onAmbient={()=>{setPalette(false);setAmbient(true);}} t={t}/>
      {ambient && <Ambient onExit={()=>setAmbient(false)} clock={clock} lang={lang} agents={agents} decisions={decisions} motion={motion} t={t}/>}

      <TweaksPanel title="Tweaks">
        <TweakSection label="Aesthetic"/>
        <TweakRadio label="Look" value={look} options={['obsidian','graphite']} onChange={setLook}/>
        <TweakColor label="Accent" value={accent==='cyan'?'#2bb8f0':accent==='amber'?'#ffb23f':accent==='green'?'#41f59b':'#a78bfa'}
          options={['#2bb8f0','#ffb23f','#41f59b','#a78bfa']}
          onChange={hex=>setAccent({'#2bb8f0':'cyan','#ffb23f':'amber','#41f59b':'green','#a78bfa':'violet'}[hex]||'cyan')}/>
        <TweakRadio label="Density" value={density} options={['compact','normal','comfy']} onChange={setDensity}/>

        <TweakSection label="Information architecture"/>
        <TweakRadio label="Navigation" value={ia} options={['rail','tabs']} onChange={setIa}/>
        <TweakSelect label="Active mode" value={mode}
          options={['cockpit','agents','trust','memory']} onChange={setMode}/>

        <TweakSection label="Motion & texture"/>
        <TweakRadio label="Motion" value={motion} options={['calm','lively']} onChange={setMotion}/>
        <TweakToggle label="Scanline" value={scanline==='on'} onChange={v=>setScanline(v?'on':'off')}/>
        <TweakToggle label="Dot grid" value={dotgrid==='on'} onChange={v=>setDotgrid(v?'on':'off')}/>

        <TweakSection label="Language"/>
        <TweakRadio label="Locale" value={lang} options={['en','ro']} onChange={setLang}/>
      </TweaksPanel>
    </div>
  );
}

function mark(trace, i, state, j, jstate){
  if(!trace) return trace;
  const stages=trace.stages.map((s,k)=> k===i?{...s,state}: (j!==undefined&&k===j)?{...s,state:jstate}:s);
  return {...trace,stages};
}
function pluginsFor(text){
  const low=text.toLowerCase(); const p=[];
  if(/calendar|meeting|schedule/.test(low))p.push('google-calendar');
  if(/email|mail|inbox/.test(low))p.push('gmail');
  if(/weather/.test(low))p.push('weather');
  if(/music|playlist/.test(low))p.push('spotify');
  if(p.length===0)p.push('google-calendar','gmail');
  return p;
}
function replyFor(text, tr){
  const a=tr.selected[0];
  const map={
    pepper:'Pepper has it — your calendar is reconciled and the **14:00 Raiffeisen review** is protected with prep at 13:15.',
    stark:'Stark pulled the numbers — **Digitaholic MRR is +6.2% WoW**; I flagged the missing churn-cohort slide for the review.',
    vision:'Vision is on it — indexing sources now; I\'ll have a cited brief in your queue within the hour.',
    veronica:'Veronica drafted it — held for your review since Ultron flagged a **client name** as sensitive.',
    gecko:'Gecko\'s watching the markets — EUR/RON steady at 4.97; idle cash is **€4.2k over buffer**, sweep available.',
    hercules:'Hercules logged it — your sleep was 7h12m; tonight\'s plan is a light mobility session.',
    frigga:'Frigga keeps that local — noted privately, nothing left the device.',
    friday:'Friday compiled your brief — **6 items ranked**, weather clear, good day to cycle in.',
    jerome:'Jerome cued the soundtrack — focus playlist matched to your morning.',
    jarvis:'Understood. I\'ll handle that directly and keep everything on-device.',
  };
  return map[a]||map.jarvis;
}

function ProvModal({ prov, onClose }){
  return (
    <div className="pal-scrim" onClick={onClose} style={{alignItems:'center',paddingTop:0}}>
      <div className="pal" onClick={e=>e.stopPropagation()} style={{width:'min(440px,92vw)'}}>
        <div className="pal-input" style={{borderBottom:'1px solid var(--panel-line)'}}><span className="pc"><Icon d={ICONS.shield} size={16}/></span><span style={{fontSize:14,letterSpacing:'.04em'}}>PROVENANCE</span><span style={{marginLeft:'auto',fontFamily:'var(--font-mono)',fontSize:11,color:'var(--green)'}}>conf {prov.conf}</span></div>
        <div style={{padding:18}}>
          <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.14em',color:'var(--ink-3)',marginBottom:8}}>AGENTS CONSULTED</div>
          <div className="dep-links" style={{marginBottom:16}}>{prov.agents.map(a=><span key={a} className="dep-link" style={{cursor:'default'}}><Glyph id={a} size={12}/>{a}</span>)}</div>
          <div style={{fontFamily:'var(--font-mono)',fontSize:9.5,letterSpacing:'.14em',color:'var(--ink-3)',marginBottom:8}}>PLUGIN READS</div>
          <div className="dep-links" style={{marginBottom:16}}>{prov.plugins.map(p=><span key={p} className="dep-link" style={{cursor:'default'}}>{p}</span>)}</div>
          <div className="verified-row"><Icon d={ICONS.shield} size={13}/> {prov.local?'100% on-device · no cloud egress':'cloud-assisted'} · sealed in audit chain</div>
        </div>
      </div>
    </div>
  );
}

window.HUDApp = App;
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
