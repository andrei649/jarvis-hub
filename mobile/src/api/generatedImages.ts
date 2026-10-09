import type { ServerConfig } from '../storage/settings';
import { normalizeBaseUrl } from './client';

const JSON_LIMIT = 64 * 1024;
const IMAGE_LIMIT = 16 * 1024 * 1024;
const TASK_LIMIT = Number.MAX_SAFE_INTEGER;
const ARTIFACT_ID = /^[a-f0-9]{32}$/;
const STATES = new Set(['awaiting_approval', 'queued', 'generating', 'ready', 'failed', 'rejected', 'deferred', 'refused', 'uncertain']);

export class GeneratedImageError extends Error {
  constructor(message: string, readonly outcome: 'transport' | 'unknown' | 'auth' | 'invalid' = 'transport') {
    super(message);
    this.name = 'GeneratedImageError';
  }
}

export type ImageStatus = { configured: boolean; reachable: boolean | null; reason: string };
export type ImageArtifact = { id: string; bytes: number; width: number; height: number };
export type ImageTask = { taskId: number; state: 'awaiting_approval' | 'queued' | 'generating' | 'ready' | 'failed' | 'rejected' | 'deferred' | 'refused' | 'uncertain'; artifact: ImageArtifact | null };
export type ImageProposal = { kind: 'queued'; taskId: number } | { kind: 'refused'; reason: string };

function headers(config: ServerConfig, accept = 'application/json', json = false): Record<string, string> {
  const values: Record<string, string> = { Accept: accept };
  if (json) values['Content-Type'] = 'application/json';
  if (config.token.trim()) values['X-User-Token'] = config.token.trim();
  if (config.adminToken.trim()) values['X-Admin-Token'] = config.adminToken.trim();
  return values;
}

function bounded<T>(signal: AbortSignal, milliseconds: number, operation: (signal: AbortSignal) => Promise<T>, unknown: boolean): Promise<T> {
  if (signal.aborted) return Promise.reject(new GeneratedImageError('Image request cancelled.', 'transport'));
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  let rejectCancelled: (error: GeneratedImageError) => void = () => {};
  const cancelled = new Promise<never>((_, reject) => { rejectCancelled = reject; });
  const fail = () => {
    controller.abort();
    rejectCancelled(new GeneratedImageError(
      unknown ? 'Submission delivery is unknown. Check Approvals before submitting again.' : 'Image request cancelled or timed out.',
      unknown ? 'unknown' : 'transport',
    ));
  };
  signal.addEventListener('abort', fail, { once: true });
  timer = setTimeout(fail, milliseconds);
  return Promise.race([operation(controller.signal), cancelled]).finally(() => {
    clearTimeout(timer);
    signal.removeEventListener('abort', fail);
  });
}

function base(config: ServerConfig): string {
  const url = normalizeBaseUrl(config.baseUrl);
  if (!url) throw new GeneratedImageError('Connect a hub in Settings.', 'transport');
  return url;
}

function safeReason(raw: unknown): string {
  return typeof raw === 'string' && /^[a-z][a-z0-9_-]{0,63}$/.test(raw) ? raw : 'unavailable';
}

function record(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new GeneratedImageError('Invalid image response.', 'invalid');
  return raw as Record<string, unknown>;
}

function taskId(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 && value <= TASK_LIMIT;
}

async function jsonRequest(config: ServerConfig, path: string, signal: AbortSignal, method: 'GET' | 'POST' = 'GET', body?: object) {
  const submit = method === 'POST';
  const badResponse = () => new GeneratedImageError(
    submit ? 'Submission delivery is unknown. Check Approvals before submitting again.' : 'Invalid image response.',
    submit ? 'unknown' : 'invalid',
  );
  const url = base(config) + path;
  return bounded(signal, 15000, async inner => {
    let response: Response;
    try {
      response = await fetch(url, { method, headers: headers(config, 'application/json', submit),
        body: body ? JSON.stringify(body) : undefined, signal: inner, cache: 'no-store' });
    } catch {
      throw new GeneratedImageError(submit ? 'Submission delivery is unknown. Check Approvals before submitting again.' : 'Could not reach the hub.', submit ? 'unknown' : 'transport');
    }
    if (response.status === 401 || response.status === 403) throw new GeneratedImageError('Check your hub tokens in Settings.', 'auth');
    if (submit && response.status >= 500) throw badResponse();
    const length = response.headers?.get('content-length');
    if (length && (!/^\d+$/.test(length) || Number(length) > JSON_LIMIT)) throw badResponse();
    let text: string;
    try { text = await response.text(); } catch { throw new GeneratedImageError('Could not read image response.', submit ? 'unknown' : 'transport'); }
    if (text.length > JSON_LIMIT) throw badResponse();
    let payload: unknown;
    try { payload = JSON.parse(text); } catch { throw badResponse(); }
    try { return { status: response.status, data: record(payload) }; } catch { throw badResponse(); }
  }, submit);
}

