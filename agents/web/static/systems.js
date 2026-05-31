'use strict';
/* systems.js — v0.3 Systems panel: memory, plugins, learning, security & bench */

// useState, useEffect, useMemo, useCallback, h sunt deja definite global în components.js

const TABS = [
  { id: 'memory',   label: 'Memory' },
  { id: 'plugins',  label: 'Plugins' },
  { id: 'heartbeats', label: 'Heartbeats' },
  { id: 'learning', label: 'Learning' },
  { id: 'resilience', label: 'Resilience' },
  { id: 'oauth',    label: 'OAuth Status' },
  { id: 'oracle',   label: 'Oracle Tab' },
  { id: 'security', label: 'Security & Bench' },
];

function SystemsTabBar({ active, onChange }) {
  return h('div', { className: 'sys-tab-bar' },
    TABS.map(t => h('button', {
      key: t.id,
      className: 'sys-tab' + (active === t.id ? ' active' : ''),
      onClick: () => onChange(t.id)
    }, t.label))
  );
}

function MemoryTab({ data, onRefresh }) {
  const [selectedAgent, setSelectedAgent] = useState(null);

  if (!data) return h('div', { className: 'sys-loading' }, 'Loading memory stats...');

  const { sessions, vectors, knowledge_graph, agent_contexts } = data;

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-grid-2' },
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'SESSIONS'),
          h('button', { className: 'sys-refresh', onClick: onRefresh }, '↻')
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Total'),
          h('span', { className: 'sys-stat-val' }, sessions.total)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Active'),
          h('span', { className: 'sys-stat-val accent' }, sessions.active)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Current'),
          h('span', { className: 'sys-stat-val mono' }, sessions.current)
        )
      ),
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'VECTOR STORE')
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Stored'),
          h('span', { className: 'sys-stat-val' }, vectors.stored.toLocaleString())
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Dimension'),
          h('span', { className: 'sys-stat-val' }, vectors.dimension)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Backend'),
          h('span', { className: 'sys-stat-val accent' }, vectors.backend)
        ),
        h('div', { className: 'sys-gauge' },
          h('div', { className: 'sys-gauge-fill', style: { width: Math.min(vectors.stored / 50, 100) + '%' } }),
          h('span', { className: 'sys-gauge-label' }, vectors.stored + ' / 5000')
        )
      )
    ),
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'KNOWLEDGE GRAPH')
      ),
      h('div', { className: 'sys-grid-3' },
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Entities'),
          h('span', { className: 'sys-stat-val' }, knowledge_graph.entities)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Relations'),
          h('span', { className: 'sys-stat-val' }, knowledge_graph.relations)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Last Seed'),
          h('span', { className: 'sys-stat-val mono' }, knowledge_graph.last_seed)
        )
      )
    ),
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'AGENT CONTEXTS')
      ),
      h('div', { className: 'sys-agent-ctx-list' },
        Object.entries(agent_contexts).map(([agent, count]) =>
          h('div', {
            key: agent,
            className: 'sys-agent-ctx-row' + (selectedAgent === agent ? ' selected' : ''),
            onClick: () => setSelectedAgent(selectedAgent === agent ? null : agent)
          },
            h('span', { className: 'sys-agent-name' }, agent),
            h('span', { className: 'sys-agent-count' }, count + ' keys')
          )
        )
      )
    )
  );
}

