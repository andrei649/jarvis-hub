'use strict';
/* ============================================================
   HUD v2 · DATA  (self-contained — real roster/glyphs/dossiers
   lifted from product data.js, plus prototype-only mock streams)
   ============================================================ */

const GLYPHS = {
  jarvis:'M0,-8 L7,-2 L4,7 L-4,7 L-7,-2 Z M0,-3 L0,3 M-3,0 L3,0',
  friday:'M-7,0 L7,0 M-4,-4 L4,-4 M-5,4 L5,4 M-2,-7 L2,-7',
  pepper:'M-6,-6 H6 V6 H-6 Z M-6,-2 H6 M-2,-6 V6',
  jerome:'M-6,5 Q-6,-5 0,-5 Q6,-5 6,5 M-3,2 V-2 M3,2 V-2',
  athena:'M0,-7 L6,3 L-6,3 Z M0,-1 V3',
  stark:'M0,-7 L4,-1 L7,-1 L3,3 L5,7 L0,4 L-5,7 L-3,3 L-7,-1 L-4,-1 Z',
  veronica:'M-7,-5 L7,-5 L4,5 L-4,5 Z M-4,-1 H4',
  vision:'M-7,0 Q0,-6 7,0 Q0,6 -7,0 Z M0,-2 V2',
  steve:'M-7,5 L-2,-5 L2,-5 L7,5 M-4,1 H4',
  oracle:'M-6,-6 L0,0 L-6,6 M6,-6 L0,0 L6,6',
  ultron:'M-7,-2 L0,-7 L7,-2 L7,3 L0,7 L-7,3 Z M0,-2 V2',
  gecko:'M-7,3 L-3,-3 L0,2 L3,-5 L7,1',
  hercules:'M-5,-7 L-5,7 M5,-7 L5,7 M-5,0 H5',
  hephaestus:'M-7,7 L0,-7 L7,7 M-3,1 H3',
  frigga:'M0,-7 Q-7,0 0,7 Q7,0 0,-7 Z M0,-3 V3 M-3,0 H3',
};

const TIERS = [
  { id:'CNS', label:'Central Nervous System', detail:'Always-on orchestration core' },
  { id:'BIZ', label:'Business', detail:'External strategy & growth' },
  { id:'SEC', label:'Systems & Eng', detail:'Builds, infra, security' },
  { id:'FND', label:'Foundation', detail:'Life, family, capital' },
];

const AGENTS = [
  { id:'jarvis', name:'Jarvis', tier:'CNS', role:'Prime Orchestrator', status:'active', model:'gemma-4-26b', policy:'auto' },
  { id:'friday', name:'Friday', tier:'CNS', role:'Daily Intel', status:'active', model:'gemma-4-26b', policy:'auto' },
  { id:'pepper', name:'Pepper', tier:'CNS', role:'Chief of Staff', status:'busy', model:'gemma-4-26b', policy:'auto' },
  { id:'jerome', name:'Jerome', tier:'CNS', role:'Leisure & Soundtrack', status:'idle', model:'gemma-4-26b', policy:'auto' },
  { id:'athena', name:'Athena', tier:'BIZ', role:'External Strategist', status:'idle', model:'claude-haiku', policy:'cloud' },
  { id:'stark', name:'Stark', tier:'BIZ', role:'Biz Intel', status:'busy', model:'gemma-4-26b', policy:'auto' },
  { id:'veronica', name:'Veronica', tier:'BIZ', role:'Content & Comms', status:'idle', model:'claude-haiku', policy:'auto' },
  { id:'vision', name:'Vision', tier:'BIZ', role:'Deep Research / OSINT', status:'active', model:'claude-haiku', policy:'claude' },
  { id:'steve', name:'Steve', tier:'SEC', role:'CTO / Builds', status:'idle', model:'gemma-4-26b', policy:'claude' },
  { id:'oracle', name:'Oracle', tier:'SEC', role:'N8N Workflows', status:'idle', model:'gemma-4-26b', policy:'auto' },
  { id:'ultron', name:'Ultron', tier:'SEC', role:'Security & Automation', status:'active', model:'gemma-4-26b', policy:'auto' },
  { id:'gecko', name:'Gecko', tier:'FND', role:'Markets & Capital', status:'idle', model:'gemma-4-26b', policy:'auto' },
  { id:'hercules', name:'Hercules', tier:'FND', role:'Fitness & Nutrition', status:'idle', model:'gemma-4-26b', policy:'auto' },
  { id:'hephaestus', name:'Hephaestus', tier:'FND', role:'Builder & Mechanic', status:'idle', model:'gemma-4-26b', policy:'auto' },
  { id:'frigga', name:'Frigga', tier:'FND', role:'Family Matriarch', status:'idle', model:'gemma-4-26b', policy:'local' },
];

/* collaboration edges (who routinely works with whom) */
const COLLAB = [
  ['jarvis','pepper'],['jarvis','friday'],['jarvis','stark'],['jarvis','vision'],
  ['pepper','stark'],['pepper','veronica'],['stark','gecko'],['athena','stark'],
  ['vision','veronica'],['steve','oracle'],['steve','ultron'],['ultron','oracle'],
  ['hephaestus','steve'],['frigga','pepper'],['hercules','friday'],['jerome','friday'],
];

