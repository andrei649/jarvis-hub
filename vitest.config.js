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
    // Coverage is NOT handled by vitest here: the HUD scripts run inside JSDOM,
    // out of reach of vitest's v8/istanbul providers. Instead the harness
    // instruments the static files with istanbul (HUD_COVERAGE=1) and
    // `npm run test:coverage` (tests/frontend/coverage.mjs) aggregates the
    // dumps with nyc. See tests/frontend/README.md.
  },
});
