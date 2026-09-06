# CLI part A — `hermes` root options, chat REPL, model/moa/fallback/worktree/browser/secrets/egress/migrate

This shard inventories the `hermes` executable's root-level options (every flag accepted before a sub-command), the `chat` sub-command and the classic prompt_toolkit REPL it launches (banner, status bar, keybindings, overlays, spinner, tool feed, bang-shell, skins), plus the sub-command families `model`, `moa`, `fallback`, `worktree`, `browser`, `secrets` (bitwarden / onepassword), `egress` (iron-proxy) and `migrate` (xai) with every sub-sub-command and flag.
It deliberately leaves to sibling shards: every other top-level sub-command (gateway, setup, sessions, config, skills, cron, kanban, dashboard, profile, …), the semantic behaviour of individual slash commands (only their CLI-mode availability table is given here), the Node TUI (`ui-tui`) internals, the agent core (`run_agent.py`), tools and toolsets, and provider back-ends (only the picker UI of `hermes model` is documented here).
Evidence: live `--help` dumps in `hermes_inv/cli_help/`, live `hermes --version`, and the source files cited inline (`hermes_cli/_parser.py`, `hermes_cli/main.py`, `cli.py`, `hermes_cli/{oneshot,moa_cmd,moa_config,fallback_cmd,fallback_config,worktree_cmd,worktree_gc,browser_connect,secrets_cli,onepassword_secrets_cli,proxy_cli,migrate,xai_retirement,relaunch,terminal_breadcrumbs,commands,banner,skin_engine,bang_shell,prompt_stash,curses_ui}.py`, `agent/proxy_sources/iron_proxy.py`, `agent/secret_sources/{bitwarden,onepassword}.py`, docs `website/docs/reference/cli-commands.md`, `website/docs/user-guide/cli.md`).

---

## A. The `hermes` entrypoint and root options

