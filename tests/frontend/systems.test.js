// Systems panel (systems.js): the tab bar and the self-fetching Fused Recall
// search box.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'systems'],
    expose: ['SystemsTabBar', 'FusedRecallBox'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('SystemsTabBar', () => {
  it('renders the full set of tabs', () => {
    const { container } = env.render(h(env.hud.SystemsTabBar, { active: 'memory', onChange: vi.fn() }));
    const labels = [...container.querySelectorAll('.sys-tab')].map((b) => b.textContent);
    expect(labels).toEqual([
      'Memory', 'Plugins', 'Heartbeats', 'Learning',
      'Resilience', 'OAuth Status', 'Oracle Tab', 'Security & Bench',
    ]);
  });

  it('marks the active tab', () => {
    const { container } = env.render(h(env.hud.SystemsTabBar, { active: 'plugins', onChange: vi.fn() }));
    const active = container.querySelector('.sys-tab.active');
    expect(active.textContent).toBe('Plugins');
    expect(container.querySelectorAll('.sys-tab.active')).toHaveLength(1);
  });

  it('reports the clicked tab id', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.SystemsTabBar, { active: 'memory', onChange }));
    const learning = [...container.querySelectorAll('.sys-tab')].find((b) => b.textContent === 'Learning');
    env.click(learning);
    expect(onChange).toHaveBeenCalledWith('learning');
  });
});

describe('FusedRecallBox', () => {
  it('queries /api/memory/search and renders scored hits', async () => {
    env.window.fetch = vi.fn().mockResolvedValue({
      json: async () => ({
        total: 2,
        results: [
          { id: 'm1', score: 0.912, sources: ['vector', 'graph'] },
          { id: 'm2', score: 0.5, sources: ['vector'] },
        ],
      }),
    });

    const { container } = env.render(h(env.hud.FusedRecallBox));
    env.type(container.querySelector('.sys-recall-input'), 'andrei');
    env.click(container.querySelector('.sys-recall-btn'));

    // Let the awaited fetch + setState settle, then flush React.
    await env.flush();

    const url = env.window.fetch.mock.calls[0][0];
    expect(url).toContain('/api/memory/search?q=andrei');
    expect(url).toContain('top_k=8');

    const hits = container.querySelectorAll('.sys-recall-hit');
    expect(hits).toHaveLength(2);
    expect(container.querySelector('.sys-recall-score').textContent).toBe('0.912');
    expect(container.querySelector('.sys-recall-sources').textContent).toBe('vector+graph');
  });

  it('shows an empty state when there are no results', async () => {
    env.window.fetch = vi.fn().mockResolvedValue({ json: async () => ({ total: 0, results: [] }) });
    const { container } = env.render(h(env.hud.FusedRecallBox));
    env.type(container.querySelector('.sys-recall-input'), 'zzz');
    env.click(container.querySelector('.sys-recall-btn'));
    await env.flush();
    expect(container.querySelector('.sys-recall-empty').textContent).toBe('No results');
  });

  it('does not fetch on an empty query', () => {
    env.window.fetch = vi.fn();
    const { container } = env.render(h(env.hud.FusedRecallBox));
    env.click(container.querySelector('.sys-recall-btn'));
    expect(env.window.fetch).not.toHaveBeenCalled();
  });
});
