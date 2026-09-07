# Web dashboard (B): Logs, Cron, Skills, Plugins, MCP pages

This shard inventories five routes of the Hermes web dashboard SPA (`web/src/pages/`): `/logs` (LogsPage.tsx), `/cron` (CronPage.tsx + ScheduleBuilder + AutomationBlueprints), `/skills` (SkillsPage.tsx + SkillEditorDialog + ToolsetConfigDrawer), `/plugins` (PluginsPage.tsx) and `/mcp` (McpPage.tsx). For each page it lists every visible control (tab, segmented radio, select option, input, checkbox, button, dialog, toast, empty-state string), the i18n key that produces the label (`web/src/i18n/en.ts`), the FastAPI route it calls (`hermes_cli/web_server.py`, `hermes_cli/web_routers/{cron,skills,mcp,tools}.py`) and the backend mechanism/storage behind it. Static string constants that are not translated are quoted verbatim from the TSX.
Deliberately left to sibling shards: the shared app shell (sidebar navigation links CHAT…ACHIEVEMENTS, `Restart Gateway`, `Update Hermes`, theme/language switchers, status strip, login) → web-a; Chat/Sessions/Files/Models pages → web-a; Channels/Webhooks/Pairing/Profiles/Config/Keys/System/Docs pages → web-c; the CLI `hermes cron|skills|plugins|mcp|logs` commands and the cron engine (`cron/jobs.py`, `cron/scheduler.py`) beyond what the dashboard routes touch → cli/core shards; the desktop app's cron/skills/plugins views → desktop shard; the dashboard-plugin SDK (`web/src/plugins/*`, `PluginSlot`) internals → web-a/core (only the Plugins page UI that manages them is here).
Evidence: live crawl `hermes_inv/web_crawl/_logs.json,_cron.json,_skills.json,_plugins.json,_mcp.json` (+ PNGs) of the running dashboard at 127.0.0.1:9119, live GET responses in `hermes_inv/api_live/get_all.json`, and the source tree at tag v2026.8.31.

---

## 1. Logs page (`/logs`)

### Logs page  `id: web-b.logs-page`
- **Surface:** Web dashboard
- **Where:** Sidebar link `LOGS` → route `/logs`; page H1 `Logs` (`i18n: logs.title`). Toolbar `role="toolbar" aria-label="Logs"` with four `FilterGroup`s, a card titled `<file>.log` (rendered uppercase by CSS: `AGENT.LOG`), header badge `AGENT · ALL · ALL`, header icon button `aria-label="Refresh"` (`i18n: common.refresh`), header switch `Auto-refresh` (`i18n: logs.autoRefresh`, `id="logs-auto-refresh"`), badge `Live` (`i18n: common.live`) when auto-refresh is on.
- **What it does:** Shows the tail of one of Hermes' log files (agent/errors/gateway) with level/component filters and a line-count cap, colour-coding each line by log level, optionally re-polling every 5 s.
- **How it works:** `web/src/pages/LogsPage.tsx:46-237`. State: `file` (default `"agent"`), `level` (default `"ALL"`), `component` (default `"all"`), `lineCount` (default `100`), `autoRefresh` (default `false`). `fetchLogs` (LogsPage.tsx:62-77) calls `api.getLogs({file, lines, level, component})` (`web/src/lib/api.ts:506-513`) which builds `GET /api/logs?file=&lines=&level=&component=` — `level` omitted when `ALL`, `component` omitted when `all`. After the response the scroll container is scrolled to bottom after 50 ms. Backend `hermes_cli/web_server.py:12704-12756 get_logs()`: maps `file` via `hermes_cli/logs.py:32 LOG_FILES` (`agent→agent.log, errors→errors.log, gateway→gateway.log, gui→gui.log, desktop→desktop.log, mcp→mcp-stderr.log`), reads `<HERMES_HOME>/logs/<name>`; returns `{"file","lines":[]}` when the file is missing; `level` normalised (`ALL`/empty → no filter); `component` resolved via `hermes_logging.py:244 COMPONENT_PREFIXES` (`gateway→(gateway, hermes_plugins, plugins.platforms)`, `agent→(agent, run_agent, model_tools, batch_runner)`, `tools→(tools,)`, `cli→(hermes_cli, cli)`, `cron→(cron,)`, `gui→(hermes_cli.web_server, hermes_cli.pty_bridge, tui_gateway, uvicorn…)`); `_read_tail(path, min(lines,500) or 2000 when search, has_filters, min_level, component_prefixes)` (`hermes_cli/logs.py:256-282`) reads `max(num_lines*20, 2000)` raw lines when filtering then keeps the last N; optional `search` (case-insensitive substring) post-filter — exposed by the API but NOT by this page's UI. Each line is classified client-side by `classifyLine` (`web/src/lib/log-classify.ts:19-38`): anchored regex `^\d{4}-\d{2}-\d{2}[ T][\d:,.]+\s+(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b` → level; fallback word-boundary match on the upper-cased line (`ERROR|CRITICAL|FATAL` or `TRACEBACK (` → error; `WARNING|WARN` → warning; `DEBUG` → debug; else info). Colour map `LINE_COLORS` (LogsPage.tsx:29-34): error→`text-destructive`, warning→`text-warning`, info→`text-foreground`, debug→`text-text-tertiary`.
- **Inputs / options:** 
  - FilterGroup `File` (`i18n: logs.file`) — Segmented radios: `AGENT`, `ERRORS`, `GATEWAY` (values `agent|errors|gateway`; labels upper-cased by `formatFilterLabel`).
  - FilterGroup `Level` (`i18n: logs.level`) — radios `ALL`, `DEBUG`, `INFO`, `WARNING`, `ERROR`.
  - FilterGroup `Component` (`i18n: logs.component`) — radios `ALL`, `GATEWAY`, `AGENT`, `TOOLS`, `CLI`, `CRON` (values `all|gateway|agent|tools|cli|cron`).
  - FilterGroup `Lines` (`i18n: logs.lines`) — radios `50`, `100`, `200`, `500`.
  - Header: icon button `Refresh` (disabled while loading, shows Spinner); switch `Auto-refresh` (`role="switch"`); badge `Live` with pulsing dot while on.
  - Plugin slots `logs:top` and `logs:bottom` (`PluginSlot`) where dashboard plugins may inject UI.
- **Outputs / side effects:** Read-only. Renders `{"file","lines"}` as monospaced `div`s (hover highlight `hover:bg-secondary/20`), min-height 400px, max-height `calc(100vh-220px)`. Empty state text `No log lines found` (`i18n: logs.noLogLines`). Errors from fetch are shown in a red banner above the lines (`String(err)`). Changing any filter refetches immediately (`useEffect` on `fetchLogs`). Auto-refresh installs `setInterval(fetchLogs, 5000)`.
- **Config / env:** `HERMES_HOME` (log dir `<HERMES_HOME>/logs`). No config keys. Logging destinations are governed by `hermes_logging` (out of scope).
- **Edge cases / guards:** Backend 400 `Unknown log file: <file>` for files outside `LOG_FILES` (the UI only offers 3 of the 6 keys — `gui`, `desktop`, `mcp` are API-only); 400 `Unknown component: X. Available: …`; `lines` server-capped at 500; header badge summarises `FILE · LEVEL · COMPONENT`; scroll pinned to bottom on every fetch; classification deliberately avoids substring matching so `parse_errors=0` in an INFO line stays uncoloured (log-classify.ts:1-9; unit tests `log-classify.test.ts`).
- **Rebuild notes:** One GET endpoint that tails a named file with level/prefix filters; a page with four segmented filter groups, a poll toggle and a monospace viewer with regex level colouring. Better: server-sent streaming (tail -f) instead of 5 s polling, a free-text search box wired to the already-supported `search` param, and expose the `gui`/`desktop`/`mcp` files.

### Logs — `GET /api/logs` endpoint  `id: web-b.logs-api`
- **Surface:** API
- **Where:** `GET /api/logs?file=agent&lines=100&level=INFO&component=gateway&search=text` (dashboard-session-authenticated).
- **What it does:** Returns the last N lines of a Hermes log file, filtered by minimum level, component logger prefix and optional substring.
- **How it works:** `hermes_cli/web_server.py:12704-12756`; delegates to `hermes_cli.logs._read_tail` and `hermes_logging.COMPONENT_PREFIXES` (see previous entry). When `search` is set, 2000 lines are read, filtered, then trimmed to `min(lines,500)`.
- **Inputs / options:** query `file` (default `agent`; one of `agent, errors, gateway, gui, desktop, mcp`), `lines` (int, default 100, max 500), `level` (`DEBUG|INFO|WARNING|ERROR`, `ALL`/empty = none), `component` (`gateway|agent|tools|cli|cron|gui`, `all` = none), `search` (string).
- **Outputs / side effects:** `{"file": "<key>", "lines": ["…\n", …]}` (lines keep trailing newline). Live sample in `hermes_inv/api_live/get_all.json["/api/logs"]`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** 400 on unknown file/component; empty list when file absent; `_read_last_n_lines` reads whole file under 1 MB else chunked from the end (`hermes_cli/logs.py:285`).
- **Rebuild notes:** Implement as a bounded reverse file read with prefix/level predicates; better: cursor-based incremental tailing.

---

## 2. Cron page (`/cron`)

### Cron page shell, view switch and header  `id: web-b.cron-page`
- **Surface:** Web dashboard
- **Where:** Sidebar `CRON` → `/cron`; H1 `Cron`. Header end-slot button `CREATE` (`i18n: common.create`, rendered uppercase). Top `Segmented` with radios `Jobs` and `Blueprints` (static strings, CronPage.tsx:872-879). Plugin slots `cron:top`, `cron:bottom`.
- **What it does:** Lists scheduled agent jobs across all profiles, lets the user create/edit/pause/resume/trigger/delete jobs, and offers a gallery of Automation Blueprints that create jobs from typed forms.
- **How it works:** `web/src/pages/CronPage.tsx:526-1233`. On mount loads `api.getProfiles()` (`GET /api/profiles`), `api.getCronDeliveryTargets()` (`GET /api/cron/delivery-targets`), and `api.getCronJobs(selectedProfile)` (`GET /api/cron/jobs?profile=all`). Job list request has a generation counter + active ref (CronPage.tsx:615-646) so stale responses after switching profile are dropped. Resources for the form (`api.getSkills(profile)`, `api.getToolsets(profile)`, `api.getModelOptions(profile)`) are loaded for `resourceProfile` = the edit job's profile or the create-modal profile (CronPage.tsx:681-696), each sorted by name. A `CronTriggerController` from `@hermes/shared` (`createCronTriggerController`) tracks in-flight trigger keys so the ⚡ button shows a spinner and is disabled per job (CronPage.tsx:531-548). Loading state: centred Spinner until first jobs response.
- **Inputs / options:** `CREATE` header button (opens create modal with profile = selected profile or `default` when `All profiles`); Segmented `Jobs` | `Blueprints`; (Jobs view) `Profile` select `id="cron-profile-filter"` with options `All profiles` + one per profile name (`default` shown as `default`); everything in the entries below.
- **Outputs / side effects:** Toasts via `useToast`: `Loading...` on list error (`t.common.loading`, type error).
- **Config / env:** n/a (per-profile `~/.hermes/profiles/<name>/cron/jobs.json` or `~/.hermes/cron/jobs.json` for default).
- **Edge cases / guards:** With `All profiles`, backend iterates every profile and swallows per-profile failures (`_list_cron_jobs_sync` web_server.py:13061-13075). Header `CREATE` is re-rendered on every `selectedProfile` change.
- **Rebuild notes:** Page = job list + two modals + blueprint gallery, all driven by 12 REST routes. Better: run-history drawer using the already-existing `GET /api/cron/jobs/{id}/runs` (not wired in this SPA), inline validation instead of toasts.

### Scheduled Jobs list and job cards  `id: web-b.cron-jobs-list`
- **Surface:** Web dashboard
- **Where:** `/cron` → `Jobs` view → H2 `Scheduled Jobs (N)` (`i18n: cron.scheduledJobs`; crawl: `Scheduled Jobs (0)`) with clock icon; one Card per job.
- **What it does:** Displays every cron job with its status, profile, delivery target, skills, mode, model, toolsets, schedule description, repeat count, last/next run and errors, plus four action buttons.
- **How it works:** CronPage.tsx:1042-1228. Title = `name` → else prompt truncated to 60 chars → else script truncated → else job id → else `"Cron job"` (`getJobTitle` :446-457). State = `job.state` or `disabled`/`scheduled` from `enabled` (`getJobState` :476-478). Badge tone map `STATUS_TONE` (:518-524): `enabled|scheduled→success`, `paused→warning`, `error|completed→destructive`, else secondary. Schedule text via `describeSchedule(job.schedule, job.schedule_display || job.schedule.display, strings)` (`web/src/lib/schedule.ts:338-372`): interval minutes → `Every {n} min|h|d` (`i18n: cron.scheduleDescribe.everyMinutes/everyHours/everyDays`), `once` → `Once at {time}`, cron expr recognised by `parseSimpleCronExpression` (5 fields, literal/list only, month `*`) → `Daily at {time}` / `Weekly on {days} at {time}` / `Monthly on the {day} at {time}` (English ordinals only for `en` locale, CronPage.tsx:566-570), else raw display/expr/`—`. Repeat display (`getRepeatDisplay` :480-485): `forever` when `repeat.times` null, `{completed}/{times}` when completed>0, else `{times} times`. Mode (`getJobMode` :487-491): `no_agent` | `script+agent` | `agent` (badge shown only when ≠ agent). Model badge label `model` with title `provider/model`. Toolsets badge `{n} toolsets` with title listing them. Skills badge: single name or `{n} skills`.
- **Inputs / options:** Per card icon buttons (right side): `Pause` (`i18n: cron.pause`, Pause icon, class `text-warning`) or `Resume` (`i18n: cron.resume`, Play icon, `text-success`) depending on state; `Trigger now` (`i18n: cron.triggerNow`, Zap icon, disabled + Spinner while running); `Edit job` (static aria-label/title, Pencil icon); `Delete` (`i18n: common.delete`, Trash2, destructive). Empty state card: `No cron jobs configured. Create one above.` (`i18n: cron.noJobs`) + `CREATE` button.
- **Outputs / side effects:** Text rows: `<schedule description>`, `repeat: <display>`, `Last: <toLocaleString or —>` (`i18n: cron.last`), `Next: …` (`i18n: cron.next`). Error lines in red: `delivery: <last_delivery_error>`, `missed scheduled fire (<time>): <last_fire_error.detail>`, `<last_error>`. Prompt preview (100 chars) shown under the title only when the job has a name.
- **Config / env:** n/a.
- **Edge cases / guards:** Badge for `deliver` only when ≠ `local`. Profile badge always shown (`default` literal). 6-field cron expressions are deliberately not humanised (schedule.ts:394-399) to avoid dropping the year.
- **Rebuild notes:** Render list from `GET /api/cron/jobs`; humanise schedule client-side with a tiny cron-shape recogniser. Better: sortable table, per-job run history and output preview from `<cron>/output/`.

### Pause / Resume job  `id: web-b.cron-pause-resume`
- **Surface:** Web dashboard
- **Where:** Job card icon button `Pause` / `Resume`.
- **What it does:** Toggles the job's `paused` state without deleting it.
- **How it works:** `handlePauseResume` (CronPage.tsx:756-777) → `api.pauseCronJob(id, profile)` = `POST /api/cron/jobs/{id}/pause?profile=` or `api.resumeCronJob` = `POST /api/cron/jobs/{id}/resume?profile=` (`api.ts:618,633`). Backend `_pause_cron_job_sync`/`_resume_cron_job_sync` (web_server.py:13259-13280) → `_mutate_cron_for_profile(profile, "pause_job"|"resume_job", job_id)` → `cron.jobs.pause_job/resume_job` under `use_cron_store(home)` (`_call_cron_for_profile` :12950-12980) then `_notify_cron_provider_for_profile` reconciles the scheduler provider (`provider.on_jobs_changed()`; skipped for external providers when >1 profile exists, :12983-13040).
- **Inputs / options:** none besides the click.
- **Outputs / side effects:** Writes `jobs.json`; toast `Resume: "<title≤30>"` or `Pause: "<title≤30>"` (success) or `Error: <e>` (`i18n: status.error`); list reloaded.
- **Config / env:** n/a.
- **Edge cases / guards:** 404 `Job not found` when profile lookup fails (`_find_cron_job_profile` scans all profiles matching id or name).
- **Rebuild notes:** Two idempotent POSTs flipping a `state` field; better: optimistic UI.

### Trigger now  `id: web-b.cron-trigger-now`
- **Surface:** Web dashboard
- **Where:** Job card icon button `Trigger now` (⚡).
- **What it does:** Runs the job immediately, outside its schedule.
- **How it works:** `handleTrigger` (CronPage.tsx:779-813) runs through the `CronTriggerController` (`controller.run(jobKey, () => api.triggerCronJob(id, profile))`) → `POST /api/cron/jobs/{id}/trigger?profile=`. Backend `_trigger_cron_job_sync` (web_server.py:13283-13316): `resolve_job_ref` → `force = not enabled or state == "paused"` → `_fire_cron_job_for_profile(profile, id, force=force)` (durable claim shared with the ticker) → re-reads the job; returns refreshed job if `last_run_at` changed; 409 `Job is already running or was claimed by another scheduler` when not run; if the one-shot removed itself returns `{...job, enabled:false, state:"completed"}`.
- **Inputs / options:** none.
- **Outputs / side effects:** Executes the agent run (session id `cron_{job_id}_{timestamp}`), delivers output per `deliver`; toast `Trigger now: "<title>" ✓` only when `result.started`; `Error: …` on failure; button disabled + spinner while in flight (`triggeringJobKeys`).
- **Config / env:** n/a.
- **Edge cases / guards:** Result ignored if the profile filter changed meanwhile (`selectedProfileRef` check); no pre-request toast by design (comment :787-791).
- **Rebuild notes:** POST that claims and runs; better: stream run progress into the card.

### Delete job (confirm dialog)  `id: web-b.cron-delete`
- **Surface:** Web dashboard
- **Where:** Job card `Delete` → `DeleteConfirmDialog` titled `Delete scheduled job?` (`i18n: cron.confirmDeleteTitle`), body `"<title≤40>" — This removes the job from the schedule. This cannot be undone.` (`i18n: cron.confirmDeleteMessage`).
- **What it does:** Permanently removes the job from the profile's store.
- **How it works:** `useConfirmDelete` hook (`@nous-research/ui/hooks/use-confirm-delete`) keyed by `profile:id` (`getJobKey`); on confirm → `api.deleteCronJob(id, profile)` = `DELETE /api/cron/jobs/{id}?profile=` → `_delete_cron_job_sync` (web_server.py:13319-13330) → `remove_job` + provider reconcile → `{"ok": true}`.
- **Inputs / options:** Dialog buttons from `web/src/components/DeleteConfirmDialog.tsx` (Cancel / Delete; loading state while deleting).
- **Outputs / side effects:** Toast `Delete: "<title>"`; list reload; 400 `ValueError` text or 404 `Job not found`.
- **Config / env:** n/a.
- **Edge cases / guards:** Error re-thrown so the dialog stays open on failure (`throw e` :829).
- **Rebuild notes:** DELETE + confirm modal.

### New Cron Job modal  `id: web-b.cron-create-modal`
- **Surface:** Web dashboard
- **Where:** `/cron` → `CREATE` → dialog `role="dialog" aria-labelledby="create-cron-title"`, heading `New Cron Job` (`i18n: cron.newJob`), close icon button `aria-label="Close"`, footer button `CREATE` / `Creating...` (`i18n: common.create` / `common.creating`).
- **What it does:** Collects all fields of a cron job and POSTs them to create the job in the chosen profile.
- **How it works:** CronPage.tsx:904-977; form state `CronJobEditorState` (`emptyCronJobForm` :135-153: deliver `local`, no_agent false, continuity false, scheduleState = `DEFAULT_SCHEDULE_STATE` = every 30 minutes). `handleCreate` (:698-723): builds payload with `buildCronJobPayloadFromEditor` → `buildCronJobPayload` (`web/src/lib/cron-job.ts:44-68`: trims, `deliver` defaults `local`, provider/model/base_url(trailing `/` stripped)/script/workdir → null when empty, `context_from` list with reserved `self` entry appended when continuity is checked, `enabled_toolsets` null when empty). Validation: schedule string empty OR (not no_agent AND no prompt/script/skills) → toast `Prompt & Schedule (cron expression) required`; no_agent without script → toast `no_agent jobs require a script`. Then `api.createCronJob(payload, createProfile)` = `POST /api/cron/jobs?profile=<name>` with body `CronJobCreate` (`hermes_cli/web_models.py:391-404`: prompt, schedule, name, deliver, skills, model, provider, base_url, script, context_from, enabled_toolsets, workdir, no_agent). Backend `_create_cron_job_sync` (web_server.py:13180-13218): resolves profile home (`_cron_profile_home`, 400 invalid name / 404 `Profile '<x>' does not exist.`), validates script inside `<profile_home>/scripts` (`_normalize_dashboard_cron_script` :12786-12806 → 400 `script must be inside …`, `script does not exist: …`, `script is not a file: …`), validates `context_from` refs exist (`_validate_dashboard_cron_context_from` :12868-12889 → 400 `context_from job '<ref>' not found in profile '<p>'`; `self` skipped), `_validate_dashboard_cron_effective_job` (:12809-12828 → 400 `no_agent=True requires a script` / `agent cron jobs require a prompt, skill, or script`), then `create_job_with_scheduler_registration(...)` via `_call_cron_for_profile(profile, "create_job", …)`; partial external-scheduler failure → 424 with `CronSchedulerRegistrationError.to_dict()` (`_raise_if_cron_registration_error` :13088-13098); other exceptions → 400 with message.
- **Inputs / options:** `Profile` select `id="cron-profile"` (one option per profile); then all fields of `CronJobFormFields` (next entries). Backdrop click and Escape close (`useModalBehavior`).
- **Outputs / side effects:** New record in `<profile>/cron/jobs.json`; toast `Create ✓`; form reset; modal closed; list reload. Failure toast `Failed to save: <e>` (`i18n: config.failedToSave`).
- **Config / env:** n/a.
- **Edge cases / guards:** Skills/toolsets/models lists come from the *create profile*, not the dashboard's management profile (comment :678-680).
- **Rebuild notes:** One POST with 13 fields + client pre-validation. Better: server-side schema echo (422 per field) and a "run now once" checkbox.

### Cron job form — basic fields  `id: web-b.cron-form-basic`
- **Surface:** Web dashboard
- **Where:** Inside both `New Cron Job` and `Edit job` modals (`CronJobFormFields`, CronPage.tsx:340-440); element ids prefixed `cron-` (create) / `edit-cron-` (edit).
- **What it does:** Captures name, prompt, schedule, delivery target and attached skills.
- **How it works:** Controlled inputs updating `CronJobEditorState`; skills list from `GET /api/skills?profile=` (installed skills for that profile, sorted), delivery targets from `GET /api/cron/delivery-targets`.
- **Inputs / options:**
  - `Name (optional)` (`i18n: cron.nameOptional`) text input, placeholder `e.g. Daily summary` (`cron.namePlaceholder`), autofocus.
  - `Prompt` (`cron.prompt`) textarea, placeholder `What should the agent do on each run?` (`cron.promptPlaceholder`).
  - Schedule builder (own entry below).
  - `Deliver to` (`cron.deliverTo`) select: `Local` (`cron.delivery.local`) for id `local`; each other target's `name` (e.g. `Telegram`, `Bot Chat (default)`), suffixed ` — set a home channel first` (`cron.delivery.needsHomeChannel`) when `home_target_set` is false; unknown current value appended as its own option (`selectOptions` :168-187). Hint below when only `local` exists: `No messaging platforms configured. Set one up under Channels to deliver reports.` (`cron.delivery.noneConfigured`).
  - `Skills (optional)` — `NameCheckboxPicker` (:74-122): scrollable list (max-h 36) of checkboxes labelled by skill name (title = description); orphaned selected names not in the list are prepended; empty label `No skills installed for this profile.`; helper text `Selected skills are loaded before the prompt runs — the cron sets when, the skill sets how.`
