'use strict';
/* Jarvis Hub HUD — Live Data Adapter */
/* Loads from /api/agents, /status, /dashboard, /tasks; falls back to embedded mocks */

const JARVIS_GLYPHS = {
  jarvis:     'M0,-8 L7,-2 L4,7 L-4,7 L-7,-2 Z M0,-3 L0,3 M-3,0 L3,0',
  friday:     'M-7,0 L7,0 M-4,-4 L4,-4 M-5,4 L5,4 M-2,-7 L2,-7',
  pepper:     'M-6,-6 H6 V6 H-6 Z M-6,-2 H6 M-2,-6 V6',
  jerome:     'M-6,5 Q-6,-5 0,-5 Q6,-5 6,5 M-3,2 V-2 M3,2 V-2',
  athena:     'M0,-7 L6,3 L-6,3 Z M0,-1 V3',
  stark:      'M0,-7 L4,-1 L7,-1 L3,3 L5,7 L0,4 L-5,7 L-3,3 L-7,-1 L-4,-1 Z',
  veronica:   'M-7,-5 L7,-5 L4,5 L-4,5 Z M-4,-1 H4',
  vision:     'M-7,0 Q0,-6 7,0 Q0,6 -7,0 Z M0,-2 V2',
  steve:      'M-7,5 L-2,-5 L2,-5 L7,5 M-4,1 H4',
  oracle:     'M-6,-6 L0,0 L-6,6 M6,-6 L0,0 L6,6',
  ultron:     'M-7,-2 L0,-7 L7,-2 L7,3 L0,7 L-7,3 Z M0,-2 V2',
  gecko:      'M-7,3 L-3,-3 L0,2 L3,-5 L7,1',
  hercules:   'M-5,-7 L-5,7 M5,-7 L5,7 M-5,0 H5',
  hephaestus: 'M-7,7 L0,-7 L7,7 M-3,1 H3',
  frigga:     'M0,-7 Q-7,0 0,7 Q7,0 0,-7 Z M0,-3 V3 M-3,0 H3',
};
const JARVIS_TIERS = [
  { id: 'CNS', label: _t('tier.cns'), detail: _t('tier.cns_det') },
  { id: 'BIZ', label: _t('tier.biz'), detail: _t('tier.biz_det') },
  { id: 'SEC', label: _t('tier.sec'), detail: _t('tier.sec_det') },
  { id: 'FND', label: _t('tier.fnd'), detail: _t('tier.fnd_det') },
];
/* JARVIS_SAMPLE_CONVERSATION, JARVIS_PROJECTS, JARVIS_COLLAB, JARVIS_TICKER, JARVIS_DEMO — removed, live data only */

const JARVIS_FALLBACK_SYS = {
  host: _t('env.fallback_host'), cpu: _t('env.fallback_cpu'),
  ram_used: 42, ram_total: 192, gpu: _t('env.fallback_gpu'),
  vram_used: 10, vram_total: 24, gpu_load: 30,
  backend: _t('env.fallback_backend'), model: _t('env.fallback_model'),
  latency: 2.1, uptime: '—', sessions: 0,
};
const JARVIS_FALLBACK_WEATHER = {
  city: _t('data.city'), temp: '—', desc: _t('data.loading'),
  wind: '—', humidity: '—', feels: '—', updated: '—', forecast: [],
};
const JARVIS_FALLBACK_CALENDAR = [];
const JARVIS_FALLBACK_NOTIFICATIONS = [];
const JARVIS_AGENT_META = {
  jarvis:     { tier: 'CNS', role: 'Prime Orchestrator' },
  friday:     { tier: 'CNS', role: 'Daily Intel' },
  pepper:     { tier: 'CNS', role: 'Chief of Staff' },
  jerome:     { tier: 'CNS', role: 'Leisure & Soundtrack' },
  athena:     { tier: 'BIZ', role: 'External Strategist' },
  stark:      { tier: 'BIZ', role: 'Biz Intel' },
  veronica:   { tier: 'BIZ', role: 'Content & Comms' },
  vision:     { tier: 'BIZ', role: 'Deep Research / OSINT' },
  steve:      { tier: 'SEC', role: 'CTO / Builds' },
  oracle:     { tier: 'SEC', role: 'N8N Workflows' },
  ultron:     { tier: 'SEC', role: 'Security & Automation' },
  gecko:      { tier: 'FND', role: 'Markets & Capital' },
  hercules:   { tier: 'FND', role: 'Fitness & Nutrition' },
  hephaestus: { tier: 'FND', role: 'Builder & Mechanic' },
  frigga:     { tier: 'FND', role: 'Family Matriarch' },
};

async function loadJarvisData() {
  let agents = [];
  let sys = { ...JARVIS_FALLBACK_SYS };
  let weather = { ...JARVIS_FALLBACK_WEATHER };
  let calendar = [...JARVIS_FALLBACK_CALENDAR];
  let notifications = [...JARVIS_FALLBACK_NOTIFICATIONS];
  let tasks = [];
  let lmOnline = true;
  let statusAgents = [];

  // Fetch /api/agents for full agent list
  try {
    const r = await fetch('/api/agents');
    const d = await r.json();
    agents = (d.agents || []).map((a) => {
      const meta = JARVIS_AGENT_META[a.id] || { tier: 'FND', role: '' };
      return { ...a, tier: meta.tier, role: meta.role, glyph: JARVIS_GLYPHS[a.id] || '' };
    });
  } catch { /* fallback below */ }

  // Always fetch /status for live sys data (replaces static fallback)
  try {
    const r = await fetch('/status');
    const d = await r.json();
    if (d.sys) sys = { ...sys, ...d.sys };
    if (d.lm_online !== undefined) lmOnline = d.lm_online;
    if (agents.length === 0 && d.agents) statusAgents = d.agents;
  } catch {}

  // If agents failed, build from /status
  if (agents.length === 0) {
    agents = Object.entries(JARVIS_AGENT_META).map(([id, meta]) => {
      const sa = statusAgents.find((x) => x.id === id);
      return {
        id, name: id.charAt(0).toUpperCase() + id.slice(1),
        tier: meta.tier, role: meta.role,
        status: sa ? sa.status : 'idle',
        enabled: true, has_heartbeat: sa && sa.status !== 'idle',
model: 'google/gemma-4-31b-a4b',
        glyph: JARVIS_GLYPHS[id] || '',
      };
    });
  }

  // Fetch /dashboard
  try {
    const r = await fetch('/dashboard');
    const d = await r.json();
    if (d.weather) weather = d.weather;
    if (d.calendar) calendar = d.calendar;
    if (d.notifications) notifications = d.notifications;
  } catch {}

  // Fetch /tasks
  try {
    const r = await fetch('/tasks');
    const d = await r.json();
    tasks = d.tasks || [];
  } catch {}

  return { agents, sys, weather, calendar, notifications, tasks, lmOnline };
}

window.JARVIS_GLYPHS = JARVIS_GLYPHS;
window.JARVIS_TIERS = JARVIS_TIERS;
window.JARVIS_AGENT_META = JARVIS_AGENT_META;
window.JARVIS_FALLBACK_SYS = JARVIS_FALLBACK_SYS;
window.JARVIS_FALLBACK_WEATHER = JARVIS_FALLBACK_WEATHER;
window.JARVIS_FALLBACK_CALENDAR = JARVIS_FALLBACK_CALENDAR;
window.JARVIS_FALLBACK_NOTIFICATIONS = JARVIS_FALLBACK_NOTIFICATIONS;
window.loadJarvisData = loadJarvisData;
