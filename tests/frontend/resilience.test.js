// Regression guard for the systems.js ResilienceTab — the component whose
// missing closing brace previously broke the entire Systems panel at load.
// Beyond catching the parse error (any test loading systems.js does that), we
// assert its rendered behaviour.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'systems'],
    expose: ['ResilienceTab'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('ResilienceTab', () => {
  it('shows a loading state without data', () => {
    const { container } = env.render(h(env.hud.ResilienceTab, { data: null, onRefresh: vi.fn() }));
    expect(container.querySelector('.sys-loading')).not.toBeNull();
  });

  it('shows an empty state when there are no metrics or breakers', () => {
    const { container } = env.render(
      h(env.hud.ResilienceTab, { data: { metrics: {}, circuit_breakers: {} }, onRefresh: vi.fn() }),
    );
    expect(container.querySelector('.sys-empty')).not.toBeNull();
  });

  it('renders retry metrics with success/failure/latency', () => {
    const data = {
      metrics: {
        gmail: { success: 10, failure: 2, avg_latency: 0.345, error_types: { Timeout: 2 } },
      },
      circuit_breakers: {},
    };
    const { container } = env.render(h(env.hud.ResilienceTab, { data, onRefresh: vi.fn() }));
    const text = container.textContent;
    expect(container.querySelector('.sys-resilience-key').textContent).toBe('gmail');
    expect(text).toContain('10'); // success
    expect(text).toContain('0.34s'); // avg latency, 2dp + 's'
    expect(text).toContain('Timeout');
  });

  it('renders circuit breaker state and failure count', () => {
    const data = {
      metrics: {},
      circuit_breakers: {
        spotify: { state: 'open', failure_count: 5, last_failure_time: 0 },
      },
    };
    const { container } = env.render(h(env.hud.ResilienceTab, { data, onRefresh: vi.fn() }));
    const row = container.querySelector('.sys-cb-row');
    expect(row.className).toContain('open');
    expect(container.querySelector('.sys-cb-state').textContent).toBe('OPEN');
    expect(container.textContent).toContain('Failures: 5');
  });

  it('wires onRefresh', () => {
    const onRefresh = vi.fn();
    const data = { metrics: { x: { success: 1, failure: 0, avg_latency: 0 } }, circuit_breakers: {} };
    const { container } = env.render(h(env.hud.ResilienceTab, { data, onRefresh }));
    env.click(container.querySelector('.sys-refresh'));
    expect(onRefresh).toHaveBeenCalled();
  });
});
