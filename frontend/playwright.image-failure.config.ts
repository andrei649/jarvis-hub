import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'image-failure-state.spec.ts',
  workers: 1,
  outputDir: './e2e/.results/image-failure',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:45161',
    headless: true,
    serviceWorkers: 'block',
  },
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py 45161`,
    url: 'http://127.0.0.1:45161/v2/',
    reuseExistingServer: false,
  },
});
