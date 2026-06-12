'use strict';
/* WorldView Redesign — panels: appbar, legend+layers, recon, stats, alerts, inspector, export, timeline, overlays */
const { useState:uPS } = React;
const D = window.WVR;
const Mk = window.WvMark;

const MODE_META = {
  live:       { label:'LIVE',       note:'real feed' },
  demo:       { label:'DEMO',       note:'synthetic data' },
  historical: { label:'HISTORICAL', note:'as of 06:12:30 UTC' },
  replay:     { label:'REPLAY',     note:'05:26 → 06:41 · 60×' },
  offline:    { label:'OFFLINE',    note:'reconnecting…' },
};

function AppBar({ mode, onGoLive, view, setView, onHelp, tourOn, setTour }){
  const m = MODE_META[mode] || MODE_META.live;
  return (
    <div className="appbar">
      <div className="wordmark">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="9" ry="3.6"/><path d="M12 3v18"/>
        </svg>
        <div><div className="wm-t">WORLDVIEW</div><div className="wm-s">4D OSINT · JARVIS HUB</div></div>
      </div>
      <span className="aoi-chip">AOI · STRAIT OF HORMUZ</span>
      <div className="seg" role="group" aria-label="Projection">
        <button className={view==='map'?'on':''} onClick={()=>setView('map')}>2.5D MAP</button>
        <button className={view==='globe'?'on':''} onClick={()=>setView('globe')}>3D GLOBE</button>
      </div>
      <button className="bar-btn" onClick={()=>setTour(!tourOn)} aria-pressed={tourOn}>{tourOn?'■ STOP TOUR':'◈ TOUR AOIs'}</button>
      <div className="bar-spacer"></div>
      <span className={'mode-pill '+mode}><span className="mdot"></span>{m.label}<span style={{fontWeight:400,opacity:.75}}>· {m.note}</span>
        {(mode==='historical'||mode==='replay') && <button className="golive" onClick={onGoLive}>GO LIVE</button>}
      </span>
      <span className="clock">06:41:03<span className="tz">UTC</span></span>
      <span className={'conn '+(mode==='offline'?'closed':mode==='demo'?'open':'open')}>
        <span className="cdot"></span>{mode==='offline'?'DISCONNECTED':'WS OPEN'}</span>
      <button className="bar-btn" onClick={onHelp} aria-label="Keyboard shortcuts">?</button>
    </div>
  );
}

/* Legend + layer toggles, unified (P1-2) */
function LegendPanel({ layers, setLayers }){
  const [open,setOpen]=uPS(true);
  const toggle=id=>setLayers(ls=>ls.includes(id)?ls.filter(x=>x!==id):[...ls,id]);
  return (
    <div className="pnl">
      <div className="pnl-h"><span className="pt">Layers · Legend</span><span className="ps">decode + toggle</span>
        <button className="collapse-btn" onClick={()=>setOpen(!open)} aria-label="Collapse">{open?'▾':'▸'}</button></div>
      {open && <div className="pnl-b">
        {D.layers.map(l=>(
          <div key={l.id}>
            <div className={'lg-row'+(layers.includes(l.id)?'':' off')}>
              <button className={'cb'+(layers.includes(l.id)?' on':'')} onClick={()=>toggle(l.id)} aria-label={'Toggle '+l.label}>{layers.includes(l.id)?'✓':''}</button>
              <svg className="glyph" width="20" height="16" viewBox="-10 -8 20 16"><Mk kind={l.shapes[0].glyph} x={0} y={0}/></svg>
              <div><span className="lname">{l.label}</span> <span className="lsub">{l.sub}</span></div>
              <span className="cnt">{l.count}</span>
            </div>
            {layers.includes(l.id) && l.shapes.length>1 && l.shapes.slice(1).map(s=>(
              <div className="lg-extra" key={s.label}>
                <svg width="20" height="16" viewBox="-10 -8 20 16"><Mk kind={s.glyph} x={0} y={0}/></svg>
                <span className="lsub" style={{fontSize:9,color:'var(--ink-3)'}}>{s.label}</span>
              </div>
            ))}
          </div>
        ))}
        <div className="lg-sep"></div>
        <div className="lg-extra"><svg width="20" height="16"><line x1="2" y1="8" x2="18" y2="8" stroke="#EEF1F5" strokeWidth="1.6" opacity=".8"/></svg><span className="lsub" style={{fontSize:9}}>Selected trail (1h)</span></div>
        <div className="lg-extra"><svg width="20" height="16"><line x1="2" y1="8" x2="18" y2="8" stroke="var(--mk-dark)" strokeWidth="1.4" strokeDasharray="4 3" opacity=".7"/></svg><span className="lsub" style={{fontSize:9}}>Dead-reckoned path</span></div>
      </div>}
    </div>
  );
}

