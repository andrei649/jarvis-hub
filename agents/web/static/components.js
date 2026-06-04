'use strict';

const { createElement: h, useState, useEffect, useRef, useMemo, useLayoutEffect, useCallback } = React;

/* ───────────────────────────── helpers ───────────────────────────── */

const pad2 = (n) => String(n).padStart(2, '0');
const fmtTime = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
const fmtDate = (d) => {
  const days = ['DUM', 'LUN', 'MAR', 'MIE', 'JOI', 'VIN', 'SÂM'];
  const months = ['IAN','FEB','MAR','APR','MAI','IUN','IUL','AUG','SEP','OCT','NOV','DEC'];
  return `${days[d.getDay()]} · ${pad2(d.getDate())} ${months[d.getMonth()]} ${d.getFullYear()}`;
};
const nowTs = () => { const d = new Date(); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()); };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/* ───────────────────────────── Bracket ───────────────────────────── */

function Bracket({ children, className = '', label, status }) {
  return h('div', { className: `bracket ${className}` },
    h('span', { className: 'bk-corner bk-tl' }),
    h('span', { className: 'bk-corner bk-tr' }),
    h('span', { className: 'bk-corner bk-bl' }),
    h('span', { className: 'bk-corner bk-br' }),
    (label || status) && h('div', { className: 'bk-head' },
      label && h('span', { className: 'bk-label' }, label),
      status && h('span', { className: 'bk-status' }, status),
    ),
    h('div', { className: 'bk-body' }, children),
  );
}

/* ───────────────────────────── StatusDot ───────────────────────────── */

function StatusDot({ status, size = 8 }) {
  return h('span', { className: `dot dot-${status}`, style: { width: size, height: size } });
}

