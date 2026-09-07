# Desktop app — Settings (every panel, every field)

This shard documents the Hermes Desktop (Electron/React) **Settings overlay** in full: the overlay shell
and its left nav, the nine schema-driven config sections (Model, Chat, Appearance, Workspace, Safety,
Browser, Memory & Context, Voice, Advanced) and every field inside them, plus the bespoke panels —
Providers (Accounts / API keys / Custom Endpoints), Gateways (local/remote/Cloud/SSH + Registered
gateways + Managed updates), Keyboard Shortcuts, Tools & Keys, Notifications, Billing, Plugins,
Archived Chats, About/Uninstall — and the shared building blocks (config-field, searchable select,
combobox, profile scope, settings search catalog, deep-link highlight, toolset config panel, memory
provider panels, computer-use panel, terminal backend panel, browser real-profile panel, voice provider
fields). Every entry cites `apps/desktop/src/app/settings/**` at `path:line` and quotes the verbatim UI
label with its i18n key from `apps/desktop/src/i18n/en.ts`.
It deliberately leaves to sibling shards: the desktop chat/composer/sidebar surfaces, the Capabilities
(`/skills`) page including the MCP tab (settings only redirects there), the web dashboard's own settings,
the CLI `hermes config` commands, and the backend meaning/defaults of each config key (config shards).

---

## 0. Settings shell

### Settings overlay (the Settings page frame)  `id: desktop-settings.overlay`
- **Surface:** Desktop app
- **Where:** Desktop → Settings (route `/settings`, opened from the sidebar gear, the command palette, or `⌘,`). Rendered by `SettingsView` in `apps/desktop/src/app/settings/index.tsx:72`. Close control label `Close settings` (`i18n: settings.closeSettings`).
- **What it does:** Full-screen overlay split into a left nav column and a content pane; the selected panel is stored in the URL as `?tab=<view>` so every settings page is deep-linkable and survives refresh.
- **How it works:** `OverlayView` + `OverlaySplitLayout` + `OverlayNav` + `OverlayMain` (`apps/desktop/src/app/overlays/overlay-split-layout.tsx`, `overlay-view.tsx`). The active tab is a route enum param: `useRouteEnumParam('tab', SETTINGS_VIEWS, 'config:model')` (`index.tsx:91`), where `SETTINGS_VIEWS` = the nine `config:<section>` ids from `SECTIONS` plus `providers`, `gateway`, `connections` (legacy alias), `keybinds`, `keys`, `notifications`, `billing`, `plugins`, `sessions`, `about` (`index.tsx:56-70`). Sub-views use their own params: `pview` for Providers (`PROVIDER_VIEWS`, default `accounts`), `kview` for Tools & Keys (`KEYS_VIEWS`, default `tools`). `openSubView` (`index.tsx:108-123`) sets `tab` + the sub-param in ONE navigate so a two-setter race can't clobber `tab`. Content dispatch is the ternary ladder at `index.tsx:373-409`.
- **Inputs / options:** Query params — `tab` (any of: `config:model`, `config:chat`, `config:appearance`, `config:workspace`, `config:safety`, `config:browser`, `config:memory`, `config:voice`, `config:advanced`, `providers`, `gateway`, `connections`, `keybinds`, `keys`, `notifications`, `billing`, `plugins`, `sessions`, `about`), `pview` (`accounts` | `keys` | `custom-endpoints`), `kview` (`tools` | `settings`), `field=<config key>` (deep-link a config row), `setting=<appearance id>`, `key=<ENV VAR>`, `plugin=<id>`, `server=<mcp server>` (legacy). Close button (top-right of the overlay).
- **Outputs / side effects:** Only URL state; the panels themselves write config/env/IPC.
- **Config / env:** n/a (URL-only). Panels below carry their own keys.
- **Edge cases / guards:** `?tab=mcp` is redirected to `/skills?tab=mcp` preserving `server=` (`index.tsx:81-89`) because MCP moved out of Settings into Capabilities. `?tab=connections` renders `GatewaySettings` and then rewrites the param to `gateway` (`index.tsx:95-99`, `378-381`) so the pre-redirect frame doesn't flash a fallback view.
- **Rebuild notes:** One overlay + URL-driven enum tab + two sub-view params; keep legacy aliases redirecting rather than 404-ing. A better version would persist scroll position per tab and expose the whole tab list to the command palette as first-class rows.

### Settings search pill (“Search”)  `id: desktop-settings.search-pill`
- **Surface:** Desktop app
- **Where:** A pill riding the top edge of the Settings card, dead-center and half off it. Label `Search` (`i18n: settings.search.pill`), followed by a live keyboard-combo badge for `nav.commandPalette`.
- **What it does:** Opens the ⌘K command palette scoped to the Settings page.
- **How it works:** `index.tsx:320-340`. `bindingsFor('nav.commandPalette')[0]` renders the `KbdCombo`; click calls `triggerHaptic('open')` then `openCommandPalettePage('settings')` (`@/store/command-palette`). While the palette is open (`$commandPaletteOpen`) the pill scales to 110% and fades to `opacity-0`, `pointer-events-none`, `tabIndex=-1`, then fades back on close. Rendered as `edgeBadge` on `OverlayView`.
- **Inputs / options:** Click; or just type — see next entry.
- **Outputs / side effects:** Opens the palette overlay.
- **Config / env:** Keybind `nav.commandPalette` (see Keyboard Shortcuts panel).
- **Edge cases / guards:** `motion-reduce:transition-none` disables the animation under reduced motion.
- **Rebuild notes:** Chrome, not an input: no border, recessed fill, live shortcut hint. Better: show recent settings searches in the pill's dropdown.

### Type-to-search on the Settings surface  `id: desktop-settings.type-to-search`
- **Surface:** Desktop app
- **Where:** Anywhere on the Settings page outside a text field.
- **What it does:** Typing any printable character opens the settings-scoped command palette seeded with that character.
- **How it works:** `index.tsx:294-313` — a `window` keydown listener; bails when `$commandPaletteOpen.get()` is true or `isEditableTarget(event.target)` (`@/lib/keybinds/combo`); resolves the char with `typeToFocusChar(event)` (`@/lib/keybinds/composer-focus-keys`); ignores `null` and `' '` (space); otherwise `preventDefault()` + `openCommandPalettePage('settings', char)`.
- **Inputs / options:** Any printable key except space.
- **Outputs / side effects:** Opens the palette with a seeded query.
- **Config / env:** n/a
- **Edge cases / guards:** Space is excluded so it can't accidentally open the palette; editable targets (inputs, textareas, contenteditable) are exempt.
- **Rebuild notes:** Mirror of the chat surface's type-to-focus, pointed at search. Better: also seed from the OS clipboard on ⌘V.

### Settings search catalog (palette entries for settings)  `id: desktop-settings.search-catalog`
- **Surface:** Desktop app
- **Where:** Command palette → Settings page rows. Search field placeholder `Search all settings…` (`i18n: settings.search.placeholder`).
- **What it does:** Builds the deep, schema-driven palette targets: every visible config field, every appearance control, every credential (env var), and every plugin.
- **How it works:** `use-settings-search.ts:30-207` + `settings-search.ts`. Four generators: `buildConfigSearchEntries` (`settings-search.ts:83-113`) walks `SECTIONS`, resolves per-key label via `fieldCopyForSchemaKey(copy.fieldLabels …) ?? FIELD_LABELS ?? prettyName(lastSegment)` and description via `fieldDescriptions ?? field.description`, id `config-field:<key>`, target `{field: key, view: 'config:<section>'}`; the Voice section is pre-filtered through `voiceFieldVisible` so an indexed field can actually mount. `appearanceEntries` (`use-settings-search.ts:112-190`) hard-codes 8 rows keyed by `APPEARANCE_SETTING_IDS` = `appearance.backdrop`, `appearance.embeds`, `appearance.intro-splash`, `appearance.language`, `appearance.theme`, `appearance.tool-view`, `appearance.translucency`, `appearance.ui-scale` (`settings-search.ts:13-22`); translucency is omitted unless `TRANSLUCENCY_SUPPORTED`. `buildCredentialSearchEntries` (`settings-search.ts:115-149`) maps each env var whose `credentialSettingsView()` resolves (`category === 'tool'` → `tools`; `setting`/`messaging` → `settings`; `channel_managed` → excluded) to id `credential:<KEY>`. `pluginEntries` merges `$pluginRecords` (desktop) and `$agentPlugins` filtered by `isDesktopRelevantPlugin`.
- **Inputs / options:** Free-text query. Ranking `searchScore` (`settings-search.ts:151-188`): every whitespace-separated term must appear in the haystack (label + context + description + keywords, normalized); exact label = 100, label prefix = 90, label substring = 80, context substring = 70, all terms split across label/context = 60, else 50. `filterSettingsSearchEntries` sorts by score desc then original index. Verbatim copy of the 8 hard-coded appearance rows (`use-settings-search.ts:112-190`), label — description — keywords: `"Language"` — `"Choose the language for the desktop interface."` (`i18n: language.label` / `language.description`) — `locale`; `"Theme"` — `"Desktop palettes only. The selected mode is applied on top."` — `color mode`, `skin`; `"UI Scale"` — (no description) — `zoom`, `size`; `"Window Translucency"` — `"See your desktop through the whole window, text and all. Tuned separately for light and dark."` (`i18n: settings.appearance.translucencyTitle` / `settings.appearance.translucencyDesc`) — `opacity`, `transparent`; `"Chat Backdrop"` — `"The faint statue image behind the conversation."` — `background`, `blur`; `"Intro Splash"` — `"The wordmark and prompt shown on an empty chat."` — `splash`, `wordmark`, `empty chat`, `new chat`; `"Tool Call Display"` — `"Product hides raw tool payloads; Technical shows full input/output."` (`i18n: settings.appearance.toolViewTitle` / `settings.appearance.toolViewDesc`) — `tool display`, `technical`; `"Inline Embeds"` — `"Rich previews load from third-party sites (YouTube, X, …). Ask shows a placeholder until you allow each one; Always loads them automatically; Off keeps plain links."` — `external content`, `privacy`. Every row uses the `Palette` icon and the context string `"Appearance"` (`i18n: settings.sections.appearance`).
- **Outputs / side effects:** Selecting a row navigates to `/settings?<query>` built by `settingsSearchTargetQuery` (`settings-search.ts:199-228`), emitting `tab`, and optionally `pview`, `kview`, `field`, `setting`, `key`, `plugin`.
- **Config / env:** Reads `GET /api/config/schema`, `GET /api/config`, `GET /api/env-vars` (via `@/hermes`), cached with `staleTime: 5 min`.
- **Edge cases / guards:** While config/schema/env queries are fetching or errored the corresponding entry set is emptied so a profile switch never surfaces stale, wrong-profile targets (`use-settings-search.ts:97-107`, `192-199`). `useOnProfileSwitch(refreshCatalog)` refetches env vars on profile change. Agent plugins are loaded only when `gatewayState === 'open'`.
- **Rebuild notes:** Keep page rows in the palette and contribute only leaf targets from here. Better: index the *values* too so “gpt-4o” finds the model field.

### Config deep-link highlight (`?field=`)  `id: desktop-settings.deep-link-field`
- **Surface:** Desktop app
- **Where:** Any config section, arriving from a palette result.
- **What it does:** Scrolls the targeted config row into view, focuses it, and flashes it for 1.6 s.
- **How it works:** `config-settings.tsx:282-315`. Looks up `document.getElementById('setting-field-' + key)` (each row is wrapped with that id at `config-settings.tsx:420`), `scrollIntoView({behavior:'smooth', block:'center'})`, sets `tabIndex=-1` if absent, `focus({preventScroll:true})`, adds CSS class `setting-field-highlight`, removes it after 1600 ms, and deletes the `field` param with `replace: true` so it can't re-fire.
- **Inputs / options:** `?field=<dotted config key>`.
- **Outputs / side effects:** DOM focus + transient class; URL param removed.
- **Config / env:** n/a
- **Edge cases / guards:** No-ops until both config and schema have loaded; silently no-ops if the id isn't in the DOM (e.g. a Voice field hidden by provider selection).
- **Rebuild notes:** Give every row a stable id derived from its canonical key. Better: auto-switch the section/sub-view when the id isn't present, instead of no-op.

### Generic deep-link highlight hook (`useDeepLinkHighlight`)  `id: desktop-settings.deep-link-hook`
- **Surface:** Desktop app
- **Where:** Used by Tools & Keys (`?key=`), Plugins (`?plugin=`), Appearance (`?setting=`), Connections, MCP tab.
- **What it does:** Same scroll+flash+consume behaviour as above, but retries while the row mounts late and can force a view open first.
- **How it works:** `use-deep-link-highlight.ts:30-100`. Options `{param, ready(target), elementId(target), onResolve?, block='center'}`. Calls `onResolve` (which may flip view state), then polls `document.getElementById(elementId(target))` every 80 ms for up to **20 attempts** (~1.6 s) before giving up; only deletes the URL param AFTER a successful scroll. `useOptionalSearchParams()` (`:18-24`) wraps `useSearchParams()` in try/catch so a consumer mounted outside a Router (e.g. the MCP tab inside a plugin dialog) degrades to inert `[empty params, no-op setter]` instead of crashing.
- **Inputs / options:** `param`, `ready`, `elementId`, `onResolve`, `block` (`ScrollLogicalPosition`).
- **Outputs / side effects:** Focus + `setting-field-highlight` class for 1600 ms; param removed with `replace: true`. Returns the pending target (null once consumed).
- **Config / env:** n/a
- **Edge cases / guards:** 20-attempt cap; cancellation on unmount clears the timer.
- **Rebuild notes:** Poll-then-consume is the important trick — deleting the param up front loses late-mounting targets.

### Export config (nav footer)  `id: desktop-settings.export-config`
- **Surface:** Desktop app
- **Where:** Settings → left nav footer → download icon. Tooltip `Export config` (`i18n: settings.exportConfig`).
- **What it does:** Downloads the whole Hermes configuration as `hermes-config.json`.
- **How it works:** `index.tsx:134-148`. `getHermesConfigRecord()` → `JSON.stringify(cfg, null, 2)` → `Blob({type:'application/json'})` → object URL → synthetic `<a download="hermes-config.json">.click()` → `URL.revokeObjectURL`. Success fires `triggerHaptic('success')`.
- **Inputs / options:** Click only.
- **Outputs / side effects:** A file named `hermes-config.json` in the browser/Electron download path.
- **Config / env:** Reads the whole `GET /api/config` record (all 785 leaf keys).
- **Edge cases / guards:** Any throw → `notifyError(err, t.settings.exportFailed)` → toast `Export failed` (`i18n: settings.exportFailed`).
- **Rebuild notes:** Plain JSON dump, no redaction. A better version would redact secrets and offer a diff-vs-defaults export.

