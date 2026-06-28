'use strict';
/* HUD v3 · APP ROOT — single-page IA: rail (≤10 + Life + World + Admin drawer),
   mode-swapping context column, Decision Inbox, Missions, honest LIVE/DEMO/OFFLINE */
const { useState:uS, useEffect:uE, useRef:uR, useCallback:uC } = React;
const {
  TopBar, Ticker, Rail, ContextColumn, Palette, Ambient, AdminDrawer, HonestyBanner, HelpOverlay, OfflineState, Onboarding, CinemaMesh, MODES_V3,
  NetworkBrain, NeuralMesh, Conversation, CognitionStream, InputBar, buildTrace,
  AgentsMode, Dossier, TrustMode, MemoryMode,
  AutonomyMode, BuildMode, ObserveMode, InteropMode,
  ChatMode, CommsMode, AdminMode,
  FinanceMode, HealthMode, KnowledgeMode, FamilyMode, WorldviewMode,
  DecisionsMode, MissionsMode, MissionDrawer, TimelineMode,
  TelemetryStrip, NetPanel,
  useConnection, useResource, useMutation, useStream,
  useClock, fmtTimeShort, Icon, ICONS, Glyph, statusClass,
  TweaksPanel, TweakSection, TweakRadio, TweakColor, TweakSelect, TweakToggle,
} = window;

/* left roster column (cockpit only) */
function RosterColumn({ agents, activeId, onSelect, t }){
  const TIERS=window.V2.TIERS;
  return (
    <div className="col">
      <div className="panel scroll" style={{flex:'1 1 auto'}}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.agents} size={14}/><span className="ttl">{t.roster}</span><span className="st">{agents.filter(a=>a.status!=='idle').length} live</span></div>
        <div className="panel-body tight">
          {TIERS.map(tier=>{
            const list=agents.filter(a=>a.tier===tier.id); if(!list.length)return null;
            return <div className="tier-group" key={tier.id}>
              <div className="tier-head"><span className="tier-tag">{tier.id}</span><span className="tier-lab">{tier.label}</span></div>
              {list.map(a=>(
                <div className={'agent-row'+(activeId===a.id?' active':'')} key={a.id} onClick={()=>onSelect(a.id)}>
                  <span className="gx"><Glyph id={a.id} size={15}/></span>
                  <div><div className="nm">{a.name}</div><div className="rl">{a.role}</div></div>
                  <span className={'sdot '+statusClass(a.status)}></span>
                </div>
              ))}
            </div>;
          })}
        </div>
      </div>
      <div className="panel" style={{flex:'none'}}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Icon d={ICONS.admin} size={14}/><span className="ttl">{t.system}</span></div>
        <div className="panel-body tight">
          <Meter label="CPU" val={34}/><Meter label="RAM" val={22}/><Meter label="VRAM" val={42}/>
          <div className="sysrow"><span className="k">BACKEND</span><span className="v acc">llama.cpp · gemma-4-26b</span></div>
          <div className="sysrow"><span className="k">LATENCY p50</span><span className="v">4.2s</span></div>
        </div>
      </div>
    </div>
  );
}
const Meter = window.Meter;

const LIFE_TABS = [['finance','finance'],['health','health'],['knowledge','knowledge'],['family','family']];