function PluginsTab({ data, onToggle, onRefresh }) {
  if (!data || !data.plugins) return h('div', { className: 'sys-loading' }, 'Loading plugins...');

  const { plugins, total } = data;
  const enabledCount = plugins.filter(p => p.enabled).length;

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-plugins-head' },
      h('span', { className: 'sys-plugins-summary' }, enabledCount + '/' + total + ' enabled'),
      h('button', { className: 'sys-refresh', onClick: onRefresh }, '↻')
    ),
    h('div', { className: 'sys-plugins-grid' },
      plugins.map(p =>
        h('div', { key: p.id, className: 'sys-plugin-card' + (p.enabled ? ' enabled' : ' disabled') },
          h('div', { className: 'sys-plugin-head' },
            h('span', { className: 'sys-plugin-name' }, p.name),
            h('button', {
              className: 'sys-plugin-toggle' + (p.enabled ? ' on' : ' off'),
              onClick: () => onToggle && onToggle(p.id)
            }, h('span', { className: 'sys-toggle-knob' }))
          ),
          h('div', { className: 'sys-plugin-badges' },
            h('span', { className: 'sys-badge network-' + p.network_access.toLowerCase() }, p.network_access),
            h('span', { className: 'sys-badge scope-' + p.data_scope.toLowerCase() }, p.data_scope)
          ),
          p.allowed_domains.length > 0 && h('div', { className: 'sys-plugin-domains' },
            p.allowed_domains.map((d, i) => h('span', { key: i, className: 'sys-domain' }, d))
          ),
          h('div', { className: 'sys-plugin-agents' },
            h('span', { className: 'sys-plugin-agents-label' }, 'Agents:'),
            p.agents_served.map((a, i) => h('span', { key: i, className: 'sys-plugin-agent' }, a))
          )
        )
      )
    )
  );
}

function LearningTab({ data, onRefresh }) {
  if (!data) return h('div', { className: 'sys-loading' }, 'Loading learning data...');

  const { interactions_total, success_rate, prompt_optimizations, promotion_candidates, demotion_warnings } = data;

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-grid-2' },
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'INTERACTIONS'),
          h('button', { className: 'sys-refresh', onClick: onRefresh }, '↻')
        ),
        h('div', { className: 'sys-big-stat' },
          h('span', { className: 'sys-big-val' }, interactions_total),
          h('span', { className: 'sys-big-label' }, 'total records')
        )
      ),
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'SUCCESS RATE')
        ),
        h('div', { className: 'sys-big-stat' },
          h('span', { className: 'sys-big-val accent' }, (success_rate * 100).toFixed(1) + '%'),
          h('span', { className: 'sys-big-label' }, 'last 30 days')
        ),
        h('div', { className: 'sys-gauge' },
          h('div', { className: 'sys-gauge-fill success', style: { width: (success_rate * 100) + '%' } })
        )
      )
    ),
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'PROMPT OPTIMIZATIONS')
      ),
      prompt_optimizations.length === 0
        ? h('div', { className: 'sys-empty' }, 'No optimizations recorded yet.')
        : h('div', { className: 'sys-opt-list' },
            prompt_optimizations.map((opt, i) =>
              h('div', { key: i, className: 'sys-opt-row' },
                h('span', { className: 'sys-opt-agent' }, opt.agent),
                h('span', { className: 'sys-opt-improvement' }, opt.improvement),
                h('div', { className: 'sys-opt-diff' },
                  h('span', { className: 'sys-opt-before' }, opt.before),
                  h('span', { className: 'sys-opt-arrow' }, '→'),
                  h('span', { className: 'sys-opt-after' }, opt.after)
                )
              )
            )
          )
    ),
    h('div', { className: 'sys-grid-2' },
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'PROMOTION CANDIDATES')
        ),
        promotion_candidates.length === 0
          ? h('div', { className: 'sys-empty' }, 'None')
          : h('div', { className: 'sys-candidate-list' },
              promotion_candidates.map((c, i) =>
                h('div', { key: i, className: 'sys-candidate-row promote' },
                  h('span', { className: 'sys-candidate-name' }, c.agent),
                  h('span', { className: 'sys-candidate-detail' }, c.triggers + '/' + c.threshold + ' triggers')
                )
              )
            )
      ),
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'DEMOTION WARNINGS')
        ),
        demotion_warnings.length === 0
          ? h('div', { className: 'sys-empty' }, 'None')
          : h('div', { className: 'sys-candidate-list' },
              demotion_warnings.map((c, i) =>
                h('div', { key: i, className: 'sys-candidate-row demote' },
                  h('span', { className: 'sys-candidate-name' }, c.agent),
                  h('span', { className: 'sys-candidate-detail' }, c.uses + ' uses (threshold: ' + c.threshold + ')')
                )
              )
            )
      )
    )
  );
}