### Import config (nav footer)  `id: desktop-settings.import-config`
- **Surface:** Desktop app
- **Where:** Settings → left nav footer → upload icon. Tooltip `Import config` (`i18n: settings.importConfig`).
- **What it does:** Loads a JSON config file and applies it as the current draft (which autosaves).
- **How it works:** The icon triggers `importInputRef.current?.click()` after `triggerHaptic('open')` (`index.tsx:349-358`); the hidden `<input type="file" accept=".json,application/json" className="hidden">` lives inside `ConfigSettings` (`config-settings.tsx:449-455`) and is handed down via `importInputRef`. `handleImport` (`config-settings.tsx:317-337`) reads the file with `FileReader.readAsText`, `JSON.parse`s it, calls `updateConfig(parsed)` (so the destructive-toolsets guard still applies) and toasts `Config imported` (`i18n: settings.config.imported`) with message `Saving…` (`i18n: common.saving`), then resets `e.target.value` so the same file can be re-picked.
- **Inputs / options:** File picker accepting `.json`, `application/json`.
- **Outputs / side effects:** Replaces the local config draft → debounced autosave (`PUT /api/config` with the structural diff).
- **Config / env:** All config keys.
- **Edge cases / guards:** Invalid JSON → `notifyError(err, c.invalidJson)` → `Invalid config JSON` (`i18n: settings.config.invalidJson`). Import is only wired while a `config:*` section is mounted (the hidden input lives there); on non-config panels the button opens nothing. Because `PUT /api/config` deep-merges, an import that omits `toolsets` does NOT wipe toolsets (`helpers.ts:137-160`).
- **Rebuild notes:** Route imports through the same guard path as manual edits. Better: show a diff preview before applying.

### Reset to defaults (nav footer)  `id: desktop-settings.reset-defaults`
- **Surface:** Desktop app
- **Where:** Settings → left nav footer → refresh icon (hover turns destructive-red). Tooltip `Reset to defaults` (`i18n: settings.resetToDefaults`).
- **What it does:** Overwrites the entire configuration with Hermes' built-in defaults.
- **How it works:** `index.tsx:150-168`. `triggerHaptic('warning')` then `confirm({confirmLabel: t.settings.resetToDefaults, destructive: true, title: t.settings.resetConfirm})` → dialog title `Reset all settings to Hermes defaults?` (`i18n: settings.resetConfirm`) with confirm button `Reset to defaults`. On confirm: `saveHermesConfig(await getHermesConfigDefaults())`, `triggerHaptic('success')`, `onConfigSaved?.()`.
- **Inputs / options:** Click → Confirm / Cancel.
- **Outputs / side effects:** Writes the full defaults record via `PUT /api/config`; every panel reloads.
- **Config / env:** All keys (`hermes_cli/config_defaults.py` DEFAULT_CONFIG, 785 leaves).
- **Edge cases / guards:** Cancel is a no-op. Failure → `notifyError(err, t.settings.resetFailed)` → `Reset failed` (`i18n: settings.resetFailed`). Destructive styling only; no undo.
- **Rebuild notes:** Confirm + full-defaults PUT. Better: snapshot the previous config to a timestamped file so reset is undoable.

### Left nav — section list  `id: desktop-settings.nav`
- **Surface:** Desktop app
- **Where:** Settings → left column. Built at `index.tsx:170-289`.
- **What it does:** Selects which settings panel the content pane shows; two entries expand into sub-items.
- **How it works:** `OverlayNavGroup[]`; each entry has `{active, icon, id, label, onSelect}` plus optional `children` and `gapBefore`. Config sections come first, generated from `SECTIONS` with label `t.settings.sections[s.id] ?? s.label`.
- **Inputs / options:** In order, top to bottom —
  1. `Model` (`i18n: settings.sections.model`, icon `Box`) → `?tab=config:model`
  2. `Chat` (`i18n: settings.sections.chat`, icon `MessageCircle`) → `?tab=config:chat`
  3. `Appearance` (`i18n: settings.sections.appearance`, icon `Palette`) → `?tab=config:appearance`
  4. `Workspace` (`i18n: settings.sections.workspace`, icon `Monitor`) → `?tab=config:workspace`
  5. `Safety` (`i18n: settings.sections.safety`, icon `Lock`) → `?tab=config:safety`
  6. `Browser` (section label falls back to the constant `'Browser'`; no `settings.sections.browser` key exists, icon `Globe`) → `?tab=config:browser`
  7. `Memory & Context` (`i18n: settings.sections.memory`, icon `Brain`) → `?tab=config:memory`
  8. `Voice` (`i18n: settings.sections.voice`, icon `Mic`) → `?tab=config:voice`
  9. `Advanced` (`i18n: settings.sections.advanced`, icon `Wrench`) → `?tab=config:advanced`
  10. `Notifications` (`i18n: settings.nav.notifications`, icon `Bell`)
  11. `Billing` (`i18n: settings.nav.billing`, icon `BarChart3`)
  12. `Providers` (`i18n: settings.nav.providers`, icon `Zap`, `gapBefore: true`) with children: `Accounts` (`i18n: settings.nav.providerAccounts`, codicon `account`), `API keys` (`i18n: settings.nav.providerApiKeys`, icon `KeyRound`), `Custom Endpoints` (`i18n: settings.nav.providerCustomEndpoints`, icon `Globe`)
  13. `Gateways` (`i18n: settings.nav.gateway`, icon `Globe`)
  14. `Keyboard Shortcuts` (`i18n: settings.nav.keybinds`, icon `Keyboard`)
  15. `Tools & Keys` (`i18n: settings.nav.apiKeys`, icon `KeyRound`) with children: `Tools` (`i18n: settings.nav.keysTools`, icon `Wrench`), `Settings` (`i18n: settings.nav.keysSettings`, icon `Settings2`)
  16. `Plugins` (`i18n: settings.nav.plugins`, icon `Package`)
  17. `Archived Chats` (`i18n: settings.nav.archivedChats`, icon `Archive`)
  18. `About` (`i18n: settings.nav.about`, icon `Info`, `gapBefore: true`)
  Footer icon buttons: Export config, Import config, Reset to defaults (see entries above).
- **Outputs / side effects:** Sets `?tab=` (and `?pview=`/`?kview=` for children).
- **Config / env:** n/a
- **Edge cases / guards:** The unused string `MCP` (`i18n: settings.nav.mcp`) remains in the catalog after MCP moved to Capabilities. Sub-item selection routes through `openSubView` so `tab` and the sub-param land in one navigate; selecting the default sub-view (`accounts` / `tools`) deletes the param instead of writing it.
- **Rebuild notes:** Nav groups as data, labels from i18n, active state derived from URL. Better: remember the last sub-view per section.

### Settings layout primitives (`SettingsContent`, `ListRow`, `ToggleRow`, `SectionHeading`, `SettingsSection`, `Pill`, `NavLink`, skeletons)  `id: desktop-settings.primitives`
- **Surface:** Desktop app
- **Where:** Every settings panel. `apps/desktop/src/app/settings/primitives.tsx`.
- **What it does:** The shared row/section/skeleton vocabulary all settings panels are built from.
- **How it works:** `SettingsContent` (`primitives.tsx:15-23`) — scroll container, `pb-20` plus `PAGE_INSET_X` gutters, or `bare` for embedded use (`px-5 pb-6`). `Pill` (`:27`) maps tones `muted|primary|warn` → Badge variants `muted|default|warn`. `SectionHeading` (`:31-52`) — icon + title + optional `meta` pill + right-aligned `aside`. `SettingsSection` (`:57-76`) — heading + body with `mb-6`. `NavLink` (`:78-106`). `ListRow` (`:108-155`) — a `@container`-queried grid: at `@2xl` it splits into `minmax(0,1fr) minmax(15rem,22rem)` label/control columns, otherwise stacks; supports `title`, `description`, `hint` (mono, `text-[0.68rem]`), `action`, `below`, `data-tour`, `id`, `wide`, `className`. `ToggleRow` (`:158-188`) — a `ListRow` whose action is a `Switch` with `aria-label={label}` and `triggerHaptic('selection')` on change. `SectionHeadingSkeleton`, `ListRowSkeleton`, `SettingsSkeleton({search, sections:[{heading,rows}]})` (`:192-245`) preserve page shape while loading. `EmptyState` is re-exported from `@/components/ui/empty-state`.
- **Inputs / options:** As listed above.
- **Outputs / side effects:** DOM only.
- **Config / env:** n/a
- **Edge cases / guards:** Container queries (not viewport) so a narrow pane stacks rather than crushing labels.
- **Rebuild notes:** One row primitive, one toggle primitive, and skeletons that mirror the real rhythm. Better: derive skeleton shapes from the same section descriptors as the real page.

---

## 1. Config sections (schema-driven)

### Config section renderer (`ConfigSettings`)  `id: desktop-settings.config-renderer`
- **Surface:** Desktop app
- **Where:** All nine `?tab=config:*` panels. `apps/desktop/src/app/settings/config-settings.tsx:52`.
- **What it does:** Loads the config record + backend field schema, renders the curated key list for the active section as rows, and autosaves edits.
- **How it works:** Outer `ConfigSettings` reads `$settingsRequestProfile` and remounts `ConfigSettingsInner` keyed on the scope (`config-settings.tsx:62-73`) so every draft/seed/autosave ref resets when the target profile changes. Inner: `useHermesConfigRecord(scopeProfile)` for the record, `useQuery(['hermes-config-schema', …], getHermesConfigSchema(scopeProfile), staleTime 5min)` for `{fields, category_order}`. The editable draft is local state seeded ONCE from the shared record (`configSeeded` ref) so background refetches can't clobber edits; `configBaselineRef` snapshots the record at seed time. **Autosave**: any change bumps `saveVersionRef`, which schedules a `550 ms` debounce (`:192-236`); the save is chained onto `saveQueueRef` so requests serialize; it PUTs only `diffConfig(baseline, snapshot)` (`helpers.ts:116-135`, a recursive per-key structural diff) so untouched keys are never resent with stale values; on success the snapshot becomes the new baseline and is mirrored into the shared query cache via `hermesConfigCacheWriter(scopeProfile)`. Field list comes from `sectionFieldEntries(schema, config)` (`helpers.ts:197-212`) which walks `SECTIONS[].keys` and uses `schema[k]` or, if the backend omitted it, `inferFieldSchema(value)` (boolean/number/list/string) when the key exists in the config — config presence is the availability signal.
- **Inputs / options:** Per-section key lists (see the nine section entries below); the hidden import `<input type=file>`; `?field=` deep link.
- **Outputs / side effects:** `PUT /api/config` (deep-merged) with the diff; `onConfigSaved?.()`; a repo rescan when the discovery policy changed (below).
- **Config / env:** Every key listed in `SECTIONS` (`constants.ts:566-771`).
- **Edge cases / guards:** (a) Load failure of either config or schema renders `PanelEmpty` with icon `error`, title `Settings failed to load` (`i18n: settings.config.failedLoad`) and a `Refresh` button (`i18n: skills.refresh`) that refetches both. (b) Loading state: the `model` section shows `ModelSettingsSkeleton`, everything else `SettingsSkeleton({sections:[{rows:6}]})`. (c) Empty section (and not `chat`) → `EmptyState` titled `Nothing to configure` (`i18n: settings.config.emptyTitle`) with `This section has no adjustable settings.` (`i18n: settings.config.emptyDesc`). (d) A profile switch (`useOnProfileSwitch`, `:150-158`) drops the seed, the draft, the baseline and zeroes `saveVersion` so the pending debounce is cancelled. (e) Autosave failure → toast `Autosave failed` (`i18n: settings.config.autosaveFailed`), only if the save is still the newest. (f) After a successful save, when editing the ACTIVE profile only, if `repoDiscoveryPolicySignature(repoDiscoveryPolicyFromConfig(snapshot))` changed, `scanAndRecordRepos(true)` re-runs repository discovery (`:219-226`).
- **Rebuild notes:** Local draft + baseline + structural diff + serialized debounced autosave is the whole engine; do not PUT the full record. A better version would show a per-row "saved" tick and an undo stack.

### Destructive guard — clearing “Enabled Toolsets”  `id: desktop-settings.toolsets-wipe-guard`
- **Surface:** Desktop app
- **Where:** Settings → Advanced → `Enabled Toolsets` row, when the list is emptied. Confirmation dialog title from `i18n: settings.config.toolsetsWipeConfirm`.
- **What it does:** Requires an explicit confirmation before an edit that turns a non-empty toolset list into an empty one is applied.
- **How it works:** `config-settings.tsx:248-265` calls `clearsEnabledToolsets(config, next)` (`helpers.ts:153-160`): true only when the previous value is a non-empty array AND the next value is an explicit `[]`. On true it awaits `confirm({destructive: true, title: c.toolsetsWipeConfirm})` and applies only on OK.
- **Inputs / options:** The comma-separated `Enabled Toolsets` input; select-all + Backspace is the accident it defends against.
- **Outputs / side effects:** None until confirmed; on confirm, normal autosave.
- **Config / env:** `toolsets`
- **Edge cases / guards:** A **missing** `toolsets` key is deliberately not a clear — `PUT /api/config` deep-merges, so an import that omits the key leaves toolsets intact and warning there would be a lie (`helpers.ts:137-152`).
- **Rebuild notes:** Guard only the non-empty→`[]` transition. Better: offer "disable all but core" instead of an empty list.

### “Applies to” profile scope chips  `id: desktop-settings.profile-scope`
- **Surface:** Desktop app
- **Where:** Top of every config-backed page (Model, Chat, Appearance, Workspace, Safety, Browser, Memory & Context, Voice, Advanced, Tools & Keys) and the Messaging overlay. Label `Applies to` (`i18n: settings.profileScope.appliesTo`); explanatory line `i18n: settings.profileScope.editsProfile(<name>)`.
- **What it does:** Chooses which Hermes profile's `config.yaml` the page edits.
- **How it works:** `profile-scope.tsx:36-77`. Reads `$settingsScopeOverride`, `$activeGatewayProfile`, `$profiles`; refreshes the roster lazily on mount with `refreshProfiles()` (failures keep the cached list). Renders one `ScopeChip` per profile (`profile-scope.tsx:13-28`, a rounded-full button whose active state uses `--ui-bg-tertiary`); clicking calls `setSettingsScope(profile.name)`. The selected key is `normalizeProfileKey(override ?? active)`.
- **Inputs / options:** One chip per profile, labelled with the profile name.
- **Outputs / side effects:** Sets the shared `$settingsScopeOverride` nanostore, which every config request appends as a profile parameter; `ConfigSettingsInner` is remounted on change.
- **Config / env:** Profiles live under `~/.hermes/profiles/<name>/config.yaml`.
- **Edge cases / guards:** Hidden entirely when `profiles.length < 2`, so single-profile users never see it and every request keeps its unscoped shape. The trailing explanation paragraph shows only when an explicit override is set (`override !== null`).
- **Rebuild notes:** One nanostore for the scope, remount on change. Better: show which keys differ from the active profile.

