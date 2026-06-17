// ModelPickerRow (admin.js, kind "model-select"): a live local-model picker
// backed by /api/models/local + /api/models/local/switch. It fetches the
// catalog on mount and switches the active model on pick (independent of the
// dirty/Save flow), degrading honestly when no backend is up.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function backend(models, active) {
  const json = (b) => Promise.resolve({ json: async () => b, ok: true });
  return vi.fn((url, opts) => {
    if (url === '/api/models/local') {
      return json({ models: models.map((id) => ({ id })), active });
    }
    if (url === '/api/models/local/switch') {
      return json({ ok: true, active: JSON.parse(opts.body).model });
    }
    return json({}); // AdminApp auto-mounts on load and makes other calls
  });
}

describe('ModelPickerRow', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('lists the live local models and switches the active one on pick', async () => {
    const fetch = backend(['gemma-12b', 'qwen-7b'], 'gemma-12b');
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], expose: ['ModelPickerRow'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const { container } = env.render(h(env.hud.ModelPickerRow, { label: 'Default local model', value: 'gemma-12b' }));
    await env.flush();

    const select = container.querySelector('select');
    expect(select).not.toBeNull();
    expect([...select.querySelectorAll('option')].map((o) => o.value)).toEqual(['gemma-12b', 'qwen-7b']);

    env.selectOption(select, 'qwen-7b');
    await env.flush();
    expect(fetch).toHaveBeenCalledWith('/api/models/local/switch', expect.objectContaining({ method: 'POST' }));
    expect(container.textContent.toLowerCase()).toContain('qwen-7b');
  });

  it('keeps the persisted model selectable even if it is not in the live catalog', async () => {
    // No active reported by the backend → the picker keeps the persisted value.
    const fetch = backend(['qwen-7b'], null);
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], expose: ['ModelPickerRow'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const { container } = env.render(h(env.hud.ModelPickerRow, { label: 'Default local model', value: 'google/gemma-4-12b' }));
    await env.flush();
    // active stays the live one (qwen-7b), but the persisted value is still an option.
    const values = [...container.querySelectorAll('option')].map((o) => o.value);
    expect(values).toContain('google/gemma-4-12b');
    expect(values).toContain('qwen-7b');
  });

  it('degrades honestly to text + a note when no local backend is up', async () => {
    const fetch = backend([], null);
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], expose: ['ModelPickerRow'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const { container } = env.render(h(env.hud.ModelPickerRow, { label: 'Default local model', value: 'google/gemma-4-12b' }));
    await env.flush();
    expect(container.querySelector('select')).toBeNull();
    expect(container.textContent).toContain('google/gemma-4-12b');
    expect(container.textContent.toLowerCase()).toContain('niciun model');
  });
});
