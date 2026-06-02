// Cognition panel (cognition.js): intent classification, routing decision,
// orchestration trace. All prop-driven.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'cognition'],
    expose: ['IntentClassification', 'RoutingDecision', 'OrchestrationTrace', 'CognitionPanel'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('IntentClassification', () => {
  it('renders a NO MATCH empty state when there is no scoring', () => {
    const { container } = env.render(h(env.hud.IntentClassification, { scoring: [] }));
    expect(container.querySelector('.cog-status').textContent).toBe('NO MATCH');
    expect(container.querySelector('.cog-empty')).not.toBeNull();
  });

  it('renders one keyword row per match with a weight bar', () => {
    const scoring = [
      { keyword: 'invoice', category: 'finance', weight: 0.8, agents: ['gecko', 'stark'] },
      { keyword: 'play', category: 'music', weight: 0.4, agents: ['jerome'] },
    ];
    const { container } = env.render(h(env.hud.IntentClassification, { scoring }));
    expect(container.querySelector('.cog-status').textContent).toBe('2 KEYWORDS');
    expect(container.querySelectorAll('.cog-keyword-row')).toHaveLength(2);
    const fill = container.querySelector('.cog-weight-fill');
    expect(fill.style.width).toBe('80%');
    expect(container.querySelector('.cog-weight-val').textContent).toBe('80%');
    expect([...container.querySelectorAll('.cog-agent-pill')].map((p) => p.textContent)).toEqual([
      'gecko', 'stark', 'jerome',
    ]);
  });
});

describe('RoutingDecision', () => {
  const decision = {
    source: 'keyword',
    confidence: 0.92,
    agents_selected: ['gecko'],
    alternatives: [{ agent: 'stark', score: 0.4 }],
    timing: { classify: 3, route: 1 },
  };

  it('returns nothing without a decision', () => {
    const { container } = env.render(h(env.hud.RoutingDecision, { decision: null }));
    expect(container.innerHTML).toBe('');
  });

  it('shows source, confidence, selected agents and timing', () => {
    const { container } = env.render(h(env.hud.RoutingDecision, { decision }));
    expect(container.querySelector('.cog-status').textContent).toBe('KEYWORD');
    expect(container.querySelector('.cog-confidence-fill').style.width).toBe('92%');
    expect(container.querySelector('.cog-confidence-val').textContent).toBe('92%');
    expect(container.querySelector('.cog-selected-agents').textContent).toBe('gecko');
    expect(container.querySelector('.cog-timing').textContent).toBe('3ms classify · 1ms route');
  });

  it('renders alternatives when present', () => {
    const { container } = env.render(h(env.hud.RoutingDecision, { decision }));
    expect(container.querySelector('.cog-alt-agent').textContent).toBe('stark');
    expect(container.querySelector('.cog-alt-score').textContent).toBe('40%');
  });
});

describe('OrchestrationTrace', () => {
  it('returns nothing for an empty trace', () => {
    const { container } = env.render(h(env.hud.OrchestrationTrace, { trace: [] }));
    expect(container.innerHTML).toBe('');
  });

  it('sums durations and renders per-step details', () => {
    const trace = [
      { step: 'classify', duration_ms: 3, result: 'keyword' },
      { step: 'route', duration_ms: 1, agents: ['gecko', 'stark'] },
      { step: 'synthesize', duration_ms: 120, tokens: 256 },
    ];
    const { container } = env.render(h(env.hud.OrchestrationTrace, { trace }));
    expect(container.querySelector('.cog-status').textContent).toBe('124ms TOTAL');
    expect(container.querySelectorAll('.cog-timeline-row')).toHaveLength(3);
    const text = container.textContent;
    expect(text).toContain('Source: keyword');
    expect(text).toContain('Agents: gecko, stark');
    expect(text).toContain('Tokens: 256');
  });
});

describe('CognitionPanel', () => {
  it('collapses and expands its body', () => {
    const { container } = env.render(
      h(env.hud.CognitionPanel, { scoring: [], decision: null, trace: [] }),
    );
    expect(container.querySelector('.cognition-body')).not.toBeNull();
    const collapseBtn = container.querySelectorAll('.cog-btn');
    const toggleBtn = collapseBtn[collapseBtn.length - 1];
    env.click(toggleBtn);
    expect(container.querySelector('.cognition-panel').className).toContain('collapsed');
    expect(container.querySelector('.cognition-body')).toBeNull();
  });

  it('wires the refresh button to onRefresh', () => {
    const onRefresh = vi.fn();
    const { container } = env.render(
      h(env.hud.CognitionPanel, { scoring: [], decision: null, trace: [], onRefresh }),
    );
    env.click(container.querySelector('.cog-btn'));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
