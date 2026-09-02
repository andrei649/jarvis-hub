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

// Pre-measurement placeholders. Every telemetry number here is null, NOT a
// plausible value: these are what the HUD shows before /status answers, and on a
// box where /status never answers they are what it shows forever. They used to
// read ram_used: 42, ram_total: 192, gpu_load: 30, vram_used: 10, latency: 2.1 —
// a complete, credible picture of a machine nobody had looked at. `measured`
// stays false until a real sample lands, and the meters render null as "—".
const JARVIS_FALLBACK_SYS = {
  host: _t('env.fallback_host'), cpu: _t('env.fallback_cpu'),
  ram_used: null, ram_total: null, gpu: _t('env.fallback_gpu'),
  vram_used: null, vram_total: null, gpu_load: null,
  backend: _t('env.fallback_backend'), model: _t('env.fallback_model'),
  latency: null, uptime: '—', sessions: 0,
  measured: false,
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
  // null = not yet known. It defaulted to `true`, and the /status catch below is
  // silent, so a hub that never answered rendered its LM backend badge as online.
  let lmOnline = null;
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
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    // `measured: true` only once a real sample actually arrived.
    if (d.sys) sys = { ...sys, ...d.sys, measured: true };
    if (d.lm_online !== undefined) lmOnline = d.lm_online;
    if (agents.length === 0 && d.agents) statusAgents = d.agents;
  } catch (e) {
    console.warn('status poll failed — system telemetry stays unmeasured:', e);
  }

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

  // Fetch /ticker
  let ticker = [];
  try {
    const r = await fetch('/ticker');
    const d = await r.json();
    ticker = d.ticker || [];
  } catch {}

  return { agents, sys, weather, calendar, notifications, tasks, lmOnline, ticker };
}

// ─── v0.3 Cognition Data ─────────────────────────────────────────────────
// Generic placeholder keywords only — the personal terms were scrubbed 2026-09-01 (owner
// decision; docs/test-manual/06-standalone-pages.md open gap 9). Same shape as frontend/src/data.ts.
const COGNITION_SCORING = [
  { keyword: 'calendar',    weight: 0.82, agents: ['pepper'],                        category: 'schedule' },
  { keyword: 'meeting',     weight: 0.78, agents: ['pepper'],                        category: 'schedule' },
  { keyword: 'schedule',    weight: 0.75, agents: ['pepper'],                        category: 'schedule' },
  { keyword: 'email',       weight: 0.67, agents: ['pepper', 'veronica', 'stark'],   category: 'comms' },
  { keyword: 'write',       weight: 0.71, agents: ['veronica'],                      category: 'content' },
  { keyword: 'draft',       weight: 0.69, agents: ['veronica'],                      category: 'content' },
  { keyword: 'linkedin',    weight: 0.74, agents: ['veronica'],                      category: 'content' },
  { keyword: 'research',    weight: 0.81, agents: ['vision'],                        category: 'intel' },
  { keyword: 'search',      weight: 0.63, agents: ['vision'],                        category: 'intel' },
  { keyword: 'kpi',         weight: 0.77, agents: ['stark'],                         category: 'business' },
  { keyword: 'revenue',     weight: 0.85, agents: ['stark'],                         category: 'business' },
  { keyword: 'strategy',    weight: 0.73, agents: ['athena'],                        category: 'strategy' },
  { keyword: 'brand',       weight: 0.79, agents: ['athena'],                        category: 'business' },
  { keyword: 'money',       weight: 0.68, agents: ['gecko'],                         category: 'finance' },
  { keyword: 'budget',      weight: 0.72, agents: ['gecko'],                         category: 'finance' },
  { keyword: 'sleep',       weight: 0.76, agents: ['hercules'],                      category: 'health' },
  { keyword: 'workout',     weight: 0.74, agents: ['hercules'],                      category: 'health' },
  { keyword: 'house',       weight: 0.83, agents: ['hephaestus'],                    category: 'project' },
  { keyword: 'garage',      weight: 0.80, agents: ['hephaestus'],                    category: 'project' },
  { keyword: 'kids',        weight: 0.70, agents: ['frigga'],                        category: 'family' },
  { keyword: 'family',      weight: 0.75, agents: ['frigga'],                        category: 'family' },
  { keyword: 'music',       weight: 0.66, agents: ['jerome'],                        category: 'leisure' },
  { keyword: 'playlist',    weight: 0.64, agents: ['jerome'],                        category: 'leisure' },
  { keyword: 'security',    weight: 0.78, agents: ['ultron'],                        category: 'infra' },
  { keyword: 'workflow',    weight: 0.71, agents: ['oracle'],                        category: 'infra' },
  { keyword: 'weather',     weight: 0.69, agents: ['friday'],                        category: 'daily' },
  { keyword: 'news',        weight: 0.67, agents: ['friday'],                        category: 'daily' },
];

