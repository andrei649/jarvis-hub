'use strict';
/* network.js — neural network SVG visualizer */
/* Copied from design_handoff_jarvis_hub/design/network.jsx */

/* h, useState, useEffect, useRef, useMemo, useLayoutEffect, useCallback — from components.js */

function NetworkBrain({ agents, tasks, collab = [], activeAgent, onSelect, routedAgents, voiceState, focusAgent, onFocusAgent }) {
  const W = 880, H = 380;
  const cx = W / 2, cy = H / 2;
  const R_AGENT = 138;
  const R_TASK  = 178;

  // Preferred display order for known agents. Any agent returned by the API
  // that is not in this list (e.g. newly promoted bench agents) is appended
  // automatically so the ring always reflects the live roster.
  const RING_PREFERRED = [
    'friday','pepper','jerome',
    'athena','stark','veronica','vision',
    'steve','oracle','ultron',
    'gecko','hercules','hephaestus','frigga',
  ];

  const agentMap = useMemo(() => Object.fromEntries(agents.map(a => [a.id, a])), [agents]);

  const RING_ORDER = useMemo(() => {
    const known = RING_PREFERRED.filter(id => agentMap[id]);
    const extra = agents
      .map(a => a.id)
      .filter(id => id && id !== 'jarvis' && !RING_PREFERRED.includes(id));
    return known.concat(extra);
  }, [agentMap, agents]);

  const ringAgents = useMemo(() => {
    return RING_ORDER.map((id, i, arr) => {
      const angle = -Math.PI / 2 + (i / arr.length) * Math.PI * 2;
      return {
        ...agentMap[id],
        angle,
        x: cx + Math.cos(angle) * R_AGENT,
        y: cy + Math.sin(angle) * R_AGENT,
      };
    }).filter(a => a.id);
  }, [agentMap, RING_ORDER]);

  const positionedTasks = useMemo(() => {
    const byOwner = {};
    tasks.forEach(t => { (byOwner[t.owner] ||= []).push(t); });
    const out = [];
    ringAgents.forEach((a) => {
      const list = byOwner[a.id] || [];
      const n = list.length;
      list.forEach((t, i) => {
        const spread = 0.18;
        const offset = n === 1 ? 0 : (i - (n - 1) / 2) * spread;
        const tAngle = a.angle + offset;
        out.push({
          ...t,
          ownerNode: a,
          angle: tAngle,
          x: cx + Math.cos(tAngle) * R_TASK,
          y: cy + Math.sin(tAngle) * R_TASK,
        });
      });
    });
    return out;
  }, [ringAgents, tasks]);

  const activeSet = useMemo(() => new Set(routedAgents.filter(id => id !== 'jarvis')), [routedAgents]);

  const focused = focusAgent ? ringAgents.find(a => a.id === focusAgent) : null;
  const focusedTasks = focused ? positionedTasks.filter(t => t.owner === focused.id) : [];
  const focusedTaskPos = useMemo(() => {
    if (!focused) return [];
    const list = positionedTasks.filter(t => t.owner === focused.id);
    const n = list.length;
    const R_FOCUS_BASE = 100;
    const FAN_SPAN     = Math.PI * 0.55;
    return list.map((task, i) => {
      const frac = n === 1 ? 0.5 : i / (n - 1);
      const dir  = focused.angle;
      const off  = (frac - 0.5) * FAN_SPAN;
      const a    = dir + off;
      return {
        ...task,
        fx: focused.x + Math.cos(a) * R_FOCUS_BASE,
        fy: focused.y + Math.sin(a) * R_FOCUS_BASE,
      };
    });
  }, [focused, positionedTasks]);

  const collabEdges = useMemo(() => {
    if (focused) return [];
    return collab.map((c) => {
      const A = ringAgents.find(x => x.id === c.a);
      const B = ringAgents.find(x => x.id === c.b);
      if (!A || !B) return null;
      const mx = (A.x + B.x) / 2;
      const my = (A.y + B.y) / 2;
      const dx = mx - cx, dy = my - cy;
      const dist = Math.hypot(dx, dy);
      const pull = 0.55;
      const ux = dx / dist, uy = dy / dist;
      const ctrlX = mx - ux * dist * pull;
      const ctrlY = my - uy * dist * pull;
      const path = `M${A.x},${A.y} Q${ctrlX},${ctrlY} ${B.x},${B.y}`;
      return { ...c, A, B, path, ctrlX, ctrlY };
    }).filter(Boolean);
  }, [ringAgents, collab, focused, cx, cy]);

  const [hovered, setHovered] = useState(null);
  const hoveredTasks = hovered ? positionedTasks.filter(t => t.owner === hovered) : [];
  const hoveredAgent = hovered ? ringAgents.find(a => a.id === hovered) : null;

  const [ambient, setAmbient] = useState([]);
  useEffect(() => {
    if (!ringAgents.length) return;
    const id = setInterval(() => {
      const pool = ringAgents.filter(a => !activeSet.has(a.id) && a.status !== 'idle');
      if (!pool.length) return;
      const picked = pool[Math.floor(Math.random() * pool.length)];
      const key = `${picked.id}-${Date.now()}`;
      setAmbient((p) => [...p, { key, agent: picked }]);
      setTimeout(() => setAmbient((p) => p.filter(a => a.key !== key)), 1800);
    }, 1300);
    return () => clearInterval(id);
  }, [ringAgents, activeSet]);

  return h(Bracket, {
    label: focused ? `NEURAL NETWORK · FOCUS · ${focused.name.toUpperCase()}` : 'NEURAL NETWORK · LIVE TOPOLOGY',
    status: focused
      ? `${focusedTasks.length} TASKS · ${focusedTasks.filter(t => t.state === 'running').length} RUNNING · esc to exit`
      : `${ringAgents.filter(a => a.status !== 'idle').length} ACTIVE NODES · ${positionedTasks.length} TASKS · dbl-click to focus`,
    className: `net-bracket ${focused ? 'is-focused' : ''}`,
  },
    h('div', { className: 'net-frame' },
      h('svg', { viewBox: `0 0 ${W} ${H}`, className: 'net-svg', preserveAspectRatio: 'xMidYMid meet' },
        h('defs', null,
          h('radialGradient', { id: 'core-grad', cx: '50%', cy: '50%', r: '50%' },
            h('stop', { offset: '0%', stopColor: 'var(--accent-light)', stopOpacity: '1' }),
            h('stop', { offset: '60%', stopColor: 'var(--accent)', stopOpacity: '0.85' }),
            h('stop', { offset: '100%', stopColor: 'var(--accent)', stopOpacity: '0' }),
          ),
          h('radialGradient', { id: 'node-grad', cx: '50%', cy: '50%', r: '50%' },
            h('stop', { offset: '0%', stopColor: 'var(--accent-light)', stopOpacity: '0.9' }),
            h('stop', { offset: '100%', stopColor: 'var(--accent)', stopOpacity: '0.1' }),
          ),
          h('filter', { id: 'glow' },
            h('feGaussianBlur', { stdDeviation: '2.2' }),
          ),
          h('filter', { id: 'glow-strong' },
            h('feGaussianBlur', { stdDeviation: '4' }),
          ),
        ),

        h('g', { className: 'net-mesh', opacity: '0.18', stroke: 'var(--accent)', 'stroke-width': '0.5', fill: 'none' },
          h('circle', { cx, cy, r: R_AGENT, 'stroke-dasharray': '2 6' }),
          h('circle', { cx, cy, r: R_TASK, 'stroke-dasharray': '1 8', opacity: '0.5' }),
          h('circle', { cx, cy, r: R_AGENT - 50, 'stroke-dasharray': '1 4', opacity: '0.4' }),
          h('line', { x1: cx - (R_TASK + 30), y1: cy, x2: cx + (R_TASK + 30), y2: cy, 'stroke-dasharray': '1 12', opacity: '0.4' }),
          h('line', { x1: cx, y1: cy - (R_TASK + 30), x2: cx, y2: cy + (R_TASK + 30), 'stroke-dasharray': '1 12', opacity: '0.4' }),
          [0, 3, 7, 10].map(i => {
            const a = -Math.PI / 2 + (i / 14) * Math.PI * 2 - Math.PI / 14;
            return h('line', {
              key: i,
              x1: cx + Math.cos(a) * 70,
              y1: cy + Math.sin(a) * 70,
              x2: cx + Math.cos(a) * (R_TASK + 20),
              y2: cy + Math.sin(a) * (R_TASK + 20),
              'stroke-dasharray': '3 5',
              opacity: '0.4',
            });
          }),
        ),

        h('g', { className: 'net-tier-labels' },
          h('text', { x: '14', y: '16', 'text-anchor': 'start', className: 'tier-label' }, 'FND · FOUNDATION'),
          h('text', { x: W - 14, y: '16', 'text-anchor': 'end', className: 'tier-label' }, 'CNS · COMMAND'),
          h('text', { x: '14', y: H - 46, 'text-anchor': 'start', className: 'tier-label' }, 'SEC · SECURITY'),
          h('text', { x: W - 14, y: H - 46, 'text-anchor': 'end', className: 'tier-label' }, 'BIZ · BUSINESS'),
        ),

        !focused && collabEdges.map(c =>
          h('g', { key: `co-${c.a}-${c.b}`, className: `collab collab-${c.dir}`, opacity: 0.35 + c.intensity * 0.45 },
            h('path', { d: c.path, className: 'collab-path', fill: 'none' }),
          )
        ),

        !focused && collabEdges.map((c, i) => {
          const dur = 4.5 - c.intensity * 2.0;
          const out = [];
          if (c.dir === 'both' || c.dir === 'a-b') {
            out.push(
              h('circle', { key: `co-pk-ab-${i}`, r: '1.8', className: 'collab-packet' },
                h('animateMotion', { dur: `${dur}s`, repeatCount: 'indefinite', path: c.path, begin: `${(i * 0.2) % 2}s` }),
              )
            );
          }
          if (c.dir === 'both' || c.dir === 'b-a') {
            const rev = `M${c.B.x},${c.B.y} Q${c.ctrlX},${c.ctrlY} ${c.A.x},${c.A.y}`;
            out.push(
              h('circle', { key: `co-pk-ba-${i}`, r: '1.8', className: 'collab-packet' },
                h('animateMotion', { dur: `${dur}s`, repeatCount: 'indefinite', path: rev, begin: `${(i * 0.2 + 0.6) % 2}s` }),
              )
            );
          }
          return out;
        }),

        ringAgents.map(a => {
          const isActive = activeSet.has(a.id);
          const isSelected = activeAgent === a.id;
          const isHover = hovered === a.id;
          const cls = ['edge', `edge-${a.status}`, isActive && 'edge-route', (isSelected || isHover) && 'edge-focus'].filter(Boolean).join(' ');
          return h('line', { key: `e-${a.id}`, x1: cx, y1: cy, x2: a.x, y2: a.y, className: cls });
        }),

        positionedTasks.map(t => {
          const a = t.ownerNode;
          const isActive = activeSet.has(t.owner);
          return h('line', {
            key: `tk-${t.id}`,
            x1: a.x, y1: a.y, x2: t.x, y2: t.y,
            className: `spoke spoke-${t.state} ${isActive ? 'spoke-route' : ''}`,
          });
        }),

        ringAgents.map(a => {
          if (activeSet.has(a.id)) return null;
          if (a.status === 'idle') return null;
          const dur = a.status === 'active' ? 2.2 : 3.4;
          return h(Packet, {
            key: `live-${a.id}`, x1: cx, y1: cy, x2: a.x, y2: a.y,
            duration: dur,
            className: a.status === 'active' ? 'packet-active' : 'packet-ambient',
          });
        }),

        ringAgents.map(a => activeSet.has(a.id) && h(Packet, {
          key: `pk-${a.id}`, x1: cx, y1: cy, x2: a.x, y2: a.y, duration: 0.9, className: 'packet-route',
        })),

        ambient.map(p => h(Packet, {
          key: p.key, x1: cx, y1: cy, x2: p.agent.x, y2: p.agent.y, duration: 1.6, className: 'packet-ambient',
        })),

        positionedTasks.filter(t => t.state === 'running').map(t => h(Packet, {
          key: `tk-pk-${t.id}`, x1: t.ownerNode.x, y1: t.ownerNode.y, x2: t.x, y2: t.y, duration: 2.4, className: 'packet-task',
        })),

        positionedTasks.map(t => {
          const isHovered = hovered === t.owner;
          return h('g', { key: t.id, className: `task task-${t.state} ${isHovered ? 'is-hovered' : ''}` },
            h('circle', { cx: t.x, cy: t.y, r: t.state === 'done' ? 1.8 : 3.2, className: 'task-dot' }),
            t.state === 'running' && h('circle', { cx: t.x, cy: t.y, r: '6', className: 'task-ring' }),
          );
        }),

        ringAgents.map(a => {
          const isActive = activeSet.has(a.id);
          const isSelected = activeAgent === a.id;
          const isHover = hovered === a.id;
          const isFocus = focused?.id === a.id;
          const isDimmed = focused && !isFocus;
          return h('g', {
            key: a.id,
            className: `node node-${a.status} ${isActive ? 'is-route' : ''} ${isSelected ? 'is-selected' : ''} ${isHover ? 'is-hover' : ''} ${isFocus ? 'is-focus' : ''} ${isDimmed ? 'is-dimmed' : ''}`,
            onMouseEnter: () => setHovered(a.id),
            onMouseLeave: () => setHovered(null),
            onClick: () => onSelect(a.id),
            onDoubleClick: (e) => { e.stopPropagation(); onFocusAgent?.(isFocus ? null : a.id); },
            style: { cursor: 'pointer' },
          },
            h('circle', { cx: a.x, cy: a.y, r: isFocus ? 36 : 22, className: 'node-halo' }),
            h(Hex, { cx: a.x, cy: a.y, r: isFocus ? 18 : 10, className: 'node-hex' }),
            a.glyph && h('g', { transform: `translate(${a.x},${a.y}) scale(${isFocus ? 1.0 : 0.42})`, className: 'node-glyph' },
              h('path', { d: a.glyph, fill: 'none', stroke: 'currentColor', 'stroke-width': isFocus ? 1.0 : 2.0, 'stroke-linejoin': 'round' }),
            ),
            h('text', {
              x: a.x + Math.cos(a.angle) * (isFocus ? 40 : 30),
              y: a.y + Math.sin(a.angle) * (isFocus ? 40 : 30) + 3,
              'text-anchor': textAnchorFor(a.angle),
              className: 'node-label',
            }, a.name.toUpperCase()),
            isFocus && h('text', {
              x: a.x + Math.cos(a.angle) * 40,
              y: a.y + Math.sin(a.angle) * 40 + 16,
              'text-anchor': textAnchorFor(a.angle),
              className: 'node-sublabel',
            }, a.role),
          );
        }),

        focused && focusedTaskPos.map(t => {
          const a = ringAgents.find(x => x.id === t.owner);
          return h('g', { key: `ft-${t.id}`, className: `focus-task focus-task-${t.state}` },
            h('line', { x1: a.x, y1: a.y, x2: t.fx, y2: t.fy, className: 'focus-task-edge' }),
            h(Packet, { x1: a.x, y1: a.y, x2: t.fx, y2: t.fy, duration: t.state === 'running' ? 1.6 : 3.0, className: t.state === 'running' ? 'packet-task' : 'packet-ambient' }),
            h('circle', { cx: t.fx, cy: t.fy, r: '6', className: 'focus-task-dot' }),
            t.state === 'running' && h('circle', { cx: t.fx, cy: t.fy, r: '10', className: 'focus-task-ring' }),
            h('text', { x: t.fx, y: t.fy + 22, 'text-anchor': 'middle', className: 'focus-task-label' }, t.label),
            h('text', { x: t.fx, y: t.fy + 34, 'text-anchor': 'middle', className: 'focus-task-project' }, `${t.project} · ${t.state}`),
          );
        }),

        h('g', { className: `core core-${voiceState}` },
          h('circle', { cx, cy, r: '68', className: 'core-aura' }),
          h('circle', { cx, cy, r: '54', className: 'core-ring-1' }),
          h('circle', { cx, cy, r: '42', className: 'core-ring-2' }),
          h('circle', { cx, cy, r: '26', fill: 'url(#core-grad)', filter: 'url(#glow-strong)', className: 'core-orb' }),
          h('circle', { cx, cy, r: '14', className: 'core-pupil' }),
          h('text', { x: cx, y: cy + 4, className: 'core-text', 'text-anchor': 'middle' }, 'JARVIS'),
          h('g', { className: 'core-ticks' },
            [0, 90, 180, 270].map(deg => h('line', {
              key: deg, x1: cx, y1: cy - 60, x2: cx, y2: cy - 64,
              transform: `rotate(${deg} ${cx} ${cy})`,
            })),
          ),
        ),
      ),

      hovered && hoveredAgent && h('div', { className: 'net-tip', style: tooltipStyle(hoveredAgent, W, H) },
        h('div', { className: 'net-tip-head' },
          h('span', { className: 'net-tip-name' }, hoveredAgent.name),
          h('span', { className: 'net-tip-tier' }, hoveredAgent.tier),
        ),
        h('div', { className: 'net-tip-role' }, hoveredAgent.role),
        h('div', { className: 'net-tip-tasks' },
          hoveredTasks.length === 0 && h('div', { className: 'net-tip-empty' }, '— no active tasks'),
          hoveredTasks.map(t => h('div', { key: t.id, className: `tip-task tip-task-${t.state}` },
            h('span', { className: 'tip-task-state' }),
            h('span', { className: 'tip-task-label' }, t.label),
            h('span', { className: 'tip-task-project' }, t.project),
          )),
        ),
      ),

      h('div', { className: `net-readout net-readout-${voiceState}` },
        h('div', { className: 'net-readout-left' },
          h('span', { className: 'net-readout-eye' }),
          h('span', { className: 'net-readout-label' },
            voiceState === 'idle'       && 'STANDBY · awaiting wake word',
            voiceState === 'listening'  && 'LISTENING · wake word detected',
            voiceState === 'processing' && 'PROCESSING · routing to specialists',
            voiceState === 'speaking'   && 'SPEAKING · response in flight',
          ),
        ),
        h('div', { className: 'net-readout-right' },
          h('span', null, 'STT · WHISPER-LARGE-V3'),
          h('span', { className: 'sep' }, '·'),
          h('span', null, 'TTS · KOKORO-EN-GB-M1'),
          h('span', { className: 'sep' }, '·'),
          h('span', null, 'BACKEND · LM-STUDIO:1234'),
        ),
      ),
    ),
  );
}

