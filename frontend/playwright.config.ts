/* HUD v2 · Playwright E2E (H23.17 quality gate). Boots the REAL FastAPI backend
   (serve.py) on a loopback test port and drives the served /v2 bundle in a real
   Chromium by default, with an opt-in browser matrix for the scheduled soak —
   the one thing jsdom/vitest can't do: prove the canvas Neural Mesh actually
   paints pixels and the HUD mounts without an uncaught exception.

   Browser: uses the environment's pre-installed Chromium (PLAYWRIGHT_BROWSERS_PATH
   = /opt/pw-browsers, chromium-1194 matches @playwright/test 1.56.1) — never
   downloads. Opt-in lane: `npm run e2e` (not part of the default `npm test`). */
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT || 8123);
const BASE = `http://127.0.0.1:${PORT}`;
// local dev runs the repo venv; CI installs into the system python → override with E2E_PYTHON
const DEFAULT_PY = process.platform === 'win32'
  ? '.venv\\Scripts\\python.exe'
  : '.venv/bin/python';
const PY = process.env.E2E_PYTHON || DEFAULT_PY;
const ENV_PREFIX = process.platform === 'win32'
  ? `set JARVIS_PORT=${PORT}&& set JARVIS_LOG_LEVEL=warning&& `
  : `JARVIS_PORT=${PORT} JARVIS_LOG_LEVEL=warning `;
const BROWSER_MATRIX = process.env.E2E_BROWSER_MATRIX === '1';
const SOAK_ITERATIONS = Math.max(1, Number(process.env.E2E_SOAK_ITERATIONS || 1));

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.results',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  repeatEach: SOAK_ITERATIONS,
  reporter: [['list']],
  use: {
    baseURL: BASE,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    /* index.html registers `/sw-v2.js` at scope '/', so every page in this lane is a
       service-worker-controlled client by the time `#root` is non-empty (measured). On
       webkit that made `page.route` never fire, so the three specs that mock the chat
       stream drove the real model-less backend instead of the mock — and persisted their
       user turns into the SHARED session, which a later page load rehydrated into a
       user-only transcript that failed an a11y scan several projects downstream. Ten of
       the 22 permanently-red nightly cases were those two symptoms.

       Measured across five browser-matrix runs, 32 or 96 cases each:
         baseline, n=1                7 failed
         this line, n=1               4 failed  (webkit routing + a11y fixed)
         scoped to those 3 specs, n=1 3 failed
         this line, n=3               9 failed  = 3 mobile-chrome specs x 3 iterations
         scoped, n=3                  9 failed  = identical
       The n=1 pair looked like a trade — a global block appeared to break the Neural Mesh
       canvas assertion on webkit. At n=3 it passes 3 of 3 and the two forms are
       indistinguishable, so that was a flake and the special-casing it justified is gone.

       What is NOT claimed: the precise WebKit path. "Playwright's interception is
       Chromium-only for service-worker-mediated requests" is the obvious explanation and
       it does not survive — firefox is also non-Chromium and passes 24 of 24, and this
       worker never mediates the request anyway (`sw-v2.js` returns early on
       `req.method !== 'GET'`; the chat stream is a POST). The worker is causally involved
       on WebKit specifically, by a mechanism this comment does not pretend to know.

       Cost, stated rather than hand-waved: the lane no longer registers the worker. That
       costs no assertion — `grep -rniE "serviceworker|caches|offline|manifest" frontend/e2e/`
       finds nothing, and the worker's fetch handler serves no request in any spec, because
       every spec navigates once and both its branches need a second navigation. If a real
       PWA spec is ever added it should opt back in with `test.use({ serviceWorkers: 'allow' })`. */
    serviceWorkers: 'block',
  },
  projects: BROWSER_MATRIX ? [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
  ] : [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Boot the real backend from the repo root; /status flips ready once the
  // orchestrator + agents are loaded. Loopback bind → assert_safe_bind allows it.
  webServer: {
    // run from the repo root (cwd) — serve.py + config.py resolve agents/_system/
    // agents.yaml relative to CWD, not to this config's frontend/ dir.
    command: `${ENV_PREFIX}${PY} serve.py`,
    cwd: '..',
    url: `${BASE}/status`,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
