# Automation — cron, loops, heartbeat, goals, kanban, projects, worktrees, hosted rooms, runs API, peers, webhooks, send

This shard documents everything Hermes Agent v2026.8.31 does *without a human typing the next
message*: the durable cron scheduler (jobs, monitor mode, no-agent scripts, incidents, notepad,
executions ledger, blueprints, suggestions, scheduler providers), autonomous `/loop` ticking, the
gateway `/heartbeat` idle pulse, `/goal` + `/subgoal` + `/refine` goal-decomposition, the Kanban
board model (states, review flow, dispatch daemon, swarm, assignees, attachments, notify
subscriptions, cross-board transfer), projects, git worktrees, hosted rooms (replicas, peers,
policy checkpoints, execution policy, links, discussion), the aiohttp API-server platform
(`/v1/runs` lifecycle, OpenAI compat, sessions/jobs/artifacts/browser-control/room-members),
bot-to-bot `hermes peer`, dynamic `hermes webhook`, and `hermes send`.
Deliberately left to sibling shards: the JSON schemas of the `cronjob` / `kanban_*` / `desktop_project`
model tools (tools shard), the dashboard's Automations/Kanban/Webhooks React pages and their i18n
strings (web-* shards), the Desktop app's scheduler dialogs (desktop-* shards), the TUI's automation
panes (tui shard), gateway slash-command dispatch mechanics (gw-slash), the `delegation.*` /
subagent engine (agent-core), and every config key's own entry (config-* shards).

---

## 1. Cron — durable scheduled jobs

### `hermes cron` (command group)  `id: automation.cli-cron-group`
- **Surface:** CLI
- **Where:** `hermes cron [--accept-hooks] {list,create,add,edit,pause,resume,run,remove,rm,delete,status,runs,history,incidents,notepad,doctor,tick}`; help header reads verbatim `Manage scheduled tasks`.
- **What it does:** Top-level entry point for Hermes' built-in scheduler. Every scheduled automation (agent-driven prompt, plain script watchdog, change monitor) is a *job* created, inspected and mutated through this group.
- **How it works:** `hermes_cli/cron.py` is the argparse layer; it never touches storage directly — it goes through `tools/cronjob_tools.py::cronjob` (`hermes_cli/cron.py:46` `_cron_api`) or straight through `cron/jobs.py`. Storage is a single JSON file per profile: `<HERMES_HOME>/cron/jobs.json` (`cron/jobs.py:123` `_CronStorePaths`, resolved per execution context at `cron/jobs.py:142` `_current_cron_store`), plus `<HERMES_HOME>/cron/output/<job_id>/` for per-run stdout snapshots, `<HERMES_HOME>/cron/executions.db` (SQLite: `executions` + `cron_incidents` tables) and `<HERMES_HOME>/cron/notepad.db` (`cron_notepad`). Writes take an in-process `threading.RLock` **and** a cross-process `flock` on `<cron_dir>/.jobs.lock` with a 30 s cap (`cron/jobs.py:116` `_JOBS_LOCK_TIMEOUT_SECONDS`). The *firing* half lives in `cron/scheduler.py` (`tick()` at `cron/scheduler.py:7829`), which the gateway runs on a 60 s daemon ticker.
- **Inputs / options:** `-h, --help`; `--accept-hooks` — "Auto-approve unseen shell hooks without a TTY prompt (equivalent to HERMES_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."; then exactly one sub-command from the list above (aliases: `add`→`create`, `rm`/`delete`→`remove`, `history`→`runs`).
- **Outputs / side effects:** Reads/writes `jobs.json`, `executions.db`, `notepad.db`, `output/`. Sub-commands that mutate jobs call `_notify_provider_jobs_changed()` (`cron/scheduler.py:7662`) so an external scheduler provider re-syncs.
- **Config / env:** `cron.*` tree (`cron.allow_agent_scheduling`, `cron.preflight`, `cron.model_drift_guard`, `cron.model`, `cron.model_provider`, `cron.provider`, `cron.chronos.portal_url`, `cron.chronos.callback_url`, `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`, `cron.wrap_response`, `cron.mirror_delivery`, `cron.max_parallel_jobs`, `cron.output_retention`, `cron.script_timeout_seconds`, `cron.session_db_timeout_seconds`, `cron.media_send_timeout_seconds`); env `HERMES_HOME`, `HERMES_ACCEPT_HOOKS`, `HERMES_CRON_TIMEOUT`, `HERMES_CRON_MAX_PARALLEL`, `HERMES_CRON_SCRIPT_TIMEOUT`, `HERMES_CRON_MEDIA_SEND_TIMEOUT`, `HERMES_CRON_SESSION_DB_TIMEOUT`, `HERMES_CRON_DRAIN_TIMEOUT`, `HERMES_CRON_INFLIGHT_MAX_MINUTES`, `HERMES_CRON_SESSION`, `HERMES_CRON_AUTO_DELIVER_PLATFORM`, `HERMES_CRON_AUTO_DELIVER_CHAT_ID`, `HERMES_CRON_AUTO_DELIVER_THREAD_ID`.
- **Edge cases / guards:** There is **no standalone cron daemon** — the built-in ticker only exists inside the gateway process; `_warn_if_gateway_not_running()` (`hermes_cli/cron.py:110`) prints `  ⚠  Gateway is not running — jobs won't fire automatically.` / `     Start it with: hermes gateway install` / `     sudo hermes gateway install --system  # Linux servers` / `     Check status:  hermes cron status` at create/list time. The warning is suppressed for any non-builtin `cron.provider` (`hermes_cli/cron.py:67` `_builtin_gateway_liveness` returns True for external providers), and liveness is probed via the gateway runtime lock → `find_gateway_pids()` → `named_profile_served_by_running_multiplexer()`.
- **Rebuild notes:** Minimum viable clone = JSON job store + flock + a 60 s ticker that computes `next_run_at` and dispatches. The non-obvious value is everything around it: a fire-claim fence so two processes can't run the same job, a durable ledger, and provider pluggability. A better version would make the store a single SQLite DB (jobs + executions + incidents + notepad) so the flock dance disappears, and would expose the ticker as a systemd/launchd timer so jobs fire without the gateway alive.

### `hermes cron list`  `id: automation.cli-cron-list`
- **Surface:** CLI
- **Where:** `hermes cron list [--all]`; help `List scheduled jobs`.
- **What it does:** Prints every scheduled job with its id, state, name, schedule, repeat counter, next run time, delivery targets and skills.
- **How it works:** `hermes_cli/cron.py:136` `cron_list()` → `cron.jobs.list_jobs(include_disabled=show_all)` (`cron/jobs.py:2502`). State comes from `effective_job_state(job)` (`cron/jobs.py:639`) so a "half-paused" record (paused marker set but `enabled=true`) never renders as frozen. `deliver` and `repeat` are coalesced with `or {}` / `or ["local"]` because they can be present-but-null in the JSON.
- **Inputs / options:** `-h, --help`; `--all` — "Include disabled jobs".
- **Outputs / side effects:** stdout only. Empty store prints `No scheduled jobs.` then `Create one with 'hermes cron create ...' or the /cron command in chat.`. Otherwise a cyan box drawn with `┌───…┐` / `│                         Scheduled Jobs                                  │` / `└───…┘`, then per job: `  <id> [active]|[paused]|[completed]|[disabled]`, `    Name:      <name>` (default `(unnamed)`), `    Schedule:  <schedule_display>`, `    Repeat:    <completed>/<times>` or `∞`, `    Next run:  <next_run_at>`, `    Deliver:   <comma-joined targets>`, `    Skills:    <comma-joined>` (only when set), plus script/workdir/model lines when present. Ends by calling `_warn_if_gateway_not_running()`.
- **Config / env:** n/a beyond `HERMES_HOME` / profile selection.
- **Edge cases / guards:** `--all` is the only way to see `enabled=false` jobs. Colors come from `hermes_cli/colors.py` and degrade when not a TTY.
- **Rebuild notes:** Straight table render over the job store. A better version would show last status + failure streak inline and colour-code overdue `next_run_at`.

### `hermes cron create` (alias `add`)  `id: automation.cli-cron-create`
- **Surface:** CLI
- **Where:** `hermes cron create <schedule> [prompt] [flags]`; help `Create a scheduled job`.
- **What it does:** Creates one scheduled job. The job can be (a) an LLM prompt run on a schedule, (b) a pure script run with no LLM (`--no-agent`), or (c) an LLM job gated by a change monitor (`--monitor-script` / `--monitor-url`).
- **How it works:** argparse in `hermes_cli/cron.py`; the actual record is minted by `cron/jobs.py:2207` `create_job()`. Sequence: `parse_schedule()` → `normalize_repeat_value()` → one-shot schedules default `repeat=1` → `deliver` defaults to `origin` when an origin dict exists else `local` → `job_id = uuid4().hex[:12]` → `_validate_job_mode_invariants()` (monitor sources mutually exclusive; monitor incompatible with `no_agent`; `no_agent` requires a script) → `check_gateway_lifecycle(prompt, script)` (`cron/lifecycle_guard.py:1199`) → `_compute_provider_model_snapshots()` records the resolved provider/model for unpinned jobs → `compute_next_run()` → append under `_jobs_lock()` → `save_jobs()`.
- **Inputs / options:** positional `schedule` — "Schedule like '30m', 'every 2h', or '0 9 * * *'"; positional optional `prompt` — "Optional self-contained prompt or task instruction". Flags, all 13: `-h, --help`; `--name NAME` "Optional human-friendly job name"; `--deliver DELIVER` "Delivery target: origin, local, telegram, discord, signal, platform:chat_id, or bot-chat[:profile] (inject output into a local profile's canonical Bot Chat as a message the bot responds to)"; `--repeat REPEAT` "Optional repeat count"; `--skill SKILLS` "Attach a skill. Repeat to add multiple skills."; `--script SCRIPT` "Path to a script under ~/.hermes/scripts/. Default mode: script stdout is injected into the agent's prompt each run. With --no-agent: the script IS the job and its stdout is delivered verbatim. .sh/.bash files run via bash, everything else via Python."; `--no-agent` "Skip the LLM entirely — run --script on schedule and deliver its stdout directly. Empty stdout = silent. Classic watchdog pattern (memory alerts, disk alerts, CI pings)."; `--monitor-script MONITOR_SCRIPT`; `--monitor-url MONITOR_URL`; `--workdir WORKDIR` "Absolute path for the job to run from. Injects AGENTS.md / CLAUDE.md / .cursorrules from that directory and uses it as the cwd for terminal/file/code_exec tools."; `--model MODEL` "Pin this job to a specific inference model (user-owned; the agent's cronjob tool cannot set this)."; `--provider MODEL_PROVIDER` "Inference provider paired with --model (e.g. 'openrouter', 'nous')."; `--reasoning-effort REASONING_EFFORT` "Pin this job's reasoning (thinking) effort: none, minimal, low, medium, high, xhigh, max, or ultra."; `--continuity` "Each run wakes up with the job's own previous output injected into its prompt… First run is unchanged."
- **Outputs / side effects:** Appends one record to `jobs.json`; prints the created job id, name, schedule and next run; runs the gateway-liveness warning. Also notifies the active scheduler provider that jobs changed.
- **Config / env:** `cron.model`, `cron.model_provider` supply the default when `--model`/`--provider` are omitted; `cron.allow_agent_scheduling` gates the equivalent *agent-initiated* path (not this CLI); `agent.reasoning_effort` / `agent.reasoning_overrides` are overridden by `--reasoning-effort`.
- **Edge cases / guards:** Empty payload (no prompt, no script, no skills) raises `EMPTY_PAYLOAD_ERROR`. A one-shot whose `run_at` is more than `ONESHOT_GRACE_SECONDS = 120` s in the past is rejected with `Requested one-shot time <t> is more than 120s in the past and cannot be scheduled.` (`cron/jobs.py:2380`). Gateway-lifecycle commands (`hermes gateway restart|stop|uninstall`, `launchctl … hermes-gateway`, `systemctl … hermes-gateway`, `pkill` at the gateway) in the prompt *or* the referenced script are rejected with `GatewayLifecycleBlocked`. `--monitor-script` and `--monitor-url` are mutually exclusive and neither may combine with `--no-agent`. `--no-agent` without a script is rejected.
- **Rebuild notes:** The three job *modes* (agent / no-agent script / monitored agent) are the design core — implement them as one record with `script`, `no_agent`, `monitor_script`, `monitor_url` fields and validate the invariants in one function shared by create and update. A better version would validate script existence and shebang at create time and dry-run the first monitor fetch.

### `hermes cron edit`  `id: automation.cli-cron-edit`
- **Surface:** CLI
- **Where:** `hermes cron edit <job_id> [flags]`; help `Edit an existing scheduled job`.
- **What it does:** Mutates any field of an existing job in place, including toggling agent/no-agent and continuity on and off, and adding/removing individual skills.
- **How it works:** Builds an `updates` dict and calls `cron/jobs.py:2518` `update_job(job_id, updates)`, which re-runs `parse_schedule` when `schedule` changes, re-normalizes repeat/model/provider/reasoning, re-validates the mode invariants via `_validate_job_mode_invariants`, and recomputes `next_run_at`. Skill list edits funnel through `_normalize_skill_list`.
- **Inputs / options:** positional `job_id`; flags, all 18: `-h, --help`; `--schedule SCHEDULE` "New schedule"; `--prompt PROMPT` "New prompt/task instruction"; `--name NAME` "New job name"; `--deliver DELIVER` "New delivery target"; `--repeat REPEAT` "New repeat count"; `--skill SKILLS` "Replace the job's skills with this set. Repeat to attach multiple skills."; `--add-skill ADD_SKILLS` "Append a skill without replacing the existing list. Repeatable."; `--remove-skill REMOVE_SKILLS` "Remove a specific attached skill. Repeatable."; `--clear-skills` "Remove all attached skills from the job"; `--script SCRIPT` (pass empty string to clear); `--no-agent` "Enable no-agent mode on this job (requires --script or an existing script on the job)."; `--agent` "Disable no-agent mode on this job (reverts to LLM-driven execution)."; `--continuity` "Turn on run-to-run continuity…"; `--no-continuity` "Turn off run-to-run continuity (other context_from job refs are preserved)."; `--monitor-script MONITOR_SCRIPT` (empty string clears); `--monitor-url MONITOR_URL` (empty string clears); `--workdir WORKDIR` (empty string clears); `--model MODEL` (empty string clears the pin); `--provider MODEL_PROVIDER` (empty clears); `--reasoning-effort REASONING_EFFORT` (empty clears).
- **Outputs / side effects:** Rewrites the job record atomically; prints the updated job. Notifies the scheduler provider.
- **Config / env:** same as create.
- **Edge cases / guards:** `--no-agent` fails when the job has no script and none is supplied in the same call. `--continuity` is implemented as a self-reference in `context_from`, so `--no-continuity` removes only the self-ref and keeps other chained job ids. Empty-string semantics ("pass empty string to clear") apply to `--script`, `--monitor-script`, `--monitor-url`, `--workdir`, `--model`, `--provider`, `--reasoning-effort`.
- **Rebuild notes:** Clear/append/remove triples per list field is the pattern worth copying (`--skill` replace vs `--add-skill`/`--remove-skill`/`--clear-skills`). A better version would support `--dry-run` printing the resulting record diff.

### `hermes cron pause`  `id: automation.cli-cron-pause`
- **Surface:** CLI
- **Where:** `hermes cron pause <job_id>`; help `Pause a scheduled job`.
- **What it does:** Stops a job from firing without deleting it.
- **How it works:** `cron/jobs.py:2704` `pause_job(job_id, reason=None)` sets `state="paused"`, `paused_at=<now>`, `paused_reason=<reason>` and clears the scheduler's arming so `get_due_jobs()` skips it. `effective_job_state()` derives the displayed state from these fields plus `enabled`.
- **Inputs / options:** positional `job_id`; `-h, --help`.
- **Outputs / side effects:** Job record updated in `jobs.json`; confirmation on stdout.
- **Config / env:** n/a.
- **Edge cases / guards:** Pausing a job already running does not kill the in-flight run; it takes effect from the next tick.
- **Rebuild notes:** Keep pause as data (`state` + `paused_at` + `paused_reason`), not deletion, so the resume path can re-arm deterministically.

### `hermes cron resume`  `id: automation.cli-cron-resume`
- **Surface:** CLI
- **Where:** `hermes cron resume [--at RUN_AT] [--run-now] <job_id>`; help `Resume a paused job`.
- **What it does:** Un-pauses a job, optionally re-arming a one-shot to a specific instant or to fire immediately.
- **How it works:** `cron/jobs.py:2720` `resume_job()` clears the pause fields and recomputes `next_run_at` from the schedule; `--at`/`--run-now` route to `cron/jobs.py:2797` `rearm_oneshot(job_id, run_at)` which also clears any stale run-claim (`_claim_is_live` with the one-shot claim TTL).
- **Inputs / options:** positional `job_id`; `-h, --help`; `--at RUN_AT` "Re-arm at an ISO-8601 time"; `--run-now` "Re-arm to run now".
- **Outputs / side effects:** Job record updated; the job becomes due at the computed time.
- **Config / env:** n/a.
- **Edge cases / guards:** A completed one-shot (repeat exhausted) needs `--at`/`--run-now` to become due again. Re-arming to a past time is bounded by the same 120 s grace window used at create.
- **Rebuild notes:** Model "resume" and "re-arm" as distinct operations; resume alone must not silently fire a job whose window elapsed weeks ago.

### `hermes cron run`  `id: automation.cli-cron-run`
- **Surface:** CLI
- **Where:** `hermes cron run [--accept-hooks] <job_id>`; help `Run a job on the next scheduler tick`.
- **What it does:** Marks a job to fire at the next tick (a manual trigger) rather than executing it inline.
- **How it works:** `cron/jobs.py:2745` `trigger_job()` sets the job's `next_run_at` to now (and clears any suppression), so the gateway ticker picks it up within 60 s. When the resolved provider supports force-fire (`provider_supports_force_fire`, `cron/scheduler_provider.py:266`) the provider is asked to fire immediately instead.
- **Inputs / options:** positional `job_id` "Job ID to trigger"; `-h, --help`; `--accept-hooks`.
- **Outputs / side effects:** Job's `next_run_at` moved to now; the run then behaves exactly like a scheduled run (same delivery, same ledger entry).
- **Config / env:** `HERMES_ACCEPT_HOOKS`, `hooks_auto_accept`.
- **Edge cases / guards:** Without a live gateway (builtin provider) nothing fires — the command is a scheduling hint, not an executor. `hermes cron tick` is the way to run due jobs in the foreground.
- **Rebuild notes:** Separating "trigger" (mark due) from "tick" (execute due) keeps a single execution path; do not add a second inline executor.

### `hermes cron remove` (aliases `rm`, `delete`)  `id: automation.cli-cron-remove`
- **Surface:** CLI
- **Where:** `hermes cron remove <job_id>` / `hermes cron rm <job_id>` / `hermes cron delete <job_id>`; help `Remove a scheduled job`.
- **What it does:** Permanently deletes a job and its per-job state.
- **How it works:** `cron/jobs.py:2851` `remove_job()` drops the record under the jobs lock and calls `cron.notepad.clear_notepad(job_id)` so notepad rows are not orphaned; the job's `output/<job_id>/` directory and its `executions.db` rows remain as audit history.
- **Inputs / options:** positional `job_id` "Job ID to remove"; `-h, --help`.
- **Outputs / side effects:** Record removed from `jobs.json`; notepad rows deleted; provider notified.
- **Config / env:** n/a.
- **Edge cases / guards:** Removing a job that is currently running does not abort the run.
- **Rebuild notes:** Cascade only the state that is meaningless without the job (notepad); keep the audit ledger.

### `hermes cron status`  `id: automation.cli-cron-status`
- **Surface:** CLI
- **Where:** `hermes cron status`; help `Check if cron scheduler is running`.
- **What it does:** Reports whether the scheduler trigger is alive and healthy — ticker heartbeat age, last successful tick, catch-up occurrences and the last ticker error.
- **How it works:** Reads the ticker heartbeat epoch files written by `cron/jobs.py:1486` `record_ticker_heartbeat(success=…)` (`get_ticker_heartbeat_age()` at `:1522`, `get_ticker_success_age()` at `:1536`), the catch-up counter (`record_catch_up_occurrence` / `get_catch_up_occurrence_count`, `:1547`/`:1595`) and the last error (`record_ticker_error` / `get_ticker_last_error`, `:1560`/`:1613`), plus the resolved provider name via `resolve_cron_scheduler()`.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** stdout report; no writes.
- **Config / env:** `cron.provider`.
- **Edge cases / guards:** All heartbeat state is per-profile under `<HERMES_HOME>/cron/`; a satellite profile served by the default multiplexer reports through `named_profile_served_by_running_multiplexer()`.
- **Rebuild notes:** Persist heartbeat as tiny atomic epoch files (not in the jobs JSON) so status never contends on the jobs lock.

### `hermes cron runs` (alias `history`)  `id: automation.cli-cron-runs`
- **Surface:** CLI
- **Where:** `hermes cron runs [--limit LIMIT] [job_id]`; help `Show durable execution attempts`.
- **What it does:** Lists rows from the durable execution ledger — every claimed/running/completed/failed/unknown attempt, optionally filtered to one job.
- **How it works:** `cron/executions.py:242` `list_executions()` over the SQLite table `executions(id, job_id, source, process_id, pid, process_started_at, status, claimed_at, started_at, finished_at, error)` in `<HERMES_HOME>/cron/executions.db` (WAL with fallback, `PRAGMA synchronous=FULL`, `busy_timeout=5000`). Indexes: `idx_executions_job_claimed(job_id, claimed_at DESC, id DESC)` and `idx_executions_status_claimed(status, claimed_at DESC, id DESC)`.
- **Inputs / options:** positional optional `job_id` "Optional job ID filter"; `-h, --help`; `--limit LIMIT` "Rows to show (1-500)".
- **Outputs / side effects:** stdout table; read-only.
- **Config / env:** `EXECUTIONS_FILE` module override exists for tests only.
- **Edge cases / guards:** Status is CHECK-constrained to `('claimed','running','completed','failed','unknown')`. Terminal states are immutable. Interrupted attempts become `unknown` only after `recover_interrupted_executions()` (`cron/executions.py:205`) proves the exact owner process is gone (pid + process start time). Ledger is pruned to `MAX_TERMINAL_EXECUTIONS = 1000` terminal rows.
- **Rebuild notes:** The pid+start-time ownership proof is the subtle part — a bare pid check misclassifies a recycled pid as "still running". A better version would also record the wall-clock duration and the delivery outcome per attempt.

### `hermes cron incidents`  `id: automation.cli-cron-incidents`
- **Surface:** CLI
- **Where:** `hermes cron incidents [list|ack] [incident_id] [--state {detected,alerted,closed}]`; help `List or acknowledge durable cron failure incidents`.
- **What it does:** Groups repeated cron failures into deduplicated incidents so the same job failing the same way does not re-ping forever, and lets the operator acknowledge (close) one.
- **How it works:** `cron/incidents.py`. Table `cron_incidents(id, job_id, error_sig, state, failure_type, first_seen_at, last_seen_at, acked_at, closed_at, error, output_file)` inside the *same* `cron/executions.db`, indexed by `job_id` and `state`. The dedup key is `sha256(job_id + normalized_error[:200])[:12]`; the incident id is `f"{job_id[:6]}_{error_sig}"`. Errors are whitespace-collapsed + lowercased for signing, redacted via `agent.redact.redact_sensitive_text` and truncated to `MAX_ERROR_CHARS = 500` for storage. `failure_type` is classified from keywords in priority order: `rate_limit` (`\b429\b`, "rate limit", "usage limit", "quota"), `timeout` ("timeout", "timed out"), `auth` (`\b401\b`, "unauthorized", "authentication", "auth"), `delivery` ("delivery", "deliver", "delivering"), `config` ("config", "configuration", "validation"), `script` ("script", "no_agent"), `agent` ("agent", "model", "provider", "inference"), else `unknown`. The scheduler upserts on failure via `_upsert_incident_for_failure` (`cron/scheduler.py:467`) and flips to `alerted` via `_mark_incident_alerted` (`:505`) once a ping actually reaches the operator.
- **Inputs / options:** positional optional action `{list,ack}` "Action (default: list)"; positional optional `incident_id` "Incident ID to acknowledge (ack)"; `-h, --help`; `--state {detected,alerted,closed}` "Filter incidents by lifecycle state".
- **Outputs / side effects:** `list` prints incidents newest-activity-first; `ack` sets `state='closed'` with `closed_at`/`acked_at` timestamps.
- **Config / env:** n/a.
- **Edge cases / guards:** Lifecycle is `detected → alerted → closed`; `closed` is terminal for that signature (`set_incident_state` refuses to leave `closed`). Re-opening happens only when the error text changes, which mints a brand-new incident id. Unknown state names are rejected as a no-op returning `False`. `list_incidents(state=<invalid>)` returns `[]` rather than raising.
- **Rebuild notes:** Signature = job + normalized error prefix is the whole trick; without normalization every stack trace becomes a new incident. A better version would cluster by failure_type + job and expose an auto-close on N consecutive successes.

### `hermes cron notepad`  `id: automation.cli-cron-notepad`
- **Surface:** CLI
- **Where:** `hermes cron notepad <job_id> [get|set|delete|list] [key] [value]`; help `Read/write a job's durable notepad (persistent KV across runs)`.
- **What it does:** A tiny per-job key/value scratchpad that survives between scheduled wake-ups (cursors, watermarks, watchlists). Its contents are injected into the job's prompt on every run.
- **How it works:** `cron/notepad.py`. SQLite `<HERMES_HOME>/cron/notepad.db`, table `cron_notepad(job_id, key, value, updated_at, PRIMARY KEY(job_id,key))`, WAL-with-fallback, `busy_timeout=5000`, guarded by a module `threading.RLock`. `render_notepad_section(job_id)` (`cron/notepad.py:169`) emits the prompt block `## Job notepad (persistent across runs)` followed by `- <key>: <value>` lines, and returns `""` when empty so non-users get a byte-identical prompt (prompt-cache safety). There is deliberately **no model tool** — the running agent writes via its terminal tool calling this CLI.
- **Inputs / options:** positional `job_id` "Job ID the notepad belongs to"; positional optional action `{get,set,delete,list}` "Action (default: list)"; positional optional `key` "Notepad key (get/set/delete)"; positional optional `value` "Value to store (set)"; `-h, --help`.
- **Outputs / side effects:** `set` upserts and returns `{job_id, key, value, updated_at}`; `get` prints the value or nothing; `delete` returns whether a row was removed; `list` prints all entries sorted by key. `cron.jobs.remove_job` calls `clear_notepad()`.
- **Config / env:** n/a.
- **Edge cases / guards:** `MAX_KEY_CHARS = 128`; `MAX_VALUE_BYTES = 16 KB` per key (UTF-8 bytes); `MAX_JOB_TOTAL_BYTES = 64 KB` summed over key+value bytes per job. Exceeding the total raises `notepad full: job '<id>' would exceed 65536 bytes total; delete unused keys first` and leaves the store untouched. Empty `job_id` or `key` raise `ValueError`. `clear_notepad` no-ops without creating the DB when the file does not exist.
- **Rebuild notes:** Hard byte caps matter because the notepad is prompt-injected every run — unbounded growth silently inflates every wake-up. A better version would auto-evict least-recently-updated keys instead of hard-failing the write.

### `hermes cron doctor`  `id: automation.cli-cron-doctor`
- **Surface:** CLI
- **Where:** `hermes cron doctor`; help `Check scheduled jobs for common health issues`.
- **What it does:** Static health check over the job store — flags jobs that can never fire or will fire wrongly (missing scripts, broken skills, unreachable delivery targets, dead gateway, provider/model drift).
- **How it works:** Walks `list_jobs(include_disabled=True)` and applies the same preflight predicates the scheduler uses at fire time: `_preflight_check_provider_key` (`cron/scheduler.py:5095`), `_preflight_check_delivery` (`:5203`), `_preflight_check_skills` (`:5268`), `_preflight_job_config` (`:5324`), plus the gateway-liveness probe and `get_ticker_last_error()`.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** stdout diagnosis list; read-only.
- **Config / env:** `cron.preflight` (default `true`) controls whether the same checks run automatically at fire time; `cron.model_drift_guard` (default `true`) controls drift alerts.
- **Edge cases / guards:** Doctor never mutates jobs; the fire-time equivalents can pause a job (`_block_and_pause_job`, `cron/scheduler.py:4941`) when a hard config error is found.
- **Rebuild notes:** Share one predicate set between "doctor" and "preflight at fire time" — divergence there is how a doctor that says OK coexists with jobs that never run.

### `hermes cron tick`  `id: automation.cli-cron-tick`
- **Surface:** CLI
- **Where:** `hermes cron tick [--accept-hooks]`; help `Run due jobs once and exit`.
- **What it does:** Executes every currently-due job in the foreground once, then exits — the manual/CI equivalent of one gateway ticker cycle.
- **How it works:** Calls `cron/scheduler.py:7829` `tick()`. That function: sweeps stale in-flight claims (`sweep_stale_inflight`, `:1053`), gets due jobs (`cron/jobs.py:3656` `get_due_jobs`), claims each for fire (`claim_job_for_fire`, `:3440`, machine-id + pid fenced), runs them (serially or on the shared `ThreadPoolExecutor` from `_get_parallel_pool`, `:1426`), records ledger rows, delivers results, advances `next_run_at`, records the ticker heartbeat, and opportunistically runs worktree maintenance (`_maybe_run_worktree_maintenance`, `:7786`).
- **Inputs / options:** `-h, --help`; `--accept-hooks` "Auto-approve unseen shell hooks without a TTY prompt (equivalent to HERMES_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."
- **Outputs / side effects:** Runs LLM turns and/or scripts, writes `cron/output/<job_id>/*`, appends ledger rows, may upsert incidents, delivers messages to configured targets, updates `last_run_at`/`last_status`/`last_error`/`failure_streak`/`repeat.completed`.
- **Config / env:** `cron.max_parallel_jobs` / `HERMES_CRON_MAX_PARALLEL`; `HERMES_CRON_TIMEOUT` (inactivity watchdog seconds, default 600, `0` = unlimited); `cron.script_timeout_seconds` / `HERMES_CRON_SCRIPT_TIMEOUT` (default 3600); `cron.media_send_timeout_seconds` / `HERMES_CRON_MEDIA_SEND_TIMEOUT` (default 300); `cron.session_db_timeout_seconds` / `HERMES_CRON_SESSION_DB_TIMEOUT` (default 10); `HERMES_CRON_DRAIN_TIMEOUT`; `HERMES_CRON_INFLIGHT_MAX_MINUTES`; `cron.output_retention` (default 50).
- **Edge cases / guards:** `CronTickYielded` (`cron/scheduler.py:209`) aborts the tick when a fresher gateway process should own it (`_should_yield_tick_to_fresh_gateway`, `:248`, logged once by `_log_tick_yield_once`); `_detect_gateway_code_skew` (`:194`) notices a running gateway on older code. fd exhaustion (EMFILE/ENFILE) triggers `_reclaim_fds_best_effort()` and exponential tick backoff capped at 15 min (`cron/scheduler_provider.py:33`).
- **Rebuild notes:** Make the tick idempotent and re-entrant-safe: claim-before-run with an owner fence, and a stale-claim sweeper with an allowance derived from the job's own interval. A better version would emit structured tick telemetry (claimed/ran/skipped/failed counts) per cycle.

### Cron job record (jobs.json schema)  `id: automation.cron-job-record`
- **Surface:** Core
- **Where:** `<HERMES_HOME>/cron/jobs.json` — one JSON array of job objects; also the shape every surface (CLI, dashboard Automations page, `cronjob` tool, TUI) reads and writes.
- **What it does:** Defines what a scheduled job *is*: identity, payload, schedule, delivery, execution mode, inference pins and run bookkeeping.
- **How it works:** Minted in `cron/jobs.py:2207` `create_job()`, normalized on read by `_normalize_job_record` (`cron/jobs.py:583`), saved by `save_jobs` → `_save_jobs_unlocked` (`:1855`) with atomic replace, 0600 perms and ownership preservation (`_preserve_file_ownership`, `:712`). `_merge_unexpected_disk_jobs` (`:1792`) reconciles jobs another process added between this process's load and save.
- **Inputs / options:** Fields, all of them: `id` (12-char uuid4 hex), `name` (defaults to the first 50 chars of prompt/skill/script), `prompt`, `skills` (list), `skill` (legacy first element), `model`, `provider`, `provider_snapshot`, `model_snapshot`, `base_url`, `script`, `no_agent` (bool), `monitor_script`, `monitor_url`, `monitor_state` (`{last_output_hash, last_changed_at}` or null), `context_from` (list of job ids or `"self"`), `schedule` (`{kind: once|interval|cron, run_at|minutes|expr, display}`), `schedule_display`, `repeat` (`{times: int|null, completed: int}`), `enabled` (bool), `state` (`scheduled|paused|completed|error`), `paused_at`, `paused_reason`, `created_at`, `next_run_at`, `last_run_at`, `last_status`, `last_error`, `last_delivery_error`, `failure_streak` (int), `deliver` (string, comma-separated), `origin` (dict capturing where the job was created), `enabled_toolsets` (list or null), `workdir`, plus two conditionally-persisted keys `attach_to_session` (bool) and `reasoning_effort` (string).
- **Outputs / side effects:** The file is the single source of truth; `output/<job_id>/<timestamp>.md` files hold each run's rendered output.
- **Config / env:** `HERMES_HOME` selects the profile store; `use_cron_store(home)` context manager (`cron/jobs.py:174`) re-points it without mutating globals.
- **Edge cases / guards:** Several fields are legitimately *present but null* (`repeat`, `deliver`), so every reader must coalesce rather than rely on `dict.get` defaults — a null `deliver` previously crashed the whole listing. `attach_to_session` and `reasoning_effort` are omitted entirely when unset so pre-existing files stay byte-identical.
- **Rebuild notes:** Keep the parsed schedule *in* the record (not the raw string) so cadence math never re-parses. A better version would version the schema and store jobs in SQLite rows with a JSON payload column.

### Schedule syntax (`parse_schedule`)  `id: automation.cron-schedule-syntax`
- **Surface:** Core / CLI
- **Where:** Any place a schedule string is accepted: `hermes cron create <schedule>`, `hermes cron edit --schedule`, the `cronjob` tool's `schedule` field, the dashboard's schedule input, `/cron` in chat.
- **What it does:** Turns a human schedule string into `{kind, …}`. Supports five families: recurring interval, one-shot delay, natural weekday/time phrases, raw cron expressions and ISO timestamps.
- **How it works:** `cron/jobs.py:962` `parse_schedule()`. Order of attempts: (1) `every …` prefix → try `_natural_every_to_cron` (`:906`) else `parse_duration` → interval; (2) a bare natural phrase without `every` (`weekdays at 9am`, `monday at 9:30`, `daily at 7am`) → same helper; (3) 5+ space-separated fields matching `^[A-Za-z\d\*\-,/]+$` → validated by `croniter` (named months/weekdays such as `MON-FRI` supported); (4) contains `T` or starts `YYYY-MM-DD` → `datetime.fromisoformat`, naive values stamped with the **configured Hermes timezone** not the server's; (5) `in <duration>` → one-shot at now+duration; (6) bare duration → recurring interval.
- **Inputs / options:** `parse_duration` (`cron/jobs.py:828`) regex `^(\d*)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$`, multipliers m=1, h=60, d=1440, bare unit ⇒ value 1 (`hour` = 60). Weekday map (`_WEEKDAY_TO_CRON_DOW`): sunday/sun=0, monday/mon=1, tuesday/tue/tues=2, wednesday/wed/weds=3, thursday/thu/thur/thurs=4, friday/fri=5, saturday/sat=6. Keyword day-specs (`_DAYSPEC_TO_CRON_DOW`): day/daily/everyday=`*`, weekday/weekdays=`1-5`, weekend/weekends=`0,6`. Clock parser `_parse_clock_time` (`:874`) accepts `9am`, `9:30am`, `9 am`, `14:00`, bare 24-h hour `7`, `noon`, `midday`, `midnight`; am/pm requires hour 1–12; rejects hour>23 or minute>59. Multi-day lists work: `every monday, wednesday at 9am` → `0 9 * * 1,3`; the separator `and` is skipped.
- **Outputs / side effects:** Returns `{"kind":"interval","minutes":N,"display":"every Nm"}`, `{"kind":"cron","expr":…,"display":<original>}`, or `{"kind":"once","run_at":<iso>,"display":"once at YYYY-MM-DD HH:MM"|"once in <duration>"}`.
- **Config / env:** Timezone comes from the Hermes-configured zone via `hermes_time.now()`.
- **Edge cases / guards:** `croniter` is an optional dependency — cron/weekday schedules raise `Cron expressions require 'croniter' package. Install with: pip install croniter` when missing. A bare duration like `30m` is **recurring** (documented contract; a 2026-08-04 fix — it used to silently create a one-shot); explicit one-shot-by-duration is `in 30m`. Failure message enumerates all five forms verbatim: `- Interval: '30m', 'every 30m', 'every 2h' (recurring)` / `- One-shot delay: 'in 30m', 'in 2h' (fires once)` / `- Weekly/daily: 'every monday 9am', 'weekdays at 9am' (recurring)` / `- Cron: '0 9 * * *' (cron expression)` / `- Timestamp: '2026-02-03T14:00:00' (one-shot at time)`.
- **Rebuild notes:** Do the natural-language pass *before* the cron-field pass, and anchor naive timestamps to the app's configured timezone, not the host's — that single choice removes the biggest class of "fires at the wrong hour" bugs.

