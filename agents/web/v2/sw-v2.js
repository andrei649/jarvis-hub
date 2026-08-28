/* T-0.29 — service worker for the HUD v2 (the shipped default surface).
 *
 * The legacy /sw.js is the v1 worker: it pre-caches a hardcoded list of v1
 * asset paths. That approach cannot work for v2, whose filenames are
 * content-hashed per build (index-CXqAhDbl.js) — a static list would be stale
 * the moment anyone rebuilds, and `cache.addAll` fails ATOMICALLY on a single
 * 404, so one stale entry silently breaks the whole install. This worker uses
 * runtime caching instead, so it never references a filename it didn't observe.
 *
 * Strategy, deliberately conservative for a local-first product handling
 * personal data:
 *   - /v2/assets/*        cache-first  (content-hashed ⇒ immutable by construction)
 *   - navigations         network-first, cached shell as the offline fallback
 *   - everything else     NETWORK-ONLY — never cached
 *
 * That last rule is the important one: API reads carry personal data
 * (conversations, memory, house/camera state). Caching them would leave a
 * plaintext copy in the browser's Cache Storage that `forget` cannot reach,
 * quietly breaking the erasure promise in PRIVACY.md. So the allowlist is
 * inverted — only the two provably-safe classes are cached, and everything
 * else, including every /api/ path, goes straight to the network.
 */
const CACHE = 'nerva-hud-v2-1';
const SHELL = '/';

self.addEventListener('install', (event) => {
  // Cache only the app shell — no asset list to go stale.
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.add(SHELL))
      .catch(() => {})          // an offline first-install must not wedge the SW
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isImmutableAsset(url) {
  // Vite emits content-hashed files under /v2/assets — safe to serve from cache
  // forever, because a change produces a different filename.
  return url.pathname.startsWith('/v2/assets/');
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;                     // never touch mutations
  let url;
  try { url = new URL(req.url); } catch { return; }
  if (url.origin !== self.location.origin) return;      // third-party: untouched

  if (isImmutableAsset(url)) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })),
    );
    return;
  }

  if (req.mode === 'navigate') {
    // Network-first so a running server always wins; the cached shell is only
    // the offline fallback (the HUD then shows its own honest offline states).
    event.respondWith(
      fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(SHELL, copy)).catch(() => {});
        }
        return res;
      }).catch(() => caches.match(SHELL).then((hit) => hit || Response.error())),
    );
    return;
  }

  // Everything else (all /api/*, /chat, /tts, …) is network-only by omission:
  // no respondWith ⇒ the browser performs its normal fetch and nothing is stored.
});
