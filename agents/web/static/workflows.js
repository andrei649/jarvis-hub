'use strict';
/* workflows.js — H9.1 Visual Workflow Builder
   Depends on: components.js (h, useState, useEffect, useRef, useCallback) */

// ── constants ──────────────────────────────────────────────────────────────────

var NODE_W = 140;
var NODE_H = 54;
var NODE_GAP_X = 180;
var NODE_GAP_Y = 90;
var CANVAS_W = 800;
var CANVAS_H = 420;

// ── helpers ────────────────────────────────────────────────────────────────────

function _nodeColor(agentId) {
  var COLORS = {
    jarvis: '#00d4ff', veronica: '#a78bfa', gecko: '#34d399',
    hercules: '#f59e0b', steve: '#60a5fa', ultron: '#f87171',
    vision: '#c084fc', athena: '#fb923c', oracle: '#38bdf8',
  };
  return COLORS[agentId] || '#94a3b8';
}

// Lay out nodes in topological order — nodes with same depth share a column.
function _layoutNodes(steps, positions) {
  if (!steps || !steps.length) return {};
  // Compute depth (longest path from root).
  var depths = {};
  var deps = {};
  steps.forEach(function (s) { deps[s.id] = (s.depends_on || []); });

  function depth(id) {
    if (id in depths) return depths[id];
    var d = deps[id] || [];
    depths[id] = d.length === 0 ? 0 : 1 + Math.max.apply(null, d.map(depth));
    return depths[id];
  }
  steps.forEach(function (s) { depth(s.id); });

  // Group by depth.
  var cols = {};
  steps.forEach(function (s) {
    var d = depths[s.id];
    if (!cols[d]) cols[d] = [];
    cols[d].push(s.id);
  });

  var layout = {};
  var maxCol = Math.max.apply(null, Object.keys(cols).map(Number));
  Object.keys(cols).forEach(function (col) {
    var ids = cols[col];
    var totalH = ids.length * NODE_H + (ids.length - 1) * (NODE_GAP_Y - NODE_H);
    var startY = (CANVAS_H - totalH) / 2;
    ids.forEach(function (id, i) {
      // Use persisted drag position if available, else compute from topology.
      if (positions && positions[id]) {
        layout[id] = positions[id];
      } else {
        layout[id] = {
          x: 40 + Number(col) * NODE_GAP_X,
          y: startY + i * NODE_GAP_Y,
        };
      }
    });
  });
  return layout;
}

// ── SVG canvas component ───────────────────────────────────────────────────────

