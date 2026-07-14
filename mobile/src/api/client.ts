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

export type CommandCenterResidencyState = 'known' | 'unknown' | 'offline';

export interface CommandCenterResidentModel {
  provider: string;
  id: string;
}

export interface CommandCenterModel {
  backend: string;
  active_model: string | null;
  configured_model: string | null;
  resident_models: CommandCenterResidentModel[];
  residency_state: CommandCenterResidencyState;
  active_provider: string | null;
  route: string | null;
  ready: boolean | null;
  cloud_configured: boolean;
}

export interface CommandCenterResponse {
  install: { ready: boolean; version: string; checks: Record<string, unknown> };
  model: CommandCenterModel;
  wizard: {
    steps: CommandCenterWizardStep[];
    completed: string[];
    complete: boolean;
    hint: string | null;
  };
  first_actions: CommandCenterAction[];
}

function commandCenterString(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}

function commandCenterOptionalString(value: unknown, limit: number): string | null {
  return commandCenterString(value, limit) || null;
}

function commandCenterModelId(value: unknown): string | null {
  const modelId = commandCenterOptionalString(value, 256);
  return modelId?.toLowerCase() === 'none' ? null : modelId;
}

function normalizeCommandCenterResident(value: unknown): CommandCenterResidentModel | null {
  const raw = securityRecord(value);
  const provider = commandCenterString(raw.provider, 64);
  const id = commandCenterModelId(raw.id);
  return provider && id ? { provider, id } : null;
}

function normalizeCommandCenterResidency(value: unknown): CommandCenterResidencyState {
  return value === 'known' || value === 'offline' ? value : 'unknown';
}

