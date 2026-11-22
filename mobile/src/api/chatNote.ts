import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

export type ChatNoteTarget = { id: string; vault: string; inbox: string };
export type ChatNoteDraft = { target: ChatNoteTarget; title: string; content: string; requestId: string };
export type ChatNoteReceipt = { relPath: string; source: { vault: string; file: string; readable: true } | null };

export class ChatNoteTitleConflict extends ApiError {
  constructor() {
    super('A note already uses this title. Change the title and save again.', 409);
    this.name = 'ChatNoteTitleConflict';
  }
}

const invalidNativePart = /[\\/:*?"<>|#^%\u0000-\u001f\u007f]/;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const validPart = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value !== '.' && value !== '..' &&
  !value.includes('\\') && !value.includes('/') && !value.includes('\u0000') && validUnicode(value);
const validNativePart = (value: unknown): value is string =>
  validPart(value) && value === value.trim() && !value.startsWith('.') &&
  !value.endsWith('.') && !invalidNativePart.test(value);
const validPath = (value: unknown): value is string =>
  typeof value === 'string' && value.length <= 4096 && value.split('/').every(validPart);
const validUnicode = (value: string) => {
  try { encodeURIComponent(value); return true; } catch { return false; }
};

function validTarget(value: unknown): value is ChatNoteTarget {
  return isRecord(value) && typeof value.id === 'string' && /^v1-[0-9a-f]{64}$/.test(value.id) &&
    validPart(value.vault) && value.vault.length <= 255 && validPath(value.inbox) &&
    value.inbox.split('/').every(part => !part.startsWith('.'));
}

function validReceipt(value: unknown, target: ChatNoteTarget): value is ChatNoteReceipt {
  if (!isRecord(value) || !validPath(value.relPath) ||
    !value.relPath.startsWith(`${target.inbox}/`) ||
    value.relPath.slice(target.inbox.length + 1).includes('/') ||
    !value.relPath.toLowerCase().endsWith('.md')) return false;
  return value.source === null || (isRecord(value.source) && value.source.vault === target.vault &&
    value.source.file === value.relPath && value.source.readable === true &&
    validNativePart(value.source.vault) && value.relPath.split('/').every(validNativePart));
}

/** Keep only the confirmed destination and note link when saving a chat cache. */
export function projectSavedChatNote(value: unknown): { target: ChatNoteTarget; receipt: ChatNoteReceipt } | null {
  if (!isRecord(value) || !validTarget(value.target) || !validReceipt(value.receipt, value.target)) return null;
  const target = value.target;
  const receipt = value.receipt;
  return {
    target: { id: target.id, vault: target.vault, inbox: target.inbox },
    receipt: { relPath: receipt.relPath, source: receipt.source === null ? null : {
      vault: receipt.source.vault, file: receipt.source.file, readable: true,
    } },
  };
}

function baseUrl(config: ServerConfig): string {
  const raw = normalizeBaseUrl(config.baseUrl);
  if (!raw) throw new ApiError('No server URL configured');
  try {
    if (raw.includes('\\')) throw new Error('Invalid server URL');
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('Invalid server URL');
    }
    return url.href.replace(/\/+$/, '');
  } catch { throw new ApiError('Invalid server URL'); }
}

async function chatNoteRequest(config: ServerConfig, path: string, body?: unknown): Promise<{ status: number; data: unknown }> {
  const base = baseUrl(config);
  const headers: Record<string, string> = { Accept: 'application/json', 'Cache-Control': 'no-store' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const { fetch: nativeFetch } = await import('expo/fetch');
    const response = await nativeFetch(base + path, {
      method: body === undefined ? 'GET' : 'POST', headers,
      body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      redirect: 'error', credentials: 'omit',
    });
    let data: unknown;
    try { data = await response.json(); }
    catch {
      if (response.status >= 200 && response.status < 300) throw new ApiError('Invalid chat note response');
      data = null;
    }
    if (controller.signal.aborted) throw new ApiError('Chat note request timed out');
    return { status: response.status, data };
  } catch (error) {
    if (controller.signal.aborted) throw new ApiError('Chat note request timed out');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Chat note request unavailable');
  } finally { clearTimeout(timer); }
}

function requireSuccess(response: { status: number; data: unknown }): unknown {
  if (response.status < 200 || response.status >= 300) {
    throw new ApiError(response.status === 401 ? 'Unauthorized — check your user token'
      : `Server returned HTTP ${response.status}`, response.status);
  }
  return response.data;
}

export async function fetchChatNoteTarget(config: ServerConfig): Promise<ChatNoteTarget | null> {
  const data = requireSuccess(await chatNoteRequest(config, '/api/os/status'));
  if (!isRecord(data) || data.ok !== true || !Object.prototype.hasOwnProperty.call(data, 'captureTarget') ||
    (data.captureTarget !== null && !validTarget(data.captureTarget))) {
    throw new ApiError('Invalid vault status');
  }
  if (data.captureTarget === null) return null;
  const target = data.captureTarget as ChatNoteTarget;
  return { id: target.id, vault: target.vault, inbox: target.inbox };
}

export async function saveChatNote(config: ServerConfig, draft: ChatNoteDraft): Promise<ChatNoteReceipt> {
  if (!isRecord(draft) || !validTarget(draft.target) ||
    typeof draft.requestId !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(draft.requestId) ||
    typeof draft.title !== 'string' || !draft.title.trim() || Array.from(draft.title).length > 120 ||
    typeof draft.content !== 'string' || !draft.content.trim() || Array.from(draft.content).length > 100_000 ||
    !validUnicode(draft.title) || !validUnicode(draft.content)) throw new ApiError('Invalid chat note draft');
  const response = await chatNoteRequest(config, '/api/os/brain/chat-note', {
    targetId: draft.target.id, requestId: draft.requestId, title: draft.title, content: draft.content,
  });
  if (response.status === 409 && isRecord(response.data) && response.data.ok === false &&
    response.data.code === 'title_conflict') throw new ChatNoteTitleConflict();
  const data = requireSuccess(response);
  if (!isRecord(data) || data.ok !== true || !validReceipt(data, draft.target)) {
    throw new ApiError('Invalid save receipt');
  }
  return { relPath: data.relPath, source: data.source };
}

export async function readSavedChatNote(
  config: ServerConfig, target: ChatNoteTarget, receipt: ChatNoteReceipt,
): Promise<string> {
  if (!validTarget(target) || !validReceipt(receipt, target)) throw new ApiError('Invalid saved note path');
  const path = `/api/os/brain/note?relPath=${encodeURIComponent(receipt.relPath)}&targetId=${encodeURIComponent(target.id)}`;
  const data = requireSuccess(await chatNoteRequest(config, path));
  if (!isRecord(data) || data.ok !== true || data.targetId !== target.id ||
    data.relPath !== receipt.relPath || typeof data.body !== 'string' ||
    Array.from(data.body).length > 100_000 || !validUnicode(data.body)) {
    throw new ApiError('Invalid saved note response');
  }
  return data.body;
}
