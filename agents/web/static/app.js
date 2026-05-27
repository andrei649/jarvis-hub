'use strict';
/* Jarvis Hub HUD — vanilla React (no JSX/Babel) */

const { createElement: h, useState, useEffect, useRef, useMemo, useLayoutEffect } = React;

/* ── Static metadata ──────────────────────────────────────────── */

const TIERS = [
  { id: 'CNS', label: 'Command — Nervous System', detail: 'Orchestration · Daily ops' },
  { id: 'BIZ', label: 'Business Intelligence',    detail: 'Strategy · Research · Comms' },
  { id: 'SEC', label: 'Security & Infrastructure',detail: 'Code · Workflows · Audit' },
  { id: 'FND', label: 'Foundation',               detail: 'Markets · Fitness · Family' },
];

const AGENT_META = {
  jarvis:     { tier: 'CNS', role: 'Prime Orchestrator' },
  friday:     { tier: 'CNS', role: 'Daily Intel' },
  pepper:     { tier: 'CNS', role: 'Chief of Staff' },
  jerome:     { tier: 'CNS', role: 'Leisure & Soundtrack' },
  athena:     { tier: 'BIZ', role: 'External Strategist' },
  stark:      { tier: 'BIZ', role: 'Biz Intel' },
  veronica:   { tier: 'BIZ', role: 'Content & Comms' },
  vision:     { tier: 'BIZ', role: 'Deep Research / OSINT' },
  steve:      { tier: 'SEC', role: 'CTO / Builds' },
  oracle:     { tier: 'SEC', role: 'N8N Workflows' },
  ultron:     { tier: 'SEC', role: 'Security & Automation' },
  gecko:      { tier: 'FND', role: 'Markets & Capital' },
  hercules:   { tier: 'FND', role: 'Fitness & Nutrition' },
  hephaestus: { tier: 'FND', role: 'Builder & Mechanic' },
  frigga:     { tier: 'FND', role: 'Family Matriarch' },
};

const FALLBACK_SYS = {
  host: 'BONOBO-WS',   cpu: 'Intel Core Ultra 9 · 24 thr',
  ram_used: 0, ram_total: 192,
  gpu: 'RTX 5090 · 24GB', vram_used: 0, vram_total: 24, gpu_load: 0,
  backend: 'LM Studio · 1234', model: 'google/gemma-4-26b-a4b',
  latency: 0, uptime: '—', sessions: 0,
};

const FALLBACK_WEATHER = {
  city: 'București', temp: '—', desc: 'Se încarcă…',
  wind: '—', humidity: '—', feels: '—', updated: '—',
  forecast: [],
};

const FALLBACK_CALENDAR = [];
const FALLBACK_NOTIFICATIONS = [];

/* ── Helpers ──────────────────────────────────────────────────── */

const pad2 = (n) => String(n).padStart(2, '0');
const fmtTime = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
const fmtDate = (d) => {
  const days = ['DUM','LUN','MAR','MIE','JOI','VIN','SÂM'];
  const months = ['IAN','FEB','MAR','APR','MAI','IUN','IUL','AUG','SEP','OCT','NOV','DEC'];
  return `${days[d.getDay()]} · ${pad2(d.getDate())} ${months[d.getMonth()]} ${d.getFullYear()}`;
};
const nowTs = () => { const d = new Date(); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; };
const esc = (t) => String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/* ── Bracket frame ────────────────────────────────────────────── */

function Bracket({ children, className = '', label, status }) {
  return h('div', { className: `bracket ${className}` },
    h('span', { className: 'bk-corner bk-tl' }),
    h('span', { className: 'bk-corner bk-tr' }),
    h('span', { className: 'bk-corner bk-bl' }),
    h('span', { className: 'bk-corner bk-br' }),
    (label || status) && h('div', { className: 'bk-head' },
      label  && h('span', { className: 'bk-label' }, label),
      status && h('span', { className: 'bk-status' }, status),
    ),
    h('div', { className: 'bk-body' }, children),
  );
}

function StatusDot({ status, size = 8 }) {
  return h('span', { className: `dot dot-${status}`, style: { width: size, height: size } });
}

