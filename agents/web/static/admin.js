'use strict';
/* admin.js — Jarvis Hub Admin Panel (Apple Settings style) */

/* h, useState, useEffect, useRef, useMemo, useCallback — from components.js */

/* ── SVG icons per category ─────────────────────────────────── */

const ICONS = {
  general: h('svg', {viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:10,cy:10,r:7}),
    h('circle',{cx:10,cy:10,r:3}),
    h('line',{x1:10,y1:1,x2:10,y2:4}),
    h('line',{x1:10,y1:16,x2:10,y2:19}),
    h('line',{x1:1,y1:10,x2:4,y2:10}),
    h('line',{x1:16,y1:10,x2:19,y2:10}),
  ),
  llm: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:3,y:3,width:14,height:14,rx:3}),
    h('circle',{cx:10,cy:10,r:3}),
    h('path',{d:'M10 13v4M10 3v4M13 10h4M3 10h4'}),
  ),
  agents: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:7,cy:7,r:3}),
    h('circle',{cx:13,cy:7,r:3}),
    h('circle',{cx:7,cy:14,r:3}),
    h('circle',{cx:13,cy:14,r:3}),
  ),
  plugins: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M5 10h10M10 5v10'}),
    h('circle',{cx:10,cy:10,r:8}),
  ),
  voice: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:8,y:1,width:4,height:11,rx:2}),
    h('path',{d:'M4 9a6 6 0 0 0 12 0'}),
    h('line',{x1:10,y1:12,x2:10,y2:19}),
    h('line',{x1:7,y1:19,x2:13,y2:19}),
  ),
  channels: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M1 5h18M1 10h18M1 15h18'}),
    h('circle',{cx:5,cy:5,r:2}),
    h('circle',{cx:15,cy:10,r:2}),
    h('circle',{cx:5,cy:15,r:2}),
  ),
  security: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 1l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V4z'}),
    h('path',{d:'M8 10l1.5 1.5L12 8'}),
  ),
  memory: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:3,y:2,width:14,height:16,rx:2}),
    h('line',{x1:7,y1:6,x2:13,y2:6}),
    h('line',{x1:7,y1:10,x2:13,y2:10}),
    h('line',{x1:7,y1:14,x2:11,y2:14}),
  ),
  skills: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 2a4 4 0 0 0-4 4v2H4v8h12V8h-2V6a4 4 0 0 0-4-4z'}),
    h('circle',{cx:10,cy:12,r:2}),
  ),
  system: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:10,cy:8,r:5}),
    h('path',{d:'M3 17c1-3 4-5 7-5s6 2 7 5'}),
  ),
  oracle: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:5,cy:5,r:2}),
    h('circle',{cx:15,cy:5,r:2}),
    h('circle',{cx:5,cy:15,r:2}),
    h('circle',{cx:15,cy:15,r:2}),
    h('path',{d:'M7 7l6 6M13 7l-6 6'}),
  ),
  mcp: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:2,y:5,width:6,height:10,rx:1}),
    h('rect',{x:12,y:5,width:6,height:10,rx:1}),
    h('path',{d:'M8 10h4'}),
  ),
  charts: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('rect',{x:2,y:12,width:4,height:6,rx:1}),
    h('rect',{x:8,y:7,width:4,height:11,rx:1}),
    h('rect',{x:14,y:2,width:4,height:16,rx:1}),
  ),
  recall: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 2a8 8 0 1 0 0 16A8 8 0 0 0 10 2z'}),
    h('path',{d:'M10 6v4l3 2'}),
  ),
  cost: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('circle',{cx:10,cy:10,r:8}),
    h('path',{d:'M10 6v1m0 6v1'}),
    h('path',{d:'M8 8h3a1 1 0 1 1 0 2H9a1 1 0 1 0 0 2h3'}),
  ),
  models: h('svg',{viewBox:'0 0 20 20',width:18,height:18,fill:'none',stroke:'currentColor',strokeWidth:1.3},
    h('path',{d:'M10 2l7 4v8l-7 4-7-4V6z'}),
    h('path',{d:'M3 6l7 4 7-4M10 10v8'}),
  ),
};

/* ── category metadata ──────────────────────────────────────── */

const CATEGORIES = [
  { id:'charts',   label:'Statistici & Analize',  icon:'charts' },
  { id:'config',   label:'Configurări Globale',   icon:'general' },
  { id:'agents',   label:'Management Agenți',    icon:'agents' },
  { id:'models',   label:'Modele Locale',        icon:'models' },
  { id:'recall',   label:'Memorie Utilizator',   icon:'recall' },
  { id:'costview', label:'Cost & Modele',        icon:'cost' },
  { id:'mcp',      label:'Servere MCP',          icon:'mcp' },
  { id:'oracle',   label:'Integrare Claude',     icon:'oracle' },
  { id:'system',   label:'Sistem & Depanare',    icon:'system' },
];

const CATEGORY_DESC = {
  charts:    'Date analitice, latențe, rate de succes ale agenților și circuit breakere active.',
  config:    'Toate setările sistemului grupate logic într-o singură listă simplă, cu denumiri intuitive.',
  agents:    'Activarea, dezactivarea și selectarea modelelor LLM utilizate de fiecare agent din rețea.',
  mcp:       'Configurarea clienților externi Model Context Protocol (stdio / sse) cu descoperire de unelte.',
  oracle:    'Statusul curent de sincronizare, conflicte de cod detectate și integrarea cu asistentul de push.',
  system:    'Variabile de mediu live, depanare rapidă și reinițializarea bazei de date.',
  recall:    'Fapte și preferințe stocate despre utilizator, grupate pe categorii, cu căutare rapidă.',
  costview:  'Clasificarea agenților pe tier de model (local / fast / standard / heavy) și costurile LLM acumulate.',
  models:    'Răsfoiește modelele locale din LM Studio / Ollama, vezi care e activ și comută dintr-un click.',
};

/* ── agent glyph map — single source of truth in data.js ───── */
/* data.js loads before admin.js, so window.JARVIS_GLYPHS exists. */

const AGENT_GLYPHS = window.JARVIS_GLYPHS || {};

/* ── Row components ─────────────────────────────────────────── */

function ToggleRow({ label, value, onChange }) {
  return h('div', {className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('label',{className:'admin-toggle'},
        h('input',{type:'checkbox', checked:value, onChange:e=>onChange(e.target.checked)}),
        h('div',{className:'admin-toggle-track'}),
      ),
    ),
  );
}

function InputRow({ label, value, onChange, kind, placeholder }) {
  const tag = kind === 'number' ? 'number' : 'text';
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('input',{
        className:'admin-input', type:tag,
        value, placeholder: placeholder||'',
        onChange:e=>onChange(tag==='number'?Number(e.target.value):e.target.value),
      }),
    ),
  );
}

function SelectRow({ label, value, onChange, opts }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('select',{className:'admin-select', value, onChange:e=>onChange(e.target.value)},
        opts.map(o=>h('option',{key:o,value:o}, o)),
      ),
    ),
  );
}

function SliderRow({ label, value, onChange, min, max, step }) {
  min = min ?? 0; max = max ?? 1; step = step ?? 0.01;
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control', style:{display:'flex',alignItems:'center',gap:10}},
      h('input',{className:'admin-slider', type:'range', min, max, step,
        value, onChange:e=>onChange(Number(e.target.value))}),
      h('span',{className:'admin-slider-value'}, value),
    ),
  );
}

function TagInputRow({ label, value, onChange }) {
  const [draft, setDraft] = useState('');
  const tags = Array.isArray(value) ? value : [];
  const addTag = () => {
    const t = draft.trim().toLowerCase();
    if (t && !tags.includes(t)) { onChange([...tags, t]); setDraft(''); }
  };
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('div',{className:'admin-tags'},
        tags.map((t,i)=>h('span',{key:i,className:'admin-tag'},
          t,
          h('span',{className:'admin-tag-remove', onClick:()=>onChange(tags.filter((_,j)=>j!==i))},'×'),
        )),
        h('input',{className:'admin-tag-input', value:draft,
          placeholder:_t('admin.tag_placeholder'),
          onChange:e=>setDraft(e.target.value),
          onKeyDown:e=>{if(e.key==='Enter'){e.preventDefault();addTag();}if(e.key==='Backspace'&&!draft&&tags.length){onChange(tags.slice(0,-1));}},
          onBlur:addTag,
        }),
      ),
    ),
  );
}

