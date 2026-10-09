import { defineConfig, devices } from '@playwright/test';

// Served production bundle without the app lifespan or live providers.
export default defineConfig({
  testDir: './e2e',
  testMatch: 'task-mediation.spec.ts',
  workers: 1,
  outputDir: './e2e/.results/task-mediation',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:45159',
    headless: true,
    serviceWorkers: 'block',
  },
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py 45159`,
    url: 'http://127.0.0.1:45159/v2/',
    reuseExistingServer: false,
  },
});
