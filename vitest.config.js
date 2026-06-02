import { defineConfig } from 'vitest/config';

// The HUD ships as plain <script> globals (vendored React 18 UMD + the static
// files in agents/web/static). We boot our own JSDOM per test in the harness
// (high fidelity — the real artifacts run, not a re-bundled copy), so the
// runner environment itself is just node.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/frontend/**/*.test.js'],
    globals: false,
    coverage: {
      provider: 'v8',
      reportsDirectory: 'tests/frontend/.coverage',
      reporter: ['text-summary', 'html'],
      // Note: scripts executed inside JSDOM run in a separate realm, so v8
      // coverage reflects the harness/specs rather than the in-page scripts.
      // Fidelity (running the shipped artifacts) is the priority for now;
      // instrumented coverage of the static files is a follow-up.
    },
  },
});