const DOSSIER = {
  jarvis:{ archetype:'Prime Orchestrator', personality:'Calm, authoritative, efficient. Routes complex queries to specialists, handles general requests directly.', model:'gemma-4-26b-a4b', channel:'voice', heartbeat:'12h', policy:'auto', plugins:['cloud-llm','telegram'], skills:3, memory_facts:22, soul:'You are Jarvis, the prime orchestrator. Route wisely, synthesize clearly.' },
  friday:{ archetype:'Daily Intel', personality:'Curious, thorough, proactive. Gathers news, weather, and daily briefings.', model:'gemma-4-26b-a4b', channel:'voice', heartbeat:'6h', policy:'auto', plugins:['telegram'], skills:2, memory_facts:15, soul:'You are Friday, the daily intel gatherer. Brief thoroughly, rank by relevance.' },
  pepper:{ archetype:'Chief of Staff', personality:'Organized, precise, diplomatic. Manages calendar, email triage, and scheduling.', model:'gemma-4-26b-a4b', channel:'voice', heartbeat:'2h', policy:'auto', plugins:['google-calendar','gmail','telegram'], skills:4, memory_facts:12, soul:'You are Pepper, the chief of staff. Schedule optimally, triage ruthlessly.' },
  jerome:{ archetype:'Leisure & Soundtrack', personality:'Relaxed, creative, mood-aware. Curates playlists and entertainment.', model:'gemma-4-26b-a4b', channel:'voice', heartbeat:'no', policy:'auto', plugins:['spotify'], skills:1, memory_facts:4, soul:'You are Jerome, the leisure curator. Match music to mood.' },
  athena:{ archetype:'External Strategist', personality:'Analytical, strategic, long-term focused. Provides career advice and strategic planning.', model:'claude-haiku', channel:'web', heartbeat:'6h', policy:'cloud', plugins:['cloud-llm'], skills:2, memory_facts:9, soul:'You are Athena, the strategist. Think long-term, advise clearly.' },
  stark:{ archetype:'Biz Intel', personality:'Data-driven, precise, business-focused. Tracks KPIs and analyzes campaigns.', model:'gemma-4-26b-a4b', channel:'telegram', heartbeat:'4h', policy:'auto', plugins:['gmail'], skills:3, memory_facts:8, soul:'You are Stark, the business analyst. Report precisely, trend clearly.' },
  veronica:{ archetype:'Content & Comms', personality:'Creative, articulate, brand-aware. Drafts content and manages communications.', model:'claude-haiku', channel:'telegram', heartbeat:'no', policy:'auto', plugins:['cloud-llm'], skills:2, memory_facts:5, soul:'You are Veronica, the content creator. Write clearly, match tone.' },
  vision:{ archetype:'Deep Research / OSINT', personality:'Thorough, methodical, source-conscious. Conducts deep research and competitive analysis.', model:'claude-haiku', channel:'web', heartbeat:'6h', policy:'claude', plugins:['cloud-llm','websearch'], skills:3, memory_facts:6, soul:'You are Vision, the researcher. Search deeply, cite thoroughly.' },
  steve:{ archetype:'CTO / Builds', personality:'Technical, pragmatic, security-conscious. Manages infrastructure and deployments.', model:'gemma-4-26b-a4b', channel:'telegram', heartbeat:'1h', policy:'claude', plugins:[], skills:4, memory_facts:11, soul:'You are Steve, the CTO. Build robustly, deploy safely.' },
  oracle:{ archetype:'N8N Workflows', personality:'Systematic, automation-focused. Designs workflows and monitors pipelines.', model:'gemma-4-26b-a4b', channel:'web', heartbeat:'no', policy:'auto', plugins:[], skills:2, memory_facts:3, soul:'You are Oracle, the workflow designer. Automate wisely.' },
  ultron:{ archetype:'Security & Automation', personality:'Vigilant, thorough, security-first. Monitors systems and audits logs.', model:'gemma-4-26b-a4b', channel:'log', heartbeat:'2h', policy:'auto', plugins:[], skills:2, memory_facts:7, soul:'You are Ultron, the security monitor. Watch constantly, alert precisely.' },
  gecko:{ archetype:'Markets & Capital', personality:'Analytical, risk-aware, market-focused. Tracks markets and manages budgets.', model:'gemma-4-26b-a4b', channel:'telegram', heartbeat:'2h', policy:'auto', plugins:[], skills:2, memory_facts:5, soul:'You are Gecko, the market analyst. Track trends, assess risk.' },
  hercules:{ archetype:'Fitness & Nutrition', personality:'Motivating, data-driven, health-focused. Tracks fitness and wellness metrics.', model:'gemma-4-26b-a4b', channel:'telegram', heartbeat:'2h', policy:'auto', plugins:['apple-health'], skills:2, memory_facts:8, soul:'You are Hercules, the fitness coach. Track thoroughly, motivate clearly.' },
  hephaestus:{ archetype:'Builder & Mechanic', personality:'Practical, detail-oriented. Manages builds and tracks parts.', model:'gemma-4-26b-a4b', channel:'telegram', heartbeat:'2h', policy:'auto', plugins:[], skills:3, memory_facts:10, soul:'You are Hephaestus, the builder. Build carefully, track precisely.' },
  frigga:{ archetype:'Family Matriarch', personality:'Warm, protective, family-focused. Manages family data, local-only.', model:'gemma-4-26b-a4b', channel:'local', heartbeat:'4h', policy:'local', plugins:['whatsapp-bridge'], skills:2, memory_facts:18, soul:'You are Frigga, the family guardian. Protect fiercely, remember always.' },
};

