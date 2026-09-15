import { defineConfig, devices } from '@playwright/test';

// Local, read-only route smoke against the production bundle. API responses are
// intercepted in the spec; no running backend, credentials or model is needed.
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
    command: 'node_modules/.bin/vite preview --host 127.0.0.1 --port 45129 --strictPort',
    url: 'http://127.0.0.1:45129/v2/',
    reuseExistingServer: false,
  },
});
