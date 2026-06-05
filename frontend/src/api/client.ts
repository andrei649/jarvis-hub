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
  opts: { admin?: boolean; _retried?: boolean } = {},
): Promise<Response> {
  const init: RequestInit = { method, headers: buildHeaders(opts.admin) };
  if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 401 && !opts._retried && typeof window !== 'undefined') {
    let tok = getToken();
    if (!tok && !_prompted) {
      _prompted = true;
      tok = window.prompt('This Jarvis is network-exposed. Enter your X-User-Token:') || '';
      if (tok) setToken(tok);
    }
    if (tok) return request(method, path, body, { ...opts, _retried: true });
  }
  return res;
}

export async function apiGet<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('GET', path, undefined, opts);
  if (!res.ok) throw Object.assign(new Error(`GET ${path} -> ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('POST', path, body, opts);
  if (!res.ok) throw Object.assign(new Error(`POST ${path} -> ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}

export async function postStream(
  path: string,
  body: unknown,
  onEvent: (evt: any) => void,
  opts: { admin?: boolean } = {},
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
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += dec.decode(value, { stream: true });
    if (done) break;
    const parts = buf.split('\n');
    buf = parts.pop() || '';
    for (const p of parts) flush(p);
  }
  if (buf) flush(buf);
}

export async function apiPut<T = unknown>(path: string, body?: unknown, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('PUT', path, body, opts);
  if (!res.ok) throw Object.assign(new Error(`PUT ${path} -> ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}
export async function apiDelete<T = unknown>(path: string, opts?: { admin?: boolean }): Promise<T> {
  const res = await request('DELETE', path, undefined, opts);
  if (!res.ok) throw Object.assign(new Error(`DELETE ${path} -> ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}