function WorkflowCanvas(props) {
  var steps = props.steps || [];
  var layout = props.layout || {};
  var selectedId = props.selectedId;
  var onDragEnd = props.onDragEnd;

  var svgRef = useRef(null);
  var dragging = useRef(null);

  function onPointerDown(e, stepId) {
    e.preventDefault();
    var svg = svgRef.current;
    if (!svg) return;
    var pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    var svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    dragging.current = {
      id: stepId,
      offsetX: svgP.x - (layout[stepId] ? layout[stepId].x : 0),
      offsetY: svgP.y - (layout[stepId] ? layout[stepId].y : 0),
    };
    svg.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e) {
    if (!dragging.current) return;
    var svg = svgRef.current;
    if (!svg) return;
    var pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    var svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    if (onDragEnd) {
      onDragEnd(dragging.current.id, {
        x: svgP.x - dragging.current.offsetX,
        y: svgP.y - dragging.current.offsetY,
      }, false);
    }
  }

  function onPointerUp(e) {
    if (!dragging.current) return;
    var svg = svgRef.current;
    if (!svg) return;
    var pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    var svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    if (onDragEnd) {
      onDragEnd(dragging.current.id, {
        x: svgP.x - dragging.current.offsetX,
        y: svgP.y - dragging.current.offsetY,
      }, true);
    }
    dragging.current = null;
  }

  // Build edge list.
  var edges = [];
  steps.forEach(function (s) {
    (s.depends_on || []).forEach(function (dep) {
      var from = layout[dep];
      var to = layout[s.id];
      if (from && to) {
        edges.push({
          key: dep + '->' + s.id,
          x1: from.x + NODE_W,
          y1: from.y + NODE_H / 2,
          x2: to.x,
          y2: to.y + NODE_H / 2,
        });
      }
    });
  });

  return h('svg', {
    ref: svgRef,
    width: CANVAS_W,
    height: CANVAS_H,
    style: { display: 'block', background: 'rgba(0,0,0,0.25)', borderRadius: '8px', border: '1px solid rgba(0,212,255,0.1)', cursor: 'default' },
    onPointerMove: onPointerMove,
    onPointerUp: onPointerUp,
  },
    // Edges.
    edges.map(function (e) {
      var mx = (e.x1 + e.x2) / 2;
      return h('path', {
        key: e.key,
        d: 'M' + e.x1 + ',' + e.y1 + ' C' + mx + ',' + e.y1 + ' ' + mx + ',' + e.y2 + ' ' + e.x2 + ',' + e.y2,
        stroke: 'rgba(0,212,255,0.35)',
        strokeWidth: 1.5,
        fill: 'none',
        markerEnd: 'url(#arrow)',
      });
    }),

    // Arrow marker def.
    h('defs', null,
      h('marker', {
        id: 'arrow', markerWidth: 8, markerHeight: 8,
        refX: 6, refY: 3, orient: 'auto',
      },
        h('path', { d: 'M0,0 L0,6 L8,3 z', fill: 'rgba(0,212,255,0.5)' })
      )
    ),

    // Nodes.
    steps.map(function (s) {
      var pos = layout[s.id] || { x: 20, y: 20 };
      var color = _nodeColor(s.agent_id);
      var isSelected = selectedId === s.id;
      return h('g', {
        key: s.id,
        transform: 'translate(' + pos.x + ',' + pos.y + ')',
        onPointerDown: function (e) { onPointerDown(e, s.id); },
        style: { cursor: 'grab' },
      },
        h('rect', {
          width: NODE_W, height: NODE_H, rx: 6, ry: 6,
          fill: isSelected ? 'rgba(0,212,255,0.12)' : 'rgba(5,5,8,0.7)',
          stroke: isSelected ? color : 'rgba(0,212,255,0.2)',
          strokeWidth: isSelected ? 2 : 1,
        }),
        h('text', {
          x: 10, y: 20,
          fill: color,
          fontSize: 11,
          fontFamily: 'monospace',
          style: { pointerEvents: 'none', userSelect: 'none' },
        }, s.id),
        h('text', {
          x: 10, y: 36,
          fill: 'rgba(200,214,229,0.5)',
          fontSize: 9,
          fontFamily: 'monospace',
          style: { pointerEvents: 'none', userSelect: 'none' },
        }, (s.agent_id || '—').slice(0, 18)),
        // Dependency count badge.
        (s.depends_on && s.depends_on.length > 0) && h('text', {
          x: NODE_W - 8, y: 12,
          fill: 'rgba(0,212,255,0.4)',
          fontSize: 8,
          textAnchor: 'end',
          style: { pointerEvents: 'none', userSelect: 'none' },
        }, 'deps:' + s.depends_on.length)
      );
    })
  );
}

// ── Step editor form ───────────────────────────────────────────────────────────

