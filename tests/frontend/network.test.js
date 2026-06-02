// Network brain (network.js): pure geometry helpers + a smoke render of the
// agent ring.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'network'],
    expose: ['NetworkBrain', 'textAnchorFor', 'tooltipStyle'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('textAnchorFor', () => {
  it('picks start/end/middle from the angle cosine', () => {
    expect(env.hud.textAnchorFor(0)).toBe('start'); // cos 0 = 1
    expect(env.hud.textAnchorFor(Math.PI)).toBe('end'); // cos π = -1
    expect(env.hud.textAnchorFor(Math.PI / 2)).toBe('middle'); // cos = 0
  });
});

describe('tooltipStyle', () => {
  it('anchors right/top for a node in the top-right quadrant', () => {
    const style = env.hud.tooltipStyle({ x: 800, y: 100 }, 880, 380);
    expect(style.left).toBeUndefined();
    expect(style.right).toBeDefined();
    expect(style.top).toBeDefined();
    expect(style.bottom).toBeUndefined();
  });
  it('anchors left/bottom for a node in the bottom-left quadrant', () => {
    const style = env.hud.tooltipStyle({ x: 100, y: 300 }, 880, 380);
    expect(style.left).toBeDefined();
    expect(style.right).toBeUndefined();
    expect(style.bottom).toBeDefined();
    expect(style.top).toBeUndefined();
  });
});

describe('NetworkBrain', () => {
  const agents = [
    { id: 'jarvis', name: 'Jarvis', status: 'active', glyph: 'M0,0' },
    { id: 'friday', name: 'Friday', status: 'idle', glyph: 'M0,0' },
    { id: 'pepper', name: 'Pepper', status: 'active', glyph: 'M0,0' },
  ];

  it('renders an svg ring including the agents', () => {
    const { container } = env.render(
      h(env.hud.NetworkBrain, {
        agents, tasks: [], collab: [], activeAgent: 'jarvis',
        onSelect: vi.fn(), routedAgents: [], voiceState: 'idle',
        focusAgent: null, onFocusAgent: vi.fn(),
      }),
    );
    expect(container.querySelector('svg')).not.toBeNull();
    const text = container.textContent.toLowerCase();
    expect(text).toContain('friday');
    expect(text).toContain('pepper');
  });
});
