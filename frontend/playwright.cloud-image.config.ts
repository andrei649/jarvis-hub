import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
  testDir:'./cloud-image-browser',testMatch:'*.spec.ts',workers:1,
  outputDir:'/tmp/nerva-cloud-hud-browser-results',
  use:{baseURL:'http://127.0.0.1:45152',headless:true,serviceWorkers:'block'},
  projects:[{name:'desktop',use:{...devices['Desktop Chrome'],viewport:{width:1280,height:900}}},{name:'phone',use:{...devices['Pixel 7']}}],
  webServer:{command:`${process.env.NERVA_TEST_PYTHON || 'python3'} cloud-image-browser/server.py 45152 /tmp/nerva-cloud-hud-assets`,url:'http://127.0.0.1:45152/nerva/_test/state',timeout:60000,reuseExistingServer:false},
});
