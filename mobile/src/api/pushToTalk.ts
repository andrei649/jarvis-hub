import * as FileSystem from 'expo-file-system/legacy';
import type { ServerConfig } from '../storage/settings';
import { normalizeBaseUrl } from './client';

const JSON_LIMIT = 64 * 1024;
const AUDIO_LIMIT = 2 * 1024 * 1024;
const CANCELLED = 'Microphone request cancelled.';
const TRUST_ERROR = 'Microphone unavailable.';
const LEASE_ERROR = 'Microphone lease unavailable.';
const FILE_ERROR = 'Recording unavailable.';
const STT_ERROR = 'Recording could not be transcribed.';

export class PushToTalkError extends Error {
  constructor(message: string) { super(message); this.name = 'PushToTalkError'; }
}

function base(config: ServerConfig, message: string): string {
  const value = normalizeBaseUrl(config.baseUrl);
  if (!value) throw new PushToTalkError(message);
  return value;
}

function headers(config: ServerConfig, json: boolean): Record<string, string> {
  const result: Record<string, string> = { Accept: 'application/json' };
  if (json) result['Content-Type'] = 'application/json';
  if (config.token.trim()) result['X-User-Token'] = config.token.trim();
  if (config.adminToken.trim()) result['X-Admin-Token'] = config.adminToken.trim();
  return result;
}

function clientName(value: string): boolean { return /^[A-Za-z0-9._-]{1,64}$/.test(value); }

async function bounded<T>(signal: AbortSignal, milliseconds: number, failure: string,
  operation: (inner: AbortSignal) => Promise<T>, onCancel?: () => void): Promise<T> {
  if (signal.aborted) throw new PushToTalkError(CANCELLED);
  const controller = new AbortController();
  let rejectCancelled: (error: PushToTalkError) => void = () => {};
  const cancelled = new Promise<never>((_, reject) => { rejectCancelled = reject; });
  let stopped = false;
  const stop = (message: string) => {
    if (stopped) return;
    stopped = true;
    controller.abort();
    try { onCancel?.(); } catch { /* Cancellation is best effort. */ }
    rejectCancelled(new PushToTalkError(message));
  };
  const onAbort = () => stop(CANCELLED);
  signal.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => stop(failure), milliseconds);
  try { return await Promise.race([operation(controller.signal), cancelled]); }
  catch (error) { throw error instanceof PushToTalkError ? error : new PushToTalkError(failure); }
  finally {
    stopped = true;
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
  }
}

function record(value: unknown, failure: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new PushToTalkError(failure);
  return value as Record<string, unknown>;
}

function parseJson(body: unknown, contentLength: unknown, failure: string): Record<string, unknown> {
  if (typeof contentLength === 'string' && (!/^\d+$/.test(contentLength) || Number(contentLength) > JSON_LIMIT)) {
    throw new PushToTalkError(failure);
  }
  if (typeof body !== 'string' || body.length > JSON_LIMIT) throw new PushToTalkError(failure);
  try { return record(JSON.parse(body), failure); }
  catch { throw new PushToTalkError(failure); }
}

async function requestJson(config: ServerConfig, path: string, signal: AbortSignal,
  method: 'GET' | 'POST', body: object | undefined, failure: string): Promise<Record<string, unknown>> {
  const url = base(config, failure) + path;
  return bounded(signal, 3000, failure, async inner => {
    const response = await fetch(url, {
      method, headers: headers(config, method === 'POST'),
      body: body === undefined ? undefined : JSON.stringify(body), signal: inner, cache: 'no-store',
    });
    if (inner.aborted || response.status !== 200) throw new PushToTalkError(failure);
    const length = response.headers?.get('content-length');
    if (length && (!/^\d+$/.test(length) || Number(length) > JSON_LIMIT)) throw new PushToTalkError(failure);
    const text = await response.text();
    if (inner.aborted) throw new PushToTalkError(failure);
    return parseJson(text, length, failure);
  });
}

