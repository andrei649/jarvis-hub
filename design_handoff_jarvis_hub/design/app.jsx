// app.jsx — root of the Jarvis Hub HUD prototype.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#00AEEF",
  "voiceState": "listening",
  "density": "regular",
  "scanline": true,
  "dotgrid": true,
  "rings": true
}/*EDITMODE-END*/;

const ACCENT_LIGHT = {
  '#00AEEF': '#7FDBFF', // arc cyan
  '#FFB23F': '#FFD787', // amber hud
  '#39FF8B': '#9CFFD2', // green phosphor
  '#9B6BFF': '#D0B6FF', // violet lab
};

function App() {
  const data = window.JARVIS_DATA;
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  const [activeAgent, setActiveAgent] = useState('jarvis');
  const [messages, setMessages] = useState(data.SAMPLE_CONVERSATION);
  const [draft, setDraft] = useState('');
  const [mic, setMic] = useState(false);
  const [thinking, setThinking] = useState(null);
  const [routedAgents, setRoutedAgents] = useState([]);
  const [focusAgent, setFocusAgent] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Live sys metrics (breathing)
  const liveSys = useLiveSys(data.SYS);

  // Memo agent map for quick lookups
  const agentMap = useMemo(() => Object.fromEntries(data.AGENTS.map((a) => [a.id, a])), [data.AGENTS]);

  // ⌘K toggle
  useHotkey('cmdk', () => setPaletteOpen((o) => !o));
  useHotkey('esc',  () => { setPaletteOpen(false); setFocusAgent(null); });

  const accentPrimary = t.accent;
  const accentLight = ACCENT_LIGHT[t.accent] || '#7FDBFF';

  // Push accent variables to :root
  useEffect(() => {
    const r = document.documentElement;
    r.style.setProperty('--accent', accentPrimary);
    r.style.setProperty('--accent-light', accentLight);
    r.dataset.density = t.density;
    r.dataset.scanline = t.scanline ? 'on' : 'off';
    r.dataset.dotgrid  = t.dotgrid  ? 'on' : 'off';
    r.dataset.rings    = t.rings    ? 'on' : 'off';
  }, [accentPrimary, accentLight, t.density, t.scanline, t.dotgrid, t.rings]);

  const voiceState = t.voiceState; // 'idle' | 'listening' | 'processing' | 'speaking'
  const cycleVoice = () => {
    const order = ['idle', 'listening', 'processing', 'speaking'];
    setTweak('voiceState', order[(order.indexOf(voiceState) + 1) % order.length]);
  };

  // Submit handler: simulate orchestration
  const submit = () => {
    const text = draft.trim() || data.DEMO_QUERY.user;
    const isDemo = !draft.trim();
    const ts = nowTs();
    const userMsg = { role: 'user', ts, text };
    setMessages((m) => [...m, userMsg]);
    setDraft('');

    // Pick routed agents (jarvis first + active + a relevant one)
    const routed = isDemo
      ? data.DEMO_QUERY.route
      : ['jarvis', activeAgent].filter((v, i, a) => a.indexOf(v) === i);

    setRoutedAgents(routed);
    setThinking('jarvis');
    setTweak('voiceState', 'processing');

    setTimeout(() => {
      setTweak('voiceState', 'speaking');
      setTimeout(() => {
        const responderId = isDemo ? data.DEMO_QUERY.agent : activeAgent;
        const response = isDemo
          ? data.DEMO_QUERY.response
          : craftReply(text, responderId, data.AGENTS);
        setMessages((m) => [...m, { role: 'agent', agent: responderId, ts: nowTs(), text: response }]);
        setThinking(null);
        setRoutedAgents([]);
        setTimeout(() => setTweak('voiceState', 'idle'), 1400);
      }, 900);
    }, 1300);
  };

  return (
    <div className="hud">
      <div className="hud-bg-grid" aria-hidden />
      <div className="hud-bg-vignette" aria-hidden />
      <div className="hud-scanline" aria-hidden />

      <TopBar activeAgent={activeAgent} voiceState={voiceState} agentCount={15} sysOnline />

      <SituationTicker items={data.TICKER} agentMap={agentMap} voiceState={voiceState} />

      <main className="hud-main">
        <AgentList
          agents={data.AGENTS}
          tiers={data.TIERS}
          activeAgent={activeAgent}
          onSelect={setActiveAgent}
          sys={liveSys}
        />

        <section className="panel panel-center">
          <NetworkBrain
            agents={data.AGENTS}
            tasks={data.TASKS}
            collab={data.COLLAB}
            activeAgent={activeAgent}
            onSelect={setActiveAgent}
            focusAgent={focusAgent}
            onFocusAgent={setFocusAgent}
            routedAgents={routedAgents.length ? routedAgents : (thinking ? ['jarvis', activeAgent] : [])}
            voiceState={voiceState}
          />
          <ConversationView
            messages={messages}
            agents={data.AGENTS}
            thinking={thinking}
            routedAgents={routedAgents}
          />
          <InputBar
            value={draft}
            onChange={setDraft}
            onSubmit={submit}
            mic={mic}
            onMicToggle={() => setMic((m) => !m)}
            activeAgent={activeAgent}
          />
        </section>

        <aside className="panel panel-right">
          <WeatherCard data={data.WEATHER} />
          <CalendarCard items={data.CALENDAR} />
          <AgentsGrid agents={data.AGENTS} activeAgent={activeAgent} onSelect={setActiveAgent} />
          <HeartbeatFeed
            items={data.NOTIFICATIONS}
            agentMap={Object.fromEntries(data.AGENTS.map((a) => [a.id, a]))}
          />
        </aside>
      </main>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        agents={data.AGENTS}
        tasks={data.TASKS}
        projects={data.PROJECTS}
        onAction={(act) => {
          if (act.type === 'focus_agent') setActiveAgent(act.agent);
          if (act.type === 'voice_state') setTweak('voiceState', act.value);
          if (act.type === 'clear_focus') setFocusAgent(null);
        }}
      />

      <TweaksPanel>
        <TweakSection label="HUD palette" />
        <TweakColor
          label="Accent"
          value={t.accent}
          options={['#00AEEF','#FFB23F','#39FF8B','#9B6BFF']}
          onChange={(v) => setTweak('accent', v)}
        />
        <TweakSection label="Voice state" />
        <TweakRadio
          label="Mode"
          value={t.voiceState}
          options={['idle','listening','processing','speaking']}
          onChange={(v) => setTweak('voiceState', v)}
        />
        <TweakSection label="Visual layer" />
        <TweakToggle label="Dot grid backdrop" value={t.dotgrid} onChange={(v) => setTweak('dotgrid', v)} />
        <TweakToggle label="Scan line"         value={t.scanline} onChange={(v) => setTweak('scanline', v)} />
        <TweakToggle label="Orbital rings"     value={t.rings} onChange={(v) => setTweak('rings', v)} />
        <TweakRadio
          label="Density"
          value={t.density}
          options={['compact','regular','comfy']}
          onChange={(v) => setTweak('density', v)}
        />
      </TweaksPanel>
    </div>
  );
}

