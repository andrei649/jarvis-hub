/* Manual focused lane: build the bundled HUD first, then run
   npx playwright test -c playwright.subagents-live.config.ts.
   Production app routes and manager run on loopback with synthetic children only. */
import { defineConfig, devices } from '@playwright/test';

const port = 45178;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'subagents-live.journey.ts',
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: 'e2e/.results/subagents-live',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    headless: true,
    serviceWorkers: 'block',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'subagents-live' }],
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/subagents_live_server.py ${port}`,
    url: `${baseURL}/v2/`,
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
