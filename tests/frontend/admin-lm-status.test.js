// LMStudioStatusRow (admin.js): a read-only live status card backed by
// /api/llm/status. It fetches the controller state on mount and shows the
// kill-switch (enabled?), server online/offline, and active model — degrading
// honestly when the controller is unavailable or the fetch fails.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function backend(status, { ok = true } = {}) {
  const json = (b, o = true) => Promise.resolve({ json: async () => b, ok: o });
  return vi.fn((url) => {
    if (url === '/api/llm/status') return json(status, ok);
    return json({}); // AdminApp auto-mounts on load and makes other calls
  });
}

describe('LMStudioStatusRow', () => {
  let env;
  afterEach(() => env && env.cleanup());

  function mount(fetch) {
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], expose: ['LMStudioStatusRow'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    return env.render(h(env.hud.LMStudioStatusRow, { label: 'Stare LM Studio' }));
  }

  it('shows enabled + online + active model when the controller is healthy', async () => {
    const fetch = backend({ online: true, enabled: true, server_url: 'http://localhost:1234', active_model: 'google/gemma-4-12b' });
    const { container } = mount(fetch);
    await env.flush();
    expect(fetch).toHaveBeenCalledWith('/api/llm/status', expect.anything());
    const text = container.textContent;
    expect(text.toLowerCase()).toContain('control activ');
    expect(text.toLowerCase()).toContain('server online');
    expect(text).toContain('google/gemma-4-12b');
  });

  it('reflects offline / disabled / no-model state honestly', async () => {
    const fetch = backend({ online: false, enabled: false, server_url: 'http://localhost:1234', active_model: null });
    const { container } = mount(fetch);
    await env.flush();
    const text = container.textContent.toLowerCase();
    expect(text).toContain('control oprit');
    expect(text).toContain('server offline');
    expect(text).toContain('niciun model');
  });

  it('degrades to an "unavailable" note when the controller is not wired (503)', async () => {
    const fetch = backend({ error: 'not initialized' }, { ok: false });
    const { container } = mount(fetch);
    await env.flush();
    expect(container.textContent.toLowerCase()).toContain('indisponibil');
  });

  it('degrades to an "unavailable" note when the fetch fails', async () => {
    const fetch = vi.fn((url) => {
      if (url === '/api/llm/status') return Promise.reject(new Error('network'));
      return Promise.resolve({ json: async () => ({}), ok: true });
    });
    const { container } = mount(fetch);
    await env.flush();
    expect(container.textContent.toLowerCase()).toContain('indisponibil');
  });
});
