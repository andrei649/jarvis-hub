import type { ServerConfig } from '../storage/settings';
import { normalizeBaseUrl } from './client';

export type WallAgent = { id: string; tier: string; status: string };
export type WallTask = { owner: string; state: string };
export type WallTrust = { mic: 'on' | 'off'; strictLocal: boolean; cloudAvailable: boolean };
export type WallLocality = { local: number; cloud: number; unknown: number; total: number; percent: number | null };
export type WallApprovals = { pending: number };
export type WallCalendar = { returned: number };
export type WallModel = { state: 'ready' | 'unknown' | 'no_model' | 'offline'; residentCount: number };
export type WallVoice = { stt: boolean; tts: boolean; ttsLocal: boolean; localOnly: boolean };
export type WallHeartbeat = { running: boolean; scheduled: number; blocked: number };
export type WallSource<T> =
  | { status: 'available'; value: T; checkedAt: number }
  | { status: 'unavailable'; value: null; checkedAt: number };
export type WallSnapshot = {
  health: WallSource<{ up: true }>;
  agents: WallSource<WallAgent[]>;
  tasks: WallSource<WallTask[]>;
  trust: WallSource<WallTrust>;
  locality: WallSource<WallLocality>;
  approvals: WallSource<WallApprovals>;
  calendar: WallSource<WallCalendar>;
  model: WallSource<WallModel>;
  voice: WallSource<WallVoice>;
  heartbeat: WallSource<WallHeartbeat>;
};

const DEADLINE_MS = 5000;
const BODY_LIMIT = 256 * 1024; // UTF-16 code units. Native response.text() has already buffered the body.
const CANCELLED = 'Briefing read cancelled.';

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid briefing response.');
  return value as Record<string, unknown>;
}

function label(value: unknown, max: number): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('Invalid briefing response.');
  return value.trim();
}

function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error('Invalid briefing response.');
  return value as number;
}

function health(value: unknown): { up: true } {
  if (object(value).status !== 'ok') throw new Error('Invalid briefing response.');
  return { up: true };
}

function agents(value: unknown): WallAgent[] {
  const rows = object(value).agents;
  if (!Array.isArray(rows) || rows.length > 256) throw new Error('Invalid briefing response.');
  const seen = new Set<string>();
  return rows.map(raw => {
    const row = object(raw);
    const id = label(row.id, 80);
    if (seen.has(id)) throw new Error('Invalid briefing response.');
    seen.add(id);
    return { id, status: label(row.status, 80), tier: label(row.tier, 64) };
  });
}

function tasks(value: unknown): WallTask[] {
  const source = object(value);
  if (source.view !== 'running' || source.history_included !== false ||
      !Array.isArray(source.tasks) || source.tasks.length > 30) throw new Error('Invalid briefing response.');
  return source.tasks.map(raw => {
    const row = object(raw);
    const effective = typeof row.state === 'string' && row.state.trim() ? row.state : row.status;
    if (label(effective, 80).toLowerCase() !== 'running') throw new Error('Invalid briefing response.');
    return { owner: label(row.owner, 80), state: 'running' };
  });
}

function trust(value: unknown): WallTrust {
  const source = object(value);
  if ((source.mic !== 'on' && source.mic !== 'off') || typeof source.strict_local !== 'boolean' ||
      typeof source.cloud_available !== 'boolean' || typeof source.claude_available !== 'boolean') {
    throw new Error('Invalid briefing response.');
  }
  return { mic: source.mic, strictLocal: source.strict_local,
    cloudAvailable: source.cloud_available || source.claude_available };
}

/** Match Python round(): an exact half goes to the even integer. */
function roundedPercent(local: number, decided: number): number {
  const value = 100 * local / decided;
  const floor = Math.floor(value);
  const fraction = value - floor;
  return fraction > 0.5 || (fraction === 0.5 && floor % 2 !== 0) ? floor + 1 : floor;
}