function commandCenterProviderKey(value: string | null): string {
  return (value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

const COMMAND_CENTER_GEMINI_ROUTES = new Set(['cloud', 'cloud-fallback', 'cloud-flash', 'cloud-pro']);
const COMMAND_CENTER_LOCAL_ROUTES = new Set(['local', 'local-deep', 'local-fallback']);

function commandCenterUsesCloud(model: CommandCenterModel): boolean {
  const provider = commandCenterProviderKey(model.active_provider || model.backend);
  const route = (model.route || '').toLowerCase();
  return (
    (provider === 'gemini' && COMMAND_CENTER_GEMINI_ROUTES.has(route)) ||
    (provider === 'claude' && route === 'claude')
  );
}

/** A conservative, user-facing projection of the backend's model truth contract. */
export function commandCenterModelLabel(model: CommandCenterModel): string {
  const active = commandCenterModelId(model.active_model);
  const configured = commandCenterModelId(model.configured_model);
  const route = (model.route || '').toLowerCase();

  if (model.ready === true && active && commandCenterUsesCloud(model)) {
    return `${active} · cloud ready`;
  }

  if (
    model.ready === true &&
    active &&
    model.residency_state === 'known' &&
    COMMAND_CENTER_LOCAL_ROUTES.has(route)
  ) {
    const provider = commandCenterProviderKey(model.active_provider || model.backend);
    const exactResident = model.resident_models.some(
      (resident) => commandCenterProviderKey(resident.provider) === provider && resident.id === active,
    );
    if (exactResident) return `${active} · loaded`;
  }

  const candidate = configured || active;
  if (candidate) {
    const residencyUnknown = model.residency_state === 'unknown' || model.ready === null;
    return residencyUnknown
      ? `${candidate} · residency unknown`
      : `${candidate} · configured, not loaded`;
  }
  return 'no runnable model';
}

function normalizeCommandCenter(raw: Record<string, unknown>): CommandCenterResponse {
  const install = securityRecord(raw.install);
  const model = securityRecord(raw.model);
  const wizard = securityRecord(raw.wizard);
  const steps = Array.isArray(wizard.steps) ? wizard.steps : [];
  const actions = Array.isArray(raw.first_actions) ? raw.first_actions : [];
  const residentModels = Array.isArray(model.resident_models)
    ? model.resident_models
        .slice(0, 64)
        .map(normalizeCommandCenterResident)
        .filter((resident): resident is CommandCenterResidentModel => resident !== null)
    : [];
  return {
    install: {
      ready: securityBool(install.ready),
      version: securityString(install.version),
      checks: securityRecord(install.checks),
    },
    model: {
      backend: commandCenterString(model.backend, 64) || 'none',
      active_model: commandCenterModelId(model.active_model),
      configured_model: commandCenterModelId(model.configured_model),
      resident_models: residentModels,
      residency_state: normalizeCommandCenterResidency(model.residency_state),
      active_provider: commandCenterOptionalString(model.active_provider, 64),
      route: commandCenterOptionalString(model.route, 64),
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

// ── Media Director ───────────────────────────────────────────────

export type MediaContentType = 'url' | 'local' | 'catalog' | 'query';
export type MediaMode = 'play' | 'show' | 'announce';
export type MediaPrivacy = 'ambient' | 'household' | 'private';
export type MediaUrgency = 'low' | 'normal' | 'high';

export type MediaDevice = {
  id: string;
  name: string;
  kind: string;
  room: string;
  supports: MediaMode[];
};

export type MediaSession = {
  device_id: string;
  content: { type: MediaContentType; value: string };
  mode: string;
  privacy: string;
  state: string;
  started_at: number;
  duration_seconds?: number;
};

export type MediaDevicesResponse = {
  enabled: boolean;
  hint: string;
  devices: MediaDevice[];
};

export type MediaSessionsResponse = {
  enabled: boolean;
  hint: string;
  sessions: MediaSession[];
};

export type MediaPresentBody = {
  content: { type: MediaContentType; value: string };
  target: string;
  mode: MediaMode;
  privacy: MediaPrivacy;
  urgency: MediaUrgency;
  duration_seconds?: number;
};

export type MediaDeviceBody = {
  id: string;
  name: string;
  kind: string;
  room: string;
  supports: MediaMode[];
};

export type MediaActionOutcome = {
  kind: 'disabled' | 'queued' | 'refused' | 'unverified' | 'verified' | 'unknown';
  status: string;
  reason: string;
  deviceId: string;
  state: string;
};

export type MediaRegistryMutation = {
  enabled: boolean;
  hint: string;
  device?: MediaDevice;
  removed: string;
  error: string;
};

const MEDIA_CONTENT_TYPES = new Set<MediaContentType>(['url', 'local', 'catalog', 'query']);
const MEDIA_MODES = new Set<MediaMode>(['play', 'show', 'announce']);

function mediaString(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.slice(0, limit) : '';
}

function mediaContentType(value: unknown): MediaContentType | null {
  return typeof value === 'string' && MEDIA_CONTENT_TYPES.has(value as MediaContentType)
    ? (value as MediaContentType)
    : null;
}

function normalizeMediaDevice(value: unknown): MediaDevice | null {
  const raw = securityRecord(value);
  const rawId = securityString(raw.id);
  const id = rawId.length <= 64 ? rawId : '';
  const name = mediaString(raw.name, 120);
  const kind = mediaString(raw.kind, 32);
  if (!id || !name || !kind) return null;
  const supports = Array.isArray(raw.supports)
    ? Array.from(
        new Set(
          raw.supports.filter(
            (item): item is MediaMode => typeof item === 'string' && MEDIA_MODES.has(item as MediaMode),
          ),
        ),
      )
    : [];
  return { id, name, kind, room: mediaString(raw.room, 64), supports: supports.slice(0, 16) };
}

function normalizeMediaSession(value: unknown): MediaSession | null {
  const raw = securityRecord(value);
  const content = securityRecord(raw.content);
  const rawDeviceId = securityString(raw.device_id);
  const deviceId = rawDeviceId.length <= 64 ? rawDeviceId : '';
  const type = mediaContentType(content.type);
  const contentValue = mediaString(content.value, 2048);
  if (!deviceId || !type || !contentValue) return null;
  const duration = raw.duration_seconds;
  return {
    device_id: deviceId,
    content: { type, value: contentValue },
    mode: mediaString(raw.mode, 16),
    privacy: mediaString(raw.privacy, 16),
    state: mediaString(raw.state, 32),
    started_at: securityNumber(raw.started_at),
    ...(typeof duration === 'number' && Number.isFinite(duration) && duration > 0 && duration <= 86400
      ? { duration_seconds: duration }
      : {}),
  };
}

function normalizeMediaMutation(rawValue: unknown): MediaRegistryMutation {
  const raw = securityRecord(rawValue);
  const device = normalizeMediaDevice(raw.device);
  return {
    enabled: securityBool(raw.enabled),
    hint: mediaString(raw.hint, 240),
    ...(device ? { device } : {}),
    removed: mediaString(raw.removed, 64),
    error: mediaString(raw.error, 240),
  };
}

function normalizeMediaAction(rawValue: unknown): MediaActionOutcome {
  const raw = securityRecord(rawValue);
  const output = securityRecord(raw.output);
  const status = mediaString(raw.status, 32);
  const reason = mediaString(output.reason, 240) || mediaString(raw.reason, 240) || mediaString(raw.hint, 240);
  const common = {
    status,
    reason,
    deviceId: mediaString(output.device_id, 64),
    state: mediaString(output.state, 32),
  };
  if (raw.enabled === false || status === 'disabled') return { kind: 'disabled', ...common };
  if (raw.enabled !== true) {
    return { kind: 'unknown', ...common, reason: reason || 'invalid_media_response' };
  }
  if (output.ok === false || status === 'refused' || status === 'failed') return { kind: 'refused', ...common };
  if (status === 'queued') return { kind: 'queued', ...common };
  if (status === 'completed' && output.ok === true && output.verified === true) {
    return { kind: 'verified', ...common };
  }
  if (status === 'completed' && output.ok === true) return { kind: 'unverified', ...common };
  return { kind: 'unknown', ...common };
}

export async function fetchMediaDevices(config: ServerConfig): Promise<MediaDevicesResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/media/devices', undefined, {
    retries: 2,
  });
  return {
    enabled: securityBool(raw.enabled),
    hint: mediaString(raw.hint, 240),
    devices: Array.isArray(raw.devices)
      ? raw.devices.map(normalizeMediaDevice).filter((item): item is MediaDevice => item !== null)
      : [],
  };
}

export async function fetchMediaSessions(config: ServerConfig): Promise<MediaSessionsResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/media/session', undefined, {
    retries: 2,
  });
  return {
    enabled: securityBool(raw.enabled),
    hint: mediaString(raw.hint, 240),
    sessions: Array.isArray(raw.sessions)
      ? raw.sessions.map(normalizeMediaSession).filter((item): item is MediaSession => item !== null)
      : [],
  };
}

