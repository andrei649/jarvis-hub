// admin.js is the standalone /admin app. It auto-mounts AdminApp into #root on
// load. We mount it against a permissive backend stub, sweep every nav page to
// exercise the sub-pages, and assert key flows (settings dirty→save). A few
// prop-driven chart/card components are also tested directly.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function adminBackend() {
  const json = (body) => Promise.resolve({ json: async () => body, ok: true });
  return vi.fn((url, opts) => {
    if (url === '/api/admin/settings') {
      return json({ general: [
        { key: 'dev_mode', label: 'Dev mode', kind: 'toggle', value: false },
        { key: 'log_level', label: 'Log level', kind: 'select', value: 'info', opts: ['info', 'debug'] },
      ] });
    }
    if (url.startsWith('/api/admin/settings/')) return json({ updated: 1 });
    if (url === '/api/admin/env') return json({ Node: 'v22', Platform: 'linux' });
    if (url === '/api/admin/stats') {
      return json({
        overview: { total_runs: 10, total_tokens: 1000, success_rate: 0.9, avg_latency: 1.2 },
        agents: [{ name: 'gecko', success_rate: 0.9, p95_latency: 2, runs: 5 }],
        daily: [{ date: '2026-06-01', total: 3 }, { date: '2026-06-02', total: 7 }],
      });
    }
    if (url === '/api/analytics/cost') return json({ total: 1.23, by_agent: {} });
    if (url === '/api/analytics/model-tiers') return json({ tiers: {} });
    if (url === '/api/agents') return json({ agents: [{ id: 'gecko', name: 'Gecko', tier: 'FND', role: 'Markets', status: 'idle', model: 'm' }] });
    if (url.startsWith('/api/admin/audit')) return json({ rows: [] });
    if (url === '/api/admin/mcp') return json({ servers: [] });
    if (url === '/api/oracle/status') return json({ connected: false });
    if (url === '/api/oracle/conflicts') return json({ conflicts: [] });
    if (url === '/api/memory/profile') return json({});
    if (url.startsWith('/api/memory/recall')) return json({ results: [] });
    return json({});
  });
}

describe('AdminApp (full mount + nav sweep)', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('mounts the admin shell with a nav entry per category', async () => {
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], fetch: adminBackend(), lang: 'ro' });
    await env.flush();
    const root = env.document.getElementById('root');
    expect(root.querySelector('.admin-wrap')).not.toBeNull();
    expect(root.querySelectorAll('.admin-nav button').length).toBeGreaterThanOrEqual(8);
    // admin.js now routes every call through afetch(), which attaches an
    // X-Admin-Token header (#128), so the bare-URL assertion no longer matches.
    expect(env.window.fetch).toHaveBeenCalledWith(
      '/api/admin/settings',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-Admin-Token': expect.anything() }) }),
    );
  });

  it('navigates through every page without crashing', async () => {
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], fetch: adminBackend(), lang: 'ro' });
    await env.flush();
    const root = env.document.getElementById('root');
    const labels = ['Configurări Globale', 'Management Agenți', 'Memorie Utilizator', 'Cost & Modele', 'Servere MCP', 'Integrare Claude', 'Sistem & Depanare', 'Statistici & Analize'];
    for (const label of labels) {
      const btn = [...root.querySelectorAll('.admin-nav button')].find((b) => b.textContent.includes(label));
      expect(btn, `nav button for ${label}`).toBeTruthy();
      env.click(btn);
      await env.flush();
      expect(root.querySelector('.admin-wrap'), `page ${label} stayed mounted`).not.toBeNull();
    }
  });

  it('marks a setting dirty and saves it to the category endpoint', async () => {
    const fetch = adminBackend();
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], fetch, lang: 'ro' });
    await env.flush();
    const root = env.document.getElementById('root');

    // Go to the global config page.
    env.click([...root.querySelectorAll('.admin-nav button')].find((b) => b.textContent.includes('Configurări Globale')));
    await env.flush();

    // Toggle the first checkbox → becomes dirty.
    const box = root.querySelector('.admin-row input[type=checkbox]');
    expect(box).not.toBeNull();
    env.toggle(box);
    await env.flush();

    // A save button appears; click it and assert the category PUT fired.
    const saveBtn = [...root.querySelectorAll('button')].find((b) => /salv|save/i.test(b.textContent));
    expect(saveBtn, 'a save button is shown when dirty').toBeTruthy();
    env.click(saveBtn);
    await env.flush();
    expect(fetch).toHaveBeenCalledWith('/api/admin/settings/general', expect.objectContaining({ method: 'PUT' }));
  });
});

describe('admin chart/card components', () => {
  let env, h;
  beforeEach(() => {
    env = loadHud({
      files: ['i18n', 'data', 'components', 'admin'],
      expose: ['StatsCard', 'BarChart', 'Sparkline', 'Toast', 'GlobalConfigPage'],
      fetch: adminBackend(),
      lang: 'ro',
    });
    h = env.React.createElement;
  });
  afterEach(() => env.cleanup());

  it('StatsCard shows label and value', () => {
    const { container } = env.render(h(env.hud.StatsCard, { label: 'Runs', value: '10', color: '#0f0' }));
    expect(container.textContent).toContain('Runs');
    expect(container.textContent).toContain('10');
  });

  it('BarChart renders a bar per datum', () => {
    const data = [{ name: 'a', v: 5 }, { name: 'b', v: 10 }];
    const { container } = env.render(
      h(env.hud.BarChart, { data, valueKey: 'v', labelKey: 'name', maxValue: 10, colorFn: () => '#0f0', unit: '' }),
    );
    expect(container.textContent).toContain('a');
    expect(container.textContent).toContain('b');
  });

  it('Sparkline renders an svg for a series', () => {
    const { container } = env.render(
      h(env.hud.Sparkline, { data: [1, 3, 2, 5], width: 100, height: 20, color: '#0f0' }),
    );
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('Toast renders its message when present', () => {
    const { container } = env.render(h(env.hud.Toast, { message: 'Saved!' }));
    expect(container.textContent).toContain('Saved!');
  });

  it('GlobalConfigPage renders rows and fires onSave', () => {
    const onSave = vi.fn();
    const settings = { general: [{ key: 'dev_mode', label: 'Dev', kind: 'toggle', value: true }] };
    const { container } = env.render(
      h(env.hud.GlobalConfigPage, { settings, dirty: { dev_mode: true }, onUpdate: vi.fn(), onSave }),
    );
    // The page relabels keys via FRIENDLY_NAMES, so dev_mode → "Mod Dezvoltator…".
    expect(container.textContent.toLowerCase()).toContain('dezvoltator');
    const saveBtn = [...container.querySelectorAll('button')].find((b) => /salv|save/i.test(b.textContent));
    expect(saveBtn).toBeTruthy();
    env.click(saveBtn);
    expect(onSave).toHaveBeenCalled();
  });
});
