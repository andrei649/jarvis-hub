import type { ServerConfig } from '../storage/settings';

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

/** Normalise user input into a usable origin: add scheme, strip trailing slashes. */
export function normalizeBaseUrl(raw: string): string {
  let url = (raw || '').trim();
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
  return url.replace(/\/+$/, '');
}

function authHeaders(config: ServerConfig, json: boolean): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (json) headers['Content-Type'] = 'application/json';
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  return headers;
}

async function request<T>(
  config: ServerConfig,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  let res: Response;
  try {
    res = await fetch(base + path, {
      method,
      headers: authHeaders(config, body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(`Could not reach ${base} — check the URL and network`);
  }
  if (!res.ok) {
    if (res.status === 401) throw new ApiError('Unauthorized — check your user token', 401);
    throw new ApiError(`Server returned HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
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
  return request<StatusResponse>(config, 'GET', '/status');
}

// ── Chat (streaming SSE over XHR) ─────────────────────────────────

export type StreamHandlers = {
  onStart?: (agent: string) => void;
  onToken: (text: string) => void;
  onDone: (full: string) => void;
  onError: (message: string) => void;
};

type SseEvent = { type: string; text?: string; agent?: string };

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
  let consumed = 0; // chars of responseText already scanned
  let buffer = ''; // incomplete trailing line
  let finished = false;

  const dispatch = (raw: string) => {
    const line = raw.trim();
    if (!line.startsWith('data:')) return;
    const payload = line.slice(line.indexOf(':') + 1).trim();
    if (!payload) return;
    let evt: SseEvent;
    try {
      evt = JSON.parse(payload);
    } catch {
      return;
    }
    if (evt.type === 'start') handlers.onStart?.(evt.agent || agent);
    else if (evt.type === 'token') handlers.onToken(evt.text || '');
    else if (evt.type === 'end') {
      finished = true;
      handlers.onDone(evt.text || '');
    }
  };

  const drain = (chunk: string) => {
    buffer += chunk;
    let nl: number;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl);
      buffer = buffer.slice(nl + 1);
      dispatch(line);
    }
  };

  xhr.open('POST', base + '/chat/stream');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.setRequestHeader('Accept', 'text/event-stream');
  if (config.token.trim()) xhr.setRequestHeader('X-User-Token', config.token.trim());

  xhr.onreadystatechange = () => {
    if (xhr.readyState >= 3 && xhr.status === 200) {
      const text = xhr.responseText;
      if (text.length > consumed) {
        drain(text.slice(consumed));
        consumed = text.length;
      }
    }
    if (xhr.readyState === 4) {
      if (xhr.status === 0) return; // aborted
      if (xhr.status !== 200) {
        handlers.onError(
          xhr.status === 401 ? 'Unauthorized — check your user token' : `Server returned HTTP ${xhr.status}`,
        );
      } else if (!finished) {
        // Stream closed without an explicit end frame.
        handlers.onDone('');
      }
    }
  };
  xhr.onerror = () => handlers.onError(`Could not reach ${base} — check the URL and network`);

  xhr.send(JSON.stringify({ message, agent }));

  return () => {
    try {
      xhr.abort();
    } catch {
      // ignore
    }
  };
}
