// systems.jsx — v0.3 Systems panel: memory, plugins, learning, security & bench
// Deep system internals with 4 tabs, each fetching from dedicated endpoints.

const { useState, useEffect, useMemo, useCallback } = React;

// ─── Tab Bar ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'memory',   label: 'Memory' },
  { id: 'plugins',  label: 'Plugins' },
  { id: 'learning', label: 'Learning' },
  { id: 'security', label: 'Security & Bench' },
];

function SystemsTabBar({ active, onChange }) {
  return (
    <div className="sys-tab-bar">
      {TABS.map(t => (
        <button
          key={t.id}
          className={`sys-tab ${active === t.id ? 'active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ─── Memory Tab ──────────────────────────────────────────────────────────────
// Sessions, vectors, knowledge graph, agent contexts

function MemoryTab({ data, onRefresh }) {
  const [selectedAgent, setSelectedAgent] = useState(null);

  if (!data) {
    return <div className="sys-loading">Loading memory stats...</div>;
  }

  const { sessions, vectors, knowledge_graph, agent_contexts } = data;

  return (
    <div className="sys-tab-content">
      <div className="sys-grid-2">
        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">SESSIONS</span>
            <button className="sys-refresh" onClick={onRefresh}>↻</button>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Total</span>
            <span className="sys-stat-val">{sessions.total}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Active</span>
            <span className="sys-stat-val accent">{sessions.active}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Current</span>
            <span className="sys-stat-val mono">{sessions.current}</span>
          </div>
        </div>

        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">VECTOR STORE</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Stored</span>
            <span className="sys-stat-val">{vectors.stored.toLocaleString()}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Dimension</span>
            <span className="sys-stat-val">{vectors.dimension}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Backend</span>
            <span className="sys-stat-val accent">{vectors.backend}</span>
          </div>
          <div className="sys-gauge">
            <div className="sys-gauge-fill" style={{ width: `${Math.min(vectors.stored / 50, 100)}%` }} />
            <span className="sys-gauge-label">{vectors.stored} / 5000</span>
          </div>
        </div>
      </div>

      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">KNOWLEDGE GRAPH</span>
        </div>
        <div className="sys-grid-3">
          <div className="sys-stat-row">
            <span className="sys-stat-key">Entities</span>
            <span className="sys-stat-val">{knowledge_graph.entities}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Relations</span>
            <span className="sys-stat-val">{knowledge_graph.relations}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Last Seed</span>
            <span className="sys-stat-val mono">{knowledge_graph.last_seed}</span>
          </div>
        </div>
      </div>

      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">AGENT CONTEXTS</span>
        </div>
        <div className="sys-agent-ctx-list">
          {Object.entries(agent_contexts).map(([agent, count]) => (
            <div
              key={agent}
              className={`sys-agent-ctx-row ${selectedAgent === agent ? 'selected' : ''}`}
              onClick={() => setSelectedAgent(selectedAgent === agent ? null : agent)}
            >
              <span className="sys-agent-name">{agent}</span>
              <span className="sys-agent-count">{count} keys</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Plugins Tab ─────────────────────────────────────────────────────────────
// Grid of 11 plugins with enable/disable toggle

function PluginsTab({ data, onToggle, onRefresh }) {
  if (!data || !data.plugins) {
    return <div className="sys-loading">Loading plugins...</div>;
  }

  const { plugins, total } = data;
  const enabledCount = plugins.filter(p => p.enabled).length;

  return (
    <div className="sys-tab-content">
      <div className="sys-plugins-head">
        <span className="sys-plugins-summary">{enabledCount}/{total} enabled</span>
        <button className="sys-refresh" onClick={onRefresh}>↻</button>
      </div>

      <div className="sys-plugins-grid">
        {plugins.map(p => (
          <div key={p.id} className={`sys-plugin-card ${p.enabled ? 'enabled' : 'disabled'}`}>
            <div className="sys-plugin-head">
              <span className="sys-plugin-name">{p.name}</span>
              <button
                className={`sys-plugin-toggle ${p.enabled ? 'on' : 'off'}`}
                onClick={() => onToggle && onToggle(p.id)}
              >
                <span className="sys-toggle-knob" />
              </button>
            </div>

            <div className="sys-plugin-badges">
              <span className={`sys-badge network-${p.network_access.toLowerCase()}`}>
                {p.network_access}
              </span>
              <span className={`sys-badge scope-${p.data_scope.toLowerCase()}`}>
                {p.data_scope}
              </span>
            </div>

            {p.allowed_domains.length > 0 && (
              <div className="sys-plugin-domains">
                {p.allowed_domains.map((d, i) => (
                  <span key={i} className="sys-domain">{d}</span>
                ))}
              </div>
            )}

            <div className="sys-plugin-agents">
              <span className="sys-plugin-agents-label">Agents:</span>
              {p.agents_served.map((a, i) => (
                <span key={i} className="sys-plugin-agent">{a}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Learning Tab ────────────────────────────────────────────────────────────
// Interaction records, prompt optimizations, promotion/demotion candidates

function LearningTab({ data, onRefresh }) {
  if (!data) {
    return <div className="sys-loading">Loading learning data...</div>;
  }

  const { interactions_total, success_rate, prompt_optimizations, promotion_candidates, demotion_warnings } = data;

  return (
    <div className="sys-tab-content">
      <div className="sys-grid-2">
        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">INTERACTIONS</span>
            <button className="sys-refresh" onClick={onRefresh}>↻</button>
          </div>
          <div className="sys-big-stat">
            <span className="sys-big-val">{interactions_total}</span>
            <span className="sys-big-label">total records</span>
          </div>
        </div>

        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">SUCCESS RATE</span>
          </div>
          <div className="sys-big-stat">
            <span className="sys-big-val accent">{(success_rate * 100).toFixed(1)}%</span>
            <span className="sys-big-label">last 30 days</span>
          </div>
          <div className="sys-gauge">
            <div className="sys-gauge-fill success" style={{ width: `${success_rate * 100}%` }} />
          </div>
        </div>
      </div>

      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">PROMPT OPTIMIZATIONS</span>
        </div>
        {prompt_optimizations.length === 0 ? (
          <div className="sys-empty">No optimizations recorded yet.</div>
        ) : (
          <div className="sys-opt-list">
            {prompt_optimizations.map((opt, i) => (
              <div key={i} className="sys-opt-row">
                <span className="sys-opt-agent">{opt.agent}</span>
                <span className="sys-opt-improvement">{opt.improvement}</span>
                <div className="sys-opt-diff">
                  <span className="sys-opt-before">{opt.before}</span>
                  <span className="sys-opt-arrow">→</span>
                  <span className="sys-opt-after">{opt.after}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="sys-grid-2">
        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">PROMOTION CANDIDATES</span>
          </div>
          {promotion_candidates.length === 0 ? (
            <div className="sys-empty">None</div>
          ) : (
            <div className="sys-candidate-list">
              {promotion_candidates.map((c, i) => (
                <div key={i} className="sys-candidate-row promote">
                  <span className="sys-candidate-name">{c.agent}</span>
                  <span className="sys-candidate-detail">{c.triggers}/{c.threshold} triggers</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">DEMOTION WARNINGS</span>
          </div>
          {demotion_warnings.length === 0 ? (
            <div className="sys-empty">None</div>
          ) : (
            <div className="sys-candidate-list">
              {demotion_warnings.map((c, i) => (
                <div key={i} className="sys-candidate-row demote">
                  <span className="sys-candidate-name">{c.agent}</span>
                  <span className="sys-candidate-detail">{c.uses} uses (threshold: {c.threshold})</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Security & Bench Tab ────────────────────────────────────────────────────
// Guardrails, scanners, SSRF, latency benchmarks

function SecurityBenchTab({ security, bench, onRefresh }) {
  if (!security || !bench) {
    return <div className="sys-loading">Loading security & bench data...</div>;
  }

  const { guardrails, scanners, ssrf } = security;
  const { latency, throughput, by_agent } = bench;

  return (
    <div className="sys-tab-content">
      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">GUARDRAILS</span>
          <button className="sys-refresh" onClick={onRefresh}>↻</button>
        </div>
        <div className="sys-grid-3">
          <div className="sys-stat-row">
            <span className="sys-stat-key">Mode</span>
            <span className={`sys-stat-val guardrail-${guardrails.mode.toLowerCase()}`}>{guardrails.mode}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Redacted</span>
            <span className="sys-stat-val">{guardrails.redact_count}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Blocked</span>
            <span className="sys-stat-val">{guardrails.block_count}</span>
          </div>
        </div>
      </div>

      <div className="sys-grid-2">
        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">SCANNERS</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Secret patterns</span>
            <span className="sys-stat-val">{scanners.secret.patterns}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Secret findings</span>
            <span className={`sys-stat-val ${scanners.secret.findings > 0 ? 'warn' : ''}`}>
              {scanners.secret.findings}
            </span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">PII patterns</span>
            <span className="sys-stat-val">{scanners.pii.patterns}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">PII findings</span>
            <span className={`sys-stat-val ${scanners.pii.findings > 0 ? 'warn' : ''}`}>
              {scanners.pii.findings}
            </span>
          </div>
        </div>

        <div className="sys-card">
          <div className="sys-card-head">
            <span className="sys-card-label">SSRF PROTECTION</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Enabled</span>
            <span className={`sys-stat-val ${ssrf.enabled ? 'accent' : 'warn'}`}>
              {ssrf.enabled ? 'YES' : 'NO'}
            </span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Blocked requests</span>
            <span className="sys-stat-val">{ssrf.blocked_requests}</span>
          </div>
          <div className="sys-stat-row">
            <span className="sys-stat-key">Max redirects</span>
            <span className="sys-stat-val">{ssrf.max_redirects}</span>
          </div>
        </div>
      </div>

      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">LATENCY BENCHMARK</span>
        </div>
        <div className="sys-bench-grid">
          <div className="sys-bench-col">
            <span className="sys-bench-label">P50</span>
            <span className="sys-bench-val">{latency.p50}s</span>
            <div className="sys-bench-bar">
              <div className="sys-bench-fill p50" style={{ width: `${(latency.p50 / latency.p99) * 100}%` }} />
            </div>
          </div>
          <div className="sys-bench-col">
            <span className="sys-bench-label">P95</span>
            <span className="sys-bench-val">{latency.p95}s</span>
            <div className="sys-bench-bar">
              <div className="sys-bench-fill p95" style={{ width: `${(latency.p95 / latency.p99) * 100}%` }} />
            </div>
          </div>
          <div className="sys-bench-col">
            <span className="sys-bench-label">P99</span>
            <span className="sys-bench-val">{latency.p99}s</span>
            <div className="sys-bench-bar">
              <div className="sys-bench-fill p99" style={{ width: `100%` }} />
            </div>
          </div>
        </div>
        <div className="sys-bench-throughput">
          <span className="sys-stat-key">Throughput</span>
          <span className="sys-stat-val">{throughput.rpm} rpm · {throughput.avg_tokens} avg tokens</span>
        </div>
      </div>

      <div className="sys-card wide">
        <div className="sys-card-head">
          <span className="sys-card-label">LATENCY BY AGENT</span>
        </div>
        <div className="sys-agent-latency-list">
          {Object.entries(by_agent)
            .sort((a, b) => a[1] - b[1])
            .map(([agent, ms]) => {
              const maxMs = Math.max(...Object.values(by_agent));
              return (
                <div key={agent} className="sys-agent-latency-row">
                  <span className="sys-agent-name">{agent}</span>
                  <div className="sys-latency-bar">
                    <div
                      className="sys-latency-fill"
                      style={{ width: `${(ms / maxMs) * 100}%` }}
                    />
                  </div>
                  <span className="sys-latency-val">{ms}s</span>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

// ─── Main Systems Panel ──────────────────────────────────────────────────────
// Container with tab switching

function SystemsPanel({ memory, plugins, learning, security, bench, onRefresh, onPluginToggle }) {
  const [activeTab, setActiveTab] = useState('memory');
  const [collapsed, setCollapsed] = useState(false);

  const handleRefresh = useCallback(() => {
    if (onRefresh) onRefresh(activeTab);
  }, [activeTab, onRefresh]);

  return (
    <div className={`systems-panel ${collapsed ? 'collapsed' : ''}`}>
      <div className="systems-head">
        <div className="systems-title">
          <svg viewBox="0 0 24 24" width="16" height="16" className="systems-icon">
            <path
              d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.488.488 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1115.6 12 3.611 3.611 0 0112 15.6z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <span>SYSTEMS</span>
        </div>
        <div className="systems-controls">
          <button className="sys-btn" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? '▼' : '▲'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="systems-body">
          <SystemsTabBar active={activeTab} onChange={setActiveTab} />

          {activeTab === 'memory' && (
            <MemoryTab data={memory} onRefresh={handleRefresh} />
          )}
          {activeTab === 'plugins' && (
            <PluginsTab data={plugins} onToggle={onPluginToggle} onRefresh={handleRefresh} />
          )}
          {activeTab === 'learning' && (
            <LearningTab data={learning} onRefresh={handleRefresh} />
          )}
          {activeTab === 'security' && (
            <SecurityBenchTab security={security} bench={bench} onRefresh={handleRefresh} />
          )}
        </div>
      )}
    </div>
  );
}

// Export to global scope
Object.assign(window, {
  SystemsPanel,
  SystemsTabBar,
  MemoryTab,
  PluginsTab,
  LearningTab,
  SecurityBenchTab,
});
