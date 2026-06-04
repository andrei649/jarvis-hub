const CACHE_NAME = 'jarvis-hud-v3';
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/fonts.css',
  '/static/style.css',
  '/static/systems.css',
  '/static/favicon.svg',
  '/static/react.production.min.js',
  '/static/react-dom.production.min.js',
  '/static/i18n.js',
  '/static/data.js',
  '/static/components.js',
  '/static/network.js',
  '/static/enhancements.js',
  '/static/cognition.js',
  '/static/systems.js',
  '/static/workflows.js',
  '/static/observability.js',
  '/static/dossier-modal.js',
  '/static/console.js',
  '/static/tools.js',
  '/static/app.js'
];

// Network-Only patterns (dynamic status updates, streaming, and command APIs)
const EXCLUDE_PATTERNS = [
  '/status',
  '/ticker',
  '/chat',
  '/tts',
  '/api/',
  '/plugins',
  '/learning',
  '/memory',
  '/bench',
  '/security'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[Service Worker] Pre-caching offline asset shell');
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            console.log('[Service Worker] Clearing old cache', cache);
            return caches.delete(cache);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Check if this request should bypass the cache entirely (Network-Only)
  const isExcluded = EXCLUDE_PATTERNS.some(pattern => url.pathname.includes(pattern));

  if (isExcluded || event.request.method !== 'GET') {
    // Network-Only Strategy. Resolve failures to a network-error Response so the
    // page still sees a failed fetch (its own error handling kicks in) without the
    // service worker emitting an uncaught "Failed to fetch" promise rejection.
    event.respondWith(fetch(event.request).catch(() => Response.error()));
    return;
  }

  // Cache-First (Network-Falling-Back-to-Cache) Strategy
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        // Fetch in background to update cache (Stale-While-Revalidate pattern) for non-critical assets
        fetch(event.request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, networkResponse);
            });
          }
        }).catch(() => { /* Ignore offline fetch errors for background sync */ });
        
        return cachedResponse;
      }

      return fetch(event.request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }

        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseToCache);
        });

        return networkResponse;
      }).catch(() => {
        // Return cached root shell if navigate requests fail offline; otherwise
        // resolve to a network-error Response. respondWith() requires a Response,
        // so we must never resolve to undefined ("Failed to convert value to 'Response'").
        if (event.request.mode === 'navigate') {
          return caches.match('/').then((cached) => cached || Response.error());
        }
        return Response.error();
      });
    })
  );
});
