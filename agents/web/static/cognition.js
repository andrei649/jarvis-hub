'use strict';
/* cognition.js — v0.3 Cognition panel: intent classification, routing decision, orchestration trace */

const { useState, useEffect, useMemo } = React;
const h = React.createElement;

function IntentClassification({ scoring, message }) {
  if (!scoring || scoring.length === 0) {
    return h('div', { className: 'cog-section' },
      h('div', { className: 'cog-section-head' },
        h('span', { className: 'cog-label' }, 'INTENT CLASSIFICATION'),
        h('span', { className: 'cog-status dim' }, 'NO MATCH')
      ),
      h('div', { className: 'cog-empty' }, 'No keywords matched. Routing to Jarvis (general).')
    );
  }

  return h('div', { className: 'cog-section' },
    h('div', { className: 'cog-section-head' },
      h('span', { className: 'cog-label' }, 'INTENT CLASSIFICATION'),
      h('span', { className: 'cog-status active' }, scoring.length + ' KEYWORDS')
    ),
    h('div', { className: 'cog-keyword-list' },
      scoring.map((s, i) =>
        h('div', { key: i, className: 'cog-keyword-row' },
          h('div', { className: 'cog-keyword-head' },
            h('span', { className: 'cog-keyword' }, '"' + s.keyword + '"'),
            h('span', { className: 'cog-category' }, s.category)
          ),
          h('div', { className: 'cog-weight-bar' },
            h('div', { className: 'cog-weight-fill', style: { width: (s.weight * 100) + '%' } }),
            h('span', { className: 'cog-weight-val' }, (s.weight * 100).toFixed(0) + '%')
          ),
          h('div', { className: 'cog-agents' },
            s.agents.map((a, j) => h('span', { key: j, className: 'cog-agent-pill' }, a))
          )
        )
      )
    )
  );
}

function RoutingDecision({ decision }) {
  if (!decision) return null;

  const { source, confidence, agents_selected, alternatives, timing } = decision;

  return h('div', { className: 'cog-section' },
    h('div', { className: 'cog-section-head' },
      h('span', { className: 'cog-label' }, 'ROUTING DECISION'),
      h('span', { className: 'cog-status ok' }, source.toUpperCase())
    ),
    h('div', { className: 'cog-decision-grid' },
      h('div', { className: 'cog-decision-col' },
        h('span', { className: 'cog-decision-label' }, 'Confidence'),
        h('div', { className: 'cog-confidence-bar' },
          h('div', { className: 'cog-confidence-fill', style: { width: (confidence * 100) + '%' } })
        ),
        h('span', { className: 'cog-confidence-val' }, (confidence * 100).toFixed(0) + '%')
      ),
      h('div', { className: 'cog-decision-col' },
        h('span', { className: 'cog-decision-label' }, 'Selected Agents'),
        h('div', { className: 'cog-selected-agents' },
          agents_selected.map((a, i) => h('span', { key: i, className: 'cog-agent-pill primary' }, a))
        )
      ),
      h('div', { className: 'cog-decision-col' },
        h('span', { className: 'cog-decision-label' }, 'Timing'),
        h('span', { className: 'cog-timing' }, timing.classify + 'ms classify · ' + timing.route + 'ms route')
      )
    ),
    alternatives && alternatives.length > 0 && h('div', { className: 'cog-alternatives' },
      h('span', { className: 'cog-alt-label' }, 'Alternatives:'),
      alternatives.map((alt, i) =>
        h('div', { key: i, className: 'cog-alt-row' },
          h('span', { className: 'cog-alt-agent' }, alt.agent),
          h('div', { className: 'cog-alt-bar' },
            h('div', { className: 'cog-alt-fill', style: { width: (alt.score * 100) + '%' } })
          ),
          h('span', { className: 'cog-alt-score' }, (alt.score * 100).toFixed(0) + '%')
        )
      )
    )
  );
}

function OrchestrationTrace({ trace }) {
  if (!trace || trace.length === 0) return null;

  const totalMs = trace.reduce((sum, t) => sum + t.duration_ms, 0);

  return h('div', { className: 'cog-section' },
    h('div', { className: 'cog-section-head' },
      h('span', { className: 'cog-label' }, 'ORCHESTRATION TRACE'),
      h('span', { className: 'cog-status ok' }, totalMs + 'ms TOTAL')
    ),
    h('div', { className: 'cog-timeline' },
      trace.map((step, i) =>
        h('div', { key: i, className: 'cog-timeline-row' },
          h('div', { className: 'cog-timeline-marker' },
            h('div', { className: 'cog-timeline-dot' }),
            i < trace.length - 1 && h('div', { className: 'cog-timeline-line' })
          ),
          h('div', { className: 'cog-timeline-content' },
            h('div', { className: 'cog-timeline-head' },
              h('span', { className: 'cog-step-name' }, step.step),
              h('span', { className: 'cog-step-duration' }, step.duration_ms + 'ms')
            ),
            h('div', { className: 'cog-step-detail' },
              step.step === 'classify' && h('span', null, 'Source: ' + step.result),
              step.step === 'route' && h('span', null, 'Agents: ' + step.agents.join(', ')),
              step.step === 'plugin_data' && h('span', null, 'Plugins: ' + step.plugins.join(', ')),
              step.step === 'synthesize' && h('span', null, 'Tokens: ' + step.tokens)
            )
          )
        )
      )
    )
  );
}

function CognitionPanel({ scoring, decision, trace, message, onRefresh }) {
  const [collapsed, setCollapsed] = useState(false);

  return h('div', { className: 'cognition-panel' + (collapsed ? ' collapsed' : '') },
    h('div', { className: 'cognition-head' },
      h('div', { className: 'cognition-title' },
        h('svg', { viewBox: '0 0 24 24', width: 16, height: 16, className: 'cognition-icon' },
          h('path', {
            d: 'M12 2L2 7v10c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-10-5z',
            fill: 'none',
            stroke: 'currentColor',
            strokeWidth: '1.5'
          }),
          h('circle', { cx: 12, cy: 12, r: 3, fill: 'currentColor' })
        ),
        h('span', null, 'COGNITION')
      ),
      h('div', { className: 'cognition-controls' },
        onRefresh && h('button', { className: 'cog-btn', onClick: onRefresh },
          h('svg', { viewBox: '0 0 24 24', width: 12, height: 12 },
            h('path', {
              d: 'M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z',
              fill: 'currentColor'
            })
          )
        ),
        h('button', { className: 'cog-btn', onClick: () => setCollapsed(!collapsed) }, collapsed ? '▼' : '▲')
      )
    ),
    !collapsed && h('div', { className: 'cognition-body' },
      h(IntentClassification, { scoring, message }),
      h(RoutingDecision, { decision }),
      h(OrchestrationTrace, { trace })
    )
  );
}

Object.assign(window, { CognitionPanel, IntentClassification, RoutingDecision, OrchestrationTrace });