### `repeat` normalization  `id: automation.cron-repeat`
- **Surface:** Core / CLI / Tool
- **Where:** `--repeat` on create/edit; `repeat` field of the `cronjob` tool; `Repeat:` column in `hermes cron list`.
- **What it does:** Controls how many times a job runs before it is done.
- **How it works:** `cron/jobs.py:798` `normalize_repeat_value()` is the single chokepoint. `'forever' | 'infinite' | 'inf' | 'none' | ''` → `None` (infinite); `'once' | 'one' | '1x'` → `1`; numeric strings → int; `0` or negative → `None`; anything else raises `Invalid repeat value <x>: use an integer, 'forever', or 'once'.` One-shot schedules default `repeat=1` when unspecified. Stored as `{"times": N|null, "completed": M}`; `mark_job_run` increments `completed` and flips `state` to `completed` when `completed >= times`.
- **Inputs / options:** integer, `forever`, `infinite`, `inf`, `none`, empty string, `once`, `one`, `1x`, numeric string.
- **Outputs / side effects:** `Repeat:` renders `<completed>/<times>` or `∞`.
- **Config / env:** n/a.
- **Edge cases / guards:** Uncoerced strings used to crash with `'<=' not supported between instances of 'str' and 'int'`; the chokepoint exists precisely so every entry point (CLI, MCP array clients, direct JSON edits) coerces identically.
- **Rebuild notes:** Accept the user's words, store one canonical type.

### Delivery targets (`deliver`)  `id: automation.cron-delivery`
- **Surface:** Core / CLI / Config
- **Where:** `--deliver` on `hermes cron create|edit`; the `deliver` slot on every automation blueprint; the dashboard's delivery dropdown (fed by `cron_delivery_targets()`).
- **What it does:** Decides where a job's output goes when it finishes.
- **How it works:** `_normalize_deliver_value` (`cron/scheduler.py:2734`) flattens lists to a comma-separated string and maps falsy to `local`; `_expand_routing_tokens` (`:2822`) expands the routing token `all` into every connected platform with a configured home chat; `_resolve_delivery_targets` (`:2840`) maps each part through `_resolve_single_delivery_target` (`:2493`). `cron_delivery_targets()` (`:2402`) is the single source of truth for pickers: `{"id","name","home_target_set","home_env_var"}` per configured platform in canonical gateway order, plus one `bot-chat:<profile>` entry per local profile.
- **Inputs / options:** Accepted values: `local` (no message, output saved only), `origin` (the chat the job was created from; falls back to the first platform home channel when no origin was captured), a bare platform name (`telegram`, `discord`, `signal`, …), `platform:chat_id` (thread ids supported via `platform:chat:thread`), `bot-chat` (this profile's canonical Bot Chat), `bot-chat:<profile>` (a named local profile's Bot Chat), the routing token `all`, and comma-separated combinations of any of these.
- **Outputs / side effects:** Messages sent through the platform adapters; `MEDIA:` tags in the response are extracted and forwarded as file attachments rather than raw text (`gateway/platforms/base.py` `BasePlatformAdapter` helpers). Delivery failures are recorded in `last_delivery_error`.
- **Config / env:** `cron.wrap_response` (default `true`) prefixes the delivered content with `Cronjob Response: <name>` / `(job_id: <id>)` / `-------------` and appends `To stop or manage this job, send me a new message (e.g. "stop reminder <name>").`; set `false` for clean output. `cron.mirror_delivery` (default `false`) plus per-job `attach_to_session` control whether the delivery is also mirrored into the origin session's transcript (`_maybe_mirror_cron_delivery`, `cron/scheduler.py:1822`). Per-platform home targets resolve via `_resolve_home_env_var(platform)` (e.g. `HERMES_TELEGRAM_HOME_CHAT_ID`-shaped vars) and `HERMES_CRON_AUTO_DELIVER_PLATFORM` / `HERMES_CRON_AUTO_DELIVER_CHAT_ID` / `HERMES_CRON_AUTO_DELIVER_THREAD_ID`. `cron.media_send_timeout_seconds` / `HERMES_CRON_MEDIA_SEND_TIMEOUT` bound attachment sends (default 300 s).
- **Edge cases / guards:** `bot-chat` is checked **before** the generic `platform:chat_id` split so a profile name is never misparsed as a chat id. `bot-chat` is deliberately excluded from `all` (it costs a full agent turn). Cross-machine bot-chat is unsupported — names resolve only against the local `~/.hermes/profiles/` tree. A stale Slack thread-per-message origin stamp is repaired at fire time by `_origin_thread_is_stale` (`:2463`). Unresolvable `platform:target` references are passed through to the adapter as written (`pass_unresolved_references=True`) rather than dropped, with a warning.
- **Rebuild notes:** Resolve routing at *fire* time, not create time — a job created before Telegram was connected must start delivering there once it comes online. A better version would let a job declare fallback targets ("Telegram, else email").

### Bot Chat delivery (`bot-chat[:profile]`)  `id: automation.cron-botchat-delivery`
- **Surface:** Core / CLI
- **Where:** `--deliver bot-chat` or `--deliver bot-chat:<profile>`; listed in the delivery picker as `Bot Chat (<profile>)`.
- **What it does:** Injects the job's output into a local profile's canonical Bot Chat session as a real *inbound turn*, so the bot actually reads it and can respond — the agent-to-agent lane, not a transcript mirror.
- **How it works:** `BOT_CHAT_PLATFORM = "bot-chat"` (`cron/scheduler.py:2767`); `parse_bot_chat_deliver_token` (`:2770`) returns `""` for the bare token (own profile), the profile name for the explicit form, `None` when not a bot-chat token; `_resolve_bot_chat_target` (`:2788`) resolves it; `_deliver_to_bot_chat` (`:2628`) spawns a local chat subprocess that inherits `HERMES_HOME` for the own-profile case, or passes `-p <name>` for a named profile.
- **Inputs / options:** `bot-chat`, `bot-chat:<profile-name>` (case-insensitive token, profile name normalized by the profile layer).
- **Outputs / side effects:** A full agent turn runs in the target profile; its response lands in that profile's Bot Chat session.
- **Config / env:** `_get_bot_chat_delivery_timeout()` (`cron/scheduler.py:2614`) bounds the subprocess.
- **Edge cases / guards:** Only profiles present in this machine's profile root can be targeted; same-named profiles on other gateways can never be hit by accident. Excluded from the `all` routing token.
- **Rebuild notes:** Treat "deliver into another agent's inbox" as a first-class target type; the cost model (one LLM turn per delivery) is why it must be opt-in.

### `--no-agent` script jobs (watchdog mode)  `id: automation.cron-no-agent`
- **Surface:** Core / CLI
- **Where:** `hermes cron create --script <path> --no-agent …`; toggled later with `hermes cron edit --no-agent` / `--agent`.
- **What it does:** Runs a script on a schedule with **no LLM at all** and delivers its stdout verbatim. Empty stdout means silence — the classic watchdog (memory alerts, disk alerts, CI pings).
- **How it works:** `run_job` short-circuits to `_run_job_script` (`cron/scheduler.py:4266`) and delivers the captured stdout. Scripts must live under `<HERMES_HOME>/scripts/`; both relative and absolute/`~` paths are resolved and validated against that directory to block traversal, absolute-path injection and symlink escape. `.sh`/`.bash` run under `/bin/bash`; anything else under `sys.executable`. The child environment is filtered through `_sanitize_subprocess_env` so provider credentials are not inherited (SECURITY.md §2.3). `workdir` is applied as the subprocess cwd; the Python process cwd is **never** mutated.
- **Inputs / options:** `--script <path>` (required for this mode), `--no-agent`, optional `--workdir`, `--deliver`, `--repeat`, `--name`, `--schedule`.
- **Outputs / side effects:** stdout delivered as the job output and written to `cron/output/<job_id>/`; non-zero exit or exception yields `(False, error)` and the error text becomes the run's failure.
- **Config / env:** `cron.script_timeout_seconds` / `HERMES_CRON_SCRIPT_TIMEOUT` (default 3600 s) via `_get_script_timeout` (`:3929`).
- **Edge cases / guards:** NUL bytes in the path are rejected (`Blocked: script path contains a NUL byte: …`); unexpandable paths yield `Blocked: script path is not a valid filesystem path: …`. `--no-agent` without a script is refused at create/update. Monitor mode is incompatible with `--no-agent`. Windows uses a dedicated bootstrap (`_windows_cron_bootstrap_argv`, `:4220`, `_read_windows_pyvenv_cfg`, `:4034`). Process trees are killed via `_terminate_cron_script_tree` (`:4142`) and pipes drained by `_drain_script_pipes` (`:4189`) so a wedged child cannot hang the ticker.
- **Rebuild notes:** Containment (scripts dir + resolve + symlink check), a sanitized env, and a process-tree kill are the three things a naive `subprocess.run` gets wrong.

### Script-as-context mode (default `--script`)  `id: automation.cron-script-context`
- **Surface:** Core / CLI
- **Where:** `hermes cron create --script <path> …` without `--no-agent`.
- **What it does:** Runs the script first each tick and injects its stdout into the agent's prompt as collected data, so the LLM analyses fresh data instead of guessing.
- **How it works:** `_build_job_prompt` (`cron/scheduler.py:4563`) prepends `## Script Output` + `The following data was collected by a pre-run script. Use it as context for your analysis.` + a fenced block. A failing script instead prepends `## Script Error` + `The data-collection script failed. Report this to the user.` A *successful* script with **empty** output returns `None`, skipping the AI call entirely.
- **Inputs / options:** `--script <path>`; same containment/interpreter rules as no-agent mode.
- **Outputs / side effects:** Sets `has_injected_data=True`, which relaxes the prompt-injection scanner to the looser tier for the assembled prompt.
- **Config / env:** `cron.script_timeout_seconds`.
- **Edge cases / guards:** Empty stdout = silent skip (documented, not an error).
- **Rebuild notes:** The empty-output-means-skip rule is what makes polling jobs cheap; keep it.

### Wake gate (`{"wakeAgent": false}`)  `id: automation.cron-wake-gate`
- **Surface:** Core
- **Where:** The last non-empty stdout line of a cron job's pre-check script.
- **What it does:** Lets a cheap script decide, per tick, whether the expensive LLM run happens at all.
- **How it works:** `_parse_wake_gate` (`cron/scheduler.py:4537`) parses the last non-empty stdout line as JSON. `{"wakeAgent": false}` skips the agent entirely — no LLM, no delivery. Any other outcome (non-JSON, not a dict, key absent, `true`) wakes the agent normally. Convention ported from nanoclaw #1232.
- **Inputs / options:** One JSON object on the final stdout line; only the `wakeAgent` boolean is read.
- **Outputs / side effects:** Suppresses the agent run and the delivery for that tick.
- **Config / env:** n/a.
- **Edge cases / guards:** Fail-open — anything unparseable wakes the agent, so a broken script never silently disables a job.
- **Rebuild notes:** A one-line, fail-open protocol is the right shape; a better version would let the gate also carry a reason string for the ledger.

### Monitor mode (`--monitor-script` / `--monitor-url`)  `id: automation.cron-monitor-mode`
- **Surface:** Core / CLI
- **Where:** `hermes cron create --monitor-script <path>` or `--monitor-url <http(s) URL>`; editable via `hermes cron edit` (empty string clears).
- **What it does:** Attaches a cheap change-detector in front of an LLM job. Each tick the source runs first; if its output is byte-identical to last time, the agent run is suppressed entirely. When it changes, a `MONITOR CHANGE DETECTED` block (unified diff + new output) is injected and the agent runs.
- **How it works:** `cron/monitor.py`. `check_monitor(job)` (`cron/monitor.py:148`) runs `_run_monitor_source` (script via `cron.scheduler._run_job_script`, or `_fetch_monitor_url`), hashes the output with `hash_monitor_output` = SHA-256 of exact UTF-8 bytes (no normalization), compares to `job["monitor_state"]["last_output_hash"]`. On change the new hash + snapshot are persisted **before** the agent runs, so a failed agent run does not re-alert on the same content forever. Snapshot file: `cron/output/<job_id>/monitor_last_output.txt`.
- **Inputs / options:** `--monitor-script MONITOR_SCRIPT` (path under `~/.hermes/scripts/`, `.sh`/`.bash` via bash else Python); `--monitor-url MONITOR_URL` (http/https only).
- **Outputs / side effects:** First run injects `## Monitor Baseline (first run)` + `This is the first observation of the monitored source — there is no previous output to diff against.` + `### Current output`. Subsequent changes inject `## MONITOR CHANGE DETECTED` + `The monitored source's output changed since the last run.` + `### Diff (previous → current)` (```diff fence) + `### Current output`. Unchanged ticks are recorded as a silent `no_change` run. Persists `monitor_state = {last_output_hash, last_changed_at}`.
- **Config / env:** Limits are module constants: `MAX_DIFF_CHARS = 4000` (diff truncated with `\n... [diff truncated]`), `MAX_OUTPUT_CHARS = 8000` (output truncated with `\n... [output truncated]`), `URL_TIMEOUT_SECONDS = 30`, `MAX_URL_BYTES = 262144` (256 KiB). URL fetches send `User-Agent: hermes-cron-monitor`.
- **Edge cases / guards:** Comparison is exact bytes — a monitor script emitting a timestamp will look changed every tick; docs tell authors to sort and omit "generated at" lines. Source *failure* is an ERROR, never a change, and nothing is persisted, so a source that recovers to its previous output still suppresses. Non-http(s) URLs are rejected with `monitor_url must be http(s): <url>`. Exactly one source may be set, and neither may combine with `--no-agent`.
- **Rebuild notes:** Persist state at *detection* time, not after a successful agent run — otherwise a flaky agent re-alerts on the same change forever. A better version would offer a normalization hook (strip regex) so ordinary timestamped feeds work without rewriting the script.

### Run-to-run continuity (`--continuity`) and `context_from` chaining  `id: automation.cron-continuity`
- **Surface:** Core / CLI
- **Where:** `hermes cron create --continuity`, `hermes cron edit --continuity` / `--no-continuity`; the `context_from` field of the job record (set by the `cronjob` tool or direct edits).
- **What it does:** Injects a previous run's output into the prompt — either the job's own last output (continuity: dedupe, continue where it left off) or another job's last output (chaining: job A collects, job B analyses).
- **How it works:** `_build_job_prompt` (`cron/scheduler.py:4624`) iterates `job["context_from"]`. The literal `"self"` (case-insensitive) or the job's own id resolves to self-continuity. For each id it reads the newest `*.md` in `cron/output/<source_job_id>/` by mtime, truncates to `_MAX_CONTEXT_CHARS = 8000` (appending `\n\n[... output truncated ...]`), and prepends either `## Your previous run's output` + `The following is this job's most recent output from its previous run. Use it for continuity: avoid repeating what was already reported, and continue where the last run left off.` (self) or `## Output from job '<id>'` + `The following is the most recent output from a preceding cron job. Use it as context for your analysis.` (chained).
- **Inputs / options:** `--continuity` / `--no-continuity` (CLI); `context_from` accepts a string or list of 12-char hex job ids, plus the special value `"self"`.
- **Outputs / side effects:** Marks `has_injected_data = True` (relaxes the injection scanner tier). Missing output dir, no `.md` files or empty output are **silent skips** — never an error in the prompt.
- **Config / env:** `cron.output_retention` (default 50) bounds how many outputs are kept (`_cron_output_keep`, `cron/jobs.py:4210`; pruning in `_prune_job_output`, `:4221`).
- **Edge cases / guards:** Path-traversal guard: a source id must be all hex characters, otherwise it is skipped with a warning naming the job id, name and origin. `--no-continuity` removes only the self-reference and preserves other chained ids. OSError/PermissionError while reading is swallowed (logged) so a chained job never pollutes the prompt with error text.
- **Rebuild notes:** Store outputs as per-job files keyed by timestamp so "last output" is an mtime sort, not a DB query; enforce the hex-id whitelist before touching the filesystem.

### Cron prompt assembly and the cron hint  `id: automation.cron-prompt-assembly`
- **Surface:** Core
- **Where:** Invisible to the user; it is the system-level prefix every cron LLM run receives.
- **What it does:** Assembles the effective prompt: skills, script output, chained/self output, notepad, per-run extra context, and the standing cron behaviour instructions.
- **How it works:** `_build_job_prompt` (`cron/scheduler.py:4563`). Assembly order (outermost first after the hint): cron hint → notepad section → script output/error → context_from blocks → user prompt (+ `## Run Context` when `cronjob(action='run')` passed extra text for this single fire only, never persisted). Attached skills are loaded via `tools/skills_tool.py::skill_view` (bundles first via `resolve_bundle_command_key` / `build_bundle_invocation_message`), each wrapped as `[IMPORTANT: The user has invoked the "<name>" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]`; usage is bumped with `bump_use(skill, task_id=<job id>)` so the curator sees the skill as active. A prompt-cache stable prefix is registered via `agent.prompt_cache_boundary.register_stable_prefix` when the skill blocks are stable and only the tail is volatile.
- **Inputs / options:** Derived entirely from the job record plus the optional per-run `extra_prompt`.
- **Outputs / side effects:** The verbatim cron hint injected on every run: `[IMPORTANT: You are running as a scheduled cron job. DELIVERY: Your final response will be automatically delivered to the user — do NOT use send_message or try to deliver the output yourself. Just produce your report/output as your final response and the system handles the rest. SILENT: If there is genuinely nothing new to report, respond with exactly "[SILENT]" (nothing else) to suppress delivery. Never combine [SILENT] with content — either report your findings normally, or say [SILENT] and nothing more.]`. Missing skills produce a leading notice `[IMPORTANT: The following skill(s) were listed for this job but could not be found and were skipped: <names>. Start your response with a brief notice so the user is aware, e.g.: '⚠️ Skill(s) not found and skipped: <names>']`.
- **Config / env:** n/a.
- **Edge cases / guards:** A skill that fails to load or returns invalid JSON is skipped with a warning rather than failing the run. A bundle that loads no skills is also skipped.
- **Rebuild notes:** Keep stable content (skills) before volatile content (data) so provider prompt caching can actually hit.

### `[SILENT]` suppression  `id: automation.cron-silent`
- **Surface:** Core
- **Where:** The agent's final response text on a cron run (and the webhook adapter's autonomous lane).
- **What it does:** Lets a scheduled job decide there is nothing worth pinging the user about, suppressing delivery entirely.
- **How it works:** `_is_cron_silence_response` (`cron/scheduler.py:746`) delegates to `gateway.response_filters.is_autonomous_silence_response`, the shared autonomous-lane matcher.
- **Inputs / options:** Recognized forms: the bracketed `[SILENT]` sentinel as the whole response, the first line, or the last line; plus bracketless `SILENT`, `NO_REPLY` and `NO REPLY`. Whitespace-trimmed, case-insensitive.
- **Outputs / side effects:** No message is delivered; the run is still recorded in the ledger and output dir.
- **Config / env:** n/a.
- **Edge cases / guards:** A token buried mid-sentence is treated as real content and delivered — so a report *about* the SILENT convention is not swallowed.
- **Rebuild notes:** Support the sloppy variants models actually emit, but only at response boundaries.