### Config field row (`ConfigField`)  `id: desktop-settings.config-field`
- **Surface:** Desktop app
- **Where:** Every row in every config section; also reused by the Capabilities TTS provider panel. `apps/desktop/src/app/settings/config-field.tsx:27`.
- **What it does:** Renders one config key as label + description + a control chosen from the field's schema type.
- **How it works:** Label resolution order (`config-field.tsx:47-50`): `t.settings.fieldLabels[camelKey]` → `FIELD_LABELS[camelKey]` (`constants.ts:295-…`) → `prettyName(lastSegment)`. Description order (`:54-59`): `t.settings.fieldDescriptions` → `FIELD_DESCRIPTIONS` → `schema.description` → `''`. A description that normalizes (lowercase, strip non-alphanumerics) to the same string as the label or the raw schema key is dropped as redundant (`:61-66`). Schema keys are mapped to copy keys by snake→camel per segment (`field-copy.ts:5-19`); `defineFieldCopy` flattens a nested literal into dotted keys and throws on empty segments or duplicates (`field-copy.ts:21-57`). Every row gets `data-tour="field-<schemaKey>"` so tours can point at one setting. **Control ladder** (`:87-236`): (1) `fallback_providers` → `FallbackModelsField` (wide); (2) `schema.type === 'boolean'` → `Switch`; (3) options present AND `schema.searchable` → `SearchableSelect` (clear item labelled `System default` (`i18n: settings.config.systemDefault`) when `schema.clearable`, empty message `No results found` (`i18n: settings.config.noResults`), placeholder `Search…` (`i18n: settings.config.searchPlaceholder`)); (4) options present AND key ∈ `FREE_INPUT_KEYS` → `ComboboxInput` (placeholder `Not set`); (5) options present → closed `Select`, empty option rendered as `None` (`i18n: settings.config.none`) for `display.personality`, `Built-in only` (`i18n: settings.config.builtinOnly`) for `memory.provider`, else `(none)` (`i18n: settings.config.noneParen`); (6) `type === 'number'` → numeric `Input` (empty string commits `0`; `NaN` is ignored); (7) `type === 'list'` → text `Input`, split on `,`, trimmed, empties dropped, placeholder `comma-separated values` (`i18n: settings.config.commaSeparated`); (8) object value → monospace `Textarea` with `JSON.stringify(value,null,2)`, parse failures silently keep the last valid value; (9) `type === 'text'` or a string longer than 100 chars → `Textarea`; (10) otherwise a plain `Input`. Placeholder for 6/8/9/10 is `Not set` (`i18n: settings.config.notSet`).
- **Inputs / options:** `schemaKey`, `schema` (`{type, options?, description?, searchable?, clearable?}`), `value`, `enumOptions`, `optionLabels`, `onChange`, `descriptionExtra`.
- **Outputs / side effects:** Calls `onChange(value)` → `setNested` → draft update → autosave.
- **Config / env:** Any config key.
- **Edge cases / guards:** `EMPTY_SELECT_VALUE = '__hermes_empty__'` (`constants.ts:43`) stands in for `''` inside Radix Select (which forbids empty values) and is mapped back to `''` on change. `CONTROL_TEXT = 'text-xs'` is the shared control class.
- **Rebuild notes:** One schema→control ladder plus a copy-override layer keyed by canonical dotted key. Better: per-type validation with inline errors instead of silent coercion.

### Enum option resolution (`enumOptionsFor`)  `id: desktop-settings.enum-options`
- **Surface:** Desktop app / Config
- **Where:** Behind every dropdown in the config sections. `helpers.ts:348-386`.
- **What it does:** Decides which options a select/combobox offers for a given key.
- **How it works:** Base list = `dynamicOptions` (backend-supplied, e.g. ElevenLabs voices) ?? `personalityOptions(config)` for `display.personality` ?? the static `ENUM_OPTIONS[key]` table (`constants.ts:222-…`). Then: (a) for `tts.provider` / `stt.provider`, user-declared *command providers* found under `tts.providers.<name>` / `stt.providers.<name>` and the back-compat `tts.<name>` / `stt.<name>` are appended (`commandProviderNames`, `helpers.ts:321-340`), excluding built-in names case-insensitively (`BUILTIN_TTS_PROVIDERS` = edge, elevenlabs, openai, minimax, xai, mistral, gemini, neutts, kittentts, piper, deepinfra; `BUILTIN_STT_PROVIDERS` = local, local_command, groq, openai, mistral, xai, elevenlabs, deepinfra); a block qualifies when `type` is absent or normalizes to `command` AND `command` is a non-empty string (`isCommandProvider`, `:293-306`). (b) for `tts.openai.voice`, if the selected `tts.openai.model` is `tts-1` or `tts-1-hd` the list is narrowed to `OPENAI_TTS1_VOICES` = alloy, ash, coral, echo, fable, nova, onyx, sage, shimmer (`:346`). (c) The current value is appended if it isn't already in the list, so a hand-edited value is never silently dropped.
- **Inputs / options:** `key`, current `value`, whole `config`, optional `dynamicOptions`.
- **Outputs / side effects:** `string[] | undefined`.
- **Config / env:** `agent.personalities` (custom personality names are merged with `BUILTIN_PERSONALITIES` from `@/lib/personalities`, mirroring `hermes_cli/personality.py`), `tts.providers.*`, `stt.providers.*`, `tts.openai.model`.
- **Edge cases / guards:** `memory.provider` is deliberately absent from `ENUM_OPTIONS` so the backend's discovery-driven `schema.options` wins (a static list would hide pip-installed providers — issue #49513, `constants.ts:230-235`).
- **Rebuild notes:** Static display table + runtime merge of user-defined providers + always-keep-current-value. Better: fetch all option lists from the backend so the display table can't drift.

### Voice field visibility rule  `id: desktop-settings.voice-visibility`
- **Surface:** Desktop app / Config
- **Where:** Settings → Voice. `helpers.ts:164-178`.
- **What it does:** Shows only the provider-specific rows belonging to the currently selected TTS/STT provider.
- **How it works:** A key matching `^(tts|stt)\.([^.]+)\.` is visible only when its `<provider>` segment equals `config[<domain>].provider`; all `stt.*.*` rows are hidden entirely while `stt.enabled` is false; keys that don't match the pattern (e.g. `tts.provider`, `voice.record_key`) are always visible. Applied in `config-settings.tsx:379` and mirrored in the search catalog (`settings-search.ts:98`) so every indexed field can actually mount.
- **Inputs / options:** Driven by `tts.provider`, `stt.provider`, `stt.enabled`.
- **Outputs / side effects:** Rows appear/disappear as the provider select changes.
- **Config / env:** `tts.provider`, `stt.provider`, `stt.enabled`.
- **Edge cases / guards:** Search must use the same predicate or the palette would deep-link to a hidden row.
- **Rebuild notes:** One predicate shared by page and search.

### Searchable select control  `id: desktop-settings.searchable-select`
- **Surface:** Desktop app
- **Where:** Any config row whose schema sets `searchable: true` — in practice `Timezone` (~590 IANA zones). `searchable-select.tsx:41`.
- **What it does:** A closed-world dropdown with a type-to-filter command palette instead of a long native list.
- **How it works:** Radix `Popover` + cmdk `Command`. Trigger is a `role="combobox"` button (`data-slot="searchable-select-trigger"`) showing the value or the placeholder, with a chevron-up/down codicon. `CommandInput` autofocuses. Ranking (`rankSearchOption`, `:15-29`): 2 when the substring matches after the last `/` (so “york” ranks `America/New_York` above deeper paths), 1 when it matches anywhere, 0 otherwise. A leading clear item is prepended when `clearLabel` is given, selecting `''`. Each item shows a check codicon at `opacity-100` when selected. Popover width tracks the trigger (`--radix-popover-trigger-width`).
- **Inputs / options:** `value`, `onChange`, `options`, `placeholder` (default `Search…`), `emptyMessage` (default `No results found.`), `clearLabel`.
- **Outputs / side effects:** `onChange(selected)` then closes.
- **Config / env:** n/a
- **Edge cases / guards:** Closed-world only — arbitrary text entry is not supported; empty-string options are filtered out before rendering (`config-field.tsx:111`).
- **Rebuild notes:** Popover+cmdk with a path-aware ranking function. Better: group by region and show the current UTC offset.

