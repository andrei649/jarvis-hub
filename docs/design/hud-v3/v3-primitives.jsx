'use strict';
/* HUD v2 · PRIMITIVES — icons, glyph, hooks */
const { useState, useEffect, useRef, useCallback, useMemo } = React;

/* ---- line icons (stroke, currentColor) ---- */
function Icon({ d, size, sw }) {
  return (
    <svg width={size||16} height={size||16} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={sw||1.6} strokeLinecap="round" strokeLinejoin="round">
      {d}
    </svg>
  );
}
const ICONS = {
  cockpit:<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></>,
  agents:<><circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2"/><path d="M16 20a5 5 0 0 1 5-2"/></>,
  trust:<><path d="M12 3l8 4v5c0 4.4-3 7.6-8 9-5-1.4-8-4.6-8-9V7z"/><path d="M9 12l2 2 4-4"/></>,
  memory:<><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16M4 9h5M4 15h5"/></>,
  autonomy:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  build:<><path d="M3 21l4-1 10-10-3-3L4 17z"/><path d="M14 7l3 3"/></>,
  observe:<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/></>,
  interop:<><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7l3 9M16 7l-3 9"/></>,
  admin:<><circle cx="12" cy="12" r="3"/><path d="M12 2l2 3 3.5-1 .5 3.5 3 2-2 3 1 3.5-3.5.5-2 3-3-2-3 2-2-3-3.5-.5 1-3.5-2-3 3-2 .5-3.5L10 5z"/></>,
  send:<><path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/></>,
  mic:<><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></>,
  search:<><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></>,
  ambient:<><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></>,
  globe:<><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"/></>,
  link:<><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7l3 9M16 7l-3 9"/></>,
  bolt:<><path d="M13 2L4 14h6l-1 8 9-12h-6z"/></>,
  shield:<><path d="M12 3l8 4v5c0 4.4-3 7.6-8 9-5-1.4-8-4.6-8-9V7z"/></>,
  brain:<><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5 3 3 0 0 0 1 5 3 3 0 0 0 6 0V4a3 3 0 0 0-3 0z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5 3 3 0 0 1-1 5 3 3 0 0 1-6 0"/></>,
  chat:<><path d="M4 5h16v11H8l-4 4z"/><path d="M8 9h8M8 12h5"/></>,
  comms:<><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></>,
  finance:<><path d="M3 17l5-5 4 3 6-7"/><path d="M16 8h3v3"/></>,
  health:<><path d="M3 12h4l2 5 3-11 2 6h5"/></>,
  knowledge:<><path d="M4 5a2 2 0 0 1 2-2h6v16H6a2 2 0 0 0-2 2z"/><path d="M20 5a2 2 0 0 0-2-2h-6v16h6a2 2 0 0 1 2 2z"/></>,
  family:<><circle cx="8" cy="8" r="2.4"/><circle cx="16" cy="9" r="2"/><path d="M3.5 19a4.5 4.5 0 0 1 9 0M13 19a4 4 0 0 1 7.5-2"/></>,
  decisions:<><path d="M4 5h16v14H4z"/><path d="M8 11l2.5 2.5L16 8"/></>,
  missions:<><path d="M5 3v18"/><path d="M5 4h11l-2 3 2 3H5"/></>,
  mesh:<><circle cx="12" cy="5" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="M12 7v4M12 11l-5.5 5M12 11l5.5 5"/></>,
  life:<><path d="M12 21s-7-4.6-9.2-9C1.3 9 3 5.5 6.2 5.5c2 0 3.2 1.3 3.8 2.3.6-1 1.8-2.3 3.8-2.3 3.2 0 4.9 3.5 3.4 6.5C19 16.4 12 21 12 21z"/></>,
  note:<><path d="M5 3h14v18l-7-3-7 3z"/><path d="M9 8h6M9 12h4"/></>,
  device:<><rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/></>,
  egress:<><circle cx="12" cy="12" r="9"/><path d="M8 12h8M13 9l3 3-3 3"/></>,
  lock:<><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></>,
  flow:<><path d="M3 6h6M3 12h12M3 18h8"/><circle cx="17" cy="6" r="2"/><circle cx="19" cy="18" r="2"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></>,
  thumbUp:<><path d="M7 10v9H4v-9z"/><path d="M7 10l3.5-6.5a1.8 1.8 0 0 1 1.8 1.8V8h4.7a1.8 1.8 0 0 1 1.8 2.1l-1.1 6.1A1.8 1.8 0 0 1 16 19H7"/></>,
  thumbDown:<><path d="M17 14V5h3v9z"/><path d="M17 14l-3.5 6.5a1.8 1.8 0 0 1-1.8-1.8V16H7a1.8 1.8 0 0 1-1.8-2.1l1.1-6.1A1.8 1.8 0 0 1 8 5h9"/></>,
  mic2:<><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></>,
  image:<><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 16l-5-5L5 20"/></>,
  plus:<><path d="M12 5v14M5 12h14"/></>,
  pause:<><path d="M9 5v14M15 5v14"/></>,
  play:<><path d="M7 4l13 8-13 8z"/></>,
  data:<><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></>,
  check:<><path d="M5 12l5 5L20 7"/></>,
  x:<><path d="M6 6l12 12M18 6L6 18"/></>,
};

/* dossier glyph */
function Glyph({ id, size }) {
  const d = (window.V2 && window.V2.GLYPHS[id]) || '';
  const s = size || 16;
  return (
    <svg width={s} height={s} viewBox="-10 -10 20 20" className="gx-svg">
      <path d={d} className="net-glyph" stroke="currentColor" />
    </svg>
  );
}

function statusClass(s){ return s==='active'?'active':s==='busy'?'busy':s==='err'?'err':'idle'; }

/* clock */
function useClock(){
  const [t,setT]=useState(new Date());
  useEffect(()=>{ const i=setInterval(()=>setT(new Date()),1000); return ()=>clearInterval(i); },[]);
  return t;
}
const pad=n=>String(n).padStart(2,'0');
function fmtTime(d){ return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function fmtTimeShort(d){ return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function fmtDate(d,lang){
  const days = lang==='ro' ? ['DUM','LUN','MAR','MIE','JOI','VIN','SÂM'] : ['SUN','MON','TUE','WED','THU','FRI','SAT'];
  const mon = lang==='ro' ? ['IAN','FEB','MAR','APR','MAI','IUN','IUL','AUG','SEP','OCT','NOI','DEC']
                          : ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  return `${days[d.getDay()]} ${pad(d.getDate())} ${mon[d.getMonth()]} ${d.getFullYear()}`;
}

/* Meter */
function Meter({ label, val, unit }){
  return (
    <div className="meter">
      <div className="ml"><span>{label}</span><span>{val}{unit||'%'}</span></div>
      <div className="mt"><div className="mf" style={{width:`${Math.min(100,val)}%`}}></div></div>
    </div>
  );
}

/* reactor logo */
function Reactor(){
  return (
    <svg className="reactor" viewBox="-16 -16 32 32" fill="none" stroke="currentColor">
      <circle className="ambient-anim spin1" r="13" strokeWidth="1" strokeDasharray="4 3" opacity=".5"/>
      <circle className="ambient-anim spin2" r="9" strokeWidth="1.4" strokeDasharray="2 4"/>
      <circle r="4.5" strokeWidth="1.6"/>
      <circle r="1.6" fill="currentColor" stroke="none"/>
    </svg>
  );
}

Object.assign(window, { Icon, ICONS, Glyph, statusClass, useClock, fmtTime, fmtTimeShort, fmtDate, Meter, Reactor });
