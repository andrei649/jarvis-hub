/* HUD v2 · first-party page-view beacon (H22).
 *
 * Privacy-first, in the lineage of the local analytics store (agents/core/
 * analytics_store.py): NO cookies, NO PII, NO cross-site fingerprinting. We post
 * a tiny page-view event to the same-origin ingest route (POST /api/analytics/
 * event) with an EPHEMERAL per-tab session id — a random token kept in
 * sessionStorage, gone when the tab closes, never joined back to a person.
 *
 * Transport: navigator.sendBeacon (survives unload, doesn't block nav), falling
 * back to fetch(keepalive). Analytics must NEVER break the app, so every path
 * swallows its errors and every call guards against SSR / test (no navigator).
 *
 * Body matches AnalyticsEvent in agents/core/routers/analytics.py exactly
 * (extra='forbid'): { name, path?, referrer?, session_id? }. No `props` here.
 */

const ENDPOINT = '/api/analytics/event';
const SESSION_KEY = 'hud.analytics.sid';

// True only in a real browser with the beacon/fetch surface available. Guards
// SSR and the vitest/jsdom-less paths so importing this module is always safe.
function hasBrowser(): boolean {
  return typeof navigator !== 'undefined' && typeof window !== 'undefined';
}

/** Ephemeral, per-tab session id. Random, NOT persistent (sessionStorage), NOT a
 *  fingerprint — it only de-dupes views inside one visit. Stable for the tab's
 *  lifetime; a fresh random id is minted if storage is unavailable. */
export function sessionId(): string {
  const mint = (): string => {
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    } catch { /* fall through */ }
    return 's-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  };
  try {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const id = mint();
    sessionStorage.setItem(SESSION_KEY, id);
    return id;
  } catch {
    // sessionStorage blocked (private mode / SSR) — still return a usable id so
    // the beacon carries one; it just won't be stable across calls.
    return mint();
  }
}

/** POST a JSON body to the ingest endpoint, beacon-first, fetch(keepalive)
 *  fallback. Always swallows errors (returns false instead of throwing). */
function send(body: Record<string, unknown>): boolean {
  if (!hasBrowser()) return false;
  const payload = JSON.stringify(body);
  try {
    if (typeof navigator.sendBeacon === 'function') {
      const blob = new Blob([payload], { type: 'application/json' });
      if (navigator.sendBeacon(ENDPOINT, blob)) return true;
      // sendBeacon returned false (queue full) — fall through to fetch.
    }
  } catch { /* fall through to fetch */ }
  try {
    if (typeof fetch === 'function') {
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(() => { /* analytics never throws */ });
      return true;
    }
  } catch { /* swallow */ }
  return false;
}

/** Record a single page-view. Defaults to the current location's path+search.
 *  Privacy: referrer is best-effort document.referrer (already in the DOM); no
 *  query of the user, no cookies, no ids beyond the ephemeral session token. */
export function trackPageview(path?: string): boolean {
  if (!hasBrowser()) return false;
  try {
    const loc = window.location || ({} as Location);
    const p = path != null ? path : ((loc.pathname || '') + (loc.search || ''));
    const body: Record<string, unknown> = {
      name: 'pageview',
      path: p,
      session_id: sessionId(),
    };
    const ref = typeof document !== 'undefined' ? document.referrer : '';
    if (ref) body.referrer = ref;
    return send(body);
  } catch {
    return false;
  }
}

let _started = false;

/** Initialize page-view tracking: fire once on load. Idempotent — calling it
 *  again (e.g. React StrictMode double-invoke) is a no-op. Returns a function
 *  that records a view for the current HUD view/route, for callers that want to
 *  beacon on view changes. */
export function initAnalytics(): () => void {
  if (_started || !hasBrowser()) return trackPageview;
  _started = true;
  trackPageview();
  return trackPageview;
}