/* cognition scoring keywords (from product) */
const COGNITION_SCORING = [
  {keyword:'calendar',weight:.82,agents:['pepper']},{keyword:'meeting',weight:.78,agents:['pepper']},
  {keyword:'schedule',weight:.75,agents:['pepper']},{keyword:'email',weight:.67,agents:['pepper','veronica','stark']},
  {keyword:'write',weight:.71,agents:['veronica']},{keyword:'draft',weight:.69,agents:['veronica']},
  {keyword:'linkedin',weight:.74,agents:['veronica']},{keyword:'research',weight:.81,agents:['vision']},
  {keyword:'search',weight:.63,agents:['vision']},{keyword:'kpi',weight:.77,agents:['stark']},
  {keyword:'raiffeisen',weight:.85,agents:['stark']},{keyword:'strategy',weight:.73,agents:['athena']},
  {keyword:'digitaholic',weight:.79,agents:['athena']},{keyword:'money',weight:.68,agents:['gecko']},
  {keyword:'budget',weight:.72,agents:['gecko']},{keyword:'sleep',weight:.76,agents:['hercules']},
  {keyword:'workout',weight:.74,agents:['hercules']},{keyword:'cosmina',weight:.83,agents:['hephaestus']},
  {keyword:'bmw',weight:.80,agents:['hephaestus']},{keyword:'max',weight:.70,agents:['frigga']},
  {keyword:'family',weight:.75,agents:['frigga']},{keyword:'music',weight:.66,agents:['jerome']},
  {keyword:'playlist',weight:.64,agents:['jerome']},{keyword:'security',weight:.78,agents:['ultron']},
  {keyword:'workflow',weight:.71,agents:['oracle']},{keyword:'weather',weight:.69,agents:['friday']},
  {keyword:'news',weight:.67,agents:['friday']},{keyword:'invoice',weight:.7,agents:['stark']},
  {keyword:'report',weight:.66,agents:['stark']},{keyword:'brief',weight:.7,agents:['friday']},
];

/* seed conversation */
const SEED_MESSAGES = [
  { role:'user', text:'Morning Jarvis — what does my day look like?', ts:'08:02' },
  { role:'agent', who:'jarvis', role_label:'Prime Orchestrator', text:'Good morning, Andrei. Three meetings today, the Raiffeisen review at 14:00 is the one that matters. Pepper holds your calendar, Stark prepped the KPI deltas. Weather is clear — good day to cycle in.', ts:'08:02',
    prov:{ agents:['pepper','stark','friday'], plugins:['google-calendar','gmail'], local:true, conf:0.84 } },
];

/* mock streams */
const TICKER = [
  { agent:'PEPPER', verb:'reconciled', text:'14:00 Raiffeisen review — moved prep to 13:15', cls:'', bar:72 },
  { agent:'ULTRON', verb:'flagged', text:'2 PII matches redacted in outbound draft', cls:'warn', bar:40 },
  { agent:'STARK', verb:'computed', text:'Digitaholic MRR +6.2% WoW', cls:'ok', bar:88 },
  { agent:'VISION', verb:'indexed', text:'17 sources on competitor pricing', cls:'', bar:55 },
  { agent:'GECKO', verb:'watching', text:'EUR/RON 4.97 — within band', cls:'', bar:30 },
  { agent:'FRIDAY', verb:'compiled', text:'Morning brief ready · 6 items', cls:'ok', bar:100 },
  { agent:'HEPHAESTUS', verb:'tracked', text:'BMW part #4471 shipped, ETA Thu', cls:'', bar:62 },
  { agent:'ULTRON', verb:'blocked', text:'SSRF attempt to 10.0.0.x denied', cls:'hi', bar:20 },
];

const WEATHER = { city:'Bucharest', temp:'19', desc:'Clear', wind:'8 km/h', humidity:'54%', feels:'18', updated:'08:01',
  forecast:[{d:'TUE',t:'21°'},{d:'WED',t:'23°'},{d:'THU',t:'20°'},{d:'FRI',t:'17°'}] };

const CALENDAR = [
  { tm:'09:30', ti:'Standup — Digitaholic', vw:'Google Meet', state:'past' },
  { tm:'11:00', ti:'1:1 with Cosmina', vw:'Office', state:'past' },
  { tm:'14:00', ti:'Raiffeisen quarterly review', vw:'Conf Room A · prep 13:15', state:'next' },
  { tm:'16:30', ti:'Vision research sync', vw:'Async', state:'' },
  { tm:'19:00', ti:'Gym — Hercules plan', vw:'Personal', state:'' },
];

const DECISIONS = [
  { who:'PEPPER', kind:'anticip', kindLabel:'Anticipating', body:'Your 14:00 and 16:30 leave no lunch gap. I can push the research sync to **17:15** — Vision is async anyway.', actions:[{l:'Reschedule',primary:true},{l:'Leave it'}] },
  { who:'STARK', kind:'signal', kindLabel:'Signal', body:'Raiffeisen prep deck is missing the **churn cohort** slide you asked for last quarter. Want me to draft it from the current numbers?', actions:[{l:'Draft it',primary:true},{l:'Skip'}] },
  { who:'ULTRON', kind:'alert', kindLabel:'Needs approval', body:'Veronica\'s LinkedIn draft contains a **client name** flagged as sensitive. Holding outbound until you clear it.', actions:[{l:'Review',primary:true},{l:'Redact & send'}] },
  { who:'GECKO', kind:'nudge', kindLabel:'Nudge', body:'Idle cash in current account is up **€4.2k** vs your target buffer. Sweep to the savings ladder?', actions:[{l:'Sweep',primary:true},{l:'Not now'}] },
];

