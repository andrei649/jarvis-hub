import { defineConfig, devices } from '@playwright/test';

// Local, read-only route smoke against the production bundle. API responses are
// intercepted in the spec; the isolated app renders the production shell.
export default defineConfig({
  testDir: './e2e',
  testMatch: 'routing.spec.ts',
  workers: 1,
  outputDir: '/tmp/nerva-h129-browser-results',
  use: { baseURL: 'http://127.0.0.1:45129', headless: true, serviceWorkers: 'block' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py 45129`,
    url: 'http://127.0.0.1:45129/v2/',
    reuseExistingServer: false,
  },
});