export async function presentMedia(config: ServerConfig, body: MediaPresentBody): Promise<MediaActionOutcome> {
  const raw = await request<Record<string, unknown>>(config, 'POST', '/api/media/present', body);
  return normalizeMediaAction(raw);
}

export async function restoreMedia(config: ServerConfig, deviceId: string): Promise<MediaActionOutcome> {
  const raw = await request<Record<string, unknown>>(
    config,
    'POST',
    `/api/media/restore/${encodeURIComponent(deviceId)}`,
  );
  return normalizeMediaAction(raw);
}

export async function registerMediaDevice(
  config: ServerConfig,
  body: MediaDeviceBody,
): Promise<MediaRegistryMutation> {
  const raw = await request<Record<string, unknown>>(config, 'POST', '/api/media/devices', body, { admin: true });
  return normalizeMediaMutation(raw);
}

export async function removeMediaDevice(config: ServerConfig, deviceId: string): Promise<MediaRegistryMutation> {
  const raw = await request<Record<string, unknown>>(
    config,
    'DELETE',
    `/api/media/devices/${encodeURIComponent(deviceId)}`,
    undefined,
    { admin: true },
  );
  return normalizeMediaMutation(raw);
}

// ── House Brain (read parity only) ───────────────────────────────

export type HouseRoom = {
  room_id: string;
  name: string;
};

export type HouseDevice = {
  entity_id: string;
  domain: string;
  state: string;
  room_id: string;
};

export type HousePresence = {
  occupant_id: string;
  status: 'present' | 'vacant' | 'unknown';
  room_id?: string;
  privacy: string;
  confidence: number;
  fresh: boolean;
};

export type HouseStateResponse = {
  enabled: boolean;
  status: 'disabled' | 'degraded' | 'live';
  reason: string;
  observed_at: number;
  freshness_seconds: number | null;
  rooms: HouseRoom[];
  devices: HouseDevice[];
  presence: HousePresence[];
  privacy_status: string;
};

const HOUSE_PSEUDONYM = /^occ-[0-9a-f]{32}$/;