function HeartbeatsTab({ agents, heartbeatStatus, onStart, onStop, onRunNow, onRefresh }) {
  const [loading, setLoading] = useState({});

  const handleAction = async (action, agentId) => {
    setLoading(prev => ({ ...prev, [agentId]: action }));
    try {
      if (action === 'start') await onStart(agentId);
      else if (action === 'stop') await onStop(agentId);
      else if (action === 'run') await onRunNow(agentId);
    } finally {
      setLoading(prev => ({ ...prev, [agentId]: null }));
    }
  };

  const scheduledAgents = new Set(
    (heartbeatStatus?.heartbeats || []).map(h => h.agent_id)
  );

  const heartbeatAgents = agents.filter(a => a.has_heartbeat);

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'HEARTBEAT SCHEDULER'),
        h('div', { className: 'sys-card-actions' },
          h('span', { className: 'sys-status-badge ' + (heartbeatStatus?.scheduler_running ? 'active' : 'inactive') },
            heartbeatStatus?.scheduler_running ? 'RUNNING' : 'STOPPED'
          ),
          h('button', { className: 'sys-refresh', onClick: onRefresh }, '↻')
        )
      ),
      h('div', { className: 'sys-stat-row' },
        h('span', { className: 'sys-stat-key' }, 'Scheduled'),
        h('span', { className: 'sys-stat-val' }, scheduledAgents.size + ' / ' + heartbeatAgents.length)
      )
    ),
    h('div', { className: 'sys-heartbeats-list' },
      heartbeatAgents.map(agent => {
        const hb = (heartbeatStatus?.heartbeats || []).find(h => h.agent_id === agent.id);
        const isScheduled = !!hb;
        const isLoading = loading[agent.id];

        return h('div', { key: agent.id, className: 'sys-heartbeat-card' },
          h('div', { className: 'sys-heartbeat-head' },
            h('div', { className: 'sys-heartbeat-agent' },
              h('span', { className: 'sys-agent-name' }, agent.name),
              h('span', { className: 'sys-heartbeat-status ' + (isScheduled ? 'scheduled' : 'inactive') },
                isScheduled ? 'SCHEDULED' : 'INACTIVE'
              )
            ),
            h('div', { className: 'sys-heartbeat-actions' },
              h('button', {
                className: 'sys-btn sys-btn-primary',
                onClick: () => handleAction('run', agent.id),
                disabled: isLoading === 'run',
              }, isLoading === 'run' ? '...' : 'Run Now'),
              isScheduled
                ? h('button', {
                    className: 'sys-btn sys-btn-danger',
                    onClick: () => handleAction('stop', agent.id),
                    disabled: isLoading === 'stop',
                  }, isLoading === 'stop' ? '...' : 'Stop')
                : h('button', {
                    className: 'sys-btn sys-btn-success',
                    onClick: () => handleAction('start', agent.id),
                    disabled: isLoading === 'start',
                  }, isLoading === 'start' ? '...' : 'Start')
            )
          ),
          hb && h('div', { className: 'sys-heartbeat-info' },
            h('div', { className: 'sys-heartbeat-row' },
              h('span', { className: 'sys-heartbeat-label' }, 'Next run:'),
              h('span', { className: 'sys-heartbeat-value' },
                hb.next_run ? new Date(hb.next_run).toLocaleString() : 'N/A'
              )
            ),
            h('div', { className: 'sys-heartbeat-row' },
              h('span', { className: 'sys-heartbeat-label' }, 'Trigger:'),
              h('span', { className: 'sys-heartbeat-value sys-mono' }, hb.trigger)
            )
          )
        );
      })
    )
  );
}

