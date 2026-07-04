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
  method: 'GET' | 'POST',
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

// ── Approvals ────────────────────────────────────────────────────

export type ApprovalAction = 'accept' | 'reject' | 'defer';

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
