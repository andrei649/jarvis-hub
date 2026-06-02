'use strict';
/*
 * observability.js — H9.2 Trace Explorer HUD module.
 *
 * Exports: ObservabilityPanel (via window.ObservabilityPanel)
 *
 * Vanilla React.createElement, no JSX, no new deps.
 * Uses the same h / useState / useEffect / useCallback / useRef globals
 * set up by components.js.
 *
 * Tab-registration convention (same as systems.js / cognition.js):
 *   Object.assign(window, { ObservabilityPanel })
 *
 * To mount from app.js (caller side — do NOT edit app.js yourself):
 *   h(window.ObservabilityPanel, {})
 * Or from a button toggle, mirroring showCognition / showSystems in app.js:
 *   showObservability && h(ObservabilityPanel, {})
 */

/* ── helpers ─────────────────────────────────────────────────── */

function _fmtTs(ts) {
  if (!ts) return '—';
  try {
    var d = new Date(ts * 1000);
    var pad = function (n) { return String(n).padStart(2, '0'); };
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  } catch (_) { return '—'; }
}

function _fmtMs(ms) {
  if (ms === undefined || ms === null) return '—';
  if (ms >= 1000) return (ms / 1000).toFixed(2) + 's';
  return ms + 'ms';
}

function _agentList(agents) {
  if (!agents || !agents.length) return '—';
  return agents.join(', ');
}

/* ── TraceRow (table row) ─────────────────────────────────────── */

function TraceRow({ trace, onSelect, selected }) {
  var okClass = trace.ok ? 'obs-ok' : 'obs-err';
  return h('tr', {
    className: 'obs-trace-row' + (selected ? ' selected' : ''),
    onClick: function () { onSelect(trace); },
    style: { cursor: 'pointer' },
  },
    h('td', { className: 'obs-td obs-ts' }, _fmtTs(trace.ts)),
    h('td', { className: 'obs-td obs-channel' }, trace.channel || '—'),
    h('td', { className: 'obs-td obs-route' }, trace.route || '—'),
    h('td', { className: 'obs-td obs-agents' }, _agentList(trace.agents)),
    h('td', { className: 'obs-td obs-model mono' },
      (trace.model || '').split('/').pop() || '—'
    ),
    h('td', { className: 'obs-td obs-total-ms' }, _fmtMs(trace.total_ms)),
    h('td', { className: 'obs-td obs-tokens' },
      h('span', { className: 'obs-tok-in' }, trace.tokens_in || 0),
      ' / ',
      h('span', { className: 'obs-tok-out' }, trace.tokens_out || 0)
    ),
    h('td', { className: 'obs-td' },
      h('span', { className: 'obs-status-dot ' + okClass },
        trace.ok ? 'OK' : 'ERR'
      )
    )
  );
}

/* ── TimingBar ────────────────────────────────────────────────── */

function TimingBar({ label, ms, total }) {
  var pct = total > 0 ? Math.min(100, Math.round((ms / total) * 100)) : 0;
  return h('div', { className: 'obs-timing-row' },
    h('div', { className: 'obs-timing-label' }, label),
    h('div', { className: 'obs-timing-track' },
      h('div', { className: 'obs-timing-fill', style: { width: pct + '%' } })
    ),
    h('div', { className: 'obs-timing-val' }, _fmtMs(ms))
  );
}

/* ── TraceDetail ──────────────────────────────────────────────── */

function TraceDetail({ trace, onClose }) {
  if (!trace) return null;
  var t = trace.timings || {};
  var total = t.total_ms || (
    (t.classify || 0) + (t.route || 0) + (t.plugin || 0) + (t.synthesize || 0)
  );

  return h('div', { className: 'obs-detail' },
    h('div', { className: 'obs-detail-head' },
      h('span', { className: 'obs-detail-title' }, 'TRACE DETAIL'),
      h('button', { className: 'obs-close-btn', onClick: onClose }, '✕')
    ),
    h('div', { className: 'obs-detail-body' },
      h('div', { className: 'obs-detail-section' },
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'ID'), h('span', { className: 'obs-val mono' }, trace.id)
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Time'), h('span', { className: 'obs-val' }, _fmtTs(trace.ts))
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Channel'), h('span', { className: 'obs-val' }, trace.channel || '—')
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Intent'), h('span', { className: 'obs-val' }, trace.intent || '—')
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Route'), h('span', { className: 'obs-val' }, trace.route || '—')
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Agents'), h('span', { className: 'obs-val' }, _agentList(trace.agents))
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Model'), h('span', { className: 'obs-val mono' }, trace.model || '—')
        ),
        h('div', { className: 'obs-detail-row' },
          h('span', { className: 'obs-key' }, 'Tokens in/out'),
          h('span', { className: 'obs-val' }, (trace.tokens_in || 0) + ' / ' + (trace.tokens_out || 0))
        ),
      ),
      h('div', { className: 'obs-detail-section' },
        h('div', { className: 'obs-section-label' }, 'PREVIEW'),
        h('div', { className: 'obs-preview' }, trace.text_preview || '(empty)')
      ),
      h('div', { className: 'obs-detail-section' },
        h('div', { className: 'obs-section-label' }, 'TIMINGS — ' + _fmtMs(total) + ' total'),
        h(TimingBar, { label: 'classify', ms: t.classify || 0, total: total }),
        h(TimingBar, { label: 'route',    ms: t.route    || 0, total: total }),
        h(TimingBar, { label: 'plugin',   ms: t.plugin   || 0, total: total }),
        h(TimingBar, { label: 'synthesize', ms: t.synthesize || 0, total: total })
      )
    )
  );
}

