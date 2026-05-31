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

// ─── v0.3 Cognition Data ─────────────────────────────────────────────────
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
  { keyword: 'raiffeisen',  weight: 0.85, agents: ['stark'],                         category: 'business' },
  { keyword: 'strategy',    weight: 0.73, agents: ['athena'],                        category: 'strategy' },
  { keyword: 'digitaholic', weight: 0.79, agents: ['athena'],                        category: 'business' },
  { keyword: 'money',       weight: 0.68, agents: ['gecko'],                         category: 'finance' },
  { keyword: 'budget',      weight: 0.72, agents: ['gecko'],                         category: 'finance' },
  { keyword: 'sleep',       weight: 0.76, agents: ['hercules'],                      category: 'health' },
  { keyword: 'workout',     weight: 0.74, agents: ['hercules'],                      category: 'health' },
  { keyword: 'cosmina',     weight: 0.83, agents: ['hephaestus'],                    category: 'project' },
  { keyword: 'bmw',         weight: 0.80, agents: ['hephaestus'],                    category: 'project' },
  { keyword: 'max',         weight: 0.70, agents: ['frigga'],                        category: 'family' },
  { keyword: 'family',      weight: 0.75, agents: ['frigga'],                        category: 'family' },
  { keyword: 'music',       weight: 0.66, agents: ['jerome'],                        category: 'leisure' },
  { keyword: 'playlist',    weight: 0.64, agents: ['jerome'],                        category: 'leisure' },
  { keyword: 'security',    weight: 0.78, agents: ['ultron'],                        category: 'infra' },
  { keyword: 'workflow',    weight: 0.71, agents: ['oracle'],                        category: 'infra' },
  { keyword: 'weather',     weight: 0.69, agents: ['friday'],                        category: 'daily' },
  { keyword: 'news',        weight: 0.67, agents: ['friday'],                        category: 'daily' },
];

const ROUTING_DECISION = {
  source: 'keyword_match',
  confidence: 0.84,
  agents_selected: ['pepper', 'stark'],
  alternatives: [
    { agent: 'veronica', score: 0.31 },
    { agent: 'friday',   score: 0.18 },
  ],
  timing: { classify: 12, route: 8, total: 20 },
};

const ORCHESTRATION_TRACE = [
  { step: 'classify',     duration_ms: 12,  result: 'keyword_match' },
  { step: 'route',        duration_ms: 8,   agents: ['pepper', 'stark'] },
  { step: 'plugin_data',  duration_ms: 145, plugins: ['gmail', 'google-calendar'] },
  { step: 'synthesize',   duration_ms: 890, tokens: 234 },
];

// ─── v0.3 Systems Data ───────────────────────────────────────────────────
const PLUGINS = {
  plugins: [
    { id: 'weather', name: 'Weather (wttr.in)', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['wttr.in'], agents_served: ['all'], enabled: true },
    { id: 'news', name: 'News (BBC RSS)', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['feeds.bbci.co.uk'], agents_served: ['all'], enabled: true },
    { id: 'cloud-llm', name: 'Cloud LLM Fallback', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'TRANSMITTED', allowed_domains: ['api.anthropic.com', 'api.openai.com'], agents_served: ['jarvis', 'athena', 'stark', 'vision', 'veronica'], enabled: true },
    { id: 'telegram', name: 'Telegram Bot', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'TRANSMITTED', allowed_domains: ['api.telegram.org'], agents_served: ['all'], enabled: true },
    { id: 'gmail', name: 'Gmail API', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['gmail.googleapis.com', 'www.googleapis.com'], agents_served: ['stark', 'pepper', 'veronica'], enabled: true },
    { id: 'google-calendar', name: 'Google Calendar API', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['www.googleapis.com'], agents_served: ['pepper'], enabled: true },
    { id: 'whatsapp-bridge', name: 'WhatsApp Local Bridge', version: '0.1.0', network_access: 'LAN', data_scope: 'LOCAL_ONLY', allowed_domains: [], agents_served: ['frigga'], enabled: true },
    { id: 'spotify', name: 'Spotify Control', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['api.spotify.com', 'accounts.spotify.com'], agents_served: ['jerome'], enabled: true },
    { id: 'apple-health', name: 'Apple Health Sync', version: '0.1.0', network_access: 'LAN', data_scope: 'LOCAL_ONLY', allowed_domains: [], agents_served: ['hercules'], enabled: true },
    { id: 'homebridge', name: 'Homebridge Smart Home', version: '0.1.0', network_access: 'LAN', data_scope: 'LOCAL_ONLY', allowed_domains: [], agents_served: ['jarvis', 'ultron'], enabled: true },
    { id: 'oracle-bridge', name: 'Oracle Pipeline Weaver', version: '0.1.0', network_access: 'RESTRICTED', data_scope: 'PROCESSED', allowed_domains: ['api.github.com'], agents_served: ['oracle'], enabled: true },
  ],
  total: 11,
};

const MEMORY_STATS = {
  sessions: { total: 47, current: '20260531-1423', active: 3 },
  vectors: { stored: 1284, dimension: 768, backend: 'qdrant' },
  knowledge_graph: { entities: 89, relations: 156, last_seed: '2026-05-30' },
  agent_contexts: { pepper: 12, stark: 8, friday: 15, jarvis: 22, vision: 6, frigga: 18 },
};

const LEARNING = {
  interactions_total: 847,
  success_rate: 0.91,
  prompt_optimizations: [
    { agent: 'jarvis', before: 'Summarize briefly', after: 'Provide structured summary with key points', improvement: '+12%' },
    { agent: 'pepper', before: 'Check calendar', after: 'Check calendar and suggest optimal scheduling', improvement: '+8%' },
    { agent: 'stark',  before: 'Report KPIs', after: 'Report KPIs with trend analysis and recommendations', improvement: '+15%' },
  ],
  promotion_candidates: [{ agent: 'howard', triggers: 23, threshold: 20 }],
  demotion_warnings: [],
};

const SECURITY = {
  guardrails: { mode: 'WARN', redact_count: 3, block_count: 0 },
  scanners: { secret: { patterns: 10, findings: 0 }, pii: { patterns: 6, findings: 2 } },
  ssrf: { enabled: true, blocked_requests: 1, max_redirects: 5 },
};

const BENCH = {
  latency: { p50: 4.2, p95: 7.8, p99: 12.1, unit: 's' },
  throughput: { rpm: 12, avg_tokens: 234 },
  by_agent: { jarvis: 4.1, pepper: 3.8, stark: 5.2, friday: 4.5, vision: 6.8, steve: 5.9, athena: 3.2 },
};

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
window.ROUTING_DECISION = ROUTING_DECISION;
window.ORCHESTRATION_TRACE = ORCHESTRATION_TRACE;
window.PLUGINS = PLUGINS;
window.MEMORY_STATS = MEMORY_STATS;
window.LEARNING = LEARNING;
window.SECURITY = SECURITY;
window.BENCH = BENCH;
window.DOSSIER = DOSSIER;