function StepForm(props) {
  var existingIds = props.existingIds || [];
  var onAdd = props.onAdd;

  var _s1 = useState(''), stepId = _s1[0], setStepId = _s1[1];
  var _s2 = useState(''), agentId = _s2[0], setAgentId = _s2[1];
  var _s3 = useState('{_input}'), prompt = _s3[0], setPrompt = _s3[1];
  var _s4 = useState([]), deps = _s4[0], setDeps = _s4[1];

  function toggleDep(id) {
    setDeps(function (prev) {
      return prev.includes(id) ? prev.filter(function (x) { return x !== id; }) : prev.concat([id]);
    });
  }

  function submit() {
    if (!stepId.trim() || !agentId.trim()) return;
    if (onAdd) onAdd({ id: stepId.trim(), agent_id: agentId.trim(), prompt_template: prompt, depends_on: deps });
    setStepId(''); setAgentId(''); setPrompt('{_input}'); setDeps([]);
  }

  var inputStyle = {
    width: '100%', padding: '5px 8px', background: 'rgba(0,0,0,0.4)',
    border: '1px solid rgba(0,212,255,0.15)', borderRadius: '4px',
    color: '#c8d6e5', fontSize: '11px', outline: 'none', boxSizing: 'border-box',
  };

  return h('div', { style: { padding: '10px 0' } },
    h('div', { style: { fontSize: '9px', letterSpacing: '2px', color: 'rgba(0,212,255,0.35)', marginBottom: '8px', textTransform: 'uppercase' } }, 'Add Step'),

    h('div', { style: { marginBottom: '6px' } },
      h('label', { style: { fontSize: '9px', color: 'rgba(0,212,255,0.3)', display: 'block', marginBottom: '2px' } }, 'Step ID'),
      h('input', { style: inputStyle, type: 'text', value: stepId, placeholder: 'e.g. summarize', onChange: function (e) { setStepId(e.target.value); } })
    ),

    h('div', { style: { marginBottom: '6px' } },
      h('label', { style: { fontSize: '9px', color: 'rgba(0,212,255,0.3)', display: 'block', marginBottom: '2px' } }, 'Agent ID'),
      h('input', { style: inputStyle, type: 'text', value: agentId, placeholder: 'e.g. veronica', onChange: function (e) { setAgentId(e.target.value); } })
    ),

    h('div', { style: { marginBottom: '6px' } },
      h('label', { style: { fontSize: '9px', color: 'rgba(0,212,255,0.3)', display: 'block', marginBottom: '2px' } }, 'Prompt Template'),
      h('textarea', {
        style: Object.assign({}, inputStyle, { height: '54px', resize: 'vertical', fontFamily: 'monospace' }),
        value: prompt,
        onChange: function (e) { setPrompt(e.target.value); },
      })
    ),

    existingIds.length > 0 && h('div', { style: { marginBottom: '8px' } },
      h('label', { style: { fontSize: '9px', color: 'rgba(0,212,255,0.3)', display: 'block', marginBottom: '4px' } }, 'Depends On'),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '4px' } },
        existingIds.map(function (id) {
          return h('button', {
            key: id,
            onClick: function () { toggleDep(id); },
            style: {
              padding: '2px 7px', fontSize: '9px', borderRadius: '10px', cursor: 'pointer',
              background: deps.includes(id) ? 'rgba(0,212,255,0.18)' : 'rgba(0,0,0,0.3)',
              border: '1px solid ' + (deps.includes(id) ? 'rgba(0,212,255,0.4)' : 'rgba(0,212,255,0.1)'),
              color: deps.includes(id) ? '#00d4ff' : 'rgba(200,214,229,0.4)',
            },
          }, id);
        })
      )
    ),

    h('button', {
      onClick: submit,
      disabled: !stepId.trim() || !agentId.trim(),
      style: {
        padding: '5px 14px', fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase',
        background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.25)',
        borderRadius: '4px', color: 'rgba(0,212,255,0.7)', cursor: 'pointer',
      },
    }, '+ Add Step')
  );
}

// ── Result panel ───────────────────────────────────────────────────────────────