function Hex({ cx, cy, r, className }) {
  const pts = [0, 1, 2, 3, 4, 5].map(i => {
    const a = -Math.PI / 2 + i * Math.PI / 3;
    return `${cx + Math.cos(a) * r},${cy + Math.sin(a) * r}`;
  }).join(' ');
  return h('polygon', { points: pts, className });
}

function Packet({ x1, y1, x2, y2, duration, className }) {
  return h('circle', { r: '2.5', className },
    h('animate', { attributeName: 'cx', values: `${x1};${x2}`, dur: `${duration}s`, repeatCount: 'indefinite' }),
    h('animate', { attributeName: 'cy', values: `${y1};${y2}`, dur: `${duration}s`, repeatCount: 'indefinite' }),
    h('animate', { attributeName: 'opacity', values: '0;1;1;0', dur: `${duration}s`, repeatCount: 'indefinite' }),
  );
}

function textAnchorFor(angle) {
  const cos = Math.cos(angle);
  if (cos > 0.3) return 'start';
  if (cos < -0.3) return 'end';
  return 'middle';
}

function tooltipStyle(agent, W, H) {
  const right = agent.x > W / 2;
  const below = agent.y < H / 2;
  return {
    left: right ? undefined : `${(agent.x / W) * 100 + 4}%`,
    right: right ? `${100 - (agent.x / W) * 100 + 4}%` : undefined,
    top:  below ? `${(agent.y / H) * 100 + 2}%` : undefined,
    bottom: below ? undefined : `${100 - (agent.y / H) * 100 + 2}%`,
  };
}

Object.assign(window, { NetworkBrain });