### Free-input combobox control  `id: desktop-settings.combobox-input`
- **Surface:** Desktop app
- **Where:** The 17 open-world voice/model fields in `FREE_INPUT_KEYS`. `combobox-input.tsx:22`.
- **What it does:** A plain text input the user can type anything into, plus a dropdown of all known suggestions.
- **How it works:** Popover anchored to the input. Suggestions filter by substring while typing, but when the typed value **exactly** matches an option the FULL list is shown again (`:40-43`) — this is the bug fix over the old native `<datalist>`, which filtered by current value and so showed only the single already-selected entry. The trailing chevron button (`aria-label="Show options"`, `tabIndex=-1`) toggles the popover and refocuses the input. `Escape`, `Enter`, `Tab` close it. `onOpenAutoFocus` is prevented so focus stays in the field. Items render `optionLabels?.[option] ?? option` with a check codicon.
- **Inputs / options:** `value`, `onChange`, `options`, `optionLabels`, `placeholder`, `className`.
- **Outputs / side effects:** `onChange` on every keystroke and on item select.
- **Config / env:** `FREE_INPUT_KEYS` (`constants.ts:277-295`) = `tts.edge.voice`, `tts.openai.model`, `tts.openai.voice`, `tts.elevenlabs.voice_id`, `tts.gemini.model`, `tts.gemini.voice`, `tts.xai.voice_id`, `tts.minimax.model`, `tts.minimax.voice_id`, `tts.mistral.model`, `tts.mistral.voice_id`, `tts.neutts.model`, `tts.kittentts.model`, `tts.kittentts.voice`, `tts.piper.voice`, `tts.deepinfra.model`, `tts.deepinfra.voice`.
- **Edge cases / guards:** Options are suggestions, not a gate — providers accept custom voice IDs (cloned ElevenLabs voices, Edge's 400+ catalog).
- **Rebuild notes:** Never use a native datalist for a "suggestions but free text" field. Better: validate against the provider's live catalog and warn (not block) on unknown values.

---

## 2. Settings → Model

### Model panel (`ModelSettings`)  `id: desktop-settings.model-panel`
- **Surface:** Desktop app
- **Where:** Settings → `Model` (`?tab=config:model`). Rendered above the section's config rows (`config-settings.tsx:386-390`). Source `apps/desktop/src/app/settings/model-settings.tsx:185`.
- **What it does:** Picks the default provider + model for new chats, sets profile-wide reasoning/fast defaults, assigns per-task auxiliary models, and edits Mixture-of-Agents presets.
- **How it works:** On mount `refresh()` (`model-settings.tsx:221-297`) fires four requests in parallel: `getGlobalModelInfo`, `getGlobalModelOptions`, `getAuxiliaryModels`, `getMoaModels` (the last is `.catch(() => null)` so a backend without MoA just hides the section). A `profileEpoch` ref is bumped on every profile switch and checked before every write-back, so an in-flight profile-A response can never paint into profile B. `useOnProfileSwitch` clears the draft selection and re-refreshes with `replaceSelection: true`.
- **Inputs / options:** See the sub-entries below (main picker, defaults row, auxiliary rows, MoA section).
- **Outputs / side effects:** `POST` model assignment endpoints; `PUT /api/config`; `invalidateHermesConfig(scopeProfile)` after every refresh.
- **Config / env:** `agent.reasoning_effort`, `agent.service_tier`; the assignment endpoints write the profile's model config.
- **Edge cases / guards:** While `loading && !mainModel`, `ModelSettingsSkeleton` (`:44-83`) mirrors the real DOM — the catalog also declares the plain loading label **"Loading model configuration..."** (`i18n: settings.model.loading`, `apps/desktop/src/i18n/en.ts:1084`, `apps/desktop/src/i18n/types.ts:942`), which has NO render site in v2026.8.31 because the page renders the skeleton instead: a catalog-only / latent string. Any error is shown as `text-destructive` text under the picker row. Deep link `?tab=config:model&aux=<task>` scrolls+flashes an auxiliary row (via `useDeepLinkHighlight`, `elementId: 'aux-task-<task>'`, ready when the task is one of the eight known ones).
- **Rebuild notes:** Epoch-guarded async + a single refresh that repopulates every sub-widget. Better: stream catalog updates instead of a four-request fan-out.

### Default model picker (Provider + Model + Apply)  `id: desktop-settings.model-main-picker`
- **Surface:** Desktop app
- **Where:** Settings → Model → the first row. Intro text `Applies to new sessions. Use the model picker in the composer to hot-swap the active chat.` (`i18n: settings.model.appliesDesc`).
- **What it does:** Chooses the provider + model used for every new chat.
- **How it works:** `model-settings.tsx:790-857`. Two Radix `Select`s and an `Apply` button. Provider options come from `getGlobalModelOptions().providers`; when empty, the placeholder row `NO_PROVIDERS = [{name:'—', slug:'', models:[]}]` is used (`:118`). `mainProviderOptions` prepends a synthetic row for a saved-but-missing provider so Radix doesn't render a blank trigger (`:305-312`). Model options are `withActive(selectedProviderModels, selectedModel)` (`:123-124`) which prepends the active value when it isn't in the curated list. `Apply` calls `setMainModelAssignment({model, provider, base_url?})` (`:642-687`), stores `stale_aux` from the response, calls `onMainModelChanged(provider, model)` only when editing the ACTIVE profile, then `refresh()`.
- **Inputs / options:** Provider select (placeholder `Provider`, `i18n: settings.model.provider`); Model select (placeholder `Model`, `i18n: settings.model.model`); `Apply` button (`i18n: common.apply`), which shows a spinner and the text `Applying...` (`i18n: settings.model.applying`) while in flight and is disabled unless both halves are chosen.
- **Outputs / side effects:** Writes the profile's main model assignment; updates live UI stores.
- **Config / env:** Provider `api_url` is passed through as `base_url` when the provider row declares one.
- **Edge cases / guards:** The catalog carries the off-catalog warning fragment **"isn't in this provider's model list — calls may fall back to a backup."** (`i18n: settings.model.notInCatalog`, `apps/desktop/src/i18n/en.ts:1102`) — meant to be appended after the selected model id when it is absent from the provider's model list; in v2026.8.31 no component reads `m.notInCatalog` (the picker instead keeps the value selectable via `withActive`), so it is a catalog-only / latent string. `isProviderReady(p)` (`:95-97`) = row exists and (`authenticated !== false` OR it reports ≥1 model). An unready provider swaps the model select for a setup affordance — see the next two entries.
- **Rebuild notes:** Always keep the currently-saved value selectable even when it's off-catalog. Better: show price/context-window next to each model.

### Inline API-key activation for an unconfigured provider  `id: desktop-settings.model-inline-api-key`
- **Surface:** Desktop app
- **Where:** Settings → Model → picker row, when the selected provider has `auth_type === 'api_key'` and a `key_env`, and is not yet ready.
- **What it does:** Lets you paste the provider's API key right in the picker, then auto-selects a recommended model.
- **How it works:** `model-settings.tsx:805-826` renders a `type="password"` `Input` with placeholder `` `Paste ${selectedProviderRow.key_env}` `` (falling back to `Paste API key`) plus an `Activate` button. `activateApiKeyProvider` (`:556-604`) → `setEnvVar(keyEnv, trimmedKey, scopeProfile)`, clears the draft, best-effort `getRecommendedDefaultModel(slug)`, then `getGlobalModelOptions()` and selects the recommendation or the first model of the refreshed row.
- **Inputs / options:** Key input (`autoComplete="off"`, Enter submits); `Activate` button (disabled while empty or activating; shows `Activating...` with a spinner).
- **Outputs / side effects:** Persists the provider's key env var; refreshes the provider catalog; pre-selects a model.
- **Config / env:** The provider's `key_env` (e.g. `OPENROUTER_API_KEY`).
- **Edge cases / guards:** The draft is cleared whenever `selectedProvider` changes so a half-typed key can't leak to another provider (`:333-335`).
- **Rebuild notes:** Set the env var, then re-fetch the catalog — don't assume activation succeeded. Better: validate the key with a cheap probe call before saving.

### Provider setup hand-off (`Set up <provider>`)  `id: desktop-settings.model-provider-setup`
- **Surface:** Desktop app
- **Where:** Settings → Model → picker row, when the selected provider is unready and is NOT an api_key provider. Button label `Set up <provider name>` (falls back to `Set up provider`).
- **What it does:** Hands off to the onboarding sign-in flow for that provider.
- **How it works:** `startProviderSetup` (`:609-630`): slug lowercased; `custom` / `local` / `custom:*` → `startManualLocalEndpoint()` (URL + optional key form); a known row → `startManualProviderOAuth(rowSlug)`; an unknown/stale slug → `startManualOnboarding()` (the generic picker) rather than deep-linking a bad slug.
- **Inputs / options:** Single button.
- **Outputs / side effects:** Opens the onboarding overlay.
- **Config / env:** n/a
- **Edge cases / guards:** A hint paragraph renders below the row (`:842-848`): `<name> needs an API key — set it up to choose a model.` when `auth_type === 'api_key'`, otherwise `<name> signs in through your browser — Hermes runs the flow for you.`
- **Rebuild notes:** Route the "custom/local endpoint" case to its own form; it is not OAuth.

### Profile defaults — Reasoning effort  `id: desktop-settings.model-reasoning-default`
- **Surface:** Desktop app
- **Where:** Settings → Model → the `Defaults` row (`i18n: settings.model.defaultsLabel`), label `Reasoning` (`i18n: settings.model.reasoning`).
- **What it does:** Sets the default thinking level for the profile.
- **How it works:** `model-settings.tsx:866-887`. Value = `agent.reasoning_effort` normalized; a hand-written `false`/`disabled` maps to `none`; an empty value falls back to `DEFAULT_REASONING_EFFORT` = `medium` (`lib/reasoning-effort.ts:15`). Change → `writeAgentDefault('agent.reasoning_effort', value)` (`:534-551`) which optimistically writes the whole config record into the shared cache, PUTs it, and rolls back on failure.
- **Inputs / options:** Select over `REASONING_EFFORT_VALUES` = `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. Labels: `none` → `Off` (`i18n: settings.model.reasoningOff`); the rest use `shell.modelOptions.*` → `Minimal`, `Low`, `Medium`, `High`, `Extra High`, `Max`, `Ultra`.
- **Outputs / side effects:** `PUT /api/config` with `agent.reasoning_effort`.
- **Config / env:** `agent.reasoning_effort`
- **Edge cases / guards:** Only rendered when the applied main model reports `capabilities[model].reasoning` — unreported defaults to `true` (`:527`). Failure toast `Failed to save model defaults` (`i18n: settings.model.defaultsFailed`).
- **Rebuild notes:** Mirror the backend's `VALID_REASONING_EFFORTS`; treat empty as inherit and `none` as off.

### Profile defaults — Fast toggle  `id: desktop-settings.model-fast-default`
- **Surface:** Desktop app
- **Where:** Settings → Model → `Defaults` row, label `Fast` (`i18n: shell.modelOptions.fast`).
- **What it does:** Switches the API service tier between fast/priority and normal for the profile.
- **How it works:** `model-settings.tsx:888-899`. Reads `agent.service_tier` through `isFastTier` (`:86-92`), which treats `fast`, `priority`, `on` (case/space-insensitive) as fast — mirroring `tui_gateway`'s `_load_service_tier`. On change writes `'fast'` or `'normal'` via `writeAgentDefault`.
- **Inputs / options:** `Switch` (size `xs`).
- **Outputs / side effects:** `PUT /api/config` with `agent.service_tier`.
- **Config / env:** `agent.service_tier` (default `""`)
- **Edge cases / guards:** Only rendered when the main model reports `capabilities[model].fast`; unreported defaults to `false` so the toggle is hidden (`:528`).
- **Rebuild notes:** Accept several truthy spellings on read, write one canonical value.

### Auxiliary models — task list  `id: desktop-settings.model-auxiliary`
- **Surface:** Desktop app
- **Where:** Settings → Model → section `Auxiliary models` (`i18n: settings.model.auxiliaryTitle`, icon `Cpu`), description `Helper tasks run on the main model by default. Assign a dedicated model to any task to override.` (`i18n: settings.model.auxiliaryDesc`).
- **What it does:** Pins a specific provider+model to each internal helper task instead of using the main model.
- **How it works:** `model-settings.tsx:911-1020`. The eight slots are hard-coded in `AUX_TASKS` (`:107-116`), mirroring `_AUX_TASK_SLOTS` in `hermes_cli/web_server.py`. Each row shows the task label + a `Pill` hint, and a mono description that reads `auto · use main model` (`i18n: settings.model.autoUseMain`) when unassigned or `provider · model` (model falling back to `(provider default)`, `i18n: settings.model.providerDefault`). Each row's container carries `id="aux-task-<key>"` for the deep link.
- **Inputs / options:** The eight tasks with their verbatim labels and hints (`i18n: settings.model.tasks.*`):
  1. `Vision` — hint `Image analysis` (key `vision`)
  2. `Compression` — hint `Context compaction` (key `compression`)
  3. `Skills hub` — hint `Skill search` (key `skills_hub`)
  4. `Approval` — hint `Smart auto-approve` (key `approval`)
  5. `MCP` — hint `MCP tool routing` (key `mcp`)
  6. `Title gen` — hint `Session titles` (key `title_generation`)
  7. `Review` — hint `/review reviewer subagent` (key `review`)
  8. `Curator` — hint `Skill-usage review` (key `curator`)
  Per-row buttons: `Set to main` (`i18n: settings.model.setToMain`, disabled without a main model or while applying) and `Change` (`i18n: settings.model.change`, disabled when no providers are loaded). Section button `Reset all to main` (`i18n: settings.model.resetAllToMain`).
- **Outputs / side effects:** `setModelAssignment({model, provider, scope:'auxiliary', task, base_url?})`; `Reset all to main` posts `task: '__reset__'` (`:766-774`).
- **Config / env:** Aux assignments live in the profile's model config; `base_url` is carried through `endpointForProvider` so a user-defined provider's endpoint isn't lost (`:691-699`).
- **Edge cases / guards:** `Change` opens an inline editor (below) which forces provider→model re-pick.
- **Rebuild notes:** Named task slots + per-slot assignment + an explicit reset sentinel.

### Auxiliary model inline editor  `id: desktop-settings.model-aux-editor`
- **Surface:** Desktop app
- **Where:** Settings → Model → Auxiliary models → any row after pressing `Change`.
- **What it does:** Picks the provider and model for one auxiliary task.
- **How it works:** `model-settings.tsx:944-1000`. `beginAuxiliaryEdit` seeds the draft from the current assignment (ignoring `auto`) or the main model (`:1042-1053` region / `:735-746`). Changing the provider clears the model (`setAuxDraft(prev => ({...prev, provider: value, model: ''}))`). `Apply` calls `applyAuxiliaryDraft` then `refresh()`.
- **Inputs / options:** Provider select (placeholder `Provider`), Model select (placeholder `Model`, options `withActive(auxDraftProviderModels, auxDraft.model)`), `Apply` (`i18n: common.apply`; disabled unless both halves are set; shows `Applying...` while in flight), `Cancel` (`i18n: common.cancel`).
- **Outputs / side effects:** One auxiliary assignment write; the row leaves edit mode.
- **Config / env:** n/a
- **Edge cases / guards:** Only one row can be in edit mode (`editingAuxTask`).
- **Rebuild notes:** Provider change must clear the model — models are per-provider.

### Stale auxiliary warning banner  `id: desktop-settings.model-stale-aux`
- **Surface:** Desktop app
- **Where:** Settings → Model — under the picker right after a main-model switch, and above the auxiliary list persistently.
- **What it does:** Warns that auxiliary tasks are still pinned to a provider that isn't the current main model, so they may silently bill a different (possibly dead) account.
- **How it works:** `StaleAuxWarning` (`model-settings.tsx:154-176`) renders an amber bordered strip with an `AlertTriangle` and the sentence `<N> auxiliary task(s) (<names>) still run on <provider|other providers>, not your main model.` plus a `Reset all to main` button. Two sources: `switchStaleAux` from the `stale_aux` field of the apply response (shown under the picker), and `persistentStaleAux` (`:911-…` / `:503-521`) computed as any aux entry whose provider is non-empty, not `auto`, and different from the main provider (shown above the aux list only when `switchStaleAux` is empty).
- **Inputs / options:** `Reset all to main` button (disabled while applying).
- **Outputs / side effects:** Posts the `__reset__` auxiliary assignment and clears the banner.
- **Config / env:** n/a
- **Edge cases / guards:** Pluralisation is inline (`task` vs `tasks`); when providers differ across slots the sentence says `other providers`. These two strings are hard-coded English, not i18n keys.
- **Rebuild notes:** Never auto-clear legitimate pins — warn and offer one click.

### Mixture of Agents (MoA) presets  `id: desktop-settings.model-moa`
- **Surface:** Desktop app
- **Where:** Settings → Model → section `Mixture of Agents` (hard-coded English, icon `Cpu`), description `Configure named presets that appear as models under the Mixture of Agents provider. The aggregator is the acting model.`
- **What it does:** Defines named presets of reference models plus an aggregator, exposed as pseudo-models under the `moa` provider.
- **How it works:** `model-settings.tsx:1022-1290`. State from `getMoaModels()` → `{presets, default_preset, active_preset}`. Preset-level ops (`Set default`, `Delete`, `Add preset`) call `saveMoa` immediately (`:452-489`), which cancels any pending debounced slot save and bumps `moaSaveGeneration`. Slot-level edits go through `updateMoaPreset` → `scheduleMoaSave` (`:387-427`): a **600 ms** debounce, held entirely while `moaConfigComplete(next)` is false so a half-filled slot is never PUT (the backend rejects those with HTTP 422 rather than substituting defaults — issue #64156, `:135-142`). `updateMoaSlot` clears `model` whenever `provider` actually changes (`:443-453`). `moaSlotProviderOptions` filters out the `moa` provider itself to prevent a recursive MoA tree.
- **Inputs / options:** Preset select (placeholder `Preset`); `Enabled` switch (size `xs`, reflects `preset.enabled !== false`); `Set default` button; `Delete` button (disabled when only one preset remains); `new preset` text input; `Add preset` button (disabled when blank or a duplicate name); a `Default: <name>` mono line; per-reference-model rows titled `Reference 1`, `Reference 2`, … each with an enable `Switch` (`aria-label` `Disable reference <n>` / `Enable reference <n>`), a provider `Select`, a model `Select`, and a `Remove` button (disabled when only one reference remains); `Add reference model` button (clones the aggregator); and an `Aggregator` row with its own provider + model selects.
- **Outputs / side effects:** `saveMoaModels(config, scopeProfile)`; disabled slots render at `opacity-60`.
- **Config / env:** MoA config is stored server-side per profile.
- **Edge cases / guards:** The whole section is hidden when `getMoaModels()` failed or returned nothing. Deleting the default preset re-points `default_preset` to the first remaining one and clears `active_preset` if it was the deleted one. `moaConfigComplete` (`:143-150`) requires every preset to have ≥1 reference model, every reference slot complete, and a complete aggregator.
- **Rebuild notes:** Hold (don't repair) incomplete payloads; generation counters on both the debounced and explicit writers so they can't race. Better: validate slot compatibility (context length, modality) before saving.

---

## 3. Config section — Model (`?tab=config:model`)

### Context Window (`model_context_length`)  `id: desktop-settings.field.model-context-length`
- **Surface:** Config
- **Where:** Settings → Model → row `Context Window` (label from `FIELD_LABELS.modelContextLength`, `constants.ts:296`).
- **What it does:** Overrides the detected context window of the selected model.
- **How it works:** Rendered by `ConfigField` as a numeric `Input` (schema `{"type":"number","description":"Context window override (0 = auto-detect from model metadata)","category":"general"}`). Description shown: `Leave at 0 to use the selected model's detected context window.` (`FIELD_DESCRIPTIONS.modelContextLength`).
- **Inputs / options:** Number input; empty commits `0`.
- **Outputs / side effects:** `PUT /api/config` `{model_context_length: n}` after the 550 ms debounce.
- **Config / env:** `model_context_length`
- **Edge cases / guards:** `0` = auto-detect. No client-side upper bound.
- **Rebuild notes:** Numeric override with 0-means-auto sentinel.

### Fallback Models (`fallback_providers`)  `id: desktop-settings.field.fallback-providers`
- **Surface:** Config
- **Where:** Settings → Model → row `Fallback Models` (label `FIELD_LABELS.fallbackProviders`), rendered `wide`.
- **What it does:** An ordered list of backup `provider:model` pairs tried when the default model fails.
- **How it works:** `ConfigField` special-cases the key and renders `FallbackModelsField` instead of the generic list input (`config-field.tsx:87-89`) because the value is a list of `{provider, model}` objects that would stringify to `[object Object]`. Description: `Backup provider:model entries to try if the default model fails.`
- **Inputs / options:** See `desktop-settings.fallback-models-field`.
- **Outputs / side effects:** `PUT /api/config` `{fallback_providers: [...]}`.
- **Config / env:** `fallback_providers` (default `[]`)
- **Edge cases / guards:** Schema type is `list`, so without the special case the generic branch would corrupt it.
- **Rebuild notes:** Structured list editor, never a comma-separated string.

### Fallback models structured editor  `id: desktop-settings.fallback-models-field`
- **Surface:** Desktop app
- **Where:** Settings → Model → `Fallback Models` row body. `apps/desktop/src/app/settings/fallback-models-field.tsx`.
- **What it does:** Adds, edits, reorders and removes `{provider, model}` fallback entries with real provider/model catalogs.
- **How it works:** See the dedicated entry in section 12 (`desktop-settings.fallback-editor`).
- **Inputs / options:** See that entry. With zero rows the editor renders a single caption line instead of any control: **"No fallback models — the default model is used unless it fails."** (`i18n: settings.model.fallbackEmpty`, `apps/desktop/src/i18n/en.ts:1101`, rendered at `apps/desktop/src/app/settings/fallback-models-field.tsx:116` as `{rows.length === 0 && <p class="text-xs text-muted-foreground">{m.fallbackEmpty}</p>}`).
- **Outputs / side effects:** Calls the field's `onChange` with the new array.
- **Config / env:** `fallback_providers`
- **Edge cases / guards:** See that entry.
- **Rebuild notes:** See that entry.

---

## 4. Config section — Chat (`?tab=config:chat`)

### Max preview / image load size  `id: desktop-settings.attachment-size`
- **Surface:** Desktop app
- **Where:** Settings → Chat → first row, above the schema fields. Title `Max preview / image load size` (`i18n: settings.config.attachmentSizeTitle`), unit suffix `MB` (`i18n: settings.config.attachmentSizeUnit`), input `aria-label` = `Max preview / image load size in megabytes` (`i18n: settings.config.attachmentSizeLabel`), description `i18n: settings.config.attachmentSizeDesc`.
- **What it does:** Caps how many megabytes the desktop main process will read into a data-URL for an attachment preview or image load.
- **How it works:** `AttachmentSizeSetting` in `config-settings.tsx:461-528`. Device-local pref, NOT `config.yaml`: it reads/writes through `@/store/data-url-read-max` (`$dataUrlReadMaxMb`, `refreshDataUrlReadMaxMb`, `setDataUrlReadMaxMb`, `clampDataUrlReadMaxMb`) which talks to the Electron main process over IPC. Committed on blur or Enter (`event.currentTarget.blur()`), never per keystroke. An empty draft resets to `DATA_URL_READ_DEFAULT_MAX_MB` rather than clamping `Number('') === 0` down to the floor. If the committed value equals the stored one the IPC write and the haptic are skipped. `triggerHaptic('selection')` fires only when the write actually landed.
- **Inputs / options:** One numeric `Input` (`inputMode="numeric"`, `type="number"`, `min={DATA_URL_READ_MIN_MAX_MB}`, `max={DATA_URL_READ_MAX_MAX_MB}`, width `w-20`); Enter blurs to commit.
- **Outputs / side effects:** Persists the cap in the main process; nothing in `config.yaml`.
- **Config / env:** n/a (device-local store).
- **Edge cases / guards:** On a bridge write failure the store keeps the old value and the draft snaps back.
- **Rebuild notes:** Blur/Enter commit + clamp + "empty means default". Better: show the current largest attachment so the cap is meaningful.

### Personality (`display.personality`)  `id: desktop-settings.field.personality`
- **Surface:** Config
- **Where:** Settings → Chat → row `Personality` (`FIELD_LABELS.display.personality`).
- **What it does:** Picks the default assistant style for new sessions.
- **How it works:** Closed `Select`; options from `personalityOptions(config)` (`helpers.ts:240-247`) = `''` + `BUILTIN_PERSONALITIES` + the keys of `agent.personalities`. The empty option renders as `None` (`i18n: settings.config.none`, special-cased in `config-field.tsx:151`). Description `Default assistant style for new sessions.`
- **Inputs / options:** `None` plus the 14 built-ins (`apps/desktop/src/lib/personalities.ts`, mirroring `hermes_cli/personality.py`): `helpful`, `concise`, `technical`, `creative`, `teacher`, `kawaii`, `catgirl`, `pirate`, `shakespeare`, `surfer`, `noir`, `uwu`, `philosopher`, `hype` — rendered through `prettyName()`. Custom personalities defined under `agent.personalities` are appended.
- **Outputs / side effects:** `PUT /api/config` `{display: {personality: "<name>"}}`.
- **Config / env:** `display.personality` (default `""`), `agent.personalities`
- **Edge cases / guards:** A value not in the list is appended by `enumOptionsFor` so it stays selectable.
- **Rebuild notes:** Merge built-ins with user-defined names and keep the current value.

### Timezone (`timezone`)  `id: desktop-settings.field.timezone`
- **Surface:** Config
- **Where:** Settings → Chat → row `Timezone` (`FIELD_LABELS.timezone`).
- **What it does:** Sets the IANA timezone Hermes uses for dates and times.
- **How it works:** Schema `{"type":"select","searchable":true,"clearable":true, "options":[…~590 IANA zones…]}` so `ConfigField` routes to `SearchableSelect` with clear item `System default` (`i18n: settings.config.systemDefault`), placeholder `Search…` and empty message `No results found`. Description `IANA timezone identifier. Blank uses the system timezone.`
- **Inputs / options:** Type-to-filter over the full tz database as served by the backend — including `Africa/*`, `America/*` (with the `America/Argentina/*`, `America/Indiana/*`, `America/Kentucky/*`, `America/North_Dakota/*` sub-trees), `Antarctica/*`, `Arctic/Longyearbyen`, `Asia/*`, `Atlantic/*`, `Australia/*`, `Europe/*`, `Indian/*`, `Pacific/*`, the fixed-offset `Etc/GMT±N` set, the legacy aliases `CET`, `CST6CDT`, `EET`, `EST`, `EST5EDT`, `Factory`, `GMT`, `HST`, `MET`, `MST`, `MST7MDT`, `PST8PDT`, `UTC`, `WET`, and `localtime`. Plus the clear item `System default`.
- **Outputs / side effects:** `PUT /api/config` `{timezone: "<zone>"}`.
- **Config / env:** `timezone` (default `""`)
- **Edge cases / guards:** Closed-world — free text is impossible. Ranking prefers a match in the final path segment.
- **Rebuild notes:** Serve the option list from the backend's `zoneinfo` so it never drifts.

### Reasoning Blocks (`display.show_reasoning`)  `id: desktop-settings.field.show-reasoning`
- **Surface:** Config
- **Where:** Settings → Chat → row `Reasoning Blocks` (`FIELD_LABELS.display.showReasoning`).
- **What it does:** Shows reasoning/thinking sections in the transcript when the backend provides them.
- **How it works:** Boolean → `Switch`. Description `Show reasoning sections when the backend provides them.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{display: {show_reasoning: bool}}`.
- **Config / env:** `display.show_reasoning` (default `true`)
- **Edge cases / guards:** Independent of the Appearance-level `Collapse thinking by default` toggle, which only controls the initial expansion state.
- **Rebuild notes:** Trivial boolean row.

### Image Attachments (`agent.image_input_mode`)  `id: desktop-settings.field.image-input-mode`
- **Surface:** Config
- **Where:** Settings → Chat → row `Image Attachments` (`FIELD_LABELS.agent.imageInputMode`).
- **What it does:** Controls how image attachments are handed to the model.
- **How it works:** Backend schema declares it a plain `string`, so `ENUM_OPTIONS['agent.image_input_mode']` (`constants.ts:225`) supplies the option list and `ConfigField` renders a closed `Select`. Description `Controls how image attachments are sent to the model.`
- **Inputs / options:** `auto`, `native`, `text` (rendered via `prettyName`, i.e. `Auto`, `Native`, `Text`).
- **Outputs / side effects:** `PUT /api/config` `{agent: {image_input_mode: "…"}}`.
- **Config / env:** `agent.image_input_mode` (default `"auto"`)
- **Edge cases / guards:** This is a desktop-side enum override; a value set elsewhere is appended to the list.
- **Rebuild notes:** Prefer backend-declared enums; the override table is a drift risk.

---

## 5. Config section — Workspace (`?tab=config:workspace`)

### Working Directory (`terminal.cwd`)  `id: desktop-settings.field.terminal-cwd`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Working Directory` (`FIELD_LABELS.terminal.cwd`).
- **What it does:** Sets the default project folder for tool and terminal work.
- **How it works:** String → `Input` (or `Textarea` if the current value exceeds 100 characters). Description `Default project folder for tool and terminal work.`
- **Inputs / options:** Free text path; placeholder `Not set`.
- **Outputs / side effects:** `PUT /api/config` `{terminal: {cwd: "…"}}`.
- **Config / env:** `terminal.cwd` (default `"."`)
- **Edge cases / guards:** No folder picker here (the Archived Chats page has one for `Default project directory`); no existence validation.
- **Rebuild notes:** Add a native directory picker and validate the path exists.

### Automatic Repository Discovery (`desktop.repo_scan_enabled`)  `id: desktop-settings.field.repo-scan-enabled`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Automatic Repository Discovery` (`FIELD_LABELS.desktop.repoScanEnabled`).
- **What it does:** Scans local folders for Git repositories so they appear in Projects.
- **How it works:** Boolean → `Switch`. Description `Scan local folders for Git repositories to show in Projects.` After a successful autosave, if the discovery-policy signature changed, `scanAndRecordRepos(true)` runs (`config-settings.tsx:219-226`) — only when editing the active profile.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` plus an immediate repository rescan.
- **Config / env:** `desktop.repo_scan_enabled` (default `true`)
- **Edge cases / guards:** The rescan is skipped for scoped (non-active-profile) edits.
- **Rebuild notes:** Signature-diff the policy so a rescan only runs when the policy actually changed.

### Repository Discovery Roots (`desktop.repo_scan_roots`)  `id: desktop-settings.field.repo-scan-roots`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Repository Discovery Roots` (`FIELD_LABELS.desktop.repoScanRoots`).
- **What it does:** Chooses which folders the repository scan walks.
- **How it works:** `list` → comma-separated `Input` (placeholder `comma-separated values`); values are split on `,`, trimmed and empties dropped. Description `Folders to scan. Leave empty to scan your home directory.`
- **Inputs / options:** Comma-separated absolute paths.
- **Outputs / side effects:** `PUT /api/config` `{desktop: {repo_scan_roots: [...]}}` + rescan.
- **Config / env:** `desktop.repo_scan_roots` (default `[]`)
- **Edge cases / guards:** Empty list means "scan `$HOME`". A path containing a comma cannot be expressed.
- **Rebuild notes:** Use a chip/token editor with a folder picker, not a comma string.

### Excluded Repository Paths (`desktop.repo_scan_exclude_paths`)  `id: desktop-settings.field.repo-scan-exclude`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Excluded Repository Paths` (`FIELD_LABELS.desktop.repoScanExcludePaths`).
- **What it does:** Skips these folders and everything under them during repository discovery.
- **How it works:** `list` → comma-separated `Input`. Description `Folders and their descendants to skip during repository discovery.`
- **Inputs / options:** Comma-separated paths.
- **Outputs / side effects:** `PUT /api/config` + rescan.
- **Config / env:** `desktop.repo_scan_exclude_paths` (default `[]`)
- **Edge cases / guards:** Prefix-matching semantics live in `@/store/projects`.
- **Rebuild notes:** Same as roots; support globs.

### Code Execution Mode (`code_execution.mode`)  `id: desktop-settings.field.code-execution-mode`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Code Execution Mode` (`FIELD_LABELS.codeExecution.mode`).
- **What it does:** Controls how strictly code execution is confined to the current project.
- **How it works:** Backend schema says `string`; `ENUM_OPTIONS['code_execution.mode']` supplies the options so a `Select` renders. Description `How strictly code execution is scoped to the current project.`
- **Inputs / options:** `project`, `strict` (shown as `Project`, `Strict`).
- **Outputs / side effects:** `PUT /api/config` `{code_execution: {mode: "…"}}`.
- **Config / env:** `code_execution.mode` (default `"project"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** Declare the enum backend-side.

### Persistent Shell (`terminal.persistent_shell`)  `id: desktop-settings.field.persistent-shell`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Persistent Shell` (`FIELD_LABELS.terminal.persistentShell`).
- **What it does:** Keeps shell state (cwd, exported vars) between commands when the backend supports it.
- **How it works:** Boolean → `Switch`. Description `Keep shell state between commands when the backend supports it.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{terminal: {persistent_shell: bool}}`.
- **Config / env:** `terminal.persistent_shell` (default `true`)
- **Edge cases / guards:** Not every execution backend honours it.
- **Rebuild notes:** Show which backends support it inline.

### Environment Passthrough (`terminal.env_passthrough`)  `id: desktop-settings.field.env-passthrough`
- **Surface:** Config
- **Where:** Settings → Workspace → row `Environment Passthrough` (`FIELD_LABELS.terminal.envPassthrough`).
- **What it does:** Names the environment variables forwarded into tool execution.
- **How it works:** `list` → comma-separated `Input`. Description `Environment variables to pass into tool execution.`
- **Inputs / options:** Comma-separated variable names.
- **Outputs / side effects:** `PUT /api/config` `{terminal: {env_passthrough: [...]}}`.
- **Config / env:** `terminal.env_passthrough` (default `[]`)
- **Edge cases / guards:** Names only, not `KEY=value` pairs.
- **Rebuild notes:** Support glob patterns and warn on secret-looking names.

### File Read Limit (`file_read_max_chars`)  `id: desktop-settings.field.file-read-max-chars`
- **Surface:** Config
- **Where:** Settings → Workspace → row `File Read Limit` (`FIELD_LABELS.fileReadMaxChars`).
- **What it does:** Caps how many characters one file-read request can return.
- **How it works:** Number → numeric `Input`. Description `Maximum characters Hermes can read from one file request.`
- **Inputs / options:** Number.
- **Outputs / side effects:** `PUT /api/config` `{file_read_max_chars: n}`.
- **Config / env:** `file_read_max_chars` (default `100000`)
- **Edge cases / guards:** Empty commits `0`.
- **Rebuild notes:** Enforce a floor so 0 doesn't silently disable file reads.

---

## 6. Config section — Safety (`?tab=config:safety`)

### Approval Mode (`approvals.mode`)  `id: desktop-settings.field.approvals-mode`
- **Surface:** Config
- **Where:** Settings → Safety → row `Approval Mode` (`FIELD_LABELS.approvals.mode`).
- **What it does:** Decides how Hermes handles commands that need explicit approval.
- **How it works:** Backend schema `{"type":"select","description":"Dangerous command approval mode","options":["manual","smart","off"]}` → closed `Select`. Displayed description `How Hermes handles commands that need explicit approval.` (the i18n copy wins over the schema description).
- **Inputs / options:** `Manual`, `Smart`, `Off`.
- **Outputs / side effects:** `PUT /api/config` `{approvals: {mode: "…"}}`.
- **Config / env:** `approvals.mode` (default `"smart"`)
- **Edge cases / guards:** `smart` uses the `approval` auxiliary model slot.
- **Rebuild notes:** Three-mode ladder; `off` should require a confirmation.

### Approval Timeout (`approvals.timeout`)  `id: desktop-settings.field.approvals-timeout`
- **Surface:** Config
- **Where:** Settings → Safety → row `Approval Timeout` (`FIELD_LABELS.approvals.timeout`).
- **What it does:** How long an approval prompt waits before timing out.
- **How it works:** Number → numeric `Input`. Description `How long approval prompts wait before timing out.`
- **Inputs / options:** Seconds.
- **Outputs / side effects:** `PUT /api/config` `{approvals: {timeout: n}}`.
- **Config / env:** `approvals.timeout` (default `300`)
- **Edge cases / guards:** The unit (seconds) is not shown in the UI.
- **Rebuild notes:** Label the unit.

### Confirm MCP Reloads (`approvals.mcp_reload_confirm`)  `id: desktop-settings.field.mcp-reload-confirm`
- **Surface:** Config
- **Where:** Settings → Safety → row `Confirm MCP Reloads` (`FIELD_LABELS.approvals.mcpReloadConfirm`).
- **What it does:** Requires a confirmation before reloading MCP tool schemas.
- **How it works:** Boolean → `Switch`. No i18n description, and the schema description (`Approvals → Mcp Reload Confirm`) normalizes to the same string as the label, so the description row is suppressed by `config-field.tsx:61-66`.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{approvals: {mcp_reload_confirm: bool}}`.
- **Config / env:** `approvals.mcp_reload_confirm` (default `true`)
- **Edge cases / guards:** The dedup rule means an auto-generated schema description never shows.
- **Rebuild notes:** Write real descriptions for every key; the dedup rule silently hides placeholders.

### Command Allowlist (`command_allowlist`)  `id: desktop-settings.field.command-allowlist`
- **Surface:** Config
- **Where:** Settings → Safety → row `Command Allowlist` (`FIELD_LABELS.commandAllowlist`).
- **What it does:** Commands that never need approval.
- **How it works:** `list` → comma-separated `Input` (placeholder `comma-separated values`).
- **Inputs / options:** Comma-separated command names/prefixes.
- **Outputs / side effects:** `PUT /api/config` `{command_allowlist: [...]}`.
- **Config / env:** `command_allowlist` (default `[]`)
- **Edge cases / guards:** Commas inside an entry are impossible; there is no per-entry validation.
- **Rebuild notes:** Token editor with a live "would this match?" tester.

### Redact Secrets (`security.redact_secrets`)  `id: desktop-settings.field.redact-secrets`
- **Surface:** Config
- **Where:** Settings → Safety → row `Redact Secrets` (`FIELD_LABELS.security.redactSecrets`).
- **What it does:** Hides detected secrets from model-visible content when possible.
- **How it works:** Boolean → `Switch`. Description `Hide detected secrets from model-visible content when possible.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{security: {redact_secrets: bool}}`.
- **Config / env:** `security.redact_secrets` (default `true`)
- **Edge cases / guards:** "when possible" — detection is heuristic.
- **Rebuild notes:** Surface the detector's rule list and a test box.

### Allow Private URLs (`security.allow_private_urls`)  `id: desktop-settings.field.allow-private-urls`
- **Surface:** Config
- **Where:** Settings → Safety → row `Allow Private URLs` (`FIELD_LABELS.security.allowPrivateUrls`).
- **What it does:** Permits tools to fetch RFC1918/loopback/link-local URLs (SSRF surface).
- **How it works:** Boolean → `Switch`; no i18n description, schema description `Security → Allow Private Urls` is deduped away.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{security: {allow_private_urls: bool}}`.
- **Config / env:** `security.allow_private_urls` (default `false`)
- **Edge cases / guards:** Distinct from `browser.allow_private_urls`, which governs the browser tool only.
- **Rebuild notes:** This is a security-relevant toggle and deserves an explicit warning string.

### File Checkpoints (`checkpoints.enabled`)  `id: desktop-settings.field.checkpoints-enabled`
- **Surface:** Config
- **Where:** Settings → Safety → row `File Checkpoints` (`FIELD_LABELS.checkpoints.enabled`).
- **What it does:** Creates rollback snapshots before file edits.
- **How it works:** Boolean → `Switch`. Description `Create rollback snapshots before file edits.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{checkpoints: {enabled: bool}}`.
- **Config / env:** `checkpoints.enabled` (default `false`)
- **Edge cases / guards:** The retention cap lives in Advanced (`checkpoints.max_snapshots`).
- **Rebuild notes:** Pair the toggle and the cap in one section.

---

## 7. Config section — Browser (`?tab=config:browser`)

### Use My Real Browser Profile (`browser.use_real_profile`)  `id: desktop-settings.field.browser-real-profile`
- **Surface:** Config
- **Where:** Settings → Browser → row `Use My Real Browser Profile` (`FIELD_LABELS.browser.useRealProfile`; the same label also exists as `i18n: settings.toolsets.browserRealProfile.label` for the Capabilities panel).
- **What it does:** Local browsing uses a snapshot of your real browser profile so the agent is already logged in to your sites.
- **How it works:** Boolean → `Switch`. Long description (`FIELD_DESCRIPTIONS.browser.useRealProfile`, `constants.ts`): `Local browsing uses your real logins. Hermes copies your default browser's profile (cookies, logins, preferences) into a managed snapshot and drives it with its packaged Chromium — your live profile is never opened directly, and the copy is refreshed from it on each run. Also lets the agent open a local real-profile session on request even when a cloud browser backend is configured. Only Chromium browsers (Chrome, Edge, Brave, Brave Origin, Chromium) are supported; a non-Chromium default fails with a clear message. Off by default.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{browser: {use_real_profile: bool}}`. Turning it off deletes the profile snapshot.
- **Config / env:** `browser.use_real_profile` (default `false`)
- **Edge cases / guards:** Chromium-family default browsers only. The parallel panel in Capabilities shows toasts `Real-profile browsing on` / `New sessions will browse with a snapshot of your default browser profile.` and `Real-profile browsing off` / `The profile snapshot will be deleted; new sessions use a clean browser.` (see `desktop-settings.browser-real-profile-panel`).
- **Rebuild notes:** Copy-then-drive, never open the live profile. Better: per-site consent instead of whole-profile copying.

### Browser Private URLs (`browser.allow_private_urls`)  `id: desktop-settings.field.browser-private-urls`
- **Surface:** Config
- **Where:** Settings → Browser → row `Browser Private URLs` (`FIELD_LABELS.browser.allowPrivateUrls`).
- **What it does:** Lets the browser tool navigate to private/LAN addresses.
- **How it works:** Boolean → `Switch`; schema description `Browser → Allow Private Urls` is deduped away.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{browser: {allow_private_urls: bool}}`.
- **Config / env:** `browser.allow_private_urls` (default `false`)
- **Edge cases / guards:** Separate from the global `security.allow_private_urls`.
- **Rebuild notes:** n/a

### Local Browser For Private URLs (`browser.auto_local_for_private_urls`)  `id: desktop-settings.field.auto-local-private-urls`
- **Surface:** Config
- **Where:** Settings → Browser → row `Local Browser For Private URLs` (`FIELD_LABELS.browser.autoLocalForPrivateUrls`).
- **What it does:** Automatically uses the local browser (instead of a cloud browser backend) when the target is a private address.
- **How it works:** Boolean → `Switch`; schema description deduped away.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{browser: {auto_local_for_private_urls: bool}}`.
- **Config / env:** `browser.auto_local_for_private_urls` (default `true`)
- **Edge cases / guards:** Only meaningful when a remote browser backend is configured.
- **Rebuild notes:** n/a

---

## 8. Config section — Memory & Context (`?tab=config:memory`)

### Persistent Memory (`memory.memory_enabled`)  `id: desktop-settings.field.memory-enabled`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Persistent Memory` (`FIELD_LABELS.memory.memoryEnabled`).
- **What it does:** Saves durable memories that can help future sessions.
- **How it works:** Boolean → `Switch`. Description `Save durable memories that can help future sessions.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{memory: {memory_enabled: bool}}`.
- **Config / env:** `memory.memory_enabled` (default `true`)
- **Edge cases / guards:** This governs the built-in `MEMORY.md`/`USER.md` memory — NOT `memory.provider` (see `isExternalMemoryProvider`, `helpers.ts:391-399`, issue #49513).
- **Rebuild notes:** Keep built-in memory and provider plugins as separate axes.

### User Profile (`memory.user_profile_enabled`)  `id: desktop-settings.field.user-profile-enabled`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `User Profile` (`FIELD_LABELS.memory.userProfileEnabled`).
- **What it does:** Maintains a compact profile of user preferences.
- **How it works:** Boolean → `Switch`. Description `Maintain a compact profile of user preferences.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{memory: {user_profile_enabled: bool}}`.
- **Config / env:** `memory.user_profile_enabled` (default `true`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Memory Budget (`memory.memory_char_limit`)  `id: desktop-settings.field.memory-char-limit`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Memory Budget` (`FIELD_LABELS.memory.memoryCharLimit`).
- **What it does:** Character cap on the memory block injected into context.
- **How it works:** Number → numeric `Input`; schema description deduped away.
- **Inputs / options:** Number of characters.
- **Outputs / side effects:** `PUT /api/config` `{memory: {memory_char_limit: n}}`.
- **Config / env:** `memory.memory_char_limit` (default `2200`)
- **Edge cases / guards:** Empty commits `0`, which would disable the block.
- **Rebuild notes:** Show the live usage against the cap.

### Profile Budget (`memory.user_char_limit`)  `id: desktop-settings.field.user-char-limit`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Profile Budget` (`FIELD_LABELS.memory.userCharLimit`).
- **What it does:** Character cap on the user-profile block.
- **How it works:** Number → numeric `Input`.
- **Inputs / options:** Number of characters.
- **Outputs / side effects:** `PUT /api/config` `{memory: {user_char_limit: n}}`.
- **Config / env:** `memory.user_char_limit` (default `1375`)
- **Edge cases / guards:** Same 0 caveat.
- **Rebuild notes:** n/a

### Memory Provider (`memory.provider`)  `id: desktop-settings.field.memory-provider`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Memory Provider` (`FIELD_LABELS.memory.provider`).
- **What it does:** Selects an external memory plugin instead of (or alongside) built-in memory.
- **How it works:** Options come **only** from the backend schema (`web_server._schema_with_dynamic_provider_options` merges discovery results per request), deliberately absent from `ENUM_OPTIONS` so a static list can't shadow pip-installed providers (`constants.ts:230-235`). The live schema returned `{"type":"select","description":"Memory provider plugin","options":["","byterover","hindsight","holographic","honcho","mem0","openviking","retaindb","supermemory"]}`. Empty renders as `Built-in only` (`i18n: settings.config.builtinOnly`, special-cased at `config-field.tsx:153`).
- **Inputs / options:** `Built-in only` plus every discovered provider — in this install: `Byterover`, `Hindsight`, `Holographic`, `Honcho`, `Mem0`, `Openviking`, `Retaindb`, `Supermemory` (names rendered through `prettyName`).
- **Outputs / side effects:** `PUT /api/config` `{memory: {provider: "…"}}`. Selecting a non-built-in provider mounts two extra affordances in the same row: `MemoryConnect` inline in the description (`config-settings.tsx:422-425`) and `ProviderConfigPanel` beneath it (`:438-444`).
- **Config / env:** `memory.provider` (default `""`)
- **Edge cases / guards:** `isExternalMemoryProvider(v)` treats `''`, `builtin`, `built-in`, `none` (case/space-insensitive) as NOT external, so those never get connect/config affordances.
- **Rebuild notes:** Discovery-driven options + provider-specific sub-panels keyed on the value.

### Context Engine (`context.engine`)  `id: desktop-settings.field.context-engine`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Context Engine` (`FIELD_LABELS.context.engine`).
- **What it does:** Chooses the strategy for managing long conversations near the context limit.
- **How it works:** Both a backend schema enum (`["default","custom"]`) and a desktop override `ENUM_OPTIONS['context.engine'] = ['compressor','default','custom']` (`constants.ts:228`); the desktop override wins in `ConfigField` because `enumOptions` is passed explicitly. Description `Strategy for managing long conversations near the context limit.`
- **Inputs / options:** `Compressor`, `Default`, `Custom` (plus the current value if off-list).
- **Outputs / side effects:** `PUT /api/config` `{context: {engine: "…"}}`.
- **Config / env:** `context.engine` (default `"compressor"`)
- **Edge cases / guards:** The backend schema omits `compressor` even though it is the default — a live drift between the two lists that the desktop override papers over.
- **Rebuild notes:** One source of truth for enum values.

### Auto-Compression (`compression.enabled`)  `id: desktop-settings.field.compression-enabled`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Auto-Compression` (`FIELD_LABELS.compression.enabled`).
- **What it does:** Summarizes older context when conversations get large.
- **How it works:** Boolean → `Switch`. Description `Summarize older context when conversations get large.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{compression: {enabled: bool}}`.
- **Config / env:** `compression.enabled` (default `true`)
- **Edge cases / guards:** Uses the `compression` auxiliary model slot.
- **Rebuild notes:** n/a

### Compression Threshold (`compression.threshold`)  `id: desktop-settings.field.compression-threshold`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Compression Threshold` (`FIELD_LABELS.compression.threshold`).
- **What it does:** Fraction of the context window at which compression kicks in.
- **How it works:** Number → numeric `Input`.
- **Inputs / options:** Number (a 0–1 ratio).
- **Outputs / side effects:** `PUT /api/config` `{compression: {threshold: n}}`.
- **Config / env:** `compression.threshold` (default `0.5`)
- **Edge cases / guards:** No range clamp in the UI; the numeric input accepts any value.
- **Rebuild notes:** Render as a percentage slider with min/max.

### Compression Target (`compression.target_ratio`)  `id: desktop-settings.field.compression-target-ratio`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Compression Target` (`FIELD_LABELS.compression.targetRatio`).
- **What it does:** How much of the original context the summary should occupy.
- **How it works:** Number → numeric `Input`.
- **Inputs / options:** Number (a 0–1 ratio).
- **Outputs / side effects:** `PUT /api/config` `{compression: {target_ratio: n}}`.
- **Config / env:** `compression.target_ratio` (default `0.2`)
- **Edge cases / guards:** Same, no clamp.
- **Rebuild notes:** Same.

### Protected Recent Messages (`compression.protect_last_n`)  `id: desktop-settings.field.compression-protect-last-n`
- **Surface:** Config
- **Where:** Settings → Memory & Context → row `Protected Recent Messages` (`FIELD_LABELS.compression.protectLastN`).
- **What it does:** Keeps the last N messages verbatim, never compressed.
- **How it works:** Number → numeric `Input`.
- **Inputs / options:** Integer.
- **Outputs / side effects:** `PUT /api/config` `{compression: {protect_last_n: n}}`.
- **Config / env:** `compression.protect_last_n` (default `20`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

---

## 9. Config section — Voice (`?tab=config:voice`)

The Voice section declares 42 keys in `SECTIONS` (`constants.ts:645-…`) but renders only the ones
`voiceFieldVisible` allows for the current `tts.provider` / `stt.provider` / `stt.enabled` (see
`desktop-settings.voice-visibility`). Order below is the declared order.

### Text-To-Speech Provider (`tts.provider`)  `id: desktop-settings.field.tts-provider`
- **Surface:** Config
- **Where:** Settings → Voice → row `Text-To-Speech Provider` (`FIELD_LABELS.tts.provider`).
- **What it does:** Picks which engine speaks assistant responses.
- **How it works:** Backend schema `{"type":"select","description":"Text-to-speech provider","options":["edge","elevenlabs","openai","xai","minimax","mistral","gemini","neutts","kittentts","piper"]}`; the desktop `ENUM_OPTIONS['tts.provider']` carries the same ten. `enumOptionsFor` then appends user-declared command providers found under `tts.providers.<name>` or `tts.<name>` (excluding the eleven built-in names incl. `deepinfra`).
- **Inputs / options:** `Edge`, `Elevenlabs`, `Openai`, `Xai`, `Minimax`, `Mistral`, `Gemini`, `Neutts`, `Kittentts`, `Piper` (rendered via `prettyName`), plus any custom command providers, plus the current value if off-list.
- **Outputs / side effects:** `PUT /api/config` `{tts: {provider: "…"}}`; changing it swaps which `tts.<provider>.*` rows are visible.
- **Config / env:** `tts.provider` (default `"edge"`)
- **Edge cases / guards:** `deepinfra` is a real runtime provider but is missing from both option lists — its rows only appear if the value is set out-of-band (then `enumOptionsFor` appends it).
- **Rebuild notes:** Merge built-ins with user command providers; keep the current value.

### Speech To Text (`stt.enabled`)  `id: desktop-settings.field.stt-enabled`
- **Surface:** Config
- **Where:** Settings → Voice → row `Speech To Text` (`FIELD_LABELS.stt.enabled`).
- **What it does:** Turns speech transcription on or off.
- **How it works:** Boolean → `Switch`. Description `Enable local or provider-backed speech transcription.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{stt: {enabled: bool}}`. Turning it off hides every `stt.<provider>.*` row (`helpers.ts:173-175`).
- **Config / env:** `stt.enabled` (default `true`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Echo Transcripts (`stt.echo_transcripts`)  `id: desktop-settings.field.stt-echo-transcripts`
- **Surface:** Config
- **Where:** Settings → Voice → row `Echo Transcripts` (`FIELD_LABELS.stt.echoTranscripts`).
- **What it does:** Posts the raw transcript of a voice message back into the chat.
- **How it works:** Boolean → `Switch`. Description `Post the raw 🎙️ transcript of voice messages back to the chat.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{stt: {echo_transcripts: bool}}`.
- **Config / env:** `stt.echo_transcripts` (default `true`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Speech-To-Text Provider (`stt.provider`)  `id: desktop-settings.field.stt-provider`
- **Surface:** Config
- **Where:** Settings → Voice → row `Speech-To-Text Provider` (`FIELD_LABELS.stt.provider`) — **only present once the key exists in the config**.
- **What it does:** Picks the transcription backend.
- **How it works:** `ENUM_OPTIONS['stt.provider'] = ['local','groq','openai','mistral','xai','elevenlabs']` (`constants.ts:246`). Because the backend deliberately seeds **no** `stt.provider` default (`hermes_cli/config_defaults.py:1902-1912` — "strict selection semantics treat a stored `stt.provider` as an explicit user pick"), the live `/api/config/schema` has no entry for it and `sectionFieldEntries` finds neither a schema nor a config value, so on a fresh install **this row does not render**. Once the key is set (CLI, YAML, or a provider-choosing flow) `inferFieldSchema` types it as `string` and the select appears.
- **Inputs / options:** `Local`, `Groq`, `Openai`, `Mistral`, `Xai`, `Elevenlabs`, plus user command providers, plus the current value.
- **Outputs / side effects:** `PUT /api/config` `{stt: {provider: "…"}}`.
- **Config / env:** `stt.provider` (no default; runtime autodetect ladder covers unset). Runtime also accepts `deepinfra` and `local_command`, which the desktop list omits.
- **Edge cases / guards:** The missing row on a fresh install is the notable one.
- **Rebuild notes:** Render an explicit "Auto (detect)" option instead of hiding the row.

### Read Responses Aloud (`voice.auto_tts`)  `id: desktop-settings.field.voice-auto-tts`
- **Surface:** Config
- **Where:** Settings → Voice → row `Read Responses Aloud` (`FIELD_LABELS.voice.autoTts`).
- **What it does:** Automatically speaks assistant responses.
- **How it works:** Boolean → `Switch`. Description `Automatically speak assistant responses.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{voice: {auto_tts: bool}}`.
- **Config / env:** `voice.auto_tts` (default `false`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Edge Voice (`tts.edge.voice`)  `id: desktop-settings.field.tts-edge-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `Edge Voice` (`FIELD_LABELS.tts.edge.voice`) — visible only when `tts.provider === 'edge'`.
- **What it does:** Chooses the Microsoft Edge neural voice.
- **How it works:** In `FREE_INPUT_KEYS`, so a `ComboboxInput` (free text + suggestions).
- **Inputs / options:** Suggestions (`ENUM_OPTIONS['tts.edge.voice']`): `en-US-AriaNeural`, `en-US-JennyNeural`, `en-US-AndrewNeural`, `en-US-BrianNeural`, `en-US-GuyNeural`, `en-GB-SoniaNeural`. Any of the 400+ Edge voices may be typed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {edge: {voice: "…"}}}`.
- **Config / env:** `tts.edge.voice` (default `"en-US-AriaNeural"`)
- **Edge cases / guards:** The list is explicitly "popular voices", not the full catalog.
- **Rebuild notes:** Fetch the real voice list from `edge-tts` and cache it.

### OpenAI TTS Model (`tts.openai.model`)  `id: desktop-settings.field.tts-openai-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `OpenAI TTS Model` (`FIELD_LABELS.tts.openai.model`) — visible when `tts.provider === 'openai'`.
- **What it does:** Chooses the OpenAI speech model.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {openai: {model: "…"}}}`; also narrows the voice suggestions below.
- **Config / env:** `tts.openai.model` (default `"gpt-4o-mini-tts"`)
- **Edge cases / guards:** Selecting `tts-1`/`tts-1-hd` filters the voice list to nine (see next entry).
- **Rebuild notes:** Model→voice compatibility should be data, not a hard-coded set.

### OpenAI Voice (`tts.openai.voice`)  `id: desktop-settings.field.tts-openai-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `OpenAI Voice` (`FIELD_LABELS.tts.openai.voice`) — visible when `tts.provider === 'openai'`.
- **What it does:** Chooses the OpenAI TTS voice.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`; options narrowed by `enumOptionsFor` per the selected model.
- **Inputs / options:** Full union (13, for `gpt-4o-mini-tts` and unknown/future models): `alloy`, `ash`, `ballad`, `cedar`, `coral`, `echo`, `fable`, `marin`, `nova`, `onyx`, `sage`, `shimmer`, `verse`. Narrowed set (9, for `tts-1`/`tts-1-hd`): `alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.
- **Outputs / side effects:** `PUT /api/config` `{tts: {openai: {voice: "…"}}}`.
- **Config / env:** `tts.openai.voice` (default `"alloy"`)
- **Edge cases / guards:** Offering `marin` against `tts-1` would 400 at the API, hence the narrowing (`helpers.ts:371-377`).
- **Rebuild notes:** n/a

### ElevenLabs Voice (`tts.elevenlabs.voice_id`)  `id: desktop-settings.field.tts-elevenlabs-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `ElevenLabs Voice` (`FIELD_LABELS.tts.elevenlabs.voiceId`) — visible when `tts.provider === 'elevenlabs'`.
- **What it does:** Chooses the ElevenLabs voice, including your cloned voices.
- **How it works:** The only field with a **live** option source: `ConfigSettingsInner` calls `getElevenLabsVoices(scopeProfile)` on mount (`config-settings.tsx:160-181`), and when `result.available` stores `voices.map(v => v.voice_id)` as options and `{voice_id: label}` as `optionLabels`. `ConfigField` receives both (`config-settings.tsx:427-433`), and being a `FREE_INPUT_KEY` renders a `ComboboxInput` whose items show the friendly label while storing the id.
- **Inputs / options:** Every voice on the account (ids with human labels); free text for any other id.
- **Outputs / side effects:** `PUT /api/config` `{tts: {elevenlabs: {voice_id: "…"}}}`.
- **Config / env:** `tts.elevenlabs.voice_id` (default `"pNInz6obpgDQGcFmaJgB"`)
- **Edge cases / guards:** A failed or unavailable fetch clears both options and labels; the field degrades to plain free text (no static fallback list exists for this key).
- **Rebuild notes:** Fetch-with-labels is the pattern every voice field should use.

### ElevenLabs Model (`tts.elevenlabs.model_id`)  `id: desktop-settings.field.tts-elevenlabs-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `ElevenLabs Model` (`FIELD_LABELS.tts.elevenlabs.modelId`) — visible when `tts.provider === 'elevenlabs'`.
- **What it does:** Chooses the ElevenLabs synthesis model.
- **How it works:** Not in `FREE_INPUT_KEYS`, so a closed `Select` from `ENUM_OPTIONS`.
- **Inputs / options:** `eleven_multilingual_v2`, `eleven_turbo_v2_5`, `eleven_flash_v2_5`.
- **Outputs / side effects:** `PUT /api/config` `{tts: {elevenlabs: {model_id: "…"}}}`.
- **Config / env:** `tts.elevenlabs.model_id` (default `"eleven_multilingual_v2"`)
- **Edge cases / guards:** Closed list — a new ElevenLabs model needs a desktop update (or an out-of-band config write, which `enumOptionsFor` then appends).
- **Rebuild notes:** Make it free-input like the sibling voice field.

### xAI (Grok) Voice (`tts.xai.voice_id`)  `id: desktop-settings.field.tts-xai-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI (Grok) Voice` (`FIELD_LABELS.tts.xai.voiceId`) — visible when `tts.provider === 'xai'`.
- **What it does:** Chooses the Grok TTS voice.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`. Description `xAI voice ID (e.g. eve) or a custom voice ID.`
- **Inputs / options:** Suggestion: `eve`. Free text for custom voice IDs.
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {voice_id: "…"}}}`.
- **Config / env:** `tts.xai.voice_id` (default `"eve"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### xAI Language (`tts.xai.language`)  `id: desktop-settings.field.tts-xai-language`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Language` (`FIELD_LABELS.tts.xai.language`) — visible when `tts.provider === 'xai'`.
- **What it does:** Sets the spoken language for Grok TTS.
- **How it works:** Plain string `Input` (no enum). Description `Spoken language code (e.g. en, pt-BR) or "auto" for auto-detection.`
- **Inputs / options:** Free text; placeholder `Not set`.
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {language: "…"}}}`.
- **Config / env:** `tts.xai.language` (default `"en"`)
- **Edge cases / guards:** `auto` is a magic value.
- **Rebuild notes:** n/a

### xAI Playback Speed (`tts.xai.speed`)  `id: desktop-settings.field.tts-xai-speed`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Playback Speed` (`FIELD_LABELS.tts.xai.speed`) — visible when `tts.provider === 'xai'`.
- **What it does:** Speeds up or slows down Grok speech.
- **How it works:** Number → numeric `Input`. Description `Playback speed. 0.7 = slower, 1.0 = normal, 1.5 = faster.`
- **Inputs / options:** Number.
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {speed: n}}}`.
- **Config / env:** `tts.xai.speed` (default `1.0`)
- **Edge cases / guards:** No clamp; empty commits `0`.
- **Rebuild notes:** Slider with the documented range.

### xAI Auto Speech Tags (`tts.xai.auto_speech_tags`)  `id: desktop-settings.field.tts-xai-auto-tags`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Auto Speech Tags` (`FIELD_LABELS.tts.xai.autoSpeechTags`) — visible when `tts.provider === 'xai'`.
- **What it does:** Lets an LLM insert expressive audio tags into the script before synthesis.
- **How it works:** Boolean → `Switch`. Description `Let an LLM insert expressive audio tags ([laughing], [sighs]) into the script before synthesis.`
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {auto_speech_tags: bool}}}`.
- **Config / env:** `tts.xai.auto_speech_tags` (default `false`)
- **Edge cases / guards:** Costs an extra model call per utterance.
- **Rebuild notes:** n/a

### xAI Streaming Latency Optimization (`tts.xai.optimize_streaming_latency`)  `id: desktop-settings.field.tts-xai-latency`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Streaming Latency Optimization` (`FIELD_LABELS.tts.xai.optimizeStreamingLatency`) — visible when `tts.provider === 'xai'`.
- **What it does:** Trades audio quality for lower latency.
- **How it works:** Number → numeric `Input`. Description `Latency vs. quality trade-off. 0 = best quality, 2 = lowest latency.`
- **Inputs / options:** Number 0–2 (not enforced).
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {optimize_streaming_latency: n}}}`.
- **Config / env:** `tts.xai.optimize_streaming_latency` (default `0`)
- **Edge cases / guards:** No clamp.
- **Rebuild notes:** Should be a three-stop segmented control.

### xAI Sample Rate (`tts.xai.sample_rate`)  `id: desktop-settings.field.tts-xai-sample-rate`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Sample Rate` (`FIELD_LABELS.tts.xai.sampleRate`) — visible when `tts.provider === 'xai'`.
- **What it does:** Audio sample rate in Hz.
- **How it works:** Number → numeric `Input`. Description `Audio sample rate in Hz. Higher = better quality, larger files.`
- **Inputs / options:** Number (Hz).
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {sample_rate: n}}}`.
- **Config / env:** `tts.xai.sample_rate` (default `24000`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### xAI Bit Rate (`tts.xai.bit_rate`)  `id: desktop-settings.field.tts-xai-bit-rate`
- **Surface:** Config
- **Where:** Settings → Voice → row `xAI Bit Rate` (`FIELD_LABELS.tts.xai.bitRate`) — visible when `tts.provider === 'xai'`.
- **What it does:** MP3 bitrate in bits per second.
- **How it works:** Number → numeric `Input`. Description `MP3 bitrate in bps. Only applies when codec is mp3.`
- **Inputs / options:** Number (bps).
- **Outputs / side effects:** `PUT /api/config` `{tts: {xai: {bit_rate: n}}}`.
- **Config / env:** `tts.xai.bit_rate` (default `128000`)
- **Edge cases / guards:** No-op for non-mp3 codecs; the codec itself is not exposed in Settings.
- **Rebuild notes:** Hide the row when the codec isn't mp3.

### MiniMax TTS Model (`tts.minimax.model`)  `id: desktop-settings.field.tts-minimax-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `MiniMax TTS Model` (`FIELD_LABELS.tts.minimax.model`) — visible when `tts.provider === 'minimax'`.
- **What it does:** Chooses the MiniMax speech model.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `speech-02-hd`, `speech-02-turbo`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {minimax: {model: "…"}}}`.
- **Config / env:** `tts.minimax.model` (default `"speech-02-hd"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### MiniMax Voice (`tts.minimax.voice_id`)  `id: desktop-settings.field.tts-minimax-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `MiniMax Voice` (`FIELD_LABELS.tts.minimax.voiceId`) — visible when `tts.provider === 'minimax'`.
- **What it does:** Chooses the MiniMax voice id.
- **How it works:** In `FREE_INPUT_KEYS` but has **no** `ENUM_OPTIONS` entry, so `selectOptions` is undefined and `ConfigField` falls through to a plain string `Input` (placeholder `Not set`).
- **Inputs / options:** Free text voice id.
- **Outputs / side effects:** `PUT /api/config` `{tts: {minimax: {voice_id: "…"}}}`.
- **Config / env:** `tts.minimax.voice_id` (default `"English_expressive_narrator"`)
- **Edge cases / guards:** Membership in `FREE_INPUT_KEYS` is inert without options.
- **Rebuild notes:** Fetch the account's voice catalog.

