import type { ServerConfig } from '../storage/settings';
import { SseDecoder } from './sse';

/**
 * Thin client for the Jarvis hub HTTP API (agents/web.py).
 * The base URL and optional user token are supplied per call so the client
 * stays stateless and easy to drive from React context.
 */

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

const DEFAULT_TIMEOUT_MS = 15000;

/** Normalise user input into a usable origin: add scheme, strip trailing slashes. */
export function normalizeBaseUrl(raw: string): string {
  let url = (raw || '').trim();
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
  return url.replace(/\/+$/, '');
}

function authHeaders(config: ServerConfig, json: boolean, admin = false): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (json) headers['Content-Type'] = 'application/json';
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  if (admin && config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
  return headers;
}

function isRetryable(err: unknown): boolean {
  // Retry transient transport failures and 5xx, never auth/4xx.
  if (err instanceof ApiError) return err.status === undefined || err.status >= 500;
  return true;
}

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

type RequestOpts = { timeoutMs?: number; retries?: number; admin?: boolean };

async function request<T>(
  config: ServerConfig,
  method: 'GET' | 'POST' | 'DELETE',
  path: string,
  body?: unknown,
  opts: RequestOpts = {},
): Promise<T> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');

  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const retries = opts.retries ?? 0;

  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) await delay(Math.min(300 * 2 ** (attempt - 1), 4000));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(base + path, {
        method,
        headers: authHeaders(config, body !== undefined, opts.admin === true),
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (!res.ok) {
        if (res.status === 401) throw new ApiError('Unauthorized — check your user token', 401);
        throw new ApiError(`Server returned HTTP ${res.status}`, res.status);
      }
      return (await res.json()) as T;
    } catch (err) {
      lastErr = err;
      if (err instanceof DOMException && err.name === 'AbortError') {
        lastErr = new ApiError(`Request to ${base} timed out`);
      } else if (!(err instanceof ApiError)) {
        lastErr = new ApiError(`Could not reach ${base} — check the URL and network`);
      }
      if (attempt < retries && isRetryable(lastErr)) continue;
      throw lastErr;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

// ── Status ────────────────────────────────────────────────────────

export type SysInfo = {
  host: string;
  cpu: string;
  ram_used: number;
  ram_total: number;
  gpu: string;
  vram_used: number;
  vram_total: number;
  gpu_load: number;
  backend: string;
  model: string;
  latency: number;
  uptime: string;
  sessions: number;
};

export type StatusResponse = {
  status?: string;
  version?: string;
  sys?: SysInfo;
  lm_online?: boolean;
  model_state?: 'ready' | 'no_model' | 'offline' | string;
  model_loaded?: boolean;
  loaded_model?: string | null;
  llm_backend?: string;
  active_model?: string | null;
  agents?: { id: string; status: string }[];
  agents_online?: number;
  agents_total?: number;
};

export function fetchStatus(config: ServerConfig): Promise<StatusResponse> {
  return request<StatusResponse>(config, 'GET', '/status', undefined, { retries: 2 });
}

// ── Ambient dashboard + ticker ───────────────────────────────────

export type DashboardWeather = {
  city?: string;
  temp?: string;
  desc?: string;
  wind?: string;
  humidity?: string;
  feels?: string;
  updated?: string;
  forecast: Record<string, unknown>[];
  [key: string]: unknown;
};

export type DashboardResponse = {
  weather?: DashboardWeather;
  calendar: Record<string, unknown>[];
  notifications: Record<string, unknown>[];
};

export type TickerItem = {
  agent?: string;
  verb?: string;
  obj?: string;
  text: string;
  pct?: number;
  pri?: string;
  bar: number;
  cls: string;
  [key: string]: unknown;
};

export type TickerResponse = {
  ticker: TickerItem[];
};

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeWeather(value: unknown): DashboardWeather | undefined {
  if (!isRecord(value)) return undefined;
  return {
    ...value,
    forecast: recordArray(value.forecast),
  } as DashboardWeather;
}

function normalizeDashboard(raw: Partial<DashboardResponse>): DashboardResponse {
  return {
    weather: normalizeWeather(raw.weather),
    calendar: recordArray(raw.calendar),
    notifications: recordArray(raw.notifications),
  };
}

function normalizeTickerItem(value: unknown): TickerItem | null {
  if (!isRecord(value)) return null;
  const rawBar = value.bar ?? value.pct ?? 0;
  const bar = typeof rawBar === 'number' && Number.isFinite(rawBar) ? rawBar : 0;
  return {
    ...value,
    text: String(value.text ?? value.obj ?? ''),
    bar,
    cls: String(value.cls ?? value.pri ?? ''),
  } as TickerItem;
}

function normalizeTicker(raw: Partial<TickerResponse>): TickerResponse {
  const ticker = Array.isArray(raw.ticker)
    ? raw.ticker.map(normalizeTickerItem).filter((item): item is TickerItem => item !== null)
    : [];
  return { ticker };
}

export async function fetchDashboard(config: ServerConfig): Promise<DashboardResponse> {
  const res = await request<Partial<DashboardResponse>>(config, 'GET', '/dashboard', undefined, {
    retries: 2,
  });
  return normalizeDashboard(res || {});
}

export async function fetchTicker(config: ServerConfig): Promise<TickerResponse> {
  const res = await request<Partial<TickerResponse>>(config, 'GET', '/ticker', undefined, { retries: 2 });
  return normalizeTicker(res || {});
}

// ── Security / Trust ─────────────────────────────────────────────

export type SecurityScoreBlock = {
  score: number;
  passed: number;
  n: number;
};

export type SecurityOwaspBlock = {
  score: number;
  covered: number;
  total: number;
};

export type SecurityGovernanceResponse = {
  pass: boolean;
  overall_score: number;
  threshold: number;
  injection: SecurityScoreBlock;
  harm: SecurityScoreBlock;
  owasp: SecurityOwaspBlock;
};

export type SecurityPostureResponse = {
  secrets: {
    encrypted_at_rest: boolean;
    backend: string;
  };
  skills: {
    require_signed: boolean;
    total: number;
    trusted: number;
    untrusted: number;
    untrusted_names: string[];
  };
  sandbox: {
    backend: string;
    isolated: boolean;
    docker_available: boolean;
    insecure_host_exec: boolean;
  };
  guardrails: {
    mode: string;
  };
};

export type SecurityKillSwitchResponse = {
  global: boolean;
  halted: Record<string, unknown>;
};

export type SecurityLoopBreakerResponse = {
  tripped: boolean;
  threshold?: number;
  window_seconds?: number;
  [key: string]: unknown;
};

function securityNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function securityBool(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false;
}

function securityString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function securityRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function securityStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function normalizeSecurityScore(value: unknown): SecurityScoreBlock {
  const raw = securityRecord(value);
  return {
    score: securityNumber(raw.score),
    passed: securityNumber(raw.passed),
    n: securityNumber(raw.n),
  };
}

function normalizeSecurityOwasp(value: unknown): SecurityOwaspBlock {
  const raw = securityRecord(value);
  return {
    score: securityNumber(raw.score),
    covered: securityNumber(raw.covered),
    total: securityNumber(raw.total),
  };
}

function normalizeSecurityGovernance(raw: Record<string, unknown>): SecurityGovernanceResponse {
  return {
    pass: securityBool(raw.pass),
    overall_score: securityNumber(raw.overall_score),
    threshold: securityNumber(raw.threshold),
    injection: normalizeSecurityScore(raw.injection),
    harm: normalizeSecurityScore(raw.harm),
    owasp: normalizeSecurityOwasp(raw.owasp),
  };
}

function normalizeSecurityPosture(raw: Record<string, unknown>): SecurityPostureResponse {
  const secrets = securityRecord(raw.secrets);
  const skills = securityRecord(raw.skills);
  const sandbox = securityRecord(raw.sandbox);
  const guardrails = securityRecord(raw.guardrails);
  return {
    secrets: {
      encrypted_at_rest: securityBool(secrets.encrypted_at_rest),
      backend: securityString(secrets.backend),
    },
    skills: {
      require_signed: securityBool(skills.require_signed),
      total: securityNumber(skills.total),
      trusted: securityNumber(skills.trusted),
      untrusted: securityNumber(skills.untrusted),
      untrusted_names: securityStringArray(skills.untrusted_names),
    },
    sandbox: {
      backend: securityString(sandbox.backend),
      isolated: securityBool(sandbox.isolated),
      docker_available: securityBool(sandbox.docker_available),
      insecure_host_exec: securityBool(sandbox.insecure_host_exec),
    },
    guardrails: {
      mode: securityString(guardrails.mode),
    },
  };
}

function normalizeSecurityKillSwitch(raw: Record<string, unknown>): SecurityKillSwitchResponse {
  return {
    global: securityBool(raw.global),
    halted: securityRecord(raw.halted),
  };
}

function normalizeSecurityLoopBreaker(raw: Record<string, unknown>): SecurityLoopBreakerResponse {
  const out: SecurityLoopBreakerResponse = { tripped: securityBool(raw.tripped) };
  if (typeof raw.threshold === 'number' && Number.isFinite(raw.threshold)) out.threshold = raw.threshold;
  if (typeof raw.window_seconds === 'number' && Number.isFinite(raw.window_seconds)) {
    out.window_seconds = raw.window_seconds;
  }
  return out;
}

export async function fetchSecurityGovernance(config: ServerConfig): Promise<SecurityGovernanceResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/security/governance', undefined, {
    retries: 2,
  });
  return normalizeSecurityGovernance(res || {});
}

