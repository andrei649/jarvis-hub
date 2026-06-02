// Second-wave HUD components (enhancements.js): the situation ticker, the
// command palette, and the numeric clamp/round helpers.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'enhancements'],
    expose: ['SituationTicker', 'CommandPalette', 'clamp', 'round1', 'round2'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('numeric helpers', () => {
  it('clamp bounds a value', () => {
    expect(env.hud.clamp(5, 0, 10)).toBe(5);
    expect(env.hud.clamp(-3, 0, 10)).toBe(0);
    expect(env.hud.clamp(99, 0, 10)).toBe(10);
  });
  it('round1 / round2 round to 1 and 2 decimals', () => {
    expect(env.hud.round1(3.146)).toBe(3.1);
    expect(env.hud.round2(3.14159)).toBe(3.14);
  });
});

describe('SituationTicker', () => {
  const agentMap = { gecko: { name: 'Gecko', glyph: 'M0,0' } };

  it('duplicates items for a seamless marquee loop', () => {
    const items = [
      { agent: 'gecko', verb: 'tracking', obj: 'markets', pri: 'hi', pct: 60 },
      { agent: 'gecko', verb: 'syncing', obj: 'ledger', pri: 'mid' },
    ];
    const { container } = env.render(h(env.hud.SituationTicker, { items, agentMap, voiceState: 'idle' }));
    // loop = items + items → 2x rows.
    expect(container.querySelectorAll('.tk')).toHaveLength(4);
  });

  it('uppercases the agent name and reflects voice state', () => {
    const items = [{ agent: 'gecko', verb: 'x', obj: 'y', pri: 'ok' }];
    const { container } = env.render(h(env.hud.SituationTicker, { items, agentMap, voiceState: 'listening' }));
    expect(container.querySelector('.tk-agent').textContent).toBe('GECKO');
    expect(container.querySelector('.situation-sub').textContent).toContain('LISTENING');
  });

  it('renders a percent bar only when pct is numeric', () => {
    const items = [{ agent: 'gecko', verb: 'x', obj: 'y', pri: 'hi', pct: 42 }];
    const { container } = env.render(h(env.hud.SituationTicker, { items, agentMap, voiceState: 'idle' }));
    expect(container.querySelector('.tk-pct-val').textContent).toBe('42%');
  });
});

describe('CommandPalette', () => {
  const agents = [
    { id: 'gecko', name: 'Gecko', role: 'Markets', tier: 'FND', model: 'm', glyph: 'M0,0', status: 'active' },
  ];
  const base = { agents, tasks: [], projects: [], onClose: vi.fn(), onAction: vi.fn() };

  it('renders nothing when closed', () => {
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, open: false }));
    expect(container.innerHTML).toBe('');
  });

  it('shows agents and voice commands with an empty query', () => {
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, open: true }));
    const labels = [...container.querySelectorAll('.palette-label')].map((l) => l.textContent);
    expect(labels).toContain('Gecko');
    expect(labels).toContain('Set voice → idle');
  });

  it('filters by query and shows an empty state for no match', () => {
    // Agents always score >=1, so an empty corpus of agents is needed to reach
    // the no-match state.
    const { container } = env.render(
      h(env.hud.CommandPalette, { ...base, agents: [], open: true }),
    );
    env.type(container.querySelector('.palette-input'), 'zzzznomatch');
    expect(container.querySelector('.palette-empty').textContent).toContain('zzzznomatch');
  });

  it('narrows results by query token', () => {
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, open: true }));
    env.type(container.querySelector('.palette-input'), 'speaking');
    const labels = [...container.querySelectorAll('.palette-label')].map((l) => l.textContent);
    expect(labels).toContain('Set voice → speaking');
    expect(labels).not.toContain('Set voice → idle');
  });

  it('runs a row on click: fires onAction and onClose', () => {
    const onClose = vi.fn();
    const onAction = vi.fn();
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, onClose, onAction, open: true }));
    const geckoRow = [...container.querySelectorAll('.palette-row')]
      .find((r) => r.textContent.includes('Gecko'));
    env.click(geckoRow);
    expect(onAction).toHaveBeenCalledWith({ type: 'focus_agent', agent: 'gecko' }, expect.objectContaining({ id: 'gecko' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, onClose, open: true }));
    env.keyDown(container.querySelector('.palette-input'), 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('runs the highlighted row on Enter', () => {
    const onAction = vi.fn();
    const { container } = env.render(h(env.hud.CommandPalette, { ...base, onAction, open: true }));
    // First result is the agent (agents are listed before commands with empty query).
    env.keyDown(container.querySelector('.palette-input'), 'Enter');
    expect(onAction).toHaveBeenCalledWith({ type: 'focus_agent', agent: 'gecko' }, expect.anything());
  });
});