function ResultPanel(props) {
  var result = props.result;
  if (!result) return null;

  var keys = Object.keys(result).filter(function (k) { return !k.startsWith('_'); });

  return h('div', {
    style: {
      marginTop: '12px', padding: '10px', background: 'rgba(0,0,0,0.3)',
      border: '1px solid rgba(0,212,255,0.1)', borderRadius: '6px', maxHeight: '200px', overflowY: 'auto',
    },
  },
    h('div', { style: { fontSize: '9px', letterSpacing: '2px', color: 'rgba(0,212,255,0.35)', marginBottom: '8px', textTransform: 'uppercase' } },
      result._ok ? '✓ Run complete' : '✗ Run errors',
      ' — ',
      result._elapsed ? result._elapsed + 's' : ''
    ),
    keys.map(function (k) {
      return h('div', {
        key: k,
        style: { marginBottom: '6px', fontSize: '10px' },
      },
        h('div', { style: { color: 'rgba(0,212,255,0.4)', marginBottom: '2px', fontFamily: 'monospace' } }, k + ':'),
        h('div', { style: { color: 'rgba(200,214,229,0.6)', paddingLeft: '8px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' } },
          String(result[k]).slice(0, 400)
        )
      );
    })
  );
}

// ── Main WorkflowsPanel ────────────────────────────────────────────────────────

