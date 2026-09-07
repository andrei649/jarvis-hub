# Gap-fill — Desktop Settings 4: Execution backend picker (Capabilities → terminal toolset)

Scope: the Electron desktop app's **Execution backend** panel — the `TerminalBackendPanel` React
component mounted inside the `terminal` toolset detail on the Capabilities/Skills page, which lists
every terminal execution backend with a live health probe and writes `terminal.backend` to
`config.yaml`. This shard documents that panel end to end: every rendered string, pill, row, toast,
button and guard, plus the two HTTP endpoints it drives and their server-side probes. It deliberately
leaves the surrounding toolset detail page (`ToolsetDetail`, tool chips, "Needs keys" pill, generic
`ToolsetConfigPanel`) to `desktop-b.md`, the raw `terminal.*` config keys to `config-a.md`/`config-b.md`,
the terminal tool itself to `tools.md`, and the bare REST payload shape to `media.md`
(`media.api-terminal-backends`).

### Execution backend picker (desktop Capabilities → terminal)  `id: gapfill-desktop-settings-4-r0.terminal-backend-panel`
- **Surface:** Desktop app
- **Where:** Desktop app → **Capabilities / Skills** page → open the **terminal** toolset → detail pane,
  below the browser/computer-use panels and above the generic toolset config editor. Mounted at
  `apps/desktop/src/app/skills/index.tsx:1174` — `{toolset.name === 'terminal' && <TerminalBackendPanel onConfiguredChange={onConfiguredChange} />}`
  (imported at `apps/desktop/src/app/skills/index.tsx:61`). The section header reads **“Execution backend”**
  (`i18n: settings.toolsets.terminalBackend.sectionTitle`, `apps/desktop/src/i18n/en.ts:1241`,
  rendered at `apps/desktop/src/app/settings/terminal-backend-panel.tsx:116`), with a refresh icon button
  (`RefreshCw`, no text label) on the same row at `terminal-backend-panel.tsx:117-119`.
- **What it does:** Shows one clickable row per terminal execution backend (Local, Docker,
  Singularity/Apptainer, Modal, Daytona, SSH, plus any plugin-registered backend), each carrying a live
  readiness probe. Clicking a row makes that backend the active one for terminal commands by writing
  `terminal.backend` into `config.yaml`. A backend that still needs setup can be selected anyway — the row
  shows what is missing instead of blocking.