export async function fetchSecurityPosture(config: ServerConfig): Promise<SecurityPostureResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/security/posture', undefined, {
    retries: 2,
    admin: true,
  });
  return normalizeSecurityPosture(res || {});
}

export async function fetchSecurityKillSwitch(config: ServerConfig): Promise<SecurityKillSwitchResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/security/kill-switch', undefined, {
    retries: 2,
  });
  return normalizeSecurityKillSwitch(res || {});
}

export async function fetchSecurityLoopBreaker(config: ServerConfig): Promise<SecurityLoopBreakerResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/security/loop-breaker', undefined, {
    retries: 2,
  });
  return normalizeSecurityLoopBreaker(res || {});
}

// ── First-run command center (0.19 / H18.19) ─────────────────────

export interface CommandCenterWizardStep {
  key: string;
  title: string;
}

export interface CommandCenterAction {
  key: string;
  title: string;
  kind: string;
  path: string;
  ready: boolean;
  reason: string | null;
  folders?: string[];
}

export interface CommandCenterResponse {
  install: { ready: boolean; version: string; checks: Record<string, unknown> };
  model: {
    backend: string;
    active_model: string | null;
    ready: boolean | null;
    cloud_configured: boolean;
  };
  wizard: {
    steps: CommandCenterWizardStep[];
    completed: string[];
    complete: boolean;
    hint: string | null;
  };
  first_actions: CommandCenterAction[];
}