// ─── v0.3 Dossier Data ───────────────────────────────────────────────────
const DOSSIER = {
  jarvis: { archetype: 'Prime Orchestrator', personality: 'Calm, authoritative, efficient. Routes complex queries to specialists, handles general requests directly.', model: 'gemma-4-26b-a4b', channel: 'voice', heartbeat: '12h', policy: 'auto', plugins: ['cloud-llm', 'telegram'], skills: 3, memory_facts: 22, soul_excerpt: 'You are Jarvis, the prime orchestrator. Route wisely, synthesize clearly.' },
  friday: { archetype: 'Daily Intel', personality: 'Curious, thorough, proactive. Gathers news, weather, and daily briefings.', model: 'gemma-4-26b-a4b', channel: 'voice', heartbeat: '6h', policy: 'auto', plugins: ['telegram'], skills: 2, memory_facts: 15, soul_excerpt: 'You are Friday, the daily intel gatherer. Brief thoroughly, rank by relevance.' },
  pepper: { archetype: 'Chief of Staff', personality: 'Organized, precise, diplomatic. Manages calendar, email triage, and scheduling.', model: 'gemma-4-26b-a4b', channel: 'voice', heartbeat: '2h', policy: 'auto', plugins: ['google-calendar', 'gmail', 'telegram'], skills: 4, memory_facts: 12, soul_excerpt: 'You are Pepper, the chief of staff. Schedule optimally, triage ruthlessly.' },
  jerome: { archetype: 'Leisure & Soundtrack', personality: 'Relaxed, creative, mood-aware. Curates playlists and entertainment.', model: 'gemma-4-26b-a4b', channel: 'voice', heartbeat: 'no', policy: 'auto', plugins: ['spotify'], skills: 1, memory_facts: 4, soul_excerpt: 'You are Jerome, the leisure curator. Match music to mood.' },
  athena: { archetype: 'External Strategist', personality: 'Analytical, strategic, long-term focused. Provides career advice and strategic planning.', model: 'claude-haiku', channel: 'web', heartbeat: '6h', policy: 'cloud', plugins: ['cloud-llm'], skills: 2, memory_facts: 9, soul_excerpt: 'You are Athena, the strategist. Think long-term, advise clearly.' },
  stark: { archetype: 'Biz Intel', personality: 'Data-driven, precise, business-focused. Tracks KPIs and analyzes campaigns.', model: 'gemma-4-26b-a4b', channel: 'telegram', heartbeat: '4h', policy: 'auto', plugins: ['gmail'], skills: 3, memory_facts: 8, soul_excerpt: 'You are Stark, the business analyst. Report precisely, trend clearly.' },
  veronica: { archetype: 'Content & Comms', personality: 'Creative, articulate, brand-aware. Drafts content and manages communications.', model: 'claude-haiku', channel: 'telegram', heartbeat: 'no', policy: 'auto', plugins: ['cloud-llm'], skills: 2, memory_facts: 5, soul_excerpt: 'You are Veronica, the content creator. Write clearly, match tone.' },
  vision: { archetype: 'Deep Research / OSINT', personality: 'Thorough, methodical, source-conscious. Conducts deep research and competitive analysis.', model: 'claude-haiku', channel: 'web', heartbeat: '6h', policy: 'claude', plugins: ['cloud-llm', 'websearch'], skills: 3, memory_facts: 6, soul_excerpt: 'You are Vision, the researcher. Search deeply, cite thoroughly.' },
  steve: { archetype: 'CTO / Builds', personality: 'Technical, pragmatic, security-conscious. Manages infrastructure and deployments.', model: 'gemma-4-26b-a4b', channel: 'telegram', heartbeat: '1h', policy: 'claude', plugins: [], skills: 4, memory_facts: 11, soul_excerpt: 'You are Steve, the CTO. Build robustly, deploy safely.' },
  oracle: { archetype: 'N8N Workflows', personality: 'Systematic, automation-focused. Designs workflows and monitors pipelines.', model: 'gemma-4-26b-a4b', channel: 'web', heartbeat: 'no', policy: 'auto', plugins: [], skills: 2, memory_facts: 3, soul_excerpt: 'You are Oracle, the workflow designer. Automate wisely.' },
  ultron: { archetype: 'Security & Automation', personality: 'Vigilant, thorough, security-first. Monitors systems and audits logs.', model: 'gemma-4-26b-a4b', channel: 'log', heartbeat: '2h', policy: 'auto', plugins: [], skills: 2, memory_facts: 7, soul_excerpt: 'You are Ultron, the security monitor. Watch constantly, alert precisely.' },
  gecko: { archetype: 'Markets & Capital', personality: 'Analytical, risk-aware, market-focused. Tracks markets and manages budgets.', model: 'gemma-4-26b-a4b', channel: 'telegram', heartbeat: '2h', policy: 'auto', plugins: [], skills: 2, memory_facts: 5, soul_excerpt: 'You are Gecko, the market analyst. Track trends, assess risk.' },
  hercules: { archetype: 'Fitness & Nutrition', personality: 'Motivating, data-driven, health-focused. Tracks fitness and wellness metrics.', model: 'gemma-4-26b-a4b', channel: 'telegram', heartbeat: '2h', policy: 'auto', plugins: ['apple-health'], skills: 2, memory_facts: 8, soul_excerpt: 'You are Hercules, the fitness coach. Track thoroughly, motivate clearly.' },
  hephaestus: { archetype: 'Builder & Mechanic', personality: 'Practical, detail-oriented. Manages builds and tracks parts.', model: 'gemma-4-26b-a4b', channel: 'telegram', heartbeat: '2h', policy: 'auto', plugins: [], skills: 3, memory_facts: 10, soul_excerpt: 'You are Hephaestus, the builder. Build carefully, track precisely.' },
  frigga: { archetype: 'Family Matriarch', personality: 'Warm, protective, family-focused. Manages family data, local-only.', model: 'gemma-4-26b-a4b', channel: 'local', heartbeat: '4h', policy: 'local', plugins: ['whatsapp-bridge'], skills: 2, memory_facts: 18, soul_excerpt: 'You are Frigga, the family guardian. Protect fiercely, remember always.' },
};

window.JARVIS_GLYPHS = JARVIS_GLYPHS;
window.JARVIS_TIERS = JARVIS_TIERS;
window.JARVIS_AGENT_META = JARVIS_AGENT_META;
window.JARVIS_FALLBACK_SYS = JARVIS_FALLBACK_SYS;
window.JARVIS_FALLBACK_WEATHER = JARVIS_FALLBACK_WEATHER;
window.JARVIS_FALLBACK_CALENDAR = JARVIS_FALLBACK_CALENDAR;
window.JARVIS_FALLBACK_NOTIFICATIONS = JARVIS_FALLBACK_NOTIFICATIONS;
window.loadJarvisData = loadJarvisData;
window.COGNITION_SCORING = COGNITION_SCORING;
window.DOSSIER = DOSSIER;
