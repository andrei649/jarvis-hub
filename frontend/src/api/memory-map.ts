import { apiFetchOnce } from './client';

export type MemoryNode = { name: string; type: string };
export type MemoryRelation = { source: string; relation: string; target: string };
export type MemoryNeighborhoodData = { entity: MemoryNode; relations: MemoryRelation[]; clipped: boolean };
export class MemoryMapError extends Error {
  constructor(public code: 'auth' | 'unavailable' = 'unavailable') { super(code); }
}
const fail = (code: MemoryMapError['code'] = 'unavailable'): never => { throw new MemoryMapError(code); };
const text = (value: unknown, max = 256): value is string => typeof value === 'string'
  && value.trim().length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value);
const node = (value: any): MemoryNode => {
  if (!value || !text(value.name) || !text(value.type, 80)) fail();
  return { name: value.name, type: value.type };
};

async function read(path: string, signal?: AbortSignal): Promise<any> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 10_000);
  try {
    controller.signal.throwIfAborted();
    const response = await apiFetchOnce(path, { signal: controller.signal });
    if (response.status === 401 || response.status === 403) fail('auth');
    if (!response.ok || response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json' || !response.body) fail();
    const limit = 1024 * 1024;
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
  } catch (error) {
    if (signal?.aborted) signal.throwIfAborted();
    if (error instanceof MemoryMapError) throw error;
    fail();
  } finally { controller.abort(); clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

export async function memoryNodes(query = '', signal?: AbortSignal): Promise<MemoryNode[]> {
  if (query.length > 200 || /[\u0000-\u001f\u007f]/.test(query)) fail();
  const value = await read('/api/kg/entities?limit=100&q=' + encodeURIComponent(query), signal);
  if (value?.error || !Array.isArray(value?.entities) || value.entities.length > 100) fail();
  return [...new Map<string, MemoryNode>(value.entities.map((item: unknown) => {
    const clean = node(item); return [clean.name, clean];
  })).values()];
}

export async function memoryNeighborhood(name: string, signal?: AbortSignal): Promise<MemoryNeighborhoodData> {
  if (!text(name) || name === '.' || name === '..' || /[/\\]/.test(name)) fail();
  const value = await read('/api/kg/entities/' + encodeURIComponent(name), signal);
  const entity = node(value?.entity);
  if (value?.error || entity.name !== name || !Array.isArray(value?.relations)) fail();
  const relations = value.relations.slice(0, 100).map((item: any) => {
    if (!text(item?.source) || !text(item?.target) || !text(item?.relation, 128)
        || (item.source !== name && item.target !== name)) fail();
    return { source: item.source, relation: item.relation, target: item.target };
  });
  return { entity, relations, clipped: value.relations.length > 100 };
}
