// Full-app smoke test: app.js mounts the entire HUD into #root on load. This
// is the integration-level guard — it would have caught the systems.js parse
// error that broke the Systems panel. We load every static file (mirroring
// index.html) with a stubbed backend and assert the app boots and hydrates.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

const ALL_FILES = [
  'i18n', 'data', 'components', 'network', 'enhancements',
  'cognition', 'systems', 'workflows', 'observability', 'dossier-modal', 'app',
];

function backendStub() {
  const json = (body) => Promise.resolve({ json: async () => body, ok: true });
  return vi.fn((url) => {
    if (url === '/api/agents') {
      return json({ agents: [
        { id: 'jarvis', name: 'Jarvis', status: 'active', enabled: true, model: 'm' },
        { id: 'gecko', name: 'Gecko', status: 'idle', enabled: true, model: 'm' },
      ] });
    }
    if (url.startsWith('/status')) return json({ lm_online: true, sys: { host: 'bonobo' }, agents: [] });
    if (url.startsWith('/dashboard')) return json({ weather: null, calendar: [], notifications: [] });
    if (url.startsWith('/tasks')) return json({ tasks: [] });
    if (url.startsWith('/ticker')) return json({ ticker: [] });
    return json({});
  });
}

describe('App (full mount)', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('boots into #root and hydrates the agent roster from the backend', async () => {
    env = loadHud({ files: ALL_FILES, fetch: backendStub(), lang: 'ro' });
    const root = env.document.getElementById('root');

    // createRoot().render() is async; let it mount and loadJarvisData() resolve.
    await env.flush();

    // The app booted and the top bar / live agent data are present.
    expect(root.childElementCount).toBeGreaterThan(0);
    expect(root.textContent).toContain('JARVIS');
    expect(env.window.fetch).toHaveBeenCalledWith('/api/agents');
  });

  it('does not crash when the backend is unreachable (apiDown fallback)', async () => {
    env = loadHud({
      files: ALL_FILES,
      fetch: vi.fn(() => Promise.reject(new Error('offline'))),
      lang: 'ro',
    });
    await env.flush();
    const root = env.document.getElementById('root');
    // Falls back to agent metadata rather than rendering an empty root.
    expect(root.childElementCount).toBeGreaterThan(0);
  });
});