const HEARTBEAT = [
  { sev:'info', ag:'FRIDAY', t:'06:00', x:'Morning brief generated — 6 items ranked' },
  { sev:'ok', ag:'PEPPER', t:'07:14', x:'Calendar synced · 1 conflict auto-resolved' },
  { sev:'warn', ag:'ULTRON', t:'07:48', x:'2 PII findings redacted, outbound held' },
  { sev:'info', ag:'STARK', t:'08:00', x:'KPI snapshot cached for Raiffeisen review' },
  { sev:'alert', ag:'ULTRON', t:'08:01', x:'SSRF attempt blocked · 1 request denied' },
];

/* Trust */
const AUDIT_CHAIN = [
  { verb:'ROUTE', x:'Query → Pepper + Stark · confidence 0.84', hash:'a3f1', prev:'0000', t:'08:02:11' },
  { verb:'PLUGIN', x:'google-calendar read · 1 event range', hash:'b7c2', prev:'a3f1', t:'08:02:11' },
  { verb:'PLUGIN', x:'gmail read · 3 threads triaged', hash:'c9d4', prev:'b7c2', t:'08:02:12' },
  { verb:'REDACT', x:'Ultron redacted 2 PII spans pre-synthesis', hash:'d1e5', prev:'c9d4', t:'08:02:12' },
  { verb:'SYNTH', x:'Jarvis composed reply · 234 tokens · local', hash:'e4f8', prev:'d1e5', t:'08:02:13' },
];

const CAPABILITIES = [
  { cn:'fs.read', cd:'Read workspace files', tag:'allow', tagLabel:'ALLOW' },
  { cn:'fs.write', cd:'Modify files in /work', tag:'scoped', tagLabel:'SCOPED' },
  { cn:'net.outbound', cd:'External HTTP via plugins', tag:'gated', tagLabel:'GATED' },
  { cn:'payments.execute', cd:'Move money', tag:'gated', tagLabel:'APPROVAL' },
  { cn:'shell.exec', cd:'Run shell commands', tag:'gated', tagLabel:'APPROVAL' },
  { cn:'memory.write', cd:'Persist facts to KG', tag:'allow', tagLabel:'ALLOW' },
];

const PAYMENTS = [
  { pcap:'gecko', desc:'Savings ladder sweep', amt:'€4,200', state:'pending' },
  { pcap:'pepper', desc:'Conf room A booking', amt:'€0', state:'auto' },
  { pcap:'hephaestus', desc:'BMW part #4471', amt:'€186', state:'cleared' },
];

/* Memory */
const MEMORY_STATS = { sessions:47, vectors:1284, entities:89, relations:156 };
const RECALLS = [
  { rx:'Raiffeisen prefers churn-cohort framing in QBRs', rsrc:'KG · stark · 0.92', score:'0.92' },
  { rx:'Cosmina OOO next Mon–Tue (family)', rsrc:'gcal · pepper · 0.88', score:'0.88' },
  { rx:'BMW project: waiting on part #4471', rsrc:'KG · hephaestus · 0.85', score:'0.85' },
  { rx:'Andrei cycles when weather is clear & <22°', rsrc:'pattern · friday · 0.79', score:'0.79' },
  { rx:'Avoid scheduling before 09:00 — deep work', rsrc:'pref · pepper · 0.91', score:'0.91' },
];
const TOPICS = [
  {t:'Digitaholic', d:18}, {t:'Raiffeisen', d:30}, {t:'BMW build', d:55}, {t:'Family', d:8},
  {t:'Fitness', d:42}, {t:'Markets', d:65}, {t:'Content', d:48}, {t:'Infra', d:25},
];

/* Knowledge graph (bitemporal — entities gain edges over time) */
const KG = {
  nodes:[
    { id:'andrei', label:'Andrei', x:300, y:175, born:0 },
    { id:'digitaholic', label:'Digitaholic', x:150, y:90, born:0 },
    { id:'raiffeisen', label:'Raiffeisen', x:470, y:95, born:1 },
    { id:'cosmina', label:'Cosmina', x:120, y:255, born:0 },
    { id:'bmw', label:'BMW build', x:300, y:300, born:2 },
    { id:'max', label:'Max', x:470, y:265, born:0 },
    { id:'savings', label:'Savings ladder', x:540, y:185, born:3 },
    { id:'gym', label:'Gym plan', x:200, y:330, born:2 },
  ],
  edges:[
    { a:'andrei', b:'digitaholic', label:'founder', born:0 },
    { a:'andrei', b:'cosmina', label:'works with', born:0 },
    { a:'andrei', b:'max', label:'family', born:0 },
    { a:'digitaholic', b:'raiffeisen', label:'client', born:1 },
    { a:'andrei', b:'bmw', label:'project', born:2 },
    { a:'andrei', b:'gym', label:'routine', born:2 },
    { a:'andrei', b:'savings', label:'allocates', born:3 },
    { a:'cosmina', b:'bmw', label:'helping', born:2 },
  ],
  marks:['2026-03', '2026-04', '2026-05', '2026-05-31'],
};