/** Fail closed unless the hub explicitly reports its microphone trust switch on. */
export async function readMicTrust(config: ServerConfig, signal: AbortSignal): Promise<void> {
  const status = await requestJson(config, '/api/trust/status', signal, 'GET', undefined, TRUST_ERROR);
  if (status.mic !== 'on' || 'error' in status) throw new PushToTalkError(TRUST_ERROR);
}

/** Acquire only this phone's armed mobile lease; never request take-over. */
export async function armMobileMic(config: ServerConfig, client: string, signal: AbortSignal): Promise<void> {
  if (!clientName(client)) throw new PushToTalkError(LEASE_ERROR);
  const response = await requestJson(config, '/api/voice/mic/arm', signal, 'POST',
    { surface: 'mobile', client, take_over: false }, LEASE_ERROR);
  const lease = record(response.lease, LEASE_ERROR);
  const own = `mobile:${client}`;
  if (response.ok !== true || lease.surface !== own || lease.device !== own || lease.kind !== 'mobile' ||
      lease.client !== client || lease.state !== 'armed') throw new PushToTalkError(LEASE_ERROR);
}

/** Finite best-effort release, including when the hub ignores abort. */
export async function releaseMobileMic(config: ServerConfig, client: string): Promise<void> {
  if (!clientName(client)) return;
  try {
    await requestJson(config, '/api/voice/mic/stop', new AbortController().signal,
      'POST', { surface: `mobile:${client}` }, LEASE_ERROR);
  } catch { /* A release failure must not strand the native recorder UI. */ }
}

function contentLength(headersValue: Record<string, string> | undefined): string | undefined {
  const found = Object.entries(headersValue || {}).find(([name]) => name.toLowerCase() === 'content-length');
  return found?.[1];
}

/** Upload one cache-local recording as an exact binary body to local STT. */
export async function transcribeRecording(config: ServerConfig, uri: string, signal: AbortSignal, lang = 'ro'): Promise<string> {
  if (signal.aborted) throw new PushToTalkError(CANCELLED);
  const directory = FileSystem.cacheDirectory;
  const cachePrefix = directory ? directory.replace(/\/?$/, '/') : '';
  const relative = uri.startsWith(cachePrefix) ? uri.slice(cachePrefix.length) : '';
  if (!directory?.startsWith('file://') || !relative || /[%\\?#]/.test(relative) ||
      relative.split('/').some(part => !part || part === '.' || part === '..') ||
      !/^[A-Za-z-]{2,16}$/.test(lang)) throw new PushToTalkError(FILE_ERROR);
  const url = base(config, STT_ERROR) + `/api/voice/stt?lang=${encodeURIComponent(lang)}`;
  let task: ReturnType<typeof FileSystem.createUploadTask> | null = null;
  return bounded(signal, 60000, STT_ERROR, async inner => {
    const info = await FileSystem.getInfoAsync(uri);
    if (inner.aborted) throw new PushToTalkError(STT_ERROR);
    if (!info.exists || info.uri !== uri || info.isDirectory || !Number.isSafeInteger(info.size) || info.size < 1 || info.size > AUDIO_LIMIT) {
      throw new PushToTalkError(FILE_ERROR);
    }
    task = FileSystem.createUploadTask(url, uri, {
      httpMethod: 'POST', uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      sessionType: FileSystem.FileSystemSessionType.FOREGROUND,
      headers: { ...headers(config, false), 'Content-Type': 'audio/mp4' },
    });
    if (inner.aborted) throw new PushToTalkError(STT_ERROR);
    const response = await task.uploadAsync();
    if (inner.aborted || !response || response.status !== 200) throw new PushToTalkError(STT_ERROR);
    const data = parseJson(response.body, contentLength(response.headers), STT_ERROR);
    if (typeof data.text !== 'string' || data.text.length > 4000) throw new PushToTalkError(STT_ERROR);
    if (!data.text.trim() || data.text.trim().toLowerCase() === '[silence]') return '';
    if (/^\[STT (?:error|unavailable)(?:\b|\])/i.test(data.text.trim())) throw new PushToTalkError(STT_ERROR);
    return data.text;
  }, () => {
    if (task) void Promise.resolve().then(() => task?.cancelAsync()).catch(() => {});
  });
}