function SecurityBenchTab({ security, bench, onRefresh }) {
  if (!security || !bench) return h('div', { className: 'sys-loading' }, 'Loading security & bench data...');

  const { guardrails, scanners, ssrf } = security;
  const { latency, throughput, by_agent } = bench;

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'GUARDRAILS'),
        h('button', { className: 'sys-refresh', onClick: onRefresh }, '↻')
      ),
      h('div', { className: 'sys-grid-3' },
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Mode'),
          h('span', { className: 'sys-stat-val guardrail-' + guardrails.mode.toLowerCase() }, guardrails.mode)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Redacted'),
          h('span', { className: 'sys-stat-val' }, guardrails.redact_count)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Blocked'),
          h('span', { className: 'sys-stat-val' }, guardrails.block_count)
        )
      )
    ),
    h('div', { className: 'sys-grid-2' },
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'SCANNERS')
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Secret patterns'),
          h('span', { className: 'sys-stat-val' }, scanners.secret.patterns)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Secret findings'),
          h('span', { className: 'sys-stat-val' + (scanners.secret.findings > 0 ? ' warn' : '') }, scanners.secret.findings)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'PII patterns'),
          h('span', { className: 'sys-stat-val' }, scanners.pii.patterns)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'PII findings'),
          h('span', { className: 'sys-stat-val' + (scanners.pii.findings > 0 ? ' warn' : '') }, scanners.pii.findings)
        )
      ),
      h('div', { className: 'sys-card' },
        h('div', { className: 'sys-card-head' },
          h('span', { className: 'sys-card-label' }, 'SSRF PROTECTION')
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Enabled'),
          h('span', { className: 'sys-stat-val' + (ssrf.enabled ? ' accent' : ' warn') }, ssrf.enabled ? 'YES' : 'NO')
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Blocked requests'),
          h('span', { className: 'sys-stat-val' }, ssrf.blocked_requests)
        ),
        h('div', { className: 'sys-stat-row' },
          h('span', { className: 'sys-stat-key' }, 'Max redirects'),
          h('span', { className: 'sys-stat-val' }, ssrf.max_redirects)
        )
      )
    ),
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'LATENCY BENCHMARK')
      ),
      h('div', { className: 'sys-bench-grid' },
        h('div', { className: 'sys-bench-col' },
          h('span', { className: 'sys-bench-label' }, 'P50'),
          h('span', { className: 'sys-bench-val' }, latency.p50 + 's'),
          h('div', { className: 'sys-bench-bar' },
            h('div', { className: 'sys-bench-fill p50', style: { width: (latency.p50 / latency.p99) * 100 + '%' } })
          )
        ),
        h('div', { className: 'sys-bench-col' },
          h('span', { className: 'sys-bench-label' }, 'P95'),
          h('span', { className: 'sys-bench-val' }, latency.p95 + 's'),
          h('div', { className: 'sys-bench-bar' },
            h('div', { className: 'sys-bench-fill p95', style: { width: (latency.p95 / latency.p99) * 100 + '%' } })
          )
        ),
        h('div', { className: 'sys-bench-col' },
          h('span', { className: 'sys-bench-label' }, 'P99'),
          h('span', { className: 'sys-bench-val' }, latency.p99 + 's'),
          h('div', { className: 'sys-bench-bar' },
            h('div', { className: 'sys-bench-fill p99', style: { width: '100%' } })
          )
        )
      ),
      h('div', { className: 'sys-bench-throughput' },
        h('span', { className: 'sys-stat-key' }, 'Throughput'),
        h('span', { className: 'sys-stat-val' }, throughput.rpm + ' rpm · ' + throughput.avg_tokens + ' avg tokens')
      )
    ),
    h('div', { className: 'sys-card wide' },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'LATENCY BY AGENT')
      ),
      h('div', { className: 'sys-agent-latency-list' },
        Object.entries(by_agent)
          .sort((a, b) => a[1] - b[1])
          .map(([agent, ms]) => {
            const maxMs = Math.max(...Object.values(by_agent));
            return h('div', { key: agent, className: 'sys-agent-latency-row' },
              h('span', { className: 'sys-agent-name' }, agent),
              h('div', { className: 'sys-latency-bar' },
                h('div', { className: 'sys-latency-fill', style: { width: (ms / maxMs) * 100 + '%' } })
              ),
              h('span', { className: 'sys-latency-val' }, ms + 's')
            );
          })
      )
    )
  );
}

