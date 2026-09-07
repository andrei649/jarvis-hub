# Desktop app — Chat, sessions, messaging, agents, artifacts, gateway, cron, webhooks, profiles, skills, starmap, learning, pets, hooks, contrib

This shard documents every user-facing surface of the Hermes Desktop (Electron + React/Vite) app that is
*not* the Settings overlay: the chat surface (composer with attachments/slash/@-mentions/voice/paste,
message rendering — tool cards, thinking, reactions, code blocks, artifacts, approval/clarify/MCP-consent
cards, todo & status stack, tips, wake feed —, the right-rail preview pane and terminal tabs), the session
sidebar and all session operations (rename, pin, unread, export, branch/fork, archive/delete, projects and
git worktrees), plus the standalone panels: Messaging (platform cards + pairing), Agents (spawn tree),
Artifacts, Cron (jobs + blueprints), Webhooks, Profiles (switcher, fleet, remote override, SOUL.md),
Capabilities/Skills hub (Skills / Tools / MCP tabs), Memory Graph (starmap), Learning (skill archive),
Pets (petdex + generation + desktop overlay), the desktop-side gateway boot/request layer, the shared
route/keybind hooks, and the `contrib` plugin-surface wiring.
It deliberately leaves to sibling shards: the Settings overlay (`desktop-settings`), the Electron main
process / window chrome / titlebar / updates / onboarding / command palette / HUD / quick-entry / zones
(`desktop-a`, `web-shell`), the web dashboard SPA (`web-*`), CLI commands (`cli-*`), gateway/backend
internals and tool implementations (`tools`, `config-*`, `env-vars`).

---

## 1. Agents panel (subagent spawn tree)

### Agents panel  `id: desktop-b.agents-panel`
- **Surface:** Desktop app
- **Where:** Right-rail / overlay pane "Agents" — opened from the composer status stack chip **“Agents”** (`i18n: statusStack.agents`) or the pane registry id `agents`. Panel header title **“Spawn tree”** (`i18n: agents.title`), subtitle **“Live subagent activity for the current turn.”** (`i18n: agents.subtitle`), close button aria **“Close agents”** (`i18n: agents.close`).
- **What it does:** Shows a live, hierarchical tree of every subagent (delegated child agent) spawned by any session in the current app, with per-agent goal, model, duration, tool count, tokens, streamed progress lines and touched files.
- **How it works:** `apps/desktop/src/app/agents/index.tsx:81` `AgentsView` reads the nanostore `$subagentsBySession` (`apps/desktop/src/store/subagents.ts:47`), flattens every session's list via `allSubagents()` and builds a parent/child tree with `buildSubagentTree()` (`store/subagents.ts:283`) — nodes are keyed by `subagent_id` (or the synthetic `"<parent_id|root>:<task_index>:<goal>"`, `store/subagents.ts:113`), linked through `parentId`, sorted by `startedAt`, then `taskIndex`, then `goal`. The store is fed by gateway events `subagent.progress`, `subagent.thinking`, `subagent.complete` handled in the message-stream hook; `upsertSubagent()` (`store/subagents.ts:270`) merges each payload into the previous row and refuses to mutate a row that is already terminal. Stream lines are capped at `MAX_STREAM = 24` (`store/subagents.ts:44`), each line compacted to 220 chars (96 for tool previews) with consecutive duplicates suppressed (`store/subagents.ts:120`). Grouping into “Delegation N” blocks happens in `groupDelegations()` (`agents/index.tsx:150`): consecutive roots merge when they share the same `taskCount > 1`, started within 5000 ms of each other, and contribute a new `taskIndex`. A 500 ms `setInterval` re-renders relative ages only while at least one node is active *and* the pane is visible (`agents/index.tsx:195`).
- **Inputs / options:** Click any subagent row header — toggles expand/collapse (`aria-expanded`, `agents/index.tsx:327`; expanded shows last 10 stream lines, collapsed shows last 2, `agents/index.tsx:314`). Rows at depth < 2 and running rows auto-expand; a row that transitions to running force-opens (`agents/index.tsx:308`). Close button (panel chrome). No other controls.
- **Outputs / side effects:** Read-only view; no network calls. Summary line joins with `" · "`: **“{n} agents”** / **“{n} agent”** (`agents.agentsCount`), **“{n} active”** (`agents.activeCount`), **“{n} failed”** (`agents.failedCount`), **“{n} tools”** (`agents.toolsCount`), **“{n} files”** (`agents.filesCount`), **“{n} tok”** (`agents.tokens`, compact-formatted), and `$<cost>` to 2 decimals when > 0 (`agents/index.tsx:215`).
- **Config / env:** n/a (pane visibility governed by the zone/pane layout store).
- **Edge cases / guards:** Empty state icon `hubot` with **“No live subagents”** (`agents.emptyTitle`) / **“When a turn delegates work, child agents stream their progress here.”** (`agents.emptyDesc`). A `subagent.complete` event with an unknown status is coerced to `failed` so no row spins forever (`store/subagents.ts:71`). Hard child timeouts have no summary from the backend, so `timeoutSummary()` synthesizes **“Timed out after {seconds}s”** (`store/subagents.ts:131`). `clearSessionSubagents` drops all rows (Stop action), `pruneFinishedSessionSubagents` drops only terminal rows at each `message.start`, `pruneDelegateFallbackSubagents` drops placeholder rows whose id starts with `delegate-tool:` once the real native event arrives (`store/subagents.ts:211,232,251`).
- **Rebuild notes:** Keep a `sessionId → SubagentProgress[]` map fed by three event types; render a tree with per-node ring-buffered stream. A better version would let a row open the child's own session (`sessionId` is already carried on the node but unused by this panel) and would expose per-delegation cost/token budgets.

### Subagent status glyph  `id: desktop-b.agents-status-glyph`
- **Surface:** Desktop app
- **Where:** Leading icon of every row in the Agents spawn tree.
- **What it does:** Encodes a subagent's lifecycle state as one of three glyphs.
- **How it works:** `apps/desktop/src/app/agents/index.tsx:28` `statusGlyph()` — `running`/`queued` → `GlyphSpinner spinner="breathe"` with aria-label **“Running”** (`agents.running`); `failed`/`interrupted` → `AlertCircle` destructive with aria-label **“Failed”** (`agents.failed`); anything else → `CheckCircle2` emerald with aria-label **“Done”** (`agents.done`). Deliberately mirrors `statusGlyph()` in the chat tool-fallback block so both surfaces share a vocabulary.
- **Inputs / options:** n/a (derived from `SubagentStatus`: `completed | failed | interrupted | queued | running`, `store/subagents.ts:5`).
- **Outputs / side effects:** Visual only.
- **Config / env:** n/a
- **Edge cases / guards:** `timeout`/`error` map to `failed`; `cancelled`/`canceled` map to `interrupted` (`store/subagents.ts:57`).
- **Rebuild notes:** Three states is enough; a better version would surface `currentTool` in the glyph tooltip.

### Subagent stream line  `id: desktop-b.agents-stream-line`
- **Surface:** Desktop app
- **Where:** Indented lines under each subagent row in the spawn tree.
- **What it does:** Renders one streamed event from a child agent — a progress note, a thinking snippet, a tool call, or the terminal summary.
- **How it works:** `apps/desktop/src/app/agents/index.tsx:264` `StreamLine`. Kind → colour comes from `STREAM_TONE` (`agents/index.tsx:46`): `progress` muted/75, `summary` foreground/85, `thinking` muted/80, `tool` foreground/85. Glyph from `streamGlyph()` (`agents/index.tsx:53`): error → `AlertCircle`; `tool` → filled dot; `summary` → `CheckCircle2`; `thinking` → an ellipsis `…`; else a small hollow dot. Tool lines render mono and are formatted `ToolLabel("preview")` by `formatTool()` (`store/subagents.ts:94`, where the tool name is split on `_` and each part capitalised). The last line of a running agent gets a trailing `GlyphSpinner` with aria-label **“Streaming”** (`agents.streaming`).
- **Inputs / options:** n/a (read-only).
- **Outputs / side effects:** Marked `data-selectable-text="true"` so the app's text-selection layer allows copying.
- **Config / env:** n/a
- **Edge cases / guards:** Identical consecutive entries (same kind+text+isError) are dropped before storage (`store/subagents.ts:120`).
- **Rebuild notes:** A ring buffer of `{at, kind, text, isError}` with de-dup on append; better: make tool lines clickable to jump to the child's transcript.

### Subagent file list  `id: desktop-b.agents-files`
- **Surface:** Desktop app
- **Where:** Under an expanded subagent row, section label **“Files”** (`i18n: agents.files`).
- **What it does:** Lists the files a child agent wrote (`+ path`) and read (`· path`).
- **How it works:** `apps/desktop/src/app/agents/index.tsx:315` concatenates `filesWritten` (prefix `+ `) then `filesRead` (prefix `· `), shows the first 8 and, if more, **“+{n} more files”** (`agents.moreFiles`) at `agents/index.tsx:378`. Source arrays come from the payload keys `files_written` / `files_read` (`store/subagents.ts:184`), which are only overwritten when non-empty so a later event cannot blank them.
- **Inputs / options:** Visible only while the row is expanded.
- **Outputs / side effects:** Visual only.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden entirely when both lists are empty.
- **Rebuild notes:** Trivial; a better version would make each path a click-to-open preview-pane link.

### Delegation group header  `id: desktop-b.agents-delegation-group`
- **Surface:** Desktop app
- **Where:** Uppercase caption above a fan-out block in the spawn tree, e.g. **“Delegation 1 · 4 workers · 2 active”**.
- **What it does:** Groups sibling subagents that were spawned as one parallel delegation and shows worker counts.
- **How it works:** `apps/desktop/src/app/agents/index.tsx:239` `DelegationGroup`; strings `agents.delegation(index)` → `Delegation {index}`, `agents.workers(count)` → `{count} workers`, `agents.workersActive(count)` → `{count} active`. A group of one node with `taskCount <= 1` renders as a bare row with no header (`agents/index.tsx:242`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Visual only.
- **Config / env:** n/a
- **Edge cases / guards:** Grouping heuristic can merge two genuinely separate delegations that share a task count and start within 5 s.
- **Rebuild notes:** Prefer an explicit `delegation_id` on the wire over the time/shape heuristic.

---

## 2. Artifacts page

### Artifacts page  `id: desktop-b.artifacts-page`
- **Surface:** Desktop app
- **Where:** Left sidebar nav → **“Artifacts”** (`i18n: sidebar.nav.artifacts`), route `/artifacts` (`apps/desktop/src/app/routes.ts`). Rendered by `ArtifactsView` at `apps/desktop/src/app/artifacts/index.tsx:114` inside `PageSearchShell`.
- **What it does:** Indexes every image, file and link that Hermes produced across your 30 most recent sessions (all profiles) and shows them as an image grid plus a sortable table, each row linking back to the chat that made it.
- **How it works:** On mount and on the refresh hotkey it calls `listAllProfileSessions(30, 1)` then, **sequentially** (one transcript resident at a time, `artifact-utils.ts:427`), `getAllSessionMessages(session.id, session.profile)` per session, and extracts artifacts with `collectArtifactsForSession()` (`artifact-utils.ts:383`). Extraction only looks at `assistant` and `tool` messages. From assistant text it scrapes: `MEDIA: <value>` tags (`MEDIA_RE`, `artifact-utils.ts:31`, quotes stripped), markdown images `![alt](url)`, markdown links `[t](url)` that pass `looksLikeArtifact`, bare `http(s)://` URLs, POSIX-ish paths (`/`, `./`, `../`, `~/`) and Windows paths (`C:\…`, `\\…`). From tool messages it additionally: parses the JSON body (also unwrapping `<untrusted_tool_result …>…</untrusted_tool_result>`, `artifact-utils.ts:92`), walks every nested string with its dotted key path, and accepts a value only when a path segment matches `STRONG_TOOL_ARTIFACT_KEY_RE` (`artifact_file|artifact_image|artifact_path|artifact_url|file(s)_created|files_modified|files_written|generated_file|generated_image|generated_path|generated_url|media_tag|output_file|output_path|output_url|result_file|result_path|result_url|saved_to|screenshot_path`) or — only for “producer” tools — `PRODUCER_TOOL_ARTIFACT_KEY_RE` (`artifact(s)`, `attachment(s)`, `download(s)`, `audio|image|video[_file|_path|_url]`, `file_path`, `local_path`, `media[_…]`, `path`). A tool counts as a producer when its name matches `/(?:^|_)(creat(e|ion)|download|export|generat(e|ion)|render|save|speech|tts|write)(?:_|$)/i` or starts with `bfl_flux3_` (legacy image tools kept for old transcripts, `artifact-utils.ts:308`). `browser_vision` output is additionally scanned for `Screenshot path: …` (`artifact-utils.ts:51`). Kind classification (`artifact-utils.ts:156`): `data:image/` or an image extension (`png|jpe?g|gif|webp|svg|bmp`) → `image`; a path or `file://` → `file`; otherwise `link`. Dedup key is `"<sessionId>:<value>"`. Timestamps normalise Unix-seconds→ms when below `10_000_000_000` and fall back to `message.timestamp → session.last_active → session.started_at → Date.now()`.
- **Inputs / options:** Search input placeholder **“Search artifacts...”** (`artifacts.search`) — matches label, value and session title, case-insensitive. Four tabs with live counts: **“All”** (`artifacts.tabAll`), **“Images”** (`artifacts.tabImages`), **“Files”** (`artifacts.tabFiles`), **“Links”** (`artifacts.tabLinks`); the active tab is persisted in the route query param `?tab=` via `useRouteEnumParam('tab', ARTIFACT_FILTERS, 'all')` (`artifacts/index.tsx:121`). Refresh icon button, tooltip/aria **“Refresh artifacts”** (`artifacts.refresh`) or **“Refreshing artifacts”** (`artifacts.refreshing`) while running; also bound to the app-wide refresh hotkey (`useRefreshHotkey`). Image grid: click a thumbnail to zoom (`ZoomableImage`), button **“Chat”** (`artifacts.chat`) to open the owning session. Table: click the primary cell (opens the link externally, or opens a file via `openExternal`), hover the location cell to reveal a copy button labelled **“Copy URL”** (`artifacts.copyUrl`) for links or **“Copy path”** (`artifacts.copyPath`) for files, click the session cell to open that chat. Pagination controls **“Prev”** / **“Next”** (`ui.pagination.previous` / `ui.pagination.next`) with numbered page buttons whose aria is **“Go to {itemLabel} page {n}”** (`artifacts.goToPage`). The Prev/Next controls carry screen-reader labels of their own from the shared primitive: `aria-label` **“Go to previous page”** (`i18n: ui.pagination.previousAria`) and **“Go to next page”** (`i18n: ui.pagination.nextAria`), inside a `<nav aria-label=“pagination”>` (`ui.pagination.label`) — see `gapfill-desktop-b-1-r0.shared-pagination`. Left of the buttons, on both pager bars, sits the **range strip** `{range} {itemLabel}` (`apps/desktop/src/app/artifacts/index.tsx:424`): `pageRangeLabel()` (`index.tsx:57-66`) prints the verbatim string **“0”** (`i18n: artifacts.zero`) when `total === 0`, otherwise **“{start}-{end} of {total}”** (`i18n: artifacts.rangeOf`, e.g. “1-24 of 57”); the noun after it is the pager's `itemLabel` — the image-grid pager always passes **“images”** (`i18n: artifacts.itemsImage`, `index.tsx:362`), and the table pager passes `itemsLabel(kindFilter, a)` (`index.tsx:107-108`) which is **“links”** (`i18n: artifacts.itemsLink`) on the Links tab, **“files”** (`i18n: artifacts.itemsFile`) on the Files tab, and the fallback **“items”** (`i18n: artifacts.itemsGeneric`) on All (and any other filter). The same `itemLabel` is spliced into the numbered-button aria **“Go to {itemLabel} page {n}”**, so those buttons read “Go to images page 2” / “Go to links page 2” / “Go to files page 2” / “Go to items page 2”. Full entry: `gapfill-desktop-b-r1.artifacts-range-strip`.
- **Outputs / side effects:** Opens URLs through `window.hermesDesktop.openExternal` (falls back to `window.open(href,'_blank','noopener,noreferrer')`). For a remote gateway, a `file:` href is downloaded through the authenticated fs bridge instead (`downloadGatewayMediaFile`, `artifacts/index.tsx:279`). Clicking **“Chat”** or a session cell calls `openSession(sessionId, navigate)`. Copy buttons write to the clipboard. No writes to disk otherwise. When that whole `openArtifact(href)` try-block throws — a rejected `openExternal`, a blocked `window.open`, or a failed authenticated download — it raises `notifyError(err, a.openFailed)` whose fallback title is **“Open failed”** (`i18n: artifacts.openFailed`, `apps/desktop/src/app/artifacts/index.tsx:291`).
- **Config / env:** n/a — the page has no config keys of its own; media resolution honours the gateway mode (`isRemoteGateway()`).
- **Edge cases / guards:** Page size is 24 for images and 100 for files/links (`artifacts/index.tsx:225`); page resets to 1 whenever the artifact set, tab or query changes. Pagination renders all pages when `pageCount <= 7`, otherwise `1 … page-1,page,page+1 … last` with ellipses (`artifacts/index.tsx:68`). Transcripts that exceed the backend "safe-load limit" or fail to read produce a 10 s warning notification titled **“Artifacts failed to load”** (`artifacts.failedLoad`) with body `Skipped {n} of {m} recent sessions while indexing artifacts.` and detail lines `{n} exceeded the safe transcript load limit.` / `{n} could not be read.` (`artifacts/index.tsx:160`). Concurrent refreshes are suppressed by `refreshInFlightRef`. Images that fail to load are recorded in `failedImageIds` and their tile renders blank. Loading state shows `PageLoader` with **“Indexing recent session artifacts”** (`artifacts.indexing`); empty state shows **“No artifacts found”** (`artifacts.noArtifactsTitle`) / **“Generated images and file outputs will appear here as sessions produce them.”** (`artifacts.noArtifactsDesc`). Search box hides entirely when zero artifacts exist.
- **Rebuild notes:** Minimum: scan the last N transcripts for URL/path-looking strings, classify by extension, dedupe per session, render grid+table. A better version would let the backend maintain the artifact index incrementally (so the page is instant and covers all sessions, not 30) and would store artifacts as first-class rows rather than re-deriving them by regex from transcripts.

### Artifacts — column layout  `id: desktop-b.artifacts-columns`
- **Surface:** Desktop app
- **Where:** Artifacts page → the table below the image grid.
- **What it does:** Three fixed columns whose headers and widths change with the active tab.
- **How it works:** `ARTIFACT_COLUMNS` at `apps/desktop/src/app/artifacts/index.tsx:651`. Column `primary` header: **“Link title”** (`artifacts.colTitleLink`) on the Links tab, **“Name”** (`artifacts.colTitleFile`) on Files, else **“Title / name”** (`artifacts.colTitleDefault`); width 50 % on Links, 35 % otherwise. Column `location` header: **“URL”** (`artifacts.colLocationLink`) / **“Path”** (`artifacts.colLocationFile`) / **“Location”** (`artifacts.colLocationDefault`); width 30 % / 41 %. Column `session` header always **“Session”** (`artifacts.colSession`); width 20 % / 24 %. The primary cell for links resolves the real page title asynchronously via `useLinkTitle(href)` and falls back to `urlSlugTitleLabel(href)`; the brand favicon comes from `resolveBrandIcon(shortHostLabel(href))`, otherwise `Link2` (links) or `FileText` (files).
- **Inputs / options:** n/a (headers are static per tab).
- **Outputs / side effects:** Visual; the link title fetch is a network read.
- **Config / env:** n/a
- **Edge cases / guards:** Table has `min-w-176` and scrolls horizontally inside its container.
- **Rebuild notes:** Keep cells memoised and the click-context object stable — a non-memoised context re-rendered every cell on each async title fetch (comment at `artifacts/index.tsx:307`).

### Artifact image card  `id: desktop-b.artifacts-image-card`
- **Surface:** Desktop app
- **Where:** Artifacts page → image grid tile (`data-tour="artifact-card"`).
- **What it does:** Shows a thumbnail plus kind, label, raw value, session title, timestamp and a button back to the chat.
- **How it works:** `ArtifactImageCard` at `apps/desktop/src/app/artifacts/index.tsx:467`. The `src` is resolved asynchronously by `artifactImageSrc()` → `resolveMediaDisplaySrc()` (`artifact-utils.ts:187`), which handles the whole ladder: inline `http`/`data` passthrough, remote gateway → authenticated fs bridge, local desktop → Electron `readFileDataUrl`. Kind chip text is **“image”** / **“file”** / **“link”** (`artifacts.kindImage|kindFile|kindLink`). Timestamp is formatted with `fmtDayTime`.
- **Inputs / options:** Click the image → zoom overlay. Button **“Chat”** (`artifacts.chat`, `FolderOpen` icon) → opens the session.
- **Outputs / side effects:** Navigation to the chat route.
- **Config / env:** n/a
- **Edge cases / guards:** A failed resolve marks the id failed and renders an empty framed tile; the effect guards against races with an `active` flag.
- **Rebuild notes:** Resolve media through one shared function so remote/local/desktop legs cannot drift.

---

## 3. Cron / Scheduled jobs

### Scheduled jobs panel  `id: desktop-b.cron-panel`
- **Surface:** Desktop app
- **Where:** Left sidebar nav → **“Scheduled jobs”** (`i18n: sidebar.nav.cron`), route `/cron`. Panel title **“Scheduled jobs”** (`cron.title`), subtitle **“{n} jobs”** / **“{n} job”** (`cron.count`), close aria **“Close cron”** (`cron.close`). Component `CronView`, `apps/desktop/src/app/cron/index.tsx:297`.
- **What it does:** Master/detail manager for the agent's cron jobs — list on the left, schedule + prompt + run history on the right — with create/edit/pause/resume/trigger/delete and one-click “blueprint” recipes.
- **How it works:** Reads the shared nanostore `$cronJobs` (`apps/desktop/src/store/cron.ts:8`) so the panel and the sidebar's Cron section can never drift. Fetching is scoped to the sidebar's `$profileScope`: `cronProfileForScope()` maps the sentinel `ALL_PROFILES` to the string `'all'` (`cron/index.tsx:93`). `refreshCronJobs(profile)` (`cron/cron-actions.ts:258`) calls `getCronJobs(profile)` under a generation/scope token so a profile or connection switch fences stale replies (`cronRequestScope()` = `"<connection>\0<profile>"`, `cron-actions.ts:236`). Mutations run through `mutateAndRefreshCronJobs()` which performs the mutation, re-reads the list, and reports refresh failure separately from mutation failure (`cron-actions.ts:262`). Trigger goes through the shared `createCronTriggerController` from `@hermes/shared` so a job cannot be double-fired. Jobs are filtered by `matchesQuery()` over title, prompt, schedule display, schedule expression and deliver target, then sorted alphabetically by title (`cron/index.tsx:394`). Job title resolution: `name` → first 60 chars of `prompt` → first 60 chars of `script` → `id` → literal `Cron job` (`cron/job-state.ts:115`). Job state: explicit `state` field, else `disabled` when `enabled === false`, else `scheduled` (`job-state.ts:107`).
- **Inputs / options:** Search field, label+placeholder **“Search cron jobs...”** (`cron.search`), with rotating "try" hints built from the first five job titles. Per-row kebab menu labelled **“Manage”** (`cron.manage`) with items **“Edit cron”** (`cron.edit`, icon `edit`) and **“Delete”** (`common.delete`, icon `trash`, danger tone). **“New cron”** add button (`cron.newCron`). Blueprint rows under section label **“Blueprints”** (`cron.blueprints.tab`), each with a `rocket` icon; clicking one opens the create dialog pre-seeded to that blueprint. Detail header actions: **“Resume”** (`cron.resumeTitle`, icon `play`) or **“Pause”** (`cron.pauseTitle`, icon `debug-pause`) depending on state, and **“Trigger now”** (`cron.triggerNow`, icon `zap`, primary). Run-history rows are buttons that open that run's session.
- **Outputs / side effects:** `POST`/`PATCH`/`DELETE` against the cron API (`createCronJob`, `updateCronJob`, `deleteCronJob`, `pauseCronJob`, `resumeCronJob`, `triggerCronJob`, `instantiateAutomationBlueprint`). Success toasts: **“Cron resumed”** (`cron.resumed`), **“Cron paused”** (`cron.paused`), **“Cron triggered”** (`cron.triggered`), **“Cron deleted”** (`cron.deleted`), **“Cron created”** (`cron.created`), **“Cron updated”** (`cron.updated`), **“Blueprint scheduled”** (`cron.blueprints.scheduled`) — message is the job title truncated to 60 chars. Failure toasts: **“Failed to load cron jobs”** (`cron.failedLoad`), **“Failed to update cron job”** (`cron.failedUpdate`), **“Failed to trigger cron job”** (`cron.failedTrigger`), **“Failed to delete cron job”** (`cron.failedDelete`), **“Failed to save cron job”** (`cron.failedSave`). Jobs are stored per-profile by the backend under the Hermes home.
- **Config / env:** Scope follows `$profileScope`; a blueprint created while scope is “all profiles” is written to profile `default` (`cron/index.tsx:585`).
- **Edge cases / guards:** First paint shows `PageLoader` **“Loading cron jobs...”** (`cron.loading`). Fully-empty state (no jobs *and* no blueprints) shows icon `watch`, **“No scheduled jobs yet”** (`cron.emptyTitleNew`), **“Schedule a prompt to run on a cron expression. Hermes will run it and deliver results to the destination you pick.”** (`cron.emptyDescNew`) plus a **“New cron”** button. A search with no hits shows **“No matches”** (`cron.emptyTitleSearch`) in the list and the search-flavoured empty detail **“Try a broader search query.”** (`cron.emptyDescSearch`). The detail pane always falls back to the first visible job so it is never blank while jobs exist. Per-job busy tokens (`Symbol`) prevent stale enable/disable races. `last_error` renders in a destructive-tinted block with an `AlertTriangle`. Opening the panel from the sidebar sets `$cronFocusJobId`, which selects and scrolls that row into view (`[data-panel-row="…"]`, `cron/index.tsx:425`) and is then cleared so re-opening does not re-trigger.
- **Rebuild notes:** Minimum: list + detail + CRUD against a cron API with a per-profile scope token. A better version would stream job state over the change-event channel instead of re-listing after each mutation, and would show the next N fire times, not just the next one.

### Cron job list row  `id: desktop-b.cron-list-row`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → left rail rows.
- **What it does:** One row per job with a coloured state pip and the job title.
- **How it works:** `CronJobListRow` (`apps/desktop/src/app/cron/index.tsx:750`) renders a `PanelListRow` with `dotClassName` from `STATE_DOT` (`cron/job-state.ts:96`): `enabled|running|scheduled` → `bg-primary`, `paused` → `bg-amber-500`, `error` → `bg-destructive`, `completed|disabled` → `bg-(--ui-text-quaternary)`, unknown → `bg-muted-foreground`.
- **Inputs / options:** Click selects; kebab menu as described above.
- **Outputs / side effects:** Selection only.
- **Config / env:** n/a
- **Edge cases / guards:** Same `STATE_DOT` map is used by the sidebar Cron section so the two surfaces agree.
- **Rebuild notes:** Keep the dot palette in one module shared by every surface.

### Cron job detail — metadata block  `id: desktop-b.cron-detail-meta`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → right pane header.
- **What it does:** Shows the state pill and a labelled key/value list for the selected job.
- **How it works:** `CronJobDetail` (`apps/desktop/src/app/cron/index.tsx:775`). Pill text from `cron.states.*`: **“enabled”**, **“scheduled”**, **“running”**, **“paused”**, **“disabled”**, **“error”**, **“completed”**; pill tone from `STATE_TONE` (`cron/index.tsx:108`) — good for enabled/scheduled/running, warn for paused, muted for disabled/completed, bad for error. Rows: **“Frequency”** (`cron.frequencyLabel`) = `schedule_display` → `schedule.display` → `schedule.expr` → `—`; **“Last”** (`cron.last` minus the trailing colon) = `last_run_at` as a locale string; **“Next”** (`cron.next`) = `next_run_at`; **“Deliver to”** (`cron.deliverLabel`) = mapped through `cron.deliveryLabels`; and, only when a per-job override exists, **“Model”** (`cron.modelLabel`).
- **Inputs / options:** n/a (read-only).
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** Unparseable ISO timestamps render verbatim; missing timestamps render `—` (`cron/index.tsx:266`).
- **Rebuild notes:** n/a

### Cron prompt block  `id: desktop-b.cron-detail-prompt`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → right pane, section label **“Prompt”** (`cron.promptLabel`).
- **What it does:** Shows the job's stored prompt verbatim.
- **How it works:** `cron/index.tsx:835` — rendered only when `job.prompt` is non-empty (script-only jobs have none).
- **Inputs / options:** n/a
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden entirely for script-only jobs.
- **Rebuild notes:** n/a

### Cron run history  `id: desktop-b.cron-run-history`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → right pane, section label **“Run history”** (`cron.runHistory`) with a ` · {count}` suffix.
- **What it does:** Lists the sessions this job produced, newest data reloaded on a poll, each clickable to open that session.
- **How it works:** `CronJobRuns` at `apps/desktop/src/app/cron/index.tsx:864` calls `getCronJobRuns(jobId)`. Poll interval is 8000 ms (`RUNS_POLL_INTERVAL_MS`) on backends without change events, dropping to a 60 000 ms backstop (`RUNS_BACKSTOP_INTERVAL_MS`) when `$changeEventsAvailable` is true; it also reloads whenever `$cronChangeTick` advances (a `cron.changed`/`sessions.changed` broadcast) and on `visibilitychange` back to visible. Polling only fires when `document.visibilityState === 'visible'`.
- **Inputs / options:** Click a run row → `onOpenSession(run.id)`.
- **Outputs / side effects:** Navigates to that session. Row label = `title` → `preview` → `id`; right-hand timestamp = `last_active || started_at` (Unix seconds ×1000) as a locale string, or `—`.
- **Config / env:** n/a
- **Edge cases / guards:** While loading, a spinning `loading` codicon; on error the previous list is kept (or `[]`); zero runs shows **“No runs yet”** (`cron.noRuns`).
- **Rebuild notes:** Prefer a push channel over an 8 s poll; the code already has the change-event path.

### Cron editor dialog — create/edit  `id: desktop-b.cron-editor`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → **“New cron”** button / row menu **“Edit cron”**. Dialog title **“New cron job”** (`cron.createTitle`) or **“Edit cron job”** (`cron.editTitle`); description **“Schedule a prompt to run automatically. Use cron syntax or a natural phrase like "every 15 minutes".”** (`cron.createDesc`) or **“Update the schedule, prompt, or delivery target. Changes apply on next run.”** (`cron.editDesc`). Component `CronEditorDialog`, `apps/desktop/src/app/cron/index.tsx:1017`.
- **What it does:** Creates or edits one cron job: name, prompt, frequency, delivery targets, optional per-job model override, and a raw cron/natural-language schedule.
- **How it works:** Form state is reseeded from the job on every open (`cron/index.tsx:1073`). Frequency presets come from `SCHEDULE_OPTIONS` (`cron/index.tsx:99`): `daily`=`0 9 * * *`, `weekdays`=`0 9 * * 1-5`, `weekly`=`0 9 * * 1`, `monthly`=`0 9 1 * *`, `hourly`=`0 * * * *`, `every-15-minutes`=`*/15 * * * *`, `custom` (no expr). When editing, the stored expression is reverse-matched to a preset by `scheduleOptionForExpr()` (`cron/index.tsx:175`) using exact match then a 5-field shape analysis. `scheduleSummary()` (`cron/index.tsx:228`) renders the human hint, e.g. **“Every day at 9:00 AM”** (`cron.everyDayAt`), **“Weekdays at 9:00 AM”** (`cron.weekdaysAt`), **“Every Monday at 9:00 AM”** (`cron.everyDayOfWeekAt` with `cron.days['1']`), **“Monthly on day 1 at 9:00 AM”** (`cron.monthlyOnDayAt`), **“At the top of every hour”** (`cron.topOfHour`) or **“Every hour at :15”** (`cron.everyHourAt`). Model override is encoded `"<providerSlug>:<model>"` and split on the **first** colon so OpenRouter ids like `anthropic/claude-sonnet-4:beta` survive (`cron/index.tsx:1165`). Validation is `validateCronEditor()` (`cron/cron-job-model.ts:138`) → `prompt_and_schedule` | `schedule` | `prompt` | null. Update payloads come from `cronEditorUpdates()` (`cron-job-model.ts:192`), which always writes both `model` and `provider` (null when cleared) for agent jobs and leaves both untouched for script-only jobs.
- **Inputs / options:** (create mode only) **“Start from”** select (`cron.blueprints.startFrom`) with **“Custom”** (`cron.blueprints.custom`) plus one item per blueprint title; a blueprint's `description` renders as a field hint. **“Name”** text input, marked **“Optional”** (`cron.nameLabel` / `cron.optional`), placeholder **“Morning briefing”** (`cron.namePlaceholder`), autofocused. **“Prompt”** textarea (mono, min-height 6 rem), placeholder **“Summarize my unread Slack threads and email me the top 5...”** (`cron.promptPlaceholder`); optional only for script-only jobs. **“Frequency”** select with the seven options labelled **“Daily”**, **“Weekdays”**, **“Weekly”**, **“Monthly”**, **“Hourly”**, **“Every 15 minutes”**, **“Custom”** (`cron.scheduleLabels.*`). **“Deliver to”** checkbox group (see next entry). **“Model”** select, marked Optional, first item **“Default (global model)”** (`cron.modelDefault`), then one `SelectGroup` per configured provider (label = provider name) listing that provider's models in mono; hidden entirely for script-only jobs. **“Custom schedule”** text input shown only when Frequency = Custom, placeholder **“0 9 * * * or weekdays at 9am”** (`cron.customPlaceholder`), hint **“Cron expression, or phrases like "every hour" or "weekdays at 9am".”** (`cron.customHint`); for every other preset the dialog shows a read-only summary strip with the human hint on the left and the raw cron expression in mono on the right. Footer: **“Cancel”** (`common.cancel`) and a submit button reading **“Create cron”** (`cron.createAction`) / **“Save changes”** (`cron.saveChanges`) / **“Saving...”** (`common.saving`) while in flight. When Frequency = **“Weekly”** the summary strip's sentence is built by `dayName()` (`apps/desktop/src/app/cron/index.tsx:157-158`, called at `cron/index.tsx:252`) over the full eight-entry `cron.days` map at `apps/desktop/src/i18n/en.ts:2024-2033` — **“Sunday”** (`cron.days.0`), **“Monday”** (`cron.days.1`), **“Tuesday”** (`cron.days.2`), **“Wednesday”** (`cron.days.3`), **“Thursday”** (`cron.days.4`), **“Friday”** (`cron.days.5`), **“Saturday”** (`cron.days.6`), **“Sunday”** (`cron.days.7`, the deliberate cron DOW-7-aliases-0 duplicate) — with unmapped tokens falling back to **“day {value}”** (`cron.dayFallback`), producing e.g. **“Every Wednesday at 9:00 AM”** or **“Every Saturday at 9:00 AM”** (`cron.everyDayOfWeekAt`). Full treatment: `gapfill-desktop-b-r2.cron-day-names`.
- **Outputs / side effects:** `createCronJob({prompt, schedule, name?, deliver, model?, provider?})` or `updateCronJob(id, updates)`. Closes on success and toasts.
- **Config / env:** Model list comes from `requestModelOptions({})` under React-Query key `['model-options','global']`, filtered to providers with `authenticated !== false` and at least one model — the same gate the chat model picker uses. Delivery targets come from `getCronDeliveryTargets()` under key `['cron-delivery-targets']`. Blueprints under key `['cron-blueprints']`.
- **Edge cases / guards:** Validation errors render inline in a destructive block: **“Schedule is required.”** (`cron.scheduleRequired`), **“Prompt is required.”** (`cron.promptRequired`), **“Prompt and schedule are required.”** (`cron.promptScheduleRequired`). A model pin whose provider/model has since disappeared from the catalog is still rendered as a selectable item so Radix does not blank the trigger (`cron/index.tsx:1135`). Radix rejects empty-string values, so “no override” uses the sentinel `__default__` (`MODEL_DEFAULT_VALUE`, `cron/index.tsx:87`). Script-only jobs (`no_agent` true **and** a non-empty `script`, `cron-job-model.ts:126`) show the hint **“Script-only job (no AI prompt). Job id:”** (`cron.scriptOnlyEditHint`) followed by the id in mono, and hide the model picker. The dialog refuses to close while saving.
- **Edge cases / guards (schedule-hint fallbacks):** `scheduleSummary()` only builds a live sentence when `cronParts(expr)` yields exactly 5 fields; when it does not (a natural-language schedule, a 6-field expression, an empty string) it falls back to the static per-preset hint `c.scheduleHints[option.value]` (`cron/index.tsx:238` and, for `custom`, the unconditional tail at `cron/index.tsx:263`). The seven fallback strings, verbatim: **“Every day at 9:00 AM”** (`i18n: cron.scheduleHints.daily`), **“Monday through Friday at 9:00 AM”** (`i18n: cron.scheduleHints.weekdays`), **“Every Monday at 9:00 AM”** (`i18n: cron.scheduleHints.weekly`), **“The first day of each month at 9:00 AM”** (`i18n: cron.scheduleHints.monthly`), **“At the top of every hour”** (`i18n: cron.scheduleHints.hourly`), **“Every 15 minutes”** (`i18n: cron.scheduleHints['every-15-minutes']`), and — always, since `custom` has no parsed shape of its own — **“Cron syntax or natural language”** (`i18n: cron.scheduleHints.custom`). Their matching preset labels in the Frequency select are `cron.scheduleLabels.daily` **“Daily”**, `cron.scheduleLabels.weekdays` **“Weekdays”**, `cron.scheduleLabels.weekly` **“Weekly”**, `cron.scheduleLabels.monthly` **“Monthly”**, `cron.scheduleLabels.hourly` **“Hourly”**, `cron.scheduleLabels['every-15-minutes']` **“Every 15 minutes”**, `cron.scheduleLabels.custom` **“Custom”**.
- **Rebuild notes:** Split “preset → expression” and “expression → preset” into one table and one matcher; a better version would validate the cron expression client-side and preview the next 5 fire times.

### Cron delivery-target checkboxes (“Deliver to”)  `id: desktop-b.cron-deliver-checkboxes`
- **Surface:** Desktop app
- **Where:** Cron editor dialog → field **“Deliver to”** (`cron.deliverLabel`); also used for the `deliver` slot of a blueprint form.
- **What it does:** Chooses one or more destinations for a job's output; the scheduler accepts a comma-separated list so results can stay local *and* go to a chat platform.
- **How it works:** `DeliverCheckboxes` at `apps/desktop/src/app/cron/index.tsx:955`. Options come from `getCronDeliveryTargets()`; any currently-selected id missing from discovery is appended so editing never silently drops a saved route (`cron/index.tsx:975`). Value parsing/toggling is `parseCronDeliveryTargets()` (splits on `,`, trims, dedupes, defaults to `['local']`) and `toggleCronDeliveryTarget()` (`cron/cron-job-model.ts:168,177`). Labels come from `deliverTargetLabel()` (`cron/index.tsx:934`): `local` → **“This desktop”** (`cron.deliveryLabels.local`), known ids → **“Telegram”**, **“Discord”**, **“Slack”**, **“Email”** (`cron.deliveryLabels.*`), unknown ids → the backend-supplied name.
- **Inputs / options:** One checkbox per target; group is `role="group"` labelled by `<id>-label`.
- **Outputs / side effects:** Writes a comma-joined string into the form's `deliver` value.
- **Config / env:** Targets are discovered from the backend's configured gateway platforms.
- **Edge cases / guards:** Unchecking the last remaining target is a no-op — the list can never become empty (`cron-job-model.ts:184`). A configured platform without a cron home channel is suffixed **“ — set a home channel first”** (`cron.deliverNeedsHomeChannel`).
- **Rebuild notes:** Never let the selection empty out; keep unknown ids so a target that is temporarily offline is not destroyed by an edit.

### Cron blueprints (“Blueprints” / ready-made automations)  `id: desktop-b.cron-blueprints`
- **Surface:** Desktop app
- **Where:** Scheduled jobs panel → list rail section **“Blueprints”** (`cron.blueprints.tab`) and the create dialog's **“Start from”** dropdown.
- **What it does:** One-click automation recipes: pick a recipe, fill its typed slots, and the backend renders the prompt + schedule and creates the job.
- **How it works:** Catalog from `getAutomationBlueprints()`; creation via `instantiateAutomationBlueprint({blueprint: key, values}, writableProfile)` (`cron/index.tsx:590`). Slot controls are rendered by `BlueprintSlotControl` (`apps/desktop/src/app/cron/blueprints.tsx:50`): `enum` and `weekdays` → a `Select` over `field.options`; `time` → `<input type="time">`; anything else → a text input whose placeholder is `field.help || field.label`. The `deliver` slot is deliberately **not** rendered by the blueprint control — the dialog substitutes the shared `DeliverCheckboxes` so only actually-connected platforms are offered (`cron/index.tsx:1240`). Defaults are seeded by `initialBlueprintValues()` (`blueprints.tsx:22`), which rewrites a `deliver` default of `''` or `origin` to `local` because the desktop has no “origin chat”. Help text is suppressed for `text` fields and for `deliver` (`blueprintSlotHelp`, `blueprints.tsx:43`).
- **Inputs / options:** One control per blueprint field (label = `field.label`, hint = `field.help`). Footer: **“Cancel”** (`common.cancel`) and **“Schedule it”** (`cron.blueprints.scheduleIt`) / **“Scheduling...”** (`cron.blueprints.scheduling`).
- **Outputs / side effects:** Creates a real per-profile cron job; success toast titled **“Blueprint scheduled”** (`cron.blueprints.scheduled`) whose message is the rendered `schedule_display` or the blueprint title.
- **Config / env:** When the sidebar scope is “all profiles”, the job is written to profile `default` (blueprints need a writable target, `cron/index.tsx:585`).
- **Edge cases / guards:** A backend 422 arrives as `"422: <message>"`; `cleanBlueprintFieldError()` strips the leading numeric code before showing it inline (`blueprints.tsx:35`). Other blueprint strings: **“Ready-made automations”** (`cron.blueprints.subtitle`), **“Fill in the details and schedule it.”** (`cron.blueprints.dialogDesc`), **“Loading blueprints...”** (`cron.blueprints.loading`), **“Failed to load blueprints”** (`cron.blueprints.failedLoad`), **“No blueprints available”** (`cron.blueprints.emptyTitle`), **“No automation blueprints are available on this backend.”** (`cron.blueprints.emptyDesc`), tab label **“Jobs”** (`cron.tabs.jobs`) / **“Blueprints”** (`cron.tabs.blueprints`).
- **Rebuild notes:** Keep the slot schema on the backend (typed fields with defaults/options/help) and render generically; a better version would preview the rendered prompt and schedule before committing.

### “Scheduled jobs need review” model-impact warning  `id: desktop-b.cron-model-impact`
- **Surface:** Desktop app
- **Where:** Global notification toast, raised whenever the main model assignment is changed (Settings → Model, chat model pill, onboarding). Title **“Scheduled jobs need review”** (`cron.modelImpact.title`).
- **What it does:** Warns that N scheduled jobs will be skipped until their model settings are reviewed, and offers a one-click jump to the Cron view.
- **How it works:** `apps/desktop/src/store/cron-model-impact.ts`. `setMainModelAssignment()` (`:145`) calls `setModelAssignment({...,scope:'main'})`; the response may carry `cron_model_impact`, which is validated by `parseCronModelImpact()` (dedup of job ids, `affected_count` consistent with `jobs.length` or the `truncated` + `MAX_JOBS` shape, `:90`). `publishImpact()` (`:117`) raises a warning notification with the stable id `CRON_MODEL_IMPACT_NOTIFICATION_ID`; when the guard is disabled or the count is 0 it dismisses that notification instead. The detail line lists the first three job names and, if more remain, uses **“{names} and {n} more”** (`cron.modelImpact.detailMore`).
- **Inputs / options:** Notification action button **“Review scheduled jobs”** (`cron.modelImpact.review`) → `requestCronReview()` (opens the Cron view), but only if the profile+connection scope is still current.
- **Outputs / side effects:** A toast; the review action navigates.
- **Config / env:** Depends on the backend's model selection guard (`guard_enabled`).
- **Edge cases / guards:** A *scoped* assignment (targeting another profile's backend) never publishes the warning, because the Review action would open the wrong profile's cron view (`:190`). A missing `cron_model_impact` field means an older backend and leaves any existing warning untouched. Profile/backend switches invalidate the scope and dismiss the toast (`:218`).
- **Rebuild notes:** Return the impact set from the same call that changes the model; scope every follow-up action by (profile, connection) generation.

### Expensive/data-training model confirmation toast  `id: desktop-b.cron-model-confirm`
- **Surface:** Desktop app
- **Where:** Warning toast titled **“Model Selection Warning”** (`cron.modelImpact.confirmTitle`), raised during a main-model assignment.
- **What it does:** Asks for an explicit acknowledgement before persisting a model the backend flags (expensive tier, or a data-training `*-contributor` tier), then retries the assignment with the ack.
- **How it works:** `confirmModelWarning()` at `apps/desktop/src/store/cron-model-impact.ts:224` — the desktop has no blocking confirm API, so it raises a notification whose action resolves a promise. Message is the backend's `confirm_message`, falling back to **“Confirm only if you accept this trade-off.”** (`cron.modelImpact.confirmDetail`), which is also always shown as the detail line. On accept, `setMainModelAssignment` retries with `confirm_expensive_model: true` (`:181`).
- **Inputs / options:** Action button **“Confirm”** (`cron.modelImpact.confirmAction`); dismissing the toast counts as decline.
- **Outputs / side effects:** On decline the assignment throws **“Model change cancelled — you declined the data-training tier warning.”** (`cron.modelImpact.declined`). On a failed save it throws the backend message or **“Hermes did not save that model change.”** (`cron.modelImpact.saveFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** If the caller already passed `confirm_expensive_model` or set `skipConfirmPrompt` (headless onboarding) the code fails closed instead of recursing or dangling a prompt (`:170`). The promise is single-settle (`settled` flag).
- **Rebuild notes:** A modal confirm would be clearer than a toast; keep the fail-closed branch.

---

## 4. Webhooks panel

### Webhooks panel  `id: desktop-b.webhooks-panel`
- **Surface:** Desktop app
- **Where:** Route `/webhooks` (reachable from the command palette / pane registry). Header title **“Subscriptions ({n})”** (`i18n: webhooks.subscriptions`), subtitle **“Subscription changes hot-reload once the receiver is running. Disabled subscriptions reject incoming events.”** (`webhooks.hint`). Component `WebhooksView`, `apps/desktop/src/app/webhooks/index.tsx:80`.
- **What it does:** Manages inbound HTTP webhook subscriptions — enable the receiver, create subscriptions with an event filter and delivery target, enable/disable/delete them, and copy the URL and one-time secret.
- **What/How it works:** React-Query key `['webhooks', profileScope]` over `getWebhooks()` so switching profile re-routes REST to the right backend (`webhooks/index.tsx:86`). The response carries `{enabled, subscriptions[]}`. Mutations: `enableWebhooks()`, `createWebhook()`, `setWebhookEnabled(name, enabled)`, `deleteWebhook(name)`; each is followed by a silent `queryClient.invalidateQueries` reconcile so backend truth wins over the optimistic paint. Filtering matches `name`, `description`, `deliver` and every `event`, case-insensitive (`webhooks/index.tsx:292`). The detail pane always falls back to the first visible subscription.
- **Inputs / options:** Search field labelled/placeholdered **“Search webhooks...”** (`webhooks.search`). Per-row kebab menu: **“Enable”** (`webhooks.enableRow`, icon `check`) or **“Disable”** (`webhooks.disableRow`, icon `circle-slash`) and **“Delete”** (`webhooks.delete`, icon `trash`, danger). **“New subscription”** add button (`webhooks.newSubscription`). Refresh hotkey re-fetches.
- **Outputs / side effects:** Toasts — **“Enabled: "{name}"”** (`webhooks.enabled`), **“Disabled: "{name}"”** (`webhooks.disabled`), **“Created”** (`webhooks.created`), **“Webhook deleted”** (`webhooks.deleted`); failures **“Webhooks failed to load”** (`webhooks.loadFailed`), **“Failed to turn "{name}" on|off”** (`webhooks.toggleFailed`), **“Failed to delete "{name}"”** (`webhooks.deleteFailed`), **“Failed to create: {detail}”** (`webhooks.createFailed`). Subscriptions persist on the backend and hot-reload into the running receiver.
- **Config / env:** Scoped by `$profileScope`. The receiver is itself a gateway platform (`webhooks` platform), so enabling it changes gateway config and needs a restart.
- **Edge cases / guards:** Loading shows `PageLoader` **“Loading webhooks...”** (`webhooks.loading`). Zero subscriptions shows icon `globe`, description **“No webhook subscriptions yet.”** (`webhooks.empty`) and a **“New subscription”** button that is disabled until the receiver is enabled. A search with no hits renders the same empty copy in the list.
- **Rebuild notes:** Minimum: list/create/toggle/delete over a REST resource plus a one-shot secret display. Better: show delivery attempts and last-received timestamps per subscription, and let events be validated against a known catalog.

### “Webhook receiver disabled” banner  `id: desktop-b.webhooks-disabled-banner`
- **Surface:** Desktop app
- **Where:** Webhooks panel → warning alert at the top. Title **“Webhook receiver disabled”** (`webhooks.disabledTitle`), body **“Webhooks are their own gateway platform. Enable them here to accept incoming HTTP events; chat channels are only needed when a subscription delivers to Telegram, Discord, Slack, or another channel.”** (`webhooks.disabledBody`).
- **What it does:** Explains that webhooks are a separate gateway platform and offers a single button to turn the receiver on.
- **How it works:** Rendered when `data.enabled === false` (`webhooks/index.tsx:313`). The button calls `enableWebhooks()`; the backend reply carries `restart_started` and possibly `restart_error`. If the restart started, the panel toasts **“Webhooks enabled; gateway restarting...”** (`webhooks.enabledRestarting`) and re-reads state after 4000 ms; otherwise it raises the restart-needed banner.
- **Inputs / options:** Button **“Enable webhooks”** (`webhooks.enable`) / **“Enabling...”** (`webhooks.enabling`) with a `Globe` icon.
- **Outputs / side effects:** Enables the `webhooks` gateway platform in config and attempts a gateway restart.
- **Config / env:** Gateway platform enablement (see the gateway/config shards for the exact key).
- **Edge cases / guards:** Any throw surfaces **“Gateway restart failed{detail}”** (`webhooks.restartFailed`).
- **Rebuild notes:** n/a

### “Restart gateway” banner  `id: desktop-b.webhooks-restart-banner`
- **Surface:** Desktop app
- **Where:** Webhooks panel → second warning alert. Default text **“Webhooks are enabled, but the gateway still needs a restart before the receiver can come online.”** (`webhooks.restartNeeded`), or the concrete restart error.
- **What it does:** Lets the user restart the gateway from inside the panel when the auto-restart did not happen.
- **How it works:** `restartGatewayNow()` at `apps/desktop/src/app/webhooks/index.tsx:147` calls `runGatewayRestart()` from `store/system-actions`, clears the banner on success and re-reads webhook state after 4000 ms (“give the receiver a moment to bind”).
- **Inputs / options:** Button **“Restart gateway”** (`webhooks.restartGateway`) / **“Restarting...”** (`webhooks.restartingGateway`) with a `RefreshCw` icon, secondary variant.
- **Outputs / side effects:** Restarts the gateway process.
- **Config / env:** n/a
- **Edge cases / guards:** A failed restart re-arms the banner and stores the stringified error as its text; also toasts `webhooks.restartFailed('')`. `webhooks.restarting` (**“Gateway restarting...”**) exists in the catalog for the transitional state.
- **Rebuild notes:** n/a

### New webhook subscription dialog  `id: desktop-b.webhooks-create`
- **Surface:** Desktop app
- **Where:** Webhooks panel → **“New subscription”**. Dialog title **“New subscription”** (`webhooks.newSubscription`).
- **What it does:** Creates a webhook subscription: a name, an optional description and agent prompt, an event filter, skill list, delivery target, and a “deliver payload only” switch.
- **How it works:** `apps/desktop/src/app/webhooks/index.tsx:417`. `handleCreate()` (`:209`) splits `events` and `skills` on commas (trim + drop empties) and posts `createWebhook({name, description?, prompt?, events?, skills?, deliver, deliver_only})`. On success the dialog swaps to the “created” view.
- **Inputs / options:** **“Name”** (`webhooks.fieldName`) input, autofocused, placeholder **“e.g. github-push”** (`webhooks.fieldNamePlaceholder`). **“Description”** (`webhooks.fieldDescription`) input, placeholder **“What this webhook does (optional)”** (`webhooks.fieldDescriptionPlaceholder`). **“Prompt”** (`webhooks.fieldPrompt`) textarea (min-height 6 rem), placeholder **“Instructions for the agent when this webhook fires (optional)”** (`webhooks.fieldPromptPlaceholder`). **“Events”** (`webhooks.fieldEvents`) input, placeholder **“comma-separated, leave empty for all”** (`webhooks.fieldEventsPlaceholder`). **“Skills”** (`webhooks.fieldSkills`) input, placeholder **“comma-separated skill names (optional)”** (`webhooks.fieldSkillsPlaceholder`). **“Deliver to”** (`webhooks.fieldDeliver`) select with exactly six options from `DELIVER_OPTIONS` (`webhooks/index.tsx:56`): **“Log”** (`log`), **“Telegram”** (`telegram`), **“Discord”** (`discord`), **“Slack”** (`slack`), **“Email”** (`email`), **“GitHub comment”** (`github_comment`) — labels from `webhooks.deliverOptions.*`. **“Deliver payload only”** (`webhooks.fieldDeliverOnly`) switch. Footer submit button **“Create”** (`webhooks.create`) / **“Creating...”** (`webhooks.creating`).
- **Outputs / side effects:** Creates the subscription; the list reloads silently.
- **Config / env:** n/a
- **Edge cases / guards:** An empty name raises the error toast **“Name required”** (`webhooks.nameRequired`) and aborts before the request. The dialog cannot be dismissed while `creating` is true (`closeCreate`, `:200`). The form is reset after a successful create so a second subscription starts blank.
- **Rebuild notes:** Keep the event/skill fields as free comma lists but validate names server-side; better: a picker sourced from the real event catalog and the installed skill list.

### Created-subscription result (URL + one-time secret)  `id: desktop-b.webhooks-created`
- **Surface:** Desktop app
- **Where:** The same dialog after a successful create. Title **“Subscription created”** (`webhooks.createdTitle`), description **“Copy the secret now — it is only shown once.”** (`webhooks.createdSecretHint`).
- **What it does:** Shows the public webhook URL and the signing secret with copy buttons; the secret is never retrievable again.
- **How it works:** `apps/desktop/src/app/webhooks/index.tsx:424` renders two `ListRow`s titled **“Webhook URL”** (`webhooks.webhookUrl`) and **“Secret (shown once)”** (`webhooks.secretOnce`), each wrapping the shared `CopyValueRow` (`webhooks/index.tsx:67`) — a flat token-backed row with a truncated mono value and a `CopyButton` labelled **“Copy”** (`webhooks.copy`).
- **Inputs / options:** Two copy buttons plus a footer button **“Done”** (`webhooks.done`).
- **Outputs / side effects:** Clipboard writes.
- **Config / env:** n/a
- **Edge cases / guards:** Closing without copying loses the secret permanently (backend only returns it at creation).
- **Rebuild notes:** Offer a "regenerate secret" action so a lost secret is recoverable without deleting the subscription.

### Webhook detail pane  `id: desktop-b.webhooks-detail`
- **Surface:** Desktop app
- **Where:** Webhooks panel → right pane.
- **What it does:** Shows one subscription's delivery target, event filter, skills, URL, description and prompt.
- **How it works:** `WebhookDetail` at `apps/desktop/src/app/webhooks/index.tsx:546`. Header shows the name and, when `deliver_only` is set, a warn pill reading **“deliver only”** (`webhooks.deliverOnly`). Meta rows: **“Deliver to”** with the mapped label, **“Events”** rendered as pills (or the literal **“(all)”** (`webhooks.all`) when the list is empty), and **“Skills”** as pills only when non-empty. Below the meta, a `CopyValueRow` for `sub.url`. Then optional sections **“Description”** (plain paragraph) and **“Prompt”** (a `PanelBlock`).
- **Inputs / options:** Copy button on the URL row.
- **Outputs / side effects:** Clipboard.
- **Config / env:** n/a
- **Edge cases / guards:** The secret is not shown here — only at creation time.
- **Rebuild notes:** n/a

### Delete webhook confirmation  `id: desktop-b.webhooks-delete`
- **Surface:** Desktop app
- **Where:** Webhooks panel → row menu **“Delete”**. Confirm dialog title **“Delete webhook”** (`webhooks.deleteTitle`), body **“This will permanently remove ”** + the name in bold + **“. This cannot be undone.”** (`webhooks.deleteDescPrefix` / `webhooks.deleteDescSuffix`).
- **What it does:** Permanently removes a subscription.
- **How it works:** `handleDelete()` (`apps/desktop/src/app/webhooks/index.tsx:277`) calls `deleteWebhook(name)`; it re-throws on failure so the `ConfirmDialog` reports the error inline and stays open.
- **Inputs / options:** Buttons **“Cancel”** (`common.cancel`) and **“Delete”** (`webhooks.delete`), destructive styling; busy label **“Deleting...”** (`webhooks.deleting`).
- **Outputs / side effects:** Removes the subscription; success toast titled **“Webhook deleted”** with the name.
- **Config / env:** n/a
- **Edge cases / guards:** The dialog owns the pending→done→close beat, so a failed delete keeps the dialog open with the error visible.
- **Rebuild notes:** n/a

---

## 5. Messaging page (gateway platform cards + pairing)

### Messaging page  `id: desktop-b.messaging-page`
- **Surface:** Desktop app
- **Where:** Left sidebar nav → **“Messaging”** (`i18n: sidebar.nav.messaging`), route `/messaging`. Component `MessagingView`, `apps/desktop/src/app/messaging/index.tsx:126`.
- **What it does:** Lists every gateway messaging platform (Telegram, Discord, Slack, …), shows its live connection state, lets you enable/disable it, fill in its credentials, and approve or revoke the users allowed to talk to it.
- **How it works:** Master/detail layout inside `PageSearchShell`. `getMessagingPlatforms(scopeProfile)` fills the platform list; `getPairing(scopeProfile)` fills `{approved[], pending[]}`. Scope comes from `$settingsRequestProfile` (the shared settings “Applies to” scope) and is rendered as a `SettingsProfileScope` strip above the list, hidden for single-profile users (`messaging/index.tsx:434`). Live refresh: when `$changeEventsAvailable`, a `platforms.changed` tick (gateway persisting connect/disconnect health to `gateway_state.json`) silently refreshes platforms and a **separate** `pairing.changed` tick refreshes pairing — deliberately two signals, because a new pairing request never moves `gateway_state.json` (`messaging/index.tsx:217,231`). On backends without change events a 6000 ms interval refreshes both, but only while the document is visible (`messaging/index.tsx:243`). The selected platform id is stored in the route query param `?platform=` via `useRouteEnumParam` (`messaging/index.tsx:148`).
- **Inputs / options:** Search field placeholder **“Search messaging...”** (`messaging.search`) — matches platform id, name, description and state; hidden when no platforms exist. Clicking a row selects it. Refresh hotkey re-reads both endpoints. Everything else lives in the detail pane / action bar (see the following entries).
- **Outputs / side effects:** `updateMessagingPlatform(id, {...}, scopeProfile)` writes gateway env/enabled state; `approvePairing` / `revokePairing` write the pairing store.
- **Config / env:** Every credential field maps to a gateway environment variable (see the “Messaging credential field” entry and the `env-vars` shard for each variable's meaning). Scope: `$settingsRequestProfile`.
- **Edge cases / guards:** Initial load shows `PageLoader` **“Loading messaging platforms...”** (`messaging.loading`); a load failure toasts **“Messaging platforms failed to load”** (`messaging.loadFailed`). A profile-scope switch immediately blanks `platforms`, `pairing` and pending `edits` so stale rows cannot be toggled against the wrong backend (`messaging/index.tsx:200`). Pairing fetch failures are swallowed on purpose — an older backend without the endpoint should show no rows, not an error banner (`messaging/index.tsx:172`).
- **Rebuild notes:** Keep platform health and pairing on separate change signals; blank the view on scope change. Better: show per-platform message throughput and last inbound message time.

### Platform list row  `id: desktop-b.messaging-platform-row`
- **Surface:** Desktop app
- **Where:** Messaging page → left list.
- **What it does:** One clickable row per platform showing the brand avatar, name, a pending-pairing badge and a status dot.
- **How it works:** `PlatformRow` (`apps/desktop/src/app/messaging/index.tsx:504`). Status tone from `stateTone()` (`messaging/index.tsx:60`): disabled → `muted`; `connected` → `good`; `fatal` or `startup_failed` → `bad`; anything else → `warn`. The pending badge is an amber pill with the count and aria-label **“{n} pending pairing request(s)”** (`messaging.pendingAria`). Avatar is `PlatformAvatar` (`apps/desktop/src/app/messaging/platform-icon.tsx:85`).
- **Inputs / options:** Click to select.
- **Outputs / side effects:** Sets `?platform=<id>`.
- **Config / env:** n/a
- **Edge cases / guards:** The pending badge is the only pre-open signal that someone is waiting to be let in.
- **Rebuild notes:** n/a

### Platform brand avatar  `id: desktop-b.messaging-platform-avatar`
- **Surface:** Desktop app
- **Where:** Messaging page → list rows and detail header.
- **What it does:** Paints each platform's brand glyph in its native colour over a soft tint, with a letter monogram fallback.
- **How it works:** `apps/desktop/src/app/messaging/platform-icon.tsx:54` `PLATFORM_ICONS` maps 17 platform ids to `{Icon, color, kind, monogram?}`: `telegram` `SiTelegram` `#26A5E4`; `discord` `SiDiscord` `#5865F2`; `slack` monogram **“S”** `#4A154B` (Simple Icons removed the Slack mark at Salesforce's request); `mattermost` `SiMattermost` `#0058CC`; `matrix` `SiMatrix` `#000000`; `signal` `SiSignal` `#3A76F0`; `whatsapp` `SiWhatsapp` `#25D366`; `bluebubbles` `SiApple` `#0BD318`; `photon` a hand-drawn three-bar `PhotonIcon` `#6366F1` (`platform-icon.tsx:27`); `homeassistant` `SiHomeassistant` `#18BCF2`; `email` `SiGmail` `#EA4335`; `sms` `MessageSquareText` `#F43F5E` (generic); `webhook` `LinkIcon` `#71717A` (generic); `api_server` `Globe` `#64748B` (generic); `weixin` `SiWechat` `#07C160`; `qqbot` `SiQq` `#EB1923`; `yuanbao` `SiBilibili` `#FB7299`. Anything unmapped falls back to `AvatarChip`'s name-derived monogram.
- **Inputs / options:** n/a
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** The component is `forwardRef` + spreads `...rest` because Radix Tooltip's `asChild` injects a ref and pointer handlers — a plain function component silently dropped them and the tooltip never opened (comment at `platform-icon.tsx:80`).
- **Rebuild notes:** n/a

### Platform detail header (state + setup pills + hint)  `id: desktop-b.messaging-detail-header`
- **Surface:** Desktop app
- **Where:** Messaging page → right pane header.
- **What it does:** Shows the platform name, its connection state pill, “needs setup” / “gateway stopped” pills, the description, and a corrective hint.
- **How it works:** `PlatformDetail` header (`apps/desktop/src/app/messaging/index.tsx:568`). State labels come from `messaging.states`: **“Connected”**, **“Connecting”**, **“Disabled”**, **“Error”** (`fatal`), **“Messaging gateway stopped”** (`gateway_stopped`), **“Needs setup”** (`not_configured`), **“Restart needed”** (`pending_restart`), **“Retrying”** (`retrying`), **“Startup failed”** (`startup_failed`); an unknown state has its underscores replaced by spaces, and a missing state renders **“Unknown”** (`messaging.unknown`). Extra pills: **“Needs setup”** (`messaging.needsSetup`) when `configured` is false, **“Messaging gateway stopped”** (`messaging.gatewayStopped`) when `gateway_running` is false. `PlatformHint` (`messaging/index.tsx:920`) adds **“Restart the gateway from the status bar to apply this change.”** (`messaging.hintPendingRestart`) for `pending_restart`, or **“Start the gateway from the status bar to connect.”** (`messaging.hintGatewayStopped`) when the gateway is not running; nothing is shown when the platform is disabled or already connected. A `platform.error_message` renders in an `ErrorBanner`.
- **Inputs / options:** n/a (display only).
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** “Resting” states earn no pill — only actionable ones (comment at `messaging/index.tsx:576`).
- **Rebuild notes:** n/a

### Platform enable/disable switch  `id: desktop-b.messaging-enable-switch`
- **Surface:** Desktop app
- **Where:** Messaging page → detail action bar (bottom-left switch).
- **What it does:** Turns a messaging platform on or off in the gateway config.
- **How it works:** `PlatformActionBar` (`apps/desktop/src/app/messaging/index.tsx:770`) → `handleToggle()` (`messaging/index.tsx:290`) calls `updateMessagingPlatform(id, {enabled}, scopeProfile)` and optimistically rewrites the local row's state to `pending_restart` (if configured), `not_configured` (enabled but unconfigured) or `disabled`.
- **Inputs / options:** One `Switch` (size `xs`) with aria-label **“Enable {name}”** (`messaging.enableAria`) or **“Disable {name}”** (`messaging.disableAria`); disabled while `saving === "enabled:<id>"`.
- **Outputs / side effects:** Success toast titled **“{name} enabled”** (`messaging.platformEnabled`) or **“{name} disabled”** (`messaging.platformDisabled`) with message **“This change takes effect after a gateway restart.”** (`messaging.restartToApply`) and a one-click action button **“Restart gateway”** (`commandCenter.restartGateway`) wired to `runGatewayRestart()`. Failure toast **“Failed to update {name}”** (`messaging.failedUpdate`).
- **Config / env:** Writes the platform's `enabled` flag into the gateway config for the scoped profile.
- **Edge cases / guards:** The optimistic state is corrected by the next refresh.
- **Rebuild notes:** n/a

### Save credentials (“Save changes”)  `id: desktop-b.messaging-save`
- **Surface:** Desktop app
- **Where:** Messaging page → detail action bar (right).
- **What it does:** Writes all edited credential fields for the selected platform in one request.
- **How it works:** `handleSave()` (`apps/desktop/src/app/messaging/index.tsx:319`) trims every edit and drops empties (`trimEdits`, `messaging/index.tsx:76`); if nothing survives it returns without a request. Otherwise `updateMessagingPlatform(id, {env}, scopeProfile)`, then clears the platform's edit map and re-reads platforms.
- **Inputs / options:** Button **“Save changes”** (`messaging.saveChanges`) with a `Save` icon, disabled unless there are trimmed edits; label becomes **“Saving...”** (`messaging.saving`) while in flight. A caption **“Unsaved changes”** (`messaging.unsavedChanges`) appears to its left whenever edits exist.
- **Outputs / side effects:** Success toast titled **“{name} setup saved”** (`messaging.setupSaved`), message **“New credentials take effect after a gateway restart.”** (`messaging.restartToReconnect`), with the same **“Restart gateway”** action. Failure toast **“Failed to save {name}”** (`messaging.failedSave`).
- **Config / env:** Writes gateway environment variables for the scoped profile.
- **Edge cases / guards:** Whitespace-only values are treated as no change.
- **Rebuild notes:** n/a

### Messaging credential field  `id: desktop-b.messaging-field`
- **Surface:** Desktop app
- **Where:** Messaging page → detail sections **“Required”** (`messaging.required`), **“Recommended”** (`messaging.recommended`) and the collapsible **“Advanced ({n})”** (`messaging.advanced`).
- **What it does:** One credential/env-var input per platform field with docs link, clear button, and a “set” badge.
- **How it works:** `MessagingField` (`apps/desktop/src/app/messaging/index.tsx:845`) renders a `ListRow` whose action is an `Input` (`type="password"` when `field.is_password`), plus optional icon buttons. Copy resolution (`fieldCopy`, `messaging/index.tsx:115`): label = localized `messaging.fieldCopy[KEY].label` → `field.prompt` → the raw key; help = localized `.help` → `field.description`; placeholder = localized `.placeholder` → `field.prompt`. When the value is already set the placeholder becomes `field.redacted_value` or **“Replace current value”** (`messaging.replaceValue`). Bucketing: `field.required` → Required; not required and not advanced → Recommended; advanced → the disclosure. A field is advanced when `field.advanced` **or** its key is in the local `FIELD_COPY` advanced list (`messaging/index.tsx:98`): `TELEGRAM_PROXY`, `DISCORD_REPLY_TO_MODE`, `DISCORD_ALLOW_ALL_USERS`, `DISCORD_HOME_CHANNEL`, `DISCORD_HOME_CHANNEL_NAME`, `BLUEBUBBLES_ALLOW_ALL_USERS`, `MATTERMOST_ALLOW_ALL_USERS`, `MATTERMOST_HOME_CHANNEL`, `QQ_ALLOW_ALL_USERS`, `QQBOT_HOME_CHANNEL`, `QQBOT_HOME_CHANNEL_NAME`, `WHATSAPP_ENABLED`, `WHATSAPP_MODE`.
- **Inputs / options:** Text/password input; an external-link icon button tooltipped **“Open docs”** (`messaging.openDocs`) when `field.url` is present; a trash icon button tooltipped **“Clear {key}”** (`messaging.clearField`) when the value is set. The **“Advanced ({n})”** header toggles the disclosure caret.
- **Outputs / side effects:** Typing writes into the local `edits` map only. Clearing calls `updateMessagingPlatform(id, {clear_env:[key]})` immediately, then refreshes and toasts **“{key} cleared”** (`messaging.keyCleared`) with message **“{name} setup was updated.”** (`messaging.setupUpdated`); failure toasts **“Failed to clear {key}”** (`messaging.failedClear`).
- **Config / env:** Each field is a gateway environment variable. The localized copy catalog (`messaging.fieldCopy`) covers, verbatim: `TELEGRAM_BOT_TOKEN` (**“Bot token”** / **“Create a bot with @BotFather, then paste the token it gives you.”** / placeholder **“Paste Telegram bot token”**), `TELEGRAM_ALLOWED_USERS` (**“Allowed Telegram user IDs”** / **“Recommended. Comma-separated numeric IDs from @userinfobot. Without this, anyone can DM your bot.”**), `TELEGRAM_PROXY` (**“Proxy URL”** / **“Only needed on networks where Telegram is blocked.”**), `DISCORD_BOT_TOKEN` (**“Bot token”** / **“Create an application in the Discord Developer Portal, add a bot, then paste its token.”**), `DISCORD_ALLOWED_USERS` (**“Allowed Discord user IDs”** / **“Recommended. Comma-separated Discord user IDs.”**), `DISCORD_REPLY_TO_MODE` (**“Reply style”** / **“first, all, or off.”**), `DISCORD_ALLOW_ALL_USERS` (**“Allow all Discord users”** / **“Development only. When true, anyone can DM the bot without an allowlist.”**), `DISCORD_HOME_CHANNEL` (**“Home channel ID”** / **“Channel where the bot sends proactive messages (cron output, reminders).”**), `DISCORD_HOME_CHANNEL_NAME` (**“Home channel name”** / **“Display name for the home channel in logs and status output.”**), `BLUEBUBBLES_ALLOW_ALL_USERS` (**“Allow all iMessage users”** / **“When true, skip the BlueBubbles allowlist.”**), `MATTERMOST_ALLOW_ALL_USERS` (**“Allow all Mattermost users”**), `MATTERMOST_HOME_CHANNEL` (**“Home channel”**), `QQ_ALLOW_ALL_USERS` (**“Allow all QQ users”**), `QQBOT_HOME_CHANNEL` (**“QQ home channel”** / **“Default channel or group for cron delivery.”**), `QQBOT_HOME_CHANNEL_NAME` (**“QQ home channel name”**), `SLACK_BOT_TOKEN` (**“Slack bot token”** / **“Use the bot token from OAuth & Permissions after installing your Slack app.”** / **“Paste Slack bot token”**), `SLACK_APP_TOKEN` (**“Slack app token”** / **“Use the app-level token required for Socket Mode.”** / **“Paste Slack app token”**), `SLACK_ALLOWED_USERS` (**“Allowed Slack user IDs”** / **“Recommended. Comma-separated Slack user IDs.”**), `MATTERMOST_URL` (**“Server URL”** / **“https://mattermost.example.com”**), `MATTERMOST_TOKEN` (**“Bot token”**), `MATTERMOST_ALLOWED_USERS` (**“Allowed user IDs”** / **“Recommended. Comma-separated Mattermost user IDs.”**), `MATRIX_HOMESERVER` (**“Homeserver URL”** / **“https://matrix.org”**), `MATRIX_ACCESS_TOKEN` (**“Access token”**), `MATRIX_USER_ID` (**“Bot user ID”** / **“@hermes:example.org”**), `MATRIX_ALLOWED_USERS` (**“Allowed Matrix user IDs”** / **“Recommended. Comma-separated user IDs in @user:server format.”**), `SIGNAL_HTTP_URL` (**“Signal bridge URL”** / **“http://127.0.0.1:8080”** / **“URL of a running signal-cli REST bridge.”**), `SIGNAL_ACCOUNT` (**“Phone number”** / **“The number registered with your signal-cli bridge.”**), `SIGNAL_ALLOWED_USERS` (**“Allowed Signal users”** / **“Recommended. Comma-separated Signal identifiers.”**), `WHATSAPP_ENABLED` (**“Enable WhatsApp bridge”** / **“Set automatically by the toggle below. Leave alone unless you know you need it.”**), `WHATSAPP_MODE` (**“Bridge mode”**), `WHATSAPP_ALLOWED_USERS` (**“Allowed WhatsApp users”** / **“Recommended. Comma-separated phone numbers or WhatsApp IDs.”**).
- **Edge cases / guards:** When a platform declares zero required fields the Required section shows **“This platform does not need a token here. Use the setup guide above, then enable it below.”** (`messaging.noTokenNeeded`). A **“Saved”** badge (`messaging.saved`, primary colour) sits next to the label whenever `field.is_set`.
- **Rebuild notes:** Drive the whole form from a backend-declared field schema (`key`, `required`, `advanced`, `is_password`, `prompt`, `description`, `url`, `is_set`, `redacted_value`) and keep only per-key copy overrides in the client.

### “Get your credentials” intro + setup guide link  `id: desktop-b.messaging-intro`
- **Surface:** Desktop app
- **Where:** Messaging page → detail section **“Get your credentials”** (`messaging.getCredentials`).
- **What it does:** Explains in one or two sentences how to obtain that platform's credentials, and links to the online setup guide.
- **How it works:** `introCopy()` (`apps/desktop/src/app/messaging/index.tsx:838`) prefers `messaging.platformIntro[id]` (empty in `en`), then the hard-coded `PLATFORM_INTRO` map (`messaging/index.tsx:806`), then `platform.description`. `PLATFORM_INTRO` covers 19 ids verbatim: `telegram` (“In Telegram, talk to @BotFather, run /newbot, and copy the token it gives you. Then grab your numeric user ID from @userinfobot.”), `discord`, `slack`, `mattermost`, `matrix`, `signal`, `whatsapp`, `bluebubbles`, `homeassistant`, `email`, `sms`, `dingtalk`, `feishu`, `wecom`, `wecom_callback`, `weixin`, `qqbot`, `api_server`, `webhook`.
- **Inputs / options:** Button **“Open setup guide”** (`messaging.openSetupGuide`) with an external-link icon, rendered only when `platform.docs_url` exists.
- **Outputs / side effects:** Opens the docs URL through `openExternalLink()`.
- **Config / env:** n/a
- **Edge cases / guards:** The click handler calls `preventDefault()` and routes through the validated opener — in a packaged Electron build an empty/relative `href` resolves to the app's own `index.html` path and `shell.openPath` then fails with "file not found"; plugin platforms (Teams, etc.) ship no `docs_url` at all (comment at `messaging/index.tsx:687`).
- **Rebuild notes:** Keep the intro copy on the backend next to the field schema so new platforms need no client change.

### Pending pairing requests  `id: desktop-b.messaging-pairing-pending`
- **Surface:** Desktop app
- **Where:** Messaging page → detail section **“Pending requests ({n})”** (`messaging.pendingRequests`), shown only when someone is waiting.
- **What it does:** Lists users who messaged the bot and are waiting for approval, and lets you let them in with one click.
- **How it works:** Rows come from `getPairing()`'s `pending[]`, grouped by platform via `byPlatform()` (`apps/desktop/src/app/messaging/index.tsx:88`); row identity is `"<platform>:<user_id>"` (`pairingKey`, `messaging/index.tsx:83`) because a user id is only unique within its platform. `handleApprove()` (`messaging/index.tsx:373`) optimistically removes the row, calls `approvePairing(platform, request_id, scopeProfile)`, then re-reads pairing; a failure restores the snapshot so the row never silently disappears.
- **Inputs / options:** Per-row button **“Approve”** (`messaging.approve`) / **“Approving...”** (`messaging.approving`), disabled while busy or when the row carries no `request_id`. Row title is `user_name || user_id`; the description joins the raw `user_id` (only when a name exists) and the waiting time — **“just now”** for under a minute, otherwise **“{n}m ago”** (`messaging.waitingSince`).
- **Outputs / side effects:** Success toast **“{name} approved”** (`messaging.approvedUser`) with message **“They are recognized automatically on their next message.”** (`messaging.approvedHint`).
- **Config / env:** n/a
- **Edge cases / guards:** An HTTP 429 is the backend's brute-force lockout and gets its own message **“Too many failed approvals — this platform is locked out. Try again later.”** (`messaging.pairingLockedOut`); other failures toast **“Failed to approve {name}”** (`messaging.failedApprove`). The section renders nothing when empty — an empty-state card would be permanent chrome on a page that is usually about credentials (comment at `messaging/index.tsx:611`).
- **Rebuild notes:** Approve by `request_id`, not by user id, and rate-limit approvals server-side.

### Approved users + revoke  `id: desktop-b.messaging-pairing-approved`
- **Surface:** Desktop app
- **Where:** Messaging page → detail section **“Approved users ({n})”** (`messaging.approvedUsers`).
- **What it does:** Lists the users already allowed on this platform and lets you revoke their access.
- **How it works:** `handleRevoke()` (`apps/desktop/src/app/messaging/index.tsx:404`) optimistically removes the row, calls `revokePairing(platform, user_id, scopeProfile)`, then refreshes; on failure it restores the snapshot and re-throws so the confirm dialog shows the error inline and stays open.
- **Inputs / options:** Per-row ghost button **“Revoke”** (`messaging.revoke`) with aria-label **“Revoke {name}”** (`messaging.revokeAria`). Confirm dialog: title **“Revoke access”** (`messaging.revokeTitle`), description **“{name} will lose access and stop being recognized on their next message.”** (`messaging.revokeDesc`), buttons **“Cancel”** (`common.cancel`) and **“Revoke”**, busy label **“Revoking...”** (`messaging.revoking`), destructive styling.
- **Outputs / side effects:** Success toast **“{name} revoked”** (`messaging.revokedUser`) whose message is the platform id. Failure toast **“Failed to revoke {name}”** (`messaging.failedRevoke`).
- **Config / env:** n/a
- **Edge cases / guards:** Row description shows the raw `user_id` only when a display name exists.
- **Rebuild notes:** n/a

---

## 6. Profiles panel and profile dialogs

### Profiles panel  `id: desktop-b.profiles-panel`
- **Surface:** Desktop app
- **Where:** Profile switcher → **“Manage profiles…”** (`i18n: profiles.manageProfiles`), route `/profiles`. Panel title **“Profiles”** (`profiles.title`), subtitle **“{n} profiles”** / **“{n} profile”** (`profiles.count`), close aria **“Close profiles”** (`profiles.close`). Component `ProfilesView`, `apps/desktop/src/app/profiles/index.tsx:42`.
- **What it does:** Lists every Hermes profile (an independent environment with its own config, skills and SOUL.md), shows its model/skill count/path, and lets you create, rename, delete and edit each one's SOUL.md.
- **How it works:** `refreshProfiles()` from `store/profile` fills the list; the selection falls back to the `is_default` profile, then the first one. Filtering matches name and model (`profiles/index.tsx:82`). Row glyph colour comes from `resolveProfileColor(profile.name, $profileColors)`; the label from `profileLabel(profile)` (display name for `default`, otherwise the id).
- **Inputs / options:** Search field labelled/placeholdered **“Search profiles...”** (`profiles.search`). Row kebab menu — for the default profile only **“Rename…”** (`profiles.renameMenu`, icon `edit`); for every other profile **“Rename…”** plus **“Delete”** (`common.delete`, icon `trash`, danger). Add button **“New profile”** (`profiles.newProfile`). Refresh hotkey (aria strings **“Refresh profiles”** / **“Refreshing profiles”**, `profiles.refresh` / `profiles.refreshing`).
- **Outputs / side effects:** Selection only; the dialogs own the mutations.
- **Config / env:** Profiles live as directories under the Hermes home (`profile.path` is displayed with `displayPath()`).
- **Edge cases / guards:** Load shows `PageLoader` **“Loading profiles...”** (`profiles.loading`); load failure toasts **“Failed to load profiles”** (`profiles.failedLoad`). Zero profiles shows icon `organization`, **“No profiles yet.”** (`profiles.noProfiles`), description **“Profiles are independent Hermes environments: separate config, skills, and SOUL.md.”** (`profiles.createDesc`) and a **“New profile”** button. No selection shows icon `account` with **“Select a profile to view its details.”** (`profiles.selectPrompt`).
- **Rebuild notes:** Model the profile as a directory + a small manifest; a better version would show per-profile disk usage and last-used time.

### Profile detail (model, skills, path, badges)  `id: desktop-b.profiles-detail`
- **Surface:** Desktop app
- **Where:** Profiles panel → right pane header.
- **What it does:** Shows one profile's display name, default/.env badges, on-disk path and a two-row meta table.
- **How it works:** `ProfileDetail` (`apps/desktop/src/app/profiles/index.tsx:226`). Badges: **“Default”** (`profiles.defaultBadge`, good tone) when `is_default`; a muted pill literally reading **“.env”** when `has_env`. Note the catalog also carries a `profiles.env` key whose English value is the bare word **“env”** (`apps/desktop/src/i18n/en.ts:1913`; also translated, e.g. `ar.ts:1452` **“البيئة”**, `ja.ts:1600` **“env”**) — it is **orphaned**: nothing reads `t.profiles.env`, because `ProfileDetail` hard-codes the literal pill `<PanelPill tone="muted">.env</PanelPill>` at `apps/desktop/src/app/profiles/index.tsx:237`. The web dashboard uses its own separate key `profiles.hasEnv` → “env” (`web/src/i18n/en.ts:330`). Meta rows: **“Model”** (`profiles.modelLabel`) rendering `model` in mono with ` · provider` appended in a dimmer tone, or **“Not set”** (`profiles.notSet`); and **“Skills”** (`profiles.skillsLabel`) with `skill_count`. Path is `displayPath(profile.path)` in mono, truncated with a full-value `title`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### SOUL.md editor  `id: desktop-b.profiles-soul-editor`
- **Surface:** Desktop app
- **Where:** Profiles panel → right pane, section label literally **“SOUL.md”**, description **“The system prompt and persona instructions baked into this profile.”** (`profiles.soulDesc`).
- **What it does:** Loads and edits the profile's `SOUL.md` (its system prompt / persona) in a full code editor.
- **How it works:** `SoulEditor` (`apps/desktop/src/app/profiles/index.tsx:270`) calls `getProfileSoul(name)` on mount/selection change and `updateProfileSoul(name, content)` on save, guarded by a `requestRef` so a late reply for a previously-selected profile is discarded. The editor is the shared `CodeEditor` with `filePath="SOUL.md"`, `framed`, keyed by profile name so switching profiles remounts it. `dirty` is a plain `content !== original` comparison.
- **Inputs / options:** The code editor (its own save keybinding calls `onSave`), and a footer button **“Save SOUL.md”** (`profiles.saveSoul`) / **“Saving...”** (`profiles.saving`) with a `Save` icon, disabled unless dirty and not busy. **“Unsaved changes”** (`profiles.unsavedChanges`) appears in the header while dirty.
- **Outputs / side effects:** Writes `SOUL.md` inside the profile directory; success toast **“SOUL.md saved”** (`profiles.soulSaved`) with the profile name as the message.
- **Config / env:** n/a
- **Edge cases / guards:** Loading shows **“Loading SOUL.md...”** (`profiles.loadingSoul`); errors render inline in a destructive block with the backend message or **“Failed to load SOUL.md”** (`profiles.failedLoadSoul`) / **“Failed to save SOUL.md”** (`profiles.failedSaveSoul`). Catalog also carries the editor placeholder **“Empty SOUL.md — start writing the persona...”** (`profiles.emptySoul`).
- **Rebuild notes:** Treat SOUL.md as a plain file resource with read/write endpoints; better: version it and show a diff against the profile template.

### Create profile dialog  `id: desktop-b.profiles-create`
- **Surface:** Desktop app
- **Where:** Profiles panel / profile rail → **“New profile”**. Dialog title **“New profile”** (`profiles.newProfile`), description **“Profiles are independent Hermes environments: separate config, skills, and SOUL.md.”** (`profiles.createDesc`). Component `apps/desktop/src/app/profiles/create-profile-dialog.tsx:32`.
- **What it does:** Creates a new profile, optionally cloned from an existing one, optionally with a starting SOUL.md.
- **How it works:** `createProfile({name, clone_from})`, then, only if the SOUL textarea is non-blank, `updateProfileSoul(name, soul)` (`create-profile-dialog.tsx:80`). On success it calls `onCreated(name)` (which selects and refreshes), flips the button to the “done” state, and auto-closes after 800 ms.
- **Inputs / options:** **“Name”** (`profiles.nameLabel`) — a `SanitizedInput` that live-slugs input (`slug`), autofocused, placeholder `my-profile`, hint **“Lowercase letters, digits, hyphens, and underscores. Must start with a letter or digit.”** (`profiles.nameHint`). **“Clone from”** (`profiles.cloneFrom`) select whose first item is **“None (blank)”** (`profiles.cloneFromNone`, sentinel value `__none__`) followed by every existing profile name; default selection is `default`; hint **“Copies config, skills, and SOUL.md from the selected source profile.”** (`profiles.cloneFromDesc`). **“SOUL.md”** textarea marked **“optional”** (`profiles.soulOptional`), mono, min-height 7 rem, placeholder **“The system prompt / persona for this profile.\nLeave blank to keep the cloned default.”** or **“…the empty default.”** (`profiles.soulPlaceholder` with `profiles.soulPlaceholderCloned` = **“cloned”** / `profiles.soulPlaceholderEmpty` = **“empty”**). Footer: **“Cancel”** (`common.cancel`, ghost) and a submit button cycling **“Create profile”** (`profiles.createAction`) → **“Creating...”** (`profiles.creating`) → **“Profile created”** (`profiles.created`).
- **Outputs / side effects:** Creates the profile directory (and copies config/skills/SOUL.md when cloning).
- **Config / env:** n/a
- **Edge cases / guards:** Name validity is `^[a-z0-9][a-z0-9_-]{0,63}$` (`PROFILE_NAME_RE`, `create-profile-dialog.tsx:23`); an invalid name sets `aria-invalid`, turns the hint red and, on submit, shows **“Invalid name. {hint}”** (`profiles.invalidName`); an empty name shows **“Name is required.”** (`profiles.nameRequired`). Backend errors surface inline, falling back to **“Failed to create profile”** (`profiles.failedCreate`). The dialog cannot be closed while saving or during the 800 ms “done” window.
- **Rebuild notes:** Validate the name identically on both client and server; keep clone as a server-side copy so a partially-created profile cannot exist.

### Rename profile dialog (and “Name this agent” for default)  `id: desktop-b.profiles-rename`
- **Surface:** Desktop app
- **Where:** Profiles panel / profile rail row menu → **“Rename…”**. Component `apps/desktop/src/app/profiles/rename-profile-dialog.tsx:195`.
- **What it does:** Renames a profile directory (and its wrapper scripts) — or, for the `default` profile, sets a presentation-only display name while the canonical id stays `default`.
- **How it works:** `renameProfile(currentName, trimmed)` (or `renameProfile(currentName, trimmed, scope)` for a profile that lives on another gateway). For non-default local profiles it first calls `retireLocalProfileGateways(currentName)` — a retained renderer socket for the old name would treat the rename's backend teardown as a transient drop, redial, and resurrect the old-name backend whose `ensure_hermes_home()` recreates the very directory the rename just moved (comment at `rename-profile-dialog.tsx:255`). On success it calls `onRenamed(name)` and auto-closes after 800 ms.
- **Inputs / options:** Normal mode — title **“Rename profile”** (`profiles.renameTitle`), description **“Renaming updates the profile directory and any wrapper scripts in ”** + `~/.local/bin` in mono + **“.”** (`profiles.renameDescPrefix` / `profiles.renameDescSuffix`), field **“New name”** (`profiles.newNameLabel`) slug-sanitised with the name hint. Default-profile mode — title **“Name this agent”** (`profiles.displayNameTitle`), description **“Sets a display name shown across the app. The internal profile ID stays "default".”** (`profiles.displayNameDesc`), field **“Display name”** (`profiles.displayNameLabel`) with **no** sanitising (Unicode allowed, `identity`, `rename-profile-dialog.tsx:191`) and no hint. Footer: **“Cancel”** (`common.cancel`) and a submit button cycling **“Rename”** (`profiles.rename`) → **“Renaming...”** (`profiles.renaming`) → **“Profile renamed”** (`profiles.renamed`).
- **Outputs / side effects:** Moves the profile directory, rewrites wrapper scripts in `~/.local/bin`, and (default mode) stores a display name.
- **Config / env:** n/a
- **Edge cases / guards:** Submitting an unchanged name is a silent close. The field starts blank in display-name mode because `default` is an id, not a name (`rename-profile-dialog.tsx:226`). Validation errors as in Create; backend errors fall back to **“Failed to rename profile”** (`profiles.failedRename`). An explicit `scope` (a remote-gateway profile) executes the rename on that gateway and skips the local backend retirement.
- **Rebuild notes:** Always tear down the old backend socket before a rename or delete, or the auto-redial will recreate what you removed.

### Delete profile dialog  `id: desktop-b.profiles-delete`
- **Surface:** Desktop app
- **Where:** Profiles panel / profile rail row menu → **“Delete”**. Title **“Delete profile?”** (`profiles.deleteTitle`). Component `apps/desktop/src/app/profiles/delete-profile-dialog.tsx:335`.
- **What it does:** Permanently deletes a profile and its directory; if the deleted profile was the live one it swaps the app back to `default`.
- **How it works:** A thin wrapper over the shared `ConfirmDialog` so Enter-to-confirm and busy/done/error behaviour are inherited; it is the single choke point for every delete entry point (rail + Profiles view). The confirm handler: captures whether the profile is the active gateway profile (`normalizeProfileKey` comparison against `$activeGatewayProfile`), calls `retireLocalProfileGateways(name)` for local profiles, calls `deleteProfile(name)` (or `deleteProfile(name, scope)` for a remote-gateway profile), calls `dropTilesForProfile(name)` — a leftover session/Bot tile would restore on relaunch and dial the deleted profile's backend, whose `ensure_hermes_home()` re-creates the just-removed directory (`delete-profile-dialog.tsx:396`) — awaits the host's `onDeleted` refresh, and only then calls `selectProfile('default')` + `setActiveProfile('default')` so its reset is the last write.
- **Inputs / options:** Description assembles **“This will delete ”** + the bold name + (optionally) **“ on {gateway}”** (`profiles.fleet.deleteOn`) + **“ and remove its ”** + the path in mono + **“ directory. This cannot be undone.”** (`profiles.deleteDescPrefix` / `deleteDescMid` / `deleteDescSuffix`). Buttons **“Delete”** (`common.delete`, destructive) with busy label **“Deleting...”** (`profiles.deleting`) and done label **“Profile deleted”** (`profiles.deleted`).
- **Outputs / side effects:** Removes the profile directory and every persisted tile that belonged to it.
- **Config / env:** n/a
- **Edge cases / guards:** The `gatewayLabel` prop is required whenever the profile lives on a gateway other than the foreground one so “two `omer`s must never read the same” (comment at `delete-profile-dialog.tsx:344`). Failures fall back to **“Failed to delete profile”** (`profiles.failedDelete`).
- **Rebuild notes:** Sequence matters: retire sockets → delete → drop tiles → refresh → reset the active profile.

---

## 7. Capabilities page (Skills / Tools / MCP)

### Capabilities page shell  `id: desktop-b.skills-page`
- **Surface:** Desktop app
- **Where:** Left sidebar nav → **“Capabilities”** (`i18n: sidebar.nav.skills`), route `/skills`. Component `SkillsView`, `apps/desktop/src/app/skills/index.tsx:206`.
- **What it does:** One page with three tabs — installed Skills (plus an embedded Skills Hub browser), Tools (toolsets), and MCP servers — all editing the same selected profile.
- **How it works:** Tabs are the tuple `SKILLS_MODES = ['skills','toolsets','mcp']` (`skills/index.tsx:70`), persisted in the route query `?tab=` via `useRouteEnumParam` (a legacy `?tab=hub` link falls back to `skills`). Skills and toolsets live in React-Query under keys `['skills-list', scopeKey]` and `['toolsets-list', scopeKey]` with `staleTime: 0`, so tab switches paint cached lists instantly and only fire a deduped background refetch; a profile swap invalidates the prefix globally. `$gateway` is subscribed through `useStoreSelector` gated on `mode === 'mcp'` so Skills/Tools do not re-render on gateway connect/disconnect (`skills/index.tsx:220`). In embedded mode (plugin dialogs such as Bot Mode's Advanced section) the tab lives in local React state instead of the URL, and `fixedProfile` / `fixedConnection` pin the whole view to one agent on one gateway; `SkillsView.supportsFixedConnection = true` is a static, probe-able feature flag so older builds cannot be handed a prop they would silently misroute (`skills/index.tsx:957`).
- **Inputs / options:** Three tabs with counts: **“Skills”** (`skills.tabSkills`, meta = number of skills), **“Tools”** (`skills.tabToolsets`, meta = number of *desktop-visible* toolsets), **“MCP”** (`skills.tabMcp`, no meta). Search field placeholder **“Search skills...”** (`skills.searchSkills`) or **“Search tools...”** (`skills.searchToolsets`); hidden entirely on the MCP tab. Refresh hotkey (`skills.refresh` = **“Refresh skills”**, `skills.refreshing` = **“Refreshing skills”**).
- **Outputs / side effects:** Invalidates the skills/toolsets query keys and `invalidateSlashCompletions()` on refresh.
- **Config / env:** Everything is written per profile scope (see the scope selector entry).
- **Edge cases / guards:** When both lists fail and neither is cached, a full-bleed error state shows icon `error`, **“Skills failed to load”** (`skills.skillsLoadFailed`), the error message and a **“Refresh skills”** button. Otherwise loading shows **“Loading capabilities...”** (`skills.loading`). Zero rows shows a full-bleed empty state (both columns, not a cramped left-rail note) with **“No skills found”** / **“No tools found”** (`skills.emptyNoneFound(noun)`), and either **“Nothing matches “{query}”.”** (`skills.emptyNothingMatches`) or **“No {noun} available yet.”** (`skills.emptyNoneAvailable`). The catalogue also carries the unused pair **“No toolsets found”** / **“Try a broader search query.”** (`skills.noToolsetsTitle` / `noToolsetsDesc`) and **“No skills found”** / **“Try a broader search or different category.”** (`skills.noSkillsTitle` / `noSkillsDesc`).
- **Rebuild notes:** Keep list caches keyed by (profile, connection) and invalidate by prefix; keep the expensive analytics query off the critical path.

### Capabilities profile-scope selector (“Configuring:”)  `id: desktop-b.skills-scope-selector`
- **Surface:** Desktop app
- **Where:** Capabilities page → strip above every tab, label **“Configuring:”** (`i18n: skills.configuringProfile`).
- **What it does:** Chooses which profile — on which registered gateway — the Skills/Tools/MCP settings on this page are written to, without switching the whole app.
- **How it works:** `apps/desktop/src/app/skills/index.tsx:749`. Options come from two paths: on a multi-connection desktop (more than one entry in `window.hermesDesktop.connections.list()`) the union agent roster `window.hermesDesktop.getAgentRoster()` yields one option per `(connectionId, profile)` pair, labelled `"{profile} — {connectionLabel}"` and `"{profile} — {connectionLabel} (current)"` for the active connection, with value `"<connectionId>::<profile>"`; otherwise the legacy per-profile list from `getProfiles()` labelled `Hermes (default)` for the default profile and the bare name otherwise (`skills/index.tsx:713`). `changeScope()` (`skills/index.tsx:684`) decodes both shapes — a `::` pick becomes `{connectionId, profile}` (so `local::x` pins the local pool even while a remote gateway is active) and a bare pick stays a string.
- **Inputs / options:** One `Select` (28 px tall, 14 rem wide). Hidden when fewer than two options exist, or when `fixedProfile` pins the view.
- **Outputs / side effects:** Every subsequent read/write on the page (skills list, toolsets list, MCP config, hub installs, analytics) routes to that profile's backend. Changing scope resets: the analytics epoch and `toolCalls` (to `null`), the open skill editor and its draft, and the pending archive target — because all of those belonged to the previous scope.
- **Config / env:** React-Query keys `['capabilities-profiles']`, `['capabilities-connections-registry']`, `['capabilities-agent-roster']`, each `staleTime: 60_000`.
- **Edge cases / guards:** `crossBackendScope` is computed by comparing the pinned connection to `activeGatewayConnectionId()`; when they differ, the MCP tab is handed `gateway={null}` so its live `reload.mcp` RPC — which rides the *active* gateway socket — cannot hot-reload the wrong machine (config edits still apply on that backend's next session, `skills/index.tsx:830`). An app-wide profile switch also clears the scope override (`useOnProfileSwitch`, `skills/index.tsx:381`).
- **Rebuild notes:** Route every capability mutation through an explicit `(connection, profile)` scope object; never assume the active socket.

### Skills tab — installed skills list  `id: desktop-b.skills-list`
- **Surface:** Desktop app
- **Where:** Capabilities page → **“Skills”** tab, left column.
- **What it does:** Lists every installed skill with its category, provenance badge, usage count and an on/off switch.
- **How it works:** `filteredSkills()` (`apps/desktop/src/app/skills/index.tsx:135`) filters on name, description and category (via `includesQuery`/`normalize`) and sorts by usage descending (or ascending when the sort is flipped), tie-broken alphabetically. Row subtitle is the prettified category plus a badge: **“learned”** for `provenance === 'agent'` and **“hub”** for `provenance === 'hub'` (`skills/index.tsx:116`); bundled skills get no badge. The `meta` column shows `×{compactNumber(usage)}` when usage > 0.
- **Inputs / options:** Per-row toggle switch (aria/label = the skill name); click a row to select it. List strip: a sort button reading **“↓ Most used”** (`skills.sortMostUsedDesc`) or **“↑ Least used”** (`skills.sortLeastUsedAsc`) which flips the persisted atom `$skillsSortDesc` (`apps/desktop/src/app/skills/store.ts:254`, localStorage key `hermes.desktop.capabilities.skillsSortDesc`); a menu labelled **“Skills”** containing the master switch **“All”** (`skills.all`) and the item **“Disable unused”** (`skills.disableUnused`).
- **Outputs / side effects:** A single toggle calls `setSkillEnabled(name, enabled, scopeProfile)` optimistically and silently on success (a toast per flip would spam rapid customisation); it then calls `invalidateSlashCompletions()` because a disabled skill loses its `/name` command. A failure reverts the row and toasts **“Failed to update {name}”** (`skills.failedToUpdate`).
- **Config / env:** Writes the profile's enabled-skills config.
- **Edge cases / guards:** Bulk actions operate on the **whole** tab, never the search-filtered view — “a tab-wide control that silently scoped to the current query would be a lie” (comment at `skills/index.tsx:398`). Catalog also carries the per-toggle toasts **“Skill enabled”** / **“Skill disabled”** (`skills.skillEnabled` / `skillDisabled`) and **“{name} applies to new sessions.”** (`skills.appliesToNewSessions`).
- **Rebuild notes:** Optimistic toggle + revert-on-error is the right shape; keep the slash-command cache invalidation coupled to it.

### Bulk enable/disable (“All” master switch)  `id: desktop-b.skills-bulk-toggle`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills or Tools tab → list-strip menu → the toggle row **“All”** (`i18n: skills.all`).
- **What it does:** Turns every skill (or every visible toolset) on or off in one action.
- **How it works:** `bulkApply()` (`apps/desktop/src/app/skills/index.tsx:508`) iterates **sequentially** — each toggle is a config read-modify-write on the backend and parallel calls would race the disabled-list save — updating the query cache after each success. The master switch is checked only when every row is already enabled (`allSkillsEnabled` / `allToolsetsEnabled`, `skills/index.tsx:567`).
- **Inputs / options:** One switch; disabled while `bulkBusy`.
- **Outputs / side effects:** N `setSkillEnabled` / `setToolsetEnabled` calls, then a success toast **“Updated {n} item(s) for new sessions.”** (`skills.bulkUpdated`), and always `invalidateSlashCompletions()` in the `finally`. Failure toasts `skills.failedToUpdate` with the tab label.
- **Config / env:** n/a
- **Edge cases / guards:** A no-op selection (nothing to change) returns immediately; the catalog carries **“Nothing to change.”** (`skills.bulkNoChange`), plus the unused labels **“Enable all”** / **“Disable all”** (`skills.enableAll` / `disableAll`).
- **Rebuild notes:** Offer a single batch endpoint instead of N sequential writes.

### “Disable unused”  `id: desktop-b.skills-disable-unused`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills tab → list-strip menu item **“Disable unused”** (`i18n: skills.disableUnused`).
- **What it does:** Disables every currently-enabled skill that has zero recorded usage — the pruning move for a 100+ skill install.
- **How it works:** `disableUnused()` (`apps/desktop/src/app/skills/index.tsx:544`) filters `skill.enabled && usageOf(skill) === 0` and runs them through `bulkApply(..., false)`. “Never used” means zero recorded activity, i.e. `skill.usage` absent or 0 (`usageOf`, `skills/index.tsx:110`).
- **Inputs / options:** One menu item; disabled while a bulk action is running.
- **Outputs / side effects:** Same as the bulk toggle.
- **Config / env:** n/a
- **Edge cases / guards:** Usage counts come from the backend's skill list, not the 365-day tool analytics.
- **Rebuild notes:** n/a

### Skill detail pane  `id: desktop-b.skills-detail`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills tab, right column. Footer caption **“Changes apply to new sessions.”** (`i18n: skills.changesApplyNewSessions`).
- **What it does:** Shows one skill's category, provenance, parsed frontmatter and the full `SKILL.md` body, and (for learned skills) offers Edit and Archive.
- **How it works:** `SkillDetail` (`apps/desktop/src/app/skills/index.tsx:1028`) fetches `getSkillContent(name, profile)` under key `['skill-content', name, scopeKey]` with `staleTime: 60_000`, then splits the file with `parseFrontmatter()` (`skills/index.tsx:997`) — the YAML block between the leading `---` fences, flattened to top-level `key: value` rows (nested blocks keep their raw indented text, two leading spaces stripped). Frontmatter renders as a bordered key/value grid with a 6 rem key column; the body renders in a mono `<pre>` marked `data-selectable-text="true"`.
- **Inputs / options:** Header pills — the prettified category, plus a provenance pill reading **“Learned”** (`skills.provenance.agent`, good tone) or **“Hub”** (`skills.provenance.hub`, muted); `bundled` (**“Built-in”**, `skills.provenance.bundled`) is deliberately not shown as a pill. Buttons, only when `provenance === 'agent'`: **“Edit”** (`skills.edit`) and **“Archive”** (`skills.archive`, destructive-coloured).
- **Outputs / side effects:** Read-only until Edit/Archive is used.
- **Config / env:** n/a
- **Edge cases / guards:** A missing description falls back to **“No description.”** (`skills.noDescription`), which is also the fallback for an empty body. While the content loads, a `CountSkeleton` is shown. The parse is display-only and is never fed back to the backend (comment at `skills/index.tsx:993`).
- **Rebuild notes:** Fetch the full file lazily per selection; a better version would render the Markdown body instead of a `<pre>`.

### Skill editor (`<name>/SKILL.md`)  `id: desktop-b.skills-editor`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills tab → **“Edit”** on a learned skill. Opens a third `DetailPane` titled `"{name}/SKILL.md"`.
- **What it does:** Edits a learned skill's `SKILL.md` in place through the same `/api/learning/node` endpoints the memory graph uses.
- **How it works:** `openSkillEditor()` calls `getLearningNode(name, scopeProfile)`; `saveSkillEdit()` calls `editLearningNode(name, draft, scopeProfile)` (`apps/desktop/src/app/skills/index.tsx:614,633`). Both are guarded by `skillEditorEpoch` so a profile or scope switch cannot let an in-flight fetch reopen the editor with the previous profile's content, and cannot let a save land on the wrong backend (`skills/index.tsx:600`). The editor itself is the shared `CodeEditor` with `filePath="SKILL.md"`.
- **Inputs / options:** Editor body (its own save/cancel keybindings), a header button **“Save”** (`common.save`) / **“Saving...”** (`common.saving`), and the pane's close control.
- **Outputs / side effects:** Writes the skill file; success toast **“Skill updated”** (`skills.skillUpdated`) with message **“{name} applies to new sessions.”** (`skills.appliesToNewSessions`), then refreshes the capability lists.
- **Config / env:** n/a
- **Edge cases / guards:** Only `provenance === 'agent'` skills are editable — bundled and hub skills are managed by their sources (comment at `skills/index.tsx:1042`).
- **Rebuild notes:** n/a

### Archive skill confirmation  `id: desktop-b.skills-archive`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills tab → **“Archive”**; also from the Memory Graph node menu. Dialog title `"Archive {skillName}?"`, description **“The skill is archived and can be restored with `hermes curator restore`.”** (`ARCHIVE_SKILL_DESCRIPTION`, `apps/desktop/src/app/learning/archive-skill-confirm-dialog.tsx:261`).
- **What it does:** Archives (soft-deletes) a learned skill, removing it from the list while keeping it restorable from the CLI.
- **How it works:** `ArchiveSkillConfirmDialog` (`archive-skill-confirm-dialog.tsx:298`) wraps the shared `ConfirmDialog` with `dismissOnConfirm`. On confirm it calls `onApply()`, which optimistically removes the row from the query cache, invalidates slash completions, and closes the editor if it was open on that skill — and returns a rollback closure. `archiveLearningSkill(id, profile)` (`:267`) calls `deleteLearningNode(id, profile)` and throws `res.message || 'Archive failed'` when `res.ok` is false. `fireOptimistic()` (`:276`) runs the promise; on failure it rolls back and reports.
- **Inputs / options:** Buttons **“Archive”** (hard-coded `confirmLabel`) and the shared cancel; destructive styling.
- **Outputs / side effects:** Success toast titled **“Skill archived”** (`skills.skillArchivedTitle`) with message **“Restorable via hermes curator restore.”** (`skills.skillArchivedMessage`). Failure toasts with the skill name as the title.
- **Config / env:** Scoped by the Capabilities profile selector.
- **Edge cases / guards:** The dialog dismisses immediately and the work happens in the background, so a failure surfaces as a toast plus a restored row rather than a stuck dialog.
- **Rebuild notes:** Keep archive reversible and say where it went — the message names the exact restore command.

### Tools tab — toolset list  `id: desktop-b.skills-toolsets-list`
- **Surface:** Desktop app
- **Where:** Capabilities page → **“Tools”** tab, left column.
- **What it does:** Lists every desktop-visible toolset with its description, per-toolset call count (or tool count) and an on/off switch.
- **How it works:** `filteredToolsets()` (`apps/desktop/src/app/skills/index.tsx:150`) first drops anything `isDesktopToolsetVisible()` rejects, then matches the query against the toolset name, display label, description and every tool name; sorting is by summed call count descending (flippable) then alphabetically by display label. `toolsetCalls()` sums per-tool counts from the analytics map (`skills/index.tsx:145`).
- **Inputs / options:** Per-row switch whose aria label is **“Turn {label} toolset on|off”** (`skills.toggleToolset`); click a row to select. List strip: the same sort button, driven by `$toolsetsSortDesc` (`hermes.desktop.capabilities.toolsetsSortDesc`), and a menu labelled **“Tools”** with only the **“All”** master switch.
- **Outputs / side effects:** `setToolsetEnabled(name, enabled, scopeProfile)`, optimistic on both `enabled` and `available`, reverting and toasting **“Failed to update {label}”** on failure. Catalog also carries **“Toolset enabled”** / **“Toolset disabled”** (`skills.toolsetEnabled` / `toolsetDisabled`) and **“{enabled}/{total} toolsets enabled”** (`skills.toolsetsEnabled`).
- **Config / env:** Analytics come from `getUsageAnalytics(365, scopeProfile)` — a 365-day message scan — cached module-wide for 10 minutes per scope key (`TOOL_CALLS_TTL_MS`, `skills/index.tsx:87`) and fetched **lazily** the first time the Tools tab is shown, never on Skills or MCP, so it cannot starve the MCP tab's config load (comment at `skills/index.tsx:360`).
- **Edge cases / guards:** While the analytics are still loading, each row's meta shows a `CountSkeleton`; once loaded, `×{count}` for used toolsets and `{n} tools` for unused ones. An explicit refresh bypasses the TTL, but only when the badges are already on screen. An app-profile switch bumps `toolCallsEpoch` and resets `toolCalls` to `null` so the next Tools view reloads for the new profile. Load failure: the toolset query (`useQuery({queryKey: [...TOOLSETS_QUERY_KEY, scopeKey], queryFn: () => getToolsets(scopeProfile), staleTime: 0})`, `skills/index.tsx:311-315`) sets `toolsetsFailed`, and `(skillsFailed || toolsetsFailed) && (!skills || !toolsets)` renders a `PanelEmpty` with the `error` icon, the raw error message as its description, and a **“Refresh”** button (`skills.refresh`) wired to `refreshCapabilities()` (`skills/index.tsx:799-810`). That panel's title is always **“Skills failed to load”** (`i18n: skills.skillsLoadFailed`): its sibling string **“Toolsets failed to refresh”** (`i18n: skills.toolsetsRefreshFailed`, declared at `apps/desktop/src/i18n/en.ts:1290`) is present in every locale catalog but has **no render site in v2026.8.31** — a toolset-only failure therefore shows the skills wording. Worth quoting verbatim so a checker can find it, and worth fixing by branching the title on `toolsetsFailed && !skillsFailed`.
- **Rebuild notes:** Move the 365-day scan server-side into a maintained counter; the client should never pay for it on tab entry.

### Toolset detail pane  `id: desktop-b.skills-toolset-detail`
- **Surface:** Desktop app
- **Where:** Capabilities page → Tools tab, right column. Footer **“Changes apply to new sessions.”** (`skills.changesApplyNewSessions`).
- **What it does:** Shows a toolset's description, its individual tools as chips with call counts, and any toolset-specific configuration panel.
- **How it works:** `ToolsetDetail` (`apps/desktop/src/app/skills/index.tsx:1104`). Header pill **“Needs keys”** (`skills.needsKeys`, warn tone) appears only when `configured` is false — “Configured” as a resting state is noise (comment at `skills/index.tsx:1123`); the string **“Configured”** (`skills.configured`) exists but is not rendered here. Each tool renders as a `ToolChip` with `×{count}` appended when the analytics have a non-zero count. Then, by toolset name: `computer_use` → `ComputerUsePanel`; `browser` → `BrowserRealProfilePanel` (rendered *above* the provider matrix because its consent toggle was previously only reachable through the generic config editor); `terminal` → `TerminalBackendPanel`. Finally the generic `ToolsetConfigPanel`, keyed by `"{toolset}:{scopeKey}"`.
- **Inputs / options:** Everything inside the sub-panels (documented in the `desktop-settings` shard). For the `vision` toolset only: the hint **“Vision uses your auxiliary model configuration — the image-capable model is picked there, not per-provider here.”** (`skills.visionModelHint`) and a button **“Choose vision model in Settings → Models”** (`skills.visionModelLink`) that navigates to `${SETTINGS_ROUTE}?tab=config:model&aux=vision`.
- **Outputs / side effects:** Sub-panels write toolset config; `onConfiguredChange` invalidates the toolsets query so the “Needs keys” pill updates.
- **Config / env:** Toolset config keys — see the config shards.
- **Edge cases / guards:** Missing description falls back to **“No description.”** (`skills.noDescription`).
- **Rebuild notes:** Keep the special-case panels declarative (a `name → Panel` map) rather than a chain of conditionals.

### Embedded Skills Hub picker  `id: desktop-b.skills-hub-picker`
- **Surface:** Desktop app
- **Where:** Capabilities page → Skills tab, the resizable section below the installed list. Header label **“Skills Hub”** (`i18n: skills.hub.pickerTitle`), footer hint **“Hit "+ Add to this Agent" on any skill — it installs and appears in the list above.”** (`skills.hub.pickerHint`). Component `apps/desktop/src/app/skills/embedded-hub-picker.tsx:65`.
- **What it does:** Embeds the live Skills Hub docs page as an iframe where every card has a one-click install button, wired to the local install pipeline.
- **How it works:** The iframe loads `https://hermes-agent.nousresearch.com/docs/skills?embed=picker` (`HUB_ORIGIN` / `HUB_PICKER_URL`, `embedded-hub-picker.tsx:21`) with `sandbox="allow-scripts allow-same-origin"`. The `?embed=picker` mode hides the docs chrome and adds a **“+ Add to this Agent”** button per card, which `postMessage`s `{type:'hermes-skill-pick', name, identifier, installCmd, source}` to the parent. The listener (`:130`) checks `event.origin === HUB_ORIGIN`, refuses a pick already present in `installedNames` (the **unfiltered** installed set, so search cannot make a skill look absent), and otherwise calls `installHubSkill(target, profile)` from `store/hub-actions`. The frame is rendered oversized and scaled down (`width/height: 133.34%`, `transform: scale(0.75)`) so the cross-origin page starts zoomed out. The component is `memo`ised so the iframe never sits in the parent's keystroke/re-render path, and it is mounted **outside** the tab ternary: it lazy-mounts the first time the Skills tab is shown and then stays mounted but `display:none` across Tools/MCP so the docs site never reloads on a tab bounce (`skills/index.tsx:927`).
- **Inputs / options:** Header buttons **“Update installed”** (`skills.hub.updateAll`) / **“Updating...”** (`skills.hub.updating`, with a spinner) → `updateHubSkills(profile)`; and **“Hide the hub browser”** (`skills.hub.pickerHide`) / **“Browse the full hub”** (`skills.hub.pickerBrowse`) which writes the pane height override to `0` or `undefined`. A top-edge drag sash resizes the section (drag up grows the hub); double-clicking it resets to the default height.
- **Outputs / side effects:** Installs land in the scoped profile through the standard hub action pipeline (background action + tailed log + Skills-list invalidation). Toasts: **“Installing {name}...”** (`skills.hub.installStarted`) with message **“Action log”** (`skills.hub.actionLog`); **“"{name}" is already installed”** (`skills.hub.alreadyInstalled`); **“Updating installed skills...”** (`skills.hub.updateStarted`); failures **“Skill action failed”** (`skills.hub.actionFailed`).
- **Config / env:** Height persists through the shared pane store under pane id `capabilities-hub`; defaults `HUB_DEFAULT_PX = 380`, minimum `HUB_MIN_PX = 120`, maximum `min(75 % of viewport height, column height − 176 px)` where `HUB_LIST_RESERVED_PX = 176` guarantees the installed list keeps real height; a stored height ≤ `HUB_COLLAPSED_PX = 4` reads as collapsed (`embedded-hub-picker.tsx:27-37`).
- **Edge cases / guards:** During a sash drag the iframe gets `pointer-events: none` or it would swallow the `pointermove` stream. The message listener is only installed while the hub is open. No scope key is used in the component key — remounting on a scope change would reload the entire site for no data benefit; the scope rides the `profile` prop into each install call (comment at `skills/index.tsx:922`).
- **Rebuild notes:** An origin-checked `postMessage` bridge into a first-party web page is a cheap way to get a full catalog UI; make sure the host validates the pick against the installed set and routes installs through its own audited pipeline.

### Skills Hub strings (standalone hub browser vocabulary)  `id: desktop-b.skills-hub-strings`
- **Surface:** Desktop app
- **Where:** The `skills.hub.*` i18n namespace, used by the hub picker and the hub browsing/scan flows.
- **What it does:** Provides every label the hub browser can show, including the security-scan verdicts and install policy.
- **How it works:** Catalog at `apps/desktop/src/i18n/en.ts:1322`.
- **Inputs / options:** Verbatim strings — search placeholder **“Search the skill hub”** (`searchPlaceholder`), **“Search”** (`search`), **“Searching...”** (`searching`), **“Connecting to skill hubs...”** (`connectingHubs`), **“Connected hubs:”** (`connectedHubs`), **“Featured skills”** (`featured`), landing hint **“Search the hub to browse installable skills from the official index, GitHub, and community sources.”** (`landingHint`), **“No matching skills found in the hub.”** (`noResults`), **“{n} result(s) in {ms}ms”** (`resultCount`), **“Timed out: {sources}”** (`timedOut`), **“Installed”**, **“Install”**, **“Installing...”**, **“Uninstall”**, **“Uninstalling...”**, **“Update installed”**, **“Updating...”**, **“Preview”**, **“Scan”**, **“Scanning...”**, **“Close”**, **“Files”**, **“This skill has no SKILL.md preview.”** (`noReadme`), trust badges **“builtin”** / **“trusted”** / **“community”** (`trust.*`), scan verdicts **“Safe”** / **“Caution”** / **“Dangerous”** (`verdictSafe|verdictCaution|verdictDangerous`), policies **“Install allowed”** / **“Review before installing”** / **“Install blocked by policy”** (`policyAllow|policyAsk|policyBlock`), **“{n} finding(s)”** (`findings`), **“No security findings.”** (`noFindings`), **“Installing {name}...”**, **“Uninstalling {name}...”**, **“Updating installed skills...”**, **“Skill action failed”**, **“Action log”**, **“"{name}" is already installed”**, **“Skills Hub”**, **“Browse the full hub”**, **“Hide the hub browser”**, plus the failures **“Skill hub failed to load”** (`loadFailed`), **“Skill preview failed”** (`previewFailed`), **“Security scan failed”** (`scanFailed`), **“Hub search failed”** (`searchFailed`).
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** In v2026.8.31 the hub is surfaced through the embedded iframe picker; the standalone browser strings remain in the catalog and are reused by the hub action pipeline and by other surfaces (web dashboard / CLI).
- **Rebuild notes:** Ship the trust tier and scan verdict with every hub result so the client can apply an install policy without a second round-trip.

---

## 8. Capabilities → MCP tab

### MCP tab  `id: desktop-b.mcp-tab`
- **Surface:** Desktop app
- **Where:** Capabilities page → **“MCP”** tab (`i18n: skills.tabMcp`). Component `McpTab`, `apps/desktop/src/app/skills/mcp-tab.tsx:350`.
- **What it does:** A two-column MCP manager: on the left the configured server fleet plus the Nous-approved catalog (or one server's config when the editor cursor is inside its block); on the right a live `mcp.json` editor with the MCP log pane pinned beneath it.
- **How it works:** The editor always speaks the ecosystem's `mcp.json` document format — server names are the JSON keys and the transport is inferred from `command` vs `url` — so any README's "add this to your mcp.json" snippet pastes verbatim, while storage stays the `config.yaml` `mcp_servers` map (CLI/TUI untouched) (comment at `mcp-tab.tsx:56`). Config comes from the shared `useHermesConfigRecord(profile)` cache and mutations write through `hermesConfigCacheWriter(profile)` so other settings surfaces see them. Selection *is* the editor cursor: `scanServerBlocks()` (`mcp-tab.tsx:235`) is a tolerant character walker (deliberately not `JSON.parse`, so it works mid-edit) that maps each server key+object to a character range; whichever block contains the cursor is the configured server on the left, and the cursor outside every block shows the list. Server order is document order, never alphabetical (`mcp-tab.tsx:432`). Every fetch/save/probe cache is keyed by the scoped profile.
- **Inputs / options:** Everything in the entries below — the fleet list, the `+ New server` button, the Import popover, the catalog rows, the JSON editor, the log pane's `stdio`/`agent` tabs.
- **Outputs / side effects:** Writes `mcp_servers` in the profile's config; probes spawn/contact servers; OAuth opens the system browser.
- **Config / env:** `mcp_servers.<name>` (the runtime gate is `enabled: false`, the same flag `hermes mcp` and the agent's MCP loader read, `mcp-tab.tsx:88`).
- **Edge cases / guards:** A failed first load renders an `ErrorBanner` with the error message and a **“Reload MCP”** (`settings.mcp.reload`) retry button; **“MCP config failed to load”** (`settings.mcp.failedLoad`) is the fallback text. Before config exists, a `PageLoader` labelled **“Loading MCP servers...”** (`settings.mcp.loading`). `profilePending` is true from a profile switch until the config query resettles, and blocks every mutation so profile A's server list cannot be written into B (`mcp-tab.tsx:377`). A deep link `?server=<name>` focuses that server's block once it exists (`useDeepLinkHighlight`, `mcp-tab.tsx:569`).
- **Rebuild notes:** Treating the raw document as the source of truth and deriving selection from the cursor is what makes paste-from-README work; keep a tolerant scanner rather than a strict parser.

### MCP server row  `id: desktop-b.mcp-row`
- **Surface:** Desktop app
- **Where:** MCP tab → left column, section header **“Servers”** (`i18n: settings.mcp.tabServers`).
- **What it does:** One row per configured server with an avatar + status dot, its name, a one-line status/capability summary, refresh and delete icons, and an enable switch.
- **How it works:** Status is computed by `statusOf()` (`apps/desktop/src/app/skills/mcp-tab.tsx:134`): `enabled === false` → `off`; probing → `probing`; no probe yet → `unknown`; probe ok → `ok`; otherwise `needs-auth` when the error matches `NEEDS_AUTH_RE`, else `error`. Dot colours from `STATUS_DOT` (`mcp-tab.tsx:152`): ok emerald-500, error red-500, needs-auth amber-500, probing a pulsing `foreground/40`, off/unknown `foreground/20`. The status line (`statusLine`, `mcp-tab.tsx:194`) renders **“Connecting…”** (`statusConnecting`), **“Needs authentication”** (`statusNeedsAuth`), **“Error”** (`statusError`), **“Off”** (`statusOff`), or — when ok — `capabilitySummary()` (`mcp-tab.tsx:168`), e.g. **“12 tools enabled”** or **“25 tools, 1 prompts, 103 resources enabled”** (`settings.mcp.capabilitySummary`), optionally extended with **“~4.2k tok/call”** (`settings.mcp.costTokens`) and **“3 uses/30d”** (`settings.mcp.usage30d`). The tool count reflects the per-tool include/exclude filter, not the raw discovered count.
- **Inputs / options:** Click the row → focus that server's block in the editor (which flips the left column to its config). Refresh icon, tooltip/aria **“Reload MCP”** (`settings.mcp.reload`) → re-probe. Trash icon, tooltip/aria **“Remove”** (`settings.mcp.remove`) → delete the server. Enable switch, aria/title = the server name.
- **Outputs / side effects:** Probe results are cached per `(name, config fingerprint, profile)` with a TTL; the toggle persists `enabled` and toasts **“{name} enabled — applies to new sessions.”** / **“{name} disabled — applies to new sessions.”** (`settings.mcp.serverEnabled` / `serverDisabled`); a failure toasts **“Failed to turn {name} on|off”** (`settings.mcp.toggleFailed`). Delete failures toast **“Remove failed”** (`settings.mcp.removeFailed`).
- **Config / env:** 30-day usage counts come from `getUsageAnalytics(30, scopeProfile)`, cached module-wide for 10 minutes per scope (`MCP_USAGE_TTL_MS`, `mcp-tab.tsx:110`); a failed analytics fetch caches nothing and the overlay simply omits usage — never an error UI.
- **Edge cases / guards:** A row shows the **“unused”** pill (`settings.mcp.unusedPill`) when it is enabled, connected, has a non-zero token estimate and zero 30-day uses (`mcp-tab.tsx:1105`). The switch reflects the configured flag only — full-strength on, dimmed off — so “is this on?” reads instantly from config and is never gated on a probe that can take seconds while an stdio server spawns `npx`; connectivity is the dot's job (comment at `mcp-tab.tsx:1354`). Probes are epoch-guarded so a slow profile-A probe cannot paint into profile B.
- **Rebuild notes:** Separate "configured on" from "currently connected" in the UI; probe lazily with a fingerprinted cache so revisiting the page does not respawn the whole fleet.

### MCP server config pane  `id: desktop-b.mcp-server-config`
- **Surface:** Desktop app
- **Where:** MCP tab → left column when the editor cursor sits inside a server block. Component `ServerConfig`, `apps/desktop/src/app/skills/mcp-tab.tsx:1201`.
- **What it does:** Shows one server's identity, endpoint/command, capability summary, catalog description, an authenticate button when applicable, and clickable chips for every discovered tool.
- **How it works:** Header shows a back button (aria/tooltip **“All servers”**, `settings.mcp.allServers`, chevron-left) that resets the cursor to 0, the status avatar, the prettified name, and the endpoint line — `entry.url` for HTTP servers or `command + args.join(' ')` for stdio. Geometry is cloned from `McpRow` (`mt-3` on the h-5 controls, `mt-2.5` on the size-6 avatar, `mt-3.5` on the h-4 switch) so nothing jumps when flipping list ⇄ config. `descriptionFor()` (`mcp-tab.tsx:455`) enriches the pane with the catalog description matched by name, url or command.
- **Inputs / options:** Back button; refresh + delete icons and the enable switch (only for a *saved* server); **“Authenticate”** (`settings.mcp.authenticate`) / **“Waiting for browser…”** (`settings.mcp.waitingForBrowser`) button when the server is OAuth-shaped; one clickable chip per discovered tool, whose title is **“Enable {tool}”** / **“Disable {tool}”** (`settings.mcp.enableTool` / `disableTool`) — excluded tools render struck-through at 70 % opacity and are `aria-pressed="false"`.
- **Outputs / side effects:** Clicking a tool chip writes the per-server include/exclude filter into the config. The probe always lists every tool regardless of the filter.
- **Config / env:** `mcp_servers.<name>` (`url` | `command` + `args`, `headers`, `auth`, `enabled`, tool filter).
- **Edge cases / guards:** OAuth is only offered to OAuth-shaped servers (`mcp-tab.tsx:1240`): a server with `headers` uses API-key/bearer auth, where a 401 means a bad key — routing it through the browser flow would wrongly rewrite its config to `auth: oauth`; so an explicit `auth: oauth` may re-auth on `needs-auth` **or** `error`, an auth-less HTTP server may try OAuth only on `needs-auth`, and header servers never do. An unsaved (freshly pasted) block shows **“Unsaved — save mcp.json to connect.”** (`settings.mcp.unsavedConnect`) and its tool chips are disabled. While probing, a `PageLoader`. There is deliberately **no** inline error dump — the status line already says “Error”/“Needs authentication” and the real failure lands in the log pane (comment at `mcp-tab.tsx:1313`).
- **Rebuild notes:** Gate the OAuth affordance on the config shape, not on the error alone.

### MCP OAuth authentication flow  `id: desktop-b.mcp-oauth`
- **Surface:** Desktop app
- **Where:** MCP server config pane → **“Authenticate”**.
- **What it does:** Runs a first-class OAuth login for an MCP server: opens the system browser, waits for the token to land, then treats the result as a fresh probe.
- **How it works:** `authenticate()` (`apps/desktop/src/app/skills/mcp-tab.tsx:604`) calls `completeMcpDesktopOAuth({serverName, start: authMcpServer, status: getMcpOAuthFlow, openExternal: window.hermesDesktop.openExternal})`. Success is verified against the token on disk — “a friendly tools/list is not proof” (comment at `mcp-tab.tsx:602`). The returned tool list doubles as the probe result and is cached under the **post-auth** fingerprint (`auth: 'oauth'`), because that is the config the mount effect will read back. The config cache is patched with `auth: 'oauth'`; if the editor draft is dirty the field is patched into the draft in place rather than clobbering the user's other edits — otherwise the next Save would drop the freshly persisted auth field (comment at `mcp-tab.tsx:628`).
- **Inputs / options:** One button; disabled and relabelled **“Waiting for browser…”** while the flow runs.
- **Outputs / side effects:** Opens the system browser; persists `auth: oauth`; toasts **“Authenticated”** (`settings.mcp.authenticatedTitle`) with message **“{server}: {n} tools”** (`settings.mcp.authenticatedMessage`), then triggers a silent MCP reload.
- **Config / env:** n/a
- **Edge cases / guards:** Every branch is epoch-guarded so a profile switch mid-flow discards profile A's result.
- **Rebuild notes:** Verify the credential on disk, not by a successful list call.

### `mcp.json` document editor  `id: desktop-b.mcp-editor`
- **Surface:** Desktop app
- **Where:** MCP tab → right column, header **“mcp.json”** with a dot when dirty.
- **What it does:** Edits the whole MCP server map as one JSON document, highlights the block under the cursor, and saves it back into config.
- **How it works:** `JsonDocumentEditor` with `filePath="mcp.json"` (`apps/desktop/src/app/skills/mcp-tab.tsx:1141`). The document is `{"mcpServers": {...}}` (`wrapDoc`, `mcp-tab.tsx:63`) and is parsed back by `parseServersDoc()` (`mcp-tab.tsx:66`). `saveDoc()` (`mcp-tab.tsx:954`) parses, persists, resets the draft, and then keeps only the probes whose server survived **and** kept the same config fingerprint — removed or edited entries drop their probe so the mount effect re-probes the new shape. `docVersion` remounts the editor when the draft is regenerated programmatically; `dirty` guards user edits from being clobbered by those regenerations.
- **Inputs / options:** The editor body; `onCursorChange` drives the left-column selection; the editor's own save keybinding; a trailing button **“Save”** (`common.save`) / **“Saving...”** (`common.saving`), disabled unless dirty.
- **Outputs / side effects:** Writes `mcp_servers`; toasts **“MCP server saved”** (`settings.mcp.savedTitle`) with **“mcp.json applies after MCP reload.”** (`settings.mcp.savedMessage`). Parse failures toast **“Invalid MCP JSON”** (`settings.mcp.invalidJson`); save failures **“Save failed”** (`settings.mcp.saveFailed`). The format-JSON action also reports through `invalidJson`.
- **Config / env:** n/a
- **Edge cases / guards:** Catalog also carries **“Name required”** / **“Give this MCP server a config key.”** (`settings.mcp.nameRequiredTitle` / `nameRequiredMessage`), **“Server config must be a JSON object”** (`objectRequired`), **“Edit server”** (`editServer`), **“Name”** (`name`), **“Server JSON”** (`serverJson`), **“Save server”** (`saveServer`), **“Test connection”** / **“Testing...”** / **“Connected — {n} tool(s) available”** / **“Connection failed”** (`test`, `testing`, `testOk`, `testFailed`) for the per-server form variant.
- **Rebuild notes:** One document, one save; derive the list from the document rather than keeping two sources of truth.

### “New server” (+) button  `id: desktop-b.mcp-new-server`
- **Surface:** Desktop app
- **Where:** MCP tab → left column, add button **“New server”** (`i18n: settings.mcp.newServer`); also the action inside the empty state.
- **What it does:** Seeds a starter server entry into the document draft and puts the cursor in it, so naming happens in the editor like any other `mcp.json`.
- **How it works:** `addServer()` (`apps/desktop/src/app/skills/mcp-tab.tsx:875`) picks the first free key from `my-server`, `my-server-2`, … and inserts `STARTER_ENTRY = { command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '/path/to/dir'] }` (`mcp-tab.tsx:60`), marks the draft dirty, bumps `docVersion`, and on the next frame moves the editor cursor just inside the new key.
- **Inputs / options:** One button.
- **Outputs / side effects:** Draft only — nothing is written until Save.
- **Config / env:** n/a
- **Edge cases / guards:** No-ops while `profilePending`. If the current draft does not parse, it falls back to the last saved server map as the base.
- **Rebuild notes:** n/a

### MCP paste-anything import  `id: desktop-b.mcp-import`
- **Surface:** Desktop app
- **Where:** MCP tab → “Servers” header → button **“Import”** (`i18n: settings.mcp.importButton`, clippy icon) opening a 20 rem popover. Component `McpImportButton`, `apps/desktop/src/app/skills/mcp-tab.tsx:1436`.
- **What it does:** Accepts almost any published MCP snippet — an `mcp.json` fragment, an `npx`/`docker` command line, a `claude mcp add` line, a bare URL, or a Cursor deeplink — infers the server name and config, previews it, and merges it into the editor draft.
- **How it works:** `parseMcpImport(text)` produces `McpImportEntry[]`; `importServers()` (`mcp-tab.tsx:912`) merges each entry under a unique key (`name`, `name-2`, …), marks the draft dirty, bumps `docVersion` and focuses the first new block. Saving stays an explicit step so placeholder env values (`YOUR_KEY`, …) can be fixed in the editor first (comment at `mcp-tab.tsx:906`).
- **Inputs / options:** An autofocused mono textarea (min 5 rem, max 10 rem) with placeholder **“Paste an mcp.json snippet, npx/docker command, claude mcp add line, URL, or Cursor link…”** (`settings.mcp.importPlaceholder`); a scrollable preview list showing each inferred name and its url or `command args`; a confirm button reading **“Add to mcp.json”** (`settings.mcp.importConfirm`) or **“Add {n} servers to mcp.json”** (`settings.mcp.importConfirmMany`), disabled until something parses.
- **Outputs / side effects:** Draft only. Closing the popover clears the text.
- **Config / env:** n/a
- **Edge cases / guards:** Unrecognised text shows **“No server config recognized in the pasted text.”** (`settings.mcp.importNoMatch`). Disabled entirely while `profilePending`.
- **Rebuild notes:** Support the four or five real-world snippet shapes; a preview before merge is what makes paste-anything safe.

### Nous-approved MCP catalog  `id: desktop-b.mcp-catalog`
- **Surface:** Desktop app
- **Where:** MCP tab → left column, section header **“Catalog”** (`i18n: settings.mcp.tabCatalog`), below the Servers list. Component `McpCatalog`, `apps/desktop/src/app/skills/mcp-tab.tsx:1525`.
- **What it does:** One-click installs of curated MCP servers, with an inline prompt for any required credentials.
- **How it works:** `getMcpCatalog(profile)` under key `['mcp-catalog', scopeProfileKey]` with `staleTime: 5 min`. The section only lists entries that are neither `installed` nor already present in the config map, so installed servers appear exactly once (in the fleet list, with live status) and there is no tab-flipping to find the install button (`mcp-tab.tsx:445`). `install()` (`mcp-tab.tsx:1541`) reveals the credential prompt on the first click when required env values are missing, and only errors on the second. Git-backed entries clone in the background: the row stays busy while `getActionStatus(action, 1, profile)` is polled every `CATALOG_INSTALL_POLL_MS = 1500` ms until it stops running, and a non-zero exit is raised as a real failure instead of a false success.
- **Inputs / options:** Per-row: an avatar with a status dot (`ok` when installed+enabled, `off` when installed but disabled, `unknown` otherwise), the prettified name, attribute chips — the transport string, **“OAuth”** or **“API key”** for `auth_type`, and **“Needs build”** (`settings.mcp.catalogNeedsInstall`) when `needs_install` — a green **“Enabled”** (`catalogEnabled`) or **“Installed”** (`catalogInstalled`) marker, a two-line clamped description, an optional credential form (one password input per `required_env` entry, label = `env.prompt || env.name` with a trailing ` *` when required), and a button reading **“Install”** (`catalogInstall`) / **“Installing...”** (`catalogInstalling`) / **“Installed”**, disabled once installed or while any install runs.
- **Outputs / side effects:** `installMcpCatalogEntry(name, envDraft, profile)`; on success toasts **“Installing {name}... applies to new sessions when done.”** (`settings.mcp.catalogInstallStarted`) and the parent refetches config + catalog and reloads live sessions.
- **Config / env:** Credentials are written by the backend; stored values are never displayed.
- **Edge cases / guards:** Missing credentials toast **“{name} requires credentials”** (`settings.mcp.catalogEnvPrompt`) with **“Fill in the required values before installing.”** (`catalogEnvRequired`); failures toast **“Failed to install {name}”** (`catalogInstallFailed`). Loading shows **“Loading MCP catalog...”** (`catalogLoading`); an empty catalog shows **“No catalog entries available.”** (`catalogEmpty`) under the title “Catalog”; load failure copy is **“MCP catalog failed to load”** (`catalogLoadFailed`). A single in-flight install disables every row so a re-click cannot spawn a second install over the first's tracked process.
- **Rebuild notes:** Poll a background install to completion before declaring success, and never show stored secrets back to the user.

### MCP logs pane  `id: desktop-b.mcp-logs`
- **Surface:** Desktop app
- **Where:** MCP tab → right column, pinned pane under the editor (`id: mcp-logs`, default height 176 px). Title is the selected server's name, or **“All servers”** (`i18n: settings.mcp.allServers`).
- **What it does:** Hermes' equivalent of Cursor's “MCP Logs” — tails either the raw stdio transcript or the agent-side MCP log, scoped to the cursor-selected server.
- **How it works:** `McpLogs` (`apps/desktop/src/app/skills/mcp-tab.tsx:1711`) polls every `LOG_POLL_MS = 2000` ms. For the stdio source, `filterStdioSections()` (`mcp-tab.tsx:1688`) keeps only the sections belonging to one server: the shared file has no per-line tags, so a section starts at that server's marker line matching `/^===== \[.*\] starting MCP server '(.+)' =====$/` (`STDIO_MARKER_RE`, `mcp-tab.tsx:1683`) and runs until the next marker of any server. The body uses the app's tool-output surface (`CodeCardBody` typography plus the floating hover-reveal copy button).
- **Inputs / options:** Two text tabs in the pane header: **“stdio”** and **“agent”**. The pane's own collapse/resize controls.
- **Outputs / side effects:** Read-only.
- **Config / env:** n/a
- **Edge cases / guards:** Empty output shows **“No output yet.”** (`settings.mcp.noOutput`).
- **Rebuild notes:** Tag log lines per server at the source instead of reconstructing sections from markers.

### MCP reload  `id: desktop-b.mcp-reload`
- **Surface:** Desktop app
- **Where:** MCP tab — the per-row/config refresh icon (**“Reload MCP”**, `i18n: settings.mcp.reload`) and the automatic silent reload after a successful OAuth.
- **What it does:** Re-probes a server and asks the live gateway to reload MCP tool schemas so new tools apply to fresh turns.
- **How it works:** `runProbe(name)` calls `testMcpServer(name, profile)` and caches the result under `(name, config fingerprint, profile)`. The live reload rides the **active gateway** socket, which is why `SkillsView` withholds the gateway instance entirely for a cross-backend scope (see `desktop-b.skills-scope-selector`).
- **Inputs / options:** Refresh icon button (spins while probing); the button is disabled during a probe.
- **Outputs / side effects:** Toasts **“MCP tools reloaded”** (`settings.mcp.reloadedTitle`) with **“New tool schemas apply to fresh turns.”** (`reloadedMessage`); label **“Reloading...”** (`reloading`) while running.
- **Config / env:** n/a
- **Edge cases / guards:** With no gateway connection the reload reports **“Gateway unavailable”** (`gatewayUnavailableTitle`) / **“Reconnect the gateway before reloading MCP.”** (`gatewayUnavailableMessage`); other failures toast **“MCP reload failed”** (`reloadFailed`).
- **Rebuild notes:** Keep config persistence and live reload independent so a reload failure never blocks a save.

### MCP empty state  `id: desktop-b.mcp-empty`
- **Surface:** Desktop app
- **Where:** MCP tab → left column when no servers are configured.
- **What it does:** Explains what an MCP server is for and offers the create action.
- **How it works:** `PanelEmpty` with icon `plug` (`apps/desktop/src/app/skills/mcp-tab.tsx:1076`).
- **Inputs / options:** Title **“No MCP servers”** (`settings.mcp.emptyTitle`), description **“Add a stdio or HTTP server to expose MCP tools.”** (`settings.mcp.emptyDesc`), button **“New server”** (`settings.mcp.newServer`).
- **Outputs / side effects:** Seeds the starter entry.
- **Config / env:** n/a
- **Edge cases / guards:** The catalog section still renders below the empty state when the catalog has entries.
- **Rebuild notes:** n/a

---

## 9. Memory Graph (star map)

### Memory Graph overlay  `id: desktop-b.starmap-overlay`
- **Surface:** Desktop app
- **Where:** Route `/starmap` (opened from the command palette / pane registry). Close aria **“Close memory graph”** (`i18n: starmap.close`). Component `StarmapView`, `apps/desktop/src/app/starmap/index.tsx:18`.
- **What it does:** A top-down “star map” of everything Hermes has learned for the active profile — every skill and memory plotted on a radial time axis, with a scrubber that plays the history forward.
- **How it works:** Data is fetched on demand by `loadStarmapGraph()` into the `$starmapGraph` / `$starmapLoading` / `$starmapError` atoms (`apps/desktop/src/store/starmap.ts`). The chrome (timeline scrubber, legend, share controls) floats over the canvas, so the panel has no header of its own (comment at `starmap/index.tsx:13`). A pasted share code populates `imported`, which overrides the live scan; it is cleared by **“Back to my map”** and whenever a fresh profile graph loads.
- **Inputs / options:** Everything in the entries below.
- **Outputs / side effects:** Read-only except for node edit/delete/archive.
- **Config / env:** n/a
- **Edge cases / guards:** An error shows icon `warning` with title **“Could not load memory graph”** (`starmap.loadFailed`) and the error as description. Loading shows a `PageLoader` labelled **“Loading…”** (`starmap.loading`). A real (non-imported) empty graph shows icon `lightbulb`, **“Nothing learned yet”** (`starmap.emptyTitle`) and **“As Hermes builds skills and memories for your work, they appear here.”** (`starmap.emptyDesc`). Catalog also carries the unrendered header strings **“Memory Graph”** (`starmap.title`), **“{n} skills across {m} categories”** (`starmap.subtitle`), **“Refresh”** (`starmap.refresh`), **“Memory”** (`starmap.memory`), and the filter/view chips **“All”** / **“Used”** / **“Learned”** / **“Graph”** (`starmap.filterAll|filterUsed|filterLearned|viewGraph`).
- **Rebuild notes:** Keep the graph in a store so overlays can be opened/closed without refetching; the canvas is one component and the chrome floats.

### Star-map canvas (rendering + camera)  `id: desktop-b.starmap-canvas`
- **Surface:** Desktop app
- **Where:** Memory Graph → the full-bleed canvas.
- **What it does:** Draws every skill and memory as a node on concentric time rings — the core is the oldest, the outer edge the newest — with force-laid links between related nodes.
- **How it works:** `StarMap` (`apps/desktop/src/app/starmap/star-map.tsx`) with the renderer in `render.ts`, the d3-force layout in `simulation.ts`, ring geometry in `geometry.ts` and `time-axis.ts`, colour math in `color.ts` and text layout in `text.ts`. Geometry constants (`apps/desktop/src/app/starmap/constants.ts`): inner radius `RING_INNER = 58`, outer `RING_OUTER = 340`, zoom clamp `ZOOM_MIN = 0.3` … `ZOOM_MAX = 5`, `FIT_PADDING = 80`, `TILT = 1` (vertical squash — “looking down at a tilted disk”), `RING_STEPS = 4`. Node glyphs come from `NODE_SHAPE`: a **circle** for a skill, a **diamond** for a memory (`constants.ts:80`). Recency drives ink through `AGE_GRADIENT = {oldInk: 0.42, mid: 0.52, midInk: 0.74, newInk: 0.95, reach: 1}` so old content is quiet and recent content bright. Orbs are darkened by `ORB_DARKEN = 0.3` so a bright primary does not swallow the sheen, and near-white ink forces the sheen to `WHITEISH_SHEEN = 0.95`. Per-theme line/ring styles live in `MODE_DEFAULTS` and `RING_PARAMS` (dark: lineAlpha 0.24, lineWidth 0.5, dashed 1.5, ringAlpha 0.1, ringWidth 1.5, bandAlpha 0.01, lightSize 0.64, sheen 0.12; light: lineAlpha 0.18, ringAlpha 0.06, ringWidth 2, bandAlpha 0.03, lightSize 0.27, sheen 0.1). A hovered/selected date's band uses `LIT_BAND_ALPHA = 0.04` (the focused ring outline is twice that).
- **Inputs / options:** Mouse wheel = zoom about the cursor (×0.9 / ×1.1 per notch, clamped); drag = pan; double-click = reset the view; right-click a node = the node context menu; macOS smart zoom (two-finger double-tap, detected by `isSmartZoomWheel`) also resets the view. Any manual zoom cancels an in-progress play-through (`star-map.tsx:913`).
- **Outputs / side effects:** Canvas only.
- **Config / env:** Colours derive from the live `--theme-primary` CSS variable (the legend's memory swatch is recomputed from it, `star-map.tsx:470`).
- **Edge cases / guards:** The canvas is `touch-none select-none`.
- **Rebuild notes:** Separate the pure geometry (`NODE_SHAPE` paths, ring radii) from the drawing so a future sprite/instanced renderer can bake from the same constants — the code explicitly calls this the seam (`constants.ts:78`).

### Star-map legend  `id: desktop-b.starmap-legend`
- **Surface:** Desktop app
- **Where:** Memory Graph → bottom-left corner.
- **What it does:** Explains the two node shapes and the radial time meaning.
- **How it works:** `apps/desktop/src/app/starmap/star-map.tsx:967`.
- **Inputs / options:** Three static lines plus a live reveal label — a primary-coloured dot followed by **“skill”**; a rotated square in the memory colour followed by **“memory”**; and the caption **“core = oldest · outer = newer”**. A `RevealLabel` shows the date the scrubber currently reveals to.
- **Outputs / side effects:** None (`pointer-events-none`).
- **Config / env:** n/a
- **Edge cases / guards:** These three strings are hard-coded English, not i18n keys.
- **Rebuild notes:** Move the legend strings into the catalog.

### Timeline scrubber  `id: desktop-b.starmap-timeline`
- **Surface:** Desktop app
- **Where:** Memory Graph → centred along the top (28 rem wide). Component `apps/desktop/src/app/starmap/timeline.tsx`.
- **What it does:** Plays or scrubs the map's history: dragging reveals the map up to a point in time, and the play button animates the reveal forward.
- **How it works:** The track is a `role="slider"` div with `aria-valuemin=0`, `aria-valuemax=100`, `aria-valuenow = round(reveal × 100)` and `tabIndex=0` (`timeline.tsx:197`). `ratioAt(clientX)` maps the pointer to a 0–1 reveal ratio clamped to the track; pointer capture keeps the drag alive outside the element. The reveal ratio feeds a CSS variable `--starmap-reveal`, which clips the “ignited constellation” layer with `clipPath: inset(0 calc((1 - var(--starmap-reveal,1)) * 100%) 0 0)` over a dimmed (opacity 0.22) full constellation. Stars twinkle via an inline `@keyframes starmap-twinkle` (opacity oscillating to 35 %). Star colour is `var(--theme-primary)` for skills and the memory colour for memories. Reveal progress also drives the map's per-element “appear” easing (`FadeBuckets.appear`, `apps/desktop/src/app/starmap/types.ts:208`) so nodes rise outward into place and rings grow out as they are revealed.
- **Inputs / options:** Play/pause button, aria-label **“Play timeline”** or **“Pause”** (hard-coded English), icon `triangle-right` / `debug-pause`. The scrubber track, aria-label **“Timeline scrubber”**, responds to pointer down/move/up.
- **Outputs / side effects:** Updates the reveal store, which the canvas reads each frame.
- **Config / env:** n/a
- **Edge cases / guards:** The container is `z-20` so it sits above the titlebar's `z-10` app-region drag layer — otherwise dragging the scrubber would drag the window (comment at `star-map.tsx:946`); both it and the share controls carry `[-webkit-app-region:no-drag]`.
- **Rebuild notes:** Drive both the visual clip and the layout easing from one 0–1 reveal value.

### Star-map node context menu  `id: desktop-b.starmap-node-menu`
- **Surface:** Desktop app
- **Where:** Memory Graph → right-click any node. Component `NodeContextMenu`, `apps/desktop/src/app/starmap/node-context-menu.tsx:252`.
- **What it does:** Lets you edit or remove one learned skill or memory directly from the map.
- **How it works:** A hand-rolled fixed-position card (the anchor is a canvas point, not a DOM node) styled to the `DropdownMenuContent`/`Item` scale, with a full-screen click-catcher behind it. `openEdit()` fetches `getLearningNode(id)`; `save()` calls `editLearningNode(id, content)` and, on success, reloads the graph with `loadStarmapGraph(true)`.
- **Inputs / options:** A truncated label header, then two items: **“Edit memory…”** / **“Edit skill…”** (built as `Edit {noun}…`, hard-coded), and **“Archive skill”** for a skill or **“Delete memory”** for a memory (destructive-coloured).
- **Outputs / side effects:** Opens the edit dialog or the confirm dialog.
- **Config / env:** n/a
- **Edge cases / guards:** `editEpoch` is bumped on every profile switch and the open edit/delete dialogs are closed, because their node ids belong to the previous profile and a Save/Delete after the switch would hit the newly active one (comment at `node-context-menu.tsx:263`).
- **Rebuild notes:** n/a

### Star-map node editor  `id: desktop-b.starmap-node-editor`
- **Surface:** Desktop app
- **Where:** Memory Graph → node menu → **“Edit …”**. Dialog title `Edit {label}` (max-width 42 rem, 20 rem tall editor).
- **What it does:** Edits the raw Markdown of a learned skill or memory.
- **How it works:** A framed `CodeEditor` with `filePath="SKILL.md"` for skills and `"memory.md"` for memories (`apps/desktop/src/app/starmap/node-context-menu.tsx:369`), saving through `editLearningNode`; failures render as a destructive line under the editor.
- **Inputs / options:** Editor body (with its own save/cancel keys), footer buttons **“Cancel”** (ghost) and **“Save”** / **“Saving…”** (all hard-coded English).
- **Outputs / side effects:** Writes the node and reloads the graph.
- **Config / env:** n/a
- **Edge cases / guards:** The dialog refuses to close while saving. A non-`ok` response throws `res.message`.
- **Rebuild notes:** n/a

### Star-map delete memory / archive skill  `id: desktop-b.starmap-node-delete`
- **Surface:** Desktop app
- **Where:** Memory Graph → node menu → **“Delete memory”** / **“Archive skill”**.
- **What it does:** Removes a memory permanently, or archives a skill (restorable via the CLI).
- **How it works:** For a skill, the shared `ArchiveSkillConfirmDialog` is reused (see `desktop-b.skills-archive`), with `evictStarmapNode(id)` as the optimistic apply/rollback pair. For a memory, a `ConfirmDialog` titled `Delete {label}?` with description **“This memory is removed permanently.”**, confirm label **“Delete”**, `destructive` and `dismissOnConfirm`; the confirm optimistically evicts the node, then `fireOptimistic(deleteLearningNode(id) …)` rolls the eviction back and toasts on failure (`apps/desktop/src/app/starmap/node-context-menu.tsx:405`).
- **Inputs / options:** Confirm / cancel.
- **Outputs / side effects:** Deletes or archives the learning node; the map repaints immediately.
- **Config / env:** n/a
- **Edge cases / guards:** A non-`ok` API response is turned into a throw so the rollback runs.
- **Rebuild notes:** n/a

### Share / import map code  `id: desktop-b.starmap-share`
- **Surface:** Desktop app
- **Where:** Memory Graph → bottom-right upload icon, tooltip/aria **“Import / export map”** (`i18n: starmap.shareTitle`). Component `ShareControls`, `apps/desktop/src/app/starmap/share-controls.tsx:466`.
- **What it does:** Serialises the visible map into a single short “loadout” code you can share, and loads someone else's code to view their map.
- **How it works:** `apps/desktop/src/app/starmap/share-code.ts` defines the body schema riding the generic loadout codec (`@/lib/loadout` owns the bitstream, DEFLATE, version+checksum frame and base64url). Prefix `HML` (“Hermes Memory Loadout”), `VERSION = 3`. Per node it writes: kind (1 bit over `['skill','memory']`), an interned label (trimmed to `MAX_LABEL = 64`), an interned category, `useCount` as a varint, `state` (2 bits over `['active','archived','disabled','draft']`), `memorySource` (2 bits over `['none','memory','profile']`), `createdBy` (2 bits over `['none','agent','user']`), a `pinned` bit, and the timestamp as a **12-bit position** within `[minTs, maxTs]` (`REC_BITS = 12`, i.e. 1/4096 of the span) rather than an absolute epoch. Edges are fixed-width node indices. Memory prose is dropped entirely; DEFLATE then makes the repetitive label/category text nearly free — a 60-skill map is a few hundred characters (comment at `share-code.ts:5`).
- **Inputs / options:** Trigger button (upload icon, ghost). Dialog title **“Import / export map”** (`starmap.shareTitle`), description **“Copy the code to share this map, or paste one to load. It only includes the layout, not your memory or skill text.”** (`starmap.shareHint`). One mono textarea (6 rem tall, `spellCheck` off), pre-filled with the current map's code, placeholder **“Paste a map code…”** (`starmap.sharePlaceholder`), with a hover-revealed copy button labelled **“Copy map code”** (`starmap.copy`). A full-width button **“Load”** (`starmap.importBtn`), disabled while the code is empty or identical to your own. When an imported map is showing, a **“Back to my map”** (`starmap.resetToMine`) text button appears to the left of the trigger.
- **Outputs / side effects:** Copy writes to the clipboard; Load replaces the rendered graph with the decoded one (the live scan is untouched). Success message **“Loaded a map with {n} node(s).”** (`starmap.importSuccess`); the imported map is badged **“imported map”** (`starmap.importedBadge`).
- **Config / env:** n/a
- **Edge cases / guards:** An empty code shows **“Paste a map code to load it.”** (`starmap.importEmpty`); decode failures surface inline as the codec's `LoadoutError` message. Catalog also carries **“Share map”** (`starmap.share`) and **“Import a map”** (`starmap.importMap`).
- **Rebuild notes:** Encode what the map *renders*, quantise time to a relative position, intern strings and DEFLATE — that is what keeps the code short and privacy-safe.

---

## 10. Pets — generation overlay and floating overlay window

### “Hatch a Pet” generation overlay  `id: desktop-b.pet-generate-overlay`
- **Surface:** Desktop app
- **Where:** A full Radix dialog opened by the pet-generate store (`$petGenerateOpen`), reached from the command palette's Pets section and from Settings → Appearance → Pet. Header title **“Generate a pet”** (`i18n: commandCenter.generatePet.title`) with an `Egg` icon. Component `PetGenerateOverlay`, `apps/desktop/src/app/pet-generate/pet-generate-overlay.tsx:33`.
- **What it does:** Generates four AI-drawn pet “looks” from a text description (optionally grounded on a reference photo), lets you pick one, animates it hatching into a full sprite sheet, and adopts it as your mascot.
- **How it works:** A thin view over the `pet-generate` store, which owns the generate → hatch → adopt steps and persists the inputs across close/reopen (`apps/desktop/src/store/pet-generate.ts`). Status values are `idle | ready | generating | hatching | preview | adopting | error | stale`. Dialog sizing follows the phase: single-pet screens (`hatching`, `preview`, `adopting`) use `min-w-[17rem] max-w-[20rem]`, the draft grid `min-w-[19rem] max-w-[22rem]`, with `fitContent` so the box hugs its content (`pet-generate-overlay.tsx:87`). The header title tracks the phase: **“Spawning…”** (`generatePet.spawning`) while hatching, **“It hatched!”** (`generatePet.hatched`) on preview/adopt, otherwise **“Generate a pet”**.
- **Inputs / options:** See the sub-entries — the concept prompt, the provider picker, the reference-image chip, the example chips, the draft grid, the hatch view and the preview.
- **Outputs / side effects:** Adopting installs the pet and makes it active; a crisp haptic fires and the dialog closes.
- **Config / env:** Needs a reference-capable image backend (see the unavailable card).
- **Edge cases / guards:** The overlay yields the screen to a full-screen route overlay (e.g. `/settings` while the user adds an image-gen key) by returning `null` from `useRouteOverlayActive()` — the store keeps it open so it reappears and re-probes on return (`pet-generate-overlay.tsx:44`). Closing never interrupts in-flight work: generation/hatching continues in the background and only an unadopted finished preview is discarded (`cleanupPetGenOnClose`, `pet-generate-overlay.tsx:51`). A footer banner narrates the async state — the failure reason on a dead-end error (`error || generatePet.genericError` = **“Generation failed — try again or pick a suggestion.”**), **“You can close this — Hermes will notify you when it's done.”** (`generatePet.backgroundHint`) while working, and **“This can take several minutes”** (`generatePet.slowProviderHint`) on step 1; the banner tone is `error` or `info`. A backend that predates the feature shows the destructive alert **“Update Hermes to generate pets.”** (`generatePet.staleBackend`).
- **Rebuild notes:** Keep every input in a store so the dialog is disposable; never let closing the UI cancel a long provider job.

### Pet concept prompt + generate button  `id: desktop-b.pet-prompt`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the top input, placeholder **“Describe a pet to generate…”** (`i18n: commandCenter.generatePet.placeholder`).
- **What it does:** Takes the description that drives generation and starts a round of four drafts.
- **How it works:** `apps/desktop/src/app/pet-generate/pet-generate-content.tsx:218`. The value lives in `$petGenInput`; Enter triggers `generate()` which calls `generateDrafts(requestGateway, {prompt, referenceImage})` when the prompt is non-empty **or** a reference image is attached and nothing is busy. The inline `GenerateButton` is the same sparkle primitive used by the commit-message and project-idea fields.
- **Inputs / options:** Text input (autofocused); Enter to generate; the inline sparkle button labelled **“Generate”** (`generatePet.generate`), which becomes a cancel control labelled **“Cancel”** (`common.cancel`) while generating and calls `discardDrafts` (abort and return to step 1, keeping the prompt for a quick tweak).
- **Outputs / side effects:** Streams up to four drafts into `$petGenDrafts`.
- **Config / env:** n/a
- **Edge cases / guards:** The prompt row is hidden entirely for `hatching`, `preview` and `adopting`, and when no backend is available. Catalog also carries the unrendered hints **“Type a description, then press Enter to draft four looks.”** (`generatePet.promptHint`), **“Press Enter to draft four looks from your description.”** (`generatePet.readyHint`), **“Generating…”** (`generatePet.generating`) and **“Retry”** (`generatePet.retry`).
- **Rebuild notes:** n/a

### Pet example prompt chips  `id: desktop-b.pet-examples`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the idle screen, a centred cluster of rounded outline buttons.
- **What it does:** One-click seed prompts that immediately start a draft round.
- **How it works:** `EmptyHint` (`apps/desktop/src/app/pet-generate/components/empty-hint.tsx:236`) renders `EXAMPLE_PROMPTS` verbatim: **“bubble-tea otter”**, **“sock elf”**, **“pixel dragon”**, **“office cat”**, **“neon axolotl”**, **“moss golem”**. Clicking one sets `$petGenInput` to `"a {example}"` and calls `generateDrafts` straight away (`pet-generate-content.tsx:143`).
- **Inputs / options:** Six buttons; the cluster is capped at 300 px wide so it wraps into two rows.
- **Outputs / side effects:** Starts a generation round.
- **Config / env:** n/a
- **Edge cases / guards:** This screen doubles as the error-empty state — the failure reason rides the dialog's footer banner, so only the retry chips are shown here (comment at `pet-generate-content.tsx:298`).
- **Rebuild notes:** Specific prompts make better pets — that is petdex's own advice, quoted in the source comment.

### Pet image-backend picker  `id: desktop-b.pet-provider-picker`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the quiet text dropdown under the prompt. Component `ProviderPicker`, `apps/desktop/src/app/pet-generate/components/provider-picker.tsx:105`.
- **What it does:** Chooses which configured image backend generates the pet.
- **How it works:** Reads `$petGenProviders` / `$petGenProvider` and writes with `setPetGenProvider`; picking the entry marked `default` clears the override by setting `''`. The trigger shows the current provider's label plus a chevron. There are no per-option notes because every backend resolves to the same faithful OpenAI image model, so there is no trade-off to describe (comment at `provider-picker.tsx:101`).
- **Inputs / options:** One dropdown; each item shows the provider label and a check on the current one.
- **Outputs / side effects:** Sets the provider override used by the next generation.
- **Config / env:** Providers come from the backend's reference-capable image-model list.
- **Edge cases / guards:** Hidden entirely when fewer than two reference-capable backends exist. The menu is portalled to `body` and needs `z-(--z-modal-popover)` or it opens behind the dialog (comment at `provider-picker.tsx:128`).
- **Rebuild notes:** n/a

### Pet reference image  `id: desktop-b.pet-reference`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → **“Add a reference”** text button (image icon) which becomes a chip once a file is chosen.
- **What it does:** Grounds generation on a photo of your own, so the pet resembles it.
- **How it works:** A hidden `<input type="file" accept="image/*">`; `readReferenceImage(file)` (`apps/desktop/src/app/pet-generate/lib/read-reference-image.ts:319`) rejects files over `DEFAULT_MAX_INPUT_BYTES = 16 MiB`, then decodes from an **object URL** (not `readAsDataURL`, so a large file never inflates into a giant base64 string first), downscales so the longest side is at most 1024 px, redraws onto a canvas and returns a PNG data URL; the object URL is always revoked. The result is stored in `$petGenRefImage` / `$petGenRefName`.
- **Inputs / options:** The **“Add a reference”** button (hard-coded English); the `ReferenceChip` (`components/reference-chip.tsx:161`) showing a 16 px thumbnail (click opens the shared `ImageLightbox`, title **“Open image”**, `desktop.openImage`), the truncated filename (falling back to the literal `Reference`), and a remove `X` with aria-label **“Remove reference”**.
- **Outputs / side effects:** The data URL is sent with the next generation request. The lightbox offers the shared image download.
- **Config / env:** n/a
- **Edge cases / guards:** An oversized file errors with **“Reference image is too large. Use one under 16 MB.”** (`generatePet.referenceImageTooLarge`); an undecodable one with **“Could not read that reference image. Try a PNG, JPG, WebP, or GIF.”** (`generatePet.referenceImageInvalid`). Picking a valid reference clears a picker-only error back to `idle`. The file input's value is reset after each pick so the same file can be re-selected.
- **Rebuild notes:** Downscale before base64 — it is the difference between a 50 KB and a 20 MB request.

### Pet draft grid  `id: desktop-b.pet-draft-grid`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the 2×2 grid. Component `DraftGrid`, `apps/desktop/src/app/pet-generate/components/draft-grid.tsx:23`.
- **What it does:** Streams in four candidate looks, lets you select one (even before the rest finish), remix any of them, or hatch the selected one.
- **How it works:** `VARIANT_COUNT = 4`. While generating, four slots are rendered and each is filled by the draft whose `index` matches; an empty slot shows a bouncing creme egg (`PixelEggSprite mode="bounce"` at 48 px with a contact shadow). A landed draft renders its `dataUri` with the `pet-reveal` hatch-into-place animation. Each cell keeps the `192/208` aspect ratio.
- **Inputs / options:** Click any landed draft to select it (`selectableCardClass({active, prominent})`). A hover/focus-revealed **“Remix”** icon button (`git-branch` codicon, tooltip and aria `generatePet.remix`) in each cell's top-right, shown only when not generating. A progress row: a shimmering **“Generating…”** (`generatePet.generating`) on the left (invisible when idle) and a tabular `{n}/4` counter on the right. A centred **“Cancel”** (`common.cancel`) text button under the grid, and — once any draft exists — a full-width **“Hatch”** button (`generatePet.hatch`, paw-print icon) disabled until something is selected.
- **Outputs / side effects:** Hatch calls `hatchSelected(requestGateway, {name: cleanPetName(prompt), prompt})`; if generation is still running it first calls `cancelGenerate()` so the remaining drafts are aborted while the existing ones are kept (`pet-generate-content.tsx:172`). The prompt is grounding text, not a label — the user names the pet on reveal.
- **Config / env:** n/a
- **Edge cases / guards:** A hatch failure with drafts still present renders a destructive `Alert` above the grid so the user can re-pick and retry without losing their options (`pet-generate-content.tsx:275`).
- **Rebuild notes:** Stream drafts as they finish and let the user commit early — waiting for all four is the slow path.

### Pet remix (with one-time confirmation)  `id: desktop-b.pet-remix`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the `git-branch` button on a draft cell. Confirm dialog title **“Remix this look?”** (`i18n: commandCenter.generatePet.remixConfirmTitle`).
- **What it does:** Runs a fresh generation round grounded on the chosen draft, so you can explore variations without starting over.
- **How it works:** `remixDraft()` (`apps/desktop/src/app/pet-generate/pet-generate-content.tsx:155`) short-circuits to `runRemix` when `$petGenRemixConfirmed` is already set; otherwise it stages the draft and shows the confirm. `runRemix` calls `generateDrafts(requestGateway, {prompt, referenceImage: draft.dataUri})` — same prompt, still on step 2. Confirming calls `markRemixConfirmed()` so the dialog never appears again.
- **Inputs / options:** Confirm button **“Remix”** (`generatePet.remix`); body **“This generates a fresh set of drafts using this one as the starting point. It can take several minutes.”** (`generatePet.remixConfirmBody`).
- **Outputs / side effects:** Replaces the current draft set.
- **Config / env:** The “confirmed” flag is persisted in the pet-generate store.
- **Edge cases / guards:** No-ops while busy.
- **Rebuild notes:** Confirm destructive-but-slow actions once, then remember the answer.

### Pet hatching view  `id: desktop-b.pet-hatching`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → after **“Hatch”**. Component `HatchingView`, `apps/desktop/src/app/pet-generate/components/hatching-view.tsx:290`.
- **What it does:** Shows a beating egg while the backend renders every animation row of the sprite sheet, with a subtitle that tracks the phase.
- **How it works:** `PetEggHatch` with a `cancelLabel` and `onCancel={cancelHatch}`. The subtitle comes from the `PetHatchStage` pushed by the store: phase `row` → **“Sketching frame {done} of {total}…”** (`generatePet.hatchRow`), phase `compose` → **“Piecing it together…”** (`generatePet.hatchComposing`), otherwise **“Almost there…”** (`generatePet.hatchSaving`); with no stage yet it shows **“Bringing it to life…”** (`generatePet.hatchingSub`). The dialog header meanwhile reads **“Spawning…”** and, once hatched, **“It hatched!”**; the catalog also carries **“Hatching your pet…”** (`generatePet.hatching`).
- **Inputs / options:** A cancel control labelled **“Cancel”** (`common.cancel`).
- **Outputs / side effects:** Produces a full `PetInfo` (spritesheet + per-row frame counts) into `$petGenPreview`.
- **Config / env:** n/a
- **Edge cases / guards:** Cancelling aborts the hatch but the dialog can also simply be closed — the job keeps running in the background.
- **Rebuild notes:** Report per-row progress from the backend; a single spinner over a multi-minute job reads as a hang.

### Pet hatch preview + adopt  `id: desktop-b.pet-preview-adopt`
- **Surface:** Desktop app
- **Where:** Pet generation overlay → the reveal screen. Component `HatchPreview`, `apps/desktop/src/app/pet-generate/components/hatch-preview.tsx:164`.
- **What it does:** Cracks the egg open, shows the finished pet cycling through all of its animations, and lets you name and adopt it — or start over.
- **How it works:** First a `PixelEggSprite mode="hatch"` plays the crack frames; its `onDone` flips `revealed` and fires a crisp haptic. The live pet then plays its “yay” jump for roughly two loops (`2 × (pet.loopMs ?? 1100)`) before the state cycler takes over, advancing every `PREVIEW_STATE_MS = 1400` ms through the pet's own `stateRows`, falling back to `PREVIEW_ROWS = ['idle','waving','running-right','running-left','running','review','jumping','failed','waiting']`, filtered to rows that actually have frames (`frameCountForRow`, `apps/desktop/src/app/pet-generate/lib/frame-count.ts:215`, which maps directional walks and aliases onto their base state via `ROW_TO_FRAME_KEY` and falls back per-row → per-state → mapped state → sheet-wide `framesPerState`). Preview scale is fixed at `PREVIEW_SCALE = 0.7`. A `PetStarShower` plays over the reveal.
- **Inputs / options:** A name input (autofocused, placeholder **“Name your pet”**, `generatePet.namePlaceholder`) where Enter adopts; a ghost button **“Start over”** (`generatePet.startOver`, `RefreshCw` icon) calling `discardHatched`; and a primary **“Adopt”** button (`generatePet.adopt`, paw-print icon, spinner while adopting).
- **Outputs / side effects:** `adoptHatched(requestGateway, name)`; on success a crisp haptic fires and the overlay closes. Leaving the name blank keeps the provisional name derived from the prompt by `cleanPetName()`.
- **Config / env:** n/a
- **Edge cases / guards:** Every piece of local state resets when `pet.slug` changes. Adoption errors render in a destructive `Alert` between the input and the buttons; both buttons disable while adopting.
- **Rebuild notes:** Preview every animation row before adoption — it is the only chance to notice a broken frame.

### “Add an image backend to generate” card  `id: desktop-b.pet-unavailable`
- **Surface:** Desktop app
- **Where:** Pet generation overlay, replacing the prompt when no reference-capable image backend is configured. Component `GenerateUnavailable`, `apps/desktop/src/app/pet-generate/components/generate-unavailable.tsx:264`.
- **What it does:** Explains why generation is impossible and offers an in-app path to configure a provider.
- **How it works:** Availability is probed by `checkPetGenAvailable(requestGateway)` on every mount of the content (so returning from the providers settings flips the card back to the prompt with no manual refresh, `pet-generate-content.tsx:80`); `null` means “not probed yet” and stays optimistic — only a confirmed `false` swaps in this card.
- **Inputs / options:** A paw-print badge; heading **“Add an image backend to generate”**; body **“Hatching a custom pet needs a provider that can ground on a reference image.”**; a primary button **“Set up image generation”** (`Settings2` icon) which navigates to `${SETTINGS_ROUTE}?tab=providers` **without closing the overlay**; and a key-source line reading **“Grab a key from”** followed by three external links — **“Nous Portal”** (`https://portal.nousresearch.com`), **“OpenRouter”** (`https://openrouter.ai/keys`) and **“OpenAI”** (`https://platform.openai.com/api-keys`) separated by `·`.
- **Outputs / side effects:** Navigation and external links.
- **Config / env:** Provider API keys (see the Providers panel in the `desktop-settings` shard).
- **Edge cases / guards:** All strings here are hard-coded English, not i18n keys. The dialog title is rendered `sr-only` in this state.
- **Rebuild notes:** n/a

### Floating pet overlay window  `id: desktop-b.pet-overlay-window`
- **Surface:** Desktop app
- **Where:** A separate, always-on-top, transparent Electron `BrowserWindow` booted with `?win=overlay`. Components `apps/desktop/src/app/pet-overlay/overlay-root.tsx:18` and `pet-overlay-app.tsx:63`.
- **What it does:** Pops the mascot out of the app window so it floats anywhere on the desktop, reacts to what Hermes is doing, and offers a one-line composer plus a “you have a reply” mail button.
- **How it works:** The overlay shares the main bundle (so it reuses the same CSS and atoms) but mounts a minimal surface with no app shell, no gateway and no i18n — its few strings are inline (comment at `overlay-root.tsx:9`). Because `index.html` paints an opaque themed background to avoid a flash in normal windows, `mountPetOverlay()` injects a late high-specificity `html,body,#root{background:transparent !important;}` rule. It is a **pure puppet**: the main renderer pushes `{info, activity, busy, awaiting, unread, reaction}` over `window.hermesDesktop.petOverlay.onState`, which is mirrored into the same `$petInfo` / `$petActivity` / session atoms so `PetSprite` and `PetBubble` render identically with zero extra logic; on mount it sends `{type:'ready'}` because subscribe-time pushes can land before the view exists. A new `reaction.id` with `kind === 'vibe'` triggers `playVibeHearts()`. Click-through is OS-level: `setIgnoreMouse(true)` by default, re-armed by sampling the rendered canvas alpha at the cursor — a pixel counts as solid at `ALPHA_HIT_THRESHOLD = 16` (low enough for anti-aliased edges, high enough that the faint halo clicks through) — with DOM hit-testing trusted for the bubble and mail button.
- **Inputs / options:** **Drag** the pet to move it anywhere on screen (a press under `CLICK_SLOP_PX = 3` of travel counts as a click); **shift-click** pops it back into the app window (`{type:'pop-in'}`); **single click** toggles the mini composer (deferred by `DOUBLE_CLICK_MS = 250`); **double-click** toggles the app window between minimize and restore (`{type:'toggle-app'}`); **Alt+wheel** over the pet resizes it (`usePetZoomGesture`); clicking the transparent backdrop dismisses the composer. The composer is a 184 px input with placeholder **“Message…”**; Enter (without Shift) sends `{type:'submit', text}` and closes it, Escape closes it. The mail button (24 px round, `Mail` icon, aria-label and title **“Open in Hermes”**) appears only when a turn finished while you were away and sends `{type:'open-app'}`.
- **Outputs / side effects:** Window bounds are persisted after every drag and every resize (`{type:'bounds', bounds}`), so the pet reopens where and how big it was. A scale change is painted locally for instant feedback and then persisted via `{type:'scale', scale}`; the main renderer pushes back the reconciled value.
- **Config / env:** `PET_PADDING_BOTTOM = 24` must match the root's `paddingBottom` — the sprite renders bottom-centred that many pixels above the window's bottom edge, and the resize anchors on it. Fallbacks mirror `PetSprite`'s defaults: `DEFAULT_FRAME_W = 192`, `DEFAULT_FRAME_H = 208`, `DEFAULT_SCALE = 0.33`. Window size comes from `overlayWindowSize(frameW, frameH, scale)` (`store/pet-overlay.ts`).
- **Edge cases / guards:** The component renders `null` unless `info.enabled` and a `spritesheetBase64` exist. On resize the window is grown/shrunk to fit so the sprite is never cropped; with an Alt+wheel anchor the pixel under the cursor is held fixed (`x = screenX + ax - (ax - curW/2)·ratio - width/2`), otherwise the bottom-centre is pinned so the pet's feet stay planted (`pet-overlay-app.tsx:353`). The mail button stops pointer propagation so clicking it cannot start a window drag, and is anchored inside the sprite's box so the click-through hit-test still catches it.
- **Rebuild notes:** Alpha-sampling the rendered sprite is what makes an irregular always-on-top mascot feel native; keep the overlay a puppet with a single state push so there is exactly one source of truth.

---

## 11. Shared app hooks and session routing

### `openSession()` — the single door for opening a chat  `id: desktop-b.open-session`
- **Surface:** Desktop app
- **Where:** Called by every surface that opens a chat: the sidebar, ⌘K command palette, notifications, the session switcher, inline session refs, the Cron run history and the Artifacts page. `apps/desktop/src/app/open-session.ts:272`.
- **What it does:** Opens a stored session in the right place — focusing it if it is already on screen, otherwise loading it into the main tab, a stacked tab, or its own window — so a chat is never yanked out from under you.
- **How it works:** Five intents (`OpenSessionIntent`, `open-session.ts:221`): **`in-place`** (sidebar click / Enter) focuses an existing tile or main, else loads into main; **`main`** always routes into main (canonical relationship chats own the workspace, and `resumeSession` removes the now-redundant tile); **`stack`** (⌘K, notifications — anything opening a chat from outside the workspace) behaves like `tab` except that main is fair game while it holds only a blank draft, and an already-open blank draft tab is spent before a new one is stacked; **`tab`** (⌘/⌃-click, ⌘-Enter, session refs) focuses if on screen, else opens a stacked session tab and never steals main; **`window`** (⇧⌘-click) pops the session into its own window, falling back to `tab` when the bridge has no session-window support (`canOpenSessionWindow()`). Every call first runs `markSessionRead(storedSessionId)` — deliberately **before** the focus short-circuits, or clicking a session already on screen would return early at `focusOpenSession` and never clear its unread dot (comment at `open-session.ts:282`) — then `setSessionTileWorkspaceScope`. `mainChatOccupied()` (`open-session.ts:240`) decides whether main is worth preserving: any loaded chat may be mid-turn, while a blank draft has nothing to lose.
- **Inputs / options:** `openSessionIntentFromModifiers(event, base)` (`open-session.ts:247`) reads modifiers exactly as session rows do: meta **or** ctrl → `tab`; meta/ctrl **plus** shift → `window`; nothing → the caller's `base` (the sidebar passes `in-place`, palette-style opens pass `stack`). `workspaceScope` carries `{workspaceMode, ownerRoute?, workspaceOwnerKey?, workspaceTabTitle?}`; a `bots` workspace mode is threaded into `reuseBlankDraftTile` and `openSessionTile`.
- **Outputs / side effects:** Marks the session read, sets its tile workspace scope, and either focuses a tile, routes to `sessionRoute(id)`, opens a tile in the `center` zone, reuses a blank draft tile, or opens a new OS window.
- **Config / env:** n/a
- **Edge cases / guards:** An empty id is a no-op. From a full page (Artifacts, Capabilities, …) a `main` hit still has to route back, because fronting the workspace tab alone would leave the page showing — hence `focusedSessionNeedsRoute(focusOpenSession(...), $workspaceIsPage.get())` (`open-session.ts:358`).
- **Rebuild notes:** One function, an intent enum and a modifier decoder — this is the whole “don't surprise me” contract for a multi-tab chat app.

### `useRefreshHotkey` — the bare `r` refresh key  `id: desktop-b.hook-refresh-hotkey`
- **Surface:** Desktop app
- **Where:** Every list-style page (Artifacts, Cron, Messaging, Profiles, Capabilities, Webhooks).
- **What it does:** Binds the unmodified `r` key to that page's refresh action while it is mounted.
- **How it works:** `apps/desktop/src/app/hooks/use-refresh-hotkey.ts:8` — a `window` keydown listener kept current through a ref so the callback identity never re-binds.
- **Inputs / options:** `onRefresh` callback and an `enabled` flag (default `true`). Accepts both `r` and `R`.
- **Outputs / side effects:** Calls the page's refresh; `preventDefault()`.
- **Config / env:** n/a
- **Edge cases / guards:** Ignored when any of meta/ctrl/alt/shift is held, when the event is an auto-repeat, or when the focus target is `contentEditable` / an `<input>` / a `<textarea>` / a `<select>` — so typing “r” in a search field never triggers it.
- **Rebuild notes:** n/a

### `useRouteEnumParam` — tab state in the URL  `id: desktop-b.hook-route-enum-param`
- **Surface:** Desktop app
- **Where:** Artifacts (`?tab=`), Capabilities (`?tab=`), Messaging (`?platform=`).
- **What it does:** Reads and writes an enum-shaped URL search parameter so a tabbed view survives a refresh and can be deep-linked.
- **How it works:** `apps/desktop/src/app/hooks/use-route-enum-param.ts:52`. An unknown or missing value falls back to the supplied default; setting the value **to** the fallback deletes the param instead of writing it. Navigation always uses `{replace: true}` so tab clicks do not pile up in history.
- **Inputs / options:** `(key, values, fallback)` → `[value, setValue]`.
- **Outputs / side effects:** Rewrites the current URL's query string (preserving pathname and hash).
- **Config / env:** n/a
- **Edge cases / guards:** A legacy value outside `values` silently resolves to the fallback (this is how the removed `?tab=hub` link still works on the Capabilities page).
- **Rebuild notes:** n/a

### `useOnProfileSwitch` — drop per-profile view state  `id: desktop-b.hook-on-profile-switch`
- **Surface:** Desktop app
- **Where:** Capabilities page, MCP tab, star-map node menu — anywhere a mounted view holds data belonging to one backend.
- **What it does:** Runs a callback when the active gateway profile changes, but never on first mount.
- **How it works:** `apps/desktop/src/app/hooks/use-on-profile-switch.ts:92` subscribes to `$activeGatewayProfile` and guards the first effect run with a ref. `onSwitch`'s identity is deliberately excluded from the dependency array so the effect fires on profile change only.
- **Inputs / options:** One callback.
- **Outputs / side effects:** Whatever the callback drops — probes, cached usage, editor drafts, pending dialogs.
- **Config / env:** n/a
- **Edge cases / guards:** Not firing on mount is the point: a fresh view must not wipe the state it just built.
- **Rebuild notes:** Pair this with epoch counters so in-flight requests from the old profile are also discarded.

### `useRouteOverlayActive` — yield the screen to a route overlay  `id: desktop-b.hook-route-overlay-active`
- **Surface:** Desktop app
- **Where:** Modals that navigate the user to a full-screen route (e.g. the pet-generation overlay's “Set up image generation” → `/settings`).
- **What it does:** Tells a portalled modal that a full-screen route overlay (Settings, Agents, Command Center, …) is showing, so it can hide itself instead of covering it.
- **How it works:** `apps/desktop/src/app/hooks/use-route-overlay-active.ts:123` → `isOverlayView(appViewForPath(pathname))`. A modal does `if (useRouteOverlayActive()) return null`; its open state lives in a store, so it stays open and reappears — re-running its mount effects, which doubles as a free refresh — when the route overlay closes.
- **Inputs / options:** None.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** Only works for modals whose open state is *not* React-local.
- **Rebuild notes:** n/a

### `useDebounced`  `id: desktop-b.hook-debounced`
- **Surface:** Desktop app
- **Where:** Search inputs and sliders whose value feeds an effect or query.
- **What it does:** Returns a value that only updates once the input has settled for `delayMs`.
- **How it works:** `apps/desktop/src/app/hooks/use-debounced.ts:132` — a `setTimeout` per change, cleared on the next.
- **Inputs / options:** `(value, delayMs)`.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** The first render returns the raw value (no initial delay).
- **Rebuild notes:** n/a

### Shared config-record cache (`useHermesConfigRecord`)  `id: desktop-b.hook-config-record`
- **Surface:** Desktop app
- **Where:** Every settings surface that reads `GET /api/config` — the MCP tab, the model panel, the config editor.
- **What it does:** Gives every surface one shared, per-profile cache of the whole config record, so a save in one place is visible in the others and revisiting a tab paints instantly instead of blanking.
- **How it works:** `apps/desktop/src/app/hooks/use-config-record.ts:172`. Base key `['hermes-config-record']` is the app-wide active profile; an explicit `ProfileScope` appends `profileScopeKey(profile)`, which folds a remote pin's connection id into the suffix so two gateways' same-named profiles never share a cache row (the AGENTS.md “scope in key” rule, comment at `use-config-record.ts:158`). `staleTime: 0` means the cache is served immediately and revalidated in the background on every mount. Writers: `setHermesConfigCache` (base key) and `hermesConfigCacheWriter(profile)` (suffixed key), plus `invalidateHermesConfig(profile)`.
- **Inputs / options:** An optional `profile` scope; `null` and `undefined` both mean “no override” and are normalised to `undefined` so `capabilityScoped` falls back to the app-wide active profile — passing `null` would wrongly target the primary backend (comment at `use-config-record.ts:175`).
- **Outputs / side effects:** Cache reads/writes only.
- **Config / env:** `GET /api/config`.
- **Edge cases / guards:** Deliberately distinct from `session/hooks/use-hermes-config.ts`, which is side-effecting — it pushes personality/cwd/voice into the session stores for live chat (comment at `use-config-record.ts:154`).
- **Rebuild notes:** One cache row per (connection, profile); optimistic writes must land on the same key the reader uses.

### Global keybind dispatcher (`useKeybinds`)  `id: desktop-b.hook-keybinds`
- **Surface:** Desktop app
- **Where:** Mounted once near the top of the app; it owns the single global `keydown` listener for every rebindable hotkey. `apps/desktop/src/app/hooks/use-keybinds.ts:102`. The bindings themselves are edited in Settings → **“Keyboard shortcuts”** (`i18n: keybinds.title`; the panel itself is documented in the `desktop-settings` shard).
- **What it does:** Turns a pressed key combination into the app action bound to it, records new bindings while the shortcut panel is capturing, and drives the ⌃Tab session switcher.
- **How it works:** `comboFromEvent(event)` normalises the key into a combo string; `$comboIndex` maps combo → action id; the action runs from `handlersRef.current[actionId]` (built-ins, which carry React context) or, failing that, `contributedKeybindHandler(actionId)` (plugin-contributed actions bring their own `run`). Listeners are attached in **capture** phase for `keydown`, `keyup` and `contextmenu`, and in bubble phase for `paste` (`handleWindowPaste`) and the composer focus chord (`handleComposerFocusChord`), plus a `blur` handler.
- **Inputs / options:** The full built-in action map (`use-keybinds.ts:186`), with the verbatim labels from `keybinds.actions.*`: `keybinds.openPanel` **“Open keyboard shortcuts”** → `/settings?tab=keybinds`; `composer.focus` **“Focus composer”**; `composer.modelPicker` **“Open model picker”** (toggles the composer pill's live dropdown under the pointer, falling back to the full dialog when no chat surface is on screen); `composer.voice` **“Start / stop voice conversation”**; `nav.commandPalette` **“Open command palette”** (on the Settings overlay the first press instead scopes the palette to settings search); `nav.commandCenter` **“Open command center”**; `nav.settings` **“Open settings”**; `nav.profiles` **“Open profiles”**; `nav.skills` **“Open skills”**; `nav.messaging` **“Open messaging”**; `nav.artifacts` **“Open artifacts”**; `nav.cron` **“Open scheduled jobs”**; `nav.agents` **“Open agents”**; `session.new` **“New session”**; `session.newTab` **“New session tab”**; `session.newWindow` **“New window”**; `session.next` **“Next session”**; `session.prev` **“Previous session”**; `session.slot.1`…`session.slot.9` **“Switch to recent session N”** (`SESSION_SLOT_COUNT`); `session.focusSearch` **“Search sessions”**; `session.togglePin` **“Pin / unpin current session”**; `session.archive` **“Archive current session”**; `workspace.newWorktree` **“New worktree”**; `workspace.openFolder` **“Open folder as project”**; `view.toggleSidebar` **“Toggle sessions sidebar”**; `view.toggleRightSidebar` **“Toggle file browser”**; `view.toggleReview` **“Toggle review pane”**; `view.toggleStatusbar` **“Toggle status bar”**; `view.toggleTabStrip` **“Toggle tabs”**; `view.showFiles` **“Show file browser”**; `view.showBrowser` **“Open browser”**; `view.toggleHud` **“Toggle HUD mode”**; `view.showTerminal` **“Toggle terminal”**; `view.newTerminal` **“New terminal”**; `view.nextTerminal` **“Next terminal”**; `view.prevTerminal` **“Previous terminal”**; `view.closeTerminal` **“Close terminal”**; `view.closeTab` **“Close tab”**; `view.reopenTab` **“Reopen closed tab”**; `view.flipPanes` **“Swap sidebar sides”**; `view.findInPage` **“Find in page”**; `view.findNext` **“Find next match”**; `view.findPrevious` **“Find previous match”**; `appearance.toggleMode` **“Toggle light / dark”**; `profile.default` **“Switch to default profile”**; `profile.switch.1`…`profile.switch.18` **“Switch to profile N”** (`PROFILE_SLOT_COUNT`); `profile.next` **“Next profile”**; `profile.prev` **“Previous profile”**; `profile.toggleAll` **“Toggle all-profiles view”**; `profile.create` **“Create profile”**. Actions labelled in the catalog but handled elsewhere: `hud.snapToPointer` **“Move HUD to pointer (global, while HUD is open)”**, `view.selectionToComposer` **“Send selection to composer”**, `view.terminalCopy` **“Copy terminal selection”**, `view.terminalPaste` **“Paste into terminal”**, and the composer-local set `composer.send` **“Send message”**, `composer.newline` **“Insert newline”**, `composer.steer` **“Steer the running turn”**, `composer.queue` **“Queue message”**, `composer.sendQueued` **“Send next queued turn”**, `composer.mention` **“Reference files, folders, URLs”**, `composer.slash` **“Slash command palette”**, `composer.help` **“Quick help”**, `composer.history` **“Cycle popover / history”**, `composer.cancel` **“Close popover · cancel run”**. Categories: **“Composer”**, **“Profiles”**, **“Session”**, **“Navigation”**, **“View”** (`keybinds.categories.*`).
- **Outputs / side effects:** Navigation, store mutations, terminal creation, window opening — whatever the action does. In capture mode it writes the new binding with `setBinding(capturing, [combo])`.
- **Config / env:** Bindings live in the keybinds store (`$comboIndex`, `$capture`); defaults and the rebinding UI are in Settings → Keyboard shortcuts.
- **Edge cases / guards:** (1) An active IME composition (`event.isComposing`) returns immediately — Windows Chinese IMEs use `Ctrl+,` as their punctuation toggle, which previously also matched `nav.settings` and navigated away mid-word, unmounting the composer and destroying the unsent draft (comment at `use-keybinds.ts:319`). (2) Capture mode swallows everything (so ⌘K rebinds instead of opening the palette); `Escape` ends the capture. (3) While the session switcher is open, `Escape` abandons it before any combo dispatch. (4) While the find bar is open it owns ⌘G / ⌘⇧G / Escape through its own capture-phase listener, and the dispatcher explicitly yields via `findBarClaimsCombo(combo)` — both listeners are on `window`, so the bar's `stopPropagation` cannot suppress this one; otherwise ⌘G would also fire `view.toggleReview` and Escape would fire `composer.cancel`, aborting a live turn (comment at `use-keybinds.ts:377`). (5) An **unbound printable** key becomes type-to-focus: the character is routed into the composer via `requestComposerFocus('active', {typeChar})`, but bound chords win. (6) An editable focus target blocks the action unless `actionAllowedInInput(actionId, combo)`. (7) The soft `composer.focus` combos (`/` and Enter) are gated by `composerFocusKeysAllowed` so dialogs, buttons and the terminal keep those keys; a rebound chord falls through to the normal handler. (8) ⌘1…⌘9 first try `activateTreeTabSlot(slot)` — they switch the focused zone's tab when it is a real tab strip and only fall through to the profile switch on a single-pane or unfocused layout; likewise ⌃Tab first tries `cycleTreeTabInFocusedZone`. Landing on the `workspace` pane while a full page covers it also routes back to the chat, because fronting the tab alone would change nothing on screen and the key would read dead (`leavePageForWorkspaceChat`, `use-keybinds.ts:117`). (9) `view.nextTerminal` / `prevTerminal` / `closeTerminal` only act while the terminal is genuinely on screen — the tree is asked, not the toggle store, which stays true behind a stacked sibling tab or a minimised zone. (10) `view.toggleRightSidebar` falls back to toggling the terminal pane when the layout has no right side, so ⌘J is never a dead key. (11) `view.findInPage` is suppressed on overlay routes so it cannot collide with an overlay's own search bar. (12) `session.new` resets the workspace scope to `sessions` and clears `$newChatProfile` so a keyboard new chat targets the live profile, not a stale per-profile quick-create selection, and dispatches a `hermes:new-session-shortcut` window event. (13) `keyup` on `Tab` and `Control` drives the Mac-app-switcher-style commit of the session switcher; a window `blur` (⌘Tab away mid-switch) closes it so it is never stranded waiting for a keyup that never comes; a trailing `contextmenu` after a Ctrl+click commit is swallowed. (14) After a keyboard-driven overlay closes, `onReleaseTypingFocus` defers one animation frame and returns focus to the composer only if nothing else editable has claimed it — otherwise the Enter that committed a model would eat the next keystroke, and a palette action that legitimately opened a dialog would lose focus (comment at `use-keybinds.ts:294`).
- **Rebuild notes:** One capture-phase dispatcher plus a combo→action index; every special case above is a real bug that a naive dispatcher reintroduces. Let surfaces that own a combo (find bar, switcher, IME) claim it explicitly rather than relying on propagation.

---

## 12. Desktop gateway layer (boot, request, HMR survival)

### Gateway boot lifecycle (`useGatewayBoot`)  `id: desktop-b.gateway-boot`
- **Surface:** Desktop app
- **Where:** Mounted once by the app root; drives the boot progress the user sees on launch (**“Starting Hermes Desktop…”**, `i18n: boot.steps.startingHermesDesktop`). `apps/desktop/src/app/gateway/hooks/use-gateway-boot.ts:149`.
- **What it does:** Brings up the desktop's connection to a Hermes backend — local, remote, SSH or Nous Cloud — opens the primary WebSocket gateway, loads config and sessions, and then owns reconnection for the life of the app.
- **How it works:** The hook takes six callbacks (`GatewayBootOptions`, `use-gateway-boot.ts:137`): `beforeConnectionSwitch`, `handleGatewayEvent(event)`, `onConnectionReady(connection)`, `onGatewayReady(gateway)`, `refreshHermesConfig(force?, shouldPublish?)` and `refreshSessions(shouldPublish?)`, all kept current in a ref so the effect never re-subscribes. `publish(connection)` (`use-gateway-boot.ts:181`) notifies the callback, writes `$connection`, and tells the Electron main process the active route via `setActiveConnectionRoute({connectionId, profile, registryScoped})`. Boot progress is written into `$desktopBoot` through `setDesktopBootStep` / `applyDesktopBootProgress` / `completeDesktopBoot` / `failDesktopBoot` / `resumeDesktopBootForRetry`, surfacing the step strings **“Starting desktop connection”** (`boot.steps.startingDesktopConnection`), **“Connecting live desktop gateway”** (`boot.steps.connectingGateway`), **“Loading Hermes settings”** (`boot.steps.loadingSettings`), **“Loading recent sessions”** (`boot.steps.loadingSessions`) and **“Reconnecting to the remote Hermes backend…”** (`boot.steps.retryingRemoteBackend`). `primaryRuntimeConnectionId()` (`use-gateway-boot.ts:128`) resolves a connection's runtime id, falling back to the literal `local` for local-mode connections. The hook also configures the multi-connection gateway registry (`configureGatewayRegistry`, `ensureGatewayForProfile`, `closeSecondaryGateways`, `pruneSecondaryGateways`, `reconnectSecondaryGateways`, …) so background profiles keep their own sockets.
- **Inputs / options:** No UI of its own; it reacts to the connection registry, profile switches (`$activeGatewayProfile`, `windowProfileOverride`) and gateway switch requests (`beginGatewaySwitch` / `endGatewaySwitch`).
- **Outputs / side effects:** Opens/closes WebSockets, publishes the active connection, refreshes config and sessions, reconciles busy state on reconnect (`reconcileBusyStatesOnReconnect`), resets tile runtime bindings, and raises toasts.
- **Config / env:** Timeouts and retry policy: `RECONNECT_ESCALATE_AFTER_MS = 300_000` (5 minutes before a *non-blocking* warning toast — deliberately time-based rather than attempt-count, because full-jitter backoff makes attempt counts a meaningless clock, and deliberately 5 min rather than the historical ~45 s so ticket-mint flaps, sleep/wake and 1–3 minute Wi-Fi blips never even toast, `use-gateway-boot.ts:94`); `GATEWAY_LIVENESS_PROBE_TIMEOUT_MS = 5_000` for the sleep/wake liveness probe, kept independent of the 30-minute prompt-submit timeout that is correct for an in-flight turn but must never be what a dead connection burns; `BOOT_RETRY_MAX_ATTEMPTS = 5` and `BOOT_RETRY_BASE_DELAY_MS = 2_000` for the bounded self-heal of a failed **remote** boot (slower than the socket loop's 300 ms because each attempt may rebuild an SSH master plus a remote dashboard); plus `BACKEND_BOOT_WAIT_TIMEOUT_MS` and `RECONNECT_ATTEMPT_TIMEOUT_MS` from `lib/with-timeout`.
- **Edge cases / guards:** No `window.hermesDesktop` bridge fails the boot with **“Desktop IPC bridge is unavailable.”** (`boot.errors.ipcBridgeUnavailable`) and clears the sessions-loading flag. A reauth-required error toasts **“Gateway sign-in required”** (`boot.errors.gatewaySignInRequired`). A long-failing reconnect toasts **“Lost connection to the gateway”** with **“Still retrying in the background. You can keep reading and drafting — open Gateway settings if this persists.”** (`boot.errors.gatewayConnectionLost` / `gatewayConnectionLostDetail`) — deliberately a toast, because the old full-screen overlay locked the user out of reading and drafting during a blip even though the transcript was still on screen; only a **confirmed** reauth escalates to the boot-failure overlay. A backend process that exits raises **“Backend stopped”** / **“Hermes background process exited.”** (`boot.errors.backendStopped` / `backgroundExited`), or **“Hermes background process exited during startup.”** (`backgroundExitedDuringStartup`) if it dies mid-boot. Any other failure toasts **“Desktop boot failed”** (`boot.errors.desktopBootFailed`), with the detailed form **“Desktop boot failed: {message}”** (`boot.desktopBootFailedWithMessage`). Success sets **“Hermes Desktop is ready”** (`boot.ready`). Remote boot retries only fire for faults the main process tagged `retryable`; local failures and confirmed reauth rejections never enter the loop, because a missing capability differs from a transient failure (comment at `use-gateway-boot.ts:112`). A liveness probe **timeout** alone no longer tears the socket down mid-turn: while a turn is in flight the first timeout defers behind one bounded re-probe (`decideLivenessForceClose`, `LIVENESS_REPROBE_DELAY_MS`), so only a *streak* of unanswered pings rebuilds the transport. Every long await is bounded, because a pending unbounded await would latch `reconnecting` forever and leave the UI stuck on “reconnecting” until restart even after the gateway came back (comment at `use-gateway-boot.ts:120`).
- **Rebuild notes:** Bound every IPC await, escalate on *elapsed time* not attempt count, never block the transcript behind a reconnect, and separate “transport unhealthy” from “credentials expired”.

### Gateway request helper (`useGatewayRequest`)  `id: desktop-b.gateway-request`
- **Surface:** Desktop app
- **Where:** Used by every feature that issues a JSON-RPC call over the live socket (pet generation, composer actions, session actions, …). `apps/desktop/src/app/gateway/hooks/use-gateway-request.ts:11`.
- **What it does:** Provides `requestGateway(method, params, timeoutMs?, signal?)`, which transparently reconnects and retries once when the call fails with a transport error.
- **How it works:** It exposes both a **ref** (`gatewayRef`, stable identity, always the live socket) and a **reactive value** (`gateway` from `useStore($gateway)`), because the ref is only populated by the subscription effect — i.e. after the first render — so a component that reads `gatewayRef.current` during render would see `null` on mount and might never re-render to pick it up; anything needing the gateway as a render-time value (props, memo deps) must use the reactive one (comment at `use-gateway-request.ts:13`). On a transport failure the primary connection takes the OAuth-aware `ensureGatewayOpen()` path — re-reading the connection for **whichever profile the gateway is currently routed to** (so a sleep/wake reconnect keeps the user on the profile they were chatting in) and re-minting the WebSocket URL with `resolveGatewayWsUrl()`, because OAuth tickets are single-use and short-lived so the cached `conn.wsUrl` ticket is already dead. Background profiles instead use the registry's connection-owned `ensureActiveGatewayOpen()`, which covers composite remote/SSH sources. Concurrent reconnects share one promise via `reconnectingRef`.
- **Inputs / options:** `requestGateway<T>(method, params = {}, timeoutMs?, signal?)`. The hook returns `{connectionRef, gateway, gatewayRef, requestGateway}`.
- **Outputs / side effects:** Sets `$connection` on reconnect; throws `Hermes gateway unavailable` when no socket exists at all.
- **Config / env:** Both reconnect awaits are bounded by `RECONNECT_ATTEMPT_TIMEOUT_MS` with the messages `Timed out reconnecting to Hermes backend` and `Timed out re-minting the gateway WebSocket URL` — without them a wedged main-process IPC round-trip would hang forever and latch `reconnectingRef`, so every later call would return the same never-settling promise (comment at `use-gateway-request.ts:76`).
- **Edge cases / guards:** `isGatewayTransportError()` (`use-gateway-request.ts:189`) treats a message matching `/not connected|connection closed|connection reset|ECONNRESET/i` as transport, or an error (or its `cause`) whose `code` is one of `ECONNABORTED`, `ECONNREFUSED`, `ECONNRESET`, `EHOSTUNREACH`, `ENETUNREACH`, `ENOTFOUND`, `EPIPE`, `ETIMEDOUT`, `ERR_NETWORK`, `ERR_SOCKET_CLOSED` (`GATEWAY_TRANSPORT_ERROR_CODES`, `use-gateway-request.ts:166`). Non-transport errors are re-thrown untouched. When a reconnect fails, a stashed reauth error (OAuth session expired) is preferred over the generic transport error that triggered the retry, so the user sees the actionable “sign in again” message.
- **Rebuild notes:** Retry exactly once, only on transport errors, and re-mint single-use credentials on every reconnect.

### Gateway HMR survivor  `id: desktop-b.gateway-hmr-survivor`
- **Surface:** Desktop app (development only)
- **Where:** `apps/desktop/src/app/gateway/hooks/gateway-hmr-survivor.ts`.
- **What it does:** Keeps the live primary gateway socket alive across a Vite hot-module reload, so editing UI code never drops the agent session.
- **How it works:** One slot on `globalThis`, keyed by `Symbol.for('hermes.desktop.gatewaySurvivor')` so repeated imports across hot reloads resolve the exact same store. `stashGatewaySurvivor({gateway, profile, connection})` parks it on dispose; `takeGatewaySurvivor()` is single-shot and clears the slot on read; `survivorIsStale(survivor)` returns true when the parked socket's `connectionState` is neither `open` nor `connecting`, so the caller can close it and boot fresh (e.g. after a backend restart between edits). The module self-accepts (`import.meta.hot.accept()`) so editing it does not blow away the cache it manages.
- **Inputs / options:** n/a (module API).
- **Outputs / side effects:** Holds a socket reference on `globalThis`.
- **Config / env:** Production builds strip `import.meta.hot`, leaving live unmount byte-for-byte unchanged.
- **Edge cases / guards:** A stale survivor is still *returned* rather than silently dropped, so the caller owns the close.
- **Rebuild notes:** n/a

---

## 13. `contrib` — the contribution-driven shell wiring

### Contribution controller (`ContribController`)  `id: desktop-b.contrib-controller`
- **Surface:** Desktop app
- **Where:** The app root renders it; it is the only public entry of `apps/desktop/src/app/contrib` (`index.ts:6`). Source `apps/desktop/src/app/contrib/controller.tsx`.
- **What it does:** Registers every built-in pane, layout preset, chrome slot, palette command and keybind through the same contribution registry that plugins use, then mounts the layout tree that becomes the window.
- **How it works:** `registry.registerMany([...])` declares the five core panes (`controller.tsx:155`): **`sessions`** (`placement: 'left'`, `collapsible`, `dock: {pane:'workspace', pos:'left'}`, `revealAliases: ['chat-sidebar']`, `hideOnly: true` — standing chrome with no close gesture, only Show/Hide — sized `SIDEBAR_DEFAULT_WIDTH`…`SIDEBAR_MAX_WIDTH`); **`workspace`** (`placement: 'main'`, `minWidth: '22vw'`, `uncloseable`, a custom `tabDrag`/`tabWrap`, live-retitled to the loaded session, default title `NEW_SESSION_TITLE`); **`terminal`** (`placement: 'bottom'`, `height: '20vh'`, `maxHeight: '80vh'`, `revealOnPreset: true` so choosing the "Terminal deck" layout also turns takeover on, `lifecycleKeepAlive: true`, and deliberately **no** `minHeight` so the sash can fold the zone to its rail instead of leaving an unusable sliver); **`files`** (`placement: 'right'`, collapsible, `dock` beside workspace on the right, `revealAliases: ['file-browser']`, `FILE_BROWSER_*` widths); and **`review`** (`placement: 'right'`, collapsible, `revealAliases: [REVIEW_PANE_ID]`, hidden until ⌘G). Four layout presets are registered in the `layouts` area (`controller.tsx:436`): **“Default”** (order 0), **“Focus”** (10), **“Terminal deck”** (20), **“Quad”** (30). The default tree is `split('row', [sessions | workspace | split('column', [split('row',[review, files],[1,1.2]), terminal],[1.6,1])], [1, 3.4, 1.25])` — sessions left, chat main, then review and files as their own zones (files outermost) over the terminal (`controller.tsx:389`). Pane visibility is bound to real stores: `sessions` ↔ `$sidebarOpen`, `files` ↔ `$fileBrowserOpen`, `review` ↔ `$reviewOpen && $hasWorkspace`, and the terminal uses `bindToolPaneCollapse` with `$terminalTakeover` so ⌃` collapses it to a rail (the tab stays and PTYs stay alive) instead of hiding it. Bundled plugins are discovered **after** core (`discoverBundledPlugins`, `discoverRuntimePlugins`), so a same-id plugin contribution deliberately overrides the core default (last writer wins).
- **Inputs / options:** Palette commands registered here (all through `paletteToggle`, so each shows on/off state): **“Toggle layout edit mode”** (`layout.editMode`), **“Reload desktop plugins”** (`plugins.reload`), **“Reset layout”** (`layout.reset`), **“Toggle status bar”** (`view.toggleStatusbar`), **“Toggle tabs”** (`view.toggleTabStrip`), **“Keyboard shortcuts”** (`keybinds.panel`), **“Export profile…”** (`profile.export` → `runExportProfileFlow`), **“Import profile…”** (`profile.import` → `runImportProfileFlow`), **“Toggle terminal”** (`view.showTerminal`, icon `Terminal`, keywords `terminal, shell, console, pty`), **“Toggle logs”** (`logs.toggle`, icon `FileText`, keywords `logs, agent log, tail, debug`), **“Toggle yolo”** (`session.yolo`, icon `Zap`, keywords `yolo, approvals, auto-approve, bypass, dangerous, commands`), plus one auto-generated **“Show/Hide {title}”** row per `hideOnly` pane (`zones.toggleStripTab`, icon `LayoutDashboard`). Also a transcript-directive contribution `transcript.preview` (`InlinePreviewDirective`).
- **Outputs / side effects:** Mutates the layout tree store, opens/closes panes, toggles YOLO through `setYoloEnabled`, runs the profile export/import flows.
- **Config / env:** Layout trees persist through the pane-shell tree store; `$logsOpen` is deliberately **session-only** (not persisted) so a fresh boot never re-opens logs.
- **Edge cases / guards:** Every pane toggle reads **on-screen truth** (`isPaneVisible(id)`), not the store boolean: `$terminalTakeover` and `$logsOpen` stay true behind a stacked sibling tab or a minimised zone, which would light the palette row “on” for a pane that is not visible and make the press a no-op (comments at `controller.tsx:619` and `:697`). `sessions` / `files` Close collapses their root *side* only while the pane actually lives in that side column; dragged next to main it falls back to dismissal, or ⌘W/Close would silently no-op (`controller.tsx:781`). Turning logs off also sweeps a stale `logs` pane out of a persisted tree, guarded so a no-op boot sweep does not commit a fresh identical tree.
- **Rebuild notes:** Register the app's own UI through the same plugin API you expose — it is the only way to be sure the plugin surface is real.

### Wired-surface bridge (`WiredPane` / `ContribWiringContext`)  `id: desktop-b.contrib-wired-pane`
- **Surface:** Desktop app
- **Where:** Inside every registered pane and chrome slot. `apps/desktop/src/app/contrib/context.tsx:106`.
- **What it does:** Lets a declaratively-registered pane render one of the four data-wired surfaces (`sidebar`, `chatRoutes`, `terminal`, `statusbar`) that the controller publishes.
- **How it works:** The controller publishes a `WiringApi` (`contrib/types.ts:81`) into `ContribWiringContext`; `WiredPane` is memoised on its single `part` prop, so a zone re-rendering for reasons that do not touch the wiring — a drag hint sweeping the tree, a sash resize, an edit-mode toggle — re-renders the group chrome but not the expensive pane body.
- **Inputs / options:** `part: 'sidebar' | 'chatRoutes' | 'terminal' | 'statusbar'`.
- **Outputs / side effects:** Rendering only.
- **Config / env:** n/a
- **Edge cases / guards:** With no wiring yet, `statusbar` renders an empty `StatusbarControls` and every other part renders a centred `DecodeText` reading **“HERMES”** with a cursor.
- **Rebuild notes:** n/a

### Wiring surfaces (sidebar / chat routes / terminal / statusbar)  `id: desktop-b.contrib-surfaces`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/surfaces.tsx`.
- **What it does:** Splits the app into four independently-rendered surfaces so a state change scoped to one never re-renders another.
- **How it works:** Each surface is its own `memo` component that subscribes to the reactive state it renders **at the leaf**, and reaches controller callbacks through a stable `actions` bag (`surfaces.tsx:123`). `SidebarSurface` renders `ChatSidebar`; `TerminalSurface` renders `TerminalPaneChrome`; `StatusbarSurface` owns the statusbar's own data hooks (a 15 s status-snapshot poll plus contributed items) so that churn re-renders the bar alone; `ChatRoutesSurface` is the real route table. `ChatRoutesSurface` mounts `ChatView` at both `index` and `:sessionId`, three lazily-imported full pages at `skills`, `messaging` and `artifacts` (each handed `setStatusbarItemGroup`), and **null** elements for the overlay routes `agents`, `command-center`, `cron`, `profiles`, `settings`, `starmap`, `webhooks` (they render as overlays above the shell, not in the pane). Registry-contributed routes render inside a `ContribBoundary` blast wall. `new` redirects to `NEW_CHAT_ROUTE`, `sessions/:sessionId` goes through `LegacySessionRedirect`, and `*` redirects to `NEW_CHAT_ROUTE`.
- **Inputs / options:** n/a (structural).
- **Outputs / side effects:** Rendering; the statusbar surface issues the status-snapshot poll keyed by `"{connectionId}\0{profile}"`.
- **Config / env:** n/a
- **Edge cases / guards:** A full page is not a tab-able surface, so the zone's tab strip stands down through the contribution's `paneChrome.headerVeto` rather than a DOM marker (the old `data-zone-no-header` attribute gated a body double-click toggle that no longer exists and nothing has read it since, comment at `surfaces.tsx:272`).
- **Rebuild notes:** Subscribe at the leaf and pass a stable action bag — this is what makes independent zone rendering possible.

### `latestChatActions` / `latestSidebarActions`  `id: desktop-b.contrib-latest-actions`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/latest-actions.ts`.
- **What it does:** Wraps the controller's callback bag so memoised children always call the newest closure without re-rendering on identity churn.
- **How it works:** The controller mutates the fields of one stable `actions` object each render. A memoised surface that passed `actions.foo` directly would hand its child the function from its own last render, which can submit or click against a **stale session closure**. Each wrapper therefore keeps a stable identity but dereferences the latest field at call time. `latestOptional()` (`latest-actions.ts:20`) preserves *optionality*: several children gate on a handler's presence, not just call it — `onDismissError` renders the dismiss button only when it exists (`assistant-message.tsx`), `onRestoreToMessage` gates the restore-confirm flow (`thread/index.tsx`), and `onTranscribeAudio` gates voice recording and voice conversation — so an unconditional arrow wrapper (always truthy) would render a dead dismiss button and let voice recording proceed with no transcription backend.
- **Inputs / options:** Chat actions wrapped: `onAddContextRef`, `onAddUrl`, `onAttachDroppedItems`, `onAttachImageBlob`, `onBranchInNewChat` (optional), `onCancel`, `onDeleteSelectedSession`, `onDismissError` (optional), `onEdit`, `onPasteClipboardImage`, `onPickFiles`, `onPickFolders`, `onPickImages`, `onReload`, `onRemoveAttachment`, `onRestoreToMessage` (optional), `onRetryResume`, `onSteer`, `onSubmit`, `onThreadMessagesChange`, `onToggleSelectedPin`, `onTranscribeAudio` (optional). Sidebar actions wrapped: `onArchiveSession`, `onBranchSession`, `onDeleteSession`, `onLoadMoreMessaging` (optional), `onLoadMoreSessions`, `onManageCronJob`, `onNavigate`, `onNewSessionInWorkspace`, `onNewSessionSplit`, `onResumeSession`, `onTriggerCronJob`. (The full controller-owned surface also carries `getGateway`, `openAgents`, `openCommandCenterSection`, `requestGateway`, `selectModel` and `toggleCommandCenter`, `contrib/types.ts:68`.)
- **Outputs / side effects:** None of its own.
- **Config / env:** n/a
- **Edge cases / guards:** Presence is sampled from the object the surface currently holds; the controller mutates fields in place rather than swapping a handler between defined and undefined, so presence is stable while the closure churns.
- **Rebuild notes:** n/a

### Logs pane  `id: desktop-b.contrib-logs-pane`
- **Surface:** Desktop app
- **Where:** Summoned only by the ⌘K command **“Toggle logs”**; it then appears as its own zone docked to the right of the terminal.
- **What it does:** Tails the live agent log.
- **How it works:** `LogsPane` (`apps/desktop/src/app/contrib/panes.tsx:36`) polls `getLogs({lines: 300})` every 5000 ms under React-Query key `['contrib-logs-tail']` and renders the joined lines in a mono `<pre>` with no chrome of its own. The pane **contribution itself** only exists while `$logsOpen` is true, so off (the default) keeps logs out of the registry and the layout tree entirely — no secondary tab riding the terminal strip, no preset or adoption path that resurrects it (comment at `controller.tsx:637`). Summoning it also calls `revealTreePane('logs')` so an earlier ✕ dismissal is undone.
- **Inputs / options:** The palette toggle; the tab ✕, ⌘W and the toggle itself all remove it (through `registerPaneCloser`/`registerPaneOpener` so the palette row stays truthful).
- **Outputs / side effects:** Reads the agent log over the API.
- **Config / env:** Sizing `height: '20vh'`, `maxHeight: '80vh'`, no `minHeight`; `dock: {pane: 'terminal', pos: 'right'}` — its own zone beside the terminal, never a tab in the terminal's strip.
- **Edge cases / guards:** A query error renders `log unavailable: {error}`; before the first response a `DecodeText` reading **“LOGS”**.
- **Rebuild notes:** n/a

### Files, Preview and Review panes  `id: desktop-b.contrib-data-panes`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/panes.tsx`.
- **What it does:** Supplies the real data bodies for the file-browser, preview and review panes.
- **How it works:** `FilesPane` renders the real `RightSidebarPane` and wires both `onActivateFile` and `onActivateFolder` to `previewFile(path)`, which normalises the path with `normalizeOrLocalPreviewTarget(path, $currentCwd)` and calls `openPreview(target, 'file-browser')` (`panes.tsx:74`). `ReviewPaneContent` renders the real `ReviewPane` **keyed by cwd** so switching projects rebuilds the diff state instead of showing the previous repo's files. The preview rail's server-restart handler is bridged through the atom `$restartPreviewServer` because this module cannot import the wiring (the wiring imports it). A shared `ZONE_CONTENT` class handles sizing for wrapped `<aside>` bodies; edge chrome (borders/shadows) is neutralised globally by the tree's seam invariant.
- **Inputs / options:** File/folder activation in the tree.
- **Outputs / side effects:** Opens a preview target.
- **Config / env:** n/a
- **Edge cases / guards:** A path that cannot be normalised is silently ignored.
- **Rebuild notes:** n/a

### Statusbar contributions  `id: desktop-b.contrib-statusbar`
- **Surface:** Desktop app
- **Where:** The window's status bar; contribution areas `statusBar.left` and `statusBar.right`.
- **What it does:** Lets plugins add status-bar items — declarative data items or arbitrary rendered nodes — beside the core items.
- **How it works:** `useStatusbarContributions(side)` (`apps/desktop/src/app/contrib/panes.tsx:113`) collects contributions for one side; a contribution with a `render()` becomes a render-item (an arbitrary stateful node), otherwise the declarative `StatusbarItem` payload is used. The wiring feeds them into the real `useStatusbarItems` as `extraLeftItems` / `extraRightItems`. There is deliberately no core filler here — the real status bar owns the core items (model pill, terminal toggle, …). `setStatusbarItemGroup` is the group setter handed to the full-page views so they can publish their own status-bar group.
- **Inputs / options:** Registry contributions.
- **Outputs / side effects:** Renders extra status-bar items.
- **Config / env:** n/a
- **Edge cases / guards:** Contributed nodes render behind the contribution blast wall.
- **Rebuild notes:** n/a

### MCP install deep-link confirmation (`hermes://mcp/install`)  `id: desktop-b.contrib-mcp-deeplink`
- **Surface:** Desktop app
- **Where:** A modal raised by the `hermes://mcp/install` deep link. Title **“Add MCP server?”** (`i18n: settings.mcp.deepLinkTitle`), description **“A link asked to add this MCP server to Hermes. Review the exact configuration below — it comes from the link, not from Hermes.”** (`settings.mcp.deepLinkDescription`). Component `apps/desktop/src/app/contrib/mcp-install-deeplink-dialog.tsx:35`.
- **What it does:** Shows exactly what a deep link wants to add to `mcp.json` and writes nothing until the user explicitly confirms.
- **How it works:** The payload is arbitrary attacker-controllable input (any web page can open the link), so the dialog shows the server name and the **full pretty-printed config** — precisely what would be written (comment at `mcp-install-deeplink-dialog.tsx:25`). On open it seeds the editable name from the request and fetches the current server map so a same-name conflict is visible **before** confirming. On confirm it re-fetches the freshest config and merges over it, because `saveMcpServers` replaces the entire `mcp_servers` document and saving over a stale snapshot would drop servers added elsewhere since the dialog opened (`mcp-install-deeplink-dialog.tsx:103`). After a successful save it writes through `setHermesConfigCache` and navigates to `/skills?tab=mcp&server=<name>`.
- **Inputs / options:** A **“Name”** (`settings.mcp.name`) input; a read-only **“Server JSON”** (`settings.mcp.serverJson`) `<pre>` (max height 16 rem, scrollable); footer buttons **“Cancel”** (`common.cancel`) and **“Add server”** (`settings.mcp.deepLinkConfirm`) / **“Saving...”** (`common.saving`) — the confirm button is rendered `destructive` for a stdio transport and `default` otherwise.
- **Outputs / side effects:** Writes one new entry into `mcp_servers` and toasts **“MCP server saved”** with **“{name} applies after MCP reload.”** (`settings.mcp.savedTitle` / `savedMessage`).
- **Config / env:** `mcp_servers.<name>`.
- **Edge cases / guards:** A `stdio` (`command`) entry shows an extra destructive caution banner: **“This server runs a local process on your machine with the command shown below. Only continue if you trust its source.”** (`settings.mcp.deepLinkStdioWarning`). The name must match `MCP_DEEPLINK_NAME_RE` or the dialog shows **“Names use 1-64 letters, digits, dots, dashes, or underscores.”** (`deepLinkNameInvalid`); an existing name is **never** silently overwritten — confirm stays blocked with **“A server named {name} already exists — choose a different name or cancel.”** (`deepLinkNameConflict`). Confirm is also blocked while the conflict preflight is still running; if that preflight fails (offline backend) the dialog stays usable because confirm re-fetches and merges anyway. The dialog cannot be dismissed while saving. Related deep-link rejection strings, raised before the dialog ever opens: **“MCP install link rejected”** (`deepLinkErrorTitle`), **“The link's server name is missing or invalid.”** (`deepLinkErrorName`), **“The link's config is not valid base64-encoded JSON.”** (`deepLinkErrorConfig`), **“The config must be a JSON object with a string `url` or `command` field.”** (`deepLinkErrorShape`), **“Only http:// and https:// server URLs are allowed.”** (`deepLinkErrorUrl`), **“The config payload exceeds the 32KB limit.”** (`deepLinkErrorTooLarge`).
- **Rebuild notes:** Show the literal bytes that will be written, block on name collision, and re-read before merging into a whole-document save.

### Desktop OS integrations (`useDesktopIntegrations`)  `id: desktop-b.contrib-desktop-integrations`
- **Surface:** Desktop app
- **Where:** Mounted by the wiring controller. `apps/desktop/src/app/contrib/hooks/use-desktop-integrations.ts:56`.
- **What it does:** Owns every Electron-main / OS / cross-window integration the shell listens for, kept in one unit so the “talks to the desktop shell” surface reads as one file.
- **How it works:** Covers update polling (`startUpdatePoller` / `stopUpdatePoller`, `openUpdatesWindow`), the ⌘W close shortcut routed from the macOS menu accelerator through IPC into `closeActiveTab`, deep links (`resolveDeepLinkAction`, `pathFromHermesDeepLink`, `resolveHermesOpenPath`, `requestMcpInstallFromDeepLink`, `openPluginInstallRequest`, `openFolderAsProject`), native-notification navigation (`storedSessionIdForNotification`, `respondToApprovalAction`, `invokePluginNotifyAction`, `invokePluginNotifyActivate`, `clearPluginNotifyHandlers`), preview-shortcut enablement (`commandFocusedPreview`), remembered-session restore (`getRememberedSessionId` / `setRememberedSessionId`, `getRememberedRoute` / `setRememberedRoute`, `sessionBelongsToProfile`), the MCP health checker (`startMcpHealthChecker` / `stopMcpHealthChecker`), and cross-window session-list sync (`onSessionsChanged`).
- **Inputs / options:** `{activeProfile, chatOpen, hasPreview, locationPathname, navigate, profileReady, refreshSessions, resumeExhaustedSessionId, routedSessionId, runtimeIdByStoredSessionId, sessions}`.
- **Outputs / side effects:** Navigation, session restore, notification responses, MCP health toasts (**“MCP server needs re-authentication”** / **“{name} MCP needs re-authentication.”** and **“MCP server unreachable”** / **“{name} MCP failed its health check.”** with actions **“Sign in”** and **“View”**, `notifications.mcp.*`).
- **Config / env:** n/a
- **Edge cases / guards:** Secondary, browser and HUD windows are excluded from the integrations they must not claim (`isSecondaryWindow`, `isBrowserWindow`, `isHudWindow`).
- **Rebuild notes:** Keep all OS-facing listeners in one hook so their lifetimes are visibly paired.

### Quick Entry bridge  `id: desktop-b.contrib-quick-entry-bridge`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/hooks/use-quick-entry-bridge.ts:53`; the UI is the global-hotkey Quick Entry window.
- **What it does:** Routes text captured in the global Quick Entry window into this window's normal prompt machinery, and pushes connection state plus a recent-session list back out so that window can disable its input.
- **How it works:** Inbound, by target: `QUICK_TARGET_NEW` starts a fresh draft and submits — exactly what clicking New Chat and typing does; `QUICK_TARGET_CURRENT` submits into the current chat; any other target is a stored session id, which is resumed and submitted **in the background** through the session-tile delegate (`resumeTile` → `submitToSession`), leaving the primary view where it is — the same path tiled sessions use. Outbound, `window.hermesDesktop.quickEntry.pushState({connected, sessions})` is called on mount and on every `$gatewayState` / `$sessions` change; the picker gets at most `QUICK_ENTRY_SESSION_OPTIONS = 5` non-archived rows, each labelled `title` → `preview` → `id`, because “the picker is a capture aid, not a session browser”.
- **Inputs / options:** n/a from this side (the Quick Entry window owns its own UI).
- **Outputs / side effects:** Submits prompts; pushes state to the quick window.
- **Config / env:** n/a
- **Edge cases / guards:** Handlers register **once** through refs tracking the latest callbacks — re-registering on identity churn would leave a nulled-handler window that can drop a submit (the same bug shape `use-pet-bridge` guards). Primary window only (`isAuxiliaryWindow()` returns early): a secondary session window must not also claim the global capture channel, or one keystroke would send N prompts. A dead or undeliverable delegate target falls back to submitting into the current chat rather than swallowing the prompt.
- **Rebuild notes:** One submit pipeline, no bespoke RPC — route by target into the code paths the UI already uses.

### Pet overlay bridge  `id: desktop-b.contrib-pet-bridge`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/hooks/use-pet-bridge.ts:25`.
- **What it does:** Wires the popped-out pet overlay back into the app — submitting a prompt, persisting a resize, opening the most recent thread — and mirrors “a session is waiting on you” into the pet's pose.
- **How it works:** Registers three handlers on the pet-overlay store: `setPetOverlaySubmitHandler(text => submitText(text))`; `setPetOverlayScaleHandler(scale => setPetScale(requestGateway, scale))` — the Alt+wheel resize is persisted through **this** window's gateway because the overlay has none, so it survives a restart; and `setPetOverlayOpenAppHandler` which resumes `$sessions.get()[0]` (the list is most-recent-first, and the pet is global, so “most recent” is the right target). A second effect mirrors `$attentionSessionIds.length > 0` into `setPetActivity({awaitingInput})` so the pet shows its `waiting` pose while a clarify or approval is blocking.
- **Inputs / options:** `{requestGateway, resumeSession, submitText}`.
- **Outputs / side effects:** Prompt submission, scale persistence, session resume, pet pose.
- **Config / env:** n/a
- **Edge cases / guards:** Same once-only ref registration and primary-window-only guard as the Quick Entry bridge.
- **Rebuild notes:** n/a

### Session-scoped RPC dispatcher  `id: desktop-b.contrib-session-rpc-dispatcher`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/session-rpc-dispatcher.ts` — the window's single session-scoped RPC router, factored out of the wiring controller so integration tests drive the exact production routing.
- **What it does:** Sends every session RPC to the backend that **owns** that session, rather than to whatever tile happens to be focused.
- **How it works:** `params.session_id` is a **runtime** id while tiles and session rows key on the **stored** id, so the dispatcher translates first through a ladder: the state cache, then a reverse scan of the stored→runtime map, then the persisted tile map (the rung that survives a reload when the state cache is cold). A miss on all rungs means the id is already a stored id — several RPCs pass stored ids directly — so it is used as-is. Only an RPC with **no** `session_id` at all (ambient/config calls) keeps the focused-tile route. Owner resolution is `resolveSessionRpcOwner`: the tile route → an exact unique owner hint → the row's owner (exact when connection-tagged, else its profile), then a cross-profile REST probe for a hidden or unlisted session.
- **Inputs / options:** `(method, params?, timeoutMs?, signal?)`.
- **Outputs / side effects:** Issues the RPC on the owning backend's socket.
- **Config / env:** n/a
- **Edge cases / guards:** A request whose session owner still cannot be named **fails closed** with an explicit `SessionOwnerResolutionError` rather than riding the ambient socket — the single exception being the legacy single-backend desktop, where ambient *is* the owner. The bug this prevents is concrete: keying the owner off `$focusedStoredSessionId` sent a non-focused tile's RPC (any bot chat while another pane is active) to the focused tile's backend, so a bot's `prompt.submit` carried its own `session_id` but ran on the default backend — served via `?profile=` out of the default's `state.db` — or returned 4001 when the default backend did not hold the runtime session (comment at `session-rpc-dispatcher.ts:6`).
- **Rebuild notes:** Route by ownership, never by focus; make “owner unknown” an error, not a silent fallback.

### Background transcript sync  `id: desktop-b.contrib-background-sync`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/hooks/use-background-sync.ts`.
- **What it does:** Keeps the persisted transcript of every open workspace tile — and the active chat — reconciled with the backend, without disturbing a live stream.
- **How it works:** `resolveActiveTranscriptSession(storedSessionId)` (`use-background-sync.ts:41`) resolves an active transcript from the visible session rows, then the messaging rows, then a unique hidden owner hint. Refreshes call `getLatestSessionMessages`, convert with `toChatMessages`, graft the refreshed tail onto any backfilled history (`graftRefreshedTailOntoBackfill`), preserve local assistant errors (`preserveLocalAssistantErrors`) and seal open tool parts (`sealOpenToolParts`) before publishing. A `sessionMessagesSignature` comparison suppresses no-op republishes, and a monotonically increasing `requestSequenceRef` discards out-of-order replies. Cadence is event-driven where possible (`$changeEventsAvailable` with `$sessionsChangeTick` / `$cronChangeTick`) and falls back to polling; `$onBattery` + `batteryPollInterval` slow the poll on battery power. `SESSION_WATCHDOG_TIMEOUT_MS` and `setSessionStalled` mark a session whose stream went quiet.
- **Inputs / options:** Refs for the active session id, busy flag, selected stored id, the signature map and the session-state updater.
- **Outputs / side effects:** Publishes reconciled session state; refreshes the active profile and current cwd.
- **Config / env:** n/a
- **Edge cases / guards:** Never clobbers a busy/streaming session; battery-aware polling; sequence-guarded publishes.
- **Rebuild notes:** Reconcile by signature and sequence, and prefer change events to polling.

### Session tile delegate  `id: desktop-b.contrib-tile-delegate`
- **Surface:** Desktop app
- **Where:** `apps/desktop/src/app/contrib/hooks/use-session-tile-delegate.ts`.
- **What it does:** Exposes the operations a *non-focused* session tile needs — resume, submit, archive, branch, remove, run a slash command — so background surfaces (tiles, Quick Entry, the pet overlay) can act on a session without stealing the primary view.
- **How it works:** `setSessionTileDelegate({...})` publishes the delegate into `store/session-states`. Resumes go through `singleFlightSessionResume` so two callers cannot double-resume, `withSessionNotFoundResume` retries a vanished runtime session, and `markSessionRecentlyInterrupted` records interruptions. Ownership is resolved with `resolveSessionOwner` / `sessionTileOwnerRoute` / `knownSessionOwner` and asserted by `assertSessionOwnerResolved`; requests are routed with `requestForSessionProfile`. A resumed transcript is merged by `mergeTileTranscript()` (`use-session-tile-delegate.ts:34`), which converts the prefetch, grafts it onto the existing backfill and reconciles with `reconcileResumeMessages`; `chatMessageArraysEquivalent` suppresses an identical republish.
- **Inputs / options:** `{archiveSession, branchStoredSession, executeSlashCommand, removeSession, requestGateway, runtimeIdByStoredSessionIdRef, sessionStateByRuntimeIdRef, updateSessionState}`.
- **Outputs / side effects:** Resumes and submits on the owning backend; publishes tile session state.
- **Config / env:** `PROMPT_SUBMIT_REQUEST_TIMEOUT_MS` bounds a submit.
- **Edge cases / guards:** A session no backend claims falls back to a read-only transcript (`readOnlyRuntimeIdFor`, `isReadOnlyRuntimeId`, `resumeWithStoredTranscriptFallback`) and the user is told through the read-only notice (**“Opened read-only”** / **“No connected backend claims this older chat yet, so it opened as a read-only transcript. Its history is intact; sending is disabled until a backend claims it.”**, `desktop.readOnlyTranscriptTitle` / `readOnlyTranscriptBody`).
- **Rebuild notes:** Give background surfaces a first-class delegate instead of letting them drive the focused view.

---

## 14. Chat composer

### Composer (ChatBar)  `id: desktop-b.composer`
- **Surface:** Desktop app
- **Where:** The message box at the bottom of every chat surface (main workspace, each session tile, the HUD bar, the popped-out floating composer). `data-slot="composer-root"` / `data-slot="composer-surface"`. Component `ChatBar`, `apps/desktop/src/app/chat/composer/index.tsx:89`.
- **What it does:** The single input for talking to Hermes: rich text with reference chips, attachments, slash commands, @-mentions, emoji, voice, a queue for follow-ups, steering a live turn, and every status strip that hangs off it.
- **How it works:** A `contentEditable` rich editor (`data-slot` = `RICH_INPUT_SLOT`) is the real input; assistant-ui's `ComposerPrimitive.Input` is rendered `sr-only` with `asChild` over a plain `<textarea>` purely to carry the composer-state binding — the default `TextareaAutosize` is deliberately swapped out because it runs `useLayoutEffect(resizeTextarea)` on every value change against a hidden measurement textarea, forcing two synchronous layouts per keystroke (>900 ms cumulative, ~2.3 ms/key, on 400-char synthetic typing) for an element nobody can see (comment at `composer/index.tsx:1084`). The DOM is the source of truth; `flushEditorToDraft()` normalises the DOM, serialises it with `composerPlainText`, sanitises it and writes `draftRef` + the AUI composer state, and `scheduleFlushEditorToDraft()` coalesces the high-frequency input/paste flushes to one per animation frame because `composerPlainText` is O(n) and a held key would make a burst O(n²) (`composer/index.tsx:411`). The whole feature is decomposed into hooks: `useComposerScope` (which composer this is — `main` or a tile — and its attachment set), `useComposerDraft` (the detached draft engine, so typing never re-renders chrome), `useComposerUndo` (an owned undo stack, because the rich editor bypasses Chromium's editing pipeline), `useComposerQueue`, `useComposerSubmit`, `useComposerTrigger` (+ `useAtCompletions`, `useSlashCompletions`, `useEmojiCompletions`), `useComposerVoice`, `useComposerPopout`, `useComposerDrop`, `useComposerMetrics`, `useComposerPlaceholder`, `useComposerUrlDialog`, `useComposerBranch`, `useComposerEscCancel`, `useComposerMicroActions`, `useSessionStatusPresence`. Every send — typed, queued or voice — first passes through the contributed middleware chain `runComposerMiddleware({text, attachments})`, which can rewrite, pass through or cancel; an empty chain is a byte-identical pass-through (`composer/index.tsx:148`).
- **Inputs / options:** The rich input itself (`aria-label` **“Message”**, `i18n: composer.message`; `spellCheck` off, `autoCapitalize`/`autoCorrect` off); the `+` context menu; the controls row (model pill, voice controls, queue, send/stop); the attachment list; the trigger popover; the queue panel; the status stack; the coding status row; four contribution slots (`COMPOSER_AREAS.top`, `.leading`, `.actions`, `.bottom`) plus an `underside` strip. Layout adapts through `useComposerMetrics`: `stacked` puts the input on its own row above `[menu | controls]`, `compactPill` shortens the model pill, `foldVoice` collapses the voice buttons into one menu, and `minimal` reduces the row to the send button alone — “the one thing that must survive every width” (`controls.tsx:80`).
- **Outputs / side effects:** Calls `onSubmit(text, {attachments, …})`, `onSteer`, `onCancel`, and the attachment callbacks. Haptics fire on selection/submit/cancel/open/close.
- **Config / env:** `maxRecordingSeconds` (default 120) caps voice recording; `--composer-*` CSS variables drive every dimension.
- **Edge cases / guards:** Extensive IME handling — input events during composition are skipped (they carry uncommitted preedit); `compositionend` force-flushes because Chromium does not reliably emit a trailing `input` event after an IME commit on Windows, which previously left `hasComposerPayload` false and the send button hidden after typing “你好” (#39614); `compositionstart` clears the empty marker so the placeholder hint does not sit behind preedit text (#75960); `blur` clears the composing flag unconditionally because a missed `compositionend` would wedge the form-submit guard forever (#44135); a stale flag also self-heals on any keydown whose native `isComposing` is false; and an `Enter` with `keyCode === 229` (macOS Chinese IME, some Windows IMEs) is treated as an IME commit, not a send.
- **Rebuild notes:** Keep the DOM authoritative and the React state derived; coalesce serialisation per frame; own the undo stack if you own the editing pipeline; and put every IME guard in from day one — each one above is a shipped bug.

### Composer keyboard map  `id: desktop-b.composer-keys`
- **Surface:** Desktop app
- **Where:** Inside the composer input.
- **What it does:** Every key the composer interprets.
- **How it works:** `handleEditorKeyDown` (`apps/desktop/src/app/chat/composer/index.tsx:566`), in priority order.
- **Inputs / options:** **⌘Z / Ctrl+Z** undo and **⌘⇧Z / Ctrl+Y** redo (`isUndoShortcut` / `isRedoShortcut`) — handled before anything else because the owned stack must never reach Chromium's history. **Backspace** immediately after a directive chip deletes the chip *and* its auto-inserted trailing space as one unit (modified backspaces stay native). **Backspace/Delete** with a non-collapsed selection uses a custom deletion because native selection-delete is ~O(n²) on large drafts (Ctrl+A → Delete froze ~1.3 s). **Space** after a typed URL chips it like a pasted one; **Space** after a bare `@path` chips it into the `@file:`/`@folder:` ref it means. **⌘⇧K / Ctrl+⇧K** drains the next queued message (plain ⌘K is reserved for the palette). With the trigger popover open: **Tab** is swallowed while items are still loading (so it cannot move focus out mid-completion), **↓/↑** move the highlight, **Tab** accepts and *descends* into a folder, **Enter/Space** accept the resolved pick (`acceptsTriggerCompletion` + `implicitSlashAcceptIndex` so a leftover highlight never replaces a typed command), **Backspace** at the end of an `@` path climbs out one segment (mirroring Tab's descent), **Escape** closes the popover. In a slash **arg stage with no suggestions left** (e.g. `/personality creative`, where the backend completer drops the exact match) **Space/Tab** commit the typed text as one directive chip while Enter falls through to submit. **↑** navigates, in priority order: step to an older queued entry while editing one → open the newest queued entry for editing when the composer is empty → browse sent-message history (never hijacking a typed draft unless already browsing). **↓** mirrors it: step to a newer queued entry (past the newest exits the edit) → step forward through history, restoring the draft. **⌘Enter / Ctrl+Enter** queues a follow-up while a turn runs. **Enter** (without Shift) submits: with an empty composer and queued prompts it drains the head; while busy with an empty composer and prompts queued it promotes-and-sends the head (the “double-send”); while busy with nothing queued it is a deliberate no-op (interrupting is explicit). **⇧Enter** inserts a newline. **Escape** cancels a queued-turn edit (restoring the prior draft), otherwise interrupts the running turn with Stop-button parity — but never while the turn is parked on the user.
- **Outputs / side effects:** As above.
- **Config / env:** The `composer.*` keybind labels are listed in `desktop-b.hook-keybinds`.
- **Edge cases / guards:** Every Enter/queue path reads the **live DOM** rather than React state (`composerPlainText(editorRef.current)`), because the AUI composer state lags the latest keystroke by a render — without it a message typed fast (or via IME) while prompts were queued would drain the queue instead of sending (`composer/index.tsx:858`).
- **Rebuild notes:** Decide send/queue/drain from the DOM, not from state.

### Composer paste handling  `id: desktop-b.composer-paste`
- **Surface:** Desktop app
- **Where:** Pasting into the composer (⌘V), or ⌘V anywhere on non-editable chrome (which routes here through the window paste handler).
- **What it does:** Turns whatever is on the clipboard into the right thing: image attachments, a structured PR-comment card, `@url:` chips, `@path` chips, or plain text.
- **How it works:** `handlePaste` (`apps/desktop/src/app/chat/composer/index.tsx:496`). Order: (1) `extractClipboardImageBlobs` → each blob goes to `onAttachImageBlob` with a selection haptic. (2) The text is read and `.trim()`ed so a copy that dragged along leading/trailing blank lines (common from terminals, code blocks and web pages) does not dump padding into the composer — internal newlines are preserved. (3) An **empty** paste with no blobs falls back to `onPasteClipboardImage({silent: true})`, because under WSL2/WSLg the Windows host clipboard does not bridge *images* to the Linux clipboard the DOM paste event reads, so a host screenshot arrives as a completely empty paste; the main process pulls it straight off the Windows clipboard, and `silent` keeps a genuinely empty paste from popping a “no image” warning. (4) Text matching `DATA_IMAGE_URL_RE` is swallowed. (5) Text matching `PR_COMMENT_URL_RE` becomes a structured GitHub review attachment (author, body, `file:line` anchor, diff hunk) — an optimistic card first, resolved via `gh` in the background, and if `gh` cannot answer (offline, unauthenticated, foreign repo) the card swaps back to a plain URL ref so nothing is lost. (6) Otherwise `linkifyUrls` + `pathifyRefs` convert links and bare `@path` tokens into chips in place, keeping a mid-sentence link in position, and the result is inserted at the caret.
- **Inputs / options:** Standard paste; the window-level ⌘V on non-editable chrome routes clipboard text *and* images into the active composer via `handleWindowPaste` (bubble phase so editables' own handlers run first).
- **Outputs / side effects:** Attachments, chips, or inserted text; an undo point is recorded first.
- **Config / env:** n/a
- **Edge cases / guards:** A paste into an **open** `@url:`/`@file:` scope **consumes** that scope instead of stacking on it — the scope is the browse mode the user is pasting into, not text they typed and want to keep (which would produce `@url:@url:\`https://…\``, comment at `composer/index.tsx:559`).
- **Rebuild notes:** Treat paste as a router, not a text insert.

### Composer send / stop / steer / queue controls  `id: desktop-b.composer-controls`
- **Surface:** Desktop app
- **Where:** The right-hand control cluster of the composer. Component `ComposerControls`, `apps/desktop/src/app/chat/composer/controls.tsx:34`.
- **What it does:** The primary action button plus the model pill and voice toggles, changing shape with the turn state.
- **How it works:** `busyAction` is computed in the ChatBar (`composer/index.tsx:391`): while busy, a steerable text-only draft → `steer`; anything else with a payload (or during compaction) → `queue`; an empty composer → `stop`. `canSteer` additionally requires `!compacting`, no blocking prompt, an `onSteer` handler, zero attachments and steerable text — steering only makes sense mid-turn and text-only, because the gateway cannot carry images into a tool result, a slash command executes inline, and a parked tool batch cannot receive a steer.
- **Inputs / options:** **Queue button** (`Layers3` icon), aria/tooltip **“Queue message”** (`composer.queueMessage`) with its keybind, shown when `busyAction !== 'stop'` and there is a payload. **Voice primary** button (`AudioLines`), aria/tooltip **“Start voice conversation”** (`composer.startVoice`), shown when idle with an empty composer. **Send / Stop** submit button: aria/tooltip **“Send”** (`composer.send`) or **“Stop”** (`composer.stop`), rendering an `arrow-up` codicon or a filled square; disabled unless `canSubmit` (`busy || hasComposerPayload`). In HUD mode two extra buttons ride the row: **“Reset HUD layout”** (`titlebar.resetHudLayout`, `discard` icon) and **“Exit HUD”** (`titlebar.exitHud`, `screen-normal` icon) — deliberately here rather than in a 26 px reserved strip above the bar, which cost chrome in every state for a control invisible until hovered (comment at `controls.tsx:169`). The catalog also carries **“Steer the current run”** (`composer.steer`) and **“Open”** (`composer.openDirective`).
- **Outputs / side effects:** Submits, queues, steers or cancels.
- **Config / env:** n/a
- **Edge cases / guards:** During an active voice conversation the whole cluster is replaced by the conversation pill (next entry). At `minimal` width only the send button renders.
- **Rebuild notes:** Derive one `busyAction` and let the button shape follow it.

### Voice conversation pill  `id: desktop-b.composer-conversation-pill`
- **Surface:** Desktop app
- **Where:** Replaces the composer control cluster while a voice conversation is live. `ConversationPill`, `apps/desktop/src/app/chat/composer/controls.tsx:214`.
- **What it does:** Shows what the voice loop is doing and gives mute / stop-turn / end controls.
- **How it works:** A `sr-only` `role="status"` announces the state: **“Speaking”** (`composer.speaking`), **“Transcribing”** (`composer.transcribing`), **“Thinking”** (`composer.thinking`), **“Muted”** (`composer.muted`) or **“Listening”** (`composer.listening`). The end button carries a live indicator: a spinner while speaking, otherwise five bars (weights `0.55, 0.85, 1, 0.85, 0.55`) whose heights track the normalised mic level (`0.3 + min(0.7, level·weight)`, flat 0.3 when not listening).
- **Inputs / options:** The wake-word ear (rendered `pausedForVoice`, so it stays visible but disabled — the conversation holds the mic, the one time wake genuinely must not listen). A mute toggle, aria/tooltip **“Mute microphone”** / **“Unmute microphone”** (`composer.muteMic` / `unmuteMic`), `aria-pressed`, `mic`/`mic-off` codicon. While listening, a **“Stop”** button (`composer.stopShort`) with aria-label **“Stop listening and send”** (`composer.stopListening`) and a filled square. A primary **“End”** button (`composer.endShort`) with aria-label **“End voice conversation”** (`composer.endConversation`).
- **Outputs / side effects:** Toggles mute, ends the current voice turn, or ends the conversation (each with a haptic).
- **Config / env:** n/a
- **Edge cases / guards:** Typing the bare stop phrase into the composer during a live conversation also ends it rather than sending the word “stop” — `interceptsTypedVoiceStop` in the submit wrapper, which reports the send as *accepted* so the draft is cleared rather than restored (`composer/index.tsx:139`). Spoken stop words are handled inside `use-voice-conversation`; outside a conversation, typed “stop” is a normal message.
- **Rebuild notes:** n/a

### Dictation button  `id: desktop-b.composer-dictation`
- **Surface:** Desktop app
- **Where:** Composer controls row. `DictationButton`, `apps/desktop/src/app/chat/composer/controls.tsx:398`.
- **What it does:** Records a single voice clip and transcribes it into the composer (no conversation loop).
- **How it works:** State machine `idle → recording → transcribing`. Icon: `mic` codicon when idle, a filled `Square` while recording, a spinning `Loader2` while transcribing.
- **Inputs / options:** One toggle button whose aria/tooltip is **“Voice dictation”** (`composer.voiceDictation`), **“Stop dictation”** (`composer.stopDictation`) while recording, or **“Transcribing dictation”** (`composer.transcribingDictation`); `aria-pressed` reflects activity.
- **Outputs / side effects:** Inserts the transcript into the composer; the catalog also carries the status labels **“Dictating”** (`composer.dictating`), **“Preparing audio”** (`composer.preparingAudio`), **“Speaking response”** (`composer.speakingResponse`) and **“Reading aloud”** (`composer.readingAloud`).
- **Config / env:** Disabled when speech-to-text is off (**“Speech-to-text is disabled in settings.”**, `desktop.sttDisabled`) and while transcribing.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### “Read replies aloud” toggle  `id: desktop-b.composer-auto-speak`
- **Surface:** Desktop app
- **Where:** Composer controls row. `AutoSpeakButton`, `apps/desktop/src/app/chat/composer/controls.tsx:327`.
- **What it does:** Types normally but has every assistant reply read aloud — TTS without dictation or a conversation loop.
- **How it works:** Reads and writes `$autoSpeakReplies`, persisted to the config key `voice.auto_tts`.
- **Inputs / options:** One toggle, aria/tooltip **“Read replies aloud”** (`composer.speakReplies`) or **“Stop reading replies aloud”** (`composer.stopSpeakingReplies`), `aria-pressed`, `Volume2` when on / `VolumeX` when off, filled with the accent style when active.
- **Outputs / side effects:** Enables TTS playback of replies.
- **Config / env:** `voice.auto_tts`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Wake-word ear (“Hey Hermes”)  `id: desktop-b.composer-wake-word`
- **Surface:** Desktop app
- **Where:** Composer controls row — and it **never hides**. `WakeWordButton`, `apps/desktop/src/app/chat/composer/controls.tsx:362`.
- **What it does:** Turns passive wake-word listening on or off, and explains itself when the backend refuses.
- **How it works:** Reads `$wakeWord` (`{phrase, listening, pending, notice}`); the phrase defaults to `hey hermes`. Clicking calls `toggleWakeWord()`. Three states: listening (accent-highlighted `Ear`), off (muted `EarOff`), and paused-for-voice (disabled while a voice conversation holds the mic).
- **Inputs / options:** One toggle. Tooltip/aria: **“Wake word: "{phrase}" — listening”** (`composer.wakeWordListening`), **“Wake word: "{phrase}" — off”** (`composer.wakeWordOff`), or **“Wake word: "{phrase}" — paused during voice chat”** (`composer.wakeWordPausedVoice`); a backend `notice` is appended as `"{label} — {notice}"`.
- **Outputs / side effects:** Starts/stops passive listening on the backend.
- **Config / env:** Wake phrase and enablement live in the voice config (see the config shards).
- **Edge cases / guards:** The button is deliberately always rendered so the user can always click it; a backend refusal (`{started: false, reason}`) keeps the toggle off and puts the reason in the tooltip rather than failing silently (comment at `controls.tsx:353`). Disabled while `wake.pending`.
- **Rebuild notes:** Never hide a control whose failure mode is “nothing happened” — show it and explain the refusal.

### Composer “+” attach menu  `id: desktop-b.composer-context-menu`
- **Surface:** Desktop app
- **Where:** The `+` button at the left of the composer. Component `ContextMenu`, `apps/desktop/src/app/chat/composer/context-menu.tsx:475`.
- **What it does:** Attaches files, folders, images, a clipboard image or a URL, and opens the prompt-snippet picker.
- **How it works:** A Radix dropdown anchored `side="top" align="start"` with a 15 rem card. Section label **“Attach”** (`composer.attachLabel`). Items are disabled when the corresponding handler is absent.
- **Inputs / options:** **“Files…”** (`composer.files`, `FileText`) → `onPickFiles`; **“Folder…”** (`composer.folder`, `FolderOpen`) → `onPickFolders`; **“Images…”** (`composer.images`, `ImageIcon`) → `onPickImages`; **“Paste image”** (`composer.pasteImage`, `Clipboard`) → `onPasteClipboardImage`; **“URL…”** (`composer.url`, `Link`) → opens the URL dialog; separator; **“Prompt snippets…”** (`composer.promptSnippets`, `MessageSquareText`) → opens the snippets dialog; then any `composer.attachments` contributions (each with its own icon, defaulting to `plug`, and label); then a footer hint reading **“Tip: type ”** + a `@` key badge + **“ to reference files inline.”** (`composer.tipPre` / `tipPost`). The trigger's tooltip and aria-label come from `state.tools.label`.
- **Outputs / side effects:** Opens native pickers or dialogs; contributions run their own `run({insertText})`.
- **Config / env:** n/a
- **Edge cases / guards:** Prompt snippets used to be a Radix submenu, which did not open reliably when the parent menu was pinned to the bottom of the window at the composer's `+` anchor, so it was promoted to a real dialog (comment at `context-menu.tsx:486`).
- **Rebuild notes:** n/a

### Prompt snippets dialog  `id: desktop-b.composer-snippets`
- **Surface:** Desktop app
- **Where:** Composer `+` menu → **“Prompt snippets…”**. Dialog title **“Prompt snippets”** (`i18n: composer.snippetsTitle`), description **“Pick a starter prompt to drop into the composer.”** (`composer.snippetsDesc`).
- **What it does:** Drops a ready-made starter prompt into the composer.
- **How it works:** `PromptSnippetsDialog` (`apps/desktop/src/app/chat/composer/context-menu.tsx:572`) renders exactly the three keys in `SNIPPET_KEYS` (`context-menu.tsx:473`).
- **Inputs / options:** Three rows, each a label + description that inserts its text and closes the dialog: **“Code review”** / **“Audit the current change for regressions, dropped edge cases, and missing tests.”** inserting `Please review this for bugs, regressions, and missing tests.`; **“Implementation plan”** / **“Outline an approach before touching code so the diff stays focused.”** inserting `Please make a concise implementation plan before changing code.`; **“Explain this”** / **“Walk through how the selected code works and link to the key files.”** inserting `Please explain how this works and point me to the key files.` (`i18n: composer.snippets.codeReview|implementationPlan|explainThis`).
- **Outputs / side effects:** Inserts the text at the caret.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Attachment pills  `id: desktop-b.composer-attachments`
- **Surface:** Desktop app
- **Where:** A wrapping row inside the composer, `data-slot="composer-attachments"`. Component `AttachmentList` / `AttachmentPill`, `apps/desktop/src/app/chat/composer/attachments.tsx:18`.
- **What it does:** Shows every attachment staged for the next turn — files, folders, images, URLs, terminal captures and GitHub review cards — with a thumbnail, upload progress and a remove button.
- **How it works:** Icon by `attachment.kind`: `file` → `FileText`, `folder` → `FolderOpen`, `image` → `ImageIcon`, `review` → `MessageCode`, `terminal` → `Terminal`, `url` → `Link` (`attachments.tsx:42`). Image pills show `thumbnailUrl ?? previewUrl` as a cover image. Clicking a previewable pill opens it: an image resolves through `readDesktopFileDataUrlLocalFirst` — trying `attachment.path` then `attachment.detail`, because an upload may replace `path` with a gateway-side staged path while `detail` still carries the original host path, so a failed submit still leaves the chip previewable across split-filesystem setups (`attachments.tsx:83`) — and opens the shared `ImageLightbox`; anything else normalises through `normalizeOrLocalPreviewTarget(target, cwd)` and calls `openPreview(target, 'manual')`. The cwd used is **this surface's** session cwd (`useSessionView().$cwd`), so a relative path in a tile composer resolves against its own session root.
- **Inputs / options:** Click a pill to preview (aria **“Preview {label}”**, `composer.previewLabel`); hover to reveal a close button, aria **“Remove {label}”** (`composer.removeAttachment`); the whole pill has a tooltip showing `path || detail || label`. `aria-busy` while uploading.
- **Outputs / side effects:** Opens a preview or lightbox; removal calls `onRemove(id)`.
- **Config / env:** n/a
- **Edge cases / guards:** Folders, terminal captures and review cards are **not** previewable — a review card's detail is resolved-comment JSON, not a path, so clicking should do nothing rather than toast a bogus failure (`attachments.tsx:57`). Full image bytes are deliberately kept out of composer state: new chips read their path only when clicked, and `previewUrl` remains a compatibility fallback for older drafts. Upload states render a spinner overlay (`uploading`) or a destructive `AlertCircle` with a destructive border (`error`). Preview failures toast **“Preview unavailable”** (`composer.previewUnavailable`) with **“Could not preview {label}”** (`composer.couldNotPreview`).
- **Rebuild notes:** Keep bytes out of state; resolve on click, with both the staged and original paths as candidates.

### “Attach a URL” dialog  `id: desktop-b.composer-url-dialog`
- **Surface:** Desktop app
- **Where:** Composer `+` menu → **“URL…”**. Dialog title **“Attach a URL”** (`i18n: composer.attachUrlTitle`, `Globe` icon), description **“Hermes will fetch the page and include it as context for this turn.”** (`composer.attachUrlDesc`). Component `UrlDialog`, `apps/desktop/src/app/chat/composer/url-dialog.tsx`.
- **What it does:** Adds a web page as context for the next turn.
- **How it works:** `useComposerUrlDialog` owns the open/value state and autofocus; submitting calls the host `onAddUrl` or inserts an `@url:` directive into the draft.
- **Inputs / options:** One URL input (`inputMode="url"`, autocomplete/autocorrect/spellcheck off), placeholder **“https://example.com/post”** (`composer.urlPlaceholder`); footer **“Cancel”** (`common.cancel`) and **“Attach”** (`composer.attach`), the latter disabled until the value matches `/^https?:\/\//i`.
- **Outputs / side effects:** Adds a URL attachment or an `@url:` chip.
- **Config / env:** n/a
- **Edge cases / guards:** A non-empty value that does not look like a URL shows the hint **“Include the full URL, e.g. ”** followed by `https://…` in mono (`composer.urlHintPre`).
- **Rebuild notes:** n/a

### Composer quick-help drawer (`?`)  `id: desktop-b.composer-help-hint`
- **Surface:** Desktop app
- **Where:** Appears above the composer when the draft is exactly the help hint (typing `?` into an empty composer). Component `HelpHint`, `apps/desktop/src/app/chat/composer/help-hint.tsx`.
- **What it does:** A cheat sheet of the most common slash commands and composer hotkeys.
- **How it works:** Two sections rendered inside the shared completion drawer. Section **“Common commands”** (`composer.commonCommands`) lists exactly `COMMON_COMMAND_KEYS`: **`/help`** — “full list of commands + hotkeys”, **`/clear`** — “start a new session”, **`/resume`** — “resume a prior session”, **`/details`** — “control transcript detail level”, **`/copy`** — “copy selection or last assistant message”, **`/quit`** — “exit hermes” (`composer.commandDescs.*`). Section **“Hotkeys”** (`composer.hotkeys`) renders `COMPOSER_HOTKEY_ROWS` with OS-resolved key badges: `@` — “reference files, folders, urls, git” (`composer.mention`); `/` — “slash command palette” (`composer.slash`); `?` — “this quick help (delete to dismiss)” (`composer.help`); `Enter` + `Shift+Enter` — “send · Shift+Enter for newline” (`composer.sendNewline`); `mod+shift+k` — “send next queued turn” (`composer.sendQueued`); `mod+/` — “all keyboard shortcuts” (`keybinds.openPanel`); `Escape` — “close popover · cancel run” (`composer.cancel`); `↑`/`↓` — “cycle popover / history” (`composer.history`). A footer reads `/help` **“opens the full panel · backspace dismisses”** (`composer.helpFooter`).
- **Inputs / options:** Read-only; Backspace dismisses it.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** Key combos are rendered through `KbdCombo`, which resolves the modifier label per OS.
- **Rebuild notes:** n/a

### Completion popover (`@`, `/`, `:`)  `id: desktop-b.composer-trigger-popover`
- **Surface:** Desktop app
- **Where:** Floats above (or below) the composer while a trigger is active. `role="listbox"`, `data-slot="composer-completion-drawer"`. Component `ComposerTriggerPopover`, `apps/desktop/src/app/chat/composer/trigger-popover.tsx:80`.
- **What it does:** The single completion list for file/folder/URL/git references (`@`), slash commands, skills and themes (`/`), and emoji (`:`).
- **How it works:** `@` and `/` deliberately share **one** row shape — icon, name, description — because they used to be two layouts in one file (`@` horizontal with an icon, `/` stacked with none), which is why picking a file and picking a skill felt like features from different apps (comment at `trigger-popover.tsx:68`). Icons and accent colours come from the shared reference vocabulary (`referenceKind` / `referenceStyle`), so a row looks like the chip it will become. `rowKind()` (`trigger-popover.tsx:21`) maps a `/` row's completion group to `skill` (group “Skills”), `theme` (group “Themes”) or `command`, and maps `@diff` / `@staged` raw text to their own glyphs since the gateway gives those simple refs one shared item type. `:` emoji is the one exception — the emoji *is* the icon, so the row is a single display string (Slack's exact shape). Slash rows are grouped with uppercase group headers. The `/skin` argument stage is the desktop's own completion source — `use-slash-completions.ts:99-107` intercepts `/^\/skin\s+(.*)$/is` and maps `desktopSkinSlashCompletions(skinThemes, activeSkin, arg)` into rows tagged `group: 'Themes'`, deliberately skipping the backend skin completions (which describe CLI/TUI skins). The catalog declares an accessible label **“Desktop theme suggestions”** (`i18n: composer.themeSuggestions`) plus **“No matching themes.”** (`composer.noMatchingThemes`) and the split hint **“Try ”** / **“.”** (`composer.themeTryPre` / `composer.themeTryPost`) for that list; as of v2026.8.31 `composer.themeSuggestions` has NO consumer anywhere in `apps/desktop/src` outside the i18n catalogs themselves (grep-verified) — it is a declared-but-currently-unreferenced label, translated in every locale (`en.ts:2445`, `zh.ts:2624`, `zh-hant.ts:2050`, `ja.ts:2119`, `ar.ts:1902`) and typed at `i18n/types.ts:2076`, so a rebuild should either wire it as the theme list's `aria-label` or delete it.
- **Inputs / options:** Mouse hover highlights a row, click picks it; keyboard navigation is documented in `desktop-b.composer-keys`. A `scope` header shows the current `@kind:` browse mode's label so the raw `@folder:` in the editor does not read as syntax the user must finish by hand.
- **Outputs / side effects:** Picking replaces the trigger token with a reference chip (Tab additionally descends into a folder).
- **Config / env:** n/a
- **Edge cases / guards:** Loading state shows a braille `GlyphSpinner` with **“Looking up…”** (`composer.lookupLoading`). Empty state shows **“No matches.”** (`composer.lookupNoMatches`) plus a kind-specific hint: **“Try `@file:` or `@folder:`.”**, **“Try `:joy:`.”** or **“Try `/help`.”** (`composer.lookupTry` / `lookupOr`). Scrolling is kept **local to the drawer** with manual arithmetic instead of `scrollIntoView`, which operates on every scrollable ancestor and would also move the transcript or the window (comment at `trigger-popover.tsx:129`); a hover echo never scrolls (it already points at a visible row, and scrolling could shift another row under the pointer); highlighting index 0 resets `scrollTop` to 0 so the group header is not clipped; a row that spans both edges is left alone. `onMouseDown` is prevented so the composer never loses focus.
- **Rebuild notes:** One row shape for every trigger; keep scrolling inside the list.

### Model pill  `id: desktop-b.composer-model-pill`
- **Surface:** Desktop app
- **Where:** Left of the voice controls in the composer row. Component `ModelPill`, `apps/desktop/src/app/chat/composer/model-pill.tsx:38`.
- **What it does:** Shows the model this chat surface is running and opens the live model menu to change it.
- **How it works:** Display follows **this surface's** `SessionView` (primary or tile) rather than the primary-only globals, so side-by-side panes each show their own model (`model-pill.tsx:36`). The label is `formatModelStatusLabel(model, {defaultEffort, fastMode, reasoningEffort})`. When a live `model.options` menu exists it renders as a dropdown reusing `modelMenuContent` verbatim; with the gateway closed it falls back to opening the full model-picker dialog (`setModelPickerOpen(true)`).
- **Inputs / options:** Click the pill (or press the `composer.modelPicker` hotkey, routed to the pane under the pointer or the active composer). Tooltip/aria is `shell.statusbar.modelTitle(provider, model)` or **“Switch model”** (`shell.statusbar.switchModel`); the no-menu variant uses **“Open model picker”** (`shell.statusbar.openModelPicker`). In `compact` mode (the floating popped-out composer) the pill shrinks to a square holding only a chevron.
- **Outputs / side effects:** Selecting a model applies it to this surface.
- **Config / env:** Reads `$currentModelSource` and `$defaultReasoningEffort`.
- **Edge cases / guards:** A **pinned-override dot** (`data-testid="model-pinned-dot"`, aria `shell.statusbar.modelPinned`) appears when the primary view has no runtime session, the model source is `manual`, and a model is set — because a composer pick is *sticky*: a manual selection is pinned and every new chat uses it instead of the Settings default, silently, which has cost users real money on a forgotten paid-model pick (#62055). Tiles always have a runtime, so the badge is primary-draft only. While the model is still resolving the pill shows a quiet braille spinner rather than flashing a literal “No model”. Closing the menu calls `releaseTypingFocus()`, or the Enter that committed a model would also swallow the next keystroke (Radix restores focus to the pill).
- **Rebuild notes:** Make a sticky default visible; scope the display to the surface, not the app.

### Micro-action pills  `id: desktop-b.composer-micro-actions`
- **Surface:** Desktop app
- **Where:** The floating strip immediately above the composer surface. Component `ActionBadges`, `apps/desktop/src/app/chat/composer/micro-actions.tsx:32`.
- **What it does:** Renders contributed one-click actions for the current session (published by `useComposerMicroActions`).
- **How it works:** Reads `$composerActionsBySession` through the session-slice hook, so unrelated sessions' churn never re-renders this strip. Each pill runs `action.run(sessionId)`; the in-flight one spins (`loading` codicon) and every pill locks so a second cannot fire.
- **Inputs / options:** One button per contributed action (its own `icon` and `label`).
- **Outputs / side effects:** Whatever the action does; failures toast with the action's label as the title.
- **Config / env:** n/a
- **Edge cases / guards:** The pills are **never** `pointer-events-none`, even when disabled — the pop-out drag region is an absolute sibling behind them, so a pill that stops taking pointer events would hand the hit test to it and a dead-looking badge would become a grab handle that floats the composer (comment at `micro-actions.tsx:10`).
- **Rebuild notes:** n/a

### Suggestion pills  `id: desktop-b.composer-suggestion-pills`
- **Surface:** Desktop app
- **Where:** Beside the micro-action badges in the floating lane above the composer. Component `SuggestionPills`, `apps/desktop/src/app/chat/composer/suggestion-pills.tsx:42`.
- **What it does:** Offers contextual one-click actions the agent or the app noticed you might want — connect an MCP server, lead with a skill, set up GitHub, reconnect a failed server, schedule a recurring prompt.
- **How it works:** Fed by the suggestion bus `$composerSuggestionsBySession`. Each pill narrates a three-phase lifecycle — `label` → `workingLabel` (a second click requests cancel) → `doneLabel` — while the provider's `invoke({cancelled, sessionId})` owns the work, cancellation, rollback and error toasts. The component is remounted per session (`key={sessionId}`) because phase keys are `provider:id` and one composer stays mounted across a session switch: without the remount, “Added GitHub” in one chat would render the next chat's genuine offer as already-done and inert (comment at `suggestion-pills.tsx:34`). A withdrawn pill's phase is dropped *and* its in-flight work cancelled at the next poll boundary — a withdrawn pill is the user's only cancel affordance, so an abandoned OAuth flow would otherwise poll forever, hold the server's in-progress slot against a retry, and either land a server the user never confirmed or roll one back with no UI to say so (comment at `suggestion-pills.tsx:57`). Unmount cancels everything.
- **Inputs / options:** Click a pill to invoke; click again while working to cancel. Icon: brand glyph (`brandFor`) when the suggestion names one, otherwise its `icon` or `lightbulb`; a spinning `loading` codicon while working and an emerald `check` when done. Known suggestion copies: MCP — **“Add {server}”** / **“Suggested because you mentioned “{keyword}” — click to connect”** / **“Connecting {server}…”** / **“Click to cancel”** / **“Added {server}”** / **“Connected — its tools are ready in this chat”** / **“Could not connect {server}”** (`composer.mcpSuggestions.*`); skills — **“Use skill: {skill}”** / **“You mentioned “{skill}” — click to lead with that skill”** / **“Added /{skill}”** / **“The skill loads when you send”** (`composer.skillSuggestions.*`); GitHub — **“Set up GitHub”** / **“GitHub works through the gh CLI skills here — click to connect your account”** / **“Added /github-auth”** / **“Send the message and the agent walks you through GitHub sign-in”** (`composer.githubSuggestions.*`); repair — **“Reconnect {server}”** / **“A {server} call just failed with a connection error”** / **“Reconnecting {server}…”** / **“Click to cancel”** / **“Reconnected {server}”** / **“Fresh credentials are live in this chat”** / **“Could not reconnect {server}”** (`composer.repairSuggestions.*`); cron — **“Schedule this”** / **““{phrase}” sounds recurring — run it on a schedule instead”** / prefix **“Set this up as a scheduled job:”** / **“Marked for scheduling”** / **“Send it and the agent creates the job”** (`composer.cronSuggestions.*`).
- **Outputs / side effects:** Whatever the provider does; `markSuggestionInvoked` clears the pill's ignored-count in the bus's declined ledger so a later withdrawal counts as success rather than a strike.
- **Config / env:** n/a
- **Edge cases / guards:** There is deliberately **no dismiss affordance**: suggestions are self-limiting (a provider withdraws its offer when the trigger condition stops holding), so a close button would mostly collect accidental permanent opt-outs — the escape hatch is not clicking (comment at `suggestion-pills.tsx:23`). Same never-`pointer-events-none` rule as the micro pills.
- **Rebuild notes:** Model a suggestion as an offer with a lifecycle and a withdrawal, not a notification.

### Voice menu (folded voice controls)  `id: desktop-b.composer-voice-menu`
- **Surface:** Desktop app
- **Where:** Replaces the four separate voice buttons when the composer is narrow or in HUD mode. Component `VoiceMenu`, `apps/desktop/src/app/chat/composer/voice-menu.tsx`.
- **What it does:** Puts dictation, spoken replies, the wake word and “start a conversation” behind one trigger.
- **How it works:** The trigger is deliberately **not** a static glyph: it reports the loudest live voice state (recording → filled square, transcribing → spinner, wake listening → `Ear`, else the `mic` codicon) and lights up whenever anything is live, so a folded menu can never look idle while the mic is open (comment at `voice-menu.tsx:33`). Its aria/tooltip is the dictation label while dictating, the wake label while listening, else **“Voice”** (`composer.voiceControls`), with a wake `notice` appended as `"{label} — {notice}"`.
- **Inputs / options:** One plain item **“Start voice conversation”** (`composer.startVoice`, `AudioLines`), a separator, then three **checkbox** items — deliberately checkboxes because all three are toggles whose current state the user is reading, and a plain row would fold that state away with the menu (comment at `voice-menu.tsx:110`): the dictation toggle (label per status), the auto-speak toggle (**“Read replies aloud”** / **“Stop reading replies aloud”** with `VolumeX`/`Volume2`), and the wake-word toggle (**“Wake word: "{phrase}" — listening/off”** with `Ear`/`EarOff`). All three call `event.preventDefault()` so the menu **stays open** — dictation especially is a mode you watch, and closing on select would hide the recording state the trigger just entered.
- **Outputs / side effects:** Same as the individual buttons.
- **Config / env:** n/a
- **Edge cases / guards:** The dictation item is disabled when STT is off or while transcribing; the wake item while `wake.pending`.
- **Rebuild notes:** n/a

### Composer status stack  `id: desktop-b.composer-status-stack`
- **Surface:** Desktop app
- **Where:** The card directly above the composer, `data-slot="composer-status-stack"`, fused to it as one capsule. Component `ComposerStatusStack`, `apps/desktop/src/app/chat/composer/status-stack/index.tsx:89`.
- **What it does:** One session-scoped sink for everything the turn is doing — the goal, todos, subagents, background tasks, preview links, the queued-message panel, and the billing wall.
- **How it works:** Reads `$statusItemsBySession` and `$previewStatusBySession` through the session-slice hook, because both maps churn on other sessions' activity and a whole-map subscription re-rendered every mounted stack (one per open tile) on all of it (comment at `status-stack/index.tsx:92`). Items are grouped by `groupStatusItems` into four types with fixed codicons (`GROUP_ICON`, `status-stack/index.tsx:47`): `goal` → `target`, `todo` → `checklist`, `subagent` → `agent`, `background` → `server-process`. Group labels: goal → **“Goal active”** / **“Goal paused”** / **“Goal waiting”** / **“Goal done”** (`statusStack.goalActive|goalPaused|goalWaiting|goalDone`); todo → **“Tasks {done}/{total}”** (`statusStack.todos`); subagent → **“{n} Subagent(s)”** (`statusStack.subagents`); background → **“{n} Background”** (`statusStack.background`). Todo and goal groups start expanded; subagent and background start collapsed. On session open the stack calls `resetBackgroundPollingGuard`, `refreshBackgroundProcesses` and `refreshSessionGoal`; while a background row is *running* it also arms a `BACKGROUND_POLL_MS = 5000` safety-net poll for silent exits (processes without `notify_on_complete` emit no event when they die).
- **Inputs / options:** Each section collapses/expands. The subagent section carries an accessory button **“Agents”** (`statusStack.agents`) with its keybind tooltip, navigating to the Agents route; clicking a subagent row opens that child's session in a new watched window, or the Agents view when it has no session id. Background rows offer **“Stop”** (`statusStack.stop`) and **“Dismiss”** (`statusStack.dismiss`) and show **“exit {code}”** (`statusStack.exit`) when finished; a running todo shows a braille spinner labelled **“Running”** (`statusStack.running`) even while collapsed. Preview rows are one-tap open links with their own dismiss.
- **Outputs / side effects:** Stops or dismisses background processes, dismisses preview artifacts, navigates.
- **Config / env:** n/a
- **Edge cases / guards:** A localhost/loopback preview (`/\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)\b/i`) is only shown while some background process is still running — that is what made dead `localhost:5174` chips stick around; on-disk file previews stand alone and are kept (`status-stack/index.tsx:41`). Preview rows are rendered as an **always-visible** block right after the background section rather than as collapsible children, because the whole point is a one-tap open and a new background task would otherwise swallow them. The billing wall (`BillingBanner`) is pushed to the very top of the stack and is rendered here rather than disabling the composer, so slash commands stay usable while out of credits. Pointer-down anywhere in the stack blurs the composer input. The card collapses to `null` when every section is empty, and the whole stack scrolls inside `max-h-[40vh]`.
- **Rebuild notes:** One sink, session-sliced subscriptions, and never hide a status behind a collapsed group when the user needs to press it.

### Queued-messages panel  `id: desktop-b.composer-queue-panel`
- **Surface:** Desktop app
- **Where:** The last section of the composer status stack. Component `QueuePanel`, `apps/desktop/src/app/chat/composer/queue-panel.tsx:30`.
- **What it does:** Lists the follow-up turns waiting to be sent, and lets each one be edited, steered, sent now or deleted.
- **How it works:** Section label **“{n} Queued”** (`composer.queued`) or, after an explicit halt, **“{n} Queued — paused”** (`composer.queuedPaused`) with a `debug-pause` icon instead of `layers`. The section is **keyed on the park flag** so it remounts on park/unpark: a Stop must *expand* the panel, because the halted prompts' only presence is here and leaving them behind a collapsed “N queued” pill is exactly how they read as vanished (comment at `queue-panel.tsx:49`). Each row's preview is `displayText ?? text`, falling back to **“Attachment-only turn”** (`composer.attachmentOnly`) or **“Empty turn”** (`composer.emptyTurn`).
- **Inputs / options:** When parked, an accessory button **“Resume”** (`composer.queueResume`) tooltipped **“Paused by Stop — resume sending the queued turns”** (`composer.queueResumeTip`). Per row: **“Edit”** (`composer.queueEdit`, `Pencil`) — disabled while another row is being edited; **“Steer — redirect the live turn now”** (`composer.queueSteer`, `SteeringWheel`) — shown only when a turn is live, a steer handler exists and the entry is steerable (`isSteerableEntry`: text-only, no slash command); **“Next”** while busy or **“Send”** when idle (`composer.queueSendNext` / `queueSend`, `CornerDownLeft`); **“Delete”** (`composer.queueDelete`, `Trash2`). A row being edited is outlined and shows **“Editing in composer”** (`composer.editingInComposer`); the composer itself shows **“Editing queued turn in composer”** (`composer.editingQueuedInComposer`) with Cancel/Save buttons. Attachment counts render as **“{n} attachment(s)”** (`composer.attachments`).
- **Outputs / side effects:** Edits load the entry into the composer; send-now promotes and (while busy) interrupts and drains on settle; delete removes the entry.
- **Config / env:** n/a
- **Edge cases / guards:** An explicit halt (Stop button or Esc) **parks** the queue through `haltRun`, so stopping never rolls straight into the next queued prompt — that read as “Stop not working”, and the queued text also seemed to vanish since the collapsed panel row was its only trace (comment at `composer/index.tsx:355`); interrupts that exist to advance the queue (send-now-while-busy) call the raw `onCancel` and keep draining. A queued turn that repeatedly fails to send raises **“Queued message not sent”** / **“A queued turn kept failing to send. It is still in the queue — try sending it again.”** (`composer.queueStuckTitle` / `queueStuckBody`).
- **Rebuild notes:** Park on explicit stop; expand the panel when you park.

### Composer placeholder  `id: desktop-b.composer-placeholder`
- **Surface:** Desktop app
- **Where:** The composer's `data-placeholder` text.
- **What it does:** Shows a rotating invitation in an empty composer, and the connection state when there is one.
- **How it works:** `useComposerPlaceholder({disabled, reconnecting, sessionId})` (`apps/desktop/src/app/chat/composer/hooks/use-composer-placeholder.ts`) re-rolls only on a real conversation change.
- **Inputs / options:** New-session pool (`composer.newSessionPlaceholders`): **“What are we building?”**, **“Give Hermes a task”**, **“What's on your mind?”**, **“Describe what you need”**, **“What should we tackle?”**, **“Ask anything”**, **“Start with a goal”**. Follow-up pool (`composer.followUpPlaceholders`): **“Send a follow-up”**, **“Add more context”**, **“Refine the request”**, **“What's next?”**, **“Keep it going”**, **“Push it further”**, **“Adjust or continue”**. Fixed states: **“Starting Hermes...”** (`composer.placeholderStarting`), **“Reconnecting to Hermes…”** (`composer.placeholderReconnecting`), **“Send follow-up”** (`composer.placeholderFollowUp`), and **“Waking up {profile}…”** (`composer.wakingProfile`).
- **Outputs / side effects:** Visual only.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Composer pop-out (floating composer)  `id: desktop-b.composer-popout`
- **Surface:** Desktop app
- **Where:** Drag the composer's transparent grab margin, or double-click the drag region. `data-popped-out` on the dock and root. Hook `useComposerPopout` (`apps/desktop/src/app/chat/composer/hooks/use-composer-popout.ts`) plus `use-popout-drag.ts`.
- **What it does:** Detaches the composer into a compact floating bar you can place anywhere over the chat, and docks it back.
- **How it works:** A `pointer-events-auto absolute inset-0` drag region covers the 5 px transparent grab margin around the surface; the surface itself sits above it (`z-4`), so the grab cursor and diagonal hatch only appear on the exposed ring, never over the input (comment at `composer/index.tsx:1285`). While dragging near the dock, a bottom-centred radial glow renders as the dock target — deliberately `absolute` (not `fixed`) so it anchors to the chat column and never spans the viewport or reaches under the sidebar — with opacity `(0.1 + dockProximity·0.57) × var(--dock-glow-scale)`. Floating width is `POPOUT_WIDTH_REM`.
- **Inputs / options:** Drag to move; double-click the drag region to toggle docked/floating.
- **Outputs / side effects:** Position persists in the composer-popout store; `pruneComposerPopoutZones` cleans up stale zones.
- **Config / env:** n/a
- **Edge cases / guards:** Secondary windows cannot pop out (`popoutAllowed`). While popped out the model pill goes compact and the status strips stay siblings of the composer rather than children, because the drag region is `absolute inset-0` **inside** the composer — anything rendered there would be inside the grab area by construction (comment at `composer/index.tsx:1176`).
- **Rebuild notes:** Keep the grab region a sibling layer under the surface, and keep anything clickable out of it structurally rather than by exclusion rules.

### Composer drag-and-drop  `id: desktop-b.composer-drop`
- **Surface:** Desktop app
- **Where:** Dropping files onto the composer or the chat area.
- **What it does:** Attaches dropped files, folders and images, or inserts inline references.
- **How it works:** `useComposerDrop({cwd, insertInlineRefs, onAttachDroppedItems, requestMainFocus})` provides `handleDragEnter/Leave/Over/Drop` for the composer root and `handleInputDragOver/Drop` for the editor itself; the root carries `data-drag-active` and the surface swaps `COMPOSER_DROP_FADE_CLASS` for `COMPOSER_DROP_ACTIVE_CLASS`.
- **Inputs / options:** Drop anywhere on the composer or the chat drop overlay.
- **Outputs / side effects:** Adds attachments or inline `@file:`/`@folder:` refs.
- **Config / env:** n/a
- **Edge cases / guards:** Overlay copy: **“Drop files to attach”** (`composer.dropFiles`) and, when dragging a session, **“Drop to link this chat”** (`composer.dropSession`).
- **Rebuild notes:** n/a

### Coding status row (working tree)  `id: desktop-b.composer-coding-row`
- **Surface:** Desktop app
- **Where:** A strip inside the composer surface, above the input. Component `CodingStatusRow`, `apps/desktop/src/app/chat/composer/status-stack/coding-row.tsx`.
- **What it does:** Shows the git state of this surface's working tree and offers the review, commit, branch and PR actions.
- **How it works:** Given a `repoPath` it probes git/GitHub and renders the branch and dirty state; with no repo it hides itself entirely. In a **bot chat** the composer passes a blank `repoPath` on purpose — a bot chat is a companion conversation, not a working session, so it has no repo, and blanking the prop also stops the row probing git and GitHub for a surface with no branch (comment at `composer/index.tsx:952`). Opening review calls `toggleReview(scope.target === 'main' ? null : cwd, scope.target)` — a tile's rail reviews **its** worktree, while main keeps the classic follow-the-active-session scope.
- **Inputs / options:** Verbatim labels from `statusStack.coding`: title **“Working tree”**, **“No branch”**, **“detached”**, **“Clean”**, **“{n} changed”**, **“{n} ahead”**, **“{n} behind”**, **“Review”**, **“Close”**, **“Open changes”**, **“Open file”**, **“Stage”**, **“Unstage”**, **“Stage all”**, **“View as tree”**, **“View as list”**, **“Revert”**, **“Revert all”**, **“Staged”**, **“No changes”**, **“Not a git repository”**, **“No diff to show”**, scope tabs **“Uncommitted”** / **“Branch”** / **“Last turn”**, **“Commit”**, **“Commit & Push”**, commit placeholder **“Message ({shortcut} to commit)”**, **“Generate commit message”**, **“Stop generating”**, **“Create PR”**, **“Open PR”**, **“Install the GitHub CLI (gh) and sign in to open PRs”**, **“Ask Hermes to open PR”**, **“New branch”**, **“New branch from {base}”**, **“Switch to {branch}”**, **“Worktrees”**. The branch submenu additionally borrows two labels from the projects catalog: **“New worktree”** (`i18n: sidebar.projects.startWork`, `coding-row.tsx:189`) which cuts a fresh worktree off the current HEAD, and — only when an `onConvertBranch` handler was supplied — **“Convert a branch…”** (`i18n: sidebar.projects.convertBranch`, `coding-row.tsx:196`; the `p = t.sidebar.projects` alias is bound at `coding-row.tsx:66`), which opens the shared worktree dialog in convert-branch mode.
- **Outputs / side effects:** Stages/unstages/reverts files, commits (and pushes), creates or opens a PR, creates/switches branches, opens worktrees. The **“Ask Hermes to open PR”** action submits the prompt **“Review the current changes, commit them with a clear conventional-commit message, push the branch, and open a pull request.”** (`statusStack.coding.agentShipPrompt`).
- **Config / env:** n/a
- **Edge cases / guards:** Revert confirmations: **“Discard changes to this file and restore it to the committed state? This cannot be undone.”** and **“Discard every change and restore files to the committed state? This cannot be undone.”**. A failed branch switch shows **“Could not switch to {branch}”**. When the owning chat is off screen the agent-ship action reports **“The chat that owns these changes isn't on screen.”** (`statusStack.coding.agentShipUnavailable`).
- **Rebuild notes:** Scope the review pane to the surface's own worktree, not the app's active session.

---

## 15. Chat sidebar

### Chat sidebar  `id: desktop-b.sidebar`
- **Surface:** Desktop app
- **Where:** The left pane (`sessions` pane id). Component `ChatSidebar`, `apps/desktop/src/app/chat/sidebar/index.tsx:310`.
- **What it does:** Navigation plus the session list: the nav rail, a search field, and the Pinned / Sessions / messaging-platform / Cron sections, with projects, worktrees, filters and the profile rail.
- **How it works:** Two height modes driven by the `compact` variant in `styles.css`: **tall** gives each section its own capped scroller with Sessions as `flex-1`; **compact** drops the caps (`COMPACT_FLAT`) so the whole stack scrolls as one. Sections stay `shrink-0` so none can be squeezed below its content and bleed onto the next — the flexbox `min-height: auto` overlap trap (comment at `sidebar/index.tsx:228`). The outer list reserves its scrollbar width permanently (`[scrollbar-gutter:stable]`) so filtering or collapsing never reflows rows sideways, and only the outer scroller does so — nested ones would stack the inset. Section-header action icons are hidden until the header row is hovered (`HEADER_ACTION_BTN`), while the view toggle stays visible at all times (`HEADER_NAV_BTN`) because it is the stable navigation affordance. The container carries `data-sessions-mode` and `data-sessions-project`.
- **Inputs / options:** See the entries below — nav rail, search, Pinned, Sessions, messaging groups, Cron, the filter menu, the profile rail.
- **Outputs / side effects:** Navigation, session ops.
- **Config / env:** Section open/closed state persists in the layout store (`setSidebarPinsOpen`, `setSidebarRecentsOpen`, `setSidebarCronOpen`, `toggleSidebarMessagingOpen`).
- **Edge cases / guards:** Messaging groups start at `NON_SESSION_INITIAL_ROWS = 3` rows and reveal `NON_SESSION_LOAD_STEP = 10` more at a time, so a busy platform cannot dominate the sidebar before the user asks. The project tree is warmed `PROJECT_TREE_WARM_MS = 2000` ms after connecting for users who are *not* in the grouped view, so the flat list — the thing actually on screen — gets the connection to itself first. With no sessions at all the sidebar renders `SidebarBlankState` with a “new project” action.
- **Rebuild notes:** Reserve the scrollbar gutter once, at the outer scroller; keep every section `shrink-0`.

### Sidebar nav rail  `id: desktop-b.sidebar-nav`
- **Surface:** Desktop app
- **Where:** The five rows at the top of the sidebar. `SIDEBAR_NAV`, `apps/desktop/src/app/chat/sidebar/index.tsx:189`.
- **What it does:** New session plus the four full-page destinations.
- **How it works:** Each item carries a codicon, an optional route and a keybind action id whose shortcut is rendered beside the label. Items: **“New session”** (`sidebar.nav['new-session']`, icon `robot`, action `new-session`, keybind `session.new`); **“Capabilities”** (`sidebar.nav.skills`, icon `symbol-misc`, route `SKILLS_ROUTE`, keybind `nav.skills`); **“Messaging”** (`sidebar.nav.messaging`, icon `comment`, route `MESSAGING_ROUTE`, keybind `nav.messaging`); **“Artifacts”** (`sidebar.nav.artifacts`, icon `files`, route `ARTIFACTS_ROUTE`, keybind `nav.artifacts`); **“Scheduled jobs”** (`sidebar.nav.cron`, icon `watch`, route `CRON_ROUTE`, keybind `nav.cron`). Each has `data-tour="sidebar-nav-<id>"`.
- **Inputs / options:** Left-click activates. Right-click on New session or any route-backed item opens a context menu with the directional **“Open in split”** submenu (`sidebar.row.openInSplit`, `CONTEXT_SPLIT_KIT`), which opens a new session or that route as a tile in the chosen direction.
- **Outputs / side effects:** Navigation, or a new session/route tile.
- **Config / env:** n/a
- **Edge cases / guards:** The New-session row shows its keyboard shortcut as a `KbdGroup` that flashes to full opacity when the shortcut is used.
- **Rebuild notes:** n/a

### Sidebar session search  `id: desktop-b.sidebar-search`
- **Surface:** Desktop app
- **Where:** Under the nav rail. `SearchField` with aria-label **“Search sessions”** (`i18n: sidebar.searchAria`) and placeholder **“Search sessions…”** (`sidebar.searchPlaceholder`).
- **What it does:** Full-text searches every session, including ones not in the loaded page, and replaces the list with a **“Results”** section.
- **How it works:** Backend FTS results are converted to a minimal `SessionInfo` by `searchResultToSession` so they render in the same row component (resume works by id; the snippet stands in for the preview). The backend's FTS layer wraps matched terms in literal `>>>` / `<<<` markers (sqlite `snippet()` delimiters from `hermes_state_search.py`), and the sidebar renders the snippet as plain text, so `stripFtsMarkers()` (`apps/desktop/src/app/chat/sidebar/index.tsx:267`) removes them — otherwise a search for “foo” paints rows titled `>>>foo<<<`.
- **Inputs / options:** Type to search; **“Clear search”** (`sidebar.clearSearch`) clears it; the `session.focusSearch` keybind focuses it.
- **Outputs / side effects:** Swaps the Pinned/Sessions/messaging/Cron sections for a single **“Results”** section (`sidebar.results`).
- **Config / env:** n/a
- **Edge cases / guards:** While the query is in flight the section shows session skeletons; with no hits it shows **“No sessions match “{query}”.”** (`sidebar.noMatch`).
- **Rebuild notes:** Strip the search backend's highlight markers at the boundary.

### Pinned section  `id: desktop-b.sidebar-pinned`
- **Surface:** Desktop app
- **Where:** Sidebar section labelled **“Pinned”** (`i18n: sidebar.pinned`).
- **What it does:** Keeps chosen sessions at the top, in a manual order.
- **How it works:** Rendered by `SidebarSessionsSection` with `pinned` and `sortable` when more than one pin exists; reordering calls `reorderPinned` through the dnd sensors.
- **Inputs / options:** Drag to reorder; the row menu's Unpin; Shift-click a chat to pin (hint **“Shift-click a chat to pin”**, `sidebar.shiftClickHint`).
- **Outputs / side effects:** Persists the pin set and order.
- **Config / env:** n/a
- **Edge cases / guards:** Empty state is `SidebarPinnedEmptyState`. When everything is pinned the recents section shows **“Everything here is pinned. Unpin a chat to show it in recents.”** (`sidebar.allPinned`).
- **Rebuild notes:** n/a

### Sessions section (recents / projects / worktrees)  `id: desktop-b.sidebar-sessions`
- **Surface:** Desktop app
- **Where:** The main sidebar list, labelled **“Sessions”** (`i18n: sidebar.sessions`) or the entered project's name.
- **What it does:** The session list itself — flat recents, or grouped by project/workspace, with date or status dividers, load-more paging, and drag reordering.
- **How it works:** `SidebarSessionsSection` (`apps/desktop/src/app/chat/sidebar/sessions-section.tsx`) takes the grouping mode: `none` for archived and magnitude-ranked lists, `status` for the WORKING/DONE dividers, else `date`. Date dividers are produced by `sessionBucketLabel(bucket, t.sidebar.dateDivider)` (`apps/desktop/src/lib/time.ts:169`) from the calendar bucket `calendarBucket()` returns (`time.ts:106`), and read, verbatim and one per bucket kind: **“Earlier today”** (`i18n: sidebar.dateDivider.today`, bucket `today`, `dayDiff <= 0`), **“Yesterday”** (`i18n: sidebar.dateDivider.yesterday`, `dayDiff === 1`), **“Earlier this week”** (`i18n: sidebar.dateDivider.thisWeek`, on/after `startOfLocalWeek`), **“Last week”** (`i18n: sidebar.dateDivider.lastWeek`, the seven days before that), **“Earlier this month”** (`i18n: sidebar.dateDivider.thisMonth`, same calendar month and year); older buckets fall through to an `Intl.DateTimeFormat` month (`month`) or month+year (`monthYear`) string with no i18n key. The same five labels serve BOTH renderers — the virtualized list (`virtual-session-list.tsx:79` reads `t.sidebar.dateDivider`, `:133` calls `sessionBucketLabel`) and the plain section (`sessions-section.tsx:218` / `:311`) — so a bucket never renders two different words depending on whether virtualization kicked in. The newest run of sessions is the UNLABELLED head (see `session-date-groups.ts`), which is what makes “Earlier today” truthful. Status dividers read **“Working”** and **“Done”** (`sidebar.statusDivider.*`); status dividers read **“Working”** and **“Done”** (`sidebar.statusDivider.*`). The section is the single authority on whether the virtual list owns scrolling — it neutralises the wrapper scroller itself when it virtualises, because gating that on the index's parallel guess desynced the two and left the list with no scroller at all under Updated grouping (comment at `sidebar/index.tsx:1667`). Only the flat list may swap its dividers for WORKING/DONE; project lanes stay chronological.
- **Inputs / options:** Header actions (right-aligned cluster): **“Mark all as read”** (`sidebar.markAllRead`, `check-all` icon) when anything is unread — it calls both `markAllSessionsRead()` and `ackAllSessionsRead()`, because acking the persisted layer too is what stops the next list refresh repainting every dot just dismissed; a **“+”** button labelled **“New project”** (`sidebar.projects.newButton`) when grouped or **“New session”** (`sidebar.nav['new-session']`) when flat; and the filter menu. Inside a project the cluster becomes: a **“New worktree”** start-work button, the project menu, and a **“Show projects”** (`sidebar.showProjects`, `list-unordered` icon) back button. A **“Load more”** footer row (`sidebar.loadMore`, or **“Load {step} more”**, `sidebar.loadCount`) appears when more sessions exist — hidden when workspace-grouped, since those groups page themselves, while profile groups do not.
- **Outputs / side effects:** Selects, reorders, pages, and opens sessions.
- **Config / env:** Grouping/ordering/row-meta live in the layout store (see the filter menu).
- **Edge cases / guards:** Empty copy depends on context: **“No sessions yet”** (`sidebar.projectEmpty`) inside a project, **“No sessions match these filters”** (`sidebar.noFilterMatches`) with filters on, **“Everything here is pinned…”** when only pins exist, else **“No sessions yet”** (`sidebar.noSessions`). Reordering and project reordering are disabled while showing all profiles. Group aria labels: **“Group sessions by workspace”** / **“Show sessions as a single list”** (`sidebar.groupAriaUngrouped` / `groupAriaGrouped`) with titles **“Group by workspace”** / **“Ungroup sessions”** — full keys `sidebar.groupAriaUngrouped`, `sidebar.groupAriaGrouped`, `sidebar.groupTitleUngrouped`, `sidebar.groupTitleGrouped`, plus the flat-list return label **“Show sessions”** (`i18n: sidebar.showSessions`), the sibling of **“Show projects”** (`i18n: sidebar.showProjects`); in v2026.8.31 only `sidebar.showProjects` still has a call site (`apps/desktop/src/app/chat/sidebar/index.tsx:1753`) — see `gapfill-desktop-b-0-r0.sidebar-group-toggle`. A scanning worktree grouping shows a loading glyph labelled **“Loading…”** (`sidebar.loading`).
- **Rebuild notes:** One authority for “who scrolls”.

### Session row  `id: desktop-b.sidebar-session-row`
- **Surface:** Desktop app
- **Where:** Every row in the Pinned / Sessions / Results / messaging sections. Component `apps/desktop/src/app/chat/sidebar/session-row.tsx`.
- **What it does:** Shows a session's status dot, title, meta and unread state, and is the click target that opens it.
- **How it works:** Title falls back to **“Chat {id}”** (`sidebar.row.untitledChat`). Meta lines can show **“{n} message(s)”** (`sidebar.row.messageCount`), **“{n} tool call(s)”** (`sidebar.toolCallCount`), **“Tasks completed”** (`sidebar.row.todoProgress`), and relative ages using the compact units **“now”**, **“d”**, **“h”**, **“m”** (`sidebar.row.ageNow|ageDay|ageHour|ageMin`).
- **Inputs / options:** Click opens in place; ⌘/Ctrl-click opens as a tab; ⌘⇧-click opens in a new window (see `openSessionIntentFromModifiers`). Shift-click pins. Right-click opens the session context menu.
- **Outputs / side effects:** Opens/pins the session.
- **Config / env:** n/a
- **Edge cases / guards:** Status tooltips: **“Session running”** (`sidebar.row.sessionRunning`), **“Needs your input”** (`needsInput`), **“Waiting for your answer”** (`waitingForAnswer`), **“Finished — unread”** (`finishedUnread`), **“Background task running”** (`backgroundRunning`), **“Draft — nothing sent yet”** (`draftSession`), **“Handed off from {platform}”** (`handoffOrigin`), **“Profile: {profile}”** (`ownedByProfile`). Full keys for the dot's own aria-label/title pairs, which are rendered by `SessionStatusDot` (`apps/desktop/src/app/chat/session-status-dot.tsx`) rather than by the row: `sidebar.row.sessionRunning`, `sidebar.row.needsInput`, `sidebar.row.waitingForAnswer` (title of the amber `needs-input` dot, `session-status-dot.tsx:36`), `sidebar.row.finishedUnread` (aria-label + title of the emerald `unread` dot, `:67` and `:70`), `sidebar.row.backgroundRunning` (aria-label + title of the hollow-muted `background` dot, `:57` and `:60`), `sidebar.row.draftSession` (aria-label + title of the hollow-grey `draft` dot, `:77` and `:79`) — full mechanism in `gapfill-desktop-b-0-r0.session-status-dot`.
- **Rebuild notes:** n/a

### Session actions menu  `id: desktop-b.sidebar-session-menu`
- **Surface:** Desktop app
- **Where:** The `…` button on a session row, the row's right-click menu, a session tab's menu, and the chat header. Aria-label **“Session actions”** (`i18n: sidebar.row.sessionActions`). Component `apps/desktop/src/app/chat/sidebar/session-actions-menu.tsx`.
- **What it does:** Every per-session verb, grouped: open, identity, work, tab, danger.
- **How it works:** `useSessionActions` builds five item groups separated by dividers (`session-actions-menu.tsx:184`). **OPEN:** **“Open in new tab”** (`sidebar.row.openInNewTab`, `browser`) — omitted on a tab surface and when the session is already tabbed or selected; **“New window”** (`sidebar.row.newWindow`, `link-external`) when the bridge supports session windows; **“Open in terminal”** (`sidebar.row.openInTerminal`, `terminal`) which resumes the session in the TUI in the user's *own* terminal, hidden on a remote connection because the emulator would open on this machine while the session lives on the remote host. **IDENTITY:** **“Rename…”** (`sidebar.row.rename`, `edit`); **“Pin”** / **“Unpin”** (`sidebar.row.pin` / `unpin`, `pin`); one read-state item — **“Mark as read”** / **“Mark as unread”** (`sidebar.row.markRead` / `markUnread`) with a `mail-read`/`mail` icon (the codicon font has `mail` and `mail-read` but no `mail-unread` glyph) — driven by *both* the transient finished-unread dot and the backend watermark; an **“Appearance”** submenu (`sidebar.projects.menuAppearance`, `symbol-color`) holding the colour swatches; and **“Copy ID”** (`sidebar.row.copyId`). **WORK:** **“Branch”** (`sidebar.row.branchFrom`, `repo-forked` — this codicon font has no `git-fork`, only `git-fork-private`); **“Export”** (`sidebar.row.export`, `cloud-download`) via `exportSession`; and a **“Move to project”** submenu (`sidebar.projects.moveToProject`, `folder`). **TAB** (tab surfaces only): **“Reload”** (`zones.reload`), **“Close”** (`common.close`), **“Close others”** (`zones.closeOthers`), **“Close to the right”** (`zones.closeToRight`), **“Close all”** (`zones.closeAll`). **DANGER:** **“Archive”** (`sidebar.row.archive`, `archive`) and **“Delete”** (`common.delete`, `trash`, destructive). A trailing **“Hide tab bar”** (`sidebar.row.hideTabBar`, `eye-closed`) appears on the main tab.
- **Outputs / side effects:** As each verb. Move-to-project calls `moveSessionToProject` and toasts **“Moved to {name}”** (`sidebar.projects.movedTo`) or **“Could not move session”** (`moveFailed`); with no eligible target the submenu shows a disabled **“No other projects”** (`moveNoProjects`), and a project without a folder gives **“That project has no folder to move into”** (`moveNoFolder`). Copy failure toasts **“Could not copy session ID”** (`sidebar.row.copyIdFailed`). Full keys for these three, with their exact call sites: **“Could not move session”** = `sidebar.projects.moveFailed` (`apps/desktop/src/app/chat/sidebar/session-actions-menu.tsx:174`), **“No other projects”** = `sidebar.projects.moveNoProjects` (`session-actions-menu.tsx:162`), **“That project has no folder to move into”** = `sidebar.projects.moveNoFolder` (thrown by `moveSessionToProject`, `apps/desktop/src/store/projects.ts:623`) — see `gapfill-desktop-b-0-r0.move-session-to-project`. The read-state item's two labels in full: **“Mark as unread”** = `sidebar.row.markUnread` and **“Mark as read”** = `sidebar.row.markRead` (`session-actions-menu.tsx:315`, handler at `:201`); a failed watermark write toasts **“Could not update unread state”** (`i18n: sidebar.row.unreadFailed`, `apps/desktop/src/app/chat/sidebar/index.tsx:405`) — mechanism in `gapfill-desktop-b-0-r0.session-unread-toggle`.
- **Config / env:** n/a
- **Edge cases / guards:** The Appearance and Move-to-project submenus are separate components so **only an open submenu** subscribes to `$sessionColorOverrides` / `$projectTree` / `$sessions` — otherwise every row's menu would re-render the sidebar on each session update (comment at `session-actions-menu.tsx:126`). The colour override is keyed by the **durable** session id (`sessionPinId`) so it survives compression, and clearing it falls back to the inherited project colour (clear label **“No color”**, `sidebar.projects.noColor`). Rename suppresses exactly one Radix focus-restore (`onCloseAutoFocus`), because the restore would put focus on the row's own button, where Space would select the session and arrows would move the list instead of the caret.
- **Rebuild notes:** Subscribe inside submenus, not in the menu root.

### Rename session dialog  `id: desktop-b.sidebar-rename-session`
- **Surface:** Desktop app
- **Where:** Session menu → **“Rename…”**. Dialog title **“Rename session”** (`i18n: sidebar.row.renameTitle`).
- **What it does:** Renames a chat (or clears the title back to untitled).
- **How it works:** `renameSessionPreferringRpc()` (`apps/desktop/src/app/chat/sidebar/session-actions-menu.tsx:69`) prefers the gateway RPC `session.title {session_id, title}` over REST — a freshly *branched* session (and any brand-new chat) lives only in the gateway's in-memory `_sessions` map keyed by its **runtime** id with no row in `state.db` until the first turn, so `PATCH /api/sessions/{id}` 404s with “Session not found”, while the RPC resolves the live runtime session and persists the row on demand. The RPC path is taken **only** for the active/selected row (its runtime id is known and it lives on the active gateway, so there is no profile-routing ambiguity); every other row keeps REST, which handles profile scoping, and clears stay on REST because the RPC rejects empty titles. An RPC failure logs a warning and falls through to REST.
- **Inputs / options:** One autofocused input (its text is selected on open), placeholder **“Untitled session”** (`sidebar.row.untitledPlaceholder`); Enter submits (guarded against IME composition), Escape closes; footer **“Cancel”** (`common.cancel`) and **“Save”** (`common.save`). The description **“Leave empty to clear.”** (`sidebar.row.renameDesc`) documents the clear behaviour.
- **Outputs / side effects:** Updates the row in `$sessions` and toasts **“Renamed”** (`sidebar.row.renamed`) for 2 s; failure toasts **“Rename failed”** (`sidebar.row.renameFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** An unchanged title closes silently.
- **Rebuild notes:** Have one rename entry point that knows about not-yet-persisted sessions.

### Delete session confirmation  `id: desktop-b.sidebar-delete-session`
- **Surface:** Desktop app
- **Where:** Session menu → **“Delete”**. Title **“Delete session?”** (`i18n: sidebar.row.deleteTitle`), description **“This will permanently delete “{title}”. This cannot be undone.”** (`sidebar.row.deleteDesc`).
- **What it does:** Permanently deletes a chat.
- **How it works:** A thin wrapper over `ConfirmDialog` and the single choke point for every delete entry point (sidebar rows, tab menus, the chat header), so all of them get the guard for free (`session-actions-menu.tsx:558`).
- **Inputs / options:** **“Delete”** (`common.delete`, destructive) with busy label **“Deleting…”** (`sidebar.row.deleting`) and done label **“Session deleted”** (`sidebar.row.deleted`); Enter confirms.
- **Outputs / side effects:** Deletes the session.
- **Config / env:** n/a
- **Edge cases / guards:** Added because deleting is irreversible and the desktop used to fire it instantly on click, unlike the CLI's y/N prompt (#61470).
- **Rebuild notes:** n/a

### Sidebar filter menu  `id: desktop-b.sidebar-filter-menu`
- **Surface:** Desktop app
- **Where:** The `list-filter` icon button in the Sessions section header, aria-label **“Filters”**. Component `SidebarFilterMenu`, `apps/desktop/src/app/chat/sidebar/filter-menu.tsx:151`.
- **What it does:** Controls how the session list is grouped, ordered, annotated and filtered.
- **How it works:** Every option row — single or multi select — calls `event.preventDefault()` so the menu **stays open** and a whole view can be configured in one pass; only the actions at the bottom dismiss it (`filter-menu.tsx:123`).
- **Inputs / options:** **“Grouping”** submenu (radio, current value shown inline on the trigger): **“Updated”** (`date`, `clock`), **“Project”** (`project`, `root-folder`), **“Status”** (`status`, `pulse`), **“Profile”** (`profile`, `account`). **“Ordering”** submenu (radio): **“Updated”** (`updated`, `clock`), **“Created”** (`created`, `add`), **“Status”** (`status`, `pulse`), **“Tokens”** (`tokens`, `symbol-numeric`), **“Cost”** (`cost`, `credit-card`), **“Manual”** (`manual`, `list-ordered`). **“Show”** submenu (checkboxes, row meta): **“Updated”**, **“Preview”**, **“Tokens”**, **“Cost”**, **“PR”**, **“Profile”**. A top-level checkbox **“Inbox style”** (`card-rows`, `inbox`) — a render variant (three-line cards: project · age / title / model · size) that composes with any grouping. Separator, then label **“Filters”**: a **“Status”** submenu with checkboxes **“Needs input”**, **“Working”**, **“Unread”**, **“Draft”**, **“Idle”** (each with the row's own status-dot class); a **“Pull request”** submenu with **“Open”**, **“Draft”**, **“Merged”**, **“Closed”**, **“No PR”**; a **“Profile”** submenu listing each profile as a checkbox plus the actions **“New profile”** (`profiles.newProfile`) and **“Import profile…”** (`profiles.importProfile`); a **“Project”** submenu (only with more than one project) listing each project, with the synthetic Home bucket labelled **“Home”** (`sidebar.projects.home`); a checkbox **“All profiles”** (`profiles.allProfiles`); a checkbox **“Archived”**; and, when the view has been customised, **“Reset to defaults”**. Separator, then **“Collapse all”** / **“Expand all”** (project grouping only) and **“Mark all as read”** (disabled when nothing is unread).
- **Outputs / side effects:** Writes the layout store (`setSidebarGrouping`, `setSidebarOrdering`, `toggleSidebarRowMeta`, `setSidebarCardRows`, `toggleSidebarStatusFilter`, `toggleSidebarPrFilter`, `toggleSidebarProfileFilter`, `toggleSidebarProjectFilter`, `toggleShowAllProfiles`, `setSidebarShowArchived`, `resetSidebarView`, `setWorkspaceNodesOpen`).
- **Config / env:** All persisted in the layout store.
- **Edge cases / guards:** **“Manual”** ordering only appears once a hand-picked order exists (dragging a row is what selects it), so it is a way *out*, never a way in. **“Cost”** — both the ordering and the row-meta option — stays hidden until some session actually reports spend. **“Preview”** row-meta only appears in Inbox style, because the one-line row has nowhere to put it. The whole **“Pull request”** submenu is hidden when `gh` is unavailable (a remote backend) rather than filtering everything out; `prAvailable` is resolved per render, not once at module load, because switching to a remote profile swaps the bridge underneath. Per-profile filter checkboxes only appear when showing all profiles **and** more than one profile exists — scoped to one profile the rail is already the filter. The **“All profiles”** checkbox stays visible while it is on even at one profile, or deleting your way down to a single profile would strand the sidebar in a mode nothing can leave. Trigger styling: active filters render as “engaged” (`--ui-control-active-background`), never as an accent, which the sidebar reserves for a session that is actually doing something.
- **Rebuild notes:** Keep the menu open across option changes; hide options that cannot apply instead of showing dead ones.

### Projects (sidebar workspaces)  `id: desktop-b.sidebar-projects`
- **Surface:** Desktop app
- **Where:** Sidebar section label **“Projects”** (`i18n: sidebar.projects.sectionLabel`) when grouping is by project/workspace. Files under `apps/desktop/src/app/chat/sidebar/projects/`.
- **What it does:** Groups sessions by the folder(s) they belong to, lets you create/rename/delete projects, add folders, set the active project, and navigate into a project's own lane view.
- **How it works:** The project tree lives in `$projectTree` (`store/projects`); an "auto" project is discovered from a session's cwd and has no materialised record, while an explicit project is a saved record with one or more folders. `workspace-groups.ts` builds the grouped model, `workspace-header.tsx` / `workspace-group.tsx` render the lanes, `overview-row.tsx` renders the overview previews, `entered-content.tsx` renders the in-project view, and `project-appearance.tsx` the colour picker.
- **Inputs / options:** **“New project”** (`sidebar.projects.newButton`); a **“Home”** bucket (`sidebar.projects.home`) for sessions with no project; **“Open {label}”** (`sidebar.projects.enter`) and **“Reorder {label}”** (`reorder`) row affordances; **“Show/Hide {label} sessions”** (`toggle`); **“All projects”** (`back`) to leave a project; **“New session in {label}”** (`sidebar.newSessionIn`) and **“Show {n} more in {label}”** (`sidebar.showMoreIn`).
- **Outputs / side effects:** Creates/updates project records and re-homes sessions.
- **Config / env:** Repo discovery is governed by `desktop.repo_scan_enabled` / `desktop.repo_scan_roots` (documented in the `desktop-settings` shard).
- **Edge cases / guards:** Creating a project against an out-of-date backend shows **“Update the Hermes backend to create projects — your backend is older than this desktop app (Settings → Updates → Backend).”** (`sidebar.projects.staleBackend`); failure toasts **“Could not create project”** (`createFailed`).
- **Rebuild notes:** n/a

### Project menu  `id: desktop-b.sidebar-project-menu`
- **Surface:** Desktop app
- **Where:** The `…` on a project row / the project header, aria-label **“Actions”** (`i18n: sidebar.projects.menu`). Component `apps/desktop/src/app/chat/sidebar/projects/project-menu.tsx`.
- **What it does:** Rename, add a folder, set active, reveal/copy the path, change the colour, and delete or hide the project.
- **How it works:** Identity items exist only for explicit projects — an auto project has no materialised record to rename or re-home (comment at `project-menu.tsx:76`).
- **Inputs / options:** **“Rename…”** (`sidebar.projects.menuRename`, `edit`); **“Add folder”** (`menuAddFolder`, `new-folder`); **“Set active”** (`menuSetActive`, `target`, disabled when already active); **“Reveal in folder”** (full key `sidebar.projects.reveal`, icon `folder-opened`, `onSelect: () => void revealPath(project.path)`, disabled when the project has no path — `apps/desktop/src/app/chat/sidebar/projects/project-menu.tsx:103`; the identical item is repeated on a worktree/workspace header at `projects/workspace-header.tsx:93`); **“Copy path”** (`copyPath`, `copy`); an **“Appearance”** entry (`menuAppearance`) whose picker chrome differs per surface (popover on one, submenu on the other); and a destructive last item — **“Hide from sidebar”** (`removeFromSidebar`, `trash`) for an auto project, or **“Delete…”** (`menuDelete`, `trash`) for an explicit one.
- **Outputs / side effects:** Delete opens a confirm titled `Delete "{label}"?` with the body **“This removes the saved project from Hermes. Files, git repos, and worktrees stay untouched.”** (`sidebar.projects.deleteConfirm`) and confirm label **“Delete”**; hiding an auto project calls `dismissAutoProject`. Both exit the project scope when performed from inside it.
- **Config / env:** n/a
- **Edge cases / guards:** Path items are disabled when the project has no path.
- **Rebuild notes:** n/a

### Project dialog (create / rename / add folder)  `id: desktop-b.sidebar-project-dialog`
- **Surface:** Desktop app
- **Where:** Titles **“New project”** (`i18n: sidebar.projects.createTitle`), **“Rename project”** (`renameTitle`) or **“Add folder”** (`addFolderTitle`). Component `apps/desktop/src/app/chat/sidebar/project-dialog.tsx`.
- **What it does:** Names a workspace, attaches one or more folders to it, and optionally records what the project is about.
- **How it works:** One dialog with three modes, chosen at `project-dialog.tsx:149` as `mode === 'rename' ? p.renameTitle : mode === 'add-folder' ? p.addFolderTitle : p.createTitle`. Full title keys: **“New project”** = `sidebar.projects.createTitle`, **“Rename project”** = `sidebar.projects.renameTitle` (`project-dialog.tsx:149`), **“Add folder”** = `sidebar.projects.addFolderTitle`. Create mode — and only create mode — shows the `DialogDescription` **“Name a workspace and add one or more folders.”** (full key `sidebar.projects.createDesc`, `project-dialog.tsx:156`).
- **Inputs / options:** A name input, placeholder **“e.g. Skunkworks”** (`namePlaceholder`). A **“Folders”** (`foldersLabel`) list — empty state **“No folders added yet.”** (`noFolders`), an **“Add folder”** button (`addFolder`), a **“primary”** badge (`primaryBadge`) on the first folder, and a **“Remove”** control per row (`removeFolder`). An **“Idea”** field (`ideaLabel`) with placeholder **“What's this project about? (saved to IDEA.md)”** (`ideaPlaceholder`), a sparkle **“Generate idea”** / **“Generating…”** button (`ideaGenerate` / `ideaGenerating`) and a **“Shuffle templates”** button (`ideaShuffle`). Footer: **“Create”** (`create`) or **“Save”** (`common.save`) in rename mode.
- **Inputs / options (full i18n keys):** name input placeholder **“e.g. Skunkworks”** = `sidebar.projects.namePlaceholder` (`project-dialog.tsx:172`, autofocused, Enter submits, Escape closes, disabled while submitting); folder-list empty state **“No folders added yet.”** = `sidebar.projects.noFolders` (`project-dialog.tsx:182`); idea textarea placeholder **“What's this project about? (saved to IDEA.md)”** = `sidebar.projects.ideaPlaceholder` (`project-dialog.tsx:239`); dice button tooltip **and** aria-label **“Shuffle templates”** = `sidebar.projects.ideaShuffle` (`project-dialog.tsx:264` and `:266`, icon `refresh`, `onClick: () => setTemplates(randomIdeaTemplates())`) — see `gapfill-desktop-b-0-r0.project-idea-templates` for the 18 template pills it cycles.
- **Outputs / side effects:** Creates or updates the project record and writes `IDEA.md`; failures toast **“Could not create project”** (`createFailed`). That fallback is the full key `sidebar.projects.createFailed`, raised through `notifyError` on **both** write paths of this dialog: the shared `runSubmit()` wrapper around create/rename/add-folder (`project-dialog.tsx:84`) and the OS folder-picker leg `pickFolder()` (`project-dialog.tsx:108`).
- **Config / env:** n/a
- **Edge cases / guards:** See the stale-backend message above.
- **Rebuild notes:** n/a

### Worktree dialog (“New worktree” / “Convert a branch”)  `id: desktop-b.sidebar-worktree-dialog`
- **Surface:** Desktop app
- **Where:** Project header **“New worktree”** (`i18n: sidebar.projects.startWork`), the `workspace.newWorktree` keybind, or the composer's coding row. One mount for the whole app. Component `apps/desktop/src/app/chat/sidebar/projects/worktree-dialog.tsx`.
- **What it does:** Creates a git worktree for a new branch — or converts an existing branch into one — and starts a session anchored there.
- **How it works:** Two modes. **New worktree:** title **“New worktree”** (`newWorktreeTitle`), description **“Name the branch for this worktree.”** (`newWorktreeDesc`), a branch-name input with placeholder **“e.g. my-feature”** (`branchPlaceholder`), and a base-branch picker rendered as “branch off ” + the picker (`branchOff`, placeholder **“Search branches…”**, `baseBranchPlaceholder`, empty **“No branches found”**, `baseBranchNone`). **Convert a branch:** title **“Convert a branch”** (`convertBranchTitle`), description **“Open checked-out branches, or create a worktree for a free branch.”** (`convertBranchDesc`), a searchable branch list (placeholder **“Search branches…”**, `convertBranchPlaceholder`; empty state **“Loading branches…”** / **“No branches found”**, `branchesLoading` / `noBranches`) where each branch offers the action that fits it: **“open”** (`branchOpenExisting`), **“switch home”** (`branchSwitchHome`), **“new worktree”** (`branchCreateWorktree`) or **“track remote”** (`branchTrackRemote`). A **“Project”** picker (`worktreeProjectLabel`, placeholder **“Search projects…”**, `worktreeProjectPlaceholder`, empty **“No projects with a folder”**, `worktreeProjectNone`) selects the repo when the caller did not.
- **Inputs / options:** Link **“Convert an existing branch”** (`convertBranchInstead`) toggles modes; primary button **“New worktree”** (`startWork`).
- **Inputs / options (full i18n keys, per call site in `apps/desktop/src/app/chat/sidebar/projects/worktree-dialog.tsx`):** Title in create mode **“New worktree”** = `sidebar.projects.newWorktreeTitle` and in convert mode **“Convert a branch”** = `sidebar.projects.convertBranchTitle`, both at `worktree-dialog.tsx:221`. `DialogDescription` in create mode **“Name the branch for this worktree.”** = `sidebar.projects.newWorktreeDesc` and in convert mode **“Open checked-out branches, or create a worktree for a free branch.”** = `sidebar.projects.convertBranchDesc`, both at `worktree-dialog.tsx:222`. Branch-name `SanitizedInput` placeholder **“e.g. my-feature”** = `sidebar.projects.branchPlaceholder` (`worktree-dialog.tsx:321`, sanitised through `gitRef`, Enter submits, Escape closes; the copy alias `p = t.sidebar.projects` is bound at `worktree-dialog.tsx:69`). Base-branch combobox placeholder **“Search branches…”** = `sidebar.projects.baseBranchPlaceholder` (`projects/base-branch-picker.tsx:124`) with `CommandEmpty` **“No branches found”** = `sidebar.projects.baseBranchNone` (`base-branch-picker.tsx:126`); the picker's props are declared at `base-branch-picker.tsx:30`. Project selector `CommandInput` placeholder **“Search projects…”** = `sidebar.projects.worktreeProjectPlaceholder` (`worktree-dialog.tsx:246`) with `CommandEmpty` **“No projects with a folder”** = `sidebar.projects.worktreeProjectNone` (`worktree-dialog.tsx:248`); it is rendered only when `projectOptions.length > 1`. Convert-mode branch list `CommandInput` placeholder **“Search branches…”** = `sidebar.projects.convertBranchPlaceholder` (`worktree-dialog.tsx:282`, disabled while a convert is `pending`), whose `CommandEmpty` renders **“Loading branches…”** = `sidebar.projects.branchesLoading` while `branchesLoading` is true and **“No branches found”** = `sidebar.projects.noBranches` once loading has finished (both at `worktree-dialog.tsx:284`). Per-branch action hints come from `branchActionLabel()` (`worktree-dialog.tsx:42`, rendered at `:300`): a checked-out branch → **“open”** (`sidebar.projects.branchOpenExisting`), a remote-only branch → **“track remote”** (`sidebar.projects.branchTrackRemote`), otherwise `branch.isDefault ? branchSwitchHome : branchCreateWorktree` — the repo's default branch shows **“switch home”** (`sidebar.projects.branchSwitchHome`, copy interface declared at `worktree-dialog.tsx:38`, resolved at `:51`) because selecting it runs `switchBranchInRepo(repoPath, branch.name)` on the home checkout instead of cutting a worktree, and every other branch shows **“new worktree”** (`sidebar.projects.branchCreateWorktree`). The mode-switch footer link **“Convert an existing branch”** = `sidebar.projects.convertBranchInstead` (`worktree-dialog.tsx:358`, `variant="link"`, calls `enterConvert()` which flips `convertMode` and kicks `loadBranches()`); the composer's coding/git row opens the same dialog straight into convert mode via the menu entry **“Convert a branch…”** = `sidebar.projects.convertBranch` (`apps/desktop/src/app/chat/composer/status-stack/coding-row.tsx:196`, alias bound at `coding-row.tsx:66`).
- **Outputs / side effects:** Creates the worktree and opens a session in it. Failures toast **“Could not create worktree”** (`startWorkFailed`) — full key `sidebar.projects.startWorkFailed`, raised on **both** submit paths: the new-branch `submit()` (`worktree-dialog.tsx:177`) and the convert-branch `convert()` (`worktree-dialog.tsx:206`); an old backend gives **“Update the Hermes backend to create worktrees over this remote connection — it predates the git worktree API.”** (`worktreeStaleBackend`).
- **Config / env:** n/a
- **Edge cases / guards:** Removing a worktree (`removeWorktree`) asks **“Remove it from git (deletes the worktree directory; the branch stays), or just hide the lane from the sidebar and leave the worktree on disk.”** (`removeWorktreeConfirm`), or, when dirty, **“This worktree has uncommitted changes. Force-remove it (discards those changes), or just hide the lane and keep it on disk.”** (`removeWorktreeDirty`) with a **“Force remove”** option (`forceRemove`); failure toasts **“Could not remove worktree (uncommitted changes?)”** (full key `sidebar.projects.removeWorktreeFailed`, raised at `apps/desktop/src/app/chat/sidebar/projects/entered-content.tsx:155` only when the failure is *not* the force-retry case — a dirty/locked failure opens the force confirm instead; see `gapfill-desktop-b-0-r0.worktree-remove`). `openWorktreeDialog()` resolves the target itself and does nothing when no repo is in reach, so the keybind also works from a detached session that merely sits inside a project (comment at `use-keybinds.ts:227`).
- **Rebuild notes:** n/a

### Sidebar cron-jobs section  `id: desktop-b.sidebar-cron-section`
- **Surface:** Desktop app
- **Where:** Sidebar section **“Cron jobs”** (`i18n: sidebar.cronJobs`). Component `apps/desktop/src/app/chat/sidebar/cron-jobs-section.tsx`.
- **What it does:** Lists the scheduled jobs with a live next-run countdown, and lets each be triggered, paused/resumed, managed, expanded to its runs, or deleted — without leaving the sidebar.
- **How it works:** Row meta is the localized state name for an inactive job (`cron.states[state]`) and a relative next-run time otherwise, or `—`. Row status pips reuse `STATE_DOT` from `job-state.ts`, so the section and the Cron page never drift.
- **Inputs / options:** Row context menu (aria **“Cron job actions”**, `cron.actionsTitle`) with **“Trigger now”** (`cron.triggerNow`, `zap`), **“Resume cron”** / **“Pause cron”** (`cron.resume` / `cron.pause`), **“Manage”** (`cron.manage`, `watch`) and delete. Hover buttons for **“Trigger now”** and **“Manage”**. A disclosure toggle labelled **“Show runs”** / **“Hide runs”** (`cron.showRuns` / `hideRuns`) expands the job's run sessions inline.
- **Outputs / side effects:** Same API calls and toasts as the Cron page (**“Cron resumed”**, **“Cron paused”**, **“Cron deleted”**, **“Failed to update cron job”**, **“Failed to delete cron job”**). **“Manage”** sets `$cronFocusJobId` and opens the Cron view scrolled to that job.
- **Config / env:** n/a
- **Edge cases / guards:** While runs load, a glyph spinner labelled **“Loading cron jobs...”** (`cron.loading`); with none, **“No runs yet”** (`cron.noRuns`). The disclosure toggle is `SidebarRowBody` itself, carrying `aria-expanded={expanded}` and `aria-label={expanded ? c.hideRuns : c.showRuns}` (`apps/desktop/src/app/chat/sidebar/cron-jobs-section.tsx:354`) — verbatim **“Show runs”** (`i18n: cron.showRuns`) while collapsed and **“Hide runs”** (`i18n: cron.hideRuns`) while expanded. The delete confirm assembles its description as `deleteDescPrefix + jobLabel + deleteDescSuffix` — verbatim **“This will remove ”** (`i18n: cron.deleteDescPrefix`) + the job title + **“ permanently. It will stop firing immediately.”** (`i18n: cron.deleteDescSuffix`) — under the title **“Delete cron job?”** (`i18n: cron.deleteTitle`), identically in the sidebar (`cron-jobs-section.tsx:266`) and on the Cron page (`apps/desktop/src/app/cron/index.tsx:738`, where the title is truncated to 60 chars and rendered in a bolded span). On the Cron page the dialog is a `ConfirmDialog` with `busyLabel={c.deleting}` (`apps/desktop/src/app/cron/index.tsx:730-731`), so while `handleConfirmDelete()` is awaiting `deleteCronJob(id)` the destructive confirm button swaps its label from **“Delete”** (`i18n: common.delete`) to the spinner + **“Deleting...”** (`i18n: cron.deleting`), then to **“Done”** (`i18n: common.done`) for the 600 ms done-beat before the dialog closes; the sidebar copy of the dialog goes through the imperative `confirm()` helper (`cron-jobs-section.tsx:263-269`), which passes no `busyLabel`, so it never shows **“Deleting...”**.
- **Rebuild notes:** n/a

### Profile rail  `id: desktop-b.sidebar-profile-rail`
- **Surface:** Desktop app
- **Where:** The strip at the bottom of the sidebar. Component `ProfileRail` in `apps/desktop/src/app/chat/sidebar/profile-switcher.tsx`, aria-label **“Profiles”** (`i18n: profiles.title`).
- **What it does:** Switches the whole app between profiles (and, on a multi-gateway desktop, between agents on different machines), and offers per-profile actions.
- **How it works:** Pills for the default profile and each named profile, plus an **“All profiles”** pill (`profiles.allProfiles`, `layers` glyph) that turns on the all-profiles view. On a multi-connection desktop the rail groups by gateway using the union agent roster: a divider per gateway labelled **“Profiles on {gateway}”** (full key `profiles.fleet.gateway`) or **“{gateway} · unreachable”** (full key `profiles.fleet.gatewayUnreachable`, with an amber dot), with **“All profiles on this gateway”** (full key `profiles.fleet.allOnGateway` — the pinned `layers`-glyph pill rendered inside each gateway group at `apps/desktop/src/app/chat/sidebar/profile-switcher.tsx:409-416`, calling `setShowAllProfiles(true)` for that gateway) and per-agent pills labelled **“{name} · {gateway}”** (full key `profiles.fleet.onGateway`).
- **Inputs / options:** Click a pill to switch (aria **“Switch to {name}”**, `profiles.switchToProfile`, or **“Switch to {name} on {gateway}”**, full key `profiles.fleet.switchTo`; a delete confirmation appends **“ on {gateway}”**, full key `profiles.fleet.deleteOn`). In the **non-fleet** multi-profile case the rail instead renders a single toggle pill (`profile-switcher.tsx:418-432`): while scoped to the default profile it reads **“Show all profiles”** (`i18n: profiles.showAllProfiles`, `layers`/`home` glyph, `setShowAllProfiles(true)`), and anywhere else (all-profiles view or a named profile) it flips to **“Switch to {name}”** (`profiles.switchToProfile`) so leaving a profile never lands on the all view; with no default profile at all that same slot falls back to the **“All profiles”** pill (`profiles.allProfiles`). **“New profile”** (`profiles.newProfile`) and **“Import profile…”** (`profiles.importProfile`) buttons. An overflow pill **“Manage profiles…”** (`profiles.manageProfiles`, `ellipsis` glyph) navigating to `/profiles`, and **“Manage gateways…”** (`profiles.connectGateway`). Each pill's own menu (aria **“Actions”**, `profiles.actions`) offers **“Color”** (`profiles.color`, with swatches labelled **“Set color {color}”** / **“Auto”**, `setColor` / `autoColor`, and the picker aria **“Color”**, `colorFor`), **“Rename…”** (`renameMenu`), **“Edit SOUL.md…”** (`editSoul`), **“Export…”** (`exportMenu`), and **“Connect to a remote host…”** (full key `profiles.remoteOverride.menuItem`, `globe` codicon, rendered at `apps/desktop/src/app/chat/sidebar/profile-switcher.tsx:1328` only when the rail was given an `onConnectRemote` handler) — replaced by the badge **“Runs on {host}”** (`profiles.remoteOverride.badge`) once one is set.
- **Outputs / side effects:** Switches the active profile/gateway, opens dialogs, exports a profile. A failed connection switch toasts **“Could not connect to {name}”** (`profiles.switchConnectionFailed`).
- **Config / env:** Profile colours persist in `$profileColors`.
- **Edge cases / guards:** The rail hides its switcher when only one profile exists. The inline SOUL editor shows **“{name} · {gateway} · SOUL.md”** as its header and saves with **“Save SOUL.md”** / **“Saving...”**, toasting **“SOUL.md saved”** (`profiles.soulSaved`) or **“Failed to load/save SOUL.md”**.
- **Rebuild notes:** n/a

### Profile remote-override dialog  `id: desktop-b.sidebar-profile-remote-override`
- **Surface:** Desktop app
- **Where:** Profile pill menu → **“Connect to a remote host…”**. Title **“Connect {profile} to a remote host”** (`i18n: profiles.remoteOverride.title`). Component `apps/desktop/src/app/chat/sidebar/profile-remote-override-dialog.tsx`.
- **What it does:** Points one profile's sessions at a remote Hermes instead of this computer.
- **How it works:** Stores a per-profile remote override (`store/profile-remote-override`) consisting of an address and an access token.
- **Inputs / options:** Description **“Sessions in this profile will run on the remote Hermes you point it at, instead of this computer.”** (`remoteOverride.description`). **“Remote address”** (`urlLabel`) input, placeholder **“https://hermes.example.com”** (`urlPlaceholder`). **“Access token”** (`tokenLabel`) input, placeholder **“Paste the remote session token”** (`tokenPlaceholder`). Buttons **“Connect”** / **“Connecting…”** (`connect` / `connecting`), **“Back”** (`confirmBack`), **“Remove remote connection”** (`disconnect`), and **“Enter new token…”** (`updateToken`).
- **Inputs / options (full i18n keys, per call site in `apps/desktop/src/app/chat/sidebar/profile-remote-override-dialog.tsx`):** `DialogDescription` **“Sessions in this profile will run on the remote Hermes you point it at, instead of this computer.”** = `profiles.remoteOverride.description` (`:236`). URL field label **“Remote address”** = `profiles.remoteOverride.urlLabel` (`:241`), on an `<Input type="url" autoCorrect="off" spellCheck={false}>` that is autofocused after the config load and submits on Enter (`:242`–`:251`); its value is trimmed and validated against `/^https?:\/\/\S+$/i` (`:130`), and a non-empty invalid value renders the destructive inline error **“Enter a full address starting with http:// or https://”** = `profiles.remoteOverride.urlInvalid` (`:252`). Token field label **“Access token”** = `profiles.remoteOverride.tokenLabel` (`:256`) on an `<Input type="password" autoComplete="off">` whose placeholder is **“Paste the remote session token”** = `profiles.remoteOverride.tokenPlaceholder` (`:261`); when `loaded.tokenSet` is true and the box is empty it shows the tertiary hint **“A token is already saved. Leave blank to keep it.”** = `profiles.remoteOverride.tokenSavedHint` (`:266`). Plain-text opt-in checkbox label = `profiles.remoteOverride.plainTextOptIn` (`:277`), rendered only when `loaded.secureTokenStorage === false` and a new token has been typed. Name-collision note = `profiles.remoteOverride.collisionWarning` (`:281`). Confirmation step: `DialogTitle` **“Connect this profile to a remote host?”** = `profiles.remoteOverride.confirmTitle` (`:219`) with `DialogDescription` = `profiles.remoteOverride.confirmNote(profile, host)` (`:220`), a ghost **“Back”** = `profiles.remoteOverride.confirmBack` (`:225`) and the primary **“Connect”** / **“Connecting…”** = `profiles.remoteOverride.connect` / `profiles.remoteOverride.connecting` (`:228`, repeated in the main footer at `:301`). Destructive footer button **“Remove remote connection”** = `profiles.remoteOverride.disconnect` (`:294`, `className="mr-auto"`, `variant="ghost"`), rendered only when `loaded.hasOverride`, calling `applyConnectionConfig({mode: 'local', profile})`. Cancel is the shared `common.cancel` (`:298`).
- **Outputs / side effects:** On save, toasts **“Profile connected”** / **“{profile} now runs on {host}”** (`savedTitle` / `savedMessage`); on removal **“Remote connection removed”** / **“{profile} now runs on this computer”** (`removedTitle` / `removedMessage`), or **“Could not remove the remote connection”** (`removeFailed`). Full keys and call sites: success notification title **“Profile connected”** = `profiles.remoteOverride.savedTitle` with message `profiles.remoteOverride.savedMessage(profile, host)` (`:157`–`:158`, followed by `refreshProfileRemoteOverrides(profileNames)` and `closeRemoteOverrideDialog()`); disconnect notification title **“Remote connection removed”** = `profiles.remoteOverride.removedTitle` with message `profiles.remoteOverride.removedMessage(profile)` (`:196`); disconnect failure `notifyError(err, p.removeFailed)` with the fallback **“Could not remove the remote connection”** = `profiles.remoteOverride.removeFailed` (`:200`, which also leaves `saving` false so the dialog stays open). A later switch that the host rejects raises **“Remote host rejected the saved token”** = `profiles.remoteOverride.authFailedTitle` carrying the action button **“Enter new token…”** = `profiles.remoteOverride.updateToken` (`apps/desktop/src/store/profile-remote-override.ts:123` and `:126`) — see `gapfill-desktop-b-0-r0.remote-override-store`.
- **Config / env:** The token is stored in the OS keychain when available.
- **Edge cases / guards:** An address that does not start with `http://` or `https://` shows **“Enter a full address starting with http:// or https://”** (`urlInvalid`). An existing saved token shows **“A token is already saved. Leave blank to keep it.”** (`tokenSavedHint`). Without secure key storage the user must opt in to **“This computer has no secure key storage, so the token would be saved unencrypted on disk. Save it anyway.”** (`plainTextOptIn`). A name clash warns **“A gateway named “{label}” already exists in Settings. This profile connection is separate and will not change it.”** (`collisionWarning`). Connecting requires an explicit confirmation step titled **“Connect this profile to a remote host?”** (`confirmTitle`) with the note **“New chats in {profile} will run on {host}. That computer will run commands and read files there, not on this one. Only connect to a host you trust.”** (`confirmNote`). A rejected saved token raises **“Remote host rejected the saved token”** / **“{host} refused the token saved for {profile}. It may have been changed on the remote side.”** (`authFailedTitle` / `authFailedMessage`).
- **Rebuild notes:** Make the trust decision explicit and irreversible-looking; it grants remote command execution.

---

## 16. Chat right rail — preview pane

### Preview pane  `id: desktop-b.preview-pane`
- **Surface:** Desktop app
- **Where:** A pane/tab in the right rail (or its own popped-out browser window). Tab label **“Preview”** (`i18n: preview.tab`), close aria **“Close preview pane”** (`preview.closePane`). Component `apps/desktop/src/app/chat/right-rail/preview-pane.tsx`.
- **What it does:** Shows whatever the agent (or you) opened: a live web page in an embedded browser, a local file with source/rendered/diff views, an artifact, or a remote HTML document.
- **How it works:** Web previews mount an Electron `<webview>` into a host div, wired to `console-message`, `context-menu`, `devtools-opened`/`closed`, `did-fail-load`, `did-navigate`, `did-navigate-in-page`, `did-start-loading`, `did-stop-loading` and `page-title-updated`. A **remote** HTML target is instead rendered in a fully sandboxed `<iframe sandbox="" referrerPolicy="no-referrer" srcDoc=…>` on a white background. Non-web targets render `ArtifactPreview` or `LocalFilePreview`. Preview targets are produced by `openPreview(target, source)` and routed by `use-preview-routing`; `preview-act.ts` implements the agent-driven preview actions, `preview-nudge.ts` the “open this” nudges, `preview-drive.ts`/`preview-reader.ts`/`preview-script-runner.ts` the automation legs, and `preview-tour.ts` the guided tour.
- **Inputs / options:** The header shows the current target as a link (tooltip **“Open {url}”**, `preview.web.openTarget`; falling back to **“Preview”**, `preview.web.fallbackTitle`) which opens externally. Mouse buttons 3 and 4 (back/forward) are captured on the pane and mapped to the preview's own history, because Chromium delivers them to the renderer as ordinary mouse events inside the app's chrome and unhandled they would walk the **host** document's history (comment at `preview-pane.tsx:981`). Everything else lives in the browser bar and the console panel.
- **Outputs / side effects:** Navigation inside the embedded browser; console capture; DevTools.
- **Config / env:** n/a
- **Edge cases / guards:** An empty target shows the blank-page state with **“Type an address above to browse, or ask Hermes to open a page.”** (`preview.web.blankPageBody`). Load failures render `PreviewLoadError` (next entry). Other preview strings: **“Loading preview”** (`preview.loading`), **“Preview unavailable”** (`preview.unavailable`), **“Opening...”** (`preview.opening`), **“Hide”** (`preview.hide`), **“Open preview”** (`preview.openPreview`), **“Open in browser”** (`preview.openInBrowser`), **“Open in external”** (`preview.openInExternal`), and the link affordance hint **“⌘/Ctrl-click for preview pane”** (`preview.linkHint`).
- **Rebuild notes:** Sandbox remote HTML; never let a guest page's navigation touch the host history.

### Preview browser bar  `id: desktop-b.preview-browser-bar`
- **Surface:** Desktop app
- **Where:** The toolbar above an embedded web preview. Component `apps/desktop/src/app/chat/right-rail/preview-browser-bar.tsx`.
- **What it does:** Back/forward/reload, an editable address field with a copy button, pop-out/pop-in/open-externally, and the console and DevTools toggles.
- **How it works:** The address field keeps three values: `draft` (null while idle so the address tracks navigation on its own, a string once the user takes it over so typing survives a page load), `pending` (the address we asked for and are still waiting on — without it, committing dropped the field straight back to the page you were *leaving*, so every navigation flashed the old address first), and the live `url`; it shows `draft ?? pending ?? url` (`preview-browser-bar.tsx:110`). `pending` clears whenever `url` changes, because the page moved or a redirect landed elsewhere. Committing runs `normalizePreviewAddress`.
- **Inputs / options:** **“Back”** (`preview.web.goBack`, `arrow-left`, disabled without history), **“Forward”** (`goForward`, `arrow-right`), **“Reload page”** (`reload`, `refresh`, spins while loading). The address `Input` (aria **“Address”**, `preview.web.address`; placeholder **“Enter address”**, `addressPlaceholder`; `inputMode="url"`, spellcheck off) — focus selects all, Enter commits and blurs, Escape reverts and blurs, blur discards the draft; a loading spinner sits inside the field's left edge and an inline **“Copy URL”** button (`contextMenu.link.copyUrl`) on its right edge, copying what the field shows (the reach-resolved address on a remote gateway). Then one of **“Pop in”** (`preview.popIn`, `screen-normal`) in a browser window, **“Pop out”** (`preview.popOut`, `empty-window`) when a browser window can be opened, or **“Open in browser”** (`preview.openInBrowser`, `link-external`). Finally **“Show/Hide preview console”** (`preview.web.showConsole` / `hideConsole`, `terminal`) and the DevTools toggle, whose label flips between **“Open preview DevTools”** (`i18n: preview.web.openDevTools`, shown while DevTools are closed) and **“Hide preview DevTools”** (`i18n: preview.web.hideDevTools`, shown while they are open) on the `bug` glyph (`preview-browser-bar.tsx:234-239`); it calls `toggleDevTools` (`preview-pane.tsx:415-428`), which no-ops when the `<webview>` exposes no `openDevTools`, calls `webview.closeDevTools()` when `webview.isDevToolsOpened()` is true and `webview.openDevTools()` otherwise. Both the console and DevTools toggles show an active state.
- **Outputs / side effects:** Navigates the webview, opens DevTools, pops the preview into its own window.
- **Config / env:** n/a
- **Edge cases / guards:** `aria-invalid` is set only while the **user** is typing something unparseable — a page that navigates itself is never the user's mistake to flag (comment at `preview-browser-bar.tsx:118`).
- **Rebuild notes:** Three-state address field (draft / pending / live) is the minimum that does not flash.

### Preview console  `id: desktop-b.preview-console`
- **Surface:** Desktop app
- **Where:** A resizable panel at the bottom of a web preview. Title **“Preview Console”** (`i18n: preview.console.title`). Components `preview-console.tsx`, `preview-console-state.ts`, `preview-console-store.ts`.
- **What it does:** Captures the previewed page's console output and lets you copy it or send selected entries into the chat.
- **How it works:** Entries come from the webview's `console-message` events into the console store; the panel keeps its own scroll-stick behaviour and a drag handle (aria **“Resize preview console”**, `preview.console.resize`).
- **Inputs / options:** Per-entry: **“Select entry”** / **“Deselect entry”** (`preview.console.select` / `deselect`), **“Copy this entry”** (`copyEntry`), **“Send this entry to chat”** (`sendEntry`). Toolbar: **“{n} selected”** (`selected`), **“Send to chat”** (`sendToChat`), **“Copy selected to clipboard”** (`copySelected`), **“Copy all to clipboard”** (`copyAll`), **“Copy”** (`copy`), **“Clear”** (`clear`). The header shows **“{n} console messages”** (`messages`).
- **Outputs / side effects:** Sending inserts the entries into the composer under the header **“Preview console:”** (`promptHeader`) and toasts **“Sent to chat”** / **“{n} log entr(y|ies) added to composer”** (`sentTitle` / `sentMessage`).
- **Config / env:** n/a
- **Edge cases / guards:** Empty state **“No console messages yet.”** (`empty`); a failed clipboard write toasts **“Could not copy console output”** (`copyFailed`).
- **Rebuild notes:** n/a

### Preview load-error and server restart  `id: desktop-b.preview-load-error`
- **Surface:** Desktop app
- **Where:** Overlays the preview when the page fails to load.
- **What it does:** Explains why the page did not load and, for a dev server, offers to ask Hermes to restart it.
- **How it works:** `loadErrorTitle(error, copy)` (`apps/desktop/src/app/chat/right-rail/preview-pane.tsx:183`) picks the headline; the restart path submits a background task and watches for its result.
- **Inputs / options:** **“Try again”** (`preview.web.tryAgain`) and, for a `url` target with a restart handler, **“Ask Hermes to restart the server”** (`preview.web.askRestart`).
- **Outputs / side effects:** Reloads, or starts a background restart.
- **Config / env:** n/a
- **Edge cases / guards:** Verbatim messages: **“Preview app failed to boot”** (`appFailedToBoot`), **“Server not found”** (`serverNotFound`), **“This address points at the machine running your agent, not this one. The browser pane loads pages locally, so a remote dev server needs a port forward or a reachable hostname.”** (`remoteLoopback`), **“Preview failed to load”** (`failedToLoad`), **“Hermes is restarting...”** (`restarting`), **“Hermes is looking for a preview server to restart ({taskId})”** (`lookingRestart`), **“Restarting preview server”** / **“Hermes is working in the background. Watch the preview console for progress.”** (`restartingTitle` / `restartingMessage`), **“Could not start server restart: {message}”** (`startRestartFailed`), **“Server restart failed”** (`restartFailed`), **“Hermes finished restarting the preview server{: message}”** (`finishedRestarting`), **“Server restart failed: {message}”** (`failedRestarting`), **“unknown error”** (`unknownError`), **“Preview server restarted”** / **“Reloading the preview now.”** (`restartedTitle` / `reloadingNow`), **“Preview restart failed”** / **“Hermes could not restart the server.”** (`restartFailedTitle` / `restartFailedMessage`), **“Hermes is still working, but no restart result has arrived yet. The server command may be running in the foreground.”** (`stillWorking`), **“Workspace changed, reloading preview”** (`workspaceReloading`), **“File changed, reloading preview: {url}”** (`fileChanged`), **“{n} file changes, reloading preview: {url}”** (`filesChanged`), **“Could not watch preview file: {message}”** (`watchFailed`), **“Module scripts are being served with the wrong MIME type. This usually means a static file server is serving a Vite/React app instead of the project dev server.”** (`moduleMimeDescription`), **“Load failed ({code}): {message}”** (`loadFailedConsole`), **“The preview page could not be reached.”** (`unreachableDescription`).
- **Rebuild notes:** Name the *likely cause*, not just the error code — the loopback and MIME messages are the two that actually unblock people.

### Local file preview  `id: desktop-b.preview-file`
- **Surface:** Desktop app
- **Where:** The preview pane when the target is a file on disk. Component `apps/desktop/src/app/chat/right-rail/preview-file.tsx`.
- **What it does:** Shows a file as source, as a rendered preview, or as a diff — and lets you edit and save it in place.
- **How it works:** Three view tabs come from `t.preview`: **“SOURCE”** (`preview.source`), **“PREVIEW”** (`preview.renderedPreview`) and **“DIFF”** (`preview.diff`); the diff tab only appears when the file has uncommitted changes. Source rendering is virtualised: text is chunked at `SOURCE_CHUNK_LINES = 200` lines with `SOURCE_LINE_PX = 20` per row and `SOURCE_OVERSCAN_LINES = 400`, and the visible window is padded with spacer rows above and below. Images are shown with the target's label as `alt` and `title`; PDFs render through the PDF viewer.
- **Inputs / options:** Clicking a source line selects it, shift-click extends, and the selection can be dragged into the composer — tooltip **“Click to select · shift-click to extend · drag to composer”** (`preview.sourceLineTitle`). An **“Edit”** button (`preview.edit`, tooltipped with its `e` shortcut) switches to editing, showing **“Editing”** (`preview.editing`) and **“Unsaved changes”** (`preview.unsavedChanges`).
- **Outputs / side effects:** Saving writes the file; a failure shows **“Couldn't save: {message}”** (`preview.saveFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** Files are blocked above `TEXT_PREVIEW_MAX_BYTES = 512 KiB` or when detected as binary, showing **“This looks like a binary file”** / **“Previewing {label} may show unreadable text.”** (`preview.binaryTitle` / `binaryBody`) or **“This file is large”** / **“{label} is {size}. Hermes will only show the first 512 KB.”** (`largeTitle` / `largeBody`) with a **“Preview anyway”** button (`previewAnyway`); once previewed, a **“Showing first 512 KB.”** notice (`truncated`) is shown. A type with no inline renderer shows **“No inline preview”** / **“{mimeType} can still be attached as context.”** (`noInlineTitle` / `noInlineBody`). If the file changes on disk while open, a banner offers **“File changed on disk”** / **“This file changed since you opened it. Overwrite it with your version, or discard your edits and reload?”** (`diskChangedTitle` / `diskChangedBody`) with **“Overwrite”** (`overwrite`) and **“Discard & reload”** (`discardReload`) — driven by `window.hermesDesktop.onPreviewFileChanged`. Unknown sizes render **“unknown size”** (`preview.unknownSize`).
- **Rebuild notes:** Virtualise source rendering from the start; a 512 KB guard plus an explicit override is the right shape.

### Artifact preview  `id: desktop-b.preview-artifact`
- **Surface:** Desktop app
- **Where:** The preview pane when the target is a generated artifact. Component `apps/desktop/src/app/chat/right-rail/preview-artifact.tsx`.
- **What it does:** Renders a generated artifact (code, an interactive HTML page, or an SVG graphic) with version navigation.
- **How it works:** Artifacts live in a local registry keyed by id with a version history.
- **Inputs / options:** Version stepper showing **“v{current} of {total}”** (`i18n: artifactPreview.versionOf`) with **“Older version”** (`olderVersion`), **“Newer version”** (`newerVersion`) and **“Latest”** (`latest`); actions **“Copy content”** (`copyContent`), **“Download”** (`download`) and **“Open in browser”** (`openInBrowser`).
- **Outputs / side effects:** Clipboard, file download, external browser.
- **Config / env:** n/a
- **Edge cases / guards:** A missing entry shows **“Artifact unavailable”** / **“This artifact is no longer in the local registry.”** (`artifactPreview.missingTitle` / `missingBody`); opening externally can fail with **“Could not open in browser”** (`openInBrowserFailed`).
- **Rebuild notes:** n/a

### Artifact card (in the transcript)  `id: desktop-b.artifact-card`
- **Surface:** Desktop app
- **Where:** Inline in the chat transcript wherever the agent produced an artifact. Component `apps/desktop/src/components/assistant-ui/artifact-card.tsx`.
- **What it does:** A compact card that names the artifact kind, shows generation progress, and opens it in the preview pane.
- **How it works:** Kind labels come from `artifactCard.kind`: **“Code”** (`code`), **“Interactive page”** (`html`), **“Graphic”** (`svg`).
- **Inputs / options:** **“Open”** button (`artifactCard.open`); a badge **“{n} versions”** (`artifactCard.versionBadge`) when more than one exists.
- **Outputs / side effects:** Opens the artifact in the preview pane.
- **Config / env:** n/a
- **Edge cases / guards:** While streaming it shows **“Generating… {n} lines”** (`artifactCard.generating`).
- **Rebuild notes:** n/a

### Right sidebar (files + terminal host)  `id: desktop-b.right-sidebar`
- **Surface:** Desktop app
- **Where:** The right rail, aria **“Right sidebar”** (`i18n: rightSidebar.aria`) with panel group aria **“Right sidebar panels”** (`panelsAria`). (The rail itself lives in `apps/desktop/src/app/right-sidebar/`; it is included here because the chat surface drives it.)
- **What it does:** Hosts the file tree (**“File system”**, `rightSidebar.files`) and the terminal (**“Terminal”**, `rightSidebar.terminal`) alongside the preview and review panes.
- **How it works:** File activation feeds the preview pipeline (see `desktop-b.contrib-data-panes`).
- **Inputs / options:** **“Open folder”** (`rightSidebar.openFolder`), **“Refresh tree”** (`refreshTree`), **“Collapse all folders”** (`collapseAll`), **“Change working directory”** (`changeCwdTitle`), the remote folder picker (**“Choose remote folder”** / **“Browse folders on the connected backend.”** / **“Select folder”**, `remotePickerTitle` / `remotePickerDescription` / `remotePickerSelect`), **“Add to chat”** (`addToChat`), and the terminal controls **“New terminal”** (`terminalNew`), **“Close others”** (`terminalCloseOthers`), **“Close all”** (`terminalCloseAll`), **“Hide terminal”** (`terminalHide`), with the tab list aria **“Terminals”** (`terminalsAria`).
- **Outputs / side effects:** Opens previews, changes the working directory, spawns terminals.
- **Config / env:** n/a
- **Edge cases / guards:** Empty and error states: **“No folder selected”** (`noFolderSelected`), **“No project”** / **“Open a project to browse its files and review changes.”** (`noProjectTitle` / `noProjectBody`), **“No project open”** (`noProjectOpen`), **“No diffs”** (`noDiffs`), **“Unreadable”** / **“Could not read this folder ({error}).”** (`unreadableTitle` / `unreadableBody`), **“Empty”** / **“This folder is empty.”** (`emptyTitle` / `emptyBody`), **“Tree error”** / **“The file tree hit an error rendering this folder.”** (`treeErrorTitle` / `treeErrorBody`) with **“Try again”** (`tryAgain`), **“Loading file tree”** (`loadingTree`), **“Loading files”** (`loadingFiles`), **“Preview unavailable”** / **“Could not preview {path}”** (`previewUnavailable` / `couldNotPreview`).
- **Rebuild notes:** n/a

---

## 17. Transcript rendering (assistant-ui)

### Thread (transcript) surface  `id: desktop-b.thread`
- **Surface:** Desktop app
- **Where:** The scrolling conversation between the header and the composer. Components under `apps/desktop/src/components/assistant-ui/thread/`.
- **What it does:** Renders the whole conversation — user messages, assistant messages, thinking blocks, tool cards, system notices, checkpoints, timestamps, changed-file cards and status rows.
- **How it works:** Built on `@assistant-ui/react` primitives with Hermes' own renderers. `list.tsx` owns the virtualised list and scroll behaviour, `message-parts.tsx` maps content parts to renderers, `timeline.tsx` + `timeline-data.ts` + `timeline-timestamp.ts` + `timestamp.ts` render the day/time rail, `content.ts` extracts message text, `message-render-boundary.tsx` isolates a single message's render failure so one bad part cannot blank the transcript.
- **Inputs / options:** **“Show earlier messages”** (`i18n: assistant.thread.showEarlier`) pages backwards; **“Scroll to bottom”** (`assistant.thread.scrollToBottom`) returns to the tail.
- **Outputs / side effects:** Reads and paginates the transcript.
- **Config / env:** n/a
- **Edge cases / guards:** While a session loads it shows **“Loading session”** (`assistant.thread.loadingSession`); while a reply is arriving, **“Hermes is loading a response”** (`loadingResponse`); when a turn is queued behind background work, **“Will resume when the background task finishes”** / **“Will resume when {n} background tasks finish”** (`resumeWhenBackgroundDone`). A generic working row reads `Hermes is working`. Day headers read **“Today, {time}”** and **“Yesterday, {time}”** (`assistant.thread.today` / `yesterday`).
- **Rebuild notes:** Isolate per-message render errors.

### Assistant message footer actions  `id: desktop-b.thread-assistant-actions`
- **Surface:** Desktop app
- **Where:** The hover-revealed action bar under each assistant message (`data-slot="aui_msg-actions"`). `apps/desktop/src/components/assistant-ui/thread/assistant-message.tsx:590`.
- **What it does:** Branch, copy, read aloud, regenerate, and react to a reply.
- **How it works:** The bar is deliberately **not** `hideWhenRunning` — that prop unmounts it while the thread streams, collapsing every completed message's footer by the bar's height and shifting the whole conversation when the turn resolves; it is invisible by default (`opacity-0` + `pointer-events-none`, revealed on hover/focus-within) so keeping it mounted reserves stable layout height at no visual cost (comment at `assistant-message.tsx:602`).
- **Inputs / options:** **“Branch in new chat”** (`assistant.thread.branchNewChat`, `GitForkIcon`) when a handler exists; **“Copy”** (`assistant.thread.copy`); the read-aloud button whose tooltip cycles **“Read aloud”** → **“Preparing audio...”** → **“Stop reading”** (`readAloud` / `preparingAudio` / `stopReading`, icons `AudioLines` / `Loader2Icon` / `VolumeXIcon`); **“Refresh”** (`assistant.thread.refresh`) which is assistant-ui's Reload — it re-runs the turn's prompt in place. A turn-duration chip on the left shows `⏱ {elapsed}` with the title **“This turn took {duration}”** (`assistant.thread.turnDuration`).
- **Outputs / side effects:** Branching creates a new chat; read-aloud drives voice playback; refresh re-runs the turn. Failure toasts **“Read aloud failed”** (`readAloudFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Never unmount a hover action bar while streaming.

### Message reactions (tapbacks)  `id: desktop-b.thread-reactions`
- **Surface:** Desktop app
- **Where:** One slot at the end of the assistant action bar (`data-slot="aui_msg-reactions"`), a picker on the user bubble, and a double-click gesture on any message body. Files `message-reactions.tsx`, `use-message-reactions.ts`, `apps/desktop/src/store/reactions.ts`.
- **What it does:** Adds an emoji reaction to a message — the desktop half of the `react_to_message` tool the agent can also call.
- **How it works:** `useMessageReactions(messageId, role)` reads the durable list from `metadata.custom.reactions`, layers this window's live overlays (`$localReactions` for the user's own click, `$agentReactions` for a mid-turn agent event) via `mergeReactions`, and returns one `react()` that paints locally first (`setLocalReaction`) and persists behind it (`toggleMessageReaction`) — a tapback is direct manipulation and must never wait on a round-trip (comment at `use-message-reactions.ts:38`). `applyReaction()` (`store/reactions.ts:16`) enforces **one reaction per author** and makes a re-tap a retraction. Writes always create a **new** `ChatMessage` object, because the runtime repository caches normalised thread messages in a `WeakMap` keyed by object identity and an in-place mutation would render stale (comment at `store/reactions.ts:32`).
- **Inputs / options:** The quick row is the six iOS Tapback defaults in Apple's order — **❤️ 👍 👎 😂 ‼️ ❓** (`QUICK_REACTIONS`, `store/reactions.ts:8`) — each a button with the emoji as its `aria-label` and `aria-pressed` on the selected one, plus a **“More emoji”** button opening the full picker. Double-clicking a message body lands `DOUBLE_CLICK_REACTION` (❤️, the first Tapback). Your own reaction is clickable to retract (aria **“Remove {emoji} reaction”**); an agent reaction is display-only with the title **“Reacted by Hermes”**.
- **Outputs / side effects:** Persists through the gateway; the badge animates with `reaction-pop`.
- **Config / env:** Gated by `$reactionsEnabled`.
- **Edge cases / guards:** The double-click gesture only claims plain message body — `detail === 2` keeps a triple-click (select-the-paragraph) from re-firing, and anything the browser already gives a double-click meaning is excluded by the selector `a, button, input, pre, select, textarea, [contenteditable="true"], [role="button"]` (`NOT_A_TAPBACK`, `use-message-reactions.ts:20`). The picker opts out of the shared popover glass, because emoji hover tints at 15 % alpha are unreadable over blurred transcript text. The trigger and the landed reaction are the **same** element (Slack-style) so reacting never shifts layout; empty shows ☺ hidden until hover, reacted shows the emoji at full strength outside the action bar so it does not ride the bar's hover opacity.
- **Rebuild notes:** Optimistic local paint, one reaction per author, re-tap to retract, and a new object per write.

### Turn error card  `id: desktop-b.thread-error-card`
- **Surface:** Desktop app
- **Where:** In place of a failed assistant message.
- **What it does:** Names which layer failed and offers the recovery that actually fits it.
- **How it works:** The gateway stamps failed turns with a structured `{layer, code, retryable}` descriptor in `metadata.custom.errorSurface` (produced by `agent/error_surface.py`). `ErrorLayerLabel` maps `layer` to `assistant.thread.errorLayers`: **“Authentication error”** (`auth`), **“Out of credits”** (`billing`), **“Disk full”** (`disk`), **“Custom endpoint error”** (`endpoint`), **“Gateway error”** (`gateway`), **“Turn failed”** (`generic`), **“Provider error”** (`provider`), **“Local runtime error”** (`runtime`), **“Streaming connection error”** (`streaming`). Older backends send no descriptor: the label falls back to the generic title and the action row still offers Retry / Open Logs / Copy error details, so nothing regresses on version skew (comment at `assistant-message.tsx:456`).
- **Inputs / options:** **“Retry”** (`assistant.thread.errorRetry`, `RefreshCwIcon`) — assistant-ui Reload, suppressed when the classifier says the failure is deterministic (`surface.retryable === false`). **“Switch provider”** (`errorSwitchProvider`) — deep-links `${SETTINGS_ROUTE}?tab=config:model`, shown only for the layers where the fix is provider/endpoint/auth configuration rather than a retry (`auth`, `billing`, `endpoint`, `provider`). **“Open logs”** (`errorOpenLogs`) or, on a remote connection, **“Open Desktop logs”** (`errorOpenDesktopLogs`). **“Copy error details”** (`errorCopyDiagnostics`) via `formatErrorDiagnostics({errorText, model, surface})`. **“Send diagnostics”** (`errorSendDiagnostics`). A **“Dismiss error”** control (`dismissError`) removes the card.
- **Outputs / side effects:** Re-runs the turn, navigates, opens the logs folder, writes the clipboard, or opens the diagnostics dialog.
- **Config / env:** n/a
- **Edge cases / guards:** “Open logs” reveals the **local** Electron profile's `HERMES_HOME/logs`; on a remote or cloud connection the failed turn's gateway and agent logs live on the remote box and the local folder only holds Desktop-side transport logs, which is exactly why the label changes (comment at `assistant-message.tsx:515`). The Switch-provider button is isolated in its own component because `useNavigate()` **throws** outside a `<Router>` — bare test harnesses and embedded panes render threads router-free — and the parent gates its mount on `useInRouterContext()` (comment at `assistant-message.tsx:475`). A failed log-folder open toasts **“Could not open the logs folder”** (`errorOpenLogsFailed`).
- **Rebuild notes:** Classify the failure server-side and let the client choose the recovery; degrade to a generic card on version skew.

### User message bubble + checkpoints  `id: desktop-b.thread-user-message`
- **Surface:** Desktop app
- **Where:** Each of your own turns in the transcript. Component `apps/desktop/src/components/assistant-ui/thread/user-message.tsx`.
- **What it does:** Renders your prompt with its reference chips, and offers edit, stop, and checkpoint restore.
- **How it works:** The bubble renders plain-text spans with directives (`@file:` etc.) still resolved inside them. Long bodies clamp with an expand affordance.
- **Inputs / options:** Click a clamped body to expand — title **“Expand message”** (`i18n: assistant.thread.expandMessage`) or **“Collapse”** (`common.collapse`). **“Edit message”** (`editMessage`) opens the inline edit composer. **“Stop”** (`assistant.thread.stop`) while the turn runs. **“Restore checkpoint”** (`restoreCheckpoint`) with the title **“Restore checkpoint — rerun from this prompt”** (`restoreFromHere`); the checkpoint rail also offers **“Restore previous checkpoint”** (`restorePrevious`) and **“Go forward”** (`assistant.thread.goForward`) — the `BranchPickerPrimitive.Next` control at `user-message.tsx:598-604`, whose `title`/tooltip is **“Restore next checkpoint”** (`i18n: assistant.thread.restoreNext`) and which steps FORWARD through the message's checkpoint branches (the mirror of `restorePrevious`); both controls hide themselves when disabled (`disabled:hidden`) and the whole rail hides when the message has a single branch (`hideWhenSingleBranch`) or the transcript is read-only.
- **Outputs / side effects:** Restoring opens a confirm titled **“Restore to this checkpoint?”** (`restoreTitle`) with the body **“Everything after this prompt is removed from the conversation, and the prompt runs again from here.”** (`restoreBody`) and the confirm label **“Restore & rerun”** (`restoreConfirm`).
- **Config / env:** n/a
- **Edge cases / guards:** While an attachment is still uploading the bubble shows **“Attaching…”** (`attachingFile`).
- **Rebuild notes:** n/a

### Inline edit composer  `id: desktop-b.thread-edit-composer`
- **Surface:** Desktop app
- **Where:** Replaces a user message when you press Edit. Component `apps/desktop/src/components/assistant-ui/thread/user-edit-composer.tsx`.
- **What it does:** Rewrites a previous prompt and re-runs the conversation from there.
- **How it works:** A full editor with the same reference-chip vocabulary as the composer.
- **Inputs / options:** **“Send edited message”** (`i18n: assistant.thread.sendEdited`) and the shared cancel.
- **Outputs / side effects:** Calls `onEdit`; failures toast **“Edit failed”** (`desktop.editFailed`) or, when the turn is no longer in server history, **“This turn is no longer in server history (it may have been compressed away).”** (`desktop.editTurnUnavailable`).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Tool call card  `id: desktop-b.thread-tool-card`
- **Surface:** Desktop app
- **Where:** Inline in the transcript for every tool the agent runs (`data-slot="tool-block"`). Components `apps/desktop/src/components/assistant-ui/tool/fallback.tsx` + `tool/fallback-model/`.
- **What it does:** Shows what the agent did — the action, its target, a status glyph, and an expandable result.
- **How it works:** Titles come from `assistant.tool.titles`, a per-tool `{done, pending, pendingAction}` triple, composed through `assistant.tool.titleTemplates`: **“{action} {command}”** (`actionCommand`), **“{action} “{value}””** (`actionQuoted`), **“{action} {target}”** (`actionTarget`), **“{prefix} {action}”** (`prefixedDone`), **“Running {prefix} {action}”** (`runningPrefixedTool`), **“Running {action}”** (`runningTool`). Generic action verbs live in `assistant.tool.actions`: **“Read”/“Reading”**, **“Opened”/“Opening”/“Failed to open”**, **“Searched”/“Searching”**, **“Ran”/“Running”**, **“Ran code”/“Scripting”**. Prefixes are **“Browser”** and **“Web”** (`assistant.tool.prefixes`). Per-tool titles cover, verbatim: `browser_click` (**“Clicked page element”** / **“Clicking page element”** / **“Clicking”**), `browser_fill` (**“Filled form field”** / **“Filling form field”** / **“Filling”**), `browser_navigate` (**“Opened page”** / **“Opening page”** / **“Opening”**), `browser_snapshot` (**“Captured page snapshot”** / **“Capturing page snapshot”** / **“Capturing”**), `browser_take_screenshot` (**“Captured screenshot”** / **“Capturing screenshot”** / **“Capturing”**), `browser_type` (**“Typed on page”** / **“Typing on page”** / **“Typing”**), `clarify` (**“Asked a question”** / **“Asking a question”** / **“Asking”**), `cronjob` (**“Cron job”** / **“Scheduling cron job”** / **“Scheduling”**), `edit_file` (**“Edited file”** / **“Editing file”** / **“Editing”**), `execute_code` (**“Ran code”** / **“Scripting”** / **“Scripting”**), `image_generate` (**“Generated image”** / **“Generating image”** / **“Generating”**), `list_files` (**“Listed files”** / **“Listing files”** / **“Listing”**), `memory` (**“Saved to memory”** / **“Saving to memory”** / **“Saving”**), `patch` (**“Patched file”** / **“Patching file”** / **“Patching”**), `read_file` (**“Read file”** / **“Reading file”** / **“Reading”**), `search_files` (**“Searched files”** / **“Searching files”** / **“Searching”**), `session_search_recall` (**“Searched session history”** / **“Searching session history”** / **“Searching”**), `terminal` (**“Ran command”** / **“Running command”** / **“Running”**), `todo` (**“Updated todos”** / **“Updating todos”** / **“Updating”**), `vision_analyze` (**“Analyzed image”** / **“Analyzing image”** / **“Analyzing”**), `web_extract` (**“Read webpage”** / **“Reading webpage”** / **“Reading”**), `web_search` (**“Searched web”** / **“Searching web”** / **“Searching”**), `write_file` (**“Edited file”** / **“Editing file”** / **“Editing”**).
- **Inputs / options:** Click the header to expand/collapse. Copy affordances by result kind: **“Copy code”** (`assistant.tool.copyCode`), **“Copy output”** (`copyOutput`), **“Copy command”** (`copyCommand`), **“Copy content”** (`copyContent`), **“Copy URL”** (`copyUrl`), **“Copy results”** (`copyResults`), **“Copy query”** (`copyQuery`), **“Copy file”** (`copyFile`), **“Copy path”** (`copyPath`), **“Copy activity”** (`copyActivity`), and **“Raw response”** (`rawResponse`). Generated images render with the alt text **“Tool output”** (`outputAlt`) and a **“Rendering image”** placeholder (`renderingImage`).
- **Outputs / side effects:** Clipboard; opening a file/URL routes to the preview pane.
- **Config / env:** n/a
- **Edge cases / guards:** Status vocabulary: **“Running”** (`statusRunning`), **“Error”** (`statusError`), **“Recovered”** (`statusRecovered`), **“Done”** (`statusDone`); retry summaries **“Recovered after 1 failed step”** (`recoveredOne`), **“Recovered after {n} failed steps”** (`recoveredMany`), **“1 step failed”** (`failedOne`), **“{n} steps failed”** (`failedMany`). A memory write that produced no visible output shows **“Memory write noted”** (`memoryWriteNoted`).
- **Rebuild notes:** Keep a per-tool title table with a pending/done/gerund triple; fall back to generic verbs for unknown tools.

### Delegate (subagent) tool card  `id: desktop-b.thread-delegate-card`
- **Surface:** Desktop app
- **Where:** Inline where the agent delegated work. Components `tool/delegate.tsx` + `tool/delegate-model.ts`.
- **What it does:** Renders a delegation as a compact live card that mirrors the Agents panel's vocabulary.
- **How it works:** Builds a view model from the delegate tool's arguments and its streamed subagent events; a placeholder row keyed `delegate-tool:…` stands in until the real native `subagent.*` events arrive, at which point `pruneDelegateFallbackSubagents` removes it.
- **Inputs / options:** Expand/collapse.
- **Outputs / side effects:** Visual.
- **Config / env:** n/a
- **Edge cases / guards:** See `desktop-b.agents-panel` for the shared store semantics.
- **Rebuild notes:** n/a

### Approval card  `id: desktop-b.thread-approval`
- **Surface:** Desktop app
- **Where:** Inline in the transcript when a command needs permission. Component `apps/desktop/src/components/assistant-ui/tool/approval.tsx`.
- **What it does:** Asks you to allow or reject a specific command before the agent runs it, with an option to allow it permanently.
- **How it works:** The card is fed by the gateway's approval request; responses go back over the socket.
- **Inputs / options:** **“Run”** (`i18n: assistant.approval.run`) and **“Reject”** (`reject`); a **“More approval options”** menu (`moreOptions`) with **“Allow this session”** (`allowSession`) and **“Always allow…”** (`alwaysAllowMenu`). The command itself is labelled **“Command”** (`command`). A jump affordance elsewhere in the UI reads **“Approval needed”** (`jumpToApproval`).
- **Outputs / side effects:** Sends the approval decision. **“Always allow…”** opens a confirm titled **“Always allow this command?”** (`alwaysTitle`) with the body **“This adds the “{pattern}” pattern to your permanent allowlist (~/.hermes/config.yaml). Hermes won't ask again for commands like this — in this session or any future one.”** (`alwaysDescription`) and the confirm label **“Always allow”** (`alwaysAllow`) — which writes the pattern into `~/.hermes/config.yaml`.
- **Config / env:** The permanent allowlist lives in the config file named in the dialog.
- **Edge cases / guards:** With no socket the card reports **“Hermes gateway is not connected”** (`gatewayDisconnected`); a failed send toasts **“Could not send approval response”** (`sendFailed`). Native OS notifications mirror the card with **“Approval needed”** / **“Approve”** / **“Reject”** (`notifications.native.approvalTitle|approveAction|rejectAction`).
- **Rebuild notes:** Say exactly what a permanent allow writes and where.

### Clarify card  `id: desktop-b.thread-clarify`
- **Surface:** Desktop app
- **Where:** Inline when the agent asks a clarifying question. Component `apps/desktop/src/components/assistant-ui/clarify-tool.tsx`.
- **What it does:** Presents one or more multiple-choice questions (with a free-text escape hatch) and sends the answers back into the turn.
- **How it works:** Questions arrive with the `clarify` tool call; answers are posted back over the gateway. Progress is shown as **“{answered} of {total} answered”** (`i18n: assistant.clarify.questionProgress`), and an answered question is badged **“Answered”** (`answeredBadge`).
- **Inputs / options:** One button per choice, plus **“Other (type your answer)”** (`other`) which reveals an input with placeholder **“Type your answer…”** (`placeholder`). **“Skip”** (`skip`) — the skipped state reads **“Skipped”** (`skipped`). **“Continue”** (`continueLabel`) or **“Confirm and continue”** (`confirmAndContinueLabel`).
- **Outputs / side effects:** Sends the clarify response and unblocks the turn.
- **Config / env:** n/a
- **Edge cases / guards:** While the request is still arriving, **“Loading question…”** (`loadingQuestion`); before it is usable, **“Clarify request is not ready yet”** (`notReady`); with no socket, **“Hermes gateway is not connected”** (`gatewayDisconnected`); a failed send toasts **“Could not send clarify response”** (`sendFailed`). Once the prompt has moved on, the card degrades to a **late answer** mode: hint **“This prompt is no longer waiting. Pick an option to draft it as a follow-up message.”** (`lateAnswerHint`), tooltip **“Draft this answer as a follow-up message”** (`lateAnswerTip`), and picking an option drafts **“Re: "{question}" — my answer: {choice}”** (`lateAnswer`) into the composer.
- **Rebuild notes:** A blocked question that expires must still be answerable as a normal message.

### MCP setup consent card  `id: desktop-b.thread-mcp-consent`
- **Surface:** Desktop app
- **Where:** Inline when the agent wants to install, enable or authorize an MCP server. Component `apps/desktop/src/components/assistant-ui/mcp-setup-tool.tsx`.
- **What it does:** Asks for explicit consent before the agent adds a tool server to your setup.
- **How it works:** Three request kinds, each with its own title: **“Add the {server} MCP server?”** (`i18n: assistant.mcpSetup.installTitle`), **“Enable the {server} MCP server?”** (`enableTitle`), **“Authorize the {server} MCP server?”** (`authorizeTitle`). The card shows the catalog provenance **“From the Nous-approved catalog”** (`catalogSource`) and the tool count **“1 tool”** / **“{n} tools”** (`toolCount`).
- **Inputs / options:** **“Install”** / **“Enable”** / **“Authorize”** (`installAction` / `enableAction` / `authorizeAction`) and **“Not now”** (`decline`). Required credential fields must be filled first.
- **Outputs / side effects:** Installs/enables/authorizes the server and reports **“Installed {server}”** / **“Enabled {server}”** / **“Authorized {server}”** (`installed` / `enabled` / `authorized`); declining shows **“Declined”** (`declined`); no answer shows **“No response”** (`unanswered`).
- **Config / env:** Writes `mcp_servers` and its credentials.
- **Edge cases / guards:** A server outside the catalog reports **““{server}” is not in the MCP catalog”** (`notInCatalog`); missing credentials **“Fill in the required credentials first”** (`envRequired`); failures **“Setup failed for {server}”** (`failed`) and **“Could not send MCP setup response”** (`sendFailed`); a save that succeeded but could not hot-reload reports **“Server saved, but reloading MCP tools failed — they load next session”** (`reloadFailed`); no socket gives **“Hermes gateway is not connected”** (`gatewayDisconnected`).
- **Rebuild notes:** Consent before install, always, and name the catalog the server came from.

### Changed-files card  `id: desktop-b.thread-changed-files`
- **Surface:** Desktop app
- **Where:** Under a turn that modified files. Component `apps/desktop/src/components/assistant-ui/thread/changed-files-card.tsx`.
- **What it does:** Summarises the files a turn touched and jumps to the review pane.
- **How it works:** File list from `changed-files.ts`; each row shows the display path with the full path as its `title`.
- **Inputs / options:** Header **“1 file changed”** / **“{n} files changed”** (`i18n: assistant.thread.filesChanged`) and a **“Review”** button (`assistant.thread.reviewChanges`).
- **Outputs / side effects:** Opens the review pane.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Thinking / reasoning blocks  `id: desktop-b.thread-thinking`
- **Surface:** Desktop app
- **Where:** Above an assistant reply when the model exposes reasoning.
- **What it does:** Shows the model's reasoning as a collapsible block with a duration.
- **How it works:** Labels come from `assistant.thread`: **“Thinking”** (`thinking`) while streaming, then **“Thought”** (`thought`), **“Thought briefly”** (`thoughtBriefly`) or **“Thought for {duration}”** (`thoughtFor`).
- **Inputs / options:** Click to expand/collapse.
- **Outputs / side effects:** Visual.
- **Config / env:** Visibility is governed by `display.show_reasoning` (see the config shards).
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Markdown, code blocks and embeds  `id: desktop-b.thread-markdown`
- **Surface:** Desktop app
- **Where:** Inside every assistant message. Files `markdown-text.tsx`, `markdown-table.tsx`, `chat/shiki-highlighter.tsx`, `chat/code-editor.tsx`, `chat/diff-lines.tsx`, `assistant-ui/embeds/*`.
- **What it does:** Renders Markdown with syntax-highlighted code, tables, diffs, and rich embeds for links, alerts, Mermaid diagrams, maps and YouTube.
- **How it works:** Code is highlighted with Shiki; diffs render through `diff-lines.tsx`; `embeds/url-embed.tsx` produces link cards using providers in `embeds/providers/` (`maps.ts`, `youtube.ts`); `embeds/alert.tsx` renders GitHub-style callouts; `embeds/mermaid-embed.tsx` renders Mermaid; `embeds/social-embed.tsx` renders social cards. `directive-text.tsx` renders `@file:`/`@url:` style references inline as chips, `transcript-directive.tsx` handles registry-contributed transcript directives, and `inline-preview-directive.tsx` is the built-in one that opens a preview.
- **Inputs / options:** Code blocks carry **“Copy code”** (`assistant.tool.copyCode`); links follow the link context menu (see below); an artifact renders as an artifact card.
- **Outputs / side effects:** Clipboard, preview pane, external browser.
- **Config / env:** n/a
- **Edge cases / guards:** `message-render-boundary.tsx` catches a per-message render error so one malformed part cannot blank the transcript.
- **Rebuild notes:** n/a

### Transcript context menus  `id: desktop-b.thread-context-menu`
- **Surface:** Desktop app
- **Where:** Right-click inside the transcript (and the preview pane's guest page). Strings in `i18n: contextMenu.*`; wiring under `apps/desktop/src/app/context-menu/`.
- **What it does:** Native-feeling context menus for links, images, editable text and the page.
- **How it works:** Built from the Electron context-menu event, including the preview webview's `context-menu` event.
- **Inputs / options:** Link: **“Open in in-app browser”** (`contextMenu.link.openInApp`), **“Open in external browser”** (`openExternal`), **“Copy URL”** (`copyUrl`), **“Copy resolved URL”** (`copyResolvedUrl`). Image: **“Copy image”** (`contextMenu.image.copyImage`), **“Copy image address”** (`copyImageAddress`), **“Save image as…”** (`saveImageAs`). Edit: **“Cut”** (`contextMenu.edit.cut`), **“Paste”** (`paste`), **“Select all”** (`selectAll`), **“Add to dictionary”** (`addToDictionary`). Page: **“Copy page URL”** (`contextMenu.page.copyPageUrl`), **“Inspect element”** (`inspectElement`).
- **Outputs / side effects:** Clipboard, downloads, browser tabs, DevTools.
- **Config / env:** n/a
- **Edge cases / guards:** Image saving reports **“Image saved”** (`desktop.imageSaved`), **“Download started”** (`downloadStarted`), **“Image download failed”** (`imageDownloadFailed`), or, on an old build, **“Restart Hermes Desktop to use Save Image.”** / **“Restart Hermes Desktop to save images”** (`restartToUseSaveImage` / `restartToSaveImages`).
- **Rebuild notes:** n/a

### Sudo / secret prompt overlays  `id: desktop-b.thread-prompt-overlays`
- **Surface:** Desktop app
- **Where:** Modal overlays raised when a turn needs a credential. Component `apps/desktop/src/components/prompt-overlays.tsx`; strings `i18n: prompts.*`.
- **What it does:** Collects an administrator password or a required secret and sends it to the local agent.
- **How it works:** Driven by the gateway's blocking-prompt events (`store/prompts`), the same state that makes `awaitingInput` true and stops Esc from interrupting the turn.
- **Inputs / options:** Sudo overlay — title **“Administrator password”** (`prompts.sudoTitle`), description **“Hermes needs your sudo password to run a privileged command. It is sent only to your local agent.”** (`sudoDesc`), placeholder **“sudo password”** (`sudoPlaceholder`). Secret overlay — title **“Secret required”** (`secretTitle`), description **“Hermes needs a credential to continue.”** (`secretDesc`), placeholder **“secret value”** (`secretPlaceholder`).
- **Outputs / side effects:** Sends the value over the socket and unblocks the turn.
- **Config / env:** n/a
- **Edge cases / guards:** No socket gives **“Hermes gateway is not connected”** (`prompts.gatewayDisconnected`); failures toast **“Could not send sudo password”** (`sudoSendFailed`) or **“Could not send secret”** (`secretSendFailed`).
- **Rebuild notes:** State plainly that the secret goes only to the local agent.
