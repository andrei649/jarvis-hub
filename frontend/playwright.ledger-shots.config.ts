/* Phase B render harness (PHASE_B_PLAN.md §9.5): a manual lane, never part of `npm run e2e`.

     npx playwright test -c playwright.ledger-shots.config.ts

   Server: the fixture hub e2e/support/base_path_server.py (an isolated JARVIS_HOME, fixture
   answers to every write, no owner data), serving the built bundle — so build first. To shoot a
   running Vite dev server instead (with ?demo=1 for content), set NERVA_SHOTS_URL, e.g.
   NERVA_SHOTS_URL=http://127.0.0.1:5173; no server is started then.

   Output: e2e/artifacts/ledger/<page>-<w>-<look>-<scheme>.png and report.json (gitignored).
   The spec sets the viewport (2560×1353 at 1.5×, 1920×1080, 1280×800) per group. */
import { defineConfig, devices } from '@playwright/test';

const external = process.env.NERVA_SHOTS_URL;
// One id for the whole run, set here (the runner's process) and inherited by every worker: a worker
// that Playwright restarts after a failed shot keeps writing to the same run, so report.json gathers
// every shot of the run instead of the last worker's alone (e2e/ledger-shots.spec.ts).
process.env.NERVA_SHOTS_RUN ||= new Date().toISOString().replace(/[:.]/g, '-');

export default defineConfig({
  testDir: './e2e',
  testMatch: ['ledger-shots.spec.ts'],
  workers: 1,
  fullyParallel: false,
  timeout: 120_000,
  reporter: [['list']],
  outputDir: 'e2e/.results/ledger-shots',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: external || 'http://127.0.0.1:45130',
    headless: true,
    reducedMotion: 'reduce',
    serviceWorkers: 'block',
    extraHTTPHeaders: { 'X-User-Token': 'h130-isolated-test-token' },
  },
  // The spec runs only under this project name: `npm run e2e` (playwright.config.ts) skips it.
  projects: [{ name: 'ledger-shots' }],
  webServer: external ? undefined : {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py`,
    url: 'http://127.0.0.1:45130/v2/',
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