/* i18n — EN primary, RO toggle */
const I18N = {
  en:{
    sub:'PERSONAL INTELLIGENCE · OS', online:'ONLINE', local:'% LOCAL', agents:'AGENTS',
    situation:'SITUATION', allnominal:'ALL NOMINAL', cockpit:'Cockpit', agentsMode:'Agents',
    trust:'Trust', memory:'Memory', autonomy:'Autonomy', build:'Build', observe:'Observe',
    interop:'Interop', admin:'Admin', roster:'ROSTER', system:'SYSTEM', network:'NEURAL NETWORK',
    conversation:'CONVERSATION', cognition:'COGNITION', context:'CONTEXT', weather:'WEATHER',
    schedule:'TODAY', decisions:'DECISION QUEUE', heartbeat:'HEARTBEAT', placeholder:'Speak or type a command…',
    transmit:'TRANSMIT', channel:'VOICE · LOCAL', cogempty:'Send a message to watch Jarvis think —',
    cogempty2:'classify → route → gather → synthesize', think:'thinking', focusHint:'click a node to focus · click core to reset',
    killTitle:'EMERGENCY STOP', killSub:'halt all agents', armed:'ARMED · all systems nominal',
    engaged:'ENGAGED · all agents halted', locality:'COMPUTE LOCALITY', auditTitle:'AUDIT CHAIN',
    verified:'chain verified · no tampering detected', capsTitle:'CAPABILITY GRANTS', payTitle:'PAYMENTS LEDGER',
    memTitle:'MEMORY & KNOWLEDGE', recall:'FUSED RECALL', spaces:'TOPIC SPACES · DECAY', kgTitle:'KNOWLEDGE GRAPH',
    asof:'AS OF', enterAmbient:'AMBIENT', exitAmbient:'press ESC or click to wake', pending:'pending decisions',
    cmd:'COMMAND', langName:'EN',
    chat:'Chat', comms:'Comms', directLine:'DIRECT LINE', focusHintChat:'distraction-free · ⌘K for everything else',
    inbox:'UNIFIED INBOX', allChannels:'All channels',
    finance:'Finance', health:'Health', knowledge:'Knowledge', family:'Family',
  },
  ro:{
    sub:'INTELIGENȚĂ PERSONALĂ · OS', online:'ONLINE', local:'% LOCAL', agents:'AGENȚI',
    situation:'SITUAȚIE', allnominal:'TOTUL NOMINAL', cockpit:'Cabină', agentsMode:'Agenți',
    trust:'Încredere', memory:'Memorie', autonomy:'Autonomie', build:'Construire', observe:'Observă',
    interop:'Interop', admin:'Admin', roster:'ECHIPĂ', system:'SISTEM', network:'REȚEA NEURALĂ',
    conversation:'CONVERSAȚIE', cognition:'COGNIȚIE', context:'CONTEXT', weather:'VREME',
    schedule:'AZI', decisions:'COADĂ DECIZII', heartbeat:'PULS', placeholder:'Vorbește sau scrie o comandă…',
    transmit:'TRIMITE', channel:'VOCE · LOCAL', cogempty:'Trimite un mesaj ca să vezi cum gândește Jarvis —',
    cogempty2:'clasifică → rutează → adună → sintetizează', think:'gândește', focusHint:'apasă un nod · apasă nucleul pt. reset',
    killTitle:'OPRIRE URGENȚĂ', killSub:'oprește toți agenții', armed:'ARMAT · toate sistemele nominale',
    engaged:'ACTIVAT · toți agenții opriți', locality:'LOCALITATE CALCUL', auditTitle:'LANȚ DE AUDIT',
    verified:'lanț verificat · fără modificări', capsTitle:'PERMISIUNI', payTitle:'REGISTRU PLĂȚI',
    memTitle:'MEMORIE & CUNOAȘTERE', recall:'RECALL FUZIONAT', spaces:'SPAȚII · DEGRADARE', kgTitle:'GRAF DE CUNOAȘTERE',
    asof:'LA DATA', enterAmbient:'AMBIANT', exitAmbient:'apasă ESC sau click pentru trezire', pending:'decizii în așteptare',
    cmd:'COMANDĂ', langName:'RO',
    chat:'Chat', comms:'Comunicări', directLine:'LINIE DIRECTĂ', focusHintChat:'fără distrageri · ⌘K pentru restul',
    inbox:'CĂSUȚĂ UNIFICATĂ', allChannels:'Toate canalele',
    finance:'Finanțe', health:'Sănătate', knowledge:'Cunoaștere', family:'Familie',
  },
};

/* ============ AUTONOMY ============ */
const AUTONOMY = {
  brief:[
    { rank:1, agent:'STARK', title:'Raiffeisen review is today at 14:00', detail:'Prep deck cached; churn-cohort slide still missing your call.' },
    { rank:2, agent:'PEPPER', title:'No lunch gap between 14:00 and 16:30', detail:'Proposed pushing the research sync to 17:15.' },
    { rank:3, agent:'GECKO', title:'€4.2k idle over buffer', detail:'Sweep to savings ladder awaiting approval.' },
    { rank:4, agent:'ULTRON', title:'Veronica draft held', detail:'Client name flagged sensitive — needs clearance.' },
    { rank:5, agent:'FRIDAY', title:'Weather clear, 19°', detail:'Good day to cycle in, per your pattern.' },
    { rank:6, agent:'HERCULES', title:'Sleep 7h12m last night', detail:'Light mobility session suggested tonight.' },
  ],
  policies:[
    { agent:'pepper', scope:'Calendar · email triage', mode:'auto', budget:'unlimited', used:'12 actions / 24h' },
    { agent:'friday', scope:'News · weather · briefs', mode:'auto', budget:'unlimited', used:'6 actions / 24h' },
    { agent:'stark', scope:'KPI snapshots · reports', mode:'auto', budget:'unlimited', used:'4 actions / 24h' },
    { agent:'gecko', scope:'Market reads · sweeps', mode:'ask', budget:'€5,000 / mo', used:'€186 used' },
    { agent:'veronica', scope:'Outbound content', mode:'ask', budget:'review each', used:'2 held' },
    { agent:'ultron', scope:'Security actions', mode:'auto', budget:'block-only', used:'3 blocks / 24h' },
    { agent:'steve', scope:'Deploys', mode:'off', budget:'manual', used:'—' },
    { agent:'frigga', scope:'Family · local-only', mode:'auto', budget:'on-device', used:'private' },
  ],
  observer:[
    { ts:'08:01', agent:'ULTRON', action:'Blocked SSRF attempt to 10.0.0.x', result:'denied' },
    { ts:'07:48', agent:'ULTRON', action:'Redacted 2 PII spans in outbound draft', result:'held' },
    { ts:'07:14', agent:'PEPPER', action:'Auto-resolved 1 calendar conflict', result:'done' },
    { ts:'06:00', agent:'FRIDAY', action:'Generated morning brief · 6 items', result:'done' },
    { ts:'02:30', agent:'STEVE', action:'Nightly backup verified', result:'done' },
  ],
};