function ResilienceTab({ data, onRefresh }) {
  if (!data) return h('div', { className: 'sys-loading' }, 'Loading resilience data...');

  const metrics = data.metrics || {};
  const breakers = data.circuit_breakers || {};
  const metricKeys = Object.keys(metrics);
  const breakerKeys = Object.keys(breakers);

  return h('div', { className: 'sys-tab-content' },
    metricKeys.length === 0 && breakerKeys.length === 0
      ? h('div', { className: 'sys-empty' }, 'No resilience data recorded yet. Data appears after API calls are made.')
      : null,

    metricKeys.length > 0 && h('div', { className: 'sys-card wide', style: { marginTop: 0 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'RETRY METRICS'),
        h('button', { className: 'sys-refresh', onClick: onRefresh }, '\u21BB')
      ),
      h('div', { className: 'sys-resilience-grid' },
        metricKeys.map(key =>
          h('div', { key, className: 'sys-resilience-card' },
            h('div', { className: 'sys-resilience-key' }, key),
            h('div', { className: 'sys-resilience-stats' },
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Success'),
                h('span', { className: 'sys-stat-val accent' }, metrics[key].success)
              ),
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Failure'),
                h('span', { className: 'sys-stat-val warn' }, metrics[key].failure)
              ),
              h('div', { className: 'sys-stat-row' },
                h('span', { className: 'sys-stat-key' }, 'Avg latency'),
                h('span', { className: 'sys-stat-val mono' }, metrics[key].avg_latency.toFixed(2) + 's')
              ),
              metrics[key].error_types && Object.keys(metrics[key].error_types).length > 0
                ? h('div', { className: 'sys-resilience-errors' },
                    Object.entries(metrics[key].error_types).map(([err, count]) =>
                      h('div', { key: err, className: 'sys-error-row' },
                        h('span', { className: 'sys-error-name' }, err),
                        h('span', { className: 'sys-error-count' }, count)
                      )
                    )
                  )
                : null
            )
          )
        )
      )
    ),

    breakerKeys.length > 0 && h('div', { className: 'sys-card wide', style: { marginTop: 12 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'CIRCUIT BREAKERS'),
        h('button', { className: 'sys-refresh', onClick: onRefresh }, '\u21BB')
      ),
      h('div', { className: 'sys-cb-grid' },
        breakerKeys.map(key =>
          h('div', {
            key,
            className: 'sys-cb-row ' + breakers[key].state,
          },
            h('div', { className: 'sys-cb-head' },
              h('span', { className: 'sys-cb-key' }, key),
              h('span', { className: 'sys-cb-state ' + breakers[key].state },
                breakers[key].state.toUpperCase()
              )
            ),
            h('div', { className: 'sys-cb-detail' },
              h('span', {}, 'Failures: ' + breakers[key].failure_count),
              breakers[key].last_failure_time
                ? h('span', { className: 'sys-cb-time' },
                    'Last: ' + new Date(breakers[key].last_failure_time * 1000).toLocaleString()
                  )
                : null
            )
          )
        )
      )
    )
  );
function OAuthTab({ data, onRefresh, onConnect, onRefreshService }) {
  if (!data) return h('div', { className: 'sys-loading' }, 'Loading OAuth status...');

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-card wide', style: { marginTop: 0 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'OAUTH EXTERNAL SERVICES'),
        h('button', { className: 'sys-refresh', onClick: onRefresh }, '\u21BB')
      ),
      h('div', { className: 'sys-cb-grid' },
        Object.entries(data).map(([key, svc]) =>
          h('div', {
            key,
            className: 'sys-cb-row ' + (svc.connected ? 'closed' : 'open'),
          },
            h('div', { className: 'sys-cb-head' },
              h('span', { className: 'sys-cb-key' }, svc.label),
              h('span', { className: 'sys-cb-state ' + (svc.connected ? 'closed' : 'open') },
                svc.connected ? 'CONNECTED' : 'DISCONNECTED'
              )
            ),
            h('div', { className: 'sys-heartbeat-actions', style: { marginTop: '8px', display: 'flex', gap: '8px' } },
              svc.connected
                ? h('button', {
                    className: 'sys-btn sys-btn-primary',
                    onClick: () => onRefreshService(key),
                  }, 'Force Refresh')
                : h('button', {
                    className: 'sys-btn sys-btn-success',
                    onClick: () => onConnect(svc.auth_url),
                  }, 'Connect')
            )
          )
        )
      )
    )
  );
}