/* ───────────────────────────── TopBar ───────────────────────────── */

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow((d) => new Date(d.getTime() + 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return h('div', { className: 'clock' },
    h('div', { className: 'clock-time' }, fmtTime(now)),
    h('div', { className: 'clock-date' }, fmtDate(now), ' · EUROPE/BUCURESTI'),
  );
}

function Badge({ label, value, kind }) {
  return h('div', { className: `badge badge-${kind}` },
    h('span', { className: 'badge-label' }, label),
    h('span', { className: 'badge-value' }, value),
  );
}

/* ─────────────────────── TrustIndicator (H12.10) ───────────────────────
 * Visible, auditable HUD signal for two trust states:
 *   - mic off/on (hardware/software mute, inspired by Voice PE's physical mute)
 *   - strict-local (no cloud calls; everything stays on the machine)
 * Reads /api/trust/status. Clear, not hidden — lives in the topbar chrome.
 */
function TrustIndicator({ trust }) {
  var micOff = trust && trust.mic === 'off';
  var strictLocal = !trust || trust.strict_local;
  var micLabel = _t('comp.trust_mic', 'Mic');
  var localLabel = _t('comp.trust_local', 'Local');
  var micTitle = micOff
    ? _t('comp.trust_mic_off_hint', 'Microphone muted — no audio is captured')
    : _t('comp.trust_mic_on_hint', 'Microphone live — audio can be captured');
  var localTitle = strictLocal
    ? _t('comp.trust_local_on_hint', 'Strict-local: no cloud calls, nothing leaves this machine')
    : _t('comp.trust_local_off_hint', 'Cloud routing available — some requests may leave this machine');
  return h('div', { className: 'trust-indicator', role: 'status', 'aria-label': 'Trust state' },
    h('div', {
      className: 'trust-chip trust-mic ' + (micOff ? 'is-off' : 'is-on'),
      title: micTitle,
      'aria-label': micLabel + ': ' + (micOff ? 'off' : 'on'),
    },
      h('span', { className: 'trust-chip-icon', 'aria-hidden': true }, micOff ? '🔇' : '🎙'),
      h('span', { className: 'trust-chip-label' }, micLabel),
      h('span', { className: 'trust-chip-val' }, micOff ? 'OFF' : 'ON'),
    ),
    h('div', {
      className: 'trust-chip trust-local ' + (strictLocal ? 'is-on' : 'is-off'),
      title: localTitle,
      'aria-label': localLabel + ': ' + (strictLocal ? 'strict' : 'cloud'),
    },
      h('span', { className: 'trust-chip-icon', 'aria-hidden': true }, strictLocal ? '🔒' : '☁'),
      h('span', { className: 'trust-chip-label' }, localLabel),
      h('span', { className: 'trust-chip-val' }, strictLocal ? 'STRICT' : 'CLOUD'),
    ),
  );
}

function TopBar({ activeAgent, voiceState, agentsOnline, agentsTotal, lmOnline, trust, toggles, version, onOpenConsole }) {
  return h('header', { className: 'topbar' },
    h('div', { className: 'topbar-left' },
      h('div', { className: 'logo' },
        h('svg', { viewBox: '0 0 32 32', width: '22', height: '22', className: 'logo-mark' },
          h('circle', { cx: '16', cy: '16', r: '14', fill: 'none', stroke: 'currentColor', strokeWidth: '1', opacity: '0.35' }),
          h('circle', { cx: '16', cy: '16', r: '9', fill: 'none', stroke: 'currentColor', strokeWidth: '1', opacity: '0.7' }),
          h('circle', { cx: '16', cy: '16', r: '4', fill: 'currentColor' }),
          h('line', { x1: '16', y1: '1', x2: '16', y2: '6', stroke: 'currentColor', strokeWidth: '1' }),
          h('line', { x1: '16', y1: '26', x2: '16', y2: '31', stroke: 'currentColor', strokeWidth: '1' }),
          h('line', { x1: '1', y1: '16', x2: '6', y2: '16', stroke: 'currentColor', strokeWidth: '1' }),
          h('line', { x1: '26', y1: '16', x2: '31', y2: '16', stroke: 'currentColor', strokeWidth: '1' }),
        ),
        h('div', { className: 'logo-text' },
          h('div', { className: 'logo-name' }, _t('comp.brand').split('·')[0], h('span', { className: 'logo-dot' }, '·'), _t('comp.brand').split('·')[1]),
          h('div', { className: 'logo-ver' }, 'v' + (version || '…') + ' · BONOBO-WS'),
        ),
      ),
    ),
    h(Clock),
    h('div', { className: 'topbar-right' },
      h(TrustIndicator, { trust: trust }),
      h(Badge, { label: 'Voice', value: voiceState.toUpperCase(), kind: voiceState === 'idle' ? 'dim' : 'active' }),
      h(Badge, { label: 'Agents', value: `${agentsOnline}/${agentsTotal}`, kind: 'active' }),
      h(Badge, { label: _t('comp.lmstudio'), value: lmOnline ? '1234' : _t('comp.offline'), kind: lmOnline ? 'active' : 'alert' }),
      // Console = the home for every feature; ⚙ = settings (console.js/tools.js).
      h('button', { className: 'topbar-btn console-open-btn', onClick: onOpenConsole, title: 'Console — all features' }, '▦ Console'),
      typeof SettingsMenu !== 'undefined' && h(SettingsMenu, { toggles: toggles, version: version }),
    ),
  );
}

/* ───────────────────────────── AgentList ───────────────────────────── */

function SysRow({ label, value, mono }) {
  return h('div', { className: 'sys-row' },
    h('span', { className: 'sys-key' }, label),
    h('span', { className: `sys-val ${mono ? 'is-mono' : ''}` }, value),
  );
}

function SysMeter({ label, used, total, unit, raw }) {
  const pct = raw ? used : Math.round((used / total) * 100);
  return h('div', { className: 'sys-meter' },
    h('div', { className: 'sys-meter-head' },
      h('span', { className: 'sys-key' }, label),
      h('span', { className: 'sys-val' }, raw ? `${used}${unit}` : `${used}/${total} ${unit}`),
    ),
    h('div', { className: 'sys-bar' },
      h('div', { className: 'sys-bar-fill', style: { width: `${pct}%` } }),
      h('div', { className: 'sys-bar-ticks' },
        Array.from({ length: 10 }).map((_, i) => h('span', { key: i })),
      ),
    ),
  );
}

function AgentList({ agents, tiers, activeAgent, onSelect, onDoubleClick, sys }) {
  const grouped = useMemo(() =>
    tiers.map((t) => ({ ...t, agents: agents.filter((a) => a.tier === t.id) })),
    [agents, tiers],
  );
  return h('aside', { className: 'panel panel-left' },
    h(Bracket, { label: _t('comp.agent_network'), status: `${agents.filter(a => a.status !== 'idle').length}/${agents.length}` },
      h('div', { className: 'agent-list' },
        grouped.map((g) =>
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
                onDoubleClick: () => onDoubleClick && onDoubleClick(a.id),
              },
                h(StatusDot, { status: a.status }),
                a.glyph && h('svg', { viewBox: '-12 -12 24 24', width: '14', height: '14', className: 'agent-glyph', style: { position: 'absolute', marginLeft: 22, marginTop: -2 } },
                  h('path', { d: a.glyph, fill: 'none', stroke: 'currentColor', strokeWidth: '1.4', strokeLinejoin: 'round' }),
                ),
                h('div', { className: 'agent-name', style: { paddingLeft: a.glyph ? 20 : 0 } }, a.name || a.id),
                h('div', { className: 'agent-role', style: { paddingLeft: a.glyph ? 20 : 0 } }, a.role || ''),
                h('div', { className: 'agent-model' }, (a.model || '').split('-').slice(0, 2).join('-')),
              ),
            ),
          ),
        ),
      ),
    ),
    h(Bracket, { label: _t('comp.system'), status: _t('comp.nominal'), className: 'sys-bracket' },
      h('div', { className: 'sys-rows' },
        h(SysRow, { label: 'HOST', value: sys.host }),
        h(SysRow, { label: 'CPU', value: sys.cpu }),
        h(SysMeter, { label: 'RAM', used: sys.ram_used, total: sys.ram_total, unit: 'GB' }),
        h(SysMeter, { label: 'VRAM', used: sys.vram_used, total: sys.vram_total, unit: 'GB' }),
        h(SysMeter, { label: _t('comp.gpu_load'), used: sys.gpu_load, total: 100, unit: '%', raw: true }),
        h(SysRow, { label: _t('comp.backend'), value: sys.backend }),
        h(SysRow, { label: _t('comp.model'), value: sys.model, mono: true }),
        h(SysRow, { label: _t('comp.latency'), value: `${(sys.latency || 0).toFixed(1)}s avg` }),
        h(SysRow, { label: _t('comp.uptime'), value: sys.uptime }),
      ),
    ),
  );
}