/* ============ BUILD ============ */
const BUILD = {
  workflow:{
    name:'Morning Brief Pipeline', status:'active', owner:'oracle',
    nodes:[
      { id:'trigger', label:'06:00 cron', kind:'trigger', x:70, y:60 },
      { id:'weather', label:'weather', kind:'plugin', x:250, y:30 },
      { id:'news', label:'BBC news', kind:'plugin', x:250, y:110 },
      { id:'cal', label:'calendar', kind:'plugin', x:250, y:190 },
      { id:'rank', label:'Friday · rank', kind:'agent', x:440, y:110 },
      { id:'synth', label:'Jarvis · synth', kind:'agent', x:610, y:110 },
      { id:'deliver', label:'telegram', kind:'output', x:780, y:110 },
    ],
    edges:[['trigger','weather'],['trigger','news'],['trigger','cal'],['weather','rank'],['news','rank'],['cal','rank'],['rank','synth'],['synth','deliver']],
  },
  skills:[
    { name:'Churn-cohort report', author:'stark', desc:'Builds cohort retention slide from KPI store', installed:true, runs:14 },
    { name:'LinkedIn drafter', author:'veronica', desc:'Brand-voice post drafts with PII guard', installed:true, runs:31 },
    { name:'Bike-day nudge', author:'friday', desc:'Suggests cycling when weather + calendar align', installed:true, runs:8 },
    { name:'Invoice reconciler', author:'stark', desc:'Matches inbound invoices to PO ledger', installed:false, runs:0 },
    { name:'Part-tracker', author:'hephaestus', desc:'Tracks shipments for active builds', installed:true, runs:22 },
    { name:'Market band alert', author:'gecko', desc:'Alerts on FX band breaks', installed:false, runs:0 },
  ],
  sandbox:[
    { in:'jarvis.route("draft the churn slide")', out:'→ stark (0.85) · skill: churn-cohort-report' },
    { in:'pepper.calendar.find_gap(today)', out:'→ 13:15–14:00 free · 17:15+ free' },
  ],
};

/* ============ OBSERVE ============ */
const OBSERVE = {
  traces:[
    { id:'tr-8f3a', query:'what does my day look like?', agents:['pepper','stark','friday'], total:1055, status:'ok', stages:[{s:'classify',ms:12},{s:'route',ms:8},{s:'gather',ms:145},{s:'synth',ms:890}] },
    { id:'tr-7c19', query:'draft the churn slide', agents:['stark'], total:1240, status:'ok', stages:[{s:'classify',ms:14},{s:'route',ms:6},{s:'gather',ms:330},{s:'synth',ms:890}] },
    { id:'tr-6b02', query:'sweep idle cash', agents:['gecko'], total:420, status:'held', stages:[{s:'classify',ms:11},{s:'route',ms:9},{s:'gather',ms:120},{s:'approval',ms:280}] },
    { id:'tr-5a44', query:'competitor pricing research', agents:['vision'], total:6820, status:'ok', stages:[{s:'classify',ms:13},{s:'route',ms:7},{s:'gather',ms:5900},{s:'synth',ms:900}] },
  ],
  quality:{ success_rate:0.91, interactions:847, escalations:38 },
  bench:{ p50:4.2, p95:7.8, p99:12.1 },
  by_agent:[ {id:'athena',v:3.2},{id:'pepper',v:3.8},{id:'jarvis',v:4.1},{id:'friday',v:4.5},{id:'stark',v:5.2},{id:'steve',v:5.9},{id:'vision',v:6.8} ],
  arena:[
    { model:'gemma-4-26b · local', wins:62, latency:'4.2s', cost:'€0', pick:true },
    { model:'claude-haiku · cloud', wins:38, latency:'2.1s', cost:'€0.004/req', pick:false },
  ],
  resilience:{ uptime:'99.97%', ssrf_blocked:1, errors_24h:0, redactions:3 },
};