function houseText(value: unknown, limit: number): string {
  const text = securityString(value).trim();
  return text.length <= limit ? text : '';
}

function normalizeHouseRoom(value: unknown): HouseRoom | null {
  const raw = securityRecord(value);
  const roomId = houseText(raw.room_id, 128);
  const name = houseText(raw.name, 160);
  return roomId && name ? { room_id: roomId, name } : null;
}

function normalizeHouseDevice(value: unknown): HouseDevice | null {
  const raw = securityRecord(value);
  const entityId = houseText(raw.entity_id, 128);
  const domain = houseText(raw.domain, 64);
  const state = houseText(raw.state, 256);
  if (!entityId || !domain || !state) return null;
  return {
    entity_id: entityId,
    domain,
    state,
    room_id: houseText(raw.room_id, 128),
  };
}

function normalizeHousePresence(value: unknown): HousePresence | null {
  const raw = securityRecord(value);
  const occupantId = houseText(raw.occupant_id, 36);
  if (!HOUSE_PSEUDONYM.test(occupantId)) return null;
  const rawStatus = houseText(raw.status, 16);
  const status = rawStatus === 'present' || rawStatus === 'vacant' ? rawStatus : 'unknown';
  const privacy = houseText(raw.privacy, 128) || 'household';
  const rawConfidence = securityNumber(raw.confidence);
  const confidence = Number.isFinite(rawConfidence)
    ? Math.max(0, Math.min(rawConfidence, 1))
    : 0;
  const roomId = privacy.toLowerCase() === 'private' ? '' : houseText(raw.room_id, 128);
  return {
    occupant_id: occupantId,
    status,
    ...(roomId ? { room_id: roomId } : {}),
    privacy,
    confidence,
    fresh: securityBool(raw.fresh),
  };
}

export async function fetchHouseState(config: ServerConfig): Promise<HouseStateResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/house/state', undefined, {
    retries: 2,
  });
  const rawStatus = houseText(raw.status, 32);
  const status = rawStatus === 'disabled' || rawStatus === 'degraded' || rawStatus === 'live'
    ? rawStatus
    : 'degraded';
  const observedAt = securityNumber(raw.observed_at);
  const rawFreshness = raw.freshness_seconds;
  return {
    enabled: securityBool(raw.enabled),
    status,
    reason: typeof raw.reason === 'string' ? raw.reason.slice(0, 256) : '',
    observed_at: Number.isFinite(observedAt) && observedAt >= 0 ? observedAt : 0,
    freshness_seconds:
      typeof rawFreshness === 'number' && Number.isFinite(rawFreshness) && rawFreshness >= 0
        ? rawFreshness
        : null,
    rooms: Array.isArray(raw.rooms)
      ? raw.rooms.map(normalizeHouseRoom).filter((item): item is HouseRoom => item !== null).slice(0, 500)
      : [],
    devices: Array.isArray(raw.devices)
      ? raw.devices.map(normalizeHouseDevice).filter((item): item is HouseDevice => item !== null).slice(0, 500)
      : [],
    presence: Array.isArray(raw.presence)
      ? raw.presence.map(normalizeHousePresence).filter((item): item is HousePresence => item !== null).slice(0, 500)
      : [],
    privacy_status: houseText(raw.privacy_status, 32) || 'unavailable',
  };
}

// ── Camera Intelligence (metadata only) ─────────────────────────

export type CameraSourceStatus = {
  status: string;
  camera_count: number;
  last_success_at: number | null;
  last_error: string | null;
};

export type CameraStorageStatus = {
  status: string;
  items: number;
  bytes: number;
  last_sweep_at: number | null;
};

export type CameraStatusResponse = {
  enabled: boolean;
  status: string;
  reason: string;
  source: CameraSourceStatus | null;
  storage: CameraStorageStatus | null;
};

export type CameraEvent = {
  event_id: string;
  camera_id: string;
  label: 'person' | 'vehicle' | 'animal' | 'package';
  occurred_at: number;
  confidence: number;
  anonymous: boolean;
  zone?: string;
  room_id?: string;
  description?: string;
  description_provenance?: 'local_vlm_on_demand';
};

export type CameraEventsResponse = {
  enabled: boolean;
  status: string;
  reason: string;
  interpretation: Record<string, string | number>;
  events: CameraEvent[];
};

