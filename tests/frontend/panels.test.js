// Self-fetching top-level panels: SystemsPanel (with a full tab sweep),
// WorkflowsPanel and ObservabilityPanel. Mounted against stubbed backends.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function json(body) { return Promise.resolve({ json: async () => body, ok: true }); }

function systemsBackend() {
  return vi.fn((url) => {
    if (url === '/memory/stats') return json({
      sessions: { total: 5, active: 1, current: 'x' },
      vectors: { stored: 100, dimension: 768, backend: 'qdrant' },
      knowledge_graph: { entities: 10, relations: 20, last_seed: '2026-06-01' },
      agent_contexts: { pepper: 3 },
    });
    if (url === '/plugins') return json({ plugins: [], total: 0 });
    if (url === '/heartbeat/status') return json({ agents: {} });
    if (url === '/learning/stats') return json({
      interactions_total: 42, success_rate: 0.9,
      prompt_optimizations: [], promotion_candidates: [], demotion_warnings: [],
    });
    if (url === '/api/resilience') return json({ metrics: {}, circuit_breakers: {} });
    // SecurityBenchTab guards on !security/!bench → null hits the loading state
    // safely (its nested shape is deep; the tab still mounts via the sweep).
    if (url === '/security/status') return json(null);
    if (url === '/bench/stats') return json(null);
    if (url === '/api/oauth/status') return json({ services: [] });
    if (url === '/api/oracle/status') return json({ connected: false });
    if (url === '/api/oracle/conflicts') return json({ conflicts: [] });
    return json({});
  });
}

describe('SystemsPanel', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('mounts and sweeps every tab without crashing', async () => {
    const fetch = systemsBackend();
    env = loadHud({ files: ['i18n', 'data', 'components', 'systems'], expose: ['SystemsPanel'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const agents = [{ id: 'gecko', name: 'Gecko', status: 'idle', tier: 'FND', role: 'Markets' }];
    const { container } = env.render(h(env.hud.SystemsPanel, { agents, onRefresh: vi.fn(), onPluginToggle: vi.fn() }));
    await env.flush();

    // Default memory tab fetched.
    expect(fetch).toHaveBeenCalledWith('/memory/stats');
    expect(container.querySelector('.sys-tab-bar')).not.toBeNull();

    // Click through every tab; the panel must stay mounted.
    const tabs = [...container.querySelectorAll('.sys-tab')];
    expect(tabs.length).toBeGreaterThanOrEqual(8);
    for (const tab of tabs) {
      env.click(tab);
      await env.flush();
      expect(container.querySelector('.sys-tab-bar'), `tab ${tab.textContent} kept panel mounted`).not.toBeNull();
    }
    // Tabs that fetch live data were hit.
    expect(fetch).toHaveBeenCalledWith('/api/resilience');
  });
});

describe('WorkflowsPanel', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('mounts and lists workflows from the backend', async () => {
    const fetch = vi.fn((url) => {
      if (url.startsWith('/api/workflows')) return json({ workflows: [{ name: 'finance_report', steps: [] }] });
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'workflows'], expose: ['WorkflowsPanel'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const { container } = env.render(h(env.hud.WorkflowsPanel));
    await env.flush();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/workflows'));
    expect(container.childElementCount).toBeGreaterThan(0);
  });
});

describe('ObservabilityPanel', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('mounts and requests the trace list', async () => {
    const fetch = vi.fn((url) => {
      if (url.startsWith('/api/traces')) return json({ traces: [] });
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'observability'], expose: ['ObservabilityPanel'], fetch, lang: 'ro' });
    const h = env.React.createElement;
    const { container } = env.render(h(env.hud.ObservabilityPanel));
    await env.flush();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/traces'));
    expect(container.childElementCount).toBeGreaterThan(0);
  });
});
