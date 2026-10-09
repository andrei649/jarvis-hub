import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'turn-latency.spec.ts',
  workers: 1,
  outputDir: './e2e/.results/turn-latency',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:45163',
    headless: true,
    serviceWorkers: 'block',
  },
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py 45163`,
    url: 'http://127.0.0.1:45163/v2/',
    reuseExistingServer: false,
  },
});
