/* H206 — client for the memory graph explorer.

   Reads: GET /api/kg/map (bounded whole-map), GET /api/kg/facts/as-of (the scrubber),
   GET /api/kg/entities/{name} (the editor's current properties), GET /skills.
   Writes go ONLY through the existing mediated routes: POST /api/kg/entities,
   DELETE /api/kg/entities/{name} (user_guard + contract + kernel `kg.write`, the
   operator capability is minted server-side so no token is ever sent from here) and
   the admin-guarded POST /api/skills/switch. Refusals are never swallowed: the
   server's own words ride on `MemoryGraphError.detail`, and a 403 body tells a
   kernel/contract denial ('denied') from a credentials problem ('auth'). */
import { apiDelete, apiFetchOnce, apiPost } from './client';
import { SKILLS_PATH, SWITCH_PATH } from '../panels/skill-switches';

/* 'unknown' = the request may have been executed but its reply never arrived (or the server broke
   while handling it): the caller must reload instead of claiming nothing changed. */
/* 'unaddressable' = the dot segments '.' and '..': a URL cannot carry them as a path segment, so they can be neither read nor deleted by name.
   'padded' = a name with leading or trailing whitespace: the server stores the exact name it is sent, so an edit is refused rather than risk writing a different entity. */
export type MemoryGraphErrorCode = 'auth' | 'admin' | 'denied' | 'invalid' | 'notfound' | 'unavailable' | 'unknown' | 'unaddressable' | 'padded';
export class MemoryGraphError extends Error {
  constructor(public code: MemoryGraphErrorCode = 'unavailable', public detail = '') { super(code); }
}
const fail = (code: MemoryGraphErrorCode = 'unavailable', detail = ''): never => { throw new MemoryGraphError(code, detail); };

export type MapEntity = { name: string; type: string; firstSeen: number | null };
export type MapRelation = { source: string; relation: string; target: string };
/* `skipped` counts entries the client would not draw (control characters, over-long names): one odd
   name must not take the whole map down, so it is left out and the panel says how many. */
export type MemoryMapData = { entities: MapEntity[]; relations: MapRelation[]; clipped: boolean; relationsClipped: boolean; skipped: number };
export type Fact = { id: number; subject: string; predicate: string; object: string; validFrom: number; validTo: number | null; ingestedAt: number };
export type TimelineBounds = { count: number; firstIngested: number | null; lastIngested: number | null; firstValid: number | null; lastChange: number | null };
export type FactsPage = { axis: TimelineAxis; facts: Fact[]; bounds: TimelineBounds; clipped: boolean; skipped: number };
export type TimelineAxis = 'known' | 'valid';
export type SkillInfo = { name: string; category: string; essential: boolean; disabled: boolean };
export type EntityDetail = { name: string; type: string; properties: Record<string, unknown> };
export type SkillSwitchResult = { changed: string[]; essential: string[]; pending: boolean; taskId: string };

export const MAP_LIMIT = 500;
export const FACT_LIMIT = 500;
/* Mirrors the server's AUD-12 label gate (validation.is_safe_kg_label) and property key gate. */
export const SAFE_TYPE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
export const SAFE_PROPERTY_KEY = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

