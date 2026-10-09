import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl, type KgEntitiesResponse, type KgEntityResponse, type KgFactsResponse, type KgFactHistoryResponse, type KnowledgeEntity, type KnowledgeFact, type KnowledgeRelation } from './client';

const DEADLINE_MS = 10_000;
const MAX_BYTES = 1024 * 1024;
const MAX_ENTITIES = 50;
const MAX_ROWS = 100;

/** Native Hermes need not provide TextEncoder; count UTF-8 without another body allocation. */
function exceedsBodyLimit(text: string): boolean {
  let bytes = 0;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff
      && text.charCodeAt(index + 1) >= 0xdc00 && text.charCodeAt(index + 1) <= 0xdfff) {
      bytes += 4;
      index += 1;
    } else bytes += 3; // BMP characters and replacement for a lone surrogate.
    if (bytes > MAX_BYTES) return true;
  }
  return false;
}

function validName(value: unknown, max = 256): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value);
}

function nameForPath(name: string): string {
  if (!validName(name) || name === '.' || name === '..' || /[/\\]/.test(name)) throw new ApiError('Invalid entity name');
  return encodeURIComponent(name);
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function entity(value: unknown): KnowledgeEntity {
  const item = record(value);
  if (!validName(item.name) || !validName(item.type, 80)) throw new ApiError('Invalid graph entity');
  return { ...item, name: item.name, type: item.type, properties: record(item.properties) };
}

function fact(value: unknown): KnowledgeFact {
  const item = record(value);
  if (!validName(item.subject) || !validName(item.predicate) || typeof item.object !== 'string') throw new ApiError('Invalid graph fact');
  return { ...item, subject: item.subject, predicate: item.predicate, object: item.object } as KnowledgeFact;
}

async function read(config: ServerConfig, path: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const controller = new AbortController();
  let timedOut = false;
  let onAbort: (() => void) | undefined;
  const cancelled = new Promise<never>((_resolve, reject) => {
    onAbort = () => { controller.abort(); reject(new DOMException('Aborted', 'AbortError')); };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => { timedOut = true; controller.abort(); reject(new ApiError('Knowledge graph request timed out')); }, DEADLINE_MS);
  });
  try {
    const operation = (async () => {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
      else if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
      const response = await fetch(base + path, { method: 'GET', headers, signal: controller.signal });
      if (response.status === 401 || response.status === 403) throw new ApiError('Unauthorized — check your user token', response.status);
      if (!response.ok) throw new ApiError(`Server returned HTTP ${response.status}`, response.status);
      const length = response.headers?.get('content-length');
      if (length !== null && length !== undefined && (!/^\d+$/.test(length) || Number(length) > MAX_BYTES)) throw new ApiError('Knowledge graph response too large');
      // React Native does not consistently expose Response.body. Bound before reading when
      // Content-Length exists and verify bytes after text() on other transports.
      const body = await response.text();
      if (exceedsBodyLimit(body)) throw new ApiError('Knowledge graph response too large');
      let parsed: unknown;
      try { parsed = JSON.parse(body); } catch { throw new ApiError('Invalid knowledge graph response'); }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new ApiError('Invalid knowledge graph response');
      const value = parsed as Record<string, unknown>;
      if (typeof value.error === 'string' && value.error) throw new ApiError(value.error);
      return value;
    })();
    return await Promise.race([operation, cancelled, timeout]);
  } catch (error) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (timedOut) throw new ApiError('Knowledge graph request timed out');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Knowledge graph unavailable');
  } finally {
    clearTimeout(timer!);
    if (onAbort) signal?.removeEventListener('abort', onAbort);
    controller.abort();
  }
}

export async function fetchGraphEntities(config: ServerConfig, query: string, signal?: AbortSignal): Promise<KgEntitiesResponse> {
  if (query.length > 200 || /[\u0000-\u001f\u007f]/.test(query)) throw new ApiError('Invalid graph search');
  const value = await read(config, `/api/kg/entities?limit=${MAX_ENTITIES}&q=${encodeURIComponent(query)}`, signal);
  if (!Array.isArray(value.entities) || value.entities.length > MAX_ENTITIES) throw new ApiError('Invalid graph entity list');
  const entities = [...new Map(value.entities.map(item => { const normalized = entity(item); return [normalized.name, normalized] as const; })).values()];
  const total = typeof value.total === 'number' && Number.isFinite(value.total) && value.total >= 0 ? value.total : entities.length;
  return { entities, total };
}

export async function fetchGraphEntity(config: ServerConfig, name: string, signal?: AbortSignal): Promise<KgEntityResponse & { clipped: boolean }> {
  const value = await read(config, `/api/kg/entities/${nameForPath(name)}`, signal);
  const selected = entity(value.entity);
  if (selected.name !== name || !Array.isArray(value.relations)) throw new ApiError('Invalid graph detail');
  const relations = value.relations.slice(0, MAX_ROWS).map(item => {
    const relation = record(item);
    if (!validName(relation.source) || !validName(relation.target) || !validName(relation.relation, 128)
      || (relation.source !== name && relation.target !== name)) throw new ApiError('Invalid unrelated relation');
    return { ...relation, source: relation.source, target: relation.target, relation: relation.relation, properties: record(relation.properties) } as KnowledgeRelation;
  });
  return { entity: selected, relations, clipped: value.relations.length > MAX_ROWS };
}

export async function fetchGraphFacts(config: ServerConfig, signal?: AbortSignal): Promise<KgFactsResponse & { clipped: boolean }> {
  const value = await read(config, '/api/kg/facts/as-of', signal);
  if (!Array.isArray(value.facts)) throw new ApiError('Invalid current facts');
  return { facts: value.facts.slice(0, MAX_ROWS).map(fact), clipped: value.facts.length > MAX_ROWS };
}

export async function fetchGraphHistory(config: ServerConfig, subject: string, signal?: AbortSignal): Promise<KgFactHistoryResponse & { clipped: boolean }> {
  const value = await read(config, `/api/kg/facts/history?subject=${nameForPath(subject)}`, signal);
  if (!Array.isArray(value.history)) throw new ApiError('Invalid fact history');
  if (value.subject !== subject) throw new ApiError('Invalid history subject');
  const history = value.history.slice(0, MAX_ROWS).map(fact);
  if (history.some(item => item.subject !== subject)) throw new ApiError('Invalid history subject');
  return { subject, history, clipped: value.history.length > MAX_ROWS };
}
