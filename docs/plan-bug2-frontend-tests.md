# Plan BUG-2 — Frontend Test Coverage (0% → 60%)

> Generat: 2026-06-02 · Read-only până la aprobare · Status: **DRAFT**
> Analiză completă a scope-ului, framework-ului și efortului pentru React HUD tests.

---

## Context

**BUG-2:** 0% test coverage pe React HUD (~5047 LOC în `agents/web/static/`).
Nu există `package.json`, niciun test runner, niciun build step.
Framework: React 18.3.1 din CDN, `createElement` (fără JSX, fără bundler).

---

## Dimensiunea proiectului

| Fișier | LOC | Complexitate | Componente/Funcții |
|--------|-----|--------------|--------------------|
| `admin.js` | 1276 | 🔴 Înaltă | 26 funcții, 8 categorii setări |
| `systems.js` | 906 | 🟠 Medie | 11 funcții, polling, metrici |
| `workflows.js` | 621 | 🔴 Înaltă | 6 funcții, drag-drop SVG canvas |
| `components.js` | 481 | 🟢 Mică | 17 funcții, UI base |
| `app.js` | 415 | 🔴 Înaltă | App() + 40+ hooks, 20+ useState |
| `network.js` | 408 | 🟠 Medie | 5 funcții, fetch wrappers |
| `observability.js` | 277 | 🟠 Medie | 7 funcții, tracing UI |
| `enhancements.js` | 240 | 🟠 Medie | 7 funcții, feature toggles |
| `data.js` | 265 | 🟠 Medie | 1 funcție async, cache |
| `cognition.js` | 158 | 🟢 Mică | 4 funcții, agent thinking display |
| **TOTAL** | **5047** | — | **85+ funcții** |

---

## Framework detectat

- **React 18.3.1** importat din CDN local (`react.production.min.js`, `react-dom.production.min.js`)
- **Stil:** `React.createElement` aliased ca `h()` — **fără JSX, fără transpiling**
- **Hooks folosite:** `useState`, `useEffect`, `useRef`, `useMemo`, `useLayoutEffect`, `useCallback` (40+ utilizări)
- **Componente:** funcționale cu hooks (nu class-based)
- **Nu există:** `package.json`, `babel`, `webpack`, TypeScript

**Implicație critică:** Setup Jest mai complex decât standard — React CDN trebuie pre-loaded în helper de test.

---

## Configurare existentă de testing

**Niciun test runner configurat.** Căutare confirmată:
- Nu există `jest.config.*`
- Nu există `vitest.config.*`
- Nu există `.babelrc`
- Nu există `package.json`

---

## Fluxuri critice de testat (prioritizate)

### P1 — Chat Flow
- **Componente:** `App.js`, `InputBar`, `ConversationView`, `Message`
- **Endpoints mock:** `POST /chat/stream`
- **Test cases:** submit gol → no-op, submit cu conținut → API call, streaming response, error handling

### P1 — Admin Settings
- **Componente:** `admin.js` (26 funcții)
- **Endpoints mock:** `/api/admin/*` (8 endpoints)
- **Test cases:** navigare categorii, salvare setări → API sync, toggle features, validare formular

### P2 — Systems Monitor
- **Componente:** `systems.js`
- **Endpoints mock:** `/status`, `/dashboard`
- **Test cases:** refresh logic (30s interval), meter rendering, status dot color, polling lifecycle

### P3 — Voice Input
- **Custom hook:** `useTTS()`
- **Test cases:** toggle mic, tranziții stare, API failure, mock `getUserMedia`

### P3 — Workflows Canvas
- **Componente:** `WorkflowCanvas` (SVG interactiv)
- **Test cases:** layout algoritm, drag-drop pointer events, edge rendering

---

## Abordare recomandată

### Jest + jsdom (recomandat)

**De ce:**
- Standard industrie pentru React
- Rulează fără browser real (20x mai rapid decât E2E)
- Compatibil cu React CDN prin pre-load în setup

**Structură fișiere propusă:**
```
agents/web/static/__tests__/
├── setup.js              # pre-load React 18, mocks globale
├── components.test.js    # StatusDot, Bracket, Badge, SysRow
├── app.test.js           # App principal, routing, state
├── chat.test.js          # InputBar, ConversationView, Message, chat flow
├── admin.test.js         # settings categories, toggles, API sync
├── systems.test.js       # polling, meters, status colors
├── voice.test.js         # useTTS hook, mic toggle
├── workflows.test.js     # canvas layout, drag-drop
└── mocks/
    ├── fetch.js          # mock /api/*, /chat/stream streaming
    ├── webAudio.js       # mock getUserMedia, AudioContext
    └── helpers.js        # render(), waitFor(), custom utilities
```

### Playwright (alternativă pentru E2E)
- Când: voice input (WebAudio), service worker, offline mode
- Cost: 10x mai lent, necesită server pornit — **nu recomandat ca abordare principală**

---

## Estimare efort

| Sprint | Conținut | SP |
|--------|----------|----|
| Setup & infrastructure | `jest.config.js`, helpers, mock fetch streaming, CI pipeline | 5–8 |
| Componente simple | `StatusDot`, `Bracket`, `Badge`, `SysRow`, `Clock` | 8–10 |
| Chat flow | `InputBar`, `ConversationView`, `Message`, mock `/chat/stream` | 12–13 |
| Admin panel | categories, forms, toggles, mock `/api/admin/*` | 10–12 |
| Systems monitor | polling, meters, status colors | 6–8 |
| Voice + hooks | `useTTS()`, mic toggle, Web Audio mock | 8–10 |
| Workflows canvas | SVG layout, drag-drop, edge rendering | 10–12 |
| **TOTAL (60% coverage)** | | **59–75 SP** |

**Timeline:** ~4 săptămâni (1 SP = ~0.5 zile, paralel cu alte wave-uri)

---

## Riscuri și dependențe

| Risc | Impact | Mitigare |
|------|--------|----------|
| Fetch streaming greu de mockat | 🔴 Înalt | Custom helper `ReadableStream` mock |
| Browser APIs (`WebAudio`, `localStorage`) | 🟠 Mediu | jsdom polyfill + mocks |
| Polling cu `setInterval` | 🟠 Mediu | `jest.useFakeTimers()` |
| Niciun `package.json` — setup de la zero | 🟠 Mediu | Creat în primul sprint |
| CDN React — versioning instabil | 🟠 Mediu | Pin version, download local |
| Service Worker (`sw.js`) | 🟠 Mediu | Izolat și testat separat |

---

## Dependențe externe

- `npm` / `node` necesar pe mașina de dev și în CI
- GitHub Actions CI pipeline — modificare `.github/workflows/ci.yml` pentru a adăuga job `test-frontend`
- Nu blochează niciun wave Python — poate rula complet în paralel

---

## Checklist implementare

- [ ] `package.json` creat cu Jest 29+
- [ ] `jest.config.js` cu jsdom environment
- [ ] React 18 pre-loaded în `setup.js`
- [ ] Fetch mock cu suport streaming
- [ ] CI pipeline actualizat cu job frontend
- [ ] Coverage reporting (`jest --coverage`)
- [ ] Primele 5 unit tests merged
- [ ] Coverage badge în README

---

> **Status:** DRAFT — niciun cod scris. Implementare începe la aprobarea planului.
