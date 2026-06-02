// Visual Workflow Builder (workflows.js): the SVG canvas, the add-step form,
// and the run result panel.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'workflows'],
    expose: ['WorkflowCanvas', 'StepForm', 'ResultPanel'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('WorkflowCanvas', () => {
  const steps = [
    { id: 'fetch', agent_id: 'veronica', depends_on: [] },
    { id: 'summarize', agent_id: 'friday', depends_on: ['fetch'] },
  ];
  const layout = { fetch: { x: 20, y: 20 }, summarize: { x: 200, y: 20 } };

  it('renders one node group per step', () => {
    const { container } = env.render(h(env.hud.WorkflowCanvas, { steps, layout }));
    expect(container.querySelectorAll('svg > g')).toHaveLength(2);
    expect(container.textContent).toContain('fetch');
    expect(container.textContent).toContain('summarize');
  });

  it('draws an edge for each resolved dependency', () => {
    const { container } = env.render(h(env.hud.WorkflowCanvas, { steps, layout }));
    // One dependency (fetch -> summarize) => one edge path (excludes the marker defs path).
    const edgePaths = [...container.querySelectorAll('svg > path')];
    expect(edgePaths).toHaveLength(1);
    expect(container.textContent).toContain('deps:1');
  });

  it('omits edges when an endpoint has no layout position', () => {
    const { container } = env.render(h(env.hud.WorkflowCanvas, { steps, layout: { fetch: { x: 0, y: 0 } } }));
    expect(container.querySelectorAll('svg > path')).toHaveLength(0);
  });
});

describe('StepForm', () => {
  it('disables Add Step until id and agent are filled', () => {
    const { container } = env.render(h(env.hud.StepForm, { existingIds: [], onAdd: vi.fn() }));
    const btn = [...container.querySelectorAll('button')].find((b) => /Add Step/.test(b.textContent));
    expect(btn.disabled).toBe(true);
  });

  it('emits the new step and clears the form on submit', () => {
    const onAdd = vi.fn();
    const { container } = env.render(h(env.hud.StepForm, { existingIds: [], onAdd }));
    const [idInput, agentInput] = container.querySelectorAll('input[type=text]');
    env.type(idInput, 'summarize');
    env.type(agentInput, 'friday');
    const btn = [...container.querySelectorAll('button')].find((b) => /Add Step/.test(b.textContent));
    env.click(btn);
    expect(onAdd).toHaveBeenCalledWith({
      id: 'summarize', agent_id: 'friday', prompt_template: '{_input}', depends_on: [],
    });
    expect(idInput.value).toBe('');
  });

  it('toggles a dependency chip into the submitted step', () => {
    const onAdd = vi.fn();
    const { container } = env.render(h(env.hud.StepForm, { existingIds: ['fetch'], onAdd }));
    env.type(container.querySelectorAll('input[type=text]')[0], 's2');
    env.type(container.querySelectorAll('input[type=text]')[1], 'friday');
    const depBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === 'fetch');
    env.click(depBtn);
    env.click([...container.querySelectorAll('button')].find((b) => /Add Step/.test(b.textContent)));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ depends_on: ['fetch'] }));
  });
});

describe('ResultPanel', () => {
  it('returns nothing without a result', () => {
    const { container } = env.render(h(env.hud.ResultPanel, { result: null }));
    expect(container.innerHTML).toBe('');
  });

  it('renders non-underscore keys and a success header', () => {
    const { container } = env.render(
      h(env.hud.ResultPanel, { result: { _ok: true, _elapsed: 2.5, summarize: 'done', fetch: 'ok' } }),
    );
    expect(container.textContent).toContain('✓ Run complete');
    expect(container.textContent).toContain('2.5s');
    expect(container.textContent).toContain('summarize:');
    expect(container.textContent).toContain('fetch:');
    // Underscore-prefixed keys are not rendered as rows.
    expect(container.textContent).not.toContain('_ok:');
  });

  it('shows an error header when not ok', () => {
    const { container } = env.render(h(env.hud.ResultPanel, { result: { _ok: false } }));
    expect(container.textContent).toContain('✗ Run errors');
  });

  it('truncates long values to 400 chars', () => {
    const long = 'x'.repeat(1000);
    const { container } = env.render(h(env.hud.ResultPanel, { result: { _ok: true, out: long } }));
    expect(container.textContent).toContain('x'.repeat(400));
    expect(container.textContent).not.toContain('x'.repeat(401));
  });
});