/* ── TopBar ───────────────────────────────────────────────────── */

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return h('div', { className: 'clock' },
    h('div', { className: 'clock-time' }, fmtTime(now)),
    h('div', { className: 'clock-date' }, `${fmtDate(now)} · EUROPE/BUCURESTI`),
  );
}

function Badge({ label, value, kind }) {
  return h('div', { className: `badge badge-${kind}` },
    h('span', { className: 'badge-label' }, label),
    h('span', { className: 'badge-value' }, value),
  );
}

function TopBar({ activeAgent, voiceState, agentsOnline, agentsTotal, lmOnline }) {
  return h('header', { className: 'topbar' },
    h('div', { className: 'topbar-left' },
      h('div', { className: 'logo' },
        h('svg', { viewBox: '0 0 32 32', width: 22, height: 22, className: 'logo-mark' },
          h('circle', { cx: 16, cy: 16, r: 14, fill: 'none', stroke: 'currentColor', strokeWidth: 1, opacity: 0.35 }),
          h('circle', { cx: 16, cy: 16, r: 9,  fill: 'none', stroke: 'currentColor', strokeWidth: 1, opacity: 0.7 }),
          h('circle', { cx: 16, cy: 16, r: 4,  fill: 'currentColor' }),
          h('line', { x1: 16, y1: 1,  x2: 16, y2: 6,  stroke: 'currentColor', strokeWidth: 1 }),
          h('line', { x1: 16, y1: 26, x2: 16, y2: 31, stroke: 'currentColor', strokeWidth: 1 }),
          h('line', { x1: 1,  y1: 16, x2: 6,  y2: 16, stroke: 'currentColor', strokeWidth: 1 }),
          h('line', { x1: 26, y1: 16, x2: 31, y2: 16, stroke: 'currentColor', strokeWidth: 1 }),
        ),
        h('div', { className: 'logo-text' },
          h('div', { className: 'logo-name' }, 'JARVIS', h('span', { className: 'logo-dot' }, '·'), 'HUB'),
          h('div', { className: 'logo-ver' }, 'v0.2.1 · BONOBO-WS'),
        ),
      ),
    ),
    h(Clock),
    h('div', { className: 'topbar-right' },
      h(Badge, { label: 'Voice', value: voiceState.toUpperCase(), kind: voiceState === 'idle' ? 'dim' : 'active' }),
      h(Badge, { label: 'Agents', value: `${agentsOnline}/${agentsTotal}`, kind: 'active' }),
      h(Badge, { label: 'Memory', value: 'ONLINE', kind: 'ok' }),
      h(Badge, { label: 'LM Studio', value: lmOnline ? '1234' : 'OFFLINE', kind: lmOnline ? 'active' : 'alert' }),
    ),
  );
}

/* ── AgentList ────────────────────────────────────────────────── */

function AgentList({ agents, activeAgent, onSelect, sys }) {
  const grouped = useMemo(() => {
    return TIERS.map((t) => ({ ...t, agents: agents.filter((a) => a.tier === t.id) }));
  }, [agents]);

  const online = agents.filter((a) => a.status !== 'idle').length;

  return h('aside', { className: 'panel panel-left' },
    h(Bracket, { label: 'AGENT NETWORK', status: `${online}/${agents.length}` },
      h('div', { className: 'agent-list' },
        grouped.map((g) => g.agents.length === 0 ? null :
          h('div', { key: g.id, className: 'agent-group' },
            h('div', { className: 'agent-group-head' },
              h('div', { className: 'agent-group-id' }, g.id),
              h('div', { className: 'agent-group-label' }, g.label),
            ),
            g.agents.map((a) =>
              h('button', {
                key: a.id,
                className: `agent-item ${activeAgent === a.id ? 'is-active' : ''} agent-${a.status}`,
                onClick: () => onSelect(a.id),
              },
                h(StatusDot, { status: a.status }),
                h('div', { className: 'agent-name' }, a.name),
                h('div', { className: 'agent-role' }, a.role),
                h('div', { className: 'agent-model' }, a.model.split('-').slice(0, 2).join('-')),
              ),
            ),
          ),
        ),
      ),
    ),
    h(Bracket, { label: 'SYSTEM', status: 'NOMINAL', className: 'sys-bracket' },
      h('div', { className: 'sys-rows' },
        h(SysRow, { label: 'HOST',    value: sys.host }),
        h(SysRow, { label: 'CPU',     value: sys.cpu }),
        h(SysMeter, { label: 'RAM',   used: sys.ram_used,  total: sys.ram_total,  unit: 'GB' }),
        h(SysMeter, { label: 'VRAM',  used: sys.vram_used, total: sys.vram_total, unit: 'GB' }),
        h(SysMeter, { label: 'GPU',   used: sys.gpu_load,  total: 100,            unit: '%',  raw: true }),
        h(SysRow, { label: 'BACKEND', value: sys.backend }),
        h(SysRow, { label: 'MODEL',   value: sys.model, mono: true }),
        h(SysRow, { label: 'LATENCY', value: `${Number(sys.latency || 0).toFixed(1)}s avg` }),
        h(SysRow, { label: 'UPTIME',  value: sys.uptime }),
      ),
    ),
  );
}

