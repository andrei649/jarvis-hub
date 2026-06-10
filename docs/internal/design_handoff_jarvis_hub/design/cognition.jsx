// cognition.jsx — v0.3 Cognition panel: intent classification, routing decision, orchestration trace
// Visualizes the "brain" of Jarvis: how it classifies intent, routes to agents, and orchestrates responses.

const { useState, useEffect, useMemo } = React;

// ─── Intent Classification ───────────────────────────────────────────────────
// Shows keywords matched with weight bars (simulated scoring)

function IntentClassification({ scoring, message }) {
  if (!scoring || scoring.length === 0) {
    return (
      <div className="cog-section">
        <div className="cog-section-head">
          <span className="cog-label">INTENT CLASSIFICATION</span>
          <span className="cog-status dim">NO MATCH</span>
        </div>
        <div className="cog-empty">No keywords matched. Routing to Jarvis (general).</div>
      </div>
    );
  }

  return (
    <div className="cog-section">
      <div className="cog-section-head">
        <span className="cog-label">INTENT CLASSIFICATION</span>
        <span className="cog-status active">{scoring.length} KEYWORDS</span>
      </div>
      <div className="cog-keyword-list">
        {scoring.map((s, i) => (
          <div key={i} className="cog-keyword-row">
            <div className="cog-keyword-head">
              <span className="cog-keyword">"{s.keyword}"</span>
              <span className="cog-category">{s.category}</span>
            </div>
            <div className="cog-weight-bar">
              <div
                className="cog-weight-fill"
                style={{ width: `${s.weight * 100}%` }}
              />
              <span className="cog-weight-val">{(s.weight * 100).toFixed(0)}%</span>
            </div>
            <div className="cog-agents">
              {s.agents.map((a, j) => (
                <span key={j} className="cog-agent-pill">{a}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Routing Decision ────────────────────────────────────────────────────────
// Shows the final routing decision with confidence bars and alternatives

function RoutingDecision({ decision }) {
  if (!decision) return null;

  const { source, confidence, agents_selected, alternatives, timing } = decision;

  return (
    <div className="cog-section">
      <div className="cog-section-head">
        <span className="cog-label">ROUTING DECISION</span>
        <span className="cog-status ok">{source.toUpperCase()}</span>
      </div>

      <div className="cog-decision-grid">
        <div className="cog-decision-col">
          <span className="cog-decision-label">Confidence</span>
          <div className="cog-confidence-bar">
            <div
              className="cog-confidence-fill"
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
          <span className="cog-confidence-val">{(confidence * 100).toFixed(0)}%</span>
        </div>

        <div className="cog-decision-col">
          <span className="cog-decision-label">Selected Agents</span>
          <div className="cog-selected-agents">
            {agents_selected.map((a, i) => (
              <span key={i} className="cog-agent-pill primary">{a}</span>
            ))}
          </div>
        </div>

        <div className="cog-decision-col">
          <span className="cog-decision-label">Timing</span>
          <span className="cog-timing">{timing.classify}ms classify · {timing.route}ms route</span>
        </div>
      </div>

      {alternatives && alternatives.length > 0 && (
        <div className="cog-alternatives">
          <span className="cog-alt-label">Alternatives:</span>
          {alternatives.map((alt, i) => (
            <div key={i} className="cog-alt-row">
              <span className="cog-alt-agent">{alt.agent}</span>
              <div className="cog-alt-bar">
                <div
                  className="cog-alt-fill"
                  style={{ width: `${alt.score * 100}%` }}
                />
              </div>
              <span className="cog-alt-score">{(alt.score * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Orchestration Trace ─────────────────────────────────────────────────────
// Timeline showing the execution steps (classify → route → plugin_data → synthesize)

function OrchestrationTrace({ trace }) {
  if (!trace || trace.length === 0) return null;

  const totalMs = trace.reduce((sum, t) => sum + t.duration_ms, 0);

  return (
    <div className="cog-section">
      <div className="cog-section-head">
        <span className="cog-label">ORCHESTRATION TRACE</span>
        <span className="cog-status ok">{totalMs}ms TOTAL</span>
      </div>

      <div className="cog-timeline">
        {trace.map((step, i) => (
          <div key={i} className="cog-timeline-row">
            <div className="cog-timeline-marker">
              <div className="cog-timeline-dot" />
              {i < trace.length - 1 && <div className="cog-timeline-line" />}
            </div>
            <div className="cog-timeline-content">
              <div className="cog-timeline-head">
                <span className="cog-step-name">{step.step}</span>
                <span className="cog-step-duration">{step.duration_ms}ms</span>
              </div>
              <div className="cog-step-detail">
                {step.step === 'classify' && (
                  <span>Source: {step.result}</span>
                )}
                {step.step === 'route' && (
                  <span>Agents: {step.agents.join(', ')}</span>
                )}
                {step.step === 'plugin_data' && (
                  <span>Plugins: {step.plugins.join(', ')}</span>
                )}
                {step.step === 'synthesize' && (
                  <span>Tokens: {step.tokens}</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Cognition Panel ────────────────────────────────────────────────────
// Container component that renders all three sections

function CognitionPanel({ scoring, decision, trace, message, onRefresh }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`cognition-panel ${collapsed ? 'collapsed' : ''}`}>
      <div className="cognition-head">
        <div className="cognition-title">
          <svg viewBox="0 0 24 24" width="16" height="16" className="cognition-icon">
            <path
              d="M12 2L2 7v10c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-10-5z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <circle cx="12" cy="12" r="3" fill="currentColor" />
          </svg>
          <span>COGNITION</span>
        </div>
        <div className="cognition-controls">
          {onRefresh && (
            <button className="cog-btn" onClick={onRefresh}>
              <svg viewBox="0 0 24 24" width="12" height="12">
                <path
                  d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"
                  fill="currentColor"
                />
              </svg>
            </button>
          )}
          <button className="cog-btn" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? '▼' : '▲'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="cognition-body">
          <IntentClassification scoring={scoring} message={message} />
          <RoutingDecision decision={decision} />
          <OrchestrationTrace trace={trace} />
        </div>
      )}
    </div>
  );
}

// Export to global scope
Object.assign(window, { CognitionPanel, IntentClassification, RoutingDecision, OrchestrationTrace });
