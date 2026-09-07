# CLI part F — sessions, insights, monitoring, claw, update, uninstall, acp, profile, completion, dashboard, serve, desktop, logs, prompt-size

This shard documents the lifecycle / operations half of the `hermes` CLI at tag v2026.8.31: the whole
`hermes sessions` family (19 sub-commands plus the interactive curses browser), `hermes insights`,
`hermes monitoring status`, the OpenClaw migration commands `hermes claw {migrate,cleanup,clean}`,
`hermes update`, `hermes uninstall`, `hermes acp`, the 13 `hermes profile` sub-commands, `hermes
completion {bash,zsh,fish}`, the two server launchers `hermes dashboard` (+ `dashboard register`) and
`hermes serve`, `hermes desktop`/`hermes gui`, `hermes logs`, and `hermes prompt-size`.
Deliberately left to sibling shards: every other top-level command (chat/gateway/config/auth/cron/
skills/tools/mcp/backup/doctor/peer/…), the web dashboard SPA pages themselves, the Electron
desktop UI, the TUI, tool/toolset catalogues, and the full config-key and env-var catalogues. Where a
command here writes a config key or reads an env var, the key is named but its own catalogue entry
lives in the config/env shards.

---

## 1. `hermes sessions` — the SQLite session store

### Sessions command group  `id: cli-f.sessions`
- **Surface:** CLI
- **Where:** `hermes sessions [-h] {list,export,delete,prune,archive,optimize,clean-markers,optimize-storage,repair,repair-routing,recover,stats,rename,pin,unpin,pinned,retitle-skills,browse,import} ...`
- **What it does:** Umbrella command for viewing and managing the local SQLite session store (`state.db`). With no sub-command it prints its own `--help`.
- **How it works:** Parser built inline in `hermes_cli/main.py:14093-14591` (`sessions_parser = subparsers.add_parser("sessions", help="Manage session history (list, rename, export, prune, delete)", description="View and manage the SQLite session store")`), sub-parsers stored in `dest="sessions_action"`. Dispatch is threaded through `functools`-style closure `_dispatch_sessions` (`hermes_cli/main.py:14601-14604`) which calls `hermes_cli/sessions_cmd.py:124 cmd_sessions(args, sessions_parser=sessions_parser)`. `cmd_sessions` special-cases `repair`, `recover` and `import` BEFORE opening `SessionDB()` (a malformed schema is exactly the case where `SessionDB()` cannot open — `hermes_cli/sessions_cmd.py:126-132`), then opens `from hermes_state import SessionDB; db = SessionDB()` for everything else, and always `db.close()` at the end (`hermes_cli/sessions_cmd.py:1462`). Unknown action → `sessions_parser.print_help()` (`hermes_cli/sessions_cmd.py:1458-1459`).
- **Inputs / options:** `-h, --help`; the 19 sub-commands listed above (each documented separately below).
- **Outputs / side effects:** None by itself except help text; sub-commands read/write `state.db`.
- **Config / env:** `HERMES_HOME` selects the store root (`<home>/state.db`); `sessions.*` config keys govern auto-archive etc.
- **Edge cases / guards:** When `SessionDB()` cannot be opened the command prints `Error: Could not open session database: {e}` and returns exit code 1 (`hermes_cli/sessions_cmd.py:325-330`). Third-party "tool" sessions are hidden by default: `_exclude = None if args.source else ["tool"]` (`hermes_cli/sessions_cmd.py:333-335`).
- **Rebuild notes:** One argparse group over one SQLite file; keep repair/recover/import outside the DB-open path so damaged databases are still serviceable. A better version would expose the same 19 verbs over a stable JSON-RPC surface so GUI/TUI/CLI share one implementation instead of three.

### Shared session filter flags (`--older-than … --max-tool-calls`)  `id: cli-f.sessions.filters`
- **Surface:** CLI
- **Where:** Attached by `_add_session_filter_args(p, default_older_help)` (`hermes_cli/main.py:14114-14209`) to `hermes sessions export`, `hermes sessions prune`, `hermes sessions archive`.
- **What it does:** One shared set of 24 selection flags that pick which sessions a bulk operation touches. The same flags mean the same thing in export, prune and archive; only the `--older-than` help text differs per command.
- **How it works:** Flags land on the argparse namespace and are translated by `hermes_cli/session_filters.py:82 build_prune_filters(args)` into `SessionDB` kwargs (`older_than_days`, `last_active_before`, `last_active_after`, `started_before`, `started_after`, `source`, `title_like`, `end_reason`, `cwd_prefix`, `min_messages`, `max_messages`, `model_like`, `provider`, `user_id`, `chat_id`, `chat_type`, `branch_like`, `min_tokens`, `max_tokens`, `min_cost`, `max_cost`, `min_tool_calls`, `max_tool_calls`). Time values accept durations (`5h`, `30m`, `2d`, `1w`; bare number = DAYS) or ISO timestamps — `parse_duration_seconds` (`hermes_cli/session_filters.py:36-48`, regex `^(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks)$`, unit seconds `{"s":1,"m":60,"h":3600,"d":86400,"w":604800}`) then `parse_point_in_time` (`:51-72`, falls back to `datetime.fromisoformat`, naive = local time). `--older-than`/`--newer-than` bound LAST ACTIVITY; `--before`/`--after` bound SESSION START. `describe_filters()` (`:183-234`) renders the human summary used in previews and confirmation prompts.
- **Inputs / options (all 24, in parser order):**
  1. `--older-than AGE` — upper bound on last activity.
  2. `--newer-than AGE` — "Only match sessions active within the last AGE (e.g. '5h', '2d') or after an ISO timestamp".
  3. `--before TIME` — "Only match sessions started before TIME (duration ago like '5h', or ISO timestamp like '2026-07-05 14:30')".
  4. `--after TIME` — "Only match sessions started at/after TIME (duration ago like '5h', or ISO timestamp)".
  5. `--source SOURCE` — "Only match sessions from this source".
  6. `--title TITLE` — "Only match sessions whose title contains this substring".
  7. `--end-reason END_REASON` — "Only match sessions with this end reason".
  8. `--cwd CWD` — "Only match sessions whose working directory is under this path".
  9. `--min-messages MIN_MESSAGES` (int) — ">= N messages".
  10. `--max-messages MAX_MESSAGES` (int) — "<= N messages".
  11. `--model MODEL` — "Only match sessions whose model name contains this substring (e.g. 'sonnet', 'gpt-5', 'hermes')".
  12. `--provider PROVIDER` — "Only match sessions billed through this provider (e.g. openrouter, anthropic, nous)".
  13. `--user USER` — "Only match sessions from this user ID".
  14. `--chat-id CHAT_ID` — "Only match sessions from this chat/channel ID".
  15. `--chat-type CHAT_TYPE` — "Only match sessions with this chat type (e.g. dm, group)".
  16. `--branch BRANCH` — "Only match sessions whose git branch contains this substring".
  17. `--min-tokens MIN_TOKENS` (int) — ">= N total tokens (input+output)".
  18. `--max-tokens MAX_TOKENS` (int) — "<= N total tokens (input+output)".
  19. `--min-cost MIN_COST` (float) — ">= N USD (actual or estimated)".
  20. `--max-cost MAX_COST` (float) — "<= N USD (actual or estimated)".
  21. `--min-tool-calls MIN_TOOL_CALLS` (int) — ">= N tool calls".
  22. `--max-tool-calls MAX_TOOL_CALLS` (int) — "<= N tool calls".
  23. `--dry-run` — "List matching sessions without changing anything".
  24. `--yes, -y` — "Skip confirmation".
- **Outputs / side effects:** No output on its own; feeds the candidate list of the owning command.
- **Config / env:** n/a
- **Edge cases / guards:** Inverted windows raise a `ValueError` rendered as `Error: Empty start-time window: the --after bound (…) is not earlier than the --before bound (…).` or `Error: Empty activity window: the --newer-than bound (…) is not earlier than the --older-than bound (…).` (`hermes_cli/session_filters.py:131-150`). Unparseable values: `Invalid value for {flag}: '{value}'. Use a duration like '5h', '30m', '2d', '1w', a bare number of days, or an ISO timestamp like '2026-07-05' or '2026-07-05 14:30'.` (`:65-69`). `older_than_days` is forced to `None` in the filter dict so `prune_sessions`' internal 90-day default cannot silently cap an `--after`-only window (`:152-157`).
- **Rebuild notes:** Implement one filter-parsing module shared by every bulk verb; accept both relative durations and ISO, and always print a `describe_filters()` line into confirmation prompts so destructive selections are auditable. Better: expose the same predicate as a saved, named query.

### `hermes sessions list`  `id: cli-f.sessions.list`
- **Surface:** CLI
- **Where:** `hermes sessions list [-h] [--source SOURCE] [--limit LIMIT] [--workspace NEEDLE]`
- **What it does:** Prints a table of recent sessions (title/preview, optional workspace, relative last-active time, source, id).
- **How it works:** `hermes_cli/sessions_cmd.py:329-402`. Calls `db.list_sessions_rich(source=args.source, exclude_sources=_exclude, limit=args.limit)`; `--workspace` post-filters with `hermes_state.workspace_key(s)` — a case-insensitive substring match on the key OR an exact match on its basename (`:337-348`). Column layout is adaptive: the `Workspace` column only appears if `--workspace` was given or at least one row carries a workspace key (`has_ws`), and the `Title` column replaces `Preview` when at least one row has a title (`has_titles`). Four literal header variants: `f"{'Title':<28} {'Workspace':<18} {'Last Active':<13} {'ID'}"` + `"─"*110`; `f"{'Preview':<38} {'Workspace':<18} {'Last Active':<13} {'Src':<6} {'ID'}"` + `"─"*100`; `f"{'Title':<32} {'Preview':<40} {'Last Active':<13} {'ID'}"` + `"─"*110`; `f"{'Preview':<50} {'Last Active':<13} {'Src':<6} {'ID'}"` + `"─"*95`. Titles truncate to 26/30 chars, previews to 36/38/48, workspace label to 16.
- **Inputs / options:** `-h, --help`; `--source SOURCE` ("Filter by source (cli, telegram, discord, etc.)"); `--limit LIMIT` (int, default 20 — `hermes_cli/main.py:14104-14106`); `--workspace NEEDLE` ("Only sessions in one workspace: a git repo root or project dir (matched by path substring or basename).").
- **Outputs / side effects:** Read-only. Prints `No sessions found.` when nothing matches.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Sessions whose source is `tool` are excluded unless `--source` is passed explicitly. Unbound workspaces render as `—`.
- **Rebuild notes:** `SELECT` recent sessions with a rich projection (title, preview, last_active, source, message_count, workspace_key) and render an adaptive table. Better: colourised, paged, and with an inline `--json` mode (this command has none — only `sessions pinned` does).

### `hermes sessions export`  `id: cli-f.sessions.export`
- **Surface:** CLI
- **Where:** `hermes sessions export [output] [--format {jsonl,md,qmd,html,trace}] [--upload] [--public] [--no-redact] [--only {user-prompts}] [--session-id ID] <24 shared filter flags> [--redact] [--lineage {single,logical}] [--delete-after-verified] [--force]`
- **What it does:** Exports one session or a filtered set to JSONL, Markdown, QMD, a self-contained HTML file, or Claude-Code-style trace JSONL (optionally uploaded to a Hugging Face dataset).
- **How it works:** Parser `hermes_cli/main.py:14211-14295`; implementation `hermes_cli/sessions_cmd.py:403-869`. Order of branches: (1) `--only user-prompts` → `hermes_cli.session_export.render_sessions_export(sessions, fmt="markdown"|"jsonl", only=args.only)` + `export_record_count`; (2) `--format html` → `hermes_cli.session_export_html.generate_html_export` for one session or `generate_multi_session_html_export` for many; (3) `--format trace` → `agent.trace_upload.build_trace_jsonl` / `upload_session_trace`; (4) `--format jsonl` → one JSON object per line via `db.export_session` / `db.export_all`; (5) md/qmd → `hermes_cli.session_export_md.write_session_markdown` + `append_manifest_entry`, with `verify_export_file` gating `--delete-after-verified`. Selection: `--session-id` (resolved through `db.resolve_session_id`, accepts unique prefixes) beats filters; filters go through `build_prune_filters` and then `filters["archived"] = None` so — unlike prune/archive — archived sessions ARE included (`:429-431`). `--redact` routes every payload through `session_export_md.redact_session_data`. For `--format trace` redaction is ON by default and `--no-redact` opts out.
- **Inputs / options:** `-h, --help`; positional `output` (optional — "Output path. JSONL: file path (use - for stdout, required). md/qmd: output directory (default: `<hermes home>/session-exports`)"); `--format {jsonl,md,qmd,html,trace}` (default `jsonl`); `--upload`; `--public`; `--no-redact`; `--only {user-prompts}`; `--session-id SESSION_ID`; the 24 shared filter flags (`--older-than`, `--newer-than`, `--before`, `--after`, `--source`, `--title`, `--end-reason`, `--cwd`, `--min-messages`, `--max-messages`, `--model`, `--provider`, `--user`, `--chat-id`, `--chat-type`, `--branch`, `--min-tokens`, `--max-tokens`, `--min-cost`, `--max-cost`, `--min-tool-calls`, `--max-tool-calls`, `--dry-run`, `--yes/-y`); `--redact`; `--lineage {single,logical}` (default `single`, md/qmd only); `--delete-after-verified` (md/qmd only, needs `--yes`); `--force` (md/qmd only).
- **Outputs / side effects:** Writes files (`<output>`, or `<hermes home>/session-exports/…` plus a manifest entry appended by `append_manifest_entry`); with `--upload` posts a trace to a Hugging Face dataset (private by default, `--public` makes it public) and prints the returned status string; with `--delete-after-verified` deletes the exported session and its delegate lineage after `verify_export_file` passes. Messages: `Exported 1 session to {output}`, `Exported {n} sessions to {output}`, `Exported {n} session{s} to {output} (HTML)`, `Exported 1 session trace to {output}`, `Exported {n} session trace(s) to {out_dir}`, `Exported {count} {noun}{s} to {output}`, `Exported 1 session ({n} message{s}) to {path}`, `Exported {n} sessions ({m} message{s}) to {dir}`, `Exported {n} session(s) to {dir}`, `Deleted exported session '{id}'{ and N delegate sessions}.`
- **Config / env:** `HF_TOKEN` (required by `--upload`); `HERMES_HOME` (default export dir).
- **Edge cases / guards:** `--only user-prompts` rejects formats other than jsonl/md: `--only user-prompts supports --format jsonl or md.` HTML with no output path: `HTML export requires an output file path.` JSONL with no output: `JSONL export requires an output path (use - for stdout).` md/qmd to stdout: `Markdown/QMD export writes files; stdout (-) is only supported with --format jsonl.` `--delete-after-verified` without `--yes`: `--delete-after-verified requires --yes.`; without `--session-id`: `--delete-after-verified is only supported with --session-id.` Bulk md/qmd without any filter: `Refusing bulk export without a filter. Pass --session-id or at least one filter (e.g. --older-than 90, --source telegram).` `--dry-run` with no filter: `--dry-run requires at least one filter.` Existing md/qmd file without `--force`: `Export already exists: {e}. Pass --force to overwrite.` (single) / `Skipping existing export: {e}. Pass --force to overwrite.` (bulk). Trace `--upload` without a single session: `--upload exports one session: pass --session-id (or drop filters to use the most recent).` Trace redaction failure: `Redaction failed; refusing to export unredacted trace content.` Unknown id: `Session '{id}' not found.` Dry-run listings cap at 100 rows then print `  ... {n} more`.
- **Rebuild notes:** Separate "select sessions" from "render sessions"; make redaction the default on any path that leaves the machine. A better version would stream large exports instead of materialising every session dict in memory, and would checksum each export into the manifest.

### `hermes sessions delete`  `id: cli-f.sessions.delete`
- **Surface:** CLI
- **Where:** `hermes sessions delete [-h] [--yes] session_id`
- **What it does:** Permanently deletes one session and all its messages.
- **How it works:** `hermes_cli/sessions_cmd.py:870-896`. Resolves prefixes with `db.resolve_session_id`; looks up the row to detect the pin flag; prompts `Delete session '{id}'{ (this session is PINNED)} and all its messages? [y/N] ` unless `--yes`; then `db.delete_session(resolved, sessions_dir=<hermes home>/sessions)`.
- **Inputs / options:** `-h, --help`; positional `session_id` ("Session ID to delete"); `--yes, -y` ("Skip confirmation").
- **Outputs / side effects:** Deletes DB rows and files under `<hermes home>/sessions`. Prints `Deleted session '{id}'.`; `Cancelled.` on a declined prompt; `Session '{id}' not found.` (exit 1) when unresolved.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** A pinned session named explicitly IS deleted, but the prompt says `(this session is PINNED)` and with `--yes` it prints `Warning: deleting a pinned session '{id}'.` (`:884-886`). `_confirm_prompt` treats EOF/KeyboardInterrupt as "no" (`:50-57`).
- **Rebuild notes:** Resolve by unique prefix, warn on keep-flagged rows, delete DB rows + on-disk artefacts in one transaction. Better: soft-delete with a trash window before hard deletion.

### `hermes sessions prune`  `id: cli-f.sessions.prune`
- **Surface:** CLI
- **Where:** `hermes sessions prune [-h] <24 shared filter flags> [--include-archived] [--include-pinned] [--never-active]`
- **What it does:** Bulk-deletes old/ended sessions selected by the shared filters. A bare `hermes sessions prune` with no filter at all means "older than 90 days".
- **How it works:** Parser `hermes_cli/main.py:14298-14344`; implementation shares the `prune`/`archive` branch at `hermes_cli/sessions_cmd.py:903-1058`, with the `--never-active` variant split off into `_prune_never_active_keyed` (`:64-121`). The implicit 90-day default is applied only when `--older-than`, `--newer-than`, `--before`, `--after` are all None AND no non-time filter is set (`:918-934`, `args.older_than = "90"`). `filters["archived"] = None if --include-archived else False`. Pinned rows are excluded unless `--include-pinned`; the difference between `count_prune_matches(include_pinned=True)` and `(…=False)` is reported as a note. `db.count_open_prune_matches(**filters)` reports how many OPEN sessions match but are skipped (prune only deletes ended sessions). Deletion itself: `db.prune_sessions(sessions_dir=<hermes home>/sessions, **filters)`.
- **Inputs / options:** `-h, --help`; the 24 shared filter flags; `--include-archived` ("Also delete archived sessions (excluded by default)"); `--include-pinned` ("Also delete pinned sessions (excluded by default — pin is a keep flag)"); `--never-active` ("Instead of ended sessions, delete keyed gateway rows that were opened and never used (no messages, tokens, tool calls or title) and are older than AGE (default 30 days). Ordinary prune can never reach these — it only ever selects ended sessions").
- **Outputs / side effects:** Deletes rows + session files. Preview block: `{n} session(s) match ({describe_filters}; oldest activity {ts}, newest activity {ts}):` then per-row `  {id}  {last_active:<17} {source:<10} {model:<24} {msgs:>4} msgs  {title}` (title truncated at 36, model at 24, model shown as the last `/`-segment); `  … and {n} more` after 15 rows unless `--dry-run` (which shows all). Confirmation: `{Delete|Archive} these {n} session(s) ({span})? [y/N] `. Final line `Pruned {n} session(s).`
- **Config / env:** `HERMES_HOME`; `sessions.*` config governs the separate auto-archive sweep, not this command.
- **Edge cases / guards:** ANY filter (including `--source`) suppresses the implicit 90-day cutoff, so `prune --source cron` matches all ages. Notes printed when applicable: `Note: {n} pinned session{s} also match these filters but will NOT be deleted (pin is a keep flag). Pass --include-pinned to delete them anyway, or unpin first with `hermes sessions unpin <id>`.` and `Note: {n} open session{s} also match these filters but will be skipped because prune only deletes ended sessions. Use `hermes sessions delete <id>` to remove one explicitly.` `No sessions match ({describe_filters}).` when the candidate list is empty. `Dry run — nothing deleted.` `Cancelled.` on refusal. Filter parse errors return exit code 1.
- **Rebuild notes:** Always preview count + oldest/newest activity before a bulk delete, and never let a filter silently inherit a time default. Better: a two-phase prune (mark then sweep) so an accidental prune is recoverable.

