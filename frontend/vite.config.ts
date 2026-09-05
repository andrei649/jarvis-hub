// `defineConfig` comes from `vitest/config`, not `vite`: the `test` key below is Vitest's, and
// Vite's own `UserConfig` does not have it. This file previously carried
// `/// <reference types="vitest" />` for that, which stopped working when Vitest moved the
// augmentation to its `vitest/config` entrypoint (this repo is on vitest 4.1.11) — and nothing
// noticed, because no tsconfig `include` covered this file, so `tsc` never compiled it. Adding it
// to tsconfig.e2e.json surfaces the error it had been carrying, reported against the `test:` key
// below:
//   error TS2769 ... 'test' does not exist in type 'UserConfigExport'
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// HUD v2 is served by FastAPI at /v2; the built bundle is committed to
// ../agents/web/v2 so the Python runtime needs no Node (local-first).
const API = 'http://127.0.0.1:8080';
const PROXY = [
  '/api', '/chat', '/status', '/agents', '/dashboard', '/ticker', '/tasks',
  '/memory', '/autonomy', '/heartbeat', '/learning', '/skills', '/plugins',
  '/sandbox', '/security', '/bench', '/sessions', '/tts', '/.well-known',
];

export default defineConfig({
  base: '/v2/',
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL('../agents/web/v2', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    // dev: run `npm run dev` (5173) beside `python serve.py` (8080); fetches proxy to the real API
    proxy: Object.fromEntries(PROXY.map((p) => [p, { target: API, changeOrigin: true }])),
  },
  // Smoke tests for the newly-wired interactive controls — jsdom + mocked fetch.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