function locality(value: unknown): WallLocality {
  const source = object(value);
  const local = count(source.local);
  const cloud = count(source.cloud);
  const unknown = count(source.unknown);
  const total = count(source.total);
  const decided = local + cloud;
  if (!Number.isSafeInteger(decided) || !Number.isSafeInteger(decided + unknown) ||
      decided + unknown !== total) throw new Error('Invalid briefing response.');
  const percent = decided ? roundedPercent(local, decided) : null;
  if (source.local_pct !== percent) throw new Error('Invalid briefing response.');
  return { local, cloud, unknown, total, percent };
}

function approvals(value: unknown): WallApprovals {
  const source = object(value);
  if (!Array.isArray(source.pending) || source.pending.length > 100 ||
      count(object(source.counts).total) !== source.pending.length) throw new Error('Invalid briefing response.');
  const seen = new Set<number>();
  for (const raw of source.pending) {
    const row = object(raw);
    const id = count(row.id);
    if (id === 0 || seen.has(id) || (row.status !== 'blocked' && row.status !== 'proposed')) {
      throw new Error('Invalid briefing response.');
    }
    seen.add(id);
  }
  return { pending: source.pending.length };
}

function isoTimestamp(value: unknown): boolean {
  if (typeof value !== 'string' || value.length > 64) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-](\d{2}):(\d{2}))?)?$/.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, offsetHour, offsetMinute] = match;
  const calendarDate = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (calendarDate.getUTCFullYear() !== Number(year) || calendarDate.getUTCMonth() + 1 !== Number(month) ||
      calendarDate.getUTCDate() !== Number(day)) return false;
  if (hour !== undefined && (Number(hour) > 23 || Number(minute) > 59 ||
      (second !== undefined && Number(second) > 59) ||
      (offsetHour !== undefined && (Number(offsetHour) > 23 || Number(offsetMinute) > 59)))) return false;
  // Native JS engines need not parse arbitrary RFC3339 precision. The full input
  // is bounded and syntax-checked above; milliseconds suffice for date validation.
  return Number.isFinite(Date.parse(value.replace(/(\.\d{3})\d+/, '$1')));
}

function calendar(value: unknown): WallCalendar {
  const rows = object(value).calendar;
  // /dashboard can cache an empty calendar after a failed or unconfigured probe.
  if (!Array.isArray(rows) || !rows.length || rows.length > 10) throw new Error('Invalid briefing response.');
  for (const raw of rows) {
    const row = object(raw);
    if ('error' in row || !isoTimestamp(row.ts) ||
        (row.state !== 'past' && row.state !== 'next' && row.state !== 'upcoming')) {
      throw new Error('Invalid briefing response.');
    }
  }
  return { returned: rows.length };
}

function model(value: unknown): WallModel {
  const source = object(value);
  const state = source.model_state;
  const rows = source.resident_models;
  if ((state !== 'ready' && state !== 'unknown' && state !== 'no_model' && state !== 'offline') ||
      typeof source.model_loaded !== 'boolean' || !Array.isArray(rows) || rows.length > 64) {
    throw new Error('Invalid briefing response.');
  }
  for (const raw of rows) {
    const row = object(raw);
    label(row.id, 256);
    label(row.provider, 80);
  }
  if ((state === 'ready') !== (rows.length > 0 && source.model_loaded === true) ||
      (state !== 'ready' && (rows.length !== 0 || source.model_loaded !== false))) {
    throw new Error('Invalid briefing response.');
  }
  return { state, residentCount: rows.length };
}

function voice(value: unknown): WallVoice {
  const source = object(value);
  if (typeof source.stt !== 'boolean' || typeof source.tts !== 'boolean' ||
      typeof source.tts_local !== 'boolean' || typeof source.local_only !== 'boolean') {
    throw new Error('Invalid briefing response.');
  }
  return { stt: source.stt, tts: source.tts, ttsLocal: source.tts_local, localOnly: source.local_only };
}

function heartbeat(value: unknown): WallHeartbeat {
  const source = object(value);
  if (typeof source.scheduler_running !== 'boolean' || !Array.isArray(source.heartbeats) ||
      source.heartbeats.length > 256 || !Array.isArray(source.blocked) || source.blocked.length > 256) {
    throw new Error('Invalid briefing response.');
  }
  for (const rows of [source.heartbeats, source.blocked]) {
    const seen = new Set<string>();
    for (const raw of rows) {
      const id = label(object(raw).agent_id, 80);
      if (seen.has(id)) throw new Error('Invalid briefing response.');
      seen.add(id);
    }
  }
  return { running: source.scheduler_running, scheduled: source.heartbeats.length, blocked: source.blocked.length };
}