function SysRow({ label, value, mono }) {
  return h('div', { className: 'sys-row' },
    h('span', { className: 'sys-key' }, label),
    h('span', { className: `sys-val${mono ? ' is-mono' : ''}` }, value),
  );
}

function SysMeter({ label, used, total, unit, raw }) {
  const pct = raw ? used : Math.round((used / total) * 100);
  const display = raw ? `${used}${unit}` : `${used}/${total} ${unit}`;
  return h('div', { className: 'sys-meter' },
    h('div', { className: 'sys-meter-head' },
      h('span', { className: 'sys-key' }, label),
      h('span', { className: 'sys-val' }, display),
    ),
    h('div', { className: 'sys-bar' },
      h('div', { className: 'sys-bar-fill', style: { width: `${pct}%` } }),
      h('div', { className: 'sys-bar-ticks' },
        Array.from({ length: 10 }).map((_, i) => h('span', { key: i })),
      ),
    ),
  );
}

/* ── VoiceVisualizer ──────────────────────────────────────────── */

function VoiceVisualizer({ state, activeAgent }) {
  const bars = Array.from({ length: 11 });
  const labels = {
    idle:       '— STANDBY —',
    listening:  '[ LISTENING · WAKE WORD DETECTED ]',
    processing: '[ PROCESSING · ROUTING TO SPECIALISTS ]',
    speaking:   `[ ${(activeAgent || 'JARVIS').toUpperCase()} RESPONDING ]`,
  };

  const core = state === 'processing'
    ? h('svg', { viewBox: '-30 -30 60 60', className: 'hex', width: 84, height: 84 },
        h('polygon', { points: '0,-24 20.78,-12 20.78,12 0,24 -20.78,12 -20.78,-12', fill: 'none', stroke: 'currentColor', strokeWidth: '1.2' }),
        h('polygon', { points: '0,-14 12.12,-7 12.12,7 0,14 -12.12,7 -12.12,-7', fill: 'none', stroke: 'currentColor', strokeWidth: '0.8', opacity: '0.6', className: 'hex-inner' }),
        h('circle', { cx: 0, cy: 0, r: 2, fill: 'currentColor' }),
        h('circle', { cx: 0, cy: -24, r: 1.5, fill: 'currentColor' }),
        h('circle', { cx: 20.78, cy: 0, r: 1.5, fill: 'currentColor' }),
        h('circle', { cx: -20.78, cy: 0, r: 1.5, fill: 'currentColor' }),
      )
    : h('div', { className: 'viz-bars' },
        bars.map((_, i) => h('span', { key: i, className: 'viz-bar', style: { '--i': i, '--n': bars.length } })),
      );

  return h(Bracket, { label: 'VOICE HUD', status: state.toUpperCase(), className: 'viz-bracket' },
    h('div', { className: `viz viz-${state}` },
      h('div', { className: 'viz-ring viz-ring-1' }),
      h('div', { className: 'viz-ring viz-ring-2' }),
      h('div', { className: 'viz-ring viz-ring-3' }),
      h('div', { className: 'viz-core' }, core),
      h('div', { className: 'viz-readout' },
        h('div', { className: 'viz-label' }, labels[state] || labels.idle),
        h('div', { className: 'viz-meta' },
          h('span', null, 'CH · VOICE'),
          h('span', { className: 'viz-dot' }, '·'),
          h('span', null, 'STT · WHISPER-LARGE-V3'),
          h('span', { className: 'viz-dot' }, '·'),
          h('span', null, 'TTS · KOKORO-EN-GB-M1'),
        ),
      ),
    ),
  );
}