/* ─────────── helpers ─────────── */

function nowTs() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

function craftReply(query, agentId, agents) {
  const agent = agents.find((a) => a.id === agentId);
  const TEMPLATES = {
    jarvis:     `Recepționat, sir. „${trim(query, 56)}” — voi rula prin specialiști și revin cu o singură sinteză.`,
    friday:     `Rulez briefingul: trei surse, un highlight relevant pentru drum. Confirmi că vrei și headline-urile pe sport?`,
    pepper:     `Verific calendarul și inbox-ul. Două slot-uri compatibile mâine, 09:30 și 14:00. Care îți convine?`,
    jerome:     `Pun „Late Night Tales” pe sufragerie, volum 28. Spune când vrei să schimb mood-ul.`,
    athena:     `Strategie scurtă: păstrează tonul direct, mută follow-up pe joi, evită discount sub 12%. Pot detalia.`,
    stark:      `KPI Q2: NPS +3.2, churn 1.8%, ARPU stabil. Două puncte slabe în onboarding — îți trimit grafic în 2 minute.`,
    veronica:   `Draft gata: două variante, una scurtă (3 fraze), una pentru post LinkedIn. Spune care merge.`,
    vision:     `Cinci surse parsate, două relevante. Concluzia: piață încă fragmentată, niciun lider clar. Detalii la cerere.`,
    steve:      `Confirmat în deploy. CI verde, 0 erori. Branch merge-uit pe main. Vrei să rulez și smoke test pe staging?`,
    oracle:     `Workflow N8N activ. Trigger-ul s-a executat de 14 ori azi. Niciun fail. Vrei breakdown pe nod?`,
    ultron:     `Scan complet. 0 incidente critice, 2 warnings (rate-limit pe API extern). Loghez și continui.`,
    gecko:      `Portofoliu: -0.4% pe zi, dar BTC se mișcă în zona suport. Nu intervin până nu apare confirmare pe volum.`,
    hercules:   `Sesiunea de azi: 47 min, 312 kcal, RHR 58. Recomand un push-day mâine dacă programul permite.`,
    hephaestus: `BMW: presiune corectă, ulei OK, urmează service la 2.400 km. Cosmina: am verificat lista materiale.`,
    frigga:     `Max a dormit 2h45 azi după-amiază. Alexandra a întrebat de cină — fac eu ordinea sau treci pe la magazin?`,
  };
  return TEMPLATES[agentId] || `[${agent?.name || agentId}] răspuns sintetic pentru: „${trim(query, 64)}”.`;
}

function trim(s, n) { return s.length > n ? s.slice(0, n) + '…' : s; }

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