### Prompt-injection scanner (two-tier)  `id: automation.cron-injection-scan`
- **Surface:** Core (security)
- **Where:** Every cron LLM run, at prompt-assembly time; also at create/update in the `cronjob` tool.
- **What it does:** Blocks a scheduled job whose assembled prompt contains prompt-injection payloads — including payloads smuggled in through skill markdown loaded from disk at runtime.
- **How it works:** `_scan_assembled_cron_prompt` (`cron/scheduler.py:4825`) picks one of two tiers from `tools/cronjob_tools.py`. **Strict tier** `_scan_cron_prompt` runs when the assembled prompt is essentially the user prompt + the cron hint (no skills, no injected data) — a bare `rm -rf /` there is a smoking gun. **Loose tier** `_scan_cron_skill_assembled` runs when runtime-loaded content is present (`has_skills` or `has_injected_data`): only unambiguous injection directives block, command-shape patterns are dropped, and invisible Unicode is *sanitized* (stripped + logged) rather than blocking, so a stray zero-width space cannot permanently kill a job. When the loose tier was chosen only because of injected data, the raw pre-assembly `user_prompt` is additionally scanned with the strict set.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Raises `CronPromptInjectionBlocked` (`cron/scheduler.py:522`); `run_job` turns it into a clear operator-facing refusal and logs `Cron job '<label>': assembled prompt blocked by injection scanner — <error>`. The cleaned (sanitized) prompt is what actually runs in the loose tier.
- **Config / env:** n/a.
- **Edge cases / guards:** Rationale for the split: cron auto-approves tool calls, so an unvetted skill payload would otherwise bypass every gate (#3968); but data feeds legitimately quote dangerous commands (a triage bot ingesting a bug report that pastes `rm -rf /`), so the same strictness there would kill real jobs.
- **Rebuild notes:** Tier the scanner by *content provenance*, not by whether a feature flag is on. Skill bodies are vetted at install time (`skills_guard.py`) and script output is operator-authored — same trust class.

### Credential-exfiltration guard (`provider` + `base_url`)  `id: automation.cron-credential-guard`
- **Surface:** Core (security)
- **Where:** Fire time, immediately before provider resolution.
- **What it does:** Refuses to run a job whose stored provider/base_url pair would send a named provider's stored API key to an off-host endpoint.
- **How it works:** `_guard_job_credential_exfil` (`cron/scheduler.py:4895`) re-runs `tools.cronjob_tools._validate_cron_base_url(job.provider, job.base_url)` — the same validator the model-callable tool uses at create/update — as a runtime backstop for jobs written directly into the store or created before the guard existed.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Raises `RuntimeError("Cron job '<id>' blocked for safety: <err>")`, caught by the run failure path and reported; logs `Job '<id>': refusing to run — unsafe provider/base_url pair could exfiltrate a stored credential: <err>`.
- **Config / env:** Operator-configured `fallback_providers` come from config, are trusted, and are validated by the caller instead.
- **Edge cases / guards:** **Fails closed**: if the validator itself raises, a job that set a `base_url` is refused with `could not validate provider/base_url pair (<Exc>: <msg>); refusing to run a job with an unverified base_url override`, while jobs with no override still run (nothing to exfiltrate).
- **Rebuild notes:** Validate at both the write boundary and the use boundary — CWE-200/CWE-522 classes reappear the moment a store can be written by anything other than the validating API.

### Gateway-lifecycle guard  `id: automation.cron-lifecycle-guard`
- **Surface:** Core (security)
- **Where:** Every job-creation path — `hermes cron create`, `hermes cron edit`, the `cronjob` model tool — and again at execution time in `tools/terminal_tool.py` when `_HERMES_GATEWAY=1`.
- **What it does:** Rejects cron jobs whose prompt or script would restart/stop/uninstall the gateway, which under launchd `KeepAlive` / systemd `Restart=` creates a SIGTERM-respawn loop every ~10 s.
- **How it works:** `cron/lifecycle_guard.py`. `check_gateway_lifecycle(prompt, script)` (`:1199`) raises `GatewayLifecycleBlocked` (a `ValueError`). Detection is deliberately **command-shaped**, not prose-shaped, via `_GATEWAY_LIFECYCLE_PATTERN` (`:61`): Branch A `hermes gateway (restart|stop|uninstall)` with a lookbehind excluding `/`, word chars, `.` and `-` so file paths don't match (`start` is intentionally allowed — starting a gateway from inside one is benign). Branch B `launchctl` verbs (including `submit`, `bootstrap`, `bootout`, `remove`, `disable`, `unload`, `kickstart`) against a `hermes-gateway`/`ai.hermes.gateway` label (`_LAUNCHCTL_LIFECYCLE_VERBS_RE` `:202`, `_HERMES_GATEWAY_LABEL_RE` `:205`). Branch C `systemctl … hermes-gateway`. Branch D `pkill` against the gateway. The profile-flag form `hermes -p <profile> gateway restart|stop` (`_PROFILE_FLAG_LIFECYCLE_PATTERN`, `:135`) is blocked only when the named profile is the current one (`_named_profile_is_current`, `:171`) — sibling-profile restarts are legitimate fleet operations. Scripts referenced by the command are read and scanned recursively (`contains_gateway_lifecycle_command_or_referenced_script`, `:1101`) up to `_MAX_REFERENCED_SCRIPT_DEPTH = 8` and `_MAX_REFERENCED_SCRIPT_BYTES = 1 MiB`, with binary-magic sniffing (`_BINARY_MAGICS`, `_BINARY_SNIFF_BYTES = 4096`) and cloud-placeholder path detection (`Mobile Documents`, `CloudStorage`).
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Creation/update fails with a clear rejection instead of scheduling a job that would only wedge the host.
- **Config / env:** `_HERMES_GATEWAY=1` marks in-gateway execution for the terminal-tool half.
- **Edge cases / guards:** Data-sink arguments are masked before scanning (`_mask_data_sink_arguments`, `:621`) so `echo "hermes gateway restart" > notes.txt` is not blocked; transparent command prefixes (`env`, `sudo`, `nohup`, `timeout`, …) are peeled up to `_MAX_PREFIX_PEELS = 8` (`_peel_transparent_prefixes`, `:554`); `contains_launchctl_submit_command` (`:597`) catches neutral-label `launchctl submit` that dodges the text anchor; pipe-to-interpreter shapes are detected (`_PIPE_TO_INTERPRETER`, `:348`).
- **Rebuild notes:** Anchor on command shape, not keywords — a substring match on "gateway restart" both false-positives on prose and misses `launchctl submit` laundering. A better version would sandbox cron scripts so the guard becomes defence-in-depth rather than the primary control.

### Preflight checks and auto-pause  `id: automation.cron-preflight`
- **Surface:** Core
- **Where:** Fire time, before the agent is constructed; the same predicates back `hermes cron doctor`.
- **What it does:** Detects jobs that cannot possibly succeed (no provider key, unreachable delivery target, missing skill, invalid config) and either alerts once or auto-pauses the job.
- **How it works:** `_cron_preflight_enabled(cfg)` (`cron/scheduler.py:5083`) reads `cron.preflight`. Checks run in order: `_preflight_check_provider_key` (`:5095`), `_preflight_check_delivery` (`:5203`, which uses `_delivery_platform_routed_from_primary_gateway`, `:5143`), `_preflight_check_skills` (`:5268`), `_preflight_job_config` (`:5324`). A hard shape error routes to `_block_and_pause_job` (`:4941`) which calls `pause_job(job_id, "Auto-paused by scheduler: <reason>")`, writes a `# Cron Job: <name>` markdown record with `**Status:** blocked (unrunnable job) — auto-paused`, and emits the alert `⚠ Cron job '<name>' was auto-paused\n\n<reason>`.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Status markers stamped into the error string: `[blocked_config]` / `[blocked_config:silent]` and `[drift_skip]` / `[drift_skip:silent]`. `run_one_job` keys off them to record `last_status='blocked_config'` and to dedupe alerts using the per-job `preflight_alerted` / `drift_alerted` bits (`mark_preflight_alerted` / `clear_preflight_alerted` / `mark_drift_alerted` / `clear_drift_alerted`, `cron/jobs.py:2943`–`:2958`).
- **Config / env:** `cron.preflight` (default `true`); `cron.model_drift_guard` (default `true`).
- **Edge cases / guards:** Alert-once semantics prevent a broken job from pinging every tick; the `:silent` marker variant means "already alerted, do not deliver again". Transient provider-resolution network errors are classified separately by `_is_transient_provider_resolve_error` (`:4988`) and do not blame the config.
- **Rebuild notes:** Auto-pausing an unrunnable job is essential — returning an error alone means it re-fires forever. Pair it with an auditable `paused_reason`.

### Model/provider drift guard  `id: automation.cron-drift-guard`
- **Surface:** Core / Config
- **Where:** Fire time for jobs that did **not** pin `--model`/`--provider`.
- **What it does:** Detects that the resolved default model/provider has changed since the job was created and skips (with an alert) rather than silently running an unpinned job on a different brain.
- **How it works:** `create_job` records `provider_snapshot` / `model_snapshot` via `_compute_provider_model_snapshots` (`cron/jobs.py:2125`) for unpinned axes; at fire time the scheduler compares the live resolution and, on mismatch, returns an error prefixed with `DRIFT_SKIP_MARKER = "[drift_skip]"` (or `[drift_skip:silent]` when already alerted).
- **Inputs / options:** Disabled by setting `cron.model_drift_guard: false`; bypassed entirely by pinning `--model` / `--provider`.
- **Outputs / side effects:** `last_status` records the skip; the drift alert is delivered once per job (`drift_alerted` bit).
- **Config / env:** `cron.model_drift_guard` (default `true`), `cron.model`, `cron.model_provider`, `model.default`.
- **Edge cases / guards:** Snapshots are `None` for pinned axes, `no_agent` jobs, resolution failures, and any job written before the fields existed — all of which skip the guard for back-compat.
- **Rebuild notes:** Snapshot the *resolved* value at create time; comparing config strings is not enough because resolution has fallbacks.

### In-flight guard and stale-claim sweep  `id: automation.cron-inflight-guard`
- **Surface:** Core
- **Where:** Every tick, before due jobs are dispatched.
- **What it does:** Guarantees one running instance per job id, and force-releases leaked claims so a crashed run cannot wedge a job forever.
- **How it works:** `try_register_running_job` / `release_running_job` (`cron/scheduler.py:868`/`:898`) maintain `_running_job_ids`, `_running_since` (wall-clock claim instant) and `_running_futures` (with a `_FUTURE_PENDING` sentinel installed at claim time so there is never a window with neither an age nor a future marker). `sweep_stale_inflight(due_jobs)` (`:1053`) force-releases any id whose claim is older than its allowance **and** has no live future. The allowance is `max(2 × job interval, floor)`; the floor is `_INFLIGHT_MIN_ALLOWANCE_MINUTES = 30.0` minutes, overridable by `cron.inflight_max_minutes` (config) or `HERMES_CRON_INFLIGHT_MAX_MINUTES` (internal escape hatch). Job cadence comes from the persisted parsed schedule: `interval.minutes`, or `_cron_interval_minutes(expr)` (`:947`) which measures the gap between the next two croniter fire times (memoised in `_cron_interval_cache`); `once` schedules return `None` → floor allowance.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** `_record_forced_release` (`:1032`) bumps `_forced_release_count`, keeps the last `_FORCED_RELEASE_HISTORY = 20` releases, and mirrors them to a JSONL under the cron dir so an out-of-process probe can catch a wedge in-cycle; `get_inflight_guard_stats()` (`:1012`) exposes the counters to unified health.
- **Config / env:** `cron.inflight_max_minutes`, `HERMES_CRON_INFLIGHT_MAX_MINUTES`, `cron.max_parallel_jobs` / `HERMES_CRON_MAX_PARALLEL`.
- **Edge cases / guards:** Cross-process fencing is separate: `claim_job_for_fire` (`cron/jobs.py:3440`) uses a machine id (`_machine_id`, `:3423`) plus pid; `heartbeat_fire_claim` / `heartbeat_run_claim` (`:3623`/`:3307`) refresh the claim while a long run proceeds; `fire_claim_fence(job_id, expected_owner=…)` (`:463`) is the ownership check; `clear_run_claim` (`:3339`) releases it. One-shot run claims expire after `ONESHOT_RUN_CLAIM_TTL_SECONDS = 1800` s, or `3 × HERMES_CRON_TIMEOUT` (headroom multiplier `_ONESHOT_RUN_CLAIM_TTL_HEADROOM = 3`) when a finite inactivity timeout is configured.
- **Rebuild notes:** Two layers are needed: an in-process set for the thread pool and a durable claim (machine+pid+start-time) for multi-process safety. Age alone is not enough — always require "no live future" before force-releasing.

### Inactivity watchdog and interruption bookkeeping  `id: automation.cron-inactivity-watchdog`
- **Surface:** Core
- **Where:** Around every cron agent run.
- **What it does:** Kills a cron run that has stopped producing output, and makes sure a killed run can never later overwrite its own status with a false "ok".
- **How it works:** `_inactivity_watchdog_loop` (`cron/scheduler.py:1379`) with `_cron_inactivity_seconds()` (`:1408`) — default 600 s from `HERMES_CRON_TIMEOUT`, `0` meaning unlimited. It is an *inactivity* limit, not a wall-clock cap: a job that keeps producing output legitimately runs longer. On gateway shutdown, `mark_running_jobs_interrupted` (`:1253`) records execution *tokens* (`object()` identity keys from `_running_fire_owners`), and `_is_interrupted` / `_consume_interrupted_flag` (`:1338`/`:1360`) let the completing thread check its own token before writing `last_status`.
- **Inputs / options:** `HERMES_CRON_TIMEOUT` (seconds; `0` = unlimited), `HERMES_CRON_DRAIN_TIMEOUT`.
- **Outputs / side effects:** Interrupted runs record an interrupted status, not `ok`.
- **Config / env:** as above; `cron.session_db_timeout_seconds` / `HERMES_CRON_SESSION_DB_TIMEOUT` (default 10) bounds session-DB work via `_BoundedCronSessionDB` (`:5431`); `_cron_cleanup_timeout_seconds` (`:5357`) bounds teardown (`_run_cron_cleanup_with_timeout`, `:5375`, `_teardown_cron_agent`, `:6929`).
- **Edge cases / guards:** Token keying is what stops a *later* run of the same recurring job id from inheriting a stale interrupt flag; legacy dispatch paths without a fire owner fall back to the bare job id. `_interpreter_shutting_down` (`:1480`) distinguishes shutdown noise from real errors.
- **Rebuild notes:** Identify a *run*, not a job, when recording interruption — recurring jobs reuse their id on every fire.

### Cron output store and retention  `id: automation.cron-output-store`
- **Surface:** Core
- **Where:** `<HERMES_HOME>/cron/output/<job_id>/*.md` (plus `monitor_last_output.txt` for monitor jobs).
- **What it does:** Persists every run's rendered output so it can be re-read for continuity/chaining, shown in the dashboard, and audited.
- **How it works:** `save_job_output(job_id, output)` (`cron/jobs.py:4250`) writes one markdown file per run into `_job_output_dir(job_id)` (`:484`), then `_prune_job_output(dir, keep)` (`:4221`) trims to `_cron_output_keep()` (`:4210`) newest files. Directories are created with `_secure_dir` / `_secure_file` (`:695`/`:703`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Files on disk; consumed by `context_from`, the monitor snapshot, and the dashboard's run viewer.
- **Config / env:** `cron.output_retention` (default `50`).
- **Edge cases / guards:** Pruning is by mtime; the monitor snapshot filename is excluded from the `*.md` glob used by `context_from`.
- **Rebuild notes:** One file per run keeps "latest output" an O(1) mtime sort and makes the retention policy trivially auditable.

### Scheduler provider interface (`cron.provider`)  `id: automation.cron-scheduler-provider`
- **Surface:** Core / Config / Plugin
- **Where:** `cron.provider` in `config.yaml` (empty = built-in); provider implementations live under `plugins/cron_providers/<name>/`.
- **What it does:** Pluggable "Axis B" — decides *when* a due job fires. It does not decide what firing means; execution and delivery stay in `cron.scheduler.run_job` / `_deliver_result` for every provider.
- **How it works:** `cron/scheduler_provider.py`. Abstract base `CronScheduler` (`:93`) requires only `name` (property) and `start`; `is_available()` and `stop()` carry safe defaults; the Phase-4 hooks `on_jobs_changed` / `fire_due` / `reconcile` are non-abstract so the built-in satisfies the ABC without overriding them. `resolve_cron_scheduler()` (`:476`) selects the provider; `scheduler_for_profile_mode()` (`:516`) picks the per-profile vs multiplex shape; `InProcessCronScheduler` (`:538`) is the historical 60 s daemon-thread ticker. Capability probes: `provider_supports_force_fire` (`:266`), `provider_supports_split_fire` (`:283`), `provider_supports_fire_cancel` (`:311`). `fire_overdue_jobs()` (`:353`) with `_misfire_grace_minutes()` (`:331`) catches up jobs missed while the process was down. `_existing_profile_homes()` (`:68`) drops deleted profile homes from the multiplex snapshot so ticking never recreates a deleted profile's `cron/` directory.
- **Inputs / options:** Config keys: `cron.provider` (name), plus the Chronos provider's `cron.chronos.portal_url` (default `https://portal.nousresearch.com`), `cron.chronos.callback_url`, `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`.
- **Outputs / side effects:** Selecting a non-built-in provider suppresses the "gateway not running" warnings, because an external provider fires via its own machinery (e.g. a NAS-mediated webhook) rather than the in-process ticker.
- **Config / env:** as above.
- **Edge cases / guards:** The interface is explicitly marked EXPERIMENTAL — signatures may change until a second provider validates it; growth must be additive (new optional methods), never a changed `start()` signature or a new abstractmethod. `is_available()` must not do network I/O. fd-exhaustion backoff (`_backoff_wait_seconds`, `:36`; `_note_tick_failure`, `:50`) doubles the tick wait per consecutive EMFILE/ENFILE failure up to `_EMFILE_BACKOFF_MAX_SECONDS = 900`.
- **Rebuild notes:** Split "when to fire" from "what firing does" from day one; every managed-cron integration then becomes a ~200-line provider instead of a fork of the scheduler.

### Automation blueprints  `id: automation.blueprints`
- **Surface:** Core / CLI / Gateway / Docs
- **Where:** `/blueprint <key> slot=value …` slash command; the dashboard renders one form field per slot; `hermes://blueprint/<key>?slot=value` deep links; the docs catalog at `website/docs/reference/automation-blueprints-catalog.mdx`.
- **What it does:** Parameterized automation templates with typed slots, so a user never types raw cron. One definition renders as a form (GUI), a pre-filled slash command (CLI/TUI/messenger), a seed prompt (agent) and a copy-paste command + deep link (docs).
- **How it works:** `cron/blueprint_catalog.py`. `AutomationBlueprint` (`:83`) = `key, title, description, category, schedule_template, prompt_template, slots, deliver_default="origin", skills, tags`. `BlueprintSlot` (`:61`) = `name, type, label, default, options, optional=False, help="", strict=True`. Slot types (`_SLOT_TYPES`): `time`, `enum`, `text`, `weekdays`. `WEEKDAY_PRESETS` maps `everyday → *`, `weekdays → 1-5`, `weekends → 0,6`. Renderers: `blueprint_form_schema` (`:578`), `blueprint_slash_command` (`:602`), `blueprint_deeplink` (`:623`), `blueprint_catalog_entry` (`:664`) with `_humanize_schedule` (`:637`). `fill_blueprint` (`:747`) validates values and returns a `cron.jobs.create_job` kwargs dict — there is no second job engine. `_resolve_schedule` (`:689`) substitutes `{minute}`, `{hour}`, `{dow}` and any custom slot placeholders into `schedule_template`.
- **Inputs / options:** 16 built-in blueprints (key | title | category | schedule template | skills): `morning-brief` | Morning briefing | daily | `{minute} {hour} * * *` | google-workspace; `important-mail` | Important-mail monitor | email | `*/{interval_min} * * * *` | email-inbox-triage; `weekly-review` | Weekly review | weekly | `{minute} {hour} * * {dow}` | weekly-review-planning; `workday-start` | Workday start reminder | daily | `{minute} {hour} * * 1-5`; `custom-reminder` | Custom reminder | general | `{minute} {hour} * * {dow}`; `evening-winddown` | Evening wind-down | daily | `{minute} {hour} * * *`; `news-digest` | Topic news digest | general | `{minute} {hour} * * {dow}`; `bill-renewal-watch` | Bills & renewals reminder | general | `{minute} {hour} * * {dow}`; `price-watch` | Price & availability watch | general | `0 */{interval_h} * * *` | product-price-monitor; `competitor-watch` | Competitor news watch | general | `{minute} {hour} * * {dow}` | competitor-news-monitor; `habit-checkin` | Habit check-in | general | `{minute} {hour} * * {dow}`; `hydration-move` | Hydration & movement nudge | general | `0 {start_hour}-{end_hour}/{interval_hours} * * 1-5`; `meal-plan` | Weekly meal plan | weekly | `{minute} {hour} * * {dow}`; `learn-daily` | Daily learning drip | daily | `{minute} {hour} * * {dow}`; `gratitude-journal` | Gratitude & reflection prompt | general | `{minute} {hour} * * {dow}`; `on-this-day` | On-this-day discovery | daily | `{minute} {hour} * * *`.
- **Outputs / side effects:** Accepting a filled blueprint creates a real cron job via `create_job`. Example rendered command: `/blueprint morning-brief time=08:00 deliver=origin`; example deep link: `hermes://blueprint/morning-brief?time=08%3A00&deliver=origin`.
- **Config / env:** n/a.
- **Edge cases / guards:** `BlueprintFillError` (`:45`) is raised for values failing validation. Unknown slot types are rejected at import (`unknown slot type <t> (slot <name>)`). The `deliver` slot is `strict=False` — its `options` are suggestions, since the real set of valid platforms depends on the user's gateways and is validated downstream.
- **Rebuild notes:** One schema, four renderers is the whole idea; do not let the GUI form and the slash command drift into separate definitions. A better version would allow user-defined blueprints in `~/.hermes/blueprints/*.yaml`.

### Automation blueprint slots (per-blueprint field reference)  `id: automation.blueprint-slots`
- **Surface:** Core / Docs
- **Where:** The dashboard's blueprint form, the `/blueprint` command's `slot=value` pairs, and the deep-link query string.
- **What it does:** Defines exactly which fields each blueprint asks for, with labels, defaults and allowed values.
- **How it works:** Data in `cron/blueprint_catalog.py`; the shared factories are `_TIME(default)` (label `What time?`, help `24h local time, e.g. 08:00`) and `_DELIVER` (label `Where to deliver?`, default `origin`, options `origin|local|telegram|discord|email`, `strict=False`, help `origin = the chat you set this up from (or your configured home channel when created from the dashboard); local = save only, no message; or any connected platform name`).
- **Inputs / options:** Verbatim slot lists — **morning-brief**: `time` (time, `What time?`, 08:00), `deliver`. **important-mail**: `interval_min` (enum, `How often?`, 30, options 15/30/60, help `minutes between checks`), `criteria` (text, `Only notify me if the mail…`, default `needs a reply today, is from my manager or family, or mentions a deadline`), `deliver`. **weekly-review**: `time` (18:00), `day` (enum, `Which day?`, sunday, options sunday/monday/friday/saturday), `deliver`. **workday-start**: `time` (09:00), `deliver`. **custom-reminder**: `what` (text, `Remind me to…`, `take a break and stretch`), `time` (14:00), `recurrence` (weekdays, `Repeat on`, everyday, options everyday/weekdays/weekends), `deliver`. **evening-winddown**: `time` (21:00), `deliver`. **news-digest**: `topic` (text, `What topic?`, `AI and technology`, help `a subject, product, person, or search phrase`), `time` (18:00), `recurrence` (weekdays), `count` (enum, `How many bullets?`, 5, options 3/5/8), `deliver`. **bill-renewal-watch**: `what` (text, `What's due?`, `my streaming subscription renews soon`), `time` (10:00), `recurrence` (everyday), `deliver`. **price-watch**: `item` (text, `What exactly to watch?`, `a product URL or exact flight/hotel/listing description`, help `URL or precise description — variant, dates, seller`), `condition` (text, `Alert me when…`, `the all-in price drops below my target`, help `threshold price (state the currency), availability, or terms change`), `interval_h` (enum, `How often?`, 6, options 1/3/6/12/24, help `hours between checks — be gentle with rate limits`), `deliver`. **competitor-watch**: `companies` (text, `Which companies?`, `two or three competitors, by canonical name`, help `canonical names and domains; aliases help dedup`), `categories` (text, `Which events matter?`, `product launches, pricing changes, funding, partnerships, executive moves, incidents`), `time` (09:00), `recurrence` (weekdays, default `monday`), `deliver`. **habit-checkin**: `habit` (text, `Which habit?`, `20 minutes of reading`), `time` (20:00), `recurrence` (everyday), `deliver`. **hydration-move**: `interval_hours` (enum, `How often?`, 1, options 1/2/3, help `hours between nudges`), `start_hour` (enum, `Start hour`, 9, options 7/8/9/10, help `first hour of the active window (24h)`), `end_hour` (enum, `End hour`, 17, options 16/17/18/19, help `last hour of the active window (24h)`), `deliver`. **meal-plan**: `diet` (enum, `Diet?`, `no restrictions`, options `no restrictions|vegetarian|vegan|high-protein|low-carb`), `meals` (enum, `Meals per day?`, `dinner only`, options `dinner only|lunch and dinner|all three`), `effort` (enum, `Cooking effort?`, quick, options quick/medium/ambitious), `time` (17:00), `day` (enum, `Which day?`, sunday, options sunday/monday/friday/saturday), `deliver`. **learn-daily**: `topic` (text, `Learn about…`, `Spanish vocabulary`), `time` (08:30), `recurrence` (weekdays), `deliver`. **gratitude-journal**: `time` (21:30), `recurrence` (everyday), `deliver`. **on-this-day**: `flavor` (enum, `What kind?`, `on this day in history`, options `on this day in history|word of the day|science fact|quote of the day`), `time` (07:30), `deliver`.
- **Outputs / side effects:** Slot values become cron `schedule` + `prompt` + `deliver` + `skills` on the created job.
- **Config / env:** n/a.
- **Edge cases / guards:** `time` slots parse to `{minute}`/`{hour}`; `weekdays` slots parse to `{dow}` through `WEEKDAY_PRESETS` (a bare weekday name such as `monday` is also accepted, as `competitor-watch`'s default shows).
- **Rebuild notes:** Ship defaults that are immediately useful so a user can accept a blueprint with zero edits.

### Cron suggestions (`/suggestions`)  `id: automation.cron-suggestions`
- **Surface:** Core / Gateway
- **Where:** The `/suggestions` surface in chat; the dashboard's suggestion cards.
- **What it does:** Proposes automations the user accepts with one tap, or dismisses permanently. Accepting creates a real cron job; nothing ever auto-schedules.
- **How it works:** `cron/suggestions.py`. Store `<HERMES_HOME>/cron/suggestions.json`, atomic writes, in-process lock, 0600 perms — mirroring the jobs store. API: `add_suggestion` (`:127`), `list_pending` (`:122`), `get_suggestion(ref)` (`:182`), `dismiss_suggestion` (`:217`), `accept_suggestion(ref, origin=…)` (`:225`, calls `cron.jobs.create_job` with the stored `job_spec`), `clear_resolved` (`:257`).
- **Inputs / options:** Sources (`VALID_SOURCES`): `catalog` (curated starters), `blueprint` (an installed skill carrying a `blueprint:` block — see `tools/blueprints.py`), `usage` (background self-improvement review spotted a recurring ask), `integration` (the user connected an account and its obvious automations are offered). Statuses: `pending`, `accepted`, `dismissed`.
- **Outputs / side effects:** Accepting mints a cron job; dismissing latches by `dedup_key` so the same proposal is never re-offered.
- **Config / env:** `MAX_PENDING = 5` — new suggestions are dropped when the pending list is full, so the surface never becomes a nag wall.
- **Edge cases / guards:** Consent-first: acceptance is always explicit. Re-seeding is idempotent (dismissed/accepted keys are skipped).
- **Rebuild notes:** A stable dedup key plus a hard pending cap is what separates a helpful suggestion surface from spam.

### Starter automation catalog (`cron/suggestion_catalog.py`)  `id: automation.cron-suggestion-catalog`
- **Surface:** Core
- **Where:** Seeded into `/suggestions` for a new user via `seed_catalog_suggestions()`.
- **What it does:** Four curated, ready-to-run automations offered out of the box.
- **How it works:** `CatalogEntry(key, title, description, job_spec)`; `job_spec` is passed verbatim to `create_job` on accept. `classify_items_script_path()` returns the absolute path of the shipped urgency classifier `cron/scripts/classify_items.py`.
- **Inputs / options:** The four entries, verbatim: `catalog:daily-briefing` — title `Daily briefing`, description `Every morning at 8am, a short briefing: today's calendar, weather, and anything urgent waiting on you.`, schedule `0 8 * * *`, deliver `origin`. `catalog:important-mail-monitor` — title `Important-mail monitor`, description `Check your inbox periodically and ping you ONLY about mail that actually needs attention — never the newsletters.`, schedule `every 30m`, deliver `origin`; its prompt pipes candidates through `python3 -m cron.scripts.classify_items --threshold 7 --criteria …` and answers `[SILENT]` when nothing clears the bar. `catalog:weekly-review` — title `Weekly review`, description `Every Sunday evening, a recap of the week: what got done, what's still open, and what's coming up next week.`, schedule `0 18 * * 0`, deliver `origin`. `catalog:standup-reminder` — title `Workday start reminder`, description `A weekday nudge at 9am with your day's agenda and top priorities, so you start focused.`, schedule `0 9 * * 1-5`, deliver `origin`.
- **Outputs / side effects:** `seed_catalog_suggestions(add_fn=…, keys=[…])` registers them as pending suggestions and returns the records actually created.
- **Config / env:** n/a.
- **Edge cases / guards:** Prompts must be self-contained — cron jobs run with no chat context. Entries already dismissed/accepted, or beyond the pending cap, are skipped by the store, so re-seeding is safe.
- **Rebuild notes:** The old "proactive monitor engine" collapsed into one catalog entry here; resist making monitoring a separate subsystem.

---

## 2. In-session autonomy — `/loop`, `/heartbeat`, `/goal`, `/subgoal`, `/refine`

### `/loop` — recurring in-session wakeups  `id: automation.loop`
- **Surface:** CLI | Gateway/Telegram | TUI | Desktop app
- **Where:** `/loop [interval] <prompt> [--times N] [--until <condition>]` typed in any chat surface; controls `/loop status`, `/loop pause`, `/loop resume`, `/loop stop` (aliases `clear`, `cancel`), `/loop help` (aliases `--help`, `-h`).
- **What it does:** Re-runs a prompt (or a slash command) on a recurring cadence **inside the current session**. Each tick is a real agent turn injected through the normal user-input path, so the agent always sees current state.
- **How it works:** `hermes_cli/loops.py`. `LoopManager` (`:528`) holds per-session state persisted to SessionDB's `state_meta` table under key `loop:<session_id>` (`_META_PREFIX = "loop:"`, `_meta_key` `:368`), so `/resume` picks the loop back up. `dispatch_loop_command` (`:855`) is the surface-agnostic handler returning `{"output": str, "created": bool}`; CLI, gateway and TUI all drive the same manager. Tick lifecycle: `is_due()` (`:678`) → `fire_tick()` (`:685`, marks `awaiting_response`, provisionally schedules the next tick from *now* so a process death mid-turn cannot tight-loop) → the surface injects the message → `complete_tick(last_response)` (`:724`) evaluates and reschedules from turn *end*; `abandon_tick()` (`:715`) rolls back a tick whose injection failed.
- **Inputs / options:** Argument grammar parsed by `parse_loop_args` (`:142`). Interval token regex `^(?=\d)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$` — compound units allowed (`30s`, `5m`, `2h`, `1h30m`); a bare number is deliberately **not** an interval (it would collide with `/loop 3 things to check`). Leading `every` is sugar (`/loop every 10m /recap`). Flags, parsed off the tail first so an interval-looking token inside `--until` cannot confuse the front parse: `--times N` (positive integer; rejects with `--times expects a positive integer, got <x>`), `--until <condition>` (consumes to end of line, DOTALL). Sub-commands: bare `/loop` or `/loop status`, `/loop pause`, `/loop resume`, `/loop stop|clear|cancel`, `/loop help|--help|-h`.
- **Outputs / side effects:** Creation prints `↻ Loop set (<cadence>): <prompt>` plus conditional lines: `(replaced the previous loop for this session)`, `(interval raised to the <X> minimum — loops.min_interval_seconds)`, `Self-paced: first check in <X>; backs off up to <Y> while nothing changes.`, `Runs N time(s), then stops.`, `Stops when: <until>`, `Backstop budget: N ticks (loops.max_ticks; 0 = unlimited).`, and `First wakeup fires now, then on the cadence above. Controls: /loop status · pause · resume · stop.`. Status line shapes: `↻ Loop (active, <meta><tail>): <prompt>` (tail `, next in <X>` or `, wakeup running`), `⏸ Loop (paused, <meta> — <reason>): <prompt>`, `✓ Loop finished (<N ticks> — <reason>): <prompt>`, and `No loop set. Start one with /loop [interval] <prompt>.`. Control replies: `⏸ Loop paused: <prompt>\nUse /loop resume to continue.`, `▶ Loop resumed (<cadence>): <prompt>`, `✓ Loop stopped.`, `No active loop.`, `No loop to resume.`, `No loop set.`. `/loop help` prints the verbatim block `Usage: /loop [interval] <prompt> [--times N] [--until <condition>]` + five example lines + `Controls: /loop status · /loop pause · /loop resume · /loop stop` + `The loop also stops itself when the agent replies with LOOP_COMPLETE.`
- **Config / env:** `loops.min_interval_seconds` (default 30, still clamped ≥ 5), `loops.max_ticks` (default 100, `0` = unlimited), `loops.self_paced_floor_seconds` (default 60), `loops.self_paced_ceiling_seconds` (default 900).
- **Edge cases / guards:** Wakeups only fire while the session is IDLE — a real user message always wins and the tick re-arms for the next idle boundary. `/goal` takes priority: `goal_blocks_loop_tick(session_id)` (`:827`) defers the loop tick when a goal continuation is queued or the goal judge is mid-flight; goal-continuation turns never count as loop ticks and vice versa. When the loop prompt itself starts with `/`, `fire_tick` returns the raw command so the surface's normal slash dispatch handles it (no wakeup framing). `migrate_loop_to_session(old, new, reason=…)` (`:466`) carries a loop across a compression session rotation. `list_active_loops()` (`:437`) enumerates every session's loop for the gateway idle watcher. A `route` dict (`platform`/`chat_id`/`chat_type`/`thread_id`) is captured at creation for gateway sessions so the idle watcher injects into the right chat; CLI/TUI pass `None`.
- **Rebuild notes:** Inject the wakeup as an ordinary user message — no system-prompt mutation, no toolset swap — so prompt caching and role alternation survive. Persist state keyed by session so `/resume` restores it. A better version would let a loop declare a per-tick tool budget.

### `/loop` self-paced mode and change-digest backoff  `id: automation.loop-self-paced`
- **Surface:** CLI | Gateway/Telegram | TUI
- **Where:** `/loop <prompt>` with **no** interval token (e.g. `/loop keep refining the failing test until green`).
- **What it does:** Lets the loop pick its own rhythm: it starts fast, backs off exponentially while the agent's replies stop changing, and snaps back to the floor the moment a reply differs — at zero extra LLM cost.
- **How it works:** `_digest_response` (`hermes_cli/loops.py:507`) lowercases, strips clock/timestamp tokens (`\d{1,2}:\d{2}(:\d{2})?`, `\d{4}-\d{2}-\d{2}`, and `\b\d+(\.\d+)?\s*(s|sec|secs|seconds|m|min|mins|minutes|h|hr|hrs|hours)\b`), collapses whitespace and SHA-256s the result. In `complete_tick` step 5, when the new digest equals `last_response_digest` the delay becomes `min(max(current_delay, floor) * 2, ceiling)`; otherwise it resets to the floor.
- **Inputs / options:** No flags of its own — mode is chosen by the absence of an interval token. Floor/ceiling come from config.
- **Outputs / side effects:** `cadence_label()` renders `self-paced, currently <X>`; the creation message reports `Self-paced: first check in <floor>; backs off up to <ceiling> while nothing changes.`
- **Config / env:** `loops.self_paced_floor_seconds` (60), `loops.self_paced_ceiling_seconds` (900).
- **Edge cases / guards:** Timestamp stripping is what makes the digest useful — a reply differing only by "checked at 14:02:33" must not defeat the backoff. Change detection is purely local; no extra model call.
- **Rebuild notes:** Normalize before hashing, and reset (not decay) on change. A better version would also digest tool-call sequences, not just the visible reply.

### `/loop` stop conditions  `id: automation.loop-stop-conditions`
- **Surface:** CLI | Gateway/Telegram | TUI
- **Where:** Evaluated by `complete_tick` after every wakeup turn.
- **What it does:** Decides when the loop ends, in a fixed priority order.
- **How it works:** `hermes_cli/loops.py:724`, in order: (1) **agent self-stop** — `response_signals_complete()` (`:500`) matches `LOOP_COMPLETE` on its own line via `(?im)^\s*LOOP_COMPLETE\s*[.!]?\s*$` (tolerating trailing `.`/`!` the model adds); status `done`, message `✓ Loop finished after N tick(s) — task complete.` (2) **`--until` judge** — reuses `hermes_cli.goals.judge_goal(until, last_response)`; a `done` verdict stops with `✓ Loop finished after N tick(s) — <reason>`; **fail-open** (a broken judge yields `continue`). (3) **`--times` cap** — `✓ Loop finished — ran N/N times.` (4) **`loops.max_ticks` backstop** — status `paused` (recoverable, not `done`), message `⏸ Loop paused — N/M ticks used (loops.max_ticks). /loop resume to keep going, /loop stop to end it.` (5) otherwise the loop continues silently (message `""`).
- **Inputs / options:** `--times N`, `--until <condition>`, `loops.max_ticks`, the `LOOP_COMPLETE` sentinel, and manual `/loop stop|pause`.
- **Outputs / side effects:** Decision dict `{"status","stopped","reason","message"}`.
- **Config / env:** `loops.max_ticks`.
- **Edge cases / guards:** The tick budget is the backstop for a broken `--until` judge, which is precisely why the judge fails open. Budget exhaustion pauses rather than finishes, so `/loop resume` can continue.
- **Rebuild notes:** Order matters: agent self-stop before judge before caps, so a completed task ends immediately without an extra model call.

### Wakeup prompt templates (`/loop`)  `id: automation.loop-wakeup-prompt`
- **Surface:** Core
- **Where:** The synthetic user message each `/loop` tick injects.
- **What it does:** Frames the tick so the agent re-checks current state and knows how to end the loop.
- **How it works:** `WAKEUP_PROMPT_TEMPLATE` (`hermes_cli/loops.py:93`) and `WAKEUP_PROMPT_WITH_UNTIL_TEMPLATE` (`:105`), formatted with `tick`, `cadence`, `prompt` and (for the until variant) `until`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Base template verbatim: `[/loop wakeup #{tick}{cadence}]` / `Recurring task: {prompt}` / blank / `This is an automatic wakeup from the /loop the user set. Perform the task now against the CURRENT state (re-check files, processes, or services fresh — do not assume anything from earlier iterations still holds). Report concisely what you found or did this iteration.` / `If the task is now complete, no longer applicable, or the thing you were watching has finished, say so and end your reply with LOOP_COMPLETE on its own line — that stops the loop.` The `--until` variant adds `Stop condition: {until}` after the task line and asks for `concrete evidence of the stop condition's status`.
- **Config / env:** n/a.
- **Edge cases / guards:** A loop whose prompt is a slash command bypasses framing entirely.
- **Rebuild notes:** Telling the model *how to stop the loop* inside the wakeup is what makes self-termination reliable.

### `/heartbeat` — recurring re-entry into this session  `id: automation.heartbeat`
- **Surface:** CLI | Gateway/Telegram | TUI
- **Where:** `/heartbeat every <interval> <prompt>` plus the pause/resume/clear/status controls in any chat surface.
- **What it does:** One user-owned recurring instruction bound to a session. When due **and** the session is idle, the prompt is injected as a normal user turn — "keep re-entering THIS conversation", as opposed to cron's "run this job on a schedule in an isolated session".
- **How it works:** `hermes_cli/heartbeat.py`. `HeartbeatState` dataclass = `prompt, interval_seconds, status ("active"|"paused"|"cleared"), created_at, last_fired_at, fire_count`. Persisted in SessionDB `state_meta` under `heartbeat:<session_id>`; the SessionDB handle is the one `hermes_cli.goals._get_session_db()` caches, so goals/heartbeats/loops share one connection. Drivers call `HeartbeatManager.due_prompt()` on a poll cadence (`POLL_SECONDS = 5.0`, not user-facing); a non-None return is the message to inject. Firing is recorded **before** the turn runs so overlapping polls or a long turn cannot double-fire.
- **Inputs / options:** Interval grammar `parse_interval` regex `^\s*(?:every\s+)?(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\s*$` — accepts `10m`, `every 2h`, `every 90 minutes`, fractional values. Unit multipliers: s/sec/secs/second/seconds = 1, m/min/mins/minute/minutes = 60, h/hr/hrs/hour/hours = 3600, d/day/days = 86400. Manager operations: `set(prompt, interval_seconds)`, `pause()`, `resume()`, `clear()`, `status_line()`, `due_prompt()`, plus `migrate_heartbeat_to_session(old, new)`.
- **Outputs / side effects:** Injected prompt template verbatim: `[Heartbeat — recurring instruction, fires every {interval}]` / `{prompt}` / blank / `If there is nothing meaningful to do or report for this instruction right now, reply briefly that nothing has changed and stop — do not invent work.` Status lines: `♥ Heartbeat (every <X>, next in ~<N>s, fired <K>×): <prompt>`, `⏸ Heartbeat (paused, every <X>, fired <K>×): <prompt>`, `Heartbeat (<status>, every <X>…): <prompt>`, and when unset `No heartbeat. Set one with /heartbeat every <interval> <prompt>.`
- **Config / env:** `MIN_INTERVAL_SECONDS = 60` (module constant, not a config key) — anything faster is a busy loop, not a heartbeat.
- **Edge cases / guards:** `parse_interval` returns `None` for "not an interval" and `-1` for "below the floor" so callers can tell the two apart; `set()` raises `interval must be at least 60s` and `heartbeat prompt is empty`. Missed ticks **coalesce** into one — the anchor resets to NOW, never to the theoretical schedule, so a backlog never stacks. `resume()` re-anchors `last_fired_at` to now so resuming does not instantly fire a stale tick. All DB/import failures degrade to "no heartbeat", never a crashed input loop. Session-scoped and in-process: the CLI or gateway process must be running.
- **Rebuild notes:** Record the fire before running the turn, and coalesce missed ticks. A better version would let a heartbeat carry a `--until` condition like `/loop`.

### `/goal` — persistent session goals (Ralph loop)  `id: automation.goal`
- **Surface:** CLI | Gateway/Telegram | TUI | Desktop app
- **Where:** `/goal <text>` and its sub-commands in any chat surface; handler `gateway/slash_commands.py:2733` `_handle_goal_command`.
- **What it does:** Gives Hermes a standing objective that survives across turns. After each turn a lightweight judge model decides whether the goal is satisfied; if not, a continuation prompt is fed back into the same session automatically until the goal is done, the budget runs out, or the user intervenes.
- **How it works:** `hermes_cli/goals.py`. `GoalManager` (`:1409`) + `GoalState` (`:547`) persisted in SessionDB `state_meta` under `goal:<session_id>` (survives `/resume`). Per-turn flow: `evaluate_after_turn()` (`:1863`) → wait-barrier check (short-circuits without burning a turn or calling the judge) → `_check_gates()` (`:1660`, deterministic shell gates run **before** the judge) → `judge_goal()` (`:1169`) → on `continue`, the continuation prompt is appended as an ordinary user message via `run_conversation`.
- **Inputs / options:** Sub-commands, all of them: `/goal <text>` (set/replace; kicks off the first turn immediately), `/goal draft <text>` (draft a structured completion contract from a plain objective, then set it), `/goal show` (print the active contract), `/goal` or `/goal status`, `/goal pause`, `/goal resume` (resets the turn counter to zero), `/goal clear`, `/goal wait <pid> [reason]`, `/goal unwait`, `/goal gate add <command>`, `/goal gate` or `/goal gate list`, `/goal gate remove <N>`, `/goal gate clear`.
- **Outputs / side effects:** `⊙ Goal set (20-turn budget): <goal>` on acceptance; `↻ Continuing toward goal (1/20): <judge's reason>` on each continuation; `⏳ Goal (parked …)` while a wait barrier holds. State fields written: `goal, status (active|paused|done|cleared), turns_used, max_turns, created_at, last_turn_at, last_verdict (done|continue|skipped), last_reason, paused_reason, consecutive_parse_failures, consecutive_transport_failures, subgoals[], waiting_on_pid, waiting_on_session, waiting_until, waiting_reason, waiting_since, contract, gates[]`.
- **Config / env:** `goals.max_turns` (default 20); `auxiliary.goal_judge.*` selects the judge model and `auxiliary.goal_judge.max_tokens` its output budget (default `DEFAULT_JUDGE_MAX_TOKENS = 4096`); `DEFAULT_JUDGE_TIMEOUT = 30.0` s.
- **Edge cases / guards:** Judge failures fail **open** (`continue`) so a broken judge cannot wedge progress; the turn budget is the backstop. `DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES = 3` auto-pauses the loop when the judge keeps returning non-JSON (small models that cannot follow the contract); `DEFAULT_MAX_CONSECUTIVE_TRANSPORT_FAILURES = 5` auto-pauses on repeated API/auth/network errors (a bad key returns 401 every call). Judge inputs are truncated to `_JUDGE_RESPONSE_SNIPPET_CHARS = 4000`. A real user message mid-loop preempts the continuation and pauses the loop for that turn (it is still re-judged after). `migrate_goal_to_session(old, new, reason=…)` (`:874`) carries the goal across compression rotations. `/goal` is explicitly **not** a Kanban bridge: setting a goal never creates a card, and pausing/clearing never touches the board.
- **Rebuild notes:** Continuation as an ordinary user message + a separate cheap judge is the whole architecture; keep the judge fail-open and always cap turns. A better version would let the judge cite the exact evidence span it used.

### `/goal` completion contracts  `id: automation.goal-contract`
- **Surface:** CLI | Gateway/Telegram
- **Where:** `/goal draft <objective>`, `/goal show`, or inline `field: value` lines inside `/goal <text>`.
- **What it does:** Layers a structured definition of "done" onto a goal, so the judge checks a named verification criterion with concrete evidence instead of a loose "looks done".
- **How it works:** `GoalContract` (`hermes_cli/goals.py:334`) with five fields `_CONTRACT_FIELDS = ("outcome","verification","constraints","boundaries","stop_when")`, rendered by `render_block()` (`:363`) with the labels `Outcome`, `Verification`, `Constraints`, `Boundaries`, `Stop when blocked`. `parse_contract(text)` (`:374`) splits the headline from recognized inline prefixes; `draft_contract(objective, timeout=…)` (`:1325`) asks the `goal_judge` auxiliary model with `DRAFT_CONTRACT_SYSTEM_PROMPT` (`:261`) and falls back to a plain free-form goal when the model is unavailable — drafting never blocks setting a goal.
- **Inputs / options:** Recognized inline aliases (`_CONTRACT_ALIASES`, `:305`), all of them → canonical field: `outcome`, `goal`, `done`, `done when` → **outcome**; `verification`, `verify`, `verified by`, `evidence`, `proof` → **verification**; `constraints`, `constraint`, `preserve`, `must not`, `do not change` → **constraints**; `boundaries`, `boundary`, `scope`, `allowed`, `files` → **boundaries**; `stop when`, `stop_when`, `blocked`, `stop if blocked`, `give up when` → **stop_when**.
- **Outputs / side effects:** When a contract is set, the continuation prompt switches to `CONTINUATION_PROMPT_WITH_CONTRACT_TEMPLATE` (`:104`) — `[Continuing toward your standing goal]` / `Goal: {goal}` / `Completion contract:` / `{contract_block}` / `Continue working toward the outcome above. Take the next concrete step. Stay within the stated boundaries and do not violate the constraints. Before claiming the goal is done, satisfy the Verification criterion and show the concrete evidence (command output, file contents, test result). If you hit the stated stop condition or are otherwise blocked and need user input, say so clearly and stop.` — and the judge prompt switches to `JUDGE_USER_PROMPT_WITH_CONTRACT_TEMPLATE` (`:233`).
- **Config / env:** `auxiliary.goal_judge.*`.
- **Edge cases / guards:** Only *known* field prefixes are extracted, so an incidental colon (`Fix bug: the parser drops commas`) is not mangled. Empty fields are omitted everywhere; a goal with no contract behaves exactly like the original free-form goal, and pre-contract state rows load unchanged.
- **Rebuild notes:** A five-field contract with a closed alias table is enough; adding more fields dilutes the judge. A better version would let the contract name a machine-checkable command directly (i.e. auto-create a gate).

### `/subgoal` — mid-loop acceptance criteria  `id: automation.subgoal`
- **Surface:** CLI | Gateway/Telegram
- **Where:** `/subgoal <text>` while a `/goal` is active; handler `gateway/slash_commands.py:3100` `_handle_subgoal_command`.
- **What it does:** Appends extra acceptance criteria to a running goal without resetting the loop. The goal is not marked done until the original objective **and** every subgoal are met.
- **How it works:** `GoalManager.add_subgoal(text)` (`hermes_cli/goals.py:1551`), `remove_subgoal(index_1based)` (`:1566`), `clear_subgoals()` (`:1579`), `render_subgoals()` (`:1588`), `GoalState.render_subgoals_block()` (`:648`). When non-empty, the continuation prompt switches to `CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE` (`:120`) which surfaces them verbatim under `Additional criteria the user added mid-loop:` and the judge prompt switches to `JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE` (`:211`).
- **Inputs / options:** `/subgoal <text>` (append), `/subgoal` with no args (list the numbered subgoals), `/subgoal remove <N>` (1-based), `/subgoal clear` (drop every subgoal, keep the goal).
- **Outputs / side effects:** Errors are surfaced verbatim: `Usage: /subgoal remove <n>`, `/subgoal remove: <n> must be an integer (1-based index).`, `/subgoal remove: <exc>`, `/subgoal clear: <exc>`, `/subgoal: <exc>`. Subgoals persist in `state_meta` alongside the goal so they survive `/resume`.
- **Config / env:** n/a.
- **Edge cases / guards:** Requires an active `/goal`. Setting a new `/goal <text>` replaces the goal and clears the subgoal list; `/goal clear` does the same. Contracts and subgoals compose — subgoals fold in as extra criteria the judge must also satisfy.
- **Rebuild notes:** Keep the criteria list in the same persisted record as the goal so one `/resume` restores both.

### `/goal` quality gates  `id: automation.goal-gates`
- **Surface:** CLI | Gateway/Telegram
- **Where:** `/goal gate add <command>`, `/goal gate` / `/goal gate list`, `/goal gate remove <N>`, `/goal gate clear`.
- **What it does:** Attaches deterministic shell commands that must exit 0 before the LLM judge is even allowed to declare the goal done. A red gate is evidence, not a vibe.
- **How it works:** `GoalGate` (`hermes_cli/goals.py:429`) = `command, timeout_seconds (default 300), max_retries (default 3), attempts, last_exit_code, last_output_tail, last_failed_fingerprint`. `run_gate(gate, cwd=…)` (`:502`) executes it; `_check_gates()` (`:1660`) runs at turn boundary **before** the judge and short-circuits judging on failure, feeding `CONTINUATION_PROMPT_GATE_FAILED_TEMPLATE` (`:135`) back to the agent. `workspace_fingerprint(cwd)` (`:472`) lets a gate that failed on an *unchanged* workspace replay its recorded failure instead of re-running, while still advancing the attempt counter.
- **Inputs / options:** `add <command>` (free-form shell), `list`, `remove <N>` (1-based), `clear`. Per-gate `timeout_seconds` default `DEFAULT_GATE_TIMEOUT_SECONDS = 300`, `max_retries` default `DEFAULT_GATE_MAX_RETRIES = 3`.
- **Outputs / side effects:** The failure continuation reads verbatim: `[Continuing toward your standing goal — a quality gate failed]` / `Goal: {goal}` / `The quality gate command below must pass before this goal can be declared done, and it just failed (attempt {attempt}/{max_retries}):` / `  $ {command}` / `Exit code: {exit_code}` / `Output (tail):` / fenced output / `Fix the underlying problem so this gate passes, then re-run it to confirm. Do not declare the goal complete while any gate fails. If the gate itself is wrong or cannot pass, say so clearly and stop.` Output is bounded to `_GATE_OUTPUT_TAIL_CHARS = 3000` of combined stdout/stderr.
- **Config / env:** n/a (per-gate values live in the goal record).
- **Edge cases / guards:** Exhausting a gate's retries auto-pauses the goal (same shape as the turn-budget pause), telling the user to fix it manually, remove the gate, or `/goal resume`. Gates run only at turn boundary, so `/goal gate …` is safe mid-run on the gateway. Gates persist with the goal and survive `/resume` and context compression.
- **Rebuild notes:** Run the deterministic check before the probabilistic one, and make the failure output the next prompt. The unchanged-workspace replay is what stops a stuck agent burning wall-clock re-running the same red suite.

### `/goal` wait barriers (parking on async work)  `id: automation.goal-wait`
- **Surface:** CLI | Gateway/Telegram
- **Where:** Automatic (judge returns a `wait` verdict) or manual: `/goal wait <pid> [reason]`, `/goal unwait`.
- **What it does:** Parks the goal loop while progress is genuinely gated on long-running async work (CI, a build, a deploy, a rate-limit cooldown) instead of re-poking the agent every turn into "is it done yet?" busy-work.
- **How it works:** Three barrier kinds on `GoalState`: `waiting_on_pid` (park until that process exits — `wait_on(pid, reason)` `:1746`, liveness by `_pid_alive` `:925`), `waiting_on_session` (park until that `process_registry` session's own trigger fires — it exits, or its `watch_patterns` match — `wait_on_session(session_id, reason)` `:1770`, checked by `_session_waiting` `:953`), and `waiting_until` (wall-clock epoch — `wait_for_seconds(seconds, reason)` `:1792`). While any barrier is active, `evaluate_after_turn` short-circuits to `should_continue=False` **without burning a turn or calling the judge**. `stop_waiting()` (`:1813`) and `is_waiting()` (`:1832`) manage it. The judge sees the live background-process list rendered by `gather_background_processes(task_id)` (`:1305`) / `_render_background_block` (`:1123`) via `JUDGE_BACKGROUND_BLOCK_TEMPLATE` (`:195`) and can therefore return `wait`.
- **Inputs / options:** `/goal wait <pid> [reason]`, `/goal unwait`. Judge-set barriers carry `waiting_reason` and `waiting_since`.
- **Outputs / side effects:** `/goal status` shows `⏳ Goal (parked …)` while parked. The barrier persists in `state_meta` and survives `/resume`.
- **Config / env:** n/a.
- **Edge cases / guards:** A dead PID at set time (or a process that dies while parked), a fired session trigger, or an elapsed deadline clears the barrier on the next check — a stale barrier can never wedge the loop. `/goal pause`, `/goal resume` and `/goal clear` all drop it. `waiting_on_session` is preferred over a raw pid for long-lived watchers/servers that signal mid-run and may never exit.
- **Rebuild notes:** Show the judge the agent's live background processes and let it return a third verdict; polling the agent to poll a process is the waste this removes.

### `/goal` judge  `id: automation.goal-judge`
- **Surface:** Core
- **Where:** Invisible; runs after every turn while a goal is active.
- **What it does:** A small auxiliary-model call that returns `done` / `continue` / `wait` with a reason, deciding whether the goal loop keeps going.
- **How it works:** `judge_goal(goal, response, …)` (`hermes_cli/goals.py:1169`) sends `JUDGE_SYSTEM_PROMPT` (`:152`) plus one of `JUDGE_USER_PROMPT_TEMPLATE` (`:201`), `JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE` (`:211`) or `JUDGE_USER_PROMPT_WITH_CONTRACT_TEMPLATE` (`:233`), and parses the reply with `_parse_judge_response` (`:1026`) / `_extract_json_object` (`:1377`) / `_JSON_OBJECT_RE`. The verdict tuple is `(verdict, reason, parse_failed, wait_spec, transport_failed)`; `_first_int` (`:1095`) extracts pid/seconds fields from the wait spec.
- **Inputs / options:** Judge sees: the standing goal text, the agent's last response (truncated to 4000 chars), recent messages, any subgoals/contract, and the background-process block.
- **Outputs / side effects:** One-line JSON verdict; drives continuation, stop or park.
- **Config / env:** `auxiliary.goal_judge.max_tokens` (`_goal_judge_max_tokens`, `:974`, default 4096 — 200 truncated reasoning models' JSON), `_goal_judge_timeout` (`:998`, default 30 s).
- **Edge cases / guards:** Deliberately conservative — `done` only when the response *explicitly* confirms completion, the final deliverable is clearly produced, or the goal is unachievable/blocked (treated as DONE with a block reason so budget is not burned on impossible tasks). Parse failures and transport failures are counted separately and auto-pause at 3 and 5 consecutive occurrences respectively.
- **Rebuild notes:** Ask for a single JSON object, extract it with a regex rather than strict parsing, and budget enough tokens for reasoning models' hidden preamble.

### `/refine` — run the self-improvement review now  `id: automation.refine`
- **Surface:** CLI | Gateway/Telegram (Slack: `/hermes refine …`)
- **Where:** `/refine [focus]`; handler `gateway/slash_commands.py:2999`.
- **What it does:** Runs the background memory/skill self-improvement review immediately instead of waiting for its automatic post-turn trigger. Optional focus text steers it (e.g. `/refine save the deploy workflow as a skill`).
- **How it works:** Forks a background review against a *conversation snapshot*, so the live session and its prompt cache are untouched; results are reported when the fork finishes.
- **Inputs / options:** Optional free-form `focus` argument appended to the command.
- **Outputs / side effects:** Refusal while a turn is in flight: `Agent is running — wait for the turn to finish, then /refine.`; start failure: `/refine failed to start: <exc>`. On success the review's findings (new/updated memories and skills) are reported into the chat.
- **Config / env:** Governed by the same self-improvement/curator configuration that drives the automatic trigger (see the agent-core shard).
- **Edge cases / guards:** Cannot run concurrently with an active turn. The fork never mutates the live session.
- **Rebuild notes:** Snapshot-and-fork is the safe way to run a second model pass over a live conversation.

---

## 3. Kanban — the durable multi-profile task board

### `hermes kanban` (command group)  `id: automation.kanban-group`
- **Surface:** CLI
- **Where:** `hermes kanban [--board <slug>] <subcommand>`; help header verbatim: `Durable SQLite-backed task board shared across Hermes profiles. Tasks are claimed atomically, can depend on other tasks, and are executed by a named profile in an isolated workspace. See https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban or docs/hermes-kanban-v1-spec.pdf for the full design.`
- **What it does:** The board where multi-agent work lives. Cards (tasks) are created, linked into dependency graphs, claimed atomically by worker profiles, executed in isolated workspaces, reviewed, and completed — all durably in SQLite.
- **How it works:** `hermes_cli/kanban.py` (3542 lines, argparse + rendering) over `hermes_cli/kanban_db.py` (12150 lines, the kernel). Storage is one SQLite DB per board: the `default` board at `<kanban-root>/kanban.db` with `<kanban-root>/kanban/{attachments,logs,workspaces}/`, other boards under `<kanban-root>/boards/<slug>/`. WAL mode, `busy_timeout` from `HERMES_KANBAN_BUSY_TIMEOUT_MS`, and a connect-time integrity guard that quarantines and REINDEXes index-only corruption.
- **Inputs / options:** `-h, --help`; `--board <slug>` — "Board slug to operate on. Defaults to the current board (set via `hermes kanban boards switch <slug>` or the HERMES_KANBAN_BOARD env var). Use `hermes kanban boards list` to see all boards." Sub-commands — 45 distinct (47 names counting the `ls` and `diag` aliases), all of them: `init`, `boards`, `create`, `swarm`, `list` (`ls`), `show`, `assign`, `set-model`, `reclaim`, `reassign`, `diagnostics` (`diag`), `link`, `unlink`, `claim`, `comment`, `attach`, `attachments`, `attach-rm`, `complete`, `edit`, `block`, `schedule`, `unblock`, `request-review`, `request-changes`, `reopen-review`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`, `repair`.
- **Outputs / side effects:** Writes to the board DB, the workspaces tree, attachments and worker logs.
- **Config / env:** `kanban.*` config tree (see individual entries); env `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_DB`, `HERMES_KANBAN_HOME`, `HERMES_KANBAN_ATTACHMENTS_ROOT`, `HERMES_KANBAN_WORKSPACES_ROOT`, `HERMES_KANBAN_BUSY_TIMEOUT_MS`, `HERMES_KANBAN_CLAIM_LOCK`, `HERMES_KANBAN_CLAIM_TTL_SECONDS`, `HERMES_KANBAN_CRASH_GRACE_SECONDS`, `HERMES_KANBAN_DISPATCH_IN_GATEWAY`, `HERMES_KANBAN_GOAL_MODE`, `HERMES_KANBAN_RUN_ID`, `HERMES_KANBAN_STOP_NUDGE`, `HERMES_KANBAN_TASK`, `HERMES_PROFILE`.
- **Edge cases / guards:** `_assert_not_delegated_child_mutation()` (`hermes_cli/kanban_db.py:165`) rejects every board mutation from a `delegate_task` child context at the DB/filesystem layer — not merely in the tool wrapper — so a delegated child cannot shell out to the CLI to mutate the board.
- **Rebuild notes:** One SQLite file per board, atomic claims via a conditional UPDATE, and an append-only event log is the entire durable core; everything else is policy on top.

### Kanban task states  `id: automation.kanban-states`
- **Surface:** Core
- **Where:** The `status` column of every card; the `--status` filter of `hermes kanban list`; the dashboard's board columns.
- **What it does:** Defines the lifecycle a card moves through.
- **How it works:** `VALID_STATUSES` (`hermes_cli/kanban_db.py:102`) = `{"triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"}`. `VALID_INITIAL_STATUSES` (`:103`) = `{"running", "blocked"}` — the only non-default statuses a card may be *created* in. Transitions: new cards land in `todo` (or `triage` with `--triage`); `recompute_ready` promotes `todo → ready` once every parent link is done/archived; the dispatcher claims `ready → running`; a worker ends in `done`, `blocked`, `review`, or (on failure) back through the retry path; `scheduled` parks a card waiting on time; `archived` retires it.
- **Inputs / options:** Nine statuses exactly as listed. `--status` on `list` accepts them in the sorted order `{archived,blocked,done,ready,review,running,scheduled,todo,triage}`.
- **Outputs / side effects:** Every status change appends a `task_events` row.
- **Config / env:** n/a.
- **Edge cases / guards:** `dependency`-kind blocks are routed to `todo`, never `blocked`, so the existing parent-gating machinery promotes them automatically with no human and no retry storm.
- **Rebuild notes:** Separating `todo` (waiting on dependencies) from `blocked` (waiting on a human) from `scheduled` (waiting on time) is what keeps an automatic promoter from fighting a human.

### Kanban task record (`tasks` table)  `id: automation.kanban-task-record`
- **Surface:** Core
- **Where:** `tasks` table of each board's `kanban.db`.
- **What it does:** Holds everything about a card.
- **How it works:** DDL at `hermes_cli/kanban_db.py:1333`. Indexes `idx_tasks_assignee_status(assignee,status)`, `idx_tasks_status(status)`, `idx_tasks_tenant(tenant)`, `idx_tasks_idempotency(idempotency_key)`, `idx_tasks_session_id(session_id)`.
- **Inputs / options:** Columns, all of them: `id` (TEXT PK), `title`, `body`, `assignee`, `status`, `priority` (INTEGER default 0), `created_by`, `created_at`, `started_at`, `completed_at`, `workspace_kind` (default `scratch`), `workspace_path`, `branch_name`, `project_id`, `claim_lock`, `claim_expires`, `tenant`, `result`, `idempotency_key`, `consecutive_failures` (default 0), `worker_pid`, `last_failure_error`, `max_runtime_seconds`, `last_heartbeat_at`, `current_run_id`, `workflow_template_id`, `current_step_key`, `skills` (JSON array), `model_override`, `provider_override`, `reasoning_effort`, `max_retries`, `goal_mode` (0/1), `goal_max_turns`, `session_id`, `block_kind`, `block_recurrences` (default 0).
- **Outputs / side effects:** n/a (storage).
- **Config / env:** `HERMES_KANBAN_DB` overrides the DB path.
- **Edge cases / guards:** `consecutive_failures` is reset **only** on successful completion; `block_recurrences` is reset only on successful completion too (resetting it on unblock is precisely the amnesia that let unblock loops run unbounded). `workflow_template_id` / `current_step_key` are forward-compat v2 columns the v1 kernel writes but does not route on.
- **Rebuild notes:** Put claim state, PID, heartbeat and runtime cap on the **run**, not the task; the task keeps only a denormalised `current_run_id` pointer.

### Kanban runs (`task_runs`) and attempt history  `id: automation.kanban-runs`
- **Surface:** Core / CLI
- **Where:** `hermes kanban runs <task_id>` and the run list inside `hermes kanban show`.
- **What it does:** Records one row per dispatch attempt so retries after crash/timeout/block are auditable.
- **How it works:** DDL at `hermes_cli/kanban_db.py:1458`. Columns: `id, task_id, profile, step_key, status, claim_lock, claim_expires, worker_pid, max_runtime_seconds, last_heartbeat_at, started_at, ended_at, outcome, summary, metadata, error`. Indexes `idx_runs_task(task_id, started_at)` and `idx_runs_status(status)`. `_end_run` (`hermes_cli/kanban_db.py:4335`) closes a run with an outcome.
- **Inputs / options:** `hermes kanban runs [-h] [--json] [--state-type {status,outcome}] [--state-name VALUE] task_id` — `--state-type`/`--state-name` filter runs by the named `task_runs` column. The same two flags exist on `hermes kanban show`.
- **Outputs / side effects:** Prints one row per run: profile, outcome, elapsed, summary.
- **Config / env:** n/a.
- **Edge cases / guards:** `status` domain: `running | done | blocked | crashed | timed_out | failed | released`. `outcome` domain: `completed | blocked | crashed | timed_out | spawn_failed | gave_up | reclaimed | NULL` (null while still running).
- **Rebuild notes:** Model attempts as first-class rows; a single mutable "last error" field on the task loses the history you need to debug a flapping card.

### Kanban events (`task_events`)  `id: automation.kanban-events`
- **Surface:** Core / CLI
- **Where:** `hermes kanban tail <task_id>`, `hermes kanban watch`, `hermes kanban show`, and the dashboard's activity stream.
- **What it does:** Append-only audit log of everything that happens to a card, optionally grouped by run.
- **How it works:** DDL at `hermes_cli/kanban_db.py:1442`: `id, task_id, run_id, kind, payload (JSON), created_at`; indexes `idx_events_task(task_id, created_at)` and `idx_events_run(run_id, id)`. Written by `_append_event(conn, task_id, kind, payload=None, *, run_id=None)` (`:4311`); read by `list_events` (`:4287`). Events not scoped to one attempt (created/edited/archived, dependency promotion) carry `run_id = NULL`.
- **Inputs / options:** Event `kind` values emitted by the kernel, all of them: `archived`, `assigned`, `attached`, `attachment_removed`, `block_loop_detected`, `blocked`, `changes_requested`, `claim_rejected`, `claimed`, `commented`, `completed`, `completion_blocked_hallucination`, `created`, `decomposed`, `dependency_wait`, `edited`, `error`, `gave_up`, `heartbeat`, `linked`, `model_override_set`, `promoted`, `promoted_manual`, `reasoning_effort_set`, `reclaim_deferred`, `reclaimed`, `reconciled`, `review_reopened`, `review_requested`, `scheduled`, `spawned`, `specified`, `stale`, `suspected_hallucinated_references`, `timed_out`, `tip_scratch_workspace`, `unblocked`, `unlinked`; the dispatcher additionally records `crashed`, `spawn_failed` and `spawn_auto_blocked` outcomes.
- **Outputs / side effects:** Drives the notifier subscriptions, the CLI watchers, and the dashboard.
- **Config / env:** `hermes kanban gc --event-retention-days N` (default 30) deletes events of terminal tasks older than N days.
- **Edge cases / guards:** `_resume_status_from_events` (`:4492`) reconstructs a task's status from its event history during recovery.
- **Rebuild notes:** Never mutate events; derive status from them when the task row is suspect.

### `hermes kanban init`  `id: automation.kanban-init`
- **Surface:** CLI
- **Where:** `hermes kanban init`; help `Create kanban.db if missing (idempotent)`.
- **What it does:** Creates the board database and its directory layout.
- **How it works:** Runs the DDL block (`CREATE TABLE IF NOT EXISTS` + additive `ALTER`s) plus index creation; safe to re-run.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** Creates `kanban.db` and the `attachments/`, `logs/`, `workspaces/` directories.
- **Config / env:** `HERMES_KANBAN_DB`, `HERMES_KANBAN_HOME`.
- **Edge cases / guards:** Idempotent; every other subcommand also auto-initialises.
- **Rebuild notes:** Make schema creation additive-only so an old binary can open a new DB.

### `hermes kanban boards`  `id: automation.kanban-boards`
- **Surface:** CLI
- **Where:** `hermes kanban boards <sub>`; group help verbatim: `Boards let you separate unrelated streams of work (projects, repos, domains) into isolated queues. Each board has its own DB, workspaces directory, and dispatcher loop — tasks on one board cannot collide with tasks on another. The first board is 'default' and always exists.`
- **What it does:** Creates, lists, switches, renames, archives, exports and imports boards.
- **How it works:** Board metadata is stored per board directory; the "current" board is a persisted CLI setting overridden by `HERMES_KANBAN_BOARD` or `--board`.
- **Inputs / options:** Sub-commands and every flag: **`list` (`ls`)** `[--json] [--all]` — `--all` "Include archived boards too"; **`create` (`new`)** `<slug> [--name NAME] [--description DESCRIPTION] [--icon ICON] [--color COLOR] [--switch] [--default-workdir PATH]` — slug help "Board slug (kebab-case, e.g. atm10-server)", `--name` "Human-readable display name (defaults to Title Case of slug)", `--icon` "Optional emoji or single-character icon for the dashboard", `--color` "Optional hex color (e.g. '#8b5cf6') for the dashboard", `--switch` "Switch to the new board after creating it", `--default-workdir` "Default workspace path for tasks created on this board"; **`rm` (`remove`, `delete`)** `<slug> [--delete]` — `--delete` "Hard-delete the board directory instead of archiving it. Default is to move it to boards/_archived/ so it's recoverable."; **`switch` (`use`)** `<slug>`; **`show` (`current`)** (no flags) — prints the active slug; **`rename`** `<slug> <name>` — "New display name" (slug is immutable); **`set-default-workdir`** `<slug> [path]` — "Absolute path to use as default workdir. Omit to clear."; **`export`** `[slug] [-o OUTPUT] [--no-attachments] [--include-logs] [--json]`; **`import`** `<archive> [--as AS_SLUG] [--switch] [--json]`.
- **Outputs / side effects:** Board directories under `<kanban-root>/boards/<slug>/`; archived boards move to `boards/_archived/`.
- **Config / env:** `HERMES_KANBAN_BOARD`.
- **Edge cases / guards:** The `default` board always exists and cannot be removed; its on-disk layout is split (`<root>/kanban.db` beside `<root>/kanban/attachments/`) while every other board lives entirely inside `boards/<slug>/`.
- **Rebuild notes:** Per-board DB + per-board dispatcher loop is what makes cross-project isolation real rather than a tag.

### `hermes kanban boards export` / `import` (board transfer)  `id: automation.kanban-transfer`
- **Surface:** CLI | API
- **Where:** `hermes kanban boards export [slug]` / `hermes kanban boards import <archive>`; also the REST endpoints `/boards/{slug}/export` and `/boards/import`, and the desktop board switcher's Export/Import items.
- **What it does:** Moves a whole board between machines as one portable `.tar.gz`, scrubbed of machine-local state.
- **How it works:** `hermes_cli/kanban_transfer.py`. `export_board()` (`:153`) takes a **consistent** snapshot with SQLite's online-backup API (`_snapshot_db`, `:76`) — a plain file copy of a WAL-mode DB being written by a dispatcher yields a torn image — then `_scrub_local_state(conn)` (`:95`) strips claims, worker PIDs, heartbeats, absolute workspace/attachment paths, gateway chat subscriptions and session ids. `_count_rows` (`:142`) records provenance counts into `manifest.json`. `import_board()` (`:386`) reads the manifest (`_read_manifest`, `:262`) and board metadata (`_read_board_metadata`, `:286`), picks a free slug (`_available_slug`, `:243`, auto-suffixing on collision), and re-scrubs + re-points rows (`_relocate_imported_rows`, `:295`). Extraction uses `hermes_cli/archive_safe.py` (`safe_extract_targz`, `archive_root_dirs`, `copy_regular_files`, `make_targz`).
- **Inputs / options:** Export: `[slug]` (default current board), `-o/--output OUTPUT` (default `./<slug>.tar.gz`), `--no-attachments` "Skip attachment files, keeping the archive small", `--include-logs` "Include per-task worker logs", `--json`. Import: `archive` (path), `--as AS_SLUG` "Slug for the imported board (default: from the archive)", `--switch`, `--json`.
- **Outputs / side effects:** Archive layout, verbatim: `<slug>/manifest.json` (format + version + provenance + row counts), `<slug>/board.json` (display metadata, machine-local fields stripped), `<slug>/kanban.db`, `<slug>/attachments/<task>/…`, `<slug>/logs/<task>.log`. Workspaces are **never** included — they are rebuilt on demand.
- **Config / env:** n/a.
- **Edge cases / guards:** Imports always land as a **new** board (slug auto-suffixes on collision), so an import can never mutate or merge into an existing board; that also guarantees an imported board is never `default`, which lets the import path ignore the default board's split on-disk layout.
- **Rebuild notes:** Online-backup for the snapshot and a two-sided scrub (export *and* import) are both required — the latter defends against a hand-edited archive.

### `hermes kanban create`  `id: automation.kanban-create`
- **Surface:** CLI
- **Where:** `hermes kanban create <title> [flags]`; help `Create a new task`.
- **What it does:** Adds a card to the board, with everything a worker will need: body, assignee, dependencies, workspace kind, skills, model pins, retry policy and goal mode.
- **How it works:** `hermes_cli/kanban.py` → `kanban_db.create_task`. New cards default to `todo`; `--triage` parks them in `triage` for the specifier/decomposer.
- **Inputs / options:** positional `title` "Task title"; flags, all 19: `-h, --help`; `--body BODY` "Optional opening post"; `--assignee ASSIGNEE` "Profile name to assign"; `--parent PARENT` "Parent task id (repeatable)"; `--workspace WORKSPACE` "scratch | worktree | worktree:<path> | dir:<path> (default: scratch)"; `--branch BRANCH` "Branch name for worktree tasks, e.g. wt/t6-wire"; `--project PROJECT` "Link to a project (id or slug). Anchors the task's worktree under the project's primary repo with a deterministic branch. See `hermes project list`."; `--tenant TENANT` "Tenant namespace"; `--priority PRIORITY` "Priority tiebreaker"; `--triage` "Park in triage — a specifier will flesh out the spec and promote to todo"; `--idempotency-key IDEMPOTENCY_KEY` "Dedup key. If a non-archived task with this key exists, its id is returned instead of creating a duplicate."; `--max-runtime MAX_RUNTIME` "Per-task runtime cap. Accepts seconds (300) or durations (90s, 30m, 2h, 1d). When exceeded, the dispatcher SIGTERMs (then SIGKILLs) the worker and re-queues the task."; `--created-by CREATED_BY` "Author name recorded on the task (default: user)"; `--skill SKILLS` "Skill to force-load into the worker (repeatable). The kanban lifecycle is already injected automatically. Example: --skill translation --skill github-code-review"; `--max-retries N` "Per-task override for the consecutive-failure circuit breaker. Trip on the Nth failure — e.g. --max-retries 1 blocks on the first failure (no retries), --max-retries 3 allows two retries. Omit to use the dispatcher's kanban.failure_limit config (default 2)."; `--model MODEL_OVERRIDE` "Pin the worker to this model (passed as -m <model>) without changing the profile's configured model. Combine with --provider when the model belongs to a different backend than the profile's default."; `--provider PROVIDER_OVERRIDE` "Provider the --model belongs to (passed as --provider <name> to the worker). Requires --model."; `--goal` "Run the worker in a goal loop: after each turn a judge checks the response against the card title/body and, if not done, the worker keeps going in the same session until the judge agrees it's complete (or the turn budget runs out, which blocks the card for review). Best for open-ended cards one shot rarely finishes."; `--goal-max-turns N` "Turn budget for --goal workers (default 20). Ignored without --goal."; `--initial-status {blocked,running}` "Initial card status. Use 'blocked' for cards that require immediate human ops (R3 gate) to skip the brief running-to-blocked transition."; `--json` "Emit JSON output".
- **Outputs / side effects:** Inserts a `tasks` row and a `created` event; `--json` prints the task id and fields.
- **Config / env:** `kanban.default_assignee`, `kanban.auto_subscribe_on_create` (default `true`), `HERMES_SESSION_ID` (captured into `session_id` when created from inside an agent loop).
- **Edge cases / guards:** `--idempotency-key` returns the existing non-archived task's id instead of creating a duplicate. `--provider` requires `--model`. Workspace kinds are validated against `VALID_WORKSPACE_KINDS = {"scratch","worktree","dir"}`.
- **Rebuild notes:** Make the card carry its own execution policy (skills, model, retries, runtime cap, goal mode) so the dispatcher stays a dumb scheduler.

### `hermes kanban list` (alias `ls`)  `id: automation.kanban-list`
- **Surface:** CLI
- **Where:** `hermes kanban list [flags]`; help `List tasks`.
- **What it does:** Lists cards with filters and a chosen sort order.
- **How it works:** `kanban_db.list_tasks()` (`hermes_cli/kanban_db.py:3661`) builds `SELECT * FROM tasks WHERE 1=1 …` with the sort clause from `VALID_SORT_ORDERS` (`:3649`).
- **Inputs / options:** `-h, --help`; `--mine` "Filter by $HERMES_PROFILE as assignee"; `--assignee ASSIGNEE`; `--status {archived,blocked,done,ready,review,running,scheduled,todo,triage}`; `--tenant TENANT`; `--session SESSION` "Filter by originating chat/agent session id (set on tasks created from inside an ACP loop)"; `--archived` "Include archived tasks"; `--json`; `--sort {assignee,created,created-desc,priority,priority-desc,status,title,updated}` "Sort order for listed tasks (default: priority)"; `--workflow-template-id ID`; `--step-key KEY`.
- **Outputs / side effects:** stdout table or JSON.
- **Config / env:** `HERMES_PROFILE` backs `--mine`.
- **Edge cases / guards:** Sort clauses verbatim: `created` → `created_at ASC, id ASC`; `created-desc` → `created_at DESC, id DESC`; `priority` → `priority DESC, created_at ASC`; `priority-desc` → `priority ASC, created_at ASC`; `status` → `status ASC, created_at ASC`; `assignee` → `assignee ASC, created_at ASC`; `title` → `title ASC, id ASC`; `updated` → `started_at DESC NULLS LAST, created_at DESC`.
- **Rebuild notes:** Whitelist sort orders as a name→SQL map; never interpolate a user string into ORDER BY.

### `hermes kanban show`  `id: automation.kanban-show`
- **Surface:** CLI
- **Where:** `hermes kanban show <task_id> [--json] [--state-type {status,outcome}] [--state-name VALUE]`; help `Show a task with comments + events`.
- **What it does:** Prints one card in full: fields, comments, events and its run history.
- **How it works:** Joins `tasks`, `task_comments`, `task_events` and `task_runs`.
- **Inputs / options:** positional `task_id`; `-h, --help`; `--json`; `--state-type {status,outcome}` "With --state-name: filter listed runs by task_runs column"; `--state-name VALUE` "With --state-type: keep runs whose column equals this value".
- **Outputs / side effects:** stdout only.
- **Config / env:** n/a.
- **Edge cases / guards:** The two state flags must be used together.
- **Rebuild notes:** One command that shows the card *and* its history removes most of the need for a UI during debugging.

### `hermes kanban assign` / `reassign` / `set-model`  `id: automation.kanban-assign`
- **Surface:** CLI
- **Where:** `hermes kanban assign <task_id> <profile>`; `hermes kanban reassign <task_id> <profile> [--reclaim] [--reason REASON]`; `hermes kanban set-model <task_id> [model] [--provider PROVIDER]`.
- **What it does:** Routes a card to a worker profile, moves it to another profile (optionally releasing a live claim first), and pins or clears a per-task model/provider override.
- **How it works:** `assign` writes `tasks.assignee` and an `assigned` event. `reassign` optionally calls the reclaim path first, then reassigns, recording a `reclaimed` event with the reason. `set-model` writes `model_override`/`provider_override` and a `model_override_set` event; it takes effect on the **next** dispatch.
- **Inputs / options:** `assign`: positional `task_id`, positional `profile` "Profile name (or 'none' to unassign)". `reassign`: positional `task_id`, positional `profile` "New profile name (or 'none' to unassign)", `--reclaim` "Release any active claim before reassigning (required if task is running)", `--reason REASON` "Human-readable reason (recorded on the reclaimed event)". `set-model`: positional `task_id`, optional positional `model` "Model to pin the worker to (or 'none' to clear the override)", `--provider PROVIDER` "Provider the model belongs to (worker is spawned with --provider <name>). Cleared together with the model."
- **Outputs / side effects:** Task row + event rows.
- **Config / env:** `kanban.default_assignee` supplies the default when unassigned.
- **Edge cases / guards:** `reassign` on a running task requires `--reclaim`. Clearing the model also clears the provider.
- **Rebuild notes:** Make "reassign a running card" an explicit two-step (reclaim then assign) so nobody silently strands a worker.

### `hermes kanban reclaim`  `id: automation.kanban-reclaim`
- **Surface:** CLI
- **Where:** `hermes kanban reclaim <task_id> [--reason REASON]`; help `Release an active worker claim on a running task`.
- **What it does:** Frees a card that a worker holds but is no longer progressing, so the dispatcher can re-queue it.
- **How it works:** Clears `claim_lock`/`claim_expires`/`worker_pid` on the task and closes the run with outcome `reclaimed`; appends a `reclaimed` event carrying the reason. `reclaim_deferred` is emitted when the claim cannot be released yet.
- **Inputs / options:** positional `task_id`; `-h, --help`; `--reason REASON` "Human-readable reason (recorded on the reclaimed event)".
- **Outputs / side effects:** Task returns to a dispatchable state; the run's outcome is recorded.
- **Config / env:** `HERMES_KANBAN_CLAIM_TTL_SECONDS`, `HERMES_KANBAN_CRASH_GRACE_SECONDS` govern automatic stale reclaim in the dispatcher.
- **Edge cases / guards:** Manual reclaim is the recovery path when the dispatcher's stale detection has not yet fired.
- **Rebuild notes:** Always record who reclaimed and why; silent reclaims make double-execution impossible to diagnose.

### `hermes kanban claim`  `id: automation.kanban-claim`
- **Surface:** CLI
- **Where:** `hermes kanban claim <task_id> [--ttl TTL]`; help `Atomically claim a ready task (prints resolved workspace path)`.
- **What it does:** Takes exclusive ownership of a ready card and prints the workspace directory the worker should run in.
- **How it works:** A conditional UPDATE writes `claim_lock` (a token) + `claim_expires = now + ttl` only when the card is unclaimed or its claim has expired, which makes the claim atomic across processes. A new `task_runs` row is opened and `tasks.current_run_id` is pointed at it; a `claimed` event is appended (`claim_rejected` when the CAS loses).
- **Inputs / options:** positional `task_id`; `-h, --help`; `--ttl TTL` "Claim TTL in seconds (default: 900)".
- **Outputs / side effects:** Prints the resolved workspace path (scratch dir, worktree, or explicit dir).
- **Config / env:** `HERMES_KANBAN_CLAIM_LOCK` (the token), `HERMES_KANBAN_CLAIM_TTL_SECONDS`.
- **Edge cases / guards:** Claims expire, so a crashed worker's card becomes claimable again after the TTL plus the crash grace period.
- **Rebuild notes:** Compare-and-swap on `(claim_lock IS NULL OR claim_expires < now)` is the whole atomicity story; do not use a separate lock table.

### `hermes kanban heartbeat`  `id: automation.kanban-heartbeat`
- **Surface:** CLI
- **Where:** `hermes kanban heartbeat <task_id> [--note NOTE]`; help `Emit a heartbeat event for a running task (worker liveness signal)`.
- **What it does:** Lets a long-running worker prove it is alive so the dispatcher's stale-claim sweep does not reclaim its card.
- **How it works:** Updates `tasks.last_heartbeat_at` and `task_runs.last_heartbeat_at`, and appends a `heartbeat` event.
- **Inputs / options:** positional `task_id`; `-h, --help`; `--note NOTE` "Optional short note attached to the heartbeat event".
- **Outputs / side effects:** Event row; freshness used by the reclaim logic.
- **Config / env:** `HERMES_KANBAN_CRASH_GRACE_SECONDS`.
- **Edge cases / guards:** A worker that never heartbeats is still protected by its claim TTL, but a long job must heartbeat or be reclaimed.
- **Rebuild notes:** Heartbeat on the run, not the task, so a retried card's liveness is per attempt.

### `hermes kanban complete` / `edit`  `id: automation.kanban-complete`
- **Surface:** CLI
- **Where:** `hermes kanban complete <task_ids…> [--result R] [--summary S] [--metadata JSON]`; `hermes kanban edit <task_id> --result R [--summary S] [--metadata JSON]`.
- **What it does:** Marks cards done with a result and a structured handoff summary downstream cards can read; `edit` backfills those fields on an already-completed card.
- **How it works:** `complete` sets `status='done'`, `completed_at`, `result`, closes the active run with outcome `completed`, stores `summary`/`metadata` on the run, resets `consecutive_failures` and `block_recurrences`, and triggers `recompute_ready` for children.
- **Inputs / options:** `complete`: positional `task_ids` (one or more; "only --result applies to all of them"), `--result RESULT` "Result summary", `--summary SUMMARY` "Structured handoff summary for downstream tasks. Falls back to --result if omitted.", `--metadata METADATA` "JSON dict of structured facts (e.g. '{\"changed_files\": [...], \"tests_run\": 12}'). Stored on the closing run." `edit`: positional `task_id`, required `--result RESULT` "Backfilled task result text for a done task", `--summary SUMMARY`, `--metadata METADATA` "JSON dict of structured facts to store on the latest completed run."
- **Outputs / side effects:** `completed` event; children may be promoted `todo → ready`.
- **Config / env:** n/a.
- **Edge cases / guards:** A `completion_blocked_hallucination` event is emitted when the completion claims artefacts that do not exist; `suspected_hallucinated_references` flags dubious references without hard-blocking.
- **Rebuild notes:** The handoff `summary` is what downstream cards actually consume — keep it separate from the human-facing `result`.

### `hermes kanban block` / `schedule` / `unblock`  `id: automation.kanban-block`
- **Surface:** CLI
- **Where:** `hermes kanban block <task_id> [reason…] [--ids …] [--kind …]`; `hermes kanban schedule <task_id> [reason…] [--ids …]`; `hermes kanban unblock <task_ids…> [--reason REASON]`.
- **What it does:** Parks a card as blocked (waiting on a human or a dependency), scheduled (waiting on time), or returns it to the queue.
- **How it works:** `block_task` routes by `block_kind`: `dependency` → `todo` (parent-gating promotes it automatically, no human); `needs_input` and `capability` → `blocked` (a human must act); `transient` → marks a maybe-flaky failure. `block_kind` is preserved across unblock so a re-block for the same kind is recognised as a loop; `block_recurrences` increments and at `BLOCK_RECURRENCE_LIMIT = 2` the card is routed to `triage` instead of `blocked` (event `block_loop_detected`). `schedule` sets `status='scheduled'` with a `scheduled` event. `unblock` returns cards to `ready`, or to `todo` while parents remain open.
- **Inputs / options:** `block`: positional `task_id`, positional `reason` (variadic; "Reason (also appended as a comment)"), `--ids IDS [IDS …]` "Additional task ids to block with the same reason (bulk mode)", `--kind {capability,dependency,needs_input,transient}` "Typed block reason. 'dependency' waits in todo (auto-promoted when parents finish, no human); 'needs_input'/'capability' go to blocked for a human; 'transient' marks a maybe-flaky failure. Repeated same-kind re-blocks after unblock route the task to triage to break unblock loops. Omit for a generic block." `schedule`: positional `task_id`, variadic `reason` "Reason/timing note (also appended as a comment)", `--ids IDS [IDS …]`. `unblock`: positional `task_ids` (one or more), `--reason REASON` "Optional reason/note — recorded as a comment before unblocking. Quote multi-word reasons."
- **Outputs / side effects:** `blocked` / `scheduled` / `unblocked` events; the reason is also appended as a comment.
- **Config / env:** n/a.
- **Edge cases / guards:** `block_recurrences` resets **only** on a successful completion, never on unblock — that is what makes the loop breaker work.
- **Rebuild notes:** Typing the block reason is the single highest-value change here; one undifferentiated "blocked" bucket guarantees an unblock↔re-block storm.

### `hermes kanban promote`  `id: automation.kanban-promote`
- **Surface:** CLI
- **Where:** `hermes kanban promote <task_id> [reason…] [--ids …] [--force] [--dry-run] [--json]`; help `Manually move one or more todo/blocked tasks to ready (recovery path)`.
- **What it does:** Forces a card into `ready` when the automatic parent-gating did not (or should be overridden).
- **How it works:** Validates parent dependencies unless `--force`, then sets `status='ready'` and appends a `promoted_manual` event carrying the reason (the automatic path emits `promoted`).
- **Inputs / options:** positional `task_id`; positional variadic `reason` "Audit-trail reason (recorded on the task_events row)"; `-h, --help`; `--ids IDS [IDS …]` "Additional task ids to promote with the same reason (bulk mode)"; `--force` "Promote even if parent dependencies are not yet done/archived"; `--dry-run` "Validate the promotion without mutating state"; `--json` "Emit machine-readable JSON result".
- **Outputs / side effects:** Status change + event; `--dry-run` mutates nothing.
- **Config / env:** n/a.
- **Edge cases / guards:** Distinguishing `promoted` from `promoted_manual` in the event log is what lets you tell automatic gating from a human override.
- **Rebuild notes:** Always offer `--dry-run` on a recovery command.

### `hermes kanban link` / `unlink`  `id: automation.kanban-link`
- **Surface:** CLI
- **Where:** `hermes kanban link <parent_id> <child_id>` / `hermes kanban unlink <parent_id> <child_id>`; help `Add a parent->child dependency` / `Remove a parent->child dependency`.
- **What it does:** Builds the dependency graph: a child stays in `todo` until every parent is done or archived.
- **How it works:** Rows in `task_links(parent_id, child_id)` with a composite primary key; indexes `idx_links_child` and `idx_links_parent`. `recompute_ready` walks the links to promote `todo → ready`. Events `linked` / `unlinked`; `dependency_wait` records that a card is gated.
- **Inputs / options:** positional `parent_id`, positional `child_id`; `-h, --help`.
- **Outputs / side effects:** Link rows; possible promotion of the child when the last parent completes.
- **Config / env:** n/a.
- **Edge cases / guards:** The composite PK makes linking idempotent.
- **Rebuild notes:** Recompute readiness on parent completion rather than polling every card.

### `hermes kanban comment`  `id: automation.kanban-comment`
- **Surface:** CLI
- **Where:** `hermes kanban comment <task_id> <text…> [--author AUTHOR] [--max-len MAX_LEN]`; help `Append a comment`.
- **What it does:** Appends a discussion post to a card; comments are part of the context a worker sees.
- **How it works:** Inserts into `task_comments(id, task_id, author, body, created_at)` (index `idx_comments_task(task_id, created_at)`) and appends a `commented` event.
- **Inputs / options:** positional `task_id`; positional variadic `text` "Comment body"; `-h, --help`; `--author AUTHOR` "Author name (default: $HERMES_PROFILE or 'user')"; `--max-len MAX_LEN` "Trim the stored comment body to this many characters".
- **Outputs / side effects:** Comment + event rows.
- **Config / env:** `HERMES_PROFILE`.
- **Edge cases / guards:** `--max-len` exists because worker-written comments can be arbitrarily long and are re-injected into every later worker's context.
- **Rebuild notes:** Bound anything that becomes prompt context.

### `hermes kanban attach` / `attachments` / `attach-rm`  `id: automation.kanban-attachments`
- **Surface:** CLI
- **Where:** `hermes kanban attach <task_id> <path> [--content-type CT] [--name NAME] [--author AUTHOR]`; `hermes kanban attachments <task_id> [--json]`; `hermes kanban attach-rm <attachment_id>`.
- **What it does:** Attaches local files (PDFs, images, source documents) to a card so the worker — which has full file-tool access — can read them by absolute path.
- **How it works:** Blob is copied to `attachments_root(board)/<task_id>/<stored_name>`; the `task_attachments` row (`id, task_id, filename, stored_path, content_type, size, uploaded_by, created_at`, index `idx_attachments_task`) carries the metadata plus the absolute `stored_path`. `build_worker_context` surfaces the absolute path to the worker. Events `attached` / `attachment_removed`.
- **Inputs / options:** `attach`: positional `task_id`, positional `path` "Path to the local file to attach", `--content-type CONTENT_TYPE` "MIME type (default: guessed from the file extension)", `--name NAME` "Stored filename (default: the source file's basename)", `--author AUTHOR` "uploaded_by label (default: $HERMES_PROFILE or 'user')". `attachments`: positional `task_id`, `--json`. `attach-rm`: positional `attachment_id`.
- **Outputs / side effects:** File on disk + DB row; removal deletes both.
- **Config / env:** `HERMES_KANBAN_ATTACHMENTS_ROOT`; size cap `KANBAN_ATTACHMENT_MAX_BYTES = 25 MiB` (`hermes_cli/kanban_db.py:162`).
- **Edge cases / guards:** Attachments are included in a board export unless `--no-attachments`.
- **Rebuild notes:** Store the blob on disk and the path in the row; putting 25 MB blobs in SQLite kills the board's read latency.

### Kanban review flow (`request-review`, `request-changes`, `reopen-review`)  `id: automation.kanban-review`
- **Surface:** CLI
- **Where:** `hermes kanban request-review <task_id> [--summary S] [--reviewer P] [--metadata JSON] [--force]`; `hermes kanban request-changes <task_id> <reason…>`; `hermes kanban reopen-review <task_ids…> [--reason REASON]`.
- **What it does:** Moves a card into a review stage after implementation, lets a reviewer send it back with concrete required changes, and lets anyone reopen a review.
- **How it works:** `request-review` sets `status='review'` — explicitly **not** a block — optionally reassigning to `--reviewer` before review dispatch, and records `review_requested` with the summary/metadata. `request-changes` is the reviewer's verdict: it returns the active review run to its implementer and records `changes_requested` with the reason. `reopen-review` sends review cards back for changes (`review → ready/todo`) with a `review_reopened` event.
- **Inputs / options:** `request-review`: positional `task_id`, `--summary SUMMARY` "What was implemented and how it was verified — shown to the reviewer.", `--reviewer REVIEWER` "Optional reviewer profile; reassigns the task before review dispatch.", `--metadata METADATA` "JSON object with structured reviewer handoff facts.", `--force` "Override the live-claim guard: move a running, claimed task to review even without owning its run (clears the worker's claim)." `request-changes`: positional `task_id`, positional variadic `reason` "Concrete changes required before re-review". `reopen-review`: positional `task_ids` (one or more), `--reason REASON` "Optional reason/note — recorded as a comment before reopening. Quote multi-word reasons."
- **Outputs / side effects:** Status changes plus the three events above; the reason is also recorded as a comment.
- **Config / env:** `kanban.review_dispatch` (default `true`) — whether the dispatcher spawns a reviewer worker for cards in `review`.
- **Edge cases / guards:** `request-review` refuses to move a running, claimed card unless `--force` (which clears the worker's claim) — the live-claim guard.
- **Rebuild notes:** Review is a status, not a block; treating it as a block breaks the ready-queue accounting.

### `hermes kanban dispatch`  `id: automation.kanban-dispatch`
- **Surface:** CLI
- **Where:** `hermes kanban dispatch [--dry-run] [--max MAX] [--failure-limit N] [--json]`; help `One dispatcher pass: reclaim stale, promote ready, spawn workers`.
- **What it does:** One scheduler pass over the board: reclaim stale claims, promote ready cards, and spawn worker processes for them.
- **How it works:** Three phases in order — (1) reclaim claims past their TTL + crash grace; (2) `recompute_ready` promotes `todo → ready` where all parents are done/archived; (3) spawn a worker subprocess per ready card, honouring per-card `assignee`, `skills`, `model_override`/`provider_override`, `reasoning_effort`, `max_runtime_seconds`, and `goal_mode`/`goal_max_turns`. Each spawn opens a `task_runs` row and appends a `spawned` event; failures record `spawn_failed`, `crashed` or `timed_out` and increment `consecutive_failures`; the circuit breaker trips at `max_retries` (per-card) else `kanban.failure_limit`, blocking the card (`spawn_auto_blocked`). Worker stdout/stderr go to `<kanban-root>/kanban/logs/<task>.log` with rotation.
- **Inputs / options:** `-h, --help`; `--dry-run` "Don't actually spawn processes; just print what would happen"; `--max MAX` "Cap number of spawns this pass"; `--failure-limit FAILURE_LIMIT` "Auto-block a task after this many consecutive non-success attempts (spawn_failed, timed_out, or crashed; default: 2)"; `--json`.
- **Outputs / side effects:** Spawned worker processes, run rows, events, log files.
- **Config / env:** `kanban.dispatch_in_gateway` (default `true`) / `HERMES_KANBAN_DISPATCH_IN_GATEWAY`; `kanban.dispatch_interval_seconds` (default 60); `kanban.failure_limit` (default 2); `kanban.max_in_progress` and `kanban.max_in_progress_per_profile` (both default null = unlimited); `kanban.dispatch_stale_timeout_seconds` (default 14400); `kanban.reconcile_orphans` (default `true`); `kanban.worker_log_rotate_bytes` (default 2097152) and `kanban.worker_log_backup_count` (default 1); `kanban.orchestrator_profile`; `kanban.review_dispatch`; `kanban.auto_decompose` (default `true`) and `kanban.auto_decompose_per_tick` (default 3); `kanban.done_sub_retention_days` (default 30).
- **Edge cases / guards:** `--max-runtime` exceeded ⇒ SIGTERM then SIGKILL, and the card is re-queued. `reconciled` events record orphan reconciliation when `kanban.reconcile_orphans` is on.
- **Rebuild notes:** Reclaim-then-promote-then-spawn in one transaction-per-phase avoids the classic race where a card is spawned twice because promotion and claiming were interleaved.

### `hermes kanban daemon` (deprecated)  `id: automation.kanban-daemon`
- **Surface:** CLI
- **Where:** `hermes kanban daemon [--interval INTERVAL] [--max MAX] [--failure-limit N] [--pidfile PIDFILE] [--verbose]`; help `DEPRECATED — dispatcher now runs in the gateway. Use \`hermes gateway start\`.`
- **What it does:** The old standalone dispatcher loop; still present for setups that do not run a gateway.
- **How it works:** Calls the same dispatch pass on a timer.
- **Inputs / options:** `-h, --help`; `--interval INTERVAL` "Seconds between dispatch ticks (default: 60)"; `--max MAX` "Cap number of spawns per tick"; `--failure-limit FAILURE_LIMIT`; `--pidfile PIDFILE` "Write the daemon's PID to this file on start"; `--verbose, -v` "Log each tick's outcome to stdout".
- **Outputs / side effects:** Long-running process; optional pidfile.
- **Config / env:** `kanban.dispatch_in_gateway` should be `false` when using this.
- **Edge cases / guards:** Running both the gateway dispatcher and this daemon on the same board double-dispatches; the claim CAS prevents double-execution but wastes spawns.
- **Rebuild notes:** Put the scheduler inside the long-lived process you already run.

### `hermes kanban swarm`  `id: automation.kanban-swarm`
- **Surface:** CLI
- **Where:** `hermes kanban swarm <goal> --worker PROFILE:TITLE[:SKILL,SKILL] --verifier V --synthesizer S [flags]`; help `Create a Kanban Swarm v1 graph (parallel workers → verifier → synthesizer)`.
- **What it does:** Writes a fan-out/fan-in task graph in one command: parallel specialist workers, then a verifier gated on all of them, then a synthesizer gated on the verifier.
- **How it works:** `hermes_cli/kanban_swarm.py`. `create_swarm()` (`:128`) writes the graph into the existing kernel — deliberately **no second scheduler**: a planning root that is completed immediately (`_activate_root_inline`, `:77`), N parallel worker cards in `ready`, a verifier in `todo` linked to every worker, and a synthesizer in `todo` linked to the verifier. The shared blackboard is structured JSON comments on the root card prefixed `[swarm:blackboard] ` (`BLACKBOARD_PREFIX`), written by `post_blackboard_update` (`:337`) and read by `latest_blackboard` (`:354`) — so all state stays in `task_comments`/`task_events` and the dashboard, notifier, slash command and dispatcher keep working unchanged. Each card's body gets a `## Swarm protocol` block (`_swarm_context`, `:66`) naming the root id as the shared blackboard.
- **Inputs / options:** positional `goal` "Swarm goal / final outcome"; `-h, --help`; `--worker PROFILE:TITLE[:SKILL,SKILL]` "Parallel worker card (repeatable)" (parsed by `parse_worker_arg`, `:381`, into `SwarmWorkerSpec(profile, title, body, skills, priority, max_runtime_seconds)`); `--verifier VERIFIER` (required) "Verifier profile"; `--synthesizer SYNTHESIZER` (required) "Synthesizer/writer profile"; `--tenant TENANT`; `--priority PRIORITY`; `--created-by CREATED_BY` "Creator/anchor profile"; `--idempotency-key IDEMPOTENCY_KEY` "Dedup key for the root card"; `--json`.
- **Outputs / side effects:** Returns `SwarmCreated{root_id, worker_ids[], verifier_id, synthesizer_id}` (`--json` prints it as a dict).
- **Config / env:** n/a beyond the normal board config.
- **Edge cases / guards:** `_require_text` rejects empty goal/profile/title with `<field> is required`.
- **Rebuild notes:** Express swarms as graph shapes over the existing task kernel; a bespoke swarm runtime duplicates claiming, retries and observability for no gain.

### `hermes kanban specify`  `id: automation.kanban-specify`
- **Surface:** CLI
- **Where:** `hermes kanban specify [task_id] [--all] [--tenant TENANT] [--author AUTHOR] [--json]`; help `Flesh out a triage-column task into a concrete spec (title + body) and promote it to todo. Uses the auxiliary LLM configured under auxiliary.triage_specifier.`
- **What it does:** Turns a one-line triage card into a concrete, actionable spec and promotes it out of triage.
- **How it works:** `hermes_cli/kanban_specify.py` (264 lines) calls the `auxiliary.triage_specifier` model, rewrites `title` + `body`, moves the card `triage → todo`, appends a `specified` event and an audit comment.
- **Inputs / options:** positional optional `task_id` "Task id to specify (required unless --all is given)"; `-h, --help`; `--all` "Specify every task currently in the triage column"; `--tenant TENANT` "When used with --all, restrict the sweep to this tenant"; `--author AUTHOR` "Author name recorded on the audit comment (default: $HERMES_PROFILE or 'specifier')"; `--json` "Emit one JSON object per task on stdout".
- **Outputs / side effects:** Card rewritten and promoted; `specified` event; audit comment.
- **Config / env:** `auxiliary.triage_specifier.*`.
- **Edge cases / guards:** `task_id` is required unless `--all`.
- **Rebuild notes:** A triage column plus an auxiliary specifier is a cheap way to accept messy input without polluting the ready queue.

### `hermes kanban decompose`  `id: automation.kanban-decompose`
- **Surface:** CLI
- **Where:** `hermes kanban decompose [task_id] [--all] [--tenant TENANT] [--author AUTHOR] [--json]`; help `Decompose a triage-column task into a graph of child tasks routed to specialist profiles by description. Falls back to specify-style single-task promotion when the task doesn't benefit from fan-out. Uses auxiliary.kanban_decomposer.`
- **What it does:** Splits a triage card into a dependency graph of child cards, each routed to the specialist profile whose description best fits.
- **How it works:** `hermes_cli/kanban_decompose.py` (468 lines) calls the `auxiliary.kanban_decomposer` model, creates child cards with `link`s, and records a `decomposed` event. When the model judges the task not worth fanning out it falls back to the specify path.
- **Inputs / options:** positional optional `task_id` "Task id to decompose (required unless --all is given)"; `-h, --help`; `--all` "Decompose every task currently in the triage column"; `--tenant TENANT`; `--author AUTHOR` (default `$HERMES_PROFILE` or `decomposer`); `--json`.
- **Outputs / side effects:** New child cards + links; `decomposed` event; audit comment.
- **Config / env:** `auxiliary.kanban_decomposer.*`; `kanban.auto_decompose` (default `true`) and `kanban.auto_decompose_per_tick` (default 3) make the dispatcher decompose triage cards automatically.
- **Edge cases / guards:** Routing is by *profile description*, so profiles need meaningful descriptions for this to work.
- **Rebuild notes:** Let the decomposer fall back to "don't fan out" — forced decomposition of a simple task produces make-work children.

### `hermes kanban context`  `id: automation.kanban-worker-context`
- **Surface:** CLI
- **Where:** `hermes kanban context <task_id>`; help `Print the full context a worker sees for a task (title + body + parent results + comments).`
- **What it does:** Reproduces exactly what a dispatched worker is handed, so the operator can debug a bad run without re-running it.
- **How it works:** `build_worker_context` assembles: the card title and body, every parent card's handoff `summary`/`result`, the card's comments, and the absolute paths of its attachments. The kanban lifecycle skill is injected automatically on top; `--skill` adds more.
- **Inputs / options:** positional `task_id`; `-h, --help`.
- **Outputs / side effects:** stdout only.
- **Config / env:** n/a.
- **Edge cases / guards:** Comments are the reason `--max-len` exists on `hermes kanban comment`.
- **Rebuild notes:** A "show me the prompt" command pays for itself the first time a worker misbehaves.

### `hermes kanban notify-subscribe` / `notify-list` / `notify-unsubscribe`  `id: automation.kanban-notify`
- **Surface:** CLI | Gateway/Telegram
- **Where:** `hermes kanban notify-subscribe <task_id> --platform P --chat-id C [flags]`; `hermes kanban notify-list [task_id] [--json]`; `hermes kanban notify-unsubscribe <task_id> --platform P --chat-id C [--thread-id T]`. Used by `/kanban subscribe` in the gateway adapter.
- **What it does:** Subscribes a chat (platform + chat + thread) to a card's terminal events so a human-in-the-loop workflow closes back into the conversation that asked for it.
- **How it works:** Rows in `kanban_notify_subs(task_id, platform, chat_id, thread_id, user_id, user_id_alt, chat_type, notifier_profile, delivery_mode, delivery_metadata, created_at, last_event_id)` with composite PK `(task_id, platform, chat_id, thread_id)` and index `idx_notify_task`. The gateway's kanban-notifier watcher tails `task_events` and pushes `completed` / `blocked` / `spawn_auto_blocked` events; `unseen_events_for_sub` (`hermes_cli/kanban_db.py:11728`) and `claim_unseen_events_for_sub` (`:11777`) advance `last_event_id` exactly once per subscription.
- **Inputs / options:** `notify-subscribe`: positional `task_id`; required `--platform PLATFORM`, required `--chat-id CHAT_ID`; `--thread-id THREAD_ID`; `--user-id USER_ID`; `--user-id-alt USER_ID_ALT`; `--chat-type {dm,group,channel,thread}` "Originating source chat_type, recorded so the active-wake delivery modes resolve the operator's real session. Omit to leave an existing sub unchanged (new subs default to 'dm')."; `--notifier-profile NOTIFIER_PROFILE` "Profile gateway that owns/delivers this subscription (default: active profile)"; `--delivery-mode {notify,notify+wake,wake}` "How the kanban-notifier reacts to terminal events for this subscription: 'notify' (passive message only; default), 'notify+wake' (message AND wake the destination gateway agent so it reads the full board context and replies in its own voice), or 'wake' (wake the agent only, no passive message). Omit to leave an existing subscription's mode unchanged (new subs default to 'notify')." `notify-list`: positional optional `task_id`, `--json`. `notify-unsubscribe`: positional `task_id`, required `--platform`, required `--chat-id`, optional `--thread-id`.
- **Outputs / side effects:** Messages or agent wakes delivered to the subscribed chat when the card reaches a terminal event.
- **Config / env:** `kanban.auto_subscribe_on_create` (default `true`) subscribes the creating chat automatically; `kanban.done_sub_retention_days` (default 30) prunes subscriptions of finished cards.
- **Edge cases / guards:** Omitting `--chat-type` or `--delivery-mode` on an existing subscription leaves that field unchanged (they are not reset to defaults).
- **Rebuild notes:** Store `last_event_id` per subscription and claim events transactionally, otherwise a restarted notifier re-notifies everything.

### `hermes kanban tail` / `watch` / `log` / `stats` / `assignees` / `diagnostics`  `id: automation.kanban-observability`
- **Surface:** CLI
- **Where:** `hermes kanban tail <task_id> [--interval INTERVAL]`; `hermes kanban watch [--assignee A] [--tenant T] [--kinds K] [--interval I]`; `hermes kanban log <task_id> [--tail TAIL]`; `hermes kanban stats [--json]`; `hermes kanban assignees [--json]`; `hermes kanban diagnostics|diag [--severity …] [--task TASK] [--json]`.
- **What it does:** The read-only observability surface: follow one card's events, live-stream all board events, read a worker's log, see per-status/per-assignee counts, list known profiles, and list active diagnostics.
- **How it works:** `tail` polls `task_events` for one task; `watch` polls the whole board (`Live-stream task_events to the terminal (Ctrl+C to exit)`); `log` reads `<kanban-root>/kanban/logs/<task>.log`; `stats` aggregates `Per-status + per-assignee counts + oldest-ready age`; `assignees` is the `union of ~/.hermes/profiles/ and current assignees on the board`; `diagnostics` comes from `hermes_cli/kanban_diagnostics.py` (1216 lines).
- **Inputs / options:** `tail`: positional `task_id`, `--interval INTERVAL`. `watch`: `--assignee ASSIGNEE` "Only show events for tasks assigned to this profile", `--tenant TENANT` "Only show events from tasks in this tenant", `--kinds KINDS` "Comma-separated event kinds to include (e.g. 'completed,blocked,gave_up,crashed,timed_out')", `--interval INTERVAL` "Poll interval in seconds (default: 0.5)". `log`: positional `task_id`, `--tail TAIL` "Only print the last N bytes". `stats`: `--json`. `assignees`: `--json`. `diagnostics`: `--severity {warning,error,critical}` "Only show diagnostics at or above this severity", `--task TASK` "Only show diagnostics for one task id", `--json` "Emit JSON (structured) instead of the default human table".
- **Outputs / side effects:** stdout only.
- **Config / env:** `kanban.worker_log_rotate_bytes` (2 MiB) and `kanban.worker_log_backup_count` (1) bound the log files `log` reads.
- **Edge cases / guards:** `watch`/`tail` are pollers (SQLite has no server-side push), so the interval is a real cost knob.
- **Rebuild notes:** Ship `stats` and `diagnostics` from day one — a board without them becomes unmaintainable at ~100 cards.

### `hermes kanban gc` / `repair` / `archive`  `id: automation.kanban-maintenance`
- **Surface:** CLI
- **Where:** `hermes kanban gc [--event-retention-days N] [--log-retention-days N]`; `hermes kanban repair [--json]`; `hermes kanban archive [task_ids…] [--rm PURGE_IDS…]`.
- **What it does:** Reclaims disk from finished work, verifies and narrowly auto-repairs the board DB, and retires or permanently deletes cards.
- **How it works:** `gc` (`Garbage-collect archived-task workspaces, old events, and old logs`) removes archived tasks' workspaces, `task_events` rows of terminal tasks older than N days (`gc_events`, `hermes_cli/kanban_db.py:11878`) and worker logs older than N days. `repair` runs `PRAGMA integrity_check`; when the failure consists **only** of index-scoped errors (`wrong # of entries in index <name>` / `row N missing from index <name>`) it quarantines the corrupt file to a `.corrupt.<hash>.bak` sibling and rebuilds the damaged indexes with `REINDEX` — the same narrow auto-repair the connect-time guard applies. `archive` sets `status='archived'` (event `archived`); `--rm` permanently deletes already-archived ids.
- **Inputs / options:** `gc`: `--event-retention-days EVENT_RETENTION_DAYS` "Delete task_events older than N days for terminal tasks (default: 30)", `--log-retention-days LOG_RETENTION_DAYS` "Delete worker log files older than N days (default: 30)". `repair`: `--json` "Emit the repair report as JSON". `archive`: positional variadic `task_ids` "Task ids to archive (default mode)", `--rm PURGE_IDS [PURGE_IDS …]` "Permanently delete already-archived task ids from the board".
- **Outputs / side effects:** Disk freed; DB possibly REINDEXed with a `.corrupt.<hash>.bak` sibling left behind.
- **Config / env:** n/a.
- **Edge cases / guards:** `repair` is **fail-closed**: any corruption class other than index-only is reported and left untouched. Exit code 0 when healthy or repaired, non-zero when still corrupt. `--rm` only accepts already-archived ids.
- **Rebuild notes:** Auto-repair exactly one, provably safe corruption class and refuse the rest; a broad auto-repair loses data.

### Kanban goal-mode cards (`--goal`)  `id: automation.kanban-goal-mode`
- **Surface:** CLI
- **Where:** `hermes kanban create --goal [--goal-max-turns N]`.
- **What it does:** Runs the card's worker in a Ralph-style goal loop inside that one card's session: a judge re-checks the worker's response against the card title/body after each turn and feeds a continuation prompt back until it agrees the work is done.
- **How it works:** `tasks.goal_mode` (INTEGER, default 0) and `tasks.goal_max_turns`; the dispatcher passes the flags through to the worker, which drives the same engine as `/goal` (`hermes_cli/goals.py`) — it borrows the engine, **not** the board. `HERMES_KANBAN_GOAL_MODE` carries the flag into the worker process.
- **Inputs / options:** `--goal` (boolean), `--goal-max-turns N` (default 20; ignored without `--goal`).
- **Outputs / side effects:** Exhausting the turn budget blocks the card for review rather than marking it done.
- **Config / env:** `goals.max_turns` supplies the engine default; `HERMES_KANBAN_GOAL_MODE`.
- **Edge cases / guards:** Documented boundary: `/goal` never creates a card, and a goal-mode card never fans out onto the board.
- **Rebuild notes:** Share the loop engine across surfaces but keep the ownership boundary explicit, or the two features start creating work for each other.

---

## 4. Projects and git worktrees

### `hermes project` (command group)  `id: automation.project-group`
- **Surface:** CLI
- **Where:** `hermes project {create,list,ls,show,add-folder,remove-folder,rename,set-primary,use,archive,restore,bind-board}`; group help verbatim: `Projects are human-named workspaces that can span multiple folders / repos. They anchor desktop session grouping and, when bound to a kanban board, give tasks a deterministic worktree + branch convention. State is per-profile.`
- **What it does:** Defines explicit, named, multi-folder workspaces that group desktop sessions and give kanban tasks a stable repo + branch convention.
- **How it works:** `hermes_cli/projects_cmd.py` (335 lines) over `hermes_cli/projects_db.py` (823 lines). Store is per-profile SQLite at `$HERMES_HOME/projects.db` (`projects_db_path()`, `:44`) — deliberately different from kanban, whose board DB is root-anchored and shared across profiles. A project may *bind* a board (`board_slug`) so the two systems agree on the convention without merging stores. Schema additions go through `_add_column_if_missing` so opening an old DB is always safe.
- **Inputs / options:** `-h, --help` plus the 11 sub-commands (aliases: `ls`→`list`).
- **Outputs / side effects:** Rows in `projects.db`.
- **Config / env:** `HERMES_HOME`; `HERMES_ENABLE_PROJECT_PLUGINS`.
- **Edge cases / guards:** A session belongs to a project when its `cwd` lives under one of the project's folders (**longest-prefix** match).
- **Rebuild notes:** Make the workspace an explicit named entity rather than inferring it from `cwd` + a git probe; inference is what makes session grouping unstable.

### Project store schema  `id: automation.project-schema`
- **Surface:** Core
- **Where:** `$HERMES_HOME/projects.db`.
- **What it does:** Persists projects, their folders, the active-project pointer, and cached repo discovery.
- **How it works:** `SCHEMA_SQL` at `hermes_cli/projects_db.py:57`. Tables: `projects(id TEXT PK, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description, icon, color, board_slug, primary_path, created_at INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0)`; `project_folders(project_id REFERENCES projects(id) ON DELETE CASCADE, path, label, is_primary INTEGER DEFAULT 0, added_at, PRIMARY KEY(project_id, path))` with index `idx_project_folders_path(path)`; `project_meta(key TEXT PK, value TEXT)` (holds the active project id and the discovery-policy key); `discovered_repos(root TEXT PK, label, last_seen INTEGER NOT NULL)` — git repos found by the desktop's "repo-first" filesystem scan, cached so the Projects view is instant after the first scan.
- **Inputs / options:** Slug grammar `_SLUG_RE = ^[a-z0-9][a-z0-9\-_]{0,63}$` — lowercase alphanumerics, hyphens and underscores, 1–64 chars, no leading separator; strict enough to stop traversal and path separators, loose enough for kebab-case. Display formatting (spaces, emoji, capitalisation) lives in `name`.
- **Outputs / side effects:** API surface: `create_project` (`:348`), `list_projects` (`:430`), `get_project` (`:441`), `update_project` (`:457`), `add_folder` (`:503`), `remove_folder` (`:549`), `set_primary` (`:598`), `archive_project` (`:611`), `restore_project` (`:619`), `delete_project` (`:627`), `set_active`/`get_active_id` (`:643`/`:656`), `find_by_primary_path` (`:327`), `record_discovered_repos` (`:715`), `list_discovered_repos` (`:758`), `clear_discovered_repos` (`:697`), `reconcile_discovered_repos_policy` (`:670`).
- **Config / env:** n/a.
- **Edge cases / guards:** `_unique_slug` (`:308`) auto-suffixes a colliding slug; the slug is immutable afterwards (only `name` can be renamed).
- **Rebuild notes:** Keep the slug as the stable handle and the name as the display string; renaming a slug breaks every stored reference.

### `hermes project create`  `id: automation.project-create`
- **Surface:** CLI
- **Where:** `hermes project create <name> [folders…] [flags]`; help `Create a new project`.
- **What it does:** Creates a named project spanning one or more folders, optionally binding a kanban board and making it active.
- **How it works:** `create_project()` slugifies the name (or uses `--slug`), inserts the project row, then one `project_folders` row per path with the first (or `--primary`) marked primary.
- **Inputs / options:** positional `name` "Human name, e.g. 'Hermes Agent'"; positional variadic `folders` "Folder paths to include (first = primary)"; `-h, --help`; `--slug SLUG` "Explicit slug override"; `--primary PATH` "Primary repo path"; `--description DESCRIPTION`; `--icon ICON`; `--color COLOR`; `--board SLUG` "Bind a kanban board"; `--use` "Set as the active project".
- **Outputs / side effects:** New rows; `--use` writes the active-project pointer in `project_meta`.
- **Config / env:** n/a.
- **Edge cases / guards:** Paths are normalized (`_normalize_path`, `:142`) before storage so the longest-prefix session match is stable.
- **Rebuild notes:** Allow multiple folders from the start — real projects span a repo plus docs plus infra.

### `hermes project list` / `show` / `use` / `rename` / `archive` / `restore`  `id: automation.project-lifecycle`
- **Surface:** CLI
- **Where:** `hermes project list [--all]`; `hermes project show <project>`; `hermes project use [project]`; `hermes project rename <project> <name>`; `hermes project archive <project>`; `hermes project restore <project>`.
- **What it does:** Lists projects, prints one project's details, sets/clears the active project, renames a project, and archives or restores one.
- **How it works:** Straight reads/writes over `projects.db`; the active project id lives in `project_meta`.
- **Inputs / options:** `list`: `--all` "Include archived projects". `show`: positional `project` "Project id or slug". `use`: positional optional `project` "Project id or slug (omit to clear)". `rename`: positional `project`, positional `name` "New name". `archive` / `restore`: positional `project`.
- **Outputs / side effects:** Row updates; the active pointer changes what desktop sessions group under.
- **Config / env:** n/a.
- **Edge cases / guards:** Archiving sets `archived=1` rather than deleting; `restore` clears it. Renaming changes only `name` — the slug is immutable.
- **Rebuild notes:** `use` with no argument clearing the pointer is the right ergonomics; a separate `unuse` is noise.

### `hermes project add-folder` / `remove-folder` / `set-primary`  `id: automation.project-folders`
- **Surface:** CLI
- **Where:** `hermes project add-folder <project> <path> [--label LABEL] [--primary]`; `hermes project remove-folder <project> <path>`; `hermes project set-primary <project> <path>`.
- **What it does:** Manages the folder set of a project and which folder is the primary repo.
- **How it works:** `add_folder` inserts a `project_folders` row (`--primary` also updates `projects.primary_path` via `_set_primary_locked`, `:579`); `remove_folder` deletes it; `set_primary` flips `is_primary` and `projects.primary_path`.
- **Inputs / options:** `add-folder`: positional `project`, positional `path` "Folder path", `--label LABEL`, `--primary` "Mark as primary repo". `remove-folder`: positional `project`, positional `path`. `set-primary`: positional `project`, positional `path` "Folder path (must already be in project)".
- **Outputs / side effects:** Row changes; the primary repo determines where kanban task worktrees are anchored.
- **Config / env:** n/a.
- **Edge cases / guards:** `set-primary` requires the path to already be a folder of the project.
- **Rebuild notes:** Exactly one primary per project keeps the worktree convention deterministic.

### `hermes project bind-board`  `id: automation.project-bind-board`
- **Surface:** CLI
- **Where:** `hermes project bind-board <project> [board]`; help `Bind a kanban board to a project`.
- **What it does:** Links a project to a kanban board so tasks on that board inherit the project's repo and branch convention. Omitting the board unbinds.
- **How it works:** Writes `projects.board_slug`. `hermes kanban create --project <id|slug>` then anchors the task's worktree under the project's primary repo with a deterministic branch name instead of the random `wt/<task-id>` fallback.
- **Inputs / options:** positional `project` "Project id or slug"; positional optional `board` "Board slug (omit to unbind)"; `-h, --help`.
- **Outputs / side effects:** One column update; changes where future task worktrees land.
- **Config / env:** n/a.
- **Edge cases / guards:** The two stores stay separate — binding is a pointer, not a merge; projects are per-profile while boards are root-anchored.
- **Rebuild notes:** A one-way pointer between two independently-scoped stores is the cheapest correct integration.

### `hermes -w` / `--worktree` — isolated worktree sessions  `id: automation.worktree-flag`
- **Surface:** CLI
- **Where:** Root parser `hermes [--worktree] …` and `hermes chat [--worktree] …`; help `--worktree, -w        Run in an isolated git worktree (for parallel agents)`; example line in `hermes --help`: `hermes -w                     Start in isolated git worktree`.
- **What it does:** Starts the session inside a fresh git worktree so several agents can work the same repository in parallel without clobbering each other.
- **How it works:** `hermes_cli/_parser.py:258` and `:501` define the flag; the session creates `.worktrees/<name>/` inside the repo on branch `hermes/<name>`, based on the freshly-fetched remote tip unless `worktree_sync: false` (`hermes_cli/cli_commands_mixin.py:1443`). Each worktree session gets its own working directory **and** its own Checkpoint Manager history for `/rollback`. `hermes_cli/main.py:3251` skips the normal cwd handling under `--worktree` because that path owns its own directory.
- **Inputs / options:** `-w`, `--worktree` (boolean).
- **Outputs / side effects:** A new `.worktrees/<name>/` directory and `hermes/<name>` branch; on exit the tree is kept only if it has unpushed commits.
- **Config / env:** `worktree_sync` (default `true`) — whether the new tree is based on the freshly-fetched remote tip.
- **Edge cases / guards:** Hermes treats the current working directory as the project root (CLI: where you run `hermes`; messaging gateways: `terminal.cwd` in `~/.hermes/config.yaml`), which is exactly why parallel agents in one checkout interfere.
- **Rebuild notes:** Per-session checkout + per-session checkpoint history is the pair that makes parallel agents safe; either alone is not enough.

### `/worktree` (in-session)  `id: automation.worktree-slash`
- **Surface:** CLI (interactive session)
- **Where:** `/worktree`, `/worktree new [name]`, `/worktree list` typed inside an interactive CLI session.
- **What it does:** Creates a worktree and retargets the running session's terminal and file tools into it, with no restart.
- **How it works:** `/worktree new my-experiment` creates `.worktrees/my-experiment/` inside the repo on branch `hermes/my-experiment`, based on the freshly-fetched remote tip unless `worktree_sync: false`, then repoints the session's tools. Omitting the name yields a random `hermes-<id>` tree. Inspired by Copilot CLI's `/worktree new`.
- **Inputs / options:** `/worktree` (show the active tree), `/worktree new [name]`, `/worktree list` (list all of them).
- **Outputs / side effects:** New directory + branch; the session's tools now operate inside it. On exit the tree is kept only if it has unpushed commits, exactly like `hermes -w`.
- **Config / env:** `worktree_sync`.
- **Edge cases / guards:** Retargeting is live — no restart, no lost session state.
- **Rebuild notes:** Retargeting the tool cwd mid-session (rather than requiring a relaunch) is the feature; make sure checkpoints follow.

### `hermes worktree` (command group)  `id: automation.worktree-group`
- **Surface:** CLI
- **Where:** `hermes worktree {list,ls,audit,prune}`; group help verbatim: `Attended reclaim for the .worktrees/ directory hermes -w sessions accumulate. Never deletes uncommitted tracked changes, unique unpushed commits, or in-use trees; untracked-only scratch is archived to ~/.hermes/archive/worktree-prune/ before removal. See: https://hermes-agent.nousresearch.com/docs/user-guide/cli#worktree-cleanup`
- **What it does:** Audits and reclaims the `.worktrees/` directory that parallel-agent sessions accumulate, plus merged local branches.
- **How it works:** `hermes_cli/worktree_cmd.py` (99 lines) over `hermes_cli/worktree_gc.py` (460 lines). `audit_worktrees(repo_root, with_sizes=True)` (`:170`) builds `TreeRecord`s (`:61`); `reclaim_worktrees` (`:266`) removes safe trees; `audit_branches` (`:332`) / `reclaim_branches` (`:415`) handle merged local branches; `worktrees_summary` (`:439`) gives the count + total size. Git is shelled through `_git(args, cwd, timeout=15)` (`:79`); dirty state is split by `_dirty_split` (`:116`); untracked-only scratch is archived by `_archive_untracked` (`:141`).
- **Inputs / options:** `-h, --help`; sub-commands `list` (aliases `ls`, `audit`) — "Classify every tree: age, size, verdict, reason (default action)" — and `prune` — "Remove safe trees and delete fully-merged local branches".
- **Outputs / side effects:** Prints a classification table; `prune` deletes trees/branches and writes archives.
- **Config / env:** n/a.
- **Edge cases / guards:** `_PROTECTED_BRANCHES = {"main","master","develop","dev","trunk"}` are never deleted. `_KANBAN_RE = ^t_[0-9a-f]+$` identifies kanban-owned trees. `_MAX_CHERRY_AHEAD = 50` bounds the unique-commit check. Uncommitted tracked changes, unique unpushed commits and in-use trees are never removed.
- **Rebuild notes:** Classify before you delete, and archive untracked scratch instead of dropping it — "attended reclaim" is the right posture for anything touching a developer's working tree.

### `hermes worktree list` (aliases `ls`, `audit`)  `id: automation.worktree-list`
- **Surface:** CLI
- **Where:** `hermes worktree list [--repo REPO]`.
- **What it does:** Classifies every worktree under the repo: age, size, verdict and the reason for that verdict.
- **How it works:** `audit_worktrees()` walks `git worktree list`, measures each tree (`_tree_size_mb`, `:101`), inspects dirtiness and unique commits, and assigns a verdict.
- **Inputs / options:** `-h, --help`; `--repo REPO` "Repo root (default: current repo)".
- **Outputs / side effects:** stdout table; read-only.
- **Config / env:** n/a.
- **Edge cases / guards:** Size measurement is best-effort and returns `None` on failure.
- **Rebuild notes:** Show the *reason* alongside the verdict; a bare "unsafe" is unactionable.

### `hermes worktree prune`  `id: automation.worktree-prune`
- **Surface:** CLI
- **Where:** `hermes worktree prune [--repo REPO] [--dry-run] [--trees-only] [--branches-only]`.
- **What it does:** Removes worktrees classified as safe and deletes fully-merged local branches.
- **How it works:** `reclaim_worktrees` then `reclaim_branches`; untracked-only scratch is tarred into `~/.hermes/archive/worktree-prune/` before removal.
- **Inputs / options:** `-h, --help`; `--repo REPO` "Repo root (default: current repo)"; `--dry-run` "Show the plan without changing anything"; `--trees-only` "Only remove worktrees; leave local branches alone"; `--branches-only` "Only delete merged local branches; leave worktrees alone".
- **Outputs / side effects:** Trees removed, branches deleted, archives written under `~/.hermes/archive/worktree-prune/`.
- **Config / env:** n/a.
- **Edge cases / guards:** Never deletes uncommitted tracked changes, unique unpushed commits, in-use trees, or a protected branch. `--trees-only` and `--branches-only` are mutually meaningful (passing both would leave nothing to do).
- **Rebuild notes:** Default to `--dry-run` in docs and make the archive step unconditional; the cost of a stale tarball is far below the cost of a lost experiment.

### Automatic worktree maintenance during cron ticks  `id: automation.worktree-cron-maintenance`
- **Surface:** Core
- **Where:** Invisible; runs opportunistically inside the cron scheduler's `tick()`.
- **What it does:** Keeps `.worktrees/` from growing without bound on machines that run many worktree sessions, without requiring the user to remember `hermes worktree prune`.
- **How it works:** `_worktree_maintenance_repos()` (`cron/scheduler.py:7743`) enumerates the repos to maintain and `_maybe_run_worktree_maintenance()` (`:7786`) runs the same safe reclaim as `hermes worktree prune` on a throttle during a tick.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Same as `prune`, including the pre-removal archive.
- **Config / env:** Governed by the cron ticker's schedule.
- **Edge cases / guards:** Uses the identical safety classification, so it can never delete unpushed work.
- **Rebuild notes:** Attach opportunistic housekeeping to an existing periodic loop rather than adding a second timer.

---

## 5. Hosted rooms (Bot Mode Group Chat)

### Hosted room — identity and event log  `id: automation.hosted-room-core`
- **Surface:** Core / Gateway
- **Where:** Gateway-hosted Bot Mode rooms; state lives in the gateway's root `state.db`. Surfaced through the Desktop's Group Chat, the `/v1/rooms/*` API-server routes, and the TUI gateway's room service.
- **What it does:** A *room* is a durable, named, multi-member conversation owned by one authority gateway, with an append-only ordered event log. Members can be local profiles or autonomous agents on other gateways.
- **How it works:** `gateway/hosted_rooms.py` owns identity + log only — it does not deliver events, lease relay work, or run turns; those belong to the relay and the driver. Schema (`_initialize_schema`, `:440`): `hosted_rooms(room_id PK, name, members_json, authority_gateway_id, authority_epoch INTEGER DEFAULT 1 CHECK ≥1, next_seq INTEGER DEFAULT 1 CHECK ≥1, event_bytes INTEGER DEFAULT 0 CHECK ≥0, revision INTEGER DEFAULT 1 CHECK ≥1, created_at, updated_at, disbanded_at)`; `hosted_room_events(room_id, seq CHECK ≥1, event_id, kind, actor_json, authority_epoch, payload_json, created_at, PRIMARY KEY(room_id,seq), UNIQUE(room_id,event_id), FK room_id)`; `hosted_room_retired_ids(room_id PK, retired_at)`; `hosted_room_links(room_id, member_id, target_url, target_profile, grant, catalog_json, cancellation_scope_id, trace_id, transport_security, status DEFAULT 'ready', updated_at, PK(room_id,member_id))`; `hosted_room_remote_runs(room_id, home_install_id, authority_gateway_id, authority_epoch, member_id, task_id, execution_generation, target_install_id, target_profile, run_id, session_id, created_at, updated_at, 9-column PK)`; `hosted_room_revoked_grants(scope_key PK, expires_at, revoked_before)`; `hosted_room_peer_reservations(room_id, member_id, target_profile, authority_gateway_id, authority_epoch, expires_at, revoked_at, created_at, updated_at, PK(room_id,member_id,target_profile))`.
- **Inputs / options:** Public API: `create_room` (`:1414`), `list_rooms` (`:1588`), `rename_room` (`:1621`), `append_event` (`:1713`), `probe_hosted_room` (`:1869`), `probe_peer_room_reservation` (`:1910`), `room_state` (`:1960`), `request_room_stop` (`:1999`), `claim_authority` (`:2027`), `disband_room` (`:2195`), `read_events` (`:2351`), `prune_disbanded_rooms` (`:1386`), `user_event_id` (`:316`), `local_authority_gateway_id` (`:278`), `default_db_path` (`:269`), plus the link/grant/reservation/receipt helpers (`list_room_link_records` `:656`, `upsert_room_link_record` `:669`, `update_room_link_status` `:719`, `delete_room_link_records` `:742`, `revoke_room_grant_scope` `:775`, `reserve_peer_room` `:821`, `peer_room_is_reserved` `:913`, `peer_room_grant_is_current` `:944`, `room_grant_is_revoked` `:991`, `upsert_remote_run_receipt` `:1014`, `list_remote_run_receipts` `:1065`, `remote_run_receipt` `:1094`).
- **Outputs / side effects:** Event kinds appended to the log, all of them: `room.created`, `room.renamed`, `room.members_changed`, `room.activity`, `room.stop_requested`, `room.disbanded`, `turn.started`, `turn.settled`, `turn.failed`, `turn.cancelled`, `turn.deferred`, `turn.reassigned`, `authority.claimed`, `authority.lost`, `member.unavailable`.
- **Config / env:** DB path is caller-supplied so tests and alternate gateway layouts can isolate state; production handlers use the gateway root `state.db`.
- **Edge cases / guards:** `PROTOCOL_VERSION = 2`. Hard limits: `MAX_ROOM_ID_CHARS = 128`, `MAX_EVENT_ID_CHARS = 128`, `MAX_ROOM_NAME_CHARS = 200`, `MAX_EVENT_KIND_CHARS = 64`, `MAX_ACTOR_ID_CHARS = 128`, `MAX_ACTOR_LABEL_CHARS = 200`, `MAX_MEMBERS = 128`, `MAX_MEMBERS_JSON_BYTES = 131072`, `MAX_EVENT_JSON_BYTES = 262144`, `MAX_LOG_LIMIT = 500`, `MAX_LOG_PAGE_BYTES = 2 MiB`, `MAX_ROOM_LIST_LIMIT = 500`, `MAX_ACTIVE_ROOMS = 256`, `MAX_DISBANDED_ROOM_TOMBSTONES = 512`, `DISBANDED_ROOM_RETENTION_SECONDS = 90 days`, `MAX_EVENTS_PER_ROOM = 50000`, `MAX_ROOM_EVENT_BYTES = 256 MiB` (deliberately well below the physical `state.db` snapshot ceiling because event accounting excludes indexes and repeated room ids). Error taxonomy: `HostedRoomError` (ValueError), `RoomNotFoundError`, `RoomHistoryExpiredError`, `RoomConflictError`, `RoomProbeUnavailableError`, `EventConflictError`, `AuthorityConflictError`, `AuthoritySupersededError`.
- **Rebuild notes:** One authority per room, a monotonically increasing `seq`, and a `UNIQUE(room_id, event_id)` idempotency key is the minimal correct core. Keep identity/log strictly separate from delivery and execution, or you end up with two transport queues.

### Room replicas and authority takeover  `id: automation.hosted-room-replicas`
- **Surface:** Core / Gateway
- **Where:** Every *non-authority* participant gateway keeps a local replica; takeover is an explicit user action today.
- **What it does:** Gives every other participant gateway a durable local copy of the room's ordered log, plus fenced primitives to continue the room when the authority host dies.
- **How it works:** `gateway/hosted_room_replicas.py`. `ingest_page()` persists replay pages (the output of `groups.log`, which carries the room's authority stamp) idempotently, **refusing sequence gaps and authority-epoch regressions**. `promote_replica()` instantiates the replicated log as a locally-owned hosted room at `epoch + 1` with a lineage-proving `authority.claimed` event, so a surviving participant can resume the room. `demote_room()` fences a returning stale authority: presented with proof of a newer epoch, the local room records `authority.lost` and stops being authoritative.
- **Inputs / options:** `ingest_page(...)`, `promote_replica(...)`, `demote_room(...)` — storage primitives only.
- **Outputs / side effects:** Local replica rows; on promotion, a real hosted room at the next epoch.
- **Config / env:** n/a.
- **Edge cases / guards:** None of these decide *when* takeover is safe — the caller (an explicit user action today; a lease/quorum driver later) must establish that the previous owner can no longer commit before promoting. Authority-epoch monotonicity is the fence that makes a split brain detectable.
- **Rebuild notes:** Model authority as a monotonically increasing epoch stamped on every event; a boolean "is owner" flag cannot fence a returning stale host.

### Room links (cross-gateway member routes)  `id: automation.hosted-room-links`
- **Surface:** Core / Gateway
- **Where:** Negotiated when a room admits a member that lives on another gateway.
- **What it does:** Stores the route and scoped grant needed to reach a remote member's gateway, with a status so the UI can show when re-authorization is needed.
- **How it works:** `gateway/hosted_room_links.py` writes `StoredRoomLink(room_id, member_id, target_url, target_profile, grant, catalog, cancellation_scope_id, trace_id, transport_security, status, updated_at)` into the gateway's private root `state.db`. Concurrency is SQLite WAL plus `BEGIN IMMEDIATE`.
- **Inputs / options:** Statuses `_STATUSES = {"ready", "unavailable", "needs_reauthorization"}`. Limits `MAX_LINKS = 512`, `MAX_GRANT_CHARS = 16384`. URL validation via `validate_room_link_url`; transport classification via `TransportSecurity`; the remote gateway's advertised capabilities via `GatewayRoomCatalog`.
- **Outputs / side effects:** Link rows; `HERMES_ROOM_LINK_URL` carries a link URL into the process that consumes it.
- **Config / env:** `HERMES_ROOM_LINK_URL`.
- **Edge cases / guards:** **Grants are never included in reprs, status payloads, or exception messages** — an explicit anti-leak rule.
- **Rebuild notes:** Keep the secret out of every rendering path by construction (separate field, excluded from `__repr__` and serializers), not by remembering to redact.

### Room peer grants and admission  `id: automation.hosted-room-peer`
- **Surface:** Core / Gateway (security)
- **Where:** The boundary where a target gateway decides whether to run model or tool work for a remote room member.
- **What it does:** Defines the typed contracts for autonomous cross-gateway hosted-room members: scoped grants, task coordinates, and the verification the target performs before admitting any work.
- **How it works:** `gateway/hosted_room_peer.py`. `PROTOCOL_VERSION = 2` adds authority/member lineage to scoped grants and is intentionally **not** wire-compatible with the unpublished v1 draft — mixed gateways must fall back to Desktop-driven rooms rather than accept a weaker token shape. Tokens are HMAC-signed (`hmac`, `hashlib`), size-capped at `MAX_TOKEN_BYTES = 16384` with `MAX_PROMPT_BYTES = 262144`. Identifiers must match `^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$`; digests must match `^[0-9a-f]{64}$`. Link kinds are ranked by `_LINK_PRIORITY = {direct: 0, overlay: 1, relay: 2, pull: 3, desktop: 4}`. Types include `HostedMemberDispatch`, `GatewayRoomCatalog`, `TransportSecurity`, `HostedRoomPeerError`.
- **Inputs / options:** n/a (protocol types).
- **Outputs / side effects:** An admitted dispatch produces a remote run whose receipt is recorded in `hosted_room_remote_runs`.
- **Config / env:** Reservation TTLs come from `hosted_room_peer_reservations.expires_at`; revocations from `hosted_room_revoked_grants`.
- **Edge cases / guards:** **The Desktop may bootstrap an invitation, but it is never the issuer or the runtime courier** — the target gateway verifies a scoped grant *and* the full task coordinates before admitting work. IP/URL validation guards against SSRF (`ipaddress`, `urllib.parse`); file permissions are checked with `stat`.
- **Rebuild notes:** Bind the grant to the room, authority epoch, member and task coordinates. A bearer token scoped only to "this room" lets any member replay another member's work.

### Room execution policy  `id: automation.hosted-room-execution-policy`
- **Surface:** Core / Gateway (security)
- **Where:** Applied at the agent and approval boundaries when a target gateway runs a RoomLink member turn.
- **What it does:** The *target* gateway — not the caller — decides what a remote member's turn may do: which toolsets are available and how many iterations it may run.
- **How it works:** `gateway/hosted_room_execution_policy.py`. `RoomExecutionPolicy` is an immutable frozen dataclass installed via a `ContextVar` for the duration of the turn. `POLICY_VERSION = 1`. Policies are canonicalised with `_canonical_json` (ASCII, sorted keys, compact separators) so they hash stably.
- **Inputs / options:** Limits `MAX_POLICY_TOOLSETS = 128`, `MAX_POLICY_ITERATIONS = (1<<53)-1`; identifiers must match `^[A-Za-z0-9][A-Za-z0-9._:-]*$` and be ≤128 chars.
- **Outputs / side effects:** Enforced at the agent boundary and at the approval boundary.
- **Config / env:** n/a.
- **Edge cases / guards:** `RoomExecutionPolicyError` is raised when a policy is malformed **or no longer current** — a stale policy cannot authorise a turn. `execution_policy_mapping()` renders it for transport.
- **Rebuild notes:** Target-issued policy is the correct direction; a caller-declared capability list is a request, not an authorisation.

### Room policy checkpoint  `id: automation.hosted-room-policy-checkpoint`
- **Surface:** Core / Gateway
- **Where:** Between the room's append-only log and the discussion planner.
- **What it does:** Materialises just enough state to choose and reconstruct the next active discussion, so a busy room does not replay its complete history on every poll.
- **How it works:** `gateway/hosted_room_policy_checkpoint.py`. `HostedRoomPolicyCheckpoint(db_path)` incrementally indexes room policy **without compacting visible history** — the log stays the user-visible source of truth. `PolicySnapshot` is a frozen dataclass `(through_seq, stopped_through_seq, events, watermarks)` where `watermarks` maps `(str, str) → int`.
- **Inputs / options:** Bounds `MAX_ACTIVE_POLICY_EVENTS = 64`, `MAX_THREAD_TRANSCRIPT_EVENTS = 24`, `_TRANSCRIPT_SCHEMA_VERSION = 1`. Terminal kinds `_TERMINAL_KINDS = {"turn.settled", "turn.failed", "turn.cancelled", "turn.deferred"}`.
- **Outputs / side effects:** A bounded snapshot consumed by the discussion planner.
- **Config / env:** n/a.
- **Edge cases / guards:** Projection is derived, never authoritative — it can always be rebuilt from the log.
- **Rebuild notes:** Build a bounded projection rather than compacting the log; compaction destroys the audit trail the room's users can see.

### Room discussions (deterministic turn planner)  `id: automation.hosted-room-discussion`
- **Surface:** Core / Gateway
- **Where:** Same-gateway hosted rooms with multiple local members.
- **What it does:** Translates a frozen local member roster plus the complete typed room log into exactly one next driver task — deciding who speaks next, and when the discussion is finished.
- **How it works:** `gateway/hosted_room_discussion.py`. Pure policy: **no I/O, no workers, no knowledge of transports or model runtimes**. Callers persist the returned task with `gateway/hosted_room_driver.py` and append publication plans with `gateway/hosted_rooms.py`. Discussion coordinates live in deterministic `TaskIdentity` values and typed terminal events, so a restart can reconstruct a task without widening the driver schema. Mentions are parsed with `_MENTION_RE = @([A-Za-z0-9][A-Za-z0-9._:-]*)` (case-insensitive).
- **Inputs / options:** Bounds `MIN_DISCUSSION_MEMBERS = 2`, `MAX_DISCUSSION_MEMBERS = 6`, `MAX_DISCUSSION_ROUNDS = 3`, `MAX_DISCUSSION_MESSAGES = 10`, `MAX_DISCUSSION_DELTA_LINES = 24`, `MAX_USER_TEXT_BYTES = 65536`, `MAX_MEMBER_TEXT_BYTES = 65536`. `DecisionStatus` ∈ `{idle, task, settled, bounded}`; `TerminalKind` ∈ `{settled, failed, cancelled, deferred}`.
- **Outputs / side effects:** One next driver task, or a terminal decision. A member reply that exceeds the byte budget is truncated with the verbatim notice `\n\n[Reply truncated. Ask the Bot to share the full result as a file.]`.
- **Config / env:** n/a.
- **Edge cases / guards:** Callers must reconcile terminal driver rows into publication plans before asking for the next task. Determinism is the contract — the same log and roster always yield the same next task.
- **Rebuild notes:** Keep the "who speaks next" policy pure and total; every non-determinism here becomes an unreproducible multi-agent bug.

### Room driver (lease + task state machine)  `id: automation.hosted-room-driver`
- **Surface:** Core / Gateway
- **Where:** The durable execution state behind every hosted-room turn.
- **What it does:** Owns the driver lease (only one process drives a room at a time) and the task state machine that survives crashes and fences stale drivers.
- **How it works:** `gateway/hosted_room_driver.py`. Both the database path *and* the clock are caller-supplied so recovery and fencing behaviour can be tested without process-global state. It deliberately does **not** invoke models, touch sessions, or depend on the hosted-room event log.
- **Inputs / options:** `TaskStatus` ∈ `{queued, running, settled, failed, cancelled, indeterminate, deferred, stopping}`; `TerminalStatus` ∈ `{settled, failed}`. Operations, all of them: `acquire_lease` (`:638`), `renew_lease` (`:757`), `release_lease` (`:798`), `admit_task` (`:851`), `start_task` (`:911`), `settle_task` (`:987`), `settle_stopping_task` (`:1055`), `resolve_indeterminate_task` (`:1110`), `resolve_indeterminate_cancellation` (`:1184`), `requeue_indeterminate_task` (`:1244`), `defer_indeterminate_task` (`:1298`), `requeue_deferred_task` (`:1363`), `requeue_not_admitted_task` (`:1419`), `cancel_task` (`:1477`), `begin_task_cancel` (`:1531`), `complete_task_cancel` (`:1578`), `recover_room` (`:1618`).
- **Outputs / side effects:** Durable task rows; leases with TTL/expiry (`_ttl`, `_expiry`).
- **Config / env:** `TERMINAL_TASK_RETENTION_SECONDS = 30 days`, `MAX_RETAINED_TERMINAL_TASKS = 2048`, `MAX_TASK_PRUNE_BATCH = 1000`, `MAX_IDENTIFIER_CHARS = 128`, `MAX_PROMPT_BYTES = 131072`, `MAX_RESULT_JSON_BYTES = 262144`.
- **Edge cases / guards:** The `indeterminate` status exists specifically for a task whose outcome is unknown after a crash: it must be explicitly resolved, requeued, deferred, or cancelled — never silently assumed failed. `_require_room_authority` and `_require_active_lease` fence every mutation.
- **Rebuild notes:** An explicit `indeterminate` state plus lease fencing is what makes crash recovery safe; a two-state (running/done) machine either double-runs work or drops it.

### Hosted-room service and peer transports (TUI gateway)  `id: automation.hosted-room-service`
- **Surface:** Core / Gateway / TUI
- **Where:** The production coordinator that actually runs same-gateway Discussion rooms.
- **What it does:** Wires the pure discussion policy, the durable driver, the room log, the policy checkpoint, and the peer transports into one running loop.
- **How it works:** `tui_gateway/hosted_room_service.py` (1013 lines) — "Production coordinator for same-gateway hosted Discussion rooms" — imports `hosted_room_discussion`, `hosted_room_driver`, `hosted_room_links`, `hosted_rooms`, `HostedRoomPolicyCheckpoint`, and the peer types, then binds them to `tui_gateway/hosted_room_driver.py`'s `HostedRoomBinding` / `HostedRoomRuntime` (1599 lines), `tui_gateway/hosted_room_server_rpc.py`'s `HostedRoomServerRPC` (213 lines), `tui_gateway/hosted_room_peer_http.py`'s `PeerRunsHTTPClient` / `PeerRunsHTTPError` (1037 lines), and `tui_gateway/hosted_room_peer_transport.py`'s `HostedRoomPeerClient` / `PeerHostedRoomTransport` / `PeerMemberRoute` (368 lines).
- **Inputs / options:** n/a (internal coordinator).
- **Outputs / side effects:** Runs member turns, publishes results back into the room log, and drives remote members over the peer HTTP transport.
- **Config / env:** `_HOSTED_ROOM_IDLE_FALLBACK_SECONDS = 5.0` is the idle poll fallback.
- **Edge cases / guards:** Remote member work goes through `PeerRunsHTTPClient` against the target gateway's `/v1/runs` surface, so a remote turn is an ordinary run on that gateway subject to its own execution policy.
- **Rebuild notes:** Keep the coordinator thin: it should only sequence pure-policy decisions and durable-state transitions, so every hard part stays unit-testable without a network.

---

## 6. The API-server platform (`/v1/runs`, OpenAI compat, sessions, jobs, artifacts, room members)

### API server platform (aiohttp listener)  `id: automation.api-server`
- **Surface:** Platform:api_server | API
- **Where:** `http://<API_SERVER_HOST>:<API_SERVER_PORT>` (default `http://127.0.0.1:8642`); startup log line `[API Server] API server listening on http://127.0.0.1:8642`.
- **What it does:** Exposes the whole agent as an authenticated HTTP surface: an OpenAI-compatible endpoint any frontend can point at, plus Hermes-native runs, sessions, jobs, artifacts, browser control and room-member endpoints.
- **How it works:** `gateway/platforms/api_server.py` (7937 lines) builds an `aiohttp` `web.Application` with middlewares `_make_profile_prefix_middleware()`, `cors_middleware`, `body_limit_middleware`, `security_headers_middleware` and `client_max_size = MAX_REQUEST_BYTES`. `_http_route_table()` (`:2210`) returns `(method, path, handler)` rows; `connect()` (`gateway/platforms/api_server.py:7722`) registers each **twice** — natively and mirrored under `/p/{profile}<path>` for multi-profile multiplexing. A background `_sweep_orphaned_runs()` task cleans up unconsumed run streams. Run routes come from `gateway/platforms/api_server_runs.py`, room-member routes from `gateway/platforms/api_server_room_grants.py`, idempotency from `gateway/platforms/api_server_run_idempotency.py`, room dispatch from `gateway/platforms/api_server_room_dispatch.py`.
- **Inputs / options:** Full route table, all 41 rows: `GET /health`, `GET /health/detailed`, `GET /v1/health`, `GET /v1/models`, `GET /api/model/options`, `GET /v1/capabilities`, `POST /v1/browser-control/register`, `GET /v1/browser-control/ws`, `POST /v1/artifacts/upload`, `GET /v1/artifacts/download/{artifact_id}`, `GET /v1/skills`, `GET /v1/toolsets`, `GET /api/sessions`, `POST /api/sessions`, `GET /api/sessions/{session_id}`, `PATCH /api/sessions/{session_id}`, `DELETE /api/sessions/{session_id}`, `GET /api/sessions/{session_id}/messages`, `POST /api/sessions/{session_id}/fork`, `POST /api/sessions/{session_id}/chat`, `POST /api/sessions/{session_id}/chat/stream`, `POST /api/sessions/{session_id}/model`, `POST /v1/chat/completions`, `POST /v1/responses`, `GET /v1/responses/{response_id}`, `DELETE /v1/responses/{response_id}`, `POST /api/platforms/{platform}/events`, `GET /api/jobs`, `POST /api/jobs`, `GET /api/jobs/{job_id}`, `PATCH /api/jobs/{job_id}`, `DELETE /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/pause`, `POST /api/jobs/{job_id}/resume`, `POST /api/jobs/{job_id}/run`, `POST /v1/room-members/invitations`, `GET /v1/room-members/capabilities`, `POST /v1/room-members/grants/refresh`, `POST /v1/room-members/grants/revoke`, `POST /v1/runs` + the five run sub-routes, and `POST /api/cron/fire` (only when cron is available).
- **Outputs / side effects:** Every response carries `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **Config / env:** `API_SERVER_ENABLED` (default `false`), `API_SERVER_PORT` (8642), `API_SERVER_HOST` (127.0.0.1), `API_SERVER_KEY` (required), `API_SERVER_CORS_ORIGINS` (none), `API_SERVER_MODEL_NAME` (defaults to the profile name, or `hermes-agent` for the default profile). The same settings are accepted under `gateway.api_server:` (`enabled`, `port`, `host`, `key`, `cors_origins`, `model_name`, `max_concurrent_runs`), `gateway.platforms.api_server:` or a top-level `platforms.api_server:`; env wins over config.yaml.
- **Edge cases / guards:** `_api_key_passes_startup_guard()` **fails closed**: the server refuses to start when `API_SERVER_KEY` is missing, a placeholder, or shorter than 16 chars, and also when its strength "could not be verified" — logging that this endpoint dispatches terminal-capable agent work and that a guessable key is remote code execution, with the fix `openssl rand -hex 32`. A rejected key is marked **non-retryable** (`_set_fatal_error("api_server_key_invalid", …, retryable=False)`) because the reconnect watcher otherwise loops forever and leaks a SQLite connection + fds per retry until EMFILE takes down the gateway; recovery is `/platform resume api_server`. Under `gateway.multiplex_profiles`, auth is bound to the routed profile: `/p/<profile>/…` requires that profile's own `API_SERVER_KEY` from `~/.hermes/profiles/<profile>/.env`; the default key is rejected on named prefixes (breaking change, July 2026 — reused default keys now return `401`), and a named profile with no key of its own fails closed. Concurrent-run cap `gateway.api_server.max_concurrent_runs` (default 10, `0` disables, negatives clamp to 0) rejects excess run-starting requests with **HTTP 429** `Too many concurrent runs (max N)`.
- **Rebuild notes:** Gate startup on key strength and make that failure non-retryable; a terminal-capable HTTP endpoint behind a weak key is RCE. Register the profile-prefixed mirror from the same table so native and multiplexed routes can never drift.

### `POST /v1/runs`  `id: automation.api-runs-create`
- **Surface:** API
- **Where:** `POST /v1/runs` (and `/p/<profile>/v1/runs`).
- **What it does:** Creates a long-form agent run and returns a `run_id` the client can poll or subscribe to, instead of holding a streaming HTTP connection.
- **How it works:** `gateway/platforms/api_server_runs.py::_handle_runs`. `_initialize_run_state()` (`:51`) sets up the adapter-owned state: `_run_idempotency_store`, `_run_idempotency_ids`, `_run_owners` (+ `_run_owner_pid` / `_run_owner_started` from `gateway.status.get_process_start_time`), `_run_streams` (run_id → `asyncio.Queue` of SSE dicts), `_run_streams_created` (TTL sweep), `_run_stream_subscribers`, `_active_run_agents`, `_active_run_tasks`, `_stopping_run_ids`, `_run_statuses`, `_run_approval_sessions`.
- **Inputs / options:** Body accepts `input` (string), `session_id`, `instructions`, `conversation_history`, `previous_response_id`, plus the per-request model controls `model`, `provider`, `model_options`. Headers: `Authorization: Bearer <API_SERVER_KEY>`, `Idempotency-Key` (1–255 visible ASCII chars), `X-Hermes-Session-Id`, `X-Hermes-Session-Key`.
- **Outputs / side effects:** `{"run_id": "run_abc123", "status": "started"}`.
- **Config / env:** `gateway.api_server.max_concurrent_runs`.
- **Edge cases / guards:** When `session_id` names an existing Hermes session and no explicit `conversation_history`/`previous_response_id` is given, the run loads that session's active transcript; session turn leases serialize concurrent writers and refresh the transcript after a contended wait. Runs may also be authorised by a room grant instead of the API key (`_uses_room_run_auth`, `:44`), in which case `_remember_room_retention` (`:29`) stamps the grant's `status_expires_at`/`expires_at` as the run's status retention deadline.
- **Rebuild notes:** Separate "create a run" from "watch a run" so a client can reconnect after navigation without losing the work.

### `Idempotency-Key` on `POST /v1/runs`  `id: automation.api-runs-idempotency`
- **Surface:** API
- **Where:** The `Idempotency-Key` request header on `POST /v1/runs`.
- **What it does:** Makes run creation safely retryable: an identical retry returns the original run instead of starting a second one.
- **How it works:** `gateway/platforms/api_server_run_idempotency.py::RunIdempotencyStore`. A unique `(scope, key)` row is inserted inside `BEGIN IMMEDIATE` so separate gateway workers/processes cannot both admit the same request. Storage is `<HERMES_HOME>/runs_idempotency.db`; when SQLite is unavailable it degrades to process memory with the warning `Run idempotency storage is unavailable; falling back to process memory, so replay will not survive a restart: <exc>`. Fingerprints are compared with `hmac.compare_digest`.
- **Inputs / options:** Header value: 1–255 visible ASCII characters.
- **Outputs / side effects:** An identical retry returns the original `run_id` with **HTTP 202** and `Idempotency-Replayed: true`, including after a gateway restart and after the run has completed, failed or been cancelled. Reusing the key with a **different** JSON payload returns **HTTP 409** with code `idempotency_key_conflict`. `/v1/capabilities` reports `{"supported": true, "durable": <bool>, "retention_seconds": 86400}` via `_idempotency_capabilities`.
- **Config / env:** `RETENTION_SECONDS = 86400` (24 h after last status update); `ACKNOWLEDGED_RETENTION_SECONDS = 86400`.
- **Edge cases / guards:** Keys are isolated by authenticated API profile/credential. **Only request fingerprints and public run status are stored — request bodies and credentials are deliberately excluded.** Requests without the header keep the legacy behaviour and always create a new run. Clients should use unique, unguessable keys and must not reuse them for unrelated operations.
- **Rebuild notes:** Reserve the key *before* starting work, inside an immediate transaction, and store a fingerprint rather than the body — that is what makes replay both correct and safe.

### `GET /v1/runs/{run_id}`  `id: automation.api-runs-status`
- **Surface:** API
- **Where:** `GET /v1/runs/{run_id}`.
- **What it does:** Polls a run's current state — for dashboards that need status without holding an SSE connection open, or UIs reconnecting after navigation.
- **How it works:** Reads `self._run_statuses[run_id]`.
- **Inputs / options:** Path parameter `run_id`; bearer auth.
- **Outputs / side effects:** `{"object": "hermes.run", "run_id": …, "status": …, "session_id": …, "model": …, "output": …, "usage": {"input_tokens": …, "output_tokens": …, "total_tokens": …}}`.
- **Config / env:** n/a.
- **Edge cases / guards:** Statuses are retained briefly after the terminal states `completed`, `failed` and `cancelled` for polling and UI reconciliation; room-grant runs use the grant's retention deadline instead.
- **Rebuild notes:** Keep terminal statuses readable for a grace window — a client that reconnects one second after completion must still learn the outcome.

### `GET /v1/runs/{run_id}/events` (SSE)  `id: automation.api-runs-events`
- **Surface:** API
- **Where:** `GET /v1/runs/{run_id}/events`.
- **What it does:** Server-Sent Events stream of the run's tool-call progress, token deltas and lifecycle events; clients can attach and detach without losing state.
- **How it works:** Drains the run's `asyncio.Queue` from `_run_streams`; `_run_stream_subscribers` tracks whether a consumer is attached.
- **Inputs / options:** Path parameter `run_id`; bearer auth.
- **Outputs / side effects:** Lifecycle and progress events, plus `subagent.start` and `subagent.complete` when the agent delegates to background subagents. The `subagent.complete` payload carries the child's status, summary, duration, token/cost figures and a `child_session_id` for correlation; free-text fields pass forced secret redaction before leaving the process.
- **Config / env:** Unconsumed buffers expire after **five minutes**.
- **Edge cases / guards:** Buffer expiry is transport state only — a still-executing run remains visible to status polling, approval, stop control and concurrency accounting until its executor work actually exits; a connected subscriber continues draining normally. Per-tool child events (`subagent.tool`, progress ticks) are **deliberately not forwarded** (high-volume UI noise); use the per-child live transcript files for play-by-play.
- **Rebuild notes:** Expire the *buffer*, not the run. Conflating the two is how a detached client silently kills work.

### `POST /v1/runs/{run_id}/stop`  `id: automation.api-runs-stop`
- **Surface:** API
- **Where:** `POST /v1/runs/{run_id}/stop`.
- **What it does:** Interrupts a running agent turn at the next safe interruption point.
- **How it works:** Adds the id to `_stopping_run_ids` and asks the active agent (`_active_run_agents`) / task (`_active_run_tasks`) to stop; the HTTP request returns immediately.
- **Inputs / options:** Path parameter `run_id`; bearer auth.
- **Outputs / side effects:** Returns `{"status": "stopping"}`; the run stays tracked as `stopping` until the executor-backed work exits, then settles as `cancelled`.
- **Config / env:** n/a.
- **Edge cases / guards:** Stop is **cooperative** — the executor thread may outlive the HTTP request, and requesting stop never hides a worker that is still running.
- **Rebuild notes:** Report `stopping` as a real state; collapsing it into `cancelled` immediately lies to the operator about a worker that is still burning CPU.

### `POST /v1/runs/{run_id}/steer`  `id: automation.api-runs-steer`
- **Surface:** API
- **Where:** `POST /v1/runs/{run_id}/steer`.
- **What it does:** Injects additional guidance into an in-flight run without cancelling it.
- **How it works:** `_handle_steer_run` in `gateway/platforms/api_server_runs.py` routes the steering text to the live agent registered in `_active_run_agents`.
- **Inputs / options:** Path parameter `run_id`; JSON body carrying the steering text; bearer auth.
- **Outputs / side effects:** The running turn receives the new instruction; the SSE stream reflects it.
- **Config / env:** n/a.
- **Edge cases / guards:** Only meaningful while the run is live; a settled run cannot be steered.
- **Rebuild notes:** Steering needs a live handle to the agent, which is why `_active_run_agents` is kept alongside the task handle.

### `POST /v1/runs/{run_id}/approval`  `id: automation.api-runs-approval`
- **Surface:** API
- **Where:** `POST /v1/runs/{run_id}/approval`.
- **What it does:** Resolves a pending approval for a run waiting on a human decision (for example a tool call gated behind an approval policy); the run resumes once the decision is recorded.
- **How it works:** `_run_approval_sessions` maps `run_id → approval session key`, because the approval core resolves requests by session key while API clients address them by run id.
- **Inputs / options:** Path parameter `run_id`; JSON body carrying the approval decision; bearer auth.
- **Outputs / side effects:** The run continues or the gated tool call is denied.
- **Config / env:** Advertised in `/v1/capabilities` as the `run_approval` feature so external UIs can detect support before surfacing an approval prompt.
- **Edge cases / guards:** Approval is addressed by run id externally and by session key internally — the mapping must survive a reconnect.
- **Rebuild notes:** Advertise approval support in a capabilities document; a UI that guesses will show a prompt nobody can answer.

### `POST /v1/chat/completions` (OpenAI compat)  `id: automation.api-chat-completions`
- **Surface:** API
- **Where:** `POST /v1/chat/completions`.
- **What it does:** Standard OpenAI Chat Completions. Stateless — the full conversation is sent in each request via `messages`. The agent answers with its full toolset (terminal, files, web search, memory, skills).
- **How it works:** `_handle_chat_completions`. A `system` message is **layered on top** of Hermes' core system prompt rather than replacing it, so the agent keeps all tools, memory and skills.
- **Inputs / options:** Body: `model`, `messages[]` (`role` + `content`), `stream` (bool), plus Hermes extensions `provider` and `model_options` (`reasoning_effort`, `service_tier`). Multimodal: user `content` may be an array of `text` and `image_url` parts; both remote `http(s)` and `data:image/...` URLs work, and `image_url` accepts `detail`. Headers: `Authorization`, `X-Hermes-Session-Id`, `X-Hermes-Session-Key`, `Idempotency-Key` (allowed under CORS).
- **Outputs / side effects:** `{"id": "chatcmpl-…", "object": "chat.completion", "created": …, "model": …, "choices": [{"index": 0, "message": {"role": "assistant", "content": …}, "finish_reason": "stop"}], "usage": {"prompt_tokens": …, "completion_tokens": …, "total_tokens": …}}`. With `"stream": true`, SSE of standard `chat.completion.chunk` events plus Hermes' custom `event: hermes.tool.progress` for tool-start visibility without polluting persisted assistant text.
- **Config / env:** `gateway.platforms.api_server.direct_model_requests` (default false) — a bare `model` without a `provider` is **ignored** on this endpoint unless enabled, because generic OpenAI clients hardcode names like `gpt-4o` and existing deployments rely on the fallback.
- **Edge cases / guards:** Uploaded files (`file` / `input_file` / `file_id`) and non-image `data:` URLs return **400 `unsupported_content_type`**.
- **Rebuild notes:** Layer the caller's system prompt rather than replacing it; a frontend prompt must not be able to strip the agent's tools.

### `POST /v1/responses` and the response store  `id: automation.api-responses`
- **Surface:** API
- **Where:** `POST /v1/responses`, `GET /v1/responses/{id}`, `DELETE /v1/responses/{id}`.
- **What it does:** OpenAI Responses API with **server-side conversation state**: the server stores the full history (including tool calls and results) so multi-turn context is preserved without the client managing it.
- **How it works:** `_handle_responses` / `_handle_get_response` / `_handle_delete_response`. `previous_response_id` chains a turn onto a stored response; the server reconstructs the whole conversation from the chain, and chained requests share one session so a multi-turn conversation appears as a single entry in the dashboard and session history. The `conversation` parameter names a conversation and auto-chains to its latest response.
- **Inputs / options:** Body: `model`, `input` (string or array of `{role, content:[{type: input_text|input_image, …}]}`), `instructions`, `store` (bool), `previous_response_id`, `conversation`, plus `provider` and `model_options`.
- **Outputs / side effects:** `{"id": "resp_…", "object": "response", "status": "completed", "model": …, "output": [ … ], "usage": {"input_tokens": …, "output_tokens": …, "total_tokens": …}}`. `output` replays already-executed tool calls as `{"type": "function_call", "status": "completed", "name": …, "arguments": …, "call_id": …}` followed by `{"type": "function_call_output", "status": "completed", "call_id": …, "output": …}` and finally `{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": …}]}` — never as pending calls for the client to execute. Streaming uses OpenAI Responses event types `response.created`, `response.output_text.delta`, `response.output_item.added`, `response.output_item.done`, `response.completed`, with spec-native `function_call` / `function_call_output` output items emitted during the stream.
- **Config / env:** `direct_model_requests` applies here too. Stored responses live in SQLite and survive gateway restarts; **max 100 stored responses with LRU eviction**.
- **Edge cases / guards:** Uploaded files (`input_file` / `file_id`) and non-image `data:` URLs return **400 `unsupported_content_type`**.
- **Rebuild notes:** Replaying server-executed tool calls with `status: completed` is the key compat trick — a client must never think it has to execute them.

### `GET /v1/models` and `GET /api/model/options`  `id: automation.api-models`
- **Surface:** API
- **Where:** `GET /v1/models`; `GET /api/model/options[?refresh=1]`.
- **What it does:** `/v1/models` is the cheap OpenAI-compat model-discovery list (one alias). `/api/model/options` is the rich Hermes picker inventory the dashboard Models page and the TUI `model.options` RPC use.
- **How it works:** `_handle_models` advertises the profile name (or `hermes-agent` for the default profile), overridable with `API_SERVER_MODEL_NAME`. `_handle_model_options` returns authenticated provider rows, curated model lists, per-model pricing and model capability hints.
- **Inputs / options:** `/api/model/options` accepts `?refresh=1`.
- **Outputs / side effects:** Model lists; `refresh=1` busts the provider model cache.
- **Config / env:** `API_SERVER_MODEL_NAME`, `gateway.api_server.model_name`.
- **Edge cases / guards:** `/v1/models` deliberately does **not** enumerate every authenticated provider/model combination and does no pricing or capability enrichment. Normal opens of `/api/model/options` are conservative for custom providers — only the **currently selected** custom endpoint is probed so a stale or offline saved endpoint cannot block the picker; `refresh=1` flips to full probing.
- **Rebuild notes:** Keep the compat surface cheap and put the rich inventory on a separate authenticated route.

### Per-request model selection and `model_routes`  `id: automation.api-model-routing`
- **Surface:** API / Config
- **Where:** The `model`, `provider` and `model_options` body fields on `POST /v1/chat/completions`, `POST /v1/responses`, `POST /v1/runs`, `POST /api/sessions/{id}/chat` and `POST /api/sessions/{id}/chat/stream`.
- **What it does:** Lets an authenticated client override the model, the provider and request-scoped reasoning/service-tier controls for one turn.
- **How it works:** Deterministic precedence, in order: (1) the session's `/model` override when that session already has one; (2) a static `gateway.platforms.api_server.model_routes` mapping selected when the request's `model` matches a configured route alias; (3) the direct request `model` / `provider` when no alias matches; (4) global gateway config / environment defaults. `model_options` stays request-scoped regardless of which model/provider wins.
- **Inputs / options:** `model` (target model id), `provider` (Hermes provider slug), `model_options` (e.g. `{"reasoning_effort": "high", "service_tier": "priority"}`).
- **Outputs / side effects:** That turn runs on the selected backend.
- **Config / env:** `gateway.platforms.api_server.model_routes`, `gateway.platforms.api_server.direct_model_requests`.
- **Edge cases / guards:** A request whose `provider` conflicts with a configured `model_routes` alias is rejected with **400** rather than silently remixing route credentials with another provider. Bare `model` without `provider` is ignored on the two OpenAI-compat endpoints unless `direct_model_requests: true`; explicit `provider`, and the Hermes-native `/v1/runs` and session-chat endpoints, always honour the requested model.
- **Rebuild notes:** Write the precedence down and test it; "which model actually ran" is the single most-asked support question for a compat endpoint.

### `GET /v1/capabilities`  `id: automation.api-capabilities`
- **Surface:** API
- **Where:** `GET /v1/capabilities`.
- **What it does:** Machine-readable description of the API server's stable surface, so external UIs, orchestrators and plugin bridges can discover support without depending on private Python internals.
- **How it works:** `_handle_capabilities` assembles the document from the live route table and feature probes.
- **Inputs / options:** Bearer auth.
- **Outputs / side effects:** Shape (verbatim from the docs): `{"object": "hermes.api_server.capabilities", "platform": "hermes-agent", "model": "hermes-agent", "auth": {"type": "bearer", "required": true}, "features": {"chat_completions": true, "responses_api": true, "run_submission": true, "run_status": true, "run_events_sse": true, "run_stop": true}}`. It also advertises `run_approval`, the `session_*` feature flags and `endpoints.session_*` / `endpoints.*` entries (including `/v1/skills` and `/v1/toolsets`), `"session_key_header": "X-Hermes-Session-Key"`, the idempotency block, and a `browser_extension_control` object reporting whether the feature is enabled, the protocol version, transport names and the exact capability allowlist.
- **Config / env:** n/a.
- **Edge cases / guards:** Feature detection here is the supported way to fall back safely; probing behaviour by trial requests is not.
- **Rebuild notes:** Generate the capabilities document from the same table that registers the routes so it cannot lie.

### `GET /health` and `GET /health/detailed`  `id: automation.api-health`
- **Surface:** API
- **Where:** `GET /health`, `GET /v1/health` (same handler, for clients expecting the `/v1/` prefix), `GET /health/detailed`.
- **What it does:** `/health` is a cheap unauthenticated liveness probe. `/health/detailed` is an authenticated readiness check for monitoring and control planes.
- **How it works:** `_handle_health` returns `{"status": "ok"}` and runs **no** readiness checks. `_handle_health_detailed` reports bounded status for the active profile's config, state database, configured model, disk space, gateway/platform state, active API runs, pending process completions and active delegations.
- **Inputs / options:** `/health/detailed` requires bearer auth.
- **Outputs / side effects:** `/health/detailed` exposes **status and counts, not config values, credentials, paths, commands, queue payloads, or raw errors**.
- **Config / env:** n/a.
- **Edge cases / guards:** A degraded readiness result still returns **HTTP 200** — callers must inspect the top-level `status` and `readiness.checks` fields rather than the status code.
- **Rebuild notes:** Two probes with different costs and different auth; a readiness check that runs on every liveness poll becomes the outage.

### `/api/sessions/*` (session control over REST)  `id: automation.api-sessions`
- **Surface:** API
- **Where:** `/api/sessions` and `/api/sessions/{session_id}/…`.
- **What it does:** Lets external UIs manage Hermes sessions over REST without standing up the dashboard.
- **How it works:** Handlers `_handle_list_sessions`, `_handle_create_session`, `_handle_get_session`, `_handle_patch_session`, `_handle_delete_session`, `_handle_session_messages`, `_handle_fork_session`, `_handle_session_chat`, `_handle_session_chat_stream`, `_handle_session_model_lock`. Forking branches the session via `SessionDB` lineage, matching CLI `/branch` semantics.
- **Inputs / options:** All nine routes: `GET /api/sessions` (paginated — `limit`, `offset`, `source`, `include_children`); `POST /api/sessions` (create an empty session); `GET /api/sessions/{id}`; `PATCH /api/sessions/{id}` (update `title` or `end_reason`); `DELETE /api/sessions/{id}`; `GET /api/sessions/{id}/messages`; `POST /api/sessions/{id}/fork` (body e.g. `{"title": "explore alt path"}`); `POST /api/sessions/{id}/chat` (one synchronous turn); `POST /api/sessions/{id}/chat/stream` (SSE wrapper over one turn). Plus `POST /api/sessions/{id}/model` to lock the session's model.
- **Outputs / side effects:** The SSE wrapper emits `assistant.delta`, `tool.started`, `tool.completed` and `run.completed` events.
- **Config / env:** All endpoints gated by `API_SERVER_KEY`.
- **Edge cases / guards:** Inline images are supported in `chat` and `chat/stream` payloads (multimodal-aware path). `/v1/capabilities` advertises the surface via `session_*` feature flags and `endpoints.session_*` entries so external UIs can detect support and fall back safely.
- **Rebuild notes:** Fork via the session store's own lineage so a branched session behaves identically to one branched from the CLI.

### `X-Hermes-Session-Id` and `X-Hermes-Session-Key` headers  `id: automation.api-session-headers`
- **Surface:** API
- **Where:** Request headers on `/v1/chat/completions`, `/v1/responses` and `/v1/runs`.
- **What it does:** `X-Hermes-Session-Id` scopes the transcript; `X-Hermes-Session-Key` is a stable per-channel identifier that scopes **long-term memory** (Honcho and friends) independently of the transcript, which rotates on `/new`.
- **How it works:** `_parse_session_key_header` (`gateway/platforms/api_server.py:2285`) validates and sanitises the key, which is then threaded into `AIAgent(gateway_session_key=…)` where the Honcho memory provider derives a stable scope. Callers may send either header, both, or neither.
- **Inputs / options:** Example value `agent:main:webui:dm:user-42`.
- **Outputs / side effects:** The key is echoed back on responses (JSON **and** SSE). `/v1/capabilities` advertises `"session_key_header": "X-Hermes-Session-Key"`.
- **Config / env:** n/a.
- **Edge cases / guards:** `_MAX_SESSION_HEADER_LEN = 256` chars — well above any realistic channel identifier while small enough that the sanitized form is safe to pass into Honcho / `state.db`. Control characters (`\r`, `\n`, `\x00`) are rejected. Accepting a caller-supplied memory scope requires API-key authentication. Without the key, Honcho's `per-session` strategy produces a different scope per `session_id` — the pre-feature behaviour.
- **Rebuild notes:** Separating "which transcript" from "whose long-term memory" is what makes a multi-user frontend work at all.

### `/api/jobs/*` (cron jobs over REST)  `id: automation.api-jobs`
- **Surface:** API
- **Where:** `/api/jobs` and `/api/jobs/{job_id}/…`.
- **What it does:** A lightweight CRUD surface for managing scheduled/background agent runs from a remote client — the REST face of `hermes cron`.
- **How it works:** Handlers `_handle_list_jobs`, `_handle_create_job`, `_handle_get_job`, `_handle_update_job`, `_handle_delete_job`, `_handle_pause_job`, `_handle_resume_job`, `_handle_run_job` over `cron/jobs.py`.
- **Inputs / options:** All eight routes: `GET /api/jobs` (list all scheduled jobs); `POST /api/jobs` (body accepts the same shape as `hermes cron` — prompt, schedule, skills, provider override, delivery target); `GET /api/jobs/{job_id}` (definition + last-run state); `PATCH /api/jobs/{job_id}` (partial updates are merged); `DELETE /api/jobs/{job_id}`; `POST /api/jobs/{job_id}/pause`; `POST /api/jobs/{job_id}/resume`; `POST /api/jobs/{job_id}/run`.
- **Outputs / side effects:** Mutates `cron/jobs.json`. `DELETE` also cancels any in-flight run. `pause` suspends next-scheduled-run timestamps until resumed. `run` triggers the job immediately, out of schedule.
- **Config / env:** All endpoints gated behind the same bearer auth.
- **Edge cases / guards:** Same job invariants as the CLI (mode validation, lifecycle guard, schedule parsing) because both go through `cron.jobs`.
- **Rebuild notes:** One job engine, many faces — do not let a REST layer grow its own job semantics.

### `POST /api/cron/fire` (Chronos webhook)  `id: automation.api-cron-fire`
- **Surface:** API
- **Where:** `POST /api/cron/fire`; registered only when cron is available.
- **What it does:** The ingress a managed-cron provider (Chronos, NAS-mediated) calls to fire a due job on this agent, for scale-to-zero deployments where the in-process ticker is not running.
- **How it works:** `_handle_cron_fire`. Authenticated by a **NAS-minted JWT**, explicitly *not* `API_SERVER_KEY`.
- **Inputs / options:** JWT bearer; body identifies the job to fire.
- **Outputs / side effects:** Runs the job through the ordinary `cron.scheduler.run_job` / `_deliver_result` path.
- **Config / env:** `cron.provider`, `cron.chronos.portal_url` (default `https://portal.nousresearch.com`), `cron.chronos.callback_url`, `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`.
- **Edge cases / guards:** Distinct auth means an API-key holder cannot forge a scheduler fire, and the scheduler cannot use its JWT to reach the rest of the API.
- **Rebuild notes:** Give each external caller its own credential class; sharing one bearer across a control plane and a webhook collapses two trust levels into one.

### `POST /api/platforms/{platform}/events`  `id: automation.api-platform-events`
- **Surface:** API
- **Where:** `POST /api/platforms/{platform}/events`.
- **What it does:** Generic HTTP event-callback ingress so external messaging platforms can deliver webhooks into the gateway.
- **How it works:** `_handle_platform_event_callback` dispatches to the named adapter, which verifies the request with **its own** platform-signed bearer.
- **Inputs / options:** Path parameter `platform`; the platform's own signed payload.
- **Outputs / side effects:** The adapter processes the event as an inbound message.
- **Config / env:** n/a.
- **Edge cases / guards:** Authenticated by the target adapter's verifier, **not** `API_SERVER_KEY` — external platforms hold no API-server key.
- **Rebuild notes:** Route third-party webhooks through the owning adapter's verifier; a shared key here would mean every platform can impersonate every other.

### `/v1/skills` and `/v1/toolsets` discovery  `id: automation.api-discovery`
- **Surface:** API
- **Where:** `GET /v1/skills`, `GET /v1/toolsets`.
- **What it does:** Lets external clients enumerate the agent's capabilities deterministically over REST instead of asking the model.
- **How it works:** `_handle_skills` returns the same metadata the skills hub uses internally; `_handle_toolsets` returns toolsets resolved for the `api_server` platform with the concrete `tools` list each expands to.
- **Inputs / options:** Bearer auth; read-only.
- **Outputs / side effects:** `/v1/skills` → `[{"name": "github-pr-workflow", "description": "...", "category": "..."}, …]`; `/v1/toolsets` → `[{"name": "core", "label": "...", "description": "...", "enabled": true, "configured": true, "tools": ["read_file", "write_file", …]}, …]`.
- **Config / env:** Gated by `API_SERVER_KEY`.
- **Edge cases / guards:** Both are advertised under `endpoints.*` in `/v1/capabilities`.
- **Rebuild notes:** Deterministic capability enumeration beats asking the model what it can do.

### `/v1/artifacts/upload` and `/v1/artifacts/download/{artifact_id}`  `id: automation.api-artifacts`
- **Surface:** API
- **Where:** `POST /v1/artifacts/upload`, `GET /v1/artifacts/download/{artifact_id}`.
- **What it does:** One-shot bounded artifact transport bound to a browser-control scope — how a controller hands a file to the agent and back.
- **How it works:** `_handle_artifact_upload` / `_handle_artifact_download`. Transfers are **SHA-256 validated** and bounded in size, over HTTPS.
- **Inputs / options:** Upload body carries the artifact and its digest; download takes the `artifact_id` path parameter (a receipt exposes `receipt.artifact_id`).
- **Outputs / side effects:** An artifact receipt the controller can exchange for the file.
- **Config / env:** Gated identically to browser-control registration: the `browser.extension_control.enabled` feature flag **plus** the API key, plus per-principal rate limits.
- **Edge cases / guards:** Bounded and digest-validated by design; the scope binding means an artifact cannot be fetched outside the browser-control session that produced it.
- **Rebuild notes:** Bind the artifact to the scope that created it and validate the digest server-side; an unbound download id is a data-exfiltration primitive.

### `/v1/browser-control/register` and `/v1/browser-control/ws`  `id: automation.api-browser-control`
- **Surface:** API
- **Where:** `POST /v1/browser-control/register`, then `GET /v1/browser-control/ws`.
- **What it does:** Routes the agent's browser tools through an authenticated browser extension that controls the browser session associated with the current Hermes session.
- **How it works:** Two-step: (1) an authenticated `POST /v1/browser-control/register` with `protocol_version`, `session_id`, `controller_id`, `browser_profile_id` and the requested `capabilities`; Hermes returns a **single-use ticket with a 30-second TTL** and the filtered, server-bound controller scope. (2) The controller opens `GET /v1/browser-control/ws` with **both** WebSocket subprotocols `hermes-browser-control-v1` and `hermes-browser-control-ticket.<ticket>`. Hermes then sends `browser.controller.command` frames (`command_id`, `action`, immutable `arguments`, browser/controller ids, originating `tool_call_id`); the controller replies with `browser.controller.result` carrying the same `command_id`, an exact boolean `ok`, and either `result` or `error`. Cancellation and timeout emit `browser.controller.cancel`; late results are ignored.
- **Inputs / options:** Capability allowlist, verbatim and complete: `controller.noop`, `browser_back`, `browser_click`, `browser_navigate`, `browser_press`, `browser_screenshot`, `browser_scroll`, `browser_snapshot`, `browser_tab_activate`, `browser_tabs`, `browser_type`. Anything outside this list is filtered out. Raw CDP, arbitrary script evaluation, console access, uploads, image extraction and vision are **not** part of the protocol. `browser.controller.detach` on the authenticated transport performs an intentional hard detach.
- **Outputs / side effects:** Browser actions executed in the controller's browser; results returned to the tool call.
- **Config / env:** `browser.extension_control.enabled` (default `false`) plus the API-server bearer key. Live contract discoverable through `GET /v1/capabilities` → `browser_extension_control`.
- **Edge cases / guards:** The ticket is **never** accepted in the query string; unknown, expired, reused or malformed tickets fail before the WebSocket upgrade. A controller may register only for an *existing* server session, and Hermes derives the principal from authenticated server state — a client-supplied `principal_id` is ignored. Selection requires one unambiguous exact match on principal, profile, session, controller, browser profile, transport family and capability; once selected, a controller failure is authoritative and is **never** retried through another browser backend. Missing, ambiguous, disconnected or incapable controllers fail closed rather than silently switching backends. An unexpected socket loss marks the controller offline and preserves in-flight work until each command's original deadline; a reconnect with the same principal/profile/session/controller id/browser profile/transport identity refreshes the transport without admitting new work before deferred cancels are flushed (negotiated capabilities may change on reconnect — they are not an identity field). A different controller id or browser profile in the same authenticated session lane is a **hard replacement**: old pending work is cancelled before the successor becomes routable. Merely closing the socket is a recoverable disconnect. The authenticated dashboard transport exposes the same registration/result/heartbeat/capability/ownership semantics over its Gateway RPC/event channel.
- **Rebuild notes:** Short-lived single-use ticket + subprotocol delivery (never the query string) + a server-side capability allowlist is the pattern; identity fields must be exactly the ones a reconnect must match.

### `/v1/room-members/*` (RoomLink grants)  `id: automation.api-room-members`
- **Surface:** API
- **Where:** `POST /v1/room-members/invitations`, `GET /v1/room-members/capabilities`, `POST /v1/room-members/grants/refresh`, `POST /v1/room-members/grants/revoke`.
- **What it does:** The target gateway's side of cross-gateway room membership: accept an invitation, advertise what a remote member may do here, renew a grant, and revoke one.
- **How it works:** `gateway/platforms/api_server_room_grants.py`. `_handle_room_member_invitation`, `_handle_room_member_capabilities`, `_handle_room_member_grant_refresh`, `_handle_room_member_grant_revoke`. `_require_unchanged_execution_policy(claims, execution_policy)` compares `execution_policy.policy_digest` against `claims.execution_policy_digest` and raises `RoomGrantReauthorizationRequired("room execution policy changed")` on a mismatch, so a renewal can never silently grant a changed execution policy.
- **Inputs / options:** Invitation body carries the room, member and policy coordinates; refresh/revoke carry the grant.
- **Outputs / side effects:** Grants stored in `hosted_room_links` / reservations in `hosted_room_peer_reservations`; revocations recorded in `hosted_room_revoked_grants` (`revoke_room_grant_scope`, `gateway/hosted_rooms.py:775`).
- **Config / env:** n/a.
- **Edge cases / guards:** Error mapping via `_room_grant_error_response`: a revoked or superseded but validly signed grant → **403** with `{"code": "room_reauthorization_required"}` and the message `Room authorization needs to be renewed.`; anything else invalid or expired → **401** with `{"code": "invalid_room_grant"}` and `Room authorization is invalid or expired.` Both use `err_type: "gateway_auth_error"`.
- **Rebuild notes:** Digest the policy into the grant so renewal cannot widen it; distinguish "renew me" (403) from "you are not authorised" (401) so clients can auto-recover from the former only.

### Room run dispatch  `id: automation.api-room-dispatch`
- **Surface:** Core / API
- **Where:** Internal — the path a hosted-room member turn takes when it is executed on this gateway via `/v1/runs`.
- **What it does:** Turns an admitted room-member dispatch into an ordinary run on this gateway, with the target's execution policy installed.
- **How it works:** `gateway/platforms/api_server_room_dispatch.py` (186 lines) bridges `HostedMemberDispatch` (from `gateway/hosted_room_peer.py`) into the runs pipeline, installing the `RoomExecutionPolicy` context and recording a remote-run receipt via `upsert_remote_run_receipt` (`gateway/hosted_rooms.py:1014`).
- **Inputs / options:** n/a (internal).
- **Outputs / side effects:** A `hosted_room_remote_runs` row keyed by `(room_id, home_install_id, authority_gateway_id, authority_epoch, member_id, target_install_id, target_profile, task_id, execution_generation)` so the same logical turn is never double-counted across epochs or generations.
- **Config / env:** n/a.
- **Edge cases / guards:** The nine-column primary key is the deduplication contract; `execution_generation` distinguishes a retried turn from the original.
- **Rebuild notes:** Make the remote-run receipt's key carry the full lineage (room, authority, epoch, member, task, generation); anything shorter collides after a takeover.

---

## 7. Peers, dynamic webhooks, and `hermes send`

### `hermes peer` (command group)  `id: automation.peer-group`
- **Surface:** CLI
- **Where:** `hermes peer {add,set,list,ls,remove,rm,dm,run,status,stop}`; group help verbatim: `Register other Hermes gateways as peers and message their agents. 'hermes peer dm <peer>[/<agent>] "..."' delivers into the remote agent's canonical Bot Chat over the peer's API server and prints the reply — the cross-machine twin of 'hermes -p <bot> chat'. The peer must run the api_server platform; its API_SERVER_KEY is stored locally as a credential in ~/.hermes/.env.`
- **What it does:** Bot-to-bot DMs across machines. A *peer* is another Hermes gateway (homelab, Spark, Hermes Cloud) running the `api_server` platform; registering it gives every bot on this machine a transport to message bots on that machine.
- **How it works:** `hermes_cli/subcommands/peer.py` (541 lines). `dm` resolves the remote agent's canonical `Bot Chat` session by title (creating it when missing: `_find_bot_chat` `:133`, `_ensure_bot_chat` `:152`), runs **one synchronous agent turn** over the peer's stock `POST /api/sessions/{id}/chat`, and prints the reply — the exact cross-machine twin of `hermes -p <bot> chat --in ~ -c "Bot Chat" …`, so the Bot Mode protocol composes over it unchanged. **No new server surface**: the peer's stock `api_server` is the transport. Peer labels/URLs live in `config.yaml` under `bot_peers`; the peer's `API_SERVER_KEY` is a credential in `~/.hermes/.env` as `HERMES_PEER_<NAME>_KEY` (`_peer_key_env`, `:53`). Named-profile targets use the peer's `/p/<profile>/` multiplex mirror (`_base_url`, `:125`); a bare target is the peer gateway's own launch profile.
- **Inputs / options:** `-h, --help` plus the sub-commands. Examples printed in the help, verbatim: `hermes peer add spark --url http://spark.lan:8377 --key <API_SERVER_KEY>`, `hermes peer list`, `hermes peer dm spark "Message from 🤖 dixie (@dixie): disk status?"`, `hermes peer dm spark/researcher "..."   # named profile on a multiplexed peer`, `hermes peer run spark --idempotency-key ticket-123 < long-task.txt`, `hermes peer status spark run_abc123`, `hermes peer stop spark run_abc123`, `hermes peer remove spark`.
- **Outputs / side effects:** `Exit codes: 0 ok, 1 delivery/peer error, 2 usage error.`
- **Config / env:** `bot_peers` in `config.yaml`; `HERMES_PEER_<NAME>_KEY` in `~/.hermes/.env`.
- **Edge cases / guards:** Peer names must match `^[a-z0-9][a-z0-9_-]{0,63}$` (`_PEER_NAME_RE`); profile names `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` (`_PROFILE_RE`). Timeouts: `DM_TIMEOUT_S = 600` (one synchronous agent turn can legitimately take minutes), `LIST_TIMEOUT_S = 30`. `BOT_CHAT_TITLE = "Bot Chat"` is the canonical session title.
- **Rebuild notes:** Reuse the existing authenticated session-chat endpoint instead of inventing a peer protocol; the whole feature is a client.

### `hermes peer add` (alias `set`)  `id: automation.peer-add`
- **Surface:** CLI
- **Where:** `hermes peer add <name> --url URL [--key KEY] [--note NOTE]`; help `Register (or update) a peer gateway`.
- **What it does:** Registers or updates a peer gateway and stores its API key locally.
- **How it works:** `_save_peers` writes the `bot_peers` map into `config.yaml`; the key goes to `~/.hermes/.env` as `HERMES_PEER_<NAME>_KEY`.
- **Inputs / options:** positional `name` "Peer name (lowercase slug, e.g. spark, homelab)"; `-h, --help`; required `--url URL` "Peer gateway base URL, e.g. http://spark.lan:8377"; `--key KEY` "The peer's API_SERVER_KEY (stored in ~/.hermes/.env)"; `--note NOTE` "Optional description".
- **Outputs / side effects:** Two files change: `config.yaml` (label/URL/note) and `.env` (secret).
- **Config / env:** `bot_peers.<name>`, `HERMES_PEER_<NAME>_KEY`.
- **Edge cases / guards:** Name must match the slug regex. Re-running with the same name updates in place.
- **Rebuild notes:** Split public metadata from the secret across two stores so the config file stays shareable.

### `hermes peer list` (alias `ls`) / `hermes peer remove` (alias `rm`)  `id: automation.peer-list-remove`
- **Surface:** CLI
- **Where:** `hermes peer list`; `hermes peer remove <name>`.
- **What it does:** Lists registered peers; removes one.
- **How it works:** Reads/writes `bot_peers` in `config.yaml`.
- **Inputs / options:** `list`: `-h, --help` only. `remove`: positional `name` "Peer name"; `-h, --help`.
- **Outputs / side effects:** stdout list; removal drops the config entry.
- **Config / env:** `bot_peers`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `hermes peer dm`  `id: automation.peer-dm`
- **Surface:** CLI
- **Where:** `hermes peer dm <target> [message] [--json]`; help `Message an agent on a peer gateway and print its reply`.
- **What it does:** Delivers a message into the remote agent's canonical Bot Chat, runs one synchronous turn there, and prints the reply.
- **How it works:** `_resolve_peer_target` (`:207`) splits `<peer>` or `<peer>/<agent>` (`_parse_target`, `:184`) and resolves the base URL + key; `_ensure_bot_chat` finds or creates the `Bot Chat` session; then `POST /api/sessions/{id}/chat`. `_message_from_args` (`:222`) takes the positional message or stdin.
- **Inputs / options:** positional `target` "<peer> or <peer>/<agent> (named profile on a multiplexed peer)"; positional optional `message` "Message text (or stdin)"; `-h, --help`; `--json` "Emit a JSON result".
- **Outputs / side effects:** Prints the remote agent's reply (or a JSON result). A `Bot Chat` session may be created on the peer.
- **Config / env:** `bot_peers`, `HERMES_PEER_<NAME>_KEY`.
- **Edge cases / guards:** `DM_TIMEOUT_S = 600` bounds the synchronous turn; HTTP errors are rendered by `_http_error_detail` (`:197`).
- **Rebuild notes:** Naming the remote session by a canonical title ("Bot Chat") is what makes bot-to-bot messaging idempotent across restarts.

### `hermes peer run` / `status` / `stop`  `id: automation.peer-run`
- **Surface:** CLI
- **Where:** `hermes peer run <target> [message] [--idempotency-key KEY] [--json]`; `hermes peer status <target> <run_id> [--json]`; `hermes peer stop <target> <run_id> [--json]`.
- **What it does:** The asynchronous pair for long turns: `run` starts the same canonical-session turn through the peer's Runs API and returns a `run_id` immediately; `status` polls that handle without holding the original HTTP connection open; `stop` cancels one run without affecting another turn.
- **How it works:** Posts to the peer's `POST /v1/runs` with the `Idempotency-Key` header, then `GET /v1/runs/{run_id}` and `POST /v1/runs/{run_id}/stop`. `_peer_run_durability(base, key)` (`:229`) probes the peer's `/v1/capabilities` to report whether its idempotency store is durable.
- **Inputs / options:** `run`: positional `target`, positional optional `message` "Message text (or stdin)", `--idempotency-key IDEMPOTENCY_KEY` "Stable retry key (generated when omitted)", `--json`. `status`: positional `target`, positional `run_id` "Run ID returned by 'hermes peer run'", `--json`. `stop`: same positionals, `--json`.
- **Outputs / side effects:** `run` prints the run id; `status` prints the status and final output; `stop` prints the stop acknowledgement.
- **Config / env:** as above.
- **Edge cases / guards:** An omitted `--idempotency-key` is generated (`uuid`), so a retry of the same shell invocation is *not* automatically deduplicated — pass a stable key for that.
- **Rebuild notes:** Expose the peer's durability through capability discovery so the caller knows whether a retry after a peer restart is safe.

### `hermes webhook` (command group)  `id: automation.webhook-group`
- **Surface:** CLI
- **Where:** `hermes webhook {subscribe,add,list,ls,remove,rm,test}`; group help `Create, list, and remove webhook subscriptions for event-driven agent activation`.
- **What it does:** Creates named HTTP routes (`/webhooks/<name>`) that external services POST to, waking the agent (or delivering a rendered message directly) with the payload.
- **How it works:** `hermes_cli/webhook.py`. Subscriptions persist to `~/.hermes/webhook_subscriptions.json` and are **hot-reloaded by the webhook adapter without a gateway restart** (`gateway/platforms/webhook.py`).
- **Inputs / options:** `-h, --help` plus the four sub-commands (aliases `add`→`subscribe`, `ls`→`list`, `rm`→`remove`).
- **Outputs / side effects:** Writes `webhook_subscriptions.json`.
- **Config / env:** Webhook platform config (`_get_webhook_config`, `:83`), enable flag (`_is_webhook_enabled`, `:93`), base URL (`_get_webhook_base_url`, `:97`); `_setup_hint()` (`:107`) prints the enablement instructions and `_require_webhook_enabled()` (`:132`) gates the commands.
- **Edge cases / guards:** The file contains per-route HMAC secrets, so `_save_subscriptions` (`:51`) writes via `tempfile.mkstemp` + `chmod 0o600` **before** the atomic rename — a permissive umask cannot leave the secrets world-readable in the window between create and rename.
- **Rebuild notes:** chmod-before-rename is the correct order for any secret-bearing file; chmod after rename leaves a real window.

### `hermes webhook subscribe` (alias `add`)  `id: automation.webhook-subscribe`
- **Surface:** CLI
- **Where:** `hermes webhook subscribe <name> [flags]`; help `Create a webhook subscription`.
- **What it does:** Defines one webhook route: which events it accepts, what prompt the payload renders into, which skills load, where the result is delivered, and optionally a filter script or agent-free direct delivery.
- **How it works:** `_cmd_subscribe` (`hermes_cli/webhook.py:162`) normalises the name (`lower()`, spaces→`-`), validates `^[a-z0-9][a-z0-9_-]*$`, auto-generates a secret with `secrets.token_urlsafe(32)` when none is given, and writes a route record `{description, events[], secret, prompt, skills[], deliver, created_at}` plus optional `deliver_only`, `script`, and `deliver_extra: {chat_id}`.
- **Inputs / options:** positional `name` "Route name (used in URL: /webhooks/<name>)"; `-h, --help`; `--prompt PROMPT` "Prompt template with {dot.notation} payload refs"; `--events EVENTS` "Comma-separated event types to accept"; `--description DESCRIPTION` "What this subscription does"; `--skills SKILLS` "Comma-separated skill names to load"; `--deliver DELIVER` "Delivery target: log, telegram, discord, slack, etc."; `--deliver-chat-id DELIVER_CHAT_ID` "Target chat ID for cross-platform delivery"; `--secret SECRET` "HMAC secret (auto-generated if omitted)"; `--deliver-only` "Skip the agent — deliver the rendered prompt directly as the message. Zero LLM cost. Requires --deliver to be a real target (not 'log')."; `--script SCRIPT` "Filter/transform script under ~/.hermes/scripts/. The route payload is passed as JSON on stdin; empty stdout, [SILENT], or a nonzero exit code ignores the webhook."
- **Outputs / side effects:** Prints, verbatim: `  Created webhook subscription: <name>` (or `  Updated …`), `  URL:    <base>/webhooks/<name>`, `  Secret: <secret>`, `  Events: <list>` or `  Events: (all)`, `  Deliver: <target>`, and when applicable `  Mode: direct delivery (no agent, zero LLM cost)`, `  Prompt: <first 80 chars…>` (labelled `  Message:` in deliver-only mode), `  Script: <path>`; then `  Configure your service to POST to the URL above.`, `  Use the secret for HMAC-SHA256 signature validation.`, `  The gateway must be running to receive events (hermes gateway run).`
- **Config / env:** Route defaults: `description` defaults to `Agent-created subscription: <name>`, `deliver` defaults to `log`.
- **Edge cases / guards:** An invalid name prints `Error: Invalid name '<name>'. Use lowercase alphanumeric with hyphens/underscores.` `--deliver-only` with `--deliver log` prints `Error: --deliver-only requires --deliver to be a real target (telegram, discord, slack, github_comment, etc.) — not 'log'.` The filter script's three "ignore this webhook" signals are empty stdout, `[SILENT]`, or a nonzero exit code — the same autonomous-lane silence matcher cron uses (`gateway.response_filters.is_autonomous_silence_response`).
- **Rebuild notes:** `--deliver-only` (render the template and send it, no LLM) plus a filter script covers most real webhook traffic at zero model cost; make that the easy path.

### `hermes webhook list` (alias `ls`)  `id: automation.webhook-list`
- **Surface:** CLI
- **Where:** `hermes webhook list`; help `List all dynamic subscriptions`.
- **What it does:** Prints every dynamic route with its URL, accepted events, delivery target and filter script.
- **How it works:** `_cmd_list` (`hermes_cli/webhook.py:227`).
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** Empty store prints `  No dynamic webhook subscriptions.` then `  Create one with: hermes webhook subscribe <name>`. Otherwise `  N webhook subscription(s):` then per route `  ◆ <name>`, the description line, `    URL:     <base>/webhooks/<name>`, `    Events:  <list>` or `(all)`, `    Deliver: <target>` (suffixed `(direct — no agent)` in deliver-only mode), and `    Script:  <path>` when set.
- **Config / env:** n/a.
- **Edge cases / guards:** Only *dynamic* routes are listed; static routes from `config.yaml` are a separate surface.
- **Rebuild notes:** Print the full URL, not just the name — the whole point is to paste it into another service.

### `hermes webhook remove` (alias `rm`)  `id: automation.webhook-remove`
- **Surface:** CLI
- **Where:** `hermes webhook remove <name>`; help `Remove a subscription`.
- **What it does:** Deletes a dynamic webhook subscription.
- **How it works:** `_cmd_remove` (`hermes_cli/webhook.py:253`).
- **Inputs / options:** positional `name` "Subscription name to remove"; `-h, --help`.
- **Outputs / side effects:** Prints `  Removed webhook subscription: <name>`.
- **Config / env:** n/a.
- **Edge cases / guards:** An unknown name prints `  No subscription named '<name>'.` followed by `  Note: Static routes from config.yaml cannot be removed here.`
- **Rebuild notes:** Say *why* a name was not found when two stores exist; a bare "not found" sends the user hunting.

### `hermes webhook test`  `id: automation.webhook-test`
- **Surface:** CLI
- **Where:** `hermes webhook test <name> [--payload PAYLOAD]`; help `Send a test POST to a webhook route`.
- **What it does:** POSTs a payload to the route so the operator can verify the end-to-end path without wiring the external service first.
- **How it works:** `_cmd_test` (`hermes_cli/webhook.py:267`) loads the route (for its secret and URL) and sends a signed request.
- **Inputs / options:** positional `name` "Subscription name to test"; `-h, --help`; `--payload PAYLOAD` "JSON payload to send (default: test payload)".
- **Outputs / side effects:** The gateway processes the event exactly as a real one.
- **Config / env:** Requires the gateway to be running to receive the event.
- **Edge cases / guards:** The test uses the route's real HMAC secret, so it also validates the signature path.
- **Rebuild notes:** A self-test that exercises the *signature* path is what catches the most common misconfiguration.

### `hermes send`  `id: automation.send`
- **Surface:** CLI
- **Where:** `hermes send [-t TARGET] [-f PATH] [-s LINE] [-l] [-q] [--json] [message]`; help verbatim: `Pipe text from any shell script to any messaging platform Hermes is already configured for. Reuses the gateway's platform credentials (~/.hermes/.env + ~/.hermes/config.yaml) — no LLM, no agent loop, no running gateway required for bot-token platforms like Telegram/Discord/Slack/Signal.`
- **What it does:** Sends a message (or a file's contents, or a media attachment) to any configured messaging platform from a shell script, CI hook, cron job or monitoring daemon — with no model call.
- **How it works:** `hermes_cli/send_cmd.py` (501 lines) is a thin wrapper around `tools/send_message_tool.py::send_message_tool`. `_read_message_body` (`:41`) resolves the body in order: (1) the positional argument, (2) `--file PATH` (or `--file -` for stdin), (3) piped stdin when not a TTY. `_resolve_target` (`:90`), `_emit_result` (`:97`), `_list_targets` (`:142`), `_load_hermes_env` (`:232`), `cmd_send` (`:328`), `register_send_subparser` (`:398`).
- **Inputs / options:** positional optional `message` "Message text. If omitted, read from --file or stdin."; `-h, --help`; `-t TARGET, --to TARGET` "Delivery target. Format: 'platform' (home channel), 'platform:chat_id', 'platform:chat_id:thread_id', or 'platform:#channel-name'. Examples: telegram, telegram:-1001234567890:17585, discord:#ops, slack:C0123ABCD, signal:+15551234567."; `-f PATH, --file PATH` "Read message body from PATH (text only). Use '-' to force stdin. To send an image/document as an attachment, use MEDIA:<path> in the message text instead."; `-s LINE, --subject LINE` "Prepend a subject/header line before the message body."; `-l, --list` "List available targets. Optional positional filter: `hermes send --list telegram`."; `-q, --quiet` "Suppress stdout on success (exit code only)."; `--json` "Emit raw JSON result instead of human-readable output."
- **Outputs / side effects:** The message is delivered. Exit codes, verbatim: `0 ok, 1 delivery/backend error, 2 usage error` (`_SUCCESS_EXIT = 0`, `_FAILURE_EXIT = 1`, `_USAGE_EXIT = 2`). Help examples, verbatim: `hermes send --to telegram "deploy finished"`, `echo "RAM 92%" | hermes send --to telegram:-1001234567890`, `hermes send --to discord:#ops --file /tmp/report.md`, `hermes send --to slack:#eng --subject "[CI]" --file build.log`, `hermes send --to telegram "MEDIA:/tmp/chart.png"   # send a media attachment`, `hermes send --list`, `hermes send --list telegram`.
- **Config / env:** Reuses `~/.hermes/.env` + `~/.hermes/config.yaml` platform credentials, loaded by `_load_hermes_env()`.
- **Edge cases / guards:** Passing a binary file to `--file` raises `UnicodeDecodeError` and prints the full guidance: `hermes send: <path> is not a text file. --file reads the message *body* (logs, reports, markdown).` / `To send an image/document/audio file as a native attachment, reference it with MEDIA: in the message text instead:` / `  hermes send --to telegram "MEDIA:<path>"` / `  hermes send --to telegram "optional caption MEDIA:<path>"` / `Add [[as_document]] to deliver an image as an uncompressed file:`. Bot-token platforms (Telegram, Discord, Slack, Signal, SMS, WhatsApp-CloudAPI) need **no running gateway**; platforms that rely on a persistent adapter connection (plugin platforms, Matrix in some modes) do, and the underlying tool surfaces that error.
- **Rebuild notes:** A credential-reusing, LLM-free `send` is the single most useful automation primitive an agent framework can ship; keep it dependency-free of the gateway process.

---

## 8. Automation infrastructure — providers, plugins, shipped scripts

### Chronos cron provider plugin  `id: automation.chronos-provider`
- **Surface:** Plugin | Config
- **Where:** `plugins/cron_providers/chronos/`; activated by `cron.provider: chronos`.
- **What it does:** Lets a hosted gateway scale to **zero** while idle and still fire cron jobs: instead of a 60 s in-process ticker, it asks Nous NAS to arm exactly one external one-shot per job at that job's real next-fire time, and NAS calls the agent back at fire time over an authenticated webhook.
- **How it works:** `plugins/cron_providers/chronos/__init__.py` defines `ChronosCronScheduler(CronScheduler)`; `_nas_client.py` speaks to NAS's `agent-cron` endpoints with the agent's existing Nous token; `verify.py` validates the callback. The callback lands on `POST /api/cron/fire` (NAS-minted JWT auth) and the agent runs the job through the shared `run_one_job` body, then re-arms the next one-shot. Wire contract: `docs/chronos-managed-cron-contract.md`.
- **Inputs / options:** `plugin.yaml`: `name: chronos`, `version: 1.0.0`, `author: Nous Research`, description verbatim: `Chronos — NAS-mediated managed cron provider for scale-to-zero hosted agents. Delegates the "wake me at time T" trigger to Nous infrastructure so an idle gateway can scale to zero and still fire cron jobs. The agent computes each job's next-fire time and asks NAS to arm a one-shot; NAS calls the agent back at fire time over an authenticated webhook. Inert unless cron.provider=chronos.`
- **Outputs / side effects:** External one-shots armed at NAS; job fires arrive as webhooks.
- **Config / env:** `cron.provider: chronos`, `cron.chronos.portal_url` (default `https://portal.nousresearch.com`), `cron.chronos.callback_url`, `cron.chronos.expected_audience`, `cron.chronos.nas_jwks_url`.
- **Edge cases / guards:** Design constraints (plan DQ-1): `start()` arms all enabled jobs and **returns** — it never blocks and never spawns a periodic wake, so between fires the machine is truly at zero; `reconcile` runs only on a warm process (start / `on_jobs_changed` / piggybacked on a fire), never as a periodic wake of a sleeping machine. Inert unless `cron.provider: chronos`, and `resolve_cron_scheduler` falls back to the built-in when Chronos is unavailable, so cron never loses its trigger. The external scheduler NAS uses is an internal NAS implementation detail — Chronos names no vendor and holds no scheduler credentials.
- **Rebuild notes:** "Arm one external one-shot per job, then exit" is the correct shape for scale-to-zero; a provider that keeps a timer alive defeats the whole point.

### Kanban dashboard plugin  `id: automation.kanban-dashboard-plugin`
- **Surface:** Plugin | Web dashboard
- **Where:** `plugins/kanban/dashboard/`; adds a `/kanban` tab positioned `after:skills` in the dashboard.
- **What it does:** Ships the board UI as a dashboard plugin: drag-and-drop cards across columns, read comment threads, and see which profile is running what.
- **How it works:** `manifest.json` declares `{"name": "kanban", "label": "Kanban", "description": "Multi-agent collaboration board — drag-drop cards across columns, read comment threads, see which profile is running what", "icon": "Package", "version": "1.0.0", "tab": {"path": "/kanban", "position": "after:skills"}, "entry": "dist/index.js", "css": "dist/style.css", "api": "plugin_api.py"}`. `plugin_api.py` is the server-side half; `dist/index.js` + `dist/style.css` the built frontend.
- **Inputs / options:** n/a here (the page's own controls belong to the web shard).
- **Outputs / side effects:** Registers a dashboard tab and a plugin API namespace.
- **Config / env:** Standard dashboard plugin loading.
- **Edge cases / guards:** The plugin is a *view* over the same board DB the CLI uses — there is no second board model.
- **Rebuild notes:** Shipping the board UI as a plugin (rather than core) is what lets the board evolve without a dashboard release.

### Standalone kanban dispatcher systemd unit (deprecated)  `id: automation.kanban-systemd`
- **Surface:** Plugin / Docs
- **Where:** `plugins/kanban/systemd/hermes-kanban-dispatcher.service`.
- **What it does:** A user-level systemd unit that runs the standalone kanban dispatcher for hosts that genuinely cannot run a gateway.
- **How it works:** `Description=Hermes Kanban dispatcher (DEPRECATED standalone daemon — prefer gateway-embedded dispatch)`, `Documentation=https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban`, `After=network.target`, `Type=simple`, `ExecStart=/usr/bin/env hermes kanban daemon --force --interval 60 --pidfile %t/hermes-kanban-dispatcher.pid`, `Restart=on-failure`, `RestartSec=5`, `StandardOutput=journal`, `StandardError=journal`, `WantedBy=default.target`.
- **Inputs / options:** The unit's own systemd knobs; the daemon flags it passes.
- **Outputs / side effects:** Journal logs; per-task worker output still goes to `$HERMES_HOME/kanban/logs/<task>.log`.
- **Config / env:** `kanban.dispatch_in_gateway` (default `true`) must be considered — the header documents the migration: `systemctl --user disable --now hermes-kanban-dispatcher.service`, then run a gateway.
- **Edge cases / guards:** The unit invokes the daemon with the **undocumented** `--force` flag (`hermes_cli/kanban.py:822`, `help=argparse.SUPPRESS`) so nobody discovers the double-dispatcher pattern casually. Running this unit **and** a gateway with `dispatch_in_gateway=true` is explicitly NOT supported.
- **Rebuild notes:** Hide the escape hatch from `--help` but keep it working, and make the deprecated artefact carry its own migration instructions.

### `cron/scripts/classify_items.py` (urgency classifier)  `id: automation.classify-items`
- **Surface:** Core / Tool (shipped script)
- **Where:** Shipped with the package; absolute path from `cron.suggestion_catalog.classify_items_script_path()`; invoked as `python3 -m cron.scripts.classify_items …`.
- **What it does:** The proactive-monitor pattern in one script: takes a JSON list of candidate items on stdin, scores each with a cheap LLM against plain-language criteria, and prints **only** the items at or above a threshold. Below-threshold runs print nothing, so a cron job wrapping it stays silent unless something actually matters.
- **How it works:** Uses Hermes' auxiliary client with `task="monitor"`, so the classifier model is configured once under `auxiliary.monitor.{provider,model}` and can be a cheap fast model independent of the main chat model. **One** LLM call scores the whole batch (single round trip) and returns structured scores; filtering happens locally.
- **Inputs / options:** `--criteria` (required) "Plain-language importance criteria."; `--threshold` (int, default 7) "Minimum score (0-10) to surface. Default 7."; `--input-file` (default None) "Read items JSON from this file instead of stdin."; `--format {text,json}` (default `text`) "Output format for surfaced items."
- **Outputs / side effects:** Surfaced items on stdout; empty result → empty stdout → the cron job's `[SILENT]`/empty-stdout path suppresses delivery, so quiet intervals produce no spam.
- **Config / env:** `auxiliary.monitor.provider`, `auxiliary.monitor.model`.
- **Edge cases / guards:** Item schema is flexible — each item is an object and the classifier sees the whole object; a `title`/`subject`/`summary`/`text` field helps it judge, and an id field (`id`/`guid`/`message_id`/`url`) is echoed back so duplicates can be deduped upstream. Documented usage, verbatim: `cat items.json | python classify_items.py --threshold 7 --criteria "Urgent if it needs a reply today or is from my manager/family"`.
- **Rebuild notes:** One batched scoring call plus local filtering is the cheap shape; per-item calls make a 30-minute monitor expensive. Reuse the empty-stdout convention so the script composes with the scheduler's silence path for free.

---

## 9. Kanban board model — lanes, diagnostics, workspaces

### Kanban worker lanes  `id: automation.kanban-worker-lanes`
- **Surface:** Core / Docs
- **Where:** Defined by a card's `assignee` string; documented in `website/docs/user-guide/features/kanban-worker-lanes.md`.
- **What it does:** A *worker lane* is a class of process the dispatcher can route tasks to. Each lane has an identity (the assignee string), a spawn mechanism, and a contract for what it must do with the task once spawned.
- **How it works:** The hierarchy, verbatim from the docs: `Hermes Kanban  =  canonical task lifecycle + audit trail`, `Worker lane    =  implementation executor for one assigned card`, `Reviewer       =  human or human-proxy that gates "done"`, `GitHub PR      =  upstreamable artifact (optional, for code lanes)`. Kanban owns lifecycle truth (`ready → running → review / blocked / done / archived`); lanes execute work but never own that truth — everything flows back through the kernel via the `kanban_*` tools, or via the API for non-Hermes external workers. For Hermes profile lanes, the dispatcher's `_default_spawn` runs `hermes -p <assignee> chat -q <prompt>` (or the equivalent module form when the `hermes` shim is not on `$PATH`) inside the task's pinned workspace. Non-Hermes lanes register a plugin `spawn_fn` callable that receives `task`, `workspace` and `board` and returns an optional pid for crash detection. The kanban lifecycle and reference details are injected into the worker's system prompt automatically via the `KANBAN_GUIDANCE` block in `agent/prompt_builder.py`.
- **Inputs / options:** Environment handed to a spawned Hermes-profile worker, all of it: `HERMES_KANBAN_TASK` (the task id), `HERMES_KANBAN_DB` (absolute path to the per-board SQLite file), `HERMES_KANBAN_BOARD` (board slug), `HERMES_KANBAN_WORKSPACES_ROOT` (root of the board's workspace tree), `HERMES_KANBAN_WORKSPACE` (absolute path to *this* task's workspace), `HERMES_KANBAN_RUN_ID` (the current run's id, for the lifecycle gate), `HERMES_KANBAN_CLAIM_LOCK` (the claim lock string `<host>:<pid>:<uuid>`), `HERMES_PROFILE` (the worker's own profile name, for `kanban_comment` author attribution), `HERMES_TENANT` (tenant namespace, if the task has one).
- **Outputs / side effects:** Every claim must end in exactly one of four terminators: `kanban_complete(summary=…, metadata=…)` → `done`; `kanban_request_review(summary=…, metadata=…, reviewer=…)` → `review` (the dispatcher loads the bundled `sdlc-review` skill unless `kanban.review_dispatch` is disabled; a reviewer approves with `kanban_complete`, returns rework with `kanban_request_changes`, or escalates with `kanban_block`); `kanban_block(reason=…)` → `blocked` (the dispatcher respawns when `kanban_unblock` runs); or the worker process exits without a tool call, which the kernel reaps as `crashed` (PID died), `gave_up` (consecutive-failure breaker tripped) or `timed_out` (`max_runtime` exceeded).
- **Config / env:** `kanban.review_dispatch`, `kanban.failure_limit`, per-card `max_retries` and `max_runtime_seconds`.
- **Edge cases / guards:** A card whose `assignee` resolves to neither a Hermes profile nor a registered non-spawnable identifier is left on `ready` with a `skipped_nonspawnable` event so a board operator can fix it — it is **not** silently dropped or executed by an arbitrary fallback. The kernel enforces exactly one terminator per run; a worker that calls none and exits normally is treated as crashed.
- **Rebuild notes:** Define the lane contract (identity, spawn, terminator) as a written interface and pass everything the worker needs through the environment; that is what makes a non-Hermes CLI worker a first-class lane instead of a fork.

### Kanban workspaces  `id: automation.kanban-workspaces`
- **Surface:** Core
- **Where:** `--workspace` on `hermes kanban create`; resolved path printed by `hermes kanban claim`; root at `<kanban-root>/kanban/workspaces/` (or per-board equivalent).
- **What it does:** Gives every card an isolated directory to work in, so parallel workers on the same board cannot clobber each other.
- **How it works:** `VALID_WORKSPACE_KINDS = {"scratch", "worktree", "dir"}` (`hermes_cli/kanban_db.py:135`) with the resolved path stored in `tasks.workspace_path` and the branch (for worktrees) in `tasks.branch_name`. `scratch` mints a throwaway directory under the workspaces root; `worktree` creates a git worktree (anchored under the project's primary repo with a deterministic branch when the card is linked to a project via `--project`, else a random `wt/<task-id>` branch); `dir:<path>` pins an explicit directory. The board's `set-default-workdir` supplies a default.
- **Inputs / options:** `--workspace scratch | worktree | worktree:<path> | dir:<path>` (default `scratch`); `--branch BRANCH` for worktree tasks (e.g. `wt/t6-wire`); `--project PROJECT`.
- **Outputs / side effects:** Directories under the workspaces root; git worktrees and branches in the target repo. `HERMES_KANBAN_WORKSPACE` carries the resolved path into the worker.
- **Config / env:** `HERMES_KANBAN_WORKSPACES_ROOT`, board default workdir.
- **Edge cases / guards:** `hermes kanban gc` garbage-collects archived tasks' workspaces; a `tip_scratch_workspace` event nudges the operator when a scratch workspace was probably not what they wanted. Worktree-kind cards interact with `hermes worktree prune`'s safety rules — kanban-owned trees are recognised by `_KANBAN_RE = ^t_[0-9a-f]+$`.
- **Rebuild notes:** Three workspace kinds cover everything: throwaway, git-isolated, and pinned. Store the *resolved* path on the card so a restarted dispatcher does not re-derive it differently.

### Kanban diagnostics engine  `id: automation.kanban-diagnostics-engine`
- **Surface:** Core / CLI / Web dashboard
- **Where:** Computed on demand on `/board` load, on `/tasks/:id` fetch, and by `hermes kanban diagnostics`.
- **What it does:** Turns "something is wrong with this card" into a machine-readable, actionable signal with suggested recovery actions the dashboard renders as buttons and the CLI renders as hints.
- **How it works:** `hermes_cli/kanban_diagnostics.py`. A `Diagnostic` carries a **kind** (canonical code the UI/tests match on), a **severity**, a **title** (one line) and **detail** (longer text), plus a list of structured **suggested actions**. Rules run over `(task, recent events, recent runs, optional graph context)` and are **stateless and read-only — no DB writes**. `compute_task_diagnostics()` (`:1171`) is the entry point; `severity_at_or_above(severity, threshold)` (`:44`) implements the `--severity` filter.
- **Inputs / options:** Severity rungs, ordered least → most urgent: `SEVERITY_ORDER = ("warning", "error", "critical")`; the UI colours them amber / orange / red and sorts critical first. Diagnostic kinds emitted by the nine rules, all of them: `hallucinated_cards` (`_rule_hallucinated_cards`, `:325`), `triage_aux_unavailable` (`:372`), `prose_phantom_refs` (`:484`), `repeated_failures` (`:518`), `repeated_crashes` (`:653`), `review_dependency_deadlock` (`:753`), `stuck_in_blocked` (`:831`), `block_unblock_cycling` (`:881`), `stranded_in_ready` (`:958`). Suggested-action kinds: `reclaim`, `reassign`, `comment`, `cli_hint`.
- **Outputs / side effects:** A human table by default, or structured JSON with `--json`.
- **Config / env:** Rule thresholds read from config: `crash_threshold`, `failure_threshold` / `failure_limit`, `blocked_stale_hours`, `block_cycle_threshold`, `block_cycle_window_seconds`, plus `auxiliary.kanban_decomposer` / `auxiliary.triage_specifier` availability for `triage_aux_unavailable`.
- **Edge cases / guards:** Design goals, verbatim: fixable-on-the-operator's-side signals only (missing config, phantom ids, crash loop) — **not** "the provider returned 502 once", which is a transient blip, not a diagnostic; every diagnostic comes with at least one recovery action the operator can actually take; and diagnostics are **auto-clearing** — when the underlying failure mode resolves (a clean `completed` event arrives, a spawn succeeds, the task gets unblocked) the diagnostic stops firing while the audit event trail stays.
- **Rebuild notes:** Stateless rules over (task, events, runs) with a canonical kind code and attached actions is the right shape: nothing to migrate, nothing to garbage-collect, and the UI can render a button per action without knowing the rule.

---

## 10. Gateway runtime hooks that drive automation

### Gateway cron trigger  `id: automation.gateway-cron-ticker`
- **Surface:** Core / Gateway
- **Where:** Started by `start_gateway` when the gateway boots; the reason `hermes cron status` reports on the gateway process at all.
- **What it does:** Runs the cron trigger inside the long-lived gateway process, so scheduled jobs actually fire without a separate daemon.
- **How it works:** `gateway/run.py` resolves a `CronScheduler` provider (`cron.scheduler_provider`) and runs its `start()` directly. `_start_cron_ticker(stop_event, adapters=None, loop=None, interval=60)` (`gateway/run.py:32273`) is a **deprecated shim** kept for external callers and tests (e.g. `hermes_cli/debug.py`) — it runs only the built-in in-process tick loop and no longer performs gateway housekeeping, which moved to `_start_gateway_housekeeping`. `_stop_cron_provider(provider)` (`gateway/run.py:32288`) stops a provider without letting it choose the gateway exit code: a `SystemExit` from `stop()` is caught and logged as `Cron provider stop() attempted to exit the gateway with code <code>; ignoring`.
- **Inputs / options:** `interval` defaults to 60 seconds.
- **Outputs / side effects:** Due jobs fire; the ticker heartbeat epoch files are refreshed each cycle.
- **Config / env:** `cron.provider` selects the provider; `HERMES_CRON_DRAIN_TIMEOUT` interacts with the shutdown drain.
- **Edge cases / guards:** `_CRON_SHUTDOWN_DRAIN_TIMEOUT = 65.0` s — the cron thread delivers via `safe_schedule_threadsafe` and blocks on `future.result(timeout=60)`, so a single in-flight delivery unblocks within ~60 s and the extra margin covers the hop back through `run_one_job`'s bookkeeping. `_await_thread_exit()` polls `is_alive()` with `await asyncio.sleep` instead of a synchronous `join()`, because blocking the event loop would deadlock the pending delivery that is itself scheduled on that loop (a `join(timeout=5)` always timed out and silently dropped the message on restart). `_HOUSEKEEPING_SHUTDOWN_DRAIN_TIMEOUT = 35.0` s covers the housekeeping ticker's 30 s channel-directory refresh future.
- **Rebuild notes:** Never `join()` a worker thread from the event loop that thread is scheduling work onto; poll instead. And bound the drain by the worst-case in-flight future, not by a guessed constant.

### `/loop` idle wakeup watcher (gateway)  `id: automation.loop-wakeup-watcher`
- **Surface:** Core / Gateway
- **Where:** A gateway background task; the mechanism that makes `/loop` work on messaging platforms.
- **What it does:** Fires due `/loop` wakeups for idle gateway sessions by injecting the wakeup prompt into the right chat.
- **How it works:** `_loop_wakeup_watcher(interval=15.0)` (`gateway/run.py:23679`). The gateway has no per-session scheduler thread, so this coarse ticker scans persisted loops (SessionDB `loop:*` rows via `list_active_loops()`) and injects the wakeup through the same synthetic-message path used by watch notifications. It sleeps 5 s at start to let platforms finish connecting, and warms the SessionDB cache off-loop once per scan so a cold cache does not run `state.db` init on the loop thread. The companion `_post_turn_loop_completion` (`gateway/run.py:23636`) runs after each gateway turn: it no-ops unless the session has a loop with `awaiting_response`, then calls `mgr.complete_tick` **in an executor** (the `--until` judge is a synchronous aux-LLM call that must stay off the event loop) and defers any status notice until after delivery.
- **Inputs / options:** Poll interval 15 s.
- **Outputs / side effects:** A user-role wakeup message injected into the loop's chat; the loop's `ticks_fired` / `next_due_at` advance.
- **Config / env:** `loops.*`.
- **Edge cases / guards:** Three documented deferrals, verbatim: a session currently running an agent turn is skipped (it stays due; the adapter FIFO would otherwise race the live turn); an active non-parked `/goal` on the session is skipped (the goal owns the idle boundary, via `goal_blocks_loop_tick`); a loop with no routing metadata is skipped with a one-time warning (CLI/TUI loops carry no `route` and are driven by their own surfaces). A loop whose platform has no connected adapter logs `loop wakeup: no adapter for platform <p> (session <sid>)` once.
- **Rebuild notes:** One coarse scanner over persisted state beats a timer per session, and every skip must leave the tick *due* rather than consuming it.

### Kanban worker stop-guard (turn-end nudge)  `id: automation.kanban-stop-nudge`
- **Surface:** Core
- **Where:** Inside a dispatcher-spawned kanban worker's conversation loop, at turn end.
- **What it does:** Stops a worker from ending its run without a terminal board tool call — the failure mode where a model narrates the next step ("Let me write the report now") and stops with `finish_reason=stop` and no tool calls, which Hermes would otherwise read as a clean exit (`rc=0`) and the dispatcher would record as `protocol_violation`.
- **How it works:** `agent/kanban_stop.py`. `kanban_stop_nudge_enabled()` (`agent/kanban_stop.py:25`) is on whenever `HERMES_KANBAN_TASK` is set (i.e. a dispatcher-spawned worker) unless `HERMES_KANBAN_STOP_NUDGE` is explicitly `0`/`false`/`no`/`off`. `session_called_kanban_terminal(messages)` (`agent/kanban_stop.py:50`) scans the conversation for an assistant `tool_calls` entry or a `tool` message naming one of `_TERMINAL_KANBAN_TOOLS = {"kanban_complete", "kanban_block"}`. When the worker tries to finish without one, `build_kanban_stop_nudge(...)` returns a bounded synthetic nudge so the conversation loop continues instead of exiting.
- **Inputs / options:** `HERMES_KANBAN_STOP_NUDGE` (`0`/`false`/`no`/`off` disables); `_DEFAULT_MAX_ATTEMPTS = 2` bounds how many times the nudge is applied.
- **Outputs / side effects:** One extra synthetic user turn per attempt; on exhaustion the run ends as before.
- **Config / env:** `HERMES_KANBAN_TASK`, `HERMES_KANBAN_STOP_NUDGE`.
- **Edge cases / guards:** The module is **policy-only** — it decides whether to nudge and what to say, and touches no board state. Bounded attempts prevent an infinite nudge loop against a model that will never call the tool.
- **Rebuild notes:** When a protocol requires a terminal tool call, detect the missing call at turn end and re-prompt a bounded number of times; treating "stopped talking" as success is what turns a model quirk into a corrupted board.

### Cron delivery mirroring (`cron.mirror_delivery` / `attach_to_session`)  `id: automation.cron-mirror-delivery`
- **Surface:** Core / Config
- **Where:** Global config key `cron.mirror_delivery` (default `false`); per-job `attach_to_session` (persisted only when explicitly set).
- **What it does:** Also writes a scheduled job's delivered output into the origin session's transcript, so a continuable cron thread reads as part of the conversation instead of an orphan message.
- **How it works:** `_cron_mirror_delivery_enabled(job, cfg)` (`cron/scheduler.py:1663`) resolves the per-job flag over the global key. `_maybe_mirror_cron_delivery(...)` (`:1822`) performs the mirror; eligibility is decided by `_target_matches_origin` (`:1703`) and `_target_mirror_eligible` (`:1747`), using the `_resolved_from` provenance stamped by `_resolve_single_delivery_target` (`origin` and `origin_fallback` are mirror-eligible; a broadcast target is not). `_inchannel_seed_allowed(is_dm=…, user_id=…)` (`:1807`) gates in-channel seeding. Thread/session seeding goes through `_open_continuable_cron_thread` (`:1892`), `_seed_cron_thread_session` (`:1929`) and `_seed_cron_channel_session` (`:2052`). `_is_channel_dm_topic(...)` (`:3007`) classifies the destination.
- **Inputs / options:** `cron.mirror_delivery: true|false`; per-job `attach_to_session: true|false`.
- **Outputs / side effects:** The delivered content appears in the origin session's transcript, making the cron output continuable in chat.
- **Config / env:** `cron.mirror_delivery` (default `false`).
- **Edge cases / guards:** `attach_to_session` is written to the job record **only** when explicitly set, so existing jobs stay byte-identical and an absent key falls back to the global config. Mirroring is deliberately restricted to targets that *are* the user's primary conversation — a broadcast delivery must not be seeded into a session.
- **Rebuild notes:** Track *why* a delivery target was chosen (`_resolved_from`) so downstream policy can distinguish "the user's own chat" from "a broadcast channel"; without that provenance, mirroring either over- or under-fires.

---

## 11. Cron execution policy (toolsets, reasoning, agent scheduling)

### Cron toolset resolution  `id: automation.cron-toolsets`
- **Surface:** Core / Config
- **Where:** Invisible; decides which tools a cron-spawned agent gets. Configured via the `cron` platform in `hermes tools`, per-job `enabled_toolsets`, and `agent.disabled_toolsets`.
- **What it does:** Restricts a scheduled agent to a chosen set of toolsets, cutting token overhead and cost, while making sure a job-scoped allowlist cannot widen past policy.
- **How it works:** `_resolve_cron_enabled_toolsets(job, cfg)` (`cron/scheduler.py:600`) with precedence: (1) the per-job `enabled_toolsets` (set through the `cronjob` tool at create/update) — enabled MCP servers are layered on by `_merge_mcp_into_per_job_toolsets` (`:569`); (2) the per-platform `hermes tools` config for the `cron` platform (`_get_platform_tools(cfg, "cron")`), mirroring gateway behaviour so cron toolsets can be gated globally without recreating every job; (3) `None` on any lookup failure, which makes `AIAgent` load the full default set (the legacy safety net), logging `Cron toolset resolution failed, falling back to full default toolset: <exc>`.
- **Inputs / options:** MCP layering rules, all three: the `no_mcp` sentinel present → no MCP servers (the sentinel is stripped); one or more MCP server names already listed → treated as an allowlist and nothing further is added (the user named exactly the servers they want); otherwise → union in every globally-enabled MCP server (`enabled_mcp_server_names(cfg)`).
- **Outputs / side effects:** The agent constructed for the run receives exactly this toolset list.
- **Config / env:** `agent.disabled_toolsets`, the `cron` entry of the platform tools config, per-job `enabled_toolsets`.
- **Edge cases / guards:** `_resolve_cron_disabled_toolsets(cfg)` (`cron/scheduler.py:535`) always removes `messaging` (interactive, needs a live gateway session) and `clarify` (interactive, blocks waiting for user input) regardless of config, and additionally `cronjob` unless `cron.allow_agent_scheduling` is true. The **user's** `agent.disabled_toolsets` is layered on top so a per-job `enabled_toolsets` cannot bypass policy that applies to ordinary agent runs (an LLM-supplied list was previously widening past config.yaml's denylist). `_DEFAULT_OFF_TOOLSETS` (`{moa, homeassistant, rl}`) are removed by `_get_platform_tools` for unconfigured platforms, so fresh installs get cron **without** `moa` by default (the fix for a surprise $4.63 run).
- **Rebuild notes:** An allowlist supplied by the model must be intersected with, never unioned onto, the operator's denylist. And a native-toolset allowlist must explicitly re-add MCP servers or every `mcp_*` call fails with "Unknown tool".

### `cron.allow_agent_scheduling`  `id: automation.cron-allow-agent-scheduling`
- **Surface:** Config
- **Where:** `cron.allow_agent_scheduling` in `config.yaml`; default `false` (`hermes_cli/config_defaults.py:2715`).
- **What it does:** Decides whether an agent *running inside a cron job* may manage the user's cron table — i.e. whether the `cronjob` toolset is available to a cron-spawned agent.
- **How it works:** `_resolve_cron_disabled_toolsets` (`cron/scheduler.py:535`) puts `cronjob` on the base denylist unless this key is truthy; setting it to `true` drops `cronjob` from the **built-in policy** denylist only.
- **Inputs / options:** boolean; default `false`.
- **Outputs / side effects:** With it on, a scheduled agent can create/edit/remove cron jobs.
- **Config / env:** `cron.allow_agent_scheduling`.
- **Edge cases / guards:** Documented in code as **loop prevention, not a security boundary** — the point is stopping a scheduled job from spawning more scheduled jobs, not sandboxing. The gate only removes the built-in policy denial; it **never** overrides the user's `agent.disabled_toolsets`.
- **Rebuild notes:** Be explicit in the code about which denials are safety and which are loop prevention — conflating them makes every future exception look dangerous.

### Cron reasoning-effort resolution  `id: automation.cron-reasoning`
- **Surface:** Core / Config
- **Where:** `--reasoning-effort` on `hermes cron create|edit`; the job record's `reasoning_effort` field.
- **What it does:** Pins how hard the model thinks for one scheduled job, overriding both the global setting and per-model overrides.
- **How it works:** `_resolve_job_reasoning_config(job, cfg, model)` (`cron/scheduler.py:633`). Precedence: the per-job `reasoning_effort` pin — validated at the store choke point `cron/jobs.py:2090` `_normalize_reasoning_effort` — wins outright over both `agent.reasoning_effort` and per-model `agent.reasoning_overrides`. The pin is model-independent by design so it also governs an auth-fallback model swap.
- **Inputs / options:** Accepted levels: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra` (case-insensitive); empty string clears the pin.
- **Outputs / side effects:** The run's request carries the resolved thinking configuration.
- **Config / env:** `agent.reasoning_effort`, `agent.reasoning_overrides`.
- **Edge cases / guards:** Capability is **not** validated at create time — levels above what the resolved model supports are clamped or omitted by the provider transport at send time, exactly like a config-set effort. The pin is inert with `no_agent=True` (there is no LLM call to configure). The `cronjob` model tool cannot set `--model`/`--provider` (user-owned), but reasoning effort follows the normal store validation.
- **Rebuild notes:** Validate the *level name* at the store boundary and let the transport clamp capability; validating capability at create time makes a job break the day you switch models.

---

## Handoffs

- `cronjob` model tool — full JSON schema, `action` verb list, and the `_scan_cron_prompt` / `_scan_cron_skill_assembled` / `_validate_cron_base_url` validators in `tools/cronjob_tools.py` (tools shard).
- `kanban_*` model tools (`kanban_create`, `kanban_claim`, `kanban_complete`, `kanban_block`, `kanban_request_review`, `kanban_request_changes`, `kanban_comment`, `kanban_unblock`, …) — schemas and per-tool guards (tools shard).
- `desktop_project` model tool — schema and desktop-side behaviour (tools shard / desktop shards).
- `/cron`, `/blueprint`, `/suggestions`, `/kanban`, `/loop`, `/heartbeat`, `/goal`, `/subgoal`, `/refine`, `/worktree` slash-command **dispatch** mechanics, permission gating and per-platform rendering — `gateway/slash_commands.py`, `gateway/slash_access.py` (gw-slash shard).
- Dashboard pages that render this shard's data — Automations/Cron page, Kanban board page (`plugins/kanban/dashboard/dist/index.js`), Webhooks page, Projects page, Runs viewer — plus their i18n keys and buttons (web-* shards).
- Desktop app scheduler dialogs (the "weekdays at 9am" natural-language input the `parse_schedule` fallback exists for), the Group Chat / Bot Mode room UI, and the desktop board switcher's Export/Import items (desktop-* shards).
- TUI automation panes and the TUI's `model.options` RPC (tui shard).
- `delegation.*` config tree and the subagent/`delegate_task` engine whose `subagent.start` / `subagent.complete` events the runs SSE stream forwards (agent-core shard).
- `agent/prompt_builder.py`'s `KANBAN_GUIDANCE` block injected into every kanban worker's system prompt (agent-core shard).
- `auxiliary.*` model configuration (`auxiliary.goal_judge`, `auxiliary.monitor`, `auxiliary.triage_specifier`, `auxiliary.kanban_decomposer`) as config entries (config-* shards).
- `gateway.multiplex_profiles` and the `/p/<profile>/` multiplex machinery in general (gw-core shard).
- The webhook **platform adapter** itself (`gateway/platforms/webhook.py`) — HMAC verification, static routes from `config.yaml`, and the render/deliver pipeline (platforms-* shards).
- `tools/send_message_tool.py` (`prepare_send_message_platforms`, `resolve_send_target`, `_send_to_platform`) which `hermes send` and cron delivery both call (tools shard).
- `hermes gateway` lifecycle commands (`install`, `start`, `stop`, `restart`, `uninstall`) that the cron lifecycle guard blocks from being scheduled (cli-* shards).
- `hermes profile` and the profile store that `bot-chat:<profile>` delivery and peer `/p/<profile>/` targets resolve against (cli-* shards).
- Skills referenced by blueprints (`google-workspace`, `email-inbox-triage`, `weekly-review-planning`, `product-price-monitor`, `competitor-news-monitor`, `sdlc-review`) — their contents (skills-core / optional shards).
- Checkpoints and `/rollback`, whose per-worktree history makes `hermes -w` safe (docs-features shard).
