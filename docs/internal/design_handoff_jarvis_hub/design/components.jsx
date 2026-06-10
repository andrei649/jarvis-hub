// components.jsx — building blocks for the Jarvis Hub HUD.
// Loaded as a Babel script. Exposes components on `window` for app.jsx to use.

const { useState, useEffect, useRef, useMemo, useLayoutEffect } = React;

/* ───────────────────────────── helpers ───────────────────────────── */

const pad2 = (n) => String(n).padStart(2, '0');
const fmtTime = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
const fmtDate = (d) => {
  const days = ['DUM', 'LUN', 'MAR', 'MIE', 'JOI', 'VIN', 'SÂM'];
  const months = ['IAN','FEB','MAR','APR','MAI','IUN','IUL','AUG','SEP','OCT','NOV','DEC'];
  return `${days[d.getDay()]} · ${pad2(d.getDate())} ${months[d.getMonth()]} ${d.getFullYear()}`;
};

function Bracket({ children, className = '', label, status }) {
  return (
    <div className={`bracket ${className}`}>
      <span className="bk-corner bk-tl" />
      <span className="bk-corner bk-tr" />
      <span className="bk-corner bk-bl" />
      <span className="bk-corner bk-br" />
      {(label || status) && (
        <div className="bk-head">
          {label && <span className="bk-label">{label}</span>}
          {status && <span className="bk-status">{status}</span>}
        </div>
      )}
      <div className="bk-body">{children}</div>
    </div>
  );
}

function StatusDot({ status, size = 8 }) {
  return <span className={`dot dot-${status}`} style={{ width: size, height: size }} />;
}

/* ───────────────────────────── TopBar ───────────────────────────── */

