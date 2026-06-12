'use strict';
/* WorldView Redesign — map canvas (SVG mock of deck.gl scene over Strait of Hormuz)
   Demonstrates the redesigned encodings: shape+color redundancy per layer (spec §3). */
const { useMemo:uMM } = React;

/* marker glyphs (shape redundancy — never color alone) */
function Mark({ kind, x, y, sel }){
  const C = {
    civil:'var(--mk-civil)', mil:'var(--mk-mil)', vessel:'var(--mk-vessel)',
    dark:'var(--mk-dark)', sat:'var(--mk-sat)', intel:'var(--mk-intel)',
  }[kind];
  const g = (()=>{ switch(kind){
    case 'civil': return <path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill={C}/>;                         // chevron
    case 'mil':   return <path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill="none" stroke={C} strokeWidth="1.5"/>; // hollow chevron
    case 'vessel':return <rect x="-3.6" y="-3.6" width="7.2" height="7.2" transform="rotate(45)" fill={C}/>; // diamond
    case 'dark':  return <g><circle r="5" fill="none" stroke={C} strokeWidth="1.8"/><circle r="1.6" fill={C}/>
                    <circle r="9" fill="none" stroke={C} strokeWidth="1" opacity=".5">
                      <animate attributeName="r" values="5;13" dur="2s" repeatCount="indefinite"/>
                      <animate attributeName="opacity" values=".6;0" dur="2s" repeatCount="indefinite"/>
                    </circle></g>;                                                                  // pulsing ring
    case 'sat':   return <g><circle r="3" fill={C}/><circle r="6" fill="none" stroke={C} strokeWidth=".8" opacity=".6"/></g>; // ringed dot
    case 'intel': return <rect x="-3.4" y="-3.4" width="6.8" height="6.8" fill={C} opacity=".9"/>;  // square
    default: return null;
  }})();
  return <g transform={`translate(${x},${y})`}>{sel && <circle r="11" fill="none" stroke="var(--ink)" strokeWidth="1" strokeDasharray="2 3"/>}{g}</g>;
}