### `hermes` executable — argument parsing, fast paths and dispatch  `id: cli-a.entrypoint`
- **Surface:** CLI
- **Where:** Shell command `hermes [global-options] [<command> ...]`. Help header verbatim: `usage: hermes [-h] [--version] [-z PROMPT] [--usage-file PATH] [-m MODEL] [--provider PROVIDER] [--reasoning LEVEL] [-t TOOLSETS] [--resume SESSION] [--no-restore-cwd] [--in DIR] [--continue [SESSION_NAME]] [--worktree] [--accept-hooks] [--skills SKILLS] [--yolo] [--pass-session-id] [--ignore-user-config] [--ignore-rules] [--safe-mode] [--tui] [--cli] [--dev] {chat,model,moa,fallback,worktree,browser,secrets,egress,migrate,gateway,proxy,lsp,setup,whatsapp,whatsapp-cloud,slack,send,login,logout,auth,status,pause,resume,cron,sync,webhook,peer,portal,kanban,project,hooks,doctor,verify,security,approvals,dump,debug,backup,checkpoints,import,import-agent,config,skin,console,pairing,skills,bundles,plugins,curator,pets,journey,learning,memory-graph,memory,tools,computer-use,mcp,sessions,insights,monitoring,claw,update,uninstall,acp,profile,completion,dashboard,serve,desktop,gui,logs,prompt-size} ...`; description `Hermes Agent - AI assistant with tool-calling capabilities`.
- **What it does:** Entry point `hermes_cli.main:main()` (`hermes_cli/main.py:13152`). With no sub-command it starts the interactive chat; with a sub-command it builds argparse sub-parsers and dispatches to the matching `cmd_*` handler. Return codes of handlers become process exit codes.
- **How it works:** Module import side effects run before `main()`: `_apply_profile_override()` (`main.py:521-771`) pre-parses `-p/--profile` and sets `HERMES_HOME`; on Windows `_install_repair.ensure_windows_bin_launchers` re-stages launchers; `load_hermes_dotenv(project_env=PROJECT_ROOT/.env, load_external_secrets=sys.argv[1:2] != ["update"])` loads `~/.hermes/.env` then the checkout `.env` (`main.py:797-800`); an early raw `config.yaml` read bridges `security.redact_secrets` → `HERMES_REDACT_SECRETS` and `network.force_ipv4` (`main.py:809-843`); `hermes_logging.setup_logging(mode="gui"|"cli")` writes `agent.log`/`errors.log` (`main.py:848-862`). `main()` then: sets process title `hermes` (`_set_process_title`), advertises `HERMES_AGENT` env (`_advertise_agent_env`, `main.py:13135`), forces UTF‑8 stdio on Windows, sweeps stale bytecode if the checkout changed (`_sweep_stale_bytecode_if_checkout_changed`), self-heals an interrupted `hermes update` (`_recover_from_interrupted_install`, skipped when `update` is in argv), warns about a pending fleet restart, then tries three fast paths in order — `_try_termux_fast_tui_launch()` (`main.py:12812`), `_try_termux_fast_cli_launch()` (`main.py:12740`), `_try_fast_chat_launch()` (`main.py:12665`) — which parse only the light top-level/chat parser (`hermes_cli/_parser.py:136 build_top_level_parser`) and jump straight to `cmd_chat` when argv is unambiguously a chat launch (no sub-command token, no `--help`, no unknown flags, no `--version`, no container mode, not a TUI launch outside Termux). Otherwise the full parser is built: `build_model_parser`, moa, fallback, worktree, browser, secrets, egress, migrate, then every other family (`main.py:13221-14727`). Before parsing, container mode (`get_container_exec_info()`) forwards ALL argv into the managed NixOS container via `_exec_in_container` (`main.py:14735-14741`); `_coalesce_session_name_args` (`main.py:10940`) joins unquoted multi-word names after `-c/--continue/-r/--resume`; a bpo‑9338 workaround sets `subparsers.required=True` when a known sub-command token is present and retries without it if parsing fails (`main.py:14745-14785`). After parse: `--version` → `cmd_version`; `--yolo` → `HERMES_YOLO_MODE=1` BEFORE `_prepare_agent_startup(args)` (`main.py:12547`, plugin discovery thread + background MCP discovery + shell-hook/outbound-webhook registration, gated to agent-capable commands `{None, chat, acp, rl}` and `cron run|tick`, `gateway run`, `mcp serve`); `-z` → `_run_and_exit_oneshot`; `--resume/--continue` with no command → `cmd_chat`; no command → `cmd_chat`; else `args.func(args)` and `sys.exit(rc)` for non-zero ints (`main.py:14790-14834`). Plugin-registered sub-commands are only discovered when the first positional token is not in `_BUILTIN_SUBCOMMANDS` (`main.py:12405-12490`); `_resolve_deferred_platform_cli_command` materialises a deferred platform plugin whose name matches the token (`main.py:12490`).
- **Inputs / options:** All root options listed in the entries below; sub-commands as listed in the usage line; `-h/--help`. Argv pre-processing accepts `--flag=value` forms; everything after `--` is positional.
- **Outputs / side effects:** Writes `~/.hermes/agent.log`, `errors.log` (or `gui.log` for dashboard/serve/gui/desktop); may create `~/.hermes/` tree; sets env vars `HERMES_HOME`, `HERMES_AGENT`, `HERMES_REDACT_SECRETS`, `HERMES_YOLO_MODE`, `HERMES_SAFE_MODE`, `HERMES_IGNORE_USER_CONFIG`, `HERMES_IGNORE_RULES`, `HERMES_SESSION_SOURCE`, `HERMES_KANBAN_BOARD`.
- **Config / env:** `HERMES_HOME`; `HERMES_DISABLE_FAST_CHAT_LAUNCH=1` (disable fast chat path); `HERMES_TERMUX_DISABLE_FAST_CLI=1`; `HERMES_TUI=1`; `HERMES_TUI_NO_EARLY_DISABLE=1` (skip early mouse-tracking reset); `HERMES_SUPERVISED_CHILD`, `HERMES_S6_SUPERVISED_CHILD`, `HERMES_GATEWAY_EXTERNAL_SUPERVISOR`, `INVOCATION_ID` (profile sticky-override suppression for supervised gateways); `SUDO_USER`; config `display.interface`, `security.redact_secrets`, `network.force_ipv4`, `container.*` (container exec routing).
- **Edge cases / guards:** `_require_tty(name)` (`main.py:490`) aborts interactive commands (`model`, `fallback add`, …) when stdin is not a TTY with `Error: 'hermes <cmd>' requires an interactive terminal.`; handlers returning non-zero ints set the exit code; help/version exit code 0 is re-raised without a second parse (#10230).
- **Rebuild notes:** One argparse tree with a light "top-level + chat" parser reusable for fast paths, pre-argparse profile extraction that sets the home dir env var before any module caches it, env loading before logging, and a dispatch that maps `func` attributes to handlers with int return codes. A better version would generate the parser from a declarative command registry (like `commands.py` does for slash commands) so `--help`, completion, docs and plugin commands share one source of truth, and would lazy-import every family instead of building 70 sub-parsers up front.

### Startup fast paths (fast chat launch, Termux launches, ultrafast --version)  `id: cli-a.startup-fast-paths`
- **Surface:** CLI
- **Where:** Implicit — `hermes`, `hermes chat …`, `hermes -z …`, `hermes --version`, `hermes --tui` (on Termux).
- **What it does:** Skips building ~40 sub-parsers (~140 ms) and heavy imports when the invocation is unambiguously a chat/one-shot/version launch.
- **How it works:** `_try_fast_chat_launch()` (`main.py:12665-12738`): bails on `HERMES_DISABLE_FAST_CHAT_LAUNCH=1`, `-h/--help`, container mode, `_wants_tui_early()` true, first positional not in `{None,"chat"}`, unknown args, `--version`; else sets `HERMES_YOLO_MODE` when `--yolo`, runs `_prepare_agent_startup`, handles `-z` via `_run_and_exit_oneshot`, maps `--resume/--continue` to `chat`, fills chat defaults (`_set_chat_arg_defaults`, `main.py:12650`) and calls `cmd_chat`. `_try_termux_fast_cli_launch()` (`main.py:12740`) additionally sets `compact=True`, `HERMES_DEFER_AGENT_STARTUP=1`, `HERMES_FAST_STARTUP_BANNER=1` for a bare prompt so the phone reaches the prompt before tool discovery. `_try_termux_fast_tui_launch()` (`main.py:12812`) execs the TUI directly. `_try_ultrafast_version()` → `_startup_fast.try_fast_version()` prints version before any config/logging import. `_wants_tui_early()` (`main.py:314`) decides TUI before argparse: `--cli` wins, then `--tui`/`HERMES_TUI=1`, then requires a real TTY on stdin+stdout, then `display.interface: tui` read via a minimal YAML load (`_config_default_interface_early`, `main.py:283`). `_suppress_mouse_residue_early()` (`main.py:352`) writes `ESC[?1003l …` mouse-off sequences to fd 1 on TUI launches.
- **Inputs / options:** n/a (argv shape).
- **Outputs / side effects:** Same as the slow path; only latency differs.
- **Config / env:** `HERMES_DISABLE_FAST_CHAT_LAUNCH`, `HERMES_TERMUX_DISABLE_FAST_CLI`, `HERMES_TUI`, `HERMES_TUI_NO_EARLY_DISABLE`, `HERMES_DEFER_AGENT_STARTUP`, `HERMES_FAST_STARTUP_BANNER`, `HERMES_TERMUX_PREFETCH_UPDATES`, `HERMES_TERMUX_FORCE_SKILLS_SYNC`, config `display.interface`.
- **Edge cases / guards:** Any `SystemExit` from the light parser or unknown flags falls back to the full parser so plugin sub-commands still parse.
- **Rebuild notes:** Detect "definitely chat" from argv before importing anything heavy; keep the light parser byte-identical with the full one for the shared flags. A better version would precompile the full parser spec into a JSON manifest loaded lazily per family.

### `--version` / `-V`  `id: cli-a.opt-version`
- **Surface:** CLI
- **Where:** `hermes --version`, `hermes -V`; help: `Show version and exit`.
- **What it does:** Prints version, install dir, install method, Python and OpenAI SDK versions, and update status, then exits 0.
- **How it works:** Flag defined `hermes_cli/_parser.py:151` (`action="store_true"`). Ultrafast path `_startup_fast.try_fast_version()` prints before imports; otherwise `cmd_version` → `_print_version_info(check_updates=True)` → `_startup_fast.print_fast_version_info` (`hermes_cli/_startup_fast.py:183-230`): line 1 `format_banner_version_label()` (`hermes_cli/banner.py:650`, includes `· upstream <sha>` for git installs), then `Install directory: <root>`, `Install method: <git|pip|managed|nix|docker>` (`detect_install_method`), `Python: <x.y.z>`, `OpenAI SDK: <ver>|Not installed`, then update status via `banner.check_for_updates`. The old `hermes version` sub-command was removed (`main.py:14618-14619`); the `/version` slash command shares this printer.
- **Inputs / options:** none.
- **Outputs / side effects:** Live output observed: `Hermes Agent v0.21.0 (2026.8.31) · upstream 9dd6634c` / `Install directory: …/hermes-agent` / `Install method: git` / `Python: 3.11.15` / `OpenAI SDK: 2.24.0` / `Update available: 5333 commits behind — run 'hermes update'`. Network call to GitHub compare API for the update line (best-effort).
- **Config / env:** `HERMES_HOME` (banner label reads install stamp).
- **Edge cases / guards:** Every lazy block degrades to the plain `Hermes Agent v<ver> (<date>)` line; on Termux `_is_termux_fast_version_argv` short-circuits.
- **Rebuild notes:** Print static lines from stdlib probes first, then lazily add network-derived lines. Better: add `--json` output and a `--no-update-check` switch.

### `--profile <name>` / `-p <name>` (pre-argparse profile selector)  `id: cli-a.opt-profile`
- **Surface:** CLI
- **Where:** `hermes -p <name> …` or `hermes --profile=<name>` anywhere in argv (also after the sub-command, e.g. `hermes chat -p coder`). Not shown in `--help` (documented in `website/docs/reference/cli-commands.md:23`: `Select which Hermes profile to use for this invocation. Overrides the sticky default set by hermes profile use.`).
- **What it does:** Selects an isolated Hermes home (`~/.hermes/profiles/<name>`) for this invocation by setting `HERMES_HOME` before any module import; strips itself from `sys.argv`.
- **How it works:** `_apply_profile_override()` (`main.py:521-771`). Scans argv skipping value-taking flags from `top_level_value_flag_sets()` (`_parser.py:49`); stops at `--` and at `mcp add … --args` passthrough. Accepts `-p X`, `--profile X`, `--profile=X`. Rejects names not matching `^[a-z0-9][a-z0-9_-]{0,63}$` (so pytest's `-p no:xdist` is ignored). If `HERMES_HOME` already points inside a `profiles/` directory and no flag is given → keep it. Otherwise reads sticky `<root>/active_profile` unless running under a gateway supervisor (`HERMES_SUPERVISED_CHILD`, `HERMES_S6_SUPERVISED_CHILD`, `INVOCATION_ID` for `gateway` commands, `HERMES_GATEWAY_EXTERNAL_SUPERVISOR`). Resolves via `hermes_cli.profiles.resolve_profile_env(name)`; for `sudo hermes -p x` falls back to `SUDO_USER`'s `~/.hermes/profiles/<name>`. Listed in `PRE_ARGPARSE_INHERITED_FLAGS` (`_parser.py:22`) so relaunches carry it.
- **Inputs / options:** `-p NAME`, `--profile NAME`, `--profile=NAME`.
- **Outputs / side effects:** Sets `HERMES_HOME`; on unknown profile prints `Error: <exc>` and exits 1; on internal failure prints `Warning: profile override failed (...), using default` and continues.
- **Config / env:** `HERMES_HOME`, `~/.hermes/active_profile`, `SUDO_USER`, supervisor markers above.
- **Edge cases / guards:** Name `default` never resolves to a profile dir; corrupted `active_profile` is ignored.
- **Rebuild notes:** Pre-argparse scan is required because modules cache the home path at import. Better: make home resolution lazy everywhere so the flag can live in argparse.

### `-z PROMPT` / `--oneshot PROMPT` (scripted one-shot)  `id: cli-a.opt-oneshot`
- **Surface:** CLI
- **Where:** `hermes -z "prompt"`, `hermes --oneshot "prompt"`; help verbatim: `One-shot mode: send a single prompt and print ONLY the final response text to stdout. No banner, no spinner, no tool previews, no session_id line. Tools, memory, rules, and AGENTS.md in the CWD are loaded as normal; approvals are auto-bypassed. Intended for scripts / pipes.`
- **What it does:** Runs one agent turn and prints only the final assistant text to stdout; everything else is silenced.
- **How it works:** Flag `_parser.py:155` (`metavar="PROMPT"`). Dispatch `main.py:14806-14815` → `_run_and_exit_oneshot` (`main.py:177`) → `hermes_cli.oneshot.run_oneshot` (`hermes_cli/oneshot.py:218`). `run_oneshot`: `logging.disable(CRITICAL)`; rejects `--provider` without `--model`/`HERMES_INFERENCE_MODEL` (exit 2, message `hermes -z: --provider requires --model (or HERMES_INFERENCE_MODEL). …`); validates `--toolsets` via `_validate_explicit_toolsets` (built-in toolsets, then plugin toolsets after `discover_plugins()`, then enabled `mcp_servers` names; `all`/`*` enables everything; unknown names are ignored with `hermes -z: ignoring unknown --toolsets entries: …`; disabled MCP servers reported; no valid names → exit 2); sets `HERMES_YOLO_MODE=1` and `HERMES_ACCEPT_HOOKS=1`; `declare_stateless_channel()` so `delegate_task` runs inline; redirects stdout+stderr to `/dev/null` around `_run_agent`. `_run_agent` (`oneshot.py:352`): resolves model = arg → `HERMES_INFERENCE_MODEL` → config `model.default`; provider = arg → (if model explicit) `model_aliases` DIRECT_ALIASES via `model_switch._ensure_direct_aliases`/`direct_alias_runtime_request` → `detect_provider_for_model` → config; `resolve_runtime_provider(...)`; toolsets = explicit or `sorted(_get_platform_tools(cfg,"cli"))`; `ensure_mcp_discovery_before_agent_build(single_query=True)` (15 s bound); preloaded skills via `agent.skill_commands.build_preloaded_skills_prompt` (unknown skill with none loaded → `ValueError`); opens `SessionDB()`; builds `AIAgent(... quiet_mode=True, platform="cli", fallback_model=get_fallback_chain(cfg), ephemeral_system_prompt=skills_prompt, clarify_callback=_oneshot_clarify_callback)`; `agent.run_conversation(prompt)`; cleanup waits for pending background completions, `shutdown_memory_provider`, `agent.close()`, `session_db.close()`. Output is surrogate-sanitised and written with a trailing newline. Exit codes: 0 ok; 1 agent failure (`hermes -z: agent failed: …` on real stderr) or no final text (`hermes -z: no final response was produced; treating the run as failed.`); 2 for failed/partial result with empty text or validation errors; 130 on Ctrl‑C. `_exit_after_oneshot` (`main.py:106`) flushes, `logging.shutdown()`, then `os._exit(rc)` to dodge native finalizer SIGABRT; `_cleanup_oneshot_runtime` (`main.py:138`) kills terminal environments, interrupts async delegations, closes browsers, shuts MCP servers and cached aux clients.
- **Inputs / options:** `PROMPT` (positional value of the flag; stdin is NOT read as prompt); combinable with `-m`, `--provider`, `-t`, `-s`, `--usage-file`, `-p`, `--yolo` (implied), `--accept-hooks` (implied), `--worktree` (see `cli.md` example `hermes -w -z "Fix issue #123"` — note: `-w` only affects the chat path; `-z` does not create a worktree in `run_oneshot`).
- **Outputs / side effects:** stdout = final response only; session persisted in `~/.hermes/state.db` (source `cli`); optional usage JSON.
- **Config / env:** `HERMES_INFERENCE_MODEL`, `HERMES_INFERENCE_PROVIDER`, `HERMES_YOLO_MODE`, `HERMES_ACCEPT_HOOKS`; config `model.*`, `fallback_providers`, `mcp_servers`, `toolsets`/platform tool config, `model_aliases`.
- **Edge cases / guards:** Clarify tool answers synthetically (`[oneshot mode: no user available. …]`); sudo prompts are unavailable (`HERMES_INTERACTIVE` unset); expensive-model/data-policy guard runs before (see `cli-a.startup-expensive-model-guard`) and refuses in non-interactive mode.
- **Rebuild notes:** Build the same agent as chat, silence all streams, print the final text, hard-exit. Better: stream to stdout with `--stream`, accept prompt from stdin when `-`/absent, and emit structured JSON (`--json`) including tool trace.

### `--usage-file PATH`  `id: cli-a.opt-usage-file`
- **Surface:** CLI
- **Where:** `hermes -z "…" --usage-file /path/report.json`; help verbatim: `One-shot mode only: after the run, write a JSON usage report (estimated cost, token counts, model, api_calls) to PATH. The report is written even when the run fails, so pipelines can always account for spend. No effect outside -z/--oneshot.`
- **What it does:** Writes a machine-readable spend/usage report after a `-z` run.
- **How it works:** `_parser.py:167`; consumed by `oneshot._write_usage_file` (`oneshot.py:175-215`). Report keys: `estimated_cost_usd`, `cost_status`, `cost_source`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `total_tokens`, `api_calls`, `model`, `provider`, `session_id`, `completed`, `failed` (bool, true when a failure was captured), `service_tier`, plus `failure` (string) when present. Written with `indent=2` + newline; parent dirs created; `~` expanded; never raises.
- **Inputs / options:** `PATH`.
- **Outputs / side effects:** File at PATH (overwritten).
- **Config / env:** none.
- **Edge cases / guards:** Ignored outside `-z`; written even on KeyboardInterrupt/SystemExit (`failure=repr(exc)`).
- **Rebuild notes:** Serialize the run result dict after the turn, also on failure. Better: append-mode ledger and per-tool-call breakdown.

### `-m MODEL` / `--model MODEL` (root)  `id: cli-a.opt-model`
- **Surface:** CLI
- **Where:** `hermes -m anthropic/claude-sonnet-4.6 …`; help: `Model override for this invocation (e.g. anthropic/claude-sonnet-4.6). Applies to -z/--oneshot and --tui. Also settable via HERMES_INFERENCE_MODEL env var.`
- **What it does:** Overrides the model for this process only (no config write).
- **How it works:** `_parser.py:184`, registered via `_inherited_flag` (carried over on relaunch). Chat path: `cmd_chat` passes `model` into `cli.main(...)` → `HermesCLI(model=...)`; TUI path: `_launch_tui` exports `HERMES_MODEL` and `HERMES_INFERENCE_MODEL` (`main.py:2975-2977`); one-shot path: see `cli-a.opt-oneshot`. The chat sub-parser redeclares `-m/--model` with `default=argparse.SUPPRESS` (`_parser.py:402`) so `hermes -m foo chat` is not clobbered. Model names may be aliases (`model_aliases:` in config, `hermes_cli/model_switch.py DIRECT_ALIASES`) or bare names auto-routed with `detect_provider_for_model`.
- **Inputs / options:** `MODEL` string.
- **Outputs / side effects:** Triggers the startup cost/data-policy guard (`cli-a.startup-expensive-model-guard`).
- **Config / env:** `HERMES_INFERENCE_MODEL` (fallback when flag absent), `HERMES_MODEL` (TUI handoff), config `model.default`, `model_aliases`.
- **Edge cases / guards:** With `--provider` absent, provider is auto-detected only when the model was explicit.
- **Rebuild notes:** Thread a nullable model override through agent construction; never persist. Better: validate against the provider catalog before starting and suggest close matches.

### `--provider PROVIDER` (root)  `id: cli-a.opt-provider`
- **Surface:** CLI
- **Where:** `hermes --provider openrouter …`; help: `Provider override for this invocation (e.g. openrouter, anthropic). Applies to -z/--oneshot and --tui. The persistent provider lives in config.yaml under model.provider — use hermes setup or edit the file to change it.`
- **What it does:** Forces the inference provider for this process.
- **How it works:** `_parser.py:193` (`_inherited_flag`, no `choices=` so user-defined `providers:` names are valid). Chat → `HermesCLI(provider=...)`; TUI → env `HERMES_TUI_PROVIDER` + `HERMES_INFERENCE_PROVIDER` (`main.py:2978-2980`); one-shot → `resolve_runtime_provider(requested=...)`. Accepted values (docs `cli-commands.md:118`): `auto`, `openrouter`, `nous`, `openai-codex`, `copilot-acp`, `copilot`, `anthropic`, `gemini`, `huggingface`, `novita` (aliases `novita-ai`, `novitaai`), `openai-api`, `zai`, `kimi-coding`, `kimi-coding-cn`, `minimax`, `minimax-cn`, `minimax-oauth`, `kilocode`, `xiaomi`, `arcee`, `gmi`, `upstage` (alias `solar`), `alibaba`, `alibaba-cn`, `alibaba-coding-plan` (alias `alibaba_coding`), `alibaba-coding-plan-cn`, `alibaba-token-plan`, `alibaba-token-plan-cn`, `deepseek`, `nvidia`, `ollama-cloud`, `xai` (alias `grok`), `xai-oauth` (alias `grok-oauth`), `qwen-oauth`, `bedrock`, `opencode-zen`, `opencode-go`, `opencode-free` (aliases `free`, `opencode_free`), `commandcode`, `commandcode-anthropic`, `ai-gateway`, `azure-foundry`, `lmstudio`, `stepfun`, `tencent-tokenhub` (aliases `tencent`, `tokenhub`), `router` (aliases `ramp-router`, `ramp`), `nebius-token-factory` (aliases `nebius`, `nebius-tf`, `tokenfactory`), `tencent-tokenplan` (aliases `tokenplan`, `tencent-lkeap`), plus `custom`, `moa`, `fireworks`, `vertex`, and any key under `providers:`/`custom_providers:`. Full alias map: `hermes_cli/models.py:1478-1580 _PROVIDER_ALIASES`.
- **Inputs / options:** `PROVIDER` string.
- **Outputs / side effects:** None persistent.
- **Config / env:** `HERMES_INFERENCE_PROVIDER`, `HERMES_TUI_PROVIDER`, config `model.provider`, `providers`, `custom_providers`.
- **Edge cases / guards:** In `-z` mode `--provider` without a model is rejected (exit 2). Unknown provider → runtime error from `resolve_runtime_provider`.
- **Rebuild notes:** Resolve provider → (base_url, api_key, api_mode, credential pool) through a single resolver used by every surface. Better: print the resolved endpoint in verbose mode.

### `--reasoning LEVEL` (root)  `id: cli-a.opt-reasoning`
- **Surface:** CLI
- **Where:** `hermes --reasoning high …`; help: `Reasoning effort for this invocation: none, minimal, low, medium, high, xhigh, max, or ultra. Overrides agent.reasoning_effort in config.yaml for this run only; the persistent level lives there (or per-model under agent.reasoning_overrides).`
- **What it does:** Sets the per-run reasoning effort sent to the model.
- **How it works:** `_parser.py:203` (`_inherited_flag`, `metavar="LEVEL"`). Chat: `cmd_chat` kwargs `reasoning` → `HermesCLI(reasoning=...)` (wins over config; parsed by `cli._parse_reasoning_config`, `cli.py:391`). Not forwarded by `_launch_tui` (TUI reads config) and not used by `run_oneshot` (root `--reasoning` is accepted but `_run_and_exit_oneshot` does not pass it — see unresolved).
- **Inputs / options:** one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`.
- **Outputs / side effects:** None persistent (same levels as `/reasoning`).
- **Config / env:** `agent.reasoning_effort`, `agent.reasoning_overrides`.
- **Edge cases / guards:** Value is not validated by argparse (no `choices`).
- **Rebuild notes:** Map level → provider-specific reasoning parameter at request time. Better: validate and show the provider's supported set.

### `-t TOOLSETS` / `--toolsets TOOLSETS` (root)  `id: cli-a.opt-toolsets`
- **Surface:** CLI
- **Where:** `hermes -t web,terminal …`; help: `Comma-separated toolsets to enable for this invocation. Applies to -z/--oneshot and --tui.`
- **What it does:** Restricts/extends the enabled toolsets for this process.
- **How it works:** `_parser.py:215`. Chat: `cli.main(toolsets=…)` splits on commas (`cli.py:21770-21790`); when absent, `agent.coding_context.coding_selection(platform="cli")` may collapse to the coding toolset in a code workspace, else `sorted(_get_platform_tools(CLI_CONFIG,"cli"))`. TUI: `_normalize_tui_toolsets` → `HERMES_TUI_TOOLSETS` (`main.py:2771,2981`). One-shot: validated as described in `cli-a.opt-oneshot`. Toolset names: 59 toolsets in `toolsets.py` (see sibling shard), MCP server names, `all`/`*`.
- **Inputs / options:** comma-separated names.
- **Outputs / side effects:** none persistent.
- **Config / env:** `HERMES_TUI_TOOLSETS`; config `toolsets` (default `["hermes-cli"]`), `platform_toolsets.cli`, `mcp_servers`.
- **Edge cases / guards:** Unknown names are ignored in `-z` (warning) but may error in chat (`cli.py` validate_toolset).
- **Rebuild notes:** Resolve names → tool definitions via a registry with includes. Better: `--tools` for individual tools and `--no-toolsets` negation.

### `--resume SESSION` / `-r SESSION` (root)  `id: cli-a.opt-resume`
- **Surface:** CLI
- **Where:** `hermes --resume 20260225_143052_a1b2c3`, `hermes -r "refactoring auth"`, `hermes --resume latest`, `hermes --resume @claude`, `hermes --resume @codex`; help: `Resume a previous session by ID or title, or pass 'latest' for the most recent session (workspace-scoped, like -c with no name)`.
- **What it does:** Reopens a stored session (history from SQLite) in the chat REPL/TUI.
- **How it works:** `_parser.py:220`. Root form with no command sets `args.command="chat"` (`main.py:14818`). In `cmd_chat` (`main.py:3163`): (1) `latest` (case-insensitive) → `_resolve_last_session(source="tui"|"cli")` (`main.py:1651`: workspace-scoped MRU via `SessionDB.search_sessions(source, limit=1, workspace_key=git toplevel|cwd)`, then global MRU; TUI falls back to `cli` source); failure prints `No previous CLI session found to resume.` + `Use 'hermes sessions list' to see available sessions.` exit 1. (2) `@claude`/`@codex` → `foreign_sessions.pick_foreign_session` + `import_foreign_session`, prints `✓ Imported as <id> — resuming it now.` and `(later: hermes --resume <id>)`. (3) otherwise `_resolve_session_by_name_or_id` (`main.py:1794`): exact ID via `SessionDB.get_session`, else title via `resolve_session_by_title` (auto-latest in lineage), then `get_compression_tip` projects to the live continuation. (4) cwd restore: unless `--no-restore-cwd`/`--worktree`/`--in`, `os.chdir(session.cwd)` printing `↪ restored workspace dir: <dir>` or `⚠ session's recorded dir is gone (<dir>); staying in <cwd>`. Unresolved values are passed through so `_init_agent` reports "Session not found". `_coalesce_session_name_args` joins unquoted multi-word titles. TUI receives `HERMES_TUI_RESUME`.
- **Inputs / options:** `SESSION` = session id (`YYYYMMDD_HHMMSS_xxxxxx`), title, `latest`, `@claude`, `@codex`.
- **Outputs / side effects:** Changes cwd; may import a foreign session into `state.db`.
- **Config / env:** `HERMES_TUI_RESUME` (internal), `~/.hermes/state.db`.
- **Edge cases / guards:** Keyword `latest` beats a session literally titled "latest" (reach it via id or `-c latest`).
- **Rebuild notes:** Session store with id/title/lineage/workspace columns; resolution order id → title → tip. Better: fuzzy title search and a `--list` preview.

### `--no-restore-cwd`  `id: cli-a.opt-no-restore-cwd`
- **Surface:** CLI
- **Where:** `hermes --resume <id> --no-restore-cwd`; help: `Don't cd into a resumed session's recorded working directory.`
- **What it does:** Keeps the current directory when resuming instead of `chdir` into the session's recorded `cwd`.
- **How it works:** `_parser.py:230`; checked in `cmd_chat` (`main.py:3254-3277`); auto-set by `--in` (`main.py:3196`).
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** Implied under `--worktree`.
- **Rebuild notes:** Trivial boolean around the restore step.

### `--in DIR`  `id: cli-a.opt-in-dir`
- **Surface:** CLI
- **Where:** `hermes --in ./project`, `hermes --tui --resume latest --in ./dir`; help: `Change into DIR before starting or resuming. Combined with '--resume latest' or -c, the most recent session for DIR's workspace is picked, and the session stays in DIR (skips the recorded-cwd restore).`
- **What it does:** `chdir` into DIR before any session resolution.
- **How it works:** `_parser.py:236` (`dest="in_dir"`). `cmd_chat` (`main.py:3169-3197`): converts MSYS/Cygwin/WSL paths via `tools.environments.local._msys_to_windows_path`, `expanduser`, `abspath`; errors `Error: --in directory not found: <dir>` / `Error: cannot enter --in directory <dir>: <e>` exit 1; sets `args.no_restore_cwd=True`.
- **Inputs / options:** `DIR`.
- **Outputs / side effects:** Process cwd changes (affects AGENTS.md discovery, workspace key, tool cwd).
- **Config / env:** n/a.
- **Edge cases / guards:** Runs before `latest`/`-c` lookups so workspace scoping keys off DIR.
- **Rebuild notes:** chdir + suppress restore. Better: accept `--in` for every sub-command.

### `--continue [SESSION_NAME]` / `-c [SESSION_NAME]`  `id: cli-a.opt-continue`
- **Surface:** CLI
- **Where:** `hermes -c`, `hermes -c "my project"`, `hermes -c Pokemon Agent Dev` (unquoted words are merged); help: `Resume a session by name, or the most recent if no name given`.
- **What it does:** Bare `-c` continues THIS terminal's last session (breadcrumb) else the workspace MRU; `-c NAME` resumes by title/id.
- **How it works:** `_parser.py:248` (`nargs="?"`, `const=True`, `dest="continue_last"`). `_resolve_continue_arg` (`main.py:1881-1960`): string → `_resolve_session_by_name_or_id`; miss → stderr `No session found matching '<name>'.` + `Use 'hermes sessions list' to see available sessions, or pass --create-if-missing to start a new session with that title.` exit 1; with `--create-if-missing` → `_create_titled_session` (`main.py:1840`: id `YYYYMMDD_HHMMSS_<6hex>`, `create_session(source="cli")`, `set_session_title`). Bare → `terminal_breadcrumbs.resolve_breadcrumb_session()` (`hermes_cli/terminal_breadcrumbs.py:150`; breadcrumb file `$HERMES_HOME/terminal-sessions/<terminal-id>` with `{"session_id","cwd","ts"}`, terminal id from tty path or `ZELLIJ_PANE_ID`/`TMUX_PANE`/`KITTY_WINDOW_ID`/`WEZTERM_PANE`/`TERM_SESSION_ID`/`WT_SESSION`, stale after 30 days, gated by `session.terminal_continue` default true) else `_resolve_last_session`. `_coalesce_session_name_args` (`main.py:10940`) merges tokens after `-c/--continue/-r/--resume` until a flag or known sub-command.
- **Inputs / options:** optional `SESSION_NAME`; pairs with `--create-if-missing` (chat only).
- **Outputs / side effects:** May create a titled empty session.
- **Config / env:** `session.terminal_continue`; `~/.hermes/terminal-sessions/`.
- **Edge cases / guards:** `--create-if-missing` with bare `-c` prints `--create-if-missing requires a session name: \`-c <name> --create-if-missing\`` on stderr and continues; on `sudo`/pipes with no terminal id, breadcrumbs are skipped.
- **Rebuild notes:** Per-terminal breadcrumb file keyed by tty/multiplexer pane + MRU fallback. Better: keep a small ring of recent sessions per terminal and offer a picker.

### `--worktree` / `-w`  `id: cli-a.opt-worktree`
- **Surface:** CLI
- **Where:** `hermes -w`, `hermes --worktree chat -q "…"`; help: `Run in an isolated git worktree (for parallel agents)`.
- **What it does:** Creates a disposable git worktree + branch under `<repo>/.worktrees/` and runs the session inside it; cleans it up on exit unless it holds unpushed commits.
- **How it works:** `_parser.py:258`. Chat path `cli.main(worktree=True)` (`cli.py:21700-21760`): `use_worktree = worktree or w or CLI_CONFIG["worktree"]`; starts a `tool-prewarm` thread and a `worktree-setup` thread calling `_setup_worktree(sync_base=CLI_CONFIG.get("worktree_sync", True))` (`cli.py:1819-2042`): requires git repo (`✗ --worktree requires being inside a git repository.`), name `hermes-<8hex>` (or sanitized `/worktree new <name>`), branch `hermes/<name>`, ensures `.worktrees/` in `.gitignore`, base ref from `_resolve_worktree_base` (fresh remote tip) or `HEAD` when `worktree_sync: false`, runs `git -c checkout.workers=8 -c checkout.thresholdForParallelism=100 worktree add <path> -b <branch> <base>` (120 s timeout, retry from HEAD, `_cleanup_failed_worktree_add` on failure), copies `.worktreeinclude` entries (files copied, dirs symlinked, Windows copytree fallback, path-traversal guarded), locks the tree with `git worktree lock --reason "hermes pid=<pid>"`, prints `✓ Worktree created: <path>` / `Branch: …` / `Base: …`. Joined after `HermesCLI` construction; failure aborts the session. Sets `TERMINAL_CWD`, registers `atexit(_cleanup_worktree)`, starts background `_prune_stale_worktrees` + `_maintain_pack_health`. Appends a system note to the prompt: `[System note: You are working in an isolated git worktree at <path>. Your branch is \`<branch>\`. Changes here do not affect the main working tree or other agents. Remember to commit and push your changes, and create a PR if appropriate. The original repo is at <repo_root>.]`. `_cleanup_worktree` (`cli.py:2538`): keeps trees with unpushed commits (`⚠ Worktree has unpushed commits, keeping: …` / shallow-clone variant), else unlock → `git worktree remove --force` → `git branch -D` → `✓ Worktree cleaned up: …`. TUI path: `_launch_tui` runs `_prune_stale_worktrees`, `_setup_worktree`, exports `HERMES_CWD`/`TERMINAL_CWD` (`main.py:2934-2967`).
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** Creates `<repo>/.worktrees/<name>`, branch `hermes/<name>`, `.gitignore` edit, git lock; startup pruner may delete old trees/branches; escalation notice when `.worktrees/` > 10 trees or 5 GB (docs `cli.md:88`).
- **Config / env:** config `worktree` (bool, default false), `worktree_sync` (default true); env `TERMINAL_CWD`, `HERMES_CWD`; file `.worktreeinclude`.
- **Edge cases / guards:** Kanban `t_<hex>` trees are never touched; shallow clones are deepened bloblessly by the pruner; `--no-restore-cwd` implied.
- **Rebuild notes:** `git worktree add` + branch + lock + atexit removal gated on unpushed-commit detection. Better: copy-on-write filesystem snapshots and a `--keep` flag.

### `--accept-hooks`  `id: cli-a.opt-accept-hooks`
- **Surface:** CLI
- **Where:** `hermes --accept-hooks …`; help: `Auto-approve any unseen shell hooks declared in config.yaml without a TTY prompt. Equivalent to HERMES_ACCEPT_HOOKS=1 or hooks_auto_accept: true in config.yaml. Use on CI / headless runs that can't prompt.`
- **What it does:** Skips the consent prompt for newly seen shell hooks (`hooks:` in config).
- **How it works:** `_parser.py:266` (`_inherited_flag`). `_prepare_agent_startup` passes `accept_hooks` to `agent.shell_hooks.register_from_config(cfg, accept_hooks=...)` (`main.py:12620-12626`); TUI exports `HERMES_ACCEPT_HOOKS=1`; Termux fast path likewise.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** Unseen hooks are recorded as accepted (hook store managed by `hermes hooks` — sibling shard).
- **Config / env:** `HERMES_ACCEPT_HOOKS`, config `hooks_auto_accept` (default false).
- **Edge cases / guards:** Does not bypass dangerous-command approvals (that is `--yolo`).
- **Rebuild notes:** Boolean threaded into hook registration. Better: accept a hook allowlist by hash.

### `--skills SKILLS` / `-s SKILLS`  `id: cli-a.opt-skills`
- **Surface:** CLI
- **Where:** `hermes -s hermes-agent-dev,github-auth`, `hermes -s a -s b`; help: `Preload one or more skills for the session (repeat flag or comma-separate)`.
- **What it does:** Loads the named skills' SKILL.md content into the system prompt before the first turn.
- **How it works:** `_parser.py:278` (`action="append"`, `_inherited_flag`). Chat: `cli.main(skills=…)` → `_parse_skills_argument` → background thread `build_preloaded_skills_prompt(parsed_skills, task_id=session_id)` joined by `finalize_preloaded_skills()` (`cli.py:8870`) before agent creation; partial success logs missing skills. TUI: `HERMES_TUI_SKILLS` comma list. One-shot: `oneshot._build_preloaded_skills_prompt` (all missing → `ValueError: Unknown skill(s): …`).
- **Inputs / options:** repeated or comma-separated skill names from `~/.hermes/skills/`.
- **Outputs / side effects:** none persistent.
- **Config / env:** `HERMES_TUI_SKILLS`.
- **Edge cases / guards:** Skipped when `--ignore-rules`/`--safe-mode`? — no: the flag says rules injection skips "preloaded skills" coming from user config; explicit `-s` is still loaded through `ephemeral_system_prompt` (see unresolved).
- **Rebuild notes:** Read SKILL.md files, wrap, prepend to system prompt. Better: report token cost per skill at load.

### `--yolo`  `id: cli-a.opt-yolo`
- **Surface:** CLI
- **Where:** `hermes --yolo …`; help: `Bypass all dangerous command approval prompts (use at your own risk)`.
- **What it does:** Disables the dangerous-command approval gate for the whole process.
- **How it works:** `_parser.py:286`. `main()` sets `os.environ["HERMES_YOLO_MODE"]="1"` before `_prepare_agent_startup` because `tools.approval` freezes `_YOLO_MODE_FROZEN` at import (PR #7994) (`main.py:14790-14797`, `12556-12557`, `3384-3385`). The REPL shows `⚠ YOLO mode — all approval prompts bypassed` in the banner and `⚠ YOLO` in the status bar; `/yolo` toggles per session and `_restore_session_yolo` persists it per session (`cli.py:9178`).
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** env `HERMES_YOLO_MODE=1`.
- **Config / env:** `HERMES_YOLO_MODE`.
- **Edge cases / guards:** Does NOT bypass the expensive-model/data-policy confirmation (`main.py:1206-1210`).
- **Rebuild notes:** Global env flag frozen at tool import. Better: scoped allowlists instead of a global bypass.

### `--pass-session-id`  `id: cli-a.opt-pass-session-id`
- **Surface:** CLI
- **Where:** `hermes --pass-session-id`; help: `Include the session ID in the agent's system prompt`.
- **What it does:** Adds the current session id to the system prompt so the model can reference/store it.
- **How it works:** `_parser.py:293`; `HermesCLI(pass_session_id=True)`; TUI `HERMES_TUI_PASS_SESSION_ID=1`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** prompt text only.
- **Config / env:** `HERMES_TUI_PASS_SESSION_ID`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Append `Session ID: …` to the system prompt.

### `--ignore-user-config`  `id: cli-a.opt-ignore-user-config`
- **Surface:** CLI
- **Where:** `hermes --ignore-user-config`; help: `Ignore ~/.hermes/config.yaml and fall back to built-in defaults (credentials in .env are still loaded)`.
- **What it does:** Runs with built-in defaults, ignoring the user's config.yaml.
- **How it works:** `_parser.py:300`; `cmd_chat` sets `HERMES_IGNORE_USER_CONFIG=1` before importing `cli` (`main.py:3391-3393`); `cli.load_cli_config` (`cli.py:414-440`) then uses the project `cli-config.yaml` fallback; `hermes_cli.config.load_config` honours the same env var.
- **Inputs / options:** boolean.
- **Outputs / side effects:** none persistent.
- **Config / env:** `HERMES_IGNORE_USER_CONFIG`.
- **Edge cases / guards:** `.env` credentials still load.
- **Rebuild notes:** Env-gated branch in the config loader.

### `--ignore-rules`  `id: cli-a.opt-ignore-rules`
- **Surface:** CLI
- **Where:** `hermes --ignore-rules`; help: `Skip auto-injection of AGENTS.md, SOUL.md, .cursorrules, memory, and preloaded skills`.
- **What it does:** Starts the agent without project rule files, memory entries or config-preloaded skills.
- **How it works:** `_parser.py:307`; `cmd_chat` sets `HERMES_IGNORE_RULES=1` and passes `ignore_rules=True` → `AIAgent(skip_context_files=True, skip_memory=True)` (`main.py:3395-3399`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** none.
- **Config / env:** `HERMES_IGNORE_RULES`.
- **Edge cases / guards:** Implied by `--safe-mode`.
- **Rebuild notes:** Two booleans on agent construction.

### `--safe-mode`  `id: cli-a.opt-safe-mode`
- **Surface:** CLI
- **Where:** `hermes --safe-mode`; help: `Troubleshooting mode: disable ALL customizations — user config, AGENTS.md/memory injection, plugins, and MCP servers (implies --ignore-user-config and --ignore-rules)`.
- **What it does:** Isolates a bug from the user's setup.
- **How it works:** `_parser.py:314`; `_apply_safe_mode` (`main.py:12642`) sets `HERMES_SAFE_MODE=1`, `HERMES_IGNORE_USER_CONFIG=1`, `HERMES_IGNORE_RULES=1`; plugin and MCP discovery consult `HERMES_SAFE_MODE`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** none.
- **Config / env:** `HERMES_SAFE_MODE`.
- **Edge cases / guards:** Shell hooks are also disabled per docs (`cli-commands.md:136`).
- **Rebuild notes:** One env var checked by every extension loader.

### `--tui`  `id: cli-a.opt-tui`
- **Surface:** CLI
- **Where:** `hermes --tui`; help: `Launch the modern TUI instead of the classic REPL`.
- **What it does:** Replaces the prompt_toolkit REPL with the Node/Ink TUI (`ui-tui`).
- **How it works:** `_parser.py:321` (`_inherited_flag`). `_resolve_use_tui(args)` (`main.py:3120-3160`) precedence: `--cli` → classic; `--tui` → TUI; no TTY → classic; `HERMES_TUI=1` → TUI; `display.interface` == `tui` → TUI; default classic. `cmd_chat` then calls `_launch_tui(...)` (`main.py:2899-3077`): builds env via `build_subprocess_env(scrub_secrets=False, inherit_profile_home=True)` + `apply_terminal_config_to_env`; temp file `hermes-tui-active-session-*.json` in `HERMES_TUI_ACTIVE_SESSION_FILE`; `NODE_ENV` production/development; exports `HERMES_MODEL`/`HERMES_INFERENCE_MODEL`, `HERMES_TUI_PROVIDER`/`HERMES_INFERENCE_PROVIDER`, `HERMES_TUI_TOOLSETS`, `HERMES_TUI_SKILLS`, `HERMES_TUI_QUERY`, `HERMES_TUI_IMAGE`, `HERMES_TUI_CHECKPOINTS`, `HERMES_TUI_PASS_SESSION_ID`, `HERMES_TUI_MAX_TURNS`, `HERMES_TUI_TOOL_PROGRESS` (`verbose`|`off`), `HERMES_ACCEPT_HOOKS`, `HERMES_TUI_RESUME`; appends `--max-old-space-size=<mb>` to `NODE_OPTIONS` (`_resolve_tui_heap_mb`, cgroup-aware, default 8192); `subprocess.call(argv, cwd)` with argv from `_make_tui_argv` (`main.py:2555`; Node from `_ensure_tui_node`, workspace from `_ensure_tui_workspace`/`_find_bundled_tui`); exit 0/130 → `_print_tui_exit_summary`; exit 42 → `relaunch(["update"], preserve_inherited=False)` printing `⚕ Launching update...`; worktree created/cleaned as in `-w`.
- **Inputs / options:** boolean; combines with `--dev`, `--resume`, `-m`, `--provider`, `-t`, `-s`, `-q`, `--image`, `-w`, `--checkpoints`, `--pass-session-id`, `--max-turns`, `--accept-hooks`, `-v`, `-Q`.
- **Outputs / side effects:** Spawns Node; may `npm install`/build `ui-tui` (`_tui_need_npm_install`, `_tui_need_rebuild`, `HERMES_TUI_FORCE_BUILD`).
- **Config / env:** `HERMES_TUI`, `HERMES_TUI_DIR`, `HERMES_NODE`, `HERMES_SKIP_NODE_BOOTSTRAP`, `HERMES_TUI_FORCE_BUILD`, `NODE_OPTIONS`; config `display.interface`, `display.tui_auto_resume_recent`.
- **Edge cases / guards:** Ambient TUI preference never applies without a TTY (kanban/cron workers); explicit `--tui` still reaches the TUI's own no-TTY bail-out.
- **Rebuild notes:** Launcher that serialises CLI flags into env vars for a child UI process and relays exit codes. Better: pass a single JSON handoff file instead of ~15 env vars.

### `--cli`  `id: cli-a.opt-cli`
- **Surface:** CLI
- **Where:** `hermes --cli`; help: `Force the classic prompt_toolkit REPL (overrides display.interface=tui)`.
- **What it does:** Forces the classic REPL for one invocation.
- **How it works:** `_parser.py:328`; highest precedence in `_wants_tui_early` and `_resolve_use_tui`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** none.
- **Config / env:** overrides `display.interface`, `HERMES_TUI`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Boolean precedence check.

### `--dev`  `id: cli-a.opt-dev`
- **Surface:** CLI
- **Where:** `hermes --tui --dev`; help: `With --tui: run TypeScript sources via tsx (skip dist build)`.
- **What it does:** Runs `ui-tui` sources through `tsx` instead of the built `dist` bundle (for TUI contributors).
- **How it works:** `_parser.py:335` (`dest="tui_dev"`); `_launch_tui(tui_dev=True)` sets `NODE_ENV=development` and `_make_tui_argv(tui_dir, tui_dev)` picks the tsx entry.
- **Inputs / options:** boolean (only meaningful with `--tui`).
- **Outputs / side effects:** none.
- **Config / env:** `HERMES_DEV`.
- **Edge cases / guards:** ignored without `--tui`.
- **Rebuild notes:** Alternate argv for the child process.

### Startup expensive-model / data-policy confirmation  `id: cli-a.startup-expensive-model-guard`
- **Surface:** CLI
- **Where:** Automatic prompt after `-m`/`--provider`: `Use this model for this invocation? [y/N] `.
- **What it does:** Warns (and asks) when an explicit startup model/provider override is expensive or routes to a data-training tier.
- **How it works:** `_confirm_startup_expensive_model_override(args)` (`main.py:1154-1250`) called from `cmd_chat`, `_try_fast_chat_launch`, and before one-shot. Uses `hermes_cli.model_selection_guards.selection_warnings(model, provider, base_url, api_key)` (kinds `cost`, `data_policy`) and `combined_message` (messages joined by blank lines). Interactive: prints message, prompts; anything but `y`/`yes` → `Model override cancelled.` exit 1. Non-interactive: prints message; `security.allow_data_training_tiers_noninteractive: true` acknowledges data-policy warnings only (`Proceeding in non-interactive mode because security.allow_data_training_tiers_noninteractive is true.`); remaining warnings → `Refusing this startup model override in non-interactive mode. Run interactively and confirm if you intend to use it.` exit 1.
- **Inputs / options:** y/N answer.
- **Outputs / side effects:** none.
- **Config / env:** `security.allow_data_training_tiers_noninteractive` (default false).
- **Edge cases / guards:** Independent of `--yolo`/`--accept-hooks`.
- **Rebuild notes:** Guard registry keyed by model id/provider returning typed warnings. Better: remember confirmations per model for N days.

### First-run provider guard  `id: cli-a.first-run-provider-guard`
- **Surface:** CLI
- **Where:** Automatic when starting chat with no provider configured: prints `It looks like Hermes isn't configured yet -- no API keys or providers found.` / `  Run:  hermes setup` and asks `Run setup now? [Y/n] `.
- **What it does:** Routes an unconfigured install into the setup wizard instead of a chat that cannot work.
- **How it works:** `_has_any_provider_configured()` (`main.py:1028-1152`) checks: provider env vars (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_TOKEN`, `OPENAI_BASE_URL` + every `PROVIDER_REGISTRY` api_key env var), the `.env` file, `~/.hermes/auth.json` active provider login, `model.provider`/`base_url`/`api_key` in config, provider auth fallbacks (e.g. Copilot via `gh`), and Claude Code credentials only when Hermes was explicitly configured. In `cmd_chat` (`main.py:3305-3332`): non-interactive stdin → `print_noninteractive_setup_guidance` exit 1; `Y`/enter → `cmd_setup(args)`; else `You can run 'hermes setup' at any time to configure.` exit 1. The REPL repeats a softer check on a TTY via `_offer_first_run_setup` (`cli.py:18115`).
- **Inputs / options:** Y/n.
- **Outputs / side effects:** May launch the setup wizard (sibling shard `setup`).
- **Config / env:** as listed.
- **Edge cases / guards:** The PROVIDER_REGISTRY sweep may spawn subprocesses (15–20 s) — cheap checks run first.
- **Rebuild notes:** Ordered credential probe. Better: a single cached "configured" stamp invalidated on config/env writes.

### xAI retirement startup warning  `id: cli-a.xai-retirement-warning`
- **Surface:** CLI
- **Where:** stderr at chat start: `⚠ xAI retires N model(s) in your config on May 15, 2026:` followed by one `⚠ <path>: '<model>' → use '<replacement>' …` line per issue, `Migration guide: https://docs.x.ai/developers/migration/may-15-retirement`, `Run 'hermes doctor' for details.`
- **What it does:** Non-blocking notice that config references retired xAI models.
- **How it works:** `cmd_chat` (`main.py:3279-3300`) calls `xai_retirement.find_retired_xai_refs(load_config())` (see `cli-a.migrate-xai`).
- **Inputs / options:** none.
- **Outputs / side effects:** stderr only.
- **Config / env:** `principal.model`, `auxiliary.*.model`, `delegation.model`, `tts.xai.model`, `plugins.image_gen.xai.model`.
- **Edge cases / guards:** never fails startup.
- **Rebuild notes:** Reuse the migrate scanner at startup.

### Relaunch — flags inherited across self re-exec  `id: cli-a.relaunch-inherited-flags`
- **Surface:** CLI
- **Where:** Implicit — after `hermes sessions browse` picks a session, after the setup wizard launches chat, after the TUI requests an update (exit 42).
- **What it does:** Re-executes `hermes` preserving UI-mode and override flags.
- **How it works:** `hermes_cli/relaunch.py:22-80`: `_build_inherited_flag_table()` introspects `build_top_level_parser()` for actions tagged `inherit_on_relaunch` (set by `_parser._inherited_flag`) → `-m/--model`, `--provider`, `--reasoning`, `--accept-hooks`, `-s/--skills`, `--yolo`, `--pass-session-id`, `--ignore-user-config`, `--ignore-rules`, `--safe-mode`, `--tui`, `--cli`, `--dev` (root and chat forms) plus `--profile`/`-p`. `_extract_inherited_flags(argv)` copies them; `resolve_hermes_bin()` finds the executable even when not on PATH (`nix run`, `python -m`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** `os.execv` of a new hermes process.
- **Config / env:** n/a.
- **Edge cases / guards:** `preserve_inherited=False` is used for `update` so `--tui` is not carried.
- **Rebuild notes:** Tag argparse actions with metadata and derive the carry-over list from the parser.

---

## B. `hermes chat`

### `hermes chat` (interactive chat sub-command)  `id: cli-a.chat`
- **Surface:** CLI
- **Where:** `hermes chat [options]` (also the implicit default for bare `hermes`, `hermes -c`, `hermes --resume X`). Help header verbatim: `usage: hermes chat [-h] [-q QUERY | --query-file PATH] [--oneshot] [--image IMAGE] [-m MODEL] [-t TOOLSETS] [--reasoning LEVEL] [-s SKILLS] [--provider PROVIDER] [-v] [-Q] [--resume SESSION_ID] [--no-restore-cwd] [--in DIR] [--continue [SESSION_NAME]] [--create-if-missing] [--worktree] [--accept-hooks] [--checkpoints] [--max-turns N] [--run-budget SECONDS] [--yolo] [--pass-session-id] [--ignore-user-config] [--ignore-rules] [--safe-mode] [--source SOURCE] [--tui] [--cli] [--dev]`; description `Start an interactive chat session with Hermes Agent`; parser help `Interactive chat with the agent`.
- **What it does:** Starts the classic REPL (or the TUI), optionally seeded with a first query, or answers a single query and exits.
- **How it works:** Parser `hermes_cli/_parser.py:347-609`; handler `cmd_chat` (`hermes_cli/main.py:3163-3508`). Sequence: `_resolve_use_tui` → `_apply_safe_mode` → `--in` chdir → `--resume latest` → `_resolve_continue_arg` → `@claude/@codex` import → title/id resolution → cwd restore → xAI warning → first-run guard → background update check (`banner.prefetch_update_check`, `prefetch_banner_data`, gated on Termux by `_termux_should_prefetch_update_check`) → bundled skills sync (`_sync_bundled_skills_for_startup`; foreground on first run when `~/.hermes/skills` has no SKILL.md, else daemon thread `bundled-skills-sync`) → env flags (`HERMES_YOLO_MODE`, `HERMES_IGNORE_USER_CONFIG`, `HERMES_IGNORE_RULES`, `HERMES_SESSION_SOURCE`) → `_pin_kanban_board_env` (`HERMES_KANBAN_BOARD` from `kanban_db.get_current_board`) → `_confirm_startup_expensive_model_override` → TUI branch `_launch_tui(...)` or classic: `--query-file` read, kwargs `{model, provider, reasoning, toolsets, skills, verbose, quiet, query, oneshot, image, resume, worktree, checkpoints, pass_session_id, max_turns, run_budget, ignore_rules, ignore_user_config, compact}` (None values dropped) → `cli.main(**kwargs)` (`cli.py:21619`). `cli.main`: sets `HERMES_INTERACTIVE=1`, worktree setup, toolset resolution, `HermesCLI(...)` construction, skill preload thread, list-tools/toolsets shortcuts (internal), atexit `_run_cleanup`, SIGTERM/SIGHUP handlers for `-q` mode, then either `_should_seed_interactive` (`cli.py:5159`: TTY on stdin+stdout and not `--oneshot`/`-Q`) → seeded interactive `HermesCLI.run()`, single-query `cli.chat(query, images)` + `_finalize_single_query`, or interactive `run()`. Errors: `ValueError` → `Error: <e>` exit 1; mixed-version `ImportError` → `emit_partial_update_hint`.
- **Inputs / options:** every flag in the entries below plus shared root flags (see `cli-a.chat-shared-flags`).
- **Outputs / side effects:** Session rows in `~/.hermes/state.db`; `~/.hermes/terminal-sessions/<id>` breadcrumb; `~/.hermes/pastes/paste_N_HHMMSS.txt` for collapsed pastes; `~/.hermes/cache/banner_snapshot*` (banner snapshot); logs.
- **Config / env:** see individual flags; `HERMES_INTERACTIVE=1` set for sudo prompts.
- **Edge cases / guards:** Positional text is not accepted (must use `-q`); `-q` and `--query-file` are mutually exclusive (argparse group + explicit check `Error: -q/--query and --query-file are mutually exclusive` exit 2).
- **Rebuild notes:** Thin argparse → kwargs → REPL class. Better: accept a positional prompt and `--stdin`.

### `-q QUERY` / `--query QUERY`  `id: cli-a.chat-query`
- **Surface:** CLI
- **Where:** `hermes chat -q "Hello"`; help verbatim: `Query to run. On a real TTY the prompt seeds an interactive session (submitted literally as the first turn); combined with --oneshot or -Q, or on a non-TTY, it answers and exits.`
- **What it does:** Seeds an interactive session with a first turn (TTY) or runs a single query and exits (non-TTY / `-Q` / `--oneshot`).
- **How it works:** `_parser.py:354` (mutually exclusive group with `--query-file`). `_should_seed_interactive(query, image, quiet, oneshot)` (`cli.py:5159-5181`). Seeded mode wraps the text in `_SeededQueryMessage(text, images)` (`cli.py:5136`) so it is submitted literally (never parsed as a slash command or `!` shell escape). Single-query mode calls `cli.chat(query, images)`, prints the answer, then `_finalize_single_query` (`cli.py:1462`: flush one-shot session store, wait for background completions, session finalize notification) and prints the exit summary without clearing the screen (`_print_exit_summary(clear_screen=False)`). `_collect_query_images` (`cli.py:4763`) extracts leading local image paths from the query and merges `--image`.
- **Inputs / options:** `QUERY` string.
- **Outputs / side effects:** Session persisted (unless discarded as empty); in single-query mode stdout carries banner + tool feed + answer unless `-Q`.
- **Config / env:** n/a.
- **Edge cases / guards:** With `--worktree`, the docs example `hermes -w -z` applies to `-z`, while `hermes chat -w -q` runs the single query inside the worktree.
- **Rebuild notes:** Treat a seed as a queued literal first message. Better: allow multiple `-q` to queue several turns.

### `--query-file PATH`  `id: cli-a.chat-query-file`
- **Surface:** CLI
- **Where:** `hermes chat --query-file prompt.txt`, `hermes chat --query-file - < prompt.txt`; help verbatim: `Read the single query from a file instead of the command line ('-' reads stdin). Safe for arbitrary text: nothing is shell-interpreted, so quotes, $(...), and backticks are preserved verbatim. Mutually exclusive with -q.`
- **What it does:** Loads the query text from a file or stdin (the transport used by Bot-Mode DMs).
- **How it works:** `_parser.py:362`; `cmd_chat` (`main.py:3437-3459`): `-` → `sys.stdin.read()`, else `open(path, encoding="utf-8", errors="replace")`; errors `Error: cannot read --query-file <p>: <e>` (exit 2) and `Error: --query-file <p> is empty` (exit 2).
- **Inputs / options:** `PATH` or `-`.
- **Outputs / side effects:** as `-q`.
- **Config / env:** n/a.
- **Edge cases / guards:** Non-TTY stdin (when reading from `-`) implies single-query mode.
- **Rebuild notes:** Read file → same path as `-q`.

### `--oneshot` (chat form)  `id: cli-a.chat-oneshot-flag`
- **Surface:** CLI
- **Where:** `hermes chat --oneshot -q "…"`; help verbatim: `With -q/--query-file: answer the query and exit (legacy single-query behavior) instead of seeding an interactive session. Implied on non-TTY stdio and by -Q/--quiet.`
- **What it does:** Forces answer-and-exit on a TTY.
- **How it works:** `_parser.py:372` (`dest="oneshot_exit"` — distinct from the root value-taking `-z/--oneshot`); `cmd_chat` passes `oneshot=bool(args.oneshot_exit)`; `_should_seed_interactive` returns False.
- **Inputs / options:** boolean.
- **Outputs / side effects:** Prints banner, tool feed and answer (unlike `-z`).
- **Config / env:** n/a.
- **Edge cases / guards:** No effect without `-q`/`--query-file`.
- **Rebuild notes:** Boolean switch between seeded and single-shot flows.

### `--image IMAGE`  `id: cli-a.chat-image`
- **Surface:** CLI
- **Where:** `hermes chat -q "Describe this" --image ~/Pictures/cat.png`; help: `Optional local image path to attach to a single query`.
- **What it does:** Attaches a local image to the seeded/single query.
- **How it works:** `_parser.py:387`; `_collect_query_images(query, image_arg)` (`cli.py:4763`) resolves via `_resolve_attachment_path`; images are sent as vision content (or pre-described by the auxiliary vision model via `_preprocess_images_with_vision` when the main model lacks vision). TUI receives `HERMES_TUI_IMAGE`.
- **Inputs / options:** file path.
- **Outputs / side effects:** none.
- **Config / env:** `HERMES_TUI_IMAGE`, `auxiliary.vision.*`.
- **Edge cases / guards:** Termux example path helper `_termux_example_image_path` shows `~/storage/shared/Pictures/cat.png`.
- **Rebuild notes:** Path → base64 image part.

### `-v` / `--verbose` (chat)  `id: cli-a.chat-verbose`
- **Surface:** CLI
- **Where:** `hermes chat --verbose`; help: `Verbose output`.
- **What it does:** Enables debug-level logging/tool output; in the TUI sets tool progress to `verbose`.
- **How it works:** `_parser.py:442` (`default=SUPPRESS`); `HermesCLI(verbose=True)`; TUI `HERMES_TUI_TOOL_PROGRESS=verbose`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** more console output.
- **Config / env:** `agent.verbose`, `HERMES_TUI_TOOL_PROGRESS`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Log-level toggle.

### `-Q` / `--quiet` (chat)  `id: cli-a.chat-quiet`
- **Surface:** CLI
- **Where:** `hermes chat --quiet -q "Return only JSON"`; help verbatim: `Quiet mode for programmatic use: suppress banner, spinner, and tool previews. Only output the final response and session info.`
- **What it does:** Machine-readable single-query contract (implies answer-and-exit).
- **How it works:** `_parser.py:449`; `cmd_chat` kwargs `quiet=True`; `_should_seed_interactive` false; TUI `HERMES_TUI_TOOL_PROGRESS=off`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** stdout = response + session info lines (unlike `-z`, session id is printed).
- **Config / env:** `HERMES_QUIET`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Suppress chrome; keep session summary.

### `--create-if-missing`  `id: cli-a.chat-create-if-missing`
- **Surface:** CLI
- **Where:** `hermes chat -c "thread name" --create-if-missing -q "…"`; help verbatim: `With -c/--continue <name>: if no session matches the name, create a new session with that title and proceed (instead of failing with a not-found error). Programmatic callers that want 'send to this named thread, making it if needed'.`
- **What it does:** Deterministic "resume-or-create by title" for scripts/plugins (#86794).
- **How it works:** `_parser.py:490`; `_resolve_continue_arg` → `_create_titled_session` (`main.py:1840`).
- **Inputs / options:** boolean; requires `-c NAME`.
- **Outputs / side effects:** New session row with user-provenance title.
- **Config / env:** n/a.
- **Edge cases / guards:** Failure → `No session found matching '<name>' and a new titled session could not be created.` exit 1; bare `-c` → warning only.
- **Rebuild notes:** Title lookup → create-on-miss.

### `--checkpoints`  `id: cli-a.chat-checkpoints`
- **Surface:** CLI
- **Where:** `hermes chat --checkpoints`; help: `Enable filesystem checkpoints before destructive file operations (use /rollback to restore)`.
- **What it does:** Turns on the checkpoint system for this session (snapshots under `~/.hermes/checkpoints/`).
- **How it works:** `_parser.py:519`; `HermesCLI(checkpoints=True)`; TUI `HERMES_TUI_CHECKPOINTS=1`; storage governed by `checkpoints.*` config (default `enabled: false`, `max_snapshots: 20`, `max_total_size_mb: 500`, `max_file_size_mb: 10`, `auto_prune: true`, `retention_days: 7`, `min_interval_hours: 24`); managed by `hermes checkpoints` (sibling shard).
- **Inputs / options:** boolean.
- **Outputs / side effects:** files under `~/.hermes/checkpoints/`.
- **Config / env:** `checkpoints.*`, `HERMES_TUI_CHECKPOINTS`.
- **Edge cases / guards:** `_run_checkpoint_auto_maintenance` (`cli.py:2676`) prunes on startup.
- **Rebuild notes:** Pre-write snapshot hook + `/rollback`.

### `--max-turns N`  `id: cli-a.chat-max-turns`
- **Surface:** CLI
- **Where:** `hermes chat --max-turns 50`; help: `Maximum tool-calling iterations per conversation turn (default: 500, or agent.max_turns in config)`.
- **What it does:** Caps tool-call iterations per user turn (shared with subagents).
- **How it works:** `_parser.py:525` (`type=int`); `HermesCLI(max_turns=…)`; TUI `HERMES_TUI_MAX_TURNS`; config default `agent.max_turns` null → 500 in `cli.load_cli_config` defaults.
- **Inputs / options:** integer.
- **Outputs / side effects:** none.
- **Config / env:** `agent.max_turns`, `HERMES_TUI_MAX_TURNS`.
- **Edge cases / guards:** none.
- **Rebuild notes:** Loop bound.

### `--run-budget SECONDS`  `id: cli-a.chat-run-budget`
- **Surface:** CLI
- **Where:** `hermes chat --run-budget 600 --oneshot -q "…"`; help verbatim: `Optional wall-clock budget in seconds for each conversation run. At 80% elapsed the agent gets a one-time wrap-up notice, and implicit provider stale timeouts are capped to the remaining budget so one hung call can't consume the run. Unset = off. Also configurable as agent.run_budget_seconds in config.yaml. Intended for one-shot/eval invocations with a hard ceiling.`
- **What it does:** Hard wall-clock ceiling per run with a wrap-up nudge at 80 %.
- **How it works:** `_parser.py:532` (`type=float`, `dest="run_budget"`); `HermesCLI(run_budget=…)` → agent run budget.
- **Inputs / options:** float seconds.
- **Outputs / side effects:** none.
- **Config / env:** `agent.run_budget_seconds` (default null).
- **Edge cases / guards:** Not forwarded to the TUI.
- **Rebuild notes:** Deadline stored on the agent; checked per iteration and used to cap HTTP timeouts.

### `--source SOURCE`  `id: cli-a.chat-source`
- **Surface:** CLI
- **Where:** `hermes chat --source tool -q "…"`; help: `Session source tag for filtering (default: cli). Use 'tool' for third-party integrations that should not appear in user session lists.`
- **What it does:** Tags the session's `source` column so integrations' sessions stay out of user listings.
- **How it works:** `_parser.py:582`; `cmd_chat` sets `HERMES_SESSION_SOURCE` (`main.py:3401-3403`); SessionDB uses it when creating the session.
- **Inputs / options:** free string (`cli`, `tool`, …).
- **Outputs / side effects:** `sessions.source` value.
- **Config / env:** `HERMES_SESSION_SOURCE`.
- **Edge cases / guards:** `-c`/`latest` lookups filter by source `cli`/`tui`, so `tool` sessions are not auto-resumed.
- **Rebuild notes:** Env → DB column.

### Shared flags redeclared on `chat`  `id: cli-a.chat-shared-flags`
- **Surface:** CLI
- **Where:** `hermes chat -m … -t … --reasoning … -s … --provider … --resume … --no-restore-cwd --in … --continue … --worktree --accept-hooks --yolo --pass-session-id --ignore-user-config --ignore-rules --safe-mode --tui --cli --dev`.
- **What it does:** Makes every root override also valid after the `chat` word.
- **How it works:** `_parser.py:402-607`: each is redeclared with `default=argparse.SUPPRESS` so the root value survives when the flag is given before `chat` (`hermes -m foo chat`) and the chat value wins when given after. Help strings differ slightly: `-m/--model` `Model to use (e.g., anthropic/claude-sonnet-4)`; `-t/--toolsets` `Comma-separated toolsets to enable`; `--reasoning` `Reasoning effort for this session: none, minimal, low, medium, high, xhigh, max, or ultra. Overrides agent.reasoning_effort for this run only (same levels as the /reasoning slash command).`; `--provider` `Inference provider (default: auto). Built-in or a user-defined name from providers: in config.yaml.`; `--resume/-r SESSION_ID` `Resume a previous session by ID (shown on exit), or 'latest' for the most recent session`; `--in DIR` `Change into DIR before starting or resuming (scopes '--resume latest' / -c lookups to DIR's workspace).`; `--worktree/-w` `Run in an isolated git worktree (for parallel agents on the same repo)`; `--accept-hooks` `… (see also HERMES_ACCEPT_HOOKS env var and hooks_auto_accept: in config.yaml).`; `--ignore-user-config` `… Useful for isolated CI runs, reproduction, and third-party integrations.`; `--ignore-rules` `… Combine with --ignore-user-config for a fully isolated run.`; `--safe-mode` `… Use to isolate whether a problem comes from your setup or from Hermes itself.`; the rest identical to root.
- **Inputs / options:** as root.
- **Outputs / side effects:** as root.
- **Config / env:** as root.
- **Edge cases / guards:** `tests/hermes_cli/test_argparse_flag_propagation.py` guards the SUPPRESS pattern.
- **Rebuild notes:** Duplicate flags on the sub-parser with SUPPRESS defaults.

## C. `hermes model` — interactive provider + model picker

### `hermes model` (provider & model selector)  `id: cli-a.model`
- **Surface:** CLI
- **Where:** `hermes model` (run from a terminal, NOT inside a chat session). Help header verbatim: `Interactively select your inference provider and default model`; top-level help entry: `Select default model and provider`. Docs: `website/docs/reference/cli-commands.md:186` — "Interactive provider + model selector. **This is the command for adding new providers, setting up API keys, and running OAuth flows.**"
- **What it does:** Opens a two-step curses picker — first a provider, then a model — running whatever credential/OAuth flow the chosen provider needs, and writes the result into `~/.hermes/config.yaml` as the new default model.
- **How it works:** parser in `hermes_cli/subcommands/model.py:13-62` (`build_model_parser`), handler `cmd_model` at `hermes_cli/main.py:3789-3805`. `cmd_model` calls `_require_tty("model")` (`main.py:490-504`), optionally clears the picker cache, then wraps `select_provider_and_model(args=args)` in `run_setup_action_with_navigation("Model & Provider", …, cancelled_message="No change.")` (`hermes_cli/setup.py:3047-3064`) so Escape/Left navigation behaves exactly as in the setup wizard. `select_provider_and_model` (`main.py:3822-4275`) reads the effective provider (`config.yaml model.provider` > `HERMES_INFERENCE_PROVIDER` > `auto`), builds the row list, prompts, and dispatches to one of 20+ `_model_flow_*` functions in `hermes_cli/model_setup_flows.py`.
- **Inputs / options:** `-h/--help`, `--refresh`, `--portal-url PORTAL_URL`, `--inference-url INFERENCE_URL`, `--client-id CLIENT_ID`, `--scope SCOPE`, `--no-browser`, `--timeout TIMEOUT`, `--ca-bundle CA_BUNDLE`, `--insecure`. No positional arguments.
- **Outputs / side effects:** prints two header lines before the picker — `  Current model:    <model>` and `  Active provider:  <label>`; writes `model.default`, `model.provider`, and (for custom endpoints) `model.base_url` / `model.api_mode` into `config.yaml`; may write credentials to `~/.hermes/.env` and OAuth tokens into the auth store; clears a stale `OPENAI_BASE_URL` afterwards.
- **Config / env:** reads `model.provider`, `model.default`, `model.base_url`, `providers:`, `custom_providers:`, `model_catalog.excluded_providers`; env `HERMES_INFERENCE_PROVIDER`, `OPENAI_BASE_URL`, `HERMES_HOME`.
- **Edge cases / guards:** exits 1 with `Error: 'hermes model' requires an interactive terminal.\nIt cannot be run through a pipe or non-interactive subprocess.\nRun it directly in your terminal instead.` when stdin is not a TTY. An unknown `model.provider` prints `Warning: Unknown provider '<x>'. Check 'hermes model' for available providers, or run 'hermes doctor' to diagnose config issues. Falling back to auto provider detection.` Providers listed in `model_catalog.excluded_providers` are hidden (matched case-insensitively against slug and every alias).
- **Rebuild notes:** Two-stage picker over a canonical provider table plus user-defined endpoints; each provider gets a pluggable credential flow; persist `{provider, model, base_url, api_mode}`. A better version would show live health/latency and per-model pricing inline and let the user try a model before committing.

### `hermes model --refresh`  `id: cli-a.model-refresh`
- **Surface:** CLI
- **Where:** `hermes model --refresh`; help verbatim: `Wipe the model picker disk cache and re-fetch every provider's live /v1/models list.`
- **What it does:** Deletes the cached provider model lists so the picker re-queries every provider's `/v1/models` endpoint.
- **How it works:** `main.py:3792-3799` → `hermes_cli.models.clear_provider_models_cache()` (`models.py:4635-4660`) with `provider=None`, which unlinks `~/.hermes/provider_models_cache.json` (`models.py:4385-4387`) and clears the in-process Ollama caches `_OLLAMA_LOCAL_MODELS_CACHE`, `_OLLAMA_LOCAL_PROBE_FAILURE_CACHE`, `_OLLAMA_LOCAL_PROBE_REACHABLE`.
- **Inputs / options:** boolean flag, no value.
- **Outputs / side effects:** prints `  Cleared model picker cache.`; removes the cache file. Failures are swallowed (bare `except Exception: pass`).
- **Config / env:** cache path derives from `HERMES_HOME`.
- **Edge cases / guards:** Same flag exists on the `/model` slash command (`/model --refresh`) and clears the same cache.
- **Rebuild notes:** A single JSON cache file keyed by provider + credential fingerprint; refresh = unlink.

### `hermes model --portal-url PORTAL_URL`  `id: cli-a.model-portal-url`
- **Surface:** CLI
- **Where:** `hermes model --portal-url https://portal.example.com`; help verbatim: `Portal base URL for Nous login (default: production portal)`.
- **What it does:** Points the Nous Portal OAuth login at a non-production portal.
- **How it works:** `subcommands/model.py:26-29`; consumed only by `_model_flow_nous` (`model_setup_flows.py:429-437`) which packs it into an `argparse.Namespace` passed to `hermes_cli.auth._login_nous`.
- **Inputs / options:** any URL string.
- **Outputs / side effects:** none by itself; changes which host the device/OAuth flow talks to and what is stored as `portal_base_url` in the auth state.
- **Config / env:** default comes from `hermes_cli.auth.DEFAULT_NOUS_PORTAL_URL` (`https://portal.nousresearch.com`, see `models.py:1207-1222`).
- **Edge cases / guards:** ignored for every non-Nous provider flow.
- **Rebuild notes:** Thread the base URL through the OAuth client construction.

### `hermes model --inference-url INFERENCE_URL`  `id: cli-a.model-inference-url`
- **Surface:** CLI
- **Where:** `hermes model --inference-url https://inference.example.com/v1`; help verbatim: `Inference API base URL for Nous login (default: production inference API)`.
- **What it does:** Overrides the inference endpoint saved after a Nous Portal login.
- **How it works:** `subcommands/model.py:30-33` → `_model_flow_nous` Namespace field `inference_url` → `_login_nous`.
- **Inputs / options:** URL string.
- **Outputs / side effects:** the saved provider config points at that base URL.
- **Config / env:** n/a beyond the Nous auth state.
- **Edge cases / guards:** Nous-only.
- **Rebuild notes:** Same as `--portal-url` but for the data-plane host.

### `hermes model --client-id CLIENT_ID`  `id: cli-a.model-client-id`
- **Surface:** CLI
- **Where:** `hermes model --client-id my-client`; help verbatim: `OAuth client id to use for Nous login (default: hermes-cli)`.
- **What it does:** Uses a different OAuth client identifier for the Nous login.
- **How it works:** `subcommands/model.py:34-38` (`default=None`) → `_model_flow_nous` → `_login_nous`.
- **Inputs / options:** string; `None` means the built-in `hermes-cli`.
- **Outputs / side effects:** changes the `client_id` in the authorization request.
- **Config / env:** n/a.
- **Edge cases / guards:** Nous-only.
- **Rebuild notes:** Plumb through to the OAuth authorize/token requests.

### `hermes model --scope SCOPE`  `id: cli-a.model-scope`
- **Surface:** CLI
- **Where:** `hermes model --scope "openid profile"`; help verbatim: `OAuth scope to request for Nous login`.
- **What it does:** Requests a custom OAuth scope string during Nous login.
- **How it works:** `subcommands/model.py:39-41` (`default=None`) → `_model_flow_nous` Namespace → `_login_nous`.
- **Inputs / options:** space-separated scope string.
- **Outputs / side effects:** affects the granted token's scope.
- **Config / env:** n/a.
- **Edge cases / guards:** Nous-only.
- **Rebuild notes:** Pass-through parameter.

### `hermes model --no-browser`  `id: cli-a.model-no-browser`
- **Surface:** CLI
- **Where:** `hermes model --no-browser`; help verbatim: `Do not attempt to open the browser automatically during Nous login`.
- **What it does:** Suppresses the automatic browser launch so the user copies the login URL by hand (headless/SSH boxes).
- **How it works:** `subcommands/model.py:42-46`, `action="store_true"`; read as `no_browser=bool(getattr(args, "no_browser", False))` in `model_setup_flows.py:435`.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** the login flow prints the URL instead of calling the OS opener.
- **Config / env:** n/a.
- **Edge cases / guards:** Nous-only.
- **Rebuild notes:** Print-URL fallback for every OAuth flow.

### `hermes model --timeout TIMEOUT`  `id: cli-a.model-timeout`
- **Surface:** CLI
- **Where:** `hermes model --timeout 30`; help verbatim: `HTTP request timeout in seconds for Nous login (default: 15)`.
- **What it does:** Sets the per-request HTTP timeout used during the Nous login exchange.
- **How it works:** `subcommands/model.py:47-52`, `type=float, default=15.0`; `model_setup_flows.py:436` uses `getattr(args, "timeout", None) or 15.0`.
- **Inputs / options:** float seconds.
- **Outputs / side effects:** none persisted.
- **Config / env:** n/a.
- **Edge cases / guards:** a `0` value falls back to `15.0` because of the `or` coercion.
- **Rebuild notes:** Timeout on the token/device-code HTTP calls.

### `hermes model --ca-bundle CA_BUNDLE`  `id: cli-a.model-ca-bundle`
- **Surface:** CLI
- **Where:** `hermes model --ca-bundle /etc/ssl/corp.pem`; help verbatim: `Path to CA bundle PEM file for Nous TLS verification`.
- **What it does:** Verifies the Nous TLS chain against a custom CA bundle (corporate MITM proxies).
- **How it works:** `subcommands/model.py:53-55`; forwarded as `ca_bundle` on the login Namespace (`model_setup_flows.py:437`).
- **Inputs / options:** filesystem path to a PEM file.
- **Outputs / side effects:** none persisted.
- **Config / env:** n/a.
- **Edge cases / guards:** Nous-only; invalid path surfaces as a TLS error from the HTTP client.
- **Rebuild notes:** Pass to the TLS context of the login client.

### `hermes model --insecure`  `id: cli-a.model-insecure`
- **Surface:** CLI
- **Where:** `hermes model --insecure`; help verbatim: `Disable TLS verification for Nous login (testing only)`.
- **What it does:** Turns off certificate verification for the Nous login requests.
- **How it works:** `subcommands/model.py:56-60`, `action="store_true"`; `model_setup_flows.py:438` reads `insecure=bool(getattr(args, "insecure", False))`.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** none persisted; credentials travel unverified.
- **Config / env:** n/a.
- **Edge cases / guards:** documented as testing-only; Nous-only.
- **Rebuild notes:** `verify=False` on the login HTTP session; keep it out of the runtime inference path.

### Provider picker — canonical provider rows  `id: cli-a.model-provider-rows`
- **Surface:** CLI
- **Where:** The first screen of `hermes model`, titled `Select provider:`. Each row is the provider's `tui_desc`.
- **What it does:** Lists every provider Hermes can authenticate against, with the active one marked.
- **How it works:** `CANONICAL_PROVIDERS` in `hermes_cli/models.py:1307-1348` (a list of `ProviderEntry(slug, label, tui_desc)`), auto-extended at `models.py:1349-1367` with any `plugins/model-providers/<name>/` provider whose `auth_type` is not in `{oauth_device_code, oauth_external, external_process, aws_sdk, copilot, vertex}`. Rows are folded through `group_providers()` (`models.py:1418-1470`) and rendered at `main.py:4053-4090`. The active row is suffixed with `  ← currently active` and pre-selected.
- **Inputs / options:** the 40 built-in rows, in order, with their VERBATIM descriptions:
  1. `nous` — `Nous Portal (Everything your agent needs, 300+ models with bundled tool use)`
  2. `fireworks` — `Fireworks AI (OpenAI-compatible direct model API)`
  3. `openrouter` — `OpenRouter (Pay-per-use API aggregator)`
  4. `moa` — `Mixture of Agents (named presets; aggregator acts after reference models)`
  5. `novita` — `NovitaAI (Cloud: Model API, Agent Sandbox, GPU Cloud)`
  6. `lmstudio` — `LM Studio (Local desktop app with built-in model server)`
  7. `anthropic` — `Anthropic (Claude models via API key or Claude Code)`
  8. `openai-codex` — `ChatGPT or Codex Subscription (Sign in with your ChatGPT account, uses Codex models)`
  9. `openai-api` — `OpenAI API (api.openai.com, API key)`
  10. `alibaba` — `Qwen Cloud / DashScope (Qwen + multi-provider)`
  11. `xai-oauth` — `xAI Grok OAuth (SuperGrok / Premium+ subscription)`
  12. `xiaomi` — `Xiaomi MiMo (MiMo-V2.5 and V2 models: pro, omni, flash)`
  13. `tencent-tokenhub` — `Tencent TokenHub (Hy4 preview via tokenhub.tencentmaas.com)`
  14. `tencent-tokenplan` — `Tencent TokenPlan (Hy4 preview via api.lkeap.cloud.tencent.com, Anthropic Messages)`
  15. `nvidia` — `NVIDIA NIM (Nemotron models via build.nvidia.com or local NIM)`
  16. `copilot` — `GitHub Copilot (Uses GITHUB_TOKEN or gh auth token)`
  17. `copilot-acp` — `GitHub Copilot ACP (Spawns copilot --acp --stdio)`
  18. `huggingface` — `Hugging Face Inference Providers`
  19. `gemini` — `Google AI Studio (Native Gemini API)`
  20. `vertex` — `Google Vertex AI (Gemini via GCP; OAuth2 service account or ADC, GCP billing/quotas)`
  21. `deepseek` — `DeepSeek (V3, R1, coder, direct API)`
  22. `xai` — `xAI Grok (Direct API)`
  23. `zai` — `Z.AI / GLM (Zhipu direct API)`
  24. `kimi-coding` — `Kimi Coding Plan (api.kimi.com & Moonshot API)`
  25. `kimi-coding-cn` — `Kimi / Moonshot China (Domestic direct API)`
  26. `stepfun` — `StepFun Step Plan (Agent / coding models via Step Plan API)`
  27. `minimax` — `MiniMax (Global direct API)`
  28. `minimax-oauth` — `MiniMax via OAuth browser login (Coding Plan, minimax.io)`
  29. `minimax-cn` — `MiniMax China (Domestic direct API)`
  30. `ollama-cloud` — `Ollama Cloud (Cloud-hosted open models, ollama.com)`
  31. `arcee` — `Arcee AI (Trinity models, direct API)`
  32. `gmi` — `GMI Cloud (Multi-model direct API)`
  33. `kilocode` — `Kilo Code (Kilo Gateway API)`
  34. `opencode-zen` — `OpenCode Zen (Curated models, pay-as-you-go)`
  35. `opencode-go` — `OpenCode Go (Open models subscription)`
  36. `bedrock` — `AWS Bedrock (Claude, Nova, Llama, DeepSeek; IAM or API key)`
  37. `azure-foundry` — `Azure Foundry (OpenAI-style or Anthropic-style endpoint, your Azure AI deployment)`
  38. `ai-gateway` — `Vercel AI Gateway (Multi-model aggregator)`
  39. `qwen-oauth` — `Qwen OAuth (Reuses local Qwen CLI login)`
  40. plus any auto-injected plugin provider, labelled `<display_name>` / `<description>` or `<label> (direct API)`.
  Short labels (used in group submenus and elsewhere) are `Nous Portal`, `Fireworks AI`, `OpenRouter`, `Mixture of Agents`, `NovitaAI`, `LM Studio`, `Anthropic`, `ChatGPT or Codex Subscription`, `OpenAI API`, `Qwen Cloud`, `xAI Grok OAuth (SuperGrok / Premium+)`, `Xiaomi MiMo`, `Tencent TokenHub`, `Tencent TokenPlan`, `NVIDIA NIM`, `GitHub Copilot`, `GitHub Copilot ACP`, `Hugging Face`, `Google AI Studio`, `Google Vertex AI`, `DeepSeek`, `xAI`, `Z.AI / GLM`, `Kimi / Kimi Coding Plan`, `Kimi / Moonshot (China)`, `StepFun Step Plan`, `MiniMax`, `MiniMax (OAuth)`, `MiniMax (China)`, `Ollama Cloud`, `Arcee AI`, `GMI Cloud`, `Kilo Code`, `OpenCode Zen`, `OpenCode Go`, `AWS Bedrock`, `Azure Foundry`, `Vercel AI Gateway`, `Qwen OAuth (Portal)`, and the special `Custom endpoint`.
- **Outputs / side effects:** selection routes to the matching `_model_flow_*`.
- **Config / env:** `model_catalog.excluded_providers` hides rows.
- **Edge cases / guards:** the dispatch chain at `main.py:4200-4264` has explicit branches for `openrouter`, `moa`, `ai-gateway`, `nous`, `openai-codex`, `xai-oauth`, `qwen-oauth`, `minimax-oauth`, `copilot-acp`, `copilot`, `custom`, saved custom providers, `remove-custom`, `anthropic`, `kimi-coding`, `stepfun`, `bedrock`, `vertex`, `azure-foundry`, and a set branch covering `openai-api, gemini, deepseek, xai, zai, kimi-coding-cn, minimax, minimax-cn, kilocode, opencode-zen, opencode-go, opencode-free, alibaba, huggingface, xiaomi, arcee, gmi, nvidia, ollama-cloud, tencent-tokenhub, tencent-tokenplan, lmstudio` plus any profile whose `auth_type == "api_key"` (`_is_profile_api_key_provider`, `main.py:3808-3820`).
- **Rebuild notes:** Keep a single declarative provider table (slug/label/description/auth_type) and derive every picker from it; new providers should be pure data drops.

### Provider picker — provider groups (collapsed rows)  `id: cli-a.model-provider-groups`
- **Surface:** CLI
- **Where:** Rows rendered as `<Group label> ▸ (<group description>)`; selecting one opens a sub-picker titled `Select <Group label> provider:`.
- **What it does:** Folds multiple slugs of the same vendor into one top-level row so the list stays short; every member slug stays individually addressable via `--provider` or `/model`.
- **How it works:** `PROVIDER_GROUPS` (`models.py:1395-1411`), reverse index `_SLUG_TO_GROUP` (`models.py:1408-1411`), fold function `group_providers()` (`models.py:1418-1470`). A group appears at the position of its first present member; a group reduced to one present member degrades to a plain row. Sub-picker at `main.py:4108-4127`.
- **Inputs / options:** all 9 groups, VERBATIM `(group_id → label, description, members)`:
  - `kimi` → `Kimi / Moonshot`, `Coding Plan, Moonshot global & China endpoints`, members `kimi-coding`, `kimi-coding-cn`
  - `minimax` → `MiniMax`, `Global, OAuth Coding Plan & China endpoints`, members `minimax`, `minimax-oauth`, `minimax-cn`
  - `xai` → `xAI Grok`, `Direct API or SuperGrok / Premium+ OAuth`, members `xai`, `xai-oauth`
  - `google` → `Google Gemini`, `Google AI Studio (API key)`, members `gemini`
  - `openai` → `OpenAI`, `ChatGPT/Codex subscription or direct OpenAI API`, members `openai-codex`, `openai-api`
  - `qwen` → `Qwen`, `Qwen Cloud / DashScope, Coding Plan, Token Plan & Qwen CLI OAuth`, members `alibaba`, `alibaba-cn`, `alibaba-coding-plan`, `alibaba-coding-plan-cn`, `alibaba-token-plan`, `alibaba-token-plan-cn`, `qwen-oauth`
  - `opencode` → `OpenCode`, `Zen pay-as-you-go, Go subscription, or free tier`, members `opencode-zen`, `opencode-go`, `opencode-free`
  - `copilot` → `GitHub Copilot`, `GitHub token API or copilot --acp process`, members `copilot`, `copilot-acp`
  - `tencent` → `Tencent Hy`, `Hy4 / Hy3 via TokenHub & TokenPlan`, members `tencent-tokenhub`, `tencent-tokenplan`
- **Outputs / side effects:** resolves to a concrete slug before dispatch; cancelling the sub-picker prints `No change.`
- **Config / env:** n/a (display only).
- **Edge cases / guards:** duplicate slugs in the input are ignored after first sight; the sub-picker pre-selects the active member when the active provider is in the group.
- **Rebuild notes:** Pure display fold over the flat list; never let grouping leak into identity.

### Provider picker — `Custom endpoint (enter URL manually)`  `id: cli-a.model-custom-endpoint-row`
- **Surface:** CLI
- **Where:** Row labelled verbatim `Custom endpoint (enter URL manually)`, appended after the canonical + saved-custom rows (`main.py:4141`).
- **What it does:** Lets the user type a base URL for any OpenAI-compatible server and save it as a named custom provider.
- **How it works:** dispatches to `_model_flow_custom(config)` (`model_setup_flows.py:895-1137`). Saved entries then reappear as their own rows labelled `<name> (<host>) — <saved model>` (`main.py:4129-4140`).
- **Inputs / options:** base URL, display name (default generated by `_auto_provider_name`, e.g. `Local (localhost:11434)`), optional API key, optional model, API-compatibility mode.
- **Outputs / side effects:** appends to `custom_providers:` in `config.yaml`; sets `model.provider: custom` and `model.base_url`.
- **Config / env:** `custom_providers`, `providers`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`.
- **Edge cases / guards:** when a saved custom provider is selected but has since been deleted, prints `Warning: the selected saved custom provider is no longer available. It may have been removed from config.yaml. No change.` (`main.py:4222-4227`).
- **Rebuild notes:** Store `{name, base_url, api_key|key_env, model, models, api_mode, extra_headers, discover_models}` per endpoint.

### Provider picker — API compatibility mode prompt  `id: cli-a.model-api-mode-picker`
- **Surface:** CLI
- **Where:** Inside the custom-endpoint flow. Header verbatim: `Select API compatibility mode:`; input line `Choice [1-4, Enter to keep current/detected]: `.
- **What it does:** Chooses which wire protocol Hermes speaks to a custom endpoint.
- **How it works:** `_prompt_custom_api_mode_selection` (`main.py:4825-4886`). Detection seed from `hermes_cli.runtime_provider._detect_api_mode_for_url`; rows are annotated ` [detected]`, ` [current]`, or ` [detected / current]`.
- **Inputs / options:** four rows, VERBATIM label + description:
  1. `Auto-detect` — `Use Hermes URL heuristics; best for standard OpenAI-compatible endpoints.` (value `""` → returns `None`)
  2. `Chat Completions` — `Use /chat/completions for standard OpenAI-compatible servers.` (value `chat_completions`)
  3. `Responses / Codex` — `Use /responses for Codex-compatible tool-calling backends.` (value `codex_responses`)
  4. `Anthropic Messages` — `Use /v1/messages for Anthropic-compatible endpoints.` (value `anthropic_messages`)
  Accepted typed answers: `1|auto|detect|auto-detect`, `2|chat|chat_completions|completions`, `3|responses|codex|codex_responses`, `4|anthropic|anthropic_messages|messages`; empty = keep current/detected.
- **Outputs / side effects:** writes `api_mode` on the custom provider entry.
- **Config / env:** `custom_providers[].api_mode`, `model.api_mode`.
- **Edge cases / guards:** unrecognised input prints `Invalid API mode choice: <raw>. Falling back to auto-detect.` and returns `None`; Ctrl-C/EOF prints `\nCancelled.` and re-raises.
- **Rebuild notes:** Store an explicit protocol enum; auto-detect only as the default.

### Provider picker — `Remove a saved custom provider`  `id: cli-a.model-remove-custom`
- **Surface:** CLI
- **Where:** Row labelled verbatim `Remove a saved custom provider` (only shown when `custom_providers:` is a non-empty list, `main.py:4142-4146`). Sub-picker title `Select provider to remove:`; header `Remove a custom provider:`.
- **What it does:** Deletes one saved custom endpoint from `config.yaml`.
- **How it works:** `_remove_custom_provider(config)` (`main.py:5011-5066`). Choices are `<name> (<host-without-scheme>)` plus a trailing `Cancel`; rendered with `hermes_cli.curses_ui.curses_radiolist(..., selected=0, cancel_returns=-1)`, falling back to a numbered `Choice [1-N]: ` prompt when curses raises `ImportError/NotImplementedError/OSError/SubprocessError`.
- **Inputs / options:** one row per saved provider, plus `Cancel`.
- **Outputs / side effects:** pops the entry from `custom_providers` and saves; prints `✅ Removed "<name>" from custom providers.` or `No change.` / `No custom providers configured.`
- **Config / env:** `custom_providers`.
- **Edge cases / guards:** an index beyond the list length is treated as cancel.
- **Rebuild notes:** List + delete on a YAML array; confirm by name in the success line.

### Provider picker — `Configure auxiliary models...`  `id: cli-a.model-aux-config-menu`
- **Surface:** CLI
- **Where:** Row labelled verbatim `Configure auxiliary models...`, second-to-last in the provider list (`main.py:4147`). Opens a looping menu.
- **What it does:** Routes Hermes' side tasks (vision, compression, titles, …) to a specific already-authenticated provider/model instead of inheriting the main chat model.
- **How it works:** `_aux_config_menu()` (`main.py:4510-4573`). Header block printed verbatim each loop:
  ```
    Auxiliary models — side-task routing

    Side tasks (vision, compression, web extraction, etc.) default
    to your main chat model.  "auto" means "use my main model" —
    Hermes only falls back to a lightweight backend (OpenRouter,
    Nous Portal) if the main model is unavailable.  Override a
    task below if you want it pinned to a specific provider/model.
  ```
  Each row is `<Name>` padded, then `(<description>)` padded, then the current setting rendered by `_format_aux_current` (`main.py:4371-4386`) as one of `auto`, `auto · <model>`, `<provider>`, `<provider> · <model>`, `custom (<host>)`, `custom (<host>) · <model>`.
- **Inputs / options:** menu rows — the 13 built-in auxiliary tasks from `_AUX_TASKS` (`main.py:4402-4416`), VERBATIM `(key, Name, description)`:
  `vision` / `Vision` / `image/screenshot analysis`;
  `compression` / `Compression` / `context summarization`;
  `approval` / `Approval` / `smart command approval`;
  `mcp` / `MCP` / `MCP tool reasoning`;
  `title_generation` / `Title generation` / `session titles`;
  `review` / `Review` / `/review reviewer subagent`;
  `memory_query_rewrite` / `Memory query rewrite` / `memory retrieval queries`;
  `tts_audio_tags` / `TTS audio tags` / `Gemini TTS tag insertion`;
  `skills_hub` / `Skills hub` / `skills search/install`;
  `triage_specifier` / `Triage specifier` / `kanban spec fleshing`;
  `kanban_decomposer` / `Kanban decomposer` / `task decomposition`;
  `profile_describer` / `Profile describer` / `auto profile descriptions`;
  `curator` / `Curator` / `skill-usage review pass`;
  plus any plugin-registered task (`get_plugin_auxiliary_tasks`, `main.py:4350-4368`), plus the special row `Delegation` / `subagent model (delegate_task)` (`_DELEGATION_TASK_KEY = "delegation"`, `main.py:4345-4347`), plus `Reset all to auto` and `Back`.
- **Outputs / side effects:** writes `auxiliary.<task>.{provider,model,base_url,api_key}` (or top-level `delegation.*` for the delegation row) via `_save_aux_choice` (`main.py:4413-4457`); `timeout`/`download_timeout` and other task settings are preserved untouched.
- **Config / env:** `auxiliary.*`, `delegation.*`.
- **Edge cases / guards:** `Reset all to auto` calls `_reset_aux_to_auto()` (`main.py:4460-4508`) and prints `Reset <n> auxiliary task(s) to auto.` or `All auxiliary tasks were already set to auto.`; delegation stores `auto` as an EMPTY provider string (never the literal `auto`, which would be resolved as a provider name).
- **Rebuild notes:** A per-task routing table `{provider, model, base_url, api_key}` with `auto` meaning "inherit"; keep non-routing task settings separate so a reset never clobbers them.

### Auxiliary task picker (per task)  `id: cli-a.model-aux-task-picker`
- **Surface:** CLI
- **Where:** Second screen of the aux menu. Header: `  Configure <Display name> — current: <rendered current>`.
- **What it does:** Chooses the provider (and then model) for one auxiliary task.
- **How it works:** `_aux_select_for_task(task)` (`main.py:4575-4657`). Provider rows come from `hermes_cli.inventory.build_aux_picker_rows(current_provider, current_model, current_base_url)` + `format_aux_picker_entries(...)` — only already-configured providers, so nothing here runs credential setup.
- **Inputs / options:** `auto (recommended)` (or `auto (inherit main agent)` for the Delegation row) — always first and marked `  ← current` when active; then one row per authenticated provider; then `Custom endpoint (direct URL)` (marked `  ← current` when a base_url is set); then `Back`.
- **Outputs / side effects:** `__auto__` prints `<Display name>: reset to auto.`; a provider row goes to `_aux_flow_provider_model` which prints `<Display name>: <provider> · <model>` or `<Display name>: <provider> (provider default model)`; `__custom__` goes to `_aux_flow_custom_endpoint`.
- **Config / env:** `auxiliary.<task>` / `delegation`.
- **Edge cases / guards:** if provider detection raises, prints `Could not detect authenticated providers: <exc>` and shows only auto/custom/back. With no curated model list it prints `No curated model list for <provider>.` then `Enter a model slug manually (blank = use provider default):` and a `Model: ` line prompt.
- **Rebuild notes:** Reuse the authenticated-provider inventory rather than re-running auth.

### Auxiliary task — `Custom endpoint (direct URL)` flow  `id: cli-a.model-aux-custom-endpoint`
- **Surface:** CLI
- **Where:** Reached from the aux task picker. Header verbatim:
  ```
    Custom endpoint for <Display name>
    Provide an OpenAI-compatible base URL (e.g. http://localhost:11434/v1)
  ```
- **What it does:** Points one auxiliary task at a raw OpenAI-compatible URL with optional key and model.
- **How it works:** `_aux_flow_custom_endpoint` (`main.py:4700-4766`). Three prompts: `Base URL [<current>]: ` (or `Base URL: `), `Model slug (optional) [<current>]: ` (or `Model slug (optional): `), and a masked `API key (optional, blank = use OPENAI_API_KEY): ` via `hermes_cli.secret_prompt.masked_secret_prompt`.
- **Inputs / options:** base URL (required), model slug (optional), API key (optional, masked).
- **Outputs / side effects:** saves `provider: custom` plus `model`, `base_url`, `api_key` on the task; prints `<Display name>: custom (<host>)` optionally ` · <model>`.
- **Config / env:** `auxiliary.<task>.{provider,model,base_url,api_key}`; falls back to `OPENAI_API_KEY` when no key is entered.
- **Edge cases / guards:** empty URL with no previous value prints `No URL provided. No change.`; Ctrl-C/EOF at any prompt returns silently.
- **Rebuild notes:** Same shape as the main custom provider, scoped to one task.

### Picker keyboard navigation (curses radiolist)  `id: cli-a.model-picker-keys`
- **Surface:** CLI
- **Where:** Every `hermes model` / `hermes fallback remove` / `hermes moa configure` menu.
- **What it does:** Arrow-key single-select with a typed-number fallback.
- **How it works:** `_prompt_provider_choice` (`main.py:4770-4806`) → `hermes_cli.setup._curses_prompt_choice` (`setup.py:316-326`) → `hermes_cli.curses_ui.curses_radiolist(question, choices, selected=default, cancel_returns=-1)`. Key decoding in `_decode_menu_key` (`curses_ui.py:570-627`) and `_enhanced_key_action` (CSI-u).
- **Inputs / options:** `↑` / `k` = up; `↓` / `j` = down (both wrap); `←` = back; `Enter` (also codes 10/13) = select; `Space` = toggle; `q` = cancel; `Esc` = cancel (a lone ESC after a 60 ms wait; ESC+`[`/`O` is parsed as a CSI/SS3 sequence instead); `Ctrl+C` (code 3, or `c`/`C` with the CSI-u Ctrl bit) = interrupt; `/` opens a type-to-filter search when the menu is `searchable` — inside search, `Esc` clears the query and exits search, `Backspace` deletes a character, printable characters extend the filter (`_handle_active_search_key`, `curses_ui.py:411-444`).
- **Outputs / side effects:** returns the ORIGINAL item index even when filtered.
- **Config / env:** n/a.
- **Edge cases / guards:** when curses is unavailable (piped stdin, no TTY) the fallback prints `Select provider:` then `  <marker> <n>. <label>` rows with `→` on the default and asks `Choice [1-<N>] (<default+1>): `; invalid entries print `Please enter 1-<N>` or `Please enter a number`; Ctrl-C/EOF returns `None`.
- **Rebuild notes:** One shared menu loop with a non-curses fallback; never let a cancel be mistaken for a selection.

### Post-switch cleanup — stale `OPENAI_BASE_URL`  `id: cli-a.model-clear-stale-base-url`
- **Surface:** CLI
- **Where:** Runs silently at the end of every `hermes model` provider switch that is not `custom`/`cancel`/`remove-custom`.
- **What it does:** Removes a leftover `OPENAI_BASE_URL` from `~/.hermes/.env` so auxiliary clients using `provider: auto` do not keep routing to the previous custom endpoint.
- **How it works:** `_clear_stale_openai_base_url()` (`main.py:4279-4308`), called at `main.py:4266-4275`. Reads `model.provider`; returns early when it is `custom` or empty; otherwise `save_env_value("OPENAI_BASE_URL", "")`.
- **Inputs / options:** none.
- **Outputs / side effects:** prints `Cleared stale OPENAI_BASE_URL from .env (was: <first 40 chars>...)` (or the full value when shorter than 40 chars); rewrites `~/.hermes/.env`.
- **Config / env:** `OPENAI_BASE_URL`, `model.provider`.
- **Edge cases / guards:** issue #5161 — the bug this exists to fix.
- **Rebuild notes:** Treat endpoint overrides as provider-scoped, not global env.

## D. `hermes moa` — Mixture of Agents presets

### `hermes moa` (command group)  `id: cli-a.moa`
- **Surface:** CLI
- **Where:** `hermes moa`; top-level help entry `Configure Mixture of Agents provider/model slots`; command description verbatim `Configure the provider/model set used by /moa <prompt>.`
- **What it does:** Manages named Mixture-of-Agents presets — a set of "reference" advisor models plus one "aggregator" model that acts on their advice.
- **How it works:** parser at `hermes_cli/main.py:13225-13238`, dispatcher `cmd_moa` at `hermes_cli/moa_cmd.py:93-152`. With no subcommand, `sub` defaults to `"list"` (`moa_cmd.py:96`). Presets live under `moa:` in `config.yaml`, normalised by `hermes_cli/moa_config.py:372-423`.
- **Inputs / options:** subcommands `list` (alias `ls`), `configure` (alias `config`), `delete` (alias `rm`); `-h/--help`.
- **Outputs / side effects:** reads/writes `config.yaml → moa`.
- **Config / env:** `moa.presets`, `moa.default_preset`, `moa.active_preset`, `moa.privacy_filter`, `auxiliary.moa_reference.timeout`.
- **Edge cases / guards:** an unknown subcommand raises `SystemExit(f"Unknown moa subcommand: {sub}")`.
- **Rebuild notes:** Named presets, each `{reference_models[], aggregator, sampling knobs}`; expose them as pseudo-models under a virtual provider.

### `hermes moa list` / `hermes moa ls`  `id: cli-a.moa-list`
- **Surface:** CLI
- **Where:** `hermes moa list`, `hermes moa ls`, or bare `hermes moa`; help verbatim `Show current MoA model slots`.
- **What it does:** Prints every preset with its reference models and aggregator.
- **How it works:** `_print_config` (`moa_cmd.py:77-90`). Output shape, verbatim:
  ```
  Mixture of Agents presets
  Default: <default_preset>
  Active in config: <active_preset or (off)>

  <marker> <preset name>
    Reference models:
      1. <provider>:<model>[ [reasoning=<effort>]]
      ...
    Aggregator: <provider>:<model>[ [reasoning=<effort>]]
  ```
  `<marker>` is `*` for the default preset and a space otherwise (`_format_slot`, `moa_cmd.py:71-75`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout only.
- **Config / env:** `moa.*`.
- **Edge cases / guards:** with no `moa:` section the defaults are synthesised: preset `default` with reference models `openai-codex:gpt-5.5` and `openrouter:deepseek/deepseek-v4-pro`, aggregator `openrouter:anthropic/claude-opus-4.8` (`moa_config.py:14-22`).
- **Rebuild notes:** Read-only formatter over the normalised config.

### `hermes moa configure [name]` / `hermes moa config [name]`  `id: cli-a.moa-configure`
- **Surface:** CLI
- **Where:** `hermes moa configure`, `hermes moa configure fastlane`; help verbatim `Interactively pick MoA models`; positional help `Preset name to create or update`.
- **What it does:** Walks you through picking one or more reference models and then the aggregator for a named preset, saving the result.
- **How it works:** `cmd_moa` branch at `moa_cmd.py:102-129`. Preset name = positional `name` → `moa.default_preset` → `DEFAULT_MOA_PRESET_NAME` (`"default"`). Prints `Configure MoA preset: <name>` and `Pick at least one reference model; choose Done when finished.` Each slot uses `_pick_slot` (`moa_cmd.py:51-69`): a `Select provider` menu whose rows are `<provider name>  (<slug>)`, then a `Select model for <slug>` menu. Provider list from `build_models_payload(load_picker_context(), include_unconfigured=False, picker_hints=True, canonical_order=True, pricing=True, capabilities=True, max_models=200)` with the `moa` slug itself filtered out (`_model_options`, `moa_cmd.py:29-49`). Between slots it asks `Add another reference model?` with rows `Add another` / `Done` (default index 1 = Done). Then prints `Configure aggregator model.` and runs one more `_pick_slot`.
- **Inputs / options:** optional positional `name`; `-h/--help`. Menu answers: provider index, model index, `Add another` / `Done`.
- **Outputs / side effects:** writes `moa.presets[<name>]`, sets `moa.default_preset` if unset, saves `config.yaml`, prints `Saved MoA preset: <name>` then the full `moa list` output.
- **Config / env:** `moa.presets.<name>.reference_models[]`, `.aggregator`, `moa.default_preset`.
- **Edge cases / guards:** raises `RuntimeError("No configured model providers found. Run \`hermes model\` first.")` when nothing is authenticated, and `RuntimeError(f"Provider {slug} has no selectable models")` for an empty model list. `_prompt_choice` (`moa_cmd.py:12-26`) uses `curses_radiolist(..., cancel_returns=default)` — cancelling keeps the default row — and falls back to a numbered list with `<title> [<default+1>]: `. The `enabled` flag of an existing slot is preserved onto the newly picked one.
- **Rebuild notes:** Loop "pick provider → pick model → add another?" then one aggregator; persist and echo the whole config back.

### `hermes moa delete <name>` / `hermes moa rm <name>`  `id: cli-a.moa-delete`
- **Surface:** CLI
- **Where:** `hermes moa delete fastlane`; help verbatim `Delete a MoA preset`; positional help `Preset name to delete`.
- **What it does:** Removes a named preset.
- **How it works:** `moa_cmd.py:131-149`. Deletes `moa.presets[name]`; if it was `default_preset`, the first remaining key becomes the default; if it was `active_preset`, that is cleared to `""`; then re-normalises and saves.
- **Inputs / options:** required positional `name`; `-h/--help`.
- **Outputs / side effects:** rewrites `config.yaml`; prints `Deleted MoA preset: <name>`.
- **Config / env:** `moa.presets`, `moa.default_preset`, `moa.active_preset`.
- **Edge cases / guards:** `SystemExit("Usage: hermes moa delete <name>")` when the name is blank; `SystemExit(f"Unknown MoA preset: {name}")` when it does not exist; `SystemExit("Cannot delete the only MoA preset")` when one preset remains.
- **Rebuild notes:** Delete + repoint default/active in one transaction.

### MoA preset schema (what `configure` writes)  `id: cli-a.moa-preset-schema`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml → moa:`; surfaced in `hermes moa list` and in every model picker as the `Mixture of Agents` provider.
- **What it does:** Defines one MoA execution mode: which advisors run, which model acts, and the sampling/timeout policy.
- **How it works:** `_normalize_preset` (`moa_config.py:313-369`) and `normalize_moa_config` (`moa_config.py:372-423`). The normaliser also emits a flattened compatibility view (`reference_models`, `aggregator`, `reference_temperature`, `aggregator_temperature`, `reference_timeout`, `degraded_reference_policy`, `max_tokens`, `reference_max_tokens`, `fanout`, `enabled`) mirroring the DEFAULT preset, for the dashboard and desktop callers.
- **Inputs / options:** per-preset fields, with defaults:
  - `enabled` (bool, default `true`)
  - `reference_models` (list of `{provider, model, enabled, reasoning_effort?}`; a JSON string or a single mapping is accepted and coerced; empty falls back to the two built-in defaults)
  - `aggregator` (`{provider, model, reasoning_effort?}`; default `openrouter:anthropic/claude-opus-4.8`)
  - `reference_temperature` (float or `None` = don't send the parameter)
  - `aggregator_temperature` (float or `None`)
  - `reference_timeout` (finite positive float, else `None` = inherit `auxiliary.moa_reference.timeout`, 900 s by default)
  - `degraded_reference_policy` — `loud` (default) or `silent`; unknown values become `loud`
  - `max_tokens` (int, default `4096`)
  - `reference_max_tokens` (positive int or `None` = uncapped advisors)
  - `fanout` — `user_turn` (default), `per_iteration`, or `every_n:<N>` with N ≥ 2; also accepts `{mode: every_n, n: N}`; `every_n:1` collapses to `per_iteration`; anything unparseable falls back to `user_turn`
  Top-level (not per-preset) fields: `default_preset`, `active_preset` (cleared to `""` when it names a missing preset), `privacy_filter` (`''` off / `display` / `full`).
- **Outputs / side effects:** consumed by the MoA runtime and by `/moa <prompt>` (which encodes a hidden turn marker `__HERMES_MOA_TURN_V1__<base64 json>` — `moa_config.py:478-487`).
- **Config / env:** `moa.*`, `auxiliary.moa_reference.timeout`.
- **Edge cases / guards:** `resolve_moa_preset` raises `MoAPresetNotFoundError` with `MoA preset '<name>' was not found. Available presets: <list>. Run \`hermes moa list\`.`; a legacy flat `moa:` block (with `reference_models`/`aggregator` at the top) is migrated into a preset named `default`; `exact_moa_preset_name` refuses to implicitly match a preset whose `enabled` is false.
- **Rebuild notes:** Normalise aggressively and tolerate hand-edited YAML; keep a flattened view for older consumers.

## E. `hermes fallback` — fallback provider chain

### `hermes fallback` (command group)  `id: cli-a.fallback`
- **Surface:** CLI
- **Where:** `hermes fallback`; top-level help entry `Manage fallback providers (tried when the primary model fails)`; description verbatim: `Manage the fallback provider chain.  Fallback providers are tried in order when the primary model fails with rate-limit, overload, or connection errors.  See: https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers`
- **What it does:** Maintains an ordered list of provider+model pairs Hermes tries when the primary model fails with a rate-limit, overload, or connection error.
- **How it works:** parser at `hermes_cli/main.py:13243-13273`, dispatcher `cmd_fallback` at `hermes_cli/fallback_cmd.py:363-377`. No subcommand = `list`.
- **Inputs / options:** subcommands `list` (alias `ls`), `add`, `remove` (alias `rm`), `clear`; `-h/--help`.
- **Outputs / side effects:** reads/writes `fallback_providers` in `~/.hermes/config.yaml`.
- **Config / env:** `fallback_providers`, legacy `fallback_model`; per-entry `api_key` / `key_env` / `api_key_env`.
- **Edge cases / guards:** an unknown subcommand prints `Unknown fallback subcommand: <sub>` then `Use one of: list, add, remove, clear` and raises `SystemExit(2)`.
- **Rebuild notes:** An ordered list of backends with identity semantics (provider+model+base_url); retry the next one on retriable failures only.

### `hermes fallback list` / `hermes fallback ls`  `id: cli-a.fallback-list`
- **Surface:** CLI
- **Where:** `hermes fallback list`, `hermes fallback ls`, or bare `hermes fallback`; help verbatim `Show the current fallback chain (default when no subcommand)`.
- **What it does:** Prints the primary model and the ordered fallback chain.
- **How it works:** `cmd_fallback_list` (`fallback_cmd.py:107-133`). Entry rendering `_format_entry` = `<model>  (via <provider>)` plus `  [<base_url>]` when a base URL is set (`fallback_cmd.py:49-56`). Primary rendering `_describe_primary` = `<model>  (via <provider>)` from `model.default`/`model.model` + `model.provider` (`fallback_cmd.py:136-145`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout. Empty chain prints:
  ```
    No fallback providers configured.

    Add one with:  hermes fallback add
  ```
  A populated chain prints `  Primary:   <…>`, `  Fallback chain (<N> entry|entries):`, numbered rows `    <i>. <entry>`, then `  Tried in order when the primary fails (rate-limit, 5xx, connection errors).` and `  Docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers`.
- **Config / env:** `fallback_providers`, `fallback_model`, `model.*`.
- **Edge cases / guards:** singular/plural of `entry`/`entries` is handled explicitly.
- **Rebuild notes:** Read-only view over the merged chain.

### `hermes fallback add`  `id: cli-a.fallback-add`
- **Surface:** CLI
- **Where:** `hermes fallback add`; help verbatim `Pick a provider + model (same picker as \`hermes model\`) and append to the chain`.
- **What it does:** Runs the full `hermes model` picker, then appends whatever you picked to the fallback chain instead of making it your primary.
- **How it works:** `cmd_fallback_add` (`fallback_cmd.py:148-243`). Calls `_require_tty("fallback add")`, snapshots `config["model"]` and the auth store's `active_provider`, prints the banner
  ```
    Adding a fallback provider.  The picker below is the same one used by
    `hermes model` — select the provider + model you want as a fallback.
  ```
  then runs `select_provider_and_model(args=args)`. Afterwards it reads the picker's result out of `config["model"]` (`_extract_fallback_from_model_cfg`, `fallback_cmd.py:59-76`), RESTORES the previous `model` block and `active_provider`, reloads the config, and appends `{provider, model, base_url?, api_mode?}` to `fallback_providers`.
- **Inputs / options:** none of its own; every prompt belongs to the shared picker.
- **Outputs / side effects:** writes `fallback_providers` and drops the legacy `fallback_model` key (`_write_chain`, `fallback_cmd.py:42-47`); prints `  Added fallback: <entry>`, `  Chain is now <N> entry|entries long.`, and `  Run \`hermes fallback list\` to view, or \`hermes fallback remove\` to delete.`
- **Config / env:** `fallback_providers`, `model.*`, auth store `active_provider`.
- **Edge cases / guards:** cancelling the picker restores state and prints `  No fallback added.`; picking the current primary prints `  Selected model matches the current primary (<entry>).` and `  A provider cannot be a fallback for itself — no change.`; an exact duplicate prints `  <entry> is already in the fallback chain — skipped.` Identity uses `agent.backend_identity.BackendIdentity.build` + `same_deployment`, so the same provider+model on a DIFFERENT explicit base URL is a legitimate distinct entry. A `SystemExit` from a provider flow restores state before re-raising.
- **Rebuild notes:** Reuse the primary picker but capture-and-revert the primary; compare backends by (provider, model, base_url) identity, not string equality.

### `hermes fallback remove` / `hermes fallback rm`  `id: cli-a.fallback-remove`
- **Surface:** CLI
- **Where:** `hermes fallback remove`; help verbatim `Pick an entry to delete from the chain`. Picker title: `Select a fallback to remove:`.
- **What it does:** Deletes one entry from the chain via a menu.
- **How it works:** `cmd_fallback_remove` (`fallback_cmd.py:257-303`). Choices are the formatted entries plus a trailing `Cancel`; rendered with `_curses_prompt_choice`, falling back to `_numbered_pick` (`fallback_cmd.py:340-360`) which prints `Select a fallback to remove:` then `  <n>. <label>` rows and asks `Choice [1-<N>]: `.
- **Inputs / options:** `-h/--help`; the menu selection.
- **Outputs / side effects:** rewrites `fallback_providers`; prints `  Removed fallback: <entry>` plus `  Chain is now <N> entry|entries long.` or `  Fallback chain is now empty.`
- **Config / env:** `fallback_providers`.
- **Edge cases / guards:** empty chain prints `  No fallback providers configured — nothing to remove.`; selecting `Cancel` (or an out-of-range index) prints `  Cancelled — no change.`; blank input in the numbered fallback returns `None` = cancel; invalid input prints `Please enter 1-<N>` / `Please enter a number`.
- **Rebuild notes:** Index-based removal on the merged chain, then persist the merged result.

### `hermes fallback clear`  `id: cli-a.fallback-clear`
- **Surface:** CLI
- **Where:** `hermes fallback clear`; help verbatim `Remove all fallback entries`.
- **What it does:** Empties the whole chain after a yes/no confirmation.
- **How it works:** `cmd_fallback_clear` (`fallback_cmd.py:306-337`). Prints the current chain, then asks `  Clear all entries? [y/N]: `; only `y`/`yes` proceeds.
- **Inputs / options:** `-h/--help`; the confirmation answer.
- **Outputs / side effects:** sets `fallback_providers: []` and removes `fallback_model`; prints `  Fallback chain cleared.`
- **Config / env:** `fallback_providers`.
- **Edge cases / guards:** empty chain prints `  No fallback providers configured — nothing to clear.`; anything but y/yes prints `  Cancelled — no change.`; Ctrl-C/EOF prints `  Cancelled.`
- **Rebuild notes:** Destructive op behind an explicit confirmation that first shows what will be lost.

### Fallback chain storage and merge rules  `id: cli-a.fallback-storage`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml → fallback_providers:` (list) and the legacy `fallback_model:` (single dict).
- **What it does:** Defines the effective ordered chain the runtime consults.
- **How it works:** `get_fallback_chain` (`hermes_cli/fallback_config.py:81-101`) walks `fallback_providers` first, then `fallback_model`, skipping entries whose `(provider, model, base_url)` identity was already seen (`_entry_identity`, `fallback_config.py:72-78`). `_iter_fallback_entries` (`fallback_config.py:44-69`) drops entries missing `provider` or `model` and normalises `base_url` by stripping whitespace and a trailing `/`.
- **Inputs / options:** per-entry fields `provider` (required), `model` (required), `base_url` (optional, normalised), `api_mode` (optional), `api_key` (optional inline), `key_env` / `api_key_env` (optional env-var name).
- **Outputs / side effects:** list of fresh dict copies; callers may mutate safely.
- **Config / env:** the named env var is read through `agent.secret_scope.get_secret` — NOT a raw `os.getenv` — so a multiplexed gateway cannot leak another profile's credential (`fallback_config.py:14-41`).
- **Edge cases / guards:** `resolve_entry_api_key` returns `None` when neither inline key nor env var yields a value, letting the provider's normal credential resolution take over.
- **Rebuild notes:** One canonical list; migrate the legacy scalar on first write; resolve secrets through a scope-aware accessor.

## F. `hermes worktree` — audit and reclaim git worktrees

### `hermes worktree` (command group)  `id: cli-a.worktree`
- **Surface:** CLI
- **Where:** `hermes worktree`; top-level help `Audit and reclaim accumulated git worktrees and merged branches`; description verbatim: `Attended reclaim for the .worktrees/ directory hermes -w sessions accumulate. Never deletes uncommitted tracked changes, unique unpushed commits, or in-use trees; untracked-only scratch is archived to ~/.hermes/archive/worktree-prune/ before removal. See: https://hermes-agent.nousresearch.com/docs/user-guide/cli#worktree-cleanup`
- **What it does:** Classifies and (on request) removes the disposable worktrees that `hermes -w` accumulates under `<repo>/.worktrees/`, plus fully-merged local branches.
- **How it works:** parser at `hermes_cli/main.py:13278-13320`, dispatcher `_dispatch_worktree` (`main.py:13322-13332`) which rewrites the aliases `ls`/`audit` to `list` before calling `cmd_worktree` (`hermes_cli/worktree_cmd.py:29-99`). Policy lives in `hermes_cli/worktree_gc.py`.
- **Inputs / options:** subcommands `list` (aliases `ls`, `audit`), `prune`; `-h/--help`.
- **Outputs / side effects:** may remove worktrees, delete branches, and archive untracked files.
- **Config / env:** none directly; uses the git repo discovered by `cli._git_repo_root()`.
- **Edge cases / guards:** outside a git repo prints `Not inside a git repository (or pass --repo <path>).` and returns 1. An unknown action prints `Unknown worktree action: <action>` and returns 1.
- **Rebuild notes:** Separate the (pure, read-only) audit from the destructive reclaim, and feed the reclaim a frozen record list so concurrent sessions cannot be caught in the sweep.

### `hermes worktree list` (aliases `ls`, `audit`)  `id: cli-a.worktree-list`
- **Surface:** CLI
- **Where:** `hermes worktree list` / `ls` / `audit`; help verbatim `Classify every tree: age, size, verdict, reason (default action)`.
- **What it does:** Prints one row per worktree with age, size, verdict, and reason, plus totals and a branch-deletion preview. Changes nothing.
- **How it works:** `cmd_worktree` action `list` (`worktree_cmd.py:41-77`) → `worktree_gc.audit_worktrees(repo_root)` (`worktree_gc.py:170-259`). Header line verbatim: `{'TREE':32} {'AGE':>6} {'SIZE':>6} {'VERDICT':13} REASON`. Rows are sorted by descending size; size is `du -sm` formatted by `_fmt_size` as `<n>M`, `<n.n>G`, or `?`. Footer: `\n<N> tree(s), <size> total — <size> reclaimable now via \`hermes worktree prune\`.` and, when applicable, `<n> local branch(es) fully merged/patch-equivalent upstream would also be deleted.`
- **Inputs / options:** `-h/--help`; `--repo REPO` (help verbatim `Repo root (default: current repo)`).
- **Outputs / side effects:** read-only, except that a shallow repo is deepened blobless-ly first (`_repo_is_shallow` / `_deepen_shallow_repo`) and the merge-verdict cache is saved when it changed.
- **Config / env:** n/a.
- **Edge cases / guards:** prints `No worktrees under .worktrees/ — nothing to reclaim.` when the directory is missing or empty.
- **Rebuild notes:** Classify with fail-safe defaults (a failing git call must mean "keep").

### `hermes worktree list --repo REPO`  `id: cli-a.worktree-list-repo`
- **Surface:** CLI
- **Where:** `hermes worktree list --repo /path/to/repo`; help verbatim `Repo root (default: current repo)`.
- **What it does:** Audits a repository other than the current working directory's.
- **How it works:** `main.py:13298`; `worktree_cmd.py:33` uses `getattr(args, "repo", None) or _repo_root()`.
- **Inputs / options:** filesystem path.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** a path without `.worktrees/` yields the "nothing to reclaim" message.
- **Rebuild notes:** Explicit root beats implicit cwd discovery.

### `hermes worktree prune`  `id: cli-a.worktree-prune`
- **Surface:** CLI
- **Where:** `hermes worktree prune`; help verbatim `Remove safe trees and delete fully-merged local branches`.
- **What it does:** Removes every worktree the audit marked reapable and deletes every local branch whose commits are all upstream.
- **How it works:** `cmd_worktree` action `prune` (`worktree_cmd.py:79-97`). Unless `--branches-only`, it runs `audit_worktrees(repo_root, with_sizes=False)` then `reclaim_worktrees(repo_root, dry_run=…, records=…)` (`worktree_gc.py:266-330`); unless `--trees-only`, it runs `reclaim_branches(repo_root, dry_run=…)` (`worktree_gc.py:415-437`). Preserved trees that carry real work are listed first as `Preserved <n> tree(s) with real work:` followed by `  <name>: <reason>` (kanban trees and in-use trees are excluded from that list).
- **Inputs / options:** `-h/--help`, `--repo REPO`, `--dry-run`, `--trees-only`, `--branches-only`.
- **Outputs / side effects:** per-action lines prefixed by two spaces, from the reclaim functions: `would remove <name> (<reason>)`, `archived <n> untracked file(s) → <archive dir>`, `kept <name> (archive of untracked files failed)`, `removed <name>`, `removed <name> (branch <branch> kept — pushed open-PR lane)`, `failed to remove <name>: <stderr>`, `would delete branch <name> (<reason>)`, `deleted branch <name>`, `failed to delete <name>: <stderr>`. Then `<N> action(s) planned.` (dry run) or `<N> action(s) done.`, or `Nothing to reclaim — all trees/branches carry real work or are in use.` A final `git worktree prune` runs when not a dry run.
- **Config / env:** archives land in `~/.hermes/archive/worktree-prune/<tree name>-<YYYYmmdd-HHMMSS>/`.
- **Edge cases / guards:** dead-pid locks are `git worktree unlock`ed before `git worktree remove --force`; the branch is deleted only AFTER a successful tree removal, and never for `main`, `master`, `develop`, `dev`, `trunk` (`_PROTECTED_BRANCHES`).
- **Rebuild notes:** Archive before destroy; gate branch deletion on tree removal success.

### `hermes worktree prune --repo REPO`  `id: cli-a.worktree-prune-repo`
- **Surface:** CLI
- **Where:** `hermes worktree prune --repo /path/to/repo`; help verbatim `Repo root (default: current repo)`.
- **What it does:** Prunes a repository other than the current one.
- **How it works:** `main.py:13303`.
- **Inputs / options:** filesystem path.
- **Outputs / side effects:** as `prune`.
- **Config / env:** n/a.
- **Edge cases / guards:** same repo-discovery error as `list`.
- **Rebuild notes:** n/a.

### `hermes worktree prune --dry-run`  `id: cli-a.worktree-prune-dry-run`
- **Surface:** CLI
- **Where:** `hermes worktree prune --dry-run`; help verbatim `Show the plan without changing anything`.
- **What it does:** Prints exactly what would be removed/deleted, changing nothing.
- **How it works:** `main.py:13304-13307`; `reclaim_worktrees`/`reclaim_branches` short-circuit to `would remove …` / `would delete branch …` strings and skip the final `git worktree prune`.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** stdout only; the trailing verb becomes `planned`.
- **Config / env:** n/a.
- **Edge cases / guards:** the audit itself may still deepen a shallow repo and write the merge cache.
- **Rebuild notes:** Same code path, one boolean.

### `hermes worktree prune --trees-only`  `id: cli-a.worktree-prune-trees-only`
- **Surface:** CLI
- **Where:** `hermes worktree prune --trees-only`; help verbatim `Only remove worktrees; leave local branches alone`.
- **What it does:** Skips the branch reclaim pass.
- **How it works:** `main.py:13308-13311`; `worktree_cmd.py:95-96` guards `reclaim_branches` with `if not trees_only`.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** only tree actions are printed.
- **Config / env:** n/a.
- **Edge cases / guards:** combining with `--branches-only` results in neither pass running.
- **Rebuild notes:** Two independent passes behind two flags.

### `hermes worktree prune --branches-only`  `id: cli-a.worktree-prune-branches-only`
- **Surface:** CLI
- **Where:** `hermes worktree prune --branches-only`; help verbatim `Only delete merged local branches; leave worktrees alone`.
- **What it does:** Skips the worktree removal pass.
- **How it works:** `main.py:13312-13315`; `worktree_cmd.py:85` guards the tree pass with `if not branches_only`.
- **Inputs / options:** boolean flag.
- **Outputs / side effects:** only branch actions are printed.
- **Config / env:** n/a.
- **Edge cases / guards:** as above.
- **Rebuild notes:** n/a.

### Worktree verdicts (audit classification)  `id: cli-a.worktree-verdicts`
- **Surface:** CLI
- **Where:** The `VERDICT` / `REASON` columns of `hermes worktree list`.
- **What it does:** Encodes exactly why a tree is safe or unsafe to remove.
- **How it works:** `audit_worktrees` (`worktree_gc.py:170-259`) evaluates, in order: kanban-owned name, live lock, tracked dirt, unpushed commits (with `git cherry` patch-equivalence and a pushed-exact probe), untracked scratch.
- **Inputs / options:** verdict/reason strings, VERBATIM:
  - `keep` / `kanban task tree (owned by kanban gc)` — name matches `^t_[0-9a-f]+$`
  - `keep` / `in use by a running hermes session` — the worktree lock's owning pid is alive
  - `keep` / `uncommitted tracked changes (real work)`
  - `keep` / `unpushed commits not found upstream`
  - `reap-keep-branch` / `pushed to origin (open-PR lane); branch kept`
  - `reap-keep-branch` / `pushed to origin (open-PR lane); branch kept; <n> untracked file(s) will be archived`
  - `reap-archive` / `merged/pushed; <n> untracked file(s) will be archived`
  - `reap` / `clean and fully merged/pushed`
- **Outputs / side effects:** `_REAP_VERDICTS = {"reap", "reap-archive", "reap-keep-branch"}` are the only ones `reclaim_worktrees` acts on.
- **Config / env:** `_MAX_CHERRY_AHEAD = 50` bounds the cherry probe; `_KANBAN_RE = ^t_[0-9a-f]+$`.
- **Edge cases / guards:** a nonzero/timed-out git call (`_git` returns returncode 124 on timeout) always degrades to `keep`; offline (`git ls-remote` unavailable) degrades every pushed-tier verdict to keep.
- **Rebuild notes:** Enumerate verdicts as data so the UI, the pruner, and the tests share one vocabulary.

### Branch verdicts (audit classification)  `id: cli-a.worktree-branch-verdicts`
- **Surface:** CLI
- **Where:** Counted in `hermes worktree list` and acted on by `hermes worktree prune`.
- **What it does:** Decides which local branches lose nothing when deleted.
- **How it works:** `audit_branches` (`worktree_gc.py:332-413`). Upstream is the first of `origin/HEAD`, `origin/main`, `origin/master` that resolves; if none does, the function returns an empty list. Branches checked out in any worktree (`git worktree list --porcelain`) are excluded. Classification runs in a thread pool of up to `min(8, cpu_count, len(branches))` workers.
- **Inputs / options:** verdict/reason strings, VERBATIM:
  - `keep` / `protected or checked out`
  - `delete` / `fully merged into <upstream>`
  - `delete` / `no commits beyond <upstream>`
  - `keep` / `<n> commits ahead (stale-base lane)` (more than 50 ahead)
  - `keep` / `could not verify (git cherry failed)`
  - `delete` / `all commits patch-equivalent upstream`
  - `keep` / `<n> unique commit(s) not upstream`
- **Outputs / side effects:** `reclaim_branches` runs `git branch -D <name>` for `delete` verdicts.
- **Config / env:** `_PROTECTED_BRANCHES = {main, master, develop, dev, trunk}`.
- **Edge cases / guards:** deletion is content-gated (reachability), never name-gated.
- **Rebuild notes:** `git cherry` patch-equivalence is what catches rebase/squash merges that `--merged` misses.

### Untracked-scratch archive  `id: cli-a.worktree-archive`
- **Surface:** CLI
- **Where:** Printed as `archived <n> untracked file(s) → <path>` during `hermes worktree prune`.
- **What it does:** Copies a doomed tree's untracked files somewhere safe before the tree is removed.
- **How it works:** `_archive_untracked` (`worktree_gc.py:141-167`). Destination `~/.hermes/archive/worktree-prune/<tree name>-<%Y%m%d-%H%M%S>/`, preserving relative paths; directories use `copytree(dirs_exist_ok=True)`, files use `copy2`; symlinks and missing paths are skipped.
- **Inputs / options:** the untracked path list captured by `_dirty_split` (lines beginning `??` in `git status --porcelain`).
- **Outputs / side effects:** a timestamped archive directory; on any failure it returns `None` and the tree is KEPT with `kept <name> (archive of untracked files failed)`.
- **Config / env:** `~/.hermes/archive/worktree-prune/`.
- **Edge cases / guards:** never destroys — an archive failure aborts that tree's removal.
- **Rebuild notes:** Copy-then-delete, never delete-then-hope.

## G. `hermes browser` — real-profile browsing helpers

### `hermes browser` (command group)  `id: cli-a.browser`
- **Surface:** CLI
- **Where:** `hermes browser`; top-level help `Real-profile browsing helpers (close a browser locking its profile)`; description verbatim: `Helpers for real-profile browsing (browser.use_real_profile). close-profile terminates the browser process tree holding your default profile so Hermes can copy it — DESTRUCTIVE (unsaved tabs in that browser are lost). The agent runs this only after you approve closing the browser.`
- **What it does:** Holds the helper commands that support `browser.use_real_profile` — currently only closing the browser that holds a profile lock.
- **How it works:** parser at `hermes_cli/main.py:13337-13358`, dispatcher `_dispatch_browser` (`main.py:13360-13387`).
- **Inputs / options:** subcommand `close-profile`; `-h/--help`.
- **Outputs / side effects:** with no subcommand it prints the group help and returns exit code 2.
- **Config / env:** `browser.use_real_profile` (default `false`), `browser.real_profile_autoclose` (default `false`).
- **Edge cases / guards:** the agent may only invoke this after an explicit user approval.
- **Rebuild notes:** Keep destructive browser control behind a named, self-documenting command rather than an implicit side effect of a snapshot.

### `hermes browser close-profile`  `id: cli-a.browser-close-profile`
- **Surface:** CLI
- **Where:** `hermes browser close-profile`; help verbatim: `Close the browser locking your real profile (asks nothing — run only with the user's explicit OK; loses unsaved tabs)`.
- **What it does:** Kills the whole Chromium process tree that holds your default profile's lock so Hermes can copy the profile.
- **How it works:** `_dispatch_browser` (`main.py:13360-13387`) resolves the browser (flag or `detect_default_chromium()`, `browser_connect.py:482-493`), then its user-data-dir (`real_profile_data_dir`, `browser_connect.py:254-289`), then calls `close_browser_holding_profile(src)` (`browser_connect.py:864-918`). That function enumerates processes bound to that exact user-data-dir, adds their recursive children (renderers, GPU, crashpad), sends `terminate()` to all, waits `min(timeout, 8.0)` s, `kill()`s survivors, waits 3 s more, then polls `_profile_is_locked` every 0.5 s until the 15 s deadline.
- **Inputs / options:** `-h/--help`; `--browser BROWSER` (see next entry).
- **Outputs / side effects:** terminates browser processes (unsaved tabs are lost). Prints `✓ closed the browser and the profile lock released.` and returns 0, or an `✗ <msg>` line on stderr and returns 1. Failure messages, VERBATIM: `psutil unavailable — cannot close the browser automatically.`, `no matching browser process found holding the profile.`, `closed the browser processes but the profile is still locked — another instance may have relaunched (background/tray mode).`
- **Config / env:** none read by the command itself; `browser.real_profile_autoclose` decides whether the agent is allowed to offer it.
- **Edge cases / guards:** prints `✗ No supported Chromium default browser detected.` (exit 1) when detection returns `None` or the `UNSUPPORTED_CHANNEL` sentinel (`__unsupported_channel__`, set for recognised-but-unsupported Beta/Dev/Canary channels); prints `✗ Could not resolve the <browser> profile directory.` (exit 1) when the data dir cannot be built. `psutil.NoSuchProcess` / `AccessDenied` are swallowed per process.
- **Rebuild notes:** Match processes by their exact `--user-data-dir`, kill the tree, then verify the lock actually released rather than assuming.

### `hermes browser close-profile --browser BROWSER`  `id: cli-a.browser-close-profile-browser`
- **Surface:** CLI
- **Where:** `hermes browser close-profile --browser brave`; help verbatim: `Override detected default browser (chrome/edge/brave/brave-origin/chromium)`.
- **What it does:** Skips OS default-browser detection and targets a specific Chromium family member.
- **How it works:** `main.py:13353-13356`; the value is used verbatim as the key into `_CHROMIUM_BROWSERS = ("chrome", "edge", "brave", "chromium", "brave-origin")` (`browser_connect.py:120`) and `_real_profile_relparts` (`browser_connect.py:223-250`).
- **Inputs / options:** one of `chrome`, `edge`, `brave`, `brave-origin`, `chromium`. Profile directories per platform:
  - `chrome` — macOS `~/Library/Application Support/Google/Chrome`; Windows `%LOCALAPPDATA%\Google\Chrome\User Data`; Linux `$XDG_CONFIG_HOME/google-chrome` (Flatpak `~/.var/app/com.google.Chrome/config/google-chrome`)
  - `edge` — macOS `~/Library/Application Support/Microsoft Edge`; Windows `%LOCALAPPDATA%\Microsoft\Edge\User Data`; Linux `$XDG_CONFIG_HOME/microsoft-edge` (Flatpak `com.microsoft.Edge`)
  - `brave` — macOS `~/Library/Application Support/BraveSoftware/Brave-Browser`; Windows `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data`; Linux `$XDG_CONFIG_HOME/BraveSoftware/Brave-Browser`, snap `~/snap/brave/current/.config/BraveSoftware/Brave-Browser`, Flatpak `com.brave.Browser`
  - `chromium` — macOS `~/Library/Application Support/Chromium`; Windows `%LOCALAPPDATA%\Chromium\User Data`; Linux `$XDG_CONFIG_HOME/chromium`, snap `~/snap/chromium/common/chromium`, Flatpak `org.chromium.Chromium`
  - `brave-origin` — macOS `~/Library/Application Support/BraveSoftware/Brave-Origin`; Windows `%LOCALAPPDATA%\BraveSoftware\Brave-Origin\User Data`; Linux `$XDG_CONFIG_HOME/BraveSoftware/Brave-Origin`
- **Outputs / side effects:** as `close-profile`.
- **Config / env:** `LOCALAPPDATA`, `XDG_CONFIG_HOME`, `HOME`.
- **Edge cases / guards:** an unknown value makes `real_profile_data_dir` return `None` → `✗ Could not resolve the <browser> profile directory.`; on Linux the first EXISTING candidate wins, otherwise the native path is returned so the error message names it.
- **Rebuild notes:** Table-drive the per-OS, per-channel profile paths; include snap/Flatpak layouts.

## H. `hermes secrets` — external secret managers

### `hermes secrets` (command group)  `id: cli-a.secrets`
- **Surface:** CLI
- **Where:** `hermes secrets`; top-level help `Manage external secret sources (Bitwarden, 1Password)`; description verbatim: `Pull API keys from an external secret manager at process startup instead of storing them in ~/.hermes/.env.  Supports Bitwarden Secrets Manager and 1Password.  See: https://hermes-agent.nousresearch.com/docs/user-guide/secrets/`
- **What it does:** Configures where Hermes fetches provider API keys from at startup instead of `~/.hermes/.env`.
- **How it works:** parser at `hermes_cli/main.py:13392-13418`, dispatcher `_dispatch_secrets` (`main.py:13420-13427`). The two backends register their own subtrees: `hermes_cli/secrets_cli.py:register_cli` (dest `secrets_bw_command`) and `hermes_cli/onepassword_secrets_cli.py:register_cli` (dest `secrets_op_command`). Backends are imported lazily because the Bitwarden backend pulls `cryptography._rust.pyd`, which would self-lock `hermes update` on Windows (#86781).
- **Inputs / options:** subcommands `bitwarden` (alias `bw`), `onepassword` (aliases `op`, `1password`); `-h/--help`.
- **Outputs / side effects:** with no subcommand it prints the group help and returns 0.
- **Config / env:** `secrets.bitwarden.*`, `secrets.onepassword.*`.
- **Edge cases / guards:** parse-time registration is crypto-free by design.
- **Rebuild notes:** Pluggable secret-source backends behind one command, each owning `setup/status/token/sync/disable`.

### `hermes secrets bitwarden` / `hermes secrets bw`  `id: cli-a.secrets-bitwarden`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden <sub>`; help verbatim `Bitwarden Secrets Manager integration`.
- **What it does:** Integrates Bitwarden Secrets Manager (BSM) as the source of Hermes' provider API keys.
- **How it works:** `hermes_cli/secrets_cli.py:76-149`. Pinned binary version `_BWS_VERSION = "2.0.0"` (`secrets_cli.py:38`); the real backend is `agent.secret_sources.bitwarden`, imported on first handler use through `_load_bw()` / PEP-562 `__getattr__`.
- **Inputs / options:** subcommands `setup`, `status`, `token`, `sync`, `disable`, `install`; `-h/--help`.
- **Outputs / side effects:** writes `secrets.bitwarden.*` in `config.yaml` and the access token into `~/.hermes/.env`.
- **Config / env:** `secrets.bitwarden.enabled`, `.access_token_env` (default `BWS_ACCESS_TOKEN`), `.project_id`, `.server_url`, `.override_existing` (default false), `.cache_ttl_seconds` (default 300), `.auto_install` (default true); env `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`.
- **Edge cases / guards:** the child `bws` process gets an env built with `build_subprocess_env(scrub_secrets=False, inherit_profile_home=False)` plus `NO_COLOR=1` — deliberately unscrubbed because it must receive the token.
- **Rebuild notes:** Fetch at process start, cache with a TTL keyed on a token fingerprint, and never overwrite an already-exported env var unless asked.

### `hermes secrets bitwarden setup`  `id: cli-a.secrets-bw-setup`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden setup`; help verbatim `Interactive wizard: install bws, store access token, pick project`.
- **What it does:** Four-step wizard: install the `bws` CLI, store an access token, pick a region, pick a project — then enables the integration.
- **How it works:** `cmd_setup` (`secrets_cli.py:156-343`). Opening panel verbatim:
  ```
  Bitwarden Secrets Manager setup

  Need an access token? In the Bitwarden web app:
    Secrets Manager → Machine accounts → [your account] →
    Access tokens → Create access token

  Copy the token (starts with 0.…) — it cannot be retrieved later.
  ```
  Steps are printed as `Step 1  Install the bws CLI`, `Step 2  Provide your access token`, `Step 3  Pick a Bitwarden region`, `Step 4  Pick a project`.
- **Inputs / options:** `-h/--help`; `--project-id PROJECT_ID` (`Pre-select a project UUID instead of prompting`); `--access-token ACCESS_TOKEN` (`Provide the access token non-interactively (will be stored in .env)`); `--server-url SERVER_URL` (`Bitwarden region / self-hosted endpoint. Examples: https://vault.bitwarden.com (US, default), https://vault.bitwarden.eu (EU), or your self-hosted URL. Skips the interactive region prompt.`). Interactive prompts: `  Paste access token (<token env>): ` (masked), the region table, and the project selection.
- **Outputs / side effects:** `save_env_value(<token_env>, token)` writes `~/.hermes/.env` and sets `os.environ`; prints `  ✓ stored in <env path> as <token env>`; sets `secrets.bitwarden.enabled: true`, `project_id`, `server_url`.
- **Config / env:** `secrets.bitwarden.*`; env `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`.
- **Edge cases / guards:** non-TTY without all flags prints `  Non-interactive mode (no TTY) requires all setup flags.` plus `  Missing: <list>` and a usage block, exit 1. Empty token → `  Empty token, aborting.` exit 1. A token not starting with `0.` prints the warning `  Warning: token doesn't start with '0.' — usually that means you pasted something other than a BSM access token.  Continuing anyway.` No visible projects prints `  No projects visible to this machine account.`
- **Rebuild notes:** Validate the credential against the real service before persisting anything.

### Bitwarden region picker  `id: cli-a.secrets-bw-region`
- **Surface:** CLI
- **Where:** Step 3 of `hermes secrets bitwarden setup`. Table columns `#` and `Region / endpoint`; prompt `  Select region [1-3]: ` (plus ` (Enter to keep current)` when a `server_url` is already configured).
- **What it does:** Chooses which Bitwarden cloud or self-hosted endpoint the `bws` CLI talks to.
- **How it works:** `_resolve_server_url` (`secrets_cli.py:709-785`). Resolution order: `--server-url` → `BWS_SERVER_URL` env → existing `secrets.bitwarden.server_url` → the interactive menu.
- **Inputs / options:** rows VERBATIM — `1` `US Cloud  (https://vault.bitwarden.com — bws default)` (stores `""`), `2` `EU Cloud  (https://vault.bitwarden.eu)` (stores that URL), `3` `Self-hosted / custom URL` (prompts `  Enter your Bitwarden server URL (e.g. https://vault.example.com): `).
- **Outputs / side effects:** stores `secrets.bitwarden.server_url`; when `BWS_SERVER_URL` is detected it prints `  Detected BWS_SERVER_URL=<url> in your shell — using it.`; an existing value prints `  Existing config: <url>. Press Enter to keep, or pick a different option below.`
- **Config / env:** `secrets.bitwarden.server_url`, `BWS_SERVER_URL`.
- **Edge cases / guards:** non-numeric input prints `  Enter a number.`; out-of-range prints `  Out of range — pick 1-3.`; an empty custom URL prints `  Empty URL, aborting.` and returns `None` (setup exits 1); a custom URL not starting with `http://`/`https://` prints `  Warning: URL doesn't start with http:// or https:// — bws may reject it.`
- **Rebuild notes:** Region presets plus a free-form escape hatch; remember the last choice.

### `hermes secrets bitwarden status`  `id: cli-a.secrets-bw-status`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden status`; help verbatim `Show config + binary + token validation status`.
- **What it does:** Prints a panel of the current Bitwarden configuration and actively probes whether the token still works.
- **How it works:** `cmd_status` (`secrets_cli.py:346-405`). Panel title `Bitwarden Secrets Manager`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** rows VERBATIM: `Enabled`, `Token env var`, `Token in env`, `Token validation`, `Project ID`, `Server URL`, `Override existing`, `Cache TTL (s)`, `Auto-install`, `bws binary`. Booleans render as `yes` / `no`; unset values as `(unset)`; the default server URL as `default (US Cloud, https://vault.bitwarden.com)`; a missing binary as `not installed`. `Token validation` is one of `passed`, `failed`, `not checked (integration disabled)`, `not checked (token missing)`, `not checked (bws not installed)` (`_token_validation_status`, `secrets_cli.py:614-645`).
- **Config / env:** as the group entry.
- **Edge cases / guards:** trailing hints — `\n  Run hermes secrets bitwarden setup to enable.` when disabled; `\n  Enabled but <token env> is not set — Hermes will skip BSM and warn on next startup.`; `\n  Enabled but no project_id — nothing to fetch.` A `bws project list` failure surfaces `  bws project list failed: <err>` plus a region hint on `invalid_client`/`400 bad request` or a token hint on `authorization`/`invalid`.
- **Rebuild notes:** Status should probe, not just echo config.

### `hermes secrets bitwarden token`  `id: cli-a.secrets-bw-token`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden token`; help verbatim `Rotate the access token: validate a new one and store it in .env`.
- **What it does:** Replaces the stored BSM access token, verifying it first so a bad paste cannot brick a working setup.
- **How it works:** `cmd_token` (`secrets_cli.py:408-486`). Prints the "create a new token" hint, prompts masked `Paste new access token (<env>): `, then (unless `--no-verify`) installs `bws` if missing and runs `bws project list`; only on success does it `save_env_value` and `bw.clear_caches()`.
- **Inputs / options:** `-h/--help`; `--access-token ACCESS_TOKEN` (`Provide the new token non-interactively (default: masked prompt)`); `--no-verify` (`Store without probing Bitwarden first (not recommended)`).
- **Outputs / side effects:** rewrites the token in `~/.hermes/.env`; prints `Verifying against Bitwarden…`, `✓ Token accepted (<n> project(s) visible).`, and `✓ stored in <env path> as <env>.  Takes effect on the next Hermes invocation.`
- **Config / env:** `secrets.bitwarden.access_token_env`, `.server_url`, `.project_id`.
- **Edge cases / guards:** no TTY and no flag → `No TTY — pass the token with --access-token.` exit 1; empty token → `Empty token, aborting.` exit 1; rejected token → `✗ New token was rejected — nothing was changed.` exit 1; missing binary with `--no-verify` unset → `bws binary not available — cannot verify.  Re-run with --no-verify to store anyway.` exit 1; a configured `project_id` not visible to the new token prints `Warning: configured project <id> is not visible to this machine account. …`; a disabled integration adds `Note: the Bitwarden integration is currently disabled — run \`hermes secrets bitwarden setup\` (or set secrets.bitwarden.enabled: true) to turn it on.`
- **Rebuild notes:** Verify-then-persist; invalidate caches keyed on the old credential.

### `hermes secrets bitwarden sync`  `id: cli-a.secrets-bw-sync`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden sync`; help verbatim `Fetch secrets now and report what changed`.
- **What it does:** Fetches the project's secrets right now and shows, per key, whether it would be exported or skipped. Dry-run unless `--apply`.
- **How it works:** `cmd_sync` (`secrets_cli.py:488-559`). Calls `bw.fetch_bitwarden_secrets(access_token, project_id, use_cache=False, server_url=…)`, then renders a two-column table (`Name`, `Action`).
- **Inputs / options:** `-h/--help`; `--apply` (`Actually export the secrets into the current shell's env (default: dry-run)`).
- **Outputs / side effects:** table cell values VERBATIM: `skip (bootstrap token)` (for the token env var itself), `skip (already set)`, `exported`, `exported (overrode)`, `would export`, `would export (overrides)`. Warnings print as `warning: <w>`. Dry-run footer: `\n  This was a dry-run — secrets are picked up automatically on the next hermes invocation.  Re-run with --apply to export into the current shell instead.` Apply footer: `\n  Exported <n> secret(s) into current process.`
- **Config / env:** `secrets.bitwarden.override_existing` (or `--apply`) decides whether an already-set env var is overwritten.
- **Edge cases / guards:** disabled → `Bitwarden integration is disabled.  Run \`hermes secrets bitwarden setup\` first.` exit 1; missing token → `<env> is not set.` exit 1; missing project → `No project_id configured.` exit 1; fetch exception → `Fetch failed: <exc>` exit 1; empty project → `No secrets in project.` exit 0.
- **Rebuild notes:** The exported-process mutation is inherently ephemeral — say so in the footer.

### `hermes secrets bitwarden disable`  `id: cli-a.secrets-bw-disable`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden disable`; help verbatim `Turn off the Bitwarden integration`.
- **What it does:** Sets `secrets.bitwarden.enabled: false`.
- **How it works:** `cmd_disable` (`secrets_cli.py:563-577`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** saves the config; prints `Disabled.  Bitwarden secrets will NOT be pulled on the next Hermes invocation.\n  Your access token is left in .env — remove it manually if you also want to revoke the credential.`
- **Config / env:** `secrets.bitwarden.enabled`.
- **Edge cases / guards:** never touches `.env` — the credential survives deliberately.
- **Rebuild notes:** Disable ≠ revoke; make that explicit in the output.

### `hermes secrets bitwarden install`  `id: cli-a.secrets-bw-install`
- **Surface:** CLI
- **Where:** `hermes secrets bitwarden install`; help verbatim `Download and verify the pinned bws binary (v2.0.0)`.
- **What it does:** Downloads and checksum-verifies the pinned Bitwarden Secrets Manager CLI.
- **How it works:** `cmd_install` (`secrets_cli.py:580-589`) → `bw.install_bws(force=…)`.
- **Inputs / options:** `-h/--help`; `--force` (`Re-download even if a managed copy already exists`).
- **Outputs / side effects:** places the binary under the Hermes-managed location; prints `✓ <path>  (<version line>)` or `Install failed: <exc>` (exit 1).
- **Config / env:** `secrets.bitwarden.auto_install`.
- **Edge cases / guards:** the version string comes from running `<binary> --version` with a 5 s timeout; failure renders as `version unknown`.
- **Rebuild notes:** Pin and verify the binary; keep the pinned version string duplicated in the CLI layer only for help text.

### `hermes secrets onepassword` / `op` / `1password`  `id: cli-a.secrets-onepassword`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword <sub>`; help verbatim `1Password (op:// references) integration`.
- **What it does:** Resolves `op://vault/item/field` references through an already-installed, already-authenticated 1Password CLI at startup.
- **How it works:** `hermes_cli/onepassword_secrets_cli.py:47-109`; backend `agent.secret_sources.onepassword`. Unlike Bitwarden, the `op` binary is NEVER auto-installed (module docstring, `onepassword_secrets_cli.py:11-13`).
- **Inputs / options:** subcommands `setup`, `status`, `token`, `set`, `remove`, `sync`, `disable`; `-h/--help`.
- **Outputs / side effects:** writes `secrets.onepassword.*` in `config.yaml`; may write a service-account token into `~/.hermes/.env`.
- **Config / env:** `secrets.onepassword.enabled`, `.account`, `.service_account_token_env` (default `OP_SERVICE_ACCOUNT_TOKEN`), `.binary_path`, `.env` (the env-var → reference map), `.cache_ttl_seconds` (default 300), `.override_existing` (default true).
- **Edge cases / guards:** docs URL surfaced throughout: `https://developer.1password.com/docs/cli/get-started/`.
- **Rebuild notes:** Reference-based (not value-based) secret config; resolve at startup through the vendor CLI.

### `hermes secrets onepassword setup`  `id: cli-a.secrets-op-setup`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword setup`; help verbatim `Verify the op CLI, set account / token env var, and enable`.
- **What it does:** Finds the `op` binary, records the account and token env var, and enables the integration.
- **How it works:** `cmd_setup` (`onepassword_secrets_cli.py:117-195`). Panel verbatim:
  ```
  1Password secret source setup

  Hermes resolves op://vault/item/field references through your
  already-installed, already-authenticated 1Password CLI (`op`).

  Don't have it yet? Install + sign in: https://developer.1password.com/docs/cli/get-started/
  ```
  Steps `Step 1  Locate the op CLI` and `Step 2  Authentication`.
- **Inputs / options:** `-h/--help`; `--account ACCOUNT` (`1Password account shorthand or sign-in address (op --account)`); `--token-env TOKEN_ENV` (`Env var holding a service-account token (default OP_SERVICE_ACCOUNT_TOKEN)`); `--token TOKEN` (`Service-account token to store in .env non-interactively`); `--binary-path BINARY_PATH` (`Absolute path to the op binary (skips PATH lookup)`).
- **Outputs / side effects:** sets `enabled: true`, `service_account_token_env`, optionally `account` and `binary_path`, and seeds `env: {}`, `cache_ttl_seconds: 300`, `override_existing: true`. Prints `  ✓ <binary>  (<version>)`, `  Account: <acct>`, one of `  ✓ service account token stored in <env path> as <env>` / `  ✓ using service-account token from <env>` / `  ✓ using existing op session (<whoami>)`, then `✓ 1Password secret source is enabled.` plus the three follow-up command hints (`hermes secrets onepassword set OPENAI_API_KEY "op://Private/OpenAI/api key"`, `hermes secrets onepassword sync`, `hermes secrets onepassword status`).
- **Config / env:** `secrets.onepassword.*`; env `OP_SERVICE_ACCOUNT_TOKEN`.
- **Edge cases / guards:** binary not found prints `  ✗ op not found on PATH.` (or `  ✗ <path> is not an executable op binary.`) plus the install URL, exit 1. Neither a token nor an active session prints `  No service-account token and no active op session detected.` with the `op signin` remedy.
- **Rebuild notes:** Never bundle or auto-install a vendor CLI that ships through OS package managers.

### `hermes secrets onepassword status`  `id: cli-a.secrets-op-status`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword status`; help verbatim `Show config + op binary + references`.
- **What it does:** Prints the 1Password configuration panel plus a table of every mapped env var → reference.
- **How it works:** `cmd_status` (`onepassword_secrets_cli.py:198-254`). Panel title `1Password secret source`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** panel rows VERBATIM: `Enabled`, `Account` (or `default`), `Token env var`, `Token in env`, `Override existing`, `Cache TTL (s)`, `op binary` (or `not found`), `References` (count). The reference table has columns `Env var` and `Reference`.
- **Config / env:** as the group entry.
- **Edge cases / guards:** disabled → `\n  Run hermes secrets onepassword setup to enable.`; binary present but no token → either `\n  Active op session: <whoami>` or `\n  No active op session and <env> is unset — Hermes will warn and skip 1Password on next startup.`; no references → `\n  No references mapped yet.  Add one: hermes secrets onepassword set ENV_VAR "op://…"`.
- **Rebuild notes:** Show the mapping table, not just the toggle.

### `hermes secrets onepassword token`  `id: cli-a.secrets-op-token`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword token`; help verbatim `Rotate the service-account token: validate and store it in .env`.
- **What it does:** Replaces the service-account token after verifying it with `op whoami`.
- **How it works:** `cmd_token` (`onepassword_secrets_cli.py:303-361`).
- **Inputs / options:** `-h/--help`; `--token TOKEN` (`Provide the new token non-interactively (default: masked prompt)`); `--no-verify` (`Store without probing 1Password first (not recommended)`).
- **Outputs / side effects:** writes the token to `~/.hermes/.env`; prompt text `Paste new token (<env>): ` preceded by `Create a new service-account token at https://my.1password.com → Developer → Service Accounts.`
- **Config / env:** `secrets.onepassword.service_account_token_env`, `.account`, `.binary_path`.
- **Edge cases / guards:** no TTY without `--token` → `No TTY — pass the token with --token.` exit 1; empty token → `Empty token, aborting.` exit 1; a disabled integration adds `Note: the 1Password integration is currently disabled — run \`hermes secrets onepassword setup\` to turn it on.`
- **Rebuild notes:** Same verify-then-persist rule as Bitwarden.

### `hermes secrets onepassword set <env_var> <reference>`  `id: cli-a.secrets-op-set`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword set OPENAI_API_KEY "op://Private/OpenAI/api key"`; help verbatim `Map an env var to an op:// reference`.
- **What it does:** Records that one environment variable should be filled from one `op://` reference.
- **How it works:** `cmd_set` (`onepassword_secrets_cli.py:258-286`). Validation reuses the backend's `op_src._validate_references({env_var: reference})` so the CLI and the startup path agree; the STRIPPED/validated value is what gets stored.
- **Inputs / options:** positional `env_var` (help `Environment variable name, e.g. OPENAI_API_KEY`); positional `reference` (help `1Password reference, e.g. op://Private/OpenAI/api key`); `-h/--help`.
- **Outputs / side effects:** writes `secrets.onepassword.env[<env_var>]`; prints `✓ mapped <env_var> → <reference>`.
- **Config / env:** `secrets.onepassword.env`.
- **Edge cases / guards:** an invalid reference prints each validator warning in red and returns 1 without writing; a disabled integration adds the `Note: the integration is disabled — …` hint.
- **Rebuild notes:** One validator shared by CLI and runtime.

### `hermes secrets onepassword remove <env_var>`  `id: cli-a.secrets-op-remove`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword remove OPENAI_API_KEY`; help verbatim `Remove an env-var → reference mapping`.
- **What it does:** Deletes one mapping.
- **How it works:** `cmd_remove` (`onepassword_secrets_cli.py:289-300`).
- **Inputs / options:** positional `env_var` (help `Environment variable name to unmap`); `-h/--help`.
- **Outputs / side effects:** rewrites `secrets.onepassword.env`; prints `✓ removed mapping for <env_var>`.
- **Config / env:** `secrets.onepassword.env`.
- **Edge cases / guards:** an unmapped name prints `<env_var> is not mapped.` and returns 1.
- **Rebuild notes:** n/a.

### `hermes secrets onepassword sync`  `id: cli-a.secrets-op-sync`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword sync`; help verbatim `Resolve references now and report what changed`.
- **What it does:** Resolves every mapped reference now and shows what would be (or was) exported.
- **How it works:** `cmd_sync` (`onepassword_secrets_cli.py:364-458`). `--apply` delegates to `op_src.apply_onepassword_secrets(..., cache_ttl_seconds=0)` so the skip/override/token-guard policy lives in exactly one place; the dry run calls `op_src.fetch_onepassword_secrets(..., use_cache=False)`.
- **Inputs / options:** `-h/--help`; `--apply` (`Actually export resolved values into the current shell (default: dry-run)`).
- **Outputs / side effects:** table columns `Env var` / `Action`; cell values VERBATIM: `exported`, `skipped (already set / token var)`, `skip (token var)`, `unresolved (see warnings)`, `skip (already set)`, `would export`, `would export (overrides)`. Warnings print as `warning: <w>`. Footers: `\n  Exported <n> secret(s) into current process.` (apply) or `\n  This was a dry-run — references resolve automatically on the next hermes invocation.  Re-run with --apply to export into the current shell instead.`
- **Config / env:** `secrets.onepassword.override_existing` (default TRUE here, unlike Bitwarden's false).
- **Edge cases / guards:** disabled → `1Password integration is disabled.  Run \`hermes secrets onepassword setup\` first.` exit 1; no references → `No op:// references configured.  Add one with \`hermes secrets onepassword set ENV_VAR "op://…"\`.` exit 0; a `RuntimeError` from the resolver is printed in red, exit 1.
- **Rebuild notes:** Apply and dry-run must share the policy code path.

### `hermes secrets onepassword disable`  `id: cli-a.secrets-op-disable`
- **Surface:** CLI
- **Where:** `hermes secrets onepassword disable`; help verbatim `Turn off the 1Password integration`.
- **What it does:** Sets `secrets.onepassword.enabled: false`.
- **How it works:** `cmd_disable` (`onepassword_secrets_cli.py:461-475`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints `Disabled.  1Password references will NOT be resolved on the next Hermes invocation.\n  Your reference mappings are left in config.yaml — remove them with hermes secrets onepassword remove ENV_VAR if you no longer need them.`
- **Config / env:** `secrets.onepassword.enabled`.
- **Edge cases / guards:** mappings survive deliberately.
- **Rebuild notes:** n/a.

## I. `hermes egress` — iron-proxy egress credential firewall

### `hermes egress` (command group)  `id: cli-a.egress`
- **Surface:** CLI
- **Where:** `hermes egress`; top-level help `Manage the iron-proxy egress credential-injection firewall`; description verbatim: `Manage iron-proxy, the optional TLS-intercepting egress firewall that swaps proxy tokens for real API credentials before outbound requests leave a sandbox.  Disabled by default.  See: https://hermes-agent.nousresearch.com/docs/user-guide/egress/iron-proxy`
- **What it does:** Manages a local TLS-intercepting proxy that lets sandboxes hold only opaque tokens: the proxy swaps them for real provider credentials at the network boundary.
- **How it works:** parser at `hermes_cli/main.py:13435-13457`, subtree registered by `hermes_cli/proxy_cli.py:register_cli` (dest `egress_command`, deliberately disjoint from the INBOUND OAuth `hermes proxy` command's `proxy_command`). Backend `agent/proxy_sources/iron_proxy.py`, pinned `_IRON_PROXY_VERSION = "0.39.0"` (`iron_proxy.py:90`).
- **Inputs / options:** subcommands `install`, `setup`, `start`, `stop`, `restart`, `reload`, `status`, `disable`, `config`; `-h/--help`.
- **Outputs / side effects:** with no subcommand `_dispatch_egress` prints the group help and returns 0.
- **Config / env:** `proxy.enabled` (default false), `proxy.tunnel_port` (default 9090), `proxy.auto_install` (default true), `proxy.enforce_on_docker` (default true), `proxy.credential_source` (`env` | `bitwarden`), `proxy.allow_env_fallback`, `proxy.extra_allowed_hosts`, `proxy.upstream_deny_cidrs`; env `HERMES_IRON_PROXY_MGMT_KEY`.
- **Edge cases / guards:** scope is Docker-backend sandboxes only in this release (`Scope: Docker backend only in this release` in the status text).
- **Rebuild notes:** Keep real credentials outside the sandbox by construction; the sandbox should only ever hold a revocable proxy token.

### `hermes egress install`  `id: cli-a.egress-install`
- **Surface:** CLI
- **Where:** `hermes egress install`; help verbatim `Download iron-proxy binary (v0.39.0)`.
- **What it does:** Downloads and verifies the pinned iron-proxy release binary.
- **How it works:** `cmd_install` (`proxy_cli.py:136-149`) → `ip.install_iron_proxy(force=…)`. Release base `https://github.com/ironsh/iron-proxy/releases/download/v0.39.0`, checksum file `checksums.txt`, detached signature `checksums.txt.asc`, signing key `public-key.asc`; download timeout 120 s (`iron_proxy.py:92-105`).
- **Inputs / options:** `-h/--help`; `--force` (`Re-download even if a managed copy already exists`).
- **Outputs / side effects:** prints `✓ installed <path>  <version>` or `✗ install failed: <exc>` plus `  Manual install: https://github.com/ironsh/iron-proxy/releases` (exit 1).
- **Config / env:** `proxy.auto_install`.
- **Edge cases / guards:** an unknown version renders as `(version unknown)`.
- **Rebuild notes:** SHA-256 the archive AND verify the checksum file's signature.

### `hermes egress setup`  `id: cli-a.egress-setup`
- **Surface:** CLI
- **Where:** `hermes egress setup`; help verbatim `Interactive wizard: install + CA + mint tokens + write config`.
- **What it does:** Four-step wizard: install the binary, generate a CA, mint per-provider proxy tokens, write `proxy.yaml` + mappings — then enables the integration and optionally restarts a running daemon.
- **How it works:** `cmd_setup` (`proxy_cli.py:152-541`). Opening panel verbatim:
  ```
  iron-proxy setup

  Routes outbound sandbox traffic through a local TLS-intercepting
  proxy so prompt-injected agents never see real provider API keys.

  Project: https://github.com/ironsh/iron-proxy  (Apache-2.0)
  ```
  Steps printed as `Step 1  Install the iron-proxy binary`, `Step 2  Generate a CA cert`, `Step 3  Mint proxy tokens for known providers`, `Step 4  Write config and persist mappings`. Discovery reads `os.environ`, backfilled from `~/.hermes/.env` for known provider names by `_load_env_file_into_environ` (`proxy_cli.py:860-895`).
- **Inputs / options:** `-h/--help`; `--tunnel-port TUNNEL_PORT` (`Override the tunnel port (default 9090)`); `--from-bitwarden` (`Treat secrets as managed by Bitwarden — discover provider keys from secrets.bitwarden config instead of the current env.  Fails loudly if BW is unreachable rather than silently falling back.`); `--no-bitwarden` (`Explicitly switch credential_source back to env on re-setup (only meaningful when the previous setup used --from-bitwarden).`); `--rotate-tokens` (`Mint fresh proxy tokens for every provider (default is to preserve tokens for providers that already had one — avoids 401-ing already-running sandboxes on re-setup).`); `--restart` / `--no-restart` (shared dest `restart`, default `None` = ask on a tty).
- **Outputs / side effects:** writes `~/.hermes/proxy/ca.crt` (0644) + `ca.key`, `~/.hermes/proxy/proxy.yaml`, `~/.hermes/proxy/mappings.json`, `~/.hermes/proxy/management.token` (0600), and pre-creates `~/.hermes/proxy/audit.log` (0600); the state dir itself is forced to 0700. Prints a `Provider env` / `Upstream hosts` / `Proxy token` table (tokens redacted as `<first 12>…<last 4>`), then `  ✓ config:   <path>`, `  ✓ mappings: <path>`, `  ✓ audit log: <path> (reserved — not written by iron-proxy v0.39; per-request records land in iron-proxy.log)`, and finally the command cheatsheet `Start: … Restart: … Reload: … Status: … Stop: … Disable: …`.
- **Config / env:** sets `proxy.enabled: true`, `proxy.tunnel_port`, `proxy.auto_install` (default true), `proxy.enforce_on_docker` (default true), `proxy.credential_source`.
- **Edge cases / guards:** `--tunnel-port` outside 1–65534 → `  ✗ --tunnel-port must be between 1 and 65534 (the plain-HTTP listener uses port+1).` exit 1. `--rotate-tokens` with existing mappings on a tty demands the literal word `rotate` at `Type 'rotate' to confirm: ` after the warning `⚠  --rotate-tokens will invalidate proxy tokens in every running Hermes sandbox.  They will start 401-ing against upstreams until restarted.`; it first copies `mappings.json` to `mappings.json.rotated-<YYYYmmddTHHMMSS>`. On first-time setup it prints `Note: --rotate-tokens is a no-op on first-time setup (no existing tokens to rotate).` With no discoverable keys it prints `  No known provider API keys found in env/Bitwarden.` plus `  Set at least one of these and rerun setup:` and the sorted `_BEARER_PROVIDERS` names, exit 1. `credential_source` is never silently downgraded from `bitwarden` to `env` on a re-run without `--no-bitwarden`.
- **Rebuild notes:** Idempotent re-setup that preserves live tokens by default; make rotation an explicit, confirmed, backed-up action.

### Egress provider coverage (minted mappings)  `id: cli-a.egress-provider-coverage`
- **Surface:** CLI
- **Where:** The Step-3 table of `hermes egress setup` and the `Token mappings` block of `hermes egress status`.
- **What it does:** Defines which provider credentials the proxy can swap, and which it cannot.
- **How it works:** `agent/proxy_sources/iron_proxy.py:148-223`.
- **Inputs / options:**
  - Bearer-token providers (`_BEARER_PROVIDERS`, env var → upstream hosts): `OPENROUTER_API_KEY` → `openrouter.ai`, `*.openrouter.ai`; `OPENAI_API_KEY` → `api.openai.com`; `GROQ_API_KEY` → `api.groq.com`; `TOGETHER_API_KEY` → `api.together.xyz`; `DEEPSEEK_API_KEY` → `api.deepseek.com`; `MISTRAL_API_KEY` → `api.mistral.ai`; `XAI_API_KEY` → `api.x.ai`; `NOUS_API_KEY` → `inference.nousresearch.com`.
  - Header-auth providers (`_HEADER_AUTH_PROVIDERS`): `ANTHROPIC_API_KEY` → hosts `api.anthropic.com`, match headers `x-api-key`, `Authorization`; `AZURE_OPENAI_API_KEY` → hosts `*.openai.azure.com`, `*.cognitiveservices.azure.com`, `*.services.ai.azure.com`, match headers `api-key`, `Authorization`; `GEMINI_API_KEY` (alias `GOOGLE_API_KEY`) → host `generativelanguage.googleapis.com`, match header `x-goog-api-key` (query params covered by `match_query`).
  - Uncovered providers (`_NON_BEARER_PROVIDERS`): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `GOOGLE_APPLICATION_CREDENTIALS` — SigV4 signing / SDK-minted OAuth, which cannot be swapped by a static replacement.
  - Default host allowlist (`_DEFAULT_ALLOWED_HOSTS`): `openrouter.ai`, `*.openrouter.ai`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.x.ai`, `api.mistral.ai`, `api.groq.com`, `api.together.xyz`, `api.deepseek.com`, `inference.nousresearch.com` — extended by `proxy.extra_allowed_hosts`; anything else is 403'd.
  - Default SSRF deny CIDRs (`_DEFAULT_UPSTREAM_DENY_CIDRS`): `127.0.0.0/8`, `::1/128`, `169.254.0.0/16` (incl. cloud IMDS), `fe80::/10`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`, plus IPv4-mapped IPv6 coverage — overridable via `proxy.upstream_deny_cidrs`.
- **Outputs / side effects:** each mapping is `{real_env_name, upstream_hosts[], proxy_token}` persisted in `mappings.json`.
- **Config / env:** `proxy.extra_allowed_hosts`, `proxy.upstream_deny_cidrs`.
- **Edge cases / guards:** uncovered providers are a WARNING, never a start blocker: `  ⚠  Detected provider env vars that the proxy does not yet cover:` followed by `    - <NAME>` and `  These providers use request signing or SDK-minted OAuth (SigV4, service-account files) and will hold real credentials inside the sandbox.  Egress isolation is INCOMPLETE for these.` The former `proxy.fail_on_uncovered_providers` toggle was deleted once `match_headers` covered Anthropic/Azure/Gemini.
- **Rebuild notes:** Table-drive the provider→host→header mapping; treat SigV4-style auth as an explicit, surfaced gap.

### `hermes egress start`  `id: cli-a.egress-start`
- **Surface:** CLI
- **Where:** `hermes egress start`; help verbatim `Start the managed iron-proxy`.
- **What it does:** Spawns the managed iron-proxy daemon with the generated config.
- **How it works:** `cmd_start` (`proxy_cli.py:543-664`) → `ip.start_proxy(install_if_missing=proxy.auto_install, refresh_secrets_from_bitwarden=…, bitwarden_config=…)`. Pidfile `~/.hermes/proxy/iron-proxy.pid`, log `~/.hermes/proxy/iron-proxy.log`, startup grace 5 s.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints `✓ iron-proxy running  pid=<pid>  port=<port>  <listening|not yet listening>`; on failure `✗ failed to start iron-proxy: <exc>` or `✗ iron-proxy did not come up cleanly` (exit 1).
- **Config / env:** `proxy.enabled`, `proxy.auto_install`, `proxy.credential_source`, `proxy.allow_env_fallback`, `secrets.bitwarden.*`; env `BWS_ACCESS_TOKEN`, `HERMES_IRON_PROXY_MGMT_KEY`.
- **Edge cases / guards:** `proxy.enabled` false → `proxy.enabled is false — run \`hermes egress setup\` first.` exit 1. `credential_source: bitwarden` with `secrets.bitwarden` disabled/missing → `✗ Refusing to start: proxy.credential_source is 'bitwarden' but secrets.bitwarden is disabled or missing.` plus three remedies, exit 1 — unless `proxy.allow_env_fallback: true`, which downgrades it to a `⚠` warning. Same source with an unset access-token env → `✗ Refusing to start: credential_source=bitwarden but <env> is not set in the environment.` exit 1; with an empty project id → `✗ Refusing to start: credential_source=bitwarden but secrets.bitwarden.project_id is empty.` exit 1.
- **Rebuild notes:** Fail loud instead of silently degrading a security-relevant credential source.

### `hermes egress stop`  `id: cli-a.egress-stop`
- **Surface:** CLI
- **Where:** `hermes egress stop`; help verbatim `Stop the managed iron-proxy`.
- **What it does:** Terminates the managed daemon.
- **How it works:** `cmd_stop` (`proxy_cli.py:667-674`) → `ip.stop_proxy()` (SIGTERM, then SIGKILL after the grace period per the docs).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints `✓ iron-proxy stopped` or `iron-proxy was not running`. Always returns 0.
- **Config / env:** pidfile under `~/.hermes/proxy/`.
- **Edge cases / guards:** stopping when nothing runs is not an error.
- **Rebuild notes:** Idempotent stop.

### `hermes egress restart`  `id: cli-a.egress-restart`
- **Surface:** CLI
- **Where:** `hermes egress restart`; help verbatim `Restart the managed iron-proxy (stop if running, then start)`.
- **What it does:** Stops (if running) and starts again with the current config — the one-command way to apply changed secrets.
- **How it works:** `cmd_restart` (`proxy_cli.py:677-689`): calls `ip.stop_proxy()`, prints `stopped the running iron-proxy` when something was running, then delegates to `cmd_start(args)` so every credential-source guard runs identically.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** as `start`.
- **Config / env:** as `start`.
- **Edge cases / guards:** required (not `reload`) when upstream SECRETS change, because the daemon reads real credentials from its environment at spawn time.
- **Rebuild notes:** Compose restart from stop+start so guards cannot drift.

### `hermes egress reload`  `id: cli-a.egress-reload`
- **Surface:** CLI
- **Where:** `hermes egress reload`; help verbatim `Hot-reload the running daemon's ruleset from proxy.yaml (management API — no restart, no dropped connections)`.
- **What it does:** Re-reads `proxy.yaml` in the running daemon and swaps the transform pipeline in place.
- **How it works:** `cmd_reload` (`proxy_cli.py:692-716`) → `ip.reload_proxy()`, which POSTs `/v1/reload` to the daemon's loopback management listener authenticated with the bearer key stored at `~/.hermes/proxy/management.token` and injected as `HERMES_IRON_PROXY_MGMT_KEY` (`iron_proxy.py:108-120, 841-842`).
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints `✓ iron-proxy ruleset reloaded in-place (no restart, connections preserved)` and the note `Note: new upstream secrets (rotated keys, new providers) still need \`hermes egress restart\` — the daemon reads real credentials from its environment at spawn time.`; on failure `✗ reload failed: <exc>` exit 1.
- **Config / env:** `HERMES_IRON_PROXY_MGMT_KEY`.
- **Edge cases / guards:** the management listener binds loopback only and every request needs the bearer key; v0.39 refuses to start when the named env var is empty.
- **Rebuild notes:** An authenticated loopback control plane beats SIGHUP for a TLS-terminating proxy.

### `hermes egress status`  `id: cli-a.egress-status`
- **Surface:** CLI
- **Where:** `hermes egress status`; help verbatim `Show proxy state and mappings`.
- **What it does:** One-screen view of the proxy: binary, config, process, listener, credential source, and token mappings.
- **How it works:** `cmd_status` (`proxy_cli.py:766-816`); a plain-text twin `format_status_text(show_tokens=…)` (`proxy_cli.py:719-763`) feeds slash commands, the Dashboard, and the Desktop app.
- **Inputs / options:** `-h/--help`; `--show-tokens` (`Print the proxy tokens (default: redacted prefix only). Beware: tokens may persist in your shell history.`).
- **Outputs / side effects:** table rows VERBATIM: `Enabled`, `Binary` (or `(missing)`), `Binary version` (or `(unknown)`), `Config` (or `(not generated)`), `CA cert` (or `(not generated)`), `Tunnel port`, `Process` (`pid <n>` or `(stopped)`), `Listening`, `Credential src`, `Docker enforce`. Then a `Token mappings` table with columns `Real env`, `Upstream`, `Proxy token`. The plain-text variant adds `Scope: Docker backend only in this release` and the next-step lines `Next: run \`hermes egress setup\` to mint tokens and write proxy.yaml.` or `Next: run \`hermes egress start\` before launching Docker sandboxes.`
- **Config / env:** `proxy.*`.
- **Edge cases / guards:** with `--show-tokens` it prints `⚠  proxy tokens just printed in full — they may persist in your shell history.  Consider clearing it after this command.`; uncovered providers are listed under `Uncovered providers (real credentials still visible inside the sandbox):`.
- **Rebuild notes:** Redact by default; make the un-redacted path loud.

### `hermes egress disable`  `id: cli-a.egress-disable`
- **Surface:** CLI
- **Where:** `hermes egress disable`; help verbatim `Turn off the proxy integration`.
- **What it does:** Sets `proxy.enabled: false` without stopping a running daemon.
- **How it works:** `cmd_disable` (`proxy_cli.py:819-841`). Uses the public `ip.get_status().pid` (which already checks pid liveness) rather than a raw pidfile read, so a stale pidfile cannot fire a spurious warning.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints `✓ proxy.enabled set to false`, plus `  iron-proxy is still running — stop it with hermes egress stop if you want it down too.` when a live pid exists; already-false prints `proxy.enabled was already false.` and returns 0 without writing.
- **Config / env:** `proxy.enabled`.
- **Edge cases / guards:** deliberately non-destructive.
- **Rebuild notes:** Separate "disable the policy" from "kill the process".

### `hermes egress config`  `id: cli-a.egress-config`
- **Surface:** CLI
- **Where:** `hermes egress config`; help verbatim `Print the generated proxy.yaml path`.
- **What it does:** Prints the path of the rendered iron-proxy config so you can inspect it.
- **How it works:** `cmd_config` (`proxy_cli.py:844-854`) reads `ip.get_status().config_path`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** prints the absolute path (typically `~/.hermes/proxy/proxy.yaml`) and returns 0.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** when nothing has been generated it prints `(no config generated — run \`hermes egress setup\`)` and returns 1.
- **Rebuild notes:** A path-printing command composes well with `cat`/`$EDITOR`.

### Egress state directory layout  `id: cli-a.egress-state-files`
- **Surface:** CLI
- **Where:** `~/.hermes/proxy/` (mode 0700, chmod'ed unconditionally on every writable access).
- **What it does:** Holds everything the managed proxy needs and produces.
- **How it works:** `_proxy_state_dir_ro` / `_proxy_state_dir` (`iron_proxy.py:365-392`).
- **Inputs / options:** files — `proxy.yaml` (rendered ruleset), `mappings.json` (env-name → upstream hosts → proxy token), `mappings.json.rotated-<ts>` (pre-rotation backups), `ca.crt` (0644) and `ca.key` (0600, written via a `.staged` temp with `O_NOFOLLOW`), `management.token` (0600), `audit.log` (0600, reserved — not written by v0.39), `iron-proxy.pid`, `iron-proxy.log` (daemon + per-request line-delimited JSON on v0.39).
- **Outputs / side effects:** everything is local; nothing leaves the machine.
- **Config / env:** rooted at `HERMES_HOME`.
- **Edge cases / guards:** an audit-log pre-create failure is a warning (`⚠ <exc>`), not a setup abort, because the file is non-load-bearing on the pinned version.
- **Rebuild notes:** 0700 state dir, 0600 secrets, atomic replace for the CA key.

## J. `hermes migrate` — config rewrites for retired models

### `hermes migrate` (command group)  `id: cli-a.migrate`
- **Surface:** CLI
- **Where:** `hermes migrate`; top-level help `Migrate configuration for retired models or deprecated settings`; description verbatim: `Diagnose and (optionally) rewrite the active config.yaml to replace references to retired models or deprecated settings.`
- **What it does:** Finds references to retired models/settings in your `config.yaml` and can rewrite them.
- **How it works:** parser at `hermes_cli/main.py:13461-13503`; dispatcher `cmd_migrate` (`hermes_cli/migrate.py:16-24`).
- **Inputs / options:** subcommand `xai`; `-h/--help`.
- **Outputs / side effects:** with no subcommand prints `usage: hermes migrate xai [--apply] [--no-backup]` to stderr and returns 2.
- **Config / env:** operates on `<HERMES_HOME>/config.yaml` (`_resolve_config_path`, `migrate.py:112-115`).
- **Edge cases / guards:** distinct from `hermes claw migrate` (which imports OpenClaw configuration) — noted in the docs.
- **Rebuild notes:** Keep the detection logic pure and reusable so `doctor` and `migrate` share it.

### `hermes migrate xai`  `id: cli-a.migrate-xai`
- **Surface:** CLI
- **Where:** `hermes migrate xai`; help verbatim `Migrate xAI models scheduled for retirement on May 15, 2026`; description verbatim: `Scan config.yaml for references to xAI models retiring on May 15, 2026 and, with --apply, rewrite them in-place to the official replacements per the xAI migration guide. The original config.yaml is backed up before any rewrite.`
- **What it does:** Reports (and with `--apply` rewrites) every config slot still pointing at a retired Grok model.
- **How it works:** `cmd_migrate_xai` (`migrate.py:27-109`) → `hermes_cli/xai_retirement.py` (`find_retired_xai_refs`, `format_issue`, `apply_migration`). Slots scanned (`xai_retirement.py:63-127`): `principal.model`, `auxiliary.<any>.model` (introspective over every aux slot), `delegation.model`, `tts.xai.model`, `plugins.image_gen.xai.model`. Model ids are normalised by stripping an `x-ai/` or `xai/` prefix and lower-casing; only names starting `grok-` are considered.
- **Inputs / options:** `-h/--help`; `--apply` (`Rewrite config.yaml in-place (default: dry-run, no writes)`); `--no-backup` (`Skip the timestamped backup of config.yaml when applying`).
- **Outputs / side effects:** header `◆ xAI Model Retirement Migration (May 15, 2026)`. Clean config prints `  ✓ No retired xAI models in config — nothing to migrate.` (exit 0). Otherwise `  Found <n> retired xAI model reference(s):`, one `    ⚠ <formatted issue>` per finding, then `    → Migration guide: https://docs.x.ai/developers/migration/may-15-retirement`. Dry-run adds `Dry-run mode — no changes written.` and `Re-run with \`hermes migrate xai --apply\` to rewrite <path> in-place (backup created automatically).` Apply prints `  ✓ Backup: <path>`, `  ✓ Updated <n> slot(s) in <file>` and `Run \`hermes doctor\` to confirm no retired xAI models remain.`
- **Config / env:** rewrites `<HERMES_HOME>/config.yaml`.
- **Edge cases / guards:** a missing config path prints `  ✗ Could not locate config.yaml (looked at: <path>)` to stderr, exit 1; an exception during rewrite prints `  ✗ Migration failed: <exc>`, exit 1; a no-op rewrite prints `  ⚠ No changes written.` and returns 0.
- **Rebuild notes:** Dry-run first, timestamped backup, then in-place edit that preserves comments.

### xAI retirement replacement map  `id: cli-a.migrate-xai-map`
- **Surface:** Core
- **Where:** Drives the findings printed by `hermes migrate xai` and by `hermes doctor`.
- **What it does:** Maps each retired xAI model to its official replacement, including reasoning-effort adjustments where there is no one-to-one successor.
- **How it works:** `_RETIRED_MODELS` (`hermes_cli/xai_retirement.py:23-32`); `RetirementIssue` carries `config_path`, `current_model` (exact value as found, casing and prefix preserved), `replacement`, `reasoning_effort`, `note`.
- **Inputs / options:** the eight retired ids, VERBATIM:
  - `grok-4-0709` → `grok-4.3`
  - `grok-4-fast-reasoning` → `grok-4.3`
  - `grok-4-fast-non-reasoning` → `grok-4.3` with `reasoning_effort: "none"`
  - `grok-4-1-fast-reasoning` → `grok-4.3`
  - `grok-4-1-fast-non-reasoning` → `grok-4.3` with `reasoning_effort: "none"`
  - `grok-code-fast-1` → `grok-4.3`
  - `grok-3` → `grok-4.3`
  - `grok-imagine-image-pro` → `grok-imagine-image-quality`
  Constants: `MIGRATION_GUIDE_URL = "https://docs.x.ai/developers/migration/may-15-retirement"`, `RETIREMENT_DATE = "May 15, 2026"`.
- **Outputs / side effects:** consumed by the migrator and the doctor check.
- **Config / env:** n/a.
- **Edge cases / guards:** `grok-4.3` reasons by default, so emulating the retired `*-non-reasoning` variants requires the explicit `reasoning_effort: "none"`.
- **Rebuild notes:** Keep the retirement table as pure data with no I/O so every surface can share it.

## K. The interactive CLI chat REPL (`cli.py`)

### Interactive CLI REPL (overall shell)  `id: cli-a.repl`
- **Surface:** CLI
- **Where:** What you get from bare `hermes` (or `hermes chat`, or `hermes --cli`): welcome banner → conversation stream → a fixed input area with a status bar above it.
- **What it does:** A full-screen-ish prompt_toolkit application that owns the composer, the modal overlays (approval, clarify, sudo, secret, model picker, command palette, prompt-stash panel), the streaming render of assistant output, and the tool-progress feed.
- **How it works:** `cli.py` (22 268 lines). The prompt_toolkit `Application` is built around line 20770 (`key_bindings=kb`), with the key map assembled from `KeyBindings()` at `cli.py:18358`. The prompt itself is dynamic (`get_prompt()` → `_get_tui_prompt_fragments`, `cli.py:17905-17943`). Display state is layered from the active skin (`hermes_cli/skin_engine.py`) over a base style dict (`_build_tui_style_dict`, `cli.py:17949-17998`), with an automatic light-mode remap driven by an OSC-11 background probe (`_query_osc11_background`, `_detect_light_mode`, `cli.py:3160-3441`).
- **Inputs / options:** every keybinding and inline command listed in the entries below; plus `!<command>` shell mode and `/<command>` slash commands.
- **Outputs / side effects:** conversation history in the session DB; terminal rendering only for the chrome.
- **Config / env:** `display.*` (busy_input_mode, cli_multiline_shortcuts, tool_preview_length, friendly_tool_labels, status bar fields), `skin`, `voice.record_key`, `paste_collapse_threshold`, `paste_collapse_char_threshold`; env `HERMES_YOLO_MODE`, `HERMES_HOME`.
- **Edge cases / guards:** the REPL is skipped entirely for `-z/--oneshot`, `--tui`, and non-TTY invocations; `_heal_cooked_mode_drift` and `_reset_terminal_input_modes_on_exit` (`cli.py:3276-3332`, `1489-1540`) repair terminal modes that leaked from a crashed child.
- **Rebuild notes:** One key-binding table with `Condition` filters per modal state, a dynamic prompt fragment function, and a redraw-on-invalidate loop. A better version would make every overlay a first-class component with its own key map instead of filtered global bindings.

### Welcome banner  `id: cli-a.repl-banner`
- **Surface:** CLI
- **Where:** Printed once at startup, above the first prompt. Docs figure: "The Hermes CLI banner, conversation stream, and fixed input prompt".
- **What it does:** Shows the model, context window, working directory, session id, available tools grouped by toolset, MCP servers, installed skills, and an update notice.
- **How it works:** `build_welcome_banner` (`hermes_cli/banner.py:960-1302`). Left column = ASCII caduceus (`HERMES_CADUCEUS`, or the skin's `banner_hero`) plus model/cwd/session lines; right column = tool, MCP, and skills sections. Rendered as a Rich `Panel` whose title is `format_banner_version_label()` (hyperlinked to the latest release when known). At ≥ 95 terminal columns an extra logo (`HERMES_AGENT_LOGO`, or the skin's `banner_logo`) prints above the panel. Colors come from skin keys `banner_accent` (#FFBF00), `banner_dim` (#B8860B), `banner_text` (#FFF8DC), `session_border` (#8B8682), `banner_title` (#FFD700), `banner_border` (#CD7F32).
- **Inputs / options:** none (display only). Sections and their VERBATIM headings: `Available Tools`, `MCP Servers`, `Available Skills`, plus optional `Runtime:` and `Profile:` lines and a summary line.
- **Outputs / side effects:** stdout. Line shapes:
  - model line — `<model short> · <N>K context · Nous Research`
  - MoA provider — `MoA: <preset> · agg <aggregator> · <ctx> context · Nous Research`
  - unconfigured — `no model configured — run /model or hermes setup` (bold red)
  - YOLO — `⚠ YOLO mode — all approval prompts bypassed` (bold red, when `HERMES_YOLO_MODE` is set)
  - cwd line, then `Session: <session id>`
  - toolset rows `<toolset>: <tool, tool, …>` (max 8 toolsets, then `(and N more toolsets...)`); tool names are red when disabled, yellow when lazy, normal otherwise; long lists truncate with `...`
  - MCP rows `<name> (<transport>) — <n> tool(s)` / `— disabled` / `— connecting` / `— configured` / `— failed`
  - skills rows `<category>: <a, b, +N more>`, or `Skills toolset disabled`, or `No skills installed`
  - runtime `Runtime: codex app-server (terminal/file ops/MCP run inside codex)` when that runtime is active
  - profile `Profile: <name>` when the active profile is not `default`
  - summary `<N> tools · <N> skills[ · <N> MCP servers] · /help for commands`
  - optional update notice from `_format_update_notice(behind)`
- **Config / env:** `mcp_servers`, enabled toolsets, active skin, active profile; `HERMES_YOLO_MODE`.
- **Edge cases / guards:** a banner snapshot (`load_banner_snapshot` / `save_banner_snapshot`, `banner.py:826-914`) lets a warm start skip the expensive availability computation; the update check NEVER blocks — if the prefetch has not landed within 50 ms, a daemon thread prints the notice above the prompt later (`_defer_update_notice`).
- **Rebuild notes:** Compute availability once, snapshot it, and never let a network check delay first paint.

### Status bar  `id: cli-a.repl-status-bar`
- **Surface:** CLI
- **Where:** A persistent single line directly above the input area. Docs sample: ` ⚕ claude-sonnet-4-20250514 │ 12.4K/200K │ [██████░░░░] 6% │ $0.06 │ 15m`.
- **What it does:** Live session telemetry — model, context usage, cost, duration, and situational badges.
- **How it works:** `_build_status_bar_text` (`cli.py:7465-7600`) with three width tiers: full at ≥ 76 columns (` │ ` separators), compact at 52–75 (` · ` separators), minimal below 52. Visibility toggled by `_status_bar_visible_from_display_config` (`cli.py:4743`) and `/statusbar`; an optional explicit field list narrows what renders (`_get_status_bar_field_set`).
- **Inputs / options:** field keys usable in the field set: `model`, `context_detail`, `context_pct`, `cache_hit`, `latency`, `tps`, `compressions`, `bg_tasks`, `bg_processes`, `bg_subagents`, `goal`, `duration`, `prompt_elapsed`, `idle_since`, `focus`, `yolo`, `title`, `total_tokens` (opt-in only).
- **Outputs / side effects:** badge glyphs VERBATIM: `⚕ <model>`, `<used>/<total>` or `ctx --`, `<n>%` or `--`, `◷ <avg latency>`, `↑ <avg tokens/s>`, `🗜️ <n>` (compressions), `▶ <n>` (background tasks), `⚙ <n>` (background processes), `⛓ <n>` (background subagents), `Σ<tokens>`, `⚠ YOLO`, `📌 <n>` (stashed drafts), plus the battery indicator prefix and a right-aligned gold session-title badge.
- **Config / env:** `display.*` status-bar settings; toggled at runtime by `/statusbar` (alias `/sb`), `/battery`, `/timestamps`, `/focus`.
- **Edge cases / guards:** context color thresholds (docs): green < 50 %, yellow 50–80 %, orange 80–95 %, red ≥ 95 %; cost shows `n/a` for unknown/zero-priced models; long titles truncate before displacing the model/context fields.
- **Rebuild notes:** Three width tiers plus an opt-in field list; never let an optional badge push out the model name.

### Prompt symbol and per-state prompts  `id: cli-a.repl-prompt`
- **Surface:** CLI
- **Where:** The leftmost characters of the input line.
- **What it does:** Signals what the composer is currently doing — normal input, agent working, a modal question, or voice capture.
- **How it works:** `_get_tui_prompt_symbols` (`cli.py:17854-17891`) resolves the skin's `branding.prompt_symbol` (default `❯ `) and prefixes the active profile name when it is not `default`/`custom` (e.g. `coder ❯ `). `_get_tui_prompt_fragments` (`cli.py:17905-17943`) then picks a state icon; narrow terminals render icon-only via `_use_minimal_tui_chrome`.
- **Inputs / options:** state icons in priority order, VERBATIM: `●` + an audio level bar (`class:voice-recording`), `◉` (`class:voice-processing`), `🔐` (sudo prompt), `🔑` (secret capture), `⚠` (approval prompt), `⚠` (slash confirmation), `✎` (clarify free-text), `?` (clarify choice), the animated command spinner frame (`_command_spinner_frame`, while a slash command runs), `⚕` (agent running), `🎤` (voice mode idle), else the plain prompt symbol.
- **Outputs / side effects:** display only.
- **Config / env:** the active skin's `branding.prompt_symbol`; active profile name.
- **Edge cases / guards:** an icon-only custom prompt still renders in special states (the symbol doubles as the state suffix); arrow-like trailing characters recognised for the suffix are `❯ > $ # › » →`.
- **Rebuild notes:** One prompt function, one ordered state list — never scatter prompt mutations across handlers.

### Keybinding — `Enter` (send)  `id: cli-a.repl-key-enter`
- **Surface:** CLI
- **Where:** Composer. Docs table row: `Enter` | `Send message`.
- **What it does:** Submits the composer contents as the next turn.
- **How it works:** `_bind_prompt_submit_keys(kb, handle_enter, …)` (`cli.py:4537-4570`) binds `enter`; the handler at `cli.py~18660-18711` inlines any collapsed-paste placeholders back to real text (`_inline_pastes`) before `reset(append_to_history=True)`, so Up-arrow recall restores the real content. When the agent is busy the submission is routed by `display.busy_input_mode`.
- **Inputs / options:** none.
- **Outputs / side effects:** the message enters the agent loop (or the busy queue/steer path); history gains the entry.
- **Config / env:** `display.busy_input_mode`, `display.cli_multiline_shortcuts`.
- **Edge cases / guards:** the first busy-Enter prints a one-line `/busy` hint once per install, recorded as `onboarding.seen.busy_input_prompt`.
- **Rebuild notes:** Expand placeholders BEFORE history append.

### Keybinding — `Alt+Enter` / `Ctrl+J` / `Ctrl+Enter` / `Shift+Enter` (newline)  `id: cli-a.repl-key-newline`
- **Surface:** CLI
- **Where:** Composer. Docs row: `Alt+Enter`, `Ctrl+J`, or `Shift+Enter` | `New line (multi-line input)…`.
- **What it does:** Inserts a literal newline instead of sending.
- **How it works:** `handle_alt_enter` bound to `('escape', 'enter')` (`cli.py:18718-18728`); `handle_ctrl_enter_newline` bound to `c-j` (`cli.py:18730-18741`) when `display.cli_multiline_shortcuts` is true (default) or `_preserve_ctrl_enter_newline()` says the environment delivers Ctrl+Enter as LF. `Shift+Enter` only arrives distinctly under the Kitty keyboard protocol or xterm `modifyOtherKeys`.
- **Inputs / options:** `display.cli_multiline_shortcuts: false` restores legacy Ctrl+J-as-submit on unusual POSIX PTYs. Backslash continuation (ending a line with `\`) is a second multiline route.
- **Outputs / side effects:** buffer text gains `\n`.
- **Config / env:** `display.cli_multiline_shortcuts`.
- **Edge cases / guards:** on Windows Terminal `Alt+Enter` is swallowed by the terminal (fullscreen toggle) — use `Ctrl+Enter`/`Ctrl+J`. Terminal support matrix (docs): distinct Shift+Enter by default on Kitty, foot, WezTerm, Ghostty; opt-in on iTerm2, Alacritty, VS Code terminal, Warp, Windows Terminal Preview 1.25+; unsupported on macOS Terminal.app and stable Windows Terminal.
- **Rebuild notes:** Bind every plausible newline encoding; never assume the terminal can distinguish Shift+Enter.

### Keybinding — `Tab` (completion / suggestion)  `id: cli-a.repl-key-tab`
- **Surface:** CLI
- **Where:** Composer. Docs row: `Tab` | `Accept auto-suggestion (ghost text) or autocomplete slash commands`.
- **What it does:** Accepts the highlighted completion, else the ghost-text suggestion, else opens the completion menu.
- **How it works:** `handle_tab` (`cli.py:18856-18888`, `eager=True`). Priority: open completion menu → `apply_completion` (selecting index 0 first if nothing is highlighted); else `buf.suggestion.text` → `insert_text`; else `buf.start_completion()`. Re-triggering matters after accepting a provider prefix like `anthropic:` so stage-2 model completions appear without another keystroke.
- **Inputs / options:** none.
- **Outputs / side effects:** buffer text changes.
- **Config / env:** completion source is `SlashCommandCompleter` wrapped in `ThreadedCompleter`, with `AutoSuggestFromHistory` for ghost text.
- **Edge cases / guards:** while a batch-clarify panel is open, a filtered `tab` binding registered later wins and cycles the active question instead.
- **Rebuild notes:** Three-tier Tab semantics, and always re-trigger completion after a staged accept.

### Keybinding — `↑` / `↓` (history and cursor)  `id: cli-a.repl-key-history`
- **Surface:** CLI
- **Where:** Composer (normal input state).
- **What it does:** On the first line, Up browses history backwards; on the last line, Down browses forwards; otherwise they move the cursor between wrapped lines.
- **How it works:** `history_up` / `history_down` (`cli.py:19204-19214`) call `buf.auto_up(count=event.arg)` / `buf.auto_down(...)` inside `_recall_without_recollapse`, which sets `_skip_paste_collapse` so a recalled multi-line paste is not re-collapsed into a placeholder.
- **Inputs / options:** repeat count via prompt_toolkit's numeric arg.
- **Outputs / side effects:** buffer text/cursor change.
- **Config / env:** n/a.
- **Edge cases / guards:** filtered off while any modal overlay owns the arrows (clarify, approval, slash-confirm, model picker, palette, stash panel — each binds its own `up`/`down`).
- **Rebuild notes:** Standard readline `auto_up`/`auto_down` semantics.

### Keybinding — `Ctrl+L` (redraw)  `id: cli-a.repl-key-ctrl-l`
- **Surface:** CLI
- **Where:** Anywhere in the composer. Also reachable as `/redraw` (`Force a full UI repaint (recovers from terminal drift)`).
- **What it does:** Forces a clean full-screen repaint.
- **How it works:** `handle_ctrl_l` (`cli.py:19216-19225`) → `self._force_full_redraw()`.
- **Inputs / options:** none.
- **Outputs / side effects:** screen repaint only.
- **Config / env:** n/a.
- **Edge cases / guards:** exists for external buffer drift — tmux/cmux tab switches, `clear` from a subshell, SSH window restores — that prompt_toolkit cannot detect.
- **Rebuild notes:** Match the universal bash/zsh/fish/vim/htop convention.

### Keybinding — `Ctrl+C` (cancel / interrupt / exit)  `id: cli-a.repl-key-ctrl-c`
- **Surface:** CLI
- **Where:** Anywhere. Docs row: `Ctrl+C` | `Interrupt agent (double-press within 2s to force exit)`.
- **What it does:** Cancels whatever is active, in a strict priority order.
- **How it works:** `handle_ctrl_c` (`cli.py:19227+`). Priority, VERBATIM from the docstring: `0. Cancel active voice recording`, `1. Cancel active sudo/approval/clarify prompt`, `2. Interrupt the running agent (first press)`, `3. Force exit (second press within 2s, or when idle)`. Voice cancellation is dispatched to a daemon thread so the event loop never blocks on `AudioRecorder._lock` or CoreAudio.
- **Inputs / options:** none.
- **Outputs / side effects:** prints `\nRecording cancelled.` when it cancelled a recording; interrupts the agent turn; a second press within 2 s exits the process.
- **Config / env:** n/a.
- **Edge cases / guards:** inside `!` shell mode, Ctrl+C kills the child command (exit code 130, message `!: interrupted`) rather than the session.
- **Rebuild notes:** One ordered cancel chain; never block the UI thread inside it.

### Keybinding — `Ctrl+Q` (alternative interrupt)  `id: cli-a.repl-key-ctrl-q`
- **Surface:** CLI
- **Where:** Anywhere in the composer.
- **What it does:** Same cancel/interrupt behaviour as Ctrl+C, minus the double-press force-exit.
- **How it works:** `handle_ctrl_q` (`cli.py:19332+`). Cancels a voice recording, then active prompts, then interrupts the agent, then clears the input buffer.
- **Inputs / options:** none.
- **Outputs / side effects:** as Ctrl+C except it never exits the process.
- **Config / env:** n/a.
- **Edge cases / guards:** exists for terminals/multiplexers that intercept Ctrl+C.
- **Rebuild notes:** Provide a second interrupt key that cannot accidentally quit.

### Keybinding — `Ctrl+D` (delete-char / exit)  `id: cli-a.repl-key-ctrl-d`
- **Surface:** CLI
- **Where:** Composer. Docs row: `Ctrl+D` | `Exit`.
- **What it does:** Deletes the character under the cursor; on an empty composer it exits the session (bash/zsh EOF semantics).
- **How it works:** `handle_ctrl_d` (`cli.py:19399-19414`). With text → `buf.delete()`. With no text but pending attached images → a no-op (so attachments are not silently lost). Otherwise sets `_should_exit` and calls `event.app.exit()`.
- **Inputs / options:** none.
- **Outputs / side effects:** exits the REPL and prints the resume command.
- **Config / env:** n/a.
- **Edge cases / guards:** the attached-image guard is the notable deviation from plain readline.
- **Rebuild notes:** Treat pending attachments as buffer content for EOF purposes.

### Keybinding — `Ctrl+Z` (suspend)  `id: cli-a.repl-key-ctrl-z`
- **Surface:** CLI
- **Where:** Composer, Unix only. Docs row: `Ctrl+Z` | `Suspend Hermes to background (Unix only). Run \`fg\` in the shell to resume.`
- **What it does:** Suspends the process to the shell's job control.
- **How it works:** `handle_ctrl_z` (`cli.py:19465+`).
- **Inputs / options:** none.
- **Outputs / side effects:** the shell prints `Hermes Agent has been suspended. Run \`fg\` to bring Hermes Agent back.`
- **Config / env:** n/a.
- **Edge cases / guards:** on Windows it prints `\nSuspend (Ctrl+Z) is not supported on Windows.` and does nothing.
- **Rebuild notes:** Restore terminal modes around SIGTSTP/SIGCONT.

### Keybinding — `Ctrl+G` / `Alt+G` / `Ctrl+X Ctrl+E` (external editor)  `id: cli-a.repl-key-editor`
- **Surface:** CLI
- **Where:** Composer. Docs rows: `Ctrl+G` | `Open the current input buffer in $EDITOR (vim/nvim/nano/VS Code/etc.). Save and quit to send the edited text as the next prompt — ideal for long, multi-paragraph prompts.` and `Ctrl+X Ctrl+E` | `Emacs-style alternate binding for the external editor (same behavior as Ctrl+G).`
- **What it does:** Hands the current draft to `$EDITOR`; on save+quit the edited text becomes the composer contents.
- **How it works:** `handle_open_in_editor` bound to both `c-g` and `('escape', 'g')` (`cli.py:18751-18756`) → `cli_ref._open_external_editor(event.current_buffer)`. The Alt+G alias exists because VS Code/Cursor bind Ctrl+G to "Find Next" at the editor level so the keystroke never reaches the embedded terminal.
- **Inputs / options:** `$EDITOR`.
- **Outputs / side effects:** a temp file round-trip; buffer replaced with the edited text.
- **Config / env:** `EDITOR`.
- **Edge cases / guards:** suppressed by `_editor_filter` while a clarify, approval, sudo, or secret prompt is active.
- **Rebuild notes:** Also expose it as a slash command (`/prompt`, alias `/compose`).

### Keybinding — `Ctrl+S` (prompt stash) and the stash panel  `id: cli-a.repl-key-stash`
- **Surface:** CLI
- **Where:** Composer. Docs row: `Ctrl+S` | **Stash the prompt.** … A `📌 N` badge in the status bar shows how many drafts are parked.
- **What it does:** Parks a half-written draft (with its attachments), lets you send something else, and brings it back later; repeated presses build a stack, not a single slot.
- **How it works:** `handle_prompt_stash` (`cli.py:18790-18825`) delegates to `hermes_cli/prompt_stash.py:resolve_ctrl_s(stash, buf.text, attached_images)` which returns one of `ACTION_STASHED`, `ACTION_RESTORED`, `ACTION_OPEN_PANEL`. Restoring calls `_restore_stash_payload`, which sets the text, moves the cursor to the end, and EXTENDS (never replaces) `_attached_images`.
- **Inputs / options:** `Ctrl+S` semantics — composer has content → push and clear; composer empty with exactly one stashed draft → pop it back; composer empty with several → open the browse panel; panel open → close it. Panel keys: `↑` / `↓` move the cursor, `Enter` restores the highlighted draft, `d` or `D` discards it, `Esc` (or `Ctrl+S`) closes the panel.
- **Outputs / side effects:** in-memory only for the session — nothing is written to disk, because drafts often contain secrets.
- **Config / env:** n/a.
- **Edge cases / guards:** `_stash_filter` suppresses Ctrl+S while a sudo/secret/approval/clarify prompt owns the composer, so it can never stash a password. Multi-line drafts round-trip exactly, blank lines included.
- **Rebuild notes:** A stack plus a browse panel; extend attachments on restore.

### Keybinding — `Ctrl+P` (command palette)  `id: cli-a.repl-key-palette`
- **Surface:** CLI
- **Where:** Composer. Also reachable as `/palette` (`Open the fuzzy command palette (also Ctrl+P)`).
- **What it does:** Opens a fuzzy, filterable list of every available slash command.
- **How it works:** `open_command_palette` (`cli.py:19093-19101`) → `_open_command_palette` (`cli.py:11405-11420`), which snapshots the composer, builds entries from `_build_command_palette_entries()`, and stores `{entries, filter, selected, _scroll_offset}`.
- **Inputs / options:** palette keys — `↑` / `↓` move the selection (clamped to the visible count), `Enter` runs the highlighted command, `Backspace` deletes a filter character, `Esc` closes and restores the composer, and every character in `0-9 A-Z a-z - _ . : / <space>` extends the filter (`cli.py:19144-19150`).
- **Outputs / side effects:** running an entry dispatches the slash command; closing restores the previous composer snapshot.
- **Config / env:** n/a.
- **Edge cases / guards:** the open binding is filtered off while any other modal (model picker, clarify, approval, slash-confirm, sudo, secret) is active, so overlays never stack.
- **Rebuild notes:** Rank on the command name; snapshot and restore the composer around the overlay.

### Keybinding — `Ctrl+V` and `Alt+V` (clipboard image paste)  `id: cli-a.repl-key-paste-image`
- **Surface:** CLI
- **Where:** Composer. Docs rows: `Alt+V` | `Paste an image from the clipboard when supported by the terminal`; `Ctrl+V` | `Paste text and opportunistically attach clipboard images`.
- **What it does:** Attaches an image sitting on the system clipboard to the next prompt.
- **How it works:** `handle_ctrl_v` (`cli.py:19656-19668`) and `handle_alt_v` (`cli.py:19670-19684`), both calling `self._try_attach_clipboard_image()`. Ctrl+V only fires on terminals that deliver raw 0x16 (GNOME Terminal, Konsole); terminals that intercept Ctrl+V for paste take the bracketed-paste path instead. Alt+V is the reliable route because Alt combos pass through as ESC+key everywhere.
- **Inputs / options:** none.
- **Outputs / side effects:** appends to `_attached_images`; the composer renders image badges via `_format_image_attachment_badges` (`cli.py:4151-4183`). Also available as `/paste` and `/image <path>`.
- **Config / env:** clipboard access via `hermes_cli/clipboard.py`.
- **Edge cases / guards:** Alt+V is deliberately silent when the clipboard holds no image (avoids noise on an accidental press).
- **Rebuild notes:** Two bindings because no single one works on every terminal.

### Keybinding — voice record key (default `Ctrl+B`)  `id: cli-a.repl-key-voice`
- **Surface:** CLI
- **Where:** Composer, when voice mode is on (`/voice on`). Docs row: `Ctrl+B` | `Start/stop voice recording when voice mode is enabled (voice.record_key, default: ctrl+b)`.
- **What it does:** Push-to-talk toggle: starts a recording, or stops it and transcribes.
- **How it works:** binding built from `voice_record_key_from_config(load_config())` → `normalize_voice_record_key_for_prompt_toolkit` → `pt_key_to_sequence` (`cli.py:19485-19522`); the handler `handle_voice_record` (`cli.py:19522+`) dispatches all heavy work (recording start, `_voice_stop_and_transcribe`) to daemon threads because it runs on prompt_toolkit's event-loop thread. The raw configured key is cached via `set_voice_record_key_cache` so every status/placeholder/hint render matches the live binding.
- **Inputs / options:** `voice.record_key` in `config.yaml` — `ctrl+<key>` or `alt+<key>`.
- **Outputs / side effects:** prompt switches to `●` + an audio level bar while recording, `◉` while transcribing; the transcript lands in the composer.
- **Config / env:** `voice.record_key`.
- **Edge cases / guards:** a `super`/`win`/`windows` modifier is TUI-only; the CLI falls back to `Ctrl+B` and logs `voice.record_key %r uses a TUI-only modifier (super/win); CLI fell back to Ctrl+B. Use ctrl+<key> or alt+<key> for cross-runtime parity.` Stopping is always allowed, even while the agent runs.
- **Rebuild notes:** One config key, normalised per runtime, with the UI label read from the same cached value.

### Keybinding — `Esc` (cancel modal) and `Esc Esc` (discard draft)  `id: cli-a.repl-key-escape`
- **Surface:** CLI
- **Where:** Composer.
- **What it does:** Single Esc cancels an active secret/sudo/slash-confirm prompt; double Esc discards the current draft and any attached images.
- **How it works:** `handle_escape_modal` bound with `filter=_modal_prompt_active, eager=True` (`cli.py:19420-19437`) — secret capture is cancelled via `_cancel_secret_capture()`, a sudo prompt gets an empty response pushed onto its queue, a slash confirmation submits `"cancel"`. `handle_double_escape` bound to `('escape','escape')` with `filter=~_modal_prompt_active` (`cli.py:19439-19463`) resets the buffer with `append_to_history=bool(buf.text)` — so Up recalls what you just discarded — and clears `_attached_images`.
- **Inputs / options:** none.
- **Outputs / side effects:** buffer and attachment state cleared; the modal resolves as cancelled.
- **Config / env:** n/a.
- **Edge cases / guards:** single Esc is also the Alt-sequence prefix (`escape+enter`, `escape+g`, `escape+v`), so prompt_toolkit's escape timeout keeps those distinct; double Esc works mid-stream, which is the gap Ctrl+C leaves.
- **Rebuild notes:** Append to history before discarding — it is what makes a reflex key safe.

### Keybinding — number keys in modal overlays  `id: cli-a.repl-key-numbers`
- **Surface:** CLI
- **Where:** Approval panel, slash-confirmation panel, clarify panel.
- **What it does:** Picks the Nth option directly instead of arrowing to it.
- **How it works:** loops that register `kb.add(str(n), filter=Condition(...))` per overlay: approval (`cli.py:19152-19164`), slash-confirm (`cli.py:19166-19178`), clarify (`cli.py:18980-18989`).
- **Inputs / options:** digits `1`–`9` select items 1–9; `0` selects the 10th item.
- **Outputs / side effects:** the overlay resolves immediately with that choice.
- **Config / env:** n/a.
- **Edge cases / guards:** each binding is filtered to its own overlay state and checks `idx < len(choices)`; clarify number keys are disabled while free-text mode is active.
- **Rebuild notes:** Generate the digit bindings from the choice list length.

### Clarify overlay keys  `id: cli-a.repl-key-clarify`
- **Surface:** CLI
- **Where:** The clarify question panel raised by the agent's clarify tool.
- **What it does:** Navigates and answers single-choice, multi-select, and batched clarify questions.
- **How it works:** `clarify_up` / `clarify_down` (`cli.py:18891-18906`), `clarify_toggle` on `space` for multi-select (`cli.py:18908-18921`), `clarify_batch_tab` on `tab` and its `s-tab` counterpart for cycling questions (`cli.py:18923-18940`), plus the digit bindings above.
- **Inputs / options:** `↑` / `↓` move the cursor (the last index is the `Other` option), `Space` toggles a checkbox in multi-select mode, `Tab` / `Shift+Tab` cycle the active question in a batch (any-order answering; revisiting an answered question lets you re-answer), digits pick directly, `Ctrl+C` cancels.
- **Outputs / side effects:** the selected answers return to the agent's clarify tool.
- **Config / env:** n/a.
- **Edge cases / guards:** all bindings are gated on `self._clarify_state` and `not self._clarify_freetext`; the batch `tab` binding is registered AFTER the generic Tab handler so the filtered one wins while the panel is open.
- **Rebuild notes:** Model the panel as a small state machine (questions, selected, selected_indices, freetext).

### Inline model picker overlay  `id: cli-a.repl-model-picker`
- **Surface:** CLI
- **Where:** Raised by `/model` inside a session.
- **What it does:** Switches between already-configured models without leaving the session (it cannot add providers or run OAuth — that is `hermes model`).
- **How it works:** overlay state `self._model_picker_state`; keys registered at `cli.py:19020-19080`: `up`/`down` move the selection, every printable character (`cli.py:19056-19062`) extends a type-to-filter query while typing mode is active, `backspace` deletes a filter character, `escape` (eager) closes the picker and resets the buffer.
- **Inputs / options:** `↑`, `↓`, printable characters (filter), `Backspace`, `Esc`, `Enter`.
- **Outputs / side effects:** switches the session's model; `--global` on the `/model` command persists it to `config.yaml`.
- **Config / env:** `model.persist_switch_by_default`.
- **Edge cases / guards:** the docs are explicit that `/model` cannot add a provider — you must exit and run `hermes model`.
- **Rebuild notes:** Same fold/grouping as the CLI picker so the two surfaces agree.

### `!` shell mode  `id: cli-a.repl-bang-shell`
- **Surface:** CLI
- **Where:** Composer. Docs row: `!<command>` | **Shell mode** — run a shell command yourself without spending a model turn (e.g. `!git status`, `!pytest -x`).
- **What it does:** Runs a shell command directly in the session's working directory, streaming its output, without invoking the model or touching conversation history.
- **How it works:** `hermes_cli/bang_shell.py`. `is_bang_command` matches only a LEADING `!` after stripping whitespace (`fix the bug!` stays a prompt); `parse_bang_command` strips it (`!!` → `!`); `resolve_bang_cwd` mirrors the terminal tool's cwd resolution (`terminal_tool.get_session_cwd`, then the configured `TERMINAL_CWD`/backend default); `check_bang_approval` routes the command through `tools.terminal_tool._check_all_guards(command, "local", has_host_access=False)` — the exact gate the agent's terminal tool uses; `run_bang_command` spawns `subprocess.Popen(command, shell=True, stdout=PIPE, stderr=STDOUT, text=True, encoding="utf-8", errors="replace")` and streams lines as they arrive.
- **Inputs / options:** any shell command after `!`. Default timeout `DEFAULT_TIMEOUT = 120` seconds.
- **Outputs / side effects:** output prints to the terminal only — no user message, no assistant message, no tool result enters history, so the prompt cache is untouched and role alternation cannot be perturbed. A non-zero exit prints `! exited <code>`.
- **Config / env:** child env is sanitised with `tools.environments.local._sanitize_subprocess_env` so Hermes-managed provider keys are filtered out; `TERMINAL_CWD`.
- **Edge cases / guards:** disabled outside interactive local CLI sessions — `bang_shell_enabled()` returns False when `HERMES_GATEWAY_SESSION` or `HERMES_CRON_SESSION` is truthy or `HERMES_SESSION_PLATFORM` is set. Failure/edge messages VERBATIM: `Usage: !<command> — run a shell command without spending a model turn (e.g. !git status)` (bare `!`), `!: failed to run command: <exc>` (exit 127), `!: command timed out after 120s` (exit 124), `!: interrupted` (exit 130).
- **Rebuild notes:** Same approval gate as the agent's shell tool — a cost shortcut must never be a security bypass.

### Slash-command completer and CLI-only commands  `id: cli-a.repl-slash-commands`
- **Surface:** CLI
- **Where:** Composer — typing `/` opens the autocomplete dropdown.
- **What it does:** Offers every slash command available in this surface, including dynamic skill commands and user-defined quick commands.
- **How it works:** `SlashCommandCompleter(skill_commands_provider=lambda: get_skill_commands(), command_filter=cli_ref._command_available)` wrapped in `ThreadedCompleter` (`cli.py:19696-19703`). The catalogue is `COMMAND_REGISTRY` in `hermes_cli/commands.py:147+` — 101 `CommandDef` entries with fields `name`, `description`, `category`, `aliases`, `args_hint`, `subcommands`, `cli_only`, `gateway_only`, `gateway_config_gate`, `busy_policy`, `busy_handler`, `execute`, `argument_mode`, `desktop`. Categories and counts: `Session` 42, `Configuration` 21, `Tools & Skills` 19, `Info` 18, `Exit` 1.
- **Inputs / options:** the 35 commands flagged `cli_only=True` (so they exist ONLY in this REPL), VERBATIM `name [args] (aliases) — description`:
  `/clear` — `Clear screen and start a new session`; `/redraw` — `Force a full UI repaint (recovers from terminal drift)`; `/history` — `Show conversation history`; `/prompt [initial text]` (alias `compose`) — `Compose your next prompt in $EDITOR (markdown), then send it`; `/handoff <platform>` — `Hand off this session to a messaging platform (Telegram, Discord, etc.)`; `/worktree [new [name]|list|prune [--dry-run]]` (subs `new`, `list`, `prune`) — `Show, list, create, or prune isolated git worktrees`; `/snapshot [create|restore <id>|prune]` (alias `snap`) — `Create or restore state snapshots of Hermes config/state`; `/export [profile] [-o output.tar.gz]` — `Export a profile (config, skills, theme) to a shareable archive`; `/import <archive.tar.gz> [--name <name>]` — `Import a shared profile archive as a new profile`; `/journey [list|delete <id>|edit <id>]` (aliases `learning`, `memory-graph`; subs `list`, `delete`, `edit`) — `Open the learning journey timeline`; `/config` — `Show current configuration`; `/statusbar` (alias `sb`) — `Toggle the context/model status bar`; `/battery [on|off|status]` — `Toggle a color-coded battery indicator in the status bar`; `/timestamps [on|off|status]` (alias `ts`) — `Toggle [HH:MM] timestamps on messages and /history`; `/verbose` — `Cycle tool progress display: off -> new -> all -> verbose`; `/focus [on|off|status]` — `Toggle focus view — show only your prompt and the final response`; `/skin [name]` — `Show or change the display skin/theme`; `/indicator [ascii|emoji|kaomoji|unicode]` — `Pick the TUI busy-indicator style`; `/wake [on|off|status]` — `Toggle the 'Hey Hermes' wake word listener`; `/tools [list|disable|enable] [name...]` — `Manage tools: /tools [list|disable|enable] [name...]`; `/toolsets` — `List available toolsets`; `/skills` (subs `search`, `browse`, `inspect`, `install`, `audit`, `pending`, `approve`, `reject`, `diff`, `approval`) — `Search, install, inspect, or manage skills`; `/pet [toggle|list|scale <n>|<slug>]` (subs `toggle`, `list`, `scale`, `off`) — `Toggle or adopt a petdex mascot (/pet, /pet list, /pet <slug>)`; `/hatch [description]` (alias `generate-pet`) — `Generate a new petdex pet from a description`; `/cron [subcommand]` (subs `list`, `add`, `create`, `edit`, `pause`, `resume`, `run`, `remove`) — `Manage scheduled tasks`; `/reload` — `Reload .env variables into the running session`; `/browser [connect|disconnect|status|use]` (subs `connect`, `disconnect`, `status`, `use`) — `Connect browser tools to your live Chromium-family browser via CDP, or switch to Browser Use mode`; `/plugins` — `List installed plugins and their status`; `/palette` — `Open the fuzzy command palette (also Ctrl+P)`; `/subscription` (alias `upgrade`) — `View your Nous plan and change it in the browser`; `/platforms` (alias `gateway`) — `Show gateway/messaging platform status`; `/copy [number]` — `Copy the last assistant response to clipboard`; `/paste` — `Attach clipboard image from your clipboard`; `/image <path>` — `Attach a local image file for your next prompt`; `/quit [--delete]` (alias `exit`) — `Exit the CLI (use --delete to also remove session history)`.
- **Outputs / side effects:** each command runs its handler in `hermes_cli/cli_commands_mixin.py`; registry-owned informational commands share one formatter via `hermes_cli/slash_exec.py:EXECUTORS`.
- **Config / env:** user-defined `quick_commands:` (types `exec` and `alias`) become slash commands in both CLI and messaging surfaces.
- **Edge cases / guards:** commands are case-insensitive (`/HELP` == `/help`); installed skills become slash commands automatically.
- **Rebuild notes:** One declarative command registry shared by CLI, gateway, desktop, and the palette — with per-surface availability as data, not `if` chains.

### Thinking spinner  `id: cli-a.repl-spinner`
- **Surface:** CLI
- **Where:** Printed while the agent waits on the model. Docs sample:
  ```
    ◜ (｡•́︿•̀｡) pondering... (1.2s)
    ◠ (⊙_⊙) contemplating... (2.4s)
    ✧٩(ˊᗜˋ*)و✧ got it! (3.1s)
  ```
- **What it does:** Animated liveness feedback with an elapsed-time counter.
- **How it works:** `KawaiiSpinner` (`agent/display.py:1083-1180+`). Output is written to the stdout captured at construction time (so a child agent's `redirect_stdout(devnull)` cannot black-hole it), or routed through an optional `print_fn` for silent background agents.
- **Inputs / options:** spinner frame sets (`SPINNERS`), VERBATIM: `dots` `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`; `bounce` `⠁⠂⠄⡀⢀⠠⠐⠈`; `grow` `▁▂▃▄▅▆▇█▇▆▅▄▃▂`; `arrows` `←↖↑↗→↘↓↙`; `star` `✶✷✸✹✺✹✸✷`; `moon` `🌑🌒🌓🌔🌕🌖🌗🌘`; `pulse` `◜◠◝◞◡◟`; `brain` `🧠💭💡✨💫🌟💡💭`; `sparkle` `⁺˚*✧✦✧*˚`. Default type `dots`.
  Waiting faces (`KAWAII_WAITING`): `(｡◕‿◕｡)`, `(◕‿◕✿)`, `٩(◕‿◕｡)۶`, `(✿◠‿◠)`, `( ˘▽˘)っ`, `♪(´ε` )`, `(◕ᴗ◕✿)`, `ヾ(＾∇＾)`, `(≧◡≦)`, `(★ω★)`.
  Thinking faces (`KAWAII_THINKING`): `(｡•́︿•̀｡)`, `(◔_◔)`, `(¬‿¬)`, `( •_•)>⌐■-■`, `(⌐■_■)`, `(´･_･`)`, `◉_◉`, `(°ロ°)`, `( ˘⌣˘)♡`, `ヽ(>∀<☆)☆`, `٩(๑❛ᴗ❛๑)۶`, `(⊙_⊙)`, `(¬_¬)`, `( ͡° ͜ʖ ͡°)`, `ಠ_ಠ`.
  Thinking verbs (`THINKING_VERBS`): `pondering`, `contemplating`, `musing`, `cogitating`, `ruminating`, `deliberating`, `mulling`, `reflecting`, `processing`, `reasoning`, `analyzing`, `computing`, `synthesizing`, `formulating`, `brainstorming`.
- **Outputs / side effects:** one rewritten terminal line; cleared when the turn ends.
- **Config / env:** the active skin may override `spinner.waiting_faces`, `spinner.thinking_faces`, `spinner.thinking_verbs` (`get_waiting_faces` / `get_thinking_faces` / `get_thinking_verbs`, `agent/display.py:1116-1152`); `/indicator [ascii|emoji|kaomoji|unicode]` picks the busy-indicator style.
- **Edge cases / guards:** the animation runs on its own thread; `print_fn` can silence it entirely.
- **Rebuild notes:** Capture stdout at construction; make face/verb sets skinnable data.

### Tool progress feed and preview truncation  `id: cli-a.repl-tool-feed`
- **Surface:** CLI
- **Where:** The lines printed under the prompt while tools run. Docs sample:
  ```
    ┊ 💻 terminal `ls -la` (0.3s)
    ┊ 🔍 web_search (1.2s)
    ┊ 📄 web_extract (2.1s)
  ```
- **What it does:** Shows which tool is running, a preview of its main argument, and how long it took.
- **How it works:** emoji resolution `get_tool_emoji(tool_name, default="⚡")` (`agent/display.py:148-165`) with priority: active skin's `tool_emojis` override → the tool registry's per-tool `emoji` field → the default. Preview length is capped by `set_tool_preview_max_len` / `get_tool_preview_max_len` (`agent/display.py:116-124`), initialised from config at `cli.py:808-813`. Friendly human-phrased verbs come from `set_friendly_tool_labels` / `get_tool_verb` (`agent/display.py:682-700`), initialised at `cli.py:815-821`.
- **Inputs / options:** `/verbose` cycles the display mode `off → new → all → verbose`.
- **Outputs / side effects:** terminal output only.
- **Config / env:** `display.tool_preview_length` (default `0` = no limit; the gateway tiers default to 40), `display.friendly_tool_labels` (default `true`).
- **Edge cases / guards:** `set_tool_preview_max_len` coerces to `max(int(n), 0)` and treats falsy as unlimited.
- **Rebuild notes:** Per-tool emoji + verb as registry data, skinnable, with one global truncation knob.

### Skins (CLI theming)  `id: cli-a.repl-skins`
- **Surface:** CLI
- **Where:** Selected with `/skin [name]` (`Show or change the display skin/theme`); YAML skins live in `~/.hermes/skins/<name>.yaml`.
- **What it does:** Retheme the whole CLI — banner art and colors, prompt symbol, spinner faces and verbs, tool emojis, and the prompt_toolkit style overrides.
- **How it works:** `hermes_cli/skin_engine.py`. Built-ins live in `_BUILTIN_SKINS` (`skin_engine.py:201+`); `get_active_skin()` / `get_active_skin_name()` / `list_skins()` / `set_active_skin()` / `resolve_skin()` form the API; `init_skin_from_config(CLI_CONFIG)` runs at import (`cli.py:800-805`); `get_prompt_toolkit_style_overrides()` is layered over the base style (`cli.py:17957-17962`).
- **Inputs / options:** the 9 built-in skins, VERBATIM `name — description`: `default` — `Classic Hermes — gold and kawaii`; `ares` — `War-god theme — crimson and bronze`; `mono` — `Monochrome — clean grayscale`; `slate` — `Cool blue — developer-focused`; `daylight` — `Light theme for bright terminals with dark text and cool blue accents`; `warm-lightmode` — `Warm light mode — dark brown/gold text for light terminal backgrounds`; `poseidon` — `Ocean-god theme — deep blue and seafoam`; `sisyphus` — `Sisyphean theme — austere grayscale with persistence`; `charizard` — `Volcanic theme — burnt orange and ember`. Skinnable keys used by the CLI: `banner_hero`, `banner_logo`, `banner_accent`, `banner_dim`, `banner_text`, `banner_title`, `banner_border`, `session_border`, `branding.prompt_symbol`, `spinner.waiting_faces`, `spinner.thinking_faces`, `spinner.thinking_verbs`, `tool_emojis`.
- **Outputs / side effects:** purely visual; the active skin name is persisted in config.
- **Config / env:** `~/.hermes/skins/*.yaml` for user skins; the skin change event is `skin.changed`.
- **Edge cases / guards:** a light-terminal probe (`_detect_light_mode`, OSC-11 background query) remaps hex colors through `_maybe_remap_for_light_mode`, but the remap is SKIPPED for style strings that paint their own `bg:` (status bar, completion menu) to avoid dark-on-dark.
- **Rebuild notes:** Ship a schema-validated YAML skin format and never hard-code a color outside it.

### Bracketed paste, paste collapse, and file drop  `id: cli-a.repl-paste`
- **Surface:** CLI
- **Where:** Composer, on any paste. Docs: "**Multiline paste preview.** When you paste a multi-line block, the CLI echoes a compact single-line preview … instead of dumping the whole payload into the scrollback."
- **What it does:** Normalises pasted text, collapses large pastes to a compact placeholder backed by a file, and recognises dragged/pasted file paths.
- **How it works:** the `Keys.BracketedPaste` handler (`cli.py:19590-19655`, `eager=True`). It normalises `\r\n` and `\r` to `\n`, strips leaked bracketed-paste wrappers (`_strip_leaked_bracketed_paste_wrappers`) and leaked terminal responses (recovering input modes when mouse reports leaked), sanitises surrogates via `run_agent._sanitize_surrogates`, then decides whether to collapse. Collapsed content is written to `~/.hermes/pastes/paste_<n>_<HHMMSS>.txt` and the buffer gets `[Pasted text #<n>: <lines> lines → <path>]`. `_inline_pastes` (`cli.py:8757-8776`) expands placeholders back to real text before submit/history/editor. Dragged paths are detected by `_detect_file_drop` (`cli.py:4079-4150`) and `_resolve_attachment_path` (`cli.py:4005-4078`).
- **Inputs / options:** thresholds `paste_collapse_threshold` (default `5` lines) and `paste_collapse_char_threshold` (default `2000` chars); either one triggers collapse.
- **Outputs / side effects:** a file under `~/.hermes/pastes/`; the placeholder in the composer; image badges when an image was attached.
- **Config / env:** `paste_collapse_threshold`, `paste_collapse_char_threshold`.
- **Edge cases / guards:** a buffer whose text already starts with `/` is never collapsed (slash commands must stay literal); a paste that looks like an image trigger auto-attaches the clipboard image (`_should_auto_attach_clipboard_image_on_paste`); a handler taking > 500 ms logs `Slow bracketed-paste handler: …ms to process … bytes (… lines) on <platform>. …` for the known macOS Tahoe/iTerm2/Ghostty freeze reports (#16263); a bracketed-paste timeout patch is installed by `_apply_bracketed_paste_timeout_patch` (`cli.py:4247+`).
- **Rebuild notes:** Collapse for display, keep the real bytes, and inline them before anything consumes the buffer.

### Busy input mode (typing while the agent works)  `id: cli-a.repl-busy-input`
- **Surface:** CLI / Config
- **Where:** Governs what pressing Enter does while the agent is running; changed inline with `/busy queue`, `/busy steer`, `/busy interrupt`, `/busy status`.
- **What it does:** Chooses between redirecting the current turn, queueing a follow-up, or steering the run at the next tool boundary.
- **How it works:** `display.busy_input_mode` read by the Enter handler; the three modes are implemented in the agent loop. Docs table (`website/docs/user-guide/cli.md:361-380`).
- **Inputs / options:** modes VERBATIM — `"interrupt"` (default): `Your message redirects the active turn. Model generation restarts with displayed reasoning and completed work preserved; running tools finish first`; `"queue"`: `Your message is silently queued and sent as the next turn after the agent finishes`; `"steer"`: `Your message is injected into the current run via /steer, arriving at the agent after the next tool call — no interrupt, no new turn`.
- **Outputs / side effects:** the first busy-Enter of an install prints a one-line reminder about `/busy`; the flag is recorded as `onboarding.seen.busy_input_prompt` in `config.yaml` (delete it to see the tip again).
- **Config / env:** `display.busy_input_mode`; `onboarding.seen.busy_input_prompt`.
- **Edge cases / guards:** unknown values fall back to `"interrupt"`. `"steer"` falls back to `"queue"` when the agent has not started yet or when images are attached. `/stop` cancels the turn and its foreground work.
- **Rebuild notes:** Three explicit policies with named fallbacks, not implicit behaviour.

### Final-response rendering (markdown stripping)  `id: cli-a.repl-render`
- **Surface:** CLI
- **Where:** The assistant's final reply in the conversation stream.
- **What it does:** Strips the most verbose markdown so replies read as terminal prose rather than raw source.
- **How it works:** `_strip_markdown_syntax` (`cli.py:3559-3593`), `_render_final_assistant_content(text, mode="render")` (`cli.py:3630-3667`), `_post_stream_transform_output` (`cli.py:3668-3693`), plus `realign_markdown_tables` and `_preserve_windows_dot_segments_for_markdown` (`cli.py:3594-3610`). Streaming width comes from `_terminal_width_for_streaming` (`cli.py:3611-3629`); reasoning tags are removed by `_strip_reasoning_tags` (`cli.py:248-319`).
- **Inputs / options:** none directly.
- **Outputs / side effects:** code blocks and lists are preserved; `**bold**` / `*italic*` wrappers and the noisiest fences are removed.
- **Config / env:** an output-history ring buffer (`_configure_output_history`, default 200 lines) supports `/redraw` replay (`cli.py:3694-3772`).
- **Edge cases / guards:** the stripping applies ONLY to final CLI replies — gateway platforms and tool results keep their markdown for native rendering.
- **Rebuild notes:** Render per surface; never mutate what other surfaces will render themselves.

## Handoffs
- `hermes chat` slash-command *catalogue* beyond the CLI-only subset (66 shared/gateway-only commands in `hermes_cli/commands.py:COMMAND_REGISTRY`) — belongs to the slash-commands shard.
- `hermes skin` / `hermes profile` / `hermes setup` / `hermes tools` / `hermes skills` / `hermes cron` / `hermes plugins` / `hermes dashboard` / `hermes proxy` (INBOUND OAuth reverse proxy, distinct from `hermes egress`) and every other top-level sub-command — other CLI shards.
- The `/model`, `/moa`, `/worktree`, `/browser`, `/busy`, `/verbose`, `/skin`, `/statusbar`, `/focus`, `/palette`, `/copy`, `/paste`, `/image` handler internals (`hermes_cli/cli_commands_mixin.py`) — slash-commands shard.
- Provider credential flows in `hermes_cli/model_setup_flows.py` (`_model_flow_openrouter`, `_model_flow_anthropic`, `_model_flow_bedrock`, `_model_flow_vertex`, `_model_flow_azure_foundry`, `_model_flow_copilot`, `_model_flow_copilot_acp`, `_model_flow_kimi`, `_model_flow_stepfun`, `_model_flow_openai_codex`, `_model_flow_xai_oauth`, `_model_flow_qwen_oauth`, `_model_flow_minimax_oauth`, `_model_flow_nous`, `_model_flow_ai_gateway`, `_model_flow_api_key_provider`, `_model_flow_custom`, `_model_flow_named_custom`) — providers shard.
- The MoA RUNTIME (advisor fan-out, aggregation, `moa.privacy_filter`, `save_traces`, `__HERMES_MOA_TURN_V1__` decoding) — core/agent shard.
- `agent/proxy_sources/iron_proxy.py` internals (config rendering, CA generation, management API client, Bitwarden secret refresh) and `agent/secret_sources/{bitwarden,onepassword}.py` — core/security shard.
- The startup worktree pruner (`cli._prune_stale_worktrees`, `cli._prune_orphaned_branches`) and the cron-scheduled 6-hourly sweep — core/lifecycle shard.
- Voice mode setup, TTS, and the wake-word listener (`hermes_cli/voice.py`, `/voice`, `/wake`) — voice shard.
- The TUI (`ui-tui/`) and Desktop app equivalents of these pickers — TUI/desktop shards.
