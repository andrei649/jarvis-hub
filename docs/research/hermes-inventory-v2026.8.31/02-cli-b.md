# CLI part B — gateway, proxy, lsp, setup, whatsapp, whatsapp-cloud, slack, send, login/logout, auth, status, pause/resume

This shard inventories the `hermes` command-line surface for: `gateway` (11 sub-commands plus the run-time guards, the service back-ends for systemd/launchd/Windows/s6, and the full interactive `gateway setup` platform wizard including every plugin-provided platform wizard), `proxy` (local OpenAI-compatible credential-attaching proxy), `lsp` (language-server management), `setup` (every wizard mode, every section, every question), `whatsapp` (Baileys QR pairing), `whatsapp-cloud` (Meta Cloud API wizard), `slack manifest`, `send`, the deprecated `login`, `logout`, `auth` (credential pools + Spotify PKCE), `status`, and `pause`/`resume` (global emergency stop).
All facts come from hermes-agent v2026.8.31 source (paths cited as `path:line`), the live `--help` dumps in `hermes_inv/cli_help/`, and live runs against the prepared HERMES_HOME. Sibling shards own: the `hermes model` provider flows that `setup model` delegates to (only the menu that `setup model` shows is documented here), `hermes portal`, `hermes tools` (which `setup tools` delegates to), `hermes pairing`, `hermes egress`, `hermes claw migrate`, the gateway runtime itself (`gateway/run.py`, adapters, slash commands), the `send_message` tool internals, the Config page / dashboard, and the per-provider OAuth internals beyond what the `auth add` command surfaces.

### hermes gateway (command group)  `id: cli-b.gateway`
- **Surface:** CLI
- **Where:** `hermes gateway [--accept-hooks] {run,start,stop,restart,status,install,uninstall,list,setup,migrate-legacy,enroll}`; help text "Manage the messaging gateway (Telegram, Discord, WhatsApp, Weixin, and more)".
- **What it does:** Entry point for everything about the long-running gateway process (messaging platforms + cron scheduler). With no sub-command it behaves exactly like `hermes gateway run`.
- **How it works:** Parser built in `hermes_cli/subcommands/gateway.py:63-387` (`build_gateway_parser`), handler `hermes_cli/main.py:3510` (`cmd_gateway`) which first calls `_sync_bundled_skills_quietly()` then `hermes_cli/gateway.py:8244` (`gateway_command`) → `_gateway_command_inner` (`gateway.py:8380`). `gateway_command` converts two exceptions into clean exits: `UserSystemdUnavailableError` (prints "User systemd not reachable:" + remediation lines, exit 1) and `SystemScopeRequiresRootError` (prints message, exit 1).
- **Inputs / options:** `-h/--help`; `--accept-hooks` (store_true, default SUPPRESS; attached to the group parser AND to `run`, see `cli-b.gateway.accept-hooks`); sub-commands `run`, `start`, `stop`, `restart`, `status`, `install`, `uninstall`, `list`, `setup`, `migrate-legacy`, `enroll`. Hidden compat flag `--platform X` accepted (not advertised) on `start`, `restart`, `status` (`subcommands/gateway.py:17-29`, help=SUPPRESS) so stale docs that printed `gateway start --platform telegram` still parse; the value is ignored.
- **Outputs / side effects:** Depends on sub-command; see entries below.
- **Config / env:** `HERMES_HOME` selects the profile whose gateway is managed (service names derive from it, see `cli-b.gateway.service-naming`).
- **Edge cases / guards:** `install`, `uninstall`, `setup`, `enroll` refuse in managed installs (`is_managed()` → `managed_error(...)`, `hermes_cli/config.py:431`). Termux: no service manager (install/uninstall/start exit 1 with guidance). WSL without systemd: start/install exit 1 with tmux/nohup guidance.
- **Rebuild notes:** One argparse group dispatching to a `{sub → fn}` table with a platform-detection layer (`supports_systemd_services()`, `is_macos()`, `is_windows()`, `is_wsl()`, `is_container()`, `is_termux()`). A better version would expose the same lifecycle over the local API so the dashboard and CLI share one implementation rather than shelling out.

### --accept-hooks (auto-approve unseen shell hooks)  `id: cli-b.gateway.accept-hooks`
- **Surface:** CLI
- **Where:** `hermes gateway --accept-hooks …` and `hermes gateway run --accept-hooks`; help "Auto-approve unseen shell hooks without a TTY prompt (equivalent to HERMES_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."
- **What it does:** Lets a headless gateway start without stopping at the interactive "unseen hook" approval prompt.
- **How it works:** Defined once in `hermes_cli/subcommands/_shared.py:15-29` (`add_accept_hooks_flag`, `action=store_true`, `default=argparse.SUPPRESS` so absence leaves the namespace untouched and env/config decide). Consumed by the hooks approval layer in `hermes_cli/hooks.py` (sibling shard) which treats the flag, env `HERMES_ACCEPT_HOOKS=1`, or config `hooks_auto_accept: true` (default `false`, `config_defaults.json`) as equivalent.
- **Inputs / options:** the flag only.
- **Outputs / side effects:** unseen hooks are recorded as accepted instead of prompting.
- **Config / env:** `hooks_auto_accept` (bool, default false); `HERMES_ACCEPT_HOOKS`.
- **Edge cases / guards:** Because the same flag is attached to the group parser and to `run`, both `hermes gateway --accept-hooks run` and `hermes gateway run --accept-hooks` work.
- **Rebuild notes:** A tri-state "auto-accept hooks" resolved flag>env>config. Better: scope acceptance to a hash of the hook file so silent approval never covers later edits.

### hermes gateway run  `id: cli-b.gateway.run`
- **Surface:** CLI
- **Where:** `hermes gateway run [-v] [-q] [--replace] [--force] [--no-supervise] [--external-supervisor] [--accept-hooks]` (also the default when `hermes gateway` has no sub-command); help "Run gateway in foreground (recommended for WSL, Docker, Termux)".
- **What it does:** Starts the gateway (all configured messaging platforms + cron scheduler) as a foreground process and blocks until Ctrl+C or a fatal error.
- **How it works:** `_gateway_command_inner` (`hermes_cli/gateway.py:8380-8393`): if `--external-supervisor`, sets env `HERMES_GATEWAY_EXTERNAL_SUPERVISOR=1` (`EXTERNAL_GATEWAY_SUPERVISOR_ENV`, `gateway/restart.py:22`); then `run_gateway(verbose, quiet, replace, force)` (`gateway.py:6426`). `run_gateway` runs four guards (`cli-b.gateway.run.guards`), on Windows optionally absorbs console-control signals (SIGINT/SIGBREAK ignored + `SetConsoleCtrlHandler(NULL,1)` when `HERMES_GATEWAY_DETACHED=1`/breakaway), refreshes the user systemd unit if stale (`refresh_systemd_unit_if_needed(system=False)`), prints the banner box "⚕ Hermes Gateway Starting..." / "Messaging platforms + cron scheduler" / "Press Ctrl+C to stop", records exit diagnostics (`cli-b.gateway.run.exit-diag`), runs the respawn-storm breaker (`cli-b.gateway.run.respawn-storm`), then `asyncio.run(gateway.run.start_gateway(replace=replace, verbosity=None if quiet else verbose))`. Exit: KeyboardInterrupt → prints "Gateway stopped." exit 0; SystemExit → same code; `start_gateway` returning False → exit 1; all exits go through `gateway.run._exit_after_graceful_shutdown` (an `os._exit` after teardown so non-daemon threads such as in-flight cron jobs cannot keep the old process alive).
- **Inputs / options:** `-v/--verbose` (count; 0=WARNING, 1=INFO, 2+=DEBUG on stderr); `-q/--quiet` (suppress all stderr logs; overrides -v); `--replace` (kill any existing gateway instance for this profile before starting — skips the existing-process guard; "useful for systemd"); `--force` (bypass the supervised-service conflict guard and the named-profile-under-multiplexer guard); `--no-supervise` (inside the s6 Docker image, do not redirect to the supervised service — see `cli-b.gateway.run.s6-redirect`); `--external-supervisor` (declare an external process manager owns this process; in-chat `/restart` and updates exit with code 75 instead of spawning a detached replacement); `--accept-hooks`.
- **Outputs / side effects:** Writes `$HERMES_HOME/gateway.pid`, `$HERMES_HOME/gateway_state.json` (runtime status; read by `gateway status`), logs under `$HERMES_HOME/logs/gateway.log`, `logs/gateway-exit-diag.log`; may rewrite `~/.config/systemd/user/hermes-gateway*.service` if outdated. Stdout banner; stderr logs.
- **Config / env:** `HERMES_GATEWAY_NO_SUPERVISE`, `HERMES_S6_SUPERVISED_CHILD`, `HERMES_GATEWAY_EXTERNAL_SUPERVISOR`, `HERMES_GATEWAY_DETACHED`, `HERMES_GATEWAY_EXIT_DIAG` (default "1"), `HERMES_ALLOW_ROOT_GATEWAY`, `HERMES_GATEWAY_MAX_STARTS`, `HERMES_GATEWAY_START_WINDOW_S`; config `gateway.respawn_storm.max_starts` (5), `gateway.respawn_storm.window_seconds` (120), `gateway.multiplex_profiles`, `gateway.multiplex_profile_allowlist`.
- **Edge cases / guards:** Exit code 78 (`GATEWAY_FATAL_CONFIG_EXIT_CODE`, `gateway/restart.py:17`) is a permanent config refusal (systemd unit has `RestartPreventExitStatus=78`); exit 75 (`GATEWAY_SERVICE_RESTART_EXIT_CODE`, `gateway/restart.py:11`) means "supervisor, please relaunch me" (`RestartForceExitStatus=75`). `run_gateway` is also what `restart` falls back to when no service manager is present.
- **Rebuild notes:** Foreground runner = guards → banner → asyncio main → hard exit with contract exit codes (0/1/75/78). Better: emit a machine-readable readiness event (already partially: `gateway_state.json`) and structured JSON logs by default.