function normalizeCommandCenter(raw: Record<string, unknown>): CommandCenterResponse {
  const install = securityRecord(raw.install);
  const model = securityRecord(raw.model);
  const wizard = securityRecord(raw.wizard);
  const steps = Array.isArray(wizard.steps) ? wizard.steps : [];
  const actions = Array.isArray(raw.first_actions) ? raw.first_actions : [];
  return {
    install: {
      ready: securityBool(install.ready),
      version: securityString(install.version),
      checks: securityRecord(install.checks),
    },
    model: {
      backend: securityString(model.backend) || 'none',
      active_model: typeof model.active_model === 'string' ? model.active_model : null,
      ready: typeof model.ready === 'boolean' ? model.ready : null,
      cloud_configured: securityBool(model.cloud_configured),
    },
    wizard: {
      steps: steps
        .map((s) => securityRecord(s))
        .map((s) => ({ key: securityString(s.key), title: securityString(s.title) }))
        .filter((s) => s.key),
      completed: securityStringArray(wizard.completed),
      complete: securityBool(wizard.complete),
      hint: typeof wizard.hint === 'string' ? wizard.hint : null,
    },
    first_actions: actions
      .map((a) => securityRecord(a))
      .map((a) => ({
        key: securityString(a.key),
        title: securityString(a.title),
        kind: securityString(a.kind),
        path: securityString(a.path),
        ready: securityBool(a.ready),
        reason: typeof a.reason === 'string' ? a.reason : null,
        ...(Array.isArray(a.folders) ? { folders: securityStringArray(a.folders) } : {}),
      }))
      .filter((a) => a.key),
  };
}

export async function fetchCommandCenter(config: ServerConfig): Promise<CommandCenterResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/onboarding/command-center', undefined, {
    retries: 2,
  });
  return normalizeCommandCenter(res || {});
}

// ── Skills ───────────────────────────────────────────────────────

export type HubSkill = {
  key: string;
  name: string;
  version: string;
  description: string;
  agents: string[];
  commands: unknown[];
};

export type SkillsResponse = {
  skills: HubSkill[];
};

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function unknownArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function normalizeSkill(key: string, value: unknown): HubSkill {
  if (!isRecord(value)) {
    return { key, name: key, version: '', description: '', agents: [], commands: [] };
  }
  const name = stringValue(value.name) || key || stringValue(value.id);
  return {
    key: key || name,
    name,
    version: stringValue(value.version),
    description: stringValue(value.description),
    agents: stringArray(value.agents),
    commands: unknownArray(value.commands),
  };
}

