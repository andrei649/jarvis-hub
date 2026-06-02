# HUD Frontend Tests

![HUD coverage](./coverage-badge.svg)

Unit tests for the Jarvis HUD (the React UI in `agents/web/static/`).
**156 tests / 20 spec files · ~66% line coverage** (target: 60%).

## Why this setup

The HUD has **no bundler and no build step**. It ships as a sequence of
`<script>` tags (vendored React 18 UMD + the static files) that share browser
globals — see `agents/web/templates/index.html`. `components.js` declares
helpers as `const` (lexical globals, *not* on `window`) and components as
`function` declarations (which *do* land on `window`).

So instead of re-bundling, the harness (`harness.js`) boots a **JSDOM with
`runScripts: 'dangerously'`** and injects the *real* shipped files as
`<script>` elements, exactly like the browser. This means tests exercise the
actual artifacts users get — no version drift between test and production.

A trailing "expose" script reads the lexical `const` bindings (`esc`, `pad2`,
`h`, …) from inside the page realm and surfaces them on `window.__hud` so specs
can reach them.

## Running

```bash
npm install          # first time
npm test             # run once (fast, no instrumentation)
npm run test:watch   # watch mode
npm run test:coverage   # instrumented run → coverage report + badge + 60% gate
```

CI runs `npm ci && npm run test:coverage` in the `frontend` job
(`.github/workflows/ci.yml`), which also fails if line coverage drops below 60%.

## Writing a test

```js
import { afterEach, beforeEach, expect, it } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({ files: ['components'], expose: ['StatusDot'] });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

it('renders a status dot', () => {
  const { container } = env.render(h(env.hud.StatusDot, { status: 'online' }));
  expect(container.querySelector('.dot-online')).not.toBeNull();
});
```

`loadHud({ files, expose, lang })`:
- `files` — static base-names to load after React, in order
  (default `['i18n', 'data', 'components']`). React UMD is always loaded first.
- `expose` — identifier names to surface on `env.hud` (needed for `const`
  helpers/components).
- `lang` — pre-seed `localStorage['hud.lang']`.

`loadHud` also accepts `fetch` (a stub installed before the app files run —
needed for `app.js`/panels that fetch on mount).

Returns `{ window, document, React, ReactDOM, hud, render, cleanup, ... }` plus
interaction helpers: `fire`, `click`, `type`, `selectOption`, `toggle`,
`keyDown`, and an async `flush()`.
`render(element)` mounts via `createRoot` + `flushSync` (synchronous DOM) and
returns `{ container, root, html }`.

## Coverage

`npm run test:coverage` (driver: `coverage.mjs`) measures real coverage of the
shipped static files. Because they run inside JSDOM — out of reach of vitest's
v8/istanbul providers — the harness instruments each file with `istanbul-lib-
instrument` before injecting it (`HUD_COVERAGE=1`), dumps each window's
`__coverage__` into `.nyc_output`, then `nyc` aggregates the report, writes
`coverage-badge.svg`, and gates the run at 60% lines.

> Earlier note (now resolved): the dangerous-realm approach used to preclude
> coverage instrumentation. The istanbul pre-instrumentation above closes that
> gap while keeping the high-fidelity loading.

## Fidelity note

Fidelity (running the shipped
artifacts) is the priority here; instrumented coverage of the static files is a
follow-up.

## Coverage status (BUG-2)

141 tests across 17 spec files. Coverage by source file:

| File | Tests |
|------|-------|
| `components.js` helpers (`esc`, `pad2`, `fmtTime`, `fmtDate`, `nowTs`) | ✅ `helpers.test.js` |
| `components.js` (`Bracket`, `StatusDot`) | ✅ `components.test.js` |
| `components.js` (`Badge`, `SysRow`, `SysMeter`, `InputBar`, `WeatherCard`, `CalendarCard`, `Message`, `ThinkingBubble`, `TopBar`) | ✅ `components-more.test.js` |
| `components.js` (`AgentList`, `AgentsGrid`, `HeartbeatFeed`) + `admin.renderRow` | ✅ `components-extra.test.js` |
| `i18n.js` (`_t`, `detectLocale`, `setLocale`) | ✅ `i18n.test.js` |
| `data.js` (constants + `loadJarvisData` resilience) | ✅ `data.test.js` |
| `admin.js` form rows (`ToggleRow`, `InputRow`, `SelectRow`, `SliderRow`, `TagInputRow`, `ButtonRow`, `InfoRow`, `Group`) | ✅ `admin-rows.test.js` |
| `systems.js` (`SystemsTabBar`, `FusedRecallBox`) | ✅ `systems.test.js` |
| `systems.js` (`MemoryTab`, `PluginsTab`, `LearningTab` guard) | ✅ `systems-tabs.test.js` |
| `systems.js` (`ResilienceTab` — regression guard) | ✅ `resilience.test.js` |
| `cognition.js` (all components) | ✅ `cognition.test.js` |
| `observability.js` (`_fmtMs`/`_agentList`, `TraceRow`, `TimingBar`, `TraceDetail`) | ✅ `observability.test.js` |
| `workflows.js` (`WorkflowCanvas`, `StepForm`, `ResultPanel`) | ✅ `workflows.test.js` |
| `enhancements.js` (`SituationTicker`, `CommandPalette`, `clamp`/`round`) | ✅ `enhancements.test.js` |
| `dossier-modal.js` (all components) | ✅ `dossier.test.js` |
| `network.js` (`textAnchorFor`, `tooltipStyle`, `NetworkBrain`) | ✅ `network.test.js` |
| `app.js` (mount smoke + apiDown fallback) | ✅ `app.test.js` |
| `app.js` chat flow (send → SSE stream → render) + polling intervals | ✅ `app-flows.test.js` |
| `admin.js` (full `AdminApp` mount + nav sweep, save flow, chart/card components) | ✅ `admin-app.test.js` |
| `systems.js` `SystemsPanel` (mount + full tab sweep), `workflows.js` `WorkflowsPanel`, `observability.js` `ObservabilityPanel` | ✅ `panels.test.js` |
| Browser E2E (Playwright) | ⬜ deferred follow-up (needs a running server + real browser) |

> **First catch:** these tests immediately surfaced a shipped syntax error in
> `systems.js` (`ResilienceTab` was missing its closing brace), which broke the
> *entire* Systems panel at load — present on `main`. Fixed in the same PR;
> `resilience.test.js` now guards against regressions.