- **How it works:** `apps/desktop/src/app/settings/terminal-backend-panel.tsx:48 TerminalBackendPanel`.
  On mount, `refresh()` (`:55-65`) sets `loading` and calls `getTerminalBackends()`
  (`apps/desktop/src/api/toolsets.ts:112`) → `GET /api/tools/terminal/backends` with the current
  profile scope (`profileScoped()`), storing `TerminalBackendsResponse` `{active, backends[]}` in state
  (`apps/desktop/src/types/hermes.ts:1100-1116`: `TerminalBackendInfo {name, label, description, active,
  status, detail}`, `TerminalBackendStatus = 'ready' | 'needs_setup' | 'unavailable'`). A fetch failure is
  swallowed into a toast via `notifyError(err, copy.failedLoad)` (`terminal-backend-panel.tsx:61`), so the
  panel never throws. `handleSelect(backend)` (`:71-98`) is a no-op when the row is already `active` or a
  selection is in flight (`selecting !== null`); otherwise it sets `selecting = backend.name`, calls
  `selectTerminalBackend(backend.name)` (`apps/desktop/src/api/toolsets.ts:119`) →
  `PUT /api/tools/terminal/backend` with body `{backend}`, then **mirrors the write locally** — rewriting
  `data.active` and each row's `active` flag without a refetch (`:82-90`, because probes are unchanged by a
  select) — fires the success toast (`:91`) and calls `onConfiguredChange?.()` (`:92`) so the parent toolset
  list re-reads its derived pills. Server side: `hermes_cli/web_routers/tools.py:717 get_terminal_backends`
  loads config inside `_profile_scope`, reads `terminal.backend` (defaulting to `local`, and falling back to
  `local` when the stored value is not a known backend name), and for each row calls
  `_probe_terminal_backend(name, terminal_cfg)`; `hermes_cli/web_routers/tools.py:754 select_terminal_backend`
  lower-cases/strips the requested name, validates it against `_terminal_backend_names()`, then writes
  `config["terminal"]["backend"]` under `_CONFIG_MUTATION_LOCK` via `save_config`. The row table is
  `hermes_cli/web_server.py:15428 _TERMINAL_BACKENDS` (built-ins) concatenated at request time with
  `_plugin_terminal_backend_rows()` (`web_server.py:15464`, which calls `discover_plugins()` then
  `agent.terminal_env_registry.list_providers()`), so a plugin installed after server start still appears
  (`_terminal_backend_rows()`, `web_server.py:15490`). Probes (`web_server.py:15517-15627`): `local` → always
  `("ready", "")`; `docker` → `shutil.which("docker")` then `docker info --format {{.ServerVersion}}` with a
  2 s timeout; `singularity` → `which singularity` or `which apptainer`; `ssh` → `terminal.ssh_host` /
  `terminal.ssh_user` from config or `TERMINAL_SSH_HOST` / `TERMINAL_SSH_USER` env, detail `"{user}@{host}"`
  when ready; `modal` → `tools.tool_backend_helpers.has_direct_modal_credentials()` or
  `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`; `daytona` → `DAYTONA_API_KEY`; anything else →
  `agent.terminal_env_registry.get_provider(name).probe()`. Toasts come from
  `apps/desktop/src/store/notifications.ts` — `notify({kind:'success', …})` auto-dismisses after 5 000 ms and
  lands in the quiet **bottom-right** placement (`notifications.ts:52-73`), while `notifyError(error, fallback)`
  (`notifications.ts:192-201`) builds `{kind:'error', title: fallback, message: readableError(...).message,
  detail}` which is sticky (duration 0) and top-center.