function normalizeSkills(raw: Partial<SkillsResponse> | Record<string, unknown>): SkillsResponse {
  const source = (raw as { skills?: unknown }).skills;
  if (Array.isArray(source)) {
    const skills = source.map((item, index) => {
      const key = isRecord(item) ? stringValue(item.key) || stringValue(item.id) || stringValue(item.name) : '';
      return normalizeSkill(key || String(index), item);
    });
    return { skills: skills.sort((a, b) => a.name.localeCompare(b.name)) };
  }
  if (!isRecord(source)) return { skills: [] };
  const skills = Object.entries(source).map(([key, value]) => normalizeSkill(key, value));
  return { skills: skills.sort((a, b) => a.name.localeCompare(b.name)) };
}

export async function fetchSkills(config: ServerConfig): Promise<SkillsResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/skills', undefined, { retries: 2 });
  return normalizeSkills(res || {});
}

// ── Memory + Notes ───────────────────────────────────────────────

export type MemoryTurn = {
  role: string;
  content: string;
  agent_id?: string;
  timestamp?: string;
  [key: string]: unknown;
};

export type MemoryResponse = {
  session?: string;
  turns: MemoryTurn[];
};

export type NotesResponse = {
  session?: string;
  content: string;
};

function normalizeMemoryTurn(value: unknown): MemoryTurn | null {
  if (!isRecord(value)) return null;
  return {
    ...value,
    role: String(value.role ?? ''),
    content: String(value.content ?? ''),
    agent_id: typeof value.agent_id === 'string' ? value.agent_id : undefined,
    timestamp: typeof value.timestamp === 'string' ? value.timestamp : undefined,
  };
}

function normalizeMemory(raw: Record<string, unknown>): MemoryResponse {
  const turns = Array.isArray(raw.turns)
    ? raw.turns.map(normalizeMemoryTurn).filter((turn): turn is MemoryTurn => turn !== null)
    : [];
  const session = raw.session === undefined || raw.session === null ? undefined : String(raw.session);
  return session === undefined ? { turns } : { session, turns };
}

function normalizeNotes(raw: Record<string, unknown>): NotesResponse {
  const session = raw.session === undefined || raw.session === null ? undefined : String(raw.session);
  const content = typeof raw.content === 'string' ? raw.content : '';
  return session === undefined ? { content } : { session, content };
}

export async function fetchMemory(config: ServerConfig): Promise<MemoryResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/memory', undefined, { retries: 2 });
  return normalizeMemory(res || {});
}

export async function fetchNotes(config: ServerConfig): Promise<NotesResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/notes', undefined, { retries: 2 });
  return normalizeNotes(res || {});
}

// ── Knowledge Graph ──────────────────────────────────────────────

export type KnowledgeEntity = {
  name: string;
  type: string;
  properties: Record<string, unknown>;
  [key: string]: unknown;
};

export type KnowledgeRelation = {
  source: string;
  relation: string;
  target: string;
  properties: Record<string, unknown>;
  [key: string]: unknown;
};

export type KnowledgeFact = {
  id?: number | string;
  subject: string;
  predicate: string;
  object: string;
  valid_from?: number;
  valid_to?: number | null;
  ingested_at?: number;
  invalidated_at?: number | null;
  [key: string]: unknown;
};

export type KgEntitiesResponse = {
  entities: KnowledgeEntity[];
  total: number;
};

export type KgEntityResponse = {
  entity?: KnowledgeEntity;
  relations: KnowledgeRelation[];
};

export type KgFactsResponse = {
  at?: number | string | null;
  facts: KnowledgeFact[];
};

export type KgFactHistoryResponse = {
  subject?: string;
  history: KnowledgeFact[];
};

export type KgEntityQuery = {
  query?: string;
  limit?: number;
};

export type KgFactQuery = {
  at?: number;
  subject?: string;
  predicate?: string;
};

function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return query ? `?${query}` : '';
}

function normalizeKnowledgeEntity(value: unknown): KnowledgeEntity | null {
  if (!isRecord(value)) return null;
  const name = String(value.name ?? '').trim();
  if (!name) return null;
  return {
    ...value,
    name,
    type: String(value.type ?? 'unknown'),
    properties: recordValue(value.properties),
  };
}

function normalizeKnowledgeRelation(value: unknown): KnowledgeRelation | null {
  if (!isRecord(value)) return null;
  return {
    ...value,
    source: String(value.source ?? ''),
    relation: String(value.relation ?? ''),
    target: String(value.target ?? ''),
    properties: recordValue(value.properties),
  };
}

