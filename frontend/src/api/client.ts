import { appUrl } from '../base-path';
import { csrfToken, isNetworkedOrigin, loadOwnerSession, ownerSession, requireSignIn } from './owner-session';
/* HUD v2 · API client — same-origin fetch with an optional user token and graceful
   errors. The guarded endpoints (/api/agents, /dashboard, /tasks, /ticker) are
   localhost-exempt, so the single-user local case needs no token; on a loopback origin a
   401 prompts once for X-User-Token and retries (mirrors v1 auth.js). On a networked
   origin (H509) the owner signs in instead: the hub keeps an HttpOnly session cookie,
   every write carries the session's X-CSRF-Token, and a 401 opens the sign-in screen. */

const TOKEN_KEY = 'hud.user_token';
const ADMIN_KEY = 'hud.admin_token';

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}
export function setToken(v: string): void {
  try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}
export function getAdminToken(): string {
  try { return localStorage.getItem(ADMIN_KEY) || ''; } catch { return ''; }
}

const WRITES = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function buildHeaders(admin?: boolean, method = 'GET'): Record<string, string> {
  const h: Record<string, string> = { Accept: 'application/json' };
  const u = getToken();
  if (u) h['X-User-Token'] = u;
  if (admin) { const a = getAdminToken(); if (a) h['X-Admin-Token'] = a; }
  // H509: a cookie-authenticated write must echo the session's CSRF token. Sent only
  // when no header credential rides along (a header request is judged on its own).
  if (WRITES.has(method) && !h['X-User-Token'] && !h['X-Admin-Token']) {
    const c = csrfToken();
    if (c) h['X-CSRF-Token'] = c;
  }
  return h;
}

/** On a networked origin, the session's CSRF token is learned before the first write. */
function needsOwnerSession(method: string): boolean {
  return WRITES.has(method) && isNetworkedOrigin() && !ownerSession();
}

/** Explicit one-attempt transport for proposals whose response can be lost.
 * It shares the HUD's header credentials, but never prompts, follows redirects,
 * or retries a mutation. Callers bound and validate the response body. */
export function apiFetchOnce(path: string, opts: {
  method?: 'GET' | 'POST'; body?: unknown; admin?: boolean; signal?: AbortSignal; accept?: string;
} = {}): Promise<Response> {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || /[\u0000-\u0020\u007f]/.test(path)) {
    return Promise.reject(new Error('same-origin path required'));
  }
  const headers = buildHeaders(opts.admin, opts.method || 'GET');
  headers.Accept = opts.accept || 'application/json';
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  return fetch(appUrl(path), { method: opts.method || 'GET', headers, signal: opts.signal,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    redirect: 'error', credentials: 'same-origin', cache: 'no-store' });
}

let _prompted = false;

async function request(
  method: string,
  path: string,
  body?: unknown,
  opts: { admin?: boolean; signal?: AbortSignal; _retried?: boolean } = {},
): Promise<Response> {
  // Awaited only when needed: on loopback the fetch still starts synchronously.
  if (needsOwnerSession(method)) await loadOwnerSession();
  const init: RequestInit = { method, headers: buildHeaders(opts.admin, method), signal: opts.signal };
  if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(appUrl(path), init);
  if (isNetworkedOrigin() && typeof window !== 'undefined') {
    // H509: a stale CSRF token (the session was re-opened in another tab) is re-read once.
    if (res.status === 403 && WRITES.has(method) && !opts._retried && csrfToken()) {
      let detail = '';
      try { detail = String((await res.clone().json())?.detail || ''); } catch { /* not JSON */ }
      if (detail.startsWith('csrf')) {
        await loadOwnerSession(true);
        return request(method, path, body, { ...opts, _retried: true });
      }
    }
    if (res.status === 401 && !getToken()) requireSignIn();
    return res;
  }
  if (res.status === 401 && !opts._retried && typeof window !== 'undefined') {
    let tok = getToken();
    if (!tok && !_prompted) {
      _prompted = true;
      tok = window.prompt('This Nerva instance is network-exposed. Enter your X-User-Token:') || '';
      if (tok) setToken(tok);
    }
    if (tok) return request(method, path, body, { ...opts, _retried: true });
  }
  return res;
}

/* ── Failed-mutation sink (2026-07-27 QA, finding F-02) ───────────────────────
   The HUD swallows rejections in 27 places (`.catch(() => {})` in gap.tsx, app.tsx,
   modes.tsx, voice.ts) plus inline catches on direct apiPost/apiPut/apiDelete calls.
   The run pressed HALT ALL, the kernel answered 403 "kernel denied", the catch ate it
   and the card kept reading "ARMED · operational" — an operator told the emergency stop
   was fine when it had been refused.

   Patching call sites cannot fix this class: a new one is one `.catch(() => {})` away.
   So the failure is recorded HERE, where it is created, before it is thrown — every
   downstream swallow still leaves a trace, and the Console renders it (see
   ActionFailureBanner in gap.tsx). GETs are deliberately NOT recorded: panels already
   surface those via <State e={e}/>, and polling failures would drown the signal.        */

export type ActionFailure = { method: string; path: string; status: number; message: string; at: number };

const MAX_FAILURES = 20;
const _failures: ActionFailure[] = [];
const _failureSubs = new Set<(f: ActionFailure[]) => void>();

export function actionFailures(): ActionFailure[] { return _failures.slice(); }

