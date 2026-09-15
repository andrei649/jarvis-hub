import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir:'./e2e', testMatch:'appearance.spec.ts', workers:1,
  outputDir:'/tmp/nerva-h135-browser-results',
  use:{baseURL:'http://127.0.0.1:45135',headless:true,serviceWorkers:'block',extraHTTPHeaders:{'X-User-Token':'h130-isolated-test-token'}},
  projects:[
    {name:'desktop',use:{...devices['Desktop Chrome'],viewport:{width:1440,height:900}}},
    {name:'mobile',use:{...devices['Pixel 7']}},
  ],
  webServer:{command:`${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py 45135`,url:'http://127.0.0.1:45135/v2/',timeout:60000,reuseExistingServer:false},
});
