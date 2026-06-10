'use strict';
/* HUD v2 · NETWORK BRAIN — signature visualizer
   nodes orbit a core; collab edges; live packets; click=focus */
const { useState, useEffect, useRef, useMemo } = React;

function NetworkBrain({ agents, activeId, onSelect, focusId, setFocusId, motion, t }) {
  const W = 640, H = 460, CX = W/2, CY = H/2;
  const [hover, setHover] = useState(null);
  const [tip, setTip] = useState(null);
  const [tick, setTick] = useState(0);

  // layout: 4 tiers on concentric rings
  const layout = useMemo(() => {
    const tiers = { CNS:[], BIZ:[], SEC:[], FND:[] };
    agents.forEach(a => (tiers[a.tier] || tiers.FND).push(a));
    const rings = { CNS:84, BIZ:150, SEC:150, FND:210 };
    const pos = {};
    // CNS ring
    const place = (list, r, startDeg) => list.forEach((a,i) => {
      const ang = ((startDeg + i*(360/Math.max(list.length, (list===tiers.CNS?list.length:6)))) * Math.PI)/180;
      pos[a.id] = { x: CX + Math.cos(ang)*r, y: CY + Math.sin(ang)*r, a };
    });
    // distribute: CNS inner full circle; BIZ left arc; SEC right arc; FND outer ring
    tiers.CNS.forEach((a,i)=>{ const ang=(i*(360/tiers.CNS.length)-90)*Math.PI/180; pos[a.id]={x:CX+Math.cos(ang)*rings.CNS, y:CY+Math.sin(ang)*rings.CNS, a}; });
    tiers.BIZ.forEach((a,i)=>{ const ang=(150 + i*(120/Math.max(1,tiers.BIZ.length-1)))*Math.PI/180; pos[a.id]={x:CX+Math.cos(ang)*rings.BIZ, y:CY+Math.sin(ang)*rings.BIZ, a}; });
    tiers.SEC.forEach((a,i)=>{ const ang=(-30 + i*(120/Math.max(1,tiers.SEC.length-1)))*Math.PI/180; pos[a.id]={x:CX+Math.cos(ang)*rings.SEC, y:CY+Math.sin(ang)*rings.SEC, a}; });
    tiers.FND.forEach((a,i)=>{ const ang=(60 + i*(360/tiers.FND.length))*Math.PI/180; pos[a.id]={x:CX+Math.cos(ang)*rings.FND, y:CY+Math.sin(ang)*rings.FND, a}; });
    return pos;
  }, [agents]);

  // collab beziers
  const COLLAB = (window.V2 && window.V2.COLLAB) || [];
  const links = useMemo(() => COLLAB.filter(([a,b]) => layout[a] && layout[b]).map(([a,b]) => {
    const p = layout[a], q = layout[b];
    const mx = (p.x+q.x)/2, my = (p.y+q.y)/2;
    // bow toward center for organic feel
    const cx = mx + (CX-mx)*0.32, cy = my + (CY-my)*0.32;
    return { a, b, d:`M${p.x},${p.y} Q${cx},${cy} ${q.x},${q.y}` };
  }), [layout]);

  // packet animation tick
  useEffect(() => {
    if (motion === 'calm') return;
    const i = setInterval(() => setTick(x => x+1), 60);
    return () => clearInterval(i);
  }, [motion]);

  // which packets are live (a few links pulse)
  const livePackets = useMemo(() => {
    const active = agents.filter(a=>a.status==='active'||a.status==='busy').map(a=>a.id);
    return links.filter(l => active.includes(l.a) || active.includes(l.b)).slice(0,6);
  }, [links, agents]);

  const focused = focusId;
  const neighbors = useMemo(() => {
    if (!focused) return null;
    const set = new Set([focused]);
    links.forEach(l => { if (l.a===focused) set.add(l.b); if (l.b===focused) set.add(l.a); });
    return set;
  }, [focused, links]);

  const dimNode = id => focused && neighbors && !neighbors.has(id);
  const dimLink = l => focused && !(l.a===focused || l.b===focused);

  function hexPath(cx, cy, r){
    let p='';
    for(let i=0;i<6;i++){ const a=(i*60-90)*Math.PI/180; p+=(i?'L':'M')+(cx+Math.cos(a)*r)+','+(cy+Math.sin(a)*r); }
    return p+'Z';
  }

  const activeCount = agents.filter(a=>a.status==='active').length;
  const busyCount = agents.filter(a=>a.status==='busy').length;

  return (
    <div className="net-wrap" ref={el=>{ if(el) NetworkBrain._wrap=el; }}>
      <svg className="net-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
        onMouseLeave={()=>{setHover(null);setTip(null);}}>
        <defs>
          <radialGradient id="coreglow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity=".55"/>
            <stop offset="60%" stopColor="var(--accent)" stopOpacity=".08"/>
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
          </radialGradient>
        </defs>

        {/* rings */}
        {[84,150,210].map(r=>(
          <circle key={r} cx={CX} cy={CY} r={r} fill="none" stroke="var(--panel-line)" strokeWidth=".6" strokeDasharray="1 5"/>
        ))}

        {/* collab links */}
        <g>
          {links.map((l,i)=>(
            <path key={i} d={l.d} className={'net-collab'+(dimLink(l)?' net-dim':'')}/>
          ))}
        </g>

        {/* core glow */}
        <circle cx={CX} cy={CY} r="70" fill="url(#coreglow)" className={focused?'net-dim':''}/>

        {/* spokes from core to CNS + active */}
        <g>
          {agents.map(a=>{
            const p=layout[a.id]; if(!p) return null;
            const isActive = a.status==='active'||a.status==='busy';
            if(a.tier!=='CNS' && !isActive) return null;
            return <line key={a.id} x1={CX} y1={CY} x2={p.x} y2={p.y}
              className={'net-edge'+(isActive&&motion!=='calm'?' flow-edge':'')+(dimNode(a.id)?' net-dim':'')}
              strokeWidth={a.tier==='CNS'?.9:.6} opacity={a.tier==='CNS'?.5:.32}/>;
          })}
        </g>

        {/* live packets */}
        {motion!=='calm' && livePackets.map((l,i)=>{
          const prog = ((tick*1.4 + i*22) % 100)/100;
          // approximate point on quadratic bezier
          const p=layout[l.a], q=layout[l.b];
          const mx=(p.x+q.x)/2, my=(p.y+q.y)/2;
          const cx=mx+(CX-mx)*0.32, cy=my+(CY-my)*0.32;
          const u=1-prog;
          const x=u*u*p.x+2*u*prog*cx+prog*prog*q.x;
          const y=u*u*p.y+2*u*prog*cy+prog*prog*q.y;
          return <circle key={i} className={'pkt'+(dimLink(l)?' net-dim':'')} cx={x} cy={y} r="1.8" opacity={Math.sin(prog*Math.PI)}/>;
        })}

        {/* CORE */}
        <g className="net-core" onClick={()=>setFocusId(null)} style={{cursor:focused?'pointer':'default'}}>
          <circle cx={CX} cy={CY} r="30" fill="var(--void-2)" stroke="var(--accent)" strokeWidth="1.4"/>
          <circle className="ambient-anim" cx={CX} cy={CY} r="30" fill="none" stroke="var(--accent)" strokeWidth=".6" opacity=".4"
            strokeDasharray="3 4" style={{transformOrigin:`${CX}px ${CY}px`, animation:motion==='calm'?'none':'spin 30s linear infinite'}}/>
          <path d={(window.V2.GLYPHS.jarvis)} transform={`translate(${CX},${CY}) scale(1.5)`} className="net-glyph" stroke="var(--accent-light)"/>
          <text className="net-core-label" x={CX} y={CY+46} textAnchor="middle" fontSize="9">JARVIS · CORE</text>
        </g>

        {/* NODES */}
        {agents.map(a=>{
          const p=layout[a.id]; if(!p) return null;
          const cls = ['net-node', a.status==='active'?'active':'', a.status==='busy'?'busy':'', dimNode(a.id)?'net-dim':''].join(' ');
          return (
            <g key={a.id} className={cls} transform={`translate(${p.x},${p.y})`}
              onClick={()=>{ onSelect(a.id); setFocusId(focused===a.id?null:a.id); }}
              onMouseEnter={()=>{ setHover(a.id); setTip({a, x:p.x, y:p.y}); }}>
              <path className="net-hex" d={hexPath(0,0,15)}/>
              <path className="net-glyph" d={(window.V2.GLYPHS[a.id]||'')} transform="scale(.9)"
                stroke={a.status==='active'||activeId===a.id?'var(--accent-light)':a.status==='busy'?'var(--amber)':'var(--ink-3)'}/>
              {(a.status==='active') && <circle r="20" fill="none" stroke="var(--accent)" strokeWidth=".7" opacity=".4" className="ambient-anim" style={{animation:motion==='calm'?'none':'pulse-green 2.6s infinite'}}/>}
              <text className="net-label" y="26" textAnchor="middle">{a.name.toUpperCase()}</text>
            </g>
          );
        })}
      </svg>

      <div className="net-overlay">
        <div className="ol">{t.network} · <b>{agents.length}</b> {t.agents.toLowerCase()}</div>
        <div className="ol"><b>{activeCount}</b> active · <b>{busyCount}</b> busy</div>
      </div>
      {tip && (
        <div className="net-tip" style={tipPos(tip)}>
          <div className="nt-name">{tip.a.name}</div>
          <div className="nt-role">{tip.a.role} · {tip.a.tier}</div>
          <div className="nt-task">{tip.a.status==='active'?'● processing':tip.a.status==='busy'?'◐ working':'○ idle'} · {tip.a.model}</div>
        </div>
      )}
      <div className="net-hint">{t.focusHint}</div>
    </div>
  );
}
function tipPos(tip){
  const W=640,H=460;
  const left = (tip.x/W)*100, top=(tip.y/H)*100;
  return { left:`calc(${left}% + 14px)`, top:`calc(${top}% - 10px)`, transform: left>60?'translateX(-110%)':'none' };
}
window.NetworkBrain = NetworkBrain;
