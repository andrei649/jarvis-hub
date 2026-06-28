'use strict';
/* ============================================================
   HUD v3 · MOCK BACKEND (DEMO transport only — synthetic, watermarked)
   An in-browser fake of the Jarvis server. It speaks the SAME wire
   shapes as the real backend (/status, /tasks, /autonomy/tasks/{id}/
   decision …) so the client's real mapper + lifecycle code is exercised
   end-to-end. A chaos layer (latency, jitter, error rate, drops, live
   arrivals) makes the Decision Inbox genuinely pressure-testable.
   ============================================================ */
(function(){
  const sleep = ms=>new Promise(r=>setTimeout(r, ms));
  const rnd = (a,b)=>a+Math.random()*(b-a);

  // chaos config — mutated live by the Chaos console
  const chaos = {
    latencyMs: 280,     // base round-trip
    jitterMs: 220,      // +/- jitter
    errorRate: 0.0,     // fraction of calls that return 5xx/429
    dropRate: 0.0,      // fraction that fail like a dropped connection
    arrivalSec: 0,      // auto-arrival cadence (0 = off)
    paused: false,
    killed: false,      // kill-switch — halts all autonomous action
  };
  const subs = new Set();
  const notify = ()=>subs.forEach(f=>{ try{ f(); }catch(e){} });

  // seed the queue in BACKEND shape (so mapTaskToDecision runs for real)
  const toTask = d => ({
    id:d.id, kind:d.kind.toLowerCase(), agent:d.agent, title:d.title, why:d.why,
    irreversible:d.bucket==='irreversible', urgent:d.urgent, ts:d.ts,
    dry_run:d.dryRun, preflight:d.preflight, requires_approval:d.kind==='ASK', tag:d.tag,
  });
  // seed missions with room to run (lower the in-flight ones so progress is visible)
  function seedMissions(){
    return (window.V2.MISSIONS||[]).map(m=>{
      const c = JSON.parse(JSON.stringify(m));
      if(c.status==='running'){ c.progress = 22 + Math.random()*12; const dn=Math.floor(c.progress/100*c.steps.length); c.steps.forEach((s,i)=>{ s.done = i<dn; }); }
      return c;
    });
  }
  const store = {
    tasks: (window.V2.DECISIONS_V3||[]).map(toTask),
    resolved: [],
    missions: seedMissions(),
    mesh: JSON.parse(JSON.stringify(window.V2.MESH||{devices:[],sync:{}})),
    audit: JSON.parse(JSON.stringify(window.V2.AUDIT_CHAIN||[])),
    policies: JSON.parse(JSON.stringify((window.V2.AUTONOMY&&window.V2.AUTONOMY.policies)||[])),
    agents: (window.V2.AGENTS||[]).map(a=>({...a})),
    version: 1,
  };

  /* ── event stream (SSE-style) + long-running mission engine ──── */
  const streamSubs = new Set();
  function emitEvent(evt){
    evt.at = Date.now();
    if(window.JarvisTelemetry && window.JarvisTelemetry.streamEvent) window.JarvisTelemetry.streamEvent(evt);
    streamSubs.forEach(f=>{ try{ f(evt); }catch(e){} });
  }
  // fresh missions that open as others finish — keeps long-running work alive
  const NEW_MISSIONS = [
    { title:'Summarize this week’s research into a brief', agent:'vision', budget:{used:0,cap:4,unit:'€ cloud',label:'€0 / €4 cloud'}, eta:'~20m',
      steps:[{s:'Gather sources',done:false},{s:'Extract themes',done:false},{s:'Write brief',done:false},{s:'Cite & file',done:false}],
      artifacts:[{name:'weekly-brief.md',kind:'doc'}], audit:[{t:'now',x:'mission opened · €4 cloud cap'}] },
    { title:'Reconcile receipts → expense report', agent:'gecko', budget:{used:0,cap:0,unit:'local',label:'local · on-device'}, eta:'~12m',
      steps:[{s:'Pull receipts',done:false},{s:'Match transactions',done:false},{s:'Flag anomalies',done:false},{s:'Export report',done:false}],
      artifacts:[{name:'expenses-Q2.csv',kind:'data'}], audit:[{t:'now',x:'mission opened · local-only'}] },
    { title:'Draft replies to 4 flagged emails', agent:'veronica', budget:{used:0,cap:3,unit:'€ cloud',label:'€0 / €3 cloud'}, eta:'~8m',
      steps:[{s:'Read thread context',done:false},{s:'Draft replies',done:false},{s:'Hold for review',done:false}],
      artifacts:[{name:'drafts.eml',kind:'doc'}], audit:[{t:'now',x:'mission opened · drafts held for review'}] },
    { title:'Index new papers into the knowledge graph', agent:'jarvis', budget:{used:0,cap:0,unit:'local',label:'local · on-device'}, eta:'~15m',
      steps:[{s:'Fetch 9 PDFs',done:false},{s:'Extract entities',done:false},{s:'Link to graph',done:false},{s:'Reflect',done:false}],
      artifacts:[{name:'kg-delta.json',kind:'data'}], audit:[{t:'now',x:'mission opened · local-only'}] },
  ];
  let nmIdx = 0;
  function pushMission(){
    if(store.missions.length>=6){ const i=store.missions.map(m=>m.status).lastIndexOf('done'); if(i>=0) store.missions.splice(i,1); else return null; }
    const tmpl = NEW_MISSIONS[nmIdx++ % NEW_MISSIONS.length];
    const m = { ...JSON.parse(JSON.stringify(tmpl)), id:'mx'+Date.now().toString(36), status:'running', progress:0, started:'now' };
    store.missions = [m, ...store.missions]; store.version++;
    emitEvent({type:'mission.opened', id:m.id, agent:m.agent, title:m.title}); notify();
    return m;
  }

  let engine = null, beat = 0;
  function engineTick(){
    if(chaos.paused || chaos.killed) return;
    let changed = false;
    store.missions.forEach(m=>{
      if(m.status!=='running') return;
      changed = true;
      m.progress = Math.min(100, Math.round((m.progress + (0.7 + Math.random()*1.6))*10)/10);
      if(m.budget && m.budget.cap>0){
        m.budget.used = Math.min(m.budget.cap, Math.round((m.budget.used + Math.random()*0.06)*100)/100);
        m.budget.label = '€'+m.budget.used.toFixed(2)+' / €'+m.budget.cap+' cloud';
      }
      const done = m.steps.filter(s=>s.done).length;
      const target = Math.floor(m.progress/100 * m.steps.length);
      if(target>done && done<m.steps.length){ m.steps[done].done=true; emitEvent({type:'mission.step', id:m.id, agent:m.agent, title:m.title, step:m.steps[done].s, n:done+1, of:m.steps.length}); }
      if(m.progress>=100){ m.status = Math.random()<0.3?'review':'done'; emitEvent({type:'mission.done', id:m.id, agent:m.agent, title:m.title, status:m.status}); }
      else emitEvent({type:'mission.progress', id:m.id, progress:m.progress});
    });
    // keep ~2 missions in flight so long-running work is always visible
    const running = store.missions.filter(m=>m.status==='running').length;
    if(running<2 && beat%3===0) pushMission();
    if(changed){ store.version++; notify(); }
    beat++;
  }
  function startEngine(){ if(engine) return; engine = setInterval(engineTick, 2200); }
  function stopEngine(){ clearInterval(engine); engine=null; }
  function streamSub(fn){
    streamSubs.add(fn);
    if(streamSubs.size===1) startEngine();
    return ()=>{ streamSubs.delete(fn); if(streamSubs.size===0) stopEngine(); };
  }

  // arrival templates — new governed decisions stream in over time
  const ARRIVALS = [
    { kind:'act', agent:'friday', tag:'signal', title:'Inbox triaged — 3 newsletters archived', why:'Routine cleanup matched your standing rule. Reversible.', irreversible:false, urgent:false, dry_run:'archive 3 · gmail · undo 24h', preflight:[{tool:'gmail.modify',scope:'label:newsletter',preview:'archive 3',risk:'reversible'}] },
    { kind:'ask', agent:'gecko', tag:'nudge', title:'EUR/RON moved 0.4% — rebalance ladder?', why:'Your FX band tripped. A small rebalance keeps the buffer on target.', irreversible:true, urgent:false, dry_run:'transfer €1,100 · ladder rung 3 · approval', preflight:[{tool:'payments.execute',scope:'€1,100',preview:'rebalance',risk:'approval'}] },
    { kind:'ask', agent:'ultron', tag:'alert', title:'Skill wants network it has never used', why:'churn-cohort-report requested api.stripe.com. Outside its declared scope — held.', irreversible:true, urgent:true, dry_run:'net.outbound · api.stripe.com · BLOCKED pending consent', preflight:[{tool:'net.outbound',scope:'api.stripe.com',preview:'first use',risk:'gated'}] },
    { kind:'notify', agent:'hercules', tag:'nudge', title:'Recovery is high — good day to train', why:'HRV up 12%. No action needed; logging for your ring.', irreversible:false, urgent:false, dry_run:'informational', preflight:[] },
    { kind:'act', agent:'stark', tag:'anticip', title:'KPI digest ready for the 14:00 review', why:'Compiled from the live store. Drop into the deck?', irreversible:false, urgent:false, dry_run:'append 1 slide · deck draft · nothing sent', preflight:[{tool:'skill.run',scope:'kpi-digest',preview:'build',risk:'allow'}] },
  ];
  let arrIdx = 0, arrTimer = null;
  function pushArrival(){
    const tmpl = ARRIVALS[arrIdx++ % ARRIVALS.length];
    const t = { ...tmpl, id:'tx'+Date.now().toString(36), ts:new Date().toTimeString().slice(0,5), requires_approval:tmpl.kind==='ask', _new:true };
    store.tasks = [t, ...store.tasks]; store.version++;
    emitEvent({type:'decision.arrived', id:t.id, agent:t.agent, title:t.title, kind:t.kind});
    notify();
    return t;
  }
  function setChaos(patch){
    Object.assign(chaos, patch);
    clearInterval(arrTimer);
    if(chaos.arrivalSec>0 && !chaos.paused) arrTimer = setInterval(pushArrival, chaos.arrivalSec*1000);
    notify();
  }

  // chat reply generator (agent-flavoured) for the cockpit
  const chatReply = (agent, text)=>{
    const map={ pepper:'Pepper has it \u2014 your calendar is reconciled and the 14:00 Raiffeisen review is protected with prep at 13:15.', stark:'Stark pulled the numbers \u2014 Digitaholic MRR is +6.2% WoW; I flagged the missing churn-cohort slide.', vision:'Vision is on it \u2014 indexing sources now; a cited brief will land in your queue within the hour.', veronica:'Veronica drafted it \u2014 held for your review since Ultron flagged a client name as sensitive.', gecko:'Gecko is watching the markets \u2014 idle cash is \u20ac4.2k over buffer, a sweep is available for your approval.', hercules:'Hercules logged it \u2014 sleep was 7h12m; tonight is a light mobility session.', frigga:'Frigga keeps that local \u2014 noted privately, nothing left the device.', friday:'Friday compiled your brief \u2014 6 items ranked, weather clear, a good day to cycle in.', jerome:'Jerome cued the soundtrack \u2014 a focus playlist matched to your morning.', jarvis:'Understood. I will handle that directly and keep everything on-device.' };
    return map[agent]||map.jarvis;
  };

  // status payload mirrors the real /status
  const status = ()=>({
    version:'v3-demo', lm_online:true, model_state:'ready', loaded_model:'gemma-4-26b (demo)',
    sys:{ host:'jarvis-prime', cpu:'34%', ram_used:11, ram_total:32, gpu:'RTX', vram_used:13, vram_total:24, gpu_load:42, backend:'llama.cpp', model:'gemma-4-26b', latency:Math.round(rnd(3,6)*10)/10, uptime:'4d', sessions:1 },
    agents:(window.V2.AGENTS||[]).map(a=>({ id:a.id, status:a.status })),
  });

  async function handle(method, path, body){
    if(chaos.paused) { await sleep(60); throw Object.assign(new Error('paused'), { code:'PAUSED' }); }
    // simulate the network: latency + jitter
    await sleep(Math.max(20, chaos.latencyMs + rnd(-chaos.jitterMs, chaos.jitterMs)));
    // dropped connection (no HTTP response)
    if(Math.random() < chaos.dropRate) throw Object.assign(new Error('ECONNRESET'), { code:'DROP' });
    // server error
    if(Math.random() < chaos.errorRate){ const s=[500,503,429][Math.floor(Math.random()*3)]; return { status:s, json:{ error:'chaos', code:s } }; }

    const u = path.split('?')[0];

    if(method==='GET' && u==='/status') return { status:200, json:status() };
    if(method==='GET' && u==='/tasks'){
      const tasks = store.tasks.map(t=>({ ...t }));   // serve once with _new intact
      store.tasks.forEach(t=>{ if(t._new) t._new=false; });   // then clear → one-time flash
      return { status:200, json:{ tasks } };
    }
    if(method==='GET' && u==='/autonomy/interrupts') return { status:200, json:{ cap:4, used: Math.min(4, store.tasks.filter(t=>t.urgent).length), window:'today' } };

    if(method==='POST' && u==='/api/feedback') return { status:200, json:{ ok:true } };
    if(method==='POST' && u==='/chat'){
      if(chaos.killed) return { status:423, json:{ error:'system halted' } };
      return { status:200, json:{ reply: chatReply((body&&body.agent)||'jarvis', (body&&body.text)||''), local:true } };
    }
    if(method==='GET' && u==='/api/security/kill-switch') return { status:200, json:{ engaged: chaos.killed, scope:'global' } };
    if(method==='POST' && u==='/api/security/kill-switch'){ chaos.killed = !!(body&&body.engage); if(chaos.killed) stopEngine(); else if(streamSubs.size>0) startEngine(); emitEvent({type:'killswitch', engaged:chaos.killed}); notify(); return { status:200, json:{ ok:true, engaged:chaos.killed } }; }

    if(method==='GET' && u==='/autonomy/missions') return { status:200, json:{ missions: store.missions.map(m=>({ ...m, steps:m.steps.map(s=>({...s})), budget:{...m.budget} })) } };
    if(method==='GET' && u==='/autonomy/observer') return { status:200, json:{ events: (window.V2.TIMELINE||[]).map(e=>({ ...e })) } };
    if(method==='GET' && u==='/api/a2a/peers') return { status:200, json:{ devices: store.mesh.devices.map(d=>({...d})), sync: {...store.mesh.sync} } };
    if(method==='GET' && u==='/api/security/audit/intent') return { status:200, json:{ actions: store.audit.map(a=>({...a})) } };
    if(method==='GET' && u==='/api/agents') return { status:200, json:{ agents: store.agents.map(a=>({...a})) } };
    if(method==='POST' && u==='/api/admin/export') return { status:200, json:{ ok:true, bytes:48211934, items:{ sessions:312, memories:1428, audit:store.audit.length, kg_nodes:64 }, file:'jarvis-export-2026-06-28.tar.gz' } };
    if(method==='POST' && u==='/api/admin/forget') return { status:200, json:{ ok:true, scheduled:true, purge_at:'+24h', note:'reversible for 24h' } };
    if(method==='GET' && u==='/api/security/audit/verify') return { status:200, json:{ ok:!chaos.killed, head:(store.audit[0]&&store.audit[0].hash||'genesis').slice(0,8), checked:store.audit.length+304, broken:chaos.killed?0:0 } };
    if(method==='GET' && u==='/api/analytics/locality') return { status:200, json:window.V2.LOCALITY };
    if(method==='GET' && u==='/governance') return { status:200, json:window.V2.GOVERNANCE };
    if(method==='GET' && u==='/posture') return { status:200, json:window.V2.POSTURE };
    if(method==='GET' && u==='/loop-breaker') return { status:200, json:window.V2.LOOPBREAKER };
    if(method==='GET' && u.indexOf('/api/memory/search')===0){ const q=(path.split('q=')[1]||'').split('&')[0]; const dq=decodeURIComponent(q||'').toLowerCase(); const base=(window.V2.RECALLS||[]); const hits=dq?base.filter(r=>(r.rx||'').toLowerCase().includes(dq)):base; const results=(hits.length?hits:base.slice(0,2)).map((r,i)=>({ score:(0.92-i*0.07).toFixed(2), payload:r.rx, source:r.rsrc })); return { status:200, json:{ query:dq, results } }; }
    if(method==='POST' && u==='/autonomy/policy'){
      if(chaos.killed) return { status:423, json:{ error:'system halted' } };
      const ag=body&&body.agent, mode=body&&body.mode;
      const p=store.policies.find(x=>x.agent===ag); if(p) p.mode=mode;
      store.audit.forEach(a=>{ a._new=false; });
      store.audit.unshift({ verb:'POLICY', t:new Date().toTimeString().slice(0,5), x:ag+' autonomy \u2192 '+String(mode).toUpperCase(), hash:Math.random().toString(16).slice(2,10), prev:((store.audit[0]&&store.audit[0].hash)||'genesis').slice(0,6), _new:true });
      if(store.audit.length>8) store.audit.pop();
      emitEvent({type:'audit.appended', id:ag}); notify();
      return { status:200, json:{ ok:true, agent:ag, mode } };
    }
    const mm = u.match(/^\/autonomy\/missions\/([^/]+)\/(pause|resume|accept)$/);
    if(method==='POST' && mm){
      if(chaos.killed) return { status:423, json:{ error:'system halted by kill-switch' } };
      const id=decodeURIComponent(mm[1]), act=mm[2];
      const ms=store.missions.find(x=>x.id===id);
      if(!ms) return { status:404, json:{ error:'not found', id } };
      if(act==='pause') ms.status='paused';
      else if(act==='resume') ms.status='running';
      else if(act==='accept'){ ms.status='done'; ms.progress=100; ms.steps.forEach(s=>s.done=true); }
      store.version++; emitEvent({type:'mission.'+act, id}); notify();
      return { status:200, json:{ ok:true, id, action:act, request_id:'req_'+Math.random().toString(36).slice(2,10) } };
    }

    // resolve a decision
    const m = u.match(/^\/autonomy\/tasks\/([^/]+)\/decision$/);
    if(method==='POST' && m){
      if(chaos.killed) return { status:423, json:{ error:'system halted by kill-switch', id:decodeURIComponent(m[1]) } };
      const id = decodeURIComponent(m[1]);
      const idx = store.tasks.findIndex(t=>t.id===id);
      if(idx<0) return { status:404, json:{ error:'not found', id } };
      // occasionally a server-side conflict to exercise rollback (only under error pressure)
      if(chaos.errorRate>0 && Math.random() < chaos.errorRate){ return { status:409, json:{ error:'conflict — already actioned elsewhere', id } }; }
      const [task] = store.tasks.splice(idx,1); store.version++;
      const receipt = { ok:true, id, action:(body&&body.action)||'accept', request_id:'req_'+Math.random().toString(36).slice(2,10), audit_hash:'sha256:'+Math.random().toString(16).slice(2,10), idempotency_key:body&&body.key, ts:Date.now() };
      store.resolved.unshift({ task, receipt });
      const act=(body&&body.action)||'accept';
      store.audit.forEach(a=>{ a._new=false; });
      store.audit.unshift({ verb:act.toUpperCase().slice(0,6), t:new Date().toTimeString().slice(0,5), x:(task.title||'decision')+' \u2014 actioned by you', hash:receipt.audit_hash.replace('sha256:',''), prev:((store.audit[0]&&store.audit[0].hash)||'genesis').slice(0,6), _new:true });
      if(store.audit.length>8) store.audit.pop();
      emitEvent({type:'decision.resolved', id:task.id, agent:task.agent, title:task.title, action:act});
      emitEvent({type:'audit.appended', id:task.id});
      notify();
      return { status:200, json:receipt };
    }

    // honest 404 for anything we don't serve (so unknowns never look live)
    return { status:404, json:{ error:'no route', path:u } };
  }

  window.JarvisMock = {
    handle,
    chaos, setChaos, pushArrival, pushMission,
    store, streamSub, emitEvent,
    sub:f=>{ subs.add(f); return ()=>subs.delete(f); },
    reset:()=>{ store.tasks = (window.V2.DECISIONS_V3||[]).map(toTask); store.resolved=[]; store.missions=seedMissions(); store.mesh=JSON.parse(JSON.stringify(window.V2.MESH||{devices:[],sync:{}})); store.audit=JSON.parse(JSON.stringify(window.V2.AUDIT_CHAIN||[])); store.version++; notify(); },
  };
})();