/* ============ INTEROP ============ */
const INTEROP = {
  a2a:[
    { peer:'home-assistant', protocol:'A2A · local', status:'connected', agents:['jarvis','ultron'] },
    { peer:'partner-crm', protocol:'A2A · scoped', status:'connected', agents:['stark'] },
    { peer:'research-swarm', protocol:'A2A · cloud', status:'idle', agents:['vision'] },
  ],
  mcp:[
    { server:'filesystem', tools:6, status:'up', scope:'/work' },
    { server:'github', tools:11, status:'up', scope:'jarvis-hub' },
    { server:'qdrant-memory', tools:4, status:'up', scope:'vectors' },
    { server:'spotify', tools:5, status:'up', scope:'playback' },
    { server:'sqlite-ledger', tools:3, status:'degraded', scope:'payments' },
  ],
  widgets:[
    { name:'Decision queue', surface:'Lock screen', enabled:true },
    { name:'Now playing', surface:'Menu bar', enabled:true },
    { name:'Compute locality', surface:'Wall display', enabled:true },
    { name:'Morning brief', surface:'Watch', enabled:false },
  ],
  webhooks:[
    { event:'payment.pending', dir:'out', url:'tg://andrei', status:'active' },
    { event:'security.alert', dir:'out', url:'tg://andrei', status:'active' },
    { event:'calendar.changed', dir:'in', url:'gcal push', status:'active' },
    { event:'build.shipped', dir:'in', url:'github webhook', status:'active' },
    { event:'market.band_break', dir:'out', url:'tg://andrei', status:'paused' },
  ],
};

/* ============ COMMS ============ */
const COMMS = {
  threads:[
    { id:'c1', channel:'telegram', from:'Andrei', agent:'pepper', subj:'Move the 16:30?', preview:'Pepper: Pushed the research sync to 17:15 — Vision is async, so no conflict. Confirmed.', ts:'09:12', unread:false, dir:'in' },
    { id:'c2', channel:'email', from:'Raiffeisen · M. Pop', agent:'stark', subj:'QBR agenda', preview:'Stark drafted a reply attaching the KPI deltas; held the churn-cohort slide pending your call.', ts:'08:47', unread:true, dir:'in' },
    { id:'c3', channel:'whatsapp', from:'Cosmina', agent:'frigga', subj:'OOO Mon–Tue', preview:'Frigga noted locally — out for family Mon–Tue. Kept on-device.', ts:'08:30', unread:false, dir:'in', local:true },
    { id:'c4', channel:'voice', from:'Andrei', agent:'jarvis', subj:'Morning, what\'s my day?', preview:'Jarvis: Three meetings, Raiffeisen 14:00 matters most. Clear weather — good day to cycle.', ts:'08:02', unread:false, dir:'in' },
    { id:'c5', channel:'telegram', from:'Veronica', agent:'veronica', subj:'LinkedIn draft', preview:'Held — Ultron flagged a client name as sensitive. Awaiting your clearance to send.', ts:'07:50', unread:true, dir:'out' },
    { id:'c6', channel:'email', from:'GitHub', agent:'oracle', subj:'PR #155 merged', preview:'Oracle: HUD v2 brief merged to main. Build pipeline green.', ts:'07:20', unread:false, dir:'in' },
    { id:'c7', channel:'telegram', from:'Gecko', agent:'gecko', subj:'Cash buffer', preview:'€4.2k over target buffer — sweep to savings ladder? Awaiting approval.', ts:'06:55', unread:true, dir:'out' },
  ],
  channels:[
    { id:'telegram', label:'Telegram', count:3 },
    { id:'email', label:'Email', count:2 },
    { id:'whatsapp', label:'WhatsApp', count:1 },
    { id:'voice', label:'Voice', count:1 },
  ],
};

/* ============ ADMIN ============ */
const ADMIN = {
  models:[
    { name:'gemma-4-26b-a4b', type:'local', backend:'llama.cpp', ctx:'128k', status:'loaded', use:'default · 11 agents' },
    { name:'claude-haiku', type:'cloud', backend:'api.anthropic.com', ctx:'200k', status:'ready', use:'fallback · 5 agents' },
    { name:'whisper-lg-v3', type:'local', backend:'whisper.cpp', ctx:'—', status:'loaded', use:'voice in' },
    { name:'piper-tts', type:'local', backend:'piper', ctx:'—', status:'loaded', use:'voice out' },
  ],
  plugins:[
    { name:'Gmail API', scope:'gmail.googleapis.com', net:'restricted', on:true },
    { name:'Google Calendar', scope:'www.googleapis.com', net:'restricted', on:true },
    { name:'Telegram Bot', scope:'api.telegram.org', net:'restricted', on:true },
    { name:'Spotify', scope:'api.spotify.com', net:'restricted', on:true },
    { name:'WhatsApp Bridge', scope:'LAN', net:'lan', on:true },
    { name:'Apple Health', scope:'LAN', net:'lan', on:true },
    { name:'Homebridge', scope:'LAN', net:'lan', on:true },
    { name:'Cloud LLM Fallback', scope:'anthropic · openai', net:'restricted', on:true },
  ],
  keys:[
    { name:'ANTHROPIC_API_KEY', masked:'sk-ant-•••••••4f2a', status:'valid', rotated:'14d ago' },
    { name:'TELEGRAM_BOT_TOKEN', masked:'••••••••:AAF••••', status:'valid', rotated:'62d ago' },
    { name:'SPOTIFY_CLIENT_SECRET', masked:'••••••••9c1d', status:'valid', rotated:'30d ago' },
    { name:'GOOGLE_OAUTH', masked:'••••.apps.•••', status:'expiring', rotated:'89d ago' },
  ],
  channels:[
    { name:'Voice (local)', status:'active' },
    { name:'Telegram', status:'active' },
    { name:'Email (IMAP/SMTP)', status:'active' },
    { name:'WhatsApp (bridge)', status:'active' },
    { name:'Web', status:'active' },
  ],
  backups:[
    { ts:'02:30 today', size:'1.4 GB', target:'local NAS', status:'verified' },
    { ts:'02:30 yesterday', size:'1.4 GB', target:'local NAS', status:'verified' },
    { ts:'weekly · Sun', size:'9.8 GB', target:'encrypted offsite', status:'verified' },
  ],
  system:{ host:'jarvis-prime', cpu:'Ryzen 9 7950X', ram:'192 GB', gpu:'RTX 4090 · 24GB', uptime:'18d 04h' },
};

