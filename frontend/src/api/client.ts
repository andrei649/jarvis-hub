/* HUD v2 · API client — same-origin fetch with an optional user token and graceful
   errors. The guarded endpoints (/api/agents, /dashboard, /tasks, /ticker) are
   localhost-exempt, so the single-user local case needs no token; on a networked
   deployment a 401 prompts once for X-User-Token and retries (mirrors v1 auth.js). */

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

function buildHeaders(admin?: boolean): Record<string, string> {
  const h: Record<string, string> = { Accept: 'application/json' };
  const u = getToken();
  if (u) h['X-User-Token'] = u;
  if (admin) { const a = getAdminToken(); if (a) h['X-Admin-Token'] = a; }
  return h;
}

let _prompted = false;

async function request(
  method: string,
  path: string,
  body?: unknown,
  opts: { admin?: boolean; signal?: AbortSignal; _retried?: boolean } = {},
): Promise<Response> {
  const init: RequestInit = { method, headers: buildHeaders(opts.admin), signal: opts.signal };
  if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
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

/** Record a mutation failure, then rethrow so existing callers behave unchanged. */
function failMutation(method: string, path: string, status: number): never {
  const message = `${method} ${path} -> ${status}`;
  reportActionFailure(method, path, status, message);
  throw Object.assign(new Error(message), { status });
}

export async function apiGet<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('GET', path, undefined, opts);
  if (!res.ok) throw Object.assign(new Error(`GET ${path} -> ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('POST', path, body, opts);
  if (!res.ok) failMutation('POST', path, res.status);
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

export async function apiPut<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('PUT', path, body, opts);
  if (!res.ok) failMutation('PUT', path, res.status);
  return res.json() as Promise<T>;
}
/* PATCH is the repo's first partial-update verb (DRA-53, `/api/notes/blocks/{id}`):
   a block edit sends only the fields that changed, and a PUT would imply the caller
   is replacing the whole block. Same failure accounting as the other mutators. */
export async function apiPatch<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('PATCH', path, body, opts);
  if (!res.ok) failMutation('PATCH', path, res.status);
  return res.json() as Promise<T>;
}
export async function apiDelete<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('DELETE', path, undefined, opts);
  if (!res.ok) failMutation('DELETE', path, res.status);
  return res.json() as Promise<T>;
}
