'use strict';
/* ============================================================
   HUD v3 · LIVE DATA LAYER
   A real runtime API client for the Jarvis backend. Mirrors the
   verified contract in /api (client.ts · loaders.ts · actions.ts):
     - same-origin fetch, localhost-exempt, 401 → X-User-Token retry
     - /status is the heartbeat (serverUp); honest-empty by default
     - real sources only; the seeded corpus is DEMO-only (watermarked)
   Adds what a north-star surface needs to survive production:
     - AbortController + timeout on every call
     - a telemetry bus (every request: id, ms, status, attempt) → p50/p95
     - mode-aware transport: LIVE=real fetch · DEMO=mock · OFFLINE=throw
     - hooks: useConnection / useResource (poll+SWR) / useMutation (optimistic)
   ============================================================ */
const { useState:uSa, useEffect:uEa, useRef:uRa, useCallback:uCa, useMemo:uMa } = React;

const CFG = {
  base: '',                 // same-origin; point at http://host:4000 for remote
  timeoutMs: 8000,
  heartbeatMs: 10000,       // /status probe cadence
  pollMs: 15000,            // decision queue refresh cadence
  tokenKey: 'hud.user_token',
  adminKey: 'hud.admin_token',
};

/* ---------------- token / headers (mirrors api/client.ts) ---------------- */
const tok = {
  get:   ()=>{ try{ return localStorage.getItem(CFG.tokenKey)||''; }catch(e){ return ''; } },
  set:   v=>{ try{ v?localStorage.setItem(CFG.tokenKey,v):localStorage.removeItem(CFG.tokenKey); }catch(e){} },
  admin: ()=>{ try{ return localStorage.getItem(CFG.adminKey)||''; }catch(e){ return ''; } },
};
function headers(admin, hasBody){
  const h = { Accept:'application/json' };
  if(hasBody) h['Content-Type']='application/json';
  const u = tok.get(); if(u) h['X-User-Token']=u;
  if(admin){ const a=tok.admin(); if(a) h['X-Admin-Token']=a; }
  return h;
}

/* ---------------- telemetry bus ---------------- */
const Telemetry = (()=>{
  const log = [];           // ring buffer of completed requests
  const subs = new Set();
  let seq = 0, inflight = 0, events = 0;
  const streamIds = new Set();
  const MAX = 200;
  const emit = ()=>subs.forEach(f=>{ try{ f(); }catch(e){} });
  function begin(method, path, mode){
    inflight++; emit();
    return { id:'r'+(++seq), method, path, mode, t0:performance.now() };
  }
  function end(rec, status, ok, attempt, bytes){
    inflight = Math.max(0, inflight-1);
    const ms = Math.round(performance.now()-rec.t0);
    const row = { ...rec, status, ok, attempt:attempt||1, ms, bytes:bytes||0, at:Date.now() };
    log.unshift(row); if(log.length>MAX) log.pop();
    emit(); return row;
  }
  function pct(p){
    const ok = log.filter(r=>r.ok && !r.stream).map(r=>r.ms).sort((a,b)=>a-b);
    if(!ok.length) return 0;
    return ok[Math.min(ok.length-1, Math.floor(p/100*ok.length))];
  }
  function stats(){
    const recent = log.filter(r=>!r.stream).slice(0, 60);
    const errs = recent.filter(r=>!r.ok).length;
    return {
      inflight,
      total: log.filter(r=>!r.stream).length,
      p50: pct(50), p95: pct(95),
      errRate: recent.length ? errs/recent.length : 0,
      count: recent.length,
      events, streams: streamIds.size,
    };
  }
  function streamEvent(){ events++; emit(); }
  function openStream(path, mode){ const id='s'+(++seq); streamIds.add(id); log.unshift({ id, method:'SSE', path, mode, status:'open', ok:true, attempt:1, ms:0, bytes:0, at:Date.now(), stream:true }); if(log.length>MAX) log.pop(); emit(); return id; }
  function closeStream(id){ streamIds.delete(id); emit(); }
  return { begin, end, stats, log, streamEvent, openStream, closeStream, sub:f=>{ subs.add(f); return ()=>subs.delete(f); } };
})();

/* ---------------- errors ---------------- */
class OfflineError extends Error { constructor(p){ super('offline: '+p); this.offline=true; this.status=0; } }
class TimeoutError extends Error { constructor(p){ super('timeout: '+p); this.timeout=true; this.status=0; } }

/* ---------------- mode-aware transport ----------------
   getMode() is injected by the app so the client always knows
   whether to hit the wire, the mock, or refuse (offline).        */
let _getMode = ()=>'demo';
function bindMode(fn){ _getMode = fn; }

