import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir:'./e2e',testMatch:'appearance-fonts.spec.ts',workers:1,
  outputDir:'/tmp/nerva-font-browser-results',
  use:{baseURL:'http://127.0.0.1:45136',headless:true,serviceWorkers:'block',extraHTTPHeaders:{'X-User-Token':'h130-isolated-test-token'}},
  projects:[{name:'desktop',use:{...devices['Desktop Chrome']}}],
  webServer:{command:`${process.env.NERVA_TEST_PYTHON || 'python'} ${process.env.NERVA_FONT_TEST_SERVER || 'e2e/support/base_path_server.py'} 45136`,url:'http://127.0.0.1:45136/v2/',timeout:60000,reuseExistingServer:false},
});
