# Quick-start for OpenCode + Qwen 3.7 Max

Paste this prompt into OpenCode (after navigating to your `cabinet/` directory):

```
Read design_handoff_jarvis_hub/README.md end-to-end first, especially §17 (v0.3 Cognition Release).
Then implement the design described there, targeting:

  cabinet/agents/web/templates/index.html
  cabinet/agents/web/static/style.css
  cabinet/agents/web/static/data.js
  cabinet/agents/web/static/app.js
  cabinet/agents/web/static/components.js
  cabinet/agents/web/static/network.js
  cabinet/agents/web/static/enhancements.js
  cabinet/agents/web/static/cognition.js       ← NEW v0.3
  cabinet/agents/web/static/systems.js         ← NEW v0.3
  cabinet/agents/web/static/dossier-modal.js   ← NEW v0.3

Use the prototype in design_handoff_jarvis_hub/design/ as the
visual + behavioral source of truth. Match it pixel-perfect.

Mode A (recommended): keep React via CDN, port .jsx → .js by
replacing JSX with React.createElement calls. Drop Babel.

Use existing FastAPI endpoints (/status, /chat/stream, /dashboard,
etc.). Add new endpoints from backend_snippets/endpoints_v03.py:
  - GET /memory/{agent_id}
  - GET /plugins
  - PUT /plugins/{plugin_id}/toggle
  - GET /cognition/stream (stretch)
  - GET /memory/stats
  - GET /learning/stats
  - GET /security/status
  - GET /bench/stats

After each file, show me a 10-line summary of what you did
before moving to the next. Work in the order from §13 of the README.

IMPORTANT FOR QWEN 3.7 MAX:
- Implement ONE file at a time. Stop after each file and show summary.
- Before each file, write a 3-5 line comment explaining what you'll do.
- After each major file (cognition, systems, dossier), verify in browser.
- React hooks pitfall: DO NOT define useState/useEffect in separate script files.
  All hooks must be in app.js or the file that defines them. If you define a hook
  in systems.jsx, export it and use it ONLY in app.js.
- Use props, not hooks, for components in separate files.
```

That's it. OpenCode will read the full README + design files on its own.

---

## Implementation Order (v0.3)

Follow this sequence strictly:

1. **data.js** — Add COGNITION_SCORING, PLUGINS, MEMORY_STATS, LEARNING, SECURITY, BENCH, DOSSIER structures
2. **cognition.jsx → cognition.js** — Intent classification, routing decision, orchestration trace panels
3. **systems.jsx → systems.js** — 4-tab panel (Memory, Plugins, Learning, Security & Bench)
4. **dossier-modal.jsx → dossier-modal.js** — Fullscreen modal on agent double-click
5. **app.js** — Integrate CognitionPanel, SystemsPanel, DossierModal into main app
6. **style.css** — Add CSS for cognition, systems, dossier panels
7. **index.html** — Add script tags for cognition.js, systems.js, dossier-modal.js
8. **Backend endpoints** — Add routes from backend_snippets/endpoints_v03.py to web.py
9. **Test** — Verify all panels render, endpoints respond, no console errors

---

## Key Pitfalls for Qwen 3.7 Max

### React Hooks in Multi-Script Architecture

**WRONG:**
```js
// In cognition.js (separate file)
function CognitionPanel() {
  const [data, setData] = useState(null);  // ❌ Hook in separate script
  return ...;
}
```

**CORRECT:**
```js
// In cognition.js
function CognitionPanel({ data, onRefresh }) {  // ✅ Props, not hooks
  return ...;
}

// In app.js
const [cognitionData, setCognitionData] = useState(null);  // ✅ Hook in app.js
<CognitionPanel data={cognitionData} onRefresh={refreshCognition} />
```

### Porting JSX to React.createElement

**JSX:**
```jsx
<div className="cog-section">
  <span className="cog-label">{label}</span>
</div>
```

**React.createElement:**
```js
h('div', { className: 'cog-section' },
  h('span', { className: 'cog-label' }, label)
)
```

### Endpoint Integration

Replace mock data fetches with real endpoints:

```js
// Mock (in data.js prototype)
const PLUGINS = { plugins: [...], total: 11 };

// Real (in production data.js)
async function loadPlugins() {
  const res = await fetch('/plugins');
  return await res.json();
}
```

---

## Verification Checklist

After implementing each major component:

- [ ] **Cognition Panel**: Open HUD → toggle Cognition panel → send "adaugă meeting mâine" → see keyword "meeting" with weight 0.78, agent pepper selected
- [ ] **Systems Panel**: Open Systems → Memory tab → see 47 sessions, 1284 vectors, 89 entities
- [ ] **Systems Panel**: Plugins tab → see 11 plugins, gmail has agents_served: [stark, pepper, veronica]
- [ ] **Dossier Modal**: Double-click Pepper → modal with archetype "Chief of Staff", model "gemma-4-26b-a4b", plugins [google-calendar, gmail]
- [ ] **Console**: Zero React hooks errors (order of hook calls is consistent)
- [ ] **Responsive**: At 1024px, Cognition panel becomes tab in right panel (not separate)

---

## Model Discrepancy Note

**Issue:** Sources are inconsistent:
- `agents.yaml`: all agents use default model (not specified per agent)
- `config.py`: default = `google/gemma-4-31b-a4b`
- `NERVA.md`: says `google/gemma-4-26b-a4b` (26b, not 31b)
- SOUL.md per agent: some mention `deepseek-r1:32b` or `qwen2.5` (probably outdated)

**Action:** Run `lms ps` to see what model is currently loaded, then update `data.js DOSSIER` with the real model per agent. If all use the same model, put it in `DOSSIER.jarvis.model` and leave others empty (they inherit default).
