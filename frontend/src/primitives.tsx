/* HUD v2 · PRIMITIVES — icons, glyph, hooks */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { V2 } from './data';

/* ---- line icons (stroke, currentColor) ---- */
function Icon({ d, size, sw }: { d?: any; size?: any; sw?: any }) {
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
};

/* dossier glyph */
function Glyph({ id, size }) {
  const d = (V2 && V2.GLYPHS[id]) || '';
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

export { Icon, ICONS, Glyph, statusClass, useClock, fmtTime, fmtTimeShort, fmtDate, Meter, Reactor };
