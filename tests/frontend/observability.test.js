// Trace Explorer (observability.js): trace table rows, timing bars, the detail
// pane, and the format helpers they share.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'observability'],
    expose: ['TraceRow', 'TimingBar', 'TraceDetail', '_fmtMs', '_agentList'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('_fmtMs', () => {
  it('renders sub-second values in ms', () => {
    expect(env.hud._fmtMs(0)).toBe('0ms');
    expect(env.hud._fmtMs(450)).toBe('450ms');
  });
  it('renders >=1s values in seconds with 2 decimals', () => {
    expect(env.hud._fmtMs(1500)).toBe('1.50s');
  });
  it('renders a dash for null/undefined', () => {
    expect(env.hud._fmtMs(null)).toBe('—');
    expect(env.hud._fmtMs(undefined)).toBe('—');
  });
});

describe('_agentList', () => {
  it('joins agents and dashes when empty', () => {
    expect(env.hud._agentList(['a', 'b'])).toBe('a, b');
    expect(env.hud._agentList([])).toBe('—');
    expect(env.hud._agentList(null)).toBe('—');
  });
});

describe('TraceRow', () => {
  const trace = {
    id: 't1', ts: 0, channel: 'web', route: 'finance', agents: ['gecko'],
    model: 'lmstudio/gemma-4-31b', total_ms: 1200, tokens_in: 50, tokens_out: 80, ok: true,
  };

  function renderRow(props) {
    // A <tr> needs a table ancestor.
    const { container } = env.render(h('table', null, h('tbody', null, h(env.hud.TraceRow, props))));
    return container;
  }

  it('renders the trimmed model, channel, route and an OK status', () => {
    const c = renderRow({ trace, onSelect: vi.fn(), selected: false });
    expect(c.querySelector('.obs-channel').textContent).toBe('web');
    expect(c.querySelector('.obs-route').textContent).toBe('finance');
    expect(c.querySelector('.obs-model').textContent).toBe('gemma-4-31b');
    expect(c.querySelector('.obs-total-ms').textContent).toBe('1.20s');
    const status = c.querySelector('.obs-status-dot');
    expect(status.className).toContain('obs-ok');
    expect(status.textContent).toBe('OK');
  });

  it('renders an ERR status when not ok', () => {
    const c = renderRow({ trace: { ...trace, ok: false }, onSelect: vi.fn(), selected: false });
    const status = c.querySelector('.obs-status-dot');
    expect(status.className).toContain('obs-err');
    expect(status.textContent).toBe('ERR');
  });

  it('fires onSelect with the trace on click', () => {
    const onSelect = vi.fn();
    const c = renderRow({ trace, onSelect, selected: false });
    env.click(c.querySelector('.obs-trace-row'));
    expect(onSelect).toHaveBeenCalledWith(trace);
  });
});

describe('TimingBar', () => {
  it('computes the fill percentage from ms/total', () => {
    const { container } = env.render(h(env.hud.TimingBar, { label: 'route', ms: 25, total: 100 }));
    expect(container.querySelector('.obs-timing-fill').style.width).toBe('25%');
    expect(container.querySelector('.obs-timing-label').textContent).toBe('route');
    expect(container.querySelector('.obs-timing-val').textContent).toBe('25ms');
  });
  it('clamps to 0 when total is 0', () => {
    const { container } = env.render(h(env.hud.TimingBar, { label: 'x', ms: 5, total: 0 }));
    expect(container.querySelector('.obs-timing-fill').style.width).toBe('0%');
  });
});

describe('TraceDetail', () => {
  it('returns nothing without a trace', () => {
    const { container } = env.render(h(env.hud.TraceDetail, { trace: null, onClose: vi.fn() }));
    expect(container.innerHTML).toBe('');
  });

  it('renders four timing bars and wires onClose', () => {
    const onClose = vi.fn();
    const trace = {
      id: 't9', ts: 0, model: 'm', text_preview: 'hello',
      timings: { classify: 2, route: 1, plugin: 3, synthesize: 10 },
    };
    const { container } = env.render(h(env.hud.TraceDetail, { trace, onClose }));
    expect(container.querySelectorAll('.obs-timing-row')).toHaveLength(4);
    expect(container.querySelector('.obs-preview').textContent).toBe('hello');
    env.click(container.querySelector('.obs-close-btn'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
