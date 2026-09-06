# Web dashboard shell, navigation, shared components, i18n

This shard documents everything the Hermes Agent web dashboard renders *around* its pages: the SPA
bootstrap and route table (`web/src/App.tsx`, `web/src/main.tsx`), the sidebar and every nav label,
the header/page-header frame, the banners, the theme + font + language pickers, the system-action
buttons (Restart Gateway / Update Hermes), all shared components under `web/src/components/`, every
module under `web/src/lib/` (API client, WS auth, stores/helpers), the theme engine and its 8 built-in
themes + user-YAML themes, the plugin SDK / slot registry and the two plugin-contributed pages
(Kanban, Achievements), the full 714-key English i18n catalog grouped by namespace, and the Python
side that serves the SPA (`hermes_cli/web_server.py` `mount_spa`, auth modes, base-path rewriting,
`hermes dashboard` flags, profile routing).
Deliberately left to sibling shards: the *content* of each built-in page — Chat/Sessions/Files/
Analytics (web-a), Logs/Cron/Skills/Plugins/MCP (web-b), Config/Keys (config-a, config-b), the CLI
(cli-a, cli-b) — and the desktop/TUI/gateway surfaces. Where a shared component is only ever used by
one page, this shard specifies the component contract and points at the owning shard for the page
behaviour.

Version under inventory: `hermes-agent` tag **v2026.8.31** (package version `0.21.0`, as shown by the
sidebar version badge `v0.21.0`). Live evidence gathered from `http://127.0.0.1:9119` with header
`X-Hermes-Session-Token: inventory-token-123`.

---

## 1. SPA bootstrap and shell frame

### SPA entry document (`index.html`)  `id: web-shell.index-html`
- **Surface:** Web dashboard
- **Where:** The document the dashboard server returns for every non-asset path. Browser tab title is
  verbatim `Hermes Agent - Dashboard`.
- **What it does:** Minimal HTML shell that mounts the React app into `<div id="root">` and loads the
  Vite-built module bundle. It carries no UI of its own.
- **How it works:** `web/index.html:1-16`. `<html lang="en">`; `<meta charset="UTF-8">`;
  `<link rel="icon" type="image/svg+xml" href="/favicon.ico">`;
  `<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content">`
  (the `viewport-fit=cover` + `interactive-widget=resizes-content` pair is what makes the mobile
  soft-keyboard inset logic in `lib/keyboard-inset.ts` work); `<title>Hermes Agent - Dashboard</title>`;
  `<div id="root"></div>`; `<script type="module" src="/src/main.tsx"></script>` (rewritten to the
  hashed `/assets/index-<hash>.js` by the production build). At serve time the Python server injects a
  second `<script>` before `</head>` — see `web-shell.index-injection`.
- **Inputs / options:** n/a (static document).
- **Outputs / side effects:** Loads the bundle; the built page also emits `<link rel="modulepreload">`
  for `rolldown-runtime`, `react-vendor`, `vendor`, `ui`, `utils`, `i18n`, `api`,
  `page-header-context`, `useProfileScope`, `themes`, `chat-activation` chunks and one
  `<link rel="stylesheet" href="/assets/index-<hash>.css">`.
- **Config / env:** n/a.
- **Edge cases / guards:** Served with `Cache-Control: no-store, no-cache, must-revalidate` so a
  rotated session token is always picked up on reload.
- **Rebuild notes:** Any SPA shell works; the load-bearing parts are the `#root` mount node, the
  `viewport-fit=cover`/`interactive-widget=resizes-content` viewport, and the fact that the HTML is
  never cached so server-injected globals stay fresh. A better version would inline a critical-CSS
  skeleton of the sidebar so the first paint is not an empty canvas.

### React provider stack and router basename  `id: web-shell.provider-stack`
- **Surface:** Web dashboard
- **Where:** Not visible; it is the wrapper every page renders inside.
- **What it does:** Creates the React root and wraps `<App/>` in router, i18n, theme, and
  system-actions providers, in that exact order, and exposes the plugin SDK on `window` *before* the
  first render so plugin `<script>` tags that land early can call `register()`.
- **How it works:** `web/src/main.tsx:1-25`. Order, outermost first:
  1. `exposePluginSDK()` — called before `createRoot(...).render(...)` (`main.tsx:13`).
  2. `<BrowserRouter basename={HERMES_BASE_PATH || undefined}>` — `react-router` v8; basename comes
     from `window.__HERMES_BASE_PATH__` (see `web-shell.base-path`).
  3. `<I18nProvider>` (`i18n/context.tsx:151`).
  4. `<ThemeProvider>` (`themes/context.tsx:411`).
  5. `<SystemActionsProvider>` (`contexts/SystemActions.tsx:16`) — also renders the global `<Toast>`.
  6. `<App/>` (`App.tsx:372`), which itself opens `<ProfileProvider>` as its outermost element
     (`App.tsx:494`).
  `./index.css` is imported here, which is what pulls in Tailwind v4, the Nous DS `fonts.css` +
  `globals.css`, and the JetBrains Mono `@font-face` rules.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `window.__HERMES_PLUGINS__` and `window.__HERMES_PLUGIN_SDK__` are
  populated; the React tree mounts into `#root`.
- **Config / env:** `window.__HERMES_BASE_PATH__` (server-injected).
- **Edge cases / guards:** `basename` is `undefined` (not `""`) when the base path is empty, because
  react-router rejects an empty-string basename.
- **Rebuild notes:** Keep SDK exposure strictly before first render — plugin bundles are injected as
  `<script async>` and can execute at any time. A better version would expose the SDK from a module
  side-effect so ordering cannot regress.

### URL base path / reverse-proxy prefix  `id: web-shell.base-path`
- **Surface:** Web dashboard / API
- **Where:** Invisible; affects every URL the SPA builds (`/api/...`, `/dashboard-plugins/...`,
  router paths, WebSocket URLs).
- **What it does:** Lets the same built bundle work when the dashboard is served at the root of a host
  (`https://kanban.example.com/`) or under a prefix behind a reverse proxy
  (`https://mission-control.example.com/hermes/`), with no rebuild.
- **How it works:** The Python server reads `X-Forwarded-Prefix` from the incoming request, normalises
  it via `hermes_cli/dashboard_auth/prefix.py::normalise_prefix` (re-exported as
  `hermes_cli/web_server.py:17729 _normalise_prefix`), and injects
  `window.__HERMES_BASE_PATH__="<prefix>"` into `index.html`. The SPA reads it in
  `web/src/lib/api.ts:10-19 readBasePath()`: ensures a leading `/`, strips trailing `/`, `""` means
  root. `HERMES_BASE_PATH` is then used as (a) the react-router `basename` (`main.tsx:16`), (b) the
  prefix on every `fetch` in `fetchJSON`/`authedFetch` (`api.ts:119`, `api.ts:260`), (c) the
  `basePath` passed to `buildHermesWebSocketUrl` (`api.ts:284`, `lib/gatewayClient.ts:58`), and (d) the
  plugin asset URLs in `plugins/usePlugins.ts:105,117`. Server-side, `_serve_index` also rewrites
  absolute asset hrefs in the HTML (`href="/assets/` → `href="<prefix>/assets/`, same for
  `src="/assets/`, `href="/favicon.ico"`, `href="/fonts/`, `href="/ds-assets/`, `src="/ds-assets/`)
  at `web_server.py:17932-17940`, and `GET /assets/{filename}.css` rewrites `url(/fonts/`,
  `url(/fonts-terminal/`, `url(/ds-assets/`, `url(/assets/` inside the built CSS
  (`web_server.py:17964-17983`).
- **Inputs / options:** HTTP request header `X-Forwarded-Prefix`.
- **Outputs / side effects:** All client URLs gain the prefix; `<base>`-free operation.
- **Config / env:** `dashboard.public_url` (config) / `HERMES_DASHBOARD_PUBLIC_URL` — when set, the
  OAuth path ignores `X-Forwarded-Prefix` because the operator declared the full public URL.
- **Edge cases / guards:** Malformed prefixes are rejected by `normalise_prefix`; the prefix is only
  read per-request (never cached), so one process can serve both prefixed and unprefixed clients.
- **Rebuild notes:** Inject the prefix as a global rather than baking it into the bundle; rewrite both
  the HTML asset URLs and the CSS `url()` references. A better version would emit relative asset URLs
  from the bundler and skip string rewriting entirely.

### Lazy route loading and `RouteFallback`  `id: web-shell.route-lazy`
- **Surface:** Web dashboard
- **Where:** Brief centred spinner with the text `Loading…` (default) or `Loading chat…` while a route
  chunk downloads.
- **What it does:** Every page component is code-split so the initial shell does not download admin
  surfaces or heavy dependencies (xterm, three.js, Observable Plot) up front.
- **How it works:** `App.tsx:80-98` declares 19 `lazy(() => import(...))` page components:
  `ConfigPage`, `DocsPage`, `EnvPage`, `FilesPage`, `SessionsPage`, `LogsPage`, `AnalyticsPage`,
  `ModelsPage`, `CronPage`, `ProfilesPage`, `ProfileBuilderPage`, `SkillsPage`, `PluginsPage`,
  `McpPage`, `PairingPage`, `ChannelsPage`, `WebhooksPage`, `SystemPage`, `ChatPage`. The `<Routes>`
  tree is wrapped in `<Suspense fallback={<RouteFallback/>}>` (`App.tsx:776`). `RouteFallback`
  (`App.tsx:111-124`) renders `<div className="flex min-h-[12rem] flex-1 items-center justify-center"
  aria-busy="true" aria-live="polite">` containing a `<Spinner/>` and the label text.
- **Inputs / options:** `label` prop (default `"Loading…"`; the chat host passes `"Loading chat…"`).
- **Outputs / side effects:** Network fetch of the route chunk.
- **Config / env:** n/a.
- **Edge cases / guards:** `aria-busy`/`aria-live="polite"` make the state announced to screen readers.
- **Rebuild notes:** Route-level `React.lazy` + a single `Suspense` boundary. A better version would
  prefetch the chunk on nav-link hover.

### Built-in route table  `id: web-shell.route-table`
- **Surface:** Web dashboard
- **Where:** Browser URL bar; every sidebar link target.
- **What it does:** Maps 19 URL paths to page components (20 including `/chat`).
- **How it works:** `App.tsx:156-176` `BUILTIN_ROUTES_CORE`, in declaration order:
  | path | component |
  |---|---|
  | `/` | `RootRedirect` → `<Navigate to="/sessions" replace/>` (`App.tsx:126-128`) |
  | `/sessions` | `SessionsPage` |
  | `/files` | `FilesPage` |
  | `/analytics` | `AnalyticsPage` |
  | `/models` | `ModelsPage` |
  | `/logs` | `LogsPage` |
  | `/cron` | `CronPage` |
  | `/skills` | `SkillsPage` |
  | `/plugins` | `PluginsPage` |
  | `/mcp` | `McpPage` |
  | `/pairing` | `PairingPage` |
  | `/channels` | `ChannelsPage` |
  | `/webhooks` | `WebhooksPage` |
  | `/system` | `SystemPage` |
  | `/profiles` | `ProfilesPage` |
  | `/profiles/new` | `ProfileBuilderPage` |
  | `/config` | `ConfigPage` |
  | `/env` | `EnvPage` |
  | `/docs` | `DocsPage` |

  `/chat` is added conditionally (`App.tsx:451-457`) and maps to `ChatRouteSink`
  (`App.tsx:182-184`), a component that renders `null` — it exists only to claim the path so the
  `*` catch-all does not fire, because the real chat UI is painted by the persistent host outside
  `<Routes>` (see `web-shell.chat-persistent-host`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Renders the matched page inside `<main>`.
- **Config / env:** `dashboard.show_token_analytics` hides `/analytics` from the nav (route still
  reachable by URL).
- **Edge cases / guards:** `/profiles` uses `end={path === "/sessions"}` only for `/sessions`, so
  `/profiles/new` still highlights the PROFILES nav item.
- **Rebuild notes:** Flat path→component map merged with plugin routes at render time. A better
  version would declare per-route metadata (title, icon, capability gate) in one place instead of
  three parallel tables (`BUILTIN_ROUTES_CORE`, `BUILTIN_NAV_REST`, `resolve-page-title.ts`).

### Unknown-route fallback  `id: web-shell.unknown-route`
- **Surface:** Web dashboard
- **Where:** Any URL that matches no built-in or plugin route.
- **What it does:** Silently redirects to `/sessions` — but only once plugin manifests have loaded, so
  a plugin route deep-link is not bounced before its manifest arrives.
- **How it works:** `App.tsx:130-136 UnknownRouteFallback`: while `pluginsLoading` is true it renders
  `null` ("a spinner here would just flash"); afterwards it renders
  `<Navigate to="/sessions" replace/>`. Wired as `<Route path="*" .../>` at `App.tsx:781-786`.
  Verified live: navigating to `/definitely-not-a-route` lands on `http://127.0.0.1:9119/sessions`.
- **Inputs / options:** `pluginsLoading: boolean`.
- **Outputs / side effects:** `history.replace` to `/sessions`.
- **Config / env:** n/a.
- **Edge cases / guards:** The plugin-loading window is normally <50 ms, worst case the 2 s safety
  timeout in `usePlugins`.
- **Rebuild notes:** Gate the catch-all on async route registration. A better version would render a
  real 404 with a "go to Sessions" affordance instead of a silent redirect.

### Persistent embedded-chat host  `id: web-shell.chat-persistent-host`
- **Surface:** Web dashboard
- **Where:** The `/chat` tab; invisible (`display:none`) on every other route.
- **What it does:** Keeps `ChatPage` (and therefore the PTY child, its WebSocket and the xterm
  instance) mounted across tab switches, so leaving Chat and coming back does not kill the session.
- **How it works:** `App.tsx:791-818`. Rendered *outside* `<Routes>`, inside the routed column. It is
  wrapped in a div carrying `data-chat-active="true"|"false"`, class `flex flex-1 flex-col` when
  active and `hidden` when not, plus `aria-hidden={!isChatRoute}`. Mounting is latched: `chatHostMounted`
  starts as `isChatRoute` and is updated through `latchChatActivation(prev, isActive)`
  (`lib/chat-activation.ts:15`, `prev || isActive` — sticky true) so the xterm chunk and the PTY are
  only paid for after the user's first `/chat` visit. Three suppression gates: `embeddedChat` must be
  true (`lib/dashboard-flags.ts`), `chatOverriddenByPlugin` must be false (any manifest with
  `tab.override === "/chat"`, `App.tsx:446-449`), and while `pluginsLoading` is true the host is not
  mounted at all (mounting then yanking it would kill a PTY mid-paint).
- **Inputs / options:** `isActive` prop passed to `ChatPage`.
- **Outputs / side effects:** A live PTY WebSocket that survives navigation.
- **Config / env:** `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` (always injected `true`).
- **Edge cases / guards:** On `/chat` while plugins load, `RouteFallback label="Loading chat…"` is
  shown; on other routes nothing is rendered.
- **Rebuild notes:** Keep the terminal host outside the router and toggle visibility with CSS; latch
  first activation. Handed off to shard `web-a` for what happens inside the terminal.

### Profile-keyed route remount  `id: web-shell.profile-keyed-routes`
- **Surface:** Web dashboard
- **Where:** Invisible; triggered by the sidebar profile switcher.
- **What it does:** Remounts the whole routed page tree when the managed profile changes, so a page
  opened under profile A refetches under profile B instead of showing stale A data while writing to B.
- **How it works:** `App.tsx:842-845 ProfileKeyedRoutes` renders
  `<div key={profile || "__own__"} className="contents">{children}</div>`. Changing the React `key`
  discards all page state. The persistent chat host is deliberately outside this wrapper and handles
  its own remount (keyed on the scoped profile inside `ChatPage`).
- **Inputs / options:** `profile` from `useProfileScope()`.
- **Outputs / side effects:** Every page's `useEffect(..., [])` data load re-runs.
- **Config / env:** n/a.
- **Edge cases / guards:** `className="contents"` keeps the extra div out of the layout box model.
- **Rebuild notes:** Key the outlet by scope. A better version would push scope into a data layer with
  per-scope cache keys instead of nuking component state.

### App layout frame  `id: web-shell.layout-frame`
- **Surface:** Web dashboard
- **Where:** The whole viewport.
- **What it does:** Full-height, non-scrolling app chrome with a sticky sidebar column and a scrolling
  content column; carries the active theme's layout variant as a data attribute.
- **How it works:** `App.tsx:514-517` root div:
  `data-layout-variant={theme.layoutVariant ?? "standard"}` and classes
  `flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base text-text-primary antialiased`.
  Below it: `<SelectionSwitcher/>` (Nous DS), a fixed `pointer-events-none inset-0 z-0` div hosting
  `<PluginSlot name="backdrop"/>`, the mobile header, the mobile backdrop button, a single
  `h-14 shrink-0 lg:hidden` spacer that provides the mobile header clearance for the banner stack,
  `<PluginSlot name="header-banner"/>`, `<ProfileScopeBanner/>`, `<MemoryPressureBanner/>`, then the
  flex row containing `<aside id="app-sidebar">` and `<PageHeaderProvider>`. The content column
  (`App.tsx:755-763`) is `relative z-2 flex min-w-0 min-h-0 flex-1 flex-col px-3 sm:px-6` with
  `pb-0 pt-1 sm:pt-2 lg:pt-4` on `/chat` and `pt-2 sm:pt-4 lg:pt-6` elsewhere. A final
  `<PluginSlot name="overlay"/>` sits above everything (`App.tsx:826`).
  `index.css:93-142` pins `html`/`body`/`#root` to `100dvh` with `overflow:hidden`, and below 768 px
  relaxes them to `min-height:100dvh; height:auto; overflow-y:auto`.
- **Inputs / options:** Theme `layoutVariant` ∈ `standard` | `cockpit` | `tiled`.
- **Outputs / side effects:** `document.documentElement.dataset.layoutVariant` is also set by the
  theme provider (`themes/context.tsx:282`) plus `--theme-layout-variant`.
- **Config / env:** Theme YAML `layoutVariant`.
- **Edge cases / guards:** `min-h-0` everywhere is what allows the inner `overflow-y-auto` to work in
  a flex column; mobile switches to document scrolling.
- **Rebuild notes:** One non-scrolling app frame; only `<main>` scrolls. A better version would honour
  `cockpit`/`tiled` in the shell itself (today only the `sidebar` slot and theme CSS react to it).

### Build pipeline and chunking (`vite.config.ts`)  `id: web-shell.build-config`
- **Surface:** Web dashboard (build-time)
- **Where:** `cd web && npm run build`; output lands in `hermes_cli/web_dist`.
- **What it does:** Builds the SPA with React Compiler, Tailwind v4, and manual vendor chunk groups;
  in dev it proxies `/api` + `/dashboard-plugins` to a running dashboard and scrapes its session token.
- **How it works:** `web/vite.config.ts:1-163`.
  - Plugins: `react()`, `babel({presets:[compilerPreset()]})` (React Compiler with a narrowed code
    filter `/\/>|<\/|from\s*['"][^'"]*react/` so babel does not parse every TS module),
    `tailwindcss()`, `hermesDevToken()`.
  - `hermesDevToken()` (`vite.config.ts:29-69`, `apply:"serve"`): on each dev page load it fetches
    `HERMES_DASHBOARD_URL` (default `http://127.0.0.1:9119`), scrapes
    `window.__HERMES_SESSION_TOKEN__ = "…"` and `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__ = true|false`
    out of the served HTML and re-injects them into the dev HTML. Warns
    `[hermes] Could not find session token in <BACKEND> — is \`hermes dashboard\` running? /api calls will 401.`
    or `[hermes] Dashboard at <BACKEND> unreachable — start it with \`hermes dashboard\` or set HERMES_DASHBOARD_URL. (<err>)`.
  - Aliases: `@` → `web/src`, `@hermes/shared` → `apps/shared/src`.
  - `dedupe`: `react`, `react-dom`, `@react-three/fiber`, `@observablehq/plot`, `three`, `leva`, `gsap`.
  - Build: `outDir: "../hermes_cli/web_dist"`, `emptyOutDir: true`, `chunkSizeWarningLimit: 600`.
  - Rolldown code-splitting groups (`minSize: 20000`), in order: `react-vendor`
    (`react|react-dom|scheduler|react-router`), `xterm` (`@xterm`), `three` (`three|@react-three`),
    `plot` (`@observablehq/plot`), `motion` (`motion|framer-motion`), `ui` (`@nous-research/ui`),
    `vendor` (everything else in `node_modules`).
  - Dev server proxy: `/api` → backend with `ws: true`; `/dashboard-plugins` → backend.
- **Inputs / options:** npm scripts (`web/package.json:6-16`): `dev`, `build` (`tsc -b && vite build`),
  `lint`, `lint:fix`, `fix`, `preview`, `typecheck`, `test` (`vitest run`),
  `check` (`typecheck && test && lint`). Env: `HERMES_DASHBOARD_URL`.
- **Outputs / side effects:** `hermes_cli/web_dist/{index.html,assets/*}`.
- **Config / env:** `HERMES_DASHBOARD_URL`; `HERMES_WEB_DIST` overrides the served dist at runtime.
- **Edge cases / guards:** `emptyOutDir` wipes the dist — a partially built dist makes `_serve_index`
  return the JSON 404 `{"error":"Frontend not built. Run: cd web && npm run build"}`.
- **Rebuild notes:** Any bundler works; the load-bearing pieces are the vendor split (so the shell
  paint does not pull xterm/three) and the dev token bridge.
- **Dependencies (verbatim, `web/package.json:17-57`):** runtime — `@hermes/shared` (`file:../apps/shared`),
  `@nous-research/ui@0.18.2`, `@observablehq/plot@0.6.17`, `@react-three/fiber@9.6.1`,
  `@tailwindcss/vite@4.3.3`, `@xterm/addon-fit@0.11.0`, `@xterm/addon-unicode11@0.9.0`,
  `@xterm/addon-web-links@0.12.0`, `@xterm/addon-webgl@0.19.0`, `@xterm/xterm@6.0.0`,
  `class-variance-authority@0.7.1`, `clsx@2.1.1`, `gsap@3.15.0`, `leva@0.10.1`,
  `lucide-react@0.577.0`, `motion@12.42.2`, `qrcode@1.5.4`, `react@19.2.7`, `react-dom@19.2.7`,
  `react-router@8.3.0`, `tailwind-merge@3.6.0`, `tailwindcss@4.3.3`, `unicode-animations@1.0.3`;
  dev — `@babel/core@8.0.1`, `@rolldown/plugin-babel@0.2.3`, `@types/babel__core@7.20.5`,
  `@types/node@22.20.1`, `@types/qrcode@1.5.6`, `@types/react@19.2.17`, `@types/react-dom@19.2.3`,
  `@vitejs/plugin-react@6.0.3`, `babel-plugin-react-compiler@1.0.0`,
  `eslint-plugin-react-refresh@0.5.3`, `three@0.180.0`, `typescript@6.0.3`, `vite@8.2.0`,
  `vitest@4.1.10`.

### Global stylesheet and design tokens (`index.css`)  `id: web-shell.index-css`
- **Surface:** Web dashboard
- **Where:** Applies to every pixel of the dashboard.
- **What it does:** Imports Tailwind v4 and the Nous design system, registers the bundled JetBrains
  Mono terminal font, declares the default (Hermes Teal / LENS_0) CSS variables, maps shadcn-style
  utility tokens onto the Nous palette, and defines the shell's keyframes and utility classes.
- **How it works:** `web/src/index.css:1-255`.
  - Imports, in required order: `tailwindcss`, `@nous-research/ui/styles/fonts.css` (must precede
    globals or the DS `--font-*` variables resolve to unloaded families),
    `@nous-research/ui/styles/globals.css`; `@source '../node_modules/@nous-research/ui/dist'` keeps
    DS utility classes from being purged.
  - Three `@font-face` rules for `JetBrains Mono` (400 normal, 700 normal, 400 italic) served from
    `/fonts-terminal/JetBrainsMono-{Regular,Bold,Italic}.woff2`, `font-display: swap`, Apache-2.0.
  - `:root` defaults (`index.css:50-89`): `--foreground: color-mix(in srgb, #ffffff 0%, transparent)`,
    `--foreground-base: #ffffff`, `--foreground-alpha: 0`, `--midground: color-mix(in srgb, #ffe6cb 100%, transparent)`,
    `--midground-base: #ffe6cb`, `--midground-alpha: 1`, `--background: color-mix(in srgb, #041c1c 100%, transparent)`,
    `--background-base: #041c1c`, `--background-alpha: 1`; typography `--theme-font-sans`
    (`system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`),
    `--theme-font-mono` (`ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace`),
    `--theme-font-display: var(--theme-font-sans)`, `--theme-base-size: 15px`,
    `--theme-line-height: 1.55`, `--theme-letter-spacing: 0`; layout `--radius: 0.5rem`,
    `--theme-radius: 0.5rem`, `--theme-spacing-mul: 1`, `--theme-density: comfortable`;
    series accents `--series-input-token: #ffe6cb`, `--series-output-token: #34d399`.
  - `html` binds font-family/size/line-height/letter-spacing to those vars and pins `100dvh` with
    `overflow:hidden`; `body` and `#root` do the same; `@media (max-width: 768px)` relaxes all three
    to document scrolling.
  - `code, kbd, pre, samp, .font-mono, .font-mono-ui` use `var(--theme-font-mono)`;
    `small { font-size: 1.0625rem }`, `code { font-size: 0.875rem }`.
  - `@theme inline` #1: `--spacing: calc(0.25rem * var(--theme-spacing-mul, 1))` (density scaling),
    `--font-sans`, `--font-mono`.
  - `@theme inline` #2 (shadcn-compat, `index.css:154-187`): `--color-foreground: var(--midground)`,
    `--color-card: color-mix(in srgb, var(--midground-base) 4%, var(--background-base))`,
    `--color-card-foreground`, `--color-primary`, `--color-primary-foreground`,
    `--color-secondary` (6%), `--color-secondary-foreground`, `--color-muted` (8%),
    `--color-muted-foreground: var(--color-text-secondary)`, `--color-accent` (10%),
    `--color-accent-foreground`, `--color-destructive: #fb2c36`, `--color-destructive-foreground: #ffffff`,
    `--color-success: #4ade80`, `--color-warning: #ffbd38`, `--color-border` (15% alpha),
    `--color-input` (15%), `--color-ring: var(--midground)`, `--color-popover` (4%),
    `--color-popover-foreground`, and the radius ladder `--radius-sm/md/lg/xl` derived from
    `--theme-radius`.
  - Keyframes: `sidebar-tooltip-in` (opacity 0→1 with a 4 px slide), `toast-in`/`toast-out`
    (16 px X slide), `fade-in`, `dialog-in` (4 px lift + `scale(0.98)`→`scale(1)`).
  - Utilities: `.scrollbar-none` (hides scrollbars incl. `::-webkit-scrollbar`), `.font-mono-ui`,
    `.grain` + `.grain::after` (a 2 px `repeating-conic-gradient` noise at `opacity: 0.12`).
  - `html[dir="rtl"] { direction: rtl }` — the only RTL rule needed because Tailwind v4 logical
    utilities flip themselves.
- **Inputs / options:** n/a (the theme provider overwrites the `:root` vars as inline styles).
- **Outputs / side effects:** Global cascade.
- **Config / env:** n/a.
- **Edge cases / guards:** The import order comment is load-bearing (fonts before globals).
- **Rebuild notes:** Express the palette as three layers (background/midground/foreground) with alpha,
  derive every semantic token by `color-mix`, and let one provider rewrite the variables.

---

## 2. Sidebar, navigation and header chrome

### Sidebar container (`#app-sidebar`)  `id: web-shell.sidebar`
- **Surface:** Web dashboard
- **Where:** Left rail, full viewport height. Accessible name is the i18n string
  `Navigation` (`i18n: app.navigation`), applied as `aria-label` on both the `<aside>` and the inner
  `<nav>`.
- **What it does:** Hosts, top to bottom: the brand block, the profile switcher, the scrolling nav
  list (core items + a "Plugins" group), the System block (status strip, gateway dot, Restart
  Gateway, Update Hermes), the theme + language picker row, the auth widget, and the footer
  (version + Nous Research link).
- **How it works:** `App.tsx:578-752`. Classes:
  `fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-64 min-h-0 flex-col font-sans border-r border-current/20 bg-background-base`
  with a 200 ms `transition-[transform]` easing `cubic-bezier(0.23,1,0.32,1)`; off-canvas by default
  on mobile (`-translate-x-full`, `translate-x-0` when open); from `lg` it becomes
  `lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden` with a 300 ms
  `transition-[width]`, and `lg:w-14` when collapsed. Inline styles read theme component vars:
  `background: var(--component-sidebar-background)`, `clipPath: var(--component-sidebar-clip-path)`,
  `borderImage: var(--component-sidebar-border-image)`.
- **Inputs / options:** `mobileOpen`, `collapsed` state.
- **Outputs / side effects:** none.
- **Config / env:** theme `componentStyles.sidebar.*`.
- **Edge cases / guards:** `lg` breakpoint is 1024 px, matched by `useBelowBreakpoint(1024)` in JS so
  CSS and JS agree.
- **Rebuild notes:** One `<aside>` with a width transition for desktop collapse and a transform
  transition for the mobile drawer.

### Brand block "HERMES / AGENT"  `id: web-shell.brand-block`
- **Surface:** Web dashboard
- **Where:** Sidebar top-left, above the nav. Rendered verbatim as two lines, uppercase:
  `Hermes` then `<br/>` then `Agent` (CSS `uppercase` makes it read `HERMES` / `AGENT`).
- **What it does:** Product wordmark; not a link.
- **How it works:** `App.tsx:613-618` — `<Typography className="font-bold text-[1.125rem] leading-[0.95] tracking-[0.0525rem] text-midground uppercase">`.
  It sits inside a flex row that also renders `<PluginSlot name="header-left"/>` *before* it
  (`App.tsx:612`). The whole group is hidden when the desktop sidebar is collapsed (`lg:hidden`).
  Header height is `h-14` with `border-b border-current/20`.
- **Inputs / options:** n/a. The mobile header uses the i18n string instead:
  `Hermes Agent` (`i18n: app.brand`); a short form `HA` (`i18n: app.brandShort`) exists in the
  catalog but is not rendered by the web shell.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Hidden in the collapsed desktop rail; always visible in the mobile drawer.
- **Rebuild notes:** Two-line uppercase wordmark, 1.125 rem, tight leading.

### Core navigation items  `id: web-shell.nav-core-items`
- **Surface:** Web dashboard
- **Where:** Sidebar `<nav>` → `<ul>`. Labels render uppercase (CSS `uppercase`), so on screen they
  read exactly: `CHAT`, `SESSIONS`, `FILES`, `MODELS`, `LOGS`, `CRON`, `SKILLS`, `PLUGINS`, `MCP`,
  `CHANNELS`, `WEBHOOKS`, `PAIRING`, `PROFILES`, `CONFIG`, `KEYS`, `SYSTEM`, `DOCUMENTATION`
  (verified live on `/sessions`). `ANALYTICS` appears in the list only when token analytics are on.
- **What it does:** Client-side navigation to each built-in page.
- **How it works:** `CHAT_NAV_ITEM` (`App.tsx:138-143`) plus `BUILTIN_NAV_REST` (`App.tsx:186-224`).
  Each item is `{path, label, labelKey?, icon}`; when `labelKey` is present the visible text comes
  from `t.app.nav[labelKey]`, otherwise the hard-coded English `label` is used. Full table in nav
  order:
  | # | path | i18n key | English label | lucide icon | source line |
  |---|---|---|---|---|---|
  | 1 | `/chat` | `app.nav.chat` | Chat | `Terminal` | App.tsx:138 |
  | 2 | `/sessions` | `app.nav.sessions` | Sessions | `MessageSquare` | App.tsx:187 |
  | 3 | `/files` | — (literal) | Files | `FolderOpen` | App.tsx:193 |
  | 4 | `/analytics` | `app.nav.analytics` | Analytics | `BarChart3` | App.tsx:194 |
  | 5 | `/models` | `app.nav.models` | Models | `Cpu` | App.tsx:199 |
  | 6 | `/logs` | `app.nav.logs` | Logs | `FileText` | App.tsx:204 |
  | 7 | `/cron` | `app.nav.cron` | Cron | `Clock` | App.tsx:205 |
  | 8 | `/skills` | `app.nav.skills` | Skills | `Package` | App.tsx:206 |
  | 9 | `/plugins` | `app.nav.plugins` | Plugins | `Puzzle` | App.tsx:207 |
  | 10 | `/mcp` | — (literal) | MCP | `Plug` | App.tsx:208 |
  | 11 | `/channels` | — (literal) | Channels | `Radio` | App.tsx:209 |
  | 12 | `/webhooks` | — (literal) | Webhooks | `Webhook` | App.tsx:210 |
  | 13 | `/pairing` | — (literal) | Pairing | `ShieldCheck` | App.tsx:211 |
  | 14 | `/profiles` | `app.nav.profiles` | Profiles | `Users` | App.tsx:212 |
  | 15 | `/config` | `app.nav.config` | Config | `Settings` | App.tsx:213 |
  | 16 | `/env` | `app.nav.keys` | Keys | `KeyRound` | App.tsx:214 |
  | 17 | `/system` | — (literal) | System | `Wrench` | App.tsx:215 |
  | 18 | `/docs` | `app.nav.documentation` | Documentation | `BookOpen` | App.tsx:216 |
  Note the nav order deliberately differs from `BUILTIN_ROUTES_CORE`: MCP/Channels/Webhooks/Pairing
  come before Profiles in the sidebar.
- **Inputs / options:** Click / Enter navigates; every link is a real `<a href>` so middle-click and
  ctrl-click open a new tab.
- **Outputs / side effects:** URL change; on mobile the drawer closes (`onClick={closeMobile}`).
- **Config / env:** `dashboard.show_token_analytics` (item 4).
- **Edge cases / guards:** `/sessions` uses `end` matching so it is not highlighted for
  `/sessions/...`; every other item uses prefix matching.
- **Rebuild notes:** A flat array of `{path,label,labelKey,icon}` rendered as `NavLink`s. A better
  version would let each page own its nav metadata so the three parallel tables cannot drift.

### Nav item anatomy (active marker, hover wash, collapsed label fade)  `id: web-shell.nav-item-anatomy`
- **Surface:** Web dashboard
- **Where:** Every sidebar row.
- **What it does:** Renders icon + label with an active left-edge hairline, a subtle hover overlay and
  a fade-out of the label text when the rail collapses.
- **How it works:** `App.tsx:847-931 SidebarNavLink`. `<NavLink>` classes:
  `group/nav relative flex items-center gap-3 px-5 py-2.5 font-sans text-display uppercase text-sm tracking-[0.12em] whitespace-nowrap transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground`,
  colour `text-midground` when active else `text-text-secondary hover:text-midground`; inline
  `clipPath: var(--component-tab-clip-path)`. Children: `<Icon className="h-3.5 w-3.5 shrink-0"/>`;
  the label `<span>` with `truncate transition-opacity duration-300` and `lg:opacity-0` when
  collapsed; an `aria-hidden` hover wash
  `absolute inset-y-0.5 left-1.5 right-1.5 bg-midground opacity-0 … group-hover/nav:opacity-5`; and,
  when active, an `aria-hidden` `absolute left-0 top-0 bottom-0 w-px bg-midground` rule.
  When collapsed, `aria-label` is set to the nav label and hover/focus opens a tooltip.
- **Inputs / options:** mouse enter/leave and focus/blur (only wired while collapsed).
- **Outputs / side effects:** none.
- **Config / env:** theme `componentStyles.tab.clipPath`.
- **Edge cases / guards:** The label is faded, not removed, so the width transition stays smooth.
- **Rebuild notes:** Opacity-fade the label rather than unmounting it; keep the icon fixed-width.

### Collapsed-rail tooltip  `id: web-shell.sidebar-tooltip`
- **Surface:** Web dashboard
- **Where:** Floating chip to the right of the collapsed sidebar, on hover/focus of any nav item,
  system-action button, the gateway dot, or the theme/language icons.
- **What it does:** Shows the item's label while the rail is icon-only.
- **How it works:** `App.tsx:1295-1333 SidebarTooltip`, portalled to `document.body`. Positioned
  `fixed`, `top: rect.top + rect.height/2`, `left: <sidebar right edge> + 8`,
  `transform: translateY(-50%)`, `z-[100]`, `pointer-events-none`. Style
  `px-2 py-1 bg-background-base border border-current/20 shadow-lg font-sans text-display text-xs tracking-[0.1em] text-midground uppercase`.
  A shared `tooltipWarmRef` (a `useRef(0)` created once in `App`, `App.tsx:392`) records the last
  tooltip time; if the previous tooltip closed <300 ms ago the entrance animation is skipped
  (`opacity: 1`, `animation: "none"`) so sweeping the mouse down the rail does not re-animate on every
  row; otherwise `animation: sidebar-tooltip-in 120ms ease-out`.
- **Inputs / options:** `anchor` element, `label`, `warmRef`.
- **Outputs / side effects:** A portalled `<span>` on `document.body`.
- **Config / env:** n/a.
- **Edge cases / guards:** Never rendered when the rail is expanded; not focusable (pointer-events
  none).
- **Rebuild notes:** Portal + measured anchor rect + a shared "recently shown" timestamp to suppress
  repeat animations.

### Sidebar collapse toggle  `id: web-shell.sidebar-collapse`
- **Surface:** Web dashboard
- **Where:** Sidebar header, right side, desktop only (`hidden lg:flex`). `aria-label` is
  `Collapse` (`i18n: common.collapse`) when expanded and `Expand` (`i18n: common.expand`) when
  collapsed — both confirmed on the live DOM.
- **What it does:** Shrinks the sidebar from `w-64` (16 rem) to `lg:w-14` (3.5 rem), hiding all text
  and the profile switcher, auth widget and footer; nav labels fade out and tooltips take over.
- **How it works:** `App.tsx:380-395` + `App.tsx:630-645`. State seeded from
  `localStorage["hermes-sidebar-collapsed"] === "true"` inside a lazy `useState` initialiser wrapped
  in try/catch; `toggleCollapsed` flips it and writes `String(next)` back, swallowing storage errors
  ("localStorage may be unavailable in private browsing"). Icons: `PanelLeftOpen` when collapsed,
  `PanelLeftClose` when expanded, both `h-4 w-4`. `isDesktopCollapsed = collapsed && !isMobile`
  (`App.tsx:397`) so the drawer on mobile is never rendered collapsed.
- **Inputs / options:** Click (mouse/keyboard). No dedicated keyboard shortcut.
- **Outputs / side effects:** `localStorage` key `hermes-sidebar-collapsed` = `"true"` / `"false"`.
- **Config / env:** n/a (per-browser only; not synced to the server).
- **Edge cases / guards:** Live check confirms the collapsed rail still exposes all nav labels to the
  accessibility tree (via `aria-label`), and hides `HERMES/AGENT`, the profile switcher, the status
  strip text, the version badge and the `Nous Research` link.
- **Rebuild notes:** Persist per-browser, gate on the same breakpoint the CSS uses.

### Plugin nav group ("Plugins" heading → KANBAN, ACHIEVEMENTS)  `id: web-shell.nav-plugin-group`
- **Surface:** Web dashboard
- **Where:** Below the core nav list, separated by a hairline. Section heading renders as
  `Plugins` (`i18n: app.pluginNavSection`, element id `hermes-sidebar-plugin-nav-heading`). On the
  stock install the group contains `KANBAN` (`/kanban`) and `ACHIEVEMENTS` (`/achievements`).
- **What it does:** Separates plugin-contributed tabs from the built-in nav so a plugin can never be
  mistaken for a core page.
- **How it works:** `App.tsx:666-697`. `partitionSidebarNav` (`App.tsx:292-305`) merges built-ins +
  manifests through `buildNavItems`, then splits by "is this path a built-in path". The group is a
  `role="group"` div with `aria-labelledby` pointing at the heading span; the heading is hidden in the
  collapsed rail (`isDesktopCollapsed && "lg:hidden"`). Rows use the same `SidebarNavLink` component,
  so they get the same active marker and tooltips. The group is not rendered at all when no plugin
  tabs exist.
- **Inputs / options:** Manifest `tab.position` (`"end"` default, `"after:<segment>"`,
  `"before:<segment>"`) still orders the item inside the group.
- **Outputs / side effects:** Navigation to the plugin route.
- **Config / env:** `dashboard.hidden_plugins` (server-side) removes a plugin from the manifest list
  entirely.
- **Edge cases / guards:** Manifests with `tab.override` or `tab.hidden` never produce a nav item
  (`App.tsx:263-264`).
- **Rebuild notes:** Merge-then-partition keeps position hints working while still visually grouping
  third-party tabs.

### Analytics nav gating  `id: web-shell.nav-analytics-gate`
- **Surface:** Web dashboard / Config
- **Where:** The `ANALYTICS` sidebar item is absent on a stock install (verified live: the nav shows
  CHAT…DOCUMENTATION with no ANALYTICS row).
- **What it does:** Hides the token/cost analytics nav entry unless the operator opts in, because the
  numbers are a local lower-bound estimate rather than billing truth.
- **How it works:** `App.tsx:416-426` — on mount, `api.getConfig()` reads
  `cfg.dashboard.show_token_analytics` and the item is filtered out of `builtinNav` unless the value
  is exactly `true` (`App.tsx:459-466`); a failed fetch also yields `false`. The `/analytics` route
  itself remains registered and reachable by URL, where `AnalyticsPage` renders its own explanation
  card (owned by shard `web-a`).
- **Inputs / options:** n/a (no UI toggle in the shell; set the config key).
- **Outputs / side effects:** Nav list length changes.
- **Config / env:** `dashboard.show_token_analytics` (default `false`,
  `hermes_cli/config_defaults.py:1696`).
- **Edge cases / guards:** The gate is client-side only — the endpoint is not access-controlled by it.
- **Rebuild notes:** Feature-flag the nav entry, not the route, so deep links still explain themselves.

### Mobile top bar  `id: web-shell.mobile-header`
- **Surface:** Web dashboard
- **Where:** Fixed top bar, shown only below `lg` (1024 px). Contains a hamburger button and the text
  `Hermes Agent` (`i18n: app.brand`).
- **What it does:** Gives the drawer an opener and shows the product name when the sidebar is
  off-canvas.
- **How it works:** `App.tsx:527-555`. `<header className="lg:hidden fixed top-0 left-0 right-0 z-40 min-h-14 flex items-center gap-2 px-4 py-2 border-b border-current/20 bg-background-base">`
  with inline `background: var(--component-header-background)`,
  `borderImage: var(--component-header-border-image)`,
  `clipPath: var(--component-header-clip-path)`. The button is a ghost icon `Button` with
  `aria-label` `Open navigation` (`i18n: app.openNavigation`),
  `aria-expanded={mobileOpen}`, `aria-controls="app-sidebar"`, and a lucide `Menu` icon. Directly
  below the header, an `aria-hidden` `h-14 shrink-0 lg:hidden` spacer supplies the single clearance
  offset for the banner stack (comment at `App.tsx:569-573` records that stacking per-banner offsets
  was the earlier bug, NS-656 review P3).
- **Inputs / options:** Tap/click the hamburger.
- **Outputs / side effects:** `mobileOpen = true`.
- **Config / env:** theme `componentStyles.header.*`.
- **Edge cases / guards:** Hidden from `lg` up.
- **Rebuild notes:** One fixed bar + one spacer; never let each banner add its own offset.

### Mobile navigation drawer and backdrop  `id: web-shell.mobile-drawer`
- **Surface:** Web dashboard
- **Where:** The sidebar slides in from the left below 1024 px; a full-screen black scrim covers the
  page behind it. The scrim's `aria-label` is `Close navigation` (`i18n: app.closeNavigation`), as is
  the `X` button in the drawer header.
- **What it does:** Presents the full sidebar on small screens.
- **What it does not do:** There is no swipe gesture and no focus trap.
- **How it works:** `App.tsx:557-568`, `App.tsx:489-511`.
  - Scrim: a ghost `Button` with classes `lg:hidden fixed inset-0 z-40 p-0 block bg-black/70`;
    clicking it calls `closeMobile`.
  - Close button inside the drawer header: ghost icon button, lucide `X`, `lg:hidden`.
  - Escape: a `keydown` listener on `document` closes the drawer while open (`App.tsx:489-502`).
  - Scroll lock: while open, `document.body.style.overflow = "hidden"`, restored on close.
  - Breakpoint auto-close: a `matchMedia("(min-width: 1024px)")` `change` listener closes the drawer
    when the viewport grows past `lg` (`App.tsx:503-511`).
  - Every nav link and the system-action buttons call `closeMobile` on activation.
- **Inputs / options:** Hamburger, scrim click, `X` button, `Escape`, viewport resize, any nav click.
- **Outputs / side effects:** Body scroll lock while open.
- **Config / env:** n/a.
- **Edge cases / guards:** Previous `body.style.overflow` is captured and restored rather than reset
  to `""`.
- **Rebuild notes:** Transform-based drawer + scrim + Escape + scroll lock. A better version would add
  a focus trap and `inert` on the background, which this one lacks.

### Profile switcher (sidebar)  `id: web-shell.profile-switcher`
- **Surface:** Web dashboard
- **Where:** Directly under the brand block, above the nav. A `Users` icon plus a `Select` with
  element id `hermes-profile-switcher`. Its container `title` is
  `Managing profile` (`i18n: app.managingProfile`). The first option reads
  `this dashboard ({name})` (`i18n: app.currentProfileOption`, `{name}` replaced by the dashboard's
  own profile, defaulting to `default`); the remaining options are the other profile names verbatim.
- **What it does:** Chooses which profile every management page (Config, Keys, Skills, MCP, Models,
  Pairing, Channels…) and every new chat reads and writes.
- **How it works:** `components/ProfileSwitcher.tsx:18-81`. Reads
  `{profile, currentProfile, profiles, setProfile}` from `useProfileScope()`. Renders `null` when
  `profiles.length < 2`, so a single-profile install never sees it. `isOther = !!profile && profile !== currentProfile`;
  when true, the `Users` icon turns `text-amber-300` and the select button gets
  `border-amber-500/50 text-amber-300`. In the collapsed rail the `<Select>` is hidden
  (`lg:hidden`) and a `sr-only` span exposes the managed profile name. Options exclude
  `currentProfile` (it is the `""` option's label).
- **Inputs / options:** Select an option → `setProfile(name)`.
- **Outputs / side effects:** `setManagementProfile()` in the API module, the `?profile=` URL param
  (replace, not push), and a remount of every page (see `web-shell.profile-keyed-routes`).
- **Config / env:** n/a.
- **Edge cases / guards:** `profiles` comes from `GET /api/profiles`; failures leave the list empty
  and the switcher hidden.
- **Rebuild notes:** State-first scope with the URL as a projection — see the provider below.

### Profile scope provider (`?profile=` synchronisation)  `id: web-shell.profile-provider`
- **Surface:** Web dashboard
- **Where:** Invisible; drives the switcher, the amber banner, and the API client's query injection.
- **What it does:** Holds the management-profile scope as React state, mirrors it into the API module
  and into the URL, and adopts the machine's sticky active profile on first load.
- **How it works:** `contexts/ProfileProvider.tsx:36-137`.
  - Initial value: `searchParams.get("profile") ?? ""` (deep link / refresh / unified-launch
    preselect).
  - `setManagementProfile(profile)` is called during render (not in an effect) so fetches fired by
    child effects in the same commit already see the scope (`ProfileProvider.tsx:50`).
  - A `?profile=` arriving via in-app navigation wins over state (`ProfileProvider.tsx:55-62`).
  - After every navigation, an effect re-asserts `?profile=` onto the new location with
    `{replace:true}` because sidebar links are bare paths (`ProfileProvider.tsx:66-79`).
  - On mount it runs `Promise.all([api.getProfiles(), api.getActiveProfile()])`; sets
    `currentProfile = info.current || "default"`; if there was no `?profile=` deep link and the sticky
    `active` differs from `current`, it adopts `active` so Chat and the management pages agree with
    what the Profiles page calls "active".
  - Context value: `{profile, currentProfile, profiles, setProfile}`
    (`contexts/profile-context.ts:3-19`), read through `useProfileScope()`.
- **Inputs / options:** URL `?profile=<name>`; the switcher.
- **Outputs / side effects:** `?profile=` in the address bar; `?profile=` appended by `fetchJSON` to
  the scoped endpoint families.
- **Config / env:** Server-side sticky active profile file (`hermes profile use`).
- **Edge cases / guards:** `""` means "the dashboard process's own profile" and removes the param.
- **Rebuild notes:** Keep state authoritative and treat the URL as a projection; the reverse (URL as
  truth) silently resets scope on every bare nav link — the exact bug the comment at
  `ProfileProvider.tsx:20-27` documents.

### Managing-profile banner  `id: web-shell.profile-scope-banner`
- **Surface:** Web dashboard
- **Where:** Full-width amber strip directly under the header/banner stack. Text verbatim:
  `Managing profile “{name}” — config, keys, skills, MCPs, model, and new chats apply to that profile.`
  (`i18n: app.managingProfileBanner`, `{name}` substituted).
- **What it does:** Warns that management writes are landing in another profile.
- **How it works:** `components/ProfileScopeBanner.tsx:10-27`. Renders `null` unless
  `profile && profile !== currentProfile`. Markup:
  `<div className="flex items-center gap-2 border-b border-amber-500/40 bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300">`
  with a `Users` icon (`h-3.5 w-3.5 shrink-0`) and the substituted string. A hard-coded English
  fallback is inlined for locales that lack the key.
- **Inputs / options:** none (not dismissible).
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Substitution is a plain `.replace("{name}", profile)`.
- **Rebuild notes:** Persistent, non-dismissible scope warning; do not make it dismissible — the whole
  point is that it stays while writes are redirected.

### Memory / disk pressure banner  `id: web-shell.memory-pressure-banner`
- **Surface:** Web dashboard
- **Where:** Full-width alert strip under the header stack, `role="alert"`,
  `data-testid="memory-pressure-banner"`. Red when critical, amber when elevated. Dismiss button
  `aria-label` is `Dismiss` (`i18n: app.dismiss`) with a lucide `X`.
- **What it does:** Surfaces five distinct resource-trouble conditions that previously only appeared
  in server logs — a hosted agent could be OOM-killed hourly or fill its disk while the dashboard
  looked healthy.
- **How it works:** `components/MemoryPressureBanner.tsx:71-186`, fed by `status.memory` and
  `status.disk` from the 10 s `/api/status` poll. Triggers, evaluated worst-first
  (`MemoryPressureBanner.tsx:115-120`):
  1. `disk_critical` — `status.disk.pressure === "critical"`. Message
     `Your agent's disk is almost full. New messages, memories, and settings may fail to save.`
     (`i18n: app.diskCriticalBanner`) with ` (<N> MB free)` appended when `disk.free_mb` is present
     (`Math.round`).
  2. `critical` — `status.memory.pressure === "critical"`. Message
     `Your agent is almost out of memory and may restart. Consider closing idle sessions or upgrading its memory.`
     (`i18n: app.memoryCriticalBanner`).
  3. `oom_restart` — `status.memory.last_boot_suspected_oom`. Message
     `Your agent restarted unexpectedly, most likely because it ran out of memory. Long sessions and many concurrent tasks increase memory use.`
     (`i18n: app.memoryOomRestartBanner`).
  4. `disk_elevated` — `disk.pressure === "elevated"`. Message
     `Your agent's disk is filling up. Consider clearing old sessions or expanding its storage.`
     (`i18n: app.diskElevatedBanner`) + the same free-space suffix.
  5. `elevated` — `memory.pressure === "elevated"`. Message
     `Your agent is running low on memory.` (`i18n: app.memoryElevatedBanner`).
  Only the worst *undismissed* trigger renders, so dismissing one reveals the next rather than
  silencing everything. Dismissal state is a JSON string array in
  `sessionStorage["memoryBannerDismissed"]`; every entry is keyed `"<trigger>:<memory.boot_id>"`
  (falling back to `"<trigger>:unknown"`), so a gateway restart invalidates all prior dismissals.
  A render-time state adjustment clears a domain's live dismissals once that domain's pressure is
  confirmed back to `"ok"` (`"unknown"` is treated as absence of evidence, not recovery), and memory
  and disk recover independently. Colours: critical → `border-red-500/40 bg-red-500/10 text-red-300`;
  otherwise `border-amber-500/40 bg-amber-500/10 text-amber-300`. Icon: lucide `AlertTriangle`.
- **Inputs / options:** Dismiss button per trigger.
- **Outputs / side effects:** `sessionStorage` write.
- **Config / env:** n/a (driven by `/api/status`).
- **Edge cases / guards:** A pre-incident-key build stored a bare string; `JSON.parse` throws and the
  catch resets to `[]`. `sessionStorage` access is wrapped in try/catch.
- **Rebuild notes:** Rank triggers, cascade dismissal, key dismissals by the reporting boot id, and
  clear only on *confirmed* recovery. There is a dedicated 438-line test file
  (`components/MemoryPressureBanner.test.tsx`).

### System block heading  `id: web-shell.system-block`
- **Surface:** Web dashboard
- **Where:** Sidebar, below the nav list. Heading renders as `System` (`i18n: app.system`), hidden in
  the collapsed rail.
- **What it does:** Groups the live status readout and the two privileged system actions.
- **How it works:** `App.tsx:1034-1081 SidebarSystemActions` renders a `shrink-0 flex flex-col
  border-t border-current/10 py-1` block containing the heading span
  (`px-5 pt-0.5 pb-0.5 font-sans text-display text-xs tracking-[0.12em] text-text-tertiary`),
  `<SidebarStatusStrip/>` (hidden when collapsed), `<GatewayDot/>` (shown only when collapsed), and
  a `<ul>` of `SystemActionButton`s.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Group status + actions so a collapsed rail can swap the text readout for a dot.

### Sidebar status strip (Gateway Status / Active Sessions)  `id: web-shell.status-strip`
- **Surface:** Web dashboard
- **Where:** Sidebar System block. Renders two lines verbatim, e.g.
  `Gateway Status: Off` and `Active Sessions: 0`. The whole strip is a link to `/sessions` whose
  `title` is `Status overview` (`i18n: app.statusOverview`).
- **What it does:** Live gateway state and active-session count, one click from the Sessions page.
- **How it works:** `components/SidebarStatusStrip.tsx:7-49`. Labels come from
  `app.gatewayStatusLabel` (`Gateway Status:`) and `app.activeSessionsLabel` (`Active Sessions:`).
  The value + colour come from `gatewayLine(status, t)` (`SidebarStatusStrip.tsx:51-68`), a map from
  `status.gateway_state`:
  | `gateway_state` | label (i18n) | tone class |
  |---|---|---|
  | `running` | `Running` (`app.gatewayStrip.running`) | `text-success` |
  | `starting` | `Starting` (`app.gatewayStrip.starting`) | `text-warning` |
  | `startup_failed` | `Start failed` (`app.gatewayStrip.failed`) | `text-destructive` |
  | `stopped` | `Stopped` (`app.gatewayStrip.stopped`) | `text-muted-foreground` |
  Fallback when `gateway_state` is absent: `status.gateway_running ? Running/text-success :`
  `Off` (`app.gatewayStrip.off`) `/text-muted-foreground`. While `status === null` a skeleton renders:
  `<div className="h-2 w-[80%] max-w-full animate-pulse rounded-sm bg-midground/10"/>` inside an
  `aria-hidden` wrapper. Session count is rendered `tabular-nums`.
- **Inputs / options:** Click → `/sessions`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Unknown `gateway_state` values fall through to the boolean fallback.
- **Rebuild notes:** One state→(label,tone) map shared by the strip and the collapsed dot.

### Status poll (`useSidebarStatus`)  `id: web-shell.sidebar-status-poll`
- **Surface:** Web dashboard
- **Where:** Invisible; feeds the status strip, gateway dot, memory banner, the Update-Hermes gate and
  the version badge.
- **What it does:** Polls `GET /api/status` every 10 seconds.
- **How it works:** `hooks/useSidebarStatus.ts:5-27`. `POLL_MS = 10_000`; loads immediately on mount
  then on an interval; errors are swallowed (`.catch(() => {})`) so a transient failure leaves the
  last-known status on screen. The comment notes the Status page uses its own faster interval to
  avoid duplicate load.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One `GET /api/status` per 10 s per open tab.
- **Config / env:** `/api/status` is in `PUBLIC_API_PATHS` (no auth needed) — see
  `web-shell.public-api-paths`.
- **Edge cases / guards:** Returns `null` until the first response.
- **Rebuild notes:** Single shared poll for all shell chrome; do not let each widget poll separately.

### Collapsed-rail gateway dot  `id: web-shell.gateway-dot`
- **Surface:** Web dashboard
- **Where:** Collapsed sidebar only; a 6 px dot at `pl-[1.625rem]`. `role="status"` with an
  `aria-label` of `Gateway <state>` (e.g. `Gateway Off`, verified live).
- **What it does:** Replaces the two-line status strip with a single colour-coded dot when the rail is
  narrow; hovering/focusing it shows the same label as a tooltip.
- **How it works:** `App.tsx:1237-1293 GatewayDot`. Colour map from the strip's tone class to a
  background class: `text-success`→`bg-success`, `text-warning`→`bg-warning`,
  `text-destructive`→`bg-destructive`, `text-muted-foreground`→`bg-muted-foreground`; when
  `status` is still `null` the dot is `bg-midground/20` and the label is just
  `Gateway` (`i18n: status.gateway`). Container is `hidden lg:flex` with a 300 ms opacity transition;
  when expanded it becomes `lg:opacity-0 lg:h-0 lg:py-0 lg:overflow-hidden` and `tabIndex={-1}`.
- **Inputs / options:** hover / focus.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** `tabIndex` flips to `0` only while collapsed so the expanded rail has no
  phantom tab stop.
- **Rebuild notes:** Same data source as the strip; only the presentation changes.

### "Restart Gateway" button + confirmation  `id: web-shell.restart-gateway`
- **Surface:** Web dashboard
- **Where:** Sidebar → System block. Button label verbatim `Restart Gateway`
  (`i18n: status.restartGateway`), lucide `RotateCw` icon. While running the label becomes
  `Restarting gateway…` (`i18n: status.restartingGateway`) and the icon is replaced by a spinner.
- **What it does:** Restarts the Hermes gateway process after an explicit confirmation, then navigates
  to `/sessions` where the action log streams.
- **How it works:** `App.tsx:986-1003` builds the action list; `handleClick("restart")` opens a
  confirm dialog instead of firing (`App.tsx:1007-1011`). The dialog is the Nous DS `ConfirmDialog`
  (`App.tsx:1083-1096`) with:
  - title `Restart gateway?` (`i18n: status.restartGatewayConfirmTitle`; falls back to
    `` `${t.status.restartGateway}?` `` — live DOM shows `RESTART GATEWAY?` because the DS uppercases
    dialog titles),
  - description `This restarts the Hermes gateway process. Connected channels and active sessions will reconnect afterward.`
    (`i18n: status.restartGatewayConfirmMessage`, with the identical English string inlined as a
    fallback),
  - confirm label `Restart Gateway`, cancel label `Cancel` (`i18n: common.cancel`),
  - `loading` while `pendingAction === "restart"`.
  Confirming calls `runAction("restart")` → `api.restartGateway()` (`POST /api/gateway/restart`),
  then `navigate("/sessions")` and `onNavigate()` (closes the mobile drawer).
- **Inputs / options:** Button click; dialog `Cancel` / `Restart Gateway`; `Escape` cancels.
- **Outputs / side effects:** Gateway process restart; a polled action log named `gateway-restart`.
- **Config / env:** n/a.
- **Edge cases / guards:** Disabled while another system action is in flight
  (`disabled={isBusy && !(pendingAction === item.action || (activeAction === item.action && isRunning))}`).
- **Rebuild notes:** Confirm before any process-level action, then send the user to where progress is
  visible.

### "Update Hermes" button + confirmation  `id: web-shell.update-hermes`
- **Surface:** Web dashboard
- **Where:** Sidebar → System block, immediately below Restart Gateway — but only when
  `status.can_update_hermes === true`. Label verbatim `Update Hermes`
  (`i18n: status.updateHermes`), lucide `Download` icon; while running the label becomes
  `Updating Hermes…` (`i18n: status.updatingHermes`) and the icon pulses (`animate-pulse`) rather than
  spinning (`spin: false`).
- **What it does:** Runs `hermes update` from the dashboard and restarts the gateway when it finishes.
- **How it works:** `App.tsx:995-1002` (conditional push) and the confirm dialog at
  `App.tsx:1098-1111`. Opening the dialog triggers `api.checkHermesUpdate(false)`
  (`App.tsx:950-971`); while that call is in flight the description shows
  `Loading...` (`i18n: common.loading`, verified live) and the confirm button is `loading`. Once the
  check resolves:
  - if `behind > 0`, the description is built inline:
    `` `This will run 'hermes update' (${cmd}) and pull ${n} new commit${n === 1 ? "" : "s"}. The gateway restarts when the update finishes; the current session keeps its prompt cache until then.` ``
  - otherwise it falls back to `i18n: status.updateHermesConfirmMessage` —
    `This runs hermes update and restarts the gateway when it finishes. Active sessions keep their prompt cache until then.`
    (with an inline English fallback that interpolates `update_command`).
  Title: `Update Hermes?` (`i18n: status.updateHermesConfirmTitle`, fallback
  `` `${t.status.updateHermes}?` ``). Confirm label: `Update now`
  (`i18n: status.updateHermesConfirmNow`). Cancel: `Cancel`.
  Confirming calls `runAction("update")` → `api.updateHermes()` then navigates to `/sessions`.
- **Inputs / options:** Button click; `Cancel` / `Update now`; `Escape`.
- **Outputs / side effects:** Spawns the update action (`hermes-update`); gateway restart on success.
- **Config / env:** `status.can_update_hermes` decides whether the button exists at all (Docker and
  externally-managed installs suppress it).
- **Edge cases / guards:** When the endpoint replies `{ok:false, message, update_command}` the
  provider shows a toast with the message plus two spaces and the command, and never polls a
  synthetic failed action (`contexts/SystemActions.tsx:77-91`).
- **Rebuild notes:** Check-then-confirm with the real commit count in the copy; never poll an action
  that was never spawned.

### System-action runner and toasts  `id: web-shell.system-actions-provider`
- **Surface:** Web dashboard
- **Where:** Invisible provider; its toast appears bottom-right (Nous DS `Toast`).
- **What it does:** Owns the state machine for the two privileged actions, polls their status, and
  raises a success/failure toast.
- **How it works:** `contexts/SystemActions.tsx:16-134`.
  - `ACTION_NAMES = {restart: "gateway-restart", update: "hermes-update"}`.
  - `runAction(action)` sets `pendingAction`, clears `actionStatus`, calls
    `api.restartGateway()` or `api.updateHermes()`, then sets `activeAction`; failures raise a toast
    `` `${t.status.actionFailed}: ${detail}` `` (`Action failed: <error>`).
  - While `activeAction` is set, it polls `api.getActionStatus(name)` every 1500 ms; when
    `resp.running` is false it toasts `Finished` (`i18n: status.actionFinished`) on exit code 0, or
    `` `${t.status.actionFailed} (exit ${resp.exit_code ?? "?"})` `` (`Action failed (exit N)`)
    otherwise. Transient fetch errors keep polling.
  - Toasts auto-dismiss after 4000 ms.
  - Exposed state (`contexts/system-actions-context.ts:10-18`): `actionStatus`, `activeAction`,
    `dismissLog`, `isBusy`, `isRunning`, `pendingAction`, `runAction`. `isRunning = activeAction !== null && actionStatus?.running !== false`;
    `isBusy = pendingAction !== null || isRunning`.
  - `useSystemActions()` throws `useSystemActions must be used within a SystemActionsProvider` when
    used outside the provider.
- **Inputs / options:** `runAction("restart" | "update")`, `dismissLog()`.
- **Outputs / side effects:** Network calls; one visible toast at a time.
- **Config / env:** n/a.
- **Edge cases / guards:** `dismissLog` is consumed by the Sessions page's action-log panel (shard
  `web-a`).
- **Rebuild notes:** One provider owning both actions means the sidebar buttons and the Sessions
  action log cannot disagree about what is running.

### System-action button anatomy  `id: web-shell.system-action-button`
- **Surface:** Web dashboard
- **Where:** The Restart / Update rows.
- **What it does:** Renders the action with a spinner-or-icon, busy styling, disabled state, and a
  collapsed-rail tooltip.
- **How it works:** `App.tsx:1107-1193 SystemActionButton`. Classes mirror the nav link
  (`group/action relative flex w-full items-center gap-3 px-5 py-2.5 font-sans text-display text-xs tracking-[0.1em] …`)
  plus `disabled:text-text-disabled disabled:cursor-not-allowed`. `aria-busy` is set while pending or
  running. Icon logic: pending → `<Spinner/>`; running with `spin:true` → `<Spinner/>`; running with
  `spin:false` → the icon with `animate-pulse`; otherwise the plain icon. A busy row also shows the
  same left hairline as an active nav item. When collapsed, `aria-label` is the current display label
  and hover/focus shows the tooltip.
- **Inputs / options:** click; hover/focus while collapsed.
- **Outputs / side effects:** none directly.
- **Config / env:** n/a.
- **Edge cases / guards:** The label swaps to `runningLabel` only while `isRunning` (not while merely
  pending).
- **Rebuild notes:** Distinguish "request in flight" (spinner) from "long action running" (pulse) so
  a multi-minute update does not look hung.

### Theme + language picker row  `id: web-shell.picker-row`
- **Surface:** Web dashboard
- **Where:** Sidebar, between the System block and the auth widget/footer. Contains
  `<PluginSlot name="header-right"/>`, then the theme trigger (live text `HERMES TEAL`) and the
  language trigger (live text `EN`).
- **What it does:** Hosts the two appearance controls and wraps each in a collapsed-rail tooltip.
- **How it works:** `App.tsx:707-741`. The row is `flex shrink-0 items-center gap-2 px-3 py-2
  border-t border-current/20`, `justify-between` when expanded and
  `lg:flex-col lg:items-start lg:gap-3 lg:py-3` when collapsed. Each control is wrapped in
  `SidebarIconWithTooltip` (`App.tsx:1195-1235`) with labels
  `Switch theme` (`i18n: theme.switchTheme`) and `Switch language` (`i18n: language.switchTo`);
  the wrapper also paints a hover wash (`absolute inset-y-0 inset-x-[-0.375rem] bg-midground …
  group-hover/icon:opacity-5 hidden lg:block`) while collapsed. Both pickers receive
  `collapsed={isDesktopCollapsed}` and `dropUp` (so their menus open upward from the bottom of the
  rail).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `dropUp` also switches the pickers to a bottom sheet below 640 px.
- **Rebuild notes:** Anchor bottom-docked menus upward and portal them so the sidebar's
  `overflow-hidden` cannot clip them.

### Auth widget ("Logged in as …")  `id: web-shell.auth-widget`
- **Surface:** Web dashboard
- **Where:** Sidebar, above the footer. Only rendered when the dashboard auth gate is engaged. The row
  has `role="status"` and `aria-label` `` `Logged in as <label>` ``; the second line reads
  `via <provider>`; the trailing button has both `aria-label` and `title` `Log out` with a lucide
  `LogOut` icon.
- **What it does:** Shows who is signed in under the gated (OAuth/password) dashboard and offers a
  logout.
- **How it works:** `components/AuthWidget.tsx:43-159`. Renders `null` immediately when
  `!window.__HERMES_AUTH_REQUIRED__` — the loopback case — so no request is fired and the console
  stays clean. Otherwise it calls `api.getAuthMe()` (`GET /api/auth/me` with
  `allowUnauthorized: true`). A `401:`/`403:` prefix on the thrown error hides the widget; any other
  error renders the literal text `auth status unavailable`. While loading it reserves a row:
  `<div className="h-9 px-5 py-2 text-[0.65rem] text-muted-foreground/40" aria-busy="true">…</div>`.
  The display label prefers `display_name` → `email` → `truncateUserId(user_id)` which cuts at 14
  characters and appends `…` (`AuthWidget.tsx:38-41`); the full `user_id` is the `title` attribute.
  Logout calls `api.logout()` → `POST /auth/logout` then `window.location.assign("/login")`.
- **Inputs / options:** Log-out button.
- **Outputs / side effects:** Session cookie cleared server-side; full-page navigation to `/login`.
- **Config / env:** `window.__HERMES_AUTH_REQUIRED__` (server-injected).
- **Edge cases / guards:** `allowUnauthorized` is load-bearing — without it the expected 401 in
  loopback mode would trip the stale-token reload and loop forever
  (`lib/api.ts:348-362` comment).
- **Rebuild notes:** Gate the probe on a server-injected flag; never let an expected 401 drive a
  reload heuristic.

### Sidebar footer (version badge + Nous Research link)  `id: web-shell.sidebar-footer`
- **Surface:** Web dashboard
- **Where:** Bottom of the sidebar. Left: the version, rendered lowercase and tabular as `v0.21.0`
  (live), or `—` when status has not loaded. Right: a link whose text is `Nous Research`
  (`i18n: app.footer.org`) pointing at `https://nousresearch.com`.
- **What it does:** Shows the installed Hermes version and links to the vendor site.
- **How it works:** `components/SidebarFooter.tsx:6-37`. Version: `` status?.version != null ? `v${status.version}` : "—" ``
  inside a `Typography` with `font-mono-ui text-xs tabular-nums tracking-[0.08em] text-text-tertiary lowercase`.
  Link: `target="_blank" rel="noopener noreferrer"` with
  `font-sans text-display text-xs tracking-[0.12em] text-midground` and a focus ring. The whole footer
  (together with the auth widget) is hidden in the collapsed desktop rail (`App.tsx:743-751`).
- **Inputs / options:** Click the link (opens a new tab).
- **Outputs / side effects:** External navigation.
- **Config / env:** n/a.
- **Edge cases / guards:** `rel="noopener noreferrer"` is present.
- **Rebuild notes:** Always show the running version somewhere persistent — it is the single most
  useful support datum.

### Page header (title + toolbar slots)  `id: web-shell.page-header`
- **Surface:** Web dashboard
- **Where:** The bar at the top of the content column, `role="banner"`, containing the page `<h1>`
  (e.g. `Sessions`, `Kanban`, `Achievements`) and two page-owned slots.
- **What it does:** Gives every page a consistent title row, plus two injection points a page can fill
  (`afterTitle` next to the title, `end` right-aligned) without owning the header markup.
- **How it works:** `contexts/PageHeaderProvider.tsx:8-138`. Context API
  (`contexts/page-header-context.ts:4-8`): `setTitle(string|null)`, `setAfterTitle(ReactNode)`,
  `setEnd(ReactNode)`; consumed through `usePageHeader()` which throws
  `usePageHeader must be used within a PageHeaderProvider` outside the provider. A
  `useLayoutEffect` keyed on `pathname` clears all three slots on navigation so a page's toolbar never
  leaks into the next page. Layout: header is `py-3` and auto-height on mobile (title stacks above the
  toolbar) and `sm:h-14 sm:min-h-[3.5rem] sm:overflow-hidden sm:py-0` from `sm` up; `/chat` forces a
  single row (`flex-row items-center`). `/env` gets a special case: its jump-nav is wide, so
  `afterTitle` becomes a full-width horizontally scrolling strip below the title on small screens
  (`isEnvRoute`, `PageHeaderProvider.tsx:39-41,94-105`) using the `.scrollbar-none` utility. The
  `<h1>` is `font-expanded min-w-0 text-sm font-bold tracking-[0.08em] text-midground` and truncates.
  `<main>` below it is `overflow-hidden` on `/chat` and
  `overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]` elsewhere.
- **Inputs / options:** `setTitle`, `setAfterTitle`, `setEnd` from any page.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Clearing happens in `useLayoutEffect` (not `useEffect`) so the old toolbar
  never paints on the new route.
- **Rebuild notes:** Header slots owned by the shell, filled by the page, cleared on navigation.

### Page-title resolution  `id: web-shell.page-title`
- **Surface:** Web dashboard
- **Where:** The `<h1>` in the page header.
- **What it does:** Derives a human title for any path — i18n nav label, plugin label, hard-coded
  literal, or capitalised path segment.
- **How it works:** `lib/resolve-page-title.ts:30-57`, precedence order:
  1. Normalise (strip one trailing `/`; empty → `/`). `/` returns `t.app.nav.sessions`.
  2. Plugin tabs (`{path,label}` pairs built in `App.tsx:476-485` from non-hidden manifests, using
     `tab.override ?? tab.path`) — exact path match wins, so a plugin overriding a built-in route also
     renames the header.
  3. `BUILTIN` i18n map (`resolve-page-title.ts:3-16`): `/chat`→`chat`, `/sessions`→`sessions`,
     `/analytics`→`analytics`, `/models`→`models`, `/logs`→`logs`, `/cron`→`cron`, `/skills`→`skills`,
     `/plugins`→`plugins`, `/profiles`→`profiles`, `/config`→`config`, `/env`→`keys`,
     `/docs`→`documentation`.
  4. `BUILTIN_LITERAL` map (`resolve-page-title.ts:21-28`): `/files`→`Files`, `/mcp`→`MCP`,
     `/channels`→`Channels`, `/webhooks`→`Webhooks`, `/pairing`→`Pairing`, `/system`→`System` — these
     exist precisely because the naive capitalise fallback would produce `Mcp`.
  5. Fallback: capitalise the first path segment (`/profiles/new` → `Profiles/new`… in practice
     `/profiles` matches at step 3).
  6. Last resort: `t.app.webUi` (`Web UI`).
  A page may override everything via `setTitle` (e.g. Chat shows the live session title).
  Unit-tested in `lib/resolve-page-title.test.ts`.
- **Inputs / options:** `pathname`, `t`, `pluginTabs`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Initialism handling is the reason for the literal map.
- **Rebuild notes:** Keep one resolver, ordered plugin → i18n → literal → derived.

---

## 3. Theming, fonts and language

### Theme picker  `id: web-shell.theme-switcher`
- **Surface:** Web dashboard
- **Where:** Sidebar picker row. Trigger shows a lucide `Palette` icon plus the active theme label —
  live text `HERMES TEAL` (uppercased by the DS `text-display` class; the underlying label is
  `Hermes Teal`). `aria-label` `Switch theme`, `title` `` `Switch theme: Hermes Teal` ``,
  `aria-expanded`, `aria-haspopup="listbox"`.
- **What it does:** Switches the whole dashboard palette/typography/layout, and (in the same menu)
  overrides the UI font independently of the theme.
- **How it works:** `components/ThemeSwitcher.tsx:27-158`. The menu is a `role="listbox"` with
  `aria-label` `Theme` (`i18n: theme.title`). Two presentations:
  - Desktop / wide (`dropUp`): portalled to `document.body`, `fixed z-[100]`, positioned
    `bottom: window.innerHeight - triggerRect.top + 4`, `left: triggerRect.left`,
    `min-w-[240px] max-h-[70dvh] overflow-y-auto border border-current/20 bg-background-base/95 shadow-[0_12px_32px_-8px_rgba(0,0,0,0.6)]`,
    with a sticky-looking header row containing the text `Theme`.
  - Narrow (<640 px, `useBelowBreakpoint(640)` + `dropUp`): a Nous DS `BottomSheet` titled `Theme`
    with `backdropDismissLabel` = `Close` (`i18n: common.close`).
  Each theme row is a DS `ListItem` with `role="option"`, `aria-selected`, a 3-cell swatch, the label
  in `text-display text-xs`, the description in `text-xs text-text-tertiary`, and a lucide `Check`
  that is `opacity-100` for the active theme and `opacity-0` otherwise. The swatch
  (`ThemeSwitcher.tsx:315-331`) is `h-4 w-9` with three equal cells filled from
  `theme.swatchColors ?? [palette.background.hex, palette.midground.hex, palette.warmGlow]`; a user
  theme without a definition gets a dashed `PlaceholderSwatch`.
  Dismissal: `Escape` (document keydown) and outside `mousedown` (skipped in bottom-sheet mode, which
  has its own backdrop).
- **Inputs / options:** Click a theme row → `setTheme(name)` and close. Live menu content (verified):
  `HERMES TEAL` / `Classic dark teal — the canonical Hermes look`;
  `HERMES TEAL (LARGE)` / `Hermes Teal with bigger fonts and roomier spacing`;
  `NOUS BLUE` / `Light mode — vivid Nous-blue accents on cream canvas`;
  `MIDNIGHT` / `Deep blue-violet with cool accents`;
  `EMBER` / `Warm crimson and bronze — forge vibes`;
  `MONO` / `Clean grayscale — minimal and focused`;
  `CYBERPUNK` / `Neon green on black — matrix terminal`;
  `ROSÉ` / `Soft pink and warm ivory — easy on the eyes`.
- **Outputs / side effects:** CSS variables rewritten on `:root`; `localStorage["hermes-dashboard-theme"]`;
  `PUT /api/dashboard/theme` persists to `config.yaml` `dashboard.theme`.
- **Config / env:** `dashboard.theme` (default `"default"`).
- **Edge cases / guards:** `setTheme` only accepts a name the server listed or a built-in; anything
  else falls back to `"default"` (`themes/context.tsx:543-559`).
- **Rebuild notes:** Preview the palette in the row itself; persist both locally (flash-free reload)
  and server-side (cross-browser).

### Font override section  `id: web-shell.font-picker`
- **Surface:** Web dashboard
- **Where:** Inside the theme menu, below the theme list, behind a hairline. Section header is a
  lucide `Type` icon plus the text `Font` (`i18n: theme.fontTitle`). Category sub-headers render
  uppercase: `SANS`, `SERIF`, `MONO` (`i18n: theme.fontSans` / `theme.fontSerif` / `theme.fontMono`).
- **What it does:** Applies any font from a curated catalog on top of the active theme, or clears the
  override.
- **How it works:** `components/ThemeSwitcher.tsx:226-313 FontSection`. First row is
  `Theme default` (`i18n: theme.fontDefault`) with sub-label
  `Use the active theme's font` (`i18n: theme.fontDefaultHint`) and the sentinel id `theme`
  (`THEME_DEFAULT_FONT_ID`, `themes/fonts.ts:46`). Each font row is a `ListItem role="option"` whose
  label is rendered **in its own font** (`style={{fontFamily: f.stack}}`) so the row is a live preview.
  Applying a font (`themes/context.tsx:324-341 applyFontOverride`) injects its Google-Fonts
  stylesheet (once, tracked in a module-level `Set`), then sets
  `--theme-font-override-sans`, `--theme-font-sans` and `--theme-font-display` on `:root`.
  `--theme-font-mono` deliberately stays owned by the theme so picking a body font does not mangle
  code blocks and the terminal. The override is re-asserted at the tail of every `applyTheme`
  (`themes/context.tsx:402-404`) via a module-scope `_ACTIVE_FONT_OVERRIDE`.
- **Inputs / options:** The 15 rows, live-verified in order — `Theme default`; **SANS**:
  `System Sans`, `Inter`, `IBM Plex Sans`, `Work Sans`, `Atkinson Hyperlegible`, `DM Sans`;
  **SERIF**: `System Serif`, `Spectral`, `Fraunces`, `Source Serif 4`; **MONO**: `System Mono`,
  `JetBrains Mono`, `IBM Plex Mono`, `Space Mono`.
- **Outputs / side effects:** `localStorage["hermes-dashboard-font"]`; `PUT /api/dashboard/font`
  persists `dashboard.font`; a `<link rel="stylesheet" data-hermes-theme-font="true">` in `<head>`
  for webfont choices.
- **Config / env:** `dashboard.font` (allow-listed server-side by `_FONT_CHOICES`).
- **Edge cases / guards:** The catalog exists specifically so an arbitrary user-supplied `fontUrl` is
  never injected as a stylesheet — a self-XSS/SSRF footgun the comment at `themes/fonts.ts:10-19`
  calls out. Unknown ids coerce to `theme` on both client and server.
- **Rebuild notes:** Vetted catalog, id-only persistence, preview each row in its own face, and keep
  the mono stack under theme control.

### Font catalog  `id: web-shell.font-catalog`
- **Surface:** Web dashboard / Config
- **Where:** Data behind the font picker; mirrored server-side as an allow-list.
- **What it does:** Defines the 14 selectable fonts (plus the `theme` sentinel) with their CSS stacks
  and webfont URLs.
- **How it works:** `themes/fonts.ts:56-144`. Shared fallbacks:
  `SYSTEM_SANS = system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`;
  `SYSTEM_MONO = ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace`;
  `SYSTEM_SERIF = Georgia, Cambria, "Times New Roman", Times, serif`.
  `GF(family)` builds `https://fonts.googleapis.com/css2?family=<family>&display=swap`.
  | id | label | category | stack | fontUrl family spec |
  |---|---|---|---|---|
  | `system-sans` | System Sans | sans | `SYSTEM_SANS` | — |
  | `system-serif` | System Serif | serif | `SYSTEM_SERIF` | — |
  | `system-mono` | System Mono | mono | `SYSTEM_MONO` | — |
  | `inter` | Inter | sans | `"Inter", SYSTEM_SANS` | `Inter:wght@400;500;600;700` |
  | `ibm-plex-sans` | IBM Plex Sans | sans | `"IBM Plex Sans", SYSTEM_SANS` | `IBM+Plex+Sans:wght@400;500;600;700` |
  | `work-sans` | Work Sans | sans | `"Work Sans", SYSTEM_SANS` | `Work+Sans:wght@400;500;600;700` |
  | `atkinson-hyperlegible` | Atkinson Hyperlegible | sans | `"Atkinson Hyperlegible", SYSTEM_SANS` | `Atkinson+Hyperlegible:wght@400;700` |
  | `dm-sans` | DM Sans | sans | `"DM Sans", SYSTEM_SANS` | `DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700` |
  | `spectral` | Spectral | serif | `"Spectral", SYSTEM_SERIF` | `Spectral:wght@400;500;600;700` |
  | `fraunces` | Fraunces | serif | `"Fraunces", SYSTEM_SERIF` | `Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600` |
  | `source-serif` | Source Serif 4 | serif | `"Source Serif 4", SYSTEM_SERIF` | `Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600;8..60,700` |
  | `jetbrains-mono` | JetBrains Mono | mono | `"JetBrains Mono", SYSTEM_MONO` | `JetBrains+Mono:wght@400;500;700` |
  | `ibm-plex-mono` | IBM Plex Mono | mono | `"IBM Plex Mono", SYSTEM_MONO` | `IBM+Plex+Mono:wght@400;500;700` |
  | `space-mono` | Space Mono | mono | `"Space Mono", SYSTEM_MONO` | `Space+Mono:wght@400;700` |
  Helpers: `getFontChoice(id)` returns `undefined` for the sentinel and unknown ids;
  `isOverrideFont(id)` is `getFontChoice(id) !== undefined`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** Server allow-list `_FONT_CHOICES` (`hermes_cli/web_server.py:18348-18355`) holds
  exactly the same 14 ids; `_FONT_DEFAULT_ID = "theme"`.
- **Edge cases / guards:** The two lists must stay in sync (comment at `themes/fonts.ts:18-19`).
- **Rebuild notes:** Ship the stacks client-side and only the id allow-list server-side.

### Theme engine (`ThemeProvider` / `applyTheme`)  `id: web-shell.theme-engine`
- **Surface:** Web dashboard
- **Where:** Invisible; it is what makes a theme change repaint the whole app.
- **What it does:** Resolves a theme name to a full definition and writes ~30 CSS custom properties
  (plus optional asset/component/custom-CSS layers) as inline styles on `document.documentElement`.
- **How it works:** `themes/context.tsx`.
  - **Storage keys:** `hermes-dashboard-theme` (theme name), `hermes-dashboard-font` (font id).
  - **Aliases:** `THEME_NAME_ALIASES = {"lens-5i": "nous-blue"}` (`context.tsx:49-52`); a stale stored
    name is migrated and written back, and if the *server* still holds the stale name the client
    pushes the migrated value back with `api.setTheme` so it converges.
  - **`layerVars(name, layer)`** emits `--<name>` = `color-mix(in srgb, <hex> <alpha*100>%, transparent)`,
    `--<name>-base` = hex, `--<name>-alpha` = alpha, for `background`, `midground`, `foreground`.
  - **`typographyVars`** emits `--theme-font-sans`, `--theme-font-mono`, `--theme-font-display`
    (falls back to `fontSans`), `--theme-base-size`, `--theme-line-height`, `--theme-letter-spacing`.
  - **`layoutVars`** emits `--radius`, `--theme-radius`, `--theme-spacing-mul`
    (`compact: 0.85`, `comfortable: 1`, `spacious: 1.2`), `--theme-density`.
  - **`overrideVars`** maps the 19 `colorOverrides` keys to `--color-*` variables
    (`card`, `cardForeground`, `popover`, `popoverForeground`, `primary`, `primaryForeground`,
    `secondary`, `secondaryForeground`, `muted`, `mutedForeground`, `accent`, `accentForeground`,
    `destructive`, `destructiveForeground`, `success`, `warning`, `border`, `input`, `ring`).
  - **`seriesColorVars`** maps `inputTokenAccent`→`--series-input-token`,
    `outputTokenAccent`→`--series-output-token`.
  - **`assetVars`** emits `--theme-asset-<key>` and `--theme-asset-<key>-raw` for the six named keys
    `bg`, `hero`, `logo`, `crest`, `sidebar`, `header`, plus `--theme-asset-custom-<key>` (+ `-raw`)
    for `assets.custom` keys matching `^[a-zA-Z0-9_-]+$`. Values already looking like
    `url(`, `linear-gradient`, `radial-gradient`, `conic-gradient` or exactly `none` pass through;
    anything else is wrapped as `url("…")` with `"` escaped.
  - **`componentStyleVars`** emits `--component-<bucket>-<kebab-prop>` for the nine buckets
    `card`, `header`, `footer`, `sidebar`, `tab`, `progress`, `badge`, `backdrop`, `page`
    (property names filtered to `^[a-zA-Z0-9_-]+$`, camelCase → kebab).
  - **Cleanup:** before applying, `applyTheme` removes every `--color-*` override var, every series
    var, and every dynamic key recorded from the previous theme (`_PREV_DYNAMIC_VAR_KEYS`), so
    switching from a decorated theme to a plain one cannot leave stale clip-paths or hero URLs.
  - **`customCSS`** is injected into a single reused `<style id="hermes-theme-custom-css"
    data-hermes-theme-css="true">` element, removed when the next theme has none.
  - **`layoutVariant`** sets `documentElement.dataset.layoutVariant` and `--theme-layout-variant`
    (default `standard`).
  - **Terminal colours:** `--theme-terminal-background` (default `#000000`) and
    `--theme-terminal-foreground` (default `#f0e6d2`), also read directly by `ChatPage`.
  - **Font stylesheet injection** (`context.tsx:290-307`) de-dupes by URL both via an in-module `Set`
    and by querying for an existing `link[rel=stylesheet][href=…]` with `CSS.escape`.
  - **Server sync:** on mount it calls `api.getThemes()` (merging user YAML definitions into
    `userThemeDefs` and adopting `resp.active`) and `api.getFontPref()`.
  - **Context value** (`context.tsx:604-615`): `{theme, themeName, availableThemes, setTheme, fontId,
    fontChoices, setFont}` via `useTheme()`.
- **Inputs / options:** `setTheme(name)`, `setFont(id)`.
- **Outputs / side effects:** Inline styles on `<html>`; one `<style>` tag; zero-to-many `<link>`
  font tags; two `localStorage` keys; two `PUT` requests.
- **Config / env:** `dashboard.theme`, `dashboard.font`.
- **Edge cases / guards:** All `document`/`window` access is guarded for SSR (`typeof document === "undefined"`).
- **Rebuild notes:** Clear-then-set is essential; without it themes leak into each other. A better
  version would batch the writes into a single `cssText` assignment and expose the variable contract
  as a typed token list.

### Built-in themes  `id: web-shell.builtin-themes`
- **Surface:** Web dashboard / Config
- **Where:** The theme picker list; `dashboard.theme` accepts these names.
- **What it does:** Eight shipped looks, each changing palette, typography, corner radius and (for one)
  density — "so switching themes produces visible changes beyond just color".
- **How it works:** `web/src/themes/presets.ts:41-240`, exported as `BUILTIN_THEMES` keyed
  `default`, `default-large`, `nous-blue`, `midnight`, `ember`, `mono`, `cyberpunk`, `rose`. The
  backend mirrors the name/label/description triples in `_BUILTIN_DASHBOARD_THEMES`
  (`hermes_cli/web_server.py:18042-18051`) — the full definitions live only in the bundle.
  Shared defaults: `DEFAULT_TYPOGRAPHY` = system sans/mono, `baseSize 15px`, `lineHeight 1.55`,
  `letterSpacing 0`; `DEFAULT_LAYOUT` = `radius 0.5rem`, `density comfortable`.
  1. **`default` — "Hermes Teal"** / `Classic dark teal — the canonical Hermes look`.
     background `#041c1c` α1, midground `#ffe6cb` α1, foreground `#ffffff` α0,
     warmGlow `rgba(255, 189, 56, 0.35)`, noiseOpacity 1; default typography/layout;
     `terminalBackground: "#000000"`.
  2. **`default-large` — "Hermes Teal (Large)"** / `Hermes Teal with bigger fonts and roomier spacing`.
     Same palette; `baseSize 18px`, `lineHeight 1.65`, `density spacious`.
  3. **`nous-blue` — "Nous Blue"** / `Light mode — vivid Nous-blue accents on cream canvas`.
     background `#E8F2FD`, midground `#0053FD`, foreground `#170d02` α0,
     warmGlow `rgba(0, 83, 253, 0.12)`, noiseOpacity 0; `terminalBackground "#f5f8fc"`,
     `terminalForeground "#170d02"`; `seriesColors {inputTokenAccent:"#001934", outputTokenAccent:"#0053fd"}`;
     `swatchColors ["#170d02", "#0053FD", "#E8F2FD"]`.
  4. **`midnight` — "Midnight"** / `Deep blue-violet with cool accents`.
     background `#0a0a1f`, midground `#d4c8ff`, warmGlow `rgba(167, 139, 250, 0.32)`,
     noiseOpacity 0.8; fonts `"Inter"` + `"JetBrains Mono"` via
     `https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap`,
     `letterSpacing -0.005em`; `radius 0.75rem`.
  5. **`ember` — "Ember"** / `Warm crimson and bronze — forge vibes`.
     background `#1a0a06`, midground `#ffd8b0`, warmGlow `rgba(249, 115, 22, 0.38)`, noiseOpacity 1;
     fonts `"Spectral", Georgia, "Times New Roman", serif` + `"IBM Plex Mono"` via
     `…family=Spectral:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;700&display=swap`;
     `radius 0.25rem`; `colorOverrides {destructive:"#c92d0f", warning:"#f97316"}`.
  6. **`mono` — "Mono"** / `Clean grayscale — minimal and focused`.
     background `#0e0e0e`, midground `#eaeaea`, warmGlow `rgba(255, 255, 255, 0.1)`,
     noiseOpacity 0.6; fonts IBM Plex Sans/Mono via
     `…family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap`;
     `radius 0`.
  7. **`cyberpunk` — "Cyberpunk"** / `Neon green on black — matrix terminal`.
     background `#040608`, midground `#9bffcf`, warmGlow `rgba(0, 255, 136, 0.22)`,
     noiseOpacity 1.2; both sans and mono are `"Share Tech Mono", "JetBrains Mono", SYSTEM_MONO` via
     `…family=Share+Tech+Mono&family=JetBrains+Mono:wght@400;700&display=swap`; `radius 0`;
     `colorOverrides {success:"#00ff88", warning:"#ffd700", destructive:"#ff0055"}`.
  8. **`rose` — "Rosé"** / `Soft pink and warm ivory — easy on the eyes`.
     background `#1a0f15`, midground `#ffd4e1`, warmGlow `rgba(249, 168, 212, 0.3)`,
     noiseOpacity 0.9; fonts `"Fraunces", Georgia, serif` + `"DM Mono"` via
     `…family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=DM+Mono:wght@400;500&display=swap`;
     `radius 1rem`.
- **Inputs / options:** Pick in the theme menu, or set `dashboard.theme` directly.
- **Outputs / side effects:** As `web-shell.theme-engine`.
- **Config / env:** `dashboard.theme`.
- **Edge cases / guards:** Names must stay in sync with the backend list (comment at
  `presets.ts:10-11`).
- **Rebuild notes:** Make each theme change more than colour; ship a swatch triple per theme.

### User themes from YAML  `id: web-shell.user-themes`
- **Surface:** Config / Web dashboard
- **Where:** Files at `~/.hermes/dashboard-themes/*.yaml` (resolved from the dashboard's *launch*
  home, not a request-scoped profile home). They appear in the theme picker alongside the built-ins.
- **What it does:** Lets an operator ship a complete reskin — palette, fonts, radius/density, hero and
  background assets, per-component clip-paths/border-images, raw CSS, and a layout variant — without
  touching the bundle.
- **How it works:** `hermes_cli/web_server.py:18268-18291 _discover_user_themes` globs `*.yaml` in
  sorted order and runs each through `_normalise_theme_definition`
  (`web_server.py:18124-18256`), which:
  - requires a non-empty string `name` (else the theme is dropped);
  - accepts `palette.<layer>` or the shorthand `colors.<layer>`, each either a bare hex string or
    `{hex, alpha}` — `_parse_theme_layer` clamps alpha to `[0,1]` and defaults background `#041c1c` α1,
    midground `#ffe6cb` α1, foreground `#ffffff` α0; `warmGlow` defaults
    `rgba(255, 189, 56, 0.35)`, `noiseOpacity` defaults 1.0;
  - merges `typography.{fontSans,fontMono,fontDisplay,fontUrl,baseSize,lineHeight,letterSpacing}`
    over `_THEME_DEFAULT_TYPOGRAPHY`;
  - merges `layout.radius` (any non-empty string) and `layout.density`
    (`compact` | `comfortable` | `spacious`);
  - keeps only the 19 valid `colorOverrides` keys with string values;
  - keeps `assets.{bg,hero,logo,crest,sidebar,header}` (non-empty strings) and
    `assets.custom.<alnum/-/_>`;
  - clips `customCSS` to `_THEME_CUSTOM_CSS_MAX` = 32 KiB and does **not** sanitise it (themes are
    user-authored YAML in `~/.hermes`, "same trust level as the config file itself");
  - keeps `componentStyles.<bucket>` for the nine buckets, property names alnum/`-`/`_`, values
    coerced to `str`;
  - validates `layoutVariant` against `{standard, cockpit, tiled}`, defaulting to `standard`.
  Built-ins win on name collision (`seen` set in `get_dashboard_themes`). User themes are shipped
  *with* their full `definition` so the client applies them without a second round-trip.
- **Inputs / options:** the YAML keys listed above.
- **Outputs / side effects:** Extra rows in the picker; the definition is applied client-side.
- **Config / env:** `HERMES_HOME` (process launch home) → `dashboard-themes/`.
- **Edge cases / guards:** A YAML that fails to parse or normalise is skipped silently; a theme with
  no `definition` shows the dashed placeholder swatch.
- **Rebuild notes:** Normalise server-side into exactly the shape the client applies; keep a size cap
  on raw CSS.

### Theme flash mitigation (bootstrap critical CSS)  `id: web-shell.theme-bootstrap-css`
- **Surface:** Web dashboard (server-rendered)
- **Where:** A `<style id="hermes-theme-bootstrap">` block injected into `<head>` before the SPA
  bootstrap script, only when the active theme is a *user* theme.
- **What it does:** Prevents the visible green flash where the first paint uses the bundle's default
  Hermes Teal canvas before `/api/dashboard/themes` resolves.
- **How it works:** `hermes_cli/web_server.py:17741-17808 _render_active_theme_bootstrap_css`. Reads
  `dashboard.theme`; returns `""` for built-ins (the bundle already owns them). For a user theme it
  emits `:root{--background-base:<bg>;--midground-base:<mg>;--theme-font-sans:<font>;--theme-base-size:<size>;}`
  plus `html,body{background-color:var(--background-base);color:var(--midground-base);font-family:var(--theme-font-sans);font-size:var(--theme-base-size);}`.
  The rule references the *variables*, not literals, so a later runtime theme switch (which writes
  inline styles on `documentElement`, outranking this stylesheet) automatically re-resolves. Values
  are escaped with `</` → `<\/`. Any exception is swallowed and logged at debug level.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One extra `<style>` in the served HTML.
- **Config / env:** `dashboard.theme`.
- **Edge cases / guards:** Falls back to `#0a0a0a` / `#e5e5e5` if the YAML palette is malformed.
- **Rebuild notes:** Server-render only the four variables that dominate the first paint, and
  reference them via `var()` so they stay live.

### Theme + font HTTP API  `id: web-shell.theme-api`
- **Surface:** API
- **Where:** `GET /api/dashboard/themes`, `PUT /api/dashboard/theme`, `GET /api/dashboard/font`,
  `PUT /api/dashboard/font`.
- **What it does:** Lists themes/active theme, persists the active theme, and reads/persists the font
  override.
- **How it works:**
  - `GET /api/dashboard/themes` (`web_server.py:18294-18326`) → `{themes: [...], active: "<name>"}`.
    Built-ins carry only `{name,label,description}`; user themes additionally carry `definition`.
    Live response confirmed to list the 8 built-ins with `"active": "default"`. This path is in
    `PUBLIC_API_PATHS` (unauthenticated) so the skin engine works pre-login.
  - `PUT /api/dashboard/theme` body `{name}` (`web_server.py:18328-18340`) → `{ok:true, theme:name}`;
    writes `config.dashboard.theme` under `_CONFIG_MUTATION_LOCK`.
  - `GET /api/dashboard/font` (`web_server.py:18357-18367`) → `{font}` (live: `{"font":"theme"}`);
    coerces unknown values to `theme`.
  - `PUT /api/dashboard/font` body `{font}` (`web_server.py:18370-18389`) → `{ok:true, font}`;
    unknown ids are coerced to `theme` rather than rejected "so a stale client can't wedge the
    picker".
- **Inputs / options:** JSON bodies `{name}` / `{font}`.
- **Outputs / side effects:** `config.yaml` writes.
- **Config / env:** `dashboard.theme`, `dashboard.font`.
- **Edge cases / guards:** Both writes take the global config mutation lock.
- **Rebuild notes:** Coerce rather than 400 on the appearance endpoints.

### Language picker  `id: web-shell.language-switcher`
- **Surface:** Web dashboard
- **Where:** Sidebar picker row, right of the theme trigger. Trigger text is `EN` when the locale is
  English and otherwise the endonym (e.g. `日本語`). `aria-label` and `title` are both
  `Switch language` (`i18n: language.switchTo`); `aria-haspopup="listbox"`, `aria-expanded`.
- **What it does:** Switches the dashboard UI language among 17 locales and persists the choice.
- **How it works:** `components/LanguageSwitcher.tsx:30-173`. The menu is `role="listbox"` with
  `aria-label` `Switch language`. Wide viewports get an anchored dropdown
  (`min-w-[10rem] border border-border bg-popover shadow-md py-1 max-h-80 overflow-y-auto`), portalled
  to `document.body` and positioned `bottom: window.innerHeight - triggerRect.top + 4`,
  `left: triggerRect.left` when `dropUp`; below 640 px with `dropUp` it becomes a DS `BottomSheet`
  titled `Switch language` with `backdropDismissLabel` `Close`. Each option is a `<button role="option"
  aria-selected>` showing the endonym; the selected row is `font-semibold text-foreground` and carries
  a lucide `Check` (`ml-auto h-3 w-3 shrink-0 text-midground`), unselected rows are
  `text-muted-foreground`. Dismissal: `Escape` and outside `pointerdown` (skipped in sheet mode).
  Deliberately **no country flags** — the comment (`LanguageSwitcher.tsx:21-23`, repeated in
  `i18n/context.tsx:98-101`) explains that languages are not countries.
- **Inputs / options:** The 17 rows, live-verified in this exact order: `English`, `简体中文`,
  `繁體中文`, `日本語`, `Deutsch`, `Español`, `Français`, `Türkçe`, `Українська`, `Afrikaans`,
  `한국어`, `Italiano`, `Gaeilge`, `Português`, `Русский`, `Magyar`, `العربية`.
- **Outputs / side effects:** `localStorage["hermes-locale"]`; `<html lang>` and `<html dir>` update.
- **Config / env:** none (browser-local only; not persisted server-side, unlike theme/font).
- **Edge cases / guards:** An unknown stored locale falls back to `en`.
- **Rebuild notes:** Endonyms only; persist locally; set `lang`/`dir` on the document element.

### i18n provider and locale registry  `id: web-shell.i18n-provider`
- **Surface:** Web dashboard
- **Where:** Wraps the entire app; consumed as `const { t, locale, setLocale } = useI18n()`.
- **What it does:** Holds the active locale, exposes the resolved translation object, persists the
  choice, and sets document language/direction.
- **How it works:** `web/src/i18n/context.tsx:69-184`.
  - `TRANSLATIONS` maps the 17 locale codes to their modules: `en`, `zh`, `zh-hant` (module export
    `zhHant`), `ja`, `de`, `es`, `fr`, `tr`, `uk`, `af`, `ko`, `it`, `ga`, `pt`, `ru`, `hu`, `ar`.
  - `LOCALE_META` (exported, `context.tsx:102-120`) pairs each code with its endonym:
    `en → English`, `zh → 简体中文`, `zh-hant → 繁體中文`, `ja → 日本語`, `de → Deutsch`,
    `es → Español`, `fr → Français`, `tr → Türkçe`, `uk → Українська`, `af → Afrikaans`,
    `ko → 한국어`, `it → Italiano`, `ga → Gaeilge`, `pt → Português`, `ru → Русский`,
    `hu → Magyar`, `ar → العربية`.
  - `RTL_LOCALES = new Set(["ar"])`.
  - `STORAGE_KEY = "hermes-locale"`; `getInitialLocale()` reads it inside try/catch, validates against
    the supported list, and falls back to `"en"` (there is **no** `navigator.language` sniffing).
  - An effect sets `document.documentElement.lang = locale` and
    `document.documentElement.dir = RTL_LOCALES.has(locale) ? "rtl" : "ltr"`.
  - The default context value is `{locale:"en", setLocale: noop, t: en}` so a component rendered
    outside the provider still gets English strings instead of crashing.
  - Translations are **statically imported** — all 17 locales are in the main bundle, not lazily
    fetched.
- **Inputs / options:** `setLocale(code)`.
- **Outputs / side effects:** `localStorage`, `<html lang>`, `<html dir>`.
- **Config / env:** n/a.
- **Edge cases / guards:** Storage failures are swallowed ("SSR or privacy mode").
- **Rebuild notes:** Static import keeps switching instant at the cost of bundle size; a better
  version would lazy-load non-active locales and still preload the persisted one.

### Partial-locale merge (`defineLocale`)  `id: web-shell.i18n-define-locale`
- **Surface:** Web dashboard (build-time helper)
- **Where:** Used by `i18n/ar.ts`; the other 15 non-English locales export a full `Translations`
  object literal.
- **What it does:** Lets a locale file supply only the strings it has translated and fall back to
  English for everything else, while still type-checking that no unknown key is introduced.
- **How it works:** `web/src/i18n/define-locale.ts:1-48`. `TranslationOverride<T>` recursively makes
  every object property optional but preserves function and array types verbatim;
  `mergeTranslations(base, overrides)` deep-merges plain objects, treats arrays and functions as
  leaves, and skips `undefined` values. `defineLocale(overrides)` = `mergeTranslations(en, overrides)`.
  Mirrors the desktop app's helper so a new locale (Arabic was the first) can land without hand-porting
  every future English key.
- **Inputs / options:** A partial translations object.
- **Outputs / side effects:** A complete `Translations` value.
- **Config / env:** n/a.
- **Edge cases / guards:** Unknown keys still fail type-check because the override type is derived
  from `Translations`.
- **Rebuild notes:** Deep-merge over the reference locale; keep arrays atomic (the weekday-abbrev
  array must not merge element-wise).

### RTL support  `id: web-shell.i18n-rtl`
- **Surface:** Web dashboard
- **Where:** Only when Arabic (`العربية`) is selected.
- **What it does:** Flips the whole layout to right-to-left.
- **How it works:** The provider sets `document.documentElement.dir = "rtl"`; `index.css:252-254`
  declares `html[dir="rtl"] { direction: rtl; }` and the comment records that Tailwind v4's logical
  utilities (`ms-`/`me-`, `ps-`/`pe-`) and logical properties then flip automatically, so the default
  LTR layout is untouched.
- **Inputs / options:** Select `العربية`.
- **Outputs / side effects:** `<html dir="rtl">`.
- **Config / env:** n/a.
- **Edge cases / guards:** Any component still using physical `ml-`/`pr-` utilities will not flip;
  the RTL support is only as complete as the utilities used.
- **Rebuild notes:** One `dir` attribute + logical properties; audit for physical-direction utilities.

---

## 4. The English i18n catalog (714 keys, 18 namespaces)

The reference locale is `web/src/i18n/en.ts` (878 lines). Flattening its nested object with
dotted paths yields **714 leaf strings** across 18 top-level namespaces. (The pre-collected
`hermes_inv/string_catalogs.json` `web_en` list reports 656 — it misses multi-line template
literals and the one array value `cron.scheduleModes.weekdaysShort`; the 714 figure below was
recomputed by evaluating `en.ts` directly and is authoritative.) Every key below is transcribed
verbatim with its English value so a mechanical checker can diff the UI against this list.

### i18n namespace `common` (45 keys)  `id: web-shell.i18n-ns-common`
- **Surface:** Web dashboard
- **Where:** Cross-cutting labels reused by every page and dialog.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `common` object; read as ``t.common.*`` from `App.tsx`, `components/ChatSessionList.tsx`, `components/ThemeSwitcher.tsx`, `components/DeleteConfirmDialog.tsx`, `components/OAuthProvidersCard.tsx`, `components/OAuthLoginModal.tsx`, `components/LanguageSwitcher.tsx`, `plugins/PluginPage.tsx`, and pages Config/Env/Plugins/Sessions/Profiles/Cron/Logs/Analytics/Skills/Models.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `common.save` = "Save"
  - `common.saving` = "Saving..."
  - `common.cancel` = "Cancel"
  - `common.close` = "Close"
  - `common.confirm` = "Confirm"
  - `common.delete` = "Delete"
  - `common.refresh` = "Refresh"
  - `common.retry` = "Retry"
  - `common.search` = "Search..."
  - `common.loading` = "Loading..."
  - `common.create` = "Create"
  - `common.creating` = "Creating..."
  - `common.set` = "Set"
  - `common.replace` = "Replace"
  - `common.clear` = "Clear"
  - `common.live` = "Live"
  - `common.off` = "Off"
  - `common.enabled` = "enabled"
  - `common.disabled` = "disabled"
  - `common.active` = "active"
  - `common.inactive` = "inactive"
  - `common.unknown` = "unknown"
  - `common.untitled` = "Untitled"
  - `common.none` = "None"
  - `common.form` = "Form"
  - `common.noResults` = "No results"
  - `common.of` = "of"
  - `common.page` = "Page"
  - `common.msgs` = "msgs"
  - `common.tools` = "tools"
  - `common.match` = "match"
  - `common.other` = "Other"
  - `common.configured` = "configured"
  - `common.removed` = "removed"
  - `common.failedToToggle` = "Failed to toggle"
  - `common.failedToRemove` = "Failed to remove"
  - `common.failedToReveal` = "Failed to reveal"
  - `common.collapse` = "Collapse"
  - `common.expand` = "Expand"
  - `common.general` = "General"
  - `common.messaging` = "Messaging"
  - `common.gateway` = "Gateway"
  - `common.gatewayHint` = "Messaging platforms, the API server and webhooks are configured on the Channels page. These are gateway-wide settings (proxy/relay mode and the global allowlist)."
  - `common.pluginLoadFailed` = "Could not load this plugin’s script. Check the Network tab (dashboard-plugins/…) and the server’s plugin path."
  - `common.pluginNotRegistered` = "The plugin’s script did not call register(), or the script errored. Open the browser console for details."
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `app` (43 keys)  `id: web-shell.i18n-ns-app`
- **Surface:** Web dashboard
- **Where:** The shell itself — brand, nav labels, banners, mobile a11y labels.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `app` object; read as ``t.app.*`` from `App.tsx`, `components/ProfileSwitcher.tsx`, `components/SidebarStatusStrip.tsx`, `components/MemoryPressureBanner.tsx`, `components/SidebarFooter.tsx`, `components/ProfileScopeBanner.tsx`, `lib/resolve-page-title.ts`, `pages/EnvPage.tsx`, `pages/DocsPage.tsx`, `pages/ChatPage.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `app.brand` = "Hermes Agent"
  - `app.brandShort` = "HA"
  - `app.closeNavigation` = "Close navigation"
  - `app.closeModelTools` = "Close model and tools"
  - `app.footer.org` = "Nous Research"
  - `app.activeSessionsLabel` = "Active Sessions:"
  - `app.gatewayStatusLabel` = "Gateway Status:"
  - `app.gatewayStrip.failed` = "Start failed"
  - `app.gatewayStrip.off` = "Off"
  - `app.gatewayStrip.running` = "Running"
  - `app.gatewayStrip.starting` = "Starting"
  - `app.gatewayStrip.stopped` = "Stopped"
  - `app.nav.analytics` = "Analytics"
  - `app.nav.chat` = "Chat"
  - `app.nav.config` = "Config"
  - `app.nav.cron` = "Cron"
  - `app.nav.documentation` = "Documentation"
  - `app.nav.keys` = "Keys"
  - `app.nav.logs` = "Logs"
  - `app.nav.models` = "Models"
  - `app.nav.profiles` = "Profiles"
  - `app.nav.plugins` = "Plugins"
  - `app.nav.sessions` = "Sessions"
  - `app.nav.skills` = "Skills"
  - `app.modelToolsSheetSubtitle` = "& tools"
  - `app.modelToolsSheetTitle` = "Model"
  - `app.navigation` = "Navigation"
  - `app.openDocumentation` = "Open documentation in a new tab"
  - `app.openNavigation` = "Open navigation"
  - `app.pluginNavSection` = "Plugins"
  - `app.sessionsActiveCount` = "{count} active"
  - `app.statusOverview` = "Status overview"
  - `app.system` = "System"
  - `app.webUi` = "Web UI"
  - `app.managingProfile` = "Managing profile"
  - `app.currentProfileOption` = "this dashboard ({name})"
  - `app.managingProfileBanner` = "Managing profile “{name}” — config, keys, skills, MCPs, model, and new chats apply to that profile."
  - `app.memoryOomRestartBanner` = "Your agent restarted unexpectedly, most likely because it ran out of memory. Long sessions and many concurrent tasks increase memory use."
  - `app.memoryCriticalBanner` = "Your agent is almost out of memory and may restart. Consider closing idle sessions or upgrading its memory."
  - `app.memoryElevatedBanner` = "Your agent is running low on memory."
  - `app.diskCriticalBanner` = "Your agent's disk is almost full. New messages, memories, and settings may fail to save."
  - `app.diskElevatedBanner` = "Your agent's disk is filling up. Consider clearing old sessions or expanding its storage."
  - `app.dismiss` = "Dismiss"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `status` (36 keys)  `id: web-shell.i18n-ns-status`
- **Surface:** Web dashboard
- **Where:** Gateway/agent status vocabulary and the two system actions.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `status` object; read as ``t.status.*`` from `App.tsx` (sidebar System block), `contexts/SystemActions.tsx`, `components/PlatformsCard.tsx`, `components/OAuthProvidersCard.tsx`, `lib/mcp-dashboard-oauth.ts`, `pages/SystemPage.tsx`, `pages/PluginsPage.tsx`, `pages/SessionsPage.tsx`, `pages/ProfilesPage.tsx`, `pages/CronPage.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `status.actionFailed` = "Action failed"
  - `status.actionFinished` = "Finished"
  - `status.actions` = "Actions"
  - `status.agent` = "Agent"
  - `status.activeSessions` = "Active Sessions"
  - `status.connected` = "Connected"
  - `status.connectedPlatforms` = "Connected Platforms"
  - `status.disabled` = "Disabled"
  - `status.disconnected` = "Disconnected"
  - `status.error` = "Error"
  - `status.failed` = "Failed"
  - `status.gateway` = "Gateway"
  - `status.gatewayFailedToStart` = "Gateway failed to start"
  - `status.lastUpdate` = "Last update"
  - `status.noneRunning` = "None"
  - `status.notRunning` = "Not running"
  - `status.pid` = "PID"
  - `status.platformDisconnected` = "disconnected"
  - `status.platformError` = "error"
  - `status.recentSessions` = "Recent Sessions"
  - `status.restartGateway` = "Restart Gateway"
  - `status.restartGatewayConfirmMessage` = "This restarts the Hermes gateway process. Connected channels and active sessions will reconnect afterward."
  - `status.restartGatewayConfirmTitle` = "Restart gateway?"
  - `status.restartingGateway` = "Restarting gateway…"
  - `status.running` = "Running"
  - `status.runningRemote` = "Running (remote)"
  - `status.startFailed` = "Start failed"
  - `status.starting` = "Starting"
  - `status.startedInBackground` = "Started in background — check logs for progress"
  - `status.stopped` = "Stopped"
  - `status.updateHermes` = "Update Hermes"
  - `status.updateHermesConfirmMessage` = "This runs hermes update and restarts the gateway when it finishes. Active sessions keep their prompt cache until then."
  - `status.updateHermesConfirmNow` = "Update now"
  - `status.updateHermesConfirmTitle` = "Update Hermes?"
  - `status.updatingHermes` = "Updating Hermes…"
  - `status.waitingForOutput` = "Waiting for output…"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `sessions` (42 keys)  `id: web-shell.i18n-ns-sessions`
- **Surface:** Web dashboard
- **Where:** Sessions page + the chat session switcher.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `sessions` object; read as ``t.sessions.*`` from `pages/SessionsPage.tsx` (shard web-a), `components/ChatSessionList.tsx`, `pages/SystemPage.tsx`, `pages/AnalyticsPage.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `sessions.title` = "Sessions"
  - `sessions.history` = "History"
  - `sessions.overview` = "Overview"
  - `sessions.filterChats` = "Chats"
  - `sessions.filterAutomation` = "Automation"
  - `sessions.filterAll` = "All"
  - `sessions.sourceFilter` = "Session source"
  - `sessions.anySource` = "Any source"
  - `sessions.searchPlaceholder` = "Search message content..."
  - `sessions.noSessions` = "No sessions yet"
  - `sessions.noSessionsInFilter` = "No sessions in this filter"
  - `sessions.noMatch` = "No sessions match your search"
  - `sessions.startConversation` = "Start a conversation to see it here"
  - `sessions.noMessages` = "No messages"
  - `sessions.untitledSession` = "Untitled session"
  - `sessions.deleteSession` = "Delete session"
  - `sessions.confirmDeleteTitle` = "Delete session?"
  - `sessions.confirmDeleteMessage` = "This permanently removes the conversation and all of its messages. This cannot be undone."
  - `sessions.sessionDeleted` = "Session deleted"
  - `sessions.failedToDelete` = "Failed to delete session"
  - `sessions.deleteEmpty` = "Delete empty"
  - `sessions.deleteEmptyConfirmTitle` = "Delete empty sessions?"
  - `sessions.deleteEmptyConfirmMessage` = "This permanently removes {count} sessions that have no messages. Active and archived sessions are skipped. This cannot be undone."
  - `sessions.emptySessionsDeleted` = "{count} empty sessions deleted"
  - `sessions.failedToDeleteEmpty` = "Failed to delete empty sessions"
  - `sessions.selectSession` = "Select session"
  - `sessions.selectAllOnPage` = "Select all on this page"
  - `sessions.clearSelection` = "Clear selection"
  - `sessions.selectedCount` = "{count} selected"
  - `sessions.deleteSelected` = "Delete {count}"
  - `sessions.deleteSelectedConfirmTitle` = "Delete {count} sessions?"
  - `sessions.deleteSelectedConfirmMessage` = "This permanently removes {count} selected sessions and all their messages. This cannot be undone."
  - `sessions.selectedSessionsDeleted` = "{count} sessions deleted"
  - `sessions.failedToDeleteSelected` = "Failed to delete selected sessions"
  - `sessions.resumeInChat` = "Resume in Chat"
  - `sessions.newChat` = "New chat"
  - `sessions.previousPage` = "Previous page"
  - `sessions.nextPage` = "Next page"
  - `sessions.roles.user` = "User"
  - `sessions.roles.assistant` = "Assistant"
  - `sessions.roles.system` = "System"
  - `sessions.roles.tool` = "Tool"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `analytics` (23 keys)  `id: web-shell.i18n-ns-analytics`
- **Surface:** Web dashboard
- **Where:** Analytics page tables and chart labels.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `analytics` object; read as ``t.analytics.*`` from `pages/AnalyticsPage.tsx`, `pages/ModelsPage.tsx` (shard web-a).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `analytics.period` = "Period:"
  - `analytics.totalTokens` = "Total Tokens"
  - `analytics.totalSessions` = "Total Sessions"
  - `analytics.apiCalls` = "API Calls"
  - `analytics.dailyTokenUsage` = "Daily Token Usage"
  - `analytics.dailyBreakdown` = "Daily Breakdown"
  - `analytics.perModelBreakdown` = "Per-Model Breakdown"
  - `analytics.topSkills` = "Top Skills"
  - `analytics.skill` = "Skill"
  - `analytics.loads` = "Agent Loaded"
  - `analytics.edits` = "Agent Managed"
  - `analytics.lastUsed` = "Last Used"
  - `analytics.input` = "Input"
  - `analytics.output` = "Output"
  - `analytics.total` = "Total"
  - `analytics.noUsageData` = "No usage data for this period"
  - `analytics.startSession` = "Start a session to see analytics here"
  - `analytics.date` = "Date"
  - `analytics.model` = "Model"
  - `analytics.tokens` = "Tokens"
  - `analytics.perDayAvg` = "/day avg"
  - `analytics.acrossModels` = "across {count} models"
  - `analytics.inOut` = "{input} in / {output} out"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `models` (9 keys)  `id: web-shell.i18n-ns-models`
- **Surface:** Web dashboard
- **Where:** Models page usage summary.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `models` object; read as ``t.models.*`` from `pages/ModelsPage.tsx` (shard web-a).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `models.modelsUsed` = "Models Used"
  - `models.estimatedCost` = "Est. Cost"
  - `models.tokens` = "tokens"
  - `models.sessions` = "sessions"
  - `models.avgPerSession` = "avg/session"
  - `models.apiCalls` = "API calls"
  - `models.toolCalls` = "tool calls"
  - `models.noModelsData` = "No model usage data for this period"
  - `models.startSession` = "Start a session to see model data here"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `logs` (7 keys)  `id: web-shell.i18n-ns-logs`
- **Surface:** Web dashboard
- **Where:** Logs page toolbar.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `logs` object; read as ``t.logs.*`` from `pages/LogsPage.tsx` (shard web-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `logs.title` = "Logs"
  - `logs.autoRefresh` = "Auto-refresh"
  - `logs.file` = "File"
  - `logs.level` = "Level"
  - `logs.component` = "Component"
  - `logs.lines` = "Lines"
  - `logs.noLogLines` = "No log lines found"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `cron` (54 keys)  `id: web-shell.i18n-ns-cron`
- **Surface:** Web dashboard
- **Where:** Cron page, the schedule builder and delivery targets.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `cron` object; read as ``t.cron.*`` from `pages/CronPage.tsx`, `components/ScheduleBuilder.tsx`, `lib/schedule.ts` (shard web-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `cron.confirmDeleteMessage` = "This removes the job from the schedule. This cannot be undone."
  - `cron.confirmDeleteTitle` = "Delete scheduled job?"
  - `cron.newJob` = "New Cron Job"
  - `cron.nameOptional` = "Name (optional)"
  - `cron.namePlaceholder` = "e.g. Daily summary"
  - `cron.prompt` = "Prompt"
  - `cron.promptPlaceholder` = "What should the agent do on each run?"
  - `cron.schedule` = "Schedule (cron expression)"
  - `cron.schedulePlaceholder` = "0 9 * * *"
  - `cron.scheduleMode` = "Schedule"
  - `cron.scheduleModes.interval` = "Every interval"
  - `cron.scheduleModes.daily` = "Daily"
  - `cron.scheduleModes.weekly` = "Weekly"
  - `cron.scheduleModes.monthly` = "Monthly"
  - `cron.scheduleModes.once` = "Once"
  - `cron.scheduleModes.custom` = "Custom (cron expression)"
  - `cron.scheduleModes.intervalEvery` = "Every"
  - `cron.scheduleModes.intervalUnit` = "Unit"
  - `cron.scheduleModes.unitMinutes` = "minutes"
  - `cron.scheduleModes.unitHours` = "hours"
  - `cron.scheduleModes.unitDays` = "days"
  - `cron.scheduleModes.timeOfDay` = "Time of day"
  - `cron.scheduleModes.weekdays` = "Days of week"
  - `cron.scheduleModes.weekdaysShort` = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
  - `cron.scheduleModes.dayOfMonth` = "Day of month"
  - `cron.scheduleModes.onceAt` = "Run at"
  - `cron.scheduleModes.customLabel` = "Cron expression"
  - `cron.scheduleModes.customPlaceholder` = "0 9 * * *"
  - `cron.scheduleModes.customHint` = "Five-field cron expression (minute, hour, day, month, weekday)."
  - `cron.scheduleModes.preview` = "Sends as"
  - `cron.scheduleModes.previewEmpty` = "(incomplete)"
  - `cron.scheduleDescribe.none` = "—"
  - `cron.scheduleDescribe.everyMinutes` = "Every {n} min"
  - `cron.scheduleDescribe.everyHours` = "Every {n} h"
  - `cron.scheduleDescribe.everyDays` = "Every {n} d"
  - `cron.scheduleDescribe.dailyAt` = "Daily at {time}"
  - `cron.scheduleDescribe.weeklyAt` = "Weekly on {days} at {time}"
  - `cron.scheduleDescribe.monthlyAt` = "Monthly on the {day} at {time}"
  - `cron.scheduleDescribe.onceAt` = "Once at {time}"
  - `cron.deliverTo` = "Deliver to"
  - `cron.scheduledJobs` = "Scheduled Jobs"
  - `cron.noJobs` = "No cron jobs configured. Create one above."
  - `cron.last` = "Last"
  - `cron.next` = "Next"
  - `cron.pause` = "Pause"
  - `cron.resume` = "Resume"
  - `cron.triggerNow` = "Trigger now"
  - `cron.delivery.local` = "Local"
  - `cron.delivery.telegram` = "Telegram"
  - `cron.delivery.discord` = "Discord"
  - `cron.delivery.slack` = "Slack"
  - `cron.delivery.email` = "Email"
  - `cron.delivery.needsHomeChannel` = "set a home channel first"
  - `cron.delivery.noneConfigured` = "No messaging platforms configured. Set one up under Channels to deliver reports."
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `profiles` (58 keys)  `id: web-shell.i18n-ns-profiles`
- **Surface:** Web dashboard
- **Where:** Profiles page and the profile builder.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `profiles` object; read as ``t.profiles.*`` from `pages/ProfilesPage.tsx`, `pages/ProfileBuilderPage.tsx`, `contexts/ProfileProvider.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `profiles.newProfile` = "New Profile"
  - `profiles.name` = "Name"
  - `profiles.namePlaceholder` = "e.g. coder, writer, etc."
  - `profiles.nameRequired` = "Name is required"
  - `profiles.nameRule` = "Lowercase letters, digits, _ and - only; must start with a letter or digit; up to 64 characters."
  - `profiles.invalidName` = "Invalid profile name"
  - `profiles.cloneFrom` = "Clone config from"
  - `profiles.cloneFromNone` = "None (blank)"
  - `profiles.allProfiles` = "Profiles"
  - `profiles.noProfiles` = "No profiles found."
  - `profiles.defaultBadge` = "default"
  - `profiles.hasEnv` = "env"
  - `profiles.model` = "Model"
  - `profiles.skills` = "Skills"
  - `profiles.rename` = "Rename"
  - `profiles.editSoul` = "Edit SOUL.md"
  - `profiles.soulSection` = "SOUL.md (personality / system prompt)"
  - `profiles.soulPlaceholder` = "# How this agent should behave…"
  - `profiles.saveSoul` = "Save SOUL"
  - `profiles.soulSaved` = "SOUL.md saved"
  - `profiles.openInTerminal` = "Copy CLI command"
  - `profiles.commandCopied` = "Copied to clipboard"
  - `profiles.copyFailed` = "Could not copy"
  - `profiles.confirmDeleteTitle` = "Delete profile?"
  - `profiles.confirmDeleteMessage` = "This permanently deletes profile '{name}' — config, keys, memories, sessions, skills, cron jobs. Cannot be undone."
  - `profiles.created` = "Created"
  - `profiles.deleted` = "Deleted"
  - `profiles.renamed` = "Renamed"
  - `profiles.activeProfile` = "Active profile"
  - `profiles.activeBadge` = "active"
  - `profiles.setActive` = "Set as active"
  - `profiles.activeSet` = "Active profile set"
  - `profiles.gatewayRunning` = "Gateway running"
  - `profiles.gatewayStopped` = "Gateway stopped"
  - `profiles.gatewayRunningWarning` = "This profile's gateway is running — it will be stopped."
  - `profiles.aliasBadge` = "alias"
  - `profiles.description` = "Description"
  - `profiles.descriptionPlaceholder` = "What is this profile good at? Used to route kanban tasks by role."
  - `profiles.noDescription` = "No description"
  - `profiles.editDescription` = "Edit description"
  - `profiles.descriptionSaved` = "Description saved"
  - `profiles.reviewBadge` = "review"
  - `profiles.autoGenerate` = "Auto-generate"
  - `profiles.generating` = "Generating…"
  - `profiles.describeFailed` = "Could not generate description"
  - `profiles.distribution` = "Distribution"
  - `profiles.advancedOptions` = "Advanced options"
  - `profiles.cloneAll` = "Clone everything (memories, sessions, skills, state)"
  - `profiles.noSkillsOption` = "Don't seed bundled skills"
  - `profiles.descriptionOptional` = "Description (optional)"
  - `profiles.modelOptional` = "Model (optional)"
  - `profiles.modelInherit` = "Inherit from clone / default"
  - `profiles.modelLoading` = "Loading models…"
  - `profiles.modelNone` = "No authenticated providers — set a key first"
  - `profiles.editModel` = "Change model"
  - `profiles.modelSaved` = "Model updated"
  - `profiles.modelSelect` = "Select a model"
  - `profiles.actions` = "Actions"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `pluginsPage` (36 keys)  `id: web-shell.i18n-ns-pluginspage`
- **Surface:** Web dashboard
- **Where:** Plugins page (agent plugins + runtime providers + dashboard extensions).
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `pluginsPage` object; read as ``t.pluginsPage.*`` from `pages/PluginsPage.tsx` (shard web-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `pluginsPage.contextEngineLabel` = "Context engine"
  - `pluginsPage.dashboardSlots` = "Dashboard slots"
  - `pluginsPage.disableRuntime` = "Disable"
  - `pluginsPage.enableAfterInstall` = "Enable after install"
  - `pluginsPage.enableRuntime` = "Enable"
  - `pluginsPage.forceReinstall` = "Force reinstall (delete existing folder first)"
  - `pluginsPage.headline` = "Discover, install, enable, and update Hermes plugins (`hermes plugins` parity)."
  - `pluginsPage.identifierLabel` = "Git URL or owner/repo"
  - `pluginsPage.inactive` = "inactive"
  - `pluginsPage.installBtn` = "Install"
  - `pluginsPage.installHeading` = "Install from GitHub / Git URL"
  - `pluginsPage.installHint` = "Use owner/repo shorthand or a full https:// or git@ clone URL. For a plugin in a subdirectory, append the path: owner/repo/path/to/plugin (or <url>#path/to/plugin)."
  - `pluginsPage.memoryProviderLabel` = "Memory provider"
  - `pluginsPage.missingEnvWarn` = "Set these in Keys before the plugin can run:"
  - `pluginsPage.noDashboardTab` = "No dashboard tab"
  - `pluginsPage.openTab` = "Open"
  - `pluginsPage.orphanHeading` = "Dashboard-only extensions (no agent plugin.yaml match)"
  - `pluginsPage.pluginListHeading` = "Installed plugins"
  - `pluginsPage.providerDefaults` = "built-in / default"
  - `pluginsPage.providersHeading` = "Runtime provider plugins"
  - `pluginsPage.providersHint` = "Writes memory.provider (empty = built-in) and context.engine to config.yaml. Takes effect next session."
  - `pluginsPage.refreshDashboard` = "Rescan dashboard extensions"
  - `pluginsPage.removeConfirm` = "Remove this plugin from ~/.hermes/plugins/?"
  - `pluginsPage.removeHint` = "Only user-installed plugins under ~/.hermes/plugins can be removed."
  - `pluginsPage.rescanHeading` = "SPA plugin registry"
  - `pluginsPage.rescanHint` = "Rescan after adding files on disk so the dashboard sidebar picks up new manifests."
  - `pluginsPage.runtimeHeading` = "Gateway runtime (YAML plugins)"
  - `pluginsPage.saveProviders` = "Save provider settings"
  - `pluginsPage.savedProviders` = "Provider settings saved."
  - `pluginsPage.sourceBadge` = "Source"
  - `pluginsPage.authRequired` = "Auth required"
  - `pluginsPage.authRequiredHint` = "Run this command to authenticate:"
  - `pluginsPage.updateGit` = "Git pull"
  - `pluginsPage.versionBadge` = "Version"
  - `pluginsPage.showInSidebar` = "Show in sidebar"
  - `pluginsPage.hideFromSidebar` = "Hide from sidebar"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `skills` (20 keys)  `id: web-shell.i18n-ns-skills`
- **Surface:** Web dashboard
- **Where:** Skills page, skill cards and toolset grid.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `skills` object; read as ``t.skills.*`` from `pages/SkillsPage.tsx`, `pages/CronPage.tsx`, `pages/AnalyticsPage.tsx`, `lib/cron-job.ts` (shard web-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `skills.title` = "Skills"
  - `skills.searchPlaceholder` = "Search skills and toolsets..."
  - `skills.enabledOf` = "{enabled}/{total} enabled"
  - `skills.all` = "All"
  - `skills.categories` = "Categories"
  - `skills.filters` = "Filters"
  - `skills.noSkills` = "No skills found. Skills are loaded from ~/.hermes/skills/"
  - `skills.noSkillsMatch` = "No skills match your search or filter."
  - `skills.skillCount` = "{count} skill{s}"
  - `skills.resultCount` = "{count} result{s}"
  - `skills.noDescription` = "No description available."
  - `skills.toolsets` = "Toolsets"
  - `skills.toolsetLabel` = "{name} toolset"
  - `skills.noToolsetsMatch` = "No toolsets match the search."
  - `skills.setupNeeded` = "Setup needed"
  - `skills.disabledForCli` = "Disabled for CLI"
  - `skills.more` = "+{count} more"
  - `skills.profileSelector` = "Profile"
  - `skills.currentProfile` = "current ({name})"
  - `skills.managingProfile` = "Managing profile “{name}” — toggles apply to that profile, not this dashboard’s."
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `config` (35 keys)  `id: web-shell.i18n-ns-config`
- **Surface:** Web dashboard
- **Where:** Config page chrome, category names and toasts.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `config` object; read as ``t.config.*`` from `pages/ConfigPage.tsx`, `pages/EnvPage.tsx`, `pages/CronPage.tsx` (shards config-a / config-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `config.configPath` = "~/.hermes/config.yaml"
  - `config.filters` = "Filters"
  - `config.sections` = "Sections"
  - `config.exportConfig` = "Export config as JSON"
  - `config.importConfig` = "Import config from JSON"
  - `config.resetDefaults` = "Reset to defaults"
  - `config.resetScopeTooltip` = "Reset {scope} to defaults"
  - `config.confirmResetScope` = "Reset all {scope} settings to their defaults? This only updates the form — changes aren't written to config.yaml until you press Save."
  - `config.resetScopeToast` = "{scope} reset to defaults — review and Save to persist"
  - `config.rawYaml` = "Raw YAML Configuration"
  - `config.searchResults` = "Search Results"
  - `config.fields` = "field{s}"
  - `config.noFieldsMatch` = "No fields match \"{query}\""
  - `config.configSaved` = "Configuration saved"
  - `config.yamlConfigSaved` = "YAML config saved"
  - `config.failedToSave` = "Failed to save"
  - `config.failedToSaveYaml` = "Failed to save YAML"
  - `config.failedToLoadRaw` = "Failed to load raw config"
  - `config.configImported` = "Config imported — review and save"
  - `config.invalidJson` = "Invalid JSON file"
  - `config.categories.general` = "General"
  - `config.categories.agent` = "Agent"
  - `config.categories.terminal` = "Terminal"
  - `config.categories.display` = "Display"
  - `config.categories.delegation` = "Delegation"
  - `config.categories.memory` = "Memory"
  - `config.categories.compression` = "Compression"
  - `config.categories.security` = "Security"
  - `config.categories.browser` = "Browser"
  - `config.categories.voice` = "Voice"
  - `config.categories.tts` = "Text-to-Speech"
  - `config.categories.stt` = "Speech-to-Text"
  - `config.categories.logging` = "Logging"
  - `config.categories.discord` = "Discord"
  - `config.categories.auxiliary` = "Auxiliary"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `env` (26 keys)  `id: web-shell.i18n-ns-env`
- **Surface:** Web dashboard
- **Where:** Keys page (.env editor).
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `env` object; read as ``t.env.*`` from `pages/EnvPage.tsx`, `pages/ProfileBuilderPage.tsx`, `lib/mcp-server-create.ts`, `plugins/usePlugins.ts` (shard config-b).
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `env.changesNote` = "Changes are saved to disk immediately. Active sessions pick up new keys automatically."
  - `env.confirmClearMessage` = "The stored value for this variable will be removed from your .env file. This cannot be undone from the UI."
  - `env.confirmClearTitle` = "Clear this key?"
  - `env.description` = "Manage API keys and secrets stored in"
  - `env.hideAdvanced` = "Hide Advanced"
  - `env.showAdvanced` = "Show Advanced"
  - `env.showLess` = "Show less"
  - `env.showMore` = "Show more"
  - `env.llmProviders` = "LLM Providers"
  - `env.providersConfigured` = "{configured} of {total} providers configured"
  - `env.getKey` = "Get key"
  - `env.notConfigured` = "{count} not configured"
  - `env.notSet` = "Not set"
  - `env.keysCount` = "{count} key{s}"
  - `env.enterValue` = "Enter value..."
  - `env.replaceCurrentValue` = "Replace current value ({preview})"
  - `env.showValue` = "Show real value"
  - `env.hideValue` = "Hide value"
  - `env.customTitle` = "Custom Keys"
  - `env.customHint` = "Arbitrary environment variables stored in your .env that Hermes doesn't recognise. Use these to inject env vars for skills, MCP servers, or your own tooling."
  - `env.customConfigured` = "{count} custom key{s} set"
  - `env.addCustomKey` = "Add a custom key"
  - `env.customKeyName` = "Variable name"
  - `env.customKeyNamePlaceholder` = "e.g. MY_SERVICE_API_KEY"
  - `env.add` = "Add"
  - `env.invalidKeyName` = "Use letters, numbers and underscores only (must start with a letter or underscore)."
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `oauth` (36 keys)  `id: web-shell.i18n-ns-oauth`
- **Surface:** Web dashboard
- **Where:** Provider-login (OAuth) card and its modal.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `oauth` object; read as ``t.oauth.*`` from `components/OAuthProvidersCard.tsx`, `components/OAuthLoginModal.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `oauth.title` = "Provider Logins (OAuth)"
  - `oauth.providerLogins` = "Provider Logins (OAuth)"
  - `oauth.description` = "{connected} of {total} OAuth providers connected. Use Login for dashboard-supported flows; CLI commands remain available for external or fallback setup."
  - `oauth.connected` = "Connected"
  - `oauth.expired` = "Expired"
  - `oauth.notConnected` = "Not connected. Use Login when available, or run {command} in a terminal."
  - `oauth.runInTerminal` = "in a terminal."
  - `oauth.noProviders` = "No OAuth-capable providers detected."
  - `oauth.login` = "Login"
  - `oauth.disconnect` = "Disconnect"
  - `oauth.managedExternally` = "Managed externally"
  - `oauth.copied` = "Copied ✓"
  - `oauth.copyCode` = "Copy code"
  - `oauth.copyFailed` = "Could not copy automatically. Select the code and copy it manually."
  - `oauth.cli` = "Copy"
  - `oauth.copyCliCommand` = "Copy CLI command (for external / fallback)"
  - `oauth.connect` = "Connect"
  - `oauth.sessionExpires` = "Session expires in {time}"
  - `oauth.initiatingLogin` = "Initiating login flow…"
  - `oauth.exchangingCode` = "Exchanging code for tokens…"
  - `oauth.connectedClosing` = "Connected! Closing…"
  - `oauth.loginFailed` = "Login failed."
  - `oauth.sessionExpired` = "Session expired. Click Retry to start a new login."
  - `oauth.reOpenAuth` = "Re-open auth page"
  - `oauth.reOpenVerification` = "Re-open verification page"
  - `oauth.submitCode` = "Submit code"
  - `oauth.pasteCode` = "Paste authorization code (with #state suffix is fine)"
  - `oauth.waitingAuth` = "Waiting for you to authorize in the browser…"
  - `oauth.enterCodePrompt` = "A new tab opened. Enter this code if prompted:"
  - `oauth.pkceStep1` = "A new tab opened to claude.ai. Sign in and click Authorize."
  - `oauth.pkceStep2` = "Copy the authorization code shown after authorizing."
  - `oauth.pkceStep3` = "Paste it below and submit."
  - `oauth.flowLabels.pkce` = "Browser login (PKCE)"
  - `oauth.flowLabels.device_code` = "Device code"
  - `oauth.flowLabels.external` = "External CLI"
  - `oauth.expiresIn` = "expires in {time}"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `language` (1 keys)  `id: web-shell.i18n-ns-language`
- **Surface:** Web dashboard
- **Where:** The language picker's single label.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `language` object; read as ``t.language.*`` from `components/LanguageSwitcher.tsx`, `App.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `language.switchTo` = "Switch language"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `theme` (8 keys)  `id: web-shell.i18n-ns-theme`
- **Surface:** Web dashboard
- **Where:** The theme picker and its font section.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `theme` object; read as ``t.theme.*`` from `components/ThemeSwitcher.tsx`, `App.tsx`.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `theme.title` = "Theme"
  - `theme.switchTheme` = "Switch theme"
  - `theme.fontTitle` = "Font"
  - `theme.fontDefault` = "Theme default"
  - `theme.fontDefaultHint` = "Use the active theme's font"
  - `theme.fontSans` = "Sans"
  - `theme.fontSerif` = "Serif"
  - `theme.fontMono` = "Mono"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `achievements` (67 keys)  `id: web-shell.i18n-ns-achievements`
- **Surface:** Web dashboard
- **Where:** The bundled Achievements plugin page.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `achievements` object; read as ``t.achievements.*`` from `plugins/hermes-achievements/dashboard/dist/index.js` via `window.__HERMES_PLUGIN_SDK__.useI18n` — no `web/src` file references this namespace.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `achievements.hero.kicker` = "Agentic Gamerscore"
  - `achievements.hero.title` = "Hermes Achievements"
  - `achievements.hero.subtitle` = "Collectible Hermes badges earned from real session history. Known unfinished achievements are shown as Discovered; Secret achievements stay hidden until the first matching behavior appears."
  - `achievements.hero.scan_subtitle` = "Scanning Hermes session history. First scan can take 5–10 seconds on large histories."
  - `achievements.actions.rescan` = "Rescan"
  - `achievements.stats.unlocked` = "Unlocked"
  - `achievements.stats.unlocked_hint` = "earned badges"
  - `achievements.stats.discovered` = "Discovered"
  - `achievements.stats.discovered_hint` = "known, not earned yet"
  - `achievements.stats.secrets` = "Secrets"
  - `achievements.stats.secrets_hint` = "hidden until first signal"
  - `achievements.stats.highest_tier` = "Highest tier"
  - `achievements.stats.highest_tier_hint` = "Copper → Silver → Gold → Diamond → Olympian"
  - `achievements.stats.latest` = "Latest"
  - `achievements.stats.latest_hint_empty` = "run Hermes more"
  - `achievements.stats.none_yet` = "None yet"
  - `achievements.state.unlocked` = "Unlocked"
  - `achievements.state.discovered` = "Discovered"
  - `achievements.state.secret` = "Secret"
  - `achievements.tier.target` = "Target {tier}"
  - `achievements.tier.hidden` = "Hidden"
  - `achievements.tier.complete` = "Complete"
  - `achievements.tier.objective` = "Objective"
  - `achievements.progress.hidden` = "hidden"
  - `achievements.scan.building_headline` = "Building achievement profile…"
  - `achievements.scan.building_detail` = "Reading sessions, tool calls, model metadata, and unlock state."
  - `achievements.scan.starting_headline` = "Starting achievement scan…"
  - `achievements.scan.progress_detail` = "Scanned {scanned} of {total} sessions · {pct}%. Badges unlock as more history streams in."
  - `achievements.scan.idle_detail` = "Reading sessions, tool calls, model metadata, and unlock state. Badges appear here as they unlock."
  - `achievements.guide.tiers_header` = "Tiers"
  - `achievements.guide.secret_header` = "Secret achievements"
  - `achievements.guide.secret_body` = "Secrets hide their exact trigger. Once Hermes sees a related signal, the card becomes Discovered and shows its requirement."
  - `achievements.guide.scan_status_header` = "Scan status"
  - `achievements.guide.scan_status_body` = "Hermes is scanning local history once, then cards will appear automatically. Nothing is stuck if this takes a few seconds."
  - `achievements.guide.what_scanned_header` = "What is scanned"
  - `achievements.guide.what_scanned_body` = "Sessions, tool calls, model metadata, errors, achievements, and local unlock state."
  - `achievements.card.share_title` = "Share this achievement"
  - `achievements.card.share_label` = "Share {name}"
  - `achievements.card.share_text` = "Share"
  - `achievements.card.how_to_reveal` = "How to reveal"
  - `achievements.card.what_counts` = "What counts"
  - `achievements.card.evidence_label` = "Evidence"
  - `achievements.card.evidence_session_fallback` = "session"
  - `achievements.card.no_evidence` = "No evidence yet"
  - `achievements.latest.header` = "Recent unlocks"
  - `achievements.empty.no_secrets_header` = "No hidden secrets left in this scan."
  - `achievements.empty.no_secrets_body` = "Clue: secrets usually start from unusual failure or power-user patterns — port conflicts, permission walls, missing env vars, YAML mistakes, Docker collisions, rollback/checkpoint use, cache hits, or tiny fixes after lots of red text."
  - `achievements.filters.all_categories` = "All"
  - `achievements.filters.visibility_all` = "all"
  - `achievements.filters.visibility_unlocked` = "unlocked"
  - `achievements.filters.visibility_discovered` = "discovered"
  - `achievements.filters.visibility_secret` = "secret"
  - `achievements.share.dialog_label` = "Share achievement"
  - `achievements.share.header` = "Share: {name}"
  - `achievements.share.close` = "Close"
  - `achievements.share.rendering` = "Rendering…"
  - `achievements.share.card_alt` = "{name} share card"
  - `achievements.share.error_generic` = "Something went wrong."
  - `achievements.share.x_title` = "Opens X with a pre-filled post"
  - `achievements.share.x_button` = "Share on X"
  - `achievements.share.copy_title` = "Copy the image to paste into your post"
  - `achievements.share.copy_button` = "Copy image"
  - `achievements.share.copied` = "Copied ✓"
  - `achievements.share.download_button` = "Download PNG"
  - `achievements.share.hint` = "Share on X opens a pre-filled post in a new tab. Click Copy image first if you want the 1200×630 badge attached — X lets you paste it right into the tweet composer. Download PNG saves the file for use anywhere."
  - `achievements.share.clipboard_unsupported` = "Clipboard image copy not supported in this browser — use Download instead."
  - `achievements.share.tweet_text` = "Just unlocked {tier_part}\"{name}\" in Hermes Agent ☤"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

### i18n namespace `kanban` (168 keys)  `id: web-shell.i18n-ns-kanban`
- **Surface:** Web dashboard
- **Where:** The bundled Kanban plugin page.
- **What it does:** Supplies every user-visible string for that surface in the active locale.
- **How it works:** Defined in `web/src/i18n/en.ts` under the `kanban` object; read as ``t.kanban.*`` from `plugins/kanban/dashboard/dist/index.js` via `window.__HERMES_PLUGIN_SDK__.useI18n` — no `web/src` file references this namespace.
- **Inputs / options:** Keys and their English values (`{...}` segments are literal placeholders replaced with `String.replace` at the call site):
  - `kanban.loading` = "Loading Kanban board…"
  - `kanban.loadFailed` = "Failed to load Kanban board: "
  - `kanban.loadFailedHint` = "The backend auto-creates kanban.db on first read. If this persists, check the dashboard logs."
  - `kanban.board` = "Board"
  - `kanban.newBoard` = "+ New board"
  - `kanban.newBoardTitle` = "New board"
  - `kanban.newBoardDescription` = "Boards let you separate unrelated streams of work — one per project, repo, or domain. Workers on one board never see another board's tasks."
  - `kanban.slug` = "Slug"
  - `kanban.slugHint` = "— lowercase, hyphens, e.g. atm10-server"
  - `kanban.displayName` = "Display name"
  - `kanban.displayNameHint` = "(optional)"
  - `kanban.description` = "Description"
  - `kanban.descriptionHint` = "(optional)"
  - `kanban.icon` = "Icon"
  - `kanban.iconHint` = "(single character or emoji)"
  - `kanban.switchAfterCreate` = "Switch to this board after creating it"
  - `kanban.cancel` = "Cancel"
  - `kanban.creating` = "Creating…"
  - `kanban.createBoard` = "Create board"
  - `kanban.search` = "Search"
  - `kanban.filterCards` = "Filter cards…"
  - `kanban.tenant` = "Tenant"
  - `kanban.allTenants` = "All tenants"
  - `kanban.assignee` = "Assignee"
  - `kanban.allProfiles` = "All profiles"
  - `kanban.showArchived` = "Show archived"
  - `kanban.lanesByProfile` = "Lanes by profile"
  - `kanban.nudgeDispatcher` = "Nudge dispatcher"
  - `kanban.refresh` = "Refresh"
  - `kanban.selected` = "selected"
  - `kanban.complete` = "Complete"
  - `kanban.archive` = "Archive"
  - `kanban.apply` = "Apply"
  - `kanban.clear` = "Clear"
  - `kanban.createTask` = "Create task in this column"
  - `kanban.noTasks` = "— no tasks —"
  - `kanban.unassigned` = "unassigned"
  - `kanban.needsAssignee` = "Needs assignee"
  - `kanban.needsAssigneeHint` = "Dependencies are satisfied, but the dispatcher skips this task until you assign a profile."
  - `kanban.untitled` = "(untitled)"
  - `kanban.loadingDetail` = "Loading…"
  - `kanban.addComment` = "Add a comment… (Enter to submit)"
  - `kanban.comment` = "Comment"
  - `kanban.status` = "Status"
  - `kanban.workspace` = "Workspace"
  - `kanban.skills` = "Skills"
  - `kanban.createdBy` = "Created by"
  - `kanban.result` = "Result"
  - `kanban.comments` = "Comments"
  - `kanban.events` = "Events"
  - `kanban.runHistory` = "Run history"
  - `kanban.workerLog` = "Worker log"
  - `kanban.loadingLog` = "Loading log…"
  - `kanban.noWorkerLog` = "— no worker log yet (task hasn't spawned or log was rotated away) —"
  - `kanban.noDescription` = "— no description —"
  - `kanban.noComments` = "— no comments —"
  - `kanban.edit` = "edit"
  - `kanban.save` = "Save"
  - `kanban.dependencies` = "Dependencies"
  - `kanban.parents` = "Parents:"
  - `kanban.children` = "Children:"
  - `kanban.none` = "none"
  - `kanban.addParent` = "— add parent —"
  - `kanban.addChild` = "— add child —"
  - `kanban.removeDependency` = "Remove dependency"
  - `kanban.block` = "Block"
  - `kanban.unblock` = "Unblock"
  - `kanban.notifyHomeChannels` = "Notify home channels"
  - `kanban.diagnostics` = "Diagnostics"
  - `kanban.hide` = "Hide"
  - `kanban.show` = "Show"
  - `kanban.attention` = "Attention"
  - `kanban.tasksNeedAttention` = "tasks need attention"
  - `kanban.taskNeedsAttention` = "1 task needs attention"
  - `kanban.diagnostic` = "diagnostic"
  - `kanban.open` = "Open"
  - `kanban.close` = "Close (Esc)"
  - `kanban.reassignTo` = "Reassign to:"
  - `kanban.copied` = "Copied"
  - `kanban.copyCommand` = "Copy command to clipboard"
  - `kanban.reclaim` = "Reclaim"
  - `kanban.reassign` = "Reassign"
  - `kanban.renderingError` = "Kanban tab hit a rendering error"
  - `kanban.reloadView` = "Reload view"
  - `kanban.wsAuthFailed` = "WebSocket auth failed — reload the page to refresh the session token."
  - `kanban.markDone` = "Mark {n} task(s) as done?"
  - `kanban.markArchived` = "Archive {n} task(s)?"
  - `kanban.warning` = "Warning"
  - `kanban.phantomIds` = "Phantom ids:"
  - `kanban.active` = "active"
  - `kanban.ended` = "ended"
  - `kanban.noProfile` = "(no profile)"
  - `kanban.showAllAttempts` = "Show all attempts"
  - `kanban.sendingUpdates` = "Sending updates to"
  - `kanban.sendNotifications` = "Send completed / blocked / gave_up notifications to"
  - `kanban.archiveBoardConfirm` = "Archive board '{name}'? It will be moved to boards/_archived/ so you can recover it later. Tasks on this board will no longer appear anywhere in the UI."
  - `kanban.archiveBoardTitle` = "Archive this board"
  - `kanban.boardSwitcherHint` = "Boards let you separate unrelated streams of work"
  - `kanban.taskCreatedWarning` = "Task created, but: "
  - `kanban.moveFailed` = "Move failed: "
  - `kanban.bulkFailed` = "Bulk: "
  - `kanban.completionBlockedHallucination` = "⚠ Completion blocked — phantom card ids"
  - `kanban.suspectedHallucinatedReferences` = "⚠ Prose referenced phantom card ids"
  - `kanban.pickProfileFirst` = "Pick a profile first."
  - `kanban.unblockedMessage` = "Unblocked {id}. Task is ready for the next tick."
  - `kanban.unblockFailed` = "Unblock failed: "
  - `kanban.reclaimedMessage` = "Reclaimed {id}. Task is back to ready."
  - `kanban.reclaimFailed` = "Reclaim failed: "
  - `kanban.reassignedMessage` = "Reassigned {id} to {profile}."
  - `kanban.reassignFailed` = "Reassign failed: "
  - `kanban.selectForBulk` = "Select for bulk actions"
  - `kanban.clickToEdit` = "Click to edit"
  - `kanban.clickToEditAssignee` = "Click to edit assignee"
  - `kanban.emptyAssignee` = "(empty = unassign)"
  - `kanban.columnLabels.triage` = "Triage"
  - `kanban.columnLabels.todo` = "Todo"
  - `kanban.columnLabels.scheduled` = "Scheduled"
  - `kanban.columnLabels.ready` = "Ready"
  - `kanban.columnLabels.running` = "In Progress"
  - `kanban.columnLabels.blocked` = "Blocked"
  - `kanban.columnLabels.done` = "Done"
  - `kanban.columnLabels.archived` = "Archived"
  - `kanban.columnHelp.triage` = "Raw ideas — a specifier will flesh out the spec"
  - `kanban.columnHelp.todo` = "Waiting on dependencies or unassigned"
  - `kanban.columnHelp.scheduled` = "Waiting on a known time delay or scheduled follow-up"
  - `kanban.columnHelp.ready` = "Dependencies satisfied; assign a profile to dispatch"
  - `kanban.columnHelp.running` = "Claimed by a worker — in-flight"
  - `kanban.columnHelp.blocked` = "Worker asked for human input"
  - `kanban.columnHelp.done` = "Completed"
  - `kanban.columnHelp.archived` = "Archived"
  - `kanban.confirmDone` = "Mark this task as done? The worker's claim is released and dependent children become ready."
  - `kanban.confirmArchive` = "Archive this task? It disappears from the default board view."
  - `kanban.confirmBlocked` = "Mark this task as blocked? The worker's claim is released."
  - `kanban.confirmScheduled` = "Move this task to Scheduled? Use this for known time delays rather than human blockers."
  - `kanban.confirmDoneMany` = "Mark {n} tasks as done? The workers' claims are released and dependent children become ready."
  - `kanban.confirmArchiveMany` = "Archive {n} tasks? They disappear from the default board view."
  - `kanban.confirmBlockedMany` = "Mark {n} tasks as blocked? The workers' claims are released."
  - `kanban.completionSummary` = "Completion summary for {label}. This is stored as the task result."
  - `kanban.completionSummaryRequired` = "Completion summary is required before marking a task done."
  - `kanban.triagePlaceholder` = "Rough idea — AI will spec it…"
  - `kanban.taskTitlePlaceholder` = "New task title…"
  - `kanban.specifier` = "specifier"
  - `kanban.assigneePlaceholder` = "assignee"
  - `kanban.priority` = "Priority"
  - `kanban.skillsPlaceholder` = "skills (optional, comma-separated): translation, github-code-review"
  - `kanban.noParent` = "— no parent —"
  - `kanban.workspacePathDir` = "workspace path (required, e.g. ~/projects/my-app)"
  - `kanban.workspacePathOptional` = "workspace path (optional, derived from assignee if blank)"
  - `kanban.logTruncated` = "(showing last 100 KB — full log at "
  - `kanban.logAt` = ")"
  - `kanban.newTaskTitle` = "New task — {column}"
  - `kanban.taskTitleLabel` = "Title"
  - `kanban.assigneeLabel` = "Assignee"
  - `kanban.assigneeLabelHint` = "(blank = dispatcher picks)"
  - `kanban.skillsLabel` = "Skills"
  - `kanban.skillsLabelHint` = "(optional, comma-separated)"
  - `kanban.parentLabel` = "Parent task"
  - `kanban.parentLabelHint` = "(child stays blocked until the parent is done)"
  - `kanban.create` = "Create"
  - `kanban.boardSettings` = "Settings"
  - `kanban.boardSettingsTitle` = "Board settings — name, description, and the default project directory new tasks inherit"
  - `kanban.boardSettingsTitleFor` = "Board settings — {name}"
  - `kanban.projectDirectoryOverrideHint` = "New tasks inherit this as their workspace default; each task can still override it in the create dialog."
  - `kanban.saving` = "Saving…"
  - `kanban.commentHint` = "Comments reach the worker on its next run or kanban_show() — no need to block the task first."
  - `kanban.commentHintTitle` = "Comments are the channel for talking to a task's worker. They land on the thread immediately — no need to block the task first. A running worker picks the thread up on its next kanban_show() or respawn; blocking is only for when you want the worker to STOP and wait for your input."
  - `kanban.trash.confirmTitle` = "Delete task?"
  - `kanban.trash.confirmManyTitle` = "Delete {n} tasks?"
- **Outputs / side effects:** Rendered text; no side effects.
- **Config / env:** Active locale from `localStorage["hermes-locale"]`.
- **Edge cases / guards:** A locale that omits a key falls back to the English value (object-literal locales copy it; `ar.ts` gets it through `defineLocale`). Some call sites additionally inline an English fallback with `??` for keys added after a locale was written.
- **Rebuild notes:** Keep the namespace boundary aligned with the owning surface; placeholders are positional-free named tokens replaced by simple string substitution, not ICU messages — plural handling is done ad hoc (e.g. `{count} skill{s}`).

---

## 5. Client library (`web/src/lib/`)

### API client core (`fetchJSON`)  `id: web-shell.api-fetchjson`
- **Surface:** Web dashboard / API
- **Where:** Invisible; every dashboard REST call and every plugin call routed through the SDK.
- **What it does:** Prefixes the base path, injects the session token, applies the management-profile
  scope, handles the two 401 recovery paths, throws on non-2xx, and parses JSON.
- **How it works:** `web/src/lib/api.ts:106-190`.
  1. `url = withManagementProfile(url)` (see next entry).
  2. `const token = window.__HERMES_SESSION_TOKEN__; if (token) setSessionHeader(headers, token)` —
     `setSessionHeader` only sets `X-Hermes-Session-Token` when the caller has not already provided
     it (`api.ts:43-47`). Header name constant: `SESSION_HEADER = "X-Hermes-Session-Token"`
     (`api.ts:41`).
  3. `fetch(`${BASE}${url}`, {...init, headers, credentials: init?.credentials ?? "include"})` —
     `credentials: "include"` is what makes the gated cookie ride along; loopback mode ignores
     cookies.
  4. **401 handling** (`api.ts:124-170`): it clones the response and tries to parse
     `{error, login_url}`. If `error` is `"unauthenticated"` or `"session_expired"` *and* a
     `login_url` is present, it saves `sessionStorage["hermes.lastLocation"] = pathname + search`
     and does `window.location.assign(body.login_url)`, returning a promise that never resolves
     (the page is unloading). Domain-level 401s without that envelope bubble up as ordinary errors.
     Otherwise, in loopback mode (`!window.__HERMES_AUTH_REQUIRED__`) and unless the caller passed
     `allowUnauthorized`, it calls `attemptDashboardTokenReloadOnce()` — the stale-token reload.
  5. Any 2xx clears the reload guard (`clearDashboardTokenReloadAttempt()`), proving the current token
     is valid so the next 401 gets its own reload cycle.
  6. Non-OK: throws `new Error(`${res.status}: ${text}`)` where `text` is the response body (or
     `statusText`). This `"<status>: <body>"` prefix convention is what `AuthWidget` matches on.
  7. Returns `res.json()`.
- **Inputs / options:** `(url, init?: RequestInit, options?: {allowUnauthorized?: boolean})`.
- **Outputs / side effects:** Possible full-page navigation to `login_url` or a reload; a
  `sessionStorage` write on session expiry.
- **Config / env:** `window.__HERMES_SESSION_TOKEN__`, `window.__HERMES_BASE_PATH__`,
  `window.__HERMES_AUTH_REQUIRED__`.
- **Edge cases / guards:** The one-shot reload guard prevents an infinite loop when the token is
  genuinely wrong; `allowUnauthorized` opts a call out entirely.
- **Rebuild notes:** One choke point for auth, base path, scope and error shape. A better version would
  return a typed `Result` instead of throwing string-prefixed `Error`s that callers parse.

### Management-profile query injection  `id: web-shell.api-profile-injection`
- **Surface:** Web dashboard / API
- **Where:** Invisible; appends `?profile=<name>` to scoped endpoints.
- **What it does:** Makes the sidebar profile switcher retarget every management read/write without
  each page threading a profile argument.
- **How it works:** `lib/api.ts:57-104`. Module state `_managementProfile` (set by
  `setManagementProfile`, read by `getManagementProfile`). `withManagementProfile(url)` returns the
  url unchanged when the scope is empty or when the url already contains `profile=` ("explicit param
  wins"), otherwise appends `?`/`&` + `profile=<encodeURIComponent(name)>` — but **only** when the
  path starts with one of the allow-listed prefixes (`PROFILE_SCOPED_PREFIXES`, `api.ts:70-92`), in
  this exact order: `/api/status`, `/api/gateway`, `/api/analytics`, `/api/skills`,
  `/api/tools/toolsets`, `/api/config`, `/api/env`, `/api/mcp`, `/api/messaging/platforms`,
  `/api/messaging/telegram/onboarding`, `/api/messaging/whatsapp/onboarding`,
  `/api/providers/oauth`, `/api/model/info`, `/api/model/set`, `/api/model/auxiliary`,
  `/api/model/moa`, `/api/model/options`, `/api/pairing`. Everything else (ops endpoints, cron —
  which carries its own per-job profile params — and the profiles endpoints themselves) is
  machine-global or self-scoped and must not be rewritten.
  Session endpoints use explicit helpers instead: `profileQuery`, `appendProfileParam`,
  `appendQueryParam`, `normalizeSessionQueryOptions`, `appendSessionFilters`
  (`api.ts:291-340`), which also serialise `source`, `sources` (comma-joined) and `exclude_sources`.
- **Inputs / options:** `SessionQueryOptions {profile?, order?: "created"|"recent", source?, sources?, excludeSources?}`.
- **Outputs / side effects:** Rewritten request URLs.
- **Config / env:** n/a.
- **Edge cases / guards:** The comment explains why the list is an allow-list and not a wildcard —
  the pairing entry notes a named profile keeps its own pairing whitelist, so approving into the
  global store would grant access the running gateway never sees.
- **Rebuild notes:** Allow-list the scoped families explicitly; never scope by default.

### WebSocket authentication (`getWsTicket`, `buildWsAuthParam`, `buildWsUrl`)  `id: web-shell.ws-auth`
- **Surface:** Web dashboard / API
- **Where:** Invisible; used by the chat PTY socket, the JSON-RPC sidecar, the events subscriber and
  any plugin WebSocket.
- **What it does:** Produces the correct WS-upgrade credential for the active auth mode, because
  browsers cannot set `Authorization` on a WebSocket upgrade.
- **How it works:** `lib/api.ts:206-290`.
  - `getWsTicket()` → `POST /api/auth/ws-ticket` with `credentials:"include"`, returning
    `{ticket, ttl_seconds}`; throws `` `/api/auth/ws-ticket: HTTP <status>` `` on failure.
  - `buildWsAuthParam()` → `["ticket", <fresh ticket>]` when `window.__HERMES_AUTH_REQUIRED__`,
    else `["token", window.__HERMES_SESSION_TOKEN__ ?? ""]`.
  - `buildWsUrl(path, params?)` → `buildHermesWebSocketUrl({authParam, basePath: BASE, params, path})`
    from `@hermes/shared`, i.e. absolute `ws(s)://` with the base path applied and extra params merged
    before the auth param.
  Server side: tickets are single-use with `TTL_SECONDS = 30`
  (`hermes_cli/dashboard_auth/ws_tickets.py:39`), stored in an in-memory dict guarded by a lock.
  A second credential shape exists for server-spawned children — a process-lifetime, multi-use
  **internal credential** (`internal_ws_credential` / `consume_internal_credential`) that is never
  injected into any HTML and only leaves the process through the spawned PTY child's environment;
  connections authenticated with it are recorded as `INTERNAL_USER_ID = "server-internal"` /
  `INTERNAL_PROVIDER = "server-internal"`.
- **Inputs / options:** `path`, optional `params` record.
- **Outputs / side effects:** One ticket-minting POST per connect attempt in gated mode.
- **Config / env:** `window.__HERMES_AUTH_REQUIRED__`.
- **Edge cases / guards:** Every connect must mint a fresh ticket (single-use, 30 s). The internal
  credential exists because a 30 s single-use ticket is the wrong shape for a child that reads its
  attach URL once and reuses it across reconnects and slow cold boots.
- **Rebuild notes:** Mint short-lived single-use tickets over the authenticated REST channel; give
  server-spawned clients a separate, never-browser-visible credential.

### `authedFetch` (non-JSON requests)  `id: web-shell.authed-fetch`
- **Surface:** Web dashboard / API
- **Where:** Invisible; used for uploads (`FormData`), blob downloads and streamed responses, and
  exposed to plugins.
- **What it does:** Same auth handling as `fetchJSON` but returns the raw `Response`.
- **How it works:** `lib/api.ts:248-265`. Attaches `X-Hermes-Session-Token` when present and
  `credentials: "include"`. Deliberately does **not** parse the body, does **not** throw on non-2xx
  (a 404 on a download is meaningful), and does **not** run the global 401→`/login` redirect (binary
  endpoints are not navigation targets).
- **Inputs / options:** `(url, init?)`.
- **Outputs / side effects:** none beyond the request.
- **Config / env:** as `fetchJSON`.
- **Edge cases / guards:** Callers that want the redirect must use `fetchJSON`.
- **Rebuild notes:** Split "auth + transport" from "parse + error policy" so binary endpoints are not
  forced through a JSON contract.

### Stale-token reload guard  `id: web-shell.dashboard-auth-reload`
- **Surface:** Web dashboard
- **Where:** Invisible; manifests as a single automatic page reload after a gateway/dashboard restart.
- **What it does:** In loopback mode the ephemeral `_SESSION_TOKEN` rotates on every server restart
  (`hermes update`, `hermes gateway restart`). A tab left open holds the old token, so every fetch
  401s; the HTML is `no-store`, so one reload picks up the fresh token.
- **How it works:** `lib/dashboard-auth-reload.ts:1-69`.
  - Key: `sessionStorage["hermes.tokenReloadAttempted"] = "1"`.
  - `attemptDashboardTokenReloadOnce(storage?, reload?)` returns `false` if already attempted,
    otherwise sets the flag and calls `window.location.reload()`, returning `true`.
  - `clearDashboardTokenReloadAttempt()` removes the flag (called from `fetchJSON` on any 2xx).
  - `maybeReloadForLoopbackWsAuthFailure(code, authRequired?, storage?, reload?)` triggers the same
    one-shot reload for WebSocket close code **4401**, and only in loopback mode.
  All storage access is try/catch-wrapped; both functions accept injected storage/reload for tests
  (`lib/dashboard-auth-reload.test.ts`).
- **Inputs / options:** WS close code 4401; HTTP 401.
- **Outputs / side effects:** One `location.reload()`; one `sessionStorage` key.
- **Config / env:** `window.__HERMES_AUTH_REQUIRED__` disables the whole path (gated mode has real
  auth failures that must not reload-loop).
- **Edge cases / guards:** The one-shot guard is the entire safety mechanism; it is cleared only by a
  successful request.
- **Rebuild notes:** Serve the shell `no-store`, rotate the token per process, and reload exactly once.

### JSON-RPC gateway WebSocket client  `id: web-shell.gateway-client`
- **Surface:** Web dashboard
- **Where:** Invisible; backs the Chat sidebar's "live" badge, slash-command completion and model
  options.
- **What it does:** Speaks the same newline-delimited JSON-RPC dialect over `/api/ws` that the Ink TUI
  speaks over stdio.
- **How it works:** `lib/gatewayClient.ts:29-63`. Extends `JsonRpcGatewayClient` from `@hermes/shared`
  with `{closedErrorMessage: "WebSocket closed", connectErrorMessage: "WebSocket connection failed",
  notConnectedErrorMessage: "gateway not connected", onSocketClose: e => maybeReloadForLoopbackWsAuthFailure(e.code),
  requestIdPrefix: "w"}`. `connect(token?)` no-ops when already `open`/`connecting`, resolves the auth
  param (explicit `token` is a test-only override), throws
  `Session token not available — page must be served by the Hermes dashboard server` when the value is
  empty, and connects to `buildHermesWebSocketUrl({authParam, basePath: HERMES_BASE_PATH, path: "/api/ws"})`.
  Usage sketch in the file header: `session.create` → `message.delta` events → `prompt.submit`.
- **Inputs / options:** `connect(token?)`, `request(method, params)`, `on(event, handler)`.
- **Outputs / side effects:** A live WebSocket; possible one-shot reload on close code 4401.
- **Config / env:** as `web-shell.ws-auth`.
- **Edge cases / guards:** Re-exports `ConnectionState`, `GatewayEvent`, `GatewayEventName` types.
- **Rebuild notes:** Share the RPC client between TUI and web via one package; only the transport
  differs.

### `dashboard-flags.ts` — embedded-chat flag  `id: web-shell.dashboard-flags`
- **Surface:** Web dashboard
- **Where:** Invisible; decides whether the `/chat` route and nav item exist.
- **What it does:** `isDashboardEmbeddedChatEnabled()` returns a hard `true`.
- **How it works:** `lib/dashboard-flags.ts:22-24`. The doc comment states the embedded TUI chat
  (`/chat`, `/api/ws`, `/api/pty`) is now an unconditional part of the dashboard because the desktop
  app and the in-browser Chat tab both depend on it; the function is retained "as a stable seam".
  The corresponding `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` global is still declared and still
  injected by the server (live value `true`), and is consumed by the Vite dev-token plugin.
- **Inputs / options:** n/a.
- **Outputs / side effects:** none.
- **Config / env:** `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` (informational).
- **Edge cases / guards:** Because the function ignores the global, setting it to `false` server-side
  would not actually disable the chat tab in this build.
- **Rebuild notes:** Either honour the flag or delete it; a seam that ignores its input is a trap.

### `chat-activation.ts` — PTY activation latch  `id: web-shell.chat-activation`
- **Surface:** Web dashboard
- **Where:** Invisible; gates the first PTY spawn.
- **What it does:** `latchChatActivation(previous, isActive)` returns `previous || isActive` — once
  true, always true.
- **How it works:** `lib/chat-activation.ts:15-17`. Rationale in the header: because `ChatPage` stays
  mounted on every route, the PTY-connect effect would otherwise open `/api/pty` — spawning the whole
  TUI + agent bootstrap, which on a fresh checkout prints `Installing TUI dependencies…` and runs
  `npm install` — as soon as the dashboard loads *any* page.
- **Inputs / options:** two booleans.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Tested in `lib/chat-activation.test.ts`.
- **Rebuild notes:** Sticky activation is the cheap way to get "persistent but lazy".

### `utils.ts` — `cn`, font helpers, relative time  `id: web-shell.lib-utils`
- **Surface:** Web dashboard
- **Where:** Invisible; `cn` is used by essentially every component and is exposed to plugins.
- **What it does:** Class merging plus two relative-time formatters and three themed-font class
  constants.
- **How it works:** `lib/utils.ts:1-35`.
  - `cn(...inputs)` = `twMerge(clsx(inputs))`.
  - `themedFont = "font-mondwest"`, `themedBody = "font-mondwest normal-case"`,
    `themedChrome = "font-mondwest text-display"` (the comments warn not to force `normal-case` on
    layout shells or DS chrome stops uppercasing).
  - `timeAgo(ts)` from a Unix **seconds** epoch: `<60s` → `just now`; `<3600` → `Nm ago`;
    `<86400` → `Nh ago`; `<172800` → `yesterday`; else `Nd ago`.
  - `isoTimeAgo(iso)` from an ISO-8601 string: negative or `NaN` → `unknown`; `<60` → `just now`;
    `<3600` → `Nm ago`; `<86400` → `Nh ago`; else `Nd ago`. Note it has no `yesterday` branch, unlike
    `timeAgo`.
- **Inputs / options:** as above.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** These strings are **not** localised — they are hard-coded English in both
  helpers.
- **Rebuild notes:** Route relative time through the i18n layer; the two functions should share one
  ladder.

### Remaining `lib/` modules (index)  `id: web-shell.lib-index`
- **Surface:** Web dashboard
- **Where:** Invisible; imported by pages and components.
- **What it does:** The rest of `web/src/lib/` — small, mostly pure helpers, each with a colocated
  `*.test.ts` (the directory ships 30 test files).
- **How it works:** Complete list of non-test modules and their owner:
  | module | lines | purpose | owning shard |
  |---|---|---|---|
  | `api.ts` | 2667 | REST client + all response types (see the four entries above and the method index) | web-shell |
  | `dashboard-auth-reload.ts` | 69 | one-shot stale-token reload | web-shell |
  | `dashboard-flags.ts` | 24 | embedded-chat seam | web-shell |
  | `chat-activation.ts` | 17 | PTY activation latch | web-shell |
  | `resolve-page-title.ts` | 57 | page-header title resolution | web-shell |
  | `utils.ts` | 35 | `cn`, themed font classes, `timeAgo`, `isoTimeAgo` | web-shell |
  | `gatewayClient.ts` | 63 | JSON-RPC WS client | web-shell |
  | `dashboard-modal-shell.ts` | 29 | shared modal backdrop/panel classes | web-shell |
  | `nested.ts` | 23 | `getNestedValue` / `setNestedValue` on dotted paths (`structuredClone` + auto-vivify) | config-a/config-b |
  | `format.ts` | 9 | `formatTokenCount` — `≥1e6 → "<n>M"`, `≥1e3 → "<n>K"`, else the raw integer; one decimal unless exactly round | web-a |
  | `fuzzy.ts` | 192 | subsequence scorer (`fuzzyScore`, `fuzzyScoreMulti`, `fuzzyRank`) — see its own entry | web-shell |
  | `clipboard.ts` | 56 | `copyTextToClipboard` — see its own entry | web-shell |
  | `env-state.ts` | 21 | Keys-page value state helpers | config-b |
  | `log-classify.ts` | 36 | log-line level/component classification | web-b |
  | `schedule.ts` | 465 | cron schedule model + `buildScheduleString` + `describeSchedule` | web-b |
  | `cron-job.ts` | 104 | cron job form model | web-b |
  | `session-prune.ts` | 11 | prune-dialog arithmetic | web-a |
  | `session-import.ts` | 46 | session JSON/JSONL import parsing | web-a |
  | `session-refresh.ts` | 26 | cross-process session refresh signal | web-a |
  | `chat-title.ts` | 15 | derive a chat title from a session | web-a |
  | `chat-sidebar-session-params.test.ts` (+ source in `ChatSidebar.tsx`) | — | sidecar session params | web-a |
  | `chatImagePaste.ts` | 164 | clipboard/drag image upload for chat | web-a |
  | `slashExec.ts` | 163 | slash-command execution from the composer | web-a |
  | `model-picker-filter.ts` | 23 | model list filtering | web-a |
  | `model-search-text.ts` | 31 | model search haystack builder | web-a |
  | `reasoning-effort.ts` | 38 | `EFFORT_OPTIONS`, `VALID_EFFORTS`, `normalizeEffort` | web-a |
  | `events-reconnect.ts` | 84 | `/api/events` reconnect/backoff policy + `EVENTS_CONNECT_TIMEOUT_MS`, `EVENTS_DISCONNECTED_MESSAGE` | web-a |
  | `pty-reconnect.ts` | 93 | PTY reconnect policy | web-a |
  | `pty-resume-loading.ts` | 47 | resume-state loading | web-a |
  | `pty-resume-sanitizer.ts` | 128 | sanitises resumed terminal output | web-a |
  | `pty-scroll.ts` | 78 | wheel/scroll handling in the terminal | web-a |
  | `pty-keyboard-shortcuts.ts` | 63 | copy/paste/word-delete key handling | web-a |
  | `pty-composition.ts` | 54 | IME composition handling | web-a |
  | `pty-mobile-input.ts` | 136 | mobile replacement-input normalisation | web-a |
  | `keyboard-inset.ts` | 71 | soft-keyboard viewport inset | web-a |
  | `mcp-server-create.ts` | 78 | MCP add-server form model | web-b |
  | `mcp-dashboard-oauth.ts` | 66 | MCP OAuth flow helper | web-b |
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** The pattern worth copying is "extract the arithmetic/policy into a pure module
  with a vitest file, leave only wiring in the component" — it is why 30 of the 66 lib files are tests.

### Fuzzy picker scorer  `id: web-shell.fuzzy`
- **Surface:** Web dashboard
- **Where:** Invisible; ranks entries in the model picker and other filter boxes.
- **What it does:** Matches a query as an ordered subsequence (`g4o` matches `gpt-4o`), scores match
  quality, and returns the matched character indices for highlighting.
- **How it works:** `lib/fuzzy.ts:26-192`. `WORD_BOUNDARY = /[-_/.\s]/`; `isBoundary` also treats a
  lower→upper transition as a boundary. `fuzzyScore(target, query)`: +1 per matched char, **+5** when
  contiguous with the previous match, **−min(gap,3)** otherwise, **+3** on a word boundary, **+5** when
  matching index 0, **+8** when the whole query is a contiguous prefix, **+20** on an exact full match,
  and **−0.01 × target.length** as a length tiebreak; returns `null` when the query is not a
  subsequence, and `{score:0, positions:[]}` for an empty query. `fuzzyScoreMulti` splits the query on
  whitespace with AND semantics, summing scores and unioning positions. `fuzzyRank(items, query, toText)`
  filters + sorts by score descending with the original index as a stable tiebreak; an empty query
  returns every item in original order.
- **Inputs / options:** `(target, query)` / `(items, query, toText)`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** The header notes this is a logically identical copy of
  `ui-tui/src/lib/fuzzy.ts` (only formatting differs) and that the TUI copy carries the vitest suite,
  so behavioural changes must be validated there.
- **Rebuild notes:** Deduplicate the two copies into the shared package rather than keeping a
  "keep in sync" comment.

### Clipboard helper  `id: web-shell.clipboard`
- **Surface:** Web dashboard
- **Where:** Invisible; behind every "Copy" affordance (CLI command copy, OAuth code copy, chat copy).
- **What it does:** Copies text with a graceful fallback for insecure contexts and browsers that deny
  the async clipboard API.
- **How it works:** `lib/clipboard.ts:1-56`. Tries `navigator.clipboard.writeText` only when
  `window.isSecureContext`; on failure or absence it creates a hidden readonly `<textarea>`
  (`position:fixed; top:-1000px; left:-1000px; opacity:0`), saves and restores every existing
  `Selection` range around the copy, selects the full value, calls `document.execCommand("copy")`,
  and removes the node in a `finally`. Returns `true`/`false`.
- **Inputs / options:** `(text: string)`.
- **Outputs / side effects:** Clipboard contents; transient DOM node; selection is restored exactly.
- **Config / env:** n/a.
- **Edge cases / guards:** SSR-safe (`typeof document === "undefined"` → `false`).
- **Rebuild notes:** Always restore the user's selection — the naive fallback destroys it.

### Shared modal shell classes  `id: web-shell.modal-shell`
- **Surface:** Web dashboard
- **Where:** Invisible; the class strings used by dashboard modals (model picker, toolset drawer,
  MoA editor).
- **What it does:** Gives every dashboard modal an opaque panel and a consistent backdrop z-band.
- **How it works:** `lib/dashboard-modal-shell.ts:15-29`.
  `DASHBOARD_MODAL_BACKDROP = "fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"`;
  `DASHBOARD_MODAL_PANEL = "relative w-full border border-border bg-card shadow-2xl"`.
  `shouldCloseOuterModalOnEscape(nestedPickerOpen)` returns `!nestedPickerOpen` so an outer modal
  hosting a nested picker (MoA → ModelPickerDialog) ignores Escape while the picker owns that key.
  The header records why: page `<Card>` defaults to `bg-background-base/80` (glass), which as a modal
  panel lets the page bleed through and kills readability, especially on Cyberpunk and mobile; and
  that callers **must** `createPortal(..., document.body)` because `z-[100]` alone cannot escape the
  content column's `relative z-2` stacking context.
- **Inputs / options:** n/a.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Note the `ConfirmDialog` in `components/` uses `z-[200]`, one band above
  these, so a confirm always sits over a picker.
- **Rebuild notes:** Publish the z-index bands as named constants; portal every overlay.

### `useModalBehavior` hook  `id: web-shell.use-modal-behavior`
- **Surface:** Web dashboard
- **Where:** Invisible; standard modal keyboard/scroll behaviour.
- **What it does:** While `open`: Escape calls `onClose`, body scroll is locked, and focus returns to
  the previously focused element on close.
- **How it works:** `hooks/useModalBehavior.ts:11-44`. Captures `document.activeElement` on open,
  adds a `keydown` listener that `preventDefault()`s Escape, sets `document.body.style.overflow =
  "hidden"` (restoring the previous value), and calls `prevActive?.focus?.()` in cleanup. Returns a
  `containerRef` "for optional future focus trapping" — focus trapping is **not** implemented.
- **Inputs / options:** `{open, onClose}`.
- **Outputs / side effects:** Body scroll lock; focus restoration.
- **Config / env:** n/a.
- **Edge cases / guards:** No focus trap, no `inert` on the background, no aria-modal enforcement.
- **Rebuild notes:** Add a real focus trap; the hook is the right place for it.

### API method index  `id: web-shell.api-method-index`
- **Surface:** API
- **Where:** `web/src/lib/api.ts` exports a single `api` object (`api.ts:341`), also handed to plugins
  as `window.__HERMES_PLUGIN_SDK__.api`.
- **What it does:** Names every dashboard endpoint the SPA can call. Endpoint semantics belong to the
  owning page shards; this is the complete surface so nothing is missed.
- **How it works:** Methods in declaration order (198 entries):
  `buildWsUrl`, `getStatus`, `getAuthMe`, `logout`, `getSessions`, `getSessionMessages`,
  `getSessionDetail`, `getSessionLatestDescendant`, `deleteSession`, `getEmptySessionsCount`,
  `deleteEmptySessions`, `bulkDeleteSessions`, `renameSession`, `getSessionStats`,
  `exportSessionUrl`, `importSessions`, `pruneSessions`, `listFiles`, `readFile`, `uploadFile`,
  `createDirectory`, `deleteFile`, `getLogs`, `getAnalytics`, `getModelsAnalytics`, `getConfig`,
  `getDefaults`, `getSchema`, `getModelInfo`, `getModelOptions`, `getAuxiliaryModels`, `getMoaModels`,
  `saveMoaModels`, `setModelAssignment`, `saveConfig`, `getConfigRaw`, `saveConfigRaw`, `getEnvVars`,
  `setEnvVar`, `deleteEnvVar`, `revealEnvVar`, `getCronJobs`, `getCronDeliveryTargets`,
  `createCronJob`, `pauseCronJob`, `updateCronJob`, `resumeCronJob`, `triggerCronJob`,
  `deleteCronJob`, `getAutomationBlueprints`, `instantiateAutomationBlueprint`, `getProfiles`,
  `getActiveProfile`, `setActiveProfile`, `createProfile`, `updateProfileDescription`,
  `describeProfileAuto`, `setProfileModel`, `renameProfile`, `deleteProfile`,
  `getProfileSetupCommand`, `getProfileSoul`, `updateProfileSoul`, `getSkills`, `toggleSkill`,
  `getSkillContent`, `createSkill`, `updateSkillContent`, `getToolsets`, `toggleToolset`,
  `getToolsetConfig`, `selectToolsetProvider`, `saveToolsetEnv`, `runToolsetPostSetup`,
  `searchSessions`, `getOAuthProviders`, `disconnectOAuthProvider`, `startOAuthLogin`,
  `submitOAuthCode`, `pollOAuthSession`, `cancelOAuthSession`, `getMessagingPlatforms`,
  `updateMessagingPlatform`, `testMessagingPlatform`, `startTelegramOnboarding`,
  `getTelegramOnboardingStatus`, `applyTelegramOnboarding`, `cancelTelegramOnboarding`,
  `startWhatsAppOnboarding`, `getWhatsAppOnboardingStatus`, `applyWhatsAppOnboarding`,
  `cancelWhatsAppOnboarding`, `restartGateway`, `updateHermes`, `checkHermesUpdate`,
  `getActionStatus`, `getPlugins`, `rescanPlugins`, `getPluginsHub`, `installAgentPlugin`,
  `enableAgentPlugin`, `disableAgentPlugin`, `updateAgentPlugin`, `removeAgentPlugin`,
  `savePluginProviders`, `setPluginVisibility`, `getThemes`, `setTheme`, `getFontPref`,
  `setFontPref`, `getMcpServers`, `addMcpServer`, `authMcpServer`, `getMcpOAuthFlow`,
  `removeMcpServer`, `testMcpServer`, `setMcpServerEnabled`, `getMcpCatalog`,
  `installMcpCatalogEntry`, `getPairing`, `approvePairing`, `revokePairing`, `clearPendingPairing`,
  `getWebhooks`, `enableWebhooks`, `createWebhook`, `deleteWebhook`, `setWebhookEnabled`,
  `getCredentialPool`, `addCredentialPoolEntry`, `removeCredentialPoolEntry`, `getMemory`,
  `getMemoryProviderConfig`, `updateMemoryProviderConfig`, `setupMemoryProvider`, `setMemoryProvider`,
  `resetMemory`, `startGateway`, `stopGateway`, `runDoctor`, `runSecurityAudit`, `runBackup`,
  `downloadBackup`, `runImport`, `runImportUpload`, `getHooks`, `createHook`, `deleteHook`,
  `getSystemStats`, `getCurator`, `setCuratorPaused`, `runCurator`, `getPortal`, `runPromptSize`,
  `runDump`, `runConfigMigrate`, `runDebugShare`, `getCheckpoints`, `pruneCheckpoints`,
  `installSkillFromHub`, `uninstallSkillFromHub`, `updateSkillsFromHub`, `searchSkillsHub`,
  `getSkillHubSources`, `previewSkillFromHub`, `scanSkillFromHub`.
  Shell-owned members of that list: `getStatus`, `getAuthMe`, `logout`, `getConfig` (analytics gate),
  `getThemes`, `setTheme`, `getFontPref`, `setFontPref`, `getPlugins`, `rescanPlugins`,
  `setPluginVisibility`, `getProfiles`, `getActiveProfile`, `restartGateway`, `updateHermes`,
  `checkHermesUpdate`, `getActionStatus`, `buildWsUrl`.
- **Inputs / options:** per method (documented in the owning shard).
- **Outputs / side effects:** per method.
- **Config / env:** n/a.
- **Edge cases / guards:** `exportSessionUrl` returns a URL string rather than performing a fetch.
- **Rebuild notes:** One flat client object keeps the plugin SDK surface trivial to expose; it is also
  2667 lines, so a better version would split it per domain and generate the response types from the
  server's OpenAPI schema.

---

## 6. Shared components (`web/src/components/`)

The directory holds 27 components plus 2 colocated test files (`MemoryPressureBanner.test.tsx`, `ChatSidebar.test.tsx`). Shell-owned components
(`SidebarFooter`, `SidebarStatusStrip`, `ProfileSwitcher`, `ProfileScopeBanner`,
`MemoryPressureBanner`, `AuthWidget`, `ThemeSwitcher`, `LanguageSwitcher`) are documented in §2–§3.
The remaining ones are catalogued here; where a component's *page* behaviour belongs to a sibling
shard, that shard is named.

### `ConfirmDialog` (dashboard-local)  `id: web-shell.cmp-confirm-dialog`
- **Surface:** Web dashboard
- **Where:** Portalled overlay. Default button labels are the literals `Cancel` and `Confirm`;
  while `loading` the confirm button shows `…`.
- **What it does:** Modal yes/no confirmation with an optional destructive treatment.
- **How it works:** `components/ConfirmDialog.tsx:19-122`. `createPortal(..., document.body)`.
  Backdrop `fixed inset-0 z-[200] flex items-center justify-center bg-background/85 p-4`; clicking
  the backdrop itself (`e.target === e.currentTarget`) cancels. Panel is
  `relative w-full max-w-md border border-border bg-card shadow-2xl` with the `themedBody` font class.
  `role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title"` and
  `aria-describedby="confirm-dialog-desc"` when a description is given. On open it focuses the
  element with `[data-confirm]` (the confirm button), locks `body.style.overflow`, listens for
  `Escape` (preventDefault + cancel), and restores focus to the previously active element on close.
  Destructive mode adds a lucide `AlertTriangle` in `text-destructive` and marks the confirm button
  `destructive`. Title is `font-mondwest text-display text-base tracking-wider`; the description is
  `text-xs text-muted-foreground leading-relaxed whitespace-pre-line`.
- **Inputs / options:** `open`, `title`, `description?`, `confirmLabel="Confirm"`,
  `cancelLabel="Cancel"`, `destructive=false`, `loading=false`, `onConfirm`, `onCancel`.
- **Outputs / side effects:** Body scroll lock; focus move and restore.
- **Config / env:** n/a.
- **Edge cases / guards:** Note this is a *second* confirm dialog: the shell's Restart/Update dialogs
  use the Nous DS `ConfirmDialog` from `@nous-research/ui`, while pages use this local one.
- **Rebuild notes:** One dialog primitive would be better than two; keep the `z-[200]` band above
  pickers.

### `DeleteConfirmDialog`  `id: web-shell.cmp-delete-confirm`
- **Surface:** Web dashboard
- **Where:** Every destructive confirmation on the pages (delete session, delete cron job, delete
  profile, clear key, …).
- **What it does:** Thin i18n-aware wrapper that pre-fills the destructive styling and the
  `Delete` / `Cancel` labels.
- **How it works:** `components/DeleteConfirmDialog.tsx:126-162`. Wraps the **DS**
  `ConfirmDialog` from `@nous-research/ui/ui/components/confirm-dialog` with `destructive` always
  true, `confirmLabel ?? t.common.delete` (`Delete`) and `cancelLabel ?? t.common.cancel` (`Cancel`).
- **Inputs / options:** `open`, `title`, `description?`, `loading`, `onConfirm`, `onCancel`,
  `confirmLabel?`, `cancelLabel?`.
- **Outputs / side effects:** per the DS dialog.
- **Config / env:** n/a.
- **Edge cases / guards:** `loading` is required here (not optional) so callers cannot forget the busy
  state.
- **Rebuild notes:** Wrap once, use everywhere — it is why every delete confirmation in the app reads
  identically.

### `ModelReloadConfirm`  `id: web-shell.cmp-model-reload-confirm`
- **Surface:** Web dashboard
- **Where:** After choosing a new main model, from either the chat sidebar picker or the Models page.
  Title verbatim `Switch model?`; confirm label `Reload`.
- **What it does:** Explains that switching the main model needs a fresh chat and offers a full page
  reload.
- **How it works:** `components/ModelReloadConfirm.tsx:179-202`. Renders the local `ConfirmDialog`
  with `open={model !== null}`, default description
  `` `Switching to ${model ?? ""} starts a fresh chat. Your current chat stays in your Sessions list and the agent's memory is kept. Reload now to apply it?` ``
  (overridable via the `description` prop for the Models-page phrasing) and
  `onConfirm={() => window.location.reload()}`. The header records why a reload rather than a hot
  swap: "the in-place hot-swap and partial remount both proved unreliable".
- **Inputs / options:** `model: string | null`, `description?`, `onCancel`.
- **Outputs / side effects:** Full page reload on confirm.
- **Config / env:** n/a.
- **Edge cases / guards:** These strings are **not** localised (hard-coded English).
- **Rebuild notes:** Be explicit that a model switch costs the running chat; sharing the dialog keeps
  both entry points honest.

### `Markdown`  `id: web-shell.cmp-markdown`
- **Surface:** Web dashboard
- **Where:** Session transcript bubbles on the Sessions page (shard web-a).
- **What it does:** Renders LLM output as HTML without a CommonMark dependency, with optional
  search-term highlighting and a streaming caret.
- **How it works:** `components/Markdown.tsx:12-383`.
  - **Block grammar** (`parseBlocks`): fenced code blocks opened by a line matching `^```(\w*)` and
    closed by the next line starting with ` ``` `; ATX headings `#`–`####`
    (`^(#{1,4})\s+(.+)`); horizontal rule `^[-*_]{3,}\s*$`; unordered list `^[-*+]\s`; ordered list
    `^\d+[.)]\s`; blank lines skipped; anything else accumulates into a paragraph until a blank or
    another block marker.
  - **Inline grammar** (`parseInline`) with this priority: inline code (backticks) > link `[t](u)` >
    bold `**…**` > italic `*…*` > bare `https?://…` > newline (`<br/>`). Single regex at
    `Markdown.tsx:245-246`.
  - **Link safety:** only `http:`, `https:` and `mailto:` hrefs render as anchors; anything else
    (`javascript:`, `data:`, `vbscript:`) degrades to plain text, "so a crafted link in agent/message
    content can't execute on click". Anchors are `target="_blank" rel="noreferrer"`.
  - **Highlighting** (`HighlightedText`): builds a case-insensitive alternation regex from the
    escaped `highlightTerms` and wraps matches.
  - **Streaming caret:** when `streaming`, an `aria-hidden` `inline-block w-[0.5em] h-[1em] ml-0.5
    align-[-0.15em] bg-foreground/50 animate-pulse` span is appended to the last block (or rendered
    alone when there are no blocks) so it hugs the final character instead of wrapping.
  - Root wrapper: `text-sm text-foreground leading-relaxed space-y-2`.
- **Inputs / options:** `content: string`, `highlightTerms?: string[]`, `streaming?: boolean`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Not a full CommonMark parser (no tables, blockquotes, nested lists,
  reference links, or HTML passthrough) — deliberately "optimized for typical assistant message
  patterns".
- **Rebuild notes:** A hand-rolled renderer is defensible here because it makes the link allow-list
  trivially auditable; keep that property if you swap in a library.

### `AutoField` (schema-driven config input)  `id: web-shell.cmp-autofield`
- **Surface:** Web dashboard
- **Where:** Config page form rows (`pages/ConfigPage.tsx:421`) — page behaviour in shards config-a /
  config-b.
- **What it does:** Renders the right input widget for one config key based on its schema type,
  including a nested editor for object/array-of-object values.
- **How it works:** `components/AutoField.tsx:85-206`. Label is derived from the last dotted segment:
  underscores become spaces, then Title Case
  (`rawLabel.replace(/_/g," ").replace(/\b\w/g, c => c.toUpperCase())`).
  `FieldHint` (`AutoField.tsx:6-18`) shows the dotted key in `text-xs font-mono text-text-tertiary`
  (only when the key contains a `.`) and the schema `description` in `text-xs text-text-secondary`.
  Type dispatch, in order:
  - object value, or array containing objects → bordered group with `NestedValueEditor`
    (`AutoField.tsx:31-83`, recursive key/value editor over `formatScalar`);
  - `boolean` → DS `Switch` on a label/description row;
  - `select` → DS `Select` over `schema.options`, rendering an empty option's text as `(none)`;
  - `number` → `<Input type="number">` where an empty string commits `0` and `NaN` is ignored;
  - `text` → `<textarea>` `min-h-[80px] w-full border border-input bg-transparent px-3 py-2 text-sm …`;
  - `list` → `<Input placeholder="comma-separated values">` that joins with `", "` and splits on `,`
    with trim + drop-empty;
  - default → plain `<Input>`.
- **Inputs / options:** `{schemaKey, schema, value, onChange}`.
- **Outputs / side effects:** Calls `onChange(nextValue)`.
- **Config / env:** Schema comes from `GET /api/config/schema`.
- **Edge cases / guards:** The number branch silently coerces `""` to `0`, which cannot express
  "unset".
- **Rebuild notes:** Schema-driven fields are what let 785 config keys share one page; add an explicit
  null/unset representation.

### `ModelInfoCard`  `id: web-shell.cmp-model-info-card`
- **Surface:** Web dashboard
- **Where:** **Not currently mounted** — no page or component imports it (only referenced in comments
  in `ChatSidebar.tsx:142` and `ReasoningPicker.tsx:6`). It is dead-but-shipped code in this tag.
- **What it does:** Would render the effective model's provider, context length and capability badges.
- **How it works:** `components/ModelInfoCard.tsx:15-112`. Props `{currentModel, refreshKey = 0}`.
  Refetches `api.getModelInfo()` whenever `` `${currentModel}:${refreshKey}` `` changes (guarded by a
  `lastFetchKeyRef` so the same key never refetches); shows a `<Spinner/>` row with
  `text-xs text-muted-foreground` while loading and renders nothing on error.
- **Inputs / options:** `currentModel: string`, `refreshKey?: number`.
- **Outputs / side effects:** `GET /api/model/info`.
- **Config / env:** n/a.
- **Edge cases / guards:** Bails out entirely when `currentModel` is empty.
- **Rebuild notes:** Either mount it or delete it; unmounted components still cost bundle size and
  review attention.

### `PlatformsCard`  `id: web-shell.cmp-platforms-card`
- **Surface:** Web dashboard
- **Where:** Sessions page overview (`pages/SessionsPage.tsx:2108`). Card title is
  `Connected Platforms` (`i18n: status.connectedPlatforms`) with a lucide `Radio` icon.
- **What it does:** Lists each configured messaging platform with a state badge and icon.
- **How it works:** `components/PlatformsCard.tsx:8-108`. State to badge map:
  `connected` → tone `success`, label `Connected` (`i18n: status.connected`);
  `disconnected` → tone `warning`, label `Disconnected` (`i18n: status.disconnected`);
  `disabled` → tone `outline`, label `Disabled` (`i18n: status.disabled`, with the literal `"Disabled"`
  as fallback); `fatal` → tone `destructive`, label `Error` (`i18n: status.error`). Unknown states
  fall back to tone `outline` with the raw state string as the label. Icon per state: `Wifi` when
  connected, the error icon when `fatal`, otherwise the neutral icon (`PlatformsCard.tsx:38-45`).
- **Inputs / options:** `platforms: [name, info][]`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Unknown states render rather than crash.
- **Rebuild notes:** One state to (tone,label,icon) table; render unknown states verbatim.

### `OAuthProvidersCard`  `id: web-shell.cmp-oauth-providers-card`
- **Surface:** Web dashboard
- **Where:** Keys page (`pages/EnvPage.tsx:932`). Card title `Provider Logins (OAuth)`
  (`i18n: oauth.title` / `oauth.providerLogins`).
- **What it does:** Lists OAuth-capable LLM providers with connection state, expiry countdown, and
  Login / Disconnect / Copy-CLI-command actions.
- **How it works:** `components/OAuthProvidersCard.tsx:52-287`. Uses the `oauth.*` i18n namespace
  (36 keys, §4) — description `{connected} of {total} OAuth providers connected. Use Login for
  dashboard-supported flows; CLI commands remain available for external or fallback setup.`,
  states `Connected` / `Expired` / `Not connected. Use Login when available, or run {command} in a
  terminal.`, empty state `No OAuth-capable providers detected.`, actions `Login`, `Disconnect`,
  `Connect`, `Copy`, `Copy CLI command (for external / fallback)`, `Managed externally`, and the
  expiry helper `formatExpiresAt` (`OAuthProvidersCard.tsx:30-50`) which returns `expired` for a past
  timestamp and feeds `expires in {time}` / `Session expires in {time}`. Icons: `ShieldCheck`,
  `ShieldOff`, `ExternalLink`, `RefreshCw`, `Terminal`. Props `{onError?, onSuccess?}` bubble toasts
  to the page.
- **Inputs / options:** Per-provider Login / Disconnect / Copy buttons.
- **Outputs / side effects:** `GET /api/providers/oauth`, provider connect/disconnect endpoints; opens
  `OAuthLoginModal`.
- **Config / env:** profile-scoped (`/api/providers/oauth` is in `PROFILE_SCOPED_PREFIXES`).
- **Edge cases / guards:** Page behaviour owned by shard config-b.
- **Rebuild notes:** Always keep the CLI fallback visible next to the GUI flow.

### `OAuthLoginModal`  `id: web-shell.cmp-oauth-login-modal`
- **Surface:** Web dashboard
- **Where:** Opened from the OAuth card's `Login` button.
- **What it does:** Drives a provider login end to end — PKCE browser flow, device-code flow, or
  external-CLI instructions — with a live phase readout.
- **How it works:** `components/OAuthLoginModal.tsx:28-395`. Phase machine
  (`OAuthLoginModal.tsx:19-27`): `idle` → `starting` → `awaiting_user` → `submitting` → `polling` →
  `approved` | `error`. Flow labels come from `oauth.flowLabels`: `Browser login (PKCE)`,
  `Device code`, `External CLI`. Copy for each phase is the `oauth.*` namespace:
  `Initiating login flow…`, `Waiting for you to authorize in the browser…`,
  `Exchanging code for tokens…`, `Connected! Closing…`, `Login failed.`,
  `Session expired. Click Retry to start a new login.`, `Re-open auth page`,
  `Re-open verification page`, `Submit code`, `Paste authorization code (with #state suffix is fine)`,
  `A new tab opened. Enter this code if prompted:`, the three PKCE steps
  (`A new tab opened to claude.ai. Sign in and click Authorize.`,
  `Copy the authorization code shown after authorizing.`, `Paste it below and submit.`),
  `Copy code`, `Copied ✓`, and
  `Could not copy automatically. Select the code and copy it manually.`. It keeps `isMounted`,
  `pollTimer` and `copyResetTimer` refs and a `secondsLeft` countdown.
- **Inputs / options:** `{provider, onClose, onSuccess, onError}`; the code textarea; Submit / Retry /
  Copy / Re-open buttons.
- **Outputs / side effects:** `api.startOAuthLogin`, `api.submitOAuthCode`, `api.pollOAuthSession`,
  `api.cancelOAuthSession`; opens a new browser tab.
- **Config / env:** n/a.
- **Edge cases / guards:** Timers are cleared on unmount via `isMounted`.
- **Rebuild notes:** Model the flow as an explicit phase enum; owned by shard config-b for the page
  integration.

### `HermesConsoleModal`  `id: web-shell.cmp-hermes-console`
- **Surface:** Web dashboard
- **Where:** System page (`pages/SystemPage.tsx:706`). Close control `aria-label` `Close console`.
- **What it does:** An in-browser `hermes>` command console — a real xterm.js terminal wired to
  `/api/console` that runs CLI commands with confirmation prompts for destructive ones.
- **How it works:** `components/HermesConsoleModal.tsx:101-537`.
  - Transport: `api.buildWsUrl("/api/console", params)` (`HermesConsoleModal.tsx:403`), so it uses the
    same ticket/token auth as every other dashboard socket.
  - Frame protocol (`ConsoleFrame`, `HermesConsoleModal.tsx:18-50`): `{type:"ready", profile?, prompt?}`,
    `{type:"output", data?, stream?}`, `{type:"error", message?}`,
    `{type:"confirm_required", command?, message?, prompt?}`, `{type:"complete", …}`.
  - Connection states: `connecting` | `ready` | `running` | `closed` | `error`.
  - Line editing implemented by hand against xterm: printable input appends; DEL (`\x7f`) backspaces
    by writing `"\b \b"`; `\x1b[A` / `\x1b[B` walk a command-history array; Ctrl-C (`\x03`) prints
    `^C\r\n` and cancels; Ctrl-L (`\x0c`) clears the screen. `redrawInput` rewrites the current line
    with `\r\x1b[2K` + prompt + line.
  - Confirmation: a `confirm_required` frame switches the input prompt to `Confirm? [y/N] ` and the
    answer is sent back as a `confirm` or `cancel` frame.
  - Terminal palette is built from the active theme
    (`buildTerminalTheme(background, foreground)`, defaults `#000000` / `#f0e6d2`) with an explicit
    ANSI set: `#ff5f67`, `#5fffb0`, `#ffd166`, `#7aa2ff`, `#d597ff`, `#58e6ff`, `#ffffff`,
    `#666666`, `#ff8b90`, `#8dffc8`, `#ffe08a`, `#9dbaff`, `#e4b7ff`, `#8ef0ff`.
  - Verbatim terminal messages: `\x1b[2mConnecting to Hermes Console...\x1b[0m`,
    `\x1b[31mConsole is not connected.\x1b[0m`, `\x1b[31mCommand timed out.\x1b[0m`,
    `\x1b[31mConsole websocket error.\x1b[0m`, `\x1b[31mMalformed console frame.\x1b[0m`,
    `\x1b[33mCancelled.\x1b[0m`, `Command failed.`, and the pre-handshake failure hint
    `Console connection failed before the server handshake. Check that this dashboard is connected to a backend with /api/console.`
  - Uses `useModalBehavior({open, onClose})` for Escape + scroll lock + focus restore, and
    `useProfileScope()` so the console runs under the selected management profile (default label
    `current`).
- **Inputs / options:** `{open, onClose}`; typed commands; Enter, Backspace, Up/Down, Ctrl-C, Ctrl-L,
  `y`/`n` at a confirm prompt.
- **Outputs / side effects:** Runs real CLI commands server-side.
- **Config / env:** management profile scope.
- **Edge cases / guards:** A malformed frame is reported rather than ignored; commands time out.
- **Rebuild notes:** Frame-typed console protocol with an explicit `confirm_required` round trip is
  the right shape for a remote CLI; page integration is owned by the System-page shard.

### `SkillEditorDialog`  `id: web-shell.cmp-skill-editor`
- **Surface:** Web dashboard
- **Where:** Skills page — "New skill" and "Edit SKILL.md" (shard web-b).
- **What it does:** Creates or edits a `SKILL.md` from the browser, for headless/VPS users whose only
  alternative is SSH plus a terminal editor.
- **How it works:** `components/SkillEditorDialog.tsx:37-215`. Create mode POSTs name + optional
  category + body; edit mode loads the existing raw `SKILL.md` and rewrites it. Validation
  (frontmatter, name, size) happens server-side through the same path the agent's `skill_manage` tool
  uses, and errors are rendered inline. The create template (`CREATE_TEMPLATE`,
  `SkillEditorDialog.tsx:19-35`) is verbatim: a YAML frontmatter block containing
  `name: my-skill` and `description: One-line description of when to use this skill.`, followed by
  `# My Skill` and `Numbered steps, exact commands, and pitfalls go here.`.
- **Inputs / options:** `{open, editName: string|null, …}` (create when `editName` is null).
- **Outputs / side effects:** `api.createSkill` / `api.updateSkillContent`.
- **Config / env:** profile-scoped via `/api/skills`.
- **Edge cases / guards:** Server-side validation is authoritative.
- **Rebuild notes:** Ship a starter template; never client-validate frontmatter.

### `ToolsetConfigDrawer`  `id: web-shell.cmp-toolset-drawer`
- **Surface:** Web dashboard
- **Where:** Skills page → a toolset tile (shard web-b).
- **What it does:** The dashboard equivalent of selecting a toolset in the `hermes tools` curses UI —
  toggle the toolset, pick a provider, enter API keys, and run a provider's post-setup install hook
  (npm/pip/binary) with a live log tail.
- **How it works:** `components/ToolsetConfigDrawer.tsx:20-460`. Props
  `{toolset: ToolsetInfo, profile?: string, onClose, onChanged}` — `onChanged` fires after any
  toggle/provider/key change so the parent grid refreshes. Uses the DS `useToast`.
- **Inputs / options:** toolset toggle, provider select, per-key inputs, post-setup run button.
- **Outputs / side effects:** `api.toggleToolset`, `api.selectToolsetProvider`, `api.saveToolsetEnv`,
  `api.runToolsetPostSetup`.
- **Config / env:** profile-scoped (`/api/tools/toolsets`).
- **Edge cases / guards:** Must be portalled (see `web-shell.modal-shell`).
- **Rebuild notes:** Pair each provider with its install hook and stream the log — otherwise a failed
  npm install is invisible.

### `ScheduleBuilder`  `id: web-shell.cmp-schedule-builder`
- **Surface:** Web dashboard
- **Where:** Cron page create/edit forms (shard web-b).
- **What it does:** Replaces "type a cron expression" with mode-appropriate inputs while still
  emitting one backend-compatible schedule string.
- **How it works:** `components/ScheduleBuilder.tsx:39-273`. Fully controlled: the parent owns
  `ScheduleBuilderState` and derives the string with `buildScheduleString` (`lib/schedule.ts`).
  Mode-specific slots (`timeOfDay`, `weekdays`, …) are preserved across mode switches so flipping back
  does not erase work. "Custom" is a first-class mode rather than an advanced toggle, "keeping
  power-user workflows discoverable without making everyone scroll past it". All labels come from
  `cron.scheduleModes.*` (§4), including the weekday abbreviation array
  `["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]`.
- **Inputs / options:** `{value: ScheduleBuilderState, onChange}`; modes `interval`, `daily`,
  `weekly`, `monthly`, `once`, `custom`; interval units `minutes`/`hours`/`days`;
  `TimeOfDayField` sub-component (`ScheduleBuilder.tsx:237`).
- **Outputs / side effects:** `onChange(nextState)`.
- **Config / env:** n/a.
- **Edge cases / guards:** Emits `(incomplete)` (`cron.scheduleModes.previewEmpty`) until the state
  produces a valid expression.
- **Rebuild notes:** Keep per-mode state so mode switching is non-destructive.

### `AutomationBlueprints`  `id: web-shell.cmp-automation-blueprints`
- **Surface:** Web dashboard
- **Where:** Cron page gallery (shard web-b).
- **What it does:** One-click instantiation of pre-authored cron automations from a server-provided
  blueprint catalog, with a generated form per blueprint.
- **How it works:** `components/AutomationBlueprints.tsx:16-225`. `initialValues(blueprint)` seeds each
  field with its `default ?? ""`. `FieldInput` renders a DS `Select` for `enum` and `weekdays` field
  types and an input otherwise. `BlueprintCard` renders one blueprint; the container takes
  `{profile, onCreated?}`.
- **Inputs / options:** Per-blueprint form fields; a create action.
- **Outputs / side effects:** `api.getAutomationBlueprints`, `api.instantiateAutomationBlueprint`.
- **Config / env:** cron profile.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Server-declared field schemas keep the gallery data-driven.

### `ChatSidebar`  `id: web-shell.cmp-chat-sidebar`
- **Surface:** Web dashboard
- **Where:** Right of the terminal on `/chat` (shard web-a owns the behaviour).
- **What it does:** Structured-events panel next to the xterm pane: connection badge, model card and
  picker, reasoning picker, credential warnings, live session title.
- **How it works:** `components/ChatSidebar.tsx:56-584`. Two WebSockets by design:
  (1) a **JSON-RPC sidecar** via `GatewayClient` to `/api/ws`, used only for connection state and
  credential warnings — deliberately independent of the PTY pane's session; the model badge instead
  reads `/api/model/info` over REST and the picker writes `/api/model/set` then offers a reload;
  (2) an **event subscriber** on `/api/events?channel=…`, passive, receiving every dispatcher emit
  from the PTY-side `tui_gateway.entry` that the dashboard fanned out — used for `session.info`
  (live chat title) and `dashboard.new_session_requested`. The `channel` id ties the listener to the
  same tab's PTY child. Transient drops auto-reconnect with exponential backoff
  (`lib/events-reconnect.ts`); auth rejections are terminal. Exports
  `sidecarSessionCreateParams(profile?)` (`ChatSidebar.tsx:104`). Everything is best-effort: WS
  failures surface in the badge/banner and the terminal keeps working.
- **Inputs / options:** props at `ChatSidebar.tsx:88-102`.
- **Outputs / side effects:** two WebSockets; REST model reads/writes.
- **Config / env:** management profile.
- **Edge cases / guards:** 455-line test file `components/ChatSidebar.test.tsx`.
- **Rebuild notes:** Separate "control plane" (RPC) from "telemetry" (events) sockets.

### `ChatSessionList`  `id: web-shell.cmp-chat-session-list`
- **Surface:** Web dashboard
- **Where:** Chat page side panel (shard web-a).
- **What it does:** A ChatGPT-style conversation switcher listing the most recent sessions for the
  active management profile.
- **How it works:** `components/ChatSessionList.tsx:33-260`. `SESSION_LIMIT = 30`. Selecting a row
  sets `/chat?resume=<id>`; `ChatPage` treats the resume target as part of the PTY identity, so the
  change tears down the terminal child and respawns it resuming that conversation. "New session"
  clears the resume param. Deliberately **read-only** (select + new): delete, rename, export and bulk
  actions live on the Sessions page, "avoiding duplicating that machinery". A failed fetch surfaces a
  small inline error with a retry affordance and the terminal keeps working. `rowLabel(session, untitled)`
  (`ChatSessionList.tsx:50`) falls back to `Untitled session` (`i18n: sessions.untitledSession`).
- **Inputs / options:** `{activeSessionId, profile?, className?, onPicked?}`.
- **Outputs / side effects:** URL `?resume=` change, hence a PTY respawn.
- **Config / env:** management profile scopes the listing.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Keep the switcher navigational; do not duplicate session management.

### `ModelPickerDialog`  `id: web-shell.cmp-model-picker`
- **Surface:** Web dashboard
- **Where:** Chat sidebar and Models page / Config settings (shards web-a and config-a).
- **What it does:** Two-stage model chooser — pick provider, then model — mirroring
  `ui-tui/src/components/modelPicker.tsx`.
- **How it works:** `components/ModelPickerDialog.tsx:37-680`. Two invocation modes:
  (1) **chat-session mode** (pass `gw` + `sessionId`) loads options via the `model.options` JSON-RPC
  call and applies via `config.set`, so expensive-model confirmation can happen before the switch;
  (2) **standalone mode** (pass `loader` + `onApply`) fetches options over REST and calls
  `onApply(provider, model, persistGlobal)`, letting the Models page reuse the UI with no open chat
  PTY. Sub-components: `ProviderColumn` (`:498`), `ModelColumn` (`:566`), `CurrentTag` (`:638`),
  `HighlightedText` (`:651`). Types include `ExpensiveModelConfirmResponse` (`:52`) and
  `PendingExpensiveConfirm` (`:62`) for the confirmation round trip. Filtering uses
  `lib/model-picker-filter.ts`, `lib/model-search-text.ts` and `lib/fuzzy.ts`.
- **Inputs / options:** props at `ModelPickerDialog.tsx:69-92`; search box; provider/model lists;
  a "persist globally" option in standalone mode.
- **Outputs / side effects:** `config.set` RPC or `api.setModelAssignment`.
- **Config / env:** management profile.
- **Edge cases / guards:** Must be portalled; owns Escape while open (see
  `shouldCloseOuterModalOnEscape`).
- **Rebuild notes:** Two-column provider-then-model with fuzzy search and a cost confirmation gate.

### `ReasoningPicker`  `id: web-shell.cmp-reasoning-picker`
- **Surface:** Web dashboard
- **Where:** Chat sidebar (shard web-a).
- **What it does:** Sets the main model's reasoning effort from the dashboard, closing the parity gap
  with the desktop app's composer radio (the dashboard previously only showed a read-only
  "Reasoning" capability badge).
- **How it works:** `components/ReasoningPicker.tsx:33-125`. Persists to `config.yaml` at
  `agent.reasoning_effort` — the same key the TUI's `/reasoning <level>` command and the desktop radio
  write — by reading the whole config and writing it back (the established single-key pattern on the
  dashboard). The running chat adopts the change on the next `/new` or page reload; the component
  surfaces that hint rather than forcing a reload. Options come from `lib/reasoning-effort.ts`
  (`EFFORT_OPTIONS`, `VALID_EFFORTS`, `normalizeEffort`).
- **Inputs / options:** `{currentModel, profile?, refreshKey?}`; the effort radio.
- **Outputs / side effects:** `api.saveConfig` write of `agent.reasoning_effort`.
- **Config / env:** `agent.reasoning_effort`; profile-scoped.
- **Edge cases / guards:** Re-reads when the model changes (a different model may support different
  levels).
- **Rebuild notes:** Write the same key every surface writes; say plainly when the change takes effect.

### `SlashPopover`  `id: web-shell.cmp-slash-popover`
- **Surface:** Web dashboard
- **Where:** Above the composer on `/chat` (shard web-a).
- **What it does:** Slash-command autocomplete mirroring the Ink TUI: type `/`, see matching commands,
  arrow keys or click to select, Tab to apply, Enter to submit.
- **How it works:** `components/SlashPopover.tsx:23-171`. Exposes an imperative handle
  `SlashPopoverHandle { handleKey(e): boolean }` via `forwardRef` + `useImperativeHandle`; the parent
  owns all keyboard handling and the popover returns `true` when it consumed the event, so the
  composer's Enter/arrow logic stays in one place. Items are
  `CompletionItem {display, text, meta?}`; completions come from the gateway over the `gw` client.
- **Inputs / options:** `{input, gw, onApply(nextInput)}`; Up/Down, Tab, Enter, click, Escape.
- **Outputs / side effects:** Rewrites the composer input.
- **Config / env:** n/a.
- **Edge cases / guards:** Returns `false` for keys it does not handle so the composer stays
  authoritative.
- **Rebuild notes:** "Child reports whether it consumed the key" is the cleanest way to layer a
  popover onto an existing composer.

### Design-system components imported from `@nous-research/ui`  `id: web-shell.ds-components`
- **Surface:** Web dashboard
- **Where:** Everywhere; these are the visual primitives the shell and pages build on.
- **What it does:** Supplies the Nous Research design language (typeface, palette hooks, chrome
  shapes) so the dashboard matches the brand without local CSS.
- **How it works:** Package `@nous-research/ui@0.18.2`. Components/hooks used by the shell and shared
  components (import paths verbatim):
  `ui/components/button` (`Button`), `ui/components/selection-switcher` (`SelectionSwitcher`),
  `ui/components/spinner` (`Spinner`), `ui/components/typography/index` (`Typography`),
  `ui/components/confirm-dialog` (`ConfirmDialog`), `ui/components/list-item` (`ListItem`),
  `ui/components/bottom-sheet` (`BottomSheet`), `ui/components/select` (`Select`, `SelectOption`),
  `ui/components/badge` (`Badge`), `ui/components/checkbox` (`Checkbox`),
  `ui/components/dialog` (`Dialog`, `DialogClose`, `DialogContent`, `DialogDescription`,
  `DialogFooter`, `DialogHeader`, `DialogTitle`), `ui/components/toast` (`Toast`),
  `ui/components/card` (`Card`, `CardHeader`, `CardTitle`, `CardContent`, `CardDescription`),
  `ui/components/input` (`Input`), `ui/components/label` (`Label`),
  `ui/components/separator` (`Separator`), `ui/components/tabs` (`Tabs`, `TabsList`, `TabsTrigger`),
  `ui/components/switch` (`Switch`); hooks `hooks/use-below-breakpoint` (`useBelowBreakpoint`),
  `hooks/use-toast` (`useToast`), `hooks/use-confirm-delete` (`useConfirmDelete`); styles
  `styles/fonts.css` and `styles/globals.css`. Icons come from `lucide-react@0.577.0` — the shell
  imports exactly: `Activity`, `BarChart3`, `BookOpen`, `Clock`, `Code`, `Cpu`, `Database`,
  `Download`, `Eye`, `FolderOpen`, `FileText`, `Globe`, `Heart`, `KeyRound`, `Menu`,
  `MessageSquare`, `Package`, `PanelLeftClose`, `PanelLeftOpen`, `Plug`, `Puzzle`, `Radio`,
  `RotateCw`, `Settings`, `Shield`, `ShieldCheck`, `Sparkles`, `Star`, `Terminal`, `Users`,
  `Webhook`, `Wrench`, `X`, `Zap` (`App.tsx:23-58`).
- **Inputs / options:** per component.
- **Outputs / side effects:** n/a.
- **Config / env:** `index.css` must import `fonts.css` before `globals.css`, and `@source` the
  package's `dist` so Tailwind does not purge DS utility classes.
- **Edge cases / guards:** `vite.config.ts` `dedupe` exists because a symlinked DS checkout would
  otherwise give two React copies and break hooks.
- **Rebuild notes:** Depend on a versioned DS package rather than vendoring; keep the dedupe list.

---

## 7. Dashboard plugin system and plugin-contributed pages

### Plugin manifest schema  `id: web-shell.plugin-manifest`
- **Surface:** Web dashboard / API
- **Where:** `<plugin>/dashboard/manifest.json` on disk; served as `GET /api/dashboard/plugins`.
- **What it does:** Declares a plugin's dashboard tab, entry bundle, stylesheet, slot claims and
  optional backend module.
- **How it works:** Client type `plugins/types.ts:5-32`; server discovery + normalisation
  `hermes_cli/web_server.py:18434-18556`. Fields:
  | field | type | default | meaning |
  |---|---|---|---|
  | `name` | string | directory name | registry key; also the URL segment under `/dashboard-plugins/<name>/` |
  | `label` | string | `name` | sidebar text |
  | `description` | string | `""` | shown on the Plugins page |
  | `icon` | string | `"Puzzle"` | lucide icon name, resolved through `ICON_MAP` |
  | `version` | string | `"0.0.0"` | displayed on the Plugins page |
  | `tab.path` | string | `"/<name>"` | route the plugin claims |
  | `tab.position` | string | `"end"` | `"end"`, `"after:<segment>"`, `"before:<segment>"` |
  | `tab.override` | string | — | a built-in route path this plugin replaces (must start with `/`) |
  | `tab.hidden` | bool | — | register component/slots without a sidebar tab |
  | `slots` | string[] | `[]` | declared slot names (informational; actual wiring is `registerSlot`) |
  | `entry` | string | `"dist/index.js"` | JS bundle, loaded as `<script async>` |
  | `css` | string \| null | — | stylesheet injected as `<link rel="stylesheet">` |
  | `integrity` | string | — | Subresource-Integrity hash (e.g. `sha384-…`); adds `crossorigin="anonymous"` |
  | `api` | string | — | relative path to a `plugin_api.py` FastAPI router (validated server-side) |
  Server-added fields on the wire: `has_api` (bool, true only when the `api` path passed validation),
  `source` (`"bundled"` | `"user"` | `"project"`). Internal fields `_dir` and `_api_file` are stripped
  before the response.
- **Inputs / options:** the JSON file.
- **Outputs / side effects:** A nav entry, a route, a script tag, optionally a CSS link and a mounted
  FastAPI router.
- **Config / env:** `HERMES_ENABLE_PROJECT_PLUGINS` (truthy = `1`/`true`/`yes`/`on`) additionally
  scans `./.hermes/plugins`; `dashboard.hidden_plugins` hides a plugin; `plugins.enabled` /
  `plugins.disabled` gate user plugins.
- **Edge cases / guards:** `_safe_plugin_api_relpath` rejects absolute paths and `..` traversal on the
  `api` field — an attacker-controlled manifest could otherwise name any file for the server to import
  as a Python module (RCE, GHSA-5qr3-c538-wm9j); a rejected value logs
  `Plugin %s: refusing unsafe api path %r (must be a relative file inside the plugin's dashboard/ directory); backend routes from this plugin will not be mounted`
  and the plugin loads without a backend. A manifest that fails to parse logs
  `Bad dashboard plugin manifest %s: %s` and is skipped.
- **Rebuild notes:** Keep `api` validation at discovery time so the cached entry is already safe;
  make SRI opt-in but supported.

### Plugin discovery and search order  `id: web-shell.plugin-discovery`
- **Surface:** API
- **Where:** `GET /api/dashboard/plugins`, `GET /api/dashboard/plugins/rescan`.
- **What it does:** Finds every directory containing `dashboard/manifest.json` across the user, bundled
  and (opt-in) project roots.
- **How it works:** `hermes_cli/web_server.py:18434-18556 _discover_dashboard_plugins`. Search order,
  first-wins by `name`:
  1. `get_process_hermes_home()/plugins` (source `user`) — resolved from the dashboard's **launch**
     home so user plugins do not vanish when a request is scoped to another profile;
  2. `get_default_hermes_root()/plugins` (source `user`), added only when it differs from (1) — needed
     because `--profile <name>` makes the launch home a profile directory that has no `plugins/`;
  3. `<bundled>/memory` (source `bundled`);
  4. `<bundled>` (source `bundled`);
  5. `./.hermes/plugins` (source `project`), only when `HERMES_ENABLE_PROJECT_PLUGINS` is truthy.
  Entries within a root are sorted by directory name. Results are cached per-process in
  `_dashboard_plugins_cache`; the cache is invalidated when any cached `_dir` no longer exists, and
  `force_rescan=True` (used by the rescan endpoint and after install/enable/disable/update/remove)
  rebuilds it.
  `GET /api/dashboard/plugins` then filters: a plugin listed in `dashboard.hidden_plugins` is dropped;
  a `user` plugin must be in `plugins.enabled` and not in `plugins.disabled`; a `bundled` plugin must
  not be in `plugins.disabled`.
  Live response on the stock install lists exactly two plugins: `hermes-achievements` (label
  `Achievements`, icon `Star`, version `0.4.0`, tab `/achievements` position `after:analytics`,
  `has_api: true`, source `bundled`) and `kanban` (label `Kanban`, icon `Package`, version `1.0.0`,
  tab `/kanban` position `after:skills`, `has_api: true`, source `bundled`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** JSON array of manifests.
- **Config / env:** `HERMES_ENABLE_PROJECT_PLUGINS`, `dashboard.hidden_plugins`, `plugins.enabled`,
  `plugins.disabled`, `HERMES_HOME`.
- **Edge cases / guards:** The env check uses shared truthy semantics after GHSA-5qr3-c538-wm9j /
  #29156, where `os.environ.get(...)` treated `=0`, `=false`, `=no` as enabling the untrusted project
  source.
- **Rebuild notes:** Explicit search roots with a first-wins dedupe, plus an enable-list gate for
  untrusted sources.

### Plugin loader (`usePlugins`)  `id: web-shell.plugin-loader`
- **Surface:** Web dashboard
- **Where:** Invisible; runs once per page load.
- **What it does:** Fetches manifests, injects each plugin's CSS and JS, waits for `register()`, and
  reports `{plugins, manifests, loading}`.
- **How it works:** `plugins/usePlugins.ts:20-192`.
  - **Manifest cache:** `sessionStorage["hermes:plugin-manifests"]` (`MANIFEST_CACHE_KEY`).
    `getCachedManifests()` / `cacheManifests()` are try/catch-wrapped. Manifests are seeded from the
    cache so plugin routes register synchronously on the first render after a refresh, and the network
    fetch always runs in the background to keep the cache fresh (handles added/removed/changed
    plugins).
  - **`canSeedLoadedFromCache(cached)`** (`usePlugins.ts:53-58`): `loading` may start `false` from the
    cache **only** when no cached manifest declares `tab.override === "/chat"`, because `App.tsx`'s
    `pluginsLoading` gate around the persistent chat host is load-bearing.
  - **CSS:** `<link rel="stylesheet" href="${HERMES_BASE_PATH}/dashboard-plugins/<name>/<css>">`,
    de-duplicated by an existing-href query.
  - **JS:** `<script data-hermes-plugin="<name>" async src="${HERMES_BASE_PATH}/dashboard-plugins/<name>/<entry>">`.
    In dev the URL is cache-busted with `?hermes_dv=<Date.now()>` (so Vite HMR can clear the in-memory
    registry) and injected scripts are removed on cleanup; in production each base URL is loaded at
    most once (`loadedScripts` ref).
  - **SRI:** when `manifest.integrity` is a string, `script.integrity` is set and
    `script.crossOrigin = "anonymous"`.
  - **Error paths:** `script.onerror` → `setPluginLoadError(name, "LOAD_FAILED")` plus a console
    warning `` `[plugins] Failed to load <name> from <src> (open Network tab)` ``;
    `script.onload` → `notifyPluginRegistry()` then a `queueMicrotask` that, if no component
    registered, records `setPluginLoadError(name, "NO_REGISTER")`.
  - **Loading window:** a 2000 ms `setTimeout` clears `loading`; it also clears early once every
    manifest has a registered component, and immediately when the manifest list is empty or the fetch
    fails.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `<link>` and `<script>` tags in the document; one `sessionStorage` key.
- **Config / env:** base path.
- **Edge cases / guards:** Covered by `plugins/usePlugins.test.ts` (144 lines).
- **Rebuild notes:** Cache manifests for instant route registration but keep the loading gate
  conservative for override-capable plugins.

### Plugin component registry  `id: web-shell.plugin-registry`
- **Surface:** Web dashboard
- **Where:** Invisible; the bridge between a plugin bundle and the React tree.
- **What it does:** Stores `name → Component`, records load errors, and notifies subscribers.
- **How it works:** `plugins/registry.ts:46-93`. Module state: `_registered: Map<string, ComponentType>`,
  `_loadErrors: Map<string,string>`, `_listeners: Set<() => void>`. API:
  `registerPlugin(name, component)` (exposed to bundles as `window.__HERMES_PLUGINS__.register`, and
  it clears any prior load error for that name), `getPluginComponent(name)`,
  `getPluginLoadError(name)`, `setPluginLoadError(name, message)`, `onPluginRegistered(fn)` returning
  an unsubscribe, `getRegisteredCount()`, and `notifyPluginRegistry()`. Listener exceptions are
  swallowed so one bad subscriber cannot break the others.
- **Inputs / options:** `register(name, Component)` from the bundle.
- **Outputs / side effects:** Subscriber notifications.
- **Config / env:** n/a.
- **Edge cases / guards:** Tested in `plugins/registry.test.ts`.
- **Rebuild notes:** A tiny observable map is enough; `useSyncExternalStore` on the consumer side
  removes all the timing races.

### `PluginPage` renderer and its error copy  `id: web-shell.plugin-page`
- **Surface:** Web dashboard
- **Where:** The body of any plugin route (`/kanban`, `/achievements`, …).
- **What it does:** Renders the plugin's component once its bundle registers; otherwise shows a
  spinner or an actionable error.
- **How it works:** `plugins/PluginPage.tsx:13-64`. Subscribes with `useSyncExternalStore` **in
  render** so a `register()` that happens before a `useEffect` would run is never missed. States:
  - component present → render it;
  - `loadError` present → `role="alert"` div
    (`max-w-lg p-4 font-mondwest text-sm tracking-[0.08em] text-text-secondary`) with the mapped
    message: `LOAD_FAILED` →
    `Could not load this plugin’s script. Check the Network tab (dashboard-plugins/…) and the server’s plugin path.`
    (`i18n: common.pluginLoadFailed`); `NO_REGISTER` →
    `The plugin’s script did not call register(), or the script errored. Open the browser console for details.`
    (`i18n: common.pluginNotRegistered`); any other code renders the raw code;
  - otherwise a spinner row with `Loading...` (`i18n: common.loading`) in
    `font-mondwest text-sm tracking-[0.1em] text-text-tertiary`.
- **Inputs / options:** `{name}`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** The two error strings name the exact places to look (Network tab, console)
  rather than saying "something went wrong".
- **Rebuild notes:** Subscribe in render; write error copy that names the diagnostic step.

### Plugin slot registry and the 30 slot names  `id: web-shell.plugin-slots`
- **Surface:** Web dashboard
- **Where:** Named injection points across the shell and inside each built-in page.
- **What it does:** Lets a plugin inject components into the shell without owning a whole route;
  multiple plugins can populate the same slot and render stacked in registration order.
- **How it works:** `plugins/slots.ts:61-200`. `registerSlot(plugin, slot, component)` (exposed as
  `window.__HERMES_PLUGINS__.registerSlot`) replaces any earlier registration by the same plugin for
  the same slot (matching HMR expectations); `getSlotEntries(slot)` returns a copy;
  `onSlotRegistered(fn)` subscribes; `unregisterPluginSlots(plugin)` clears one plugin's entries
  (not wired in by default). `<PluginSlot name fallback?/>` renders every registered component
  stacked, re-reads the registry in an effect to catch anything registered between the initial
  `useState` and the first effect tick, and renders `fallback` (or `null`) when the slot is empty.
  The registry accepts any string so plugin ecosystems can define their own slots; the shell only
  renders the ones it knows.
  **Shell-wide slots (10)** and where the shell renders them:
  | slot | rendered at |
  |---|---|
  | `backdrop` | `App.tsx:487` — fixed `inset-0 z-0`, `pointer-events-none`, behind all chrome |
  | `header-left` | `App.tsx:612` — before the `HERMES/AGENT` wordmark |
  | `header-right` | `App.tsx:723` — before the theme/language switchers |
  | `header-banner` | `App.tsx:574` — full-width, below the mobile header spacer |
  | `sidebar` | cockpit rail — only rendered when `layoutVariant === "cockpit"` |
  | `pre-main` | `App.tsx:765` — above the route outlet |
  | `post-main` | `App.tsx:820` — below the route outlet |
  | `footer-left` | replaces the left footer cell content |
  | `footer-right` | replaces the right footer cell content |
  | `overlay` | `App.tsx:826` — fixed layer above everything (scanlines, vignettes) |
  **Page-scoped slots (20):** `sessions:top`, `sessions:bottom`, `analytics:top`,
  `analytics:bottom`, `logs:top`, `logs:bottom`, `cron:top`, `cron:bottom`, `skills:top`,
  `skills:bottom`, `plugins:top`, `plugins:bottom`, `config:top`, `config:bottom`, `env:top`,
  `env:bottom`, `docs:top`, `docs:bottom`, `chat:top`, `chat:bottom`.
- **Inputs / options:** `registerSlot(plugin, slot, Component)`.
- **Outputs / side effects:** Extra components in the shell.
- **Config / env:** n/a.
- **Edge cases / guards:** `KNOWN_SLOT_NAMES` is a `const` tuple typed as `KnownSlotName`; unknown
  names are accepted by the registry but never rendered by the shell.
- **Rebuild notes:** Name slots after their position, expose an escape-hatch `fallback`, and let
  multiple plugins stack.

### Plugin SDK exposed on `window`  `id: web-shell.plugin-sdk`
- **Surface:** Web dashboard
- **Where:** `window.__HERMES_PLUGINS__` and `window.__HERMES_PLUGIN_SDK__`, set before the first
  render (`main.tsx:13`).
- **What it does:** Gives plugin bundles React, hooks, the API client, WS helpers, UI components and
  utilities so they never bundle their own copies — which would break hooks and duplicate the DS.
- **How it works:** `plugins/registry.ts:99-192`; the public contract is declared in
  `plugins/sdk.d.ts` (184 lines).
  - `window.__HERMES_PLUGINS__` = `{register, registerSlot}`.
  - `window.__HERMES_PLUGIN_SDK__` = an object with:
    - `sdkVersion` — `SDK_CONTRACT_VERSION = "1.1.0"` (`registry.ts:106`). "Bump the major on any
      backwards-incompatible change to the exposed surface; additive changes don't require a bump."
    - `React` — the host's React instance.
    - `hooks` — `useState`, `useEffect`, `useCallback`, `useMemo`, `useRef`, `useContext`,
      `createContext`, `useToast` (returns `{showToast, toast}`; `showToast(message, 'success'|'error')`),
      `useConfirmDelete` (returns `requestDelete` / `confirm` / `cancel` / `isOpen` / `isDeleting` /
      `pendingId`).
    - `api` — the full `api` client object (see the method index).
    - `fetchJSON` — raw JSON fetch for plugin-specific endpoints.
    - `authedFetch` — authenticated fetch for non-JSON endpoints, "so plugins never read
      `window.__HERMES_SESSION_TOKEN__` directly".
    - `buildWsUrl` — WS URL with the correct auth param for the active mode.
    - `buildWsAuthParam` — the lower-level `[name, value]` pair.
    - `components` — `Card`, `CardHeader`, `CardTitle`, `CardContent`, `Badge`, `Button`, `Checkbox`,
      `ConfirmDialog`, `Dialog`, `DialogClose`, `DialogContent`, `DialogDescription`, `DialogFooter`,
      `DialogHeader`, `DialogTitle`, `Input`, `Label`, `Select`, `SelectOption`, `Separator`, `Tabs`,
      `TabsList`, `TabsTrigger`, `Toast`, `PluginSlot`.
    - `utils` — `cn`, `timeAgo`, `isoTimeAgo`.
    - `useI18n` — the host i18n hook, giving plugins access to the shared catalog (this is how the
      `kanban.*` and `achievements.*` namespaces reach the bundles).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Two `window` globals.
- **Config / env:** n/a.
- **Edge cases / guards:** Window globals are declared only in `sdk.d.ts` — "the single source of
  truth for the public contract. Don't redeclare them here (duplicate ambient declarations with
  differing modifiers conflict)."
- **Rebuild notes:** Version the SDK surface, expose it before first paint, and include the auth
  helpers so plugins cannot invent their own (insecure) auth path.

### Plugin nav positioning and route override  `id: web-shell.plugin-nav-routing`
- **Surface:** Web dashboard
- **Where:** Sidebar ordering and route resolution.
- **What it does:** Places a plugin tab relative to built-ins and lets a plugin replace a built-in
  page entirely.
- **How it works:** `App.tsx:256-368`.
  - `buildNavItems(builtIn, manifests)` skips manifests with `tab.override` or `tab.hidden`, then
    inserts each plugin item by `tab.position`: `"end"` appends;
    `"after:<segment>"` finds `"/" + segment` and splices at `idx + 1` (appending when not found);
    `"before:<segment>"` splices at `idx`; anything unrecognised appends.
  - `buildRoutes(builtinRoutes, manifests)` builds the route list: for each built-in path, if a
    manifest claims `tab.override === path` the route element becomes `<PluginPage name={m.name}/>`
    with key `override:<name>`, otherwise `builtin:<path>`; then non-override, non-hidden addons get
    their own routes (`plugin:<name>`) unless they claim `/plugins` or collide with a built-in path;
    finally hidden plugins still get routes (`plugin:hidden:<name>`) under the same exclusions, so a
    slot-only plugin can still be deep-linked.
  - `/plugins` is explicitly reserved — a plugin cannot claim the Plugins page path as an addon.
  - A `/chat` override additionally suppresses the persistent chat host entirely (see
    `web-shell.chat-persistent-host`); the comment notes nothing ships overriding `/chat` today but it
    is an advertised extension point, so the pre-persistence contract is preserved.
- **Inputs / options:** `tab.position`, `tab.override`, `tab.hidden`.
- **Outputs / side effects:** Nav order and route table.
- **Config / env:** n/a.
- **Edge cases / guards:** An `after:`/`before:` target that does not exist degrades to append rather
  than throwing.
- **Rebuild notes:** Relative positioning by path segment is friendlier than numeric weights and
  survives nav reordering.

### Plugin asset serving (`/dashboard-plugins/<name>/<file>`)  `id: web-shell.plugin-assets`
- **Surface:** API
- **Where:** Every plugin script/stylesheet/image URL.
- **What it does:** Serves files from a plugin's `dashboard/` directory to the browser, unauthenticated
  but tightly constrained.
- **How it works:** `hermes_cli/web_server.py:18983-19060 serve_plugin_asset`. Steps: look the plugin
  up in the discovery cache (404 `Plugin not found` if absent); apply the same enable/disable gate as
  the manifest list (user plugins must be enabled, bundled plugins must not be disabled — #46435,
  GHSA-mcfc-hp25-cjv7); resolve `base/<file_path>` and 403 `Path traversal blocked` when it escapes
  `base`; 404 `File not found` when it is not a regular file; then enforce a **suffix allow-list**
  with explicit content types: `.js`/`.mjs` → `application/javascript`, `.css` → `text/css`,
  `.json` → `application/json`, `.html` → `text/html`, `.svg` → `image/svg+xml`, `.png` → `image/png`,
  `.jpg`/`.jpeg` → `image/jpeg`, `.gif` → `image/gif`, `.webp` → `image/webp` (plus font types).
  Anything outside the set 404s — the docstring explains why: user plugins ship a `plugin_api.py` the
  browser never fetches, and without the allow-list anyone on the loopback port could curl the `.py`
  source of a private third-party plugin.
- **Inputs / options:** `plugin_name`, `file_path`.
- **Outputs / side effects:** File bytes.
- **Config / env:** `plugins.enabled` / `plugins.disabled`.
- **Edge cases / guards:** The route is deliberately unauthenticated because `<script src>` and
  `<link href>` cannot attach a custom auth header.
- **Rebuild notes:** Allow-list by extension, gate by enablement, and resolve-then-compare for
  traversal.

### Plugin API runtime gate  `id: web-shell.plugin-api-gate`
- **Surface:** API
- **Where:** Every `/api/plugins/{name}/...` request (the routers plugins mount via `plugin_api.py`).
- **What it does:** Enforces the enabled/disabled policy at request time, so disabling a plugin takes
  effect immediately instead of at the next dashboard restart.
- **How it works:** `hermes_cli/web_server.py:986-1059 _plugin_api_runtime_gate` middleware.
  `_mount_plugin_api_routes` gates at import time, but a router already mounted stays mounted; this
  middleware re-checks per request. It only gates **authenticated** requests
  (`request.state.token_authenticated`, `app.state.auth_required`, a valid session token, or a valid
  query token) so an unauthenticated caller gets auth's 401 first and cannot use the endpoint as a
  plugin-name oracle. Policy: `user` plugins must be in `plugins.enabled` and not in
  `plugins.disabled`; `bundled` plugins must not be in `plugins.disabled`; an unknown plugin defaults
  to `user` (safe default — blocks). Failures return 404 `{"detail": "Plugin not found"}`.
  Registration order matters: it is registered *before* the auth middlewares so it *executes after*
  them.
- **Inputs / options:** n/a.
- **Outputs / side effects:** 404 for disabled plugins.
- **Config / env:** `plugins.enabled`, `plugins.disabled`.
- **Edge cases / guards:** Uses 404 rather than 403 so existence is not leaked.
- **Rebuild notes:** Runtime policy checks for anything mounted at import time.

### Plugin sidebar visibility toggle  `id: web-shell.plugin-visibility`
- **Surface:** API / Web dashboard
- **Where:** Plugins page rows (`Show in sidebar` / `Hide from sidebar`,
  `i18n: pluginsPage.showInSidebar` / `pluginsPage.hideFromSidebar`); the shell consumes the result.
- **What it does:** Removes a plugin's tab from the sidebar (and its manifest from the SPA payload)
  without uninstalling or disabling it.
- **How it works:** `POST /api/dashboard/plugins/{name}/visibility` body `{hidden: bool}`
  (`hermes_cli/web_server.py:18955-18981`). Requires a token (`_require_token`), validates the plugin
  name, then adds/removes the name in `config.dashboard.hidden_plugins` (creating the list if the
  stored value is not a list) under `_CONFIG_MUTATION_LOCK`, saves, invalidates the plugins-hub cache
  and returns `{ok:true, name, hidden}`. The manifest endpoint reports the current state as
  `user_hidden` (`web_server.py:18794`) for the Plugins page.
- **Inputs / options:** `{hidden: true|false}`.
- **Outputs / side effects:** `config.yaml` `dashboard.hidden_plugins` list.
- **Config / env:** `dashboard.hidden_plugins`.
- **Edge cases / guards:** Hiding removes the plugin from `GET /api/dashboard/plugins` entirely, so
  its route disappears too (not just the nav entry).
- **Rebuild notes:** Distinguish "hidden" (cosmetic) from "disabled" (does not run) — this API
  currently makes hidden also mean unrouted.

### Kanban plugin page  `id: web-shell.plugin-kanban`
- **Surface:** Web dashboard (plugin page)
- **Where:** Sidebar → Plugins group → `KANBAN`, route `/kanban`. Page header title `Kanban`.
- **What it does:** A multi-agent collaboration board — drag-and-drop cards across columns, read
  comment threads, and see which profile is running what. Manifest description verbatim:
  `Multi-agent collaboration board — drag-drop cards across columns, read comment threads, see which profile is running what`.
- **How it works:** Bundle `plugins/kanban/dashboard/dist/index.js` (204 KB) + `dist/style.css`
  (45 KB), registered through the plugin SDK; backend router `plugins/kanban/dashboard/plugin_api.py`
  (3100 lines) mounted under `/api/plugins/kanban/`. Strings come from the host `kanban.*` i18n
  namespace (168 keys, §4) through a `tx(t, key, fallback)` helper, with a few English-only strings
  living in the bundle. There is also a systemd unit
  `plugins/kanban/systemd/hermes-kanban-dispatcher.service` for the dispatcher.
  **Live page anatomy** (verified on `/kanban`):
  - Toolbar row: `+ New board` (`i18n: kanban.newBoard`), `Settings`
    (`i18n: kanban.boardSettings`, `title` = `Board settings — name, description, and the default project directory new tasks inherit`),
    a `?` help affordance, the collapsed orchestration pill `Orchestration:` + mode (`Auto`), and the
    expander `▸ Orchestration settings`. The board switcher's `title` is `Switch kanban board` with
    the hint `Boards are independent work streams. Each board has its own tasks, tenants, and assignees.`
    and `Boards let you separate unrelated streams of work` (`i18n: kanban.boardSwitcherHint`);
    archiving uses `Archive this board` (`i18n: kanban.archiveBoardTitle`).
  - Filter row: `SEARCH` with placeholder `Filter cards…` (`i18n: kanban.filterCards`);
    `TENANT` select defaulting to `All tenants` (`i18n: kanban.allTenants`);
    `ASSIGNEE` select defaulting to `All profiles` (`i18n: kanban.allProfiles`);
    checkboxes `Show archived` (`i18n: kanban.showArchived`) and
    `Lanes by profile` (`i18n: kanban.lanesByProfile`); buttons `Nudge dispatcher`
    (`i18n: kanban.nudgeDispatcher`), `Refresh` (`i18n: kanban.refresh`) and `Clear filters`.
  - Eight columns, each with a count, a `+` "create task in this column" button
    (`aria-label` `Select all tasks in <Column>` on the select-all control) and a help line:
    | column | label | help text |
    |---|---|---|
    | triage | `Triage` | `Raw ideas — a specifier will flesh out the spec` |
    | todo | `Todo` | `Waiting on dependencies or unassigned` |
    | scheduled | `Scheduled` | `Waiting on a known time delay or scheduled follow-up` |
    | ready | `Ready` | `Dependencies satisfied; assign a profile to dispatch` |
    | running | `In Progress` | `Claimed by a worker — in-flight` |
    | blocked | `Blocked` | `Worker asked for human input` |
    | review | `Review` | `Implementation complete — awaiting review` |
    | done | `Done` | `Completed` |
    Empty columns show `— no tasks —` (`i18n: kanban.noTasks`). An `archived` column
    (`Archived` / `Archived`) exists in the label maps and appears when `Show archived` is on.
    Note: `review` is **not** in the host `kanban.columnLabels` catalog — its label and help text are
    English-only strings inside the bundle (`review: "Review"`,
    `review: "Implementation complete — awaiting review"`).
  - A trash drop-zone at the bottom right showing `🗑️` and `Drop to delete`.
  - **Orchestration settings panel** (collapsible, `OrchestrationPanel` in the bundle): `Loading mode…`
    placeholder; `Orchestration mode` with `Auto` / `Manual`; `Auto-decompose triage tasks` with the
    two explanations `The dispatcher decomposes new triage tasks automatically.` and
    `Triage tasks stay in triage until you click ⚗ Decompose.`; `Orchestrator profile` with
    `Resolved: `; `Default assignee`; `Reload`; a `Profile descriptions` list with the hint
    `Descriptions guide the decomposer's routing. Click ⚗ to auto-generate, or edit and save.`,
    the empty state `No profiles installed.`, the field placeholder `What is this profile good at?`,
    and the actions `Save` (`title` `Save the description above as user-authored`, busy label
    `Saving…`) and auto-generate (`title`
    `Auto-generate a description from this profile's skills and model`, busy label `Generating…`).
    Toasts: `Settings saved.`, `Save failed: `, `Failed to load: `, `Auto-generate failed: `,
    `` `Description saved for <name>.` ``, `` `Auto-generated description for <name>.` ``.
  - Errors: `Kanban tab hit a rendering error` (`i18n: kanban.renderingError`) with
    `Reload view`; `WebSocket auth failed — reload the page to refresh the session token.`
    (`i18n: kanban.wsAuthFailed`); `Failed to load Kanban board: ` +
    `The backend auto-creates kanban.db on first read. If this persists, check the dashboard logs.`
  - **Backend routes** mounted under `/api/plugins/kanban` (46, from `plugin_api.py`):
    `GET /board`, `GET /tasks/{task_id}`, `POST /tasks`, `GET /tasks/{task_id}/attachments`,
    `POST /tasks/{task_id}/attachments`, `GET /attachments/{attachment_id}`,
    `DELETE /attachments/{attachment_id}`, `PATCH /tasks/{task_id}`, `DELETE /tasks/{task_id}`,
    `POST /tasks/{task_id}/comments`, `POST /links`, `DELETE /links`, `POST /tasks/bulk`,
    `GET /diagnostics`, `GET /workers/active`, `GET /runs/{run_id}`, `GET /runs/{run_id}/inspect`,
    `POST /runs/{run_id}/terminate`, `POST /tasks/{task_id}/reclaim`, `POST /tasks/{task_id}/specify`,
    `POST /tasks/{task_id}/reassign`, `POST /estimate`, `POST /tasks/{task_id}/estimate`,
    `GET /config`, `GET /home-channels`, `POST /tasks/{task_id}/home-subscribe/{platform}`,
    `DELETE /tasks/{task_id}/home-subscribe/{platform}`, `GET /stats`, `GET /assignees`,
    `GET /tasks/{task_id}/log`, `POST /dispatch`, `GET /model-options`, `GET /projects`,
    `GET /boards`, `POST /boards`, `PATCH /boards/{slug}`, `DELETE /boards/{slug}`,
    `POST /boards/{slug}/export`, `POST /boards/import`, `POST /boards/{slug}/switch`,
    `GET /profiles`, `PATCH /profiles/{profile_name}`, `POST /profiles/{profile_name}/describe-auto`,
    `POST /tasks/{task_id}/decompose`, `GET /orchestration`, `PUT /orchestration`, and a WebSocket
    `/events`.
- **Inputs / options:** Every control listed above; drag-and-drop between columns; the trash zone;
  per-card actions from the `kanban.*` catalog (`Block`, `Unblock`, `Reclaim`, `Reassign`,
  `Complete`, `Archive`, `Apply`, `Clear`, `Comment`, `Diagnostics`, `Show`/`Hide`, `Open`,
  `Close (Esc)`, `Copy command to clipboard`, `Show all attempts`, `Notify home channels`, …).
- **Outputs / side effects:** Writes to `kanban.db` under the Hermes home; dispatcher nudges; worker
  reassignment; board export/import files.
- **Config / env:** Board state in `kanban.db` (auto-created on first read); the dispatcher may run as
  a systemd unit.
- **Edge cases / guards:** Bulk completion is blocked when the model referenced phantom card ids
  (`⚠ Completion blocked — phantom card ids`, `⚠ Prose referenced phantom card ids`); a completion
  summary is required before marking a task done
  (`Completion summary is required before marking a task done.`).
- **Rebuild notes:** The board is the reference example of a full plugin: manifest + JS bundle + CSS +
  FastAPI router + WebSocket + host i18n namespace. A better version would move the English-only
  bundle strings (`Review`, the orchestration panel copy) into the shared catalog so the page fully
  localises.

### Achievements plugin page  `id: web-shell.plugin-achievements`
- **Surface:** Web dashboard (plugin page)
- **Where:** Sidebar → Plugins group → `ACHIEVEMENTS`, route `/achievements`. Page header title
  `Achievements`. Manifest description verbatim:
  `Steam-style achievements for vibe coding and agentic Hermes workflows.`
- **What it does:** Scans local Hermes session history and awards 60 tiered badges across 8
  categories, 8 of which are secret until a matching signal appears.
- **How it works:** Bundle `plugins/hermes-achievements/dashboard/dist/index.js` (47 KB) +
  `dist/style.css` (18 KB); backend `plugins/hermes-achievements/dashboard/plugin_api.py` (1092 lines)
  mounted under `/api/plugins/hermes-achievements/`. Strings come from the host `achievements.*`
  namespace (67 keys, §4).
  **Live page anatomy** (verified on `/achievements`):
  - Hero: kicker `AGENTIC GAMERSCORE` (`i18n: achievements.hero.kicker`), title
    `Hermes Achievements`, subtitle
    `Collectible Hermes badges earned from real session history. Known unfinished achievements are shown as Discovered; Secret achievements stay hidden until the first matching behavior appears.`,
    and a `Rescan` button (`i18n: achievements.actions.rescan`).
  - Five stat tiles: `UNLOCKED` `0 / 60` / `earned badges`; `DISCOVERED` `52` / `known, not earned yet`;
    `SECRETS` `8` / `hidden until first signal`; `HIGHEST TIER` `None yet` /
    `Copper → Silver → Gold → Diamond → Olympian`; `LATEST` `None yet` / `run Hermes more`.
  - Guide blocks: `TIERS` showing `COPPER → SILVER → GOLD → DIAMOND → OLYMPIAN`;
    `SECRET ACHIEVEMENTS` with
    `Secrets hide their exact trigger. Once Hermes sees a related signal, the card becomes Discovered and shows its requirement.`;
    plus (during a scan) `Scan status` and `What is scanned` blocks.
  - Category filter row: `All`, `Agent Autonomy`, `Debugging Chaos`, `Vibe Coding`, `Hermes Native`,
    `Research/Web`, `Tool Mastery`, `Model Lore`, `Lifestyle`.
  - Visibility filter row: `all`, `unlocked`, `discovered`, `secret`
    (`i18n: achievements.filters.visibility_*`).
  - Cards show: name, category, state badge (`Unlocked` / `Discovered` / `Secret`), the tier target
    (`Target {tier}` → e.g. `TARGET COPPER`) or `OBJECTIVE` for multi-condition badges, the
    description, and a progress readout under `WHAT COUNTS` (`x / y`) or `HOW TO REVEAL` → `hidden`
    for secrets. Secret cards render name `???` and the description
    `Secret achievement: hidden until Hermes detects the first relevant behavior in your session history.`
  - Share dialog (`achievements.share.*`): header `Share: {name}`, `Rendering…`, `Share on X`
    (`title` `Opens X with a pre-filled post`), `Copy image`
    (`title` `Copy the image to paste into your post`), `Copied ✓`, `Download PNG`, the hint
    `Share on X opens a pre-filled post in a new tab. Click Copy image first if you want the 1200×630 badge attached — X lets you paste it right into the tweet composer. Download PNG saves the file for use anywhere.`,
    the unsupported-browser notice
    `Clipboard image copy not supported in this browser — use Download instead.`, and the tweet
    template `Just unlocked {tier_part}"{name}" in Hermes Agent ☤`.
  - Empty-secrets state: `No hidden secrets left in this scan.` plus the clue
    `Clue: secrets usually start from unusual failure or power-user patterns — port conflicts, permission walls, missing env vars, YAML mistakes, Docker collisions, rollback/checkpoint use, cache hits, or tiny fixes after lots of red text.`
  - **Backend routes** under `/api/plugins/hermes-achievements` (6): `GET /achievements`,
    `GET /scan-status`, `GET /recent-unlocks`, `GET /sessions/{session_id}/badges`,
    `POST /rescan`, `POST /reset-state`.
  - **Engine:** `TIER_NAMES = ["Copper","Silver","Gold","Diamond","Olympian"]`; `tiers(values)` pairs
    each name with a threshold; `req(metric, gte)` builds a multi-condition requirement. Achievement
    kinds: `lifetime` (cumulative metric), `best_session` (max within one session),
    `multi_condition` (all requirements met). State is derived by
    `evaluate_tiered` / `evaluate_requirements` / `evaluate_boolean` into
    `{unlocked, discovered, state, tier, progress, next_tier, next_threshold, progress_pct}`;
    a secret with no progress renders as `state: "secret"` and is masked by `display_achievement`.
    Scanning writes a snapshot, a checkpoint and unlock state under the Hermes home data dir
    (`_data_dir`, `state_path`, `snapshot_path`, `checkpoint_path`).
  - **The 60 achievements** (`id | name | category | kind`, `*` = secret):
    `let_him_cook | Let Him Cook | Agent Autonomy | best_session`;
    `autonomous_avalanche | Autonomous Avalanche | Agent Autonomy | lifetime`;
    `toolchain_maxxer | Toolchain Maxxer | Agent Autonomy | best_session`;
    `full_send | Full Send | Agent Autonomy | multi_condition`;
    `subagent_commander | Subagent Commander | Agent Autonomy | lifetime`;
    `background_process_enjoyer | Background Process Enjoyer | Agent Autonomy | lifetime`;
    `cron_necromancer | Cron Necromancer | Agent Autonomy | lifetime`;
    `red_text_connoisseur | Red Text Connoisseur | Debugging Chaos | lifetime`;
    `stack_trace_sommelier | Stack Trace Sommelier | Debugging Chaos | lifetime`;
    `actually_read_the_logs | Actually Read The Logs | Debugging Chaos | lifetime`;
    `port_3000_taken | Port 3000 Is Taken | Debugging Chaos | lifetime *`;
    `permission_denied_any_percent | Permission Denied Any% | Debugging Chaos | lifetime *`;
    `dependency_hell_tourist | Dependency Hell Tourist | Debugging Chaos | multi_condition`;
    `the_fix_was_restarting | The Fix Was Restarting It | Debugging Chaos | multi_condition`;
    `forgot_the_env_var | Forgot The Env Var | Debugging Chaos | lifetime *`;
    `yaml_colon_incident | YAML Colon Incident | Debugging Chaos | lifetime *`;
    `docker_name_collision | Docker Name Collision | Debugging Chaos | lifetime *`;
    `supposed_to_be_quick | This Was Supposed To Be Quick | Vibe Coding | best_session`;
    `one_more_small_change | One More Small Change | Vibe Coding | best_session`;
    `vibe_architect | Vibe Architect | Vibe Coding | best_session`;
    `pixel_goblin | Pixel Goblin | Vibe Coding | lifetime`;
    `ship_first_ask_later | Ship First, Ask Later | Vibe Coding | multi_condition`;
    `css_exorcist | CSS Exorcist | Vibe Coding | lifetime`;
    `one_character_fix | One Character Fix | Vibe Coding | multi_condition *`;
    `skillsmith | Skillsmith | Hermes Native | lifetime`;
    `skill_issue_skill_created | Skill Issue? Skill Created. | Hermes Native | lifetime`;
    `memory_keeper | Memory Keeper | Hermes Native | lifetime`;
    `memory_palace | Memory Palace | Hermes Native | lifetime`;
    `context_dragon | Context Dragon | Hermes Native | lifetime`;
    `gateway_dweller | Gateway Dweller | Hermes Native | lifetime`;
    `plugin_goblin | Plugin Goblin | Hermes Native | lifetime`;
    `rollback_wizard | Rollback Wizard | Hermes Native | lifetime *`;
    `toolset_cartographer | Toolset Cartographer | Hermes Native | lifetime`;
    `config_surgeon | Config Surgeon | Hermes Native | lifetime`;
    `rabbit_hole_certified | Rabbit Hole Certified | Research/Web | lifetime`;
    `citation_goblin | Citation Goblin | Research/Web | lifetime`;
    `docs_archaeologist | Docs Archaeologist | Research/Web | lifetime`;
    `browser_possession | Browser Possession | Research/Web | lifetime`;
    `terminal_goblin | Terminal Goblin | Tool Mastery | lifetime`;
    `patch_wizard | Patch Wizard | Tool Mastery | lifetime`;
    `file_archaeologist | File Archaeologist | Tool Mastery | lifetime`;
    `image_whisperer | Image Whisperer | Tool Mastery | lifetime`;
    `voice_of_the_machine | Voice Of The Machine | Tool Mastery | lifetime`;
    `test_suite_tamer | Test Suite Tamer | Tool Mastery | lifetime`;
    `screenshot_hunter | Screenshot Hunter | Tool Mastery | lifetime`;
    `model_hopper | Model Hopper | Model Lore | lifetime`;
    `openrouter_enjoyer | OpenRouter Enjoyer | Model Lore | lifetime`;
    `codex_conjurer | Codex Conjurer | Model Lore | lifetime`;
    `multi_model_mage | Multi-Model Mage | Model Lore | lifetime`;
    `five_model_flight | Five-Model Flight | Model Lore | lifetime`;
    `provider_polyglot | Provider Polyglot | Model Lore | lifetime`;
    `model_sommelier | Model Sommelier | Model Lore | lifetime`;
    `claude_confidant | Claude Confidant | Model Lore | lifetime`;
    `gemini_cartographer | Gemini Cartographer | Model Lore | lifetime`;
    `open_weights_pilgrim | Open Weights Pilgrim | Model Lore | lifetime`;
    `rebase_acrobat | Rebase Acrobat | Vibe Coding | lifetime`;
    `marathon_operator | Marathon Operator | Lifestyle | lifetime`;
    `weekend_warrior | Weekend Warrior | Lifestyle | lifetime`;
    `night_shift_operator | Night Shift Operator | Lifestyle | lifetime`;
    `cache_hit_appreciator | Cache Hit Appreciator | Lifestyle | lifetime *`.
    Category totals: Debugging Chaos 10, Hermes Native 10, Model Lore 10, Vibe Coding 8,
    Agent Autonomy 7, Tool Mastery 7, Research/Web 4, Lifestyle 4.
- **Inputs / options:** `Rescan` button; category chips; visibility chips; per-card `Share` action
  and its dialog buttons.
- **Outputs / side effects:** Reads session history; writes snapshot/checkpoint/unlock-state files
  under the Hermes home; generates a 1200×630 PNG share card; opens X with a pre-filled post.
- **Config / env:** none beyond `HERMES_HOME`.
- **Edge cases / guards:** First scan "can take 5–10 seconds on large histories"
  (`i18n: achievements.hero.scan_subtitle`); progress is reported as
  `Scanned {scanned} of {total} sessions · {pct}%. Badges unlock as more history streams in.`
- **Rebuild notes:** Derive gamification entirely from existing telemetry (sessions, tool calls, model
  metadata, errors) with a cached snapshot and an explicit "secret until first signal" state machine.

---

## 8. Serving the SPA: `hermes_cli/web_server.py` and the dashboard CLI

### `mount_spa` — static mount and SPA fallback  `id: web-shell.mount-spa`
- **Surface:** API / Core
- **Where:** Every URL the dashboard server answers that is not an explicit API route.
- **What it does:** Serves the built bundle from `hermes_cli/web_dist`, falls back to `index.html`
  for client-side routes, and returns a real JSON 404 for unmatched `/api/*` paths.
- **How it works:** `hermes_cli/web_server.py:17820-18038`.
  - `WEB_DIST = Path(os.environ["HERMES_WEB_DIST"]) if "HERMES_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"`
    (`web_server.py:143`).
  - A missing `WEB_DIST` is deliberately **not** a mount-time terminal state (#82614): a long-lived
    `hermes dashboard --skip-build` process that survives a `git pull` used to install a permanent
    `no_frontend` catch-all and answer 404 `Frontend not built` forever. The routes are mounted
    unconditionally and cope per-request, so the dashboard recovers the moment a build appears.
  - `/assets` is mounted with `_ImmutableAssetFiles(directory=WEB_DIST/"assets", check_dir=False)`,
    a `StaticFiles` subclass that stamps `Cache-Control: public, max-age=31536000, immutable`
    (`_IMMUTABLE_ASSET_CACHE_CONTROL`, `web_server.py:17817`) on every 200 — safe because every
    `/assets/<name>-<contenthash>.<ext>` filename changes when its content does, and `index.html` is
    `no-store`. `check_dir=False` lets the mount survive a missing dist.
  - `GET /assets/{filename}.css` is intercepted *before* the static mount so absolute
    `url(/fonts/…)`, `url(/fonts-terminal/…)`, `url(/ds-assets/…)` and `url(/assets/…)` references
    inside the built CSS can be prefixed under a path-prefix proxy; it also validates the resolved
    path stays inside `WEB_DIST` and returns `{"error": "not found"}` with 404 otherwise.
  - Catch-all `GET /{full_path:path}` (`web_server.py:18010-18038`): `full_path == "api"` or
    `full_path.startswith("api/")` returns `{"detail": f"No such API endpoint: /{full_path}"}` with
    404 — "falling through to index.html here returns `<!doctype html>` with status 200, which makes
    JSON clients … blow up with an opaque `SyntaxError: Unexpected token '<'`". Otherwise, if the
    requested path resolves inside `WEB_DIST` and is an existing file it is returned as a
    `FileResponse`; otherwise `_serve_index(prefix)` is returned so client-side routing works.
    The `resolve().is_relative_to()` check blocks URL-encoded traversal (`%2e%2e/`).
- **Inputs / options:** the request path and `X-Forwarded-Prefix`.
- **Outputs / side effects:** Static files or the injected `index.html`.
- **Config / env:** `HERMES_WEB_DIST`, `HERMES_SERVE_HEADLESS`.
- **Edge cases / guards:** Note the consequence of the catch-all: a URL like `/p/default/api/status`
  (which belongs to the *gateway's* aiohttp API-server platform, not the dashboard) returns the SPA
  HTML with status 200 from this server — verified live.
- **Rebuild notes:** Mount statics with an immutable cache, serve the shell `no-store`, and never let
  an unmatched `/api/*` fall through to HTML.

### `index.html` bootstrap injection  `id: web-shell.index-injection`
- **Surface:** API / Web dashboard
- **Where:** A `<script>` inserted just before `</head>` in every served `index.html`.
- **What it does:** Hands the SPA its session token (loopback only), embedded-chat flag, base path and
  auth-mode flag.
- **How it works:** `hermes_cli/web_server.py:17889-17952 _serve_index`. Live output on the running
  instance is exactly:
  `<script>window.__HERMES_SESSION_TOKEN__="inventory-token-123";window.__HERMES_DASHBOARD_EMBEDDED_CHAT__=true;window.__HERMES_BASE_PATH__="";window.__HERMES_AUTH_REQUIRED__=false;</script>`
  In **gated** mode (`app.state.auth_required`) the `__HERMES_SESSION_TOKEN__` assignment is omitted
  entirely — the SPA reads identity from `/api/auth/me` over cookie auth — and only the other three
  globals are emitted. The response carries
  `Cache-Control: no-store, no-cache, must-revalidate`. When a prefix is present, the HTML's absolute
  asset URLs are rewritten first (`href="/assets/`, `src="/assets/`, `href="/favicon.ico"`,
  `href="/fonts/`, `href="/ds-assets/`, `src="/ds-assets/`), then the theme bootstrap `<style>` (if
  any) and finally the bootstrap `<script>` are inserted before `</head>`. If `index.html` cannot be
  read the handler returns
  `{"error": "Frontend not built. Run: cd web && npm run build"}` with status 404.
- **Inputs / options:** `prefix` (normalised `X-Forwarded-Prefix`).
- **Outputs / side effects:** The four `window` globals the SPA depends on.
- **Config / env:** `_SESSION_TOKEN` (from `HERMES_DASHBOARD_SESSION_TOKEN` or generated),
  `_DASHBOARD_EMBEDDED_CHAT_ENABLED` (constant `True`, `web_server.py:659`).
- **Edge cases / guards:** The token is never exposed by an API endpoint — only through this HTML, and
  only when the gate is off.
- **Rebuild notes:** Injecting the credential into a `no-store` shell avoids an unauthenticated
  token-dispensing endpoint; rotate it per process.

### Headless backend mode (`hermes serve`)  `id: web-shell.headless-serve`
- **Surface:** CLI / API
- **Where:** `hermes serve` (or `HERMES_SERVE_HEADLESS=1`).
- **What it does:** Runs the JSON-RPC/WebSocket/API surface with **no** browser SPA, even if a dist is
  lying around from a prior build.
- **How it works:** `hermes_cli/web_server.py:17837-17875`. When `HERMES_SERVE_HEADLESS == "1"`,
  `mount_spa` installs a single `GET /{full_path:path}` that returns
  `{"error": "Headless backend (hermes serve): web UI disabled — use \`hermes dashboard\` for the browser UI."}`
  with status 404 — **except** at the exact root path and only when the auth gate is off, where it
  returns a minimal token-only HTML page:
  `<!doctype html><html><head><script>window.__HERMES_SESSION_TOKEN__=<token>;window.__HERMES_AUTH_REQUIRED__=false;</script></head><body>Headless backend (hermes serve): web UI disabled — use \`hermes dashboard\` for the browser UI.</body></html>`
  with `Cache-Control: no-store, no-cache, must-revalidate`. The rationale (#94227, #95575): the
  Electron shell boots by fetching `/` and extracting `window.__HERMES_SESSION_TOKEN__` for `/api/ws`
  auth (`apps/desktop/electron/dashboard-token.ts`); when headless serve 404'd every path, a renderer
  whose spawn token no longer matched the backend's live token (e.g. after `hermes update` replaced
  the backend) had no way to adopt the served token and the window white-screened. On a gated serve the
  404 JSON stays so the token is never readable without auth.
- **Inputs / options:** `hermes serve` flags: `--port PORT` (default 9119, `0` = OS-assigned),
  `--host HOST` (default `127.0.0.1`), `--insecure` (deprecated no-op), `--skip-build`, `--isolated`,
  `--stop`, `--status`, `--ssh-session-token-file PATH`, `--ssh-owner-nonce NONCE`.
- **Outputs / side effects:** No SPA; API + WS only.
- **Config / env:** `HERMES_SERVE_HEADLESS=1`.
- **Edge cases / guards:** `cmd_dashboard` pops an inherited `HERMES_SERVE_HEADLESS` for the non-serve
  path so a shell that inherited Desktop env cannot silently disable the SPA.
- **Rebuild notes:** Keep a token-only root page for a desktop shell that needs to re-adopt a rotated
  token — 404-ing everything breaks the handshake.

### Loopback session-token auth  `id: web-shell.auth-loopback-token`
- **Surface:** API
- **Where:** Every `/api/*` request when the dashboard is bound to loopback.
- **What it does:** Authenticates the browser with an ephemeral per-process token injected into the
  SPA HTML.
- **How it works:** `hermes_cli/web_server.py:588-770`.
  - `_SESSION_TOKEN = _resolve_session_token()` (`web_server.py:588-592`);
    `_SESSION_HEADER_NAME = "X-Hermes-Session-Token"`.
  - `_has_valid_session_token(request)` accepts the dedicated header (constant-time
    `hmac.compare_digest`) or the legacy `Authorization: Bearer <token>` form; the dedicated header
    exists because reverse proxies such as Caddy `basic_auth` already use `Authorization`.
  - `_QUERY_TOKEN_API_PATHS = frozenset({"/api/files/download"})` — the only route that may also
    authenticate via `?token=`, "for download links opened by the OS shell or a new browser tab where
    the session header can't be set".
  - `auth_middleware` (`web_server.py:1067-1090`) rejects any `/api/` path not in
    `PUBLIC_API_PATHS` (and not an `/api/mcp/oauth/callback/` path) with
    `{"detail": "Unauthorized"}` 401 unless the token (or the narrow query token) validates. It
    short-circuits when `request.state.token_authenticated` is set or when the OAuth gate is active.
  - `_require_token(request)` is the per-endpoint guard used by sensitive routes; in gated mode it
    defers to the cookie gate (checking `request.state.session` is present) because the token is not
    injected at all there — requiring it would 401 every cookie-authenticated request and make plugin
    install/enable/disable permanently unreachable behind the gate.
- **Inputs / options:** `X-Hermes-Session-Token` header, `Authorization: Bearer`, or `?token=` on the
  one allowed path.
- **Outputs / side effects:** 401 JSON on failure.
- **Config / env:** `HERMES_DASHBOARD_SESSION_TOKEN` (Desktop local spawns);
  `--ssh-session-token-file` / `--ssh-owner-nonce` (Desktop SSH), applied via
  `_apply_ssh_session_token` / `_apply_ssh_owner_nonce`.
- **Edge cases / guards:** The token rotates per process, which is exactly why the SPA has a one-shot
  reload on 401 (`web-shell.dashboard-auth-reload`).
- **Rebuild notes:** A per-process token in a `no-store` HTML shell is a reasonable loopback story;
  use a dedicated header, never `Authorization`.

### Auth-gate engagement rules  `id: web-shell.auth-gate-rules`
- **Surface:** API / Core
- **Where:** Startup, and on every request via `app.state.auth_required`.
- **What it does:** Decides whether the dashboard requires a real login.
- **How it works:** `hermes_cli/web_server.py:771-874`.
  - `_LOOPBACK_HOST_VALUES = frozenset({"localhost", "127.0.0.1", "::1"})`.
  - `should_require_auth(host, allow_public=False)` returns `host not in _LOOPBACK_HOST_VALUES`.
    RFC1918 / CGNAT / link-local are deliberately treated as **public** — "a hostile device on the
    same LAN is exactly the threat model the gate is designed for". `allow_public` (the legacy
    `--insecure` escape hatch) is accepted for backward compatibility with old launch scripts and
    desktop shells **but is ignored**: a non-loopback bind always requires an auth provider. The
    docstring names the reason — the June 2026 `hermes-0day` MCP-persistence campaign, where
    `--insecure --host 0.0.0.0` left the config/MCP/agent surface open to internet scanners.
  - `should_require_dashboard_auth(host, trusted_public_hosts=None)` additionally engages the gate
    when `dashboard.public_url` resolves to a non-loopback hostname, even if the backend binds to
    loopback behind a reverse proxy.
  - `_dashboard_public_hosts()` derives the trusted hostname set from `dashboard.public_url`, failing
    closed to an empty set on malformed or unset values.
  - `_desktop_loopback_auth_exempt(host, ssh_session_token, ssh_owner_nonce)` (#96490) exempts a
    Desktop-owned loopback backend from the ticket-only gate. It requires **all** of: a loopback bind,
    `HERMES_DESKTOP=1`, and an operator-minted credential
    (`HERMES_DASHBOARD_SESSION_TOKEN`, an SSH session token, or an owner nonce). A plain
    `hermes serve` with `HERMES_DESKTOP=1` exported but no credential is **not** exempt.
- **Inputs / options:** `--host`, `dashboard.public_url`, `HERMES_DESKTOP`.
- **Outputs / side effects:** `app.state.auth_required`, which changes both the middleware chain and
  the HTML injection.
- **Config / env:** `dashboard.public_url` / `HERMES_DASHBOARD_PUBLIC_URL`, `HERMES_DESKTOP`,
  `HERMES_DASHBOARD_SESSION_TOKEN`.
- **Edge cases / guards:** `0.0.0.0` / `::` binds accept any Host header because "no Host-layer
  defence can protect that mode".
- **Rebuild notes:** Make the escape hatch a documented no-op rather than removing the flag, so old
  launch scripts keep working while the hole closes.

### Host-header (DNS-rebinding) guard  `id: web-shell.host-header-guard`
- **Surface:** API
- **Where:** Every HTTP request; a mismatch returns 400 with
  `Invalid Host header. Dashboard requests must use the bound hostname or the configured public hostname.`
- **What it does:** Rejects requests whose `Host` header does not match the interface the server bound
  to, defeating DNS rebinding against a localhost dashboard (GHSA-ppp5-vxwm-4cf7).
- **How it works:** `hermes_cli/web_server.py:876-983`. `_host_header_hostname` normalises a Host
  *authority* and fails closed on quotes, angle brackets, whitespace, control characters, `://`,
  `/`, `?`, `#`, `@`, malformed IPv6 brackets, unbracketed IPv6 (ambiguous with the port separator),
  and non-numeric ports. `_is_accepted_host(host_header, bound_host, trusted_public_hosts)` accepts:
  an exact operator-declared public host; any host when bound to `0.0.0.0`/`::`; the three loopback
  aliases when bound to loopback; an exact match otherwise. The middleware reads `app.state.bound_host`
  (set by `start_server()` at listen time) and `app.state.trusted_public_hosts`.
- **Inputs / options:** the `Host` header.
- **Outputs / side effects:** 400 JSON on mismatch.
- **Config / env:** `dashboard.public_url`.
- **Edge cases / guards:** No `bound_host` on app state means the check is skipped (e.g. in tests).
- **Rebuild notes:** Validate Host at the app layer — CORS and same-origin do not help once the
  attacker hostname resolves to 127.0.0.1.

### Public (unauthenticated) API allow-list  `id: web-shell.public-api-paths`
- **Surface:** API
- **Where:** Six exact `/api/*` paths that both auth middlewares let through.
- **What it does:** Keeps liveness probes and the skin/plugin bootstrap working before login.
- **How it works:** `hermes_cli/dashboard_auth/public_paths.py:33-60`, imported by both
  `web_server.auth_middleware` and `dashboard_auth.middleware.gated_auth_middleware` so the lists
  cannot drift (they did once: `/api/status` was public under the legacy gate and 401'd under the
  OAuth gate, breaking the portal's wildcard liveness probe). Entries, matched **exactly** (no prefix
  expansion, "so adding `/api/status` doesn't accidentally expose `/api/status/secret-extension`"):
  `/api/health`, `/api/status`, `/api/config/defaults`, `/api/config/schema`, `/api/model/info`,
  `/api/dashboard/themes`, `/api/dashboard/plugins`, `/api/cron/fire`. The admission test each entry
  must pass is written down: safe to expose to external uptime probes, to the SPA before login, and to
  anyone who curls the hostname. `/api/cron/fire` is the exception — it carries its own short-lived
  NAS-minted JWT (`purpose=cron_fire`) which is the real security boundary.
- **Inputs / options:** n/a.
- **Outputs / side effects:** These endpoints answer without credentials.
- **Config / env:** n/a.
- **Edge cases / guards:** The gate additionally has prefix-matched public routes (next entry).
- **Rebuild notes:** One shared frozenset, exact matching, and a written admission test.

### Gated (cookie/OAuth) auth middleware  `id: web-shell.auth-gate-middleware`
- **Surface:** API
- **Where:** Active only when `app.state.auth_required` is true; otherwise a pass-through.
- **What it does:** Verifies a session cookie (or an RFC 8252 bearer token), transparently refreshes
  expired access tokens, and bounces unauthenticated browsers to `/login`.
- **How it works:** `hermes_cli/dashboard_auth/middleware.py:323-591`.
  - Pass-through order: not gated → next; `request.state.token_authenticated` (service caller on a
    registered token route) → next; `_path_is_public(path)` → next.
  - `_path_is_public` = exact match in `PUBLIC_API_PATHS` **or** prefix match in
    `_GATE_PUBLIC_PREFIXES` (`middleware.py:49-65`): `/auth/login`, `/auth/callback`,
    `/auth/native/authorize`, `/auth/native/token`, `/auth/native/refresh`, `/auth/password-login`,
    `/auth/logout`, `/login`, `/api/auth/providers`, `/api/mcp/oauth/callback/`, `/assets/`,
    `/favicon.ico`, `/ds-assets/`, `/fonts/`, `/fonts-terminal/`. (Prefix matching is why the
    server-rendered login page can load the DS webfonts from `/fonts/` pre-auth.)
  - **Bearer path (RFC 8252 native app):** an `Authorization: Bearer <access_token>` is verified with
    the same provider stack as the cookie; success attaches `request.state.session` with **no cookie
    read or written**; an unreachable IDP yields 503
    `{"detail": "Auth provider '<name>' unreachable"}`; a presented-but-invalid bearer returns the
    structured 401 (`reason="invalid_or_expired_session"`) rather than falling through, so the desktop
    knows to refresh.
  - **Cookie path:** cookies are `hermes_session_at` (access token, `Max-Age` ≈ 15 min),
    `hermes_session_rt` (refresh token, 30 days), `hermes_session_provider` (provider hint),
    `hermes_session_pkce` (short-lived PKCE state + CSRF nonce + provider), `hermes_sso_attempt`
    (one-shot auto-SSO loop guard) — `dashboard_auth/cookies.py:78-93`, with `__Secure-`/`__Host-`
    prefix resolution for HTTPS. With neither token present the gate first tries a silent
    auto-SSO bounce through the portal (`_auto_sso_response`, guarded against ping-pong by the
    one-shot cookie), then returns the unauthenticated response with `reason="no_cookie"`.
  - Providers are tried in order with the cookie's provider hint moved to the front by a **stable**
    sort (`_ordered_session_providers`), so a stale hint never breaks the scan. A provider must return
    `None` for tokens it does not recognise; a `ProviderError` (unreachable IDP) does not abort the
    chain — only "no provider verified AND at least one was unreachable" surfaces a 503, which
    distinguishes a transient IDP outage from a genuinely invalid token.
  - When only the refresh cookie survives (the common expiry case, because the browser evicts the
    access cookie at its `Max-Age`), verification is skipped and the refresh path runs, then the
    rotated cookies are set on the response.
  - `_unauth_response(request, reason)` (`middleware.py:112-160`): `/api/*` paths get a **401 JSON
    envelope** `{error: "unauthenticated" | "session_expired", login_url: "<prefix>/login?next=<safe>"}`
    — never a 302, because `fetch()` would follow a redirect into the cross-origin OAuth dance
    opaquely. HTML paths get a `302` to the same `login_url`. Both carry a validated same-origin
    `next=`; both honour `X-Forwarded-Prefix`.
  - `_client_ip` prefers the first `X-Forwarded-For` entry.
- **Inputs / options:** cookies, `Authorization: Bearer`.
- **Outputs / side effects:** Cookie rotation; 302/401/503 responses.
- **Config / env:** `dashboard.oauth.client_id` / `HERMES_DASHBOARD_OAUTH_CLIENT_ID`,
  `dashboard.oauth.portal_url` / `HERMES_DASHBOARD_PORTAL_URL`.
- **Edge cases / guards:** The SPA-side contract is exactly the two error codes plus `login_url`
  (`lib/api.ts:124-156`).
- **Rebuild notes:** Return a structured 401 for XHR and a 302 for navigation; make the refresh path
  work off the refresh cookie alone.

### Bearer token-auth seam (service callers)  `id: web-shell.token-auth-seam`
- **Surface:** API
- **Where:** Outermost middleware; only affects routes a token provider has registered.
- **What it does:** Lets non-interactive service callers authenticate with a bearer token on opted-in
  routes, bypassing the cookie/session gates.
- **How it works:** `hermes_cli/web_server.py:1091-1103` delegates to
  `hermes_cli/dashboard_auth/token_auth.py::token_auth_middleware`. Registered **last** so it runs
  **first** (Starlette middleware is outermost-last). A registered token route is fully owned here:
  authenticate by token, attach the principal plus `request.state.token_authenticated`, and let both
  downstream gates skip enforcement. Non-token routes pass straight through untouched. The first
  consumer is the bundled `dashboard_auth/drain` plugin, whose secret is provisioned only via
  `HERMES_DASHBOARD_DRAIN_SECRET`; a weak secret is rejected at registration (fail-closed) and the
  drain endpoint stays disabled.
- **Inputs / options:** `Authorization: Bearer <token>` on a registered route.
- **Outputs / side effects:** `request.state.token_principal`, `request.state.token_authenticated`.
- **Config / env:** `dashboard.drain_auth.scope` (default `"drain"`),
  `dashboard.drain_auth.min_secret_chars` (default `43`, ≈256 bits of url-safe base64),
  `HERMES_DASHBOARD_DRAIN_SECRET`.
- **Edge cases / guards:** Registration is fail-closed on entropy.
- **Rebuild notes:** A separate seam for machine callers keeps human-session logic uncomplicated.

### Password (bundled basic-auth) provider  `id: web-shell.auth-password`
- **Surface:** Config / API
- **Where:** The `/login` page shows a username/password form for any provider whose
  `supports_password` is true.
- **What it does:** A self-hosted "just put a password on my dashboard" gate that needs no OAuth IDP.
- **How it works:** Provider registered by `plugins/dashboard_auth/basic` when
  `dashboard.basic_auth.username` plus either `password_hash` (preferred) or `password` are set.
  `POST /auth/password-login` (`hermes_cli/dashboard_auth/routes.py:699`) takes JSON
  `{provider, username, password, next}`; `_password_rate_limited(ip)` (`routes.py:664`) throttles by
  client IP. It mints a stateless HMAC-signed session token and sets the session cookies.
- **Inputs / options:** config keys (`hermes_cli/config_defaults.py:1767-1773`):
  `dashboard.basic_auth.username` (`""` = plugin no-op),
  `dashboard.basic_auth.password_hash` (`scrypt$…`, preferred — no plaintext at rest),
  `dashboard.basic_auth.password` (plaintext fallback, hashed in memory at load),
  `dashboard.basic_auth.secret` (HMAC signing key; blank = random per-process, so sessions do not
  survive a restart or span workers), `dashboard.basic_auth.session_ttl_seconds` (`0` → plugin default
  of 12 h). Each has an env override: `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`, `_PASSWORD_HASH`,
  `_PASSWORD`, `_SECRET`, `_TTL_SECONDS`, env winning when non-empty. Hash recipe from the config
  comment: `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"`.
- **Outputs / side effects:** Session cookies; `{next}` JSON on success.
- **Config / env:** as above.
- **Edge cases / guards:** The login page's inline script maps status codes to copy:
  429 → `Too many attempts. Please wait and try again.`; 401 → `Invalid username or password.`;
  anything else → `Sign-in failed. Please try again.`; a thrown fetch → `Network error. Please try again.`
- **Rebuild notes:** Ship a password provider so self-hosters are not forced into OAuth; store a hash,
  and require an explicit signing secret for multi-worker deployments.

### Server-rendered `/login` page  `id: web-shell.login-page`
- **Surface:** Web dashboard (server-rendered)
- **Where:** `GET /login`. Browser title `Sign in — Hermes Agent`.
- **What it does:** Lists the registered session providers as sign-in affordances, with no React and
  (for OAuth-only deployments) no JavaScript at all.
- **How it works:** `hermes_cli/dashboard_auth/login_page.py`. Verbatim page copy:
  brand `Nous` + a dot + `Research`; heading `Sign in`; subtitle
  `Choose a sign-in method to continue to the Hermes Agent dashboard.`; footer
  `Public bind · Auth required`. Each OAuth provider renders
  `<a class="provider-btn" href="/auth/login?provider=<name>[&next=<encoded>]">Sign in with <Display Name></a>`;
  each password provider renders a `<form class="provider-form" data-provider="<name>" autocomplete="on">`
  with the title `Sign in with <Display Name>`, a hidden `next` field, labelled fields
  `Username` (`type=text autocomplete=username autocapitalize=none autocorrect=off spellcheck=false required`)
  and `Password` (`type=password autocomplete=current-password required`), a
  `<div class="form-error" role="alert" hidden>`, and a submit button labelled `Sign in`.
  Styling mirrors the Nous DS: `Collapse` and `Rules Compressed` webfaces loaded from `/fonts/`
  (`Collapse-Regular.woff2`, `Collapse-Bold.woff2`, `RulesCompressed-Regular.woff2`,
  `RulesCompressed-Medium.woff2`), colour tokens `--background-base: #170d02`, `--midground: #ffac02`,
  `--foreground: #ffffff`, a dot-grid backdrop built from a radial gradient plus a 3 px
  `repeating-conic-gradient`, and `::selection { background: var(--midground); color: var(--background-base) }`.
  `_PASSWORD_FORM_SCRIPT` is emitted **only** when at least one password provider is listed, so
  OAuth-only pages stay script-free; it delegates one submit handler across every form, POSTs JSON to
  `/auth/password-login` with `credentials: "same-origin"`, and navigates to `data.next || "/"`.
  When **no** providers are registered, `_EMPTY_HTML` renders instead: title
  `Sign-in unavailable — Hermes Agent`, heading `Sign-in unavailable`, body
  `This dashboard is bound to a non-loopback host but no authentication providers are available.`,
  `Configure the bundled username/password provider or an OAuth provider. See the dashboard authentication documentation for setup instructions.`
  (linking `https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard#authentication-gated-mode`)
  and `For auth-free local use, bind to 127.0.0.1 and connect through an SSH tunnel or Tailscale.`
- **Inputs / options:** `?next=<path>` (validated same-origin by the caller and HTML-escaped here as
  defence in depth); the provider buttons/forms.
- **Outputs / side effects:** Starts an OAuth round trip or a password login.
- **Config / env:** registered providers.
- **Edge cases / guards:** The class name `provider-btn` is contractually stable — the test suite
  `tests/hermes_cli/test_dashboard_auth_401_reauth.py` extracts that anchor's href to walk the flow,
  and the docstring says it "MUST NOT change without updating" that test.
- **Rebuild notes:** A JS-free login page that does not depend on the SPA build being present is the
  right call; keep the fonts on a pre-auth allow-listed path.

### Native / desktop OAuth broker (RFC 8252)  `id: web-shell.auth-native`
- **Surface:** API / Desktop app
- **Where:** `GET /auth/native/authorize`, `POST /auth/native/token`, `POST /auth/native/refresh`.
- **What it does:** Lets the desktop app sign in to a gated gateway using the system browser and a
  loopback redirect — no embedded webview, no cookies — with the gateway acting as authorization
  server to the app and OAuth client to the Nous Portal.
- **How it works:** `hermes_cli/dashboard_auth/native_flow.py` (store) + `routes.py:290, 974, 1027`.
  Wire shape:
  1. Desktop generates its own PKCE pair `(cv_d, cc_d)` and a `state`, opens a loopback listener on
     `127.0.0.1:<port>`, and sends the system browser to
     `GET /auth/native/authorize?...` carrying `cc_d`, `state` and its loopback `redirect_uri`.
  2. The gateway stashes a pending authorization (`register_pending`) keyed by an opaque
     `broker_state` and runs the existing upstream PKCE flow (`provider.start_login` → Portal
     `/oauth/authorize` → gateway `/auth/callback`). The desktop's `cc_d`/`state`/`redirect_uri` ride
     through inside the gateway's own PKCE cookie, so no desktop secret ever reaches the Portal.
  3. On the upstream callback the gateway holds a verified `Session`, mints a one-time gateway
     authorization code bound to `cc_d` (`complete_pending`), and 302s the browser to
     `<redirect_uri>?code=<gw_code>&state=<state>`.
  4. The desktop POSTs `/auth/native/token` with `gw_code` + `cv_d`; the gateway verifies
     `SHA256(cv_d) == cc_d` (`redeem_code`), consumes the code (single use), and returns the upstream
     `access_token` / `refresh_token` / `expires_at` **in the JSON body**.
  5. The desktop stores them in the OS keychain and authenticates REST with
     `Authorization: Bearer <access_token>` through the token seam, minting ws-tickets the same way.
  Password providers ride the same broker with step 2 swapped: `/auth/native/authorize` sends the
  browser to the interactive `/login` form (broker_state in the PKCE cookie) and a successful
  `/auth/password-login` plays the role of the upstream callback. The stated point of brokering a
  password login at all is that the system browser can autofill from the OS password manager, which
  no embedded webview can.
  `_validate_loopback_redirect_uri` (`routes.py:254`) constrains the redirect target.
- **Inputs / options:** `code_challenge`, `state`, `redirect_uri`, `code`, `code_verifier`,
  `refresh_token`.
- **Outputs / side effects:** Tokens in the JSON body; no cookies for this path.
- **Config / env:** the Portal client id / URL keys.
- **Edge cases / guards:** PKCE binding (RFC 7636) means an intercepted loopback `gw_code` is useless
  without `cv_d`; `redeem_code` pops the entry so a replay finds nothing.
- **Rebuild notes:** Broker the flow at the gateway when the IDP will not accept a loopback redirect;
  never put an IDP webview inside a desktop app.

### SSH-owned backend credentials  `id: web-shell.auth-ssh`
- **Surface:** CLI / API
- **Where:** `hermes serve --ssh-session-token-file PATH --ssh-owner-nonce NONCE`.
- **What it does:** Lets the Desktop app own a remote backend over SSH with a one-shot session token
  and an owner nonce, instead of a browser session.
- **How it works:** `hermes_cli/web_server.py:594-657` holds `_SSH_OWNER_NONCE`,
  `_SSH_RUNTIME_PURELIB`, `_SSH_RUNTIME_MARKER`, with `_apply_ssh_session_token(token)`,
  `_apply_ssh_owner_nonce(nonce)` and `_ssh_runtime_intact()`. `GET /api/ssh/ownership`
  (`web_server.py:3667`) reports ownership. The CLI validates the nonce as 16 lowercase hex characters
  (`hermes_cli/main.py:12026-12028`, error `--ssh-owner-nonce must be 16 lowercase hex characters`),
  refuses `--ssh-session-token-file` together with `--status`/`--stop`
  (`--ssh-session-token-file cannot be used with --status or --stop`) and outside `hermes serve`
  (`--ssh-session-token-file is only valid with hermes serve`), then reads the token from the file.
- **Inputs / options:** `--ssh-session-token-file PATH`, `--ssh-owner-nonce NONCE`.
- **Outputs / side effects:** Replaces the process session token; marks the process Desktop-owned.
- **Config / env:** `HERMES_DESKTOP=1`.
- **Edge cases / guards:** Feeds `_desktop_loopback_auth_exempt`, which requires the credential to be
  present — a bare `HERMES_DESKTOP=1` is not enough.
- **Rebuild notes:** One-shot file-delivered tokens avoid putting a credential on the command line
  where `ps` can read it.

### `hermes dashboard` command and its flags  `id: web-shell.cli-dashboard`
- **Surface:** CLI
- **Where:** `hermes dashboard [...]`. Help text verbatim:
  `Launch the Hermes Agent web dashboard for managing config, API keys, and sessions`.
- **What it does:** Builds (unless skipped) and starts the dashboard server, opens a browser, or
  manages running dashboards.
- **How it works:** `hermes_cli/main.py:11995+ cmd_dashboard`.
- **Inputs / options:** all 8 options plus one sub-command, transcribed from the live
  `hermes dashboard --help`:
  - `-h, --help` — show the help message and exit.
  - `--port PORT` — `Port (default 9119, 0 for auto-assign by OS)`.
  - `--host HOST` — `Host (default 127.0.0.1)`.
  - `--insecure` — `DEPRECATED / NO-OP. Formerly bypassed auth on a non-loopback bind. As of the June
    2026 hardening it no longer disables authentication — a public bind always requires an auth
    provider (password or OAuth). Bind 127.0.0.1 + tunnel to keep it local.`
  - `--skip-build` — `Skip the web UI build step and serve the existing dist directly. Useful for
    non-interactive contexts (Windows Scheduled Tasks, CI) where npm may not be available. Pre-build
    with: cd web && npm run build`
  - `--isolated` — `When launched from a named profile, run a dedicated server scoped to that profile
    instead of routing to the machine-level server. Default behavior is unified: profile launches
    attach to (or start) ONE machine-level server and preselect the profile.`
  - `--stop` — `Stop all running Hermes web server processes and exit`.
  - `--status` — `List running Hermes web server processes and exit`.
  - `--no-open` — `Don't open browser automatically`.
  - sub-command `register` — `Register a self-hosted dashboard with Nous Portal (writes the OAuth
    client ID to .env)` (`cmd_dashboard_register`, `main.py:12318`).
  Internal/undocumented flags threaded through the re-exec: `--open-profile <name>`,
  `--ssh-session-token-file PATH`, `--ssh-owner-nonce NONCE`, `--headless-backend`.
- **Outputs / side effects:** A listening server, an opened browser tab, or process management output.
- **Config / env:** `HERMES_HOME`, `HERMES_WEB_DIST`, `HERMES_DESKTOP`, `HERMES_SERVE_HEADLESS`.
- **Edge cases / guards:** `--status` always exits 0 (informational); `--stop` exits 1 only if
  processes survived the SIGTERM-grace-SIGKILL sequence. Environment sanitising
  (`main.py:12030-12053`) strips an inherited Electron-packaged `HERMES_WEB_DIST` when
  `HERMES_DESKTOP != "1"` — otherwise a shell that inherited Desktop env would serve the desktop
  renderer and show "Desktop IPC bridge is unavailable" (#52945) — and pops an inherited
  `HERMES_SERVE_HEADLESS` on the non-serve path.
- **Rebuild notes:** Ship `--status`/`--stop` with the server command; sanitise inherited env from a
  parent GUI process.

### Unified profile launch routing (`/?profile=`)  `id: web-shell.profile-routing`
- **Surface:** CLI / Web dashboard
- **Where:** Running `hermes dashboard` from a named profile.
- **What it does:** Routes a per-profile dashboard launch to the single machine dashboard with that
  profile preselected in the switcher, instead of starting a second server.
- **How it works:** `hermes_cli/main.py:12053-12153`. The gate fires when the active profile is not
  `default`/`custom`, `--isolated` is absent, `--open-profile` is absent, and `HERMES_DESKTOP != "1"`
  (Desktop pool backends are intentionally per-profile). Then:
  - if a dashboard is already listening on the target host/port, it prints
    `Machine dashboard already running on port <port>.` and
    `  Managing profile '<name>': <url>` and opens
    `http://<host>:<port>/?profile=<name>` unless `--no-open`, then exits 0;
  - otherwise it prints
    `Routing to the machine dashboard (profile '<name>' preselected). Use --isolated for a dedicated per-profile server.`
    and re-execs `python -m hermes_cli.main -p default {dashboard|serve} --port … --host … --open-profile <name>`
    (propagating `--ssh-owner-nonce`, `--ssh-session-token-file`, `--no-open`, `--insecure`,
    `--skip-build`), with `HERMES_HOME` pinned to `get_default_hermes_root()` so the child sees the
    machine root (in the Docker layout that is `/opt/data`; simply dropping `HERMES_HOME` would land
    on `$HOME/.hermes` = `/opt/data/.hermes`, an empty auto-seeded home).
  On Windows the re-exec uses `subprocess.Popen` + `sys.exit(proc.wait())` instead of `os.execvpe`,
  because under Python 3.14+ `execvpe` can crash with `STATUS_ACCESS_VIOLATION (0xC0000005)`.
  The SPA side of this contract is `ProfileProvider`, which reads `?profile=` on first load
  (`web-shell.profile-provider`).
  Note the dashboard server itself has **no** `/p/{profile}` route — that URL prefix belongs to the
  gateway's aiohttp API-server platform (`gateway/platforms/api_server.py:7772`) and webhook platform
  (`gateway/platforms/webhook.py:298`); requesting it on the dashboard port just returns the SPA.
- **Inputs / options:** `--isolated` opts out; `--open-profile <name>` is the internal preselect flag.
- **Outputs / side effects:** Either a browser open + exit, or a re-exec.
- **Config / env:** `HERMES_HOME`, `HERMES_DESKTOP`.
- **Edge cases / guards:** `apply_nofile_soft_limit()` is applied *after* routing so a named profile's
  higher limit cannot leak into the machine dashboard.
- **Rebuild notes:** One machine-level management surface with a per-request scope beats N servers;
  keep an `--isolated` escape hatch.

### Dashboard health counters and self-test  `id: web-shell.dashboard-health`
- **Surface:** API
- **Where:** The `components` dict on `GET /api/status`.
- **What it does:** Tracks in-process error and self-test counts so a degraded dashboard is visible on
  the (public) status endpoint without leaking details.
- **How it works:** `hermes_cli/web_server.py:1112-1240`. `DashboardHealth` keeps a
  300 s window (`_DASHBOARD_HEALTH_WINDOW_SECONDS = 300.0`) with `record_error(exc_type, path)`,
  `record_selftest(passed, http_status)`, `recent_error_count()` and `snapshot()`.
  `_dashboard_health_middleware` records exceptions per request. A background loop
  (`_dashboard_selftest_loop`) hits `_DASHBOARD_SELFTEST_ROUTE = "/api/sessions?limit=1"` every
  `_DASHBOARD_SELFTEST_INTERVAL_SECONDS = 60.0`. Because `/api/status` is public, the module comment
  is explicit that "everything exported from here must be counts and enums only: no exception
  messages, no request paths, no tokens".
- **Inputs / options:** n/a.
- **Outputs / side effects:** Counters on `/api/status`.
- **Config / env:** n/a.
- **Edge cases / guards:** The self-test route is a cheap authenticated read done in-process.
- **Rebuild notes:** Self-test from inside the process and expose only counts on a public endpoint.

---

## 9. Static assets, keyboard surface, toasts, and cross-surface notes

### Static assets shipped with the SPA (`web/public/`)  `id: web-shell.static-assets`
- **Surface:** Web dashboard
- **Where:** Copied verbatim into `hermes_cli/web_dist/` by the build and served from the site root.
- **What it does:** Supplies the favicon and every self-hosted webfont, so neither the dashboard nor
  the server-rendered login page depends on an external font CDN.
- **How it works:** Complete listing of `web/public`:
  | file | served at | used by |
  |---|---|---|
  | `favicon.ico` | `/favicon.ico` | `index.html` `<link rel="icon" type="image/svg+xml">`; also in the gate's public prefix list |
  | `fonts/Collapse-Regular.woff2` | `/fonts/Collapse-Regular.woff2` | Nous DS body face; login page `@font-face` |
  | `fonts/Collapse-Bold.woff2` | `/fonts/Collapse-Bold.woff2` | Nous DS bold; login page |
  | `fonts/RulesCompressed-Regular.woff2` | `/fonts/RulesCompressed-Regular.woff2` | DS display face; login page |
  | `fonts/RulesCompressed-Medium.woff2` | `/fonts/RulesCompressed-Medium.woff2` | DS display medium; login page headings |
  | `fonts/RulesExpanded-Regular.woff2` | `/fonts/RulesExpanded-Regular.woff2` | DS expanded face (`font-expanded`, used by the page-header `<h1>`) |
  | `fonts/RulesExpanded-Bold.woff2` | `/fonts/RulesExpanded-Bold.woff2` | DS expanded bold |
  | `fonts/Mondwest-Regular.woff2` | `/fonts/Mondwest-Regular.woff2` | `font-mondwest` (dialog titles, plugin-page copy) |
  | `fonts-terminal/JetBrainsMono-Regular.woff2` | `/fonts-terminal/JetBrainsMono-Regular.woff2` | xterm.js terminal (`index.css:23-29`) |
  | `fonts-terminal/JetBrainsMono-Bold.woff2` | `/fonts-terminal/JetBrainsMono-Bold.woff2` | terminal bold |
  | `fonts-terminal/JetBrainsMono-Italic.woff2` | `/fonts-terminal/JetBrainsMono-Italic.woff2` | terminal italic |
  A fourth asset root, `/ds-assets/`, is referenced by the built CSS and by the prefix rewriter
  (`web_server.py:17939-17940`, `17974`) and comes from the `@nous-research/ui` package's `dist`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `/fonts/`, `/fonts-terminal/`, `/ds-assets/`, `/assets/` and
  `/favicon.ico` are all in `_GATE_PUBLIC_PREFIXES`, which is why the gated login page renders with
  brand fonts before authentication.
- **Rebuild notes:** Self-host the brand faces and allow-list their paths pre-auth, or the login page
  falls back to a system stack.

### Keyboard surface of the shell (and the absence of a command palette)  `id: web-shell.keyboard-surface`
- **Surface:** Web dashboard
- **Where:** Global.
- **What it does:** The shell has **no command palette, no global search box, and no global hotkeys**.
  This is a deliberate negative fact for a mechanical checker: grepping `web/src` for global key
  listeners finds only modal/drawer Escape handlers and per-field handlers.
- **How it works:** Complete inventory of document/window-level key handling in the shell and shared
  components:
  | binding | scope | effect | source |
  |---|---|---|---|
  | `Escape` | while the mobile nav drawer is open | closes the drawer | `App.tsx:489-502` |
  | `Escape` | while the theme menu is open | closes it | `ThemeSwitcher.tsx:38-45` |
  | `Escape` | while the language menu is open | closes it | `LanguageSwitcher.tsx:38-45` |
  | `Escape` | while the local `ConfirmDialog` is open | cancels (with `preventDefault`) | `ConfirmDialog.tsx:40-47` |
  | `Escape` | any modal using `useModalBehavior` | calls `onClose` (with `preventDefault`) | `hooks/useModalBehavior.ts:25-32` |
  | `Escape` | while `ModelPickerDialog` is open | closes the picker (it owns the key; the outer modal defers via `shouldCloseOuterModalOnEscape`) | `ModelPickerDialog.tsx:202`, `lib/dashboard-modal-shell.ts:25-29` |
  | `Enter` | OAuth code field | submits the PKCE code | `OAuthLoginModal.tsx:248` |
  Page-local handlers (out of scope here, listed so nothing looks missing):
  `pages/ChatPage.tsx:441` and `:848` (terminal keys and the IME composition guard, shard web-a),
  `pages/EnvPage.tsx:578`, `pages/ProfileBuilderPage.tsx:464`, `pages/SessionsPage.tsx:649` and
  `:1653`, `pages/FilesPage.tsx:480`, `pages/ProfilesPage.tsx:850` and `:1043`,
  `pages/SkillsPage.tsx:1015`. Inside the embedded terminal, `lib/pty-keyboard-shortcuts.ts` adds
  copy/paste and word-delete handling (shard web-a). `SlashPopover` handles arrows/Tab/Enter but only
  through the composer's delegated `handleKey`.
- **Inputs / options:** as tabulated.
- **Outputs / side effects:** none beyond closing overlays.
- **Config / env:** n/a.
- **Edge cases / guards:** Nested overlays are resolved by an explicit predicate rather than by
  listener ordering.
- **Rebuild notes:** The obvious improvement is a `Cmd/Ctrl-K` palette over the 18 routes, the 785
  config keys and the session list — the data for it already exists client-side (`lib/fuzzy.ts` is
  already a ranked matcher).

### Toasts  `id: web-shell.toasts`
- **Surface:** Web dashboard
- **Where:** Transient notifications; the shell-level one is rendered by `SystemActionsProvider` so it
  survives navigation.
- **What it does:** Reports the outcome of an action without blocking.
- **How it works:** The Nous DS `Toast` component (`@nous-research/ui/ui/components/toast`).
  - Shell instance: `contexts/SystemActions.tsx:128` renders `<Toast toast={toast}/>` as a sibling of
    `children`, with state `{message, type: "success" | "error"}` auto-cleared after **4000 ms**
    (`SystemActions.tsx:29-33`). Messages it can raise: `Finished` (`i18n: status.actionFinished`),
    `` `Action failed (exit <code>)` ``, `` `Action failed: <detail>` ``, and the
    update-not-applicable message from the server (`resp.message` plus two spaces and
    `resp.update_command`, defaulting to `Updates don't apply from this dashboard.`).
  - Page instances use the DS `useToast()` hook, which returns `{showToast, toast}` where
    `showToast(message, 'success'|'error')` replaces the current toast; it is also re-exported to
    plugins through the SDK.
  - Animations `toast-in` / `toast-out` (16 px horizontal slide) are declared in `index.css:197-204`.
- **Inputs / options:** message text and type.
- **Outputs / side effects:** A transient overlay.
- **Config / env:** n/a.
- **Edge cases / guards:** One toast at a time; a new one replaces the old.
- **Rebuild notes:** Put the long-running-action toast in a provider above the router so navigating
  away does not lose the result.

### Dialog and overlay z-index bands  `id: web-shell.z-bands`
- **Surface:** Web dashboard
- **Where:** Invisible; determines what covers what.
- **What it does:** Keeps overlays layered predictably across shell chrome, page modals and
  confirmations.
- **How it works:** Bands actually in use:
  | z-index | element | source |
  |---|---|---|
  | `z-0` | `backdrop` plugin slot (fixed, `pointer-events-none`) | `App.tsx:520-525` |
  | `z-1` | page header bar | `contexts/PageHeaderProvider.tsx:56` |
  | `z-2` | routed content column (creates a stacking context — the reason overlays must be portalled) | `App.tsx:754` |
  | `z-40` | mobile top bar and the mobile nav scrim | `App.tsx:529`, `App.tsx:562` |
  | `z-50` | the sidebar `<aside>`; non-`dropUp` picker dropdowns | `App.tsx:581`, `ThemeSwitcher.tsx:125`, `LanguageSwitcher.tsx:114` |
  | `z-[100]` | collapsed-rail tooltips; `dropUp` picker dropdowns; `DASHBOARD_MODAL_BACKDROP` | `App.tsx:1317`, `ThemeSwitcher.tsx:125`, `lib/dashboard-modal-shell.ts:16` |
  | `z-[200]` | the local `ConfirmDialog` backdrop | `components/ConfirmDialog.tsx:69` |
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `z-[100]` alone cannot escape the `relative z-2` content column, so every
  overlay above the page must `createPortal(..., document.body)`.
- **Rebuild notes:** Publish the bands as named tokens; the current mix of Tailwind scale values and
  arbitrary `z-[…]` values is easy to get wrong.

### `@hermes/shared` — the cross-surface client package  `id: web-shell.hermes-shared`
- **Surface:** Web dashboard / Desktop app / Core
- **Where:** Imported as `@hermes/shared`, aliased in `vite.config.ts:81` to `../apps/shared/src` and
  declared in `package.json` as `"@hermes/shared": "file:../apps/shared"`.
- **What it does:** Holds the pieces the dashboard and the desktop app must implement identically —
  the WebSocket URL builder and the JSON-RPC gateway client.
- **How it works:** The dashboard uses two exports:
  - `buildHermesWebSocketUrl({authParam, basePath, params, path})` — used by `lib/api.ts:284` and
    `lib/gatewayClient.ts:56`; turns a dashboard-relative path plus an auth `[name, value]` pair into
    an absolute `ws(s)://` URL honouring the base path.
  - `JsonRpcGatewayClient` plus the types `ConnectionState`, `GatewayEvent`, `GatewayEventName` —
    subclassed by `GatewayClient` (`lib/gatewayClient.ts:29`).
- **Inputs / options:** per export.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Because it is a `file:` dependency, a stale `apps/shared` build breaks both
  surfaces at once — the alias points at `src` so Vite compiles it directly.
- **Rebuild notes:** Share the protocol client, not just the protocol document; it is what keeps the
  TUI, dashboard and desktop honest about the same JSON-RPC dialect.

### Web themes vs. CLI/TUI/desktop "skins" (two separate systems)  `id: web-shell.themes-vs-skins`
- **Surface:** Core / Docs
- **Where:** `hermes skin …` (CLI) versus the dashboard theme picker.
- **What it does:** Disambiguates two similarly-named theming systems that do **not** share files,
  names, or storage.
- **How it works:**
  - **Dashboard themes** — this shard. Built-ins in `web/src/themes/presets.ts`; user themes in
    `~/.hermes/dashboard-themes/*.yaml`; active name in `config.yaml` `dashboard.theme`; applied as
    CSS variables by `ThemeProvider`; endpoints `/api/dashboard/themes` and `/api/dashboard/theme`.
  - **Skins** — `hermes_cli/skin_engine.py` (plus `hermes_cli/skin_cmd.py` and
    `hermes_cli/subcommands/skin.py`). Its own docstring: "A data-driven skin system that lets users
    (and Hermes itself) customize the visual appearance across the CLI, the TUI, and the desktop GUI
    from a single file. Skins are defined as YAML files in `~/.hermes/skins/` or as built-in presets."
    The gateway pushes the resolved palette to the TUI and desktop via `resolve_skin` /
    `skin.changed`. Its colour keys are Rich-markup oriented (`background`, `banner_border`,
    `banner_title`, `banner_accent`, `banner_dim`, `banner_text`, `ui_accent`, `ui_label`, `ui_ok`,
    `ui_error`, `ui_warn`, `ui_tool`, `ui_thinking`, …) and built-ins include `ares`, `slate`,
    `daylight` and an ocean-god theme. CLI surface: `hermes skin list`, `hermes skin use`,
    `hermes skin set <key> '<#hex>'`.
  - **The web dashboard is not a skin consumer.** A skin dropped in `~/.hermes/skins/` themes the CLI,
    TUI and desktop GUI; it does not change the browser dashboard, which needs a
    `~/.hermes/dashboard-themes/*.yaml` instead.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `dashboard.theme` (web) vs. the skin engine's active-skin state (CLI/TUI/desktop).
- **Edge cases / guards:** The naming collision is a real usability trap: "theme" in `config.yaml`
  under `dashboard:` is the web one; `hermes skin` is everything else.
- **Rebuild notes:** Unify the two, or at minimum make each surface's picker say which file it reads.
  Skin-engine internals are handed off to the CLI shard.

### `web/README.md` — the developer contract  `id: web-shell.web-readme`
- **Surface:** Docs
- **Where:** `web/README.md`.
- **What it does:** Tells a contributor how to run the dashboard with hot reload and why the built
  bundle and the dev server are different things.
- **How it works:** Verbatim points: stack is **Vite** + **React 19** + **TypeScript**, **Tailwind CSS
  v4** with a custom dark theme, and "**shadcn/ui**-style components (hand-rolled, no CLI
  dependency)". Development flow: start the backend with
  `python -m hermes_cli.main web --no-open`, then `cd web/ && npm install && npm run dev`, and open the
  Vite URL (usually `http://localhost:5173`) — "That is the live-reload UI." It then states the trap
  explicitly: "`hermes dashboard` on port 9119 serves the **built** bundle from
  `hermes_cli/web_dist/`, not the Vite dev server — changes in `web/src/` will not appear there until
  you run `npm run build` and restart the dashboard". Build: `npm run build` outputs to
  `../hermes_cli/web_dist/`, "which the FastAPI server serves as a static SPA. The built assets are
  included in the Python package via `pyproject.toml` package-data."
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** the Vite proxy sends `/api` to `http://127.0.0.1:9119`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Write down the built-vs-dev distinction; it is the single most common confusion
  in a Python-serves-SPA layout.

---

## 10. Coverage notes for a mechanical checker

- **i18n**: all **714** English keys in `web/src/i18n/en.ts` are transcribed in §4, grouped by their
  18 namespaces (`common` 45, `app` 43, `status` 36, `sessions` 42, `analytics` 23, `models` 9,
  `logs` 7, `cron` 54, `profiles` 58, `pluginsPage` 36, `skills` 20, `config` 35, `env` 26,
  `oauth` 36, `language` 1, `theme` 8, `achievements` 67, `kanban` 168). The evidence bundle's
  `string_catalogs.json` under-reports this as 656 because its scanner skips multi-line template
  literals and the one array value (`cron.scheduleModes.weekdaysShort`).
- **Locales**: 17 total. 15 are full object literals (`af`, `de`, `es`, `fr`, `ga`, `hu`, `it`, `ja`,
  `ko`, `pt`, `ru`, `tr`, `uk`, `zh`, `zh-hant`), 1 uses the partial-override helper (`ar`, via
  `defineLocale`), plus the English reference (`en`).
- **Components**: all 27 files under `web/src/components/` are documented (8 in §2–§3, 19 in §6),
  plus the 2 colocated test files.
- **Contexts / hooks**: all 9 files under `web/src/contexts/` and both files under `web/src/hooks/`
  are documented.
- **Themes**: all 5 files under `web/src/themes/` are documented; all 8 built-in themes are
  transcribed with their full palettes, typography, layout and overrides; all 14 catalog fonts plus
  the `theme` sentinel are listed.
- **lib/**: all 36 non-test modules under `web/src/lib/` appear in the index table
  (`web-shell.lib-index`), with 10 of them fully specified in their own entries.
- **plugins/**: all 6 non-test files under `web/src/plugins/` are documented, along with the 30
  slot names, the full SDK surface, and both bundled plugin pages.
- **Routes**: all 20 built-in route paths, the 18 (or 19 with Analytics) sidebar items and the 2
  plugin tabs are enumerated.
- **Live verification**: nav labels, theme list, font list, language list, the two confirm dialogs,
  the collapsed rail, the mobile drawer, the unknown-route redirect, `/kanban` and `/achievements`
  were all exercised against the running instance at `http://127.0.0.1:9119`; artefacts in
  `hermes_inv/web_crawl_shell/` (`shell.json` plus 8 PNGs) and `hermes_inv/web_crawl/`.

## Handoffs

- `/models` page (Model Settings card, auxiliary-task modal, MoA presets) — covered by shard `web-a`.
- `/sessions`, `/files`, `/analytics`, `/chat` pages — shard `web-a`.
- `/logs`, `/cron`, `/skills`, `/plugins`, `/mcp` pages — shard `web-b`.
- `/config` and `/env` (Keys) pages — shards `config-a` / `config-b`.
- `/docs` page (documentation iframe host, `DocsPage.tsx`, `app.openDocumentation` string) — **not
  covered by any shard I can see**; needs an owner.
- `/system` page (`SystemPage.tsx`: doctor, security audit, backup, import, hooks, curator, portal,
  prompt-size, dump, config-migrate, debug-share, checkpoints, and the `HermesConsoleModal` host) —
  needs an owner.
- `/channels` page (`ChannelsPage.tsx`, messaging platforms, Telegram/WhatsApp onboarding) — needs an
  owner.
- `/webhooks` page (`WebhooksPage.tsx`) — needs an owner.
- `/pairing` page (`PairingPage.tsx`, pairing whitelist, QR/deep-link) — needs an owner.
- `/profiles` and `/profiles/new` pages (`ProfilesPage.tsx`, `ProfileBuilderPage.tsx`) — needs an
  owner; the `profiles` i18n namespace (58 keys) is transcribed here in §4.
- `hermes_cli/skin_engine.py` / `skin_cmd.py` / `subcommands/skin.py` and `hermes skin list|use|set`
  (CLI/TUI/desktop skins, `~/.hermes/skins/*.yaml`) — CLI shard; §9 only disambiguates it from web
  themes.
- `apps/desktop` (Electron shell, its own 2354-key i18n catalog, `dashboard-token.ts` handshake) —
  desktop shard.
- `ui-tui` (Ink TUI, `ui-tui/src/lib/fuzzy.ts` which is the sibling copy of `web/src/lib/fuzzy.ts`,
  `ui-tui/src/components/modelPicker.tsx` which `ModelPickerDialog` mirrors) — TUI shard.
- `gateway/platforms/api_server.py` `/p/{profile}<path>` and `gateway/platforms/webhook.py`
  `/p/{profile}/webhooks/{route_name}` — gateway shard. The dashboard server has no `/p/` route; that
  prefix belongs to the aiohttp API-server platform.
- `plugins/kanban/dashboard/plugin_api.py` (3100 lines) and
  `plugins/hermes-achievements/dashboard/plugin_api.py` (1092 lines) backend semantics beyond the
  route lists and the achievement catalog transcribed here — plugin/backend shard.
- `hermes_cli/dashboard_auth/{audit,base,cookies,registry,routes,token_auth}.py` internals beyond the
  gate behaviour documented in §8 — auth shard.
- `POST /api/console` server side (the counterpart of `HermesConsoleModal`) — System-page or gateway
  shard.
- `dashboard.turn_isolation`, `dashboard.compute_host_heartbeat_secs`,
  `dashboard.compute_host_respawn_max`, `dashboard.trusted_proxies`, `dashboard.ws_ping_interval`,
  `dashboard.ws_ping_timeout`, `dashboard.ws_orphan_reap_grace_s`,
  `dashboard.startup_orphan_sweep` — config keys under `dashboard:` that do not affect the SPA shell;
  owned by the config shards.