function ReconPanel(){
  return (
    <div className="pnl" style={{maxHeight:230}}>
      <div className="pnl-h"><span className="pt">Recon · next passes</span><span className="ps">24h horizon</span></div>
      <div className="pnl-b">
        {D.recon.map((r,i)=>(
          <div className={'rc-row'+(r.q<0.5?' poor':'')} key={i}>
            <div className="rc-top">
              <span className={'rc-sensor '+r.sensor.toLowerCase()}>{r.sensor}</span>
              <span className="rc-in">in {r.inMin<60?r.inMin+'m':Math.floor(r.inMin/60)+'h '+(r.inMin%60)+'m'}</span>
              <span className="rc-q" style={{color:r.q>=0.7?'var(--green)':'var(--amber)'}}>q {r.q}</span>
            </div>
            <div className="rc-sub">NORAD {r.norad} · {r.aoi.toUpperCase()} {r.sunlit?'· ☀':'· ☾'} {r.note&&'— '+r.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatsPanel({ mode }){
  const off = mode==='offline';
  return (
    <div className="pnl">
      <div className="pnl-h"><span className="pt">On globe</span><span className="ps">{off?'stale 41s':'tick 1s'}</span></div>
      <div className="pnl-b">
        {D.layers.map(l=>(
          <div className="st-row" key={l.id}>
            <svg width="20" height="14" viewBox="-10 -7 20 14"><Mk kind={l.shapes[0].glyph} x={0} y={0}/></svg>
            <span className="st-l">{l.label}</span>
            <span className="st-n" style={off?{color:'var(--ink-4)'}:{}}>{off?'—':l.count}</span>
          </div>
        ))}
        {!off && <div className="darkstrip" role="alert">⚠ 1 dark vessel detected</div>}
      </div>
    </div>
  );
}

function InspectorPanel({ onClose }){
  const I = D.inspector;
  return (
    <div className="pnl" style={{borderColor:'rgba(255,90,82,.3)'}}>
      <div className="pnl-h"><span className="pt" style={{color:'var(--red)'}}>Inspector</span><span className="ps">{I.id}</span>
        <button className="collapse-btn" onClick={onClose} aria-label="Close inspector">✕</button></div>
      <div className="pnl-b">
        <div className="insp-id">
          <span className="insp-glyph"><svg width="14" height="14" viewBox="-7 -7 14 14"><Mk kind="dark" x={0} y={0}/></svg></span>
          <div><div className="insp-name">{I.name}</div><div className="insp-kind">{I.kind}</div></div>
        </div>
        <div style={{marginTop:8}}>
          {I.rows.map(([k,v,cls],i)=>(
            <div className="kv" key={i}><span className="k">{k}</span><span className={'v '+(cls||'')}>{v}</span></div>
          ))}
        </div>
        <div className="prov">
          <div className="prov-t">PROVENANCE · CHAIN OF CUSTODY</div>
          <div className="prov-b">{I.prov}</div>
        </div>
        <div className="insp-acts">
          <button className="pri">TRAIL</button><button>WATCH</button><button>+ CASE</button><button>EXPORT</button>
        </div>
      </div>
    </div>
  );
}

function AlertsPanel({ onLocate }){
  return (
    <div className="pnl" style={{maxHeight:220}}>
      <div className="pnl-h"><span className="pt">Active alerts</span><span className="ps">{D.alerts.length}</span></div>
      <div className="pnl-b">
        {D.alerts.map((a,i)=>(
          <div className="al-row" key={i} onClick={()=>a.locatable&&onLocate()} role="button" tabIndex={0}>
            <span className={'al-sev '+(a.sev==='high'?'high':a.sev==='med'?'med':'low')}></span>
            <div>
              <div className="al-t"><span className={'sevtag '+a.sev}>{a.sev.toUpperCase()}</span>{a.t}</div>
              <div className="al-m"><span>{a.m}</span><span>{a.ts}</span>{a.locatable&&<span className="al-loc">LOCATE →</span>}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExportPanel(){
  const [open,setOpen]=uPS(false);
  return (
    <div className="pnl">
      <div className="pnl-h"><span className="pt">Export</span><span className="ps">GeoJSON · brief</span>
        <button className="collapse-btn" onClick={()=>setOpen(!open)} aria-label="Toggle export">{open?'▾':'▸'}</button></div>
      {open && <div className="pnl-b">
        <button className="exp-main">⬇ CURRENT VIEW · GEOJSON</button>
        <div className="exp-row"><input placeholder="case id…" aria-label="Case id"/><button>BRIEF</button><button>GEO</button></div>
        <div className="exp-row"><input placeholder="reconstruction id…" aria-label="Reconstruction id"/><button>GEO</button><button>JSON</button></div>
        <div className="exp-recents">recent: <span>case-7</span><span>recon-12</span></div>
      </div>}
    </div>
  );
}

function Timeline({ mode, onScrub, onGoLive }){
  const live = mode==='live'||mode==='demo';
  const headPct = mode==='replay'?64:live?97:71;
  return (
    <div className="timeline">
      <div className="tl-r1">
        <button className="tp-btn" aria-label="Play/pause">{live||mode==='replay'?'⏸':'▶'}</button>
        <button className={'live-btn '+(live?'on':'off')} onClick={onGoLive}>● LIVE</button>
        <span className="tl-clock">{mode==='historical'?'06:12:30':mode==='replay'?'05:53:12':'06:41:03'} <span style={{fontSize:9,color:'var(--ink-3)'}}>UTC</span></span>
        <span className="tl-mode-note">
          {mode==='historical'&&'VIEWING THE PAST — world state as of this moment'}
          {mode==='replay'&&'REPLAY 05:26→06:41 · deterministic · 36%'}
          {(mode==='live')&&'master clock · all layers in lockstep'}
          {(mode==='demo')&&'master clock · synthetic feed'}
          {mode==='offline'&&'last data 06:40:22 — clock paused'}
        </span>
        <div className="bar-spacer"></div>
        {mode==='replay'
          ? <span className="replay-chip">REPLAY WINDOW 05:26 → 06:41 · 60× <button>🔗 COPY LINK</button><button>■ STOP</button></span>
          : <span className="replay-chip" style={{opacity:.75}}>SET REPLAY WINDOW <button>⧉</button></span>}
        <select className="spd" aria-label="Playback speed"><option>1×</option><option>10×</option><option>60×</option><option>300×</option></select>
      </div>
      <div className="scrub" onClick={onScrub} role="slider" aria-label="24 hour timeline" aria-valuenow={headPct}>
        <div className="scrub-track"></div>
        <div className="scrub-fill" style={{left:0,width:headPct+'%'}}></div>
        {mode==='replay'&&<div className="replay-win" style={{left:'52%',width:'23%'}}></div>}
        {D.events.map((e,i)=>(<div key={i} className={'evmark '+e.kind} style={{left:e.pct+'%'}} title={e.label}></div>))}
        <div className="scrub-head" style={{left:headPct+'%'}}></div>
        {['-24h','-18h','-12h','-6h','now'].map((t,i)=>(<span key={t} className="tick" style={{left:(i*25)+'%'}}>{t}</span>))}
      </div>
    </div>
  );
}

/* First-run / API-down overlay (P1-1) */
function FirstRun({ onRetry }){
  return (
    <div className="overlay">
      <div className="ov-card">
        <div className="ov-glyph"><svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3">
          <circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="9" ry="3.6"/><path d="M12 3v18"/></svg></div>
        <div className="ov-t">WorldView is up — its data feed isn't.</div>
        <div className="ov-s">This screen fuses live aircraft, vessels, satellites, GPS-jamming and intel onto one time-scrubbable map. Right now the API at <code style={{color:'var(--signal-light)'}}>localhost:4000</code> isn't answering, so the globe is empty.</div>
        <div className="ov-step"><span className="ov-n">1</span><div><div className="ov-st">Start the backend</div><div className="ov-sc"><code>START.bat</code> — boots the API + a synthetic Hormuz demo feed</div></div></div>
        <div className="ov-step"><span className="ov-n">2</span><div><div className="ov-st">Or point at a running API</div><div className="ov-sc">set <code>NEXT_PUBLIC_API_URL</code> and reload</div></div></div>
        <div className="ov-step"><span className="ov-n">3</span><div><div className="ov-st">Then take the tour</div><div className="ov-sc">press <code>?</code> for shortcuts · ◈ TOUR flies the camera between AOIs</div></div></div>
        <div className="ov-foot">◐ The demo feed is synthetic — WorldView will badge it. It never passes demo data as real.
          <button className="bar-btn ov-retry" onClick={onRetry}>RETRY ⟳</button></div>
      </div>
    </div>
  );
}

function HelpOverlay({ onClose }){
  return (
    <div className="overlay" onClick={onClose}>
      <div className="ov-card" onClick={e=>e.stopPropagation()}>
        <div className="ov-t">Keyboard</div>
        <div className="help-grid">
          {D.shortcuts.map(([k,l])=>(
            <div className="hk-row" key={k}><span className="hk-l">{l}</span><span className="kbd">{k}</span></div>
          ))}
        </div>
        <div style={{marginTop:16,fontSize:11,color:'var(--ink-3)'}}>Esc or click anywhere to close.</div>
      </div>
    </div>
  );
}

/* Arrival moment — landing from a JARVIS/Argus alert deep link (brief §1, journey 3) */
function ArrivalBanner({ onDismiss }){
  return (
    <div className="arrive" role="status">
      <span className="agen">◈ ARGUS · VIA JARVIS DIGEST</span>
      <span className="atxt">Dark vessel — MMSI 244660000 · Musandam geofence</span>
      <span className="atime">window 05:26 → 06:41 pre-set</span>
      <button className="pri">▶ REPLAY THE GAP</button>
      <button onClick={onDismiss}>DISMISS</button>
    </div>
  );
}

/* Demo lens — the one restrained cinematic treatment (brief §7), tour/demo only */
function DemoLens({ onOff }){
  return (<>
    <div className="lens"></div>
    <div className="lens-chip">LENS · MONO GRADE<button onClick={onOff}>✕ OFF</button></div>
  </>);
}

Object.assign(window,{ AppBar, LegendPanel, ReconPanel, StatsPanel, InspectorPanel, AlertsPanel, ExportPanel, Timeline, FirstRun, HelpOverlay, ArrivalBanner, DemoLens });
