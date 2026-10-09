import type { ServerConfig } from '../storage/settings';
import { normalizeBaseUrl } from './client';

export type WallAgent = { id: string; tier: string; status: string };
export type WallTask = { owner: string; state: string };
export type WallTrust = { mic: 'on' | 'off'; strictLocal: boolean; cloudAvailable: boolean };
export type WallLocality = { local: number; cloud: number; unknown: number; total: number; percent: number | null };
export type WallSource<T> =
  | { status: 'available'; value: T; checkedAt: number }
  | { status: 'unavailable'; value: null; checkedAt: number };
export type WallSnapshot = {
  health: WallSource<{ up: true }>;
  agents: WallSource<WallAgent[]>;
  tasks: WallSource<WallTask[]>;
  trust: WallSource<WallTrust>;
  locality: WallSource<WallLocality>;
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
    return { health: unavailable, agents: unavailable, tasks: unavailable, trust: unavailable, locality: unavailable };
  }
  const [healthSource, agentsSource, tasksSource, trustSource, localitySource] = await Promise.all([
    readSource(base, '/healthz', config, signal, health),
    readSource(base, '/api/agents', config, signal, agents),
    readSource(base, '/tasks?view=running', config, signal, tasks),
    readSource(base, '/api/trust/status', config, signal, trust),
    readSource(base, '/api/analytics/locality', config, signal, locality),
  ]);
  if (signal.aborted) throw new Error(CANCELLED);
  return { health: healthSource, agents: agentsSource, tasks: tasksSource, trust: trustSource, locality: localitySource };
}