### `hermes sessions prune --never-active`  `id: cli-f.sessions.prune-never-active`
- **Surface:** CLI
- **Where:** `hermes sessions prune --never-active [--older-than AGE] [--dry-run] [--yes]`
- **What it does:** Deletes keyed gateway session rows that were opened and never used — no messages, tokens, tool calls or title — older than a given age (default 30 days).
- **How it works:** `hermes_cli/sessions_cmd.py:64-121`, reached from `:897-901` before the shared prune branch, because "the shared prune/archive selector is pinned to `ended_at IS NOT NULL`, so never-closed rows sit outside it by construction". `_NEVER_ACTIVE_DEFAULT_DAYS = 30.0` (`:61`). `--older-than` is parsed with `parse_duration_seconds` only (no ISO form) and divided by 86400 into days. Candidates come from `db.list_never_active_keyed_sessions(older_than_days=days)`; deletion from `db.prune_never_active_keyed_sessions(older_than_days=days, sessions_dir=<home>/sessions)` which returns `(deleted, routing_deleted)`.
- **Inputs / options:** `--never-active`; `--older-than AGE` (duration or bare days; ISO not accepted here); `--dry-run`; `--yes, -y`. All other shared filters are ignored on this path.
- **Outputs / side effects:** Deletes session rows AND stale routing entries. Prints `{n} never-active keyed session(s) older than {days:g} day(s) — no messages, tokens, tool calls or title:`, per row `  {id}  {started_at:<17} {source:<10} {session_key}`, `  … {n} more` past 15 rows (dry-run shows all), then `Deleted {n} never-active session(s) and {m} stale routing entr(ies).`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** ISO/unparseable `--older-than`: `Error: --older-than '{v}' is not a duration. Use a bare number of days or a form like '2d' / '1w'.` Nothing found: `No never-active keyed sessions older than {days:g} day(s).` Refused prompt: `Aborted.` The population is dominated by escaped test fixtures (issue #82770).
- **Rebuild notes:** Track a separate "never used" predicate outside the ended-session selector, and sweep routing rows alongside session rows. Better: refuse to create such rows in the first place (the code notes the hermetic-isolation guard already prevents new ones).

### `hermes sessions archive`  `id: cli-f.sessions.archive`
- **Surface:** CLI
- **Where:** `hermes sessions archive [-h] <24 shared filter flags>`
- **What it does:** Bulk soft-hides sessions matching the filters. Nothing is deleted; archived sessions disappear from listings but stay fully recoverable.
- **How it works:** Same branch as prune (`hermes_cli/sessions_cmd.py:903-1058`), diverging at `:1048-1057` where it calls `db.archive_sessions(**filters)` instead of `prune_sessions`. `filters["archived"] = False` always (idempotent — only not-yet-archived rows are targeted). Pinned rows are always spared; there is no `--include-pinned` on archive. Archive expands each selected row to its compression lineage, which can include open continuations, so the "open sessions skipped" note is suppressed (`skipped_open` is computed only for prune, `:995-997`).
- **Inputs / options:** `-h, --help`; the 24 shared filter flags. No `--include-archived`, no `--include-pinned`, no `--never-active`.
- **Outputs / side effects:** Sets the archived flag on matching rows. Prints the same preview/confirmation block as prune with the verb `Archive`, then `Archived {n} session(s). They're hidden from listings but fully recoverable (nothing was deleted).`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Refuses a filterless run: `Refusing to archive every ended session: pass at least one filter (e.g. --newer-than 5h, --source cli, --title codex).` (`:942-950`). Pinned note wording differs from prune: `… will NOT be archived (pin is a keep flag). Unpin first with `hermes sessions unpin <id>` to include them.` `Dry run — nothing archived.`
- **Rebuild notes:** Reuse the prune selector but change only the terminal operation; refuse an unfiltered archive. Better: an `unarchive` counterpart on the same filter grammar (currently only prune's `--include-archived` acknowledges the flag exists).

### `hermes sessions optimize`  `id: cli-f.sessions.optimize`
- **Surface:** CLI
- **Where:** `hermes sessions optimize [-h]`
- **What it does:** Reclaims disk space in `state.db` by merging FTS5 index segments and running VACUUM. No conversation data changes.
- **How it works:** `hermes_cli/sessions_cmd.py:1237-1271`. Measures `os.path.getsize(db.db_path)` before, prints `Optimizing session store (FTS merge + VACUUM)…`, calls `db.vacuum()` (which runs `optimize_fts` then VACUUM and returns the number of merged indexes), measures after, then PREFERS SQLite's own page accounting via `db.logical_size_bytes()` over `stat()` because in WAL mode the VACUUM rewrite sits in the `-wal` file until a checkpoint (refused while a live gateway holds a read-mark) and `stat()` can report a negative saving.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** Rewrites the database file. Prints `Optimized {n} FTS index(es).` and `Database size: {before:.1f} MB -> {after:.1f} MB ({_size_delta_label(saved)})`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** On exception prints `Error: optimization failed: {e}` and closes the DB.
- **Rebuild notes:** `INSERT INTO <fts>(<fts>) VALUES('optimize')` then `VACUUM`, and report size from `page_count * page_size`, not `stat()`. Better: run incrementally in the background so a live gateway never blocks it.

### `hermes sessions clean-markers`  `id: cli-f.sessions.clean-markers`
- **Surface:** CLI
- **Where:** `hermes sessions clean-markers [-h] [--dry-run] [--no-backup]`
- **What it does:** Permanently clears stale bracketed tool-call marker content (e.g. `[memory]`) that pre-#78148 sessions persisted as an assistant turn's content instead of real text.
- **How it works:** `hermes_cli/sessions_cmd.py:1272-1291` calling `db.purge_stale_tool_call_markers(dry_run=args.dry_run, backup=not args.no_backup)`. The report dict has `rows_affected`, `row_ids`, `backup_path`. Only the `content` column is touched; `tool_calls` and every other column are left untouched. This is optional — the same repair already happens in memory on every session load; running it once stops long-lived sessions re-scanning the same rows on every resume.
- **Inputs / options:** `-h, --help`; `--dry-run` ("Report the affected row count without writing"); `--no-backup` ("Skip the timestamped state.db backup taken before writing (not recommended)").
- **Outputs / side effects:** Rewrites affected `content` cells; writes a timestamped `state.db` backup first unless `--no-backup`. Prints `Dry run — scanning for stale tool-call marker rows (#78148)…` or `Scanning for stale tool-call marker rows (#78148)…`, then one of `✓ No affected rows found — nothing to clean.`, `Would clear {n} row(s): ids {row_ids}`, or `  backup: {path}` + `✓ Cleared {n} row(s).`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Idempotent; safe to skip entirely.
- **Rebuild notes:** A one-shot data migration guarded by a dry-run and an automatic backup. Better: fold it into the schema-version migration ladder so it runs once automatically.

### `hermes sessions optimize-storage`  `id: cli-f.sessions.optimize-storage`
- **Surface:** CLI
- **Where:** `hermes sessions optimize-storage [-h] [--no-vacuum] [--yes]`
- **What it does:** Rebuilds the full-text search index into the compact v23 external-content layout, reclaiming a large fraction of `state.db` on big databases, then VACUUMs.
- **How it works:** `hermes_cli/sessions_cmd.py:1292-1391`. Guard: `db.fts_optimize_available()` — if False prints `Search index is already on the compact layout — nothing to do.` Disk preflight computes `need_bytes = before_bytes` when vacuuming or `int(before_bytes * 0.3)` with `--no-vacuum`, compares against `shutil.disk_usage(db_path.parent).free`. Runs `db.optimize_fts_storage(progress_cb=_progress, vacuum=do_vacuum)`; the progress callback renders phases `backfill` (`  Rebuilding index: {pct:3d}% ({indexed:,}/{total:,})`), `teardown` → `Reclaiming old index…`, `vacuum` → `Compacting database (VACUUM)…`, `done` → `Done…`. Final size uses `db.logical_size_bytes()` for the same WAL reason as `optimize` (the comment records a real "reclaimed -3820.1 MB" misreport). Resumable: safe to Ctrl-C and re-run.
- **Inputs / options:** `-h, --help`; `--no-vacuum` ("Skip the final VACUUM (index is rebuilt but freed pages aren't returned to the OS until a later VACUUM)"); `--yes, -y` ("Skip the disk-space confirmation prompt").
- **Outputs / side effects:** Rebuilds the FTS index in place and (by default) VACUUMs. Prints `Search-index optimization for {db_path}`, `  Current database size: {mb:.1f} MB`, `  Free disk: {mb:.0f} MB (need ~{mb:.0f} MB to complete[ incl. VACUUM])`, optionally `  This may take a while on a large database. It runs in the foreground with progress below; safe to Ctrl-C and re-run (it resumes).` (only when the DB is > 500 MB), the prompt `Proceed? [y/N] `, then `Optimizing search-index storage…`, `✓ Search index optimized.`, `  Database size: {before} MB -> {after} MB ({delta})`, and if VACUUM was skipped `  (VACUUM was skipped or failed — run `hermes sessions optimize` later to reclaim freed space.)`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Insufficient disk aborts with `⚠ Not enough free disk to complete safely. Free up space, or run with --no-vacuum (rebuilds the index but doesn't reclaim space until a later VACUUM).` Failure prints `Error: optimization failed: {e}` + `No data was lost. Re-run to resume.` A non-ok result prints `Could not optimize: {reason}`. Declining the prompt prints `Cancelled.` No conversation data is changed — only the index.
- **Rebuild notes:** Migrate an FTS5 contentless/duplicated index to `content=` external-content, backfilling in throttled batches with a resumable cursor, then VACUUM. Better: perform it online during idle gateway time rather than as a foreground chore.

### `hermes sessions repair`  `id: cli-f.sessions.repair`
- **Surface:** CLI
- **Where:** `hermes sessions repair [-h] [--check-only] [--no-backup]`
- **What it does:** Repairs a `state.db` whose SCHEMA is malformed (e.g. `table messages_fts already exists`), the failure that makes Desktop/Dashboard show no sessions at all.
- **How it works:** `hermes_cli/sessions_cmd.py:133-191`, deliberately BEFORE `SessionDB()` is opened. Uses `hermes_state.DEFAULT_DB_PATH`, `_db_opens_cleanly(db_path)` (returns a reason string or None), and `repair_state_db_schema(db_path, backup=not --no-backup)` returning `{repaired, backup_path, strategy, error}`. After a successful repair it re-opens `SessionDB()` and counts `SELECT COUNT(*) FROM sessions`.
- **Inputs / options:** `-h, --help`; `--check-only` ("Only report whether the database opens cleanly; do not modify it"); `--no-backup` ("Skip the timestamped backup copy (not recommended)").
- **Outputs / side effects:** May rewrite the schema and rebuild the FTS index; writes a timestamped backup first by default. Messages: `No session database at {path} (nothing to repair).`; `✓ {path} opens cleanly — no repair needed.`; `✗ {path} does not open cleanly: {reason}`; `Repairing (a backup copy is made first)…`; `  backup: {path}`; `  strategy: {strategy}`; `✓ Repaired — {n} sessions recovered.` or `✓ Repaired.`
- **Config / env:** `HERMES_HOME` (via `DEFAULT_DB_PATH`).
- **Edge cases / guards:** On failure it prints `✗ Repair failed: {error}`, `  A backup is preserved at: {path}`, `  Keep state.db and the backup; do not delete them.` and then hands the user the offline-recovery escape hatch verbatim: `  Next step — offline recovery (never modifies the source):` / `    hermes sessions recover --source {source_hint} \` / `        --inspect-only` / `  If that reports the data is recoverable, rebuild it into` / `  a NEW database (the active one is left untouched):` / `    hermes sessions recover --source {source_hint} \` / `        --output recovered-state.db`.
- **Rebuild notes:** Detect "malformed schema" by trying to open, back up, then rebuild derived objects while preserving canonical tables. Better: never let the FTS trigger set get into that state (versioned migrations with a transactional guard).

### `hermes sessions repair-routing`  `id: cli-f.sessions.repair-routing`
- **Surface:** CLI
- **Where:** `hermes sessions repair-routing [-h] [--apply] [--max-gap-seconds MAX_GAP_SECONDS]`
- **What it does:** Finds gateway conversations stranded in session rows whose routing identity (`session_key`/`chat_id`/`origin`) was never written (issue #82616) and re-stamps each orphan from the keyed predecessor it continues.
- **How it works:** `hermes_cli/sessions_cmd.py:1392-1437`. `db.find_orphaned_gateway_sessions(max_gap_s=args.max_gap_seconds)` returns records with `orphan_id`, `source`, `message_count`, `adoptable`, `session_key`, `donor_id`, `evidence`, `reason`. Adoption is performed only for unambiguous predecessors and only with `--apply`, after an interactive confirmation. Adoption itself: `db.adopt_orphaned_gateway_session(record["orphan_id"], record["donor_id"])`.
- **Inputs / options:** `-h, --help`; `--apply` ("Perform the adoptions (default: report only)"); `--max-gap-seconds MAX_GAP_SECONDS` (float, default None → the DB layer's 900 s — "Window between a keyed predecessor's last activity and an orphan's start for them to count as the same conversation (default: 900)").
- **Outputs / side effects:** With `--apply` and a `y` answer, rewrites routing identity columns. Prints per record `{orphan_id}  ({source}, {n} messages)` then either `  → adopt into {session_key} (from {donor_id}, evidence: {evidence})` or `  ✗ not repairable — {reason}`; summaries `✓ No gateway sessions are missing their routing identity.`, `{n} orphaned session(s) found, none unambiguously repairable. Nothing to do.`, `{k} of {n} orphaned session(s) can be repaired. Re-run with --apply to perform them.`; apply-mode `Stop the gateway before applying — a running gateway still holds the old routing mapping in memory.`, prompt `Adopt {k} orphaned session(s)? [y/N] `, per-row `✓ {orphan_id} now owns {session_key}` or `✗ {orphan_id} was not adopted (the row changed since it was reported)`, and `Repaired {r} of {k} session(s).`; `Aborted — nothing was changed.` on refusal.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Explicitly warns to stop the gateway first — a running gateway holds the old mapping in memory and would write it back. Adoption is skipped when the row changed since it was reported (optimistic concurrency).
- **Rebuild notes:** Detect rows with NULL routing identity, match them to the nearest preceding keyed row within a gap window, and adopt only unambiguous matches. Better: make the routing write part of the same transaction as the session insert so orphans cannot occur.

### `hermes sessions recover`  `id: cli-f.sessions.recover`
- **Surface:** CLI
- **Where:** `hermes sessions recover [-h] --source SOURCE [--output OUTPUT] [--inspect-only] [--work-dir WORK_DIR] [--chunk-size CHUNK_SIZE] [--allow-partial] [--report REPORT]`
- **What it does:** Offline, non-destructive recovery of a damaged `state.db`: rebuilds canonical rows into a NEW database, never replacing the active one.
- **How it works:** `hermes_cli/sessions_cmd.py:192-304`, again before `SessionDB()` is opened. Delegates to `hermes_cli/session_recovery.py`: `inspect_session_database(source, work_dir=…)`, `recover_session_database(source, output, work_dir=…, chunk_size=…, progress_cb=…, allow_partial=…)`, `write_recovery_report(path, report)`. The source DB and its WAL/SHM/rollback-journal sidecars are copied before SQLite opens anything. Derived search indexes are recreated in the output. Progress prints `  {table}: {copied:,}/{total:,}` in place per table.
- **Inputs / options:** `-h, --help`; `--source SOURCE` (Path, REQUIRED — "Source state.db or preserved backup to inspect/recover"); `--output OUTPUT` (Path — "New recovery database path (required unless --inspect-only)"); `--inspect-only`; `--work-dir WORK_DIR` (Path — "Existing directory for the disposable source copy (defaults beside the output)"); `--chunk-size CHUNK_SIZE` (int, default 1000 — "Rows committed per recovery batch"); `--allow-partial` ("Best-effort salvage across damaged row ranges; the output remains separate and every skipped range is recorded"); `--report REPORT` (Path — "JSON report path (defaults to `<output>.recovery.json`)").
- **Outputs / side effects:** Creates the output database and a JSON report file (or prints the report JSON to stdout with `--inspect-only` and no `--report`). Prints `Recovering canonical session data into a new database…`, `Recovery report: {path}`, and one of `✓ Recovered database verified at: {output}` + `  The active session database was not changed.` + `  Review the JSON report before installing this database.`; `✓ BEST-EFFORT page-level salvage verified at: {output}` + `  The source table schemas were unreadable; rows were rebuilt from raw pages via sqlite3 .recover and mapped heuristically.`; `✓ Partial recovery output verified at: {output}`; `  Recovered {n:,} sessions and {m:,} messages.`; `  This output is incomplete. Review every skipped range and orphan count in the JSON report before installing it.`; `✗ Recovery output did not pass every verification check.` + `  Do not install it. Review the JSON report for partial data or errors.`
- **Config / env:** n/a (works on explicit paths).
- **Edge cases / guards:** Argument conflicts return exit code 2: `Error: --output cannot be used with --inspect-only.`, `Error: --allow-partial cannot be used with --inspect-only.`, `Error: --output is required unless --inspect-only is used.` Refuses to clobber a report: `Error: refusing to overwrite existing report: {path}` (exit 2). Failures return 1 with `Error: session recovery failed: {exc}` + `The supplied source database was not replaced or deleted.` and `Error: could not write recovery report: {exc}`. `--inspect-only` exit code is 0 when `report["recoverable"]` else 1.
- **Rebuild notes:** Copy source + sidecars to a scratch dir, read canonical tables in chunked transactions into a fresh schema, rebuild derived indexes, verify counts, write a machine-readable report, and never touch the original. Better: offer an atomic "install this recovery" step with a rollback.

### `hermes sessions stats`  `id: cli-f.sessions.stats`
- **Surface:** CLI
- **Where:** `hermes sessions stats [-h]`
- **What it does:** Prints session-store statistics: total sessions, total messages, per-source counts, and the database file size.
- **How it works:** `hermes_cli/sessions_cmd.py:1438-1450`. `db.session_count()`, `db.message_count()`, then `db.session_count(source=src)` for the fixed list `["cli", "telegram", "discord", "whatsapp", "slack"]` (only non-zero sources are printed), then `os.path.getsize(db.db_path) / (1024*1024)`.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** Read-only. Prints `Total sessions: {n}`, `Total messages: {m}`, `  {src}: {c} sessions` per non-zero source, `Database size: {mb:.1f} MB`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** The per-source list is hardcoded to five platforms — sessions from other sources (e.g. `cron`, `tool`, `api`) are counted in the total but never itemised.
- **Rebuild notes:** Trivial aggregate query. Better: derive the source list from `SELECT DISTINCT source` instead of a hardcoded five, and add token/cost totals.

### `hermes sessions rename`  `id: cli-f.sessions.rename`
- **Surface:** CLI
- **Where:** `hermes sessions rename [-h] session_id title [title ...]`
- **What it does:** Sets or changes a session's title. The title may be typed unquoted as multiple words.
- **How it works:** `hermes_cli/sessions_cmd.py:1059-1092`. `args.title` is `nargs="+"` and joined with `" ".join(args.title)`. Length validation happens inside `db.set_session_title`; emptiness and newline guards are enforced in the CLI.
- **Inputs / options:** `-h, --help`; positional `session_id` ("Session ID to rename"); positional `title` (`nargs="+"`, "New title for the session").
- **Outputs / side effects:** Updates the title column. Prints `Session '{resolved}' renamed to: {title}`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `Session '{id}' not found.` → exit 1. `Error: title cannot be empty or whitespace-only.` → exit 1. `Error: title cannot contain newlines.` (rejects both `\n` and `\r`) → exit 1. A `ValueError` from `set_session_title` (e.g. length or unique-title collision) prints `Error: {e}` → exit 1.
- **Rebuild notes:** Join `nargs="+"` tokens, reject blank/control-char titles, enforce a length cap in the store. Better: allow a `--generate` mode that re-runs the auto-titler.

### `hermes sessions pin`  `id: cli-f.sessions.pin`
- **Surface:** CLI
- **Where:** `hermes sessions pin [-h] session_ids [session_ids ...]`
- **What it does:** Sets the durable "keep" flag on one or more sessions. Pinned sessions are exempt from the `sessions.auto_archive` stale sweep and always appear in listings; the same flag drives the Desktop sidebar's Pinned section.
- **How it works:** `hermes_cli/sessions_cmd.py:1092-1111` (shared `pin`/`unpin` branch). For each raw id: `db.resolve_session_id(raw_id)` (unique prefixes accepted) then `db.set_session_pinned(resolved, True)`, and `db.get_session_title(resolved)` for the confirmation suffix. Introduced by issue #52955; the code comment cites Perplexity Computer's cross-surface pin/archive as the inspiration and states "pin state is operational infrastructure, so every surface — GUI, TUI, CLI, scripts — needs read/write access to the same store".
- **Inputs / options:** `-h, --help`; positional `session_ids` (`nargs="+"`, "Session ID(s) or unique prefix(es) to pin").
- **Outputs / side effects:** Sets the pinned column. Prints `Pinned session '{resolved}'.  ({title})` per success.
- **Config / env:** `sessions.auto_archive` (pinned rows are exempt from that sweep).
- **Edge cases / guards:** Unresolvable ids print `Session '{raw}' not found.` and the command exits 1 if ANY id failed, after processing the rest.
- **Rebuild notes:** A boolean column plus a shared resolver that accepts prefixes. Better: pin with an optional reason/expiry.

### `hermes sessions unpin`  `id: cli-f.sessions.unpin`
- **Surface:** CLI
- **Where:** `hermes sessions unpin [-h] session_ids [session_ids ...]`
- **What it does:** Removes the pin (durable keep flag) from one or more sessions.
- **How it works:** Same branch as pin (`hermes_cli/sessions_cmd.py:1092-1111`) with `pinning = False`, so `db.set_session_pinned(resolved, False)`.
- **Inputs / options:** `-h, --help`; positional `session_ids` (`nargs="+"`, "Session ID(s) or unique prefix(es) to unpin").
- **Outputs / side effects:** Clears the pinned column. Prints `Unpinned session '{resolved}'.  ({title})`.
- **Config / env:** `sessions.auto_archive`.
- **Edge cases / guards:** Identical to pin — `Session '{raw}' not found.` per failure, exit 1 if any failed.
- **Rebuild notes:** As pin, inverted.

### `hermes sessions pinned`  `id: cli-f.sessions.pinned`
- **Surface:** CLI
- **Where:** `hermes sessions pinned [-h] [--json]`
- **What it does:** Lists every pinned conversation regardless of age, as a table or machine-readable JSON.
- **How it works:** `hermes_cli/sessions_cmd.py:1112-1147`. Calls `db.list_sessions_rich(limit=1, include_pinned=True, exclude_sources=_exclude)` — `limit=1` keeps the recency page minimal while `include_pinned=True` back-fills ALL pinned rows the page missed (bounded by the pin count), so old pins cannot fall off a paging window. Filters the result to rows where `s["pinned"]`.
- **Inputs / options:** `-h, --help`; `--json` ("Emit machine-readable JSON (for backup/restore scripting)").
- **Outputs / side effects:** Read-only. Table header `f"{'Title':<32} {'Last Active':<13} {'Src':<9} {'ID'}"` + `"─"*100`; rows use title, else preview, else `—`, truncated to 30. `--json` prints an indented array of `{"id","title","source","last_active","message_count"}`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Empty: `No pinned sessions. Pin one with: hermes sessions pin <session_id>`. `tool` sessions are excluded unless `--source` was set (this command has no `--source`, so they are always excluded).
- **Rebuild notes:** Query by the pin flag with no time bound and offer JSON for scripting. Better: include the pin timestamp and who pinned it.

### `hermes sessions retitle-skills`  `id: cli-f.sessions.retitle-skills`
- **Surface:** CLI
- **Where:** `hermes sessions retitle-skills [-h] [--apply] [--limit LIMIT]`
- **What it does:** Re-titles sessions whose auto-title was generated from an expanded `/skill` body (so the title described the SKILL, not the user's request) using what the user actually typed.
- **How it works:** `hermes_cli/sessions_cmd.py:1148-1207`. Candidates from `db.list_skill_scaffolded_sessions(limit=limit)`; the typed text is recovered with `agent.skill_commands.describe_skill_invocation(row["content"])` and re-titled with `agent.title_generator.generate_title(typed)`. A local `_is_titlelike(candidate)` guard rejects a candidate whose first character is not alphanumeric — the auxiliary model occasionally echoes command output (`$ df -h /`) instead of a title, and since this is a REPAIR, keeping the old title is better. Writes with `db.set_session_title`; on a unique-title `ValueError` it dedupes exactly like the live auto-titler using `db.get_next_title_in_lineage(new_title)` (base #2, base #3, …).
- **Inputs / options:** `-h, --help`; `--apply` ("Write the new titles (default: dry run)"); `--limit LIMIT` (int, default 200, floored at 1 — "Maximum sessions to examine").
- **Outputs / side effects:** With `--apply`, rewrites titles. Prints `{n} session(s) opened with a /skill[ (dry run — pass --apply to write)]:`, per change `  {session_id}` / `    {old!r}` / `    → {new!r}`, per rejected candidate `  {session_id}` / `    kept {old!r} — got {new!r}`, dedupe note `    (renamed to {deduped!r} — title was taken)`, skip note `    skipped: {e}`, and finally `  every title already reflects the user's request.` or `✓ Re-titled {n} session(s).`
- **Config / env:** The auxiliary-LLM config used by `agent.title_generator`.
- **Edge cases / guards:** No candidates: `No sessions were titled from a /skill invocation.` A failed dedupe decrements the changed counter so the summary stays honest.
- **Rebuild notes:** Store the raw user text alongside the expanded prompt so titles never need repairing; until then, regenerate from the recovered text and refuse non-title-shaped answers. Better: keep an `title_source` column so this sweep can be targeted exactly.

### `hermes sessions browse`  `id: cli-f.sessions.browse`
- **Surface:** CLI
- **Where:** `hermes sessions browse [-h] [--source SOURCE] [--limit LIMIT]`
- **What it does:** Opens the interactive session picker; selecting a row re-execs `hermes --resume <id>` in place.
- **How it works:** `hermes_cli/sessions_cmd.py:1208-1236`. Loads `db.list_sessions_rich(source=source, exclude_sources=(None if source else ["tool"]), limit=limit)`, keeps the DB OPEN (the picker needs it for lifecycle status tags and the `d` delete action), calls `_session_browse_picker(sessions, session_db=db)` (`hermes_cli/main.py:1281`), closes the DB in a `finally`, then prints `Resuming session: {id}` and calls `hermes_cli.relaunch.relaunch(["--resume", selected_id])`, which replaces the process (execvp) and never returns.
- **Inputs / options:** `-h, --help`; `--source SOURCE` ("Filter by source (cli, telegram, discord, etc.)"); `--limit LIMIT` (int, default 500 — "Max sessions to load").
- **Outputs / side effects:** Replaces the current process with a resumed chat session; can delete a session from inside the picker. Prints `No sessions found.` or `Cancelled.`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** See the picker entry below for the curses/fallback split.
- **Rebuild notes:** Load rows once, hand them to a TUI picker with a live DB handle, then exec the resume command so the picker's process does not linger. Better: fuzzy scoring instead of substring match, and preview-on-hover of the last few turns.

### Interactive session browser (curses picker)  `id: cli-f.sessions.browse-picker`
- **Surface:** CLI
- **Where:** Full-screen curses UI shown by `hermes sessions browse` (and reused by other resume paths). Header line: `  Browse sessions — ↑↓ navigate  Enter select  Type to filter  Esc quit`; while filtering: `  Browse sessions — filter: {text}█`.
- **What it does:** Lets the user scroll/search a list of sessions, see each one's lifecycle status and message count, delete a row, and pick one to resume.
- **How it works:** `hermes_cli/main.py:1281-1596` (`_session_browse_picker`). Statuses are annotated first by `_annotate_session_statuses(sessions, session_db)` and rendered by `_session_status_tag(status)`. Layout constant `_FIXED_COLS = 3 + 5 + 2 + 5 + 2 + 12 + 6 + 18 + 6`; the name column is `max(20, max_x - _FIXED_COLS)` wide. Row format: `f"{name:<{name_width}}  {status:<5}  {msgs_str:>5}  {last_active:<10}  {source:<5} {sid}"` where `sid = s["id"][:18]`, `source = s.get("source","")[:6]`, `last_active = _relative_time(...)`, and name = title, else preview, else the id. Column header: `f"   {'Title / Preview':<{name_width}}  {'Stat':<5}  {'Msgs':>5}  {'Active':<10}  {'Src':<5} {'ID'}"`. Colour pairs: 1 green (selected), 2 yellow (header), 3 cyan (search), 4 dim/grey-8 (dim), 5 red (error/delete); status→colour map `{"complete": green, "interrupted": yellow, "error": red, "empty": dim}`. Search matching `_match(s, query)` is case-insensitive across title, preview, id and source. Deletion goes through `_delete_session(session_id)` → `session_db.delete_session(session_id, sessions_dir=<home>/sessions)`.
- **Inputs / options (every key):**
  - `↑` (`curses.KEY_UP`) — move cursor up, wrapping (`(cursor - 1) % len(filtered)`).
  - `↓` (`curses.KEY_DOWN`) — move cursor down, wrapping.
  - `Enter` (`KEY_ENTER`, 10, 13) — select the highlighted session and return its id.
  - `Esc` (27) — first press clears an active search filter; second press exits with no selection.
  - `Backspace` (`KEY_BACKSPACE`, 127, 8) — delete the last character of the search filter.
  - `q` — quit, but ONLY while the search filter is empty (otherwise it types `q`).
  - `d` — delete the highlighted session, but ONLY while the search filter is empty AND a live `session_db` was passed; enters a y/N confirmation mode.
  - `y` / `Y` — confirm a pending delete. Any other key cancels it.
  - Any printable character (ASCII 32–126) — appended to the live search filter, which re-filters and resets cursor/scroll to 0.
  - Fallback (non-curses) prompt: `  Select [1-{n}]: ` accepting a number, or `q` / `quit` / `exit` / empty to cancel.
- **Outputs / side effects:** Returns a session id (or None). `d` + `y` permanently deletes a session and its files; the row disappears from the list and the footer flashes `Deleted.` or `Delete failed.` If the last session is deleted the picker exits.
- **Config / env:** `HERMES_HOME` (for `sessions_dir`).
- **Edge cases / guards:** Terminal smaller than 5 rows × 40 cols prints `Terminal too small`, waits for one key and returns. Every `stdscr.addstr/addnstr` is wrapped in `try/except curses.error`. If curses raises at any point, the whole block falls through to a numbered-list fallback (`  Browse sessions  (enter number to resume, q to cancel)`) which shows the same status/message-count columns but has NO delete support; the label truncates at 50 chars with `...`. Invalid input in the fallback prints `  Invalid selection. Enter 1-{n} or q to cancel.` or `  Invalid input. Enter a number or q to cancel.`; Ctrl-C/EOF returns None. Footer variants: `  {i}/{n} sessions`, `  {i}/{n} sessions (filtered from {total})`, `  0/{n} sessions`, plus `   d delete` appended when deletion is available; delete confirmation footer `  Delete session '{label}'? [y/N]` with the label truncated to 37 chars + `...`.
- **Rebuild notes:** A single-screen curses loop over an in-memory list with incremental substring filtering, a fixed-width row formatter that reserves a flexible name column, and a modal y/N confirmation for the destructive key. Better: fuzzy ranking, multi-select, and an undo buffer for deletes.

### `hermes sessions import`  `id: cli-f.sessions.import`
- **Surface:** CLI
- **Where:** `hermes sessions import [-h] [--from {claude,codex}] [path]`
- **What it does:** Pulls a conversation started in Claude Code (`~/.claude/projects`) or Codex CLI (`~/.codex/sessions`) into the Hermes session store so it can be resumed with `hermes --resume <id>`. The foreign files are only read, never modified.
- **How it works:** Parser `hermes_cli/main.py:14573-14592`; dispatch `hermes_cli/sessions_cmd.py:305-320` → `hermes_cli.foreign_sessions.run_sessions_import(args)`, executed BEFORE `SessionDB()` is opened.
- **Inputs / options:** `-h, --help`; `--from {claude,codex}` (dest `from_source`; default None = "pick across both"); positional `path` (optional — "Path to a specific session JSONL file (skips the picker)").
- **Outputs / side effects:** Inserts a session (and its messages) into `state.db`; prints whatever `run_sessions_import` reports.
- **Config / env:** `HERMES_HOME` (destination); reads `~/.claude/projects` and `~/.codex/sessions`.
- **Edge cases / guards:** If an explicit `path` was given and nothing was imported (bad path, unknown source, no turns), the command returns exit code 1 so scripts can detect it (SES-04/SES-10); cancelling the interactive picker with no path returns None and exits 0 (`hermes_cli/sessions_cmd.py:313-320`).
- **Rebuild notes:** Parse foreign JSONL transcripts into the native message schema and never write to the source tree. Better: a two-way sync with provenance so an imported session can be re-exported to its origin format.

---

## 2. `hermes insights` and `hermes monitoring`

### `hermes insights`  `id: cli-f.insights`
- **Surface:** CLI
- **Where:** `hermes insights [-h] [--days DAYS] [--source SOURCE]` — description "Analyze session history to show token usage, costs, tool patterns, and activity trends"; top-level help entry "Show usage insights and analytics".
- **What it does:** Analyses the local session history and prints a terminal report of token usage, costs, tool-call patterns and activity trends over a rolling window.
- **How it works:** Parser `hermes_cli/subcommands/insights.py:12-25`. Handler `hermes_cli/main.py:12956-12974 cmd_insights`: opens `hermes_state.SessionDB()`, builds `agent.insights.InsightsEngine(db)`, calls `engine.generate(days=args.days, source=args.source)` and prints `engine.format_terminal(report)`. The DB is always closed in a `finally`.
- **Inputs / options:** `-h, --help`; `--days DAYS` (int, default 30 — "Number of days to analyze"); `--source SOURCE` ("Filter by platform (cli, telegram, discord, etc.)").
- **Outputs / side effects:** Read-only; prints the rendered report to stdout.
- **Config / env:** `HERMES_HOME` (session store location); pricing tables used by the insights engine come from the model catalogue.
- **Edge cases / guards:** Any exception is swallowed into `Error generating insights: {e}` — the command never raises; the DB close is also exception-guarded.
- **Rebuild notes:** Aggregate over the session/message tables grouped by day, tool name, model and provider; render as a fixed-width terminal report. Better: add `--json`, `--since/--until`, and per-project (workspace) grouping.

### `hermes monitoring`  `id: cli-f.monitoring`
- **Surface:** CLI
- **Where:** `hermes monitoring [-h] {status} ...` — top-level help "Inspect gateway monitoring (health & diagnostics export)".
- **What it does:** Umbrella for gateway monitoring inspection. Its description states the contract: "Gateway monitoring: service health metrics plus redacted diagnostics, exported over OTLP to an operator-configured endpoint. Content-free by construction — no prompts, messages, tool args/results, or usage analytics. Configure under monitoring.* in config.yaml."
- **How it works:** Parser `hermes_cli/subcommands/monitoring.py:16-36` with sub-parser dest `monitoring_action`; handler `hermes_cli/main.py:12976-13021 cmd_monitoring`, which defaults the action to `status` when none is given.
- **Inputs / options:** `-h, --help`; sub-command `status`.
- **Outputs / side effects:** Read-only.
- **Config / env:** `monitoring.*` in `config.yaml`.
- **Edge cases / guards:** Any action other than `status` prints `Unknown monitoring action: {action}` to stderr and exits 2.
- **Rebuild notes:** Keep the content-free guarantee structural (never route rendered messages into the exporter) rather than configurable. Better: add `monitoring test` that emits one synthetic span/metric to prove the endpoint works.

### `hermes monitoring status`  `id: cli-f.monitoring.status`
- **Surface:** CLI
- **Where:** `hermes monitoring status [-h]` — help "Show monitoring settings, export state, and redaction posture".
- **What it does:** Prints whether the gateway health & diagnostics export is enabled, at what intervals, where it points, whether the OpenTelemetry SDK is installed, and restates the redaction scope.
- **How it works:** `hermes_cli/main.py:12984-13018`. Reads `load_config()["monitoring"]`, then `monitoring.gateway_health_export` (`enabled`, `metrics_enabled` default True, `export_interval_seconds` default 60, `diagnostic_events_enabled` default True, `warning_error_events_enabled` default True, `logs_export_interval_seconds` default 5) and `monitoring.export.otlp` (`enabled`, `endpoint`). SDK presence via `agent.monitoring.otlp_exporter.is_available()`.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** Read-only. Exact output lines: `Gateway monitoring`; `  Health export:  {enabled|disabled} (monitoring.gateway_health_export.enabled)`; when enabled `    Metrics:            {on|off} (interval {n}s)`, `    Diagnostic events:  {on|off}`, `    Warning/error logs: {on|off} (interval {n}s)`, `    Content safety:     always on (rendered messages are never exported; not configurable)`; then `  OTLP endpoint:  {endpoint}` or `  OTLP endpoint:  not configured (monitoring.export.otlp)`; `  OTel SDK:       {installed|not installed} (optional extra: hermes-agent[otlp])`; a blank line, then `  Scope: gateway service health + redacted diagnostics only.` and `  No prompts, messages, tool args/results, usage analytics, or traces.`
- **Config / env:** `monitoring.gateway_health_export.enabled`, `monitoring.gateway_health_export.metrics_enabled`, `monitoring.gateway_health_export.export_interval_seconds`, `monitoring.gateway_health_export.diagnostic_events_enabled`, `monitoring.gateway_health_export.warning_error_events_enabled`, `monitoring.gateway_health_export.logs_export_interval_seconds`, `monitoring.export.otlp.enabled`, `monitoring.export.otlp.endpoint`. Optional pip extra `hermes-agent[otlp]`.
- **Edge cases / guards:** Non-dict config values are coerced to `{}` before use so a malformed `config.yaml` cannot crash the status view. The OTLP endpoint is only reported as configured when BOTH `enabled` and a non-empty `endpoint` are present.
- **Rebuild notes:** Print effective values with their dotted config key next to each, and state non-configurable guarantees explicitly. Better: also show last export timestamp / error and a live reachability probe.

---

## 3. `hermes claw` — OpenClaw migration

### `hermes claw`  `id: cli-f.claw`
- **Surface:** CLI
- **Where:** `hermes claw [-h] {migrate,cleanup,clean} ...` — top-level help "OpenClaw migration tools", description "Migrate settings, memories, skills, and API keys from OpenClaw to Hermes".
- **What it does:** Umbrella for the OpenClaw → Hermes migration commands.
- **How it works:** Parser `hermes_cli/subcommands/claw.py:12-92` (`dest="claw_action"`); handler `hermes_cli/main.py:13129-13132 cmd_claw` → `hermes_cli/claw.py:301-317 claw_command(args)`.
- **Inputs / options:** `-h, --help`; sub-commands `migrate`, `cleanup` (alias `clean`).
- **Outputs / side effects:** With no sub-command prints its own mini-usage: `Usage: hermes claw <command> [options]`, blank, `Commands:`, `  migrate          Migrate settings from OpenClaw to Hermes`, `  cleanup          Archive leftover OpenClaw directories after migration`, blank, `Run 'hermes claw <command> --help' for options.`
- **Config / env:** n/a
- **Edge cases / guards:** Known OpenClaw directory names are `(".openclaw", ".clawdbot", ".moltbot")` (`hermes_cli/claw.py:56`).
- **Rebuild notes:** A thin router; the value is in the two verbs. Better: a generic `hermes migrate --from <tool>` with pluggable importers.

### `hermes claw migrate`  `id: cli-f.claw.migrate`
- **Surface:** CLI
- **Where:** `hermes claw migrate [-h] [--source SOURCE] [--dry-run] [--preset {user-data,full}] [--overwrite] [--migrate-secrets] [--no-backup] [--workspace-target WORKSPACE_TARGET] [--skill-conflict {skip,overwrite,rename}] [--yes]`
- **What it does:** Imports settings, memories, skills and (opt-in) API keys from an OpenClaw installation into `~/.hermes`. Always shows a preview before making changes.
- **How it works:** `hermes_cli/claw.py:319-562 _cmd_migrate`. Source resolution: explicit `--source`, else `~/.openclaw`, else the first existing legacy dir among `.clawdbot`, `.moltbot`. The actual migrator is the `openclaw_to_hermes.py` script shipped with the `openclaw-migration` optional skill, found at `optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py` or `<hermes home>/skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py` (`:37-53`, `:202-208`), loaded dynamically via `importlib.util.spec_from_file_location` and registered in `sys.modules` (Python 3.11+ needs that for `@dataclass` resolution, `:210-225`). Flow: banner → source check → script check → settings header → `_warn_if_openclaw_running` → `_warn_if_gateway_running` → ensure `config.yaml` exists (`save_config(load_config())`) → `mod.resolve_selected_options(None, None, preset=preset)` → **Phase 1** `mod.Migrator(..., execute=False, ...)` preview → conflict guard → **Phase 2** confirmation → **Phase 2b** pre-apply backup via `hermes_cli.backup.create_pre_migration_backup(hermes_home=…)` (same exclusion rules / SQLite safe-copy / zip format as the pre-update backup, auto-pruned to the last 5 pre-migration zips) → `mod.Migrator(..., execute=True, ...)` → `_print_migration_report(report, dry_run=False)`. The `Migrator` kwargs are `source_root`, `target_root`, `execute`, `workspace_target`, `overwrite`, `migrate_secrets`, `output_dir=None`, `selected_options`, `preset_name`, `skill_conflict_mode`.
- **Inputs / options:** `-h, --help`; `--source SOURCE` ("Path to OpenClaw directory (default: ~/.openclaw)"); `--dry-run` ("Preview only — stop after showing what would be migrated"); `--preset {user-data,full}` (default `full`; "Neither preset imports secrets — pass --migrate-secrets to include API keys."); `--overwrite` ("Overwrite existing files (default: refuse to apply when the plan has conflicts)"); `--migrate-secrets` ("Include allowlisted secrets (TELEGRAM_BOT_TOKEN, API keys, etc.). Required even under --preset full."); `--no-backup` ("Skip the pre-migration zip snapshot of ~/.hermes/ (by default a single restore-point archive is written to ~/.hermes/backups/ before apply; restorable with 'hermes import')."); `--workspace-target WORKSPACE_TARGET` ("Absolute path to copy workspace instructions into"); `--skill-conflict {skip,overwrite,rename}` (default `skip`); `--yes, -y` ("Skip confirmation prompts").
- **Outputs / side effects:** Writes files into `~/.hermes` (config, memories, skills, optionally `.env` secrets), writes a pre-migration zip into `~/.hermes/backups/`, and writes a full JSON report into the migrator's output directory. Visible strings include the magenta banner box `│          ⚕ Hermes — OpenClaw Migration                 │`; `Migration Settings` header with `Source:      {dir}`, `Target:      {hermes home}`, `Preset:      {preset}`, `Overwrite:   {yes|no (skip conflicts)}`, `Secrets:     {yes (allowlisted only)|no}`, optional `Skill conflicts: {mode}` and `Workspace:   {path}`; `Migration Preview — {n} item(s) would be imported` or `Migration Preview — {n} conflict(s), nothing would be imported`; `No changes have been made yet. Review the list below:`; report sections `Dry Run Results` / `Migration Results`, `  ✓ Would migrate:` / `  ✓ Migrated:` (rows `      {kind:<22s} → {dest}` with `$HOME` shortened to `~`), `  ⚠ Conflicts (skipped — use --overwrite to force):`, `  ─ Skipped:`, `  ✗ Errors:`, `Summary: {n} migrated, {n} conflict(s), {n} skipped, {n} error(s)` or `Nothing to migrate.`, `Full report saved to: {output_dir}`, `To execute the migration, run without --dry-run:` + `  hermes claw migrate --preset {preset}`, `Migration complete!`, and the API-key warning block `  ⚠ API keys were NOT migrated (secrets migration is disabled by default).` / `  Your OPENROUTER_API_KEY and other provider keys must be added manually.` / `To migrate API keys, re-run with:` / `  hermes claw migrate --migrate-secrets` / `Or add your key manually:` / `  hermes config set OPENROUTER_API_KEY sk-or-v1-...`; backup lines `Pre-migration backup: {path} ({size})` and `Restore with: hermes import {name}`.
- **Config / env:** Writes `~/.hermes/config.yaml` and `~/.hermes/.env`; reads `HERMES_HOME`.
- **Edge cases / guards:** Missing source: `OpenClaw directory not found: {dir}` + `Make sure your OpenClaw installation is at the expected path.` + `You can specify a custom path: hermes claw migrate --source /path/to/.openclaw`. Missing script: `Migration script not found.` + `Expected at one of:` + both paths + `Make sure the openclaw-migration skill is installed.` Load failure: `Could not load migration script.` / `Could not load migration script: {e}`. Preview failure: `Migration preview failed: {e}`. Nothing to do (0 migrated AND 0 conflicts): `Nothing to migrate from OpenClaw.` **Conflict guard** (modelled on OpenClaw's `assertConflictFreePlan()`): with conflicts and no `--overwrite` it refuses — `Plan has {n} conflict(s). Refusing to apply.` + `Each conflict is an item whose target already exists in ~/.hermes/. Re-run with --overwrite to replace conflicting targets (item-level backups are written to the migration report directory).` + `Or re-run with --dry-run to review the full plan.` **Non-TTY**: `Non-interactive session — preview only.` + `To execute, re-run with: hermes claw migrate --yes`. Declined prompt: `Migration cancelled.` Backup failure aborts: `Could not create pre-migration backup: {e}` + `Re-run with --no-backup to skip, or free up disk space under the Hermes home.` Migration failure: `Migration failed: {e}` + `A pre-migration backup is available at: {path}` + `Restore with: hermes import {name}`. **Running-OpenClaw guard** (`_warn_if_openclaw_running`, `:125-155`): detects `systemctl --user is-active openclaw-gateway.service` == `active`, `pgrep -f openclaw` on POSIX, and on Windows `tasklist /FI "IMAGENAME eq openclaw.exe|clawd.exe"` plus a PowerShell `Get-CimInstance Win32_Process` scan for `node.exe` whose command line matches `openclaw|clawd` — all through `bounded_probe_run` on Windows because a plain `subprocess.run(timeout=…)` can hang forever in post-timeout cleanup when a `conhost.exe` descendant holds duplicated pipe handles (#87134). It prints `OpenClaw appears to be running:` + `  * {detail}` + the one-token-per-bot explanation + `Recommendation: stop OpenClaw before migrating.` and, on a `no` answer, `Migration cancelled. Stop OpenClaw and try again.` then `sys.exit(0)`. **Running-gateway guard** (`_warn_if_gateway_running`, `:157-192`) reads `gateway.status.get_running_pid()` / `read_runtime_status()` and warns only when at least one platform is in state `connected`: `Hermes gateway is running with active connections: {names}` + the Telegram-409 explanation + `Recommendation: stop the gateway first with 'hermes gateway stop'.`, exiting 0 on refusal. The source directory is deliberately left untouched — archiving is `hermes claw cleanup`'s job.
- **Rebuild notes:** Two-phase (preview then apply) with an explicit conflict-free assertion, a mandatory restore point before mutation, and secrets strictly opt-in even under a "full" preset. Better: make the apply transactional (stage into a temp tree and swap) so a mid-run failure cannot leave a half-migrated home.

### `hermes claw cleanup` (alias `hermes claw clean`)  `id: cli-f.claw.cleanup`
- **Surface:** CLI
- **Where:** `hermes claw cleanup [-h] [--source SOURCE] [--dry-run] [--yes]`; the alias `hermes claw clean` resolves to the same parser (`aliases=["clean"]`, `hermes_cli/subcommands/claw.py:75-80`).
- **What it does:** Scans for leftover OpenClaw directories and archives them by renaming to `<name>.pre-migration`, to prevent state fragmentation. Nothing is deleted.
- **How it works:** `hermes_cli/claw.py:564-707 _cmd_cleanup`. Targets: `--source` if given, else `_find_openclaw_dirs()` = existing `~/.openclaw`, `~/.clawdbot`, `~/.moltbot`. For each target it scans workspace state with `_scan_workspace_state` (root `todo.json`, `sessions`, `logs`; then per non-dot subdirectory `todo.json`, `sessions`, `logs`, `memory`) and counts "workspace directories" (a subdir containing any of `todo.json`, `SOUL.md`, `MEMORY.md`, `USER.md`). Renaming is `_archive_directory` (`:274-299`): `<name>.pre-migration`, then `<name>.pre-migration-<YYYYMMDD>` if taken, then `<name>.pre-migration-<YYYYMMDD>-<counter>` incrementing from 2.
- **Inputs / options:** `-h, --help`; `--source SOURCE` ("Path to a specific OpenClaw directory to clean up"); `--dry-run` ("Preview what would be archived without making changes"); `--yes, -y` ("Skip confirmation prompts").
- **Outputs / side effects:** Renames directories on disk. Banner `│          ⚕ Hermes — OpenClaw Cleanup                   │`; per directory `Found: {dir}` header, `Workspace directories: {n}` with up to 5 rows `      {name}/  ({todo.json, sessions/, SOUL.md, MEMORY.md | empty})` then `      ... and {n} more`, `  {n} state file(s) found:` with up to 8 rows `      {description}` then `      ... and {n} more`; per directory `Would archive: {src} → {dest}` (dry run), `Archived: {src} → {dest}`, or `Skipped.`; summary `Dry run complete. {n} director{y|ies} would be archived.` + `Run without --dry-run to archive them.`, `Cleaned up {n} OpenClaw director{y|ies}.` + `Directories were renamed, not deleted. You can undo by renaming them back.`, or `No directories were archived.`
- **Config / env:** n/a
- **Edge cases / guards:** Nothing found: `No OpenClaw directories found. Nothing to clean up.` **Running-OpenClaw guard** (issue #8502): archiving while the service is active makes it immediately recreate an empty skeleton directory, destroying the config — prints `OpenClaw appears to be still running:` + `  * {detail}` + `Archiving .openclaw/ while the service is active may cause it to immediately recreate an empty skeleton directory, destroying your config.` + `Stop OpenClaw first: systemctl --user stop openclaw-gateway.service`, and in a non-TTY session `Non-interactive session — aborting. Stop OpenClaw and re-run.`, or on refusal `Aborted. Stop OpenClaw first, then re-run: hermes claw cleanup`. Non-TTY without `--yes` per directory: `Non-interactive session — would archive: {dir}` + `To execute, re-run with: hermes claw cleanup --yes`. Rename failure: `Could not archive: {e}` + `Try manually: mv {src} {src}.pre-migration`.
- **Rebuild notes:** Rename-not-delete with a collision-avoiding suffix ladder, plus a guard against the source service recreating the directory. Better: offer a `--restore` that renames back.

---

## 4. `hermes prompt-size`, `hermes logs`, `hermes completion`

### `hermes prompt-size`  `id: cli-f.prompt-size`
- **Surface:** CLI
- **Where:** `hermes prompt-size [-h] [--platform PLATFORM] [--json]` — top-level help "Show a byte breakdown of the system prompt + tool schemas", description "Report the fixed prompt budget for a fresh session: system prompt total, skills index, memory, user profile, and tool-schema JSON. Runs offline (no API call)."
- **What it does:** Shows exactly where the fixed per-call prompt budget goes for a fresh session: total system prompt bytes, the `<available_skills>` index, memory, user profile, the three prompt tiers, tool-schema JSON, per-toolset schema cost and per-skill cost.
- **How it works:** Parser `hermes_cli/subcommands/prompt_size.py:12-36`; handler `hermes_cli/main.py:12345-12349` → `hermes_cli/prompt_size.py:365-377 cmd_prompt_size`. `compute_prompt_breakdown(platform)` (`:235-298`) builds a REAL but offline agent via `_build_inspection_agent` (`:50-81`): `AIAgent(model=<config model.default|model.model>, api_key="inspect-only", base_url="https://openrouter.ai/api/v1", quiet_mode=True, save_trajectories=False, platform=platform, enabled_toolsets=sorted(_get_platform_tools(cfg, platform)), disabled_toolsets=parse_config_string_list(cfg["agent"]["disabled_toolsets"]))` — the dummy credentials force the direct-construction path so no provider auto-detection or network call happens. It then calls `agent.system_prompt.build_system_prompt_parts(agent)` (tiers `stable`, `context`, `volatile`) and `build_system_prompt(agent)`, extracts the skills index with the regex `<available_skills>.*?</available_skills>` (searched in `volatile` first, then `stable` — the index moved to the volatile tier so skill edits do not invalidate the cached identity prefix), re-derives memory and user-profile blocks from `agent._memory_store.format_for_system_prompt("memory"|"user")` gated on `agent._memory_enabled` / `agent._user_profile_enabled`, and serialises `agent.tools` to JSON. Per-skill attribution `_compute_skills_breakdown` (`:117-206`) parses lines starting with `"    - "` as `name: desc` (partitioning on `": "` so namespaced names like `codex:rescue` stay intact) and handles posture-demoted categories rendered as `^  .+ \[names only\]: (?P<names>.+)$` by splitting on commas and dividing the shared prefix bytes evenly (`divmod`, remainder handed to the first names) so attributed bytes sum exactly to the rendered line; `skill_md_bytes` is the on-disk `SKILL.md` size resolved through `_skill_md_paths_by_name()` (keyed by both frontmatter `name` and directory name, local skill dirs winning via `setdefault`). Per-toolset attribution `_compute_toolsets_breakdown` (`:209-232`) maps each tool to its canonical toolset via `tools.registry.registry.get_tool_to_toolset_map()` (unmapped → `(unknown)`).
- **Inputs / options:** `-h, --help`; `--platform PLATFORM` (default `cli` — "Platform to simulate (cli, telegram, discord, ...)"); `--json` ("Emit the breakdown as JSON").
- **Outputs / side effects:** Read-only, offline. Text output lines: `Prompt-size breakdown (platform={platform}, model={model|unset})`; `  System prompt total : {bytes:>8,} B  ({kb}, {chars:,} chars)`; `  Major blocks:` with `    skills index       : {b:>8,} B  ({kb})`, `    memory             : …`, `    user profile       : …`; `  Prompt tiers:` with the three labels `stable (identity/guidance/skills)`, `context (AGENTS.md/cwd files)`, `volatile (memory/profile/timestamp)`; `  Tool schemas         : {b:>8,} B  ({kb}, {n} tools)`; `  Toolsets by size (tool-schema JSON, largest first):` with header `    {'toolset':<22} {'tools':>5}  {'schema':>10}`; `  Skills by size (SKILL.md on-disk = read cost; index cost = attributed always-on bytes, largest first):` with header `    {'skill':<28} {'SKILL.md':>10}  {'index cost':>10}`, capped at 20 rows (`_SKILLS_TABLE_LIMIT`) then `    … and {n} more (use --json for the full list)`. `--json` emits the whole dict: `platform`, `model`, `system_prompt{chars,bytes}`, `skills_index{chars,bytes}`, `memory{chars,bytes}`, `user_profile{chars,bytes}`, `tools{count,json_bytes}`, `sections[[label,chars,bytes]…]`, `skills_breakdown[{name,index_line_bytes,index_line_total_bytes,index_line_shared_bytes,index_line_skill_count,skill_md_bytes,path}…]`, `toolsets_breakdown[{toolset,tool_count,json_bytes}…]`.
- **Config / env:** `model.default` / `model.model`, `agent.disabled_toolsets`, the platform toolset mapping consumed by `_get_platform_tools`; skill directories from `agent.skill_utils.get_all_skills_dirs()`.
- **Edge cases / guards:** Any exception during computation prints `Could not compute prompt-size breakdown: {e}` and returns (never raises). `skill_md_bytes` is `None`/`n/a` when a name cannot be mapped to a file (e.g. a plugin skill outside the scanned dirs). Skill entries sort by `-(skill_md_bytes or 0)` then name; toolsets by `-json_bytes` then name. Byte counts are UTF-8 (`len(s.encode("utf-8"))`).
- **Rebuild notes:** Construct the agent the way a real session would but with sentinel credentials, then measure the rendered prompt rather than estimating it; attribute shared lines proportionally so totals reconcile. Better: also report token counts per tokenizer and diff two platforms side by side.

### `hermes logs`  `id: cli-f.logs`
- **Surface:** CLI
- **Where:** `hermes logs [-h] [-n LINES] [-f] [--level LEVEL] [--session ID] [--since TIME] [--component NAME] [log_name]` — top-level help "View and filter Hermes log files", description "View, tail, and filter agent.log / errors.log / gateway.log / gui.log / desktop.log".
- **What it does:** Views, tails and filters the Hermes log files under `<hermes home>/logs/`, or lists the available files with sizes.
- **How it works:** Parser `hermes_cli/subcommands/logs.py:13-78` (uses `argparse.RawDescriptionHelpFormatter` so the examples epilog keeps its layout); handler `hermes_cli/main.py:12352-12370 cmd_logs` → `hermes_cli/logs.py`. `log_name == "list"` routes to `list_logs()` (`hermes_cli/logs.py:365-397`); everything else to `tail_log(...)` (`:145-253`). The name→file map `LOG_FILES` (`:32-41`) is `{"agent": "agent.log", "errors": "errors.log", "gateway": "gateway.log", "gui": "gui.log", "desktop": "desktop.log", "mcp": "mcp-stderr.log"}` — note `mcp` is accepted by the code but NOT advertised in `--help`; its comment says it holds "Every stdio MCP subprocess's stderr (tools/mcp_tool.py redirects it here, with per-server session markers) — the 'MCP output channel'". Filtering: `--since` is parsed by `_parse_since` (`:63-80`) with regex `^(\d+)\s*([smhd])$` → seconds/minutes/hours/days before now; line timestamps by `^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})` and `datetime.strptime(..., "%Y-%m-%d %H:%M:%S")`; levels by `\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s` with ordering `{"DEBUG":0,"INFO":1,"WARNING":2,"ERROR":3,"CRITICAL":4}`; logger names by `\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)(?:\s+\[.*?\])?\s+(\S+):` so a session tag between level and logger is tolerated; components map to logger prefixes via `hermes_logging.COMPONENT_PREFIXES` = `{"gateway": ("gateway","hermes_plugins","plugins.platforms"), "agent": ("agent","run_agent","model_tools","batch_runner"), "tools": ("tools",), "cli": ("hermes_cli","cli"), "cron": ("cron",), "gui": ("hermes_cli.web_server","hermes_cli.pty_bridge","tui_gateway","uvicorn")}` (`hermes_logging.py:244-260`). Tail reading `_read_last_n_lines` (`:285-338`) reads the whole file when ≤ 1 MiB (1_048_576 bytes), otherwise walks backwards in doubling chunks (8192 → 65536) merging split lines; with filters active it first pulls `max(num_lines*20, 2000)` raw lines then filters down. Follow mode `_follow_log` (`:341-362`) seeks to EOF and polls `readline()` with `time.sleep(0.3)` between empty reads.
- **Inputs / options:** `-h, --help`; positional `log_name` (`nargs="?"`, default `agent`; documented values `agent`, `errors`, `gateway`, `gui`, plus `desktop` and the undocumented `mcp`, plus the literal `list`); `-n LINES, --lines LINES` (int, default 50); `-f, --follow`; `--level LEVEL` (metavar `LEVEL`; DEBUG/INFO/WARNING/ERROR — CRITICAL is also accepted by the code); `--session ID` (substring match on the whole line); `--since TIME` (e.g. `1h`, `30m`, `2d`, also `s` seconds); `--component NAME` (gateway, agent, tools, cli, cron, gui).
- **Outputs / side effects:** Read-only. Header line `--- {display_hermes_home()}/logs/{filename}{filter_desc} (last {n}) ---` or `--- … (Ctrl+C to stop) ---` in follow mode, where `filter_desc` is ` [level>=X, session=Y, component=Z, since=W]` built in that order. Follow ends on Ctrl-C with `\n--- stopped ---`. `hermes logs list` prints `Log files in {home}/logs/:` then one row per `*.log` file `  {name:<25} {size:>8}   {age}` where size is `{n}B` / `{kb:.1f}KB` / `{mb:.1f}MB` and age is `just now` (<60 s), `{n}m ago` (<1 h), `{n}h ago` (<24 h) else the `YYYY-MM-DD` mtime; empty dir → `  (no log files yet — run 'hermes chat' to generate logs)`.
- **Config / env:** `HERMES_HOME` (log directory `<home>/logs`).
- **Edge cases / guards:** Unknown log name: `Unknown log: {name!r}. Available: {sorted names}` then `sys.exit(1)`. Missing file: `Log file not found: {path}` + `(Logs are created when Hermes runs — try 'hermes chat' first)` then exit 1. Bad `--since`: `Invalid --since value: {v!r}. Use format like '1h', '30m', '2d'.` exit 1. Bad `--level`: `Invalid --level: {v!r}. Use DEBUG, INFO, WARNING, ERROR, or CRITICAL.` exit 1. Unknown component: `Unknown component: {v!r}. Available: {sorted}` exit 1. `PermissionError` while reading: `Permission denied: {path}` exit 1. Missing log dir for `list`: `No logs directory at {home}/logs/`. Lines with no parseable timestamp are NOT excluded by `--since`, and lines with no parseable level are NOT excluded by `--level` (both filters only reject when they can positively read the field). Any read error in `_read_last_n_lines` falls back to reading the entire file.
- **Rebuild notes:** A tail implementation that reads backwards in chunks, a small set of regexes for timestamp/level/logger, and a component→logger-prefix table shared with the logging setup. Better: structured (JSON-lines) logs so filtering is exact rather than regex-based, plus `--grep` and `--json`.

### `hermes completion`  `id: cli-f.completion`
- **Surface:** CLI
- **Where:** `hermes completion [-h] [{bash,zsh,fish}]` — top-level help "Print shell completion script (bash, zsh, or fish)".
- **What it does:** Prints a shell completion script for the `hermes` command, generated by walking the live argparse parser tree so it is always in sync with the installed version.
- **How it works:** Parser `hermes_cli/main.py:14643-14654`; the handler is a lambda that passes the ROOT parser: `completion_parser.set_defaults(func=lambda args: cmd_completion(args, parser))` (`:14654`). `cmd_completion` (`hermes_cli/main.py:12332-12343`) dispatches to `hermes_cli/completion.py` `generate_zsh(parser)`, `generate_fish(parser)` or `generate_bash(parser)` (default). `_walk(parser)` (`hermes_cli/completion.py:15-43`) recurses through `argparse._SubParsersAction._choices_actions`, which yields exactly one entry per CANONICAL sub-command name (aliases are omitted, keeping the completion lists clean), collecting `{"flags": [...], "subcommands": {...}, "help": ...}`. `_clean(text, maxlen=60)` strips `'`, `"` and `\` and truncates to 60 chars so help strings are shell-safe.
- **Inputs / options:** `-h, --help`; positional `shell` (`nargs="?"`, `choices=["bash","zsh","fish"]`, default `bash`).
- **Outputs / side effects:** Writes the script to stdout only. Nothing is installed.
- **Config / env:** The generated bash/zsh/fish helpers read `$HOME/.hermes/profiles` at completion time to list profile names.
- **Edge cases / guards:** Profile-name completion is special-cased in all three generators for the actions `use`, `delete`, `show`, `alias`, `rename`, `export` (bash `hermes_cli/completion.py:66`, zsh `:171`, fish `:293`) and after `-p` / `--profile`. Sub-command completion wins over flag completion: a command with sub-commands never offers its flags.
- **Rebuild notes:** Generate completions from the parser at runtime rather than checking in static lists. Better: also complete session ids, model names and skill names from the live store.

### `hermes completion bash`  `id: cli-f.completion.bash`
- **Surface:** CLI
- **Where:** `hermes completion bash` — install with `eval "$(hermes completion bash)"` in `~/.bashrc` (the generated script says so in its own header comment).
- **What it does:** Emits a bash completion function `_hermes_completion` registered with `complete -F _hermes_completion hermes`.
- **How it works:** `hermes_cli/completion.py:55-139 generate_bash`. Emits a `_hermes_profiles()` helper that echoes `default` plus every directory basename under `$HOME/.hermes/profiles`; then a completion function that (1) completes profile names when `$prev` is `-p` or `--profile`, (2) at `COMP_CWORD >= 2` switches on `${COMP_WORDS[1]}` with one `case` arm per top-level command — sub-commands if the command has them, else its flags, (3) at `COMP_CWORD == 1` completes the sorted top-level command list.
- **Inputs / options:** n/a (no flags of its own).
- **Outputs / side effects:** Script text on stdout.
- **Config / env:** Reads `$HOME/.hermes/profiles` at completion time (hardcoded — it does not honour `HERMES_HOME`).
- **Edge cases / guards:** The `profile` command gets a nested `case "$prev"` so `hermes profile use <TAB>` completes profile names for `use|delete|show|alias|rename|export`.
- **Rebuild notes:** Emit one `case` arm per command from the parser walk. Better: honour `HERMES_HOME` for the profile directory.

### `hermes completion zsh`  `id: cli-f.completion.zsh`
- **Surface:** CLI
- **Where:** `hermes completion zsh` — install with `eval "$(hermes completion zsh)"` in `~/.zshrc`.
- **What it does:** Emits a `#compdef hermes` zsh completion function `_hermes` registered with `compdef _hermes hermes`.
- **How it works:** `hermes_cli/completion.py:146-244 generate_zsh`. Uses `_arguments -C` with `'(-)'{-h,--help}'[Show help and exit]'`, `'(-)'{-V,--version}'[Show version and exit]'`, `'(-)'{-p,--profile}'[Profile name]:profile:_hermes_profiles'`, `'1:command:->commands'` and `'*::arg:->args'`. Top-level commands are described via `_describe 'hermes command' subcmds` with `'name:help'` pairs; each command that has sub-commands gets a `case ${line[1]}` arm calling `_describe '<cmd> command' <cmd>_cmds`. The `_hermes_profiles` helper uses the zsh glob qualifier `$HOME/.hermes/profiles/*(N/:t)` (null-glob, directories only, tail).
- **Inputs / options:** n/a
- **Outputs / side effects:** Script text on stdout.
- **Config / env:** Reads `$HOME/.hermes/profiles`.
- **Edge cases / guards:** Command names containing `-` are sanitised into array variable names with `cmd.replace("-", "_")` (`:190`), so e.g. `prompt-size` yields `prompt_size_cmds`.
- **Rebuild notes:** As bash, but emit `_describe` pairs so zsh shows help text inline.

### `hermes completion fish`  `id: cli-f.completion.fish`
- **Surface:** CLI
- **Where:** `hermes completion fish` — install with `hermes completion fish | source`.
- **What it does:** Emits fish `complete -c hermes` lines for every top-level command and every sub-command, plus profile-name completion.
- **How it works:** `hermes_cli/completion.py:251-319 generate_fish`. Emits `function __hermes_profiles` (echo `default` then each directory basename under `$HOME/.hermes/profiles`), `complete -c hermes -f` (disable file completion by default), `complete -c hermes -f -s p -l profile -d 'Profile name' -xa '(__hermes_profiles)'`, then one `complete … -n 'not __fish_seen_subcommand_from <all top cmds>' -a <cmd> -d '<help>'` line per top-level command, then per sub-command `complete … -n '__fish_seen_subcommand_from <cmd>' -a <sub> -d '<help>'`, and for `profile` additional lines gated on `__fish_seen_subcommand_from <action>; and __fish_seen_subcommand_from profile` for the actions `alias`, `delete`, `export`, `rename`, `show`, `use`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Script text on stdout.
- **Config / env:** Reads `$HOME/.hermes/profiles`.
- **Edge cases / guards:** File completion is globally disabled for `hermes`, so path arguments (e.g. `sessions export <path>`) get no filename suggestions in fish.
- **Rebuild notes:** One `complete` line per node of the parser tree. Better: re-enable file completion for the specific positionals that take paths.

---

## 5. `hermes update` — the self-update pipeline

### `hermes update`  `id: cli-f.update`
- **Surface:** CLI
- **Where:** `hermes update [-h] [--gateway] [--check] [--plan] [--no-backup] [--backup] [--yes] [--keep-stash] [--branch NAME] [--switch-branch] [--force] [--force-venv]`. Root help line: `update              Update Hermes Agent to the latest version`; description `Pull the latest changes from git and reinstall dependencies`. Also reachable from the gateway slash command `/update` (which passes `--gateway`) and from the web dashboard's Update button (`POST /api/hermes/update` → detached `hermes update`).
- **What it does:** Pulls the newest Hermes source from git into the local checkout, reinstalls Python dependencies, re-syncs bundled skills into every profile, and restarts every running Hermes service it can identify.
- **How it works:** Parser `hermes_cli/subcommands/update.py:12-114 build_update_parser` (`update_parser.set_defaults(func=cmd_update)`). Handler `hermes_cli/main.py:10790 cmd_update` is a thin wrapper: (1) `is_managed()` → `managed_error("update Hermes Agent")` and return; (2) `--plan` runs first (read-only, before any refusal gate) via `hermes_cli/update_inventory.py:144 collect_runtime_inventory()` + `:392 print_update_plan()`; (3) `hermes_cli/update_contract.py:40 evaluate_update_admission(PROJECT_ROOT)` — refuse image/package-managed installs, print the real command, `record_refusal_receipt`, `sys.exit(2)`; (4) `--check` → `_resolve_update_branch(args)` then `update_cmd.py:4222 _cmd_update_check(branch, branch_explicit)`; (5) `_install_hangup_protection(gateway_mode)` (`main.py:10663`) sets `SIGHUP` to `SIG_IGN` and wraps stdout/stderr in `_UpdateOutputStream` mirroring to `<HERMES_HOME>/logs/update.log` with the header `=== hermes update started <iso> ===`; (6) `hermes_cli/update_lock.py UpdateLock().acquire()` — cross-process marker `<HERMES_HOME>/.hermes-update-in-progress` containing `"<pid>\n<started_at_unix>"`, live only while the pid is alive and younger than `UPDATE_MARKER_MAX_AGE_SECONDS = 20*60`; a live foreign holder prints `describe_holder(...)` and exits `UPDATE_EXIT_CONCURRENT = 2`; (7) `update_cmd.py:7821 _cmd_update_impl(args, gateway_mode)`; (8) finally `finalize_pending_update_receipt(code, reason)`, `_update_lock.release()`, `_finalize_update_output(state)`, and on the Windows re-exec hand-off child (`_UPDATE_REEXEC_ENV == "1"`) `os._exit(code)` to avoid a hung console.
  The impl phases, in order (`update_cmd.py:7821+`): capture active lazy features + tool dependencies → read pre-update version → decide `_non_interactive_update` (gateway mode, `--yes`, or non-TTY) and read `updates.non_interactive_local_changes` (`stash` default, `discard` opt-in) → print `⚕ Updating Hermes Agent...` → `begin_update_receipt()` → fleet plan (`→ Fleet: N running service(s) across profiles: …`) → Windows concurrent-`hermes.exe` guard (skippable with `--force`) → `_run_pre_update_backup(args)` → `_pause_windows_gateways_for_update()` + atexit resume → Windows venv-holder guard with five escalating rungs (leftover gateways → ledger-identified orphaned backends → orphaned Desktop backends → manual serve/dashboard holders relaunched at exit → GUI hand-off) unless `--force-venv` → git repo check (`✗ Not a git repository. Please reinstall:`) → fork/upstream detection (`⚠ Updating from fork:`) → `gitlock.clear_stale_git_locks` / `clear_stale_tmp_packs` → `→ Fetching updates...` → `→ Pulling updates...` (with syntax-check + rollback of the pulled tree on `✗ Pulled code has a syntax error in a critical file:`) → no-op detection (`✗ Code did not move — update was a no-op.`) → dependency sync (`→ Updating Python dependencies...`, or `→ Python dependencies unchanged — skipping reinstall`; Termux/Android take a curated `termux-all` optional profile and pre-build psutil) → model-catalog cache refresh → `→ Syncing bundled skills...` and `→ Syncing bundled skills to all profiles...` → optional `→ Refreshing cua-driver (Computer Use)...` (`updates.refresh_cua_driver`) → legacy `hermes.service` unit warning → restart phase reconciled against the pre-update plan → `finalize_update_receipt`.
- **Inputs / options:** `-h, --help`; `--gateway`; `--check`; `--plan`; `--no-backup`; `--backup`; `--yes` / `-y`; `--keep-stash`; `--branch NAME`; `--switch-branch`; `--force`; `--force-venv`. (12 flags; each documented separately below.)
- **Outputs / side effects:** Rewrites the git checkout at `PROJECT_ROOT`; rewrites the venv's installed packages; writes `<HERMES_HOME>/logs/update.log`, `<HERMES_HOME>/logs/update_receipts/*.json` (last 20 kept), `<HERMES_HOME>/state-snapshots/<id>/` and optionally `<HERMES_HOME>/backups/<zip>`; creates/removes `<HERMES_HOME>/.hermes-update-in-progress`; may `git stash` and re-apply local changes; restarts systemd/launchd/Windows-service/desktop/manual backends; re-seeds `skills/` in every profile.
- **Config / env:** `updates.pre_update_backup` (`quick` default; `off`/`full`), `updates.backup_keep` (5), `updates.non_interactive_local_changes` (`stash`), `updates.auto_switch_parked_branch` (true), `updates.parked_branch_strategy` (`switch`), `updates.refresh_cua_driver` (true). Env: `HERMES_HOME`, `HERMES_UPDATE_HANDOFF_PID` (`update_lock.HANDOFF_PID_ENV`), the Windows re-exec marker env, `ELECTRON_MIRROR` (desktop rebuild path), `HERMES_REDACT_SECRETS`.
- **Edge cases / guards:** Refuses on managed installs (`is_managed()`); exits 2 for image/docker/nix/apt-managed installs and for a concurrent update; exits 2 on Windows when another `hermes.exe` or venv-python process is detected; leaves the tree untouched and rolls back when the pulled code fails a syntax check; a shallow clone reports "commit count unknown" instead of a bogus behind-count; `--yes` never enters API keys (the message tells the user to run `hermes config migrate`).
- **Rebuild notes:** Minimum viable: acquire a pid+mtime marker lock, back up state, `git fetch && git reset --hard origin/<branch>`, reinstall deps, restart supervised services, write a JSON receipt. A better version would do an atomic two-slot install (new tree beside old, symlink flip) so a failed dependency sync can never strand a half-updated interpreter.

### `hermes update --check`  `id: cli-f.update.check`
- **Surface:** CLI
- **Where:** `hermes update --check` — help text `Check whether an update is available without installing anything`.
- **What it does:** Fetches the compare branch and prints whether the local checkout is behind, without touching any file outside `.git`.
- **How it works:** `main.py:10841-10849` → `_resolve_update_branch(args)` (`main.py:10766`: `(args.branch or "main").strip() or "main"`) → `update_cmd.py:4222 _cmd_update_check`. Runs the same `evaluate_update_admission` gate first (so an image-managed install never reports git state). Requires `.git` (`✗ Not a git repository — cannot check for updates.`, exit 1). On Windows adds `git -c windows.appendAtomically=false`. Clears stale git locks (`  (removed stale git lock: <path>)`) and aborted-fetch temp packs (`  (removed N aborted-fetch pack temp file(s))`). Detects a shallow clone via `git rev-parse --is-shallow-repository` and then fetches with `--depth 1`. For branch `main` it probes `git remote get-url upstream` locally first; if present it prints `→ Fetching from upstream...` and compares against `upstream/main`, else `→ Fetching from origin...` and `origin/main`. Non-default branches always compare against `origin/<branch>`. Verifies the compare ref with `git rev-parse --verify --quiet` (`✗ Branch '<b>' not found on origin.`, exit 1). Shallow path compares tip SHAs and asks `banner._github_compare_behind(head, target)` for an exact count; otherwise `git rev-list HEAD..<compare> --count`.
- **Inputs / options:** none of its own; honours `--branch NAME`.
- **Outputs / side effects:** Network fetch only (plus lock/tmp-pack cleanup). Prints one of: `✓ Already up to date.`, `⚕ Update available: N commit[s] behind <compare_branch>.`, `⚕ Update available (behind <compare_branch>).`, followed by `  Run '<recommended_update_command()>' to install.`
- **Config / env:** none beyond `HERMES_HOME`; exit code 1 on fetch/ref failure, 2 on an image-managed refusal.
- **Edge cases / guards:** A shallow installer clone is never unshallowed by the check. If `--branch` was explicitly given on an install that cannot honour non-default branches (e.g. Docker) a one-line notice is printed rather than the flag being silently dropped (`branch_explicit`).
- **Rebuild notes:** `git fetch --depth 1 <remote> <branch>` then `rev-list HEAD..<remote>/<branch> --count`. Better: cache the result with a TTL so the startup banner and the dashboard share one network call.

### `hermes update --plan`  `id: cli-f.update.plan`
- **Surface:** CLI
- **Where:** `hermes update --plan`.
- **What it does:** Prints exactly what an update would touch — install kind, version/SHA, every profile, every running Hermes service with its supervisor and restart mechanism — and exits without changing anything.
- **How it works:** `main.py:10808-10820`, deliberately BEFORE the docker/nix/apt refusal gate so an image-managed install still gets a useful answer. `update_inventory.collect_runtime_inventory()` builds an `UpdatePlan {install_method, expected_version, expected_sha, updatable_in_place, update_mechanism, profiles, runtimes[]}`; each runtime carries `{kind, profile, pid, supervisor, code_sha, restart_via}` from `_detect_supervisor_for_pid` and `_restart_mechanism` (`update_inventory.py:81,105`). `print_update_plan` (`:392`) renders it.
- **Inputs / options:** none.
- **Outputs / side effects:** stdout only. Observed live output on this checkout: `Update plan:` / `  Install: git (v0.21.0 @ 29112bef)` / `  Profiles: default` / `  Running services to restart (1):` / `    • dashboard [default] pid 1633 — manual-serve` / `      restart: stop before code swap, relaunch with recorded launch args`. When no service is running: `  Running Hermes services: none detected — code swap only.` When not updatable: `  ⚠ This install is NOT updatable in place.` + `    Update via: <mechanism>`.
- **Config / env:** none.
- **Edge cases / guards:** Read-only and never raises — a probe failure simply records nothing. Restart-mechanism ids and their human strings: `systemd` → `systemctl restart (drain-first SIGUSR1 when supported)`; `launchd` → `launchctl kickstart -k (drain-first, per-label domain)`; `desktop` → `Desktop app respawns its serve backend`; `windows-service` → `sc.exe stop before venv mutation, sc.exe start after update`; `respawn-argv` → `stop before code swap, relaunch with recorded launch args`; `manual` → `hermes gateway restart` (or `hermes -p <profile> gateway restart`).
- **Rebuild notes:** Enumerate supervised processes, map pid→supervisor, print the policy table. A better version would emit the same plan as JSON for fleet tooling.

### `hermes update --gateway`  `id: cli-f.update.gateway`
- **Surface:** CLI
- **Where:** `hermes update --gateway` — help `Gateway mode: use file-based IPC for prompts instead of stdin (used internally by /update)`.
- **What it does:** Runs the update in a mode where every interactive prompt is answered through files instead of the terminal, so the gateway's `/update` slash command can drive it from a chat message.
- **How it works:** `update_cmd.py:7834-7838` swaps the input function for `lambda prompt, default="": _gateway_prompt(prompt, default)`. `_install_hangup_protection(gateway_mode=True)` returns immediately (no SIGHUP ignore, no stdio wrap) because the process is already detached from a terminal. `gateway_mode` also forces `_non_interactive_update` true, so `updates.non_interactive_local_changes` decides stash-vs-discard.
- **Inputs / options:** none of its own; combines with every other update flag.
- **Outputs / side effects:** Prompt/answer files exchanged with the gateway; no stdio mirroring to `update.log`.
- **Config / env:** `updates.non_interactive_local_changes`.
- **Edge cases / guards:** Internal flag — documented but intended for `/update`.
- **Rebuild notes:** Any file/socket prompt channel works; the point is that no code path may block on `input()` when there is no TTY.

### `hermes update --backup` / `--no-backup`  `id: cli-f.update.backup`
- **Surface:** CLI
- **Where:** `hermes update --backup`, `hermes update --no-backup`.
- **What it does:** Force a FULL pre-update backup (quick state snapshot + a zip of `HERMES_HOME`) for one run, or skip ALL pre-update backups for one run.
- **How it works:** `update_cmd.py:4611 _run_pre_update_backup(args)` resolves the mode via `_resolve_pre_update_backup_mode(args)`: `--no-backup` → `off`, `--backup` → `full`, else the config value `updates.pre_update_backup` (default `quick`). `quick` calls `hermes_cli/backup.py create_quick_snapshot(label="pre-update", keep=_PRE_UPDATE_SNAPSHOT_KEEP, max_file_size=_PRE_UPDATE_SNAPSHOT_MAX_FILE_SIZE)` which copies `_QUICK_STATE_FILES` (pairing JSONs, cron jobs, config, auth, state.db via the read-only SQLite backup API) into `<HERMES_HOME>/state-snapshots/<id>/`, skipping files over 1 GiB with a warning. `full` additionally zips the whole `HERMES_HOME` into `<HERMES_HOME>/backups/` (restorable with `hermes import`). After the snapshot it re-verifies the live `state.db` with `verify_sqlite_integrity(check_header=True, run_pragma=True)`.
- **Inputs / options:** `--backup`, `--no-backup` (both `store_true`, independent flags — `--no-backup` wins because the mode resolver checks it first).
- **Outputs / side effects:** `state-snapshots/<id>/` and/or `backups/<zip>`; receipt step `pre_update_backup` with `snapshot=<id>` or `disabled or failed`. With `--no-backup`: `◆ Pre-update backup: skipped (--no-backup)`. Config-level `off` is silent. Integrity messages: `  ⚠ state.db integrity check FAILED after snapshot: <msg>`, `  ✓ Snapshot copy is valid — continuing update.`, `    If state.db is lost after update it will be auto-restored.`, `  ✗ Snapshot copy ALSO failed integrity — the source was already corrupted before the backup.`
- **Config / env:** `updates.pre_update_backup` (`quick`|`full`|`off`), `updates.backup_keep` (5).
- **Edge cases / guards:** Never raises — a backup failure does not block the update. The returned snapshot id feeds the post-update cron-jobs restore safety net (`  ⚠ No pre-update snapshot was taken` when absent).
- **Rebuild notes:** Snapshot the small, irreplaceable files before mutating anything; verify the DB after copying. A better version would checksum the snapshot and expose a one-command rollback.

### `hermes update --yes` / `-y`  `id: cli-f.update.yes`
- **Surface:** CLI
- **Where:** `hermes update --yes` / `hermes update -y`.
- **What it does:** Runs the update without blocking on prompts — auto-accepts the config-migration and stash-restore prompts and skips the fork-upstream prompt without adding a remote.
- **How it works:** `update_cmd.py:7840 assume_yes = bool(getattr(args, "yes", False))`; feeds `_non_interactive_update` (`:7854-7859`), which then reads `updates.non_interactive_local_changes` to decide whether stashed local source changes are restored (`stash`, default) or thrown away (`discard`).
- **Inputs / options:** `--yes`, `-y`.
- **Outputs / side effects:** No prompts. API-key entry is explicitly skipped; the help text tells the user to `run 'hermes config migrate' separately for those`.
- **Config / env:** `updates.non_interactive_local_changes`.
- **Edge cases / guards:** A non-TTY stdin/stdout is treated as `--yes` for the local-changes decision even without the flag.
- **Rebuild notes:** Separate "assume yes" from "no TTY"; only the latter should change data-loss defaults.

### `hermes update --keep-stash`  `id: cli-f.update.keep-stash`
- **Surface:** CLI
- **Where:** `hermes update --keep-stash`.
- **What it does:** Stashes uncommitted local changes so the update can proceed, but never re-applies them afterwards — they stay parked in `git stash`.
- **How it works:** `update_cmd.py:7840-7846` `keep_stash = bool(getattr(args, "keep_stash", False))`. Only applies when an update actually landed; abort/no-op paths still restore, because the tree they restore onto is unchanged. Used by the desktop updater so local source edits never silently ride along across updates.
- **Inputs / options:** `--keep-stash`.
- **Outputs / side effects:** A surviving `git stash` entry; on the restore-skipped path the user is told to `Restore manually with: git stash apply`.
- **Config / env:** n/a.
- **Edge cases / guards:** Does not prevent the stash itself — a dirty tree is always stashed first.
- **Rebuild notes:** Stash → update → conditionally pop. Better: name the stash with the update's receipt id so the user can find it later.

### `hermes update --branch NAME` / `--switch-branch`  `id: cli-f.update.branch`
- **Surface:** CLI
- **Where:** `hermes update --branch NAME`, `hermes update --switch-branch`.
- **What it does:** `--branch` updates against a branch other than `main`, switching the local checkout to it first (auto-stashing). `--switch-branch` overrides `updates.parked_branch_strategy: update_in_place` for one run so the update switches to the target instead of merging the target into the checked-out branch.
- **How it works:** `_resolve_update_branch(args)` (`main.py:10766`) normalises the value (`None`/empty/whitespace → `main`) for the check path, the git-update path and the ZIP-fallback path alike. `switch_branch = bool(getattr(args, "switch_branch", False))` (`update_cmd.py:7844-7849`) is only meaningful when `updates.parked_branch_strategy` is `update_in_place`; under the default `switch` strategy it has no effect because that strategy already switches. Neither flag touches a dirty tree beyond the stash.
- **Inputs / options:** `--branch NAME` (metavar `NAME`, default `None`), `--switch-branch` (`store_true`).
- **Outputs / side effects:** May change the checked-out branch; with `--switch-branch` the parked branch's history is left exactly as it was — no merge commit is written into it.
- **Config / env:** `updates.parked_branch_strategy` (`switch` default, `update_in_place`), `updates.auto_switch_parked_branch` (true).
- **Edge cases / guards:** Still refuses to touch a dirty tree. `--check` honours `--branch` so the "is there an update?" answer matches what the apply would pull.
- **Rebuild notes:** One branch resolver shared by check/apply/fallback; make the merge-vs-switch policy explicit config rather than implicit behaviour.

### `hermes update --force` / `--force-venv` (Windows guards)  `id: cli-f.update.force`
- **Surface:** CLI
- **Where:** `hermes update --force`, `hermes update --force-venv` (Windows-only semantics).
- **What it does:** `--force` proceeds even when another `hermes.exe` is detected. `--force-venv` mutates the venv even while other processes are running from its interpreter.
- **How it works:** `update_cmd.py:7925-7942` — when `_is_windows()` and not `--force`, `_detect_concurrent_hermes_instances(scripts_dir)` plus `_filter_non_gateway_concurrent_instances()` aborts with `_format_concurrent_instances_message(...)` and `sys.exit(2)`; pure-gateway instances are paused instead of aborting (`_pause_windows_gateways_for_update`). `update_cmd.py:7977+` — when `_is_windows()` and not `--force-venv`, `_detect_venv_python_processes()` runs the escalation ladder described in `cli-f.update` before dead-ending.
- **Inputs / options:** `--force`, `--force-venv` (both `store_true`).
- **Outputs / side effects:** With `--force`, expect `WinError 32` warnings. With `--force-venv`, a partial dependency sync is likely and can strand a half-updated install.
- **Config / env:** n/a.
- **Edge cases / guards:** `--force` explicitly does NOT bypass the venv-process guard (the help says so). The desktop bootstrap updater passes `--force` only to skip the shim guard.
- **Rebuild notes:** On Windows, never mutate files an interpreter still maps; detect holders by module path, not by name.

### Update lock (`.hermes-update-in-progress`)  `id: cli-f.update.lock`
- **Surface:** CLI / Core
- **Where:** Not a flag — the file `<HERMES_HOME>/.hermes-update-in-progress`, shared by `hermes update`, the dashboard Update button, the Tauri `hermes-setup --update` flow and the Electron desktop (`apps/desktop/electron/update-marker.ts`).
- **What it does:** Guarantees that at most one updater mutates the checkout at a time, across CLI, dashboard and desktop.
- **How it works:** `hermes_cli/update_lock.py`. Body format is `"<pid>\n<started_at_unix>"`. `read_live_update()` (`:171`) treats a marker as live only when the pid is alive AND the marker is younger than `UPDATE_MARKER_MAX_AGE_SECONDS = 20 * 60`; a stale marker is removed by whoever notices it. Two hand-off escapes recognise an orchestrating parent: the env var `HANDOFF_PID_ENV` naming the parent's pid (which must ALSO be the live marker owner, so a forged value grants nothing) and `_is_ancestor_pid(pid)` (`:140`) — a live holder that is a process ancestor is our own orchestrator. `UpdateLock.acquire()/release()` (`:235,:265`) also work as a context manager.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Creates/removes the marker file. On a conflict prints `describe_holder(holder)` and exits `UPDATE_EXIT_CONCURRENT = 2`.
- **Config / env:** `HERMES_HOME` (marker location), the hand-off pid env var.
- **Edge cases / guards:** Byte-compatible with the Rust and Electron readers — the format may not change unilaterally. A crashed updater self-heals after 20 minutes.
- **Rebuild notes:** pid + start-time + age ceiling beats an OS advisory lock here because three languages read it. Better: store the start-time of the pid too, so pid reuse cannot fake liveness.

### Update receipts (`logs/update_receipts/`)  `id: cli-f.update.receipt`
- **Surface:** CLI / Core
- **Where:** `<HERMES_HOME>/logs/update_receipts/*.json`; surfaced by fleet tooling and `read_latest_receipt()`.
- **What it does:** Records what each update run discovered, did and skipped, so silent-failure classes become diagnosable from disk.
- **How it works:** `hermes_cli/update_receipt.py`. `begin_update_receipt()` (`:155`) creates a module-singleton `UpdateReceipt`; `record_step(name, ok, detail)` (`:165`), `record_skip(name, reason)` (`:174`) and `record_gateway_restart(**kwargs)` (`:183`) append to it; `finalize_update_receipt(outcome, fleet, stop_reason)` (`:192`) stamps `outcome` ∈ {`success`, `partial`, `failed`, `refused`}, `finished_at`, and `post_update = build_info.get_code_identity(refresh=True)`, then writes the JSON and prunes to `_RECEIPT_KEEP = 20` per profile home (`_prune_old_receipts`, `:271`). `finalize_pending_update_receipt(code, reason)` (`:235`) is the command-boundary safety net for the many `sys.exit` paths — exactly-once by construction (the singleton is popped first). `collect_fleet_versions()` (`:303`) and `print_fleet_version_matrix()` (`:461`) render the cross-profile version matrix.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One JSON file per update run under `<HERMES_HOME>/logs/update_receipts/`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Every recorder swallows its own exceptions — a receipt failure never breaks an update. A refusal by the admission contract also writes a `refused` receipt so fleet tooling sees the blocked attempt.
- **Rebuild notes:** One append-only structured log per run, capped by count. Better: include the resolved dependency diff so "why did this break" is answerable offline.

### Update admission contract (image/package-managed refusal)  `id: cli-f.update.admission`
- **Surface:** CLI / Core
- **Where:** Runs inside `hermes update` and `hermes update --check`, and behind the dashboard update endpoint.
- **What it does:** Refuses an in-place update on installs that are managed by an image or a package manager, and tells the user the real update command.
- **How it works:** `hermes_cli/update_contract.py:40 evaluate_update_admission(project_root)` layers: (1) the baked provenance marker `/etc/hermes/image-provenance.json` read by `hermes_cli/image_provenance.read_image_provenance()` — authoritative, and FAIL-CLOSED: a present-but-malformed marker still refuses (`code="image-marker-invalid"`); (2) `detect_install_method()` heuristics for docker/nix/apt. Returns an `UpdateRefusal {code, message, update_command}` where `code ∈ {image-marker, image-marker-invalid, docker, nix, apt}`. `record_refusal_receipt(refusal)` (`:116`) persists it. CLI surfaces print `refusal.message` and `sys.exit(2)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** stdout message + a `refused` update receipt; exit code 2 (distinct from exit 1 errors).
- **Config / env:** `/etc/hermes/image-provenance.json`.
- **Edge cases / guards:** `--plan` deliberately runs BEFORE this gate so an image-managed install still gets the full plan (which reports "not updatable in place" and the right mechanism).
- **Rebuild notes:** A build-time provenance marker beats runtime sniffing; keep the heuristics only as a fallback for older images.

---

## 6. `hermes uninstall`

### `hermes uninstall`  `id: cli-f.uninstall`
- **Surface:** CLI
- **Where:** `hermes uninstall [-h] [--full] [--gui] [--gui-summary] [--yes] [--dry-run]`. Root help `uninstall           Uninstall Hermes Agent`; description `Remove Hermes Agent from your system. Can keep configs/data for reinstall.`
- **What it does:** Removes the Hermes code checkout, its PATH entries, its wrapper scripts and services, and — with `--full` — the whole `HERMES_HOME` data directory.
- **How it works:** Parser `hermes_cli/subcommands/uninstall.py:12-46 build_uninstall_parser` (`set_defaults(func=cmd_uninstall)`). Handler `main.py:5995 cmd_uninstall` dispatches: `--gui-summary` (before any TTY gate) → `gui_uninstall.gui_install_summary()` printed as JSON; `--gui` → `_require_tty("uninstall --gui")` unless `--yes`, then `uninstall.run_gui_uninstall(args)`; otherwise `_require_tty("uninstall")` unless `--yes`, then `uninstall.run_uninstall(args)`.
  Interactive flow (`hermes_cli/uninstall.py:650 run_uninstall`): prints the banner box `│            ⚕ Hermes Agent Uninstaller                  │`, then `Current Installation:` with `  Code:    <project_root>`, `  Config:  <home>/config.yaml`, `  Secrets: <home>/.env`, `  Data:    <home>/cron/, <home>/sessions/, <home>/logs/`; then `Other profiles detected:` with one `  • <name>[ (gateway running)]: <path>` line each; then `Uninstall Options:` with `  1) Keep data - Remove code only, keep configs/sessions/logs` (`     (Recommended - you can reinstall later with your settings intact)`), `  2) Full uninstall - Remove everything including all data` (`     (Warning: This deletes all configs, sessions, and logs permanently)`) and `  3) Cancel - Don't uninstall`; prompt `Select option [1/2/3]: `. Choice `3`/`c`/`cancel`/`q`/`quit`/`n`/`no` → `Uninstall cancelled.`. On `2` with named profiles it asks `Also stop and remove these N profile(s)? [y/N]: `. Final gate `Type 'yes' to confirm: `.
  Destructive sequence (`uninstall.py:822 _perform_uninstall`): 1 stop/remove gateway service + standalone processes (`uninstall_gateway_service()`); 2 strip PATH from `~/.bashrc`, `~/.bash_profile`, `~/.profile`, `~/.zshrc`, `~/.zprofile` (`find_shell_configs`, `:33`) and, on Windows, from the User-scope registry PATH (markers `<root>\hermes-agent`, `<root>\git`, `<root>\node`, `<root>\venv`, plus `<root>\bin` only on a full default-root wipe — `_hermes_path_markers`, `:339`) and delete the User env vars `HERMES_HOME`, `HERMES_GIT_BASH_PATH` (`remove_hermes_env_vars_windows`, `:405`); 3 remove the wrapper scripts `~/.local/bin/{hermes,hermes-acp,hermes-agent}` and `/usr/local/bin/{hermes,hermes-acp,hermes-agent}` (only when the file body contains `hermes_cli` or `hermes-agent`); 3a Windows launchers in the managed bin dir (`remove_windows_bin_launchers`, `:447` — a locked running launcher is renamed aside with a non-executable suffix); 3b Hermes-managed `node`/`npm`/`npx` symlinks in `~/.local/bin`, `/usr/local/bin` (Linux root FHS) and `$PREFIX/bin` (Termux), only when they resolve into `<home>/node` (`remove_node_symlinks`, `:151`); 3c `gui_uninstall.uninstall_gui(home)`; 4 `shutil.rmtree(project_root)`; 4b on Windows `remove_portable_tooling_windows` deletes `<home>/git`, `<home>/node`, `<home>/gateway-service`; 5 on `--full` optionally `_uninstall_profile(p)` per named profile then `shutil.rmtree(hermes_home)`.
- **Inputs / options:** `-h, --help`; `--full`; `--gui`; `--gui-summary`; `--yes` / `-y`; `--dry-run`. Interactive inputs: `Select option [1/2/3]: `, `Also stop and remove these N profile(s)? [y/N]: `, `Type 'yes' to confirm: `.
- **Outputs / side effects:** Deletes the code checkout and (on `--full`) `HERMES_HOME`; edits shell rc files and the Windows registry; stops services. Ends with the box `│              ✓ Uninstall Complete!                      │` and, in keep-data mode, `Your configuration and data have been preserved:` + the reinstall one-liner (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash` or `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`), then `Reload your shell to complete the process:` / `  source ~/.bashrc  # or ~/.zshrc` (POSIX) or `Open a new terminal (PowerShell / Windows Terminal) to pick up` / `the updated User PATH and environment variables.` (Windows), then `Thank you for using Hermes Agent! ⚕`.
- **Config / env:** `HERMES_HOME` selects what is wiped. `PREFIX` (Termux) affects the node-symlink sweep.
- **Edge cases / guards:** Without `--yes`, ANY invocation (including `--dry-run`) requires a TTY — verified live: `hermes uninstall --dry-run` through a pipe prints `Error: 'hermes uninstall' requires an interactive terminal.` / `It cannot be run through a pipe or non-interactive subprocess.` / `Run it directly in your terminal instead.` Named profiles are never auto-removed on the `--yes` path (destructive default avoided). Real user binaries are never deleted: wrappers must contain the Hermes marker, node links must be symlinks resolving into the Hermes node dir.
- **Rebuild notes:** Keep an explicit manifest of everything the installer created (paths, PATH entries, env vars, services) and undo exactly that list. A better version would write that manifest at install time instead of re-deriving it heuristically at uninstall time.

### `hermes uninstall --full`  `id: cli-f.uninstall.full`
- **Surface:** CLI
- **Where:** `hermes uninstall --full` — help `Full uninstall - remove everything including configs and data`.
- **What it does:** Selects the "remove everything" mode: the code checkout AND the whole `HERMES_HOME` (configs, API keys, sessions, cron jobs, logs).
- **How it works:** `uninstall.py:684 full_uninstall = bool(getattr(args, "full", False))` on the `--yes` path; interactively it is option `2`. In `_perform_uninstall` step 5, `shutil.rmtree(hermes_home)` runs, and (only when the user opted in interactively) `_uninstall_profile(p)` (`:528`) runs first for each named profile — shelling out to `python -m hermes_cli.main --profile <name> gateway stop` then `gateway uninstall` (60 s timeout each), unlinking `alias_path`, and rmtree-ing the profile home.
- **Inputs / options:** `--full` (`store_true`).
- **Outputs / side effects:** Irreversible data loss unless a backup exists. Warning text: `⚠️  WARNING: This will permanently delete ALL Hermes data!` / `   Including: configs, API keys, sessions, scheduled jobs, logs` / `   Plus N profile(s): …`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** With `--yes` the profile sweep is skipped (`remove_profiles=False`) — an unattended full uninstall never silently deletes sibling profiles.
- **Rebuild notes:** Two-stage confirmation (mode choice + typed `yes`) for anything that deletes user data.

### `hermes uninstall --gui`  `id: cli-f.uninstall.gui`
- **Surface:** CLI
- **Where:** `hermes uninstall --gui` — help `Uninstall only the desktop Chat GUI, leaving the agent intact`.
- **What it does:** Removes the Electron desktop app's build artifacts, packaged bundle and Electron `userData` directory, leaving the Python agent, config, sessions and `.env` untouched.
- **How it works:** `uninstall.py:578 run_gui_uninstall`. Prints the box `│         ⚕ Hermes Chat GUI Uninstaller                  │`. If `gui_install_summary()["gui_installed"]` is false: `No Hermes Chat GUI installation was found.` + `  Checked: <home>, and the standard app locations for this OS.` Otherwise prints `This removes the Chat GUI only. The Hermes agent stays installed.`, a `Will remove:` list (each source artifact, each packaged path, and `  • <userdata_dir>  (desktop app data)`), a `Kept intact:` block (`  • The Hermes agent at <home>/hermes-agent`, `  • Your config, sessions, and secrets under <home>`) when `agent_is_installed()`, and gates on `Type 'yes' to remove the Chat GUI: ` unless `--yes`. Then `gui_uninstall.uninstall_gui(home)` (`gui_uninstall.py:241`) removes, in order: source-built artifacts `apps/desktop/dist`, `apps/desktop/release`, `apps/desktop/node_modules`, `<agent_root>/node_modules`, `<home>/desktop-build-stamp.json` (`source_built_gui_artifacts`, `:90`); packaged app paths per OS (`packaged_gui_app_paths`, `:111`) — macOS `/Applications/Hermes.app` and `~/Applications/Hermes.app`; Windows `%LOCALAPPDATA%\Programs\Hermes`, `%LOCALAPPDATA%\hermes-desktop`, `%ProgramFiles%\Hermes`; Linux the `.desktop` entry from `linux_desktop_entry.desktop_entry_path()`, `<XDG_DATA_HOME>/applications/Hermes.desktop`, and the hicolor icons `scalable/apps/hermes.png`, `256x256/apps/hermes.png`, `512x512/apps/hermes.png`, `1024x1024/apps/hermes.png`; then the Electron `userData` dir (`desktop_userdata_dir`, `:70` — macOS `~/Library/Application Support/Hermes`, Windows `%APPDATA%\Hermes`, Linux `$XDG_CONFIG_HOME/Hermes` or `~/.config/Hermes`).
- **Inputs / options:** `--gui` (`store_true`); combines with `--yes`.
- **Outputs / side effects:** Log lines `→ Removing built GUI artifacts (renderer, release, node_modules)...`, `→ Removing installed desktop app...`, `No packaged desktop app found in standard locations`, `→ Removing desktop app data (Electron userData)...`, `No desktop GUI artifacts found to remove`; on Linux it refreshes the application-menu cache (`✓ Refreshed the application menu cache (<tool>)`) and prints the deb/rpm/AppImage hint. Closing box `│            ✓ Chat GUI Uninstalled!                      │` then `The Hermes agent is still installed. Run 'hermes' to use the CLI,` / `or 'hermes uninstall' to remove the agent too.`
- **Config / env:** `HERMES_HOME`, `APPDATA`, `LOCALAPPDATA`, `ProgramFiles`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`.
- **Edge cases / guards:** Never touches `hermes-agent/hermes_cli`, `venv/`, or anything else under `HERMES_HOME`. deb/rpm installs under `/usr` are reported, not force-removed.
- **Rebuild notes:** Split "app artifacts" from "user data" by directory ownership, and refuse to delete anything outside the two known trees.

### `hermes uninstall --gui-summary`  `id: cli-f.uninstall.gui-summary`
- **Surface:** CLI
- **Where:** `hermes uninstall --gui-summary` — help `Print a JSON summary of installed GUI/agent artifacts and exit (used by the desktop app to gate uninstall options)`.
- **What it does:** Prints a machine-readable snapshot of what is installed so the desktop app can enable/disable its uninstall options.
- **How it works:** `main.py:5999-6003` runs BEFORE any TTY gate (it is called from a non-interactive child). `gui_uninstall.gui_install_summary(home)` (`:197`) returns `{hermes_home, agent_installed, gui_installed, source_built_artifacts[], packaged_app_paths[], userdata_dir, userdata_exists, platform}` — all JSON primitives so Electron can forward it over IPC.
- **Inputs / options:** `--gui-summary` (`store_true`).
- **Outputs / side effects:** One JSON line on stdout, exit 0. Live example on this checkout: `{"hermes_home": "…/hermes_home", "agent_installed": false, "gui_installed": false, "source_built_artifacts": [], "packaged_app_paths": [], "userdata_dir": "/root/.config/Hermes", "userdata_exists": false, "platform": "linux"}`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `agent_installed` is true when either `<home>/hermes-agent/hermes_cli` is a directory OR `<home>/hermes-agent/venv|.venv` exists (`agent_is_installed`, `:167`).
- **Rebuild notes:** Any destructive UI should be driven by a probe endpoint like this rather than by guessing on the client.

### `hermes uninstall --dry-run`  `id: cli-f.uninstall.dry-run`
- **Surface:** CLI
- **Where:** `hermes uninstall --dry-run` — help `Print what uninstall would remove without changing anything`.
- **What it does:** Prints the uninstall plan without stopping services, editing files, or deleting anything.
- **How it works:** `uninstall.py:662-668` returns early into `_print_uninstall_dry_run` (`:798`).
- **Inputs / options:** `--dry-run` (`store_true`); combines with `--full` to see the full-wipe plan.
- **Outputs / side effects:** stdout only. Exact lines: `Dry run: no files, services, or environment entries will be changed.`, `Would inspect/remove:`, `  • Gateway services and standalone gateway processes`, `  • Hermes PATH entries from shell configs / Windows User PATH`, `  • Hermes wrapper scripts and Hermes-managed node/npm/npx symlinks`, `  • Desktop Chat GUI artifacts`, `  • Code checkout: <project_root>`; then either `  • Hermes config/data: <home>` (with `  • Named profiles (interactive uninstall asks before removing):` and `    - <name>: <path>` lines when the home is the default root) or `  • Keep Hermes config/data: <home>`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Still requires a TTY unless `--yes` is also passed — the TTY gate in `cmd_uninstall` runs before `run_uninstall` reaches the dry-run branch.
- **Rebuild notes:** Put the dry-run branch BEFORE the interactivity gate so it is usable from scripts.

### `hermes uninstall --yes` / `-y`  `id: cli-f.uninstall.yes`
- **Surface:** CLI
- **Where:** `hermes uninstall --yes`, `hermes uninstall -y`.
- **What it does:** Skips every confirmation prompt and the TTY requirement; `--full` then selects a full wipe, otherwise keep-data.
- **How it works:** `main.py:6008-6017` — `_require_tty` is only called when `--yes` is absent. `uninstall.py:683-693` takes the non-interactive fast path with `remove_profiles=False`. This is the path the desktop app's detached cleanup script uses for its lite/full modes.
- **Inputs / options:** `--yes`, `-y`.
- **Outputs / side effects:** The full destructive sequence, unattended.
- **Config / env:** n/a.
- **Edge cases / guards:** Named profiles are deliberately NOT removed here.
- **Rebuild notes:** Non-interactive must never widen the blast radius relative to interactive.

### `python -m hermes_cli.uninstall --mode <gui|lite|full>`  `id: cli-f.uninstall.module-entry`
- **Surface:** CLI
- **Where:** `python -m hermes_cli.uninstall --mode gui|lite|full` (prog string `python -m hermes_cli.uninstall`).
- **What it does:** Runs the uninstall under an interpreter OUTSIDE the venv being deleted — the desktop app's uninstall path.
- **How it works:** `uninstall.py:1031 main(argv)`. Argparse with a single required `--mode` (`choices=["gui","lite","full"]`, help `gui = Chat GUI only; lite = GUI + agent, keep data; full = everything`). Builds `_UninstallArgs(mode=…)` (`:1013`) which sets `gui = mode=="gui"`, `full = mode=="full"`, `gui_summary=False`, `yes=True` (always non-interactive), then calls `run_gui_uninstall` or `run_uninstall`. The module imports only stdlib + `hermes_constants` + `hermes_cli.colors` (and lazily `hermes_cli.gui_uninstall`) so it runs under a bare system Python with no venv site-packages. The desktop launches it with the system Python and `PYTHONPATH=<agentRoot>`.
- **Inputs / options:** `--mode gui`, `--mode lite`, `--mode full` (required); `-h/--help`.
- **Outputs / side effects:** Same as the corresponding `hermes uninstall` mode; returns 0.
- **Config / env:** `PYTHONPATH`, `HERMES_HOME`.
- **Edge cases / guards:** Exists because on Windows a running `python.exe` inside the venv is mandatory-locked, so rmtree-ing the venv from its own interpreter half-fails.
- **Rebuild notes:** Any self-deleting installer needs a bootstrap interpreter outside the tree it deletes.

---

## 7. `hermes acp` — Agent Client Protocol server

### `hermes acp`  `id: cli-f.acp`
- **Surface:** CLI
- **Where:** `hermes acp [-h] [--accept-hooks] [--version] [--check] [--setup] [--setup-browser] [--yes]`. Root help `acp                 Run Hermes Agent as an ACP (Agent Client Protocol) server`; description `Start Hermes Agent in ACP mode for editor integration (VS Code, Zed, JetBrains)`. Also available as the console script `hermes-acp` and as `python -m acp_adapter.entry`.
- **What it does:** Runs Hermes as an ACP stdio server so an editor (Zed, VS Code, JetBrains) can drive it as its coding agent.
- **How it works:** Parser `hermes_cli/subcommands/acp.py:14-52 build_acp_parser` (adds the shared `--accept-hooks` flag via `_shared.add_accept_hooks_flag`, then `--version` → `dest="acp_version"`, `--check`, `--setup`, `--setup-browser`, `--yes`/`-y` → `dest="assume_yes"`; `set_defaults(func=cmd_acp)`). Handler `main.py:12916 cmd_acp` re-serialises those booleans into an argv list and calls `acp_adapter.entry.main(acp_argv)`. `acp_adapter/entry.py:220 main` parses with its own parser (prog `hermes-acp`), handles `--version`/`--check`/`--setup`/`--setup-browser` and returns; otherwise `_setup_logging()` routes ALL logging to stderr with a `RedactingFormatter` (`%(asctime)s [%(levelname)s] %(name)s: %(message)s`, datefmt `%Y-%m-%d %H:%M:%S`) so stdout stays clean for the JSON-RPC transport, quiets `httpx`/`httpcore`/`openai` to WARNING, and installs `_BenignProbeMethodFilter` which swallows `Background task failed` tracebacks caused by unknown liveness probes `ping`, `health`, `healthcheck` (JSON-RPC `-32601`) while leaving every other background error visible. `_load_env()` loads `<HERMES_HOME>/.env` via `hermes_cli.env_loader.load_hermes_dotenv`. The project root is prepended to `sys.path`; MCP discovery is started in a background daemon thread (`hermes_cli.mcp_startup.start_background_mcp_discovery(thread_name="acp-mcp-discovery")`) unless `HERMES_ACP_SKIP_CONFIGURED_MCP=1`; then `asyncio.run(acp.run_agent(HermesACPAgent(), use_unstable_protocol=True))`. `hermes_bootstrap` is imported first (UTF-8 stdio on Windows) and `hermes_bootstrap.harden_import_path()` stops a `utils/`, `proxy/` or `ui/` package in the launch directory from shadowing Hermes modules.
- **Inputs / options:** `-h, --help`; `--accept-hooks`; `--version`; `--check`; `--setup`; `--setup-browser`; `--yes` / `-y`. Adapter modules: `acp_adapter/{server,session,tools,events,permissions,edit_approval,provenance,auth}.py`.
- **Outputs / side effects:** Speaks ACP JSON-RPC on stdout, logs on stderr; connects MCP servers in the background.
- **Config / env:** `HERMES_HOME`, `HERMES_ACCEPT_HOOKS`, `hooks_auto_accept`, `HERMES_ACP_SKIP_CONFIGURED_MCP`.
- **Edge cases / guards:** Missing optional deps → `ACP dependencies not installed.` + `Install them with:  pip install -e '.[acp]'` on stderr, `sys.exit(1)` (from `cmd_acp`'s `except ImportError`). A `KeyboardInterrupt` logs `Shutting down (KeyboardInterrupt)`; any other exception logs `ACP agent crashed` and exits 1.
- **Rebuild notes:** Keep stdout exclusively for the protocol; every human message goes to stderr. A better version would advertise capability negotiation so an editor can discover tool/permission support without probing.

### `hermes acp --version`  `id: cli-f.acp.version`
- **Surface:** CLI
- **Where:** `hermes acp --version` (argparse `dest="acp_version"`; help `Print Hermes ACP version and exit`).
- **What it does:** Prints the Hermes version string and exits.
- **How it works:** `acp_adapter/entry.py:223-225` → `_print_version()` (`:150`) prints `hermes_cli.__version__`.
- **Inputs / options:** `--version`.
- **Outputs / side effects:** One line on stdout. Live: `0.21.0`, exit 0.
- **Config / env:** n/a.
- **Edge cases / guards:** Distinct from the root `hermes --version` (`dest` is renamed so the two never collide in the same namespace).
- **Rebuild notes:** n/a.

### `hermes acp --check`  `id: cli-f.acp.check`
- **Surface:** CLI
- **Where:** `hermes acp --check` — help `Verify ACP dependencies and adapter imports, then exit`.
- **What it does:** Imports the `acp` package and `acp_adapter.server.HermesACPAgent` to prove the ACP extra is installed and the adapter is importable.
- **How it works:** `acp_adapter/entry.py:155-159 _run_check()`; on success prints `Hermes ACP check OK`.
- **Inputs / options:** `--check`.
- **Outputs / side effects:** stdout line or the ImportError message from `cmd_acp`. Live on a checkout without the extra: `ACP dependencies not installed.` / `Install them with:  pip install -e '.[acp]'`.
- **Config / env:** n/a.
- **Edge cases / guards:** The ImportError is caught in `cmd_acp` (not in `_run_check`), so the friendly message wins over a traceback.
- **Rebuild notes:** A `--check` that only imports is cheap and catches 90% of integration failures.

### `hermes acp --setup`  `id: cli-f.acp.setup`
- **Surface:** CLI
- **Where:** `hermes acp --setup` — help `Run interactive Hermes provider/model setup for ACP terminal auth`.
- **What it does:** Runs the normal `hermes model` provider/model picker so an editor-launched ACP server has credentials, then offers to install browser tools.
- **How it works:** `acp_adapter/entry.py:162-186 _run_setup()` temporarily rewrites `sys.argv` to `["hermes", "model"]` and calls `hermes_cli.main.main()`, restoring argv in a `finally`. Afterwards, when stdin is a TTY, it prompts `Install browser tools? Downloads agent-browser (npm) and optionally Playwright Chromium (~400 MB). [y/N] ` and on `y`/`yes` calls `_run_setup_browser(assume_yes=False)`.
- **Inputs / options:** `--setup`; the follow-up y/N prompt.
- **Outputs / side effects:** Writes provider/model settings to `config.yaml`/`.env` via the model command; may download Node + Chromium.
- **Config / env:** whatever `hermes model` writes.
- **Edge cases / guards:** The follow-up prompt is skipped silently when stdin is not a TTY.
- **Rebuild notes:** Reuse the main setup flow rather than a second, divergent one.

### `hermes acp --setup-browser`  `id: cli-f.acp.setup-browser`
- **Surface:** CLI
- **Where:** `hermes acp --setup-browser [-y]` — help `Install agent-browser + Playwright Chromium into ~/.hermes/node/ for browser tool support (idempotent).`
- **What it does:** Bootstraps the Node runtime and the browser tooling Hermes' browser tools need, into `~/.hermes/node/`.
- **How it works:** `acp_adapter/entry.py:189-217 _run_setup_browser(assume_yes)` calls `hermes_cli.dep_ensure.ensure_dependency("node", interactive=not assume_yes)` then `ensure_dependency("browser", interactive=not assume_yes)`, which route through `install.sh` / `install.ps1 --ensure` (shared with the runtime lazy installer). Returns 0/1; a non-zero return makes `main()` `sys.exit(rc)`.
- **Inputs / options:** `--setup-browser`; `--yes` / `-y` to skip the ~400 MB Chromium download confirmation.
- **Outputs / side effects:** Downloads and installs Node and Playwright Chromium under `~/.hermes/node/`. Failure messages on stderr: `Node.js installation failed — cannot proceed with browser tools.`, `Browser tools installation failed.`, `Browser bootstrap failed: <err>`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Idempotent — safe to re-run.
- **Rebuild notes:** Route optional heavy dependencies through one `ensure_dependency` shim shared by the CLI and the runtime.

### `hermes acp --yes` / `-y`  `id: cli-f.acp.yes`
- **Surface:** CLI
- **Where:** `hermes acp --yes`, `hermes acp -y` (argparse `dest="assume_yes"`).
- **What it does:** Accepts all prompts — currently used by `--setup-browser` to skip the ~400 MB Chromium download confirmation.
- **How it works:** `subcommands/acp.py:44-51`; forwarded as `--yes` in `cmd_acp`'s reconstructed argv (`main.py:12930-12931`), then read as `args.assume_yes` in `entry.main`.
- **Inputs / options:** `--yes`, `-y`.
- **Outputs / side effects:** none of its own.
- **Config / env:** n/a.
- **Edge cases / guards:** Only meaningful alongside `--setup-browser` (and `--setup`'s follow-up).
- **Rebuild notes:** n/a.

### `hermes acp --accept-hooks`  `id: cli-f.acp.accept-hooks`
- **Surface:** CLI
- **Where:** `hermes acp --accept-hooks` — help `Auto-approve unseen shell hooks without a TTY prompt (equivalent to HERMES_ACCEPT_HOOKS=1 / hooks_auto_accept: true).`
- **What it does:** Pre-approves shell hooks the agent has not seen before, so an editor-hosted ACP session never blocks on a TTY prompt that has no terminal.
- **How it works:** Added by the shared helper `hermes_cli/subcommands/_shared.py add_accept_hooks_flag(acp_parser)` (`subcommands/acp.py:11,21`), the same flag the chat/gateway parsers use.
- **Inputs / options:** `--accept-hooks` (`store_true`).
- **Outputs / side effects:** Unseen shell hooks run without an approval prompt.
- **Config / env:** `HERMES_ACCEPT_HOOKS=1`; config `hooks_auto_accept: true`.
- **Edge cases / guards:** This is an approval bypass — it should only be used where the editor itself is the trust boundary.
- **Rebuild notes:** Any headless surface needs an explicit, auditable auto-approve switch rather than silently degrading approvals.

---

## 8. `hermes profile` — multiple isolated Hermes instances

### Profile command group / bare `hermes profile`  `id: cli-f.profile`
- **Surface:** CLI
- **Where:** `hermes profile [-h] {list,use,create,delete,describe,show,alias,rename,export,import,install,update,info} ...`. Root help `profile             Manage profiles — multiple isolated Hermes instances`. Docs: `website/docs/reference/profile-commands.md:9`, `website/docs/user-guide/profiles.md`.
- **What it does:** Umbrella for creating and switching between isolated Hermes instances (each with its own `HERMES_HOME`: config, `.env`, SOUL.md, memories, sessions, skills, cron). With no sub-command it prints the active profile's status.
- **How it works:** Parser `hermes_cli/subcommands/profile.py:17-209 build_profile_parser` (`profile_subparsers = profile_parser.add_subparsers(dest="profile_action")`, `profile_parser.set_defaults(func=cmd_profile)`). Handler `hermes_cli/main.py:11019 cmd_profile` switches on `args.profile_action`; `None` runs the bare-status branch (`:11036-11076`) which reads `get_active_profile_name()`, `display_hermes_home()` and the matching `ProfileInfo` from `list_profiles()`.
  Storage model (`hermes_cli/profiles.py`): named profiles live at `<root>/profiles/<id>/` where `<root>` = `_get_default_hermes_home()` (`:296` — `~/.hermes`, or the Docker/custom `HERMES_HOME` root with a trailing `profiles/<name>` stripped); the `default` profile IS the root itself. Sticky selection is the file `<root>/active_profile` (`_get_active_profile_path`, `:307`). Wrapper aliases live in `~/.local/bin` (`_get_wrapper_dir`, `:312`). Per-profile presentation metadata is `<profile>/profile.yaml`. Every new profile bootstraps the directories `memories`, `sessions`, `skills`, `skins`, `logs`, `plans`, `workspace`, `cron`, `home` (`_PROFILE_DIRS`, `:55`).
- **Inputs / options:** `-h, --help` and the 13 sub-commands `list`, `use`, `create`, `delete`, `describe`, `show`, `alias`, `rename`, `export`, `import`, `install`, `update`, `info`.
- **Outputs / side effects:** Bare form prints (live-verified): `` (blank) ``, `Active profile: default`, `Path:           <HERMES_HOME>`, optionally `Model:          <model> (<provider>)`, `Gateway:        running|stopped`, `Skills:         N installed`, optionally `Alias:          <alias> → hermes -p <name>`, then a blank line.
- **Config / env:** `HERMES_HOME` (overrides everything), `active_profile` file.
- **Edge cases / guards:** `get_active_profile_name()` (`profiles.py:2087`) returns `default` when `HERMES_HOME` resolves to the root, the profile id when it resolves to `<root>/profiles/<id>`, and the literal string `custom` for any other path.
- **Rebuild notes:** One directory per profile + one sticky pointer file + one wrapper script per alias. A better version would namespace running services per profile automatically instead of relying on per-profile unit generation.

### `hermes profile list`  `id: cli-f.profile.list`
- **Surface:** CLI
- **Where:** `hermes profile list [-h]` — sub-help `List all profiles`.
- **What it does:** Prints a table of every profile with its model, gateway state, alias and distribution, marking the active one.
- **How it works:** `main.py:11077-11114`. `profiles.list_profiles()` (`profiles.py:1029`) builds one `ProfileInfo` for the default home plus one per valid directory under `<root>/profiles/` (skipping non-dirs, the literal name `default`, names failing `_PROFILE_ID_RE = ^[a-z0-9][a-z0-9_-]{0,63}$`, and tombstoned dirs via `named_profile_is_deleted`). Each entry reads `_read_config_model` (`:753`), `_check_gateway_running` (`:808`), `_count_skills` (`:880`, cached 30 s by a `skills/` mtime signature), `_read_distribution_meta` (`:728`), `read_profile_meta` (`:924`) and the alias from `build_alias_map()` (`:639`) — a single pass over `~/.local/bin` reading at most `_WRAPPER_READ_LIMIT = 8192` bytes per candidate and skipping binaries, replacing the old O(N*M) per-profile scan.
- **Inputs / options:** `-h, --help` only.
- **Outputs / side effects:** stdout table. Header (live-verified): `` ` Profile          Model                        Gateway      Alias        Distribution` `` then a rule of box-drawing dashes; rows are `<marker><name:<15} {model:<28} {gw:<12} {alias:<12} {dist}` where marker is `" ◆"` for the active profile and `"  "` otherwise, model is truncated to 26 chars and falls back to `—`, gateway is `running`/`stopped`, alias is `—` for the default profile or when no wrapper exists, and distribution is `<name>@<version|?>` truncated to 30 chars or `—`. Empty store prints `No profiles found.`
- **Config / env:** `HERMES_HOME`, `~/.local/bin` for aliases.
- **Edge cases / guards:** `format_profile_label(name, display_name)` (`:995`) renders `display_name (canonical_id)` when a display name is set and differs from the id, else the bare id. A corrupt `profile.yaml` never breaks the listing (`read_profile_meta` returns empty defaults on any exception).
- **Rebuild notes:** Build the alias reverse-map once; cache skill counts by directory mtime.

### `hermes profile use <profile_name>`  `id: cli-f.profile.use`
- **Surface:** CLI
- **Where:** `hermes profile use [-h] profile_name` — sub-help `Set sticky default profile`; positional help `Profile name (or 'default')`.
- **What it does:** Sets the profile every later `hermes` invocation uses by default, until changed.
- **How it works:** `main.py:11116-11126` → `profiles.set_active_profile(name)` (`profiles.py:2062`): normalises, validates, refuses a non-existent profile, then atomically writes `<name>\n` to `<root>/active_profile` via a `.tmp` file + `replace()`; the special value `default` UNLINKS the file instead.
- **Inputs / options:** positional `profile_name`; `-h, --help`.
- **Outputs / side effects:** `Switched to: default (~/.hermes)` or `Switched to: <name>`. On failure: `Error: <msg>` and `sys.exit(1)`; the not-found message is `Profile '<n>' does not exist. Create it with: hermes profile create <n>`.
- **Config / env:** writes `<root>/active_profile`.
- **Edge cases / guards:** A gateway-supervised child ignores the sticky file (see `cli-a.opt-profile`); `-p` on the command line always wins.
- **Rebuild notes:** A single-line pointer file with atomic replace; delete-to-reset is simpler than storing the default name.

### `hermes profile create <profile_name>`  `id: cli-f.profile.create`
- **Surface:** CLI
- **Where:** `hermes profile create [-h] [--clone] [--clone-all] [--clone-from SOURCE] [--no-alias] [--no-skills] [--description DESCRIPTION] profile_name`. Positional help `Profile name (lowercase, alphanumeric)`.
- **What it does:** Creates a new isolated profile directory, optionally cloning config/skills (or everything) from another profile, seeds bundled skills, and creates a shell wrapper alias.
- **How it works:** `main.py:11128-11235` → `profiles.create_profile(...)` (`profiles.py:1177`). Sequence: reject `--no-skills` combined with any clone flag (`--no-skills is mutually exclusive with --clone / --clone-from / --clone-all (cloning explicitly copies skills from the source profile).`); `normalize_profile_name` + `validate_profile_name`; refuse the name `default`; refuse an existing directory (a tombstoned empty shell without `config.yaml`/`.env` is rmtree'd and replaced, otherwise `FileExistsError`); resolve the clone source (`--clone-from` or the active profile). `--clone-all` does `shutil.copytree(symlinks=True, ignore=_clone_all_copytree_ignore(source))` then strips `_CLONE_ALL_STRIP = ["gateway.pid","gateway_state.json","processes.json"]`; the ignore filter drops `_CLONE_ALL_HISTORY_EXCLUDE_ROOT = {state.db, state.db-wal, state.db-shm, sessions, backups, state-snapshots, checkpoints}` always and, when the source is the default root, also `_CLONE_ALL_DEFAULT_EXCLUDE_ROOT = {hermes-agent, .worktrees, profiles, bin, node_modules}`. Otherwise it mkdirs `_PROFILE_DIRS`, calls `_seed_model_config` for a source-less create, and for a clone copies `_CLONE_CONFIG_FILES = ["config.yaml", ".env", "SOUL.md"]` (chmod `.env` to `0o600`), copytrees `skills/`, and copies `_CLONE_SUBDIR_FILES = ["memories/MEMORY.md", "memories/USER.md"]`. Then it always seeds an owner-only `.env` header when absent, writes `DEFAULT_SOUL_MD` to `SOUL.md` when absent, writes the `.no-bundled-skills` marker for `--no-skills`, runs `_migrate_profile_config_if_outdated` (unless `--clone-all`), persists `--description` into `profile.yaml`, and calls `_maybe_register_gateway_service(canon)` (s6 inside a container; no-op on host). Back in `cmd_profile`: Honcho config is cloned when cloning (`plugins.memory.honcho.cli.clone_honcho_for_profile`); for fresh profiles `seed_profile_skills(profile_dir)` (`profiles.py:1380`) runs `tools.skills_sync.sync_skills` in a subprocess with `HERMES_HOME=<profile>` and a 60 s timeout; unless `--no-alias`, `check_alias_collision` then `create_wrapper_script`.
- **Inputs / options:** positional `profile_name`; `--clone` (`Copy config.yaml, .env, SOUL.md, and skills from active profile`); `--clone-all` (`Full copy of active profile (all state, excluding per-profile history)`); `--clone-from SOURCE` (`Source profile to clone from; implies --clone unless --clone-all is set`); `--no-alias` (`Skip wrapper script creation`); `--no-skills` (`Create an empty profile with no bundled skills (opts out of 'hermes update' skill sync)`); `--description DESCRIPTION`; `-h, --help`.
- **Outputs / side effects:** Creates `<root>/profiles/<name>/` with the nine bootstrap dirs, `.env` (0600), `SOUL.md`, optionally `profile.yaml` and `.no-bundled-skills`; creates `~/.local/bin/<name>` (or `<name>.bat`). Prints: `Profile '<name>' created at <dir>`; `Full copy from <source> (excluding session history, backups, and snapshots).` or `Cloned config, .env, SOUL.md, and skills from <source>.`; `Honcho config cloned (peer: <name>)`; `No bundled skills seeded (--no-skills). Delete .no-bundled-skills in the profile to opt back in.` / `<N> bundled skills synced.` / `⚠ Skills could not be seeded. Run '<name> update' to retry.`; `Wrapper created: <path>`; `⚠ Cannot create alias '<name>' — <collision>` with `  Choose a custom alias:  hermes profile alias <name> --name <custom>` and `  Or access via flag:     hermes -p <name> chat`; `⚠ <wrapper_dir> is not in your PATH.` + `  Add to your shell config (~/.bashrc or ~/.zshrc):` + `    export PATH="$HOME/.local/bin:$PATH"`; then `Next steps:` with `  <name> setup              Configure API keys and model`, `  <name> chat               Start chatting`, `  <name> gateway start      Start the messaging gateway`, and either `  Edit <dir>/.env for different API keys` + `  Edit <dir>/SOUL.md for different personality` or `  ⚠ This profile has no API keys yet. Run '<name> setup' first,` + `    or it will inherit keys from your shell environment.` + `  Edit <dir>/SOUL.md to customize personality`.
- **Config / env:** writes the new profile's `config.yaml`; `auxiliary.profile_describer` is only used by `describe --auto`.
- **Edge cases / guards:** Name must match `^[a-z0-9][a-z0-9_-]{0,63}$` and must not be in `_RESERVED_NAMES = {hermes, default, test, tmp, root, sudo}` (`validate_profile_name`, `profiles.py:339`). Alias collisions are also checked against `_HERMES_SUBCOMMANDS` (a 25-name frozenset: chat, model, gateway, setup, whatsapp, login, logout, status, cron, doctor, dump, config, pairing, skills, tools, mcp, sessions, insights, version, update, uninstall, profile, plugins, honcho, acp) and against any existing binary on PATH via `which`/`where` with a 5 s timeout — our own wrapper (body contains `hermes -p`) may be overwritten. `create_profile` errors (`ValueError`, `FileExistsError`, `FileNotFoundError`) print `Error: <msg>` and exit 1.
- **Rebuild notes:** Bootstrap dirs + copy an explicit allowlist; never recursive-copy the profiles root into a profile. A better version would hard-link unchanged skill files instead of copying them.

### `hermes profile delete <profile_name>`  `id: cli-f.profile.delete`
- **Surface:** CLI
- **Where:** `hermes profile delete [-h] [-y] profile_name` — sub-help `Delete a profile`; positional help `Profile to delete`.
- **What it does:** Stops the profile's gateway and other backends, removes its service registration and alias wrapper, and deletes its directory.
- **How it works:** `main.py:11237-11245` → `profiles.delete_profile(name, yes)` (`profiles.py:1693`). Refuses `default` (`Cannot delete the default profile (~/.hermes).\nTo remove everything, use: hermes uninstall`). Prints the profile summary, then a confirmation `Type '<canon>' to confirm: ` unless `-y`. Then: 1 `_cleanup_gateway_service(canon, dir)` (disable systemd/launchd first so nothing auto-restarts); 1b `_maybe_unregister_gateway_service(canon)` (removes `/run/service/gateway-<profile>/` inside a container); 2 `_stop_gateway_process(dir)`; 2b `_stop_profile_backends(canon, dir)` — Desktop-spawned `serve`/`dashboard` processes bound to the profile that the `gateway.pid` file never names; tombstone via `mark_named_profile_deleted(dir)`; 2c release this process's holographic memory-store handles (`plugins.memory.holographic.store.MemoryStore.release_all_under`); 3 `remove_wrapper_script(canon)`; 4 `_rmtree_with_retry(dir, _make_writable)` where the handler chmods `+w` on the path AND its parent for `PermissionError` (NixOS read-only store copies) and supports both the 3.12+ `onexc` and the 3.11 `onerror` signatures; 5 reset `active_profile` to default when it pointed here.
- **Inputs / options:** positional `profile_name`; `-y, --yes` (`Skip confirmation prompt`); `-h, --help`.
- **Outputs / side effects:** Prints `Profile: <name>`, `Path:    <dir>`, optional `Model:`, `Skills:`, `Distribution:`/`Installed from:`, then `This will permanently delete:` with `  • All config, API keys, memories, sessions, skills, cron jobs` and (when a wrapper exists) `  • Command alias (<path>)`, plus `  ⚠ Gateway is running — it will be stopped.` Success lines: `✓ Released N memory-store connection(s) held by this process`, `✓ Removed <wrapper>`, `✓ Removed <dir>`, `✓ Active profile reset to default`, `Profile '<name>' deleted.` Failure: `⚠ Could not remove <dir>: <e>` then a raised `RuntimeError`. Cancelling prints `Cancelled.` and returns the path unchanged.
- **Config / env:** `active_profile`.
- **Edge cases / guards:** The tombstone is written BEFORE the rmtree so a stale `serve` process's logging mkdir cannot relist the name as a live profile. On Windows the Desktop's main `serve` process is deliberately not killed, so its open `memory_store.db` handles are released in-process instead (WinError 32).
- **Rebuild notes:** Stop supervisors before processes before files; tombstone before deleting so concurrent writers cannot resurrect the tree.

### `hermes profile describe [profile_name]`  `id: cli-f.profile.describe`
- **Surface:** CLI
- **Where:** `hermes profile describe [-h] [--text TEXT] [--auto] [--overwrite] [--all] [profile_name]` — sub-help `Read or set a profile's description (used by the kanban orchestrator)`; positional help `Profile to describe (omit + use --all --auto to sweep)`.
- **What it does:** Reads, sets, or LLM-generates the one-to-two-sentence description the kanban decomposer uses to route tasks to a profile by role rather than by name.
- **How it works:** `main.py:11247-11362`. Validation first: `--all` without `--auto` → `profile describe: --all requires --auto` (exit 2); `--all` with a name or `--text` → `profile describe: --all is mutually exclusive with a profile name / --text` (exit 2); no name and no `--all` → `profile describe: profile name is required (or --all --auto)` (exit 2); `--text` with `--auto` → `profile describe: --text is mutually exclusive with --auto` (exit 2). Read path (name, no `--text`, no `--auto`): resolves the profile dir (`default` maps to `get_hermes_home()`), reads `profile.yaml` and prints `(no description set for '<n>')` or `[auto] <desc>` / `<desc>`; exit 0. Write path (`--text`): `write_profile_meta(dir, description=text, description_auto=False)` then `Description updated for '<n>'.`; exit 0. Auto path: `hermes_cli/profile_describer.py:156 describe_profile(target, overwrite=...)` — refuses to overwrite a user-authored description unless `--overwrite`; collects up to `MAX_SKILLS_FOR_PROMPT = 60` skill names from `<profile>/skills/**/SKILL.md` (formatted `category/skill` or bare `skill`, evenly SAMPLED not head-truncated when over the cap); calls `agent.auxiliary_client.call_llm(task="profile_describer", temperature=0.3, max_tokens=400, timeout=60)` with a fixed system prompt demanding `{"description": "..."}` JSON, ≤2 sentences, ≤280 characters, no invented capabilities, no meta-narration, no code fences; parses with `_extract_json_blob` (strips ``` fences, takes the outermost `{...}`) and falls back to the first paragraph of raw text truncated to 280 chars; writes back with `description_auto=True`. `--all` targets come from `list_describable_profiles(missing_only=True)` (`:277`).
- **Inputs / options:** optional positional `profile_name`; `--text TEXT`; `--auto`; `--overwrite`; `--all` (argparse `dest="all_missing"`); `-h, --help`.
- **Outputs / side effects:** Writes `description` / `description_auto` into `<profile>/profile.yaml` via `write_profile_meta` (`profiles.py:951`, atomic through `utils.atomic_yaml_write`). Per-target prints `Described '<n>': <description>` or, on stderr, `profile describe <n>: <reason>`. `--all` with nothing to do prints `All profiles already have descriptions.` (exit 0). Exit code: single target → 0 on success else 1; `--all` → 0 if at least one succeeded.
- **Config / env:** `auxiliary.profile_describer.*` (provider/model/base_url/extra_body/reasoning_effort/retries), routed through `call_llm` precisely so `extra_body` is not dropped.
- **Edge cases / guards:** `describe_profile` never raises for expected failures; the failure reasons are the literal strings `profile not found`, `cannot resolve profile dir: <exc>`, `profile already has a user-authored description (use --overwrite to replace)`, `auxiliary client unavailable`, `LLM error: <ExcType>`, `LLM returned an empty response`, `LLM response missing 'description' field`, `failed to write profile.yaml: <exc>`. Memory files are deliberately NOT read (privacy + role-not-biography).
- **Rebuild notes:** Skills are the strongest role signal; sample evenly so the description is not alphabetically biased. A better version would also diff recent tool usage.

### `hermes profile show <profile_name>`  `id: cli-f.profile.show`
- **Surface:** CLI
- **Where:** `hermes profile show [-h] profile_name` — sub-help `Show profile details`; positional help `Profile to show`.
- **What it does:** Prints one profile's path, model, gateway state, skill count, whether `.env`/`SOUL.md` exist, its distribution and its alias.
- **How it works:** `main.py:11364-11398`. `profile_exists(name)` gate (`Error: Profile '<n>' does not exist.`, exit 1), then `get_profile_dir`, `_read_config_model`, `_check_gateway_running`, `_count_skills`, `_read_distribution_meta`, `find_alias_for_profile` and `read_profile_meta`.
- **Inputs / options:** positional `profile_name`; `-h, --help`.
- **Outputs / side effects:** `Profile: <label>`, `Path:    <dir>`, optional `Model:   <model> (<provider>)`, `Gateway: running|stopped`, `Skills:  <n>`, `.env:    exists|not configured`, `SOUL.md: exists|not configured`, optional `Distribution: <name>@<ver>` + `Installed from: <src>` + `  (run 'hermes profile info <name>' for full manifest)`, optional `Alias:   <alias> → hermes -p <name>  (<wrapper path>)`.
- **Config / env:** reads the target profile's `config.yaml`.
- **Edge cases / guards:** On Windows the wrapper path is `<alias>.bat`.
- **Rebuild notes:** n/a.

### `hermes profile alias <profile_name>`  `id: cli-f.profile.alias`
- **Surface:** CLI
- **Where:** `hermes profile alias [-h] [--remove] [--name NAME] profile_name` — sub-help `Manage wrapper scripts`; positional help `Profile name`.
- **What it does:** Creates, renames or removes the shell wrapper that lets you type `<alias> chat` instead of `hermes -p <profile> chat`.
- **How it works:** `main.py:11400-11434`. Requires the profile to exist; `alias_name = --name or profile_name`; `validate_alias_name` (`profiles.py:369` — same `^[a-z0-9][a-z0-9_-]{0,63}$` regex, which is what stops a traversal value like `../../.bashrc` from escaping `~/.local/bin`). `--remove` → `remove_wrapper_script(alias)` (`:548`) which only unlinks a file whose body contains `hermes -p`. Otherwise `check_alias_collision(alias)` then `create_wrapper_script(alias, target=profile if custom_name else None)` (`:505`) — POSIX writes `#!/bin/sh\nexec <shutil.which("hermes") or "hermes"> -p <profile> "$@"\n` and chmods `+x` for user/group/other; Windows writes `@echo off\r\nhermes -p <profile> %*\r\n` to `<alias>.bat`.
- **Inputs / options:** positional `profile_name`; `--remove` (`Remove the wrapper script`); `--name NAME` (argparse `dest="alias_name"`, `Custom alias name (default: profile name)`); `-h, --help`.
- **Outputs / side effects:** Creates/removes `~/.local/bin/<alias>` (or `.bat`). Prints `✓ Removed alias '<alias>'`, `No alias '<alias>' found to remove.`, `✓ Alias created: <path>`, `⚠ <wrapper_dir> is not in your PATH.`, or `Error: <collision>` (exit 1).
- **Config / env:** `PATH` (for the collision check and the in-PATH warning).
- **Edge cases / guards:** A custom alias whose name differs from the profile is preferred by `build_alias_map` / `find_alias_for_profile` when displaying, so `profile list`/`show` surface the command the user actually types.
- **Rebuild notes:** A two-line exec wrapper is enough; validate the alias as a filename, not as free text.

### `hermes profile rename <old_name> <new_name>`  `id: cli-f.profile.rename`
- **Surface:** CLI
- **Where:** `hermes profile rename [-h] old_name new_name` — sub-help `Rename a profile ('default': sets a display name; id unchanged)`; positionals `Current profile name` and `New profile name (for 'default': a display name — the canonical id stays 'default')`.
- **What it does:** Renames a profile's directory, wrapper alias, Honcho host blocks and sticky pointer. For `default` it instead sets a presentation-only display name.
- **How it works:** `main.py:11436-11446` → `profiles.rename_profile(old, new)` (`profiles.py:2419`). For `default`: rejects an empty name (`Display name cannot be empty.`), calls `set_profile_display_name("default", new)` (`:1007`, max 64 chars) and prints `✓ Display name set: <name> (canonical id remains 'default')`. Otherwise: validates both names, rejects `default` as a target (`Cannot rename to 'default' — it is reserved.`), requires the old dir and an absent new dir; then 1 stops the gateway (`_cleanup_gateway_service` + `_stop_gateway_process`) if running; 2 `old_dir.rename(new_dir)`; 3 `_migrate_honcho_profile_host(old, new, new_dir)` (`:2359`, preserves aiPeer identity); 4 removes the old wrapper and creates a new one when there is no collision; 5 rewrites `active_profile` if it pointed at the old name.
- **Inputs / options:** positionals `old_name`, `new_name`; `-h, --help`.
- **Outputs / side effects:** Moves `<root>/profiles/<old>` → `<root>/profiles/<new>`; rewrites `~/.local/bin`. Prints `✓ Renamed <old> → <new>`, `✓ Alias updated: <new>` or `⚠ Cannot create alias '<new>' — <collision>`, `✓ Active profile updated: <new>`, then `Profile renamed: <old> → <new>` and `Path: <new_dir>`.
- **Config / env:** `active_profile`, Honcho plugin config.
- **Edge cases / guards:** Display names are presentation-only free text (Unicode fine) — never a directory name, wrapper filename or argv token.
- **Rebuild notes:** Renaming the root profile is impossible (its home IS the install root), so give it a display name instead of faking a move.

### `hermes profile export <profile_name>`  `id: cli-f.profile.export`
- **Surface:** CLI
- **Where:** `hermes profile export [-h] [-o OUTPUT] profile_name` — sub-help `Export a profile to archive`; positional `Profile to export`; option help `Output file (default: <name>.tar.gz)`.
- **What it does:** Packages a profile into a portable, credential-free `.tar.gz`.
- **How it works:** `main.py:11448-11458` → `profiles.export_profile(name, output)` (`profiles.py:2229`). Stages a filtered copy in a temp dir, then `make_targz(base, tmpdir, canon)` (base = the output path with `.tar.gz`/`.tgz` stripped). For a named profile the ignore filter drops `{auth.json, .env}`. For `default` the copy uses `_default_export_ignore` (`:2118`) built from `_DEFAULT_EXPORT_EXCLUDE_ROOT` (`:218` — `hermes-agent`, `.worktrees`, `profiles`, `bin`, `node_modules`, `state.db`+`-shm`/`-wal`, `hermes_state.db`, `response_store.db`+`-shm`/`-wal`, `gateway.pid`, `gateway_state.json`, `processes.json`, `auth.json`, `.env`, `auth.lock`, `active_profile`, `.update_check`, `errors.log`, `.hermes_history`, `image_cache`, `audio_cache`, `document_cache`, `browser_screenshots`, `checkpoints`, `sandboxes`, `logs`) and, when `HERMES_HOME` is a cwd-style custom root, an ALLOWLIST `_DEFAULT_EXPORT_INCLUDE_ROOT` (`:251` — `config.yaml`, `SOUL.md`, `MEMORY.md`, `USER.md`, `todo.json`, `system_prompt.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `desktop.json`, `skills`, `cron`, `scripts`, `sessions`, `plugins`, `memories`, `knowledge`, `preferences`). Every staged text-ish file is then force-redacted by `_scrub_export_secrets` (`:2182`) using `agent.redact.redact_sensitive_text(..., force=True)` — the same pass as `hermes sessions export --redact`, and `force=True` ignores `security.redact_secrets`/`HERMES_REDACT_SECRETS` so a share archive never emits raw keys. Redaction applies to `_EXPORT_REDACT_SUFFIXES` (`.md .txt .yaml .yml .json .jsonl .toml .ini .cfg .conf .py .sh .bash .zsh .js .ts .tsx .jsx .css .html .xml .csv`), the name `.cursorrules`, and anything ending `.env.example`; a symlink whose content changes is materialised into a regular file so redaction never writes back through the link into the live profile.
- **Inputs / options:** positional `profile_name`; `-o OUTPUT` / `--output OUTPUT`; `-h, --help`. The library function also takes `extra_files` (root-relative filename → text), used by the desktop app to bundle `desktop.json`.
- **Outputs / side effects:** Writes `<name>.tar.gz` (or `-o`) in the cwd. Prints `✓ Exported '<name>' to <path>`; errors print `Error: <msg>` and exit 1.
- **Config / env:** none (redaction is forced regardless of config).
- **Edge cases / guards:** The default profile is staged under the archive directory name `default/` (its real directory name is `.hermes`).
- **Rebuild notes:** Stage-then-scrub-then-archive; never redact the live tree.

### `hermes profile import <archive>`  `id: cli-f.profile.import`
- **Surface:** CLI
- **Where:** `hermes profile import [-h] [--name NAME] archive` — sub-help `Import a profile from archive`; positional `Path to .tar.gz archive`; option help `Profile name (default: inferred from archive)`.
- **What it does:** Restores a profile from a `.tar.gz` produced by `hermes profile export` and offers to create its alias.
- **How it works:** `main.py:11460-11478` → `profiles.import_profile(archive, name)` (`profiles.py:2292`). Requires the file to exist; reads `archive_root_dirs(archive)` and requires EXACTLY one top-level directory (`Profile archive must contain exactly one top-level directory.`); infers the name from `--name` or that directory; refuses `default` (`Cannot import as 'default' — that is the built-in root profile (~/.hermes). Specify a different name: hermes profile import <archive> --name <name>`); refuses an existing target. Extracts with `safe_extract_targz` into a temp dir (path-traversal safe), renames the extracted root to the canonical name when they differ, then `shutil.move` into `<root>/profiles/<name>`. Back in `cmd_profile`, when `check_alias_collision(name)` is clean it creates the wrapper.
- **Inputs / options:** positional `archive`; `--name NAME` (argparse `dest="import_name"`); `-h, --help`.
- **Outputs / side effects:** Creates `<root>/profiles/<name>/`. Prints `✓ Imported profile '<name>' at <dir>` and `  Wrapper created: <path>`; errors print `Error: <msg>` and exit 1.
- **Config / env:** n/a.
- **Edge cases / guards:** An archive with no single root and no `--name` errors with `Cannot determine profile name from archive. Specify it explicitly: hermes profile import <archive> --name <name>`. Imported archives carry no credentials — the user must fill `.env` afterwards.
- **Rebuild notes:** Validate the archive shape before extracting; extract into a staging dir and move atomically.

### `hermes profile install <source>`  `id: cli-f.profile.install`
- **Surface:** CLI
- **Where:** `hermes profile install [-h] [--name NAME] [--alias] [--force] [-y] source` — sub-help `Install a profile distribution from a git URL or local directory`; description `Install a Hermes profile distribution. SOURCE can be a git URL (github.com/user/repo, https://..., git@...) or a local directory containing distribution.yaml at its root.` Docs `website/docs/user-guide/profile-distributions.md`.
- **What it does:** Installs a whole shareable agent (SOUL.md, skills, cron, mcp.json, config) from a git repository or a local development directory into a new profile.
- **How it works:** `main.py:11480-11527`. Two-stage: first `plan_install(source, tmpdir, override_name)` inside a `TemporaryDirectory(prefix="hermes_dist_preview_")` renders `_render_distribution_plan(plan)` (`main.py:11592-11662`) and asks `Proceed with install? [y/N] ` unless `-y`; then the REAL `install_distribution(...)` re-stages from scratch, so declining has no side effects. `hermes_cli/profile_distribution.py`: `_stage_source` (`:410`) either `git clone --depth 1` (with `noninteractive_git_env()`, `.git` removed after) or uses a local directory, requiring `distribution.yaml` at the root; `_reject_distribution_symlinks` (`:453`) refuses any symlink anywhere in the tree; `read_manifest` parses `DistributionManifest`; `check_hermes_requires(spec, hermes_version)` (`:315`) supports a single comparator `>= <= == != > <` (a bare version means `>=`) over a three-field semver with pre-release/build metadata stripped; the target name is `--name` or `manifest.name`, normalised and validated, and `default` is refused; `manifest.source` is set to the provenance string and `manifest.installed_at` to an ISO-8601 UTC timestamp. `install_distribution` (`:662`) refuses an existing profile without `--force`, `_bootstrap_user_dirs` creates the nine dirs, and `_copy_dist_payload(staged, target, manifest, preserve_config=False)` (`:563`) copies either the manifest's explicit `distribution_owned` allowlist (path-aware, rejecting `..`, absolute paths and any first segment in `USER_OWNED_EXCLUDE`) or, when the list is omitted, every staged entry outside `USER_OWNED_EXCLUDE`; `.env.template` is renamed to `.env.EXAMPLE`; a `.env.EXAMPLE` is generated from `env_requires` when the tree shipped none; the resolved manifest is written back with `write_manifest`.
- **Inputs / options:** positional `source`; `--name NAME` (argparse `dest="install_name"`, `Override profile name (default: read from manifest)`); `--alias` (`Create a shell wrapper alias for the installed profile`); `--force` (`Overwrite an existing profile of the same name (user data preserved)`); `-y, --yes` (`Skip manifest preview confirmation`); `-h, --help`.
- **Outputs / side effects:** Creates/updates `<root>/profiles/<name>/`. Preview block: `Distribution: <name> v<version>`, `  <description>`, `  Author:   <author>`, `  Requires: Hermes <spec>`, `  Source:   <provenance>`, `  Target:   <dir>`, plus either `  (profile exists — will overwrite distribution-owned files only)` or the four-line warning `  ⚠ Profile exists but is NOT a distribution.  Installing here will` / `    overwrite its SOUL.md, skills/, cron/, and mcp.json.` / `    Your memories, sessions, auth.json, and .env will be preserved,` / `    but any hand-edits to distribution-owned files will be lost.`; an `  Env vars:` list of `    • <NAME> (required|optional, ✓ set|needs setting|—) — <description>` where "set" is checked against BOTH the shell environment and the target profile's `.env` (read as `utf-8-sig` so a Notepad BOM cannot hide the first key); and `  ⚠ This distribution ships cron jobs.  They will NOT run automatically — review and enable manually.` Success block: `✓ Installed '<name>' v<version>`, `  Profile path: <dir>`, `  Next: copy .env.EXAMPLE to .env and fill in required keys:` + `    <dir>/.env.EXAMPLE`, `  Cron jobs were included but are NOT scheduled automatically.` + `  Review them with:  hermes -p <name> cron list`, `  Use with:      hermes -p <name> chat`. Declining prints `Install cancelled.`
- **Config / env:** git credentials/SSH keys are used as-is for private repos.
- **Edge cases / guards:** `USER_OWNED_EXCLUDE` (`profile_distribution.py:101`) is never copied or overwritten: `auth.json`, `.env`, `state.db(-shm/-wal)`, `hermes_state.db`, `response_store.db(-shm/-wal)`, `gateway.pid`, `gateway_state.json`, `processes.json`, `auth.lock`, `active_profile`, `.update_check`, `errors.log`, `.hermes_history`, `memories`, `sessions`, `logs`, `plans`, `workspace`, `home`, `image_cache`, `audio_cache`, `document_cache`, `browser_screenshots`, `checkpoints`, `sandboxes`, `backups`, `cache`, `hermes-agent`, `.worktrees`, `profiles`, `bin`, `node_modules`, `local`. Errors (`DistributionError`, `ValueError`) print `Error: <msg>` and exit 1. Git failures surface as `git clone failed: <stderr>` or `git is required for git-URL installs`.
- **Rebuild notes:** Preview from a throwaway stage, install from a fresh one; separate distribution-owned from user-owned by explicit lists, not heuristics.

### `hermes profile update <profile_name>`  `id: cli-f.profile.update`
- **Surface:** CLI
- **Where:** `hermes profile update [-h] [--force-config] [-y] profile_name` — sub-help `Re-pull a distribution and apply updates (user data preserved)`; description `Fetch the distribution from its recorded source and overwrite distribution-owned files (SOUL.md, skills/, cron/, mcp.json). User data (memories, sessions, auth, .env) is never touched. config.yaml is preserved unless --force-config is passed.`
- **What it does:** Re-pulls an installed distribution from its recorded source and overwrites only the distribution-owned files.
- **How it works:** `main.py:11529-11569`. Reads the installed `distribution.yaml` with `read_manifest(get_profile_dir(canon))`; a profile without one errors `Error: Profile '<n>' is not a distribution (no distribution.yaml). Only profiles installed via 'hermes profile install' can be updated.` (exit 1). Unless `-y` it prints the preview and asks `Proceed? [y/N] `. Then `update_distribution(canon, force_config)` (`profile_distribution.py:705`) re-stages from `existing_manifest.source` (erroring `Profile '<n>' has no recorded source.  Re-install with 'hermes profile install <source> --name {canon} --force'.` when empty) and calls `_copy_dist_payload(..., preserve_config=not force_config)`.
- **Inputs / options:** positional `profile_name`; `--force-config` (`Also overwrite config.yaml (normally preserved to keep user overrides)`); `-y, --yes` (`Skip confirmation`); `-h, --help`.
- **Outputs / side effects:** Overwrites SOUL.md, `skills/`, `cron/`, `mcp.json`, `distribution.yaml` (and `config.yaml` with `--force-config`). Preview lines: `Update '<n>' from: <source>|(no source)`, `  Currently at version <v>`, `  --force-config set: config.yaml WILL be overwritten.` or `  config.yaml will be preserved (pass --force-config to overwrite).`, `  User data (memories, sessions, auth, .env) will NOT be touched.` Declining prints `Update cancelled.` Success: `✓ Updated '<name>' → v<version>` and, when cron files shipped, `  Cron files were refreshed.  Review with:  hermes -p <name> cron list`.
- **Config / env:** the recorded `source:` in the profile's `distribution.yaml`.
- **Edge cases / guards:** A directory entry being replaced is rmtree'd first, so removed upstream files really disappear; the copytree ignore only filters `USER_OWNED_EXCLUDE` at the STAGED ROOT (nested files with those names are copied normally).
- **Rebuild notes:** Store the source in the installed manifest so update needs no extra state.

### `hermes profile info <profile_name>`  `id: cli-f.profile.info`
- **Surface:** CLI
- **Where:** `hermes profile info [-h] profile_name` — sub-help `Show a profile's distribution manifest (version, requirements, source)`; positional `Profile to inspect`.
- **What it does:** Prints the full distribution manifest of an installed profile.
- **How it works:** `main.py:11571-11590` → `describe_distribution(name)` (`profile_distribution.py:762`) returns `manifest.to_dict()` or `{}` when the profile has no `distribution.yaml`.
- **Inputs / options:** positional `profile_name`; `-h, --help`.
- **Outputs / side effects:** `Distribution: <name>`, `Version:      <version|?>`, optional `Description:`, `Author:`, `License:`, `Requires:     Hermes <spec>`, `Source:`, `Installed:`, then when `env_requires` is present `Environment variables:` with `  <NAME> (required|optional) — <description>` and `      default: <value>` lines. A non-distribution profile prints `Profile '<n>' is not a distribution (no distribution.yaml).`
- **Config / env:** n/a.
- **Edge cases / guards:** `DistributionError`/`ValueError` (missing profile) print `Error: <msg>` and exit 1.
- **Rebuild notes:** n/a.

### Profile wrapper scripts / aliases (`~/.local/bin/<alias>`)  `id: cli-f.profile.wrappers`
- **Surface:** CLI / Core
- **Where:** `~/.local/bin/<alias>` (POSIX) or `~/.local/bin/<alias>.bat` (Windows), created by `hermes profile create`, `hermes profile alias`, `hermes profile import`, `hermes profile install --alias` and `hermes profile rename`.
- **What it does:** Turns a profile into a first-class command: typing `coder chat` runs `hermes -p coder chat`.
- **How it works:** `profiles.py:505 create_wrapper_script(name, target=None)` — the FILE is named after the alias, the profile it activates is `target or name`, which is what lets a custom alias point at a differently-named profile. POSIX body: `#!/bin/sh\nexec <shlex.quote(shutil.which("hermes") or "hermes")> -p <profile> "$@"\n`, chmod adds `S_IEXEC|S_IXGRP|S_IXOTH`. Windows body: `@echo off\r\nhermes -p <profile> %*\r\n`. `remove_wrapper_script` (`:548`) validates the alias name (traversal guard) and only unlinks files whose body contains `hermes -p`. `build_alias_map()` (`:639`) reverse-maps profile→alias in one pass over the wrapper dir, reading at most 8192 bytes per candidate, skipping non-files, skipping suffixed files on POSIX and non-`.bat` files on Windows, and skipping anything that fails strict UTF-8 decoding (binaries like ffmpeg). A custom alias (file name ≠ profile) wins over the profile-named wrapper; iteration is sorted for determinism.
- **Inputs / options:** n/a (driven by the profile sub-commands).
- **Outputs / side effects:** Files in `~/.local/bin`. `_is_wrapper_dir_in_path()` (`:499`) checks `~/.local/bin` against `PATH` split on `os.pathsep` and drives the `⚠ … is not in your PATH.` warning.
- **Config / env:** `PATH`.
- **Edge cases / guards:** `check_alias_collision` (`:457`) returns a human message for: an invalid alias name, a reserved name (`'<n>' is a reserved name`), a hermes sub-command (`'<n>' conflicts with a hermes subcommand`), or an existing PATH binary (`'<n>' conflicts with an existing command (<path>)`) — except our own wrapper, which may be overwritten.
- **Rebuild notes:** Reading a bounded head slice of each candidate is the difference between a 4.5 s and a sub-100 ms `profile list` on a busy `~/.local/bin`.

### Profile metadata file (`<profile>/profile.yaml`)  `id: cli-f.profile.meta`
- **Surface:** Config / Core
- **Where:** `<root>/profiles/<name>/profile.yaml` (and `<root>/profile.yaml` for `default`).
- **What it does:** Stores the profile's presentation name and its orchestrator-facing description.
- **How it works:** `profiles.py:920-993`. Keys: `description` (string), `description_auto` (bool — true when written by the LLM describer, which lets the dashboard show a "review" badge), `display_name` (string, max 64 chars; an empty value REMOVES the key). `read_profile_meta` never raises — a corrupt file returns `{"description": "", "description_auto": False, "display_name": ""}`. `write_profile_meta` merges only the explicitly-passed fields and writes through `utils.atomic_yaml_write(path, existing, sort_keys=False)` (a bare `open("w")` would truncate before the dump and, because the read path swallows parse errors as `{}`, silently drop unspecified fields on the next call).
- **Inputs / options:** written by `hermes profile create --description`, `hermes profile describe`, `hermes profile rename default <display>`, and the dashboard.
- **Outputs / side effects:** One small YAML file per profile.
- **Config / env:** n/a.
- **Edge cases / guards:** `format_profile_label` renders `display_name (canonical_id)` only when the display name is set AND differs from the id.
- **Rebuild notes:** Keep presentation metadata out of `config.yaml` so a config migration can never destroy it.

### Distribution manifest (`distribution.yaml`)  `id: cli-f.profile.manifest`
- **Surface:** Config / Docs
- **Where:** The file at the root of a profile-distribution repo and inside every installed distribution profile. Documented in `website/docs/user-guide/profile-distributions.md:117` and `website/docs/reference/profile-commands.md:404`.
- **What it does:** Declares a shareable agent: its identity, version, Hermes requirement, required environment variables, and which paths the distribution owns.
- **How it works:** `hermes_cli/profile_distribution.py:170 DistributionManifest`. Fields: `name` (required — a missing/empty name raises `distribution.yaml missing 'name'`), `version` (default `"0.1.0"`), `description`, `hermes_requires`, `author`, `license`, `env_requires` (list of `{name, description, required=true, default}`; a non-list raises `env_requires must be a list`, a non-mapping entry raises `env_requires entry must be a mapping, got <type>`, a nameless entry raises `env_requires entry missing 'name'`), `distribution_owned` (optional list of paths; a non-list raises `distribution_owned must be a list`), plus the two install-time fields `source` and `installed_at`. `owned_paths()` returns `distribution_owned` when non-empty, else `DEFAULT_DIST_OWNED = ("SOUL.md", "config.yaml", "mcp.json", "skills", "cron", "distribution.yaml")`. `_env_template_from_manifest` (`:351`) generates the `.env.template`/`.env.EXAMPLE` body: a two-line header, then per requirement an optional `# <description>` line, a `# (required)`/`# (optional)` line, and `NAME=<default>` (commented out with `# ` when optional).
- **Inputs / options:** the YAML keys above.
- **Outputs / side effects:** `write_manifest(profile_dir, manifest)` (`:266`) rewrites the file inside the installed profile with the resolved name, source and timestamp.
- **Config / env:** the declared `env_requires` names.
- **Edge cases / guards:** `MANIFEST_FILENAME = "distribution.yaml"`, `ENV_TEMPLATE_FILENAME = ".env.template"`, `ENV_EXAMPLE_FILENAME = ".env.EXAMPLE"`. Source detection (`_looks_like_git_url`, `:375`) accepts anything ending `.git`, anything starting `git@`/`ssh://`/`git://`, ANY `http(s)://` URL, and the bare shorthand matching `^github\.com/[\w.-]+/[\w.-]+/?$` — tar.gz URLs are explicitly no longer accepted.
- **Rebuild notes:** An explicit ownership list plus a hard user-owned denylist is what makes updates safe; symlinks must be rejected outright.

---

## 9. `hermes dashboard` and `hermes serve` — the web UI and the headless backend

### `hermes dashboard`  `id: cli-f.dashboard`
- **Surface:** CLI
- **Where:** `hermes dashboard [-h] [--port PORT] [--host HOST] [--insecure] [--skip-build] [--isolated] [--stop] [--status] [--no-open] {register} ...`. Root help `dashboard           Start the web UI dashboard`; description `Launch the Hermes Agent web dashboard for managing config, API keys, and sessions`.
- **What it does:** Builds (if needed) and serves the Hermes web dashboard SPA plus its JSON-RPC/WebSocket API, and opens it in the browser.
- **How it works:** Parser `hermes_cli/subcommands/dashboard.py:87-125 build_dashboard_parser` — shared runtime flags come from `_add_server_runtime_args(parser)` (`:17-84`), then `--no-open`, the hidden `--tui` back-compat shim (`argparse.SUPPRESS`, silently ignored so an old desktop shell + new CLI degrades gracefully instead of exiting 2 with "unrecognized arguments: --tui"), and `set_defaults(func=cmd_dashboard)`. Handler `main.py:11995 cmd_dashboard`, in order: reject `--ssh-session-token-file` with `--status`/`--stop`; `--status` → `_report_dashboard_status()` and exit 0; `--stop` → `_find_stale_dashboard_pids()` + `_kill_stale_dashboard_processes(reason="requested via --stop")`; resolve `_headless_backend` (`serve` only) and validate `--ssh-owner-nonce` against `^[0-9a-f]{16}$`; sanitize Desktop-inherited env (pop `HERMES_WEB_DIST` when it looks like `.../app.asar[.unpacked]/dist` and `HERMES_DESKTOP != 1`; pop `HERMES_SERVE_HEADLESS` for the dashboard path); unified profile-launch routing (see `cli-f.dashboard.profile-routing`); `resource_limits.apply_nofile_soft_limit()`; read the SSH token file; `hermes_logging.setup_logging(mode="gui")` so startup/build failures land in `gui.log`; import-check `fastapi` + `uvicorn` (missing → a `Web UI dependencies not installed (need fastapi + uvicorn).` block with the exact `pip install -e .` / `uv pip install -e .` commands and exit 1); `_sync_bundled_skills_quietly()`; `config.apply_terminal_config_to_env()` (bridges `terminal.*` into `TERMINAL_*` for the in-process agents and cron ticks); build/verify the web dist; `plugins.discover_plugins()` so a `DashboardAuthProvider` plugin registers BEFORE the fail-closed gate; `mcp_startup.start_background_mcp_discovery(thread_name="dashboard-mcp-discovery")`; `_maybe_setup_dashboard_auth_interactively(args)`; `web_server.start_server(host, port, open_browser=not no_open, allow_public=insecure, initial_profile=open_profile, headless=_headless_backend, ssh_session_token=…, ssh_owner_nonce=…)`.
- **Inputs / options:** `-h, --help`; `--port PORT` (`type=int`, default `9119`, help `Port (default 9119, 0 for auto-assign by OS)`); `--host HOST` (default `127.0.0.1`); `--insecure`; `--skip-build`; `--isolated`; `--open-profile` (hidden, `argparse.SUPPRESS`, default `""` — set by the unified-launch re-exec); `--stop`; `--status`; `--no-open`; `--tui` (hidden, no-op); sub-command `register`.
- **Outputs / side effects:** Binds a TCP listener; may run `npm install`/`npm run build` for the web UI; prints `  Hermes Web UI → http://<host>:<port>`; opens a browser tab; registers the process in the spawn ledger with `{host, port, profile}`; writes `gui.log`.
- **Config / env:** `dashboard.*` (theme, turn_isolation, compute_host_heartbeat_secs, compute_host_respawn_max, show_token_analytics, trusted_proxies, ws_ping_interval, ws_ping_timeout, ws_orphan_reap_grace_s, startup_orphan_sweep, oauth.client_id, oauth.portal_url, basic_auth.*, drain_auth.*, public_url); env `HERMES_WEB_DIST`, `HERMES_SERVE_HEADLESS`, `HERMES_DESKTOP`, `HERMES_DASHBOARD_SESSION_TOKEN`, `HERMES_DASHBOARD_OAUTH_CLIENT_ID`, `HERMES_DASHBOARD_PORTAL_URL`, `HERMES_DASHBOARD_PUBLIC_URL`, `HERMES_DESKTOP_READY_FILE`, `HERMES_DESKTOP_CHILD_PID`.
- **Edge cases / guards:** `--status`/`--stop` win over the start flags because they exit before the server starts. A missing web dist under `--skip-build` triggers ONE recovery build (only when `HERMES_WEB_DIST` is unset) before failing. Plugin-discovery failure prints `⚠ Plugin discovery failed: <exc>` to stderr but does not block startup.
- **Rebuild notes:** One server binary, two entry points (UI and headless), one auth gate. A better version would ship a prebuilt dist so `npm` is never required at runtime.

### `hermes dashboard --status`  `id: cli-f.dashboard.status`
- **Surface:** CLI
- **Where:** `hermes dashboard --status` / `hermes serve --status` — help `List running Hermes web server processes and exit`.
- **What it does:** Lists every running dashboard or serve backend that is actually accepting connections.
- **How it works:** `main.py:11693 _report_dashboard_status()`. `dashboard_procs._scan_dashboard_processes()` matches the six cmdline patterns `hermes dashboard`, `hermes_cli.main dashboard`, `hermes_cli/main.py dashboard`, `hermes serve`, `hermes_cli.main serve`, `hermes_cli/main.py serve` (Windows uses `wmic` through `bounded_probe_run` with `errors="ignore"`); `_parse_dashboard_runtime(command)` (`main.py:8614`) extracts `(mode, host, port)` with `--port(=| )(\d+)` and `--host(=| )("…"|'…'|\S+)`, defaulting to `127.0.0.1:9119`; each candidate must have a live pid (`gateway.status._pid_exists`) and an accepting socket (`_dashboard_listening`, a 1.5 s `socket.create_connection` to `_dashboard_probe_host(host)` where `0.0.0.0`/`::`/empty map to `127.0.0.1`). Serve-mode backends are deliberately INCLUDED, because `--stop` kills them.
- **Inputs / options:** `--status` (`store_true`).
- **Outputs / side effects:** stdout only; always exit 0. `No hermes dashboard or serve processes running.` or `N hermes dashboard/serve process(es) running:` followed by `    PID <pid> [<mode>]: <full cmdline>` lines (live-verified — note the substring match also catches shell wrappers whose command line merely CONTAINS `hermes dashboard`, so a `bash -c '… hermes dashboard --status'` invocation lists itself).
- **Config / env:** n/a.
- **Edge cases / guards:** Ledger-registered profiled serves that the argv scan cannot match are added by the spawn-ledger augmentation inside `_scan_dashboard_processes`.
- **Rebuild notes:** Positive process identity (a spawn ledger) beats cmdline matching; keep the argv scan only as a fallback for hand-started processes.

### `hermes dashboard --stop`  `id: cli-f.dashboard.stop`
- **Surface:** CLI
- **Where:** `hermes dashboard --stop` / `hermes serve --stop` — help `Stop all running Hermes web server processes and exit`.
- **What it does:** Terminates every running dashboard/serve backend.
- **How it works:** `main.py:12009-12020` → `_find_stale_dashboard_pids()` then `dashboard_procs._kill_stale_dashboard_processes(reason="requested via --stop")` (`dashboard_procs.py:355`). POSIX: SIGTERM, wait up to ~3 s, SIGKILL survivors. Windows: `taskkill /PID <pid> /F`. PIDs listed in `HERMES_DESKTOP_CHILD_PID` (comma-separated, or a lone int for back-compat) are excluded so a desktop-managed backend is never killed by its own update. Manually started dashboards are NOT auto-restarted because the original launch args are unknown.
- **Inputs / options:** `--stop` (`store_true`).
- **Outputs / side effects:** Kills processes. `No hermes dashboard processes running.` (exit 0) when nothing matched; otherwise the kill outcomes are printed by the helper and the exit code is 0 when the survivors list is empty, 1 when some were unkillable.
- **Config / env:** `HERMES_DESKTOP_CHILD_PID`.
- **Edge cases / guards:** `restart_managed=True` (the `hermes update` path, not `--stop`) additionally excludes SSH-lock-owned serves and restarts owning systemd units after the kill, because systemd treats the SIGTERM as a clean stop and `Restart=on-failure` would never fire.
- **Rebuild notes:** Never SIGKILL first; always exclude the caller's own supervisor tree.

### `hermes dashboard --isolated`  `id: cli-f.dashboard.isolated`
- **Surface:** CLI
- **Where:** `hermes dashboard --isolated` / `hermes serve --isolated`.
- **What it does:** Opts out of the machine-level dashboard routing so a named profile gets its own dedicated server instead of attaching to the shared one.
- **How it works:** See `cli-f.dashboard.profile-routing`; the routing block is skipped when `args.isolated` is true.
- **Inputs / options:** `--isolated` (`store_true`, help `When launched from a named profile, run a dedicated server scoped to that profile instead of routing to the machine-level server. Default behavior is unified: profile launches attach to (or start) ONE machine-level server and preselect the profile.`).
- **Outputs / side effects:** A second server process on the requested port.
- **Config / env:** n/a.
- **Edge cases / guards:** Desktop pool backends (`HERMES_DESKTOP=1`) are always per-profile and never routed, with or without this flag.
- **Rebuild notes:** Make "one management surface per machine" the default and per-tenant isolation the explicit opt-in.

### Unified profile-launch routing (`--open-profile`)  `id: cli-f.dashboard.profile-routing`
- **Surface:** CLI / Web dashboard
- **Where:** Triggered by launching the dashboard from a named profile, e.g. `worker dashboard` or `hermes -p worker dashboard`.
- **What it does:** Instead of starting one dashboard per profile, a named-profile launch attaches to (or starts) the single machine-level dashboard and preselects that profile in the SPA's switcher.
- **How it works:** `main.py:12060-12146`. Guard: `_launch_profile = get_active_profile_name()` is not `default`/`custom`, `--isolated` not set, `--open-profile` not already set, and `HERMES_DESKTOP != "1"`. If `_dashboard_listening(host, port)` → print `Machine dashboard already running on port <port>.` and `  Managing profile '<name>': <url>`, open the browser at `http://<host>:<port>/?profile=<name>` unless `--no-open`, exit 0. Otherwise print `Routing to the machine dashboard (profile '<name>' preselected). Use --isolated for a dedicated per-profile server.` and re-exec `sys.executable -m hermes_cli.main -p default {dashboard|serve} --port <p> --host <h> --open-profile <name>` (plus `--ssh-owner-nonce`, `--ssh-session-token-file`, `--no-open`, `--insecure`, `--skip-build` when set). The child's environment comes from `tools.environments.local.build_subprocess_env(scrub_secrets=False, inherit_profile_home=False)` with `HERMES_HOME` pinned to `hermes_constants.get_default_hermes_root()` — resolved explicitly rather than unset, because in the Docker layout the machine root is `/opt/data` and an unset `HERMES_HOME` would fall back to `$HOME/.hermes = /opt/data/.hermes`, an empty auto-seeded home. On Windows it uses `subprocess.Popen` + `sys.exit(proc.wait())` instead of `os.execvpe`, which under Python 3.14+ can crash with `STATUS_ACCESS_VIOLATION (0xC0000005)`.
- **Inputs / options:** `--open-profile <name>` (hidden internal flag); `--isolated` opts out.
- **Outputs / side effects:** Either no new process (attach + browser open) or one re-exec'd machine dashboard. `start_server(initial_profile=…)` appends `/?profile=<quoted name>` to the auto-opened URL.
- **Config / env:** `HERMES_HOME`, `HERMES_DESKTOP`.
- **Edge cases / guards:** The re-exec pins `-p default` so `_apply_profile_override` cannot re-route the child through the sticky `active_profile` file.
- **Rebuild notes:** Per-request tenant scoping (`?profile=`) plus one process is strictly better than N processes fighting over one port.

### `hermes dashboard --skip-build`  `id: cli-f.dashboard.skip-build`
- **Surface:** CLI
- **Where:** `hermes dashboard --skip-build` / `hermes serve --skip-build`.
- **What it does:** Serves the already-built web dist instead of running the npm build — for non-interactive contexts (Windows Scheduled Tasks, CI) where npm is unavailable.
- **How it works:** `main.py:12203-12256`. Without the flag and without `HERMES_WEB_DIST`, `_build_web_ui(PROJECT_ROOT/"web", fatal=True)` runs (`main.py:6549`), which serialises concurrent builds behind an exclusive `flock` on `<project_root>/.web_ui_build.lock`: a process that cannot take the lock serves the existing `hermes_cli/web_dist/index.html`, or blocks until the builder finishes when no dist exists at all (Windows has no flock and falls through unserialised). With `--skip-build` the dist root is `HERMES_WEB_DIST` or `PROJECT_ROOT/hermes_cli/web_dist`, and a missing `index.html` triggers ONE recovery build — but only when `HERMES_WEB_DIST` is unset, since a caller-managed directory cannot be populated by the build.
- **Inputs / options:** `--skip-build` (`store_true`).
- **Outputs / side effects:** `→ Skipping web UI build (--skip-build); using dist at <path>`; recovery path prints `⚠ --skip-build was passed but no web dist found at: <path>` + `  Attempting one recovery build of the web UI...` then `  ✓ Recovery build produced a web dist`; hard failure prints `✗ --skip-build was passed but no web dist found at: <path>`, optionally `  The recovery build did not produce a usable dist.`, `  Pre-build first:  npm install --workspace web && npm run build -w web`, `  Or drop --skip-build to build automatically.` and exits 1. With `HERMES_WEB_DIST` set but no `--skip-build`, the same validation runs and prints `→ Using web dist from HERMES_WEB_DIST: <path>` (the path is expanduser'd and written back into the env var because `web_server` reads it raw at import).
- **Config / env:** `HERMES_WEB_DIST`.
- **Edge cases / guards:** `serve` sets `HERMES_SERVE_HEADLESS=1` and skips the whole build gate.
- **Rebuild notes:** Ship the dist in the package; make the runtime build a development-only fallback.

### `hermes dashboard --insecure` (deprecated no-op)  `id: cli-f.dashboard.insecure`
- **Surface:** CLI
- **Where:** `hermes dashboard --insecure` / `hermes serve --insecure`.
- **What it does:** Nothing. Formerly bypassed authentication on a non-loopback bind; since the June 2026 hardening a public bind ALWAYS requires an auth provider.
- **How it works:** Threaded through as `start_server(allow_public=...)`; `web_server.py:19630-19638` logs a warning when it is passed with a non-loopback host: `--insecure no longer bypasses dashboard authentication. A non-loopback bind (%s) now ALWAYS requires an auth provider (OAuth or the bundled password provider). Configure one — see below — or bind to 127.0.0.1 and reach it over an SSH tunnel / Tailscale.` It still flips `uvicorn` `proxy_headers` only via `app.state.auth_required`, not via this flag.
- **Inputs / options:** `--insecure` (`store_true`, help text quoted in the parser: `DEPRECATED / NO-OP. Formerly bypassed auth on a non-loopback bind. As of the June 2026 hardening it no longer disables authentication — a public bind always requires an auth provider (password or OAuth). Bind 127.0.0.1 + tunnel to keep it local.`).
- **Outputs / side effects:** A log warning.
- **Config / env:** n/a.
- **Edge cases / guards:** Kept accepted (rather than removed) so existing scripts do not die with "unrecognized arguments".
- **Rebuild notes:** When you remove an escape hatch, keep the flag and make it loudly inert instead of silently changing behaviour.

### `hermes dashboard --no-open`  `id: cli-f.dashboard.no-open`
- **Surface:** CLI
- **Where:** `hermes dashboard --no-open` — help `Don't open browser automatically`. Also accepted (hidden) by `hermes serve`, where it is redundant.
- **What it does:** Starts the server without launching a browser tab.
- **How it works:** `start_server(open_browser=not args.no_open)`; `web_server.py:19250 _maybe_open_browser` returns immediately when false. Even when true it skips on headless Linux (neither `DISPLAY` nor `WAYLAND_DISPLAY`) to avoid a TUI browser (links, lynx) SIGHUP-ing the server, logging `Skipping browser-open: no DISPLAY or WAYLAND_DISPLAY detected (headless Linux). Pass --no-open to suppress this detection.`; it maps `0.0.0.0`/`::` to `127.0.0.1`, appends `/?profile=<quoted>` when `initial_profile` is set, and opens after a 1 s delay on a daemon thread.
- **Inputs / options:** `--no-open` (`store_true`).
- **Outputs / side effects:** none beyond suppressing the browser.
- **Config / env:** `DISPLAY`, `WAYLAND_DISPLAY`.
- **Edge cases / guards:** `serve` hard-sets `no_open=True` via `set_defaults`, so the flag there exists only to keep legacy desktop spawns from tripping "unrecognized arguments".
- **Rebuild notes:** n/a.

### `hermes dashboard register`  `id: cli-f.dashboard.register`
- **Surface:** CLI
- **Where:** `hermes dashboard register [-h] [--name NAME] [--redirect-uri REDIRECT_URI] [--portal-url PORTAL_URL]`. Sub-help `Register a self-hosted dashboard with Nous Portal (writes the OAuth client ID to .env)`; description `Register this install as a self-hosted dashboard with your Nous Portal account. Creates an OAuth client, writes HERMES_DASHBOARD_OAUTH_CLIENT_ID into ~/.hermes/.env, and prints how to engage the login gate. Requires being logged in (hermes setup).`
- **What it does:** Provisions (or updates) a self-hosted OAuth client on Nous Portal and writes the resulting client id into `~/.hermes/.env`, so a publicly bound dashboard can require Nous login.
- **How it works:** Parser `subcommands/dashboard.py:176-214` (nested sub-parser under `dashboard`, so bare `hermes dashboard` still launches the server). Handler `main.py:12318 cmd_dashboard_register` → `hermes_cli/dashboard_register.py:230`. Steps: (1) refuse on a managed install (`✗ 'hermes dashboard register' is not available in a managed/hosted install.` + `  The dashboard OAuth client is provisioned by the hosting platform.`, exit 1); (2) `auth.resolve_nous_access_token()` (refreshes near expiry) — a relogin-required `AuthError` prints `✗ You're not logged into Nous Portal.` + `  Run 'hermes setup' (or 'hermes auth add nous') first, then retry.`, other errors print `✗ Could not resolve a Nous Portal access token: <exc>`, both exit 1; (3) resolve the portal (flag > `HERMES_DASHBOARD_PORTAL_URL` > the stored login's portal); (4) read the existing `HERMES_DASHBOARD_OAUTH_CLIENT_ID` from `.env` and send it back so the portal UPDATES that row instead of minting a duplicate; (5) pick the name — explicit `--name`, else keep the portal's stored name on a re-run (send no name), else generate a Docker-style `<adjective>_<noun>` from the 45 adjectives (`amber` … `zesty`) and 43 nouns (`albatross` … `lovelace`) in `_NAME_ADJECTIVES`/`_NAME_NOUNS` (`:41,:49`); (6) `POST {portal}/api/oauth/self-hosted-client` with `Authorization: Bearer <token>`, `Content-Type: application/json`, `Accept: application/json`, 15 s timeout, body `{name?, custom_redirect_uri?, client_id?}`; (7) write `HERMES_DASHBOARD_OAUTH_CLIENT_ID` always, `HERMES_DASHBOARD_PORTAL_URL` when explicitly supplied or when inferred-and-non-default-and-absent, and `HERMES_DASHBOARD_PUBLIC_URL` derived as `scheme://netloc` of `--redirect-uri` (the runtime appends `/auth/callback` itself, so persisting the full callback would double the path).
- **Inputs / options:** `-h, --help`; `--name NAME`; `--redirect-uri REDIRECT_URI`; `--portal-url PORTAL_URL`.
- **Outputs / side effects:** Creates/updates a portal OAuth client; rewrites `~/.hermes/.env`. Prints `✓ Registered dashboard "<name>"` or `✓ Updated dashboard "<name>"`, then `  Wrote to <env_path>:` with `    HERMES_DASHBOARD_OAUTH_CLIENT_ID=<id>` (and the two optional lines), then the caveat block `  Heads up — Nous login only *engages* on a non-loopback bind. A plain` / `  'hermes dashboard' (localhost) leaves the gate off and serves locally` / `  without auth, which is fine for your own machine.`, then either `  To require Nous login on your registered host, run the dashboard` / `  bound publicly (it must be reachable at https://<host>) and log in` / `  at its /login page.` or `  To require Nous login (e.g. exposing on your LAN or a public host):` / `    hermes dashboard --host 0.0.0.0` / `  …then log in at the dashboard's /login page.`, then `  If the dashboard is already running, restart it to pick up the new env.` and `  Manage or revoke this dashboard at <portal>/local-dashboards`.
- **Config / env:** writes `HERMES_DASHBOARD_OAUTH_CLIENT_ID`, `HERMES_DASHBOARD_PORTAL_URL`, `HERMES_DASHBOARD_PUBLIC_URL`; reads `HERMES_DASHBOARD_PORTAL_URL`; the default portal is `https://portal.nousresearch.com`.
- **Edge cases / guards:** HTTP 401 → `Nous Portal rejected the access token (401). Try 'hermes auth add nous' to re-authenticate.`; 403 → the portal's `error_description` or `Your account is not permitted to register a self-hosted dashboard.`; other codes → `Portal returned HTTP <code>[: <detail>]`; transport failure → `Could not reach Nous Portal at <portal>: <reason>`; a response without `client_id` → `Portal returned an unexpected response (no client_id).` All surface as `✗ Registration failed: <msg>` + exit 1. Re-sending a stale/deleted client_id is safe — the portal falls back to creating a fresh one.
- **Rebuild notes:** Idempotency by resending the stored id; derive the public origin from the redirect URI rather than asking for it twice.

### Interactive dashboard-auth setup prompt  `id: cli-f.dashboard.auth-setup`
- **Surface:** CLI
- **Where:** Runs automatically inside `hermes dashboard` (just before `start_server`) when the auth gate will engage, no provider is registered, and stdin/stdout are both TTYs.
- **What it does:** Offers to configure dashboard authentication on the spot instead of greeting the operator with a hard fail-closed error.
- **How it works:** `main.py:11741 _maybe_setup_dashboard_auth_interactively(args)`. No-ops when `should_require_dashboard_auth(host)` is false, when `dashboard_auth.list_providers()` is non-empty, or when either stream is not a TTY. Otherwise prints the menu and, for choice `1`, collects a username (`line_input`) and a password twice (`getpass.getpass`), hashes it with `plugins.dashboard_auth.basic.hash_password`, mints a stable `secrets.token_urlsafe(32)` signing secret, writes `dashboard.basic_auth.{username,password_hash,secret}` (clearing any plaintext `password`), calls `plugins_cmd.ensure_basic_auth_plugin_enabled_in_config(cfg)` to un-disable the bundled `basic` plugin, `save_config(cfg)`, then `discover_plugins(force=True)`.
- **Inputs / options:** the prompt `  Choice [1]: ` over the menu `    [1] Username & password (quickest; for a trusted LAN / VPN)`, `    [2] OAuth via Nous Portal (run 'hermes dashboard register')`, `    [3] Cancel`; then `  Username [admin]: `, `  Password: `, `  Confirm password: `.
- **Outputs / side effects:** Header `⚠ Dashboard authentication is required for this configuration (<host>).` + `  Non-loopback binds and configured external dashboard.public_url values require authentication (--insecure does not bypass this).` + `  How do you want to authenticate the dashboard?`. Choice 2 prints the `hermes dashboard register` instructions and the docs link `https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard#authentication-gated-mode` and exits 0. Success prints `  ✓ Username/password auth configured (user: <u>).` + `    Saved to config.yaml under dashboard.basic_auth.` + `    Sign in at the dashboard with these credentials.` Failures: `  ✗ Empty password — aborting.`, `  ✗ Passwords don't match — aborting.`, `  ✗ Could not load the password provider: <exc>`, `  ✗ Failed to write config.yaml: <exc>` (all exit 1), and the non-fatal `  ⚠ Plugin re-discovery failed (<exc>); the gate may still fail closed. Set the password again or restart the dashboard.` Also `  ✓ Re-enabled the bundled 'basic' auth plugin (was in plugins.disabled)`.
- **Config / env:** writes `dashboard.basic_auth.username`, `.password_hash`, `.password` (cleared), `.secret`; removes `basic` from `plugins.disabled`.
- **Edge cases / guards:** Non-TTY callers (Docker/s6, CI, piped `--no-open`) fall through to `start_server`'s fail-closed `SystemExit` unchanged.
- **Rebuild notes:** When a security gate would hard-fail a human, offer the fix inline; when it would hard-fail a script, fail closed with the exact remediation.

### Dashboard auth gate (fail-closed on public binds)  `id: cli-f.dashboard.auth-gate`
- **Surface:** API / Core
- **Where:** Startup of both `hermes dashboard` and `hermes serve`; enforced per request afterwards.
- **What it does:** Requires a registered authentication provider whenever the dashboard is reachable from anywhere but loopback, and refuses to start otherwise.
- **How it works:** `web_server.py:19553 start_server`. `app.state.trusted_public_hosts = _dashboard_public_hosts()` is resolved once so request middleware never reloads config. `app.state.auth_required = should_require_dashboard_auth(host, trusted_public_hosts)` (`:820`) = `should_require_auth(host) or any(candidate not in _LOOPBACK_HOST_VALUES for candidate in trusted_public_hosts)` — so a non-loopback `dashboard.public_url` engages the gate even on a loopback bind. Exception: `_desktop_loopback_auth_exempt(host, ssh_session_token, ssh_owner_nonce)` (`:838`) exempts a Desktop-owned loopback backend, requiring ALL of a loopback bind, `HERMES_DESKTOP=1`, and one operator-minted credential (`HERMES_DASHBOARD_SESSION_TOKEN`, `--ssh-session-token-file`, or `--ssh-owner-nonce`). When gated and `dashboard_auth.list_providers()` is empty, startup raises `SystemExit` with `Refusing to bind dashboard to <host> — <gate reason>, but no auth providers are registered.` plus the bundled providers' `LAST_SKIP_REASON` lines (`  • nous: <reason>`) and a fix hint listing both paths (`  • Password: set dashboard.basic_auth.username + password_hash in config.yaml` with the exact `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('your-password'))"` recipe, and `  • OAuth: run 'hermes dashboard register' (Nous Portal) or install a DashboardAuthProvider plugin.`) plus `There is no unauthenticated public-dashboard option.` When the bind is loopback the message names `dashboard.public_url` as the sole trigger and adds the local-only escape (`remove dashboard.public_url from config.yaml (and unset HERMES_DASHBOARD_PUBLIC_URL)`). A configured-but-disabled `basic` plugin adds `The 'basic' dashboard-auth plugin is in plugins.disabled but dashboard.basic_auth is configured.` Success logs `Dashboard binding to %s with auth gate enabled. Providers: %s`. `app.state.bound_host = host` then lets `host_header_middleware` validate incoming Host headers against the bind (DNS-rebinding defence, GHSA-ppp5-vxwm-4cf7).
- **Inputs / options:** n/a (driven by `--host` and config).
- **Outputs / side effects:** Refuses to start, or enables cookie-based auth for every non-public `/api/` route.
- **Config / env:** `dashboard.public_url`, `HERMES_DASHBOARD_PUBLIC_URL`, `dashboard.basic_auth.*`, `dashboard.oauth.*`, `HERMES_DASHBOARD_OAUTH_CLIENT_ID`, `plugins.disabled`, `HERMES_DESKTOP`.
- **Edge cases / guards:** `proxy_headers` is enabled on uvicorn ONLY when the gate is active (otherwise `X-Forwarded-For` would defeat the loopback peer check); `forwarded_allow_ips` defaults to `("127.0.0.1", "::1")` and is extended only by explicit IPs/CIDRs from `dashboard.trusted_proxies` (`_dashboard_forwarded_allow_ips`, `:19496`).
- **Rebuild notes:** Compute the exposure boundary from bind host AND declared public URL; refuse rather than degrade.

### Dashboard session token (`X-Hermes-Session-Token`)  `id: cli-f.dashboard.session-token`
- **Surface:** API / Core
- **Where:** The header `X-Hermes-Session-Token` (legacy: `Authorization: Bearer <token>`); injected into the SPA as `window.__HERMES_SESSION_TOKEN__`.
- **What it does:** Authenticates the local web UI (and the desktop shell) against sensitive `/api/` endpoints on an ungated loopback bind.
- **How it works:** `web_server.py:588-593` — `_resolve_session_token()` returns `HERMES_DASHBOARD_SESSION_TOKEN` when the desktop shell minted one, else `secrets.token_urlsafe(32)` generated fresh per process; `_SESSION_HEADER_NAME = "X-Hermes-Session-Token"`. `_apply_ssh_session_token(token)` (`:598`) overrides it for a Desktop SSH backend. `_has_valid_session_token(request)` (`:700`) compares the dedicated header with `hmac.compare_digest`, falling back to `Authorization: Bearer <token>`. `_has_valid_query_token(request, path)` (`:728`) additionally accepts `?token=` for the narrow allowlist `_QUERY_TOKEN_API_PATHS = {"/api/files/download"}` (OS-shell-opened download links cannot set a header). `_require_token(request)` (`:736`) defers entirely to the gate when `app.state.auth_required` is true — in gated mode the token is NOT injected and the SPA authenticates with a session cookie, so requiring the absent token would 401 every cookie-authenticated request.
- **Inputs / options:** the header value.
- **Outputs / side effects:** Injected into `index.html` (`_serve_index`, `web_server.py:17889`) as `<script>window.__HERMES_SESSION_TOKEN__="…";window.__HERMES_DASHBOARD_EMBEDDED_CHAT__=…;window.__HERMES_BASE_PATH__="…";window.__HERMES_AUTH_REQUIRED__=…;</script>`; in gated mode only the latter three are emitted.
- **Config / env:** `HERMES_DASHBOARD_SESSION_TOKEN`.
- **Edge cases / guards:** A dedicated header avoids collisions with reverse proxies that already use `Authorization` (e.g. Caddy `basic_auth`). The token dies with the process. WebSocket paths accept `?token=<token>` only on loopback/ungated binds; once the gate is engaged a ticket is required instead (`:16406-16504`).
- **Rebuild notes:** Inject the token into the page rather than exposing a token-dispensing endpoint; use constant-time comparison.

### Backend ready sentinels and ready file  `id: cli-f.serve.ready`
- **Surface:** CLI / Core
- **Where:** stdout of `hermes dashboard` / `hermes serve`, and the file named by `HERMES_DESKTOP_READY_FILE`.
- **What it does:** Tells the spawning process (the desktop app, a script) the exact port the backend bound to, including ephemeral `--port 0` binds.
- **How it works:** `web_server.py:19905-19945`. After `server.startup()` the real bound port is read from the live socket (`_read_bound_port`), stored on `app.state.bound_port`, registered in the spawn ledger via `process_identity.register_self("serve"|"dashboard", detail={host, port, profile})` and `attach_self_to_kill_on_close_job()` (Windows job object so the child tree dies with the backend), then `_write_dashboard_ready_file(actual_port)` (`:19211`) atomically writes `{"port": <n>}` to `HERMES_DESKTOP_READY_FILE` (tempfile + fsync + `os.replace`), and `_write_machine_sentinel_line(f"{ready_token} port={actual_port}")` writes `HERMES_BACKEND_READY port=<n>` (headless) or `HERMES_DASHBOARD_READY port=<n>` (dashboard) directly to fd 1 — NOT through `sys.stdout`, which `tui_gateway.server` redirects to stderr at import time to keep stray prints off the JSON-RPC stream.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The sentinel line, plus `  Hermes backend listening on <host>:<port>` (headless, `flush=True`) or `  Hermes Web UI → http://<host>:<port>`.
- **Config / env:** `HERMES_DESKTOP_READY_FILE`.
- **Edge cases / guards:** Under `pythonw.exe` (Windows, no console) fd 1 may be invalid; the sentinel writer falls back to `print()` for human visibility and the desktop relies on the ready FILE for port discovery.
- **Rebuild notes:** Announce the bound port after the socket is live, never before; use a fd-level write so stream redirection cannot swallow it.

### Port-conflict detection (`BACKEND_PORT_IN_USE`)  `id: cli-f.serve.port-conflict`
- **Surface:** CLI / Core
- **Where:** Startup of `hermes dashboard` / `hermes serve` with an explicit non-zero `--port`.
- **What it does:** Turns "port already taken" from an indistinguishable exit-1 error into a stable machine sentinel and a distinct exit code.
- **How it works:** `web_server.py:19393-19494`. `PORT_IN_USE_EXIT_CODE = 75`; `_PORT_IN_USE_SENTINEL = "BACKEND_PORT_IN_USE port={port}"`. `_port_bind_conflict(host, port)` (`:19410`) skips `port == 0`, picks `AF_INET6` when the host contains `:`, and on Windows sets `SO_EXCLUSIVEADDRUSE` (because `SO_REUSEADDR` there means "bind over anyone" and could never detect a conflict) while on POSIX it sets `SO_REUSEADDR` to match uvicorn's own bind flags exactly; `_is_addr_in_use_error` accepts `errno.EADDRINUSE`, 98, 48, 10048 and `winerror == 10048`. The probe runs before `uvicorn.Server` is served, and again as a translation of uvicorn's own `SystemExit(1)` to cover the probe-to-bind race.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `BACKEND_PORT_IN_USE port=<n>` on fd 1 plus `  Port <n> on <host> is already in use — likely another 'hermes serve' / 'hermes dashboard' backend or the Hermes gateway. Stop the other process, or pass --port <other> (--port 0 picks a free ephemeral port).`; exit code 75.
- **Config / env:** n/a.
- **Edge cases / guards:** `--port 0` can never conflict and is unaffected.
- **Rebuild notes:** Probe with the same socket options the real server will use, or the probe lies.

### `hermes serve`  `id: cli-f.serve`
- **Surface:** CLI
- **Where:** `hermes serve [-h] [--port PORT] [--host HOST] [--insecure] [--skip-build] [--isolated] [--stop] [--status] [--ssh-session-token-file PATH] [--ssh-owner-nonce NONCE]`. Root help `serve               Start the Hermes backend server (headless; powers the desktop app and remote backends)`; description `Run the Hermes backend server — the JSON-RPC/WebSocket gateway the desktop app and remote clients connect to. Headless: it never opens a browser UI.`
- **What it does:** Runs the same server as `hermes dashboard` but headless — no web UI build, no SPA, no browser — for the Electron desktop app and remote backends.
- **How it works:** Parser `subcommands/dashboard.py:136-170` — the same `_add_server_runtime_args`, plus a hidden `--no-open` (accepted for legacy desktop spawns), `--ssh-session-token-file`, `--ssh-owner-nonce`, and `set_defaults(func=cmd_dashboard, no_open=True, headless_backend=True)`. `cmd_dashboard` exports `HERMES_SERVE_HEADLESS=1` before importing `web_server`, which makes `mount_spa` (`web_server.py:17820`) install a catch-all `GET /{full_path:path}` returning `{"error": "Headless backend (hermes serve): web UI disabled — use \`hermes dashboard\` for the browser UI."}` with status 404 — EXCEPT at the exact root path on an ungated bind, where it serves a minimal token-only HTML page carrying `window.__HERMES_SESSION_TOKEN__` and `window.__HERMES_AUTH_REQUIRED__=false` with `Cache-Control: no-store, no-cache, must-revalidate`, so the Electron shell's boot handshake (`apps/desktop/electron/dashboard-token.ts`) can adopt the live token after an update replaced the backend. On a gated serve the 404 stays, so the token is never readable without auth.
- **Inputs / options:** `-h, --help`; `--port PORT`; `--host HOST`; `--insecure`; `--skip-build`; `--isolated`; `--stop`; `--status`; `--open-profile` (hidden); `--no-open` (hidden, redundant); `--ssh-session-token-file PATH`; `--ssh-owner-nonce NONCE`.
- **Outputs / side effects:** Prints `HERMES_BACKEND_READY port=<n>` and `  Hermes backend listening on <host>:<port>`; registers itself as purpose `serve` in the spawn ledger.
- **Config / env:** all `dashboard.*` keys apply; `HERMES_SERVE_HEADLESS`, `HERMES_DESKTOP`, `HERMES_PARENT_PID` (parent-death watchdog), `HERMES_DESKTOP_CHILD_PID`.
- **Edge cases / guards:** Startup also reaps corpses from a prior unclean Desktop exit — `dashboard_procs._reap_orphaned_desktop_local_serves()` when `HERMES_DESKTOP=1`, and `process_identity.reap_orphaned_mcp_helpers()` always (positive spawn-ledger identity only: a helper whose spawner is alive or unprovable is never touched). `install_exit_flush_signal_handlers()` from `tui_gateway.server` is installed BEFORE uvicorn's `capture_signals()` so in-memory transcripts are flushed to `state.db` on SIGTERM/SIGINT. On loopback binds the WS protocol ping is DISABLED (`ws_ping_interval=None`) because a GIL-bound turn can stall the loop for minutes and a missed pong would kill a healthy local socket; non-loopback binds keep `dashboard.ws_ping_interval`/`ws_ping_timeout` (20/20 default) to stay under a Cloudflare Tunnel's ~100 s idle window. `ws_max_size = _DESKTOP_ATTACHMENT_WS_MAX_BYTES = 384 * 1024 * 1024`. A loop-heartbeat watchdog re-arms every 2 s and logs `event loop stalled %.1fs (GIL pressure suspected)` past a 5 s drift. On Windows the serve loop is run through uvicorn's own `asyncio_run` + `config.get_loop_factory()` because `asyncio.run`'s default ProactorEventLoop binds a socket that never accepts.
- **Rebuild notes:** One server, two framings; make "headless" a hard switch that disables the SPA mount rather than a hint.

### `hermes serve --ssh-session-token-file PATH`  `id: cli-f.serve.ssh-token-file`
- **Surface:** CLI
- **Where:** `hermes serve --ssh-session-token-file PATH` — help `Read a one-shot Desktop SSH session token from PATH` (argparse `dest="ssh_session_token_file"`, `metavar="PATH"`).
- **What it does:** Reads (and consumes) a one-shot session token the Desktop SSH client wrote into a private runtime directory, so a remote backend can authenticate its owner without the token ever appearing in argv or the environment.
- **How it works:** `main.py:11891 _read_ssh_session_token_file(path)`. On Windows it delegates to `hermes_cli.windows_ssh_runtime.read_token`. On POSIX it enforces, in order: the path must be absolute; it must be under `Path.home()/".hermes"/"desktop-ssh"` (anchored to the OS home, NOT `get_hermes_home()`, so a non-default sticky profile or a Docker `/opt/data` root cannot reject a legitimate token); the relative part must be exactly two components with the directory matching `^[0-9a-f]{32}$` and the file matching `^[0-9a-f]{16}\.token$`; every `open` uses `O_NOFOLLOW` (+ `O_DIRECTORY` for the dirs); the runtime root and the per-session directory must be directories owned by the current uid, and the session directory's mode must be exactly `0o700`; the token file must be a regular file of exactly 64 bytes owned by the current uid with no bits outside `0o600`; the content must match `^[0-9a-f]{64}$`. The file is UNLINKED in the `finally` block (one-shot). `start_server` then calls `_apply_ssh_session_token(token)` which replaces the module-level `_SESSION_TOKEN`.
- **Inputs / options:** `--ssh-session-token-file PATH`.
- **Outputs / side effects:** The token file is deleted; the process's session token becomes the supplied value. Never persisted, never exported to children.
- **Config / env:** n/a.
- **Edge cases / guards:** Rejected with `SystemExit` and one of the exact messages `--ssh-session-token-file cannot be used with --status or --stop`, `--ssh-session-token-file is only valid with hermes serve`, `--ssh-session-token-file must be absolute`, `--ssh-session-token-file must be under the desktop-ssh directory`, `--ssh-session-token-file has an invalid runtime path`, `--ssh-session-token-file has an invalid filename`, `--ssh-session-token-file has an unsafe runtime root`, `--ssh-session-token-file runtime root has the wrong owner`, `--ssh-session-token-file has an unsafe parent directory`, `--ssh-session-token-file parent has the wrong owner`, `--ssh-session-token-file parent has unsafe permissions`, `--ssh-session-token-file is a symlink`, `--ssh-session-token-file is not accessible`, `--ssh-session-token-file is not a regular file`, `--ssh-session-token-file contains an invalid token`, `--ssh-session-token-file has the wrong owner`, `--ssh-session-token-file has unsafe permissions`.
- **Rebuild notes:** File-based one-shot secrets need `O_NOFOLLOW`, fd-relative opens, ownership and mode checks, a fixed size, and an unlink — anything less is a symlink race.

### `hermes serve --ssh-owner-nonce NONCE`  `id: cli-f.serve.ssh-owner-nonce`
- **Surface:** CLI
- **Where:** `hermes serve --ssh-owner-nonce NONCE` — help `Identify a Desktop-owned SSH backend process` (argparse `dest="ssh_owner_nonce"`, `metavar="NONCE"`).
- **What it does:** Marks this backend as owned by a specific Desktop SSH client session, so ownership survives a venv replacement and the loopback auth exemption can apply.
- **How it works:** Validated in `cmd_dashboard` (`main.py:12026-12028`) against `^[0-9a-f]{16}$`; passed to `start_server(ssh_owner_nonce=…)` → `web_server._apply_ssh_owner_nonce(nonce)` (`:604`) which stores `_SSH_OWNER_NONCE` and derives `_SSH_RUNTIME_PURELIB` / `_SSH_RUNTIME_MARKER` — a marker FILE written into the interpreter's `sysconfig.get_paths()["purelib"]` now, so a replaced venv (recreated with the same or a different Python version) loses it deterministically while pip installs into the live venv leave it untouched. A bare `(dev, ino)` snapshot of the directory is explicitly not sufficient because ext4 reuses directory inodes immediately.
- **Inputs / options:** `--ssh-owner-nonce NONCE` (16 lowercase hex characters).
- **Outputs / side effects:** Process-local only; never persisted or exported to children. Counts as an operator-minted credential for `_desktop_loopback_auth_exempt`.
- **Config / env:** n/a.
- **Edge cases / guards:** An invalid value raises `SystemExit("--ssh-owner-nonce must be 16 lowercase hex characters")`.
- **Rebuild notes:** Prove liveness of a runtime with a file inside the runtime, not with inode identity.

---

## 10. `hermes desktop` / `hermes gui` — the Electron app

### `hermes desktop` (alias `hermes gui`)  `id: cli-f.desktop`
- **Surface:** CLI / Desktop app
- **Where:** `hermes desktop [-h] [--source] [--build-only] [--fake-boot] [--ignore-existing] [--hermes-root HERMES_ROOT] [--cwd CWD] [--skip-build] [--force-build] [--setup-tcc-identity] [--identity IDENTITY]`; `hermes gui` is an argparse alias and its `--help` renders the identical `usage: hermes desktop …` block. Root help `Build and launch the native desktop app`; description `Launch the Hermes Electron desktop app. By default this installs workspace Node dependencies, builds the current OS's unpacked Electron app, then launches that packaged artifact.`
- **What it does:** Installs the Node workspace dependencies, builds the Electron app for the current OS, and launches it.
- **How it works:** Parser `hermes_cli/subcommands/gui.py:12-80 build_gui_parser` (`add_parser("desktop", aliases=["gui"])`, `set_defaults(func=cmd_gui)`). Handler `main.py:8318 cmd_gui`: requires `apps/desktop/package.json` (`Desktop GUI source not found at: <dir>`, exit 1); `hermes_logging.setup_logging(mode="gui")`; builds the child env from `hermes_constants.with_hermes_node_path()` and sets `HERMES_DESKTOP_BOOT_FAKE`, `HERMES_DESKTOP_IGNORE_EXISTING`, `HERMES_DESKTOP_HERMES_ROOT`, `HERMES_DESKTOP_CWD` (defaulting to `os.getcwd()`) from the flags; reads `_desktop_launch_options()` (`main.py:8243`) → `(electron_flags, disable_gpu, password_store, ozone_hint)` from `desktop.electron_flags` (string is `shlex.split`, list is stringified), `desktop.disable_gpu` (bool or `1/true/yes/on` → `"1"`, `0/false/no/off` → `"0"`, anything else `auto`), `desktop.password_store` (validated against `_LINUX_PASSWORD_STORES`), `desktop.ozone_platform_hint` (`auto|x11|wayland`), bridging non-`auto` values into `HERMES_DESKTOP_DISABLE_GPU` and `ELECTRON_OZONE_PLATFORM_HINT` only when the env var is not already set; on Linux resolves the Chromium keychain backend via config or `_detect_linux_password_store()` (`main.py:8203` — `KDE_SESSION_VERSION` 6/5/other → `kwallet6`/`kwallet5`/`kwallet`, `KDE_FULL_SESSION` → `kwallet`, `GNOME_KEYRING_CONTROL` → `gnome-libsecret`, else a 2 s `dbus-send` ping of `org.freedesktop.secrets` → `gnome-libsecret`, else `None`) into `HERMES_DESKTOP_PASSWORD_STORE`. Then `--setup-tcc-identity` exits early; `_desktop_packaged_executable(desktop_dir)` (`main.py:6970`) locates the unpacked app (`release/mac*/Hermes.app/Contents/MacOS/Hermes`; `release/win-unpacked|win-ia32-unpacked|win-arm64-unpacked/Hermes.exe` with PE-machine matching against the host so a stale cross-arch tree is never launched; `release/linux-unpacked|linux-arm64-unpacked/hermes|Hermes`); `_resolve_node_runtime_npm()` is required unless `--skip-build` in packaged mode; `_desktop_build_needed()` (`:6908`) compares `<HERMES_HOME>/desktop-build-stamp.json` (`{contentHash, sourceMode, builtAt}`) against `_compute_desktop_content_hash(project_root)` and also forces a rebuild when the artifact is missing or the renderer bundle is torn; the build runs `_run_npm_install_deterministic(npm, PROJECT_ROOT)` then `npm run build` (source) or `npm run pack` (packaged), with three recovery layers — purge + redownload the Electron dist, retry via `_ELECTRON_FALLBACK_MIRROR = "https://npmmirror.com/mirrors/electron/"`, and on Windows `_ensure_desktop_exe_launchable` which rolls back to the `.bak` tree left by `before-pack.mjs` when the produced `Hermes.exe` cannot load; `_desktop_macos_relaunchable_fixup` re-signs ad-hoc builds so an in-place self-update does not make macOS report "Hermes is damaged"; `_write_desktop_build_stamp`. Finally `_register_linux_desktop_entry()` (`:8299`) installs the XDG launcher entry, then either `--build-only` returns, or source mode runs `npm exec -- electron .` in `apps/desktop`, or the packaged executable is launched with `_desktop_linux_sandbox_fixup` (falling back to appending `--no-sandbox` when the host restricts unprivileged user namespaces) plus `config_electron_flags`.
- **Inputs / options:** `-h, --help`; `--source`; `--build-only`; `--fake-boot`; `--ignore-existing`; `--hermes-root HERMES_ROOT`; `--cwd CWD`; `--skip-build`; `--force-build`; `--setup-tcc-identity`; `--identity IDENTITY` (default `Hermes Local Signing`).
- **Outputs / side effects:** Writes `apps/desktop/dist`, `apps/desktop/release`, `node_modules`, `<HERMES_HOME>/desktop-build-stamp.json`, and on Linux an XDG `.desktop` entry (`✓ Desktop launcher entry installed: <path>` / `⚠ Could not install the desktop launcher entry: <exc>`). Progress lines: `✓ Desktop <source build|packaged app> is up to date (content stamp matches)`, `→ Installing desktop workspace dependencies...`, `→ Building desktop <label>...`, `  → No Developer ID configured; ad-hoc signing this local rebuild (CSC_IDENTITY_AUTO_DISCOVERY=false)`, `  ⚠ Stopped running desktop app to free the build output (pid <ids>)`, `  ⚠ Desktop build failed; refreshed the Electron download and retrying once...`, `  ⚠ Desktop build still failing; the Electron download from GitHub looks blocked. Re-downloading via a public mirror (npmmirror.com)... (set ELECTRON_MIRROR to use another mirror)`, `→ Launching Hermes Desktop from source build...`, `→ Launching packaged Hermes Desktop: <command>`, `⚠ Falling back to --no-sandbox because this Linux host restricts unprivileged user namespaces and the Electron sandbox helper could not be configured.` The process exits with the launched app's return code.
- **Config / env:** `desktop.electron_flags`, `desktop.disable_gpu`, `desktop.ozone_platform_hint`, `desktop.password_store`, `desktop.macos_signing_identity`, `desktop.repo_scan_enabled`, `desktop.repo_scan_roots`, `desktop.repo_scan_exclude_paths`, `desktop.auto_continue.*`. Env written: `HERMES_DESKTOP_BOOT_FAKE`, `HERMES_DESKTOP_IGNORE_EXISTING`, `HERMES_DESKTOP_HERMES_ROOT`, `HERMES_DESKTOP_CWD`, `HERMES_DESKTOP_DISABLE_GPU`, `ELECTRON_OZONE_PLATFORM_HINT`, `HERMES_DESKTOP_PASSWORD_STORE`; env read: `ELECTRON_MIRROR`, `KDE_SESSION_VERSION`, `KDE_FULL_SESSION`, `GNOME_KEYRING_CONTROL`.
- **Edge cases / guards:** Missing npm → `Desktop GUI requires Node.js/npm, but npm was not found on PATH.` + `Install Node.js, then run:  hermes gui`, exit 1. A build failure prints `✗ Desktop GUI build failed`, `  Run manually:  cd apps/desktop && npm run <script>`, the Windows "Access is denied" hint, and `  If the log shows Electron download retries, rebuild via a mirror:` + `    ELECTRON_MIRROR=<mirror-base-url> hermes desktop --force-build`.
- **Rebuild notes:** Content-hash stamp → conditional build → launch. A better version would ship signed release artifacts so end users never need Node at all.

### `hermes desktop --source`  `id: cli-f.desktop.source`
- **Surface:** CLI
- **Where:** `hermes desktop --source` — help `Launch via 'electron .' against apps/desktop/dist instead of the packaged app`.
- **What it does:** Runs the app from the development build (`apps/desktop/dist`) instead of the packaged unpacked Electron artifact.
- **How it works:** `main.py:8375 source_mode`; the build script becomes `build` instead of `pack`; the launch becomes `subprocess.run([npm, "exec", "--", "electron", "."], cwd=apps/desktop)` and the process exits with its return code. `_desktop_build_needed` checks `_desktop_dist_exists(desktop_dir)` rather than the packaged executable, and the build stamp records `sourceMode: true` so switching modes forces a rebuild.
- **Inputs / options:** `--source` (`store_true`); combines with `--skip-build`, `--build-only`, `--force-build`.
- **Outputs / side effects:** Uses `apps/desktop/dist`.
- **Config / env:** n/a.
- **Edge cases / guards:** `--skip-build --source` additionally requires the workspace deps: `✗ --skip-build --source requires existing desktop workspace dependencies.` + `  Install first:  cd <root> && npm ci` + `  Or drop --skip-build to install dependencies and build automatically.`; a missing dist prints `✗ --skip-build --source was passed but no desktop dist found at: <dir>/dist` + `  Pre-build first:  cd apps/desktop && npm run build`.
- **Rebuild notes:** n/a.

### `hermes desktop --build-only`  `id: cli-f.desktop.build-only`
- **Surface:** CLI
- **Where:** `hermes desktop --build-only` — help `Build the desktop app but do not launch it (used by the installer's --update flow)`.
- **What it does:** Produces the desktop artifact and returns without launching.
- **How it works:** `main.py:8563-8579`. The installer's `--update` flow drives the rebuild headlessly and then launches the desktop itself, detached, after the old executable has exited — launching here would block the installer and, on Windows, the old exe is still being replaced. The branch verifies the expected artifact exists so a silent "built nothing" cannot slip past.
- **Inputs / options:** `--build-only` (`store_true`).
- **Outputs / side effects:** `✓ Desktop source build ready at <dir>/dist (not launching; --build-only)` or `✓ Desktop packaged app ready: <exe> (not launching; --build-only)`; failures `✗ --build-only --source produced no dist at: <dir>/dist` (exit 1) and `✗ --build-only produced no launchable app at: <dir>/release` + `  Expected an unpacked Electron app for the current OS.` (exit 1).
- **Config / env:** n/a.
- **Edge cases / guards:** Runs AFTER `_register_linux_desktop_entry()`, so the launcher entry is installed even on a build-only run.
- **Rebuild notes:** Verify the artifact after every build step; never trust a zero exit code alone.

### `hermes desktop --fake-boot`  `id: cli-f.desktop.fake-boot`
- **Surface:** CLI
- **Where:** `hermes desktop --fake-boot` — help `Enable deterministic desktop boot delays for validating startup UI`.
- **What it does:** Makes the desktop app insert deterministic delays during boot so the startup UI (splash, progress states) can be validated.
- **How it works:** `main.py:8335-8336` sets `env["HERMES_DESKTOP_BOOT_FAKE"] = "1"` for the launched Electron process.
- **Inputs / options:** `--fake-boot` (`store_true`).
- **Outputs / side effects:** Slower, deterministic boot.
- **Config / env:** `HERMES_DESKTOP_BOOT_FAKE`.
- **Edge cases / guards:** Development/QA only.
- **Rebuild notes:** n/a.

### `hermes desktop --ignore-existing`  `id: cli-f.desktop.ignore-existing`
- **Surface:** CLI
- **Where:** `hermes desktop --ignore-existing` — help `Force Desktop to ignore any hermes CLI already on PATH during backend resolution`.
- **What it does:** Makes the desktop app resolve its backend from the source root instead of adopting whatever `hermes` is on PATH.
- **How it works:** `main.py:8337-8338` sets `env["HERMES_DESKTOP_IGNORE_EXISTING"] = "1"`.
- **Inputs / options:** `--ignore-existing` (`store_true`).
- **Outputs / side effects:** Changes which `hermes serve` the desktop spawns.
- **Config / env:** `HERMES_DESKTOP_IGNORE_EXISTING`.
- **Edge cases / guards:** Useful when a globally installed Hermes would otherwise shadow the checkout under test.
- **Rebuild notes:** n/a.

### `hermes desktop --hermes-root HERMES_ROOT`  `id: cli-f.desktop.hermes-root`
- **Surface:** CLI
- **Where:** `hermes desktop --hermes-root <path>` — help `Override the Hermes source root used by Desktop (sets HERMES_DESKTOP_HERMES_ROOT)`.
- **What it does:** Points the desktop app at a different Hermes source checkout.
- **How it works:** `main.py:8339-8340` sets `env["HERMES_DESKTOP_HERMES_ROOT"] = str(Path(args.hermes_root).expanduser().resolve())`.
- **Inputs / options:** `--hermes-root HERMES_ROOT` (string, no default).
- **Outputs / side effects:** none locally; the child Electron process resolves its backend there.
- **Config / env:** `HERMES_DESKTOP_HERMES_ROOT`.
- **Edge cases / guards:** The path is expanded and resolved before being exported.
- **Rebuild notes:** n/a.

### `hermes desktop --cwd CWD`  `id: cli-f.desktop.cwd`
- **Surface:** CLI
- **Where:** `hermes desktop --cwd <path>` — help `Initial project directory for Desktop chat sessions (sets HERMES_DESKTOP_CWD)`.
- **What it does:** Sets the project directory new desktop chat sessions start in.
- **How it works:** `main.py:8341-8344` sets `env["HERMES_DESKTOP_CWD"]` to the expanded+resolved path, or to `os.getcwd()` when the flag is absent.
- **Inputs / options:** `--cwd CWD`.
- **Outputs / side effects:** none locally.
- **Config / env:** `HERMES_DESKTOP_CWD`.
- **Edge cases / guards:** Always set — the default is the launching shell's cwd, so `hermes desktop` from a repo opens that repo.
- **Rebuild notes:** n/a.

### `hermes desktop --skip-build` / `--force-build`  `id: cli-f.desktop.build-control`
- **Surface:** CLI
- **Where:** `hermes desktop --skip-build`, `hermes desktop --force-build`.
- **What it does:** `--skip-build` launches the existing unpacked app from `apps/desktop/release` (or the existing `dist` with `--source`) without any npm work. `--force-build` rebuilds even when the content stamp matches.
- **How it works:** `main.py:8375-8425`. `--skip-build` also skips resolving npm entirely in packaged mode. `--force-build` short-circuits `_desktop_build_needed(...)` to true.
- **Inputs / options:** `--skip-build` (`store_true`), `--force-build` (`store_true`).
- **Outputs / side effects:** `→ Skipping desktop package build (--skip-build); using <exe>` or `→ Skipping desktop source build (--skip-build --source); using dist at <dir>`; failure `✗ --skip-build was passed but no packaged desktop app was found at: <dir>/release` + `  Pre-build first:  cd apps/desktop && npm run pack` + `  Or drop --skip-build to package automatically.` (exit 1).
- **Config / env:** the stamp file `<HERMES_HOME>/desktop-build-stamp.json`.
- **Edge cases / guards:** The stamp is ignored when the renderer bundle is torn — `  ⚠ A previous update left the desktop bundle incomplete (<dir>); rebuilding it`.
- **Rebuild notes:** Hash the SOURCE tree, but validate the OUTPUT; a stamp alone cannot detect a half-written bundle.

### `hermes desktop --setup-tcc-identity` / `--identity`  `id: cli-f.desktop.tcc-identity`
- **Surface:** CLI (macOS only)
- **Where:** `hermes desktop --setup-tcc-identity [--identity "<cert name>"]`.
- **What it does:** Creates (or reuses) a self-signed code-signing certificate in the login keychain, points `desktop.macos_signing_identity` at it, and re-signs the packaged app so macOS TCC grants (Full Disk Access, Accessibility, Files and Folders, microphone) survive rebuilds.
- **How it works:** `main.py:8383-8387` runs it as a one-shot before any build and exits `0`/`1`. `main.py:7921 _desktop_macos_setup_tcc_identity(identity)`: non-macOS prints `  (--setup-tcc-identity is macOS-only; skipping)` and returns False; requires `openssl`, `security` and `codesign` on PATH (`  (--setup-tcc-identity requires openssl, security, and codesign; found openssl=<b> security=<b> codesign=<b>)`); probes `_macos_codesigning_identity_valid(security, identity)` with `security find-identity -v` so a previously imported-but-untrusted certificate is repaired rather than reported as done; otherwise generates a 10-year self-signed cert with `openssl req -x509 -newkey rsa:2048 -days 3650 -nodes -subj /CN=<identity> -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,digitalSignature,keyCertSign -addext extendedKeyUsage=codeSigning`, exports a PKCS#12 with passphrase `hermeslocal` (retrying with `-legacy` when macOS `security import` rejects the OpenSSL 3 AES/SHA-2 format with "MAC verification failed during PKCS12 import"), and imports it into `~/Library/Keychains/login.keychain-db` with `-T <codesign> -T /usr/bin/codesign_allocate` so signing needs no interactive unlock. Then it writes `desktop.macos_signing_identity` to `config.yaml` and re-signs the packaged app.
- **Inputs / options:** `--setup-tcc-identity` (`store_true`); `--identity IDENTITY` (default `Hermes Local Signing`).
- **Outputs / side effects:** A new keychain certificate; a config write; a re-signed app bundle. Exit 0 on success (including "already configured"), 1 on failure.
- **Config / env:** writes `desktop.macos_signing_identity`.
- **Edge cases / guards:** Idempotent — safe to re-run after updates. Never raises.
- **Rebuild notes:** TCC grants bind to the code-signing identity, not the path — a certificate-anchored ad-hoc identity is the only way to keep permissions across local rebuilds.

---

## Handoffs

- `hermes -p` / `--profile` / `--profile=` global pre-argparse selector and `PRE_ARGPARSE_INHERITED_FLAGS` — already documented as `cli-a.opt-profile`; this shard only references it.
- `hermes backup` / `hermes import` (the restore side of `updates.pre_update_backup: full` zips and of `create_quick_snapshot`) — backup/restore shard.
- `hermes gateway` family (`start`, `stop`, `run`, `restart`, `uninstall`, `migrate-legacy`) that `hermes update`, `profile delete` and `uninstall` shell out to — gateway CLI shard.
- `hermes config migrate` / `hermes config` (the `--yes` update path defers API-key entry to it) and the full `updates.*`, `dashboard.*`, `desktop.*` key catalogue — config shards.
- `hermes skills` and `tools/skills_sync.py sync_skills()` (invoked by `seed_profile_skills` and by the update's all-profile skill sync) — skills shard.
- `hermes model` / `hermes setup` / `hermes auth add nous` (invoked by `hermes acp --setup` and required by `hermes dashboard register`) — cli-a/cli-b shards.
- `hermes cron list` (referenced by `profile install`/`update` when a distribution ships cron files) — cron shard.
- `hermes plugins enable/disable` and `plugins.disabled` handling, plus the `plugins/dashboard_auth/{basic,nous}` provider plugins and `hash_password` — plugins shard.
- The web dashboard SPA itself (Profiles page, Update button, Config page, theme system, `/login` page) — web-a/web-b/web-c shards.
- Dashboard HTTP/WS API surface referenced here: `POST /api/hermes/update`, `DELETE /api/profiles/<name>`, `/api/ws`, `/api/pty`, `/api/files/download`, `/api/auth/me`, `/api/dashboard/themes`, `/api/config/schema`, and the `hermes_cli/dashboard_auth/*` routers and ticket flow — API shard.
- The Electron desktop application itself (`apps/desktop/**`: renderer, `electron/remote-lifecycle.ts`, `electron/dashboard-token.ts`, `electron/update-marker.ts`, `before-pack.mjs`) — desktop-a/desktop-b/desktop-main/desktop-settings shards.
- The ACP adapter internals (`acp_adapter/{server,session,tools,events,permissions,edit_approval,provenance,auth}.py`) beyond the CLI entry point — ACP/tools shard.
- `hermes_cli/process_identity.py` spawn ledger (`register_self`, `attach_self_to_kill_on_close_job`, `reap_orphaned_mcp_helpers`) and `hermes_cli/dashboard_procs.py` orphan reaping — core/process-hygiene shard.
- `hermes_cli/linux_desktop_entry.py` (XDG entry install, icon hicolor copies, `refresh_desktop_databases`) — desktop/platform shard.
- `tui_gateway.server.install_exit_flush_signal_handlers`, `tui_gateway.loop_noise.install_loop_noise_filter`, `tui_gateway.server._make_agent` — gateway/TUI shard.
- `hermes_cli/image_provenance.py` (`/etc/hermes/image-provenance.json`) and `hermes_cli/config.py detect_install_method()` / `recommended_update_command()` — install/deployment shard.
- `agent.redact.redact_sensitive_text` and `security.redact_secrets` / `HERMES_REDACT_SECRETS` (used with `force=True` by profile export) — security shard.
- `plugins/memory/honcho/cli.clone_honcho_for_profile` and the Honcho host-block migration on profile rename — memory-plugins shard.
- `hermes_cli/resource_limits.apply_nofile_soft_limit()` and `runtime.nofile_soft_limit` — config/core shard.
- `hermes_cli/windows_ssh_runtime.read_token` and the Windows SSH runtime lock files (`~/.hermes/desktop-ssh/*`) — Windows/platform shard.
