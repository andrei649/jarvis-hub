import { defineConfig } from 'vitest/config';

// CI's existing `npm test` runs both HUD and real native React source tests.
// Production Vite configuration and the shipped browser bundle are unchanged.
export default defineConfig({
  test: {
    maxWorkers: 1,
    projects: ['./vite.config.ts', './vitest.native.config.ts'],
  },
});
