import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', testMatch: 'media-gallery.spec.ts', workers: 1,
  outputDir: '/tmp/nerva-h518-browser-results',
  use: { baseURL: 'http://127.0.0.1:45138', headless: true, serviceWorkers: 'block' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: { command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/gallery_server.py`,
    url: 'http://127.0.0.1:45138/v2/', timeout: 60000, reuseExistingServer: false },
});