/* ── Conversation ─────────────────────────────────────────────── */

function ConversationView({ messages, agentMap, thinking, routedAgents }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, thinking]);

  const sessionId = useMemo(() => {
    const d = new Date();
    return `SESSION ${d.getFullYear()}${pad2(d.getMonth()+1)}${pad2(d.getDate())}-${pad2(d.getHours())}${pad2(d.getMinutes())}`;
  }, []);

  return h(Bracket, { label: `CONVERSATION · ${sessionId}`, status: `${messages.length} TURNS`, className: 'convo-bracket' },
    h('div', { className: 'convo', ref },
      messages.map((m, i) => h(Message, { key: i, m, agentMap })),
      thinking && h(ThinkingBubble, { agent: agentMap[thinking], routedAgents, agentMap }),
    ),
  );
}

function Message({ m, agentMap }) {
  if (m.role === 'user') {
    return h('div', { className: 'msg msg-user' },
      h('div', { className: 'msg-meta' },
        h('span', { className: 'msg-tag' }, 'ANDREI'),
        h('span', { className: 'msg-ts' }, m.ts),
      ),
      h('div', { className: 'msg-body' }, m.text),
    );
  }
  const a = agentMap[m.agent];
  return h('div', { className: 'msg msg-agent' },
    h('div', { className: 'msg-meta' },
      h('span', { className: 'msg-tag msg-tag-agent' }, `[${((a && a.name) || m.agent).toUpperCase()}]`),
      h('span', { className: 'msg-role' }, a && a.role),
      h('span', { className: 'msg-ts' }, m.ts),
    ),
    h('div', { className: 'msg-body' }, m.text),
  );
}

function ThinkingBubble({ agent, routedAgents, agentMap }) {
  return h('div', { className: 'msg msg-agent msg-thinking' },
    h('div', { className: 'msg-meta' },
      h('span', { className: 'msg-tag msg-tag-agent' }, `[${((agent && agent.name) || 'JARVIS').toUpperCase()}]`),
      h('span', { className: 'msg-role' }, 'orchestrating'),
      h('span', { className: 'msg-ts' }, '···'),
    ),
    h('div', { className: 'thinking-trace' },
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'), ' classify intent',
        h('span', { className: 'trace-dots' }, h('span'), h('span'), h('span')),
      ),
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'), ' route · ',
        ...(routedAgents || []).map((id, i) =>
          h('span', { key: id, className: 'trace-pill' },
            (agentMap[id] && agentMap[id].name) || id,
            i < routedAgents.length - 1 && h('span', { className: 'trace-sep' }, '→'),
          ),
        ),
      ),
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'), ' synthesize',
        h('span', { className: 'trace-dots' }, h('span'), h('span'), h('span')),
      ),
    ),
  );
}

/* ── InputBar ─────────────────────────────────────────────────── */

function InputBar({ value, onChange, onSubmit, mic, onMicToggle, activeAgent, disabled }) {
  const handleKey = (e) => { if (e.key === 'Enter' && !disabled) onSubmit(); };
  return h('div', { className: 'input-bar' },
    h('div', { className: 'input-prefix' },
      h('span', { className: 'input-prompt' }, '›'),
      h('span', { className: 'input-channel' }, `CH:VOICE → ${(activeAgent || 'JARVIS').toUpperCase()}`),
    ),
    h('input', {
      className: 'input-field',
      type: 'text',
      value,
      placeholder: 'Comandă… (text sau wake word „jarvis")',
      onChange: (e) => onChange(e.target.value),
      onKeyDown: handleKey,
      disabled,
      autoFocus: true,
    }),
    h('button', { className: `input-mic${mic ? ' is-on' : ''}`, onClick: onMicToggle, title: 'Microphone' },
      h('svg', { viewBox: '0 0 24 24', width: 16, height: 16 },
        h('rect', { x: 9, y: 3, width: 6, height: 12, rx: 3, fill: 'none', stroke: 'currentColor', strokeWidth: '1.5' }),
        h('path', { d: 'M5 11a7 7 0 0 0 14 0', fill: 'none', stroke: 'currentColor', strokeWidth: '1.5' }),
        h('line', { x1: 12, y1: 18, x2: 12, y2: 22, stroke: 'currentColor', strokeWidth: '1.5' }),
      ),
    ),
    h('button', { className: 'input-send', onClick: disabled ? undefined : onSubmit, disabled },
      h('span', null, 'TRANSMIT'),
      h('svg', { viewBox: '0 0 16 16', width: 12, height: 12 },
        h('path', { d: 'M2 8h10M8 4l4 4-4 4', stroke: 'currentColor', strokeWidth: '1.5', fill: 'none' }),
      ),
    ),
  );
}

