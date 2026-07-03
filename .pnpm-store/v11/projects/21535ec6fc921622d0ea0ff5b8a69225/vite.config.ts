/// <reference types="vitest" />
import { defineConfig } from 'vite';
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