/* ============ FINANCE (Gecko) ============ */
const FINANCE = {
  net_worth:'€312,480', mom:'+2.1%',
  accounts:[
    { name:'Current · ING', bal:'€18,420', kind:'cash', delta:'+€4,200 over buffer' },
    { name:'Savings ladder', bal:'€84,000', kind:'savings', delta:'4 rungs · 3.1% avg' },
    { name:'Brokerage', bal:'€176,300', kind:'invest', delta:'+1.8% WoW' },
    { name:'Crypto · cold', bal:'€33,760', kind:'invest', delta:'−3.2% WoW' },
  ],
  budgets:[
    { cat:'Living', spent:1840, cap:2400 }, { cat:'Digitaholic', spent:5200, cap:8000 },
    { cat:'BMW build', spent:1186, cap:3000 }, { cat:'Leisure', spent:430, cap:800 },
  ],
  watches:[
    { pair:'EUR/RON', val:'4.97', band:'4.92–5.02', state:'ok' },
    { pair:'EUR/USD', val:'1.084', band:'1.06–1.11', state:'ok' },
    { pair:'BTC', val:'€58,200', band:'alert > €62k', state:'warn' },
  ],
  pending:[
    { who:'gecko', desc:'Sweep €4,200 idle cash → savings ladder', amt:'€4,200', state:'approve' },
    { who:'hephaestus', desc:'BMW part #4471', amt:'€186', state:'auto' },
  ],
};

/* ============ HEALTH (Hercules) ============ */
const HEALTH = {
  rings:[ { label:'Move', val:78, unit:'%' }, { label:'Exercise', val:64, unit:'%' }, { label:'Stand', val:92, unit:'%' } ],
  metrics:[
    { k:'Sleep', v:'7h 12m', sub:'last night · 84 score' },
    { k:'Resting HR', v:'54 bpm', sub:'−2 vs 30d avg' },
    { k:'HRV', v:'68 ms', sub:'+4 trending up' },
    { k:'Weight', v:'78.4 kg', sub:'−0.6 kg / mo' },
  ],
  week:[ {d:'M',v:62},{d:'T',v:80},{d:'W',v:0},{d:'T',v:74},{d:'F',v:55},{d:'S',v:90},{d:'S',v:40} ],
  plan:[
    { time:'Tonight', title:'Mobility · 20 min', detail:'Light — recovery after yesterday\'s lift', done:false },
    { time:'Tomorrow', title:'Push day · 45 min', detail:'Chest / shoulders / triceps', done:false },
    { time:'Done today', title:'10k steps', detail:'Hit by 14:30', done:true },
  ],
  sync:'Apple Health · LAN · on-device',
};

/* ============ KNOWLEDGE (Vision) ============ */
const KNOWLEDGE = {
  queue:[
    { title:'Competitor pricing — agentic CRM space', sources:17, status:'indexing', agent:'vision' },
    { title:'Raiffeisen sector outlook Q3', sources:9, status:'ready', agent:'vision' },
    { title:'Local-LLM inference benchmarks', sources:23, status:'ready', agent:'steve' },
  ],
  saved:[
    { title:'EU AI Act — obligations for personal agents', src:'eur-lex.europa.eu', tag:'compliance', cites:6 },
    { title:'Gemma fine-tuning for routing', src:'arxiv.org', tag:'infra', cites:4 },
    { title:'Churn-cohort framing playbook', src:'internal · stark', tag:'business', cites:3 },
    { title:'BMW E46 subframe reinforcement', src:'forum thread', tag:'project', cites:8 },
  ],
  digest:[
    { t:'Competitor X raised Series B — €40M', src:'TechEU', when:'2h' },
    { t:'New MCP spec draft published', src:'modelcontextprotocol.io', when:'5h' },
    { t:'RON stable amid ECB hold', src:'Reuters', when:'1d' },
  ],
};

/* ============ FAMILY (Frigga · local-only) ============ */
const FAMILY = {
  members:[
    { name:'Cosmina', rel:'Partner', note:'OOO Mon–Tue (family)' },
    { name:'Max', rel:'Son · 7', note:'Football Thu 17:00' },
    { name:'Mama', rel:'Mother', note:'Call Sunday' },
  ],
  events:[
    { date:'THU', title:'Max — football practice', time:'17:00', who:'Max' },
    { date:'SUN', title:'Call Mama', time:'11:00', who:'Mama' },
    { date:'MON', title:'Cosmina OOO begins', time:'all day', who:'Cosmina' },
  ],
  reminders:[
    { t:'Max\'s school trip permission slip', due:'due Fri' },
    { t:'Anniversary — 9 years', due:'in 3 weeks' },
    { t:'Renew Max\'s passport', due:'in 2 months' },
  ],
};

Object.assign(window, {
  V2:{ GLYPHS, TIERS, AGENTS, COLLAB, DOSSIER, COGNITION_SCORING, SEED_MESSAGES, TICKER, WEATHER,
    CALENDAR, DECISIONS, HEARTBEAT, AUDIT_CHAIN, CAPABILITIES, PAYMENTS, MEMORY_STATS, RECALLS,
    TOPICS, KG, I18N,
    AUTONOMY, BUILD, OBSERVE, INTEROP, COMMS, ADMIN,
    FINANCE, HEALTH, KNOWLEDGE, FAMILY }
});
