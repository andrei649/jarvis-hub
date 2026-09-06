# CLI Part C — cron / sync / webhook / peer / portal / kanban / project

This shard documents seven top-level `hermes` CLI command groups and every one of their
sub-commands, flags, positional arguments, aliases and printed output strings, as observed in
the live install of hermes-agent v2026.8.31: `hermes cron` (17 sub-commands), `hermes sync` (8),
`hermes webhook` (7 incl. aliases), `hermes peer` (10 incl. aliases), `hermes portal` (5),
`hermes kanban` (~50 sub-commands including the `boards` sub-group) and `hermes project` (12).
Storage layers (`~/.hermes/cron/jobs.json`, `cron/executions.db`, `cron/notepad.db`,
`<root>/kanban.db` + `kanban/boards/<slug>/`, `$HERMES_HOME/projects.db`,
`~/.hermes/webhook_subscriptions.json`, `bot_peers` in `config.yaml` + `HERMES_PEER_*_KEY` in
`~/.hermes/.env`, and `~/.hermes/skills/.sync_state`) are described only to the depth needed to
rebuild the CLI behaviour.
It deliberately leaves to sibling shards: the gateway slash commands (`/cron`, `/kanban`,
`/webhook`) and Telegram/Discord surfaces, the `cronjob`/`kanban` **model tools** and their JSON
schemas, the Web-dashboard Cron/Kanban/Projects pages, the Desktop app, the config-key reference
(`cron.*`, `kanban.*`, `sync.*`, `peer.*` keys are named here but defined in the config shards),
and every other top-level CLI command (`gateway`, `auth`, `skills`, `mcp`, `setup`, …).

## 1. `hermes cron` — scheduled jobs

### Cron command group  `id: cli-c.cron-group`
- **Surface:** CLI
- **Where:** `hermes cron [--accept-hooks] {list,create,add,edit,pause,resume,run,remove,rm,delete,status,runs,history,incidents,notepad,doctor,tick}`. Group help title: `Manage scheduled tasks`; short help in the root command list: `Cron job management`.
- **What it does:** Umbrella for creating, editing and inspecting the agent's scheduled jobs (the same jobs the gateway ticker fires every 60 s). With no sub-command it behaves exactly like `hermes cron list`.
- **How it works:** Parser built in `hermes_cli/subcommands/cron.py:15` (`build_cron_parser`), dispatched via `cron_parser.set_defaults(func=cmd_cron)` at `hermes_cli/subcommands/cron.py:330`. `cmd_cron` (`hermes_cli/main.py:5626`) imports `hermes_cli/cron.py:cron_command` (`hermes_cli/cron.py:954`), which routes on `args.cron_command`. Most mutating actions go through `_cron_api()` (`hermes_cli/cron.py:46`), which calls the **agent-facing model tool** `tools/cronjob_tools.py:cronjob(...)` and `json.loads` its string result — CLI and LLM share one code path. Job records live in `~/.hermes/cron/jobs.json` (`cron/jobs.py:85` `JOBS_FILE = CRON_DIR / "jobs.json"`, `cron/jobs.py:84` `CRON_DIR = HERMES_DIR / "cron"`); per-run outputs under `~/.hermes/cron/output/` (`cron/jobs.py:118`).
- **Inputs / options:** `-h`, `--help`; `--accept-hooks` (added to the group parser AND to `cron run` / `cron tick` by `add_accept_hooks_flag`, `hermes_cli/subcommands/cron.py:328-329`) — "Auto-approve unseen shell hooks without a TTY prompt (equivalent to HERMES_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."; one of the 17 sub-command tokens.
- **Outputs / side effects:** No side effect by itself; unknown sub-command prints `Unknown cron command: <x>` + `Usage: hermes cron [list|create|edit|pause|resume|run|remove|status|runs|doctor|tick]` and `sys.exit(1)` (`hermes_cli/cron.py:999-1002`).
- **Config / env:** `cron.allow_agent_scheduling` (default `false`), `cron.preflight` (`true`), `cron.model_drift_guard` (`true`), `cron.model` (`""`), `cron.model_provider` (`""`), `cron.provider` (`""`), `cron.wrap_response` (`true`), `cron.mirror_delivery` (`false`), `cron.max_parallel_jobs` (`null`), `cron.output_retention` (`50`), `cron.script_timeout_seconds` (`3600`), `cron.session_db_timeout_seconds` (`10`), `cron.media_send_timeout_seconds` (`300`), `cron.chronos.portal_url` (`https://portal.nousresearch.com`), `cron.chronos.callback_url`, `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`. Env: `HERMES_HOME` (profile root), `HERMES_ACCEPT_HOOKS=1`, `_HERMES_GATEWAY=1` (in-gateway marker used by the lifecycle guard).
- **Edge cases / guards:** Jobs only fire while a gateway process runs the ticker (there is no standalone cron daemon) unless a non-builtin provider (Chronos) is configured. Gateway-lifecycle commands inside job prompts are blocked by `cron/lifecycle_guard.py` (`contains_gateway_lifecycle_command`, re-exported as `_contains_gateway_lifecycle_command` at `hermes_cli/cron.py:25` and reused by `tools/terminal_tool.py` at execution time).
- **Rebuild notes:** One argparse group + one JSON job store + a ticker thread. A better version would make the ticker a supervised OS-level service independent of the gateway, so `next_run_at` can never silently pass.

### Cron scheduler provider selection (`cron.provider`)  `id: cli-c.cron-provider`
- **Surface:** Config / Core
- **Where:** `config.yaml` key `cron.provider`; observable through `hermes cron status` (which reports `✓ Cron provider: <name> …` for a non-builtin provider) and through the silence of the gateway warning in `hermes cron list` / `create`.
- **What it does:** Chooses *when* a due job fires — the built-in in-process 60 s ticker, the NAS-managed `chronos` provider for scale-to-zero hosted gateways, or a custom plugin — without changing what firing means.
- **How it works:** `cron/scheduler_provider.py`. `resolve_cron_scheduler()` (line 476) reads `cfg_get(load_config(), "cron", "provider", default="")`. Empty, `builtin`, `in-process` or `inprocess` → `InProcessCronScheduler` (the historical 60 s daemon-thread ticker). Any other name is loaded via `plugins.cron_providers.load_cron_scheduler(name)`; custom providers live under `plugins/cron_providers/<name>/` (docs also cite `plugins/cron/<name>/` and `$HERMES_HOME/plugins/<name>/`). Providers decide **only** timing — execution and delivery stay in `cron.scheduler.run_job` / `_deliver_result` and are shared by every provider, which "must never reimplement agent construction or delivery" (module docstring). The interface is marked **⚠️ EXPERIMENTAL**: validated by exactly one consumer until an external provider shakes it out, so signatures may change without a deprecation cycle, and any growth must be additive. `scheduler_for_profile_mode` (line 516) **fails closed to the built-in multiplex ticker** when the gateway multiplexes profiles, because external providers own one unscoped remote registry/client and cannot safely reconcile several profile stores from one process.
- **Inputs / options:** `cron.provider` (`""` default); `cron.chronos.portal_url` (`https://portal.nousresearch.com`), `cron.chronos.callback_url` (`""`), `cron.chronos.expected_audience` (`""`), `cron.chronos.nas_jwks_url` (`""`).
- **Outputs / side effects:** Determines whether the in-process ticker thread starts at all. An external provider arms one external one-shot per job and is fired by an authenticated, NAS-mediated webhook.
- **Config / env:** as above.
- **Edge cases / guards:** A provider that is missing, fails to load, or reports `is_available() == False` falls back to the built-in **with a warning** — cron must never be left without a trigger (log lines: `cron.provider '<n>' not found; using built-in ticker`, `cron.provider '<n>' not available; using built-in ticker`, `Failed to load cron.provider '<n>' (<e>); using built-in ticker`). The built-in ticker also carries an EMFILE backoff: `_backoff_wait_seconds` doubles the wait per consecutive fd-exhaustion failure, capped at `_EMFILE_BACKOFF_MAX_SECONDS = 15 * 60`; any other failure resets the counter.
- **Rebuild notes:** An ABC with `name`, `is_available()`, `start(...)` and a registry that falls back to the built-in on every failure path. Better: make the interface stable and carry explicit profile identity through lifecycle and webhook calls so external providers can serve multiplexed gateways.

### `hermes cron list` — list scheduled jobs  `id: cli-c.cron-list`
- **Surface:** CLI
- **Where:** `hermes cron list [--all]`; also the default when `hermes cron` is run bare. Help: `List scheduled jobs`.
- **What it does:** Prints every scheduled job with its schedule, next run, delivery targets, skills, script/monitor/workdir settings and last-run status, then warns if the gateway isn't running.
- **How it works:** `cron_list()` at `hermes_cli/cron.py:136` calls `cron.jobs.list_jobs(include_disabled=show_all)`. For each job it derives the displayed state with `cron.jobs.effective_job_state(job)` (`cron/jobs.py:639`) — a job with `enabled=true` is never shown as paused; terminal `completed`/`error` win. `repeat` and `deliver` are coalesced with `or {}` / `or ["local"]` because they can be present-but-null in the record.
- **Inputs / options:** `--all` — "Include disabled jobs" (`store_true`, `hermes_cli/subcommands/cron.py:24`); `-h/--help`.
- **Outputs / side effects:** Read-only. Empty case prints `No scheduled jobs.` (DIM) + `Create one with 'hermes cron create ...' or the /cron command in chat.` Otherwise a CYAN box: `┌───…───┐` / `│                         Scheduled Jobs                                  │` / `└───…───┘`, then per job: `  <job_id> [active]|[paused]|[completed]|[disabled]` and the indented labels `Name:`, `Schedule:`, `Repeat:` (`completed/times` or `∞`), `Next run:`, `Deliver:` (comma-joined), `Skills:` (only if any), `Script:` (if any), `Monitor:  <src> (agent runs only on output change)` plus `Changed:   <last_changed_at>`, `Mode:      no-agent (script stdout delivered directly)`, `Workdir:`, `Last run:  <ts>  ok` / `<status>: <last_error>` with `  (<n> failures in a row)` when `failure_streak >= 2`, `Execution: <status>  <id>`, `⚠ Delivery failed: <err>`, `⚠ Missed scheduled fire: <at>  <detail>`.
- **Config / env:** Reads `~/.hermes/cron/jobs.json`; `HERMES_HOME` selects the profile.
- **Edge cases / guards:** Ends with `_warn_if_gateway_not_running()` (`hermes_cli/cron.py:110`) which prints `  ⚠  Gateway is not running — jobs won't fire automatically.`, `     Start it with: hermes gateway install`, `                    sudo hermes gateway install --system  # Linux servers`, `     Check status:  hermes cron status` — but only when liveness is definitively `False`; a probe failure (`None`) or a non-builtin provider stays silent.
- **Rebuild notes:** `list_jobs(include_disabled)` + a fixed-order field printer. Better: add `--json` and column alignment; today the output is only human-readable.

### `hermes cron create` (alias `add`) — create a scheduled job  `id: cli-c.cron-create`
- **Surface:** CLI
- **Where:** `hermes cron create <schedule> [prompt] [options]`, alias `hermes cron add`. Help: `Create a scheduled job`.
- **What it does:** Registers a new scheduled job: an LLM prompt, a shell/Python script, a monitor watcher, or a mix, with an optional delivery target and per-job model/effort pins.
- **How it works:** `cron_create(args)` at `hermes_cli/cron.py:680` forwards everything to `_cron_api(action="create", …)` → `tools/cronjob_tools.py:cronjob` → `cron.jobs.create_job()` (`cron/jobs.py:2207`). Skills are normalised by `_normalize_skills` (`hermes_cli/cron.py:30`, dedupes + strips, `--skill` legacy scalar merged with the repeatable list). The schedule string is parsed by `cron.jobs.parse_schedule` (`cron/jobs.py:962`). The gateway-lifecycle guard lives inside `create_job`, so it fires for both this CLI and the agent's `cronjob` tool; a block raises `GatewayLifecycleBlocked`, surfaced as `result["error"]`.
- **Inputs / options:** positional `schedule` — "Schedule like '30m', 'every 2h', or '0 9 * * *'"; positional optional `prompt` — "Optional self-contained prompt or task instruction"; `--name NAME`; `--deliver DELIVER` ("origin, local, telegram, discord, signal, platform:chat_id, or bot-chat[:profile]"); `--repeat REPEAT` (int); `--skill SKILLS` (repeatable, dest `skills`); `--script SCRIPT` (path under `~/.hermes/scripts/`; `.sh`/`.bash` via bash, else Python); `--no-agent` (store_true, default False); `--monitor-script MONITOR_SCRIPT`; `--monitor-url MONITOR_URL`; `--workdir WORKDIR`; `--model MODEL`; `--provider MODEL_PROVIDER` (dest `model_provider`); `--reasoning-effort REASONING_EFFORT` (none|minimal|low|medium|high|xhigh|max|ultra); `--continuity` (store_const True, default None); `-h/--help`.
- **Outputs / side effects:** Appends a job record to `~/.hermes/cron/jobs.json`. On success prints GREEN `Created job: <job_id>` then `  Name: …`, `  Schedule: …`, `  Skills: a, b` (if any), `  Script: …`, `  Monitor: <src> (agent runs only on output change)`, `  Mode: no-agent (script stdout delivered directly)`, `  Continuity: on (each run sees the previous run's output)`, `  Workdir: …`, `  Next run: <iso>`; then the gateway warning. Failure prints RED `Failed to create job: <error>` and returns 1.
- **Config / env:** `cron.model` / `cron.model_provider` are the fallback when `--model`/`--provider` are omitted; `agent.reasoning_effort` + `agent.reasoning_overrides` are overridden by `--reasoning-effort`; `cron.allow_agent_scheduling` gates the agent (not the CLI) from creating jobs.
- **Edge cases / guards:** `--monitor-script` and `--monitor-url` are mutually exclusive and both are incompatible with `--no-agent`; `--no-agent` requires a script; scripts must resolve **inside** `HERMES_HOME/scripts` (containment enforced, see `_script_health_issue`, `hermes_cli/cron.py:567`); `--model` is user-owned — the agent's `cronjob` tool cannot set it.
- **Rebuild notes:** `create_job(prompt, schedule, name, repeat, deliver, origin, skill, skills, model, provider, base_url, script, context_from, enabled_toolsets, workdir, no_agent, attach_to_session, monitor_script, monitor_url, reasoning_effort)` is the whole contract (`cron/jobs.py:2207-2228`). Better: validate mutually-exclusive flags in argparse itself instead of deep inside the store.

### Cron schedule syntax  `id: cli-c.cron-schedule-syntax`
- **Surface:** CLI / Core
- **Where:** the `schedule` positional of `hermes cron create` and `--schedule` of `hermes cron edit`.
- **What it does:** Accepts five schedule dialects and normalises them into `{"kind": "once"|"interval"|"cron", …, "display": …}`.
- **How it works:** `cron.jobs.parse_schedule` (`cron/jobs.py:962`). Order of attempts: (1) `every <rest>` → `_natural_every_to_cron(rest)`; when it yields a cron expression it is validated with `croniter` and stored as `{"kind":"cron","expr":…, "display": original}`, otherwise `parse_duration(rest)` → `{"kind":"interval","minutes":n,"display":"every Nm"}`. (2) Bare natural phrases without `every ` (e.g. `weekdays at 9am`, `monday at 9:30`, `daily at 7am`) via the same helper. (3) A 5-or-6-field cron expression — fields matched with `^[A-Za-z\d\*\-,/]+$` so `JAN-DEC`, `MON-FRI`, `MON,WED,FRI` are accepted — validated by `croniter`. (4) ISO timestamps (containing `T` or matching `^\d{4}-\d{2}-\d{2}`) → `{"kind":"once","run_at":…}`; naive timestamps are anchored to the **configured Hermes timezone**, not the server's, so `20:07` means 20:07 on the clock the due-check uses. (5) `in <duration>` → one-shot `{"kind":"once","display":"once in <d>"}`. (6) A bare duration (`30m`, `2h`, `1d`) → **recurring** interval (documented contract; was a one-shot before the 2026-08-04 fix).
- **Inputs / options:** examples from the docstring: `30m`, `2h`, `every 30m`, `every 2h`, `every monday 9am`, `every day at 9am`, `0 9 * * *`, `2026-02-03T14:00`, `in 30m`, `in 2h`, `weekdays at 9am`, `monday at 9:30`, `daily at 7am`.
- **Outputs / side effects:** The parsed dict is stored under the job's `schedule` field; `schedule_display` is what `cron list` prints.
- **Config / env:** Timezone comes from the Hermes time layer (`hermes_time.now()`), not the OS local zone.
- **Edge cases / guards:** Weekday/time phrases and cron expressions require the optional `croniter` package — otherwise `ValueError("Weekday/time schedules like 'every monday 9am' require the 'croniter' package. Install with: pip install croniter")` / `"Cron expressions require 'croniter' package. …"`. An unparseable string raises the multi-line help: `Invalid schedule '<x>'. Use:` + `  - Interval: '30m', 'every 30m', 'every 2h' (recurring)` + `  - One-shot delay: 'in 30m', 'in 2h' (fires once)` + `  - Weekly/daily: 'every monday 9am', 'weekdays at 9am' (recurring)` + `  - Cron: '0 9 * * *' (cron expression)` + `  - Timestamp: '2026-02-03T14:00:00' (one-shot at time)`.
- **Rebuild notes:** A cascade of regex/keyword tests with croniter as the only hard dependency. Better: return a structured parse error naming which dialect was closest.

### Cron monitor mode (`--monitor-script` / `--monitor-url`)  `id: cli-c.cron-monitor-mode`
- **Surface:** CLI / Core
- **Where:** `hermes cron create --monitor-script <path>` / `--monitor-url <url>`; `hermes cron edit --monitor-script`/`--monitor-url` (empty string clears). Shown in `cron list` as `Monitor:   <src> (agent runs only on output change)` and `Changed:   <ts>`.
- **What it does:** Runs a cheap "source" (script or bounded HTTP GET) before the agent on every tick; if its output bytes are unchanged the agent run is suppressed entirely (no LLM, no delivery), otherwise a diff block is injected and the agent runs.
- **How it works:** `cron/monitor.py`. Output is hashed as **exact bytes** — no timestamp stripping, no whitespace normalisation. State: `job["monitor_state"]` in `jobs.json` (`last_output_hash`, `last_changed_at`) plus `OUTPUT_DIR/<job_id>/monitor_last_output.txt` (`_SNAPSHOT_FILENAME`, `cron/monitor.py:52`) holding the previous text so a diff can be rendered. On change the prompt gets a `## MONITOR CHANGE DETECTED` block (`cron/monitor.py:186`) containing a unified diff plus the new output. A source failure is treated as an ERROR, never a change, and the stored hash is left untouched so recovery to the previous output still suppresses.
- **Inputs / options:** `--monitor-script <path under ~/.hermes/scripts/>`; `--monitor-url <http(s) URL>`; on `edit`, empty string clears either.
- **Outputs / side effects:** Unchanged ticks are recorded as a silent `no_change` run; changed ticks produce a normal agent run + delivery. Writes `monitor_last_output.txt`.
- **Config / env:** Script execution honours `cron.script_timeout_seconds` (3600).
- **Edge cases / guards:** Caps — `MAX_DIFF_CHARS = 4000` (diff truncated with `\n... [diff truncated]`), `MAX_OUTPUT_CHARS = 8000` (`\n... [output truncated]`), `URL_TIMEOUT_SECONDS = 30`, `MAX_URL_BYTES = 262_144` (256 KiB, body hard-truncated). Mutually exclusive with each other; incompatible with `--no-agent`. Unstable output (timestamps) makes every tick look like a change.
- **Rebuild notes:** hash(previous) != hash(current) → run; store the raw previous output for diffing. Better: optional normalisation rules (regex strip) per job so noisy sources are usable.

### Cron no-agent mode (`--no-agent` / `--agent`)  `id: cli-c.cron-no-agent`
- **Surface:** CLI
- **Where:** `hermes cron create --no-agent --script <path>`; `hermes cron edit --no-agent` / `--agent`. Shown in `cron list` as `Mode:      no-agent (script stdout delivered directly)`.
- **What it does:** Skips the LLM completely — the script *is* the job and its stdout is delivered verbatim; empty stdout means silence.
- **How it works:** `no_agent=True` on the job record (`cron/jobs.py:create_job` docstring lines for `no_agent`). `--no-agent` on `create` is `store_true` default `False` (`hermes_cli/subcommands/cron.py:60`); on `edit` it is a tri-state `store_const True` with `--agent` as `store_const False` on the same dest (`hermes_cli/subcommands/cron.py:163,175`) so "leave unchanged" is representable.
- **Inputs / options:** `--no-agent`; `--agent` (edit only); requires `--script` (or an existing script on the job).
- **Outputs / side effects:** Delivery of raw stdout to the job's `deliver` target; no LLM tokens consumed.
- **Config / env:** `cron.script_timeout_seconds` bounds the script; `workdir` (if set) is still applied as the script's cwd.
- **Edge cases / guards:** `cron doctor` reports `no-agent job has no script` when the pair is inconsistent (`hermes_cli/cron.py:634`). Incompatible with monitor mode.
- **Rebuild notes:** A boolean that swaps "prompt the model" for "exec the script, deliver stdout". Better: expose exit-code semantics (non-zero = incident) as an explicit flag.

### Cron run-to-run continuity (`--continuity` / `--no-continuity`)  `id: cli-c.cron-continuity`
- **Surface:** CLI
- **Where:** `hermes cron create --continuity`; `hermes cron edit --continuity` / `--no-continuity`. Printed as `  Continuity: on (each run sees the previous run's output)`.
- **What it does:** Injects the job's own previous output into its next prompt so the job can dedupe against what it already reported and continue where it left off (scouts, monitors, incremental digests).
- **How it works:** Sets `continuity` on the job; implemented as a self-referencing `context_from` job ref inside `cron.jobs`. The first run is unchanged (no previous output exists). `--no-continuity` turns it off while preserving other `context_from` job refs (`hermes_cli/subcommands/cron.py:206-215`).
- **Inputs / options:** `--continuity` (`store_const True`, default `None` — tri-state so edit can leave it alone); `--no-continuity` (`store_const False`, edit only).
- **Outputs / side effects:** Larger prompts on every run after the first; previous outputs read from `~/.hermes/cron/output/<job_id>/`.
- **Config / env:** `cron.output_retention` (default 50) bounds how many outputs are kept.
- **Edge cases / guards:** Injected context is truncated (the 8 KB `context_from` truncation in `cron/scheduler.py`, mirrored by `MAX_OUTPUT_CHARS` in monitor mode).
- **Rebuild notes:** Store last N outputs per job; prepend the latest to the prompt. Better: summarise the previous output instead of pasting it, to bound growth.

### `hermes cron edit` — edit an existing job  `id: cli-c.cron-edit`
- **Surface:** CLI
- **Where:** `hermes cron edit <job_id> [options]`. Help: `Edit an existing scheduled job`.
- **What it does:** Mutates any field of an existing job in place, including three-way skill editing (replace / add / remove / clear) and tri-state toggles.
- **How it works:** `cron_edit(args)` at `hermes_cli/cron.py:732`. First resolves the reference with `cron.jobs.resolve_job_ref(args.job_id)` (`cron/jobs.py:2477`) — accepts an ID or a name; an ambiguous name raises `AmbiguousJobReference`, whose message is printed followed by `  <id>  (name: '<name>')` for each candidate. Skill resolution order: `--clear-skills` → `[]`; else `--skill` replacement set; else existing minus `--remove-skill` plus `--add-skill` (order preserved, deduped). Then `_cron_api(action="update", …)`.
- **Inputs / options:** positional `job_id`; `--schedule SCHEDULE` ("New schedule"); `--prompt PROMPT`; `--name NAME`; `--deliver DELIVER`; `--repeat REPEAT` (int); `--skill SKILLS` (repeatable — *replaces* the set); `--add-skill ADD_SKILLS` (repeatable); `--remove-skill REMOVE_SKILLS` (repeatable); `--clear-skills` (store_true); `--script SCRIPT` (empty string clears); `--no-agent` / `--agent` (tri-state pair); `--continuity` / `--no-continuity` (tri-state pair); `--monitor-script` (empty clears); `--monitor-url` (empty clears); `--workdir` (empty clears); `--model` (empty clears the pin); `--provider MODEL_PROVIDER` (empty clears); `--reasoning-effort` (empty clears); `-h/--help`.
- **Outputs / side effects:** Rewrites the job in `jobs.json`. Prints GREEN `Updated job: <job_id>`, then `  Name:`, `  Schedule:`, `  Skills: a, b` or `  Skills: none`, `  Script:`, `  Monitor: … (agent runs only on output change)`, `  Mode: no-agent (script stdout delivered directly)`, `  Continuity: on (each run sees the previous run's output)`, `  Workdir:`. Failure: RED `Failed to update job: <error>`, exit 1. Unknown id: RED `Job not found: <ref>`, exit 1.
- **Config / env:** Same keys as create.
- **Edge cases / guards:** Ambiguous name references are refused rather than guessed. Clearing a value requires passing an **empty string**, not omitting the flag (omission = unchanged).
- **Rebuild notes:** Tri-state flags (`store_const` with `default=None`) are the crux — without them an edit cannot distinguish "false" from "not mentioned". Better: a `--set key=value` generic form plus a `--json` patch mode.

### `hermes cron pause` — pause a job  `id: cli-c.cron-pause`
- **Surface:** CLI
- **Where:** `hermes cron pause <job_id>`. Help: `Pause a scheduled job`.
- **What it does:** Stops a job from firing without deleting it.
- **How it works:** `_job_action("pause", args.job_id, "Paused")` (`hermes_cli/cron.py:808`, dispatched at `hermes_cli/cron.py:990`) → `_cron_api(action="pause", job_id=…)` → `cron.jobs.pause_job`. Sets `enabled=false` and a pause marker; `effective_job_state` then reports `paused`.
- **Inputs / options:** positional `job_id` — "Job ID to pause"; `-h/--help`.
- **Outputs / side effects:** GREEN `Paused job: <name> (<job_id>)`. Failure: RED `Failed to pause job: <error>`, exit 1.
- **Config / env:** n/a
- **Edge cases / guards:** A record with `enabled=true` but a stale pause marker is never displayed as paused (`effective_job_state`, guarding against the "list looked frozen while the fleet kept merging" failure mode).
- **Rebuild notes:** One boolean plus a marker timestamp. Better: `--until <ts>` for a self-expiring pause.

### `hermes cron resume` — resume / re-arm a job  `id: cli-c.cron-resume`
- **Surface:** CLI
- **Where:** `hermes cron resume [--at RUN_AT] [--run-now] <job_id>`. Help: `Resume a paused job`.
- **What it does:** Re-enables a paused job, or explicitly re-arms a *completed one-shot* to fire again at a given time or immediately.
- **How it works:** `cron_resume(args)` at `hermes_cli/cron.py:868`. With neither `--at` nor `--run-now` it is a plain `_job_action("resume", …, "Resumed")`. With exactly one of them it calls `cron.jobs.rearm_oneshot(job_id, run_at)` (`cron/jobs.py:2797`), using `cron.jobs._hermes_now().isoformat()` for `--run-now`.
- **Inputs / options:** positional `job_id` — "Job ID to resume"; `--at RUN_AT` — "Re-arm at an ISO-8601 time"; `--run-now` (store_true) — "Re-arm to run now"; `-h/--help`.
- **Outputs / side effects:** Plain resume: GREEN `Resumed job: <name> (<job_id>)` plus `  Next run: <iso>` when the record has one. Re-arm: GREEN `Re-armed job: <name> (<job_id>)` + `  Next run: <iso>`.
- **Config / env:** n/a
- **Edge cases / guards:** Passing **both** `--at` and `--run-now` prints RED `Use exactly one of --at or --run-now.` and exits 1 (the XOR test at `hermes_cli/cron.py:870`). Unknown/ambiguous refs: RED `Failed to re-arm job: <exc>` or `Job not found: <ref>`, exit 1.
- **Rebuild notes:** Resume = clear the pause flag + recompute `next_run_at`; re-arm = force `next_run_at` on a terminal one-shot. Better: allow relative re-arm (`--in 30m`).

