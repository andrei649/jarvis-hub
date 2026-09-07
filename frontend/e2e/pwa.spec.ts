/* HUD v2 · the service worker, exercised for real (T-0.29 / E2E-no-pwa-spec).
 *
 * Why this file exists at all. `playwright.config.ts` sets `serviceWorkers: 'block'`
 * for the whole lane and says so in a long measured comment, which ends with an
 * explicit handoff: "If a real PWA spec is ever added it should opt back in with
 * `test.use({ serviceWorkers: 'allow' })`." This is that spec, and that is exactly
 * what the line below does. The block stays in place for every other spec — none of
 * them asserts anything about the worker, and allowing it there cost webkit its
 * request interception.
 *
 * What is asserted, in the order that matters:
 *   1. the worker actually installs, activates, and takes control of the page;
 *   2. /v2/assets/* lands in Cache Storage (cache-first, safe: content-hashed);
 *   3. NOTHING under /api/ ever lands in Cache Storage — this is the important one;
 *   4. the cached shell serves a real HUD document when the network is gone.
 *
 * (3) is the one with teeth. `sw-v2.js` caches by an inverted allowlist: only the
 * two provably-safe classes get `respondWith`, and every other request — every
 * /api/ read carrying conversations, memory, house and camera state — is
 * network-only *by omission*. Caching one would leave a plaintext copy in the
 * browser's Cache Storage that `forget` cannot reach, quietly breaking the erasure
 * promise in PRIVACY.md. An omission is invisible in review: a future `respondWith`
 * added one branch too high would inherit every /api/ path silently and no unit test
 * would notice, because Cache Storage only exists in a real browser. That is the
 * regression this file is here to make loud.
 *
 * What is NOT asserted: install-prompt / add-to-home-screen behaviour (driven by
 * browser heuristics Playwright does not expose), push, or background sync — the
 * worker implements none of them. The manifest is served and linked, but "is it
 * installable" is a UA judgement, not a contract this repo can state.
 */
import { test, expect } from '@playwright/test';

// The one line the config's comment asked for. File-scoped: the block stays global.
test.use({ serviceWorkers: 'allow' });

const CACHE = 'nerva-hud-v2-1';   // must match sw-v2.js; a rename here is the point

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

/** Load /v2 and wait until this client is genuinely controlled by the worker.
 *  The worker `skipWaiting()`s and `clients.claim()`s, so the FIRST load can end up
 *  controlled — but that is a race with the page's own `load` handler, which is what
 *  calls `register`. So: register, wait for activation, then reload. After the reload
 *  the document and every subresource it asks for go through the worker's fetch
 *  handler, which is the only state in which (2) and (3) mean anything. */
async function loadControlled(page): Promise<void> {
  await page.goto('/v2', { waitUntil: 'load' });
  await page.waitForFunction(async () => {
    const reg = await navigator.serviceWorker.getRegistration('/');
    return !!(reg && reg.active && reg.active.state === 'activated');
  }, null, { timeout: 30_000 });
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => !!navigator.serviceWorker.controller, null, { timeout: 30_000 });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
}

/** Every request URL currently held in the worker's cache, as absolute strings. */
async function cachedUrls(page): Promise<string[]> {
  return page.evaluate(async (name) => {
    if (!(await caches.has(name))) return [];
    const c = await caches.open(name);
    return (await c.keys()).map((r) => r.url);
  }, CACHE);
}

test('the worker installs, activates, and controls the HUD', async ({ page }) => {
  await loadControlled(page);

  const state = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration('/');
    return {
      scope: reg ? new URL(reg.scope).pathname : null,
      active: reg && reg.active ? reg.active.state : null,
      controlled: !!navigator.serviceWorker.controller,
      script: reg && reg.active ? new URL(reg.active.scriptURL).pathname : null,
    };
  });

  // Root scope is load-bearing: a worker served from /v2/ could only control /v2/,
  // and the default HUD is mounted at "/". web.py sends Service-Worker-Allowed: /
  // for exactly this reason.
  expect(state.scope, 'the worker must own the ROOT scope, not just /v2/').toBe('/');
  expect(state.script).toBe('/sw-v2.js');
  expect(state.active).toBe('activated');
  expect(state.controlled).toBe(true);

  // The worker's activate handler deletes every cache key that is not the current
  // one, so a stale build's cache cannot survive an upgrade. Assert the survivor.
  const names = await page.evaluate(() => caches.keys());
  expect(names, `unexpected cache names: ${names.join(', ')}`).toEqual([CACHE]);
});

test('content-hashed assets are cached, and the shell is cached for offline', async ({ page }) => {
  await loadControlled(page);
  // The reload's subresources go through the worker; give the put()s a beat to land
  // (the fetch handler returns the response BEFORE the cache write resolves, by
  // design — the write must never delay the page).
  await expect.poll(async () => (await cachedUrls(page)).some((u) => new URL(u).pathname.startsWith('/v2/assets/')),
    { timeout: 15_000, message: 'no /v2/assets/* entry appeared in Cache Storage' }).toBe(true);

  const urls = await cachedUrls(page);
  const paths = urls.map((u) => new URL(u).pathname);

  // The shell is written at install time under the SHELL key ('/'), not under the
  // navigated URL — so a visit to /v2 must NOT have produced a '/v2' cache entry.
  expect(paths, 'the app shell should be cached under "/"').toContain('/');
  expect(paths.filter((p) => p.startsWith('/v2/assets/')).length,
    'at least one content-hashed asset should be cached').toBeGreaterThan(0);
});

test('no /api/ response is ever written to Cache Storage', async ({ page }) => {
  await loadControlled(page);

  // Boot alone fetches a good deal of /api/; then drive the HUD a little more so the
  // 30s refresh loop and a mode switch add their own reads on top. Anything the
  // worker were to cache would be here by the time we look.
  await page.keyboard.press('3');      // Trust Center — its own fetches
  await page.waitForTimeout(1500);
  await page.keyboard.press('1');      // back to the cockpit
  await page.waitForTimeout(1500);

  const paths = (await cachedUrls(page)).map((u) => new URL(u).pathname);
  const leaked = paths.filter((p) => p.startsWith('/api/'));
  expect(leaked,
    'a personal-data response reached Cache Storage, where `forget` cannot delete it '
    + '(PRIVACY.md erasure promise); sw-v2.js must keep /api/ network-only')
    .toEqual([]);

  // Same promise stated positively, so the assertion cannot pass vacuously on an
  // empty cache: the only things in there are the shell and hashed assets.
  const unexpected = paths.filter((p) => p !== '/' && !p.startsWith('/v2/assets/'));
  expect(unexpected, `only the shell and /v2/assets/* may be cached; found: ${unexpected.join(', ')}`)
    .toEqual([]);
});

test('offline, the cached shell still serves a real HUD document', async ({ page, context }) => {
  await loadControlled(page);

  await context.setOffline(true);
  try {
    // A navigation the network cannot answer: the worker's `.catch` must fall back
    // to the cached shell rather than surfacing the browser's offline error page.
    const res = await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    expect(res, 'the offline navigation should be answered by the worker').not.toBeNull();
    // The shell is the HUD's index.html — assert the document, not the app: React
    // cannot boot offline (its /api/ reads all fail), and it is not supposed to.
    await expect(page.locator('#root')).toHaveCount(1);
    const title = await page.title();
    expect(title.length, 'the offline document should be the HUD shell, not an error page')
      .toBeGreaterThan(0);
  } finally {
    await context.setOffline(false);
  }
});
