import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', testMatch: ['base-path.spec.ts', 'pwa.spec.ts'], workers: 1,
  outputDir: '/tmp/nerva-h130-browser-results',
  use: {baseURL:'http://127.0.0.1:45130', headless:true, serviceWorkers:'allow', extraHTTPHeaders:{'X-User-Token':'h130-isolated-test-token'}},
  projects: [
    {name:'desktop', use:{...devices['Desktop Chrome'], viewport:{width:1440,height:900}}},
    {name:'mobile', use:{...devices['Pixel 7']}},
  ],
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py`,
    url:'http://127.0.0.1:45130/v2/', timeout:60000, reuseExistingServer:false,
  },
});
