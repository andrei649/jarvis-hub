'use strict';
/* h, useState, useEffect, useRef, useMemo, useLayoutEffect, useCallback — from components.js */

function App() {
  var _a = useState([]), agents = _a[0], setAgents = _a[1];
  var _b = useState('jarvis'), activeAgent = _b[0], setActiveAgent = _b[1];
  var _c = useState(null), focusAgent = _c[0], setFocusAgent = _c[1];
  var _d = useState([]), messages = _d[0], setMessages = _d[1];
  var _e = useState(''), draft = _e[0], setDraft = _e[1];
  var _f = useState(false), mic = _f[0], setMic = _f[1];
  var _g = useState('idle'), voiceState = _g[0], setVoiceState = _g[1];
  var _h = useState(null), thinking = _h[0], setThinking = _h[1];
  var _i = useState([]), routedAgents = _i[0], setRoutedAgents = _i[1];
  var _j = useState(false), paletteOpen = _j[0], setPaletteOpen = _j[1];
  var _k = useState(JARVIS_FALLBACK_SYS), sys = _k[0], setSys = _k[1];
  var _l = useState(JARVIS_FALLBACK_WEATHER), weather = _l[0], setWeather = _l[1];
  var _m = useState(JARVIS_FALLBACK_CALENDAR), calendar = _m[0], setCalendar = _m[1];
  var _n = useState(JARVIS_FALLBACK_NOTIFICATIONS), notifications = _n[0], setNotifications = _n[1];
  var _o = useState([]), tasks = _o[0], setTasks = _o[1];
  var _p = useState([]), ticker = _p[0], setTicker = _p[1];
  var _q = useState(true), lmOnline = _q[0], setLmOnline = _q[1];
  var _r = useState(false), sending = _r[0], setSending = _r[1];
  var _s = useState(true), loading = _s[0], setLoading = _s[1];
  var _u = useState(false), apiDown = _u[0], setApiDown = _u[1];
  var _v = useState(false), showCognition = _v[0], setShowCognition = _v[1];
  var _w = useState(false), showSystems = _w[0], setShowSystems = _w[1];
  var _x = useState(null), dossierAgent = _x[0], setDossierAgent = _x[1];
  var _y = useState(null), cognitionData = _y[0], setCognitionData = _y[1];
  var recRef = useRef(null);

  var fetchCognition = useCallback(async function () {
    try {
      var r = await fetch('/api/cognition');
      var d = await r.json();
      setCognitionData(d);
    } catch (e) { console.error('Failed to fetch cognition:', e); }
  }, []);

  useEffect(function () {
    if (showCognition) fetchCognition();
  }, [showCognition, fetchCognition]);

  var agentMap = useMemo(function () { return Object.fromEntries(agents.map(function (a) { return [a.id, a]; })); }, [agents]);

  useEffect(function () {
    loadJarvisData().then(function (data) {
      setAgents(data.agents);
      setSys(data.sys);
      setWeather(data.weather);
      setCalendar(data.calendar);
      setNotifications(data.notifications);
      setTasks(data.tasks);
      if (data.ticker) setTicker(data.ticker);
      setLmOnline(data.lmOnline);
      setApiDown(data.agents.length === 0);
    }).catch(function (err) {
      console.error('initial data load failed:', err);
      setApiDown(true);
    }).finally(function () { setLoading(false); });
  }, []);

  useEffect(function () {
    var id = setInterval(function () {
      loadJarvisData().then(function (data) {
        if (data.agents.length) setAgents(data.agents);
        // sys is owned by the dedicated 10s /status poll below; the 30s data
        // poll must not overwrite it (would clobber fresher values — bug 2.2).
        if (data.weather.temp !== '\u2014') setWeather(data.weather);
        if (data.calendar.length) setCalendar(data.calendar);
        if (data.notifications.length) setNotifications(data.notifications);
        if (data.tasks.length) setTasks(data.tasks);
        if (data.ticker && data.ticker.length) setTicker(data.ticker);
        setLmOnline(data.lmOnline);
        setApiDown(data.agents.length === 0);
      }).catch(function (err) { console.error('poll data load failed:', err); setApiDown(true); });
    }, 30000);
    return function () { clearInterval(id); };
  }, []);

  useEffect(function () {
    return function () { if (recRef.current) { recRef.current.stop(); recRef.current = null; } };
  }, []);

  useEffect(function () {
    var id = setInterval(async function () {
      try {
        var r = await fetch('/status');
        var d = await r.json();
        if (d.agents) {
          setAgents(function (prev) { return prev.map(function (a) {
            var upd = d.agents.find(function (x) { return x.id === a.id; });
            return upd ? Object.assign({}, a, { status: upd.status }) : a;
          }); });
        }
        if (d.sys) setSys(function (prev) { var o = {}; for (var k in prev) o[k] = prev[k]; for (var k in d.sys) o[k] = d.sys[k]; return o; });
        if (d.lm_online !== undefined) setLmOnline(d.lm_online);
        if (d.voice_state) setVoiceState(d.voice_state);
        setApiDown(false);
        try {
          var tRes = await fetch('/ticker');
          var tData = await tRes.json();
          if (tData.ticker) setTicker(tData.ticker);
        } catch (_) {}
      } catch (e) { setApiDown(e); }
    }, 10000);
    return function () { clearInterval(id); };
  }, []);

  var liveSys = useLiveSys(sys);

  useHotkey('cmdk', function () { setPaletteOpen(function (o) { return !o; }); });
  useHotkey('esc', function () { setPaletteOpen(false); setFocusAgent(null); });

  var speakText = async function (text, lang) {
    if (window.activeJarvisAudio) {
      try { window.activeJarvisAudio.pause(); } catch(e){}
      window.activeJarvisAudio = null;
    }
    try {
      var resp = await fetch('/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, lang: lang || 'ro' }),
      });
      if (!resp.ok) return;
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      var audio = new Audio(url);
      window.activeJarvisAudio = audio;
      audio.onended = function () {
        URL.revokeObjectURL(url);
        if (window.activeJarvisAudio === audio) window.activeJarvisAudio = null;
      };
      audio.onerror = function () {
        if (window.activeJarvisAudio === audio) window.activeJarvisAudio = null;
      };
      await audio.play();
    } catch (e) {
      console.error('Auto TTS failed:', e);
    }
  };

  var submit = async function (textOverride, isVoice) {
    if (sending) return;
    var text = (textOverride !== undefined ? textOverride : draft).trim();
    if (!text) return;
    if (textOverride === undefined) setDraft('');
    setSending(true);

    var ts = nowTs();
    setMessages(function (m) { return [].concat(m, [{ role: 'user', ts: ts, text: text }]); });
    setThinking(activeAgent);
    setRoutedAgents(['jarvis', activeAgent].filter(function (v, i, a) { return a.indexOf(v) === i; }));
    setVoiceState('processing');

    var responderId = activeAgent;
    var responseText = '';

    try {
      var resp = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, agent: activeAgent }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      var reader = resp.body.getReader();
      var dec = new TextDecoder();
      var buf = '';
      var finished = false;

      var finalize = function (evt) {
        if (finished) return;        // guard: end may arrive both in-loop and in trailing buf
        finished = true;
        var finalText = evt.text || responseText;
        var finalAgent = evt.agent || responderId;
        setMessages(function (m) { return [].concat(m, [{ role: 'agent', agent: finalAgent, ts: nowTs(), text: finalText }]); });
        setThinking(null);
        setRoutedAgents([]);
        setTimeout(function () { setVoiceState('idle'); }, 1400);
        setSending(false);
        if (isVoice) {
          speakText(finalText, 'ro');
        }
      };

      var processLines = function (parts) {
        if (!parts || !parts.length) return false;
        for (var _i3 = 0; _i3 < parts.length; _i3++) {
          var line2 = parts[_i3];
          if (!line2.startsWith('data: ')) continue;
          try {
            var evt2 = JSON.parse(line2.slice(6));
            if (evt2.type === 'start') {
              responderId = evt2.agent || activeAgent;
              setVoiceState('speaking');
              setThinking(responderId);
            } else if (evt2.type === 'token') {
              responseText += evt2.text || '';
            } else if (evt2.type === 'end') {
              finalize(evt2);
              return true;
            }
          } catch (e) {}
        }
        return false;
      };

      while (true) {
        var _ref = await reader.read(), done = _ref.done, value = _ref.value;
        if (value) buf += dec.decode(value, { stream: true });
        if (done || finished) break;
        var parts = buf.split('\n');
        buf = parts.pop();
        if (processLines(parts)) break;
      }
      if (!finished && buf) processLines([buf]);
      fetchCognition();
    } catch (err) {
      console.error('stream error', err);
      setMessages(function (m) { return [].concat(m, [{ role: 'agent', agent: 'jarvis', ts: nowTs(), text: _t('app.connection_error') }]); });
      setThinking(null);
      setRoutedAgents([]);
      setVoiceState('idle');
      setSending(false);
      fetchCognition();
    }
  };

  var toggleMic = function () {
    console.log('toggleMic called, mic=', mic);
    if (mic) {
      if (recRef.current) { recRef.current.stop(); recRef.current = null; }
      setMic(false);
      return;
    }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert('Speech recognition not supported. Try Chrome/Edge.'); return; }
    if (!window.isSecureContext && location.protocol !== 'https:' && location.hostname !== 'localhost') {
      alert('Microphone requires HTTPS or localhost.'); return;
    }
    var rec = new SR();
    rec.lang = 'ro-RO';
    rec.continuous = false;
    rec.interimResults = false;
    rec.onresult = function (e) {
      var t = e.results[0][0].transcript;
      console.log('recognition result:', t);
      setDraft('');
      setMic(false);
      submit(t, true);
    };
    rec.onerror = function (ev) { console.warn('recognition error:', ev.error); setMic(false); recRef.current = null; };
    rec.onend = function () { recRef.current = null; };
    recRef.current = rec;
    try { rec.start(); } catch (err) { console.error('recognition start failed:', err); setMic(false); return; }
    setMic(true);
  };

  return h('div', { className: 'hud' },
    h('div', { className: 'hud-bg-grid', 'aria-hidden': true }),
    h('div', { className: 'hud-bg-vignette', 'aria-hidden': true }),
    h('div', { className: 'hud-scanline', 'aria-hidden': true }),

    loading && h('div', { className: 'hud-loading' },
      h('div', { className: 'hud-loading-ring' }),
      h('div', { className: 'hud-loading-label' }, _t('app.loading')),
    ),

    !loading && apiDown && h('div', { className: 'hud-apidown', role: 'status' },
      _t('app.apidown')),

    h(TopBar, {
      activeAgent: activeAgent,
      voiceState: voiceState,
      agentsOnline: agents.filter(function (a) { return a.status !== 'idle'; }).length,
      agentsTotal: agents.length || 15,
      lmOnline: lmOnline,
      onToggleCognition: function () { setShowCognition(function (v) { return !v; }); },
      onToggleSystems: function () { setShowSystems(function (v) { return !v; }); },
    }),

    h(SituationTicker, {
      items: ticker,
      agentMap: agentMap,
      voiceState: voiceState,
    }),

    h('main', { className: 'hud-main' },
      h(AgentList, {
        agents: agents,
        tiers: JARVIS_TIERS,
        activeAgent: activeAgent,
        onSelect: setActiveAgent,
        onDoubleClick: setDossierAgent,
        sys: liveSys,
      }),

      h('section', { className: 'panel panel-center' },
        h(NetworkBrain, {
          agents: agents,
          tasks: tasks,
          collab: [],
          activeAgent: activeAgent,
          onSelect: setActiveAgent,
          focusAgent: focusAgent,
          onFocusAgent: setFocusAgent,
          routedAgents: routedAgents.length ? routedAgents : (thinking ? ['jarvis', activeAgent] : []),
          voiceState: voiceState,
        }),
        h(ConversationView, {
          messages: messages,
          agentMap: agentMap,
          thinking: thinking,
          routedAgents: routedAgents,
        }),
        h(InputBar, {
          value: draft,
          onChange: setDraft,
          onSubmit: submit,
          mic: mic,
          onMicToggle: toggleMic,
          activeAgent: activeAgent,
          disabled: sending,
        }),
      ),

      h('aside', { className: 'panel panel-right' },
        h(WeatherCard, { data: weather }),
        h(CalendarCard, { items: calendar }),
        h(AgentsGrid, {
          agents: agents,
          activeAgent: activeAgent,
          onSelect: setActiveAgent,
        }),
        h(HeartbeatFeed, {
          items: notifications,
          agentMap: agentMap,
        }),
        showCognition && h(CognitionPanel, {
          scoring: cognitionData ? cognitionData.scoring : [],
          decision: cognitionData ? cognitionData.decision : null,
          trace: cognitionData ? cognitionData.trace : [],
          message: '',
          onRefresh: fetchCognition,
        }),
        showSystems && h(SystemsPanel, {
          agents: agents,
          onRefresh: function (tab) { console.log('refresh systems tab:', tab); },
          onPluginToggle: function (id) {
            fetch('/plugins/' + id + '/toggle', { method: 'PUT' })
              .then(function (r) { return r.json(); })
              .then(function (d) {
                console.log('plugin toggled:', d);
                window.dispatchEvent(new CustomEvent('jarvis:plugins_updated'));
              })
              .catch(function (err) { console.error('plugin toggle failed:', err); });
          },
        }),
      ),
    ),

    h(CommandPalette, {
      open: paletteOpen,
      onClose: function () { setPaletteOpen(false); },
      agents: agents,
      tasks: tasks,
      projects: [],
      onAction: function (act) {
        if (act.type === 'focus_agent') setActiveAgent(act.agent);
        if (act.type === 'voice_state') setVoiceState(act.value);
        if (act.type === 'clear_focus') setFocusAgent(null);
        if (act.type === 'filter_project') console.log('filter project:', act.project);
      },
    }),

    dossierAgent && h(DossierModal, {
      agent: agentMap[dossierAgent],
      dossier: DOSSIER[dossierAgent],
      memoryContext: null,
      onClose: function () { setDossierAgent(null); },
      onChat: function (id) { setActiveAgent(id); setDossierAgent(null); },
      onViewSoul: function (id) { console.log('view soul:', id); },
    })
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(h(App));