async function xfetch(method, path, body, opts={}){
  const mode = opts.modeOverride || _getMode();
  const rec = Telemetry.begin(method, path, mode);

  // OFFLINE — never invent data; throw so the UI shows an honest state
  if(mode==='offline'){ Telemetry.end(rec, 0, false, 1); throw new OfflineError(path); }

  // DEMO — route to the in-browser mock backend (synthetic, watermarked)
  if(mode==='demo'){
    try{
      const r = await window.JarvisMock.handle(method, path, body);
      Telemetry.end(rec, r.status, r.status<400, r.attempt||1, JSON.stringify(r.json||'').length);
      if(r.status>=400){ throw Object.assign(new Error(method+' '+path+' → '+r.status), { status:r.status, payload:r.json }); }
      return r.json;
    }catch(e){
      if(e.status===undefined) Telemetry.end(rec, 0, false, 1);
      throw e;
    }
  }

  // LIVE — real same-origin fetch with timeout + one 401→token retry
  const run = async (attempt)=>{
    const ctrl = new AbortController();
    const timer = setTimeout(()=>ctrl.abort('timeout'), CFG.timeoutMs);
    const init = { method, headers:headers(opts.admin, body!==undefined), signal:ctrl.signal };
    if(body!==undefined) init.body = JSON.stringify(body);
    let res;
    try{ res = await fetch(CFG.base+path, init); }
    catch(e){ clearTimeout(timer); if(ctrl.signal.reason==='timeout'){ Telemetry.end(rec,0,false,attempt); throw new TimeoutError(path); } Telemetry.end(rec,0,false,attempt); throw new OfflineError(path); }
    clearTimeout(timer);
    if(res.status===401 && attempt===1 && typeof window!=='undefined'){
      let t = tok.get();
      if(!t){ t = window.prompt('This Jarvis is network-exposed. Enter your X-User-Token:')||''; if(t) tok.set(t); }
      if(t) return run(2);
    }
    const text = await res.text();
    Telemetry.end(rec, res.status, res.ok, attempt, text.length);
    if(!res.ok) throw Object.assign(new Error(method+' '+path+' → '+res.status), { status:res.status });
    try{ return text ? JSON.parse(text) : null; }catch(e){ return null; }
  };
  return run(1);
}

const get  = (p,o)=>xfetch('GET', p, undefined, o);
const post = (p,b,o)=>xfetch('POST', p, b, o);
const put  = (p,b,o)=>xfetch('PUT', p, b, o);

/* event stream — SSE-style. DEMO subscribes to the mock's engine; LIVE opens
   an EventSource('/events'); OFFLINE is a no-op. Returns an unsubscribe.   */
function streamEvents(onEvent){
  const mode = _getMode();
  if(mode==='offline') return ()=>{};
  const sid = Telemetry.openStream('/events', mode);
  if(mode==='demo'){
    const un = window.JarvisMock.streamSub(onEvent);
    return ()=>{ un(); Telemetry.closeStream(sid); };
  }
  let es; try{ es = new EventSource(CFG.base+'/events'); es.onmessage = e=>{ try{ onEvent(JSON.parse(e.data)); }catch(x){} }; }catch(e){}
  return ()=>{ try{ es&&es.close(); }catch(e){} Telemetry.closeStream(sid); };
}

/* ---------------- mappers · backend shape → v3 view shape ----------------
   The honest mapping for the Decision Inbox: the backend autonomy queue
   (/tasks) is the source of truth. A task that needs the human is a
   decision. Unknown fields degrade gracefully; empty queue = queue clear. */
const KIND_FROM = { approval:'ASK', confirm:'ASK', ask:'ASK', notify:'NOTIFY', fyi:'NOTIFY', act:'ACT', action:'ACT', proposal:'ACT' };
function mapTaskToDecision(tk, i){
  const id = tk.id || tk.task_id || ('t'+i);
  const kind = KIND_FROM[(tk.kind||tk.type||'').toLowerCase()] || (tk.requires_approval ? 'ASK' : 'ACT');
  const irreversible = !!(tk.irreversible || tk.reversible===false || /payment|delete|send|post/i.test(tk.tool||tk.action||''));
  return {
    id,
    kind,
    tag: tk.tag || (kind==='ASK'?'alert':kind==='NOTIFY'?'signal':'anticip'),
    agent: tk.agent || tk.owner || 'jarvis',
    title: tk.title || tk.summary || tk.action || 'Pending decision',
    why: tk.why || tk.rationale || tk.detail || '',
    bucket: irreversible ? 'irreversible' : 'reversible',
    urgent: !!(tk.urgent || tk.priority==='high'),
    ts: tk.ts || tk.created_at || '',
    dryRun: tk.dry_run || tk.preview || (tk.tool? (tk.tool+' · awaiting consent') : 'no side effects'),
    preflight: Array.isArray(tk.preflight) ? tk.preflight : (Array.isArray(tk.tool_calls)? tk.tool_calls.map(c=>({tool:c.tool||c.name,scope:c.scope||'',preview:c.preview||'',risk:c.risk||'gated'})) : []),
    _new: !!tk._new,
    _src: tk,
  };
}