function ButtonRow({ label, buttonLabel, onClick, variant }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control'},
      h('button',{className:`admin-btn ${variant?'is-'+variant:''}`, onClick}, buttonLabel),
    ),
  );
}

function InfoRow({ label, value }) {
  return h('div',{className:'admin-row'},
    h('div',{className:'admin-row-label'}, label),
    h('div',{className:'admin-row-control', style:{fontFamily:'var(--font-mono)',fontSize:12,color:'var(--text-dim)'}},
      String(value),
    ),
  );
}

function Group({ title, children }) {
  if (!children || (Array.isArray(children) && children.every(c=>!c))) return null;
  return h('div',{className:'admin-group'},
    h('div',{className:'admin-group-header'}, title),
    children,
  );
}

/* ── Settings row renderer ──────────────────────────────────── */

function renderRow(s, i, onUpdate, onAction) {
  const update = (val) => onUpdate(s.key, val);
  switch (s.kind) {
    case 'toggle': return h(ToggleRow,{key:i,label:s.label,value:!!s.value,onChange:update});
    case 'select': return h(SelectRow,{key:i,label:s.label,value:s.value,onChange:update,opts:s.opts});
    case 'slider': return h(SliderRow,{key:i,label:s.label,value:s.value,onChange:update});
    case 'tags':   return h(TagInputRow,{key:i,label:s.label,value:s.value,onChange:update});
    case 'number': return h(InputRow,{key:i,label:s.label,value:s.value,onChange:update,kind:'number'});
    case 'info':   return h(InfoRow,{key:i,label:s.label,value:s.value});
    case 'button': return h(ButtonRow,{key:i,label:s.label,buttonLabel:s.opts[0]||'Action',onClick:()=>onAction&&onAction(s.key),variant:s.opts[1]});
    default:       return h(InputRow,{key:i,label:s.label,value:s.value,onChange:update});
  }
}

const FRIENDLY_NAMES = {
  timezone: "Fus orar local",
  wake_words: "Cuvinte de trezire vocală",
  addressing: "Mod de adresare",
  default_tts: "Voce implicită pentru sinteză",
  ui_density: "Densitate interfață HUD",
  dev_mode: "Mod Dezvoltator activat",
  backend_type: "Tip motor inteligență artificială (LLM)",
  lm_studio_url: "Adresă URL server LM Studio",
  ollama_url: "Adresă URL server Ollama local",
  default_model: "Model lingvistic implicit",
  temperature: "Creativitate model (Temperatură)",
  max_tokens: "Număr maxim de cuvinte per răspuns",
  cloud_fallback: "Regim backup în Cloud",
  gemini_model: "Model Google Gemini din Cloud",
  hybrid_local_max: "Limită maximă tokeni locali",
  hybrid_flash_max: "Limită maximă tokeni în Cloud",
  stt_model_size: "Mărime model recunoaștere vocală (STT)",
  stt_language: "Limbă recunoaștere vocală",
  tts_voice: "Voce sinteză Microsoft (TTS)",
  wake_threshold: "Sensibilitate detectare cuvânt trezire",
  silence_sec: "Toleranță liniște înainte de răspuns (secunde)",
  max_recording: "Durată maximă înregistrare vocală (secunde)",
  volume_threshold: "Prag volum de fundal microfon",
  guardrails_mode: "Mod protecție date sensibile",
  scan_input: "Scanează datele introduse de utilizator",
  scan_output: "Scanează răspunsurile generate de AI",
  sandbox_timeout: "Toleranță timeout execuție sandbox (secunde)",
  sandbox_memory: "Limită memorie RAM sandbox (MB)",
  max_turns: "Număr maxim de replici memorate per sesiune",
  context_window: "Fereastră de context activ (număr de replici)",
  persist: "Salvează memoria pe disc automat",
  rate_limit: "Limită Gateway de securitate (mesaje/minut)",
  web_enabled: "Canal Web direct activ",
  weather: "Activare plugin Vreme (wttr.in)",
  news: "Activare plugin Știri (BBC RSS)",
  "cloud-llm": "Activare plugin Cloud LLM (OpenAI/Anthropic)",
  telegram: "Activare plugin Telegram Bot",
  gmail: "Activare plugin Gmail API",
  "google-calendar": "Activare plugin Google Calendar",
  "whatsapp-bridge": "Activare punte locală WhatsApp",
  spotify: "Activare plugin Control Spotify",
  "apple-health": "Activare sincronizare Apple Health",
  homebridge: "Activare integrare Smart Home (Homebridge)",
  gecko_ing_client_id: "Identificator Client ING Bank (Gecko)",
  gecko_ing_client_secret: "Secret Client ING Bank (Gecko)",
  gecko_libra_token: "Token API Libra Bank (Gecko)",
  gecko_csv_path: "Cale fișiere export extras bancar CSV",
  stark_ga4_service_account: "Cale fișier credențiale GA4 (Stark)",
  stark_ga4_property_id: "Identificator Proprietate Google Analytics 4",
  auto_scale: "Scalare automată a resurselor agenților",
  cardinality_cap: "Capacitate maximă de agenți încărcați",
  promote_on_use: "Număr utilizări necesare promovării în HUD",
  demote_on_inactive: "Număr luni de inactivitate până la demovare",
  auto_generate: "Autogenerare automată de noi abilități",
  sandbox_enabled: "Execuție în sandbox protejat",
  max_skills: "Număr maxim de abilități memorate",
  import_source: "Sursă implicită de import abilități",
  log_level: "Nivel detaliere loguri sistem",
  heartbeat_interval: "Interval heartbeat (secunde)",
  poll_interval: "Interval verificare status (secunde)",
  theme: "Temă interfață vizuală",
  autonomy_tick: "Frecvență verificare autonomie (secunde)",
  observer_enabled: "Monitorizare resurse gazdă (Observer)",
  watchers_enabled: "Monitorizare evenimente personale (Watchers)",
  error_backlog_sync_enabled: "Sincronizare automată erori în BACKLOG.md",
  owner_chat_id: "Identificator Chat Telegram Proprietar",
  cap_per_action: "Sumă limită per acțiune financiară (RON)",
  daily_ceiling: "Plafon maxim zilnic acțiuni financiare (RON)",
  interrupt_budget: "Plafon mesaje push urgente pe zi",
  night_shift: "Regim de noapte activ (Autonomie redusă)",
  night_start: "Oră start regim noapte (Ex: 23)",
  night_end: "Oră sfârșit regim noapte (Ex: 6)",
  priority_senders: "Expeditori email prioritari",
  finance_min_ron: "Prag minim cont RON (Gecko)",
  finance_min_eur: "Prag minim cont EUR (Gecko)",
  health_min_sleep: "Durată minimă somn (ore - Hercules)",
  health_min_hrv: "Prag minim HRV (ms - Hercules)",
  calendar_lead_time: "Avertizare în avans întâlniri (minute - Pepper)",
};

const FRIENDLY_DESCS = {
  timezone: "Zona orară utilizată pentru planificarea alertelor și a sarcinilor în fundal.",
  wake_words: "Cuvintele la care asistentul vocal local va răspunde automat la rostire.",
  addressing: "Modul în care asistentul se adresează utilizatorului (ex: 'sir' sau 'boss').",
  ui_density: "Compactitatea vizuală a elementelor afișate în interfața grafică HUD.",
  dev_mode: "Activează instrumentele suplimentare pentru depanare și execuție sandbox.",
  backend_type: "Alege între detecție automată, LM Studio local sau Ollama local.",
  temperature: "Valori mai mari oferă răspunsuri creative; valori mai mici oferă răspunsuri precise.",
  cloud_fallback: "Fallback automat pe cloud (Anthropic/Gemini) dacă motorul local este offline sau suprasolicitat.",
  guardrails_mode: "Modul în care datele confidențiale sau PII sunt filtrate (Avertizare, Redactare sau Blocare completă).",
  sandbox_timeout: "Timpul maxim acordat execuției de cod nesigur înainte de a fi oprită forțat.",
  observer_enabled: "Rulează bucla de fundal ce monitorizează starea Docker, procesele gazdei și memoria liberă.",
  watchers_enabled: "Verifică automat emailurile importante, programul din calendar, soldurile bancare și indicii de somn/sănătate.",
  error_backlog_sync_enabled: "Scrie live runtime crash-urile direct sub formă de TODO checklist în BACKLOG.md.",
  night_shift: "Când este activ, limitează executarea sarcinilor active/financiare în intervalul orar nocturn.",
  priority_senders: "Expeditorii Gmail de la care noile mesaje necitite vor fi marcate instant ca fiind alerte prioritare.",
  finance_min_ron: "Suma minimă sub care un cont de RON (ING, Libra etc.) va declanșa o alertă de sold scăzut.",
  finance_min_eur: "Suma minimă sub care un cont de EUR va declanșa o alertă de sold scăzut.",
  health_min_sleep: "Dacă durata totală a somnului de azi-noapte este mai mică decât acest prag, asistentul te va alerta.",
  health_min_hrv: "Prag minim pentru indicatorul HRV (Heart Rate Variability) — sub acest nivel se va raporta stare de oboseală/stres.",
  calendar_lead_time: "Intervalul orar (în minute) înainte de începerea unei întâlniri în care asistentul te va avertiza de eveniment.",
};

