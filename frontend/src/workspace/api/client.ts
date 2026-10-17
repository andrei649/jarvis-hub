/* The one HTTP client every Workspace screen goes through.

   Why a single choke point: the workspace authenticates with an httpOnly session cookie plus a
   synchronizer CSRF token (spec §6), so every mutating request must carry `X-CSRF-Token` from
   the current session, every failure must surface as the server's stable `error` code (the UI
   translates codes, never English server prose), and an expired session must route the user
   back to the login screen instead of leaving half-broken pages behind.

   Callers pass the full URL, written as a literal at the call site (`appUrl(`/api/workspace/…`)`),
   so the route-parity gate can see every endpoint the UI calls. */
import type { ApiErrorBody } from './types';

export class WorkspaceApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly extra: Record<string, unknown>;

  constructor(code: string, message: string, status: number, extra: Record<string, unknown> = {}) {
    super(message || code);
    this.name = 'WorkspaceApiError';
    this.code = code;
    this.status = status;
    this.extra = extra;
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestOptions {
  /** JSON-serialisable body; sent with `Content-Type: application/json`. */
  json?: unknown;
  /** A raw body (file upload); `contentType` names its media type. */
  raw?: Blob | ArrayBuffer | Uint8Array;
  contentType?: string;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** Skip the session-expiry hook (the auth screens handle their own 401s). */
  skipAuthRedirect?: boolean;
}

interface SessionHooks {
  /** Called once per expired session; the session layer re-reads /session and shows login. */
  onAuthRequired: () => void;
  /** Re-reads the session and returns the fresh CSRF token (null when signed out). */
  refreshCsrf: () => Promise<string | null>;
}

const MUTATING: ReadonlySet<HttpMethod> = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

let csrfToken: string | null = null;
let hooks: SessionHooks | null = null;

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token || null;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function setSessionHooks(next: SessionHooks | null): void {
  hooks = next;
}

/** Lets streaming callers report an expired session the same way the JSON client does. */
export function reportSessionFailure(error: WorkspaceApiError): void {
  if (error.status === 401 && error.code === 'auth_required') hooks?.onAuthRequired();
}

export function isMutating(method: HttpMethod): boolean {
  return MUTATING.has(method);
}

/** Headers shared by JSON and streaming requests: the CSRF token rides on every write. */
export function baseHeaders(method: HttpMethod, extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (isMutating(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return headers;
}

function bodyInit(opts: RequestOptions, method: HttpMethod, headers: Record<string, string>): BodyInit | undefined {
  if (opts.raw !== undefined) {
    headers['Content-Type'] = opts.contentType || 'application/octet-stream';
    return opts.raw as BodyInit;
  }
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    return JSON.stringify(opts.json);
  }
  if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
    // Public workspace POSTs require a JSON content type even when there is nothing to send.
    headers['Content-Type'] = 'application/json';
    return '{}';
  }
  return undefined;
}

async function readErrorBody(response: Response): Promise<ApiErrorBody | null> {
  const type = response.headers.get('Content-Type') || '';
  if (!type.includes('json')) return null;
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === 'object') {
      const body = parsed as Record<string, unknown>;
      if (typeof body.error === 'string') return body as ApiErrorBody;
      // FastAPI's default validation body ({"detail": [...]}) when no handler is installed.
      if ('detail' in body) return { error: 'invalid_request', message: '' };
    }
  } catch {
    return null;
  }
  return null;
}

/** Turns a failed response into a typed error carrying the server's code and extras. */
export async function toApiError(response: Response): Promise<WorkspaceApiError> {
  const body = await readErrorBody(response);
  if (body) {
    const { error, message, ...extra } = body;
    return new WorkspaceApiError(error, typeof message === 'string' ? message : '', response.status, extra);
  }
  const code = response.status >= 500 ? 'server_error' : `http_${response.status}`;
  return new WorkspaceApiError(code, response.statusText || '', response.status);
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException ? err.name === 'AbortError' : (err as Error)?.name === 'AbortError';
}

/** fetch with the workspace conventions; returns the raw Response (ok or not). */
export async function send(method: HttpMethod, url: string, opts: RequestOptions = {}): Promise<Response> {
  const headers = baseHeaders(method, { Accept: 'application/json', ...opts.headers });
  const body = bodyInit(opts, method, headers);
  try {
    return await fetch(url, { method, headers, body, credentials: 'same-origin', cache: 'no-store', signal: opts.signal });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new WorkspaceApiError('network_error', String((err as Error)?.message || ''), 0);
  }
}

/**
 * Handles the two session failures centrally: `auth_required` (the session expired or was
 * revoked → re-read the session so the app shows login) and `csrf_failed` (the token rotated,
 * e.g. after a new login in another tab → refresh it and replay the write once).
 */
async function withSessionRecovery(
  method: HttpMethod, url: string, opts: RequestOptions, response: Response,
): Promise<Response> {
  if (response.ok || opts.skipAuthRedirect) return response;
  if (response.status === 403 && isMutating(method) && hooks) {
    const error = await toApiError(response.clone());
    if (error.code === 'csrf_failed') {
      const fresh = await hooks.refreshCsrf();
      if (fresh) return send(method, url, opts);
    }
  }
  if (response.status === 401 && hooks) reportSessionFailure(await toApiError(response.clone()));
  return response;
}

async function parseBody<T>(response: Response): Promise<T> {
  if (response.status === 204 || response.status === 205) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new WorkspaceApiError('invalid_response', '', response.status);
  }
}

/** Sends a request and resolves with the parsed JSON body (undefined for 204). */
export async function request<T = unknown>(method: HttpMethod, url: string, opts: RequestOptions = {}): Promise<T> {
  const first = await send(method, url, opts);
  const response = await withSessionRecovery(method, url, opts, first);
  if (!response.ok) throw await toApiError(response);
  return parseBody<T>(response);
}

export const api = {
  get: <T>(url: string, opts?: RequestOptions) => request<T>('GET', url, opts),
  post: <T>(url: string, json?: unknown, opts?: RequestOptions) => request<T>('POST', url, { ...opts, json }),
  put: <T>(url: string, json?: unknown, opts?: RequestOptions) => request<T>('PUT', url, { ...opts, json }),
  patch: <T>(url: string, json?: unknown, opts?: RequestOptions) => request<T>('PATCH', url, { ...opts, json }),
  del: <T = void>(url: string, opts?: RequestOptions) => request<T>('DELETE', url, opts),
};

/** Builds `?a=1&b=2` from defined, non-empty values (order preserved). */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, typeof value === 'boolean' ? (value ? '1' : '0') : String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export function isApiError(err: unknown): err is WorkspaceApiError {
  return err instanceof WorkspaceApiError;
}

export { isAbort };