### `hermes cron run` — trigger a job now  `id: cli-c.cron-run`
- **Surface:** CLI
- **Where:** `hermes cron run [--accept-hooks] <job_id>`. Help: `Run a job on the next scheduler tick`.
- **What it does:** Fires a job immediately (or arms it for the next tick) and reports whether it ran inline, was dispatched to the gateway's background worker, was skipped, or will run on the next tick.
- **How it works:** `_job_action("run", …, "Triggered")` (`hermes_cli/cron.py:808`). Before calling the API it sets `gateway.session_context._SESSION_ASYNC_DELIVERY` to `False` via a context token (reset in `finally`) so the run executes **synchronously** — a one-shot CLI process would otherwise orphan a background daemon thread mid-LLM-call, leaving the execution row stuck in `claimed` (issue #86721 in the source comment). Afterwards it inspects the returned job dict for `execution_mode == "background"` / `delegation_id`.
- **Inputs / options:** positional `job_id` — "Job ID to trigger"; `--accept-hooks`; `-h/--help`.
- **Outputs / side effects:** GREEN `Triggered job: <name> (<job_id>)`, then one of: `  Next run: <iso>`; `  Running in background (delegation <id>).`; `  Running in background.`; `  Ran now: succeeded.` / `  Ran now: failed.`; `  <execution_skipped message>`; `  It will run on the next scheduler tick.` Failure: RED `Failed to run job: <error>`, exit 1. Writes an execution row to `cron/executions.db` and an output file under `cron/output/`.
- **Config / env:** `HERMES_ACCEPT_HOOKS=1` / `hooks_auto_accept: true` equivalently to `--accept-hooks`; `HERMES_SESSION_KEY` inherited from a gateway/desktop session is what would otherwise trigger the background path.
- **Edge cases / guards:** Never claims a terminal verdict for a background dispatch; a run already claimed by a live owner is skipped rather than double-fired.
- **Rebuild notes:** Force-fire = claim an execution row, run, record terminal state. Better: `--wait`/`--detach` to make the sync/async choice explicit instead of env-inferred.

### `hermes cron remove` (aliases `rm`, `delete`) — delete a job  `id: cli-c.cron-remove`
- **Surface:** CLI
- **Where:** `hermes cron remove <job_id>`, `hermes cron rm <job_id>`, `hermes cron delete <job_id>`. Help: `Remove a scheduled job`.
- **What it does:** Permanently deletes a scheduled job from the store.
- **How it works:** `_job_action("remove", args.job_id, "Removed")` (`hermes_cli/cron.py:997`) → `_cron_api(action="remove", …)` → `cron.jobs.remove_job`. The result carries `removed_job`, which `_job_action` falls back to when printing the name.
- **Inputs / options:** positional `job_id` — "Job ID to remove"; `-h/--help`. All three spellings are registered by one `add_parser("remove", aliases=["rm", "delete"], …)` at `hermes_cli/subcommands/cron.py:270`.
- **Outputs / side effects:** GREEN `Removed job: <name> (<job_id>)`; the record disappears from `jobs.json`. Failure: RED `Failed to remove job: <error>`, exit 1.
- **Config / env:** n/a
- **Edge cases / guards:** No confirmation prompt — deletion is immediate. Execution history in `executions.db` is *not* removed with the job.
- **Rebuild notes:** Delete by id; return the removed record so the CLI can name it. Better: `--purge` to also drop history/outputs, and a soft-delete/undo window.

### `hermes cron status` — is the scheduler running?  `id: cli-c.cron-status`
- **Surface:** CLI
- **Where:** `hermes cron status`. Help: `Check if cron scheduler is running`.
- **What it does:** Reports whether jobs will actually fire — distinguishing "gateway dead", "gateway alive but ticker never started", "ticker stalled", "ticker alive but every tick fails", and "healthy" — plus the active-job count and next run.
- **How it works:** `cron_status()` at `hermes_cli/cron.py:392`. If `_active_cron_provider_name()` (`hermes_cli/cron.py:52`, via `cron.scheduler_provider.resolve_cron_scheduler`) is not `builtin`, it short-circuits with the provider message and skips all ticker heuristics. Otherwise it looks for gateway PIDs (`hermes_cli.gateway.find_gateway_pids`) and, if none, falls back to `gateway.status.is_gateway_runtime_lock_active()` + `get_running_pid()` — only when both say dead is "not running" declared. Health then uses `cron.jobs.get_ticker_heartbeat_age()` (`cron/jobs.py:1522`), `get_ticker_success_age()` (`cron/jobs.py:1536`), `get_ticker_last_error()` (`cron/jobs.py:1613`) and the threshold `STALE_AFTER = TICKER_INTERVAL_SECONDS * 3 + 20` (= 200 s at the 60 s default, `cron/jobs.py:99`). Heartbeat file: `~/.hermes/cron/ticker_heartbeat` (`cron/jobs.py:91`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. Strings, verbatim: external provider → GREEN `✓ Cron provider: <name> — jobs fire via the managed scheduler, not the in-process ticker.` + DIM `  (No ticker heartbeat is expected for an external provider; due jobs are delivered by an authenticated webhook.)`. No heartbeat → YELLOW `⚠ Gateway is running but the cron ticker has not reported a heartbeat.`, `  PID: …`, `  Cron jobs will NOT fire until the ticker writes its first heartbeat.`, `  If the gateway just started, wait ~60s and re-run \`hermes cron status\`.`, `  If heartbeat never appears, restart: hermes gateway restart`. Stale heartbeat → YELLOW `⚠ Gateway is running but the cron ticker looks STALLED — no heartbeat for <n>s (expected every ~60s).` + `  Cron jobs may NOT be firing. Restart: hermes gateway restart`. Failing ticks → YELLOW `⚠ Gateway and cron ticker are running, but no tick has succeeded in <n>s — ticks may be failing.` + RED `  Last tick error: <err>` + hints: `  Hint: jobs.json may be owned by another user (e.g. rewritten by a root \`docker exec hermes hermes cron ...\`). Fix ownership to match the gateway user, and prefer \`docker exec -u <uid>:<gid>\`.` (on `Permission denied`) or `  Hint: the ticker hit file-descriptor exhaustion (EMFILE). The scheduler now retries with backoff and attempts fd reclamation, but if the leak persists, restart the gateway to recover scheduling.` + `  Check the gateway log for 'Cron tick error'.`. Healthy → GREEN `✓ Gateway is running — cron jobs will fire automatically` + `  PID: …` + `  Ticker heartbeat: <n>s ago`. Dead → RED `✗ Gateway is not running — cron jobs will NOT fire` + `  To enable automatic execution:` + `    hermes gateway install    # Install as a user service` + `    sudo hermes gateway install --system  # Linux servers: boot-time system service` + `    hermes gateway            # Or run in foreground`. Always ends with `_print_active_jobs_summary` (`hermes_cli/cron.py:543`): `  <N> active job(s)` + `  Next run: <min next_run_at>`, or `  No active jobs`.
- **Config / env:** cron provider selection (Chronos vs builtin) via `cron.chronos.*`; `HERMES_HOME`.
- **Edge cases / guards:** Deliberately never reports ticker staleness for an external provider (would be a permanent false alarm on a healthy Chronos install). PID-scan misses right after a restart are covered by the runtime-lock probe.
- **Rebuild notes:** Three signals — process alive, heartbeat age, last-success age — with one shared interval constant. Better: expose the same tri-state over an API/JSON so dashboards don't re-implement it.

### `hermes cron runs` (alias `history`) — durable execution attempts  `id: cli-c.cron-runs`
- **Surface:** CLI
- **Where:** `hermes cron runs [--limit LIMIT] [job_id]`, alias `hermes cron history`. Help: `Show durable execution attempts`.
- **What it does:** Prints the audit ledger of cron execution attempts — one row per attempt with id, status, job, source and claim time.
- **How it works:** `cron_runs()` at `hermes_cli/cron.py:276` → `cron.executions.list_executions(job_id=…, limit=…)`. The ledger is SQLite at `~/.hermes/cron/executions.db` (`cron/executions.py:33`) with table `executions(id TEXT PRIMARY KEY, job_id, source, process_id, pid, process_started_at, status CHECK IN ('claimed','running','completed','failed','unknown'), claimed_at, started_at, finished_at, error)` and indexes `idx_executions_job_claimed`, `idx_executions_status_claimed` (`cron/executions.py:44-67`). PRAGMAs: `busy_timeout=5000`, WAL with fallback, `synchronous=FULL`.
- **Inputs / options:** optional positional `job_id` — "Optional job ID filter"; `--limit LIMIT` (int, **default 20**, help "Rows to show (1-500)"); `-h/--help`.
- **Outputs / side effects:** Read-only. Empty: `No cron execution attempts recorded.` Otherwise one line per record: `<id>  <status padded to 9>  job=<job_id>  source=<source>  <claimed_at>`, and when the row has an error a second indented line `    <error>`.
- **Config / env:** n/a (path derived from `HERMES_HOME`).
- **Edge cases / guards:** The ledger is an audit trail, **not** a retry queue. Interrupted attempts become `unknown` only after their exact owner process is proved gone (`_owner_is_live`, pid + process start time). Terminal states are immutable. Retention: `MAX_TERMINAL_EXECUTIONS = 1000` terminal rows (`cron/executions.py:25`). The advertised 1-500 limit range is documentation only — the CLI does not clamp it.
- **Rebuild notes:** One SQLite table + a claim/finish protocol keyed by `(pid, process_started_at)`. Better: actually enforce the documented 1-500 clamp and add `--status`/`--since` filters.

### `hermes cron incidents` — durable failure incidents  `id: cli-c.cron-incidents`
- **Surface:** CLI
- **Where:** `hermes cron incidents [--state {detected,alerted,closed}] [list|ack] [incident_id]`. Help: `List or acknowledge durable cron failure incidents`.
- **What it does:** Groups repeated cron failures into incidents keyed by (job, error signature) and lets you acknowledge one so its failure ping goes quiet until the error text changes.
- **How it works:** `cron_incidents(args)` at `hermes_cli/cron.py:301` → `cron.incidents.list_incidents(state=…)` / `ack_incident(id)`. Incidents live in the **same** `cron/executions.db` (`cron/incidents.py` module docstring). Lifecycle `detected` → `alerted` → `closed` (`INCIDENT_STATES`, `cron/incidents.py:41`); state validity is Python-side, not a SQLite CHECK, so new states need no table rebuild. Failure classification is an ordered keyword table `_FAILURE_TYPE_ORDER` (`cron/incidents.py:42`): `rate_limit` (`\b429\b`, "rate limit", "usage limit", "quota"), `timeout` ("timeout", "timed out"), `auth` (`\b401\b`, "unauthorized", "authentication", "auth"), `delivery` ("delivery", "deliver", "delivering"), `config` ("config", "configuration", "validation"), `script` ("script", "no_agent"), `agent` ("agent", "model", "provider", "inference"). Signature = hash of the normalised error, truncated at `_MAX_SIGNATURE_ERROR_CHARS = 200`; stored error capped at `MAX_ERROR_CHARS = 500`.
- **Inputs / options:** optional positional `incident_action` with `choices=["list","ack"]`, default `list`; optional positional `incident_id` — "Incident ID to acknowledge (ack)"; `--state {detected,alerted,closed}` — "Filter incidents by lifecycle state"; `-h/--help`.
- **Outputs / side effects:** `ack` without an id: RED `✗ Incident ID required: hermes cron incidents ack <incident_id>`, exit 1. Successful ack: GREEN `✓ Incident <id> acknowledged (closed).` Unknown/already closed: YELLOW `Incident <id> not found or already closed.` (still exit 0). Empty list: DIM `No cron failure incidents recorded.` plus DIM `  (filtered by state '<s>')` when a filter was given. Otherwise a CYAN box `│                         Cron Failure Incidents                          │` then per incident `  <id>  <state>` (state coloured RED/YELLOW/GREEN via `_INCIDENT_STATE_COLORS`, `hermes_cli/cron.py:294`), `    Job:        <job_id>`, `    Type:       <failure_type|unknown>`, `    First seen: <ts>`, `    Last seen:  <ts>`, `    Error:      <whitespace-collapsed, truncated at 160 chars with "...">`, `    Output:     <output_file>` (if any); footer DIM `  <n> incident(s)  |  ack one with: hermes cron incidents ack <id>`.
- **Config / env:** n/a
- **Edge cases / guards:** Acking is per-signature — the same job failing with the same normalised error resolves to the same incident id, so a closed incident stays closed until the error text changes (which mints a new incident). The stored error is redacted and truncated at write time, so it is safe for terminal display.
- **Rebuild notes:** `sha(job_id + normalized_error[:200])` as the incident key + a 3-state lifecycle. Better: auto-close incidents after N consecutive successes.

### `hermes cron notepad` — per-job durable KV scratchpad  `id: cli-c.cron-notepad`
- **Surface:** CLI
- **Where:** `hermes cron notepad <job_id> [get|set|delete|list] [key] [value]`. Help: `Read/write a job's durable notepad (persistent KV across runs)`.
- **What it does:** A tiny key/value store attached to one cron job, carried across scheduled wake-ups (cursors, watermarks, watchlists). Non-empty notepads are injected into the job's prompt on every run.
- **How it works:** `cron_notepad(args)` at `hermes_cli/cron.py:891` → `cron/notepad.py` (`set_note`, `get_note`, `delete_note`, `list_notes`). Storage: SQLite `~/.hermes/cron/notepad.db` (`cron/notepad.py:36` `NOTEPAD_FILE`), table `cron_notepad(job_id TEXT, key TEXT, value TEXT, updated_at TEXT, PRIMARY KEY (job_id, key))` (`cron/notepad.py:53-60`), `PRAGMA busy_timeout=5000` + WAL-with-fallback. This CLI is the **write path** — a running cron agent updates its own notepad by shelling out to these commands through its terminal tool; no model tool is exposed. Module docstring credits "Amp (Sourcegraph) cron notepad (idea-level, proprietary — zero code)".
- **Inputs / options:** positional `job_id` (required); positional `notepad_action` with `choices=["get","set","delete","list"]`, default `list`; positional `key` (get/set/delete); positional `value` (set); `-h/--help`.
- **Outputs / side effects:** `set` → GREEN `Set notepad key '<key>' for job <job_id>.` (exit 0); missing key/value → RED `Usage: hermes cron notepad <job_id> set <key> <value>`, exit 1. `get` → prints the raw stored value (exit 0); missing key → RED `Usage: hermes cron notepad <job_id> get <key>` exit 1; absent key → YELLOW `No notepad key '<key>' for job <job_id>.` exit **1**. `delete` → GREEN `Deleted notepad key '<key>' for job <job_id>.` exit 0, or YELLOW `No notepad key '<key>' for job <job_id>.` exit 1; missing key → RED `Usage: hermes cron notepad <job_id> delete <key>` exit 1. `list` (default) → DIM `Notepad for job <job_id> is empty.` or, per note, `  <key> = <value>` and DIM `    updated: <updated_at>`. Empty job id → RED `A job ID is required.` exit 1. A `ValueError` from the cap checks prints RED `Notepad error: <exc>` exit 1.
- **Config / env:** n/a
- **Edge cases / guards:** Documented caps — `MAX_VALUE_BYTES = 16 * 1024` (16 KB per value, UTF-8 bytes), `MAX_KEY_CHARS = 128`, `MAX_JOB_TOTAL_BYTES = 64 * 1024` (64 KB per job over the sum of key+value bytes). Oversized writes raise `ValueError` and leave the store untouched, because the notepad is prompt-injected on every run and unbounded growth would bloat every wake-up.
- **Rebuild notes:** `(job_id, key) → value` SQLite table with byte caps + prompt injection. Better: TTL per key and a `--json` list output.

### `hermes cron doctor` — job health check  `id: cli-c.cron-doctor`
- **Surface:** CLI
- **Where:** `hermes cron doctor`. Help: `Check scheduled jobs for common health issues`.
- **What it does:** Read-only sweep over active jobs that reports failing last runs, failed deliveries, overdue `next_run_at`, missing/mis-located scripts, no-agent jobs without a script, and missing workdirs; exits non-zero when anything is found.
- **How it works:** `cron_doctor()` at `hermes_cli/cron.py:647`, per-job checks in `_cron_doctor_issues_for_job` (`hermes_cli/cron.py:611`). Checks, in order: (1) `last_status` present and != `ok` → `last run failed: <last_error|unknown error>`; (2) `last_delivery_error` → `last delivery failed: <err>`; (3) job enabled and state not in {paused, completed}: no `next_run_at` → `active job has no next_run_at`, else `_next_run_overdue_issue` (`hermes_cli/cron.py:592`) with `_OVERDUE_GRACE_SECONDS = 15 * 60` (`hermes_cli/cron.py:589`) → `next_run_at is <h>h overdue — job is not firing (is the scheduler running?)` / `… <m>m overdue …` / `next_run_at is not a valid timestamp: '<x>'`; (4) `no_agent` without script → `no-agent job has no script`; (5) script health via `_script_health_issue` → `script resolves outside HERMES_HOME/scripts: '<x>'`, `script not found: <path>`, `script path is not a file: <path>`; (6) `workdir` that doesn't exist → `workdir not found: <path>`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Clean: GREEN `✓ Cron doctor found no issues` + DIM `  Checked <n> active job(s).` or DIM `  No active jobs configured.`; **exit 0**. Problems: YELLOW `Cron doctor found <k> issue(s) across <j> job(s):`, then per job `  <job_id> <name>` and `    - <issue>` lines, then DIM `Next: fix the listed job config, then run \`hermes cron doctor\` again.`; **exit 1**.
- **Config / env:** Script containment root is `cron.jobs.CRON_DIR.parent / "scripts"` (`_scripts_dir_for_cron`, `hermes_cli/cron.py:555`) — deliberately derived from the loaded cron store, not a fresh `get_hermes_home()`, so profile-aware callers and tests agree.
- **Edge cases / guards:** Only **active** (non-disabled) jobs are checked. The 15-minute grace period avoids flagging a busy tick that dispatched a few minutes late.
- **Rebuild notes:** Six pure predicates over the job record + a non-zero exit. Better: add `--fix` for the mechanical cases (recompute `next_run_at`, disable a job whose script vanished).

### `hermes cron tick` — run due jobs once and exit  `id: cli-c.cron-tick`
- **Surface:** CLI
- **Where:** `hermes cron tick [--accept-hooks]`. Help: `Run due jobs once and exit` (described in the source as "mostly for debugging").
- **What it does:** Performs a single scheduler pass in the foreground: claims every due job, runs it, delivers output, and exits.
- **How it works:** `cron_tick()` at `hermes_cli/cron.py:250` → `cron.scheduler.tick(verbose=True)`. A file lock prevents duplicate execution when several processes overlap (module docstring, `cron/__init__.py:14`).
- **Inputs / options:** `--accept-hooks`; `-h/--help`.
- **Outputs / side effects:** Verbose scheduler output; jobs actually run and deliver. Returns 0 normally. On `CronTickYielded`: YELLOW `✗ <exc>` + `  A fresher gateway process owns the runtime lock and will fire due jobs; this stale process yielded its tick.`, return 1. On `OSError` (EMFILE, EACCES on open, …): RED `✗ Cron tick failed: <exc>` + `  Check \`hermes cron status\` and the gateway log for details.`, return 1.
- **Config / env:** `cron.max_parallel_jobs`, `cron.script_timeout_seconds`, `cron.media_send_timeout_seconds`, `cron.session_db_timeout_seconds`, `cron.wrap_response`, `cron.mirror_delivery`, `cron.output_retention`; `HERMES_ACCEPT_HOOKS`.
- **Edge cases / guards:** The yield gate is inert on this surface (a one-shot CLI process has no boot fingerprint) but is handled cleanly anyway. Real lock-acquisition failures propagate rather than being swallowed as contention.
- **Rebuild notes:** `tick()` = scan due → claim → execute → record; guard with a file lock. Better: `--dry-run` listing what *would* fire.

## 2. `hermes sync` — Skill Sync (personal + organisation)

### Sync command group  `id: cli-c.sync-group`
- **Surface:** CLI
- **Where:** `hermes sync {status,pull,push,now,enable,disable,device,propose}`. Root help: `Skill Sync — sync your skills across devices and with your team`. Description: "Skill Sync keeps your skills with you. Personal sync moves your own skills between your devices; if you belong to an organisation, you also get its shared skills and can propose your own back to the team." Epilog (RawDescriptionHelpFormatter): `Examples:` / `  hermes sync status            what is synced, and from where` / `  hermes sync enable my-skill   include a skill in your sync` / `  hermes sync now               pull, then push` / `  hermes sync propose my-skill  share a skill with your team`.
- **What it does:** Moves the user's own skills between their devices via a content-addressed sync plane, and (for org members) mirrors the organisation's shared skills and submits local ones back.
- **How it works:** Parser: `hermes_cli/subcommands/sync.py:31` (`build_sync_parser`), `set_defaults(func=cmd_sync)` at line 99. Handler `cmd_sync` at `hermes_cli/main.py:5633`. Everything below the CLI is `tools/skills_sync_client.py` — a Git-like object model (`KIND_BLOB`/`KIND_TREE`/`KIND_COMMIT` at lines 79-81; modes `file`/`exec`/`dir` at 84-86; `WIRE_VERSION = "1"` at line 75) pushed to `/v1/sync/` on the sync plane, with CAS on `refs/user/<owner>/HEAD` and a three-way merge on HTTP 409.
- **Inputs / options:** `-h/--help`; one of the 8 sub-command tokens.
- **Outputs / side effects:** With **no** sub-command it prints a hand-written usage block to **stderr** and returns 1 (`hermes_cli/main.py:5641-5658`): `usage: hermes sync <status|pull|push|now|enable|disable|device|propose>` / blank / `Your skills, across your devices:` / `  status            Show what is synced, and from where` / `  pull              Pull your synced skills` / `  push              Push your opted-in skills` / `  now               Reconcile now: pull then push` / `  enable <skill>    Include a skill in your sync` / `  disable <skill>   Exclude a skill from your sync` / `  device [--name N] Show or set this device's label` / blank / `Shared with your team:` / `  propose <skill>   Share a skill with your organisation`.
- **Config / env:** `sync.base_url` ← `HERMES_SYNC_BASE_URL` (default `https://gateway-gateway.nousresearch.com`, `tools/skills_sync_client.py:305`); `sync.enabled` ← `HERMES_SYNC_ENABLED` (default **false**); `sync.default_opt_in` ← `HERMES_SYNC_DEFAULT_OPT_IN` (default false = opt-in); `sync.org_auto_propose` ← `HERMES_SYNC_ORG_AUTO_PROPOSE` (default false); `HERMES_SYNC_DEVICE_NAME` (first-use device label seed). Booleans accept `1/true/yes/on` and `0/false/no/off/""` (`_TRUE`/`_FALSE`, lines 354-355).
- **Edge cases / guards:** Sync is **INERT** unless three things hold: the resolved Nous token carries the access-gate claim `tool_gateway_admin` (`NOUS_ADMIN_CLAIM`, line 216 — populated by NAS from `Permissions.ADMIN_ACCESS`), `sync.enabled`/`HERMES_SYNC_ENABLED` is on, and a base URL is configured. The commands report that state rather than failing opaquely.
- **Rebuild notes:** Content-addressed blob/tree/commit objects + a CAS'd per-user ref + a local `.sync_state` head record. Better: replace the admin-claim gate with a real `sync:*` entitlement (the source itself flags this as pre-launch containment).

### `hermes sync status` — what is synced, and from where  `id: cli-c.sync-status`
- **Surface:** CLI
- **Where:** `hermes sync status`. Help: `Show what is synced, and from where`.
- **What it does:** Prints a JSON snapshot of the sync gate, opt-in list, local head and org membership, followed by human-readable advice on stderr explaining exactly why sync is or isn't active.
- **How it works:** `hermes_cli/main.py:5720` → `tools.skills_sync_client.sync_status()` (`tools/skills_sync_client.py:1650`, "never raises"). The snapshot keys are: `nous_admin`, `logged_in`, `feature_enabled`, `default_opt_in`, `base_url`, `opted_in_skills`, `local_head`, `owner`, `org_available`, `org_id`, `org_role`, `org_skills`, `org_skills_modified`. `local_head` comes from `~/.hermes/skills/.sync_state` (`{"head": "sha256:…|null", "skills": {name: {tree, commit}}}`, `tools/skills_sync_client.py:946,955`; a legacy `.sync_manifest` file is migrated transparently). `org_skills` is the list of `SKILL.md` directories under the org mirror `_org/<org_id>/`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout: `json.dumps(status, indent=2, ensure_ascii=False)`. stderr, conditionally: when `org_available` — `\nOrg skills: <n> shared skill(s) from your organisation (your role: <org_role>). They load alongside your own, labeled by origin, and you can edit them.` and, when some are locally modified, `  <k> with local edits not yet shared: <names>` + `  Share them back with \`hermes sync propose <skill>\`. Org updates will not overwrite them.`; when logged in but not in an org — `\nOrg skills: not applicable — this account isn't a member of a shared organisation.`. Then exactly one gate message: `\nNot logged into Nous Portal — sync is inert.` / `\nSync is not enabled for your account yet.` / `\nSync feature is off for this instance (set HERMES_SYNC_ENABLED=1 or config.yaml sync.enabled: true). Sync is inert.` / `\nNo sync base URL configured (config.yaml sync.base_url or HERMES_SYNC_BASE_URL). Sync is inert.` Always returns 0.
- **Config / env:** all `sync.*` keys above.
- **Edge cases / guards:** Never raises; a failing identity/org lookup silently leaves the corresponding fields at their defaults. `org_available: false` means "not in a shared org", which is deliberately distinct from "broken/misconfigured".
- **Rebuild notes:** One pure snapshot function + a fixed ladder of gate explanations. Better: make it exit non-zero when inert so scripts can branch.

### `hermes sync pull` — pull your synced skills  `id: cli-c.sync-pull`
- **Surface:** CLI
- **Where:** `hermes sync pull`. Help: `Pull your synced skills (and your organisation's)`.
- **What it does:** Fetches the owner's HEAD from the sync plane, materialises opted-in skills locally, reconciles the local opt-in flags from the plane manifest, and additionally refreshes the org mirror when the account belongs to an organisation.
- **How it works:** `hermes_cli/main.py:5789` → `ssc.pull_skills(identity=identity)` then `ssc.maybe_pull_org_skills()`. The durable, cross-device opt-in state is a committed `sync-manifest` object (`SYNC_MANIFEST_ENTRY_NAME = "sync-manifest"`, `SYNC_MANIFEST_TYPE`, `SYNC_MANIFEST_VERSION = 1`, lines 113-115) — a root-level blob in the tree at `refs/user/<owner>/HEAD` recording per-skill `{name, enabled}`. The plane manifest is authoritative; the local `.usage.json` `sync` flag is just editable intent.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Writes skill directories under `~/.hermes/skills/` and the org mirror under `~/.hermes/skills/_org/<org_id>/`; updates `.sync_state`. Prints the result dict as indented JSON. stderr extras: `org: refreshed <n> shared skill(s) from your organisation.`; on conflicts `org: <k> skill(s) have BOTH local edits and org updates, so they were left as-is: <names>` + `     Your local version is intact. Review it, then either propose it or delete the local copy and pull again to take the org version.`
- **Config / env:** `sync.base_url`, `sync.enabled`, Nous credentials.
- **Edge cases / guards:** Three gate checks run **before** any work (shared with push/now): `SyncInertError` → stderr `sync inert: <e>` exit 1; missing admin claim → `sync unavailable: not enabled for your account yet.` exit 1; no base URL → `sync inert: no sync base URL configured (config.yaml sync.base_url or HERMES_SYNC_BASE_URL).` exit 1. Any `SyncError` during the operation → `sync failed: <e>` exit 1. Org skills with simultaneous local edits and remote updates are never overwritten.
- **Rebuild notes:** GET the ref → walk the commit's tree → materialise → reconcile manifest. Better: a `--dry-run` diff of what pull would change.

### `hermes sync push` — push your opted-in skills  `id: cli-c.sync-push`
- **Surface:** CLI
- **Where:** `hermes sync push`. Help: `Push your opted-in skills`.
- **What it does:** Uploads every opted-in skill as content-addressed objects and compare-and-swaps the owner's HEAD ref, merging automatically if another device moved it first.
- **How it works:** `hermes_cli/main.py:5812` → `ssc.push_skills(identity=identity, message="hermes sync push")` (`tools/skills_sync_client.py:1258`). Sequence: `client.capabilities()` → `_check_version(caps)` → `max_object_bytes` (default `DEFAULT_MAX_OBJECT_BYTES = 26214400`, 25 MiB) → `snapshot_profile(skill_names, …)` → idempotency check (if the profile-root tree hash equals the last pushed `root`, return `{"ok": True, "head": …, "reason": "unchanged", "noop": True}`) → upload new objects in batch → CAS `refs/user/<owner>/HEAD`. HTTP 409 returns the actual head, triggering a three-way merge and one retry.
- **Inputs / options:** `-h/--help` only. (The commit message is fixed to `hermes sync push`.)
- **Outputs / side effects:** Network upload; `.sync_state` head/root updated. Prints the result dict as indented JSON. Known no-op shapes: `{"ok": False, "reason": "no sync base url configured", "noop": True}`, `{"ok": True, "reason": "no skills opted into sync", "noop": True}`, `{"ok": True, "head": …, "reason": "unchanged", "noop": True}`.
- **Config / env:** as pull; commit `author.device` is the device label.
- **Edge cases / guards:** Same three pre-gates as pull. Objects larger than the server-advertised `max_object_bytes` are rejected. Only agent-created / user-authored skills under `~/.hermes/skills/` are eligible — bundled (`.bundled_manifest`), hub-installed, external-dir and org-mirror (`_org/`) skills are excluded (`is_sync_eligible`, line 452).
- **Rebuild notes:** Snapshot → hash → upload-missing → CAS-with-retry. Better: expose the commit message as a flag and support partial pushes (`--skill`).

### `hermes sync now` — reconcile (pull then push)  `id: cli-c.sync-now`
- **Surface:** CLI
- **Where:** `hermes sync now`. Help: `Reconcile now: pull then push`.
- **What it does:** Runs a pull immediately followed by a push, in one command.
- **How it works:** `hermes_cli/main.py:5814-5816`: `pull_res = ssc.pull_skills(identity=identity)`; `push_res = ssc.push_skills(identity=identity, message="hermes sync now")`; `result = {"pull": pull_res, "push": push_res}`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Both effects above; prints `{"pull": …, "push": …}` as indented JSON. Note: unlike a bare `pull`, `now` does **not** call `maybe_pull_org_skills()` — the org refresh is only wired into the `pull` branch.
- **Config / env:** as pull/push.
- **Edge cases / guards:** Same three pre-gates; a `SyncError` in either half aborts with `sync failed: <e>` exit 1.
- **Rebuild notes:** Trivial composition. Better: make `now` cover the org refresh too (current asymmetry looks like an oversight).

### `hermes sync enable` — opt a skill into sync  `id: cli-c.sync-enable`
- **Surface:** CLI
- **Where:** `hermes sync enable <skill>`. Help: `Include a skill in your sync`.
- **What it does:** Marks one local skill as syncable so subsequent pushes include it and other devices receive it.
- **How it works:** `hermes_cli/main.py:5702-5717` → `tools.skill_usage.is_curation_eligible(skill)` then `set_sync(skill, True)`. The flag is a `sync` boolean on the skill's `.usage.json` sidecar (alongside `pinned` / `created_by`); the durable cross-device truth is the plane's `sync-manifest`, which push writes from this flag and pull reconciles back into it.
- **Inputs / options:** positional `skill` — "Skill name (frontmatter name / directory name)"; `-h/--help`.
- **Outputs / side effects:** stdout `sync enabled for '<skill>'.` and exit 0.
- **Config / env:** `sync.default_opt_in` / `HERMES_SYNC_DEFAULT_OPT_IN` — when true, every eligible skill counts as opted in without this command.
- **Edge cases / guards:** Ineligible skills print to **stderr** `'<skill>' is not sync-eligible (bundled, hub-installed, external, or not found). Only agent-created / user-authored skills under ~/.hermes/skills/ can sync.` and exit 1. Unlike pull/push this path does **not** require the admin gate — the flag can be set while sync is inert.
- **Rebuild notes:** One boolean in a per-skill sidecar + an eligibility predicate. Better: `hermes sync enable --all` and tab-completion over eligible names.

### `hermes sync disable` — opt a skill out of sync  `id: cli-c.sync-disable`
- **Surface:** CLI
- **Where:** `hermes sync disable <skill>`. Help: `Exclude a skill from your sync`.
- **What it does:** Clears the sync flag on one skill so it stops being pushed.
- **How it works:** Identical code path to `enable` with `set_sync(skill, False)` (`sub == "enable"` is the boolean, `hermes_cli/main.py:5716`).
- **Inputs / options:** positional `skill` — "Skill name (frontmatter name / directory name)"; `-h/--help`.
- **Outputs / side effects:** stdout `sync disabled for '<skill>'.`, exit 0.
- **Config / env:** as enable.
- **Edge cases / guards:** Same eligibility check and stderr message as `enable`. Disabling does not delete already-pushed content from the plane.
- **Rebuild notes:** As enable. Better: state whether the remote copy is retained or tombstoned.

### `hermes sync device` — show or set this device's label  `id: cli-c.sync-device`
- **Surface:** CLI
- **Where:** `hermes sync device [--name DEVICE_NAME]`. Help: `Show or set this device's label (shown in the sync console)`.
- **What it does:** Prints or sets the human-friendly label attached to this machine's sync commits.
- **How it works:** `hermes_cli/main.py:5659-5679`. Without `--name`: prints `ssc.stable_device_id()` (`tools/skills_sync_client.py:675`), which reads `~/.hermes/skills/.sync_device_id`, or seeds it from `HERMES_SYNC_DEVICE_NAME`, else from `_default_device_label()` (`line 656`) = short hostname (domain dropped, non-alphanumeric stripped except `-`/`_`) + `-` + 6 hex chars, e.g. `bens-macbook-a1b2c3`; a bare uuid4 hex if the hostname is unusable. With `--name`: `ssc.set_device_name(name)` writes the trimmed string to the same file.
- **Inputs / options:** `--name DEVICE_NAME` (dest `device_name`, default None) — "Set a human-friendly label for this device (e.g. \"Ben's Laptop\"). Omit to print the current label."; `-h/--help`.
- **Outputs / side effects:** Read: the label on stdout, exit 0. Write: stdout `device label set to '<stored>'.` plus stderr `New commits from this device will use this label; existing commits keep their previous one.`, exit 0. Creates/overwrites `~/.hermes/skills/.sync_device_id`.
- **Config / env:** `HERMES_SYNC_DEVICE_NAME` seeds the first-use value only; an existing file always wins.
- **Edge cases / guards:** An empty/whitespace name raises `ValueError("device name must be a non-empty string")`, printed as stderr `error: <e>` with exit 1. The label is advisory metadata (`author.device`), never an auth input, so any non-empty string is accepted.
- **Rebuild notes:** One file, one default generator, one setter. Better: also record OS/hostname so the console can disambiguate re-labelled devices.

### `hermes sync propose` — share a skill with your organisation  `id: cli-c.sync-propose`
- **Surface:** CLI
- **Where:** `hermes sync propose <name> [-m MESSAGE | --message MESSAGE]`. Help: `Share a skill with your organisation`. Description: "Submit one of your skills to your organisation's shared set. If you are an admin it is added directly; otherwise it becomes a proposal for an admin to review. Accounts that aren't part of a shared organisation don't have this workflow."
- **What it does:** Uploads a local skill's current content as an org-scoped commit layered on the org HEAD; admins merge it directly, members create a proposal for review.
- **How it works:** `hermes_cli/main.py:5680-5700` → `ssc.propose_skill(name, message=args.message)` (`tools/skills_sync_client.py:2015`). Locates the skill in the **personal** namespace (never `_org/`), requires `SKILL.md`, builds the skill subtree, splices it into the current org HEAD tree, uploads objects with `?scope=org`, then CAS-es the org HEAD. ADMIN/OWNER token → server merges → `{ok, merged: True}`; MEMBER token → server returns 202 → `{ok, proposal_pending: True, proposal_id, ref}`, never presented as live.
- **Inputs / options:** positional `name` — "Skill name to share"; `-m MESSAGE` / `--message MESSAGE` (default None) — "Optional message describing the change"; `-h/--help`.
- **Outputs / side effects:** Pending: `Shared '<name>' with your organisation — an admin needs to approve it (proposal #<proposal_id>). It is not live for the team until then.` Merged: `Added '<name>' to your organisation's shared skills.` Both exit 0.
- **Config / env:** `sync.org_auto_propose` / `HERMES_SYNC_ORG_AUTO_PROPOSE` — when true, every local edit to an org skill is proposed automatically without running this command.
- **Edge cases / guards:** `SyncInertError` → stderr `cannot share this skill: <e>` exit 1 (raised for "no sync base URL configured", for a server whose `capabilities().features` lacks `"org"` → `this server does not support org-shared skills`, and for a non-org account). `SyncError` → stderr `could not share '<name>': <e>` exit 1 (raised for `skill '<n>' not found under the skills dir` and `skill '<n>' has no SKILL.md`).
- **Rebuild notes:** Splice one subtree into the org root tree, upload with an org scope, CAS the org ref; let the server decide merge-vs-proposal from the token role. Better: show a diff of what will be proposed before uploading.

## 3. `hermes webhook` — dynamic webhook subscriptions

### Webhook command group  `id: cli-c.webhook-group`
- **Surface:** CLI
- **Where:** `hermes webhook {subscribe,add,list,ls,remove,rm,test}`. Root help: `Manage dynamic webhook subscriptions`; description: `Create, list, and remove webhook subscriptions for event-driven agent activation`.
- **What it does:** Creates and manages named HTTP routes (`/webhooks/<name>`) that wake the agent (or deliver a message directly) when an external service POSTs to them.
- **How it works:** Parser at `hermes_cli/subcommands/webhook.py:12` (`build_webhook_parser`), `set_defaults(func=cmd_webhook)` at line 80. Handler `cmd_webhook` (`hermes_cli/main.py:5828`) → `hermes_cli/webhook.py:webhook_command` (line 140). Subscriptions persist to `~/.hermes/webhook_subscriptions.json` (`_SUBSCRIPTIONS_FILENAME`, `hermes_cli/webhook.py:27`) and are **hot-reloaded by the webhook adapter without a gateway restart** (module docstring line 9-10).
- **Inputs / options:** `-h/--help`; one of the sub-command tokens.
- **Outputs / side effects:** With no sub-command: `Usage: hermes webhook {subscribe|list|remove|test}` + `Run 'hermes webhook --help' for details.` and returns.
- **Config / env:** `platforms.webhook.enabled`, `platforms.webhook.extra.host`, `platforms.webhook.extra.port` (default `8644`), `platforms.webhook.extra.secret`; env bridges `WEBHOOK_ENABLED`, `WEBHOOK_PORT`, `WEBHOOK_SECRET`.
- **Edge cases / guards:** Every sub-command except the bare form is gated by `_require_webhook_enabled()` (`hermes_cli/webhook.py:132`); see `cli-c.webhook-enable-gate`. The store is written with mode `0o600` (`_SUBSCRIPTIONS_FILE_MODE`) via mkstemp → fsync → chmod → `atomic_replace` → chmod again, because it contains per-route HMAC secrets and a permissive umask must not leak them.
- **Rebuild notes:** JSON dict keyed by route name, hot-reloaded by the HTTP adapter. Better: keep secrets in a separate keyring-backed store so the route file can be world-readable config.

### Webhook enablement gate + setup hint  `id: cli-c.webhook-enable-gate`
- **Surface:** CLI / Config
- **Where:** Printed by any `hermes webhook <sub>` when the webhook platform is off.
- **What it does:** Refuses to operate and prints a three-option setup guide instead of a bare error.
- **How it works:** `_is_webhook_enabled()` reads `platforms.webhook.enabled` via `cfg_get(cfg, "platforms", "webhook", default={})` (`hermes_cli/webhook.py:83-95`); `_setup_hint()` (line 107) builds the message with `display_hermes_home()`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Verbatim text: blank line, then `  Webhook platform is not enabled. To set it up:`, `  1. Run the gateway setup wizard:`, `     hermes gateway setup`, `  2. Or manually add to <HERMES_HOME>/config.yaml:`, `     platforms:`, `       webhook:`, `         enabled: true`, `         extra:`, `           port: 8644`, `           secret: "your-global-hmac-secret"`, `  3. Or set environment variables in <HERMES_HOME>/.env:`, `     WEBHOOK_ENABLED=true`, `     WEBHOOK_PORT=8644`, `     WEBHOOK_SECRET=your-global-secret`, `  Then start the gateway: hermes gateway run`. Returns without doing anything.
- **Config / env:** as above.
- **Edge cases / guards:** The gate returns `None` (not a non-zero exit), so scripts cannot detect it from the exit code.
- **Rebuild notes:** A single boolean check plus a static how-to. Better: exit 2 so automation can branch, and offer `--enable` to flip the key in place.

### Webhook base-URL display  `id: cli-c.webhook-base-url`
- **Surface:** CLI
- **Where:** The `URL:` line printed by `subscribe`, `list` and `test`.
- **What it does:** Renders the externally-usable route URL for a subscription.
- **How it works:** `_get_webhook_base_url()` (`hermes_cli/webhook.py:97`): reads `platforms.webhook.extra.host` and `.port` (default `8644`); a missing host or `0.0.0.0` / `::` is displayed as `localhost`; a raw IPv6 literal is bracketed (`[::1]`); result is `http://<display_host>:<port>` and routes are `<base>/webhooks/<name>`.
- **Inputs / options:** n/a
- **Outputs / side effects:** String only.
- **Config / env:** `platforms.webhook.extra.host`, `platforms.webhook.extra.port`.
- **Edge cases / guards:** Always `http://` — the helper never emits `https://` even behind a TLS terminator, so the printed URL can be wrong for a reverse-proxied deployment.
- **Rebuild notes:** Trivial formatter. Better: a `platforms.webhook.extra.public_url` override for proxied installs.

### `hermes webhook subscribe` (alias `add`) — create a subscription  `id: cli-c.webhook-subscribe`
- **Surface:** CLI
- **Where:** `hermes webhook subscribe <name> [options]`, alias `hermes webhook add`. Help: `Create a webhook subscription`.
- **What it does:** Registers (or updates) a named webhook route with an HMAC secret, an optional event filter, a prompt template, skills, a delivery target, and optional filter script / direct-delivery mode.
- **How it works:** `_cmd_subscribe(args)` (`hermes_cli/webhook.py:162`). The name is normalised `strip().lower().replace(" ", "-")` and must match `^[a-z0-9][a-z0-9_-]*$`. Secret defaults to `secrets.token_urlsafe(32)`. Events and skills are comma-split and stripped. The persisted route dict is `{description, events, secret, prompt, skills, deliver, created_at}` with optional `deliver_only: true`, `script`, and `deliver_extra: {"chat_id": …}`. `created_at` is `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`.
- **Inputs / options:** positional `name` — "Route name (used in URL: /webhooks/<name>)"; `--prompt PROMPT` (default `""`) — "Prompt template with {dot.notation} payload refs"; `--events EVENTS` (default `""`) — "Comma-separated event types to accept"; `--description DESCRIPTION` (default `""`); `--skills SKILLS` (default `""`) — "Comma-separated skill names to load"; `--deliver DELIVER` (**default `log`**) — "Delivery target: log, telegram, discord, slack, etc."; `--deliver-chat-id DELIVER_CHAT_ID` (default `""`) — "Target chat ID for cross-platform delivery"; `--secret SECRET` (default `""`, auto-generated when empty); `--deliver-only` (store_true); `--script SCRIPT` (default `""`); `-h/--help`.
- **Outputs / side effects:** Writes `~/.hermes/webhook_subscriptions.json` (0600). Prints blank line then `  Created webhook subscription: <name>` (or `  Updated webhook subscription: <name>` when the name already existed), `  URL:    <base>/webhooks/<name>`, `  Secret: <secret>`, `  Events: a, b` or `  Events: (all)`, `  Deliver: <target>`, `  Mode: direct delivery (no agent, zero LLM cost)` (when `deliver_only`), `  Prompt: <first 80 chars…>` — labelled `  Message:` instead when `deliver_only` — , `  Script: <path>`, then blank line, `  Configure your service to POST to the URL above.`, `  Use the secret for HMAC-SHA256 signature validation.`, `  The gateway must be running to receive events (hermes gateway run).` and a blank line.
- **Config / env:** `platforms.webhook.*` as above; the default description is `Agent-created subscription: <name>`.
- **Edge cases / guards:** Invalid name → `Error: Invalid name '<name>'. Use lowercase alphanumeric with hyphens/underscores.` and return. `--deliver-only` with `--deliver log` → `Error: --deliver-only requires --deliver to be a real target (telegram, discord, slack, github_comment, etc.) — not 'log'.` and return. Re-subscribing the same name silently **overwrites** the whole route (including rotating the secret when `--secret` is omitted).
- **Rebuild notes:** Name-validate → build dict → merge into JSON → print URL+secret once. Better: never rotate an existing secret on update unless asked, and print the secret only on creation.

### Webhook direct-delivery mode (`--deliver-only`)  `id: cli-c.webhook-deliver-only`
- **Surface:** CLI
- **Where:** `hermes webhook subscribe <name> --deliver-only --deliver <target>`; shown afterwards as `  Mode: direct delivery (no agent, zero LLM cost)` and in `list` as `Deliver: <target> (direct — no agent)`.
- **What it does:** Skips the LLM entirely — the rendered prompt template *is* the message delivered to the target.
- **How it works:** Sets `route["deliver_only"] = True` (`hermes_cli/webhook.py:191`). The prompt template's `{dot.notation}` payload references are substituted and the result is sent verbatim; the `Prompt:` preview line is relabelled `Message:` accordingly (`hermes_cli/webhook.py:218`).
- **Inputs / options:** `--deliver-only` (store_true) — help: "Skip the agent — deliver the rendered prompt directly as the message. Zero LLM cost. Requires --deliver to be a real target (not 'log')."
- **Outputs / side effects:** Zero LLM tokens; a message on the chosen platform per accepted webhook.
- **Config / env:** requires a real `--deliver` target.
- **Edge cases / guards:** Hard-rejected with `--deliver log` (see above). Combined with `--script`, the script still runs first and can silence the event.
- **Rebuild notes:** A boolean that swaps "prompt the agent" for "format and send". Better: support a template language with conditionals so simple routing needs no LLM either.

### Webhook filter/transform script (`--script`)  `id: cli-c.webhook-script`
- **Surface:** CLI
- **Where:** `hermes webhook subscribe <name> --script <path>`; shown as `  Script: <path>` and in `list` as `Script:  <path>`.
- **What it does:** Runs a user script on each incoming payload before anything else; the script can rewrite the payload or silence the event entirely.
- **How it works:** Stored as `route["script"]` (`hermes_cli/webhook.py:194-195`, `.strip()`ed, empty means absent). Help text defines the contract: the script lives under `~/.hermes/scripts/`, the route payload is passed as **JSON on stdin**, and the webhook is ignored when the script produces empty stdout, outputs `[SILENT]`, or exits non-zero.
- **Inputs / options:** `--script SCRIPT` (default `""`).
- **Outputs / side effects:** Either a transformed payload flows on to the prompt/delivery step, or the event is dropped silently.
- **Config / env:** shares `~/.hermes/scripts/` with cron scripts.
- **Edge cases / guards:** Three distinct "ignore" signals (empty stdout, `[SILENT]`, non-zero exit) — a script that crashes is therefore indistinguishable from one that deliberately silenced the event.
- **Rebuild notes:** Popen the script, feed JSON on stdin, read stdout. Better: separate "error" from "silence" (e.g. exit 78 = silence) and log the distinction.

### `hermes webhook list` (alias `ls`) — list subscriptions  `id: cli-c.webhook-list`
- **Surface:** CLI
- **Where:** `hermes webhook list`, `hermes webhook ls`. Help: `List all dynamic subscriptions`.
- **What it does:** Shows every dynamic subscription with its URL, accepted events, delivery target and filter script.
- **How it works:** `_cmd_list(args)` (`hermes_cli/webhook.py:227`) reads `webhook_subscriptions.json` and iterates in insertion order.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. Empty: `  No dynamic webhook subscriptions.` + `  Create one with: hermes webhook subscribe <name>`. Otherwise blank line, `  <n> webhook subscription(s):`, blank line, then per route: `  ◆ <name>`, `    <description>` (only when set), `    URL:     <base>/webhooks/<name>`, `    Events:  a, b` or `(all)`, `    Deliver: <target>` (suffixed ` (direct — no agent)` when `deliver_only`), `    Script:  <path>` (when set), and a blank line.
- **Config / env:** `platforms.webhook.extra.*` for the URL.
- **Edge cases / guards:** Only **dynamic** routes are listed — static routes declared in `config.yaml` are invisible here (and, per `remove`, cannot be deleted here). Secrets are deliberately not printed.
- **Rebuild notes:** Iterate the JSON, format. Better: merge static+dynamic with an origin column so the operator sees the full route table.

### `hermes webhook remove` (alias `rm`) — delete a subscription  `id: cli-c.webhook-remove`
- **Surface:** CLI
- **Where:** `hermes webhook remove <name>`, `hermes webhook rm <name>`. Help: `Remove a subscription`.
- **What it does:** Deletes one dynamic subscription from the store.
- **How it works:** `_cmd_remove(args)` (`hermes_cli/webhook.py:253`): lowercases + strips the name, `del subs[name]`, re-saves atomically.
- **Inputs / options:** positional `name` — "Subscription name to remove"; `-h/--help`.
- **Outputs / side effects:** `  Removed webhook subscription: <name>`; the route stops accepting POSTs after the adapter hot-reloads.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown name: `  No subscription named '<name>'.` + `  Note: Static routes from config.yaml cannot be removed here.` — and returns 0. No confirmation prompt; the HMAC secret is destroyed with the route.
- **Rebuild notes:** Dict delete + atomic save. Better: `--yes` guard and an archive of removed routes for accidental deletions.

### `hermes webhook test` — send a signed test POST  `id: cli-c.webhook-test`
- **Surface:** CLI
- **Where:** `hermes webhook test <name> [--payload PAYLOAD]`. Help: `Send a test POST to a webhook route`.
- **What it does:** Posts a JSON payload to the local route with a valid HMAC-SHA256 signature so you can verify the whole path end-to-end.
- **How it works:** `_cmd_test(args)` (`hermes_cli/webhook.py:267`). Looks up the route's stored `secret`, computes `sig = "sha256=" + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()`, and issues a `urllib.request` POST to `<base>/webhooks/<name>` with headers `Content-Type: application/json`, `X-Hub-Signature-256: <sig>`, `X-GitHub-Event: test`, timeout 10 s.
- **Inputs / options:** positional `name` — "Subscription name to test"; `--payload PAYLOAD` (default `""`) — "JSON payload to send (default: test payload)". The built-in default payload is exactly `{"test": true, "event_type": "test", "message": "Hello from hermes webhook test"}`. `-h/--help`.
- **Outputs / side effects:** Prints `  Sending test POST to <url>` then `  Response (<status>): <body>`. A real agent run / delivery may be triggered by the test. Failure: `  Error: <e>` + `  Is the gateway running? (hermes gateway run)`.
- **Config / env:** `platforms.webhook.extra.host`/`port`.
- **Edge cases / guards:** Unknown route: `  No subscription named '<name>'.` and return. The payload string is sent as-is — it is **not** validated as JSON, so a malformed `--payload` reaches the server. Always signs with the *route's* secret, never the global `WEBHOOK_SECRET`. The `X-GitHub-Event: test` header is hard-coded, so a route filtering on GitHub event types sees `test`.
- **Rebuild notes:** HMAC + urllib POST. Better: validate the payload is JSON, allow choosing the event header, and support `--url` for remote testing.

## 4. `hermes peer` — bot-to-bot DMs across machines

### Peer command group  `id: cli-c.peer-group`
- **Surface:** CLI
- **Where:** `hermes peer {add,set,list,ls,remove,rm,dm,run,status,stop}`. Root help: `Bot-to-bot DMs across machines (peer Hermes gateways)`. Description: "Register other Hermes gateways as peers and message their agents. 'hermes peer dm <peer>[/<agent>] \"...\"' delivers into the remote agent's canonical Bot Chat over the peer's API server and prints the reply — the cross-machine twin of 'hermes -p <bot> chat'. The peer must run the api_server platform; its API_SERVER_KEY is stored locally as a credential in ~/.hermes/.env." Epilog: `Examples:` / `  hermes peer add spark --url http://spark.lan:8377 --key <API_SERVER_KEY>` / `  hermes peer list` / `  hermes peer dm spark "Message from 🤖 dixie (@dixie): disk status?"` / `  hermes peer dm spark/researcher "..."   # named profile on a multiplexed peer` / `  hermes peer run spark --idempotency-key ticket-123 < long-task.txt` / `  hermes peer status spark run_abc123` / `  hermes peer stop spark run_abc123` / `  hermes peer remove spark` / blank / `Exit codes: 0 ok, 1 delivery/peer error, 2 usage error.`
- **What it does:** Registers other Hermes gateways as named peers and gives every bot on this machine a transport to message bots on those machines, synchronously (`dm`) or asynchronously (`run`/`status`/`stop`).
- **How it works:** Whole implementation is `hermes_cli/subcommands/peer.py` (541 lines) — parser at line 443 (`build_peer_parser`), handler `cmd_peer` at line 244, `set_defaults(func=cmd_peer)` at line 541. Peer labels/URLs live in `config.yaml` under `bot_peers` (`_load_peers`/`_save_peers`, lines 57-70); the peer's API key is a **credential** in `~/.hermes/.env` as `HERMES_PEER_<NAME>_KEY` (`_peer_key_env`, line 53: `f"HERMES_PEER_{name.upper().replace('-', '_')}_KEY"`), read via the profile-scoped secret store `agent.secret_scope.get_secret` with a raw `os.environ` fallback (`_peer_secret`, line 73). No new server surface is added — the peer's stock `api_server` platform is the transport.
- **Inputs / options:** `-h/--help`; one of the sub-command tokens. Every remote sub-command takes a `target` of the form `<peer>` or `<peer>/<agent>`.
- **Outputs / side effects:** Bare `hermes peer` with no sub-command falls into the `list` branch (`action in ("list","ls",None)`, line 284) and lists peers.
- **Config / env:** `bot_peers.<name>.url`, `bot_peers.<name>.note`; env `HERMES_PEER_<NAME>_KEY`.
- **Edge cases / guards:** Timeouts: `DM_TIMEOUT_S = 600` for one synchronous agent turn, `LIST_TIMEOUT_S = 30` for everything else (lines 49-50). All requests go through `hermes_cli.urllib_security.open_credentialed_url`, which **strips non-safelisted headers across a cross-origin redirect** so a compromised/MITM'd peer cannot harvest the `Authorization: Bearer` key. Non-JSON responses raise `Peer returned non-JSON response: <first 200 chars>`; a non-object JSON body raises `Peer returned a non-object JSON response`. Fixed `User-Agent: hermes-peer-dm`.
- **Rebuild notes:** A named-URL registry + a bearer token per name + three REST calls (`/api/sessions`, `/api/sessions/{id}/chat`, `/v1/runs`). Better: mTLS or signed requests instead of a shared bearer, and peer capability negotiation cached locally.

### Peer target syntax `<peer>[/<agent>]`  `id: cli-c.peer-target-syntax`
- **Surface:** CLI
- **Where:** the `target` positional of `hermes peer dm|run|status|stop`.
- **What it does:** Selects the peer gateway and, optionally, a named profile ("agent") on a multiplexed peer.
- **How it works:** `_parse_target` (line 184) partitions on the first `/`. `_base_url` (line 125) then builds `<peer url>` for a bare target or `<peer url>/p/<url-quoted profile>` for a named profile — the peer's multiplex mirror, same handlers scoped to that profile. The bare target is the peer gateway's own (launch) profile.
- **Inputs / options:** `<peer>` must match `_PEER_NAME_RE = ^[a-z0-9][a-z0-9_-]{0,63}$` (line 45); `<agent>` must match `_PROFILE_RE = ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` (line 46) (note: profiles allow uppercase, peer names do not).
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Empty peer → `Peer name required (hermes peer dm <peer>[/<agent>] ...)` exit 2. Bad profile → `Invalid agent/profile name: '<p>'` exit 2. Unregistered peer → `No peer named '<peer>'. Run: hermes peer list` exit 1. Missing key → `No API key for peer '<peer>'. Set it: hermes peer add <peer> --url <url> --key <key> (or add HERMES_PEER_<NAME>_KEY=<key> to ~/.hermes/.env)` exit 1.
- **Rebuild notes:** `split("/", 1)` + two regexes + a registry lookup. Better: allow `peer/profile/session` to address a non-canonical session too.

### Remote canonical "Bot Chat" resolution  `id: cli-c.peer-bot-chat`
- **Surface:** CLI / API
- **Where:** implicit in `hermes peer dm` and `hermes peer run`.
- **What it does:** Finds (or creates) the single canonical session titled `Bot Chat` on the remote gateway, so every peer message lands in one continuous conversation.
- **How it works:** `BOT_CHAT_TITLE = "Bot Chat"` (line 44). `_find_bot_chat` (line 133) GETs `<base>/api/sessions?limit=200&title=Bot%20Chat&include_hidden=1` and matches the exact stripped title. Bot Mode always HIDES canonical chats, so a plain listing would miss it and a create would collide with the peer's `UNIQUE(title)` guard. Older peers ignore the unknown query params and return the ordinary visible listing, degrading to the previous behaviour. `_ensure_bot_chat` (line 152) POSTs `<base>/api/sessions` with `{"title": "Bot Chat", "source": "bot_peer_dm"}` when nothing is found, and unwraps the api_server envelope `{"object": "hermes.session", "session": {...}}`.
- **Inputs / options:** n/a
- **Outputs / side effects:** May create a session on the remote machine.
- **Config / env:** n/a
- **Edge cases / guards:** On HTTP 400 whose detail mentions `title`, it raises the explanatory error: `Peer already has a 'Bot Chat' session but it is hidden and the peer's gateway is too old to expose hidden sessions to this lookup (HTTP 400: <detail>). Update the peer's hermes-agent, or unhide the session there: PATCH /api/sessions/<id> {"hidden": false}.` If the create returns no id: `Peer did not return a session id for the new Bot Chat`.
- **Rebuild notes:** Exact-title lookup including hidden, else create. Better: address the canonical chat by a stable well-known id instead of by title.

### `hermes peer add` (alias `set`) — register/update a peer  `id: cli-c.peer-add`
- **Surface:** CLI
- **Where:** `hermes peer add <name> --url URL [--key KEY] [--note NOTE]`, alias `hermes peer set`. Help: `Register (or update) a peer gateway`.
- **What it does:** Stores a peer's name → base URL (and optional note) in `config.yaml`, and its API key in `~/.hermes/.env`.
- **How it works:** `cmd_peer` lines 246-271. Name is `strip().lower()` then validated against `_PEER_NAME_RE`. URL must start with `http://` or `https://` (case-insensitive) and is stored with trailing slashes stripped. The record is `{"url": <url>, "note": <note>}` (note only when non-empty). Key is written via `hermes_cli.config.save_env_value(_peer_key_env(name), key)`.
- **Inputs / options:** positional `name` — "Peer name (lowercase slug, e.g. spark, homelab)"; `--url URL` (**required**) — "Peer gateway base URL, e.g. http://spark.lan:8377"; `--key KEY` (default `""`) — "The peer's API_SERVER_KEY (stored in ~/.hermes/.env)"; `--note NOTE` (default `""`) — "Optional description"; `-h/--help`.
- **Outputs / side effects:** Rewrites `config.yaml`'s `bot_peers` map and, with a key, `~/.hermes/.env`. With a key: `Peer '<name>' saved (<url>) — key stored as HERMES_PEER_<NAME>_KEY in ~/.hermes/.env`. Without: `Peer '<name>' saved (<url>). No key given — set the peer's API_SERVER_KEY with:` + `  hermes peer add <name> --url <url> --key <key>` + `  (or add HERMES_PEER_<NAME>_KEY=<key> to ~/.hermes/.env)`. Exit 0.
- **Config / env:** writes `bot_peers`, `HERMES_PEER_<NAME>_KEY`.
- **Edge cases / guards:** Bad name → stderr `Invalid peer name: '<name>' (lowercase, digits, -, _; max 64)` exit **2**. Bad URL → stderr `Peer --url must be an http(s) gateway base URL, e.g. http://spark.lan:8377` exit **2**. Re-adding an existing name replaces the whole record (note is dropped unless re-supplied). The key is echoed nowhere, but it is passed on the command line and therefore visible in shell history / process listings.
- **Rebuild notes:** Two writes (config + env) with two regex validations. Better: read the key from stdin or a prompt so it never enters shell history.

### `hermes peer list` (alias `ls`) — list registered peers  `id: cli-c.peer-list`
- **Surface:** CLI
- **Where:** `hermes peer list`, `hermes peer ls`, or bare `hermes peer`. Help: `List registered peers`.
- **What it does:** Prints each registered peer with its URL, whether a key is present, and its note.
- **How it works:** lines 284-294; iterates `sorted(peers)` from `config.yaml`'s `bot_peers` and probes `_peer_secret(name)` for each.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. Empty: `No peers registered. Add one: hermes peer add <name> --url http://host:port --key <API_SERVER_KEY>` exit 0. Otherwise one **tab-separated** line per peer: `<name>\t<url or ?>\t[key set]` or `<name>\t<url>\t[NO KEY (HERMES_PEER_<NAME>_KEY unset)]`, with ` — <note>` appended when a note exists. Exit 0.
- **Config / env:** reads `bot_peers`, `HERMES_PEER_*_KEY`.
- **Edge cases / guards:** A malformed (non-dict) entry degrades to `{}` and prints `?` for the URL. Secrets are never printed, only their presence.
- **Rebuild notes:** Sorted iteration + presence probe. Better: `--json` and a `--check` that pings each peer's `/v1/capabilities`.

### `hermes peer remove` (alias `rm`) — remove a peer  `id: cli-c.peer-remove`
- **Surface:** CLI
- **Where:** `hermes peer remove <name>`, `hermes peer rm <name>`. Help: `Remove a peer`.
- **What it does:** Deletes a peer's entry from `config.yaml`, leaving its `.env` key in place.
- **How it works:** lines 273-282; `strip().lower()` the name, `peers.pop(name)`, `_save_peers`.
- **Inputs / options:** positional `name` — "Peer name"; `-h/--help`.
- **Outputs / side effects:** `Peer '<name>' removed (its HERMES_PEER_<NAME>_KEY entry in .env is kept; delete it manually if unused).` Exit 0.
- **Config / env:** mutates `bot_peers`.
- **Edge cases / guards:** Unknown name → stderr `No peer named '<name>'.` exit 1. The credential is deliberately **not** deleted — the message tells the user to remove it manually.
- **Rebuild notes:** Dict pop + save. Better: offer `--purge-key`.

### `hermes peer dm` — one synchronous remote turn  `id: cli-c.peer-dm`
- **Surface:** CLI
- **Where:** `hermes peer dm <target> [message] [--json]`. Help: `Message an agent on a peer gateway and print its reply`.
- **What it does:** Delivers a message into the remote agent's canonical Bot Chat, waits for the full agent turn, and prints the reply.
- **How it works:** lines 404-434. Resolves the target, ensures the remote Bot Chat, then POSTs `<base>/api/sessions/<url-quoted session_id>/chat` with `{"message": message}` and `timeout=DM_TIMEOUT_S` (600 s). The reply is `result["message"]["content"]` when `message` is a dict.
- **Inputs / options:** positional `target` — "<peer> or <peer>/<agent> (named profile on a multiplexed peer)"; positional optional `message` (default None) — "Message text (or stdin)"; `--json` (store_true, default False) — "Emit a JSON result"; `-h/--help`. The message may come from **stdin** when the argument is absent and stdin is not a TTY (`_message_from_args`, line 222).
- **Outputs / side effects:** Runs a real agent turn on the remote machine (tokens, tools, side effects there). Human output: the reply text, or `(no reply)` when empty. JSON output: `{"peer":…, "profile":…, "session_id":…, "reply":…}` on one line. Exit 0.
- **Config / env:** `bot_peers`, `HERMES_PEER_<NAME>_KEY`.
- **Edge cases / guards:** Empty message → stderr `Message required (argument or stdin).` exit 2. HTTP error → stderr `Peer '<name>' rejected the request (HTTP <code>): <detail>` exit 1 (detail extracted from `error.message` in the JSON body, else the first 200 bytes). `RuntimeError` (non-JSON / hidden-Bot-Chat) → stderr `Peer '<name>': <exc>` exit 1. Network/timeout → stderr `Could not reach peer '<name>': <exc>` exit 1. A turn longer than 10 minutes is cut off — that is what `run` exists for.
- **Rebuild notes:** Ensure session → POST chat → print `message.content`. Better: stream the reply (SSE) instead of holding one 10-minute request.

### `hermes peer run` — start an asynchronous remote run  `id: cli-c.peer-run`
- **Surface:** CLI
- **Where:** `hermes peer run <target> [message] [--idempotency-key KEY] [--json]`. Help: `Start a long peer turn asynchronously and return its run ID`.
- **What it does:** Starts the same canonical-session turn through the peer's Runs API and returns a `run_id` immediately, without holding the HTTP connection open.
- **How it works:** lines 345-402. Generates an idempotency key `peer-<uuid4 hex>` when none is given, probes `_peer_run_durability(base, key)` (line 229 — GETs `<base>/v1/capabilities` and reads `features.runs_idempotency.{supported,durable}`), ensures the Bot Chat, then POSTs `<base>/v1/runs` with body `{"input": message, "session_id": session_id}` and header `Idempotency-Key: <key>`.
- **Inputs / options:** positional `target`; positional optional `message` (or stdin); `--idempotency-key IDEMPOTENCY_KEY` (default None) — "Stable retry key (generated when omitted)"; `--json` (store_true) — "Emit a JSON result"; `-h/--help`.
- **Outputs / side effects:** Starts a remote run. Human output: `<run_id>: <status>` (with ` (replayed)` appended when the peer reports a replay), then `session_id: <id>` and `idempotency_key: <key>`. JSON output: `{"peer","profile","session_id","run_id","status","idempotency_key","replayed"}`. Default status when the peer omits it is `started`. Exit 0.
- **Config / env:** as `dm`.
- **Edge cases / guards:** Idempotency key validation: must be 1-255 chars with no `\r`, `\n` or NUL, otherwise stderr `Idempotency key must be 1-255 characters without control newlines.` exit 2. When the peer does not advertise **restart-durable** replay (`durability is not True`, which includes older peers that cannot advertise it at all) it prints to stderr: `Warning: this peer does not advertise restart-durable run replay; keep the run ID and avoid blind retries after a gateway restart.` Missing run id in the response → stderr `Peer '<name>' did not return a run ID.` exit 1. Same HTTP/network error strings as `dm`. Empty message → exit 2.
- **Rebuild notes:** POST `/v1/runs` with an `Idempotency-Key`; poll separately. Better: a `--wait` flag that polls `status` until terminal.

### `hermes peer status` — read an asynchronous run  `id: cli-c.peer-status`
- **Surface:** CLI
- **Where:** `hermes peer status <target> <run_id> [--json]`. Help: `Read the status and final output of an asynchronous peer run`.
- **What it does:** Polls one run handle on a peer and prints its status plus final output (or error).
- **How it works:** lines 308-337; GETs `<base>/v1/runs/<url-quoted run_id>` with the standard 30 s `LIST_TIMEOUT_S`.
- **Inputs / options:** positional `target`; positional `run_id` — "Run ID returned by 'hermes peer run'"; `--json` (store_true); `-h/--help`.
- **Outputs / side effects:** Read-only on the peer. Human output: `<run_id>: <status or 'unknown'>`, then `result["output"]` on stdout when present, else `result["error"]` on **stderr**. JSON output: `{"peer":…, "profile":…, **result}`. Exit 0 even for a failed remote run.
- **Config / env:** as `dm`.
- **Edge cases / guards:** Empty run id → stderr `Run ID required.` exit 2. HTTP/network errors as in `dm`/`run`. Note the exit code does **not** reflect the remote run's success — callers must parse `status`.
- **Rebuild notes:** GET the run resource, print two fields. Better: exit non-zero on a failed remote run, and support `--follow`.

### `hermes peer stop` — stop one asynchronous run  `id: cli-c.peer-stop`
- **Surface:** CLI
- **Where:** `hermes peer stop <target> <run_id> [--json]`. Help: `Stop one asynchronous peer run without affecting another turn`.
- **What it does:** Cancels a single in-flight run on a peer, leaving any other turn on that peer untouched.
- **How it works:** Same branch as `status` (lines 308-337) but POSTs `<base>/v1/runs/<run_id>/stop` with an empty JSON body `{}`.
- **Inputs / options:** positional `target`; positional `run_id`; `--json` (store_true); `-h/--help`.
- **Outputs / side effects:** Cancels the remote run. Human output: `<run_id>: <status>` (the `output`/`error` printing is `status`-only, so `stop` prints just the one line). JSON output: `{"peer","profile", **result}`. Exit 0.
- **Config / env:** as `dm`.
- **Edge cases / guards:** Empty run id → `Run ID required.` exit 2. Stopping an already-finished run is whatever the peer's endpoint returns; the CLI does not special-case it.
- **Rebuild notes:** POST `/stop` on the run resource. Better: report whether the stop actually took effect vs. the run having already finished.

## 5. `hermes portal` — Nous Portal onboarding & Tool Gateway

### Portal command group  `id: cli-c.portal-group`
- **Surface:** CLI
- **Where:** `hermes portal [{login,info,status,open,tools}]`. Root help: `Set up Nous Portal (login, model pick, Tool Gateway); see also \`portal info\``. Description: "Run `hermes portal` with no subcommand to log in to Nous Portal and set it up — pick a model, set Nous as your provider, and offer the Tool Gateway (the human-readable alias for `hermes auth add nous --type oauth`, identical to `hermes setup --portal`). Subcommands: login (default), info, open, tools."
- **What it does:** The onboarding + discovery surface for the Nous Portal subscription: log in, see what is routed through Portal, open the subscription page, and list the Tool Gateway catalog.
- **How it works:** Whole implementation is `hermes_cli/portal_cli.py` (246 lines). Parser registered by `add_parser(subparsers)` at line 212, `set_defaults(func=portal_command)` at line 246. Dispatch `portal_command` at line 192: `None`/`""`/`login` → `_cmd_login`; `info` **or** `status` → `_cmd_status`; `open` → `_cmd_open`; `tools` → `_cmd_tools`. Module constants: `DEFAULT_PORTAL_URL = "https://portal.nousresearch.com"`, `SUBSCRIPTION_URL = "https://portal.nousresearch.com/manage-subscription"`, `DOCS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway"` (lines 29-31).
- **Inputs / options:** `-h/--help`; one of `login`, `info`, `status`, `open`, `tools` (all take no options of their own beyond `-h`).
- **Outputs / side effects:** Unknown sub-command → stderr `Unknown portal subcommand: <sub>` + `Run \`hermes portal -h\` for usage.` return 1.
- **Config / env:** Reads `config.yaml` (`model.provider`) and the Nous auth/subscription state.
- **Edge cases / guards:** Deliberately minimal — it does not duplicate `hermes auth` or `hermes tools`.
- **Rebuild notes:** Five thin commands over an OAuth state reader and a static partner catalog. Better: make `info` machine-readable (`--json`) so scripts can assert Portal state.

### `hermes portal` / `hermes portal login` — one-shot Portal onboarding  `id: cli-c.portal-login`
- **Surface:** CLI
- **Where:** `hermes portal` (bare) or `hermes portal login`. Help: `Log in to Nous Portal + set it up (default; one-shot onboarding)`.
- **What it does:** Runs device-code OAuth login against Nous Portal, lets you pick a Nous model, switches the inference provider to `nous`, and offers the Tool Gateway opt-in — all in one command.
- **How it works:** `_cmd_login` (`hermes_cli/portal_cli.py:171`) loads config and calls `hermes_cli.setup._run_portal_one_shot(config)` (`hermes_cli/setup.py:2869`), which prints the banner and then delegates **everything** to `hermes_cli.main._model_flow_nous(config)` — the identical routine used by first-time quick setup (`_run_first_time_quick_setup`) and by `hermes model` when Nous is picked. It handles both the logged-out path (device-code OAuth, which selects a model internally) and the already-logged-in path (curated Nous model picker).
- **Inputs / options:** `-h/--help` only. Interactive prompts come from the shared Nous model flow (model picker, Tool Gateway opt-in yes/no).
- **Outputs / side effects:** Writes Nous OAuth credentials, `model.provider: nous` and the selected model into `config.yaml`; may enable Tool Gateway routing. Banner printed verbatim (MAGENTA): `┌─────────────────────────────────────────────────────────┐`, `│     ⚕ Hermes Setup — Nous Portal (one-shot)             │`, `└─────────────────────────────────────────────────────────┘`, then `  One subscription, 300+ models, plus the Tool Gateway:`, `    web search, image generation, TTS, browser automation`, `    — all routed through your Nous Portal sub.`, `  Sign up: https://portal.nousresearch.com/manage-subscription`.
- **Config / env:** `model.provider`, Nous auth store; Portal base URL from the auth record (`portal_base_url`) defaulting to `https://portal.nousresearch.com`.
- **Edge cases / guards:** `KeyboardInterrupt`/`EOFError` at the CLI layer → `Portal setup cancelled.` and return 1. Inside `_run_portal_one_shot`, `KeyboardInterrupt`/`EOFError`/**`SystemExit`** are all caught (because `_login_nous` raises `SystemExit(130)`/`(1)` on cancel/failure and the expired-session re-login path only catches `Exception`, so an uncaught `SystemExit` would kill the whole CLI) and reported as `  Setup cancelled.` + `  You can retry later with \`hermes portal\`.`
- **Rebuild notes:** Delegate to one shared provider-onboarding routine rather than re-implementing auth+model+provider writes. Better: a `--non-interactive` mode that takes a model id and a device-code token.

### `hermes portal info` (alias `status`) — Portal auth + routing summary  `id: cli-c.portal-info`
- **Surface:** CLI
- **Where:** `hermes portal info`; `hermes portal status` is a retained (undocumented in the sub-list, registered without a help string) back-compat alias for the prior default. Help for `info`: `Show Portal auth + Tool Gateway routing summary`.
- **What it does:** Prints whether you are logged into Nous Portal, which Portal/API URLs are in use, whether Nous is your inference provider, and for each Tool Gateway feature whether it is routed via Nous, via another provider, active, or not configured.
- **How it works:** `_cmd_status` (`hermes_cli/portal_cli.py:34`). Auth: `hermes_cli.auth.get_nous_auth_status_local()` — deliberately a **refresh-free snapshot** (no OAuth refresh) because this is a read-only display. Provider: `config["model"]["provider"]` lowercased. Features: `hermes_cli.nous_subscription.get_nous_subscription_features(config)`, iterating `features.items()` and reading each feature's `label`, `managed_by_nous`, `active`, `current_provider`. Labels are left-padded to the widest label.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. Verbatim structure: blank, MAGENTA `  Nous Portal`, MAGENTA `  ───────────`; logged in → `  Auth:    ✓ logged in` (GREEN), `  Portal:  <portal_base_url>`, `  API:     <inference_base_url>` (only when present); logged out → `  Auth:    not logged in` (YELLOW), `  Sign up: https://portal.nousresearch.com/manage-subscription`, `  Login:   hermes portal`. Then provider: `  Model:   ✓ using Nous as inference provider` (GREEN) when provider == `nous`, else `  Model:   currently <provider> (switch with \`hermes model\`)` when a provider is set (nothing when unset). Then blank, MAGENTA `  Tool Gateway`, MAGENTA `  ────────────`; if features cannot be resolved → `  (could not resolve subscription state)` and return 0; otherwise one aligned row per feature `  <label>   <state>` where state is `via Nous Portal` (GREEN), `<current_provider>`, `active`, or `not configured` (DIM). When not logged in it ends with DIM `  Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway`. Always returns 0.
- **Config / env:** `model.provider`; Nous auth store.
- **Edge cases / guards:** Both the auth read and the feature read are wrapped in bare `except Exception` and degrade to `{}` / `None` — the command never fails, it just says less.
- **Rebuild notes:** Two state reads + an aligned table. Better: exit non-zero when logged out so `hermes portal info && …` composes.

### `hermes portal open` — open the subscription page  `id: cli-c.portal-open`
- **Surface:** CLI
- **Where:** `hermes portal open`. Help: `Open the Portal subscription page in your default browser`.
- **What it does:** Launches the system browser at the Nous Portal subscription-management page.
- **How it works:** `_cmd_open` (`hermes_cli/portal_cli.py:107`): prints the target, then `webbrowser.open(SUBSCRIPTION_URL)` inside a try/except.
- **Inputs / options:** `-h/--help` only. The URL is fixed — `https://portal.nousresearch.com/manage-subscription`.
- **Outputs / side effects:** `Opening https://portal.nousresearch.com/manage-subscription`. On success return 0. On failure: blank line + `Could not launch a browser. Visit the URL above manually.` and return 1.
- **Config / env:** honours whatever `webbrowser` resolves (`BROWSER` env on Unix).
- **Edge cases / guards:** Headless/SSH sessions typically return `opened=False` → exit 1, which is the documented way to detect it.
- **Rebuild notes:** `webbrowser.open` + a fallback message. Better: print a QR code for remote/headless machines.

### `hermes portal tools` — Tool Gateway catalog  `id: cli-c.portal-tools`
- **Surface:** CLI
- **Where:** `hermes portal tools`. Help: `List Tool Gateway tools and which are routed via Nous`.
- **What it does:** Prints the five Tool Gateway capabilities, the partner behind each, and how each is currently routed.
- **How it works:** `_cmd_tools` (`hermes_cli/portal_cli.py:122`). The catalog is a **static list** in the source (line 134): `("web", "Web search & extract", "Firecrawl")`, `("image_gen", "Image generation", "FAL")`, `("tts", "Text-to-speech", "OpenAI TTS")`, `("browser", "Browser automation", "Browser Use")`, `("modal", "Cloud terminal", "Modal")`. Each key is looked up in `get_nous_subscription_features(config).features`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. Blank, MAGENTA `  Tool Gateway catalog`, MAGENTA `  ────────────────────`; when `features.nous_auth_present` is false → YELLOW `  Not logged into Nous Portal — sign in with \`hermes portal\`.` plus a blank line. Then one row per catalog entry: `  <label padded>  partner: <partner padded to 14> <state>`, where state is `unknown` (DIM, feature key absent), `✓ via Nous Portal` (GREEN), `<current_provider>`, `active`, or `not configured` (DIM). Footer: blank, DIM `  Manage your subscription: https://portal.nousresearch.com/manage-subscription`, DIM `  Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway`. Return 0.
- **Config / env:** Nous subscription state derived from `config.yaml` + auth store.
- **Edge cases / guards:** If `get_nous_subscription_features` raises, prints to **stderr** `Could not resolve Tool Gateway state.` and returns 1 (unlike `info`, which degrades gracefully).
- **Rebuild notes:** Static catalog × dynamic feature state. Better: fetch the catalog from the Portal so new partners appear without a client release.

## 6. `hermes project` — named multi-folder workspaces

### Project command group  `id: cli-c.project-group`
- **Surface:** CLI
- **Where:** `hermes project {create,list,ls,show,add-folder,remove-folder,rename,set-primary,use,archive,restore,bind-board}`. Root help: `Manage projects (named, multi-folder workspaces)`. Description: "Projects are human-named workspaces that can span multiple folders / repos. They anchor desktop session grouping and, when bound to a kanban board, give tasks a deterministic worktree + branch convention. State is per-profile."
- **What it does:** Creates and manages explicit, persisted "Project" entities — a human name plus one or more folders with one designated primary repo — which the desktop uses to group sessions and kanban uses to place worktrees.
- **How it works:** Parser `build_parser` at `hermes_cli/projects_cmd.py:22`; dispatch `projects_command` at line 108 with an explicit `handlers` dict (line 122) mapping each action (including the `ls` alias) to a `_cmd_*` function. Handler registered as `cmd_project` (`hermes_cli/main.py:5876`) → `hermes_cli.projects_cmd.projects_command`. Project-scoped sub-commands share the `_with_project` decorator (line 151) which opens the DB, resolves `args.project`, returns 1 on not-found and 2 on `ValueError`.
- **Inputs / options:** `-h/--help`; one of the 12 sub-command tokens.
- **Outputs / side effects:** With **no** action it prints the group's own `--help` (via the `_project_parser` default stashed at line 104) and returns **0**; if that default is missing it prints to stderr `usage: hermes project <action> [options]` + `Run 'hermes project --help' for the full list.` Unknown action → stderr `Unknown project action: <a>` return 1.
- **Config / env:** `HERMES_HOME` selects the profile whose `projects.db` is used.
- **Edge cases / guards:** Described in the source as "a footprint-ladder rung-2 capability: a CLI command + gateway RPC, with zero model-tool schema cost" — there is deliberately **no** model tool for projects.
- **Rebuild notes:** Twelve verbs over a two-table SQLite store. Better: a `--json` output mode so the desktop and CLI share one contract.

### Project store (`$HERMES_HOME/projects.db`)  `id: cli-c.project-store`
- **Surface:** Core / CLI
- **Where:** Not user-visible directly; backs every `hermes project` sub-command and the desktop Projects view.
- **What it does:** Persists projects, their folders, the active-project pointer and a cache of git repos discovered by filesystem scan.
- **How it works:** `hermes_cli/projects_db.py`. Path `get_hermes_home() / "projects.db"` (`projects_db_path`, line 44) — **per-profile**, deliberately unlike kanban whose board DB is root-anchored and shared across profiles. Schema (`SCHEMA_SQL`, line 56): `projects(id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description, icon, color, board_slug, primary_path, created_at INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0)`; `project_folders(project_id REFERENCES projects(id) ON DELETE CASCADE, path, label, is_primary INTEGER DEFAULT 0, added_at, PRIMARY KEY (project_id, path))` with `idx_project_folders_path`; `project_meta(key TEXT PRIMARY KEY, value TEXT)`; `discovered_repos(root TEXT PRIMARY KEY, label, last_seen INTEGER NOT NULL)`. WAL with fallback (`apply_wal_with_fallback`, `db_label="projects.db"`). Ids are `"p_" + secrets.token_hex(4)`. Meta keys: `active_id` (`_ACTIVE_META_KEY`, line 639), `repo_discovery_policy` (line 640).
- **Inputs / options:** n/a
- **Outputs / side effects:** All project state.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Column additions go through `_add_column_if_missing` so opening an old DB is always safe. Paths are normalised by `_normalize_path` — `os.path.abspath(os.path.expanduser(strip(path)))` with trailing `/` and `\` stripped.
- **Rebuild notes:** Four tables, additive migrations, one meta KV row for "active". Better: store folder paths relative to a machine-id so a synced DB works across hosts.

### Project slug rules  `id: cli-c.project-slug`
- **Surface:** CLI / Core
- **Where:** `--slug` on `hermes project create`, and the `<project>` positional everywhere (which accepts id **or** slug).
- **What it does:** Turns a human name into a stable, filesystem- and branch-safe handle.
- **How it works:** `_SLUG_RE = ^[a-z0-9][a-z0-9\-_]{0,63}$` (`hermes_cli/projects_db.py:107`). `_slugify(name)` lowercases, replaces every run of non-`[a-z0-9]` with `-`, strips leading/trailing `-`/`_`, truncates to 64, and falls back to the literal `project` when nothing survives. `normalize_slug(slug)` lowercases+strips and validates. `_unique_slug` (line 308) de-duplicates against existing rows. `get_project` (line 441) looks up **by id first, then by lowercased slug**.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** An invalid explicit slug raises `invalid project slug '<x>': must be 1-64 chars, lowercase alphanumerics / hyphens / underscores, not starting with '-' or '_'` — surfaced as `project: <msg>` on stderr with exit 2. The regex is strict enough to stop path traversal and separators.
- **Rebuild notes:** One regex + a slugifier + a uniquifier. Better: reserve a small set of slugs (e.g. `all`, `new`) that would collide with CLI verbs.

### Deterministic project branch names  `id: cli-c.project-branch-name`
- **Surface:** Core (consumed by kanban)
- **Where:** Applied when a kanban task belongs to a project (see `hermes project bind-board`).
- **What it does:** Gives a project-linked kanban task a stable, human-meaningful git branch instead of the random `wt/<task-id>` fallback.
- **How it works:** `branch_name_for(project, task_id, title="")` (`hermes_cli/projects_db.py:810`): `<project-slug>/<task-id>`, plus `-<title-slug>` when a title is given, where the title slug is `re.sub(r"[^a-z0-9._-]+", "-", title.strip().lower()).strip("-")` truncated to 40 chars (`_BRANCH_SAFE_RE`, line 807).
- **Inputs / options:** n/a
- **Outputs / side effects:** The worktree branch created for a task.
- **Config / env:** n/a
- **Edge cases / guards:** A project with an empty slug falls back to `_slugify(project.name)`. Very long titles are truncated, so two tasks with similar long titles can only collide if their ids collide (they cannot — the id is in the name).
- **Rebuild notes:** `slug/task-id[-title]`. Better: guarantee uniqueness against existing remote branches before creating.

### `hermes project create` — create a project  `id: cli-c.project-create`
- **Surface:** CLI
- **Where:** `hermes project create <name> [folders ...] [--slug SLUG] [--primary PATH] [--description DESCRIPTION] [--icon ICON] [--color COLOR] [--board SLUG] [--use]`. Help: `Create a new project`.
- **What it does:** Creates a named project with any number of folders, one primary repo, optional cosmetics and an optional kanban-board binding, and can immediately make it the active project.
- **How it works:** `_cmd_create` (`hermes_cli/projects_cmd.py:191`) → `pdb.create_project(...)` (`hermes_cli/projects_db.py:348`). Folder handling: each path is normalised and de-duplicated in order; if `--primary` is given it is **inserted at position 0** of the folder list when absent; otherwise the first folder becomes primary. `--use` then calls `pdb.set_active(conn, pid)`.
- **Inputs / options:** positional `name` — "Human name, e.g. 'Hermes Agent'"; positional variadic `folders` (`nargs="*"`) — "Folder paths to include (first = primary)"; `--slug SLUG` (default None) — "Explicit slug override"; `--primary PATH` (default None, metavar `PATH`) — "Primary repo path"; `--description DESCRIPTION` (default None, no help text); `--icon ICON` (default None, no help text); `--color COLOR` (default None, no help text); `--board SLUG` (default None, metavar `SLUG`) — "Bind a kanban board"; `--use` (store_true) — "Set as the active project"; `-h/--help`.
- **Outputs / side effects:** Inserts one `projects` row + one `project_folders` row per folder. Prints `Created project <slug> (<id>)` followed by the standard project block (`_print_project`, line 173): `<slug>  [<id>]` (with ` (archived)` when archived), `  name:    <name>`, `  about:   <description>` (if set), `  board:   <board_slug>` (if set), `  primary: <primary_path>` (if set), `  folders:` then per folder `    * <path> (<label>)` for the primary or `      <path>` otherwise. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Empty name → `project: project name must not be empty` (stderr) exit 2. A create whose resolved primary path already belongs to a **non-archived** project raises `folder already belongs to project '<slug>' (<id>); switch to it instead of creating a duplicate` → exit 2 (duplicates would multiply the desktop sidebar's per-project repo subtrees). The `allow_duplicate_path=True` bypass exists in the API but is **not** exposed as a CLI flag. Slug collisions are resolved silently by `_unique_slug`. A post-create disappearance prints `project: vanished after create` exit 2.
- **Rebuild notes:** Insert + folder rows in one transaction, with primary-path duplicate detection. Better: expose `--allow-duplicate-path` and `--no-primary`.

### `hermes project list` (alias `ls`) — list projects  `id: cli-c.project-list`
- **Surface:** CLI
- **Where:** `hermes project list [--all]`, `hermes project ls [--all]`. Help: `List projects`.
- **What it does:** Lists projects one per line with an active marker, slug, name, archived flag and folder count.
- **How it works:** `_cmd_list` (`hermes_cli/projects_cmd.py:219`): reads `pdb.get_active_id(conn)` then `pdb.list_projects(conn, include_archived=…)`.
- **Inputs / options:** `--all` (store_true, dest `include_archived`) — "Include archived projects"; `-h/--help`.
- **Outputs / side effects:** Read-only. Empty: `No projects yet. Create one with \`hermes project create <name>\`.` return 0. Otherwise per project: `<marker> <slug padded to 24> <name>[ (archived)]  [<n> folder(s)]`, where marker is `*` for the active project and a space otherwise.
- **Config / env:** n/a
- **Edge cases / guards:** Archived projects are hidden unless `--all`.
- **Rebuild notes:** One SELECT + a formatted line. Better: show the bound board and primary path columns.

### `hermes project show` — show a project's details  `id: cli-c.project-show`
- **Surface:** CLI
- **Where:** `hermes project show <project>`. Help: `Show a project's details`.
- **What it does:** Prints one project's full record: slug, id, archived flag, name, description, bound board, primary path and every folder.
- **How it works:** `_cmd_show` (`hermes_cli/projects_cmd.py:237`, wrapped in `_with_project`) → `_print_project(proj)`.
- **Inputs / options:** positional `project` — "Project id or slug"; `-h/--help`.
- **Outputs / side effects:** Read-only. Exactly the `_print_project` block described under `create`.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown project → stderr `project: no such project: <ident>` exit 1 (from `_resolve`, line 144).
- **Rebuild notes:** Lookup + fixed printer. Better: `--json`.

### `hermes project add-folder` — add a folder  `id: cli-c.project-add-folder`
- **Surface:** CLI
- **Where:** `hermes project add-folder <project> <path> [--label LABEL] [--primary]`. Help: `Add a folder to a project`.
- **What it does:** Adds a folder (repo) to a project, optionally labelling it and making it the primary repo.
- **How it works:** `_cmd_add_folder` (`hermes_cli/projects_cmd.py:243`) → `pdb.add_folder(conn, proj.id, path, label=…, is_primary=…)` (`hermes_cli/projects_db.py:503`). `INSERT OR IGNORE` on `(project_id, path)`; the label is applied with a follow-up UPDATE when provided. With `is_primary` the previous primary is demoted and `projects.primary_path` is repointed (`_set_primary_locked`). Without it, the **first** folder of an otherwise-empty project becomes primary implicitly.
- **Inputs / options:** positional `project` — "Project id or slug"; positional `path` — "Folder path"; `--label LABEL` (default None, no help text); `--primary` (store_true) — "Mark as primary repo"; `-h/--help`.
- **Outputs / side effects:** Inserts/updates a `project_folders` row. Prints `Added <normalized path> to <slug>` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Empty path → `project: folder path must not be empty` exit 2. Unknown project id inside the store → `project: no such project: <id>` exit 2 (the wrapper already catches the CLI-level not-found at exit 1). Re-adding the same path is a silent no-op (`INSERT OR IGNORE`) but still prints `Added …`. The path is not required to exist on disk.
- **Rebuild notes:** Upsert + primary bookkeeping. Better: warn when the path does not exist or is not a git repo.

### `hermes project remove-folder` — remove a folder  `id: cli-c.project-remove-folder`
- **Surface:** CLI
- **Where:** `hermes project remove-folder <project> <path>`. Help: `Remove a folder from a project`.
- **What it does:** Detaches a folder from a project, repointing the primary if the removed folder was it.
- **How it works:** `_cmd_remove_folder` (`hermes_cli/projects_cmd.py:250`) → `pdb.remove_folder(conn, proj.id, path)` (`hermes_cli/projects_db.py:549`): normalises the path, notes whether it was primary, DELETEs the row, and repoints `primary` when needed.
- **Inputs / options:** positional `project`; positional `path` — "Folder path"; `-h/--help`.
- **Outputs / side effects:** Deletes the row; prints `Removed <path> from <slug>` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Path not in the project → stderr `project: folder not in project: <path>` exit 1. The message echoes the **raw** argument, not the normalised path, which can confuse when the user passed a relative path.
- **Rebuild notes:** DELETE + primary repoint. Better: echo the normalised path in the error.

### `hermes project rename` — rename a project  `id: cli-c.project-rename`
- **Surface:** CLI
- **Where:** `hermes project rename <project> <name>`. Help: `Rename a project`.
- **What it does:** Changes a project's display name; the slug is unchanged.
- **How it works:** `_cmd_rename` (`hermes_cli/projects_cmd.py:259`) → `pdb.update_project(conn, proj.id, name=args.name)` (line 457). Only supplied fields are patched.
- **Inputs / options:** positional `project`; positional `name` — "New name"; `-h/--help`.
- **Outputs / side effects:** `Renamed <slug> -> <new name>` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Empty/whitespace name → `project: project name must not be empty` exit 2. **The slug is deliberately not re-derived**, so a renamed project keeps its original handle (and its branch names stay stable).
- **Rebuild notes:** One UPDATE. Better: offer `--reslug` with an explicit warning about branch-name churn.

### `hermes project set-primary` — set the primary folder  `id: cli-c.project-set-primary`
- **Surface:** CLI
- **Where:** `hermes project set-primary <project> <path>`. Help: `Set the primary folder`.
- **What it does:** Designates which of a project's folders is the primary repo (where worktrees are created).
- **How it works:** `_cmd_set_primary` (`hermes_cli/projects_cmd.py:266`) → `pdb.set_primary(conn, proj.id, path)` (line 598), which demotes the old primary, promotes the new one and updates `projects.primary_path`.
- **Inputs / options:** positional `project`; positional `path` — "Folder path (must already be in project)"; `-h/--help`.
- **Outputs / side effects:** `Set primary of <slug> -> <path>` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Path not already a folder of the project → stderr `project: '<path>' is not a folder of <slug>; add it first with \`hermes project add-folder\`.` exit 1. It never implicitly adds the folder.
- **Rebuild notes:** Two UPDATEs in one transaction. Better: accept `--add` to add-and-promote in one step.

### `hermes project use` — set / clear the active project  `id: cli-c.project-use`
- **Surface:** CLI
- **Where:** `hermes project use [project]`. Help: `Set the active project`.
- **What it does:** Points the profile's "active project" at a project, or clears it when the argument is omitted.
- **How it works:** `_cmd_use` (`hermes_cli/projects_cmd.py:278`) → `pdb.set_active(conn, proj.id)` or `pdb.set_active(conn, None)` (`hermes_cli/projects_db.py:643`), which upserts/deletes the `project_meta` row with key `active_id`.
- **Inputs / options:** positional optional `project` (`nargs="?"`, default None) — "Project id or slug (omit to clear)"; `-h/--help`.
- **Outputs / side effects:** Set: `Active project: <slug>` return 0. Clear: `Cleared active project` return 0. The `*` marker in `hermes project list` follows this pointer.
- **Config / env:** Stored per-profile in `projects.db`, so switching `HERMES_HOME`/profile switches the active project.
- **Edge cases / guards:** Unknown project → `project: no such project: <ident>` exit 1. Note this handler is **not** wrapped in `_with_project` (it must tolerate a missing argument), so it resolves manually.
- **Rebuild notes:** One meta row. Better: print the previous active project so `use` is trivially reversible.

### `hermes project archive` — archive a project  `id: cli-c.project-archive`
- **Surface:** CLI
- **Where:** `hermes project archive <project>`. Help: `Archive a project`.
- **What it does:** Hides a project from the default listing without deleting it or its folders.
- **How it works:** `_cmd_archive` (`hermes_cli/projects_cmd.py:293`) → `pdb.archive_project(conn, proj.id)` (line 611): sets `projects.archived = 1`.
- **Inputs / options:** positional `project`; `-h/--help`.
- **Outputs / side effects:** `Archived <slug>` return 0. The project stops appearing in `hermes project list` unless `--all`, and stops blocking `create` duplicate-path detection (which only considers non-archived projects).
- **Config / env:** n/a
- **Edge cases / guards:** Unknown project → exit 1. Archiving does **not** clear the active-project pointer, so the active project can be an archived one.
- **Rebuild notes:** One boolean column. Better: clear (or warn about) the active pointer on archive.

### `hermes project restore` — restore an archived project  `id: cli-c.project-restore`
- **Surface:** CLI
- **Where:** `hermes project restore <project>`. Help: `Restore an archived project`.
- **What it does:** Un-archives a project so it shows in the default listing again.
- **How it works:** `_cmd_restore` (`hermes_cli/projects_cmd.py:300`) → `pdb.restore_project(conn, proj.id)` (line 619): sets `archived = 0`.
- **Inputs / options:** positional `project`; `-h/--help`.
- **Outputs / side effects:** `Restored <slug>` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown project → exit 1. Restoring a project whose primary path is now claimed by another project is allowed — the duplicate-path guard only runs on `create`.
- **Rebuild notes:** Inverse of archive. Better: warn on restore when the primary path now belongs to another project.

### `hermes project bind-board` — bind/unbind a kanban board  `id: cli-c.project-bind-board`
- **Surface:** CLI
- **Where:** `hermes project bind-board <project> [board]`. Help: `Bind a kanban board to a project`.
- **What it does:** Associates a kanban board slug with the project (omit the board to unbind) and, on bind, points that board's `default_workdir` at the project's primary repo so task worktrees land in the right place.
- **How it works:** `_cmd_bind_board` (`hermes_cli/projects_cmd.py:307`) → `pdb.update_project(conn, proj.id, board_slug=args.board)` (an empty string clears the column to NULL). On a non-empty board it then calls `_sync_board_default_workdir(proj, board)` (line 317): imports `hermes_cli.kanban_db`, normalises the slug with `kb._normalize_board_slug`, verifies it is `kb.DEFAULT_BOARD` or `kb.board_exists(slug)`, and calls `kb.write_board_metadata(slug, default_workdir=proj.primary_path)`.
- **Inputs / options:** positional `project`; positional optional `board` (`nargs="?"`, default `""`) — "Board slug (omit to unbind)"; `-h/--help`.
- **Outputs / side effects:** Bind: `Bound <slug> -> board <board>` and (best-effort) a `default_workdir` write on that board. Unbind: `Unbound board from <slug>`. Return 0.
- **Config / env:** Touches the kanban board metadata store (shared, root-anchored) as well as the per-profile projects DB.
- **Edge cases / guards:** An invalid board slug raises from `normalize_slug` → `project: <msg>` exit 2. The `default_workdir` sync is entirely best-effort inside a bare `except Exception: pass` — a failure is silent and the binding still succeeds. It is skipped when the project has no primary path, and when the board neither is the default nor exists.
- **Rebuild notes:** One column + one cross-store write. Better: report whether the workdir sync succeeded instead of swallowing the failure.

## 7. `hermes kanban` — durable multi-profile task board

### Kanban command group  `id: cli-c.kanban-group`
- **Surface:** CLI
- **Where:** `hermes kanban [--board <slug>] {init,boards,create,swarm,list,ls,show,assign,set-model,reclaim,reassign,diagnostics,diag,link,unlink,claim,comment,attach,attachments,attach-rm,complete,edit,block,schedule,unblock,request-review,request-changes,reopen-review,promote,archive,tail,dispatch,daemon,watch,stats,notify-subscribe,notify-list,notify-unsubscribe,log,runs,heartbeat,assignees,context,specify,decompose,gc,repair}`. Root help: `Multi-profile collaboration board (tasks, links, comments)`. Description: "Durable SQLite-backed task board shared across Hermes profiles. Tasks are claimed atomically, can depend on other tasks, and are executed by a named profile in an isolated workspace. See https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban or docs/hermes-kanban-v1-spec.pdf for the full design."
- **What it does:** The full command surface of the Hermes Kanban board: create tasks, link dependencies, assign them to named profiles, dispatch workers, watch events, review, complete and garbage-collect.
- **How it works:** Parser `build_parser` at `hermes_cli/kanban.py:216`; dispatch `kanban_command` at line 1063 with a 45-entry `handlers` dict (line 1146) plus `boards` and `repair` handled before it. Handler registered as `cmd_kanban` (`hermes_cli/main.py:5869`) → `hermes_cli.kanban.kanban_command`. All DB work is delegated to `hermes_cli/kanban_db.py` (12 150 lines). Status icons used across outputs (`_STATUS_ICONS`, `hermes_cli/kanban.py:35`): `todo ◻`, `ready ▶`, `running ●`, `scheduled ⏱`, `blocked ⊘`, `done ✓`, `archived —`; unknown status prints `?`. Timestamps render as `%Y-%m-%d %H:%M` in local time (`_fmt_ts`, line 46). A task list line is `<icon> <id>  <status:8>  <assignee:20><[tenant]>  <title>` (`_fmt_task_line`, line 52).
- **Inputs / options:** `-h/--help`; `--board <slug>`; one of the ~50 sub-command tokens.
- **Outputs / side effects:** With no action it prints the group help via the stored `_kanban_parser` default and returns **0**; the fallback (parser missing) prints to stderr `usage: hermes kanban <action> [options]` + `Run 'hermes kanban --help' for the full list of actions.` Unknown action → stderr `kanban: unknown action '<a>'` return 2. `ValueError`/`RuntimeError` from a handler → stderr `kanban: <exc>`.
- **Config / env:** `kanban.auto_subscribe_on_create` (true), `kanban.dispatch_in_gateway` (true), `kanban.review_dispatch` (true), `kanban.dispatch_interval_seconds` (60), `kanban.failure_limit` (2), `kanban.worker_log_rotate_bytes` (2097152), `kanban.worker_log_backup_count` (1), `kanban.orchestrator_profile` (""), `kanban.default_assignee` (""), `kanban.max_in_progress` (null), `kanban.max_in_progress_per_profile` (null), `kanban.auto_decompose` (true), `kanban.auto_decompose_per_tick` (3), `kanban.dispatch_stale_timeout_seconds` (14400), `kanban.reconcile_orphans` (true), `kanban.done_sub_retention_days` (30), plus the undeclared `kanban.max_spawn`. Env: `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_DB`, `HERMES_KANBAN_WORKSPACES_ROOT`, `HERMES_KANBAN_HOME`, `HERMES_KANBAN_TASK`, `HERMES_KANBAN_RUN_ID`, `HERMES_PROFILE`.
- **Edge cases / guards:** `kb.init_db()` runs automatically before **every** sub-command (idempotent — one `SELECT` against `sqlite_master` when the tables exist) so a fresh `HERMES_HOME` never errors with `no such table: tasks`; a failure prints `kanban: could not initialize database: <exc>` exit 1. `repair` is dispatched *before* the auto-init, because `init_db()` itself raises `KanbanDbCorruptError` on a corrupt DB and would make every repair attempt fail.
- **Rebuild notes:** One SQLite DB (WAL + `BEGIN IMMEDIATE` + CAS on `tasks.status`/`tasks.claim_lock`), a dispatcher loop, and a wide argparse surface. Better: a single typed RPC contract so CLI, gateway slash commands and dashboard share one implementation rather than three call sites.

### Kanban `--board <slug>` global flag  `id: cli-c.kanban-board-flag`
- **Surface:** CLI
- **Where:** `hermes kanban --board <slug> <action> …` — a flag on the **group** parser, so it precedes the sub-command. Help: "Board slug to operate on. Defaults to the current board (set via `hermes kanban boards switch <slug>` or the HERMES_KANBAN_BOARD env var). Use `hermes kanban boards list` to see all boards."
- **What it does:** Scopes all reads and writes of that one invocation to a specific board's isolated database.
- **How it works:** `kanban_command` (`hermes_cli/kanban.py:1104-1122`) normalises the slug with `kb._normalize_board_slug`, checks existence, then enters `kb.scoped_current_board(normed)` — implemented as an **env-var pin** on `HERMES_KANBAN_BOARD` for the duration of the call rather than threading a `board=` kwarg through 50+ `kb.connect()` sites, so workers inherit exactly the same resolution the dispatcher uses. Board resolution order (`hermes_cli/kanban_db.py:26-38`): explicit `board=` argument → `HERMES_KANBAN_BOARD` env → `HERMES_KANBAN_DB` env (pins the file path directly) → `<root>/kanban/current` text file → `default`.
- **Inputs / options:** `--board <slug>` (default None, metavar `<slug>`).
- **Outputs / side effects:** None by itself.
- **Config / env:** `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_DB`.
- **Edge cases / guards:** An invalid slug → stderr `kanban: <exc>` exit 2; empty → `kanban: --board requires a slug` exit 2; a non-existent, non-default board → `kanban: board '<slug>' does not exist. Create it with \`hermes kanban boards create <slug>\`.` exit 1 (typoed slugs must not silently create empty boards). **`boards` sub-commands deliberately ignore `--board`**, because they operate on the on-disk board metadata and the current-board pointer itself — otherwise `--board beta boards show` would report beta while the on-disk pointer said alpha.
- **Rebuild notes:** One contextvar/env scope around the whole call. Better: make it a real parameter so nested library calls cannot escape the scope.

### Kanban storage layout & board isolation  `id: cli-c.kanban-store`
- **Surface:** Core
- **Where:** `<root>/kanban.db`, `<root>/kanban/workspaces/`, `<root>/kanban/logs/`, `<root>/kanban/boards/<slug>/`, `<root>/kanban/current`, `<root>/kanban/boards/_archived/`.
- **What it does:** Holds every board's tasks, comments, links, events, runs and attachments, deliberately at the **shared Hermes root** (the parent of any profile) so profiles collapse onto one board — the board *is* the cross-profile coordination primitive.
- **How it works:** `hermes_cli/kanban_db.py` module docstring (lines 1-70). The `default` board keeps its DB at `<root>/kanban.db` (not `boards/default/kanban.db`) for zero-migration back-compat; every other board is a directory `<root>/kanban/boards/<slug>/` with its own `kanban.db`, `workspaces/` and `logs/`. `<root>` is `~/.hermes` normally, or `HERMES_HOME` in Docker/custom deployments. Concurrency: WAL mode + `BEGIN IMMEDIATE` write transactions + compare-and-swap on `tasks.status` and `tasks.claim_lock`; SQLite serialises writers via the WAL lock so at most one claimer wins a task and losers simply observe zero affected rows (no retry loops, no distributed locks). CAS coordination is **per-board**. Core tables: `tasks`, `task_links`, `task_comments`, `task_events`, plus `task_runs`, attachments and notify-subscription tables. The dispatcher injects `HERMES_KANBAN_DB`, `HERMES_KANBAN_WORKSPACES_ROOT` and `HERMES_KANBAN_BOARD` into worker subprocess env (`hermes_cli/kanban_db.py:10837`) so workers converge on the exact DB even under symlink/Docker layouts.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** `HERMES_KANBAN_DB` (pin the DB file path), `HERMES_KANBAN_WORKSPACES_ROOT` (pin the workspaces root), `HERMES_KANBAN_HOME` (pin the umbrella root — useful for tests and unusual deployments), `HERMES_KANBAN_BOARD`.
- **Edge cases / guards:** Workers spawned for a task on board `atm10-server` see only that board's tasks and cannot enumerate other boards. `workspace_kind` decouples coordination from git worktrees so research/ops/digital-twin workloads coexist with coding ones.
- **Rebuild notes:** Directory-per-board + one SQLite DB each + a one-line `current` pointer file. Better: a board registry table instead of directory scanning, so listing does not need filesystem walks.

### Kanban task status lifecycle  `id: cli-c.kanban-statuses`
- **Surface:** Core / CLI
- **Where:** `--status` on `hermes kanban list`, `--initial-status` on `create`, the `status:` line of `show`, and the status column everywhere.
- **What it does:** Defines the nine states a task can occupy and which transitions each command performs.
- **How it works:** `VALID_STATUSES = {"triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"}` (`hermes_cli/kanban_db.py:102`). `VALID_INITIAL_STATUSES = {"running", "blocked"}` (line 103) — only these two may be requested at create time. `VALID_BLOCK_KINDS = {"dependency", "needs_input", "capability", "transient"}` (line 125) route a block to different destinations: `dependency` waits in **todo** (auto-promoted when parents finish, no human); `needs_input`/`capability` go to **blocked** for a human; `transient` marks a maybe-flaky failure. A repeated same-kind re-block after an unblock routes the task to **triage** to break unblock loops.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** `review` is explicitly **not** a block. `archived` tasks are excluded from listings unless `--archived`/`--all`.
- **Rebuild notes:** Nine states, typed block reasons, and an anti-loop rule. Better: publish the transition table as data so the UI and CLI cannot drift.

### Kanban `--workspace` kinds  `id: cli-c.kanban-workspace-flag`
- **Surface:** CLI
- **Where:** `hermes kanban create --workspace <value>`; displayed by `show` as `  workspace: <kind> @ <path>`.
- **What it does:** Chooses where a task's worker runs: a throwaway scratch dir, a git worktree, or an existing directory.
- **How it works:** `_parse_workspace_flag` (`hermes_cli/kanban.py:97`) accepts exactly four shapes: `scratch` (default), `worktree`, `worktree:<path>`, `dir:<path>`. Prefixed forms expand `~` via `os.path.expanduser`. The resolved kind/path are stored on the task; `kb.resolve_workspace(task)` materialises the actual path at claim time.
- **Inputs / options:** `--workspace WORKSPACE` (default `scratch`) — help: "scratch | worktree | worktree:<path> | dir:<path> (default: scratch)". Paired flag: `--branch BRANCH` — "Branch name for worktree tasks, e.g. wt/t6-wire".
- **Outputs / side effects:** A directory under `<root>/kanban/workspaces/<task-id>` for scratch tasks; a git worktree for worktree tasks.
- **Config / env:** `HERMES_KANBAN_WORKSPACES_ROOT`; a board's `default_workdir` (see `boards set-default-workdir`).
- **Edge cases / guards:** `dir:` / `worktree:` with nothing after the colon → `--workspace <prefix> requires a path after the colon` (exit 2). Anything else → `unknown --workspace value '<v>': use scratch, worktree, worktree:<path>, or dir:<path>` (exit 2). `--branch` without `--workspace worktree` → `kanban: --branch is only valid with --workspace worktree` exit 2. `_parse_branch_flag` (line 122) additionally rejects an empty branch (`--branch requires a non-empty name`), one starting with `-` (`--branch must not start with '-'`) and one containing whitespace (`--branch must not contain whitespace`).
- **Rebuild notes:** A tiny prefix parser + a resolve-at-claim step. Better: validate the target directory exists (for `dir:`) at create time rather than at dispatch.

### Kanban duration parsing (`--max-runtime`)  `id: cli-c.kanban-duration`
- **Surface:** CLI
- **Where:** `hermes kanban create --max-runtime <value>`.
- **What it does:** Sets a per-task wall-clock cap after which the dispatcher kills the worker and re-queues the task.
- **How it works:** `_parse_duration` (`hermes_cli/kanban.py:1549`): a bare integer is seconds; a suffixed form uses `{"s":1,"m":60,"h":3600,"d":86400}` and accepts a float mantissa (`1.5h`). Empty/None → `None`. Enforcement is in the dispatcher, which **SIGTERMs then SIGKILLs** the worker and re-queues (help text of `--max-runtime`).
- **Inputs / options:** `--max-runtime MAX_RUNTIME` — "Per-task runtime cap. Accepts seconds (300) or durations (90s, 30m, 2h, 1d)."
- **Outputs / side effects:** `tasks.max_runtime_seconds`.
- **Config / env:** n/a
- **Edge cases / guards:** Malformed input raises `malformed duration '<v>'` or `malformed duration '<v>' (expected 30s, 5m, 2h, 1d, or a number)` → printed as `kanban: --max-runtime: <msg>` exit 2. There is no upper bound and no minimum.
- **Rebuild notes:** Regex-free suffix table. Better: reject absurd values (0 s, 30 d) with a warning.

### Delegated-child mutation guard  `id: cli-c.kanban-delegate-guard`
- **Surface:** CLI / Core
- **Where:** Any mutating `hermes kanban …` invocation made from inside a `delegate_task` child context.
- **What it does:** Stops a delegated sub-agent from mutating the board through the CLI.
- **How it works:** `_is_delegated_child_cli_mutation(args)` is checked at the very top of `kanban_command` (`hermes_cli/kanban.py:1082`). The source is explicit that this is a **fast-fail for clearer CLI UX only** — "the durable trust boundary is lower in `hermes_cli.kanban_db`, because children can import DB mutators directly."
- **Inputs / options:** n/a
- **Outputs / side effects:** stderr `kanban: delegate_task child contexts cannot mutate Kanban tasks via the CLI`, exit 1.
- **Config / env:** Detected from the delegated-child environment markers.
- **Edge cases / guards:** Read-only actions are unaffected.
- **Rebuild notes:** Two-layer guard (UX layer + DB layer). Better: one enforcement point at the DB layer with a typed capability token.

### `hermes kanban init` — create the board DB  `id: cli-c.kanban-init`
- **Surface:** CLI
- **Where:** `hermes kanban init`. Help: `Create kanban.db if missing (idempotent)`.
- **What it does:** Creates the board database if absent, lists the profiles on disk that can be used as assignees, and tells the user to start the gateway.
- **How it works:** `_cmd_init` (`hermes_cli/kanban.py:1574`) calls `kb.init_db()` then `kb.list_profiles_on_disk()`. Profile enumeration happens here rather than at dispatcher start because the dispatcher just passes the name through to `hermes -p <name>`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Creates the DB file. Prints `Kanban DB initialized at <path>`, blank line, then either `Discovered <n> profile(s) on disk; any of these can be an --assignee:` followed by two-space-indented names, or `No profiles found under ~/.hermes/profiles/.` + `Create one with \`hermes -p <name> setup\` before assigning tasks.` Then blank, `Next step: start the gateway so ready tasks actually get picked up.`, `  hermes gateway start`, blank, and `The gateway hosts an embedded dispatcher that ticks every 60 seconds\nby default (config: kanban.dispatch_interval_seconds). Without a\nrunning gateway, tasks stay in 'ready' forever.` Return 0.
- **Config / env:** `kanban.dispatch_interval_seconds`.
- **Edge cases / guards:** Idempotent — safe to run repeatedly. Every other sub-command auto-inits anyway, so this command is mostly informational.
- **Rebuild notes:** `CREATE TABLE IF NOT EXISTS` + a profile scan. Better: also verify the gateway is running and say so.

### `hermes kanban boards` — board management sub-group  `id: cli-c.kanban-boards-group`
- **Surface:** CLI
- **Where:** `hermes kanban boards {list,ls,create,new,rm,remove,delete,switch,use,show,current,rename,set-default-workdir,export,import}`. Help: `Manage kanban boards (one board per project / workstream)`. Description: "Boards let you separate unrelated streams of work (projects, repos, domains) into isolated queues. Each board has its own DB, workspaces directory, and dispatcher loop — tasks on one board cannot collide with tasks on another. The first board is 'default' and always exists."
- **What it does:** Creates, lists, switches between, renames, archives, exports and imports boards.
- **How it works:** Sub-parser at `hermes_cli/kanban.py:254`; dispatch `_dispatch_boards` at line 1285, called **before** the `--board` scoping and before auto-init, because board management operates on the filesystem (board directories, the `current` pointer, `board.json`), not on a per-board SQLite DB — so a fresh `HERMES_HOME` that has never run `kanban init` can still run `boards create` / `boards list`. The default action when none is given is `list` (`sub = getattr(args, "boards_action", None) or "list"`).
- **Inputs / options:** `-h/--help`; one of the 15 sub-command tokens (9 distinct actions plus aliases).
- **Outputs / side effects:** Unknown action → stderr `kanban boards: unknown action '<sub>'` return 2.
- **Config / env:** `HERMES_KANBAN_HOME`.
- **Edge cases / guards:** Ignores the group's `--board` flag entirely (see `cli-c.kanban-board-flag`).
- **Rebuild notes:** Filesystem-first board registry with a `board.json` per directory. Better: guard against two processes switching the `current` pointer concurrently.

### `hermes kanban boards list` (alias `ls`) — list boards  `id: cli-c.kanban-boards-list`
- **Surface:** CLI
- **Where:** `hermes kanban boards list [--json] [--all]`, alias `ls`; also the default when `hermes kanban boards` is run bare. Help: `List all boards with task counts`.
- **What it does:** Lists every board with its display name, per-status task counts and a marker on the current one.
- **How it works:** `_cmd_boards_list` (`hermes_cli/kanban.py:1332`): `kb.list_boards(include_archived=…)`, then per board `_board_task_counts(slug)` (line 1317 — `SELECT status, COUNT(*) FROM tasks GROUP BY status`, returning `{}` for a missing DB or any error) and `is_current` against `kb.get_current_board()`.
- **Inputs / options:** `--json` (store_true, no help text); `--all` (store_true) — "Include archived boards too"; `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: the enriched board list, indent 2. Empty: `(no boards — create one with \`hermes kanban boards create <slug>\`)`. Human table header: `      SLUG                      NAME                          COUNTS` (formatted as `{'':2s}  {'SLUG':24s}  {'NAME':28s}  COUNTS`); rows `<marker:2> <slug:24>  <name:28>  <counts>` where marker is `●` for the current board and a space otherwise, name gains ` [archived]` when archived, and counts is `status=n, status=n` sorted or `(empty)`. Then a blank line, `Current board: <slug>` and, when more than one board exists, `Switch boards with \`hermes kanban boards switch <slug>\`.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Count probing swallows every exception, so a corrupt board DB shows as `(empty)` rather than failing the listing.
- **Rebuild notes:** Directory scan + per-board count query. Better: surface the count-probe failure instead of hiding it as `(empty)`.

### `hermes kanban boards create` (alias `new`) — create a board  `id: cli-c.kanban-boards-create`
- **Surface:** CLI
- **Where:** `hermes kanban boards create <slug> [--name NAME] [--description DESCRIPTION] [--icon ICON] [--color COLOR] [--switch] [--default-workdir DEFAULT_WORKDIR]`, alias `new`. Help: `Create a new board`.
- **What it does:** Creates an isolated board directory with its own DB, workspaces and logs, plus dashboard metadata (name, description, icon, colour) and an optional default workdir.
- **How it works:** `_cmd_boards_create` (`hermes_cli/kanban.py:1367`): normalise slug → `kb.board_exists()` pre-check → `kb.create_board(normed, name=…, description=…, icon=…, color=…, default_workdir=…)`.
- **Inputs / options:** positional `slug` — "Board slug (kebab-case, e.g. atm10-server)"; `--name NAME` (default None) — "Human-readable display name (defaults to Title Case of slug)"; `--description DESCRIPTION` (default None) — "Optional description"; `--icon ICON` (default None) — "Optional emoji or single-character icon for the dashboard"; `--color COLOR` (default None) — "Optional hex color (e.g. '#8b5cf6') for the dashboard"; `--switch` (store_true) — "Switch to the new board after creating it"; `--default-workdir DEFAULT_WORKDIR` (default None) — "Default workspace path for tasks created on this board"; `-h/--help`.
- **Outputs / side effects:** Creates `<root>/kanban/boards/<slug>/` with `board.json`. Prints `Board '<slug>' created.` — or `Board '<slug>' already exists.` when the directory was already there and the slug is not `default` — then `  Display name: <name>`, `  DB path:      <path>`, and either `  Switched to '<slug>'.` (with `--switch`) or `  Use \`hermes kanban boards switch <slug>\` to make it current.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Invalid slug → stderr `kanban boards create: <exc>` exit 2; empty slug → `kanban boards create: slug is required` exit 2. Creating an existing board is **idempotent** (metadata is re-written, tasks untouched). The `already exists` detection deliberately excludes `default`, which always exists.
- **Rebuild notes:** mkdir + `board.json` + optional pointer switch. Better: refuse to silently overwrite metadata of an existing board without `--force`.

### `hermes kanban boards rm` (aliases `remove`, `delete`) — archive/delete a board  `id: cli-c.kanban-boards-rm`
- **Surface:** CLI
- **Where:** `hermes kanban boards rm <slug> [--delete]`, aliases `remove`, `delete`. Help: `Archive (default) or delete a board`.
- **What it does:** Moves a board directory to `boards/_archived/` (recoverable) or, with `--delete`, hard-deletes it.
- **How it works:** `_cmd_boards_rm` (`hermes_cli/kanban.py:1397`) → `kb.remove_board(slug, archive=not force_delete)`. `force_delete` is `args.delete` **or** the fact that the user typed the `delete` alias — because `--delete` belongs only to the `rm` subparser, the alias would otherwise archive instead of delete (the fix references issue #23139).
- **Inputs / options:** positional `slug`; `--delete` (store_true) — "Hard-delete the board directory instead of archiving it. Default is to move it to boards/_archived/ so it's recoverable."; `-h/--help`.
- **Outputs / side effects:** Archive: `Board '<slug>' archived → <new_path>` + `Recover by moving the directory back to <root>/kanban/boards/<slug>/.` Delete: `Board '<slug>' deleted.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Removal is **refused for the `default` board**; that and an unknown slug raise `ValueError` → stderr `kanban boards rm: <exc>` exit 1. Archived boards land in `<root>/kanban/boards/_archived/<slug>-<ts>/`. No confirmation prompt for `--delete`.
- **Rebuild notes:** `shutil.move` vs `rmtree` behind one flag, with alias detection. Better: require `--yes` for the hard delete.

### `hermes kanban boards switch` (alias `use`) — set the active board  `id: cli-c.kanban-boards-switch`
- **Surface:** CLI
- **Where:** `hermes kanban boards switch <slug>`, alias `use`. Help: `Set the active board for subsequent CLI calls`.
- **What it does:** Writes the persistent current-board pointer so later commands default to that board.
- **How it works:** `_cmd_boards_switch` (`hermes_cli/kanban.py:1417`) → `kb.set_current_board(normed)`, which writes the slug to the one-line file `<root>/kanban/current`.
- **Inputs / options:** positional `slug`; `-h/--help`.
- **Outputs / side effects:** Writes `<root>/kanban/current`. Prints `Active board is now '<slug>'.` Return 0.
- **Config / env:** Overridden at runtime by `HERMES_KANBAN_BOARD` and by `--board`.
- **Edge cases / guards:** Invalid slug → stderr `kanban boards switch: <exc>` exit 2; empty → `kanban boards switch: slug is required` exit 2; non-existent → `kanban boards switch: board '<slug>' does not exist. Create it with \`hermes kanban boards create <slug>\`.` exit 1.
- **Rebuild notes:** One text file. Better: make it per-shell (env) by default with an explicit `--global` for the file.

### `hermes kanban boards show` (alias `current`) — print the active board  `id: cli-c.kanban-boards-show`
- **Surface:** CLI
- **Where:** `hermes kanban boards show`, alias `current`. Help: `Print the currently-active board slug`.
- **What it does:** Prints the active board's slug, display name, description, DB path and task counts.
- **How it works:** `_cmd_boards_show` (`hermes_cli/kanban.py:1438`): `kb.get_current_board()` + `kb.read_board_metadata(current)` + `_board_task_counts(current)`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Read-only. `Current board: <slug>`, `  Display name: <name>`, `  Description:  <desc>` (only when set), `  DB path:      <path>`, `  Tasks:        <total> total (status=n, status=n)` — the parenthesised part is omitted when there are no counts. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Deliberately ignores `--board`, so it always reports the persisted pointer.
- **Rebuild notes:** Read pointer + metadata + counts. Better: add `--json`.

### `hermes kanban boards rename` — rename a board's display name  `id: cli-c.kanban-boards-rename`
- **Surface:** CLI
- **Where:** `hermes kanban boards rename <slug> <name>`. Help: `Change a board's human-readable display name (slug is immutable)`.
- **What it does:** Changes only the display name in `board.json`; the slug (and therefore all paths) never changes.
- **How it works:** `_cmd_boards_rename` (`hermes_cli/kanban.py:1454`) → `kb.write_board_metadata(normed, name=args.name)`.
- **Inputs / options:** positional `slug`; positional `name` — "New display name"; `-h/--help`.
- **Outputs / side effects:** Rewrites `board.json`. Prints `Board '<slug>' renamed to '<name>'.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Invalid slug → stderr `kanban boards rename: <exc>` exit 2; non-existent → `kanban boards rename: board '<slug>' does not exist` exit 1.
- **Rebuild notes:** One metadata field. Better: allow renaming the slug via export/import in one step.

### `hermes kanban boards set-default-workdir` — set/clear a board's default workspace  `id: cli-c.kanban-boards-set-default-workdir`
- **Surface:** CLI
- **Where:** `hermes kanban boards set-default-workdir <slug> [path]`. Help: `Set the default workspace path for tasks on a board`.
- **What it does:** Sets (or clears) the directory new tasks on that board default to as their workspace.
- **How it works:** `_cmd_boards_set_default_workdir` (`hermes_cli/kanban.py:1469`) → `kb.write_board_metadata(normed, default_workdir=args.path)`. `hermes project bind-board` calls the same function to point a bound board at the project's primary repo.
- **Inputs / options:** positional `slug`; positional optional `path` (`nargs="?"`, default None) — "Absolute path to use as default workdir. Omit to clear."; `-h/--help`.
- **Outputs / side effects:** Rewrites `board.json`. Prints `Board '<slug>' default workdir set to '<path>'.` or `Board '<slug>' default workdir cleared.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Invalid slug → `kanban boards set-default-workdir: <exc>` exit 2; non-existent → `kanban boards set-default-workdir: board '<slug>' does not exist` exit 1. The path is not checked for existence.
- **Rebuild notes:** One metadata field consumed at task-create time. Better: validate the path and warn if it is not a git repo when worktree tasks are expected.

### `hermes kanban boards export` — export a board to an archive  `id: cli-c.kanban-boards-export`
- **Surface:** CLI
- **Where:** `hermes kanban boards export [slug] [-o OUTPUT | --output OUTPUT] [--no-attachments] [--include-logs] [--json]`. Help: `Export a board to a portable .tar.gz archive`. Description: "Package a board's tasks, comments, links, history, and file attachments into one archive that can be imported on another machine. Claims, worker PIDs, chat subscriptions, and paths belonging to this machine are stripped. Workspaces are never included — they are rebuilt on demand."
- **What it does:** Produces a portable `.tar.gz` of one board's data, machine-specific state removed.
- **How it works:** `_cmd_boards_export` (`hermes_cli/kanban.py:1488`) → `hermes_cli.kanban_transfer.export_board(slug, output, include_attachments=not args.no_attachments, include_logs=args.include_logs)`. Sizes are rendered by `hermes_cli.sizefmt.format_bytes`.
- **Inputs / options:** positional optional `slug` (`nargs="?"`, default None) — "Board to export (default: the current board)"; `-o OUTPUT` / `--output OUTPUT` (default None) — "Archive path (default: ./<slug>.tar.gz)"; `--no-attachments` (store_true) — "Skip attachment files, keeping the archive small"; `--include-logs` (store_true) — "Include per-task worker logs"; `--json` (store_true); `-h/--help`.
- **Outputs / side effects:** Writes the archive to disk. JSON: the full result dict. Human: `Exported board '<board>' → <archive>`, `  Size:        <formatted bytes>`, `  Tasks:       <n>`, `  Comments:    <n>`, `  Attachments: <n>`, `Import it with \`hermes kanban boards import <archive>\`.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** `OSError`/`ValueError` → stderr `kanban boards export: <exc>` exit 1. Claims, worker PIDs, chat subscriptions and machine-local paths are stripped; workspaces are **never** included.
- **Rebuild notes:** tar.gz of the board dir with a sanitising pass over the DB. Better: sign or checksum the archive so an import can verify integrity.

### `hermes kanban boards import` — import a board archive  `id: cli-c.kanban-boards-import`
- **Surface:** CLI
- **Where:** `hermes kanban boards import <archive> [--as AS_SLUG] [--switch] [--json]`. Help: `Import a board archive as a new board`. Description: "Import a .tar.gz produced by `hermes kanban boards export`. The board always lands as a NEW board — the slug gains a numeric suffix if it is already taken — so an import can never overwrite or merge into a board you already have."
- **What it does:** Restores an exported board as a brand-new board on this machine.
- **How it works:** `_cmd_boards_import` (`hermes_cli/kanban.py:1518`) → `kanban_transfer.import_board(args.archive, args.as_slug, activate=args.switch)`.
- **Inputs / options:** positional `archive` — "Path to the .tar.gz archive"; `--as AS_SLUG` (dest `as_slug`, default None) — "Slug for the imported board (default: from the archive)"; `--switch` (store_true) — "Switch to the imported board afterwards"; `--json` (store_true); `-h/--help`.
- **Outputs / side effects:** Creates a new board directory. JSON: the full result. Human: `Imported board '<board>' (<name>).`, then `  Renamed from '<requested_board>' — that slug was taken.` when the slug collided, `  Path:  <path>`, `  Tasks: <n>`, one `  Note:  <warning>` line per warning, and either `  Active board is now '<board>'.` or `  Switch to it with \`hermes kanban boards switch <board>\`.` Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** `OSError`/`ValueError` → stderr `kanban boards import: <exc>` exit 1. An import can **never** overwrite or merge into an existing board — collisions always get a numeric suffix.
- **Rebuild notes:** Untar into a fresh slug, rewrite machine-local fields, report warnings. Better: a `--dry-run` that reports what would be imported and any warnings first.

### `hermes kanban create` — create a task  `id: cli-c.kanban-create`
- **Surface:** CLI
- **Where:** `hermes kanban create <title> [22 options]`. Help: `Create a new task`.
- **What it does:** Creates a board task with a title, optional body, assignee, dependencies, workspace kind, project binding, priority, runtime cap, skills, model/provider pins, goal-loop mode and initial status — and warns when nothing is running to dispatch it.
- **How it works:** `_cmd_create` (`hermes_cli/kanban.py:1642`): parses `--workspace`/`--branch`/`--max-runtime`, validates `--max-retries >= 1`, then `kb.create_task(conn, title=…, body=…, assignee=…, created_by=…, workspace_kind=…, workspace_path=…, branch_name=…, project_id=…, tenant=…, priority=…, parents=…, triage=…, idempotency_key=…, max_runtime_seconds=…, skills=…, max_retries=…, model_override=…, provider_override=…, goal_mode=…, goal_max_turns=…, initial_status=…)`. `created_by` falls back to `_profile_author()` (`$HERMES_PROFILE` or `user`).
- **Inputs / options:** positional `title` — "Task title"; `--body BODY` (None) — "Optional opening post"; `--assignee ASSIGNEE` (None) — "Profile name to assign"; `--parent PARENT` (append, default `[]`) — "Parent task id (repeatable)"; `--workspace WORKSPACE` (default `scratch`); `--branch BRANCH` (None); `--project PROJECT` (None) — "Link to a project (id or slug). Anchors the task's worktree under the project's primary repo with a deterministic branch. See `hermes project list`."; `--tenant TENANT` (None) — "Tenant namespace"; `--priority PRIORITY` (int, default 0) — "Priority tiebreaker"; `--triage` (store_true) — "Park in triage — a specifier will flesh out the spec and promote to todo"; `--idempotency-key IDEMPOTENCY_KEY` (None) — "Dedup key. If a non-archived task with this key exists, its id is returned instead of creating a duplicate."; `--max-runtime MAX_RUNTIME` (None); `--created-by CREATED_BY` (default `user`) — "Author name recorded on the task (default: user)"; `--skill SKILLS` (append, dest `skills`, default `[]`) — "Skill to force-load into the worker (repeatable). The kanban lifecycle is already injected automatically. Example: --skill translation --skill github-code-review"; `--max-retries N` (int, None, metavar `N`) — per-task circuit-breaker override, "Trip on the Nth failure — e.g. --max-retries 1 blocks on the first failure (no retries), --max-retries 3 allows two retries. Omit to use the dispatcher's kanban.failure_limit config (default 2)."; `--model MODEL_OVERRIDE` (dest `model_override`, None) — "Pin the worker to this model (passed as -m <model>) without changing the profile's configured model."; `--provider PROVIDER_OVERRIDE` (dest `provider_override`, None) — "Provider the --model belongs to (passed as --provider <name> to the worker). Requires --model."; `--goal` (store_true, dest `goal_mode`) — "Run the worker in a goal loop: after each turn a judge checks the response against the card title/body and, if not done, the worker keeps going in the same session until the judge agrees it's complete (or the turn budget runs out, which blocks the card for review)."; `--goal-max-turns N` (int, None, dest `goal_max_turns`) — "Turn budget for --goal workers (default 20). Ignored without --goal."; `--initial-status {blocked,running}` (default `running`) — "Initial card status. Use 'blocked' for cards that require immediate human ops (R3 gate) to skip the brief running-to-blocked transition."; `--json` (store_true) — "Emit JSON output"; `-h/--help`.
- **Outputs / side effects:** Inserts a `tasks` row (+ link rows per `--parent`). JSON mode: `_task_to_dict(task)` — keys `id, title, body, assignee, status, priority, tenant, workspace_kind, workspace_path, branch_name, project_id, created_by, created_at, started_at, completed_at, result, skills, max_retries, model_override, provider_override, session_id, workflow_template_id, current_step_key`. Human mode: `Created <task_id>  (<status>, assignee=<assignee or ->)`, plus — only when the task landed `ready` **and** has an assignee **and** no dispatcher is present — a stderr line `\n⚠  <message>`.
- **Config / env:** `kanban.failure_limit`, `kanban.dispatch_in_gateway`; `HERMES_PROFILE`.
- **Edge cases / guards:** `--branch` without worktree → exit 2. Bad `--workspace`/`--branch`/`--max-runtime` → exit 2 with `kanban: <msg>`. `--max-retries < 1` → `kanban: --max-retries must be >= 1 (got <n>); use 1 to trip on the first failure.` exit 2. The dispatcher-presence warning is **skipped in `--json` mode** so stdout stays machine-parseable, and it is skipped for triage/todo (expected to sit) and unassigned tasks (cannot be dispatched). The probe (`_check_dispatcher_presence`, line 136) fails **open** — an unreadable probe returns `(True, "")` so it never cries wolf.
- **Rebuild notes:** One INSERT plus link rows, with option parsing up front and a presence probe at the end. Better: validate `--provider` requires `--model` in argparse (today it is only documented).

### Dispatcher-presence warning  `id: cli-c.kanban-dispatcher-warning`
- **Surface:** CLI
- **Where:** printed by `hermes kanban create` (and shared callers) when a ready+assigned task has nothing to pick it up.
- **What it does:** Tells the user their task will sit in `ready` and exactly what to do about it.
- **How it works:** `_check_dispatcher_presence(hermes_home=None)` (`hermes_cli/kanban.py:136`) uses `gateway.status.resolve_gateway_liveness(profile_dir=…, use_cache=False)` — the same ladder the dashboard status endpoints use, so a PID-file-less (launch-service-managed) or cross-container gateway is not misreported as absent — then checks `kanban.dispatch_in_gateway`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Two possible messages. Gateway up but dispatch off: "Gateway is running but kanban.dispatch_in_gateway=false in config.yaml — the task will sit in 'ready' until you flip it back on and restart the gateway, OR run the legacy standalone daemon (`hermes kanban daemon --force`)." No gateway: "No gateway is running — the task will sit in 'ready' until you start it. Run:\n    hermes gateway start\nThe gateway hosts an embedded dispatcher (tick interval 60s by default); your task will be picked up on the next tick after the gateway comes up."
- **Config / env:** `kanban.dispatch_in_gateway`.
- **Edge cases / guards:** Import failure, probe exception, or `liveness.probe_error` all return `(True, "")` — silent — because "can't tell" must not read as "no gateway".
- **Rebuild notes:** Liveness ladder + a config check + fail-open. Better: also detect a gateway whose dispatcher thread has died (the cron-status equivalent).

### `hermes kanban swarm` — create a Swarm v1 graph  `id: cli-c.kanban-swarm`
- **Surface:** CLI
- **Where:** `hermes kanban swarm <goal> [--worker PROFILE:TITLE[:SKILL,SKILL]]… --verifier VERIFIER --synthesizer SYNTHESIZER [--tenant TENANT] [--priority PRIORITY] [--created-by CREATED_BY] [--idempotency-key IDEMPOTENCY_KEY] [--json]`. Help: `Create a Kanban Swarm v1 graph (parallel workers → verifier → synthesizer)`.
- **What it does:** Creates a whole dependency graph in one command: a root goal card, N parallel worker cards, a verifier card that depends on them, and a synthesizer card that depends on the verifier.
- **How it works:** `_cmd_swarm` (`hermes_cli/kanban.py:1710`): each `--worker` string is parsed by `hermes_cli.kanban_swarm.parse_worker_arg(raw)` into profile/title/skills, then `ks.create_swarm(conn, goal=…, workers=…, verifier_assignee=…, synthesizer_assignee=…, tenant=…, created_by=…, priority=…, idempotency_key=…)` builds the cards and links.
- **Inputs / options:** positional `goal` — "Swarm goal / final outcome"; `--worker PROFILE:TITLE[:SKILL,SKILL]` (append, default `[]`) — "Parallel worker card (repeatable)"; `--verifier VERIFIER` (**required**) — "Verifier profile"; `--synthesizer SYNTHESIZER` (**required**) — "Synthesizer/writer profile"; `--tenant TENANT` (None); `--priority PRIORITY` (int, 0); `--created-by CREATED_BY` (None) — "Creator/anchor profile"; `--idempotency-key IDEMPOTENCY_KEY` (None) — "Dedup key for the root card"; `--json` (store_true); `-h/--help`.
- **Outputs / side effects:** Creates 3+N tasks and their links. JSON: `created.as_dict()`. Human: `Swarm root: <root_id>`, `Workers: <id, id, …>`, `Verifier: <id>`, `Synthesizer: <id>`. Return 0.
- **Config / env:** `HERMES_PROFILE` (for the `created_by` fallback).
- **Edge cases / guards:** A malformed `--worker` string → stderr `kanban swarm: <exc>` exit 2. Zero workers → `kanban swarm: at least one --worker is required` exit 2. `--verifier` and `--synthesizer` are required by argparse itself.
- **Rebuild notes:** Fan-out/fan-in graph builder with a `profile:title:skills` mini-DSL. Better: allow a YAML/JSON graph file for larger swarms than a command line can hold.

### `hermes kanban list` (alias `ls`) — list tasks  `id: cli-c.kanban-list`
- **Surface:** CLI
- **Where:** `hermes kanban list [--mine] [--assignee ASSIGNEE] [--status …] [--tenant TENANT] [--session SESSION] [--archived] [--json] [--sort …] [--workflow-template-id ID] [--step-key KEY]`, alias `ls`. Help: `List tasks`.
- **What it does:** Lists tasks with filters and sort orders, first recomputing which tasks are ready.
- **How it works:** `_cmd_list` (`hermes_cli/kanban.py:1741`): `--mine` resolves to `_profile_author()` when `--assignee` is absent; then a "cheap mini-dispatch" `kb.recompute_ready(conn)` so the output reflects dependencies that cleared since the last dispatcher tick; then `kb.list_tasks(...)`.
- **Inputs / options:** `--mine` (store_true) — "Filter by $HERMES_PROFILE as assignee"; `--assignee ASSIGNEE` (None, no help text); `--status {archived,blocked,done,ready,review,running,scheduled,todo,triage}` (None, choices = `sorted(kb.VALID_STATUSES)`); `--tenant TENANT` (None, no help text); `--session SESSION` (None) — "Filter by originating chat/agent session id (set on tasks created from inside an ACP loop)"; `--archived` (store_true) — "Include archived tasks"; `--json` (store_true, no help text); `--sort {assignee,created,created-desc,priority,priority-desc,status,title,updated}` (None) — "Sort order for listed tasks (default: priority)"; `--workflow-template-id ID` (None, metavar `ID`) — "Restrict to tasks with this workflow_template_id"; `--step-key KEY` (None, dest `current_step_key`, metavar `KEY`) — "Restrict to tasks with this current_step_key"; `-h/--help`. Sort orders map to SQL (`VALID_SORT_ORDERS`, `hermes_cli/kanban_db.py:3649`): `created` → `created_at ASC, id ASC`; `created-desc` → `created_at DESC, id DESC`; `priority` → `priority DESC, created_at ASC`; `priority-desc` → `priority ASC, created_at ASC`; `status` → `status ASC, created_at ASC`; `assignee` → `assignee ASC, created_at ASC`; `title` → `title ASC, id ASC`; `updated` → `started_at DESC NULLS LAST, created_at DESC`.
- **Outputs / side effects:** Mutates readiness (`recompute_ready`) — this command is **not** purely read-only. JSON: a list of `_task_to_dict`. Human: when more than one non-archived board exists, a header `Board: <current> (<n> other board(s) — \`hermes kanban boards list\`)` and a blank line — single-board users never see it. Then `(no matching tasks)` or one `_fmt_task_line` per task. Return 0.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** An invalid `--status` is rejected by argparse; `kb.list_tasks` raises `status must be one of [...]` for programmatic callers. The board-count probe swallows exceptions.
- **Rebuild notes:** One parameterised SELECT + a readiness recompute. Better: paginate and add `--limit`, which the DB layer already supports but the CLI never exposes.

### `hermes kanban show` — show a task in full  `id: cli-c.kanban-show`
- **Surface:** CLI
- **Where:** `hermes kanban show <task_id> [--json] [--state-type {status,outcome}] [--state-name VALUE]`. Help: `Show a task with comments + events`.
- **What it does:** Prints everything about one task: metadata, effective retry threshold, active diagnostics, dependencies, body, result or latest run summary, all comments, the last 20 events and every run.
- **How it works:** `_cmd_show` (`hermes_cli/kanban.py:1786`) gathers task, comments, events, parents, children, runs, `kb.latest_summary` and (human mode only) `kb.task_graph_context`. Diagnostics come from `hermes_cli.kanban_diagnostics.compute_task_diagnostics` — the same rule engine the dashboard uses.
- **Inputs / options:** positional `task_id`; `--json` (store_true); `--state-type {status,outcome}` (None) — "With --state-name: filter listed runs by task_runs column"; `--state-name VALUE` (None, metavar `VALUE`) — "With --state-type: keep runs whose column equals this value"; `-h/--help`.
- **Outputs / side effects:** Read-only. JSON payload keys: `task` (see `_task_to_dict`), `latest_summary`, `parents`, `children`, `comments[{author,body,created_at}]`, `events[{kind,payload,created_at,run_id}]`, `runs[{id,profile,step_key,status,outcome,summary,error,metadata,worker_pid,started_at,ended_at}]`. Human output, in order: `Task <id>: <title>`, `  status:    <status>`, `  assignee:  <assignee or ->`, `  tenant:    <tenant>` (if set), `  workspace: <kind>[ @ <path>]`, `  branch:    <branch>` (if set), `  skills:    a, b` (if set), `  model:     <model>[ (provider: <p>)]` (if set), then the effective retry line — `  max-retries: <n> (task)`, `  max-retries: <n> (config kanban.failure_limit)`, or `  max-retries: 2 (default)` — then `  created:   <ts> by <created_by or ->`. Then a `\n  Diagnostics (<n>):` block with `    <marker> [<severity>] <title>` (markers `⚠` warning, `!!` error, `!!!` critical, `?` unknown), optional `       data: k=v | k=v` and `       → <suggested action label>`. Then `  started:`, `  completed:`, `  parents:`, `  children:` when present; `Body:` + body; `Result:` + result, or else `Latest summary:` + the latest run summary; `Comments (<n>):` with `  [<ts>] <author>: <body>`; `Events (<n>):` with the **last 20** as `  [<ts>][ [run <id>]] <kind>[ <payload>]`; `Runs (<n>):` with `  #<id:<3> <outcome:<12> @<profile or -> <elapsed>  <started ts>` plus `        → <first summary line, 160 chars>` and `        ! <first error line, 160 chars>`.
- **Config / env:** `kanban.failure_limit` for the effective-retry line.
- **Edge cases / guards:** Unknown id → stderr `no such task: <id>` exit 1. Passing exactly one of `--state-type`/`--state-name` → stderr `kanban show: pass both --state-type and --state-name, or omit both` exit 2 (`_run_state_kwargs`, line 87). Elapsed is clamped at 0 so an NTP backward jump cannot print a negative duration.
- **Rebuild notes:** Six queries + a fixed renderer + the shared diagnostics engine. Better: `--events N` to control the 20-event truncation.

### `hermes kanban assign` — assign or unassign a task  `id: cli-c.kanban-assign`
- **Surface:** CLI
- **Where:** `hermes kanban assign <task_id> <profile>`. Help: `Assign or reassign a task`.
- **What it does:** Sets (or clears) the profile that will execute a task.
- **How it works:** `_cmd_assign` (`hermes_cli/kanban.py:1961`): `profile` is treated as unassign when it lowercases to `none`, `-` or `null`; then `kb.assign_task(conn, task_id, profile)`.
- **Inputs / options:** positional `task_id`; positional `profile` — "Profile name (or 'none' to unassign)"; `-h/--help`.
- **Outputs / side effects:** `Assigned <task_id> to <profile>` or `Assigned <task_id> to (unassigned)`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown id → stderr `no such task: <id>` exit 1. A task that is **currently running with a claim** is refused by the store with `RuntimeError("cannot reassign <id>: currently running (claimed). Wait for completion or reclaim the stale lock first.")` (`hermes_cli/kanban_db.py:3726`), surfaced as `kanban: <exc>`. Changing the assignee also **resets** `consecutive_failures` to 0 and clears `last_failure_error`, because a human reassigning is an explicit recovery action and the new profile must not inherit the old one's failure streak; re-assigning to the same profile keeps the streak.
- **Rebuild notes:** Guarded UPDATE + an `assigned` event + a failure-streak reset. Better: expose the streak reset in the CLI output so the operator knows the circuit breaker was cleared.

### `hermes kanban set-model` — per-task model/provider override  `id: cli-c.kanban-set-model`
- **Surface:** CLI
- **Where:** `hermes kanban set-model <task_id> [model] [--provider PROVIDER]`. Help: `Set or clear a task's model/provider override (takes effect on the next dispatch)`.
- **What it does:** Pins the worker for one task to a specific model (and optionally provider) without touching the assignee profile's configured model.
- **How it works:** `_cmd_set_model` (`hermes_cli/kanban.py:1972`): the model is cleared when it lowercases to `none`, `-`, `null` or the empty string; then `kb.set_model_override(conn, task_id, model, provider=provider)`. The worker is spawned with `-m <model>` and `--provider <name>`.
- **Inputs / options:** positional `task_id`; positional optional `model` (`nargs="?"`, default None) — "Model to pin the worker to (or 'none' to clear the override)"; `--provider PROVIDER` (None) — "Provider the model belongs to (worker is spawned with --provider <name>). Cleared together with the model."; `-h/--help`.
- **Outputs / side effects:** Set: `Set model override on <task_id>: <provider>:<model> (applies on next dispatch)` — or just `<model>` when no provider. Clear: `Cleared model override on <task_id> (worker uses its profile default)`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** `ValueError`/`RuntimeError` from the store → stderr `kanban: <exc>` exit 2. Unknown id → `no such task: <id>` exit 1. Only affects the **next** dispatch — a running worker keeps its model.
- **Rebuild notes:** Two nullable columns. Better: validate the model against the provider's catalogue at set time.

### `hermes kanban reclaim` — release a worker claim  `id: cli-c.kanban-reclaim`
- **Surface:** CLI
- **Where:** `hermes kanban reclaim <task_id> [--reason REASON]`. Help: `Release an active worker claim on a running task`.
- **What it does:** Frees a task whose worker died or hung, so the dispatcher can pick it up again.
- **How it works:** `_cmd_reclaim` (`hermes_cli/kanban.py:1996`) → `kb.reclaim_task(conn, task_id, reason=…)`, which clears `claim_lock` and records a `reclaimed` event carrying the reason.
- **Inputs / options:** positional `task_id`; `--reason REASON` (None) — "Human-readable reason (recorded on the reclaimed event)"; `-h/--help`.
- **Outputs / side effects:** Writes a `reclaimed` event. Prints `Reclaimed <task_id>`. Return 0.
- **Config / env:** `kanban.dispatch_stale_timeout_seconds` governs the dispatcher's automatic stale reclaim.
- **Edge cases / guards:** Not running / unknown id → stderr `cannot reclaim <task_id> (not running or unknown id)` exit 1. Reclaiming does not kill the worker process — a still-live worker can keep writing.
- **Rebuild notes:** Clear the lock + event row. Better: optionally SIGTERM the recorded `worker_pid`.

### `hermes kanban reassign` — reassign (optionally reclaiming)  `id: cli-c.kanban-reassign`
- **Surface:** CLI
- **Where:** `hermes kanban reassign <task_id> <profile> [--reclaim] [--reason REASON]`. Help: `Reassign a task to a different profile, optionally reclaiming first`.
- **What it does:** Moves a task to another profile, releasing an active claim first when asked.
- **How it works:** `_cmd_reassign` (`hermes_cli/kanban.py:2012`): same `none`/`-`/`null` unassign convention; `kb.reassign_task(conn, task_id, profile, reclaim_first=…, reason=…)`.
- **Inputs / options:** positional `task_id`; positional `profile` — "New profile name (or 'none' to unassign)"; `--reclaim` (store_true) — "Release any active claim before reassigning (required if task is running)"; `--reason REASON` (None) — "Human-readable reason (recorded on the reclaimed event)"; `-h/--help`.
- **Outputs / side effects:** `Reassigned <task_id> to <profile>` (or `(unassigned)`), with ` (claim reclaimed)` appended when `--reclaim` was passed. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Failure → stderr `cannot reassign <task_id> (unknown id, or still running — pass --reclaim to release first)` exit 1. Note the ` (claim reclaimed)` suffix is printed whenever the flag was given, even if there was no claim to release.
- **Rebuild notes:** Reclaim-then-assign in one transaction. Better: report whether a claim was actually released.

### `hermes kanban diagnostics` (alias `diag`) — board health  `id: cli-c.kanban-diagnostics`
- **Surface:** CLI
- **Where:** `hermes kanban diagnostics [--severity {warning,error,critical}] [--task TASK] [--json]`, alias `diag`. Help: `List active diagnostics on the current board`.
- **What it does:** Runs the board's diagnostic rule engine over every non-archived task (or one task) and prints the distress signals with suggested actions.
- **How it works:** `_cmd_diagnostics` (`hermes_cli/kanban.py:2035`) loads `hermes_cli.kanban_diagnostics` and builds its config from the runtime config (`kd.config_from_runtime_config(load_config())`). One-task mode fetches that task's events, runs and `task_graph_context`; fleet mode selects all `status != 'archived'` tasks, bulk-loads `task_events` and `task_runs` with an `IN (...)` query and `kb.task_graph_contexts(conn, ids)`, then computes per task. Severity filtering uses `kd.SEVERITY_ORDER.index(...) >= index(sev)`. This wraps the **same rule engine the dashboard uses**, so CLI output matches the UI.
- **Inputs / options:** `--severity {warning,error,critical}` (None) — "Only show diagnostics at or above this severity"; `--task TASK` (None) — "Only show diagnostics for one task id"; `--json` (store_true) — "Emit JSON (structured) instead of the default human table"; `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: a list of `{"task_id": …, "title": …, "status": …, "assignee": …, "diagnostics": [d.to_dict()]}`. Human: `No active diagnostics on this board.` when empty; otherwise `<total> active diagnostic(s) across <n> task(s):` + blank, then per task `  <task_id>  <status:8>  @<assignee:18>  <title>` (title defaults to `(untitled)`, assignee to `(unassigned)`, status to `?`), then per diagnostic `    <marker> [<severity>] <kind>: <title>`, optional `       data: k=v | k=v` (list values joined with commas) and `       → <label>` for each **suggested** action, then a blank line. Return 0.
- **Config / env:** Diagnostic thresholds come from the runtime config via `config_from_runtime_config`.
- **Edge cases / guards:** `--task` with an unknown id → stderr `no such task: <id>` exit 1. Filtering can empty a task's list, in which case the task disappears from the output entirely. Always exits 0 even when critical diagnostics exist.
- **Rebuild notes:** Rule engine over (task, events, runs, graph) shared with the UI. Better: exit non-zero at/above a chosen severity so CI can gate on it.

### `hermes kanban link` — add a dependency  `id: cli-c.kanban-link`
- **Surface:** CLI
- **Where:** `hermes kanban link <parent_id> <child_id>`. Help: `Add a parent->child dependency`.
- **What it does:** Makes the child wait until the parent finishes.
- **How it works:** `_cmd_link` (`hermes_cli/kanban.py:2169`) → `kb.link_tasks(conn, parent_id, child_id)`, inserting into `task_links`. Readiness is recomputed by `recompute_ready` / the dispatcher.
- **Inputs / options:** positional `parent_id`; positional `child_id`; `-h/--help`.
- **Outputs / side effects:** `Linked <parent_id> -> <child_id>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** The store enforces three rules (`hermes_cli/kanban_db.py:3840`): self-links raise `a task cannot depend on itself`; unknown ids raise `unknown task(s): <ids>`; and a link that would create a cycle raises `linking <parent> -> <child> would create a cycle` (`_would_cycle`, line 3871, walks downward from the child looking for the parent). All three surface as `kanban: <exc>` via the group's `ValueError`/`RuntimeError` catch. Both tasks must be on the same board.
- **Rebuild notes:** One INSERT into an edge table guarded by a descendant walk, plus a demotion and an inherited-subscription step. Better: report the offending cycle path in the error.

### `hermes kanban unlink` — remove a dependency  `id: cli-c.kanban-unlink`
- **Surface:** CLI
- **Where:** `hermes kanban unlink <parent_id> <child_id>`. Help: `Remove a parent->child dependency`.
- **What it does:** Deletes one dependency edge.
- **How it works:** `_cmd_unlink` (`hermes_cli/kanban.py:2176`) → `kb.unlink_tasks(conn, parent_id, child_id)`.
- **Inputs / options:** positional `parent_id`; positional `child_id`; `-h/--help`.
- **Outputs / side effects:** `Unlinked <parent_id> -> <child_id>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** No such edge → stderr `No such link: <parent_id> -> <child_id>` exit 1.
- **Rebuild notes:** One DELETE. Better: recompute readiness immediately so a freed child shows as ready without waiting for a tick.

### `hermes kanban claim` — atomically claim a ready task  `id: cli-c.kanban-claim`
- **Surface:** CLI
- **Where:** `hermes kanban claim <task_id> [--ttl TTL]`. Help: `Atomically claim a ready task (prints resolved workspace path)`.
- **What it does:** Takes ownership of a ready task, materialises its workspace, and prints the path a worker should run in.
- **How it works:** `_cmd_claim` (`hermes_cli/kanban.py:2186`): `kb.claim_task(conn, task_id, ttl_seconds=args.ttl)` (CAS on `status`+`claim_lock`), then `kb.resolve_workspace(task)` and `kb.set_workspace_path(conn, task.id, str(workspace))`.
- **Inputs / options:** positional `task_id`; `--ttl TTL` (int, default `kb.DEFAULT_CLAIM_TTL_SECONDS` = `15 * 60` = **900**) — "Claim TTL in seconds (default: 900)"; `-h/--help`.
- **Outputs / side effects:** Sets `claim_lock` and `workspace_path`; may create the workspace directory or worktree. Prints `Claimed <id>` then `Workspace: <path>`. Return 0.
- **Config / env:** `HERMES_KANBAN_WORKSPACES_ROOT`.
- **Edge cases / guards:** Unknown id → stderr `no such task: <id>` exit 1. Otherwise the failure is explained: `cannot claim <task_id>: status=<status> lock=<claim_lock or (none)>` exit 1. Losing the CAS race is not an error condition to retry — the loser simply sees zero affected rows.
- **Rebuild notes:** CAS claim + TTL + workspace resolve. Better: a `--renew` to extend a TTL from a long-running worker (today `heartbeat` is the liveness signal).

### `hermes kanban comment` — append a comment  `id: cli-c.kanban-comment`
- **Surface:** CLI
- **Where:** `hermes kanban comment <task_id> <text…> [--author AUTHOR] [--max-len MAX_LEN]`. Help: `Append a comment`.
- **What it does:** Adds a timestamped, attributed comment to a task's thread, optionally truncating it.
- **How it works:** `_cmd_comment` (`hermes_cli/kanban.py:2208`): the variadic `text` is joined with spaces and stripped; when `--max-len` is set and exceeded, the body becomes `body[:max(0, max_len - len(suffix))].rstrip() + suffix` where `suffix = "\n\n[trimmed to <n> chars by --max-len]"`; author defaults to `_profile_author()` (`$HERMES_PROFILE` or `user`); then `kb.add_comment(conn, task_id, author, body)`.
- **Inputs / options:** positional `task_id`; positional variadic `text` (`nargs="+"`) — "Comment body"; `--author AUTHOR` (None) — "Author name (default: $HERMES_PROFILE or 'user')"; `--max-len MAX_LEN` (int, None) — "Trim the stored comment body to this many characters"; `-h/--help`.
- **Outputs / side effects:** Inserts into `task_comments`. Prints `Comment added to <task_id>`. Return 0.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** `--max-len < 1` → stderr `kanban: --max-len must be positive` exit 2. Because `text` is variadic and unquoted words are joined, shell globbing/quoting is the caller's problem. The task id is not validated — a comment on an unknown id relies on the store to error.
- **Rebuild notes:** Join + optional truncate + INSERT. Better: read the body from stdin when `text` is `-`.

### `hermes kanban attach` — attach a local file  `id: cli-c.kanban-attach`
- **Surface:** CLI
- **Where:** `hermes kanban attach <task_id> <path> [--content-type CONTENT_TYPE] [--name NAME] [--author AUTHOR]`. Help: `Attach a local file to a task`.
- **What it does:** Copies a local file into the task's attachments directory and records its metadata.
- **How it works:** `_cmd_attach` (`hermes_cli/kanban.py:2224`): reads the file bytes, guesses the MIME type with `mimetypes.guess_type(name)` when `--content-type` is absent, then `kb.store_attachment_bytes(conn, task_id, name, data, content_type=…, uploaded_by=…)` — **the same code path the dashboard upload and the agent tool use**, so the 25 MB cap and name sanitisation behave identically everywhere.
- **Inputs / options:** positional `task_id`; positional `path` — "Path to the local file to attach"; `--content-type CONTENT_TYPE` (None) — "MIME type (default: guessed from the file extension)"; `--name NAME` (None) — "Stored filename (default: the source file's basename)"; `--author AUTHOR` (None) — "uploaded_by label (default: $HERMES_PROFILE or 'user')"; `-h/--help`.
- **Outputs / side effects:** Writes the blob under the task's attachments dir + an attachment row. Prints `Attached <name> to <task_id> (attachment <id>, <n> bytes)`. Return 0.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** Missing/non-file path → stderr `kanban: no such file: <src>` exit 1. `kb.AttachmentTooLarge` → stderr `kanban: <exc>` exit 1 (25 MB cap). `~` in the path is expanded. The whole file is read into memory before storing.
- **Rebuild notes:** Read bytes → shared store function. Better: stream large files instead of buffering, and hash for de-duplication.

### `hermes kanban attachments` — list a task's attachments  `id: cli-c.kanban-attachments`
- **Surface:** CLI
- **Where:** `hermes kanban attachments <task_id> [--json]`. Help: `List a task's attachments`.
- **What it does:** Lists every file attached to a task with id, size, type, uploader and on-disk path.
- **How it works:** `_cmd_attachments` (`hermes_cli/kanban.py:2259`): verifies the task exists, then `kb.list_attachments(conn, task_id)`.
- **Inputs / options:** positional `task_id`; `--json` (store_true, no help text); `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: a list of `{id, filename, content_type, size, uploaded_by, stored_path, created_at}`. Human: `No attachments on <task_id>` or `Attachments on <task_id>:` then per attachment `  [<id>] <filename>  (<size> bytes, <content_type or ->, by <uploaded_by or ->)` and an indented second line `        <stored_path>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown task → stderr `no such task: <id>` exit 1.
- **Rebuild notes:** One SELECT + formatter. Better: show a total size and warn as the per-task budget fills.

### `hermes kanban attach-rm` — delete an attachment  `id: cli-c.kanban-attach-rm`
- **Surface:** CLI
- **Where:** `hermes kanban attach-rm <attachment_id>`. Help: `Delete an attachment by id`.
- **What it does:** Removes an attachment row and its on-disk blob.
- **How it works:** `_cmd_attach_rm` (`hermes_cli/kanban.py:2291`) → `kb.delete_attachment(conn, attachment_id)`, which returns the removed record (or `None`).
- **Inputs / options:** positional `attachment_id` (**type `int`**); `-h/--help`.
- **Outputs / side effects:** Deletes the row and the file. Prints `Deleted attachment <id> (<filename>) from <task_id>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown id → stderr `no such attachment: <id>` exit 1. A non-integer argument is rejected by argparse itself. No confirmation.
- **Rebuild notes:** DELETE + unlink. Better: soft-delete with a retention window.

### `hermes kanban complete` — mark tasks done  `id: cli-c.kanban-complete`
- **Surface:** CLI
- **Where:** `hermes kanban complete <task_ids…> [--result RESULT] [--summary SUMMARY] [--metadata METADATA]`. Help: `Mark one or more tasks done`.
- **What it does:** Closes one or more tasks, optionally recording a result, a structured handoff summary for downstream tasks, and a JSON metadata object on the closing run.
- **How it works:** `_cmd_complete` (`hermes_cli/kanban.py:2347`): parses `--metadata` as JSON (must be an object), then per id applies the **goal-mode judge gate** `_goal_mode_handoff_rejection(task, (summary or result).strip())` (line 2314 — uses `agent.auxiliary_client.get_text_auxiliary_client("goal_judge")` and `hermes_cli.goals.judge_goal`; a judge failure logs a warning and *allows* the handoff), then `kb.complete_task(conn, tid, result=…, summary=…, metadata=…, expected_run_id=_worker_run_id_for(tid))`.
- **Inputs / options:** positional variadic `task_ids` (`nargs="+"`) — "One or more task ids (only --result applies to all of them)"; `--result RESULT` (None) — "Result summary"; `--summary SUMMARY` (None) — "Structured handoff summary for downstream tasks. Falls back to --result if omitted."; `--metadata METADATA` (None) — "JSON dict of structured facts (e.g. '{\"changed_files\": [...], \"tests_run\": 12}'). Stored on the closing run."; `-h/--help`.
- **Outputs / side effects:** Sets `status=done`, `completed_at`, closes the run. Prints `Completed <tid>` per success; failures print to stderr. Returns 0 when every id succeeded, else 1.
- **Config / env:** `auxiliary.goal_judge` (the auxiliary model used by the judge).
- **Edge cases / guards:** No ids → stderr `at least one task_id is required` exit 1. `--summary`/`--metadata` with **more than one id** → stderr `kanban: --summary / --metadata are per-task and can't be used with multiple ids (would apply the same handoff to every task). Complete tasks one at a time, or drop the flags for the bulk close.` exit 2. Bad metadata → `kanban: --metadata: <exc>` exit 2 (also rejects a non-object JSON with `must be a JSON object`). A goal-mode task whose evidence the judge rejects → stderr `kanban: goal completion of <tid> rejected by judge: <reason>. Provide evidence matching the task's acceptance criteria.` and that id counts as failed. `expected_run_id` comes from `HERMES_KANBAN_TASK`/`HERMES_KANBAN_RUN_ID` so a worker can only close its own run (`_worker_run_id_for`, line 2302).
- **Rebuild notes:** Loop + CAS close + optional judge gate. Better: make the bulk/per-task flag conflict a parser-level error rather than a runtime check.

### `hermes kanban edit` — backfill a completed task's result  `id: cli-c.kanban-edit`
- **Surface:** CLI
- **Where:** `hermes kanban edit <task_id> --result RESULT [--summary SUMMARY] [--metadata METADATA]`. Help: `Edit recovery fields on an already-completed task`.
- **What it does:** Repairs a done task whose result/summary/metadata were never recorded.
- **How it works:** `_cmd_edit` (`hermes_cli/kanban.py:2409`) → `kb.edit_completed_task_result(conn, task_id, result=…, summary=…, metadata=…)`, which writes the metadata onto the **latest completed run**.
- **Inputs / options:** positional `task_id`; `--result RESULT` (**required**) — "Backfilled task result text for a done task"; `--summary SUMMARY` (None) — "Structured handoff summary. Falls back to --result if omitted."; `--metadata METADATA` (None) — "JSON dict of structured facts to store on the latest completed run."; `-h/--help`.
- **Outputs / side effects:** Updates `tasks.result` and the latest completed run. Prints `Edited <task_id>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Not done / unknown id → stderr `cannot edit <task_id> (unknown id or task is not done)` exit 1. Bad metadata → `kanban: --metadata: <exc>` exit 2. This is a **recovery path only** — it cannot change status or reopen the task.
- **Rebuild notes:** Constrained UPDATE limited to done tasks. Better: record who edited and when, as an event.

### `hermes kanban block` — block tasks (typed)  `id: cli-c.kanban-block`
- **Surface:** CLI
- **Where:** `hermes kanban block <task_id> [reason…] [--ids IDS…] [--kind {capability,dependency,needs_input,transient}]`. Help: `Mark one or more tasks blocked`.
- **What it does:** Marks tasks blocked with an optional typed reason that decides where they actually land (todo, blocked, or triage).
- **How it works:** `_cmd_block` (`hermes_cli/kanban.py:2437`): joins the variadic reason, builds `ids = [task_id] + (--ids)`, adds a comment `BLOCKED: <reason>` per id when a reason was given, then `kb.block_task(conn, tid, reason=…, kind=…, expected_run_id=_worker_run_id_for(tid))`, then re-reads the task to report **where it actually landed**.
- **Inputs / options:** positional `task_id`; positional variadic `reason` (`nargs="*"`) — "Reason (also appended as a comment)"; `--ids IDS [IDS …]` (`nargs="+"`, default None) — "Additional task ids to block with the same reason (bulk mode)"; `--kind {capability,dependency,needs_input,transient}` (None, choices = `sorted(kb.VALID_BLOCK_KINDS)`) — "Typed block reason. 'dependency' waits in todo (auto-promoted when parents finish, no human); 'needs_input'/'capability' go to blocked for a human; 'transient' marks a maybe-flaky failure. Repeated same-kind re-blocks after unblock route the task to triage to break unblock loops. Omit for a generic block."; `-h/--help`.
- **Outputs / side effects:** Status change + optional comment + event. Per id one of: `<tid> → todo (dependency wait)[: <reason>]`, `<tid> → triage (unblock loop detected — needs a human decision)[: <reason>]`, or `Blocked <tid>[: <reason>]`. Failures print `cannot block <tid>` to stderr. Returns 0 when all succeeded, else 1.
- **Config / env:** n/a
- **Edge cases / guards:** The comment is written **before** the block attempt, so a failed block can still leave a `BLOCKED:` comment. `expected_run_id` restricts a worker to its own run.
- **Rebuild notes:** Typed block reasons + a repeat-detector that escalates to triage. Better: make the comment write conditional on the block succeeding.

### `hermes kanban schedule` — park tasks in Scheduled  `id: cli-c.kanban-schedule`
- **Surface:** CLI
- **Where:** `hermes kanban schedule <task_id> [reason…] [--ids IDS…]`. Help: `Park one or more tasks in Scheduled (waiting on time, not human input)`.
- **What it does:** Moves tasks to the `scheduled` state — waiting on a clock rather than a person, so they are not mixed in with human-blocked work.
- **How it works:** `_cmd_schedule` (`hermes_cli/kanban.py:2474`), structurally identical to `block`: joins the reason, adds a `SCHEDULED: <reason>` comment per id, then `kb.schedule_task(conn, tid, reason=…, expected_run_id=…)`.
- **Inputs / options:** positional `task_id`; positional variadic `reason` (`nargs="*"`) — "Reason/timing note (also appended as a comment)"; `--ids IDS [IDS …]` (default None) — "Additional task ids to schedule with the same reason (bulk mode)"; `-h/--help`.
- **Outputs / side effects:** Status → `scheduled` + optional comment. Prints `Scheduled <tid>[: <reason>]` per success; `cannot schedule <tid>` on stderr per failure. Returns 0/1.
- **Config / env:** n/a
- **Edge cases / guards:** Same comment-before-attempt ordering as `block`. There is no time argument — the reason is free text; nothing auto-unschedules.
- **Rebuild notes:** One more status + comment. Better: accept `--until <ts>` and auto-promote when it passes.

### `hermes kanban unblock` — return tasks to ready/todo  `id: cli-c.kanban-unblock`
- **Surface:** CLI
- **Where:** `hermes kanban unblock <task_ids…> [--reason REASON]`. Help: `Return blocked/scheduled tasks to ready, or todo while parents remain open`.
- **What it does:** Releases blocked or scheduled tasks; they go to `ready`, or to `todo` when parents are still open.
- **How it works:** `_cmd_unblock` (`hermes_cli/kanban.py:2496`): when a reason is given it writes an `UNBLOCK: <reason>` comment (author `_profile_author()`) before calling `kb.unblock_task(conn, tid)`.
- **Inputs / options:** positional variadic `task_ids` (`nargs="+"`); `--reason REASON` (None) — "Optional reason/note — recorded as a comment before unblocking. Quote multi-word reasons."; `-h/--help`.
- **Outputs / side effects:** Status change + optional comment. `Unblocked <tid>[: <reason>]` per success; `cannot unblock <tid> (not blocked/scheduled?)` on stderr per failure. Returns 0/1.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** No ids → stderr `at least one task_id is required` exit 1 (argparse's `nargs="+"` normally prevents this). A whitespace-only `--reason` is normalised to `None`. `kb.unblock_task` (`hermes_cli/kanban_db.py:6901`) restores the **source phase**: for a previously-`blocked` task `_resume_status_from_events` recovers where it came from, so a task blocked out of `review` returns to `review`; `scheduled` tasks always resume at `ready`; and `_landing_status_after_parents` re-gates on parents, landing the task in `todo` while any parent is still open. It defensively closes a dangling `current_run_id` as `reclaimed` in the same transaction to keep the runs invariant. It resets `consecutive_failures` and `last_failure_error` (a deliberate unblock is a fresh dispatcher retry budget) but deliberately does **not** touch `block_recurrences` / `block_kind` — that counter must survive so a same-cause re-block can detect the unblock loop and route to triage at `BLOCK_RECURRENCE_LIMIT`; it is cleared only by a successful `complete_task`.
- **Rebuild notes:** Source-phase restore + parent re-gate + counter policy (reset the retry budget, keep the loop counter). Better: report where each task landed (ready/todo/review), as `block` does.

### `hermes kanban request-review` — move a task to review  `id: cli-c.kanban-request-review`
- **Surface:** CLI
- **Where:** `hermes kanban request-review <task_id> [--summary SUMMARY] [--reviewer REVIEWER] [--metadata METADATA] [--force]`. Help: `Move a task to 'review' (implementation done, awaiting review) — NOT a block`.
- **What it does:** Hands an implemented task to a reviewer, recording what was implemented and how it was verified.
- **How it works:** `_cmd_request_review` (`hermes_cli/kanban.py:2518`): parses `--metadata` as a JSON object, applies the same goal-mode judge gate as `complete` (so review cannot bypass the acceptance contract), then `kb.request_review(conn, tid, summary=…, metadata=…, reviewer=…, expected_run_id=…, force=…, with_reason=True)`, and finally re-reads `kb.latest_run(conn, tid).summary` to echo what was actually persisted.
- **Inputs / options:** positional `task_id`; `--summary SUMMARY` (None) — "What was implemented and how it was verified — shown to the reviewer."; `--reviewer REVIEWER` (None) — "Optional reviewer profile; reassigns the task before review dispatch."; `--metadata METADATA` (None) — "JSON object with structured reviewer handoff facts."; `--force` (store_true) — "Override the live-claim guard: move a running, claimed task to review even without owning its run (clears the worker's claim)."; `-h/--help`.
- **Outputs / side effects:** Status → `review`, possibly reassigns, closes the implementation run. Prints `Requested review for <tid>[: <persisted summary>]`. Return 0.
- **Config / env:** `kanban.review_dispatch` (true) controls whether reviewers are dispatched automatically.
- **Edge cases / guards:** Bad metadata → `kanban: --metadata: <exc>` exit 2. Judge rejection → stderr `kanban: goal review handoff of <tid> rejected by judge: <reason>. Provide acceptance evidence matching the task.` exit 1. Store refusal → `cannot request review for <tid>: <detail or 'not running/ready?'>` exit 1. `--force` clears another worker's claim — an explicitly destructive override.
- **Rebuild notes:** Status transition + run close + optional reassign, gated by claim ownership. Better: require a reason with `--force` and record it on the event.

### `hermes kanban request-changes` — reviewer verdict  `id: cli-c.kanban-request-changes`
- **Surface:** CLI
- **Where:** `hermes kanban request-changes <task_id> <reason…>`. Help: `Reviewer verdict: return the active review run to its implementer`.
- **What it does:** The reviewer's "no" — sends the task back to whoever implemented it, with the concrete changes required.
- **How it works:** `_cmd_request_changes` (`hermes_cli/kanban.py:2572`): joins the variadic reason, then `kb.request_changes(conn, tid, reason=…, expected_run_id=_worker_run_id_for(tid))`, which returns `(ok, detail)` where `detail` names where the task was routed.
- **Inputs / options:** positional `task_id`; positional variadic `reason` (`nargs="+"`) — "Concrete changes required before re-review"; `-h/--help`.
- **Outputs / side effects:** Routes the task back to its implementer. Prints `Requested changes for <tid>[; routed to <detail>]`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Invalid review state → stderr `cannot request changes for <tid>: <detail or 'invalid review state'>` exit 1. The reason is **required** (`nargs="+"`), unlike `reopen-review` where it is optional.
- **Rebuild notes:** Review→implementer transition keyed on the active review run. Better: attach the reason to the reopened run so the implementer sees it in `context`.

### `hermes kanban reopen-review` — send review tasks back  `id: cli-c.kanban-reopen-review`
- **Surface:** CLI
- **Where:** `hermes kanban reopen-review <task_ids…> [--reason REASON]`. Help: `Send one or more review tasks back for changes (review -> ready/todo)`.
- **What it does:** The operator-side bulk equivalent of `request-changes`: pulls tasks out of review back into the work queue.
- **How it works:** `_cmd_reopen_review` (`hermes_cli/kanban.py:2595`): the reason is passed through `kb.redact_review_value(...)` before being stripped, then per id `kb.reopen_review_task(conn, tid)` and, on success, a comment `CHANGES REQUESTED: <reason>` authored by `_profile_author()` or the literal `operator`.
- **Inputs / options:** positional variadic `task_ids` (`nargs="+"`); `--reason REASON` (None) — "Optional reason/note — recorded as a comment before reopening. Quote multi-word reasons."; `-h/--help`.
- **Outputs / side effects:** Status → `ready`/`todo` + optional comment. `Reopened <tid>[: <reason>]` per success; `cannot reopen <tid> (not in review?)` on stderr per failure. Returns 0/1.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** No ids → stderr `at least one task_id is required` exit 1. Note the help text says the comment is recorded "before reopening" but the code writes it **after** the successful transition. The reason is redacted (secret-scrubbed) before storage.
- **Rebuild notes:** Bulk review→queue transition. Better: align the help text with the actual ordering.

### `hermes kanban promote` — force tasks to ready  `id: cli-c.kanban-promote`
- **Surface:** CLI
- **Where:** `hermes kanban promote <task_id> [reason…] [--ids IDS…] [--force] [--dry-run] [--json]`. Help: `Manually move one or more todo/blocked tasks to ready (recovery path)`.
- **What it does:** The recovery path that pushes stuck tasks into `ready` so the dispatcher will pick them up, optionally ignoring unmet dependencies.
- **How it works:** `_cmd_promote` (`hermes_cli/kanban.py:2622`): dedupes `[task_id, *--ids]` preserving order (positional first), then per id `kb.promote_task(conn, tid, actor=_profile_author(), reason=…, force=…, dry_run=…)` returning `(ok, err)`, collecting a result dict per id.
- **Inputs / options:** positional `task_id`; positional variadic `reason` (`nargs="*"`) — "Audit-trail reason (recorded on the task_events row)"; `--ids IDS [IDS …]` (default None) — "Additional task ids to promote with the same reason (bulk mode)"; `--force` (store_true) — "Promote even if parent dependencies are not yet done/archived"; `--dry-run` (store_true) — "Validate the promotion without mutating state"; `--json` (store_true) — "Emit machine-readable JSON result"; `-h/--help`.
- **Outputs / side effects:** Status → `ready` + a `task_events` row carrying the actor and reason. JSON: a flat object for a single id (back-compat) or a list for bulk, each `{task_id, promoted, dry_run, forced, reason, error}`. Human: `Promoted <tid> -> ready[: <reason>]`, or `Would promote <tid> -> ready (dry)[: <reason>]` under `--dry-run`; failures print `cannot promote <tid>: <error>` to stderr. Returns 0 when all succeeded, else 1 (in both JSON and human mode).
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** `--dry-run` validates without mutating. `--force` bypasses the dependency check — the escape hatch for a wedged graph.
- **Rebuild notes:** Per-id validate-then-transition with an audit event. Better: report *which* parents are unmet in the error text.

### `hermes kanban archive` — archive or purge tasks  `id: cli-c.kanban-archive`
- **Surface:** CLI
- **Where:** `hermes kanban archive [task_ids…] [--rm PURGE_IDS…]`. Help: `Archive one or more tasks`.
- **What it does:** Archives tasks (hiding them from listings) or, with `--rm`, permanently deletes already-archived ones.
- **How it works:** `_cmd_archive` (`hermes_cli/kanban.py:2673`): two mutually exclusive modes. Purge mode calls `kb.delete_archived_task(conn, tid)` per id; archive mode calls `kb.archive_task(conn, tid)`.
- **Inputs / options:** positional variadic `task_ids` (`nargs="*"`) — "Task ids to archive (default mode)"; `--rm PURGE_IDS [PURGE_IDS …]` (dest `purge_ids`, `nargs="+"`, default None) — "Permanently delete already-archived task ids from the board"; `-h/--help`.
- **Outputs / side effects:** Archive: `Archived <tid>` per success, `cannot archive <tid>` on stderr per failure. Purge: `Deleted <tid>` per success, `cannot delete <tid> (must already be archived)` on stderr per failure. Returns 0/1. Archived tasks' scratch workspaces are cleaned up later by `gc`.
- **Config / env:** n/a
- **Edge cases / guards:** Passing both modes → stderr `choose either task_ids to archive or --rm archived task_ids` exit 1. Neither → `at least one task_id is required` exit 1. A task must **already be archived** before `--rm` will delete it — a two-step destructive path by design.
- **Rebuild notes:** Two loops behind one command with a mode conflict check. Better: make it two sub-commands (`archive` / `purge`) so the exclusive modes are structural.

### `hermes kanban tail` — follow one task's events  `id: cli-c.kanban-tail`
- **Surface:** CLI
- **Where:** `hermes kanban tail <task_id> [--interval INTERVAL]`. Help: `Follow a task's event stream`.
- **What it does:** Polls one task's event stream and prints new events as they arrive, until Ctrl-C.
- **How it works:** `_cmd_tail` (`hermes_cli/kanban.py:2701`): a loop that opens a fresh connection each iteration, calls `kb.list_events(conn, task_id)`, prints every event with `id > last_id`, then sleeps `max(0.1, interval)`.
- **Inputs / options:** positional `task_id`; `--interval INTERVAL` (**float**, default `1.0`, no help text); `-h/--help`.
- **Outputs / side effects:** Read-only, long-running. Prints `Tailing events for <task_id>. Ctrl-C to stop.` then per event `[<ts>] <kind>[ <payload>]` (flushed). On Ctrl-C: `\n(stopped)` and return 0.
- **Config / env:** n/a
- **Edge cases / guards:** The interval is floored at 0.1 s. It re-reads the **whole** event list each poll and filters client-side, so a task with thousands of events polls expensively. An unknown task id simply produces no output rather than an error.
- **Rebuild notes:** Poll-with-cursor. Better: use the `id > ?` SQL filter (as `watch` does) instead of fetching all events every tick.

### `hermes kanban watch` — live-stream board events  `id: cli-c.kanban-watch`
- **Surface:** CLI
- **Where:** `hermes kanban watch [--assignee ASSIGNEE] [--tenant TENANT] [--kinds KINDS] [--interval INTERVAL]`. Help: `Live-stream task_events to the terminal (Ctrl+C to exit)`.
- **What it does:** Streams every new board event (optionally filtered by assignee, tenant or kind) as it happens.
- **How it works:** `_cmd_watch` (`hermes_cli/kanban.py:2971`): seeds the cursor at `SELECT COALESCE(MAX(id),0) FROM task_events` so history is not replayed, then polls `SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.assignee, t.tenant FROM task_events e LEFT JOIN tasks t ON t.id = e.task_id WHERE e.id > ? ORDER BY e.id ASC LIMIT 200`, filters client-side and sleeps `max(0.1, interval)`.
- **Inputs / options:** `--assignee ASSIGNEE` (None) — "Only show events for tasks assigned to this profile"; `--tenant TENANT` (None) — "Only show events from tasks in this tenant"; `--kinds KINDS` (None) — "Comma-separated event kinds to include (e.g. 'completed,blocked,gave_up,crashed,timed_out')"; `--interval INTERVAL` (**float**, default `0.5`) — "Poll interval in seconds (default: 0.5)"; `-h/--help`.
- **Outputs / side effects:** Read-only, long-running. Prints `Watching kanban events. Ctrl-C to stop.` then per event `[<ts>] <task_id:10> <kind:18> (@<assignee or ->)[ <payload dict>]`. On Ctrl-C: `\n(stopped)` return 0.
- **Config / env:** n/a
- **Edge cases / guards:** The 200-row `LIMIT` per poll means a burst larger than 200 events per interval is drained across several polls (never lost, since the cursor advances only over rows actually fetched). Payload JSON that fails to parse is rendered as nothing. Filters are applied **after** the cursor advance, so filtered-out events still move the cursor (correct behaviour).
- **Rebuild notes:** Cursor + LIMIT + client-side filters. Better: push filters into SQL and support `--since`.

### `hermes kanban stats` — board statistics  `id: cli-c.kanban-stats`
- **Surface:** CLI
- **Where:** `hermes kanban stats [--json]`. Help: `Per-status + per-assignee counts + oldest-ready age`.
- **What it does:** Summarises the board: how many tasks in each status, per-assignee breakdown, and how long the oldest ready task has been waiting.
- **How it works:** `_cmd_stats` (`hermes_cli/kanban.py:3020`) → `kb.board_stats(conn)` returning `{by_status, by_assignee, oldest_ready_age_seconds}`.
- **Inputs / options:** `--json` (store_true, no help text); `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: the raw stats dict. Human: `By status:` then a fixed-order list of exactly seven statuses — `triage`, `todo`, `scheduled`, `ready`, `running`, `blocked`, `done` — each as `  <status:8>  <count>` (0 when absent); then, when non-empty, `\nBy assignee:` with `  <who:20>  status=n, status=n`; then, when known, `\nOldest ready task age: <n>s`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** The human table deliberately omits `review` and `archived` from the fixed status list, so review-column work is invisible in human mode (it is present in `--json`).
- **Rebuild notes:** Three aggregate queries. Better: iterate `VALID_STATUSES` rather than a hardcoded seven, so no status can be silently dropped.

### `hermes kanban dispatch` — one dispatcher pass  `id: cli-c.kanban-dispatch`
- **Surface:** CLI
- **Where:** `hermes kanban dispatch [--dry-run] [--max MAX] [--failure-limit FAILURE_LIMIT] [--json]`. Help: `One dispatcher pass: reclaim stale, promote ready, spawn workers`.
- **What it does:** Runs a single dispatcher tick by hand: reclaims stale claims, detects crashed/timed-out workers, auto-blocks repeat failures, promotes ready tasks and spawns workers.
- **How it works:** `_cmd_dispatch` (`hermes_cli/kanban.py:2719`) reads `kanban.default_assignee`, `kanban.max_in_progress_per_profile`, `kanban.max_in_progress` (passed through `kb.resolve_max_in_progress(...)`, which supplies a **memory-derived default when unset**) and `kanban.max_spawn`, then calls `kb.dispatch_once(conn, dry_run=…, max_spawn=…, max_in_progress=…, failure_limit=…, default_assignee=…, max_in_progress_per_profile=…)`. **CLI `--max` overrides config `kanban.max_spawn`** because it is the more explicit signal. Any config-read failure degrades every knob to `None` except `max_spawn`, which falls back to `--max`. The semantics are identical to the gateway-embedded dispatcher, so behaviour matches whichever path runs the tick.
- **Inputs / options:** `--dry-run` (store_true) — "Don't actually spawn processes; just print what would happen"; `--max MAX` (int, None) — "Cap number of spawns this pass"; `--failure-limit FAILURE_LIMIT` (int, default `kb.DEFAULT_SPAWN_FAILURE_LIMIT` = `DEFAULT_FAILURE_LIMIT` = **2**) — "Auto-block a task after this many consecutive non-success attempts (spawn_failed, timed_out, or crashed; default: 2)"; `--json` (store_true, no help text); `-h/--help`.
- **Outputs / side effects:** Spawns worker processes (unless `--dry-run`), writes claims, events and runs. JSON keys: `reclaimed`, `crashed`, `timed_out`, `stale`, `auto_blocked`, `promoted`, `spawned[{task_id,assignee,workspace}]`, `skipped_unassigned`, `skipped_nonspawnable`, `skipped_per_profile_capped[{task_id,assignee,current}]`, `auto_assigned_default`. Human output lines, in order: `Reclaimed:    <n>`; `Crashed:      <n>` + an indented comma-joined id list when non-empty; `Timed out:    <n>` + list; `Stale:        <n>` + list; `Auto-blocked: <n>` + list; `Promoted:     <n>`; `Spawned:      <n>` then per spawn `  - <tid>  ->  <who>  @ <workspace or ->` with ` (dry)` appended under `--dry-run`; then optionally `Auto-assigned to kanban.default_assignee='<name>': <ids>`, `Skipped (unassigned): <ids>`, one `Deferred (<who> at per-profile cap, <current> running): <tid>` line per capped task, and `Skipped (non-spawnable assignee — terminal lane, OK): <ids>`. Return 0.
- **Config / env:** `kanban.default_assignee`, `kanban.max_in_progress`, `kanban.max_in_progress_per_profile`, `kanban.max_spawn`, `kanban.failure_limit`, `kanban.dispatch_stale_timeout_seconds`.
- **Edge cases / guards:** Running this while a gateway dispatcher is also ticking means two dispatchers race for claims — safe (CAS) but wasteful. Non-positive config values are coerced to `None` by `_coerce_positive_int`.
- **Rebuild notes:** One tick = reclaim → detect terminal-state workers → auto-block → promote → spawn under caps. Better: emit the tick result as a structured event so operators can trend it.

### `hermes kanban daemon` — DEPRECATED standalone dispatcher  `id: cli-c.kanban-daemon`
- **Surface:** CLI
- **Where:** `hermes kanban daemon [--interval INTERVAL] [--max MAX] [--failure-limit FAILURE_LIMIT] [--pidfile PIDFILE] [--verbose|-v]`. Help: `DEPRECATED — dispatcher now runs in the gateway. Use \`hermes gateway start\`.`
- **What it does:** By default refuses to run and prints a migration message; behind a hidden `--force` it still runs the legacy standalone dispatch loop.
- **How it works:** `_cmd_daemon` (`hermes_cli/kanban.py:2830`). Without `--force` it prints the deprecation block to stderr and returns **2**. With `--force` it calls `kb.init_db()` first (so the DB path and any init error surface before "started"), optionally writes the pidfile, prints a warning to stderr, and enters the loop with health telemetry: a `HEALTH_WINDOW = 6`-tick window that warns when every tick finds ready work but spawns nothing (catching broken profiles, PATH drift, missing venv, credential loss — cases where the per-task circuit breaker auto-blocks each task quietly while the dispatcher itself is dysfunctional).
- **Inputs / options:** `--interval INTERVAL` (**float**, default `60.0`) — "Seconds between dispatch ticks (default: 60)"; `--max MAX` (int, None) — "Cap number of spawns per tick"; `--failure-limit FAILURE_LIMIT` (int, default 2, no help text); `--pidfile PIDFILE` (None) — "Write the daemon's PID to this file on start"; `--verbose` / `-v` (store_true) — "Log each tick's outcome to stdout"; **`--force`** (store_true, `help=argparse.SUPPRESS`) — an undocumented escape hatch deliberately excluded from `--help` "so nobody discovers it casually and keeps the old double-dispatcher pattern alive"; `-h/--help`.
- **Outputs / side effects:** Default path: the stderr block `hermes kanban daemon: DEPRECATED — the dispatcher now runs` / `inside the gateway. To use kanban:` / blank / `    hermes gateway start       # starts the gateway + embedded dispatcher` / blank / `Ready tasks will be picked up on the next dispatcher tick` / `(default: every 60 seconds). Configure via config.yaml:` / blank / `    kanban:` / `      dispatch_in_gateway: true      # default` / `      dispatch_interval_seconds: 60` / `      failure_limit: 2              # consecutive non-success attempts before auto-block` / blank / `Running both the gateway AND this standalone daemon will` / `race for claims. If you truly need the old standalone` / `daemon (no gateway available), rerun with --force.` — exit 2. Forced path: writes the pidfile, prints to stderr `Kanban dispatcher running STANDALONE via --force (interval=<n>s, pid=<pid>). Ctrl-C to stop. NOTE: if a gateway is also running with dispatch_in_gateway=true (default), you have two dispatchers racing for claims.` and loops.
- **Config / env:** `kanban.dispatch_in_gateway`, `kanban.dispatch_interval_seconds`, `kanban.failure_limit`.
- **Edge cases / guards:** A failed pidfile write only warns (`warning: could not write pidfile <path>: <exc>`) and continues. The stub exists so old scripts/systemd units get guidance rather than "no such command".
- **Rebuild notes:** Keep the deprecated verb as an explaining stub with a suppressed escape hatch. Better: detect a live gateway and refuse `--force` outright rather than warning.

### `hermes kanban notify-subscribe` — subscribe a chat to a task  `id: cli-c.kanban-notify-subscribe`
- **Surface:** CLI
- **Where:** `hermes kanban notify-subscribe <task_id> --platform PLATFORM --chat-id CHAT_ID [--thread-id THREAD_ID] [--user-id USER_ID] [--user-id-alt USER_ID_ALT] [--chat-type {dm,group,channel,thread}] [--notifier-profile NOTIFIER_PROFILE] [--delivery-mode {notify,notify+wake,wake}]`. Help: `Subscribe a gateway source to a task's terminal events (used by /kanban subscribe in the gateway adapter)`.
- **What it does:** Registers a chat destination that should be told (and optionally woken) when a task reaches a terminal event.
- **How it works:** `_cmd_notify_subscribe` (`hermes_cli/kanban.py:3040`): verifies the task exists, then `kb.add_notify_sub(conn, task_id=…, platform=…, chat_id=…, chat_type=…, thread_id=…, user_id=…, user_id_alt=…, notifier_profile=args.notifier_profile or _profile_author(), delivery_mode=…)`. `_NOTIFY_DELIVERY_MODES = ("notify", "notify+wake", "wake")` (`hermes_cli/kanban_db.py:11358`) is the single source of truth shared with the DB/watcher enum.
- **Inputs / options:** positional `task_id`; `--platform PLATFORM` (**required**, no help text); `--chat-id CHAT_ID` (**required**, no help text); `--thread-id THREAD_ID` (None, no help text); `--user-id USER_ID` (None, no help text); `--user-id-alt USER_ID_ALT` (None, no help text); `--chat-type {dm,group,channel,thread}` (None) — "Originating source chat_type, recorded so the active-wake delivery modes resolve the operator's real session. Omit to leave an existing sub unchanged (new subs default to 'dm')."; `--notifier-profile NOTIFIER_PROFILE` (None) — "Profile gateway that owns/delivers this subscription (default: active profile)"; `--delivery-mode {notify,notify+wake,wake}` (None) — "How the kanban-notifier reacts to terminal events for this subscription: 'notify' (passive message only; default), 'notify+wake' (message AND wake the destination gateway agent so it reads the full board context and replies in its own voice), or 'wake' (wake the agent only, no passive message). Omit to leave an existing subscription's mode unchanged (new subs default to 'notify')."; `-h/--help`.
- **Outputs / side effects:** Inserts/updates a subscription row. Prints `Subscribed <platform>:<chat_id>[:<thread_id>] to <task_id>`. Return 0.
- **Config / env:** `kanban.auto_subscribe_on_create` (true) makes the gateway subscribe the creating chat automatically; `kanban.done_sub_retention_days` (30) bounds how long done-task subscriptions are kept.
- **Edge cases / guards:** Unknown task → stderr `no such task: <id>` exit 1. Omitting `--chat-type` / `--delivery-mode` on an **existing** subscription leaves those fields unchanged (a tri-state, not a reset to the default).
- **Rebuild notes:** `(task_id, platform, chat_id, thread_id)` unique subscription row + a delivery mode enum. Better: expose a `--all-events` mode instead of terminal-only.

### `hermes kanban notify-list` — list subscriptions  `id: cli-c.kanban-notify-list`
- **Surface:** CLI
- **Where:** `hermes kanban notify-list [task_id] [--json]`. Help: `List notification subscriptions (optionally for a single task)`.
- **What it does:** Shows which chats are subscribed to which tasks, with owner, chat type, alt user id and delivery mode.
- **How it works:** `_cmd_notify_list` (`hermes_cli/kanban.py:3060`) → `kb.list_notify_subs(conn, task_id)` (a `None` task id lists all).
- **Inputs / options:** positional optional `task_id` (`nargs="?"`, default None); `--json` (store_true, no help text); `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: the raw subscription list. Human: `(no subscriptions)` or per row `  <task_id:10>  <platform>:<chat_id>[:<thread_id>]  (since event <last_event_id>)[  owner=<notifier_profile>][  chat_type=<type>][  user_id_alt=<id>][  mode=<mode>]` — the `chat_type` and `mode` suffixes are **omitted when they equal the defaults** (`dm` and `notify` respectively), so the common case stays terse. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** No task-existence check — listing an unknown id just prints `(no subscriptions)`.
- **Rebuild notes:** One SELECT + conditional suffixes. Better: a `--platform` filter.

### `hermes kanban notify-unsubscribe` — remove a subscription  `id: cli-c.kanban-notify-unsubscribe`
- **Surface:** CLI
- **Where:** `hermes kanban notify-unsubscribe <task_id> --platform PLATFORM --chat-id CHAT_ID [--thread-id THREAD_ID]`. Help: `Remove a gateway subscription from a task`.
- **What it does:** Stops a chat from being notified about a task.
- **How it works:** `_cmd_notify_unsubscribe` (`hermes_cli/kanban.py:3082`) → `kb.remove_notify_sub(conn, task_id=…, platform=…, chat_id=…, thread_id=…)`.
- **Inputs / options:** positional `task_id`; `--platform PLATFORM` (**required**); `--chat-id CHAT_ID` (**required**); `--thread-id THREAD_ID` (None); `-h/--help`.
- **Outputs / side effects:** Deletes the row. Prints `Unsubscribed from <task_id>`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** No matching subscription → stderr `(no such subscription)` exit 1. The `(platform, chat_id, thread_id)` triple must match exactly — a subscription created **with** a thread id cannot be removed without passing it.
- **Rebuild notes:** Keyed DELETE. Better: allow removing by row id, which `notify-list --json` already exposes.

### `hermes kanban log` — print a worker log  `id: cli-c.kanban-log`
- **Surface:** CLI
- **Where:** `hermes kanban log <task_id> [--tail TAIL]`. Help: `Print the worker log for a task (from <kanban-root>/kanban/logs/)`.
- **What it does:** Dumps the worker's stdout/stderr log for one task, optionally only the last N bytes.
- **How it works:** `_cmd_log` (`hermes_cli/kanban.py:3096`) → `kb.read_worker_log(task_id, tail_bytes=args.tail)`, writing the content directly to `sys.stdout` and appending a newline when the content does not end with one.
- **Inputs / options:** positional `task_id`; `--tail TAIL` (int, None) — "Only print the last N bytes"; `-h/--help`.
- **Outputs / side effects:** Read-only. Missing log → stderr `(no log for <task_id> — task may not have spawned yet)` exit 1.
- **Config / env:** `kanban.worker_log_rotate_bytes` (2 097 152 = 2 MiB), `kanban.worker_log_backup_count` (1) govern rotation; logs live under `<kanban-root>/kanban/logs/`.
- **Edge cases / guards:** `--tail` counts **bytes**, not lines, so it can slice mid-character on multi-byte UTF-8. Rotated backups are not concatenated — only the current log file is read.
- **Rebuild notes:** Read (or seek-and-read) one file. Better: a `--follow` mode and line-based tailing.

### `hermes kanban runs` — attempt history for a task  `id: cli-c.kanban-runs`
- **Surface:** CLI
- **Where:** `hermes kanban runs <task_id> [--json] [--state-type {status,outcome}] [--state-name VALUE]`. Help: `Show attempt history for a task (one row per run: profile, outcome, elapsed, summary)`.
- **What it does:** Prints every execution attempt of a task with its outcome, profile, elapsed time, summary and error.
- **How it works:** `_cmd_runs` (`hermes_cli/kanban.py:3108`) → `kb.list_runs(conn, task_id, **rsk)` where `rsk` comes from `_run_state_kwargs`. Elapsed is `max(0, (ended_at or now) - started_at)` — clamped so an NTP backward jump cannot print a negative duration — and formatted `<n>s` under a minute, `<n>m` under an hour, `<n.n>h` above.
- **Inputs / options:** positional `task_id`; `--json` (store_true); `--state-type {status,outcome}` (None) — "With --state-name: filter runs by task_runs column"; `--state-name VALUE` (None, metavar `VALUE`) — "With --state-type: keep runs whose column equals this value"; `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: a list of `{id, profile, status, outcome, started_at, ended_at, summary, error, metadata, worker_pid, step_key}`. Human: `(no runs yet for <task_id>)`, or the header `#    OUTCOME       PROFILE            ELAPSED  STARTED` (`{'#':3s}  {'OUTCOME':12s}  {'PROFILE':16s}  {'ELAPSED':>8s}  STARTED`) then per run `<i:3d>  <outcome:12>  <profile or -:16>  <elapsed:>8>  <started ts>`, plus `     → <first summary line, 100 chars>` and `     ✖ <error, 100 chars>`. `outcome` falls back to `(running)` when the run has no `ended_at`, else to `status`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** Passing only one of `--state-type`/`--state-name` → stderr `kanban runs: pass both --state-type and --state-name, or omit both` exit 2. The row index `#` is a display counter, not the run id (the id is in `--json`).
- **Rebuild notes:** One SELECT + duration formatter. Better: print the run id in the human table so `--state-*` filters can be targeted.

### `hermes kanban heartbeat` — worker liveness signal  `id: cli-c.kanban-heartbeat`
- **Surface:** CLI
- **Where:** `hermes kanban heartbeat <task_id> [--note NOTE]`. Help: `Emit a heartbeat event for a running task (worker liveness signal)`.
- **What it does:** Lets a long-running worker prove it is still alive so the dispatcher does not reclaim its task as stale.
- **How it works:** `_cmd_heartbeat` (`hermes_cli/kanban.py:1608`) → `kb.heartbeat_worker(conn, task_id, note=…, expected_run_id=_worker_run_id_for(task_id))`.
- **Inputs / options:** positional `task_id`; `--note NOTE` (None) — "Optional short note attached to the heartbeat event"; `-h/--help`.
- **Outputs / side effects:** Writes a heartbeat event. Prints `Heartbeat recorded for <task_id>`. Return 0.
- **Config / env:** `HERMES_KANBAN_TASK`, `HERMES_KANBAN_RUN_ID` (the worker's own run identity); `kanban.dispatch_stale_timeout_seconds` (14400) is the staleness threshold.
- **Edge cases / guards:** Not running / unknown / wrong run → stderr `cannot heartbeat <task_id> (not running?)` exit 1. `expected_run_id` is only non-`None` when `HERMES_KANBAN_TASK` matches the id being heartbeaten, so a worker cannot heartbeat someone else's task.
- **Rebuild notes:** One event row + a timestamp the reclaimer reads. Better: heartbeat automatically from the worker runtime rather than requiring a CLI call.

### `hermes kanban assignees` — known profiles and their load  `id: cli-c.kanban-assignees`
- **Surface:** CLI
- **Where:** `hermes kanban assignees [--json]`. Help: `List known profiles + per-profile task counts (union of ~/.hermes/profiles/ and current assignees on the board)`.
- **What it does:** Lists every profile that can be an assignee, whether it exists on disk, and how many tasks it holds per status.
- **How it works:** `_cmd_assignees` (`hermes_cli/kanban.py:1623`) → `kb.known_assignees(conn)`, which unions the profile directories under `~/.hermes/profiles/` with the distinct assignees currently on the board.
- **Inputs / options:** `--json` (store_true, no help text); `-h/--help`.
- **Outputs / side effects:** Read-only. JSON: the raw list. Human: `(no assignees — create a profile with \`hermes -p <name> setup\`)` or the header `NAME                  ON DISK   COUNTS` (`{'NAME':20s}  {'ON DISK':8s}  COUNTS`) then per entry `<name:20>  <yes|no:8>  <status=n, status=n>` or `(idle)`. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** A profile that exists only as a board assignee (never created on disk) shows `on disk = no` — a useful signal that dispatch will fail for it.
- **Rebuild notes:** Union of a directory listing and a `DISTINCT assignee` query. Better: flag `on disk = no` rows as an error, since they can never be dispatched.

### `hermes kanban context` — print a worker's full context  `id: cli-c.kanban-context`
- **Surface:** CLI
- **Where:** `hermes kanban context <task_id>`. Help: `Print the full context a worker sees for a task (title + body + parent results + comments).`
- **What it does:** Renders exactly the text a spawned worker receives for a task, for debugging or manual execution.
- **How it works:** `_cmd_context` (`hermes_cli/kanban.py:3155`) → `kb.build_worker_context(conn, task_id)` and prints the resulting string verbatim.
- **Inputs / options:** positional `task_id`; `-h/--help`.
- **Outputs / side effects:** Read-only; prints the assembled context block to stdout. Return 0.
- **Config / env:** n/a
- **Edge cases / guards:** No `--json`; the output is prose by design. An unknown id relies on `build_worker_context` to raise (surfaced as `kanban: <exc>`).
- **Rebuild notes:** One assembler shared with the dispatcher, so what you print is what the worker gets. Better: mark the sections (title/body/parent results/comments) with stable delimiters for tooling.

### `hermes kanban specify` — triage → todo via auxiliary LLM  `id: cli-c.kanban-specify`
- **Surface:** CLI
- **Where:** `hermes kanban specify [task_id] [--all] [--tenant TENANT] [--author AUTHOR] [--json]`. Help: `Flesh out a triage-column task into a concrete spec (title + body) and promote it to todo. Uses the auxiliary LLM configured under auxiliary.triage_specifier.`
- **What it does:** Turns a rough triage card into a concrete, actionable spec (rewriting title and body) and promotes it to `todo`.
- **How it works:** `_cmd_specify` (`hermes_cli/kanban.py:3162`), a thin wrapper over `hermes_cli.kanban_specify`: `spec.list_triage_ids(tenant=…)` for `--all`, then `spec.specify_task(tid, author=…)` per id returning an outcome with `ok`, `reason`, `task_id`, `new_title`.
- **Inputs / options:** positional optional `task_id` (`nargs="?"`, default None) — "Task id to specify (required unless --all is given)"; `--all` (store_true, dest `all_triage`) — "Specify every task currently in the triage column"; `--tenant TENANT` (None) — "When used with --all, restrict the sweep to this tenant"; `--author AUTHOR` (None) — "Author name recorded on the audit comment (default: $HERMES_PROFILE or 'specifier')"; `--json` (store_true) — "Emit one JSON object per task on stdout"; `-h/--help`.
- **Outputs / side effects:** Rewrites the task's title/body, promotes it to `todo`, and records an audit comment. JSON: **one object per line** (not an array) `{task_id, ok, reason, new_title}`; the empty `--all` case emits `{"specified": 0, "total": 0}`. Human: `Specified <task_id> → todo[ — retitled: '<new_title>']` per success; `kanban: specify <task_id>: <reason>` on stderr per failure; the empty `--all` case prints `No triage tasks[ for tenant '<t>'].`
- **Config / env:** `auxiliary.triage_specifier` (the auxiliary LLM used).
- **Edge cases / guards:** Both a task id and `--all` → stderr `kanban: pass either a task id OR --all, not both` exit 2. Neither → `kanban: specify requires a task id or --all` exit 2. Exit codes: single-id mode returns 0 only when exactly one succeeded, else 1; `--all` returns 0 when **at least one** promotion landed (or there were no candidates) and 1 only when every candidate failed — "an honest signal for scripts".
- **Rebuild notes:** Auxiliary-LLM rewrite + status promotion + audit comment. Better: show a diff of the rewritten title/body before committing (a `--dry-run`).

### `hermes kanban decompose` — triage → child-task graph  `id: cli-c.kanban-decompose`
- **Surface:** CLI
- **Where:** `hermes kanban decompose [task_id] [--all] [--tenant TENANT] [--author AUTHOR] [--json]`. Help: `Decompose a triage-column task into a graph of child tasks routed to specialist profiles by description. Falls back to specify-style single-task promotion when the task doesn't benefit from fan-out. Uses auxiliary.kanban_decomposer.`
- **What it does:** Fans a triage card out into child tasks assigned to specialist profiles, or — when fan-out would not help — behaves like `specify`.
- **How it works:** `_cmd_decompose` (`hermes_cli/kanban.py:3235`), a thin wrapper over `hermes_cli.kanban_decompose`: `decomp.list_triage_ids(tenant=…)` and `decomp.decompose_task(tid, author=…)` returning an outcome with `ok`, `reason`, `fanout`, `child_ids`, `new_title`.
- **Inputs / options:** positional optional `task_id` (`nargs="?"`, default None) — "Task id to decompose (required unless --all is given)"; `--all` (store_true, dest `all_triage`) — "Decompose every task currently in the triage column"; `--tenant TENANT` (None) — "When used with --all, restrict the sweep to this tenant"; `--author AUTHOR` (None) — "Author name recorded on the audit comment (default: $HERMES_PROFILE or 'decomposer')"; `--json` (store_true) — "Emit one JSON object per task on stdout"; `-h/--help`.
- **Outputs / side effects:** Creates child tasks + links and promotes the root to `todo`. JSON: one object per line `{task_id, ok, reason, fanout, child_ids, new_title}`; the empty `--all` case emits `{"decomposed": 0, "total": 0}`. Human, fan-out case: `Decomposed <task_id> → <n> children (<id, id, …>); root promoted to todo`; no-fanout case: `Specified <task_id> → todo (no fanout)[ — retitled: '<new_title>']`; failures: `kanban: decompose <task_id>: <reason>` on stderr; empty sweep: `No triage tasks[ for tenant '<t>'].`
- **Config / env:** `auxiliary.kanban_decomposer`; `kanban.auto_decompose` (true) and `kanban.auto_decompose_per_tick` (3) let the dispatcher run this automatically.
- **Edge cases / guards:** Same both/neither argument errors and the same exit-code policy as `specify`.
- **Rebuild notes:** LLM-planned fan-out with profile routing by description, plus a graceful single-task fallback. Better: cap the fan-out width and require confirmation above a threshold.

### `hermes kanban gc` — garbage-collect workspaces, events and logs  `id: cli-c.kanban-gc`
- **Surface:** CLI
- **Where:** `hermes kanban gc [--event-retention-days EVENT_RETENTION_DAYS] [--log-retention-days LOG_RETENTION_DAYS]`. Help: `Garbage-collect archived-task workspaces, old events, and old logs`.
- **What it does:** Frees disk: removes archived tasks' scratch workspaces (and clean, fully-pushed worktrees), prunes old event rows for terminal tasks, and deletes old worker logs.
- **How it works:** `_cmd_gc` (`hermes_cli/kanban.py:3316`): selects `id, workspace_kind, workspace_path, branch_name FROM tasks WHERE status = 'archived'`. Worktree tasks go through `kb._cleanup_worktree_workspace(id, path, branch)` — a backstop for worktrees that escaped the completion/archive hook, using the same safety predicate (**only clean, fully-pushed worktrees are removed**). Scratch tasks resolve their path and are `shutil.rmtree`'d only after `path.relative_to(scratch_root.resolve())` succeeds — a hard guard that never deletes outside the scratch root. Then `kb.gc_events(conn, older_than_seconds=event_days * 86400)` and `kb.gc_worker_logs(older_than_seconds=log_days * 86400)`.
- **Inputs / options:** `--event-retention-days EVENT_RETENTION_DAYS` (int, default **30**) — "Delete task_events older than N days for terminal tasks (default: 30)"; `--log-retention-days LOG_RETENTION_DAYS` (int, default **30**) — "Delete worker log files older than N days (default: 30)"; `-h/--help`.
- **Outputs / side effects:** Deletes directories, event rows and log files. Prints `GC complete: <n> workspace(s), <n> event row(s), <n> log file(s) removed`. Return 0.
- **Config / env:** `HERMES_KANBAN_WORKSPACES_ROOT`.
- **Edge cases / guards:** Path resolution failures (`OSError`) skip the entry. Non-scratch, non-worktree kinds (e.g. `dir:`) are skipped entirely — a user-supplied directory is never deleted. No `--dry-run`.
- **Rebuild notes:** Containment-checked rmtree + two retention sweeps. Better: add `--dry-run` and report reclaimed bytes.

### `hermes kanban repair` — DB integrity check and index repair  `id: cli-c.kanban-repair`
- **Surface:** CLI
- **Where:** `hermes kanban repair [--json]`. Help: `Check kanban.db integrity and auto-repair index-only corruption`. Description: "Runs PRAGMA integrity_check on the board's DB and reports the result. When the failure consists only of index-scoped errors ('wrong # of entries in index <name>' / 'row N missing from index <name>'), the corrupt file is quarantined to a .corrupt.<hash>.bak sibling first and the damaged indexes are rebuilt with REINDEX — the same narrow auto-repair the connect-time guard applies. Any other corruption class is reported and left untouched (fail-closed). Exits 0 when the DB is healthy or was repaired, non-zero when it is still corrupt."
- **What it does:** Diagnoses and, for the narrow index-only corruption class, repairs the board database.
- **How it works:** `_cmd_repair` (`hermes_cli/kanban.py:3368`) → `kb.repair_db()` returning a report with `status` (`ok` / `repaired` / `missing` / corrupt), `db_path`, `messages`, `post_repair_messages`, `backup_path`, `reindexed`. Dispatched **before** the auto `kb.init_db()` in `kanban_command`, because `init_db()` itself refuses a corrupt DB and would otherwise make every repair attempt fail with "could not initialize database".
- **Inputs / options:** `--json` (store_true) — "Emit the repair report as JSON"; `-h/--help`.
- **Outputs / side effects:** May quarantine the DB to a `.corrupt.<hash>.bak` sibling and run `REINDEX`. JSON: `{status, db_path, messages, post_repair_messages, backup_path, reindexed}` — exit 0 for `ok`/`repaired`/`missing`, else 1. Human: `No kanban DB at <path> — nothing to repair.` (exit 0); `<path>: integrity_check ok — no repair needed.` (exit 0); `<path>: repaired.` + `  reindexed: <names>` + `  pre-repair backup: <path>` + `  integrity_check now ok.` (exit 0); or, to stderr, `<path>: CORRUPT.` + up to 10 `  <line>` messages + optionally `  REINDEX (<names>) attempted but integrity_check is still failing:` and up to 10 `    <line>` post-repair messages (exit non-zero).
- **Config / env:** n/a
- **Edge cases / guards:** Any exception from the probe (locked/busy, unexpected I/O) → stderr `kanban repair: <exc>` exit 1. **Fail-closed**: any corruption class other than index-scoped errors is reported and left untouched.
- **Rebuild notes:** `PRAGMA integrity_check` → classify → quarantine → `REINDEX` → re-check. Better: also offer a `.recover`-based rebuild path behind an explicit flag for non-index corruption.

## Handoffs

- Gateway slash commands `/cron`, `/kanban` (including `/kanban subscribe`, the `boards` sub-commands and the `--board` flag) and `/webhook` — same argument surface as these CLI groups, dispatched in `gateway/slash_commands.py`.
- The `cronjob` **model tool** (`tools/cronjob_tools.py`) and its JSON schema — the agent-facing twin of `hermes cron create/update/pause/resume/run/remove`, gated by `cron.allow_agent_scheduling`.
- The `kanban_*` model toolset used by dispatcher-spawned workers: `kanban_show`, `kanban_complete`, `kanban_request_review`, `kanban_request_changes`, `kanban_block`, `kanban_create`, `kanban_link`, `kanban_comment`, `kanban_heartbeat`, plus `kanban_list` and `kanban_unblock` for orchestrator profiles.
- `hermes gateway` (install / install --system / start / restart / run / setup / status) — the process that hosts both the cron ticker and the embedded kanban dispatcher.
- `hermes auth add nous --type oauth`, `hermes setup --portal`, `hermes model` and `_model_flow_nous` — the shared Nous onboarding flow `hermes portal login` delegates to.
- `hermes tools` and the Tool Gateway feature itself (web / image_gen / tts / browser / modal routing) — `hermes portal tools` only lists it.
- `hermes skills` and the skill curation layer (`tools/skill_usage.py`: `set_sync`, `is_curation_eligible`, the `.usage.json` sidecar) that `hermes sync enable/disable` writes to.
- The low-level Skill Sync wire contract in `tools/skills_sync_client.py` (object model, `/v1/sync/` endpoints, `SyncClient`, three-way merge, org mirror `_org/<org_id>/`) beyond what the CLI exposes.
- `hermes profile` / `hermes -p <name> setup` — how the profiles that appear as kanban assignees are created.
- The api_server platform endpoints `hermes peer` speaks to: `GET /api/sessions`, `POST /api/sessions`, `POST /api/sessions/{id}/chat`, `POST /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/stop`, `GET /v1/capabilities` (incl. `features.runs_idempotency`).
- `hermes_cli/urllib_security.open_credentialed_url` — the cross-origin-redirect header-stripping helper every peer request goes through.
- The kanban diagnostics rule engine (`hermes_cli/kanban_diagnostics.py`): the full catalogue of diagnostic kinds, severities, `SEVERITY_ORDER`, actions and `config_from_runtime_config` keys.
- `hermes_cli/kanban_transfer.py` — the board export/import archive format, its manifest and the sanitisation rules.
- `hermes_cli/kanban_swarm.py` — `parse_worker_arg` grammar and `create_swarm` graph shape.
- `hermes_cli/kanban_specify.py` / `hermes_cli/kanban_decompose.py` and the `auxiliary.triage_specifier` / `auxiliary.kanban_decomposer` / `auxiliary.goal_judge` model configuration.
- `hermes_cli/goals.py:judge_goal` and goal-loop worker execution (`--goal`, `--goal-max-turns`).
- The Web dashboard Cron, Kanban (with its `?board=` query param), Projects and Diagnostics pages, and the Desktop app's project/session grouping.
- The full config-key reference for `cron.*`, `kanban.*`, `sync.*`, `auxiliary.*`, `platforms.webhook.*` and `bot_peers` — named here, defined in the config shards.
- Environment-variable reference entries for `HERMES_KANBAN_*`, `HERMES_SYNC_*`, `HERMES_PEER_<NAME>_KEY`, `HERMES_ACCEPT_HOOKS`, `WEBHOOK_*`.
- `plugins/cron_providers/<name>/` provider authoring (the `CronScheduler` ABC, `is_available()`, `start()`), and the Chronos provider itself.
- `hermes hooks` and the shell-hook approval model behind `--accept-hooks`.
- `hermes gateway setup` (the wizard referenced by the webhook setup hint) and the webhook HTTP adapter that serves `/webhooks/<name>` and validates `X-Hub-Signature-256`.
