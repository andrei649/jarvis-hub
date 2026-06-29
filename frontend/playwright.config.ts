/* HUD v2 · Playwright E2E (H23.17 quality gate). Boots the REAL FastAPI backend
   (serve.py) on a loopback test port and drives the served /v2 bundle in a real
   Chromium — the one thing jsdom/vitest can't do: prove the canvas Neural Mesh
   actually paints pixels and the HUD mounts without an uncaught exception.

   Browser: uses the environment's pre-installed Chromium (PLAYWRIGHT_BROWSERS_PATH
   = /opt/pw-browsers, chromium-1194 matches @playwright/test 1.56.1) — never
   downloads. Opt-in lane: `npm run e2e` (not part of the default `npm test`). */
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT || 8123);
const BASE = `http://127.0.0.1:${PORT}`;
// local dev runs the repo venv; CI installs into the system python → override with E2E_PYTHON
const PY = process.env.E2E_PYTHON || '.venv/bin/python';

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.results',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: BASE,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Boot the real backend from the repo root; /status flips ready once the
  // orchestrator + agents are loaded. Loopback bind → assert_safe_bind allows it.
  webServer: {
    // run from the repo root (cwd) — serve.py + config.py resolve agents/_system/
    // agents.yaml relative to CWD, not to this config's frontend/ dir.
    command: `JARVIS_PORT=${PORT} JARVIS_LOG_LEVEL=warning ${PY} serve.py`,
    cwd: '..',
    url: `${BASE}/status`,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