function MapCanvas({ layers, selected, mode }){
  const on = id => layers.includes(id);
  const hexes = uMM(()=>{ // jamming H3 cluster near Qeshm
    const cells=[]; const cx=560, cy=395;
    const pos=[[0,0],[34,0],[17,28],[-17,28],[51,28],[34,56],[0,56],[68,0],[-17,-28],[17,-28]];
    pos.forEach((p,i)=>cells.push({ x:cx+p[0], y:cy+p[1], i:[0.82,0.7,0.61,0.5,0.44,0.38,0.3,0.26,0.5,0.34][i] }));
    return cells;
  },[]);
  const hexPath = (x,y,r=19)=>{ let d=''; for(let k=0;k<6;k++){ const a=Math.PI/3*k+Math.PI/6; d+=(k?'L':'M')+(x+r*Math.cos(a)).toFixed(1)+','+(y+r*Math.sin(a)).toFixed(1);} return d+'Z'; };

  return (
    <svg viewBox="0 0 1600 880" preserveAspectRatio="xMidYMid slice" style={{width:'100%',height:'100%',display:'block',background:'#04070E'}}>
      <defs>
        <radialGradient id="oceanG" cx="48%" cy="46%" r="75%">
          <stop offset="0%" stopColor="#081220"/><stop offset="100%" stopColor="#04070E"/>
        </radialGradient>
        <linearGradient id="trailG" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#EEF1F5" stopOpacity="0"/><stop offset="100%" stopColor="#EEF1F5" stopOpacity=".85"/>
        </linearGradient>
      </defs>
      <rect width="1600" height="880" fill="url(#oceanG)"/>
      {/* graticule with coordinate labels (P3 fix) */}
      {[0,1,2,3,4].map(i=>(<g key={'gv'+i}>
        <line x1={200+i*300} y1="0" x2={200+i*300} y2="880" stroke="rgba(139,196,240,.07)" strokeWidth="1"/>
        <text x={206+i*300} y="872" fontFamily="JetBrains Mono" fontSize="9" fill="rgba(238,241,245,.22)">{54+i*2}°E</text>
      </g>))}
      {[0,1,2].map(i=>(<g key={'gh'+i}>
        <line x1="0" y1={180+i*260} x2="1600" y2={180+i*260} stroke="rgba(139,196,240,.07)" strokeWidth="1"/>
        <text x="8" y={176+i*260} fontFamily="JetBrains Mono" fontSize="9" fill="rgba(238,241,245,.22)">{28-i*2}°N</text>
      </g>))}
      {/* land — Iran (N) */}
      <path d="M0,0 H1600 V178 C1460,196 1372,262 1218,276 C1080,288 992,222 858,238 C724,254 608,196 478,222 C338,250 128,210 0,238 Z"
        fill="#0A1322" stroke="rgba(139,196,240,.22)" strokeWidth="1.2"/>
      <text x="700" y="120" fontFamily="JetBrains Mono" fontSize="10" letterSpacing="4" fill="rgba(238,241,245,.25)">IRAN</text>
      {/* land — Arabian peninsula + Musandam (S) */}
      <path d="M0,880 V600 C150,572 296,596 392,636 C470,668 540,720 648,710 C716,704 742,652 728,592 C718,548 696,524 716,488 C730,462 766,470 786,506 C802,536 800,580 836,606 C920,664 1080,690 1240,720 C1380,746 1520,752 1600,748 V880 Z"
        fill="#0A1322" stroke="rgba(139,196,240,.22)" strokeWidth="1.2"/>
      <text x="300" y="790" fontFamily="JetBrains Mono" fontSize="10" letterSpacing="4" fill="rgba(238,241,245,.25)">U.A.E. · OMAN</text>
      <text x="746" y="478" fontFamily="JetBrains Mono" fontSize="8" letterSpacing="2" fill="rgba(238,241,245,.3)">MUSANDAM</text>
      {/* AOI geofence */}
      <path d="M520,300 L1060,330 L1100,560 L760,640 L520,520 Z" fill="none" stroke="rgba(43,184,240,.3)" strokeWidth="1" strokeDasharray="6 5"/>
      <text x="530" y="292" fontFamily="JetBrains Mono" fontSize="8.5" letterSpacing="2" fill="rgba(43,184,240,.55)">AOI · STRAIT OF HORMUZ</text>

      {/* EW jamming hexes */}
      {on('ew') && hexes.map((h,i)=>(
        <path key={i} d={hexPath(h.x,h.y)} fill={`rgba(255,${Math.round(180*(1-h.i))+40},40,${0.12+h.i*0.3})`}
          stroke="rgba(255,140,40,.55)" strokeWidth=".8"/>
      ))}
      {on('ew') && <text x="505" y="340" fontFamily="JetBrains Mono" fontSize="8" fill="rgba(255,140,40,.8)">JAM 0.82</text>}

      {/* satellite footprint */}
      {on('tle') && <>
        <ellipse cx="930" cy="430" rx="300" ry="170" fill="rgba(232,210,122,.07)" stroke="rgba(232,210,122,.45)" strokeWidth="1" strokeDasharray="3 4"/>
        <line x1="1180" y1="150" x2="1010" y2="320" stroke="rgba(232,210,122,.35)" strokeWidth=".8" strokeDasharray="2 4"/>
        <Mark kind="sat" x={1180} y={150}/>
        <text x="1196" y="148" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-sat)">NORAD 43437 · SAR</text>
        <text x="1196" y="162" fontFamily="JetBrains Mono" fontSize="8" fill="rgba(238,241,245,.4)">7.61 km/s · footprint ↓</text>
      </>}

      {/* intel: NOTAM zone + strike event */}
      {on('context') && <>
        <path d="M1150,360 L1330,346 L1368,470 L1210,500 Z" fill="rgba(167,139,250,.1)" stroke="rgba(167,139,250,.6)" strokeWidth="1.1"/>
        <text x="1186" y="420" fontFamily="JetBrains Mono" fontSize="8.5" fill="var(--mk-intel)">NOTAM A0142/26</text>
        <Mark kind="intel" x={1262} y={560}/>
        <text x="1276" y="556" fontFamily="JetBrains Mono" fontSize="8.5" fill="var(--mk-intel)">strike · sev 0.74</text>
      </>}

      {/* aircraft + trails */}
      {on('adsb') && <>
        <path d="M260,420 C360,402 440,388 520,372" stroke="url(#trailG)" strokeWidth="1.6" fill="none"/>
        <Mark kind="civil" x={524} y={371}/>
        <text x="538" y="368" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-civil)">UAE12 · FL350 · 480kt</text>
        <path d="M1030,290 C1010,330 1018,370 1052,392 C1086,412 1124,398 1136,362" stroke="rgba(255,178,63,.35)" strokeWidth="1.2" fill="none" strokeDasharray="4 4"/>
        <Mark kind="mil" x={1137} y={358}/>
        <text x="1151" y="356" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-mil)">RQ-4 ⚑ MIL · orbit</text>
      </>}

      {/* vessels */}
      {on('ais') && <>
        <Mark kind="vessel" x={880} y={520}/>
        <text x="894" y="518" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-vessel)">VLCC · 14.2kt</text>
        <Mark kind="vessel" x={988} y={478}/>
        <Mark kind="vessel" x={700} y={580}/>
        {/* NEGATIVE SPACE — the dark vessel story rendered as evidence (brief §7):
            solid past trail → gap marker at signal loss → ghost ring at last fix → dashed dead-reckoned cone */}
        <path d="M860,640 C842,612 824,584 806,560" stroke="rgba(95,224,176,.5)" strokeWidth="1.4" fill="none"/>
        <g transform="translate(806,560)">
          <circle r="7" fill="none" stroke="rgba(255,90,82,.7)" strokeWidth="1.2" strokeDasharray="2 2"/>
          <path d="M-3,-3 L3,3 M3,-3 L-3,3" stroke="rgba(255,90,82,.85)" strokeWidth="1.2"/>
        </g>
        <text x="818" y="566" fontFamily="JetBrains Mono" fontSize="8" fill="rgba(255,90,82,.7)">signal lost 05:41</text>
        <path d="M806,560 C792,540 782,522 776,502" stroke="rgba(255,90,82,.55)" strokeWidth="1.4" fill="none" strokeDasharray="5 4"/>
        <path d="M806,560 L760,496 L792,489 Z" fill="rgba(255,90,82,.05)" stroke="rgba(255,90,82,.18)" strokeWidth=".6"/>
        <Mark kind="dark" x={775} y={499} sel={selected}/>
        <text x="752" y="484" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-dark)" textAnchor="end">MMSI 244660000 · DR ±2.1nm</text>
      </>}

      {/* NEGATIVE SPACE — voided airspace: absence rendered, not blank (brief §7) */}
      {on('context') && <>
        <path d="M1150,360 L1330,346 L1368,470 L1210,500 Z" fill="none" stroke="rgba(238,241,245,.14)" strokeWidth=".8" strokeDasharray="2 5"/>
        {[[1208,392],[1262,378],[1300,430],[1240,452],[1330,398]].map((p,i)=>(
          <path key={'gh'+i} d="M0,-4 L3.2,3.2 L0,1.3 L-3.2,3.2 Z" transform={`translate(${p[0]},${p[1]})`}
            fill="none" stroke="rgba(127,180,232,.28)" strokeWidth=".8" strokeDasharray="1.5 1.5"/>
        ))}
        <text x="1196" y="372" fontFamily="JetBrains Mono" fontSize="8" fill="rgba(238,241,245,.45)">AIRSPACE VOIDED — 14 TRACKS DEPARTED IN 22M</text>
      </>}
    </svg>
  );
}
/* ---------- 3D GLOBE view (journey 6 — the demo moment; no Mapbox here, the dark earth is ours) ---------- */
function GlobeCanvas({ layers, selected, tour }){
  const on = id => layers.includes(id);
  const CX=800, CY=470, R=330;
  return (
    <svg viewBox="0 0 1600 880" preserveAspectRatio="xMidYMid slice" style={{width:'100%',height:'100%',display:'block',background:'#04070E'}}>
      <defs>
        <radialGradient id="gSphere" cx="38%" cy="32%" r="78%">
          <stop offset="0%" stopColor="#0C1A2E"/><stop offset="55%" stopColor="#071120"/><stop offset="100%" stopColor="#04070E"/>
        </radialGradient>
        <radialGradient id="gAtmo" cx="50%" cy="50%" r="50%">
          <stop offset="78%" stopColor="rgba(43,184,240,0)"/><stop offset="92%" stopColor="rgba(43,184,240,.14)"/><stop offset="100%" stopColor="rgba(43,184,240,0)"/>
        </radialGradient>
        <linearGradient id="gTerm" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="rgba(2,4,9,.78)"/><stop offset="55%" stopColor="rgba(2,4,9,.55)"/><stop offset="100%" stopColor="rgba(2,4,9,0)"/>
        </linearGradient>
        <clipPath id="gClip"><circle cx={CX} cy={CY} r={R}/></clipPath>
      </defs>
      {/* starfield */}
      {[...Array(90)].map((_,i)=><circle key={i} cx={(i*199+57)%1600} cy={(i*113+23)%880} r={(i%4)*0.4+0.3} fill="#8FE0FF" opacity={0.06+(i%5)*0.045}/>)}
      {/* atmosphere + sphere */}
      <circle cx={CX} cy={CY} r={R+40} fill="url(#gAtmo)"/>
      <circle cx={CX} cy={CY} r={R} fill="url(#gSphere)" stroke="rgba(139,196,240,.3)" strokeWidth="1.2"/>
      {/* graticule */}
      <g clipPath="url(#gClip)" opacity=".5">
        {[-2,-1,0,1,2].map(i=><ellipse key={'p'+i} cx={CX} cy={CY+i*92} rx={Math.sqrt(Math.max(R*R-(i*92)*(i*92),0))} ry={Math.sqrt(Math.max(R*R-(i*92)*(i*92),0))*0.26} fill="none" stroke="rgba(90,130,170,.22)" strokeWidth=".7"/>)}
        {[0.18,0.45,0.72,1].map((f,i)=><ellipse key={'m'+i} cx={CX} cy={CY} rx={R*f} ry={R} fill="none" stroke="rgba(90,130,170,.22)" strokeWidth=".7"/>)}
        <line x1={CX-R} y1={CY} x2={CX+R} y2={CY} stroke="rgba(90,130,170,.28)" strokeWidth=".7"/>
      </g>
      {/* landmasses — abstract dark-earth around the gulf, lit by data not basemaps */}
      <g clipPath="url(#gClip)">
        {/* Africa / Horn */}
        <path d="M560,560 C600,500 660,480 700,510 C740,540 720,610 750,660 C770,700 740,760 690,780 C620,805 560,740 545,670 C535,620 540,590 560,560 Z" fill="#0B1424" stroke="rgba(139,196,240,.18)" strokeWidth="1"/>
        {/* Arabian peninsula */}
        <path d="M700,470 C740,430 800,420 850,445 C895,468 905,510 940,520 C965,527 980,505 975,478 L1010,560 C980,610 920,640 860,625 C790,608 720,560 700,520 Z" fill="#0C1626" stroke="rgba(139,196,240,.22)" strokeWidth="1"/>
        {/* Iran / Asia */}
        <path d="M760,300 C840,260 950,260 1030,300 C1090,330 1110,380 1080,420 C1050,458 990,450 950,470 C930,480 920,500 940,518 C905,512 893,470 850,447 C800,420 740,430 700,468 C690,420 710,330 760,300 Z" fill="#0C1626" stroke="rgba(139,196,240,.22)" strokeWidth="1"/>
        {/* India edge at limb */}
        <path d="M1090,440 C1110,480 1105,560 1085,620 C1070,660 1050,690 1040,720 L1115,690 C1126,600 1128,500 1118,430 Z" fill="#0B1424" stroke="rgba(139,196,240,.16)" strokeWidth="1"/>
        {/* day/night terminator */}
        <rect x={CX-R} y={CY-R} width={R*1.16} height={R*2} fill="url(#gTerm)"/>
      </g>
      {/* AOI + data over the gulf */}
      {on('context') && <>
        <circle cx="952" cy="505" r="34" fill="none" stroke="rgba(43,184,240,.5)" strokeWidth="1" strokeDasharray="4 4"/>
        <text x="996" y="498" fontFamily="JetBrains Mono" fontSize="9" letterSpacing="1.5" fill="rgba(43,184,240,.8)">AOI · HORMUZ</text>
      </>}
      {on('ew') && <circle cx="930" cy="492" r="9" fill="rgba(255,140,40,.3)" stroke="rgba(255,140,40,.6)" strokeWidth=".8"/>}
      {on('ais') && <>
        <Mark kind="vessel" x={962} y={516}/>
        <Mark kind="dark" x={946} y={503} sel={selected}/>
      </>}
      {on('adsb') && <Mark kind="civil" x={905} y={478}/>}
      {/* satellite orbits */}
      {on('tle') && <>
        <ellipse cx={CX} cy={CY} rx={R+92} ry={(R+92)*0.42} fill="none" stroke="rgba(232,210,122,.35)" strokeWidth="1" strokeDasharray="2 6" transform={`rotate(-24 ${CX} ${CY})`}/>
        <ellipse cx={CX} cy={CY} rx={R+150} ry={(R+150)*0.34} fill="none" stroke="rgba(139,196,240,.18)" strokeWidth=".8" strokeDasharray="1 7" transform={`rotate(18 ${CX} ${CY})`}/>
        <Mark kind="sat" x={1158} y={290}/>
        <path d={`M1158,296 L968,492`} stroke="rgba(232,210,122,.4)" strokeWidth=".8" strokeDasharray="3 4"/>
        <text x="1174" y="288" fontFamily="JetBrains Mono" fontSize="9" fill="var(--mk-sat)">NORAD 43437 · SAR</text>
        <text x="1174" y="302" fontFamily="JetBrains Mono" fontSize="8" fill="rgba(238,241,245,.4)">ingress in 12m · q 0.87</text>
      </>}
      {/* limb highlight + tour chip */}
      <circle cx={CX} cy={CY} r={R} fill="none" stroke="rgba(143,224,255,.12)" strokeWidth="6" style={{filter:'blur(3px)'}}/>
      {tour && <g>
        <rect x={CX-92} y="60" width="184" height="30" rx="15" fill="rgba(12,21,36,.92)" stroke="rgba(43,184,240,.4)"/>
        <text x={CX} y="79" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="10" letterSpacing="2" fill="#8FE0FF">→ STRAIT OF HORMUZ</text>
      </g>}
      {/* basemap status (P2-6, designed) */}
      <text x="20" y="858" fontFamily="JetBrains Mono" fontSize="8.5" letterSpacing="1" fill="rgba(238,241,245,.3)">BASEMAP · WORLDVIEW DARK EARTH — MAPBOX UNUSED IN GLOBE PROJECTION</text>
    </svg>
  );
}
window.MapCanvas = MapCanvas; window.WvMark = Mark; window.GlobeCanvas = GlobeCanvas;