/* ── Right panel widgets ──────────────────────────────────────── */

function WeatherIconCloud({ small }) {
  return h('svg', { viewBox: '0 0 32 24', className: 'weather-icon', width: small ? 18 : 36, height: small ? 14 : 28, fill: 'none', stroke: 'currentColor', strokeWidth: small ? 1.2 : 1.5 },
    h('path', { d: 'M8 18h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 18z' }),
  );
}

function WeatherIconRain({ small }) {
  return h('svg', { viewBox: '0 0 32 28', className: 'weather-icon', width: small ? 18 : 36, height: small ? 14 : 28, fill: 'none', stroke: 'currentColor', strokeWidth: small ? 1.2 : 1.5 },
    h('path', { d: 'M8 16h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 16z' }),
    h('line', { x1: 11, y1: 20, x2: 9,  y2: 25 }),
    h('line', { x1: 16, y1: 20, x2: 14, y2: 25 }),
    h('line', { x1: 21, y1: 20, x2: 19, y2: 25 }),
  );
}

function WeatherCard({ data }) {
  if (!data) return null;
  const firstCode = (data.forecast && data.forecast[0] && data.forecast[0].code) || 'cloud';
  const Icon = firstCode === 'rain' ? h(WeatherIconRain) : h(WeatherIconCloud);

  return h(Bracket, { label: 'AMBIENT · WEATHER', status: (data.city || '').toUpperCase() },
    h('div', { className: 'weather' },
      h('div', { className: 'weather-main' },
        h('div', { className: 'weather-temp' },
          h('span', { className: 'weather-deg' }, data.temp),
          h('span', { className: 'weather-unit' }, '°C'),
        ),
        Icon,
      ),
      h('div', { className: 'weather-desc' }, data.desc),
      h('div', { className: 'weather-grid' },
        h('div', null, h('span', { className: 'k' }, 'VÂNT'),  h('span', { className: 'v' }, data.wind)),
        h('div', null, h('span', { className: 'k' }, 'UMID.'), h('span', { className: 'v' }, data.humidity)),
        h('div', null, h('span', { className: 'k' }, 'SIMTE'), h('span', { className: 'v' }, `${data.feels}°C`)),
        h('div', null, h('span', { className: 'k' }, 'UPD'),   h('span', { className: 'v' }, data.updated)),
      ),
      data.forecast && data.forecast.length > 0 &&
        h('div', { className: 'weather-forecast' },
          data.forecast.map((f) =>
            h('div', { key: f.hr, className: 'fc-cell' },
              h('div', { className: 'fc-hr' }, f.hr),
              f.code === 'rain' ? h(WeatherIconRain, { small: true }) : h(WeatherIconCloud, { small: true }),
              h('div', { className: 'fc-t' }, `${f.t}°`),
            ),
          ),
        ),
    ),
  );
}

function CalendarCard({ items }) {
  if (!items) return null;
  const next = items.find((i) => i.state === 'next');
  return h(Bracket, { label: 'CALENDAR · ASTĂZI', status: next ? `NEXT ${next.ts}` : '—' },
    h('div', { className: 'calendar' },
      items.map((it, i) =>
        h('div', { key: i, className: `cal-row cal-${it.state}` },
          h('div', { className: 'cal-marker' }, it.state === 'past' ? '○' : it.state === 'next' ? '▸' : '·'),
          h('div', { className: 'cal-ts' }, it.ts),
          h('div', { className: 'cal-body' },
            h('div', { className: 'cal-title' }, it.title),
            h('div', { className: 'cal-owner' }, `via ${it.owner}`),
          ),
        ),
      ),
    ),
  );
}