### Mistral TTS Model (`tts.mistral.model`)  `id: desktop-settings.field.tts-mistral-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `Mistral TTS Model` (`FIELD_LABELS.tts.mistral.model`) — visible when `tts.provider === 'mistral'`.
- **What it does:** Chooses the Mistral (Voxtral) speech model.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `voxtral-mini-tts-2603`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {mistral: {model: "…"}}}`.
- **Config / env:** `tts.mistral.model` (default `"voxtral-mini-tts-2603"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Mistral Voice (`tts.mistral.voice_id`)  `id: desktop-settings.field.tts-mistral-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `Mistral Voice` (`FIELD_LABELS.tts.mistral.voiceId`) — visible when `tts.provider === 'mistral'`.
- **What it does:** Chooses the Mistral voice id (a UUID).
- **How it works:** In `FREE_INPUT_KEYS` with no `ENUM_OPTIONS` entry → plain string `Input`.
- **Inputs / options:** Free text.
- **Outputs / side effects:** `PUT /api/config` `{tts: {mistral: {voice_id: "…"}}}`.
- **Config / env:** `tts.mistral.voice_id` (default `"c69964a6-ab8b-4f8a-9465-ec0925096ec8"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Gemini TTS Model (`tts.gemini.model`)  `id: desktop-settings.field.tts-gemini-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `Gemini TTS Model` (`FIELD_LABELS.tts.gemini.model`) — visible when `tts.provider === 'gemini'`.
- **What it does:** Chooses the Gemini speech model.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `gemini-2.5-flash-preview-tts`, `gemini-2.5-pro-preview-tts`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {gemini: {model: "…"}}}`.
- **Config / env:** `tts.gemini.model` (default `"gemini-2.5-flash-preview-tts"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Gemini Voice (`tts.gemini.voice`)  `id: desktop-settings.field.tts-gemini-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `Gemini Voice` (`FIELD_LABELS.tts.gemini.voice`) — visible when `tts.provider === 'gemini'`.
- **What it does:** Chooses the Gemini prebuilt voice.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** All 30 prebuilt voices, in list order: `Zephyr`, `Puck`, `Charon`, `Kore`, `Fenrir`, `Leda`, `Orus`, `Aoede`, `Callirrhoe`, `Autonoe`, `Enceladus`, `Iapetus`, `Umbriel`, `Algieba`, `Despina`, `Erinome`, `Algenib`, `Rasalgethi`, `Laomedeia`, `Achernar`, `Alnilam`, `Schedar`, `Gacrux`, `Pulcherrima`, `Achird`, `Zubenelgenubi`, `Vindemiatrix`, `Sadachbia`, `Sadaltager`, `Sulafat`.
- **Outputs / side effects:** `PUT /api/config` `{tts: {gemini: {voice: "…"}}}`.
- **Config / env:** `tts.gemini.voice` (default `"Kore"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### NeuTTS Model (`tts.neutts.model`)  `id: desktop-settings.field.tts-neutts-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `NeuTTS Model` (`FIELD_LABELS.tts.neutts.model`) — visible when `tts.provider === 'neutts'`.
- **What it does:** Chooses which local NeuTTS weights to load.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `neuphonic/neutts-air-q4-gguf`, `neuphonic/neutts-air-q8-gguf`, `neuphonic/neutts-air`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {neutts: {model: "…"}}}`.
- **Config / env:** `tts.neutts.model` (default `"neuphonic/neutts-air-q4-gguf"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### NeuTTS Device (`tts.neutts.device`)  `id: desktop-settings.field.tts-neutts-device`
- **Surface:** Config
- **Where:** Settings → Voice → row `NeuTTS Device` (`FIELD_LABELS.tts.neutts.device`) — visible when `tts.provider === 'neutts'`.
- **What it does:** Selects the local inference device.
- **How it works:** Not a free-input key → closed `Select` from `ENUM_OPTIONS`. Description `Local inference device for NeuTTS.`
- **Inputs / options:** `Cpu`, `Cuda`, `Mps` (values `cpu`, `cuda`, `mps`).
- **Outputs / side effects:** `PUT /api/config` `{tts: {neutts: {device: "…"}}}`.
- **Config / env:** `tts.neutts.device` (default `"cpu"`)
- **Edge cases / guards:** No availability probe — picking `cuda` on a CPU-only machine fails at runtime.
- **Rebuild notes:** Probe the device list.

### KittenTTS Model (`tts.kittentts.model`)  `id: desktop-settings.field.tts-kittentts-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `KittenTTS Model` (`FIELD_LABELS.tts.kittentts.model`) — visible when `tts.provider === 'kittentts'`.
- **What it does:** Chooses the KittenTTS weights.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `KittenML/kitten-tts-nano-0.8-int8`, `KittenML/kitten-tts-micro-0.8-int8`, `KittenML/kitten-tts-mini-0.8-int8`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {kittentts: {model: "…"}}}`.
- **Config / env:** `tts.kittentts.model` (default `"KittenML/kitten-tts-nano-0.8-int8"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### KittenTTS Voice (`tts.kittentts.voice`)  `id: desktop-settings.field.tts-kittentts-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `KittenTTS Voice` (`FIELD_LABELS.tts.kittentts.voice`) — visible when `tts.provider === 'kittentts'`.
- **What it does:** Chooses the KittenTTS voice.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `Jasper`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {kittentts: {voice: "…"}}}`.
- **Config / env:** `tts.kittentts.voice` (default `"Jasper"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Piper Voice (`tts.piper.voice`)  `id: desktop-settings.field.tts-piper-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `Piper Voice` (`FIELD_LABELS.tts.piper.voice`) — visible when `tts.provider === 'piper'`.
- **What it does:** Chooses the Piper voice model.
- **How it works:** `FREE_INPUT_KEYS` → `ComboboxInput`.
- **Inputs / options:** `en_US-lessac-medium`, `en_US-amy-medium`, `en_US-ryan-high`, `en_GB-alan-medium`; free text allowed.
- **Outputs / side effects:** `PUT /api/config` `{tts: {piper: {voice: "…"}}}`.
- **Config / env:** `tts.piper.voice` (default `"en_US-lessac-medium"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### DeepInfra TTS Model (`tts.deepinfra.model`)  `id: desktop-settings.field.tts-deepinfra-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `DeepInfra TTS Model` (`FIELD_LABELS.tts.deepinfra.model`) — visible only when `tts.provider === 'deepinfra'`, a value the desktop provider dropdown does not offer.
- **What it does:** Chooses the DeepInfra speech model.
- **How it works:** In `FREE_INPUT_KEYS` with no `ENUM_OPTIONS` entry → plain string `Input`.
- **Inputs / options:** Free text.
- **Outputs / side effects:** `PUT /api/config` `{tts: {deepinfra: {model: "…"}}}`.
- **Config / env:** `tts.deepinfra.model` (default `""`)
- **Edge cases / guards:** Practically unreachable from Settings alone because `deepinfra` is missing from `ENUM_OPTIONS['tts.provider']`; set the provider via CLI/YAML first.
- **Rebuild notes:** Add `deepinfra` to the provider list.