/* ───────────────────────────── Voice Visualizer ───────────────────────────── */


/* ───────────────────────────── Conversation ───────────────────────────── */

function useTTS() {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef(null);

  const speak = async (text, lang) => {
    if (window.activeJarvisAudio) {
      try { window.activeJarvisAudio.pause(); } catch(e){}
      window.activeJarvisAudio = null;
    }
    // Stop any ongoing playback
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      if (playing) { setPlaying(false); return; }
    }
    setPlaying(true);
    try {
      const resp = await fetch('/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, lang: lang || 'ro' }),
      });
      if (!resp.ok) { console.error('TTS error:', await resp.json()); setPlaying(false); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      window.activeJarvisAudio = audio;
      audio.onended = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
        audioRef.current = null;
        if (window.activeJarvisAudio === audio) window.activeJarvisAudio = null;
      };
      audio.onerror = () => {
        setPlaying(false);
        audioRef.current = null;
        if (window.activeJarvisAudio === audio) window.activeJarvisAudio = null;
      };
      await audio.play();
    } catch (e) {
      console.error('TTS failed:', e);
      setPlaying(false);
    }
  };

  return { speak, playing };
}

function Message({ m, agentMap }) {
  if (m.role === 'user') {
    return h('div', { className: 'msg msg-user' },
      h('div', { className: 'msg-meta' },
        h('span', { className: 'msg-tag' }, _t('comp.andrei')),
        h('span', { className: 'msg-ts' }, m.ts),
      ),
      h('div', { className: 'msg-body' }, m.text),
    );
  }
  const a = agentMap[m.agent];
  const { speak, playing } = useTTS();
  return h('div', { className: 'msg msg-agent' },
    h('div', { className: 'msg-meta' },
      h('span', { className: 'msg-tag msg-tag-agent' }, `[${(a?.name || m.agent || 'unknown').toUpperCase()}]`),
      h('span', { className: 'msg-role' }, a?.role),
      h('span', { className: 'msg-ts' }, m.ts),
      h('button', {
        className: `msg-tts-btn ${playing ? 'is-playing' : ''}`,
        title: playing ? 'Stop' : 'Ascultă',
        onClick: () => speak(m.text, 'ro'),
      },
        h('svg', { viewBox: '0 0 20 20', width: '13', height: '13', fill: 'currentColor' },
          playing
            ? h('rect', { x: '4', y: '4', width: '4', height: '12', rx: '1' },
                h('animate', { attributeName: 'height', values: '12;6;12', dur: '0.8s', repeatCount: 'indefinite' })
              )
            : h('path', { d: 'M3 6.5v7a.5.5 0 0 0 .8.4l5-3.5a.5.5 0 0 0 0-.8l-5-3.5A.5.5 0 0 0 3 6.5zM13 5a1 1 0 0 1 0 1.5A5 5 0 0 1 13 15a1 1 0 0 1 0-1.5 3 3 0 0 0 0-5 1 1 0 0 1 0-1.5zM16 3a1 1 0 0 1 0 1.5A8 8 0 0 1 16 17a1 1 0 0 1 0-1.5 6 6 0 0 0 0-11A1 1 0 0 1 16 3z' })
        ),
      ),
    ),
    h('div', { className: 'msg-body' }, m.text),
  );
}