function App(){
  const [look,setLook]=uS('obsidian');
  const [accent,setAccent]=uS('cyan');
  const [density,setDensity]=uS('normal');
  const [motion,setMotion]=uS('lively');
  const [lang,setLang]=uS('en');
  const [scanline,setScanline]=uS('on');
  const [dotgrid,setDotgrid]=uS('off');

  const [mode,setMode]=uS('cockpit');
  const [lifeTab,setLifeTab]=uS('finance');
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
  const [adminOpen,setAdminOpen]=uS(false);
  const [missionOpen,setMissionOpen]=uS(null);
  const [egress,setEgress]=uS('sealed');
  const [dataState,setDataState]=uS('demo');   // user intent; effective phase derived via useConnection
  const [netOpen,setNetOpen]=uS(false);
  const [killed,setKilled]=uS(false);
  const [cinema,setCinema]=uS(false);
  const [notes,setNotes]=uS(window.V2.NOTES);
  const [helpOpen,setHelpOpen]=uS(false);
  const [toast,setToast]=uS(null);
  const [firstRun,setFirstRun]=uS(()=>{ try{ return !localStorage.getItem('jarvis_v3_seen'); }catch(e){ return false; } });
  const dismissFirstRun=(mode)=>{ try{ localStorage.setItem('jarvis_v3_seen','1'); }catch(e){} if(mode==='live'||mode==='demo') setDataState(mode); setFirstRun(false); };

  const clock = useClock();
  const t = window.V2.I18N[lang];
  const localPct = 87;

  /* ── LIVE DATA LAYER ───────────────────────────────────────────────
     user intent (dataState) → effective phase via /status heartbeat.     */
  const [conn] = useConnection(dataState);
  const eff = conn.phase==='probing' ? 'live' : conn.phase;   // live | demo | offline
  const phaseRef = uR(eff); phaseRef.current = eff;
  uE(()=>{ window.JarvisClient.bindMode(()=>phaseRef.current); },[]);

  // the Decision Inbox: GET /tasks → resolve via POST /autonomy/tasks/{id}/decision
  const decRes = useResource(()=>window.JarvisAPI.listDecisions(), { mode:eff, pollMs: eff==='live'?15000:5000, deps:[eff] });
  const decisions = decRes.data || [];
  const { mutate, pending } = useMutation((id,args)=>window.JarvisAPI.resolveDecision(id, args.action, { key:args.key, patch:args.patch }));

  // in DEMO, reflect mock pushes (arrivals / resolutions) without waiting for the poll
  const softRef = uR(()=>{}); softRef.current = decRes.softRefetch;
  uE(()=>{ if(!window.JarvisMock) return; return window.JarvisMock.sub(()=>{ if(phaseRef.current==='demo') softRef.current(); }); },[]);

  // Missions — live list + event stream (progress pushes in real time via SSE/mock)
  const missionsRes = useResource(()=>window.JarvisAPI.listMissions(), { mode:eff, pollMs: eff==='live'?20000:8000, deps:[eff] });
  const missions = missionsRes.data || [];
  const missionMut = useMutation((id,args)=>window.JarvisAPI.missionAction(id, args.action));
  const softMis = uR(()=>{}); softMis.current = missionsRes.softRefetch;

  // Mesh + Trust audit — live resources (audit chain grows as decisions resolve)
  const meshRes = useResource(()=>window.JarvisAPI.listMesh(), { mode:eff, pollMs: eff==='live'?30000:0, deps:[eff] });
  const auditRes = useResource(()=>window.JarvisAPI.listAudit(), { mode:eff, pollMs: eff==='live'?30000:0, deps:[eff] });
  const softAudit = uR(()=>{}); softAudit.current = auditRes.softRefetch;

  // Agents roster — hydrate from /api/agents (keeps setAgents intact for the cockpit busy-flip)
  const agentsRes = useResource(()=>window.JarvisAPI.listAgents(), { mode:eff, pollMs:0, deps:[eff] });
  uE(()=>{ if(agentsRes.data && agentsRes.data.length) setAgents(agentsRes.data); },[agentsRes.data]);

  // Timeline — base ledger (/autonomy/observer) + a LIVE TAIL off the same event stream
  const timelineRes = useResource(()=>window.JarvisAPI.listTimeline(), { mode:eff, pollMs: eff==='live'?30000:0, deps:[eff] });
  const [liveLog,setLiveLog]=uS([]);
  const [unseenTl,setUnseenTl]=uS(0);
  const modeRef = uR(mode); modeRef.current = mode;
  useStream((evt)=>{
    if(!evt || typeof evt.type!=='string') return;
    if(evt.type.indexOf('mission')===0) softMis.current();
    if(evt.type==='audit.appended') softAudit.current();
    const row = window.eventToTimelineRow && window.eventToTimelineRow(evt);
    if(row){ setLiveLog(l=>[row, ...l].slice(0,40)); if(modeRef.current!=='timeline') setUnseenTl(n=>Math.min(99,n+1)); }
  }, [eff]);
  uE(()=>{ if(mode==='timeline') setUnseenTl(0); },[mode]);

  const cycleData = ()=>setDataState(s=> s==='live'?'demo':s==='demo'?'offline':'live');
  const urgentCount = decisions.filter(d=>d.urgent).length;
  const interrupts = { cap:4, used:Math.min(4, urgentCount) };
  const counts = { dec:decisions.length, mis:missions.filter(m=>m.status!=='done').length, urgent:urgentCount>0, tl:unseenTl };

  const PRIMARY = { '1':'cockpit','2':'decisions','3':'agents','4':'memory','5':'autonomy','6':'missions','7':'trust','8':'build','9':'observe','0':'interop' };
  const gRef = uR(false); const gTimer=uR(null);

  uE(()=>{
    function onKey(e){
      if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); setPalette(p=>!p); return; }
      if(ambient){ return; }
      const tag=(e.target.tagName||'').toLowerCase();
      if(tag==='input'||tag==='textarea') return;
      if(e.key==='Escape'){ setAdminOpen(false); setMissionOpen(null); setDossier(null); setProvModal(null); setHelpOpen(false); return; }
      if(e.key==='?'){ setHelpOpen(h=>!h); return; }
      // g-chord
      if(gRef.current){
        gRef.current=false; clearTimeout(gTimer.current);
        const k=e.key.toLowerCase();
        if(k==='l'){ setMode('life'); return; }
        if(k==='w'){ setMode('world'); return; }
        if(k==='t'){ setMode('timeline'); return; }
        if(k==='c'){ setMode('comms'); return; }
        if(k==='d'){ setAdminOpen(true); return; }
        if(k==='n'){ setNetOpen(o=>!o); return; }
        if(k==='m'){ setCinema(true); return; }
        if(k==='f'){ setMode('chat'); return; }
        if(k==='a'){ setAmbient(true); return; }
        return;
      }
      if(e.key==='g'){ gRef.current=true; clearTimeout(gTimer.current); gTimer.current=setTimeout(()=>gRef.current=false,900); return; }
      if(PRIMARY[e.key]){ setMode(PRIMARY[e.key]); return; }
      if(e.key.toLowerCase()==='a'){ setAmbient(true); }
    }
    window.addEventListener('keydown',onKey);
    return ()=>window.removeEventListener('keydown',onKey);
  },[ambient]);

  // focus trap + restore-focus for any open overlay (a11y)
  const anyOverlay = palette||helpOpen||adminOpen||netOpen||!!dossier||!!missionOpen||!!provModal;
  uE(()=>{
    if(!anyOverlay) return;
    const prev=document.activeElement;
    const sel='a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';
    const pick=()=>document.querySelector('.pal, .netpanel, [role="dialog"]');
    const tm=setTimeout(()=>{ const node=pick(); if(node){ const f=[...node.querySelectorAll(sel)].filter(e=>e.offsetParent!==null); if(f[0]){ try{ f[0].focus(); }catch(e){} } } },40);
    const onKey=(e)=>{ if(e.key!=='Tab') return; const node=pick(); if(!node) return; const f=[...node.querySelectorAll(sel)].filter(el=>el.offsetParent!==null); if(!f.length) return; const a=f[0],b=f[f.length-1]; if(e.shiftKey&&document.activeElement===a){ e.preventDefault(); b.focus(); } else if(!e.shiftKey&&document.activeElement===b){ e.preventDefault(); a.focus(); } else if(!node.contains(document.activeElement)){ e.preventDefault(); a.focus(); } };
    document.addEventListener('keydown',onKey,true);
    return ()=>{ clearTimeout(tm); document.removeEventListener('keydown',onKey,true); if(prev&&prev.focus){ try{ prev.focus(); }catch(e){} } };
  },[anyOverlay]);

  const timers = uR([]);
  const onFeedback=(idx,v)=>{ setMessages(m=>m.map((x,j)=>j===idx?{...x,fb:v}:x)); try{ window.JarvisClient&&window.JarvisClient.post('/api/feedback',{idx,vote:v}).catch(()=>{}); }catch(e){} };
  const streamReply = (full, prov)=>{
    setMessages(m=>[...m,{role:'agent',who:'jarvis',role_label:'Prime Orchestrator',ts:fmtTimeShort(new Date()),text:'',prov:null,streaming:true}]);
    const toks = String(full).split(/(\s+)/); let i=0;
    const step=()=>{ i++; const partial=toks.slice(0,i).join('');
      setMessages(m=>{ const n=[...m]; for(let k=n.length-1;k>=0;k--){ if(n[k].role==='agent'){ n[k]={...n[k],text:partial,streaming:i<toks.length,prov:i>=toks.length?prov:null}; break; } } return n; });
      if(i<toks.length) timers.current.push(setTimeout(step,26));
    };
    step();
  };
  const submit = uC((text)=>{
    timers.current.forEach(clearTimeout); timers.current=[];
    setMessages(m=>[...m,{role:'user',text,ts:fmtTimeShort(new Date())}]);
    const tr = buildTrace(text);
    setTrace({stages:tr.stages.map(s=>({...s,state:''}))});
    setCenterTab('cognition');
    setAgents(prev=>prev.map(a=> tr.selected.includes(a.id)?{...a,status:'busy'}:a));
    setThinking({label:t.think+' · classify', route:null});
    const seq=[
      [250, ()=>{ setTrace(p=>mark(p,0,'on')); }],
      [700, ()=>{ setTrace(p=>mark(p,0,'done',1,'on')); setThinking({label:t.think+' · route', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [1400,()=>{ setTrace(p=>mark(p,1,'done',2,'on')); setThinking({label:t.think+' · gather', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [2300,()=>{ setTrace(p=>mark(p,2,'done',3,'on')); setThinking({label:t.think+' · synthesize', route:tr.selected.map(s=>s.toUpperCase())}); }],
      [3300,()=>{
        setTrace(p=>mark(p,3,'done')); setThinking(null);
        const prov={ agents:tr.selected, plugins:pluginsFor(text), local:true, conf:+tr.conf.toFixed(2) };
        const fallback = replyFor(text, tr); const agent = tr.selected[0]||'jarvis';
        Promise.resolve((window.JarvisAPI&&window.JarvisAPI.chat)?window.JarvisAPI.chat(text,agent).then(r=>(r&&r.reply)||fallback).catch(()=>fallback):fallback).then(reply=>streamReply(reply,prov));
        setAgents(window.V2.AGENTS);
      }],
    ];
    seq.forEach(([ms,fn])=>timers.current.push(setTimeout(fn,ms)));
  },[t]);
  uE(()=>()=>timers.current.forEach(clearTimeout),[]);

  const resolveDecision = async (id,action,extra={})=>{
    const d=decisions.find(x=>x.id===id); const ag=(window.V2.AGENTS.find(a=>a.id===(d&&d.agent))||{}).name||'';
    const r = await mutate(id, { action, patch:extra.patch }, {});
    if(r.skipped) return;
    if(r.ok){
      const M={ accept:['\u2713','Accepted \u2014 '+ag+' proceeding','ok'], edit:['\u2713','Re-planned & accepted with your edits','ok'], reject:['\u2715','Rejected \u2014 logged as feedback','rej'], defer:['\u21bb','Deferred \u2014 back in 1h','def'] };
      const m=M[action]||M.accept;
      setToast({icon:m[0],text:m[1],kind:m[2],req:r.res&&r.res.request_id});
      decRes.setData(ds=>(ds||[]).filter(x=>x.id!==id));
    } else {
      const why = r.error&&r.error.status===423?'system is halted (kill-switch)':r.error&&r.error.offline?'backend offline':r.error&&r.error.timeout?'timed out':('server '+((r.error&&r.error.status)||'error'));
      setToast({icon:'\u2715',text:'Couldn\u2019t commit \u2014 '+why+'. Still in your queue.',kind:'rej'});
    }
    clearTimeout(window.__toastT); window.__toastT=setTimeout(()=>setToast(null),3400);
  };

  const onKill = async (engage)=>{
    try{ await window.JarvisClient.post('/api/security/kill-switch',{engage,scope:'global',reason:'hud'}); setKilled(engage);
      setToast({icon:engage?'\u25A0':'\u25B6',text:engage?'KILL-SWITCH ENGAGED \u2014 all autonomous action halted':'Kill-switch released \u2014 systems resuming',kind:engage?'rej':'ok'});
    }catch(e){ setToast({icon:'\u2715',text:'Kill-switch unreachable',kind:'rej'}); }
    clearTimeout(window.__toastT); window.__toastT=setTimeout(()=>setToast(null),3200);
  };

  const resolveMission = async (id,action)=>{
    const r = await missionMut.mutate(id, { action }, {});
    if(r.skipped) return;
    if(r.ok){ missionsRes.softRefetch(); const verb={pause:'Paused',resume:'Resumed',accept:'Accepted'}[action]||action; setToast({icon:'\u2713',text:verb+' mission',kind:'ok',req:r.res&&r.res.request_id}); }
    else { setToast({icon:'\u2715',text:'Couldn\u2019t '+action+' \u2014 '+(r.error&&r.error.offline?'offline':'server error')+'.',kind:'rej'}); }
    clearTimeout(window.__toastT); window.__toastT=setTimeout(()=>setToast(null),3000);
  };

  const rootAttrs = { className:'hud-root','data-look':look,'data-accent':accent,'data-density':density,'data-motion':motion,'data-scanline':scanline,'data-dotgrid':dotgrid };
  const fullModes = ['chat','comms'];
  const showCtx = !fullModes.includes(mode);
  const showTicker = mode!=='chat';

  /* primary canvas by mode */
  function Canvas(){
    if(eff==='offline') return <OfflineState mode={mode} onDemo={()=>setDataState('demo')} onRetry={()=>setDataState('live')} t={t}/>;
    switch(mode){
      case 'cockpit': return (
        <div className="workzone duo" style={{flex:1,minHeight:0}}>
          <RosterColumn agents={agents} activeId={activeId} onSelect={id=>{setActiveId(id);setDossier(id);}} t={t}/>
          <div className="col" style={{minHeight:0}}>
            <div className="panel" style={{flex:'1.25 1 0',minHeight:0}}>
              <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
              <div className="panel-head"><Icon d={ICONS.brain} size={14}/><span className="ttl">{t.network}</span><span className="st">focus mode</span></div>
              <NeuralMesh agents={agents} activeId={activeId} onSelect={id=>setActiveId(id)} motion={motion} t={t}/>
            </div>
            <div className="panel" style={{flex:'1 1 0',minHeight:0}}>
              <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
              <div className="center-tabs">
                <button className={'center-tab'+(centerTab==='conversation'?' active':'')} onClick={()=>setCenterTab('conversation')}>{t.conversation}{thinking&&<span className="pip"></span>}</button>
                <button className={'center-tab'+(centerTab==='cognition'?' active':'')} onClick={()=>setCenterTab('cognition')}>{t.cognition}{trace&&!thinking&&<span className="pip"></span>}</button>
              </div>
              {centerTab==='conversation'
                ? <Conversation messages={messages} thinking={thinking} onProv={setProvModal} onFeedback={onFeedback} t={t}/>
                : <CognitionStream trace={trace} t={t}/>}
              <InputBar onSubmit={submit} mic={mic} setMic={setMic} t={t}/>
            </div>
          </div>
        </div>
      );
      case 'decisions': return <div className="workzone solo" style={{flex:1,minHeight:0}}><DecisionsMode res={decRes} onResolve={resolveDecision} pending={pending} conn={eff} interrupts={interrupts} onOpenNet={()=>setNetOpen(true)} t={t}/></div>;
      case 'agents':    return <div className="workzone solo" style={{flex:1,minHeight:0}}><AgentsMode agents={agents} onOpen={id=>{setActiveId(id);setDossier(id);}} t={t}/></div>;
      case 'memory':    return <div className="workzone solo" style={{flex:1,minHeight:0}}><MemoryMode t={t}/></div>;
      case 'autonomy':  return <div className="workzone solo" style={{flex:1,minHeight:0}}><AutonomyMode t={t}/></div>;
      case 'missions':  return <div className="workzone solo" style={{flex:1,minHeight:0}}><MissionsMode res={missionsRes} onOpen={setMissionOpen} onAction={resolveMission} pending={missionMut.pending} onOpenNet={()=>setNetOpen(true)} conn={eff} t={t}/></div>;
      case 'trust':     return <div className="workzone solo" style={{flex:1,minHeight:0}}><TrustMode auditRes={auditRes} killed={killed} onKill={onKill} t={t}/></div>;
      case 'build':     return <div className="workzone solo" style={{flex:1,minHeight:0}}><BuildMode t={t}/></div>;
      case 'observe':   return <div className="workzone solo" style={{flex:1,minHeight:0}}><ObserveMode t={t}/></div>;
      case 'interop':   return <div className="workzone solo" style={{flex:1,minHeight:0}}><InteropMode meshRes={meshRes} t={t}/></div>;
      case 'life':      return (
        <div className="workzone solo" style={{flex:1,minHeight:0}}>
          <div className="col" style={{minHeight:0}}>
            <div className="life-tabs">
              {LIFE_TABS.map(([k])=><button key={k} className={'subtab'+(lifeTab===k?' active':'')} onClick={()=>setLifeTab(k)}><Icon d={ICONS[k]} size={13}/>{t[k]}</button>)}
              <span className="life-note">{t.life} group · demo agents stay watermarked, off the rail</span>
            </div>
            {lifeTab==='finance'&&<FinanceMode t={t}/>}
            {lifeTab==='health'&&<HealthMode t={t}/>}
            {lifeTab==='knowledge'&&<KnowledgeMode t={t}/>}
            {lifeTab==='family'&&<FamilyMode t={t}/>}
          </div>
        </div>
      );
      case 'world':     return <div className="workzone solo" style={{flex:1,minHeight:0}}><WorldviewMode t={t} onAsk={(label)=>{ setMode('cockpit'); setTimeout(()=>submit('Tell me what you know about '+label),120); }}/></div>;
      case 'timeline':  return <div className="workzone solo" style={{flex:1,minHeight:0}}><TimelineMode res={timelineRes} live={liveLog} onMode={setMode} conn={eff} onOpenNet={()=>setNetOpen(true)} t={t}/></div>;
      case 'chat':      return <div className="workzone full" style={{flex:1,minHeight:0}}><ChatMode messages={messages} thinking={thinking} onSubmit={submit} onProv={setProvModal} mic={mic} setMic={setMic} t={t}/></div>;
      case 'comms':     return <div className="workzone full" style={{flex:1,minHeight:0}}><CommsMode t={t}/></div>;
      default:          return null;
    }
  }

  return (
    <div {...rootAttrs}>
      <div className="tex-layer tex-glow"></div>
      <div className="tex-layer tex-dotgrid"></div>
      <div className="tex-layer tex-scan"></div>
      <div className="tex-scanbar"></div>

      <div className="shell">
        <TopBar clock={clock} lang={lang} setLang={setLang} agents={agents} localPct={localPct}
          egress={egress} setEgress={setEgress} mic={mic} setMic={setMic} dataState={eff} cycleData={cycleData}
          onPalette={()=>setPalette(true)} onAmbient={()=>setAmbient(true)} onAdmin={()=>setAdminOpen(true)} onHelp={()=>setHelpOpen(true)} t={t}/>
        <HonestyBanner dataState={eff} onLive={()=>setDataState('live')} t={t}/>
        {killed && <div className="honesty offline" role="alert"><span className="hb-dot"></span><span className="hb-tx">KILL-SWITCH ENGAGED — all autonomous action is halted. Reads stay live; writes are blocked until you release.</span><button className="hb-btn" onClick={()=>onKill(false)}>Release</button></div>}
        {firstRun && eff!=='offline' && (
          <div className="firstrun">
            <span className="fr-dot"></span>
            <span className="fr-tx"><b>Welcome to your HUD.</b> Press <kbd>?</kbd> for the shortcut map, <kbd>⌘K</kbd> to jump anywhere, and toggle the <b>DATA</b> badge to switch live / demo.</span>
            <button className="fr-btn" onClick={dismissFirstRun}>Got it</button>
          </div>
        )}
        <Ticker items={window.V2.TICKER} t={t} hidden={!showTicker}/>

        <div className="main" data-ia="rail">
          <Rail mode={mode} setMode={setMode} counts={counts} onAdmin={()=>setAdminOpen(true)} t={t}/>
          <div style={{minHeight:0,display:'flex',flexDirection:'column',gap:'var(--gap)'}}>
            {showCtx ? (
              <div className="canvas-with-ctx" style={{flex:1,minHeight:0}}>
                <Canvas/>
                <ContextColumn mode={mode} decisions={decisions} notes={notes} setNotes={setNotes} onMode={setMode} egress={egress} dataState={eff} missions={missions} t={t}/>
              </div>
            ) : <Canvas/>}
          </div>
        </div>
      </div>

      {eff==='demo' && <div className="demo-watermark" aria-hidden="true"></div>}
      {dossier && <Dossier id={dossier} onClose={()=>setDossier(null)} onOpen={setDossier}/>}
      {missionOpen && <MissionDrawer mission={missions.find(x=>x.id===missionOpen)} onClose={()=>setMissionOpen(null)} onAction={resolveMission} pending={missionMut.pending} t={t}/>}
      {provModal && <ProvModal prov={provModal} onClose={()=>setProvModal(null)}/>}
      <AdminDrawer open={adminOpen} onClose={()=>setAdminOpen(false)} t={t}/>
      <HelpOverlay open={helpOpen} onClose={()=>setHelpOpen(false)} t={t}/>
      {firstRun && <Onboarding onDone={dismissFirstRun} t={t}/>}
      {cinema && <CinemaMesh agents={agents} onExit={()=>setCinema(false)} t={t}/>}
      <NetPanel open={netOpen} onClose={()=>setNetOpen(false)} conn={eff}/>
      {toast && <div className={'toast '+(toast.kind||'ok')} role="status" aria-live="polite"><span className="toast-i" aria-hidden="true">{toast.icon}</span>{toast.text}{toast.req&&<span className="toast-req">{toast.req}</span>}</div>}
      <Palette open={palette} onClose={()=>setPalette(false)} onMode={setMode}
        setAccent={setAccent} setLang={setLang} onAmbient={()=>{setPalette(false);setAmbient(true);}}
        onAdmin={()=>{setPalette(false);setAdminOpen(true);}} cycleData={()=>setDataState('live')} setEgress={setEgress} t={t}/>
      {ambient && <Ambient onExit={()=>setAmbient(false)} clock={clock} lang={lang} agents={agents} decisions={decisions} motion={motion} egress={egress} t={t}/>}

      <TweaksPanel title="Tweaks">
        <TweakSection label="Honesty & trust"/>
        <TweakRadio label="Data" value={dataState} options={['live','demo','offline']} onChange={setDataState}/>
        <TweakRadio label="Egress" value={egress} options={['sealed','hybrid']} onChange={setEgress}/>
        <TweakSelect label="Active mode" value={mode} options={['cockpit','decisions','agents','memory','autonomy','missions','trust','build','observe','interop','life','world','comms']} onChange={setMode}/>

        <TweakSection label="Aesthetic"/>
        <TweakRadio label="Look" value={look} options={['obsidian','graphite']} onChange={setLook}/>
        <TweakColor label="Accent" value={accent==='cyan'?'#2bb8f0':accent==='amber'?'#ffb23f':accent==='green'?'#41f59b':'#a78bfa'}
          options={['#2bb8f0','#ffb23f','#41f59b','#a78bfa']}
          onChange={hex=>setAccent({'#2bb8f0':'cyan','#ffb23f':'amber','#41f59b':'green','#a78bfa':'violet'}[hex]||'cyan')}/>
        <TweakRadio label="Density" value={density} options={['compact','normal','comfy']} onChange={setDensity}/>

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