### DeepInfra Voice (`tts.deepinfra.voice`)  `id: desktop-settings.field.tts-deepinfra-voice`
- **Surface:** Config
- **Where:** Settings → Voice → row `DeepInfra Voice` (`FIELD_LABELS.tts.deepinfra.voice`) — same visibility caveat.
- **What it does:** Chooses the DeepInfra voice.
- **How it works:** `FREE_INPUT_KEYS`, no options → plain string `Input`.
- **Inputs / options:** Free text.
- **Outputs / side effects:** `PUT /api/config` `{tts: {deepinfra: {voice: "…"}}}`.
- **Config / env:** `tts.deepinfra.voice` (default `"default"`)
- **Edge cases / guards:** Same as above.
- **Rebuild notes:** n/a

### Local Transcription Model (`stt.local.model`)  `id: desktop-settings.field.stt-local-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `Local Transcription Model` (`FIELD_LABELS.stt.local.model`) — visible when `stt.enabled` and `stt.provider === 'local'`.
- **What it does:** Chooses the faster-whisper model size used locally.
- **How it works:** Backend schema `{"type":"select","description":"Local faster-whisper model size","options":["tiny","base","small","medium","large-v3"]}` and the same list in `ENUM_OPTIONS` → closed `Select`.
- **Inputs / options:** `Tiny`, `Base`, `Small`, `Medium`, `Large V3` (values `tiny`, `base`, `small`, `medium`, `large-v3`).
- **Outputs / side effects:** `PUT /api/config` `{stt: {local: {model: "…"}}}`.
- **Config / env:** `stt.local.model` (default `"base"`)
- **Edge cases / guards:** Larger models download on first use.
- **Rebuild notes:** Show download size and whether the weights are cached.

