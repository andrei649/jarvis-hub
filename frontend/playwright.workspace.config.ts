/* Nerva Workspace · the end-to-end lane against the REAL hub (spec §1 definition of done 3).

   Three servers, all on loopback, all started fresh for every run:
     1. tests/support/fake_openai_server.py through e2e/support/workspace_model.py — a
        deterministic OpenAI-compatible model server (the hub's lm-studio backend points at it),
        streaming word-sized tokens 20 ms apart. The launcher lets the journey stop it and start
        it again on the same port (<run>/model.down and <run>/model.state), to prove that a model
        server which goes away is explained honestly and recovered from;
     2. the SMTP sink (tests/support/smtp_sink.py) through e2e/support/workspace_smtp.py — a real
        SMTP conversation; every accepted message is one JSON line in <run>/mail.jsonl, which the
        journey reads to prove delivery. The launcher also lets the journey stop the sink and start
        it again on the same port (the files <run>/smtp.down and <run>/smtp.state), to prove that
        an approved email which cannot reach the mail server fails honestly, and hold its greeting
        (<run>/smtp.hold, <run>/smtp.hold.state), to prove a run page shows its email's outcome
        live while the delivery is still under way;
     3. the hub itself (serve.py) through e2e/support/workspace_hub.py, which builds a hermetic
        environment: a fresh JARVIS_HOME and key folder under the run directory, the workspace
        on with a fixed setup code, no cloud keys and no .env (see that file).

   The run directory is created once, here, in the runner process, and handed to the workers
   through the environment (they inherit it, so the config's second evaluation in a worker sees
   it set and does not make another). It holds home/, keys/, docs/, mail.jsonl, the switches'
   control and state files, and hub.log, and is kept after the run for a post-mortem; run
   directories older than 12 hours are removed when the next run starts.

   Browser: the pre-installed Chromium only (PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers); this
   lane never downloads one. Screenshots of every main page land in
   e2e/.results/workspace-screens/ (gitignored with the rest of e2e/.results/), or under
   WS_E2E_RESULTS_DIR when that is set.

   Run: `npx playwright test -c playwright.workspace.config.ts` from frontend/. */
import { mkdtempSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const MODEL_PORT = Number(process.env.WS_E2E_MODEL_PORT || 18491);
const SMTP_PORT = Number(process.env.WS_E2E_SMTP_PORT || 18492);
const HUB_PORT = Number(process.env.WS_E2E_HUB_PORT || 18493);
const BASE = `http://127.0.0.1:${HUB_PORT}`;
const PY = process.env.E2E_PYTHON || (process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python');

const RUN_PREFIX = 'nerva-ws-e2e-';
const KEEP_RUNS_MS = 12 * 60 * 60 * 1000;

function pruneOldRuns(): void {
  for (const name of readdirSync(tmpdir())) {
    if (!name.startsWith(RUN_PREFIX)) continue;
    const dir = path.join(tmpdir(), name);
    try {
      if (Date.now() - statSync(dir).mtimeMs > KEEP_RUNS_MS) rmSync(dir, { recursive: true, force: true });
    } catch {
      // Gone already, or not ours to remove: either way nothing to do.
    }
  }
}

if (!process.env.WS_E2E_RUN_DIR) {
  pruneOldRuns();
  process.env.WS_E2E_RUN_DIR = mkdtempSync(path.join(tmpdir(), RUN_PREFIX));
}
const RUN_DIR = process.env.WS_E2E_RUN_DIR;
process.env.WS_E2E_SETUP_CODE ||= 'e2e-setup-code-7Qm2Lx9Vt4';
// Read by the spec (mail sink address, hub URL) and by the hub launcher (ports, setup code).
Object.assign(process.env, {
  WS_E2E_MODEL_PORT: String(MODEL_PORT),
  WS_E2E_SMTP_PORT: String(SMTP_PORT),
  WS_E2E_HUB_PORT: String(HUB_PORT),
  WS_E2E_BASE_URL: BASE,
});

export default defineConfig({
  testDir: './e2e',
  testMatch: /workspace.*\.spec\.ts$/,
  // WS_E2E_RESULTS_DIR keeps a run's traces and screenshots apart from the shared e2e/.results/.
  outputDir: process.env.WS_E2E_RESULTS_DIR ? path.join(process.env.WS_E2E_RESULTS_DIR, 'workspace') : './e2e/.results/workspace',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    // A stuck click or fill fails in seconds with its own message, instead of silently using up
    // the whole 120 s test budget (test-depth T1).
    actionTimeout: 15_000,
    baseURL: BASE,
    viewport: { width: 1280, height: 800 },
    headless: true,
    locale: 'ro-RO',
    timezoneId: 'Europe/Bucharest',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'workspace-chromium' }],
  webServer: [
    {
      name: 'model',
      command: `${PY} frontend/e2e/support/workspace_model.py --port ${MODEL_PORT} --token-delay 0.02 --run-dir "${RUN_DIR}"`,
      cwd: '..',
      url: `http://127.0.0.1:${MODEL_PORT}/health`,
      wait: { stdout: /READY/ },
      reuseExistingServer: false,
      timeout: 30_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    },
    {
      name: 'smtp',
      command: `${PY} frontend/e2e/support/workspace_smtp.py --port ${SMTP_PORT} --out "${path.join(RUN_DIR, 'mail.jsonl')}" --run-dir "${RUN_DIR}"`,
      cwd: '..',
      wait: { stdout: /READY 127\.0\.0\.1:\d+/ },
      reuseExistingServer: false,
      timeout: 30_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    },
    {
      name: 'hub',
      command: `${PY} frontend/e2e/support/workspace_hub.py`,
      cwd: '..',
      url: `${BASE}/readyz`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
      gracefulShutdown: { signal: 'SIGTERM', timeout: 20_000 },
    },
  ],
});
