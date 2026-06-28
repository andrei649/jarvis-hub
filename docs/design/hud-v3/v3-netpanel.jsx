'use strict';
/* ============================================================
   HUD v3 · NETWORK INSPECTOR + CHAOS CONSOLE  (pressure-test rig)
   Bottom-docked devtools for the live data layer:
     - Inspector: every request from the telemetry bus (path, status, ms, attempt)
     - Chaos:     inject latency / jitter / errors / drops / live arrivals
     - Strip:     always-visible p50 · p95 · inflight · err% (ties to north-star guard)
   Chaos drives the DEMO mock transport (synthetic). LIVE calls hit the wire.
   ============================================================ */
const { useState:uSn, useEffect:uEn, useRef:uRn } = React;
const { Icon:Icn, ICONS:IKn } = window;

/* throttled subscription to the telemetry bus (rAF-coalesced under load) */
function useBusTick(){
  const [,set] = uSn(0);
  uEn(()=>{
    let raf=0, dirty=false;
    const tick=()=>{ dirty=false; set(n=>n+1); };
    const onChange=()=>{ if(!dirty){ dirty=true; raf=requestAnimationFrame(tick); } };
    const u1 = window.JarvisTelemetry.sub(onChange);
    const u2 = window.JarvisMock ? window.JarvisMock.sub(onChange) : ()=>{};
    return ()=>{ u1(); u2(); cancelAnimationFrame(raf); };
  },[]);
}

function statusClassFor(r){ if(r.status===0) return 'drop'; if(r.status>=500) return 'err5'; if(r.status>=400) return 'err4'; return 'ok'; }

/* compact telemetry strip — sits in the Decisions header */
function TelemetryStrip({ conn }){
  useBusTick();
  const s = window.JarvisTelemetry.stats();
  const p95cls = s.p95>4000?'bad':s.p95>1500?'warn':'good';
  return (
    <div className="telem-strip" title="live data-layer telemetry">
      <span className={'tel-dot '+(conn==='live'?'live':conn==='demo'?'demo':'off')}></span>
      <span className="tel-k">p50</span><span className="tel-v">{s.p50}ms</span>
      <span className="tel-k">p95</span><span className={'tel-v '+p95cls}>{s.p95}ms</span>
      <span className="tel-k">inflight</span><span className="tel-v">{s.inflight}</span>
      <span className="tel-k">err</span><span className={'tel-v '+(s.errRate>0.1?'bad':'good')}>{Math.round(s.errRate*100)}%</span>
    </div>
  );
}

/* one row in the inspector */
function ReqRow({ r }){
  return (
    <div className={'ni-row '+statusClassFor(r)}>
      <span className="ni-method">{r.method}</span>
      <span className="ni-path">{r.path}</span>
      <span className="ni-mode">{r.mode}</span>
      <span className="ni-status">{r.status||'—'}</span>
      <span className="ni-ms">{r.ms}ms</span>
      <span className="ni-try">{r.attempt>1?('×'+r.attempt):''}</span>
    </div>
  );
}

function NetInspector(){
  useBusTick();
  const log = window.JarvisTelemetry.log;
  const s = window.JarvisTelemetry.stats();
  return (
    <div className="ni-wrap">
      <div className="ni-summary">
        <span><b>{s.total}</b> reqs</span>
        <span>p50 <b>{s.p50}ms</b></span>
        <span>p95 <b className={s.p95>4000?'bad':''}>{s.p95}ms</b></span>
        <span>inflight <b>{s.inflight}</b></span>
        <span>err <b className={s.errRate>0.1?'bad':''}>{Math.round(s.errRate*100)}%</b></span>
        <span>stream <b className={s.streams?'good':''}>{s.streams?('open · '+s.events+' evt'):'closed'}</b></span>
      </div>
      <div className="ni-head"><span>method</span><span>path</span><span>mode</span><span>status</span><span>ms</span><span>retry</span></div>
      <div className="ni-list">
        {log.length===0 && <div className="ni-empty">no requests yet — interact with the Decision Inbox</div>}
        {log.slice(0,80).map(r=><ReqRow key={r.id} r={r}/>)}
      </div>
    </div>
  );
}

function Slider({ label, val, min, max, step, unit, onChange }){
  return (
    <div className="ch-row">
      <label>{label}<span className="ch-val">{val}{unit}</span></label>
      <input type="range" min={min} max={max} step={step} value={val} onChange={e=>onChange(+e.target.value)}/>
    </div>
  );
}

