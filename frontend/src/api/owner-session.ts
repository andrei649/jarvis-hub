import { appUrl } from '../base-path';
/* Owner browser sign-in for a networked Nerva (H509). The hub keeps the session in an
   HttpOnly cookie the page never sees; what the page holds is the session's CSRF token,
   in memory only, which it echoes in X-CSRF-Token on every write. On a loopback origin
   none of this runs: a fresh box trusts a direct loopback browser exactly as before. */

const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);

export type OwnerSession = {
  signed_in: boolean;
  csrf?: string;
  expires_at?: number;
  idle_expires_at?: number;
  sign_in_available?: boolean;
};

let _session: OwnerSession | null = null;
let _loading: Promise<OwnerSession> | null = null;
const _subs = new Set<(s: OwnerSession | null, wanted: boolean) => void>();
let _wanted = false;

/** True when the HUD was opened by a network name or address, not loopback. */
export function isNetworkedOrigin(): boolean {
  if (typeof window === 'undefined' || !window.location) return false;
  const host = (window.location.hostname || '').toLowerCase();
  return !!host && !LOOPBACK.has(host);
}

export function ownerSession(): OwnerSession | null { return _session; }
export function csrfToken(): string { return _session?.signed_in ? _session.csrf || '' : ''; }
export function signInWanted(): boolean { return _wanted; }

function publish(): void {
  _subs.forEach((fn) => { try { fn(_session, _wanted); } catch { /* a bad subscriber must not break auth */ } });
}

export function onOwnerSession(fn: (s: OwnerSession | null, wanted: boolean) => void): () => void {
  _subs.add(fn);
  return () => { _subs.delete(fn); };
}

/** Ask the shell to show the sign-in screen (a networked request answered 401). */
export function requireSignIn(): void {
  if (!_wanted) { _wanted = true; publish(); }
}

/** Read the session from the hub (once; `force` re-reads, e.g. after a CSRF refusal). */
export function loadOwnerSession(force = false): Promise<OwnerSession> {
  if (_loading && !force) return _loading;
  _loading = fetch(appUrl('/api/auth/session'), {
    headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store',
  }).then(async (res) => {
    const body = res.ok ? await res.json() as OwnerSession : { signed_in: false };
    _session = body;
    publish();
    return body;
  }).catch(() => {
    _session = { signed_in: false };
    publish();
    return _session;
  });
  return _loading;
}

export type SignInResult = { ok: true } | { ok: false; status: number; message: string; retryAfter?: number };

/** Exchange the owner secret for the session cookie. The secret is never stored. */
export async function signIn(secret: string): Promise<SignInResult> {
  let res: Response;
  try {
    res = await fetch(appUrl('/api/auth/login'), {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ secret }),
    });
  } catch {
    return { ok: false, status: 0, message: 'The hub could not be reached.' };
  }
  let body: any = {};
  try { body = await res.json(); } catch { /* non-JSON answer */ }
  if (res.ok && body?.signed_in) {
    _session = { signed_in: true, csrf: body.csrf, expires_at: body.expires_at, sign_in_available: true };
    _loading = Promise.resolve(_session);
    _wanted = false;
    publish();
    return { ok: true };
  }
  const retryAfter = Number(res.headers.get('Retry-After')) || body?.retry_after_seconds || undefined;
  const message = res.status === 401 ? "That is not this hub's owner secret."
    : res.status === 429 ? `Too many failed attempts. Try again in ${Math.max(1, Math.ceil((retryAfter || 60) / 60))} min.`
    : (typeof body?.message === 'string' && body.message) || `Sign-in failed (${res.status}).`;
  return { ok: false, status: res.status, message, retryAfter };
}

async function post(path: string, csrf?: string): Promise<boolean> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (csrf) headers['X-CSRF-Token'] = csrf;
  try {
    const res = await fetch(appUrl(path), { method: 'POST', credentials: 'same-origin',
      cache: 'no-store', redirect: 'error', headers });
    return res.ok;
  } catch { return false; }
}

/** End this browser's session (the hub revokes it and expires the cookie). */
export async function signOut(): Promise<boolean> {
  const ok = await post('/api/auth/logout');
  _session = { signed_in: false, sign_in_available: true };
  _loading = Promise.resolve(_session);
  _wanted = true;
  publish();
  return ok;
}

/** End every owner browser session, on every device. */
export async function signOutEverywhere(): Promise<boolean> {
  const ok = await post('/api/auth/logout-all', csrfToken());
  if (ok) {
    _session = { signed_in: false, sign_in_available: true };
    _loading = Promise.resolve(_session);
    _wanted = true;
    publish();
  }
  return ok;
}

/** Test seam: forget everything this module learned. */
export function _resetOwnerSessionForTests(): void {
  _session = null; _loading = null; _wanted = false; _subs.clear();
}
