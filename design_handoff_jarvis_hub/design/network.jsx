// network.jsx — the live agent network visualization.
// Replaces the voice visualizer as the centerpiece of the HUD.
// Each agent is a node orbiting the Jarvis core; each task is a satellite.
// Active routes (jarvis → routedAgents) light up with traveling packets.

const { useMemo, useState, useEffect, useRef } = React;

function NetworkBrain({ agents, tasks, collab = [], activeAgent, onSelect, routedAgents, voiceState, focusAgent, onFocusAgent }) {
  // SVG viewBox dimensions
  const W = 880, H = 380;
  const cx = W / 2, cy = H / 2;
  const R_AGENT = 138;
  const R_TASK  = 178;

  // Order around the circle so tiers are contiguous (no line crossings)
  // Excludes Jarvis (which is the core)
  const RING_ORDER = [
    'friday','pepper','jerome',                  // CNS  (top arc)
    'athena','stark','veronica','vision',        // BIZ  (right arc)
    'steve','oracle','ultron',                   // SEC  (bottom arc)
    'gecko','hercules','hephaestus','frigga',    // FND  (left arc)
  ];

  const agentMap = useMemo(() => Object.fromEntries(agents.map(a => [a.id, a])), [agents]);

  // Position each agent on the ring
  const ringAgents = useMemo(() => {
    return RING_ORDER.map((id, i, arr) => {
      const angle = -Math.PI / 2 + (i / arr.length) * Math.PI * 2;
      return {
        ...agentMap[id],
        angle,
        x: cx + Math.cos(angle) * R_AGENT,
        y: cy + Math.sin(angle) * R_AGENT,
      };
    }).filter(a => a.id); // drop missing
  }, [agentMap]);

  // Position tasks: fan out perpendicular-ish from the agent's radial line
  const positionedTasks = useMemo(() => {
    const byOwner = {};
    tasks.forEach(t => { (byOwner[t.owner] ||= []).push(t); });
    const out = [];
    ringAgents.forEach((a) => {
      const list = byOwner[a.id] || [];
      const n = list.length;
      list.forEach((t, i) => {
        // spread tasks across a small angular range centered on the agent's angle
        const spread = 0.18; // radians
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

  // Active route ids (jarvis is implicit as core)
  const activeSet = useMemo(() => new Set(routedAgents.filter(id => id !== 'jarvis')), [routedAgents]);

  // Focus mode: when an agent is double-clicked, dim others & expand its tasks
  const focused = focusAgent ? ringAgents.find(a => a.id === focusAgent) : null;
  const focusedTasks = focused ? positionedTasks.filter(t => t.owner === focused.id) : [];
  // Focused-agent task projection: lay tasks on a fan in front of the agent's radial line, much bigger spread
  const focusedTaskPos = useMemo(() => {
    if (!focused) return [];
    const list = positionedTasks.filter(t => t.owner === focused.id);
    const n = list.length;
    const R_FOCUS_BASE = 100;   // distance from focused node center
    const FAN_SPAN     = Math.PI * 0.55; // ~99° fan
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

  // Collab edges: build path with bend angle so they curve along the ring
  const collabEdges = useMemo(() => {
    if (focused) return []; // hide collab edges in focus mode (visually noisy)
    return collab.map((c) => {
      const A = ringAgents.find(x => x.id === c.a);
      const B = ringAgents.find(x => x.id === c.b);
      if (!A || !B) return null;
      // Control point: midpoint pulled toward the center, scaled by intensity
      const mx = (A.x + B.x) / 2;
      const my = (A.y + B.y) / 2;
      const dx = mx - cx, dy = my - cy;
      const dist = Math.hypot(dx, dy);
      const pull = 0.55; // pull halfway toward center
      const ux = dx / dist, uy = dy / dist;
      const ctrlX = mx - ux * dist * pull;
      const ctrlY = my - uy * dist * pull;
      const path = `M${A.x},${A.y} Q${ctrlX},${ctrlY} ${B.x},${B.y}`;
      return { ...c, A, B, path, ctrlX, ctrlY };
    }).filter(Boolean);
  }, [ringAgents, collab, focused, cx, cy]);

  // Hover state for agent tooltip
  const [hovered, setHovered] = useState(null);
  const hoveredTasks = hovered ? positionedTasks.filter(t => t.owner === hovered) : [];
  const hoveredAgent = hovered ? ringAgents.find(a => a.id === hovered) : null;

  // Ambient packets: pick a random non-active edge every ~1.6s and pulse it briefly
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

  return (
    <Bracket
      label={focused ? `NEURAL NETWORK · FOCUS · ${focused.name.toUpperCase()}` : "NEURAL NETWORK · LIVE TOPOLOGY"}
      status={focused
        ? `${focusedTasks.length} TASKS · ${focusedTasks.filter(t=>t.state==='running').length} RUNNING · esc to exit`
        : `${ringAgents.filter(a => a.status !== 'idle').length} ACTIVE NODES · ${positionedTasks.length} TASKS · dbl-click to focus`}
      className={`net-bracket ${focused ? 'is-focused' : ''}`}
    >
      <div className="net-frame">
        <svg viewBox={`0 0 ${W} ${H}`} className="net-svg" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="core-grad" cx="50%" cy="50%" r="50%">
              <stop offset="0%"  stopColor="var(--accent-light)" stopOpacity="1" />
              <stop offset="60%" stopColor="var(--accent)" stopOpacity="0.85" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="node-grad" cx="50%" cy="50%" r="50%">
              <stop offset="0%"  stopColor="var(--accent-light)" stopOpacity="0.9" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.1" />
            </radialGradient>
            <filter id="glow"><feGaussianBlur stdDeviation="2.2" /></filter>
            <filter id="glow-strong"><feGaussianBlur stdDeviation="4" /></filter>
          </defs>

          {/* === circuit-board ambient mesh (decorative) === */}
          <g className="net-mesh" opacity="0.18" stroke="var(--accent)" strokeWidth="0.5" fill="none">
            {/* concentric guide arcs */}
            <circle cx={cx} cy={cy} r={R_AGENT}    strokeDasharray="2 6" />
            <circle cx={cx} cy={cy} r={R_TASK}     strokeDasharray="1 8" opacity="0.5" />
            <circle cx={cx} cy={cy} r={R_AGENT-50} strokeDasharray="1 4" opacity="0.4" />
            {/* horizontal/vertical cardinal guides */}
            <line x1={cx-(R_TASK+30)} y1={cy} x2={cx+(R_TASK+30)} y2={cy} strokeDasharray="1 12" opacity="0.4"/>
            <line x1={cx} y1={cy-(R_TASK+30)} x2={cx} y2={cy+(R_TASK+30)} strokeDasharray="1 12" opacity="0.4"/>
            {/* tier sector dividers */}
            {[0, 3, 7, 10].map(i => {
              const a = -Math.PI/2 + (i / 14) * Math.PI * 2 - Math.PI / 14;
              return (
                <line key={i}
                  x1={cx + Math.cos(a) * 70} y1={cy + Math.sin(a) * 70}
                  x2={cx + Math.cos(a) * (R_TASK+20)} y2={cy + Math.sin(a) * (R_TASK+20)}
                  strokeDasharray="3 5" opacity="0.4"
                />
              );
            })}
          </g>

          {/* tier sector stamps in corners (don't overlap with agent labels) */}
          <g className="net-tier-labels">
            <text x="14" y="16"      textAnchor="start" className="tier-label">FND · FOUNDATION</text>
            <text x={W-14} y="16"    textAnchor="end"   className="tier-label">CNS · COMMAND</text>
            <text x="14" y={H-46}    textAnchor="start" className="tier-label">SEC · SECURITY</text>
            <text x={W-14} y={H-46}  textAnchor="end"   className="tier-label">BIZ · BUSINESS</text>
          </g>

          {/* === collab edges: agent ↔ agent === */}
          {!focused && collabEdges.map((c) => (
            <g key={`co-${c.a}-${c.b}`} className={`collab collab-${c.dir}`} opacity={0.35 + c.intensity * 0.45}>
              <path d={c.path} className="collab-path" fill="none" />
            </g>
          ))}
          {/* === collab packets: travel along the curves === */}
          {!focused && collabEdges.map((c, i) => {
            const dur = 4.5 - c.intensity * 2.0; // higher intensity → faster
            const out = [];
            if (c.dir === 'both' || c.dir === 'a-b') {
              out.push(
                <circle key={`co-pk-ab-${i}`} r="1.8" className="collab-packet">
                  <animateMotion dur={`${dur}s`} repeatCount="indefinite" path={c.path} begin={`${(i * 0.2) % 2}s`} />
                </circle>
              );
            }
            if (c.dir === 'both' || c.dir === 'b-a') {
              // reverse path
              const rev = `M${c.B.x},${c.B.y} Q${c.ctrlX},${c.ctrlY} ${c.A.x},${c.A.y}`;
              out.push(
                <circle key={`co-pk-ba-${i}`} r="1.8" className="collab-packet">
                  <animateMotion dur={`${dur}s`} repeatCount="indefinite" path={rev} begin={`${(i * 0.2 + 0.6) % 2}s`} />
                </circle>
              );
            }
            return out;
          })}

          {/* === connection lines: jarvis core → each agent === */}
          {ringAgents.map((a) => {
            const isActive = activeSet.has(a.id);
            const isSelected = activeAgent === a.id;
            const isHover = hovered === a.id;
            const cls = [
              'edge', `edge-${a.status}`,
              isActive && 'edge-route',
              (isSelected || isHover) && 'edge-focus',
            ].filter(Boolean).join(' ');
            return (
              <line
                key={`e-${a.id}`}
                x1={cx} y1={cy} x2={a.x} y2={a.y}
                className={cls}
              />
            );
          })}

          {/* === agent → task spokes === */}
          {positionedTasks.map((t) => {
            const a = t.ownerNode;
            const isActive = activeSet.has(t.owner);
            return (
              <line
                key={`tk-${t.id}`}
                x1={a.x} y1={a.y} x2={t.x} y2={t.y}
                className={`spoke spoke-${t.state} ${isActive ? 'spoke-route' : ''}`}
              />
            );
          })}

          {/* === continuous packets on each active agent's edge === */}
          {ringAgents.map((a) => {
            if (activeSet.has(a.id)) return null; // active route packets handled below
            if (a.status === 'idle') return null;
            const dur = a.status === 'active' ? 2.2 : 3.4;
            return (
              <Packet
                key={`live-${a.id}`}
                x1={cx} y1={cy} x2={a.x} y2={a.y}
                duration={dur}
                className={a.status === 'active' ? 'packet-active' : 'packet-ambient'}
              />
            );
          })}

          {/* === ambient + active route packets === */}
          {ringAgents.map((a) => activeSet.has(a.id) && (
            <Packet key={`pk-${a.id}`} x1={cx} y1={cy} x2={a.x} y2={a.y} duration={0.9} className="packet-route" />
          ))}
          {ambient.map((p) => (
            <Packet key={p.key} x1={cx} y1={cy} x2={p.agent.x} y2={p.agent.y} duration={1.6} className="packet-ambient" />
          ))}

          {/* === packets along running task spokes (agent → task) === */}
          {positionedTasks.filter(t => t.state === 'running').map((t) => (
            <Packet
              key={`tk-pk-${t.id}`}
              x1={t.ownerNode.x} y1={t.ownerNode.y} x2={t.x} y2={t.y}
              duration={2.4}
              className="packet-task"
            />
          ))}

          {/* === task satellites === */}
          {positionedTasks.map((t) => {
            const isHovered = hovered === t.owner;
            return (
              <g key={t.id} className={`task task-${t.state} ${isHovered ? 'is-hovered' : ''}`}>
                <circle cx={t.x} cy={t.y} r={t.state === 'done' ? 1.8 : 3.2} className="task-dot" />
                {t.state === 'running' && (
                  <circle cx={t.x} cy={t.y} r="6" className="task-ring" />
                )}
              </g>
            );
          })}

          {/* === agent nodes === */}
          {ringAgents.map((a) => {
            const isActive = activeSet.has(a.id);
            const isSelected = activeAgent === a.id;
            const isHover = hovered === a.id;
            const isFocus = focused?.id === a.id;
            const isDimmed = focused && !isFocus;
            return (
              <g
                key={a.id}
                className={`node node-${a.status} ${isActive ? 'is-route' : ''} ${isSelected ? 'is-selected' : ''} ${isHover ? 'is-hover' : ''} ${isFocus ? 'is-focus' : ''} ${isDimmed ? 'is-dimmed' : ''}`}
                onMouseEnter={() => setHovered(a.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(a.id)}
                onDoubleClick={(e) => { e.stopPropagation(); onFocusAgent?.(isFocus ? null : a.id); }}
                style={{ cursor: 'pointer' }}
              >
                {/* halo */}
                <circle cx={a.x} cy={a.y} r={isFocus ? 36 : 22} className="node-halo" />
                {/* hexagon outline */}
                <Hex cx={a.x} cy={a.y} r={isFocus ? 18 : 10} className="node-hex" />
                {/* agent glyph inside hex */}
                {a.glyph && (
                  <g transform={`translate(${a.x},${a.y}) scale(${isFocus ? 1.0 : 0.42})`} className="node-glyph">
                    <path d={a.glyph} fill="none" stroke="currentColor" strokeWidth={isFocus ? 1.0 : 2.0} strokeLinejoin="round" />
                  </g>
                )}
                {/* label */}
                <text
                  x={a.x + Math.cos(a.angle) * (isFocus ? 40 : 30)}
                  y={a.y + Math.sin(a.angle) * (isFocus ? 40 : 30) + 3}
                  textAnchor={textAnchorFor(a.angle)}
                  className="node-label"
                >
                  {a.name.toUpperCase()}
                </text>
                {/* role subtitle in focus mode */}
                {isFocus && (
                  <text
                    x={a.x + Math.cos(a.angle) * 40}
                    y={a.y + Math.sin(a.angle) * 40 + 16}
                    textAnchor={textAnchorFor(a.angle)}
                    className="node-sublabel"
                  >
                    {a.role}
                  </text>
                )}
              </g>
            );
          })}

          {/* === focused agent task fan === */}
          {focused && focusedTaskPos.map((t) => {
            const a = ringAgents.find(x => x.id === t.owner);
            return (
              <g key={`ft-${t.id}`} className={`focus-task focus-task-${t.state}`}>
                <line x1={a.x} y1={a.y} x2={t.fx} y2={t.fy} className="focus-task-edge" />
                <Packet x1={a.x} y1={a.y} x2={t.fx} y2={t.fy}
                  duration={t.state === 'running' ? 1.6 : 3.0}
                  className={t.state === 'running' ? 'packet-task' : 'packet-ambient'} />
                <circle cx={t.fx} cy={t.fy} r="6" className="focus-task-dot" />
                {t.state === 'running' && (
                  <circle cx={t.fx} cy={t.fy} r="10" className="focus-task-ring" />
                )}
                <text x={t.fx} y={t.fy + 22} textAnchor="middle" className="focus-task-label">
                  {t.label}
                </text>
                <text x={t.fx} y={t.fy + 34} textAnchor="middle" className="focus-task-project">
                  {t.project} · {t.state}
                </text>
              </g>
            );
          })}

          {/* === central JARVIS core === */}
          <g className={`core core-${voiceState}`}>
            {/* outer pulsing aura */}
            <circle cx={cx} cy={cy} r="68" className="core-aura" />
            {/* rotating dashed ring */}
            <circle cx={cx} cy={cy} r="54" className="core-ring-1" />
            {/* counter-rotating ring */}
            <circle cx={cx} cy={cy} r="42" className="core-ring-2" />
            {/* inner orb */}
            <circle cx={cx} cy={cy} r="26" fill="url(#core-grad)" filter="url(#glow-strong)" className="core-orb" />
            <circle cx={cx} cy={cy} r="14" className="core-pupil" />
            {/* JARVIS text */}
            <text x={cx} y={cy + 4} className="core-text" textAnchor="middle">JARVIS</text>
            {/* state ticks (4 cardinal arcs) */}
            <g className="core-ticks">
              {[0, 90, 180, 270].map(deg => (
                <line key={deg}
                  x1={cx} y1={cy - 60} x2={cx} y2={cy - 64}
                  transform={`rotate(${deg} ${cx} ${cy})`}
                />
              ))}
            </g>
          </g>
        </svg>

        {/* === Hover tooltip card === */}
        {hovered && hoveredAgent && (
          <div className="net-tip" style={tooltipStyle(hoveredAgent, W, H)}>
            <div className="net-tip-head">
              <span className="net-tip-name">{hoveredAgent.name}</span>
              <span className="net-tip-tier">{hoveredAgent.tier}</span>
            </div>
            <div className="net-tip-role">{hoveredAgent.role}</div>
            <div className="net-tip-tasks">
              {hoveredTasks.length === 0 && <div className="net-tip-empty">— no active tasks</div>}
              {hoveredTasks.map(t => (
                <div key={t.id} className={`tip-task tip-task-${t.state}`}>
                  <span className="tip-task-state" />
                  <span className="tip-task-label">{t.label}</span>
                  <span className="tip-task-project">{t.project}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* === voice-state readout strip (footer) === */}
        <div className={`net-readout net-readout-${voiceState}`}>
          <div className="net-readout-left">
            <span className="net-readout-eye" />
            <span className="net-readout-label">
              {voiceState === 'idle'       && 'STANDBY · awaiting wake word'}
              {voiceState === 'listening'  && 'LISTENING · wake word detected'}
              {voiceState === 'processing' && 'PROCESSING · routing to specialists'}
              {voiceState === 'speaking'   && 'SPEAKING · response in flight'}
            </span>
          </div>
          <div className="net-readout-right">
            <span>STT · WHISPER-LARGE-V3</span>
            <span className="sep">·</span>
            <span>TTS · KOKORO-EN-GB-M1</span>
            <span className="sep">·</span>
            <span>BACKEND · LM-STUDIO:1234</span>
          </div>
        </div>
      </div>
    </Bracket>
  );
}

/* helpers */

function Hex({ cx, cy, r, className }) {
  // pointy-top hexagon
  const pts = [0,1,2,3,4,5].map(i => {
    const a = -Math.PI/2 + i * Math.PI/3;
    return `${cx + Math.cos(a)*r},${cy + Math.sin(a)*r}`;
  }).join(' ');
  return <polygon points={pts} className={className} />;
}

function Packet({ x1, y1, x2, y2, duration, className }) {
  return (
    <circle r="2.5" className={className}>
      <animate
        attributeName="cx"
        values={`${x1};${x2}`}
        dur={`${duration}s`}
        repeatCount="indefinite"
      />
      <animate
        attributeName="cy"
        values={`${y1};${y2}`}
        dur={`${duration}s`}
        repeatCount="indefinite"
      />
      <animate
        attributeName="opacity"
        values="0;1;1;0"
        dur={`${duration}s`}
        repeatCount="indefinite"
      />
    </circle>
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