export function onActionFailure(fn: (f: ActionFailure[]) => void): () => void {
  _failureSubs.add(fn);
  return () => { _failureSubs.delete(fn); };
}

export function clearActionFailures(): void {
  _failures.length = 0;
  _failureSubs.forEach((fn) => fn(actionFailures()));
}

function reportActionFailure(method: string, path: string, status: number, message: string): void {
  _failures.unshift({ method, path, status, message, at: Date.now() });
  if (_failures.length > MAX_FAILURES) _failures.length = MAX_FAILURES;
  _failureSubs.forEach((fn) => { try { fn(actionFailures()); } catch { /* a bad subscriber must not eat the report */ } });
}

/** Record a mutation failure, then rethrow so existing callers behave unchanged.

   The refusal BODY rides along on the thrown error (`err.body`) because the routes
   answer with a machine-readable `reason` and, until now, no call site could reach it:
   the throw happened before anyone read the response. A caller left guessing writes a
   plausible-looking cause of its own — exactly the fabrication this HUD exists to
   remove. `message` and `status` are untouched, so existing callers are unaffected;
   a non-JSON or empty error body simply leaves `body` undefined. */
async function failMutation(method: string, path: string, res: Response): Promise<never> {
  let body: unknown;
  try { body = await res.json(); } catch { /* non-JSON, empty, or already-consumed body */ }
  return failWithBody(method, path, res.status, body);
}

function failWithBody(method: string, path: string, status: number, body: unknown): never {
  const message = `${method} ${path} -> ${status}`;
  reportActionFailure(method, path, status, message);
  throw Object.assign(new Error(message), { status, body });
}

/** A refusal the caller names as its expected answer. ToolRPC queues a gated tool's
    owner-approval task and answers 422 `approval_required` with its task id: that is the
    task being created, not a failed action, and the Console banner must not call it one
    (review of #1321). Every other refusal is still recorded and thrown. */
export type AcceptRefusal = (status: number, body: unknown) => boolean;

export async function apiGet<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('GET', path, undefined, opts);
  if (!res.ok) {
    // The refusal body rides along (`err.body`), as it does for a mutation: a caller can
    // tell the hub's own answer from a proxy's. A non-JSON body leaves it undefined.
    let body: unknown;
    try { body = await res.json(); } catch { /* non-JSON, empty, or already-consumed body */ }
    throw Object.assign(new Error(`GET ${path} -> ${res.status}`), { status: res.status, body });
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(path: string, body?: unknown,
  opts?: { admin?: boolean; accept?: AcceptRefusal }): Promise<T> {
  const res = await request('POST', path, body, opts?.admin === undefined ? undefined : { admin: opts.admin });
  if (!res.ok) {
    if (!opts?.accept) await failMutation('POST', path, res);
    let refusal: unknown;
    try { refusal = await res.json(); } catch { /* non-JSON, empty, or already-consumed body */ }
    if (opts?.accept?.(res.status, refusal)) return refusal as T;
    failWithBody('POST', path, res.status, refusal);
  }
  return res.json() as Promise<T>;
}

export async function postStream(
  path: string,
  body: unknown,
  onEvent: (evt: any) => void,
  opts: { admin?: boolean; signal?: AbortSignal } = {},
): Promise<void> {
  const res = await request('POST', path, body, opts);
  if (!res.ok || !res.body) throw Object.assign(new Error(`stream ${path} -> ${res.status}`), { status: res.status });
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  const flush = (line: string) => {
    const s = line.trim();
    if (!s.startsWith('data:')) return;
    try { onEvent(JSON.parse(s.slice(s.indexOf(':') + 1).trim())); } catch { /* ignore */ }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (value) buf += dec.decode(value, { stream: true });
      if (done) break;
      const parts = buf.split('\n');
      buf = parts.pop() || '';
      for (const p of parts) flush(p);
    }
  } catch (err) {
    // Aborting the signal rejects the in-flight read; close the reader and
    // rethrow so the caller can tell a user stop (AbortError) from a failure.
    try { await reader.cancel(); } catch { /* already closed */ }
    throw err;
  }
  if (buf) flush(buf);
}

export async function apiPut<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean; conflictIsExpected?: boolean }): Promise<T> {
  const res = await request('PUT', path, body, opts);
  if (res.status === 409 && opts?.conflictIsExpected) throw Object.assign(new Error('Revision changed'), {status:409});
  if (!res.ok) await failMutation('PUT', path, res);
  return res.json() as Promise<T>;
}
/* PATCH is the repo's first partial-update verb (DRA-53, `/api/notes/blocks/{id}`):
   a block edit sends only the fields that changed, and a PUT would imply the caller
   is replacing the whole block. Same failure accounting as the other mutators. */
export async function apiPatch<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('PATCH', path, body, opts);
  if (!res.ok) await failMutation('PATCH', path, res);
  return res.json() as Promise<T>;
}
export async function apiDelete<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('DELETE', path, undefined, opts);
  if (!res.ok) await failMutation('DELETE', path, res);
  return res.json() as Promise<T>;
}
/** Revisioned owner deletes carry their expected CAS value in a JSON body. */
export async function apiDeleteBody<T = unknown>(path: string, body: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('DELETE', path, body, opts);
  if (!res.ok) await failMutation('DELETE', path, res);
  return res.json() as Promise<T>;
}
