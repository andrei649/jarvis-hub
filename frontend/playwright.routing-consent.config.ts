/* Manual owner-machine proof of two real Ledger turns through the native hub.
   The fixture launches only loopback model responders under a scratch profile. */
import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.ROUTE_PROOF_HUB_PORT || 46791);
const baseURL = `http://127.0.0.1:${port}`;
const python = process.env.E2E_PYTHON || (process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'routing-consent.spec.ts',
  outputDir: process.env.ROUTE_PROOF_RESULTS_DIR || 'e2e/.results/routing-consent',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    headless: true,
    serviceWorkers: 'block',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    // The owner's key may be used only by an owner chat turn. A user-tier
    // browser would be correctly refused by credential_scope before dispatch.
    extraHTTPHeaders: { 'X-User-Token': 'route-proof-user', 'X-Admin-Token': 'route-proof-admin' },
  },
  projects: [{ name: 'routing-consent' }],
  webServer: {
    command: `${python} frontend/e2e/support/routing_consent_hub.py ${port}`,
    cwd: '..',
    url: `${baseURL}/readyz`,
    timeout: 120_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 20_000 },
    env: {
      PYTHON_DOTENV_DISABLED: '1',
      HTTP_PROXY: 'http://127.0.0.1:9', HTTPS_PROXY: 'http://127.0.0.1:9',
      ALL_PROXY: 'http://127.0.0.1:9', NO_PROXY: '127.0.0.1,localhost',
    },
  },
});