const CONTROL = /[\u0000-\u001f\u007f]/;
/* Something the map code would keep: a name made only of C1, line-separator or bidi control characters is cleaned to nothing by the encoder and then refused by the decoder. */
const VISIBLE = /[^\u0000-\u0020\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/;
const text = (value: unknown, max = 256): value is string =>
  typeof value === 'string' && value.trim().length > 0 && value.length <= max && !CONTROL.test(value) && VISIBLE.test(value);
const num = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
/* The largest |epoch seconds| a JavaScript Date can show. A stored time beyond it would throw in the panel's formatter. */
export const MAX_TIME = 8.64e12;
const sane = (value: unknown): value is number => num(value) && Math.abs(value) <= MAX_TIME;
/* A bound that is a number but out of range is dropped (null), anything else that is not a number fails the read. */
const numOrNull = (value: unknown): number | null => (value === null || value === undefined ? null : num(value) ? (sane(value) ? value : null) : fail());
/* The routes /api/kg/entities/{name:path} carry any name, '/' and '\\' included (the client sends it percent-encoded);
   only the dot segments cannot travel in a URL path (MEM-098). */
export const isAddressable = (name: string): boolean => name !== '.' && name !== '..';
/* Edit writes by the exact name: one with surrounding whitespace is refused (the server would otherwise store a different, trimmed entity). Delete and read are by path and unaffected. */
export const isEditable = (name: string): boolean => isAddressable(name) && name === name.trim();

/* ── errors ─────────────────────────────────────────────────────────────── */
const bodyError = (body: any): string => (body && typeof body === 'object' && typeof body.error === 'string' ? body.error.slice(0, 300) : '');
function fromHttp(status: number, body: unknown, admin = false): MemoryGraphError {
  const message = bodyError(body);
  if (status === 401) return new MemoryGraphError(admin ? 'admin' : 'auth');
  if (status === 403) {
    if (/^(kernel|contract) denied/i.test(message)) return new MemoryGraphError('denied', message);
    return new MemoryGraphError(admin ? 'admin' : 'auth', message);
  }
  if (status === 404) return new MemoryGraphError('notfound', message);
  if (status === 400 || status === 409 || status === 422) {
    const reason = message || (body && typeof (body as any).reason === 'string' ? (body as any).reason : '');
    return new MemoryGraphError('invalid', reason);
  }
  return new MemoryGraphError('unavailable', message);
}

/* ── bounded GET ────────────────────────────────────────────────────────── */
async function readBody(response: Response, controller: AbortController, limit: number): Promise<unknown> {
  if (!response.body) return undefined;
  const length = response.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) fail();
  const reader = response.body.getReader();
  const stop = () => { void reader.cancel().catch(() => {}); };
  controller.signal.addEventListener('abort', stop, { once: true });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      controller.signal.throwIfAborted();
      const { value, done } = await reader.read();
      controller.signal.throwIfAborted();
      if (done) break;
      if (value.byteLength > limit - size) fail();
      chunks.push(value); size += value.byteLength;
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { controller.signal.removeEventListener('abort', stop); reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}

async function read(path: string, signal?: AbortSignal, limit = 2 * 1024 * 1024): Promise<any> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 10_000);
  try {
    controller.signal.throwIfAborted();
    const response = await apiFetchOnce(path, { signal: controller.signal });
    const json = response.headers.get('content-type')?.split(';')[0].trim() === 'application/json';
    if (!response.ok) {
      let body: unknown;
      if (json) { try { body = await readBody(response, controller, 64 * 1024); } catch { body = undefined; } }
      throw fromHttp(response.status, body);
    }
    if (!json || !response.body) fail();
    return await readBody(response, controller, limit);
  } catch (error) {
    if (signal?.aborted) signal.throwIfAborted();
    if (error instanceof MemoryGraphError) throw error;
    return fail();
  } finally { controller.abort(); clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

/* ── reads ──────────────────────────────────────────────────────────────── */
export async function loadMemoryMap(signal?: AbortSignal): Promise<MemoryMapData> {
  const value = await read('/api/kg/map?limit=' + MAP_LIMIT, signal);
  if (value?.error || !Array.isArray(value?.entities) || !Array.isArray(value?.relations)
    || value.entities.length > 1000 || value.relations.length > 4000) fail();
  let skipped = 0;
  const kept = new Map<string, MapEntity>();
  for (const item of value.entities) {
    if (!item || !text(item.name)) { skipped++; continue; }
    let firstSeen: number | null = null;
    if (item.first_seen !== null && item.first_seen !== undefined) { if (sane(item.first_seen)) firstSeen = item.first_seen; else { skipped++; continue; } }
    kept.set(item.name, { name: item.name, type: text(item.type, 80) ? item.type : 'unknown', firstSeen });
  }
  const entities = [...kept.values()];
  const relations: MapRelation[] = [];
  for (const item of value.relations) {
    if (!item || typeof item.source !== 'string' || typeof item.target !== 'string') { skipped++; continue; }
    if (!kept.has(item.source) || !kept.has(item.target)) continue;      // an endpoint left out above (already counted)
    if (!text(item.relation, 128)) { skipped++; continue; }
    relations.push({ source: item.source, relation: item.relation, target: item.target });
  }
  return { entities, relations, clipped: value.clipped === true, relationsClipped: value.relations_clipped === true, skipped };
}

export async function loadFacts(axis: TimelineAxis, at: number | null, signal?: AbortSignal): Promise<FactsPage> {
  if (axis !== 'known' && axis !== 'valid') return fail();
  if (at !== null && !num(at)) return fail();
  const value = await read(`/api/kg/facts/as-of?axis=${axis}${at === null ? '' : '&at=' + at}&limit=${FACT_LIMIT}`, signal);
  if (value?.error || value?.axis !== axis || !Array.isArray(value?.facts) || value.facts.length > 1000
    || !value.bounds || typeof value.bounds !== 'object') fail();
  const facts: Fact[] = [];
  let skipped = 0;
  for (const f of value.facts) {
    if (!f || !num(f.id) || !text(f.subject, 512) || !text(f.predicate, 256) || !text(f.object, 512)
      || !sane(f.valid_from) || !sane(f.ingested_at) || !(f.valid_to === null || f.valid_to === undefined || sane(f.valid_to))) { skipped++; continue; }
    facts.push({ id: f.id, subject: f.subject, predicate: f.predicate, object: f.object,
      validFrom: f.valid_from, validTo: f.valid_to ?? null, ingestedAt: f.ingested_at });
  }
  const b = value.bounds;
  return {
    axis, facts, clipped: value.clipped === true, skipped,
    bounds: { count: num(b.count) ? b.count : 0, firstIngested: numOrNull(b.first_ingested), lastIngested: numOrNull(b.last_ingested),
      firstValid: numOrNull(b.first_valid), lastChange: numOrNull(b.last_change) },
  };
}

export async function loadSkills(signal?: AbortSignal): Promise<SkillInfo[]> {
  const value = await read(SKILLS_PATH, signal, 8 * 1024 * 1024);
  const map = value?.skills;
  if (!map || typeof map !== 'object' || Array.isArray(map)) return fail();
  return Object.entries(map).slice(0, 500).map(([key, item]: [string, any]) => {
    const name = text(item?.name, 128) ? item.name : key;
    if (!text(name, 128)) return fail();
    return { name, category: typeof item?.category === 'string' ? item.category.slice(0, 64) : '',
      essential: item?.essential === true, disabled: item?.disabled === true };
  }).sort((a, b) => a.name.localeCompare(b.name));
}

export async function loadEntity(name: string, signal?: AbortSignal): Promise<EntityDetail> {
  if (!text(name)) return fail();
  if (!isAddressable(name)) return fail('unaddressable');
  const value = await read('/api/kg/entities/' + encodeURIComponent(name), signal);
  const e = value?.entity;
  if (value?.error || !e || e.name !== name || !text(e.type, 80)) fail();
  const props = e.properties && typeof e.properties === 'object' && !Array.isArray(e.properties) ? e.properties : {};
  return { name, type: e.type, properties: { ...props } };
}

/* ── writes (mediated routes only) ─────────────────────────────────────── */
async function mutate<T>(run: () => Promise<T>, admin = false): Promise<T> {
  try { return await run(); } catch (error: any) {
    if (error instanceof MemoryGraphError) throw error;
    if (typeof error?.status === 'number') {
      const known = fromHttp(error.status, error.body, admin);
      /* A 5xx other than "graph not available" means the server broke while handling the write. */
      if (known.code === 'unavailable' && error.status !== 503) throw new MemoryGraphError('unknown', known.detail);
      throw known;
    }
    /* No HTTP status: the request left, the reply did not (or was unreadable) — it may have been applied. */
    throw new MemoryGraphError('unknown');
  }
}

export async function saveEntity(name: string, type: string, properties: Record<string, unknown>): Promise<EntityDetail> {
  if (!text(name)) return fail('invalid', 'name required');
  if (!isAddressable(name)) return fail('unaddressable');
  if (name !== name.trim()) return fail('padded');
  if (!SAFE_TYPE.test(type.trim())) return fail('invalid', 'invalid entity type');
  const body = await mutate(() => apiPost<any>('/api/kg/entities', { name, type: type.trim(), properties }));
  /* A 200 with ok:false means the graph could not store the write (e.g. a Neo4j node-shape
     lookup failed): the owner's edit was NOT kept, so it is never reported as saved. */
  if (body?.ok !== true) return fail('unavailable', 'the graph did not store the change');
  const e = body?.entity;
  return { name, type: text(e?.type, 80) ? e.type : type.trim(), properties: e?.properties && typeof e.properties === 'object' ? e.properties : properties };
}

/* `graphDeleted` false: the live graph never held it (the default graph forgets at restart) and only timeline facts were closed. */
export async function removeEntity(name: string): Promise<{ factsRetracted: number; graphDeleted: boolean }> {
  if (!text(name)) return fail('invalid', 'name required');
  if (!isAddressable(name)) return fail('unaddressable');
  const body = await mutate(() => apiDelete<any>('/api/kg/entities/' + encodeURIComponent(name)));
  return { factsRetracted: num(body?.facts_retracted) ? body.facts_retracted : 0, graphDeleted: body?.graph_deleted !== false };
}

const names = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string').slice(0, 50) : []);
export async function switchSkill(skill: string, enabled: boolean): Promise<SkillSwitchResult> {
  if (!text(skill, 128)) return fail('invalid', 'skill required');
  const body = await mutate(() => apiPost<any>(SWITCH_PATH, { skill, enabled }, { admin: true }), true);
  return { changed: names(body?.changed), essential: names(body?.essential), pending: body?.status === 'pending',
    taskId: typeof body?.task_id === 'string' ? body.task_id : '' };
}