const CAMERA_EVENT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const CAMERA_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const CAMERA_LABELS = new Set(['person', 'vehicle', 'animal', 'package']);
const CAMERA_ERROR = /^[a-z][a-z0-9_]{0,63}$/;

function cameraText(value: unknown, limit: number): string {
  const text = securityString(value).trim();
  return text.length <= limit && !/[\u0000-\u001f]/.test(text) ? text : '';
}

function cameraTimestamp(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function normalizeCameraStatus(rawValue: unknown): CameraStatusResponse {
  const raw = securityRecord(rawValue);
  const sourceRaw = securityRecord(raw.source);
  const sourceStatus = cameraText(sourceRaw.status, 32);
  const source = raw.source && sourceStatus
    ? {
      status: sourceStatus,
      camera_count: Math.max(0, Math.min(128, Math.trunc(securityNumber(sourceRaw.camera_count) || 0))),
      last_success_at: cameraTimestamp(sourceRaw.last_success_at),
      last_error: CAMERA_ERROR.test(cameraText(sourceRaw.last_error, 64))
        ? cameraText(sourceRaw.last_error, 64)
        : sourceRaw.last_error ? 'source_error' : null,
    }
    : null;
  const storageRaw = securityRecord(raw.storage);
  const storageStatus = cameraText(storageRaw.status, 32);
  const storage = raw.storage && storageStatus
    ? {
      status: storageStatus,
      items: Math.max(0, Math.trunc(securityNumber(storageRaw.items) || 0)),
      bytes: Math.max(0, Math.trunc(securityNumber(storageRaw.bytes) || 0)),
      last_sweep_at: cameraTimestamp(storageRaw.last_sweep_at),
    }
    : null;
  return {
    enabled: securityBool(raw.enabled),
    status: cameraText(raw.status, 32) || 'unavailable',
    reason: cameraText(raw.reason, 128),
    source,
    storage,
  };
}

function normalizeCameraEvent(value: unknown): CameraEvent | null {
  const raw = securityRecord(value);
  const eventId = cameraText(raw.event_id, 128);
  const cameraId = cameraText(raw.camera_id, 64);
  const label = cameraText(raw.label, 32);
  const occurredAt = cameraTimestamp(raw.occurred_at);
  const rawConfidence = typeof raw.confidence === 'number' ? raw.confidence : Number.NaN;
  if (
    !CAMERA_EVENT_ID.test(eventId)
    || !CAMERA_ID.test(cameraId)
    || !CAMERA_LABELS.has(label)
    || occurredAt === null
    || !Number.isFinite(rawConfidence)
  ) return null;
  const description = cameraText(raw.description, 512);
  const provenance = cameraText(raw.description_provenance, 64);
  const localDescription = description && provenance === 'local_vlm_on_demand';
  return {
    event_id: eventId,
    camera_id: cameraId,
    label: label as CameraEvent['label'],
    occurred_at: occurredAt,
    confidence: Math.max(0, Math.min(1, rawConfidence)),
    anonymous: label === 'person',
    ...(cameraText(raw.zone, 64) ? { zone: cameraText(raw.zone, 64) } : {}),
    ...(cameraText(raw.room_id, 64) ? { room_id: cameraText(raw.room_id, 64) } : {}),
    ...(localDescription ? { description, description_provenance: 'local_vlm_on_demand' as const } : {}),
  };
}

function normalizeCameraEvents(rawValue: unknown): CameraEventsResponse {
  const raw = securityRecord(rawValue);
  const interpretationRaw = securityRecord(raw.interpretation);
  const interpretation: Record<string, string | number> = {};
  for (const key of ['after', 'before', 'label', 'camera_id', 'zone', 'room_id']) {
    const value = interpretationRaw[key];
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) interpretation[key] = value;
    else if (typeof value === 'string' && cameraText(value, 64)) interpretation[key] = cameraText(value, 64);
  }
  return {
    enabled: securityBool(raw.enabled),
    status: cameraText(raw.status, 32) || 'unavailable',
    reason: cameraText(raw.reason, 128),
    interpretation,
    events: Array.isArray(raw.events)
      ? raw.events.map(normalizeCameraEvent).filter((item): item is CameraEvent => item !== null).slice(0, 100)
      : [],
  };
}

