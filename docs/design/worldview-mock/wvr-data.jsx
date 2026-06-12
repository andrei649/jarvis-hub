'use strict';
/* WorldView Redesign — Hormuz demo scenario data (mirrors the seed in the brief §1) */
window.WVR = {
  layers:[
    { id:'adsb', label:'Aircraft', sub:'ADS-B', count:142, shapes:[
      { glyph:'civil', label:'Civil', color:'var(--mk-civil)' },
      { glyph:'mil', label:'Military', color:'var(--mk-mil)' } ] },
    { id:'ais', label:'Vessels', sub:'AIS', count:387, shapes:[
      { glyph:'vessel', label:'Underway', color:'var(--mk-vessel)' },
      { glyph:'dark', label:'Dark vessel', color:'var(--mk-dark)' } ] },
    { id:'tle', label:'Satellites', sub:'SGP4', count:23, shapes:[
      { glyph:'sat', label:'+ sensor footprint', color:'var(--mk-sat)' } ] },
    { id:'ew', label:'GPS jamming', sub:'H3 cells', count:14, shapes:[
      { glyph:'hex', label:'Intensity ramp', color:'var(--mk-jam)' } ] },
    { id:'context', label:'Intel', sub:'events · zones', count:6, shapes:[
      { glyph:'intel', label:'Event / NOTAM', color:'var(--mk-intel)' } ] },
  ],
  recon:[
    { sensor:'SAR', norad:43437, aoi:'hormuz', inMin:12, q:0.87, sunlit:false, note:'night-capable' },
    { sensor:'OPTICAL', norad:39084, aoi:'hormuz', inMin:107, q:0.42, sunlit:false, note:'daylight in 1h 47m — quality limited' },
    { sensor:'SAR', norad:48915, aoi:'suez', inMin:163, q:0.79, sunlit:true, note:'' },
  ],
  alerts:[
    { sev:'high', t:'Dark vessel — MMSI 244660000', m:'AIS silent 1h 00m · Musandam geofence', ts:'06:41', locatable:true },
    { sev:'med', t:'Airspace closure — NOTAM A0142/26', m:'severity 0.8 · active until 18:00 UTC', ts:'05:58', locatable:true },
    { sev:'low', t:'Jamming intensity rising', m:'H3 cell 8a2a… · 0.82 ↑ from 0.55', ts:'05:12', locatable:true },
  ],
  inspector:{
    id:'MMSI 244660000', kind:'DARK VESSEL · ALERT CONTEXT', name:'M/T SAFEEN PIONEER',
    rows:[
      ['Vessel', 'Crude tanker · 274 m'],
      ['Last AIS fix', '05:41:03 UTC'],
      ['Silent for', '1h 00m', 'bad'],
      ['Last speed / course', '11.2 kt · 312°'],
      ['Position now', 'dead-reckoned', 'warn'],
      ['Geofence', 'Hormuz · Musandam'],
    ],
    prov:'Reported by AISStream — true at 05:41:03, recorded by WorldView at 05:41:07. Position since then is estimated from last course and speed.',
  },
  events:[ // timeline markers, pct of 24h window
    { pct:38, kind:'intel', label:'strike event' },
    { pct:57, kind:'alert', label:'NOTAM issued' },
    { pct:71, kind:'alert', label:'vessel went dark' },
    { pct:88, kind:'recon', label:'SAR pass' },
    { pct:96, kind:'recon', label:'optical pass' },
  ],
  shortcuts:[
    ['Space','Play / pause the master clock'], ['L','Snap back to LIVE'],
    ['← →','Scrub ±30 s (enters historical)'], ['Esc','Clear selection / close overlay'],
    ['1–5','Toggle data layers'], ['G','Switch 2.5D map / 3D globe'],
    ['R','Set replay window at cursor'], ['?','This help'],
  ],
};
