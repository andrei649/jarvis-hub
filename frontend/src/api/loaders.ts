/* HUD v2 · live-data loaders — fetch the real backend and map to the shapes the
   cockpit components expect (the prototype shapes were lifted from product data.js,
   so they already match). Every fetch is independent and falls back to the seeded
   mock, so a partial/absent backend never blanks the HUD (recall-never-hard-fails). */
import { apiGet } from './client';
import type { StatusResp, AgentsResp, DashboardResp, TickerResp, TasksResp } from './types';
// data.ts is the prototype's (untyped) mock — used as the fallback corpus.
import { V2 } from '../data';

export interface JarvisData {
  live: boolean;
  agents: any[];
  sys: StatusResp['sys'] | null;
  ticker: any[];
  weather: any;
  calendar: any[];
  heartbeat: any[];
  tasks: any[];
  lmOnline: boolean;
  trust: { mic: string; strict_local: boolean; cloud_available?: boolean; claude_available?: boolean };
}

const META: Record<string, { tier: string; role: string; name: string; model: string }> = {};
(V2.AGENTS as any[]).forEach((a) => { META[a.id] = { tier: a.tier, role: a.role, name: a.name, model: a.model }; });
const GLYPHS: Record<string, string> = V2.GLYPHS as any;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export async function loadJarvisData(): Promise<JarvisData> {
  const out: JarvisData = {
    live: false,
    agents: V2.AGENTS as any[],
    sys: null,
    ticker: V2.TICKER as any[],
    weather: V2.WEATHER,
    calendar: V2.CALENDAR as any[],
    heartbeat: V2.HEARTBEAT as any[],
    tasks: [],
    lmOnline: true,
    trust: { mic: 'on', strict_local: false },
  };

  // 1) full enriched roster
  let agents: any[] = [];
  try {
    const d = await apiGet<AgentsResp>('/api/agents');
    agents = (d.agents || []).map((a) => {
      const m = META[a.id] || ({} as any);
      return {
        ...a,
        id: a.id,
        name: a.name || m.name || cap(a.id),
        tier: a.tier || m.tier || 'FND',
        role: a.role || m.role || '',
        status: a.status || 'idle',
        model: a.model || m.model || '',
        glyph: GLYPHS[a.id] || '',
      };
    });
  } catch { /* fall through */ }

  // 2) live system + (fallback) statuses; /status is unguarded so it usually succeeds
  let statusAgents: { id: string; status: string }[] = [];
  try {
    const d = await apiGet<StatusResp>('/status');
    out.live = true;
    if (d.sys) out.sys = d.sys;
    if (d.lm_online !== undefined) out.lmOnline = !!d.lm_online;
    if (Array.isArray(d.agents)) statusAgents = d.agents;
  } catch { /* keep mock sys */ }

  // 3) if /api/agents failed, build the roster from /status + static meta
  if (agents.length === 0 && statusAgents.length) {
    agents = Object.keys(META).map((id) => {
      const sa = statusAgents.find((x) => x.id === id);
      const m = META[id];
      return { id, name: m.name || cap(id), tier: m.tier, role: m.role, status: sa ? sa.status : 'idle', model: m.model || '', glyph: GLYPHS[id] || '' };
    });
  }
  if (agents.length) out.agents = agents;

  // 4) ambient: weather / calendar / heartbeat
  try {
    const d = await apiGet<DashboardResp>('/dashboard');
    if (d.weather) out.weather = normWeather(d.weather);
    if (Array.isArray(d.calendar) && d.calendar.length) out.calendar = d.calendar.map(normCal);
    if (Array.isArray(d.notifications) && d.notifications.length) out.heartbeat = d.notifications.map(normHb);
  } catch { /* keep mock */ }

  // 5) tasks (autonomy queue) — empty is a valid state
  try {
    const d = await apiGet<TasksResp>('/tasks');
    out.tasks = d.tasks || [];
  } catch { /* keep [] */ }

  // 6) situation ticker — map backend {obj,pct,pri} → UI {text,bar,cls}
  try {
    const d = await apiGet<TickerResp>('/ticker');
    if (Array.isArray(d.ticker) && d.ticker.length) {
      out.ticker = d.ticker.map((it) => ({
        agent: String(it.agent || '').toUpperCase(),
        verb: it.verb || '',
        text: it.text || it.obj || '',
        bar: it.bar != null ? it.bar : it.pct != null ? it.pct : 0,
        cls: it.cls || (({ high: 'hi', mid: 'mid', warn: 'warn', ok: 'ok' } as any)[it.pri || ''] || ''),
      }));
    }
  } catch { /* keep mock */ }

  // 7) trust signal — mic state + strict-local (visible governance, H12.10)
  try {
    const d = await apiGet<any>('/api/trust/status');
    if (d && typeof d === 'object') {
      out.trust = {
        mic: d.mic || 'on',
        strict_local: !!d.strict_local,
        cloud_available: !!d.cloud_available,
        claude_available: !!d.claude_available,
      };
    }
  } catch { /* keep default */ }

  return out;
}

function normWeather(w: any) {
  return {
    city: w.city || 'București', temp: w.temp ?? '—', desc: w.desc || '—',
    wind: w.wind || '—', humidity: w.humidity || '—', feels: w.feels || '—',
    updated: w.updated || '—', forecast: Array.isArray(w.forecast) ? w.forecast : [],
  };
}
function normCal(c: any) {
  return {
    tm: c.tm || c.time || c.start || '',
    ti: c.ti || c.title || c.summary || '',
    vw: c.vw || c.location || c.via || '',
    state: c.state || '',
  };
}
function normHb(n: any) {
  return {
    sev: n.sev || n.level || 'info',
    ag: String(n.ag || n.agent || '').toUpperCase(),
    t: n.t || n.time || '',
    x: n.x || n.text || n.message || '',
  };
}