export async function fetchCameraStatus(config: ServerConfig): Promise<CameraStatusResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/cameras/status', undefined, { retries: 2 });
  return normalizeCameraStatus(raw);
}

export async function fetchCameraEvents(config: ServerConfig): Promise<CameraEventsResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/cameras/events', undefined, { retries: 2 });
  return normalizeCameraEvents(raw);
}

export async function searchCameraEvents(
  config: ServerConfig,
  query: string,
  limit = 100,
): Promise<CameraEventsResponse> {
  const text = query.trim();
  if (!text || text.length > 256) throw new ApiError('Camera search must be 1 to 256 characters');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new ApiError('Camera search limit is invalid');
  const raw = await request<Record<string, unknown>>(
    config,
    'POST',
    '/api/cameras/search',
    { query: text, limit },
  );
  return normalizeCameraEvents(raw);
}

// ── Ambient Intelligence (redacted read parity) ────────────────

export type AmbientRung = 'ignore' | 'remember' | 'monitor' | 'act_silently' | 'ask' | 'interrupt';

export type AmbientDecision = {
  monitor_id: string;
  transition: string;
  rung: AmbientRung;
  attention_mode: string;
  policy_reason: string;
  decided_at: number;
};

export type AmbientMonitor = {
  monitor_id: string;
  version: number;
  source: 'house' | 'camera' | 'digital';
  schema: string;
  enabled: boolean;
  alert_rung: AmbientRung;
  recovery_rung: AmbientRung;
  state: string;
  last_event_at: number | null;
  last_decision: AmbientDecision | null;
};

export type AmbientSource = {
  source: 'house' | 'camera' | 'digital';
  status: string;
  last_event_at: number | null;
  reason: string;
  queued: number;
  critical_backpressure: number;
};

export type AmbientMonitorsResponse = {
  enabled: boolean;
  status: string;
  reason: string;
  monitors: AmbientMonitor[];
  sources: AmbientSource[];
  last_decision: AmbientDecision | null;
  rung_counts: Record<AmbientRung, number>;
  decision_samples: number;
  attention: { status: string; reason: string; limit: number; used: number; remaining: number };
};

const AMBIENT_RUNGS = new Set<AmbientRung>([
  'ignore', 'remember', 'monitor', 'act_silently', 'ask', 'interrupt',
]);
const AMBIENT_SOURCES = new Set<AmbientSource['source']>(['house', 'camera', 'digital']);
const AMBIENT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function ambientText(value: unknown, limit: number): string {
  const text = securityString(value).trim();
  return text.length <= limit && !/[\u0000-\u001f]/.test(text) ? text : '';
}

function ambientCount(value: unknown, max = 100_000): number {
  return Math.max(0, Math.min(max, Math.trunc(securityNumber(value) || 0)));
}

function normalizeAmbientDecision(value: unknown): AmbientDecision | null {
  const raw = securityRecord(value);
  const monitorId = ambientText(raw.monitor_id, 128);
  const rung = ambientText(raw.rung, 16) as AmbientRung;
  const decidedAt = cameraTimestamp(raw.decided_at);
  if (!AMBIENT_ID.test(monitorId) || !AMBIENT_RUNGS.has(rung) || decidedAt === null) return null;
  return {
    monitor_id: monitorId,
    transition: ambientText(raw.transition, 16),
    rung,
    attention_mode: ambientText(raw.attention_mode, 16),
    policy_reason: ambientText(raw.policy_reason, 64),
    decided_at: decidedAt,
  };
}

function normalizeAmbientMonitor(value: unknown): AmbientMonitor | null {
  const raw = securityRecord(value);
  const monitorId = ambientText(raw.monitor_id, 128);
  const source = ambientText(raw.source, 16) as AmbientSource['source'];
  const schema = ambientText(raw.schema, 128);
  const alertRung = ambientText(raw.alert_rung, 16) as AmbientRung;
  const recoveryRung = ambientText(raw.recovery_rung, 16) as AmbientRung;
  if (
    !AMBIENT_ID.test(monitorId) || !AMBIENT_SOURCES.has(source) || !AMBIENT_ID.test(schema)
    || !AMBIENT_RUNGS.has(alertRung) || !AMBIENT_RUNGS.has(recoveryRung)
  ) return null;
  return {
    monitor_id: monitorId,
    version: Math.max(1, ambientCount(raw.version)),
    source,
    schema,
    enabled: securityBool(raw.enabled),
    alert_rung: alertRung,
    recovery_rung: recoveryRung,
    state: ambientText(raw.state, 16) || 'waiting',
    last_event_at: cameraTimestamp(raw.last_event_at),
    last_decision: normalizeAmbientDecision(raw.last_decision),
  };
}