- **Inputs / options:** Every interactive element and rendered string of the panel, in render order:
  1. **Section header row** (`terminal-backend-panel.tsx:115-120`): text **“Execution backend”**
     (`i18n: settings.toolsets.terminalBackend.sectionTitle`); **refresh button** — icon-only `RefreshCw`,
     `size="sm" variant="text"`, `disabled={loading}`, spins (`animate-spin`) while loading, `onClick` re-runs
     `refresh()` (re-probes every backend).
  2. **Loading state** (`:100-107`, shown only while `loading && !data`): spinner + **“Checking execution backends…”**
     (`i18n: settings.toolsets.terminalBackend.loading`, `en.ts:1241`). When `data` is still `null` after a failed
     load the component renders **nothing** (`:109-111`).
  3. **One backend row per entry** — a `<button type="button">` with `aria-pressed={backend.active}`,
     `disabled={selecting !== null}` (all rows lock while any selection is in flight), active rows styled
     `border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary)` and inactive rows `border-transparent
     bg-background/55 hover:bg-accent/40` (`:122-135`). Row contents:
     - **Backend label** (`backend.label`, `:137`) — verbatim built-ins: **“Local”**, **“Docker”**,
       **“Singularity / Apptainer”**, **“Modal”**, **“Daytona”**, **“SSH”** (`web_server.py:15428-15459`).
     - **Status pill** (`StatusPill`, `:19-38`): **“Ready”** (`i18n: settings.toolsets.terminalBackend.ready`,
       `en.ts:1243`, `Pill tone="primary"` + `Check` icon) when `status === 'ready'`; otherwise a
       `Pill tone="muted"` + `AlertTriangle` icon showing **“Needs setup”**
       (`i18n: settings.toolsets.terminalBackend.needsSetup`, `en.ts:1244`) for `status === 'needs_setup'` or
       **“Unavailable”** (`i18n: settings.toolsets.terminalBackend.unavailable`, `en.ts:1245`) for
       `status === 'unavailable'`.
     - **Active pill** (`:139-144`): **“In use”** (`i18n: settings.toolsets.terminalBackend.inUse`,
       `en.ts:1246`, `Pill tone="primary"` + `Check`) rendered only on the row where `backend.active` is true.
     - **In-flight spinner** (`:145`): `Loader2` spinner shown on the row currently being selected
       (`selecting === backend.name`).
     - **Description line** (`backend.description`, `:147`) — verbatim built-ins: **“Run commands directly on
       this machine. No isolation.”**, **“Run commands in an isolated Docker container with a persistent
       workspace.”**, **“Run commands in a Singularity/Apptainer container (HPC-friendly, rootless).”**,
       **“Run commands in a Modal cloud sandbox.”**, **“Run commands in a Daytona cloud sandbox.”**,
       **“Run commands on a remote host over SSH.”**
     - **Guidance line** (`:148-154`), rendered only when `status !== 'ready'` **and** `detail` is non-empty:
       an `AlertTriangle` icon plus the server `detail` string in amber (`text-amber-600 dark:text-amber-300`).
       Observed probe details verbatim: **“Docker CLI not found — install Docker Desktop or docker-ce.”**,
       **“Docker daemon not reachable — start Docker and retry.”**, **“Docker daemon not responding (timed out).”**,
       **“Docker probe failed: {exc}”**, **“Neither singularity nor apptainer found on PATH.”**,
       **“Set terminal.ssh_host and terminal.ssh_user in config.yaml (or the matching TERMINAL_SSH_* env vars).”**,
       **“Modal credentials not found — set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (or run `modal setup`).”**,
       **“Set DAYTONA_API_KEY to use the Daytona backend.”**, **“Unknown backend: {name}”**, **“Probe failed: {exc}”**.
     - **Active + needs-setup suffix** (`:152`): when the non-ready row is also the active one, the sentence
       **“You can select this backend now — commands will fail until setup is complete.”**
       (`i18n: settings.toolsets.terminalBackend.needsSetupHint`, `en.ts:1250`) is appended after the detail,
       separated by a single space (`{backend.active && \` ${copy.needsSetupHint}\`}`).
  4. **Click gesture** — clicking any non-active row selects it; clicking the already-active row does nothing
     (`:72-74`). There is no keyboard shortcut, no dropdown, no confirm dialog, and no Save button: selection
     is the write.
  Localized variants of the panel strings exist for Japanese (`apps/desktop/src/i18n/ja.ts:1131-1143`),
  Simplified Chinese (`zh.ts:1429-1441`) and Traditional Chinese (`zh-hant.ts:1090-1102`) — e.g. **“実行バックエンド”**,
  **“执行后端”**, **“執行後端”** for the section title.
- **Outputs / side effects:**
  - `GET /api/tools/terminal/backends?profile=…` → `{"active": "local", "backends": [{name, label,
    description, active, status, detail}, …]}` (server never 500s on a probe failure — the failure becomes a
    `status`/`detail`).
  - `PUT /api/tools/terminal/backend` body `{"backend": "<name>"}` → `{"ok": true, "backend": "<name>"}`; on
    disk it sets `terminal.backend` in the profile's `config.yaml` (written under `_CONFIG_MUTATION_LOCK`,
    `hermes_cli/web_routers/tools.py:774-786`).
  - **Success toast** on a completed switch (`terminal-backend-panel.tsx:91`): title **“Backend selected”**
    (`i18n: settings.toolsets.terminalBackend.selectedTitle`, `en.ts:1247`), message
    **“Terminal commands now run via {backend}. Applies to new sessions.”**
    (`i18n: settings.toolsets.terminalBackend.selectedMessage`, `en.ts:1248` — a function of the backend's
    display label), `kind: 'success'` → bottom-right, auto-dismiss after 5 s.
  - **Load-failure toast** (`terminal-backend-panel.tsx:61`, fallback title passed to `notifyError`):
    **“Could not load terminal backends”** (`i18n: settings.toolsets.terminalBackend.failedLoad`,
    `en.ts:1242`), `kind: 'error'` → top-center, sticky until dismissed, with the underlying error text as
    the message/detail.
  - **Select-failure toast** (`terminal-backend-panel.tsx:94`): **“Failed to select {backend}”**
    (`i18n: settings.toolsets.terminalBackend.failedSelect`, `en.ts:1249`), same error placement; the local
    active-row mirror is not applied, so the highlight stays on the previous backend.
  - `onConfiguredChange?.()` bubbles up to the Capabilities page so the toolset list refetches and any derived
    pill (e.g. **“Needs keys”**) stays in sync (`terminal-backend-panel.tsx:14-16, :92`).