function GlobalConfigPage({ settings, dirty, onUpdate, onSave }) {
  const [search, setSearch] = useState('');
  
  const SECTIONS = [
    {
      title: "⚙️ Preferințe Asistent Globale",
      desc: "Setări generale referitoare la fusul orar, cuvinte de trezire și adresare.",
      keys: ["general.timezone", "general.wake_words", "general.addressing", "general.default_tts", "general.ui_density", "general.dev_mode"]
    },
    {
      title: "🎙️ Configurare Voce & Sunet (STT / TTS)",
      desc: "Parametrii microfonului local, ai algoritmilor de recunoaștere vocală și ai sintezei de voce.",
      keys: ["voice.stt_model_size", "voice.stt_language", "voice.tts_voice", "voice.wake_threshold", "voice.silence_sec", "voice.max_recording", "voice.volume_threshold"]
    },
    {
      title: "🤖 Modele Lingvistice & AI (LLM)",
      desc: "Configurarea motoarelor LLM locale (LM Studio / Ollama) și a fallback-urilor inteligente în Cloud.",
      keys: ["llm.backend_type", "llm.lm_studio_url", "llm.ollama_url", "llm.default_model", "llm.temperature", "llm.max_tokens", "llm.cloud_fallback", "llm.gemini_model", "llm.hybrid_local_max", "llm.hybrid_flash_max"]
    },
    {
      title: "🔒 Securitate & Sandbox Protejat",
      desc: "Reguli stricte pentru filtrarea datelor sensibile, scanere de secrete și timpi limită sandbox.",
      keys: ["security.guardrails_mode", "security.scan_input", "security.scan_output", "security.sandbox_timeout", "security.sandbox_memory", "skills.sandbox_enabled"]
    },
    {
      title: "🧠 Memorie & Context Conversațional",
      desc: "Administrarea istoricului de dialog stocat pe disc și a ferestrei de context a agenților.",
      keys: ["memory.max_turns", "memory.context_window", "memory.persist"]
    },
    {
      title: "🎯 Cortex Autonom & Buget Inteligent",
      desc: "Setări de securitate financiară, plafoane zilnice pentru acțiuni autonome și regim de noapte protectiv.",
      keys: ["autonomy.owner_chat_id", "autonomy.cap_per_action", "autonomy.daily_ceiling", "autonomy.interrupt_budget", "autonomy.night_shift", "autonomy.night_start", "autonomy.night_end", "system.autonomy_tick", "system.observer_enabled", "system.watchers_enabled", "system.error_backlog_sync_enabled", "autonomy.priority_senders", "autonomy.finance_min_ron", "autonomy.finance_min_eur", "autonomy.health_min_sleep", "autonomy.health_min_hrv", "autonomy.calendar_lead_time"]
    },
    {
      title: "📞 Canale de Comunicare",
      desc: "Activarea/dezactivarea integrărilor Gateway și a limitelor de apeluri pe secundă.",
      keys: ["channels.rate_limit", "channels.web_enabled", "plugins.telegram"]
    },
    {
      title: "🔌 Extensii & Module Active (Plugins)",
      desc: "Activarea live a modulelor suplimentare integrate în platformă.",
      keys: ["plugins.weather", "plugins.news", "plugins.cloud-llm", "plugins.gmail", "plugins.google-calendar", "plugins.whatsapp-bridge", "plugins.spotify", "plugins.apple-health", "plugins.homebridge"]
    },
    {
      title: "🔑 Chei API & Conexiuni Bancare",
      desc: "Parametrii de autentificare pentru servicii externe, solduri Gecko (ING / Libra) și Stark Analytics.",
      keys: ["plugins.gecko_ing_client_id", "plugins.gecko_ing_client_secret", "plugins.gecko_libra_token", "plugins.gecko_csv_path", "plugins.stark_ga4_service_account", "plugins.stark_ga4_property_id"]
    }
  ];

  const flatSettings = {};
  if (settings && typeof settings === 'object') {
    Object.entries(settings).forEach(([cat, list]) => {
      if (Array.isArray(list)) {
        list.forEach(s => {
          flatSettings[`${cat}.${s.key}`] = s;
        });
      }
    });
  }

  const getMergedSetting = (fullKey) => {
    const s = flatSettings[fullKey];
    if (!s) return null;
    return {
      ...s,
      value: dirty.hasOwnProperty(s.key) ? dirty[s.key] : s.value,
      friendlyLabel: FRIENDLY_NAMES[s.key] || s.label,
      friendlyDesc: FRIENDLY_DESCS[s.key] || ""
    };
  };

  const hasChanges = Object.keys(dirty).length > 0;

  return h('div', null,
    h('input', {
      className: 'admin-sidebar-search',
      type: 'text',
      placeholder: 'Căutare setare după denumire...',
      value: search,
      onChange: e => setSearch(e.target.value),
      style: { marginBottom: 20, width: '100%' }
    }),

    SECTIONS.map((section, idx) => {
      const sectionSettings = section.keys
        .map(k => getMergedSetting(k))
        .filter(s => s !== null)
        .filter(s => !search || s.friendlyLabel.toLowerCase().includes(search.toLowerCase()) || s.key.toLowerCase().includes(search.toLowerCase()));

      if (sectionSettings.length === 0) return null;

      return h(Group, { key: idx, title: section.title },
        section.desc && h('p', { style: { padding: '0 12px 10px 12px', fontSize: 11, color: 'var(--text-dim)', fontStyle: 'italic' } }, section.desc),
        sectionSettings.map((s, i) => {
          return h('div', { key: i, className: 'flat-setting-wrapper', style: { borderBottom: '1px solid var(--border-glass)', paddingBottom: 8, marginBottom: 8 } },
            renderRow(
              { ...s, label: s.friendlyLabel },
              s.key,
              onUpdate,
              (key) => onUpdate(key, true)
            ),
            s.friendlyDesc && h('div', { style: { padding: '4px 12px 0 12px', fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.3 } }, s.friendlyDesc)
          );
        })
      );
    }),

    hasChanges && h('div', { style: { position: 'sticky', bottom: 0, padding: '12px 0', background: 'var(--bg-void)', zIndex: 10 } },
      h('button', { className: 'admin-btn is-primary', onClick: onSave }, '💾 Salvează Configurări Globale')
    )
  );
}

/* ── Agent card for Agents page ─────────────────────────────── */

function AgentCard({ agent, onUpdate }) {
  const [open, setOpen] = useState(false);
  const glyph = AGENT_GLYPHS[agent.id] || '';
  return h('div',{className:'admin-agent-card'},
    h('button',{className:'admin-agent-head', onClick:()=>setOpen(!open)},
      glyph && h('svg',{viewBox:'-12 -12 24 24',width:16,height:16,style:{flexShrink:0}},
        h('path',{d:glyph,fill:'none',stroke:'currentColor',strokeWidth:1.2,strokeLinejoin:'round'}),
      ),
      h('span',{className:`admin-agent-dot is-${agent.status||'idle'}`}),
      h('span',{className:'admin-agent-name'}, agent.name || agent.id),
      h('span',{className:'admin-agent-role'}, agent.role || ''),
      h('span',{className:'admin-agent-tier'}, agent.tier || 'FND'),
      h('span',{style:{marginLeft:'auto',color:'var(--text-dim)',fontSize:12}}, open?'▲':'▼'),
    ),
    open && h('div',{className:'admin-agent-body'},
      h(ToggleRow,{label:'Status (active)',value:agent.status==='active',onChange:v=>onUpdate(agent.id,'status',v?'active':'paused')}),
      h(InputRow,{label:'Model',value:agent.model||'',onChange:v=>onUpdate(agent.id,'model',v)}),
      h(SelectRow,{label:'Channel',value:agent.channel||'voice',onChange:v=>onUpdate(agent.id,'channel',v),opts:['voice','web','telegram','discord','email','slack']}),
      h(SelectRow,{label:'Tier',value:agent.tier||'FND',onChange:v=>onUpdate(agent.id,'tier',v),opts:['CNS','BIZ','SEC','FND']}),
    ),
  );
}