function OracleTab({ data, conflicts, onRefresh, onSync, onResolve }) {
  if (!data) return h('div', { className: 'sys-loading' }, 'Loading Oracle status...');

  return h('div', { className: 'sys-tab-content' },
    h('div', { className: 'sys-card wide', style: { marginTop: 0 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'ORACLE GITHUB INTEGRATION'),
        h('div', { className: 'sys-card-actions', style: { display: 'flex', gap: '10px', alignItems: 'center' } },
          h('span', { className: 'sys-status-badge ' + (data.sync_active ? 'active' : 'inactive') },
            data.sync_active ? 'SYNC ACTIVE' : 'IDLE'
          ),
          h('button', { className: 'sys-refresh', onClick: onRefresh }, '\u21BB')
        )
      ),
      h('div', { className: 'sys-stat-row' },
        h('span', { className: 'sys-stat-key' }, 'Last Succeeded Sync'),
        h('span', { className: 'sys-stat-val' }, data.last_sync ? new Date(data.last_sync * 1000).toLocaleString() : 'Never')
      ),
      h('div', { className: 'sys-stat-row' },
        h('span', { className: 'sys-stat-key' }, 'Active Branch'),
        h('span', { className: 'sys-stat-val mono' }, data.branch || 'main')
      ),
      h('div', { className: 'sys-stat-row' },
        h('span', { className: 'sys-stat-key' }, 'Local Commit'),
        h('span', { className: 'sys-stat-val mono' }, (data.commit || 'N/A').slice(0, 7))
      ),
      h('div', { className: 'sys-heartbeat-actions', style: { marginTop: '12px' } },
        h('button', {
          className: 'sys-btn sys-btn-primary',
          onClick: onSync,
          disabled: data.sync_active
        }, data.sync_active ? 'Syncing...' : 'Sync Now')
      )
    ),
    h('div', { className: 'sys-card wide', style: { marginTop: 12 } },
      h('div', { className: 'sys-card-head' },
        h('span', { className: 'sys-card-label' }, 'LIVE CODE CONFLICTS')
      ),
      !conflicts || conflicts.length === 0
        ? h('div', { className: 'sys-empty' }, 'No unresolved code conflicts detected. Local workspace is fully in sync.')
        : h('div', { className: 'sys-candidate-list' },
            conflicts.map((c, i) =>
              h('div', { key: i, className: 'sys-candidate-row demote' },
                h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px' } },
                  h('span', { className: 'sys-candidate-name', style: { textTransform: 'none' } }, c.file),
                  h('span', { style: { fontSize: '10px', color: 'var(--text-dim)' } }, 'Reason: ' + c.reason)
                ),
                h('button', {
                  className: 'sys-btn sys-btn-danger',
                  onClick: () => onResolve(c.id)
                }, 'Resolve')
              )
            )
          )
    )
  );
}