- **Outputs / side effects:** Populates the payload fields `name, prompt, schedule, deliver, skills`.
- **Config / env:** Delivery targets depend on gateway platform config (`cron.scheduler.cron_delivery_targets`, `cron/scheduler.py:2402-2460`: connected platforms with a known home-target env var, plus `bot-chat:<profile>` `Bot Chat (<profile>)` per local profile; the backend's own `local` entry is named `Local (save only)` but the SPA relabels it `Local`).
- **Edge cases / guards:** i18n fallbacks hard-coded for `needsHomeChannel` and `noneConfigured` (`??` operators :363, :410).
- **Rebuild notes:** Straight form; better: prompt templates and a live "preview run" button.

### Schedule builder  `id: web-b.cron-schedule-builder`
- **Surface:** Web dashboard
- **Where:** Cron job form → `Schedule` select `id="cron-schedule-mode"` (`i18n: cron.scheduleMode`) and mode-specific inputs (`web/src/components/ScheduleBuilder.tsx:39-235`); preview line `Sends as: <string>` (`cron.scheduleModes.preview`) or `(incomplete)` (`cron.scheduleModes.previewEmpty`).
- **What it does:** Lets the user pick a recurrence with human inputs and converts it to the single schedule string accepted by `cron/jobs.py::parse_schedule`.
- **How it works:** Pure logic in `web/src/lib/schedule.ts`. `buildScheduleString` (:104-148): interval → `every {n}{m|h|d}`; daily → `{min} {hour} * * *`; weekly → `{min} {hour} * * {sorted days or *}`; monthly → `{min} {hour} {dom} * *`; once → `YYYY-MM-DDTHH:MM:00` (appends `:00` when 16 chars); custom → trimmed raw string. `parseScheduleString` (:151-205) reverses it when editing (ISO → once; `every N[mhd]` → interval; simple 5-field cron → daily/weekly/monthly; anything else → custom). Defaults `DEFAULT_SCHEDULE_STATE` (:78-87): mode interval, 30 minutes, timeOfDay `09:00`, weekdays Mon–Fri `[1,2,3,4,5]`, dayOfMonth 1. Backend grammar (`cron/jobs.py:962-1042`): `every 30m`, `2h`, `every monday 9am`, `weekdays at 9am`, 5/6-field cron (named months/days allowed, needs `croniter`), ISO timestamps.
- **Inputs / options:** Mode select options: `Every interval` (`scheduleModes.interval`), `Daily`, `Weekly`, `Monthly`, `Once`, `Custom (cron expression)`. Interval mode: number input `Every` (`scheduleModes.intervalEvery`, `id="cron-interval-value"`, min 1 max 9999, invalid → 1) + select `Unit` (`intervalUnit`) with `minutes|hours|days` (`unitMinutes/unitHours/unitDays`). Daily: time input `Time of day` (`timeOfDay`, `id="cron-daily-time"`). Weekly: group `Days of week` (`weekdays`, `role="group"`) with 7 toggle buttons `Sun Mon Tue Wed Thu Fri Sat` (`weekdaysShort`, `aria-pressed`) + time input `id="cron-weekly-time"`. Monthly: number `Day of month` (`dayOfMonth`, `id="cron-month-day"`, 1–31, invalid → 1) + time `id="cron-monthly-time"`. Once: `datetime-local` input `Run at` (`onceAt`, `id="cron-once-at"`). Custom: text input `Cron expression` (`customLabel`, `id="cron-custom-expr"`, placeholder `0 9 * * *`) with hint `Five-field cron expression (minute, hour, day, month, weekday).` (`customHint`).
- **Outputs / side effects:** Emits the schedule string into the payload; state slots for every mode preserved across mode switches.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty weekday selection emits `*` (every day) rather than an invalid expr (schedule.ts:119-127); `L` last-day cron sugar unsupported; time regex `^\d{1,2}:\d{2}$` with range checks.
- **Rebuild notes:** Two pure functions (build/parse) + a mode-switched form. Better: next-N-fires preview computed from the expression and timezone selector.

### Cron job form — Advanced fields  `id: web-b.cron-form-advanced`
- **Surface:** Web dashboard
- **Where:** Cron job form → collapsible `<details open>` with summary `Advanced fields` (static, CronPage.tsx:189-330); ids prefixed `cron-advanced-` / `edit-cron-advanced-`.
- **What it does:** Sets per-job model/provider/base URL, script mode, working directory, continuity, cross-job context and toolset restrictions.
- **How it works:** Provider list = `modelOptions.providers` filtered `authenticated !== false` from `GET /api/models/options?profile=`; selecting a provider resets model to `""`; models = that provider's `models[]`. Toolsets from `GET /api/toolsets?profile=` (via `api.getToolsets`). Values flow into `buildCronJobPayload` (cron-job.ts). `context_from` textarea split on newlines/commas; `continuity` checkbox becomes the reserved `self` entry (cron-job.ts:45-51) — reading back, `self` or an explicit `continuity` flag re-checks the box (:77-104).
- **Inputs / options:** `Provider` select (`Default` = "" + provider names by slug); `Model` select (`Default` + model ids); `Base URL override` input placeholder `https://api.example.com/v1`; checkbox `no_agent: run the script only and deliver stdout verbatim`; `Script` input placeholder `relative/path/in/scripts`; `Workdir` input placeholder `/absolute/project/path`; checkbox `continuity: each run sees the previous run's output (dedupe, pick up where it left off)`; textarea `context_from job IDs` placeholder `one job id per line`; `enabled_toolsets` checkbox picker (title = toolset description) with empty label `No toolsets available.`.
- **Outputs / side effects:** Payload fields `provider, model, base_url, script, no_agent, workdir, context_from, enabled_toolsets`.
- **Config / env:** Script must live under `<profile_home>/scripts` (server-enforced).
- **Edge cases / guards:** Unknown stored provider/model values are appended as extra options so editing a job created via CLI does not silently drop them (`selectOptions`). Hand-typed `self` in `context_from` is stripped and re-added only via the checkbox.
- **Rebuild notes:** Optional overrides serialised as null when blank so PUT clears them; better: validate script path/toolset names against the server before submit.

### Edit job modal  `id: web-b.cron-edit-modal`
- **Surface:** Web dashboard
- **Where:** Job card `Edit job` → dialog `aria-labelledby="edit-cron-title"`, heading `Edit job` (static), footer shows the job id (monospace) and button `Save changes` / `Loading...` (`i18n: common.loading`).
- **What it does:** Edits every field of an existing job and PUTs the full normalised payload.
- **How it works:** `openEditModal` (CronPage.tsx:610-613) → `editorFormFromJob` = `cronJobFormFromJob(job)` (schedule from `schedule.expr` → `schedule.run_at` → `schedule_display`) + `parseScheduleString`. `handleEdit` (:725-754) same validation toasts as create, then `api.updateCronJob(id, payload, profile)` = `PUT /api/cron/jobs/{id}?profile=` with body `{"updates": {...}}` (`CronJobUpdate`, web_models.py:407-408). Backend `_update_cron_job_sync` (web_server.py:13223-13256): 404 if profile/job missing; `_normalize_dashboard_cron_updates` (:12831-12865) trims model/provider/workdir, validates script, strips base_url trailing slash, `deliver` default `local`, list-normalises `context_from`/`enabled_toolsets`; validates `context_from`; when any of `prompt, skill, skills, script, no_agent` change, validates the effective merged job; `update_job(job_id, updates)` + provider reconcile; `ValueError` → 400.
- **Inputs / options:** Same fields as create (no Profile select — the job's own profile is used); close `X`, backdrop, Escape.
- **Outputs / side effects:** Toast `Saved changes ✓`; list reload; `Failed to save: <e>` on error.
- **Config / env:** n/a.
- **Edge cases / guards:** Skills list shown is the one loaded for the job's profile; a job's current skills are always displayed even if not installed.
- **Rebuild notes:** PUT with a partial-update envelope; better: diff-only updates and optimistic concurrency (ETag on jobs.json).

### Cron delivery targets endpoint  `id: web-b.cron-delivery-targets-api`
- **Surface:** API
- **Where:** `GET /api/cron/delivery-targets` (`hermes_cli/web_routers/cron.py:83-108`).
- **What it does:** Lists where a cron job may auto-deliver its report.
- **How it works:** Always prepends `{"id":"local","name":"Local (save only)","home_target_set":true,"home_env_var":null}` then extends with `cron.scheduler.cron_delivery_targets()` (`cron/scheduler.py:2402-2460`): for each platform in `_iter_home_target_platforms()` that is connected per `gateway.config.load_gateway_config().get_connected_platforms()` (plus relay-fronted platforms) and `_is_known_delivery_platform`, emits `{id: platform, name: Title Case, home_target_set: bool(_get_home_target_chat_id(name)), home_env_var}`; then one `{id: "bot-chat:<profile>", name: "Bot Chat (<profile>)", home_target_set: true}` per local profile (`hermes_cli.profiles.list_profile_names`).
- **Inputs / options:** none.
- **Outputs / side effects:** `{"targets":[…]}`; live: `local` + `bot-chat:default` (`api_live/get_all.json`).
- **Config / env:** Gateway platform credentials + per-platform home env vars (e.g. `TELEGRAM_HOME_CHANNEL`-style, resolved by `_resolve_home_env_var`), `cron.*` config.
- **Edge cases / guards:** Exceptions are logged and swallowed so the dropdown always has `local`.
- **Rebuild notes:** Derive from connected platforms; better: include a "test delivery" action.

### Automation Blueprints gallery  `id: web-b.cron-blueprints`
- **Surface:** Web dashboard
- **Where:** `/cron` → Segmented `Blueprints` → grid of cards (`web/src/components/AutomationBlueprints.tsx:173-223`); each card: wand icon + `title`, `description`, tag badges, button `Set up` / `Cancel`, expanded form with one field per slot, error line `role="alert"`, button `Schedule it` (clock icon; spinner while submitting). Loading text `Loading blueprints…`; error `Couldn't load blueprints: <msg>`; empty `No automation blueprints available.`
- **What it does:** Creates a ready-made cron job (prompt + schedule + skills) from a typed form, without writing a cron expression.
- **How it works:** `api.getAutomationBlueprints()` = `GET /api/cron/blueprints` (`web_routers/cron.py:272-303`): serialises `cron.blueprint_catalog.CATALOG` via `blueprint_catalog_entry` (`cron/blueprint_catalog.py:686-696`: form schema + `schedule` template + `scheduleHuman` + `command` slash string + `appUrl` `hermes://blueprint/<key>?…`), and rewrites the `deliver` slot's options to `["origin","local", *connected platform ids]` from `cron_delivery_targets()`. Form initial values = each field's default (`initialValues`). `FieldInput` (:29-67): `enum`/`weekdays` → Select of `options`; `time` → `<input type=time>`; `text` → text input with placeholder = help or label; help text shown under non-text fields. Submit → `api.instantiateAutomationBlueprint({blueprint: key, values}, profile)` = `POST /api/cron/blueprints/instantiate?profile=` (`web_routers/cron.py:306-339`): `get_blueprint` (404 `Unknown blueprint: <key>`), `fill_blueprint` (`blueprint_catalog.py:770-799`: unknown slot names → error `unknown slot(s): … — valid: …`; missing required → `missing required value: <name> (<label>)`; strict enum mismatch → `<name>=<v> not allowed — one of …`; `_resolve_schedule` fills `{minute}{hour}` from `HH:MM` (error `invalid time … — use HH:MM (24h)`), `{dow}` from `recurrence` preset (`everyday→*`, `weekdays→1-5`, `weekends→0,6`) or `day` name, `{interval_min}` positive int, other placeholders verbatim; prompt = `prompt_template.format(**resolved)`; spec = `{prompt, schedule, name: title, deliver, skills}`) → 422 with the message; `spec.pop("origin")`; `create_job` via `_call_cron_for_profile` + provider reconcile; 424 on registration error; 400 otherwise.
- **Inputs / options:** Profile = the page's selected profile (or `default` for `All profiles`). Per blueprint (live catalog, 16 entries, `hermes_inv/api_live/get_all.json["/api/cron/blueprints"]`) — every field listed:
  1. `morning-brief` **Morning briefing** (`daily`; tags daily, briefing; schedule `{minute} {hour} * * *`, human `daily at 08:00`; skills `google-workspace`): `What time?` (time, default `08:00`, help `24h local time, e.g. 08:00`); `Where to deliver?` (enum, default `origin`, options `origin, local, bot-chat:default` live / static `origin, local, telegram, discord, email`, non-strict, help `origin = the chat you set this up from (or your configured home channel when created from the dashboard); local = save only, no message; or any connected platform name`).
  2. `important-mail` **Important-mail monitor** (`email`; tags email, monitor; `*/{interval_min} * * * *`, `every 30 minutes`): `How often?` (enum `15|30|60`, default `30`, help `minutes between checks`); `Only notify me if the mail…` (text, default `needs a reply today, is from my manager or family, or mentions a deadline`); `Where to deliver?`.
  3. `weekly-review` **Weekly review** (`weekly`; tags weekly, review; `{minute} {hour} * * {dow}`, `sunday at 18:00`): `What time?` (default `18:00`); `Which day?` (enum `sunday|monday|friday|saturday`, default `sunday`); `Where to deliver?`.
  4. `workday-start` **Workday start reminder** (`daily`; tags daily, focus; `{minute} {hour} * * 1-5`, `weekdays at 09:00`): `What time?` (`09:00`); `Where to deliver?`.
  5. `custom-reminder` **Custom reminder** (`general`; tag reminder; `{minute} {hour} * * {dow}`, `everyday at 14:00`): `Remind me to…` (text, default `take a break and stretch`); `What time?` (`14:00`); `Repeat on` (weekdays `everyday|weekdays|weekends`, default `everyday`); `Where to deliver?`.
  6. `evening-winddown` **Evening wind-down** (`daily`; tags daily, evening; `daily at 21:00`): `What time?` (`21:00`); `Where to deliver?`.
  7. `news-digest` **Topic news digest** (`general`; tags digest, research; `{minute} {hour} * * {dow}`, `weekdays at 18:00`): `What topic?` (text, default `AI and technology`, help `a subject, product, person, or search phrase`); `What time?` (`18:00`); `Repeat on` (default `weekdays`); `How many bullets?` (enum `3|5|8`, default `5`); `Where to deliver?`.
  8. `bill-renewal-watch` **Bills & renewals reminder** (`general`; tags reminder, finance; `everyday at 10:00`): `What's due?` (text, default `my streaming subscription renews soon`); `What time?` (`10:00`); `Repeat on` (`everyday`); `Where to deliver?`.
  9. `price-watch` **Price & availability watch** (`general`; tags prices, shopping, travel, monitor; `0 */{interval_h} * * *`, `on a schedule`): `What exactly to watch?` (text, default `a product URL or exact flight/hotel/listing description`, help `URL or precise description — variant, dates, seller`); `Alert me when…` (text, default `the all-in price drops below my target`, help `threshold price (state the currency), availability, or terms change`); `How often?` (enum `1|3|6|12|24`, default `6`, help `hours between checks — be gentle with rate limits`); `Where to deliver?`.
  10. `competitor-watch` **Competitor news watch** (`general`; tags competitors, news, monitor, research; `monday at 09:00`): `Which companies?` (text, default `two or three competitors, by canonical name`, help `canonical names and domains; aliases help dedup`); `Which events matter?` (text, default `product launches, pricing changes, funding, partnerships, executive moves, incidents`); `What time?` (`09:00`); `Repeat on` (default `monday` — note: not in the `everyday|weekdays|weekends` option list, so the Select shows an unlisted default); `Where to deliver?`.
  11. `habit-checkin` **Habit check-in** (`general`; tags habit, wellbeing; `everyday at 20:00`): `Which habit?` (text, `20 minutes of reading`); `What time?` (`20:00`); `Repeat on` (`everyday`); `Where to deliver?`.
  12. `hydration-move` **Hydration & movement nudge** (`general`; tags wellbeing, focus; `0 {start_hour}-{end_hour}/{interval_hours} * * 1-5`, `weekdays, every hour`): `How often?` (enum `1|2|3`, default `1`, help `hours between nudges`); `Start hour` (enum `7|8|9|10`, default `9`, help `first hour of the active window (24h)`); `End hour` (enum `16|17|18|19`, default `17`, help `last hour of the active window (24h)`); `Where to deliver?`.
  13. `meal-plan` **Weekly meal plan** (`weekly`; tags weekly, food; `sunday at 17:00`): `Diet?` (enum `no restrictions|vegetarian|vegan|high-protein|low-carb`); `Meals per day?` (enum `dinner only|lunch and dinner|all three`); `Cooking effort?` (enum `quick|medium|ambitious`); `What time?` (`17:00`); `Which day?` (`sunday|monday|friday|saturday`); `Where to deliver?`.
  14. `learn-daily` **Daily learning drip** (`daily`; tags learning, daily; `weekdays at 08:30`): `Learn about…` (text, `Spanish vocabulary`); `What time?` (`08:30`); `Repeat on` (`weekdays`); `Where to deliver?`.
  15. `gratitude-journal` **Gratitude & reflection prompt** (`general`; tags wellbeing, reflection; `everyday at 21:30`): `What time?` (`21:30`); `Repeat on` (`everyday`); `Where to deliver?`.
  16. `on-this-day` **On-this-day discovery** (`daily`; tags daily, curiosity; `daily at 07:30`): `What kind?` (enum `on this day in history|word of the day|science fact|quote of the day`); `What time?` (`07:30`); `Where to deliver?`.
- **Outputs / side effects:** Creates a job named after the blueprint title; toast `<title> scheduled — <schedule_display>`; card collapses and values reset; parent job list refreshed (`onCreated`). 422 messages are shown inline with the leading `NNN: ` stripped.
- **Config / env:** n/a (uses the same store as manual jobs).
- **Edge cases / guards:** `deliver` slot is non-strict (any platform accepted; validated downstream by the scheduler); `origin` from the dashboard means the configured home channel; the `command` and `appUrl` fields are returned by the API but not rendered on this page (they power docs/CLI `/blueprint`).
- **Rebuild notes:** A catalog of `{key,title,description,category,schedule_template,prompt_template,slots[]}` + a filler that validates slots and emits a create-job spec; render as cards with typed fields. Better: show the generated prompt/schedule preview before scheduling, allow editing the prompt, and support user-defined blueprints.

### Cron run history endpoint (API-only in SPA)  `id: web-b.cron-runs-api`
- **Surface:** API
- **Where:** `GET /api/cron/jobs/{job_id}/runs?profile=&limit=20` (`web_routers/cron.py:73-75`).
- **What it does:** Lists the sessions produced by one cron job, newest first (used by the desktop app's cron detail; not rendered by the web SPA at this version).
- **How it works:** `_list_cron_job_runs_sync` (web_server.py:13133-13177): resolves job to canonical id (name accepted), clamps `limit` 1–100 (default 20), opens the profile's session DB read-only and calls `SessionDB.list_cron_job_runs(canonical, limit, offset=0)` — a bounded id-range scan over session ids `cron_{job_id}_{timestamp}` with `source='cron'`; adds `is_active` (not ended and active within 300 s), `archived`, `profile`.
- **Inputs / options:** path `job_id`, query `profile`, `limit`.
- **Outputs / side effects:** `{"runs":[SessionInfo…], "limit": n}`.
- **Config / env:** n/a.
- **Edge cases / guards:** Same row shape as `/api/sessions`.
- **Rebuild notes:** Index sessions by job prefix; better: surface in the web cron card.

### Other cron API routes reachable from the page  `id: web-b.cron-api-misc`
- **Surface:** API
- **Where:** `GET /api/cron/jobs?profile=all|<name>`; `GET /api/cron/jobs/{job_id}?profile=`; `POST /api/cron/fire` (`web_routers/cron.py:63-70, 136-269`). Literal FastAPI paths of the whole cron router (`routes_static.txt`): `GET /api/cron/jobs`, `GET /api/cron/jobs/{job_id}`, `GET /api/cron/jobs/{job_id}/runs`, `POST /api/cron/jobs`, `GET /api/cron/delivery-targets`, `PUT /api/cron/jobs/{job_id}`, `POST /api/cron/jobs/{job_id}/pause`, `POST /api/cron/jobs/{job_id}/resume`, `POST /api/cron/jobs/{job_id}/trigger`, `DELETE /api/cron/jobs/{job_id}`, `POST /api/cron/fire`, `GET /api/cron/blueprints`, `POST /api/cron/blueprints/instantiate`.
- **What it does:** `GET /api/cron/jobs` returns all jobs (including disabled) for one profile or every profile, each annotated with `profile`, `profile_name`, `hermes_home`, `is_default_profile` (`_annotate_cron_job` web_server.py:12940-12946). `GET /api/cron/jobs/{id}` returns one job (404 `Job not found`). `POST /api/cron/fire` is the Chronos managed-cron webhook (public path; Bearer JWT verified by `plugins.cron_providers.chronos.verify.get_fire_verifier` against `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`, `cron.chronos.portal_url`), which forwards the fire to the gateway api_server on loopback; responses: 401 `invalid fire token`, 400 `missing job_id`, 200 `{"status":"gone"}` when job absent, 200 `{"status":"gateway_stopped",…}` when the gateway is deliberately stopped, 503 `gateway unreachable; retry` with `Retry-After: 60`, else the gateway's own status/body.
- **How it works:** `web_routers/cron.py` thin-wraps three sync helpers executed in a worker thread under `_profile_scope`: `_list_cron_jobs_sync` (web_server.py:13061-13086 — `profile=all` iterates `hermes_cli.profiles.list_profile_names()` and swallows per-profile failures, otherwise resolves one profile home via `_cron_profile_home`), `_get_cron_job_sync` (web_server.py:13101-13130 — `_call_cron_for_profile(profile, "get_job", job_id)`, 404 `Job not found`), and the Chronos fire verifier (`plugins.cron_providers.chronos.verify.get_fire_verifier` → JWT `aud`/JWKS check, then an HTTP forward to the gateway api_server on loopback). Every response row passes through `_annotate_cron_job` (web_server.py:12940-12946) which adds `profile`, `profile_name`, `hermes_home` and `is_default_profile`.
- **Inputs / options:** as above.
- **Outputs / side effects:** `POST /api/cron/fire` stamps `last_fire_error` on the job when forwarding fails (`note_fire_forward_failure`) — this is the text the page renders as `missed scheduled fire (...)`.
- **Config / env:** `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`, `cron.chronos.portal_url`, `API_SERVER_KEY` (gateway api_server binding).
- **Edge cases / guards:** Not dashboard-cookie protected (`PUBLIC_API_PATHS`).
- **Rebuild notes:** Keep fire execution in the process that owns platform adapters; the dashboard only verifies and forwards.

---

## 3. Skills page (`/skills`)

### Skills page shell, header and profile scoping  `id: web-b.skills-page`
- **Surface:** Web dashboard
- **Where:** Sidebar `SKILLS` → `/skills`; H1 `Skills` (`i18n: skills.title`). Header after-title text `{enabled}/{total} enabled` (`i18n: skills.enabledOf`); header end-slot search `Input` placeholder `Search...` (`i18n: common.search`) with clear icon button `aria-label="Clear"` (`i18n: common.clear`) shown while text is present. Left `aside aria-label="Skills"` panel titled `Filters` (`i18n: skills.filters`, hidden on mobile) with three `PanelItem`s: `All (N)` (`i18n: skills.all`), `Toolsets (N)` (`i18n: skills.toolsets`), `Browse hub` (static) — rendered uppercase (`ALL (53)`, `TOOLSETS (27)`, `BROWSE HUB` in the crawl). Plugin slots `skills:top`, `skills:bottom`.
- **What it does:** Central place to enable/disable installed skills, author SKILL.md files, configure tool backends (toolsets) and browse/install skills from remote hubs, all scoped to the profile chosen in the global profile switcher.
- **How it works:** `web/src/pages/SkillsPage.tsx:128-734`. On mount and whenever `selectedProfile` (from `useProfileScope()`, `web/src/contexts/useProfileScope.ts`; deep-linkable `?profile=<name>`) changes it loads `api.getSkills(profile)` = `GET /api/skills?profile=` and `api.getToolsets(profile)` = `GET /api/tools/toolsets?profile=` in parallel (SkillsPage.tsx:155-174); on failure toast `Loading...` (`common.loading`, error). `view` state ∈ `skills | toolsets | hub` (default `skills`); `activeCategory` (null = all, `__none__` = uncategorised); `search` string. Loading state: centred Spinner; header slots cleared while loading.
- **Inputs / options:** Search input (filters skills by name/description/category, or toolsets by name/label/description depending on view); Clear button; panel items `All (N)` (resets category + search, view=skills), `Toolsets (N)` (view=toolsets, clears search), `Browse hub` (view=hub, clears search); categories list (own entry).
- **Outputs / side effects:** Read-only until a toggle/edit is used. i18n strings `managingProfile` (`Managing profile “{name}” — toggles apply to that profile, not this dashboard’s.`), `profileSelector` (`Profile`), `currentProfile` (`current ({name})`) exist in `en.ts:423-446` for the profile banner rendered by the shared `ProfileScopeBanner` component (web-a shard).
- **Config / env:** `skills.disabled` (config.yaml, per profile) governs enabled state; `HERMES_HOME/skills/` is the skills dir.
- **Edge cases / guards:** Old list stays visible until the new profile's list arrives (comment :156-158). Search mode replaces the category-filtered list with a `Skills` card (own entry).
- **Rebuild notes:** Three-view page driven by two GETs + profile context. Better: URL-persisted view/category, virtualised list for hundreds of skills.

### Skills list, categories and search results  `id: web-b.skills-list`
- **Surface:** Web dashboard
- **Where:** `/skills` → `All` view: Card title `All` (`skills.all`) or the pretty category name; badge `{count} skill{s}` (`skills.skillCount`); buttons `Learn a skill` (sparkles icon) and `New skill` (plus icon); rows of `SkillRow`. Sidebar sub-section `Categories` (`skills.categories`) lists `<Pretty name> <count>` items (crawl: `Autonomous Ai Agents 5`, `Creative 10`, `Email 2`, `Media 3`, `Note Taking 1`, `Productivity 14`, `Research 4`, `Social Media 1`, `Software Development 12`, `Web 1`). Search mode: Card title `Skills` with badge `{count} result{s}` (`skills.resultCount`).
- **What it does:** Shows every discovered skill for the profile (sorted by name), filterable by category or free-text, each with an on/off switch and an edit button.
- **How it works:** `allCategories` (SkillsPage.tsx:291-308) counts `skill.category || "__none__"` and sorts `__none__` first then alphabetically; `prettyCategory` (:87-97) maps via `CATEGORY_LABELS` (`mlops→MLOps`, `mlops/cloud→MLOps / Cloud`, `mlops/evaluation→MLOps / Evaluation`, `mlops/inference→MLOps / Inference`, `mlops/models→MLOps / Models`, `mlops/training→MLOps / Training`, `mlops/vector-databases→MLOps / Vector DBs`, `mcp→MCP`, `red-teaming→Red Teaming`, `ocr→OCR`, `p5js→p5.js`, `ai→AI`, `ux→UX`, `ui→UI`) else Title-Cases on `-_/`; uncategorised label = `General` (`common.general`). `activeSkills` (:278-289) filters by `activeCategory`; `searchMatchedSkills` (:268-276) matches lower-cased substring in name, description or category. Clicking an active category again deselects it. `SkillRow` (:736-778): `Switch` (disabled while toggling), name in mono (muted when disabled), description clamped to 2 lines or `No description available.` (`skills.noDescription`), hover-revealed icon button `title="Edit SKILL.md"` `aria-label="Edit <name>"`.
- **Inputs / options:** Category `ListItem`s (toggle select); per-row `Switch`; per-row edit pencil; `Learn a skill`; `New skill`.
- **Outputs / side effects:** Empty states: `No skills found. Skills are loaded from ~/.hermes/skills/` (`skills.noSkills`, when no skills at all) or `No skills match your search or filter.` (`skills.noSkillsMatch`).
- **Config / env:** n/a.
- **Edge cases / guards:** Categories panel hidden while searching and on small screens (`hidden sm:flex`); panel scroll capped at `calc(100vh-340px)`.
- **Rebuild notes:** Derive categories client-side from the flat list. Better: multi-select categories, sort by usage (`usage` is already returned by the API but unused here).

### Toggle skill on/off  `id: web-b.skills-toggle`
- **Surface:** Web dashboard
- **Where:** Skill row `Switch` (role `switch`).
- **What it does:** Enables or disables a skill for the selected profile (disabled skills are hidden from the agent's skill index).
- **How it works:** `handleToggleSkill` (SkillsPage.tsx:177-199) → `api.toggleSkill(name, !enabled, profile)` = `PUT /api/skills/toggle` body `{name, enabled, profile}` (`SkillToggle`, web_models.py:650-653). Handler `toggle_skill` (`hermes_cli/web_routers/skills.py:465-481`): under `_profile_scope` + `_CONFIG_MUTATION_LOCK`, `get_disabled_skills(config)` → add/discard name → `save_disabled_skills` (`hermes_cli/skills_config.py:67-79`, writes `skills.disabled` sorted list; `ESSENTIAL_SKILLS` such as `hermes-agent` are silently dropped so they can never be disabled).
- **Inputs / options:** the switch only.
- **Outputs / side effects:** `{"ok":true,"name","enabled"}`; local list patched optimistically after success; toast `<name> enabled` / `<name> disabled` (`common.enabled/disabled`) or `Failed to toggle <name>` (`common.failedToToggle`).
- **Config / env:** `skills.disabled` (global), `skills.platform_disabled.<platform>` (not written by this UI).
- **Edge cases / guards:** Per-skill `togglingSkills` set prevents double-clicks.
- **Rebuild notes:** One PUT flipping membership in a config list.

### `GET /api/skills` (skill inventory)  `id: web-b.skills-api-list`
- **Surface:** API
- **Where:** `GET /api/skills?profile=`.
- **What it does:** Lists every skill visible to the profile with enabled flag, usage count and provenance.
- **How it works:** `get_skills` (`web_routers/skills.py:430-462`): `tools.skills_tool._find_all_skills(skip_disabled=True)` (scans project-local skill dirs, `<HERMES_HOME>/skills`, external dirs; cached by mtime signature, `tools/skills_tool.py:687-727`), `get_disabled_skills(config)`, `tools.skill_usage.load_usage()`; annotates `enabled` (not in disabled set), `usage` (`activity_count`), `provenance` = `hub` (in `skills/.hub/lock.json`) | `bundled` (in bundled manifest) | `agent` (agent-authored or hand-made).
- **Inputs / options:** `profile` query.
- **Outputs / side effects:** JSON array of `{name, description, category, enabled, usage, provenance}`; live: 53 skills, categories `autonomous-ai-agents, creative, email, media, note-taking, productivity, research, social-media, software-development, web`.
- **Config / env:** `skills.disabled`, `skills.external_dirs`.
- **Edge cases / guards:** Runs in a worker thread inside `_profile_scope` (process-global skills lock).
- **Rebuild notes:** Directory scan of `*/SKILL.md` frontmatter + config overlay.

### New skill editor dialog  `id: web-b.skills-new-skill`
- **Surface:** Web dashboard
- **Where:** `/skills` → `All` view → button `New skill` → `Dialog` titled `New skill`, description `Author a custom skill — YAML frontmatter plus markdown instructions. It becomes available to the agent and attachable to cron jobs.` (`web/src/components/SkillEditorDialog.tsx:48-215`).
- **What it does:** Creates a new local skill directory with a SKILL.md written in the browser.
- **How it works:** `EditorBody` remounted via `key` per open. Content pre-filled with `CREATE_TEMPLATE` (:27-35: frontmatter `name: my-skill`, `description: One-line description of when to use this skill.`, heading `# My Skill`, line `Numbered steps, exact commands, and pitfalls go here.`). `handleSave` (:102-135): client checks `Skill name is required.` and `SKILL.md content is required.`; then `api.createSkill({name, content, category}, profile)` = `POST /api/skills` body `SkillCreate {name, content, category?, profile?}` → `create_skill` (`web_routers/skills.py:506-525`) → `tools.skill_manager_tool._create_skill` (`tools/skill_manager_tool.py:978-1030`): `_validate_name` (`^[a-z0-9][a-z0-9._-]*$`, ≤64 chars → `Invalid skill name '<n>'. Use lowercase letters, numbers, hyphens, dots, and underscores. Must start with a letter or digit.` / `Skill name exceeds 64 characters.`), `_validate_category` (single dir segment, same charset → `Invalid category '<c>'. …`), `_validate_frontmatter(new_skill=True)` (`Content cannot be empty.`, `SKILL.md must start with YAML frontmatter (---). …`, `SKILL.md frontmatter is not closed. …`, name/description required; description ≤ `SKILL_PROMPT_DESC_LIMIT`=60 chars for new skills), `_validate_content_size` (≤ `MAX_SKILL_CONTENT_CHARS`=100 000), collision check `A skill named '<n>' already exists at <path>.`, writes `<skills>/<category?>/<name>/SKILL.md` atomically (mode 0644), then `_security_scan_skill` — on block the dir is deleted and `Security scan blocked this skill (<reason>):\n<report>` returned. Route returns 400 with the error text; on success `_clear_skills_prompt_cache()`.
- **Inputs / options:** `Name` input `id="skill-editor-name"` placeholder `my-skill` (autofocus); `Category (optional)` input `id="skill-editor-category"` placeholder `devops`; `SKILL.md` textarea `id="skill-editor-content"` (min-height 320px, spellcheck off); buttons `Cancel`, `Create skill` / `Saving…` (disabled while saving/loading).
- **Outputs / side effects:** New directory on disk; dialog closes; parent toast `<name> saved ✓` and list reload (`handleEditorSaved` SkillsPage.tsx:251-262). Server errors rendered inline in red (pre-wrap).
- **Config / env:** `HERMES_HOME/skills`.
- **Edge cases / guards:** Bypasses the agent's write-approval gate — the authenticated dashboard user IS the approver (docstring :508-513).
- **Rebuild notes:** Textarea + POST to a validated writer. Better: frontmatter form fields + live markdown preview + a file tree for the sibling files bundled skills actually use (`references/`, `scripts/`, `templates/`, `tests/`, `LICENSE`, `README.md`).

### Edit skill (SKILL.md) dialog  `id: web-b.skills-edit-skill`
- **Surface:** Web dashboard
- **Where:** Skill row pencil `Edit SKILL.md` → Dialog `Edit skill: <name>`, description `Rewrite this skill's SKILL.md. Frontmatter (name, description) is validated on save.`
- **What it does:** Loads the raw SKILL.md and replaces it wholesale on save.
- **How it works:** `api.getSkillContent(name, profile)` = `GET /api/skills/content?name=&profile=` (`web_routers/skills.py:484-503`; `_find_skill(name)` → 404 `Skill '<n>' not found.` / `Skill '<n>' has no SKILL.md.`; returns `{name, content, path}`). Save → `api.updateSkillContent(name, content, profile)` = `PUT /api/skills/content` body `SkillContentUpdate {name, content, profile?}` → `_edit_skill` (`tools/skill_manager_tool.py:1077-1120`: frontmatter + size validation without the 60-char description limit, org-mirror and background-review write guards, atomic write with backup, security scan with rollback). 404 when error contains `not found`, else 400.
- **Inputs / options:** `SKILL.md` textarea (spinner while loading); `Cancel`; `Save changes` / `Saving…`.
- **Outputs / side effects:** File rewritten; toast `<name> saved ✓`; list reload.
- **Config / env:** n/a.
- **Edge cases / guards:** Works for bundled/hub skills too (any `_find_skill` hit) — edits to bundled skills are local overrides subject to org-mirror guard.
- **Rebuild notes:** GET/PUT of one file.

### Learn a skill dialog  `id: web-b.skills-learn`
- **Surface:** Web dashboard
- **Where:** `/skills` → `Learn a skill` → Dialog title `Learn a skill`, description `Point Hermes at anything and it will distill a reusable skill — following the house authoring standards. Fill in any combination below; the agent gathers the sources and writes the skill in chat.` (SkillsPage.tsx:673-730).
- **What it does:** Composes a `/learn` instruction from up to three inputs and hands it to the Chat page so the live agent authors a skill.
- **How it works:** `submitLearn` (:233-246): segments `local source: <dir>`, `URL: <url>`, free text; joined with `; `, newlines flattened; navigates to `/chat?learn=<encoded>`. No backend endpoint — Chat resolves `?learn=` into a normal `/learn` slash-command turn (dispatch handled by ChatPage, web-a shard).
- **Inputs / options:** `Local file or directory` input placeholder `~/projects/some-sdk  (read with read_file / search_files)`; `URL` input placeholder `https://docs.example.com/api  (fetched with web_extract)`; textarea labelled `Anything else — describe the workflow, paste notes, or say "what we just did"` placeholder `e.g. how I file an expense report: open the portal, …`; buttons `Cancel`, `Learn it` (disabled until at least one field is non-blank).
- **Outputs / side effects:** Route change to `/chat?learn=…`; the agent later writes via `skill_manage`.
- **Config / env:** n/a.
- **Edge cases / guards:** Fields reset on every open.
- **Rebuild notes:** Pure client composition; better: show the resulting `/learn` command before sending.

### Toolsets grid  `id: web-b.toolsets-grid`
- **Surface:** Web dashboard
- **Where:** `/skills` → panel item `Toolsets (N)` → responsive grid (1/2/3 columns) of toolset cards (SkillsPage.tsx:569-652). Each card: icon (picked by name substring — `computer→Cpu, web→Globe, security→Shield, vision→Eye, design→Paintbrush, ai→Brain, integration→Blocks, code→Code, automation→Zap`, else Wrench; :99-122), label, badge `active`/`inactive` (`common.active/inactive`), description, amber line `Setup needed` (`skills.setupNeeded`) when enabled but not configured, chips of tool names, or (no tools) `{name} toolset` (`skills.toolsetLabel`) when enabled / `Disabled for CLI` (`skills.disabledForCli`), and button `Configure` (wrench icon). Empty: `No toolsets match the search.` (`skills.noToolsetsMatch`).
- **What it does:** Shows every configurable toolset for the profile with its enablement, key status and the tools it exposes; opens the configuration drawer.
- **How it works:** `GET /api/tools/toolsets?profile=` (`hermes_cli/web_routers/tools.py:62-125`): `_get_effective_configurable_toolsets()` rows `(name,label,desc)`, per-platform enabled sets via `_get_platform_tools(config, platform, include_default_mcp_servers=False)`, `resolve_toolset(name)` for tool names, `_toolset_has_keys` → `configured`; config-only toolsets (`_CONFIG_ONLY_TOOLSETS = {"stt"}`) read `<name>.enabled`. Response rows `{name,label,description,platform,platform_label,enabled,available,configured,tools[]}`. `filteredToolsets` (SkillsPage.tsx:361-369) applies the header search.
- **Inputs / options:** `Configure` button per card (opens `ToolsetConfigDrawer`).
- **Outputs / side effects:** none (read-only view). Live inventory (27 toolsets, `api_live/get_all.json["/api/tools/toolsets"]`): `web` (Web Search & Scraping: web_extract, web_search), `browser` (Browser Automation: browser_back, browser_cdp, browser_click, browser_console, browser_dialog, browser_exec, browser_get_images, browser_navigate, browser_press, browser_scroll, browser_snapshot, browser_type, browser_vision, web_search), `terminal` (Terminal & Processes: process, terminal), `file` (File Operations: patch, read_file, search_files, write_file), `code_execution` (execute_code), `vision` (Vision / Image Analysis: vision_analyze), `video` (Video Analysis: video_analyze), `image_gen` (image_generate), `video_gen` (video_generate, xai_video_edit, xai_video_extend), `x_search` (X (Twitter) Search: x_search), `tts` (Text-to-Speech: text_to_speech), `stt` (Speech-to-Text: no tools), `skills` (skill_manage, skill_view, skills_list), `todo` (Task Planning: todo), `memory` (memory), `context_engine` (Context Engine: no tools), `session_search`, `clarify` (Clarifying Questions), `delegation` (Task Delegation: delegate_task), `cronjob` (Cron Jobs: cronjob), `homeassistant` (ha_call_service, ha_get_state, ha_list_entities, ha_list_services), `spotify` (spotify_albums, spotify_devices, spotify_library, spotify_playback, spotify_playlists, spotify_queue, spotify_search), `discord` (platform Discord: discord), `discord_admin` (Discord Server Admin: discord_admin), `yuanbao` (yb_query_group_info, yb_query_group_members, yb_search_sticker, yb_send_dm, yb_send_sticker), `computer_use` (Computer Use (macOS/Windows/Linux): computer_use), `a2a` (a2a_call, a2a_discover, a2a_history, a2a_list, a2a_orchestrate).
- **Config / env:** `platform_toolsets.<platform>` (list of enabled toolsets per platform: `cli`, `discord`, …), `stt.enabled`.
- **Edge cases / guards:** `platform` differs for platform-restricted toolsets (Discord's persist to `platform_toolsets.discord`).
- **Rebuild notes:** Grid over a `{name,enabled,configured,tools}` list. Better: group by platform and show which model/provider is active inline.

### Toolset configuration drawer  `id: web-b.toolset-config-drawer`
- **Surface:** Web dashboard
- **Where:** Toolset card `Configure` → portal modal (`web/src/components/ToolsetConfigDrawer.tsx:37-460`): close icon `aria-label="Close"`; header = toolset label + badge `Active`/`Inactive`, description, `Switch aria-label="Enable toolset for <platform label>"` with caption `Enabled for <platform>` / `Disabled for <platform>`; body = provider matrix.
- **What it does:** The dashboard equivalent of `hermes tools`: toggle the toolset, pick its backend provider, enter API keys, run a provider's one-time install hook with a live log.
- **How it works:** `loadConfig` → `api.getToolsetConfig(name, profile)` = `GET /api/tools/toolsets/{name}/config?profile=` (`web_routers/tools.py:233-345`): for toolsets with a `TOOL_CATEGORIES` entry, rows from `_visible_providers(cat, config)` (static catalog in `hermes_cli/tools_config.py:305` merged with plugin-registered providers, e.g. `web-ddgs` registers `DuckDuckGo (ddgs)`), each `{name, badge, tag, env_vars[{key,prompt,url,default,is_set}], post_setup, requires_nous_auth, is_active, status (ready|needs_keys|needs_setup|needs_auth), web_backend?, capabilities?, tts_provider?}`; `active_provider` from `_is_provider_active`; for `web` also `active_search_backend`/`active_extract_backend`. Per-provider actions: `Select` → `PUT /api/tools/toolsets/{name}/provider` body `{provider, profile}` (`apply_provider_selection` writes e.g. `web.backend`, `tts.provider`, `image_gen.provider`; managed Nous rows may return `needs_nous_auth: true` — this SPA only toasts `Provider set to <p>`); `Save keys` → `PUT /api/tools/toolsets/{name}/env` body `{env:{KEY:value}, profile}` (`save_env_value` into the profile's `.env`; keys validated against the category's env-var allowlist → 400 `Unknown env var(s) for toolset <n>: …`; blanks skipped; returns `{saved[], skipped[], is_set{}}`); `Run setup` → `POST /api/tools/toolsets/{name}/post-setup` body `{key, profile}` (validated against `valid_post_setup_keys()` = `agent_browser, browser_use_cli, browserbase, camofox, cua_driver, ddgs, faster_whisper, kittentts, langfuse, lightpanda, piper, spotify, xai_grok`; spawns `hermes [-p profile] tools post-setup <key>` as action `tools-post-setup`), then polls `GET /api/actions/tools-post-setup/status?lines=300` every 1.2 s (first after 800 ms) until `running=false`, toasting `Post-setup complete` (exit 0) or `Post-setup finished with errors`, then reloads config and calls `onChanged` so the grid refreshes. Header switch → `PUT /api/tools/toolsets/{name}` body `{enabled, profile}` (own entry).
- **Inputs / options:** Header `Switch`; per provider: button `Select` (spinner while selecting; disabled while any selection in flight) or badge `✓ Selected`; badge text `provider.badge` (e.g. `★ recommended · free`, `subscription`, `paid`, `free · no key`); badge `Nous Portal` when `requires_nous_auth`; tag line; per env var: label `<KEY>` (mono), badge `Saved` when set, password `Input id="env-<KEY>"` placeholder `•••••••• (saved — leave blank to keep)` or the provider prompt, link `Get a key` (external, when `url`); button `Save keys` (spinner per provider); post-setup block text `This backend needs a one-time install (<key>). Runs on this host — may take a few minutes.` with button `Run setup` / `Installing…`; live log panel header `post-setup: <key>` and `<pre>` (`Starting…` until lines arrive). Body messages: `This toolset has no configurable backends — toggle it on or off above. It works with no provider selection or API keys.` (no category) and `No providers are available for this toolset in this install.` (empty provider list). Backdrop mouse-down closes.
- **Outputs / side effects:** Writes `config.yaml` (provider keys, `platform_toolsets`), `.env` (API keys), spawns installer subprocesses logging to `<HERMES_HOME>/logs/action-tools-post-setup.log`-style files. Toasts: `<label> enabled/disabled`, `Failed to toggle toolset`, `Provider set to <p>`, `Failed to select provider`, `Enter at least one value to save`, `Saved N key(s)` / `Nothing to save`, `Failed to save keys`, `Failed to start post-setup`, `Lost track of the post-setup process`, `Failed to load toolset config`.
- **Config / env:** `web.backend`, `web.search_backend`, `web.extract_backend`, `tts.provider`, `stt.provider`, `image_gen.provider`, `video_gen.provider`, `browser.*`, `platform_toolsets.*`; env vars per provider (below).
- **Edge cases / guards:** Live provider matrix (fetched from the running dashboard, `GET /api/tools/toolsets/<n>/config`): 
  - `web` (active search/extract = `parallel`): `Nous Subscription` (subscription; Nous Portal; firecrawl; search+extract), `Firecrawl Self-Hosted` (`FIRECRAWL_API_URL`), `Brave Search (Free)` (`BRAVE_SEARCH_API_KEY`, search only), `DuckDuckGo (ddgs)` (post-setup `ddgs`, search only), `Exa · Free (keyless)`, `Exa · Paid (API key)` (`EXA_API_KEY`), `Firecrawl` (`FIRECRAWL_API_KEY` optional), `Keenable · Free (keyless)`, `Keenable · Paid (API key)` (`KEENABLE_API_KEY`), `Parallel · Free (keyless)`, `Parallel · Paid (API key)` (`PARALLEL_API_KEY`), `SearXNG` (`SEARXNG_URL`, search only), `xAI Web Search (Grok)` (post-setup `xai_grok`, search only).
  - `browser` (active `Browser Use`): `Local Browser` (post-setup `agent_browser`), `Lightpanda` (`lightpanda`), `Nous Subscription (Browser Use cloud)` (Nous Portal; `browserbase`), `Camofox` (`CAMOFOX_URL`; `camofox`), `Browser Use` (`browser_use_cli`), `Browserbase` (`BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`), `Firecrawl` (`FIRECRAWL_API_KEY`).
  - `image_gen`: `Nous Subscription`, `DeepInfra` (`DEEPINFRA_API_KEY`), `FAL.ai` (`FAL_KEY`), `Krea` (`KREA_API_KEY`), `Nous Portal (image)`, `OpenAI` (`OPENAI_API_KEY`), `OpenAI (Codex auth)`, `OpenRouter (image)` (`OPENROUTER_API_KEY`), `xAI Grok Imagine (image)` (`xai_grok`).
  - `video_gen`: `Nous Subscription`, `DeepInfra` (`DEEPINFRA_API_KEY`), `FAL` (`FAL_KEY`), `xAI Grok Imagine` (`xai_grok`).
  - `x_search`: `xAI Grok OAuth (SuperGrok / Premium+)` (`xai_grok`), `xAI API key` (`XAI_API_KEY`).
  - `tts` (active `Microsoft Edge TTS`): `Microsoft Edge TTS`, `Nous Subscription`, `OpenAI TTS` (`VOICE_TOOLS_OPENAI_KEY`), `xAI TTS` (`xai_grok`), `ElevenLabs` (`ELEVENLABS_API_KEY`), `Mistral (Voxtral TTS)` (`MISTRAL_API_KEY`), `Google Gemini TTS` (`GEMINI_API_KEY`), `KittenTTS` (`kittentts`), `Piper` (`piper`), `DeepInfra TTS` (`DEEPINFRA_API_KEY`).
  - `stt` (active `Local Whisper`): `Local Whisper` (`faster_whisper`), `Nous Subscription`, `OpenAI` (`VOICE_TOOLS_OPENAI_KEY`), `Groq` (`GROQ_API_KEY`), `xAI` (`xai_grok`), `ElevenLabs Scribe` (`ELEVENLABS_API_KEY`), `DeepInfra` (`DEEPINFRA_API_KEY`).
  - `homeassistant`: `Home Assistant` (`HASS_TOKEN` "Home Assistant Long-Lived Access Token", `HASS_URL`).
  - `spotify`: `Spotify Web API` (post-setup `spotify`, PKCE wizard).
  - `computer_use`: `cua-driver (background)` (post-setup `cua_driver`).
  - `langfuse` category exists in `TOOL_CATEGORIES` (`Langfuse Cloud`, `Langfuse Self-Hosted`: `HERMES_LANGFUSE_PUBLIC_KEY`, `HERMES_LANGFUSE_SECRET_KEY`, `HERMES_LANGFUSE_BASE_URL`, post-setup `langfuse`) but is not among the 27 toolset rows.
  - All other toolsets (`terminal, file, code_execution, vision, video, skills, todo, memory, context_engine, session_search, clarify, delegation, cronjob, discord, discord_admin, yuanbao, a2a`) return `has_category: false`.
  The SPA does not use the per-capability `capability: search|extract` selection nor the `GET/PUT /api/tools/toolsets/{name}/models|model` catalog endpoints (`web_routers/tools.py:348-463`, image/video model picker) — those are desktop-only at this version.
- **Rebuild notes:** Provider rows = data; three PUTs and one spawn-and-poll. Better: react to `needs_nous_auth` by launching the Nous Portal OAuth flow, expose search/extract split and model catalogs.

### Toggle toolset  `id: web-b.toolset-toggle`
- **Surface:** Web dashboard
- **Where:** Toolset drawer header `Switch` (`aria-label="Enable toolset for <platform>"`).
- **What it does:** Adds/removes the toolset from the platform's enabled set, persisting to config.
- **How it works:** `PUT /api/tools/toolsets/{name}` body `ToolsetToggle {enabled, profile?}` (`web_routers/tools.py:128-230`): 400 `Unknown toolset: <n>`; config-only (`stt`) writes `stt.enabled`; others read `_get_platform_tools`, add/discard, `_save_platform_tools(config, platform, enabled)`. Install-on-enable: if enabling and a visible provider has a `post_setup` key whose install predicate (`_POST_SETUP_INSTALLED`) is unsatisfied, spawns `hermes tools post-setup <key>` as `tools-post-setup` and reports `post_setup_started`.
- **Inputs / options:** switch.
- **Outputs / side effects:** `{"ok","name","platform","enabled","post_setup_started"}`; toast `<label> enabled|disabled`; grid refresh.
- **Config / env:** `platform_toolsets.<platform>`, `stt.enabled`.
- **Edge cases / guards:** Spawn failure never fails the toggle.
- **Rebuild notes:** Set membership write + best-effort installer kick.

### Browse hub view  `id: web-b.skills-hub-browser`
- **Surface:** Web dashboard
- **Where:** `/skills` → `Browse hub` → `HubBrowser` (SkillsPage.tsx:858-1161): search card with `Input` placeholder `Search the skill hub (GitHub, official, community)…`, button `Search` (search icon / spinner; disabled when empty or searching), button `Update all` (refresh icon); `ConnectedHubs` strip; optional action-log card; landing section `Featured skills` `from the Hermes index — search above for thousands more` or card `Search the hub above to browse installable skills from the connected sources.`; results with `SearchMeta`; empty result card `No matching skills found in the hub.`
- **What it does:** Searches all configured skill-hub sources, shows featured skills, previews and security-scans a skill, installs it into the profile, and updates all hub-installed skills.
- **How it works:** On mount `api.getSkillHubSources(profile)` = `GET /api/skills/hub/sources?profile=` (`web_routers/skills.py:114-184`): builds `tools.skills_hub.create_source_router()` inside `_config_profile_scope`, returns `{sources:[{id,label,rate_limited?,available?,searchable}], index_available, featured (index search("" , limit 12) when index available), installed{identifier→{name,trust_level,scan_verdict}}}`; labels from `_SKILL_HUB_SOURCE_LABELS` (web_server.py:14860: `official→Official (Nous)`, `hermes-index→Hermes Index`, `skills-sh→skills.sh`, `well-known→Well-Known`, `url→Direct URL`, `github→GitHub`, `clawhub→ClawHub`, `lobehub→LobeHub`, `browse-sh→browse.sh`). Search (Enter or button) → `api.searchSkillsHub(q, "all", 20, profile)` = `GET /api/skills/hub/search?q=&source=all&limit=20&profile=` (`:187-235`): `parallel_search_sources(sources, query, source_filter, overall_timeout=30)`, dedupe by identifier preferring trust rank `builtin(2) > trusted(1) > community(0)`, cap `limit` 1–50; returns `{results[], source_counts{}, timed_out[], installed{}}`; client measures elapsed ms. `ConnectedHubs` (:1164-1214): `Connecting to skill hubs…` while loading; with no sources `Results come from the same sources as hermes skills search.`; else `Connected hubs:` + one badge per source (`<label>` + ` (rate-limited)` for GitHub; dimmed with titles `GitHub API rate-limited — set GITHUB_TOKEN to raise the limit` / `Centralized index unavailable — falling back to live sources`). `SearchMeta` (:1217-1252): badge `N result(s)`, `X.Xs`, per-source `id:n` counts, amber `a, b timed out`.
- **Inputs / options:** search input (Enter submits), `Search`, `Update all`, result cards (own entry), detail dialog (own entry), action-log `Dismiss` button.
- **Outputs / side effects:** none until install/update. Live: 9 sources (`Official (Nous)`, `Hermes Index` (available:false), `skills.sh`, `Well-Known`, `Direct URL`, `GitHub`, `ClawHub`, `LobeHub`, `browse.sh`), `index_available:false`, no featured (`api_live/get_all.json["/api/skills/hub/sources"]`).
- **Config / env:** `GITHUB_TOKEN` (raises GitHub rate limits), skills-hub source config (`skills.hub.*`, taps) per profile.
- **Edge cases / guards:** 502 `Hub search failed: …` / `Hub sources failed: …` on exceptions; toast `Hub search failed: <e>`. `searchable` flag is returned but not used by this SPA (desktop does per-source fan-out).
- **Rebuild notes:** Fan-out search across pluggable sources with trust-ranked dedupe. Better: per-source filter chips, pagination, and using `searchable` to avoid redundant API sources.

### Hub result card  `id: web-b.skills-hub-result-card`
- **Surface:** Web dashboard
- **Where:** Browse hub → each `HubResultCard` (SkillsPage.tsx:1255-1335): clickable body (`aria-label="Open <name>"`) with name, trust badge (`trusted` success / `builtin` secondary / `community` warning / other outline, `trustVisual` :817-831), source badge, `installed` badge, description (2 lines), up to 5 tag chips, identifier line; right column buttons `Details` (file icon) and `Install` (download icon) or disabled `Installed` (check icon).
- **What it does:** Summarises one hub skill and offers preview or one-click install.
- **How it works:** `installed` = `installed[identifier]` map presence. `onOpen` sets `detail`; `onInstall` calls the install action (own entry).
- **Inputs / options:** body click, `Details`, `Install`.
- **Outputs / side effects:** none directly.
- **Config / env:** n/a.
- **Edge cases / guards:** Same card used for featured and search results.
- **Rebuild notes:** Presentational.

### Hub skill detail dialog (preview + security scan)  `id: web-b.skills-hub-detail`
- **Surface:** Web dashboard
- **Where:** Result card `Details` (or body click) → `SkillDetailDialog` (SkillsPage.tsx:1338-1516): title = package icon + name + trust/source/`installed` badges; sr-only description `Preview the SKILL.md source and run a security scan for <name> before installing.`; description + identifier; action row buttons `Read SKILL.md`, `Security scan` / `Re-scan` (shield / spinner), right side link `<owner/repo>` (external, when `repo`) and `Install` / `Installed`; body (max 55vh) = readme tab or `ScanPanel`.
- **What it does:** Lets the user read the actual SKILL.md and file manifest, and run the installer's security scan, before installing.
- **How it works:** On open `api.previewSkillFromHub(identifier)` = `GET /api/skills/hub/preview?identifier=` (`web_routers/skills.py:238-300`: `_resolve_source_meta_and_bundle` across sources, decodes bundle files as UTF-8 (`(binary file)` fallback), returns `{name, description, source, identifier, trust_level, repo, tags[], skill_md, files[]}`; 404 `Skill not found: <id>`; 502 `Hub preview failed: …`). Readme tab shows tag chips, `Files: <a  b  c>` and `<pre>` of `skill_md` or `(SKILL.md is empty)`; failure text `Couldn't load the skill source.`; toast `Preview failed: <e>`. `Security scan` → `api.scanSkillFromHub(identifier)` = `GET /api/skills/hub/scan?identifier=` (`:303-427`): fetches bundle, `quarantine_bundle`, `tools.skills_guard.scan_skill(q_path, source)` (+ optional SkillEvaluator Tier-1 advisory when `tier1_advisory_enabled()`), `should_allow_install(result, force=False)` → `policy` `allow|ask|block`; cleans quarantine; returns `{name, identifier, source, trust_level, verdict, summary, policy, policy_reason, findings[{severity,category,file,line,description}], severity_counts{critical,high,medium,low}, tier1}`; toast `Scan failed: <e>`.
- **Inputs / options:** `Read SKILL.md` tab button; `Security scan`/`Re-scan` (disabled while scanning); repo link; `Install`; dialog close (overlay/Escape via `Dialog onOpenChange`).
- **Outputs / side effects:** `ScanPanel` (:1519-1634): spinner text `Fetching, quarantining, and scanning…`; placeholder `Run a security scan to inspect this skill for risky patterns before installing.`; verdict header `Verdict: Safe|Caution|Dangerous` (icons ShieldCheck/ShieldAlert; colours emerald/amber/red) + verdict badge, `<trust_level> source · N finding(s)`, policy badge `Install allowed` (allow) / `Needs confirmation` (ask) / `Install blocked` (block); severity tally badges `N critical|high|medium|low` (tones destructive/destructive/warning/secondary) or `No risky patterns detected`; `policy_reason` text; findings list rows `<severity> <category> <file>:<line> <description>`.
- **Config / env:** `skills.hub.*` trust/scan policy config; `GITHUB_TOKEN`.
- **Edge cases / guards:** `tier1` block is returned by the API but not rendered by this SPA. Scan never installs; quarantine dir removed in `finally`.
- **Rebuild notes:** Two GETs (preview, scan) over the same bundle resolver as the CLI installer. Better: render markdown, show Tier-1 findings, diff against installed version.

### Install skill from hub / action log  `id: web-b.skills-hub-install`
- **Surface:** Web dashboard
- **Where:** Result card or detail dialog `Install`; progress card with download icon, action name (mono), badge `running` (warning) / `done` (success), `Dismiss` icon button (after completion) and a `<pre>` log (`Starting…` until lines arrive).
- **What it does:** Installs a hub skill into the selected profile by spawning the CLI installer non-interactively and tailing its log.
- **How it works:** `install(identifier)` (SkillsPage.tsx:967-981) → `api.installSkillFromHub(identifier, profile)` = `POST /api/skills/hub/install` body `SkillInstallRequest {identifier, profile?}` (`web_routers/skills.py:58-75`): 400 `identifier is required`; action name from `_hub_action_name("install", identifier)` (web_server.py:14825-14835: `skills-install-<slug≤48>-<sha1[:8]>`, log file `action-<name>.log`); `_spawn_hermes_action(_profile_cli_args(profile) + ["skills","install",identifier,"--yes"], name)` (web_server.py:4710-4760: runs `<venv python> -m hermes_cli.main …` detached, `HERMES_NONINTERACTIVE=1`, `_HERMES_GATEWAY` stripped, stdout+stderr appended to `<action log dir>/<file>` with a `=== <name> started <ts> ===` marker; `-p <profile>` only for non-default profiles :14808-14822); returns `{ok, pid, name}`; 500 `Failed to install skill: …`. The page then polls `api.getActionStatus(name, 200)` = `GET /api/actions/{name}/status?lines=200` (web_server.py:5814: 404 `Unknown action`, tails ≤2000 lines, `{exit_code, lines[], name, pid, running}`) every 1.2 s; when finished, re-fetches hub sources to refresh `installed` badges.
- **Inputs / options:** `Install` buttons; `Dismiss`.
- **Outputs / side effects:** Skill files under `<profile>/skills/…` + lock entry in `skills/.hub/lock.json`; toast `Installing <identifier>…` (success) or `Install failed: <e>`; detail dialog closed.
- **Config / env:** `HERMES_HOME`, profile.
- **Edge cases / guards:** `--yes` skips interactive confirmations — the scan policy `ask` verdicts are therefore auto-accepted by the CLI's non-interactive rules (see CLI shard); one log/process per identifier so parallel installs don't clobber each other.
- **Rebuild notes:** Spawn-and-poll pattern reused by post-setup and MCP git installs. Better: stream via SSE and surface the scan verdict inline before spawning.

### Update all hub skills  `id: web-b.skills-hub-update-all`
- **Surface:** Web dashboard
- **Where:** Browse hub search card → button `Update all`.
- **What it does:** Runs `hermes skills update` for the profile to refresh every hub-installed skill.
- **How it works:** `api.updateSkillsFromHub(profile)` = `POST /api/skills/hub/update` body `{profile?}` (`web_routers/skills.py:97-111`) → `_spawn_hermes_action(args + ["skills","update"], "skills-update")`; polled like installs; toast `Updating installed skills…` / `Update failed: <e>`.
- **Inputs / options:** button.
- **Outputs / side effects:** Updated skill dirs; log card named `skills-update`.
- **Config / env:** n/a.
- **Edge cases / guards:** Shared action name `skills-update` (a second click overwrites tracking of the first).
- **Rebuild notes:** Same spawn/poll pattern.

### Hub uninstall endpoint (API-only in SPA)  `id: web-b.skills-hub-uninstall-api`
- **Surface:** API
- **Where:** `POST /api/skills/hub/uninstall` body `{name, profile?}` (`web_routers/skills.py:78-94`).
- **What it does:** Spawns `hermes skills uninstall <name> --yes` as action `skills-uninstall-<slug>-<hash>`.
- **How it works:** identical spawn pattern; 400 `name is required`; 500 `Failed to uninstall skill: …`. `api.uninstallSkillFromHub` exists in `api.ts:1308` but no button on this page calls it (desktop uses it).
- **Inputs / options:** as above.
- **Outputs / side effects:** `{ok,pid,name}`.
- **Config / env:** n/a.
- **Edge cases / guards:** none.
- **Rebuild notes:** n/a.

### Skills page catalog-only string (unused i18n key)  `id: web-b.skills-unused-strings`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts:425` — `skills.searchPlaceholder` = `Search skills and toolsets...` is defined but `SkillsPage.tsx:331` uses `common.search` (`Search...`) for the header search input instead.
- **What it does:** Legacy placeholder for the former in-page search box.
- **How it works:** Kept for locale type parity (`web/src/i18n/types.ts`).
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Use the more descriptive placeholder when rebuilding — the search box does filter both skills and toolsets.

---

## 4. Plugins page (`/plugins`)

### Plugins page shell  `id: web-b.plugins-page`
- **Surface:** Web dashboard
- **Where:** Sidebar `PLUGINS` → `/plugins`; H1 `Plugins`. Header after-title icon button `aria-label="Rescan dashboard extensions"` (`i18n: pluginsPage.refreshDashboard`, RefreshCw icon / spinner). Four vertical sections: card `Runtime provider plugins` (`pluginsPage.providersHeading`), card `Install from GitHub / Git URL` (`pluginsPage.installHeading`), heading `Installed plugins` (`pluginsPage.pluginListHeading`), heading `Dashboard-only extensions (no agent plugin.yaml match)` (`pluginsPage.orphanHeading`). Plugin slots `plugins:top`, `plugins:bottom`. Page headline string `Discover, install, enable, and update Hermes plugins (\`hermes plugins\` parity).` (`pluginsPage.headline`) exists in the catalog for the page description.
- **What it does:** Manages agent (YAML) plugins: install from git, enable/disable at runtime, update, remove, hide dashboard tabs; and selects the memory provider and context engine plugins.
- **How it works:** `web/src/pages/PluginsPage.tsx:281-912`. `loadHub` → `api.getPluginsHub()` = `GET /api/dashboard/plugins/hub` (session-token protected, `_require_token`; web_server.py:18837-18845) → `_merged_plugins_hub()` (:18660-18834, memoised 5 s `_PLUGINS_HUB_CACHE_TTL_SECONDS`): iterates `hermes_cli.plugins_cmd._discover_all_plugins()` (bundled `<repo>/plugins/**`, user `~/.hermes/plugins/**`), computes `runtime_status` = `disabled` (in `plugins.disabled`) | `enabled` (in `plugins.enabled`) | `inactive`, `has_dashboard_manifest` (`dashboard/manifest.json`), `can_remove`/`can_update_git` (source `user|git` under `~/.hermes/plugins`, `.git` present), `auth_required`/`auth_command` (`hermes auth <name>` when a provided tool's cached `check_fn` verdict is False; cold caches trigger a background probe), `user_hidden` (`dashboard.hidden_plugins`); plus `orphan_dashboard_plugins` (dashboard manifests without an agent plugin) and `providers {memory_provider, memory_options[], context_engine, context_options[]}`. Rescan → `api.rescanPlugins()` = `GET /api/dashboard/plugins/rescan` (:18619-18623, forces `_discover_dashboard_plugins`) then `loadHub`; toast `Rescan dashboard extensions (<count>)`.
- **Inputs / options:** header rescan button; everything in the entries below.
- **Outputs / side effects:** Toast `Loading...` on hub load failure; `Rescan failed`.
- **Config / env:** `plugins.enabled`, `plugins.disabled`, `dashboard.hidden_plugins`, `memory.provider`, `context.engine` (all in `config.yaml`); `HERMES_ENABLE_PROJECT_PLUGINS` (adds `./.hermes/plugins` as a dashboard-plugin source).
- **Edge cases / guards:** Hub route rejects with 500 `Failed to build plugins hub.` on error. Live: 54 bundled plugins, all `inactive`, 2 orphan dashboard extensions (`hermes-achievements` → `/achievements`, `kanban` → `/kanban`).
- **Rebuild notes:** One aggregated GET + 8 mutation routes. Better: search/filter for the 54-row list, group by category (platforms, image_gen, web…), install progress log.

### Runtime provider plugins — Memory provider  `id: web-b.plugins-memory-provider`
- **Surface:** Web dashboard
- **Where:** `/plugins` → card `Runtime provider plugins`, subtitle `Configure memory providers and runtime context engine selection.`; left column label `Memory provider` (`pluginsPage.memoryProviderLabel`, `id="mem-provider"`) with status badges and a `Select`; provider hints, dynamic settings form, button `Save memory provider`.
- **What it does:** Chooses which memory plugin backs the agent's long-term memory (or the built-in MEMORY.md/USER.md files), configures its settings/secrets, and can install its dependencies.
- **How it works:** PluginsPage.tsx:289-480, 537-732. Select value `__hermes_memory_builtin__` (`MEMORY_PROVIDER_BUILTIN`, never `""`) means built-in; options = `providers.memory_options[].name`. Badges next to the label: provider status badge (`ready→"ready"`, `needs_config→"needs setup"`, `unavailable→"unavailable"`, `missing→"missing"`; tones success/warning/destructive/destructive, `MEMORY_STATUS_LABEL/TONE` :37-49), `active` (outline) when the selection equals `providers.memory_provider`, `active` (success) when built-in is both selected and active. Selecting a provider loads `api.getMemoryProviderConfig(name)` = `GET /api/memory/providers/{name}/config` (web_server.py:7176-7196; `{name,label,fields[],setup}`) and seeds `memoryValues` (secrets blank, booleans coerced, others stringified; `fieldInitialValue` :51-55). `fieldIsVisible` (:57-63) hides fields whose `when` map doesn't match current values. Save (`onSaveMemoryProvider` :426-448): built-in → `api.setMemoryProvider("")` = `PUT /api/memory/provider` body `{provider:""}`; else `api.updateMemoryProviderConfig(name, visibleValues)` = `PUT /api/memory/providers/{name}/config` body `{values}` (web_server.py:7221-7250: `_write_memory_provider_config_values` writes non-secret fields to config and secrets to `.env`, then `_require_memory_provider_ready(name)` → 400 `Memory provider '<n>' is not ready (<status>). Configure it in the dashboard first.`, then sets `memory.provider = name`). Toast `Provider settings saved.` (`pluginsPage.savedProviders`) or `Save failed`.
- **Inputs / options:** `Select` `(built-in / default)` (`pluginsPage.providerDefaults`) + provider names (live: `byterover`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory`); text/hints: `Hermes will use the built-in MEMORY.md and USER.md files.` (built-in selected); `Active provider <name> is no longer installed. Select another provider and save.` (status `missing`); provider `description`; `Provider dependencies are installed. Add the required credentials or self-hosted URL below, then save the provider.` (status `needs_config`); `Loading provider settings…`; `This provider does not expose dashboard settings.`; settings form (own entry); setup hint (own entry); button `Save memory provider` (disabled while saving/loading/setup running).
- **Outputs / side effects:** `config.yaml` `memory.provider` + provider-specific keys, `.env` secrets; `_invalidate_plugins_hub_cache()`; hub reload.
- **Config / env:** `memory.provider` (`""` = built-in), `memory.<provider>.*`; provider-declared env vars (e.g. `RETAINDB_API_KEY`).
- **Edge cases / guards:** Live statuses: `holographic` ready (local SQLite FTS5/HRR); `openviking`, `retaindb` needs_config; `byterover` (needs `brv` CLI: `curl -fsSL https://byterover.dev/install.sh | sh`, check `brv --version`), `hindsight` (pip `hindsight-client>=0.6.1`), `honcho` (pip `honcho-ai`), `mem0` (pip `mem0ai>=2.0.10,<3`), `supermemory` (pip `supermemory`) unavailable until dependencies are installed. Providers discovered by `plugins.memory.discover_memory_providers()`; a configured-but-missing provider is synthesised with description `Configured provider was not found.` (web_server.py:7069-7075).
- **Rebuild notes:** Provider registry with `{status, setup, fields}` schema; a generic form renderer; ready-gate before activation. Better: test-connection button per provider and migration of existing memories between providers.

### Memory provider settings form fields  `id: web-b.plugins-memory-provider-fields`
- **Surface:** Web dashboard
- **Where:** Memory provider section → bordered form (`PluginsPage.tsx:616-721`) with one control per visible `MemoryProviderField`.
- **What it does:** Renders provider-declared configuration fields generically.
- **How it works:** Field schema (`api.ts:1726-1741`): `{key, label, kind: text|secret|select|boolean|integer|number, description, placeholder, required, value, is_set, options[{value,label,description?}], url, minimum?, maximum?, step?, when?}`. Per field: `Label htmlFor="memory-<key>"`, badge `required`, badge `set` (secret already stored and input blank), link `Open ↗` (when `url`); control: `select` → `Select` of options; `boolean` → `Switch`; else `Input` typed `password` (secret hidden) / `number` (integer|number, with min/max/step, integer step defaults 1) / `text`, placeholder `Leave blank to keep existing value` for set secrets else `field.placeholder`; secrets get an eye toggle button `aria-label="Show secret"` / `"Hide secret"`; `description` under the control.
- **Inputs / options:** as above, dynamic.
- **Outputs / side effects:** values submitted with `Save memory provider` / `Install provider dependencies` (only visible fields are sent).
- **Config / env:** provider-specific.
- **Edge cases / guards:** Secret visibility state resets on provider change.
- **Rebuild notes:** Schema-driven form; better: inline validation from `required`.

### Memory provider dependency setup hint  `id: web-b.plugins-memory-provider-setup`
- **Surface:** Web dashboard
- **Where:** Memory provider section → `MemoryProviderSetupHint` (PluginsPage.tsx:152-279) shown when the provider needs dependency setup, is unavailable with details, or after a setup run.
- **What it does:** Explains and runs the provider's declared setup (pip dependencies, external CLIs, required env vars) and shows per-step results.
- **How it works:** Uses `provider.setup` = `{pip_dependencies[], external_dependencies[{name,install,check}], required_env[], dependencies_installed}`. `Install provider dependencies` → `api.setupMemoryProvider(name, visibleValues)` = `POST /api/memory/providers/{name}/setup` body `{values}` (web_server.py:7199-7218: persists submitted values first, then `_install_memory_provider_setup(name)` runs pip installs / external install commands; 404 `Unknown memory provider: <n>`) → `{ok, provider, results[{kind,name,status,command,returncode,stdout,stderr}], status?}`; toast `Provider setup finished` or `Provider setup failed: <names>. See setup results below.`; hub reloaded keeping the selection.
- **Inputs / options:** button `Install provider dependencies` / `Installing provider dependencies` (spinner); copy buttons (`CopyButton`) on each `SetupCommandBlock` (`Install <dep>` / `Install dependency`, `Verify <dep>` / `Verify dependency`).
- **Outputs / side effects:** Texts: `This provider is installed but unavailable. It may need local dependencies or a manual setup step before Hermes can activate it.` (no details); `Finish these setup steps before Hermes can activate this provider.` / `Provider dependency setup completed.`; `Running provider setup. This may take a minute…`; `Setup results` list with status chips (`already installed`, `no declared setup`, else status with underscores → spaces; classes success for `installed|verified|already_installed`, destructive for `failed`, warning for `missing`), `<name> (<kind>)`, command and stdout/stderr `<pre>`; sections `External dependency: <name>`, `Python dependencies` (chips), `Required environment values. Fill the matching fields below, or set them in the Hermes environment.` (chips of env names).
- **Config / env:** provider manifest `setup` block.
- **Edge cases / guards:** `isBlocked` (unavailable + needs setup) renders the box in destructive colour.
- **Rebuild notes:** Manifest-declared setup steps executed server-side with structured results.

### Runtime provider plugins — Context engine  `id: web-b.plugins-context-engine`
- **Surface:** Web dashboard
- **Where:** `Runtime provider plugins` card → right column label `Context engine` (`pluginsPage.contextEngineLabel`, `id="ctx-engine"`) `Select` + button `Save context engine`.
- **What it does:** Chooses the context-management engine plugin (default `compressor`).
- **How it works:** Options = `compressor` + `providers.context_options` (from `_discover_context_engines()`, live: none extra). Save → `api.savePluginProviders({context_engine})` = `PUT /api/dashboard/plugin-providers` (web_server.py:18932-18952) → `_save_context_engine` writes `context.engine` (`plugins_cmd.py:2095-2102`). The same route accepts `memory_provider` (gated by `_require_memory_provider_ready`), but the SPA's memory path uses `/api/memory/...` instead.
- **Inputs / options:** select; `Save context engine` (spinner).
- **Outputs / side effects:** Toast `Provider settings saved.` / `Save failed`; hint text `Writes memory.provider (empty = built-in) and context.engine to config.yaml. Takes effect next session.` (`pluginsPage.providersHint`) is in the catalog.
- **Config / env:** `context.engine`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Single config key.

### Install plugin from GitHub / Git URL  `id: web-b.plugins-install`
- **Surface:** Web dashboard
- **Where:** `/plugins` → card `Install from GitHub / Git URL` (rendered uppercase by CSS: `INSTALL FROM GITHUB / GIT URL`; label rendered `GIT URL OR OWNER/REPO`), subtitle `Use owner/repo shorthand or a full https:// or git@ clone URL. For a plugin in a subdirectory, append the path: owner/repo/path/to/plugin (or <url>#path/to/plugin).` (`pluginsPage.installHint`); label `Git URL or owner/repo` (`pluginsPage.identifierLabel`, `id="install-url"`).
- **What it does:** Clones a plugin repository into `~/.hermes/plugins/<name>` (security-scanned) and optionally enables it.
- **How it works:** `onInstall` (PluginsPage.tsx:368-392): empty id → toast of `installHint`; `api.installAgentPlugin({identifier, force, enable})` = `POST /api/dashboard/agent-plugins/install` (web_server.py:18848-18866) → `plugins_cmd.dashboard_install_plugin` (`hermes_cli/plugins_cmd.py:2639-2705`): `_resolve_git_url` (warning `Insecure URL scheme; prefer https:// or git@ for production installs.` for http/file), `_install_plugin_core(identifier, force)`; `PluginScanBlocked` → `{ok:false, error, scan_blocked:true, scan_verdict, scan_findings[]}`; `PluginOperationError` → error; on `enable` adds to `plugins.enabled` and removes from `plugins.disabled`; returns `{ok, plugin_name, warnings[], missing_env[], enabled, after_install_path}`; route 400 with `error` when not ok, then rescans dashboard plugins and invalidates the hub cache.
- **Inputs / options:** `Input id="install-url"` placeholder `owner/repo, owner/repo/subdir, or https://...` (mono, lowercase, spellcheck off); `Switch` `Force reinstall (delete existing folder first)` (`pluginsPage.forceReinstall`, default off); `Switch` `Enable after install` (`pluginsPage.enableAfterInstall`, default on); button `Install` (`pluginsPage.installBtn`, spinner while busy). Hint lines `Rescan after adding files on disk so the dashboard sidebar picks up new manifests.` (`pluginsPage.rescanHint`) and `Only user-installed plugins under ~/.hermes/plugins can be removed.` (`pluginsPage.removeHint`).
- **Outputs / side effects:** Toasts `<plugin_name> installed`, warnings joined (error tone), `Set these in Keys before the plugin can run: <ENV, ENV>` (`pluginsPage.missingEnvWarn`), or `Install failed` / server error message; input cleared; hub reload.
- **Config / env:** `plugins.enabled`, `plugins.disabled`; install root `~/.hermes/plugins`.
- **Edge cases / guards:** Scan-blocked installs surface only the error text in this SPA (findings ignored). Identifier forms: `owner/repo`, `owner/repo/sub/dir`, `https://…`, `git@…`, `<url>#sub/dir`.
- **Rebuild notes:** git clone + manifest read + scan + allow-list write. Better: show scan findings and `after-install.md` contents in a dialog.

### Installed plugins list and row actions  `id: web-b.plugins-installed-list`
- **Surface:** Web dashboard
- **Where:** `/plugins` → heading `Installed plugins` → one `PluginRowCard` per plugin (PluginsPage.tsx:927-1124): name (bold), badge `Source: <source>` (`pluginsPage.sourceBadge`), badge `v<version>` (or `v—`), badge runtime status (`enabled` success / `disabled` destructive / `inactive` outline), badge `Auth required` (`pluginsPage.authRequired`, destructive); action buttons; description; `Dashboard slots: <a, b>` (`pluginsPage.dashboardSlots`) when the dashboard manifest declares slots; `CommandBlock` labelled `Run this command to authenticate:` (`pluginsPage.authRequiredHint`) with `hermes auth <name>` and a `Copy` button when auth is required; italic `No dashboard tab` (`pluginsPage.noDashboardTab`) when there is no dashboard manifest. Empty list: `No results` (`common.noResults`); loading: spinner + `Loading...`.
- **What it does:** Shows every discovered agent plugin (bundled and user) with its state and lets the user enable/disable, open its dashboard tab, git-pull, hide/show its sidebar tab, or remove it.
- **How it works:** Row actions all go through `setRuntimeLoading(name, fn)` (:495-505) which marks the row busy (`opacity-70`), awaits the call, reloads the hub, toasts `Failed`/message on error. Buttons:
  - `Enable` (`pluginsPage.enableRuntime`) / `Disable` (`pluginsPage.disableRuntime`) → `POST /api/dashboard/agent-plugins/{name}/enable|disable` (web_server.py:18878-18901) → `plugins_cmd.dashboard_set_agent_plugin_enabled(name, enabled)` (moves the name between `plugins.enabled`/`plugins.disabled`; returns `{ok, name, unchanged?}`); toast `Enable`/`Disable`.
  - `Open` (`pluginsPage.openTab`) — a `Link` to the dashboard manifest's tab path (`tab.override ?? tab.path`, hidden tabs excluded).
  - `Git pull` (`pluginsPage.updateGit`, only when `can_update_git`) → `POST /api/dashboard/agent-plugins/{name}/update` → `dashboard_update_user_plugin` (`{ok, name, output, unchanged?}`); toast `Git pull`.
  - `Show in sidebar` / `Hide from sidebar` (`pluginsPage.showInSidebar/hideFromSidebar`, eye icons; only when `has_dashboard_manifest`) → `POST /api/dashboard/plugins/{name}/visibility` body `{hidden}` (web_server.py:18955-18980; edits `dashboard.hidden_plugins` list).
  - Trash icon (destructive ghost; only when `can_remove`) → `ConfirmDialog` title `Remove this plugin from ~/.hermes/plugins/?` (`pluginsPage.removeConfirm`), description `This will remove the "<name>" plugin from your agent.`, confirm label `Delete` (`common.delete`) → `DELETE /api/dashboard/agent-plugins/{name}` → `dashboard_remove_user_plugin`; toast `<name> removed`.
  Plugin names may contain `/` (nested category plugins) — `pluginPath()` in `api.ts` encodes segments and routes use `{name:path}` (literal FastAPI paths: `POST /api/dashboard/agent-plugins/install`, `POST /api/dashboard/agent-plugins/{name:path}/enable`, `POST /api/dashboard/agent-plugins/{name:path}/disable`, `POST /api/dashboard/agent-plugins/{name:path}/update`, `DELETE /api/dashboard/agent-plugins/{name:path}`, `PUT /api/dashboard/plugin-providers`, `POST /api/dashboard/plugins/{name:path}/visibility`, `GET /dashboard-plugins/{plugin_name}/{file_path:path}`); `_validate_plugin_name` rejects `..` and `\`. Server-side error texts: `Plugin '<n>' is not installed or bundled.`, `Bundled plugins cannot be removed from the dashboard.`, `Plugin '<n>' was not found under <plugins_dir>.`, `Could not remove plugin '<n>': <exc>`, `Plugin '<n>' is not a git checkout; cannot pull updates.` (`hermes_cli/plugins_cmd.py:2793-3050`).
- **Inputs / options:** per-row buttons above; confirm dialog `Cancel`/`Delete`.
- **Outputs / side effects:** `config.yaml` (`plugins.enabled`, `plugins.disabled`, `dashboard.hidden_plugins`), `~/.hermes/plugins/<name>` removed on delete; hub cache invalidated; dashboard plugin rescan after update/remove.
- **Config / env:** as above.
- **Edge cases / guards:** Bundled plugins cannot be removed or git-pulled (`can_remove`/`can_update_git` false). Live inventory (54, all bundled/inactive; `api_live/get_all.json["/api/dashboard/plugins/hub"]`): browser backends `browser-browser-use`, `browser-browserbase`, `browser-firecrawl`; cron provider `chronos`; dashboard auth `basic`, `drain`, `nous`, `self-hosted`; `disk-cleanup` (v2.0.0); `google_meet` (0.2.0); image_gen `deepinfra`, `fal`, `krea` (1.1.0), `openai`, `openai-codex`, `openrouter` (1.1.0), `xai`; `langfuse`; platform adapters `a2a-platform` (auth required → `hermes auth a2a-platform`), `buzz-platform`, `dingtalk-platform`, `discord-platform`, `email-platform`, `feishu-platform`, `google_chat-platform`, `homeassistant-platform`, `irc-platform`, `line-platform`, `matrix-platform`, `mattermost-platform`, `ntfy-platform`, `photon-platform` (0.3.0), `raft-platform`, `simplex-platform` (1.1.0), `slack-platform`, `sms-platform`, `teams-platform`, `telegram-platform`, `wecom-platform`, `whatsapp-platform`; `security-guidance` (0.1.0); `spotify` (auth required → `hermes auth spotify`); `teams_pipeline` (0.1.0); video_gen `deepinfra`, `fal`, `xai`; web providers `web-brave-free`, `web-ddgs`, `web-exa`, `web-firecrawl`, `web-keenable`, `web-parallel`, `web-searxng`, `web-xai`. Note duplicate display names (`deepinfra`, `fal`, `xai` appear for both image_gen and video_gen) — rows are keyed by `name`, so React keys collide for these.
- **Rebuild notes:** List + 5 mutations against config allow/deny lists. Better: key rows by path, show category, filter/search, and surface `after-install.md`.

### Dashboard-only extensions (orphans)  `id: web-b.plugins-orphans`
- **Surface:** Web dashboard
- **Where:** `/plugins` → heading `Dashboard-only extensions (no agent plugin.yaml match)` → list items `<label|name> — <description|tab.path>` with link `Open` (`pluginsPage.openTab`, external-link icon) when the tab is not hidden (PluginsPage.tsx:871-905).
- **What it does:** Lists dashboard SPA extensions (plugins with `dashboard/manifest.json` but no matching agent plugin) so users can open their tabs.
- **How it works:** `hub.orphan_dashboard_plugins` = manifests from `_discover_dashboard_plugins()` (web_server.py:18434-18560: scans `<launch HERMES_HOME>/plugins`, `<root>/plugins`, bundled `plugins/memory`, bundled `plugins/`, and `./.hermes/plugins` when `HERMES_ENABLE_PROJECT_PLUGINS` is truthy; manifest fields `name, label, description, icon, version, tab{path, position, override?, hidden?}, slots[], entry, css, has_api, source`) whose name is not an agent plugin. Assets are served by `GET /dashboard-plugins/{plugin_name}/{file_path}` (:18983-19060; only `dashboard/` files with a browser-asset suffix allowlist `.js .mjs .css .json .html .svg .png .jpg .jpeg .gif .webp .ico .woff2 .woff .ttf .otf .map`; user plugins must be in `plugins.enabled`; bundled must not be disabled; path traversal → 403). `GET /api/dashboard/plugins` (:18575-18616) returns the active manifests (excluding hidden/disabled) that the SPA sidebar loads.
- **Inputs / options:** `Open` link.
- **Outputs / side effects:** none. Live orphans: `Achievements` (`hermes-achievements` v0.4.0, tab `/achievements` `after:analytics`, has_api) and `Kanban` (v1.0.0, `/kanban` `after:skills`, has_api).
- **Config / env:** `dashboard.hidden_plugins`, `plugins.enabled/disabled`, `HERMES_ENABLE_PROJECT_PLUGINS`.
- **Edge cases / guards:** Plugin JS load failures show `Could not load this plugin’s script. Check the Network tab (dashboard-plugins/…) and the server’s plugin path.` (`common.pluginLoadFailed`) / `The plugin’s script did not call register(), or the script errored. Open the browser console for details.` (`common.pluginNotRegistered`) on the plugin page itself (web-a shard).
- **Rebuild notes:** Manifest discovery + static file server with allowlist.

### Plugins page catalog-only strings (unused i18n keys)  `id: web-b.plugins-unused-strings`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts:382-421` (`pluginsPage` namespace) — keys defined but not referenced by `PluginsPage.tsx` at v2026.8.31: `pluginsPage.rescanHeading` = `SPA plugin registry`, `pluginsPage.runtimeHeading` = `Gateway runtime (YAML plugins)`, `pluginsPage.saveProviders` = `Save provider settings`, `pluginsPage.headline` = `Discover, install, enable, and update Hermes plugins (\`hermes plugins\` parity).`, `pluginsPage.providersHint` = `Writes memory.provider (empty = built-in) and context.engine to config.yaml. Takes effect next session.`, `pluginsPage.inactive` = `inactive`.
- **What it does:** Leftover labels from the earlier two-column layout (SPA registry vs gateway runtime sections and a single `Save provider settings` button) kept in every locale file for translation parity.
- **How it works:** Translation objects are typed by `web/src/i18n/types.ts`, so keys cannot be dropped from one locale without touching all 18 locale files; the page now renders `Runtime provider plugins`, `Save memory provider` and `Save context engine` instead.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** A mechanical string checker will find these strings only in the locale catalogs, not in the DOM.
- **Rebuild notes:** Prune unused keys when reimplementing; keep `runtime_status` badge text (`inactive`) as a literal from the API.

---

## 5. MCP page (`/mcp`)

### MCP page shell  `id: web-b.mcp-page`
- **Surface:** Web dashboard
- **Where:** Sidebar `MCP` → `/mcp`; H1 `MCP`. Header end-slot button `Add Server` (uppercase). Two sections: H2 `Your MCP servers (N)` (server icon) and H2 `Catalog (N)` (package icon) with subtitle `Browse Nous-approved MCP servers and install them with one click.` All strings are static (no `mcp` i18n namespace exists in `web/src/i18n/en.ts`).
- **What it does:** Manages the profile's configured MCP servers (add, test, OAuth-authenticate, enable/disable, delete) and installs curated servers from the bundled catalog.
- **How it works:** `web/src/pages/McpPage.tsx:46-902`. On mount `Promise.all([loadServers(), loadCatalog()])`: `api.getMcpServers()` = `GET /api/mcp/servers` (`hermes_cli/web_routers/mcp.py:61-74`: `_get_mcp_servers()` from config `mcp_servers` map, each summarised by `_mcp_server_summary` web_server.py:13667-13685 → `{name, transport: http|stdio|unknown, url, command, args[], env{redacted}, auth: header|oauth|null (header inferred from an Authorization header), enabled (not `false`), tools (include list or null)}`), and `api.getMcpCatalog()` = `GET /api/mcp/catalog` (own entry). Errors toast `Error: <e>`. Loading state: centred Spinner.
- **Inputs / options:** `Add Server`; everything below.
- **Outputs / side effects:** Empty states `No MCP servers configured.` and `No catalog entries available.`; warning line `Enable/disable takes effect on the next gateway restart.` after a toggle.
- **Config / env:** `mcp_servers.<name>` in `config.yaml` (per profile); `.env` for bearer tokens (`MCP_<NAME>_API_KEY`) and catalog credentials; OAuth tokens under the profile's MCP token storage (`tools.mcp_oauth.HermesTokenStorage`).
- **Edge cases / guards:** Live: 0 servers, 65 catalog entries, 0 diagnostics.
- **Rebuild notes:** CRUD over a config map + catalog of manifests. Better: profile selector on the page (routes accept `?profile=` but the SPA never sends it here), inline tool picker after test.

### Add MCP server modal  `id: web-b.mcp-add-server`
- **Surface:** Web dashboard
- **Where:** `/mcp` → `Add Server` → dialog `aria-labelledby="create-mcp-title"` heading `Add MCP server`, close `aria-label="Close"` (McpPage.tsx:343-506).
- **What it does:** Registers a new HTTP/SSE or stdio MCP server in the profile config, optionally with bearer-token or OAuth auth.
- **How it works:** Draft → `buildMcpServerCreate` (`web/src/lib/mcp-server-create.ts:53-78`): name trimmed (`Name required`); http: url required (`URL required`), `auth` set unless `none`, `bearer_token` when `header` (`Bearer token required` if blank); stdio: command required (`Command required`), args split on whitespace/commas, env parsed from `KEY=VALUE` lines (lines without `=` ignored). Validation errors toast the message. `api.addMcpServer(body)` = `POST /api/mcp/servers` body `MCPServerCreate {name, url?, command?, args[], env{}, auth?, bearer_token?(SecretStr), profile?}` (`web_routers/mcp.py:77-117`): `_normalize_mcp_server_create` (web_server.py:13585-13655: `Server name is required`; `Provide exactly one of URL (HTTP/SSE) or command (stdio)`; `Unsupported auth mode: <a>`; `Arguments are only supported for stdio MCP servers`; `Environment variables are only supported for stdio MCP servers`; `Bearer token is required`; `Bearer token requires header authentication`; `HTTP authentication is not supported for stdio MCP servers`; `Server '<n>' rejected: <issues>` from `hermes_cli.mcp_security.validate_mcp_server_entry`), then under the config lock: 409 `Server '<n>' already exists`; bearer token saved to the profile `.env` as `MCP_<NAME>_API_KEY` (`_save_bearer_auth_token`, `hermes_cli/mcp_config.py:153-196`) and config gets `headers: {Authorization: "Bearer ${MCP_<NAME>_API_KEY}"}`; `_save_mcp_server` (400 `Server '<n>' rejected: suspicious command/args configuration` for exfiltration-shaped stdio commands); OAuth sets `auth: oauth`.
- **Inputs / options:** `Name` input `id="mcp-name"` placeholder `my-server` (autofocus); `Transport` select `id="mcp-transport"` options `HTTP/SSE` (`http`, default) | `stdio`; http mode: `URL` `id="mcp-url"` placeholder `https://example.com/mcp`; `Authentication` select `id="mcp-auth"` options `None` | `Bearer token` (`header`) | `OAuth`; when Bearer: password `Bearer token` `id="mcp-bearer-token"` placeholder `Token or Bearer token` (autocomplete `new-password`) with note `Stored in this profile's .env; config.yaml keeps only an environment-variable reference.`; when OAuth: note `Add the server, then use Authenticate. Hermes opens the OAuth browser on the machine running the Dashboard backend.`; stdio mode: `Command` `id="mcp-command"` placeholder `npx`; `Args` `id="mcp-args"` placeholder `-y @modelcontextprotocol/server-foo`; textarea `Environment (KEY=VALUE per line)` `id="mcp-env"` placeholder `API_KEY=secret\nDEBUG=1`; button `Add` / `Adding...`. Switching transport to stdio or auth away from `header` clears the token; closing clears the token.
- **Outputs / side effects:** New `mcp_servers.<name>` block; toast `Add ✓` or `Added — authenticate with OAuth` (http+oauth) or `Failed to add: <e>`; form reset; server list reload.
- **Config / env:** `mcp_servers.<name>.{url|command,args,env,headers,auth,enabled,tools}`; `.env` `MCP_<NAME>_API_KEY`.
- **Edge cases / guards:** Duplicate-name check and save share one lock span. `env` values are redacted in reads (`_redact_mcp_env`).
- **Rebuild notes:** Normalised create with strict transport/auth matrix; secret kept out of config via env interpolation.

### MCP server card and actions  `id: web-b.mcp-server-card`
- **Surface:** Web dashboard
- **Where:** `Your MCP servers` list → one Card per server (McpPage.tsx:612-739): name, transport badge (`http` success / `stdio` warning / `unknown` secondary), badge `auth: bearer` (for `header`) or `auth: oauth`, badge `disabled` (card dimmed `opacity-60` when disabled); second line = URL (http) or `command args…` (stdio) in mono, plus `N env var(s)`; optional test result line; right-side buttons.
- **What it does:** Shows each configured server and exposes Authenticate / Enable-Disable / Test / Delete.
- **How it works:** Buttons: `Authenticate` (key icon; only for `auth === "oauth"`; own entry); `Enable` / `Disable` (power icon, `title`/`aria-label` same; green when enabled) → `api.setMcpServerEnabled(name, !enabled)` = `PUT /api/mcp/servers/{name}/enabled` body `{enabled}` (`web_routers/mcp.py:377-400`: 404 `Server '<n>' not found`, 400 `Malformed server config`; writes `mcp_servers.<n>.enabled`), local state patched, note `Enable/disable takes effect on the next gateway restart.`; `Test connection` (⚡ icon button) → own entry; `Delete` (trash, destructive) → `DeleteConfirmDialog` title `Remove MCP server`, description `"<name≤40>" — this will remove the server.` → `api.removeMcpServer(name)` = `DELETE /api/mcp/servers/{name}` (`:143-155`; `_remove_mcp_server` drops the key and the whole `mcp_servers` map when empty; 404 when missing); toast `Delete: "<name>"`; cached test result cleared.
- **Inputs / options:** the four buttons; delete confirm `Cancel`/`Delete`.
- **Outputs / side effects:** Test result text: `Connected — no tools` / `Tools: a, b, c` (green) or `<error>` / `Connection failed` (red).
- **Config / env:** `mcp_servers.<name>.enabled`.
- **Edge cases / guards:** Spinners per action (`testing`, `authenticating`, `togglingName`); toasts `Error: <e>`.
- **Rebuild notes:** Row with four idempotent calls.

### Test MCP connection  `id: web-b.mcp-test`
- **Surface:** Web dashboard
- **Where:** Server card icon button `Test connection`.
- **What it does:** Connects to the server, lists its tools, disconnects, and reports the result inline.
- **How it works:** `api.testMcpServer(name)` = `POST /api/mcp/servers/{name}/test` (`web_routers/mcp.py:158-233`): 404 if unknown; `_probe_single_server(name, cfg, details)` on a dedicated MCP event loop inside a worker thread (home-only `_config_profile_scope`, not the skills lock, to avoid blocking other endpoints during slow `npx` cold starts); for `auth: oauth` servers also requires a token on disk (`_oauth_tokens_present`) → `{ok:false, error:"OAuth authentication required — no token found.", tools:[]}`; exceptions → `{ok:false, error, tools:[]}`; success → `{ok:true, tools:[{name, description, schema_chars?}], prompts: n, resources: n}`.
- **Inputs / options:** button.
- **Outputs / side effects:** Toast `<name>: N tool(s)` or `<name>: <error|Failed>`; result cached per server for the card.
- **Config / env:** `mcp_servers.<name>.connect_timeout`.
- **Edge cases / guards:** `validate_mcp_server_entry` re-run before probing (`mcp_config.py:290-292`).
- **Rebuild notes:** Ephemeral client session → `tools/list`.

### Authenticate MCP server with OAuth  `id: web-b.mcp-oauth`
- **Surface:** Web dashboard
- **Where:** Server card button `Authenticate` (`title="Authenticate with OAuth"`, key icon; spinner while running).
- **What it does:** Runs the MCP OAuth 2.1 browser flow from the dashboard: opens a popup, polls until approved, stores tokens, reconnects the live server.
- **How it works:** `completeMcpDashboardOAuth` (`web/src/lib/mcp-dashboard-oauth.ts:15-66`): opens `about:blank` popup synchronously (error `OAuth popup was blocked — allow popups for this dashboard and retry`), `api.authMcpServer(name)` = `POST /api/mcp/servers/{name}/auth` (`web_routers/mcp.py:236-303`: `_require_token`; 404 unknown; 400 `stdio servers authenticate via env keys, not OAuth`; 400 `This server uses header/API-key auth, not OAuth`; creates `DashboardOAuthFlow(flow_id=token_urlsafe(24), redirect_uri = cfg.oauth.redirect_uri or <public/base url>/api/mcp/oauth/callback/<name>)`; 429 `Too many MCP OAuth flows are already in progress` (cap `_MAX_PENDING_MCP_OAUTH_FLOWS = 8`), 409 `MCP OAuth for '<n>' is already in progress`; worker thread `_run_dashboard_mcp_oauth` (web_server.py:13764-13856) runs `_probe_single_server` under `force_interactive_oauth()` + `dashboard_oauth_flow(flow)` with connect timeout ≥315 s, requires tokens present else `The server responded, but no OAuth token was obtained — this provider may require a manually-registered OAuth client.`, saves config, sets `flow.tools`, marks approved and `reconnect_mcp_server` when the flow home equals the process home; registration 403s are humanised via `humanize_oauth_registration_error`; waits ≤30 s for the authorization URL; returns `flow.snapshot()` `{flow_id, server_name, status: starting|authorization_required|approved|error, authorization_url, error}`); popup navigated to `authorization_url` (`OAuth server did not provide an authorization URL` otherwise); then polls `api.getMcpOAuthFlow(flow_id)` = `GET /api/mcp/oauth/flows/{flow_id}` every 1 s (tolerating 3 consecutive poll failures) until `approved` (returns `tools`) or `error` (`OAuth authorization failed`), or throws `OAuth authorization window was closed before completion` if the popup closes. Provider redirect lands on `GET /api/mcp/oauth/callback/{server_name:path}?code&state&error` (`:335-374`; constant-time `state` match; HTML pages `Authorization received` / `OAuth flow expired` (404) / `OAuth callback rejected` (400/409) / `Authorization failed` (400)). `DELETE /api/mcp/oauth/flows/{flow_id}` cancels (used by desktop; not by this SPA). Flows expire after `_MCP_DASHBOARD_OAUTH_TTL` = 15 min (`_gc_mcp_oauth_flows`).
- **Inputs / options:** button; the browser popup.
- **Outputs / side effects:** Tokens written to the profile's MCP token storage; server config saved with `auth: oauth`; card test result set to the returned tools; toast `<name>: OAuth authentication complete` or `OAuth error: <e>`.
- **Config / env:** `mcp_servers.<name>.oauth.redirect_uri` (override), dashboard public URL (`resolve_public_url`, prefix from request).
- **Edge cases / guards:** Token storage snapshot is restored on failure (`storage.restore(backup, only_if_absent=True)`); manager entry restored.
- **Rebuild notes:** Server-driven flow registry + popup + polling. Better: WebSocket/SSE push of flow status and an in-page cancel button.

### MCP catalog list  `id: web-b.mcp-catalog`
- **Surface:** Web dashboard
- **Where:** `/mcp` → H2 `Catalog (65)` (crawl heading `Catalog (65)`; sibling heading `Your MCP servers (0)`) → one Card per entry (McpPage.tsx:766-898): name, transport badge, badge `auth: <auth_type>`, link `source ↗` (when `source` is an http(s) URL) or badge `<source>`, badge `Installed` (+ `disabled` when installed but disabled), description, `Endpoint: <url>` (http) or `Runs: <command args>` (stdio), `Installs from: <install_url> @ <ref>` (git entries), collapsible `Bootstrap commands (N)` list, collapsible `Setup notes` (`post_install`), diagnostic messages (warning colour); right side badge `Installed` or button `Install` / `Installing...`.
- **What it does:** Browses the repo-shipped, Nous-approved MCP manifests and installs them into the profile with one click (prompting for credentials when needed).
- **How it works:** `GET /api/mcp/catalog?profile=` (`web_routers/mcp.py:403-487`): `hermes_cli.mcp_catalog.list_catalog()` parses `optional-mcps/<name>/manifest.yaml` (65 dirs; `hermes_cli/mcp_catalog.py:374-403`; schema dataclasses `:59-162`: `CatalogEntry{name, description, source, transport{type, command, args, url, version, env}, auth{type api_key|oauth|none, env[{name,prompt,required,secret,default}], provider, scopes, env_var}, tools{default_enabled, default_excluded}, install{type git, url, ref, bootstrap[]}, post_install, suggest{keywords, hosts}}`); each entry annotated `installed` (`name in mcp_servers`) and `enabled`; response `{entries[{name, description, source, transport, auth_type, required_env[{name,prompt,required}], command, args, url, install_url, install_ref, bootstrap[], default_enabled, post_install, suggest, needs_install, installed, enabled}], diagnostics[{name, kind: future_manifest|invalid, message}]}`.
- **Inputs / options:** `Install` per entry; `<details>` toggles `Bootstrap commands (N)` and `Setup notes`; `source ↗` / `Installs from` external links.
- **Outputs / side effects:** none until install. Full live catalog (all 65; transport/auth/endpoint):
  1. `airtable` http oauth `https://mcp.airtable.com/mcp` — Bases, tables, and records from your Airtable workspace.
  2. `algolia` http oauth `https://mcp.algolia.com/mcp` — Algolia search: indices, analytics, and settings (read-only).
  3. `alltrails` http none `https://www.alltrails.com/mcp` — AllTrails: find hikes and trails with reviews and ratings.
  4. `amplitude` http oauth `https://mcp.amplitude.com/mcp` — Amplitude analytics: charts, dashboards, experiments, flags.
  5. `asana` http oauth `https://mcp.asana.com/sse` — Tasks, projects, and goals from your Asana workspace.
  6. `atlassian` http oauth `https://mcp.atlassian.com/v1/mcp/authv2` — Jira issues and Confluence pages via Atlassian's hosted remote MCP.
  7. `attio` http oauth `https://mcp.attio.com/mcp` — CRM records, lists, and notes in Attio.
  8. `aws-knowledge` http none `https://knowledge-mcp.global.api.aws` — Authoritative AWS docs, API references, and best practices.
  9. `betterstack` http oauth `https://mcp.betterstack.com` — Better Stack: logs, uptime monitors, incidents, and status pages.
  10. `buildkite` http oauth `https://mcp.buildkite.com/mcp` — CI/CD pipelines, builds, and test results from Buildkite.
  11. `calendly` http oauth `https://mcp.calendly.com` — Scheduling links, events, and invitees from Calendly.
  12. `canva` http oauth `https://mcp.canva.com/mcp` — Create, search, and manage Canva designs.
  13. `circleci` http oauth `https://mcp.circleci.com/v1/mcp` — CircleCI: diagnose build failures, read logs, rerun workflows.
  14. `clickup` http oauth `https://mcp.clickup.com/mcp` — Tasks, docs, and workspaces in ClickUp.
  15. `close` http oauth `https://mcp.close.com/mcp` — Sales CRM: leads, opportunities, calls, and emails.
  16. `cloudflare` http oauth `https://mcp.cloudflare.com/mcp?codemode=false` — Full Cloudflare API access via the official remote MCP.
  17. `cloudinary` http oauth `https://asset-management.mcp.cloudinary.com/mcp` — Upload, search, and transform media assets in Cloudinary.
  18. `comfy-cloud` http oauth `https://cloud.comfy.org/mcp` — Generate images, video, audio, and 3D on Comfy Cloud (default_enabled: search_templates, get_template, get_template_schema, search_models, search_nodes, get_node, get_prompting_guide, run_template, submit_workflow, partner_generate, upload_file, apply_slots, get_job_status, wait_for_job, get_output, use_previous_output, cancel_job, get_queue, get_billing_status, get_workflow_canvas_url).
  19. `context7` http none `https://mcp.context7.com/mcp` — Up-to-date, version-specific library docs and code examples.
  20. `craft` http oauth `https://mcp.craft.do/my/mcp` — Craft: structured docs, tasks, and personal knowledge base.
  21. `datadog` http oauth `https://mcp.datadoghq.com/api/unstable/mcp-server/mcp` — Logs, monitors, dashboards, and incidents from Datadog.
  22. `deepwiki` http none `https://mcp.deepwiki.com/mcp` — Ask questions about any public GitHub repo (Devin's DeepWiki).
  23. `dropbox` http oauth `https://mcp.dropbox.com/mcp` — Search, read, and manage files in Dropbox.
  24. `figma` http oauth `https://mcp.figma.com/mcp` — Official Figma remote MCP — design context, Code Connect, and write-to-canvas.
  25. `fireflies` http oauth `https://api.fireflies.ai/mcp` — Meeting transcripts, summaries, and action items.
  26. `gamma` http oauth `https://mcp.gamma.app/mcp` — Gamma: generate and edit AI presentations, docs, and sites.
  27. `gitlab` http oauth `https://gitlab.com/api/v4/mcp` — GitLab: issues, merge requests, pipelines, and repo context.
  28. `globalping` http oauth `https://mcp.globalping.dev/mcp` — Ping, traceroute, DNS, and HTTP tests from global probes.
  29. `grafana` http oauth `https://mcp.grafana.com/mcp` — Query metrics, logs, dashboards, alerts, and incidents from Grafana Cloud.
  30. `hugging_face` http oauth `https://huggingface.co/mcp` — Models, datasets, Spaces, and papers from the Hugging Face Hub.
  31. `indeed` http oauth `https://mcp.indeed.com/claude/mcp` — Search jobs and listings on Indeed.
  32. `intercom` http oauth `https://mcp.intercom.com/mcp` — Conversations, tickets, and customer data from Intercom.
  33. `kiwi` http none `https://mcp.kiwi.com` — Kiwi.com flight search: itineraries with direct booking links (default_enabled: search-flight).
  34. `klaviyo` http oauth `https://mcp.klaviyo.com/mcp?core-tools-only=true&disable-tools-with-user-generated-content=true` — Klaviyo marketing: campaigns, flows, segments, and reporting.
  35. `linear` http oauth `https://mcp.linear.app/mcp` — Find, create, and update Linear issues, projects, and comments.
  36. `microsoft-learn` http none `https://learn.microsoft.com/api/mcp` — Official Microsoft, Azure, and .NET docs and code samples.
  37. `miro` http oauth `https://mcp.miro.com/` — Read and edit Miro boards, diagrams, and frames.
  38. `mixpanel` http oauth `https://mcp.mixpanel.com/mcp` — Mixpanel analytics: events, funnels, retention, dashboards.
  39. `monday` http oauth `https://mcp.monday.com/mcp` — Boards, items, docs, and workflows in monday.com.
  40. `motherduck` http oauth `https://api.motherduck.com/mcp` — MotherDuck: query DuckDB cloud warehouses with SQL (default_enabled: list_columns, list_databases, list_macros, list_shares, list_tables, list_views, query, query_rw, search_catalog).
  41. `n8n` **stdio** api_key — Manage and inspect n8n workflows from Hermes (stdio bridge, no public port). Runs `${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/server.py`; required env `N8N_BASE_URL` (prompt `n8n instance URL`), `N8N_API_KEY` (`n8n API key (generate under Settings → API)`); installs from `https://github.com/CyberSamuraiX/hermes-n8n-mcp.git` @ `7a9ae00795593aa1fdb4e61ecd640e8bfd0c3841`; bootstrap `python3 -m venv .venv`, `.venv/bin/pip install -r requirements.txt`; default_enabled: health, list_workflows, get_workflow, find_workflows, list_executions, get_execution, recent_failures, export_workflow; `needs_install: true` (the only git-bootstrap entry).
  42. `neon` http oauth `https://mcp.neon.tech/mcp` — Neon serverless Postgres: projects, branches, and SQL.
  43. `netlify` http oauth `https://netlify-mcp.netlify.app/mcp` — Sites, deploys, and env vars via Netlify's hosted MCP.
  44. `notion` http oauth `https://mcp.notion.com/mcp` — Pages and databases from your Notion workspace.
  45. `paypal` http oauth `https://mcp.paypal.com/sse` — Payments, invoices, and subscriptions via PayPal's hosted MCP.
  46. `plaid` http oauth `https://api.dashboard.plaid.com/mcp/` — Plaid dashboard: integrations, Items, and usage debugging.
  47. `postman` http oauth `https://mcp.postman.com/minimal` — Postman workspaces, collections, environments, and APIs.
  48. `prisma-postgres` http oauth `https://mcp.prisma.io/mcp` — Create and manage Prisma Postgres databases.
  49. `railway` http oauth `https://mcp.railway.com` — Railway: projects, services, deployments, and environments.
  50. `robinhood` http oauth `https://agent.robinhood.com/mcp/trading` — Robinhood agentic trading: portfolio, balances, and orders.
  51. `semgrep` http oauth `https://mcp.semgrep.ai/mcp` — Scan code for security vulnerabilities with Semgrep.
  52. `sentry` http oauth `https://mcp.sentry.dev/mcp` — Issues, stack traces, and error context from Sentry.
  53. `square` http oauth `https://mcp.squareup.com/sse` — Catalog, orders, and payments via Square's hosted MCP.
  54. `strava` http oauth `https://mcp.strava.com/mcp` — Strava: activities, fitness trends, training load (read-only).
  55. `stripe` http oauth `https://mcp.stripe.com` — Payments, customers, and invoices via Stripe's hosted MCP.
  56. `supabase` http oauth `https://mcp.supabase.com/mcp` — Database, auth, and storage from your Supabase projects.
  57. `todoist` http oauth `https://ai.todoist.net/mcp` — Manage Todoist tasks and projects.
  58. `trivago` http none `https://mcp.trivago.com/mcp` — trivago hotel search: compare prices by city and dates.
  59. `twelve-data` http oauth `https://mcp.twelvedata.com/mcp` — Stocks, forex, and crypto market data from Twelve Data.
  60. `twilio-docs` http none `https://mcp.twilio.com/docs` — Twilio developer docs search (public beta, read-only).
  61. `unreal-engine` http none `http://127.0.0.1:8000/mcp` — Drive the Unreal Engine 5.8 editor over its local MCP server.
  62. `vercel` http oauth `https://mcp.vercel.com` — Deployments, logs, and projects via Vercel's hosted MCP.
  63. `webflow` http oauth `https://mcp.webflow.com/mcp` — Sites, CMS collections, and pages via Webflow's hosted MCP.
  64. `wolfram` http none `https://agenttools.wolfram.com/mcp` — Wolfram|Alpha computation, math, and curated knowledge.
  65. `wordpress-com` http oauth `https://public-api.wordpress.com/wpcom/v2/mcp/v1` — WordPress.com: posts, pages, drafts, stats, and comments.
  Every OAuth entry's `post_install` note reads `On first connection Hermes opens a browser to authorize with <Vendor> (or run \`hermes mcp login <name>\`). Approve access, then restart the session so tools load.` (some add vendor notes, e.g. amplitude EU URL, alltrails `hermes mcp configure alltrails` pruning hint). Most entries carry `suggest {keywords, hosts}` used by the desktop composer's brand pills (not by this page).
- **Config / env:** catalog dir override via `get_optional_mcps_dir` (`HERMES_OPTIONAL_MCPS_DIR`-style constant in `hermes_constants`); install state in `mcp_servers.<name>`.
- **Edge cases / guards:** Invalid manifests are skipped and reported in `diagnostics` (`invalid` / `future_manifest` = "update Hermes"); unknown profile → 404 rather than an empty list.
- **Rebuild notes:** YAML manifests → typed entries → per-entry install. Better: search/filter, category tags, show tool lists from `default_enabled`, and a per-entry tool checklist after install (the CLI has it; the SPA does not).

### Install catalog entry (with credentials modal)  `id: web-b.mcp-catalog-install`
- **Surface:** Web dashboard
- **Where:** Catalog card `Install`; for entries with `required_env`, dialog `aria-labelledby="install-mcp-title"` heading `Install <name>`, text `This MCP requires the following values to be configured.`, one password input per env var labelled `<prompt>` + ` *` when required (`id="install-env-<NAME>"`, placeholder `<NAME>`), button `Install` / `Installing...`, close `aria-label="Close"` (McpPage.tsx:245-294, 509-588).
- **What it does:** Writes the catalog server into config (and its credentials into `.env`), enabling it by default; git-bootstrap entries install in the background via the CLI.
- **How it works:** `handleInstallClick`: no required env → `runInstall(entry, {})` immediately; else opens the modal; `handleInstallSubmit` validates required fields (toast `<prompt> required`) and trims values. `api.installMcpCatalogEntry(name, env, true)` = `POST /api/mcp/catalog/install` body `MCPCatalogInstall {name, env{}, enable:true, profile?}` (`web_routers/mcp.py:490-577`): 404 `No catalog entry '<n>'`; 400 `Catalog entry '<n>' does not declare environment variable(s): …` (closed schema); `validate_env_var_name_for_write` per key; saves supplied env via `save_env_value`; if `entry.install` (git) → `_spawn_hermes_action(args + ["mcp","install",name], "mcp-install-<slug>-<hash>")` and returns `{ok, name, background:true, action}`; else `mcp_catalog.install_entry(entry, enable)` synchronously (`hermes_cli/mcp_catalog.py:887-976`: builds `mcp_servers.<name>` from the manifest via `_build_server_config`, `_save_mcp_server` (CatalogError `catalog entry '<n>' rejected: suspicious command/args configuration`), `_apply_tool_selection` — in this non-interactive path falls back to `tools.default_enabled` / prior selection when the probe fails), returning `{ok, name, background:false}`.
- **Inputs / options:** `Install` buttons; modal inputs.
- **Outputs / side effects:** Toasts `Installing in background…` or `Installed: "<name>"` or `Failed to install: <e>`; modal closed; servers + catalog reloaded (entry now shows `Installed`). The SPA does not tail the `mcp-install-*` action log (no progress card on this page).
- **Config / env:** `mcp_servers.<name>` (`enabled: true`, `auth: oauth` for OAuth entries, `tools.include`/`exclude` per manifest), `.env` credentials, git checkouts under the MCP install root (`_install_root()`).
- **Edge cases / guards:** OAuth entries need a subsequent `Authenticate` (server card) or first-connection browser flow; `hermes mcp login <name>` is the CLI equivalent.
- **Rebuild notes:** Manifest → config translation; better: show background install progress and auto-prompt OAuth after install.

### Replace whole MCP server map (API-only in SPA)  `id: web-b.mcp-replace-api`
- **Surface:** API
- **Where:** `PUT /api/mcp/servers` body `MCPServersReplace {servers{name→raw config}, profile?}` (`web_routers/mcp.py:120-140`).
- **What it does:** Replaces the entire `mcp_servers` map so deletions/`enabled:false` removals persist (the generic `/api/config` deep-merge cannot delete keys). Used by the desktop mcp.json editor, not by this page.
- **How it works:** `_replace_mcp_servers` validates every entry up front; any suspicious entry rejects the whole save → 400 with joined issues; empty map removes the key.
- **Inputs / options:** as above.
- **Outputs / side effects:** `{"ok": true}`.
- **Config / env:** `mcp_servers`.
- **Edge cases / guards:** atomic all-or-nothing.
- **Rebuild notes:** n/a.

---

## 6. Addendum — items verified against the live DOM (second pass)

The entries below were added after a second Playwright pass that opened states the first crawl never reached
(Blueprints view, toolset drawer, cron schedule-mode switching, the MCP transport/auth comboboxes, the memory-provider
picker). They quote strings that are rendered by the running dashboard but were only summarised, or not present at all,
in sections 1–5. Nothing here replaces an earlier entry; each one adds strings/fields an earlier entry left implicit.

### Schedule description renderer (`describeSchedule`) and its string surface  `id: web-b.cron-schedule-describe`
- **Surface:** Web dashboard
- **Where:** `/cron` → `Jobs` → each job card's schedule line (the text under the job title, e.g. `Every 30 min`, `Daily at 09:00`, `Weekly on Mon, Wed, Fri at 14:30`, `Monthly on the 1st at 09:00`, `Once at 2026-02-03 14:00`, or `—`). Rendered at `CronPage.tsx:1147` via `getJobScheduleDisplay(job, scheduleDescribeStrings)` (`CronPage.tsx:459-473`).
- **What it does:** Turns the machine schedule stored on a cron job (`interval` minutes / `once` ISO timestamp / `cron` expression) into one human sentence, falling back to the raw expression when the shape is too exotic to humanise safely.
- **How it works:** `web/src/lib/schedule.ts:338-372 describeSchedule(schedule, fallbackDisplay, strings)`. Order of attempts: (1) `kind === "interval"` and numeric `minutes` → `describeInterval` (`:374-388`): `minutes <= 0` → `strings.none`; `minutes % 1440 === 0` → `everyDays` with `{n} = minutes/1440`; `minutes % 60 === 0` → `everyHours` with `{n} = minutes/60`; otherwise `everyMinutes` with `{n} = minutes`. (2) `kind === "once"` and `run_at` → `onceAt` with `{time}` = `formatIsoLocal(run_at, false)` (`:433-444`: local `YYYY-MM-DD HH:MM`, seconds and timezone dropped; unparseable input returned verbatim). (3) `kind === "cron"` and `expr` → `describeCronExpression` (`:400-424`) which calls `parseSimpleCronExpression` (`:213-276`) and maps `daily → dailyAt{time}`, `weekly → weeklyAt{days}{time}` (days = `strings.weekdaysShort[d]` joined with `, `), `monthly → monthlyAt{day}{time}` with `{day} = strings.ordinal(dayOfMonth)`. (4) `fallbackDisplay` (the backend's `schedule_display`) re-run through `describeCronExpression`, else printed raw. (5) `schedule.display`, then `schedule.expr`, then `strings.none`. `parseSimpleCronExpression` accepts **exactly 5 whitespace-separated fields**, requires `month === "*"`, requires every field to match `^\d+(,\d+)*$|^\*$` (no ranges, no `*/n` steps, no names, no `L`), rejects `*` in minute or hour, rejects multi-value minute/hour lists, range-checks hour 0–23 and minute 0–59, then: `dom=* dow=*` → daily; `dom=* dow=list` → weekly with each entry 0–7 (7 normalised to 0, duplicates dropped, empty → null); `dom=<1..31> dow=*` → monthly; `dom` and `dow` both constrained → null. 6-field expressions (`minute hour dom month dow year`, which the backend `parse_schedule` accepts) are deliberately rejected so `0 9 * * * 2099` is not mis-rendered as `Daily at 09:00` (comment `schedule.ts:392-399`). `strings` is assembled inline per render at `CronPage.tsx:566-570`: `...t.cron.scheduleDescribe`, `weekdaysShort: t.cron.scheduleModes.weekdaysShort`, and `ordinal: locale === "en" ? englishOrdinal : (n) => String(n)` — every non-English locale gets bare digits rather than fabricated ordinals. `englishOrdinal` (`schedule.ts:450-465`): floors the day, returns `String(day)` for non-finite or `< 1`, `th` for last-two-digits 11–13, else `st/nd/rd` for 1/2/3 and `th` otherwise.
- **Inputs / options:** No user controls — this is a pure render path. Its complete translated string surface (`web/src/i18n/en.ts:287-296`, one object per locale, 18 locales) is: `cron.scheduleDescribe.none` = `—`; `cron.scheduleDescribe.everyMinutes` = `Every {n} min`; `cron.scheduleDescribe.everyHours` = `Every {n} h`; `cron.scheduleDescribe.everyDays` = `Every {n} d`; `cron.scheduleDescribe.dailyAt` = `Daily at {time}`; `cron.scheduleDescribe.weeklyAt` = `Weekly on {days} at {time}`; `cron.scheduleDescribe.monthlyAt` = `Monthly on the {day} at {time}`; `cron.scheduleDescribe.onceAt` = `Once at {time}`. Weekday tokens come from `cron.scheduleModes.weekdaysShort` = `["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]` (`en.ts:277`).
- **Outputs / side effects:** A single string per job card. No network, no storage.
- **Config / env:** n/a — locale comes from the dashboard language switcher (`useI18n().locale`).
- **Edge cases / guards:** `describeSchedule` never throws on malformed input; every failure path degrades to raw text. `strings.ordinal` is a function, so a locale that ships a different pluralisation cannot break the render. Unit-tested in `web/src/lib/schedule.test.ts`.
- **Rebuild notes:** Implement as `(schedule, fallback, strings) → string` with a strict 5-field cron recogniser and an explicit "give up and show the raw expression" branch; never guess at ranges or steps. A better version would compute the next 3 fire times (with the job's timezone) and show them under the sentence, and would humanise steps (`*/15` → `Every 15 min`) which this version deliberately refuses.

### Cron page catalog-only strings (unused i18n keys)  `id: web-b.cron-unused-strings`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts` `cron` namespace (lines 255-313) — keys that exist in all 18 locale files but that `CronPage.tsx` / `ScheduleBuilder.tsx` never render at v2026.8.31.
- **What it does:** Leftovers from the pre-ScheduleBuilder cron form (a raw cron-expression input) and from a hard-coded delivery-target list that the `/api/cron/delivery-targets` endpoint replaced.
- **How it works:** Locale objects are typed by `web/src/i18n/types.ts`, so a key cannot be deleted from `en.ts` without editing every other locale; unused keys therefore survive refactors. Verified by grepping `t.cron.<key>` across `web/src`.
- **Inputs / options:** The unused keys, verbatim: `cron.schedulePlaceholder` = `0 9 * * *` (en.ts:261 — the builder uses `cron.scheduleModes.customPlaceholder`, whose value is the identical string); `cron.delivery.telegram` = `Telegram`; `cron.delivery.discord` = `Discord`; `cron.delivery.slack` = `Slack`; `cron.delivery.email` = `Email` (en.ts:305-311 — the Deliver-to select labels every non-`local` option from the API's `target.name`, `CronPage.tsx:361`, so these four are never read). Partially-used: `cron.schedule` = `Schedule (cron expression)` (en.ts:260) is no longer a field label — its only remaining use is inside the validation toast `${t.cron.prompt} & ${t.cron.schedule} required` → `Prompt & Schedule (cron expression) required` (`CronPage.tsx:704`, `:732`); the visible label above the picker is `cron.scheduleMode` = `Schedule`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** A mechanical string checker will find these five strings in the locale catalogs but never in the DOM. `Slack` in particular appears nowhere else in this shard's UI.
- **Rebuild notes:** Prune on rewrite, or wire `cron.delivery.*` back in as a display-name override table for platform ids so target names are translated instead of echoed from the server.

### Automation Blueprints — verbatim card copy  `id: web-b.cron-blueprints-copy`
- **Surface:** Web dashboard
- **Where:** `/cron` → segmented radio `Blueprints` → the 16 cards, each rendering `title` (bold), `description` (muted paragraph), tag badges, and the `Set up` button (`AutomationBlueprints.tsx:173-223`). Captured live from the running dashboard (`hermes_inv/web_crawl_b/cron_blueprints2.png`, `webb_states2.json` state `cron:blueprints2`).
- **What it does:** Supplies the human-facing sales copy for each blueprint; the entry `web-b.cron-blueprints` documents the mechanism, slots and defaults — this entry records the exact rendered sentences and tag chips so a checker can match them.
- **How it works:** `description` and `tags` are serialised straight from `cron/blueprint_catalog.py` `CATALOG` by `blueprint_catalog_entry()` and returned by `GET /api/cron/blueprints`; the SPA renders them verbatim with no truncation. The same payload also carries `scheduleHuman`, `command` (a `/blueprint …` slash string) and `appUrl` (`hermes://blueprint/<key>?…`), neither of which this page renders.
- **Inputs / options:** All 16 cards, `key` :: `title` :: `description` :: tags :: `scheduleHuman` :: `command`:
  1. `morning-brief` :: `Morning briefing` :: `A short daily briefing: today's calendar, weather, and anything urgent waiting on you.` :: `daily`, `briefing` :: `daily at 08:00` :: `/blueprint morning-brief time=08:00 deliver=origin`
  2. `important-mail` :: `Important-mail monitor` :: `Check your inbox periodically and ping you ONLY about mail that actually needs attention.` :: `email`, `monitor` :: `every 30 minutes` :: `/blueprint important-mail interval_min=30 criteria="needs a reply today, is from my manager or family, or mentions a deadline" deliver=origin`
  3. `weekly-review` :: `Weekly review` :: `A weekly recap: what got done, what's still open, and what's coming up.` :: `weekly`, `review` :: `sunday at 18:00` :: `/blueprint weekly-review time=18:00 day=sunday deliver=origin`
  4. `workday-start` :: `Workday start reminder` :: `A weekday nudge with your agenda and top priorities.` :: `daily`, `focus` :: `weekdays at 09:00` :: `/blueprint workday-start time=09:00 deliver=origin`
  5. `custom-reminder` :: `Custom reminder` :: `A recurring reminder in your own words, on your schedule.` :: `reminder` :: `everyday at 14:00` :: `/blueprint custom-reminder what="take a break and stretch" time=14:00 recurrence=everyday deliver=origin`
  6. `evening-winddown` :: `Evening wind-down` :: `An end-of-day check-in: tomorrow's calendar at a glance and anything you should prep tonight.` :: `daily`, `evening` :: `daily at 21:00` :: `/blueprint evening-winddown time=21:00 deliver=origin`
  7. `news-digest` :: `Topic news digest` :: `A recurring digest on a topic you care about — deduped against what was already sent, so only genuinely new items land.` :: `digest`, `research` :: `weekdays at 18:00` :: `/blueprint news-digest topic="AI and technology" time=18:00 recurrence=weekdays count=5 deliver=origin`
  8. `bill-renewal-watch` :: `Bills & renewals reminder` :: `A heads-up before a recurring payment, subscription renewal, or due date — so nothing auto-charges by surprise.` :: `reminder`, `finance` :: `everyday at 10:00` :: `/blueprint bill-renewal-watch what="my streaming subscription renews soon" time=10:00 recurrence=everyday deliver=origin`
  9. `price-watch` :: `Price & availability watch` :: `Watch an exact product, flight, hotel, or listing and alert when your price or availability condition is met.` :: `prices`, `shopping`, `travel`, `monitor` :: `on a schedule` :: `/blueprint price-watch item="a product URL or exact flight/hotel/listing description" condition="the all-in price drops below my target" interval_h=6 deliver=origin`
  10. `competitor-watch` :: `Competitor news watch` :: `Track named companies for material news — launches, pricing, funding, filings — with a cited digest.` :: `competitors`, `news`, `monitor`, `research` :: `monday at 09:00` :: `/blueprint competitor-watch companies="two or three competitors, by canonical name" categories="product launches, pricing changes, funding, partnerships, executive moves, incidents" time=09:00 recurrence=monday deliver=origin`
  11. `habit-checkin` :: `Habit check-in` :: `A recurring nudge to keep a habit on track and reflect on whether you did it.` :: `habit`, `wellbeing` :: `everyday at 20:00` :: `/blueprint habit-checkin habit="20 minutes of reading" time=20:00 recurrence=everyday deliver=origin`
  12. `hydration-move` :: `Hydration & movement nudge` :: `A periodic nudge during the day to drink water, stand up, and stretch.` :: `wellbeing`, `focus` :: `weekdays, every hour` :: `/blueprint hydration-move interval_hours=1 start_hour=9 end_hour=17 deliver=origin`
  13. `meal-plan` :: `Weekly meal plan` :: `A weekly meal plan plus a consolidated grocery list, tuned to your diet and how much time you have to cook.` :: `weekly`, `food` :: `sunday at 17:00` :: `/blueprint meal-plan diet="no restrictions" meals="dinner only" effort=quick time=17:00 day=sunday deliver=origin`
  14. `learn-daily` :: `Daily learning drip` :: `One bite-sized lesson a day on a topic you want to learn, building progressively over time.` :: `learning`, `daily` :: `weekdays at 08:30` :: `/blueprint learn-daily topic="Spanish vocabulary" time=08:30 recurrence=weekdays deliver=origin`
  15. `gratitude-journal` :: `Gratitude & reflection prompt` :: `A gentle evening prompt to reflect on the day and note what went well.` :: `wellbeing`, `reflection` :: `everyday at 21:30` :: `/blueprint gratitude-journal time=21:30 recurrence=everyday deliver=origin`
  16. `on-this-day` :: `On-this-day discovery` :: `A daily dose of curiosity: a notable historical event, fact, or word for the day.` :: `daily`, `curiosity` :: `daily at 07:30` :: `/blueprint on-this-day flavor="on this day in history" time=07:30 deliver=origin`
- **Outputs / side effects:** Expanded card (live DOM, state `cron:blueprint-form2`) renders field labels upper-cased by CSS — e.g. `Morning briefing` expands to `Cancel`, `WHAT TIME?` + help `24h local time, e.g. 08:00`, `WHERE TO DELIVER?` with the value `origin` and help `origin = the chat you set this up from (or your configured home channel when created from the dashboard); local = save only, no message; or any connected platform name`, then `Schedule it`.
- **Config / env:** n/a.
- **Edge cases / guards:** Each expanded field renders `<Label htmlFor="<blueprint key>-<slot name>">` (live: `morning-brief-time`, `morning-brief-deliver`) but `FieldInput` (`AutomationBlueprints.tsx:29-67`) sets **no `id`** on the control it returns, so every blueprint label points at a non-existent element and clicking a label never focuses its input — a real a11y defect, and the reason blueprint fields cannot be driven by `label` selectors. All 16 cards render simultaneously and only one can be expanded at a time (`Set up` on another card replaces the open form); an expanded card shows `Cancel` in place of `Set up`.
- **Rebuild notes:** Keep title/description/tags in the catalog (server-side) so they translate and version with the prompt templates rather than living in the SPA. A better version would preview the exact generated prompt and cron expression inside the expanded card before `Schedule it`.

### Local skills inventory rendered by the page (53 rows)  `id: web-b.skills-local-inventory`
- **Surface:** Web dashboard
- **Where:** `/skills` → panel item `All (53)` (rendered `ALL (53)`) → card `All` → one `SkillRow` per skill; also the same 53 names appear as checkbox labels inside the cron job form's `Skills (optional)` picker (`cron-skills`, live DOM state `cron:create-modal`). Header text `53/53 enabled`. Each row's edit button carries `aria-label="Edit <name>"` (e.g. `Edit airtable`, `Edit youtube-content`).
- **What it does:** This is the actual content of the Skills page on a fresh install — the bundled skill set the agent ships with. `web-b.skills-list` documents the row mechanics; this entry records the names, categories and one-line descriptions that are rendered as visible text.
- **How it works:** `GET /api/skills?profile=` → `tools.skills_tool._find_all_skills(skip_disabled=True)` scans `<repo>/skills/**/SKILL.md` plus `<HERMES_HOME>/skills` and `skills.external_dirs`; `name`/`description`/`category` come from each SKILL.md's YAML frontmatter (`category` is the directory segment under `skills/`). All 53 report `enabled: true`, `usage: 0`, `provenance: "bundled"` on a fresh install. Category chips in the left panel are derived client-side (`allCategories`, `SkillsPage.tsx:291-308`) and title-cased by `prettyCategory` (`:87-97`).
- **Inputs / options:** Category panel items rendered live (label + count): `Autonomous Ai Agents 5`, `Creative 10`, `Email 2`, `Media 3`, `Note Taking 1`, `Productivity 14`, `Research 4`, `Social Media 1`, `Software Development 12`, `Web 1`. Full row list, grouped by category exactly as the panel groups them (name — description, verbatim):
  - **Autonomous Ai Agents** (`autonomous-ai-agents`, 5):
    1. `claude-code` — Delegate coding to Claude Code CLI (features, PRs).
    2. `codex` — Delegate coding to OpenAI Codex CLI (features, PRs).
    3. `computer-use` — Drive the desktop background-first; escalate on signal.
    4. `hermes-agent` — Use, configure, theme, extend, and orchestrate Hermes Agent.
    5. `opencode` — Delegate coding to OpenCode CLI (features, PR review).
  - **Creative** (`creative`, 10):
    6. `architecture-diagram` — Dark-themed SVG architecture/cloud/infra diagrams as HTML.
    7. `ascii-video` — ASCII video: convert video/audio to colored ASCII MP4/GIF.
    8. `baoyu-infographic` — Infographics: 21 layouts x 21 styles (信息图, 可视化).
    9. `claude-design` — Design one-off HTML artifacts (landing, deck, prototype).
    10. `design-md` — Author/validate/export Google's DESIGN.md token spec files.
    11. `humanizer` — Humanize text: strip AI-isms and add real voice.
    12. `manim-video` — Manim CE animations: 3Blue1Brown math/algo videos.
    13. `p5js` — p5.js sketches: gen art, shaders, interactive, 3D.
    14. `popular-web-designs` — 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS.
    15. `songwriting-and-ai-music` — Songwriting craft and Suno AI music prompts.
  - **Email** (`email`, 2):
    16. `email-inbox-triage` — Triage an inbox: prioritize threads, draft replies safely.
    17. `himalaya` — Himalaya CLI: IMAP/SMTP email from terminal.
  - **Media** (`media`, 3):
    18. `gif-search` — Search/download GIFs from Tenor via curl + jq.
    19. `songsee` — Audio spectrograms/features (mel, chroma, MFCC) via CLI.
    20. `youtube-content` — YouTube transcripts to summaries, threads, blogs.
  - **Note Taking** (`note-taking`, 1):
    21. `obsidian` — Read, search, create, and edit notes in the Obsidian vault.
  - **Productivity** (`productivity`, 14):
    22. `airtable` — Airtable REST API via curl. Records CRUD, filters, upserts.
    23. `box` — Box manages cloud files, sharing, search, and metadata.
    24. `document-to-action-items` — Extract cited obligations, deadlines, tasks from documents.
    25. `docx` — Create, read, edit, template, and review Word .docx files.
    26. `google-workspace` — Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python.
    27. `maps` — Geocode, POIs, routes, timezones via OpenStreetMap/OSRM.
    28. `meeting-action-items` — Turn meeting notes into cited decisions, owners, tickets.
    29. `notion` — Notion API + ntn CLI: pages, databases, markdown, Workers.
    30. `pdf` — PDF files: create, read, merge, fill, OCR, edit text.
    31. `powerpoint` — Create, read, edit .pptx decks with python-pptx.
    32. `product-price-monitor` — Watch product, flight, or listing prices; alert on target.
    33. `teams-meeting-pipeline` — Teams meeting summaries, job replay, Graph subscriptions.
    34. `weekly-review-planning` — Weekly reset: commitments, stalled work, next-week plan.
    35. `xlsx` — Create, read, edit Excel .xlsx workbooks and CSVs.
  - **Research** (`research`, 4):
    36. `arxiv` — Search arXiv papers by keyword, author, category, or ID.
    37. `competitor-news-monitor` — Watch named companies for material news; cited digests.
    38. `grounded-citations` — Ground answers and documents in cited, verifiable sources.
    39. `llm-wiki` — Karpathy's LLM Wiki: build/query interlinked markdown KB.
  - **Social Media** (`social-media`, 1):
    40. `xurl` — X/Twitter via xurl CLI: raw post search, posting, DM, media.
  - **Software Development** (`software-development`, 12):
    41. `codebase-inspection` — Inspect codebases w/ pygount: LOC, languages, ratios.
    42. `dogfood` — Exploratory QA of web apps: find bugs, evidence, reports.
    43. `github` — GitHub via gh CLI: PRs, issues, reviews, repos, auth.
    44. `hermes-agent-skill-authoring` — Author in-repo SKILL.md files: frontmatter and structure.
    45. `inspecting-hermes-desktop-dom` — Read the live Hermes desktop DOM/CSS over CDP.
    46. `node-inspect-debugger` — Debug Node.js via --inspect + Chrome DevTools Protocol CLI.
    47. `python-debugpy` — Debug Python: pdb REPL + debugpy remote (DAP).
    48. `requesting-code-review` — Pre-commit review: security scan, quality gates, auto-fix.
    49. `simplify-code` — Parallel 4-agent cleanup of recent code changes.
    50. `spike` — Throwaway experiments to validate an idea before build.
    51. `systematic-debugging` — 4-phase root cause debugging: understand bugs before fixing.
    52. `test-driven-development` — TDD: enforce RED-GREEN-REFACTOR, tests before code.
  - **Web** (`web`, 1):
    53. `blocked-page-recovery` — Use when a fetch fails: 403/429, paywall, WAF, bot wall.
- **Outputs / side effects:** Each row's `Switch` writes `skills.disabled`; each row's pencil opens `Edit skill: <name>`. Every row's pencil is addressable by its own aria-label, all 53 verbatim: `Edit airtable`, `Edit architecture-diagram`, `Edit arxiv`, `Edit ascii-video`, `Edit baoyu-infographic`, `Edit blocked-page-recovery`, `Edit box`, `Edit claude-code`, `Edit claude-design`, `Edit codebase-inspection`, `Edit codex`, `Edit competitor-news-monitor`, `Edit computer-use`, `Edit design-md`, `Edit document-to-action-items`, `Edit docx`, `Edit dogfood`, `Edit email-inbox-triage`, `Edit gif-search`, `Edit github`, `Edit google-workspace`, `Edit grounded-citations`, `Edit hermes-agent`, `Edit hermes-agent-skill-authoring`, `Edit himalaya`, `Edit humanizer`, `Edit inspecting-hermes-desktop-dom`, `Edit llm-wiki`, `Edit manim-video`, `Edit maps`, `Edit meeting-action-items`, `Edit node-inspect-debugger`, `Edit notion`, `Edit obsidian`, `Edit opencode`, `Edit p5js`, `Edit pdf`, `Edit popular-web-designs`, `Edit powerpoint`, `Edit product-price-monitor`, `Edit python-debugpy`, `Edit requesting-code-review`, `Edit simplify-code`, `Edit songsee`, `Edit songwriting-and-ai-music`, `Edit spike`, `Edit systematic-debugging`, `Edit teams-meeting-pipeline`, `Edit test-driven-development`, `Edit weekly-review-planning`, `Edit xlsx`, `Edit xurl`, `Edit youtube-content` (each also carries `title="Edit SKILL.md"`). Nothing else on the page mutates this list.
- **Config / env:** `skills.disabled`, `skills.external_dirs`, `HERMES_HOME`.
- **Edge cases / guards:** `hermes-agent` is in `ESSENTIAL_SKILLS` and is silently re-enabled if a caller tries to disable it (`hermes_cli/skills_config.py:67-79`). Descriptions are clamped to two lines in the row (`line-clamp-2`) but returned in full by the API; skills without a description render `No description available.` (`i18n: skills.noDescription`) — none of the 53 bundled skills hit that path.
- **Rebuild notes:** Ship the catalog as directories of `SKILL.md` with `name`/`description`/`category` frontmatter and derive the UI grouping from the data, not from a hard-coded taxonomy. A better version would show per-skill usage counts (already returned as `usage`) and last-used timestamps, and let a category be multi-selected.

### Browse hub — Featured skills landing (live)  `id: web-b.skills-hub-featured`
- **Surface:** Web dashboard
- **Where:** `/skills` → `Browse hub` → before any search, section heading `Featured skills` with the sub-line `from the Hermes index — search above for thousands more`; while the sources request is in flight the strip reads `Connecting to skill hubs…` (live DOM state `skills:hub2`).
- **What it does:** Shows a starter grid of installable skills pulled from the centralised Hermes index so the hub view is not empty before the user types a query.
- **How it works:** `GET /api/skills/hub/sources?profile=` returns `featured` = the index's `search("", limit=12)` result, and it is populated **only when `index_available` is true** (`web_routers/skills.py:114-184`). When the index is unreachable, `index_available` is `false`, `featured` is empty and the page falls back to the card `Search the hub above to browse installable skills from the connected sources.` — both states were observed on the same install (the first evidence pass captured `index_available: false`, the second `index_available: true`), so this is a runtime-availability toggle, not a build flag. Each featured item renders through the same `HubResultCard` as a search hit, so it carries the trust badge (`builtin`), the source badge (`official`), up to 5 tag chips, the identifier line, and the `Details` / `Install` buttons (`aria-label="Open <name>"` on the card body).
- **Inputs / options:** Live featured set (12 cards, all `source: official`, `trust_level: builtin`), as `name` — `identifier` — tags — description:
  1. `1password` — `official/security/1password` — `security`, `secrets`, `1password`, `op`, `cli` — `Set up and use 1Password CLI (op). Use when installing the CLI, enabling desktop app integration, signing in, and reading/injecting secrets for commands.`
  2. `3-statement-model` — `official/finance/3-statement-model` — `finance`, `three-statement`, `income-statement`, `balance-sheet`, `cash-flow`, `excel`, `openpyxl`, `modeling` — `Build fully-integrated 3-statement models (IS, BS, CF) in Excel with working capital schedules, D&A roll-forwards, debt schedule, and the plugs that make cash and retained earnings tie.` (truncated in the card by `line-clamp-2`)
  3. `adversarial-ux-test` — `official/dogfood/adversarial-ux-test` — `qa`, `ux`, `testing`, `adversarial`, `dogfood`, `personas`, `user-testing` — `Roleplay the most difficult, tech-resistant user for your product. Browse the app as that persona, find every UX pain point, then filter complaints through a pragmatism layer to separate real problems…`
  4. `agentmail` — `official/email/agentmail` — `email`, `communication`, `agentmail`, `mcp` — `Give the agent its own dedicated email inbox via AgentMail. Send, receive, and manage email autonomously using agent-owned email addresses (e.g. hermes-agent@agentmail.to).`
  5. `antigravity-cli` — `official/autonomous-ai-agents/antigravity-cli` — `Coding-Agent`, `Antigravity`, `CLI`, `Auth`, `Plugins`, `Sandbox` — `Operate the Antigravity CLI (agy): plugins, auth, sandbox.`
  6. `axolotl` — `official/mlops/training/axolotl` — `Fine-Tuning`, `Axolotl`, `LLM`, `LoRA`, `QLoRA`, `DPO`, `KTO`, `ORPO`, `GRPO`, `YAML`, `HuggingFace`, `DeepSpeed`, `Multimodal` — `Axolotl: YAML LLM fine-tuning (LoRA, DPO, GRPO).`
  7. `baoyu-article-illustrator` — `official/creative/baoyu-article-illustrator` — `article-illustration`, `creative`, `image-generation` — `Article illustrations: type × style × palette consistency.`
  8. `baoyu-comic` — `official/creative/baoyu-comic` — `comic`, `knowledge-comic`, `creative`, `image-generation` — `Knowledge comics (知识漫画): educational, biography, tutorial.`
  9. `bioinformatics` — `official/research/bioinformatics` — `bioinformatics`, `genomics`, `sequencing`, `biology`, `research`, `science` — `Gateway to 400+ bioinformatics skills from bioSkills and ClawBio. Covers genomics, transcriptomics, single-cell, variant calling, pharmacogenomics, metagenomics, structural biology, and more.`
  10. `blackbox` — `official/autonomous-ai-agents/blackbox` — `Coding-Agent`, `Blackbox`, `Multi-Agent`, `Judge`, `Multi-Model` — `Delegate coding tasks to Blackbox AI CLI agent. Multi-model agent with built-in judge that runs tasks through multiple LLMs and picks the best result. Requires the blackbox CLI and a Blackbox AI API key.`
  11. `blender-mcp` — `official/creative/blender-mcp` — (no tags) — `Drive Blender via the catalog blender MCP, with bpy recipes.`
  12. `canvas` — `official/productivity/canvas` — `Canvas`, `LMS`, `Education`, `Assignments`, `Courses` — `Canvas LMS integration — fetch enrolled courses and assignments using API token authentication.`
- **Outputs / side effects:** Read-only until `Install`/`Details` is used (see `web-b.skills-hub-install`, `web-b.skills-hub-detail`). The card body click and the `Details` button open the same dialog. The 12 card bodies are addressable by aria-label, verbatim: `Open 1password`, `Open 3-statement-model`, `Open adversarial-ux-test`, `Open agentmail`, `Open antigravity-cli`, `Open axolotl`, `Open baoyu-article-illustrator`, `Open baoyu-comic`, `Open bioinformatics`, `Open blackbox`, `Open blender-mcp`, `Open canvas`.
- **Config / env:** Index availability (`index_available`) is a live probe of the centralised Hermes skills index; `GITHUB_TOKEN` affects only the GitHub source.
- **Edge cases / guards:** The featured list is capped at 12 by the server; the strip badge `Hermes Index` is dimmed with title `Centralized index unavailable — falling back to live sources` while `available` is false, and that same condition empties `featured`.
- **Rebuild notes:** Serve a small curated/ranked "featured" page from the index so a cold hub view is never blank, and reuse the search result card component. A better version would personalise the featured set from installed skills and show install counts.

### Skills page — remaining catalog-only strings  `id: web-b.skills-unused-strings-2`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts:440-445` — `skills` keys defined in every locale but never read by `SkillsPage.tsx` (the only file that reads `t.skills.*`).
- **What it does:** Records the rest of the dead `skills.*` surface. `web-b.skills-unused-strings` already covers `skills.searchPlaceholder`; these four were previously described as "used by the shared profile banner", which is not the case at this version.
- **How it works:** Verified by enumerating every `t.skills.<key>` occurrence in `web/src` — used keys are exactly `title, all, categories, filters, noSkills, noSkillsMatch, skillCount, resultCount, noDescription, toolsets, toolsetLabel, noToolsetsMatch, setupNeeded, disabledForCli, enabledOf`. `ProfileScopeBanner.tsx:21` renders `t.app.managingProfileBanner` (with `t.app.managingProfile` / `t.app.currentProfileOption`, `en.ts:96-99`), **not** the `skills.*` variants.
- **Inputs / options:** Unused keys, verbatim: `skills.more` = `+{count} more`; `skills.profileSelector` = `Profile`; `skills.currentProfile` = `current ({name})`; `skills.managingProfile` = `Managing profile “{name}” — toggles apply to that profile, not this dashboard’s.` (note the curly quotes and the right single quote in `dashboard’s`).
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** `skills.more` was the "+N more" affordance for the tag/tool chip rows; the toolset card now prints every tool chip with no overflow cap, so nothing renders it.
- **Rebuild notes:** Either delete them or restore the `+{count} more` chip cap on the toolset cards, which currently wrap unboundedly for toolsets like `browser` (14 tools).

### Toolset configuration drawer — verbatim provider matrix (badges, tags, key prompts)  `id: web-b.toolset-provider-strings`
- **Surface:** Web dashboard
- **Where:** `/skills` → `Toolsets (27)` → any card's `Configure` → the drawer body. Each provider block renders, top to bottom: the provider name, its badge chip, the badge `Nous Portal` when `requires_nous_auth`, the tag sentence, one labelled password input per env var (label = the env var name in mono, `id="env-<KEY>"`, badge `Saved` when `is_set`), the `Get a key` external link when the var declares a URL, the `Save keys` button, and — for providers with a `post_setup` key — the sentence `This backend needs a one-time install (<key>). Runs on this host — may take a few minutes.` with `Run setup`. Verified live (`hermes_inv/web_crawl_b/skills_drawer.png`, state `skills:toolset-drawer`).
- **What it does:** `web-b.toolset-config-drawer` documents the mechanism and the routes; this entry transcribes every user-visible string the drawer renders for each of the 10 toolsets that declare a `TOOL_CATEGORIES` entry, so a checker can match badge/tag/placeholder text exactly.
- **How it works:** All of it is data from `GET /api/tools/toolsets/{name}/config` (`hermes_cli/web_routers/tools.py:233-345`), sourced from `hermes_cli/tools_config.py` `TOOL_CATEGORIES` merged with plugin-registered providers. `status` drives no colour of its own in this SPA — the drawer shows `✓ Selected` vs a `Select` button and renders the env inputs regardless; `needs_setup` is what makes the post-setup block appear. The `placeholder` of each password input is the env var's `prompt` when unset, and `•••••••• (saved — leave blank to keep)` once `is_set` is true.
- **Inputs / options:** Complete live matrix (toolset → providers → env vars):
  - **`web`** — active provider: none selected (active search backend `parallel`, active extract backend `parallel`)
    - `Nous Subscription` — tag `Managed Firecrawl billed to your subscription` — badge `subscription`; status `needs_auth`; `Nous Portal`; web.backend `firecrawl`; capabilities `search`, `extract`
    - `Firecrawl Self-Hosted` — tag `Run your own Firecrawl instance (Docker)` — badge `free · self-hosted`; status `needs_keys`; web.backend `firecrawl`; capabilities `search`, `extract`
      - env `FIRECRAWL_API_URL` — input placeholder / prompt `Your Firecrawl instance URL (e.g., http://localhost:3002)`
    - `Brave Search (Free)` — tag `Free-tier API key — 2k queries/mo, search only.` — badge `free`; status `needs_keys`; web.backend `brave-free`; capabilities `search`
      - env `BRAVE_SEARCH_API_KEY` — input placeholder / prompt `Brave Search API key (free tier)`, link `Get a key` → https://brave.com/search/api/
    - `DuckDuckGo (ddgs)` — tag `Search via the ddgs Python package — no API key (pair with any extract provider)` — badge `free · no key · search only`; status `needs_setup`; post_setup `ddgs`; web.backend `ddgs`; capabilities `search`
    - `Exa · Free (keyless)` — tag `Semantic + neural web search with content extraction on Exa's anonymous free tier. Rate-limited under burst load.` — badge `free · no key`; status `ready`; web.backend `exa`; capabilities `search`, `extract`
    - `Exa · Paid (API key)` — tag `Semantic + neural web search with content extraction via the Exa SDK. Unthrottled, guaranteed service.` — badge `paid`; status `needs_keys`; web.backend `exa`; capabilities `search`, `extract`
      - env `EXA_API_KEY` — input placeholder / prompt `Exa API key`, link `Get a key` → https://exa.ai
    - `Firecrawl` — tag `Full search + extract; supports keyless cloud, direct API, and Nous tool-gateway routing.` — badge `keyless/paid · optional gateway`; status `needs_keys`; web.backend `firecrawl`; capabilities `search`, `extract`
      - env `FIRECRAWL_API_KEY` — input placeholder / prompt `Firecrawl API key (optional; blank = keyless cloud or self-hosted)`, link `Get a key` → https://docs.firecrawl.dev/introduction
    - `Keenable · Free (keyless)` — tag `Independent web index for AI apps — fast search + page fetch on Keenable's anonymous free tier.` — badge `free · no key`; status `ready`; web.backend `keenable`; capabilities `search`, `extract`
    - `Keenable · Paid (API key)` — tag `Independent web index for AI apps. Keyed access with higher limits and guaranteed service.` — badge `paid`; status `needs_keys`; web.backend `keenable`; capabilities `search`, `extract`
      - env `KEENABLE_API_KEY` — input placeholder / prompt `Keenable API key`, link `Get a key` → https://keenable.ai
    - `Parallel · Free (keyless)` — tag `Objective-tuned search + page extraction on Parallel's anonymous free tier. Rate-limited under burst load.` — badge `free · no key`; status `ready`; web.backend `parallel`; capabilities `search`, `extract`
    - `Parallel · Paid (API key)` — tag `Objective-tuned search + parallel page extraction via the Parallel SDK. Unthrottled, guaranteed service.` — badge `paid`; status `needs_keys`; web.backend `parallel`; capabilities `search`, `extract`
      - env `PARALLEL_API_KEY` — input placeholder / prompt `Parallel API key`, link `Get a key` → https://parallel.ai
    - `SearXNG` — tag `Free, privacy-respecting metasearch. Point SEARXNG_URL at your instance.` — badge `free · self-hosted`; status `needs_keys`; web.backend `searxng`; capabilities `search`
      - env `SEARXNG_URL` — input placeholder / prompt `SearXNG instance URL (e.g. http://localhost:8080)`, link `Get a key` → https://searx.space/
    - `xAI Web Search (Grok)` — tag `Agentic web search via Grok's web_search tool — uses xAI Grok OAuth or XAI_API_KEY.` — badge `paid`; status `needs_auth`; post_setup `xai_grok`; web.backend `xai`; capabilities `search`
  - **`browser`** — active provider: `Browser Use`
    - `Local Browser` — tag `Headless Chromium, no API key needed` — badge `★ recommended · free`; status `ready`; post_setup `agent_browser`
    - `Lightpanda` — tag `Zig headless browser spawned by Hermes, text-only (no screenshots)` — badge `free · local · no Chromium`; status `needs_setup`; post_setup `lightpanda`
    - `Nous Subscription (Browser Use cloud)` — tag `Managed Browser Use billed to your subscription` — badge `subscription`; status `needs_auth`; post_setup `browserbase`; `Nous Portal`
    - `Camofox` — tag `Anti-detection browser (Firefox/Camoufox)` — badge `free · local`; status `needs_keys`; post_setup `camofox`
      - env `CAMOFOX_URL` — input placeholder / prompt `Camofox server URL`, default `http://localhost:9377`, link `Get a key` → https://github.com/jo-inc/camofox-browser
    - `Browser Use` — tag `New SOTA web harness (CLI 3.0)` — badge `free · local · cloud`; status `ready`; post_setup `browser_use_cli`
    - `Browserbase` — tag `Cloud browser with stealth and proxies` — badge `paid`; status `needs_keys`; post_setup `browserbase`
      - env `BROWSERBASE_API_KEY` — input placeholder / prompt `Browserbase API key`, link `Get a key` → https://browserbase.com
      - env `BROWSERBASE_PROJECT_ID` — input placeholder / prompt `Browserbase project ID`
    - `Firecrawl` — tag `Cloud browser with remote execution` — badge `paid`; status `needs_keys`; post_setup `browserbase`
      - env `FIRECRAWL_API_KEY` — input placeholder / prompt `Firecrawl API key`, link `Get a key` → https://firecrawl.dev
  - **`image_gen`** — active provider: none selected
    - `Nous Subscription` — tag `Managed FAL image generation billed to your subscription` — badge `subscription`; status `needs_auth`; `Nous Portal`
    - `DeepInfra` — tag `FLUX, Qwen-Image, … — live catalog from api.deepinfra.com` — badge `paid`; status `needs_keys`
      - env `DEEPINFRA_API_KEY` — input placeholder / prompt `DeepInfra API key`, link `Get a key` → https://deepinfra.com/dash/api_keys
    - `FAL.ai` — tag `Pick from flux-2-klein, flux-2-pro, gpt-image, nano-banana-2, nano-banana-pro, etc. — text-to-image & image editing` — badge `paid`; status `needs_keys`
      - env `FAL_KEY` — input placeholder / prompt `FAL API key`, link `Get a key` → https://fal.ai/dashboard/keys
    - `Krea` — tag `Krea 2 foundation model — Medium ($0.03), Large ($0.06), Medium Turbo ($0.015). Style transfer, moodboards, reference-guided generation. Direct key or managed Nous Subscription gateway.` — badge `paid`; status `needs_keys`
      - env `KREA_API_KEY` — input placeholder / prompt `Krea API key`, link `Get a key` → https://www.krea.ai/settings/api-tokens
    - `Nous Portal (image)` — tag `Reference-grounded image generation via Nous Portal (OpenRouter-backed)` — badge `subscription`; status `ready`
    - `OpenAI` — tag `gpt-image-2 at low/medium/high quality tiers — text-to-image & image editing` — badge `paid`; status `needs_keys`
      - env `OPENAI_API_KEY` — input placeholder / prompt `OpenAI API key`, link `Get a key` → https://platform.openai.com/api-keys
    - `OpenAI (Codex auth)` — tag `gpt-image-2 via ChatGPT/Codex OAuth — no API key required; supports text and image inputs` — badge `free`; status `ready`
    - `OpenRouter (image)` — tag `Gemini Flash Image, gpt-image-2, Krea 2, Qwen Image 3 & more via OpenRouter; uses OPENROUTER_API_KEY` — badge `paid`; status `needs_keys`
      - env `OPENROUTER_API_KEY` — input placeholder / prompt `OpenRouter API key`, link `Get a key` → https://openrouter.ai/keys
    - `xAI Grok Imagine (image)` — tag `grok-imagine-image - text-to-image & image editing; uses xAI Grok OAuth or XAI_API_KEY. xAI Imagine storage is enabled so generated media gets a reusable public URL without an automatic expiry. xAI may bill for stored files and public URL hosting. Disable this with `image_gen.xai.storage.enabled: false` or set `expires_after` to change the retention.` — badge `paid`; status `needs_auth`; post_setup `xai_grok`
  - **`video_gen`** — active provider: none selected
    - `Nous Subscription` — tag `Managed FAL video generation billed to your subscription` — badge `subscription`; status `needs_auth`; `Nous Portal`
    - `DeepInfra` — tag `Wan, p-video, … — live catalog from api.deepinfra.com; text-to-video & image-to-video` — badge `paid`; status `needs_keys`
      - env `DEEPINFRA_API_KEY` — input placeholder / prompt `DeepInfra API key`, link `Get a key` → https://deepinfra.com/dash/api_keys
    - `FAL` — tag `LTX, Pixverse, Seedance 2.0/2.5/Mini, Veo 3.1, MiniMax H3, FLUX 3, Kling 4K, Happy Horse, Grok Imagine, Gemini Omni — text-to-video & image-to-video` — badge `paid`; status `needs_keys`
      - env `FAL_KEY` — input placeholder / prompt `FAL.ai API key`, link `Get a key` → https://fal.ai/dashboard/keys
    - `xAI Grok Imagine` — tag `grok-imagine-video for text/reference; grok-imagine-video-1.5 for image-to-video; edit/extend: pass the stored public HTTPS MP4 (`video` / `public_url` from a prior Imagine result); uses xAI Grok OAuth or XAI_API_KEY. xAI Imagine storage is enabled so generated media gets a reusable public URL without an automatic expiry. xAI may bill for stored files and public URL hosting. Disable this with `video_gen.xai.storage.enabled: false` or set `expires_after` to change the retention.` — badge `paid`; status `needs_auth`; post_setup `xai_grok`
  - **`x_search`** — active provider: none selected
    - `xAI Grok OAuth (SuperGrok / Premium+)` — tag `Browser login at accounts.x.ai — no API key required` — badge `subscription`; status `needs_auth`; post_setup `xai_grok`
    - `xAI API key` — tag `Direct xAI API billing via XAI_API_KEY` — badge `paid`; status `needs_keys`
      - env `XAI_API_KEY` — input placeholder / prompt `xAI API key`, link `Get a key` → https://console.x.ai/
  - **`tts`** — active provider: `Microsoft Edge TTS`
    - `Microsoft Edge TTS` — tag `Good quality, no API key needed` — badge `★ recommended · free`; status `ready`; tts.provider `edge`
    - `Nous Subscription` — tag `Managed OpenAI TTS billed to your subscription` — badge `subscription`; status `needs_auth`; `Nous Portal`; tts.provider `openai`
    - `OpenAI TTS` — tag `High quality voices` — badge `paid`; status `needs_keys`; tts.provider `openai`
      - env `VOICE_TOOLS_OPENAI_KEY` — input placeholder / prompt `OpenAI API key`, link `Get a key` → https://platform.openai.com/api-keys
    - `xAI TTS` — tag `Grok voices — uses xAI Grok OAuth or XAI_API_KEY` — badge (empty); status `needs_auth`; post_setup `xai_grok`; tts.provider `xai`
    - `ElevenLabs` — tag `Most natural voices` — badge `paid`; status `needs_keys`; tts.provider `elevenlabs`
      - env `ELEVENLABS_API_KEY` — input placeholder / prompt `ElevenLabs API key`, link `Get a key` → https://elevenlabs.io/app/settings/api-keys
    - `Mistral (Voxtral TTS)` — tag `Multilingual, native Opus` — badge `paid`; status `needs_keys`; tts.provider `mistral`
      - env `MISTRAL_API_KEY` — input placeholder / prompt `Mistral API key`, link `Get a key` → https://console.mistral.ai/
    - `Google Gemini TTS` — tag `30 prebuilt voices, controllable via prompts` — badge `preview`; status `needs_keys`; tts.provider `gemini`
      - env `GEMINI_API_KEY` — input placeholder / prompt `Gemini API key`, link `Get a key` → https://aistudio.google.com/app/apikey
    - `KittenTTS` — tag `Lightweight local ONNX TTS (~25MB), no API key` — badge `local · free`; status `needs_setup`; post_setup `kittentts`; tts.provider `kittentts`
    - `Piper` — tag `Local neural TTS, 44 languages (voices ~20-90MB)` — badge `local · free`; status `needs_setup`; post_setup `piper`; tts.provider `piper`
    - `DeepInfra TTS` — tag `Chatterbox, Qwen3-TTS, … — live catalog from api.deepinfra.com` — badge `paid`; status `needs_keys`; tts.provider `deepinfra`
      - env `DEEPINFRA_API_KEY` — input placeholder / prompt `DeepInfra API key`, link `Get a key` → https://deepinfra.com/dash/api_keys
  - **`stt`** — active provider: `Local Whisper`
    - `Local Whisper` — tag `faster-whisper on-device, no API key` — badge `★ recommended · free`; status `ready`; post_setup `faster_whisper`
    - `Nous Subscription` — tag `Managed OpenAI transcription billed to your subscription` — badge `subscription`; status `needs_auth`; `Nous Portal`
    - `OpenAI` — tag `whisper-1, gpt-4o-transcribe, gpt-transcribe` — badge `paid`; status `needs_keys`
      - env `VOICE_TOOLS_OPENAI_KEY` — input placeholder / prompt `OpenAI API key`, link `Get a key` → https://platform.openai.com/api-keys
    - `Groq` — tag `Whisper large-v3 family — very fast` — badge `free tier`; status `needs_keys`
      - env `GROQ_API_KEY` — input placeholder / prompt `Groq API key`, link `Get a key` → https://console.groq.com/keys
    - `xAI` — tag `grok-stt — uses xAI Grok OAuth or XAI_API_KEY` — badge (empty); status `needs_auth`; post_setup `xai_grok`
    - `ElevenLabs Scribe` — tag `scribe_v2 — diarization + audio-event tagging` — badge `paid`; status `needs_keys`
      - env `ELEVENLABS_API_KEY` — input placeholder / prompt `ElevenLabs API key`, link `Get a key` → https://elevenlabs.io/app/settings/api-keys
    - `DeepInfra` — tag `Live STT catalog from api.deepinfra.com` — badge `paid`; status `needs_keys`
      - env `DEEPINFRA_API_KEY` — input placeholder / prompt `DeepInfra API key`, link `Get a key` → https://deepinfra.com/dash/api_keys
  - **`homeassistant`** — active provider: none selected
    - `Home Assistant` — tag `REST API integration` — badge (empty); status `needs_keys`
      - env `HASS_TOKEN` — input placeholder / prompt `Home Assistant Long-Lived Access Token`
      - env `HASS_URL` — input placeholder / prompt `Home Assistant URL`, default `http://homeassistant.local:8123`
  - **`spotify`** — active provider: none selected
    - `Spotify Web API` — tag `PKCE OAuth — opens the setup wizard` — badge (empty); status `needs_setup`; post_setup `spotify`
  - **`computer_use`** — active provider: none selected
    - `cua-driver (background)` — tag `Background computer-use via cua-driver — does NOT steal your cursor or focus. Works with any model.` — badge `★ recommended · free · local`; status `needs_setup`; post_setup `cua_driver`
  The remaining 17 toolsets (`terminal`, `file`, `code_execution`, `vision`, `video`, `skills`, `todo`, `memory`, `context_engine`, `session_search`, `clarify`, `delegation`, `cronjob`, `discord`, `discord_admin`, `yuanbao`, `a2a`) return `has_category: false` and the drawer body shows only `This toolset has no configurable backends — toggle it on or off above. It works with no provider selection or API keys.`
- **Outputs / side effects:** `Select` → `PUT /api/tools/toolsets/{name}/provider` (writes `web.backend` / `tts.provider` / `image_gen.provider` / `video_gen.provider` / `stt.provider` / `browser.*`); `Save keys` → `PUT /api/tools/toolsets/{name}/env` (writes the profile `.env`); `Run setup` → `POST /api/tools/toolsets/{name}/post-setup` (spawns `hermes tools post-setup <key>`).
- **Config / env:** Every `env` key listed above, written to `<profile>/.env`. Provider selection keys as above.
- **Edge cases / guards:** `xAI Grok Imagine (image)` and `xAI Grok Imagine` (video) tags both carry a storage/billing warning naming the config keys `image_gen.xai.storage.enabled` / `video_gen.xai.storage.enabled` and `expires_after` — these are the only provider tags that document config keys inline. `Camofox` and `Home Assistant` are the only providers whose env vars ship a `default` (`http://localhost:9377`, `http://homeassistant.local:8123`) which the input shows as its placeholder-adjacent hint. `spotify` and `computer_use` have exactly one provider each and no env vars — they exist purely to expose `Run setup`.
- **Rebuild notes:** Keep the provider catalog as data (name, badge, tag, env schema, post-setup key, capabilities) so the drawer is a pure renderer; that is what makes plugin-registered providers (e.g. `web-ddgs`) appear with no UI change. A better version would show which provider is active per capability (`search` vs `extract`) — the API already returns `active_search_backend` / `active_extract_backend` but this SPA ignores both.

### Memory provider settings — the eight live field schemas  `id: web-b.plugins-memory-provider-schemas`
- **Surface:** Web dashboard
- **Where:** `/plugins` → card `Runtime provider plugins` → `Memory provider` select (`id="mem-provider"`) → picking any non-built-in option renders the bordered settings form below the select (labels rendered upper-case by CSS, e.g. selecting `holographic` shows `DB PATH`, `AUTO EXTRACT`, `DEFAULT TRUST`, `HRR DIM`). Verified live (`hermes_inv/web_crawl_b/plugins_mem_holo.png`, state `plugins:mem-holographic`).
- **What it does:** `web-b.plugins-memory-provider-fields` documents the generic renderer; this entry transcribes the actual field schemas the eight bundled memory providers declare, because those labels, options, ranges and help sentences are the visible content of the form.
- **How it works:** `GET /api/memory/providers/{name}/config` (`hermes_cli/web_server.py:7176-7196`) returns `{name, label, fields[], setup}`; `fields[]` comes from each provider plugin's declared config schema. The SPA seeds `memoryValues` from `fieldInitialValue` (secrets always blank, booleans coerced, everything else stringified) and hides a field whose `when` map does not match the current values (`fieldIsVisible`, `PluginsPage.tsx:57-63`). Only visible fields are submitted by `Save memory provider` / `Install provider dependencies`. Field label text is the API's `label` (title-cased key), the DOM id is `memory-<key>`; `select` renders a `Select`, `boolean` a `Switch`, `integer`/`number` a numeric `Input` honouring `minimum`/`maximum`/`step` (integer step defaults to 1), `secret` a password `Input` with an eye toggle (`aria-label="Show secret"` / `"Hide secret"`) and a `set` badge when already stored.
- **Inputs / options:** Live schemas (provider → fields):
  - **`byterover`** — select option `byterover`, drawer label `Byterover`; setup: pip none; external `brv` (install `curl -fsSL https://byterover.dev/install.sh | sh`, check `brv --version`); required_env none; `dependencies_installed: false`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; link `Open ↗` → https://app.byterover.dev — description `ByteRover API key (optional, for cloud sync)`
    - `auto_extract` — label `Auto Extract` (`id="memory-auto_extract"`) — kind `select`; options `true`, `false` — description `Automatically curate completed turns and compression/memory hooks`
  - **`hindsight`** — select option `hindsight`, drawer label `Hindsight`; setup: pip `hindsight-client>=0.6.1`; external none; required_env none; `dependencies_installed: false`
    - `mode` — label `Mode` (`id="memory-mode"`) — kind `select`; options `cloud`, `local_embedded`, `local_external` — description `Connection mode`
    - `api_url` — label `Api Url` (`id="memory-api_url"`) — kind `text`; shown when `mode=cloud` — description `Hindsight Cloud API URL`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; shown when `mode=cloud`; link `Open ↗` → https://ui.hindsight.vectorize.io — description `Hindsight Cloud API key`
    - `api_url` — label `Api Url` (`id="memory-api_url"`) — kind `text`; shown when `mode=local_external` — description `Hindsight API URL`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; shown when `mode=local_external` — description `API key (optional)`
    - `llm_provider` — label `Llm Provider` (`id="memory-llm_provider"`) — kind `select`; shown when `mode=local_embedded`; options `openai`, `anthropic`, `gemini`, `groq`, `openrouter`, `minimax`, `ollama`, `lmstudio`, `openai_compatible` — description `LLM provider`
    - `llm_base_url` — label `Llm Base Url` (`id="memory-llm_base_url"`) — kind `text`; shown when `mode=local_embedded`, `llm_provider=openai_compatible` — description `Endpoint URL (e.g. http://192.168.1.10:8080/v1)`
    - `llm_api_key` — label `Llm Api Key` (`id="memory-llm_api_key"`) — kind `secret`; shown when `mode=local_embedded` — description `LLM API key (optional for openai_compatible)`
    - `llm_model` — label `Llm Model` (`id="memory-llm_model"`) — kind `text`; shown when `mode=local_embedded` — description `LLM model`
    - `bank_id` — label `Bank Id` (`id="memory-bank_id"`) — kind `text` — description `Memory bank name (static fallback when bank_id_template is unset)`
    - `bank_id_template` — label `Bank Id Template` (`id="memory-bank_id_template"`) — kind `text` — description `Optional template to derive bank_id dynamically. Placeholders: {profile}, {workspace}, {platform}, {user}, {session}. Example: hermes-{profile}`
    - `bank_mission` — label `Bank Mission` (`id="memory-bank_mission"`) — kind `text` — description `Mission/purpose description for the memory bank`
    - `bank_retain_mission` — label `Bank Retain Mission` (`id="memory-bank_retain_mission"`) — kind `text` — description `Custom extraction prompt for memory retention`
    - `recall_budget` — label `Recall Budget` (`id="memory-recall_budget"`) — kind `select`; options `low`, `mid`, `high` — description `Recall thoroughness`
    - `memory_mode` — label `Memory Mode` (`id="memory-memory_mode"`) — kind `select`; options `hybrid`, `context`, `tools` — description `Memory integration mode`
    - `recall_prefetch_method` — label `Recall Prefetch Method` (`id="memory-recall_prefetch_method"`) — kind `select`; options `recall`, `reflect` — description `Auto-recall method`
    - `retain_tags` — label `Retain Tags` (`id="memory-retain_tags"`) — kind `text` — description `Default tags applied to retained memories (comma-separated)`
    - `observation_scopes` — label `Observation Scopes` (`id="memory-observation_scopes"`) — kind `text` — description `How observations are scoped during consolidation: 'combined' (default — one pass over all tags), 'per_tag' (one isolated observation per tag), 'all_combinations' (every tag subset — expensive), or a JSON list of tag-lists for explicit custom scopes. Empty uses Hindsight's 'combined' default.`
    - `retain_source` — label `Retain Source` (`id="memory-retain_source"`) — kind `text` — description `Metadata source value attached to retained memories (identifies the client that stored them)`
    - `retain_user_prefix` — label `Retain User Prefix` (`id="memory-retain_user_prefix"`) — kind `text` — description `Label used before user turns in retained transcripts`
    - `retain_assistant_prefix` — label `Retain Assistant Prefix` (`id="memory-retain_assistant_prefix"`) — kind `text` — description `Label used before assistant turns in retained transcripts`
    - `recall_tags` — label `Recall Tags` (`id="memory-recall_tags"`) — kind `text` — description `Tags to filter when searching memories (comma-separated)`
    - `recall_tags_match` — label `Recall Tags Match` (`id="memory-recall_tags_match"`) — kind `select`; options `any`, `all`, `any_strict`, `all_strict` — description `Tag matching mode for recall`
    - `recall_types` — label `Recall Types` (`id="memory-recall_types"`) — kind `text` — description `Fact types to surface on recall — applies to both auto-recall and the hindsight_recall tool (comma-separated or list). Defaults to observation-only — observations are Hindsight's consolidated, deduplicated, evidence-grounded knowledge layer; raw world/experience facts are the supporting evidence observations already summarize. Set to e.g. 'observation,world,experience' to also include raw facts.`
    - `auto_recall` — label `Auto Recall` (`id="memory-auto_recall"`) — kind `boolean` — description `Automatically recall memories before each turn`
    - `recall_sync` — label `Recall Sync` (`id="memory-recall_sync"`) — kind `boolean` — description `Recall synchronously against the current message before each turn (higher relevance, adds recall latency to the turn). Default off: recall runs in the background and is injected on the next turn.`
    - `recall_indicator` — label `Recall Indicator` (`id="memory-recall_indicator"`) — kind `boolean` — description `Show a '👁️ Hindsight — recalled N memories' status line when auto-recall injects memory (turn off for customer-facing agents)`
    - `retain_indicator` — label `Retain Indicator` (`id="memory-retain_indicator"`) — kind `boolean` — description `Show a '👁️ Hindsight — saving to memory…' status line when a turn is saved to memory (turn off for customer-facing agents)`
    - `auto_retain` — label `Auto Retain` (`id="memory-auto_retain"`) — kind `boolean` — description `Automatically retain conversation turns`
    - `retain_every_n_turns` — label `Retain Every N Turns` (`id="memory-retain_every_n_turns"`) — kind `integer` — description `Retain every N turns (1 = every turn)`
    - `retain_async` — label `Retain Async` (`id="memory-retain_async"`) — kind `boolean` — description `Process retain asynchronously on the Hindsight server`
    - `prefetch_waits_for_retain` — label `Prefetch Waits For Retain` (`id="memory-prefetch_waits_for_retain"`) — kind `boolean` — description `Have the background next-turn prefetch wait for the just-completed retain to become recall-visible on the server (local queue drain + async operation completion) before recalling, so recall includes the just-completed turn (runs off the reply path, adds no response latency)`
    - `prefetch_retain_drain_timeout` — label `Prefetch Retain Drain Timeout` (`id="memory-prefetch_retain_drain_timeout"`) — kind `number` — description `Max seconds the background prefetch waits for the retain to become recall-visible (queue drain + server-side completion) before recalling anyway`
    - `retain_context` — label `Retain Context` (`id="memory-retain_context"`) — kind `text` — description `Context label for retained memories`
    - `recall_max_tokens` — label `Recall Max Tokens` (`id="memory-recall_max_tokens"`) — kind `integer` — description `Maximum tokens for recall results`
    - `recall_max_input_chars` — label `Recall Max Input Chars` (`id="memory-recall_max_input_chars"`) — kind `integer` — description `Maximum input query length for auto-recall`
    - `recall_prompt_preamble` — label `Recall Prompt Preamble` (`id="memory-recall_prompt_preamble"`) — kind `text` — description `Custom preamble for recalled memories in context`
    - `timeout` — label `Timeout` (`id="memory-timeout"`) — kind `integer` — description `API request timeout in seconds`
    - `idle_timeout` — label `Idle Timeout` (`id="memory-idle_timeout"`) — kind `integer`; shown when `mode=local_embedded` — description `Embedded daemon idle timeout in seconds (0 disables auto-shutdown)`
    - `port_health_grace_timeout` — label `Port Health Grace Timeout` (`id="memory-port_health_grace_timeout"`) — kind `text`; shown when `mode=local_embedded` — description `Seconds to wait for a slow daemon /health before treating it as stale (raise on busy/low-resource hosts; blank uses the 30s default)`
  - **`holographic`** — select option `holographic`, drawer label `Holographic`; setup: pip none; external none; required_env none; `dependencies_installed: true`
    - `db_path` — label `Db Path` (`id="memory-db_path"`) — kind `text` — description `SQLite database path`
    - `auto_extract` — label `Auto Extract` (`id="memory-auto_extract"`) — kind `select`; options `true`, `false` — description `Auto-extract facts at session end`
    - `default_trust` — label `Default Trust` (`id="memory-default_trust"`) — kind `text` — description `Default trust score for new facts`
    - `hrr_dim` — label `Hrr Dim` (`id="memory-hrr_dim"`) — kind `text` — description `HRR vector dimensions`
  - **`honcho`** — select option `honcho`, drawer label `Honcho`; setup: pip `honcho-ai`; external none; required_env none; `dependencies_installed: false`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; link `Open ↗` → https://app.honcho.dev — description `Honcho API key`
    - `baseUrl` — label `Baseurl` (`id="memory-baseUrl"`) — kind `text` — description `Honcho base URL (for self-hosted)`
  - **`mem0`** — select option `mem0`, drawer label `Mem0`; setup: pip `mem0ai>=2.0.10,<3`; external none; required_env none; `dependencies_installed: false`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; **required**; link `Open ↗` → https://app.mem0.ai — description `Mem0 Platform API key`
    - `host` — label `Host` (`id="memory-host"`) — kind `text` — description `Self-hosted Mem0 server URL (leave blank for cloud)`
    - `user_id` — label `User Id` (`id="memory-user_id"`) — kind `text` — description `User identifier`
    - `agent_id` — label `Agent Id` (`id="memory-agent_id"`) — kind `text` — description `Agent identifier`
    - `rerank` — label `Rerank` (`id="memory-rerank"`) — kind `select`; options `true`, `false` — description `Enable reranking for recall`
  - **`openviking`** — select option `openviking`, drawer label `Openviking`; setup: pip `httpx`; external none; required_env none; `dependencies_installed: true`
    - `endpoint` — label `Endpoint` (`id="memory-endpoint"`) — kind `text`; **required** — description `OpenViking server URL`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret` — description `OpenViking API key (recommended; only leave blank for an explicitly unauthenticated local development server)`
    - `account` — label `Account` (`id="memory-account"`) — kind `text` — description `Advanced local identity override (leave blank for user API keys)`
    - `user` — label `User` (`id="memory-user"`) — kind `text` — description `Advanced local user override (leave blank for user API keys)`
    - `agent` — label `Agent` (`id="memory-agent"`) — kind `text` — description `Optional peer ID for separate assistant context. Uses user memory when no peer is configured.`
    - `recall_limit` — label `Recall Limit` (`id="memory-recall_limit"`) — kind `integer`; minimum `1`; maximum `100` — description `Maximum memories injected by automatic recall`
    - `recall_score_threshold` — label `Recall Score Threshold` (`id="memory-recall_score_threshold"`) — kind `number`; minimum `0.0`; maximum `1.0`; step `0.01` — description `Minimum relevance score for automatic recall`
    - `recall_max_injected_chars` — label `Recall Max Injected Chars` (`id="memory-recall_max_injected_chars"`) — kind `integer`; minimum `100`; maximum `50000` — description `Maximum total characters injected by recall`
    - `profile_token_budget` — label `Profile Token Budget` (`id="memory-profile_token_budget"`) — kind `integer`; minimum `500`; maximum `50000` — description `Maximum session-start memory tokens injected`
    - `recall_timeout_seconds` — label `Recall Timeout Seconds` (`id="memory-recall_timeout_seconds"`) — kind `number`; minimum `0.25`; maximum `60.0`; step `0.25` — description `Total timeout for recall (seconds)`
    - `recall_request_timeout_seconds` — label `Recall Request Timeout Seconds` (`id="memory-recall_request_timeout_seconds"`) — kind `number`; minimum `0.25`; maximum `60.0`; step `0.25` — description `Per-request timeout for recall (seconds)`
    - `recall_full_read_limit` — label `Recall Full Read Limit` (`id="memory-recall_full_read_limit"`) — kind `integer`; minimum `0`; maximum `100` — description `Max full L2 content reads per recall`
    - `recall_prefer_abstract` — label `Recall Prefer Abstract` (`id="memory-recall_prefer_abstract"`) — kind `boolean` — description `Use abstracts instead of full L2 reads`
    - `recall_resources` — label `Recall Resources` (`id="memory-recall_resources"`) — kind `boolean` — description `Include resources in recall`
  - **`retaindb`** — select option `retaindb`, drawer label `Retaindb`; setup: pip `requests`; external none; required_env `RETAINDB_API_KEY`; `dependencies_installed: true`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; **required**; link `Open ↗` → https://retaindb.com — description `RetainDB API key`
    - `base_url` — label `Base Url` (`id="memory-base_url"`) — kind `text` — description `API endpoint`
    - `project` — label `Project` (`id="memory-project"`) — kind `text` — description `Project identifier (optional — uses 'default' project if not set)`
  - **`supermemory`** — select option `supermemory`, drawer label `Supermemory`; setup: pip `supermemory`; external none; required_env none; `dependencies_installed: false`
    - `api_key` — label `Api Key` (`id="memory-api_key"`) — kind `secret`; **required**; link `Open ↗` → http://app.supermemory.ai/integrations?connect=hermes — description `Supermemory API key`
  Note `hindsight` declares `api_url` and `api_key` **twice** with different `when` guards (`mode=cloud` and `mode=local_external`) — the renderer keys the form state by `key`, so the two pairs share one value and only one pair is ever visible at a time.
- **Outputs / side effects:** `PUT /api/memory/providers/{name}/config` body `{values}` writes non-secret fields into `config.yaml` under the provider's namespace and secrets into the profile `.env`, then gates activation through `_require_memory_provider_ready(name)` before setting `memory.provider`. `POST /api/memory/providers/{name}/setup` runs the `setup` block's pip/external installs and returns per-step results.
- **Config / env:** `memory.provider`, `memory.<provider>.<field>`; secrets as provider-declared env vars (e.g. `RETAINDB_API_KEY`, which `retaindb` also lists in `required_env`).
- **Edge cases / guards:** Only `mem0`, `openviking`, `retaindb` and `supermemory` mark a field `required` (`api_key`, `endpoint`, `api_key`, `api_key` respectively); the rest accept an empty form. `holographic` and `openviking` and `retaindb` report `dependencies_installed: true` on this install, so their setup hint is hidden; `byterover`, `hindsight`, `honcho`, `mem0`, `supermemory` show `Install provider dependencies`. `openviking` is the only provider with numeric ranges (`recall_limit` 1–100, `recall_score_threshold` 0.0–1.0 step 0.01, `recall_max_injected_chars` 100–50000, `profile_token_budget` 500–50000, `recall_timeout_seconds` / `recall_request_timeout_seconds` 0.25–60.0 step 0.25, `recall_full_read_limit` 0–100).
- **Rebuild notes:** Declare provider settings as a JSON schema with `kind`, `when`, `required`, `options`, `minimum/maximum/step`, `url` and `description`, and render generically — that is what lets a new memory plugin ship a full settings UI with no dashboard change. A better version would namespace duplicate keys per `when` branch, validate `required` client-side before enabling Save, and offer a "test connection" per provider.

### Plugins page — remaining catalog-only string  `id: web-b.plugins-unused-strings-2`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts:418` — `pluginsPage.versionBadge` = `Version`.
- **What it does:** Completes the dead-key list started in `web-b.plugins-unused-strings` (which covers `rescanHeading`, `runtimeHeading`, `saveProviders`, `headline`, `providersHint`, `inactive`).
- **How it works:** The installed-plugin row renders the version as the literal template `` `v${row.version || "—"}` `` instead of `${t.pluginsPage.versionBadge} ${row.version}`, so the key is never read (grep for `t.pluginsPage.versionBadge` across `web/src` returns nothing, while its sibling `pluginsPage.sourceBadge` = `Source` **is** used for the `Source: <source>` badge).
- **Inputs / options:** n/a
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** The complete unused `pluginsPage` set at v2026.8.31 is therefore: `headline`, `inactive`, `providersHint`, `rescanHeading`, `runtimeHeading`, `saveProviders`, `versionBadge` (7 of 36 keys).
- **Rebuild notes:** Use the key or delete it; a `Version 1.2.3` badge would translate, `v1.2.3` does not need to.

### DOM contract of the five pages — element ids, label bindings and the `Select` widget  `id: web-b.dom-id-index`
- **Surface:** Web dashboard
- **Where:** All five routes. Every `<Label htmlFor=…>` in this shard binds to one of the ids below; the visible label text is rendered upper-case by the theme's CSS (`NAME (OPTIONAL)`, `DELIVER TO`, `GIT URL OR OWNER/REPO`, `SKILL.MD`, …) while the DOM's text node keeps the sentence case listed in the earlier entries.
- **What it does:** Gives a rebuilder (and an automated checker) the exact stable handles the pages expose, and records that the `Select` control is **not** a native `<select>`.
- **How it works:** `Select` from `@nous-research/ui` renders a `<div id=…>` wrapper containing a `<button role="combobox">` whose text is the current option label; opening it renders a listbox of `[role="option"]` nodes. Consequences observed live: `page.selectOption('#cron-schedule-mode', …)` fails with `Element is not a <select> element`, and each option's text appears twice in a DOM dump (button label + option node). `Switch` renders `<button role="switch">`; the segmented filters on `/logs` and `/cron` render `<button role="radio">`; the cron/skills/toolset checkbox pickers render real `<input type="checkbox">` with the label text as a sibling (no `for` attribute, so they are label-wrapped). Modals set `role="dialog"` + `aria-labelledby` pointing at the heading id.
- **Inputs / options:** Complete id map:
  - `/logs`: switch `logs-auto-refresh` (`Auto-refresh`); the four filter groups are `role="radiogroup"` inside `role="toolbar" aria-label="Logs"` and have no ids; header icon button `aria-label="Refresh"`.
  - `/cron` list: select `cron-profile-filter` (`Profile`).
  - `/cron` create modal: `aria-labelledby="create-cron-title"`, heading id `create-cron-title`; select `cron-profile` (`Profile`); `cron-name`, `cron-prompt`, `cron-deliver`, `cron-skills`; advanced (`<details>` summary `Advanced fields`): `cron-advanced-provider`, `cron-advanced-model`, `cron-advanced-base-url`, `cron-advanced-script`, `cron-advanced-workdir`, `cron-advanced-context-from`, `cron-advanced-toolsets` (the two advanced checkboxes — `no_agent…` and `continuity…` — are label-wrapped and id-less).
  - `/cron` edit modal: `aria-labelledby="edit-cron-title"`, heading id `edit-cron-title`; the same fields with the `edit-cron` / `edit-cron-advanced` prefixes (`edit-cron-name`, `edit-cron-prompt`, `edit-cron-deliver`, `edit-cron-skills`, `edit-cron-advanced-provider`, …). There is **no** `edit-cron-profile` — the edit modal reuses the job's own profile.
  - ScheduleBuilder (rendered inside both modals, ids **not** prefixed, so create and edit share them): `cron-schedule-mode` (`Schedule`), `cron-interval-value` (`Every`), `cron-interval-unit` (`Unit`), `cron-daily-time` (`Time of day`), `cron-weekly-time` (`Time of day`), `cron-month-day` (`Day of month`), `cron-monthly-time` (`Time of day`), `cron-once-at` (`Run at`), `cron-custom-expr` (`Cron expression`). The weekday toggles are `<button aria-pressed>` inside `role="group" aria-label="Days of week"` with no ids.
  - `/skills`: header search input has no id; skill editor dialog `skill-editor-name`, `skill-editor-category`, `skill-editor-content`; toolset drawer env inputs `env-<ENV_VAR_NAME>` (e.g. `env-FIRECRAWL_API_URL`, `env-BRAVE_SEARCH_API_KEY`, `env-EXA_API_KEY`, `env-FIRECRAWL_API_KEY`, `env-KEENABLE_API_KEY`, `env-PARALLEL_API_KEY`, `env-SEARXNG_URL` for `web`); the drawer's toolset switch is `aria-label="Enable toolset for CLI"` on this install (the platform label is interpolated).
  - `/plugins`: `mem-provider` (`Memory provider`), `ctx-engine` (`Context engine`), `install-url` (`Git URL or owner/repo`), dynamic memory fields `memory-<field key>` (live for `holographic`: `memory-db_path`, `memory-auto_extract`, `memory-default_trust`, `memory-hrr_dim`).
  - `/mcp`: add dialog `aria-labelledby="create-mcp-title"`, heading id `create-mcp-title`; `mcp-name`, `mcp-transport`, `mcp-url`, `mcp-auth`, `mcp-bearer-token`, `mcp-command`, `mcp-args`, `mcp-env`. Catalog credential dialog `aria-labelledby="install-mcp-title"`, heading id `install-mcp-title`; one input per required env var, `install-env-<ENV_VAR_NAME>`.
- **Outputs / side effects:** none — this is structure, not behaviour.
- **Config / env:** n/a.
- **Edge cases / guards:** On `/mcp` the only catalog card that renders a bootstrap disclosure is `n8n`, whose summary reads `Bootstrap commands (2)`; every other card shows only `Setup notes`. Because ScheduleBuilder does not prefix its ids, opening the edit modal while the create modal is mounted would duplicate `cron-schedule-mode` in the document; in practice `CronPage` renders at most one modal at a time so the collision is unreachable. Automation-driven tests must click the combobox and then an `[role="option"]`, not call `selectOption`.
- **Rebuild notes:** Keep stable, prefixed ids on every control (including the schedule picker) and expose native form semantics or a documented ARIA combobox; the current mix costs every integration test an extra interaction step.

### Toast and inline-error string index (five pages)  `id: web-b.toast-string-index`
- **Surface:** Web dashboard
- **Where:** Transient toasts (top-of-page `useToast`) and inline error text on `/logs`, `/cron`, `/skills`, `/plugins`, `/mcp`.
- **What it does:** One place a checker can enumerate every message these pages can emit. Most are already described in the entry that owns the action; three literals were not covered anywhere and are marked **(new)**.
- **How it works:** All are produced by `showToast(message, "success" | "error")` from `web/src/hooks` (rendered by the shared `Toast` in the app shell) except the `/logs` red banner, which is inline JSX. Messages built with template literals interpolate server error strings (`${e}`), so a backend `HTTPException` detail is shown verbatim to the user.
- **Inputs / options:** Complete literal inventory, by file:
  - `LogsPage.tsx` — inline banner only: `String(err)` of the fetch failure (no toast on this page).
  - `CronPage.tsx` — `Prompt & Schedule (cron expression) required` (composed from `t.cron.prompt` + `t.cron.schedule`, `:704`, `:732`); `no_agent jobs require a script` (`:707`, `:735`); `Create ✓` / `Saved changes ✓` (`${label} ✓`); `Pause: "<job title ≤30>"`, `Resume: "<job title ≤30>"`, `Delete: "<job title ≤30>"`, `Trigger now ✓`; `Failed to save: ${e}` (`t.config.failedToSave`); `Error: ${e}` (`t.status.error`); `Loading...` (`t.common.loading`) on list-load failure.
  - `AutomationBlueprints.tsx` — `${blueprint.title} scheduled — <schedule_display>`; inline `role="alert"` line with the server's 422 detail (leading `NNN: ` stripped); `Couldn't load blueprints: <msg>`; `Loading blueprints…`; `No automation blueprints available.`
  - `SkillsPage.tsx` — `<name> enabled` / `<name> disabled` (`t.common.enabled/disabled`); `Failed to toggle <name>` (`t.common.failedToToggle`); `<name> saved ✓`; `Installing <identifier>…`; `Install failed: ${e}`; `Updating installed skills…`; `Update failed: ${e}`; `Hub search failed: ${e}`; `Preview failed: ${e}`; `Scan failed: ${e}`; `Loading...` on initial load failure.
  - `SkillEditorDialog.tsx` — inline red text: `Skill name is required.`, `SKILL.md content is required.`, and the server's 400/404 detail verbatim.
  - `ToolsetConfigDrawer.tsx` — `<toolset label> enabled` / `<toolset label> disabled`; `Failed to toggle toolset`; `Provider set to <provider name>`; `Failed to select provider`; `Enter at least one value to save`; `Saved N key(s)` / `Nothing to save`; `Failed to save keys`; `Failed to start post-setup`; `Post-setup complete`; `Post-setup finished with errors`; `Lost track of the post-setup process`; `Failed to load toolset config`.
  - `PluginsPage.tsx` — `<plugin_name> installed`; `Install failed`; `<warnings joined by space>` (error tone); `Set these in Keys before the plugin can run: <ENV, ENV>` (`t.pluginsPage.missingEnvWarn` + list); `Rescan dashboard extensions (<count>)`; `Rescan failed`; `Provider settings saved.` (`t.pluginsPage.savedProviders`); `Save failed`; `Provider setup finished`; `Provider setup failed: <names>. See setup results below.`; `<row.name> removed`; `Failed` (generic row-action fallback); **(new)** `Failed to load provider config` (`PluginsPage.tsx:355`) — shown when `GET /api/memory/providers/{name}/config` throws while switching the Memory provider select; the form is cleared to no fields.
  - `McpPage.tsx` — `Add ✓`; `Added — authenticate with OAuth`; `Failed to add: ${e}`; `Delete: "<name ≤30>"`; `Installed: "<entry name ≤30>"`; `Installing in background…`; `Failed to install: ${e}`; `<prompt> required` (credential modal); `<server>: N tool(s)`; `<server>: <error|Failed>`; `<server>: OAuth authentication complete`; `OAuth error: ${e}`; `Error: ${e}`; **(new)** `Invalid MCP server` (`McpPage.tsx:135`) — the fallback when `buildMcpServerCreate` throws a non-`Error` value, i.e. it replaces `Name required` / `URL required` / `Command required` / `Bearer token required` only in the unreachable non-Error case.
  - `lib/mcp-dashboard-oauth.ts` — `OAuth popup was blocked — allow popups for this dashboard and retry` (`:27`); **(new)** `OAuth failed to start` (`:34`) — used when the server returns `status: "error"` with an empty `error` field; `OAuth server did not provide an authorization URL` (`:37`); `OAuth authorization failed` (`:59`, when `status: "error"` mid-poll with an empty `error`); `OAuth authorization window was closed before completion` (`:62`). Polling gives up after `maxPollFailures = 3` consecutive status-request failures and rethrows the last network error.
- **Outputs / side effects:** Toasts are ephemeral UI only; none of them retries or rolls back the underlying request.
- **Config / env:** n/a.
- **Edge cases / guards:** Every `${e}` path prints the raw exception/`HTTPException.detail`, so server-side validation messages (e.g. `script must be inside …`, `Server '<n>' rejected: <issues>`, `context_from job '<ref>' not found in profile '<p>'`) surface unmodified in the toast — those strings are documented in the owning entries.
- **Rebuild notes:** Route all user-facing failures through one typed error channel with a stable code plus a translatable message, instead of stringifying exceptions into toasts; keep the raw detail behind a "details" disclosure so the happy path stays readable.

---

### ScheduleBuilder string map (`cron.scheduleModes.*` fully-qualified keys)  `id: web-b.cron-schedulemodes-keymap`
- **Surface:** Web dashboard
- **Where:** `/cron` → create/edit modal → the schedule picker (`web/src/components/ScheduleBuilder.tsx:63-233`). `web-b.cron-schedule-builder` documents the controls using short key names; this is the fully-qualified key → rendered-string crosswalk so a mechanical checker can match `web/src/i18n/en.ts:263-286` one-to-one.
- **What it does:** Names every translated string the schedule picker can render.
- **How it works:** `ScheduleBuilder` reads `const modeStrings = t.cron.scheduleModes` (`:42`) and indexes it directly; the only fallback in the component is `cronStrings.scheduleMode ?? "Schedule"` (`:67`).
- **Inputs / options:** `cron.scheduleMode` = `Schedule` (the `<Label htmlFor="cron-schedule-mode">`); `cron.scheduleModes.interval` = `Every interval`; `cron.scheduleModes.daily` = `Daily`; `cron.scheduleModes.weekly` = `Weekly`; `cron.scheduleModes.monthly` = `Monthly`; `cron.scheduleModes.once` = `Once`; `cron.scheduleModes.custom` = `Custom (cron expression)`; `cron.scheduleModes.intervalEvery` = `Every`; `cron.scheduleModes.intervalUnit` = `Unit`; `cron.scheduleModes.unitMinutes` = `minutes`; `cron.scheduleModes.unitHours` = `hours`; `cron.scheduleModes.unitDays` = `days`; `cron.scheduleModes.timeOfDay` = `Time of day`; `cron.scheduleModes.weekdays` = `Days of week` (used both as the `<Label>` and as the `role="group"` `aria-label`); `cron.scheduleModes.weekdaysShort` = `["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]` (array, indexed 0=Sunday); `cron.scheduleModes.dayOfMonth` = `Day of month`; `cron.scheduleModes.onceAt` = `Run at`; `cron.scheduleModes.customLabel` = `Cron expression`; `cron.scheduleModes.customPlaceholder` = `0 9 * * *`; `cron.scheduleModes.customHint` = `Five-field cron expression (minute, hour, day, month, weekday).`; `cron.scheduleModes.preview` = `Sends as` (rendered as `Sends as: <built string>`); `cron.scheduleModes.previewEmpty` = `(incomplete)`.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** `weekdaysShort` is the only array-valued key in the whole web catalog and is shared with the job-card schedule describer (`web-b.cron-schedule-describe`); a locale that ships fewer than 7 entries would render `undefined` on the weekday buttons (no runtime guard).
- **Rebuild notes:** Keep the weekday names as an ordered array keyed 0=Sunday to match both cron's `dow` field and `Date.getDay()`; a better version would derive them from `Intl.DateTimeFormat(locale, {weekday: "short"})` instead of translating seven strings 18 times.


---

## 7. Addendum — module-level functions, pure helpers and client data contracts (third pass)

Sections 1–6 cover every rendered control, string, dialog and HTTP route of the five pages. This third pass closes the
remaining "not a single function" gap: every module-scope function, constant table and exported TypeScript interface that
these five pages (and the four components + four libs they import) define, with the exact algorithm and the literal data a
rebuilder must reproduce. Nothing here replaces an earlier entry; each one documents code that earlier entries referenced
only by effect. Verbatim catalog data that the API returns but no earlier entry transcribed (the 16 blueprint deep-links)
is included here too.

### Automation blueprint deep-links and ready-to-paste slash commands  `id: web-b.cron-blueprint-deeplinks`
- **Surface:** API
- **Where:** `GET /api/cron/blueprints` → each entry's `command` and `appUrl` fields (returned to `/cron` → `Blueprints`, but not rendered by the SPA — they exist for the docs generator, the desktop `hermes://` protocol handler and the gateway `/blueprint` slash command).
- **What it does:** Gives every blueprint two ready-to-use invocations besides the dashboard form: a flattened chat command (`/blueprint <key> slot=val …`) and a desktop deep-link URL (`hermes://blueprint/<key>?slot=val`), both pre-filled with the blueprint's default slot values.
- **How it works:** `blueprint_catalog_entry(blueprint)` (`cron/blueprint_catalog.py:663-679`) merges `blueprint_form_schema(blueprint)` (`:580-599` → `key,title,description,category,tags,fields[{name,type,label,default,options,optional,strict,help}]`) with four extra keys: `schedule` (the raw `schedule_template`), `scheduleHuman` (`_humanize_schedule`, `:637-660`), `command` (`blueprint_slash_command`, `:602-621`) and `appUrl` (`blueprint_deeplink`, `:624-634`). `blueprint_slash_command` starts from `/blueprint <key>` and appends `name=value` for every slot using `values.get(name, slot.default)`; a slot whose value is `None`/`""` is skipped when `optional` else emitted as empty; values are double-quoted (with `"` → `\"`) when `slot.type == "text"` **or** the value contains a space. `blueprint_deeplink` URL-encodes the key with `quote()` and appends `urlencode(query)` over the non-empty slot values (so spaces become `+`, `:` becomes `%3A`, `,` becomes `%2C`). `_humanize_schedule` derives the human string from the template: leading `*/` → `every <interval_min default> minutes`; `{interval_hours}` present → `weekdays, ` prefix when the template contains `* * 1-5`, then `every hour` (when the default is `1`) or `every <n> hours`; `* * 1-5` with a `time`-typed slot → `weekdays at <time>`; `{dow}` present → `<day|recurrence default> at <time>`; otherwise `daily at <time>` or the literal `on a schedule`.
- **Inputs / options:** No user input — the strings are computed from the blueprint definition. The 16 live `appUrl` values (verbatim, `api_live/get_all.json["/api/cron/blueprints"]`):
  1. `hermes://blueprint/morning-brief?time=08%3A00&deliver=origin`
  2. `hermes://blueprint/important-mail?interval_min=30&criteria=needs+a+reply+today%2C+is+from+my+manager+or+family%2C+or+mentions+a+deadline&deliver=origin`
  3. `hermes://blueprint/weekly-review?time=18%3A00&day=sunday&deliver=origin`
  4. `hermes://blueprint/workday-start?time=09%3A00&deliver=origin`
  5. `hermes://blueprint/custom-reminder?what=take+a+break+and+stretch&time=14%3A00&recurrence=everyday&deliver=origin`
  6. `hermes://blueprint/evening-winddown?time=21%3A00&deliver=origin`
  7. `hermes://blueprint/news-digest?topic=AI+and+technology&time=18%3A00&recurrence=weekdays&count=5&deliver=origin`
  8. `hermes://blueprint/bill-renewal-watch?what=my+streaming+subscription+renews+soon&time=10%3A00&recurrence=everyday&deliver=origin`
  9. `hermes://blueprint/price-watch?item=a+product+URL+or+exact+flight%2Fhotel%2Flisting+description&condition=the+all-in+price+drops+below+my+target&interval_h=6&deliver=origin`
  10. `hermes://blueprint/competitor-watch?companies=two+or+three+competitors%2C+by+canonical+name&categories=product+launches%2C+pricing+changes%2C+funding%2C+partnerships%2C+executive+moves%2C+incidents&time=09%3A00&recurrence=monday&deliver=origin`
  11. `hermes://blueprint/habit-checkin?habit=20+minutes+of+reading&time=20%3A00&recurrence=everyday&deliver=origin`
  12. `hermes://blueprint/hydration-move?interval_hours=1&start_hour=9&end_hour=17&deliver=origin`
  13. `hermes://blueprint/meal-plan?diet=no+restrictions&meals=dinner+only&effort=quick&time=17%3A00&day=sunday&deliver=origin`
  14. `hermes://blueprint/learn-daily?topic=Spanish+vocabulary&time=08%3A30&recurrence=weekdays&deliver=origin`
  15. `hermes://blueprint/gratitude-journal?time=21%3A30&recurrence=everyday&deliver=origin`
  16. `hermes://blueprint/on-this-day?flavor=on+this+day+in+history&time=07%3A30&deliver=origin`
  The matching `command` strings are the `/blueprint <key> …` forms already transcribed per blueprint in `web-b.cron-blueprints`; e.g. `/blueprint morning-brief time=08:00 deliver=origin` and `/blueprint important-mail interval_min=30 criteria="needs a reply today, is from my manager or family, or mentions a deadline" deliver=origin`.
- **Outputs / side effects:** Pure strings in the JSON response; no disk or network effect. Opening an `appUrl` in a machine with the desktop app registered for `hermes://` pre-fills the desktop's blueprint form; pasting the `command` into any Hermes chat runs the `/blueprint` slash command.
- **Config / env:** The `deliver` slot's `options` (and therefore both strings' `deliver=` default) come from `cron_delivery_targets()` at request time; `hermes://` handler registration is the desktop app's (`apps/desktop`).
- **Edge cases / guards:** `deliver` defaults to `origin`, which from the dashboard means "the configured home channel" (the dashboard has no originating chat). Text slots always get quoted in `command`, even when they contain no spaces, so the shell-ish parser on the slash-command side never splits them. A slot whose default is `""` and which is not `optional` produces `name=` (empty) rather than being dropped.
- **Rebuild notes:** Serialise each catalog row three ways from one definition — form schema, command line, URL — so every surface (web form, chat, OS deep-link, docs) is generated, never hand-written. A better version would round-trip: parse an inbound `hermes://blueprint/...` back into filled form values and open the gallery card pre-filled.

### Cron payload/form normalisation library (`web/src/lib/cron-job.ts`)  `id: web-b.cron-job-payload-lib`
- **Surface:** Web dashboard
- **Where:** Not directly visible; sits between the create/edit modals (`/cron` → `CREATE` / `Edit job`) and `POST /api/cron/jobs` / `PUT /api/cron/jobs/{id}`. Shared with the desktop cron editor.
- **What it does:** Converts the flat form state into the exact create/update JSON body the backend expects (and back again when editing), including the trick that stores the `continuity` checkbox as a reserved `self` entry inside `context_from`.
- **How it works:** `web/src/lib/cron-job.ts`.
  - `CronJobFormState` (`:3-18`) — 15 fields: `name, prompt, schedule, deliver, skills[], provider, model, base_url, script, no_agent, context_from, continuity, enabled_toolsets[], workdir` (all strings except the two booleans and the two arrays).
  - `splitCronList(value)` (`:21-27`, exported) — accepts an array or a string; strings are split on `/[\n,]/`; every item is `String(item).trim()`ed and empties dropped. Used for `context_from` and `enabled_toolsets`.
  - `optionalText(value, stripTrailingSlash=false)` (`:31-34`, module-private) — trims, optionally strips trailing `/`+ (`replace(/\/+$/,"")`), returns `null` when the result is empty. Mirrors the backend's `_cron_optional_text` so an update explicitly clears a field instead of leaving a stale value.
  - `asString(value)` (`:37-39`, module-private) — `typeof value === "string" ? value : ""`.
  - `buildCronJobPayload(form)` (`:44-68`, exported) → `CronJobMutation`: `name`/`prompt`/`schedule` trimmed; `deliver` trimmed or `"local"`; `skills` filtered for truthiness; `provider`, `model`, `script`, `workdir` through `optionalText`; `base_url` through `optionalText(..., true)`; `no_agent` coerced with `Boolean()`; `context_from` = `splitCronList(form.context_from)` with any hand-typed `self` (case-insensitive) removed, then `"self"` pushed when `form.continuity` — `null` when the list ends up empty; `enabled_toolsets` filtered, `null` when empty.
  - `cronJobHasExecutionContent(job)` (`:70-75`, exported) — `true` when the trimmed `prompt`, the trimmed `script`, or a non-empty filtered `skills` array is present. The create/edit modals use it (via CronPage validation) to decide whether an agent job has anything to run.
  - `cronJobFormFromJob(job)` (`:77-102`, exported) — the inverse: `continuity` is `true` when the row carries an explicit `continuity` boolean (tool/RPC-formatted rows) **or** when `context_from` contains a case-insensitive `self` (raw store rows); `externalRefs` is `context_from` minus `self`, re-joined with `\n` for the textarea; `schedule` is the first non-empty of `job.schedule.expr`, `job.schedule.run_at`, `job.schedule_display`; `deliver` falls back to `"local"`; arrays are filtered/split.
- **Inputs / options:** n/a (pure functions).
- **Outputs / side effects:** The `CronJobMutation` body sent to the cron routes; the `CronJobFormState` used to seed the Edit modal.
- **Config / env:** n/a.
- **Edge cases / guards:** `self` is never typed by users — stripping it first means a user who *does* type it cannot create a duplicate continuity ref. `null` (not `undefined` or `""`) is what clears an optional field server-side, so omitting the null collapse would make edits unable to remove a `script` or a `base_url`.
- **Rebuild notes:** One build/parse pair keyed on a single flat form type, with `null` as the explicit "clear this" sentinel and a reserved list entry as the continuity flag. A better version would model continuity as a first-class boolean on the wire and let the store derive `self` itself.

### Cron job derived-display helpers (`CronPage.tsx` module scope)  `id: web-b.cron-display-helpers`
- **Surface:** Web dashboard
- **Where:** Every string on a `/cron` job card (title, schedule line, `repeat:`, `Last:`, `Next:`, mode, model, profile badge) and the identity used by the trigger/edit/delete handlers.
- **What it does:** Turns a raw `CronJob` row into the exact text and status tone the card shows, and gives each job a stable `profile:id` key so two profiles can hold jobs with the same id.
- **How it works:** All module-scope in `web/src/pages/CronPage.tsx`:
  - `formatTime(iso?)` (`:54-58`) — `"—"` for null/empty, else `new Date(iso).toLocaleString()`. Renders `Last:` and `Next:`.
  - `asText(value)` (`:60-62`) — `typeof value === "string" ? value : ""`; used everywhere a nullable API field is read.
  - `truncateText(value, maxLength)` (`:64-68`) — slices and appends `"..."` when longer than `maxLength`.
  - `getJobPrompt(job)` (`:70-72`) — `asText(job.prompt)`.
  - `getJobName(job)` (`:442-444`) — `asText(job.name).trim()`.
  - `getJobTitle(job)` (`:446-457`) — first non-empty of: name → `truncateText(prompt, 60)` → `truncateText(script, 60)` → `job.id` → the literal `"Cron job"`.
  - `getJobScheduleDisplay(job, strings)` (`:459-473`) — `describeSchedule(job.schedule, asText(job.schedule_display) || asText(job.schedule?.display), strings)`; the structured render is preferred so `30 14 * * 1,3,5` shows as `Weekly on Mon, Wed, Fri at 14:30` instead of the raw fields.
  - `getJobState(job)` (`:475-477`) — `asText(job.state)` or, when absent, `"disabled"` when `job.enabled === false` else `"scheduled"`.
  - `getRepeatDisplay(job)` (`:479-484`) — `"forever"` when there is no `repeat` or `repeat.times == null`; else `"<completed>/<times>"` when `completed > 0`, otherwise `"<times> times"`.
  - `getJobMode(job)` (`:486-490`) — `"no_agent"` when `job.no_agent`, `"script+agent"` when a `script` is set, else `"agent"`.
  - `getModelDisplay(job)` (`:492-497`) — `"<provider>/<model>"` when both are set, else whichever one is set, else `""`.
  - `getJobProfile(job)` (`:499-501`) — `job.profile` → `job.profile_name` → the literal `"default"`.
  - `getJobKey(job)` (`:503-505`) — `` `${getJobProfile(job)}:${job.id}` ``; this is the key for the `triggeringJobKeys` set and the React list key.
  - `splitJobKey(key)` (`:507-511`) — splits on the **first** `:`; no colon → `{profile:"default", id:key}`; empty left side → `"default"`. Lets a job id itself contain colons.
  - `profileLabel(profile)` (`:513-515`) — identity function today (`default` → `default`); the seam where a friendlier label would go.
  - `STATUS_TONE` (`:517-523`) — badge tone map: `enabled: success`, `scheduled: success`, `paused: warning`, `error: destructive`, `completed: destructive`; anything else falls back to the Badge default (`secondary`).
  - `selectOptions(current, options)` (`:168-187`) — renders `<SelectOption>` for each `{value,label}` and, when `current` is truthy but not among them, appends a final option whose value **and** label are `current`, so an unknown stored value (a delivery target that has since disappeared, a model no longer offered) is preserved instead of being silently rewritten by the Select.
- **Inputs / options:** n/a (pure functions over one `CronJob`).
- **Outputs / side effects:** Text nodes and badge tones only.
- **Config / env:** `formatTime` uses the browser locale/timezone (`toLocaleString`), so the same job reads differently on two machines.
- **Edge cases / guards:** `getJobTitle` never returns empty; `getRepeatDisplay` distinguishes "has run some" from "not started"; `splitJobKey` is asymmetric with `getJobKey` only for profile names containing `:` (not possible — profile names are validated).
- **Rebuild notes:** Keep every "what does this row say" decision in named pure functions next to the page so they are unit-testable and so the desktop can reuse them. Better: move them into the shared package next to `describeSchedule` and cover them with the same tests.

### Cron "Trigger now" concurrency controller (`@hermes/shared`)  `id: web-b.cron-trigger-controller`
- **Surface:** Web dashboard
- **Where:** `/cron` → job card `Trigger now` (⚡) — the button's disabled/spinner state. Also used by the desktop cron view (same package).
- **What it does:** Prevents one mounted UI from firing the same cron job twice concurrently, and drives the per-row busy state, without pretending to be the real execution lock.
- **How it works:** `apps/shared/src/cron-trigger-controller.ts`. `createCronTriggerController(onRunningChange = () => undefined)` closes over a `Set<string>` of in-flight keys and returns `{isRunning(key), run(key, action, onStarted?)}`. `run` returns immediately with `{started:false, value:null}` when the key is already in the set; otherwise it adds the key, calls `onRunningChange(key, true)`, calls the optional `onStarted()` (the seam where a UI could toast "starting…" — CronPage deliberately passes nothing), awaits `action()` and returns `{started:true, value}`; a `finally` block always deletes the key and calls `onRunningChange(key, false)`. `CronPage` builds one controller in a ref (`createCronTriggerController` imported from `@hermes/shared`) whose `onRunningChange` updates the `triggeringJobKeys` state set, and calls `controller.run(getJobKey(job), () => api.triggerCronJob(id, profile))`. Types: `CronTriggerRunResult<T> {started: boolean; value: T | null}`, `CronTriggerController {isRunning(key): boolean; run<T>(key, action, onStarted?): Promise<CronTriggerRunResult<T>>}`.
- **Inputs / options:** `key` (the `profile:id` job key), `action` (the async call), `onStarted` (optional callback), `onRunningChange` (constructor callback).
- **Outputs / side effects:** Only the in-memory set and the callback; the toast is emitted by the caller and only when `started` is true, so a double-click produces exactly one toast.
- **Config / env:** n/a.
- **Edge cases / guards:** The source comment is explicit that this is "an interaction guard for one mounted UI surface. Cross-window and cross-process exclusion remains the backend's responsibility via its durable cron claim; a renderer-local `Set` must never be treated as the execution lock." A second browser tab, or the scheduler ticker, can still race — the backend answers 409 `Job is already running or was claimed by another scheduler`.
- **Rebuild notes:** A keyed in-flight set with a `finally`-guaranteed release and a change callback; keep the "not a lock" contract explicit so nobody removes the server-side claim.

### Schedule library — the ten pure functions behind the picker and the job line  `id: web-b.schedule-lib-functions`
- **Surface:** Web dashboard
- **Where:** `/cron` → the `Schedule` picker inside both job modals, and the schedule sentence on every job card. Source `web/src/lib/schedule.ts` (+ `TimeOfDayField` in `web/src/components/ScheduleBuilder.tsx`).
- **What it does:** Converts picker state ⇄ backend schedule string, and renders any stored schedule as an English sentence — without ever "humanising" an expression it does not fully understand.
- **How it works:** Every function in `web/src/lib/schedule.ts`:
  - `ScheduleMode` (`:32-40`) = `"interval" | "daily" | "weekly" | "monthly" | "once" | "custom"`; `IntervalUnit` (`:41`) = `"minutes" | "hours" | "days"`; `WEEKDAY_INDEXES` (`:45`) = `[0,1,2,3,4,5,6]` with `Weekday` its member type (0 = Sunday, matching both cron's `dow` and `Date.getDay()`).
  - `ScheduleBuilderState` (`:48-77`) — `{mode, intervalValue, intervalUnit, timeOfDay, weekdays: Weekday[], dayOfMonth, onceAt, custom}`; every mode keeps its own slot so switching modes never loses input.
  - `DEFAULT_SCHEDULE_STATE` (`:78-87`) — `mode:"interval"`, `intervalValue:30`, `intervalUnit:"minutes"`, `timeOfDay:"09:00"`, `weekdays:[1,2,3,4,5]`, `dayOfMonth:1`, `onceAt:""`, `custom:""`.
  - `UNIT_SUFFIX` (`:89-93`) — `{minutes:"m", hours:"h", days:"d"}`.
  - `buildScheduleString(state)` (`:104-148`) — `interval`: `Math.floor(intervalValue)`, returns `""` when not finite or `< 1`, else `every <n><suffix>`. `daily`: `parseTimeOfDay(timeOfDay)` or `""`, then `<minute> <hour> * * *`. `weekly`: same time parse, days = `"*"` when the selection is empty else the sorted numeric list joined with `,` → `<minute> <hour> * * <days>`. `monthly`: time parse plus `Math.floor(dayOfMonth)` in 1–31 → `<minute> <hour> <dom> * *`. `once`: trimmed `onceAt`; when exactly 16 chars (the `YYYY-MM-DDTHH:MM` a `datetime-local` input emits) `":00"` is appended so the backend regex takes its `T` branch. `custom`: the trimmed raw string. An empty return is the signal the Submit button uses to stay disabled. The comment explains the design choice: interval syntax (`every 30m`) is emitted rather than cron whenever possible because it survives a backend without `croniter` and reads better in the list; raw cron is only emitted when specific weekdays or a day-of-month are needed.
  - `parseScheduleString(schedule)` (`:151-205`) — empty → `DEFAULT_SCHEDULE_STATE`; `/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/` → `once` with `onceAt = trimmed.slice(0,16)`; `/^every\s+(\d+)\s*([mhd])$/i` → `interval` (`d`→days, `h`→hours, else minutes; non-positive → 1); `parseSimpleCronExpression` hit → `daily` / `weekly` (`weekdays` or `[]`) / `monthly` (`dayOfMonth` or 1); anything else → `custom` preserving the raw string.
  - `parseSimpleCronExpression(expr)` (`:213-276`, private) — the shared strictness gate. Requires exactly 5 whitespace-separated fields; month field must be `*`; every field must match `^\d+(,\d+)*$|^\*$` (so ranges `1-5`, steps `*/5`, names `MON` and macros `@reboot` all bail out); minute and hour must not be `*` and must each be a single value in 0–59 / 0–23; time is rendered `HH:MM` with `pad2`. Then: `dom == "*" && dow == "*"` → `daily`; `dom == "*"` with a dow list → `weekly` with each entry parsed 0–7, `7` normalised to `0`, duplicates dropped, empty list rejected; `dow == "*"` with a numeric dom 1–31 → `monthly`; both constrained → `null`.
  - `parseTimeOfDay(value)` (`:278-297`, private) — `/^\d{1,2}:\d{2}$/` plus range checks 0–23 / 0–59 → `{hour, minute}` else `null`.
  - `ScheduleDescribeStrings` (`:299-319`) — the translation surface passed in instead of importing i18n: `none, everyMinutes, everyHours, everyDays, dailyAt, weeklyAt, monthlyAt, onceAt, weekdaysShort` (a 7-tuple, Sunday-first) and `ordinal(day) => string`.
  - `ScheduleLike` (`:322-328`) — the stored shape: `{kind?, expr?, minutes?, run_at?, display?}`.
  - `describeSchedule(schedule, fallbackDisplay, strings)` (`:338-372`) — no schedule → `fallbackDisplay || strings.none`; `kind === "interval"` with numeric `minutes` → `describeInterval`; `kind === "once"` with `run_at` → `onceAt.replace("{time}", formatIsoLocal(run_at, false))`; `kind === "cron"` with `expr` → `describeCronExpression` when it returns non-null; then, for legacy rows without `kind`, it tries `describeCronExpression(fallbackDisplay)` and finally returns `fallbackDisplay`, then `schedule.display`, then `schedule.expr`, then `strings.none`.
  - `describeInterval(minutes, strings)` (`:374-398`, private) — `<= 0` → `none`; divisible by 1440 → `everyDays` with `{n} = minutes/1440`; divisible by 60 → `everyHours` with `{n} = minutes/60`; else `everyMinutes` with `{n} = minutes`.
  - `describeCronExpression(expr, strings)` (`:400-424`, private) — `parseSimpleCronExpression` or `null`; `daily` → `dailyAt` with `{time}`; `weekly` → `weeklyAt` with `{days}` = the selected `weekdaysShort` labels joined `", "` and `{time}`; `monthly` → `monthlyAt` with `{day} = strings.ordinal(dayOfMonth)` and `{time}`. Deliberately 5-field only: the backend also accepts the 6-field `minute hour dom month dow year` form, and destructuring only the first five would silently drop the year (`0 9 * * * 2099` would read as `Daily at 09:00`), so 6+ field expressions fall through to the raw-string fallback.
  - `pad2(n)` (`:426-428`, private) — zero-pads to two digits.
  - `formatIsoLocal(iso, includeSeconds)` (`:433-448`, private) — `new Date(iso)`; on `NaN` returns the raw string; else `YYYY-MM-DD HH:MM` in **local** time, with `:SS` appended when `includeSeconds`.
  - `englishOrdinal(day)` (`:450-…`, exported) — floors; non-finite or `< 1` → `String(day)`; last two digits 11–13 → `<d>th`; else `1→st`, `2→nd`, `3→rd`, default `th`. Non-English locales are expected to override `ordinal` with `String(day)`.
  - `TimeOfDayField({id, label, onChange, value})` (`ScheduleBuilder.tsx:237-259`) — a `<Label htmlFor>` plus a native `<input type="time">` (classes `h-9 w-full border border-border bg-background/40 px-3 py-2 text-sm font-courier`), chosen over two hour/minute selects so the browser honours the user's AM/PM locale and the value round-trips with `buildScheduleString` without extra parsing. `ScheduleBuilder.tsx:261` re-exports `DEFAULT_SCHEDULE_STATE`.
- **Inputs / options:** n/a (pure); `TimeOfDayField` takes `id`, `label`, `value` (`HH:MM`), `onChange`.
- **Outputs / side effects:** Strings only. Unit-tested in `web/src/lib/schedule.test.ts` fixtures such as `every 2h`, `every 1d`, `30 14 * * 1,3,5`, `2026-02-03T14:00:00`.
- **Config / env:** n/a. Local timezone affects `formatIsoLocal` only.
- **Edge cases / guards:** The croniter `L` ("last day of month") extension is deliberately unsupported — `dayOfMonth` is documented as 1..31 with no sugar, because `parse_schedule`'s regex would reject it. `parseSimpleCronExpression` is intentionally conservative: anything it cannot fully explain is shown raw rather than mis-described.
- **Rebuild notes:** One strict recogniser shared by the builder and the describer is the whole trick — never humanise what you cannot round-trip. A better version would compute the next N fire times (with a timezone selector) and show them under the picker.

### Logs level classification and filter tables  `id: web-b.logs-classify-lib`
- **Surface:** Web dashboard
- **Where:** `/logs` → the colour of every rendered log line, and the four `FilterGroup`s in the toolbar (`File`, `Level`, `Component`, `Lines`).
- **What it does:** Decides which of four levels a log line belongs to (for colouring) using the structured level token first and word-boundary matching only as a fallback, and supplies the exact option tables the filters render.
- **How it works:** `web/src/lib/log-classify.ts`: `LogLevel` = `"error" | "warning" | "info" | "debug"`. `LEVEL_TOKEN_RE` = `/^\d{4}-\d{2}-\d{2}[ T][\d:,.]+\s+(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b/` — anchored to the line head so payload text cannot spoof the level (the format it matches is `hermes_logging`'s, e.g. `2026-07-26 13:07:45,228 INFO …`). `classifyLine(line)`: when the token matches, `ERROR|CRITICAL|FATAL` → `error`, `WARNING|WARN` → `warning`, `DEBUG` → `debug`, anything else → `info`. With no token (tracebacks, wrapped continuation lines) it upper-cases the line and tests, in order, `/\b(ERROR|CRITICAL|FATAL)\b/` or a `TRACEBACK (` prefix → `error`; `/\b(WARNING|WARN)\b/` → `warning`; `/\bDEBUG\b/` → `debug`; default `info`. Word boundaries are what keep `parse_errors=0` and the path `errors.log` out of the red bucket. `web/src/pages/LogsPage.tsx` module scope: `FILES = ["agent","errors","gateway"]`, `LEVELS = ["ALL","DEBUG","INFO","WARNING","ERROR"]`, `COMPONENTS = ["all","gateway","agent","tools","cli","cron"]`, `LINE_COUNTS = [50,100,200,500]`, `LINE_COLORS = {error:"text-destructive", warning:"text-warning", info:"text-foreground", debug:"text-text-tertiary"}`; `formatFilterLabel(value) = value.toUpperCase()`; `toSegmentOptions(values)` maps each value to `{value, label: formatFilterLabel(value)}` — this is why the radios read `AGENT`, `ERRORS`, `ALL`, `DEBUG`, `50`, `100` in caps while the request sends the lower-case value.
- **Inputs / options:** `classifyLine(line: string) => LogLevel`; `toSegmentOptions(values: readonly T[])`.
- **Outputs / side effects:** A Tailwind class per line; the segmented option arrays.
- **Config / env:** n/a — the tables are hard-coded, which is why the backend's `gui`, `desktop` and `mcp` log files have no radio.
- **Edge cases / guards:** Unit-tested in `web/src/lib/log-classify.test.ts`. `CRITICAL` and `FATAL` map to the same colour as `ERROR` even though the Level filter offers no `CRITICAL` option (the backend's minimum-level filter treats them as ≥ ERROR).
- **Rebuild notes:** Prefer the structured token, fall back to word boundaries, never substring — and keep the classifier in its own tested module. Better: parse the whole line into `{ts, level, logger, message}` and render columns instead of colouring raw text.

### Skills page badge/tone/icon maps  `id: web-b.skills-badge-maps`
- **Surface:** Web dashboard
- **Where:** `/skills` — the toolset card icons, the category names in the `Categories` panel, the trust badge on every hub result card and detail dialog, and the verdict header plus severity tallies inside the security-scan panel.
- **What it does:** Maps raw API enum values to the icon, badge tone and human label the page renders.
- **How it works:** `web/src/pages/SkillsPage.tsx` module scope:
  - `CATEGORY_LABELS` (`:70-84`) — 14 explicit overrides: `mlops → MLOps`, `mlops/cloud → MLOps / Cloud`, `mlops/evaluation → MLOps / Evaluation`, `mlops/inference → MLOps / Inference`, `mlops/models → MLOps / Models`, `mlops/training → MLOps / Training`, `mlops/vector-databases → MLOps / Vector DBs`, `mcp → MCP`, `red-teaming → Red Teaming`, `ocr → OCR`, `p5js → p5.js`, `ai → AI`, `ux → UX`, `ui → UI`.
  - `prettyCategory(raw, generalLabel)` (`:86-97`) — falsy `raw` → `generalLabel` (`common.general` = `General`); an override hit → that label; otherwise split on `[-_/]`, upper-case each word's first character, join with spaces (so `autonomous-ai-agents` → `Autonomous Ai Agents`, including the un-special-cased `Ai`).
  - `TOOLSET_ICONS` (`:99-110`) + `toolsetIcon(name)` (`:112-121`) — first **substring** hit against the lower-cased toolset name, in object order: `computer → Cpu`, `web → Globe`, `security → Shield`, `vision → Eye`, `design → Paintbrush`, `ai → Brain`, `integration → Blocks`, `code → Code`, `automation → Zap`; no hit → `Wrench`. Substring matching means `browser` gets `Wrench` but `web` matches `web`, and `x_search` gets `Wrench`.
  - `trustVisual(level)` (`:816-831`) — `trusted → {tone:"success", label:"trusted"}`, `builtin → {tone:"secondary", label:"builtin"}`, `community → {tone:"warning", label:"community"}`, anything else → `{tone:"outline", label: level || "unknown"}` (so an unseen trust tier renders its own raw name, or the literal `unknown` when the field is empty).
  - `verdictVisual(verdict)` (`:833-848`) — `safe → {tone:"success", Icon: ShieldCheck, label:"Safe"}`, `caution → {tone:"warning", Icon: ShieldAlert, label:"Caution"}`, `dangerous → {tone:"destructive", Icon: ShieldAlert, label:"Dangerous"}`, default → `{tone:"warning", Icon: ShieldQuestion, label: verdict}` (an unknown verdict shows its raw string with a question-mark shield).
  - `SEVERITY_TONE` (`:850-856`) — `critical → destructive`, `high → destructive`, `medium → warning`, `low → secondary`; a severity outside the four falls back to the Badge default tone.
  - `SkillRow` (`:736-778`) — the row component: a `Switch` (`disabled` while toggling), the skill name in `font-mono-ui` (muted when disabled), the description clamped to two lines or the `noDescriptionLabel` (`skills.noDescription` = `No description available.`), and a pencil `Button` that is `opacity-0` until the row is hovered or the button is focused (`group-hover:opacity-100 focus-visible:opacity-100`), `title="Edit SKILL.md"`, `aria-label="Edit <name>"`.
  - `PanelItem` (`:780-796`) — the left-panel entry: a `ListItem` with the icon, a truncating label, `font-mondwest text-[0.7rem] tracking-[0.08em] uppercase` (this is what renders `ALL (53)` / `TOOLSETS (27)` / `BROWSE HUB` in caps) and, when active, `bg-foreground/90 text-background`.
- **Inputs / options:** n/a (pure maps and presentational components).
- **Outputs / side effects:** Icons, badge tones and labels only.
- **Config / env:** n/a.
- **Edge cases / guards:** `toolsetIcon` is substring-based and order-dependent, so a future toolset named e.g. `code_vision` takes the `vision` icon only if `vision` precedes `code` in the object — it does not, so it would take `Code`. Both `trustVisual` and `verdictVisual` degrade gracefully to the raw enum string rather than throwing on an unknown value.
- **Rebuild notes:** Keep the enum→presentation maps as data next to the page and always provide an "unknown" branch that shows the raw value. Better: drive them from a shared design-token table so the desktop and web agree on tones.

### Plugins page memory-provider helper functions  `id: web-b.plugins-memory-helpers`
- **Surface:** Web dashboard
- **Where:** `/plugins` → card `Runtime provider plugins` → the `Memory provider` column: its status badge, the dynamic settings form, the dependency-setup hint box and the `Setup results` list.
- **What it does:** Turns the provider registry's `{status, fields, setup}` JSON into badges, a conditional form and a per-step results list, and decides when the "install dependencies" affordance is shown at all.
- **How it works:** `web/src/pages/PluginsPage.tsx` module scope:
  - `MEMORY_PROVIDER_BUILTIN` (`:33`) = the sentinel string `"__hermes_memory_builtin__"`. The config value for built-in memory is `""`, but the `Select` component maps an empty value to an empty label, so the page substitutes this sentinel in the widget and translates back to `""` on save.
  - `MemoryFormValue` (`:35`) = `string | boolean | number`.
  - `MEMORY_STATUS_LABEL` (`:37-42`) — `ready → "ready"`, `needs_config → "needs setup"`, `unavailable → "unavailable"`, `missing → "missing"`.
  - `MEMORY_STATUS_TONE` (`:44-49`) — `ready → success`, `needs_config → warning`, `unavailable → destructive`, `missing → destructive`.
  - `fieldInitialValue(field)` (`:51-55`) — `secret` → `""` (never pre-fills a stored secret), `boolean` → `Boolean(field.value)`, everything else → `String(field.value ?? "")`.
  - `fieldIsVisible(field, values)` (`:57-63`) — no `when` map → visible; otherwise every `[key, expected]` pair must satisfy `String(values[key] ?? "") === String(expected)`. This is a pure AND over stringified comparisons, so `true`/`"true"` and `1`/`"1"` match. Only visible fields are submitted on save/setup.
  - `setupHasDetails(setup?)` (`:65-72`) — true when the setup block has any `external_dependencies`, `pip_dependencies` or `required_env`. Gates whether the hint box renders its detail sections.
  - `setupHasInstallableSteps(setup?)` (`:74-80`) — true when some external dependency has a non-empty `install` command **or** there are `pip_dependencies`. Gates the `Install provider dependencies` button (a provider that only needs env vars gets no button).
  - `SetupCommandBlock({code, label})` (`:82-94`) — a small label row with a `CopyButton` on the right and a bordered mono `<code>` block below (`break-all`). Used for `Install <dep>` / `Verify <dep>` commands.
  - `setupResultLabel(status)` (`:96-100`) — `already_installed → "already installed"`, `no_declared_steps → "no declared setup"`, otherwise the raw status with `_` replaced by spaces.
  - `setupResultClass(status)` (`:102-109`) — `failed → "border-destructive/50 text-destructive"`; `installed`, `verified` or `already_installed` → `"border-success/50 text-success"`; `missing → "border-warning/50 text-warning"`; anything else → `"border-border text-muted-foreground"`.
  - `MemoryProviderSetupResults({results})` (`:111-…`) — renders nothing for an empty array; otherwise a bordered box headed `Setup results` with one block per result: a status chip (`setupResultLabel` + `setupResultClass`), the result `name` followed by ` (<kind with _ → spaces>)`, the `command` in a mono block when present, and a `<pre>` (max-height 32, wrapping, break-words) showing `stderr || stdout` when either is present. The React key is `` `${kind}-${name}-${index}` `` so duplicate names across kinds do not collide.
- **Inputs / options:** n/a (pure helpers + two presentational components).
- **Outputs / side effects:** Class names, labels and JSX only; the copy buttons write to the clipboard.
- **Config / env:** Values come from `GET /api/memory/providers/{name}/config` and `POST /api/memory/providers/{name}/setup`.
- **Edge cases / guards:** Because `fieldIsVisible` compares stringified values, a `when` clause keyed on a boolean field works whether the provider declares `true` or `"true"`. Because `fieldInitialValue` blanks secrets, saving without retyping keeps the stored value (the backend treats a blank secret as "unchanged").
- **Rebuild notes:** Schema-driven form + a status/label/tone table + a gate that hides an install button when there is nothing to install. Better: express `when` as a small typed predicate language instead of string equality, and stream setup output live instead of returning it at the end.

### MCP "Add server" draft builder (`web/src/lib/mcp-server-create.ts`)  `id: web-b.mcp-draft-builder`
- **Surface:** Web dashboard
- **Where:** `/mcp` → header `Add Server` → dialog `Add MCP server`; the client-side validation that toasts before any request is sent. Shared with the Profile Builder page and the desktop.
- **What it does:** Validates the eight-field add-server draft and turns it into the exact `MCPServerCreate` body, splitting args and parsing `KEY=VALUE` env lines.
- **How it works:** `web/src/lib/mcp-server-create.ts`.
  - `McpTransport` = `"http" | "stdio"`.
  - `McpServerDraft` (`:5-14`) — `{name, transport, url, httpAuth, bearerToken, command, args, env}` (all strings except `transport` and `httpAuth`).
  - `emptyMcpServerDraft()` (`:16-27`) — every string `""`, `transport:"http"`, `httpAuth:"none"`; this is the reset the modal applies after a successful add and on close.
  - `parseArgs(raw)` (`:29-35`, private) — splits on `/[\s,]+/`, trims each token, drops empties. So `-y, @scope/pkg` and `-y @scope/pkg` are equivalent.
  - `parseEnv(raw)` (`:37-49`, private) — iterates `raw.split("\n")`, trims each line, skips blanks and any line with no `=`, splits at the **first** `=` (so values may contain `=`), trims key and value, and skips entries whose key is empty.
  - `buildMcpServerCreate(draft)` (`:51-77`) — trims `name`, throws `Error("Name required")` when empty. HTTP branch: trims `url`, throws `Error("URL required")` when empty; throws `Error("Bearer token required")` when `httpAuth === "header"` and the token is blank; builds `{name, url}`, adds `auth` when `httpAuth !== "none"`, adds `bearer_token` (the untrimmed draft value) when `header`. stdio branch: trims `command`, throws `Error("Command required")` when empty; builds `{name, command}`, adds `args` only when `parseArgs` yields ≥1 entry and `env` only when `parseEnv` yields ≥1 key.
- **Inputs / options:** The draft object assembled from the modal's inputs `mcp-name`, `mcp-transport`, `mcp-url`, `mcp-auth`, `mcp-bearer-token`, `mcp-command`, `mcp-args`, `mcp-env`.
- **Outputs / side effects:** Either an `McpServerCreate` object or a thrown `Error` whose message the page shows as an error toast (`McpPage.tsx` catches it and falls back to the literal `"Invalid MCP server"` for non-`Error` throws).
- **Config / env:** n/a.
- **Edge cases / guards:** Args/env are only meaningful for stdio and are simply not attached in the HTTP branch — matching the backend's `_normalize_mcp_server_create`, which rejects them with `Arguments are only supported for stdio MCP servers` / `Environment variables are only supported for stdio MCP servers` if a hand-crafted request sends them anyway. The bearer token is deliberately **not** trimmed into the payload (only its emptiness is checked), so a token with meaningful leading/trailing whitespace survives.
- **Rebuild notes:** Keep the transport/auth matrix in one pure builder used by every surface, and make the error strings the user-facing copy. Better: return a structured `{field, message}` so the modal can highlight the offending input instead of toasting.

### MCP dashboard OAuth client driver (`web/src/lib/mcp-dashboard-oauth.ts`)  `id: web-b.mcp-oauth-client-helper`
- **Surface:** Web dashboard
- **Where:** `/mcp` → server card `Authenticate` (only shown when `auth === "oauth"`); the popup window it opens and the spinner on the button.
- **What it does:** Drives the whole browser side of the MCP OAuth 2.1 flow: opens a popup before the first await so it is not blocked, starts the flow, navigates the popup to the authorization URL, then polls flow status once a second until approval, error, or the popup closing.
- **How it works:** `completeMcpDashboardOAuth({serverName, start, status, open, sleep = defaultSleep, maxPollFailures = 3})`.
  - `defaultSleep(ms)` = `new Promise(resolve => window.setTimeout(resolve, ms))`; injectable so tests run without timers.
  - `open("about:blank", "_blank")` runs **synchronously** in the click handler before any `await` — browsers classify a popup opened after an await as unsolicited. A null result throws `Error("OAuth popup was blocked — allow popups for this dashboard and retry")`. The new window's `opener` is immediately set to `null` (reverse-tabnabbing guard).
  - `start(serverName)` (= `api.authMcpServer`) → an `McpOAuthFlow`. `status === "error"` throws `started.error || "OAuth failed to start"`; a missing `authorization_url` throws `"OAuth server did not provide an authorization URL"`; any throw in this block closes the popup first and re-throws. Otherwise `authWindow.location.href = started.authorization_url`.
  - Poll loop: `status(started.flow_id)` (= `api.getMcpOAuthFlow` → `GET /api/mcp/oauth/flows/{flow_id}`), resetting a `pollFailures` counter on success. A throw increments it; at `maxPollFailures` (3) the error propagates, otherwise it sleeps 1000 ms and retries — so a transient network blip does not abort a flow. `status === "approved"` returns the flow (its `tools` array populates the card's test result). `status === "error"` throws `current.error || "OAuth authorization failed"`. If neither and `authWindow.closed` is true, it throws `"OAuth authorization window was closed before completion"`. Otherwise sleeps 1000 ms and loops.
- **Inputs / options:** `serverName`; the injected `start`, `status`, `open`, `sleep` and `maxPollFailures` (default 3).
- **Outputs / side effects:** A popup window; on success the returned `McpOAuthFlow` with `tools`; the caller toasts `<name>: OAuth authentication complete` or `OAuth error: <e>`. The page never calls `DELETE /api/mcp/oauth/flows/{flow_id}` — abandoning the flow leaves it to the server's 15-minute GC (the desktop's cancel button does call it).
- **Config / env:** n/a on the client; the redirect URI and flow caps are server-side.
- **Edge cases / guards:** The loop has no overall timeout — it ends only on approval, error, popup close, or three consecutive poll failures. Because the popup is polled rather than messaged, a user who navigates the popup elsewhere and leaves it open keeps the loop running until the server-side flow errors out.
- **Rebuild notes:** Open the popup synchronously, poll a server-side flow registry by id, and treat "popup closed" as a terminal user cancel. Better: use `BroadcastChannel`/`postMessage` from the callback page plus a server push (SSE) instead of 1 s polling, and call the cancel endpoint on unmount.

### Client data contract — Cron page types (`web/src/lib/api.ts`)  `id: web-b.cron-client-types`
- **Surface:** API
- **Where:** The exact JSON the `/cron` page reads and writes: `GET /api/cron/jobs`, `GET /api/cron/jobs/{id}`, `POST /api/cron/jobs`, `PUT /api/cron/jobs/{id}`, `GET /api/cron/delivery-targets`, `GET /api/cron/blueprints`.
- **What it does:** Defines every field the dashboard expects from (and sends to) the cron API, so a reimplementation can be byte-compatible with this SPA.
- **How it works:** TypeScript interfaces in `web/src/lib/api.ts`:
  - `CronJob` — `id` (string, required); `profile?: string|null`; `profile_name?: string|null`; `hermes_home?: string|null`; `is_default_profile?: boolean`; `name?: string|null`; `prompt?: string|null`; `script?: string|null`; `skills?: string[]|null`; `schedule?: {kind?: string; expr?: string; run_at?: string; display?: string}`; `schedule_display?: string|null`; `repeat?: CronJobRepeat|null`; `enabled: boolean`; `state?: string|null`; `deliver?: string|null`; `model?: string|null`; `provider?: string|null`; `base_url?: string|null`; `no_agent?: boolean|null`; `context_from?: string[]|string|null`; `enabled_toolsets?: string[]|null`; `workdir?: string|null`; `last_run_at?: string|null`; `next_run_at?: string|null`; `last_status?: string|null`; `last_error?: string|null`; `last_delivery_error?: string|null`; `last_fire_error?: {at?: string|null; detail?: string|null}|null`. (`enabled` is the only required field besides `id`; `profile`, `profile_name`, `hermes_home` and `is_default_profile` are added by `_annotate_cron_job` server-side, not stored on the job.)
  - `CronJobRepeat` — `{times: number|null; completed?: number}`.
  - `CronJobMutation` — the create/update body: `{name?, prompt?, schedule?, deliver?, skills?: string[], provider?: string|null, model?: string|null, base_url?: string|null, script?: string|null, no_agent?: boolean, context_from?: string[]|null, enabled_toolsets?: string[]|null, workdir?: string|null}`. Note `context_from` is an **array** on the wire even though the form edits it as newline text, and the nullable fields are how a field gets cleared.
  - `CronDeliveryTarget` — `{id: string; name: string; home_target_set: boolean; home_env_var: string|null}`.
  - `AutomationBlueprint` — `{key, title, description, category, tags: string[], fields: AutomationBlueprintField[], command: string, appUrl: string}` (the API additionally returns `schedule` and `scheduleHuman`, which this interface does not declare and the page therefore ignores).
  - `AutomationBlueprintField` — `{name: string; type: "time"|"enum"|"text"|"weekdays"; label: string; default: string|null; options: string[]; optional: boolean; strict?: boolean; help: string}`; `strict: false` means the options are suggestions and any value is accepted (the `deliver` slot).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a (type declarations).
- **Config / env:** n/a.
- **Edge cases / guards:** `context_from` is typed `string[] | string | null` on read because raw store rows may hold either shape; `cronJobFormFromJob` normalises via `splitCronList`. `schedule` is optional, so a legacy row with only `schedule_display` still renders (via the `describeSchedule` fallback chain).
- **Rebuild notes:** Keep the read shape a superset of the write shape and annotate profile provenance server-side; never make the client compute which profile a row came from.

### Client data contract — Skills page types (`web/src/lib/api.ts`)  `id: web-b.skills-client-types`
- **Surface:** API
- **Where:** The JSON behind `/skills`: `GET /api/skills`, `GET /api/tools/toolsets`, `GET /api/skills/hub/sources`, `GET /api/skills/hub/search`, `GET /api/skills/hub/preview`, `GET /api/skills/hub/scan`.
- **What it does:** Defines every field the skills list, toolset grid and hub browser read.
- **How it works:** Interfaces in `web/src/lib/api.ts`:
  - `SkillInfo` — `{name: string; description: string; category: string; enabled: boolean}`. Note the backend also returns `usage` and `provenance` (`hub` | `bundled` | `agent`); the client type does **not** declare them, so the web SPA cannot show usage counts or provenance badges (the desktop's own type does).
  - `ToolsetInfo` — `{name, label, description, platform, platform_label, enabled, configured, tools: string[]}`.
  - `SkillHubResult` — `{name, description, source, identifier, trust_level, repo: string|null, tags: string[]}`.
  - `SkillHubSource` — `{id, label, rate_limited?: boolean (GitHub only), available?: boolean (hermes-index only)}`.
  - `SkillHubSourcesResponse` — `{sources: SkillHubSource[]; index_available: boolean; featured: SkillHubResult[]; installed: Record<string, SkillHubInstalledEntry>}`. (The API also returns a per-source `searchable` boolean, computed as `!(index_available && id ∈ {github, skills-sh, clawhub, lobehub, well-known})` — when the centralized index is up it already subsumes those API sources, so a per-source fan-out should skip them to avoid ~70 GitHub calls per keystroke. `SkillHubSource` does not declare it and this SPA ignores it.)
  - `SkillHubInstalledEntry` — `{name: string|null; trust_level: string|null; scan_verdict: string|null}` — the lock-file row that drives the `installed` badge.
  - `SkillHubSearchResponse` — `{results: SkillHubResult[]; source_counts: Record<string, number>; timed_out: string[]; installed: Record<string, SkillHubInstalledEntry>}`.
  - `SkillHubPreview` — `SkillHubResult`'s fields plus `{skill_md: string; files: string[]}` (bundle-relative paths; binary files come back as the literal `(binary file)`).
  - `SkillHubScan` — `{name, identifier, source, trust_level, verdict: string ("safe"|"caution"|"dangerous"), summary: string, policy: "allow"|"ask"|"block", policy_reason: string, findings: SkillHubScanFinding[], severity_counts: Record<string, number>}`. The API additionally returns an advisory `tier1` block which this interface omits and the page never renders.
  - `SkillHubScanFinding` — `{severity: string; category: string; file: string; line: number; description: string}`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `severity_counts` is an open `Record<string, number>`, so a new severity tier renders with the Badge default tone rather than breaking (`SEVERITY_TONE` has no entry for it). `identifier` is the install/preview/scan key everywhere — names are not unique across sources.
- **Rebuild notes:** Model hub results as `{source, identifier, trust_level}` triples and keep the installed-state map a separate lookup so badges do not need a second round-trip per row.

### Client data contract — Plugins page types (`web/src/lib/api.ts`)  `id: web-b.plugins-client-types`
- **Surface:** API
- **Where:** The JSON behind `/plugins`: `GET /api/dashboard/plugins`, `GET /api/dashboard/plugins/hub`, `GET /api/dashboard/plugins/rescan`, `POST /api/dashboard/agent-plugins/install`, `POST /api/dashboard/agent-plugins/{name}/enable|disable|update`, `DELETE /api/dashboard/agent-plugins/{name}`, `PUT /api/dashboard/plugin-providers`, `POST /api/dashboard/plugins/{name}/visibility`, and the memory-provider routes `GET/PUT /api/memory/providers/{name}/config`, `POST /api/memory/providers/{name}/setup`, `PUT /api/memory/provider`.
- **What it does:** Defines every field the plugin hub rows, the orphan list and the memory/context provider forms read and write.
- **How it works:** Interfaces in `web/src/lib/api.ts`:
  - `PluginManifestResponse` — `{name, label, description, icon, version, tab: {path: string; position?: string; override?: string; hidden?: boolean}, slots?: string[], entry: string, css?: string|null, has_api: boolean, source: string}` — the parsed `dashboard/manifest.json`.
  - `HubAgentPluginRow` — `{name, version, description, source, runtime_status: "disabled"|"enabled"|"inactive", has_dashboard_manifest: boolean, dashboard_manifest: PluginManifestResponse|null, path: string, can_remove: boolean, can_update_git: boolean, auth_required: boolean, auth_command: string, user_hidden: boolean}`.
  - `PluginsHubProviders` — `{memory_provider: string; memory_options: MemoryProviderInfo[]; context_engine: string; context_options: Array<{name: string; description: string}>}`.
  - `PluginsHubResponse` — `{plugins: HubAgentPluginRow[]; orphan_dashboard_plugins: PluginManifestResponse[]; providers: PluginsHubProviders}`.
  - `AgentPluginInstallRequest` — `{identifier: string; force?: boolean; enable?: boolean}` (the two switches in the install card).
  - `AgentPluginInstallResponse` — `{ok: boolean; plugin_name?: string; warnings?: string[]; missing_env?: string[]; after_install_path?: string|null; enabled?: boolean; error?: string}`. (`after_install_path` points at the plugin's `after-install.md`; this SPA never opens it. The scan-blocked shape `{scan_blocked, scan_verdict, scan_findings[]}` is not declared here, which is why blocked installs only surface their `error` text.)
  - `AgentPluginUpdateResponse` — `{ok: boolean; name?: string; output?: string; unchanged?: boolean; error?: string}` (`output` is the raw `git pull` output).
  - `PluginProvidersPutRequest` — `{memory_provider?: string; context_engine?: string}`.
  - `MemoryProviderInfo` — `{name, description, available: boolean, configured: boolean, status: "ready"|"needs_config"|"unavailable"|"missing", setup?: MemoryProviderSetupInfo}`.
  - `MemoryProviderField` — `{key, label, kind: "text"|"secret"|"select"|"boolean"|"integer"|"number", description, placeholder, required: boolean, value: string|boolean|number, is_set: boolean, options: MemoryProviderFieldOption[], url: string, minimum?: number|null, maximum?: number|null, step?: number|null, when?: Record<string, string|boolean|number>|null}`.
  - `MemoryProviderFieldOption` — `{value: string; label: string; description?: string}`.
  - `MemoryProviderSetupInfo` — `{pip_dependencies: string[]; external_dependencies: MemoryProviderExternalDependency[]; required_env: string[]; dependencies_installed: boolean}`.
  - `MemoryProviderExternalDependency` — `{name: string; install: string; check: string}` (the two commands the `SetupCommandBlock`s show).
  - `MemoryProviderSetupResult` — `{kind: string; name: string; status: string; command: string; returncode: number|null; stdout: string; stderr: string}`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `runtime_status` has exactly three values and is **not** the same as "installed" — every bundled plugin is `inactive` until it appears in `plugins.enabled`. `status` on a provider is computed server-side from availability + configuration; the page never derives it.
- **Rebuild notes:** One aggregate hub GET carrying rows, orphans and provider options avoids five round-trips per page load; keep field schemas declarative so new providers need no client change.

### Client data contract — MCP page types (`web/src/lib/api.ts`)  `id: web-b.mcp-client-types`
- **Surface:** API
- **Where:** The JSON behind `/mcp`: `GET /api/mcp/servers`, `POST /api/mcp/servers`, `PUT /api/mcp/servers`, `DELETE /api/mcp/servers/{name}`, `PUT /api/mcp/servers/{name}/enabled`, `POST /api/mcp/servers/{name}/test`, `POST /api/mcp/servers/{name}/auth`, `GET /api/mcp/oauth/flows/{flow_id}`, `GET /api/mcp/catalog`, `POST /api/mcp/catalog/install`.
- **What it does:** Defines every field the server cards, the add dialog, the test result line, the OAuth driver and the 65-entry catalog read.
- **How it works:** Interfaces and unions in `web/src/lib/api.ts` (+ `lib/mcp-server-create.ts`):
  - `McpTransport` (in `mcp-server-create.ts`) = `"http" | "stdio"`; `McpHttpAuth` = `"none" | "header" | "oauth"`.
  - `McpServer` — `{name: string; transport: "http"|"stdio"|"unknown"; url: string|null; command: string|null; args: string[]; env: Record<string, string>; auth: "header"|"oauth"|null; enabled: boolean; tools: string[]|null}`. `env` values are redacted server-side (`_redact_mcp_env`), so the card can only count them (`N env var(s)`), never show them. `transport: "unknown"` is what a malformed entry renders as (secondary badge tone).
  - `McpServerCreate` — `{name: string; url?: string; command?: string; args?: string[]; env?: Record<string, string>; auth?: McpHttpAuth; bearer_token?: string}`.
  - `McpTestResult` — `{ok: boolean; error?: string; tools: Array<{name: string; description: string}>}`. (The backend also returns `prompts` and `resources` counts and a per-tool `schema_chars`; the client type omits them.)
  - `McpOAuthFlow` — `{flow_id: string; server_name: string; status: "starting"|"authorization_required"|"approved"|"error"; authorization_url: string|null; error: string|null; tools?: Array<{name: string; description: string}>}` — `tools` is only populated by the `GET /api/mcp/oauth/flows/{flow_id}` snapshot, not by the initial `POST .../auth`.
  - `McpCatalogEntry` — `{name, description, source, transport: "http"|"stdio", auth_type: "api_key"|"oauth"|"none", required_env: Array<{name: string; prompt: string; required: boolean}>, command: string|null, args: string[], url: string|null, install_url: string|null, install_ref: string|null, bootstrap: string[], default_enabled: string[]|null, post_install: string, needs_install: boolean, installed: boolean, enabled: boolean}`. `default_enabled: null` means "all tools pre-checked"; `needs_install` marks git-bootstrap entries that clone and build locally. (The API also returns a `suggest {keywords, hosts}` block used by the desktop composer's brand pills; the client type omits it.)
  - `McpCatalogDiagnostic` — `{name: string; kind: string; message: string}` (`kind` is `future_manifest` or `invalid`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** `McpServer.auth` has no `"none"` member — the absence of auth is `null`, while `McpHttpAuth` (the form union) does have `"none"`; `buildMcpServerCreate` bridges the two by omitting `auth` entirely for `"none"`. `tools: string[]|null` on a server row is the configured include-list, not the live tool list (that comes from the test result).
- **Rebuild notes:** Keep the wire type for a configured server distinct from the type for a catalog entry, and never let secrets round-trip — redact on read and accept write-only on create.

---

## Handoffs
- Shared app shell on every page (sidebar links `CHAT … ACHIEVEMENTS`, `Restart Gateway`, `Update Hermes`, theme switcher `HERMES TEAL`, language switcher `EN`, status strip `Gateway Status: Off Active Sessions: 0`, `Collapse`, `Open/Close navigation`, page-header slots, `ProfileScopeBanner`/global profile switcher, `PluginSlot` mechanics, `useModalBehavior`, toast/confirm primitives from `@nous-research/ui`) → web-a.
- Chat page handling of `/chat?learn=<text>` (the `/learn` slash-command turn triggered by the Skills page) → web-a / gateway slash-commands shard.
- Plugin-provided dashboard tabs `/kanban` and `/achievements` (bundled dashboard plugins with their own API mounts `/api/plugins/kanban/`, `/api/plugins/hermes-achievements/`) → web-a or a plugins/core shard.
- `GET /api/actions/{name}/status` generic action framework and the other registered actions (`gateway-restart`, `hermes-update`, `doctor`, `security-audit`, `backup`, `import`, `checkpoints-prune`, `curator-run`, `prompt-size`, `computer-use-grant`) → web-c (System page) / core.
- Toolset endpoints not used by this SPA: `GET/PUT /api/tools/toolsets/{name}/models|model`, `GET /api/tools/terminal/backends`, `PUT /api/tools/terminal/backend`, `GET /api/tools/computer-use/status`, `POST /api/tools/computer-use/permissions/grant` → desktop shard / web-c.
- Memory page endpoints `GET /api/memory`, `POST /api/memory/reset`, `surface=declared` provider config schema → web-c (Config/System) or desktop.
- Cron engine internals (`cron/jobs.py` store format, `cron/scheduler.py` ticker, delivery, Chronos provider plugin, `hermes cron …` CLI, `/blueprint` slash command, `hermes://blueprint/...` deep-links) → cli / core / gateway shards.
- Skills hub internals (`tools/skills_hub.py` sources, taps, lock file, `tools/skills_guard.py` scan rules, SkillEvaluator Tier-1) and `hermes skills …` CLI → cli / core shards; the skills "curator" and "bundles" concepts named in the task brief do not appear on this SPA page (only `curator-run` exists as an action name in `web_server.py:4585`) → CLI shard.
- Plugin loader semantics (`hermes_cli/plugins.py`, `plugins_cmd.py` install core, scan policy, `plugin.yaml` manifest schema, `provides_tools`, `requires_env`) → core/plugins shard.
- MCP runtime (`tools/mcp_tool.py`, `tools/mcp_oauth*.py`, `hermes_cli/mcp_security.validate_mcp_server_entry` rules, `hermes mcp …` CLI incl. `picker`, `configure`, `login`) → cli / core shards; the "picker" named in the brief is the curses CLI picker, not a web feature.
- Profile Builder page's use of `MCPServerCreate` normalisation (`_normalize_mcp_server_create` shared) → web-c.
- Desktop app's cron run-history view (consumer of `GET /api/cron/jobs/{id}/runs`) → desktop shard.
- Memory-provider plugin implementations themselves (`plugins/memory/<name>`: byterover, hindsight, holographic, honcho, mem0, openviking, retaindb, supermemory — their tools, hooks, storage formats and the `setup` manifests whose fields the Plugins page renders) → core/plugins shard.
- The `skills` bundled catalog as *content* (the 53 `skills/**/SKILL.md` files, their frontmatter conventions, `references/`, `scripts/`) → a skills/content shard; this shard only records the 53 names/descriptions as rendered page text.
- The Hermes skills index service behind `index_available` / `featured` (`hermes-index` source, its ranking and the `official/<category>/<name>` identifier scheme) → core/skills-hub shard.
- Plugin "packs" and "capabilities" named in the task brief: no such surface exists on the web `/plugins` page at v2026.8.31 (grep for `pack`/`capabilit` in `PluginsPage.tsx` returns nothing) — they live in the CLI/desktop plugin surfaces → cli / desktop shards.
- The `@nous-research/ui` primitives whose DOM contract this shard documents (`Select` as a `role="combobox"` div, `Switch`, `Segmented`, `Dialog`, `Toast`, `ConfirmDialog`, `DeleteConfirmDialog`, `CopyButton`, `CommandBlock`, `PanelItem`, `FilterGroup`) → web-a / design-system shard.
- `@hermes/shared` (`apps/shared/src/`) beyond `createCronTriggerController` — the rest of the package shared by web and desktop → desktop / web-a shard.
- `web/src/lib/api.ts` transport layer itself (`fetchJSON`, `pluginPath`, session-token/ticket auth header, `?profile=` auto-injection, base-path resolution) → web-a.
- Memory-provider registry internals (`plugins.memory.discover_memory_providers`, per-provider manifests, `_install_memory_provider_setup` runner) and the `/api/memory/*` routes' non-plugins-page uses → web-c / core.
- `cron/blueprint_catalog.py` beyond the dashboard-facing serialisation (`AutomationBlueprint` dataclass, `fill_blueprint` schedule resolution, `prompt_template`s, the `/blueprint` slash command and the `hermes://` desktop protocol handler that consumes `appUrl`) → gateway / desktop / core shards.