function ThinkingBubble({ agent, routedAgents, agentMap }) {
  return h('div', { className: 'msg msg-agent msg-thinking' },
    h('div', { className: 'msg-meta' },
      h('span', { className: 'msg-tag msg-tag-agent' }, `[${(agent?.name || 'JARVIS').toUpperCase()}]`),
      h('span', { className: 'msg-role' }, 'orchestrating'),
      h('span', { className: 'msg-ts' }, '···'),
    ),
    h('div', { className: 'thinking-trace' },
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'),
        ' classify intent',
        h('span', { className: 'trace-dots' }, h('span'), h('span'), h('span')),
      ),
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'),
        ' route · ',
        routedAgents.map((id, i) =>
          h('span', { key: id, className: 'trace-pill' },
            agentMap[id]?.name || id,
            i < routedAgents.length - 1 && h('span', { className: 'trace-sep' }, '→'),
          ),
        ),
      ),
      h('div', { className: 'trace-line' },
        h('span', { className: 'trace-arrow' }, '›'),
        ' synthesize',
        h('span', { className: 'trace-dots' }, h('span'), h('span'), h('span')),
      ),
    ),
  );
}

function ConversationView({ messages, agentMap, thinking, routedAgents }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, thinking]);
  return h(Bracket, { label: `${_t('comp.conversation')}20260527-0723`, status: `${messages.length}${_t('comp.turns')}`, className: 'convo-bracket' },
    h('div', { className: 'convo', ref },
      messages.map((m, i) => h(Message, { key: i, m, agentMap })),
      thinking && h(ThinkingBubble, { agent: agentMap[thinking] || { name: thinking }, routedAgents, agentMap }),
    ),
  );
}

