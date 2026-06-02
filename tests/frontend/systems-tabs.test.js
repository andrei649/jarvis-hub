// Remaining Systems panel tabs (systems.js): Memory, Plugins, Learning.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'systems'],
    expose: ['MemoryTab', 'PluginsTab', 'LearningTab'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('MemoryTab', () => {
  it('shows a loading state without data', () => {
    const { container } = env.render(h(env.hud.MemoryTab, { data: null, onRefresh: vi.fn() }));
    expect(container.querySelector('.sys-loading')).not.toBeNull();
  });

  const data = {
    sessions: { total: 12, active: 3, current: 'abc' },
    vectors: { stored: 1500, dimension: 768, backend: 'qdrant' },
    knowledge_graph: { entities: 40, relations: 88, last_seed: '2026-06-01' },
    agent_contexts: { pepper: 12, stark: 8 },
  };

  it('renders session, vector and graph stats', () => {
    const { container } = env.render(h(env.hud.MemoryTab, { data, onRefresh: vi.fn() }));
    const text = container.textContent;
    expect(text).toContain('12'); // sessions total
    expect(text).toContain('1,500'); // vectors stored, localized
    expect(text).toContain('qdrant');
    expect(text).toContain('2026-06-01');
  });

  it('toggles an agent context row as selected on click', () => {
    const { container } = env.render(h(env.hud.MemoryTab, { data, onRefresh: vi.fn() }));
    const row = container.querySelector('.sys-agent-ctx-row');
    env.click(row);
    expect(container.querySelector('.sys-agent-ctx-row.selected')).not.toBeNull();
  });

  it('calls onRefresh from the sessions card', () => {
    const onRefresh = vi.fn();
    const { container } = env.render(h(env.hud.MemoryTab, { data, onRefresh }));
    env.click(container.querySelector('.sys-refresh'));
    expect(onRefresh).toHaveBeenCalled();
  });
});

describe('PluginsTab', () => {
  const data = {
    total: 2,
    plugins: [
      { id: 'gmail', name: 'Gmail', enabled: true, network_access: 'WAN', data_scope: 'SHARED', allowed_domains: ['googleapis.com'], agents_served: ['pepper'] },
      { id: 'spotify', name: 'Spotify', enabled: false, network_access: 'WAN', data_scope: 'SHARED', allowed_domains: [], agents_served: ['jerome'] },
    ],
  };

  it('shows a loading state without data', () => {
    const { container } = env.render(h(env.hud.PluginsTab, { data: null, onToggle: vi.fn(), onRefresh: vi.fn() }));
    expect(container.querySelector('.sys-loading')).not.toBeNull();
  });

  it('summarizes enabled count and renders a card per plugin', () => {
    const { container } = env.render(h(env.hud.PluginsTab, { data, onToggle: vi.fn(), onRefresh: vi.fn() }));
    expect(container.querySelector('.sys-plugins-summary').textContent).toBe('1/2 enabled');
    expect(container.querySelectorAll('.sys-plugin-card')).toHaveLength(2);
    expect(container.querySelector('.sys-plugin-card.enabled')).not.toBeNull();
    expect(container.querySelector('.sys-plugin-card.disabled')).not.toBeNull();
  });

  it('fires onToggle with the plugin id', () => {
    const onToggle = vi.fn();
    const { container } = env.render(h(env.hud.PluginsTab, { data, onToggle, onRefresh: vi.fn() }));
    env.click(container.querySelector('.sys-plugin-toggle'));
    expect(onToggle).toHaveBeenCalledWith('gmail');
  });
});

describe('LearningTab', () => {
  it('shows a loading state without data', () => {
    const { container } = env.render(h(env.hud.LearningTab, { data: null, onRefresh: vi.fn() }));
    expect(container.querySelector('.sys-loading')).not.toBeNull();
  });
});