function normalizeAmbientSource(value: unknown): AmbientSource | null {
  const raw = securityRecord(value);
  const source = ambientText(raw.source, 16) as AmbientSource['source'];
  if (!AMBIENT_SOURCES.has(source)) return null;
  return {
    source,
    status: ambientText(raw.status, 16) || 'waiting',
    last_event_at: cameraTimestamp(raw.last_event_at),
    reason: ambientText(raw.reason, 64),
    queued: ambientCount(raw.queued, 2_048),
    critical_backpressure: ambientCount(raw.critical_backpressure),
  };
}

function normalizeAmbientMonitors(rawValue: unknown): AmbientMonitorsResponse {
  const raw = securityRecord(rawValue);
  const rungRaw = securityRecord(raw.rung_counts);
  const attentionRaw = securityRecord(raw.attention);
  const rungCounts = {} as Record<AmbientRung, number>;
  for (const rung of AMBIENT_RUNGS) rungCounts[rung] = ambientCount(rungRaw[rung]);
  return {
    enabled: securityBool(raw.enabled),
    status: ambientText(raw.status, 16) || 'unavailable',
    reason: ambientText(raw.reason, 128),
    monitors: Array.isArray(raw.monitors)
      ? raw.monitors.map(normalizeAmbientMonitor).filter((item): item is AmbientMonitor => item !== null).slice(0, 200)
      : [],
    sources: Array.isArray(raw.sources)
      ? raw.sources.map(normalizeAmbientSource).filter((item): item is AmbientSource => item !== null).slice(0, 3)
      : [],
    last_decision: normalizeAmbientDecision(raw.last_decision),
    rung_counts: rungCounts,
    decision_samples: ambientCount(raw.decision_samples, 1_000),
    attention: {
      status: ambientText(attentionRaw.status, 16) || 'degraded',
      reason: ambientText(attentionRaw.reason, 64),
      limit: ambientCount(attentionRaw.limit, 100),
      used: ambientCount(attentionRaw.used, 100),
      remaining: ambientCount(attentionRaw.remaining, 100),
    },
  };
}

export async function fetchAmbientMonitors(config: ServerConfig): Promise<AmbientMonitorsResponse> {
  const raw = await request<Record<string, unknown>>(config, 'GET', '/api/ambient/monitors', undefined, { retries: 2 });
  return normalizeAmbientMonitors(raw);
}

// ── Governed capability acquisition (read-only mobile projection) ──

export type AcquisitionPackage = {
  name: string;
  version: string;
  status: string;
  confidence: number;
};

export type AcquisitionAuditHealth = {
  status: string;
  events: number;
  summarized_events: number;
  chain_valid: boolean;
};

export type AcquisitionStatusResponse = {
  enabled: boolean;
  status: string;
  reason: string;
  states: Record<string, number>;
  reuse: {
    reused: number;
    generated: number;
    blocked: number;
    abandoned: number;
    reuse_rate: number;
  };
  packages: AcquisitionPackage[];
  audit: AcquisitionAuditHealth;
};

export type AcquisitionEvent = {
  sequence: number;
  event_type: string;
  actor: string;
  status: string;
  occurred_at: number;
};

export type AcquisitionEventsResponse = {
  enabled: boolean;
  status: string;
  events: AcquisitionEvent[];
};

const ACQUISITION_STATES = new Set([
  'missing',
  'researching',
  'quarantined',
  'approval_pending',
  'installed',
  'reused',
  'blocked',
  'abandoned',
  'revoked',
]);
const ACQUISITION_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const ACQUISITION_EVENT = /^[a-z][a-z_]{0,31}\.[a-z][a-z_]{0,31}$/;
const ACQUISITION_ACTOR = /^[A-Za-z0-9_.:@/-]{1,128}$/;

function acquisitionText(value: unknown, limit: number): string {
  const text = securityString(value).trim();
  return text.length <= limit && !/[\u0000-\u001f]/.test(text) ? text : '';
}