function normalizeKnowledgeFact(value: unknown): KnowledgeFact | null {
  if (!isRecord(value)) return null;
  const subject = String(value.subject ?? '').trim();
  const predicate = String(value.predicate ?? '').trim();
  const object = String(value.object ?? '').trim();
  if (!subject && !predicate && !object) return null;
  return {
    ...value,
    subject,
    predicate,
    object,
  } as KnowledgeFact;
}

function normalizeKgEntities(raw: Record<string, unknown>): KgEntitiesResponse {
  const entities = Array.isArray(raw.entities)
    ? raw.entities
        .map(normalizeKnowledgeEntity)
        .filter((entity): entity is KnowledgeEntity => entity !== null)
    : [];
  const rawTotal = typeof raw.total === 'number' && Number.isFinite(raw.total) ? raw.total : entities.length;
  return { entities, total: rawTotal };
}

function normalizeKgEntity(raw: Record<string, unknown>): KgEntityResponse {
  const entity = normalizeKnowledgeEntity(raw.entity);
  const relations = Array.isArray(raw.relations)
    ? raw.relations
        .map(normalizeKnowledgeRelation)
        .filter((relation): relation is KnowledgeRelation => relation !== null)
    : [];
  return entity ? { entity, relations } : { relations };
}

function normalizeKgFacts(raw: Record<string, unknown>): KgFactsResponse {
  const facts = Array.isArray(raw.facts)
    ? raw.facts.map(normalizeKnowledgeFact).filter((fact): fact is KnowledgeFact => fact !== null)
    : [];
  return raw.at === undefined ? { facts } : { at: raw.at as number | string | null, facts };
}

function normalizeKgFactHistory(raw: Record<string, unknown>): KgFactHistoryResponse {
  const history = Array.isArray(raw.history)
    ? raw.history.map(normalizeKnowledgeFact).filter((fact): fact is KnowledgeFact => fact !== null)
    : [];
  const subject = raw.subject === undefined || raw.subject === null ? undefined : String(raw.subject);
  return subject === undefined ? { history } : { subject, history };
}

export async function fetchKgEntities(
  config: ServerConfig,
  query: KgEntityQuery = {},
): Promise<KgEntitiesResponse> {
  const qs = buildQuery({ q: query.query, limit: query.limit ?? 50 });
  const res = await request<Record<string, unknown>>(config, 'GET', `/api/kg/entities${qs}`, undefined, {
    retries: 2,
  });
  return normalizeKgEntities(res || {});
}

export async function fetchKgEntity(config: ServerConfig, name: string): Promise<KgEntityResponse> {
  const res = await request<Record<string, unknown>>(
    config,
    'GET',
    `/api/kg/entities/${encodeURIComponent(name)}`,
    undefined,
    { retries: 2 },
  );
  return normalizeKgEntity(res || {});
}

export async function fetchKgFacts(config: ServerConfig, query: KgFactQuery = {}): Promise<KgFactsResponse> {
  const qs = buildQuery({ at: query.at, subject: query.subject, predicate: query.predicate });
  const res = await request<Record<string, unknown>>(config, 'GET', `/api/kg/facts/as-of${qs}`, undefined, {
    retries: 2,
  });
  return normalizeKgFacts(res || {});
}

export async function fetchKgFactHistory(
  config: ServerConfig,
  subject: string,
  predicate = '',
): Promise<KgFactHistoryResponse> {
  const qs = buildQuery({ subject, predicate });
  const res = await request<Record<string, unknown>>(config, 'GET', `/api/kg/facts/history${qs}`, undefined, {
    retries: 2,
  });
  return normalizeKgFactHistory(res || {});
}

// ── Canvas artifacts (H18.20 — governed Agent Canvas parity) ─────

/** Canvas bounds Markdown bodies to 4,000 chars (agents/core/canvas.py). */
export const CANVAS_MARKDOWN_LIMIT = 4000;

export type CanvasArtifact = {
  id: string;
  agent: string;
  type: string;
  payload: Record<string, unknown>;
  pinned: boolean;
  created_at?: number;
};

export type CanvasListResponse = { elements: CanvasArtifact[] };

function normalizeCanvasArtifact(raw: unknown): CanvasArtifact | null {
  if (!raw || typeof raw !== 'object') return null;
  const el = raw as Record<string, unknown>;
  if (typeof el.id !== 'string' || !el.id) return null;
  return {
    id: el.id,
    agent: typeof el.agent === 'string' ? el.agent : 'agent',
    type: typeof el.type === 'string' ? el.type : 'unknown',
    payload: el.payload && typeof el.payload === 'object' ? (el.payload as Record<string, unknown>) : {},
    pinned: el.pinned === true,
    created_at: typeof el.created_at === 'number' ? el.created_at : undefined,
  };
}