### gateway run — automatic s6 supervision redirect (Docker image)  `id: cli-b.gateway.run.s6-redirect`
- **Surface:** CLI
- **Where:** implicit in `hermes gateway run` inside the official s6-overlay container; opt-out with `--no-supervise` or `HERMES_GATEWAY_NO_SUPERVISE=1`.
- **What it does:** When PID 1 is s6, a bare `gateway run` is upgraded to "start the supervised `gateway-<profile>` longrun and keep the CMD process alive as a heartbeat" so the gateway auto-restarts on crash and the dashboard runs alongside if `HERMES_DASHBOARD` is set.
- **How it works:** `_maybe_redirect_run_to_s6_supervision` (`hermes_cli/gateway.py:8265-8355`): returns False (no redirect) if `--no-supervise`/env set, or if `HERMES_S6_SUPERVISED_CHILD` is set (we ARE the supervised child — prevents recursion), or if `_dispatch_via_service_manager_if_s6("start")` returns False (not an s6 container). Otherwise prints a stderr banner "→ gateway is now running under s6 supervision (auto-restart on crash, dashboard supervised alongside if HERMES_DASHBOARD is set)…Use `--no-supervise` (or HERMES_GATEWAY_NO_SUPERVISE=1) to opt out…", then `os.execvp("sleep", ["sleep","infinity"])`; if `sleep` is missing from PATH (issue #36208) it prints "→ `sleep` is unavailable; keeping the s6 CMD process alive in-process until the container is stopped." and blocks in `_block_until_terminated()` (`gateway.py:8357`) which installs a SIGTERM handler exiting 128+15 and loops on `signal.pause()` (or `threading.Event().wait()` where `pause` is missing).
- **Inputs / options:** `--no-supervise`; env `HERMES_GATEWAY_NO_SUPERVISE` (1/true/yes).
- **Outputs / side effects:** Supervised gateway logs go to `docker logs` and `$HERMES_HOME/logs/gateways/<profile>/current` via s6-log.
- **Config / env:** `HERMES_S6_SUPERVISED_CHILD`, `HERMES_DASHBOARD`.
- **Edge cases / guards:** Only inside a container where `hermes_cli.service_manager.detect_service_manager() == "s6"`; on hosts it is a no-op.
- **Rebuild notes:** Detect supervisor, delegate, exec a heartbeat. Better: return the supervised service's readiness status instead of blindly sleeping.

### gateway run — startup guards  `id: cli-b.gateway.run.guards`
- **Surface:** CLI
- **Where:** run automatically at the top of `run_gateway` (`hermes_cli/gateway.py:6438-6441`).
- **What it does:** Refuses to start a second/wrong gateway in four situations, each with an actionable message.
- **How it works:** (1) `_guard_official_docker_root_gateway` (`gateway.py:6399`): if euid==0 AND project root is `/opt/hermes` with `docker/entrypoint.sh` AND `HERMES_ALLOW_ROOT_GATEWAY` not truthy → "Refusing to run the Hermes gateway as root inside the official Docker image." exit 1. (2) `_guard_named_profile_under_multiplexer(force)` (`gateway.py:6257`): if this HERMES_HOME is `<root>/profiles/<name>` and `named_profile_served_by_running_multiplexer()` (`gateway.py:6181`: default root `gateway.pid` alive AND `multiplex_profiles` on via `GATEWAY_MULTIPLEX_PROFILES` env override or `<root>/config.yaml` `multiplex_profiles`/`gateway.multiplex_profiles`, AND profile not excluded by `gateway.multiplex_profile_allowlist`) → prints "The default gateway is running as a profile multiplexer and already serves profile '<name>'." + explanation + "hermes gateway restart" + "--force" hint; exits 78. (3) `_guard_supervised_gateway_conflict(force)` (`gateway.py:6309`): skipped when `--force` or when `is_gateway_supervisor_process()` (INVOCATION_ID from systemd, XPC_SERVICE_NAME from launchd, HERMES_S6_SUPERVISED_CHILD, or HERMES_GATEWAY_EXTERNAL_SUPERVISOR); otherwise if `get_gateway_runtime_snapshot()` says a service is installed AND running → "A gateway is already running under <manager> for this profile." + kanban-DB corruption warning (#35240) + "hermes gateway restart" + "--force"; exit 1. (4) `_guard_existing_gateway_process_conflict(replace)` (`gateway.py:6349`): skipped with `--replace` or under a supervisor; reads `gateway.status.get_running_pid()` (profile-scoped PID file); if a PID is alive → "Another gateway instance is already running (PID N)." + "Use 'hermes gateway restart' to replace it, or 'hermes gateway stop' first. Or use 'hermes gateway run --replace' to auto-replace." exit 1; if the PID file belongs to another profile a warning is logged only.
- **Inputs / options:** `--force`, `--replace`.
- **Outputs / side effects:** stderr/stdout messages; process exit codes 1 or 78.
- **Config / env:** `HERMES_ALLOW_ROOT_GATEWAY`, `GATEWAY_MULTIPLEX_PROFILES`, `gateway.multiplex_profiles`, `gateway.multiplex_profile_allowlist` (default null).
- **Edge cases / guards:** Guard probes are best-effort — any exception inside a probe is logged at DEBUG and the start proceeds.
- **Rebuild notes:** Four cheap pre-import checks (PID file, unit status, config flags) before the expensive `gateway.run` import. Better: a single "who owns this profile" lock file with owner metadata instead of four heuristics.

### gateway run — respawn-storm circuit breaker  `id: cli-b.gateway.run.respawn-storm`
- **Surface:** CLI
- **Where:** automatic inside `run_gateway` (`hermes_cli/gateway.py:6555-6605`); no flag.
- **What it does:** If the gateway has been (re)started more than N times within W seconds, sleeps a back-off before starting so a crash loop under any supervisor cannot spin at full speed.
- **How it works:** Defaults `max_starts=5`, `window=120s` from `DEFAULT_CONFIG gateway.respawn_storm`; overridden by config then by env `HERMES_GATEWAY_MAX_STARTS` / `HERMES_GATEWAY_START_WINDOW_S`; `max_starts <= 0` disables. Calls `gateway.status.record_start_and_check_storm(max_starts, window_s)`; if it returns a storm record, logs "Gateway (re)started %d times in %.0fs — backing off %.0fs to break a respawn storm." and `time.sleep(backoff_s)`.
- **Inputs / options:** none (config/env only).
- **Outputs / side effects:** start timestamps persisted by `gateway.status` (in `$HERMES_HOME`), a warning log, a delay.
- **Config / env:** `gateway.respawn_storm.max_starts` (5), `gateway.respawn_storm.window_seconds` (120), `HERMES_GATEWAY_MAX_STARTS`, `HERMES_GATEWAY_START_WINDOW_S`. Related but separate: `gateway.restart_loop_guard.{max_restarts:3,window_seconds:60,max_gap_seconds:300}` (used by the runtime, sibling shard).
- **Edge cases / guards:** Any bookkeeping failure is swallowed (DEBUG log) — never blocks startup.
- **Rebuild notes:** Sliding-window counter in a small state file + exponential back-off. Better: expose the storm state in `gateway status` output.

### gateway run — exit diagnostics log  `id: cli-b.gateway.run.exit-diag`
- **Surface:** CLI
- **Where:** automatic; file `$HERMES_HOME/logs/gateway-exit-diag.log`.
- **What it does:** Appends one JSON line for every way the gateway process can end (start, asyncio returned, KeyboardInterrupt, SystemExit, other exception, atexit, nonzero/clean exit) so silent deaths (historically Windows) leave evidence.
- **How it works:** `_exit_diag(tag, **extra)` closure in `run_gateway` (`hermes_cli/gateway.py:6494-6553`): gated on env `HERMES_GATEWAY_EXIT_DIAG` == "1" (default on); each line has `ts` (UTC ISO), `tag`, `pid`, `python`, `platform` plus tag-specific fields (`replace`, `argv`, `stdin_is_tty`, `console_window_attached`, `detached`, `breakaway`, `absorb_windows_console_controls`, `success`, `code`, `traceback`, `exc_type`, `exc_repr`, `sys_exc`). Tags: `gateway.start`, `asyncio.run.returned`, `asyncio.run.KeyboardInterrupt`, `asyncio.run.SystemExit`, `asyncio.run.exception`, `atexit.hook`, `gateway.exit_nonzero`, `gateway.exit_clean`.
- **Inputs / options:** none.
- **Outputs / side effects:** append-only JSONL file; never raises.
- **Config / env:** `HERMES_GATEWAY_EXIT_DIAG` (set to anything other than "1" to disable).
- **Edge cases / guards:** Directory created on demand; failures ignored.
- **Rebuild notes:** Wrap the main loop in a try/except that journals each exit path. Better: rotate the file and surface the last entry in `gateway status`.

### hermes gateway start  `id: cli-b.gateway.start`
- **Surface:** CLI
- **Where:** `hermes gateway start [--system] [--all]`; help "Start the installed systemd/launchd background service".
- **What it does:** Starts the already-installed background service for the current profile (or, in an s6 container, the profile's s6 slot).
- **How it works:** `_gateway_command_inner` (`hermes_cli/gateway.py:8541-8600`): if not `--all` and s6 detected → `_dispatch_via_service_manager_if_s6("start")` and return. If `--all` → `kill_gateway_processes(all_profiles=True)`, print "✓ Killed N stale gateway process(es) across all profiles", `_wait_for_gateway_exit(10s, force_after=5s)`. Then per platform: Termux → message + exit 1; systemd → `systemd_start(system)` (`gateway.py:4594`: `_select_systemd_scope`, root check for `--system`, `_preflight_user_systemd()` for user scope (D-Bus socket reachable, auto-enable linger), `_require_service_installed` ("✗ Gateway service is not installed / Run: hermes gateway install"), `refresh_systemd_unit_if_needed`, `systemctl [--user] start hermes-gateway[-profile]`, prints "✓ User service started"/"✓ System service started"); macOS → `launchd_start()` (`gateway.py:5719`: regenerates a missing plist, `launchctl kickstart <domain>/<label>`, re-bootstraps if unloaded, falls back to a detached process on macOS where launchd cannot manage the domain — issue #23387 — prints "✓ Service started"); Windows → `gateway_windows.start()` (`gateway_windows.py:1491`: no-op if PIDs exist "✓ Gateway already running (PID: …)", else runs the Scheduled Task / detached pythonw launcher); WSL without systemd → guidance + exit 1; other container → guidance ("Service start is not applicable inside a Docker container.") exit 0; else "Not supported on this platform." exit 1.
- **Inputs / options:** `--system` (target `/etc/systemd/system/hermes-gateway*.service`; requires root); `--all` (kill all stale gateway processes across all profiles first); hidden `--platform`.
- **Outputs / side effects:** service started; stdout confirmation lines.
- **Config / env:** `HERMES_HOME` (profile), `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` (user systemd preflight).
- **Edge cases / guards:** `_select_systemd_scope` auto-picks the system scope when only a system unit exists; `SystemScopeRequiresRootError` if `--system` without root; `UserSystemdUnavailableError` if the user bus is unreachable (fresh SSH session, no linger).
- **Rebuild notes:** Thin wrapper around the platform service manager with an install-check and a unit refresh. Better: return structured status (pid, since) instead of text.

### hermes gateway stop  `id: cli-b.gateway.stop`
- **Surface:** CLI
- **Where:** `hermes gateway stop [--system] [--all]`; help "Stop gateway service".
- **What it does:** Stops the current profile's gateway (service or manual process), or every gateway on the machine with `--all`.
- **How it works:** `hermes_cli/gateway.py:8602-8690`. Self-protection first: `tools.process_registry._is_supervised_gateway_process()` → if running inside the gateway itself prints "Refusing to stop the gateway from inside the gateway process. This command was blocked to prevent restart loops. Use `hermes gateway stop` from a shell outside the running gateway." exit 1. s6: `--all` → `_dispatch_all_via_service_manager_if_s6("stop")`, else `_dispatch_via_service_manager_if_s6("stop")`. `--all`: try the installed service stop (systemd `systemd_stop` / launchd `launchd_stop` / Windows `gateway_windows.stop`), then `kill_gateway_processes(all_profiles=True)`; prints "✓ Stopped N gateway process(es) across all profiles" or "✗ No gateway processes found". Default: same service stop; if no service definition exists falls back to `stop_profile_gateway()` (`gateway.py:2478`, PID-file based) printing "✓ Stopped gateway for this profile" / "✗ No gateway running for this profile"; with a service prints "✓ Stopped hermes-gateway[-profile] service". `systemd_stop` (`gateway.py:4612`) writes a planned-stop marker via `gateway.status.write_planned_stop_marker(pid)` so the gateway drains gracefully, then `systemctl stop` with a 90 s timeout ("Gateway user service is still stopping after 90s; check `hermes gateway status`…"). `launchd_stop` (`gateway.py:5777`) uses `launchctl bootout` (a plain SIGTERM would be respawned by KeepAlive), then `_wait_for_gateway_exit(10s, force_after=5s)`. Windows `stop()` (`gateway_windows.py:1619`) writes the planned-stop marker (Windows asyncio cannot receive SIGTERM; the marker file is the IPC), drains for `_windows_stop_drain_timeout()`, then force-terminates known PIDs.
- **Inputs / options:** `--system`, `--all`.
- **Outputs / side effects:** processes stopped; planned-stop marker file in `$HERMES_HOME`; stdout lines.
- **Config / env:** drain timeouts `_get_restart_drain_timeout()` / cron drain (`gateway.py:4433-4478`, config `gateway.*` restart timeouts — runtime shard).
- **Edge cases / guards:** in-gateway invocation refused; `subprocess.CalledProcessError` from the service manager is swallowed so the PID fallback still runs.
- **Rebuild notes:** service stop → PID fallback → force kill, with a planned-stop marker so the runtime distinguishes crash from intent. Better: wait for the runtime to acknowledge drain completion instead of fixed timeouts.

### hermes gateway restart  `id: cli-b.gateway.restart`
- **Surface:** CLI
- **Where:** `hermes gateway restart [--system] [--all]`; help "Restart gateway service".
- **What it does:** Gracefully restarts the gateway, preferring an in-band graceful restart (finish in-flight turns, then relaunch) and escalating to forced restarts when the process is wedged.
- **How it works:** `hermes_cli/gateway.py:8692-8850`. In-gateway invocation refused ("Refusing to restart the gateway from inside the gateway process…"). s6 dispatch as for stop. `--all`: stop service + `kill_gateway_processes(all_profiles=True)`, wait, print "Starting gateway...", then start the service (systemd/launchd/Windows) or `run_gateway(verbose=0)` in foreground. Default: systemd → `systemd_restart(system)` (`gateway.py:4640`): pre-flight, `refresh_systemd_unit_if_needed`, find PID; if `probe_gateway_loop_liveness(pid) == "wedged"` (`gateway.py:526`, socket tick probe) prints "⚠ Gateway PID N event loop is unresponsive — skipping graceful drain and forcing a bounded stop..." → `_escalate_wedged_gateway` (SIGTERM grace → SIGKILL) → `systemctl reset-failed` + `restart`; otherwise prints "⏳ User service restarting gracefully (PID N) — waiting up to Ns for in-flight turns + drain..." and sends SIGUSR1 (`_graceful_restart_via_sigusr1`, `gateway.py:307`; gateway exits 75 so systemd relaunches), waits with `_wait_for_systemd_service_restart`; handles start-limit ("⏳ Restart pending: systemd is temporarily rate-limiting starts"), stuck-failed and "⚠ Systemd did not relaunch the gateway after its graceful exit; starting the inactive service..." cases. macOS → `launchd_restart()` (`gateway.py:5901`: `_request_gateway_self_restart(pid)` → "✓ Service restart requested"; wedged escalation; graceful path; fallbacks to `launchctl kickstart -k`). Windows → `gateway_windows.restart()` (`gateway_windows.py:1687`: stop, wait ≤30 s for absence, force-kill if needed, sleep 1 s, start, wait ≤15 s for readiness, raises RuntimeError on failure). If no service: linger check ("⚠ Cannot restart gateway as a service — linger is not enabled." + "sudo loginctl enable-linger <user>"), or if a service definition exists but failed → "✗ Gateway service restart failed." exit 1; otherwise manual: `stop_profile_gateway()`, wait, "Starting gateway...", `run_gateway(verbose=0)` in the foreground.
- **Inputs / options:** `--system`, `--all`, hidden `--platform`.
- **Outputs / side effects:** service restarted; may rewrite unit/plist; stdout progress lines.
- **Config / env:** restart budgets from `_get_restart_exit_wait_budget()` / `_get_restart_after_turn_timeout()` / `_get_restart_drain_timeout()` / `_get_cron_drain_timeout()` (`gateway.py:4433-4478`).
- **Edge cases / guards:** Exit 75 contract with systemd (`RestartForceExitStatus=75`) and launchd (`KeepAlive`); `hermes update` reuses this path.
- **Rebuild notes:** Prefer signal-based graceful restart with the supervisor doing the relaunch; escalate only on a proven-dead event loop. Better: a single restart state machine shared by systemd/launchd/Windows/s6 back-ends.

### hermes gateway status  `id: cli-b.gateway.status`
- **Surface:** CLI
- **Where:** `hermes gateway status [--deep] [-l|--full] [--system]`; help "Show gateway status".
- **What it does:** Reports whether the gateway service/process is installed and running for this profile, recent runtime health, and the status of other profiles' gateways.
- **How it works:** `hermes_cli/gateway.py:8852-8990`. Takes `get_gateway_runtime_snapshot(system)` (`gateway.py:1961`; fields `running`, `manager`, `gateway_pids`, `service_installed`, `service_running`, `has_process_service_mismatch`). Branches: systemd unit exists → `systemd_status(deep, system, full)` (`gateway.py:4781`: "✗ Gateway service is not installed", scope-conflict and legacy-unit warnings, "⚠ Installed gateway service definition is outdated / Run: hermes gateway restart", runs `systemctl status <svc> --no-pager [-l]`, then `is-active` → "✓ User gateway service is running" / "✗ … is stopped / Run: hermes gateway start", "Configured to run as: <user>" for system scope, "Recent gateway health:" lines from `_runtime_health_lines()` (fatal platform errors "⚠ <platform>: <msg>", stale `gateway_state.json`, "⚠ Last startup issue:", "⏳ Gateway draining for restart|shutdown (N active agent(s))", "⚠ Last shutdown reason:"), unit property analysis ("⏳ Restart pending: systemd is waiting to relaunch the gateway", start-limit guidance, "⚠ Planned restart is stuck in systemd failed state (exit 75)", "⚠ Systemd unit result: <code>"), linger line ("✓ Systemd linger is enabled (service survives logout)" / "⚠ Systemd linger is disabled…Run: sudo loginctl enable-linger $USER" / for --system "✓ System service starts at boot without requiring systemd linger"), and with `--deep` "Recent logs:" + `journalctl [--user] -u <svc> -n 20 --no-pager [-l]`); then `_print_gateway_process_mismatch(snapshot)`. macOS plist exists → `launchd_status(deep)` (`gateway.py:6065`: "Launchd plist: <path>", "✓ Service definition matches the current Hermes install" / "⚠ Service definition is stale…", "✓ Gateway is supervised by launchd (PID N)", detached-fallback explanations, "✗ Gateway service is not loaded", with `--deep` `tail -20 logs/gateway.log`). Windows task/startup entry → `gateway_windows.status(deep)` (`gateway_windows.py:1448`: "✓ Scheduled Task registered: Hermes_Gateway[_profile]" + Status/Last Run Time/Last Run Result, or "✓ Windows login item installed: <vbs>", "✗ Gateway service not installed", "✓ Gateway process running (PID: …)" / "✗ No gateway process detected", deep: task name/script/startup entry + `_print_deep_probes()`). No service → manual detection: "✓ Gateway is running (PID: …)" + "(Running manually, not as a system service)" + health lines + platform note (Termux/WSL/Windows/"To install as a service: hermes gateway install / sudo hermes gateway install --system"), or "✗ Gateway is not running" + "To start:" list. Finally `_print_other_profiles_gateway_status()` (`gateway.py:2071`).
- **Inputs / options:** `--deep` (journal/log tail + linger guidance), `-l/--full` (pass `-l` to systemctl/journalctl for untruncated lines), `--system`, hidden `--platform`.
- **Outputs / side effects:** read-only; stdout report.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Live run in this environment printed "✗ Gateway is not running" + the three start hints (no service installed).
- **Rebuild notes:** Snapshot (PID file + service manager query + `gateway_state.json`) → human report. Better: `--json` output for dashboards (currently text only).

### hermes gateway install  `id: cli-b.gateway.install`
- **Surface:** CLI
- **Where:** `hermes gateway install [--force] [--system] [--run-as-user USER] [--start-now|--no-start-now] [--start-on-login|--no-start-on-login]`; help "Install gateway as a systemd/launchd background service".
- **What it does:** Registers the gateway as a background service (systemd user/system unit, launchd agent, or Windows Scheduled Task with Startup-folder fallback), optionally enabling boot/login autostart and starting it immediately.
- **How it works:** `hermes_cli/gateway.py:8395-8500`. Managed install → `managed_error`. Termux → "Gateway service installation is not supported on Termux." exit 1. Linux with systemd: WSL prints "WSL detected — systemd services may not survive WSL restarts." + tmux hint; `start_now`/`start_on_login` resolved from flags, else prompted on a TTY ("Start the gateway now after installing the service?" default Yes; "Start the gateway automatically on login/boot with systemd?" default Yes), else True; then `systemd_install(force, system, run_as_user, enable_on_startup, non_interactive)` (`gateway.py:4479`): root check for `--system`; offers legacy-unit removal ("Remove the legacy unit(s) before installing?" default Yes; auto-yes non-interactive); existing unit without `--force` → repair if outdated ("↻ Repairing outdated user systemd service at: <path>" → "✓ User service definition updated") else "Service already installed at: <path> / Use --force to reinstall"; otherwise writes `generate_systemd_unit()` (see `cli-b.gateway.install.systemd-unit`), refuses temp-home paths (`_refuse_temp_home_service_write`), `systemctl daemon-reload`, `systemctl enable` when enabling, prints "✓ User service installed and enabled!" + "Next steps:" (`hermes gateway start`, `hermes gateway status`, `journalctl --user -u hermes-gateway -f`), for system scope "Configured to run as: <user>", for user scope `_ensure_linger_enabled()` (runs `loginctl enable-linger`, warns via `_print_linger_enable_warning` on failure), then scope-conflict and legacy warnings; finally `systemd_start` if `start_now`. macOS → `launchd_install(force)` (`gateway.py:5662`: repair-if-stale, "Service already installed at: … Use --force to reinstall", write plist, `launchctl bootstrap`, on unsupported domain (exit 5/125) `_launchd_fallback_to_detached`, prints "✓ Service installed and loaded!" + "Next steps:" `hermes gateway status`, `tail -f ~/.hermes/logs/gateway.log`). Windows → `gateway_windows.install(force, start_now, start_on_login, elevated_handoff)` (`gateway_windows.py:1055`: asks "Start the gateway now after install?" and "Start the gateway automatically on Windows login with a Scheduled Task?" unless given via flags or env `HERMES_GATEWAY_INSTALL_START_NOW` / `HERMES_GATEWAY_INSTALL_START_ON_LOGIN`; writes `%HERMES_HOME%\gateway-service\Hermes_Gateway[_profile].cmd` + `.vbs`, registers Scheduled Task `Hermes_Gateway[_profile]` via `schtasks` (elevating through UAC with `--elevated-handoff` re-entry when access is denied), falls back to a Startup-folder `.vbs` login item ("↻ Scheduled Task install blocked (…) — using Startup folder fallback", "✓ Installed Windows login item: <path>"), optionally spawns detached ("✓ Gateway already running (PID: …)" / "ℹ Startup fallback installed; gateway not started now.")). WSL w/o systemd → guidance exit 1. Container: s6 → "Per-profile gateways are auto-registered when you create a profile." + `hermes profile create <name>` / `hermes -p <name> gateway start` / `hermes status` (return); other container → "Service installation is not needed inside a Docker container." + docker restart-policy hints, exit 0. Else "Service installation not supported on this platform." exit 1.
- **Inputs / options:** `--force` (reinstall even if current); `--system` (Linux system-level unit in `/etc/systemd/system`, starts at boot); `--run-as-user USER` (User= for the system unit; defaults via `_default_system_service_user()`); `--start-now` / `--no-start-now` (tri-state, default None → prompt/True); `--start-on-login` / `--no-start-on-login` (tri-state); hidden `--elevated-handoff` (Windows UAC re-entry marker).
- **Outputs / side effects:** unit/plist/task files written; `systemctl daemon-reload/enable`; `loginctl enable-linger`; service possibly started.
- **Config / env:** `HERMES_HOME` baked into the unit (`Environment="HERMES_HOME=…"`); `HERMES_GATEWAY_INSTALL_START_NOW`, `HERMES_GATEWAY_INSTALL_START_ON_LOGIN` (Windows).
- **Edge cases / guards:** Refuses to write a unit that points into a temp home; `--system` without root raises `SystemScopeRequiresRootError`; legacy `hermes.service` detection (`cli-b.gateway.migrate-legacy`).
- **Rebuild notes:** Generate a service definition from (python path, project root, HERMES_HOME, profile arg) and register it with the native manager; keep an `is_current()` comparator to self-repair. Better: keep the definition in a versioned template and diff-print what changed on repair.

### gateway install — generated systemd unit  `id: cli-b.gateway.install.systemd-unit`
- **Surface:** Core
- **Where:** `~/.config/systemd/user/hermes-gateway[-<profile>].service` (user) or `/etc/systemd/system/hermes-gateway[-<profile>].service` (system).
- **What it does:** Defines how systemd supervises the gateway.
- **How it works:** `generate_systemd_unit(system, run_as_user)` (`hermes_cli/gateway.py:3995-4133`). Both scopes contain: `Description=Hermes Agent Gateway - Messaging Platform Integration`, `After=network-online.target`, `StartLimitIntervalSec=0` (rate limiter off — the exit-code backstops replace it), `Type=<systemd_type>` (notify when the watchdog is enabled, via `_systemd_watchdog_service_fields`, `WatchdogSec` from `_systemd_watchdog_seconds()`), `ExecStart=<python> -m hermes_cli.main [--profile <name>] gateway run`, `WorkingDirectory=<stable dir>` (`_stable_service_working_dir`), `Environment="PATH=<sane path incl. ~/.local/bin, venv, node dir, WSL interop>"`, `Environment="VIRTUAL_ENV=…"`, `Environment="HERMES_HOME=…"`, `Environment="HERMES_SUPERVISED_CHILD=1"`, `Restart=always`, `RestartSec=5`, `RestartForceExitStatus=75`, `RestartPreventExitStatus=78`, `KillMode=mixed`, `TimeoutStopSec=<restart_timeout>`, `StandardOutput=journal`, `StandardError=journal`. System scope adds `User=`, `Environment="HOME=…"`, `USER`, `LOGNAME`, `WantedBy=multi-user.target`; user scope `WantedBy=default.target`. `systemd_unit_is_current()` (`gateway.py:4179`) normalises both texts (dropping optional directives) to decide repair; `refresh_systemd_unit_if_needed` (`gateway.py:4276`) rewrites + `daemon-reload` and syncs `HERMES_HOME` from the installed unit (`_sync_hermes_home_from_systemd_unit`).
- **Inputs / options:** n/a (derived).
- **Outputs / side effects:** unit file text.
- **Config / env:** watchdog seconds derived from config (`gateway.py:3897`).
- **Edge cases / guards:** `_refuse_temp_home_service_write` blocks `/tmp`-style homes.
- **Rebuild notes:** Template with exit-code contract (75 relaunch, 78 stop). Better: `ExecReload` mapped to SIGUSR1 so `systemctl reload` triggers the graceful restart.

### gateway install — generated launchd plist  `id: cli-b.gateway.install.launchd-plist`
- **Surface:** Core
- **Where:** `~/Library/LaunchAgents/<label>.plist` (`get_launchd_plist_path`, `hermes_cli/gateway.py:3626`), label from `get_launchd_label()` (`gateway.py:4905`, profile-scoped).
- **What it does:** Defines the macOS LaunchAgent that keeps the gateway alive.
- **How it works:** `generate_launchd_plist()` (`gateway.py:5318-5438`): keys `Label`, `ProgramArguments` (python, `-m hermes_cli.main`, optional `--profile <name>`, `gateway`, `run`), `WorkingDirectory`, `EnvironmentVariables` (PATH, HERMES_HOME, VIRTUAL_ENV…), `RunAtLoad` true, `KeepAlive` true, `ThrottleInterval` (raised above launchd's 10 s default to damp respawn storms), `ExitTimeOut` (25 s graceful drain), `StandardOutPath`/`StandardErrorPath` → `$HERMES_HOME/logs/gateway.log`. Domain resolution `_launchd_domain()` (`gateway.py:4965`, `gui/<uid>` vs `user/<uid>`), bootstrap with retries (`_retry_launchctl_bootstrap_until_registered`), unsupported-domain marker file (`_launchd_unsupported_marker_path`, `gateway.py:5171`) and reload log (`_launchd_reload_log_path`, `gateway.py:5066`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** plist text; marker/log files under `$HERMES_HOME`.
- **Config / env:** n/a.
- **Edge cases / guards:** macOS 26+ domains that refuse `bootstrap`/`kickstart` (exit 5/125) trigger the detached-process fallback with "⚠ Auto-start at login and auto-restart on crash are NOT available." in status.
- **Rebuild notes:** KeepAlive agent + exit-code contract. Better: use `launchctl print` structured output for status instead of parsing `launchctl list`.

### gateway install — Windows Scheduled Task backend  `id: cli-b.gateway.install.windows-task`
- **Surface:** CLI
- **Where:** Windows only; `hermes gateway install|uninstall|start|stop|restart|status` route to `hermes_cli/gateway_windows.py`.
- **What it does:** Implements the gateway service on Windows as a Scheduled Task named `Hermes_Gateway` (`_TASK_NAME_DEFAULT`, `gateway_windows.py:62`) or `Hermes_Gateway_<profile>`, with a Startup-folder `.vbs` login item as fallback when `schtasks` is denied.
- **How it works:** Task script `%HERMES_HOME%\gateway-service\<task>.cmd` (`get_task_script_path`, `gateway_windows.py:315`) + windowless `.vbs` launcher (`_build_gateway_vbs_script`), task XML (`_build_scheduled_task_xml`), `schtasks /Create` (`_install_scheduled_task`), Startup entry `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\<task>.vbs` (`get_startup_entry_path`, legacy `.cmd` variant also cleaned). Detached spawn uses `pythonw.exe` (`_resolve_detached_python`, `_spawn_detached`) with `HERMES_GATEWAY_DETACHED=1`. `uninstall()` (`gateway_windows.py:1220`) deletes the task (`schtasks /Delete /F /TN`), the `.cmd`/`.vbs` scripts and both Startup entries. `status`, `start`, `stop`, `restart` documented in the respective entries above. UAC elevation helpers `_launch_elevated_install` / `_launch_elevated_uninstall` re-run the command elevated and pass `--elevated-handoff`.
- **Inputs / options:** same flags as `gateway install`; env `HERMES_GATEWAY_INSTALL_START_NOW`, `HERMES_GATEWAY_INSTALL_START_ON_LOGIN` (1/true/yes/y/on or 0/false/no/n/off).
- **Outputs / side effects:** task registered, scripts written, login item.
- **Config / env:** `HERMES_GATEWAY_DETACHED`.
- **Edge cases / guards:** `_assert_windows()` raises on other OSes; `is_installed()` = task registered OR startup entry present; "installed" does not imply "running" (PID scan is authoritative).
- **Rebuild notes:** Scheduled Task (logon trigger) + windowless launcher + PID-file lifecycle. Better: a real Windows service wrapper (e.g. via `pywin32`) with SCM integration.

### hermes gateway uninstall  `id: cli-b.gateway.uninstall`
- **Surface:** CLI
- **Where:** `hermes gateway uninstall [--system]`; help "Uninstall gateway service".
- **What it does:** Stops, disables and removes the background service definition for this profile.
- **How it works:** `hermes_cli/gateway.py:8502-8539`. In-gateway invocation refused ("Refusing to uninstall the gateway from inside the gateway process…"). Managed → `managed_error`. Termux → message exit 1. systemd → `systemd_uninstall(system)` (`gateway.py:4566`: scope select, root check, `systemctl stop` (90 s) + `disable`, unlink unit "✓ Removed <path>", `daemon-reload`, "✓ User service uninstalled"). macOS → `launchd_uninstall()` (`gateway.py:5703`: `launchctl bootout <domain>/<label>`, unlink plist, "✓ Service uninstalled"). Windows → `gateway_windows.uninstall()`. Container: s6 → "Per-profile gateways are auto-unregistered when you delete the profile." (+ `hermes profile delete <name>`, `hermes -p <name> gateway stop`); other → "Service uninstall is not applicable inside a Docker container." + `docker stop/rm`, exit 0. Else "Not supported on this platform." exit 1.
- **Inputs / options:** `--system`.
- **Outputs / side effects:** service files removed; the gateway process is stopped as a side effect.
- **Config / env:** n/a.
- **Edge cases / guards:** never touches profile units of other profiles.
- **Rebuild notes:** reverse of install. Better: print what was removed and what remains (logs, PID files).

### hermes gateway list  `id: cli-b.gateway.list`
- **Surface:** CLI
- **Where:** `hermes gateway list`; help "List all profiles and their gateway status".
- **What it does:** Prints every known profile and whether its gateway is running (with PID).
- **How it works:** `_gateway_list()` (`hermes_cli/gateway.py:2096-2135`): `hermes_cli.profiles.list_profiles()` + `get_active_profile_name()`; header "Gateways:"; per profile "  ✓|✗ <name>[ (current)]" then " — PID <n>" (from `gateway.status.get_running_pid(<profile>/gateway.pid, cleanup_stale=False)`) or " — not running". "No profiles found." / "Unable to list profiles." fallbacks.
- **Inputs / options:** none.
- **Outputs / side effects:** read-only. Live output here: "Gateways:\n  ✗ default (current)        — not running".
- **Config / env:** profiles under `<root>/profiles/<name>`.
- **Edge cases / guards:** PID lookup failures are ignored.
- **Rebuild notes:** iterate profile dirs, stat PID files. Better: include manager type and uptime per profile.

### hermes gateway setup (interactive platform wizard)  `id: cli-b.gateway.setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup`; help "Configure messaging platforms". (The `hermes setup gateway` section reuses the same platform wizards but with a checklist UI — see `cli-b.setup.gateway`.)
- **What it does:** Menu-driven configuration of every messaging platform Hermes knows (built-in + plugin), then offers to install/start/restart the gateway service.
- **How it works:** `gateway_setup()` (`hermes_cli/gateway.py:7878-8135`). Managed → `managed_error("run gateway setup")`. Prints the magenta box "⚕ Gateway Setup / Configure messaging platforms and the gateway service. / Press Ctrl+C at any time to exit." Service status: warns on systemd scope conflicts (`print_systemd_scope_conflict_warning`) and legacy units; "Gateway service is installed and running." / "Gateway service is installed but not running." → (if system scope needs root prints remediation, else asks "  Start it now?" default Yes and starts) / "Gateway service is not installed yet. / You'll be offered to install it after configuring platforms.". Loop: `print_header("Messaging Platforms")`, builds `menu_items = ["<emoji> <label>  (<status>)", …, "Done"]` from `_all_platforms()` + `_platform_status()` (`cli-b.gateway.setup.platform-menu`), `prompt_choice("Select a platform to configure:", …, default=Done)`; choosing a platform calls `_configure_platform(platform)` (`gateway.py:7834`: plugin `setup_fn` → built-in fn (`_builtin_setup_fn`: bluebubbles→`setup._setup_bluebubbles`, webhooks→`setup._setup_webhooks`, signal, weixin, qqbot) → `_setup_standard_platform` when the entry has `vars` → env-var hint fallback). After "Done": if any platform reports progress (`_is_progress`: status not "not configured"/"partially…"/"plugin disabled…") → post-setup service block (`cli-b.gateway.setup.post-setup-service`), else "No platforms configured. Run 'hermes gateway setup' when ready."
- **Inputs / options:** none on the command line; all interaction is via curses menus (`prompt_choice`, arrow keys, Enter; Esc cancels; numbered fallback without curses) and line prompts.
- **Outputs / side effects:** writes `~/.hermes/.env` keys via `save_env_value` (`hermes_cli/config.py:4544`; rewrites the file, matches `KEY=` and `export KEY=` forms, strips newlines/non-ASCII from credentials, quotes values), platform config fields in `config.yaml` (`write_platform_config_field`), and may install/start/restart the service.
- **Config / env:** every platform's env vars (see per-platform entries); `GATEWAY_ALLOW_ALL_USERS`.
- **Edge cases / guards:** Matrix hidden on Windows (python-olm has no wheel); plugin platforms under `~/.hermes/plugins/` must be enabled in `plugins.enabled` to appear; bundled `kind: platform` plugins auto-load.
- **Rebuild notes:** registry of platforms → (status probe, wizard fn); a loop menu; a post-step that reconciles the service. Better: drive each wizard from a declarative schema (already partially: `vars` lists) so the dashboard and CLI render the same form.

### gateway setup — platform menu and status strings  `id: cli-b.gateway.setup.platform-menu`
- **Surface:** CLI
- **Where:** the "Select a platform to configure:" menu of `hermes gateway setup` and the checklist of `hermes setup gateway`.
- **What it does:** Enumerates the platforms and shows a status word for each.
- **How it works:** `_all_platforms()` (`hermes_cli/gateway.py:6883-6946`) = built-in `_PLATFORMS` (`gateway.py:6691-6881`: mattermost, signal, weixin, bluebubbles, qqbot, yuanbao) + every `gateway.platform_registry` entry not already covered (plugins discovered via `hermes_cli.plugins.discover_plugins()`). Live menu order/labels in this install: `💬 Mattermost`, `📡 Signal`, `💬 Weixin / WeChat`, `💬 BlueBubbles (iMessage)`, `🐧 QQ Bot`, `💎 Yuanbao`, `🧩 A2A`, `🐝 Buzz`, `🐳 DingTalk`, `🎮 Discord`, `📧 Email`, `🪽 Feishu / Lark`, `💬 Google Chat`, `🏠 Home Assistant`, `💬 IRC`, `💚 LINE`, `🔐 Matrix`, `🔔 ntfy`, `📱 iMessage via Photon`, `🔔 Raft`, `🔒 SimpleX Chat`, `💼 Slack`, `📱 SMS (Twilio)`, `💼 Microsoft Teams`, `✈️ Telegram`, `💼 WeCom (Enterprise WeChat)`, `💼 WeCom Callback (self-built apps)`, `💬 WhatsApp`, then `Done`. Status via `_platform_status()` (`gateway.py:6948-7025`): registry entries → `entry.is_connected(PlatformConfig(enabled=True))` else `entry.check_fn()` → "configured"/"not configured"; built-ins by `token_var`: WhatsApp `WHATSAPP_ENABLED=true` + `whatsapp/session/creds.json` → "configured + paired", enabled without creds → "enabled, not paired"; signal needs `SIGNAL_HTTP_URL`+`SIGNAL_ACCOUNT` ("partially configured" if only one); email needs `EMAIL_ADDRESS`+`EMAIL_PASSWORD`+`EMAIL_IMAP_HOST`+`EMAIL_SMTP_HOST`; matrix needs (`MATRIX_ACCESS_TOKEN` or `MATRIX_PASSWORD`) + `MATRIX_HOMESERVER`, suffix " + E2EE" when `MATRIX_ENCRYPTION` truthy; weixin needs `WEIXIN_ACCOUNT_ID`+`WEIXIN_TOKEN`; otherwise token present → "configured".
- **Inputs / options:** n/a.
- **Outputs / side effects:** none.
- **Config / env:** per-platform `token_var`s listed in the per-platform entries.
- **Edge cases / guards:** Uncolored status text so curses width math is right.
- **Rebuild notes:** registry + `is_connected` probe. Better: a tri-state (configured / partial / not) with the missing-field names.

### gateway setup — standard vars-driven wizard  `id: cli-b.gateway.setup.standard-platform`
- **Surface:** CLI
- **Where:** used by `hermes gateway setup` for built-in entries with a `vars` list (Mattermost, Yuanbao) — `_setup_standard_platform` (`hermes_cli/gateway.py:7090-7285`).
- **What it does:** Generic prompt loop over a platform's declared env vars with allowlist handling and an access-policy question.
- **How it works:** Prints "  ─── <emoji> <label> Setup ───", the `setup_instructions` lines, and if the `token_var` already exists "✓ <label> is already configured." → "  Reconfigure <label>?" (default No → return). Telegram-specific automatic path (kept for compatibility: "  Telegram can be configured automatically with a managed bot: [1] Automatic (scan QR → confirm in Telegram → done) [2] Manual BotFather token", "  Choice [1/2]" default 1 → `telegram_managed_bot.auto_setup_telegram_bot_result()`; Telegram now normally routes to the plugin wizard). Filters vars through `hermes_cli/setup_hidden_env.is_setup_hidden_env` (hides home channel/reply mode/proxy/mention knobs unless required or allowlist). For each var: prints its `help`, "  Current: <value>" when set, then: allowlist vars → "  The gateway DENIES all users by default for security. / Enter user IDs to create an allowlist, or leave empty / and you'll be asked about open access next." → `prompt("  <prompt>")`; non-empty → spaces stripped, Discord `<@123>`/`user:` prefixes stripped, saved, "  Saved — only these users can interact with the bot."; empty → `prompt_choice("  How should unauthorized users be handled?", ["Enable open access (anyone can message the bot)", "Use DM pairing (unknown users request access, you approve with 'hermes pairing approve')", "Skip for now (bot will deny all users until configured)"], default 1)` (email variant: "Enable open access (any email sender can message the bot)", "Use DM pairing (unknown email senders receive a pairing code)", "Keep unknown senders silent", default 2) → writes `GATEWAY_ALLOW_ALL_USERS=true` (or `EMAIL_ALLOW_ALL_USERS`) with "  Open access enabled — anyone can use your bot!", or pairing ("  DM pairing mode — users will receive a code to request access." + "  Approve with: hermes pairing approve <platform> <code>"; email also writes `unauthorized_dm_behavior: pair` into config.yaml), or "  Skipped — configure later with 'hermes gateway setup'". Other vars → `prompt(prompt, password=var.password)`; saved "  Saved <NAME>"; empty token → "  Skipped — <label> won't work without this." and abort; empty optional → "  Skipped (can configure later)". After the loop, if an allowlist was set and `<LABEL>_HOME_CHANNEL` is unset and label is Telegram → "  Use your user ID (<id>) as the home channel?" default Yes. Ends "<emoji> <label> configured!".
- **Inputs / options:** Mattermost vars: `MATTERMOST_URL` "Server URL (e.g. https://mm.example.com)", `MATTERMOST_TOKEN` "Bot token" (hidden), `MATTERMOST_ALLOWED_USERS` "Allowed user IDs (comma-separated)" (allowlist), `MATTERMOST_HOME_CHANNEL` "Home channel ID (for cron/notification delivery, or empty to set later with /set-home)", `MATTERMOST_REPLY_MODE` "Reply mode — 'off' for flat messages, 'thread' for threaded replies (default: off)"; instructions 1-5 quoted at `gateway.py:6709-6717`. Yuanbao vars: `YUANBAO_APP_ID` "App ID", `YUANBAO_APP_SECRET` "App Secret" (hidden); instructions "1. Download the Yuanbao app from https://yuanbao.tencent.com/ … 4. Enter them below and Hermes will connect automatically over WebSocket". (QQ Bot and BlueBubbles also declare `vars` but are dispatched to dedicated wizards; their `vars` only drive status.)
- **Outputs / side effects:** `.env` writes; `config.yaml` platform field for email pairing.
- **Config / env:** `GATEWAY_ALLOW_ALL_USERS`, `EMAIL_ALLOW_ALL_USERS`, `gateway.platforms.<key>.unauthorized_dm_behavior`.
- **Edge cases / guards:** Note: the Mattermost plugin also registers its own `interactive_setup` (`plugins/platforms/mattermost/adapter.py:1166`, prompts "Mattermost server URL (e.g. https://mm.example.com)", "Bot token", "Allowed user IDs (comma-separated, leave empty for open access)", "Home channel ID (leave empty to set later with /set-home)") but the built-in dict wins in `_all_platforms` (by_key dedupe), so the standard wizard above is what runs.
- **Rebuild notes:** schema-driven prompts + shared allowlist/access policy step. Better: validate values per field (URL, numeric IDs) before saving.

### gateway setup — Signal wizard  `id: cli-b.gateway.setup.signal`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `📡 Signal`; `_setup_signal` (`hermes_cli/gateway.py:7665-7793`).
- **What it does:** Configures the signal-cli HTTP daemon URL, account number, allowlist and group policy.
- **How it works:** Header "  ─── 📡 Signal Setup ───"; if both `SIGNAL_HTTP_URL` and `SIGNAL_ACCOUNT` set → "Signal is already configured." / "  Reconfigure Signal?" (No → return). Checks `shutil.which("signal-cli")` → "signal-cli found on PATH." or warning + install options (Linux releases URL, `brew install signal-cli`, Docker `bbernhard/signal-cli-rest-api`) and link/daemon commands (`signal-cli link -n "HermesAgent"`, `signal-cli --account +YOURNUMBER daemon --http 127.0.0.1:8080`). Prompts: "  HTTP URL [<existing or http://127.0.0.1:8080>]: "; "  Testing connection..." → `httpx.get(<url>/api/v1/check, timeout=10)` → "  signal-cli daemon is reachable!" / "  signal-cli responded with status N." + "  Continue anyway?" (default No) / unreachable → "  Save this URL anyway? (you can start signal-cli later)" (default Yes); saves `SIGNAL_HTTP_URL`. "  Account number[ [existing]]: " (E.164, required → "  Account number is required."), saves `SIGNAL_ACCOUNT`. "  Allowed users [<existing or account>]: " → `SIGNAL_ALLOWED_USERS`. "  Enable group messaging? (disabled by default for security)" (default No) → "  Group IDs [<existing or *>]: " → `SIGNAL_GROUP_ALLOWED_USERS`. Summary "Signal configured!" with URL, Account, "DM auth: via SIGNAL_ALLOWED_USERS + DM pairing", "Groups: enabled|disabled".
- **Inputs / options:** the prompts above; Ctrl+C/EOF at any prompt → "  Setup cancelled.".
- **Outputs / side effects:** `.env` keys `SIGNAL_HTTP_URL`, `SIGNAL_ACCOUNT`, `SIGNAL_ALLOWED_USERS`, `SIGNAL_GROUP_ALLOWED_USERS`.
- **Config / env:** as above.
- **Edge cases / guards:** connectivity test is advisory.
- **Rebuild notes:** URL probe + 4 prompts. Better: auto-detect the account from `signal-cli listAccounts`.

### gateway setup — Weixin / WeChat wizard  `id: cli-b.gateway.setup.weixin`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💬 Weixin / WeChat`; `_setup_weixin` (`hermes_cli/gateway.py:7368-7536`).
- **What it does:** Logs a Tencent iLink bot identity in via QR code and stores the returned credentials plus DM/group policies.
- **How it works:** Header "  ─── 💬 Weixin / WeChat Setup ───" + 4 info lines (QR login in terminal; scan with WeChat; stores account_id/token in `~/.hermes/.env`; supports text/image/video/document). Already configured (`WEIXIN_ACCOUNT_ID`+`WEIXIN_TOKEN`) → "  Reconfigure Weixin?" (No → return). Imports `gateway.platforms.weixin.check_weixin_requirements/qr_login` (failure → "  Weixin adapter import failed: …" / "  Missing dependencies: Weixin needs aiohttp and cryptography."). "  Start QR login now?" (default Yes) → `asyncio.run(qr_login(HERMES_HOME))` → saves `WEIXIN_ACCOUNT_ID`, `WEIXIN_TOKEN`, `WEIXIN_BASE_URL` (if returned), `WEIXIN_CDN_BASE_URL` (default `https://novac2c.cdn.weixin.qq.com/c2c`). `prompt_choice("  How should direct messages be authorized?", ["Use DM pairing approval (recommended)", "Allow all direct messages", "Only allow listed user IDs", "Disable direct messages"], 0)` → writes `WEIXIN_DM_POLICY` (pairing|open|allowlist|disabled), `WEIXIN_ALLOW_ALL_USERS`, `WEIXIN_ALLOWED_USERS` (allowlist prompt "  Allowed Weixin user IDs (comma-separated)" defaulting to the detected user id). Note lines about @im.bot identities not receiving ordinary group events. `prompt_choice("  How should group chats be handled?", ["Disable group chats (recommended)", "Allow all group chats", "Only allow listed group chat IDs"], 0)` → `WEIXIN_GROUP_POLICY` (disabled|open|allowlist) + `WEIXIN_GROUP_ALLOWED_USERS` ("  Allowed group chat IDs (comma-separated, not member user IDs)"). If a user id was returned: "  Use your Weixin user ID (<id>) as the home channel?" (Yes → `WEIXIN_HOME_CHANNEL`). Ends "Weixin configured!" + "  Account ID: …" / "  User ID: …".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys listed; QR session files under `$HERMES_HOME` by `qr_login`.
- **Config / env:** `WEIXIN_*` keys above.
- **Edge cases / guards:** KeyboardInterrupt → "  Weixin setup cancelled."; "  QR login did not complete." when no credentials.
- **Rebuild notes:** async QR flow returning creds → policy prompts. Better: persist DM/group policy in config.yaml instead of six env keys.

### gateway setup — QQ Bot wizard  `id: cli-b.gateway.setup.qqbot`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🐧 QQ Bot`; `_setup_qqbot` (`hermes_cli/gateway.py:7539-7662`); `hermes setup gateway` reaches the same function via `setup._setup_qqbot` (`setup.py:2211`).
- **What it does:** Registers a QQ official bot by QR scan or manual App ID/Secret, then sets DM policy and home channel.
- **How it works:** Header "  ─── 🐧 QQ Bot Setup ───"; existing `QQ_APP_ID`+`QQ_CLIENT_SECRET` → "  Reconfigure QQ Bot?" (No → return). `prompt_choice("  How would you like to set up QQ Bot?", ["Scan QR code to add bot automatically (recommended)", "Enter existing App ID and App Secret manually"], 0)`; QR → `gateway.platforms.qqbot.qr_register()` (Ctrl+C → "  QQ Bot setup cancelled."; None → "  QR setup did not complete. Continuing with manual input."). Manual: "  Go to https://q.qq.com to register a QQ Bot application." → `prompt("  App ID")` (empty → "  Skipped — QQ Bot won't work without an App ID."), `prompt("  App Secret", password=True)`. Saves `QQ_APP_ID`, `QQ_CLIENT_SECRET`. `prompt_choice("  How should direct messages be authorized?", ["Use DM pairing approval (recommended)", "Allow all direct messages", "Only allow listed user OpenIDs"], 0)` → pairing: `QQ_ALLOW_ALL_USERS=false`, optional "  Add yourself (<openid>) to the allow list?" (Yes → `QQ_ALLOWED_USERS=<openid>`), "  DM pairing enabled."; open: `QQ_ALLOW_ALL_USERS=true`; allowlist: "  Allowed user OpenIDs (comma-separated)". Home channel: "  Use your QQ user ID (<openid>) as the home channel?" or "  Home channel OpenID (for cron/notifications, or empty)" → `QQBOT_HOME_CHANNEL`. Ends "🐧 QQ Bot configured!" + "  App ID: …".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys `QQ_APP_ID`, `QQ_CLIENT_SECRET`, `QQ_ALLOW_ALL_USERS`, `QQ_ALLOWED_USERS`, `QQBOT_HOME_CHANNEL`.
- **Config / env:** as above; legacy `QQ_HOME_CHANNEL` still honoured by `hermes status`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** QR-or-manual credential capture + policy prompts. Better: validate App ID numeric shape.

### gateway setup — BlueBubbles (iMessage) wizard  `id: cli-b.gateway.setup.bluebubbles`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💬 BlueBubbles (iMessage)` and `hermes setup gateway`; both dispatch to `hermes_cli/setup.py:2146` `_setup_bluebubbles` (via `_builtin_setup_fn`).
- **What it does:** Stores the BlueBubbles server URL/password, allowlist, home channel and optional webhook port.
- **How it works:** `print_header("BlueBubbles (iMessage)")`; existing `BLUEBUBBLES_SERVER_URL` → "BlueBubbles: already configured" / "Reconfigure BlueBubbles?" (No → return). Info: requires Mac running BlueBubbles Server v1.0.0+, download URL, "In BlueBubbles Server → Settings → API, note your Server URL and Password.". Prompts: "BlueBubbles server URL (e.g. http://192.168.1.10:1234)" (required → "Server URL is required — skipping BlueBubbles setup"; trailing slash stripped), "BlueBubbles server password" (hidden, required), "BlueBubbles credentials saved"; security block "🔒 Security: Restrict who can message your bot / Use iMessage addresses: email (user@icloud.com) or phone (+15551234567)"; "Allowed iMessage addresses (comma-separated, leave empty for open access)" → `BLUEBUBBLES_ALLOWED_USERS` or "⚠️  No allowlist set — anyone who can iMessage you can use the bot!"; "📬 Home Channel: phone or email for cron job delivery and notifications." → "Home channel address (leave empty to set later)" → `BLUEBUBBLES_HOME_CHANNEL`; "Advanced settings (defaults are fine for most setups):" → "Configure webhook listener settings?" (default No) → "Webhook listener port (default: 8645)" → `BLUEBUBBLES_WEBHOOK_PORT` (int validated: "Invalid port number, using default 8645"); closing note about the Private API helper bundle URL.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys `BLUEBUBBLES_SERVER_URL`, `BLUEBUBBLES_PASSWORD`, `BLUEBUBBLES_ALLOWED_USERS`, `BLUEBUBBLES_HOME_CHANNEL`, `BLUEBUBBLES_WEBHOOK_PORT`.
- **Config / env:** as above.
- **Edge cases / guards:** The `_PLATFORMS` dict also carries a `vars` schema for BlueBubbles (URL, password, allowlist with DM-pairing hint "hermes pairing generate bluebubbles", home channel) used only for status.
- **Rebuild notes:** 4 prompts + optional advanced port. Better: probe `<url>/api/v1/ping` with the password before saving.

### gateway setup — Telegram wizard  `id: cli-b.gateway.setup.telegram`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `✈️ Telegram` (plugin `plugins/platforms/telegram/adapter.py:11135` `interactive_setup` → `hermes_cli/setup.py:2027` `_setup_telegram`); same in `hermes setup gateway`.
- **What it does:** Creates/links a Telegram bot automatically (managed QR onboarding) or by pasting a BotFather token, then sets the allowlist and home channel.
- **How it works:** `print_header("Telegram")`; existing `TELEGRAM_BOT_TOKEN` → "Telegram: already configured" / "Reconfigure Telegram?" (No → if `TELEGRAM_ALLOWED_USERS` empty: "⚠️  Telegram has no user allowlist - anyone can use your bot!" → "Add allowed users now?" (Yes → hint "   To find your Telegram user ID: message @userinfobot" → "Allowed user IDs (comma-separated)" → saved, "Telegram allowlist configured") → return). Method: "How would you like to create your Telegram bot?" / "  [1] Automatic (recommended) / Scan a QR code → confirm in Telegram → done. / No token copy-paste needed." / "  [2] Manual / Create a bot via @BotFather yourself and paste the token." → `prompt("Choice [1/2]", default="1")`. Automatic → `hermes_cli.telegram_managed_bot.auto_setup_telegram_bot_result(profile_name)` (returns token + owner_user_id; invalid token → "Automatic setup returned an invalid Telegram bot token." → "Falling back to manual setup..."). Manual → `_prompt_telegram_bot_token()`: "Create a bot via @BotFather on Telegram" → "Telegram bot token" (hidden; validated by regex `^\d+:[A-Za-z0-9_-]{30,}$`, else "Invalid token format. Expected: <numeric_id>:<alphanumeric_hash> (e.g., 123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ)" and re-prompt; empty → abort). Saves `TELEGRAM_BOT_TOKEN` ("Telegram token saved"). Security block "🔒 Security: Restrict who can use your bot / 1. Message @userinfobot on Telegram / 2. It will reply with your numeric ID (e.g., 123456789)". If owner id detected: "Detected your Telegram user ID: <id>" → "Allow this Telegram account to use the bot?" (Yes → "Additional allowed user IDs (comma-separated, optional)"; No → "Allowed user IDs (comma-separated, leave empty for open access)"); else the latter prompt. Saves `TELEGRAM_ALLOWED_USERS` ("Telegram allowlist configured - only listed users can use the bot") or "⚠️  No allowlist set - anyone who finds your bot can use it!". Home channel block "📬 Home Channel: where Hermes delivers cron job results, cross-platform messages, and notifications. / For Telegram DMs, this is your user ID (same as above)." → "Use your user ID (<first>) as the home channel?" (Yes → `TELEGRAM_HOME_CHANNEL`) else "Home channel ID (or leave empty to set later with /set-home in Telegram)"; without allowlist: "Home channel ID (leave empty to set later)".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** token regex; managed-bot module optional (ImportError → manual).
- **Rebuild notes:** two acquisition paths + allowlist + home channel. Better: verify the token with `getMe` before saving.

### gateway setup — Discord wizard  `id: cli-b.gateway.setup.discord`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🎮 Discord`; `plugins/platforms/discord/adapter.py:10301-10384` `interactive_setup`.
- **What it does:** Stores the Discord bot token, user allowlist and home channel.
- **How it works:** `print_header("Discord")`; existing token → "Reconfigure Discord?" (No → if no allowlist: "Add allowed users now?" → "Allowed user IDs (comma-separated)" → cleaned ids saved to `DISCORD_ALLOWED_USERS`, "Discord allowlist configured"; return). Prompts: "Discord bot token" (hidden) → `DISCORD_BOT_TOKEN` ("Discord token saved"); allowlist prompt (line 10359) → `DISCORD_ALLOWED_USERS` ("Discord allowlist configured"); "Home channel ID (leave empty to set later with /set-home)" → `DISCORD_HOME_CHANNEL`.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** ids cleaned of `<@…>`/`user:` prefixes.
- **Rebuild notes:** 3 prompts. Better: validate token via the Discord API and offer an invite URL with computed intents.

### gateway setup — Slack wizard  `id: cli-b.gateway.setup.slack`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💼 Slack`; `plugins/platforms/slack/adapter.py:9682-9798` `interactive_setup`.
- **What it does:** Writes the Slack app manifest for you, then stores bot/app tokens, allowlist and home channel.
- **How it works:** `print_header("Slack")`; existing `SLACK_BOT_TOKEN` → "Reconfigure Slack?" (No → "Regenerate the Slack app manifest with the latest command list? (recommended after `hermes update`)" default Yes → `_write_slack_manifest_and_instruct()` → return). Steps info: "1. Go to https://api.slack.com/apps → Create New App / Pick 'From an app manifest' — we'll generate one for you below." / "2. Enable Socket Mode: Settings → Socket Mode → Enable / • Create an App-Level Token with 'connections:write' scope" / "3. Install to Workspace: Settings → Install App" / "4. After installing, invite the bot to channels: /invite @YourBot" / guide URL. `_write_slack_manifest_and_instruct()` writes `$HERMES_HOME/slack-manifest.json` using `hermes_cli.slack_cli._build_full_manifest` ("Slack app manifest written to: <path>" / "Could not write Slack manifest: …"). Prompts: "Slack Bot Token (xoxb-...)" (hidden) → `SLACK_BOT_TOKEN`; "Slack App Token (xapp-...)" (hidden) → `SLACK_APP_TOKEN` ("Slack tokens saved"); allowlist prompt (line 9777) → `SLACK_ALLOWED_USERS` ("Slack allowlist configured") or "⚠️  No Slack allowlist set - unpaired users will be denied by default."; "Home channel ID (leave empty to set later with /set-home)" → `SLACK_HOME_CHANNEL`.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `slack-manifest.json`; `.env` keys `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_USERS`, `SLACK_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** Socket Mode assumed (manifest sets `socket_mode_enabled: true`).
- **Rebuild notes:** manifest-first onboarding. Better: verify tokens with `auth.test` and `apps.connections.open`.

### gateway setup — WhatsApp (Baileys) plugin wizard  `id: cli-b.gateway.setup.whatsapp`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💬 WhatsApp`; `plugins/platforms/whatsapp/adapter.py:1842-1887` `interactive_setup`. (Full QR pairing is the separate `hermes whatsapp` command, `cli-b.whatsapp`.)
- **What it does:** Toggles WhatsApp on/off and sets the allowlist and home chat without pairing.
- **How it works:** `print_header("WhatsApp")`; existing `WHATSAPP_ENABLED` → "Reconfigure WhatsApp?" (No → return). "Enable WhatsApp?" (default Yes) → `WHATSAPP_ENABLED=true` ("WhatsApp enabled") else `false`. "Allowed user IDs (comma-separated, leave empty for no allowlist)" → `WHATSAPP_ALLOWED_USERS` ("WhatsApp allowlist configured"). "Home chat ID for cron delivery (leave empty to skip)" → `WHATSAPP_HOME_CHANNEL`. Points to `hermes whatsapp` for pairing.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `WHATSAPP_ENABLED`, `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_HOME_CHANNEL`, `WHATSAPP_MODE` (set by `hermes whatsapp`).
- **Edge cases / guards:** Enabling without a paired session yields status "enabled, not paired" and a 30 s bridge timeout at gateway start.
- **Rebuild notes:** trivial toggle; better to chain into the pairing flow automatically.

### gateway setup — DingTalk wizard  `id: cli-b.gateway.setup.dingtalk`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🐳 DingTalk`; `plugins/platforms/dingtalk/adapter.py:1774-1824`.
- **What it does:** Obtains Client ID/Secret by QR scan (`hermes_cli/dingtalk_auth.dingtalk_qr_auth`) or manual entry.
- **How it works:** `print_header("DingTalk")`; existing → "DingTalk is already configured (Client ID: <id>)." / "Reconfigure DingTalk?" (No → return). `prompt_choice("Choose setup method", ["QR Code Scan (Recommended, auto-obtain Client ID and Client Secret)", "Manual Input (Client ID and Client Secret)"], 0)`; QR failures → "QR auth module failed to load (…), falling back to manual input." / "QR auth incomplete, falling back to manual input."; saves `DINGTALK_CLIENT_ID`, `DINGTALK_CLIENT_SECRET`, "DingTalk configured via QR scan!" (or manual equivalent).
- **Inputs / options:** the method choice + Client ID / Client Secret prompts.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `DINGTALK_CLIENT_ID`, `DINGTALK_CLIENT_SECRET`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** QR-or-manual credential capture.

### gateway setup — Feishu / Lark wizard  `id: cli-b.gateway.setup.feishu`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🪽 Feishu / Lark`; `plugins/platforms/feishu/adapter.py:5694-5867`.
- **What it does:** Creates or links a Feishu/Lark bot (QR or manual), picks domain and connection mode, and sets DM/group policy and home chat.
- **How it works:** `print_header("Feishu / Lark")`; existing → "Feishu / Lark is already configured." / "Reconfigure Feishu / Lark?". `prompt_choice("How would you like to set up Feishu / Lark?", ["Scan QR code to create a new bot automatically (recommended)", "Enter existing App ID and App Secret manually"], 0)`; QR → `qr_register()` (cancel → "Feishu / Lark setup cancelled."; failure → "QR registration failed: …"). Manual: "App ID" (empty → "Skipped — Feishu / Lark won't work without an App ID."), "App Secret" (hidden), `prompt_choice("Domain", ["feishu (China)", "lark (International)"], 0)`, credential verification ("Credentials verified — bot: <name>" / "Could not verify bot connection. Credentials saved anyway." / "Credential verification skipped: …"). Saves `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_DOMAIN`. `prompt_choice("Connection mode", ["WebSocket (recommended — no public URL needed)", "Webhook (requires a reachable HTTP endpoint)"], 0)` → `FEISHU_CONNECTION_MODE` (webhook prints defaults "127.0.0.1:8765/feishu/webhook", overrides `FEISHU_WEBHOOK_HOST/PORT/PATH`, and `FEISHU_ENCRYPT_KEY`/`FEISHU_VERIFICATION_TOKEN` for signatures). "Bot created: <name>" on QR. `prompt_choice("How should direct messages be authorized?", ["Use DM pairing approval (recommended)", "Allow all direct messages", "Only allow listed user IDs"], 0)` → `FEISHU_ALLOW_ALL_USERS` + `FEISHU_ALLOWED_USERS`. `prompt_choice("How should group chats be handled?", ["Respond only when @mentioned in groups (recommended)", "Disable group chats"], 0)` → `FEISHU_GROUP_POLICY` open|disabled. "Home chat ID (optional, for cron/notifications)" → `FEISHU_HOME_CHANNEL`. Ends "🪽 Feishu / Lark configured!".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `FEISHU_*` keys above.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — WeCom (Enterprise WeChat) wizard  `id: cli-b.gateway.setup.wecom`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💼 WeCom (Enterprise WeChat)`; `plugins/platforms/wecom/adapter.py:3414-3526`.
- **What it does:** Obtains Bot ID/Secret by QR or manually, sets allowlist/DM policy and home chat.
- **How it works:** `print_header("WeCom (Enterprise WeChat)")`; existing → "WeCom is already configured." / "Reconfigure WeCom?". `prompt_choice("How would you like to set up WeCom?", ["Scan QR code to obtain Bot ID and Secret automatically (recommended)", "Enter existing Bot ID and Secret manually"], 0)` (QR cancel/failure messages; success "✔ QR scan successful! Bot ID and Secret obtained."). Manual: "Bot ID", "Secret" (hidden) with skip warnings. Saves `WECOM_BOT_ID`, `WECOM_SECRET`. "Allowed user IDs (comma-separated, or empty)" → `WECOM_ALLOWED_USERS` ("Saved — only these users can interact with the bot.") else `prompt_choice("How should unauthorized users be handled?", ["Enable open access (anyone can message the bot)", "Use DM pairing (unknown users request access, you approve with 'hermes pairing approve')", "Disable direct messages", "Skip for now (bot will deny all users until configured)"], 1)` → `WECOM_DM_POLICY` open (+ `GATEWAY_ALLOW_ALL_USERS=true`, "Open access enabled — anyone can use your bot!") | pairing ("DM pairing mode — users will receive a code to request access.") | disabled ("Direct messages disabled."). "Home chat ID (optional, for cron/notifications)" → `WECOM_HOME_CHANNEL`. Ends "💬 WeCom configured!".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `WECOM_*`, `GATEWAY_ALLOW_ALL_USERS`.
- **Edge cases / guards:** The separate "WeCom Callback (self-built apps)" platform has no wizard (env hint: `WECOM_CALLBACK_CORP_ID`, `WECOM_CALLBACK_CORP_SECRET`).
- **Rebuild notes:** as above.

### gateway setup — Matrix wizard  `id: cli-b.gateway.setup.matrix`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🔐 Matrix` (hidden on Windows); `plugins/platforms/matrix/adapter.py:5272-5373`.
- **What it does:** Configures homeserver + token-or-password login, optional E2EE (installs the `mautrix[encryption]` extra), allowlist, home room.
- **How it works:** `print_header("Matrix")`; existing → "Reconfigure Matrix?". "Homeserver URL (e.g. https://matrix.example.org)" → `MATRIX_HOMESERVER`; "Access token (leave empty for password login)" (hidden) → `MATRIX_ACCESS_TOKEN` + optional "User ID (@bot:server — optional, will be auto-detected)" → `MATRIX_USER_ID` ("Matrix access token saved"), or password path: "User ID (@bot:server)" + "Password" (hidden) → `MATRIX_USER_ID`, `MATRIX_PASSWORD` ("Matrix credentials saved"). "Enable end-to-end encryption (E2EE)?" (default No) → `MATRIX_ENCRYPTION=true` ("E2EE enabled") and pip-installs the matrix package ("<pkg> installed" / warning). "Allowed user IDs (comma-separated, leave empty for open access)" → `MATRIX_ALLOWED_USERS` ("Matrix allowlist configured"). "Home room ID (leave empty to set later with /set-home)" → `MATRIX_HOME_ROOM`.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys; possible pip install.
- **Config / env:** `MATRIX_*` keys above.
- **Edge cases / guards:** Windows excluded (python-olm).
- **Rebuild notes:** as above.

### gateway setup — IRC wizard  `id: cli-b.gateway.setup.irc`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💬 IRC`; `plugins/platforms/irc/adapter.py:564-668`.
- **What it does:** Configures server, TLS, port, nickname, channel, optional server/NickServ passwords and access policy.
- **How it works:** `print_header("IRC")`; existing → "Reconfigure IRC?". Prompts: "IRC server hostname (e.g. irc.libera.chat)" (required → "Server is required — skipping IRC setup") → `IRC_SERVER`; "Use TLS (recommended)?" (Yes) → `IRC_USE_TLS`; "Port (default <6697|6667>)" → `IRC_PORT` (int; "Invalid port — using default N"); nickname prompt (line 612; required) → `IRC_NICKNAME`; channel prompt (line 621; required) → `IRC_CHANNEL`; "Configure a server password (PASS command)?" (No) → "Server password" (hidden) → `IRC_SERVER_PASSWORD`; "Identify with NickServ on connect?" (No) → "NickServ password" → `IRC_NICKSERV_PASSWORD`; "Allow all users in the channel to talk to the bot?" (No) → `IRC_ALLOW_ALL_USERS=true` + "⚠️  Open access — any nick in the channel can command the bot." or allowlist prompt (line 655) → `IRC_ALLOWED_USERS` ("Allowlist configured"). Ends "IRC configuration saved to ~/.hermes/.env".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys `IRC_SERVER`, `IRC_USE_TLS`, `IRC_PORT`, `IRC_NICKNAME`, `IRC_CHANNEL`, `IRC_SERVER_PASSWORD`, `IRC_NICKSERV_PASSWORD`, `IRC_ALLOW_ALL_USERS`, `IRC_ALLOWED_USERS`.
- **Config / env:** as above.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — LINE wizard  `id: cli-b.gateway.setup.line`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💚 LINE`; `plugins/platforms/line/adapter.py:1688-1727`.
- **What it does:** Prompts for the four LINE env vars (secrets masked) and saves non-empty answers.
- **How it works:** local `_prompt(var, prompt, secret)` shows the current value as `[…]` suffix, reads via `masked_secret_prompt` or `input`, saves when non-empty. Prompts: "Channel access token" (secret) → `LINE_CHANNEL_ACCESS_TOKEN`; "Channel secret" (secret) → `LINE_CHANNEL_SECRET`; "Public HTTPS base URL (optional, e.g. https://my-tunnel.example.com)" → `LINE_PUBLIC_URL`; "Allowed user IDs (comma-separated; blank=skip)" → `LINE_ALLOWED_USERS`.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `LINE_*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — SimpleX Chat wizard  `id: cli-b.gateway.setup.simplex`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🔒 SimpleX Chat`; `plugins/platforms/simplex/adapter.py:1293-1346`.
- **What it does:** Prompts for the SimpleX daemon URL, allowlists, auto-accept and home channel.
- **How it works:** same `_prompt` helper. Prompts: "Daemon WebSocket URL (default ws://127.0.0.1:5225)" → `SIMPLEX_WS_URL`; "Allowed contactIds or display names (comma-separated; blank=skip)" → `SIMPLEX_ALLOWED_USERS`; "Allowed group IDs (comma-separated, or '*' for any; blank=disable groups)" → `SIMPLEX_GROUP_ALLOWED`; "Auto-accept incoming contact requests? (true/false, default true)" → `SIMPLEX_AUTO_ACCEPT`; "Home channel contact/group ID (or empty)" → `SIMPLEX_HOME_CHANNEL`.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `SIMPLEX_*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — Microsoft Teams wizard  `id: cli-b.gateway.setup.teams`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💼 Microsoft Teams`; `plugins/platforms/teams/adapter.py:1536-1604`.
- **What it does:** Stores Azure app Client ID/Secret/Tenant ID and access policy.
- **How it works:** existing → "Reconfigure Teams?". "Client ID" (required → "Client ID is required — skipping Teams setup") → `TEAMS_CLIENT_ID`; "Client secret" (hidden, required) → `TEAMS_CLIENT_SECRET`; "Tenant ID" (required) → `TEAMS_TENANT_ID`; "Restrict access to specific users? (recommended)" (Yes) → allowlist prompt (line 1588) → `TEAMS_ALLOWED_USERS` ("Allowlist configured") else `TEAMS_ALLOWED_USERS=""` + `TEAMS_ALLOW_ALL_USERS=true` + "⚠️  Open access — anyone who can message the bot can command it.". Ends "Teams configuration saved to ~/.hermes/.env".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `TEAMS_*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — Google Chat wizard  `id: cli-b.gateway.setup.google-chat`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `💬 Google Chat`; `plugins/platforms/google_chat/adapter.py:3434-3523`.
- **What it does:** Stores GCP project, Pub/Sub subscription, service-account JSON path, access policy and home space.
- **How it works:** existing → "Reconfigure Google Chat?". Prompts (lines 3474-3519): project ID (required → "Project ID is required — skipping Google Chat setup") → `GOOGLE_CHAT_PROJECT_ID`; subscription (required) → `GOOGLE_CHAT_SUBSCRIPTION_NAME`; service-account JSON path → `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON`; "Restrict access to specific users? (recommended)" (Yes) → allowlist → `GOOGLE_CHAT_ALLOWED_USERS` else `GOOGLE_CHAT_ALLOW_ALL_USERS=true` + "⚠️  Open access — anyone who can DM the bot can command it."; home prompt → `GOOGLE_CHAT_HOME_CHANNEL`. Ends "Google Chat configuration saved to ~/.hermes/.env".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `GOOGLE_CHAT_*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — Buzz (Nostr) wizard  `id: cli-b.gateway.setup.buzz`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🐝 Buzz`; `plugins/platforms/buzz/adapter.py:3290-3364`.
- **What it does:** Stores relay URL, Nostr private key, channels, home channel and access policy.
- **How it works:** `print_header("Buzz")`; existing → "Reconfigure Buzz?". Relay prompt (line 3318; required → "Relay URL is required — skipping Buzz setup") → `BUZZ_RELAY_URL`; "Nostr private key (nsec or hex; leave blank to keep current)" (hidden) → `BUZZ_PRIVATE_KEY` (blank without existing → "No private key configured — set BUZZ_PRIVATE_KEY before starting the gateway"); channels prompt (line 3333) → `BUZZ_CHANNELS`; home prompt (line 3340) → `BUZZ_HOME_CHANNEL`; "Allow all community members to talk to the agent?" (No) → `BUZZ_ALLOW_ALL_USERS=true` + warning, else allowlist (line 3356) → `BUZZ_ALLOWED_USERS`. Ends "Buzz configuration saved to ~/.hermes/.env".
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `BUZZ_*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — Raft wizard  `id: cli-b.gateway.setup.raft`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🔔 Raft`; `plugins/platforms/raft/adapter.py:787-826`.
- **What it does:** Stores the Raft profile slug.
- **How it works:** `print_header("Raft")`; existing → "Reconfigure Raft?"; "Raft profile slug" (required → "Raft profile slug is required; skipping Raft setup") → `RAFT_PROFILE`; "Raft configuration saved".
- **Inputs / options:** one prompt.
- **Outputs / side effects:** `.env` `RAFT_PROFILE`.
- **Config / env:** `RAFT_PROFILE`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** as above.

### gateway setup — A2A (Agent-to-Agent) wizard  `id: cli-b.gateway.setup.a2a`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `🧩 A2A`; `plugins/platforms/a2a/__init__.py:47-94`.
- **What it does:** Configures the inbound A2A port, advertised agent name, peer/bearer tokens and bind host.
- **How it works:** `print_header("A2A (Agent-to-Agent)")` + "Expose Hermes as an A2A-discoverable agent and call other A2A agents." + "Uses Python stdlib — no extra packages needed."; "Inbound A2A port (default 9900)" → `A2A_PORT` ("Invalid port — using default 9900"); "Agent name to advertise (blank = hostname-derived)" → `A2A_AGENT_NAME`; security note ("with NO token configured the server binds to 127.0.0.1 only", prefer `A2A_PEER_TOKENS="alice:tok1,bob:tok2"`); "Configure tokens to allow REMOTE A2A peers?" (No) → "Per-peer tokens (name:token, comma-separated; blank to skip)" → `A2A_PEER_TOKENS`; "Shared bearer token (blank to skip)" (hidden) → `A2A_BEARER_TOKEN`; "Bind host for remote access (e.g. 0.0.0.0)" → `A2A_HOST`; "No tokens entered — staying localhost-only." otherwise.
- **Inputs / options:** prompts above.
- **Outputs / side effects:** `.env` keys.
- **Config / env:** `A2A_PORT`, `A2A_AGENT_NAME`, `A2A_PEER_TOKENS`, `A2A_BEARER_TOKEN`, `A2A_HOST`.
- **Edge cases / guards:** Live status shows A2A "configured (plugin)" even with nothing set (its `check_fn` needs no env).
- **Rebuild notes:** as above.

### gateway setup — iMessage via Photon wizard  `id: cli-b.gateway.setup.photon`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `📱 iMessage via Photon`; `plugins/platforms/photon/cli.py:513` `gateway_setup` → `_cmd_setup(Namespace(photon_command="setup", project_name=None, phone=None, first_name=None, last_name=None, email=None, no_browser=False, skip_sidecar_install=False))`.
- **What it does:** Runs the Photon `setup` sub-command (account/project creation + sidecar install) with all defaults.
- **How it works:** delegation only; the Photon CLI (`hermes photon …`, registered via `setup_fn=_cli.register_cli`) is owned by the platform/plugin shard.
- **Inputs / options:** none here.
- **Outputs / side effects:** `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET` (per registry `required_env`).
- **Config / env:** as above.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** handoff.

### gateway setup — env-hint platforms (Email, Home Assistant, ntfy, SMS, WeCom Callback)  `id: cli-b.gateway.setup.envhint`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → `📧 Email`, `🏠 Home Assistant`, `🔔 ntfy`, `📱 SMS (Twilio)`, `💼 WeCom Callback (self-built apps)`.
- **What it does:** For registry platforms without a `setup_fn`, prints where to configure them instead of prompting.
- **How it works:** `_configure_platform` fallback (`hermes_cli/gateway.py:7861-7876`): "  ─── <emoji> <label> Setup ───", then "  Set these env vars in ~/.hermes/.env: <required_env>" or "  Configure <label> in config.yaml under gateway.platforms.<key>", plus the plugin's `install_hint`. Required env per live registry: Email `EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_HOST`; Home Assistant `HASS_TOKEN`; ntfy `NTFY_TOPIC`; SMS `TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER`; WeCom Callback `WECOM_CALLBACK_CORP_ID, WECOM_CALLBACK_CORP_SECRET`.
- **Inputs / options:** none.
- **Outputs / side effects:** informational.
- **Config / env:** listed above.
- **Edge cases / guards:** Email/SMS gain interactive prompts only through `hermes setup --quick` messaging checklist (Telegram/Discord/Slack only) — not here.
- **Rebuild notes:** better: generate a generic prompt loop from `required_env` instead of a hint.

### gateway setup — post-setup service block  `id: cli-b.gateway.setup.post-setup-service`
- **Surface:** CLI
- **Where:** end of `hermes gateway setup` (`hermes_cli/gateway.py:7962-8135`) once any platform shows progress.
- **What it does:** Restarts, starts, or installs the gateway service to pick up the new platform config.
- **How it works:** Service running → (root-needed system scope: remediation text) else "  Restart the gateway to pick up changes?" (Yes → `systemd_restart()` / `launchd_restart()` / `gateway_windows.restart()` / else `stop_profile_gateway()` + "Start manually: hermes gateway"). Installed but stopped → "  Start the gateway service?" (Yes → start). Not installed on systemd/macOS/Windows → "  Start the gateway now?" (Yes) and "  Start the gateway automatically on login/boot as a systemd|launchd|Scheduled Task service?[ (note: services may not survive WSL restarts)]" (Yes); if either yes → Linux `install_linux_gateway_from_setup(force=False, enable_on_startup=start_on_login)` (`cli-b.gateway.setup.linux-scope-prompt`), macOS `launchd_install`, Windows `gateway_windows.install`, then start if requested; both no → "  Skipped start and auto-start setup." + later-install hints (`hermes gateway install`, `sudo hermes gateway install --system`, `hermes gateway run`). WSL without systemd / Termux / unsupported → guidance lines only. Errors: `UserSystemdUnavailableError` → "  Restart failed — user systemd not reachable:" etc.; `CalledProcessError` → "  Install failed: … / You can try manually: hermes gateway install".
- **Inputs / options:** yes/no prompts above.
- **Outputs / side effects:** service install/start/restart.
- **Config / env:** n/a.
- **Edge cases / guards:** Uses `_system_scope_wizard_would_need_root()` to avoid raising inside the wizard.
- **Rebuild notes:** three-state reconcile (running/installed/none). Better: show a diff of platform changes before offering restart.

### gateway setup — Linux service scope prompt  `id: cli-b.gateway.setup.linux-scope-prompt`
- **Surface:** CLI
- **Where:** `prompt_linux_gateway_install_scope()` / `install_linux_gateway_from_setup()` (`hermes_cli/gateway.py:3394-3460`), reached from gateway setup, `hermes setup gateway` (via `ensure_gateway_service`? no — via the wizard block) and quick setup.
- **What it does:** Asks whether the gateway should be a user service or (root only) a boot-time system service.
- **How it works:** Non-root: `prompt_choice("  Choose how the gateway should run in the background:", ["User service (no sudo; best for laptops/dev boxes; may need linger after logout)", "Skip service install for now"], 0)`; picking user prints "  Tip: for a boot-time system service, re-run setup as root (e.g. from a root shell or `sudo -i`)." Root: third option "System service (starts on boot; runs as your chosen user)"; system scope resolves `run_as_user` via `_default_system_service_user()` or asks "  Run the system gateway service as which user?" (loops until non-empty, "  Enter a username."), then `systemd_install(system=True, run_as_user=…)`. Returns `(scope, did_install)`.
- **Inputs / options:** the choice + username.
- **Outputs / side effects:** unit installed.
- **Config / env:** n/a.
- **Edge cases / guards:** never prints a self-elevation recipe for non-root.
- **Rebuild notes:** as above.

### gateway — non-interactive service reconcile (ensure_gateway_service)  `id: cli-b.gateway.ensure-service`
- **Surface:** Core
- **Where:** `hermes_cli/gateway.py:3463-3549` `ensure_gateway_service(context="setup")`; called by `hermes setup gateway`, quick setup when messaging is skipped, and post-migration flows.
- **What it does:** Installs a user-scope service if none exists and starts it, without asking questions.
- **How it works:** Container → prints "Start the gateway to bring your bots online:" + `hermes gateway run` + docker restart-policy hint, returns False. No service manager → "  No supported service manager found on this host. / Run the gateway in the foreground with: hermes gateway" → False. Otherwise if not installed: warns on scope conflict, "  Installing the gateway background service ...", `systemd_install(force=False, non_interactive=True)` / `launchd_install(False)` / `gateway_windows.install(False)` ("  Gateway service installed and started."); then start; "  Gateway service running (cron jobs + messaging platforms)." Errors: "  Could not reach user systemd to start the gateway service:" / "  Gateway service needs root for this scope: …".
- **Inputs / options:** none.
- **Outputs / side effects:** service installed/started.
- **Config / env:** n/a.
- **Edge cases / guards:** never raises; never self-elevates.
- **Rebuild notes:** idempotent "make sure something supervises the gateway".

### hermes gateway migrate-legacy  `id: cli-b.gateway.migrate-legacy`
- **Surface:** CLI
- **Where:** `hermes gateway migrate-legacy [--dry-run] [-y|--yes]`; help "Remove legacy hermes.service units from pre-rename installs".
- **What it does:** Stops, disables and deletes old `hermes.service` unit files (user and system scope) that predate the `hermes-gateway.service` rename and would otherwise fight the new unit for the same bot token.
- **How it works:** `hermes_cli/gateway.py:8995-9004` → `remove_legacy_hermes_units(interactive=not yes, dry_run)` (`gateway.py:3213-3312`). Detection `_find_legacy_hermes_units` (`gateway.py:3151`): allowlisted names `_LEGACY_SERVICE_NAMES=("hermes.service",)` in `~/.config/systemd/user` and `/etc/systemd/system`, only if the file contains one of `_LEGACY_UNIT_EXECSTART_MARKERS` (`"hermes_cli.main gateway"`, `"hermes_cli/main.py gateway"`, `"gateway/run.py"`, …). Output: "No legacy Hermes gateway units found." or "Legacy Hermes gateway unit(s) found:" + "  <path>  (user|system scope)"; `--dry-run` → "(dry-run — nothing removed)"; interactive → "Remove these legacy units?" (default Yes; No → "Skipped. Run again with: hermes gateway migrate-legacy"). Removal: user units `systemctl --user stop/disable`, unlink, "  ✓ Removed <path>", `daemon-reload`; system units require root ("System-scope legacy units require root to remove. / Re-run with: sudo hermes gateway migrate-legacy") else same with `systemctl`. Summary "Removed N legacy unit(s)." or "N legacy unit(s) still present — see messages above." Non-systemd/non-macOS hosts: "Legacy unit migration only applies to systemd-based Linux hosts."
- **Inputs / options:** `--dry-run`, `-y/--yes`.
- **Outputs / side effects:** unit files deleted; systemd reloaded.
- **Config / env:** n/a.
- **Edge cases / guards:** Profile units and third-party `hermes-*` services are never matched; also offered automatically by `gateway install`, and warned about by `gateway status`/`gateway setup` (`print_legacy_unit_warning`).
- **Rebuild notes:** allowlist + content-signature detection before deletion. Better: keep a backup copy of removed units.

### hermes gateway enroll (relay connector enrollment)  `id: cli-b.gateway.enroll`
- **Surface:** CLI
- **Where:** `hermes gateway enroll [--token TOKEN] [--connector-url URL] [--gateway-id ID] [--wake-url URL]`; help "Enroll this gateway with a relay connector (writes relay auth creds to .env)". EXPERIMENTAL.
- **What it does:** Redeems a single-use enrollment token at a relay connector, receiving this gateway's per-gateway secret and the tenant's delivery key, and persists them to `.env`.
- **How it works:** `hermes_cli/gateway_enroll.py:162-291` `cmd_gateway_enroll`. Managed install → "✗ `hermes gateway enroll` is not available in a managed/hosted install." exit 1. Token from `--token` or `GATEWAY_RELAY_ENROLL_TOKEN` (missing → "✗ No enrollment token. Pass --token <token> (or set GATEWAY_RELAY_ENROLL_TOKEN)…" exit 1). Connector URL via `_resolve_connector_url` (`gateway_enroll.py:59`): `--connector-url` > `GATEWAY_RELAY_URL` env > `gateway.relay_url` in config.yaml; `ws://`→`http://`, `wss://`→`https://`, trailing `/relay` stripped (missing → "✗ No connector URL…" exit 1). Gateway id: `--gateway-id` or `gw-<hostname>` (`_default_gateway_id`). Identity token via `gateway.relay._resolve_relay_identity_token()` (`cli-b.gateway.enroll.identity-token`); `AuthError(relogin_required)` → "✗ You're not logged into Nous Portal. / Run `hermes setup` (or `hermes auth add nous`) first, then retry." exit 1. `_post_enroll` (`gateway_enroll.py:104`): `POST <base>/relay/enroll` JSON `{"enrollmentToken","gatewayId"}` with `Authorization: Bearer <identity>`, 15 s timeout; 401 → "Connector rejected the caller identity (401)…try `hermes auth add nous`"; 403 → connector error or "Enrollment token invalid, expired, already used, or tenant mismatch (403)."; other → "Connector returned HTTP N: …"; URLError → "Could not reach the connector at <url>: …"; no `secret` → "Connector returned an unexpected response (no secret)." Response `{secret, deliveryKey, tenant, gatewayId}`. Writes via `save_env_value`: `GATEWAY_RELAY_ID`, `GATEWAY_RELAY_SECRET`, `GATEWAY_RELAY_DELIVERY_KEY`, plus `GATEWAY_RELAY_URL` (only when `--connector-url` given, stored as passed minus trailing `/`) and `GATEWAY_RELAY_WAKE_URL` (when `--wake-url`). Prints "✓ Enrolled gateway "<id>" for tenant <t>", "  Wrote to <env path>:" with `GATEWAY_RELAY_ID=…`, `GATEWAY_RELAY_SECRET=<hidden>`, `GATEWAY_RELAY_DELIVERY_KEY=<hidden>`, optional URL lines, then either the secondary-profile warning (`_warn_if_secondary_multiplex_profile`: HERMES_HOME under `<root>/profiles/` AND multiplexing on → "⚠ This profile is a SECONDARY profile of a multiplexed gateway. GATEWAY_RELAY_URL / GATEWAY_RELAY_WAKE_URL are process-level deployment settings…") or "The gateway now authenticates its relay WS upgrade with the per-gateway secret and verifies signed inbound deliveries with the tenant delivery key. Restart the gateway to pick up the new env."
- **Inputs / options:** `--token`, `--connector-url`, `--gateway-id`, `--wake-url` (a payload-free GET URL the connector pokes to wake an idle gateway).
- **Outputs / side effects:** `.env` writes; network POST.
- **Config / env:** `GATEWAY_RELAY_ENROLL_TOKEN`, `GATEWAY_RELAY_URL`, `gateway.relay_url`, `GATEWAY_RELAY_ID`, `GATEWAY_RELAY_SECRET`, `GATEWAY_RELAY_DELIVERY_KEY`, `GATEWAY_RELAY_WAKE_URL`, `GATEWAY_MULTIPLEX_PROFILES`.
- **Edge cases / guards:** Empty values are skipped; write failure → "✗ Failed to write KEY to .env: …" exit 1.
- **Rebuild notes:** OAuth-authenticated one-shot enrollment → secrets in .env. Better: store secrets in the OS keychain and print a verification `curl` for the wake URL.

### gateway enroll — caller-identity token resolution  `id: cli-b.gateway.enroll.identity-token`
- **Surface:** Core
- **Where:** `gateway/relay/__init__.py:521` `_resolve_relay_identity_token()` (shared by `gateway enroll` and runtime self-provision).
- **What it does:** Produces the bearer token proving which tenant the gateway belongs to.
- **How it works:** Mode 1 — generic OIDC client-credentials when `GATEWAY_RELAY_IDP_TOKEN_URL` (or config `gateway.idp.token_url`) plus `GATEWAY_RELAY_IDP_CLIENT_ID`/`GATEWAY_RELAY_IDP_CLIENT_SECRET` (or `gateway.idp.client_id`/`client_secret`, optional `scope`) are set: POST `grant_type=client_credentials`. Mode 1b — ambient token endpoint when `token_url` is set with neither id nor secret: plain GET whose body is the token (raw JWT or JSON `access_token`). Mode 2 (default) — `hermes_cli.auth.resolve_nous_access_token()` from `~/.hermes/auth.json`.
- **Inputs / options:** env/config only.
- **Outputs / side effects:** none.
- **Config / env:** `GATEWAY_RELAY_IDP_TOKEN_URL`, `GATEWAY_RELAY_IDP_CLIENT_ID`, `GATEWAY_RELAY_IDP_CLIENT_SECRET`, `GATEWAY_RELAY_IDP_SCOPE`, `gateway.idp.{token_url,client_id,client_secret,scope}` (not in DEFAULT_CONFIG; optional).
- **Edge cases / guards:** Raises on failure; enroll treats it as fatal.
- **Rebuild notes:** precedence chain env > config > Nous login.

### gateway — s6 container service-manager dispatch  `id: cli-b.gateway.s6-dispatch`
- **Surface:** Core
- **Where:** `_dispatch_via_service_manager_if_s6(action, profile)` / `_dispatch_all_via_service_manager_if_s6(action)` (`hermes_cli/gateway.py:8141-8241`).
- **What it does:** Inside the s6-overlay Docker image, routes `start`/`stop`/`restart` (and `--all` for stop/restart) to the per-profile s6 longrun `gateway-<profile>` instead of systemd/launchd/pkill.
- **How it works:** `hermes_cli.service_manager.detect_service_manager() == "s6"`; profile = `_profile_suffix()` or `"default"`; `get_service_manager().start|stop|restart("gateway-<profile>")`; `GatewayNotRegisteredError`/`S6CommandError` → "✗ <msg>" exit 1. `--all` iterates `list_profile_gateways()`; prints "✓ Stopped|Restarted N profile gateway(s) under s6" and "✗ Could not <action> gateway-<p>: <err>"; "✗ No profile gateways registered under s6" when none.
- **Inputs / options:** n/a.
- **Outputs / side effects:** s6 service state.
- **Config / env:** n/a.
- **Edge cases / guards:** `start --all` is not an s6 surface (falls through).
- **Rebuild notes:** supervisor abstraction with `start/stop/restart/list`.

### gateway — service naming and paths per profile  `id: cli-b.gateway.service-naming`
- **Surface:** Core
- **Where:** `get_service_name()`, `get_systemd_unit_path()`, `_profile_suffix()`, `_profile_arg()` (`hermes_cli/gateway.py:2746-2835`); `get_launchd_label()`/`get_launchd_plist_path()` (`gateway.py:4905`/`3626`); `get_task_name()` (`gateway_windows.py:294`).
- **What it does:** Derives per-profile service identifiers so several profiles can run side by side.
- **How it works:** `_SERVICE_BASE="hermes-gateway"`; suffix "" for the default root, the profile name for `<root>/profiles/<name>` (regex `^[a-z0-9][a-z0-9_-]{0,63}$`), else an 8-char sha256 of the path → `hermes-gateway`, `hermes-gateway-coder`, `hermes-gateway-1a2b3c4d`. Unit paths `~/.config/systemd/user/<name>.service` or `/etc/systemd/system/<name>.service`. `_profile_arg()` yields `--profile <name>` for ExecStart only for named profiles. Windows task `Hermes_Gateway[_<suffix>]`; script `%HERMES_HOME%\gateway-service\<task>.cmd`.
- **Inputs / options:** `HERMES_HOME`.
- **Outputs / side effects:** n/a.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** hash fallback keeps arbitrary homes unique.
- **Rebuild notes:** deterministic naming from the home path.


### hermes proxy (command group)  `id: cli-b.proxy`
- **Surface:** CLI
- **Where:** `hermes proxy [-h] {start,status,providers}`; description "Run a local HTTP server that forwards OpenAI-compatible requests to an OAuth-authenticated provider (e.g. Nous Portal). External apps can point at the proxy with any bearer token; the proxy attaches your real credentials."; top-level `hermes --help` row "Local OpenAI-compatible proxy to OAuth providers".
- **What it does:** Runs a credential-attaching localhost forwarder so third-party OpenAI-compatible apps (OpenViking, Karakeep, Open WebUI, …) can ride your logged-in Nous/xAI subscription without ever seeing a real key.
- **How it works:** Parser is built inside the gateway subcommand module — `hermes_cli/subcommands/gateway.py:316-353` (`proxy_parser`, `dest="proxy_command"`). Handler `hermes_cli/main.py:3519` (`cmd_proxy`) lazily imports `hermes_cli/proxy/cli.py:109` (`cmd_proxy`) and re-raises a non-zero return as `SystemExit(rc)`. Dispatch table in `proxy/cli.py:111-117`: `start`→`cmd_proxy_start`, `status`→`cmd_proxy_status`, `providers` **or** the undocumented alias `list`→`cmd_proxy_list_providers`. With no sub-command it prints a 10-line usage block to stderr and returns 0.
- **Inputs / options:** `-h/--help`; sub-commands `start`, `status`, `providers` (plus hidden alias `list` accepted by the dispatcher but not registered in argparse, so `hermes proxy list` fails at parse time and only reaches the dispatcher when `proxy_command` is set programmatically).
- **Outputs / side effects:** No-subcommand help text on stderr:
  ```
  hermes proxy — local OpenAI-compatible proxy that attaches your
  OAuth-authenticated provider credentials to outbound requests.

  Subcommands:
    hermes proxy start [--provider nous|xai] [--host 127.0.0.1] [--port 8645]
        Run the proxy in the foreground.
    hermes proxy status
        Show which upstream adapters are ready.
    hermes proxy providers
        List available upstream providers.
  ```
- **Config / env:** none directly; adapters read `~/.hermes/auth.json` and `NOUS_INFERENCE_BASE_URL`.
- **Edge cases / guards:** Every path first checks `AIOHTTP_AVAILABLE` (`proxy/server.py:19-26`); when aiohttp is missing `start` prints "hermes proxy requires aiohttp. Run `hermes setup` to install it." to stderr and returns 1.
- **Rebuild notes:** argparse group + adapter registry + aiohttp reverse proxy. A better version would daemonize (`proxy start --detach`), expose a `/metrics` endpoint, and support per-app API keys so the proxy can attribute usage per client.

### hermes proxy start  `id: cli-b.proxy.start`
- **Surface:** CLI
- **Where:** `hermes proxy start [-h] [--provider PROVIDER] [--host HOST] [--port PORT]`; help row "Run the proxy in the foreground".
- **What it does:** Binds an aiohttp server on `http://<host>:<port>` that forwards `/v1/*` to the selected provider with your real bearer attached, and `/health` locally. Runs until Ctrl+C.
- **How it works:** `hermes_cli/proxy/cli.py:28-73`. Steps: (1) aiohttp guard; (2) `get_adapter(provider or "nous")` (`proxy/adapters/__init__.py:22-34`) — unknown name → `ValueError` → `"Error: Unknown proxy upstream provider: 'x'. Available: nous, xai"` on stderr, exit 2; (3) `adapter.is_authenticated()` false → prints "Not logged into <display_name>. Run `<auth_hint>` first." (hint = `adapter.auth_hint` if defined, else `hermes auth add <adapter.name>`; the xAI adapter defines `auth_hint = "hermes auth add xai-oauth --type oauth"`, `proxy/adapters/xai.py:34`), exit 2; (4) prints the banner to stderr; (5) `asyncio.run(run_server(adapter, host, port))` (`proxy/server.py:246`). Server app (`proxy/server.py:88-243`): `web.Application(client_max_size=10_000_000)`, routes `GET /health` and `* /v1/{tail:.*}`. Per request: relative path must be in `adapter.allowed_paths` else 404 JSON `{"error":{"message":"Path /v1<p> is not forwarded by this proxy. Allowed: …","type":"path_not_allowed","code":"path_not_allowed"}}`; `adapter.get_credential()` failure → 401 `upstream_auth_failed`; body read fully into memory; hop-by-hop + `authorization` headers stripped (`host, content-length, connection, keep-alive, proxy-authenticate, proxy-authorization, te, trailers, transfer-encoding, upgrade, authorization`); `Authorization: <token_type> <bearer>` set; query string preserved verbatim; `ClientTimeout(total=None, sock_connect=15, sock_read=300)`; `allow_redirects=False`. On upstream 401/429 it calls `adapter.get_retry_credential(...)` once and replays. Response streamed back with `StreamResponse` + `content.iter_any()` (SSE preserved); `content-encoding`/`content-length` also stripped from the response. Errors: `ClientError` → 502 `upstream_unreachable`, `asyncio.TimeoutError` → 504 `upstream_timeout`, session-init `RuntimeError` → 500. `run_server` installs SIGINT/SIGTERM handlers when it owns the loop (NotImplementedError on Windows is swallowed).
- **Inputs / options:** `-h/--help`; `--provider PROVIDER` (default `"nous"`; help "Upstream provider: nous or xai (default: nous). See `hermes proxy providers`."); `--host HOST` (default None → `DEFAULT_HOST` `127.0.0.1`; help "Bind address (default: 127.0.0.1). Use 0.0.0.0 to expose on LAN."); `--port PORT` (int, default None → `DEFAULT_PORT` `8645`; help "Bind port (default: 8645)").
- **Outputs / side effects:** Startup banner on stderr:
  ```
  Starting Hermes proxy for <display_name>
    Listening on:  http://<host>:<port>/v1
    Forwarding to: (resolved per-request from your subscription)
    Use any bearer token in the client — the proxy attaches your real credential.

  Press Ctrl+C to stop.
  ```
  Ctrl+C prints "\nproxy: stopped"; a bind failure prints "proxy: failed to bind <host>:<port>: <err>" and returns 1. `GET /health` returns `{"status":"ok","upstream":"<display_name>","authenticated":<bool>}`. May persist refreshed Nous tokens back into `~/.hermes/auth.json` (see the Nous adapter).
- **Config / env:** `NOUS_INFERENCE_BASE_URL` (dev/staging override honoured by the Nous adapter), `HERMES_HOME` (auth store location).
- **Edge cases / guards:** Request bodies over 10 MB are rejected by aiohttp's `client_max_size`. The proxy never logs or rewrites bodies. Binding `0.0.0.0` exposes an unauthenticated credential-attaching endpoint on the LAN — any bearer is accepted and discarded.
- **Rebuild notes:** aiohttp catch-all route + allowlist + header filter + single-retry credential rotation. A better version would authenticate clients (per-app tokens), rate-limit, and add structured request logging with token redaction.

### hermes proxy status  `id: cli-b.proxy.status`
- **Surface:** CLI
- **Where:** `hermes proxy status [-h]`; help "Show which proxy upstreams are ready".
- **What it does:** Prints one line per registered adapter saying whether it is logged in and, when known, when its bearer expires.
- **How it works:** `hermes_cli/proxy/cli.py:76-97`. Header "Hermes proxy upstream adapters" + blank line; then for each name in `sorted(ADAPTERS)` (`nous`, `xai`): not authenticated → `  [<name:8s>] <display_name> — not logged in`; `get_credential()` raises → `  [<name:8s>] <display_name> — credentials need attention (<exc>)`; else → `  [<name:8s>] <display_name> — ready` plus `" (bearer expires <expires_at>)"` when `cred.expires_at` is set. Footer: "\nStart the proxy with: hermes proxy start [--provider <name>]". Always returns 0.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout only — but calling `get_credential()` can refresh and persist Nous tokens as a side effect.
- **Config / env:** same as `proxy start`.
- **Edge cases / guards:** Never raises; every adapter exception is caught and rendered inline.
- **Rebuild notes:** iterate the registry and render three states (logged out / broken / ready+ttl).

### hermes proxy providers  `id: cli-b.proxy.providers`
- **Surface:** CLI
- **Where:** `hermes proxy providers [-h]`; help "List available proxy upstream providers".
- **What it does:** Lists the adapter keys accepted by `--provider`.
- **How it works:** `hermes_cli/proxy/cli.py:100-106`. Prints "Available proxy upstream providers:" then `  <name>  — <display_name>` for each sorted key. Current output: `  nous  — Nous Portal` and `  xai  — xAI Grok OAuth`. Returns 0.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout.
- **Config / env:** n/a.
- **Edge cases / guards:** none — instantiating an adapter is cheap and does no network work.
- **Rebuild notes:** print the registry keys; keep them identical to `--provider` values.

### Proxy upstream adapter: Nous Portal  `id: cli-b.proxy.adapter.nous`
- **Surface:** Provider
- **Where:** `hermes proxy start --provider nous` (the default); shown as "Nous Portal" in `proxy status`/`proxy providers`.
- **What it does:** Resolves (and refreshes) your Nous Portal inference JWT and forwards to the Nous inference API.
- **How it works:** `hermes_cli/proxy/adapters/nous_portal.py`. `name="nous"`, `display_name="Nous Portal"`. `allowed_paths` = `{"/chat/completions", "/completions", "/embeddings", "/models"}` (`:35-42`). `is_authenticated()` reads `providers.nous` from `~/.hermes/auth.json` via `_auth_store_lock()`+`_load_auth_store()` and is true when `agent_key` exists **or** both `refresh_token` and `access_token` exist. `get_credential()` (`:93-155`) takes a `threading.Lock`, calls `resolve_nous_runtime_credentials(force_refresh=…)`; an `AuthError` that `_is_terminal_nous_refresh_error()` classifies as terminal triggers `_quarantine_nous_oauth_state(state, exc, reason="proxy_refresh_failure")` + `_quarantine_nous_pool_entries(...)` and a re-save of the store plus `_write_shared_nous_state(state)`; any failure raises `RuntimeError("Failed to refresh Nous Portal credentials: …")`. Base URL precedence: `_nous_inference_env_override()` → `_validate_nous_inference_url_from_network(refreshed.base_url)` → `DEFAULT_NOUS_INFERENCE_URL`, then `rstrip("/")`. `get_retry_credential()` retries only on HTTP 401, logging "proxy: Nous upstream rejected bearer; force-refreshing invoke JWT" and re-resolving with `force_refresh=True`.
- **Inputs / options:** n/a (selected by `--provider nous`).
- **Outputs / side effects:** May rewrite `~/.hermes/auth.json` (`providers.nous`, pool quarantine flags) and the shared Nous state file.
- **Config / env:** `NOUS_INFERENCE_BASE_URL` (env override), auth store under `$HERMES_HOME/auth.json`.
- **Edge cases / guards:** Missing state → `RuntimeError("Not logged into Nous Portal. Run `hermes auth add nous` first.")`; refresh returning no `api_key` → `RuntimeError("Nous Portal refresh did not return a usable inference JWT. Try `hermes auth add nous` to re-authenticate.")`.
- **Rebuild notes:** wrap the provider's token refresh in a lock, validate the base URL against an allowlist, and quarantine terminally-broken credentials so the pool stops re-trying them.

### Proxy upstream adapter: xAI Grok OAuth  `id: cli-b.proxy.adapter.xai`
- **Surface:** Provider
- **Where:** `hermes proxy start --provider xai`; shown as "xAI Grok OAuth".
- **What it does:** Forwards to xAI's OpenAI-compatible API using a credential from the `xai-oauth` pool, rotating pool entries on 401/429.
- **How it works:** `hermes_cli/proxy/adapters/xai.py`. `name="xai"`, `display_name="xAI Grok OAuth"`, `auth_hint="hermes auth add xai-oauth --type oauth"`. `allowed_paths` = `{"/responses", "/chat/completions", "/completions", "/embeddings", "/models"}` (`:20-28`) — `/responses` is included because Hermes' native xAI runtime uses `codex_responses` mode. Pool via `agent.credential_pool.load_pool("xai-oauth")`. `is_authenticated()` = `pool.has_available()`. `get_credential()` → `pool.select()`; bearer = `entry.runtime_api_key or entry.access_token`; base URL = `entry.runtime_base_url or entry.base_url or DEFAULT_XAI_OAUTH_BASE_URL`. `get_retry_credential()` handles 401 and 429 only: 429 → `pool.mark_exhausted_and_rotate(status_code=429)` (1-hour cooldown on the rate-limited key); 401 → `pool.try_refresh_current()` and, if that returns None, `mark_exhausted_and_rotate`. A rotation that yields the same bearer returns None (no infinite retry). Logs "proxy: xAI upstream returned <code>; retrying with rotated pool credential".
- **Inputs / options:** n/a (selected by `--provider xai`).
- **Outputs / side effects:** Updates the credential pool file (exhaustion timestamps, refreshed tokens).
- **Config / env:** `xai-oauth` pool in the auth store; `DEFAULT_XAI_OAUTH_BASE_URL` from `hermes_cli/auth.py`.
- **Edge cases / guards:** No credentials → `RuntimeError("No xAI OAuth credentials found. Run `hermes auth add xai-oauth --type oauth` first.")`; all exhausted → `RuntimeError("No available xAI OAuth credentials found. Run `hermes auth reset xai-oauth` or re-authenticate with `hermes auth add xai-oauth --type oauth`.")`; empty token on the entry → `RuntimeError("xAI OAuth credential pool entry did not contain an access token. Re-authenticate with `hermes auth add xai-oauth --type oauth`.")`.
- **Rebuild notes:** pool-backed adapter with rotate-on-429 and refresh-then-rotate-on-401; guard against returning the same failing bearer.

### hermes lsp (command group)  `id: cli-b.lsp`
- **Surface:** CLI
- **Where:** `hermes lsp [-h] {status,list,install,install-all,restart,which}`; help "Language Server Protocol management"; description "Manage the LSP layer that powers post-write semantic diagnostics in write_file/patch."
- **What it does:** Manages the language servers Hermes spawns to produce real compiler/type-checker diagnostics after `write_file`/`patch` edits.
- **How it works:** Parser + handlers live in the LSP package itself so it ships self-contained: `agent/lsp/cli.py:21-66` (`register_subparser`) and `agent/lsp/cli.py:69-88` (`run_lsp_command`). A missing sub-command defaults to `status` (`:71`). `KeyboardInterrupt` → exit 130; an unknown sub-command writes "unknown lsp subcommand: <sub>" to stderr and returns 2. The service singleton is `agent/lsp/__init__.py:45` (`get_service()`), built by `LSPService.create_from_config()` (`agent/lsp/manager.py:192-254`) which reads the `lsp:` config block; an `atexit` hook tears down spawned servers on clean exit.
- **Inputs / options:** `-h/--help`; sub-commands `status`, `list`, `install`, `install-all`, `restart`, `which`.
- **Outputs / side effects:** Depends on sub-command; installs land in `$HERMES_HOME/lsp/bin/`.
- **Config / env:** `lsp.enabled` (default true), `lsp.wait_mode` (`document`|`full`, default `document`), `lsp.wait_timeout` (default `DIAGNOSTICS_DOCUMENT_WAIT` = 5.0 s; full mode budget is 10.0 s, `agent/lsp/client.py:79-80`), `lsp.install_strategy` (`auto`|`manual`|`off`, default `auto`), `lsp.idle_timeout` (default 600 s, clamped up to a 30 s floor when non-zero, `manager.py:61-62,217-222`), and per-server `lsp.servers.<id>.{disabled,command,env,initialization_options}` (`manager.py:223-242`). `HERMES_HOME` selects the bin staging dir.
- **Edge cases / guards:** LSP only runs when the file's workspace is a git worktree (`agent/lsp/__init__.py:8-12`, `manager.enabled_for()`); a (server, workspace) pair that failed to spawn is added to a broken-set and skipped for the process lifetime until `hermes lsp restart`.
- **Rebuild notes:** registry of servers (id, extensions, root markers) + install recipes + a per-workspace client pool with an idle reaper. A better version would ship prebuilt server binaries per platform and stream diagnostics incrementally rather than waiting a fixed budget.

### hermes lsp status  `id: cli-b.lsp.status`
- **Surface:** CLI
- **Where:** `hermes lsp status [-h] [--json]`; help "Show LSP service status".
- **What it does:** Prints the LSP service settings, live clients, broken pairs, backend warnings, and the full server registry with per-server install status.
- **How it works:** `agent/lsp/cli.py:91-173` (`_cmd_status`). Human output sections, verbatim: `LSP Service` / `===========`, then `  enabled:         <bool>`; when the service is active also `  wait_mode:       <mode>`, `  wait_timeout:    <n>s`, `  install_strategy:<strategy>`, `  active clients:  <n>` (each `    - <server_id:20s> state=<state:10s> root=<workspace_root>`) or `  active clients:  none`, `  broken pairs:    <n>` with `    - <pair>` lines, and `  disabled in cfg: <comma list>`. Then optional `Backend warnings` / `================` with `  ! <line>` items from `_backend_warnings()` (`:277-298`) — currently one rule: bash-language-server installed but `shellcheck` missing → "bash-language-server is installed but shellcheck is missing — diagnostics will be empty (apt: shellcheck, brew: shellcheck, scoop: shellcheck)." Finally `Registered Servers` / `==================` with `  <marker> <server_id:24s> [<status:11s>] <first 5 extensions>` (marker `✓` installed, `·` missing, `?` manual-only; more than 5 extensions renders `, … (+N)`) and an indented description line.
- **Inputs / options:** `-h/--help`; `--json` ("Emit machine-readable JSON") → `{"service": <get_status() dict>, "registry": [{"server_id","extensions","description","binary_status"}, …]}` printed with `indent=2`.
- **Outputs / side effects:** stdout only. Returns 0.
- **Config / env:** reads the whole `lsp.*` block; `detect_status()` probes `$HERMES_HOME/lsp/bin/` then PATH.
- **Edge cases / guards:** With no service (`get_service()` → None) `info` is `{"enabled": False}` and only the registry table plus the `enabled:` line are printed.
- **Rebuild notes:** two renderers over one status dict; keep the JSON shape stable for dashboards.

### hermes lsp list  `id: cli-b.lsp.list`
- **Surface:** CLI
- **Where:** `hermes lsp list [-h] [--installed-only]`; help "List supported language servers".
- **What it does:** One line per registered language server with its install status and every file extension it claims.
- **How it works:** `agent/lsp/cli.py:176-188`. Format: `f"{s.server_id:24s} [{status:11s}] {','.join(s.extensions)}"`. `status` comes from `detect_status(_recipe_pkg_for(server_id))` ∈ `installed` | `missing` | `manual-only`.
- **Inputs / options:** `-h/--help`; `--installed-only` ("Only show servers whose binary is currently available") filters to `status == "installed"`.
- **Outputs / side effects:** stdout; returns 0.
- **Config / env:** n/a.
- **Edge cases / guards:** none.
- **Rebuild notes:** trivial registry dump — keep column widths so it greps cleanly.

### LSP server registry (27 servers)  `id: cli-b.lsp.registry`
- **Surface:** Core
- **Where:** Rows printed by `hermes lsp list` / `hermes lsp status`; defined in `agent/lsp/servers.py` (`SERVERS`).
- **What it does:** Maps file extensions to a language server, its root markers, and its spawn command.
- **How it works:** Enumerated live from the installed package. All 27 entries (`server_id` — extensions — description): `pyright` — `.py,.pyi` — "Python — Microsoft pyright"; `typescript` — `.ts,.tsx,.js,.jsx,.mjs,.cjs,.mts,.cts` — "JavaScript/TypeScript — typescript-language-server"; `vue-language-server` — `.vue` — "Vue.js — @vue/language-server"; `svelte-language-server` — `.svelte` — "Svelte — svelte-language-server"; `astro-language-server` — `.astro` — "Astro — @astrojs/language-server"; `gopls` — `.go` — "Go — gopls"; `rust-analyzer` — `.rs` — "Rust — rust-analyzer"; `clangd` — `.c,.cpp,.cc,.cxx,.h,.hh,.hpp,.hxx` — "C/C++ — clangd"; `bash-language-server` — `.sh,.bash,.zsh,.ksh` — "Bash — bash-language-server"; `yaml-language-server` — `.yaml,.yml` — "YAML — yaml-language-server"; `lua-language-server` — `.lua` — "Lua — lua-language-server"; `intelephense` — `.php` — "PHP — intelephense"; `ocaml-lsp` — `.ml,.mli` — "OCaml — ocaml-lsp"; `dockerfile-ls` — `.dockerfile,Dockerfile` — "Dockerfile — dockerfile-language-server-nodejs"; `terraform-ls` — `.tf,.tfvars` — "Terraform — terraform-ls"; `dart` — `.dart` — "Dart — built-in language server"; `haskell-language-server` — `.hs,.lhs` — "Haskell — haskell-language-server"; `julia` — `.jl` — "Julia — LanguageServer.jl"; `clojure-lsp` — `.clj,.cljs,.cljc,.edn` — "Clojure — clojure-lsp"; `nixd` — `.nix` — "Nix — nixd"; `zls` — `.zig,.zon` — "Zig — zls"; `gleam` — `.gleam` — "Gleam — built-in language server"; `elixir-ls` — `.ex,.exs` — "Elixir — elixir-ls"; `prisma` — `.prisma` — "Prisma — built-in language server"; `kotlin-language-server` — `.kt,.kts` — "Kotlin — kotlin-language-server"; `jdtls` — `.java` — "Java — Eclipse JDT Language Server"; `powershell` — `.ps1,.psm1,.psd1` — "PowerShell — PowerShellEditorServices (manual bundle)".
- **Inputs / options:** n/a (data table).
- **Outputs / side effects:** n/a.
- **Config / env:** `lsp.servers.<server_id>.disabled` removes one from consideration.
- **Edge cases / guards:** `_recipe_pkg_for()` (`agent/lsp/cli.py:262-274`) aliases four ids to their install-recipe keys: `vue-language-server`→`@vue/language-server`, `astro-language-server`→`@astrojs/language-server`, `dockerfile-ls`→`dockerfile-language-server-nodejs`, `typescript`→`typescript-language-server`. Servers with no recipe (ocaml-lsp, terraform-ls, dart, haskell-language-server, julia, clojure-lsp, nixd, zls, gleam, elixir-ls, prisma, kotlin-language-server, jdtls) report `missing` and are never auto-installed.
- **Rebuild notes:** a declarative table (id, extensions, root markers, argv, description) that both the installer and the spawner read.

### LSP install recipes (14)  `id: cli-b.lsp.recipes`
- **Surface:** Core
- **Where:** Drives `hermes lsp install`, `install-all`, `which`, and the `[installed|missing|manual-only]` column.
- **What it does:** Declares how each installable server is fetched and which binary name proves it is present.
- **How it works:** `agent/lsp/install.py:52-110` (`INSTALL_RECIPES`), all 14 entries: `pyright` → npm pkg `pyright`, bin `pyright-langserver`; `typescript-language-server` → npm `typescript-language-server`, bin `typescript-language-server`, `extra_pkgs: ["typescript"]` (tsserver must live in the same node_modules tree or `initialize()` fails with "Could not find a valid TypeScript installation"); `@vue/language-server` → npm, bin `vue-language-server`; `svelte-language-server` → npm, bin `svelteserver`; `@astrojs/language-server` → npm, bin `astro-ls`; `yaml-language-server` → npm, bin `yaml-language-server`; `bash-language-server` → npm, bin `bash-language-server`; `intelephense` → npm, bin `intelephense`; `dockerfile-language-server-nodejs` → npm, bin `docker-langserver`; `gopls` → strategy `go`, pkg `golang.org/x/tools/gopls@latest`, bin `gopls`; `rust-analyzer` → strategy `manual`, bin `rust-analyzer` (too heavy — install via rustup); `clangd` → `manual`, bin `clangd` (ships with LLVM); `lua-language-server` → `manual`, bin `lua-language-server` (platform-specific GitHub release); `powershell` → `manual`, bin `pwsh` (PowerShellEditorServices ships as a zip + bootstrap script).
- **Inputs / options:** n/a.
- **Outputs / side effects:** npm/go installs write into `$HERMES_HOME/lsp/bin/` so the user's global toolchain is untouched; per-package `threading.Lock` deduplicates concurrent installs; every failure path returns None (non-fatal — the tool layer falls back to its in-process syntax checker).
- **Config / env:** `lsp.install_strategy` (`auto` attempts installs, `manual`/`off` never do); node is located via `hermes_constants.find_node_executable`.
- **Edge cases / guards:** Windows wrapper suffixes `.cmd`, `.exe`, `.bat` are probed when resolving a binary (`install.py:_WINDOWS_WRAPPER_SUFFIXES`).
- **Rebuild notes:** {strategy, pkg, bin, extra_pkgs} records + a staging bin dir; treat every install as best-effort.

### hermes lsp install  `id: cli-b.lsp.install`
- **Surface:** CLI
- **Where:** `hermes lsp install [-h] server`; help "Install a server binary"; positional help "Server id (e.g. pyright, gopls)".
- **What it does:** Installs one language server's binary into the Hermes-owned staging dir.
- **How it works:** `agent/lsp/cli.py:191-212`. Maps the id through `_recipe_pkg_for()`, checks `detect_status(pkg)`; already installed → prints "<server> already installed" and returns 0. Otherwise prints "installing <server> (pkg=<pkg>) ..." (flushed) and calls `try_install(pkg, "auto")`. On success prints "installed: <bin_path>" → 0. On failure: if the recipe's strategy is `manual`, stderr gets "<server>: this server requires a manual install. See documentation."; otherwise "<server>: install failed (see logs)." — either way return 1.
- **Inputs / options:** `-h/--help`; positional `server` (required).
- **Outputs / side effects:** Writes into `$HERMES_HOME/lsp/bin/` (npm tree or `go install` output).
- **Config / env:** `HERMES_HOME`; PATH must contain `npm`/`go` for the respective strategies.
- **Edge cases / guards:** Passing an unknown id yields `pkg == server` with no recipe; `try_install` returns None and the generic "install failed" message is printed.
- **Rebuild notes:** id→recipe lookup then a per-strategy installer; always report the resolved binary path.

### hermes lsp install-all  `id: cli-b.lsp.install-all`
- **Surface:** CLI
- **Where:** `hermes lsp install-all [-h] [--include-manual]`; help "Install every server with a known auto-install recipe".
- **What it does:** Walks the whole registry and installs every server that has an automatic recipe.
- **How it works:** `agent/lsp/cli.py:215-238`. Skips servers with no recipe; skips `strategy == "manual"` unless `--include-manual`; already-installed prints `  <server_id:24s> already installed`. Otherwise prints `  installing <server_id> (pkg=<pkg>) ... ` then `ok (<path>)` or `FAILED`. Return code is 1 if any install failed, else 0.
- **Inputs / options:** `-h/--help`; `--include-manual` ("Even attempt servers marked manual-install (best effort)").
- **Outputs / side effects:** Multiple npm/go installs into `$HERMES_HOME/lsp/bin/`; can take minutes and hundreds of MB.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `--include-manual` will still fail for rust-analyzer/clangd/lua-language-server/powershell because their recipes have an empty `pkg`; the run continues and returns 1.
- **Rebuild notes:** loop the recipes, keep going on failure, aggregate the exit code.

### hermes lsp restart  `id: cli-b.lsp.restart`
- **Surface:** CLI
- **Where:** `hermes lsp restart [-h]`; help "Tear down running LSP clients (next edit re-spawns)".
- **What it does:** Shuts down the in-process LSP service so the next file edit spawns fresh language servers (and clears the broken-pairs set).
- **How it works:** `agent/lsp/cli.py:241-246` calls `agent.lsp.shutdown_service()` (`agent/lsp/__init__.py:80-93`), which swaps the singleton to None under a lock and calls `svc.shutdown()`, swallowing errors at debug level. Prints "LSP service shut down. Next edit will respawn clients." and returns 0.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Kills language-server subprocesses owned by **this** process only — a separately running `hermes gateway` keeps its own clients.
- **Config / env:** n/a.
- **Edge cases / guards:** Safe to call when no service was ever created (no-op).
- **Rebuild notes:** singleton teardown + idempotent shutdown; note that per-process scope is a real limitation worth fixing with an IPC signal.

### hermes lsp which  `id: cli-b.lsp.which`
- **Surface:** CLI
- **Where:** `hermes lsp which [-h] server`; help "Print binary path for a server"; positional help "Server id".
- **What it does:** Prints the resolved executable path for a server, or reports that it is not installed.
- **How it works:** `agent/lsp/cli.py:249-259`. Looks the id up **directly** in `INSTALL_RECIPES` (note: it does *not* go through `_recipe_pkg_for`, so aliased ids such as `typescript` or `vue-language-server` fall through to `bin_name = server_id`), then `_existing_binary(bin_name)` which probes `$HERMES_HOME/lsp/bin/` first and PATH second. Found → path on stdout, exit 0. Not found → "<server>: not installed" on stderr, exit 1.
- **Inputs / options:** `-h/--help`; positional `server` (required).
- **Outputs / side effects:** stdout/stderr only.
- **Config / env:** `HERMES_HOME`, `PATH`.
- **Edge cases / guards:** The alias gap above means `hermes lsp which typescript` looks for a binary literally called `typescript`; use `hermes lsp which typescript-language-server`.
- **Rebuild notes:** resolve through the same alias map the installer uses — this is a genuine inconsistency worth fixing in a reimplementation.

### hermes setup (interactive wizard)  `id: cli-b.setup`
- **Surface:** CLI
- **Where:** `hermes setup [-h] [--non-interactive] [--reset] [--reconfigure] [--quick] [--portal] [{model,tts,terminal,gateway,tools,telemetry,agent}]`; top-level help row "Interactive setup wizard"; description "Configure Hermes Agent with an interactive wizard. Run a specific section: hermes setup model|tts|terminal|gateway|tools|telemetry|agent".
- **What it does:** The onboarding and reconfiguration wizard. Chooses a provider/model, a terminal backend, messaging platforms and tools, and writes `~/.hermes/config.yaml` + `~/.hermes/.env`.
- **How it works:** Parser `hermes_cli/subcommands/setup.py:12-67` (`build_setup_parser`), handler `hermes_cli/main.py:3782` (`cmd_setup`) → `hermes_cli/setup.py:2970` (`run_setup_wizard`) → `_run_setup_wizard_impl` (`setup.py:3068`). Order of operations: (1) `is_managed()` → `managed_error("run setup wizard")` and return; (2) `ensure_hermes_home()`; (3) `--reset` writes `deepcopy(DEFAULT_CONFIG)` and prints "Configuration reset to defaults."; (4) `load_config()` + `get_hermes_home()`; (5) timestamped backup of `config.yaml` to `config.yaml.bak.<YYYYmmdd_HHMMSS>` via `shutil.copy2`; (6) non-interactive detection (`--non-interactive` **or** `not is_interactive_stdin()`) → print the headless guidance block and return; (7) `--portal` → `_run_portal_one_shot(config)` and return; (8) a named `section` → run just that section; (9) otherwise the existing-install / first-time branch. All choices go through the curses menu layer with a shared navigation handler (`cli-b.setup.navigation`).
- **Inputs / options:** `-h/--help`; positional `section` (`nargs="?"`, choices `model`, `tts`, `terminal`, `gateway`, `tools`, `telemetry`, `agent`, default None; help "Run a specific setup section instead of the full wizard"); `--non-interactive` ("Non-interactive mode (use defaults/env vars)"); `--reset` ("Reset configuration to defaults"); `--reconfigure` ("(Default on existing installs.) Re-run the full wizard, showing current values as defaults. Kept for backwards compatibility — a bare 'hermes setup' now does this."); `--quick` ("On existing installs: only prompt for items that are missing or unset, instead of running the full reconfigure wizard."); `--portal` ("One-shot Nous Portal setup: log in via OAuth, pick a Nous model, set Nous as the inference provider, and opt into the Tool Gateway. Skips the rest of the wizard.").
- **Outputs / side effects:** Writes `$HERMES_HOME/config.yaml`, `$HERMES_HOME/.env`, a `config.yaml.bak.<stamp>` backup, possibly installs pip packages (modal/daytona/vercel/neutts/kittentts), installs/starts the gateway service, and may seed or opt out of bundled skills.
- **Config / env:** Everything under `model.*`, `terminal.*`, `agent.*`, `compression.*`, `session_reset.*`, `display.*`, `tts.*`, `telemetry.shared_metrics.*`, `platform_toolsets.*`, `proxy.*`; env vars written include `TERMINAL_ENV`, `TERMINAL_MODAL_MODE`, `TERMINAL_VERCEL_RUNTIME`, `TERMINAL_SSH_*`, `MODAL_TOKEN_ID/SECRET`, `DAYTONA_API_KEY`, `VERCEL_TOKEN/PROJECT_ID/TEAM_ID`, `TELEGRAM_*`, `BLUEBUBBLES_*`, `WEBHOOK_*`, plus every TTS key. Reads `HERMES_NONINTERACTIVE`.
- **Edge cases / guards:** Managed installs refuse. `--reconfigure`/`--quick` on a fresh install print "No existing configuration found — running first-time setup." and fall through. Ctrl+C anywhere exits with status 1; Escape raises `_SetupCancelled` → "Setup cancelled. Remaining sections were not changed."
- **Rebuild notes:** A state machine of named sections, each a pure `f(config) -> None` that mutates a dict, wrapped in a navigation context with replayable answers. A better version would make every prompt declarative (id, type, default, validator) so the same schema drives CLI, TUI and web wizards.

### setup — non-interactive guidance block  `id: cli-b.setup.noninteractive`
- **Surface:** CLI
- **Where:** Printed by `hermes setup --non-interactive` or any `hermes setup` run without a TTY.
- **What it does:** Explains how to configure Hermes without the wizard.
- **How it works:** `hermes_cli/setup.py:187-203` (`print_noninteractive_setup_guidance`), called with the reason "Running in a non-interactive environment (no TTY detected)." from `_run_setup_wizard_impl` (`setup.py:3103`). Verbatim output: header "⚕ Hermes Setup — Non-interactive mode"; the reason line; "The interactive wizard cannot be used here."; "Configure Hermes using environment variables or config commands:"; "  hermes config set model.provider custom"; "  hermes config set model.base_url http://localhost:8080/v1"; "  hermes config set model.default your-model-name"; "Or set OPENROUTER_API_KEY / OPENAI_API_KEY in your environment."; "Run 'hermes setup' in an interactive terminal to use the full wizard."
- **Inputs / options:** n/a.
- **Outputs / side effects:** stdout only; no config is written.
- **Config / env:** `HERMES_NONINTERACTIVE`.
- **Edge cases / guards:** `is_interactive_stdin()` (`setup.py:176-185`) returns False when `sys.stdin` is None or `isatty()` raises.
- **Rebuild notes:** always give the headless user the three exact commands that replace the wizard.

### setup — curses navigation model (Escape / Left arrow / Space / Enter)  `id: cli-b.setup.navigation`
- **Surface:** CLI
- **Where:** Every menu the wizard shows; also `hermes model` via `run_setup_action_with_navigation`.
- **What it does:** Lets you cancel the whole wizard with Escape and step back one choice with the Left arrow, replaying earlier answers invisibly.
- **How it works:** `hermes_cli/setup.py:228-306` defines the control-flow exceptions `_SetupControlFlow(BaseException)` (deliberately not `Exception` so provider code that catches `Exception` cannot swallow navigation), `_SetupCancelled`, `_SetupGoBack(prompt_index)`, plus `_SetupNavigationState` (section_index, prompt_index, active_prompt_index, resolved_choices, replay_choices) held in a `ContextVar`. `_handle_setup_menu_navigation` (`setup.py:265-306`) translates `MenuNavigationEvent.BEGIN/RESOLVE/CANCEL/BACK` from `hermes_cli/curses_ui.py`: BEGIN returns `MenuNavigationStart(allow_back=…, replay_value=…)`, RESOLVE records the answer and truncates any later answers, CANCEL raises `_SetupCancelled`, BACK raises `_SetupGoBack`. `_run_setup_steps` (`setup.py:2981-3044`) is the replay engine: on `_SetupGoBack` with `prompt_index > 0` it re-enters the same section replaying the first `prompt_index-1` answers ("Returning to the previous choice in <label>..."), otherwise it drops to the previous section ("Returning to <previous label>..."). `_setup_navigation_scope()` (`setup.py:2954-2968`) is the context manager that installs/removes the handler.
- **Inputs / options:** Keyboard: **↑/↓** move, **Enter** confirm, **Space** toggle in checklists, **Left arrow** go back one prompt/section, **Escape** cancel the wizard, **Ctrl+C** exit the process (status 1). Selecting the same index as the current default prints "  Skipped (keeping current)".
- **Outputs / side effects:** No config change on cancel — "Setup cancelled. Remaining sections were not changed."
- **Config / env:** n/a.
- **Edge cases / guards:** `prompt_yes_no` routes through the same curses menu (choices "Yes"/"No") **only** while a navigation scope is active; outside setup it uses a plain `[Y/n]` line prompt that returns the default on EOF. `is_noninteractive()` (`HERMES_NONINTERACTIVE` ∈ {1,true,yes,on}) makes `prompt_yes_no` return the default without prompting. Pasted input is scrubbed of bracketed-paste markers `ESC[200~`/`ESC[201~` (`_sanitize_pasted_input`, `setup.py:309-314`).
- **Rebuild notes:** model each prompt as an indexed step with a recorded answer; "back" = truncate the answer list and replay. Use a non-`Exception` base class for control flow so third-party handlers cannot eat it.

### setup — first-run mode picker  `id: cli-b.setup.mode-picker`
- **Surface:** CLI
- **Where:** Shown only on a fresh install: question "How would you like to set up Hermes?".
- **What it does:** Chooses between the Nous Portal quick path, the full bring-your-own-keys wizard, and a Blank Slate install.
- **How it works:** `hermes_cli/setup.py:3271-3299`. "Existing install" is detected as `bool(get_env_value("OPENROUTER_API_KEY")) or bool(get_env_value("OPENAI_BASE_URL")) or get_active_provider() is not None` (`setup.py:3225-3231`). The banner block printed first is verbatim: `┌─────────────────────────────────────────────────────────┐`, `│             ⚕ Hermes Agent Setup Wizard                │`, `├─────────────────────────────────────────────────────────┤`, `│  Let's configure your Hermes Agent installation.       │`, `│  Press Ctrl+C at any time to exit.                     │`, `└─────────────────────────────────────────────────────────┘`.
- **Inputs / options:** Three choices, verbatim: `[0] "Quick Setup (Nous Portal) — free OAuth login, no API keys, model + tools (recommended)"`; `[1] "Full setup — configure every provider, tool & option yourself (bring your own keys)"`; `[2] "Blank Slate — everything off except the bare minimum; opt in to each capability"`. Default index 0.
- **Outputs / side effects:** 0 → `_run_first_time_quick_setup`; 2 → `_run_blank_slate_setup`; 1 → falls through to the four-section full wizard.
- **Config / env:** n/a.
- **Edge cases / guards:** On an existing install this picker is skipped entirely and the reconfigure path runs.
- **Rebuild notes:** keep three named onboarding tracks; make the recommended one the default index.

### setup — existing-install reconfigure header  `id: cli-b.setup.reconfigure`
- **Surface:** CLI
- **Where:** Shown by a bare `hermes setup` on an already-configured install.
- **What it does:** Announces that the full wizard will run with current values as defaults, and points at the section shortcuts.
- **How it works:** `hermes_cli/setup.py:3252-3268`. Verbatim lines after the `◆ Reconfigure` header: "You already have Hermes configured."; "Running the full wizard — each prompt shows your current value."; "Press Enter to keep it, or type a new value to change it."; ""; "Tip: jump straight to a section with 'hermes setup model|terminal|"; "     gateway|tools|agent', or fill only missing items with --quick."
- **Inputs / options:** n/a (informational).
- **Outputs / side effects:** Falls through to the four-step full wizard (`Model & Provider`, `Terminal Backend`, `Messaging Platforms`, `Tools`).
- **Config / env:** n/a.
- **Edge cases / guards:** `--reconfigure` is now a no-op flag kept for backwards compatibility; `--quick` short-circuits to `_run_quick_setup` before this header prints.
- **Rebuild notes:** show the defaults inline and say plainly that Enter keeps them.

### setup — Configuration Location block  `id: cli-b.setup.location-block`
- **Surface:** CLI
- **Where:** Printed at the start of the full-setup path, header "◆ Configuration Location".
- **What it does:** Tells the user exactly which files the wizard is about to write.
- **How it works:** `hermes_cli/setup.py:3311-3319`. Lines: `Config file:  <get_config_path()>`, `Secrets file: <get_env_path()>`, `Data folder:  <hermes_home>`, `Install dir:  <PROJECT_ROOT>`, then "You can edit these files directly or use 'hermes config edit'". When an OpenClaw migration just ran it adds "Settings were imported from OpenClaw.", "Each section below will show what was imported — press Enter to keep,", "or choose to reconfigure if needed."
- **Inputs / options:** n/a.
- **Outputs / side effects:** stdout.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** name the files before mutating them.

### setup model — Inference Provider section  `id: cli-b.setup.model`
- **Surface:** CLI
- **Where:** `hermes setup model`, or step 1 of the full wizard; header "◆ Inference Provider" inside the box `│     ⚕ Hermes Setup — Model & Provider … │`.
- **What it does:** Picks the inference provider and default model by delegating to the exact same picker `hermes model` uses.
- **How it works:** `hermes_cli/setup.py:951-1006` (`setup_model_provider`). Prints "Choose how to connect to your main chat model." and "   Guide: https://hermes-agent.nousresearch.com/docs/integrations/providers", then calls `hermes_cli.main.select_provider_and_model()` (`main.py:3823`). `SystemExit`/`KeyboardInterrupt` → "Provider setup skipped."; any other exception → "Provider setup encountered an error: <exc>" + "You can try again later with: hermes model". Afterwards it re-reads `load_config()` and replaces the wizard's dict in place (`config.clear(); config.update(_refreshed)`) so a later `save_config` cannot clobber what the picker wrote (issue #4172), then `save_config(config)`.
- **Inputs / options:** All prompts belong to the shared provider picker (documented by the `hermes model` shard): provider menu, credential prompt, model list. The `quick=True` keyword exists on the function but nothing in the wizard passes it any more.
- **Outputs / side effects:** Writes `model.provider`, `model.default`, `model.base_url`, `custom_providers`, `auxiliary`, provider metadata, and credentials into the auth store / `.env`.
- **Config / env:** `model.*`, `credential_pool_strategies.*`.
- **Edge cases / guards:** Credential rotation, vision-backend selection and TTS provider are deliberately **not** prompted here any more — defaults are rotation off, vision auto-detected from the main provider, TTS = Edge (`setup.py:996-1002`).
- **Rebuild notes:** one provider/model picker shared by the wizard and the standalone command; always reload config after delegating.

### setup — provider fallback model lists  `id: cli-b.setup.default-provider-models`
- **Surface:** Config
- **Where:** Used by the model picker when a provider's live `/models` endpoint is unreachable.
- **What it does:** Supplies a hard-coded model menu per provider so setup still works offline or behind a broken endpoint.
- **How it works:** `hermes_cli/setup.py:73-122` (`_DEFAULT_PROVIDER_MODELS`), 17 providers, verbatim: `copilot-acp`: copilot-acp. `copilot`: gpt-5.4, gpt-5.4-mini, gpt-5-mini, gpt-5.3-codex, gpt-5.2-codex, gpt-4.1, gpt-4o, gpt-4o-mini, claude-opus-4.6, claude-sonnet-5, claude-sonnet-4.6, claude-sonnet-4.5, claude-haiku-4.5, gemini-2.5-pro. `gemini`: gemini-3.1-pro-preview, gemini-3-pro-preview, gemini-3.6-flash, gemini-3.1-flash-lite-preview. `vertex`: google/gemini-3.1-pro-preview, google/gemini-3-pro-preview, google/gemini-3-flash-preview, google/gemini-3.1-flash-lite-preview, google/gemini-2.5-pro, google/gemini-2.5-flash. `zai`: glm-5.3, glm-5.3-flash, glm-5.2, glm-5.1, glm-5, glm-4.7, glm-4.5, glm-4.5-flash. `kimi-coding` and `kimi-coding-cn`: kimi-k3, kimi-k2.6, kimi-k2.5, kimi-k2-thinking, kimi-k2-turbo-preview. `stepfun`: step-3.5-flash, step-3.5-flash-2603. `arcee`: trinity-large-thinking, trinity-large-preview, trinity-mini. `minimax` and `minimax-cn`: MiniMax-M2.7, MiniMax-M2.5, MiniMax-M2.1, MiniMax-M2. `ai-gateway`: anthropic/claude-opus-4.6, anthropic/claude-sonnet-4.6, openai/gpt-5, google/gemini-3-flash. `kilocode`: anthropic/claude-sonnet-5, anthropic/claude-opus-4.6, anthropic/claude-sonnet-4.6, openai/gpt-5.4, google/gemini-3-pro-preview, google/gemini-3-flash-preview. `opencode-zen`: x-preview-f-free, gpt-5.6-sol, gpt-5.4, gpt-5.3-codex, claude-opus-5, claude-sonnet-5, gemini-3.7-flash, glm-5.2, kimi-k3, minimax-m3. `opencode-free`: deepseek-v4-flash-free, hy3-free, mimo-v2.5-free, laguna-s-2.1-free, nemotron-3-ultra-free, nemotron-3.5-lightning-free, muse-spark-1.2-contributor-free. `opencode-go`: kimi-k3, kimi-k2.7-code, kimi-k2.6, gpt-5.6-luna, grok-4.5, glm-5.3, glm-5.3-flash, glm-5.2, mimo-v2.5-pro, mimo-v2.5, minimax-m3, minimax-m2.7, qwen3.8-max, qwen3.7-max, deepseek-v4-pro, hy3. `huggingface`: Qwen/Qwen3.5-397B-A17B, Qwen/Qwen3-235B-A22B-Thinking-2507, Qwen/Qwen3-Coder-480B-A35B-Instruct, deepseek-ai/DeepSeek-R1-0528, deepseek-ai/DeepSeek-V3.2, moonshotai/Kimi-K2.5.
- **Inputs / options:** n/a (data).
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Providers absent from this map show an empty list and the picker falls back to free-text entry.
- **Rebuild notes:** ship a cached snapshot of each provider's catalogue and refresh it in the background rather than hard-coding.

### setup — credential-pool strategy helpers  `id: cli-b.setup.credential-pool`
- **Surface:** Config
- **Where:** Invisible plumbing behind the model section's "add another key of the same provider" flow.
- **What it does:** Records, per provider, how multiple stored credentials are chosen at runtime.
- **How it works:** `hermes_cli/setup.py:48-70`. `_get_credential_pool_strategies(config)` reads the `credential_pool_strategies` dict; `_set_credential_pool_strategy(config, provider, strategy)` writes `credential_pool_strategies[<provider>] = <strategy>`. `_supports_same_provider_pool_setup(provider)` returns False for empty/`custom`, True for `openrouter`, else True when `PROVIDER_REGISTRY[provider].auth_type` is `api_key` or `oauth_device_code`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `config.credential_pool_strategies`.
- **Config / env:** `credential_pool_strategies.<provider>`.
- **Edge cases / guards:** Unknown providers return False and the pooling prompt is skipped.
- **Rebuild notes:** per-provider {round-robin | failover} strategy stored alongside the pool.

### setup — reasoning-effort helpers  `id: cli-b.setup.reasoning-effort`
- **Surface:** Config
- **Where:** Used by model flows that offer a reasoning-effort choice.
- **What it does:** Reads/writes `agent.reasoning_effort`.
- **How it works:** `hermes_cli/setup.py:125-139`. `_current_reasoning_effort(config)` lower-cases and strips `agent.reasoning_effort`; `_set_reasoning_effort(config, effort)` creates the `agent` dict if missing and assigns.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `config.agent.reasoning_effort`.
- **Config / env:** `agent.reasoning_effort`.
- **Edge cases / guards:** returns `""` when unset or when `agent` is not a dict.
- **Rebuild notes:** trivial accessor pair.

### setup tts — Text-to-Speech Provider section  `id: cli-b.setup.tts`
- **Surface:** CLI
- **Where:** `hermes setup tts`; header "◆ Text-to-Speech Provider (optional)"; question "Select TTS provider:".
- **What it does:** Chooses which TTS backend voice output uses, prompts for its key (or installs the local model), and writes `tts.provider`.
- **How it works:** `hermes_cli/setup.py:1155-1389` (`_setup_tts_provider`), wrapped by `setup_tts` (`:1391-1393`). Prints `Current: <label>` from the label map `{edge:"Edge TTS", elevenlabs:"ElevenLabs", openai:"OpenAI TTS", xai:"xAI TTS", minimax:"MiniMax TTS", mistral:"Mistral Voxtral TTS", gemini:"Google Gemini TTS", neutts:"NeuTTS", kittentts:"KittenTTS"}`. The first choice, "Nous Subscription (managed OpenAI TTS, billed to your subscription)" (internal key `nous-openai`), appears only when `managed_nous_tools_enabled()` **and** `subscription_features.nous_auth_present`. On save: `config["tts"]["provider"] = selected`, `save_config`, then "TTS provider set to: <label>".
- **Inputs / options:** Menu items, verbatim and in order: (optional) "Nous Subscription (managed OpenAI TTS, billed to your subscription)"; "Edge TTS (free, cloud-based, no setup needed)"; "ElevenLabs (premium quality, needs API key)"; "OpenAI TTS (good quality, needs API key)"; "xAI TTS (Grok voices — OAuth login or API key)"; "MiniMax TTS (high quality with voice cloning, needs API key)"; "Mistral Voxtral TTS (multilingual, native Opus, needs API key)"; "Google Gemini TTS (30 prebuilt voices, prompt-controllable, needs API key)"; "NeuTTS (local on-device, free, ~300MB model download)"; "KittenTTS (local on-device, free, lightweight ~25-80MB ONNX)"; "Keep current (<label>)" (the default selection). Follow-up prompts per provider: ElevenLabs → "ElevenLabs API key" (masked) → `ELEVENLABS_API_KEY`; OpenAI → "OpenAI API key for TTS" (masked) → `VOICE_TOOLS_OPENAI_KEY`; xAI → menu "How do you want xAI TTS to authenticate?" with ["Sign in with xAI Grok OAuth (SuperGrok / Premium+) — browser login", "Paste an xAI API key (console.x.ai)", "Skip → fallback to Edge TTS"], then either the device-code login or "xAI API key for TTS" (masked) → `XAI_API_KEY`, followed by "xAI voice_id (Enter for 'eve', or paste a custom voice ID)" → `tts.xai.voice_id`; MiniMax → "MiniMax API key for TTS" → `MINIMAX_API_KEY`; Mistral → "Mistral API key for TTS" → `MISTRAL_API_KEY`; Gemini → prints "Get a free API key at https://aistudio.google.com/app/apikey" then "Gemini API key for TTS" → `GEMINI_API_KEY`; NeuTTS → "Install NeuTTS dependencies now?" (default Yes) after listing "  • Python package: neutts (~50MB install + ~300MB model on first use)" and "  • System package: espeak-ng (phonemizer)"; KittenTTS → prints "KittenTTS is lightweight (~25-80MB, CPU-only, no API key required)." and "Voices: Jasper, Bella, Luna, Bruno, Rosie, Hugo, Kiki, Leo", then "Install KittenTTS now?" (default Yes).
- **Outputs / side effects:** Writes `tts.provider` (and `tts.xai.voice_id`), saves API keys to `~/.hermes/.env`, may pip-install `neutts`/`kittentts`, may run the xAI device-code OAuth login and store tokens.
- **Config / env:** `tts.provider`, `tts.xai.voice_id`; env `ELEVENLABS_API_KEY`, `VOICE_TOOLS_OPENAI_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `MINIMAX_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`.
- **Edge cases / guards:** Every provider falls back to `edge` when its key prompt is left empty ("No API key provided. Falling back to Edge TTS."). Choosing the Nous option maps to provider `openai` plus the note "OpenAI TTS will use the managed Nous gateway and bill to your subscription." and, if direct OpenAI keys exist, the warning "Direct OpenAI credentials are still configured and may take precedence until removed from ~/.hermes/.env." Already-installed local engines print "NeuTTS is already installed" / "KittenTTS is already installed" and skip the install prompt. Declining an install prints "Skipping install. Set tts.provider to '<x>' after installing manually." and reverts to Edge.
- **Rebuild notes:** provider menu → credential/install gate → single config write, with a universal safe fallback. A better version would probe each backend with a 1-second synth test before committing the choice.

### setup tts — xAI OAuth helpers  `id: cli-b.setup.tts.xai-oauth`
- **Surface:** CLI
- **Where:** Inside the xAI branch of `hermes setup tts` (and reused by tools config).
- **What it does:** Detects an existing xAI Grok OAuth session and, if absent, runs the device-code login for side tools without switching the inference provider.
- **How it works:** `hermes_cli/setup.py:1098-1151`. `_xai_oauth_logged_in_for_setup()` returns `get_xai_oauth_auth_status()["logged_in"]`, swallowing exceptions. `_run_xai_oauth_login_from_setup()` imports `_is_remote_session`, `_save_xai_oauth_tokens`, `_xai_oauth_device_code_login`, `unsuppress_credential_source` from `hermes_cli.auth`; opens a browser unless the session is remote; prints "Signing in to xAI Grok OAuth (SuperGrok / Premium+)..."; on success saves the tokens with `auth_mode="oauth_device_code"` and `set_active=False` (so `model.provider` is untouched) and calls `unsuppress_credential_source("xai-oauth", "device_code")`; on failure prints "xAI Grok OAuth login failed: <exc>" and returns False.
- **Inputs / options:** none (browser/device-code interaction).
- **Outputs / side effects:** Writes xAI OAuth tokens into the auth store; clears the `device_code` suppression flag.
- **Config / env:** auth store; remote-session detection uses `SSH_CONNECTION`-style signals inside `_is_remote_session`.
- **Edge cases / guards:** Import failure prints "xAI Grok OAuth helpers unavailable: <exc>" and returns False.
- **Rebuild notes:** separate "credential for side tools" from "active inference provider" — the `set_active=False` flag is the key detail.

### setup terminal — Terminal Backend section  `id: cli-b.setup.terminal`
- **Surface:** CLI
- **Where:** `hermes setup terminal`, or step 2 of the full wizard; header "◆ Terminal Backend"; question "Select terminal backend:".
- **What it does:** Chooses where shell commands and code execution run — locally, in a container, or in a remote/cloud sandbox — and collects that backend's credentials.
- **How it works:** `hermes_cli/setup.py:1401-1767` (`setup_terminal_backend`). Intro lines: "Choose where Hermes runs shell commands and code.", "This affects tool execution, file access, and isolation.", "   Guide: https://hermes-agent.nousresearch.com/docs/user-guide/configuration#terminal-backend-configuration". Current backend from `cfg_get(config,"terminal","backend",default="local")`. Choices are built dynamically: six fixed entries, then "Singularity/Apptainer - HPC-friendly container" only on Linux, then one entry per plugin-registered provider from `agent.terminal_env_registry.list_providers()` rendered as `"<display_name> - <description>"`, then "Keep current (<backend>)" as the default. Selecting the keep entry prints "Keeping current backend: <backend>" and returns without writing. Otherwise `config["terminal"]["backend"]` is set, the per-backend branch runs, and finally `save_env_value("TERMINAL_ENV", selected_backend)` (plus `TERMINAL_MODAL_MODE` for modal and `TERMINAL_VERCEL_RUNTIME` for vercel_sandbox), `save_config`, and "Terminal backend set to: <backend>".
- **Inputs / options:** Fixed menu entries, verbatim: `[0] "Local - run directly on this machine (default)"` → `local`; `[1] "Docker - isolated container with configurable resources"` → `docker`; `[2] "Modal - serverless cloud sandbox"` → `modal`; `[3] "SSH - run on a remote machine"` → `ssh`; `[4] "Daytona - persistent cloud development environment"` → `daytona`; `[5] "Vercel Sandbox - cloud microVM with snapshot filesystem persistence"` → `vercel_sandbox`; `[6, Linux only] "Singularity/Apptainer - HPC-friendly container"` → `singularity`; then plugin backends; then `"Keep current (<current>)"`.
- **Outputs / side effects:** `terminal.backend` (+ backend-specific keys), `TERMINAL_ENV` in `.env`, possible pip installs (`modal`, `daytona`, `vercel`).
- **Config / env:** `terminal.backend`, `terminal.cwd`, `terminal.docker_image`, `terminal.singularity_image`, `terminal.daytona_image`, `terminal.modal_mode`, `terminal.vercel_runtime`, `terminal.container_*`, `proxy.enabled`, `proxy.enforce_on_docker`; env `TERMINAL_ENV`, `TERMINAL_MODAL_MODE`, `TERMINAL_VERCEL_RUNTIME`, `TERMINAL_SSH_HOST/USER/PORT/KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `DAYTONA_API_KEY`, `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`, `VERCEL_OIDC_TOKEN` (removed).
- **Edge cases / guards:** Plugin discovery is wrapped in a bare `except Exception: pass` so a broken plugin cannot take the wizard down; a plugin backend's `post_setup()` failure prints "Backend plugin setup hook failed: <exc>".
- **Rebuild notes:** a backend registry where each entry owns {label, description, availability probe, credential prompts, post-setup hook}; the built-ins should use the same interface the plugins do.

### setup terminal — Local backend  `id: cli-b.setup.terminal.local`
- **Surface:** CLI
- **Where:** Choice "Local - run directly on this machine (default)".
- **What it does:** Runs commands directly on the host with no isolation.
- **How it works:** `hermes_cli/setup.py:1468-1474`. Prints "Terminal backend: Local" and "Commands run directly on this machine.", then `config["terminal"].setdefault("cwd", str(Path.home()))`.
- **Inputs / options:** none.
- **Outputs / side effects:** `terminal.backend=local`, `terminal.cwd=<home>`, `TERMINAL_ENV=local`.
- **Config / env:** `terminal.cwd`.
- **Edge cases / guards:** sudo stays off; both cwd and sudo are tunable later via config.
- **Rebuild notes:** default cwd to the user's home so the gateway does not inherit a random directory.

### setup terminal — Docker backend  `id: cli-b.setup.terminal.docker`
- **Surface:** CLI
- **Where:** Choice "Docker - isolated container with configurable resources".
- **What it does:** Runs commands in a Docker container and optionally turns on the egress credential firewall.
- **How it works:** `hermes_cli/setup.py:1476-1508`. Prints "Terminal backend: Docker"; `shutil.which("docker")` missing → "Docker not found in PATH!" + "Install Docker: https://docs.docker.com/get-docker/", else "Docker found: <path>". Sets `terminal.docker_image` default `nikolaik/python-nodejs:python3.11-nodejs20`. Then the egress pitch: "Docker sandboxes can be protected with the egress credential firewall.", "It routes sandbox traffic through iron-proxy so containers receive proxy tokens instead of real API keys.", "   Docker only for now; Modal, SSH, Daytona, and Singularity are not wired yet."
- **Inputs / options:** `prompt_yes_no("  Enable egress firewall for Docker sandboxes?", False)`.
- **Outputs / side effects:** Yes → `proxy.enabled=True`, `proxy.enforce_on_docker` defaulted True, prints "Egress firewall enabled in config" + "Run `hermes egress setup` then `hermes egress start` to mint tokens and launch the proxy." No → "Skipping egress firewall. You can enable it later with `hermes egress setup`."
- **Config / env:** `terminal.docker_image`, `proxy.enabled`, `proxy.enforce_on_docker`.
- **Edge cases / guards:** A missing docker binary is a warning, not a blocker — the backend is still selected.
- **Rebuild notes:** pair sandboxing with credential redaction; make the firewall the default rather than an opt-in.

### setup terminal — Singularity/Apptainer backend  `id: cli-b.setup.terminal.singularity`
- **Surface:** CLI
- **Where:** Choice "Singularity/Apptainer - HPC-friendly container" (Linux only).
- **What it does:** Runs commands inside a Singularity/Apptainer container for HPC clusters.
- **How it works:** `hermes_cli/setup.py:1510-1527`. Prints "Terminal backend: Singularity/Apptainer"; probes `shutil.which("apptainer") or shutil.which("singularity")` → "Found: <path>" or "Singularity/Apptainer not found in PATH!" + "Install: https://apptainer.org/docs/admin/main/installation.html". Sets `terminal.singularity_image` default `docker://nikolaik/python-nodejs:python3.11-nodejs20`.
- **Inputs / options:** none beyond the backend choice.
- **Outputs / side effects:** `terminal.backend=singularity`, `terminal.singularity_image`, `TERMINAL_ENV=singularity`.
- **Config / env:** `terminal.singularity_image`.
- **Edge cases / guards:** The menu entry is hidden on non-Linux (`platform.system() == "Linux"`).
- **Rebuild notes:** same shape as Docker with a `docker://` image URI.

### setup terminal — Modal backend  `id: cli-b.setup.terminal.modal`
- **Surface:** CLI
- **Where:** Choice "Modal - serverless cloud sandbox".
- **What it does:** Runs each session in a serverless Modal container, billed either to your Nous subscription or to your own Modal account.
- **How it works:** `hermes_cli/setup.py:1529-1601`. Prints "Terminal backend: Modal" and "Serverless cloud sandboxes. Each session gets its own container." Managed mode is offered only when `managed_nous_tools_enabled()` **and** `nous_auth_present` **and** `is_managed_tool_gateway_ready("modal")`. Default index: 0 when `modal_mode == "managed"`, 1 when `"direct"`, else 1 if `MODAL_TOKEN_ID` is set else 0.
- **Inputs / options:** Menu "Select how Modal execution should be billed:" with ["Use my Nous subscription", "Use my own Modal account"]. Direct mode prompts "    Modal Token ID" (masked) and "    Modal Token Secret" (masked); when a token already exists it first asks "  Update Modal credentials?" (default No) after printing "  Modal token: already configured".
- **Outputs / side effects:** `terminal.modal_mode` = `managed` or `direct`; `TERMINAL_MODAL_MODE` in `.env`; `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` saved; may pip-install the `modal` SDK via `hermes_cli.tools_config._pip_install(["modal"])` printing "Installing modal SDK...", then "modal SDK installed" or "Install failed — run manually: uv pip install modal".
- **Config / env:** `terminal.modal_mode`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `TERMINAL_MODAL_MODE`.
- **Edge cases / guards:** Managed mode prints "Modal execution will use the managed Nous gateway and bill to your subscription." and, when direct tokens also exist, "Direct Modal credentials are still configured, but this backend is pinned to managed mode." Direct mode prints "Requires a Modal account: https://modal.com" and "  Get your token at: https://modal.com/settings".
- **Rebuild notes:** an explicit billing-mode switch with a deterministic default derived from existing credentials.

### setup terminal — Daytona backend  `id: cli-b.setup.terminal.daytona`
- **Surface:** CLI
- **Where:** Choice "Daytona - persistent cloud development environment".
- **What it does:** Runs each session in a persistent Daytona sandbox with a durable filesystem.
- **How it works:** `hermes_cli/setup.py:1603-1643`. Prints "Terminal backend: Daytona", "Persistent cloud development environments.", "Each session gets a dedicated sandbox with filesystem persistence.", "Sign up at: https://daytona.io". Installs the `daytona` SDK when missing ("Installing daytona SDK..." → "daytona SDK installed" / "Install failed — run manually: uv pip install daytona" plus "  Error: <last stderr line>"). Sets `terminal.daytona_image` default `nikolaik/python-nodejs:python3.11-nodejs20`.
- **Inputs / options:** "    Daytona API key" (masked). When one exists: "  Daytona API key: already configured" then "  Update API key?" (default No) → on yes re-prompt and print "    Updated"; fresh key prints "    Configured".
- **Outputs / side effects:** `DAYTONA_API_KEY` in `.env`; `terminal.daytona_image`; `TERMINAL_ENV=daytona`.
- **Config / env:** `terminal.daytona_image`, `DAYTONA_API_KEY`.
- **Edge cases / guards:** SDK install failure is non-fatal.
- **Rebuild notes:** same credential-then-image pattern as Docker/Modal.

### setup terminal — Vercel Sandbox backend  `id: cli-b.setup.terminal.vercel`
- **Surface:** CLI
- **Where:** Choice "Vercel Sandbox - cloud microVM with snapshot filesystem persistence".
- **What it does:** Runs commands in a Vercel microVM whose filesystem persists via snapshots.
- **How it works:** `hermes_cli/setup.py:1645-1684` for the branch and `setup.py:845-911` (`_prompt_vercel_sandbox_settings`) for the questions. The branch prints "Terminal backend: Vercel Sandbox", "Cloud microVM sandboxes with snapshot-backed filesystem persistence.", "Requires the optional SDK: pip install 'hermes-agent[vercel]'", then installs the `vercel` SDK preferring the managed uv (`ensure_uv()` → `uv pip install --python <sys.executable> vercel`) and falling back to `python -m pip install vercel`. Settings block prints "Vercel Sandbox settings:", "  Filesystem persistence uses Vercel snapshots.", "  Snapshots restore files only; live processes do not continue after sandbox recreation." Auth block prints "Vercel authentication:", "  Use a long-lived Vercel access token plus project/team IDs." and, when a `.vercel/project.json` is found by walking up from cwd (`_read_nearest_vercel_project`, `setup.py:914-948`), "  Found defaults in nearest .vercel/project.json." It always calls `remove_env_value("VERCEL_OIDC_TOKEN")` first.
- **Inputs / options:** "  Runtime (<comma-joined _SUPPORTED_VERCEL_RUNTIMES>)" default `node24`; "  Persist filesystem with snapshots? (yes/no)"; "  CPU cores"; "  Memory in MB (5120 = 5GB)"; "    Vercel access token" (masked); "    Vercel project ID" (default from `.vercel/project.json` `projectId`); "    Vercel team ID" (default from `orgId`).
- **Outputs / side effects:** `terminal.vercel_runtime`, `terminal.container_persistent`, `terminal.container_cpu`, `terminal.container_memory`, `terminal.container_disk` (forced to 51200); env `TERMINAL_VERCEL_RUNTIME`, `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`; `VERCEL_OIDC_TOKEN` deleted.
- **Config / env:** as above.
- **Edge cases / guards:** An unsupported runtime prints "Unsupported Vercel runtime '<x>', keeping <current>." and falls back to the current value or `node24`. A custom `container_disk` other than 0/51200 prints "Vercel Sandbox does not support custom disk sizing; resetting container_disk to 51200." Truthy yes-values are `{yes,true,y,1}`; non-numeric CPU/memory entries are silently ignored.
- **Rebuild notes:** hide knobs the platform does not support instead of accepting then resetting them.

### setup terminal — SSH backend  `id: cli-b.setup.terminal.ssh`
- **Surface:** CLI
- **Where:** Choice "SSH - run on a remote machine".
- **What it does:** Runs every command over SSH on a remote host, with an optional live connection test.
- **How it works:** `hermes_cli/setup.py:1699-1745`. Prints "Terminal backend: SSH" and "Run commands on a remote machine via SSH." Each answer is saved to `.env` immediately. The test builds `ssh -o BatchMode=yes -o ConnectTimeout=5 [-i <key>] [-p <port>] <user@host> echo ok` with a 10-second subprocess timeout.
- **Inputs / options:** "  SSH host (hostname or IP)" (default = current `TERMINAL_SSH_HOST`); "  SSH user" (default = current value or `$USER`); "  SSH port" (default current or "22" — only saved when it differs from 22); "  SSH private key path" (default current or `~/.ssh/id_rsa`); "  Test SSH connection?" (default Yes, only asked when a host was given).
- **Outputs / side effects:** `TERMINAL_SSH_HOST`, `TERMINAL_SSH_USER`, `TERMINAL_SSH_PORT`, `TERMINAL_SSH_KEY` in `.env`; `TERMINAL_ENV=ssh`.
- **Config / env:** the four `TERMINAL_SSH_*` vars.
- **Edge cases / guards:** Test success prints "  SSH connection successful!"; failure prints "  SSH connection failed: <stderr>" and "  Check your SSH key and host settings." — a failed test does not block the selection.
- **Rebuild notes:** validate connectivity before committing, and offer to append the key to the agent.

### setup terminal — container resource prompts  `id: cli-b.setup.terminal.container-resources`
- **Surface:** CLI
- **Where:** `_prompt_container_resources` — the shared block for Docker/Singularity/Modal/Daytona resource sizing.
- **What it does:** Asks for filesystem persistence and CPU/memory/disk limits for container backends.
- **How it works:** `hermes_cli/setup.py:803-842`. Prints "Container Resource Settings:", "  Persistent filesystem keeps files between sessions.", "  Set to 'no' for ephemeral sandboxes that reset each time."
- **Inputs / options:** "  Persist filesystem across sessions? (yes/no)" (default from `terminal.container_persistent`, default True); "  CPU cores" (default `terminal.container_cpu`, default 1, parsed as float); "  Memory in MB (5120 = 5GB)" (default `terminal.container_memory`, default 5120, int); "  Disk in MB (51200 = 50GB)" (default `terminal.container_disk`, default 51200, int).
- **Outputs / side effects:** `terminal.container_persistent`, `terminal.container_cpu`, `terminal.container_memory`, `terminal.container_disk`.
- **Config / env:** as above.
- **Edge cases / guards:** Unparseable numbers keep the previous value (silent `except ValueError: pass`). Truthy set `{yes,true,y,1}`. In v2026.8.31 the main backend branches set image defaults without calling this helper — it stays available for the Vercel variant and for callers that want the full sizing block.
- **Rebuild notes:** validate ranges and show the provider's real limits instead of silently ignoring bad input.

### setup agent — Agent Settings section  `id: cli-b.setup.agent`
- **Surface:** CLI
- **Where:** `hermes setup agent`; header "◆ Agent Settings".
- **What it does:** Tunes max iterations, tool-progress verbosity, context-compression threshold, and the session-reset policy.
- **How it works:** `hermes_cli/setup.py:1798-1976` (`setup_agent_settings`). Prints "   Guide: https://hermes-agent.nousresearch.com/docs/user-guide/configuration". Four blocks in order: Max Iterations, Tool Progress Display, "◆ Context Compression", "◆ Session Reset Policy". Note this section is **not** part of the four-step full wizard — new installs silently get `_apply_default_agent_settings` instead.
- **Inputs / options:** (1) "Max iterations" — default `agent.max_turns` (fallback 90); help lines "Maximum tool-calling iterations per conversation.", "Higher = more complex tasks, but costs more tokens.", "Press Enter to keep <n>. Use 90 for most tasks or 150+ for open exploration." (2) "Tool progress mode" — default `display.tool_progress` (fallback "all"); the five documented values, verbatim: "  off     — Silent, just the final response", "  new     — Show tool name only when it changes (less noise)", "  all     — Show every tool call with a short preview", "  verbose — Full args, results, and debug logs", "  log     — Silent in chat; write every tool call to ~/.hermes/logs/tool_calls.log (gateway only)". (3) "Compression threshold (0.5-0.95)" — default `compression.threshold` (fallback 0.50). (4) Menu "Session reset mode:" with exactly: `[0] "Inactivity + daily reset (reset whichever comes first)"`, `[1] "Inactivity only (reset after N minutes of no messages)"`, `[2] "Daily only (reset at a fixed hour each day)"`, `[3] "Never auto-reset (recommended - context lives until /reset or context compression)"`, `[4] "Keep current settings"`; default index derived from the current mode via `{"both":0,"idle":1,"daily":2,"none":3}` (fallback 3). Sub-prompts: "  Inactivity timeout (minutes)" (default `session_reset.idle_minutes`, fallback 1440) and "  Daily reset hour (0-23, local time)" (default `session_reset.at_hour`, fallback 4).
- **Outputs / side effects:** `agent.max_turns` (and deletes any legacy top-level `max_turns`), removes `HERMES_MAX_ITERATIONS` from `.env`, `display.tool_progress`, `compression.enabled=True` + `compression.threshold`, `session_reset.mode`/`idle_minutes`/`at_hour`. Success lines: "Max iterations set to <n>", "Tool progress set to: <mode>", "Context compression threshold set to <t>", and per mode "Sessions reset after <n> min idle or daily at <h>:00" / "Sessions reset after <n> min of inactivity" / "Sessions reset daily at <h>:00". Mode 3 prints "Sessions will never auto-reset. Context is managed only by compression." plus the warning "Long conversations will grow in cost. Use /reset manually when needed."
- **Config / env:** `agent.max_turns`, `display.tool_progress`, `compression.enabled`, `compression.threshold`, `session_reset.mode|idle_minutes|at_hour`; env `HERMES_MAX_ITERATIONS` (removed, never written).
- **Edge cases / guards:** A non-integer iteration count prints "Invalid number, keeping current value"; an unknown progress mode prints "Unknown mode '<x>', keeping '<current>'"; a threshold outside 0.5–0.95 (or unparseable) is silently ignored; an out-of-range hour or non-positive idle is ignored.
- **Rebuild notes:** config.yaml as the single source of truth with an explicit purge of the shadowing env var — this is the fix for the historical "60-vs-500 iterations" bug.

### setup — recommended agent defaults (silent)  `id: cli-b.setup.agent-defaults`
- **Surface:** Core
- **Where:** Applied automatically on a first install (full wizard and quick setup) — no prompts.
- **What it does:** Writes the recommended agent settings so a new user never sees the Agent Settings questions.
- **How it works:** `hermes_cli/setup.py:1770-1795` (`_apply_default_agent_settings`): `agent.max_turns = 150`, `remove_env_value("HERMES_MAX_ITERATIONS")`, `display.tool_progress = "all"`, `compression.enabled = True`, `compression.threshold = 0.50`, `session_reset.mode = "none"`, then `save_config`.
- **Inputs / options:** none.
- **Outputs / side effects:** Prints "Applied recommended defaults:" then "  Max iterations: 150", "  Tool progress: all", "  Compression threshold: 0.50", "  Session reset: never (use /reset or compression)", "  Run `hermes setup agent` later to customize."
- **Config / env:** as listed.
- **Edge cases / guards:** Existing installs keep whatever they already have — the helper is only called when `is_existing` is False.
- **Rebuild notes:** state the applied defaults out loud instead of hiding them.

### setup gateway — Messaging Platforms section  `id: cli-b.setup.gateway`
- **Surface:** CLI
- **Where:** `hermes setup gateway`, or step 3 of the full wizard; header "◆ Messaging Platforms"; checklist title "Select platforms to configure:".
- **What it does:** Multi-selects which messaging platforms to configure, runs each platform's wizard, then installs/starts (or offers to restart) the gateway service.
- **How it works:** `hermes_cli/setup.py:2264-2404` (`setup_gateway`). Intro: "Connect to messaging platforms to chat with Hermes from anywhere.", "Toggle with Space, confirm with Enter." Items come from `hermes_cli.gateway._all_platforms()` rendered as `"<emoji> <label>  (<status>)"` via `_platform_status(plat)`; already-`configured` rows are pre-selected. Each chosen index runs `_configure_platform(platform)` — the same per-platform wizards documented under `cli-b.gateway.setup.*`. Then it recomputes "did the user make progress" with `_is_progress(status)` = not (`"not configured"` or startswith `"partially"` or startswith `"plugin disabled"`).
- **Inputs / options:** The checklist (Space toggles, Enter confirms on "Continue →"); afterwards, when the service is already running and something changed, "  Restart the gateway to pick up changes?" (default Yes).
- **Outputs / side effects:** Platform credentials in `.env`; a `hermes-gateway` service installed/started via `ensure_gateway_service(context="setup")` when not already running; a restart via `systemd_restart()` / `launchd_restart()` / `gateway_windows.restart()` otherwise. Prints a `━`×50 rule and "Messaging platforms configured!" when any platform is in progress; "No platforms selected. Run 'hermes setup gateway' later to configure." when nothing was picked.
- **Config / env:** every platform env var; `HERMES_HOME` for service naming.
- **Edge cases / guards:** Missing home channels are reported: it checks Telegram (`TELEGRAM_BOT_TOKEN` without `TELEGRAM_HOME_CHANNEL`), Discord, Slack, BlueBubbles (`BLUEBUBBLES_SERVER_URL`), and QQBot (`QQ_APP_ID` without `QQBOT_HOME_CHANNEL`/`QQ_HOME_CHANNEL`) and prints "No home channel set for: <list>", "   Without a home channel, cron jobs and cross-platform", "   messages can't be delivered to those platforms.", "   Set one later with /set-home in your chat, or:", then one `hermes config set <PLAT>_HOME_CHANNEL <channel_id>` line per platform. The service block runs **unconditionally**, even with zero platforms, so cron keeps working. `UserSystemdUnavailableError` → "  Restart failed — user systemd not reachable:" plus the indented message; `SystemScopeRequiresRootError` → "  Restart failed: <e>" plus `_print_system_scope_remediation("restart")`; any other exception → "  Restart failed: <e>". When `_system_scope_wizard_would_need_root()` is true the restart prompt is replaced by the remediation text.
- **Rebuild notes:** checklist over a platform registry + one wizard per platform + an unconditional service reconcile. The "install the service even with no platforms" rule is load-bearing for cron.

### setup gateway — built-in Telegram wizard (setup.py copy)  `id: cli-b.setup.gateway.telegram`
- **Surface:** CLI
- **Where:** `_setup_telegram()` — header "◆ Telegram".
- **What it does:** Creates or accepts a Telegram bot token, sets the user allowlist, and sets the home channel.
- **How it works:** `hermes_cli/setup.py:2027-2143`. When `TELEGRAM_BOT_TOKEN` already exists it prints "Telegram: already configured" and asks "Reconfigure Telegram?" (default No); declining still offers to fix a missing allowlist ("⚠️  Telegram has no user allowlist - anyone can use your bot!" → "Add allowed users now?" default Yes → "   To find your Telegram user ID: message @userinfobot" → "Allowed user IDs (comma-separated)"). The creation menu is a plain text prompt, printed verbatim as "  [1] Automatic (recommended)", "      Scan a QR code → confirm in Telegram → done.", "      No token copy-paste needed.", "  [2] Manual", "      Create a bot via @BotFather yourself and paste the token.", then `prompt("Choice [1/2]", default="1")`. Choice 1 calls `_setup_telegram_auto_result()` → `hermes_cli.telegram_managed_bot.auto_setup_telegram_bot_result(profile_name=…)` where the profile name is the HERMES_HOME directory name when its parent is `profiles` (`_profile_name_from_hermes_home`, `setup.py:1999-2004`). Token shape is validated with `^\d+:[A-Za-z0-9_-]{30,}$` (`_TELEGRAM_BOT_TOKEN_RE`, `setup.py:1979-1981`).
- **Inputs / options:** "Choice [1/2]" (default 1); "Telegram bot token" (masked, looped until valid or empty); "Allow this Telegram account to use the bot?" (default Yes, only when auto-setup detected an owner id); "Additional allowed user IDs (comma-separated, optional)"; "Allowed user IDs (comma-separated, leave empty for open access)"; "Use your user ID (<id>) as the home channel?" (default Yes); "Home channel ID (or leave empty to set later with /set-home in Telegram)"; "Home channel ID (leave empty to set later)".
- **Outputs / side effects:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` (spaces stripped), `TELEGRAM_HOME_CHANNEL` in `.env`. Messages: "Telegram token saved", "🔒 Security: Restrict who can use your bot", "   To find your Telegram user ID:", "   1. Message @userinfobot on Telegram", "   2. It will reply with your numeric ID (e.g., 123456789)", "Detected your Telegram user ID: <id>", "Telegram allowlist configured - only listed users can use the bot", "⚠️  No allowlist set - anyone who finds your bot can use it!", "📬 Home Channel: where Hermes delivers cron job results,", "   cross-platform messages, and notifications.", "   For Telegram DMs, this is your user ID (same as above).", "Telegram home channel set to <id>".
- **Config / env:** the three `TELEGRAM_*` vars.
- **Edge cases / guards:** An invalid pasted token prints "Invalid token format. Expected: <numeric_id>:<alphanumeric_hash> (e.g., 123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ)" and re-asks. A malformed token from the automatic path prints "Automatic setup returned an invalid Telegram bot token." and falls back with "Falling back to manual setup...".
- **Rebuild notes:** QR-based bot provisioning with a strict token regex and an allowlist prompt that cannot be skipped silently.

### setup gateway — built-in BlueBubbles (iMessage) wizard  `id: cli-b.setup.gateway.bluebubbles`
- **Surface:** CLI
- **Where:** `_setup_bluebubbles()` — header "◆ BlueBubbles (iMessage)".
- **What it does:** Points Hermes at a BlueBubbles macOS server so it can send and receive iMessages.
- **How it works:** `hermes_cli/setup.py:2146-2208`. Already-configured check on `BLUEBUBBLES_SERVER_URL` → "BlueBubbles: already configured" + "Reconfigure BlueBubbles?" (default No). Intro lines: "Connects Hermes to iMessage via BlueBubbles — a free, open-source", "macOS server that bridges iMessage to any device.", "   Requires a Mac running BlueBubbles Server v1.0.0+", "   Download: https://bluebubbles.app/", "In BlueBubbles Server → Settings → API, note your Server URL and Password."
- **Inputs / options:** "BlueBubbles server URL (e.g. http://192.168.1.10:1234)" (required); "BlueBubbles server password" (masked, required); "Allowed iMessage addresses (comma-separated, leave empty for open access)"; "Home channel address (leave empty to set later)"; "Configure webhook listener settings?" (default No) → "Webhook listener port (default: 8645)".
- **Outputs / side effects:** `BLUEBUBBLES_SERVER_URL` (trailing `/` stripped), `BLUEBUBBLES_PASSWORD`, `BLUEBUBBLES_ALLOWED_USERS`, `BLUEBUBBLES_HOME_CHANNEL`, `BLUEBUBBLES_WEBHOOK_PORT`. Messages: "BlueBubbles credentials saved", "🔒 Security: Restrict who can message your bot", "   Use iMessage addresses: email (user@icloud.com) or phone (+15551234567)", "BlueBubbles allowlist configured", "⚠️  No allowlist set — anyone who can iMessage you can use the bot!", "📬 Home Channel: phone or email for cron job delivery and notifications.", "   You can also set this later with /set-home in your iMessage chat.", "Advanced settings (defaults are fine for most setups):", "Webhook port set to <p>", then the closing note "Requires the BlueBubbles Private API helper for typing indicators,", "read receipts, and tapback reactions. Basic messaging works without it.", "   Install: https://docs.bluebubbles.app/helper-bundle/installation".
- **Config / env:** the five `BLUEBUBBLES_*` vars.
- **Edge cases / guards:** Empty URL → "Server URL is required — skipping BlueBubbles setup" and return; empty password → "Password is required — skipping BlueBubbles setup" and return; a non-integer port → "Invalid port number, using default 8645".
- **Rebuild notes:** required-field gating with an explicit abort message rather than storing a half-configured platform.

### setup gateway — QQ Bot delegation  `id: cli-b.setup.gateway.qqbot`
- **Surface:** CLI
- **Where:** `_setup_qqbot()` in the setup module.
- **What it does:** Runs the QQ Bot (Official API v2) wizard.
- **How it works:** `hermes_cli/setup.py:2211-2214` — a two-line shim that imports `hermes_cli.gateway._setup_qqbot` and calls it, so `hermes setup gateway` and `hermes gateway setup` share one implementation (documented at `cli-b.gateway.setup.qqbot`).
- **Inputs / options:** delegated.
- **Outputs / side effects:** delegated (`QQ_APP_ID`, `QQ_APP_SECRET`, `QQBOT_HOME_CHANNEL`, …).
- **Config / env:** delegated.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** never fork a platform wizard between two entry points.

### setup gateway — Webhooks wizard  `id: cli-b.setup.gateway.webhooks`
- **Surface:** CLI
- **Where:** `_setup_webhooks()` — header "◆ Webhooks".
- **What it does:** Turns on the inbound webhook listener, sets its port and a global HMAC secret.
- **How it works:** `hermes_cli/setup.py:2217-2261`. Already-configured check on `WEBHOOK_ENABLED` → "Webhooks: already configured" + "Reconfigure webhooks?" (default No). Prints the security warning "⚠  Webhook and SMS platforms require exposing gateway ports to the", "   internet. For security, run the gateway in a sandboxed environment", "   (Docker, VM, etc.) to limit blast radius from prompt injection.", then "   Full guide: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/".
- **Inputs / options:** "Webhook port (default 8644)"; "Global HMAC secret (shared across all routes)" (masked).
- **Outputs / side effects:** `WEBHOOK_PORT`, `WEBHOOK_SECRET`, `WEBHOOK_ENABLED=true`. Closing block: "Webhooks enabled! Next steps:", "   1. Define webhook routes in <hermes_home>/config.yaml", "   2. Point your service (GitHub, GitLab, etc.) at:", "      http://your-server:8644/webhooks/<route-name>", "   Route configuration guide:", "   https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/#configuring-routes", "   Open config in your editor:  hermes config edit" (printed **twice** — a duplicated line at `setup.py:2260-2261`).
- **Config / env:** `WEBHOOK_PORT`, `WEBHOOK_SECRET`, `WEBHOOK_ENABLED`.
- **Edge cases / guards:** Non-integer port → "Invalid port number, using default 8644". Empty secret → "No secret set — you must configure per-route secrets in config.yaml".
- **Rebuild notes:** default-deny (require a secret) instead of warning about it.

### setup tools — Tools section  `id: cli-b.setup.tools`
- **Surface:** CLI
- **Where:** `hermes setup tools`, or step 4 of the full wizard.
- **What it does:** Opens the unified tool selector — platform selection → toolset toggles → provider/API-key configuration.
- **How it works:** `hermes_cli/setup.py:2410-2424` (`setup_tools`) is a thin delegation to `hermes_cli.tools_config.tools_command(first_install=<not is_existing>, config=config)`, the exact same entry point `hermes tools` uses. `first_install=True` selects the simplified flow (no platform menu; prompt for every unconfigured API key).
- **Inputs / options:** All prompts belong to `tools_command` (documented by the `hermes tools` shard). The only input decided here is the `first_install` flag.
- **Outputs / side effects:** `platform_toolsets.*` and tool provider keys in `.env`.
- **Config / env:** `platform_toolsets.*`, tool API keys.
- **Edge cases / guards:** `tools_command` performs its own load/save cycle, so Blank Slate re-syncs the wizard's dict afterwards.
- **Rebuild notes:** one selector shared by wizard and standalone command, with a "first install" variant that skips the platform picker.

### setup telemetry — Shared Metrics section  `id: cli-b.setup.telemetry`
- **Surface:** CLI
- **Where:** `hermes setup telemetry`; header "◆ Shared Metrics".
- **What it does:** Turns the local, privacy-safe shared-metrics subscriber on or off.
- **How it works:** `hermes_cli/setup.py:2430-2458` (`setup_telemetry`). Prints "Shared metrics contain only bounded counters and histograms." and "Packages stay under this Hermes profile and are not uploaded." Then it ensures `telemetry` and `telemetry.shared_metrics` are dicts and asks a single yes/no whose default is the current value (`shared_metrics.enabled is True`).
- **Inputs / options:** "Enable local shared metrics?" (default = current state).
- **Outputs / side effects:** `telemetry.shared_metrics.enabled`; prints "Local shared metrics enabled." or "Local shared metrics disabled." Note the section itself does **not** call `save_config` — the caller (`_run_setup_wizard_impl`'s section path) saves afterwards.
- **Config / env:** `telemetry.shared_metrics.enabled`.
- **Edge cases / guards:** Non-dict `telemetry`/`shared_metrics` values are replaced with fresh dicts.
- **Rebuild notes:** one boolean, stated plainly, with "nothing is uploaded" in the copy.

### setup — section runner (`hermes setup <section>`)  `id: cli-b.setup.section-runner`
- **Surface:** CLI
- **Where:** `hermes setup model|tts|terminal|gateway|tools|telemetry|agent`.
- **What it does:** Runs exactly one wizard section inside its own navigation scope and saves.
- **How it works:** `hermes_cli/setup.py:3130-3160`. `SETUP_SECTIONS` (`setup.py:2858-2866`) is the ordered table `[("model","Model & Provider",setup_model_provider), ("tts","Text-to-Speech",setup_tts), ("terminal","Terminal Backend",setup_terminal_backend), ("gateway","Messaging Platforms (Gateway)",setup_gateway), ("tools","Tools",setup_tools), ("telemetry","Shared Metrics",setup_telemetry), ("agent","Agent Settings",setup_agent_settings)]`. The banner is `┌…┐` / `│     ⚕ Hermes Setup — <label left-padded to 34> │` / `└…┘`. After the section it calls `save_config(config)` and prints "<label> configuration complete!".
- **Inputs / options:** the positional `section` value.
- **Outputs / side effects:** config write + completion line.
- **Config / env:** n/a.
- **Edge cases / guards:** An unrecognised section (only reachable when argparse `choices` is bypassed) prints "Unknown setup section: <x>" and "Available sections: model, tts, terminal, gateway, tools, telemetry, agent".
- **Rebuild notes:** one ordered table drives both the full wizard and the per-section entry point.

### setup --portal — one-shot Nous Portal setup  `id: cli-b.setup.portal`
- **Surface:** CLI
- **Where:** `hermes setup --portal` (and the standalone `hermes portal`, owned by a sibling shard).
- **What it does:** Logs into Nous Portal via OAuth, picks a Nous model, sets Nous as the inference provider, and offers the Tool Gateway — then stops.
- **How it works:** `hermes_cli/setup.py:2869-2951` (`_run_portal_one_shot`). Banner `│     ⚕ Hermes Setup — Nous Portal (one-shot)             │`; copy: "  One subscription, 300+ models, plus the Tool Gateway:", "    web search, image generation, TTS, browser automation", "    — all routed through your Nous Portal sub.", "  Sign up: https://portal.nousresearch.com/manage-subscription". Everything is delegated to `hermes_cli.main._model_flow_nous(config)` so `hermes portal`, `setup --portal` and quick setup share one Nous onboarding path. Afterwards it re-reads `load_config()` into the same dict.
- **Inputs / options:** none of its own; the device-code login and model picker come from `_model_flow_nous`.
- **Outputs / side effects:** Nous OAuth tokens in the auth store, `model.provider=nous`, `model.default=<chosen>`, Tool Gateway opt-in. Success prints "Portal setup complete.", "  Run `hermes portal info` to inspect routing.", "  Run `hermes` to start chatting."
- **Config / env:** `model.*`, Nous auth state.
- **Edge cases / guards:** `KeyboardInterrupt`, `EOFError` **and** `SystemExit` are all treated as a graceful cancel ("  Setup cancelled." + "  You can retry later with `hermes portal`.") — `SystemExit` is caught explicitly because `_login_nous` raises `SystemExit(130)`/`SystemExit(1)` and the expired-session re-login path only catches `Exception`. Other exceptions print "  Nous Portal setup encountered an error: <exc>" and the same retry hint.
- **Rebuild notes:** a single shareable "zero to working agent" command; catch `SystemExit` when delegating into code that uses it as control flow.

### setup — first-time Quick Setup (Nous Portal track)  `id: cli-b.setup.quick-firsttime`
- **Surface:** CLI
- **Where:** First-run menu choice 0, "Quick Setup (Nous Portal) — free OAuth login, no API keys, model + tools (recommended)".
- **What it does:** Four steps: Nous Portal login + model, terminal backend, recommended defaults, optional messaging.
- **How it works:** `hermes_cli/setup.py:3354-3432` (`_run_first_time_quick_setup`). Step 1 prints header "◆ Nous Portal" then "One subscription, 300+ models, plus the Tool Gateway:", "  web search, image generation, TTS, browser automation.", "Sign up: https://portal.nousresearch.com/manage-subscription", then `_model_flow_nous(config)` and a config re-sync. Step 2 `setup_terminal_backend(config)`. Step 3 `_apply_default_agent_settings(config)` + `save_config`. Step 4 the messaging question below. Ends with `_print_macos_fda_tip()` and `_print_setup_summary(config, hermes_home)`.
- **Inputs / options:** Menu "Connect a messaging platform? (Telegram, Discord, etc.)" with `[0] "Set up messaging now (recommended)"` and `[1] "Skip — set up later with 'hermes setup gateway'"`, default 0.
- **Outputs / side effects:** Choice 0 → `setup_gateway(config)` + `save_config`. Choice 1 → `ensure_gateway_service(context="setup")` anyway, so cron jobs run and platforms activate as soon as tokens appear (e.g. via `hermes import`). Closing lines: "Setup complete! You're ready to go.", "  Configure all settings:    hermes setup", and (only when messaging was skipped) "  Connect Telegram/Discord:  hermes setup gateway".
- **Config / env:** `model.*`, `terminal.*`, `agent.*`, `compression.*`, `session_reset.*`, `display.*`.
- **Edge cases / guards:** A cancelled Nous login prints "Nous Portal setup cancelled."; an error prints "Nous Portal setup encountered an error: <exc>" + "You can try again later with: hermes model" — either way the wizard continues to the terminal step.
- **Rebuild notes:** never let the optional messaging step gate the service install.

### setup — macOS Full Disk Access tip  `id: cli-b.setup.macos-fda-tip`
- **Surface:** CLI
- **Where:** Printed once at the end of first-time quick setup, on macOS only.
- **What it does:** Teaches the one-switch fix that silences every per-folder permission dialog.
- **How it works:** `hermes_cli/setup.py:3434-3458` (`_print_macos_fda_tip`). Returns immediately unless `sys.platform == "darwin"`. Probes `~/Library/Application Support/com.apple.TCC` with `os.listdir` — success means FDA is already granted (silent), `PermissionError` means not granted (print), any other `OSError` is indeterminate (silent). This probe never triggers a dialog.
- **Inputs / options:** none.
- **Outputs / side effects:** Verbatim: "  macOS tip: silence ALL folder permission prompts with one switch —", "  System Settings → Privacy & Security → Full Disk Access → enable", "  your terminal (and Hermes.app if you use Desktop), or run:", "    open \"x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles\"", "  The grant is permanent — it survives every Hermes update."
- **Config / env:** n/a.
- **Edge cases / guards:** Silent on non-macOS and when already granted.
- **Rebuild notes:** probe before nagging; use a permission check that itself cannot prompt.

### setup — Blank Slate install  `id: cli-b.setup.blank-slate`
- **Surface:** CLI
- **Where:** First-run menu choice 2, "Blank Slate — everything off except the bare minimum; opt in to each capability"; header "◆ Blank Slate Setup".
- **What it does:** Forces on only provider+model, file, terminal, vision and skills, disables everything else, then lets you stop or walk through opting back in.
- **How it works:** `hermes_cli/setup.py:3542-3624` (`_run_blank_slate_setup`). Intro: "Everything starts OFF. First we force-enable only what's required", "to run an agent, then you choose whether to stop there or walk", "through enabling more — opting in to exactly what you want.", "", "Forced on: Provider & Model, File Operations, Terminal, Vision, Skills.", "Everything else (web, browser, code exec, memory,", "delegation, cron, plugins, MCP, …) starts disabled. The", "essential `hermes-agent` skill is always kept so the agent", "can help you drive and configure Hermes itself." Then "◆ Step 1 — Provider & Model (required)" → `setup_model_provider`; "◆ Step 2 — Terminal Backend" → `setup_terminal_backend`; then `_blank_slate_minimal_toolsets` + `_blank_slate_minimize_config` and "Minimal baseline applied:", "  Toolsets: file, terminal, vision, skills (everything else off)", "  Compression, memory, checkpoints, smart routing: off". Finally header "◆ How far do you want to go?".
- **Inputs / options:** Menu "Your minimal agent is ready. What next?" with `[0] "Start with everything disabled — finish now (most minimal)"` (default) and `[1] "Walk through all configurations — opt in to tools, skills, plugins, MCP"`.
- **Outputs / side effects:** Choice 0 saves, calls `set_bundled_skills_opt_out(True)` + `sync_skills(quiet=True)` (essential `hermes-agent` skill still seeded), prints "Blank Slate setup complete — minimal agent ready." then "Enable anything later, on demand:", "  Enable tools:        hermes tools", "  Seed skills:         hermes skills opt-in --sync", "  Add MCP servers:     hermes mcp add", "  Enable plugins:      hermes plugins", "  Tune agent settings: hermes setup agent", then the setup summary. Choice 1 runs `_blank_slate_walkthrough`.
- **Config / env:** `platform_toolsets.cli`, `agent.disabled_toolsets`, `agent.max_turns`, `compression.enabled`, `memory.memory_enabled`, `memory.user_profile_enabled`, `checkpoints.enabled`, `smart_model_routing.enabled`, `session_reset.mode`, `display.tool_progress`.
- **Edge cases / guards:** Skill opt-out errors are swallowed at debug level.
- **Rebuild notes:** two enforcement layers (explicit allow-list + global disable list) so platform "recovery" logic cannot re-add toolsets behind the user's back.

### Blank Slate — minimal toolset enforcement  `id: cli-b.setup.blank-slate.toolsets`
- **Surface:** Core
- **Where:** Applied silently by Blank Slate before the fork question.
- **What it does:** Restricts the agent to `file`, `terminal`, `vision`, `skills` and hard-disables every other toolset.
- **How it works:** `hermes_cli/setup.py:3461-3515` (`_blank_slate_minimal_toolsets`). Layer 1: `config["platform_toolsets"]["cli"] = ["file","skills","terminal","vision"]` — an explicit list the resolver treats as authoritative (`has_explicit_config`) so default toolsets are not re-expanded. Layer 2: `agent.disabled_toolsets` = every known key minus the four kept, computed from `CONFIGURABLE_TOOLSETS` + `_get_plugin_toolset_keys()` + plain `TOOLSETS` entries, **excluding** keys starting with `hermes-` (platform composites), entries with `includes` (composite groupings), and entries with `posture` (session-level selections like `coding`, which if disabled would subtract terminal/read_file from the minimal surface — issue #57315). Rationale kept in the docstring: vision stays because `read_file` cannot read images and points at `vision_analyze`; skills stays because the always-seeded `hermes-agent` skill would be unloadable without `skill_view`.
- **Inputs / options:** none.
- **Outputs / side effects:** the two config keys above.
- **Config / env:** `platform_toolsets.cli`, `agent.disabled_toolsets`.
- **Edge cases / guards:** the whole computation is wrapped in try/except (debug log "blank-slate disabled_toolsets computation skipped: <exc>") so layer 1 still applies if the toolset registry fails to import.
- **Rebuild notes:** an allow-list alone is not enough when a recovery path can re-add toolsets — carry an explicit deny-list applied last.

### Blank Slate — minimized config knobs  `id: cli-b.setup.blank-slate.config`
- **Surface:** Core
- **Where:** Applied silently by Blank Slate.
- **What it does:** Turns off every optional runtime feature so the install is as small as it can be.
- **How it works:** `hermes_cli/setup.py:3517-3540` (`_blank_slate_minimize_config`). Exact writes: `agent.max_turns = 90`; `compression.enabled = False`; `memory.memory_enabled = False`; `memory.user_profile_enabled = False`; `checkpoints.enabled = False`; `smart_model_routing.enabled = False`; `session_reset.mode = "none"`; `display.tool_progress = "all"`.
- **Inputs / options:** none.
- **Outputs / side effects:** the eight keys above.
- **Config / env:** as listed.
- **Edge cases / guards:** everything is re-enableable later via `hermes setup agent` / `hermes config set`.
- **Rebuild notes:** keep the minimized profile as data, not code, so it can be diffed against defaults.

### Blank Slate — opt-in walkthrough  `id: cli-b.setup.blank-slate.walkthrough`
- **Surface:** CLI
- **Where:** Chosen by "Walk through all configurations — opt in to tools, skills, plugins, MCP".
- **What it does:** Asks, one capability at a time, whether to enable bundled skills, extra toolsets, plugins, MCP servers and messaging.
- **How it works:** `hermes_cli/setup.py:3626-3711` (`_blank_slate_walkthrough`). Five blocks with headers "◆ Bundled Skills", "◆ Tools", "◆ Plugins", "◆ MCP Servers", then the messaging question. Skills: prints "Blank Slate ships with NO bundled skills by default."; yes → `set_bundled_skills_opt_out(False)` + `sync_skills(quiet=True)` + "Seeded <n> bundled skills."; no → `set_bundled_skills_opt_out(True)` + `sync_skills(quiet=True)` + "No skills seeded (except the essential `hermes-agent`", "skill). A .no-bundled-skills marker keeps future", "`hermes update` runs from re-injecting them. Opt back in any", "time with `hermes skills opt-in --sync`." Tools: prints "Pick exactly which additional toolsets to turn on.", "(file and terminal are already on; leave the rest off if you want", " the most minimal agent.)"; yes → `tools_config.tools_command(first_install=False, config=config)` then re-sync from disk; no → "Keeping the minimal toolset. Add tools later with `hermes tools`."
- **Inputs / options:** "Seed the full bundled skill catalog? (No = start with zero skills)" (default No); "Open the tool selector to enable more tools?" (default No); "Review and enable built-in plugins now?" (default No); "Add an MCP server now?" (default No); "Connect a messaging platform (Telegram, Discord, …)?" (default No).
- **Outputs / side effects:** Plugins-yes prints "Manage plugins with `hermes plugins list` / `hermes plugins install`."; plugins-no prints "No plugins enabled. Add later with `hermes plugins`." MCP-yes prints "Add servers with `hermes mcp add <name> --url ... | --command ...`."; MCP-no prints "No MCP servers configured. Add later with `hermes mcp add`." Messaging-yes runs `setup_gateway(config)`. Then `save_config` and the closing block "Blank Slate setup complete — minimal agent ready.", "  Enable more tools:   hermes tools", "  Seed skills:         hermes skills opt-in --sync", "  Add MCP servers:     hermes mcp add", "  Tune agent settings: hermes setup agent", then the setup summary.
- **Config / env:** skills opt-out marker `.no-bundled-skills`, `platform_toolsets.*`.
- **Edge cases / guards:** Skill and tool errors print "Skill setup step encountered an error: <exc>" / "Tool selector encountered an error: <exc>" and the walkthrough continues. The Plugins and MCP steps are informational only in v2026.8.31 — answering yes prints instructions rather than opening a selector.
- **Rebuild notes:** every default is No; the yes-paths that only print advice are the obvious place to wire real selectors.

### setup --quick — missing-items-only flow  `id: cli-b.setup.quick`
- **Surface:** CLI
- **Where:** `hermes setup --quick` on an existing install; header "◆ Quick Setup — Missing Items Only".
- **What it does:** Prompts only for settings that are missing or unset, then adds any new config fields with their defaults.
- **How it works:** `hermes_cli/setup.py:3713-3876` (`_run_quick_setup`). Gathers `get_missing_env_vars(required_only=False)` split into required/optional, `get_missing_config_fields()`, and `check_config_version()` → `(current_ver, latest_ver)`. Nothing missing → "Everything is configured! Nothing to do." + "Run 'hermes setup' and choose 'Full Setup' to reconfigure," + "or pick a specific section from the menu." Otherwise: required vars are listed as "<n> required setting(s) missing:" with `     • <NAME>` bullets and prompted one by one (each shows the name in cyan, its description, and "  Get key at: <url>" when present); optional vars are split by `category` into `tool` and non-advanced `messaging`.
- **Inputs / options:** Per required var: `"  <prompt or NAME>"` (masked when `var["password"]`). Tool keys: checklist "Which tools would you like to configure?" whose labels are `"<description>{ → first two tool names}"`, then `_prompt_api_key(var)` per selection. Messaging: checklist "Which platforms would you like to set up?" with labels "📱 Telegram", "💬 Discord", "💼 Slack" (grouped by whether the var name contains TELEGRAM/DISCORD/SLACK; anything else is dropped), then per-var prompts.
- **Outputs / side effects:** Saves each answered var with `save_env_value` printing "  Saved <NAME>" (required) or "  ✓ Saved" (optional); skipped ones print "  Skipped <NAME>" / "  Skipped". Missing config fields print "Adding <n> new config option(s) with defaults..." then "  Added <key> = <default>" per field, set `config["_config_version"] = latest_ver`, and save. Always ends with `_print_setup_summary`.
- **Config / env:** `_config_version`; every env var reported as missing.
- **Edge cases / guards:** Headers "◆ Tool API Keys" and "◆ Messaging Platforms" only appear when their bucket is non-empty; the messaging block also prints "Connect Hermes to messaging apps to chat from anywhere." and "You can configure these later with 'hermes setup gateway'."
- **Rebuild notes:** derive "missing" from a declarative schema of env vars (name, description, url, password, category, tools, required) — that schema is what makes this flow possible.

### setup — API-key prompt card  `id: cli-b.setup.api-key-card`
- **Surface:** CLI
- **Where:** `_prompt_api_key(var)` — used by the quick-setup tool-key loop.
- **What it does:** Renders a single formatted API-key entry screen for one env var.
- **How it works:** `hermes_cli/setup.py:446-471`. Prints `  ─── <description or name> ───` in cyan, then "  Enables: <first three tool names>" (with ", +<n> more" when there are more than three), then "  Get your key at: <url>" when the var declares one, then prompts `"  <prompt or name>"` masked when `var["password"]`.
- **Inputs / options:** one free-text/masked answer.
- **Outputs / side effects:** `save_env_value(var["name"], value)` + "  ✓ Saved", or "  Skipped (configure later with 'hermes setup')".
- **Config / env:** the named env var.
- **Edge cases / guards:** an empty answer is a skip, never an error.
- **Rebuild notes:** tell the user what the key unlocks before asking for it.

### setup — OpenClaw migration offer  `id: cli-b.setup.openclaw-migration`
- **Surface:** CLI
- **Where:** First-time setup only, before the mode picker; header "◆ OpenClaw Installation Detected".
- **What it does:** Detects `~/.openclaw`, shows a full dry-run preview of what would be imported, and imports only after explicit confirmation.
- **How it works:** `hermes_cli/setup.py:2721-2855` (`_offer_openclaw_migration`). Guards: `~/.openclaw` must be a directory and `_OPENCLAW_SCRIPT` must exist — that path is `<optional-skills>/migration/openclaw-migration/scripts/openclaw_to_hermes.py` (`setup.py:2606-2611`). The script is loaded as a module via `importlib.util.spec_from_file_location` and registered in `sys.modules` so `@dataclass` can resolve it (`_load_openclaw_migration_module`, `setup.py:2613-2654`). Phase 1 runs `mod.Migrator(..., execute=False, overwrite=True, migrate_secrets=True, selected_options=resolve_selected_options(None,None,preset="full"), preset_name="full")` and renders the report; Phase 2 re-runs with `execute=True, overwrite=False` so existing Hermes config wins.
- **Inputs / options:** "Would you like to see what can be imported?" (default Yes); "Proceed with migration?" (default No).
- **Outputs / side effects:** Copies OpenClaw data into `$HERMES_HOME`. Messages: "Found OpenClaw data at <dir>", "Hermes can preview what would be imported before making any changes.", "Skipping migration. You can run it later with: hermes claw migrate --dry-run", "◆ Migration Preview — <n> item(s) would be imported", "No changes have been made yet. Review the list below:", "Nothing to import from OpenClaw.", "Migration cancelled. You can run it later with: hermes claw migrate", "Use --dry-run to preview again, or --preset minimal for a lighter import.", "Imported <n> item(s) from OpenClaw.", "Skipped <n> item(s) that already exist in Hermes (use hermes claw migrate --overwrite to force).", "Skipped <n> item(s) (not found or unchanged).", "<n> item(s) had errors — check the migration report.", "Full report saved to: <dir>", "Migration complete! Continuing with setup..."
- **Config / env:** writes into `$HERMES_HOME`; ensures `config.yaml` exists first (`save_config(load_config())`).
- **Edge cases / guards:** Module load failure → "Could not load migration script." / "Could not load migration script: <e>"; preview failure → "Migration preview failed: <e>"; execution failure → "Migration failed: <e>" — all return False and setup continues.
- **Rebuild notes:** always dry-run first with `overwrite=True` (to surface conflicts) and execute with `overwrite=False` (to protect existing state).

### setup — migration preview renderer and high-impact warnings  `id: cli-b.setup.migration-preview`
- **Surface:** CLI
- **Where:** Inside the OpenClaw migration preview.
- **What it does:** Groups the dry-run items into import / overwrite / skip buckets and raises explicit warnings for dangerous takeovers.
- **How it works:** `hermes_cli/setup.py:2657-2718` (`_print_migration_preview`) plus the keyword map `_HIGH_IMPACT_KIND_KEYWORDS` (`setup.py:2668-2679`). Sections, verbatim: "  Would import:" with `      <kind:<22s> → <destination with $HOME collapsed to ~>`; "  Would overwrite (conflicts with existing Hermes config):" with `      <kind:<22s>  <reason>`; "  Would skip:" with `      <kind:<22s>  <reason>`; then "  ── Warnings ──" listing the matched warnings sorted, followed by "  Note: OpenClaw config values may have different semantics in Hermes.", "  For example, OpenClaw's tool_call_execution: \"auto\" ≠ Hermes's yolo mode.", "  Instruction files (.md) from OpenClaw may contain incompatible procedures." Empty item list prints "Nothing to migrate."
- **Inputs / options:** n/a (renderer).
- **Outputs / side effects:** stdout only.
- **Config / env:** n/a.
- **Edge cases / guards:** All nine warning keywords and their exact texts: `gateway` → "⚠ Gateway/messaging — this will configure Hermes to use your OpenClaw messaging channels"; `telegram` → "⚠ Telegram — this will point Hermes at your OpenClaw Telegram bot"; `slack` → "⚠ Slack — this will point Hermes at your OpenClaw Slack workspace"; `discord` → "⚠ Discord — this will point Hermes at your OpenClaw Discord bot"; `whatsapp` → "⚠ WhatsApp — this will point Hermes at your OpenClaw WhatsApp connection"; `config` → "⚠ Config values — OpenClaw settings may not map 1:1 to Hermes equivalents"; `soul` → "⚠ Instruction file — may contain OpenClaw-specific setup/restart procedures"; `memory` → "⚠ Memory/context file — may reference OpenClaw-specific infrastructure"; `context` → "⚠ Context file — may contain OpenClaw-specific instructions". A keyword matches if it appears in the item's `kind` **or** its destination path (both lower-cased).
- **Rebuild notes:** classify migration items by blast radius and warn per class, not per file.

### setup — post-migration section skip  `id: cli-b.setup.section-skip`
- **Surface:** CLI
- **Where:** Shown after an OpenClaw migration, before each of the four full-wizard steps.
- **What it does:** Reports what the migration already configured for a section and offers to leave it alone.
- **How it works:** `hermes_cli/setup.py:2584-2597` (`_skip_configured_section`) prints "  <Label>: <summary>" then asks "  Reconfigure <label lower-cased>?" (default No) — answering No skips the section. Summaries come from `_get_section_config_summary` (`setup.py:2529-2581`): `model` → the model string / `model.default` / `"configured"`, but only when `_model_section_has_credentials(config)` is true; `terminal` → `"backend: <backend>"`; `agent` → `"max turns: <n>"`; `gateway` → a comma list of platform labels whose `_platform_status` is neither empty nor `"not configured"`, each stripped of any trailing parenthetical by `_gateway_platform_short_label` (`setup.py:2523-2527`); `tools` → a comma list built from `ELEVENLABS_API_KEY` → "TTS/ElevenLabs", `BROWSERBASE_API_KEY` → "Browser", `FIRECRAWL_API_KEY` → "Firecrawl". Any section with no summary returns None and always runs.
- **Inputs / options:** one yes/no per section.
- **Outputs / side effects:** Skipping the gateway section still calls `ensure_gateway_service(context="setup")` so imported platforms and cron jobs become active (`setup.py:3321-3327`).
- **Config / env:** the keys named above.
- **Edge cases / guards:** `_model_section_has_credentials` (`setup.py:2461-2521`) checks `PROVIDER_REGISTRY` api-key env vars, the auth store's `active_provider`, and the legacy OpenRouter aggregator vars.
- **Rebuild notes:** show the concrete imported value, not just "configured".

### setup — completion summary and Tool Availability table  `id: cli-b.setup.summary`
- **Surface:** CLI
- **Where:** End of every wizard path; header "◆ Tool Availability Summary".
- **What it does:** Reports whether a provider is usable, lists each tool category as available or missing (with the exact env var to set), and prints the file locations plus next commands.
- **How it works:** `hermes_cli/setup.py:474-800` (`_print_setup_summary`). First it calls `resolve_provider()`; on failure it prints "No inference provider is configured — Hermes cannot chat yet.", "  Finish this one step with either of:", "    hermes model            (pick any provider/model)", "    hermes setup --portal   (Nous Portal OAuth, no API key)". Then it builds `tool_status` rows and prints "<available>/<total> tool categories available:" followed by `   ✓ <name>` or `   ✗ <name> (missing <var>)`.
- **Inputs / options:** none (report only).
- **Outputs / side effects:** stdout only. Rows, in order: "Vision (image analysis)" (missing hint "run 'hermes setup' to configure"); "Web Search & Extract" — "(Nous subscription)" when managed, "(<provider>)" when a provider is set, missing hint "EXA_API_KEY, PARALLEL_API_KEY, FIRECRAWL_API_KEY/FIRECRAWL_API_URL, KEENABLE_API_KEY, or SEARXNG_URL"; "Browser Automation" — "(Nous Browser Use)" when managed or "(<provider>)", with provider-specific missing hints: Browserbase → "npm install -g agent-browser and set BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID", Browser Use → "npm install -g agent-browser and set BROWSER_USE_API_KEY", Camofox → "CAMOFOX_URL", Local browser → "npm install -g agent-browser && agent-browser install --with-deps", default → "npm install -g agent-browser, set CAMOFOX_URL, or configure Browser Use or Browserbase"; "Image Generation" / "Image Generation (Nous subscription)" / "Image Generation (<plugin display name>)", missing hint "FAL_KEY or OPENAI_API_KEY"; "Video Generation (FAL via Nous subscription)" or "Video Generation (<backend>)" — the row is omitted entirely when no video backend is available; the TTS row, one of "Text-to-Speech (OpenAI via Nous subscription)", "(ElevenLabs)", "(OpenAI)", "(MiniMax)", "(Mistral Voxtral)", "(Google Gemini)", "(NeuTTS local)", "(NeuTTS — not installed)" [hint "run 'hermes setup tts'"], "(KittenTTS local)", "(KittenTTS — not installed)" [same hint], or "(Edge TTS)"; the STT row, one of "Speech-to-Text (OpenAI via Nous subscription)", "(OpenAI)", "(Groq Whisper)", "(ElevenLabs Scribe)", "(xAI)", "(DeepInfra)", "(Local Whisper)", or "(Local Whisper — not installed)" [hint "run 'hermes tools' → Speech-to-Text"]; "Modal Execution (Nous subscription)" / "Modal Execution (direct Modal)" / "Modal Execution" [hint "run 'hermes setup terminal'"] / "Modal Execution (optional via Nous subscription)"; "Smart Home (Home Assistant)" (only when `HASS_TOKEN` is set); "Spotify (PKCE OAuth)" (only when the auth store holds a Spotify access or refresh token); "Skills Hub (GitHub)" [hint "GITHUB_TOKEN"]; "Terminal/Commands"; "Task Planning (todo)"; "Skills (view, create, edit)". Any missing row triggers "Some tools are disabled. Run 'hermes setup tools' to configure them," and "or edit <hermes home>/.env directly to add the missing API keys." Then the green box `│              ✓ Setup Complete!                          │`; "📁 All your files are in <hermes home>/:" with `Settings:`, `API Keys:`, `Data:      <home>/cron/, sessions/, logs/`; "📝 To edit your configuration:" listing `hermes setup` "Re-run the full wizard", `hermes setup model` "Change model/provider", `hermes setup terminal` "Change terminal backend", `hermes setup gateway` "Configure messaging", `hermes setup tools` "Configure tool providers", `hermes config` "View current settings", `hermes config edit` "Open config in your editor", `hermes config set <key> <value>` "Set a specific value", plus "   Or edit the files directly:" with `nano <config path>` / `nano <env path>`; and "🚀 Ready to go!" listing `hermes` "Start chatting", `hermes gateway` "Start messaging gateway", `hermes doctor` "Check for issues".
- **Config / env:** reads `tts.provider`, `stt.provider`, `terminal.backend` and every key named above.
- **Edge cases / guards:** Every backend probe is wrapped in try/except so a broken plugin cannot break the summary; vision uses the same runtime resolver as the vision tools (`agent.auxiliary_client.get_available_vision_backends`).
- **Rebuild notes:** the value of this screen is that each ✗ names the exact variable or command that fixes it — keep that property.

### hermes whatsapp (Baileys QR pairing wizard)  `id: cli-b.whatsapp`
- **Surface:** CLI
- **Where:** `hermes whatsapp [-h]`; top-level help row "Set up WhatsApp integration"; description "Configure WhatsApp and pair via QR code"; banner "⚕ WhatsApp Setup" followed by a 50-character `=` rule.
- **What it does:** Seven-step wizard that picks a WhatsApp mode, sets the allowlist, npm-installs the Baileys bridge, and pairs your account by QR code.
- **How it works:** Parser `hermes_cli/subcommands/whatsapp.py:12-22`; handler `hermes_cli/main.py:3530-3760` (`cmd_whatsapp`), guarded by `_require_tty("whatsapp")`. Step 1 mode (`WHATSAPP_MODE`); Step 2 deliberately does **not** write `WHATSAPP_ENABLED=true` yet — an aborted wizard would otherwise leave `.env` claiming WhatsApp is ready with no `creds.json`, making every later `hermes gateway` pay a 30 s bridge-bootstrap timeout and queue endless retries; Step 3 allowlist; Step 4 `npm install --no-fund --no-audit --progress=false` inside `resolve_whatsapp_bridge_dir()` (from `gateway/platforms/whatsapp_common.py`) using `find_node_executable("npm")` and `with_hermes_node_path()`; Step 5 existing-session check at `$HERMES_HOME/whatsapp/session/creds.json`; Step 6 runs `node bridge.js --pair-only --session <session_dir>` in the foreground so the QR renders in the terminal; Step 7 writes `WHATSAPP_ENABLED=true` **only** if `creds.json` now exists.
- **Inputs / options:** `-h/--help` (the command takes no flags). Interactive prompts: `"  Choose [1/2]: "` for the mode, with the menu printed verbatim as "How will you use WhatsApp with Hermes?", "  1. Separate bot number (recommended)", "     People message the bot's number directly — cleanest experience.", "     Requires a second phone number with WhatsApp installed on a device.", "  2. Personal number (self-chat)", "     You message yourself to talk to the agent.", "     Quick to set up, but the UX is less intuitive."; `"\n  Update allowed users? [y/N] "` when an allowlist already exists; `"  Phone numbers that can message the bot (comma-separated): "` (bot mode, update path); `"  Phone numbers (comma-separated, or * for anyone): "` (bot mode, first run, preceded by "  Who should be allowed to message the bot?"); `"  Your phone number (e.g. 15551234567): "` (self-chat mode); `"\n  Re-pair? This will clear the existing session. [y/N] "`.
- **Outputs / side effects:** `.env`: `WHATSAPP_MODE` (`bot` or `self-chat`), `WHATSAPP_ALLOWED_USERS` (spaces stripped), `WHATSAPP_ENABLED=true` (only after successful pairing). Filesystem: `<bridge_dir>/node_modules`, `$HERMES_HOME/whatsapp/session/` (recreated on re-pair via `shutil.rmtree`). Bot-mode banner, verbatim: "  ┌─────────────────────────────────────────────────┐", "  │  Getting a second number for the bot:           │", "  │                                                 │", "  │  Easiest: Install WhatsApp Business (free app)  │", "  │  on your phone with a second number:            │", "  │    • Dual-SIM: use your 2nd SIM slot            │", "  │    • Google Voice: free US number (voice.google) │", "  │    • Prepaid SIM: $3-10, verify once            │", "  │                                                 │", "  │  WhatsApp Business runs alongside your personal │", "  │  WhatsApp — no second phone needed.             │", "  └─────────────────────────────────────────────────┘". Pairing instructions: bot mode "📱 Open WhatsApp (or WhatsApp Business) on the" + "   phone with the BOT's number, then scan:"; self-chat "📱 Open WhatsApp on your phone, then scan:"; both followed by "   Settings → Linked Devices → Link a Device". Success block: "✓ WhatsApp paired successfully!" then "  Next steps:", "    1. Start the gateway:  hermes gateway", "    2. Send a message to the bot's WhatsApp number" / "    2. Open WhatsApp → Message Yourself", "    3. The agent will reply automatically" / "    3. Type a message — the agent will reply", "  Tip: Agent responses are prefixed with '⚕ Hermes Agent'" (self-chat adds "  so you can tell them apart from your own messages."), and "  Or install as a service: hermes gateway install".
- **Config / env:** `WHATSAPP_MODE`, `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_ENABLED`; `HERMES_HOME` for the session dir.
- **Edge cases / guards:** Ctrl+C/EOF at the mode prompt prints "\nSetup cancelled." and returns. Missing `bridge.js` prints "\n✗ Bridge script not found at <path>" and returns. Missing npm prints "  ✗ npm not found on PATH — install Node.js first". A cancelled install prints "\n  ✗ Install cancelled". A failed install prints "  ✗ npm install failed:" plus the last 30 stderr lines (or "(no output)"). An empty allowlist prints "  ⚠ No allowlist — the agent will respond to ALL incoming messages". Keeping an existing session re-asserts `WHATSAPP_ENABLED=true` (older installs may have lost it) and prints "\n✓ WhatsApp is configured and paired!" + "  Start the gateway with: hermes gateway". Failure to produce `creds.json` prints "⚠ Pairing may not have completed. Run 'hermes whatsapp' to try again."
- **Rebuild notes:** the load-bearing design decision is that the enable flag is written **after** proof of pairing, not before — copy that. A better version would stream the QR into the dashboard and detect pairing over IPC instead of a foreground subprocess.

### hermes whatsapp-cloud (Meta Cloud API wizard)  `id: cli-b.whatsapp-cloud`
- **Surface:** CLI
- **Where:** `hermes whatsapp-cloud [-h]`; description "Configure the official Meta WhatsApp Business Cloud API adapter (Business account required, public webhook URL required). Distinct from `hermes whatsapp` which sets up the Baileys bridge for personal accounts."; banner "⚕ WhatsApp Business Cloud API Setup" + a 50-char `=` rule.
- **What it does:** Six numbered steps that collect Meta's credentials, auto-generate a webhook verify token, set the recipient allowlist, and print the exact tunnel/webhook/curl follow-up instructions.
- **How it works:** Handler `hermes_cli/main.py:3763-3780` (`cmd_whatsapp_cloud`, guarded by `_require_tty("whatsapp-cloud")`) → `hermes_cli/setup_whatsapp_cloud.py:233` (`run_whatsapp_cloud_setup`). Each field uses `_prompt_validated(message, validator, current=…, help_text=…, secret=…)` (`:191-225`) which prints the help block indented two spaces, prompts `"  → <message>[ <default>]"`, re-asks on validation failure printing `"    ✗ <reason>"`, and after 3 failed attempts offers `"    Try again, or press Enter to skip: "`. Secrets read through `getpass` when stdin is a TTY, prompt suffix "(input hidden): ". Returns 0 on success, 1 on abort.
- **Inputs / options:** `-h/--help` (no flags). Prompts in order: the gate `"Press Enter to continue, or Ctrl+C to abort... "`; **STEP 1 — Phone Number ID** → "Phone Number ID"; **STEP 2 — Access Token** → "Access Token" (hidden); **STEP 3 — App Secret (required for webhook signature verification)** → "App Secret" (hidden); **STEP 4 — App ID & WABA ID (optional, for analytics)** → "App ID (optional, press Enter to skip)" and "WABA ID (optional, press Enter to skip)"; **STEP 5 — Verify Token (auto-generated)** → `"  Generate a new one? [y/N]: "` only when one exists; **STEP 6 — Recipient Allowlist** → `"  → Allowed users[ <current>]: "`.
- **Outputs / side effects:** `.env` writes: `WHATSAPP_CLOUD_PHONE_NUMBER_ID`, `WHATSAPP_CLOUD_ACCESS_TOKEN`, `WHATSAPP_CLOUD_APP_SECRET`, `WHATSAPP_CLOUD_APP_ID`, `WHATSAPP_CLOUD_WABA_ID`, `WHATSAPP_CLOUD_VERIFY_TOKEN` (`secrets.token_urlsafe(32)`), `WHATSAPP_CLOUD_ALLOWED_USERS` (each entry stripped of whitespace, `-` and `+`). Confirmations: "  ✓ Saved: <value>", "  ✓ Saved (token hidden)", "  ✓ Saved (secret hidden)", "  ✓ Keeping existing: <v>", "  ✓ Keeping existing token", "  ✓ Keeping existing App Secret", "  ✓ New verify token: <t>", "  ✓ Keeping existing verify token", "  ✓ Generated: <t>", plus "  → COPY THIS TOKEN NOW. You'll paste it into Meta's webhook" / "    configuration dialog (next step)." The closing "SETUP COMPLETE — Next steps" block lists all seven steps verbatim, including the cloudflared install lines ("         Windows:  winget install Cloudflare.cloudflared", "         macOS:    brew install cloudflared", "         Linux:    https://github.com/cloudflare/cloudflared/releases"), "         cloudflared tunnel --url http://localhost:8090", "         hermes gateway", the verification curl `curl 'https://YOUR-TUNNEL.trycloudflare.com/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=hello'` with "       Expected: HTTP 200 with body 'hello'." and "       Also try: curl https://YOUR-TUNNEL.trycloudflare.com/health" "(should return JSON with verify_token_configured: true)", the Meta webhook config ("         App Dashboard → WhatsApp → Configuration → Edit webhook", "         Callback URL: <tunnel-url>/whatsapp/webhook", "         Verify Token: <token>", "         → Click 'Verify and save'", "         → Then 'Manage' webhook fields → subscribe to 'messages'"), "    6. Add your phone to Meta's recipient list:" and "    7. DM the bot's test number from your phone." A final "Optional: polish your bot's WhatsApp profile" block links `https://business.facebook.com/wa/manage/phone-numbers/?waba_id=<waba>` (or the un-parameterised URL plus "        (select your WhatsApp Business Account on that page)"), notes "        Display-name changes go through a ~24-48h Meta review.", the "Edit profile" path, the verified-badge path ("        Business Manager → Security Center → Start Verification."), and the docs link "https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp-cloud".
- **Config / env:** the seven `WHATSAPP_CLOUD_*` vars.
- **Edge cases / guards:** Field-shape validators (`setup_whatsapp_cloud.py:53-158`) with their exact messages — Phone Number ID: "Phone Number ID is required", "Phone Number ID must be numeric (no '+', spaces, or dashes)", the 10–12-digit trap "That looks like a phone number — but this field needs the Phone Number ID (Meta's internal ID, 15-17 digits, e.g. '7794189252778687'). Look just BELOW the 'From' dropdown in API Setup → it's labelled 'Phone number ID'.", "Phone Number ID looks too short (expected 13-18 digits)" (<13), "Phone Number ID looks too long (expected 13-18 digits)" (>20). WABA ID: "WABA ID is required", "WABA ID must be numeric", "WABA ID looks wrong (expected 10-25 digits)". App ID: "App ID is required", "App ID must be numeric", "App ID looks wrong (expected 15-16 digits)" (outside 13–20). App Secret: "App Secret is required", the hex message "App Secret should be a hex string (only digits 0-9 and letters a-f). Make sure you copied the 'App secret' from Settings → Basic, not some other token.", "App Secret should be exactly 32 hex characters (got <n>)". Access token: "Access token is required", "That's an OpenAI key (starts with 'sk-'), not a Meta WhatsApp access token. Meta tokens start with 'EAA'.", "That's a Slack token, not a Meta WhatsApp access token. Meta tokens start with 'EAA'." (`xoxb-`/`xoxp-`), "That's a GitHub token, not a Meta WhatsApp access token. Meta tokens start with 'EAA'." (`ghp_`/`gho_`), the generic "Meta WhatsApp access tokens start with 'EAA'. Check that you're copying from the right place (API Setup → 'Generate access token', or Business Settings → System Users → 'Generate token' for a permanent one).", and "Access token looks too short (<n> chars, expected 100+)". Aborts: missing Phone Number ID → "\n✗ Phone Number ID is required. Aborting." return 1; missing Access Token → "\n✗ Access Token is required. Aborting." return 1; missing App Secret is a warning only — "\n⚠ Skipping App Secret — inbound webhooks will be refused" + "   until you set WHATSAPP_CLOUD_APP_SECRET manually."; empty allowlist → "  ⚠ No allowlist — every inbound message will be denied." + "    Re-run this wizard or set WHATSAPP_CLOUD_ALLOWED_USERS manually." Ctrl+C at the intro prints "\nSetup cancelled." and returns 1. The wizard deliberately does **not** smoke-test the webhook because the gateway and tunnel run in separate processes started afterwards.
- **Rebuild notes:** the paste-mistake diagnostics (`sk-`, `xoxb-`, `ghp_`, phone-number-length) are the highest-value part; keep them and add a live Graph API `GET /<phone_number_id>` probe once credentials are entered.

### hermes slack (command group)  `id: cli-b.slack`
- **Surface:** CLI
- **Where:** `hermes slack [-h] {manifest}`; top-level help row "Slack integration helpers (manifest generation, etc.)"; description "Slack integration helpers for Hermes."
- **What it does:** Slack-specific helper commands; today only manifest generation.
- **How it works:** Parser `hermes_cli/subcommands/slack.py:12-93`; handler `hermes_cli/main.py:5835-5866` (`cmd_slack`). No sub-command prints the usage block to stderr and returns 1: "usage: hermes slack <subcommand>", "", "subcommands:", "  manifest   Generate a Slack app manifest with every gateway", "             command registered as a native slash", "", "Run `hermes slack manifest -h` for details." An unrecognised sub-command prints "Unknown slack subcommand: <sub>" to stderr and returns 1.
- **Inputs / options:** `-h/--help`; sub-command `manifest`.
- **Outputs / side effects:** see the sub-command.
- **Config / env:** `HERMES_HOME` (default write path).
- **Edge cases / guards:** the manifest command's non-zero return is re-raised as `SystemExit`.
- **Rebuild notes:** keep the group open for future Slack helpers (token check, socket-mode probe).

### hermes slack manifest  `id: cli-b.slack.manifest`
- **Surface:** CLI
- **Where:** `hermes slack manifest [-h] [--write [PATH]] [--name NAME] [--description DESCRIPTION] [--long-description TEXT | --long-description-file PATH] [--slashes-only] [--no-assistant | --agent-view]`; description "Generate a Slack app manifest that registers every gateway command in COMMAND_REGISTRY as a first-class Slack slash command (matching Discord and Telegram parity). Paste the output into Slack app config → Features → App Manifest → Edit, then Save. Reinstall the app if Slack prompts for it."
- **What it does:** Emits the Slack app manifest JSON (display info, bot scopes, event subscriptions, socket mode, and one slash command per gateway command) to stdout or a file.
- **How it works:** `hermes_cli/slack_cli.py:166-282` (`slack_manifest_command`) building on `_build_full_manifest` (`:30-163`). Slash commands come from `hermes_cli.commands.slack_app_manifest()["features"]["slash_commands"]`, so they always match `COMMAND_REGISTRY`. The manifest shape: `_metadata` `{major_version: 1, minor_version: 1}`; `display_information` `{name: <name>[:35], description: <description>[:140], background_color: "#1a1a2e"}` plus `long_description` when supplied; `features.app_home` `{home_tab_enabled: false, messages_tab_enabled: true, messages_tab_read_only_enabled: false}`; `features.bot_user` `{display_name: <name>[:80], always_online: true}`; `features.slash_commands`; `oauth_config.scopes.bot` sorted; `settings.event_subscriptions.bot_events` sorted; `settings.interactivity.is_enabled: true`; `settings.org_deploy_enabled: false`; `settings.socket_mode_enabled: true`; `settings.token_rotation_enabled: false`. Base bot scopes (16): `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `commands`, `files:read`, `files:write`, `groups:history`, `groups:read`, `im:history`, `im:read`, `im:write`, `mpim:history`, `mpim:read`, `reactions:read`, `users:read`. Base bot events (7): `app_mention`, `message.channels`, `message.groups`, `message.im`, `message.mpim`, `reaction_added`, `reaction_removed`. Messaging experience `assistant` (default) adds `features.assistant_view = {"assistant_description": "Chat with Hermes in threads and DMs."}`, the scope `assistant:write`, and the events `assistant_thread_context_changed` + `assistant_thread_started`. Experience `agent` adds `features.agent_view = {"agent_description": "Chat with Hermes in Slack Messages."}`, the scope `assistant:write`, and the events `app_context_changed` + `app_home_opened`. Experience `none` adds nothing.
- **Inputs / options:** `-h/--help`; `--write [PATH]` (`nargs="?"`, `const=True`; with no PATH writes `$HERMES_HOME/slack-manifest.json`); `--name NAME` (default "Hermes"); `--description DESCRIPTION` (default "Your Hermes agent on Slack"); `--long-description TEXT` and `--long-description-file PATH` (mutually exclusive, 175–4000 characters); `--slashes-only`; `--no-assistant` and `--agent-view` (mutually exclusive).
- **Outputs / side effects:** JSON with `indent=2, ensure_ascii=False` plus a trailing newline, to stdout or the file. With `--write`, stderr gets "Slack manifest written to: <target>" followed by "\nNext steps:", "  1. Open https://api.slack.com/apps and pick your Hermes app", "     (or create a new one: Create New App → From an app manifest).", "  2. Features → App Manifest → paste the contents of", "     <target>", "  3. Save; Slack will prompt to reinstall the app if scopes or", "     slash commands changed.", "  4. Make sure Socket Mode is enabled and you have a bot token", "     (xoxb-...) and app token (xapp-...) configured via", "     `hermes setup`." Parent directories of the write target are created.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `--slashes-only` combined with either long-description flag prints "hermes slack manifest: long description options cannot be used with --slashes-only" to stderr and returns 2. An unreadable long-description file prints "hermes slack manifest: cannot read long description from <path>: <exc>" and returns 2. Too short → "hermes slack manifest: long description must be at least 175 characters (got <n>)"; too long → "hermes slack manifest: long description must be at most 4000 characters (got <n>)"; both return 2. `--agent-view` wins over `--no-assistant` in the precedence chain (`agent_view` checked first) even though argparse also makes them mutually exclusive. `_build_full_manifest` raises `ValueError("messaging_experience must be one of: assistant, agent, none")` for an invalid programmatic value. The `--agent-view` help warns the change "cannot be reversed in Slack after applying the manifest."
- **Rebuild notes:** generate the slash list from the same registry the runtime dispatches from — that is what keeps Slack, Discord and Telegram at parity. Long-description bounds mirror Slack's own API limits.

### hermes send  `id: cli-b.send`
- **Surface:** CLI
- **Where:** `hermes send [-h] [-t TARGET] [-f PATH] [-s LINE] [-l] [-q] [--json] [message]`; top-level help row "Send a message to a configured platform (scripts, cron jobs, CI)."
- **What it does:** Sends a one-off message to any configured messaging platform from a shell script — no LLM, no agent loop, and for bot-token platforms no running gateway.
- **How it works:** `hermes_cli/send_cmd.py`. `register_send_subparser` (`:398-498`) builds the parser; `cmd_send` (`:328-395`) runs: (1) `_load_hermes_env()` (`:232-325`) which `load_dotenv($HERMES_HOME/.env, override=True, encoding="utf-8-sig")` with a latin-1 + manual-BOM-strip fallback, then bridges top-level **scalar** keys from `config.yaml` into `os.environ` without overriding existing values — reading via `read_user_config_raw` (presence-sensitive, so only keys the user actually wrote are bridged), then `_expand_env_vars`, then `managed_scope.apply_managed_overlay`; (2) `--list` short-circuit; (3) target resolution; (4) body resolution; (5) optional subject prepend as `f"{subject}\n\n{message.lstrip()}"`; (6) `tools.send_message_tool.send_message_tool({"action":"send","target":…,"message":…})`; (7) `_emit_result`. Body precedence (`_read_message_body`, `:41-87`): positional `message` → `--file PATH` (`-` = stdin) → piped stdin when `not sys.stdin.isatty()`.
- **Inputs / options:** `-h/--help`; `-t/--to TARGET` ("Delivery target. Format: 'platform' (home channel), 'platform:chat_id', 'platform:chat_id:thread_id', or 'platform:#channel-name'. Examples: telegram, telegram:-1001234567890:17585, discord:#ops, slack:C0123ABCD, signal:+15551234567."); positional `message` ("Message text. If omitted, read from --file or stdin."); `-f/--file PATH`; `-s/--subject LINE`; `-l/--list` (dest `list_targets`); `-q/--quiet`; `--json`. Epilog examples, verbatim: `hermes send --to telegram "deploy finished"`, `echo "RAM 92%" | hermes send --to telegram:-1001234567890`, `hermes send --to discord:#ops --file /tmp/report.md`, `hermes send --to slack:#eng --subject "[CI]" --file build.log`, `hermes send --to telegram "MEDIA:/tmp/chart.png"   # send a media attachment`, `hermes send --list                  # all platforms`, `hermes send --list telegram         # filter by platform`; plus "Exit codes: 0 ok, 1 delivery/backend error, 2 usage error."
- **Outputs / side effects:** Delivers the message via the platform's REST API. Human mode prints the result's `note`, or "sent" on success; `--json` prints the parsed payload with `indent=2`; `--quiet` prints nothing on success. Errors print "hermes send: <error>" on stderr. Exit codes: 0 when `success` or `skipped`, 1 on `error` or an unrecognised payload shape, 2 for usage errors.
- **Config / env:** Everything in `$HERMES_HOME/.env` and every top-level scalar in `$HERMES_HOME/config.yaml` (notably `TELEGRAM_HOME_CHANNEL` and its siblings).
- **Edge cases / guards:** No `--to` prints "hermes send: --to PLATFORM[:channel[:thread]] is required" plus three examples and exits 2. No body prints "hermes send: no message provided. Pass text as a positional argument, use --file PATH, or pipe data via stdin." and exits 2. A binary `--file` raises `UnicodeDecodeError` and prints the media-attachment guidance verbatim: "hermes send: <path> is not a text file. --file reads the message *body* (logs, reports, markdown).", "To send an image/document/audio file as a native attachment, reference it with MEDIA: in the message text instead:", `  hermes send --to telegram "MEDIA:<path>"`, `  hermes send --to telegram "optional caption MEDIA:<path>"`, "Add [[as_document]] to deliver an image as an uncompressed file:", `  hermes send --to telegram "[[as_document]] MEDIA:<path>"` — exit 2. An unreadable file prints "hermes send: cannot read <path>: <exc>" and exits 2. Reading from a TTY never blocks — stdin is only consumed when it is not a TTY. Invalid JSON from the tool is wrapped as `{"error": "invalid JSON from send_message_tool", "raw": <str>}`.
- **Rebuild notes:** replicate the gateway's env bridge exactly (dotenv + scalar config keys, no overrides) so a standalone send resolves the same home channels the gateway would; keep `MEDIA:` and `[[as_document]]` in the message body rather than adding attachment flags.

### hermes send --list  `id: cli-b.send.list`
- **Surface:** CLI
- **Where:** `hermes send --list [platform]`; help "List available targets. Optional positional filter: `hermes send --list telegram`."
- **What it does:** Prints every messaging target Hermes can send to, optionally filtered to one platform.
- **How it works:** `hermes_cli/send_cmd.py:142-229` (`_list_targets`). Loads `gateway.channel_directory.load_directory()` and takes `raw["platforms"]`, then merges in every platform from `gateway.config.load_gateway_config().get_connected_platforms()` (skipping `local`, `api_server`, `webhook`) with an empty channel list — so a configured-but-never-discovered platform (e.g. a fresh SimpleX used only for outbound `hermes send`) is still listed. Unfiltered human output reuses `format_directory_for_display(platforms)` — the exact rendering the `send_message` tool shows the model. Filtered output is built locally as `"<platform>:"` then `"  <platform>:<name>[  [<chat_id>]]"` per channel, or `"  (no channels discovered yet)"`.
- **Inputs / options:** the optional positional filter (argparse stores it in `message` because `--list` takes no argument); `--json`.
- **Outputs / side effects:** `--json` prints `{"platforms": {...}}` with `indent=2, default=str`. Empty directory prints "No messaging platforms configured or no channels discovered yet.", "Set one up with `hermes gateway setup`, or run the gateway once so", "channel discovery can populate ~/.hermes/channel_directory.json." (exit 0).
- **Config / env:** `$HERMES_HOME/channel_directory.json`, gateway config.
- **Edge cases / guards:** Directory-load failure prints "hermes send: failed to load channel directory: <exc>" or "hermes send: failed to read channel directory: <exc>" and exits 1. An unmatched filter prints "hermes send: no targets found for platform '<x>'. Configured: <sorted list or (none)>" and exits 1. A gateway-config parse error is swallowed so the directory contents still list.
- **Rebuild notes:** merge "discovered" and "configured" sources so the list never hides a working target.

### hermes login (deprecated)  `id: cli-b.login`
- **Surface:** CLI
- **Where:** `hermes login [-h] [--provider PROVIDER] [--portal-url …] [--inference-url …] [--client-id …] [--scope …] [--no-browser] [--timeout …] [--ca-bundle …] [--insecure]`; description "Deprecated. Use `hermes auth` to manage credentials, `hermes model` to select a provider, or `hermes setup` for full setup."
- **What it does:** Prints a deprecation notice pointing at the replacement commands and exits 0. It performs no authentication.
- **How it works:** Parser `hermes_cli/subcommands/login.py:12-79` deliberately registers the sub-parser **without** a `help=` kwarg so the row is omitted from `hermes --help` — argparse only lists sub-commands that have a help string, and `help=argparse.SUPPRESS` would leak `==SUPPRESS==` on Python 3.12+ (issue #24756). Handler `hermes_cli/main.py:5598-5602` → `hermes_cli/auth.py:8041-8046` (`login_command`), which prints "The 'hermes login' command has been removed.", "Use 'hermes auth' to manage credentials,", "'hermes model' to select a provider, or 'hermes setup' for full setup." then `raise SystemExit(0)`.
- **Inputs / options:** All nine flags are still accepted and all are ignored: `-h/--help`; `--provider PROVIDER` (no `choices=` on purpose so `hermes login --provider anthropic` reaches the friendly redirect instead of dying with an argparse "invalid choice" error; help "(deprecated) Provider name; ignored — see `hermes model`"); `--portal-url PORTAL_URL` ("Portal base URL (default: production portal)"); `--inference-url INFERENCE_URL` ("Inference API base URL (default: production inference API)"); `--client-id CLIENT_ID` ("OAuth client id to use (default: hermes-cli)"); `--scope SCOPE` ("OAuth scope to request"); `--no-browser` ("Do not attempt to open the browser automatically"); `--timeout TIMEOUT` (float, default 15.0; "HTTP request timeout in seconds (default: 15)"); `--ca-bundle CA_BUNDLE` ("Path to CA bundle PEM file for TLS verification"); `--insecure` ("Disable TLS verification (testing only)").
- **Outputs / side effects:** three stdout lines, exit code 0. Nothing is written.
- **Config / env:** none.
- **Edge cases / guards:** The sub-parser stays registered so old scripts and shell aliases get an actionable message instead of `invalid choice: 'login'`.
- **Rebuild notes:** the pattern worth copying is "keep the parser, drop the help row, print a redirect, exit 0" — a removed command should never fail at the argument layer before it can explain itself.

### hermes logout  `id: cli-b.logout`
- **Surface:** CLI
- **Where:** `hermes logout [-h] [--provider {nous,openai-codex,xai-oauth,spotify}]`; top-level help row "Clear authentication for an inference provider"; description "Remove stored credentials and reset provider config".
- **What it does:** Clears the stored auth state for one provider and, when that provider is also the configured inference provider, resets `model.provider` back to auto.
- **How it works:** Parser `hermes_cli/subcommands/logout.py:12-28`; handler `hermes_cli/main.py:5605-5609` → `hermes_cli/auth.py:9512-9541` (`logout_command`). Target resolution: explicit `--provider` → `get_active_provider()` → `_logout_default_provider_from_config()` (`auth.py:7647-7659`), which returns the config's provider only when it is one of `nous`, `openai-codex`, `xai-oauth` — this exists because logout historically keyed off `auth.json.active_provider` alone, leaving users stuck when auth state was already cleared but `config.yaml` still selected an OAuth provider. `_should_reset_config_provider_on_logout` (`auth.py:7639-7644`) is true when the target is in `PROVIDER_REGISTRY` **and** `_config_provider_matches(target)`. Then `clear_provider_auth(target)` and, if applicable, `_reset_config_provider()` (`auth.py:7662+`) rewrites `config.yaml`.
- **Inputs / options:** `-h/--help`; `--provider` with exactly four choices `nous`, `openai-codex`, `xai-oauth`, `spotify` (default None = "the active provider").
- **Outputs / side effects:** Removes the provider block from `~/.hermes/auth.json`; may rewrite `model.provider` in `config.yaml`. Messages: "No provider is currently logged in." (nothing to target); "Logged out of <display name>." followed by one of "Hermes will use OpenRouter for inference." (config was reset and `OPENROUTER_API_KEY` is set), "Run `hermes model` or configure an API key to use Hermes." (config was reset, no fallback key), or "Model provider configuration was unchanged."; "No auth state found for <display name>." when nothing was cleared.
- **Config / env:** `auth.json`, `model.provider` in `config.yaml`, `OPENROUTER_API_KEY`.
- **Edge cases / guards:** An unknown provider (only reachable when `choices` is bypassed) prints "Unknown provider: <p>" and exits 1. `hermes auth logout <provider>` reaches the same function through `auth_logout_command` with an unrestricted provider id.
- **Rebuild notes:** fall back to the *config's* provider when the auth store has no active one — that is the fix for the "cannot log out of a provider whose tokens are already gone" trap.

### hermes logout --provider nous  `id: cli-b.logout.nous`
- **Surface:** CLI
- **Where:** `hermes logout --provider nous`.
- **What it does:** Clears the Nous Portal OAuth state and resets the inference provider when Nous was selected.
- **How it works:** `logout_command` with `target="nous"`; `nous` is in `PROVIDER_REGISTRY` so `_should_reset_config_provider_on_logout` returns true whenever `model.provider` is `nous`, and `_reset_config_provider()` runs. `clear_provider_auth("nous")` removes `providers.nous` from `auth.json`.
- **Inputs / options:** none beyond the flag.
- **Outputs / side effects:** "Logged out of <Nous display name>." plus the OpenRouter/`hermes model` follow-up line.
- **Config / env:** `auth.json` → `providers.nous`; `model.provider`.
- **Edge cases / guards:** The pooled `nous` credential-pool entries are a separate surface — `hermes auth remove nous <target>` manages those.
- **Rebuild notes:** clearing OAuth state and clearing the provider selection are two distinct writes; do both or say which you skipped.

### hermes logout --provider openai-codex  `id: cli-b.logout.openai-codex`
- **Surface:** CLI
- **Where:** `hermes logout --provider openai-codex`.
- **What it does:** Clears Hermes' own OpenAI Codex OAuth session (independent of Codex CLI / VS Code) and resets the provider if it was selected.
- **How it works:** Same `logout_command` path with `target="openai-codex"`. Hermes keeps its own device-code session precisely so this logout does not disturb `~/.codex/auth.json`.
- **Inputs / options:** none beyond the flag.
- **Outputs / side effects:** removes the Codex block from `auth.json`; may reset `model.provider`.
- **Config / env:** `auth.json`, `model.provider`, `HERMES_CODEX_BASE_URL` (used at login time, not logout).
- **Edge cases / guards:** Pool entries added by `hermes auth add openai-codex` carry `source=manual:device_code` and are self-contained — they are removed with `hermes auth remove`, not by this command.
- **Rebuild notes:** never share an OAuth session file with a third-party CLI; owning your own session is what makes logout safe.

### hermes logout --provider xai-oauth  `id: cli-b.logout.xai-oauth`
- **Surface:** CLI
- **Where:** `hermes logout --provider xai-oauth`.
- **What it does:** Clears the xAI Grok (SuperGrok / Premium+) OAuth tokens and resets the provider if it was selected.
- **How it works:** Same path with `target="xai-oauth"`; `_normalize_provider` elsewhere also accepts the aliases `grok-oauth`, `x-ai-oauth`, `xai-grok-oauth` (`auth_commands.py:111-122`), though `hermes logout`'s `choices` only accepts the canonical id.
- **Inputs / options:** none beyond the flag.
- **Outputs / side effects:** removes the xAI OAuth singleton from `auth.json`; may reset `model.provider`. The `hermes proxy --provider xai` adapter and xAI TTS both stop working until re-authenticated.
- **Config / env:** `auth.json`, `model.provider`.
- **Edge cases / guards:** Pool entries survive; use `hermes auth remove xai-oauth <target>` or `hermes auth logout xai-oauth`.
- **Rebuild notes:** document which downstream features (proxy, TTS, STT) a provider logout silently disables.

### hermes logout --provider spotify  `id: cli-b.logout.spotify`
- **Surface:** CLI
- **Where:** `hermes logout --provider spotify` (equivalently `hermes auth spotify logout` or `hermes auth logout spotify`).
- **What it does:** Clears the stored Spotify PKCE tokens.
- **How it works:** Same `logout_command` path with `target="spotify"`. Spotify is a **service** provider, not an inference provider: it appears in `SERVICE_PROVIDER_NAMES = {"spotify": "Spotify"}` (`auth.py:184-186`) and is absent from `PROVIDER_REGISTRY`, so `_should_reset_config_provider_on_logout` returns False and `model.provider` is never touched — the message is therefore "Logged out of Spotify." + "Model provider configuration was unchanged."
- **Inputs / options:** none beyond the flag.
- **Outputs / side effects:** removes `providers.spotify` (access_token, refresh_token, scope, expiry) from `auth.json`.
- **Config / env:** `auth.json`; `HERMES_SPOTIFY_CLIENT_ID` in `.env` is **not** removed, so `hermes auth spotify` can re-login without repeating the developer-app wizard.
- **Edge cases / guards:** With no stored state the output is "No auth state found for Spotify."
- **Rebuild notes:** separate "service" credentials from "inference provider" credentials so a service logout cannot break the model config.

### hermes auth (command group + interactive mode)  `id: cli-b.auth`
- **Surface:** CLI
- **Where:** `hermes auth [-h] {add,list,remove,reset,status,logout,spotify}`; top-level help row "Manage pooled provider credentials". A bare `hermes auth` opens the interactive manager headed "Credential Pool Status" + a 50-char `=` rule.
- **What it does:** Manages the multi-credential pool per provider — adding, listing, removing, resetting cooldowns, checking status, logging out, and Spotify PKCE.
- **How it works:** Parser `hermes_cli/subcommands/auth.py:12-98`; handler `hermes_cli/main.py:5612-5616` → `hermes_cli/auth_commands.py:877-901` (`auth_command`) dispatching on `auth_action`; no action → `_interactive_auth()` (`auth_commands.py:645-750`). The interactive screen prints the full credential listing, then an AWS Bedrock block when `has_aws_credentials()` — "bedrock (AWS SDK credential chain):", "  Auth: <env var or unknown>", "  Region: <region>", "  Identity: <STS ARN>" or "  Identity: (could not resolve — boto3 STS call failed)" — then an Azure Foundry block when `model.provider == "azure-foundry"` and `model.auth_mode == "entra_id"`: "azure-foundry (Microsoft Entra ID):", "  Endpoint: <base_url or (not configured)>", "  Scope: <scope or SCOPE_AI_AZURE_DEFAULT>", and one of "  Status: ⚠ azure-identity not installed (pip install azure-identity)", "  Status: ✓ token acquired (<env sources or 'default chain'>)", or "  Status: ⚠ <error or 'credential chain exhausted'>" plus an optional "  Hint: <hint>".
- **Inputs / options:** `-h/--help`; sub-commands `add`, `list`, `remove`, `reset`, `status`, `logout`, `spotify`. Interactive menu, printed as "What would you like to do?" with numbered items `  1. Add a credential`, `  2. Remove a credential`, `  3. Reset cooldowns for a provider`, `  4. Set rotation strategy for a provider`, `  5. Exit`, read from `"\nChoice: "` — an empty answer or `5` exits.
- **Outputs / side effects:** `~/.hermes/auth.json` (`credential_pool`, `providers`, `suppressed_sources`), `config.yaml` `credential_pool_strategies`.
- **Config / env:** `credential_pool_strategies.<provider>`; all provider API-key env vars.
- **Edge cases / guards:** Both the Bedrock and Azure blocks are wrapped in try/except so a missing boto3 / azure-identity never breaks the screen. EOF/Ctrl+C at the menu returns silently.
- **Rebuild notes:** one pool file keyed by provider with per-entry {id, label, auth_type, source, tokens, status}; surface non-pool credential chains (AWS, Entra) read-only in the same screen so the user sees everything at once.

### hermes auth add  `id: cli-b.auth.add`
- **Surface:** CLI
- **Where:** `hermes auth add [-h] [--type {oauth,api-key,api_key}] [--label LABEL] [--api-key API_KEY] [--portal-url …] [--inference-url …] [--client-id …] [--scope …] [--no-browser] [--timeout …] [--insecure] [--ca-bundle …] provider`; help "Add a pooled credential".
- **What it does:** Adds one more credential (API key or OAuth account) to a provider's pool so Hermes can rotate between accounts.
- **How it works:** `hermes_cli/auth_commands.py:248-521` (`auth_add_command`). Steps: `_normalize_provider` (aliases `or`/`open-router` → `openrouter`; `grok-oauth`/`x-ai-oauth`/`xai-grok-oauth` → `xai-oauth`; custom-provider display names → their pool key); `_configured_provider_entry` for `providers:`-style entries; `_is_known_provider` gate; `_migrate_legacy_custom_pool_key` moves an old `custom:<name>` pool into the provider's runtime slug and clears the model cache. Default type: `api_key` for `custom:` pools, else `oauth` when the provider is in `_OAUTH_CAPABLE_PROVIDERS = {"anthropic","nous","openai-codex","xai-oauth","qwen-oauth","minimax-oauth"}`, else `api_key`. Before adding, **all** suppressions for the provider are cleared (`unsuppress_credential_source` for every entry in `suppressed_sources[provider]`) because re-adding a credential is a strong signal the user wants auth re-enabled — this covers `env:*`, `gh_cli`, `claude_code`, `qwen-cli`, `device_code`. Each entry gets `id=uuid4().hex[:6]`, `priority=0`, and a `source`.
- **Inputs / options:** positional `provider` ("Provider id (for example: anthropic, openai-codex, openrouter)"); `--type` (dest `auth_type`, choices `oauth`, `api-key`, `api_key`; `api-key` is normalised to `api_key`); `--label LABEL`; `--api-key API_KEY` (otherwise `masked_secret_prompt("Paste your API key: ")`); `--portal-url`, `--inference-url`, `--client-id`, `--scope` (Nous device-code login parameters); `--no-browser`; `--timeout` (float); `--insecure`; `--ca-bundle`. Interactive label prompt when `--label` is omitted and stdin is a TTY: `"Label (optional, default: <default>): "`; default labels are `api-key-<n>` for keys and `<provider>-oauth-<n>` for OAuth.
- **Outputs / side effects:** Per-provider OAuth branches: **anthropic** → `agent.anthropic_adapter.run_hermes_oauth_login_pure()`, source `manual:hermes_pkce`, stores access/refresh/`expires_at_ms`; **nous** → first offers to import a shared credential found at `<hermes-root>/shared/nous_auth.json` ("Found existing Nous OAuth credentials at <path>" / "Found existing shared Nous OAuth credentials", prompt `"Import these credentials? [Y/n]: "`, then "Rehydrating Nous session from shared credentials..." and on failure "Could not refresh shared credentials — falling back to device-code login."), else `_nous_device_code_login(...)`, persisted via `persist_nous_credentials(creds, label=…)`; **openai-codex** → `_codex_device_code_login()` stored as an independent `manual:device_code` pool entry (not through the singleton — the singleton round-trip collapsed every added account into the latest login, issue #39236); **xai-oauth** → `_xai_oauth_device_code_login(timeout_seconds=<timeout or 20.0>, open_browser=…)`, same independent-entry rationale; **qwen-oauth** → `resolve_qwen_runtime_credentials(refresh_if_expiring=False)` + `_mark_qwen_oauth_active`, source `manual:qwen_cli`; **minimax-oauth** → `_minimax_oauth_login(...)`, source `manual:minimax_oauth`. For `openai-codex` and `xai-oauth` the **first** credential also calls `mark_provider_active_if_unset(provider)`. Confirmation lines: `Added <provider> credential #<n>: "<label>"`, `Added <provider> OAuth credential #<n>: "<label>"`, `Saved <provider> OAuth device-code credentials: "<label>"`, `Imported <provider> OAuth credentials: "<label>"`.
- **Config / env:** `auth.json` `credential_pool.<provider>` and `suppressed_sources`; base URL from `_provider_base_url` (OpenRouter constant, custom-provider config, `providers:` entry, or `PROVIDER_REGISTRY[provider].inference_base_url`).
- **Edge cases / guards:** Unknown provider → `SystemExit("Unknown provider: <p>")`. Empty API key → `SystemExit("No API key provided.")`. Anthropic OAuth returning nothing → `SystemExit("Anthropic OAuth login did not return credentials.")`. Any other provider with `--type oauth` → `SystemExit("`hermes auth add <p>` is not implemented for auth type <t> yet.")`. Non-TTY stdin skips the label prompt and uses the default.
- **Rebuild notes:** one independent pool entry per account (never a singleton mirror), plus "adding a credential clears every suppression for that provider" — both are hard-won correctness rules.

### hermes auth list  `id: cli-b.auth.list`
- **Surface:** CLI
- **Where:** `hermes auth list [-h] [provider]`; help "List pooled credentials"; positional help "Optional provider filter".
- **What it does:** Lists every stored credential per provider with its label, type, source, cooldown status, and which one is currently selected.
- **How it works:** `hermes_cli/auth_commands.py:524-559`. Without a filter the provider set is the union of `PROVIDER_REGISTRY` keys, `"openrouter"`, `list_custom_pool_providers()`, every configured `provider_key`, and every key persisted in `auth.json.credential_pool` — sorted. Providers with zero entries are skipped. Header `"<provider> (<n> credentials):"`; each row `"  #<idx>  <label:<20> <auth_type:<7> <source><status> <marker>"` right-stripped, where the marker is `"← "` for `pool.peek()`'s entry and `"  "` otherwise, and `_display_source` strips a leading `manual:` prefix.
- **Inputs / options:** `-h/--help`; optional positional `provider` (normalised through the same alias map as `add`).
- **Outputs / side effects:** stdout only.
- **Config / env:** `auth.json`.
- **Edge cases / guards:** A blank line follows each provider block.
- **Rebuild notes:** show the *selected* entry inline — rotation is invisible otherwise.

### auth — exhaustion status rendering  `id: cli-b.auth.exhaustion-status`
- **Surface:** CLI
- **Where:** The trailing status text on each `hermes auth list` / interactive-remove row.
- **What it does:** Explains why a credential is unusable and, when it is a temporary cooldown, how long is left.
- **How it works:** `hermes_cli/auth_commands.py:200-245`. `_classify_exhausted_status(entry)` returns `("rate-limited", True)` when `last_error_code == 429` or the reason contains `rate_limit`/`usage_limit`/`quota`/`exhausted` or the message contains "rate limit"/"usage limit"/"quota"/"too many requests"; `("auth failed", False)` when the code is 401/403 or the reason contains `invalid_token`/`invalid_grant`/`unauthorized`/`forbidden`/`auth` or the message contains "unauthorized"/"forbidden"/"expired"/"revoked"/"invalid token"/"authentication"; otherwise `("exhausted", True)`. `_format_exhausted_status` returns "" unless `last_status == STATUS_EXHAUSTED`, then renders `" <label><reason><(code)>"` plus, for non-retryable states, "(re-auth may be required)"; for retryable ones "(ready to retry)" when the window has passed, or "(<wait> left)" formatted as `Xd Yh`, `Xh Ym`, `Xm Ys`, or `Xs`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** display text only.
- **Config / env:** n/a.
- **Edge cases / guards:** An exhausted entry with no computable window shows the bare label + reason + code.
- **Rebuild notes:** distinguish "rate-limited, wait" from "auth failed, re-login" — the two need different user actions.

### hermes auth remove  `id: cli-b.auth.remove`
- **Surface:** CLI
- **Where:** `hermes auth remove [-h] provider target`; help "Remove a pooled credential by index, id, or label".
- **What it does:** Deletes one credential from a provider's pool and performs the source-specific cleanup (e.g. suppressing an env-var-derived credential so it does not reappear).
- **How it works:** `hermes_cli/auth_commands.py:562-597`. `pool.resolve_target(target)` accepts a 1-based index, the 6-hex entry id, or an exact label; then `pool.remove_index(index)`. Cleanup goes through `agent.credential_sources.find_removal_step(provider, removed.source)`: an unregistered source (e.g. plain `manual`) has nothing external to clean and the function returns; otherwise `step.remove_fn(provider, removed)` returns a result whose `cleaned` lines are printed, whose `suppress` flag triggers `suppress_credential_source(provider, removed.source)`, and whose `hints` lines are printed last. This is what makes removal uniform across env vars, external OAuth files, `auth.json` blocks and custom config.
- **Inputs / options:** `-h/--help`; positional `provider` ("Provider id"); positional `target` ("Credential index, entry id, or exact label"). A legacy `args.index` is accepted as a fallback when `target` is None.
- **Outputs / side effects:** "Removed <provider> credential #<index> (<label>)" plus any cleanup/hint lines; writes `auth.json` (`credential_pool`, possibly `suppressed_sources`).
- **Config / env:** `auth.json`.
- **Edge cases / guards:** An unresolvable target → `SystemExit("<error> Provider: <provider>.")`; a resolved-but-missing entry → `SystemExit('No credential matching "<target>" for provider <provider>.')`.
- **Rebuild notes:** a removal-step registry per credential source is the right abstraction — deleting a pool row is rarely the whole job.

### hermes auth reset  `id: cli-b.auth.reset`
- **Surface:** CLI
- **Where:** `hermes auth reset [-h] provider`; help "Clear exhaustion status for all credentials for a provider".
- **What it does:** Clears rate-limit/exhaustion cooldowns so every credential in the pool becomes selectable again immediately.
- **How it works:** `hermes_cli/auth_commands.py:600-604`: `load_pool(provider).reset_statuses()` returns the number of entries touched.
- **Inputs / options:** `-h/--help`; positional `provider` ("Provider id"), normalised through the alias map.
- **Outputs / side effects:** "Reset status on <n> <provider> credentials"; writes `auth.json`.
- **Config / env:** `auth.json`.
- **Edge cases / guards:** Safe on a provider with no entries (prints 0). Resetting does not re-validate the credentials — a genuinely revoked key will simply fail again on next use.
- **Rebuild notes:** cooldowns must be resettable by hand; a provider's own limit windows are not always what the client recorded.

### hermes auth status  `id: cli-b.auth.status`
- **Surface:** CLI
- **Where:** `hermes auth status [-h] provider`; help "Show auth status for a provider".
- **What it does:** Reports whether a provider is logged in, and prints the known auth metadata.
- **How it works:** `hermes_cli/auth_commands.py:607-624`. Calls `hermes_cli.auth.get_auth_status(provider)`; when `logged_in` is false it prints "<provider>: logged out (<error>)" or "<provider>: logged out"; otherwise "<provider>: logged in" followed by any of these six fields that are set, each as `  <key>: <value>`, in exactly this order: `auth_type`, `client_id`, `redirect_uri`, `scope`, `expires_at`, `api_base_url`.
- **Inputs / options:** `-h/--help`; positional `provider` ("Provider id").
- **Outputs / side effects:** stdout only.
- **Config / env:** `auth.json`.
- **Edge cases / guards:** An empty provider → `SystemExit("Provider is required. Example: `hermes auth status spotify`.")`.
- **Rebuild notes:** print only populated fields, in a fixed order, so the output diffs cleanly across runs.

### hermes auth logout  `id: cli-b.auth.logout`
- **Surface:** CLI
- **Where:** `hermes auth logout [-h] provider`; help "Log out a provider and clear stored auth state".
- **What it does:** Same as `hermes logout --provider <p>` but accepts any provider id, not just the four in `hermes logout`'s choices.
- **How it works:** `hermes_cli/auth_commands.py:627-628` builds a `SimpleNamespace(provider=<provider>)` and calls `hermes_cli.auth.logout_command` — so all the target-resolution and config-reset behaviour of `cli-b.logout` applies.
- **Inputs / options:** `-h/--help`; positional `provider` ("Provider id").
- **Outputs / side effects:** identical to `hermes logout`.
- **Config / env:** `auth.json`, `model.provider`.
- **Edge cases / guards:** An id `is_known_auth_provider()` rejects prints "Unknown provider: <p>" and exits 1.
- **Rebuild notes:** one logout implementation, two entry points with different validation strictness — document which is the permissive one.

### hermes auth spotify  `id: cli-b.auth.spotify`
- **Surface:** CLI
- **Where:** `hermes auth spotify [-h] [--client-id CLIENT_ID] [--redirect-uri REDIRECT_URI] [--scope SCOPE] [--no-browser] [--timeout TIMEOUT] [{login,status,logout}]`; help "Authenticate Hermes with Spotify via PKCE".
- **What it does:** Runs the Spotify Authorization-Code-with-PKCE login (with a first-time developer-app wizard), or reports/clears that state.
- **How it works:** `hermes_cli/auth_commands.py:631-642` (`auth_spotify_command`) dispatches: `""`/`login` → `hermes_cli.auth.login_spotify_command(args)` (`auth.py:3554-3646`); `status` → `auth_status_command(SimpleNamespace(provider="spotify"))`; `logout` → `auth_logout_command(SimpleNamespace(provider="spotify"))`. The login flow: resolve `client_id` (`--client-id` → `HERMES_SPOTIFY_CLIENT_ID` → `SPOTIFY_CLIENT_ID` → stored state) and on `spotify_client_id_missing` run `_spotify_interactive_setup`; resolve redirect URI (`--redirect-uri` → `HERMES_SPOTIFY_REDIRECT_URI` → `SPOTIFY_REDIRECT_URI` → stored state → default `http://127.0.0.1:43827/spotify/callback`), scope, accounts base URL (default `https://accounts.spotify.com`) and API base URL (default `https://api.spotify.com/v1`); generate a code verifier + S256 challenge and a `uuid4().hex` state nonce; build and print the authorize URL; open a browser unless `--no-browser`, the session is remote (`_is_remote_session()`), or no graphical browser exists; run a loopback callback server; exchange the code for tokens; store under `providers.spotify` with `set_active=False` so the inference provider is untouched.
- **Inputs / options:** `-h/--help`; positional `spotify_action` (`nargs="?"`, choices `login`, `status`, `logout`, default `login`); `--client-id CLIENT_ID` ("Spotify app client_id (or set HERMES_SPOTIFY_CLIENT_ID)"); `--redirect-uri REDIRECT_URI` ("Allow-listed localhost redirect URI for your Spotify app"); `--scope SCOPE` ("Override requested Spotify scopes"); `--no-browser` ("Do not attempt to open the browser automatically"); `--timeout TIMEOUT` (float; "Callback/token exchange timeout in seconds" — used as the callback wait with default 180.0 s and the token exchange with default 20.0 s).
- **Outputs / side effects:** Writes `providers.spotify` into `auth.json`. Login prints "Starting Spotify PKCE login...", "Client ID: <id>", "Redirect URI: <uri>", "Make sure this redirect URI is allow-listed in your Spotify app settings.", "Open this URL to authorize Hermes:", the authorize URL, "Full setup guide: https://hermes-agent.nousresearch.com/docs/user-guide/features/spotify", an SSH loopback hint when relevant (`_print_loopback_ssh_hint`, docs `https://hermes-agent.nousresearch.com/docs/guides/oauth-over-ssh`), then "Browser opened for Spotify authorization." or "Could not open the browser automatically; use the URL above.", and finally "Spotify login successful!", "  Auth state: <path>", "  Docs: <SPOTIFY_DOCS_URL>".
- **Config / env:** `HERMES_SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_ID`, `HERMES_SPOTIFY_REDIRECT_URI`, `SPOTIFY_REDIRECT_URI`, `HERMES_SPOTIFY_API_BASE_URL`, `HERMES_SPOTIFY_ACCOUNTS_BASE_URL`; `auth.json` `providers.spotify`. Default scope (`auth.py:172-183`), ten space-separated values: `user-modify-playback-state user-read-playback-state user-read-currently-playing user-read-recently-played playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private user-library-read user-library-modify`. Access tokens are refreshed with a 120-second skew (`SPOTIFY_ACCESS_TOKEN_REFRESH_SKEW_SECONDS`).
- **Edge cases / guards:** A callback carrying `error` → `SystemExit("Spotify authorization failed: <error_description or error>")`; a mismatched state nonce → `SystemExit("Spotify authorization failed: state mismatch.")`. An unknown action → `SystemExit("Unknown Spotify auth action: <action>")`.
- **Rebuild notes:** PKCE + loopback callback + state-nonce check, with the client_id persisted so the developer-app wizard runs exactly once per machine.

### auth spotify — first-time developer-app wizard  `id: cli-b.auth.spotify.setup`
- **Surface:** CLI
- **Where:** Runs automatically inside `hermes auth spotify login` when no client_id is configured; header "Spotify first-time setup" between two 70-character `=` rules.
- **What it does:** Walks the user through registering their own Spotify developer app and stores the resulting Client ID.
- **How it works:** `hermes_cli/auth.py:3495-3551` (`_spotify_interactive_setup`). Opens `https://developer.spotify.com/dashboard` in a browser unless the session is remote, then prompts for the id.
- **Inputs / options:** one prompt, `"Spotify Client ID: "`.
- **Outputs / side effects:** Verbatim body: "Spotify requires every user to register their own lightweight", "developer app. This takes about two minutes and only has to be", "done once per machine.", "Full guide: https://hermes-agent.nousresearch.com/docs/user-guide/features/spotify", "Steps:", "  1. Opening https://developer.spotify.com/dashboard in your browser...", "  2. Click 'Create app' and fill in:", "       App name:     anything (e.g. hermes-agent)", "       Description:  anything", "       Redirect URI: <redirect_uri_hint>", "       API/SDK:      Web API", "  3. Agree to the terms, click Save.", "  4. Open the app's Settings page and copy the Client ID.", "  5. Paste it below." Saves `HERMES_SPOTIFY_CLIENT_ID` and, only when the hint differs from the default, `HERMES_SPOTIFY_REDIRECT_URI`; prints "Saved HERMES_SPOTIFY_CLIENT_ID to ~/.hermes/.env".
- **Config / env:** `HERMES_SPOTIFY_CLIENT_ID`, `HERMES_SPOTIFY_REDIRECT_URI`.
- **Edge cases / guards:** Ctrl+C/EOF → `SystemExit("Spotify setup cancelled.")`; an empty id prints "No Client ID entered. See <docs> for the full guide." then `SystemExit("Spotify setup cancelled: empty Client ID.")`. The redirect URI is only pinned when non-default so a future default change is not blocked.
- **Rebuild notes:** when a provider forces per-user app registration, script the registration steps rather than erroring on a missing env var.

### auth — interactive add / remove / reset / strategy  `id: cli-b.auth.interactive`
- **Surface:** CLI
- **Where:** The four menu items of a bare `hermes auth`.
- **What it does:** Guided equivalents of `auth add`, `auth remove`, `auth reset`, plus the rotation-strategy editor that has no flag-based counterpart.
- **How it works:** `hermes_cli/auth_commands.py:753-874`. `_pick_provider(prompt)` prints "Known providers: <sorted PROVIDER_REGISTRY + openrouter>" and, when custom endpoints exist, "Custom endpoints: <display names>", then reads `"<prompt>: "`. `_interactive_add` asks the type for OAuth-capable providers with "  1. API key (paste a key from the provider dashboard)" / "  2. OAuth login (authenticate via browser)" read from `"Type [1/2]: "` (2 → oauth, anything else → api_key), then "Label / account name (optional): ", and delegates to `auth_add_command`. `_interactive_remove` prints "No credentials for <provider>." when the pool is empty, otherwise each entry as `  #<i>  <label:25s> <auth_type:10s> <source><exhausted> [id:<id>]` and reads "Remove #, id, or label (blank to cancel): ". `_interactive_reset` delegates to `auth_reset_command`. `_interactive_strategy` prints "Current strategy for <provider>: <current>" then the four options with descriptions — `fill_first` "Use first key until exhausted, then next", `round_robin` "Cycle through keys evenly", `least_used` "Always pick the least-used key", `random` "Random selection" — marking the current one with " ←", read from "\nStrategy [1-4]: ".
- **Inputs / options:** the prompts above; blank/EOF cancels each flow.
- **Outputs / side effects:** the strategy editor writes `config.yaml` `credential_pool_strategies[<provider>]` and prints "Set <provider> strategy to: <strategy>".
- **Config / env:** `credential_pool_strategies.<provider>`.
- **Edge cases / guards:** A non-numeric or out-of-range strategy choice prints "Invalid choice." and returns; an unknown provider raises `SystemExit("Unknown provider: <p>")`; `_pick_provider` raises a bare `SystemExit()` on Ctrl+C/EOF.
- **Rebuild notes:** the rotation strategy is CLI-only through this menu — a reimplementation should expose it as `hermes auth strategy <provider> <name>` too.

### hermes status  `id: cli-b.status`
- **Surface:** CLI
- **Where:** `hermes status [-h] [--all] [--deep]`; top-level help row "Show status of all components"; description "Display status of Hermes Agent components"; banner `┌…┐` / `│                 ⚕ Hermes Agent Status                  │` / `└…┘`.
- **What it does:** One screen covering environment, API keys, OAuth providers, the Nous Tool Gateway, API-key providers, terminal backend, messaging platforms, gateway service, cron jobs, sessions, and (optionally) live connectivity checks.
- **How it works:** Parser `hermes_cli/subcommands/status.py:12-27`; handler `hermes_cli/main.py:5619-5623` → `hermes_cli/status.py:132` (`show_status`). Sections in order, each headed by a cyan `◆` title: **pause banner** (see `cli-b.status.estop-banner`); **◆ Environment** — `  Project:      <PROJECT_ROOT>`, `  Python:       <version>`, `  .env file:    <✓|✗> exists|not found`, `  Model:        <_configured_model_label(config)>`, `  Provider:     <_effective_provider_label()>`; **◆ API Keys** — one `  <name:<12>  <✓|✗> <redacted>` row per entry in the key map, each value masked by `agent.redact.mask_secret` with "(not set)" in dim when empty; **◆ Auth Providers** with per-provider detail lines `    Portal URL:`, `    Inference:`, `    Access exp:`, `    Key exp:`, `    Refresh:`, `    Error:` (Nous), `    Auth file:` / `    Refreshed:` / `    Error:` (Codex, xAI), `    Auth file:` / `    Access exp:` / `    Error:` (Qwen), `    Region:` / `    Access exp:` / `    Error:` (MiniMax); **◆ Nous Tool Gateway** — "  Nous Portal   ✗ not logged in" or "  Nous Portal   ✓ managed tools available" plus one `  <feature label:<15> <✓|✗> <state>` row per subscription feature; **◆ API-Key Providers** — `  <provider:<16> <✓|✗> <label>` plus an LM Studio probe row `  LM Studio        <✓|✗> <msg>`; **◆ Terminal Backend** — `  Backend:      <TERMINAL_ENV>` plus backend-specific rows (`  SSH Host:`, `  SSH User:`, `  Docker Image:`, `  Daytona Image:`, and for Vercel `  Runtime:`, `  SDK:`, `  Auth:`, `  Auth detail:`, `  Persistence:      snapshot filesystem|ephemeral filesystem`, "  Processes:    live processes do not survive cleanup, snapshots, or sandbox recreation"), plugin-backend rows `  <label>: <✓|✗> <detail>`, and `  Sudo:         <✓|✗> enabled|disabled`; **◆ Messaging Platforms** — `  <name:<12>  <✓|✗> <status>` and plugin rows `  <label:<12>  <✓|✗> <status> (plugin)`; **◆ Gateway Service** (see below); **◆ Scheduled Jobs** — `  Jobs:         <n> active, <m> total`, "  Jobs:         (error reading jobs file)", or "  Jobs:         0"; **◆ Sessions** — `  Active:       <n> session(s)`, `  Last activity:<relative>`, "  Active:       (error reading sessions file)", and the slot block described below; then optional **◆ Deep Checks**; then a dim 60-char rule with "  Run 'hermes doctor' for detailed diagnostics" and "  Run 'hermes setup' to configure".
- **Inputs / options:** `-h/--help`; `--all` ("Show all details (redacted for sharing)"); `--deep` ("Run deep checks (may take longer)"). **Note:** `show_status` reads only `args.deep` (`status.py:134`) — `--all` is accepted and currently has no effect on the output.
- **Outputs / side effects:** stdout only; no config is written. `--deep` performs network I/O: an `httpx.get(OPENROUTER_MODELS_URL, headers={"Authorization": "Bearer <key>"}, timeout=10)` printed as `  OpenRouter:   <✓|✗> reachable|error (<status>)` or `  OpenRouter:   ✗ error: <exc>` (only when `OPENROUTER_API_KEY` is set), and a 1-second TCP connect to `127.0.0.1:18789` printed as `  Port 18789:   in use|available`.
- **Config / env:** The API-key map (`status.py:171-192`), all 20 rows: OpenRouter=`OPENROUTER_API_KEY`, OpenAI=`OPENAI_API_KEY`, Anthropic=(`ANTHROPIC_API_KEY`,`ANTHROPIC_TOKEN`), Google / Gemini=(`GOOGLE_API_KEY`,`GEMINI_API_KEY`), DeepSeek=`DEEPSEEK_API_KEY`, xAI / Grok=`XAI_API_KEY`, NVIDIA NIM=`NVIDIA_API_KEY`, Z.AI / GLM=`GLM_API_KEY`, Kimi=`KIMI_API_KEY`, StepFun Step Plan=`STEPFUN_API_KEY`, MiniMax=`MINIMAX_API_KEY`, MiniMax-CN=`MINIMAX_CN_API_KEY`, DeepInfra=`DEEPINFRA_API_KEY`, Firecrawl=`FIRECRAWL_API_KEY`, Keenable=`KEENABLE_API_KEY`, Browser Use=`BROWSER_USE_API_KEY`, Browserbase=`BROWSERBASE_API_KEY`, FAL=`FAL_KEY`, ElevenLabs=`ELEVENLABS_API_KEY`, GitHub=`GITHUB_TOKEN`. Also `TERMINAL_ENV`, `TERMINAL_SSH_HOST/USER`, `terminal.docker_image`, `terminal.daytona_image`, `terminal.vercel_runtime`, `agent.max_concurrent_sessions`.
- **Edge cases / guards:** The Anthropic row is skipped in the generic loop and printed once at the end from `get_anthropic_key()` so OAuth-resolved tokens count and no duplicate row appears. `load_config()` failure falls back to `{}`. Tuple-valued env refs resolve first-non-empty via `_resolve_env`. Every optional import (boto3, azure-identity, plugin registries) is wrapped.
- **Rebuild notes:** a single read-only screen whose every row is derived from the same resolvers the runtime uses — never a second source of truth. Wire `--all` to something (or drop it) rather than shipping an inert flag.

### status — ESTOP pause banner  `id: cli-b.status.estop-banner`
- **Surface:** CLI
- **Where:** Immediately under the `hermes status` banner when the global emergency stop is engaged.
- **What it does:** Says loudly that dispatch is paused and how to lift it.
- **How it works:** `hermes_cli/status.py:115-129` (`_estop_status_line`) calls `agent.estop.get_state()` — a single `os.stat` — and returns `f"⏸️  PAUSED (global emergency stop{suffix}; `hermes resume` to lift)"` where `suffix` is `" — reason: <reason>"` when a reason was recorded. Printed in yellow + bold.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one line; nothing else in the screen changes.
- **Config / env:** `$HERMES_HOME/ESTOP` (and the fleet-root sentinel).
- **Edge cases / guards:** Returns None when `agent.estop` cannot be imported or the sentinel is absent.
- **Rebuild notes:** a paused system must announce it at the top of every status surface.

### status — Gateway Service block  `id: cli-b.status.gateway-service`
- **Surface:** CLI
- **Where:** `hermes status` → "◆ Gateway Service".
- **What it does:** Reports whether the gateway is running, which service manager owns it, and its PIDs.
- **How it works:** `hermes_cli/status.py:562-596`. Uses a gateway snapshot (`snapshot.manager`, `snapshot.gateway_pids`) and `_is_service_running`.
- **Inputs / options:** none.
- **Outputs / side effects:** Lines, verbatim: `  Status:       <✓|✗> running|stopped`; `  Manager:      <manager>`; `  PID(s):       <formatted pids>`; "  Service:      installed but not managing the current running gateway"; "  Start with:   hermes gateway"; "  Note:         Android may stop background jobs when Termux is suspended"; "  Service:      installed but stopped"; and the unknown-manager variants `  Status:       unknown` (dim) with "  Manager:      Termux / manual process", "  Manager:      systemd/manual", or "  Manager:      launchd", plus `  Status:       N/A` (dim) with "  Manager:      (not supported on this platform)".
- **Config / env:** `HERMES_HOME` (service naming).
- **Edge cases / guards:** Platform differences are explicit rather than hidden behind a generic "unknown".
- **Rebuild notes:** distinguish "installed but stopped" from "installed but not managing this process" — they need different fixes.

### status — session slot usage  `id: cli-b.status.session-slots`
- **Surface:** CLI
- **Where:** `hermes status` → "◆ Sessions" → the `  Slots:` line, shown only when a concurrency cap is configured.
- **What it does:** Shows how many concurrent-session slots are in use across every surface and who holds them.
- **How it works:** `hermes_cli/status.py:664-694`. `resolve_max_concurrent_sessions(config)` gives the cap; `active_session_registry_snapshot()` the holders. Prints `  Slots:        <held>/<cap> in use` coloured yellow when full and green otherwise, then one indented row per holder sorted by `started_at`: 16 spaces + `<surface or 'unknown':<17> <session_id or '?':<24> <age>` where age comes from `format_age(now - started_at)`.
- **Inputs / options:** none.
- **Outputs / side effects:** stdout.
- **Config / env:** `agent.max_concurrent_sessions`; `$HERMES_HOME/runtime/active_sessions.json`.
- **Edge cases / guards:** The whole block is skipped when no cap is set; snapshot failure falls back to an empty list. The rationale in the source is that the cap is shared between CLI, desktop/TUI and gateway, so the surface that gets rejected is rarely the one holding the slots.
- **Rebuild notes:** when a limit is shared across surfaces, always show who is holding it — otherwise the only diagnosis is reading a JSON file by hand.

### hermes pause (global emergency stop)  `id: cli-b.pause`
- **Surface:** CLI
- **Where:** `hermes pause [-h] [--reason REASON]`; top-level help row "Emergency stop: pause cron/kanban dispatch and new gateway turns"; description "Engage the global emergency stop. Halts NEW work only — cron dispatch, kanban dispatch, and new gateway turns — until `hermes resume`. In-flight work is never killed."
- **What it does:** Writes a sentinel file that stops the scheduler, the kanban dispatcher and new gateway turns from starting new work. Running work continues to completion.
- **How it works:** `hermes_cli/subcommands/pause.py:17-33` (`cmd_pause`) → `agent.estop.engage(reason=…)` (`agent/estop.py:110-126`), which writes `$HERMES_HOME/ESTOP` containing `{"engaged_at": "<UTC ISO-8601>", "reason": <reason or null>}` pretty-printed with a trailing newline; on `OSError` it falls back to `path.touch(exist_ok=True)` because an empty sentinel must still pause (fail-safe). `is_engaged()` is checked first so the verb can be "Still paused" instead of "Hermes paused". Consumers: `cron/scheduler.py:tick`, `gateway/kanban_watchers.py`, `gateway/run.py:_handle_message` — all via `check_paused(component, logger)` (`estop.py:199-225`) which logs once per engagement per component instead of once per tick.
- **Inputs / options:** `-h/--help`; `--reason REASON` ("Optional reason stored in the sentinel and shown to users").
- **Outputs / side effects:** Creates `$HERMES_HOME/ESTOP`. Prints `⏸️  <Hermes paused|Still paused>[ — reason: <reason>]`, then `    sentinel: <path>`, then "    Cron dispatch, kanban dispatch, and new gateway turns are on hold." and "    In-flight work keeps running. Run `hermes resume` to lift the pause." Returns 0. While engaged, new gateway turns receive `agent.estop.paused_reply()`: "⏸️ Hermes is paused (<reason>). New work is on hold; run `hermes resume` to pick things back up." or the same sentence without the parenthetical.
- **Config / env:** `HERMES_HOME` (profile sentinel) and the fleet root from `get_default_hermes_root()`.
- **Edge cases / guards:** Idempotent — re-running updates the file and reports "Still paused". Detection is fail-safe in two ways: a stat error counts as engaged (`is_engaged` returns True when any candidate path raised `OSError`), and a corrupt/empty body still counts as engaged with `{"reason": None, "engaged_at": None}`. Detection is also profile-aware: `_candidate_sentinel_paths()` checks the process `HERMES_HOME` **and** the fleet canonical root, because profile gateways run with `HERMES_HOME=~/.hermes/profiles/<name>` while an operator's `hermes pause` writes `~/.hermes/ESTOP` — without the second path the pause would not bind. Note the asymmetry: `engage()` writes only `sentinel_path()` (the process home).
- **Rebuild notes:** a file sentinel with no caching, checked with one stat per dispatch tick, fail-safe on error, plus per-component log-once bookkeeping. Deliberately *not* panic/kill semantics — pause-new-work is resumable.

### hermes resume  `id: cli-b.resume`
- **Surface:** CLI
- **Where:** `hermes resume [-h]`; top-level help row "Lift the emergency stop set by `hermes pause`"; description "Remove the ESTOP sentinel; dispatch resumes on the next tick."
- **What it does:** Deletes the ESTOP sentinel so cron, kanban and gateway dispatch start new work again on their next check — no restart needed.
- **How it works:** `hermes_cli/subcommands/pause.py:36-44` (`cmd_resume`) → `agent.estop.disengage()` (`estop.py:129-145`), which unlinks **every** candidate sentinel path (profile home and fleet root) so a resume issued from inside a profile gateway still clears an operator pause written at `~/.hermes/ESTOP`. Returns True if at least one file was removed.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Prints "▶️  Hermes resumed — dispatch picks up on the next tick." when a sentinel was removed, or "Hermes is not paused (no sentinel at <sentinel_path()>)." otherwise. Returns 0 either way. Each component's log-once flag re-arms automatically the next time `check_paused` sees a disengaged state.
- **Config / env:** `HERMES_HOME`, fleet root.
- **Edge cases / guards:** `FileNotFoundError` and any `OSError`/`AttributeError` per path are skipped so a partially removable set still resumes what it can. Because `disengage()` clears both paths while `engage()` writes only one, resume is strictly broader than pause — intentional, so a stuck fleet sentinel is always liftable.
- **Rebuild notes:** removal must be broader than creation for any safety sentinel; and resumption must not require restarting long-running processes.

### slack manifest — native slash-command generation (50 commands)  `id: cli-b.slack.native-slashes`
- **Surface:** CLI
- **Where:** The `features.slash_commands` array produced by `hermes slack manifest` (and, verbatim, by `--slashes-only`).
- **What it does:** Turns the gateway `COMMAND_REGISTRY` into Slack slash commands, clamped to Slack's 50-command ceiling, skipping names Slack reserves.
- **How it works:** `hermes_cli/commands.py:1496-1601`. `_sanitize_slack_name` (`:1484-1493`) lower-cases, strips everything outside `[a-z0-9_-]` (`_SLACK_INVALID_CHARS`), trims leading/trailing `-`/`_`, and truncates to 32 chars (`_SLACK_NAME_LIMIT`). `_add(name, desc, hint)` skips empty/duplicate names, anything in `_SLACK_RESERVED_COMMANDS`, anything in `_SLACK_VIA_HERMES_ONLY`, and everything once `len(entries) >= 50` (`_SLACK_MAX_SLASH_COMMANDS`); it truncates descriptions to 140 chars and hints to 100. Slot order: (1) `/hermes` is reserved first as the catch-all; (2) `_SLACK_PRIORITY_ALIASES` — currently the empty tuple `()`, because `/bg` and `/btw` were promoted from aliases of `/background` to canonical commands and now win first-pass slots on their own; (3) canonical `COMMAND_REGISTRY` names that pass `_is_gateway_available(cmd, overrides)` where overrides come from `_resolve_config_gates()`; (4) aliases, described as "Alias for /<canonical> — <description>"; (5) plugin commands from `_iter_plugin_command_entries()`. Every entry gets `should_escape: false` and `url` = the `request_url` parameter (default `https://hermes-agent.local/slack/commands`) — a placeholder because Socket Mode routes the command over the WebSocket and Slack ignores the URL.
- **Inputs / options:** n/a (generated); `--slashes-only` emits just this array.
- **Outputs / side effects:** The 50 commands emitted by a stock v2026.8.31 install, in order, as `/<name> — <description> — <usage_hint>`: `/hermes` — "Talk to Hermes or run a subcommand" — `[subcommand] [args]`; `/start` — "Acknowledge platform start pings without a reply"; `/new` — "Start a new session (fresh session ID + history)" — `[name]`; `/save` — "Export the current conversation (bare /save shows usage)" — `<json|md|html> [filename] [redact]`; `/retry` — "Retry the last message (resend to agent)"; `/undo` — "Back up N user turns and re-prompt (default 1)" — `[N]`; `/title` — "Set a title for the current session" — `[name]`; `/branch` — "Branch the current session (explore a different path)" — `[name]`; `/compress` — "Compress conversation context (add 'here [N]' to keep recent N turns; --preview shows what would happen)" — `[here [N] | focus topic | --preview|--dry-run]`; `/rollback` — "List or restore filesystem checkpoints (restores keep your hand-edits; --all overrides)" — `[number] [--all]`; `/stop` — "Kill all running background processes"; `/approve` — "Approve a pending dangerous command" — `[session|always]`; `/deny` — "Deny a pending dangerous command (optionally with a reason)" — `[all] [reason]`; `/bg` — "Run a prompt in a separate background session" — `<prompt>`; `/btw` — "Ask a side question about the current conversation without interrupting it" — `<question>`; `/agents` — "Show active agents and running tasks"; `/queue` — "Queue a prompt for the next turn (doesn't interrupt)" — `<prompt>`; `/steer` — "Inject a message after the next tool call without interrupting" — `<prompt>`; `/goal` — "Set a standing goal Hermes works on across turns until achieved" — `[text | draft <text> | show | gate add <cmd> | pause | resume | clear | status | wait <pid> | unwait`; `/loop` — "Re-run a prompt on a recurring interval in this session" — `[interval] <prompt> [--times N] [--until <condition>] | status | pause | resume | stop`; `/plan` — "Write a markdown implementation plan to .hermes/plans/ without executing anything" — `[task]`; `/subgoal` — "Add or manage extra criteria on the active goal" — `[text | remove N | clear]`; `/context` — "Show detailed context window view with usage gauge, category breakdown, compression stats, and throughput" — `[all]`; `/profile` — "Show active profile name and home directory"; `/sethome` — "Set this chat as the home channel"; `/resume` — "Resume a previously-named session" — `[name]`; `/sessions` — "Browse and resume previous sessions"; `/model` — "Switch model (session-scoped; --global to persist)" — `[model] [--provider name] [--global|--session] [--refresh]`; `/codex-runtime` — "Toggle codex app-server runtime for OpenAI/Codex models" — `[auto|codex_app_server]`; `/personality` — "Set a predefined personality" — `[name]`; `/footer` — "Toggle gateway runtime-metadata footer on final replies" — `[on|off|status]`; `/yolo` — "Toggle YOLO mode (skip all dangerous command approvals)"; `/approvals` — "Show or set the persistent dangerous-command approval mode" — `[manual|smart|off]`; `/reasoning` — "Manage reasoning effort and display" — `[level|show|hide|full|clamp] [--global]`; `/fast` — "Toggle fast mode — OpenAI Priority Processing / Anthropic Fast Mode (Normal/Fast)" — `[normal|fast|status] [--global]`; `/voice` — "Toggle voice mode" — `[on|off|tts|status]`; `/busy` — "Control how messages behave while Hermes is working" — `[queue|steer|interrupt|status]`; `/memory` — "Review pending memory writes / toggle the approval gate" — `[pending|approve|reject|approval] [id|on|off]`; `/bundles` — "List skill bundles (aliases /<name> for multiple skills)"; `/learn` — "Learn a reusable skill from anything you describe (dirs, URLs, this chat, notes)" — `<what to learn from>`; `/suggestions` — "Review suggested automations (accept/dismiss)" — `[accept|dismiss N | catalog]`; `/blueprint` — "Set up an automation from a blueprint template" — `[name] [slot=value ...]`; `/curator` — "Background skill maintenance (status, run, pin, archive, list-archived)" — `[subcommand]`; `/kanban` — "Multi-profile collaboration board (tasks, links, comments)" — `[subcommand]`; `/reload-mcp` — "Reload MCP servers from config"; `/reload-skills` — "Re-scan ~/.hermes/skills/ for newly installed or removed skills"; `/commands` — "Browse all commands and skills (paginated)" — `[page]`; `/help` — "Show available commands (/help skills lists skill commands, /help <text> filters)" — `[skills|<filter>]`; `/restart` — "Gracefully restart the gateway after draining active runs"; `/usage` — "Show token usage and rate limits; `reset` redeems a banked Codex limit reset" — `[reset [--force]]`.
- **Config / env:** Config gates from `_resolve_config_gates()` can hide commands; plugin commands appear when their plugins are enabled.
- **Edge cases / guards:** `_SLACK_RESERVED_COMMANDS` (20 Slack built-ins that apps cannot register) — `me`, `status`, `away`, `dnd`, `shrug`, `remind`, `msg`, `feed`, `who`, `collapse`, `expand`, `leave`, `join`, `open`, `search`, `topic`, `mute`, `pro`, `shortcuts`. `_SLACK_VIA_HERMES_ONLY` (15 canonical commands deliberately denied a native slot because the registry is already at Slack's ceiling) — `topup`, `moa`, `debug`, `egress`, `init`, `version`, `diff`, `update`, `heartbeat`, `refine`, `review`, `pause`, `whoami`, `platform`, `insights`. Everything skipped or clamped stays reachable as `/hermes <command>`. Note `hermes update` can add commands, so the docs tell users to re-run `hermes slack manifest --write` afterwards.
- **Rebuild notes:** a deterministic slot-allocation order (catch-all → pinned aliases → canonical → aliases → plugins) with an explicit reserved-name set and an explicit "via catch-all only" set — that is what keeps the clamp from silently dropping a load-bearing command.

### pause — reason is overwritten on re-engage  `id: cli-b.pause.reason-overwrite`
- **Surface:** CLI
- **Where:** Running `hermes pause` a second time without `--reason` while already paused.
- **What it does:** Re-writes the sentinel with `reason: null`, so the previously recorded reason is lost and the banner becomes a bare "⏸️  Still paused".
- **How it works:** `agent/estop.py:110-126` — `engage(reason=None)` always writes a fresh payload `{"engaged_at": <now>, "reason": None}`; it never merges with an existing sentinel. `cmd_pause` (`hermes_cli/subcommands/pause.py:22-27`) reads `is_engaged()` *before* engaging to choose the verb, then reads `get_state()` *after*, so the detail suffix reflects the new (empty) reason. Verified live: `hermes pause --reason "inventory probe"` → "⏸️  Hermes paused — reason: inventory probe"; a following bare `hermes pause` → "⏸️  Still paused" with no reason line, and the sentinel's `reason` becomes null.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `engaged_at` is also refreshed, so the original pause time is lost.
- **Config / env:** `$HERMES_HOME/ESTOP`.
- **Edge cases / guards:** This also means `hermes status`'s pause banner drops its reason after a bare re-pause.
- **Rebuild notes:** merge on re-engage (keep the first `engaged_at` and the existing reason unless a new one is given), or make re-engaging without a reason a no-op.

### setup — docs/help drift on the `telemetry` section  `id: cli-b.setup.docs-drift`
- **Surface:** Docs
- **Where:** `website/docs/reference/cli-commands.md:307-311` documents `hermes setup [model|tts|terminal|gateway|tools|agent]` and its section table lists only `model`, `terminal`, `gateway`, `tools`, `agent`.
- **What it does:** The docs omit two sections that the CLI accepts — `tts` appears in the usage line but not the table, and `telemetry` appears in neither.
- **How it works:** argparse `choices` (`hermes_cli/subcommands/setup.py:27-35`) and `SETUP_SECTIONS` (`hermes_cli/setup.py:2858-2866`) both carry all seven: `model`, `tts`, `terminal`, `gateway`, `tools`, `telemetry`, `agent`. The command's own `--help` string ("Run a specific section: hermes setup model|tts|terminal|gateway|tools|telemetry|agent") is correct; only the docs page is stale.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `hermes setup telemetry` works and is simply undocumented on the reference page.
- **Config / env:** `telemetry.shared_metrics.enabled`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** generate the docs table from `SETUP_SECTIONS` so the two can never drift.

### status --all — accepted but inert  `id: cli-b.status.all-flag-inert`
- **Surface:** CLI
- **Where:** `hermes status --all`; help "Show all details (redacted for sharing)"; docs table "Show all details in a shareable redacted format."
- **What it does:** Parses and exits successfully but changes nothing about the output — the flag is not read.
- **How it works:** `hermes_cli/subcommands/status.py:22-24` registers `--all`, but `hermes_cli/status.py:134` reads only `deep = getattr(args, 'deep', False)`; `args.all` is never consulted anywhere in `status.py` (verified by grep). All redaction happens unconditionally through `redact_key()` → `agent.redact.mask_secret`.
- **Inputs / options:** `--all` (store_true).
- **Outputs / side effects:** identical output with and without the flag.
- **Config / env:** n/a.
- **Edge cases / guards:** Because keys are always masked, the "redacted for sharing" promise is already met by the default output.
- **Rebuild notes:** either wire the flag to an expanded (still-redacted) report or remove it; an inert flag documented in two places is worse than no flag.

## Handoffs

- `hermes model` / `select_provider_and_model()` (`hermes_cli/main.py:3823`) — the full provider picker, credential prompts and model list that `hermes setup model` and Blank Slate Step 1 delegate to; owned by the model/provider shard.
- `_model_flow_nous()` (`hermes_cli/main.py`) — the Nous device-code OAuth + curated model picker + Tool Gateway opt-in reused by `setup --portal`, first-time quick setup and `hermes portal`.
- `hermes portal` (`status`, `open`, `tools`) — the standalone Nous Portal inspector documented at `website/docs/reference/cli-commands.md:340-354`.
- `hermes tools` / `hermes_cli/tools_config.py:tools_command()` — the platform → toolset → provider-key selector that `hermes setup tools` and the Blank Slate walkthrough delegate to; also `CONFIGURABLE_TOOLSETS` and `_pip_install`.
- `hermes gateway setup` per-platform wizards that live in `hermes_cli/gateway.py` (`_all_platforms`, `_platform_status`, `_configure_platform`) and in plugin adapters (`plugins/platforms/slack/adapter.py::interactive_setup`, `plugins/platforms/matrix/adapter.py::interactive_setup`) — already covered by the `cli-b.gateway.setup.*` entries in this shard; the plugin adapter internals belong to the plugins shard.
- `hermes egress setup` / `hermes egress start` — the iron-proxy credential firewall the Docker terminal branch offers to enable (`proxy.enabled`, `proxy.enforce_on_docker`).
- `hermes claw migrate` (and `--dry-run`, `--overwrite`, `--preset minimal`) — the standalone OpenClaw migration command that `_offer_openclaw_migration` points users at.
- `hermes skills opt-in --sync`, `tools.skills_sync.set_bundled_skills_opt_out`, `sync_skills` and the `.no-bundled-skills` marker used by Blank Slate.
- `hermes plugins` and `hermes mcp add` — the real selectors the Blank Slate walkthrough only prints instructions for.
- `hermes doctor` — referenced by the status footer and the setup summary.
- `tools/send_message_tool.py::send_message_tool` and `gateway/channel_directory.py` (`load_directory`, `format_directory_for_display`) — the delivery engine and channel directory behind `hermes send`.
- `hermes_cli/commands.py::COMMAND_REGISTRY` and the gateway slash-command runtime (`gateway/slash_commands.py`) — the source of the 50 Slack slashes; the runtime behaviour of each `/command` belongs to the gateway shard.
- `agent/lsp/{manager,client,servers,install,workspace,reporter,eventlog,range_shift,protocol}.py` — the LSP runtime (spawn, diagnostics delta, idle reaper, workspace gating) behind `hermes lsp`; the `lsp.*` config keys belong to the config shard.
- `agent/credential_pool.py` (selection strategies, `mark_exhausted_and_rotate`, `try_refresh_current`) and `agent/credential_sources.py` (`find_removal_step`) — the pool engine behind `hermes auth` and the xAI proxy adapter.
- `hermes_cli/auth.py` provider login internals: `_nous_device_code_login`, `_codex_device_code_login`, `_xai_oauth_device_code_login`, `_minimax_oauth_login`, `resolve_qwen_runtime_credentials`, `run_hermes_oauth_login_pure`, `resolve_nous_runtime_credentials`, `_read_shared_nous_state` / `_try_import_shared_nous_state`.
- `hermes_cli/telegram_managed_bot.py::auto_setup_telegram_bot_result` — the QR-based managed Telegram bot provisioning used by the setup wizard's "Automatic" path.
- `gateway/platforms/whatsapp_common.py::resolve_whatsapp_bridge_dir` and the Node Baileys bridge (`bridge.js --pair-only`) — the runtime behind `hermes whatsapp`.
- The WhatsApp Cloud webhook endpoints (`/whatsapp/webhook`, `/health` on port 8090) served by the gateway — the wizard only configures them.
- `hermes_cli/curses_ui.py` (`curses_radiolist`, `curses_checklist`, `MenuNavigationEvent`, `set_menu_navigation_handler`) — the menu widget layer the setup navigation model plugs into.
- `hermes_cli/config.py` helpers `get_missing_env_vars`, `get_missing_config_fields`, `check_config_version`, `is_managed`, `managed_error` — the declarative env-var schema that makes `setup --quick` possible.
- `hermes_cli/status.py`'s per-provider status resolvers (`get_nous_auth_status_local`, `get_codex_auth_status`, the Qwen/MiniMax/xAI equivalents) and `hermes_cli/nous_subscription.py::get_nous_subscription_features` — shared with the dashboard.
- `agent/estop.py` consumers: `cron/scheduler.py:tick`, `gateway/kanban_watchers.py`, `gateway/run.py:_handle_message` — where the pause actually takes effect.
- `hermes_cli/subcommands/gateway.py` also builds the `proxy` parser (an organisational quirk worth noting for anyone refactoring the parser modules).