/* ---------------- endpoint bindings (verified routes) ---------------- */
const API = {
  // heartbeat — unguarded; the single source of "is the server up + LLM ready"
  status: ()=>get('/status'),

  // Decision Inbox = the autonomy queue
  listDecisions: async ()=>{
    const d = await get('/tasks');
    const tasks = Array.isArray(d&&d.tasks) ? d.tasks : Array.isArray(d) ? d : [];
    return tasks.map(mapTaskToDecision);
  },
  // resolve one — brief §: POST /autonomy/tasks/{id}/decision {action,patch,idempotency_key}
  resolveDecision: (id, action, extra={})=>post('/autonomy/tasks/'+encodeURIComponent(id)+'/decision',
    { action, idempotency_key:extra.key, patch:extra.patch||null, ts:Date.now() }),

  // Missions — long-running governed work
  listMissions: async ()=>{ const d=await get('/autonomy/missions'); return Array.isArray(d&&d.missions)?d.missions:(Array.isArray(d)?d:[]); },
  missionAction: (id, action)=>post('/autonomy/missions/'+encodeURIComponent(id)+'/'+action, { ts:Date.now() }),

  // Timeline — Today in Jarvis (activity ledger)
  listTimeline: async ()=>{ const d=await get('/autonomy/observer'); return Array.isArray(d&&d.events)?d.events:(Array.isArray(d)?d:[]); },

  // Mesh (devices/peers) + Trust audit chain
  listMesh: async ()=>{ const d=await get('/api/a2a/peers'); return { devices:(d&&d.devices)||[], sync:Object.assign({state:'—',vector_lag:'—',last_full:'—',conflicts:0},(d&&d.sync)||{}) }; },
  listAudit: async ()=>{ const d=await get('/api/security/audit/intent'); const a=(d&&(d.actions||d.records||d.entries))||[]; return Array.isArray(a)?a:[]; },
  listAgents: async ()=>{ const d=await get('/api/agents'); return Array.isArray(d&&d.agents)?d.agents:[]; },
  setPolicy: (agent,mode)=>post('/autonomy/policy',{ agent, mode }),
  memorySearch: (q)=>get('/api/memory/search?q='+encodeURIComponent(q)+'&top_k=8'),
  chat: (text,agent)=>post('/chat',{ text, agent }),
  auditVerify: ()=>get('/api/security/audit/verify'),
  locality: ()=>get('/api/analytics/locality'),
  governance: ()=>get('/governance'),
  posture: ()=>get('/posture'),
  loopBreaker: ()=>get('/loop-breaker'),

  // interrupt budget (calm-by-the-numbers)
  interrupts: ()=>get('/autonomy/interrupts'),

  // other v3 surfaces (read side mirrors api/live.ts)
  missions: ()=>get('/autonomy/missions'),
  mesh:     ()=>get('/api/a2a/peers'),
  timeline: ()=>get('/autonomy/observer'),
  audit:    ()=>get('/api/security/audit/intent'),
  killSwitch: ()=>get('/api/security/kill-switch'),
  setKill:  engage=>post('/api/security/kill-switch', { engage, scope:'global', reason:'hud' }, { admin:true }),
};

/* ---------------- hook · connection heartbeat ----------------
   Owns the truth of LIVE/DEMO/OFFLINE. In LIVE it probes /status on a
   cadence; a failed probe degrades to OFFLINE (honest) and surfaces why. */
function useConnection(intent /* 'live'|'demo'|'offline' */){
  const [state, setState] = uSa({ phase: intent==='demo'?'demo':'probing', serverUp:false, llm:{state:'unknown',model:null}, sys:null, lastProbe:0, error:null });
  const timer = uRa(null);

  const probe = uCa(async ()=>{
    if(intent!=='live'){ setState(s=>({ ...s, phase:intent })); return; }
    try{
      const d = await xfetch('GET','/status',undefined,{ modeOverride:'live' });
      const llm = d.model_state ? { state:d.model_state, model:d.loaded_model||null }
                : d.lm_online!==undefined ? { state:d.lm_online?'no_model':'offline', model:null }
                : { state:'unknown', model:null };
      setState({ phase:'live', serverUp:true, llm, sys:d.sys||null, lastProbe:Date.now(), error:null });
    }catch(e){
      setState(s=>({ ...s, phase:'offline', serverUp:false, lastProbe:Date.now(), error:e.timeout?'timeout':'unreachable' }));
    }
  },[intent]);

  uEa(()=>{
    clearInterval(timer.current);
    if(intent==='live'){ probe(); timer.current=setInterval(probe, CFG.heartbeatMs); }
    else setState(s=>({ ...s, phase:intent, error:null }));
    return ()=>clearInterval(timer.current);
  },[intent, probe]);

  return [state, probe];
}