export async function fetchCanvasArtifacts(config: ServerConfig): Promise<CanvasListResponse> {
  const res = await request<Record<string, unknown>>(config, 'GET', '/api/canvas', undefined, { retries: 2 });
  const rawElements = Array.isArray(res?.elements) ? res.elements : [];
  const elements: CanvasArtifact[] = [];
  for (const raw of rawElements) {
    const el = normalizeCanvasArtifact(raw);
    if (el) elements.push(el);
  }
  return { elements };
}

export type SaveCanvasResult = { element: CanvasArtifact | null; truncated: boolean };

/**
 * Explicitly save a completed assistant reply as a governed markdown artifact —
 * the exact unchanged POST /api/canvas/post contract the browser cockpit uses.
 * Truncates at the canvas bound on a CODE-POINT boundary so an astral char at
 * the limit is never split into a lone UTF-16 surrogate.
 */
export async function saveCanvasArtifact(
  config: ServerConfig,
  args: { agent: string; body: string },
): Promise<SaveCanvasResult> {
  const cps = Array.from(args.body || '');
  const truncated = cps.length > CANVAS_MARKDOWN_LIMIT;
  const body = truncated ? cps.slice(0, CANVAS_MARKDOWN_LIMIT).join('') : args.body;
  const res = await request<Record<string, unknown>>(config, 'POST', '/api/canvas/post', {
    agent: args.agent || 'jarvis',
    type: 'markdown',
    payload: { title: 'Saved response', body },
    pinned: false,
  });
  return { element: normalizeCanvasArtifact(res), truncated };
}

export async function pinCanvasArtifact(
  config: ServerConfig,
  id: string,
  pinned: boolean,
): Promise<CanvasArtifact | null> {
  const res = await request<Record<string, unknown>>(
    config,
    'POST',
    `/api/canvas/${encodeURIComponent(id)}/pin?pinned=${pinned}`,
  );
  return normalizeCanvasArtifact(res);
}

export async function deleteCanvasArtifact(
  config: ServerConfig,
  id: string,
): Promise<{ removed: boolean }> {
  const res = await request<Record<string, unknown>>(
    config,
    'DELETE',
    `/api/canvas/${encodeURIComponent(id)}`,
  );
  return { removed: res?.removed === true };
}

// ── Tasks ────────────────────────────────────────────────────────