/* ───────────────────────────── Input bar ───────────────────────────── */

function InputBar({ value, onChange, onSubmit, mic, onMicToggle, activeAgent, disabled }) {
  return h('div', { className: 'input-bar' },
    h('div', { className: 'input-prefix' },
      h('span', { className: 'input-prompt' }, '›'),
      h('span', { className: 'input-channel' }, `CH:VOICE → ${activeAgent.toUpperCase()}`),
    ),
    h('input', {
      className: 'input-field',
      type: 'text',
      value,
      placeholder: _t('comp.input_placeholder'),
      onChange: (e) => onChange(e.target.value),
      onKeyDown: (e) => { if (e.key === 'Enter') onSubmit(); },
      autoFocus: true,
      disabled,
    }),
    h('button', { className: `input-mic ${mic ? 'is-on' : ''}`, onClick: onMicToggle, title: _t('comp.microphone'), disabled },
      h('svg', { viewBox: '0 0 24 24', width: '16', height: '16' },
        h('rect', { x: '9', y: '3', width: '6', height: '12', rx: '3', fill: 'none', stroke: 'currentColor', strokeWidth: '1.5' }),
        h('path', { d: 'M5 11a7 7 0 0 0 14 0', fill: 'none', stroke: 'currentColor', strokeWidth: '1.5' }),
        h('line', { x1: '12', y1: '18', x2: '12', y2: '22', stroke: 'currentColor', strokeWidth: '1.5' }),
      ),
    ),
    h('button', { className: 'input-send', onClick: onSubmit, disabled },
      h('span', null, _t('comp.transmit')),
      h('svg', { viewBox: '0 0 16 16', width: '12', height: '12' },
        h('path', { d: 'M2 8h10M8 4l4 4-4 4', stroke: 'currentColor', strokeWidth: '1.5', fill: 'none' }),
      ),
    ),
  );
}

/* ───────────────────────────── Ambient panels ───────────────────────────── */

const WeatherIcon = {
  cloud: ({ className, small }) =>
    h('svg', { viewBox: '0 0 32 24', className, width: small ? 18 : 36, height: small ? 14 : 28, fill: 'none', stroke: 'currentColor', strokeWidth: small ? 1.2 : 1.5 },
      h('path', { d: 'M8 18h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 18z' }),
    ),
  rain: ({ className, small }) =>
    h('svg', { viewBox: '0 0 32 28', className, width: small ? 18 : 36, height: small ? 14 : 28, fill: 'none', stroke: 'currentColor', strokeWidth: small ? 1.2 : 1.5 },
      h('path', { d: 'M8 16h16a5 5 0 0 0 0-10 6 6 0 0 0-11.8-1.4A4.5 4.5 0 0 0 8 16z' }),
      h('line', { x1: '11', y1: '20', x2: '9', y2: '25' }),
      h('line', { x1: '16', y1: '20', x2: '14', y2: '25' }),
      h('line', { x1: '21', y1: '20', x2: '19', y2: '25' }),
    ),
};

