import { normalizeBaseUrl } from './client';
import type { ServerConfig } from '../storage/settings';

export type ActiveImage = { handle: string; count: number; question: string };
export type ImageCandidate = { prompt: string; agent: string; sessionId: string;
  imageDigests: string[]; activeImageHandles: string[] };
export type SelectedReview = { reviewToken: string; destination: string; model: string;
  sessionId: string; activeImageCount: number; reachable: null };
export type SelectedAnswer = { response: string; model: string; destination: string;
  activeImageHandle: string | null };

/** A safe fixed message. A selected-chat refusal is definite only for known precommit HTTP codes. */
export class SelectedImageError extends Error {
  constructor(message: string, readonly definite: boolean, readonly status?: number) {
    super(message); this.name = 'SelectedImageError';
  }
}
const sid = /^[A-Za-z0-9_-]{1,128}$/;
const agentId = /^[a-z][a-z0-9_-]{0,63}$/;
const digest = /^[0-9a-f]{64}$/;
const token = /^[-_A-Za-z0-9]{20,128}$/;
const handle = /^[-_A-Za-z0-9]{20,128}$/;
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const safeString = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const invalid = () => new SelectedImageError('Selected image response unavailable', false);
const badInput = () => new SelectedImageError('Invalid selected image request', true);

function candidateValid(c: ImageCandidate): boolean {
  return safeString(c.prompt, 4000) && !!c.prompt.trim() && sid.test(c.sessionId) && agentId.test(c.agent)
    && Array.isArray(c.imageDigests) && c.imageDigests.length <= 4 && c.imageDigests.every(x => typeof x === 'string' && digest.test(x))
    && Array.isArray(c.activeImageHandles) && c.activeImageHandles.length <= 8
    && c.activeImageHandles.every(x => typeof x === 'string' && handle.test(x))
    && new Set(c.activeImageHandles).size === c.activeImageHandles.length
    && c.imageDigests.length + c.activeImageHandles.length > 0;
}
function destinationValid(value: unknown): value is string {
  if (!safeString(value, 2048)) return false;
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:')
      && (url.hostname === 'localhost' || url.hostname === '[::1]'
        || /^127(?:\.\d{1,3}){3}$/.test(url.hostname) && url.hostname.split('.').slice(1).every(n => Number(n) <= 255))
      && !url.username && !url.password && !url.search && !url.hash
      && url.origin === value;
  } catch { return false; }
}

async function request(config: ServerConfig, method: 'GET' | 'POST', path: string,
  body: unknown, signal: AbortSignal | undefined, deadlineMs: number, cap: number): Promise<unknown> {
  if (signal?.aborted) throw new SelectedImageError('Selected image request cancelled', false);
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw badInput();
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new SelectedImageError('Selected image request timed out', false)); }, deadlineMs);
  });
  const cancelled = new Promise<never>((_, reject) => {
    onAbort = () => { controller.abort(); reject(new SelectedImageError('Selected image request cancelled', false)); };
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) onAbort();
  });
  try {
    if (signal?.aborted) throw new SelectedImageError('Selected image request cancelled', false);
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
    if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
    const operation = async () => {
      const response = await fetch(base + path, { method, headers,
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal });
      if (!response.ok) {
        const definite = [401, 403, 409, 422].includes(response.status);
        throw new SelectedImageError(definite ? 'Selected image review refused' : 'Selected image result unknown',
          definite, response.status);
      }
      const sizeHeader = response.headers?.get('Content-Length');
      if (sizeHeader != null && (!/^\d+$/.test(sizeHeader) || Number(sizeHeader) > cap)) throw invalid();
      const raw = await response.text(); // RN buffers before this cap; no hard network byte bound.
      if (raw.length > cap) throw invalid();
      try { return JSON.parse(raw) as unknown; } catch { throw invalid(); }
    };
    return await Promise.race([operation(), timeout, cancelled]);
  } catch (error) {
    if (error instanceof SelectedImageError) throw error;
    throw new SelectedImageError('Selected image connection unavailable', false);
  } finally {
    if (timer) clearTimeout(timer);
    if (onAbort) signal?.removeEventListener('abort', onAbort);
  }
}