- **Config / env:** Writes/reads `terminal.backend` (enum `local` | `docker` | `singularity` | `modal` |
  `daytona` | `ssh` + plugin-provided names). Probes additionally read `terminal.ssh_host`, `terminal.ssh_user`
  and the env vars `TERMINAL_SSH_HOST`, `TERMINAL_SSH_USER`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`,
  `DAYTONA_API_KEY`. Both requests carry `?profile=` from the desktop profile scope, so the write lands in the
  selected profile's `config.yaml`.
- **Edge cases / guards:** Selecting a `needs_setup` backend is deliberately **allowed** — the row shows what
  is missing rather than blocking, matching the CLI configurator (`terminal-backend-panel.tsx:40-47`,
  `hermes_cli/web_routers/tools.py:759-763`); the guidance detail plus **“You can select this backend now —
  commands will fail until setup is complete.”** then stays visible on the now-active row (covered by
  `apps/desktop/src/app/settings/terminal-backend-panel.test.tsx:106-116`). An unknown backend name in the
  `PUT` returns HTTP 400 with `Unknown terminal backend: {value!r}. Use one of: {sorted names}`
  (`tools.py:766-772`). An invalid `terminal.backend` already stored in config is coerced back to `local` for
  display (`tools.py:735-737`). Probes are bounded (Docker `docker info` has a 2 s timeout) and never raise —
  `_probe_terminal_backend` wraps everything in try/except and degrades to
  `("unavailable", "Probe failed: {exc}")` (`web_server.py:15601-15627`). Plugin discovery is fail-soft
  (`web_server.py:15464-15487` swallows every exception, returning the built-ins alone). While a selection is
  in flight all rows are `disabled`, preventing double-writes. `vercel_sandbox` / `managed_modal` are not
  separate picker rows. Repeated `refresh()` calls are safe (the button is disabled while `loading`).
  Test coverage of the visible behaviour: `terminal-backend-panel.test.tsx:63-126` (list + pills,
  needs-setup detail, `aria-pressed` on the active row, select + `onConfiguredChange`, needs-setup selection
  allowed, no re-select of the active row).
- **Rebuild notes:** Minimal spec — (a) a table of `{name, label, description}` backend rows extended at
  request time by a plugin registry; (b) a per-row probe returning `(status, detail)` where `detail` is an
  *actionable* sentence and no probe may raise or block longer than ~2 s; (c) a `GET` that pairs the probes
  with the current config value and a `PUT` that validates and persists it under a config lock; (d) a
  single-click row list that mirrors the write locally, toasts success/failure, and appends a
  "selectable but broken" hint on the active row. A better version would run the probes concurrently and
  stream them in (so a dead Docker socket cannot stall the whole list), cache the last probe result per
  backend with an explicit staleness timestamp, and offer an inline one-click remediation per detail
  (e.g. "Start Docker", "Open SSH settings", "Paste Daytona API key") instead of a text instruction the user
  must act on elsewhere.