export type HubTask = {
  id?: number | string;
  owner?: string;
  agent_id?: string;
  agent?: string;
  kind?: string;
  title?: string;
  label?: string;
  project?: string;
  status?: string;
  state?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type TasksResponse = {
  tasks: HubTask[];
};

function hubTaskArray(value: unknown): HubTask[] {
  return Array.isArray(value) ? (value as HubTask[]) : [];
}

export async function fetchTasks(config: ServerConfig): Promise<TasksResponse> {
  const res = await request<Partial<TasksResponse>>(config, 'GET', '/tasks', undefined, { retries: 2 });
  return { tasks: hubTaskArray(res?.tasks) };
}

// ── Approvals ────────────────────────────────────────────────────

export type ApprovalAction = 'accept' | 'reject' | 'defer';

export type RollbackContract = {
  mode: 'none' | 'cancel' | 'compensate' | 'restore' | 'revoke' | 'disable' | 'implementation_specific';
  description: string;
  automatic: boolean;
  handler_ref?: string | null;
  limitations?: string;
};

export type ApprovalTask = {
  id: number;
  agent?: string;
  kind?: string;
  title?: string;
  payload?: Record<string, unknown>;
  risk_tier?: number;
  status?: string;
  autonomy_level?: string;
  origin?: string;
  reversible?: boolean;
  reversibility?: string;
  tier_name?: string;
  capability_id?: string | null;
  rollback?: RollbackContract | null;
  created_at?: string;
  updated_at?: string;
};

export type ApprovalCounts = {
  total: number;
  reversible: number;
  irreversible: number;
};

export type ApprovalsResponse = {
  pending: ApprovalTask[];
  reversible: ApprovalTask[];
  irreversible: ApprovalTask[];
  counts: ApprovalCounts;
};

function taskArray(value: unknown): ApprovalTask[] {
  return Array.isArray(value) ? (value as ApprovalTask[]) : [];
}

function normalizeApprovals(raw: Partial<ApprovalsResponse>): ApprovalsResponse {
  const pending = taskArray(raw.pending);
  const reversible = taskArray(raw.reversible);
  const irreversible = taskArray(raw.irreversible);
  return {
    pending,
    reversible,
    irreversible,
    counts: {
      total: Number(raw.counts?.total ?? pending.length),
      reversible: Number(raw.counts?.reversible ?? reversible.length),
      irreversible: Number(raw.counts?.irreversible ?? irreversible.length),
    },
  };
}

export async function fetchApprovals(config: ServerConfig): Promise<ApprovalsResponse> {
  const res = await request<Partial<ApprovalsResponse>>(config, 'GET', '/autonomy/approvals', undefined, {
    retries: 2,
    admin: true,
  });
  return normalizeApprovals(res || {});
}

export type ApprovalDecisionResponse = {
  ok?: boolean;
  task?: ApprovalTask;
};

export function decideApproval(
  config: ServerConfig,
  taskId: number,
  action: ApprovalAction,
): Promise<ApprovalDecisionResponse> {
  return request<ApprovalDecisionResponse>(
    config,
    'POST',
    `/autonomy/tasks/${encodeURIComponent(String(taskId))}/decision`,
    { action },
    { admin: true },
  );
}

// ── Channel Inbox ────────────────────────────────────────────────

export type ChannelInboxThread = {
  id?: string;
  thread_id: string;
  channel?: string;
  sender?: string;
  from?: string;
  subj?: string;
  preview?: string;
  ts?: number;
  count?: number;
  unread?: boolean;
  reply?: Record<string, unknown>;
  last_message_id?: string;
};

export type ChannelInboxMessage = {
  id: string;
  thread_id?: string;
  channel?: string;
  direction?: 'in' | 'out' | string;
  sender?: string;
  text?: string;
  preview?: string;
  reply?: Record<string, unknown>;
  reply_to?: string;
  ts?: number;
};

export type ChannelInboxResponse = {
  threads: ChannelInboxThread[];
};

export type ChannelThreadResponse = {
  thread?: ChannelInboxThread;
  messages: ChannelInboxMessage[];
};

export type ChannelReplyResponse = {
  ok?: boolean;
  queued?: boolean;
  task_id?: number | string;
  reason?: string;
  error?: string;
};

function channelThreadArray(value: unknown): ChannelInboxThread[] {
  return Array.isArray(value) ? (value as ChannelInboxThread[]) : [];
}

function channelMessageArray(value: unknown): ChannelInboxMessage[] {
  return Array.isArray(value) ? (value as ChannelInboxMessage[]) : [];
}

function normalizeChannelInbox(raw: Partial<ChannelInboxResponse>): ChannelInboxResponse {
  return { threads: channelThreadArray(raw.threads) };
}

function normalizeChannelThread(raw: Partial<ChannelThreadResponse>): ChannelThreadResponse {
  return {
    thread: raw.thread,
    messages: channelMessageArray(raw.messages),
  };
}

export async function fetchChannelInbox(config: ServerConfig): Promise<ChannelInboxResponse> {
  const res = await request<Partial<ChannelInboxResponse>>(config, 'GET', '/api/channels/inbox', undefined, {
    retries: 2,
  });
  return normalizeChannelInbox(res || {});
}

export async function fetchChannelThread(
  config: ServerConfig,
  threadId: string,
): Promise<ChannelThreadResponse> {
  const encoded = encodeURIComponent(threadId);
  const res = await request<Partial<ChannelThreadResponse>>(
    config,
    'GET',
    `/api/channels/inbox/${encoded}`,
    undefined,
    { retries: 2 },
  );
  return normalizeChannelThread(res || {});
}

export function sendChannelReply(
  config: ServerConfig,
  threadId: string,
  text: string,
  agent = 'jarvis',
): Promise<ChannelReplyResponse> {
  return request<ChannelReplyResponse>(
    config,
    'POST',
    `/api/channels/inbox/${encodeURIComponent(threadId)}/reply`,
    { text, agent, source: 'mobile' },
  );
}

// ── Agents ────────────────────────────────────────────────────────

export type AgentInfo = {
  id: string;
  name: string;
  tier?: string;
  role?: string;
  status?: string;
  enabled?: boolean;
  model?: string;
};

export async function fetchAgents(config: ServerConfig): Promise<AgentInfo[]> {
  const res = await request<{ agents: AgentInfo[] }>(config, 'GET', '/api/agents', undefined, {
    retries: 2,
  });
  return res.agents ?? [];
}

// ── Sessions ──────────────────────────────────────────────────────

export type SessionInfo = {
  id: string;
  agent_id?: string;
  started_at?: string;
  ended_at?: string;
  turn_count?: number;
  summary?: string;
};

export type HistoryTurn = {
  role: string;
  content: string;
  agent_id?: string | null;
  timestamp?: string;
};

export async function fetchSessions(config: ServerConfig): Promise<SessionInfo[]> {
  const res = await request<{ sessions: SessionInfo[] }>(config, 'GET', '/sessions', undefined, {
    retries: 2,
  });
  return res.sessions ?? [];
}

export async function resumeSession(
  config: ServerConfig,
  sessionId: string,
): Promise<{ ok: boolean; session: string; turns: HistoryTurn[] }> {
  return request(config, 'POST', '/sessions/resume', { session_id: sessionId });
}

// ── TTS ───────────────────────────────────────────────────────────

/** POST /tts and return the synthesized MP3 as base64 (for expo-file-system). */
export async function ttsFetchBase64(config: ServerConfig, text: string, lang: string): Promise<string> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  let res: Response;
  try {
    res = await fetch(base + '/tts', {
      method: 'POST',
      headers: { ...authHeaders(config, true), Accept: 'audio/mpeg' },
      body: JSON.stringify({ text, lang }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw new ApiError('TTS request timed out');
    throw new ApiError(`Could not reach ${base} — check the URL and network`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    throw new ApiError(
      res.status === 401 ? 'Unauthorized — check your user token' : `TTS failed (HTTP ${res.status})`,
      res.status,
    );
  }
  return blobToBase64(await res.blob());
}

/** Read a Blob as a bare base64 string (data-URL prefix stripped). */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new ApiError('Could not read TTS audio'));
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        const comma = result.indexOf(',');
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      } else {
        reject(new ApiError('Unexpected TTS audio format'));
      }
    };
    reader.readAsDataURL(blob);
  });
}