/* ── Toast ───────────────────────────────────────────────────── */

function Toast({ message }) {
  if (!message) return null;
  return h('div',{className:'admin-toast', key:message}, message);
}

/* ── System page ─────────────────────────────────────────────── */

function SystemPage({ envData, onRefresh }) {
  const entries = envData ? Object.entries(envData) : [];
  return h('div',null,
    h(Group,{title:_t('admin.env_title')},
      entries.length === 0 && h('div',{style:{padding:12,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading')),
      entries.map(([k,v],i)=>h(InfoRow,{key:i,label:k,value:v})),
    ),
    h('div',{style:{marginTop:16}},
      h('button',{className:'admin-btn', onClick:onRefresh}, _t('admin.reload')),
    ),
  );
}

/* ── Agents page ─────────────────────────────────────────────── */

function AgentsPage({ onUpdate }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/agents').then(r=>r.json()).then(d=>{
      if (d.agents) setList(d.agents);
      setLoading(false);
    }).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading'));
  return h('div',null,
    list.map((a,i)=>h(AgentCard,{key:i,agent:a,onUpdate})),
  );
}

/* ── Audit log (in Security page) ────────────────────────────── */

function AuditLog() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/admin/audit?limit=30').then(r=>r.json()).then(d=>{setRows(d.rows||[]);setLoading(false)}).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:8,fontSize:11,color:'var(--text-dim)'}}, _t('admin.loading'));
  if (!rows.length) return h('div',{style:{padding:8,fontSize:11,color:'var(--text-dim)'}}, _t('admin.no_audit'));
  return h('div',{style:{marginTop:8}},
    rows.slice(0,20).map((r,i)=>h('div',{key:i,style:{
      display:'flex',gap:12,padding:'4px 0',fontFamily:'var(--font-mono)',fontSize:10,
      borderBottom:'1px solid var(--border-glass)',color:'var(--text-secondary)',
    }},
      h('span',{style:{width:80,flexShrink:0}}, r.timestamp ? r.timestamp.slice(11,19) : '--'),
      h('span',{style:{width:80,flexShrink:0,color:'var(--accent)'}}, r.event_type||'--'),
      h('span',{style:{width:60,flexShrink:0}}, r.agent_id||'--'),
      h('span',{style:{flex:1,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}, r.summary||''),
    )),
  );
}

/* ── LLM test button ─────────────────────────────────────────── */

function LLMTest() {
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const test = () => {
    setBusy(true);
    fetch('/api/admin/llm/test',{method:'POST'}).then(r=>r.json()).then(d=>{setResults(d.results);setBusy(false)}).catch(()=>setBusy(false));
  };
  return h('div',null,
    h('button',{className:'admin-btn is-primary', onClick:test, disabled:busy}, busy ? _t('admin.test_busy') : _t('admin.test_btn')),
    results && h('div',{style:{marginTop:10,display:'flex',flexDirection:'column',gap:4}},
      results.map((r,i)=>h('div',{key:i,style:{display:'flex',gap:12,fontFamily:'var(--font-mono)',fontSize:11,alignItems:'center'}},
        h('span',{style:{width:100}}, r.name),
        r.ok
          ? h('span',{style:{color:'var(--green-active)'}}, '✓ Online')
          : h('span',{style:{color:'var(--red-alert)'}}, '✗ Offline'),
        h('span',{style:{color:'var(--text-dim)',fontSize:10}}, r.status ? `HTTP ${r.status}` : (r.error||'')),
      )),
    ),
  );
}

/* ── Memory clear button ─────────────────────────────────────── */

function MemoryClear({ onToast }) {
  const clear = () => {
    if (!confirm(_t('admin.confirm_clear'))) return;
    fetch('/api/admin/memory/clear',{method:'POST'}).then(r=>r.json()).then(d=>{onToast(d.message||_t('admin.btn_clear'))}).catch(()=>onToast(_t('admin.error_unknown')));
  };
  return h('button',{className:'admin-btn is-danger', onClick:clear}, _t('admin.btn_clear'));
}

/* ── Oracle Pipeline Weaver panel ───────────────────────────── */

function OraclePage() {
  const [data, setData] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState('status');

  const fetchData = () => {
    fetch('/api/oracle/status').then(r=>r.json()).then(d=>setData(d)).catch(()=>{});
    fetch('/api/oracle/conflicts').then(r=>r.json()).then(d=>setConflicts(d.conflicts||[])).catch(()=>{});
  };

  useEffect(() => { fetchData(); const id = setInterval(fetchData, 15000); return ()=>clearInterval(id); }, []);

  const doSync = () => {
    setSyncing(true);
    fetch('/api/oracle/sync', {method:'POST'}).then(r=>r.json()).then(()=>{ fetchData(); setSyncing(false); }).catch(()=>setSyncing(false));
  };

  const resolveConflicts = () => {
    fetch('/api/oracle/conflicts/resolve', {method:'POST'}).then(r=>r.json()).then(()=>fetchData()).catch(()=>{});
  };

  if (!data) return h('div',{className:'oracle-loading'}, _t('admin.loading'));

  return h('div',{className:'oracle-wrap'},
    h('div',{className:'oracle-tabs'},
      h('button',{className:`oracle-tab ${tab==='status'?'is-active':''}`, onClick:()=>setTab('status')}, _t('oracle.tab.status')),
      h('button',{className:`oracle-tab ${tab==='sessions'?'is-active':''}`, onClick:()=>setTab('sessions')}, _t('oracle.tab.sessions')),
      h('button',{className:`oracle-tab ${tab==='conflicts'?'is-active':''}`, onClick:()=>setTab('conflicts')}, _t('oracle.tab.conflicts'), conflicts.length ? ` (${conflicts.length})` : ''),
    ),

    tab === 'status' && h('div',{className:'oracle-status'},
      h('div',{className:'oracle-watcher'}, data.watcher_running ? _t('oracle.watcher_on') : _t('oracle.watcher_off')),
      h('div',{className:'oracle-meta'}, `Last checked: ${data.last_checked || '—'} · Total sessions: ${data.total_sessions}`),

      data.current_session
        ? h('div',{className:'oracle-session-card'},
            h('div',{className:'oracle-session-header'}, `Session: ${data.current_session.session_id}`),
            h('div',{className:'oracle-session-status'}, `Status: ${data.current_session.status} · Commit: ${data.current_session.commit_sha||'—'}`),
            data.current_session.commit_msg && h('div',{className:'oracle-commit-msg'}, data.current_session.commit_msg),
            data.current_session.tasks_completed?.length
              ? h('div',{className:'oracle-tasks'}, `Tasks: ${data.current_session.tasks_completed.join(', ')}`)
              : null,
            data.current_session.tests_total > 0
              ? h('div',{className:`oracle-tests ${data.current_session.tests_failed > 0 ? 'is-fail' : 'is-pass'}`},
                  `Tests: ${data.current_session.tests_passed}/${data.current_session.tests_total} passed` +
                  (data.current_session.tests_failed ? ` · ${data.current_session.tests_failed} failed` : ''))
              : null,
            data.current_session.error && h('div',{className:'oracle-error'}, data.current_session.error),
          )
        : h('div',{className:'oracle-empty'}, _t('oracle.no_session')),

      h('button',{className:'admin-btn is-primary', onClick:doSync, disabled:syncing},
        syncing ? _t('oracle.syncing') : _t('oracle.sync_btn')),
    ),

    tab === 'sessions' && h('div',{className:'oracle-sessions'},
      (data.sessions || []).length === 0
        ? h('div',{className:'oracle-empty'}, _t('oracle.no_session'))
        : (data.sessions || []).slice().reverse().map(s => h('div',{key:s.session_id, className:'oracle-session-row'},
            h('span',{className:'oracle-ses-id'}, s.session_id),
            h('span',{className:`oracle-ses-status oracle-ses-${s.status}`}, s.status),
            h('span',{className:'oracle-ses-commit'}, s.commit_sha ? s.commit_sha.slice(0,8) : '—'),
            h('span',{className:'oracle-ses-tasks'}, (s.tasks_completed||[]).join(', ')),
            h('span',{className:`oracle-ses-tests ${s.tests_failed > 0 ? 'is-fail' : 'is-pass'}`},
              s.tests_total ? `${s.tests_passed}/${s.tests_total}` : '—'),
          ))
    ),

    tab === 'conflicts' && h('div',{className:'oracle-conflicts'},
      conflicts.length === 0
        ? h('div',{className:'oracle-empty'}, _t('oracle.conflict_none'))
        : h('div',null,
            h('p',{className:'oracle-warn'}, _t('oracle.conflict_found')),
            conflicts.map(c => h('div',{key:c.file_path, className:'oracle-conflict-row'},
              h('span',{className:'oracle-conflict-file'}, c.file_path),
              h('span',{className:'oracle-conflict-hash'}, `local:${c.local_hash.slice(0,6)} remote:${c.remote_hash.slice(0,6)}`),
            )),
            h('button',{className:'admin-btn is-success', onClick:resolveConflicts}, _t('oracle.resolve_btn')),
          ),
    ),
  );
}

/* ── Local model management panel (H12.9) ──────────────────── */

function LocalModelsPage({ onToast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState('');

  const fetchModels = () => {
    setLoading(true);
    fetch('/api/models/local').then(r=>r.json()).then(d=>{setData(d);setLoading(false);})
      .catch(()=>{setData({models:[],providers:[]});setLoading(false);});
  };
  useEffect(()=>{fetchModels();},[]);

  const switchModel = (id) => {
    if (id === data.active) return;
    setSwitching(id);
    fetch('/api/models/local/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:id})})
      .then(r=>{if(!r.ok) return r.json().then(d=>{throw new Error(d.error||'switch failed')}); return r.json();})
      .then(d=>{ onToast('Model activ: '+d.active); setSwitching(''); fetchModels(); })
      .catch(e=>{ onToast('Eroare: '+e.message); setSwitching(''); });
  };

  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}}, 'Se încarcă modelele locale…');

  const providers = data.providers || [];
  const models = data.models || [];

  return h('div',null,
    // Provider availability strip
    h('div',{style:{display:'flex',gap:10,marginBottom:16,flexWrap:'wrap'}},
      providers.map(p => h('div',{key:p.name,style:{
        display:'flex',alignItems:'center',gap:6,padding:'4px 10px',
        background:'var(--bg-glass)',borderRadius:20,border:'1px solid var(--border-glass)',fontSize:11,
      }},
        h('div',{style:{width:8,height:8,borderRadius:'50%',background: p.online ? 'var(--green-active)' : 'var(--text-dim)'}}),
        p.name,
        h('span',{style:{color:'var(--text-dim)'}}, p.online ? 'disponibil' : 'offline'),
      )),
      h('button',{className:'admin-btn',style:{fontSize:11,padding:'3px 10px',marginLeft:'auto'},onClick:fetchModels}, 'Reîmprospătează'),
    ),

    models.length === 0
      ? h('p',{style:{padding:12,fontSize:12,color:'var(--text-dim)'}},
          'Niciun model local găsit. Pornește LM Studio (port 1234) sau Ollama (port 11434) și descarcă un model.')
      : h('div',{style:{display:'flex',flexDirection:'column',gap:8}},
          h('div',{style:{fontSize:11,color:'var(--text-dim)',marginBottom:4}}, 'Modele instalate: '+models.length),
          models.map(m => h('div',{key:m.provider+'/'+m.id,style:{
            display:'flex',alignItems:'center',gap:10,padding:'8px 12px',
            background:'var(--bg-glass)',borderRadius:8,
            border:'1px solid '+(m.active?'var(--accent)':'var(--border-glass)'),
          }},
            h('div',{style:{width:8,height:8,borderRadius:'50%',flexShrink:0,background: m.active ? 'var(--accent)' : 'var(--text-dim)'}}),
            h('div',{style:{flex:1,minWidth:0}},
              h('div',{style:{fontSize:13,fontWeight:600,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}, m.id),
              h('div',{style:{fontSize:10,color:'var(--text-dim)'}}, m.provider),
            ),
            m.active
              ? h('span',{style:{fontSize:11,color:'var(--accent)',fontWeight:600,padding:'3px 8px'}}, 'Activ')
              : h('button',{className:'admin-btn is-primary',style:{fontSize:11,padding:'3px 10px'},
                  disabled: !!switching, onClick:()=>switchModel(m.id)},
                  switching === m.id ? '…' : 'Activează'),
          )),
        ),
  );
}

/* ── MCP Server Management panel ────────────────────────────── */

function MCPPage({ onToast }) {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:'', transport:'stdio', command:'', url:'' });

  const fetchServers = () => {
    setLoading(true);
    fetch('/api/admin/mcp').then(r=>r.json()).then(d=>{setServers(d.servers||[]);setLoading(false)}).catch(()=>setLoading(false));
  };
  useEffect(()=>{fetchServers();},[]);

  const addServer = (e) => {
    e.preventDefault();
    if (!form.name) return;
    const body = { name:form.name, transport:form.transport };
    if (form.transport === 'stdio') body.command = form.command;
    else body.url = form.url;
    fetch('/api/admin/mcp', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
      .then(r=>{if (!r.ok) return r.json().then(d=>{throw new Error(d.error)}); return r.json()})
      .then(()=>{ onToast(_t('mcp.add_success')); setShowForm(false); setForm({name:'',transport:'stdio',command:'',url:''}); fetchServers(); })
      .catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  const removeServer = (name) => {
    if (!confirm(_t('mcp.remove_confirm')+name+'?')) return;
    fetch(`/api/admin/mcp/${encodeURIComponent(name)}`, {method:'DELETE'})
      .then(r=>r.json()).then(()=>{ onToast(_t('mcp.remove_success')); fetchServers(); })
      .catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  const toggleConnect = (srv) => {
    const action = srv.connected ? 'disconnect' : 'connect';
    fetch(`/api/admin/mcp/${encodeURIComponent(srv.name)}/${action}`, {method:'POST'})
      .then(r=>r.json()).then(d=>{
        if (action === 'connect') onToast(d.ok ? _t('mcp.connect_success') : (d.error||'Connect failed'));
        else onToast(_t('mcp.disconnect_success'));
        fetchServers();
      }).catch(e=>onToast(_t('admin.error_prefix')+e.message));
  };

  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}}, _t('admin.loading'));

  return h('div',null,
    servers.length === 0
      ? h('p',{style:{padding:12,fontSize:12,color:'var(--text-dim)'}}, _t('mcp.no_servers'))
      : h('div',{style:{display:'flex',flexDirection:'column',gap:8,marginBottom:16}},
          h('div',{style:{fontSize:11,color:'var(--text-dim)',marginBottom:4}}, _t('mcp.total')+servers.length),
          servers.map(srv => h('div',{key:srv.name,style:{
            display:'flex',alignItems:'center',gap:10,padding:'8px 12px',
            background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',
          }},
            h('div',{style:{
              width:8,height:8,borderRadius:'50%',flexShrink:0,
              background: srv.connected ? 'var(--green-active)' : 'var(--text-dim)',
            }}),
            h('div',{style:{flex:1,minWidth:0}},
              h('div',{style:{fontSize:13,fontWeight:600}}, srv.name),
              h('div',{style:{fontSize:10,color:'var(--text-dim)'}},
                srv.transport === 'stdio' ? srv.command : srv.url,
                ' · ', srv.tools_count, _t('mcp.tools'),
              ),
            ),
            srv.tools_count > 0 && h('div',{style:{fontSize:10,color:'var(--text-secondary)',maxWidth:200,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},
              srv.tools.map(t=>t.name).join(', ')
            ),
            h('button',{className:'admin-btn', style:{fontSize:11,padding:'3px 8px'},
              onClick:()=>toggleConnect(srv)},
              srv.connected ? _t('mcp.disconnect') : _t('mcp.connect')
            ),
            h('button',{className:'admin-btn is-danger', style:{fontSize:11,padding:'3px 8px'},
              onClick:()=>removeServer(srv.name)},
              _t('mcp.remove')
            ),
          )),
        ),

    showForm
      ? h('form',{onSubmit:addServer, style:{background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',padding:12}},
          h('div',{style:{fontSize:12,fontWeight:600,marginBottom:8}}, _t('mcp.add_title')),
          h(InputRow,{label:_t('mcp.name'), value:form.name, onChange:v=>setForm({...form,name:v})}),
          h(SelectRow,{label:_t('mcp.transport'), value:form.transport, onChange:v=>setForm({...form,transport:v}), opts:['stdio','sse']}),
          form.transport === 'stdio'
            ? h(InputRow,{label:_t('mcp.command'), value:form.command, onChange:v=>setForm({...form,command:v})})
            : h(InputRow,{label:_t('mcp.url'), value:form.url, onChange:v=>setForm({...form,url:v})}),
          h('div',{style:{display:'flex',gap:8,marginTop:8}},
            h('button',{type:'submit',className:'admin-btn is-primary'}, _t('mcp.add_submit')),
            h('button',{type:'button',className:'admin-btn', onClick:()=>setShowForm(false)}, _t('oracle.sync_btn') ? 'Anulează' : 'Anulează'),
          ),
        )
      : h('button',{className:'admin-btn is-primary', onClick:()=>setShowForm(true)}, _t('mcp.add_btn')),
  );
}

/* ── SVG Chart components ───────────────────────────────────── */

function StatsCard({ label, value, color }) {
  return h('div', {style:{
    background:'var(--bg-glass)',borderRadius:8,border:'1px solid var(--border-glass)',
    padding:'16px',flex:1,textAlign:'center',minWidth:120,
  }},
    h('div',{style:{fontSize:28,fontWeight:700,color:color||'var(--accent)'}}, value),
    h('div',{style:{fontSize:11,color:'var(--text-dim)',marginTop:4}}, label),
  );
}

function BarChart({ data, valueKey, labelKey, maxValue, colorFn, unit }) {
  if (!data || !data.length) return null;
  const max = maxValue || Math.max(...data.map(d => d[valueKey]), 0.01);
  const barH = 18;
  const gap = 4;
  const svgHeight = data.length * (barH + gap);
  const lw = 80;
  const cw = 260;
  const tw = lw + cw + 70;
  return h('svg',{viewBox:`0 0 ${tw} ${svgHeight}`,width:'100%',style:{maxWidth:tw,maxHeight:svgHeight}},
    data.map((d,i)=>{
      const y = i * (barH + gap);
      const ratio = Math.min(d[valueKey] / max, 1);
      const bw = Math.max(ratio * cw, 2);
      const c = typeof colorFn === 'function' ? colorFn(ratio) : 'var(--accent)';
      return [
        h('text',{key:`l${i}`,x:0,y:y+barH-4,fontSize:10,fill:'var(--text-secondary)'}, d[labelKey]||''),
        h('rect',{key:`b${i}`,x:lw,y:y,width:bw,height:barH-2,rx:2,fill:c,opacity:0.85}),
        h('text',{key:`v${i}`,x:lw+bw+4,y:y+barH-4,fontSize:9,fill:'var(--text-dim)'}, `${d[valueKey]}${unit||''}`),
      ];
    })
  );
}

function Sparkline({ data, width, height, color }) {
  if (!data || data.length < 2) return h('div',{style:{padding:12,fontSize:11,color:'var(--text-dim)'}},'—');
  const pad = {top:8,right:8,bottom:18,left:8};
  const w = width - pad.left - pad.right;
  const sparkHeight = height - pad.top - pad.bottom;
  const vals = data.map(d=>d.value);
  const mx = Math.max(...vals,1);
  const mn = Math.min(...vals,0);
  const rng = mx - mn || 1;
  const pts = data.map((d,i)=>{
    const x = pad.left + (i/(data.length-1))*w;
    const y = pad.top + sparkHeight - ((d.value-mn)/rng)*sparkHeight;
    return `${x},${y}`;
  }).join(' ');
  const xLabels = data.map((d,i)=>{
    if (data.length>8 && i%Math.ceil(data.length/8)!==0 && i!==data.length-1) return null;
    return h('text',{key:`x${i}`,x:pad.left+(i/(data.length-1))*w,y:height-2,fontSize:8,fill:'var(--text-dim)',textAnchor:'middle'},d.label);
  });
  return h('svg',{viewBox:`0 0 ${width} ${height}`,width:'100%',style:{maxWidth:width,maxHeight:height}},
    h('text',{key:'ymx',x:0,y:pad.top+8,fontSize:9,fill:'var(--text-dim)'}, mx),
    ...xLabels,
    h('polyline',{key:'pl',points:pts,fill:'none',stroke:color||'var(--accent)',strokeWidth:1.5,strokeLinejoin:'round'}),
    h('polygon',{key:'pg',points:pts+` ${pad.left+w},${height-pad.bottom} ${pad.left},${height-pad.bottom}`,fill:color||'var(--accent)',opacity:0.06}),
  );
}

/* ── Recall (Memory) page ───────────────────────────────────── */

function RecallPage() {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [openCats, setOpenCats] = useState({});

  useEffect(() => {
    fetch('/api/memory/profile').then(r => r.json()).then(d => {
      setProfile(d);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const doSearch = (e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    fetch(`/api/memory/recall?q=${encodeURIComponent(q)}`).then(r => r.json()).then(d => {
      setResults(d.results || []);
      setSearching(false);
    }).catch(() => setSearching(false));
  };

  const toggleCat = (cat) => setOpenCats(prev => ({ ...prev, [cat]: !prev[cat] }));

  const isEmpty = !profile || Object.keys(profile).length === 0;

  return h('div', null,
    h('form', { onSubmit: doSearch, style: { display: 'flex', gap: 8, marginBottom: 20 } },
      h('input', {
        className: 'admin-input',
        type: 'text',
        placeholder: 'Caută în memorie...',
        value: query,
        onChange: e => setQuery(e.target.value),
        style: { flex: 1 },
      }),
      h('button', { type: 'submit', className: 'admin-btn is-primary', disabled: searching },
        searching ? 'Se caută...' : 'Caută'
      ),
    ),

    results !== null && h('div', { className: 'admin-group', style: { marginBottom: 20 } },
      h('div', { className: 'admin-group-header' }, `Rezultate căutare (${results.length})`),
      results.length === 0
        ? h('div', { style: { padding: 12, fontSize: 12, color: 'var(--text-dim)' } }, 'Niciun rezultat găsit.')
        : results.map((r, i) => h('div', {
            key: i,
            style: {
              display: 'flex', gap: 12, padding: '6px 12px',
              borderBottom: '1px solid var(--border-glass)',
              fontFamily: 'var(--font-mono)', fontSize: 11,
            },
          },
          h('span', { style: { color: 'var(--accent)', width: 100, flexShrink: 0 } }, r.category || '—'),
          h('span', { style: { width: 120, flexShrink: 0, color: 'var(--text-secondary)' } }, r.key || '—'),
          h('span', { style: { flex: 1, color: 'var(--text-primary)' } }, String(r.value || '')),
        ))
    ),

    loading
      ? h('div', { style: { padding: 20, fontSize: 12, color: 'var(--text-dim)' } }, _t('admin.loading'))
      : isEmpty
        ? h('div', { style: { padding: 20, fontSize: 12, color: 'var(--text-dim)' } }, 'No memory entries yet.')
        : Object.entries(profile).map(([cat, facts]) =>
            h('div', { key: cat, className: 'admin-group', style: { marginBottom: 8 } },
              h('button', {
                className: 'admin-group-header',
                style: {
                  display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text-primary)', textAlign: 'left',
                },
                onClick: () => toggleCat(cat),
              },
                ICONS.memory,
                h('span', { style: { flex: 1 } }, cat),
                h('span', { style: { fontSize: 11, color: 'var(--text-dim)' } }, `${facts.length} fapte`),
                h('span', { style: { color: 'var(--text-dim)', fontSize: 12 } }, openCats[cat] ? '▲' : '▼'),
              ),
              openCats[cat] && facts.map((f, i) => h('div', {
                key: i,
                style: {
                  display: 'flex', gap: 12, padding: '5px 12px',
                  borderBottom: '1px solid var(--border-glass)',
                  fontFamily: 'var(--font-mono)', fontSize: 11,
                },
              },
                h('span', { style: { width: 160, flexShrink: 0, color: 'var(--text-secondary)' } }, f.key),
                h('span', { style: { flex: 1, color: 'var(--text-primary)' } }, String(f.value)),
              ))
            )
          )
  );
}

/* ── Cost & Model Tiers page ────────────────────────────────── */

function CostPage() {
  const [tiers, setTiers] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/analytics/cost').then(r => r.json()),
      fetch('/api/analytics/model-tiers').then(r => r.json()),
    ]).then(([_cost, tierData]) => {
      setTiers(tierData);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return h('div', { style: { padding: 20, fontSize: 12, color: 'var(--text-dim)' } }, _t('admin.loading'));
  if (!tiers) return h('div', { style: { padding: 20, fontSize: 12, color: 'var(--text-dim)' } }, 'Eroare la încărcarea datelor.');

  const allEmpty = tiers.total_cost_usd === 0 && Object.values(tiers.tier_counts || {}).every(c => c === 0);

  if (allEmpty) {
    return h('div', { style: { padding: 20, fontSize: 12, color: 'var(--text-dim)' } }, 'No usage recorded yet.');
  }

  const tierDefs = [
    { key: 'local',    label: 'Local',    color: '#4ade80' },
    { key: 'fast',     label: 'Fast',     color: '#60a5fa' },
    { key: 'standard', label: 'Standard', color: '#a78bfa' },
    { key: 'heavy',    label: 'Heavy',    color: '#f87171' },
  ];

  return h('div', null,
    h('div', { style: { display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' } },
      h(StatsCard, { label: 'Cost Total (USD)', value: '$' + (tiers.total_cost_usd || 0).toFixed(4), color: '#f59e0b' }),
      ...tierDefs.map(td =>
        h(StatsCard, { key: td.key, label: td.label + ' Agents', value: (tiers.tier_counts || {})[td.key] || 0, color: td.color })
      ),
    ),

    h('div', { className: 'admin-group' },
      h('div', { className: 'admin-group-header' }, 'Distribuție pe Tier de Model'),
      h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 12 } },
        h('thead', null,
          h('tr', { style: { borderBottom: '1px solid var(--border-glass)', color: 'var(--text-dim)', fontSize: 11 } },
            h('th', { style: { textAlign: 'left', padding: '4px 8px' } }, 'Tier'),
            h('th', { style: { textAlign: 'right', padding: '4px 8px' } }, 'Agenți'),
            h('th', { style: { textAlign: 'right', padding: '4px 8px' } }, 'Total Apeluri'),
            h('th', { style: { textAlign: 'right', padding: '4px 8px' } }, 'Cost (USD)'),
          ),
        ),
        h('tbody', null,
          tierDefs.map(td => {
            const agentList = (tiers.tiers || {})[td.key] || [];
            const totalCalls = agentList.reduce((s, a) => s + (a.calls || 0), 0);
            const totalCost = agentList.reduce((s, a) => s + (a.cost_usd || 0), 0);
            return h('tr', {
              key: td.key,
              style: { borderBottom: '1px solid var(--border-glass)' },
            },
              h('td', { style: { padding: '6px 8px', color: td.color, fontWeight: 600 } }, td.label),
              h('td', { style: { padding: '6px 8px', textAlign: 'right' } }, agentList.length),
              h('td', { style: { padding: '6px 8px', textAlign: 'right' } }, totalCalls),
              h('td', { style: { padding: '6px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)' } }, '$' + totalCost.toFixed(4)),
            );
          })
        ),
      ),
    ),

    tierDefs.map(td => {
      const agentList = (tiers.tiers || {})[td.key] || [];
      if (agentList.length === 0) return null;
      return h('div', { key: td.key, className: 'admin-group', style: { marginTop: 12 } },
        h('div', { className: 'admin-group-header', style: { color: td.color } }, td.label + ' — Detalii Agenți'),
        agentList.map((a, i) => h('div', {
          key: i,
          style: {
            display: 'flex', gap: 12, padding: '5px 12px',
            borderBottom: '1px solid var(--border-glass)', fontSize: 11,
          },
        },
          h('span', { style: { width: 100, flexShrink: 0, fontWeight: 600 } }, a.agent),
          h('span', { style: { flex: 1, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' } }, a.model),
          h('span', { style: { width: 60, textAlign: 'right', color: 'var(--text-secondary)' } }, a.calls + ' calls'),
          h('span', { style: { width: 80, textAlign: 'right', fontFamily: 'var(--font-mono)', color: td.color } }, '$' + (a.cost_usd || 0).toFixed(4)),
        ))
      );
    }),
  );
}

/* ── Charts page ────────────────────────────────────────────── */

function ChartsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    fetch('/api/admin/stats').then(r=>r.json()).then(d=>{setData(d);setLoading(false)}).catch(()=>setLoading(false));
  },[]);
  if (loading) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('admin.loading'));
  if (!data || !data.overview) return h('div',{style:{padding:20,fontSize:12,color:'var(--text-dim)'}},_t('charts.no_data'));

  const ov = data.overview;
  const agents = (data.agents||[]).sort((a,b)=>b.success_rate - a.success_rate);
  const latencyAgents = (data.agents||[]).sort((a,b)=>b.p95_latency - a.p95_latency);
  const daily = (data.daily||[]).slice(-14).map(d=>({label:d.date.slice(5),value:d.total}));
  const channels = Object.entries(data.channels||{});
  const chMax = Math.max(...channels.map(c=>c[1]),1);
  const errors = data.error_types||[];

  const greenYellow = (r) => r > 0.8 ? '#4ade80' : r > 0.5 ? '#facc15' : '#f87171';

  return h('div',null,
    h('div',{style:{display:'flex',gap:12,marginBottom:20,flexWrap:'wrap'}},
      h(StatsCard,{label:_t('charts.total_int'),value:ov.total_interactions,color:'var(--accent)'}),
      h(StatsCard,{label:_t('charts.success_rate'),value:(ov.success_rate*100).toFixed(0)+'%',color:greenYellow(ov.success_rate)}),
      h(StatsCard,{label:_t('charts.avg_latency'),value:ov.avg_latency.toFixed(1)+'s',color:'#60a5fa'}),
      h(StatsCard,{label:_t('charts.agents'),value:ov.agents_tracked,color:'#a78bfa'}),
    ),

    agents.length > 0 && h('div',{className:'admin-group'},
      h('div',{className:'admin-group-header'}, _t('charts.success')),
      h(BarChart,{data:agents.map(a=>({label:a.agent_id,value:a.success_rate*100})),
        valueKey:'value',labelKey:'label',maxValue:100,unit:'%',
        colorFn:(r)=>r>0.8?'#4ade80':r>0.5?'#facc15':'#f87171'}),
    ),

    latencyAgents.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.latency')),
      h(BarChart,{data:latencyAgents.map(a=>({label:a.agent_id,value:a.p95_latency||a.avg_latency})),
        valueKey:'value',labelKey:'label',unit:'s',colorFn:()=>'#60a5fa'}),
    ),

    daily.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.daily_vol')),
      h(Sparkline,{data:daily,width:500,height:80,color:'var(--accent)'}),
    ),

    channels.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.channel')),
      channels.map(([ch,count],i)=>h('div',{key:i,style:{display:'flex',alignItems:'center',gap:8,padding:'4px 0'}},
        h('span',{style:{width:80,fontSize:11,color:'var(--text-secondary)'}}, ch),
        h('div',{style:{flex:1,height:14,background:'var(--bg-glass)',borderRadius:7,overflow:'hidden'}},
          h('div',{style:{width:`${(count/chMax)*100}%`,height:'100%',background:'var(--accent)',opacity:0.7,borderRadius:7}}),
        ),
        h('span',{style:{fontSize:10,color:'var(--text-dim)',width:40,textAlign:'right'}}, count),
      )),
    ),

    errors.length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.errors')),
      errors.map(([err,count],i)=>h('div',{key:i,style:{display:'flex',gap:8,padding:'3px 0',fontSize:11}},
        h('span',{style:{color:'var(--text-secondary)'}}, err),
        h('span',{style:{color:'#f87171',fontWeight:600}}, count),
      )),
    ),

    data.route_usage && Object.keys(data.route_usage).length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'}, _t('charts.route_usage')),
      h(BarChart,{data:Object.entries(data.route_usage).map(([k,v])=>({label:k,value:v})).sort((a,b)=>b.value-a.value),
        valueKey:'value',labelKey:'label',colorFn:()=>'#a78bfa'}),
    ),

    data.cost_estimates && h('div',{style:{display:'flex',gap:12,marginTop:20,flexWrap:'wrap'}},
      h(StatsCard,{label:_t('charts.cost_total'),
        value:'$'+data.cost_estimates.total.toFixed(4),color:'#f59e0b'}),
      data.cost_estimates.total_savings > 0 && h(StatsCard,{label:_t('charts.cost_savings'),
        value:'$'+data.cost_estimates.total_savings.toFixed(4),color:'#4ade80'}),
      h(StatsCard,{label:_t('charts.cache_active'),
        value:data.cost_estimates.total_interactions,color:'#60a5fa'}),
    ),

    // Resilience metrics
    data.resilience && Object.keys(data.resilience).length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'},'Resilience Metrics'),
      Object.entries(data.resilience).map(([key, stats])=>
        h('div',{key,style:{padding:'8px',margin:'4px 0',background:'var(--bg-glass)',borderRadius:6,fontSize:11}},
          h('div',{style:{fontWeight:600,color:'var(--text-secondary)',marginBottom:4}},key),
          h('div',{style:{display:'flex',gap:12}},
            h('span',{style:{color:'#4ade80'}},'S: '+stats.success),
            h('span',{style:{color:'#f87171'}},'F: '+stats.failure),
            h('span',{style:{color:'#60a5fa'}},'Avg: '+stats.avg_latency.toFixed(2)+'s'),
          ),
          stats.error_types && Object.keys(stats.error_types).length > 0 &&
            h('div',{style:{marginTop:4,color:'var(--text-dim)'}},
              'Errors: '+Object.entries(stats.error_types).map(([t,c])=>t+':'+c).join(', '),
            ),
        )
      ),
    ),

    // Circuit breakers
    data.circuit_breakers && Object.keys(data.circuit_breakers).length > 0 && h('div',{className:'admin-group',style:{marginTop:16}},
      h('div',{className:'admin-group-header'},'Circuit Breakers'),
      Object.entries(data.circuit_breakers).map(([key, cb])=>
        h('div',{key,style:{display:'flex',gap:12,padding:'6px 8px',margin:'4px 0',borderRadius:4,
          background:cb.state==='open'?'var(--error-bg)':cb.state==='half-open'?'var(--warning-bg)':'var(--bg-glass)'}},
          h('span',{style:{fontWeight:600,flex:1}},key),
          h('span',{style:{fontWeight:600,textTransform:'uppercase',fontSize:10,
            color:cb.state==='open'?'#f87171':cb.state==='half-open'?'#facc15':'#4ade80'}},cb.state),
          h('span',{style:{color:'var(--text-dim)',fontSize:10}},'Failures: '+cb.failure_count),
        )
      ),
    ),
  );
}