function SystemsPanel({ agents, onRefresh, onPluginToggle }) {
  const [activeTab, setActiveTab] = useState('memory');
  const [collapsed, setCollapsed] = useState(false);
  const [heartbeatStatus, setHeartbeatStatus] = useState(null);
  const [resilience, setResilience] = useState(null);
  const [memoryData, setMemoryData] = useState(null);
  const [pluginsData, setPluginsData] = useState(null);
  const [learningData, setLearningData] = useState(null);
  const [securityData, setSecurityData] = useState(null);
  const [benchData, setBenchData] = useState(null);
  const [oauthData, setOauthData] = useState(null);
  const [oracleData, setOracleData] = useState(null);
  const [oracleConflicts, setOracleConflicts] = useState([]);

  const fetchHeartbeatStatus = useCallback(async () => {
    try {
      const res = await fetch('/heartbeat/status');
      const data = await res.json();
      setHeartbeatStatus(data);
    } catch (err) {
      console.error('Failed to fetch heartbeat status:', err);
    }
  }, []);

  const fetchResilience = useCallback(async () => {
    try {
      const res = await fetch('/api/resilience');
      const data = await res.json();
      setResilience(data);
    } catch (err) {
      console.error('Failed to fetch resilience:', err);
    }
  }, []);

  const fetchMemory = useCallback(async () => {
    try {
      const res = await fetch('/memory/stats');
      setMemoryData(await res.json());
    } catch (err) { console.error('Failed to fetch memory:', err); }
  }, []);

  const fetchPlugins = useCallback(async () => {
    try {
      const res = await fetch('/plugins');
      setPluginsData(await res.json());
    } catch (err) { console.error('Failed to fetch plugins:', err); }
  }, []);

  const fetchLearning = useCallback(async () => {
    try {
      const res = await fetch('/learning/stats');
      setLearningData(await res.json());
    } catch (err) { console.error('Failed to fetch learning:', err); }
  }, []);

  const fetchSecurity = useCallback(async () => {
    try {
      const res = await fetch('/security/status');
      setSecurityData(await res.json());
    } catch (err) { console.error('Failed to fetch security:', err); }
  }, []);

  const fetchBench = useCallback(async () => {
    try {
      const res = await fetch('/bench/stats');
      setBenchData(await res.json());
    } catch (err) { console.error('Failed to fetch bench:', err); }
  }, []);

  const fetchOauth = useCallback(async () => {
    try {
      const res = await fetch('/api/oauth/status');
      setOauthData(await res.json());
    } catch (err) { console.error('Failed to fetch OAuth status:', err); }
  }, []);

  const fetchOracle = useCallback(async () => {
    try {
      const res = await fetch('/api/oracle/status');
      setOracleData(await res.json());
    } catch (err) { console.error('Failed to fetch Oracle status:', err); }
  }, []);

  const fetchOracleConflicts = useCallback(async () => {
    try {
      const res = await fetch('/api/oracle/conflicts');
      const d = await res.json();
      setOracleConflicts(d.conflicts || []);
    } catch (err) { console.error('Failed to fetch Oracle conflicts:', err); }
  }, []);

  useEffect(() => {
    fetchHeartbeatStatus();
  }, [fetchHeartbeatStatus]);

  useEffect(() => {
    fetchResilience();
  }, [fetchResilience]);

  useEffect(() => { fetchMemory(); }, [fetchMemory]);
  useEffect(() => {
    fetchPlugins();
    const handler = () => fetchPlugins();
    window.addEventListener('jarvis:plugins_updated', handler);
    return () => window.removeEventListener('jarvis:plugins_updated', handler);
  }, [fetchPlugins]);
  useEffect(() => { fetchLearning(); }, [fetchLearning]);
  useEffect(() => { fetchOauth(); }, [fetchOauth]);
  useEffect(() => { fetchOracle(); fetchOracleConflicts(); }, [fetchOracle, fetchOracleConflicts]);
  useEffect(() => { fetchSecurity(); }, [fetchSecurity]);
  useEffect(() => { fetchBench(); }, [fetchBench]);

  const handleRefresh = useCallback(() => {
    if (onRefresh) onRefresh(activeTab);
    if (activeTab === 'heartbeats') fetchHeartbeatStatus();
    if (activeTab === 'resilience') fetchResilience();
    if (activeTab === 'memory') fetchMemory();
    if (activeTab === 'plugins') fetchPlugins();
    if (activeTab === 'learning') fetchLearning();
    if (activeTab === 'oauth') fetchOauth();
    if (activeTab === 'oracle') { fetchOracle(); fetchOracleConflicts(); }
    if (activeTab === 'security') { fetchSecurity(); fetchBench(); }
  }, [activeTab, onRefresh, fetchHeartbeatStatus, fetchResilience, fetchMemory, fetchPlugins, fetchLearning, fetchSecurity, fetchBench, fetchOauth, fetchOracle, fetchOracleConflicts]);

  const handleOAuthRefreshService = async (service) => {
    try {
      await fetch(`/api/oauth/refresh?service=${service}`, { method: 'POST' });
      await fetchOauth();
    } catch (err) { console.error('Failed to refresh service token:', err); }
  };

  const handleOracleSync = async () => {
    try {
      setOracleData(prev => prev ? { ...prev, sync_active: true } : null);
      await fetch('/api/oracle/sync', { method: 'POST' });
      await fetchOracle();
    } catch (err) { console.error('Failed to sync Oracle:', err); }
  };

  const handleOracleResolve = async () => {
    try {
      await fetch('/api/oracle/conflicts/resolve', { method: 'POST' });
      await fetchOracleConflicts();
    } catch (err) { console.error('Failed to resolve conflicts:', err); }
  };

  const handleHeartbeatStart = async (agentId) => {
    try {
      const res = await fetch(`/heartbeat/${agentId}/start`, { method: 'POST' });
      if (res.ok) {
        await fetchHeartbeatStatus();
      } else {
        console.error('Failed to start heartbeat');
      }
    } catch (err) {
      console.error('Error starting heartbeat:', err);
    }
  };

  const handleHeartbeatStop = async (agentId) => {
    try {
      const res = await fetch(`/heartbeat/${agentId}/stop`, { method: 'POST' });
      if (res.ok) {
        await fetchHeartbeatStatus();
      } else {
        console.error('Failed to stop heartbeat');
      }
    } catch (err) {
      console.error('Error stopping heartbeat:', err);
    }
  };

  const handleHeartbeatRunNow = async (agentId) => {
    try {
      const res = await fetch(`/heartbeat/${agentId}/run`, { method: 'POST' });
      if (res.ok) {
        await fetchHeartbeatStatus();
      } else {
        console.error('Failed to run heartbeat');
      }
    } catch (err) {
      console.error('Error running heartbeat:', err);
    }
  };

  return h('div', { className: 'systems-panel' + (collapsed ? ' collapsed' : '') },
    h('div', { className: 'systems-head' },
      h('div', { className: 'systems-title' },
        h('svg', { viewBox: '0 0 24 24', width: 16, height: 16, className: 'systems-icon' },
          h('path', {
            d: 'M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.488.488 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1115.6 12 3.611 3.611 0 0112 15.6z',
            fill: 'none',
            stroke: 'currentColor',
            strokeWidth: '1.5'
          })
        ),
        h('span', null, 'SYSTEMS')
      ),
      h('div', { className: 'systems-controls' },
        h('button', { className: 'sys-btn', onClick: () => setCollapsed(!collapsed) }, collapsed ? '▼' : '▲')
      )
    ),
    !collapsed && h('div', { className: 'systems-body' },
      h(SystemsTabBar, { active: activeTab, onChange: setActiveTab }),
      activeTab === 'memory' && h(MemoryTab, { data: memoryData, onRefresh: handleRefresh }),
      activeTab === 'plugins' && h(PluginsTab, { data: pluginsData, onToggle: onPluginToggle, onRefresh: handleRefresh }),
      activeTab === 'heartbeats' && h(HeartbeatsTab, {
        agents: agents || [],
        heartbeatStatus,
        onStart: handleHeartbeatStart,
        onStop: handleHeartbeatStop,
        onRunNow: handleHeartbeatRunNow,
        onRefresh: fetchHeartbeatStatus,
      }),
      activeTab === 'learning' && h(LearningTab, { data: learningData, onRefresh: handleRefresh }),
      activeTab === 'resilience' && h(ResilienceTab, { data: resilience, onRefresh: handleRefresh }),
      activeTab === 'oauth' && h(OAuthTab, {
        data: oauthData,
        onRefresh: fetchOauth,
        onConnect: (url) => window.open(url, '_blank'),
        onRefreshService: handleOAuthRefreshService,
      }),
      activeTab === 'oracle' && h(OracleTab, {
        data: oracleData,
        conflicts: oracleConflicts,
        onRefresh: () => { fetchOracle(); fetchOracleConflicts(); },
        onSync: handleOracleSync,
        onResolve: handleOracleResolve,
      }),
      activeTab === 'security' && h(SecurityBenchTab, { security: securityData, bench: benchData, onRefresh: handleRefresh })
    )
  );
}

Object.assign(window, { SystemsPanel, SystemsTabBar, MemoryTab, PluginsTab, HeartbeatsTab, LearningTab, SecurityBenchTab, ResilienceTab, OAuthTab, OracleTab });
