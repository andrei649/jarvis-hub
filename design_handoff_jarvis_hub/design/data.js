// Static reference data for the Jarvis Hub prototype.
// Mirrors the agents.yaml registry and mock ambient/conversation data.

window.JARVIS_DATA = (() => {
  // Agent glyphs — small geometric SVG mark per personality.
  // Each is a polyline/polygon string fitted to a -10..10 viewBox.
  // Keep abstract — no recognisable IP, just personality cues.
  const GLYPHS = {
    jarvis:     'M0,-8 L7,-2 L4,7 L-4,7 L-7,-2 Z M0,-3 L0,3 M-3,0 L3,0',                 // command pentagon + crosshair
    friday:     'M-7,0 L7,0 M-4,-4 L4,-4 M-5,4 L5,4 M-2,-7 L2,-7',                       // signal bars (daily intel)
    pepper:     'M-6,-6 H6 V6 H-6 Z M-6,-2 H6 M-2,-6 V6',                                // ledger / planner grid
    jerome:     'M-6,5 Q-6,-5 0,-5 Q6,-5 6,5 M-3,2 V-2 M3,2 V-2',                        // music arch
    athena:     'M0,-7 L6,3 L-6,3 Z M0,-1 V3',                                            // owl/strategy triangle
    stark:      'M0,-7 L4,-1 L7,-1 L3,3 L5,7 L0,4 L-5,7 L-3,3 L-7,-1 L-4,-1 Z',          // spark/star (biz intel)
    veronica:   'M-7,-5 L7,-5 L4,5 L-4,5 Z M-4,-1 H4',                                   // megaphone trapezoid
    vision:     'M-7,0 Q0,-6 7,0 Q0,6 -7,0 Z M0,-2 V2',                                  // eye (OSINT)
    steve:      'M-7,5 L-2,-5 L2,-5 L7,5 M-4,1 H4',                                       // wrench/A-frame (CTO)
    oracle:     'M-6,-6 L0,0 L-6,6 M6,-6 L0,0 L6,6',                                     // brackets (workflow nodes)
    ultron:     'M-7,-2 L0,-7 L7,-2 L7,3 L0,7 L-7,3 Z M0,-2 V2',                          // shield hex (security)
    gecko:      'M-7,3 L-3,-3 L0,2 L3,-5 L7,1',                                          // candlestick chart
    hercules:   'M-5,-7 L-5,7 M5,-7 L5,7 M-5,0 H5',                                       // dumbbell (fitness)
    hephaestus: 'M-7,7 L0,-7 L7,7 M-3,1 H3',                                              // anvil triangle
    frigga:     'M0,-7 Q-7,0 0,7 Q7,0 0,-7 Z M0,-3 V3 M-3,0 H3',                          // family knot / spindle
  };

  const AGENTS = [
    // Command tier
    { id: 'jarvis',     name: 'Jarvis',     tier: 'CNS',     role: 'Prime Orchestrator',    model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'voice',    load: 0.62, glyph: GLYPHS.jarvis },
    { id: 'friday',     name: 'Friday',     tier: 'CNS',     role: 'Daily Intel',           model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'voice',    load: 0.48, glyph: GLYPHS.friday },
    { id: 'pepper',     name: 'Pepper',     tier: 'CNS',     role: 'Chief of Staff',        model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'voice',    load: 0.22, glyph: GLYPHS.pepper },
    { id: 'jerome',     name: 'Jerome',     tier: 'CNS',     role: 'Leisure & Soundtrack',  model: 'gemma-4-26b',    status: 'idle',    heartbeat: false, channel: 'voice',    load: 0.05, glyph: GLYPHS.jerome },
    // Business tier
    { id: 'athena',     name: 'Athena',     tier: 'BIZ',     role: 'External Strategist',   model: 'claude-haiku',   status: 'ready',   heartbeat: true,  channel: 'web',      load: 0.31, glyph: GLYPHS.athena },
    { id: 'stark',      name: 'Stark',      tier: 'BIZ',     role: 'Biz Intel',             model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'telegram', load: 0.74, glyph: GLYPHS.stark },
    { id: 'veronica',   name: 'Veronica',   tier: 'BIZ',     role: 'Content & Comms',       model: 'claude-haiku',   status: 'idle',    heartbeat: false, channel: 'telegram', load: 0.15, glyph: GLYPHS.veronica },
    { id: 'vision',     name: 'Vision',     tier: 'BIZ',     role: 'Deep Research / OSINT', model: 'claude-haiku',   status: 'ready',   heartbeat: true,  channel: 'web',      load: 0.40, glyph: GLYPHS.vision },
    // Security / Tech tier
    { id: 'steve',      name: 'Steve',      tier: 'SEC',     role: 'CTO / Builds',          model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram', load: 0.55, glyph: GLYPHS.steve },
    { id: 'oracle',     name: 'Oracle',     tier: 'SEC',     role: 'N8N Workflows',         model: 'gemma-4-26b',    status: 'idle',    heartbeat: false, channel: 'web',      load: 0.10, glyph: GLYPHS.oracle },
    { id: 'ultron',     name: 'Ultron',     tier: 'SEC',     role: 'Security & Automation', model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'log',      load: 0.28, glyph: GLYPHS.ultron },
    // Foundation tier
    { id: 'gecko',      name: 'Gecko',      tier: 'FND',     role: 'Markets & Capital',     model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram', load: 0.38, glyph: GLYPHS.gecko },
    { id: 'hercules',   name: 'Hercules',   tier: 'FND',     role: 'Fitness & Nutrition',   model: 'gemma-4-26b',    status: 'idle',    heartbeat: true,  channel: 'telegram', load: 0.08, glyph: GLYPHS.hercules },
    { id: 'hephaestus', name: 'Hephaestus', tier: 'FND',     role: 'Builder & Mechanic',    model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram', load: 0.33, glyph: GLYPHS.hephaestus },
    { id: 'frigga',     name: 'Frigga',     tier: 'FND',     role: 'Family Matriarch',      model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'local',    load: 0.19, glyph: GLYPHS.frigga },
  ];

  const TIERS = [
    { id: 'CNS', label: 'Command — Nervous System', detail: 'Orchestration · Daily ops' },
    { id: 'BIZ', label: 'Business Intelligence',    detail: 'Strategy · Research · Comms' },
    { id: 'SEC', label: 'Security & Infrastructure',detail: 'Code · Workflows · Audit' },
    { id: 'FND', label: 'Foundation',               detail: 'Markets · Fitness · Family' },
  ];

  const SAMPLE_CONVERSATION = [
    {
      role: 'user',
      ts: '14:21:08',
      text: 'Cere lui Pepper agenda de mâine și verifică vremea pentru Cosmina, plec dimineața devreme.',
    },
    {
      role: 'agent',
      agent: 'jarvis',
      ts: '14:21:11',
      text: 'Pepper rulează agenda — primul slot 09:00 stand-up, două apeluri ferme la 11 și 15. Friday a interogat wttr.in pentru Cosmina: 11°C la 06:00, ploaie după 16:00. Recomand plecare 06:30, întoarcere înainte de 15:00.',
    },
    {
      role: 'user',
      ts: '14:22:34',
      text: 'Mută review-ul cu Steve după ora 17, vreau să prind asfalțitul uscat.',
    },
    {
      role: 'agent',
      agent: 'pepper',
      ts: '14:22:36',
      text: 'Confirmat. Mutat 17:30 → 18:15. Steve notificat pe Telegram, calendarul Google actualizat. Buffer 45 minute păstrat pentru drum.',
    },
  ];

  const NOTIFICATIONS = [
    { id: 'n1', agent: 'friday',   level: 'info',  ts: '14:18', text: 'Brief de dimineață gata. 3 articole flagged.' },
    { id: 'n2', agent: 'gecko',    level: 'warn',  ts: '13:54', text: 'BTC ↓ 2.3% în ultima oră. Threshold passed.' },
    { id: 'n3', agent: 'ultron',   level: 'ok',    ts: '13:30', text: 'Audit nocturn finalizat. 0 high-severity findings.' },
  ];

  const CALENDAR = [
    { ts: '09:00', title: 'Stand-up Raiffeisen',       owner: 'Pepper',  state: 'past' },
    { ts: '11:00', title: 'Athena · brief strategie',  owner: 'Athena',  state: 'next' },
    { ts: '15:00', title: 'Call Stark — KPI Q2',       owner: 'Stark',   state: 'upcoming' },
    { ts: '17:30', title: 'Review cod cu Steve',       owner: 'Steve',   state: 'upcoming' },
    { ts: '20:00', title: 'Cină Alexandra · Max bath', owner: 'Frigga',  state: 'upcoming' },
  ];

  const WEATHER = {
    city: 'București',
    temp: 22,
    desc: 'Înnorat cu deschideri',
    wind: '18 km/h NV',
    humidity: '64%',
    feels: 21,
    updated: '14:21',
    forecast: [
      { hr: '15', t: 22, code: 'cloud' },
      { hr: '16', t: 21, code: 'cloud' },
      { hr: '17', t: 19, code: 'rain'  },
      { hr: '18', t: 18, code: 'rain'  },
      { hr: '19', t: 17, code: 'cloud' },
    ],
  };

  const SYS = {
    host: 'BONOBO-WS',
    cpu: 'Intel Core Ultra 9 · 32c',
    ram_used: 86,   // GB
    ram_total: 192, // GB
    gpu: 'RTX 5090 · 24GB',
    vram_used: 16.76,
    vram_total: 24,
    gpu_load: 47,
    backend: 'LM Studio · 1234',
    model: 'gemma-4-26b-a4b',
    latency: 4.2,  // s
    uptime: '03:14:22',
    sessions: 7,
  };

  // Pre-canned demo conversation that plays when the user presses Send with empty input
  const DEMO_QUERY = {
    user: 'Care e statusul pe Digitaholic pipeline săptămâna asta?',
    route: ['jarvis', 'stark', 'veronica'],
    agent: 'stark',
    response: 'Pipeline: 4 lead-uri calde, 2 propuneri trimise. Răspuns așteptat de la WeCare până vineri. Veronica are draftul de follow-up gata — îți pun varianta scurtă în inbox în 5 minute.',
  };

  // Active tasks/projects each agent is working on (network satellite nodes)
  const TASKS = [
    // Daily ops
    { id: 't_pep_cal', owner: 'pepper',     project: 'Daily',       label: 'Cal sync',       state: 'running' },
    { id: 't_pep_inb', owner: 'pepper',     project: 'Daily',       label: 'Inbox triage',   state: 'queued'  },
    { id: 't_fri_am',  owner: 'friday',     project: 'Daily',       label: 'AM brief',       state: 'done'    },
    { id: 't_fri_news',owner: 'friday',     project: 'Daily',       label: 'News scrape',    state: 'running' },
    { id: 't_jer_mix', owner: 'jerome',     project: 'Leisure',     label: 'Evening mix',    state: 'queued'  },
    // Business — Raiffeisen
    { id: 't_stk_kpi', owner: 'stark',      project: 'Raiffeisen',  label: 'Q2 KPI deck',    state: 'running' },
    { id: 't_stk_nps', owner: 'stark',      project: 'Raiffeisen',  label: 'NPS deep-dive',  state: 'waiting' },
    { id: 't_ath_q3',  owner: 'athena',     project: 'Raiffeisen',  label: 'Q3 strategy',    state: 'queued'  },
    // Business — Digitaholic
    { id: 't_ver_li',  owner: 'veronica',   project: 'Digitaholic', label: 'LinkedIn draft', state: 'running' },
    { id: 't_ver_em',  owner: 'veronica',   project: 'Digitaholic', label: 'Email reply',    state: 'queued'  },
    { id: 't_vis_os',  owner: 'vision',     project: 'Digitaholic', label: 'OSINT · Acme',   state: 'running' },
    // Hub / infra
    { id: 't_stv_dep', owner: 'steve',      project: 'Hub',         label: 'Deploy v0.2.2',  state: 'running' },
    { id: 't_stv_ci',  owner: 'steve',      project: 'Hub',         label: 'CI fix · #284',  state: 'done'    },
    { id: 't_orc_n8n', owner: 'oracle',     project: 'Hub',         label: 'N8N workflow',   state: 'running' },
    { id: 't_ult_aud', owner: 'ultron',     project: 'Hub',         label: 'Nightly audit',  state: 'done'    },
    // Foundation
    { id: 't_gec_btc', owner: 'gecko',      project: 'Markets',     label: 'BTC alerts',     state: 'running' },
    { id: 't_her_push',owner: 'hercules',   project: 'Health',      label: 'Push day plan',  state: 'queued'  },
    { id: 't_hep_bmw', owner: 'hephaestus', project: 'Garage',      label: 'BMW service',    state: 'queued'  },
    { id: 't_hep_cos', owner: 'hephaestus', project: 'Cosmina',     label: 'Cosmina BOM',    state: 'running' },
    { id: 't_fri_max', owner: 'frigga',     project: 'Family',      label: 'Max sleep log',  state: 'running' },
    { id: 't_fri_dn',  owner: 'frigga',     project: 'Family',      label: 'Cină · Alex',    state: 'queued'  },
  ];

  const PROJECTS = [
    { id: 'Daily',       color: 'cyan',  label: 'Daily Ops' },
    { id: 'Raiffeisen',  color: 'amber', label: 'Raiffeisen CRM' },
    { id: 'Digitaholic', color: 'green', label: 'Digitaholic' },
    { id: 'Hub',         color: 'cyan',  label: 'Hub · Infra' },
    { id: 'Markets',     color: 'amber', label: 'Markets' },
    { id: 'Health',      color: 'green', label: 'Health' },
    { id: 'Garage',      color: 'amber', label: 'Garage' },
    { id: 'Cosmina',     color: 'green', label: 'Cosmina build' },
    { id: 'Family',      color: 'cyan',  label: 'Family' },
    { id: 'Leisure',     color: 'cyan',  label: 'Leisure' },
  ];

  // Agent ↔ agent collaboration edges (lateral, around the ring).
  // intensity = relative traffic 0-1, dir = 'both' | 'a-b' | 'b-a'
  const COLLAB = [
    { a: 'friday',    b: 'pepper',     intensity: 0.85, dir: 'both', label: 'daily brief' },
    { a: 'pepper',    b: 'frigga',     intensity: 0.55, dir: 'both', label: 'family sync' },
    { a: 'stark',     b: 'veronica',   intensity: 0.72, dir: 'a-b',  label: 'KPI → content' },
    { a: 'stark',     b: 'vision',     intensity: 0.68, dir: 'b-a',  label: 'OSINT feed' },
    { a: 'athena',    b: 'stark',      intensity: 0.62, dir: 'both', label: 'strategy ↔ KPI' },
    { a: 'steve',     b: 'oracle',     intensity: 0.40, dir: 'a-b',  label: 'CI → workflows' },
    { a: 'steve',     b: 'ultron',     intensity: 0.58, dir: 'both', label: 'deploy ↔ audit' },
    { a: 'hephaestus',b: 'gecko',      intensity: 0.30, dir: 'b-a',  label: 'budget' },
    { a: 'hercules',  b: 'frigga',     intensity: 0.25, dir: 'both', label: 'family · health' },
    { a: 'vision',    b: 'athena',     intensity: 0.50, dir: 'a-b',  label: 'research → strategy' },
  ];

  // Live activity events used by the situation ticker.
  // Cycle order matters — keep newest-first feel by repeating high-priority items.
  const TICKER = [
    { agent: 'stark',      verb: 'synthesizing',  obj: 'Q2 brief',            pct: 78,  pri: 'hi' },
    { agent: 'vision',     verb: 'parsing',       obj: '5 sources · Acme',    pct: 40,  pri: 'mid' },
    { agent: 'steve',      verb: 'deploying',     obj: 'v0.2.2 → staging',    pct: 92,  pri: 'hi' },
    { agent: 'ultron',     verb: '2 warnings',    obj: 'rate-limit · API ext',pri: 'warn' },
    { agent: 'friday',     verb: 'ranking',       obj: '12 RSS feeds',        pct: 64,  pri: 'mid' },
    { agent: 'pepper',     verb: 'rescheduled',   obj: '17:30 → 18:15',       pri: 'ok' },
    { agent: 'gecko',      verb: 'watching',      obj: 'BTC support 67.2k',   pri: 'mid' },
    { agent: 'hephaestus', verb: 'sourcing',      obj: 'Cosmina BOM · 14/22', pct: 64,  pri: 'mid' },
    { agent: 'veronica',   verb: 'drafted',       obj: 'LinkedIn · 2 var.',   pri: 'ok' },
    { agent: 'frigga',     verb: 'logged',        obj: 'Max sleep 2h45',      pri: 'ok' },
    { agent: 'athena',     verb: 'pricing memo',  obj: 'queued',              pri: 'mid' },
  ];

  return { AGENTS, TIERS, SAMPLE_CONVERSATION, NOTIFICATIONS, CALENDAR, WEATHER, SYS, DEMO_QUERY, TASKS, PROJECTS, COLLAB, TICKER };
})();