function AdminApp() {
  const [active, setActive] = useState('charts');
  const [settings, setSettings] = useState({});
  const [search, setSearch] = useState('');
  const [dirty, setDirty] = useState({});
  const [toast, setToast] = useState('');
  const [envData, setEnvData] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(()=>{
    fetch('/api/admin/settings').then(r=>r.json()).then(d=>setSettings(d));
    fetch('/api/admin/env').then(r=>r.json()).then(d=>setEnvData(d)).catch(()=>{});
  },[refreshKey]);

  const showToast = (msg) => { setToast(msg); setTimeout(()=>setToast(''), 2500); };

  const onUpdate = (key, value) => {
    setDirty(prev => ({...prev, [key]: value}));
  };

  const onAgentUpdate = (agentId, key, value) => {
    fetch(`/api/admin/agents/${agentId}`, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({updates:{[key]:value}}),
    }).then(r=>r.json()).then(d=>{
      if (d.saved) showToast(`${agentId}.${key} → ${JSON.stringify(value)}`);
      else showToast(`${_t('admin.error_prefix')}${d.error||_t('admin.error_unknown')}`);
    }).catch(e=>showToast(`${_t('admin.error_network')}${e.message}`));
  };

  const saveAllSettings = () => {
    const keys = Object.keys(dirty);
    if (!keys.length) return;
    
    // Group dirty settings by their actual category in the database
    const byCategory = {};
    keys.forEach(k => {
      let foundCat = 'general';
      for (const catId of Object.keys(settings)) {
        const list = settings[catId];
        if (list && Array.isArray(list)) {
          if (list.some(s => s.key === k)) {
            foundCat = catId;
            break;
          }
        }
      }
      if (!byCategory[foundCat]) byCategory[foundCat] = {};
      byCategory[foundCat][k] = dirty[k];
    });

    // Make PUT requests for each category in parallel
    const promises = Object.entries(byCategory).map(([cat, values]) => {
      return fetch(`/api/admin/settings/${cat}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values }),
      }).then(r => r.json());
    });

    Promise.all(promises)
      .then(results => {
        const totalUpdated = results.reduce((sum, r) => sum + (r.updated || 0), 0);
        setDirty({});
        showToast(`Parametri salvați cu succes! Am actualizat ${totalUpdated} setări.`);
        fetch('/api/admin/settings').then(r=>r.json()).then(s=>setSettings(s));
      })
      .catch(() => showToast('Eroare la salvarea setărilor globale.'));
  };

  const cat = CATEGORIES.find(c=>c.id===active);

  const isAgents = active === 'agents';
  const isSystem = active === 'system';
  const isOracle = active === 'oracle';
  const isMCP = active === 'mcp';
  const isCharts = active === 'charts';
  const isConfig = active === 'config';
  const isRecall = active === 'recall';
  const isCostView = active === 'costview';
  const isModels = active === 'models';

  return h('div',{className:'admin-wrap'},
    h('div',{className:'admin-sidebar'},
      h('div',{className:'admin-sidebar-head'},
        ICONS.system,
        _t('admin.brand'),
      ),
      h('nav',{className:'admin-nav', style:{marginTop:20}},
        CATEGORIES.map(c=>h('button',{
          key:c.id,
          className:`admin-nav-item ${active===c.id?'is-active':''}`,
          onClick:()=>{setActive(c.id);setSearch('');},
        }, ICONS[c.icon] || ICONS.general, c.label)),
      ),
    ),

    h('div',{className:'admin-content'},
      h('h1',null, cat ? cat.label : ''),
      h('p',{className:'admin-page-desc'}, cat ? (CATEGORY_DESC[cat.id]||'') : ''),

      isAgents
        ? h(AgentsPage,{onUpdate:onAgentUpdate})

        : isSystem
          ? h(SystemPage,{envData, onRefresh:()=>fetch('/api/admin/env').then(r=>r.json()).then(d=>setEnvData(d))})

          : isOracle
            ? h(OraclePage)

            : isMCP
              ? h(MCPPage,{onToast:showToast})

              : isCharts
                ? h(ChartsPage)

                : isConfig
                  ? h(GlobalConfigPage,{settings, dirty, onUpdate, onSave:saveAllSettings})

                  : isRecall
                    ? h(RecallPage)

                    : isCostView
                      ? h(CostPage)

                      : isModels
                        ? h(LocalModelsPage,{onToast:showToast})

                        : null,

      // Reseed settings button on System page
      active === 'system' && h('div',{style:{marginTop:20}},
        h('button',{className:'admin-btn is-warning',
          onClick:()=>{
            if (!confirm('Reinițializați toate setările la valorile implicite? Modificările custom vor fi pierdute.')) return;
            fetch('/api/admin/settings/reseed',{method:'POST'}).then(r=>r.json()).then(d=>{
              showToast(d.message||'Reseeded');
              setDirty({});
              setRefreshKey(k=>k+1);
            }).catch(()=>showToast('Reseed failed'));
          }
        }, '🔄 Resetează setări implicite'),
      ),
    ),

    h(Toast,{message:toast}),
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(h(AdminApp));
