/* The Home registers lane (PHASE_B_PLAN.md §5.1, §5.3, §5.4): a manual lane, never part of
   `npm run e2e`.

     npx playwright test -c playwright.home-registers.config.ts

   Server: the fixture hub e2e/support/base_path_server.py (an isolated JARVIS_HOME, fixture answers
   to every write, no owner data, no model), serving the built bundle — so build first. It listens on
   45166 and keeps its app on the port after it, apart from the render matrix (45130) and the other
   fixture lanes. The specs stub what they need with page.route (the hub's roster, the chat stream),
   so nothing reaches a model.

   Specs: e2e/talk-recipient.spec.ts (the conversation's recipient, end to end, through a held
   streaming reply) and e2e/home-registers.spec.ts (the register heads at every width, the held
   question's layout, and the docket's rows in every look, measured). Both run only under this
   project name: the main lane (playwright.config.ts) ignores them and they skip themselves
   anywhere else. */
import { defineConfig, devices } from '@playwright/test';

const PORT = 45166;
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  testMatch: ['talk-recipient.spec.ts', 'home-registers.spec.ts'],
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: 'e2e/.results/home-registers',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: BASE,
    headless: true,
    serviceWorkers: 'block',
    screenshot: 'only-on-failure',
    extraHTTPHeaders: { 'X-User-Token': 'h130-isolated-test-token' },
  },
  // The specs run only under this project name (test.skip elsewhere).
  projects: [{ name: 'home-registers' }],
  webServer: {
    command: `${process.env.NERVA_TEST_PYTHON || 'python'} e2e/support/base_path_server.py ${PORT}`,
    url: `${BASE}/v2/`,
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
