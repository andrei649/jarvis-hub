// Remaining components.js list/grid blocks: AgentList, AgentsGrid,
// HeartbeatFeed, and the admin renderRow dispatcher.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'admin'],
    expose: ['AgentList', 'AgentsGrid', 'HeartbeatFeed', 'renderRow'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

const agents = [
  { id: 'jarvis', name: 'Jarvis', role: 'Orchestrator', tier: 'CNS', status: 'active', model: 'gemma-4-31b', glyph: 'M0,0' },
  { id: 'gecko', name: 'Gecko', role: 'Markets', tier: 'FND', status: 'idle', model: 'gemma-4-26b', glyph: 'M0,0' },
];

describe('AgentList', () => {
  const tiers = [{ id: 'CNS', label: 'Command' }, { id: 'FND', label: 'Foundation' }];
  const sys = { host: 'bonobo', cpu: 'Ryzen', ram_used: 48, ram_total: 192, vram_used: 10, vram_total: 24, gpu_load: 30, backend: 'lmstudio', model: 'gemma' };

  it('groups agents by tier and renders one item each', () => {
    const { container } = env.render(
      h(env.hud.AgentList, { agents, tiers, activeAgent: 'jarvis', onSelect: vi.fn(), sys }),
    );
    expect(container.querySelectorAll('.agent-item')).toHaveLength(2);
    expect(container.querySelector('.agent-item.is-active .agent-name').textContent).toBe('Jarvis');
  });

  it('selects on click and double-click', () => {
    const onSelect = vi.fn();
    const onDoubleClick = vi.fn();
    const { container } = env.render(
      h(env.hud.AgentList, { agents, tiers, activeAgent: 'jarvis', onSelect, onDoubleClick, sys }),
    );
    const geckoItem = [...container.querySelectorAll('.agent-item')].find((b) => /Gecko/.test(b.textContent));
    env.click(geckoItem);
    env.fire(geckoItem, 'dblclick');
    expect(onSelect).toHaveBeenCalledWith('gecko');
    expect(onDoubleClick).toHaveBeenCalledWith('gecko');
  });
});

describe('AgentsGrid', () => {
  it('renders a 3-letter cell per agent and reports clicks', () => {
    const onSelect = vi.fn();
    const { container } = env.render(h(env.hud.AgentsGrid, { agents, activeAgent: 'gecko', onSelect }));
    const tags = [...container.querySelectorAll('.agrid-tag')].map((t) => t.textContent);
    expect(tags).toEqual(['JAR', 'GEC']);
    expect(container.querySelector('.agrid-cell.is-active')).not.toBeNull();
    env.click([...container.querySelectorAll('.agrid-cell')][0]);
    expect(onSelect).toHaveBeenCalledWith('jarvis');
  });
});

describe('HeartbeatFeed', () => {
  it('renders feed items with uppercased agent tags', () => {
    const agentMap = { gecko: { name: 'Gecko' } };
    const items = [
      { id: 1, agent: 'gecko', level: 'info', ts: '12:00', text: 'pulse ok' },
      { id: 2, agent: 'unknown', level: 'warn', ts: '12:01', text: 'late' },
    ];
    const { container } = env.render(h(env.hud.HeartbeatFeed, { items, agentMap }));
    expect(container.querySelectorAll('.hb')).toHaveLength(2);
    expect(container.querySelector('.hb-tag').textContent).toBe('[GECKO]');
    expect(container.textContent).toContain('pulse ok');
  });
});

describe('renderRow (admin dispatcher)', () => {
  function rendered(setting) {
    const onUpdate = vi.fn();
    const onAction = vi.fn();
    const { container } = env.render(env.hud.renderRow(setting, 0, onUpdate, onAction));
    return { container, onUpdate, onAction };
  }

  it('dispatches a toggle setting to a checkbox row', () => {
    const { container } = rendered({ kind: 'toggle', key: 'dev_mode', label: 'Dev', value: true });
    expect(container.querySelector('input[type=checkbox]').checked).toBe(true);
  });

  it('dispatches a select setting and forwards updates with the key', () => {
    const { container, onUpdate } = rendered({ kind: 'select', key: 'theme', label: 'Theme', value: 'a', opts: ['a', 'b'] });
    env.selectOption(container.querySelector('select'), 'b');
    expect(onUpdate).toHaveBeenCalledWith('theme', 'b');
  });

  it('dispatches a button setting to onAction with the key', () => {
    const { container, onAction } = rendered({ kind: 'button', key: 'reset', label: 'Reset', opts: ['Run', 'danger'] });
    env.click(container.querySelector('.admin-btn'));
    expect(onAction).toHaveBeenCalledWith('reset');
  });

  it('falls back to a text input for unknown kinds', () => {
    const { container } = rendered({ kind: 'mystery', key: 'x', label: 'X', value: 'v' });
    expect(container.querySelector('input.admin-input').value).toBe('v');
  });
});