/* ---------------- hook · useResource (poll + stale-while-revalidate) ----------------
   Returns { data, error, loading, stale, refetch, lastOk }. Keeps the last
   good data on screen while revalidating; an error after success → stale, not blank. */
function useResource(fetcher, { mode, pollMs, deps=[] }={}){
  const [st, setSt] = uSa({ data:null, error:null, loading:true, stale:false, lastOk:0 });
  const alive = uRa(true);
  const gen = uRa(0);
  const fref = uRa(fetcher); fref.current = fetcher;

  const run = uCa(async (soft)=>{
    const myGen = ++gen.current;
    setSt(s=>({ ...s, loading: soft?false:!s.data, error:null }));
    try{
      const data = await fref.current();
      if(!alive.current || myGen!==gen.current) return;
      setSt({ data, error:null, loading:false, stale:false, lastOk:Date.now() });
    }catch(e){
      if(!alive.current || myGen!==gen.current) return;
      setSt(s=>({ data:s.data, error:e, loading:false, stale:!!s.data, lastOk:s.lastOk }));
    }
  },[]);

  uEa(()=>{ alive.current=true; run(false);
    let iv=null; if(pollMs && mode!=='offline') iv=setInterval(()=>run(true), pollMs);
    return ()=>{ alive.current=false; clearInterval(iv); };
  // eslint-disable-next-line
  },[mode, pollMs, ...deps]);

  return { ...st, refetch:()=>run(false), softRefetch:()=>run(true), setData:(d)=>setSt(s=>({ ...s, data:typeof d==='function'?d(s.data):d })) };
}

/* ---------------- hook · useMutation (optimistic + rollback + idempotency) ---------------- */
function useMutation(mutator){
  const [pending, setPending] = uSa({});   // id → true while in flight (double-submit lock)
  const mref = uRa(mutator); mref.current = mutator;
  const run = uCa(async (id, args, { optimistic, rollback }={})=>{
    if(pending[id]) return { skipped:true };
    setPending(p=>({ ...p, [id]:true }));
    const key = id+':'+(args&&args.action||'')+':'+Date.now();
    if(optimistic) optimistic();
    try{
      const res = await mref.current(id, { ...args, key });
      setPending(p=>{ const n={...p}; delete n[id]; return n; });
      return { ok:true, res };
    }catch(e){
      if(rollback) rollback(e);
      setPending(p=>{ const n={...p}; delete n[id]; return n; });
      return { ok:false, error:e };
    }
  },[pending]);
  return { mutate:run, pending };
}

/* hook · subscribe to the event stream for the component's lifetime */
function useStream(onEvent, deps){
  const ref = uRa(onEvent); ref.current = onEvent;
  uEa(()=>{ const un = streamEvents(e=>ref.current(e)); return un; }, deps||[]);
}

/* shared mapper · live stream event → Today-in-Jarvis row (null = don't surface) */
function eventToTimelineRow(evt){
  if(!evt || !evt.type) return null;
  const now = new Date().toTimeString().slice(0,5);
  switch(evt.type){
    case 'decision.arrived':  return { t:now, agent:evt.agent, kind:'decision', title:evt.title, detail:'New '+String(evt.kind||'').toLowerCase()+' decision queued for you.', local:true, _live:true };
    case 'decision.resolved': { const v={accept:'Accepted',edit:'Accepted (edited)',reject:'Rejected',defer:'Deferred'}[evt.action]||evt.action; return { t:now, agent:evt.agent, kind:evt.action==='reject'?'guard':'action', title:v+': '+evt.title, detail:'Resolved from the Decision Inbox.', local:true, _live:true }; }
    case 'mission.opened':    return { t:now, agent:evt.agent, kind:'mission', title:'Opened mission · '+evt.title, detail:'Long-running work started.', local:true, _live:true };
    case 'mission.step':      return { t:now, agent:evt.agent, kind:'action', title:evt.step, detail:'Mission step '+evt.n+'/'+evt.of+' · '+evt.title, local:true, _live:true };
    case 'mission.done':      return { t:now, agent:evt.agent, kind:'mission', title:(evt.status==='review'?'Mission ready for review':'Mission complete')+' · '+evt.title, detail:evt.status==='review'?'Needs your sign-off.':'Sealed in audit.', local:true, _live:true };
    default: return null;
  }
}

Object.assign(window, {
  JarvisAPI: API,
  JarvisClient: { get, post, put, xfetch, bindMode, tok, CFG },
  JarvisTelemetry: Telemetry,
  OfflineError, TimeoutError,
  useConnection, useResource, useMutation, useStream, streamEvents,
  mapTaskToDecision, eventToTimelineRow,
});
