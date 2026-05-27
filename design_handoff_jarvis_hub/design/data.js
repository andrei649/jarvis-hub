// Static reference data for the Jarvis Hub prototype.
// Mirrors the agents.yaml registry and mock ambient/conversation data.

window.JARVIS_DATA = (() => {
  const AGENTS = [
    // Command tier
    { id: 'jarvis',     name: 'Jarvis',     tier: 'CNS',     role: 'Prime Orchestrator',    model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'voice' },
    { id: 'friday',     name: 'Friday',     tier: 'CNS',     role: 'Daily Intel',           model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'voice' },
    { id: 'pepper',     name: 'Pepper',     tier: 'CNS',     role: 'Chief of Staff',        model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'voice' },
    { id: 'jerome',     name: 'Jerome',     tier: 'CNS',     role: 'Leisure & Soundtrack',  model: 'gemma-4-26b',    status: 'idle',    heartbeat: false, channel: 'voice' },
    // Business tier
    { id: 'athena',     name: 'Athena',     tier: 'BIZ',     role: 'External Strategist',   model: 'claude-haiku',   status: 'ready',   heartbeat: true,  channel: 'web' },
    { id: 'stark',      name: 'Stark',      tier: 'BIZ',     role: 'Biz Intel',             model: 'gemma-4-26b',    status: 'active',  heartbeat: true,  channel: 'telegram' },
    { id: 'veronica',   name: 'Veronica',   tier: 'BIZ',     role: 'Content & Comms',       model: 'claude-haiku',   status: 'idle',    heartbeat: false, channel: 'telegram' },
    { id: 'vision',     name: 'Vision',     tier: 'BIZ',     role: 'Deep Research / OSINT', model: 'claude-haiku',   status: 'ready',   heartbeat: true,  channel: 'web' },
    // Security / Tech tier
    { id: 'steve',      name: 'Steve',      tier: 'SEC',     role: 'CTO / Builds',          model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram' },
    { id: 'oracle',     name: 'Oracle',     tier: 'SEC',     role: 'N8N Workflows',         model: 'gemma-4-26b',    status: 'idle',    heartbeat: false, channel: 'web' },
    { id: 'ultron',     name: 'Ultron',     tier: 'SEC',     role: 'Security & Automation', model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'log' },
    // Foundation tier
    { id: 'gecko',      name: 'Gecko',      tier: 'FND',     role: 'Markets & Capital',     model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram' },
    { id: 'hercules',   name: 'Hercules',   tier: 'FND',     role: 'Fitness & Nutrition',   model: 'gemma-4-26b',    status: 'idle',    heartbeat: true,  channel: 'telegram' },
    { id: 'hephaestus', name: 'Hephaestus', tier: 'FND',     role: 'Builder & Mechanic',    model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'telegram' },
    { id: 'frigga',     name: 'Frigga',     tier: 'FND',     role: 'Family Matriarch',      model: 'gemma-4-26b',    status: 'ready',   heartbeat: true,  channel: 'local' },
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

  return { AGENTS, TIERS, SAMPLE_CONVERSATION, NOTIFICATIONS, CALENDAR, WEATHER, SYS, DEMO_QUERY };
})();