export async function listActiveImages(config: ServerConfig, sessionId: string, agent: string,
  signal?: AbortSignal): Promise<ActiveImage[]> {
  if (!sid.test(sessionId) || !agentId.test(agent)) throw badInput();
  const body = await request(config, 'GET', `/api/vlm/composer/active-images?session_id=${encodeURIComponent(sessionId)}&agent=${encodeURIComponent(agent)}`,
    undefined, signal, 5000, 32768);
  if (!obj(body) || body.session_id !== sessionId || !Array.isArray(body.images) || body.images.length > 32) throw invalid();
  const rows: ActiveImage[] = body.images.map((row: unknown) => {
    if (!obj(row) || typeof row.handle !== 'string' || !handle.test(row.handle)
      || !Number.isInteger(row.count) || (row.count as number) < 1 || (row.count as number) > 8
      || typeof row.question !== 'string' || [...row.question].length > 120) throw invalid();
    return { handle: row.handle, count: row.count as number, question: row.question };
  });
  if (new Set(rows.map(row => row.handle)).size !== rows.length) throw invalid();
  return rows;
}

export async function prepareSelectedImages(config: ServerConfig, candidate: ImageCandidate,
  signal?: AbortSignal): Promise<SelectedReview> {
  if (!candidateValid(candidate)) throw badInput();
  const body = await request(config, 'POST', '/api/vlm/composer/selected-prepare', {
    prompt: candidate.prompt, agent: candidate.agent, session_id: candidate.sessionId,
    image_digests: candidate.imageDigests, active_image_handles: candidate.activeImageHandles,
  }, signal, 10000, 8192);
  if (!obj(body) || body.configured !== true || body.reachable !== null || body.local !== true
    || body.backend !== 'ollama' || body.session_id !== candidate.sessionId
    || !destinationValid(body.destination) || !safeString(body.model, 512)
    || typeof body.review_token !== 'string' || !token.test(body.review_token)
    || !Number.isInteger(body.active_image_count) || (body.active_image_count as number) < 0
    || (body.active_image_count as number) > 8) throw invalid();
  return { reviewToken: body.review_token, destination: body.destination, model: body.model,
    sessionId: body.session_id, activeImageCount: body.active_image_count as number, reachable: null };
}

export async function sendSelectedImages(config: ServerConfig,
  payload: ImageCandidate & { images: string[]; reviewToken: string; expectedDestination: string; expectedModel: string },
  signal?: AbortSignal): Promise<SelectedAnswer> {
  if (!candidateValid(payload) || !Array.isArray(payload.images)
    || payload.images.length !== payload.imageDigests.length
    || !token.test(payload.reviewToken) || !destinationValid(payload.expectedDestination)
    || !safeString(payload.expectedModel, 512)) throw badInput();
  let aggregateBytes = 0;
  for (const image of payload.images) {
    if (!safeString(image, 5_700_000)) throw badInput();
    const comma = image.indexOf(',');
    const header = image.slice(0, comma);
    const encoded = image.slice(comma + 1);
    if (!['data:image/png;base64', 'data:image/jpeg;base64', 'data:image/gif;base64',
      'data:image/webp;base64'].includes(header) || encoded.length % 4 !== 0
      || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw badInput();
    const padding = encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0;
    const byteCount = encoded.length / 4 * 3 - padding;
    if (byteCount < 1 || byteCount > 4 * 1024 * 1024) throw badInput();
    aggregateBytes += byteCount;
    if (aggregateBytes > 8 * 1024 * 1024) throw badInput();
  }
  const body = await request(config, 'POST', '/api/vlm/composer/selected-chat', {
    prompt: payload.prompt, agent: payload.agent, session_id: payload.sessionId,
    images: payload.images, active_image_handles: payload.activeImageHandles,
    expected_destination: payload.expectedDestination, expected_binding: payload.reviewToken,
    review_token: payload.reviewToken, remote_ack: false,
  }, signal, 180000, 131072);
  if (!obj(body) || body.ok !== true || body.committed !== true || body.local !== true
    || body.backend !== 'ollama' || body.destination !== payload.expectedDestination
    || body.model !== payload.expectedModel || !safeString(body.response, 131072)
    || (body.active_image_handle !== null && (typeof body.active_image_handle !== 'string'
      || !handle.test(body.active_image_handle)))) throw invalid();
  return { response: body.response, model: body.model, destination: body.destination,
    activeImageHandle: body.active_image_handle as string | null };
}