function Clock() {
  const [now, setNow] = useState(() => new Date(2026, 4, 27, 14, 23, 41));
  useEffect(() => {
    const id = setInterval(() => setNow((d) => new Date(d.getTime() + 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="clock">
      <div className="clock-time">{fmtTime(now)}</div>
      <div className="clock-date">{fmtDate(now)} · EUROPE/BUCURESTI</div>
    </div>
  );
}

function TopBar({ activeAgent, voiceState, agentCount, sysOnline }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="logo">
          <svg viewBox="0 0 32 32" width="22" height="22" className="logo-mark">
            <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.35" />
            <circle cx="16" cy="16" r="9"  fill="none" stroke="currentColor" strokeWidth="1" opacity="0.7" />
            <circle cx="16" cy="16" r="4"  fill="currentColor" />
            <line x1="16" y1="1"  x2="16" y2="6"  stroke="currentColor" strokeWidth="1"/>
            <line x1="16" y1="26" x2="16" y2="31" stroke="currentColor" strokeWidth="1"/>
            <line x1="1"  y1="16" x2="6"  y2="16" stroke="currentColor" strokeWidth="1"/>
            <line x1="26" y1="16" x2="31" y2="16" stroke="currentColor" strokeWidth="1"/>
          </svg>
          <div className="logo-text">
            <div className="logo-name">JARVIS<span className="logo-dot">·</span>HUB</div>
            <div className="logo-ver">v0.2.1 · BONOBO-WS</div>
          </div>
        </div>
      </div>
      <Clock />
      <div className="topbar-right">
        <Badge label="Voice" value={voiceState.toUpperCase()} kind={voiceState === 'idle' ? 'dim' : 'active'} />
        <Badge label="Agents" value={`${agentCount}/15`} kind="active" />
        <Badge label="Memory" value="ONLINE" kind="ok" />
        <Badge label="LM Studio" value={sysOnline ? '1234' : 'OFFLINE'} kind={sysOnline ? 'active' : 'alert'} />
      </div>
    </header>
  );
}

function Badge({ label, value, kind }) {
  return (
    <div className={`badge badge-${kind}`}>
      <span className="badge-label">{label}</span>
      <span className="badge-value">{value}</span>
    </div>
  );
}

/* ───────────────────────────── AgentList ───────────────────────────── */

function AgentList({ agents, tiers, activeAgent, onSelect, sys }) {
  const grouped = useMemo(() => {
    return tiers.map((t) => ({ ...t, agents: agents.filter((a) => a.tier === t.id) }));
  }, [agents, tiers]);

  return (
    <aside className="panel panel-left">
      <Bracket label="AGENT NETWORK" status={`${agents.filter(a=>a.status!=='idle').length}/${agents.length}`}>
        <div className="agent-list">
          {grouped.map((g) => (
            <div key={g.id} className="agent-group">
              <div className="agent-group-head">
                <div className="agent-group-id">{g.id}</div>
                <div className="agent-group-label">{g.label}</div>
              </div>
              {g.agents.map((a) => (
                <button
                  key={a.id}
                  className={`agent-item ${activeAgent === a.id ? 'is-active' : ''} agent-${a.status}`}
                  onClick={() => onSelect(a.id)}
                >
                  <StatusDot status={a.status} />
                  {a.glyph && (
                    <svg viewBox="-12 -12 24 24" width="14" height="14" className="agent-glyph" style={{ position: 'absolute', marginLeft: 22, marginTop: -2 }}>
                      <path d={a.glyph} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                    </svg>
                  )}
                  <div className="agent-name" style={{ paddingLeft: a.glyph ? 20 : 0 }}>{a.name}</div>
                  <div className="agent-role" style={{ paddingLeft: a.glyph ? 20 : 0 }}>{a.role}</div>
                  <div className="agent-model">{a.model.split('-').slice(0,2).join('-')}</div>
                </button>
              ))}
            </div>
          ))}
        </div>
      </Bracket>

      <Bracket label="SYSTEM" status="NOMINAL" className="sys-bracket">
        <div className="sys-rows">
          <SysRow label="HOST" value={sys.host} />
          <SysRow label="CPU"  value={sys.cpu} />
          <SysMeter label="RAM" used={sys.ram_used} total={sys.ram_total} unit="GB" />
          <SysMeter label="VRAM" used={sys.vram_used} total={sys.vram_total} unit="GB" />
          <SysMeter label="GPU LOAD" used={sys.gpu_load} total={100} unit="%" raw />
          <SysRow label="BACKEND" value={sys.backend} />
          <SysRow label="MODEL"   value={sys.model} mono />
          <SysRow label="LATENCY" value={`${sys.latency.toFixed(1)}s avg`} />
          <SysRow label="UPTIME"  value={sys.uptime} />
        </div>
      </Bracket>
    </aside>
  );
}

function SysRow({ label, value, mono }) {
  return (
    <div className="sys-row">
      <span className="sys-key">{label}</span>
      <span className={`sys-val ${mono ? 'is-mono' : ''}`}>{value}</span>
    </div>
  );
}

function SysMeter({ label, used, total, unit, raw }) {
  const pct = raw ? used : Math.round((used / total) * 100);
  return (
    <div className="sys-meter">
      <div className="sys-meter-head">
        <span className="sys-key">{label}</span>
        <span className="sys-val">{raw ? `${used}${unit}` : `${used}/${total} ${unit}`}</span>
      </div>
      <div className="sys-bar">
        <div className="sys-bar-fill" style={{ width: `${pct}%` }} />
        <div className="sys-bar-ticks">
          {Array.from({ length: 10 }).map((_, i) => <span key={i} />)}
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────────── Voice Visualizer ───────────────────────────── */

function VoiceVisualizer({ state, activeAgent, onCycle }) {
  // 7 bars; heights computed per state via CSS keyframes
  const bars = Array.from({ length: 11 });
  const labels = {
    idle:       '— STANDBY —',
    listening:  '[ LISTENING · WAKE WORD DETECTED ]',
    processing: '[ PROCESSING · ROUTING TO SPECIALISTS ]',
    speaking:   `[ ${activeAgent.toUpperCase()} RESPONDING ]`,
  };
  return (
    <Bracket label="VOICE HUD" status={state.toUpperCase()} className="viz-bracket">
      <div className={`viz viz-${state}`} onClick={onCycle}>
        <div className="viz-ring viz-ring-1" />
        <div className="viz-ring viz-ring-2" />
        <div className="viz-ring viz-ring-3" />
        <div className="viz-core">
          {state === 'processing' ? (
            <svg viewBox="-30 -30 60 60" className="hex" width="84" height="84">
              <polygon
                points="0,-24 20.78,-12 20.78,12 0,24 -20.78,12 -20.78,-12"
                fill="none" stroke="currentColor" strokeWidth="1.2"
              />
              <polygon
                points="0,-14 12.12,-7 12.12,7 0,14 -12.12,7 -12.12,-7"
                fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.6"
                className="hex-inner"
              />
              <circle cx="0" cy="0" r="2" fill="currentColor" />
              <circle cx="0" cy="-24" r="1.5" fill="currentColor" />
              <circle cx="20.78" cy="0" r="1.5" fill="currentColor" />
              <circle cx="-20.78" cy="0" r="1.5" fill="currentColor" />
            </svg>
          ) : (
            <div className="viz-bars">
              {bars.map((_, i) => (
                <span key={i} className="viz-bar" style={{ '--i': i, '--n': bars.length }} />
              ))}
            </div>
          )}
        </div>
        <div className="viz-readout">
          <div className="viz-label">{labels[state]}</div>
          <div className="viz-meta">
            <span>CH · VOICE</span>
            <span className="viz-dot">·</span>
            <span>STT · WHISPER-LARGE-V3</span>
            <span className="viz-dot">·</span>
            <span>TTS · KOKORO-EN-GB-M1</span>
          </div>
        </div>
      </div>
    </Bracket>
  );
}

/* ───────────────────────────── Conversation ───────────────────────────── */

function ConversationView({ messages, agents, thinking, routedAgents }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, thinking]);

  const agentMap = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);

  return (
    <Bracket label="CONVERSATION · SESSION 20260527-0723" status={`${messages.length} TURNS`} className="convo-bracket">
      <div className="convo" ref={ref}>
        {messages.map((m, i) => (
          <Message key={i} m={m} agentMap={agentMap} />
        ))}
        {thinking && <ThinkingBubble agent={agentMap[thinking]} routedAgents={routedAgents} agentMap={agentMap} />}
      </div>
    </Bracket>
  );
}

function Message({ m, agentMap }) {
  if (m.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-meta">
          <span className="msg-tag">ANDREI</span>
          <span className="msg-ts">{m.ts}</span>
        </div>
        <div className="msg-body">{m.text}</div>
      </div>
    );
  }
  const a = agentMap[m.agent];
  return (
    <div className="msg msg-agent">
      <div className="msg-meta">
        <span className="msg-tag msg-tag-agent">[{(a?.name || m.agent).toUpperCase()}]</span>
        <span className="msg-role">{a?.role}</span>
        <span className="msg-ts">{m.ts}</span>
      </div>
      <div className="msg-body">{m.text}</div>
    </div>
  );
}

function ThinkingBubble({ agent, routedAgents, agentMap }) {
  return (
    <div className="msg msg-agent msg-thinking">
      <div className="msg-meta">
        <span className="msg-tag msg-tag-agent">[{(agent?.name || 'JARVIS').toUpperCase()}]</span>
        <span className="msg-role">orchestrating</span>
        <span className="msg-ts">···</span>
      </div>
      <div className="thinking-trace">
        <div className="trace-line">
          <span className="trace-arrow">›</span> classify intent
          <span className="trace-dots"><span/><span/><span/></span>
        </div>
        <div className="trace-line">
          <span className="trace-arrow">›</span> route ·{' '}
          {routedAgents.map((id, i) => (
            <span key={id} className="trace-pill">
              {agentMap[id]?.name || id}{i < routedAgents.length - 1 && <span className="trace-sep">→</span>}
            </span>
          ))}
        </div>
        <div className="trace-line">
          <span className="trace-arrow">›</span> synthesize
          <span className="trace-dots"><span/><span/><span/></span>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────────── Input bar ───────────────────────────── */

function InputBar({ value, onChange, onSubmit, mic, onMicToggle, activeAgent }) {
  return (
    <div className="input-bar">
      <div className="input-prefix">
        <span className="input-prompt">›</span>
        <span className="input-channel">CH:VOICE → {activeAgent.toUpperCase()}</span>
      </div>
      <input
        className="input-field"
        type="text"
        value={value}
        placeholder="Comandă... (text sau wake word „jarvis”)"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSubmit(); }}
        autoFocus
      />
      <button className={`input-mic ${mic ? 'is-on' : ''}`} onClick={onMicToggle} title="Microphone">
        <svg viewBox="0 0 24 24" width="16" height="16">
          <rect x="9" y="3" width="6" height="12" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M5 11a7 7 0 0 0 14 0" fill="none" stroke="currentColor" strokeWidth="1.5"/>
          <line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" strokeWidth="1.5"/>
        </svg>
      </button>
      <button className="input-send" onClick={onSubmit}>
        <span>TRANSMIT</span>
        <svg viewBox="0 0 16 16" width="12" height="12"><path d="M2 8h10M8 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" fill="none"/></svg>
      </button>
    </div>
  );
}

/* ───────────────────────────── Ambient panels ───────────────────────────── */

function WeatherCard({ data }) {
  const Icon = WeatherIcon[data.forecast[0].code] || WeatherIcon.cloud;
  return (
    <Bracket label="AMBIENT · WEATHER" status={data.city.toUpperCase()}>
      <div className="weather">
        <div className="weather-main">
          <div className="weather-temp">
            <span className="weather-deg">{data.temp}</span>
            <span className="weather-unit">°C</span>
          </div>
          <Icon className="weather-icon" />
        </div>
        <div className="weather-desc">{data.desc}</div>
        <div className="weather-grid">
          <div><span className="k">VÂNT</span><span className="v">{data.wind}</span></div>
          <div><span className="k">UMID.</span><span className="v">{data.humidity}</span></div>
          <div><span className="k">SIMTE</span><span className="v">{data.feels}°C</span></div>
          <div><span className="k">UPD</span><span className="v">{data.updated}</span></div>
        </div>
        <div className="weather-forecast">
          {data.forecast.map((f) => {
            const FI = WeatherIcon[f.code] || WeatherIcon.cloud;
            return (
              <div key={f.hr} className="fc-cell">
                <div className="fc-hr">{f.hr}</div>
                <FI className="fc-icon" small />
                <div className="fc-t">{f.t}°</div>
              </div>
            );
          })}
        </div>
      </div>
    </Bracket>
  );
}

const WeatherIcon = {
  cloud: ({ className, small }) => (
    <svg viewBox="0 0 32 24" className={className} width={small ? 18 : 36} height={small ? 14 : 28} fill="none" stroke="currentColor" strokeWidth={small ? 1.2 : 1.5}>
      <path d="M8 18h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 18z" />
    </svg>
  ),
  rain: ({ className, small }) => (
    <svg viewBox="0 0 32 28" className={className} width={small ? 18 : 36} height={small ? 14 : 28} fill="none" stroke="currentColor" strokeWidth={small ? 1.2 : 1.5}>
      <path d="M8 16h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 16z" />
      <line x1="11" y1="20" x2="9" y2="25"/><line x1="16" y1="20" x2="14" y2="25"/><line x1="21" y1="20" x2="19" y2="25"/>
    </svg>
  ),
};

function CalendarCard({ items }) {
  const next = items.find((i) => i.state === 'next');
  return (
    <Bracket label="CALENDAR · ASTĂZI" status={next ? `NEXT ${next.ts}` : '—'}>
      <div className="calendar">
        {items.map((it, i) => (
          <div key={i} className={`cal-row cal-${it.state}`}>
            <div className="cal-marker">
              {it.state === 'past' ? '○' : it.state === 'next' ? '▸' : '·'}
            </div>
            <div className="cal-ts">{it.ts}</div>
            <div className="cal-body">
              <div className="cal-title">{it.title}</div>
              <div className="cal-owner">via {it.owner}</div>
            </div>
          </div>
        ))}
      </div>
    </Bracket>
  );
}

function AgentsGrid({ agents, activeAgent, onSelect }) {
  const online = agents.filter((a) => a.status !== 'idle').length;
  return (
    <Bracket label="AGENT GRID" status={`${online}/${agents.length} ONLINE`}>
      <div className="agrid">
        {agents.map((a) => (
          <button
            key={a.id}
            className={`agrid-cell agent-${a.status} ${activeAgent === a.id ? 'is-active' : ''}`}
            onClick={() => onSelect(a.id)}
            title={`${a.name} — ${a.role}`}
          >
            <div className="agrid-dot" />
            <div className="agrid-tag">{a.name.slice(0, 3).toUpperCase()}</div>
          </button>
        ))}
      </div>
      <div className="agrid-legend">
        <span><span className="dot dot-active" /> active</span>
        <span><span className="dot dot-ready"  /> ready</span>
        <span><span className="dot dot-idle"   /> idle</span>
      </div>
    </Bracket>
  );
}

function HeartbeatFeed({ items, agentMap }) {
  return (
    <Bracket label="HEARTBEAT · ALERTS" status={`${items.length} ACTIVE`}>
      <div className="hbfeed">
        {items.map((n) => (
          <div key={n.id} className={`hb hb-${n.level}`}>
            <div className="hb-bar" />
            <div className="hb-body">
              <div className="hb-head">
                <span className="hb-tag">[{(agentMap[n.agent]?.name || n.agent).toUpperCase()}]</span>
                <span className="hb-ts">{n.ts}</span>
              </div>
              <div className="hb-text">{n.text}</div>
            </div>
          </div>
        ))}
      </div>
    </Bracket>
  );
}

/* ───────────────────────────── exports ───────────────────────────── */

Object.assign(window, {
  TopBar, AgentList, VoiceVisualizer, ConversationView, InputBar,
  WeatherCard, CalendarCard, AgentsGrid, HeartbeatFeed,
  Bracket, StatusDot,
});