/* ── ObservabilityPanel (main export) ─────────────────────────── */

function ObservabilityPanel() {
  var _traces = useState([]);
  var traces = _traces[0], setTraces = _traces[1];

  var _selected = useState(null);
  var selected = _selected[0], setSelected = _selected[1];

  var _detail = useState(null);
  var detail = _detail[0], setDetail = _detail[1];

  var _loading = useState(false);
  var loading = _loading[0], setLoading = _loading[1];

  var _error = useState(null);
  var error = _error[0], setError = _error[1];

  var _collapsed = useState(false);
  var collapsed = _collapsed[0], setCollapsed = _collapsed[1];

  var limitRef = useRef(50);

  var fetchTraces = useCallback(async function () {
    setLoading(true);
    setError(null);
    try {
      var r = await fetch('/api/traces?limit=' + limitRef.current);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var d = await r.json();
      setTraces(d.traces || []);
    } catch (e) {
      setError('Failed to load traces: ' + e.message);
    }
    setLoading(false);
  }, []);

  var fetchDetail = useCallback(async function (trace) {
    setSelected(trace);
    try {
      var r = await fetch('/api/traces/' + encodeURIComponent(trace.id));
      if (!r.ok) { setDetail(trace); return; }
      var d = await r.json();
      setDetail(d);
    } catch (_) {
      setDetail(trace);
    }
  }, []);

  var clearTraces = useCallback(async function () {
    try {
      await fetch('/api/traces/clear', { method: 'POST' });
      setTraces([]);
      setSelected(null);
      setDetail(null);
    } catch (e) {
      setError('Clear failed: ' + e.message);
    }
  }, []);

  useEffect(function () {
    fetchTraces();
  }, [fetchTraces]);

  return h('div', { className: 'obs-panel' + (collapsed ? ' collapsed' : '') },
    /* ── header ── */
    h('div', { className: 'obs-head' },
      h('div', { className: 'obs-title' },
        h('svg', { viewBox: '0 0 24 24', width: 15, height: 15, className: 'obs-icon' },
          h('circle', { cx: 12, cy: 12, r: 9, fill: 'none', stroke: 'currentColor', strokeWidth: '1.5' }),
          h('line', { x1: 12, y1: 7, x2: 12, y2: 13, stroke: 'currentColor', strokeWidth: '1.5' }),
          h('circle', { cx: 12, cy: 16, r: 1, fill: 'currentColor' })
        ),
        'TRACE EXPLORER'
      ),
      h('div', { className: 'obs-controls' },
        h('span', { className: 'obs-count' }, traces.length + ' traces'),
        h('button', { className: 'obs-btn', onClick: fetchTraces, title: 'Refresh', disabled: loading },
          loading ? '…' : '↺'
        ),
        h('button', { className: 'obs-btn obs-btn-warn', onClick: clearTraces, title: 'Clear all traces' },
          'CLR'
        ),
        h('button', { className: 'obs-btn', onClick: function () { setCollapsed(function (v) { return !v; }); } },
          collapsed ? '▼' : '▲'
        )
      )
    ),

    /* ── body ── */
    !collapsed && h('div', { className: 'obs-body' },
      error && h('div', { className: 'obs-error' }, error),

      /* left: trace table */
      h('div', { className: 'obs-table-wrap' },
        h('table', { className: 'obs-table' },
          h('thead', null,
            h('tr', null,
              h('th', { className: 'obs-th' }, 'Time'),
              h('th', { className: 'obs-th' }, 'Ch'),
              h('th', { className: 'obs-th' }, 'Route'),
              h('th', { className: 'obs-th' }, 'Agents'),
              h('th', { className: 'obs-th' }, 'Model'),
              h('th', { className: 'obs-th' }, 'Latency'),
              h('th', { className: 'obs-th' }, 'Tok in/out'),
              h('th', { className: 'obs-th' }, 'St.')
            )
          ),
          h('tbody', null,
            traces.length === 0
              ? h('tr', null, h('td', { colSpan: 8, className: 'obs-empty' },
                  loading ? 'Loading…' : 'No traces yet. Send a chat message to record the first trace.'
                ))
              : traces.map(function (t) {
                  return h(TraceRow, {
                    key: t.id,
                    trace: t,
                    selected: selected && selected.id === t.id,
                    onSelect: fetchDetail,
                  });
                })
          )
        )
      ),

      /* right: detail pane */
      detail && h(TraceDetail, {
        trace: detail,
        onClose: function () { setSelected(null); setDetail(null); },
      })
    )
  );
}

/* ── export to window (same convention as cognition.js / systems.js) ── */
Object.assign(window, { ObservabilityPanel, TraceDetail, TimingBar });
