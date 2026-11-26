/* Manual focused lane: build the bundled HUD first, then run
   npx playwright test -c playwright.subagents-live.config.ts.
   Set NERVA_FINISH_PARALLEL_MODEL to an installed physical Ollama model for the real lane. */
import { defineConfig, devices } from '@playwright/test';

const port = 45178;
const baseURL = `http://127.0.0.1:${port}`;
const real = Boolean(process.env.NERVA_FINISH_PARALLEL_MODEL);

export default defineConfig({
  testDir: './e2e',
  testMatch: 'subagents-live.journey.ts',
  workers: 1,
  retries: 0,
  timeout: real ? 300_000 : 45_000,
  expect: { timeout: real ? 60_000 : 15_000 },
  reporter: [['list']],
  outputDir: 'e2e/.results/subagents-live',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    headless: true,
    launchOptions: {
      ...(process.env.NERVA_TEST_BROWSER ? { executablePath: process.env.NERVA_TEST_BROWSER } : {}),
      ...(real ? { args: ['--disable-background-networking', '--no-proxy-server',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1'] } : {}),
    },
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
