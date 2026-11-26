import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.E2E_PORT || 47451);
if (!Number.isInteger(port) || port < 1024 || port > 65535 || port === 8080) {
  throw new Error('ChatGPT plan E2E requires a disposable high port other than 8080');
}
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'chatgpt-plan.spec.ts',
  workers: 1,
  reporter: 'list',
  outputDir: './e2e/.results/chatgpt-plan',
  use: { baseURL, headless: true, serviceWorkers: 'block' },
  projects: [{ name: 'chatgpt-plan', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } }],
  webServer: {
    command: `${process.env.E2E_PYTHON || 'python3'} e2e/support/chatgpt_plan_hub.py ${port}`,
    url: `${baseURL}/_test/state`, timeout: 60000, reuseExistingServer: false,
  },
});
