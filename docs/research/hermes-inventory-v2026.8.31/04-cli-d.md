# CLI part D — hooks, doctor, verify, security, approvals, dump, debug, backup, checkpoints, import, import-agent, config, skin, console, pairing

This shard documents fifteen top-level `hermes` CLI command trees and every one of their sub-commands,
flags, positional arguments, prompts and on-disk side effects, as read from the live `--help` dumps in
`hermes_inv/cli_help/` and from the real implementation modules under `hermes-agent/hermes_cli/`.
It covers: `hermes hooks` (list/ls, test, revoke/remove/rm, doctor), `hermes doctor` (each of its named
checks and its `--fix` repairs and `--live` probes), `hermes verify`, `hermes security audit`,
`hermes approvals` (suggest, test), `hermes dump`, `hermes debug` (share, delete), `hermes backup`,
`hermes checkpoints` (status, list, prune, clear, clear-legacy), `hermes import`, `hermes import-agent`
(claude-code, codex), `hermes config` (show, edit, get, set, unset, path, env-path, check, migrate),
`hermes skin` (list, use, set), `hermes console` (every REPL command it offers) and `hermes pairing`
(list, approve, revoke, clear-pending).
Deliberately left to sibling shards: all other CLI commands (`setup`, `gateway`, `dashboard`, `run`,
`sessions`, `mcp`, `plugins`, `skills`, `model`, `auth`, `cron`, `kanban`, `update`, `uninstall`, …) →
`cli-a`/`cli-b`/`cli-c`; the config *keys* themselves (785 leaves of `DEFAULT_CONFIG`) → `config-a`/
`config-b`; the web dashboard's Config/Hooks/Security pages → `web-a`/`web-b`; gateway slash commands →
the gateway shard; tools/toolsets → the tools shard.

---

## 1. `hermes hooks` — shell-script hook inspection & consent

### hooks — command group  `id: cli-d.hooks`
- **Surface:** CLI
- **Where:** `hermes hooks` (also `hermes hooks --help`). Group help text: *"Inspect shell-script hooks declared in ~/.hermes/config.yaml, test them against synthetic payloads, and manage the first-use consent allowlist at ~/.hermes/shell-hooks-allowlist.json."* Short help in the root command list: *"Inspect and manage shell-script hooks"*.
- **What it does:** Umbrella command for the shell-hook subsystem: shows which hooks the config declares, whether each has been consented to, fires them against synthetic payloads, and removes consent records.
- **How it works:** Parser built by `hermes_cli/subcommands/hooks.py:12` `build_hooks_parser()`; dispatch in `hermes_cli/hooks.py:26` `hooks_command(args)` which switches on `args.hooks_action`. All heavy lifting is delegated to `agent/shell_hooks.py` (spec parsing, subprocess spawn, allowlist I/O). Hook definitions come from the `hooks:` block of `~/.hermes/config.yaml`; consent records live in `~/.hermes/shell-hooks-allowlist.json` (`agent/shell_hooks.py:168` `ALLOWLIST_FILENAME`, path built by `allowlist_path()` at `agent/shell_hooks.py:848` from `get_hermes_home()`).
- **Inputs / options:** `-h`, `--help`. Sub-commands: `list` (alias `ls`), `test`, `revoke` (aliases `remove`, `rm`), `doctor`.
- **Outputs / side effects:** With no sub-command it prints exactly two lines: `Usage: hermes hooks {list|test|revoke|doctor}` and `Run 'hermes hooks --help' for details.` (`hermes_cli/hooks.py:31-32`). Unknown sub-command prints `Unknown hooks subcommand: <sub>` (`hermes_cli/hooks.py:44`).
- **Config / env:** `hooks:` (config.yaml block), `hooks_auto_accept` (bool/str in cli-config), env `HERMES_ACCEPT_HOOKS` (`1|true|yes|on`), `HERMES_HOME` (relocates the allowlist).
- **Edge cases / guards:** The 37 valid hook events are `hermes_cli/plugins.py:163` `VALID_HOOKS`: `api_request_error`, `gateway_platform_event`, `kanban_task_blocked`, `kanban_task_claimed`, `kanban_task_completed`, `on_interim_message`, `on_kanban_dispatch_tick`, `on_kanban_task_updated`, `on_kanban_worker_exited`, `on_kanban_worker_spawned`, `on_kanban_worker_stale_claim`, `on_session_end`, `on_session_finalize`, `on_session_reset`, `on_session_start`, `on_skill_lifecycle`, `on_stream_delta`, `on_stream_end`, `on_stream_start`, `post_api_request`, `post_approval_response`, `post_llm_call`, `post_tool_call`, `pre_api_request`, `pre_approval_request`, `pre_command`, `pre_gateway_dispatch`, `pre_llm_call`, `pre_tool_call`, `pre_transcription`, `pre_verify`, `subagent_start`, `subagent_stop`, `transform_api_error_classification`, `transform_llm_output`, `transform_terminal_output`, `transform_tool_result`. `SHELL_UNSUPPORTED_HOOKS = {transform_api_error_classification}` — declaring it as a shell hook is refused with a warning (`agent/shell_hooks.py:390-398`) because `_parse_response` has no channel for its directive. `hooks.output_spill` and `hooks.outbound` are reserved sub-keys, not events (`agent/shell_hooks.py:388`).
- **Rebuild notes:** Model a hook as `(event, command, matcher?, timeout, fail_closed)`. Keep a JSON consent file keyed by `(event, command)` with `approved_at` and `script_mtime_at_approval`; refuse to run a hook that is not in it. Better: sign the script hash instead of the mtime, and offer per-hook dry-run sandboxes (seccomp/container) so `hooks test` never runs untrusted code with full user credentials.

### hermes hooks list / ls  `id: cli-d.hooks-list`
- **Surface:** CLI
- **Where:** `hermes hooks list`, alias `hermes hooks ls`. Help: *"List configured hooks with matcher, timeout, and consent status"*.
- **What it does:** Prints every shell hook declared under `hooks:` in `~/.hermes/config.yaml`, grouped by event, with matcher, timeout and whether the user has consented; then prints every configured outbound webhook.
- **How it works:** `hermes_cli/hooks.py:51` `_cmd_list()`. Loads config via `hermes_cli.config.load_config()`, gets specs from `agent.shell_hooks.iter_configured_hooks(cfg)` (`agent/shell_hooks.py:333`) and outbound targets from `agent.outbound_webhooks.iter_configured_targets(cfg)`. Builds a `by_event` dict, sorts event names, and loads the allowlist once (`shell_hooks.load_allowlist()`), collapsing it to a set of `(event, command)` pairs. For approved hooks it re-reads the full record with `allowlist_entry_for()` to print `approved_at` and to compare `script_mtime_at_approval` against the current `script_mtime_iso(command)`.
- **Inputs / options:** `-h`, `--help` only. No other flags.
- **Outputs / side effects:** Read-only. Exact strings emitted:
  - When there is neither a hook nor a webhook: `No shell hooks or outbound webhooks configured in ~/.hermes/config.yaml.` / `See `hermes hooks --help` or` / `    website/docs/user-guide/features/hooks.md` / `for the config schema and worked examples.`
  - When only webhooks exist: `No shell hooks configured in ~/.hermes/config.yaml.`
  - Header: `Configured shell hooks (<N> total):` then a blank line.
  - Per event: `  [<event>]`; per hook: `    - <command>[ matcher=<repr>] (timeout=<N>s, ✓ allowed)` or `… ✗ not allowlisted)`.
  - For approved hooks: `      approved_at: <iso>`; on mtime drift: `      ⚠ script modified since approval (was <iso>, now <iso>) — run `hermes hooks doctor` to re-validate`.
  - Webhook block: `Configured outbound webhooks (<N> total):`, then per target `  - <label>`, `      url:     <url>`, `      events:  <e1, e2>[ matcher=<repr>] (timeout=<N>s, signed|UNSIGNED)`.
- **Config / env:** Reads `hooks.<event>[]` entries (`command`, `matcher`, `timeout`, `fail_closed`/`failClosed`) and `hooks.outbound[]` (`url`, `events`, `secret`/`secret_env`, `matcher`, `timeout`, `name`). Allowlist path honours `HERMES_HOME`.
- **Edge cases / guards:** A hook whose script was edited after approval is flagged but still listed as `✓ allowed` (the runtime still fires it — the warning is advisory). `signed` vs `UNSIGNED` is purely `bool(target.secret)`. `target.label` falls back to the URL when no `name` is set (`agent/outbound_webhooks.py:139`).
- **Rebuild notes:** One pass over config + one read of the consent file; group by event and sort. A better version would also show last-fired timestamp, success/failure counters and average latency per hook, and would colour-code drift.

### hermes hooks test  `id: cli-d.hooks-test`
- **Surface:** CLI
- **Where:** `hermes hooks test <event> [--for-tool TOOL] [--payload-file FILE]`. Help: *"Fire every hook matching <event> against a synthetic payload"*.
- **What it does:** Runs, for real, every configured shell hook registered on `<event>`, feeding it a synthetic JSON payload shaped exactly like a production firing, and prints exit code, timing, stdout, stderr and the parsed Hermes-wire-shape directive.
- **How it works:** `hermes_cli/hooks.py:241` `_cmd_test()`. Validates `event` against `VALID_HOOKS`; picks a canned payload from the module-level `_DEFAULT_PAYLOADS` table (`hermes_cli/hooks.py:130-238`), falling back to `{"session_id": "test-session"}`; overrides `tool_name` with `--for-tool`; merges a JSON object from `--payload-file`; filters `iter_configured_hooks()` to that event and (for `pre_tool_call`/`post_tool_call`) to specs whose `matches_tool()` accepts `--for-tool`; then calls `agent.shell_hooks.run_once(spec, payload)` per spec. `run_once` (`agent/shell_hooks.py:1136`) routes through the *same* `_serialize_payload()` + `_spawn()` + `_evaluate_result()` used in production, so the stdin the script sees is identical to a live firing.
- **Inputs / options:**
  - positional `event` — hook event name (help example: *"e.g. pre_tool_call, pre_llm_call, subagent_stop"*).
  - `--for-tool FOR_TOOL` — *"Only fire hooks whose matcher matches this tool name (used for pre_tool_call / post_tool_call)"*; also overwrites `payload["tool_name"]`.
  - `--payload-file PAYLOAD_FILE` — *"Path to a JSON file whose contents are merged into the synthetic payload before execution"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Executes the hook subprocesses (real side effects!). Prints `Firing <N> hook(s) for event '<event>':`, then per hook `  → <command>` followed by one of: `      ✗ error: <msg>`, `      ✗ timed out after <s>s`, or `      exit=<rc>  elapsed=<s>s` plus optional `      stdout: <≤400 chars>`, `      stderr: <≤400 chars>`, and finally either `      parsed (Hermes wire shape): <json>` or `      parsed: <none — hook contributed nothing to the dispatcher>`. Truncation helper `_truncate(s, 400)` appends `...`.
- **Config / env:** Same `hooks:` block; no env of its own. The subprocess inherits the caller's environment.
- **Edge cases / guards:** Unknown event → `Unknown event: '<e>'` + `Valid events: <sorted comma list>` and return. Non-object payload file → `Warning: <path> is not a JSON object; ignoring`. Unreadable payload file → `Error reading payload file: <exc>` and return. No matching hooks → `No shell hooks configured for event: <event>` and, if `--for-tool` was given, `(with matcher filter --for-tool=<tool>)`. **`hooks test` does NOT check the allowlist** — unlike `hooks doctor` it will run a hook that has not been consented to.
- **Synthetic payload table (verbatim keys per event, `hermes_cli/hooks.py:130`):**
  - `pre_tool_call`: `tool_name="terminal"`, `args={"command":"echo hello"}`, `session_id="test-session"`, `task_id="test-task"`, `tool_call_id="test-call"`.
  - `post_tool_call`: the above plus `result='{"output": "hello"}'`, `duration_ms=42`.
  - `pre_llm_call`: `session_id`, `user_message="What is the weather?"`, `conversation_history=[]`, `is_first_turn=True`, `model="gpt-4"`, `platform="cli"`.
  - `post_llm_call`: `session_id`, `model="gpt-4"`, `platform="cli"`.
  - `pre_verify`: `session_id`, `platform="cli"`, `model="gpt-4"`, `coding=True`, `attempt=0`, `final_response="All done — the change is applied."`, `changed_paths=["src/app.tsx"]`.
  - `on_session_start`: `session_id`.
  - `on_session_end`: `session_id`, `task_id`, `turn_id="test-turn"`, `completed=True`, `failed=False`, `interrupted=False`, `turn_exit_reason="text_response(stop)"`, `model`, `platform`.
  - `on_session_finalize`: `session_id`.
  - `on_session_reset`: `session_id`.
  - `pre_api_request`: `session_id`, `task_id`, `platform="cli"`, `model="claude-sonnet-4-6"`, `provider="anthropic"`, `base_url="https://api.anthropic.com"`, `api_mode="anthropic_messages"`, `api_call_count=1`, `message_count=4`, `tool_count=12`, `approx_input_tokens=2048`, `request_char_count=8192`, `max_tokens=4096`.
  - `post_api_request`: `session_id`, `task_id`, `platform`, `model`, `provider`, `base_url`, `api_mode`, `api_call_count=1`, `api_duration=1.234`, `finish_reason="stop"`, `message_count=4`, `response_model="claude-sonnet-4-6"`, `usage={"input_tokens":2048,"output_tokens":512}`, `assistant_content_chars=1200`, `assistant_tool_call_count=0`, `moa_references=None`.
  - `subagent_stop`: `parent_session_id="parent-sess"`, `child_role=None`, `child_summary="Synthetic summary for hooks test"`, `child_status="completed"`, `tool_call_history=[{tool_name:"write_file", tool_input:{argument_keys:["content","path"], targets:{path:"/tmp/report.txt"}}, input_bytes:128, output_bytes:32, status:"ok"}]`, `duration_ms=1234`.