// ── Chat (streaming SSE over XHR) ─────────────────────────────────

export type StreamHandlers = {
  onStart?: (agent: string) => void;
  onToken: (text: string) => void;
  onDone: (full: string) => void;
  onError: (message: string) => void;
};

/** Abort the stream if no data arrives for this long. */
const STREAM_IDLE_TIMEOUT_MS = 45000;

/**
 * POST /chat/stream and surface server-sent events incrementally.
 * React Native's fetch has no readable-stream body, so we use XHR and read
 * responseText as it grows. Returns a cancel function that aborts the request.
 */
export function streamChat(
  config: ServerConfig,
  message: string,
  agent: string,
  handlers: StreamHandlers,
): () => void {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) {
    handlers.onError('No server URL configured');
    return () => {};
  }

  const xhr = new XMLHttpRequest();
  const decoder = new SseDecoder();
  let consumed = 0; // chars of responseText already scanned
  let finished = false;
  let settled = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const cleanup = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = null;
  };
  const finish = (fn: () => void) => {
    if (settled) return;
    settled = true;
    cleanup();
    fn();
  };
  const armIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      try {
        xhr.abort();
      } catch {
        // ignore
      }
      finish(() => handlers.onError('Stream stalled — no response from the hub'));
    }, STREAM_IDLE_TIMEOUT_MS);
  };

  const handleEvents = (chunk: string) => {
    for (const evt of decoder.push(chunk)) {
      if (evt.type === 'start') handlers.onStart?.(evt.agent || agent);
      else if (evt.type === 'token') handlers.onToken(evt.text || '');
      else if (evt.type === 'end') {
        finished = true;
        finish(() => handlers.onDone(evt.text || ''));
      }
    }
  };

  xhr.open('POST', base + '/chat/stream');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.setRequestHeader('Accept', 'text/event-stream');
  if (config.token.trim()) xhr.setRequestHeader('X-User-Token', config.token.trim());

  xhr.onreadystatechange = () => {
    if (xhr.readyState >= 3 && xhr.status === 200) {
      armIdle();
      const text = xhr.responseText;
      if (text.length > consumed) {
        handleEvents(text.slice(consumed));
        consumed = text.length;
      }
    }
    if (xhr.readyState === 4) {
      if (xhr.status === 0) return; // aborted
      if (xhr.status !== 200) {
        finish(() =>
          handlers.onError(
            xhr.status === 401 ? 'Unauthorized — check your user token' : `Server returned HTTP ${xhr.status}`,
          ),
        );
      } else if (!finished) {
        // Stream closed without an explicit end frame — flush any tail.
        handleEvents('\n');
        finish(() => handlers.onDone(''));
      }
    }
  };
  xhr.onerror = () => finish(() => handlers.onError(`Could not reach ${base} — check the URL and network`));

  armIdle();
  xhr.send(JSON.stringify({ message, agent }));

  return () => {
    cleanup();
    try {
      xhr.abort();
    } catch {
      // ignore
    }
  };
}