function acquisitionCount(value: unknown, max = 100_000): number {
  const number = securityNumber(value);
  return Math.max(0, Math.min(max, Math.trunc(number || 0)));
}

function normalizeAcquisitionStatus(rawValue: unknown): AcquisitionStatusResponse {
  const raw = securityRecord(rawValue);
  const statesRaw = securityRecord(raw.states);
  const states: Record<string, number> = {};
  for (const name of ACQUISITION_STATES) {
    if (name in statesRaw) states[name] = acquisitionCount(statesRaw[name]);
  }
  const reuseRaw = securityRecord(raw.reuse);
  const auditRaw = securityRecord(raw.audit);
  const packages = Array.isArray(raw.packages)
    ? raw.packages.map((value): AcquisitionPackage | null => {
      const item = securityRecord(value);
      const name = acquisitionText(item.name, 64);
      const version = acquisitionText(item.version, 64);
      const status = acquisitionText(item.status, 32);
      if (!ACQUISITION_NAME.test(name) || !version || !status) return null;
      const confidence = typeof item.confidence === 'number' && Number.isFinite(item.confidence)
        ? Math.max(0, Math.min(1, item.confidence))
        : 0;
      return { name, version, status, confidence };
    }).filter((item): item is AcquisitionPackage => item !== null).slice(0, 256)
    : [];
  const reuseRate = typeof reuseRaw.reuse_rate === 'number' && Number.isFinite(reuseRaw.reuse_rate)
    ? Math.max(0, Math.min(1, reuseRaw.reuse_rate))
    : 0;
  return {
    enabled: securityBool(raw.enabled),
    status: acquisitionText(raw.status, 32) || 'unavailable',
    reason: acquisitionText(raw.reason, 128),
    states,
    reuse: {
      reused: acquisitionCount(reuseRaw.reused),
      generated: acquisitionCount(reuseRaw.generated),
      blocked: acquisitionCount(reuseRaw.blocked),
      abandoned: acquisitionCount(reuseRaw.abandoned),
      reuse_rate: reuseRate,
    },
    packages,
    audit: {
      status: acquisitionText(auditRaw.status, 32) || 'unavailable',
      events: acquisitionCount(auditRaw.events),
      summarized_events: acquisitionCount(auditRaw.summarized_events),
      chain_valid: securityBool(auditRaw.chain_valid),
    },
  };
}

function normalizeAcquisitionEvents(rawValue: unknown): AcquisitionEventsResponse {
  const raw = securityRecord(rawValue);
  const events = Array.isArray(raw.events)
    ? raw.events.map((value): AcquisitionEvent | null => {
      const item = securityRecord(value);
      const eventType = acquisitionText(item.event_type, 64);
      const actor = acquisitionText(item.actor, 128);
      const status = acquisitionText(item.status, 32);
      const sequence = securityNumber(item.sequence);
      const occurredAt = securityNumber(item.occurred_at);
      if (
        !ACQUISITION_EVENT.test(eventType)
        || !ACQUISITION_ACTOR.test(actor)
        || !status
        || !Number.isInteger(sequence)
        || sequence < 1
        || !Number.isFinite(occurredAt)
        || occurredAt < 0
      ) return null;
      return { sequence, event_type: eventType, actor, status, occurred_at: occurredAt };
    }).filter((item): item is AcquisitionEvent => item !== null).slice(0, 100)
    : [];
  return {
    enabled: securityBool(raw.enabled),
    status: acquisitionText(raw.status, 32) || 'unavailable',
    events,
  };
}

export async function fetchAcquisitionStatus(
  config: ServerConfig,
): Promise<AcquisitionStatusResponse> {
  const raw = await request<Record<string, unknown>>(
    config,
    'GET',
    '/api/acquisition/status',
    undefined,
    { retries: 2 },
  );
  return normalizeAcquisitionStatus(raw);
}

export async function fetchAcquisitionEvents(
  config: ServerConfig,
): Promise<AcquisitionEventsResponse> {
  const raw = await request<Record<string, unknown>>(
    config,
    'GET',
    '/api/acquisition/events?limit=100',
    undefined,
    { retries: 2 },
  );
  return normalizeAcquisitionEvents(raw);
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