function AgentsGrid({ agents, activeAgent, onSelect }) {
  const online = agents.filter((a) => a.status !== 'idle').length;
  return h(Bracket, { label: 'AGENT GRID', status: `${online}/${agents.length} ONLINE` },
    h('div', { className: 'agrid' },
      agents.map((a) =>
        h('button', {
          key: a.id,
          className: `agrid-cell agent-${a.status}${activeAgent === a.id ? ' is-active' : ''}`,
          onClick: () => onSelect(a.id),
          title: `${a.name} — ${a.role}`,
        },
          h('div', { className: 'agrid-dot' }),
          h('div', { className: 'agrid-tag' }, a.name.slice(0, 3).toUpperCase()),
        ),
      ),
    ),
    h('div', { className: 'agrid-legend' },
      h('span', null, h('span', { className: 'dot dot-active', style: { width: 6, height: 6, display: 'inline-block' } }), ' active'),
      h('span', null, h('span', { className: 'dot dot-ready',  style: { width: 6, height: 6, display: 'inline-block' } }), ' ready'),
      h('span', null, h('span', { className: 'dot dot-idle',   style: { width: 6, height: 6, display: 'inline-block' } }), ' idle'),
    ),
  );
}

function HeartbeatFeed({ items, agentMap }) {
  if (!items || items.length === 0) return null;
  return h(Bracket, { label: 'HEARTBEAT · ALERTS', status: `${items.length} ACTIVE` },
    h('div', { className: 'hbfeed' },
      items.map((n) =>
        h('div', { key: n.id, className: `hb hb-${n.level}` },
          h('div', { className: 'hb-bar' }),
          h('div', { className: 'hb-body' },
            h('div', { className: 'hb-head' },
              h('span', { className: 'hb-tag' }, `[${((agentMap[n.agent] && agentMap[n.agent].name) || n.agent || '').toUpperCase()}]`),
              h('span', { className: 'hb-ts' }, n.ts),
            ),
            h('div', { className: 'hb-text' }, n.text),
          ),
        ),
      ),
    ),
  );
}

/* ── API helpers ──────────────────────────────────────────────── */

async function apiAgents() {
  try {
    const r = await fetch('/api/agents');
    const d = await r.json();
    return (d.agents || []).map((a) => {
      const meta = AGENT_META[a.id] || { tier: 'FND', role: '' };
      const status = a.enabled ? (a.has_heartbeat ? 'ready' : 'idle') : 'idle';
      return { ...a, tier: meta.tier, role: meta.role, status };
    });
  } catch { return []; }
}

async function apiStatus() {
  try {
    const r = await fetch('/status');
    return await r.json();
  } catch { return {}; }
}

async function apiDashboard() {
  try {
    const r = await fetch('/dashboard');
    return await r.json();
  } catch { return {}; }
}

/* SSE chat stream */
async function streamChat(message, agentId, callbacks) {
  const { onStart, onToken, onEnd, onError } = callbacks;
  try {
    const resp = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, agent: agentId }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'start') onStart && onStart(evt);
          else if (evt.type === 'token') onToken && onToken(evt);
          else if (evt.type === 'end') onEnd && onEnd(evt);
        } catch { /* skip malformed */ }
      }
    }
    if (buf.startsWith('data: ')) {
      try {
        const evt = JSON.parse(buf.slice(6));
        if (evt.type === 'end') onEnd && onEnd(evt);
      } catch { /* ignore */ }
    }
  } catch (err) {
    onError && onError(err);
  }
}

/* ── App root ─────────────────────────────────────────────────── */

