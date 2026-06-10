// @ts-nocheck
/* HUD v2 · APP ROOT — P0: shell + cockpit are live; the other modes render an
   honest placeholder and get ported from the prototype in the next phase. */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { V2 } from './data';
import { useClock, fmtTimeShort, Icon, ICONS, Glyph } from './primitives';
import { TopBar, Ticker, Rail, Tabs, RosterColumn, ContextColumn, Palette, Ambient } from './shell';
import { NetworkBrain } from './network';
import { Conversation, CognitionStream, InputBar, buildTrace, traceFromCognition } from './cockpit';
import { useVoice } from './voice';
import { loadJarvisData } from './api/loaders';
import { useLiveModes } from './api/live';
import { postStream, apiGet } from './api/client';
import { AgentsMode, Dossier, TrustMode, MemoryMode } from './modes';
import { AutonomyMode, BuildMode, ObserveMode, InteropMode } from './modes2';
import { ChatMode, CommsMode, AdminMode } from './modes3';
import { FinanceMode, HealthMode, KnowledgeMode, FamilyMode } from './modes4';
import { ConsoleOverlay } from './gap';

function ModeStub({ label }) {
  return (
    <div className="workzone full" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel" style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div style={{ textAlign: 'center', color: 'var(--ink-3)', maxWidth: 360 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '.18em', color: 'var(--accent-light)' }}>{String(label).toUpperCase()}</div>
          <div style={{ marginTop: 12, fontSize: 13, color: 'var(--ink-2)' }}>Mode wiring in progress — ported from the prototype next.</div>
          <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10 }}>P0 · shell + cockpit live · build green</div>
        </div>
      </div>
    </div>
  );
}

// Client-only UI prefs persisted to localStorage (mirrors v1). Pure look/feel —
// no backend involved — so the HUD remembers density/scanline/dotgrid/theme across
// reloads. Each is read lazily with a safe default and written back on change.
const UI_PREFS = { look: 'obsidian', density: 'normal', scanline: 'on', dotgrid: 'off' };
function loadPref(key, def) { try { return localStorage.getItem('hud.' + key) || def; } catch { return def; } }

