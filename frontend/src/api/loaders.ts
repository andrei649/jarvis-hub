/* HUD v2 · live-data loaders — fetch the real backend and map to the shapes the
   cockpit components expect. HONESTY CONTRACT: by default we show only what the
   backend actually returns; a tile with no real source stays EMPTY (the UI renders
   an honest "not connected" state) rather than inventing plausible data. The seeded
   demo corpus is used ONLY when `demo` is true (an explicit, watermarked mode), so
   the HUD never passes fiction off as fact. */
import { apiGet } from './client';
import type {
  StatusResp, AgentsResp, DashboardResp, TickerResp, TasksResp,
  LlmLiveState, LocalModelRef, ModelState,
} from './types';
import { runningTasks } from '../task-state';
// data.ts is the prototype's (untyped) mock — used ONLY as the opt-in demo corpus.
import { V2 } from '../data';

export type LlmState = ModelState;

export interface LiveSources {
  tasks: boolean;
  trust: boolean;
  [source: string]: boolean;
}

export interface JarvisData {
  demo: boolean;
  serverUp: boolean;       // /status answered (server reachable)
  live: boolean;           // real (non-demo) content is present on screen
  llm: LlmLiveState;
  agents: any[];
  sys: StatusResp['sys'] | null;
  ticker: any[];
  weather: any | null;
  calendar: any[];
  heartbeat: any[];
  tasks: any[];
  trust: { mic: string; strict_local: boolean; cloud_available?: boolean; claude_available?: boolean };
  sources: LiveSources;   // per-tile: did REAL data arrive in this load cycle?
}

const META: Record<string, { tier: string; role: string; name: string; model: string }> = {};
(V2.AGENTS as any[]).forEach((a) => { META[a.id] = { tier: a.tier, role: a.role, name: a.name, model: a.model }; });
const GLYPHS: Record<string, string> = V2.GLYPHS as any;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export async function loadJarvisData(demo = false): Promise<JarvisData> {
  // Default state is HONEST-EMPTY; only `demo` pre-fills the seeded corpus.
  const out: JarvisData = {
    demo,
    serverUp: false,
    live: false,
    llm: { state: 'unknown', model: null, residents: [] },
    agents: demo ? (V2.AGENTS as any[]) : [],
    sys: null,
    ticker: demo ? (V2.TICKER as any[]) : [],
    weather: demo ? V2.WEATHER : null,
    calendar: demo ? (V2.CALENDAR as any[]) : [],
    heartbeat: demo ? (V2.HEARTBEAT as any[]) : [],
    tasks: [],
    trust: { mic: 'on', strict_local: false },
    sources: { tasks: false, trust: false },
  };

  // 1) full enriched roster (real registry)
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

  // 2) live system + LLM readiness; /status is unguarded so it usually succeeds
  let statusAgents: { id: string; status: string }[] = [];
  try {
    const d = await apiGet<any>('/status');
    out.serverUp = true;
    if (d.sys) out.sys = d.sys;
    const residents: LocalModelRef[] = Array.isArray(d.resident_models)
      ? d.resident_models.flatMap((pair: unknown) => {
        if (!pair || typeof pair !== 'object') return [];
        const provider = typeof (pair as any).provider === 'string' ? (pair as any).provider.trim() : '';
        const id = typeof (pair as any).id === 'string' ? (pair as any).id.trim() : '';
        return provider && id ? [{ provider, id }] : [];
      })
      : [];
    if (d.model_state) out.llm = { state: d.model_state, model: d.loaded_model || null, residents };
    else if (d.lm_online !== undefined) out.llm = { state: d.lm_online ? 'no_model' : 'offline', model: null, residents };
    if (Array.isArray(d.agents)) statusAgents = d.agents;
  } catch { /* server unreachable */ }

  // 3) if /api/agents failed, build the roster from /status + static meta
  if (agents.length === 0 && statusAgents.length) {
    agents = Object.keys(META).map((id) => {
      const sa = statusAgents.find((x) => x.id === id);
      const m = META[id];
      return { id, name: m.name || cap(id), tier: m.tier, role: m.role, status: sa ? sa.status : 'idle', model: m.model || '', glyph: GLYPHS[id] || '' };
    });
  }
  if (agents.length) { out.agents = agents; out.sources.agents = true; }

  // 4) ambient: weather / calendar / heartbeat — real only when actually populated
  try {
    const d = await apiGet<DashboardResp>('/dashboard');
    const w = (d as any).weather;
    if (w && w.temp != null && String(w.temp) !== '—' && String(w.temp) !== '') {
      out.weather = normWeather(w); out.sources.weather = true;
    }
    if (Array.isArray(d.calendar) && d.calendar.length) { out.calendar = d.calendar.map(normCal); out.sources.calendar = true; }
    if (Array.isArray(d.notifications) && d.notifications.length) { out.heartbeat = d.notifications.map(normHb); out.sources.heartbeat = true; }
  } catch { /* not connected */ }

  // 5) tasks (autonomy queue) — empty is a valid, honest state
  try {
    const d = await apiGet<TasksResp>('/tasks?view=running');
    if (Array.isArray(d.tasks)) {
      out.tasks = runningTasks(d.tasks);
      out.sources.tasks = true;
    }
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
      out.sources.ticker = true;
    }
  } catch { /* keep [] */ }

  // 7) trust signal — mic state + strict-local (visible governance, H12.10)
  try {
    const d = await apiGet<any>('/api/trust/status');
    if (d && typeof d === 'object') {
      out.sources.trust = true;
      // Fail-closed parse. `d.mic || 'on'` used to turn a missing, empty or otherwise
      // falsy value into an affirmative permission, which defeated the wall's
      // "exact mic === 'on'" rule before the value ever reached it. Only the literal
      // strings authorize anything; everything else is 'unknown' and refuses capture.
      // `!!d.strict_local` likewise made the STRING "false" true — a false governance
      // claim that also feeds a derived 100% locality figure.
      out.trust = {
        mic: d.mic === 'on' ? 'on' : d.mic === 'off' ? 'off' : 'unknown',
        strict_local: d.strict_local === true,
        cloud_available: d.cloud_available === true,
        claude_available: d.claude_available === true,
      };
    }
  } catch { /* keep default */ }

  // "live" = at least one tile is showing REAL (non-demo) content
  out.live = Object.values(out.sources).some(Boolean);
  return out;
}

interface LatestRefreshRunnerOptions<TData, TLocality> {
  loadData: () => Promise<TData>;
  loadLocality?: () => Promise<TLocality>;
  commitData: (data: TData) => void;
  commitLocality: (locality: TLocality | null) => void;
}

/* Polls may overlap when a backend response takes longer than the interval.
   Only the newest cycle is allowed to publish either its primary snapshot or
   its follow-up locality evidence, so a late response cannot rewind the HUD. */
export function createLatestRefreshRunner<TData, TLocality>({
  loadData,
  loadLocality,
  commitData,
  commitLocality,
}: LatestRefreshRunnerOptions<TData, TLocality>) {
  let generation = 0;
  let stopped = false;
  const isCurrent = (id: number) => !stopped && id === generation;

  return {
    async refresh() {
      const id = ++generation;
      let data: TData;
      try {
        data = await loadData();
      } catch {
        return;
      }
      if (!isCurrent(id)) return;
      commitData(data);

      if (!loadLocality) {
        commitLocality(null);
        return;
      }
      try {
        const locality = await loadLocality();
        if (isCurrent(id)) commitLocality(locality);
      } catch {
        if (isCurrent(id)) commitLocality(null);
      }
    },
    stop() {
      stopped = true;
      generation += 1;
    },
  };
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