function WorkflowsPanel() {
  // ── workflow list state ──
  var _wl = useState([]), workflows = _wl[0], setWorkflows = _wl[1];
  var _sel = useState(null), selectedWfId = _sel[0], setSelectedWfId = _sel[1];

  // ── current draft state ──
  var _wid = useState(''), wfId = _wid[0], setWfId = _wid[1];
  var _wname = useState(''), wfName = _wname[0], setWfName = _wname[1];
  var _wdesc = useState(''), wfDesc = _wdesc[0], setWfDesc = _wdesc[1];
  var _steps = useState([]), steps = _steps[0], setSteps = _steps[1];

  // ── canvas drag positions ──
  var _pos = useState({}), positions = _pos[0], setPositions = _pos[1];

  // ── run state ──
  var _inp = useState(''), runInput = _inp[0], setRunInput = _inp[1];
  var _res = useState(null), runResult = _res[0], setRunResult = _res[1];
  var _running = useState(false), running = _running[0], setRunning = _running[1];

  // ── save state ──
  var _saving = useState(false), saving = _saving[0], setSaving = _saving[1];
  var _saveErr = useState(''), saveErr = _saveErr[0], setSaveErr = _saveErr[1];
  var _saveOk = useState(false), saveOk = _saveOk[0], setSaveOk = _saveOk[1];

  // ── load workflow list on mount ──
  var loadWorkflows = useCallback(function () {
    fetch('/api/workflows')
      .then(function (r) { return r.json(); })
      .then(function (d) { setWorkflows(d.workflows || []); })
      .catch(function (err) { console.error('WorkflowsPanel: load error', err); });
  }, []);

  useEffect(function () { loadWorkflows(); }, [loadWorkflows]);

  // ── layout ──
  var layout = _layoutNodes(steps, positions);

  // ── handlers ──

  function loadSelected(id) {
    var wf = workflows.find(function (w) { return w.id === id; });
    if (!wf) return;
    setSelectedWfId(id);
    setWfId(wf.id);
    setWfName(wf.name || '');
    setWfDesc(wf.description || '');
    setSteps((wf.steps || []).map(function (s) {
      return { id: s.id, agent_id: s.agent_id, prompt_template: s.prompt_template, depends_on: s.depends_on || [] };
    }));
    setPositions({});
    setRunResult(null);
    setSaveErr('');
    setSaveOk(false);
  }

  function newWorkflow() {
    setSelectedWfId(null);
    setWfId('');
    setWfName('');
    setWfDesc('');
    setSteps([]);
    setPositions({});
    setRunResult(null);
    setSaveErr('');
    setSaveOk(false);
  }

  function addStep(step) {
    setSteps(function (prev) { return prev.concat([step]); });
    setPositions(function (prev) {
      var upd = {};
      Object.keys(prev).forEach(function (k) { upd[k] = prev[k]; });
      return upd;
    });
  }

  function removeStep(id) {
    setSteps(function (prev) {
      return prev
        .filter(function (s) { return s.id !== id; })
        .map(function (s) {
          return Object.assign({}, s, { depends_on: (s.depends_on || []).filter(function (d) { return d !== id; }) });
        });
    });
  }

  function onDragEnd(id, pos) {
    setPositions(function (prev) {
      var upd = {};
      Object.keys(prev).forEach(function (k) { upd[k] = prev[k]; });
      upd[id] = pos;
      return upd;
    });
  }

  async function saveWorkflow() {
    if (!wfId.trim()) { setSaveErr('Pipeline ID is required'); return; }
    setSaving(true); setSaveErr(''); setSaveOk(false);
    try {
      var body = { id: wfId.trim(), name: wfName, description: wfDesc, steps: steps };
      var r = await fetch('/api/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        var err = await r.json();
        setSaveErr(err.detail || JSON.stringify(err));
      } else {
        setSaveOk(true);
        loadWorkflows();
        setSelectedWfId(wfId.trim());
      }
    } catch (e) {
      setSaveErr(String(e));
    }
    setSaving(false);
  }

  async function runWorkflow() {
    if (!wfId.trim()) return;
    setRunning(true); setRunResult(null);
    try {
      var r = await fetch('/api/workflows/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_id: wfId.trim(), input: runInput }),
      });
      var d = await r.json();
      setRunResult(d.result || d);
    } catch (e) {
      setRunResult({ _ok: false, _error: String(e) });
    }
    setRunning(false);
  }

  async function deleteWorkflow() {
    if (!selectedWfId) return;
    if (!window.confirm('Delete workflow "' + selectedWfId + '"?')) return;
    try {
      await fetch('/api/workflows/' + encodeURIComponent(selectedWfId), { method: 'DELETE' });
      newWorkflow();
      loadWorkflows();
    } catch (e) {
      console.error('delete workflow error', e);
    }
  }

  // ── styles ──
  var panelStyle = {
    display: 'flex', flexDirection: 'column', gap: '12px',
    padding: '16px', background: 'rgba(5,5,8,0.6)',
    border: '1px solid rgba(0,212,255,0.08)', borderRadius: '8px',
    minHeight: '520px', maxHeight: '90vh', overflowY: 'auto',
  };

  var rowStyle = { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' };

  var inputStyle = {
    flex: 1, padding: '5px 8px', background: 'rgba(0,0,0,0.4)',
    border: '1px solid rgba(0,212,255,0.15)', borderRadius: '4px',
    color: '#c8d6e5', fontSize: '11px', outline: 'none', minWidth: '60px',
  };

  var btnStyle = {
    padding: '5px 14px', fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase',
    background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.25)',
    borderRadius: '4px', color: 'rgba(0,212,255,0.7)', cursor: 'pointer',
  };

  var dangerBtnStyle = Object.assign({}, btnStyle, {
    background: 'rgba(255,51,85,0.08)', border: '1px solid rgba(255,51,85,0.25)', color: 'rgba(255,100,120,0.8)',
  });

  var labelStyle = { fontSize: '9px', letterSpacing: '2px', color: 'rgba(0,212,255,0.35)', textTransform: 'uppercase' };

  return h('div', { style: panelStyle },

    // ── header row ──
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('span', { style: { fontSize: '10px', letterSpacing: '3px', color: 'rgba(0,212,255,0.5)', textTransform: 'uppercase' } }, '◆ Workflow Builder'),
      h('button', { onClick: newWorkflow, style: btnStyle }, '+ New')
    ),

    // ── workflow selector ──
    h('div', { style: rowStyle },
      h('span', { style: labelStyle }, 'Load:'),
      h('select', {
        value: selectedWfId || '',
        onChange: function (e) { if (e.target.value) loadSelected(e.target.value); },
        style: Object.assign({}, inputStyle, { flex: '0 1 200px' }),
      },
        h('option', { value: '' }, '— select a workflow —'),
        workflows.map(function (w) {
          return h('option', { key: w.id, value: w.id }, w.name || w.id);
        })
      ),
      selectedWfId && h('button', { onClick: deleteWorkflow, style: dangerBtnStyle }, 'Delete')
    ),

    // ── identity fields ──
    h('div', { style: rowStyle },
      h('div', { style: { flex: '0 0 auto' } },
        h('span', { style: labelStyle }, 'ID'),
        h('input', { style: Object.assign({}, inputStyle, { flex: 'none', width: '140px', marginTop: '3px', display: 'block' }), type: 'text', value: wfId, placeholder: 'pipeline-id', onChange: function (e) { setWfId(e.target.value); } })
      ),
      h('div', { style: { flex: 1 } },
        h('span', { style: labelStyle }, 'Name'),
        h('input', { style: Object.assign({}, inputStyle, { display: 'block', marginTop: '3px', width: '100%', boxSizing: 'border-box' }), type: 'text', value: wfName, placeholder: 'Human-readable name', onChange: function (e) { setWfName(e.target.value); } })
      ),
    ),
    h('div', null,
      h('span', { style: labelStyle }, 'Description'),
      h('input', { style: Object.assign({}, inputStyle, { display: 'block', marginTop: '3px', width: '100%', boxSizing: 'border-box' }), type: 'text', value: wfDesc, placeholder: 'Optional description', onChange: function (e) { setWfDesc(e.target.value); } })
    ),

    // ── canvas ──
    h('div', { style: { overflowX: 'auto' } },
      steps.length === 0
        ? h('div', {
            style: {
              height: '100px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'rgba(0,212,255,0.15)', fontSize: '11px', border: '1px dashed rgba(0,212,255,0.1)',
              borderRadius: '8px',
            },
          }, 'No steps yet — add steps below')
        : h(WorkflowCanvas, { steps: steps, layout: layout, onDragEnd: onDragEnd })
    ),

    // ── step list (compact) ──
    steps.length > 0 && h('div', null,
      h('div', { style: labelStyle }, 'Steps (' + steps.length + ')'),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px' } },
        steps.map(function (s) {
          return h('div', {
            key: s.id,
            style: {
              padding: '4px 10px', fontSize: '10px', borderRadius: '12px',
              background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(0,212,255,0.15)',
              display: 'flex', gap: '8px', alignItems: 'center',
            },
          },
            h('span', { style: { color: _nodeColor(s.agent_id) } }, s.id),
            h('span', { style: { color: 'rgba(200,214,229,0.35)', fontSize: '9px' } }, s.agent_id),
            h('button', {
              onClick: function () { removeStep(s.id); },
              style: {
                background: 'none', border: 'none', color: 'rgba(255,100,100,0.5)',
                cursor: 'pointer', padding: '0 0 0 4px', fontSize: '12px', lineHeight: 1,
              },
            }, '×')
          );
        })
      )
    ),

    // ── step editor ──
    h(StepForm, { existingIds: steps.map(function (s) { return s.id; }), onAdd: addStep }),

    // ── save / run row ──
    h('div', { style: Object.assign({}, rowStyle, { borderTop: '1px solid rgba(0,212,255,0.07)', paddingTop: '10px' }) },
      h('button', { onClick: saveWorkflow, disabled: saving || !wfId.trim(), style: btnStyle },
        saving ? 'Saving…' : 'Save Workflow'
      ),
      saveOk && h('span', { style: { fontSize: '10px', color: '#34d399' } }, '✓ Saved'),
      saveErr && h('span', { style: { fontSize: '10px', color: '#f87171', maxWidth: '200px' } }, saveErr),
    ),

    // ── run section ──
    h('div', { style: rowStyle },
      h('span', { style: labelStyle }, 'Input:'),
      h('input', { style: Object.assign({}, inputStyle, { flex: 1 }), type: 'text', value: runInput, placeholder: 'Initial input for the workflow', onChange: function (e) { setRunInput(e.target.value); } }),
      h('button', {
        onClick: runWorkflow,
        disabled: running || !wfId.trim(),
        style: Object.assign({}, btnStyle, { background: running ? 'rgba(0,212,255,0.04)' : 'rgba(0,212,255,0.12)' }),
      }, running ? 'Running…' : '▶ Run')
    ),

    h(ResultPanel, { result: runResult })
  );
}

// ── export ────────────────────────────────────────────────────────────────────

Object.assign(window, { WorkflowsPanel });