function App() {
  // tweak axes — persisted client-side prefs (restored regression: v1 remembered
  // these). Accent + language are user-changeable via the command palette / top bar.
  const [look, setLook] = useState(() => loadPref('look', UI_PREFS.look));
  const [density, setDensity] = useState(() => loadPref('density', UI_PREFS.density));
  const [scanline, setScanline] = useState(() => loadPref('scanline', UI_PREFS.scanline));
  const [dotgrid, setDotgrid] = useState(() => loadPref('dotgrid', UI_PREFS.dotgrid));
  // P5 — honor the OS reduced-motion preference (gates packets/ambient animation)
  const motion = (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) ? 'calm' : 'lively';
  const ia = 'rail';
  const [accent, setAccent] = useState(() => { try { return localStorage.getItem('hud.accent') || 'cyan'; } catch { return 'cyan'; } });
  const [lang, setLang] = useState(() => { try { return localStorage.getItem('hud.lang') || 'en'; } catch { return 'en'; } });
  // DEMO mode (opt-in, watermarked): OFF by default → the HUD shows ONLY real
  // backend data + honest empty states; ON → fills the seeded demo corpus.
  const [demo, setDemo] = useState(() => { try { return localStorage.getItem('hud.demo') === '1' || /[?&]demo=1/.test(window.location.search); } catch { return false; } });
  // Voice preferences (persisted): mode = hands-free | ptt; tts = server | browser | off;
  // lang = auto | ro | en; barge = off | on (experimental talk-over interrupt)
  const [voiceCfg, setVoiceCfg] = useState(() => { const d = { mode: 'hands-free', tts: 'server', lang: 'auto', barge: 'off' }; try { return { ...d, ...JSON.parse(localStorage.getItem('hud.voice') || '{}') }; } catch { return d; } });
  const setVoice = (patch) => setVoiceCfg((c) => ({ ...c, ...patch }));

  const [mode, setMode] = useState('cockpit');
  const [agents, setAgents] = useState(demo ? V2.AGENTS : []);
  const [activeId, setActiveId] = useState('jarvis');
  const [focusId, setFocusId] = useState(null);
  const [messages, setMessages] = useState(demo ? V2.SEED_MESSAGES : []);
  const [thinking, setThinking] = useState(null);
  const [trace, setTrace] = useState(null);
  const [centerTab, setCenterTab] = useState('conversation');
  // mic/voice state is owned by the useVoice loop (defined below), not a bare flag
  const [palette, setPalette] = useState(false);
  const [ambient, setAmbient] = useState(false);
  const [provModal, setProvModal] = useState(null);
  const [dossier, setDossier] = useState(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [decisions, setDecisions] = useState(() => demo ? V2.DECISIONS.map((d, i) => ({ ...d, _id: 'd' + i })) : []);
  // P1 live-data state — empty by default (honest); demo pre-seeds, backend overwrites
  const [ticker, setTicker] = useState(demo ? V2.TICKER : []);
  const [tasks, setTasks] = useState([]); // autonomy queue → network task-fan (/tasks)
  const [weather, setWeather] = useState(demo ? V2.WEATHER : null);
  const [calendar, setCalendar] = useState(demo ? V2.CALENDAR : []);
  const [heartbeat, setHeartbeat] = useState(demo ? V2.HEARTBEAT : []);
  const [sys, setSys] = useState(null);
  const [live, setLive] = useState(false);
  const [serverUp, setServerUp] = useState(false);
  const [llm, setLlm] = useState({ state: 'unknown', model: null });
  const [trust, setTrust] = useState({ mic: 'on', strict_local: false });
  const [locality, setLocality] = useState(null); // {local_pct} from real runs, or null
  const baseAgents = useRef(demo ? V2.AGENTS : []);

  const clock = useClock();
  const t = V2.I18N[lang];
  // %-local is honest, in priority order: a real measured split from /api/analytics/
  // locality (the brand metric, from run-history routes) → strict-local proof (100%)
  // → demo sample → unknown (hidden, never faked).
  const localPct = (locality && locality.local_pct != null) ? locality.local_pct
    : trust.strict_local ? 100 : (demo ? 87 : null);
  const liveModes = useLiveModes(); // P4: stream live data into the capability modes; reports which keys are live
  useEffect(() => { try { localStorage.setItem('hud.accent', accent); } catch { /* ignore */ } }, [accent]); // P5 persist
  useEffect(() => { try { localStorage.setItem('hud.lang', lang); } catch { /* ignore */ } }, [lang]);
  useEffect(() => { try { localStorage.setItem('hud.look', look); } catch { /* ignore */ } }, [look]); // client-only UI prefs
  useEffect(() => { try { localStorage.setItem('hud.density', density); } catch { /* ignore */ } }, [density]);
  useEffect(() => { try { localStorage.setItem('hud.scanline', scanline); } catch { /* ignore */ } }, [scanline]);
  useEffect(() => { try { localStorage.setItem('hud.dotgrid', dotgrid); } catch { /* ignore */ } }, [dotgrid]);
  useEffect(() => { try { localStorage.setItem('hud.demo', demo ? '1' : '0'); } catch { /* ignore */ } }, [demo]);
  useEffect(() => { try { localStorage.setItem('hud.voice', JSON.stringify(voiceCfg)); } catch { /* ignore */ } }, [voiceCfg]);
  // Re-seed (or clear) the demo-only cockpit corpus when DEMO toggles at runtime.
  useEffect(() => {
    setDecisions(demo ? V2.DECISIONS.map((d, i) => ({ ...d, _id: 'd' + i })) : []);
    setMessages(demo ? V2.SEED_MESSAGES : []);
  }, [demo]);

  // hotkeys: number keys jump modes, ⌘K palette, A ambient
  useEffect(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return; }
      if (ambient) return;
      const tag = (e.target && e.target.tagName ? e.target.tagName : '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;
      const m = { '1': 'cockpit', '2': 'agents', '3': 'trust', '4': 'memory', '5': 'autonomy', '6': 'build', '7': 'observe', '8': 'interop', '9': 'chat', '0': 'comms' };
      if (m[e.key]) setMode(m[e.key]);
      else if (e.key.toLowerCase() === 'a') setAmbient(true);
      else if (e.key === '`') { e.preventDefault(); setConsoleOpen((c) => !c); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [ambient]);

  // NTH-1 — live cognition scoring over SSE (/api/cognition/stream). EventSource
  // can't send the user token, so this only attaches where the guard is
  // localhost-exempt; elsewhere it errors out silently and the post-turn
  // /api/cognition snapshot (runTurn) remains the source. Frames only arrive when
  // the snapshot CHANGES, so this never overwrites a fresher post-turn trace with
  // stale data — it upgrades the cockpit to routing-decisions-as-they-happen.
  useEffect(() => {
    if (demo || typeof EventSource === 'undefined') return undefined;
    let es;
    try { es = new EventSource('/api/cognition/stream'); } catch { return undefined; }
    es.onmessage = (ev) => {
      try {
        const f = JSON.parse(ev.data);
        const cog = f && f.type === 'cognition' ? f.cognition : null;
        if (!cog) return;
        const tr = traceFromCognition(cog, '');
        setTrace({ stages: tr.stages.map((s) => ({ ...s, state: 'done' })) });
      } catch { /* malformed frame — ignore */ }
    };
    es.onerror = () => { try { es.close(); } catch { /* ignore */ } };
    return () => { try { es.close(); } catch { /* ignore */ } };
  }, [demo]);

  // submit → cognition flow (mock timeline; real SSE arrives in P2)
  const timers = useRef([]);

  // offline fallback — the prototype's staged timeline so the cockpit still demos
  const runMock = useCallback((text) => {
    timers.current.forEach(clearTimeout); timers.current = [];
    const tr = buildTrace(text);
    setTrace({ stages: tr.stages.map((s) => ({ ...s, state: '' })) });
    setCenterTab('cognition');
    setAgents((prev) => prev.map((a) => (tr.selected.includes(a.id) ? { ...a, status: 'busy' } : a)));
    setThinking({ label: t.think + ' · classify', route: null });
    const seq = [
      [250, () => setTrace((p) => mark(p, 0, 'on'))],
      [700, () => { setTrace((p) => mark(p, 0, 'done', 1, 'on')); setThinking({ label: t.think + ' · route', route: tr.selected.map((s) => s.toUpperCase()) }); }],
      [1400, () => { setTrace((p) => mark(p, 1, 'done', 2, 'on')); setThinking({ label: t.think + ' · gather', route: tr.selected.map((s) => s.toUpperCase()) }); }],
      [2300, () => { setTrace((p) => mark(p, 2, 'done', 3, 'on')); setThinking({ label: t.think + ' · synthesize', route: tr.selected.map((s) => s.toUpperCase()) }); }],
      [3300, () => {
        setTrace((p) => mark(p, 3, 'done'));
        setThinking(null);
        setMessages((m) => [...m, { role: 'agent', who: 'jarvis', role_label: 'Prime Orchestrator', ts: fmtTimeShort(new Date()), text: replyFor(text, tr), prov: { agents: tr.selected, plugins: pluginsFor(text), local: true, conf: +tr.conf.toFixed(2) } }]);
        setAgents(baseAgents.current);
      }],
    ];
    seq.forEach(([ms, fn]) => timers.current.push(setTimeout(fn, ms)));
  }, [t]);

  // P2 — real streaming turn: POST /chat/stream token-by-token, then pull the live
  // /api/cognition snapshot for the trace + provenance. Falls back to runMock offline.
  // P2 — real streaming turn. Resolves with the FINAL reply text so the voice loop can
  // speak it. On /chat/stream failure: honest system notice (or the DEMO staged mock).
  const runTurn = useCallback((text) => new Promise((resolve) => {
    timers.current.forEach(clearTimeout); timers.current = [];
    setMessages((m) => [...m, { role: 'user', text, ts: fmtTimeShort(new Date()) }]);
    setCenterTab('conversation');
    setThinking({ label: t.think + ' · routing', route: null });
    let streamed = '';
    let idx = -1;
    postStream('/chat/stream', { message: text, agent: activeId }, (evt) => {
      if (evt.type === 'start') {
        setThinking({ label: t.think, route: [String(evt.agent || activeId).toUpperCase()] });
        setMessages((m) => { idx = m.length; return [...m, { role: 'agent', who: evt.agent || activeId, role_label: '', ts: fmtTimeShort(new Date()), text: '' }]; });
      } else if (evt.type === 'token') {
        streamed += evt.text || '';
        setMessages((m) => { const c = [...m]; if (idx >= 0 && c[idx]) c[idx] = { ...c[idx], text: streamed }; return c; });
      } else if (evt.type === 'end') {
        const finalText = evt.text || streamed;
        setMessages((m) => { const c = [...m]; if (idx >= 0 && c[idx]) c[idx] = { ...c[idx], text: finalText, who: evt.agent || activeId }; else c.push({ role: 'agent', who: evt.agent || activeId, ts: fmtTimeShort(new Date()), text: finalText }); return c; });
        setThinking(null);
        resolve(finalText);
        apiGet('/api/cognition').then((cog) => {
          const tr = traceFromCognition(cog, text);
          setTrace({ stages: tr.stages.map((s) => ({ ...s, state: 'done' })) });
          // HONESTY: real plugin reads + locality from the cognition snapshot — never a
          // client-side guess. Unknown locality renders as "—" instead of a false claim.
          const dloc = (cog && cog.decision) || {};
          const reads = (cog && (cog.plugins || dloc.plugins)) || [];
          const localKnown = typeof dloc.local === 'boolean' ? dloc.local : (cog && typeof cog.local === 'boolean' ? cog.local : undefined);
          setMessages((m) => { const c = [...m]; const j = idx >= 0 ? idx : c.length - 1; if (c[j]) c[j] = { ...c[j], prov: { agents: tr.selected, plugins: reads, local: localKnown, conf: +(tr.conf || 0).toFixed(2) } }; return c; });
        }).catch(() => {});
      }
    }).catch(() => {
      // HONESTY: never fabricate a reply. The staged mock is for DEMO only; otherwise
      // surface the real failure (e.g. no model loaded / backend offline).
      if (demo) { runMock(text); resolve(''); return; }
      setThinking(null);
      setMessages((m) => [...m, { role: 'agent', who: 'system', role_label: '', ts: fmtTimeShort(new Date()), text: '⚠ No reply — the model backend is unreachable or no model is loaded. Load a model in LM Studio, or enable ◐ DEMO to preview the interface.' }]);
      resolve('');
    });
  }), [t, activeId, runMock, demo]);

  const submit = useCallback((text) => { runTurn(text); }, [runTurn]);
  // Hands-free voice loop: mic → local Whisper → runTurn → speak the reply, repeat.
  const voice = useVoice({ lang: voiceCfg.lang === 'auto' ? lang : voiceCfg.lang, mode: voiceCfg.mode, ttsSource: voiceCfg.tts, micMuted: trust.mic === 'off', barge: voiceCfg.barge === 'on', onTurn: runTurn });

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  // P1 — load live data and poll every 30s; falls back to the seeded mock when
  // the backend is unreachable, so the HUD never blanks (recall-never-hard-fails).
  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const d = await loadJarvisData(demo);
        if (!alive) return;
        setAgents(d.agents); baseAgents.current = d.agents;
        setTicker(d.ticker); setTasks(Array.isArray(d.tasks) ? d.tasks : []); setWeather(d.weather); setCalendar(d.calendar);
        setHeartbeat(d.heartbeat); setSys(d.sys); setLive(!!d.live);
        setServerUp(!!d.serverUp); setLlm(d.llm || { state: 'unknown', model: null });
        if (d.trust) setTrust(d.trust);
        if (!demo) {
          // Real %-local from run-history routes; failure leaves it null (meter hides).
          apiGet('/api/analytics/locality').then((l) => { if (alive) setLocality(l); }).catch(() => {});
        }
      } catch { /* unreachable — keep current */ }
    }
    refresh();
    const iv = setInterval(refresh, 30000);
    return () => { alive = false; clearInterval(iv); };
  }, [demo]);
  const dismissDecision = (id) => setDecisions((ds) => ds.filter((d) => d._id !== id));

  const rootAttrs = {
    className: 'hud-root',
    'data-look': look, 'data-accent': accent, 'data-density': density,
    'data-motion': motion, 'data-scanline': scanline, 'data-dotgrid': dotgrid,
  };

  return (
    <div {...rootAttrs}>
      <div className="tex-layer tex-glow"></div>
      <div className="tex-layer tex-dotgrid"></div>
      <div className="tex-layer tex-scan"></div>
      <div className="tex-scanbar"></div>

      <div className="shell">
        {demo && <DemoBanner onExit={() => setDemo(false)} />}
        <TopBar clock={clock} lang={lang} setLang={setLang} accent={accent} agents={agents} localPct={localPct} live={live} trust={trust}
          llm={llm} demo={demo} setDemo={setDemo} serverUp={serverUp}
          onPalette={() => setPalette(true)} onAmbient={() => setAmbient(true)} t={t} />
        <Ticker items={ticker} t={t} hidden={mode === 'chat'} />

        <div className="main" data-ia={ia}>
          {ia === 'rail' && <Rail mode={mode} setMode={setMode} t={t} />}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>
            {ia === 'tabs' && <Tabs mode={mode} setMode={setMode} t={t} />}

            {mode === 'cockpit' ? (
              <div className="workzone cockpit" style={{ flex: 1, minHeight: 0 }}>
                <RosterColumn agents={agents} activeId={activeId} onSelect={(id) => { setActiveId(id); setDossier(id); }} sys={sys} llm={llm} demo={demo} t={t} />
                <div className="col" style={{ minHeight: 0 }}>
                  <div className="panel" style={{ flex: '1.3 1 0', minHeight: 0 }}>
                    <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
                    <div className="panel-head"><Icon d={ICONS.brain} size={14} /><span className="ttl">{t.network}</span><span className="st">focus mode</span></div>
                    <NetworkBrain agents={agents} tasks={tasks} activeId={activeId} onSelect={(id) => setActiveId(id)}
                      focusId={focusId} setFocusId={setFocusId} motion={motion} t={t} />
                  </div>
                  <div className="panel" style={{ flex: '1 1 0', minHeight: 0 }}>
                    <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
                    <div className="center-tabs">
                      <button className={'center-tab' + (centerTab === 'conversation' ? ' active' : '')} onClick={() => setCenterTab('conversation')}>{t.conversation}{thinking && <span className="pip"></span>}</button>
                      <button className={'center-tab' + (centerTab === 'cognition' ? ' active' : '')} onClick={() => setCenterTab('cognition')}>{t.cognition}{trace && !thinking && <span className="pip"></span>}</button>
                    </div>
                    {centerTab === 'conversation'
                      ? <Conversation messages={messages} thinking={thinking} onProv={setProvModal} lang={lang} t={t} />
                      : <CognitionStream trace={trace} t={t} />}
                    <InputBar onSubmit={submit} mic={voice.active} setMic={voice.toggle} voice={voice} cfg={voiceCfg} onCfg={setVoice} micMuted={trust.mic === 'off'} t={t} />
                  </div>
                </div>
                <ContextColumn decisions={decisions} onDecision={dismissDecision} weather={weather} calendar={calendar} heartbeat={heartbeat} demo={demo} t={t} />
              </div>
            ) : mode === 'agents' ? (
              <div className="workzone wide" style={{ flex: 1, minHeight: 0 }}>
                <AgentsMode agents={agents} onOpen={(id) => { setActiveId(id); setDossier(id); }} t={t} />
                <ContextColumn decisions={decisions} onDecision={dismissDecision} weather={weather} calendar={calendar} heartbeat={heartbeat} demo={demo} t={t} />
              </div>
            ) : mode === 'chat' ? (
              <div className="workzone full" style={{ flex: 1, minHeight: 0 }}>
                <ChatMode messages={messages} thinking={thinking} onSubmit={submit} onProv={setProvModal} mic={voice.active} setMic={voice.toggle} lang={lang} t={t} />
              </div>
            ) : (
              <div className="workzone full" style={{ flex: 1, minHeight: 0 }}>
                {modeComponent(mode, t, { demo, live: liveModes.live, onDemo: () => setDemo(true), localPct, activeId, onOpen: (id) => { setActiveId(id); setDossier(id); } })}
              </div>
            )}
          </div>
        </div>
      </div>

      {provModal && <ProvModal prov={provModal} onClose={() => setProvModal(null)} />}
      {dossier && <Dossier id={dossier} onClose={() => setDossier(null)} onOpen={setDossier} />}
      {consoleOpen && <ConsoleOverlay onClose={() => setConsoleOpen(false)} />}
      <button className="tool-btn" onClick={() => setConsoleOpen(true)} title="console (`)"
        style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 50 }}>▦ CONSOLE</button>
      <Palette open={palette} onClose={() => setPalette(false)} onMode={setMode}
        setAccent={setAccent} setLang={setLang} onAmbient={() => { setPalette(false); setAmbient(true); }}
        ui={{ density, setDensity, scanline, setScanline, dotgrid, setDotgrid }} t={t} />
      {ambient && <Ambient onExit={() => setAmbient(false)} clock={clock} lang={lang} agents={agents} decisions={decisions} motion={motion} localPct={localPct} t={t} />}
    </div>
  );
}