function ChaosConsole({ conn }){
  useBusTick();
  const M = window.JarvisMock;
  const c = M.chaos;
  const live = conn==='live';
  return (
    <div className="ch-wrap">
      {live && <div className="ch-note"><Icn d={IKn.egress} size={13}/> LIVE transport hits the real backend — chaos shapes the <b>DEMO</b> mock. Switch DATA to DEMO to drive these.</div>}
      <div className="ch-grid">
        <Slider label="latency" val={c.latencyMs} min={0} max={3000} step={20} unit="ms" onChange={v=>M.setChaos({latencyMs:v})}/>
        <Slider label="jitter" val={c.jitterMs} min={0} max={1500} step={20} unit="ms" onChange={v=>M.setChaos({jitterMs:v})}/>
        <Slider label="error rate" val={Math.round(c.errorRate*100)} min={0} max={100} step={5} unit="%" onChange={v=>M.setChaos({errorRate:v/100})}/>
        <Slider label="drop rate" val={Math.round(c.dropRate*100)} min={0} max={100} step={5} unit="%" onChange={v=>M.setChaos({dropRate:v/100})}/>
        <Slider label="auto-arrivals" val={c.arrivalSec} min={0} max={30} step={1} unit={c.arrivalSec?'s':' off'} onChange={v=>M.setChaos({arrivalSec:v})}/>
      </div>
      <div className="ch-actions">
        <button className="da-btn" onClick={()=>M.pushArrival()}><Icn d={IKn.plus} size={12}/> Inject arrival</button>
        <button className="da-btn" onClick={()=>M.pushMission&&M.pushMission()}><Icn d={IKn.missions} size={12}/> Inject mission</button>
        <button className="da-btn" onClick={()=>{ for(let i=0;i<5;i++) M.pushArrival(); }}>Burst ×5</button>
        <button className="da-btn" onClick={()=>{ const o=M.chaos.errorRate; M.setChaos({errorRate:1}); setTimeout(()=>M.setChaos({errorRate:o}),6000); }}>Force 5xx · 6s</button>
        <button className="da-btn" onClick={()=>{ const o=M.chaos.dropRate; M.setChaos({dropRate:1}); setTimeout(()=>M.setChaos({dropRate:o}),5000); }}>Sever · 5s</button>
        <button className="da-btn ghost" onClick={()=>M.reset()}>Reset queue</button>
      </div>
      <div className="ch-presets">
        <span className="ch-pl">presets</span>
        <button className="ch-chip" onClick={()=>M.setChaos({latencyMs:120,jitterMs:60,errorRate:0,dropRate:0})}>fast LAN</button>
        <button className="ch-chip" onClick={()=>M.setChaos({latencyMs:650,jitterMs:500,errorRate:0.05,dropRate:0})}>3G mobile</button>
        <button className="ch-chip" onClick={()=>M.setChaos({latencyMs:1400,jitterMs:900,errorRate:0.2,dropRate:0.08})}>brownout</button>
        <button className="ch-chip" onClick={()=>M.setChaos({latencyMs:280,jitterMs:220,errorRate:0,dropRate:0,arrivalSec:0})}>reset chaos</button>
      </div>
    </div>
  );
}

function NetPanel({ open, onClose, conn }){
  const [tab,setTab]=uSn('inspector');
  uEn(()=>{ const h=e=>{ if(e.key==='Escape'&&open) onClose(); }; window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h); },[open,onClose]);
  if(!open) return null;
  return (
    <div className="netpanel" role="dialog" aria-modal="true" aria-label="Data layer inspector">
      <div className="np-head">
        <span className="np-title"><Icn d={IKn.flow} size={14}/> DATA LAYER</span>
        <div className="np-tabs">
          <button className={'np-tab'+(tab==='inspector'?' on':'')} onClick={()=>setTab('inspector')}>Network</button>
          <button className={'np-tab'+(tab==='chaos'?' on':'')} onClick={()=>setTab('chaos')}>Chaos</button>
        </div>
        <span className={'np-conn '+conn}>{conn.toUpperCase()}</span>
        <button className="np-close" aria-label="Close" onClick={onClose}><Icn d={IKn.x} size={15}/></button>
      </div>
      <div className="np-body">
        {tab==='inspector' ? <NetInspector/> : <ChaosConsole conn={conn}/>}
      </div>
    </div>
  );
}

Object.assign(window, { TelemetryStrip, NetPanel, NetInspector, ChaosConsole });
