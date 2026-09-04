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
// e2e.yml now exposes this as a dispatch input, so pin what a non-integer means here
// instead of leaving it to coercion. `Math.max(1, Number(x))` returns NaN for an
// unparseable x and passes it straight to `repeatEach`; measured on @playwright/test
// 1.62.1, `repeatEach: NaN` behaves as 1, so this is not a bug being fixed — it is
// undocumented behaviour being made explicit. It does change one case: a fractional
// value floors (2.7 -> 2) rather than reaching `repeatEach` as 2.7.
const SOAK_ITERATIONS = (() => {
  const n = Number(process.env.E2E_SOAK_ITERATIONS);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
})();

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
