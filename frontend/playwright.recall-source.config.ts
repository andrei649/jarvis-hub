/* Opt-in real recall/source lane. Run from frontend/ with an installed local
   Ollama model: NERVA_MEMORY_MODEL=<model> npx playwright test -c playwright.recall-source.config.ts
   The fixture creates a fresh synthetic home and HTTPS 127.0.0.2 listener; it
   never reuses a running hub. NERVA_TEST_BROWSER may name an installed Chrome. */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const repo = path.resolve(process.cwd(), '..');
const helper = path.join(repo, 'frontend', 'e2e', 'support', 'recall_source_hub.py');
const python = process.env.E2E_PYTHON || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(path.join(repo, 'serve.py')) || !existsSync(helper)) throw new Error('Run from frontend/ in the Nerva checkout');
if (!process.env.NERVA_MEMORY_MODEL) throw new Error('Set NERVA_MEMORY_MODEL to an installed local Ollama model');
if (!existsSync(python)) throw new Error('Set E2E_PYTHON to the existing Python environment with locked dependencies');

// A caller's stale fixture is never reused. Only Playwright's worker inherits
// the fresh run directory prepared by its own runner process.
if (process.env.TEST_WORKER_INDEX === undefined) {
  process.env.NERVA_RECALL_RUN_DIR = execFileSync(python, [helper, '--prepare'], {
    cwd: repo, env: process.env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}
const run = process.env.NERVA_RECALL_RUN_DIR;
if (!run) throw new Error('Recall-source worker did not inherit the prepared fixture');
const fixture = JSON.parse(readFileSync(path.join(run, 'fixture.json'), 'utf8')) as {
  port: number; url: string; model: string; token: string; marker: string;
};
if (fixture.url !== `https://127.0.0.2:${fixture.port}` || fixture.port <= 1024 || fixture.port === 8080
  || fixture.model !== process.env.NERVA_MEMORY_MODEL) throw new Error('Invalid recall-source fixture');
Object.assign(process.env, {
  NERVA_MEMORY_ADMIN_TOKEN: fixture.token,
  NERVA_MEMORY_VAULT_MARKER: fixture.marker,
  NERVA_RUN_RECALL_SOURCE_ACCEPTANCE: '1',
});

const browser = process.env.NERVA_TEST_BROWSER;
if (browser && !existsSync(browser)) throw new Error('NERVA_TEST_BROWSER does not exist');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'recall-saved-source.spec.ts',
  outputDir: path.join(run, 'test-results'),
  timeout: 420_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: fixture.url,
    headless: true,
    ignoreHTTPSErrors: true, // this fixture's ephemeral self-signed loopback cert only
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 960 },
    launchOptions: {
      ...(browser ? { executablePath: browser } : {}),
      args: ['--disable-background-networking', '--no-proxy-server',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1, EXCLUDE 127.0.0.2'],
    },
  },
  webServer: {
    command: `"${python}" "${helper}" --serve`,
    cwd: repo,
    env: { NERVA_RECALL_RUN_DIR: run },
    wait: { stdout: /READY recall-source loopback/ },
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  },
});
