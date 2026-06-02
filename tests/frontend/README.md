# HUD Frontend Tests

Unit tests for the Jarvis HUD (the React UI in `agents/web/static/`).

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
npm test             # run once
npm run test:watch   # watch mode
npm run test:coverage
```

CI runs `npm ci && npm test` in the `frontend` job (`.github/workflows/ci.yml`).

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

Returns `{ window, document, React, ReactDOM, hud, render, cleanup }`.
`render(element)` mounts via `createRoot` + `flushSync` (synchronous DOM) and
returns `{ container, root, html }`.

## Known limitation

Scripts run inside JSDOM's own realm, so v8 line-coverage reflects the
harness/specs, not the in-page static files. Fidelity (running the shipped
artifacts) is the priority here; instrumented coverage of the static files is a
follow-up.

## Coverage status (BUG-2)

| File | Tests |
|------|-------|
| `components.js` (helpers: `esc`, `pad2`, `fmtTime`, `fmtDate`, `nowTs`) | ✅ `helpers.test.js` |
| `components.js` (`Bracket`, `StatusDot`) | ✅ `components.test.js` |
| `i18n.js` (`_t`, `detectLocale`, `setLocale`) | ✅ `i18n.test.js` |
| `data.js`, `network.js`, `cognition.js`, `systems.js`, `workflows.js`, `observability.js`, `admin.js`, `app.js` | ⬜ todo |