function WeatherCard({ data }) {
  const fc0 = data.forecast && data.forecast[0];
  const Icon = (fc0 && WeatherIcon[fc0.code]) || WeatherIcon.cloud;
  return h(Bracket, { label: _t('comp.weather'), status: data.city.toUpperCase() },
    h('div', { className: 'weather' },
      h('div', { className: 'weather-main' },
        h('div', { className: 'weather-temp' },
          h('span', { className: 'weather-deg' }, data.temp),
          h('span', { className: 'weather-unit' }, '°C'),
        ),
        h(Icon, { className: 'weather-icon' }),
      ),
      h('div', { className: 'weather-desc' }, data.desc),
      h('div', { className: 'weather-grid' },
        h('div', null, h('span', { className: 'k' }, 'VÂNT'), h('span', { className: 'v' }, data.wind)),
        h('div', null, h('span', { className: 'k' }, 'UMID.'), h('span', { className: 'v' }, data.humidity)),
        h('div', null, h('span', { className: 'k' }, _t('comp.simte')), h('span', { className: 'v' }, `${data.feels}°C`)),
        h('div', null, h('span', { className: 'k' }, 'UPD'), h('span', { className: 'v' }, data.updated)),
      ),
      h('div', { className: 'weather-forecast' },
        data.forecast.map((f) => {
          const FI = WeatherIcon[f.code] || WeatherIcon.cloud;
          const hr = f.hr || '';
          const t = f.t ?? '';
          return h('div', { key: hr, className: 'fc-cell' },
            h('div', { className: 'fc-hr' }, hr),
            h(FI, { className: 'fc-icon', small: true }),
            h('div', { className: 'fc-t' }, `${t}°`),
          );
        }),
      ),
    ),
  );
}

function CalendarCard({ items }) {
  const next = items.find((i) => i.state === 'next');
  return h(Bracket, { label: _t('comp.calendar'), status: next ? `${_t('comp.next')}${next.ts}` : '—' },
    h('div', { className: 'calendar' },
      items.map((it, i) =>
        h('div', { key: i, className: `cal-row cal-${it.state}` },
          h('div', { className: 'cal-marker' }, it.state === 'past' ? '○' : it.state === 'next' ? '▸' : '·'),
          h('div', { className: 'cal-ts' }, it.ts),
          h('div', { className: 'cal-body' },
            h('div', { className: 'cal-title' }, it.title),
            h('div', { className: 'cal-owner' }, `via ${it.owner || '\u2014'}`),
          ),
        ),
      ),
    ),
  );
}

function AgentsGrid({ agents, activeAgent, onSelect }) {
  const online = agents.filter((a) => a.status !== 'idle').length;
  return h(Bracket, { label: _t('comp.agent_grid'), status: `${online}/${agents.length}${_t('comp.online_suffix')}` },
    h('div', { className: 'agrid' },
      agents.map((a) =>
        h('button', {
          key: a.id,
          className: `agrid-cell agent-${a.status} ${activeAgent === a.id ? 'is-active' : ''}`,
          onClick: () => onSelect(a.id),
          title: `${a.name} — ${a.role}`,
        },
          h('div', { className: 'agrid-dot' }),
          h('div', { className: 'agrid-tag' }, a.name.slice(0, 3).toUpperCase()),
        ),
      ),
    ),
    h('div', { className: 'agrid-legend' },
      h('span', null, h('span', { className: 'dot dot-active' }), ' active'),
      h('span', null, h('span', { className: 'dot dot-ready' }), ' ready'),
      h('span', null, h('span', { className: 'dot dot-idle' }), ' idle'),
    ),
  );
}

function HeartbeatFeed({ items, agentMap }) {
  return h(Bracket, { label: _t('comp.heartbeat'), status: `${items.length}${_t('comp.active')}` },
    h('div', { className: 'hbfeed' },
      items.map((n) =>
        h('div', { key: n.id, className: `hb hb-${n.level}` },
          h('div', { className: 'hb-bar' }),
          h('div', { className: 'hb-body' },
            h('div', { className: 'hb-head' },
              h('span', { className: 'hb-tag' }, `[${(agentMap[n.agent]?.name || n.agent).toUpperCase()}]`),
              h('span', { className: 'hb-ts' }, n.ts),
            ),
            h('div', { className: 'hb-text' }, n.text),
          ),
        ),
      ),
    ),
  );
}

/* ───────────────────────────── exports ───────────────────────────── */

Object.assign(window, {
  TopBar, AgentList, ConversationView, InputBar,
  WeatherCard, CalendarCard, AgentsGrid, HeartbeatFeed,
  Bracket, StatusDot,
});
