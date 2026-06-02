// Presentational components from components.js.
// `function` declarations land on window, but we go through window.__hud
// uniformly for clarity.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({ files: ['components'], expose: ['Bracket', 'StatusDot'] });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('StatusDot', () => {
  it('renders a status-specific dot class', () => {
    const { container } = env.render(h(env.hud.StatusDot, { status: 'online' }));
    const dot = container.querySelector('span.dot');
    expect(dot).not.toBeNull();
    expect(dot.className).toContain('dot-online');
  });

  it('applies the size prop to width and height', () => {
    const { container } = env.render(h(env.hud.StatusDot, { status: 'warn', size: 12 }));
    const dot = container.querySelector('span.dot');
    expect(dot.style.width).toBe('12px');
    expect(dot.style.height).toBe('12px');
  });

  it('defaults size to 8px when omitted', () => {
    const { container } = env.render(h(env.hud.StatusDot, { status: 'idle' }));
    expect(container.querySelector('span.dot').style.width).toBe('8px');
  });
});

describe('Bracket', () => {
  it('renders the four corner markers and a body', () => {
    const { container } = env.render(h(env.hud.Bracket, {}, 'content'));
    expect(container.querySelectorAll('.bk-corner')).toHaveLength(4);
    const body = container.querySelector('.bk-body');
    expect(body).not.toBeNull();
    expect(body.textContent).toBe('content');
  });

  it('renders a header with label and status when provided', () => {
    const { container } = env.render(
      h(env.hud.Bracket, { label: 'SYSTEMS', status: 'OK' }, 'x'),
    );
    expect(container.querySelector('.bk-label').textContent).toBe('SYSTEMS');
    expect(container.querySelector('.bk-status').textContent).toBe('OK');
  });

  it('omits the header when no label or status', () => {
    const { container } = env.render(h(env.hud.Bracket, {}, 'x'));
    expect(container.querySelector('.bk-head')).toBeNull();
  });

  it('merges a custom className onto the bracket', () => {
    const { container } = env.render(h(env.hud.Bracket, { className: 'wide' }, 'x'));
    expect(container.querySelector('.bracket').className).toContain('wide');
  });
});