### Transcription Language (`stt.local.language`)  `id: desktop-settings.field.stt-local-language`
- **Surface:** Config
- **Where:** Settings → Voice → row `Transcription Language` (`FIELD_LABELS.stt.local.language`) — visible with local STT.
- **What it does:** Forces a language for local transcription instead of auto-detecting.
- **How it works:** Plain string `Input`.
- **Inputs / options:** Free text language code; blank = auto-detect.
- **Outputs / side effects:** `PUT /api/config` `{stt: {local: {language: "…"}}}`.
- **Config / env:** `stt.local.language` (default `""`)
- **Edge cases / guards:** The global `stt.language` (default `"en"`) is a separate key not exposed in this section.
- **Rebuild notes:** Offer a language picker.

### OpenAI STT Model (`stt.openai.model`)  `id: desktop-settings.field.stt-openai-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `OpenAI STT Model` (`FIELD_LABELS.stt.openai.model`) — visible when `stt.provider === 'openai'`.
- **What it does:** Chooses the OpenAI transcription model.
- **How it works:** Backend schema select + matching `ENUM_OPTIONS` → closed `Select`.
- **Inputs / options:** `whisper-1`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-transcribe`.
- **Outputs / side effects:** `PUT /api/config` `{stt: {openai: {model: "…"}}}`.
- **Config / env:** `stt.openai.model` (default `"whisper-1"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Groq STT Model (`stt.groq.model`)  `id: desktop-settings.field.stt-groq-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `Groq STT Model` (`FIELD_LABELS.stt.groq.model`) — visible when `stt.provider === 'groq'`.
- **What it does:** Chooses the Groq Whisper model.
- **How it works:** Options come from the **backend schema only** (there is no `ENUM_OPTIONS['stt.groq.model']`) → closed `Select`.
- **Inputs / options:** `whisper-large-v3-turbo`, `whisper-large-v3`, `distil-whisper-large-v3-en`.
- **Outputs / side effects:** `PUT /api/config` `{stt: {groq: {model: "…"}}}`.
- **Config / env:** `stt.groq.model` (default `"whisper-large-v3-turbo"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Mistral STT Model (`stt.mistral.model`)  `id: desktop-settings.field.stt-mistral-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `Mistral STT Model` (`FIELD_LABELS.stt.mistral.model`) — visible when `stt.provider === 'mistral'`.
- **What it does:** Chooses the Mistral Voxtral transcription model.
- **How it works:** Backend schema types it `string`, but `ENUM_OPTIONS['stt.mistral.model']` supplies options → closed `Select` (not a free-input key).
- **Inputs / options:** `voxtral-mini-latest`, `voxtral-mini-2602`.
- **Outputs / side effects:** `PUT /api/config` `{stt: {mistral: {model: "…"}}}`.
- **Config / env:** `stt.mistral.model` (default `"voxtral-mini-latest"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### ElevenLabs STT Model (`stt.elevenlabs.model_id`)  `id: desktop-settings.field.stt-elevenlabs-model`
- **Surface:** Config
- **Where:** Settings → Voice → row `ElevenLabs STT Model` (`FIELD_LABELS.stt.elevenlabs.modelId`) — visible when `stt.provider === 'elevenlabs'`.
- **What it does:** Chooses the ElevenLabs Scribe model.
- **How it works:** Backend schema select + matching `ENUM_OPTIONS` → closed `Select`.
- **Inputs / options:** `scribe_v2`, `scribe_v1`.
- **Outputs / side effects:** `PUT /api/config` `{stt: {elevenlabs: {model_id: "…"}}}`.
- **Config / env:** `stt.elevenlabs.model_id` (default `"scribe_v2"`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### ElevenLabs Language (`stt.elevenlabs.language_code`)  `id: desktop-settings.field.stt-elevenlabs-language`
- **Surface:** Config
- **Where:** Settings → Voice → row `ElevenLabs Language` (`FIELD_LABELS.stt.elevenlabs.languageCode`) — visible when `stt.provider === 'elevenlabs'`.
- **What it does:** Pins the transcription language for Scribe.
- **How it works:** Plain string `Input`. Description `Optional ISO-639-3 language code. Blank lets ElevenLabs auto-detect.`
- **Inputs / options:** Free text ISO-639-3 code.
- **Outputs / side effects:** `PUT /api/config` `{stt: {elevenlabs: {language_code: "…"}}}`.
- **Config / env:** `stt.elevenlabs.language_code` (default `""`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Tag Audio Events (`stt.elevenlabs.tag_audio_events`)  `id: desktop-settings.field.stt-elevenlabs-tag-events`
- **Surface:** Config
- **Where:** Settings → Voice → row `Tag Audio Events` (`FIELD_LABELS.stt.elevenlabs.tagAudioEvents`) — visible when `stt.provider === 'elevenlabs'`.
- **What it does:** Annotates non-speech audio events in the transcript.
- **How it works:** Boolean → `Switch`.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{stt: {elevenlabs: {tag_audio_events: bool}}}`.
- **Config / env:** `stt.elevenlabs.tag_audio_events` (default `false`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Speaker Diarization (`stt.elevenlabs.diarize`)  `id: desktop-settings.field.stt-elevenlabs-diarize`
- **Surface:** Config
- **Where:** Settings → Voice → row `Speaker Diarization` (`FIELD_LABELS.stt.elevenlabs.diarize`) — visible when `stt.provider === 'elevenlabs'`.
- **What it does:** Labels who spoke which segment.
- **How it works:** Boolean → `Switch`.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{stt: {elevenlabs: {diarize: bool}}}`.
- **Config / env:** `stt.elevenlabs.diarize` (default `false`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Voice Shortcut (`voice.record_key`)  `id: desktop-settings.field.voice-record-key`
- **Surface:** Config
- **Where:** Settings → Voice → row `Voice Shortcut` (`FIELD_LABELS.voice.recordKey`).
- **What it does:** The push-to-talk key combination.
- **How it works:** Plain string `Input` — no capture widget, the combo is typed as text.
- **Inputs / options:** Free text, e.g. `ctrl+b`.
- **Outputs / side effects:** `PUT /api/config` `{voice: {record_key: "…"}}`.
- **Config / env:** `voice.record_key` (default `"ctrl+b"`)
- **Edge cases / guards:** No validation; a bad combo silently fails at runtime. Note this is separate from the Keyboard Shortcuts panel, which has a real recorder.
- **Rebuild notes:** Reuse the keybind recorder from the Keyboard Shortcuts panel here.

### Max Recording Length (`voice.max_recording_seconds`)  `id: desktop-settings.field.voice-max-recording`
- **Surface:** Config
- **Where:** Settings → Voice → row `Max Recording Length` (`FIELD_LABELS.voice.maxRecordingSeconds`).
- **What it does:** Hard cap on a single voice recording.
- **How it works:** Number → numeric `Input`.
- **Inputs / options:** Seconds.
- **Outputs / side effects:** `PUT /api/config` `{voice: {max_recording_seconds: n}}`.
- **Config / env:** `voice.max_recording_seconds` (default `120`)
- **Edge cases / guards:** n/a
- **Rebuild notes:** Show the unit.

### Client Direct (`voice.client_direct`)  `id: desktop-settings.field.voice-client-direct`
- **Surface:** Config
- **Where:** Settings → Voice → last row; label falls back to `prettyName('client_direct')` = `Client Direct` (no `FIELD_LABELS` entry).
- **What it does:** Lets the client talk to the voice provider directly instead of proxying through the gateway.
- **How it works:** Boolean → `Switch`; schema description `Voice → Client Direct` is deduped away, so the row shows a bare label with no explanation.
- **Inputs / options:** On/Off switch.
- **Outputs / side effects:** `PUT /api/config` `{voice: {client_direct: bool}}`.
- **Config / env:** `voice.client_direct` (default `true`)
- **Edge cases / guards:** This is the one Voice row with neither a curated label nor a description — a copy gap.
- **Rebuild notes:** Add label + description copy.