export async function fetchGeneratedImageStatus(config: ServerConfig, signal: AbortSignal): Promise<ImageStatus> {
  const { status, data } = await jsonRequest(config, '/api/media', signal);
  if (status !== 200) throw new GeneratedImageError('Image status unavailable.');
  const local = record(data.local_image);
  if (typeof local.configured !== 'boolean' ||
      (local.configured && (local.local !== true || local.approval_required !== true || local.reachable !== null)) ||
      (!local.configured && local.reachable !== undefined && local.reachable !== null)) {
    throw new GeneratedImageError('Invalid image status.', 'invalid');
  }
  return { configured: local.configured, reachable: null, reason: safeReason(local.reason) };
}

export async function proposeGeneratedImage(config: ServerConfig, prompt: string, signal: AbortSignal): Promise<ImageProposal> {
  if (!prompt.trim() || prompt.length > 4000) throw new GeneratedImageError('Enter a prompt up to 4,000 characters.', 'invalid');
  const { status, data } = await jsonRequest(config, '/api/media/generate', signal, 'POST', { kind: 'image', prompt, cloud: false });
  if (status === 202 && data.ok === false && data.reason === 'approval_required' && taskId(data.task_id)) return { kind: 'queued', taskId: data.task_id };
  if (data.ok === false && (status === 422 || (status === 200 && data.paused === true))) return { kind: 'refused', reason: data.paused === true ? 'paused' : safeReason(data.reason) };
  throw new GeneratedImageError('Submission delivery is unknown. Check Approvals before submitting again.', 'unknown');
}

export async function fetchGeneratedTask(config: ServerConfig, id: number, signal: AbortSignal): Promise<ImageTask> {
  if (!taskId(id)) throw new GeneratedImageError('Invalid image task.', 'invalid');
  const { status, data } = await jsonRequest(config, `/api/media/generation-tasks/${id}`, signal);
  if (status !== 200) throw new GeneratedImageError(status === 404 ? 'Image task no longer available.' : 'Image task unavailable.');
  if (data.task_id !== id || typeof data.state !== 'string' || !STATES.has(data.state)) throw new GeneratedImageError('Invalid image task.', 'invalid');
  let artifact: ImageArtifact | null = null;
  if (data.state === 'ready') {
    const raw = record(data.artifact);
    if (typeof raw.id !== 'string' || !ARTIFACT_ID.test(raw.id) ||
        !Number.isSafeInteger(raw.bytes) || (raw.bytes as number) < 1 || (raw.bytes as number) > IMAGE_LIMIT ||
        !Number.isSafeInteger(raw.width) || (raw.width as number) < 1 || (raw.width as number) > 2048 ||
        !Number.isSafeInteger(raw.height) || (raw.height as number) < 1 || (raw.height as number) > 2048) {
      throw new GeneratedImageError('Invalid image task.', 'invalid');
    }
    artifact = { id: raw.id, bytes: raw.bytes as number, width: raw.width as number, height: raw.height as number };
  } else if (data.artifact !== null) {
    throw new GeneratedImageError('Invalid image task.', 'invalid');
  }
  return { taskId: id, state: data.state as ImageTask['state'], artifact };
}

function blobBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new GeneratedImageError('Could not read PNG.'));
    reader.onloadend = () => {
      const value = reader.result;
      const comma = typeof value === 'string' ? value.indexOf(',') : -1;
      if (typeof value !== 'string' || !value.startsWith('data:') || comma < 0 || comma > 128 ||
          !value.slice(0, comma).toLowerCase().endsWith(';base64')) reject(new GeneratedImageError('Invalid PNG.', 'invalid'));
      else resolve(value.slice(comma + 1));
    };
    reader.readAsDataURL(blob);
  });
}

export async function fetchGeneratedPng(config: ServerConfig, id: string, expectedBytes: number, signal: AbortSignal): Promise<string> {
  if (!ARTIFACT_ID.test(id) || !Number.isSafeInteger(expectedBytes) || expectedBytes < 1 || expectedBytes > IMAGE_LIMIT) {
    throw new GeneratedImageError('Invalid PNG.', 'invalid');
  }
  return bounded(signal, 30000, async inner => {
    let response: Response;
    try { response = await fetch(base(config) + `/api/media/generated/${id}`, { method: 'GET', headers: headers(config, 'image/png'), signal: inner, cache: 'no-store' }); }
    catch { throw new GeneratedImageError('Could not download PNG.'); }
    if (response.status === 401 || response.status === 403) throw new GeneratedImageError('Check your hub tokens in Settings.', 'auth');
    const length = response.headers?.get('content-length');
    if (!response.ok || (response.headers?.get('content-type') || '').split(';')[0].trim().toLowerCase() !== 'image/png' ||
        length == null || !/^\d+$/.test(length) || Number(length) !== expectedBytes) throw new GeneratedImageError('Invalid PNG.', 'invalid');
    const blob = await response.blob();
    if (blob.size !== expectedBytes || blob.size > IMAGE_LIMIT) throw new GeneratedImageError('Invalid PNG.', 'invalid');
    const encoded = await blobBase64(blob);
    if (!encoded.startsWith('iVBORw0KGgo') || encoded.length !== Math.ceil(expectedBytes / 3) * 4) throw new GeneratedImageError('Invalid PNG.', 'invalid');
    return encoded;
  }, false);
}
