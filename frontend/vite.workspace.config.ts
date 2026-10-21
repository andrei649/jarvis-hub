// Nerva Workspace — the B2B pilot web app (docs/business/WORKSPACE_PILOT_SPEC.md §10).
// A second, independent bundle next to the HUD: its own HTML entry, no public dir, built into
// ../agents/web/workspace and served by FastAPI under /workspace. Relative asset URLs (`base:
// './'`) let the server rewrite `./assets/X` to the deployment's root path at request time.
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const API = 'http://127.0.0.1:8080';

/** Dev only: serve the SPA shell for every /workspace page path so deep links and reloads
    work under `npm run dev:workspace` exactly as they do behind FastAPI. Asset and module
    requests (anything with a file extension or a Vite-internal prefix) pass through. */
function workspaceHistoryFallback(): Plugin {
  return {
    name: 'nerva-workspace-history-fallback',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const path = (req.url || '').split('?')[0];
        if (path === '/' || path === '/workspace' || (path.startsWith('/workspace/') && !/\.[a-z0-9]+$/i.test(path))) {
          req.url = '/workspace.html';
        }
        next();
      });
    },
  };
}

export default defineConfig({
  base: './',
  publicDir: false,
  plugins: [react(), workspaceHistoryFallback()],
  build: {
    outDir: fileURLToPath(new URL('../agents/web/workspace', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: { input: 'workspace.html' },
  },
  server: {
    port: 5174,
    proxy: { '/api/workspace': { target: API, changeOrigin: false } },
  },
});