function mark(trace, i, state, j, jstate) {
  if (!trace) return trace;
  const stages = trace.stages.map((s, k) => (k === i ? { ...s, state } : (j !== undefined && k === j) ? { ...s, state: jstate } : s));
  return { ...trace, stages };
}
function pluginsFor(text) {
  const low = text.toLowerCase(); const p = [];
  if (/calendar|meeting|schedule/.test(low)) p.push('google-calendar');
  if (/email|mail|inbox/.test(low)) p.push('gmail');
  if (/weather/.test(low)) p.push('weather');
  if (/music|playlist/.test(low)) p.push('spotify');
  if (p.length === 0) p.push('google-calendar', 'gmail');
  return p;
}
function replyFor(text, tr) {
  const a = tr.selected[0];
  const map = {
    pepper: 'Pepper has it — your calendar is reconciled and the **14:00 Raiffeisen review** is protected with prep at 13:15.',
    stark: 'Stark pulled the numbers — **Digitaholic MRR is +6.2% WoW**; I flagged the missing churn-cohort slide for the review.',
    vision: "Vision is on it — indexing sources now; I'll have a cited brief in your queue within the hour.",
    veronica: 'Veronica drafted it — held for your review since Ultron flagged a **client name** as sensitive.',
    gecko: "Gecko's watching the markets — EUR/RON steady at 4.97; idle cash is **€4.2k over buffer**, sweep available.",
    hercules: "Hercules logged it — your sleep was 7h12m; tonight's plan is a light mobility session.",
    frigga: 'Frigga keeps that local — noted privately, nothing left the device.',
    friday: 'Friday compiled your brief — **6 items ranked**, weather clear, good day to cycle in.',
    jerome: 'Jerome cued the soundtrack — focus playlist matched to your morning.',
    jarvis: "Understood. I'll handle that directly and keep everything on-device.",
  };
  return map[a] || map.jarvis;
}
function DemoBanner({ onExit }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, padding: '4px 0',
      background: 'repeating-linear-gradient(45deg, rgba(245,158,11,.16) 0 12px, rgba(245,158,11,.05) 12px 24px)',
      borderBottom: '1px solid rgba(245,158,11,.5)', fontFamily: 'var(--font-mono)', fontSize: 10.5, letterSpacing: '.18em', color: 'var(--amber)' }}>
      ◐ DEMO DATA — seeded sample, not your live backend
      <button className="tool-btn" onClick={onExit}>exit demo</button>
    </div>
  );
}
function ProvModal({ prov, onClose }) {
  return (
    <div className="pal-scrim" onClick={onClose} style={{ alignItems: 'center', paddingTop: 0 }}>
      <div className="pal" onClick={(e) => e.stopPropagation()} style={{ width: 'min(440px,92vw)' }}>
        <div className="pal-input" style={{ borderBottom: '1px solid var(--panel-line)' }}><span className="pc"><Icon d={ICONS.shield} size={16} /></span><span style={{ fontSize: 14, letterSpacing: '.04em' }}>PROVENANCE</span><span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--green)' }}>conf {prov.conf}</span></div>
        <div style={{ padding: 18 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', marginBottom: 8 }}>AGENTS CONSULTED</div>
          <div className="dep-links" style={{ marginBottom: 16 }}>{prov.agents.map((a) => <span key={a} className="dep-link" style={{ cursor: 'default' }}><Glyph id={a} size={12} />{a}</span>)}</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', marginBottom: 8 }}>PLUGIN READS</div>
          <div className="dep-links" style={{ marginBottom: 16 }}>{prov.plugins.map((p) => <span key={p} className="dep-link" style={{ cursor: 'default' }}>{p}</span>)}</div>
          <div className="verified-row"><Icon d={ICONS.shield} size={13} /> {prov.local === true ? '100% on-device · no cloud egress' : prov.local === false ? 'cloud-assisted' : 'locality not reported'}</div>
        </div>
      </div>
    </div>
  );
}

// Which V2 keys must carry REAL backend data for a capability mode to be "live".
// Modes absent here (build/comms/finance/health/knowledge/family) have no backend
// wired yet, so they are demo-only previews until one exists.
const MODE_LIVE_KEYS = {
  trust: ['AUDIT_CHAIN', 'PAYMENTS'], memory: ['MEMORY_STATS'], autonomy: ['AUTONOMY'],
  observe: ['OBSERVE'], interop: ['INTEROP'], admin: ['ADMIN'],
};
const MODE_LABELS = {
  trust: 'Trust & Governance', memory: 'Memory', autonomy: 'Autonomy', build: 'Builds',
  observe: 'Observability', interop: 'Interop', comms: 'Comms', admin: 'Admin',
  finance: 'Finance', health: 'Health', knowledge: 'Knowledge', family: 'Family',
};

function ModeEmpty({ mode, onDemo }) {
  const keys = MODE_LIVE_KEYS[mode];
  const wired = !!keys; // has a backend path, just no data yet
  return (
    <div className="workzone full" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="panel" style={{ maxWidth: 460, textAlign: 'center', padding: '30px 26px' }}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.2em', color: 'var(--ink-3)', marginBottom: 10 }}>{(MODE_LABELS[mode] || mode).toUpperCase()}</div>
        <div style={{ fontSize: 14, color: 'var(--ink)', marginBottom: 8 }}>{wired ? 'Not connected' : 'Design preview'}</div>
        <div style={{ fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5, marginBottom: 18 }}>
          {wired
            ? 'No live data from the backend for this view yet. It populates automatically once the source responds.'
            : 'This view has no backend wired yet. Enable DEMO to preview the design with sample data.'}
        </div>
        <button className="tool-btn" onClick={onDemo} style={{ color: 'var(--amber)', borderColor: 'var(--amber)' }}>◐ enable DEMO</button>
      </div>
    </div>
  );
}

function modeComponent(mode, t, ctx) {
  const { demo, live, onDemo, localPct } = ctx || {};
  const keys = MODE_LIVE_KEYS[mode];
  // Honest gate: show real content only in DEMO, or when this mode's source is live.
  const isLive = demo || (keys && live && keys.some((k) => live[k]));
  if (!isLive) return <ModeEmpty mode={mode} onDemo={onDemo} />;
  switch (mode) {
    case 'trust': return <TrustMode t={t} localPct={localPct} />;
    case 'memory': return <MemoryMode t={t} />;
    case 'autonomy': return <AutonomyMode t={t} />;
    case 'build': return <BuildMode t={t} />;
    case 'observe': return <ObserveMode t={t} />;
    case 'interop': return <InteropMode t={t} />;
    case 'comms': return <CommsMode t={t} />;
    case 'admin': return <AdminMode t={t} />;
    case 'finance': return <FinanceMode t={t} />;
    case 'health': return <HealthMode t={t} />;
    case 'knowledge': return <KnowledgeMode t={t} />;
    case 'family': return <FamilyMode t={t} />;
    default: return <ModeStub label={mode} />;
  }
}

export default App;
