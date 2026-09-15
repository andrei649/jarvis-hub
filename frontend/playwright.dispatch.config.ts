import {defineConfig, devices} from '@playwright/test';
export default defineConfig({
  testDir:'./dispatch-e2e', testMatch:'dispatch.spec.ts', workers:1,
  outputDir:'/tmp/nerva-dispatch-browser-results',
  use:{baseURL:'http://127.0.0.1:45149',serviceWorkers:'block',...devices['Desktop Chrome']},
  webServer:{command:`${process.env.NERVA_TEST_PYTHON || 'python'} dispatch-e2e/server.py`,
    url:'http://127.0.0.1:45149/v2/',reuseExistingServer:false,timeout:60000},
});