function requestHeaders(config: ServerConfig): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
  return headers;
}

/** Each request races native fetch and buffered text reads against an independent deadline. */
async function getJson(base: string, path: string, config: ServerConfig, signal: AbortSignal): Promise<unknown> {
  if (signal.aborted) throw new Error(CANCELLED);
  const controller = new AbortController();
  let rejectStopped: (reason: Error) => void = () => {};
  const stopped = new Promise<never>((_, reject) => { rejectStopped = reject; });
  let stoppedOnce = false;
  const stop = (reason: string) => {
    if (stoppedOnce) return;
    stoppedOnce = true;
    controller.abort();
    rejectStopped(new Error(reason));
  };
  const onAbort = () => stop(CANCELLED);
  signal.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => stop('Briefing source unavailable.'), DEADLINE_MS);
  try {
    if (signal.aborted) throw new Error(CANCELLED);
    return await Promise.race([(async () => {
      const response = await fetch(base + path, { method: 'GET', headers: requestHeaders(config),
        signal: controller.signal, cache: 'no-store', redirect: 'error' });
      if (controller.signal.aborted || response.status !== 200) throw new Error('Briefing source unavailable.');
      const length = response.headers?.get('content-length');
      if (length !== null && length !== undefined && (!/^\d+$/.test(length) || Number(length) > BODY_LIMIT)) {
        throw new Error('Briefing source unavailable.');
      }
      const body = await response.text();
      if (controller.signal.aborted || body.length > BODY_LIMIT) throw new Error('Briefing source unavailable.');
      return JSON.parse(body) as unknown;
    })(), stopped]);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
  }
}

async function readSource<T>(base: string, path: string, config: ServerConfig, signal: AbortSignal,
  project: (value: unknown) => T): Promise<WallSource<T>> {
  try {
    const value = project(await getJson(base, path, config, signal));
    if (signal.aborted) throw new Error(CANCELLED);
    return { status: 'available', value, checkedAt: Date.now() };
  } catch {
    if (signal.aborted) throw new Error(CANCELLED);
    return { status: 'unavailable', value: null, checkedAt: Date.now() };
  }
}

/** A read-only snapshot; source failures never become fabricated zeros or raw server errors. */
export async function readBriefingWall(config: ServerConfig, signal: AbortSignal): Promise<WallSnapshot> {
  if (signal.aborted) throw new Error(CANCELLED);
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) {
    const unavailable = { status: 'unavailable' as const, value: null, checkedAt: Date.now() };
    return { health: unavailable, agents: unavailable, tasks: unavailable, trust: unavailable, locality: unavailable,
      approvals: unavailable, calendar: unavailable, model: unavailable, voice: unavailable, heartbeat: unavailable };
  }
  const [healthSource, agentsSource, tasksSource, trustSource, localitySource,
    approvalsSource, calendarSource, modelSource, voiceSource, heartbeatSource] = await Promise.all([
    readSource(base, '/healthz', config, signal, health),
    readSource(base, '/api/agents', config, signal, agents),
    readSource(base, '/tasks?view=running', config, signal, tasks),
    readSource(base, '/api/trust/status', config, signal, trust),
    readSource(base, '/api/analytics/locality', config, signal, locality),
    readSource(base, '/autonomy/approvals', config, signal, approvals),
    readSource(base, '/dashboard', config, signal, calendar),
    readSource(base, '/status', config, signal, model),
    readSource(base, '/api/voice/capabilities', config, signal, voice),
    readSource(base, '/heartbeat/status', config, signal, heartbeat),
  ]);
  if (signal.aborted) throw new Error(CANCELLED);
  return { health: healthSource, agents: agentsSource, tasks: tasksSource, trust: trustSource, locality: localitySource,
    approvals: approvalsSource, calendar: calendarSource, model: modelSource, voice: voiceSource, heartbeat: heartbeatSource };
}