function App() {
  const [agents, setAgents] = useState([]);
  const [activeAgent, setActiveAgent] = useState('jarvis');
  const [messages, setMessages] = useState([{
    role: 'agent', agent: 'jarvis', ts: nowTs(),
    text: 'Bună. Sistemul este operațional. Cu ce pot să te ajut?',
  }]);
  const [draft, setDraft] = useState('');
  const [mic, setMic] = useState(false);
  const [voiceState, setVoiceState] = useState('idle');
  const [thinking, setThinking] = useState(null);
  const [routedAgents, setRoutedAgents] = useState([]);
  const [sys, setSys] = useState(FALLBACK_SYS);
  const [weather, setWeather] = useState(FALLBACK_WEATHER);
  const [calendar, setCalendar] = useState(FALLBACK_CALENDAR);
  const [notifications, setNotifications] = useState(FALLBACK_NOTIFICATIONS);
  const [lmOnline, setLmOnline] = useState(true);
  const [sending, setSending] = useState(false);

  const agentMap = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, a])),
    [agents],
  );

  /* initial data load */
  useEffect(() => {
    apiAgents().then(setAgents);
    apiStatus().then((d) => {
      if (d.sys) setSys({ ...FALLBACK_SYS, ...d.sys });
      if (d.lm_online !== undefined) setLmOnline(d.lm_online);
      if (d.voice_state) setVoiceState(d.voice_state);
    });
    apiDashboard().then((d) => {
      if (d.weather) setWeather(d.weather);
      if (d.calendar) setCalendar(d.calendar);
      if (d.notifications) setNotifications(d.notifications);
    });
  }, []);

  /* poll /status every 10s for live data */
  useEffect(() => {
    const id = setInterval(() => {
      apiStatus().then((d) => {
        if (d.sys) setSys((prev) => ({ ...prev, ...d.sys }));
        if (d.lm_online !== undefined) setLmOnline(d.lm_online);
        if (d.agents) {
          setAgents((prev) => prev.map((a) => {
            const upd = d.agents.find((x) => x.id === a.id);
            return upd ? { ...a, status: upd.status } : a;
          }));
        }
      });
    }, 10000);
    return () => clearInterval(id);
  }, []);

  const submit = async () => {
    if (sending) return;
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    setSending(true);

    const ts = nowTs();
    setMessages((m) => [...m, { role: 'user', ts, text }]);
    setThinking(activeAgent);
    setRoutedAgents(['jarvis', activeAgent].filter((v, i, a) => a.indexOf(v) === i));
    setVoiceState('processing');

    let responderId = activeAgent;
    let responseText = '';

    await streamChat(text, activeAgent, {
      onStart: (evt) => {
        responderId = evt.agent || activeAgent;
        setVoiceState('speaking');
        setThinking(responderId);
      },
      onToken: (evt) => {
        responseText += evt.text || '';
      },
      onEnd: (evt) => {
        const finalText = evt.text || responseText;
        const finalAgent = evt.agent || responderId;
        setMessages((m) => [...m, { role: 'agent', agent: finalAgent, ts: nowTs(), text: finalText }]);
        setThinking(null);
        setRoutedAgents([]);
        setTimeout(() => setVoiceState('idle'), 1400);
        setSending(false);
      },
      onError: (err) => {
        console.error('stream error', err);
        setMessages((m) => [...m, { role: 'agent', agent: 'jarvis', ts: nowTs(), text: 'Eroare de conexiune. Încearcă din nou.' }]);
        setThinking(null);
        setRoutedAgents([]);
        setVoiceState('idle');
        setSending(false);
      },
    });
  };

  const agentsOnline = agents.filter((a) => a.status !== 'idle').length;

  return h('div', { className: 'hud' },
    h('div', { className: 'hud-bg-grid',     'aria-hidden': true }),
    h('div', { className: 'hud-bg-vignette', 'aria-hidden': true }),
    h('div', { className: 'hud-scanline',    'aria-hidden': true }),

    h(TopBar, { activeAgent, voiceState, agentsOnline, agentsTotal: agents.length || 15, lmOnline }),

    h('main', { className: 'hud-main' },
      h(AgentList, { agents, activeAgent, onSelect: setActiveAgent, sys }),

      h('section', { className: 'panel panel-center' },
        h(VoiceVisualizer, { state: voiceState, activeAgent }),
        h(ConversationView, { messages, agentMap, thinking, routedAgents }),
        h(InputBar, {
          value: draft,
          onChange: setDraft,
          onSubmit: submit,
          mic,
          onMicToggle: () => setMic((m) => !m),
          activeAgent,
          disabled: sending,
        }),
      ),

      h('aside', { className: 'panel panel-right' },
        h(WeatherCard, { data: weather }),
        h(CalendarCard, { items: calendar }),
        h(AgentsGrid, { agents, activeAgent, onSelect: setActiveAgent }),
        h(HeartbeatFeed, { items: notifications, agentMap }),
      ),
    ),
  );
}

/* boot */
ReactDOM.createRoot(document.getElementById('root')).render(h(App));
