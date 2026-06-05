/* HUD v2 · response types for the endpoints the cockpit consumes.
   Hand-written (the backend declares response_model on ~1/228 routes, so OpenAPI
   gives thin response types). The generated request/param types from /openapi.json
   are a follow-up (`openapi-typescript`, needs a running server). */

export interface StatusSys {
  host: string; cpu: string;
  ram_used: number; ram_total: number;
  gpu: string; vram_used: number; vram_total: number; gpu_load: number;
  backend: string; model: string;
  latency: number; uptime: string; sessions: number;
}

export interface StatusResp {
  version?: string;
  sys?: StatusSys;
  voice_state?: string;
  lm_online?: boolean;
  llm_backend?: string;
  active_model?: string | null;
  agents?: { id: string; status: string }[];
  agents_online?: number;
  agents_total?: number;
}

export interface AgentResp {
  id: string;
  name?: string;
  status?: string;
  model?: string;
  enabled?: boolean;
  has_heartbeat?: boolean;
  tier?: string;
  role?: string;
}
export interface AgentsResp { agents: AgentResp[]; }

export interface WeatherResp {
  city: string; temp: string; desc: string; wind: string;
  humidity: string; feels: string; updated: string;
  forecast: { d: string; t: string }[];
}
export interface DashboardResp {
  weather?: WeatherResp;
  calendar?: Record<string, unknown>[];
  notifications?: Record<string, unknown>[];
}

export interface TickerItem {
  agent: string; verb: string;
  obj?: string; text?: string;
  pct?: number; bar?: number;
  pri?: string; cls?: string;
}
export interface TickerResp { ticker: TickerItem[]; }

export interface TasksResp { tasks: Record<string, unknown>[]; }