- **Wire payload shape (what lands on the script's stdin, `agent/shell_hooks.py:742` `_serialize_payload`):** `{"hook_event_name": <event>, "tool_name": <or null>, "tool_input": <args dict or null>, "session_id": <session_id or parent_session_id or "">, "cwd": <cwd>, "extra": {<all other kwargs>}}` serialised with `ensure_ascii=False, default=str`.
- **Rebuild notes:** Keep one canonical payload serialiser shared by test and production so test output is trustworthy. A better version would add `--allowlist-only` (refuse to run unapproved hooks, matching doctor), a `--dry-run` that only prints the stdin JSON, and per-hook stdin capture to a file for replay.

### hermes hooks revoke / remove / rm  `id: cli-d.hooks-revoke`
- **Surface:** CLI
- **Where:** `hermes hooks revoke <command>`, aliases `hermes hooks remove`, `hermes hooks rm`. Help: *"Remove a command's allowlist entries (takes effect on next restart)"*. Positional help: *"The exact command string to revoke (as declared in config.yaml)"*.
- **What it does:** Deletes every consent record whose `command` field equals the given string from `~/.hermes/shell-hooks-allowlist.json`, across all events.
- **How it works:** `hermes_cli/hooks.py:328` `_cmd_revoke()` calls `agent.shell_hooks.revoke(command)` (`agent/shell_hooks.py:1003`), which does a locked read-modify-write via `_locked_update_approvals()` — an exclusive `fcntl.flock` on `<allowlist>.lock` on POSIX, an in-process `threading.Lock` where `fcntl` is missing — then persists with `save_allowlist()` (mkstemp in the same directory + `utils.atomic_replace`, JSON with `indent=2, sort_keys=True`).
- **Inputs / options:** positional `command` (exact match, no globbing); `-h`, `--help`.
- **Outputs / side effects:** Rewrites the allowlist file. Prints `No allowlist entry found for command: <cmd>` when zero removed, else `Removed <N> allowlist entry/entries for: <cmd>` followed by `Note: currently running CLI / gateway processes keep their already-registered callbacks until they restart.`
- **Config / env:** `HERMES_HOME` decides the allowlist location.
- **Edge cases / guards:** Match is on the exact `command` string only — event is ignored, so a script registered on three events loses all three. Already-running processes keep the hook live (documented in the printed note). Write failures are logged inside `save_allowlist`, not surfaced as a non-zero exit.
- **Rebuild notes:** Store consent as `{event, command, approved_at, script_mtime_at_approval}`; make revoke idempotent and report the count. Better: allow `--event` scoping, glob patterns, and an audit trail of who revoked when.

### hermes hooks doctor  `id: cli-d.hooks-doctor`
- **Surface:** CLI
- **Where:** `hermes hooks doctor`. Help: *"Check each configured hook: exec bit, allowlist, mtime drift, JSON validity, and synthetic run timing"*.
- **What it does:** Health-checks every configured shell hook: does the script exist and is it runnable, is it allowlisted, has it changed since approval, and does it emit valid JSON on a synthetic payload within its timeout.
- **How it works:** `hermes_cli/hooks.py:346` `_cmd_doctor()` → `_doctor_one(spec, shell_hooks)` (`hermes_cli/hooks.py:370`) per spec. The four checks, in order:
  1. **Executable check** — `shell_hooks.script_is_executable(command)` (`agent/shell_hooks.py:1111`). For a bare invocation (`argv[0] == script path`) it requires `os.X_OK`; for interpreter-prefixed commands (`python3 hook.py`, `/usr/bin/env bash hook.sh`) only `os.R_OK`. Prints `      ✓ script exists and is executable` or `      ✗ script missing or not executable (chmod +x the file, or fix the path)`.
  2. **Allowlist check** — `allowlist_entry_for(event, command)`. Prints `      ✓ allowlisted (approved <iso|?>)` or `      ✗ not allowlisted — hook will NOT fire at runtime (run with --accept-hooks once, or confirm at the TTY prompt)`.
  3. **Mtime drift** — only when an entry with `script_mtime_at_approval` exists. Drift prints `      ⚠ script modified since approval (was <a>, now <b>) — review changes, then `hermes hooks revoke` + re-approve to refresh`; equality prints `      ✓ script unchanged since approval`.
  4. **JSON smoke test** — skipped entirely when the hook is not yet allowlisted (deliberately, so doctor never executes an unreviewed script pulled in with a fresh config): `      ℹ skipped JSON smoke test — not allowlisted yet. Approve the hook first (via TTY prompt or --accept-hooks), then re-run `hermes hooks doctor`.` Otherwise, if the script is executable, `run_once()` fires it with the same `_DEFAULT_PAYLOADS[event]` (fallback `{"extra": {}}`) and prints one of: `      ✗ timed out after <s>s on synthetic payload (timeout=<N>s)`, `      ✗ execution error: <msg>`, `      ✓ produced valid JSON on synthetic payload (exit=<rc>, <s>s)`, `      ✗ stdout was not valid JSON (exit=<rc>, <s>s): <≤120 chars>`, `      ✓ ran clean with empty stdout (exit=<rc>, <s>s) — hook is observer-only`.
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** Executes allowlisted hook scripts (real side effects). Prints `No shell hooks configured — nothing to check.` when empty; otherwise `Checking <N> configured shell hook(s)...`, then per hook `  [<event>] <command>` and the four check lines; finally `<N> issue(s) found.  Fix before relying on these hooks.` or `All shell hooks look healthy.`
- **Config / env:** `hooks:` block; `HERMES_HOME`.
- **Edge cases / guards:** Each of checks 1, 2, 4 and the drift branch increments a `problems` counter; a drift warning counts as a problem even though the hook still fires. Exit status is not changed by problems (the function returns `None`) — the count is informational.
- **Rebuild notes:** Separate "will it fire" (consent + exec bit) from "does it behave" (JSON contract + timing), and never execute unapproved code during a health check. A better version would hash-pin scripts, run the smoke test in a sandbox with a fake cwd, and expose a `--json` machine-readable report plus a non-zero exit on problems.

### Shell-hook consent & runtime semantics (context for the `hooks` group)  `id: cli-d.hooks-consent-model`
- **Surface:** Core
- **Where:** Not a command — the behaviour the four `hooks` sub-commands inspect. Files: `~/.hermes/config.yaml` (`hooks:` block), `~/.hermes/shell-hooks-allowlist.json`, `~/.hermes/shell-hooks-allowlist.json.lock`.
- **What it does:** Gates first use of every shell hook behind an interactive consent prompt, records the approval with the script's mtime, and defines how a hook's exit code and stdout translate into agent behaviour.
- **How it works:** `agent/shell_hooks.py`. `register_from_config(cfg, accept_hooks=)` (line 247) walks parsed specs, checks `_is_allowlisted(event, command)` under `_registered_lock`, and for unseen pairs calls `_prompt_and_record()` (line 943). Approval writes `{"event","command","approved_at","script_mtime_at_approval"}` into `approvals[]`. Registration is idempotent per `(event, matcher, command)` triple (`_registered` set, line 189). `_spawn()` (line 533) runs the command with `shell=False` after `split_command_line(os.path.expanduser(command))`, in its own process group on POSIX (`process_group=0`) so a timed-out tree can be reaped; Windows uses `windows_hide_flags()` and `taskkill /T` via `kill_process_tree`.
- **Inputs / options:** Per-hook config fields: `command` (required non-empty string), `matcher` (regex string; honoured only for `pre_tool_call`/`post_tool_call`, matched with `re.fullmatch`, falling back to literal equality if the regex fails to compile), `timeout` (int seconds, default `DEFAULT_TIMEOUT_SECONDS = 60`, minimum 1, clamped to `MAX_TIMEOUT_SECONDS = 300`), `fail_closed` (canonical) / `failClosed` (Cursor/Claude-Code compat; canonical wins). Consent prompt: `Allow this hook to run? [y/N]:` accepting `y`/`yes`.
- **Outputs / side effects:** Consent prompt text printed verbatim: `⚠ Hermes is about to register a shell hook that will run a` / `  command on your behalf.` / `    Event:   <event>` / `    Command: <command>` / `  Commands run with your full user credentials.  Only approve` / `  commands you trust.` Allowlist JSON written atomically.
- **Config / env:** `hooks_auto_accept` (bool or string `1|true|yes|on`), env `HERMES_ACCEPT_HOOKS` (`1|true|yes|on`), CLI flag `--accept-hooks`. Precedence: flag > env > config (`_resolve_effective_accept`, line 1057).
- **Edge cases / guards:** Non-TTY stdin without an opt-in returns `False` (hook silently skipped, warning logged). Exit code `2` (`BLOCK_EXIT_CODE`) blocks — but only for `_BLOCKING_EVENTS = {"pre_tool_call"}`; `fail_closed` likewise only applies there and is downgraded with a warning elsewhere. Block message precedence: stdout block JSON → stderr excerpt (capped at `_STDERR_MESSAGE_LIMIT = 400`) → `"Blocked by shell hook."`. `_parse_response` (line 772) translates Claude-Code shapes: `{"decision":"block","reason":…}` → `{"action":"block","message":…}`; `{"decision":"modify","tool_input":{…}}` → `{"action":"modify","args":{…}}`; for `pre_verify`, `action`/`decision` of `continue` or `block` with a non-empty message → `{"action":"continue","message":…}`; for other events a non-empty `context` string passes through.
- **Rebuild notes:** The consent file is the security boundary — treat an unapproved hook as absent, not as a warning. A better version would pin `sha256(script)` rather than mtime, support per-event revocation, and run hooks under a restricted profile with an explicit env allowlist.

---

## 2. `hermes doctor` — diagnostics

### hermes doctor  `id: cli-d.doctor`
- **Surface:** CLI
- **Where:** `hermes doctor [--fix] [--live] [--ack ADVISORY_ID]`. Root help entry: *"Check configuration and dependencies"*. Description: *"Diagnose issues with Hermes Agent setup"*.
- **What it does:** Runs ~19 named sections of static health checks over the Python environment, config files, auth, directories, databases, external tools, API connectivity, tool availability, skills hub, memory provider and profiles; prints a numbered list of remediations at the end; optionally auto-fixes and optionally makes real network probes.
- **How it works:** Parser at `hermes_cli/subcommands/doctor.py:12`; body is the ~2200-line `run_doctor(args)` at `hermes_cli/doctor.py:1236`. It sets `HERMES_INTERACTIVE=1` (via `os.environ.setdefault`) so CLI-gated toolsets are evaluated the way `hermes` sees them. Output primitives (`hermes_cli/doctor.py:395-404`): `check_ok` prints `  ✓ <text> <dim detail>`, `check_warn` prints `  ⚠ …`, `check_fail` prints `  ✗ …`, `check_info` prints `    → <text>`. Section banners come from `_section(title)` (line 510): a blank line then bold-cyan `◆ <title>`. Two issue buckets are accumulated: `issues` (auto-fixable/actionable) and `manual_issues` (needs a human); the closing summary concatenates them.
- **Inputs / options:**
  - `--fix` — *"Attempt to fix issues automatically"* (see `cli-d.doctor-fix`).
  - `--live` — *"Opt-in: run one bounded, read-only real-call health probe per configured tool backend (Firecrawl/FAL/browser/MCP/TTS/STT) after the static checks. Makes real network calls."* (see `cli-d.doctor-live`).
  - `--ack ADVISORY_ID` — *"Acknowledge a security advisory by ID and exit. After ack, the advisory will no longer trigger startup banners. Run `hermes doctor` first to see active advisories and their IDs."* (see `cli-d.doctor-ack`).
  - `-h`, `--help`.
- **Outputs / side effects:** A banner box drawn as `┌─…┐` / `│                 🩺 Hermes Doctor                        │` / `└─…┘` in cyan, then the sections, then one of three trailers:
  - with `--fix` and at least one fix: green `─`×60, `  Fixed <N> issue(s).` optionally followed by ` <M> issue(s) require manual intervention.` and the numbered list;
  - otherwise with issues: yellow `─`×60, `  Found <N> issue(s) to address:`, blank line, numbered list, and (without `--fix`) `  Tip: run 'hermes doctor --fix' to auto-fix what's possible.`;
  - with nothing to report: green `─`×60 and `  All checks passed! 🎉`.
  Read-only except under `--fix`; `--live` performs network calls; `--ack` writes to config.yaml.
- **Config / env:** Reads `~/.hermes/config.yaml` (raw, via `read_user_config_raw`) and `~/.hermes/.env` (via `load_env`), plus `HERMES_HOME`, `HERMES_INTERACTIVE`, `TERMINAL_ENV`, `PREFIX`/`TERMUX_VERSION`, `AWS_EC2_METADATA_DISABLED` (temporarily forced to `true` around the connectivity block), `HERMES_MANAGED_DIR`, `HERMES_KANBAN_TASK`, `GITHUB_TOKEN`/`GH_TOKEN`, and every provider key listed in the connectivity section. Config keys consumed include `model.provider`, `model.default`/`model.model`, `providers.*`, `agent.max_turns`, `security.acked_advisories`, `memory.provider`, `mcp_servers.*`, `sessions.auto_prune`, `doctor.live_probe_timeout`, `display.tool_progress`, `terminal.backend`, `browser.engine`.
- **Edge cases / guards:** Every section is wrapped so a failing check degrades to a warning rather than aborting the run (`except Exception as e: check_warn(...)`). Sections that are platform-specific (`s6 Supervision`, `Gateway Service`, `Command Installation`, macOS TCC checks) are skipped silently off-platform. `hermes doctor` is also callable in-process from the dashboard console, so the journal-mode probe refuses to read a DB this process holds open.
- **Rebuild notes:** Structure diagnostics as ordered sections of independent `(status, text, detail)` emitters plus two issue lists; parallelise only network probes; make every remediation a copy-pasteable command. A better version would emit `--json` for CI, tag each check with a stable ID so acks/suppressions are possible per check, and separate "broken" from "not configured".

### hermes doctor — section “Security Advisories”  `id: cli-d.doctor-sec-advisories`
- **Surface:** CLI
- **Where:** first `◆ Security Advisories` block of `hermes doctor` output.
- **What it does:** Scans the active venv for installed Python packages whose exact versions match a hard-coded advisory list of known-compromised releases and prints full remediation steps.
- **How it works:** `hermes_cli/doctor.py:1285`. Calls `security_advisories.detect_compromised()` → hits, then `filter_unacked()`. Advisory table `ADVISORIES` at `hermes_cli/security_advisories.py:95` currently holds one entry: `id="shai-hulud-2026-05"`, `title="Mini Shai-Hulud worm — mistralai 2.4.6 compromised on PyPI"`, `compromised=(("mistralai", {"2.4.6"}),)`, `severity="critical"`, `published="2026-05-12"`, `url="https://socket.dev/blog/mini-shai-hulud-worm-pypi"`. Detection uses `importlib.metadata.version()` inside the active venv (uv venvs may lack pip). Acks live in `config.security.acked_advisories` (a list of IDs).
- **Inputs / options:** none of its own (`--ack <id>` short-circuits the whole doctor run).
- **Outputs / side effects:** On a clean scan: `  ✓ No active security advisories`. On a hit: `  ✗ <advisory title> (<package>==<version>)` followed by the indented yellow `full_remediation_text(hit)` block (the five `remediation` lines: `Run: pip uninstall -y mistralai  (or: uv pip uninstall mistralai)`, `Rotate API keys in ~/.hermes/.env (…)`, `Audit ~/.npmrc, ~/.pypirc, ~/.aws/credentials, ~/.config/gh/hosts.yml, …`, `Check GitHub for unexpected new SSH keys, deploy keys, or webhook additions …`, `After cleanup: hermes doctor --ack shai-hulud-2026-05  to dismiss this warning.`). A `manual_issues` entry is appended: `Resolve security advisory <id>: uninstall <pkg>==<ver> and rotate credentials, then run `hermes doctor --ack <id>`.` Acked-but-still-installed packages produce `  ⚠ <pkg>==<ver> still installed (advisory <id> acknowledged)`. On an internal error: `  ⚠ Security advisory check failed: <e>`.
- **Config / env:** `security.acked_advisories` in config.yaml.
- **Edge cases / guards:** Purely local — no network. Acked advisories stop the startup banner but the "still installed" warning remains so an ack cannot hide the package.
- **Rebuild notes:** Hard-code a small, versioned advisory table with `id/title/summary/url/compromised/remediation/published/severity`; ack by ID into config. Better: pull the advisory feed (OSV/PyPI) at run time with a signed, cached snapshot.

### hermes doctor — section “MCP Server Security”  `id: cli-d.doctor-sec-mcp`
- **Surface:** CLI
- **Where:** `◆ MCP Server Security` block.
- **What it does:** Inspects each `mcp_servers.<name>` entry for the three known-malicious stdio shapes and warns about any that match.
- **How it works:** `hermes_cli/doctor.py:1331` iterates `load_config()["mcp_servers"]` sorted by name and calls `hermes_cli/mcp_security.py:121` `validate_mcp_server_entry(name, entry)`, which checks (1) a hard-coded hermes-0day IOC substring anywhere in command/args/env (`_IOC_SUBSTRINGS`; one match returns immediately without leaking the full match list), (2) a shell interpreter (`_SHELL_INTERPRETERS`) whose inline script matches `_EGRESS_PATTERN` (network egress), with an extra clause when `_EXFIL_HINT_PATTERN` also matches, and (3) the same interpreter writing to an OS persistence surface per `_PERSISTENCE_PATTERN` (SSH keys / PAM / sudoers / cron / shell rc).
- **Inputs / options:** none.
- **Outputs / side effects:** Clean: `  ✓ No suspicious MCP stdio commands`. Hit: `  ⚠ MCP server '<name>' has suspicious stdio command <joined issues>` plus a manual issue `Review/remove mcp_servers.<name> in config.yaml; rotate any credentials that may have been exposed.` Error: `  ⚠ MCP security check failed: <e>`. Issue strings are: `MCP server '<n>' contains a known hermes-0day indicator-of-compromise ('<ioc>')`; `MCP server '<n>' uses shell interpreter '<cmd>' with network egress in args[ and exfiltration-shaped arguments]`; `MCP server '<n>' uses shell interpreter '<cmd>' to write to an OS persistence surface (SSH keys / PAM / sudoers / cron / shell rc) — this is the hermes-0day backdoor shape, not a real MCP server`.
- **Config / env:** `mcp_servers` block of config.yaml.
- **Edge cases / guards:** Deliberately not a whitelist — legitimate local MCPs using npx/uvx/python are untouched; only the three narrow shapes trigger. Non-dict entries are skipped.
- **Rebuild notes:** Pattern-match the launch command, not the server name; refuse on IOC immediately. A better version would sandbox stdio MCP servers and require an explicit per-server consent record like shell hooks have.

### hermes doctor — section “Python Environment”  `id: cli-d.doctor-python-env`
- **Surface:** CLI
- **Where:** `◆ Python Environment` block.
- **What it does:** Reports the Python version, the linked SQLite library (including the WAL-reset bug), the journal mode and size of every Hermes database, whether a virtualenv is active, the macOS TCC anchor / Full Disk Access state, version-file consistency and macOS TCC grant durability.
- **How it works / individual checks (in order):**
  1. **Python version** (`doctor.py:1355`): `>=3.11` → `✓ Python X.Y.Z`; `3.10` → `✓` plus `⚠ Python 3.11+ recommended for RL Training tools (tinker requires >= 3.11)`; `3.8–3.9` → `⚠ Python X.Y.Z (3.10+ recommended)`; below → `✗ Python X.Y.Z (3.10+ required)` + issue `Upgrade Python to 3.10+`.
  2. **SQLite WAL-reset bug** (`doctor.py:1372`): `hermes_state.is_sqlite_wal_reset_vulnerable()`. Vulnerable → `⚠ SQLite <ver> (WAL-reset bug)` with detail from `_sqlite_upgrade_hint()` (`doctor.py:89`) which reads `detect_install_method(PROJECT_ROOT)` and says `run \`hermes update\`` / a docker recreate / a Nix prose hint / an apt command, always ending `fixed versions: 3.51.3+ / 3.50.7 / 3.44.6 — see https://sqlite.org/wal.html#walresetbug`. Otherwise `✓ SQLite <ver>`. Then `→ SQLite source id: <first 48 chars>…`.
  3. **Per-database journal modes** (`_report_database_journal_modes`, `doctor.py:192`): iterates `_hermes_database_paths()` = every `*.db` in `hermes_cli.backup._QUICK_STATE_FILES` plus every `kanban/boards/*/kanban.db`. Mode is read from **header byte 18** (2=WAL, 1=rollback) via `hermes_cli.sqlite_safe_read.read_header_bytes_preopen(path, length=20)` — never by opening the DB, so no `-wal`/`-shm` sidecars are created and no advisory locks are dropped. Lines: `→ <name>: rollback journal mode (<size>[, not exposed])`, `→ <name>: WAL journal mode (<size>)`, `⚠ <name> is in WAL mode (<size>) (exposed to the WAL-reset bug until SQLite is upgraded)`, `⚠ <name>: journal mode could not be read (<reason>; cannot rule out WAL exposure)` or `→ <name>: journal mode could not be read (<reason>)`. Reasons come from `_unreadable_reason()`/`_read_journal_mode()`: `database is open in this process`, `permission denied: <path>`, `file is empty`, `file is not a database`, `unrecognized file-format version <n>`, or the raw `OSError`. When anything is exposed: `→ To clear the exposure: <_wal_reset_repair_hint()>`.
  4. **Virtualenv** (`doctor.py:1394`): `sys.prefix != sys.base_prefix` → `✓ Virtual environment active`, else `⚠ Not in virtual environment (recommended)`.
  5. **macOS TCC interpreter anchor** (`check_macos_tcc_anchor`, `doctor.py:1158`): via `hermes_cli.macos_tcc_anchor.tcc_anchor_state()`; `skip` → silent; `active` → `✓ macOS TCC anchor active (<detail>)`; with `--fix` calls `ensure_tcc_anchor()` → `✓ macOS TCC anchor installed (<path>)`; else `⚠ macOS TCC anchor missing|stale (<detail>)`; on exception `⚠ macOS TCC anchor check failed (<e>)`.
  6. **macOS Full Disk Access** (`check_macos_full_disk_access`, `doctor.py:1187`): probes `os.listdir(~/Library/Application Support/com.apple.TCC)`. Granted → `✓ macOS Full Disk Access granted (no per-folder permission prompts will occur)`. `PermissionError` → the long `→ One switch silences all macOS folder prompts: … Open: System Settings → Privacy & Security → Full Disk Access — or run: open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" then enable your terminal (and Hermes.app if you use Desktop), and restart them once. …` Other `OSError` → silent.
  7. **Version-file consistency** (`_check_version_consistency`, `doctor.py:726`): compares `[project] version` in `pyproject.toml` with `hermes_cli.__version__`. Match → `✓ Version files consistent (<v>)`. Mismatch → `✗ Version mismatch between source files (pyproject.toml <a> != hermes_cli/__init__.py <b>)` + issue `Re-sync version files (e.g. run 'hermes update', or set hermes_cli/__init__.py __version__ to match pyproject.toml)`. Silent for installed wheels (no pyproject.toml).
  8. **macOS TCC grant persistence** (`check_macos_tcc_grants`, `doctor.py:1053`): locates `apps/desktop/release/mac*/Hermes.app` (newest by mtime; `/Applications/Hermes.app` is deliberately not probed) and runs `codesign -d --requirements - <app>` (15s timeout). DR containing `cdhash` → `⚠ macOS TCC grants will reset after every update` + the pre-#73681 explanation; DR containing `certificate` → `✓ macOS TCC signing identity is stable (certificate-anchored DR; grants survive rebuilds)`; otherwise `✓ macOS TCC signing identity is stable (identifier-pinned DR; grants survive rebuilds — for the strongest anchor, see \`hermes desktop --setup-tcc-identity\`)`; unreadable → `⚠ macOS TCC grant check (could not read code-signing requirement of the desktop bundle)`. Followed by `→ If macOS still re-prompts for permissions (toggle shows ON): the stored grant is stale — run \`tccutil reset ScreenCapture com.nousresearch.hermes\` (repeat per affected service), toggle it ON in System Settings, then fully quit & relaunch Hermes once.`
- **Inputs / options:** `--fix` affects checks 5 only in this section.
- **Outputs / side effects:** Read-only except `--fix` installing the TCC anchor.
- **Config / env:** none directly; `HERMES_HOME` decides which DBs are inspected.
- **Edge cases / guards:** SQLite probe failures degrade to `⚠ SQLite version probe failed: <e>`. Database listing failure prints `⚠ Could not list Hermes databases: <exc>`.
- **Rebuild notes:** Read a SQLite journal mode from the file header, never by connecting — that is the non-obvious correctness rule here.

### hermes doctor — section “SSL / CA Certificates”  `id: cli-d.doctor-ssl`
- **Surface:** CLI
- **Where:** `◆ SSL / CA Certificates` block.
- **What it does:** Verifies the certifi CA bundle loads, and with `--fix` force-reinstalls certifi and re-verifies in the same process.
- **How it works:** `check_certificates(should_fix, issues)` at `hermes_cli/doctor.py:802`, calling `agent.ssl_guard.verify_ca_bundle_with_fallback()`. On `--fix` it runs `<sys.executable> -m pip install --force-reinstall certifi` (300s timeout), pops every `certifi*` entry from `sys.modules`, calls `importlib.invalidate_caches()` and re-verifies.
- **Inputs / options:** `--fix`.
- **Outputs / side effects:** `  ✓ SSL CA certificate bundle is valid`; or `  ✗ SSL CA certificate bundle is broken <first error>` + manual issue ``Repair the CA bundle: run `hermes doctor --fix`, or `<python> -m pip install --force-reinstall certifi` ``. Under `--fix`: `    → Repairing: force-reinstalling certifi...` then `✓ SSL CA certificate bundle repaired (certifi reinstalled)` or `✗ SSL CA certificate bundle still broken after reinstall <e>` (+ issue naming `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`), `✗ certifi repair could not run pip <exc>`, or `✗ certifi reinstall failed <last 500 chars of stderr/stdout>`. Import failure → `⚠ SSL certificate check skipped <e>`.
- **Config / env:** `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` (named in the remediation).
- **Edge cases / guards:** `--fix` mutates the interpreter's site-packages; the 300s pip timeout is the only bound.
- **Rebuild notes:** Verify by actually loading the bundle, not by checking a path exists.

### hermes doctor — section “Required Packages”  `id: cli-d.doctor-packages`
- **Surface:** CLI
- **Where:** `◆ Required Packages` block.
- **What it does:** Imports five required and three optional Python modules and reports each.
- **How it works:** `hermes_cli/doctor.py:1427`. Required list (module → label): `openai` → `OpenAI SDK`, `rich` → `Rich (terminal UI)`, `dotenv` → `python-dotenv`, `yaml` → `PyYAML`, `httpx` → `HTTPX`. Optional list: `croniter` → `Croniter (cron expressions)`, `telegram` → `python-telegram-bot`, `discord` → `discord.py`.
- **Inputs / options:** none.
- **Outputs / side effects:** Present required → `✓ <label>`; missing required → `✗ <label> (missing)` + issue `Install <label>: <uv pip install|python -m pip install> <module>` (`python -m pip install` on Termux, `uv pip install` elsewhere — `_python_install_cmd()`, `doctor.py:77`). Present optional → `✓ <label> (optional)`; missing optional → `⚠ <label> (optional, not installed)`.
- **Config / env:** `TERMUX_VERSION`/`PREFIX` change the install command.
- **Rebuild notes:** Import, don't parse a lockfile — the import is what actually fails at runtime.

### hermes doctor — section “Configuration Files”  `id: cli-d.doctor-config-files`
- **Surface:** CLI
- **Where:** `◆ Configuration Files` block.
- **What it does:** Checks the managed scope, `.env`, `config.yaml`, the config schema version, stale/deprecated keys, provider/model validity, and config structure.
- **How it works / individual checks (in order):**
  1. **Managed scope** (`managed_scope_check`, `doctor.py:1028`): silent when no managed dir; otherwise `✓ Managed scope active: <n> config key(s), <m> env key(s) pinned by <dir>`, plus `→ managed dir set via HERMES_MANAGED_DIR=<dir>` when the override env var is set.
  2. **`~/.hermes/.env` presence** (`doctor.py:1459`): exists → `✓ <home>/.env file exists`, then `_has_provider_env_config()` over the file text (UTF-8, falling back to latin-1 like `env_loader._load_dotenv_with_fallback`) → `✓ API key or custom endpoint configured` or `⚠ No API key found in <home>/.env` + issue `Run 'hermes setup' to configure API keys`. Missing → falls back to `<PROJECT_ROOT>/.env` (`✓ .env file exists (in project directory)`), else `✗ <home>/.env file missing`; with `--fix` it `mkdir -p`s, `touch`es and `chmod 0600`s the file then prints `✓ Created empty <home>/.env` and `→ Run 'hermes setup' to configure API keys`; without `--fix` it prints `→ Run 'hermes setup' to create one` and adds issue `Run 'hermes setup' to create .env`.
  3. **`~/.hermes/config.yaml` presence** (`doctor.py:1499`): exists → `✓ <home>/config.yaml exists`; else project `cli-config.yaml` → `✓ cli-config.yaml exists (in project directory)`; else with `--fix` copies `cli-config.yaml.example` (`✓ Created <home>/config.yaml from cli-config.yaml.example`) or writes `DEFAULT_CONFIG` (`✓ Created <home>/config.yaml from defaults`); without `--fix` → `⚠ config.yaml not found (using defaults)`.
  4. **`model.provider` validity** (`doctor.py:1503-1620`): builds the known-provider set from `hermes_cli.auth.PROVIDER_REGISTRY` ∪ `{openrouter, custom, auto, moa}` ∪ enabled `providers:` entries ∪ `get_compatible_custom_providers()` aliases, normalises through `hermes_cli.providers.normalize_provider` / `resolve_provider_full`. Unknown → `✗ model.provider '<raw>' is not a recognised provider (known: <sorted list>)` + issue `model.provider '<raw>' is unknown. Valid providers: <list>. Fix: run 'hermes config set model.provider <valid_provider>'`.
  5. **Vendor-slug mismatch** (`doctor.py:1610`): if `model.default` contains `/` and the resolved provider is not in `{openrouter, auto, ai-gateway, kilocode, opencode-zen, huggingface, lmstudio, nous, nvidia, fireworks, deepinfra}` and not `custom`/`custom:*` → `⚠ model.default '<m>' uses a vendor/model slug but provider is '<p>' (vendor-prefixed slugs belong to aggregators like openrouter)` + issue.
  6. **Provider credentials** (`doctor.py:1645`): for API-key providers in `PROVIDER_REGISTRY` (and `openrouter` via `OPENROUTER_API_KEY`/`OPENAI_API_KEY`) → `✗ model.provider '<p>' is set but no API key is configured (check ~/.hermes/.env or run 'hermes setup')` + issue. Any exception in 4–6 → `⚠ Could not validate model/provider config (<e>)`.
  7. **Config schema version** (`doctor.py:1721`): `check_config_version()` → up to date `✓ Config version up to date (v<n>)`; outdated `⚠ Config version outdated (v<a> → v<b>) (new settings available)` and, with `--fix`, `migrate_config(interactive=False, quiet=False)` → `✓ Config migrated to latest version` or `⚠ Auto-migration failed: <e>` + issue `Run 'hermes setup' to migrate config`; without `--fix` issue `Run 'hermes doctor --fix' or 'hermes setup' to migrate config`.
  8. **Stale root-level keys** (`doctor.py:1745`): `provider` / `base_url` at the top level of the raw YAML → `⚠ Stale root-level config keys: <list> (should be under 'model:' section)`; `--fix` moves them under `model:` (coercing a scalar `model:` into `{"default": …}`) and prints `✓ Migrated stale root-level keys into model section`; otherwise issue `Stale root-level provider/base_url in config.yaml — run 'hermes doctor --fix'`.
  9. **`HERMES_MAX_ITERATIONS` ghost** (`doctor.py:1786`): compares the `.env` file value against `agent.max_turns` (or legacy root `max_turns`). Drift → `⚠ HERMES_MAX_ITERATIONS=<e> in .env shadows agent.max_turns=<c> in config.yaml (stale ghost from an earlier \`hermes setup\` run)`; `--fix` → `remove_env_value(...)` then `✓ Removed stale HERMES_MAX_ITERATIONS from .env (config.yaml agent.max_turns=<c> is now authoritative)` or `⚠ Could not remove HERMES_MAX_ITERATIONS from .env` + a manual issue; without `--fix` issue `Stale HERMES_MAX_ITERATIONS in .env shadows config.yaml — run 'hermes doctor --fix'`.
  10. **Deprecated keys / env vars** (`report_deprecated_config_and_env`, `doctor.py:641`): clean → `✓ No deprecated config keys or env vars`. Deprecated config keys checked (`_DEPRECATED_CONFIG_KEYS`, line 519): `display.tool_progress_overrides` → `display.platforms`; `delegation.max_async_children` → `delegation.max_concurrent_children`; plus `compression.summary_model`, `compression.summary_provider`, `compression.summary_base_url` → `auxiliary.compression`. Deprecated env vars (`_DEPRECATED_ENV_VARS`, line 536, read from the `.env` file not `os.environ`): `HERMES_TOOL_PROGRESS` → `display.tool_progress in config.yaml — ignored/unsupported since config floor v12`; `HERMES_TOOL_PROGRESS_MODE` → `display.tool_progress in config.yaml`; `TERMINAL_CWD` → `terminal.cwd in config.yaml`; `MESSAGING_CWD` → `terminal.cwd in config.yaml`; `QQ_HOME_CHANNEL` → `QQBOT_HOME_CHANNEL`; `QQ_HOME_CHANNEL_NAME` → `QQBOT_HOME_CHANNEL_NAME`. Each prints `⚠ Deprecated: <legacy> (use <replacement> instead)` and `→ Replace <legacy> → <replacement> (warn-only; not auto-migrated here)`.
  11. **Relay-plugin cutover** (`collect_relay_plugin_cutover_findings`, `doctor.py:595`): legacy `plugins.enabled` relay keys → `⚠ Breaking Relay migration: plugins.enabled: <key> (remove it and configure <RELAY_PLUGINS_CONFIG_ENV>)`; legacy relay export env vars while the new var is unset → `⚠ Breaking Relay migration: <VAR> (move exporter settings to <RELAY_PLUGINS_CONFIG_ENV>; this variable is now ignored)`; each followed by `→ Migrate <legacy>: <replacement>`.
  12. **Config structure validation** (`doctor.py:1855`): `validate_config_structure()`; when it returns findings a nested `◆ Config Structure` section is opened and each finding prints `✗`/`⚠ <message>` plus indented `→ <hint line>` per line, and appends `message` to `issues`.
- **Inputs / options:** `--fix` affects checks 2, 3, 7, 8, 9.
- **Outputs / side effects:** May create `.env` (mode 0600), create/migrate `config.yaml`, rewrite it to move stale keys, and delete a line from `.env`.
- **Config / env:** as listed above; `HERMES_MANAGED_DIR`.
- **Edge cases / guards:** All raw-config reads use `read_user_config_raw` so the diagnostic sees what the user actually wrote, not merged defaults. When `config.yaml` does not exist, the deprecated-env sweep still runs with an empty config dict.
- **Rebuild notes:** Diagnose against the *raw* file, fix against an atomic writer, and never auto-delete deprecated keys — warn and point at the replacement.

### hermes doctor — section “xAI Model Retirement (May 15, 2026)”  `id: cli-d.doctor-xai-retirement`
- **Surface:** CLI
- **Where:** `◆ xAI Model Retirement (May 15, 2026)` block.
- **What it does:** Flags configuration that still references xAI models retired on 2026-05-15.
- **How it works:** `hermes_cli/doctor.py:1889` calls `hermes_cli.xai_retirement.find_retired_xai_refs(load_config())` and `format_issue(ref)`.
- **Inputs / options:** none.
- **Outputs / side effects:** Clean → `✓ No retired xAI models in config`. Hits → one `⚠ <format_issue(ref)>` per reference, then `→ Migration guide: <MIGRATION_GUIDE_URL>` and a manual issue `Update <N> retired xAI model reference(s) in config.yaml — see <URL>`. Failure → `⚠ xAI retirement check skipped (<e>)`.
- **Config / env:** any config key holding an xAI model id.
- **Rebuild notes:** Keep retirement tables data-driven with a dated migration URL.

### hermes doctor — section “Auth Providers”  `id: cli-d.doctor-auth-providers`
- **Surface:** CLI
- **Where:** `◆ Auth Providers` block.
- **What it does:** Shows the login state of the four OAuth-style providers without triggering a token refresh.
- **How it works:** `hermes_cli/doctor.py:1914`. Uses `get_nous_auth_status_local()` (deliberately the refresh-free local snapshot), `get_codex_auth_status()`, `get_minimax_oauth_auth_status()` and, in its own try/except, `get_xai_oauth_auth_status()`.
- **Inputs / options:** none.
- **Outputs / side effects:** Rows, verbatim: `✓|⚠ Nous Portal auth (logged in)|(not logged in)`; `✓|⚠ OpenAI Codex auth (logged in)|(not logged in)` — when not logged in it also prints `→ <codex_status["error"]>` if present and, when the `codex` binary is absent, `→ codex CLI not installed (optional — only required to import tokens from an existing Codex CLI login)`; `✓ MiniMax OAuth (logged in, region=<region>)` or `⚠ MiniMax OAuth (not logged in)`; `✓|⚠ xAI OAuth (logged in)|(not logged in)` with an optional `→ <error>` line (observed: `No xAI OAuth credentials stored. Select xAI Grok OAuth (SuperGrok / Premium+) in \`hermes model\`.`). Group failure → `⚠ Auth provider status (could not check: <e>)`.
- **Config / env:** the credential stores each provider uses under `~/.hermes`.
- **Edge cases / guards:** Doctor must never refresh an OAuth token as a side effect of a health check — hence the `_local` variant for Nous.
- **Rebuild notes:** Read-only auth status calls only; keep the xAI probe in its own try/except so one import failure cannot swallow the other rows.

### hermes doctor — section “Directory Structure”  `id: cli-d.doctor-dirs`
- **Surface:** CLI
- **Where:** `◆ Directory Structure` block.
- **What it does:** Verifies the Hermes home directory, its five expected sub-directories, the persona file, the memory files and the session database (including FTS write-health and size/WAL statistics).
- **How it works / individual checks (in order):**
  1. **Home dir** (`doctor.py:1972`): exists → `✓ <home> directory exists`; `--fix` creates it (`✓ Created <home> directory`); else `⚠ <home> not found (will be created on first use)`.
  2. **Sub-directories** — exactly `cron`, `sessions`, `logs`, `skills`, `memories`: `✓ <home>/<name>/ exists` / `✓ Created <home>/<name>/` (with `--fix`) / `⚠ <home>/<name>/ not found (will be created on first use)`.
  3. **`SOUL.md`** (`doctor.py:1997`): present with non-comment content → `✓ <home>/SOUL.md exists (persona configured)`; present but only comments/blank → `→ <home>/SOUL.md exists but is empty — edit it to customize personality`; absent → `⚠ <home>/SOUL.md not found (create it to give Hermes a custom personality)`, and with `--fix` writes the template `# Hermes Agent Persona\n\n<!-- Edit this file to customize how Hermes communicates. -->\n\nYou are Hermes, a helpful AI assistant.\n` then `✓ Created <home>/SOUL.md with basic template`.
  4. **`memories/`** (`doctor.py:2019`): `✓ <home>/memories/ directory exists`, then per file `✓ MEMORY.md exists (<n> chars)` / `→ MEMORY.md not created yet (will be created when the agent first writes a memory)` and the same pair for `USER.md`. Missing dir → `⚠ <home>/memories/ not found (will be created on first use)` (+ `--fix` creates it).
  5. **`state.db`** (`doctor.py:2042`): `SELECT COUNT(*) FROM sessions` → `✓ <home>/state.db exists (<n> sessions)`. Then an FTS **write-health probe** `hermes_state._db_opens_cleanly(path)` (a rolled-back write, because a plain COUNT succeeds even when the FTS triggers are broken): failure → `⚠ <home>/state.db fails a write-health probe (FTS index may be corrupt) (<reason>)`; with `--fix`, `repair_state_db_schema(path)` → `✓ Repaired state.db FTS write health (strategy: <s>; backup: <file>)` or `⚠ state.db FTS write-health repair did not recover automatically (<error>; backup: <path>)` + issue; without `--fix` issue `state.db FTS write corruption — run 'hermes doctor --fix' (or 'hermes sessions repair') to rebuild the FTS index`.
  6. **Malformed schema** (`doctor.py:2098`): when the initial query raises and `is_malformed_db_error(e)` → `⚠ <home>/state.db schema is malformed (sessions hidden until repaired) (<e>)`; `--fix` repairs in place and prints `✓ Repaired state.db schema (<n> sessions recovered) (strategy: <s>; backup: <file>)`, else `⚠ state.db schema repair did not recover automatically (…)` + issue; without `--fix` issue `state.db schema malformed — run 'hermes doctor --fix' (or 'hermes sessions repair') to recover hidden sessions`. Any other exception → `⚠ <home>/state.db exists but has issues: <e>`.
  7. **DB stats snapshot** (`_render_state_db_stats`, `doctor.py:418`, fed by `collect_state_db_stats()` opened `mode=ro` and `count_db_holders()`): `→ state.db logical size <X>, <N> pages, <M> free, WAL <Y>`; `→ <n> messages, <m> sessions, journal_mode=<mode>, <k> process(es) holding the DB open`; `→ FTS tables: <comma list|none>`; when a deferral record exists `⚠ state.db FTS repair is blocked after <n> deferral(s) by PID(s) <pids> (stop the listed processes, then run 'hermes sessions optimize-storage' with the gateway stopped)`; when logical size > `STATE_DB_SIZE_WARN_BYTES` (1 GiB) `⚠ state.db is large (<size>) (consider enabling sessions.auto_prune in config.yaml to bound growth[; run 'hermes sessions optimize-storage' offline (with the gateway stopped) to compact FTS storage])` plus the matching issue. Stats failure → `→ state.db stats unavailable (<exc>)`. Missing DB → `→ <home>/state.db not created yet (will be created on first session)`.
  8. **WAL file size** (`doctor.py:2172`): `state.db-wal` > 50 MB → `⚠ WAL file is large (<n> MB) (may indicate missed checkpoints)`; `--fix` runs `PRAGMA wal_checkpoint(PASSIVE)` and prints `✓ WAL checkpoint performed (<a>K → <b>K)`; without `--fix` issue `Large WAL file — run 'hermes doctor --fix' to checkpoint`. Between 10 MB and 50 MB → `→ WAL file is <n> MB (normal for active sessions)`.
- **Inputs / options:** `--fix` affects checks 1, 2, 3, 4, 5, 6, 8.
- **Outputs / side effects:** May create directories, `SOUL.md`, repair `state.db` (writing a timestamped backup beside it) and checkpoint the WAL.
- **Config / env:** `HERMES_HOME`; `sessions.auto_prune` is the recommended remedy for a large DB.
- **Rebuild notes:** A `COUNT(*)` is not a health check for an FTS-backed store — probe with a rolled-back write.

### hermes doctor — section “Gateway Service”  `id: cli-d.doctor-gateway-service`
- **Surface:** CLI
- **Where:** `◆ Gateway Service` block (Linux only, non-s6, and only when the systemd unit file exists).
- **What it does:** Warns when a systemd *user* gateway service will be killed at logout because linger is not enabled.
- **How it works:** `_check_gateway_service_linger(issues)` at `hermes_cli/doctor.py:888`. Returns early on non-Linux, on `detect_service_manager() == "s6"`, and when `get_systemd_unit_path()` does not exist. Otherwise calls `get_systemd_linger_status()`.
- **Inputs / options:** none.
- **Outputs / side effects:** `✓ Systemd linger enabled (gateway service survives logout)`; or `⚠ Systemd linger disabled (gateway may stop after logout)` + `→ Run: sudo loginctl enable-linger $USER` + issue `Enable linger for the gateway user service: sudo loginctl enable-linger $USER`; or `⚠ Could not verify systemd linger (<detail>)`. Import failure → `⚠ Gateway service linger (could not import gateway helpers: <e>)`.
- **Rebuild notes:** Only warn about linger where the concept exists — containers under s6 get their own section instead.

### hermes doctor — section “s6 Supervision”  `id: cli-d.doctor-s6`
- **Surface:** CLI
- **Where:** `◆ s6 Supervision` block (only inside a container whose service manager is s6).
- **What it does:** Reports whether the two static s6 services are up and how many per-profile gateway slots are supervised.
- **How it works:** `_check_s6_supervision(issues)` at `hermes_cli/doctor.py:754`. Returns early unless `detect_service_manager() == "s6"`. Probes `S6ServiceManager.is_running(name)` for `main-hermes` and `dashboard`, then `list_profile_gateways()` and `is_running(f"gateway-{p}")` per profile.
- **Inputs / options:** none.
- **Outputs / side effects:** `✓ <service>: up` or `→ <service>: down (expected if not enabled via env)`; then `→ No per-profile gateways registered yet — create one with \`hermes profile create <name>\`` or `✓ Per-profile gateways: <up>/<total> supervised up (<comma list>)` — the name list is appended only when there are 8 or fewer profiles.
- **Rebuild notes:** Match the supervisor to the environment; a single "service healthy?" abstraction across systemd and s6 hides the differences that matter.

### hermes doctor — section “Command Installation”  `id: cli-d.doctor-command-install`
- **Surface:** CLI
- **Where:** `◆ Command Installation` block (skipped entirely on `win32`).
- **What it does:** Verifies the venv entry point exists and that the user-facing `hermes` symlink points at it.
- **How it works:** `hermes_cli/doctor.py:2202`. Looks for `<PROJECT_ROOT>/venv/bin/hermes` then `<PROJECT_ROOT>/.venv/bin/hermes`. Link dir mirrors `install.sh`: `$PREFIX/bin` on Termux (when `TERMUX_VERSION` is set or `PREFIX` contains `com.termux/files/usr`), otherwise `~/.local/bin`; displayed as `$PREFIX/bin` or `~/.local/bin`.
- **Inputs / options:** `--fix`.
- **Outputs / side effects:** No venv binary → `⚠ Venv entry point not found (hermes not in venv/bin/ or .venv/bin/ — reinstall with pip install -e '.[all]')` + manual issue `Reinstall entry point: cd <root> && source venv/bin/activate && pip install -e '.[all]'`. Otherwise `✓ Venv entry point exists (<relative path>)`, then one of: `✓ <linkdir>/hermes → correct target`; `⚠ <linkdir>/hermes points to wrong target (→ <actual>, expected → <expected>)` with `--fix` relinking (`✓ Fixed symlink: <linkdir>/hermes → <target>`) else issue `Broken symlink at <linkdir>/hermes — run 'hermes doctor --fix'`; `✓ <linkdir>/hermes exists (non-symlink)` for a wrapper script; `✗ <linkdir>/hermes not found (hermes command may not work outside the venv)` with `--fix` creating the symlink (`✓ Created symlink: <linkdir>/hermes → <target>`) and, when the dir is not on `PATH`, `⚠ <linkdir> is not on your PATH (add it to your shell config: export PATH="$HOME/.local/bin:$PATH")` + manual issue `Add <linkdir> to your PATH`; else issue `Missing <linkdir>/hermes symlink — run 'hermes doctor --fix'`.
- **Config / env:** `PREFIX`, `TERMUX_VERSION`, `PATH`.
- **Rebuild notes:** Compare `resolve()`d paths, not strings; treat a non-symlink file as a legitimate wrapper.

### hermes doctor — section “External Tools”  `id: cli-d.doctor-external-tools`
- **Surface:** CLI
- **Where:** `◆ External Tools` block.
- **What it does:** Probes git, ripgrep, the configured terminal backend's requirements, Node.js and the browser stack, Lightpanda, and runs `npm audit` on four Node trees.
- **How it works / individual checks (in order):**
  1. **git** (`doctor.py:2277`): `✓ git` or `⚠ git not found (optional)`.
  2. **ripgrep** — `✓ ripgrep (rg) (faster file search)` or `⚠ ripgrep (rg) not found (file search uses grep fallback)` + `→ Install for faster search: <brew|pkg|sudo apt> install ripgrep` (`_system_package_install_cmd`, `doctor.py:81`: `pkg install` on Termux, `brew install` on darwin, `sudo apt install` elsewhere).
  3. **Docker** (`doctor.py:2290`): when `TERMINAL_ENV=docker`, runs `docker info` (10s) → `✓ docker (daemon running)` or `✗ docker daemon not running` + issue `Start Docker daemon`, or `✗ docker not found (required for TERMINAL_ENV=docker)` + issue `Install Docker or change TERMINAL_ENV`. Otherwise `✓ docker (optional)` / `→ Docker backend is not available inside Termux (expected on Android)` / `⚠ docker not found (optional)`. Inside a container with a non-docker backend: `→ Running inside a container — using local terminal backend (docker-in-docker is not configured by default)`.
  4. **SSH backend** (`TERMINAL_ENV=ssh`): builds `ssh -o ConnectTimeout=5 -o BatchMode=yes [-p PORT] [-i KEY] [user@]host echo ok` (15s) → `✓ SSH connection to <host>` or `✗ SSH connection to <host>` + issue `Check SSH configuration for <host>`; no host → `✗ TERMINAL_SSH_HOST not set (required for TERMINAL_ENV=ssh)` + issue `Set TERMINAL_SSH_HOST in .env`. Env read: `TERMINAL_SSH_HOST`, `TERMINAL_SSH_USER`, `TERMINAL_SSH_PORT`, `TERMINAL_SSH_KEY`.
  5. **Daytona backend**: `✓ Daytona API key (configured)` or `✗ DAYTONA_API_KEY not set (required for TERMINAL_ENV=daytona)` + issue; `✓ daytona SDK (installed)` or `✗ daytona SDK not installed (pip install daytona)` + issue.
  6. **Vercel Sandbox backend**: runtime from `TERMINAL_VERCEL_RUNTIME` (default `node24`) validated against `tools.terminal_tool._SUPPORTED_VERCEL_RUNTIMES` → `✓ Vercel runtime (<r>)` or `✗ Vercel runtime unsupported (<r>; use <list>)` + issue; `TERMINAL_CONTAINER_DISK` must be `""`/`0`/`51200` → `✓ Vercel disk setting (uses platform default)` or `✗ Vercel custom disk unsupported (reset terminal.container_disk to 51200)` + issue; SDK presence → `✓ vercel SDK (installed)` or `✗ vercel SDK not installed (pip install 'hermes-agent[vercel]')` + issue; auth via `describe_vercel_auth()` → `✓ Vercel auth (<label>)`, `✗ Vercel auth incomplete (<label>)` + issue `Set VERCEL_TOKEN, VERCEL_PROJECT_ID, and VERCEL_TEAM_ID together`, or `✗ Vercel auth not configured (<label>)` + issue; each `auth_status.detail_lines` printed as `→ Vercel auth <line>`; persistence note `→ Vercel persistence: snapshot filesystem only; live processes do not survive sandbox recreation` (when `TERMINAL_CONTAINER_PERSISTENT` is truthy) or `→ Vercel persistence: ephemeral filesystem`.
  7. **Plugin terminal backends** (`doctor.py:2452`): for any `TERMINAL_ENV` outside `{local, docker, singularity, modal, managed_modal, daytona, vercel_sandbox, ssh}`, discovers plugins and resolves `agent.terminal_env_registry.get_provider(name)`; unknown → `✗ Unknown terminal backend '<name>' (no built-in or plugin backend by that name)` + issue `Fix terminal.backend in config.yaml, or install/enable the plugin that provides it`; known → each `(ok, label, detail)` from `provider.doctor_checks()` is printed as `✓`/`✗`.
  8. **Node.js + agent-browser** (`doctor.py:2481`): `✓ Node.js` then, mirroring `tools.browser_tool._find_agent_browser(validate=False)`: npx sentinel → `✓ agent-browser (resolves via npx on first use)` and with `--fix` a cache warm-up printing `→   Warmed npx cache for agent-browser` or `→   Could not warm npx cache (offline or npx unavailable)`; a runnable binary → `✓ agent-browser (browser automation)`; found but not runnable → `⚠ agent-browser found but not runnable (broken symlink at <path>? run: npx agent-browser --version)`; Termux → `→ agent-browser is not installed (expected in the tested Termux path)`, `→ Install it manually later with: npm install -g agent-browser && agent-browser install`, `→ Termux browser setup:` plus the numbered steps from `_termux_browser_setup_steps()`; otherwise `⚠ agent-browser not installed (requires npm/npx on PATH)`. No Node → `⚠ Node.js not found (optional, needed for browser tools)` or, on Termux, `→ Node.js not found (browser tools are optional in the tested Termux path)` + `→ Install Node.js on Termux with: pkg install nodejs` + the setup steps.
  9. **Playwright Chromium** (`doctor.py:2544`): only when agent-browser resolved, not on Termux, and not skipped by Camofox mode / a CDP override / a cloud provider / the Lightpanda engine. `✓ Playwright Chromium (browser engine)` or `⚠ Playwright Chromium not installed (browser_* tools will be hidden from the agent)` + `→ Install with: cd <root> && npx playwright install [--with-deps] chromium` (`--with-deps` off Windows).
  10. **Lightpanda** (`doctor.py:2595`): when `browser.engine`/`AGENT_BROWSER_ENGINE` selects Lightpanda: shadowed → `⚠ browser.engine=lightpanda is shadowed (<reason>)` + `→ Fix: pick Lightpanda in \`hermes tools\` → Browser Automation, or set browser.engine: auto`; binary present → `✓ Lightpanda (<reason>)`; missing → `⚠ Lightpanda selected but binary not found (browser tools will fail until it is installed)` + `→ <LIGHTPANDA_INSTALL_HINT>`.
  11. **npm audit** (`doctor.py:2625`): four targets, each skipped when the relevant `node_modules` is absent — `(PROJECT_ROOT, "Browser tools (agent-browser)", ["--workspaces=false"])`, `(PROJECT_ROOT, "web workspace", ["--workspace","web"])`, `(PROJECT_ROOT, "ui-tui workspace", ["--workspace","ui-tui"])`, `(resolve_whatsapp_bridge_dir(), "WhatsApp bridge", [])`. Runs `npm audit --json <extra>` (30s). Zero → `✓ <label> deps (no known vulnerabilities)`; critical or high → `⚠ <label> deps (<c> critical, <h> high, <m> moderate — run: <fix cmd>)` or, for workspace-scoped targets where `npm audit fix --workspace` is known to crash, `… — build-tool advisory; clears via lockfile bump)` plus `→   ^ build-time tooling (not runtime); if manual npm remediation errors with an arborist crash it's a known npm bug — clears via a lockfile bump`, and an issue `<label> has <n> npm vulnerability|vulnerabilities`; moderate only → `✓ <label> deps (<m> moderate vulnerability|vulnerabilities)`.
  12. **Termux fallback notes** (`doctor.py:2718`): on Termux prints `→ Termux compatibility fallbacks:` and the four notes from `_termux_install_all_fallback_notes()` (`doctor.py:256`): *"Termux install profile: use .[termux-all] for broad compatibility (installer default on Termux)."*, *"Matrix E2EE extra is excluded on Termux (python-olm currently fails to build)."*, *"Local faster-whisper extra is excluded on Termux (ctranslate2/av build path unavailable)."*, *"STT fallback: use Groq Whisper (set GROQ_API_KEY) or OpenAI Whisper (set VOICE_TOOLS_OPENAI_KEY)."*
- **Inputs / options:** `--fix` warms the npx cache (check 8) only.
- **Config / env:** `TERMINAL_ENV`, `TERMINAL_SSH_*`, `DAYTONA_API_KEY`, `TERMINAL_VERCEL_RUNTIME`, `TERMINAL_CONTAINER_DISK`, `TERMINAL_CONTAINER_PERSISTENT`, `VERCEL_TOKEN`/`VERCEL_PROJECT_ID`/`VERCEL_TEAM_ID`, `browser.engine`/`AGENT_BROWSER_ENGINE`, `terminal.backend`.
- **Edge cases / guards:** All subprocess probes are bounded (10s docker, 15s ssh, 30s npm). `npm audit` failures are swallowed silently.
- **Rebuild notes:** Reuse the *runtime* resolver for a dependency rather than a second lookup, so the health check cannot diverge from what the tool will actually find — that is the explicit design rule here.

### hermes doctor — section “API Connectivity”  `id: cli-d.doctor-api-connectivity`
- **Surface:** CLI
- **Where:** `◆ API Connectivity` block.
- **What it does:** Fires one bounded HTTP/SDK probe per configured model provider in parallel and prints one line per provider.
- **How it works:** `hermes_cli/doctor.py:2729`. Each probe is a pure function returning `_ConnectivityResult(label, lines, issues)`; nothing prints from inside a worker. Submission order: `_probe_openrouter`, `_probe_anthropic`, then one generic `_probe_apikey_provider` per entry of `_build_apikey_providers_list()` (cached in `_APIKEY_PROVIDERS_CACHE`), then `_probe_bedrock`, then `_probe_azure_entra`. Execution: a `ThreadPoolExecutor(max_workers=8, thread_name_prefix="doctor-probe")`; `AWS_EC2_METADATA_DISABLED=true` is set on the parent thread for the duration (and restored) so boto3 does not spend seconds probing `169.254.169.254`. A progress line `  Running <N> connectivity checks in parallel…` is printed and then erased with `\r` + 70 spaces + `\r`.
- **Inputs / options:** none (the provider list is derived from config + env).
- **Static API-key provider table** (`_build_apikey_providers_list`, `doctor.py:935`), as `(label, key env vars, models URL, base-URL env, supports /models)`:
  - `Z.AI / GLM` — `GLM_API_KEY`, `ZAI_API_KEY`, `Z_AI_API_KEY` — `https://api.z.ai/api/paas/v4/models` — `GLM_BASE_URL` — yes
  - `Kimi / Moonshot` — `KIMI_API_KEY` — `https://api.moonshot.ai/v1/models` — `KIMI_BASE_URL` — yes
  - `StepFun Step Plan` — `STEPFUN_API_KEY` — `https://api.stepfun.ai/step_plan/v1/models` — `STEPFUN_BASE_URL` — yes
  - `Kimi / Moonshot (China)` — `KIMI_CN_API_KEY` — `https://api.moonshot.cn/v1/models` — (none) — yes
  - `Arcee AI` — `ARCEEAI_API_KEY` — `https://api.arcee.ai/api/v1/models` — `ARCEE_BASE_URL` — yes
  - `GMI Cloud` — `GMI_API_KEY` — `https://api.gmi-serving.com/v1/models` — `GMI_BASE_URL` — yes
  - `DeepSeek` — `DEEPSEEK_API_KEY` — `https://api.deepseek.com/v1/models` — `DEEPSEEK_BASE_URL` — yes
  - `Hugging Face` — `HF_TOKEN` — `https://router.huggingface.co/v1/models` — `HF_BASE_URL` — yes
  - `NVIDIA NIM` — `NVIDIA_API_KEY` — `https://integrate.api.nvidia.com/v1/models` — `NVIDIA_BASE_URL` — yes
  - `Alibaba/DashScope` — `DASHSCOPE_API_KEY` — `https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models` — `DASHSCOPE_BASE_URL` — yes
  - `MiniMax` — `MINIMAX_API_KEY` — `https://api.minimax.io/v1/models` — `MINIMAX_BASE_URL` — yes
  - `MiniMax (China)` — `MINIMAX_CN_API_KEY` — `https://api.minimaxi.com/v1/models` — `MINIMAX_CN_BASE_URL` — **no** (endpoint 404s on `/models`)
  - `Vercel AI Gateway` — `AI_GATEWAY_API_KEY` — `https://ai-gateway.vercel.sh/v1/models` — `AI_GATEWAY_BASE_URL` — yes
  - `Kilo Code` — `KILOCODE_API_KEY` — `https://api.kilo.ai/api/gateway/models` — `KILOCODE_BASE_URL` — yes
  - `OpenCode Zen` — `OPENCODE_ZEN_API_KEY` — `https://opencode.ai/zen/v1/models` — `OPENCODE_ZEN_BASE_URL` — yes
  - `OpenCode Go` — `OPENCODE_GO_API_KEY` — (no models URL) — `OPENCODE_GO_BASE_URL` — **no**
  The list is then extended with every `providers.list_providers()` `ProviderProfile` whose `auth_type == "api_key"` and that is not already present by display name or canonical name, excluding `{anthropic, openrouter, bedrock}` (which have dedicated probes with non-Bearer auth). For plugin profiles, key vars are the `env_vars` **not** ending in `_BASE_URL`/`_URL`; the base-URL var is the first that does; the models URL is `models_url` or `base_url + "/models"`; `supports_health_check` (default `True`) gates the probe.
- **Outputs / side effects:** One line per probe, e.g. `⚠ OpenRouter API (not configured)`, `⚠ AWS Bedrock (ClientError: …)`. Failed probes append remediation strings to `issues`, except when `_has_healthy_oauth_fallback_for_apikey_provider(label)` says the provider (currently `minimax` or `xai`) already has a healthy OAuth login — then the row still prints but the issue is dropped.
- **Config / env:** every env var in the table above, plus `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, AWS credentials, and `model.entra.scope` for the Azure probe.
- **Azure Foundry (Entra ID) probe** (`_probe_azure_entra`, `doctor.py:3015`): imports `agent.azure_identity_adapter`; adapter import failure → `⚠ … (adapter import failed: <exc>)` + issue; `azure-identity` missing → `⚠ … (azure-identity not installed)` + issue `Install azure-identity: <python> -m pip install azure-identity`; otherwise `describe_active_credential(config=EntraIdentityConfig(scope=<model.entra.scope or SCOPE_AI_AZURE_DEFAULT>), timeout_seconds=10.0)` → `✓ … (<env sources or "default credential chain">, scope=<scope>)` or `⚠ … (<error>)` + issue `Azure Foundry Entra: <err>. <hint>` where the default hint is `Run \`az login\`, set AZURE_TENANT_ID/AZURE_CLIENT_ID/AZURE_CLIENT_SECRET, or attach a managed identity to this VM.`
- **Edge cases / guards:** Closures capture loop variables via default arguments (a real bug class the comment calls out). Results are printed strictly in submission order regardless of completion order.
- **Rebuild notes:** Pure probe functions + ordered result printing is what makes parallelism safe here; disable cloud metadata lookups before fanning out.

### hermes doctor — section “Tool Availability”  `id: cli-d.doctor-tool-availability`
- **Surface:** CLI
- **Where:** `◆ Tool Availability` block.
- **What it does:** Lists every toolset that is currently loadable and every one that is not, with the reason (missing env var vs unmet system dependency).
- **How it works:** `hermes_cli/doctor.py:3158`. Calls `model_tools.check_tool_availability()` then `_apply_doctor_tool_availability_overrides()` (`doctor.py:353`), which (a) promotes `kanban` to available when it is unavailable only because this is not a dispatcher-spawned worker (`_is_kanban_worker_env_gate`: name is `kanban`, `HERMES_KANBAN_TASK` unset, and every listed tool starts with `kanban_`), and (b) promotes `honcho` when `_honcho_is_configured_for_doctor()` is true. The `web` toolset is split into two readiness rows by `_doctor_web_capability_rows()` (`doctor.py:299`) which loads web plugins (`_ensure_web_plugins_loaded()`) and reports `web search` and `web extract` separately using the same `get_active_search_provider()`/`get_active_extract_provider()` resolvers plus `_provider_is_ready()`.
- **Inputs / options:** none.
- **Outputs / side effects:** `✓ <toolset display name> [<detail>]` per available toolset — the only detail currently emitted is `(runtime-gated; loaded only for dispatcher-spawned workers)` for `kanban` (`_doctor_tool_availability_detail`, `doctor.py:292`). Web rows: `✓ web search (<provider name>)` / `✓ web extract (<provider name>)`, or `⚠ web search (no provider selected or registered)` / `⚠ web search (<name> selected; provider not configured)`. Unavailable rows: `⚠ <name> (missing <VAR1, VAR2>)` when env vars are known, else `⚠ <name> (system dependency not met)`. When any *CLI-enabled* API-key toolset is missing keys, or any web row is not ok, one issue is appended: `Run 'hermes setup' to configure missing API keys for full tool access`. Total failure → `⚠ Could not check tool availability (<e>)`.
- **Config / env:** `HERMES_KANBAN_TASK`; the CLI platform toolset list from `hermes_cli.tools_config._get_platform_tools(cfg, "cli")` decides which missing-key warnings are promoted into the summary (`_missing_api_key_toolsets_for_summary`, `doctor.py:685`).
- **Edge cases / guards:** A toolset can warn in the list yet be excluded from the final summary because it is not enabled for the CLI platform.
- **Rebuild notes:** Separate "the toolset cannot load" from "the toolset is not enabled here"; only the former belongs in the actionable summary.

### hermes doctor — section “Skills Hub”  `id: cli-d.doctor-skills-hub`
- **Surface:** CLI
- **Where:** `◆ Skills Hub` block.
- **What it does:** Checks the skills hub directory, its lock file, the quarantine folder, and GitHub API authentication.
- **How it works:** `hermes_cli/doctor.py:3204`. Inspects `<home>/skills/.hub`, `<home>/skills/.hub/lock.json` (counting `installed` entries) and `<home>/skills/.hub/quarantine/*` (counting directories). GitHub auth reads `GITHUB_TOKEN` then `GH_TOKEN` via `get_env_value`, falling back to `gh auth status --json authenticated` (10s timeout).
- **Inputs / options:** none.
- **Outputs / side effects:** `✓ Skills Hub directory exists`; `✓ Lock file OK (<n> hub-installed skill(s))` or `⚠ Lock file (corrupted or unreadable)`; `⚠ <n> skill(s) in quarantine (pending review)` when non-zero; `⚠ Skills Hub directory not initialized (run: hermes skills list)`. Then `✓ GitHub token configured (authenticated API access)`, or `✓ GitHub authenticated via gh CLI (full API access — no GITHUB_TOKEN needed)`, or `⚠ No GITHUB_TOKEN (60 req/hr rate limit — set in <home>/.env for better rates)`.
- **Config / env:** `GITHUB_TOKEN`, `GH_TOKEN`.
- **Rebuild notes:** Accept either an explicit token or a delegated CLI login; state the rate limit consequence rather than just "missing".

### hermes doctor — section “Memory Provider”  `id: cli-d.doctor-memory-provider`
- **Surface:** CLI
- **Where:** `◆ Memory Provider` block.
- **What it does:** Reports which memory backend is active and whether it is actually reachable/configured.
- **How it works:** `hermes_cli/doctor.py:3245`. Reads `memory.provider` from the raw config with the managed overlay applied (`managed_scope.apply_managed_overlay`). Four branches:
  - **empty** → `✓ Built-in memory active (no external provider configured — this is fine)`.
  - **`honcho`** → resolves `HonchoClientConfig.from_global_config()` and `resolve_config_path()`: config file missing but env vars present → `✓ Honcho configured via environment variables (config file <path> not found, using HONCHO_API_KEY env var)`; config file missing and nothing in env → `⚠ Honcho config not found (run: hermes memory setup)`; `enabled: false` → `→ Honcho disabled (set enabled: true in <path> to activate)`; no key/base URL → `✗ Honcho API key or base URL not set (run: hermes memory setup)` + issue `No Honcho API key — run 'hermes memory setup'`; otherwise it resets and re-creates the client → `✓ Honcho connected (workspace=<id> mode=<recall_mode> freq=<write_frequency>)` or `✗ Honcho connection failed <e>` + issue `Honcho unreachable: <e>`. `ImportError` → `✗ honcho-ai not installed (pip install honcho-ai)` + issue.
  - **`mem0`** → `✓ Mem0 API key configured` + `→ user_id=<id>  agent_id=<id>`, or `✗ Mem0 API key not set (set MEM0_API_KEY in .env or run hermes memory setup)` + issue, or `✗ Mem0 plugin not loadable (pip install mem0ai)` + issue.
  - **any other provider** (e.g. `openviking`, `hindsight`) → `plugins.memory.load_memory_provider(name)`: available → `✓ <name> provider active`; loaded but unavailable → `⚠ <name> configured but not available (run: hermes memory status)`; not found → `⚠ <name> plugin not found (run: hermes memory setup)`; exception → `⚠ <name> check failed <e>`.
- **Config / env:** `memory.provider`, `HONCHO_API_KEY`, `MEM0_API_KEY`, the Honcho plugin config file.
- **Rebuild notes:** Treat "no provider" as a healthy state, not a warning.

### hermes doctor — section “Profiles”  `id: cli-d.doctor-profiles`
- **Surface:** CLI
- **Where:** `◆ Profiles` block — printed only when at least one non-default profile exists.
- **What it does:** Lists named profiles with their gateway state, model, and missing artefacts, and flags orphaned shell aliases.
- **How it works:** `hermes_cli/doctor.py:3346`. `list_profiles()` filtered to `not p.is_default`; per profile it assembles parts: `gateway running` (when `p.gateway_running`), the first 30 chars of `p.model`, `⚠ missing config` when `<profile>/config.yaml` is absent, `no .env` when `<profile>/.env` is absent, `no alias` when `<wrapper_dir>/<name>` is absent. Then it scans every file in `_get_wrapper_dir()` for the substring `hermes -p` and extracts the profile name with `re.search(r"hermes -p (\S+)")`.
- **Inputs / options:** none.
- **Outputs / side effects:** `✓ <n> profile(s) found`, then `✓   <name>: <comma-joined parts>` or `✓   <name>: configured` when nothing is noteworthy; plus `⚠ Orphan alias: <wrapper filename> → profile '<name>' no longer exists`.
- **Rebuild notes:** Report per-profile completeness as a compact status string; detect orphan wrappers by parsing what the wrapper actually invokes.

### hermes doctor --fix  `id: cli-d.doctor-fix`
- **Surface:** CLI
- **Where:** `hermes doctor --fix`. Help: *"Attempt to fix issues automatically"*.
- **What it does:** Runs the same checks but applies the repairs each check knows how to make, counts them, and reports how many issues still need a human.
- **How it works:** `should_fix = getattr(args, 'fix', False)` at `hermes_cli/doctor.py:1238`, threaded into every fixable check and incrementing `fixed_count`.
- **Complete list of what `--fix` repairs:**
  1. Installs the macOS TCC interpreter anchor (`ensure_tcc_anchor()`).
  2. Force-reinstalls `certifi` and re-verifies the CA bundle.
  3. Creates an empty `~/.hermes/.env` with mode `0600`.
  4. Creates `~/.hermes/config.yaml` from `cli-config.yaml.example` or from `DEFAULT_CONFIG`.
  5. Runs `migrate_config(interactive=False, quiet=False)` when the config version is behind.
  6. Moves stale root-level `provider` / `base_url` keys under `model:` (atomic write).
  7. Removes the stale `HERMES_MAX_ITERATIONS` line from `.env`.
  8. Creates `~/.hermes` and each missing sub-directory (`cron`, `sessions`, `logs`, `skills`, `memories`).
  9. Writes a template `SOUL.md`.
  10. Creates `~/.hermes/memories/`.
  11. Repairs `state.db` FTS write health via `repair_state_db_schema()` (writes a backup beside the DB).
  12. Repairs a malformed `state.db` schema via the same function.
  13. Runs `PRAGMA wal_checkpoint(PASSIVE)` on an oversized WAL.
  14. Creates or re-points the `~/.local/bin/hermes` (or `$PREFIX/bin/hermes`) symlink.
  15. Warms the npx cache for `agent-browser` (`warm_agent_browser_npx_cache()`).
- **Outputs / side effects:** Everything the list above touches, plus the closing block `  Fixed <N> issue(s).` (green, bold) and, when anything remains, ` <M> issue(s) require manual intervention.` followed by the numbered remaining list.
- **Edge cases / guards:** `--fix` never uninstalls packages, never edits `mcp_servers`, never touches credentials, and never resolves an advisory — those stay in `manual_issues`.
- **Rebuild notes:** Every auto-fix should be idempotent, back up before mutating a database, and be counted so the user can see what changed.

### hermes doctor --live  `id: cli-d.doctor-live`
- **Surface:** CLI
- **Where:** `hermes doctor --live`; output appears in a final `◆ Live Backend Probes (opt-in, real calls)` section after every static check.
- **What it does:** Makes one bounded, read-only, metadata-only network call per configured tool backend to prove the credentials and connectivity actually work.
- **How it works:** `hermes_cli/doctor_live.py`. `maybe_run_live_checks(args, manual_issues)` (line 320) no-ops unless `args.live`; `run_live_checks()` (line 267) resolves the timeout from `doctor.live_probe_timeout` (default `DEFAULT_PROBE_TIMEOUT = 10.0`, floored at `1.0`) and runs probes **sequentially** for predictable ordering. Every probe is wrapped by `_run_one()` which converts any exception into a `fail` (with `(timed out: …)` when the message contains `time`).
- **Probes, in order:**
  1. **Firecrawl** — `GET https://api.firecrawl.dev/v2/team/credit-usage` with `Authorization: Bearer $FIRECRAWL_API_KEY`; no key → `skip (not configured)`.
  2. **FAL** — `GET https://fal.ai/api/models?page=1` with `Authorization: Key $FAL_KEY`; no key → `skip (not configured)`.
  3. **Browser** — availability via `agent-browser` on PATH, `<PROJECT_ROOT>/node_modules/agent-browser`, `<home>/node/bin`, `<home>/node`, `<home>/node_modules/.bin`, or the npx sentinel from `tools.browser_tool._find_agent_browser(validate=False)` (excluding the Termux carve-out). Then `_launch_browser_probe` launches headless Chromium via `playwright.sync_api`, opens `about:blank`, closes → detail `(launched + about:blank + closed)`; missing Playwright → `(playwright not installed)`.
  4. **MCP: <name>** — one entry per key of `mcp_servers`, sorted; runs `hermes_cli.mcp_config._probe_single_server(name, config, connect_timeout=timeout)` (the same machinery as `hermes mcp test`) and reports `(<n> tool(s))`; a non-dict entry → `skip (malformed config entry)`. No servers at all → a single `MCP skip (no servers configured)` row.
  5. **TTS** — provider from `tts.provider`; `""`/`local`/`edge`/`neutts`/`kittentts`/`piper` → `skip (provider '<p|local>' — no remote backend to probe)`; `openai` → `GET https://api.openai.com/v1/models` (Bearer `OPENAI_API_KEY`); `groq` → `GET https://api.groq.com/openai/v1/models` (Bearer `GROQ_API_KEY`); `elevenlabs` → `GET https://api.elevenlabs.io/v1/voices` (header `xi-api-key: $ELEVENLABS_API_KEY`); any other provider → `skip (provider '<p>' — no live probe implemented)`; provider set but key missing → `warn (provider '<p>' configured but <VAR> is not set)`.
  6. **STT** — identical logic against `stt.provider`.
- **Inputs / options:** the `--live` flag only; timeout via config.
- **Outputs / side effects:** Real HTTP requests and (for Browser) a headless Chromium launch. Rows: `✓ <name> (<detail>)` for pass, `⚠` for warn, `✗` for fail (which also appends `Live probe failed: <name> <detail>` to the manual-issue list), and `    → <name> <detail> — skipped` for skip. HTTP classification (`_classify_http`, line 150): 2xx → `pass (HTTP <code>)`; 401/403 → `fail (HTTP <code> — check <KEY_ENV_VAR>)`; anything else → `fail (HTTP <code>)`. A crash of the whole subsystem prints `⚠ Live backend probes crashed (<exc>)`.
- **Config / env:** `doctor.live_probe_timeout`, `tts.provider`, `stt.provider`, `mcp_servers`, `FIRECRAWL_API_KEY`, `FAL_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`.
- **Edge cases / guards:** Metadata GETs only — explicitly never a generation call, never a scrape that spends credits, never a state mutation. Unconfigured backends skip, never fail.
- **Rebuild notes:** Make live probes opt-in, sequential, bounded, and read-only; classify 401/403 separately so the user is told *which* key to check.

### hermes doctor --ack ADVISORY_ID  `id: cli-d.doctor-ack`
- **Surface:** CLI
- **Where:** `hermes doctor --ack <ADVISORY_ID>`. Help: *"Acknowledge a security advisory by ID and exit. After ack, the advisory will no longer trigger startup banners. Run `hermes doctor` first to see active advisories and their IDs."*
- **What it does:** Records an acknowledgement for a security advisory so its startup banner stops appearing, then exits without running any other check.
- **How it works:** Fast path at the very top of `run_doctor` (`hermes_cli/doctor.py:1247`). Validates the ID against `{a.id for a in ADVISORIES}`; calls `security_advisories.ack_advisory(id)` which appends the ID to `security.acked_advisories` in `~/.hermes/config.yaml` (idempotent).
- **Inputs / options:** one advisory ID. Currently the only valid value is `shai-hulud-2026-05`.
- **Outputs / side effects:** Writes config.yaml. Success → green `  ✓ Acknowledged advisory <id>. It will no longer trigger startup banners.` and returns (exit 0). Unknown ID → red `Unknown advisory ID: '<id>'. Known IDs: <sorted comma list|(none)>` and `sys.exit(2)`. Persist failure → red `  ✗ Failed to persist ack for <id>. Check ~/.hermes/config.yaml is writable.` and `sys.exit(1)`.
- **Config / env:** `security.acked_advisories`.
- **Edge cases / guards:** An ack silences the banner but the doctor section still shows `⚠ <pkg>==<ver> still installed (advisory <id> acknowledged)` while the package remains on disk.
- **Rebuild notes:** Distinguish exit codes for "unknown id" (2) and "could not persist" (1); never let an ack hide the fact that the artefact is still installed.

---

## 3. `hermes verify` — project run-recipe detection and smoke test

### hermes verify  `id: cli-d.verify`
- **Surface:** CLI
- **Where:** `hermes verify [path] [--detect-only] [--save] [--skip-start] [--phase {bootstrap,build,test,start}] [--port PORT] [--timeout TIMEOUT] [--ready-timeout READY_TIMEOUT] [--json]`. Root help: *"Detect a project's run recipe and smoke-test it"*. Description: *"Detect how the current project is built, tested, and started (or load the saved manifest at .hermes/environment.json), then run a verification pass: bootstrap -> build -> test -> start in background -> poll readiness -> teardown."*
- **What it does:** Figures out how a project installs, builds, tests and starts; runs those commands in order; then boots the app in the background and polls an HTTP readiness URL before tearing the process group down. A passing run is written into the coding-verification evidence ledger, so it satisfies the verify-on-stop guard the same way a passing canonical test command does.
- **How it works:** Parser `hermes_cli/subcommands/verify.py:17`; handler `hermes_cli/verify_cmd.py:21` `run_verify_command(args)`. Flow: resolve `path` (default `.`), `agent.verify.environment.load_or_detect(root)` → `(recipe, source)` where a saved `<root>/.hermes/environment.json` wins over fresh detection (source `"manifest"` vs `"detected"`). For a *detected* recipe only, `_merge_project_facts_commands()` (`verify_cmd.py:88`) appends any `agent.coding_context.detect_project_facts(root).verify_commands` not already in bootstrap/build/test into `recipe.test` — the prompt layer and the runtime layer union rather than contradict. Execution is `agent/verify/runner.py:238` `run_verify()`: phases `("bootstrap","build","test")` in order (each command via `subprocess.run(shell=True, cwd=root)`), stopping at the first failure (`stop_on_failure=True`); then, unless skipped or a phase failed or `recipe.start` is empty, `_run_start_phase()` spawns the start command with `start_new_session=True`, polls `http://127.0.0.1:<port><readiness_path>` every 1s with a 5s per-request timeout, and tears down via `_terminate_process_group()` (SIGTERM to the process group, `wait(10)`, then SIGKILL, `wait(5)`; on Windows `proc.terminate()`/`kill()` on the direct child only).
- **Inputs / options:**
  - positional `path` (optional) — *"Project root to verify (default: current directory)"*.
  - `--detect-only` — *"Only detect and print the recipe as JSON; run nothing"*.
  - `--save` — *"Save the recipe as .hermes/environment.json in the project"*.
  - `--skip-start` — *"Run command phases but skip starting the app / readiness poll"*.
  - `--phase {bootstrap,build,test,start}` — *"Run only the given phase(s); repeatable"* (argparse `action="append"`).
  - `--port PORT` (int) — *"Override the port used for the readiness poll"*; also overwrites `recipe.port` before `--save`/`--detect-only`.
  - `--timeout TIMEOUT` (float) — *"Per-phase timeout in seconds (default: 600)"* (`DEFAULT_PHASE_TIMEOUT = 600.0`).
  - `--ready-timeout READY_TIMEOUT` (float) — *"Readiness poll timeout in seconds (default: 60)"* (`DEFAULT_READY_TIMEOUT = 60.0`).
  - `--json` — *"Emit a machine-readable JSON result"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Runs arbitrary project commands with `shell=True` (documented as the same trust level as the terminal tool). May write `<root>/.hermes/environment.json`. Always attempts to append to the verification evidence ledger via `agent.verification_evidence.record_verify_run(root, session_id=$HERMES_SESSION_ID, ok, command="hermes verify", scope="targeted"|"full", output=<joined tails>)` — `scope` is downgraded to `targeted` whenever `--phase` or `--skip-start` was used, so a partial pass is never presented as a full green. Human report (`_print_human_report`, `verify_cmd.py:151`): `Recipe: <name> (<kind>) — source: <manifest|detected>`, blank line, one aligned row per phase `  <phase>  <PASS|FAIL|TIMEOUT>  <duration>s  <command>` (or `  (no phases executed)`), an equivalent `start` row, `Readiness: <url> -> ready (HTTP <code>)|not ready (<error|timeout>)`, then `Result: OK|FAILED` and, for each failure, `--- output tail: <phase> (<command>) ---` followed by up to 2000 characters of combined stdout+stderr (`_TAIL_CHARS = 2000`).
- **JSON shapes:** `--detect-only` prints `{"source": <src>, "recipe": {...}}` (indent 2 unless `--json`). A run with `--json` prints `VerifyResult.to_dict()` plus `"source"`: `{"recipe": <name>, "ok": <bool>, "phases": [{"phase","command","exitCode","duration","ok","timedOut","outputTail"}], "readiness": {"url","ready","statusCode","duration","error","outputTail"} | null, "source": …}`. Recipe dict keys: `name`, `kind`, `bootstrap`, `build`, `test`, `start`, `port`, `readinessPath`, `evidence`.
- **Config / env:** `HERMES_SESSION_ID` (recorded with the evidence entry). No config keys.
- **Exit codes:** `2` when `path` is not a directory (`error: not a directory: <root>` on stderr); `1` when no recipe could be resolved (message `No recognizable project found at <root>.` + `Create <root>/.hermes/environment.json to define a recipe manually.` on stderr, or `{"ok": false, "error": "no-recipe", "root": …}` with `--json`); `0` for `--detect-only`; otherwise `0` when `result.ok` else `1`.
- **Edge cases / guards:** A readiness poll counts an `HTTPError` (4xx/5xx) as *ready* — the server answered. Phase failure short-circuits the rest and skips the start phase entirely. A malformed manifest silently degrades to fresh detection (`load_manifest` swallows every read/parse/shape problem). `_merge_project_facts_commands` never runs against a saved manifest (user file is the source of truth) and never raises.
- **Rebuild notes:** Model a project as `(bootstrap[], build[], test[], start, port, readiness_path)`; run phases sequentially, start in a new session so the whole tree can be killed, and treat any HTTP response as "up". A better version would stream phase output live, support multiple readiness probes (TCP/HTTP/log-line), and record per-phase artefacts.

### `hermes verify` phase — bootstrap  `id: cli-d.verify-phase-bootstrap`
- **Surface:** CLI
- **Where:** `hermes verify --phase bootstrap`. First entry of `PHASE_ORDER = ("bootstrap", "build", "test")` (`agent/verify/runner.py:30`).
- **What it does:** Runs every command in `recipe.bootstrap` (the install/dependency step) in the project root.
- **How it works:** `run_verify()` loops `getattr(recipe, "bootstrap")` and calls `_run_phase_command("bootstrap", cmd, root, phase_timeout, on_output)` (`runner.py:98`), which uses `subprocess.run(cmd, shell=True, cwd=root, stdout=PIPE, stderr=STDOUT, timeout=…, text=True, errors="replace")`.
- **Inputs / options:** `--timeout` bounds each command; `--phase bootstrap` selects it alone.
- **Detected commands per project kind:** Node → `pnpm install` / `bun install` / `yarn install` / `npm install` (lockfile-chosen). Python → `uv sync` (uv.lock), `poetry install` (poetry.lock), `pipenv install` (Pipfile.lock), `pip install -e .` (pyproject with no requirements.txt), else `pip install -r requirements.txt`. Go / Rust / Java / compose → none. Makefile → `make <install|setup|bootstrap>` (first target present).
- **Outputs / side effects:** Whatever the project's install command does. `PhaseResult` with `exit_code`, `duration`, a 2000-char `output_tail`, and `timed_out`.
- **Edge cases / guards:** A timeout yields `exit_code=None`, `timed_out=True`, and status `TIMEOUT`; it counts as a failure and stops the run.
- **Rebuild notes:** Choose the package manager from lockfiles, never from what happens to be installed.

### `hermes verify` phase — build  `id: cli-d.verify-phase-build`
- **Surface:** CLI
- **Where:** `hermes verify --phase build`.
- **What it does:** Runs every command in `recipe.build`.
- **Detected commands per project kind:** Node → the deduped `<runner> build` and `<runner> typecheck` for whichever of the `build`/`typecheck` scripts exist, where `<runner>` is `pnpm <s>` / `bun run <s>` / `yarn <s>` / `npm run <s>` (`_script_runner`, `agent/verify/recipes.py:183`). Go → `go build ./...`. Rust → `cargo build`. Maven → `mvn package`. Gradle → `./gradlew build` or `gradle build`. Makefile → `make <build|compile>`. docker-compose → `docker compose build`. Django/FastAPI/Flask/generic Python → none.
- **How it works / Inputs / Outputs / Edge cases / Rebuild notes:** identical machinery to `cli-d.verify-phase-bootstrap`.

### `hermes verify` phase — test  `id: cli-d.verify-phase-test`
- **Surface:** CLI
- **Where:** `hermes verify --phase test`.
- **What it does:** Runs every command in `recipe.test`, including any commands folded in from `detect_project_facts` when the recipe was detected rather than loaded from a manifest.
- **Detected commands per project kind:** Node → deduped `<runner> test`, `<runner> check`, `<runner> lint` for whichever scripts exist. Django → `python manage.py test`. FastAPI / Flask → `pytest` when a `tests/` directory exists, else nothing. Generic Python → `pytest` when `tests/` exists, else `python -m unittest discover`. Go → `go test ./...`. Rust → `cargo test`. Maven → `mvn test`. Gradle → `./gradlew test` / `gradle test`. Makefile → `make <test|check>`. docker-compose → none.
- **How it works:** Same runner. Additionally `_merge_project_facts_commands` (`hermes_cli/verify_cmd.py:88`) appends any `detect_project_facts(root).verify_commands` (e.g. `scripts/run_tests.sh`, a project-specific pytest invocation) that is not already present in bootstrap/build/test.
- **Edge cases / guards:** Deduped by exact stripped string; the merge is best-effort and never raises.
- **Rebuild notes:** Union the "cheap prompt-time facts" layer into the runtime recipe rather than letting the two disagree.

### `hermes verify` phase — start (background boot + readiness poll)  `id: cli-d.verify-phase-start`
- **Surface:** CLI
- **Where:** `hermes verify --phase start`; suppressed by `--skip-start`.
- **What it does:** Launches the project's start command in the background, polls an HTTP readiness URL until it answers or the timeout expires, then kills the whole process group.
- **How it works:** `_run_start_phase()` (`agent/verify/runner.py:200`). Port = `--port` → `recipe.port` → `8000`. URL = `http://127.0.0.1:<port><recipe.readiness_path>` (readiness path defaults to `/`). `subprocess.Popen(recipe.start, shell=True, cwd=root, stdout=PIPE, stderr=STDOUT, start_new_session=True)`. `_poll_readiness(url, ready_timeout, interval=1.0)` uses `urllib.request.urlopen(url, timeout=5)`; an `HTTPError` counts as ready (the server answered) and its code is reported; `URLError`/`OSError`/`TimeoutError` record the last error and retry. Teardown always runs in a `finally`.
- **Detected start commands and ports per project kind:** Next.js → `<runner> dev|start`, port 3000; SvelteKit → port 5173; Astro → port 4321; Remix → port 3000; Create React App → port 3000; Vite → port 5173; plain Node → no default port. The port is first inferred from the start script body via `_infer_port_from_command` (`recipes.py:158`) which matches `(?:--port|-p)\s+(\d{2,5})` then `\bPORT=(\d{2,5})\b`, falling back to the framework default. Django → `python manage.py runserver 0.0.0.0:8000`, port 8000. FastAPI → `uvicorn <main:app|app:app> --host 0.0.0.0 --port 8000`, port 8000 (module chosen by the presence of `main.py` then `app.py`, defaulting to `main:app`). Flask → `flask --app <app.py|main.py> run --host 0.0.0.0 --port 5000`, port 5000. Go → `go run .` only when `main.go` exists. Rust → `cargo run` only when `src/main.rs` exists. Makefile → `make <run|start|serve|dev>`. docker-compose → `docker compose up`. Maven/Gradle/generic Python → no start command.
- **Inputs / options:** `--port`, `--ready-timeout`, `--skip-start`, `--phase start`.
- **Outputs / side effects:** Starts and then kills a real server process tree. `ReadinessResult` with `url`, `ready`, `status_code`, `duration`, `error`, `output_tail`.
- **Edge cases / guards:** The start phase is skipped when `skip_start`, when `"start"` is not in the selected phases, when any earlier phase failed, or when `recipe.start` is empty. The child's stdout is read only after teardown, so a chatty server cannot deadlock the poll on a full pipe.
- **Rebuild notes:** `start_new_session=True` + `killpg` is the difference between a clean teardown and orphaned servers; read the pipe after termination, not during.

### `hermes verify --detect-only`  `id: cli-d.verify-detect-only`
- **Surface:** CLI
- **Where:** `hermes verify --detect-only [--json]`.
- **What it does:** Prints the resolved recipe as JSON and exits without executing anything.
- **How it works:** `hermes_cli/verify_cmd.py:57` — prints `json.dumps({"source": source, "recipe": recipe.to_dict()}, indent=None if args.json else 2)` and returns 0.
- **Inputs / options:** combines with `path`, `--json` (compact vs indented), `--port` (which mutates the printed `port`) and `--save`.
- **Outputs / side effects:** stdout only, unless `--save` was also given.
- **Rebuild notes:** Make detection independently inspectable — it is the part users will want to correct by hand.

### `hermes verify --save` / the `.hermes/environment.json` manifest  `id: cli-d.verify-manifest`
- **Surface:** CLI / Config
- **Where:** `hermes verify --save`; file at `<project>/.hermes/environment.json`.
- **What it does:** Persists the detected (or overridden) recipe as the project's user-editable verification manifest, which then wins over fresh detection on every later run.
- **How it works:** `agent/verify/environment.py:49` `save_manifest(root, recipe)` writes `{"version": 1, "recipe": <recipe dict>, "updatedAt": <UTC ISO>}` with `indent=2` and a trailing newline, creating `<root>/.hermes/` if needed. `load_manifest()` (line 26) accepts both the wrapped `{version, recipe}` shape and a bare recipe object, and returns `None` on any `OSError`, JSON error, or non-dict shape. `Recipe.from_dict` (`agent/verify/recipes.py:68`) is tolerant and accepts grok-cli aliases: `appLabel`→`name`, `appKind`→`kind`, `installCommands`→`bootstrap`, `buildCommands`→`build`, `testCommands`→`test`, `startCommand`→`start`, `startPort`→`port`, `readiness_path`/`readinessPath`→`readiness_path`. A string in a command field is accepted and wrapped in a one-element list. `port` must be an int (or a digit string) in `0 < p < 65536`; `readinessPath` must start with `/` or it is reset to `/`.
- **Inputs / options:** the `--save` flag; the JSON fields listed above are the user-editable surface.
- **Outputs / side effects:** Writes the file and prints `Saved manifest: <path>` (suppressed with `--json`).
- **Config / env:** `MANIFEST_VERSION = 1`.
- **Edge cases / guards:** A corrupt manifest degrades to detection instead of erroring. Because a manifest wins, `_merge_project_facts_commands` is deliberately not applied to it.
- **Rebuild notes:** Store a version wrapper, accept aliases for a friendlier hand-edit, and never fail hard on a bad file.

---

## 4. `hermes security` — supply-chain audit

### hermes security  `id: cli-d.security`
- **Surface:** CLI
- **Where:** `hermes security`. Root help: *"Supply-chain audit (OSV.dev) for venv, plugins, and MCP servers"*. Description: *"On-demand vulnerability scan against OSV.dev. Covers the Hermes venv (installed PyPI dists), Python deps declared by plugins under ~/.hermes/plugins/, and pinned npx/uvx MCP servers in config.yaml. Does NOT scan globally-installed packages or editor/browser extensions."*
- **What it does:** Command group whose only sub-command is `audit`.
- **How it works:** Parser at `hermes_cli/subcommands/security.py:12`; `security_parser.set_defaults(func=cmd_security)` so a bare `hermes security` dispatches to the same handler with `security_command=None`.
- **Inputs / options:** `-h`, `--help`; sub-command `audit`.
- **Rebuild notes:** Keep the scope statement in the help text — being explicit about what is *not* scanned is what makes the tool trustworthy.

### hermes security audit  `id: cli-d.security-audit`
- **Surface:** CLI
- **Where:** `hermes security audit [--json] [--fail-on {low,moderate,high,critical}] [--skip-venv] [--skip-plugins] [--skip-mcp]`. Help: *"Run a one-shot supply-chain audit"*. Description: *"Query OSV.dev for known vulnerabilities in installed components."*
- **What it does:** Enumerates every auditable component on three surfaces (installed venv distributions, plugin-declared Python pins, pinned npx/uvx MCP packages), asks OSV.dev which of them have known vulnerabilities, prints the findings sorted by severity, and exits non-zero when anything meets the `--fail-on` threshold.
- **How it works:** `hermes_cli/security_audit.py:522` `cmd_security_audit(args)`.
  - **Discovery** (`_discover_components`, line 411): `_discover_venv()` walks `importlib.metadata.distributions()` and emits `Component(name, version, ecosystem="PyPI", source="venv")` deduped case-insensitively by `(name.lower(), version)`. `_discover_plugins(home)` walks `~/.hermes/plugins/*/` (skipping dot-dirs), reading `requirements.txt`, `requirements-dev.txt` (via `_parse_requirements`, which accepts **only** exact `name[extras]==version` pins, dropping comments, `-` option lines and environment markers) and `pyproject.toml` (`_parse_pyproject_pins` uses `tomllib` and collects `project.dependencies` plus every `project.optional-dependencies` group, again exact pins only); source is `plugin:<dirname>`. `_discover_mcp()` reads `hermes_cli.mcp_config._get_mcp_servers()` and maps `command/args` through `_extract_mcp_component` (line 216): for `npx` (any path ending in `npx`) it skips leading `-` flags and matches the first non-flag token against `^(@scope/pkg|pkg)@version$` → npm component; for `uvx` it matches `^pkg==version$` → PyPI component; anything else (local path, docker image, unversioned npx) yields nothing. Source is `mcp:<server name>`.
  - **Lookup**: `_osv_query_batch` POSTs to `https://api.osv.dev/v1/querybatch` in chunks of `OSV_BATCH_MAX = 1000` with a 20s `HTTP_TIMEOUT`; a network failure raises `RuntimeError("OSV batch query failed: …")`. `_osv_fetch_details` then GETs `https://api.osv.dev/v1/vulns/{id}` for each unique id with a `ThreadPoolExecutor(max_workers=DETAIL_PARALLELISM=8)`; a fetch failure degrades that vuln to `severity="UNKNOWN"` with no summary.
  - **Severity** (`_osv_severity_from_record`, line 330): prefers `database_specific.severity` when it is one of the known tiers, then `affected[].ecosystem_specific.severity`, then a CVSS numeric mapped as `>=9.0 CRITICAL`, `>=7.0 HIGH`, `>=4.0 MODERATE`, `>0 LOW`; otherwise `UNKNOWN`. Ordering table `SEVERITY_ORDER = {UNKNOWN:0, LOW:1, MODERATE:2, MEDIUM:2, HIGH:3, CRITICAL:4}`.
  - **Fix versions** (`_osv_fixed_versions`): every `affected[].ranges[].events[].fixed`, order-preserving deduped.
  - **Sorting**: descending severity, then `component.source`, then lowercased package name, then OSV id.
- **Inputs / options:**
  - `--json` — *"Emit machine-readable JSON instead of human-readable text"*.
  - `--fail-on {low,moderate,high,critical}` (default `critical`) — *"Exit non-zero when any finding meets this severity (default: critical)"*.
  - `--skip-venv` — *"Skip scanning the Hermes Python venv"*.
  - `--skip-plugins` — *"Skip scanning plugin requirements files"*.
  - `--skip-mcp` — *"Skip scanning pinned MCP servers in config.yaml"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Network calls to OSV.dev only; nothing written to disk. Human output (`_render_human`): `No known vulnerabilities found across <N> component(s).` or `Found <M> known vulnerability finding(s) across <N> component(s):`, a blank line, then per source group a `[<source>]` header followed by `  <SEVERITY padded to 8>  <name>==<version>  <OSV id>`, an indented summary line truncated to 100 chars with `...`, and `           fixed in: <first three fixed versions>`. Zero components → `No components discovered (everything skipped, or empty environment).` JSON output (`_render_json`): `{"total_components_scanned": N, "finding_count": M, "findings": [{"package","version","ecosystem","source","vuln_id","severity","summary","fixed_versions"}]}` with `indent=2`.
- **Config / env:** `HERMES_HOME` (plugins dir), `mcp_servers` in config.yaml.
- **Exit codes:** `0` when nothing meets the threshold (or nothing was discovered); `1` when at least one finding's severity ≥ `--fail-on`; `2` for an unknown `--fail-on` value (`unknown --fail-on value: <v> (choose from: low, moderate, high, critical)` on stderr) or an OSV query failure (`audit failed: <exc>` on stderr).
- **Edge cases / guards:** Loose pins (`>=`, `~=`, unpinned) are deliberately skipped — the module states that a false positive is worse than a missed finding for an audit tool. Unversioned `npx <pkg>` maps to "latest" at runtime and is therefore not audited. Explicitly out of scope: global pip/npm, editor/browser extensions, daily background scans, auto-blocking installs.
- **Rebuild notes:** Batch the OSV query (1000 per request), fetch details in parallel, and gate the exit code on a user-chosen severity. A better version would cache OSV responses with an ETag, resolve loose pins against the actually-installed version, and audit lockfiles (`package-lock.json`, `uv.lock`) as well as pins.

---

## 5. `hermes approvals` — dangerous-command approval tooling

### hermes approvals  `id: cli-d.approvals`
- **Surface:** CLI
- **Where:** `hermes approvals`. Root help: *"Approval-prompt tools (mine history into allowlist proposals)"*. Description: *"Tools for the dangerous-command approval system. `hermes approvals suggest` mines past approval decisions from the session database and proposes command_allowlist entries so repeatedly-approved commands stop prompting."*
- **What it does:** Group command for the two approval utilities.
- **How it works:** Parser `hermes_cli/subcommands/approvals.py:14`; dispatcher `hermes_cli/approvals_suggest.py:466` `approvals_command(args)` switching on `args.approvals_command`.
- **Inputs / options:** `-h`, `--help`; sub-commands `suggest`, `test`.
- **Outputs / side effects:** With no sub-command it prints the usage block verbatim: `usage: hermes approvals <subcommand>` / (blank) / `subcommands:` / `  suggest    Mine past approval decisions into a proposed` / `             command_allowlist (dry by default; --apply N,M to merge)` / `  test       Dry-run the approval verdict for a command without` / `             executing it (exit 0 allow / 2 ask / 3 deny)` / (blank) / ``Run `hermes approvals <subcommand> -h` for details.`` and returns exit code 1.
- **Rebuild notes:** Group "learn from history" and "explain a decision" under one namespace — they are the two questions users have about an approval system.

### hermes approvals suggest  `id: cli-d.approvals-suggest`
- **Surface:** CLI
- **Where:** `hermes approvals suggest [--apply N[,M...]] [--json] [--days DAYS] [--min-count MIN_COUNT] [--limit LIMIT] [--db DB]`. Help: *"Propose command_allowlist entries from past approvals"*. Description: *"Scan the session database for dangerous-classified commands that ran with user approval, rank the recurring patterns, and print a numbered allowlist proposal. Nothing is written unless --apply is given. Destructive classes (recursive delete, sudo, disk writes, credential edits, ...) are never proposed."*
- **What it does:** Mines the session database for commands that the dangerous-command classifier flagged but that still executed (i.e. the user approved them), aggregates the recurring ones into narrow command globs, filters out anything destructive, and prints a numbered proposal you can merge into `command_allowlist`.
- **How it works:** `hermes_cli/approvals_suggest.py:406` `suggest_command(args)`.
  - **Scan** (`scan_approval_history`, line 210): opens `~/.hermes/state.db` read-only (`file:<path>?mode=ro`). `_blocked_tool_call_ids()` collects every `role='tool'` message id whose content contains one of the `_BLOCK_MARKERS` — `BLOCKED (hardline)`, `BLOCKED: User denied`, `BLOCKED: Action `, `BLOCKED: Command flagged as dangerous`, `BLOCKED: approval required`, `BLOCKED: Failed to send approval request`, `The user has NOT consented`, `Asking the user for approval`, `approval_required`, `BLOCKED by user deny rule`. `_iter_terminal_calls()` streams `role='assistant'` rows whose `tool_calls` mention `terminal`, in batches of 2000, extracting `(tool_call_id, command)`. A command is kept when its id is not blocked, `detect_hardline_command()` says it is not hardline, and `detect_dangerous_command()` says it is dangerous — the record is `(command, class description)`.
  - **Normalise** (`normalize_command`): folds resolved user-home and Hermes-home prefixes back to `~` via `tools.approval._rewrite_resolved_user_home` / `_rewrite_resolved_hermes_home`, then collapses whitespace.
  - **Safety filter**: `is_unsafe_class(description)` drops anything matching `_UNSAFE_CLASS_RE`, built from the 33 patterns at `approvals_suggest.py:57`: `delete`, `\brm\b`, `destro`, `wipe`, `format`, `\bdisk\b`, `block device`, `fork bomb`, `kill (?:all )?process`, `kill all`, `self-termination`, `\bsudo\b`, `privilege`, `credential`, `\bssh\b`, `shell.rc`, `system config`, `system file`, `\bsql\b`, `\bchown\b`, `\bchmod\b`, `writable`, `overwrite`, `in-place edit`, `pipe`, `obfuscation`, `remote content`, `remote script`, `heredoc`, `encoded`, `command substitution`, `process substitution`, `\bdd\b`, `shutdown`, `reboot`, `hardline` (case-insensitive).
  - **Glob derivation** (`derive_glob`, line 271): returns `None` for compound commands (`_has_allowlist_shell_operator`) and for commands whose first token is an unsafe root binary — `_UNSAFE_ROOT_BINARIES = {rm, rmdir, unlink, shred, dd, fdisk, parted, wipefs, sudo, doas, su, chmod, chown, chgrp, kill, killall, pkill, halt, shutdown, reboot, poweroff, init, del, format, truncate, mkswap}` plus any token starting with `mkfs`. A single-token command becomes itself; when the second token starts with `-` or contains `*?[$` the glob is `<cmd> *`; otherwise `<cmd> <subcmd> *`.
  - **Aggregate & rank** (`build_proposals`, line 297): keys on `(glob, "glob")` or, when no safe glob exists, `(class description, "class")` — the same key an interactive `[a]lways` answer would persist. Patterns already in the allowlist are skipped. Each proposal keeps a count, the set of matching class descriptions and up to three ≤100-char examples. Sorted by `(-count, pattern)` and truncated to `limit`.
  - **Apply** (`apply_proposals`, line 368): merges the chosen patterns into `tools.approval.load_permanent_allowlist()`, persists with `save_permanent_allowlist()`, and calls `load_permanent(merged)` so a long-lived process sees the change immediately.
- **Inputs / options:**
  - `--apply N[,M...]` (dest `apply_indices`) — *"Merge the numbered proposals (from a prior run) into command_allowlist in config.yaml"*. Parsed by `parse_apply_indices` (line 348): comma-separated 1-based integers, deduped, validated against the proposal count.
  - `--json` — *"Emit machine-readable JSON instead of human-readable text"*.
  - `--days DAYS` (int, default 90) — *"How far back to scan session history (default: 90; 0 = all)"*.
  - `--min-count MIN_COUNT` (int, default 2) — *"Minimum approval count for a pattern to be proposed (default: 2)"*.
  - `--limit LIMIT` (int, default 20) — *"Maximum number of proposals to show (default: 20)"*.
  - `--db DB` — *"Path to an alternate session database (default: ~/.hermes/state.db)"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Read-only unless `--apply`, which rewrites `command_allowlist` in `~/.hermes/config.yaml`. Human output (`_render_text`, line 380): `Proposed command_allowlist additions (from approval history, last <N> days|all history):`, blank line, then per proposal `  <i>. <pattern>    — approved <count>x[ (class key)]`, `       class: <description>` per class, `       e.g. <example>` per example, closing with `Nothing has been changed. Apply selected entries with:` / `  hermes approvals suggest --apply 1,3` / `Entries are merged into command_allowlist in ~/.hermes/config.yaml.` Empty result: `No allowlist candidates found in approval history (<window>).` + `Either nothing dangerous was approved often enough (see --min-count/--days), or the approved classes are excluded for safety.` Apply output: `Added to command_allowlist:` then `  + <pattern>` per entry then `command_allowlist now has <n> entries (~/.hermes/config.yaml).` JSON dry-run: `{"db": …, "days": …, "proposals": [{"n","pattern","kind","count","classes","examples"}]}`; JSON apply: `{"applied": [...], "allowlist_size": n}`.
- **Config / env:** `command_allowlist` in `~/.hermes/config.yaml`; `HERMES_HOME` for the default DB path.
- **Exit codes:** `1` when the DB does not exist (`Session database not found: <path>`) or `--apply` selection is invalid (`--apply error: <msg>`); otherwise `0`.
- **Edge cases / guards:** Never auto-applies. Hardline commands are dropped even if a stale DB row shows them running. A destructive class is excluded no matter how many times it was approved (`rm -rf build/` approved 100 times still yields no `rm` entry). The DB connection is read-only.
- **Rebuild notes:** Mine *implied* approvals (dangerous-classified + not blocked) since most approval answers are never persisted; then aggregate at a glob grain narrow enough to stay safe. A better version would keep a real approval-decision ledger with the answer type (once/session/always/yolo), so the mining step is unnecessary and the counts are exact.

### hermes approvals test  `id: cli-d.approvals-test`
- **Surface:** CLI
- **Where:** `hermes approvals test [--env-type ENV_TYPE] [--json] -- <command...>`. Help: *"Dry-run the approval verdict for a command (never executes it)"*. Description ends with the tip: *"use `--` before the command so its own flags aren't parsed: hermes approvals test -- rm -rf /tmp/x"*.
- **What it does:** Answers "what would the approval system do with this command?" by composing the real runtime guards in the real order, and prints the verdict, the matching rule and the normalized-command trace — without executing, prompting, or persisting anything.
- **How it works:** `hermes_cli/approvals_test.py:49` `evaluate_command(command, env_type)` runs the seven-stage ladder in the same order as the runtime `check_all_command_guards`:
  1. `approval._should_skip_container_guards(env_type)` → `allow`, detail `env_type '<t>' is an isolated container backend; the runtime skips all command guards for it`.
  2. `approval.detect_hardline_command(command)` → `hardline-deny`, rule = the hardline description, detail `matches the hardline blocklist (never bypassable, blocked even under --yolo / approvals.mode=off)`.
  3. `approval._check_sudo_stdin_guard(command)` → `hardline-deny`, detail `sudo stdin guard (unconditional block)`.
  4. `approval._match_user_deny_rule(command)` → `user-deny`, rule = the matching pattern, detail `matches a user-defined approvals.deny rule in config.yaml (blocked even under --yolo / mode=off)`.
  5. `approval._YOLO_MODE_FROZEN` or `is_current_session_yolo_enabled()` or `_get_approval_mode() == "off"` → `allow`, detail `approval bypass active (--yolo or approvals.mode: off); only hardline/deny rules would block`.
  6. `approval._command_matches_permanent_allowlist(command)` → `allow`, detail `matches command_allowlist in config.yaml (permanently approved)`.
  7. `approval.detect_dangerous_command(command)` → `ask-approval`, rule = the description, detail `matches a dangerous-command pattern; the runtime would raise an interactive approval prompt (pattern key: '<key>')`.
  Fallthrough → `allow`, detail `no guard matched; would run without a prompt`. `variants = list(approval._command_detection_variants(command))` is computed up front and returned as the trace, so an obfuscated command (e.g. `r\m -rf /`) gets exactly the verdict its plain form would get. `load_permanent_allowlist()` is called first (read-only) so the allowlist check sees what the runtime would see.
- **Inputs / options:**
  - positional `command` (argparse dest `command_words`, `nargs=REMAINDER`; the dest is deliberately not `command` because `main.py` reads `args.command` as the top-level sub-command name) — *"The command to evaluate (prefix with -- to protect its flags)"*. A leading `--` separator is stripped before joining the words with spaces.
  - `--env-type ENV_TYPE` (default `local`) — *"Terminal backend type to evaluate against (default: local; isolated container backends like docker skip the guards)"*.
  - `--json` — *"Emit machine-readable JSON instead of human-readable text"*.
  - `-h`, `--help`.
- **Outputs / side effects:** None — no execution, no prompt, no config write, no approval-history entry, no gateway notification. Human output (`_render_text`, line 146): `command : <cmd>`, `env-type: <t>`, `verdict : <v>  (exit <n>)`, optional `rule    : <r>`, optional `detail  : <d>`, then `normalized trace (variants the detectors evaluated):` and one `  - <variant>` per variant. JSON output is `json.dumps(verdict, indent=2)` over `{"command","env_type","verdict","exit_code","rule","detail","normalized_variants"}`.
- **Config / env:** `approvals.deny`, `approvals.mode`, `command_allowlist` in config.yaml; the session's yolo state.
- **Exit codes:** `EXIT_ALLOW = 0` (allow), `EXIT_USAGE = 1` (no command given — prints `usage: hermes approvals test [--env-type TYPE] [--json] -- <command...>`), `EXIT_ASK = 2` (ask-approval), `EXIT_DENY = 3` (`hardline-deny` or `user-deny`).
- **Edge cases / guards:** The `--` separator is required whenever the command has its own flags; without it argparse consumes them. `hardline-deny` covers both the blocklist and the sudo-stdin guard, and both map to exit 3.
- **Rebuild notes:** Compose the *real* guard functions in the *real* order rather than reimplementing the ladder, and expose the normalized variants so users can see why an obfuscated command was caught. A better version would also print which config file and line the matching rule came from.

---

## 6. `hermes dump` — copy-pasteable setup summary

### hermes dump  `id: cli-d.dump`
- **Surface:** CLI
- **Where:** `hermes dump [--show-keys]`. Root help: *"Dump setup summary for support/debugging"*. Description: *"Output a compact, plain-text summary of your Hermes setup that can be copy-pasted into Discord/GitHub for support context"*.
- **What it does:** Prints a fixed-shape, colour-free, ~50-line plain-text block describing version, OS, model, provider, terminal backend, which API keys are set, feature counts and non-default config overrides — designed to be pasted into a support thread.
- **How it works:** Parser `hermes_cli/subcommands/dump.py:12`; body `hermes_cli/dump.py:280` `run_dump(args)`. It first loads `~/.hermes/.env` (and the project `.env`) with `load_hermes_dotenv` so key checks see the real values, then assembles `lines[]` and prints them joined with `\n`. Version string = `<__version__> [<git short sha (8)>] (<commit date>)`; the SHA comes from `git rev-parse --short=8 HEAD` (5s timeout, run in `PROJECT_ROOT`) with a fallback to the baked `<project_root>/.hermes_build_sha` written by the Dockerfile's `HERMES_GIT_SHA` build arg (`hermes_cli/build_info.get_build_sha(short=8)`), else `(unknown)`. Commit date = `git log -1 --format=%cd --date=short HEAD`, dropped when unavailable. The package `__release_date__` is deliberately not shown.
- **Inputs / options:** `--show-keys` — *"Show redacted API key prefixes (first/last 4 chars) instead of just set/not set"*; `-h`, `--help`.
- **Exact output shape (in order):**
  - `--- hermes dump ---`
  - `version:          <ver> [<sha>] (<date>)`
  - `os:               <platform.system()> <release> <machine>`
  - `python:           <sys.version first token>`
  - `openai_sdk:       <openai.__version__ | not installed>`
  - `profile:          <active profile name | (default)>`
  - `hermes_home:      <display_hermes_home()>`
  - `model:            <model.default | model.model | model.name | (not set)>`
  - `provider:         <model.provider | (auto)>`
  - `terminal:         <backend>` — where a `TERMINAL_ENV` that differs from `terminal.backend` renders as `<env>  (TERMINAL_ENV overrides config.yaml terminal.backend=<cfg>)`
  - blank line, then `api_keys:` and one `  <label padded to 20> <status>` row for each of these 26 env vars (label in parentheses): `OPENROUTER_API_KEY` (openrouter), `OPENAI_API_KEY` (openai), `ANTHROPIC_API_KEY` (anthropic), `ANTHROPIC_TOKEN` (anthropic_token), `NOUS_API_KEY` (nous), `GOOGLE_API_KEY` (google/gemini), `GEMINI_API_KEY` (gemini), `GLM_API_KEY` (glm/zai), `ZAI_API_KEY` (zai), `KIMI_API_KEY` (kimi), `MINIMAX_API_KEY` (minimax), `DEEPSEEK_API_KEY` (deepseek), `DASHSCOPE_API_KEY` (dashscope), `HF_TOKEN` (huggingface), `NVIDIA_API_KEY` (nvidia), `AI_GATEWAY_API_KEY` (ai_gateway), `OPENCODE_ZEN_API_KEY` (opencode_zen), `OPENCODE_GO_API_KEY` (opencode_go), `COMMANDCODE_API_KEY` (commandcode), `KILOCODE_API_KEY` (kilocode), `FIRECRAWL_API_KEY` (firecrawl), `KEENABLE_API_KEY` (keenable), `BROWSERBASE_API_KEY` (browserbase), `FAL_KEY` (fal), `ELEVENLABS_API_KEY` (elevenlabs), `GITHUB_TOKEN` (github). Status is `set` / `not set`, or the masked value (`agent.redact.mask_secret` — first 4 and last 4 chars) with `--show-keys`. Two decorations: a key present in the process env but absent from `~/.hermes/.env` gets ` (shell only — not in .env; managed/desktop backend may not see it)`; an unset `openrouter` whose credential pool has entries becomes `set (auth pool)`.
  - blank line, then `features:` with `  toolsets:           <comma list | (default)>`, `  mcp_servers:        <count of config.mcp.servers>`, `  memory_provider:    <memory.provider | built-in>`, `  gateway:            <running (<manager>, pid <n>) | stopped (<manager>) | unknown | N/A>`, `  platforms:          <comma list | none>`, `  cron_jobs:          <N active / M total | 0 | (error reading)>`, `  skills:             <count of SKILL.md under ~/.hermes/skills excluding excluded paths>`.
  - optionally blank line, `config_overrides:` and `  <dotted key>: <value>` for each non-default value among these 17 probes: `agent.max_turns`, `agent.gateway_timeout`, `agent.session_stall_timeout`, `agent.tool_use_enforcement`, `agent.execution_guidance`, `terminal.backend`, `terminal.docker_image`, `terminal.persistent_shell`, `browser.allow_private_urls`, `compression.enabled`, `compression.threshold`, `compression.in_place`, `display.streaming`, `display.skin`, `display.show_reasoning`, `privacy.redact_pii`, `tts.provider`, plus `toolsets` (when it differs from `DEFAULT_CONFIG["toolsets"]`) and `fallback_providers` (when non-empty).
  - `--- end dump ---`
- **Platform detection table** (`_configured_platforms`, `dump.py:181`) — a platform is listed when its env var is non-empty: `telegram`→`TELEGRAM_BOT_TOKEN`, `discord`→`DISCORD_BOT_TOKEN`, `slack`→`SLACK_BOT_TOKEN`, `whatsapp`→`WHATSAPP_ENABLED`, `signal`→`SIGNAL_HTTP_URL`, `email`→`EMAIL_ADDRESS`, `sms`→`TWILIO_ACCOUNT_SID`, `matrix`→`MATRIX_HOMESERVER_URL`, `mattermost`→`MATTERMOST_URL`, `homeassistant`→`HASS_TOKEN`, `dingtalk`→`DINGTALK_CLIENT_ID`, `feishu`→`FEISHU_APP_ID`, `wecom`→`WECOM_BOT_ID`, `wecom_callback`→`WECOM_CALLBACK_CORP_ID`, `weixin`→`WEIXIN_ACCOUNT_ID`, `qqbot`→`QQ_APP_ID`.
- **Outputs / side effects:** stdout only (no ANSI colours, no checkmarks). Reads `~/.hermes/cron/jobs.json` with `utf-8-sig` (tolerating a Windows BOM) and walks `~/.hermes/skills/**/SKILL.md`.
- **Config / env:** every env var above; config keys `model.*`, `terminal.*`, `toolsets`, `mcp.servers`, `memory.provider`, `fallback_providers`, and the 17 override probes.
- **Edge cases / guards:** Never prints a raw key unless `--show-keys`, and even then it is masked. `_dotenv_key_names()` parses `.env` itself (stripping a leading `export ` and treating `KEY=` with an empty value as unset) so the "shell only" warning is accurate — this is the documented cause of "web_search missing under launchd" reports.
- **Rebuild notes:** A support dump must report the *effective* value, not the configured one, and must say where a credential lives (shell vs `.env` vs credential pool). A better version would add a stable machine-readable variant and a one-line copyable hash of the whole state.

---

## 7. `hermes debug` — log/report sharing

### hermes debug  `id: cli-d.debug`
- **Surface:** CLI
- **Where:** `hermes debug`. Root help: *"Debug tools — upload logs and system info for support"*. Description: *"Debug utilities for Hermes Agent. Use 'hermes debug share' to upload a debug report (system info + recent logs) to a paste service and get a shareable URL."* The parser uses `RawDescriptionHelpFormatter` and an epilog listing eight examples verbatim: `hermes debug share              Upload debug report (asks for confirmation)`, `hermes debug share --yes        Skip confirmation (for scripts/CI)`, `hermes debug share --lines 500  Include more log lines`, `hermes debug share --expire 30  Keep paste for 30 days`, `hermes debug share --local      Print report locally (no upload)`, `hermes debug share --no-redact  Disable upload-time secret redaction`, `hermes debug share --nous       Upload to Nous-internal storage (private)`, `hermes debug delete <url>       Delete a previously uploaded paste`.
- **What it does:** Group command for sharing and deleting debug reports; every invocation also opportunistically sweeps expired pastes.
- **How it works:** Parser `hermes_cli/subcommands/debug.py:13`; router `hermes_cli/debug.py:1018` `run_debug(args)`. Before dispatching it calls `_sweep_expired_pastes()` inside a bare `try/except` — this replaced an older design that forked one sleeping Python interpreter per scheduled deletion (each leaking ~20 MB until its 6-hour sleep ended).
- **Inputs / options:** `-h`, `--help`; sub-commands `share`, `delete`.
- **Outputs / side effects:** With no sub-command prints a help block: `Usage: hermes debug <command>`, blank, `Commands:`, `  share    Upload debug report to a paste service and print URL`, `  delete   Delete a previously uploaded paste`, blank, `Options (share):`, `  --lines N    Number of log lines to include (default: 200)`, `  --expire N   Paste expiry in days (default: 7)`, `  --local      Print report locally instead of uploading`, `  --nous       Upload to Nous-internal storage (private, staff-only,` / `               auto-deletes in 14 days) instead of a public paste`, `  --no-redact  Disable upload-time secret redaction (default: redact)`, blank, `Options (delete):`, `  <url> ...    One or more paste URLs to delete`.
- **Config / env:** `HERMES_HOME` (log directory, `pastes/pending.json`).
- **Rebuild notes:** Drive scheduled cleanup from a durable pending file swept by an existing ticker, never from sleeping subprocesses.

### hermes debug share  `id: cli-d.debug-share`
- **Surface:** CLI
- **Where:** `hermes debug share [--lines LINES] [--expire EXPIRE] [--local] [-y|--yes] [--no-redact] [--nous]`. Help: *"Upload debug report to a paste service and print a shareable URL"*.
- **What it does:** Builds a report (the `hermes dump` output plus tails of five log files), plus full copies of four logs, force-redacts secrets, asks for explicit consent, uploads each piece to a paste service, prints the URLs and schedules auto-deletion after six hours.
- **How it works:** `hermes_cli/debug.py:846` `run_debug_share(args)` → `build_debug_share()` (line 754) → `collect_share_bundle()` (line 645) → `collect_debug_report()` (line 583) + `_capture_default_log_snapshots()` (line 532).
  - **Logs captured:** `agent` (tail = `--lines`), `errors`, `gateway`, `gui`, `desktop` (each tail = `min(lines, 100)`). Path resolution `_resolve_log_path` (line 404) prefers `<home>/logs/<LOG_FILES[name]>` and falls back to the `.1` rotation, returning the first non-empty candidate. A missing file renders `(file not found)` except for the client-side `desktop` log, which renders `(not on this host: written by Hermes Desktop on the machine running the app, not by this backend. If the desktop connects to a remote/docker/SSH backend, collect it on that client machine — expected at <path>)`. An existing-but-empty primary renders `(file empty)`; a read error renders `(error reading: <exc>)`. Full-log capture is capped at `_MAX_LOG_BYTES = 512_000` and prefixed with `[... truncated — showing last ~500KB ...]` when it hits the cap.
  - **Redaction:** on by default. `_redact_log_text` (line 425) runs `agent.redact.redact_sensitive_text(text, force=True)` — `force=True` so it fires regardless of the operator's `security.redact_secrets` setting — and then replaces every email address matched by `_EMAIL_ADDRESS_RE` with `[REDACTED_EMAIL]`. Only the in-memory copy is redacted; the on-disk log is never modified. Every redacted artefact is prefixed with `_REDACTION_BANNER`: `[hermes debug share: log content redacted at upload time. run with --no-redact to disable]`.
  - **Bundle shape:** `{"report": …, "agent.log": …, "gateway.log": …, "gui.log": …, "desktop.log": …}` — absent/empty logs are omitted. Each full log is prefixed with the dump header and a `--- full <name> ---` divider so every file is self-contained.
  - **Report body:** the dump text, then `--- agent.log (last <N> lines) ---`, `--- errors.log (last <M> lines) ---`, `--- gateway.log (last <M> lines) ---`, `--- gui.log (last <M> lines) ---`, `--- desktop.log (last <M> lines) ---`.
  - **Upload:** `upload_to_pastebin` (line 329) tries `POST https://paste.rs/` (plain text body, 30s timeout, `User-Agent: hermes-agent/debug-share`) and falls back to `POST https://dpaste.com/api/` (multipart with fields `content`, `syntax=text`, `expiry_days`, boundary `----HermesDebugBoundary9f3c`). Total failure raises `RuntimeError("Failed to upload to any paste service:\n  <errors>")`. The `Report` upload is required; the four full-log uploads are best-effort and their errors are collected into `failures`.
  - **Auto-delete:** every resulting URL is recorded in `~/.hermes/pastes/pending.json` as `{"url": …, "expire_at": <now + 21600>}` (`_AUTO_DELETE_SECONDS = 21600`, six hours), written atomically via a `.json.tmp` + `atomic_replace`. Only paste.rs URLs are recorded (dpaste.com expires on its own and has no delete API). The gateway's cron ticker (`gateway/run.py::_start_cron_ticker`) sweeps hourly; `hermes debug` sweeps opportunistically. A failed delete is retried for up to 24 hours past expiry, then dropped.
- **Inputs / options:**
  - `--lines LINES` (int, default 200) — *"Number of log lines to include per log file (default: 200)"*.
  - `--expire EXPIRE` (int, default 7) — *"Paste expiry in days (default: 7)"* (only honoured by the dpaste.com fallback).
  - `--local` — *"Print the report locally instead of uploading"*.
  - `-y`, `--yes` — *"Skip the confirmation prompt and upload immediately. Required in non-interactive contexts (scripts/CI); without it, and with no TTY on stdin, the command refuses rather than upload silently."*
  - `--no-redact` — *"Disable upload-time secret redaction (default: redact). Logs are normally run through agent.redact.redact_sensitive_text with force=True before upload so credentials are not leaked into the public paste service."*
  - `--nous` — *"Upload the debug bundle to Nous-internal storage (AWS S3) instead of a public paste service. The bundle is private — viewable only by Nous staff (and allowlisted Discord mods) via a Google-login-gated viewer — and auto-deletes after 14 days. Still force-redacts secrets unless --no-redact is also passed."*
  - `-h`, `--help`.
- **Consent flow (`_confirm_upload`, line 814):** the privacy notice `_PRIVACY_NOTICE` is printed first, verbatim: `⚠️  This will upload system info + logs to a PUBLIC paste service.` / (blank) / `Cryptographic secrets (API keys, tokens, passwords) are redacted before` / `upload, but the following personal data is NOT redacted and will be public:` / `  • Your display name and persistent platform user ID` / `  • Verbatim content of your recent messages (prompts, responses, tool output)` / `  • Local filesystem paths` / `  • Any other PII present in the logs` / (blank) / `The resulting URL is public to anyone who has the link. Pastes auto-delete` / `after 6 hours, but may be archived by third parties in the meantime.` / (blank) / `Use --local to view the report without uploading.` Then: with `--yes`, proceed; with no TTY on stdin, print to stderr `ERROR: Non-interactive mode requires --yes to confirm upload.` / `       This prevents accidental exposure of personal data.` / `       Use --local to view the report without uploading.` and `sys.exit(1)`; otherwise prompt `Upload debug report? [y/N] ` and abort with `Aborted.` on anything but `y`/`yes` (EOF/^C count as abort).
- **Outputs / side effects:** Network uploads; writes `~/.hermes/pastes/pending.json`. Console: `Collecting debug report...`, `Uploading...`, then `Debug report uploaded:` and one aligned `  <label>  <url>` per artefact (`Report`, `agent.log`, `gateway.log`, `gui.log`, `desktop.log`), optionally `  (failed to upload: <label: error>, …)`, then `⏱  Pastes will auto-delete in 6 hours.`, `To delete now:  hermes debug delete <url>`, and `Share these links with the Hermes team for support.` On upload failure: `Upload failed: <exc>` on stderr, `Run `hermes debug share --local` to print the report instead.`, exit 1.
- **`--local` path:** never touches the network. Prints `Collecting debug report...`, the report, and then for each present full log a block of `============…` (60 `=`), the title (`FULL agent.log`, `FULL gateway.log`, `FULL gui.log`, `FULL desktop.log`), another 60-`=` rule, and the body.
- **`--nous` path (`_run_debug_share_nous`, line 930):** prints `_NOUS_PRIVACY_NOTICE` verbatim (`⚠️  --nous: This uploads your debug bundle to Nous-INTERNAL storage (AWS S3),` / `    NOT a public paste service. The following is included:` / `  • System info (OS, Python/Hermes version, provider, which API keys are` / `    configured — NOT the actual keys)` / `  • Full agent.log, gateway.log, and desktop.log (up to 512 KB each — likely` / `    contains conversation content, tool outputs, and file paths)` / (blank) / `  • The bundle is viewable only by Nous staff (and allowlisted Discord mods)` / `    via a Google-login-gated viewer.` / `  • It is NOT a public paste — there is no public URL to the contents.` / `  • It auto-deletes after 14 days.`), asks the same consent question, warns `⚠️  --no-redact is set: secrets in your logs will NOT be redacted before upload.` when applicable, gzips the bundle into the envelope `{"format": "hermes-debug-share/1", "redacted": <bool>, "created": <ISO-8601 UTC>, "files": {…}}` (`build_nous_bundle`, line 714), and uploads it via `hermes_cli.diagnostics_upload.share_to_nous(blob)` (signed URL from NAS → S3). Prints `Uploading to Nous diagnostics storage...`, then `Debug bundle uploaded to Nous (private):` and `  View URL  <url>` (or `  (no view URL returned; upload id: <id>)`), `⏱  Auto-deletes at <expiresAt> (14-day retention).` or `⏱  Auto-deletes after 14 days.`, `Share this private link with the Nous team — only Nous staff (via Google login) can open it.`, and a three-line follow-up list: `  GitHub Issues        https://github.com/NousResearch/hermes-agent/issues`, `  Nous Portal Support  https://portal.nousresearch.com/help`, `  Discord              https://discord.gg/NousResearch`. On failure: `Nous upload failed: <exc>` plus the fallback advice and exit 1.
- **Config / env:** `security.redact_secrets` is deliberately bypassed (`force=True`). `HERMES_HOME` for logs and the pending file.
- **Edge cases / guards:** Redaction is described as the safety boundary: the Nous path is built from the *same* force-redacted snapshots as the public path so it can never see raw logs. The gateway-side variant of this feature shows a shorter notice, `_GATEWAY_PRIVACY_NOTICE`, which adds that *"Full logs are NOT included from the gateway — use `hermes debug share` from the CLI for full log uploads."*
- **Rebuild notes:** One collector, one redactor, two destinations; require an explicit `--yes` when there is no TTY; record deletions in a file swept by an existing ticker. A better version would encrypt the bundle to a support public key and let the user diff exactly what will be uploaded before consenting.

### hermes debug delete  `id: cli-d.debug-delete`
- **Surface:** CLI
- **Where:** `hermes debug delete [urls ...]`. Help: *"Delete a paste uploaded by 'hermes debug share'"*. Positional help: *"One or more paste URLs to delete (e.g. https://paste.rs/abc123)"*.
- **What it does:** Issues an unauthenticated HTTP DELETE against each given paste.rs URL.
- **How it works:** `hermes_cli/debug.py:997` `run_debug_delete(args)` loops the URLs calling `delete_paste(url)` (line 235), which extracts the id via `_extract_paste_id` (accepting only `https://paste.rs/` and `http://paste.rs/` prefixes, trailing slash stripped) and sends `DELETE https://paste.rs/<id>` with `User-Agent: hermes-agent/debug-share` and a 30s timeout, returning `True` for a 2xx.
- **Inputs / options:** zero or more positional `urls`; `-h`, `--help`.
- **Outputs / side effects:** Deletes remote pastes. Per URL prints `  ✓ Deleted: <url>`, `  ✗ Failed to delete: <url> (unexpected response)`, `  ✗ Cannot delete: only paste.rs URLs are supported.  Got: <url>` (the `ValueError` text), or `  ✗ Could not delete <url>: <exc>`. With no URLs prints `Usage: hermes debug delete <url> [<url> ...]` and `  Deletes paste.rs pastes uploaded by 'hermes debug share'.`
- **Edge cases / guards:** dpaste.com pastes cannot be deleted (no unauthenticated DELETE API) — they expire on their own. The pending-file sweep still runs on entry via `run_debug`.
- **Rebuild notes:** Only offer delete where the service actually supports it, and say so explicitly for the ones that do not.

---

## 8. `hermes backup` — archive the Hermes home

### hermes backup (full zip)  `id: cli-d.backup`
- **Surface:** CLI
- **Where:** `hermes backup [-o OUTPUT] [-q] [-l LABEL]`. Root help: *"Back up Hermes home directory to a zip file"*. Description: *"Create a zip archive of your entire Hermes configuration, skills, sessions, and data (excludes the hermes-agent codebase). Use --quick for a fast snapshot of just critical state files."*
- **What it does:** Walks `~/.hermes`, skipping regeneratable and unsafe directories, takes WAL-safe snapshots of every `*.db`, adds external memory-provider state, and writes a single deflate zip to `~/hermes-backup-<timestamp>.zip`.
- **How it works:** Parser `hermes_cli/subcommands/backup.py:12`; dispatcher `hermes_cli/main.py:5964` routes to `run_quick_backup` when `--quick` else `run_backup`. `run_backup` (`hermes_cli/backup.py:793`) acquires a cross-process lock on `<home>/.backup.lock` (`_backup_operation_lock`, line 183 — `msvcrt.locking` on Windows, `fcntl` elsewhere, 0.25s timeout) and delegates to `_run_backup_locked` (line 809).
  - **Output path**: `-o` is expanded and resolved; if it names an existing directory the file becomes `<dir>/hermes-backup-<YYYY-MM-DD-HHMMSS>.zip`; a missing `.zip` suffix is appended; the parent directory is created. Default: `~/hermes-backup-<YYYY-MM-DD-HHMMSS>.zip`.
  - **Scan**: `os.walk(hermes_root, followlinks=False)`, pruning `dirnames` in place.
  - **Archive**: `zipfile.ZipFile(..., "w", ZIP_DEFLATED, compresslevel=6)` written through `_atomic_output_path` (staged then published). Each `*.db` is first snapshotted with `_safe_copy_db` into a NamedTemporaryFile **in the output directory** (not `/tmp`, which may be a small tmpfs) and the snapshot is what gets zipped; a failed snapshot records `  <rel>: SQLite safe copy failed`.
  - **External state**: `_collect_memory_provider_external_paths()` asks the active memory provider for `backup_paths()` (e.g. `~/.honcho`, `~/.hindsight`); each file under `$HOME` is stored under the reserved arc prefix `_external/<path relative to $HOME>`. Anything outside `$HOME` is skipped and reported.
  - **Progress**: prints `  <i>/<total> files ...` every 500 files and logs structured lines `backup phase=scan|archive status=…`.
- **Inputs / options:**
  - `-o OUTPUT`, `--output OUTPUT` — *"Output path for the zip file (default: ~/hermes-backup-<timestamp>.zip)"*.
  - `-q`, `--quick` — *"Quick snapshot: only critical state files (config, state.db, .env, auth, cron)"* (see `cli-d.backup-quick`).
  - `-l LABEL`, `--label LABEL` — *"Label for the snapshot (only used with --quick)"*.
  - `-h`, `--help`.
- **Exclusions (verbatim sets):**
  - `_EXCLUDED_DIRS` (`backup.py:68`): `hermes-agent` (root level only, so `skills/*/hermes-agent/` survives), `__pycache__`, `.git`, `node_modules`, `backups`, `state-snapshots`, `checkpoints`, `browser-profiles`, `browser-profile`, `.venv`, `venv`, `site-packages`, `.cache`, `.tox`, `.nox`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`. `skills/.archive/` is deliberately **not** excluded (it holds restorable user skills).
  - `_EXCLUDED_SUFFIXES` (line 106): `.pyc`, `.pyo`, `.db-wal`, `.db-shm`, `.db-journal` (sidecars would pair a fresh snapshot with stale state and produce a torn restore).
  - `_EXCLUDED_NAMES` (line 120): `.backup.lock`, `gateway.pid`, `cron.pid`.
- **Outputs / side effects:** Writes the zip. Console: `Scanning <home> ...`, `Backing up <N> files ...`, progress lines, then a blank line and `Backup complete: <path>` (or `Backup incomplete: <path>` when any file errored), `  Files:       <N>`, `  Original:    <human size>`, `  Compressed:  <human size>`, `  Time:        <s>s`; optionally `  Included <n> memory-provider file(s) stored outside <home>.`, `  Skipped <n> memory-provider path(s) outside your home directory (not portable):` with up to 10 paths, `  Excluded directories:` with each `    <dir>/`, `  Warnings (<n> files skipped):` with up to 10 entries and `  ... and <k> more`; and on a clean run `Restore with: hermes import <filename>`.
- **Config / env:** `HERMES_HOME`; the active `memory.provider` decides the `_external/` contents.
- **Exit codes:** `1` when the Hermes home does not exist (`Error: Hermes home directory not found at <path>`) or the output path is unwritable (`Error: cannot write backup to <path>: <exc>`); `2` when another process holds the backup lock (`Error: <BackupInProgressError message>`); `0` otherwise. `No files to back up.` returns normally.
- **Edge cases / guards:** Live browser profiles are excluded because Chromium holds its SQLite files with exclusive locks and `sqlite3.Connection.backup()` retries `SQLITE_BUSY` forever — a full backup would hang mid-archive. `browser-profile` (singular) is excluded additionally because it holds copies of the user's Cookies / Login Data / Web Data. Dependency trees and caches are excluded because a single plugin venv under `HERMES_HOME` turns a backup into hundreds of thousands of entries (the "backup stuck for days / 426543 files" symptom).
- **Rebuild notes:** Snapshot SQLite via the engine's own backup API, never a file copy; stage the snapshot on the destination filesystem; keep one cross-process lock so quick and full backups cannot interleave. A better version would support incremental/deduplicated archives and an encrypted output.

### hermes backup --quick (state snapshot)  `id: cli-d.backup-quick`
- **Surface:** CLI
- **Where:** `hermes backup --quick [-l LABEL]` (`-q`). Also reachable as the `/snapshot` slash command and used automatically by `hermes update` as a pre-update safety net.
- **What it does:** Copies a fixed list of critical state files into a timestamped directory under `~/.hermes/state-snapshots/`, then prunes old snapshots.
- **How it works:** `hermes_cli/backup.py:2076` `run_quick_backup(args)` → `create_quick_snapshot(label=…)` (line 1486), which takes the same `_backup_operation_lock` and calls `_create_quick_snapshot_locked` (line 1503). SQLite files are copied WAL-safely via `_safe_copy_db`. Retention default `_QUICK_DEFAULT_KEEP = 20`; `_prune_quick_snapshots` removes the excess. An optional `max_file_size` (used only by the pre-update path) skips oversized files so a multi-GB `state.db` cannot stall `hermes update`.
- **Inputs / options:** `-l LABEL` / `--label LABEL` (used only here); `-q` / `--quick`.
- **Captured file list (`_QUICK_STATE_FILES`, `backup.py:1446`, relative to `HERMES_HOME`; missing entries are silently skipped, directories are captured recursively):** `state.db`, `config.yaml`, `.env`, `auth.json`, `cron/jobs.json`, `cron/executions.db`, `gateway_state.json`, `channel_directory.json`, `channel_aliases.json`, `processes.json`, `gateway/discord_message_recovery.db`, `projects.db`, `response_store.db`, `memory_store.db`, `verification_evidence.db`, `kanban.db`, `kanban/boards` (each `<slug>/kanban.db` plus board metadata; `workspaces/` and `attachments/` are skipped as regenerable), `pairing` (legacy location), `platforms/pairing` (new location), `feishu_comment_pairing.json`.
- **Outputs / side effects:** Creates `~/.hermes/state-snapshots/<snapshot id>/`. Console: `State snapshot created: <id>`, `  <n> snapshot(s) stored in <home>/state-snapshots/`, `  Restore with: /snapshot restore <id>`; or `No state files found to snapshot.`
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `state-snapshots` is itself in `_EXCLUDED_DIRS`, so a full backup never re-ships one copy of `state.db` per snapshot.
- **Rebuild notes:** Keep the "critical state" list explicit and versioned; it is what makes a fast pre-update net possible. A better version would hard-link unchanged files between snapshots.

### hermes import  `id: cli-d.import`
- **Surface:** CLI
- **Where:** `hermes import <zipfile> [--force|-f]`. Root help: *"Restore a Hermes backup from a zip file"*. Description: *"Extract a previously created Hermes backup into your Hermes home directory, restoring configuration, skills, sessions, and data"*. Positional help: *"Path to the backup zip file"*; flag help: *"Overwrite existing files without confirmation"*.
- **What it does:** Validates that a zip looks like a Hermes backup, extracts every member atomically into `~/.hermes` (and `_external/` members back under `$HOME`), preserves this machine's volatile runtime state, restores profile alias wrappers, and offers to start the gateway.
- **How it works:** `hermes_cli/backup.py:1196` `run_import(args)`.
  - **Validation** (`_validate_backup_zip`, line 1021): rejects an empty archive and any archive containing none of the marker basenames `config.yaml`, `.env`, `state.db`.
  - **Prefix stripping** (`_detect_prefix`, line 1048): when every entry shares one leading directory and that directory is `.hermes` or `hermes`, it is stripped.
  - **Confirmation**: when `config.yaml` or `.env` already exists and `--force` was not given, prints `Warning: Target directory already has Hermes configuration.` / `Importing will overwrite existing files with backup contents.` and asks `Continue? [y/N] `; anything but `y`/`yes` prints `Aborted.` and returns; EOF/^C prints `Aborted.` and exits 1.
  - **Atomic member extraction** (`_extract_member_atomically`, line 1093): stages into `tempfile.mkstemp(dir=target.parent, prefix=".<name[:80]>.", suffix=".partial")`, streams the member with `shutil.copyfileobj` (so a multi-GB `state.db` is never held in memory), `flush()` + `os.fsync()`, applies the preserved mode with `fchmod` *before* the replace, publishes with `utils.atomic_replace` (which resolves a symlinked target so a dotfiles-linked `config.yaml` keeps its link, and falls back to copy/fsync/unlink on `EXDEV`/`EBUSY`), then restores owner and mode. **setuid/setgid are deliberately stripped** (`mode &= ~(S_ISUID | S_ISGID)`) because the replacement bytes come from an untrusted archive; the sticky bit is kept. `_default_new_file_mode()` (line 1072) probes the umask once so newly created files are not left at mkstemp's 0600.
  - **Runtime-state preservation** (`_IMPORT_SKIP_NAMES`, `backup.py:151`, matched by basename so named profiles are covered too): `gateway_state.json`, `gateway.pid`, `cron.pid`, `gateway.lock`, `processes.json` are never overwritten — restoring them onto a different host breaks the container-boot reconciler and disconnects hosted instances from the Nous portal.
  - **Secret tightening** (`_SECRET_FILE_NAMES`, line 160): `.env`, `auth.json`, `state.db` are chmod'd `0600` after restore; under `_external/`, any `.json`/`.env`/`.conf` file gets the same treatment.
  - **Path-traversal guards**: every target's resolved path must stay under `hermes_root` (or under `$HOME` for `_external/`), else `  <member>: path traversal blocked`.
  - **Post-import**: recreates profile wrapper scripts for every `profiles/<name>/` that has a `config.yaml` or `.env` (via `hermes_cli.profiles.create_wrapper_script`, skipping alias collisions), then tries `ensure_gateway_service(context="import")` when no gateway is running.
- **Inputs / options:** positional `zipfile`; `--force` / `-f`; `-h`, `--help`.
- **Outputs / side effects:** Writes files into `~/.hermes` and possibly under `$HOME`; creates alias wrappers; may install/start the gateway service. Console: `Backup contains <N> files`, `Target: <home>`, optionally `Detected archive prefix: '<p>' (will be stripped)`, `Importing <N> files ...`, progress `  <n>/<N> files ...` every 500, then `Import complete: <n> files restored in <s>s`, `  Target: <home>`, optionally `  Restored <n> memory-provider file(s) to their original location(s) outside <home>.`, `  Warnings (<n> files skipped):` (up to 10 + `  ... and <k> more`), `  Preserved <n> runtime state file(s) (kept this machine's, not the backup's):` (up to 10 + more), `  Profile aliases restored: <names>` / `  Profile aliases skipped:  <names>` / `  Skipped alias '<name>': <collision reason>`, `  Note: <wrapper dir> is not in your PATH.` + `  Add to your shell config (~/.bashrc or ~/.zshrc):` + `    export PATH="$HOME/.local/bin:$PATH"`, `Note: The hermes-agent codebase was not included in the backup.` + `  If this is a fresh install, run: hermes update`, `To re-enable gateway services for profiles:` + `  hermes -p <name> gateway install` per profile, a gateway-start fallback `Start the gateway to activate cron jobs and messaging:` + `  hermes gateway install`, and finally `Done. Your Hermes configuration has been restored.`
- **Config / env:** `HERMES_HOME`, `$HOME`, umask.
- **Exit codes:** `1` for a missing file (`Error: File not found: <path>`), a non-zip (`Error: Not a valid zip file: <path>`), a failed validation (`Error: zip archive is empty` / `Error: zip does not appear to be a Hermes backup (no config.yaml, .env, or state databases found)`), or an aborted confirmation via EOF/^C.
- **Edge cases / guards:** Import is the disaster-recovery path, so no file is ever truncated before its replacement bytes exist. Older archives predate the backup-side exclusions, so runtime-state filtering is applied on import too rather than trusting the archive. `sudo hermes import` would otherwise re-own every restored file to root — the owner is explicitly carried across the replace.
- **Rebuild notes:** Extract through a temp file in the target's own directory + rename; strip setuid/setgid from archive-sourced content; preserve host-local runtime state. A better version would verify a manifest checksum per member and support a dry-run diff before writing.

---

## 9. `hermes checkpoints` — filesystem checkpoint store

### hermes checkpoints  `id: cli-d.checkpoints`
- **Surface:** CLI
- **Where:** `hermes checkpoints [COMMAND]`. Description: *"Manage the filesystem checkpoint store — the shadow git repo hermes uses to snapshot working directories before write_file/patch/terminal calls. Lets you see how much space checkpoints occupy, force a prune, or wipe the base."*
- **What it does:** Inspects and manages `~/.hermes/checkpoints/` — the shadow git store that backs `/rollback`. A bare `hermes checkpoints` runs `status`.
- **How it works:** `hermes_cli/checkpoints.py:232` `register_cli(parser)` sets `parser.set_defaults(func=cmd_status)` then adds five sub-parsers. All data comes from `tools.checkpoint_manager`: `CHECKPOINT_BASE = get_hermes_home() / "checkpoints"` (line 72), a single shared store dir `store/` (`_STORE_DIRNAME`), and pre-v2 archives under `legacy-<timestamp>/` (`_LEGACY_PREFIX`). `store_status()` (`tools/checkpoint_manager.py:2121`) returns `{base, store_size_bytes, legacy_size_bytes, total_size_bytes, project_count, projects[], pre_v2_projects[], legacy_archives[]}`; each project carries `hash`, `workdir`, `exists`, `created_at`, `last_touch` and a `commits` count obtained with `git rev-list --count <ref>` inside the shadow store.
- **Inputs / options:** `-h`, `--help`; sub-commands `status`, `list`, `prune`, `clear`, `clear-legacy`.
- **Edge cases / guards:** None of these require the agent to be running; they are safe to call at any time.
- **Rebuild notes:** One shared shadow git repo with a per-project ref keyed by a workdir hash is what makes cross-project rollback cheap; expose size and orphan state so users can reason about disk.

### hermes checkpoints status  `id: cli-d.checkpoints-status`
- **Surface:** CLI
- **Where:** `hermes checkpoints status [--limit LIMIT]` (also the default for a bare `hermes checkpoints`). Help: *"Show total size, project count, and per-project breakdown"*.
- **What it does:** Prints the checkpoint base path, its total/`store/`/`legacy-*` sizes, the project count, a per-project table and any legacy archives.
- **How it works:** `hermes_cli/checkpoints.py:56` `cmd_status(args)`. Projects are sorted by `last_touch` descending and truncated to `--limit`.
- **Inputs / options:** `--limit LIMIT` (int, default 20) — *"Max projects to list (default 20)"*; `-h`, `--help`.
- **Outputs / side effects:** Read-only. Lines: `Checkpoint base: <path>`, `Total size:      <human>`, `  store/         <human>`, `  legacy-*       <human>`, `Projects:        <N>`; then a table header `  WORKDIR<padded to 60>  COMMITS  LAST TOUCH  STATE` and one row per project `  <workdir, left-truncated to 60 with a leading …>  <commits>  <age>  <live|orphan>`. Age formatting (`_fmt_age`, line 40): `now` for negative, `<n>s ago` under 60s, `<n>m ago` under an hour, `<n>h ago` under a day, `<n>d ago` beyond, `—` when unparseable. Then, when present, `Legacy archives (<n>):`, one `  <name padded to 40>  <size right-aligned to 10>` per archive sorted by mtime descending, and `Clear with: hermes checkpoints clear-legacy`.
- **Exit codes:** always `0`.
- **Rebuild notes:** Show `live` vs `orphan` per project — that single column is what tells a user whether a prune is safe.

### hermes checkpoints list  `id: cli-d.checkpoints-list`
- **Surface:** CLI
- **Where:** `hermes checkpoints list [--limit LIMIT]`. Help: *"Alias for 'status'"*.
- **What it does:** Identical to `status`.
- **How it works:** `hermes_cli/checkpoints.py:96` `cmd_list(args)` simply `return cmd_status(args)`.
- **Inputs / options:** `--limit LIMIT` (int, default 20 — declared without help text on this sub-parser); `-h`, `--help`.
- **Outputs / side effects:** identical to `cli-d.checkpoints-status`.
- **Rebuild notes:** n/a — a deliberate alias.

### hermes checkpoints prune  `id: cli-d.checkpoints-prune`
- **Surface:** CLI
- **Where:** `hermes checkpoints prune [--retention-days N] [--max-size-mb N] [--keep-orphans] [-f|--force]`. Help: *"Delete orphan/stale checkpoints and GC the store"*.
- **What it does:** Forces a checkpoint sweep (ignoring the 24-hour auto-prune marker): deletes projects whose working directory no longer exists, drops projects untouched for longer than the retention window, then trims oldest commits per project until the store fits the size budget.
- **How it works:** `hermes_cli/checkpoints.py:101` `cmd_prune(args)`. When orphan deletion is enabled and `--force` was not passed, it first previews the orphans (from both `projects` and `pre_v2_projects`), asks for confirmation, and — critically — binds the subsequent deletion to an `orphan_allowlist` built from exactly the previewed identities (`hash` for v2 projects, `path` for pre-v2 shadow repos). An empty preview binds to an empty allowlist, so a project that becomes orphaned *while the user is answering the prompt* can never be swept in the same run. With `--force`, `orphan_allowlist` is `None` (no restriction). Then `tools.checkpoint_manager.prune_checkpoints(retention_days=…, delete_orphans=…, max_total_size_mb=…, orphan_allowlist=…)`.
- **Inputs / options:**
  - `--retention-days RETENTION_DAYS` (int, default 7) — *"Drop projects whose last_touch is older than N days (default 7)"*.
  - `--max-size-mb MAX_SIZE_MB` (int, default 500) — *"After orphan/stale prune, drop oldest commits per project until total size <= this (default 500)"*.
  - `--keep-orphans` — *"Skip deleting projects whose workdir no longer exists"*.
  - `-f`, `--force` — *"Skip the orphan-deletion confirmation prompt"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Deletes refs/objects from the shadow store and legacy archives. Confirmation block: `This will permanently delete <n> orphan checkpoint project(s) whose workdir is not currently reachable:`, blank, per orphan `  <workdir>  (<n> commit(s))` or `  <workdir>  (pre-v2 shadow repo)`, blank, `A workdir can be unreachable because the project was deleted,`, `or because an external volume / network share / VPN is down.`, `Pass --keep-orphans to prune stale entries only.`, then `Delete these orphan projects? [y/N]: `. Run output: `Pruning checkpoint store…`, `  retention_days:    <n>`, `  delete_orphans:    <bool>`, `  max_total_size_mb: <n>`, blank, then `Scanned:         <n>`, `Deleted orphan:  <n>`, `Deleted stale:   <n>`, `Errors:          <n>`, `Bytes reclaimed: <human>`.
- **Exit codes:** `1` when the confirmation is declined (prints `Aborted.`), else `0`.
- **Edge cases / guards:** An unreachable workdir may simply mean an unmounted volume or a VPN that is down — the prompt says so explicitly, and `--keep-orphans` exists for exactly that case. Legacy `legacy-*` archives older than the retention window are swept by the same policy.
- **Rebuild notes:** Bind a destructive sweep to the exact set the user was shown — re-scanning after the prompt is a real TOCTOU bug in this shape of command.

### hermes checkpoints clear  `id: cli-d.checkpoints-clear`
- **Surface:** CLI
- **Where:** `hermes checkpoints clear [-f|--force]`. Help: *"Delete the entire checkpoint base (all /rollback history)"*.
- **What it does:** Deletes the whole `~/.hermes/checkpoints/` tree, destroying every project's rollback history.
- **How it works:** `hermes_cli/checkpoints.py:180` `cmd_clear(args)`. Reads `store_status()` for the preview, then calls `tools.checkpoint_manager.clear_all()`.
- **Inputs / options:** `-f`, `--force` — *"Skip confirmation prompt"*; `-h`, `--help`.
- **Outputs / side effects:** Removes the checkpoint base. Console: `Nothing to clear — checkpoint base does not exist.` when the base is absent and empty; otherwise `This will delete the ENTIRE checkpoint base at <path>`, `  size:        <human>`, `  projects:    <n>`, `  legacy dirs: <n>`, blank, `All /rollback history for every working directory will be lost.`, then `Proceed? [y/N]: `, and finally `Cleared. Reclaimed <human>.` or `Could not clear checkpoint base (see logs).`
- **Exit codes:** `0` on success or when there is nothing to clear; `1` when the confirmation is declined (`Aborted.`); `2` when the delete failed.
- **Rebuild notes:** State the blast radius ("all /rollback history for every working directory") in the prompt, not just the byte count.

### hermes checkpoints clear-legacy  `id: cli-d.checkpoints-clear-legacy`
- **Surface:** CLI
- **Where:** `hermes checkpoints clear-legacy [-f|--force]`. Help: *"Delete only the legacy-<ts>/ archives from v1 migration"*.
- **What it does:** Deletes only the `legacy-<timestamp>/` directories that hold pre-v2 per-project shadow repos moved aside during the single-store migration, leaving the live `store/` intact.
- **How it works:** `hermes_cli/checkpoints.py:206` `cmd_clear_legacy(args)` → `tools.checkpoint_manager.clear_legacy()`.
- **Inputs / options:** `-f`, `--force` — *"Skip confirmation prompt"*; `-h`, `--help`.
- **Outputs / side effects:** Deletes the archive directories. Console: `No legacy archives to clear.` when there are none; otherwise `Found <n> legacy archive(s), total <human>:`, one `  <name padded to 40>  <size right-aligned to 10>` per archive, blank, `Legacy archives hold pre-v2 per-project shadow repos, moved aside`, `during the single-store migration. Delete when you're confident`, `you don't need the old /rollback history.`, then `Delete all legacy archives? [y/N]: `, and `Deleted <n> archive(s), reclaimed <human>.`
- **Exit codes:** `0` on success or when nothing to clear; `1` when declined (`Aborted.`).
- **Note:** This sub-command is listed in the group's `--help` (`clear-legacy  Delete only the legacy-<ts>/ archives from v1 migration`) but has no dedicated `cli_help/checkpoints__clear-legacy.txt` dump in the evidence folder — its flags are `-f/--force` only.
- **Rebuild notes:** Separate "delete the migration leftovers" from "delete everything"; users reach for the former far more often.

---

## 10. `hermes import-agent` — import another coding agent's setup

### hermes import-agent  `id: cli-d.import-agent`
- **Surface:** CLI
- **Where:** `hermes import-agent [{claude-code,codex}] [--source SOURCE] [--dry-run] [--overwrite] [--yes|-y]`. Root help: *"Import a Claude Code or Codex CLI setup into Hermes"*. Description: *"One-command import of another coding agent's setup into Hermes. Maps CLAUDE.md/AGENTS.md instructions, permission allowlists, MCP servers, skills, and memories into their Hermes equivalents. Always shows a preview before making changes. API keys and credentials are never imported — run 'hermes setup' for those."*
- **What it does:** Reads `~/.claude` or `~/.codex`, maps its instruction files, permission rules, MCP servers, skills and memories into the Hermes equivalents, shows a per-item preview, and only then (after confirmation) applies the changes. Credentials are never copied.
- **How it works:** Parser `hermes_cli/subcommands/import_agent.py:13`; entry point `hermes_cli/agent_import.py:844` `import_agent_command(args)`.
  - **Detection**: `detect_agents()` returns the supported agents whose default directory exists (`_AGENT_DEFAULT_DIRS = {"claude-code": ".claude", "codex": ".codex"}`). No agent argument and none detected → `No supported agent setup found (~/.claude or ~/.codex).` + `Specify one explicitly: hermes import-agent claude-code --source /path`. More than one detected with no `--source` → `Multiple agent setups detected: <list>` + `Pick one: hermes import-agent claude-code   or   hermes import-agent codex`.
  - **Two-phase run**: an `AgentImporter(execute=False)` pass builds the full plan without touching disk, the report is printed, and only then (unless `--dry-run`) does a second `AgentImporter(execute=True)` pass apply it. `config.yaml` is created from defaults first if it does not exist.
  - **Item statuses**: every mapped artefact is recorded as `imported`, `skipped`, `conflict` or `error` with a human-readable reason, and the report groups them.
- **Inputs / options:**
  - positional `agent` — `claude-code` or `codex` — *"Which agent to import from (default: auto-detect ~/.claude or ~/.codex)"*.
  - `--source SOURCE` — *"Path to the agent's config directory (default: ~/.claude or ~/.codex)"*.
  - `--dry-run` — *"Preview only — stop after showing what would be imported"*.
  - `--overwrite` — *"Overwrite existing Hermes items on name conflicts (default: skip)"*.
  - `--yes`, `-y` — *"Skip confirmation prompts"*.
  - `-h`, `--help`.
- **Outputs / side effects:** Writes to `~/.hermes/memories/MEMORY.md` (after taking a `<name>.bak.<unix ts>` backup), `~/.hermes/config.yaml` (`command_allowlist`, `approvals.deny`, `mcp_servers`) and `~/.hermes/skills/<category>/<name>/`. Console: a magenta banner box `┌───…┐` / `│          ⚕ Hermes — Import From Another Agent          │` / `└───…┘`; an `Import Settings` header with `Agent:       <a>`, `Source:      <dir>`, `Target:      <hermes home>`, `Overwrite:   yes|no (skip conflicts)`, `Secrets:     never imported — run 'hermes setup' for credentials`; then either `Nothing to import from <agent>.` or `Import Preview — <n> item(s) would be imported` + `No changes have been made yet. Review the list below:` and the report. Report sections (`print_import_report`, line 969): header `Dry Run Results` + `No files were modified. This is a preview of what would happen.` or `Import Results`; then the four groups in order — `  ✓ Would import:` / `  ✓ Imported:` (green), `  ⚠ Conflicts (skipped — use --overwrite to force):` (yellow), `  ─ Skipped:` (dim), `  ✗ Errors:` (red) — each with rows `      <kind padded to 22> → <destination with $HOME collapsed to ~>` for imports and `      <kind padded to 22>  <reason>` otherwise; then, when applicable, `  ⚷ Secrets stripped (never imported):` with one `      <dotted config path>` per stripped key and `Re-add credentials deliberately via 'hermes setup' or ~/.hermes/.env.`; and finally `Summary: <n> would import|imported, <n> conflict(s), <n> skipped, <n> error(s)`. On success: `Import complete.` + `API keys and credentials were NOT imported — run 'hermes setup' to configure providers, or add them to ~/.hermes/.env.`
- **Config / env:** writes `command_allowlist`, `approvals.deny`, `mcp_servers` in `~/.hermes/config.yaml`. `HERMES_HOME` decides the target.
- **Edge cases / guards:** Files named `.credentials.json`, `auth.json`, `credentials.json` inside the source tree are never read (`_CREDENTIAL_FILENAMES`). An env-var or header name matching `_SECRET_KEY_RE` — `(^|_)(API[_-]?KEY|APIKEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH|PRIVATE[_-]?KEY|ACCESS[_-]?KEY)(_|$)` or anything ending in `KEY` — is stripped, as is any header whose name contains `authorization`. In a non-interactive session without `--yes` the command stops after the preview: `Non-interactive session — preview only.` + `To execute, re-run with: hermes import-agent <agent> --yes`. Declining the prompt prints `Import cancelled.`. If `config.yaml` exists but cannot be parsed, the affected item is recorded as an `error` and the file is left untouched — even in dry-run, so the preview reports the refusal rather than promising an import that would destroy the config.
- **Rebuild notes:** Always plan then apply, with the identical code path for both; refuse to merge into a config you cannot read; strip secrets by name pattern and *report* what was stripped. A better version would diff the resulting config and let the user deselect individual items.

### `hermes import-agent claude-code` — mappings  `id: cli-d.import-agent-claude-code`
- **Surface:** CLI
- **Where:** `hermes import-agent claude-code [--source ~/.claude]`.
- **What it does:** Maps a Claude Code setup into Hermes: `CLAUDE.md` → memories, `permissions.allow` → `command_allowlist`, `permissions.deny` → `approvals.deny`, `mcpServers` → `mcp_servers`, `skills/` → Hermes skills. Claude slash commands are explicitly not mapped.
- **How it works:** `hermes_cli/agent_import.py:476` `_run_claude_code()`, in this order:
  1. **settings.json** (`_load_claude_settings`, line 501) — missing → `skipped` with `No settings.json found`; unparseable → `error` `Could not parse settings.json: <exc>`; non-object → `error` `settings.json is not a JSON object`.
  2. **`CLAUDE.md` → `memories/MEMORY.md`** (kind `claude-md`). `extract_markdown_entries` (line 168) walks the markdown: fenced code blocks are skipped entirely, table rows (`|…|`) are skipped, headings become a `>`-joined context prefix (filtering out headings that name `MEMORY.md`/`USER.md`/`SOUL.md`/`AGENTS.md`/`TOOLS.md`/`IDENTITY.md`/`CLAUDE.md`), each bullet (`-`, `*`, `1.`) becomes one entry prefixed `"<context>: "`, and paragraph runs are collapsed to a single entry. Entries are deduped case- and whitespace-insensitively. Merging (`merge_entries`, line 294) skips duplicates against the existing store, enforces `MEMORY_CHAR_LIMIT = 20_000` characters (overflow entries counted, not written), and reports `existing_entries`, `added_entries`, `duplicate_entries`, `overflowed_entries`. The destination is parsed with `parse_existing_memory_entries` (line 253), which splits **only** on `ENTRY_DELIMITER = "\n§\n"` — deliberately never re-running the markdown extractor over the user's own store, because that would drop code blocks and tables permanently. A `<name>.bak.<unix ts>` backup is taken first, and a failed backup aborts the rewrite with an `error`.
  3. **`settings.json permissions.allow` → `config.yaml command_allowlist`** (kind `command-allowlist`). Each rule goes through `claude_rule_to_command_pattern` (line 332): `Bash(npm run build)` → `npm run build`; `Bash(npm run test:*)` → `npm run test*` (Claude's `:*` prefix form); `Bash(git diff *)` → `git diff *`; a bare `Bash` → `None`; non-Bash rules (`Read(...)`, `WebFetch(...)`, …) → `None`. Unmapped rules are reported as `unmapped_rules`. Patterns are deduped and sorted, merged with the existing list, and only the additions are reported.
  4. **`settings.json permissions.deny` → `config.yaml approvals.deny`** (kind `command-denylist`). Same conversion; no `unmapped_rules` detail.
  5. **MCP servers** (kind `mcp-servers`) from `~/.claude.json` (note: **next to** `~/.claude/`, not inside it) merged with `settings.json`'s `mcpServers` (the `.claude.json` entry wins). Each server is rewritten into the Hermes shape: `command` (+ `args`, sanitized `env`, `cwd`) and/or `url` (+ filtered `headers`). A server that is not a mapping → `skipped` `Server entry is not a mapping`; one with neither `command` nor `url` → `skipped` `Server has neither a command nor a url`; a name that already exists without `--overwrite` → `conflict` `MCP server already exists in Hermes config`.
  6. **`skills/<name>/SKILL.md` → `~/.hermes/skills/claude-code-imports/<name>/`** (`_SKILL_CATEGORY["claude-code"]`). Only directories containing a `SKILL.md` are considered; the whole directory is `shutil.copytree`'d (after `rmtree` when `--overwrite` and the destination exists). Existing destination without `--overwrite` → `conflict` `Destination skill already exists`. No skills dir → `skipped` `No skills directory found`; a dir with no `SKILL.md` → `skipped` `No skills with SKILL.md found`.
  7. **Slash commands**: when `<source>/commands/` exists and holds any `*.md`, one row is recorded — `skipped`, reason *"Claude slash commands have no direct Hermes equivalent — consider converting them into skills"*.
- **Inputs / options:** as `cli-d.import-agent`.
- **Outputs / side effects:** as `cli-d.import-agent`.
- **Rebuild notes:** Convert permission rules to globs with an explicit, documented rule table, and report the ones you could not map instead of dropping them silently.

### `hermes import-agent codex` — mappings  `id: cli-d.import-agent-codex`
- **Surface:** CLI
- **Where:** `hermes import-agent codex [--source ~/.codex]`.
- **What it does:** Maps a Codex CLI setup into Hermes: `AGENTS.md` → memories, `config.toml`'s `[mcp_servers.*]` → `mcp_servers`, `memories/*.md` → memories, `skills/` → Hermes skills. Codex has no permission-rule import.
- **How it works:** `hermes_cli/agent_import.py:491` `_run_codex()`, in this order:
  1. **config.toml** (`_load_codex_config`, line 537) parsed with `tomllib`; missing → `skipped` `No config.toml found`; unparseable → `error` `Could not parse config.toml: <exc>`.
  2. **`AGENTS.md` → `memories/MEMORY.md`** (kind `agents-md`), identical extractor/merger to the Claude path.
  3. **`config.toml` `mcp_servers` → `config.yaml mcp_servers`** (kind `mcp-servers`), identical rewrite and secret stripping.
  4. **`memories/*.md` → `memories/MEMORY.md`** (kind `memories`): every `*.md` in sorted order is run through `extract_markdown_entries` and merged as one batch. No directory → `skipped` `No memories directory found`; nothing extractable → `skipped` `No importable entries found`; an unreadable file → `error` `Could not read file: <exc>`.
  5. **`skills/<name>/SKILL.md` → `~/.hermes/skills/codex-imports/<name>/`** (`_SKILL_CATEGORY["codex"]`), identical copy semantics.
- **Inputs / options:** as `cli-d.import-agent`.
- **Outputs / side effects:** as `cli-d.import-agent`.
- **Edge cases / guards:** Codex has no `permissions` block, so `command_allowlist`/`approvals.deny` are untouched by this path.
- **Rebuild notes:** Keep the per-agent runner thin — one ordered list of mapper calls — so adding a third agent is a new `_run_<agent>` plus a category name.

---

## 11. `hermes config` — configuration management

### hermes config  `id: cli-d.config`
- **Surface:** CLI
- **Where:** `hermes config [{show,edit,get,set,unset,path,env-path,check,migrate}]`. Root help: *"View and edit configuration"*. Description: *"Manage Hermes Agent configuration"*.
- **What it does:** Command group for reading, editing, setting, removing, locating, checking and migrating the Hermes configuration. A bare `hermes config` runs `show`.
- **How it works:** Parser `hermes_cli/subcommands/config.py:12`; dispatcher `hermes_cli/config.py:6072` `config_command(args)` switching on `args.config_command` (`None` → `show`). `hermes_cli/main.py:5941` `cmd_config` wraps the call in a `try/except RuntimeError` so the fail-closed config-write guard prints `✗ <message>` on stderr and exits 1 instead of a traceback.
- **Inputs / options:** `-h`, `--help`; sub-commands `show`, `edit`, `get`, `set`, `unset`, `path`, `env-path`, `check`, `migrate`.
- **Outputs / side effects:** An unknown sub-command prints `Unknown config command: <s>`, a blank line, `Available commands:` and the nine lines `  hermes config           Show current configuration`, `  hermes config edit      Open config in editor`, `  hermes config get <key>          Print a resolved config value`, `  hermes config set <key> <value>   Set a config value`, `  hermes config unset <key>        Remove a config value`, `  hermes config check     Check for missing/outdated config`, `  hermes config migrate   Update config with new options`, `  hermes config path      Show config file path`, `  hermes config env-path  Show .env file path`, then exits 1.
- **Config / env:** `~/.hermes/config.yaml`, `~/.hermes/.env`, the managed scope (`HERMES_MANAGED_DIR`).
- **Edge cases / guards:** Two independent lock-outs exist: `is_managed()` (a package-manager write-lock — `edit`, `set` and `unset` refuse with `managed_error(...)`) and the managed scope (`managed_scope.is_key_managed(key)` — an administrator-pinned key cannot be set or unset).
- **Rebuild notes:** Keep read (`show`/`get`/`path`/`env-path`/`check`) and write (`edit`/`set`/`unset`/`migrate`) clearly separated, and make every write fail closed on an unreadable config.

### hermes config show  `id: cli-d.config-show`
- **Surface:** CLI
- **Where:** `hermes config show` (also the default for a bare `hermes config`). Help: *"Show current configuration"*.
- **What it does:** Prints a sectioned, human-readable summary of the merged configuration with secrets redacted.
- **How it works:** `hermes_cli/config.py:4925` `show_config()` over `load_config()` (merged with defaults). Section banners are cyan-bold `◆ <name>`.
- **Inputs / options:** `-h`, `--help` only.
- **Exact output sections and rows:**
  - Cyan banner box `┌───…┐` / `│              ⚕ Hermes Configuration                    │` / `└───…┘`.
  - **Managed-scope notice** (only when a managed scope pins anything): `  ⚷ Some settings are managed by your administrator (<dir>) and cannot be changed`, then `    Managed config keys: <sorted comma list>` and/or `    Managed env keys: <sorted comma list>`.
  - `◆ Paths` — `  Config:       <config path>`, `  Secrets:      <env path>`, `  Install:      <project root>`.
  - `◆ API Keys` — nine rows, each `  <name padded to 14> <redacted value>`: `OpenRouter` (`OPENROUTER_API_KEY`), `OpenAI (STT/TTS)` (`VOICE_TOOLS_OPENAI_KEY`), `Exa` (`EXA_API_KEY`), `Parallel` (`PARALLEL_API_KEY`), `Firecrawl` (`FIRECRAWL_API_KEY`), `Browserbase` (`BROWSERBASE_API_KEY`), `Browser Use` (`BROWSER_USE_API_KEY`), `FAL` (`FAL_KEY`), and `Anthropic` (from `hermes_cli.auth.get_anthropic_key()`). Unset renders `(not set)`.
  - `◆ Model` — `  Model:        <redacted model value>`, `  Max turns:    <agent.max_turns>`, plus a yellow `                ⚠ .env has stale HERMES_MAX_ITERATIONS=<v> (run 'hermes doctor --fix' to remove)` when the `.env` file disagrees with config.yaml.
  - `◆ Display` — `  Personality:  <active personality|none>`, `  Reasoning:    on|off` (`display.show_reasoning`, default on), `  Bell:         on|off` (`display.bell_on_complete`, default off), `  User preview: first <n> line(s), last <n> line(s)` (`display.user_message_preview.first_lines`/`last_lines`, defaults 2/2).
  - `◆ Terminal` — `  Backend:      <terminal.backend|local>`, `  Working dir:  <terminal.cwd|.>`, `  Timeout:      <terminal.timeout|60>s`, then backend-specific rows: docker → `  Docker image: <terminal.docker_image|nikolaik/python-nodejs:python3.11-nodejs20>`; singularity → `  Image:        <terminal.singularity_image|docker://nikolaik/…>`; modal → `  Modal image:  <…>` + `  Modal token:  configured|(not set)` (`MODAL_TOKEN_ID`); daytona → `  Daytona image: <…>` + `  API key:      configured|(not set)` (`DAYTONA_API_KEY`); vercel_sandbox → `  Vercel runtime: <terminal.vercel_runtime|node24>` + `  Vercel auth:    configured|(not set)` (`VERCEL_OIDC_TOKEN`, or all three of `VERCEL_TOKEN`/`VERCEL_PROJECT_ID`/`VERCEL_TEAM_ID`); ssh → `  SSH host:     <TERMINAL_SSH_HOST|(not set)>` + `  SSH user:     <TERMINAL_SSH_USER|(not set)>`.
  - `◆ Timezone` — `  Timezone:     <timezone>` or a dim `  Timezone:     (server-local)`.
  - `◆ Context Compression` — `  Enabled:      yes|no`; when enabled: `  Threshold:    <compression.threshold × 100>%` (default 0.50), optional `  Token cap:    <n> tokens (takes lower of ratio vs absolute)` when `compression.threshold_tokens` is a positive int, `  Target ratio: <compression.target_ratio × 100>% of threshold preserved` (default 0.20), `  Protect last: <compression.protect_last_n|20> messages`, `  Protect first: <compression.protect_first_n|3> non-system head messages`, `  Model:        <auxiliary.compression.model|(auto)>`, and `  Provider:     <auxiliary.compression.provider>` when it is set and not `auto`.
  - `◆ Auxiliary Models (overrides)` — printed only when an auxiliary task has a non-`auto` provider or a model; currently one row label, `Vision` (`auxiliary.vision`), rendered `  <label padded to 12>  provider=<p>[, model=<m>]`.
  - `◆ Messaging Platforms` — `  Telegram:     configured|not configured` (`TELEGRAM_BOT_TOKEN`), `  Discord:      configured|not configured` (`DISCORD_BOT_TOKEN`).
  - `◆ Skill Settings` — one row per discovered skill config var: `  <key padded to 20> <value|(not set)>  [<skill name>]` (from `agent.skill_utils.discover_all_skill_config_vars()` + `resolve_skill_config_values()`).
  - A dim 60-character rule then three hint lines: `  hermes config edit     # Edit config file`, `  hermes config set <key> <value>`, `  hermes setup           # Run setup wizard`.
- **Outputs / side effects:** stdout only.
- **Edge cases / guards:** Values are passed through `redact_key()` / `redact_config_value()` so a secret is never printed in full. The skill-settings block is wrapped in a bare `except Exception` and simply omitted on failure.
- **Rebuild notes:** Show the *merged* view, but flag anything the user cannot change (managed scope) and anything shadowed by a stale `.env` ghost.

### hermes config edit  `id: cli-d.config-edit`
- **Surface:** CLI
- **Where:** `hermes config edit`. Help: *"Open config file in editor"*.
- **What it does:** Opens `~/.hermes/config.yaml` in the user's editor, creating it from defaults first if it does not exist.
- **How it works:** `hermes_cli/config.py:5147` `edit_config()`. Refuses immediately when `is_managed()`. Creates the file with `save_config(DEFAULT_CONFIG, strip_defaults=False)` and prints `Created <path>` when absent. Editor resolution: `$EDITOR`, then `$VISUAL`, then the first of a platform-ordered candidate list found on `PATH` — on Windows `notepad`, `code`, `vim`, `vi`, `nano`; elsewhere `nano`, `vim`, `vi`, `code`, `notepad` (nano/vim first on POSIX because headless servers are more likely to have them). Launches `subprocess.run([editor, str(config_path)])`.
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** May create `config.yaml`; spawns an interactive editor. With no editor found: `No editor found. Config file is at:` + `  <path>`. Otherwise `Opening <path> in <editor>...`.
- **Config / env:** `EDITOR`, `VISUAL`.
- **Edge cases / guards:** Managed installs are blocked with the shared `managed_error("edit configuration")` message.
- **Rebuild notes:** Platform-order the fallback editor list; creating the file before opening avoids the "empty buffer, nothing saved" trap.

### hermes config get  `id: cli-d.config-get`
- **Surface:** CLI
- **Where:** `hermes config get [key] [--json]`. Help: *"Print a resolved configuration value"*. Positional help: *"Configuration key (e.g., model)"*; flag help: *"Print value as JSON"*.
- **What it does:** Prints one resolved configuration value (from the merged config, or from `.env` for env-shaped keys).
- **How it works:** `hermes_cli/config.py:6000` `get_config_value(key, as_json=)`. When `_is_env_config_key(key)` it reads `get_env_value(key.upper())`; otherwise `_get_nested(load_config(), key)` over the merged config. Formatting goes through `_format_config_get_value(value, as_json=)`.
- **Inputs / options:** positional `key` (dotted path, optional); `--json`; `-h`, `--help`.
- **Outputs / side effects:** stdout only. With no key: `Usage: hermes config get <key> [--json]`, blank, `Examples:`, `  hermes config get model`, `  hermes config get terminal.backend`, `  hermes config get skills.config --json`, exit 1. Unset key: `Config key not set: <key>` on stderr, exit 1.
- **Edge cases / guards:** Reads the merged view, so a value that comes from `DEFAULT_CONFIG` is still printed — "not set" here means "no default and no user value".
- **Rebuild notes:** Offer a JSON mode from the start; structured values are unreadable otherwise.

### hermes config set  `id: cli-d.config-set`
- **Surface:** CLI
- **Where:** `hermes config set [--force] [key] [value]`. Help: *"Set a configuration value"*. Positional help: *"Configuration key (e.g., model, terminal.backend)"* and *"Value to set"*. Flag help: *"Skip the unknown-key notice printed after writing a key the running version doesn't recognize (the value is saved either way)."*
- **What it does:** Writes one configuration value — into `~/.hermes/.env` for credential-shaped keys, otherwise into `~/.hermes/config.yaml` — coercing the string to the right YAML type and warning about unrecognized keys.
- **How it works:** `hermes_cli/config.py:5726` `set_config_value(key, value, force=)`, in order:
  1. **Managed write-lock** — `is_managed()` → `managed_error("set configuration values")` and return.
  2. **Key validation** — a key with surrounding whitespace or an empty string → `✗ Invalid config key: <repr> (empty or surrounding whitespace).` exit 1; any empty dotted segment (leading, trailing or doubled `.`) → `✗ Invalid config key: <repr> — contains an empty path segment (leading, trailing, or doubled '.').` exit 1.
  3. **Managed-scope guard** — `managed_scope.is_key_managed(key)` → `Cannot set '<key>': it is managed by your administrator (<managed dir>/config.yaml) and cannot be changed. Contact your administrator to modify it.` on stderr, exit 1.
  4. **Env-shaped keys** — `_is_env_config_key(key)` routes to `credential_lifecycle.save_provider_env_credential(key.upper(), value)` (which also rotates any config.yaml mirror of the old value so a stale higher-precedence copy cannot win) and prints `✓ Set <key> in <env path>`.
  5. **Fail-closed read** — `require_readable_config_before_write(config_path)` returns the raw user mapping; an unparseable or non-mapping config raises `RuntimeError`, surfaced as `✗ <message>` + exit 1.
  6. **Type coercion** (skipped entirely when the key's default is a `str`, so enum members like `approvals.mode: off` cannot become YAML booleans): `true|yes|on` → `True`; `false|no|off` → `False`; `null|none|~` → `None`; an int-parsable string (signs, whitespace and underscores allowed) → `int`; a float-parsable string → `float`; a value that `_looks_structured_value()` accepts (a list/mapping literal or a multi-line YAML block) is parsed with `yaml.safe_load` and stored as the parsed list/dict — with warnings `Warning: value for '<key>' looks like a list/mapping but parsed as <type>; storing as string.` or `Warning: value for '<key>' looks like a list/mapping but is not valid YAML/JSON; storing as string. Most isinstance-gated readers will ignore a string here.`
  7. **Scalar `model` normalisation** — writing any `model.*` sub-key while `model` is a bare string rewrites it to `{"default": <old string>}` first so the model id is not destroyed.
  8. **Section-overwrite guard** — a single-segment key naming an existing mapping is refused. For `model` specifically, without `--force` the write is redirected: `✓ Redirecting bare 'model' to 'model.default' (preserving <n> existing model sub-key(s))`; with `--force`: `⚠ Replacing entire 'model' section with a scalar (discarding <n> existing sub-key(s))`. For any other section without `--force`: `✗ Cannot set '<key>' to a scalar — '<key>' is a configuration section with <n> sub-key(s).`, `  Sub-keys: <first 8, comma-joined>`, `  ... and <k> more`, `  Use a dotted path to set a specific leaf key:`, `    hermes config set <key>.<sub-key> <value>`, `  Or use --force to replace the entire section:`, `    hermes config set --force <key> <value repr>`, exit 1.
  9. **Write** — `_set_nested()` (which preserves list-typed nodes and supports numeric list indices such as `custom_providers.0.api_key`; a `ValueError` prints `✗ <e>` + exit 1), then `atomic_yaml_write(config_path, user_config, sort_keys=False)`.
  10. **Alias normalisation** — `model.api_base` / `api_base` are rewritten to `model.base_url` with the note `  (note: 'api_base' is an alias — saved as model.base_url)`.
  11. **`.env` mirroring** — for keys `terminal_config_env_var_for_key(key)` recognises (except `terminal.cwd`), the corresponding env var is written with `save_env_value`.
  12. **Skin re-apply** — setting `display.skin` to a name with a file at `<home>/skins/<name>.yaml` `touch`es that file so the gateway's `(name, mtime)` watcher signature moves even when the name is unchanged.
  13. **Echo** — `✓ Set <key> = <value> in <config path>`, with the value masked (`agent.redact.mask_secret`) when the leaf key is in `_SECRET_CONFIG_KEYS`.
  14. **Cron drift warning** — `warn_unpinned_cron_jobs_after_model_config_change(key, value, user_config)` fires for `model`, `model.default`, `model.model`, `model.name` (axis `model`) and `model.provider`, `provider` (axis `provider`), governed by `cron.model_drift_guard` (only a literal `false` disables it).
  15. **Unknown-key notice** — when `_validate_config_key(key)` says the key is unrecognized and `--force` was not given: yellow `⚠ '<key>' is not a recognized config key — it was saved anyway, but Hermes may not read it.`, optional `  Did you mean: <suggestion>`, and dim `  (Custom top-level keys are supported and bridged to the environment for skills/external tools. Use --force to skip this notice.)`
- **Inputs / options:** positional `key`, positional `value`, `--force`, `-h`, `--help`.
- **Outputs / side effects:** Writes `config.yaml` and/or `.env`; may touch a skin file. With no key/value: `Usage: hermes config set [--force] <key> <value>`, blank, `Examples:`, `  hermes config set model anthropic/claude-sonnet-4`, `  hermes config set terminal.backend docker`, `  hermes config set OPENROUTER_API_KEY sk-or-...`, blank, `  --force: skip the unknown-key notice for unrecognized keys,`, `           and allow a scalar to replace a whole mapping section`, exit 1.
- **Config / env:** every dotted key in `DEFAULT_CONFIG`; `cron.model_drift_guard`; the managed scope.
- **Edge cases / guards:** Unknown keys are *written*, not rejected — top-level scalars are bridged into `os.environ` for skills and external apps — but the user is told the runtime may never read them.
- **Rebuild notes:** Read raw (not merged) before writing so defaults are never materialised into the user file; coerce types from the key's declared default; refuse to overwrite a section with a scalar unless forced.

### hermes config unset  `id: cli-d.config-unset`
- **Surface:** CLI
- **Where:** `hermes config unset [key]`. Help: *"Remove a configuration value"*. Positional help: *"Configuration key to remove"*.
- **What it does:** Removes a user-set value from `config.yaml` (or the credential from `.env`), leaving the built-in default in effect.
- **How it works:** `hermes_cli/config.py:6015` `unset_config_value(key)`. Refuses under `is_managed()`; refuses an administrator-pinned key with `Cannot unset '<key>': it is managed by your administrator (<src>) and cannot be changed. Contact your administrator to modify it.` (stderr, exit 1). For env-shaped keys it calls `credential_lifecycle.remove_provider_env_credential(key.upper())`, which also prunes env-seeded `credential_pool` entries and model-cache rows so the provider is fully removed rather than resurrectable; on success prints `✓ Unset <key> from <env path>`. For config keys it reads through `require_readable_config_before_write`, calls `_unset_nested`, also removes the mirrored `.env` var via `terminal_config_env_var_for_key` (except for `terminal.cwd`), and writes with `atomic_yaml_write(..., sort_keys=False)`, printing `✓ Unset <key> from <config path>`.
- **Inputs / options:** positional `key`; `-h`, `--help`.
- **Outputs / side effects:** Rewrites `config.yaml` and/or `.env`. With no key: `Usage: hermes config unset <key>`, blank, `Examples:`, `  hermes config unset model`, `  hermes config unset terminal.backend`, `  hermes config unset OPENROUTER_API_KEY`, exit 1. Key absent: `Config key not set: <key>` (stderr), exit 1.
- **Rebuild notes:** Unsetting a credential must also clear every derived cache; otherwise the provider comes back on the next load.

### hermes config path  `id: cli-d.config-path`
- **Surface:** CLI
- **Where:** `hermes config path`. Help: *"Print config file path"*.
- **What it does:** Prints the absolute path of the active `config.yaml`.
- **How it works:** `hermes_cli/config.py:6134` — a single `print(get_config_path())`; `get_config_path()` is at `hermes_cli/config.py:770` and resolves under `HERMES_HOME` (profile-aware).
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** One line, e.g. `/home/user/.hermes/config.yaml`. Read-only.
- **Config / env:** `HERMES_HOME`, the active profile.
- **Rebuild notes:** Print the path unadorned so it can be used directly in `$(...)`.

### hermes config env-path  `id: cli-d.config-env-path`
- **Surface:** CLI
- **Where:** `hermes config env-path`. Help: *"Print .env file path"*.
- **What it does:** Prints the absolute path of the active `.env`.
- **How it works:** `hermes_cli/config.py:6137` — `print(get_env_path())` (`get_env_path()` at `hermes_cli/config.py:774`).
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** One line, e.g. `/home/user/.hermes/.env`. Read-only.
- **Config / env:** `HERMES_HOME`, the active profile.
- **Rebuild notes:** n/a.

### hermes config check  `id: cli-d.config-check`
- **Surface:** CLI
- **Where:** `hermes config check`. Help: *"Check for missing/outdated config"*.
- **What it does:** Non-interactively reports the config schema version and which required/optional environment variables are set, plus how many new config options are available.
- **How it works:** `hermes_cli/config.py:6196`. `check_config_version()` (line 2184) returns `(current, latest)`. Then it iterates `REQUIRED_ENV_VARS` and `OPTIONAL_ENV_VARS` calling `get_env_value(name)`. `OPTIONAL_ENV_VARS` is auto-extended at import time by `_inject_profile_env_vars()` (line 2258), which pulls the `env_vars` of every `providers/` `ProviderProfile` with `auth_type == "api_key"` — so adding a provider profile automatically adds its keys here. Finally `get_missing_config_fields()` (line 1397) counts new options.
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** Read-only. Output: blank line, cyan-bold `📋 Configuration Status`, blank, then `  Config version: <n> ✓` or yellow `  Config version: <a> → <b> (update available)`; blank; bold `  Required:` and per var `    ✓ <NAME>` or red `    ✗ <NAME> (missing)`; blank; bold `  Optional:` and per var `    ✓ <NAME>` or dim `    ○ <NAME> → <first two tool names>`; then, when new options exist, yellow `  <n> new config option(s) available` and `    Run 'hermes config migrate' to add them`. (Observed live: config version 39, an empty `Required:` list, and ~200 optional vars including `NOUS_BASE_URL`, `OPENROUTER_API_KEY → vision_analyze`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `GLM_API_KEY`, `KIMI_API_KEY`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `HF_TOKEN`, `OLLAMA_API_KEY`, `AWS_REGION`, `BUZZ_*`, `SIMPLEX_*`, …).
- **Config / env:** the full `REQUIRED_ENV_VARS` / `OPTIONAL_ENV_VARS` tables — enumerated in the `config-a`/`config-b` shards, not here.
- **Rebuild notes:** Derive the optional-key list from the provider registry rather than a hand-maintained literal.

### hermes config migrate  `id: cli-d.config-migrate`
- **Surface:** CLI
- **Where:** `hermes config migrate`. Help: *"Update config with new options"*.
- **What it does:** Brings `config.yaml` up to the current schema version, adds newly-introduced options with their defaults, and interactively prompts for missing environment variables.
- **How it works:** `hermes_cli/config.py:6140`. First computes `get_missing_env_vars(required_only=False)` (line 1037), `get_missing_config_fields()` (line 1397) and `check_config_version()` (line 2184). If nothing is missing and the version is current it prints `✓ Configuration is up to date!` and returns. Otherwise it previews, then runs `migrate_config(interactive=True, quiet=False)` (line 2532) and reports the result.
- **Inputs / options:** `-h`, `--help` only. (The migration itself prompts interactively for missing keys.)
- **Outputs / side effects:** Rewrites `config.yaml` (and may write `.env`). Output: blank, cyan-bold `🔄 Checking configuration for updates...`, blank; then when up to date green `✓ Configuration is up to date!`; otherwise `  Config version: <a> → <b>` (when behind), `  <n> new config option(s) will be added with defaults`, `  ⚠️  <n> required API key(s) missing:` with `     • <NAME>` per var, `  ℹ️  <n> optional API key(s) not configured:` with `     • <NAME> (enables: <first two tools>)` per var; after the migration, green `✓ Configuration updated!` when anything was added, and each warning as yellow `  ⚠️  <warning>`.
- **Config / env:** the config schema version key; every default in `DEFAULT_CONFIG`.
- **Edge cases / guards:** `hermes doctor --fix` calls the same `migrate_config` non-interactively (`interactive=False, quiet=False`).
- **Rebuild notes:** Show the diff before applying, add new keys with defaults rather than rewriting the whole file, and keep an idempotent version counter.

---

## 12. `hermes skin` — terminal skins

### hermes skin  `id: cli-d.skin`
- **Surface:** CLI
- **Where:** `hermes skin [{list,use,set}]`. Root help: *"List, switch, and tweak skins"*. Description: *"Manage Hermes skins. `set` tweaks one color of the active skin in place."*
- **What it does:** Group command for terminal colour skins. Bare `hermes skin` falls through to `list`.
- **How it works:** Parser `hermes_cli/subcommands/skin.py:8`; dispatcher `hermes_cli/skin_cmd.py:98` `skin_command(args)` on `args.skin_command` (`set` → `_skin_set`, `use` → `_use`, anything else including `None` → `_skin_list`). Skins are YAML files in `<HERMES_HOME>/skins/*.yaml` plus the built-in table `_BUILTIN_SKINS` at `hermes_cli/skin_engine.py:201`. The active skin is `display.skin` in config.yaml (default `"default"`).
- **Inputs / options:** `-h`, `--help`; sub-commands `list`, `use`, `set`.
- **Config / env:** `display.skin`; `HERMES_HOME` (skins dir).
- **Edge cases / guards:** Editing a skin file bumps its mtime; the gateway's skin watcher repaints every live surface within about a second — hence the `(live within ~1s)` suffix on every success message.
- **Rebuild notes:** Keep built-ins as data and user skins as files, with the file shadowing rule "user name wins unless it duplicates a built-in name".

### hermes skin list  `id: cli-d.skin-list`
- **Surface:** CLI
- **Where:** `hermes skin list`. Help: *"List available skins"*.
- **What it does:** Lists every built-in and user skin with its source and description, marking the active one with `*`.
- **How it works:** `hermes_cli/skin_cmd.py:88` `_skin_list()` over `skin_engine.list_skins()` (`skin_engine.py:861`), which enumerates `_BUILTIN_SKINS` first (`source: "builtin"`) then every `<HERMES_HOME>/skins/*.yaml` in sorted order (`source: "user"`), skipping a user skin whose `name` shadows a built-in.
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** One line per skin: `<'*' if active else ' '> <name padded to 16> <source padded to 8> <description>`. The nine built-ins shipped at v2026.8.31, verbatim:
  - `default` — `Classic Hermes — gold and kawaii`
  - `ares` — `War-god theme — crimson and bronze`
  - `mono` — `Monochrome — clean grayscale`
  - `slate` — `Cool blue — developer-focused`
  - `daylight` — `Light theme for bright terminals with dark text and cool blue accents`
  - `warm-lightmode` — `Warm light mode — dark brown/gold text for light terminal backgrounds`
  - `poseidon` — `Ocean-god theme — deep blue and seafoam`
  - `sisyphus` — `Sisyphean theme — austere grayscale with persistence`
  - `charizard` — `Volcanic theme — burnt orange and ember`
- **Exit codes:** always `0` (via `sys.exit(_skin_list())`).
- **Rebuild notes:** Mark the active entry inline rather than printing it separately.

### hermes skin use  `id: cli-d.skin-use`
- **Surface:** CLI
- **Where:** `hermes skin use <name>`. Help: *"Switch the active skin"*. Positional help: *"Skin name"*.
- **What it does:** Sets `display.skin` to the named skin so every Hermes surface repaints with it.
- **How it works:** `hermes_cli/skin_cmd.py:34` `_use(name)` calls the shared config writer with a synthetic namespace: `config_command(argparse.Namespace(config_command="set", key="display.skin", value=name, force=True))` — `force=True` so the unknown-key notice never fires. That write path also `touch`es `<home>/skins/<name>.yaml` when it exists, moving the watcher's `(name, mtime)` signature.
- **Inputs / options:** positional `name`; `-h`, `--help`.
- **Outputs / side effects:** Writes `display.skin` into config.yaml (the config writer prints its own `✓ Set display.skin = <name> in <path>`), then `✓ active skin → <name> (live within ~1s)`.
- **Config / env:** `display.skin`.
- **Edge cases / guards:** An unknown name is accepted here; `skin_engine.load_skin()` (line 892) logs `Skin '<name>' not found, using default` and falls back to `default` at render time.
- **Rebuild notes:** Route the switch through the same config writer as everything else so managed-scope and mirroring rules apply once.

### hermes skin set  `id: cli-d.skin-set`
- **Surface:** CLI
- **Where:** `hermes skin set <key> <value> [--skin SKIN]`. Help: *"Set one color of the active skin (e.g. `skin set ui_tool '#00FFFF'`)"*. Positional help: *"Color key (e.g. ui_tool, ui_accent, background)"* and *"Hex color (#rrggbb)"*. Flag help: *"Target a specific skin instead of the active one"*.
- **What it does:** Changes exactly one colour of the active (or named) skin in place, leaving the rest of the palette — background included — untouched.
- **How it works:** `hermes_cli/skin_cmd.py:41` `_skin_set(key, value, skin)`. Validates the value against `_HEX_RE = ^#[0-9a-fA-F]{6}$`. Resolves the target name from `--skin` or `display.skin` (default `"default"`). If `<home>/skins/<name>.yaml` exists it is loaded and mutated. If it does not (i.e. the target is a built-in), the built-in is **forked**: `skin_engine.load_skin(name)` resolves the full palette and a new file `<home>/skins/<name>-custom.yaml` is written with `{"name": "<name>-custom", "description": "<name> + custom <key>", "colors": {…full palette…}, "branding": {…}, "tool_prefix": …}`, so the current look is preserved, only the one key changes, and the built-in stays intact for revert. The file is written with `utils.atomic_yaml_write(path, data, sort_keys=False)` — deliberately atomic because a truncating `write_text` plus `yaml.safe_load("") → None → {}` would permanently lose the palette on the next `set`. When a fork happened, `_use(target)` is called so the new skin becomes active.
- **Inputs / options:** positional `key`, positional `value`, `--skin SKIN`, `-h`, `--help`.
- **Colour keys (the `colors` block of a skin, from `_BUILTIN_SKINS["default"]`, `skin_engine.py:207`):** `banner_border`, `banner_title`, `banner_accent`, `banner_dim`, `banner_text`, `ui_accent`, `ui_label`, `ui_ok`, `ui_error`, `ui_warn`, `prompt`, `input_rule`, `response_border`, `status_bar_bg`, `status_bar_text`, `status_bar_strong`, `status_bar_dim`, `status_bar_good`, `status_bar_warn`, `status_bar_bad`, `status_bar_critical`, `session_label`, `session_border`, `completion_menu_bg`, `completion_menu_current_bg`, `selection_bg`, `shell_dollar`, `voice_status_bg`. A parallel `light_colors` block is merged over `colors` in light mode (default's light overlay redefines `banner_title`, `banner_accent`, `banner_dim`, `banner_text`, `ui_accent`, `ui_label`, `ui_ok`, `ui_error`, `ui_warn`, `prompt`, `response_border`, `session_label`, `status_bar_text`, `status_bar_strong`, `status_bar_dim`, `status_bar_good`, `status_bar_warn`, `status_bar_bad`, `status_bar_critical`, `shell_dollar`, `completion_menu_bg`, `completion_menu_current_bg`, `selection_bg`, `status_bar_bg`, `voice_status_bg`). The help text's example key `background` and the docstring's `ui_tool` are accepted as arbitrary keys — any key is written into the `colors` mapping.
- **Skin file schema (beyond `colors`):** `name`, `description`, `light_colors`, `spinner`, `branding` (`agent_name`, `welcome`, `goodbye`, `response_label`, `prompt_symbol`, `help_header`), `tool_prefix`.
- **Outputs / side effects:** Writes (or creates) a YAML file under `<home>/skins/`, and may switch `display.skin`. Prints `✓ <key> = <value> in <home>/skins/<target>.yaml (live within ~1s)`.
- **Exit codes:** `1` when the value is not a `#rrggbb` hex colour (`✗ '<value>' is not a #rrggbb hex color` on stderr); `0` otherwise.
- **Edge cases / guards:** A non-dict `colors` in an existing file is replaced with `{}` before the write. `data.setdefault("name", target)` guarantees the file names itself.
- **Rebuild notes:** Fork-on-first-edit is the key idea: never mutate a shipped preset, and carry the *resolved* palette into the fork so a one-key tweak does not reset everything else.

---

## 13. `hermes console` — the safe command REPL

### hermes console  `id: cli-d.console`
- **Surface:** CLI
- **Where:** `hermes console`. Root help: *"Open the safe Hermes command console"*. Description: *"Open a curated Hermes command REPL. This is not a raw shell and does not expose the full Hermes CLI."*
- **What it does:** Opens a line-oriented REPL that accepts a curated allowlist of Hermes commands (186 of them at v2026.8.31), refuses shell syntax, and asks for `[y/N]` confirmation before any of the 121 mutating commands.
- **How it works:** Parser `hermes_cli/subcommands/console.py:8`; entry `hermes_cli/main.py:12373` `cmd_console` → `hermes_cli/console_engine.py:1649` `run_console_repl()`. The engine (`HermesConsoleEngine`, line 505) holds `commands: dict[tuple[str, ...], ConsoleCommand]` where each `ConsoleCommand` carries `path`, `usage`, `summary`, `handler`, `mutating`, `confirmation`. Registration happens in `_register_defaults()` (line 576) — fifteen hand-written commands — plus `_register_broad_cli_surface()` (line 621), which reflects over the *real* argparse builders of the mainline CLI so the console's summaries are the same strings `hermes <cmd> --help` prints. Four adapter shapes exist: `_extracted_handler` (a `hermes_cli/subcommands/<x>.py` `build_*_parser` + a `main.cmd_*` handler), `_registered_handler` (a module with `register_cli`), `_builder_handler` (a module with `build_parser` + a named handler), and `_adder_handler` (a module with an `add_parser`/`register_*_subparser` function). Handler output is captured with `_capture_output` and the status footer stripped (`_strip_console_status_footer`).
  - **Execution pipeline** (`execute`, line 514): strip the line; tokenize with `_split_line`; drop a leading literal `hermes`; reject shell syntax via `_contains_shell_syntax`; try the built-ins; otherwise `_resolve_command` matches the longest 3-, 2- or 1-token prefix; a `mutating` command with `confirmed=False` returns `confirm_required`; otherwise the handler runs and the output is capped at `output_limit = 20000` bytes.
  - **REPL loop** (line 1649): prints `Hermes Console. Type \`help\` for commands, \`exit\` to quit.` when interactive, then a `hermes> ` prompt per line. On `confirm_required` it prints `<confirmation message> [y/N] ` and re-executes with `confirmed=True` on `y`/`yes`, else prints `Cancelled.`. Non-interactive input that hits a confirmation prints `Confirmation required: <message>` to stderr and returns 1. EOF returns 0.
- **Inputs / options:** `-h`, `--help` for the sub-command itself; inside the REPL every registered command plus the built-ins.
- **Built-in REPL commands (6):** `help` (full command table), `help <command>` (that command's `usage` + `summary`), `history` (numbered list of executed lines, or `No history yet.`), `clear` (emits `\033[2J\033[H`), `exit`, `quit`.
- **Refusals (`_rejection_for`, line 1170):** any token starting with `-` → `<token> is not available in Hermes Console.` Blocked top-level commands (23): `acp`, `chat`, `claw`, `completion`, `dashboard`, `desktop`, `fallback`, `gateway`, `gui`, `login`, `logout`, `model`, `moa`, `oneshot`, `proxy`, `serve`, `setup`, `uninstall`, `update`, `whatsapp`, `whatsapp-cloud` → `` `hermes <cmd>` is not available in Hermes Console.`` Blocked pairs (14), each with its own message: `config edit` (*"`config edit` opens an editor and is not available in Hermes Console."*), `mcp serve` (*"starts a server"*), `profile alias` (*"creates shell wrappers"*), `skills config` (*"is interactive"*), `skills publish`, `portal login` (*"is interactive"*), `portal open` (*"opens a browser"*), `kanban tail` (*"streams output"*), `kanban watch` (*"streams output"*), `kanban daemon` (*"starts a service"*), `kanban dispatcher` (*"starts a worker"*), `kanban swarm` (*"starts agent work"*), `kanban decompose` (*"starts agent work"*), `kanban specify` (*"starts agent work"*), `kanban gc`. Plus `sessions delete` and `sessions prune` → `` `sessions delete` and `sessions prune` are not available in Hermes Console.`` Shell syntax anywhere in the line → `Hermes Console does not run shell syntax. Use one supported Hermes command at a time.` An unmatched command → `Unsupported Hermes Console command: <probe>.` with a ` Did you mean: <up to 3 close matches>?` suffix from `difflib.get_close_matches(probe, available, n=3, cutoff=0.45)`.
- **Outputs / side effects:** Whatever the underlying command does. Output over 20000 bytes is truncated with `\n... output truncated (<n> bytes omitted)`.
- **Config / env:** none of its own; each delegated command uses its normal config.
- **Rebuild notes:** Build the allowlist by *reflecting over the real parsers*, so the console's help can never drift from the CLI's; gate mutation behind an explicit confirmation token rather than a mode flag.

### `hermes console` — the command table  `id: cli-d.console-commands`
- **Surface:** CLI
- **Where:** the output of `help` inside `hermes console`. Header lines: `Hermes Console`, blank, `Supported commands:`; footer lines: blank, `* requires confirmation`, `Built-ins: help, help <command>, history, clear, exit, quit`. Each row is `<' *' if mutating else '  '> <usage padded to 32> <summary truncated to 76 chars>`.
- **What it does:** Defines exactly which Hermes commands the console exposes. 186 commands total, 121 of them mutating (marked `*`).
- **Complete list, verbatim from a live `help` run (usage — summary; `*` = requires confirmation):**
  - `* auth add` — Add a pooled credential
  - `  auth list` — List pooled credentials
  - `* auth logout` — Log out a provider and clear stored auth state
  - `* auth remove` — Remove a pooled credential by index, id, or label
  - `* auth reset` — Clear exhaustion status for all credentials for a provider
  - `* auth spotify login` — Run `hermes auth spotify login`.
  - `* auth spotify logout` — Run `hermes auth spotify logout`.
  - `  auth spotify status` — Run `hermes auth spotify status`.
  - `  auth status` — Show auth status for a provider
  - `* backup` — Back up Hermes home directory to a zip file
  - `* bundles create` — Create a new skill bundle
  - `* bundles delete` — Delete a skill bundle
  - `  bundles list` — List installed skill bundles
  - `* bundles reload` — Re-scan the bundles directory and report changes
  - `  bundles show` — Show one bundle's contents
  - `* checkpoints clear` — Delete the entire checkpoint base (all /rollback history)
  - `* checkpoints clear-legacy` — Delete only the legacy-<ts>/ archives from v1 migration
  - `  checkpoints list` — Alias for 'status'
  - `* checkpoints prune` — Delete orphan/stale checkpoints and GC the store
  - `  checkpoints status` — Show total size, project count, and per-project breakdown
  - `  config check` — Check for missing/outdated config
  - `  config env-path` — Print .env file path
  - `* config migrate` — Update config with new options.
  - `  config path` — Print config.yaml path.
  - `* config set <key> <value>` — Set a configuration value.
  - `  config show` — Show current configuration.
  - `* cron create` — Create a scheduled job
  - `* cron edit` — Edit an existing scheduled job
  - `  cron list [--all]` — List scheduled jobs.
  - `* cron pause <job>` — Pause a scheduled job.
  - `* cron remove` — Remove a scheduled job
  - `* cron resume <job>` — Resume a paused cron job.
  - `* cron run <job>` — Run a job on the next scheduler tick.
  - `  cron status` — Show cron scheduler status.
  - `* cron tick` — Run due jobs once and exit
  - `* curator archive` — Manually archive a skill (move to .archive/, excluded from prompt)
  - `* curator backup` — Take a manual tar.gz snapshot of ~/.hermes/skills/ (curator also does thi...
  - `  curator list-archived` — List archived skills
  - `* curator pause` — Pause the curator until resumed
  - `* curator pin` — Pin a skill so the curator never auto-transitions it
  - `* curator prune` — Bulk-archive curator-managed skills idle for >= N days (default 90)
  - `* curator restore` — Restore an archived skill
  - `* curator resume` — Resume a paused curator
  - `* curator rollback` — Restore ~/.hermes/skills/ from a curator snapshot, or a single mutation b...
  - `* curator run` — Trigger a curator review now
  - `  curator status` — Show curator status and skill stats
  - `* curator unpin` — Unpin a skill
  - `* debug delete` — Delete a paste uploaded by 'hermes debug share'
  - `* debug share` — Upload debug report to a paste service and print a shareable URL
  - `  doctor` — Run diagnostics without auto-fix.
  - `  dump` — Dump setup summary for support/debugging
  - `* hooks doctor` — Check each configured hook: exec bit, allowlist, mtime drift, JSON validi...
  - `  hooks list` — List configured hooks with matcher, timeout, and consent status
  - `* hooks revoke` — Remove a command's allowlist entries (takes effect on next restart)
  - `* hooks test` — Fire every hook matching <event> against a synthetic payload
  - `* import` — Restore a Hermes backup from a zip file
  - `  insights` — Show usage insights and analytics
  - `* kanban archive` — Archive one or more tasks
  - `* kanban assign` — Assign or reassign a task
  - `  kanban assignments` — Run `hermes kanban assignments`.
  - `* kanban block` — Mark one or more tasks blocked
  - `* kanban boards create` — Create a new board
  - `  kanban boards current` — Run `hermes kanban boards current`.
  - `  kanban boards list` — List all boards with task counts
  - `* kanban boards rename` — Change a board's human-readable display name (slug is immutable)
  - `* kanban boards rm` — Archive (default) or delete a board
  - `* kanban boards set-workdir` — Run `hermes kanban boards set-workdir`.
  - `* kanban boards switch` — Set the active board for subsequent CLI calls
  - `* kanban claim` — Atomically claim a ready task (prints resolved workspace path)
  - `* kanban comment` — Append a comment
  - `* kanban complete` — Mark one or more tasks done
  - `  kanban context` — Print the full context a worker sees for a task (title + body + parent re...
  - `* kanban create` — Create a new task
  - `  kanban diagnose` — Run `hermes kanban diagnose`.
  - `* kanban edit` — Edit recovery fields on an already-completed task
  - `  kanban heartbeat` — Emit a heartbeat event for a running task (worker liveness signal)
  - `* kanban init` — Create kanban.db if missing (idempotent)
  - `* kanban link` — Add a parent->child dependency
  - `  kanban list` — List tasks
  - `* kanban promote` — Manually move one or more todo/blocked tasks to ready (recovery path)
  - `* kanban reassign` — Reassign a task to a different profile, optionally reclaiming first
  - `* kanban reclaim` — Release an active worker claim on a running task
  - `  kanban runs` — Show attempt history for a task (one row per run: profile, outcome, elaps...
  - `* kanban schedule` — Park one or more tasks in Scheduled (waiting on time, not human input)
  - `  kanban show` — Show a task with comments + events
  - `  kanban stats` — Per-status + per-assignee counts + oldest-ready age
  - `* kanban unblock` — Return blocked/scheduled tasks to ready, or todo while parents remain open
  - `* kanban unlink` — Remove a parent->child dependency
  - `  logs [name] [-n N]` — Show recent Hermes logs.
  - `* mcp add` — Add an MCP server (discovery-first install)
  - `  mcp catalog` — List Nous-approved MCPs available for one-click install
  - `* mcp configure` — Toggle tool selection
  - `* mcp install` — Install a catalog MCP by name (e.g. `hermes mcp install n8n`)
  - `  mcp list` — List configured MCP servers
  - `* mcp login` — Force re-authentication for an OAuth-based MCP server
  - `* mcp picker` — Interactive catalog picker (also the default for `hermes mcp`)
  - `* mcp reauth` — Re-authenticate one OAuth MCP server, or all of them (--all)
  - `* mcp remove` — Remove an MCP server
  - `  mcp test` — Test MCP server connection
  - `* memory off` — Disable external provider (built-in only)
  - `* memory reset` — Erase all built-in memory (MEMORY.md and USER.md)
  - `  memory status` — Show current memory provider config
  - `* pairing approve` — Approve a pairing request
  - `* pairing clear-pending` — Clear all pending codes
  - `  pairing list` — Show pending + approved users
  - `* pairing revoke` — Revoke user access
  - `  pets doctor` — Check pet setup + terminal graphics support
  - `* pets install` — Install a pet from the gallery
  - `  pets list` — Browse the petdex gallery
  - `* pets off` — Disable the pet display
  - `* pets remove` — Delete an installed pet
  - `* pets scale` — Resize the pet everywhere (display.pet.scale)
  - `* pets select` — Set the active pet (writes display.pet.*)
  - `  pets show` — Animate the active pet in the terminal
  - `* plugins disable` — Disable a plugin without removing it
  - `* plugins enable` — Enable a disabled plugin
  - `* plugins install` — Install a plugin from a Git URL, owner/repo, or index name
  - `  plugins list` — List installed plugins
  - `* plugins remove` — Remove an installed plugin
  - `* plugins update` — Pull latest changes for an installed plugin
  - `  portal info` — Show Portal auth + Tool Gateway routing summary
  - `  portal tools` — List Tool Gateway tools and which are routed via Nous
  - `  profile` — Show active profile status.
  - `* profile create` — Create a new profile
  - `* profile delete` — Delete a profile
  - `* profile describe` — Read or set a profile's description (used by the kanban orchestrator)
  - `* profile export` — Export a profile to archive
  - `* profile import` — Import a profile from archive
  - `  profile info` — Show a profile's distribution manifest (version, requirements, source)
  - `* profile install` — Install a profile distribution from a git URL or local directory
  - `  profile list` — List all profiles
  - `* profile rename` — Rename a profile ('default': sets a display name; id unchanged)
  - `  profile show` — Show profile details
  - `* profile update` — Re-pull a distribution and apply updates (user data preserved)
  - `* profile use` — Set sticky default profile
  - `* project add-folder` — Add a folder to a project
  - `* project archive` — Archive a project
  - `* project bind-board` — Bind a kanban board to a project
  - `* project create` — Create a new project
  - `  project list` — List projects
  - `* project remove-folder` — Remove a folder from a project
  - `* project rename` — Rename a project
  - `* project restore` — Restore an archived project
  - `* project set-primary` — Set the primary folder
  - `  project show` — Show a project's details
  - `* project use` — Set the active project
  - `  prompt-size` — Show a byte breakdown of the system prompt + tool schemas
  - `  security audit` — Run a one-shot supply-chain audit
  - `* send --to <target> <message>` — Send a message to a configured platform.
  - `* sessions export <output> [--source SOURCE] [--session-id ID]` — Export sessions to JSONL.
  - `  sessions list [--limit N]` — List recent sessions.
  - `* sessions optimize` — Optimize the session store.
  - `* sessions rename <session> <title>` — Rename a session.
  - `* sessions repair [--check-only] [--no-backup]` — Repair a malformed session database schema.
  - `  sessions stats` — Show session store statistics.
  - `* skills audit` — Re-scan installed hub skills
  - `  skills browse` — Browse all available skills (paginated)
  - `  skills check` — Check installed hub skills for updates
  - `  skills diff` — Show how your copy of a bundled skill differs from the stock version
  - `  skills inspect` — Preview a skill without installing
  - `* skills install` — Install a skill
  - `  skills list` — List installed skills
  - `  skills list-modified` — List bundled skills you've edited (which `hermes update` keeps)
  - `* skills opt-in` — Re-enable bundled-skill seeding (undo opt-out)
  - `* skills opt-out` — Stop bundled skills from being seeded into this profile
  - `* skills repair-official` — Backfill or restore official optional skills from repo source
  - `* skills reset` — Reset a bundled skill — clears 'user-modified' tracking so updates work a...
  - `  skills search` — Search skill registries
  - `* skills snapshot export` — Export installed skills to a file
  - `* skills snapshot import` — Import and install skills from a file
  - `* skills tap add` — Add a GitHub repo as skill source
  - `  skills tap list` — List configured taps
  - `* skills tap remove` — Remove a tap
  - `* skills uninstall` — Remove a hub-installed skill
  - `* skills update` — Update installed hub skills
  - `  slack manifest` — Print or write a Slack app manifest with every gateway command registered...
  - `  status` — Show Hermes component status.
  - `* tools disable` — Disable toolsets or MCP tools
  - `* tools enable` — Enable toolsets or MCP tools
  - `  tools list` — Show all tools and their enabled/disabled status
  - `* tools post-setup` — Run a provider's post-setup install hook (npm/pip/binary)
  - `  version` — Show Hermes version information.
  - `  webhook list` — List all dynamic subscriptions
  - `* webhook remove` — Remove a subscription
  - `* webhook subscribe` — Create a webhook subscription
  - `  webhook test` — Send a test POST to a webhook route
- **Confirmation messages (the hand-written ones):** `Update Hermes configuration?` (`config set`), `Update Hermes configuration with missing defaults?` (`config migrate`), `Pause this cron job?`, `Resume this cron job?`, `Trigger this cron job?`, `Export session data?`, `Rename this session?`, `Optimize the session database?`, `Repair the session database?`, `Send this message?`. Every reflected command falls back to `` Run `<usage>`? ``.
- **Rebuild notes:** A curated REPL is only safe if the deny list is explicit *and* the allow list is generated — hand-maintaining both drifts.

---

## 14. `hermes pairing` — DM pairing approvals

### hermes pairing  `id: cli-d.pairing`
- **Surface:** CLI
- **Where:** `hermes pairing [{list,approve,revoke,clear-pending}]`. Root help: *"Manage DM pairing codes for user authorization"*. Description: *"Approve or revoke user access via pairing codes"*.
- **What it does:** Group command for approving and revoking messaging-platform users who paired with the bot by DM code.
- **How it works:** Parser `hermes_cli/subcommands/pairing.py:12`; entry `hermes_cli/main.py:13111` `cmd_pairing` → `hermes_cli/pairing.py:11` `pairing_command(args)`, which instantiates `gateway.pairing.PairingStore()` and dispatches on `args.pairing_action`. Storage: `<HERMES_HOME>/platforms/pairing/` (with the legacy `<HERMES_HOME>/pairing/` merged in on first use by `_migrate_split_pairing_dirs`), holding `<platform>-pending.json`, `<platform>-approved.json` and `_rate_limits.json`.
- **Inputs / options:** `-h`, `--help`; sub-commands `list`, `approve`, `revoke`, `clear-pending`.
- **Outputs / side effects:** With no sub-command: `Usage: hermes pairing {list|approve|revoke|clear-pending}` and `Run 'hermes pairing --help' for details.`
- **Config / env:** `HERMES_HOME`, the active profile; per-platform allowlist env vars (`_PLATFORM_ALLOWLIST_ENV`, e.g. `TELEGRAM_ALLOWED_USERS`) — approving also writes the user into the operator's own allowlist when one is configured, and revoking removes them, so the allowlist stays the single visible source of truth.
- **Pairing constants (`gateway/pairing.py:45`):** code alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `0/O`, `1/I`), `CODE_LENGTH = 8`, `CODE_TTL_SECONDS = 3600` (1 hour), `RATE_LIMIT_SECONDS = 600` (one request per user per 10 minutes), `LOCKOUT_SECONDS = 3600`, `MAX_PENDING_PER_PLATFORM = 3`, `MAX_FAILED_ATTEMPTS = 5`.
- **Edge cases / guards:** `PAIRING_DIR` is deliberately left unresolved at import time — the long-lived gateway process would otherwise freeze the path to whatever `HERMES_HOME`/profile existed at import, which made gateway-issued codes unrecoverable from the CLI. A `PermissionError` reading a pairing file is logged loudly with owner uid and mode, because the classic Docker symptom (`docker exec` as root writes a 0600 file the gateway user cannot read) would otherwise silently mark the user unauthorized.
- **Rebuild notes:** Two identifiers per request — a public request id for admin surfaces and a secret code DM'd to the user — with rate limiting and lockout on the code path only.

### hermes pairing list  `id: cli-d.pairing-list`
- **Surface:** CLI
- **Where:** `hermes pairing list`. Help: *"Show pending + approved users"*.
- **What it does:** Prints two tables: pending pairing requests (with their request ids) and already-approved users.
- **How it works:** `hermes_cli/pairing.py:31` `_cmd_list(store)` over `store.list_pending()` (`gateway/pairing.py:800`) and `store.list_approved()` (line 554).
- **Inputs / options:** `-h`, `--help` only.
- **Outputs / side effects:** Read-only. Nothing at all → `No pairing data found. No one has tried to pair yet~`. Pending block: `  Pending Pairing Requests (<n>):`, header `  Platform     Request ID         User ID              Name                 Age` (widths 12/18/20/20), a dashed rule row `  --------     ----------         -------              ----                 ---`, then per row `  <platform:<12> <request_id or '-':<18> <user_id:<20> <user_name:<20> <n>m ago`; then `  Approve with: hermes pairing approve <platform> <request-id>` and `  The code the bot DM'd the user also works if they relay it.` No pending → `  No pending pairing requests.` Approved block: `  Approved Users (<n>):`, header `  Platform     User ID              Name` (widths 12/20/20), a dashed rule, then per row `  <platform:<12> <user_id:<20> <user_name:<20>`. None → `  No approved users.`
- **Edge cases / guards:** The one-time code is deliberately never shown — only the request id — so an admin surface cannot leak it.
- **Rebuild notes:** Show the request id, never the secret; print the exact approve command so the operator can copy it.

### hermes pairing approve  `id: cli-d.pairing-approve`
- **Surface:** CLI
- **Where:** `hermes pairing approve <platform> <request-id|code>`. Help: *"Approve a pairing request"*. Positional help: *"Platform name (telegram, discord, slack, whatsapp)"* and, for the second argument (metavar `request-id|code`), *"Request ID from 'pairing list', or the code the bot DM'd the user"*.
- **What it does:** Grants a pending user access to the bot on that platform, accepting either the admin-visible request id or the one-time code the bot DM'd the user.
- **How it works:** `hermes_cli/pairing.py:66` `_cmd_approve(store, platform, code)`. The platform is lower-cased and stripped. `PairingStore.looks_like_request_id(value)` (`gateway/pairing.py:754`) decides the path: a request id is exactly 16 hex characters (`secrets.token_hex(8)`), a code is 8 characters from the unambiguous uppercase alphabet — the two shapes cannot collide. A request id routes to `approve_request(platform, request_id)` (line 765), which deliberately does **not** count a miss toward the failed-attempt lockout; anything else is upper-cased and routed to `approve_code(platform, code)` (line 695), which does.
- **Inputs / options:** positional `platform`, positional `code` (request id or code); `-h`, `--help`.
- **Outputs / side effects:** Writes `<platform>-approved.json` (and the operator's platform allowlist env var when configured). Success: blank line then `  Approved! User <name> (<uid>)|<uid> on <platform> can now use the bot~` and `  They'll be recognized automatically on their next message.` Lock-out: `  Platform '<p>' is locked out after too many failed approval attempts.`, `  Lockout clears in ~<n> minute(s).`, `  To reset sooner, delete the '_lockout:<p>' entry from ~/.hermes/platforms/pairing/_rate_limits.json`. Not found: `  Pairing request or code '<code>' not found or expired for platform '<p>'.` and `  Run 'hermes pairing list' to see pending requests.`
- **Config / env:** `_PLATFORM_ALLOWLIST_ENV` (e.g. `TELEGRAM_ALLOWED_USERS`).
- **Edge cases / guards:** After `MAX_FAILED_ATTEMPTS = 5` failed code approvals the platform is locked out for `LOCKOUT_SECONDS = 3600`; the CLI disambiguates lockout from a wrong code explicitly, because `approve_code` returns `None` for both.
- **Rebuild notes:** Accept both identifier shapes and dispatch on their (deliberately non-colliding) shapes; only the guessable one feeds the lockout counter.

### hermes pairing revoke  `id: cli-d.pairing-revoke`
- **Surface:** CLI
- **Where:** `hermes pairing revoke <platform> <user_id>`. Help: *"Revoke user access"*. Positional help: *"Platform name"* and *"User ID to revoke"*.
- **What it does:** Removes a user from the approved list for a platform (and from the operator's allowlist env var when one is configured).
- **How it works:** `hermes_cli/pairing.py:104` `_cmd_revoke(store, platform, user_id)` → `PairingStore.revoke(platform, user_id)` (`gateway/pairing.py:587`). Platform is lower-cased and stripped.
- **Inputs / options:** positional `platform`, positional `user_id`; `-h`, `--help`.
- **Outputs / side effects:** Rewrites `<platform>-approved.json`. Prints `  Revoked access for user <uid> on <platform>.` or `  User <uid> not found in approved list for <platform>.` (each surrounded by blank lines).
- **Edge cases / guards:** Revoking is idempotent — an unknown user is reported, not an error.
- **Rebuild notes:** Keep grant and revoke symmetric across both stores (pairing file and allowlist env var), or the two drift.

### hermes pairing clear-pending  `id: cli-d.pairing-clear-pending`
- **Surface:** CLI
- **Where:** `hermes pairing clear-pending`. Help: *"Clear all pending codes"*.
- **What it does:** Deletes every outstanding (unapproved) pairing request across platforms.
- **How it works:** `hermes_cli/pairing.py:114` `_cmd_clear_pending(store)` → `PairingStore.clear_pending()` (`gateway/pairing.py:833`), which returns the number removed.
- **Inputs / options:** `-h`, `--help` only. (The underlying `clear_pending(platform=None)` supports a platform filter; the CLI does not expose it.)
- **Outputs / side effects:** Rewrites the `<platform>-pending.json` files. Prints `  Cleared <n> pending pairing request(s).` or `  No pending requests to clear.` (each surrounded by blank lines).
- **Edge cases / guards:** Codes expire on their own after `CODE_TTL_SECONDS = 3600`; this is the manual override. There is no confirmation prompt.
- **Rebuild notes:** Return the count so the operator can tell "cleared nothing" from "cleared everything".

---

## 15. Loose ends inside this shard

### `hermes verify <path>` — the project-root positional  `id: cli-d.verify-path`
- **Surface:** CLI
- **Where:** `hermes verify [path]` — the single optional positional argument. Help: *"Project root to verify (default: current directory)"*.
- **What it does:** Chooses which directory `hermes verify` detects, runs and (with `--save`) writes its manifest into.
- **How it works:** `hermes_cli/verify_cmd.py:29` — `root = Path(getattr(args, "path", None) or ".").resolve()`. Everything downstream (`load_or_detect(root)`, `manifest_path(root)`, `run_verify(root, …)`, `record_verify_run(root=…)`) uses this resolved path, and every phase command runs with `cwd=root`.
- **Inputs / options:** one optional path; `argparse` `nargs="?"`, `default=None`.
- **Outputs / side effects:** Determines where `.hermes/environment.json` is read and written, and the working directory of every executed command.
- **Edge cases / guards:** A path that is not a directory prints `error: not a directory: <resolved path>` on stderr and exits `2` — before any detection or execution.
- **Rebuild notes:** Resolve the path once and thread it everywhere; a relative `cwd` for shell commands is the classic source of "works in my terminal, fails in the runner".

### `hermes checkpoints` with no sub-command  `id: cli-d.checkpoints-default`
- **Surface:** CLI
- **Where:** `hermes checkpoints` (no verb).
- **What it does:** Runs `status`.
- **How it works:** `hermes_cli/checkpoints.py:234` — `parser.set_defaults(func=cmd_status)` before the sub-parsers are added, so a bare invocation dispatches to `cmd_status`. Because no `status` sub-parser ran, `args` has no `limit` attribute; `cmd_status` guards with `args.limit if hasattr(args, "limit") and args.limit else 20`.
- **Inputs / options:** none.
- **Outputs / side effects:** identical to `cli-d.checkpoints-status` with a 20-project limit.
- **Rebuild notes:** When a group has an obvious read-only default, wire it with `set_defaults` and make the handler tolerate the missing sub-parser attributes.

### `hermes security` with no sub-command  `id: cli-d.security-default`
- **Surface:** CLI
- **Where:** `hermes security` (no verb).
- **What it does:** Runs `audit` with all defaults (`--fail-on critical`, nothing skipped, human-readable output).
- **How it works:** `hermes_cli/main.py:5905` `cmd_security(args)` — `if sub in ("audit", None): … cmd_security_audit(args); sys.exit(int(code or 0))`. Anything else prints `unknown security subcommand: <sub>` on stderr and exits `2`.
- **Inputs / options:** none (defaults are read with `getattr(args, …, default)` so the missing sub-parser attributes are safe).
- **Outputs / side effects:** as `cli-d.security-audit`.
- **Rebuild notes:** Read sub-command options through `getattr` defaults so the group-level default path cannot crash on a missing attribute.

## Handoffs
- `hermes setup` (the interactive wizard `hermes doctor`, `hermes config migrate` and `hermes import-agent` all point users at) — cli-a/cli-b.
- `hermes sessions repair` / `hermes sessions optimize-storage` (the remedies `hermes doctor` names for a corrupt or oversized `state.db`) — cli-a/cli-b.
- `hermes update` (named as the SQLite/version-drift/agent-browser remedy and the caller of the pre-update quick snapshot and `create_pre_update_backup`) — cli-a/cli-b.
- `hermes gateway install` / `ensure_gateway_service` (invoked at the end of `hermes import`) — cli-a/cli-b.
- `hermes profile *` (wrapper scripts recreated by `hermes import`; the `Profiles` doctor section) — cli-a/cli-b.
- `hermes mcp test` (`hermes doctor --live` reuses `mcp_config._probe_single_server`) — cli-a/cli-b.
- `hermes memory setup` / `hermes memory status` (remedies named by the doctor Memory Provider section) — cli-a/cli-b.
- `hermes skills list` (remedy named by the doctor Skills Hub section) and the whole `hermes skills` tree exposed in the console — cli-a/cli-b.
- `hermes desktop --setup-tcc-identity` (named by the macOS TCC grant check) — cli-a/cli-b or the desktop shard.
- `hermes tools` → “Browser Automation” picker (named by the Lightpanda doctor check) — cli-a/cli-b.
- `/snapshot`, `/snapshot restore <id>` and `/rollback` gateway slash commands (the user-facing front ends of `backup --quick` and the checkpoint store) — the gateway shard.
- `POST /api/ops/debug-share` (the dashboard endpoint sharing `build_debug_share`) and the dashboard's Config/Hooks/Security pages — web-a/web-b.
- The 785 `DEFAULT_CONFIG` leaf keys that `hermes config set/get/unset` operate on, plus `REQUIRED_ENV_VARS` / `OPTIONAL_ENV_VARS` enumerated by `hermes config check` — config-a/config-b.
- `agent.redact.redact_sensitive_text` / `mask_secret` and the `security.redact_secrets` setting that `hermes debug share` force-overrides — the core/security shard.
- `tools.approval`'s hardline blocklist, `DANGEROUS_PATTERNS` and `_command_detection_variants` (the ladder `hermes approvals test` composes) — the core/security shard.
- `agent.shell_hooks` runtime dispatch beyond the CLI surface (the 37 `VALID_HOOKS` payload contracts and the `hooks.outbound` webhook signer) — the core/hooks shard.
- `tools.checkpoint_manager` internals (`prune_checkpoints`, `clear_all`, `clear_legacy`, the shadow-git layout) — the core/tools shard.
- `hermes_cli.security_advisories` startup banner path (`should_banner`, the cache) — cli-a/cli-b or the core shard.
- `hermes_cli.managed_scope` (the administrator-pinned config/env layer that gates `config set`/`unset`/`edit`) — config-a/config-b.
