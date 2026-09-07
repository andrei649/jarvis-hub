# Configuration keys B — platform, auxiliary, gateway & ops sections, hidden keys, and the config.yaml machinery

This shard inventories every `config.yaml` key that the live `GET /api/config/schema` (785 fields) files under the categories **discord** (33 `discord.*` + 4 `telegram.*` merged in), **auxiliary** (115), **bedrock** (8), **curator** (10), **database** (3), **desktop** (11), **gateway** (22), **kanban** (16), **loops** (4), **lsp** (5), **matrix** (3), **mattermost** (3), **moa** (10), **model_catalog** (3), **monitoring** (11), **openrouter** (3), **proxy** (5), **secrets** (15), **sessions** (13), **slack** (6), **streaming** (6), **tool_loop_guardrails** (10), **tool_output** (3), **tools** (6), **vertex** (2), **wake_word** (14), **web** (9) and **x_search** (4) — 357 schema fields in total, each with its live default from `hermes_cli/config_defaults.py` (DEFAULT_CONFIG, `_config_version: 39`) and the code that consumes it.
It also documents (a) the 42 DEFAULT_CONFIG keys the schema does NOT expose (empty-dict "open" keys such as `providers`, `hooks`, `quick_commands`, `auxiliary.<task>.extra_body`, `discord.channel_prompts`, plus `_config_version`), (b) the root keys code reads that are absent from DEFAULT_CONFIG altogether (`mcp_servers`, `platforms`, `custom_providers`, `fallback_model`, `plugins.enabled`, …), and (c) the whole configuration engine in `hermes_cli/config.py`: HERMES_HOME resolution, load order and caching, `${VAR}` interpolation, managed scope (`/etc/hermes`), the package-manager write lock, migrations, structure validation, `save_config` default-stripping, the `.env` writer, and every `hermes config …` sub-command.
Every entry states the exact dashboard label (auto-generated as `Section → Sub → Key` in Title Case) so a mechanical checker can find it. For all keys the generic write paths are: edit `~/.hermes/config.yaml` (or the profile's `<root>/profiles/<name>/config.yaml`), `hermes config set <dotted.key> <value>`, Web dashboard **Config** page → category tab → field, Desktop **Settings → Config** (same schema), `PUT /api/config`.
Deliberately left to sibling shards: the categories general/agent/terminal/display/delegation/memory/compression/security/browser/voice/tts/stt/logging (config-a); the `OPTIONAL_ENV_VARS` table and env-var reference (env shard); the messaging adapters' behaviour beyond reading these keys (platform shards); the Web Config page chrome and Desktop settings UI beyond what these keys need (web/desktop shards); `hermes doctor`, `hermes setup`, `hermes update` (CLI shards).

## A. The configuration engine (`hermes_cli/config.py`, `hermes_cli/managed_scope.py`, `hermes_constants.py`)

### Config file location and HERMES_HOME resolution  `id: config-b.core.hermes_home`
- **Surface:** Core | Config | Env
- **Where:** implicit for every command; printed by `hermes config path` (config file) and `hermes config env-path` (.env); shown in `hermes config` → "◆ Paths" → `Config:` / `Secrets:` / `Install:` lines.
- **What it does:** Resolves the directory that holds `config.yaml`, `.env`, `state.db`, `sessions/`, `skills/` and so on, and makes sure it exists with secure permissions before any config read.
- **How it works:** `hermes_constants.get_hermes_home()` (hermes_constants.py:114) returns, in order: a context-local override set by `set_hermes_home_override()` (used by multiplexed gateway turns) → the `HERMES_HOME` env var → the platform default (`~/.hermes` on POSIX, `%LOCALAPPDATA%\hermes` on Windows, hermes_constants.py:53-59). When `HERMES_HOME` is unset but `<default>/active_profile` names a non-default profile, a one-shot warning is written to `errors.log` (`_warn_profile_fallback_once`, hermes_constants.py:78-110). Profiles live at `<root>/profiles/<name>` and `get_profiles_root()` walks back to `<root>` when the parent dir is named `profiles` (hermes_constants.py:189-224). `hermes_cli.config.get_config_path()` = `<home>/config.yaml` (config.py:770), `get_env_path()` = `<home>/.env` (config.py:774), `get_project_root()` = the install tree (config.py:778). `ensure_hermes_home()` (config.py:943-986) runs inside every `load_config()`: memoised per home path; refuses named profiles that have a deletion tombstone (`assert_named_profile_home_live`); creates the home + subdirs `cron, sessions, logs, logs/curator, memories, pairing, hooks, image_cache, audio_cache, skills`; chmods each to `HERMES_HOME_MODE` (octal, default 0700, config.py:840-870); chowns to `HERMES_UID`/`HERMES_GID` when set; seeds `SOUL.md` from `DEFAULT_SOUL_MD` (upgrading a legacy comment-only template in place, config.py:916-937). In managed mode (see `config-b.core.managed_install_lock`) it only verifies dirs exist and uses `umask 0o007` so files are group-writable. `_secure_file()` chmods 0600 except in managed mode or containers (`HERMES_CONTAINER`/`HERMES_SKIP_CHMOD` env, `/.dockerenv`, or `docker|lxc|kubepods` in `/proc/1/cgroup`, config.py:873-913).
- **Inputs / options:** env `HERMES_HOME`, `HERMES_HOME_MODE`, `HERMES_UID`, `HERMES_GID`, `HERMES_CONTAINER`, `HERMES_SKIP_CHMOD`; file `<default>/active_profile`.
- **Outputs / side effects:** directory skeleton + `SOUL.md` created on first load; permission bits changed.
- **Config / env:** n/a (this is the root of all config).
- **Edge cases / guards:** subprocess spawners must pass `HERMES_HOME` explicitly (systemd template in hermes_cli/gateway.py, kanban workers) or the child silently uses the default profile; a missing HERMES_HOME dir in managed mode raises `RuntimeError("HERMES_HOME … does not exist.")`.
- **Rebuild notes:** one function returning override → env → platform default; create skeleton idempotently; chmod 0700/0600 outside containers. A better version would record the resolved home in a lock file so children can inherit it without env plumbing.

### Effective config load pipeline (`load_config` / `load_config_readonly`)  `id: config-b.core.load_config`
- **Surface:** Core | Config
- **Where:** every reader (`from hermes_cli.config import load_config`); `hermes config` / `hermes config get` print the *effective* (merged) values.
- **What it does:** Produces the effective configuration dictionary: schema defaults deep-merged with the user's YAML, normalised, `${VAR}`-expanded, then overlaid by the administrator's managed config.
- **How it works:** `_load_config_impl(want_deepcopy)` (config.py:3936-4092) under `_CONFIG_LOCK` (RLock, config.py:306): (1) `ensure_hermes_home()`; (2) stat `config.yaml` and the managed `config.yaml` to build a cache signature `(user_mtime_ns, user_size, managed_mtime_ns, managed_size)`; (3) cache hit only if the signature matches AND every `${VAR}` referenced at expansion time still has the same `os.environ` value (`_env_ref_snapshot`, config.py:2948); (4) `config = deepcopy(DEFAULT_CONFIG)`; (5) parse the user file with `fast_safe_load`; a root-level `max_turns` is hoisted into `agent.max_turns` before merge; (6) `_deep_merge(defaults, user)` (config.py:2820): user keys win, dicts recurse, and a user `None` over a dict default is ignored (an empty `terminal:` line cannot wipe the section, #58277); (7) `_normalize_max_turns_config` (config.py:3265) and `_normalize_root_model_keys` (config.py:3152: root `provider`/`base_url`/`context_length` move under `model:` only as fallback, `api_base` → `model.base_url`, model id canonicalised to `model.default` from `model.model`/`model.name`, a dict-valued `model.default: {provider, model}` is flattened); (8) `_expand_env_vars` (see `config-b.core.env_interpolation`); (9) `managed_scope.load_managed_config()` is normalised/expanded the same way and deep-merged ON TOP so managed leaves win (config.py:4039-4055); (10) result stored in `_LAST_EXPANDED_CONFIG_BY_PATH` (last-known-good) and `_LOAD_CONFIG_CACHE`. `load_config()` returns a deepcopy (~265µs on hit); `load_config_readonly()` returns the cached object itself for hot paths (mutating it corrupts the cache). Raw readers: `read_raw_config()` (cached deepcopy of the on-disk YAML, no defaults), `read_raw_config_readonly()`, `read_user_config_raw(path)` (no cache, no merge, no expansion — for write-back round-trips and diagnostics, config.py:3518-3565).
- **Inputs / options:** none (module functions); `want_deepcopy` internal.
- **Outputs / side effects:** in-process caches; warnings on parse failure (see `config-b.core.corrupt_config_recovery`).
- **Config / env:** all keys; env vars referenced by `${…}`.
- **Edge cases / guards:** on a YAML parse error a running process keeps serving the last successfully loaded config ("last-known-good", port of openai/codex#31188) instead of dropping security-critical overrides such as `approvals.deny`; a fresh process falls back to DEFAULT_CONFIG. libyaml is not thread-safe so all reads/writes serialise on `_CONFIG_LOCK`. Profile switches change `get_config_path()` so caches are keyed by path string.
- **Rebuild notes:** defaults ⊕ user YAML ⊕ managed overlay with stat-keyed caching and an env-value snapshot for invalidation. Better: a typed schema (pydantic) that validates on load and reports the source layer of every value.

### `${VAR}` / `${env:VAR}` interpolation in config values  `id: config-b.core.env_interpolation`
- **Surface:** Config | Env
- **Where:** any string value in `config.yaml`, e.g. `auxiliary.vision.api_key: ${env:OPENAI_API_KEY}`; documented in website/docs/user-guide/configuration.md → "Environment Variable Substitution".
- **What it does:** Replaces `${NAME}` or `${env:NAME}` inside string values with the process environment value at load time, so secrets can stay in `.env` while config references them.
- **How it works:** `_expand_env_vars` (config.py:2931) recurses dicts/lists and regex-substitutes `\${([^}]+)}` in strings only (keys, numbers, bools untouched) via `_env_expand_match` (config.py:2871): `env:NAME` → `os.environ[NAME]` (missing → keep the literal, log a WARNING naming `~/.hermes/.env`); bare `NAME` → `os.environ.get(NAME, literal)`; any other `source:` prefix (e.g. `bitwarden:FOO`, `vault:`) warns once that config refs must be `${env:NAME}` (vault backends inject env vars via the `secrets:` block) and stays verbatim. `_env_ref_snapshot` records each referenced var's value so a later `load_config()` re-expands when the environment changed (late `.env` load, in-process rotation, #58514). On save, `_preserve_env_ref_templates` (config.py:2994) writes the original `${…}` template back instead of the expanded secret whenever the value is unchanged, matching list items by `name` (custom_providers) or position. Managed-scope refs are expanded only against the process env, never user-defined refs (config.py:4039).
- **Inputs / options:** `${NAME}`, `${env:NAME}`; whitespace inside braces is stripped.
- **Outputs / side effects:** expanded values in memory only; WARNING logs for unresolved `env:` refs and non-env sources.
- **Config / env:** any string key; any env var.
- **Edge cases / guards:** unresolved refs remain the literal `${…}` so callers can detect them; templates survive `hermes config set` of unrelated keys and dashboard saves.
- **Rebuild notes:** regex substitution on strings + a snapshot of referenced env values for cache invalidation + template preservation on write-back. Better: support `${file:path}` and default values `${VAR:-default}`.

### Managed scope — administrator-pinned config and env (`/etc/hermes`)  `id: config-b.core.managed_scope`
- **Surface:** Config | Env | CLI
- **Where:** files `/etc/hermes/config.yaml` and `/etc/hermes/.env` (or `$HERMES_MANAGED_DIR`); `hermes config` prints "⚷ Some settings are managed by your administrator (<dir>) and cannot be changed", "Managed config keys: …", "Managed env keys: …"; `hermes config set` refuses with "Cannot set '<key>': it is managed by your administrator (<dir>/config.yaml) and cannot be changed. Contact your administrator to modify it."; docs website/docs/user-guide/managed-scope.md.
- **What it does:** Lets IT ship immutable per-key values that override the user's config.yaml/.env leaf by leaf, without blocking the user from editing everything else.
- **How it works:** `managed_scope.get_managed_dir()` (managed_scope.py:56-71): `HERMES_MANAGED_DIR` (non-empty AND existing dir) → else `/etc/hermes` if it is a directory (ignored under pytest). `load_managed_config()`/`load_managed_env()` read with an `(mtime_ns, size)` cache and fail OPEN: a malformed file logs "managed scope: failed to parse … IGNORING this managed file. Admin policy from this file is NOT being applied." (managed_scope.py:86-118). `apply_managed_overlay(config)` (managed_scope.py:139-176) and `_load_config_impl` normalise the managed root `model` key (bare string → `model.default`), expand `${VAR}` against the process env only, then `_deep_merge` managed ON TOP. `managed_config_keys()` flattens the managed YAML to dotted leaves; `is_key_managed(key)` / `is_env_managed(name)` gate writers: `set_config_value`/`unset_config_value` exit 1 (config.py:5765-5773, 6025-6035); `save_env_value`/`remove_env_value` print "Cannot set/remove X: it is managed by your administrator (…)" (config.py:4549-4560, 4660-4670); `save_config` strips managed leaves from bulk writes and prints "Note: N managed setting(s) were not saved (managed by your administrator): a, b" (config.py:4196-4208). The managed file's mtime/size is folded into the load cache signature so edits invalidate immediately.
- **Inputs / options:** env `HERMES_MANAGED_DIR`; files `config.yaml` (YAML mapping) and `.env` (`KEY=VALUE`, quotes stripped) inside the managed dir.
- **Outputs / side effects:** effective config values replaced; user-facing refusals; stderr notes on bulk saves.
- **Config / env:** every dotted key may be pinned; every env var may be pinned.
- **Edge cases / guards:** v1 enforcement is filesystem permissions only (root-owned dir); distinct from and combinable with the package-manager lock; a user `${VAR}` cannot shadow a managed literal because managed expansion ignores user refs.
- **Rebuild notes:** a second config layer with leaf-level precedence + writer guards keyed on the flattened managed key set. Better: signed policy bundles and a `hermes config explain <key>` that shows which layer supplied the value.

### Package-manager managed install lock (`HERMES_MANAGED`, `.managed`, `.container-mode`)  `id: config-b.core.managed_install_lock`
- **Surface:** Config | Env | CLI
- **Where:** env `HERMES_MANAGED`, marker file `<HERMES_HOME>/.managed`, container marker `<HERMES_HOME>/.container-mode`; error text "Cannot <action>: this Hermes installation is managed by <system>.\nUse your package manager to upgrade or reinstall Hermes." on `hermes config set/unset/edit`, `save_config`, `.env` writes.
- **What it does:** Declarative installs (NixOS module, home-manager) mark the install as managed so Hermes refuses to mutate config.yaml/.env and points users at their package manager.
- **How it works:** `get_managed_system()` (config.py:402-429): `HERMES_MANAGED` env (lower-cased) else the `.managed` marker's content; `""`, `true`, `1`, `yes` → legacy `nixos`; `brew`/`homebrew` are ignored (Homebrew no longer supported). `is_managed()` → truthy system. `managed_error(action)` prints `format_managed_message`. `get_managed_update_command()` returns the Nix update sentence for `nixos`/`home-manager`. `detect_install_method()`/`stamp_install_method()` (config.py:472-611) classify git/pip/nix/docker installs. `get_container_exec_info()` (config.py:717-766) parses `.container-mode` (`backend=docker`, `container_name=hermes-agent`, `exec_user=hermes`, `hermes_bin=/data/current-package/bin/hermes`) so the host CLI execs into the NixOS container unless `HERMES_DEV=1` or already inside a container. `_secure_dir`/`_secure_file` are skipped in managed mode (NixOS uses 0750/0640 group-shared perms).
- **Inputs / options:** env `HERMES_MANAGED` (`nixos`|`home-manager`|`true`|…), `HERMES_DEV=1`; marker files above.
- **Outputs / side effects:** writes refused with stderr message; `hermes update` shows the Nix instructions.
- **Config / env:** n/a.
- **Edge cases / guards:** `_secure_dir` also honours the mode for containers; an unknown marker string is still treated as "managed by <string>".
- **Rebuild notes:** boolean lock derived from env/marker; short-circuit every writer. Better: allow a per-key allowlist of user-editable settings even under managed installs.

### Corrupt config.yaml recovery (backup + last-known-good + refuse-write)  `id: config-b.core.corrupt_config_recovery`
- **Surface:** Core | Config
- **Where:** stderr line "⚠️  hermes config: Failed to parse <path>: <err>. …" plus `agent.log`/`errors.log` WARNING; backup file `config.yaml.corrupt.<YYYYmmdd-HHMMSS>.bak` next to the config.
- **What it does:** When config.yaml is not valid YAML, Hermes warns once per file version, snapshots the broken file, and either keeps the previously loaded config (running process) or falls back to defaults (fresh process); write paths refuse to overwrite it.
- **How it works:** `_warn_config_parse_failure(path, exc, fallback)` (config.py:102-165) dedups on `(path, mtime_ns, size)` in `_CONFIG_PARSE_WARNED`, calls `_backup_corrupt_config` (config.py:48-99: skips symlinks and empty files, skips when an existing `.corrupt.*.bak` has the same size, `shutil.copy2`), then logs one of three messages: defaults ("Falling back to default config — every user override … is being IGNORED. Fix the YAML and restart."), last-known-good ("Keeping the previously loaded config for this process — edits to config.yaml are being IGNORED until the YAML is fixed."), refuse-write ("REFUSING to write config.yaml so the existing file is preserved. Fix the YAML (hermes config edit) and retry."). `require_readable_config_before_write()` (config.py:3612-3655) and `_load_user_config_for_mutation` raise `RuntimeError("Refusing to overwrite …")` for unreadable, unparseable or non-mapping files; `atomic_config_write()` (config.py:3696) is the single chokepoint that runs that guard before `atomic_yaml_write`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `.bak` file; stderr/log warnings; `hermes config set` prints "✗ Refusing to overwrite …" and exits 1.
- **Config / env:** n/a.
- **Edge cases / guards:** never mutates the live config.yaml (unlike Gemini CLI's reset policy); backups are best-effort and swallowed on error.
- **Rebuild notes:** dedup key on file identity, copy-on-first-warning, keep last good dict in memory, fail closed on writes. Better: offer `hermes config repair` that shows a diff against the last good copy.

### Saving config (`save_config`: default-stripping, template preservation, commented sections)  `id: config-b.core.save_config`
- **Surface:** Core | Config
- **Where:** called by `hermes setup`, `hermes model`, migrations, dashboard `PUT /api/config` and `PUT /api/config/raw`, plugins; not a user command itself.
- **What it does:** Writes a config dict back to `config.yaml` while omitting values that merely equal the schema default, preserving `${VAR}` templates, and appending helpful commented-out sections.
- **How it works:** `save_config(config, *, strip_defaults=True, preserve_keys=None, merge_existing=False)` (config.py:4169-4283): refuses in managed-install mode; strips managed-scope leaves; `require_readable_config_before_write`; computes the set of leaf paths the user explicitly wrote (`_explicit_config_paths` on the raw file) so those survive stripping even when equal to defaults; `merge_existing=True` deep-merges the on-disk raw file under the partial dict (`_merge_partial_save`, used by migrations); normalises model/max_turns keys; `_preserve_env_ref_templates`; `_strip_default_values` (config.py:3083) removes leaves equal to DEFAULT_CONFIG and prunes emptied subtrees (always keeps `_config_version`); appends `_SECURITY_COMMENT` when `security.redact_secrets` is absent and `_FALLBACK_COMMENT` (provider list openrouter/openai-codex/nous/zai/kimi-coding/kimi-coding-cn/minimax/minimax-cn/bedrock) when no valid `fallback_model`; `atomic_yaml_write(path, normalized, extra_content=…)`; `_secure_file`; drops `_RAW_CONFIG_CACHE` entry and updates `_LAST_EXPANDED_CONFIG_BY_PATH`. `_persist_migration` wraps it for migrations under the invariant "never materialise pure defaults" (config.py:2506-2529). `write_platform_config_field(platform, field, value, raw=False)` (config.py:3763) persists one scalar under `platforms.<platform>`.
- **Inputs / options:** `strip_defaults`, `preserve_keys` (set of path tuples), `merge_existing`.
- **Outputs / side effects:** rewritten `config.yaml` (new inode, 0600), stderr note for stripped managed keys.
- **Config / env:** all keys.
- **Edge cases / guards:** full-document callers (raw YAML editor) pass `merge_existing=False` so deletions survive; `hermes config set` deliberately bypasses `save_config` and writes the raw user file to avoid dumping defaults.
- **Rebuild notes:** diff-against-defaults writer with explicit-path preservation and atomic replace. Better: keep YAML comments/ordering via a round-trip parser (ruamel) so hand-written comments survive saves.

### Config schema versioning & migrations (`_config_version`, support floor, migration ladder)  `id: config-b.core.migrations`
- **Surface:** Core | CLI | Config
- **Where:** `hermes config migrate`, `hermes config check`, `hermes update` (prints "Config version: <old> → <new>" and "N new config option(s) available"), `hermes setup`; key `_config_version` in config.yaml.
- **What it does:** Upgrades an older config.yaml to the current schema by applying versioned steps, prompting for newly introduced API keys and skill settings, and stamping `_config_version`.
- **How it works:** `check_config_version()` (config.py:2184-2214) reads the RAW file's `_config_version` (missing/invalid → 0) versus `DEFAULT_CONFIG["_config_version"]` = 39. `migrate_config(interactive, quiet)` (config.py:2532-2798): (1) `sanitize_env_file()`; (2) support floor: a file with an EXPLICIT version < `SUPPORT_FLOOR_VERSION` = 12 is refused untouched with "This config predates version 12 (~2 years old) and can no longer be auto-migrated. Back up ~/.hermes/config.yaml and run `hermes setup` to regenerate, or manually set _config_version: 12 after reviewing the changelog." (config_migrations.py:53-66); a file with NO version key is migrated normally; (3) `run_migrations(current_ver, results, quiet)` applies every registry step whose target > current, all gated on the initial version (config_migrations.py:869-910): 12 custom_providers list → `providers:` dict; 13 clear dead `LLM_MODEL`/`OPENAI_MODEL` from .env; 14 flat `stt.model` → provider section; 16 `display.tool_progress_overrides` → `display.platforms`; 17 drop `compression.summary_*`; 21 grandfather installed user plugins into `plugins.enabled`; 23 seed the `curator` section + create `logs/curator/`; 25 `model_catalog.ttl_hours` 24 → 1 (only if still 24); 29 `write_mode` → `write_approval` (memory/skills); 31 `agent.verify_on_stop` auto → off; 32 literal `verify_on_stop: true` → off; 33 fold `delegation.max_async_children` into `max_concurrent_children`; 34 one-time personality reset; 35 `display.background_process_notifications` all → concise; 36 `delegation.max_iterations` 50 → 250; 37 `delegation.max_concurrent_children` 3 → 10; 38 remove the retired `observability/nemo_relay` plugin keys; 39 strip the retired `bfl` toolset from saved lists; (4) post-migration: `mcp_servers` entries failing `mcp_security.validate_mcp_server_entry` get `enabled: false` ("Disabled suspicious MCP server '<name>'"); (5) `platform_toolsets` names validated (#38798); (6) required env vars (`REQUIRED_ENV_VARS` is empty) and NEW optional vars since the old version (`ENV_VARS_BY_VERSION`: v3 FIRECRAWL_API_KEY/BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID/FAL_KEY, v4 VOICE_TOOLS_OPENAI_KEY/ELEVENLABS_API_KEY, v5 WHATSAPP_ENABLED/WHATSAPP_MODE/WHATSAPP_ALLOWED_USERS/SLACK_BOT_TOKEN/SLACK_APP_TOKEN/SLACK_ALLOWED_USERS, v11 TERMINAL_MODAL_MODE) are offered interactively ("Configure new keys? [y/N]"); (7) `get_missing_config_fields()` lists default keys absent from the effective config for display only; (8) version bump persisted via `_persist_migration`; (9) skill-declared settings (`metadata.hermes.config` in SKILL.md) missing under `skills.config.<key>` are prompted ("Configure skill settings? [y/N]").
- **Inputs / options:** `interactive` (prompts), `quiet`.
- **Outputs / side effects:** rewritten config.yaml/.env; result dict `{env_added, config_added, warnings}`; console lines "✓ Normalized .env line formatting", "✓ Saved <VAR>", "⚠ …".
- **Config / env:** `_config_version`; `mcp_servers.*.enabled`; `platform_toolsets`; `skills.config.*`.
- **Edge cases / guards:** steps never write schema defaults (`_persist_migration` invariant); an unparseable file skips migration with the parse warning; `_coerce_config_version` treats booleans/garbage as 0.
- **Rebuild notes:** table of `(target_version, fn)` steps gated on the on-disk version, plus a floor. Better: record applied step ids in the file so partially failed migrations can resume.

### Config structure validation & startup warnings  `id: config-b.core.structure_validation`
- **Surface:** Core | CLI
- **Where:** stderr block "⚠ Config issues detected in config.yaml:" … "Run 'hermes doctor' for fix suggestions." printed early by the CLI and gateway; "⚠ Deprecated .env settings detected:" for `MESSAGING_CWD`/`TERMINAL_CWD`.
- **What it does:** Detects common YAML shape mistakes that would otherwise surface as cryptic "Unknown provider" errors.
- **How it works:** `validate_config_structure(config)` (config.py:2279-2439) returns `ConfigIssue(severity, message, hint)` items for: `voice.submit_mode` not `direct|draft` (error); `custom_providers` written as a dict instead of a list (error, with a corrected snippet) and root keys that look like provider fields (`base_url`, `api_key`, `rate_limit_delay`, `api_mode`); list entries that are not dicts / missing `name` / missing `base_url` (warnings); `fallback_model` as list (each entry needs provider+model), non-dict (error), or missing provider/model (warning — "fallback will be disabled"); `fallback_model` nested inside `custom_providers` (error); `custom_providers` without a `model` section (warning); root-level provider-like keys (warning). Arbitrary unknown root keys are NOT flagged because top-level scalars are bridged into `os.environ` for skills. Known roots = `DEFAULT_CONFIG.keys()` ∪ `_EXTRA_KNOWN_ROOT_KEYS` (config.py:2225-2254, listed in `config-b.hidden.extra_root_keys`). `print_config_warnings` renders ✗ (error) / ⚠ (warning) markers. `warn_deprecated_cwd_env_vars` (config.py:2464) reads `.env` directly and tells the user to move to `terminal.cwd`.
- **Inputs / options:** optional pre-loaded config dict.
- **Outputs / side effects:** stderr text only.
- **Config / env:** `voice.submit_mode`, `custom_providers`, `fallback_model`, `model`; env `MESSAGING_CWD`, `TERMINAL_CWD`.
- **Edge cases / guards:** any exception inside validation is swallowed (never blocks startup).
- **Rebuild notes:** a list of shape predicates producing (severity, message, hint). Better: JSON-schema validation with line numbers from a round-trip YAML parser.

### Dotted key-path syntax for `hermes config get/set/unset`  `id: config-b.core.key_path_syntax`
- **Surface:** CLI | Config
- **Where:** the `<key>` argument of `hermes config get|set|unset`; errors "✗ Invalid config key: 'agent.' — contains an empty path segment (leading, trailing, or doubled '.')." and "✗ Refusing to create nested key 'grok-4' in 'providers.p.models.grok-4.context_length': the mapping already contains a literal key 'grok-4.5' that contains a dot. If you meant that key, escape its dots with a backslash (e.g. grok-4\.5)."
- **What it does:** Maps `a.b.c` onto nested YAML mappings and lists, tolerating keys that themselves contain dots (model ids, Matrix room ids).
- **How it works:** `_split_key_path` (config.py:1059) splits on `.` except `\.`; `_greedy_literal_match` (config.py:1093) prefers an EXISTING literal key equal to the dot-join of the next N segments (longest wins) so `providers.p.models.grok-4.6.context_length` lands on the real `grok-4.6` entry; `_phantom_sibling` (config.py:1118) makes `_set_nested` raise `ValueError` when creating an intermediate mapping would shadow an existing dotted sibling; numeric segments index lists (`custom_providers.0.api_key`) but never grow them; a scalar hit mid-path is replaced by a fresh dict (legacy behaviour); `_get_nested` returns a `_MISSING` sentinel; `_unset_nested` (config.py:1287) deletes and then prunes emptied `{}` containers while preserving user-authored empty lists.
- **Inputs / options:** dotted key string; `\.` escape.
- **Outputs / side effects:** n/a.
- **Config / env:** all keys.
- **Edge cases / guards:** whitespace-padded or empty keys exit 1; `_set_nested` into a list with a non-numeric segment raises `TypeError`.
- **Rebuild notes:** split-with-escape + greedy literal match + phantom-sibling refusal. Better: expose `hermes config keys <prefix>` for discovery.

### Value coercion & guards in `hermes config set`  `id: config-b.core.set_value_coercion`
- **Surface:** CLI | Config
- **Where:** `hermes config set [--force] <key> <value>` echo lines "✓ Set <key> = <value> in <path>", "✓ Redirecting bare 'model' to 'model.default' (preserving N existing model sub-key(s))", "⚠ Replacing entire 'model' section with a scalar (discarding N existing sub-key(s))", "✗ Cannot set '<key>' to a scalar — '<key>' is a configuration section with N sub-key(s)." + "Sub-keys: …" + "Use a dotted path to set a specific leaf key:" + "Or use --force to replace the entire section:", "(note: 'api_base' is an alias — saved as model.base_url)".
- **What it does:** Converts the CLI string into the right YAML type and protects mapping sections from accidental overwrite.
- **How it works:** `set_config_value(key, value, force)` (config.py:5726-5998): managed-install and managed-scope guards; env-shaped keys go to `.env` via `credential_lifecycle.save_provider_env_credential` (prints "✓ Set <KEY> in <env path>"); `_validate_config_key` (see `config-b.core.key_validation`); reads the RAW user file fail-closed; coercion only when the DEFAULT_CONFIG leaf is NOT a string (`_default_value_for_key`): `true|yes|on` → True, `false|no|off` → False, `null|none|~` → None (CFG-05), `_coerce_int` (accepts signs, spaces, underscores; CFG-02), `_coerce_float` (only when the decimal round-trips exactly; NaN/inf rejected), `_looks_structured_value` (`[`/`{` prefix or multi-line `- item`/`key: value`) → `yaml.safe_load` list/mapping with warnings "looks like a list/mapping but parsed as …; storing as string" / "not valid YAML/JSON; storing as string"; a bare-string `model:` is promoted to `{default: …}` before setting `model.*`; single-segment key naming an existing mapping: `model` → redirected to `model.default`, others refused unless `--force` (exit 1); `_set_nested`; `api_base` alias normalised to `model.base_url`; `atomic_yaml_write(path, user_config, sort_keys=False)`; terminal keys mirrored to `.env` via `TERMINAL_CONFIG_ENV_MAP` (except `terminal.cwd`); `display.skin` touches `skins/<name>.yaml`; credential-shaped leaf names (`_SECRET_CONFIG_KEYS`: api_key, apikey, key, token, access_token, refresh_token, id_token, secret, client_secret, password, passwd, auth, authorization, private_key, bearer, jwt) are masked in the echo; `warn_unpinned_cron_jobs_after_model_config_change` warns about cron jobs without pinned models; unknown keys print "⚠ '<key>' is not a recognized config key — it was saved anyway, but Hermes may not read it." + "Did you mean: <suggestion>" + "(Custom top-level keys are supported and bridged to the environment for skills/external tools. Use --force to skip this notice.)".
- **Inputs / options:** `--force`; `key`; `value` (string, may be multi-line YAML).
- **Outputs / side effects:** raw config.yaml rewritten (defaults NOT dumped), possibly `.env`; stdout/stderr lines above.
- **Config / env:** any key; `.env` for terminal mirror keys.
- **Edge cases / guards:** string-typed settings such as `approvals.mode: off` are never coerced to booleans; the write goes to the raw file so a value equal to the default is persisted explicitly.
- **Rebuild notes:** type-directed coercion using the default's type + section-overwrite refusal + alias normalisation. Better: validate against per-key enums/ranges from the schema before writing.

### Unknown-key validation & "did you mean" suggestions  `id: config-b.core.key_validation`
- **Surface:** CLI | Config
- **Where:** post-write notice of `hermes config set` (see above).
- **What it does:** Decides whether a dotted key is known to the schema, accepting user-defined sub-keys under open containers, and suggests the closest valid path on typos.
- **How it works:** `_validate_config_key` (config.py:5559-5652): keys whose first segment starts with `_` are internal and accepted; `platforms.<name>.…` accepted (`_PLATFORM_CONTAINER_KEYS`); first segment must be in `DEFAULT_CONFIG` ∪ `_OPEN_DICT_TOP_LEVEL_KEYS` {providers, credential_pool_strategies, mcp_servers, hooks, quick_commands, personalities, command_allowlist, model_catalog, channel_prompts, server_actions, secrets, goals, loops} ∪ `_DYNAMIC_TOP_LEVEL_KEYS` {custom_providers} ∪ `_SCHEMA_DEFINED_DICT_KEYS` {discord, telegram, slack, whatsapp, signal, mattermost, matrix, feishu, wecom, weixin, bluebubbles, qqbot, yuanbao, email, sms, dingtalk, sessions, checkpoints, plugins}; anything below an open/schema-defined/dynamic root is accepted; otherwise DEFAULT_CONFIG is walked segment by segment, stopping at a nested `platforms` container or a scalar leaf, and an unknown sub-key yields the closest sibling via `difflib.get_close_matches(cutoff=0.6)`. Headline case #34067: `gateway.discord.gateway_restart_notification` → suggests `discord.gateway_restart_notification`.
- **Inputs / options:** key string.
- **Outputs / side effects:** `(is_known, suggestion)`.
- **Config / env:** n/a.
- **Edge cases / guards:** the value is always written; validation only affects the notice; `--force` suppresses it.
- **Rebuild notes:** walk defaults with allow-listed open containers. Better: derive open containers from a schema annotation instead of hard-coded sets.

### Env-shaped keys routed to `.env` by `hermes config set/get/unset`  `id: config-b.core.env_shaped_keys`
- **Surface:** CLI | Env
- **Where:** `hermes config set OPENROUTER_API_KEY sk-or-…` → "✓ Set OPENROUTER_API_KEY in ~/.hermes/.env"; `hermes config unset OPENROUTER_API_KEY` → "✓ Unset OPENROUTER_API_KEY from ~/.hermes/.env"; `hermes config get OPENROUTER_API_KEY`.
- **What it does:** Treats undotted, credential-looking keys as environment variables stored in `.env` instead of config.yaml.
- **How it works:** `_is_env_config_key` (config.py:1360-1380): no `.` in the key AND (upper-cased name is in the explicit list OPENROUTER_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, VOICE_TOOLS_OPENAI_KEY, EXA_API_KEY, PARALLEL_API_KEY, FIRECRAWL_API_KEY, FIRECRAWL_API_URL, FIRECRAWL_GATEWAY_URL, TOOL_GATEWAY_DOMAIN, TOOL_GATEWAY_SCHEME, TOOL_GATEWAY_USER_TOKEN, BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, BROWSER_USE_API_KEY, FAL_KEY, TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN, TERMINAL_SSH_HOST, TERMINAL_SSH_USER, TERMINAL_SSH_KEY, SUDO_PASSWORD, SLACK_BOT_TOKEN, SLACK_APP_TOKEN, GITHUB_TOKEN, HONCHO_API_KEY, OR ends with `_API_KEY`/`_TOKEN`/`_SECRET`, OR starts with `TERMINAL_SSH`). Set → `credential_lifecycle.save_provider_env_credential` (also rotates config.yaml mirrors of the old value, #62269); unset → `remove_provider_env_credential` (prunes credential-pool entries and model-cache rows, #51071); get → `get_env_value(key.upper())`.
- **Inputs / options:** key name (case-insensitive).
- **Outputs / side effects:** `.env` line added/updated/removed; `os.environ` updated.
- **Config / env:** `.env`.
- **Edge cases / guards:** dotted keys are never env-routed even if they end in `_TOKEN`.
- **Rebuild notes:** name heuristic → separate secrets store. Better: an explicit `hermes env set` command (exists elsewhere) and a schema flag per env var.

### `.env` file reader/writer (`load_env`, `save_env_value`, `remove_env_value`, `reload_env`, `get_env_value`)  `id: config-b.core.dotenv_file`
- **Surface:** Core | Env
- **Where:** `~/.hermes/.env`; used by setup wizards, `hermes config set <API_KEY>`, dashboard Env page, `hermes secrets … token`.
- **What it does:** Parses and atomically rewrites the secrets file, keeping the process environment in sync.
- **How it works:** `load_env()` (config.py:4308-4372): utf-8-sig with BOM tolerance, `_sanitize_env_lines` normalises line endings without touching values, strips a bash `export ` prefix (#6659), `_parse_env_value` handles `"…"` with `\"`/`\\` escapes and `'…'`; memoised on `(path, mtime, size)`; `invalidate_env_cache()` for writers. `save_env_value(key, value)` (config.py:4544-4633): managed guards; `validate_env_var_name_for_write` (regex `^[A-Za-z_][A-Za-z0-9_]*$` + denylist, see next entry); strips CR/LF; `_check_non_ascii_credential` strips non-ASCII bytes and prints a warning listing offending positions ("Warning: <KEY> contains non-ASCII characters that will break API requests…"); `_quote_env_value` quotes when the value contains `#`, quotes, or any whitespace; replaces the first line that defines the key (`KEY=`, `export KEY=`, `KEY = `) else appends; tempfile + fsync + `atomic_replace`; preserves the original file mode (Docker 0640) else 0600; sets `os.environ[key]`. `remove_env_value` mirrors it and returns whether a line was removed. `reload_env()` re-reads into `os.environ` and deletes vars that vanished but only for known names (`OPTIONAL_ENV_VARS` ∪ `_EXTRA_ENV_KEYS`, config.py:309-383). `get_env_value(key)` reads `os.environ` through `agent.secret_scope.get_secret` (profile-scoped under multiplexing) then `.env`; `get_env_value_prefer_dotenv` inverts the order for Hermes-managed credentials. `custom_endpoint_key_env(identity)` derives `HERMES_CUSTOM_<SLUG>_API_KEY`. `sanitize_env_file()` rewrites the file when normalisation changed anything and returns the count (run by every migration).
- **Inputs / options:** key, value strings.
- **Outputs / side effects:** `.env` rewritten atomically; `os.environ` mutated.
- **Config / env:** n/a.
- **Edge cases / guards:** Windows locale issues avoided by explicit UTF-8; Docker volume permission preserved; `UnscopedSecretError` propagates when a multiplexed turn reads an unscoped secret.
- **Rebuild notes:** line-preserving dotenv editor with atomic replace and an mtime cache. Better: keep secrets in the OS keychain with `.env` as an export format.

### Env-var write denylist (`_ENV_VAR_NAME_DENYLIST`)  `id: config-b.core.env_write_denylist`
- **Surface:** Core | Env
- **Where:** any writer that persists env vars (dashboard Env page, `hermes config set`, setup flows); error "Environment variable 'X' is on the writer denylist. Names that influence subprocess execution (LD_PRELOAD, PYTHONPATH, PATH, EDITOR, ...) or Hermes runtime location and security policy (HERMES_HOME, HERMES_YOLO_MODE, ...) cannot be persisted via the env writer. If you really need this, edit ~/.hermes/.env directly."
- **What it does:** Prevents a writable surface (especially the dashboard) from planting variables that change how the next subprocess executes or where Hermes keeps state.
- **How it works:** `_reject_denylisted_env_var` (config.py:253) compares `_env_var_policy_name` (upper-cased on Windows only) against the frozenset (config.py:207-240): loader `LD_PRELOAD, LD_LIBRARY_PATH, LD_AUDIT, LD_DEBUG, DYLD_INSERT_LIBRARIES, DYLD_LIBRARY_PATH, DYLD_FRAMEWORK_PATH, DYLD_FALLBACK_LIBRARY_PATH, DYLD_FALLBACK_FRAMEWORK_PATH`; Python `PYTHONPATH, PYTHONHOME, PYTHONSTARTUP, PYTHONUSERBASE, PYTHONEXECUTABLE, PYTHONNOUSERSITE`; Node `NODE_OPTIONS, NODE_PATH`; general `PATH, SHELL, BROWSER, EDITOR, VISUAL, PAGER`; git `GIT_SSH_COMMAND, GIT_EXEC_PATH, GIT_SHELL`; Hermes location `HERMES_HOME, HERMES_PROFILE, HERMES_CONFIG, HERMES_ENV, HERMES_CONFIG_PATH, HERMES_ENV_PATH`; `HERMES_OPTIONAL_MCPS`; `HERMES_COPILOT_ACP_COMMAND, HERMES_COPILOT_ACP_ARGS`; security policy `HERMES_YOLO_MODE, HERMES_ACCEPT_HOOKS, HERMES_REDACT_SECRETS, HERMES_INTERACTIVE, HERMES_EXEC_ASK, HERMES_GATEWAY_SESSION, HERMES_CRON_SESSION, HERMES_SINGLE_QUERY_SESSION, HERMES_SESSION_KEY, HERMES_SESSION_PLATFORM`. `HERMES_*` is deliberately NOT blanket-blocked (integration credentials use that prefix).
- **Inputs / options:** env var name.
- **Outputs / side effects:** `ValueError` on write.
- **Config / env:** n/a.
- **Edge cases / guards:** enforced on write only — pre-existing values keep working.
- **Rebuild notes:** name-by-name denylist checked before every persistence write. Better: allow an operator-extended denylist in managed scope.

### Config schema generation for the dashboard/desktop (`CONFIG_SCHEMA`, categories, labels)  `id: config-b.core.schema_generation`
- **Surface:** API | Web dashboard | Desktop app
- **Where:** `GET /api/config/schema[?profile=]` → `{"fields": {<dotted key>: {type, description, category[, options]}}, "category_order": [...]}` (hermes_cli/web_server.py:7285-7292); consumed by web `ConfigPage.tsx` and desktop `config-settings.tsx`.
- **What it does:** Derives a flat, typed field list from DEFAULT_CONFIG so UIs can render a form without a hand-maintained schema.
- **How it works:** `_build_schema_from_config(DEFAULT_CONFIG)` (web_server.py:1525-1560) walks the defaults: `_config_version` skipped; a nested dict recurses (so an EMPTY dict such as `providers: {}` or `auxiliary.vision.extra_body: {}` contributes no field — this is exactly what makes the 42 "hidden" keys of section F invisible); type from `_infer_type` (bool→`boolean`, int/float→`number`, list→`list`, dict→`object`, else `string`); description = dotted path with `.` → ` → `, `_` → space, Title Case (e.g. `discord.voice_fx.ack_phrases` → "Discord → Voice Fx → Ack Phrases"); category = first path segment (top-level scalars → `general`); `_SCHEMA_OVERRIDES` (web_server.py ~1000-1440) replaces type/description/options for a subset of keys (none of the keys in this shard carry an override — every field here is the auto-generated label with the inferred type); `_CATEGORY_MERGE` folds small categories: privacy→security, context/skills/cron/network/models_dev/checkpoints/code_execution/prompt_caching/bot_mode/goals/onboarding/mcp/computer_use/plugins/runtime→agent, approvals→security, human_delay/dashboard→display, updates/doctor/session→general, telegram→discord, telemetry→security. `_CATEGORY_ORDER` = general, agent, terminal, display, delegation, memory, compression, security, browser, voice, tts, stt, logging, discord, auxiliary; the remaining categories (bedrock, curator, database, desktop, gateway, kanban, loops, lsp, matrix, mattermost, moa, model_catalog, monitoring, openrouter, proxy, secrets, sessions, slack, streaming, tool_loop_guardrails, tool_output, tools, vertex, wake_word, web, x_search) sort alphabetically after them in the UI. A virtual `model_context_length` field is injected after `model`. `_schema_with_dynamic_provider_options()` recomputes `tts.provider`, `stt.provider`, `memory.provider`, `terminal.backend` option lists per request.
- **Inputs / options:** query `profile`.
- **Outputs / side effects:** JSON schema; no writes.
- **Config / env:** all keys.
- **Edge cases / guards:** dashboard hides `memory.provider` from the generic form; a `None` default infers type `string` (e.g. `database.wal_autocheckpoint`, `kanban.max_in_progress`, `wake_word.input_device`, `proxy.upstream_deny_cidrs`, `x_search.reasoning_effort`, `gateway.multiplex_profile_allowlist`) so those render as free-text inputs even though the runtime coerces them to ints/lists.
- **Rebuild notes:** reflect over the defaults tree, infer types, Title-Case labels, merge tiny categories. Better: attach min/max/enum/help to each leaf in the defaults file itself.

### Web dashboard "Config" page for this shard's categories  `id: config-b.web.config_page`
- **Surface:** Web dashboard
- **Where:** Dashboard → **Config** (route `/config`, `web/src/pages/ConfigPage.tsx`); sidebar "Filters" (`i18n: config.filters`) / "Sections" (`config.sections`) with one tab per category showing a count badge; tab labels for this shard: "Discord" (`config.categories.discord`), "Auxiliary" (`config.categories.auxiliary`), and — because `web/src/i18n/en.ts` only defines the 15 ordered categories — "Bedrock", "Curator", "Database", "Desktop", "Gateway", "Kanban", "Loops", "Lsp", "Matrix", "Mattermost", "Moa", "Model_catalog", "Monitoring", "Openrouter", "Proxy", "Secrets", "Sessions", "Slack", "Streaming", "Tool_loop_guardrails", "Tool_output", "Tools", "Vertex", "Wake_word", "Web", "X_search" (`prettyCategoryName`: first letter upper-cased, underscores kept, ConfigPage.tsx:158-162). Header buttons: "Export config as JSON" (`config.exportConfig`), "Import config from JSON" (`config.importConfig`), "Reset to defaults" (`config.resetDefaults`, tooltip "Reset {scope} to defaults", confirm "Reset all {scope} settings to their defaults? This only updates the form — changes aren't written to config.yaml until you press Save.", toast "{scope} reset to defaults — review and Save to persist"), Save, and the "Raw YAML Configuration" (`config.rawYaml`) editor; search box with "Search Results" (`config.searchResults`) / "No fields match \"{query}\"" (`config.noFieldsMatch`); toasts "Configuration saved", "YAML config saved", "Failed to save", "Failed to save YAML", "Failed to load raw config", "Config imported — review and save", "Invalid JSON file"; path chip defaults to "~/.hermes/config.yaml" (`config.configPath`).
- **What it does:** Renders every schema field of the active category as a form control and saves the changed subtree.
- **How it works:** loads `GET /api/config` + `GET /api/config/schema`; groups by `category`, sub-headers by first path segment when it differs from the tab; each field is an `AutoField` (`web/src/components/AutoField.tsx:90-200`): label = last path segment Title-Cased with underscores → spaces (so `discord.require_mention` shows "Require Mention"); `boolean` → Switch; `select` → Select (empty option shown as "(none)"); `number` → `<Input type="number">` (empty → 0); `text` → textarea; `list` → text Input with placeholder "comma-separated values" (split on `,`, trimmed); dict/object values → `NestedValueEditor`; default → text Input. Save → `PUT /api/config` with `{config, profile}`; the server deep-merges over the on-disk raw file so unsent keys survive (web_server.py:8150-8185) and broadcasts `session.info` when `approvals.mode` changed. Raw editor → `GET/PUT /api/config/raw` (full replacement, `merge_existing=False`, web_server.py:15654-15694).
- **Inputs / options:** every field in section B–E; search query; profile scope switcher.
- **Outputs / side effects:** config.yaml rewritten through `save_config` (defaults stripped).
- **Config / env:** all shard keys.
- **Edge cases / guards:** list fields typed as comma-separated cannot express nested items (e.g. `moa.presets.default.reference_models`, which contains dicts → falls to `NestedValueEditor`); `None`-default keys appear as empty text inputs.
- **Rebuild notes:** schema-driven form with per-type widgets and merge-on-save. Better: per-key help text, validation ranges, and a "changed vs default" indicator.

### Desktop app Settings → Config (schema-driven)  `id: config-b.desktop.config_settings`
- **Surface:** Desktop app
- **Where:** Hermes Desktop → Settings → "Config" section (`apps/desktop/src/app/settings/config-settings.tsx`, uses `getHermesConfigSchema()` / `saveHermesConfig()`, `ConfigField` per key); auxiliary tasks additionally appear under Settings → Model → "Auxiliary models" (`i18n: settings.model.auxiliaryTitle`, description "Helper tasks run on the main model by default. Assign a dedicated model to any task to override." `settings.model.auxiliaryDesc`).
- **What it does:** Same schema and endpoints as the web Config page, rendered natively in the Electron app with per-profile scope ("Applies to").
- **How it works:** `sectionFieldEntries` groups the schema fields by category; `enumOptionsFor` preserves the current value in select options; `diffConfig` sends only changed keys; autosave via `saveHermesConfig`; `repoDiscoveryPolicyFromConfig` re-scans repos when `desktop.repo_scan_*` change.
- **Inputs / options:** all shard keys; profile scope.
- **Outputs / side effects:** `PUT /api/config`.
- **Config / env:** all shard keys.
- **Edge cases / guards:** see desktop shard for the full settings UI.
- **Rebuild notes:** reuse the web schema. (Details of the Desktop settings UI are handed off.)

### Config REST endpoints  `id: config-b.api.config_endpoints`
- **Surface:** API
- **Where:** `GET /api/config[?profile]` (effective config normalised for the web: `model` flattened to a string plus virtual `model_context_length`, keys starting with `_` stripped; web_server.py:7264-7278), `GET /api/config/defaults` (raw DEFAULT_CONFIG), `GET /api/config/schema[?profile]`, `PUT /api/config` (body `ConfigUpdate{config, profile}`; `_denormalize_config_from_web` re-nests `model`; deep-merge + `save_config`), `GET /api/config/raw[?profile]` → `{yaml, path}`, `PUT /api/config/raw` (body `RawConfigUpdate{yaml_text, profile}`; 400 "YAML must be a mapping" / "Invalid YAML: …"; full replacement). All run under `_profile_scope(profile)` in a worker thread and `_CONFIG_MUTATION_LOCK`.
- **What it does:** Read/write the configuration for the dashboard, desktop and scripts.
- **How it works:** as above; auth via the dashboard session token header/cookie (dashboard-auth shard).
- **Inputs / options:** query `profile`; JSON bodies above.
- **Outputs / side effects:** `{"ok": true}`; config.yaml rewritten.
- **Config / env:** all keys.
- **Edge cases / guards:** a profile-scoped save targets that profile's HERMES_HOME; `approvals.mode` change triggers a `session.info` broadcast only for the own profile.
- **Rebuild notes:** four endpoints over `load_config`/`save_config`. Better: PATCH with JSON-merge-patch semantics and ETag concurrency.

## A2. `hermes config` command family (`hermes_cli/config.py:config_command`, help from `cli_help/config*.txt`)

### `hermes config` (parent)  `id: config-b.cli.config`
- **Surface:** CLI
- **Where:** `hermes config [-h] {show,edit,get,set,unset,path,env-path,check,migrate} ...` — "Manage Hermes Agent configuration".
- **What it does:** Dispatches to the sub-commands below; with no sub-command behaves like `show`.
- **How it works:** `config_command(args)` (config.py:6072-6255) switches on `args.config_command`; an unknown sub-command prints "Unknown config command: X" plus the list "hermes config           Show current configuration / edit / get <key> / set <key> <value> / unset <key> / check / migrate / path / env-path" and exits 1.
- **Inputs / options:** `-h/--help`; sub-commands show, edit, get, set, unset, path, env-path, check, migrate.
- **Outputs / side effects:** see each sub-command.
- **Config / env:** n/a.
- **Edge cases / guards:** none.
- **Rebuild notes:** argparse sub-parsers.

### `hermes config show`  `id: config-b.cli.config_show`
- **Surface:** CLI
- **Where:** `hermes config` or `hermes config show` — "Show current configuration".
- **What it does:** Prints a human summary of the effective configuration with secrets masked.
- **How it works:** `show_config()` (config.py:4925-5144) prints the boxed header "⚕ Hermes Configuration", the managed-scope notice when applicable, then sections: "◆ Paths" (Config/Secrets/Install); "◆ API Keys" (OpenRouter, OpenAI (STT/TTS), Exa, Parallel, Firecrawl, Browserbase, Browser Use, FAL, Anthropic — masked via `redact_key`, "(not set)" dimmed); "◆ Model" (Model: redacted model section, Max turns:, plus a warning "⚠ .env has stale HERMES_MAX_ITERATIONS=… (run 'hermes doctor --fix' to remove)" when `.env` disagrees); "◆ Display" (Personality, Reasoning on/off, Bell on/off, User preview first/last lines); "◆ Terminal" (Backend, Working dir, Timeout, then backend-specific lines: Docker image / Image / Modal image+token / Daytona image+API key / Vercel runtime+auth / SSH host+user); "◆ Timezone" ("(server-local)" when empty); "◆ Context Compression" (Enabled, Threshold %, Token cap, Target ratio, Protect last/first, Model, Provider); "◆ Auxiliary Models (overrides)" only when `auxiliary.vision` deviates from auto; "◆ Messaging Platforms" (Telegram/Discord configured or "not configured" from bot tokens); "◆ Skill Settings" (skill-declared `skills.config.*` vars with `[skill]` tags); footer hints "hermes config edit", "hermes config set <key> <value>", "hermes setup".
- **Inputs / options:** none.
- **Outputs / side effects:** stdout only.
- **Config / env:** reads everything; env keys listed above.
- **Edge cases / guards:** `auxiliary` section is summarised only for Vision — other aux tasks are visible via `hermes config get auxiliary.<task>`.
- **Rebuild notes:** curated pretty-printer over `load_config()`.

### `hermes config edit`  `id: config-b.cli.config_edit`
- **Surface:** CLI
- **Where:** `hermes config edit` — "Open config file in editor".
- **What it does:** Opens `config.yaml` in `$EDITOR`/`$VISUAL` or a detected editor, creating the file with full defaults if absent.
- **How it works:** `edit_config()` (config.py:5147-5184): managed-install guard; if the file does not exist → `save_config(DEFAULT_CONFIG, strip_defaults=False)` and print "Created <path>"; editor = `EDITOR` or `VISUAL`, else first found of `nano, vim, vi, code, notepad` (POSIX) / `notepad, code, vim, vi, nano` (Windows); prints "Opening <path> in <editor>..." and runs `subprocess.run([editor, path])`; if none found prints "No editor found. Config file is at:".
- **Inputs / options:** env `EDITOR`, `VISUAL`.
- **Outputs / side effects:** may create a full-defaults config.yaml (the only path that dumps every default).
- **Config / env:** n/a.
- **Edge cases / guards:** refuses in managed-install mode.
- **Rebuild notes:** trivial; better to open in the dashboard's raw editor when headless.

### `hermes config get <key> [--json]`  `id: config-b.cli.config_get`
- **Surface:** CLI
- **Where:** `hermes config get [-h] [--json] [key]` — positional `key` "Configuration key (e.g., model)", `--json` "Print value as JSON"; usage hint prints examples `hermes config get model`, `hermes config get terminal.backend`, `hermes config get skills.config --json`.
- **What it does:** Prints one resolved value from the effective config (or `.env` for env-shaped keys).
- **How it works:** `get_config_value` (config.py:6000-6012): env-shaped keys → `get_env_value`; else `_get_nested(load_config(), key)`; missing → stderr "Config key not set: <key>" exit 1; `_format_config_get_value`: `--json` → `json.dumps`, bools → `true`/`false`, None → `null`, dict/list → YAML block, else `str`.
- **Inputs / options:** `key`, `--json`.
- **Outputs / side effects:** stdout.
- **Config / env:** any.
- **Edge cases / guards:** values are NOT masked (prints secrets) — the effective (merged + managed) value is shown, not the raw file's.
- **Rebuild notes:** nested lookup + formatter.

### `hermes config set [--force] <key> <value>`  `id: config-b.cli.config_set`
- **Surface:** CLI
- **Where:** `hermes config set [-h] [--force] [key] [value]` — `key` "Configuration key (e.g., model, terminal.backend)", `value` "Value to set", `--force` "Skip the unknown-key notice printed after writing a key the running version doesn't recognize (the value is saved either way)."; usage examples `hermes config set model anthropic/claude-sonnet-4`, `hermes config set terminal.backend docker`, `hermes config set OPENROUTER_API_KEY sk-or-...`.
- **What it does:** Writes one value into the raw config.yaml (or `.env`) with type coercion and safety guards.
- **How it works:** see `config-b.core.set_value_coercion`, `config-b.core.key_validation`, `config-b.core.key_path_syntax`, `config-b.core.env_shaped_keys`. `RuntimeError` from the fail-closed writer is printed as "✗ <msg>" exit 1.
- **Inputs / options:** `--force`, `key`, `value`.
- **Outputs / side effects:** config.yaml / .env rewritten.
- **Config / env:** any.
- **Edge cases / guards:** managed guards; section-overwrite refusal.
- **Rebuild notes:** see referenced entries.

### `hermes config unset <key>`  `id: config-b.cli.config_unset`
- **Surface:** CLI
- **Where:** `hermes config unset [-h] [key]` — `key` "Configuration key to remove"; examples `hermes config unset model`, `hermes config unset terminal.backend`, `hermes config unset OPENROUTER_API_KEY`.
- **What it does:** Removes a user-set key so the schema default (or managed value) applies again.
- **How it works:** `unset_config_value` (config.py:6015-6069): managed guards; env-shaped → `remove_provider_env_credential`; else `_unset_nested` on the raw file, mirrored `.env` removal for terminal keys, "Config key not set: <key>" exit 1 when absent, `atomic_yaml_write`, prints "✓ Unset <key> from <path>".
- **Inputs / options:** `key`.
- **Outputs / side effects:** config.yaml / .env rewritten; empty parent mappings pruned.
- **Config / env:** any.
- **Edge cases / guards:** cannot unset managed keys.
- **Rebuild notes:** nested delete + prune.

### `hermes config path` / `hermes config env-path`  `id: config-b.cli.config_path`
- **Surface:** CLI
- **Where:** `hermes config path` — "Print config file path"; `hermes config env-path` — "Print .env file path".
- **What it does:** Prints the resolved `config.yaml` / `.env` path for the active profile.
- **How it works:** `print(get_config_path())` / `print(get_env_path())` (config.py:6127-6131).
- **Inputs / options:** none.
- **Outputs / side effects:** one line on stdout.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** none.
- **Rebuild notes:** trivial.

### `hermes config check`  `id: config-b.cli.config_check`
- **Surface:** CLI
- **Where:** `hermes config check` — "Check for missing/outdated config".
- **What it does:** Non-interactive status of schema version and which env vars are set.
- **How it works:** config.py:6191-6225 prints "📋 Configuration Status", "Config version: N ✓" or "Config version: N → M (update available)", "Required:" (empty set) with ✓/✗, "Optional:" listing every `OPTIONAL_ENV_VARS` name as "✓ NAME" or dimmed "○ NAME → tool1, tool2", and "N new config option(s) available / Run 'hermes config migrate' to add them" when `get_missing_config_fields()` is non-empty.
- **Inputs / options:** none.
- **Outputs / side effects:** stdout.
- **Config / env:** `_config_version`; all optional env vars.
- **Edge cases / guards:** none.
- **Rebuild notes:** status printer.

### `hermes config migrate`  `id: config-b.cli.config_migrate`
- **Surface:** CLI
- **Where:** `hermes config migrate` — "Update config with new options".
- **What it does:** Interactive migration: shows what is outdated, then runs `migrate_config(interactive=True)`.
- **How it works:** config.py:6133-6189: prints "🔄 Checking configuration for updates...", "✓ Configuration is up to date!" when nothing to do; else "Config version: a → b", "N new config option(s) will be added with defaults" (informational — defaults are not materialised), "⚠️  N required API key(s) missing:", "ℹ️  N optional API key(s) not configured:" with "(enables: tool1, tool2)", then the migration results "✓ Configuration updated!" and warnings.
- **Inputs / options:** interactive prompts (y/N, key values).
- **Outputs / side effects:** see `config-b.core.migrations`.
- **Config / env:** `_config_version`, env vars.
- **Edge cases / guards:** support floor refusal message.
- **Rebuild notes:** wrapper over the migration engine.

## B. Category `discord` (37 schema fields: 33 × `discord.*` + 4 × `telegram.*` folded in)

Rendering contract for **every** field in this shard (verified in code, no per-key overrides exist for any of the 357 fields — `hermes_cli/web_server.py:1565` builds them all from `DEFAULT_CONFIG` with `description = full_key.replace(".", " → ").replace("_", " ").title()`):
Web dashboard **Config** page → left rail heading `Sections` (`i18n: config.sections`) → category row → field row rendered by `web/src/components/AutoField.tsx:85-200`.
The tab label is `prettyCategoryName(cat)` (`web/src/pages/ConfigPage.tsx:158-162`): the i18n `config.categories.<cat>` string when one exists — only `general, agent, terminal, display, delegation, memory, compression, security, browser, voice, tts, stt, logging, discord ("Discord"), auxiliary ("Auxiliary")` are translated (`web/src/i18n/en.ts:468-484`) — otherwise `cat.charAt(0).toUpperCase() + cat.slice(1)`, which leaves underscores intact: **Model_catalog**, **Tool_loop_guardrails**, **Tool_output**, **Wake_word**, **X_search**, **Lsp**, **Moa**. Each row also shows the category's field count; the same pretty name is the card title, with a badge reading `<n> field{s}` (`i18n: config.fields` = `field{s}`, `ConfigPage.tsx:328`, `:407`, `:641-649`). The rail heading string is `Sections` (`web/src/i18n/en.ts:450`) and the aside's aria-label is `Filters` (`config.filters`, `:449`). One field is removed client-side before rendering — `memory.provider`, "hidden from the generic config form" because the Plugins page owns it (`ConfigPage.tsx:172-181`).
Field row anatomy:
line 1 = **Label** = last dotted segment, `_`→space, Title Case (e.g. `Require Mention`);
line 2 = the dotted key in monospace (`discord.require_mention`);
line 3 = the schema description (`Discord → Require Mention`);
widget = `Switch` for `boolean`, `Input type="number"` for `number` (an emptied box writes `0`), comma-joined `Input` with placeholder `comma-separated values` for `list`, plain `Input` for `string`, and a bordered `NestedValueEditor` (one `Label` per sub-key, `Item N` labels for arrays) for `object`/list-of-objects.
Inside a tab, a field whose first path segment differs from the tab name gets a group heading of that segment with `_`→space (so the `telegram.*` fields render under a `telegram` heading on the **Discord** tab, `web/src/pages/ConfigPage.tsx:412-419`).
`telegram`, `mcp`, `computer_use`, `telemetry`, `plugins`, `doctor`, `runtime`, `session` are merged into other tabs by `_CATEGORY_MERGE` (`hermes_cli/web_server.py:1465-1499`); the merge comment states the reason verbatim: "Only `telegram.reactions` currently lives under telegram — fold it in with the other messaging-platform config (discord) so it isn't an orphan tab of one field."

### Discord → Require Mention  `id: config-b.discord.require_mention`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Require Mention`, key `discord.require_mention`, description `Discord → Require Mention` (boolean switch, default `true`).
- **What it does:** In guild (server) channels the bot only answers messages that @mention it. DMs are unaffected.
- **How it works:** `hermes_cli/config_defaults.py:2403`. The gateway bridges the YAML value into the process env at adapter setup: `plugins/platforms/discord/adapter.py:10413-10414` sets `DISCORD_REQUIRE_MENTION=<lower(value)>` only when the env var is not already set (env wins, first-writer-wins), and `gateway/config.py:1718-1719` copies `require_mention` into `PlatformConfig.extra` so multiplexed profiles stay isolated; the runtime read is `self.config.extra.get("require_mention")` at `plugins/platforms/discord/adapter.py:6562`. The same `extra` key is honoured by Signal (`gateway/platforms/signal.py:302`), BlueBubbles (`gateway/platforms/bluebubbles.py:192`), Buzz (`plugins/platforms/buzz/adapter.py:833-835`), WhatsApp (`gateway/platforms/whatsapp_common.py:128`) and Slack (`plugins/platforms/slack/adapter.py:9058`).
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** sets `DISCORD_REQUIRE_MENTION`; changes which messages produce a turn.
- **Config / env:** `discord.require_mention`; env `DISCORD_REQUIRE_MENTION` (wins).
- **Edge cases / guards:** per-channel exceptions come from `discord.free_response_channels`; threads have their own gate (`discord.thread_require_mention`).
- **Rebuild notes:** boolean gate consulted before dispatching a channel message. Better: per-guild/per-channel overrides in one map instead of three flat CSV keys.

### Discord → Free Response Channels  `id: config-b.discord.free_response_channels`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Free Response Channels`, key `discord.free_response_channels`, description `Discord → Free Response Channels` (string, default `''`).
- **What it does:** Comma-separated channel IDs where the bot replies without being mentioned, even when `require_mention` is true.
- **How it works:** `config_defaults.py:2404`; read at `plugins/platforms/discord/adapter.py:6745` (`self.config.extra.get("free_response_channels")`), seeded into `extra` at `adapter.py:10469-10473` (`str(frc)`), bridged generically at `gateway/config.py:1728-1730`, and consulted by the relay path at `gateway/relay/__init__.py:409-411` (platform block first, then the root config key).
- **Inputs / options:** comma-separated numeric channel IDs (a YAML list is stringified).
- **Outputs / side effects:** widens the response gate for those channels.
- **Config / env:** `discord.free_response_channels`; env `DISCORD_FREE_RESPONSE_CHANNELS` (adapter gate helper `_gate_raw`).
- **Edge cases / guards:** IDs must be the numeric snowflake, not the `#name`; also used as the default channel list for `discord.missed_message_backfill.channels`.
- **Rebuild notes:** CSV → set membership test.

### Discord → Allowed Channels  `id: config-b.discord.allowed_channels`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Allowed Channels`, key `discord.allowed_channels`, description `Discord → Allowed Channels` (string, default `''`).
- **What it does:** Whitelist — when non-empty the bot responds ONLY in these channel IDs.
- **How it works:** `config_defaults.py:2405`; `plugins/platforms/discord/adapter.py:6673` `return self._gate_csv_set(self._gate_raw("allowed_channels", "DISCORD_ALLOWED_CHANNELS"))`; seeded at `adapter.py:10492-10496`. Slack (`slack/adapter.py:9202,9856`) and Mattermost (`mattermost/adapter.py:871,1263`) implement the identical key for their own sections.
- **Inputs / options:** comma-separated channel IDs; empty = no whitelist.
- **Outputs / side effects:** hard filter before any other gate.
- **Config / env:** `discord.allowed_channels`; env `DISCORD_ALLOWED_CHANNELS` (wins).
- **Edge cases / guards:** a typo silently mutes the bot everywhere; DMs are governed by `DISCORD_ALLOWED_USERS`/roles, not this key.
- **Rebuild notes:** CSV allowlist evaluated first.

### Discord → Auto Thread  `id: config-b.discord.auto_thread`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Auto Thread`, key `discord.auto_thread`, description `Discord → Auto Thread` (boolean, default `true`).
- **What it does:** On an @mention in a channel the bot creates a thread and answers there (Slack-style), keeping channels tidy.
- **How it works:** `config_defaults.py:2406`; bridged at `plugins/platforms/discord/adapter.py:10476-10477` to `DISCORD_AUTO_THREAD`. Matrix has the mirror key (`plugins/platforms/matrix/adapter.py:5409-5410` → `MATRIX_AUTO_THREAD`). The OpenCLAW importer maps `discord.autoThread` → this key (`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py:2767`).
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** creates Discord threads; thread replies then follow `discord.thread_require_mention`.
- **Config / env:** `discord.auto_thread`; env `DISCORD_AUTO_THREAD`.
- **Edge cases / guards:** needs Create Public Threads permission; forum parents propagate `channel_prompts` to child threads.
- **Rebuild notes:** create-thread-on-trigger toggle.

### Discord → Thread Require Mention  `id: config-b.discord.thread_require_mention`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Thread Require Mention`, key `discord.thread_require_mention`, description `Discord → Thread Require Mention` (boolean, default `false`).
- **What it does:** Also demand an @mention inside threads (for threads shared by several bots).
- **How it works:** `config_defaults.py:2407`; read `self.config.extra.get("thread_require_mention")` at `plugins/platforms/discord/adapter.py:6879`; bridged at `adapter.py:10415-10416` to `DISCORD_THREAD_REQUIRE_MENTION`. Slack (`slack/adapter.py:9119,9825-9829`) and Matrix (`matrix/adapter.py:1424`) share the key name.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** narrows thread responses.
- **Config / env:** `discord.thread_require_mention`; env `DISCORD_THREAD_REQUIRE_MENTION`.
- **Edge cases / guards:** with `auto_thread: true` and this `true`, the bot creates a thread and then ignores follow-ups until mentioned.
- **Rebuild notes:** second gate applied only in thread contexts.

### Discord → Bots Require Inline Mention  `id: config-b.discord.bots_require_inline_mention`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Bots Require Inline Mention`, key `discord.bots_require_inline_mention`, description `Discord → Bots Require Inline Mention` (boolean, default `false`).
- **What it does:** In multi-bot rooms, another bot must literally type `@thisbot` in its message body to trigger a reply — a Discord reply/quote alone will not. Prevents two bots replying to each other forever. Humans are unaffected.
- **How it works:** `config_defaults.py:2408` (comment verbatim); read at `plugins/platforms/discord/adapter.py:6811`; bridged at `adapter.py:10417-10418` to `DISCORD_BOTS_REQUIRE_INLINE_MENTION`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** bot-authored messages are dropped unless they contain the inline mention.
- **Config / env:** `discord.bots_require_inline_mention`; env `DISCORD_BOTS_REQUIRE_INLINE_MENTION`.
- **Edge cases / guards:** only applies to messages whose author is a bot account.
- **Rebuild notes:** author-is-bot ∧ no inline mention ⇒ drop. Better: loop detection by conversation depth rather than a static flag.

### Discord → History Backfill / History Backfill Limit  `id: config-b.discord.history_backfill`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → labels `History Backfill` (key `discord.history_backfill`, description `Discord → History Backfill`, boolean, default `true`) and `History Backfill Limit` (key `discord.history_backfill_limit`, description `Discord → History Backfill Limit`, number, default `50`).
- **What it does:** When the bot IS triggered, prepend the recent channel scrollback to the prompt so the messages that `require_mention` filtered out are still visible; the limit caps how many recent messages are scanned when assembling that block.
- **How it works:** `config_defaults.py:2409-2410`; reads at `plugins/platforms/discord/adapter.py:6888` (`history_backfill`) and `:6903` (`history_backfill_limit`); bridged at `adapter.py:10510-10512` to `DISCORD_HISTORY_BACKFILL` / `DISCORD_HISTORY_BACKFILL_LIMIT`.
- **Inputs / options:** boolean; integer message count.
- **Outputs / side effects:** larger prompt per triggered turn; extra REST history fetch.
- **Config / env:** `discord.history_backfill`, `discord.history_backfill_limit`; envs `DISCORD_HISTORY_BACKFILL`, `DISCORD_HISTORY_BACKFILL_LIMIT`.
- **Edge cases / guards:** large limits inflate token cost on every trigger; needs Read Message History.
- **Rebuild notes:** fetch N previous messages, render as a context block before the trigger message.

### Discord → Missed Message Backfill (5 keys)  `id: config-b.discord.missed_message_backfill`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`), group heading `discord`, labels `Enabled`, `Channels`, `Window Seconds`, `Limit`, `Max Dispatches` — keys `discord.missed_message_backfill.enabled` (boolean, default `false`), `.channels` (string, default `''`), `.window_seconds` (number, default `21600`), `.limit` (number, default `100`), `.max_dispatches` (number, default `10`); descriptions `Discord → Missed Message Backfill → Enabled` … `→ Max Dispatches`.
- **What it does:** After a reconnect or gateway startup, replays messages that arrived while the bot was offline, dispatching them as real turns.
- **How it works:** `config_defaults.py:2411-2417`. The adapter reads the block as a dict: `enabled` at `plugins/platforms/discord/adapter.py:2487-2488`, `channels` at `:2504-2505`, `window_seconds` at `:2520` (`configured.get("window_seconds", 21600)`), `limit` at `:2533` (`configured.get("limit", 100)`), `max_dispatches` at `:2546` (`configured.get("max_dispatches", 10)`). Empty `channels` falls back to `discord.free_response_channels` (comment at `config_defaults.py:2413`).
- **Inputs / options:** `enabled` true|false; `channels` CSV of channel IDs; `window_seconds` lookback (6 h default); `limit` global cap on messages scanned per reconnect; `max_dispatches` cap on recovered messages actually dispatched per reconnect.
- **Outputs / side effects:** replayed messages become agent turns and platform replies.
- **Config / env:** the five dotted keys.
- **Edge cases / guards:** off by default because a replay storm can bill many turns; the two caps bound it; messages older than the window are skipped permanently.
- **Rebuild notes:** on connect, for each channel fetch messages after `now-window`, dedupe against the delivery ledger, dispatch at most `max_dispatches`.

### Discord → Reactions  `id: config-b.discord.reactions`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Reactions`, key `discord.reactions`, description `Discord → Reactions` (boolean, default `true`).
- **What it does:** Adds 👀 / ✅ / ❌ reactions to the user's message while the turn is processing / on success / on failure.
- **How it works:** `config_defaults.py:2418` (comment: "Add 👀/✅/❌ reactions to messages during processing"); bridged at `plugins/platforms/discord/adapter.py:10478-10479` to `DISCORD_REACTIONS`. Slack (`slack/adapter.py:9843-9844` → `SLACK_REACTIONS`) and Telegram (`telegram/adapter.py:11223-11224` → `TELEGRAM_REACTIONS`) mirror it. Reaction state is persisted under the `reactions` metadata key (`hermes_state.py:11803`) and survives compression (`agent/context_compressor.py:8537`).
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** REST reaction add/remove calls.
- **Config / env:** `discord.reactions`; env `DISCORD_REACTIONS`.
- **Edge cases / guards:** needs Add Reactions permission; extra rate-limit budget per turn.
- **Rebuild notes:** three-state progress indicator on the triggering message.

### Discord → WebSocket liveness probe (4 keys)  `id: config-b.discord.websocket_liveness`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → labels `Websocket Liveness Interval Seconds` (`discord.websocket_liveness_interval_seconds`, number, default `15`), `Websocket Liveness Failure Threshold` (`discord.websocket_liveness_failure_threshold`, number, default `2`), `Websocket Heartbeat Ack Max Age Seconds` (`discord.websocket_heartbeat_ack_max_age_seconds`, number, default `60`), `Websocket Max Latency Seconds` (`discord.websocket_max_latency_seconds`, number, default `30`); descriptions `Discord → Websocket …`.
- **What it does:** Health-checks the live Discord Gateway WebSocket (ready/open/heartbeat-ack age/latency) and triggers a reconnect when it looks dead, without using REST as a liveness proxy.
- **How it works:** `config_defaults.py:2419-2426` — the comment states the design rule verbatim: "These settings inspect the active WebSocket's ready/open/heartbeat state; they never use Discord REST as proof that Gateway events are still arriving. Set any value to 0 to disable this compatibility-safe probe during a rollback." Canonical values are computed once and seeded into `PlatformConfig.extra` (`plugins/platforms/discord/adapter.py:10553-10563`) and read back at `adapter.py:1133-1147`.
- **Inputs / options:** interval seconds; consecutive-failure threshold; max heartbeat-ACK age; max latency seconds; any `0` disables the probe.
- **Outputs / side effects:** forced reconnects; log lines.
- **Config / env:** the four dotted keys (per-profile via `PlatformConfig.extra`, so multiplexed profiles are isolated).
- **Edge cases / guards:** the rollback escape hatch is setting a value to 0; too-tight values cause reconnect churn on slow links.
- **Rebuild notes:** periodic probe of socket state + heartbeat age with a strike counter.

### Discord → Dm Role Auth Guild  `id: config-b.discord.dm_role_auth_guild`
- **Surface:** Config | Platform:Discord | Security
- **Where:** Config page tab **Discord** (category id `discord`) → label `Dm Role Auth Guild`, key `discord.dm_role_auth_guild`, description `Discord → Dm Role Auth Guild` (string, default `''`).
- **What it does:** Opt-in: lets members of ONE trusted guild who hold an allowed role also authorise DMs (by default `DISCORD_ALLOWED_ROLES` authorises guild messages only and DMs need `DISCORD_ALLOWED_USERS`).
- **How it works:** `config_defaults.py:2427-2433` (issue #12136); read at `plugins/platforms/discord/adapter.py:973` (`discord_cfg.get("dm_role_auth_guild")`).
- **Inputs / options:** a guild (server) ID string; unset / empty / `0` = secure default (DM role-auth off).
- **Outputs / side effects:** widens who may DM the agent.
- **Config / env:** `discord.dm_role_auth_guild`; interacts with `DISCORD_ALLOWED_ROLES`, `DISCORD_ALLOWED_USERS`.
- **Edge cases / guards:** a wrong guild ID silently grants nothing; a public guild with a broad role grants DM access to everyone in it.
- **Rebuild notes:** resolve the DM author's membership+roles in one pinned guild before authorising.

### Discord → Server Actions  `id: config-b.discord.server_actions`
- **Surface:** Config | Tool | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Server Actions`, key `discord.server_actions`, description `Discord → Server Actions` (string, default `''`).
- **What it does:** Restricts which `discord` / `discord_admin` tool actions the agent may call. Empty = all actions allowed (subject to the bot's privileged intents).
- **How it works:** `config_defaults.py:2434-2441`; read at `tools/discord_tool.py:719` (`raw = (cfg.get("discord") or {}).get("server_actions")`); listed in the config writer's known-keys table at `hermes_cli/config.py:5490`.
- **Inputs / options:** comma-separated string (`"list_guilds,list_channels,fetch_messages"`) or a YAML list. The complete action vocabulary from the comment: `list_guilds`, `server_info`, `list_channels`, `channel_info`, `list_roles`, `member_info`, `search_members`, `fetch_messages`, `list_pins`, `pin_message`, `unpin_message`, `create_thread`, `add_role`, `remove_role`.
- **Outputs / side effects:** unknown names are dropped with a warning at load time; disallowed actions fail inside the tool.
- **Config / env:** `discord.server_actions`.
- **Edge cases / guards:** an allowlist of one typo'd name effectively disables the tool.
- **Rebuild notes:** normalise to a set, intersect with the tool's action registry, warn on unknowns.

### Discord → Allow Any Attachment (deprecated no-op)  `id: config-b.discord.allow_any_attachment`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Allow Any Attachment`, key `discord.allow_any_attachment`, description `Discord → Allow Any Attachment` (boolean, default `false`).
- **What it does:** DEPRECATED / no-op. Any uploaded file is now always cached and surfaced to the agent regardless of file type — authorisation to message the agent is the gate, not the extension.
- **How it works:** `config_defaults.py:2442-2447` (verbatim deprecation note); the value is still read at `plugins/platforms/discord/adapter.py:6577` so old configs do not error.
- **Inputs / options:** `true` | `false` (both behave identically).
- **Outputs / side effects:** none.
- **Config / env:** `discord.allow_any_attachment`; env override `DISCORD_ALLOW_ANY_ATTACHMENT`.
- **Edge cases / guards:** kept only for config compatibility.
- **Rebuild notes:** keep accepting the key, ignore it.

### Discord → Max Attachment Bytes  `id: config-b.discord.max_attachment_bytes`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Max Attachment Bytes`, key `discord.max_attachment_bytes`, description `Discord → Max Attachment Bytes` (number, default `33554432` = 32 MiB).
- **What it does:** Caps the bytes per attachment the gateway will cache; the whole file is held in memory while written, so unlimited uploads carry a real memory cost.
- **How it works:** `config_defaults.py:2448-2452`; read at `plugins/platforms/discord/adapter.py:6591`.
- **Inputs / options:** integer bytes; `0` = no cap.
- **Outputs / side effects:** oversize attachments are rejected/not cached.
- **Config / env:** `discord.max_attachment_bytes`; env override `DISCORD_MAX_ATTACHMENT_BYTES`.
- **Edge cases / guards:** the global inbound-media ceiling `gateway.max_inbound_media_bytes` (128 MiB) also applies.
- **Rebuild notes:** stream to disk with a size guard instead of buffering.

### Discord → Approval Mentions  `id: config-b.discord.approval_mentions`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → label `Approval Mentions`, key `discord.approval_mentions`, description `Discord → Approval Mentions` (boolean, default `false`).
- **What it does:** Makes Discord approval prompts @mention the numeric allowed users so owners notice approval requests in shared channels/threads.
- **How it works:** `config_defaults.py:2453-2457`; resolved at `plugins/platforms/discord/adapter.py:10464-10465` — `discord_cfg["approval_mentions"]` when present, else `platform_extra_cfg.get("approval_mentions")` (i.e. `platforms.discord.extra`).
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** approval messages contain `<@id>` pings.
- **Config / env:** `discord.approval_mentions`; env override `DISCORD_APPROVAL_MENTIONS`; interacts with `approvals.timeout`.
- **Edge cases / guards:** default false "avoids surprise pings".
- **Rebuild notes:** prefix the approval card with mentions of the authorised approvers.

### Discord → Voice channel timeouts (2 keys)  `id: config-b.discord.voice_timeouts`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`) → labels `Voice Channel Inactivity Timeout Seconds` (`discord.voice_channel_inactivity_timeout_seconds`, number, default `300`) and `Voice Playback Timeout Seconds` (`discord.voice_playback_timeout_seconds`, number, default `120`).
- **What it does:** How long the bot lingers in a voice channel with nothing happening, and the minimum wait before a VC playback is force-stopped.
- **How it works:** `config_defaults.py:2458-2464`; read at `plugins/platforms/discord/adapter.py:4355` and `:4363`. The adapter probes clip duration and extends the playback floor by a padding window so long TTS readbacks are not cut at exactly 120 s.
- **Inputs / options:** seconds; inactivity `0` = stay until an explicit `/voice leave` / disconnect.
- **Outputs / side effects:** the bot disconnects from VC; playback is stopped.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** the playback value is a floor, not a hard cut.
- **Rebuild notes:** idle timer + duration-aware playback watchdog.

### Discord → Voice Fx (8 keys — the continuous voice mixer)  `id: config-b.discord.voice_fx`
- **Surface:** Config | Platform:Discord
- **Where:** Config page tab **Discord** (category id `discord`), keys `discord.voice_fx.enabled` (boolean, default `false`), `.ambient_enabled` (boolean, `true`), `.ambient_path` (string, `''`), `.ambient_gain` (number, `0.18`), `.duck_gain` (number, `0.06`), `.speech_gain` (number, `1.0`), `.ack_enabled` (boolean, `true`), `.ack_phrases` (list, default `['Let me look into that.', 'One moment.', 'Checking on that now.', 'Give me a sec.', 'On it.']`); labels `Enabled`, `Ambient Enabled`, `Ambient Path`, `Ambient Gain`, `Duck Gain`, `Speech Gain`, `Ack Enabled`, `Ack Phrases`; descriptions `Discord → Voice Fx → …`.
- **What it does:** Installs a software mixer on the outgoing voice stream so a low ambient "thinking" bed, spoken acknowledgements and TTS replies OVERLAP (ducking the bed under speech) instead of stop-and-swap — "the Grok-voice-mode feel".
- **How it works:** `config_defaults.py:2465-2487`; discord.py ships no mixer, so it is implemented in `plugins/platforms/discord/voice_mixer.py`. Adapter defaults mirror the config at `plugins/platforms/discord/adapter.py:4310-4320`; reads: master switch `:4605`, `ambient_enabled` `:4425`, `ambient_path` `:4433` (stripped; empty ⇒ synthesised pad), `ambient_gain` `:4455`, `duck_gain` `:4456`, `speech_gain` `:4457` (also `:4536`, `:4677`), `ack_enabled` `:4501`, `ack_phrases` `:4508` (`or ["One moment."]` when the list is empty).
- **Inputs / options:** master switch; ambient bed on/off; custom loop audio file path; three gains in 0.0–1.0; ack on/off; ack phrase list (set `[]` to disable phrases — the code then falls back to the single phrase `One moment.`).
- **Outputs / side effects:** continuous audio mixing on the VC stream; a random ack phrase is spoken before the first tool call.
- **Config / env:** the eight dotted keys.
- **Edge cases / guards:** OFF by default; requires a working voice stack (opus/ffmpeg); gains outside 0–1 are not clamped by config.
- **Rebuild notes:** PCM mixer with an ambient loop bus, a speech bus and a duck envelope; pick an ack phrase at random on first tool call. Better: real barge-in and per-guild volume memory.

### Telegram → Reactions  `id: config-b.telegram.reactions`
- **Surface:** Config | Platform:Telegram
- **Where:** Config page tab **Discord** (category id `discord`), group heading `telegram` → label `Reactions`, key `telegram.reactions`, description `Telegram → Reactions` (boolean, default `false`).
- **What it does:** Adds 👀/✅/❌ reactions to Telegram messages during processing.
- **How it works:** `config_defaults.py:2498-2499`; bridged at `plugins/platforms/telegram/adapter.py:11223-11224` to `TELEGRAM_REACTIONS` (only when the env var is unset).
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** `setMessageReaction` API calls.
- **Config / env:** `telegram.reactions`; env `TELEGRAM_REACTIONS`.
- **Edge cases / guards:** default off (unlike Discord) — Telegram reactions are noisier in DMs.
- **Rebuild notes:** same three-state indicator.

### Telegram → Allowed Chats  `id: config-b.telegram.allowed_chats`
- **Surface:** Config | Platform:Telegram
- **Where:** Config page tab **Discord** (category id `discord`), group heading `telegram` → label `Allowed Chats`, key `telegram.allowed_chats`, description `Telegram → Allowed Chats` (string, default `''`).
- **What it does:** Whitelist of group/supergroup chat IDs — when set the bot ONLY responds in those chats.
- **How it works:** `config_defaults.py:2501`; read at `plugins/platforms/telegram/adapter.py:8972` (`self.config.extra.get("allowed_chats")`), seeded at `:11200`, bridged for the TELEGRAM platform only at `gateway/config.py:1723-1724`. DingTalk implements the same key (`plugins/platforms/dingtalk/adapter.py:498,1856`).
- **Inputs / options:** comma-separated chat IDs (negative IDs for groups/supergroups).
- **Outputs / side effects:** hard filter on group traffic.
- **Config / env:** `telegram.allowed_chats`; siblings `group_allowed_chats`, `allowed_topics` are bridged from `platforms.telegram` but are not DEFAULT_CONFIG keys (see the hidden-keys section).
- **Edge cases / guards:** DMs are governed separately by the allow lists.
- **Rebuild notes:** CSV allowlist for group chats.

### Telegram → Extra → Rich Messages / Rich Drafts  `id: config-b.telegram.extra_rich`
- **Surface:** Config | Platform:Telegram
- **Where:** Config page tab **Discord** (category id `discord`), group heading `telegram` → labels `Rich Messages` (key `telegram.extra.rich_messages`, boolean, default `false`) and `Rich Drafts` (key `telegram.extra.rich_drafts`, boolean, default `false`); descriptions `Telegram → Extra → Rich Messages` / `→ Rich Drafts`.
- **What it does:** Opt into Bot API 10.1 rich messages (tables / task lists / details / math rendered natively) and into experimental rich draft previews during Telegram DM streaming.
- **How it works:** `config_defaults.py:2502-2505`; `plugins/platforms/telegram/adapter.py:719` `self._rich_messages_enabled = self._coerce_bool_extra("rich_messages", False)` and `:727` the same for `rich_drafts`. When rich messages are on, the system prompt is extended (`agent/system_prompt.py:860` `if _tg_extra.get("rich_messages")`) so the model knows it may emit the richer markup.
- **Inputs / options:** two booleans.
- **Outputs / side effects:** different outbound formatting mode; changed system prompt.
- **Config / env:** `telegram.extra.rich_messages`, `telegram.extra.rich_drafts`.
- **Edge cases / guards:** defaults stay legacy MarkdownV2 "because rich messages can be hard to copy as plain text in Telegram clients"; drafts default off "because Telegram Desktop/macOS can visually overlay rich draft frames until the chat redraws".
- **Rebuild notes:** capability flag → formatter selection + prompt hint.

## C. Category `auxiliary` (115 schema fields)

### Auxiliary task block — the shared field shape and resolution chain  `id: config-b.auxiliary.task_shape`
- **Surface:** Config | Core
- **Where:** every `auxiliary.<task>.*` field on the Config page tab **Auxiliary** (category id `auxiliary`); also editable from the CLI picker `hermes model` → `Auxiliary models` menu (`_AUX_TASKS`, `hermes_cli/main.py:4322-4336`).
- **What it does:** Each side task (vision, compression, …) gets its own provider/model/credentials/timeout so background work can run on a cheap model while the main agent runs on an expensive one.
- **How it works:** `hermes_cli/config_defaults.py:1129-1397` defines the blocks; the header comment (`:1104-1128`) states the contract verbatim: `"auto"` for provider = auto-detect best available provider; empty model = use the provider's default auxiliary model; **all tasks fall back to `openrouter:google/gemini-3-flash-preview`** if the configured provider is unavailable. `agent/auxiliary_client.py:8520-8562` `_get_auxiliary_task_config(task)` reads `auxiliary.<task>` from `load_config_readonly()` and layers plugin-declared defaults (`ctx.register_auxiliary_task(defaults=…)`, via `hermes_cli/plugins.get_plugin_auxiliary_tasks()`) UNDER the user config. Resolution priority (`auxiliary_client.py:8330-8420`): (1) explicit provider/model/base_url/api_key arguments always win; (2) `auxiliary.{task}.provider/model/base_url/api_key/api_mode`; (3) `"auto"` = full auto-detection. A literal `model: auto` (and an explicit `model="auto"` kwarg from a MoA slot) is normalised to `None` so the string never reaches the wire. `provider: moa` is unwrapped to the preset's aggregator slot (`_resolve_moa_aggregator`). Timeouts: `_get_task_timeout` (`:8684`) reads `auxiliary.{task}.timeout` as float; `_effective_aux_timeout` (`:8697`) applies a compression-only floor `_COMPRESSION_TIMEOUT_FLOOR_SECONDS` unless the caller passed an explicit timeout. `reasoning_effort` is folded into `extra_body.reasoning` by `_get_task_extra_body` (`:8715-8758`) using `hermes_constants.parse_reasoning_effort`; an explicit `extra_body.reasoning` wins; an invalid level logs `auxiliary.%s.reasoning_effort %r is not a valid level (none, minimal, low, medium, high, xhigh, max, ultra) — ignoring`.
- **Inputs / options:** per task — `provider` (`auto` | a provider id such as `openrouter`, `nous`, `codex`, `anthropic`, `custom`), `model` (slug), `base_url` (a direct OpenAI-compatible endpoint, which takes precedence over `provider`), `api_key` (falls back to `OPENAI_API_KEY` for a bare `base_url`), `timeout` (seconds), `reasoning_effort` (`none|minimal|low|medium|high|xhigh|max|ultra`, empty = provider default), `extra_body` (dict forwarded verbatim on every call).
- **Outputs / side effects:** determines which endpoint every background call hits and how it is billed.
- **Config / env:** all `auxiliary.*` keys; provider credentials from `.env`.
- **Edge cases / guards:** each aux task is independent — main-agent `provider_routing` and `openrouter.min_coding_score` do NOT propagate to aux calls by design (`config_defaults.py:1127-1128`); MoA tasks reject `reasoning_effort` with a warning (per-slot instead).
- **Rebuild notes:** a table of task → backend descriptor, resolved lazily with a documented fallback chain. Better: show the resolved endpoint per task in `hermes doctor`.

### Auxiliary → Transient Retries  `id: config-b.auxiliary.transient_retries`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → label `Transient Retries`, key `auxiliary.transient_retries`, description `Auxiliary → Transient Retries` (number, default `2`).
- **What it does:** Same-provider retries for a transient transport blip (connection reset / timeout / 5xx / 408) on ANY auxiliary call before falling back to another provider.
- **How it works:** `config_defaults.py:1129-1136`; read at `agent/auxiliary_client.py:4548` `val = cfg_get(load_config(), "auxiliary", "transient_retries")`. Default 2 → 3 total attempts, clamped to `[0,6]`.
- **Inputs / options:** integer 0–6.
- **Outputs / side effects:** more retry latency, fewer lost calls.
- **Config / env:** `auxiliary.transient_retries`.
- **Edge cases / guards:** "Matters most for pinned calls like MoA reference advisors, where provider fallback is not a meaningful recovery, so an unretried blip silently loses the call."
- **Rebuild notes:** bounded retry on transport-class errors only, before the fallback chain.

### Auxiliary → Free Only  `id: config-b.auxiliary.free_only`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → label `Free Only`, key `auxiliary.free_only`, description `Auxiliary → Free Only` (boolean, default `false`).
- **What it does:** Restricts the auxiliary auto-chain's OpenRouter fallback to free (`:free`) SKUs — with it on, the OpenRouter step is skipped entirely unless the resolved fallback model ends in `:free`, so a PAID lane is never engaged for background traffic.
- **How it works:** `config_defaults.py:1137-1144`; `agent/auxiliary_client.py:3052-3068` `_aux_openrouter_settings()` reads it with `cfg_get(cfg, "auxiliary", "free_only", default=False)`. `_is_free_model` (`:3040-3050`) treats a model as free when it ends in `:free` **or** starts with `stealth/` (naming-convention trust). `_warn_paid_lane_once` (`:3071+`) logs a WARNING the first time a non-free model is engaged, naming both remedy keys.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** background tasks may fail instead of falling back to a paid model.
- **Config / env:** `auxiliary.free_only`, `auxiliary.openrouter_model`, `OPENROUTER_API_KEY`.
- **Edge cases / guards:** default false keeps "the historical paid fallback for users who want it"; affected tasks listed in the comment: compression, title generation, session search, vision, web extract.
- **Rebuild notes:** predicate on the fallback candidate before engaging it.

### Auxiliary → Openrouter Model  `id: config-b.auxiliary.openrouter_model`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → label `Openrouter Model`, key `auxiliary.openrouter_model`, description `Auxiliary → Openrouter Model` (string, default `''`).
- **What it does:** Overrides the auxiliary auto-chain's OpenRouter fallback model (built-in default `google/gemini-3.6-flash`, a PAID model).
- **How it works:** `config_defaults.py:1145-1150`; read at `agent/auxiliary_client.py:3063`; falls back to the module constant `_OPENROUTER_MODEL` when empty.
- **Inputs / options:** an OpenRouter model slug, e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`.
- **Outputs / side effects:** changes which model absorbs every failed aux call.
- **Config / env:** `auxiliary.openrouter_model` (pair with `auxiliary.free_only: true` to stay free).
- **Edge cases / guards:** "A one-time WARNING is logged whenever a non-`:free` model is engaged."
- **Rebuild notes:** single configurable last-resort model id.

### Auxiliary → Stream Only Base Urls  `id: config-b.auxiliary.stream_only_base_urls`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → label `Stream Only Base Urls`, key `auxiliary.stream_only_base_urls`, description `Auxiliary → Stream Only Base Urls` (list, default `[]`, comma-separated input).
- **What it does:** Marks endpoints that reject NON-streaming chat requests outright; auxiliary calls to a matching endpoint are sent with `stream=True` and aggregated client-side.
- **How it works:** `config_defaults.py:1151-1157`; read at `agent/auxiliary_client.py:9426-9427` `aux_cfg = (load_config() or {}).get("auxiliary", {})` → `markers = aux_cfg.get("stream_only_base_urls") or []`. Entries are case-insensitive substrings matched against the endpoint URL; `copilot.tencent.com` is always treated as stream-only.
- **Inputs / options:** list of URL substrings.
- **Outputs / side effects:** streaming request shape + client-side aggregation for those hosts.
- **Config / env:** `auxiliary.stream_only_base_urls`.
- **Edge cases / guards:** the documented symptom is HTTP 400 "Non-stream chat request is currently not supported".
- **Rebuild notes:** substring allowlist that flips the `stream` flag.

### Auxiliary → Vision (7 keys)  `id: config-b.auxiliary.vision`
- **Surface:** Config | Tool
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.vision.provider` (string, `'auto'`), `.model` (`''`), `.base_url` (`''`), `.api_key` (`''`), `.timeout` (number, `120`), `.reasoning_effort` (`''`), `.download_timeout` (number, `30`); labels `Provider`, `Model`, `Base Url`, `Api Key`, `Timeout`, `Reasoning Effort`, `Download Timeout`; descriptions `Auxiliary → Vision → …`. CLI: `hermes model` → auxiliary picker row `Vision` — "image/screenshot analysis".
- **What it does:** Model used to analyse images/screenshots (`view_image`, browser screenshots).
- **How it works:** `config_defaults.py:1158-1167` (block starts at `:1158`); task name `"vision"` at `tools/vision_tools.py:1596` and `tools/browser_tool.py:5678`. `download_timeout` is the image HTTP download timeout, read separately at `tools/vision_tools.py:88` (`cfg_get(cfg, "auxiliary", "vision", "download_timeout")`). `provider` accepts `auto | openrouter | nous | codex | custom` (comment at `:1159`); `_resolve_provider_vision_default` (`auxiliary_client.py:1137`) picks a per-provider vision default when the model is empty. Vision is excluded from the per-task concurrency semaphore because `max_concurrency` there already means the encode/resize CPU worker pool (`auxiliary_client.py:8776-8783`).
- **Inputs / options:** the seven fields above; timeout comment: "vision payloads need generous timeout"; download_timeout "increase for slow connections".
- **Outputs / side effects:** image analysis text; HTTP downloads of remote images.
- **Config / env:** `auxiliary.vision.*`; `OPENAI_API_KEY` as api_key fallback for a bare `base_url`.
- **Edge cases / guards:** a non-vision model produces provider errors; `download_timeout` only bounds the fetch, not the LLM call.
- **Rebuild notes:** separate backend + separate download deadline for multimodal side calls.

### Auxiliary → Compression (7 keys)  `id: config-b.auxiliary.compression`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.compression.provider` (`'auto'`), `.model` (`''`), `.base_url` (`''`), `.api_key` (`''`), `.timeout` (`120`), `.reasoning_effort` (`''`), `.max_output_tokens` (number, `0`); labels `Provider`…`Max Output Tokens`; descriptions `Auxiliary → Compression → …`. CLI picker row `Compression` — "context summarization".
- **What it does:** Model that summarises the conversation when the context window fills.
- **How it works:** `config_defaults.py:1173-1189`; task `"compression"` at `agent/context_compressor.py:5254,7072`. `max_output_tokens` is the guarded fast lane: `_fast_lane_config_fields` (`agent/auxiliary_client.py:8594-8601`) only honours it with a concrete provider/model AND an explicit `reasoning_effort` that disables thinking (`none`, `false`, `disabled`, YAML `false` — all parsed by `parse_reasoning_effort`); booleans are treated as config drift, never a cap; `0` preserves the historic uncapped compression request. `_effective_aux_timeout` raises the compression timeout to `_COMPRESSION_TIMEOUT_FLOOR_SECONDS` when the caller passes no explicit timeout (#54915). `agent/conversation_compression.py:1247-1250` reads the (hidden) `fallback_chain` for this task.
- **Inputs / options:** the seven fields; timeout comment "increase for local models".
- **Outputs / side effects:** compression summaries; cost per compaction.
- **Config / env:** `auxiliary.compression.*`; related `compression.*` (config-a shard).
- **Edge cases / guards:** a capped output on a reasoning model would truncate the summary — hence the certification requirement.
- **Rebuild notes:** dedicated summariser backend with a certified non-reasoning fast lane.

### Auxiliary → Skills Hub (6 keys)  `id: config-b.auxiliary.skills_hub`
- **Surface:** Config | Skill
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.skills_hub.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`30`), `.reasoning_effort`; descriptions `Auxiliary → Skills Hub → …`. CLI picker row `Skills hub` — "skills search/install".
- **What it does:** Model behind skills-hub search/install reasoning.
- **How it works:** `config_defaults.py:1190-1198`; the task name `"skills_hub"` is one of the documented auxiliary tasks (`agent/auxiliary_client.py:9862`, `:7406`).
- **Inputs / options:** the six fields.
- **Outputs / side effects:** hub query/selection calls.
- **Config / env:** `auxiliary.skills_hub.*`.
- **Edge cases / guards:** 30 s timeout suits a short call.
- **Rebuild notes:** cheap-model lane for catalogue reasoning.

### Auxiliary → Approval (6 keys)  `id: config-b.auxiliary.approval`
- **Surface:** Config | Security
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.approval.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`30`), `.reasoning_effort`. CLI picker row `Approval` — "smart command approval".
- **What it does:** The classifier that decides whether a dangerous command is low-risk enough to auto-approve in `approvals.mode: smart`.
- **How it works:** `config_defaults.py:1199-1207`; called with `task="approval"` at `tools/approval.py:3724`. The model comment recommends "fast/cheap model recommended (e.g. gemini-flash, haiku)".
- **Inputs / options:** the six fields.
- **Outputs / side effects:** auto-approve / prompt decisions.
- **Config / env:** `auxiliary.approval.*`; `approvals.mode`, `approvals.timeout` (config-a shard).
- **Edge cases / guards:** a slow/unavailable approval model degrades to a manual prompt; security-sensitive — do not point it at an untrusted endpoint.
- **Rebuild notes:** short structured-JSON risk classifier.

### Auxiliary → Review (5 keys — the `/review` subagent)  `id: config-b.auxiliary.review`
- **Surface:** Config | Delegation
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.review.provider` (`'auto'`), `.model` (`''`), `.base_url` (`''`), `.api_key` (`''`), `.api_mode` (`''`); labels `Provider`, `Model`, `Base Url`, `Api Key`, `Api Mode`. CLI picker row `Review` — "/review reviewer subagent". Note: no `timeout` and no `reasoning_effort` field for this task.
- **What it does:** Picks the model for the independent reviewer subagent spawned by `/review`.
- **How it works:** `config_defaults.py:1208-1221` — unlike other aux tasks this is not a single LLM call: "the reviewer is a full subagent (all normal subagent tools) spawned on the async delegation rail", and provider/model/base_url/api_key/api_mode "are resolved through the same credential system as delegation.provider pins". `api_mode` forces the transport and is read at `agent/auxiliary_client.py:8368` (`cfg_api_mode`).
- **Inputs / options:** `provider` (`auto` = inherit main model | `openrouter` | `nous` | `anthropic` | …), `model` (e.g. `anthropic/claude-opus-4.6`), `base_url`, `api_key`, `api_mode` ∈ `chat_completions` | `anthropic_messages` | `codex_responses`.
- **Outputs / side effects:** the reviewer subagent runs on the chosen backend.
- **Config / env:** `auxiliary.review.*`; `delegation.*` for the rail itself.
- **Edge cases / guards:** leaving provider `auto` + model empty runs the reviewer on the main agent's model.
- **Rebuild notes:** treat "review" as a delegation profile, not a one-shot call.

### Auxiliary → Mcp (6 keys)  `id: config-b.auxiliary.mcp`
- **Surface:** Config | Tool
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.mcp.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`30`), `.reasoning_effort`. CLI picker row `MCP` — "MCP tool reasoning".
- **What it does:** Model used for MCP tool reasoning (argument synthesis / server selection).
- **How it works:** `config_defaults.py:1222-1230`; invoked with `task="mcp"` at `tools/mcp_tool.py:2121`.
- **Inputs / options:** the six fields.
- **Outputs / side effects:** MCP call planning.
- **Config / env:** `auxiliary.mcp.*`; `mcp_discovery_timeout`, `mcp_single_query_discovery_timeout` (root keys).
- **Edge cases / guards:** a weak model here produces malformed MCP arguments.
- **Rebuild notes:** dedicated planner model for tool bridges.

### Auxiliary → Title Generation (9 keys)  `id: config-b.auxiliary.title_generation`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.title_generation.enabled` (boolean, `true`), `.provider` (`'auto'`), `.model` (`''`), `.prefer_fast_model` (boolean, `false`), `.base_url` (`''`), `.api_key` (`''`), `.timeout` (`30`), `.reasoning_effort` (`''`), `.language` (`''`); labels `Enabled`, `Provider`, `Model`, `Prefer Fast Model`, `Base Url`, `Api Key`, `Timeout`, `Reasoning Effort`, `Language`. CLI picker row `Title generation` — "session titles".
- **What it does:** Generates the short session title shown in `/resume`, the dashboard and the desktop app.
- **How it works:** `config_defaults.py:1231-1242`; `agent/title_generator.py:180-183` reads `(config.get("auxiliary") or {}).get("title_generation")` for `enabled` and logs `Auto-title skipped: auxiliary.title_generation.enabled=false` at `:371`; the call runs `task="title_generation"` (`title_generator.py:404`, one-shot helper `agent/oneshot.py:112`). `prefer_fast_model` is read by `_task_prefers_fast_model` (`agent/auxiliary_client.py:1119-1124`, `is_truthy_value(task_config.get("prefer_fast_model"), default=False)`) and `title_generation` is the only member of `_FAST_MODEL_TASKS` (`:1116`); when true `_get_aux_model_for_provider(provider, prefer_fast=True)` selects the provider's fast tier, otherwise "auto" uses the main model. `language` is read at `title_generator.py:163-164` to force the title's language.
- **Inputs / options:** the nine fields; `language` is a free-text language name/code, empty = follow the conversation.
- **Outputs / side effects:** a session title stored in `state.db`; one cheap LLM call per new session.
- **Config / env:** `auxiliary.title_generation.*`.
- **Edge cases / guards:** disabling it leaves sessions with their fallback (first-message) titles; `prefer_fast_model` is opt-in because fast tiers can be worse at multilingual titles.
- **Rebuild notes:** one short call after the first exchange, guarded by a per-session flag.

### Auxiliary → Memory Query Rewrite (5 keys)  `id: config-b.auxiliary.memory_query_rewrite`
- **Surface:** Config | Memory
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.memory_query_rewrite.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (number, `8`). No `reasoning_effort` and no `extra_body`-exposed sibling beyond the hidden `extra_body`. CLI picker row `Memory query rewrite` — "memory retrieval queries".
- **What it does:** Rewrites the user's phrasing into a better memory-retrieval query before searching stored memories.
- **How it works:** `config_defaults.py:1243-1250`; the aggressive 8-second timeout keeps retrieval latency inside a turn.
- **Inputs / options:** the five fields.
- **Outputs / side effects:** one very short call on the memory path.
- **Config / env:** `auxiliary.memory_query_rewrite.*`; `memory.*` (config-a shard).
- **Edge cases / guards:** on timeout the raw query is used.
- **Rebuild notes:** sub-second query expansion with a hard deadline and graceful degradation.

### Auxiliary → Tts Audio Tags (6 keys)  `id: config-b.auxiliary.tts_audio_tags`
- **Surface:** Config | Tool
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.tts_audio_tags.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`30`), `.reasoning_effort`. CLI picker row `TTS audio tags` — "Gemini TTS tag insertion".
- **What it does:** Inserts expressive audio tags into text before Gemini TTS synthesis.
- **How it works:** `config_defaults.py:1251-1259`; called with `task="tts_audio_tags"` at `tools/tts_tool.py:2082`.
- **Inputs / options:** the six fields.
- **Outputs / side effects:** modified TTS input text; one extra call per synthesis.
- **Config / env:** `auxiliary.tts_audio_tags.*`; `tts.*` (config-a shard).
- **Edge cases / guards:** only meaningful for tag-aware TTS engines.
- **Rebuild notes:** text→annotated-text transform behind a feature flag.

### Auxiliary → Triage Specifier (6 keys)  `id: config-b.auxiliary.triage_specifier`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.triage_specifier.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`120`), `.reasoning_effort`. CLI picker row `Triage specifier` — "kanban spec fleshing".
- **What it does:** Fleshes out a rough one-liner in the Kanban **Triage** column into a concrete spec, then promotes it to `todo`.
- **How it works:** `config_defaults.py:1260-1278`; invoked by `hermes kanban specify` (single id or `--all`) at `hermes_cli/kanban_specify.py:181` (`task="triage_specifier"`).
- **Inputs / options:** the six fields; the comment recommends "a cheap, capable model here (gemini-flash works well); the main model is overkill for short spec expansion".
- **Outputs / side effects:** rewrites the card body and moves the card to `todo`.
- **Config / env:** `auxiliary.triage_specifier.*`; `kanban.*`.
- **Edge cases / guards:** 120 s allows a slow local model.
- **Rebuild notes:** prompt → structured spec → card update.

### Auxiliary → Kanban Decomposer (6 keys)  `id: config-b.auxiliary.kanban_decomposer`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.kanban_decomposer.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`180`), `.reasoning_effort`. CLI picker row `Kanban decomposer` — "task decomposition".
- **What it does:** Decomposes a triage task into a graph of child tasks routed to specialist profiles by description.
- **How it works:** `config_defaults.py:1279-1291`; invoked by `hermes kanban decompose` (`hermes_cli/kanban_decompose.py:320`, `task="kanban_decomposer"`) and by the kanban auto-decompose dispatcher tick. "Returns a JSON task graph; uses more tokens than the specifier so allow more headroom."
- **Inputs / options:** the six fields.
- **Outputs / side effects:** creates child cards with dependencies and assignees.
- **Config / env:** `auxiliary.kanban_decomposer.*`; `kanban.auto_decompose`, `kanban.auto_decompose_per_tick`, `kanban.orchestrator_profile`, `kanban.default_assignee`.
- **Edge cases / guards:** a malformed graph is rejected; per-tick cap bounds burst spend.
- **Rebuild notes:** JSON-schema-constrained decomposition call.

### Auxiliary → Profile Describer (6 keys)  `id: config-b.auxiliary.profile_describer`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.profile_describer.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`60`), `.reasoning_effort`. CLI picker row `Profile describer` — "auto profile descriptions".
- **What it does:** Auto-generates a 1–2 sentence description of what a profile is good at.
- **How it works:** `config_defaults.py:1292-1303`; invoked by `hermes profile describe <name> --auto` and the dashboard's auto-generate button (`hermes_cli/profile_describer.py:232`, `task="profile_describer"`). "Short, cheap call."
- **Inputs / options:** the six fields.
- **Outputs / side effects:** writes the profile description.
- **Config / env:** `auxiliary.profile_describer.*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** one-shot summarisation of a profile's prompt/skills.

### Auxiliary → Goal Judge (6 keys)  `id: config-b.auxiliary.goal_judge`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.goal_judge.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`60`), `.reasoning_effort`. **Not** listed in the `hermes model` auxiliary picker (`_AUX_TASKS`) — config-only.
- **What it does:** Evaluates whether a `/goal` run's latest response satisfies the goal/contract, and drafts goal contracts.
- **How it works:** `config_defaults.py:1304-1317`; called at `hermes_cli/goals.py:1278` and `:1351` with `task="goal_judge"`. "Short structured-JSON calls; a fast cheap model is fine."
- **Inputs / options:** the six fields.
- **Outputs / side effects:** goal pass/fail verdicts and drafted contracts.
- **Config / env:** `auxiliary.goal_judge.*`; `goals.max_turns`.
- **Edge cases / guards:** a lenient judge ends goal loops early; a strict one loops to the turn cap.
- **Rebuild notes:** rubric-scored JSON verdict.

### Auxiliary → Curator (6 keys)  `id: config-b.auxiliary.curator`
- **Surface:** Config | Skill
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.curator.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`600`), `.reasoning_effort`. CLI picker row `Curator` — "skill-usage review pass".
- **What it does:** Model for the skill-usage review fork (umbrella building over hundreds of candidate skills).
- **How it works:** `config_defaults.py:1318-1332`; read at `agent/curator.py:1801` (`_aux.get("curator", {})`). The 600 s timeout is deliberately generous "because the review pass can take several minutes on reasoning models". The comment names the override path verbatim: "`auto` = use main chat model; override via `hermes model` → auxiliary → Curator to route to a cheaper aux model (e.g. openrouter google/gemini-3-flash-preview)".
- **Inputs / options:** the six fields.
- **Outputs / side effects:** skill consolidation proposals.
- **Config / env:** `auxiliary.curator.*`; `curator.*` (section E).
- **Edge cases / guards:** only used when `curator.consolidate` is true (the deterministic prune needs no LLM).
- **Rebuild notes:** long-running batch review with its own timeout budget.

### Auxiliary → Monitor (6 keys)  `id: config-b.auxiliary.monitor`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.monitor.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`60`), `.reasoning_effort`. Not in the `hermes model` picker.
- **What it does:** Urgency/importance classifier used by the important-mail monitor catalog automation — scores candidate items 0–10 against the user's criteria so only above-threshold items are delivered.
- **How it works:** `config_defaults.py:1333-1352`; the consumer is `cron/scripts/classify_items.py:167` (`task="monitor"`), whose header states "Uses Hermes' auxiliary client with task="monitor", so the classifier model" is configurable.
- **Inputs / options:** the six fields; comment: "`auto` = main chat model; override to a cheap fast model (e.g. openrouter google/gemini-3-flash-preview, haiku) since per-item scoring is high-volume and a small model is fine".
- **Outputs / side effects:** per-item 0–10 scores driving delivery.
- **Config / env:** `auxiliary.monitor.*`.
- **Edge cases / guards:** high call volume — the per-task concurrency semaphore applies.
- **Rebuild notes:** batched scoring with a numeric-only output contract.

### Auxiliary → Background Review (8 keys)  `id: config-b.auxiliary.background_review`
- **Surface:** Config | Core | Memory
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.background_review.enabled` (boolean, `true`), `.provider` (`'auto'`), `.model` (`''`), `.base_url` (`''`), `.api_key` (`''`), `.timeout` (`120`), `.reasoning_effort` (`''`), `.max_input_tokens` (number, `600000`). Not in the `hermes model` picker.
- **What it does:** The post-turn self-improvement fork that decides whether to save a memory or patch a skill; `enabled: false` skips automatic spawns (manual `/refine` still works).
- **How it works:** `config_defaults.py:1353-1374`. `agent/background_review.py:266-289` `load_background_review_settings()` reads `auxiliary.background_review` once and returns `(is_truthy_value(task.get("enabled"), default=True), task_cfg)`, **failing open** (enabled) with a WARNING when config cannot be read. `_review_input_token_budget` (`background_review.py:246-263`) reads `max_input_tokens` (default `_REVIEW_MAX_INPUT_TOKENS_DEFAULT`), and `<= 0` means unlimited. Routing note from the comment: `auto` runs on the main chat model replaying the full conversation (warm prompt cache); a different provider/model automatically replays a compact digest instead of the full transcript, since a different model cannot reuse the main prompt cache ("Same model = full replay; different model = digest"). The budget caps the SUM of input tokens across the whole review tool loop (iterations separately capped at 16); the loop stops before the provider call that would cross it. The fork is spawned at `background_review.py:1040` with `task="background_review"`.
- **Inputs / options:** the eight fields.
- **Outputs / side effects:** memory writes / skill patches; extra token spend per turn.
- **Config / env:** `auxiliary.background_review.*`; `memory.*`, `skills.*`.
- **Edge cases / guards:** fail-open design means a broken config still bills reviews; issue #93057 motivated the budget.
- **Rebuild notes:** post-turn reflection fork with an aggregate input budget and cache-aware replay strategy.

### Auxiliary → Moa Reference / Moa Aggregator (10 keys)  `id: config-b.auxiliary.moa_tasks`
- **Surface:** Config | Core
- **Where:** Config page tab **Auxiliary** (category id `auxiliary`) → keys `auxiliary.moa_reference.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`900`) and `auxiliary.moa_aggregator.provider` (`'auto'`), `.model`, `.base_url`, `.api_key`, `.timeout` (`900`). Neither block exposes `reasoning_effort`. Not in the `hermes model` picker.
- **What it does:** Transport/credential defaults for the MoA reference (advisor) fan-out and for the aggregator synthesis call.
- **How it works:** `config_defaults.py:1375-1397`; used by `agent/moa_loop.py:590` (`task="moa_reference"`) and `:1375`, `:1869` (`task="moa_aggregator"`). Both are excluded from auxiliary cost accounting roll-ups (`agent/aux_accounting.py:43` `_EXCLUDED_TASKS = frozenset({"moa_reference", "moa_aggregator"})`). Setting `reasoning_effort` on either logs the warning at `agent/auxiliary_client.py:8739-8747` and is ignored — MoA reasoning depth is per slot (`moa.presets.<name>.reference_models[].reasoning_effort` / `aggregator.reasoning_effort`).
- **Inputs / options:** the ten fields; 900 s timeouts because a fan-out slot may be a slow reasoning model.
- **Outputs / side effects:** advisor and aggregator calls.
- **Config / env:** `auxiliary.moa_reference.*`, `auxiliary.moa_aggregator.*`; `moa.*` (section N).
- **Edge cases / guards:** per-slot preset values win over these task-level defaults.
- **Rebuild notes:** two credential lanes for the ensemble, with all model choice in the preset.

## D. Category `bedrock` (8 schema fields)

### Bedrock → Region  `id: config-b.bedrock.region`
- **Surface:** Config | Provider
- **Where:** Config page tab **Bedrock** (category id `bedrock`) → label `Region`, key `bedrock.region`, description `Bedrock → Region` (string, default `''`). Also written by the model setup wizard (`hermes model` → AWS Bedrock flow).
- **What it does:** AWS region for Bedrock API calls; only used when `model.provider` is `bedrock`.
- **How it works:** `hermes_cli/config_defaults.py:1083-1086`; `agent/bedrock_adapter.py:560-573` `resolve_bedrock_runtime_region()` — `bedrock_cfg = (config or {}).get("bedrock") or {}`, returns `bedrock.region` when non-empty, otherwise `resolve_bedrock_region()` (botocore session region, `bedrock_adapter.py:538`, then `us-east-1`). The setup flow writes it at `hermes_cli/model_setup_flows.py:2425` and `:2631`; the transport default is `us-east-1` (`agent/transports/bedrock.py:51`).
- **Inputs / options:** an AWS region string (e.g. `us-east-1`, `eu-central-1`).
- **Outputs / side effects:** endpoint selection for every Bedrock call and for model discovery.
- **Config / env:** `bedrock.region`; `AWS_REGION` / botocore profile as fallback.
- **Edge cases / guards:** the docstring notes this exists so the runtime region wins "when `bedrock.region` and the ambient AWS env/profile disagree"; cross-region inference profiles (`global.*`, `us.*`) still apply.
- **Rebuild notes:** config → env → SDK default resolution order.

### Bedrock → Discovery → Enabled / Provider Filter / Refresh Interval  `id: config-b.bedrock.discovery`
- **Surface:** Config | Provider
- **Where:** Config page tab **Bedrock** (category id `bedrock`) → labels `Enabled` (key `bedrock.discovery.enabled`, boolean, default `true`), `Provider Filter` (key `bedrock.discovery.provider_filter`, list, default `[]`), `Refresh Interval` (key `bedrock.discovery.refresh_interval`, number, default `3600`); descriptions `Bedrock → Discovery → …`.
- **What it does:** Declares auto-discovery of Bedrock models via `ListFoundationModels`, an optional provider allowlist, and the discovery cache TTL.
- **How it works:** `config_defaults.py:1087-1091`. The discovery implementation is `agent/bedrock_adapter.py:1567-1697` `discover_bedrock_models(region, provider_filter=None)`; it caches per `f"{region}:{','.join(sorted(provider_filter or []))}"` for `_DISCOVERY_CACHE_TTL_SECONDS = 3600` (`:1559`), filters with `filter_set = {f.lower() for f in (provider_filter or [])}` (`:1601`) and sorts global cross-region profiles first. **Honest finding:** at v2026.8.31 nothing reads `bedrock.discovery.*` from config — the three call sites (`bedrock_adapter.py:588`, `hermes_cli/model_setup_flows.py:2507`, `hermes_cli/models.py:7238`) call `discover_bedrock_models(region)` with no filter, and the TTL is the module constant, so these keys are currently inert/documentation-only. `grep -rn 'get("bedrock")' ` shows only `region` and `guardrail` being consumed.
- **Inputs / options:** boolean; list of provider names (e.g. `["anthropic", "amazon"]`); seconds.
- **Outputs / side effects:** none today; intended: which models the picker lists and how long they are cached.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** setting them has no observable effect in this release — a rebuild must wire them into the discovery call.
- **Rebuild notes:** pass the config values into the discovery function and key the cache on them; note the returned model dict shape (`id`, `name`, `provider`, `input_modalities`, `output_modalities`, `streaming`).

### Bedrock → Guardrail (4 keys)  `id: config-b.bedrock.guardrail`
- **Surface:** Config | Provider | Security
- **Where:** Config page tab **Bedrock** (category id `bedrock`) → labels `Guardrail Identifier` (key `bedrock.guardrail.guardrail_identifier`, string, `''`), `Guardrail Version` (`bedrock.guardrail.guardrail_version`, string, `''`), `Stream Processing Mode` (`bedrock.guardrail.stream_processing_mode`, string, `'async'`), `Trace` (`bedrock.guardrail.trace`, string, `'disabled'`); descriptions `Bedrock → Guardrail → …`.
- **What it does:** Attaches an Amazon Bedrock Guardrail (content filtering / safety policy) to every Bedrock request.
- **How it works:** `config_defaults.py:1092-1101` (with the console link `https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html`). Both the agent path and the runtime-provider path build the same AWS `guardrailConfig`: `agent/agent_init.py:1274-1283` — `_gr = _load_br_cfg().get("bedrock", {}).get("guardrail", {})`; only when BOTH `guardrail_identifier` and `guardrail_version` are set does it emit `{"guardrailIdentifier": …, "guardrailVersion": …}`, then optionally `["streamProcessingMode"] = _gr["stream_processing_mode"]` and `["trace"] = _gr["trace"]`. Mirrored at `hermes_cli/runtime_provider.py:2375-2392`.
- **Inputs / options:** identifier (e.g. `"abc123def456"`); version (e.g. `"1"` or `"DRAFT"`); `stream_processing_mode` ∈ `sync` | `async`; `trace` ∈ `enabled` | `disabled` | `enabled_full`.
- **Outputs / side effects:** guardrail interventions can block or mask model output; traces appear in the Bedrock response.
- **Config / env:** the four dotted keys.
- **Edge cases / guards:** setting only one of identifier/version silently disables the guardrail (the `and` guard).
- **Rebuild notes:** pass-through of the provider's guardrail block, gated on a complete pair.

## E. Category `curator` (10 schema fields)

### Curator → Enabled  `id: config-b.curator.enabled`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → label `Enabled`, key `curator.enabled`, description `Curator → Enabled` (boolean, default `true`).
- **What it does:** Master switch for the skill curator (the periodic skill-hygiene pass).
- **How it works:** `hermes_cli/config_defaults.py:2330-2331`; consumed by `agent/curator.py` and the `hermes curator` command family.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** no scheduled curator runs when false.
- **Config / env:** `curator.enabled`.
- **Edge cases / guards:** `hermes curator run` remains available manually.
- **Rebuild notes:** gate around the scheduler hook.

### Curator → Interval Hours / Min Idle Hours  `id: config-b.curator.cadence`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → labels `Interval Hours` (key `curator.interval_hours`, number, default `168` — written in source as `24 * 7`) and `Min Idle Hours` (key `curator.min_idle_hours`, number, default `2`).
- **What it does:** How long to wait between curator runs, and how long the agent must have been idle before one may start.
- **How it works:** `config_defaults.py:2332-2336`.
- **Inputs / options:** hours (integers).
- **Outputs / side effects:** run scheduling only.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** a busy install may never reach the idle window.
- **Rebuild notes:** last-run timestamp + idle detector.

### Curator → Stale After Days / Archive After Days  `id: config-b.curator.inactivity`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → labels `Stale After Days` (key `curator.stale_after_days`, number, default `30`) and `Archive After Days` (key `curator.archive_after_days`, number, default `90`).
- **What it does:** Marks a skill "stale" after N days without use, and archives it (moves to `skills/.archive/`) after M days without use.
- **How it works:** `config_defaults.py:2337-2341`; archived skills are recoverable — "no auto-deletion".
- **Inputs / options:** days.
- **Outputs / side effects:** files move under `~/.hermes/skills/.archive/`.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** built-ins are only archived when `curator.prune_builtins` is true.
- **Rebuild notes:** usage telemetry per skill + two thresholds.

### Curator → Consolidate  `id: config-b.curator.consolidate`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → label `Consolidate`, key `curator.consolidate`, description `Curator → Consolidate` (boolean, default `false`).
- **What it does:** Runs the LLM consolidation (umbrella-building) pass that merges overlapping skills into class-level umbrellas. OFF by default.
- **How it works:** `config_defaults.py:2342-2349`: when off, "a curator run does ONLY the deterministic inactivity prune (mark stale / archive long-unused skills) and skips the forked aux-model review entirely — no umbrella-building, no aux-model cost". `hermes curator run --consolidate` overrides it for a single invocation.
- **Inputs / options:** `true` | `false`; CLI flag `--consolidate`.
- **Outputs / side effects:** aux-model spend (task `curator`), merged skill files.
- **Config / env:** `curator.consolidate`; `auxiliary.curator.*`.
- **Edge cases / guards:** consolidation rewrites skills — the pre-run backup exists for this.
- **Rebuild notes:** split the deterministic pass from the LLM pass and gate the latter.

### Curator → Prune Builtins  `id: config-b.curator.prune_builtins`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → label `Prune Builtins`, key `curator.prune_builtins`, description `Curator → Prune Builtins` (boolean, default `true`).
- **What it does:** Also archives bundled built-in skills after the inactivity period, not just agent-created ones.
- **How it works:** `config_defaults.py:2350-2360`. Built-ins are normally restored on every `hermes update`, so pruning them "only sticks because a suppression list tells the re-seeder to leave them archived". Hub-installed skills are NEVER pruned here (they have an external upstream owner). Built-ins accrue usage telemetry and their inactivity clock starts the first time the curator sees them, so a long-unused built-in is archived only after `archive_after_days` of genuine non-use — never a mass-prune on the first run.
- **Inputs / options:** `true` | `false` (false keeps all bundled built-ins permanently).
- **Outputs / side effects:** entries added to the re-seeder suppression list.
- **Config / env:** `curator.prune_builtins`.
- **Edge cases / guards:** hub-installed skills are exempt by design.
- **Rebuild notes:** archive + suppression list so an updater does not resurrect pruned built-ins.

### Curator → Archive Ttl Days  `id: config-b.curator.archive_ttl_days`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → label `Archive Ttl Days`, key `curator.archive_ttl_days`, description `Curator → Archive Ttl Days` (number, default `0`).
- **What it does:** TTL purge of `skills/.archive/`. `0` = never purge; when > 0, `hermes curator purge` deletes archived skills older than this many days.
- **How it works:** `config_defaults.py:2361-2365`: "explicit command only, never automatic; every purge is recorded in the audit ledger".
- **Inputs / options:** days; `0` disables.
- **Outputs / side effects:** irreversible deletion of archived skill directories; an audit-ledger entry.
- **Config / env:** `curator.archive_ttl_days`.
- **Edge cases / guards:** the only destructive curator path — still requires the explicit command.
- **Rebuild notes:** age filter + ledgered delete.

### Curator → Backup → Enabled / Keep  `id: config-b.curator.backup`
- **Surface:** Config | Skill
- **Where:** Config page tab **Curator** (category id `curator`) → labels `Enabled` (key `curator.backup.enabled`, boolean, default `true`) and `Keep` (key `curator.backup.keep`, number, default `5`); descriptions `Curator → Backup → Enabled` / `→ Keep`.
- **What it does:** Before every real curator pass (dry-run is skipped) snapshots `~/.hermes/skills/` so the user can roll back.
- **How it works:** `config_defaults.py:2366-2372`: the snapshot path is `~/.hermes/skills/.curator_backups/<utc-iso>/skills.tar.gz`; rollback is `hermes curator rollback`; `keep` retains the last N regular snapshots.
- **Inputs / options:** boolean; integer N.
- **Outputs / side effects:** tar.gz files on disk; oldest snapshots deleted beyond N.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** disabling backups makes consolidation unrecoverable.
- **Rebuild notes:** timestamped tarball with retention.

## F. Category `database` (3 schema fields)

### Database → Journal Mode  `id: config-b.database.journal_mode`
- **Surface:** Config | Core
- **Where:** Config page tab **Database** (category id `database`) → label `Journal Mode`, key `database.journal_mode`, description `Database → Journal Mode` (string, default `'wal'`).
- **What it does:** SQLite journal mode for `~/.hermes/state.db`.
- **How it works:** `hermes_cli/config_defaults.py:16-17`; read at `hermes_state.py:1354` `raw = database.get("journal_mode", "wal")` and applied as a PRAGMA at connection open. The effective value is reported by `hermes doctor` (`hermes_cli/doctor.py:449-450` appends `journal_mode=<value>` to the DB row) and by session recovery diagnostics (`hermes_cli/session_recovery.py:301-303`, `:1202`, `:1507`, `:1707`).
- **Inputs / options:** any SQLite journal mode string — `wal` (default), `delete`, `truncate`, `persist`, `memory`, `off`.
- **Outputs / side effects:** presence/absence of `state.db-wal` / `-shm` files; concurrency behaviour.
- **Config / env:** `database.journal_mode`.
- **Edge cases / guards:** non-WAL modes serialise readers/writers; network filesystems may need `delete`.
- **Rebuild notes:** one PRAGMA at connect, surfaced in diagnostics.

### Database → Wal Autocheckpoint / Journal Size Limit  `id: config-b.database.wal_sizing`
- **Surface:** Config | Core
- **Where:** Config page tab **Database** (category id `database`) → labels `Wal Autocheckpoint` (key `database.wal_autocheckpoint`, type `string` because the default is `None`, default `null`) and `Journal Size Limit` (key `database.journal_size_limit`, `string`/`null`).
- **What it does:** Optional WAL sizing PRAGMAs, applied only when set to integers. `null` = SQLite defaults (autocheckpoint 1000 pages, no size limit).
- **How it works:** `config_defaults.py:18-21` (comment verbatim); the two names are applied from the pragma list at `hermes_state.py:2001-2002`.
- **Inputs / options:** integers — pages for `wal_autocheckpoint`, bytes for `journal_size_limit`; `null` leaves SQLite defaults.
- **Outputs / side effects:** WAL file growth/truncation behaviour.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** because the default is `None`, the generated schema types them as `string`; the UI shows a text box and a non-integer value is ignored.
- **Rebuild notes:** optional PRAGMA pass-through with an int guard.

## G. Category `desktop` (11 schema fields)

### Desktop → Repo scan (3 keys)  `id: config-b.desktop.repo_scan`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → labels `Repo Scan Enabled` (key `desktop.repo_scan_enabled`, boolean, default `true`), `Repo Scan Roots` (key `desktop.repo_scan_roots`, list, default `[]`), `Repo Scan Exclude Paths` (key `desktop.repo_scan_exclude_paths`, list, default `[]`).
- **What it does:** Controls git-repository discovery for the Desktop **Projects** sidebar.
- **How it works:** `hermes_cli/config_defaults.py:3883-3889`: "Empty roots preserve the historical bounded scan of the user's home." These keys only affect `hermes desktop`; they do not touch the CLI/gateway (`config_defaults.py:3881-3882`).
- **Inputs / options:** boolean; list of absolute/`~` roots; list of paths to skip.
- **Outputs / side effects:** which repos appear in the sidebar; filesystem scan cost at startup.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** a huge root (e.g. `/`) makes the scan slow; exclusions are the mitigation.
- **Rebuild notes:** bounded breadth-first `.git` search with an exclusion set.

### Desktop → Electron Flags  `id: config-b.desktop.electron_flags`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → label `Electron Flags`, key `desktop.electron_flags`, description `Desktop → Electron Flags` (list, default `[]`).
- **What it does:** Extra Electron command-line flags appended to every desktop launch.
- **How it works:** `config_defaults.py:3890-3893`; examples given verbatim: `["--ozone-platform=x11"]` on headless/VM X11 hosts that need an explicit ozone backend, or GPU workaround flags. "A list of strings; a single string is also accepted and shell-split."
- **Inputs / options:** list of flag strings (or one string).
- **Outputs / side effects:** modifies the Electron process argv.
- **Config / env:** `desktop.electron_flags`.
- **Edge cases / guards:** a bad flag can prevent the app from starting.
- **Rebuild notes:** append-to-argv with shell-splitting for the string form.

### Desktop → Ozone Platform Hint  `id: config-b.desktop.ozone_platform_hint`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → label `Ozone Platform Hint`, key `desktop.ozone_platform_hint`, description `Desktop → Ozone Platform Hint` (string, default `'auto'`).
- **What it does:** Linux Ozone backend hint, bridged to `ELECTRON_OZONE_PLATFORM_HINT` at launch (an explicit env var still wins).
- **How it works:** `config_defaults.py:3894-3902`. `"auto"` is Chromium's default (Wayland on a Wayland session, X11 otherwise). Setting `"x11"` runs under XWayland "when a compositor ignores always-on-top for native Wayland clients (COSMIC, issue #84011)"; that "also lands the HUD on the solid-window input path, because `setIgnoreMouseEvents` is a one-way door on X11". `"wayland"` forces a native Wayland surface.
- **Inputs / options:** `auto` | `x11` | `wayland`.
- **Outputs / side effects:** sets an env var for the Electron child; changes HUD input behaviour.
- **Config / env:** `desktop.ozone_platform_hint`; env `ELECTRON_OZONE_PLATFORM_HINT` (wins).
- **Edge cases / guards:** Linux-only.
- **Rebuild notes:** config→env bridge with env precedence.

### Desktop → Disable Gpu  `id: config-b.desktop.disable_gpu`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → label `Disable Gpu`, key `desktop.disable_gpu`, description `Desktop → Disable Gpu` (string, default `'auto'`).
- **What it does:** GPU hardware-acceleration policy for the desktop app.
- **How it works:** `config_defaults.py:3903-3910`; bridged to `HERMES_DESKTOP_DISABLE_GPU`, which the Electron app reads. Options verbatim: `"auto"` — let the app detect remote displays (SSH/VNC/RDP) and disable GPU only then (default; current behavior); `true` — always disable GPU acceleration (software rendering), "Use on no-GPU VMs / Proxmox hosts where the GPU path hangs"; `false` — always keep GPU acceleration on, even over a remote display.
- **Inputs / options:** `auto` | `true` | `false`.
- **Outputs / side effects:** sets `HERMES_DESKTOP_DISABLE_GPU`; changes renderer performance.
- **Config / env:** `desktop.disable_gpu`; env `HERMES_DESKTOP_DISABLE_GPU`.
- **Edge cases / guards:** typed `string` in the schema even though booleans are accepted.
- **Rebuild notes:** tri-state policy with remote-display detection.

### Desktop → Password Store  `id: config-b.desktop.password_store`
- **Surface:** Config | Desktop app | Security
- **Where:** Config page tab **Desktop** (category id `desktop`) → label `Password Store`, key `desktop.password_store`, description `Desktop → Password Store` (string, default `'auto'`).
- **What it does:** Linux keychain backend for secure token storage (Chromium's `--password-store` switch, which `safeStorage` needs before it can encrypt remote gateway tokens).
- **How it works:** `config_defaults.py:3911-3921`; bridged to `HERMES_DESKTOP_PASSWORD_STORE` so an explicit env var still wins. `"auto"` detects the session keychain: KWallet via KDE session env vars, GNOME Keyring / any `org.freedesktop.secrets` provider (e.g. KeePassXC) via D-Bus.
- **Inputs / options:** `auto` | `gnome-libsecret` | `kwallet` | `kwallet5` | `kwallet6` | `basic` (`"basic"` = unencrypted store).
- **Outputs / side effects:** determines whether stored gateway tokens are encrypted at rest.
- **Config / env:** `desktop.password_store`; env `HERMES_DESKTOP_PASSWORD_STORE`.
- **Edge cases / guards:** ignored on macOS/Windows.
- **Rebuild notes:** detect-then-pin keychain backend selection.

### Desktop → Macos Signing Identity  `id: config-b.desktop.macos_signing_identity`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → label `Macos Signing Identity`, key `desktop.macos_signing_identity`, description `Desktop → Macos Signing Identity` (string, default `''`).
- **What it does:** macOS only — an optional persistent code-signing identity used to re-sign locally rebuilt desktop apps so TCC permission grants survive updates.
- **How it works:** `config_defaults.py:3922-3931`: a cert in the login keychain (a self-signed "Code Signing" cert from Keychain Access works; no Apple Developer account needed). "A certificate-anchored Designated Requirement stays stable across rebuilds, so TCC grants (Full Disk Access, Desktop/Downloads/Documents, Accessibility, Automation, microphone) survive every update. Empty keeps the default stable ad-hoc signing (identifier-pinned requirement)."
- **Inputs / options:** the identity string as `codesign -s` expects it.
- **Outputs / side effects:** the rebuilt `.app` is signed with that identity.
- **Config / env:** `desktop.macos_signing_identity`.
- **Edge cases / guards:** a wrong identity fails the signing step of a rebuild.
- **Rebuild notes:** pass the identity to `codesign` during packaging.

### Desktop → Auto Continue (3 keys)  `id: config-b.desktop.auto_continue`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Desktop** (category id `desktop`) → labels `Enabled` (key `desktop.auto_continue.enabled`, boolean, default `true`), `Freshness Minutes` (key `desktop.auto_continue.freshness_minutes`, number, default `15`), `Max Attempts` (key `desktop.auto_continue.max_attempts`, number, default `2`); descriptions `Desktop → Auto Continue → …`.
- **What it does:** Auto-continues a turn killed mid-run by an app/backend/machine crash: resuming that session re-submits the interrupted prompt (shown as a "resumed interrupted turn" event) if the interruption is fresh; a stale interruption just shows the recovered partial transcript.
- **How it works:** `config_defaults.py:3932-3944` (comment verbatim). `freshness_minutes` = how recent the interruption must be; `max_attempts` = crash-loop breaker capping automatic re-runs of one interrupted turn.
- **Inputs / options:** boolean; minutes; attempt count.
- **Outputs / side effects:** an extra agent turn on resume; a visible "resumed interrupted turn" event.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** a prompt that reliably crashes the app is stopped after `max_attempts`.
- **Rebuild notes:** persist the in-flight prompt + timestamp + attempt counter; replay on next open.

## H. Category `gateway` (22 schema fields)

Note on precedence: `gateway/config.py:1210-1340` builds the typed `GatewayConfig` from a merged dict, reading each key first at the top level of the gateway block and then from `nested_gateway` (`data["gateway"]`), so `gateway.<key>` in `config.yaml` and a top-level key of the same name both work; `gateway/config.py:1146-1161` re-serialises them.

### Gateway → Multiplex Profile Allowlist  `id: config-b.gateway.multiplex_profile_allowlist`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Multiplex Profile Allowlist`, key `gateway.multiplex_profile_allowlist`, description `Gateway → Multiplex Profile Allowlist` (type `string` because the default is `None`, default `null`).
- **What it does:** Optional named-profile allowlist for multiplex mode — which profiles the one gateway process will serve.
- **How it works:** `hermes_cli/config_defaults.py:3172-3175`: "None preserves the historical serve-all behavior; `[]` serves only the default." Carried on `GatewayConfig` (`gateway/config.py:1155`, parsed at `:1225`), passed to the router at `gateway/run.py:2470` (`profile_allowlist=getattr(config, "multiplex_profile_allowlist", None)`), and enforced on the programmatic surfaces at `gateway/platforms/api_server.py:2140` and `gateway/platforms/webhook.py:604`.
- **Inputs / options:** `null` (all), `[]` (default profile only), or a YAML list of profile names.
- **Outputs / side effects:** requests naming a non-allowed profile are refused.
- **Config / env:** `gateway.multiplex_profile_allowlist`.
- **Edge cases / guards:** the schema types it `string`; entering a comma list in the UI stores a string, so prefer YAML mode for a real list.
- **Rebuild notes:** tri-state allowlist (None/[]/list) checked at profile resolution.

### Gateway → Signal Interrupt Grace Timeout  `id: config-b.gateway.signal_interrupt_grace_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Signal Interrupt Grace Timeout`, key `gateway.signal_interrupt_grace_timeout`, description `Gateway → Signal Interrupt Grace Timeout` (number, default `1`).
- **What it does:** After an unexpected SIGTERM interrupts a running gateway agent, wait this many seconds for it to unwind before adapter and database teardown proceeds.
- **How it works:** `config_defaults.py:3177-3181`; the default is re-exported at `gateway/restart.py:28` (`DEFAULT_CONFIG["gateway"]["signal_interrupt_grace_timeout"]`) and read at `gateway/run.py:10438`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** delays teardown by up to that long.
- **Config / env:** `gateway.signal_interrupt_grace_timeout`.
- **Edge cases / guards:** "Keep this short so service-manager shutdowns do not exhaust their stop budget before resource cleanup begins."
- **Rebuild notes:** small grace window between signal and teardown.

### Gateway → Delivery Ledger  `id: config-b.gateway.delivery_ledger`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Delivery Ledger`, key `gateway.delivery_ledger`, description `Gateway → Delivery Ledger` (boolean, default `true`).
- **What it does:** Durable delivery-obligation ledger: final agent responses are recorded in `state.db` around the platform send, and a gateway that died between finalize and platform ACK redelivers the stored response on the next boot.
- **How it works:** `config_defaults.py:3183-3192`; read at `gateway/delivery_ledger.py:535` `value = gw.get("delivery_ledger", True)`. Ambiguous cases carry a visible "recovered reply — may be a duplicate" marker ("honest at-least-once").
- **Inputs / options:** `true` | `false` (false loses in-flight final responses on crash/restart, as before).
- **Outputs / side effects:** ledger rows in `state.db`; possible duplicate deliveries with a marker.
- **Config / env:** `gateway.delivery_ledger`.
- **Edge cases / guards:** at-least-once, not exactly-once, by design.
- **Rebuild notes:** write-ahead record around the send + replay on boot.

### Gateway → Platform Connect Timeout  `id: config-b.gateway.platform_connect_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Platform Connect Timeout`, key `gateway.platform_connect_timeout`, description `Gateway → Platform Connect Timeout` (number, default `30`).
- **What it does:** Seconds the gateway waits for a single messaging platform to finish connecting during startup (and on reconnect).
- **How it works:** `config_defaults.py:3194-3205`; read at `gateway/run.py:2890-2894`, then bridged at startup to the internal env var `HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT`, "which still works as a manual override and wins if set explicitly". The comment cites #19776: Discord with 90-173 skills takes ~28-31 s to sync slash commands, which blows past the old fixed 30 s and causes "discord connect timed out" / "Timeout waiting for connection to Discord" restart loops.
- **Inputs / options:** seconds; `0` or negative disables the timeout entirely (wait indefinitely).
- **Outputs / side effects:** startup abort/restart on timeout.
- **Config / env:** `gateway.platform_connect_timeout`; env `HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT` (wins).
- **Edge cases / guards:** raising it is the documented fix for Discord slash-command sync storms.
- **Rebuild notes:** per-adapter connect deadline with an escape hatch.

### Gateway → Loop watchdog (4 keys)  `id: config-b.gateway.loop_watchdog`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → labels `Loop Watchdog` (key `gateway.loop_watchdog`, boolean, default `true`), `Loop Watchdog Probe Interval S` (`gateway.loop_watchdog_probe_interval_s`, number, `30.0`), `Loop Watchdog Probe Timeout S` (`gateway.loop_watchdog_probe_timeout_s`, number, `10.0`), `Loop Watchdog Max Strikes` (`gateway.loop_watchdog_max_strikes`, number, `3`).
- **What it does:** In-process event-loop liveness watchdog (#69089): a daemon OS thread probes the gateway asyncio loop; after consecutive missed probes it dumps all-thread stacks and hard-exits with the service-restart exit code so the supervisor revives the process instead of leaving a wedged-but-alive zombie.
- **How it works:** `config_defaults.py:3201-3216`; defaults mirror `gateway/shutdown_watchdog.py` constants. Enabled check `gateway/run.py:13246` (`if config is not None and not getattr(config, "loop_watchdog", True)`), tuning read at `run.py:13262`, `:13267`, `:13272`; all four are typed fields on `GatewayConfig` (`gateway/config.py:1158-1161`, parsed `:1243-1263`). Semantics: `probe_interval` = seconds between liveness probes; `probe_timeout` = seconds a probe may go unprocessed before counting as a miss; `max_strikes` = consecutive misses before the watchdog hard-exits **75** for a service respawn (~90-120 s of sustained loop block at the defaults).
- **Inputs / options:** boolean + three numbers.
- **Outputs / side effects:** all-thread stack dump in the logs; `exit(75)`; supervisor restart.
- **Config / env:** the four dotted keys.
- **Edge cases / guards:** a machine under heavy IO can trip it; raise `max_strikes` rather than disabling.
- **Rebuild notes:** watchdog thread + `loop.call_soon_threadsafe` ping with a strike counter and a stack dump before exit.

### Gateway → Write Sessions Json  `id: config-b.gateway.write_sessions_json`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Write Sessions Json`, key `gateway.write_sessions_json`, description `Gateway → Write Sessions Json` (boolean, default `true`).
- **What it does:** Whether the gateway keeps writing the legacy `sessions.json` mirror of its routing index (the primary copy lives in the `gateway_routing` table in `state.db`).
- **How it works:** `config_defaults.py:3218-3224`; read at `gateway/session.py:1296` (`getattr(config, "write_sessions_json", True)`); typed field at `gateway/config.py:1146`, coerced at `:1329` (`_coerce_bool(data.get("write_sessions_json"), True)`), and also accepted as a top-level YAML key at `:1547-1548`.
- **Inputs / options:** `true` | `false` (false stops producing `~/.hermes/sessions/sessions.json` entirely).
- **Outputs / side effects:** presence and freshness of that file.
- **Config / env:** `gateway.write_sessions_json`.
- **Edge cases / guards:** kept true "for backward compatibility with external tooling and downgrade safety".
- **Rebuild notes:** optional JSON mirror of a DB table.

### Gateway → Scale To Zero → Idle Timeout Minutes  `id: config-b.gateway.scale_to_zero`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Idle Timeout Minutes`, key `gateway.scale_to_zero.idle_timeout_minutes`, description `Gateway → Scale To Zero → Idle Timeout Minutes` (number, default `2`).
- **What it does:** Idle timeout for scale-to-zero: the gateway watches for idle and drives the relay transport dormant so the hosting platform (e.g. Fly `autostop:"suspend"`) can suspend the machine; it wakes on the connector's `wakeUrl` poke.
- **How it works:** `config_defaults.py:3226-3238`; read at `gateway/run.py:9325` (`raw = stz.get("idle_timeout_minutes")`). The comment is emphatic about scope: "This is the idle TIMEOUT only — whether the feature is enabled at all is the Labs toggle, never a config key (decisions.md D2/D11)"; the enabling conditions are the NAS "Labs" toggle carried as the `HERMES_SCALE_TO_ZERO` env stamp AND messaging being relay-only/absent AND a registered `wakeUrl`.
- **Inputs / options:** minutes; `0`/negative falls back to the default.
- **Outputs / side effects:** relay transport goes dormant; the machine may suspend.
- **Config / env:** `gateway.scale_to_zero.idle_timeout_minutes`; env stamp `HERMES_SCALE_TO_ZERO`.
- **Edge cases / guards:** without the Labs toggle the key does nothing.
- **Rebuild notes:** idle timer that parks the transport, plus a wake endpoint.

### Gateway → Restart Loop Guard (3 keys)  `id: config-b.gateway.restart_loop_guard`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → labels `Max Restarts` (key `gateway.restart_loop_guard.max_restarts`, number, `3`), `Window Seconds` (`gateway.restart_loop_guard.window_seconds`, number, `60`), `Max Gap Seconds` (`gateway.restart_loop_guard.max_gap_seconds`, number, `300`).
- **What it does:** Auto-resume restart-loop breaker (#30719, defense-3). When a gateway killed mid-turn is revived by a supervisor it auto-resumes the interrupted session; if that turn keeps triggering another kill, the breaker chains restart-interrupted boots and, after `max_restarts` of them, SKIPS auto-resume for that boot — the gateway still starts and serves real inbound messages, it just stops replaying the session that keeps killing it.
- **How it works:** `config_defaults.py:3240-3266`; read at `gateway/run.py:9350-9353` (`rlg.get("max_restarts")`, `rlg.get("window_seconds")`). Chaining rule: two boots belong to the same chain when they are no more than `max_gap_seconds` apart (floored by `window_seconds`). The comment explains why the gap matters: a slow crash cycle whose period exceeds the window used to prune its own history on every boot, so the counter never left 1 — e.g. the ~150 s wedged-event-loop cycle in #81642 (stall → ~90 s liveness-watchdog hard-exit → respawn → auto-resume replays the same session), which also makes `hermes update` hang because it can never drain the gateway.
- **Inputs / options:** three integers; `max_restarts: 0` disables the breaker.
- **Outputs / side effects:** auto-resume is skipped for a boot; chain state persisted between boots.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** the guard never prevents the gateway from starting, only from replaying.
- **Rebuild notes:** persistent chain counter keyed on boot gaps.

### Gateway → Respawn Storm (2 keys)  `id: config-b.gateway.respawn_storm`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → labels `Max Starts` (key `gateway.respawn_storm.max_starts`, number, `5`) and `Window Seconds` (`gateway.respawn_storm.window_seconds`, number, `120`).
- **What it does:** Portable respawn-storm circuit breaker: counts gateway (re)starts in a sliding window and, when too many land, sleeps an exponential backoff before booting so a crash-looping supervisor cannot hammer the process into a respawn storm.
- **How it works:** `config_defaults.py:3268-3277`; read at `hermes_cli/gateway.py:6595-6598` (`_rs.get("max_starts")`, `_rs.get("window_seconds")` as float).
- **Inputs / options:** integers; `max_starts <= 0` disables the breaker. Escape-hatch env vars `HERMES_GATEWAY_MAX_STARTS` / `HERMES_GATEWAY_START_WINDOW_S` override these defaults.
- **Outputs / side effects:** a startup sleep before the process serves traffic.
- **Config / env:** the two dotted keys + the two env vars.
- **Edge cases / guards:** complements (does not replace) `restart_loop_guard`.
- **Rebuild notes:** start-timestamp ring buffer + exponential pre-boot sleep.

### Gateway → Message Timestamps → Enabled  `id: config-b.gateway.message_timestamps`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Enabled`, key `gateway.message_timestamps.enabled`, description `Gateway → Message Timestamps → Enabled` (boolean, default `false`).
- **What it does:** Injects a human-readable timestamp prefix (e.g. `[Tue 2026-04-28 13:40:53 CEST]`) onto user messages IN THE MODEL'S CONTEXT so the agent has temporal awareness of when each message was sent.
- **How it works:** `config_defaults.py:3279-3288`; `gateway/run.py:1791-1804` `_message_timestamps_enabled(user_config)` reads `gw.get("message_timestamps")`. The reverse operation lives in `gateway/message_timestamps.py:88` `strip_leading_message_timestamps(content, tz=None)` (used at `:122`), so persisted transcripts always stay clean — the timestamp is stored as message metadata regardless of the toggle, and turning it on later surfaces send-times for past messages too.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** prompt text changes; no change to stored transcripts.
- **Config / env:** `gateway.message_timestamps.enabled`; `timezone` (root key) selects the rendered zone.
- **Edge cases / guards:** off by default — "when off, the model sees clean message text".
- **Rebuild notes:** render-time prefix from stored metadata, plus a stripper for round-trips.

### Gateway → Max Inbound Media Bytes  `id: config-b.gateway.max_inbound_media_bytes`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Max Inbound Media Bytes`, key `gateway.max_inbound_media_bytes`, description `Gateway → Max Inbound Media Bytes` (number, default `134217728` = 128 MiB).
- **What it does:** Maximum bytes for an inbound image / audio / video payload the gateway will buffer into memory and cache to disk.
- **How it works:** `config_defaults.py:3290-3300`; enforced in the shared cache helpers so the cap holds across every platform adapter — `gateway/platforms/base.py:816-819` (`if not isinstance(gw, dict) or "max_inbound_media_bytes" not in gw` … `return int(gw["max_inbound_media_bytes"])`).
- **Inputs / options:** integer bytes; `0` disables the cap.
- **Outputs / side effects:** oversized inbound media is rejected instead of cached.
- **Config / env:** `gateway.max_inbound_media_bytes`.
- **Edge cases / guards:** the rationale is OOM protection — "Inbound media is read fully into RAM before being written, so an unbounded upload (Discord Nitro allows 500 MB) or a remote media URL pointing at a huge file can spike memory and OOM-kill the gateway on constrained deployments."
- **Rebuild notes:** size check in the single shared cache helper, not per adapter.

### Gateway → Strict (media delivery posture)  `id: config-b.gateway.strict`
- **Surface:** Config | Gateway/Telegram | Security
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Strict`, key `gateway.strict`, description `Gateway → Strict` (boolean, default `false`).
- **What it does:** Chooses the outbound file-delivery posture. Default (`false`): any file path the agent emits is delivered as a native attachment as long as it is not under the credential/system-path denylist (`/etc`, `/proc`, `~/.ssh`, `~/.aws`, `~/.hermes/.env`, `auth.json`, …). `true`: fall back to the older allowlist+recency-window behaviour — files must live under the Hermes cache, under `media_delivery_allow_dirs`, or be freshly produced inside the `trust_recent_files_seconds` window.
- **How it works:** `config_defaults.py:3294-3312`; `gateway/media_policy.py:69-71` bridges it to the env var `_STRICT_ENV` (`HERMES_MEDIA_DELIVERY_STRICT`) only when the env var is unset, so "operator shell exports keep precedence"; the whole bridge is wrapped so "a policy-bridge failure must not break delivery".
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** which agent-emitted paths become attachments.
- **Config / env:** `gateway.strict`; env `HERMES_MEDIA_DELIVERY_STRICT` (wins).
- **Edge cases / guards:** strict mode is "Recommended for public-facing gateways where prompt injection from one user shouldn't be able to exfiltrate the host's secrets to that same user."
- **Rebuild notes:** denylist-by-default vs allowlist-by-default toggle in one policy module.

### Gateway → Media Delivery Allow Dirs  `id: config-b.gateway.media_delivery_allow_dirs`
- **Surface:** Config | Gateway/Telegram | Security
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Media Delivery Allow Dirs`, key `gateway.media_delivery_allow_dirs`, description `Gateway → Media Delivery Allow Dirs` (list, default `[]`).
- **What it does:** Extra directories from which model-emitted bare file paths may be uploaded as native gateway attachments (project dirs, scratch dirs, mounted shares). Files inside the Hermes cache (`~/.hermes/cache/{documents,images,audio,video,screenshots}`) are always trusted.
- **How it works:** `config_defaults.py:3313-3321`; `gateway/media_policy.py:73-82` accepts a list/tuple (joined with `os.pathsep`) or a single string and exports it as `HERMES_MEDIA_ALLOW_DIRS` when that env var is unset. Tilde paths are expanded. Honored in both default and strict mode.
- **Inputs / options:** list of absolute paths, or one `os.pathsep`-separated string.
- **Outputs / side effects:** widens the delivery allowlist.
- **Config / env:** `gateway.media_delivery_allow_dirs`; env `HERMES_MEDIA_ALLOW_DIRS`.
- **Edge cases / guards:** adding `/` or `$HOME` defeats the purpose of strict mode.
- **Rebuild notes:** path-prefix allowlist evaluated after the denylist.

### Gateway → Trust Recent Files / Trust Recent Files Seconds  `id: config-b.gateway.trust_recent_files`
- **Surface:** Config | Gateway/Telegram | Security
- **Where:** Config page tab **Gateway** (category id `gateway`) → labels `Trust Recent Files` (key `gateway.trust_recent_files`, boolean, default `true`) and `Trust Recent Files Seconds` (key `gateway.trust_recent_files_seconds`, number, default `600`).
- **What it does:** In strict mode, trusts files whose mtime is within the recency window even outside the cache/operator allowlist — useful for `pandoc -o /tmp/report.pdf` or PDFs the agent writes into a working directory.
- **How it works:** `config_defaults.py:3322-3334`; `gateway/media_policy.py:84-86` bridges the boolean to `HERMES_MEDIA_TRUST_RECENT_FILES` when unset; the window is read at `gateway/run.py:2881` and bridged to `HERMES_MEDIA_TRUST_RECENT_SECONDS`. Both are "Only consulted when `strict` is true; in default mode the denylist alone gates delivery." System paths (`/etc`, `/proc`, `~/.ssh`, `~/.aws`, …) remain blocked regardless.
- **Inputs / options:** boolean; seconds (600 = 10 min, "comfortably covers a multi-tool agent turn").
- **Outputs / side effects:** more files deliverable in strict mode.
- **Config / env:** the two dotted keys; envs `HERMES_MEDIA_TRUST_RECENT_FILES`, `HERMES_MEDIA_TRUST_RECENT_SECONDS`.
- **Edge cases / guards:** disabling it yields pure-allowlist mode.
- **Rebuild notes:** mtime freshness check inside the strict branch.

### Gateway → Api Server → Max Concurrent Runs  `id: config-b.gateway.api_server_max_concurrent_runs`
- **Surface:** Config | API
- **Where:** Config page tab **Gateway** (category id `gateway`) → label `Max Concurrent Runs`, key `gateway.api_server.max_concurrent_runs`, description `Gateway → Api Server → Max Concurrent Runs` (number, default `10`).
- **What it does:** Maximum agent runs the OpenAI-compatible API-server platform will service concurrently; requests over the limit are rejected with HTTP 429 + `Retry-After`.
- **How it works:** `config_defaults.py:3336-3345`; read at `gateway/platforms/api_server.py:1773`. Applies to `/v1/chat/completions`, `/v1/responses` and `/v1/runs`, "bounding CPU / memory / upstream-LLM-quota exhaustion from a request flood".
- **Inputs / options:** integer; `0` disables the cap entirely.
- **Outputs / side effects:** 429 responses with a `Retry-After` header.
- **Config / env:** `gateway.api_server.max_concurrent_runs`.
- **Edge cases / guards:** the cap is per gateway process, not per profile.
- **Rebuild notes:** semaphore around run creation + 429 with backoff hint.

## I. Category `kanban` (16 schema fields)

Besides the Config page, four of these keys are editable from the Kanban dashboard plugin's orchestration form: `GET /orchestration` returns `{orchestrator_profile, default_assignee, auto_decompose, auto_promote_children, resolved_orchestrator_profile, resolved_default_assignee, active_profile}` and `PUT /orchestration` writes them back into `~/.hermes/config.yaml` via `save_config` (`plugins/kanban/dashboard/plugin_api.py:2863-2975`); a profile name that does not exist is rejected with HTTP 400 `profile '<name>' does not exist`.

### Kanban → Auto Subscribe On Create  `id: config-b.kanban.auto_subscribe_on_create`
- **Surface:** Config | Tool
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Auto Subscribe On Create`, key `kanban.auto_subscribe_on_create`, description `Kanban → Auto Subscribe On Create` (boolean, default `true`).
- **What it does:** Auto-subscribes the originating gateway/TUI session to task completion + block events when `kanban_create` is called from inside a session that has a persistent delivery channel, so the dispatching agent is notified instead of polling.
- **How it works:** `hermes_cli/config_defaults.py:2825-2832`; read at `tools/kanban_tools.py:1524` `if not cfg_get(cfg, "kanban", "auto_subscribe_on_create", default=True)`.
- **Inputs / options:** `true` | `false` (false mirrors pre-feature behaviour — explicit `kanban_notify-subscribe` calls per task).
- **Outputs / side effects:** subscription rows created alongside the card.
- **Config / env:** `kanban.auto_subscribe_on_create`.
- **Edge cases / guards:** only applies when the calling session has a delivery channel.
- **Rebuild notes:** implicit subscription at creation time.

### Kanban → Dispatch In Gateway  `id: config-b.kanban.dispatch_in_gateway`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Dispatch In Gateway`, key `kanban.dispatch_in_gateway`, description `Kanban → Dispatch In Gateway` (boolean, default `true`).
- **What it does:** Runs the kanban dispatcher inside the gateway process.
- **How it works:** `config_defaults.py:2833-2838`: "the cost is ~300µs every `dispatch_interval_seconds` when idle, and gateway is the supervisor users already have". Read at `gateway/kanban_watchers.py:1312` (`kanban_cfg.get("dispatch_in_gateway", True)`) and echoed by the CLI at `hermes_cli/kanban.py:187`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** worker processes spawned by the gateway.
- **Config / env:** `kanban.dispatch_in_gateway`.
- **Edge cases / guards:** set false only when running the dispatcher as a separate systemd unit.
- **Rebuild notes:** co-locate the scheduler in the long-lived supervisor by default.

### Kanban → Review Dispatch  `id: config-b.kanban.review_dispatch`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Review Dispatch`, key `kanban.review_dispatch`, description `Kanban → Review Dispatch` (boolean, default `true`).
- **What it does:** Automatically claims tasks in the first-class review column and spawns the assigned profile with the bundled `sdlc-review` skill.
- **How it works:** `config_defaults.py:2839-2842`; read at `hermes_cli/kanban_db.py:9618` `(load_config() or {}).get("kanban", {}).get("review_dispatch", True)`.
- **Inputs / options:** `true` | `false` ("Disable for boards where every review is performed manually from the dashboard").
- **Outputs / side effects:** review workers spawn automatically.
- **Config / env:** `kanban.review_dispatch`.
- **Edge cases / guards:** shares the global concurrency cap with the ready lane.
- **Rebuild notes:** second dispatch lane keyed on the review column.

### Kanban → Dispatch Interval Seconds  `id: config-b.kanban.dispatch_interval_seconds`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Dispatch Interval Seconds`, key `kanban.dispatch_interval_seconds`, description `Kanban → Dispatch Interval Seconds` (number, default `60`).
- **What it does:** Seconds between dispatcher ticks, idle or not.
- **How it works:** `config_defaults.py:2843-2845`; read at `gateway/kanban_watchers.py:1350` `interval = float(kanban_cfg.get("dispatch_interval_seconds", 60) or 60)` (also logged at `:1354`).
- **Inputs / options:** seconds. "Lower = snappier pickup of newly-ready tasks; higher = less SQL pressure."
- **Outputs / side effects:** tick cadence for claims, stale reclaims, orphan reconciliation and auto-decompose.
- **Config / env:** `kanban.dispatch_interval_seconds`.
- **Edge cases / guards:** `0`/falsy falls back to 60 by the `or 60` guard.
- **Rebuild notes:** single periodic tick doing all board maintenance.

### Kanban → Failure Limit  `id: config-b.kanban.failure_limit`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Failure Limit`, key `kanban.failure_limit`, description `Kanban → Failure Limit` (number, default `2`).
- **What it does:** Auto-blocks a card after this many consecutive non-success attempts for the same task/profile (`spawn_failed`, `timed_out`, or `crashed`).
- **How it works:** `config_defaults.py:2846-2849`; read at `gateway/kanban_watchers.py:1403` (`kanban_cfg.get("failure_limit", _kb.DEFAULT_FAILURE_LIMIT)`) and surfaced in diagnostics at `hermes_cli/kanban_diagnostics.py:551,648,1137`.
- **Inputs / options:** integer.
- **Outputs / side effects:** the card moves to blocked; a block event fires to subscribers.
- **Config / env:** `kanban.failure_limit`.
- **Edge cases / guards:** "Reassignment resets the streak for the new profile."
- **Rebuild notes:** per (task, profile) failure counter with reset on reassignment.

### Kanban → Worker Log Rotate Bytes / Worker Log Backup Count  `id: config-b.kanban.worker_logs`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → labels `Worker Log Rotate Bytes` (key `kanban.worker_log_rotate_bytes`, number, default `2097152` = 2 MiB) and `Worker Log Backup Count` (key `kanban.worker_log_backup_count`, number, default `1`).
- **What it does:** Rotation policy for kanban worker stdout/stderr logs, applied at spawn time.
- **How it works:** `config_defaults.py:2850-2854`; read at `hermes_cli/kanban_db.py:10455` and `:10460`. "Defaults preserve the historical 2 MiB + one-backup behavior; long-running workers can raise these to keep more early failure evidence."
- **Inputs / options:** bytes; backup count.
- **Outputs / side effects:** log files under the kanban worker log directory.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** rotation is decided at spawn, so changes apply to newly spawned workers.
- **Rebuild notes:** `RotatingFileHandler`-style sizing per worker process.

### Kanban → Orchestrator Profile  `id: config-b.kanban.orchestrator_profile`
- **Surface:** Config | Kanban | Web dashboard
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Orchestrator Profile`, key `kanban.orchestrator_profile`, description `Kanban → Orchestrator Profile` (string, default `''`); also the Kanban dashboard orchestration form field `orchestrator_profile`.
- **What it does:** Profile assigned to the root/orchestration task after Triage decomposition.
- **How it works:** `config_defaults.py:2855-2860`; read at `hermes_cli/kanban_decompose.py:187` and `plugins/kanban/dashboard/plugin_api.py:2873`, with fallback resolution to the active/default profile at `plugin_api.py:2879-2893`. "This does not control the decomposer prompt, model, or skills; configure that LLM path under `auxiliary.kanban_decomposer`."
- **Inputs / options:** a profile name; empty = the default profile (the one `hermes` launches with no `-p` flag).
- **Outputs / side effects:** assignment of the root card; `resolved_orchestrator_profile` in the API response.
- **Config / env:** `kanban.orchestrator_profile`.
- **Edge cases / guards:** a non-existent profile is rejected with HTTP 400 by the dashboard endpoint and falls back to the active profile in the resolver.
- **Rebuild notes:** explicit-then-resolved profile pointer.

### Kanban → Default Assignee  `id: config-b.kanban.default_assignee`
- **Surface:** Config | Kanban | Web dashboard
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Default Assignee`, key `kanban.default_assignee`, description `Kanban → Default Assignee` (string, default `''`); dashboard form field `default_assignee`.
- **What it does:** Where a child task lands if the orchestrator cannot match an assignee to any installed profile.
- **How it works:** `config_defaults.py:2861-2864`: "A task never ends up with assignee=None." Read at `plugins/kanban/dashboard/plugin_api.py:2874`; the assignment source is recorded as `"kanban.default_assignee"` at `hermes_cli/kanban_db.py:10156`.
- **Inputs / options:** a profile name; empty = the default profile.
- **Outputs / side effects:** assignee field + a provenance tag on the card.
- **Config / env:** `kanban.default_assignee`.
- **Edge cases / guards:** same 400 validation as above from the dashboard.
- **Rebuild notes:** fallback assignee with recorded provenance.

### Kanban → Max In Progress  `id: config-b.kanban.max_in_progress`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Max In Progress`, key `kanban.max_in_progress`, description `Kanban → Max In Progress` (type `string` because the default is `None`, default `null`).
- **What it does:** Global concurrency cap (#33488) — when set to a positive int the HOST never has more than N tasks `running` at once, counted across every active board and across both the ready and review dispatch lanes.
- **How it works:** `config_defaults.py:2865-2877`; read at `gateway/kanban_watchers.py:1368` (`kanban_cfg.get("max_in_progress", None)`), `hermes_cli/kanban.py:2745` (`_coerce_positive_int`), `hermes_cli/kanban_db.py:9719`. Unset (`None`) means "derive from system memory" (OOF-30/OOF-77): the dispatcher caps concurrency at roughly `MemTotal / 512 MiB`, clamped to `[2, 8]` — e.g. 2 workers on a 1 GiB VM. On hosts where total memory cannot be read (macOS/Windows) unset falls back to no cap.
- **Inputs / options:** positive integer, or `null` for the derived default.
- **Outputs / side effects:** tasks stay `ready` until a slot frees.
- **Config / env:** `kanban.max_in_progress`.
- **Edge cases / guards:** "workers are OS processes sharing one machine's memory, so the cap bounds the machine, not each board".
- **Rebuild notes:** memory-derived default with an explicit override.

### Kanban → Max In Progress Per Profile  `id: config-b.kanban.max_in_progress_per_profile`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Max In Progress Per Profile`, key `kanban.max_in_progress_per_profile`, description `Kanban → Max In Progress Per Profile` (type `string`, default `null`).
- **What it does:** Per-profile concurrency cap (#21582) — no single profile may have more than N workers running at once, even if the global cap would allow it.
- **How it works:** `config_defaults.py:2878-2886`; read at `gateway/kanban_watchers.py:1458` and `hermes_cli/kanban.py:2743`. Tasks blocked this way defer to the next dispatcher tick.
- **Inputs / options:** positive integer; `null` = no per-profile cap (backward-compatible).
- **Outputs / side effects:** fairer fan-out across profiles.
- **Config / env:** `kanban.max_in_progress_per_profile`.
- **Edge cases / guards:** useful "for fan-out workflows that would otherwise saturate one profile's local model / API quota / browser pool while leaving other profiles idle".
- **Rebuild notes:** second counter keyed by profile in the claim query.

### Kanban → Auto Decompose / Auto Decompose Per Tick  `id: config-b.kanban.auto_decompose`
- **Surface:** Config | Kanban | Web dashboard
- **Where:** Config page tab **Kanban** (category id `kanban`) → labels `Auto Decompose` (key `kanban.auto_decompose`, boolean, default `true`) and `Auto Decompose Per Tick` (key `kanban.auto_decompose_per_tick`, number, default `3`); dashboard form field `auto_decompose`.
- **What it does:** Auto-runs the decomposer on tasks that land in **Triage** on every dispatcher tick, capped at N tasks per tick.
- **How it works:** `config_defaults.py:2887-2895`; read at `gateway/kanban_watchers.py:74` (`enabled = bool(kcfg.get("auto_decompose", True))`) and `:76` (`per_tick = int(kcfg.get("auto_decompose_per_tick", 3) or 3)`); the dashboard mirrors it at `plugins/kanban/dashboard/plugin_api.py:2875,2898,2963`.
- **Inputs / options:** boolean; integer per-tick cap. When false, decomposition is manual via `hermes kanban decompose <id>` or the dashboard's **Decompose** button.
- **Outputs / side effects:** aux LLM calls (`auxiliary.kanban_decomposer`) and new child cards.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** the per-tick cap exists to prevent "a large bulk-load of triage tasks from spending a burst of aux LLM calls in one tick"; excess tasks defer.
- **Rebuild notes:** rate-limited background decomposition queue.

### Kanban → Dispatch Stale Timeout Seconds  `id: config-b.kanban.dispatch_stale_timeout_seconds`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Dispatch Stale Timeout Seconds`, key `kanban.dispatch_stale_timeout_seconds`, description `Kanban → Dispatch Stale Timeout Seconds` (number, default `14400` = 4 h).
- **What it does:** Running tasks that exceed this many seconds without a heartbeat (`last_heartbeat_at`) are auto-reclaimed to `ready` on the next dispatcher tick; a still-running host-local worker process is terminated before the reclaim.
- **How it works:** `config_defaults.py:2896-2901`; read at `gateway/kanban_watchers.py:1422` (`kanban_cfg.get("dispatch_stale_timeout_seconds", 0)`).
- **Inputs / options:** seconds; `0` disables stale detection entirely.
- **Outputs / side effects:** worker kill + card requeue.
- **Config / env:** `kanban.dispatch_stale_timeout_seconds`.
- **Edge cases / guards:** a legitimately long task without heartbeats will be killed — raise the value for such boards.
- **Rebuild notes:** heartbeat column + reclaim sweep.

### Kanban → Reconcile Orphans  `id: config-b.kanban.reconcile_orphans`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Reconcile Orphans`, key `kanban.reconcile_orphans`, description `Kanban → Reconcile Orphans` (boolean, default `true`).
- **What it does:** Each dispatcher tick requeues `running` cards whose claim bookkeeping is broken (`claim_lock` or `claim_expires` NULL with a dead/gone worker) — zombies invisible to the TTL/crash/stale recovery paths.
- **How it works:** `config_defaults.py:2902-2907`; read at `gateway/kanban_watchers.py:1437` (`bool(kanban_cfg.get("reconcile_orphans", True))`).
- **Inputs / options:** `true` | `false` ("Set false to keep orphans frozen for manual forensics").
- **Outputs / side effects:** cards move back to `ready`.
- **Config / env:** `kanban.reconcile_orphans`.
- **Edge cases / guards:** disabling it leaks running-state cards forever.
- **Rebuild notes:** consistency sweep over claim columns.

### Kanban → Done Sub Retention Days  `id: config-b.kanban.done_sub_retention_days`
- **Surface:** Config | Kanban
- **Where:** Config page tab **Kanban** (category id `kanban`) → label `Done Sub Retention Days`, key `kanban.done_sub_retention_days`, description `Kanban → Done Sub Retention Days` (number, default `30`).
- **What it does:** Notifier GC — purges notify subscriptions for tasks that have been `done` with no new activity for this many days, on boards that never archive.
- **How it works:** `config_defaults.py:2908-2915` + comment at `:2911-2918`; read at `gateway/kanban_watchers.py:326` (`_kanban_cfg.get("done_sub_retention_days", 30)`). Subscriptions survive a task reaching `done` because "completion is reversible — controllers reopen done work for review corrections" and are normally removed on archive.
- **Inputs / options:** days; `0` disables the sweep.
- **Outputs / side effects:** subscription rows deleted.
- **Config / env:** `kanban.done_sub_retention_days`.
- **Edge cases / guards:** without the sweep, stale rows "get scanned on every notifier tick forever".
- **Rebuild notes:** age-based GC of subscription rows.

## J. Category `loops` (4 schema fields)

### Loops → Min Interval Seconds  `id: config-b.loops.min_interval_seconds`
- **Surface:** Config | CLI
- **Where:** Config page tab **Loops** (category id `loops`) → label `Min Interval Seconds`, key `loops.min_interval_seconds`, description `Loops → Min Interval Seconds` (number, default `30`).
- **What it does:** Smallest fixed interval accepted for a `/loop` schedule; tighter cadences are raised to this floor because each tick is a full agent turn.
- **How it works:** `hermes_cli/config_defaults.py:2197-2200`; read at `hermes_cli/loops.py:251` `int(_loops_config().get("min_interval_seconds", DEFAULT_MIN_INTERVAL_SECONDS))`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** a user-supplied interval below the floor is silently raised.
- **Config / env:** `loops.min_interval_seconds`.
- **Edge cases / guards:** protects against a per-second loop billing a turn each time.
- **Rebuild notes:** clamp on schedule creation.

### Loops → Max Ticks  `id: config-b.loops.max_ticks`
- **Surface:** Config | CLI
- **Where:** Config page tab **Loops** (category id `loops`) → label `Max Ticks`, key `loops.max_ticks`, description `Loops → Max Ticks` (number, default `100`).
- **What it does:** Backstop tick budget — the loop auto-pauses after this many wakeups unless the user set `--times`.
- **How it works:** `config_defaults.py:2201-2203`; read at `hermes_cli/loops.py:259` and stored per loop at `:332` (`int(data.get("max_ticks", DEFAULT_MAX_TICKS) or 0)`).
- **Inputs / options:** integer; `0` = unlimited; CLI `--times` overrides.
- **Outputs / side effects:** the loop enters a paused state.
- **Config / env:** `loops.max_ticks`.
- **Edge cases / guards:** the budget is stored on the loop record at creation, so changing the config does not retro-extend running loops.
- **Rebuild notes:** per-loop counter with a configurable default.

### Loops → Self Paced Floor Seconds / Self Paced Ceiling Seconds  `id: config-b.loops.self_paced_bounds`
- **Surface:** Config | CLI
- **Where:** Config page tab **Loops** (category id `loops`) → labels `Self Paced Floor Seconds` (key `loops.self_paced_floor_seconds`, number, default `60`) and `Self Paced Ceiling Seconds` (key `loops.self_paced_ceiling_seconds`, number, default `900`).
- **What it does:** Bounds for the self-paced cadence, where the model itself chooses when to wake next.
- **How it works:** `config_defaults.py:2204-2206`; read at `hermes_cli/loops.py:267` and `:276`.
- **Inputs / options:** seconds each.
- **Outputs / side effects:** a model-requested delay is clamped into `[floor, ceiling]`.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** a ceiling below the floor would invert the clamp — keep floor ≤ ceiling.
- **Rebuild notes:** clamp the model's requested sleep.

## K. Category `lsp` (5 schema fields)

### Lsp → Enabled  `id: config-b.lsp.enabled`
- **Surface:** Config | Tool
- **Where:** Config page tab **Lsp** (category id `lsp`) → label `Enabled`, key `lsp.enabled`, description `Lsp → Enabled` (boolean, default `true`).
- **What it does:** Master toggle for the whole language-server subsystem.
- **How it works:** `hermes_cli/config_defaults.py:3601-3605`; read at `agent/lsp/manager.py:209` `enabled = bool(lsp_cfg.get("enabled", True))` and reported in the status dict at `manager.py:703` / `hermes lsp status` (`agent/lsp/cli.py:98`).
- **Inputs / options:** `true` | `false` — "no servers spawn, no background event loop, no cost".
- **Outputs / side effects:** no LSP child processes; no post-write diagnostics.
- **Config / env:** `lsp.enabled`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** single kill switch checked before the manager starts.

### Lsp → Wait Mode / Wait Timeout  `id: config-b.lsp.wait`
- **Surface:** Config | Tool
- **Where:** Config page tab **Lsp** (category id `lsp`) → labels `Wait Mode` (key `lsp.wait_mode`, string, default `'document'`) and `Wait Timeout` (key `lsp.wait_timeout`, number, default `5.0`).
- **What it does:** Diagnostic-wait mode for the post-write check: `document` waits up to `wait_timeout` seconds for the current file's diagnostics; `full` additionally requests workspace-wide diagnostics (slower).
- **How it works:** `config_defaults.py:3607-3612`; read at `agent/lsp/manager.py:210-211` (`lsp_cfg.get("wait_mode", "document")`, `float(lsp_cfg.get("wait_timeout", DIAGNOSTICS_DOCUMENT_WAIT))`); printed by `hermes lsp status` as `  wait_mode:       <v>` and `  wait_timeout:    <v>s` (`agent/lsp/cli.py:122-123`).
- **Inputs / options:** `document` | `full`; seconds (float).
- **Outputs / side effects:** how long a write tool blocks before returning diagnostics.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** `full` can be very slow on large monorepos.
- **Rebuild notes:** await either the document publish or the workspace pull, with a deadline.

### Lsp → Install Strategy  `id: config-b.lsp.install_strategy`
- **Surface:** Config | Tool
- **Where:** Config page tab **Lsp** (category id `lsp`) → label `Install Strategy`, key `lsp.install_strategy`, description `Lsp → Install Strategy` (string, default `'auto'`).
- **What it does:** How to handle missing language-server binaries.
- **How it works:** `config_defaults.py:3614-3619`; read at `agent/lsp/manager.py:212`; shown by `hermes lsp status` as `  install_strategy:<v>` (`agent/lsp/cli.py:124`). `"auto"` tries to install via npm/go/pip into `<HERMES_HOME>/lsp/bin/` on first use; `"manual"` only uses binaries already on PATH; `"off"` is an alias for `manual`.
- **Inputs / options:** `auto` | `manual` | `off`.
- **Outputs / side effects:** downloads into `~/.hermes/lsp/bin/`.
- **Config / env:** `lsp.install_strategy`.
- **Edge cases / guards:** air-gapped hosts should use `manual`.
- **Rebuild notes:** per-server install recipe table + a strategy gate.

### Lsp → Idle Timeout  `id: config-b.lsp.idle_timeout`
- **Surface:** Config | Tool
- **Where:** Config page tab **Lsp** (category id `lsp`) → label `Idle Timeout`, key `lsp.idle_timeout`, description `Lsp → Idle Timeout` (number, default `600.0`).
- **What it does:** Idle language servers are shut down after this many seconds with no file activity, then respawned on demand.
- **How it works:** `config_defaults.py:3621-3627`; read at `agent/lsp/manager.py:214` `float(lsp_cfg.get("idle_timeout", DEFAULT_IDLE_TIMEOUT))`. Rationale: "Prevents long-running gateway/CLI processes from accumulating stale pyright/gopls/tsserver children (hundreds of MB each, plus pipe FDs) as the agent moves across worktrees."
- **Inputs / options:** seconds; `0` disables idle reaping (servers live for the process lifetime).
- **Outputs / side effects:** child processes exit and later restart (cold-start latency on the next use).
- **Config / env:** `lsp.idle_timeout`.
- **Edge cases / guards:** very low values cause constant respawn churn.
- **Rebuild notes:** per-server last-activity timestamp + reaper.

## L. Category `matrix` (3 schema fields)

### Matrix → Require Mention  `id: config-b.matrix.require_mention`
- **Surface:** Config | Platform:Matrix
- **Where:** Config page tab **Matrix** (category id `matrix`) → label `Require Mention`, key `matrix.require_mention`, description `Matrix → Require Mention` (boolean, default `true`).
- **What it does:** Require an @mention to respond in Matrix rooms.
- **How it works:** `hermes_cli/config_defaults.py:2517-2518`; read at `plugins/platforms/matrix/adapter.py:1404` (`config.extra.get("require_mention")`), reported in adapter status at `:2299`, and bridged at `:5383-5384` to `MATRIX_REQUIRE_MENTION` when that env var is unset.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** which room messages trigger a turn.
- **Config / env:** `matrix.require_mention`; env `MATRIX_REQUIRE_MENTION`.
- **Edge cases / guards:** Matrix also honours `thread_require_mention` (`matrix/adapter.py:1424`) and `auto_thread` (`:5409`) from its platform block even though those are not `matrix.*` DEFAULT_CONFIG keys.
- **Rebuild notes:** same gate shape as Discord/Slack.

### Matrix → Free Response Rooms  `id: config-b.matrix.free_response_rooms`
- **Surface:** Config | Platform:Matrix
- **Where:** Config page tab **Matrix** (category id `matrix`) → label `Free Response Rooms`, key `matrix.free_response_rooms`, description `Matrix → Free Response Rooms` (string, default `''`).
- **What it does:** Comma-separated room IDs where the bot responds without a mention.
- **How it works:** `config_defaults.py:2519`; read at `plugins/platforms/matrix/adapter.py:1265` (`config.extra.get("free_response_rooms")`) and seeded at `:5390`.
- **Inputs / options:** comma-separated room IDs (`!abc:server`).
- **Outputs / side effects:** widens the gate for those rooms.
- **Config / env:** `matrix.free_response_rooms`.
- **Edge cases / guards:** room ID, not alias.
- **Rebuild notes:** CSV set membership.

### Matrix → Allowed Rooms  `id: config-b.matrix.allowed_rooms`
- **Surface:** Config | Platform:Matrix
- **Where:** Config page tab **Matrix** (category id `matrix`) → label `Allowed Rooms`, key `matrix.allowed_rooms`, description `Matrix → Allowed Rooms` (string, default `''`).
- **What it does:** Whitelist — when set the bot ONLY responds in these room IDs.
- **How it works:** `config_defaults.py:2520`; read at `plugins/platforms/matrix/adapter.py:1277`, seeded at `:5395`. LINE reuses the same `extra` key name (`plugins/platforms/line/adapter.py:747`).
- **Inputs / options:** comma-separated room IDs.
- **Outputs / side effects:** hard filter.
- **Config / env:** `matrix.allowed_rooms`.
- **Edge cases / guards:** empty = no whitelist.
- **Rebuild notes:** CSV allowlist.

## M. Category `mattermost` (3 schema fields)

### Mattermost → Require Mention  `id: config-b.mattermost.require_mention`
- **Surface:** Config | Platform:Mattermost
- **Where:** Config page tab **Mattermost** (category id `mattermost`) → label `Require Mention`, key `mattermost.require_mention`, description `Mattermost → Require Mention` (boolean, default `true`).
- **What it does:** Require an @mention to respond in Mattermost channels.
- **How it works:** `hermes_cli/config_defaults.py:2509-2510`; bridged at `plugins/platforms/mattermost/adapter.py:1255-1256` to `MATTERMOST_REQUIRE_MENTION` when unset.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** message gating.
- **Config / env:** `mattermost.require_mention`; env `MATTERMOST_REQUIRE_MENTION`.
- **Edge cases / guards:** DMs unaffected.
- **Rebuild notes:** shared gate implementation.

### Mattermost → Free Response Channels  `id: config-b.mattermost.free_response_channels`
- **Surface:** Config | Platform:Mattermost
- **Where:** Config page tab **Mattermost** (category id `mattermost`) → label `Free Response Channels`, key `mattermost.free_response_channels`, description `Mattermost → Free Response Channels` (string, default `''`).
- **What it does:** Comma-separated channel IDs where the bot responds without a mention.
- **How it works:** `config_defaults.py:2511`; seeded at `plugins/platforms/mattermost/adapter.py:1257`.
- **Inputs / options:** comma-separated channel IDs.
- **Outputs / side effects:** widened gate.
- **Config / env:** `mattermost.free_response_channels`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** CSV set.

### Mattermost → Allowed Channels  `id: config-b.mattermost.allowed_channels`
- **Surface:** Config | Platform:Mattermost
- **Where:** Config page tab **Mattermost** (category id `mattermost`) → label `Allowed Channels`, key `mattermost.allowed_channels`, description `Mattermost → Allowed Channels` (string, default `''`).
- **What it does:** Whitelist of channel IDs.
- **How it works:** `config_defaults.py:2512`; read at `plugins/platforms/mattermost/adapter.py:871` (`self.config.extra.get("allowed_channels")`), seeded at `:1263`.
- **Inputs / options:** comma-separated channel IDs.
- **Outputs / side effects:** hard filter.
- **Config / env:** `mattermost.allowed_channels`.
- **Edge cases / guards:** the fourth Mattermost key `mattermost.channel_prompts` exists in DEFAULT_CONFIG but is an empty dict and therefore absent from the schema (see the hidden-keys section).
- **Rebuild notes:** CSV allowlist.

## N. Category `moa` (10 schema fields)

### Moa → Default Preset / Active Preset  `id: config-b.moa.preset_selection`
- **Surface:** Config | CLI
- **Where:** Config page tab **Moa** (category id `moa`) → labels `Default Preset` (key `moa.default_preset`, string, default `'default'`) and `Active Preset` (key `moa.active_preset`, string, default `''`). CLI: `hermes moa` (`hermes_cli/moa_cmd.py`), slash command `/moa`.
- **What it does:** `default_preset` names the preset used when `/moa` is invoked without a name; `active_preset` pins MoA on for every turn (empty = off).
- **How it works:** `hermes_cli/config_defaults.py:2212-2214`; `agent/moa_loop.py:2449` `resolved_preset = moa_cfg.get("default_preset") or "default"`; `hermes_cli/moa_config.py:393-406` normalises both, `:433` resolves `preset_name = str(name or cfg.get("default_preset") or DEFAULT_MOA_PRESET_NAME).strip()`, `:474` writes `cfg["active_preset"] = clean`. `hermes_cli/moa_cmd.py:82` prints `active = cfg.get("active_preset") or "(off)"`.
- **Inputs / options:** preset names (keys of `moa.presets`).
- **Outputs / side effects:** whether the reference fan-out runs and which slots are used.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** a name that does not exist falls back to the default preset.
- **Rebuild notes:** two pointers into a preset map — "what /moa uses" vs "always on".

### Moa → Save Traces / Trace Dir  `id: config-b.moa.traces`
- **Surface:** Config | Core
- **Where:** Config page tab **Moa** (category id `moa`) → labels `Save Traces` (key `moa.save_traces`, boolean, default `false`) and `Trace Dir` (key `moa.trace_dir`, string, default `''`).
- **What it does:** Writes the FULL MoA turn (each reference's exact input messages + output + usage/cost, and the aggregator's exact input + output) to a JSONL file so runs can be audited.
- **How it works:** `config_defaults.py:2215-2222`; `agent/moa_trace.py:44-56`: config is read lazily per call (only on a cache-MISS MoA turn), `if not moa_cfg.get("save_traces"): return None`, then `override = moa_cfg.get("trace_dir")` — expanded with `os.path.expandvars(os.path.expanduser(...))` — else `get_hermes_home() / "moa-traces"`. The file is `<dir>/<session_id>.jsonl` with the session id sanitised to `[A-Za-z0-9-_.]` (`_sanitize_session_id`, `moa_trace.py:60-65`).
- **Inputs / options:** boolean; directory path (`~` and `${VAR}` expanded).
- **Outputs / side effects:** JSONL files containing full prompts and outputs — potentially sensitive.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** traces contain raw advisor text unless `moa.privacy_filter` redacts them.
- **Rebuild notes:** per-turn JSONL append with a redaction hook.

### Moa → Privacy Filter  `id: config-b.moa.privacy_filter`
- **Surface:** Config | Security
- **Where:** Config page tab **Moa** (category id `moa`) → label `Privacy Filter`, key `moa.privacy_filter`, description `Moa → Privacy Filter` (string, default `''`).
- **What it does:** Privacy redaction filter for advisor (reference) outputs, which can echo PII (emails, formatted phone numbers) and credential shapes into reference blocks, traces and the aggregator prompt.
- **How it works:** `config_defaults.py:2223-2232`; `agent/moa_loop.py:81` `return coerce_privacy_filter(raw.get("privacy_filter"))`, mirrored at `hermes_cli/moa_config.py:422`. Modes verbatim: `''` = off (the default); `"display"` — redact user-visible surfaces only (reference blocks shown in the UI + saved MoA trace records), the aggregator still sees raw advisor text; `"full"` — additionally redact the advisor text injected into the aggregator prompt (issue #59959).
- **Inputs / options:** `''` | `display` | `full`.
- **Outputs / side effects:** redacted UI blocks / trace records / aggregator prompt.
- **Config / env:** `moa.privacy_filter`.
- **Edge cases / guards:** `full` can degrade synthesis quality by hiding details from the aggregator.
- **Rebuild notes:** one redaction function applied at two configurable boundaries.

### Moa → Presets → Default (5 schema fields + the hidden preset fields)  `id: config-b.moa.presets_default`
- **Surface:** Config | Core
- **Where:** Config page tab **Moa** (category id `moa`) → `Reference Models` (key `moa.presets.default.reference_models`, list-of-objects rendered by `NestedValueEditor` with `Item 1`, `Item 2`, … labels; default `[{'provider': 'openai-codex', 'model': 'gpt-5.5'}, {'provider': 'openrouter', 'model': 'deepseek/deepseek-v4-pro'}]`), `Provider` (key `moa.presets.default.aggregator.provider`, string, default `'openrouter'`), `Model` (key `moa.presets.default.aggregator.model`, string, default `'anthropic/claude-opus-4.8'`), `Max Tokens` (key `moa.presets.default.max_tokens`, number, default `4096`), `Enabled` (key `moa.presets.default.enabled`, boolean, default `true`).
- **What it does:** The built-in MoA preset: which advisor models fan out, which model aggregates their answers, the aggregator token budget, and whether the preset is usable. "A preset is an execution mode around the main model, not a provider/model itself: references + aggregator synthesize private guidance before each main-model iteration" (`config_defaults.py:2209-2211`).
- **How it works:** `config_defaults.py:2233-2244`. Normalisation lives in `hermes_cli/moa_config.py`: `_clean_slot` (`:193-222`) requires a non-empty `provider` and `model`, **rejects `provider: moa`** so a preset can never recurse ("the runtime guards in moa_loop.py skip references / raise on aggregators, but that surfaces only mid-turn"), and keeps optional `reasoning_effort` and per-slot `max_tokens`; `include_enabled` adds `enabled` (default true). `_normalize_preset` (`:305-330`) tolerates a JSON string or a single mapping for `reference_models`. `validate_moa_payload` emits messages such as `preset '<label>': must be an object`, `preset '<label>' reference <n>: must be an object with 'provider' and 'model'`, `preset '<label>': needs at least one complete reference model`, `preset '<label>' aggregator: …`. At runtime `agent/moa_loop.py:1274` and `:1951-1952` filter slots by `slot.get("enabled", True)` and `:1996` skips a preset with `enabled: false`; the aggregator slot is read at `:1710-1711`, per-slot `max_tokens` at `:568`, aggregator `max_tokens` at `:1765`.
- **Inputs / options:** (including fields the schema does not expose) per preset — `reference_models` (list of `{provider, model, reasoning_effort?, max_tokens?, enabled?}`), `aggregator` (`{provider, model, reasoning_effort?}`), `max_tokens`, `enabled`, plus the defaults minted by `_default_preset()` (`moa_config.py:289-303`) that DEFAULT_CONFIG does not declare: `reference_temperature` (`None` = temperature omitted from API calls, matching single-model behaviour), `aggregator_temperature` (`None`), `reference_timeout` (`DEFAULT_MOA_REFERENCE_TIMEOUT`), `degraded_reference_policy` (`"loud"`), `reference_max_tokens` (`None`), `fanout` (`"user_turn"`). Any number of additional presets can be added under `moa.presets.<name>`.
- **Outputs / side effects:** parallel advisor calls, an aggregator call, and a private guidance block injected before the main model's turn.
- **Config / env:** `moa.presets.*`; `auxiliary.moa_reference.*` / `auxiliary.moa_aggregator.*` supply credentials/timeouts.
- **Edge cases / guards:** MoA reference/aggregator costs are excluded from the auxiliary accounting roll-up (`agent/aux_accounting.py:43`); a slot naming `provider: moa` is dropped at save time.
- **Rebuild notes:** preset = list of advisor descriptors + one aggregator descriptor + budgets; validate at the write boundary with exactly the same predicate used at runtime.

## O. Category `model_catalog` (3 schema fields)

### Model Catalog → Enabled / Url / Ttl Hours  `id: config-b.model_catalog`
- **Surface:** Config | Provider
- **Where:** Config page tab **Model_catalog** (category id `model_catalog`) → labels `Enabled` (key `model_catalog.enabled`, boolean, default `true`), `Url` (key `model_catalog.url`, string, default `https://hermes-agent.nousresearch.com/docs/api/model-catalog.json`), `Ttl Hours` (key `model_catalog.ttl_hours`, number, default `1`).
- **What it does:** Fetches Nous's curated model list used by `/model` and `hermes model`, with a disk cache.
- **How it works:** `hermes_cli/config_defaults.py:3050-3059`; `hermes_cli/model_catalog.py:108-110` normalises the block (`bool(raw.get("enabled", True))`, `str(raw.get("url") or DEFAULT_CATALOG_URL)`, `float(raw.get("ttl_hours") or DEFAULT_TTL_HOURS)`); `:277` and `:336` early-return when disabled; `:280` computes `ttl_seconds = max(0.0, cfg["ttl_hours"] * 3600.0)`; `:309` spawns a stale-while-revalidate background refresh and `:313` fetches with `_fetch_manifest_with_fallback(cfg["url"], DEFAULT_FETCH_TIMEOUT)`. "Beyond this, the CLI refetches on the next `/model` or `hermes model` invocation; network failures silently fall back to the stale cache." Migration `hermes_cli/config_migrations.py:467-468` rewrites a stored `ttl_hours == 24` to `1`.
- **Inputs / options:** boolean; URL; hours. A fourth key `model_catalog.providers` (per-provider override URLs, read at `model_catalog.py:341` `provider_cfg.get("url")`) is an empty dict by default and therefore absent from the schema — see the hidden-keys section.
- **Outputs / side effects:** HTTP GET of the manifest; a cache file under the Hermes home.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** self-hosters can point `url` at their own curation list using the same schema.
- **Rebuild notes:** TTL cache + SWR refresh + stale fallback on network failure.

## P. Category `monitoring` (11 schema fields)

### Monitoring → Install Id  `id: config-b.monitoring.install_id`
- **Surface:** Config | Core
- **Where:** Config page tab **Monitoring** (category id `monitoring`) → label `Install Id`, key `monitoring.install_id`, description `Monitoring → Install Id` (string, default `''`).
- **What it does:** Stable install identifier attached to exported health signals so an operator can tell instances apart in their collector. Carries no account identity.
- **How it works:** `hermes_cli/config_defaults.py:3137-3142`; `agent/monitoring/policy.py:19-52` `ensure_install_id(config)` — returns the existing non-empty value, otherwise mints `str(uuid.uuid4())`, re-loads the config, sets `monitoring.install_id` and calls `save_config`. "The id must survive gateway restarts (it becomes `service.instance.id` on exported signals)". The write is fail-open: on a read-only home or managed scope the ephemeral id is still returned and a new one is minted next start.
- **Inputs / options:** any string; empty means "mint a fresh UUID on first use". Rotation is documented verbatim: `hermes config set monitoring.install_id ""`.
- **Outputs / side effects:** writes a UUID back into `config.yaml`; `service.instance.id` on OTLP signals.
- **Config / env:** `monitoring.install_id`.
- **Edge cases / guards:** managed scope prevents persistence (ephemeral id each boot).
- **Rebuild notes:** lazily minted, persisted instance id.

### Monitoring → Gateway Health Export (8 keys)  `id: config-b.monitoring.gateway_health_export`
- **Surface:** Config | Gateway/Telegram | API
- **Where:** Config page tab **Monitoring** (category id `monitoring`) → labels `Enabled` (key `monitoring.gateway_health_export.enabled`, boolean, `false`), `Metrics Enabled` (`.metrics_enabled`, boolean, `true`), `Diagnostic Events Enabled` (`.diagnostic_events_enabled`, boolean, `true`), `Warning Error Events Enabled` (`.warning_error_events_enabled`, boolean, `true`), `Export Interval Seconds` (`.export_interval_seconds`, number, `60`), `Logs Export Interval Seconds` (`.logs_export_interval_seconds`, number, `5`), `Name` (`monitoring.gateway_health_export.resource_attributes.service.name`, string, `'hermes-gateway'`), `Name` (`monitoring.gateway_health_export.resource_attributes.deployment.environment.name`, string, `'production'`).
- **What it does:** Exports gateway health metrics, diagnostic events and warning/error logs over OTLP.
- **How it works:** `config_defaults.py:3143-3156`. `agent/monitoring/gateway_health_export.py:181` gates everything on `bool(gh.get("enabled") and otlp.get("enabled") and otlp.get("endpoint"))` — all three must be set. Metric export: `:419` skips when `metrics_enabled` is false, `:425` `interval_ms = max(5, int(gh.get("export_interval_seconds", 60))) * 1000` (5 s hard floor). Log export: `:560` `interval = max(5, int(...get("logs_export_interval_seconds", 5)))`, `:573` requires both `diagnostic_events_enabled` and `warning_error_events_enabled`. Resource attributes are sanitised by `_safe_resource_attributes` (`:55`) and merged by `_runtime_resource_attributes` (`:77-82`), also reused for the general OTLP exporter with `telemetry_scope="gateway_monitoring"` (`agent/monitoring/otlp_exporter.py:118-129`). `hermes gateway monitoring`-style status output prints, verbatim: `Gateway monitoring`, `  Health export:  enabled|disabled (monitoring.gateway_health_export.enabled)`, `    Metrics:            on|off (interval Ns)`, `    Diagnostic events:  on|off`, `    Warning/error logs: on|off (interval Ns)`, `    Content safety:     always on (rendered messages are never exported; not configurable)` (`hermes_cli/main.py:12995-13005`).
- **Inputs / options:** four booleans, two intervals, two resource-attribute strings (`service.name`, `deployment.environment.name` — note the dotted attribute names become nested config keys).
- **Outputs / side effects:** periodic OTLP metric/log pushes to the configured endpoint.
- **Config / env:** the eight dotted keys plus `monitoring.export.otlp.*`.
- **Edge cases / guards:** message content is never exported — that is stated as "not configurable"; intervals below 5 s are clamped up.
- **Rebuild notes:** OTel SDK meter/logger providers created only when the three gates line up; clamp intervals.

### Monitoring → Export → Otlp → Enabled / Endpoint  `id: config-b.monitoring.export_otlp`
- **Surface:** Config | API
- **Where:** Config page tab **Monitoring** (category id `monitoring`) → labels `Enabled` (key `monitoring.export.otlp.enabled`, boolean, default `false`) and `Endpoint` (key `monitoring.export.otlp.endpoint`, string, default `''`).
- **What it does:** The OTLP destination for all monitoring exports.
- **How it works:** `config_defaults.py:3157-3166`; `agent/monitoring/otlp_exporter.py:230` `return bool(otlp.get("enabled") and otlp.get("endpoint"))`; endpoints are derived per signal (`_metric_endpoint`, `_logs_endpoint` — `gateway_health_export.py:422`, `:491`). Headers come from the sibling `headers_env` map, which "maps header names to ENVIRONMENT VARIABLE NAMES (never secret values); values are read from the environment at export time" (`_resolve_headers`, `gateway_health_export.py:222-226`); that key is an empty dict by default and therefore not in the schema.
- **Inputs / options:** boolean; base OTLP URL.
- **Outputs / side effects:** network egress to the collector.
- **Config / env:** the two dotted keys; `monitoring.export.otlp.headers_env` (hidden); the env vars it names.
- **Edge cases / guards:** the CLI prints `  OTLP endpoint:  not configured (monitoring.export.otlp)` when either is missing.
- **Rebuild notes:** one endpoint + header-name→env-var indirection so secrets never live in config.yaml.

## Q. Category `openrouter` (3 schema fields)

### Openrouter → Response Cache / Response Cache Ttl  `id: config-b.openrouter.response_cache`
- **Surface:** Config | Provider
- **Where:** Config page tab **Openrouter** (category id `openrouter`) → labels `Response Cache` (key `openrouter.response_cache`, boolean, default `true`) and `Response Cache Ttl` (key `openrouter.response_cache_ttl`, number, default `300`).
- **What it does:** Asks OpenRouter to cache responses by sending the `X-OpenRouter-Cache` / `X-OpenRouter-Cache-TTL` headers.
- **How it works:** `hermes_cli/config_defaults.py:1077-1079`; `agent/auxiliary_client.py:1250-1281`: env first — `HERMES_OPENROUTER_CACHE` (truthy values) overrides the config flag, then `cache_enabled = or_config.get("response_cache", False)`; when enabled it sets `headers["X-OpenRouter-Cache"] = "true"`. TTL: `HERMES_OPENROUTER_CACHE_TTL` wins if it `isdigit()` and is within `1..86400`, else `ttl = or_config.get("response_cache_ttl", 300)` is used when it is an int/float in `1..86400`, emitted as `X-OpenRouter-Cache-TTL`.
- **Inputs / options:** boolean; TTL seconds in `[1, 86400]` (out-of-range values are silently dropped, no header sent).
- **Outputs / side effects:** two request headers; possible cached (cheaper, faster) responses.
- **Config / env:** the two dotted keys; envs `HERMES_OPENROUTER_CACHE`, `HERMES_OPENROUTER_CACHE_TTL` (both win).
- **Edge cases / guards:** the code default when the key is absent is `False` even though DEFAULT_CONFIG ships `True`.
- **Rebuild notes:** header injection with env override and a range check.

### Openrouter → Min Coding Score  `id: config-b.openrouter.min_coding_score`
- **Surface:** Config | Provider
- **Where:** Config page tab **Openrouter** (category id `openrouter`) → label `Min Coding Score`, key `openrouter.min_coding_score`, description `Openrouter → Min Coding Score` (number, default `0.65`).
- **What it does:** Floor for OpenRouter's Pareto Code router — only models at or above this coding score are eligible.
- **How it works:** `config_defaults.py:1080`; the value is emitted as an OpenRouter plugin entry `{"id": "pareto-router", "min_coding_score": <score>}` on the request body by `plugins/model-providers/openrouter/__init__.py:157`, `agent/chat_completion_helpers.py:3226` and `agent/transports/chat_completions.py:735`; it is read from config at `cli.py:5567` (`_or_cfg.get("min_coding_score")`) and passed into cron runs at `cron/scheduler.py:6446` (`openrouter_min_coding_score=(_cfg.get("openrouter") or {}).get("min_coding_score")`).
- **Inputs / options:** float 0.0–1.0.
- **Outputs / side effects:** narrows/widens the router's model pool.
- **Config / env:** `openrouter.min_coding_score`.
- **Edge cases / guards:** it does NOT propagate to auxiliary calls by design — set `auxiliary.<task>.extra_body.plugins` for those (`config_defaults.py:1127-1128`).
- **Rebuild notes:** provider-routing plugin parameter passed through on the main-agent path only.

## R. Category `proxy` (5 schema fields)

The `proxy` block configures the **iron-proxy** egress broker: sandboxes get `HTTPS_PROXY=http://<host>:<port>` and the proxy swaps in the real upstream credentials at egress time, so the sandbox never holds them. Three sibling keys of the same block — `proxy.enabled`, `proxy.credential_source`, `proxy.enforce_on_docker` — are filed by the live schema under the **security** category (verified against `GET /api/config/schema`) and are therefore documented in the config-a shard, not here; the five below are the ones the schema files under `proxy`.

### Proxy → Tunnel Port  `id: config-b.proxy.tunnel_port`
- **Surface:** Config | Security
- **Where:** Config page tab **Proxy** (category id `proxy`) → label `Tunnel Port`, key `proxy.tunnel_port`, description `Proxy → Tunnel Port` (number, default `9090`).
- **What it does:** Listener port for the proxy tunnel; sandboxes receive `HTTPS_PROXY=http://<host>:<port>`.
- **How it works:** `hermes_cli/config_defaults.py:3838-3841`; `hermes_cli/proxy_cli.py:383-384` `tunnel_port = int(proxy_cfg.get("tunnel_port", ip._DEFAULT_TUNNEL_PORT))` and writes the resolved value back into the config block.
- **Inputs / options:** TCP port number. "9090 is the default; collide-aware setup wizard can reassign."
- **Outputs / side effects:** binds a local listener; sets the sandbox env var.
- **Config / env:** `proxy.tunnel_port`.
- **Edge cases / guards:** a busy port makes the daemon fail to start; the wizard reassigns.
- **Rebuild notes:** configurable bind port echoed back after collision resolution.

### Proxy → Auto Install  `id: config-b.proxy.auto_install`
- **Surface:** Config | Security
- **Where:** Config page tab **Proxy** (category id `proxy`) → label `Auto Install`, key `proxy.auto_install`, description `Proxy → Auto Install` (boolean, default `true`).
- **What it does:** Auto-downloads the pinned `iron-proxy` binary into `~/.hermes/bin/` on first use.
- **How it works:** `config_defaults.py:3842-3845`; `hermes_cli/proxy_cli.py:439` `proxy_cfg.setdefault("auto_install", True)`, then `install_if_missing=bool(proxy_cfg.get("auto_install", True))` at `:504` and `:643`.
- **Inputs / options:** `true` | `false` (false = you must place `iron-proxy` on PATH yourself).
- **Outputs / side effects:** a binary download into the Hermes home.
- **Config / env:** `proxy.auto_install`.
- **Edge cases / guards:** air-gapped hosts should disable it and pre-install.
- **Rebuild notes:** pinned-version fetch guarded by a flag.

### Proxy → Allow Env Fallback  `id: config-b.proxy.allow_env_fallback`
- **Surface:** Config | Security
- **Where:** Config page tab **Proxy** (category id `proxy`) → label `Allow Env Fallback`, key `proxy.allow_env_fallback`, description `Proxy → Allow Env Fallback` (boolean, default `false`).
- **What it does:** When `credential_source` is `bitwarden` but the BWS access token / project id is missing OR the fetch returns no values for mapped providers, the daemon raises by default; setting this true opts back in to the legacy "silently fall back to host env" behaviour.
- **How it works:** `config_defaults.py:3861-3868`; three refuse-start checks at `agent/proxy_sources/iron_proxy.py:2187`, `:2219`, `:2239` — each is `if not (bitwarden_config or {}).get("allow_env_fallback")`.
- **Inputs / options:** `true` | `false` (default false = strict).
- **Outputs / side effects:** either a hard failure or a silent fallback to host env credentials.
- **Config / env:** `proxy.allow_env_fallback`; `proxy.credential_source`; `secrets.bitwarden.*`.
- **Edge cases / guards:** intended for migrations "where the operator wants to switch credential_source to bitwarden but hasn't fully wired BWS yet".
- **Rebuild notes:** fail-closed by default with a documented escape hatch.

### Proxy → Upstream Deny Cidrs  `id: config-b.proxy.upstream_deny_cidrs`
- **Surface:** Config | Security
- **Where:** Config page tab **Proxy** (category id `proxy`) → label `Upstream Deny Cidrs`, key `proxy.upstream_deny_cidrs`, description `Proxy → Upstream Deny Cidrs` (type `string` because the default is `None`, default `null`).
- **What it does:** SSRF deny list applied to outbound traffic.
- **How it works:** `config_defaults.py:3869-3874`; read at `hermes_cli/proxy_cli.py:410` (`deny_cidrs = proxy_cfg.get("upstream_deny_cidrs")`) and passed to the daemon config as `"upstream_deny_cidrs"` (`agent/proxy_sources/iron_proxy.py:1273`).
- **Inputs / options:** `null`/omitted = the safe default (loopback, link-local including the cloud metadata IP `169.254.169.254`, and RFC1918); an explicit `[]` opts out entirely ("only sensible in hermetic tests that need to reach a loopback upstream"); or a YAML list of CIDRs.
- **Outputs / side effects:** blocked upstream connections.
- **Config / env:** `proxy.upstream_deny_cidrs`.
- **Edge cases / guards:** the distinction between `null` (safe defaults) and `[]` (no protection) is the security-critical part.
- **Rebuild notes:** tri-state list with metadata-IP protection by default.

### Proxy → Extra Allowed Hosts  `id: config-b.proxy.extra_allowed_hosts`
- **Surface:** Config | Security
- **Where:** Config page tab **Proxy** (category id `proxy`) → label `Extra Allowed Hosts`, key `proxy.extra_allowed_hosts`, description `Proxy → Extra Allowed Hosts` (list, default `[]`).
- **What it does:** Extra upstream hosts allowed through the proxy beyond the bundled defaults.
- **How it works:** `config_defaults.py:3875-3879`; read at `hermes_cli/proxy_cli.py:386` `extra_hosts = list(proxy_cfg.get("extra_allowed_hosts") or [])`. The bundled defaults "cover OpenRouter, OpenAI, Anthropic, Google, xAI, Mistral, Groq, Together, DeepSeek, Nous". Wildcards (`*.foo.com`) are supported.
- **Inputs / options:** list of hostnames / wildcard patterns.
- **Outputs / side effects:** widens the egress allowlist.
- **Config / env:** `proxy.extra_allowed_hosts`.
- **Edge cases / guards:** a `*` entry defeats the allowlist.
- **Rebuild notes:** host allowlist with glob matching.

## S. Category `secrets` (15 schema fields)

### Secrets → Bitwarden (9 keys)  `id: config-b.secrets.bitwarden`
- **Surface:** Config | Security | CLI
- **Where:** Config page tab **Secrets** (category id `secrets`) → labels `Enabled` (key `secrets.bitwarden.enabled`, boolean, `false`), `Access Token Env` (`.access_token_env`, string, `'BWS_ACCESS_TOKEN'`), `Project Id` (`.project_id`, string, `''`), `Cache Ttl Seconds` (`.cache_ttl_seconds`, number, `300`), `Enabled` (key `secrets.bitwarden.encrypted_cache.enabled`, boolean, `false`), `Max Stale Seconds` (key `secrets.bitwarden.encrypted_cache.max_stale_seconds`, number, `0`), `Override Existing` (`.override_existing`, boolean, `true`), `Auto Install` (`.auto_install`, boolean, `true`), `Server Url` (`.server_url`, string, `''`). CLI: `hermes secrets bitwarden setup` / `status` / `sync` (`hermes_cli/secrets_cli.py`).
- **What it does:** Pulls credentials from Bitwarden Secrets Manager (BSM) into the process environment at startup instead of storing them in `~/.hermes/.env`.
- **How it works:** `hermes_cli/config_defaults.py:3671-3721`. `hermes secrets bitwarden setup` writes the block (`secrets_cli.py:324-330`: `enabled=True`, `project_id`, `server_url`, `setdefault("access_token_env", token_env)`, `setdefault("cache_ttl_seconds", 300)`, `setdefault("override_existing", True)`, `setdefault("auto_install", True)`). `hermes secrets bitwarden status` renders a table whose row labels are verbatim: `Enabled`, `Token env var`, `Token in env`, `Token validation`, `Project ID` (`[dim](unset)[/dim]` when empty), `Server URL` (`[dim]default (US Cloud, https://vault.bitwarden.com)[/dim]` when empty), `Override existing`, `Cache TTL (s)`, `Auto-install`, `bws binary` (`<path> (<version>)` or `[yellow]not installed[/yellow]`) — `secrets_cli.py:352-385`. The fetch path is `agent/secret_sources/bitwarden.py:950-975`: `ttl = float(cfg.get("cache_ttl_seconds", 300))`, `encrypted_enabled = bool(encrypted_cfg.get("enabled", False))`, `encrypted_max_stale = float(encrypted_cfg.get("max_stale_seconds", 0))`, all passed to `fetch_bitwarden_secrets(...)` together with `server_url`.
- **Inputs / options:** the nine fields. `access_token_env` names the env var holding the machine-account token ("This is the one bootstrap secret; it lives in `~/.hermes/.env` (or your shell) and never in config.yaml"). `cache_ttl_seconds: 0` disables normal fresh-cache reuse. `encrypted_cache` writes AES-GCM encrypted cache material under `~/.hermes/cache/` and may be reused for up to `max_stale_seconds` when a later startup cannot reach Bitwarden due to NETWORK/TIMEOUT — "Auth failures do not fall back". `server_url` empty = the bws CLI default (US Cloud); `https://vault.bitwarden.eu` for EU Cloud; any URL for self-hosted — plumbed into the bws subprocess as `BWS_SERVER_URL` and prompted for during `hermes secrets bitwarden setup`.
- **Outputs / side effects:** environment variables populated at startup; a `bws` binary download when `auto_install`; encrypted cache files.
- **Config / env:** the nine dotted keys; env `BWS_ACCESS_TOKEN` (name configurable), `BWS_SERVER_URL` (derived).
- **Edge cases / guards:** `override_existing` defaults true "because the point of using BSM is centralized rotation — if .env had the final say, rotating in Bitwarden wouldn't take effect until you also cleared the matching .env line"; note the status table reads `override_existing` with a **False** code default while DEFAULT_CONFIG ships `True`.
- **Rebuild notes:** bulk secret source with TTL cache, optional encrypted last-good fallback, and a single bootstrap token.

### Secrets → Onepassword (6 keys)  `id: config-b.secrets.onepassword`
- **Surface:** Config | Security | CLI
- **Where:** Config page tab **Secrets** (category id `secrets`) → labels `Enabled` (key `secrets.onepassword.enabled`, boolean, `false`), `Account` (`.account`, string, `''`), `Service Account Token Env` (`.service_account_token_env`, string, `'OP_SERVICE_ACCOUNT_TOKEN'`), `Binary Path` (`.binary_path`, string, `''`), `Cache Ttl Seconds` (`.cache_ttl_seconds`, number, `300`), `Override Existing` (`.override_existing`, boolean, `true`). CLI: `hermes secrets onepassword …` (`hermes_cli/onepassword_secrets_cli.py`).
- **What it does:** Resolves `op://vault/item/field` references into environment variables with a single `op read` per entry at startup.
- **How it works:** `config_defaults.py:3722-3748`. Setup writes the block (`onepassword_secrets_cli.py:146-184`: `binary_path`, `account`, `service_account_token_env`, `enabled=True`, `setdefault("cache_ttl_seconds", 300)`, `setdefault("override_existing", True)`). Status renders rows labelled verbatim `Enabled`, `Account` (`[dim]default[/dim]` when empty), `Token env var`, `Token in env`, `Override existing`, `Cache TTL (s)`, `op binary` (`<path> (<version>)` or `[yellow]not found[/yellow]`), `References` (`onepassword_secrets_cli.py:214-226`). The resolver passes `override_existing=bool(op_cfg.get("override_existing", True))` at `:396`.
- **Inputs / options:** the six fields; `account` is passed as `op read --account <account>` (empty = op's default account); `binary_path` when set is used verbatim ("PATH is not consulted — pin this to avoid trusting whatever `op` appears first on PATH"); `cache_ttl_seconds: 0` disables BOTH cache layers (no values written to disk); `service_account_token_env` names the env var exported to the `op` child as `OP_SERVICE_ACCOUNT_TOKEN` (leave the var unset to use an interactive/desktop op session).
- **Outputs / side effects:** environment variables; `op` subprocess invocations; optional on-disk cache.
- **Config / env:** the six dotted keys + the hidden `secrets.onepassword.env` map (VAR → `op://…` reference) which is an empty dict by default and therefore absent from the schema.
- **Edge cases / guards:** "mapped" sources (explicit VAR→ref bindings) always take precedence over "bulk" sources (project dumps like Bitwarden BSM), and the first source to claim a var wins — later claims are skipped with a warning (`config_defaults.py:3671-3679`). The optional ordering key `secrets.sources` is present only as a commented example in DEFAULT_CONFIG (`# "sources": [],`), so it is neither a default nor a schema field.
- **Rebuild notes:** mapped secret source resolved per-reference, with a pinned binary and a claim-ordering rule against bulk sources.

## T. Category `sessions` (13 schema fields)

The whole block governs automatic maintenance of `~/.hermes/state.db`, which "accumulates every session, message, tool call, and FTS5 index entry forever" — the motivating report is "384MB+ databases with 68K+ messages, which slows down FTS5 inserts, /resume listing, and insights queries" (`hermes_cli/config_defaults.py:3388-3392`). The sweep runs at CLI/gateway/cron startup (`gateway/run.py:7745-7790`, `cli.py:2655-2672`).

### Sessions → Auto Prune / Retention Days  `id: config-b.sessions.auto_prune`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → labels `Auto Prune` (key `sessions.auto_prune`, boolean, default `false`) and `Retention Days` (key `sessions.retention_days`, number, default `90`).
- **What it does:** Prunes ended sessions inactive for `retention_days`, roughly once per `min_interval_hours`, at startup.
- **How it works:** `config_defaults.py:3388-3403`; `gateway/run.py:7755-7758` (`_sess_cfg.get("auto_prune", False)`, `retention_days=int(_sess_cfg.get("retention_days", 90))`) and `cli.py:2663-2666`. "Activity is the latest message timestamp, falling back to creation time for empty sessions. Active sessions are always preserved."
- **Inputs / options:** boolean; days. Matches the default of `hermes sessions prune`.
- **Outputs / side effects:** rows deleted from `state.db`.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** off by default because "session history is valuable for search recall, and silently deleting it could surprise users"; note the parallel checkpoint block uses its own `retention_days` default of 7 (`gateway/run.py:7784`).
- **Rebuild notes:** startup sweep with an interval gate.

### Sessions → Auto Archive / Auto Archive Days  `id: config-b.sessions.auto_archive`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → labels `Auto Archive` (key `sessions.auto_archive`, boolean, default `false`) and `Auto Archive Days` (key `sessions.auto_archive_days`, number, default `3`).
- **What it does:** Auto-archives (soft-hides, never deletes) sessions untouched for N days.
- **How it works:** `config_defaults.py:3404-3412`; `gateway/run.py:7750-7752` and `:32238-32242` (`idle_days=float(_sess_cfg.get("auto_archive_days", 3))`), `cli.py:2657-2659`. "'Touched' is last activity, not creation, so an old-but-recently-used session is spared. Pinned sessions are always exempt."
- **Inputs / options:** boolean; days (float-coerced).
- **Outputs / side effects:** sessions hidden from the default listings.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** archiving is reversible; pruning is not.
- **Rebuild notes:** archived flag + last-activity threshold.

### Sessions → Vacuum After Prune / Min Vacuum Interval Days  `id: config-b.sessions.vacuum`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → labels `Vacuum After Prune` (key `sessions.vacuum_after_prune`, boolean, default `true`) and `Min Vacuum Interval Days` (key `sessions.min_vacuum_interval_days`, number, default `30`).
- **What it does:** Runs SQLite `VACUUM` after a prune that actually deleted rows, at most once every N days.
- **How it works:** `config_defaults.py:3413-3422`; `gateway/run.py:7761-7763`, `cli.py:2668-2669`. Rationale verbatim: "SQLite does not reclaim disk space on DELETE — freed pages are just reused on subsequent INSERTs — so without VACUUM the file stays bloated even after pruning. VACUUM blocks writes for a few seconds per 100MB, so it only runs at startup, and only when prune deleted ≥1 session."
- **Inputs / options:** boolean; days.
- **Outputs / side effects:** the DB file shrinks; writes block during the rewrite.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** "Pruning can still run on its normal cadence while SQLite reuses the freed pages."
- **Rebuild notes:** conditional VACUUM with its own cooldown.

### Sessions → Min Interval Hours  `id: config-b.sessions.min_interval_hours`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → label `Min Interval Hours`, key `sessions.min_interval_hours`, description `Sessions → Min Interval Hours` (number, default `24`).
- **What it does:** Minimum hours between auto-maintenance runs, so the sweep does not repeat on every CLI invocation.
- **How it works:** `config_defaults.py:3423-3426`; read at `gateway/run.py:7753`, `:7759`, `:7785`. "Tracked via `state_meta` in `state.db` itself, so it's shared across all processes."
- **Inputs / options:** hours.
- **Outputs / side effects:** a timestamp row in `state_meta`.
- **Config / env:** `sessions.min_interval_hours`.
- **Edge cases / guards:** shared across processes by design.
- **Rebuild notes:** last-run marker inside the database being maintained.

### Sessions → Write Json Snapshots  `id: config-b.sessions.write_json_snapshots`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → label `Write Json Snapshots`, key `sessions.write_json_snapshots`, description `Sessions → Write Json Snapshots` (boolean, default `false`).
- **What it does:** Legacy per-session JSON snapshot writer — rewrites `~/.hermes/sessions/session_{sid}.json` on every turn boundary with the full message list.
- **How it works:** `config_defaults.py:3427-3435`; `agent/agent_init.py:1715` `agent._session_json_enabled = bool(_sess_cfg.get("write_json_snapshots", False))`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** one JSON file per session rewritten each turn.
- **Config / env:** `sessions.write_json_snapshots`.
- **Edge cases / guards:** off by default — "state.db is canonical and has every field the snapshot stored (plus per-message timestamps and token counts) … the snapshots had no consumer outside their own overwrite guard and accumulated GBs of disk on heavy users. Opt in only if you have an external tool that consumes the JSON files directly."
- **Rebuild notes:** optional mirror writer behind a flag.

### Sessions → Fts Optimize Notice  `id: config-b.sessions.fts_optimize_notice`
- **Surface:** Config | CLI
- **Where:** Config page tab **Sessions** (category id `sessions`) → label `Fts Optimize Notice`, key `sessions.fts_optimize_notice`, description `Sessions → Fts Optimize Notice` (string, default `'advise'`).
- **What it does:** Controls the notice `hermes update` prints when it detects a legacy search-index layout, offering the compact v23 layout (drops duplicate content copies and stops trigram-indexing tool output; "typically reclaims ~60%+ of state.db on heavy users").
- **How it works:** `config_defaults.py:3439-3452`; read at `hermes_cli/update_cmd.py:935` (`"fts_optimize_notice", "advise"`). The upgrade itself is OPT-IN via `hermes sessions optimize-storage` "because the rebuild is disk-heavy and long on large DBs (see that command's disk preflight)".
- **Inputs / options:** `advise` (default — one-line notice with the reclaimable size and the command; nothing is changed automatically), `require` (the notice is shown as a REQUIRED upgrade with firmer copy, and future tooling may gate on it), `off` (suppress the notice entirely).
- **Outputs / side effects:** console text during `hermes update`.
- **Config / env:** `sessions.fts_optimize_notice`.
- **Edge cases / guards:** the comment states the intent to flip the default in a future release — "enforcement is a copy/gating change, not new migration code".
- **Rebuild notes:** three-level nag setting for an opt-in migration.

### Sessions → Cjk Fts  `id: config-b.sessions.cjk_fts`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → label `Cjk Fts`, key `sessions.cjk_fts`, description `Sessions → Cjk Fts` (boolean, default `true`).
- **What it does:** Uses the CJK-bigram search index (`messages_fts_cjk`, `cjk_unicode61` loadable tokenizer) so 1-2 character CJK terms (일본, 项目, …) get index-speed exact matching instead of LIKE full-table scans.
- **How it works:** `config_defaults.py:3453-3460`; the extension is built by `native/fts5_cjk/build.sh` into `~/.hermes/lib/libfts5_cjk.so`. Bridged to the internal carrier env var at `gateway/run.py:2403-2404` (`os.environ["HERMES_CJK_FTS"] = str(sessions_cfg["cjk_fts"])`, mirrored at `:2838`).
- **Inputs / options:** `true` (use the index when the extension is present; the setting is inert when it isn't) | `false` (never load the extension or serve the cjk index).
- **Outputs / side effects:** sets `HERMES_CJK_FTS`; loads a SQLite extension.
- **Config / env:** `sessions.cjk_fts`; env `HERMES_CJK_FTS` (internal carrier).
- **Edge cases / guards:** disable if the extension misbehaves on your platform.
- **Rebuild notes:** optional tokenizer extension with a graceful no-op.

### Sessions → Search Slow Ms  `id: config-b.sessions.search_slow_ms`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → label `Search Slow Ms`, key `sessions.search_slow_ms`, description `Sessions → Search Slow Ms` (number, default `1000`).
- **What it does:** Slow session-search log threshold — searches at or above it log one INFO line with the routing path taken so latency regressions stay attributable per query shape.
- **How it works:** `config_defaults.py:3461-3466`; bridged at `gateway/run.py:2405-2406` (`os.environ["HERMES_SEARCH_SLOW_MS"] = str(sessions_cfg["search_slow_ms"])`, mirrored at `:2840`). The logged routing paths are named verbatim: `fts_cjk`, `fts5`, `trigram`, `like_scan`.
- **Inputs / options:** milliseconds; `0` logs every search.
- **Outputs / side effects:** INFO log lines.
- **Config / env:** `sessions.search_slow_ms`; env `HERMES_SEARCH_SLOW_MS` (internal carrier).
- **Edge cases / guards:** `0` is noisy but useful when profiling.
- **Rebuild notes:** timed query wrapper that logs the chosen index path.

### Sessions → Max Resume Messages / Max Export Messages  `id: config-b.sessions.transcript_limits`
- **Surface:** Config | Core
- **Where:** Config page tab **Sessions** (category id `sessions`) → labels `Max Resume Messages` (key `sessions.max_resume_messages`, number, default `20000`) and `Max Export Messages` (key `sessions.max_export_messages`, number, default `20000`).
- **What it does:** Transcript safety limits: the maximum active messages (across the full compression lineage) a session may hold and still be resumed interactively (CLI/TUI/desktop), and the maximum for an in-memory (non-streaming) export such as `hermes sessions export`.
- **How it works:** `config_defaults.py:3467-3477`; read at `hermes_state.py:138` (`"max_resume_messages", MAX_SAFE_RESUME_MESSAGES`) and `:145` (`"max_export_messages", MAX_SAFE_EXPORT_MESSAGES`). Rationale: "A runaway session (hundreds of thousands of rows) can exhaust memory when its transcript is materialized in one shot."
- **Inputs / options:** integers; `0` disables that guard.
- **Outputs / side effects:** resume/export is refused with a bounded-row error instead of OOMing.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** the export limit is "Checked per session, so full-DB backups of many small sessions still work".
- **Rebuild notes:** row-count preflight before materialising a transcript.

## U. Category `slack` (6 schema fields)

### Slack → Require Mention  `id: config-b.slack.require_mention`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Require Mention`, key `slack.require_mention`, description `Slack → Require Mention` (boolean, default `true`).
- **What it does:** Require an @mention to respond in Slack channels.
- **How it works:** `hermes_cli/config_defaults.py:2385-2386`; read at `plugins/platforms/slack/adapter.py:9058` (`self.config.extra.get("require_mention")`); bridged generically at `gateway/config.py:1718-1719`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** message gating.
- **Config / env:** `slack.require_mention`.
- **Edge cases / guards:** overridden per channel by `free_response_channels` / `require_mention_channels`.
- **Rebuild notes:** shared gate.

### Slack → Free Response Channels  `id: config-b.slack.free_response_channels`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Free Response Channels`, key `slack.free_response_channels`, description `Slack → Free Response Channels` (string, default `''`).
- **What it does:** Comma-separated channel IDs where the bot responds without a mention.
- **How it works:** `config_defaults.py:2387`; read at `plugins/platforms/slack/adapter.py:9164`, seeded at `:9833`, also consulted by the relay at `gateway/relay/__init__.py:409-411`.
- **Inputs / options:** comma-separated channel IDs.
- **Outputs / side effects:** widened gate.
- **Config / env:** `slack.free_response_channels`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** CSV set.

### Slack → Allowed Channels  `id: config-b.slack.allowed_channels`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Allowed Channels`, key `slack.allowed_channels`, description `Slack → Allowed Channels` (string, default `''`).
- **What it does:** Whitelist — the bot responds ONLY in these channel IDs.
- **How it works:** `config_defaults.py:2388`; read at `plugins/platforms/slack/adapter.py:9202`, seeded at `:9856`.
- **Inputs / options:** comma-separated channel IDs.
- **Outputs / side effects:** hard filter.
- **Config / env:** `slack.allowed_channels`.
- **Edge cases / guards:** empty = no whitelist.
- **Rebuild notes:** CSV allowlist.

### Slack → Require Mention Channels  `id: config-b.slack.require_mention_channels`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Require Mention Channels`, key `slack.require_mention_channels`, description `Slack → Require Mention Channels` (string, default `''`).
- **What it does:** Channel IDs where an @mention is ALWAYS required, even when `require_mention` is false globally (per-channel force-mention override).
- **How it works:** `config_defaults.py:2389-2391`; read at `plugins/platforms/slack/adapter.py:9221` (`self.config.extra.get("require_mention_channels")`), seeded at `:9838`.
- **Inputs / options:** comma-separated channel IDs.
- **Outputs / side effects:** narrows the gate for those channels only.
- **Config / env:** `slack.require_mention_channels`.
- **Edge cases / guards:** the inverse of `free_response_channels`; both can be set.
- **Rebuild notes:** per-channel override map instead of two CSV lists.

### Slack → Ignore Other User Mentions  `id: config-b.slack.ignore_other_user_mentions`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Ignore Other User Mentions`, key `slack.ignore_other_user_mentions`, description `Slack → Ignore Other User Mentions` (boolean, default `false`).
- **What it does:** Ignores a channel/thread message addressed to another user (first token @mentions someone other than the bot) unless the bot is also mentioned.
- **How it works:** `config_defaults.py:2392-2395`; read at `plugins/platforms/slack/adapter.py:9098`; bridged at `:9821-9823` to `SLACK_IGNORE_OTHER_USER_MENTIONS` when that env var is unset.
- **Inputs / options:** `true` | `false` (opt-in; "default off keeps existing behaviour").
- **Outputs / side effects:** fewer accidental replies in busy channels.
- **Config / env:** `slack.ignore_other_user_mentions`; env `SLACK_IGNORE_OTHER_USER_MENTIONS`.
- **Edge cases / guards:** only the FIRST token is inspected.
- **Rebuild notes:** leading-mention heuristic.

### Slack → Thread Require Mention  `id: config-b.slack.thread_require_mention`
- **Surface:** Config | Platform:Slack
- **Where:** Config page tab **Slack** (category id `slack`) → label `Thread Require Mention`, key `slack.thread_require_mention`, description `Slack → Thread Require Mention` (boolean, default `false`).
- **What it does:** Requires an @mention in Slack thread replies too.
- **How it works:** `config_defaults.py:2396-2397`; read at `plugins/platforms/slack/adapter.py:9119`; bridged at `:9825-9829`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** thread gating.
- **Config / env:** `slack.thread_require_mention`.
- **Edge cases / guards:** the seventh Slack key `slack.channel_prompts` (per-channel ephemeral system prompts) is an empty dict and therefore not in the schema — see the hidden-keys section.
- **Rebuild notes:** thread-scoped gate.

## V. Category `streaming` (6 schema fields)

The block controls real-time token streaming to messaging platforms. It is read at the top level by the gateway; "absent this block the gateway falls back to these same defaults, so adding it here only makes the feature discoverable in config.yaml — it does not change behavior" (`hermes_cli/config_defaults.py:3349-3356`). The typed carrier is `StreamingConfig` (`gateway/config.py:775-880`), serialised at `:806-814` and built at `:817-880`, wired into `GatewayConfig` at `:1023`, `:1163`, `:1348`, with a top-level `streaming:` YAML block accepted at `:1527`.

### Streaming → Enabled  `id: config-b.streaming.enabled`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Streaming** (category id `streaming`) → label `Enabled`, key `streaming.enabled`, description `Streaming → Enabled` (boolean, default `false`).
- **What it does:** Master switch. When false, each response is delivered as a single final message (no progressive updates).
- **How it works:** `config_defaults.py:3357-3360`; `StreamingConfig.from_dict` (`gateway/config.py:817+`). A restart is required after enabling ("Set `enabled: true` and restart the gateway to turn it on").
- **Inputs / options:** `true` | `false`. The alias `streaming.mode` (see the hidden-keys section) turns streaming ON and selects the transport in one key; an explicit `enabled` always wins.
- **Outputs / side effects:** extra edit/draft API calls per response.
- **Config / env:** `streaming.enabled`.
- **Edge cases / guards:** disabled by default because "streaming costs extra edit/draft API calls per response".
- **Rebuild notes:** master switch separate from transport selection.

### Streaming → Transport  `id: config-b.streaming.transport`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Streaming** (category id `streaming`) → label `Transport`, key `streaming.transport`, description `Streaming → Transport` (string, default `'auto'`).
- **What it does:** Chooses how progressive updates are delivered.
- **How it works:** `config_defaults.py:3361-3372` + `gateway/config.py:129-140` `_normalize_streaming_token` (YAML's bare `off`/`on` parse as booleans, so both are normalised to canonical tokens rather than `"false"`/`"true"`). Options verbatim: `"auto"` — prefer native draft streaming where the platform supports it (Telegram DMs via `sendMessageDraft`, Bot API 9.5+) and fall back to edit-based elsewhere; `"draft"` — explicitly request native drafts, falling back to edit when the platform/chat doesn't support them; `"edit"` — progressive `editMessageText` only (legacy behavior); `"off"` — disable streaming entirely (same as `enabled: false`).
- **Inputs / options:** `auto` | `draft` | `edit` | `off`.
- **Outputs / side effects:** which API method the streamer calls.
- **Config / env:** `streaming.transport`.
- **Edge cases / guards:** "`transport` alone does NOT imply `enabled`" — only the `mode` alias flips the master switch (`gateway/config.py:831-834`). Discord, Slack, Matrix and Telegram groups report `supports_draft_streaming() == False` and transparently use the edit path.
- **Rebuild notes:** capability-probed transport with a documented fallback ladder.

### Streaming → Edit Interval / Buffer Threshold  `id: config-b.streaming.pacing`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Streaming** (category id `streaming`) → labels `Edit Interval` (key `streaming.edit_interval`, number, default `0.8`) and `Buffer Threshold` (key `streaming.buffer_threshold`, number, default `24`).
- **What it does:** Minimum seconds between progressive edits, and the character count that forces an early flush so short replies feel near-instant.
- **How it works:** `config_defaults.py:3373-3378`; `gateway/config.py:856` (`data.get("edit_interval")`, fallback `DEFAULT_STREAMING_EDIT_INTERVAL`) and `:859` (`data.get("buffer_threshold")`, fallback `DEFAULT_STREAMING_BUFFER_THRESHOLD`); serialised at `:810-811`.
- **Inputs / options:** seconds (float); characters (int).
- **Outputs / side effects:** update rate against the platform's flood limits ("tuned for Telegram's ~1 edit/s flood envelope").
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** too-small an interval invites platform rate limits.
- **Rebuild notes:** time-and-size double trigger on the flush loop.

### Streaming → Cursor  `id: config-b.streaming.cursor`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab **Streaming** (category id `streaming`) → label `Cursor`, key `streaming.cursor`, description `Streaming → Cursor` (string, default `' ▉'` — a space plus U+2589 LEFT THREE QUARTERS BLOCK, written in source as `" ▉"`).
- **What it does:** Cursor glyph appended to the in-progress message while streaming.
- **How it works:** `config_defaults.py:3379-3380`; carried on `StreamingConfig` and serialised at `gateway/config.py:812`.
- **Inputs / options:** any string (empty = no cursor).
- **Outputs / side effects:** visible text at the end of each partial update.
- **Config / env:** `streaming.cursor`.
- **Edge cases / guards:** some clients render exotic glyphs poorly.
- **Rebuild notes:** appended suffix stripped on the final edit.

### Streaming → Fresh Final After Seconds  `id: config-b.streaming.fresh_final_after_seconds`
- **Surface:** Config | Platform:Telegram
- **Where:** Config page tab **Streaming** (category id `streaming`) → label `Fresh Final After Seconds`, key `streaming.fresh_final_after_seconds`, description `Streaming → Fresh Final After Seconds` (number, default `0.0`).
- **What it does:** When > 0, the final edit of a long-running streamed response is delivered as a FRESH message if the preview has been visible at least this many seconds, so the platform timestamp reflects completion time.
- **How it works:** `config_defaults.py:3381-3385` and `gateway/config.py:796-804`; read at `gateway/run.py:29644` `float(getattr(scfg, "fresh_final_after_seconds", 0.0) or 0.0)`; parsed at `gateway/config.py:863`.
- **Inputs / options:** seconds; `0` disables the fresh-message replacement path.
- **Outputs / side effects:** an extra message instead of a final edit.
- **Config / env:** `streaming.fresh_final_after_seconds`.
- **Edge cases / guards:** "Telegram only; other platforms ignore it."
- **Rebuild notes:** post-stream repost when the preview is old.

## W. Category `tool_loop_guardrails` (10 schema fields)

### Tool Loop Guardrails → Warnings Enabled / Hard Stop Enabled  `id: config-b.tool_loop_guardrails.switches`
- **Surface:** Config | Core
- **Where:** Config page tab **Tool_loop_guardrails** (category id `tool_loop_guardrails`) → labels `Warnings Enabled` (key `tool_loop_guardrails.warnings_enabled`, boolean, default `true`) and `Hard Stop Enabled` (key `tool_loop_guardrails.hard_stop_enabled`, boolean, default `false`).
- **What it does:** Guardrails that nudge the model when it repeats failed or non-progressing tool calls: soft warnings are always-on by default, hard stops are opt-in "so interactive CLI/TUI sessions keep flowing".
- **How it works:** `hermes_cli/config_defaults.py:795-800`; `agent/tool_guardrails.py:130-171` `ToolCallGuardrailConfig.from_mapping` — `warnings_enabled=_as_bool(data.get("warnings_enabled"), defaults.warnings_enabled)` and the same for `hard_stop_enabled`.
- **Inputs / options:** two booleans.
- **Outputs / side effects:** a warning notice appended after a tool result, or a hard block of further identical calls.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** the per-turn loop caps below fire "regardless of the warn/hard-stop thresholds".
- **Rebuild notes:** two-tier nudging (advice → refusal).

### Tool Loop Guardrails → Warn After (3 keys) / Hard Stop After (3 keys)  `id: config-b.tool_loop_guardrails.thresholds`
- **Surface:** Config | Core
- **Where:** Config page tab **Tool_loop_guardrails** (category id `tool_loop_guardrails`) → labels `Exact Failure`, `Same Tool Failure`, `Idempotent No Progress` under both `warn_after` and `hard_stop_after` — keys `tool_loop_guardrails.warn_after.exact_failure` (number, `2`), `tool_loop_guardrails.warn_after.same_tool_failure` (number, `3`), `tool_loop_guardrails.warn_after.idempotent_no_progress` (number, `2`), `tool_loop_guardrails.hard_stop_after.exact_failure` (number, `5`), `tool_loop_guardrails.hard_stop_after.same_tool_failure` (number, `8`), `tool_loop_guardrails.hard_stop_after.idempotent_no_progress` (number, `5`); descriptions `Tool Loop Guardrails → Warn After → …` / `→ Hard Stop After → …`.
- **What it does:** How many repetitions of each pathology are tolerated before a warning, and before a hard stop. The three pathologies are: the exact same call failing again (`exact_failure`), the same tool failing repeatedly with different arguments (`same_tool_failure`), and an idempotent call repeated with no state change (`idempotent_no_progress`).
- **How it works:** `config_defaults.py:801-812`; `agent/tool_guardrails.py:135-170` reads `warn_after` / `hard_stop_after` as mappings and coerces each with `_positive_int`, accepting **flat alias keys** as a fallback (`data.get("exact_failure_warn_after")`, `"same_tool_failure_warn_after"`, `"no_progress_warn_after"`, `"exact_failure_block_after"`, `"same_tool_failure_halt_after"`, `"no_progress_block_after"`) — those aliases are not in DEFAULT_CONFIG and therefore not in the schema.
- **Inputs / options:** six positive integers.
- **Outputs / side effects:** guardrail notices / blocks in the tool loop.
- **Config / env:** the six dotted keys (+ six hidden flat aliases).
- **Edge cases / guards:** non-positive or non-numeric values fall back to the dataclass defaults.
- **Rebuild notes:** per-pathology counters with two thresholds each.

### Tool Loop Guardrails → Loop Caps → Max Web Searches / Max Subagents  `id: config-b.tool_loop_guardrails.loop_caps`
- **Surface:** Config | Core
- **Where:** Config page tab **Tool_loop_guardrails** (category id `tool_loop_guardrails`) → labels `Max Web Searches` (key `tool_loop_guardrails.loop_caps.max_web_searches`, number, default `50`) and `Max Subagents` (key `tool_loop_guardrails.loop_caps.max_subagents`, number, default `50`).
- **What it does:** Per-turn runaway-loop caps: hard ceilings on how many times a runaway-prone tool may be called within a SINGLE agent loop (turn). Counters reset at the start of every turn, so a legitimate multi-turn session is never starved.
- **How it works:** `config_defaults.py:813-824` (inspired by Claude Code v2.1.212, Week 29, July 2026); `agent/tool_guardrails.py:186-225` — `LoopCapConfig.from_mapping` coerces both with `_non_negative_int`; the counters reset in `reset_for_turn` at the start of every `run_conversation`. "these caps are a hard ceiling on the total count of a tool within the turn and fire regardless of `hard_stop_enabled`."
- **Inputs / options:** integers; `0` disables that cap (unlimited).
- **Outputs / side effects:** further calls of that tool in the turn are refused.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** "A single turn issuing dozens of web searches or spawning dozens of subagents is already pathological, so the defaults are low."
- **Rebuild notes:** per-turn counters distinct from the repetition detector.

## X. Category `tool_output` (3 schema fields)

### Tool Output → Max Bytes / Max Lines / Max Line Length  `id: config-b.tool_output`
- **Surface:** Config | Tool
- **Where:** Config page tab **Tool_output** (category id `tool_output`) → labels `Max Bytes` (key `tool_output.max_bytes`, number, default `50000`), `Max Lines` (key `tool_output.max_lines`, number, default `2000`), `Max Line Length` (key `tool_output.max_line_length`, number, default `2000`).
- **What it does:** Truncation limits applied to tool results before they enter the model's context.
- **How it works:** `hermes_cli/config_defaults.py:789-793`; `tools/tool_output_limits.py:70-90` loads the `tool_output` section once and memoises `{"max_bytes": _coerce_positive_int(section.get("max_bytes"), DEFAULT_MAX_BYTES), "max_lines": …, "max_line_length": …}`; `_reset_tool_output_limits_cache()` (`:92-96`) clears it "for tests or after config hot-reload". Consumers use the shortcuts `get_max_bytes()` (terminal tool), `get_max_lines()` and `get_max_line_length()` (file ops) at `:99-113`.
- **Inputs / options:** three positive integers (non-positive or unparsable values fall back to the module defaults).
- **Outputs / side effects:** truncated tool output with a truncation marker; lower token spend.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** the values are cached per process, so a change needs a restart (or the internal cache reset).
- **Rebuild notes:** one memoised limits struct shared by every tool.

## Y. Category `tools` (6 schema fields)

### Tools → Tool Search (6 keys — tiered tool disclosure)  `id: config-b.tools.tool_search`
- **Surface:** Config | Tool
- **Where:** Config page tab **Tools** (category id `tools`) → labels `Enabled` (key `tools.tool_search.enabled`, type `string`, default `'auto'`), `Threshold Pct` (`.threshold_pct`, number, `5`), `Search Default Limit` (`.search_default_limit`, number, `5`), `Max Search Limit` (`.max_search_limit`, number, `25`), `Listing` (`.listing`, string, `'auto'`), `Listing Max Tokens` (`.listing_max_tokens`, number, `4000`); descriptions `Tools → Tool Search → …`.
- **What it does:** Controls tiered disclosure of tools: instead of putting every MCP/plugin tool schema in the prompt, a `tool_search` bridge tool is exposed and individual tools are discovered on demand.
- **How it works:** `hermes_cli/config_defaults.py:2993-3037` documents the three tiers verbatim — **Tier 0** no MCP/plugin tools: everything stays eager; **Tier 1** catalog listing fits the budget: bridge + skills-style name+description manifest (degrades to names-only); **Tier 2** per-tool listing over budget even names-only (e.g. Cloudflare's ~3,300-tool flat API surface): bare bridge + a one-line-per-server summary (name + tool count) so the model knows which domains are reachable, with individual tools discoverable through `tool_search` only. Parsing is `tools/tool_search.py:120-170`: a bare `true` → `enabled="auto"`, a bare `false` → `enabled="off"`, a non-dict → auto; `enabled` accepts `true/1/yes` → `"on"`, `false/0/no` → `"off"`, `auto/on/off` verbatim, anything else → `"auto"`. `threshold_pct` is clamped to `[0,100]`; `max_search_limit` to `[1,50]`; `search_default_limit` to `[1, max_search_limit]`; `listing` uses the same truthy mapping as `enabled`; `listing_max_tokens` is clamped to `[200,60000]`.
- **Inputs / options:** `enabled` ∈ `auto` | `on` | `off` (today "auto" is an alias of "on"; it stays the default so a future budget-gated mode can land on "auto" without changing behavior for anyone who pinned "on" or "off"); `threshold_pct` — listing budget as a percentage of the active model's context length, effective budget = `min(pct% of context, listing_max_tokens)`; `search_default_limit` — hits returned per query when the model omits `limit`; `max_search_limit` — hard upper bound the model may request via `limit`; `listing` ∈ `auto` (include when the listing fits the budget, falling back to names-only then to the bare tier-2 bridge) | `on` (same rendering, explicit intent to always list) | `off` (always the bare bridge); `listing_max_tokens` — absolute cap on the embedded listing in tokens (chars/4 estimate).
- **Outputs / side effects:** the tools array sent to the model, and the bridge tool's description text.
- **Config / env:** the six dotted keys.
- **Edge cases / guards:** with `enabled: off` "Tools-array assembly is a pass-through"; the listing embeds every deferred tool's name + first sentence of its description (≤60 chars), grouped by MCP server / toolset.
- **Rebuild notes:** budget-aware catalog renderer with three degradation tiers and a search tool that returns schemas on demand.

## Z. Category `vertex` (2 schema fields)

### Vertex → Project Id / Region  `id: config-b.vertex`
- **Surface:** Config | Provider
- **Where:** Config page tab **Vertex** (category id `vertex`) → labels `Project Id` (key `vertex.project_id`, string, default `''`) and `Region` (key `vertex.region`, string, default `'global'`).
- **What it does:** Non-secret routing config for the Google Vertex AI provider (Gemini via the OpenAI-compatible endpoint).
- **How it works:** `hermes_cli/config_defaults.py:3946-3963`. Auth is OAuth2 (short-lived access tokens minted from a service-account JSON or Application Default Credentials) — NOT a static API key; the credential *path* is a secret-adjacent pointer and lives in `.env` (`VERTEX_CREDENTIALS_PATH` / `GOOGLE_APPLICATION_CREDENTIALS`). Both keys are bridged to the `VERTEX_PROJECT_ID` / `VERTEX_REGION` env vars the adapter reads, so an explicit env var still wins. Reads: `agent/vertex_adapter.py:88` `cfg_project = str(_vertex_config().get("project_id") or "").strip()` and `:75` `cfg_region = str(_vertex_config().get("region") or "").strip()`; the setup wizard shows/writes them at `hermes_cli/model_setup_flows.py:2679` and `:2690` (`str(vertex_cfg.get("region") or "global").strip() or "global"`).
- **Inputs / options:** GCP project id (empty → use the project embedded in the service-account JSON, or the ADC-resolved project); region string.
- **Outputs / side effects:** endpoint routing for Vertex calls.
- **Config / env:** the two dotted keys; envs `VERTEX_PROJECT_ID`, `VERTEX_REGION` (win), `VERTEX_CREDENTIALS_PATH`, `GOOGLE_APPLICATION_CREDENTIALS`.
- **Edge cases / guards:** `"global"` is required for the Gemini 3.x preview models — "regional endpoints silently 404 them"; override to a regional value only if your models are pinned to a region.
- **Rebuild notes:** two routing strings + env precedence; keep credentials out of config.yaml.

## AA. Category `wake_word` (14 schema fields)

All reads go through `tools/wake_word.py`, whose `_DEFAULTS` table (`:76-90`) mirrors DEFAULT_CONFIG and whose `_get(cfg, key)` helper (`:200-202`) substitutes the default whenever the configured value is `None`.

### Wake Word → Enabled  `id: config-b.wake_word.enabled`
- **Surface:** Config | CLI | TUI | Desktop app
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Enabled`, key `wake_word.enabled`, description `Wake Word → Enabled` (boolean, default `false`). Also toggled programmatically by the CLI and the TUI gateway, both of which call `save_config_value("wake_word.enabled", enabled)` (`hermes_cli/cli_commands_mixin.py:4158`, `tui_gateway/server.py:16972`).
- **What it does:** Arms the always-listening wake-word detector.
- **How it works:** `hermes_cli/config_defaults.py:1993-1994`; the eligibility check is `tools/wake_word.py:320-327` — `if not cfg.get("enabled"): return False`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** a microphone stream is opened; the config file is rewritten when toggled from the CLI/TUI.
- **Config / env:** `wake_word.enabled`.
- **Edge cases / guards:** a process/machine ownership lock permits only the first claimant to arm.
- **Rebuild notes:** persisted switch that both the UI and the CLI write.

### Wake Word → Surface  `id: config-b.wake_word.surface`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Surface`, key `wake_word.surface`, description `Wake Word → Surface` (string, default `'auto'`).
- **What it does:** Which surface may claim the wake-word listener.
- **How it works:** `config_defaults.py:1995`; `tools/wake_word.py:326-327` `want = str(_get(cfg, "surface")).strip().lower() or "auto"` then `return want == "auto" or want == surface.strip().lower()`. "`auto` makes a surface eligible; the process/machine ownership lock still permits only the first claimant."
- **Inputs / options:** `auto` (first claimant) | `cli` | `tui` | `gui`.
- **Outputs / side effects:** which process owns the mic.
- **Config / env:** `wake_word.surface`.
- **Edge cases / guards:** pinning to a surface that is not running means no listener at all.
- **Rebuild notes:** eligibility predicate + exclusive lock.

### Wake Word → Input Device  `id: config-b.wake_word.input_device`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Input Device`, key `wake_word.input_device`, description `Wake Word → Input Device` (type `string` because the default is `None`, default `null`).
- **What it does:** PortAudio input device index or name; null uses the process default.
- **How it works:** `config_defaults.py:1996`; `tools/wake_word.py:210-217` `_input_device` preserves integer indices, rejects booleans, and strips strings (empty → `None`); echoed by the TUI status payload at `tui_gateway/server.py:17252`.
- **Inputs / options:** integer index, device-name string, or `null`.
- **Outputs / side effects:** which microphone is opened.
- **Config / env:** `wake_word.input_device`.
- **Edge cases / guards:** device indices are not stable across reboots — a name is safer.
- **Rebuild notes:** accept both index and name; validate at arm time.

### Wake Word → Capture  `id: config-b.wake_word.capture`
- **Surface:** Config | Desktop app
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Capture`, key `wake_word.capture`, description `Wake Word → Capture` (string, default `'auto'`).
- **What it does:** Where PCM is captured — locally by the process, or streamed from a client (the desktop app streams the Mac mic via `wake.feed`).
- **How it works:** `config_defaults.py:1997`; `tools/wake_word.py:251-290` `resolve_capture_mode(cfg, prefer_client=…, force_local=…)`: `force_local` wins; `client|remote|external` → `"client"`; `local` → `"local"`; on `auto` a working backend input always wins ("so local desktops keep PortAudio and the configured `input_device` selection"), else `prefer_client` (set by remote desktop: Mac mic, headless backend) selects client, else CLI/TUI stay local. The resolved mode is reported in the status payload (`wake_word.py:977`).
- **Inputs / options:** `auto` | `local` | `client` (the aliases `remote` and `external` also map to client).
- **Outputs / side effects:** whether the backend opens a mic or waits for `wake.feed` frames.
- **Config / env:** `wake_word.capture`.
- **Edge cases / guards:** headless VPS/Cloud is the motivating "no local mic" case.
- **Rebuild notes:** capability-probed capture side with explicit overrides.

### Wake Word → Provider  `id: config-b.wake_word.provider`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Provider`, key `wake_word.provider`, description `Wake Word → Provider` (string, default `'openwakeword'`).
- **What it does:** Selects the detection engine.
- **How it works:** `config_defaults.py:1998`; `tools/wake_word.py:206-207` `_provider` lowercases and defaults to `openwakeword`; reported at `:973`.
- **Inputs / options:** `openwakeword` (free, local) | `sherpa` (free, ANY phrase, no training) | `porcupine` (premium; needs `PORCUPINE_ACCESS_KEY`).
- **Outputs / side effects:** which model files/dependencies are loaded.
- **Config / env:** `wake_word.provider`; env `PORCUPINE_ACCESS_KEY` for porcupine.
- **Edge cases / guards:** each engine keys detection differently — see `phrase` below.
- **Rebuild notes:** engine registry with a common `detect(frame) -> score` interface.

### Wake Word → Phrase  `id: config-b.wake_word.phrase`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Phrase`, key `wake_word.phrase`, description `Wake Word → Phrase` (string, default `'hey hermes'`).
- **What it does:** For the `sherpa` engine this IS the detected phrase (any text works); for other engines it is a cosmetic label — detection is keyed by the model/keyword sub-key.
- **How it works:** `config_defaults.py:1999`; `tools/wake_word.py:245-249` `wake_phrase()` ("Human-facing wake phrase label (purely cosmetic; engine keys detection)"); in the sherpa path the phrase set is built at `:689-700` — this profile's phrase plus, when `profile_routing` is on, every other wake-enabled profile's phrase, with runtime tokenisation of the arbitrary phrases ("the open-vocab core").
- **Inputs / options:** free text.
- **Outputs / side effects:** the label shown in status output; for sherpa, the actual trigger.
- **Config / env:** `wake_word.phrase`.
- **Edge cases / guards:** a profile with no phrase defaults to `hey <profile-name>` (`wake_word.py:367`).
- **Rebuild notes:** one field with engine-dependent meaning — document it loudly.

### Wake Word → Sensitivity / Confirmation Frames  `id: config-b.wake_word.thresholds`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → labels `Sensitivity` (key `wake_word.sensitivity`, number, default `0.6`) and `Confirmation Frames` (key `wake_word.confirmation_frames`, number, default `3`).
- **What it does:** Detection threshold (consistent across engines; higher = stricter, fewer false triggers) and, for openWakeWord only, how many consecutive over-threshold frames are required to fire.
- **How it works:** `config_defaults.py:2000-2001`; `tools/wake_word.py:221-226` clamps sensitivity into `[0.0, 1.0]` (unparsable → the default), `:229-241` clamps confirmation frames into `[1, 10]` ("`1` restores the old single-frame behaviour; higher values reject ambient-speech blips at the cost of a few tens of ms of extra latency").
- **Inputs / options:** float 0.0–1.0; integer 1–10.
- **Outputs / side effects:** false-accept vs false-reject balance; a few tens of ms of latency.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** `confirmation_frames` is ignored by engines other than openWakeWord.
- **Rebuild notes:** threshold + N-of-N consecutive confirmation.

### Wake Word → Start New Session  `id: config-b.wake_word.start_new_session`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Start New Session`, key `wake_word.start_new_session`, description `Wake Word → Start New Session` (boolean, default `true`).
- **What it does:** Start a fresh session on wake instead of continuing the current one.
- **How it works:** `config_defaults.py:2002`; default table `tools/wake_word.py:88`.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** a new session row per wake, or continued context.
- **Config / env:** `wake_word.start_new_session`.
- **Edge cases / guards:** continuing keeps context but can accumulate a long transcript.
- **Rebuild notes:** session-selection policy at wake time.

### Wake Word → Profile Routing  `id: config-b.wake_word.profile_routing`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Profile Routing`, key `wake_word.profile_routing`, description `Wake Word → Profile Routing` (boolean, default `true`).
- **What it does:** sherpa only — also listen for every wake-enabled profile's phrase and route the wake to the matching profile, so ONE listener can wake any profile ("hey hermes" / "hey coder" / …).
- **How it works:** `config_defaults.py:2003`; `tools/wake_word.py:692` `if bool(cfg.get("profile_routing", True))` merges `enrolled_profile_phrases()` into the phrase map. That helper (`:355-375`) reads **each profile's own `config.yaml` directly** with `read_user_config_raw(Path(get_profile_dir(name)) / "config.yaml")` because `load_config()` targets only the active profile's home, and skips profiles whose `wake_word.enabled` is falsy.
- **Inputs / options:** `true` | `false`.
- **Outputs / side effects:** a display-name → profile map used to route the match.
- **Config / env:** `wake_word.profile_routing`; every profile's `wake_word.enabled` / `wake_word.phrase`.
- **Edge cases / guards:** ignored by openWakeWord/porcupine, which are keyed to one model/keyword.
- **Rebuild notes:** open-vocabulary keyword spotting with a phrase→profile routing table.

### Wake Word → Openwakeword → Model / Inference Framework  `id: config-b.wake_word.openwakeword`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → labels `Model` (key `wake_word.openwakeword.model`, string, default `'hey_hermes'`) and `Inference Framework` (key `wake_word.openwakeword.inference_framework`, string, default `''`).
- **What it does:** Which openWakeWord model detects the phrase, and which inference backend runs it.
- **How it works:** `config_defaults.py:2004-2018`; `tools/wake_word.py:544` `model_ref = str(sub.get("model") or _BUNDLED_MODEL_NAME).strip()` and `:141` `framework = str(sub.get("inference_framework") or "").strip().lower()`.
- **Inputs / options:** `model` — `"hey_hermes"` (the bundled, works-out-of-the-box default) OR a built-in openWakeWord name (`"hey_jarvis"`, `"alexa"`, `"hey_mycroft"`, …) OR a path to a custom `.onnx`/`.tflite` model for another phrase (see the wake-word docs for the custom-model training guide). `inference_framework` — `""` (auto: tflite on macOS ARM64, onnx elsewhere) | `"onnx"` | `"tflite"`.
- **Outputs / side effects:** model file loading; detection quality.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** "openWakeWord's onnx backend scores near-zero on macOS ARM64 (dscripka/openWakeWord#336), so auto avoids a listener that arms but never fires. Set explicitly only to override that choice."
- **Rebuild notes:** per-platform backend default with an override.

### Wake Word → Sherpa → Model Dir  `id: config-b.wake_word.sherpa_model_dir`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Model Dir`, key `wake_word.sherpa.model_dir`, description `Wake Word → Sherpa → Model Dir` (string, default `''`).
- **What it does:** Optional path to a sherpa-onnx KWS model directory.
- **How it works:** `config_defaults.py:2019-2023`; `tools/wake_word.py:680` `model_dir = str(sub.get("model_dir") or "").strip()`. Empty = auto-download the small English zipformer model on first use.
- **Inputs / options:** directory path.
- **Outputs / side effects:** a model download on first use when empty.
- **Config / env:** `wake_word.sherpa.model_dir`.
- **Edge cases / guards:** the directory must contain the tokens/encoder/decoder/joiner files sherpa expects.
- **Rebuild notes:** bundled auto-download with a local override.

### Wake Word → Porcupine → Keyword  `id: config-b.wake_word.porcupine_keyword`
- **Surface:** Config
- **Where:** Config page tab **Wake_word** (category id `wake_word`) → label `Keyword`, key `wake_word.porcupine.keyword`, description `Wake Word → Porcupine → Keyword` (string, default `'jarvis'`).
- **What it does:** Which Picovoice Porcupine keyword fires the wake.
- **How it works:** `config_defaults.py:2024-2027`; `tools/wake_word.py:797` `keyword = str(sub.get("keyword") or "jarvis").strip()`.
- **Inputs / options:** a built-in keyword (`"jarvis"`, `"computer"`, `"bumblebee"`, …) or a path to a custom `.ppn` from the Picovoice Console.
- **Outputs / side effects:** keyword model loading.
- **Config / env:** `wake_word.porcupine.keyword`; env `PORCUPINE_ACCESS_KEY` (required for this engine).
- **Edge cases / guards:** custom `.ppn` files are platform-specific.
- **Rebuild notes:** keyword id or file path, validated against the engine's catalogue.

## AB. Category `web` (9 schema fields)

### Web → Backend / Search Backend / Extract Backend  `id: config-b.web.backends`
- **Surface:** Config | Tool | CLI
- **Where:** Config page tab **Web** (category id `web`) → labels `Backend` (key `web.backend`, string, default `''`), `Search Backend` (key `web.search_backend`, string, `''`), `Extract Backend` (key `web.extract_backend`, string, `''`). Also set by the `hermes tools` picker.
- **What it does:** `backend` is the shared fallback for both capabilities; `search_backend` and `extract_backend` are per-capability overrides for `web_search` and `web_extract` (e.g. `"searxng"`, `"native"`).
- **How it works:** `hermes_cli/config_defaults.py:530-533`; resolution in `agent/web_search_registry.py:360` (generic), `:391` (`_read_config_key("web", "search_backend") or _read_config_key("web", "backend")`) and `:401` (the same for extract). The tuple `("backend", "search_backend", "extract_backend")` is scanned by `plugins/web/firecrawl/provider.py:166` and `plugins/web/keyless_mcp.py:664`; the tools also read it directly at `tools/web_tools.py:224` and `:1520` (`(_load_web_config().get("backend") or "").lower().strip()`), and the Nous subscription check inspects it at `hermes_cli/nous_subscription.py:445`.
- **Inputs / options:** a provider id string; empty = auto (keyless ring / keyed backend detection).
- **Outputs / side effects:** which vendor serves each web call.
- **Config / env:** the three dotted keys; per-vendor API-key env vars.
- **Edge cases / guards:** a per-capability override always wins over the shared `backend`.
- **Rebuild notes:** two-level backend resolution (capability → shared → auto).

### Web → Extract Char Limit  `id: config-b.web.extract_char_limit`
- **Surface:** Config | Tool
- **Where:** Config page tab **Web** (category id `web`) → label `Extract Char Limit`, key `web.extract_char_limit`, description `Web → Extract Char Limit` (number, default `15000`).
- **What it does:** Per-page character budget for `web_extract`; larger pages are truncated and the full text is stored in the cache so it can be read later.
- **How it works:** `config_defaults.py:534` (comment verbatim: "per-page char budget for web_extract; larger pages truncate + store full text in cache/web").
- **Inputs / options:** integer characters.
- **Outputs / side effects:** truncated tool output + a `cache/web` full-text record with a `read_file` pointer.
- **Config / env:** `web.extract_char_limit`.
- **Edge cases / guards:** web_extract no longer uses an auxiliary LLM — "pages are truncate-and-stored with a read_file pointer (no summarization)" (`config_defaults.py:1168-1172`).
- **Rebuild notes:** truncate-and-store with a pointer instead of summarising.

### Web → Keyless Fallback / Keyless Rescue  `id: config-b.web.keyless`
- **Surface:** Config | Tool
- **Where:** Config page tab **Web** (category id `web`) → labels `Keyless Fallback` (key `web.keyless_fallback`, boolean, default `true`) and `Keyless Rescue` (key `web.keyless_rescue`, boolean, default `true`).
- **What it does:** `keyless_fallback` — with NO web backend configured or keyed, `web_search`/`web_extract` rotate round-robin across the public free tiers of the ring vendors (exa, parallel, firecrawl, keenable), failing over to the next ring vendor on rate limits; it never pre-empts a configured or keyed backend. `keyless_rescue` — one-shot rescue: when the chosen/keyed backend fails a call, THAT call retries once on the keyless ring, and the next call attempts the chosen backend again (no sticky failover).
- **How it works:** `config_defaults.py:535-549`; the ring lives in `plugins/web/keyless_mcp.py`.
- **Inputs / options:** two booleans.
- **Outputs / side effects:** requests to third-party free endpoints.
- **Config / env:** the two dotted keys.
- **Edge cases / guards:** "Off when `keyless_fallback` is false" — the rescue path depends on the ring being enabled.
- **Rebuild notes:** round-robin free-tier ring + a single-attempt rescue that never becomes sticky.

### Web → Cache Enabled / Cache Ttl Minutes / Cache Exempt Hosts  `id: config-b.web.cache`
- **Surface:** Config | Tool
- **Where:** Config page tab **Web** (category id `web`) → labels `Cache Enabled` (key `web.cache_enabled`, boolean, default `true`), `Cache Ttl Minutes` (key `web.cache_ttl_minutes`, number, default `20`), `Cache Exempt Hosts` (key `web.cache_exempt_hosts`, list, default `[]`).
- **What it does:** TTL result caching for `web_search` + `web_extract`. Repeat searches (same query, same provider) within the TTL are served from an in-process memo; repeat extracts of the same URL are served from the `cache/web` full-text store; concurrent identical searches (parallel subagents) coalesce into one vendor request. Only successful responses are cached. Exempt hosts are always fetched live.
- **How it works:** `config_defaults.py:550-572` (comments verbatim, including the example `cache_exempt_hosts: ["mysite.vercel.app", "*.ngrok-free.app"]`).
- **Inputs / options:** boolean; minutes; list of host patterns — entries match exactly, as `*.wildcard`, or as a domain suffix (`mysite.dev` also covers `preview.mysite.dev`).
- **Outputs / side effects:** fewer vendor requests; possibly stale content.
- **Config / env:** the three dotted keys.
- **Edge cases / guards:** "localhost/private-IP URLs are always exempt automatically"; the exemption exists for "sites you're actively developing but testing over the public internet (staging deploys, tunnel URLs, preview builds)".
- **Rebuild notes:** memo + request coalescing + host-pattern exemption list.

## AC. Category `x_search` (4 schema fields)

### X Search → Model / Reasoning Effort / Timeout Seconds / Retries  `id: config-b.x_search`
- **Surface:** Config | Tool
- **Where:** Config page tab **X_search** (category id `x_search`) → labels `Model` (key `x_search.model`, string, default `'grok-4.5'`), `Reasoning Effort` (key `x_search.reasoning_effort`, type `string`, default `null`), `Timeout Seconds` (key `x_search.timeout_seconds`, number, default `180`), `Retries` (key `x_search.retries`, number, default `2`).
- **What it does:** Tunes the xAI Responses API call behind the X (Twitter) search tool.
- **How it works:** `hermes_cli/config_defaults.py:3646-3669`. The tool registers "when xAI credentials are available (SuperGrok OAuth or `XAI_API_KEY`) AND the x_search toolset is enabled in `hermes tools`". Reads in `tools/x_search_tool.py`: `:84` `return (str(cfg.get("model") or "").strip() or DEFAULT_X_SEARCH_MODEL)`, `:89` `raw_value = cfg.get("reasoning_effort")`, `:105` `cfg.get("timeout_seconds", DEFAULT_X_SEARCH_TIMEOUT_SECONDS)`, `:114` `cfg.get("retries", DEFAULT_X_SEARCH_RETRIES)`; the resolved model is put on the request payload at `:350` and echoed at `:442`.
- **Inputs / options:** any Grok model with x_search tool access (`grok-4.5` recommended); an optional reasoning effort sent to xAI Responses models that support it (`null` preserves the model's default); timeout seconds (minimum 30 — "x_search can take 60-120s for complex queries — the default is generous"); retry count on 5xx / ReadTimeout / ConnectionError, where "Each retry backs off (1.5x attempt seconds, capped at 5s)".
- **Outputs / side effects:** an xAI Responses API call returning X search results.
- **Config / env:** the four dotted keys; env `XAI_API_KEY` or SuperGrok OAuth.
- **Edge cases / guards:** the timeout floor of 30 s is enforced in code, so a smaller configured value is raised.
- **Rebuild notes:** provider-native search tool wrapper with bounded retries and backoff.

## AD. Keys the dashboard schema does NOT expose — "open" container keys

Method (reproducible): `GET /api/config/schema` returns exactly 785 fields; `DEFAULT_CONFIG` flattens to exactly 785 leaves. Diffing them shows the schema contains every leaf except `_config_version`, plus one synthesised field `model_context_length`. So the only DEFAULT_CONFIG keys the Config page cannot render are the ones whose default is an **empty dict** (they have no leaves to walk) — `_build_schema_from_config` recurses into dicts and only emits a field for scalars (`hermes_cli/web_server.py:1526-1560`), and it explicitly skips `_config_version` (`:1535`). All 41 empty-dict keys + `_config_version` are listed below, grouped; they are still editable in the Config page's **YAML** mode (`web/src/pages/ConfigPage.tsx:495-520`, button label `YAML` / `t.common.form`) and via `hermes config set`.

### Open dicts in this shard's categories (11 keys)  `id: config-b.hidden.shard_open_dicts`
- **Surface:** Config
- **Where:** absent from the Config page's form view; present in YAML mode and in `GET /api/config/defaults`.
- **What it does:** Each declares a user-populated map that the schema generator cannot enumerate.
- **What it does (per key):** each declares a user-populated map.
- **How it works:**
  1. `web.provider_tier` (`config_defaults.py:553-563`) — per-provider tier selection for ring vendors that have both a keyless free endpoint and a keyed paid path (exa, parallel, firecrawl, keenable). Values: `free` (always the anonymous free endpoint, even with a key), `paid` (always the keyed path; a missing key is an error and the vendor is also excluded from the keyless ring), unset (auto: keyed when the API key is present, else the ring). Written by the `hermes tools` picker's "Free (keyless)" / "Paid (API key)" rows (`hermes_cli/tools_config.py:4732`, `:5475` `web_cfg.setdefault("provider_tier", {})`, stale-entry cleanup at `:4736`, `:5483`); read at `plugins/web/keyless_mcp.py:97` and `hermes_cli/tools_config.py:4075`.
  2. `model_catalog.providers` (`config_defaults.py:3060-3068`) — optional per-provider override URLs "for third parties that want to self-host their own curation list using the same schema" (`providers: {openrouter: {url: https://example.com/my-curation.json}}`); normalised at `hermes_cli/model_catalog.py:111` and consulted at `:338` (`cfg["providers"].get(provider)`), `:354`, `:361`, `:425`.
  3. `monitoring.export.otlp.headers_env` (`config_defaults.py:3158-3165`) — header name → ENVIRONMENT VARIABLE NAME (never secret values); resolved at export time by `_resolve_headers` (`agent/monitoring/gateway_health_export.py:222-226`, used at `:423`, `:490` and `agent/monitoring/otlp_exporter.py:114`).
  4. `lsp.servers` (`config_defaults.py:3629-3641`) — per-server overrides keyed by registry `server_id` (`pyright`, `typescript`, `gopls`, `rust-analyzer`, …), each accepting `disabled: true` (skip this server even when its extensions match), `command: ["full/path/to/server", "--stdio"]` (pin a custom binary path; bypasses auto-install), `env: {"KEY": "value"}` (extra env vars passed to the spawned process) and `initialization_options: {...}` (merged into the LSP `initializationOptions`). Read at `agent/lsp/manager.py:223` `servers_cfg = lsp_cfg.get("servers") or {}`.
  5. `secrets.onepassword.env` (`config_defaults.py:3726-3729`) — mapping of env-var name → 1Password secret reference (`op://vault/item/field`), each resolved with a single `op read` at startup; `setdefault("env", {})` at `hermes_cli/onepassword_secrets_cli.py:182`, listed as `References` in the status table (`:207`), edited at `:270-273`, `:292`, `:375`, and consumed at `agent/secret_sources/onepassword.py:563`.
  6-9. `discord.channel_prompts`, `slack.channel_prompts`, `telegram.channel_prompts`, `mattermost.channel_prompts` (`config_defaults.py:2427`, `:2400`, `:2500`, `:2513`) — per-channel/per-chat ephemeral system prompts (Discord forum parents apply to child threads; Telegram topics inherit from the parent group). Bridged into `PlatformConfig.extra` with string-keyed normalisation at `gateway/config.py:1755-1760` and read at `gateway/platforms/base.py:2944` `prompts = config_extra.get("channel_prompts") or {}`; `channel_prompts` is one of the open-dict names in the config-set validator (`hermes_cli/config.py:5489`).
  10. `whatsapp` (`config_defaults.py:2490-2497`) — an entirely empty section whose only documented field is a comment: `reply_prefix`, the prefix prepended to every outgoing WhatsApp message; default `None` uses the built-in `⚕ *Hermes Agent*` header, `""` disables the header entirely, and `\n` is supported (`"🤖 *My Bot*\n──────\n"`).
  11. `honcho` (`config_defaults.py:2374-2378`) — Honcho AI-native memory; the section is only needed for hermes-specific overrides because Honcho "reads `~/.honcho/config.json` as single source of truth" for apiKey, workspace, peerName, sessions and enabled. Read at `plugins/memory/honcho/client.py:1101` (`load_config_readonly().get("honcho", {})`) and `:1286`.
- **Inputs / options:** free-form maps as described above.
- **Outputs / side effects:** the same as the features they configure.
- **Config / env:** the eleven dotted keys.
- **Edge cases / guards:** because the form view cannot render them, saving the form does not drop them — the dashboard PUTs the whole config object it loaded, and `save_config` preserves unknown keys.
- **Rebuild notes:** a schema generator must emit an "object" field for empty dicts (with a JSON editor) instead of skipping them.

### Open dicts owned by sibling shards (17 auxiliary `extra_body` maps + 13 others)  `id: config-b.hidden.other_open_dicts`
- **Surface:** Config
- **Where:** absent from the Config page form view; YAML mode / `hermes config set` only.
- **What it does:** each key below is a dict-shaped setting the form view cannot render.
- **How it works — the keys:**
  **Auxiliary (17, in this shard's `auxiliary` category but dict-shaped):** `auxiliary.vision.extra_body`, `auxiliary.compression.extra_body`, `auxiliary.skills_hub.extra_body`, `auxiliary.approval.extra_body`, `auxiliary.mcp.extra_body`, `auxiliary.title_generation.extra_body`, `auxiliary.memory_query_rewrite.extra_body`, `auxiliary.tts_audio_tags.extra_body`, `auxiliary.triage_specifier.extra_body`, `auxiliary.kanban_decomposer.extra_body`, `auxiliary.profile_describer.extra_body`, `auxiliary.goal_judge.extra_body`, `auxiliary.curator.extra_body`, `auxiliary.monitor.extra_body`, `auxiliary.background_review.extra_body`, `auxiliary.moa_reference.extra_body`, `auxiliary.moa_aggregator.extra_body` — each is "forwarded verbatim as request body fields on every aux call for that task", read at `agent/auxiliary_client.py:8733-8734` and merged into the outgoing kwargs at `:9167`. The documented example (`config_defaults.py:1110-1126`) sets OpenRouter provider routing (`provider: {order: [anthropic, google], sort: throughput | price | latency}`) and the Pareto Code router (`plugins: [{id: pareto-router, min_coding_score: 0.5}]`). Note `auxiliary.review` has NO `extra_body` (it is a subagent, not a single call).
  **Others (13, documented here for completeness of the 785-vs-schema diff; their features belong to sibling shards):** `providers` (per-provider credential/settings map), `credential_pool_strategies` (read at `agent/credential_pool.py:550`, written by `hermes_cli/auth_commands.py:868-872` and `hermes_cli/setup.py:49-58`), `agent.reasoning_overrides` (`hermes_constants.py:1507`), `terminal.docker_env` (`tools/terminal_tool.py:1937`, `:1977`, `agent/prompt_builder.py:1239`; env carrier `TERMINAL_DOCKER_ENV` per `hermes_cli/config.py:3814`), `compression.model_thresholds` (`agent/agent_init.py:2262`, `tui_gateway/server.py:6873`, `agent/context_engine.py:485`), `display.status_phrases` (`gateway/status_phrases.py:174-181`, also loadable from `status_phrases.yaml` in the Hermes home), `delegation.request_overrides` (`agent/agent_init.py:484`, `agent/chat_completion_helpers.py:2918-2942`, propagated into MoA/background-review runtimes), `quick_commands` (`gateway/run.py:18877`, `:19322`, `gateway/config.py:1144`/`:1205`/`:1446-1451`, `tui_gateway/methods_tools.py:312`, `cli.py:9933`), `platform_hints` (`agent/agent_init.py:2086`), `hooks` (`agent/shell_hooks.py:282`, `:338`, `agent/outbound_webhooks.py:175`, `:215`), `personalities` (`hermes_cli/personality.py:113`), `model_overrides` (`agent/models_dev.py:895`; the DEFAULT_CONFIG comment at `config_defaults.py:3070-3109` documents the recognised fields `context_window`, `max_output_tokens`, `supports_tools`, `supports_vision`, `supports_reasoning`, `model_family`, the two-tier precedence with `_default` fill-gap blocks, and provider-key aliasing), `onboarding.seen` (`agent/onboarding.py:207`, `:237-240`; "Each hint is shown once per install and then latched here so it never fires again. Users can wipe the section to re-see all hints").
- **Inputs / options:** free-form maps.
- **Outputs / side effects:** per the owning feature.
- **Config / env:** the 30 dotted keys named above.
- **Edge cases / guards:** the config-set validator treats several of these as "open dicts" that accept ANY child path without deep checking (`_OPEN_DICT_TOP_LEVEL_KEYS`, `hermes_cli/config.py:5479-5495`: `providers`, `credential_pool_strategies`, `mcp_servers`, `hooks`, `quick_commands`, `personalities`, `command_allowlist`, `model_catalog`, `channel_prompts`, `server_actions`, `secrets`, `goals`, `loops`).
- **Rebuild notes:** mark dict-shaped settings explicitly in the schema so a UI can offer a key/value editor.

### `_config_version` (the one deliberately hidden scalar)  `id: config-b.hidden.config_version`
- **Surface:** Config | Core
- **Where:** `~/.hermes/config.yaml` only; stripped from `GET /api/config` (`hermes_cli/web_server.py:7276` filters keys starting with `_`) and skipped by the schema builder (`:1535`).
- **What it does:** Records which migration generation the file has been brought up to; current value `39` (`hermes_cli/config_defaults.py:3964`).
- **How it works:** `hermes_cli/config.py:2181` (`_looks_like_config` = a dict containing `_config_version`), `:2196` (latest = the DEFAULT_CONFIG value), `:2212` (current = the file's value), `:2752` and `hermes_cli/setup.py:3872` write the latest after a migration; it is always in the write-preserve set (`config.py:3099`, `:4244` `preserve_keys = {("_config_version",)}`). `hermes_cli/update_cmd.py:171` notes that during an update `DEFAULT_CONFIG["_config_version"]` is the OLD value.
- **Inputs / options:** integer (do not hand-edit).
- **Outputs / side effects:** decides whether `hermes config migrate` has work to do.
- **Config / env:** `_config_version`.
- **Edge cases / guards:** lowering it re-runs migrations; a value above the support floor is required (see `config-b.core.migrations`).
- **Rebuild notes:** single integer generation marker, never exposed to UI.

## AE. Keys code reads that `DEFAULT_CONFIG` does not define at all

These never appear in `GET /api/config/defaults` or `/api/config/schema`, yet the loader accepts them and features depend on them. They are the reason `hermes config set` keeps three extra allowlists (`hermes_cli/config.py:5479-5528`).

### Top-level sections absent from DEFAULT_CONFIG  `id: config-b.hidden.absent_top_level`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` (hand-written or written by wizards); accepted by `hermes config set` because of the validator allowlists.
- **What it does:** top-level sections that code reads although DEFAULT_CONFIG never declares them.
- **How it works — the keys:**
  - `mcp_servers` — the MCP server map (`cli.py:5492`, `:14447`, `:18296`); listed in `_OPEN_DICT_TOP_LEVEL_KEYS` so `hermes config set mcp_servers.my-server.command …` validates.
  - `platforms` / `gateway.platforms` — per-platform blocks keyed by a user-supplied platform name; resolved both at the top level and under `gateway` (`gateway/config.py:1175`, `:1593`, `gateway/runtime_footer.py:87`). `_PLATFORM_CONTAINER_KEYS = frozenset({"platforms"})` (`config.py:5528`) accepts anything below the platform-name segment "because `PlatformConfig` carries an open `extra` mapping".
  - `custom_providers` — list-shaped, indexed by position (`_DYNAMIC_TOP_LEVEL_KEYS`, `config.py:5516-5518`); read at `gateway/slash_commands.py:1829`, `gateway/run.py:3292`, `:20029`.
  - `fallback_model` — read at `hermes_cli/config.py:2355` and normalised at `:4266`.
  - `plugins.*` — "enable/disable lists plus index_url override … Absent from DEFAULT_CONFIG (written only when used), so listed here for `hermes config set plugins.index_url ...` validation" (`config.py:5507-5512`); `plugins.disabled` is read at `hermes_cli/plugins.py:643` and `:4609`, `plugins.enabled` at `:671`.
  - `gateway.multiplex_profiles` — the multiplex profile list (`gateway/config.py:1222`, `:1283`, `hermes_cli/gateway_enroll.py:334`), distinct from the schema-exposed `gateway.multiplex_profile_allowlist`.
  - `secrets.sources` — explicit ordering of enabled secret sources; present only as a commented example in DEFAULT_CONFIG (`config_defaults.py:3679`, `# "sources": [],`).
  - `kanban.auto_promote_children` — read and written by the Kanban dashboard orchestration endpoint (`plugins/kanban/dashboard/plugin_api.py:2876`, `:2898`, `:2966`) with a code default of `True`.
  - The platform-block keys bridged by `gateway/config.py:1702-1760` that have no DEFAULT_CONFIG counterpart: `unauthorized_dm_behavior`, `notice_delivery`, `reply_prefix`, `reply_in_thread`, `cron_continuable_surface`, `send_read_receipts`, `group_allowed_chats` (Telegram), `allowed_topics` (Telegram), `mention_patterns`, `exclusive_bot_mentions`, `observe_unmentioned_group_messages` (Telegram), `dm_policy`, `allow_from`, `allow_admin_from`, `user_allowed_commands`, `group_policy`.
- **Inputs / options:** per feature.
- **Outputs / side effects:** per feature.
- **Config / env:** as listed.
- **Edge cases / guards:** `_known_top_level_keys()` (`config.py:5530-5543`) is the union of `DEFAULT_CONFIG.keys()` + `_OPEN_DICT_TOP_LEVEL_KEYS` + `_DYNAMIC_TOP_LEVEL_KEYS` + `_SCHEMA_DEFINED_DICT_KEYS`; anything outside it gets the "did you mean" suggestion from `_suggest_closest_key` (difflib, cutoff 0.6).
- **Rebuild notes:** keep one authoritative key registry; a key that code reads but the schema never declares is a documentation bug waiting to happen.

### Sub-keys of this shard's sections that DEFAULT_CONFIG does not declare  `id: config-b.hidden.absent_subkeys`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml`, under sections this shard documents.
- **What it does:** sub-keys of this shard's sections that code reads although DEFAULT_CONFIG never declares them.
- **How it works — the keys:**
  - **Auxiliary, per task:** `auxiliary.<task>.fallback_chain` — a list of `{provider, model, base_url?, api_key?}` entries tried in order after the primary backend fails; read at `agent/auxiliary_client.py:5247` and `:5925-5990`, and separately by compression at `agent/conversation_compression.py:1250`. Skipping semantics are owned by `agent/backend_identity.py`: a failure with a `failed_model` is model-scoped (only that exact deployment is skipped), a failure without one is provider-wide (the whole credential surface is skipped); each candidate is also checked against `_task_minimum_context_length(task)`. `auxiliary.<task>.max_concurrency` — a positive int capping in-flight calls for that task via a per-task semaphore (`auxiliary_client.py:8776-8790`); ignored for `vision`, where the key already means the encode/resize CPU worker pool. `auxiliary.<task>.key_env` (alias `api_key_env`) — name of an env var to read the API key from when `api_key` is empty (`auxiliary_client.py:8360-8367`, resolved through `_scoped_key_env`). `auxiliary.<task>.api_mode` — declared in DEFAULT_CONFIG only for `review`, but read for EVERY task at `auxiliary_client.py:8368`.
  - **MoA preset fields** minted by `_default_preset()` but absent from DEFAULT_CONFIG (`hermes_cli/moa_config.py:289-303`): `moa.presets.<name>.reference_temperature`, `.aggregator_temperature`, `.reference_timeout`, `.degraded_reference_policy`, `.reference_max_tokens`, `.fanout`; plus per-slot `reference_models[].reasoning_effort`, `reference_models[].max_tokens`, `reference_models[].enabled` and `aggregator.reasoning_effort`.
  - **Tool-loop guardrail flat aliases** accepted as fallbacks by `agent/tool_guardrails.py:146-170`: `tool_loop_guardrails.exact_failure_warn_after`, `.same_tool_failure_warn_after`, `.no_progress_warn_after`, `.exact_failure_block_after`, `.same_tool_failure_halt_after`, `.no_progress_block_after`.
  - **Streaming alias:** `streaming.mode` — "an ergonomic alias for the transport that ALSO implies `enabled`"; `mode: off` disables streaming, and an explicit `enabled` key always wins (`gateway/config.py:821-834`). Without it, `mode` "was silently ignored and streaming stayed disabled … which is a surprising footgun: the whole reply buffers and sends at once."
  - **Sessions/checkpoints extras:** `sessions` and `checkpoints` are in `_SCHEMA_DEFINED_DICT_KEYS` (`config.py:5506`), so extra sub-keys validate; the checkpoint sweep reads its own `auto_prune`, `retention_days` (default 7) and `min_interval_hours` from `checkpoints.*` (`gateway/run.py:7775-7785`).
  - **Discord/Matrix extras:** `matrix.thread_require_mention` (`plugins/platforms/matrix/adapter.py:1424`) and `matrix.auto_thread` (`:5409-5410`) are read from the Matrix platform block although DEFAULT_CONFIG declares only three `matrix.*` keys.
- **Inputs / options:** as described per key.
- **Outputs / side effects:** per feature.
- **Config / env:** as listed.
- **Edge cases / guards:** these keys are invisible in the dashboard, so a user who sets one sees no confirmation there; `hermes config get <key>` is the way to verify.
- **Rebuild notes:** either declare every readable key in the defaults table or generate the reader from the table — the drift documented here is exactly what a generated schema prevents.

## AF. Key index — every schema field of this shard, mapped to the entry that documents it

All 357 fields the live `GET /api/config/schema` files under this shard's categories, one line each, so a mechanical checker can confirm none was summarised away. Format: `<dotted key>` = `<live default>` → the entry id that documents it.


**discord** (37 fields)

- `discord.require_mention` = `True` → `config-b.discord.require_mention`
- `discord.free_response_channels` = `''` → `config-b.discord.free_response_channels`
- `discord.allowed_channels` = `''` → `config-b.discord.allowed_channels`
- `discord.auto_thread` = `True` → `config-b.discord.auto_thread`
- `discord.thread_require_mention` = `False` → `config-b.discord.thread_require_mention`
- `discord.bots_require_inline_mention` = `False` → `config-b.discord.bots_require_inline_mention`
- `discord.history_backfill` = `True` → `config-b.discord.history_backfill`
- `discord.history_backfill_limit` = `50` → `config-b.discord.history_backfill`
- `discord.missed_message_backfill.enabled` = `False` → `config-b.discord.missed_message_backfill`
- `discord.missed_message_backfill.channels` = `''` → `config-b.discord.missed_message_backfill`
- `discord.missed_message_backfill.window_seconds` = `21600` → `config-b.discord.missed_message_backfill`
- `discord.missed_message_backfill.limit` = `100` → `config-b.discord.missed_message_backfill`
- `discord.missed_message_backfill.max_dispatches` = `10` → `config-b.discord.missed_message_backfill`
- `discord.reactions` = `True` → `config-b.discord.reactions`
- `discord.websocket_liveness_interval_seconds` = `15` → `config-b.discord.websocket_liveness`
- `discord.websocket_liveness_failure_threshold` = `2` → `config-b.discord.websocket_liveness`
- `discord.websocket_heartbeat_ack_max_age_seconds` = `60` → `config-b.discord.websocket_liveness`
- `discord.websocket_max_latency_seconds` = `30` → `config-b.discord.websocket_liveness`
- `discord.dm_role_auth_guild` = `''` → `config-b.discord.dm_role_auth_guild`
- `discord.server_actions` = `''` → `config-b.discord.server_actions`
- `discord.allow_any_attachment` = `False` → `config-b.discord.allow_any_attachment`
- `discord.max_attachment_bytes` = `33554432` → `config-b.discord.max_attachment_bytes`
- `discord.approval_mentions` = `False` → `config-b.discord.approval_mentions`
- `discord.voice_channel_inactivity_timeout_seconds` = `300` → `config-b.discord.voice_timeouts`
- `discord.voice_playback_timeout_seconds` = `120` → `config-b.discord.voice_timeouts`
- `discord.voice_fx.enabled` = `False` → `config-b.discord.voice_fx`
- `discord.voice_fx.ambient_enabled` = `True` → `config-b.discord.voice_fx`
- `discord.voice_fx.ambient_path` = `''` → `config-b.discord.voice_fx`
- `discord.voice_fx.ambient_gain` = `0.18` → `config-b.discord.voice_fx`
- `discord.voice_fx.duck_gain` = `0.06` → `config-b.discord.voice_fx`
- `discord.voice_fx.speech_gain` = `1.0` → `config-b.discord.voice_fx`
- `discord.voice_fx.ack_enabled` = `True` → `config-b.discord.voice_fx`
- `discord.voice_fx.ack_phrases` = `['Let me look into that.', 'One moment.', 'Checking on that now.', 'Give me a sec.', 'On it.']` → `config-b.discord.voice_fx`
- `telegram.reactions` = `False` → `config-b.telegram.reactions`
- `telegram.allowed_chats` = `''` → `config-b.telegram.allowed_chats`
- `telegram.extra.rich_messages` = `False` → `config-b.telegram.extra_rich`
- `telegram.extra.rich_drafts` = `False` → `config-b.telegram.extra_rich`

**auxiliary** (115 fields)

- `auxiliary.transient_retries` = `2` → `config-b.auxiliary.transient_retries`
- `auxiliary.free_only` = `False` → `config-b.auxiliary.free_only`
- `auxiliary.openrouter_model` = `''` → `config-b.auxiliary.openrouter_model`
- `auxiliary.stream_only_base_urls` = `[]` → `config-b.auxiliary.stream_only_base_urls`
- `auxiliary.vision.provider` = `'auto'` → `config-b.auxiliary.vision`
- `auxiliary.vision.model` = `''` → `config-b.auxiliary.vision`
- `auxiliary.vision.base_url` = `''` → `config-b.auxiliary.vision`
- `auxiliary.vision.api_key` = `''` → `config-b.auxiliary.vision`
- `auxiliary.vision.timeout` = `120` → `config-b.auxiliary.vision`
- `auxiliary.vision.reasoning_effort` = `''` → `config-b.auxiliary.vision`
- `auxiliary.vision.download_timeout` = `30` → `config-b.auxiliary.vision`
- `auxiliary.compression.provider` = `'auto'` → `config-b.auxiliary.compression`
- `auxiliary.compression.model` = `''` → `config-b.auxiliary.compression`
- `auxiliary.compression.base_url` = `''` → `config-b.auxiliary.compression`
- `auxiliary.compression.api_key` = `''` → `config-b.auxiliary.compression`
- `auxiliary.compression.timeout` = `120` → `config-b.auxiliary.compression`
- `auxiliary.compression.reasoning_effort` = `''` → `config-b.auxiliary.compression`
- `auxiliary.compression.max_output_tokens` = `0` → `config-b.auxiliary.compression`
- `auxiliary.skills_hub.provider` = `'auto'` → `config-b.auxiliary.skills_hub`
- `auxiliary.skills_hub.model` = `''` → `config-b.auxiliary.skills_hub`
- `auxiliary.skills_hub.base_url` = `''` → `config-b.auxiliary.skills_hub`
- `auxiliary.skills_hub.api_key` = `''` → `config-b.auxiliary.skills_hub`
- `auxiliary.skills_hub.timeout` = `30` → `config-b.auxiliary.skills_hub`
- `auxiliary.skills_hub.reasoning_effort` = `''` → `config-b.auxiliary.skills_hub`
- `auxiliary.approval.provider` = `'auto'` → `config-b.auxiliary.approval`
- `auxiliary.approval.model` = `''` → `config-b.auxiliary.approval`
- `auxiliary.approval.base_url` = `''` → `config-b.auxiliary.approval`
- `auxiliary.approval.api_key` = `''` → `config-b.auxiliary.approval`
- `auxiliary.approval.timeout` = `30` → `config-b.auxiliary.approval`
- `auxiliary.approval.reasoning_effort` = `''` → `config-b.auxiliary.approval`
- `auxiliary.review.provider` = `'auto'` → `config-b.auxiliary.review`
- `auxiliary.review.model` = `''` → `config-b.auxiliary.review`
- `auxiliary.review.base_url` = `''` → `config-b.auxiliary.review`
- `auxiliary.review.api_key` = `''` → `config-b.auxiliary.review`
- `auxiliary.review.api_mode` = `''` → `config-b.auxiliary.review`
- `auxiliary.mcp.provider` = `'auto'` → `config-b.auxiliary.mcp`
- `auxiliary.mcp.model` = `''` → `config-b.auxiliary.mcp`
- `auxiliary.mcp.base_url` = `''` → `config-b.auxiliary.mcp`
- `auxiliary.mcp.api_key` = `''` → `config-b.auxiliary.mcp`
- `auxiliary.mcp.timeout` = `30` → `config-b.auxiliary.mcp`
- `auxiliary.mcp.reasoning_effort` = `''` → `config-b.auxiliary.mcp`
- `auxiliary.title_generation.enabled` = `True` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.provider` = `'auto'` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.model` = `''` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.prefer_fast_model` = `False` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.base_url` = `''` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.api_key` = `''` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.timeout` = `30` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.reasoning_effort` = `''` → `config-b.auxiliary.title_generation`
- `auxiliary.title_generation.language` = `''` → `config-b.auxiliary.title_generation`
- `auxiliary.memory_query_rewrite.provider` = `'auto'` → `config-b.auxiliary.memory_query_rewrite`
- `auxiliary.memory_query_rewrite.model` = `''` → `config-b.auxiliary.memory_query_rewrite`
- `auxiliary.memory_query_rewrite.base_url` = `''` → `config-b.auxiliary.memory_query_rewrite`
- `auxiliary.memory_query_rewrite.api_key` = `''` → `config-b.auxiliary.memory_query_rewrite`
- `auxiliary.memory_query_rewrite.timeout` = `8` → `config-b.auxiliary.memory_query_rewrite`
- `auxiliary.tts_audio_tags.provider` = `'auto'` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.tts_audio_tags.model` = `''` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.tts_audio_tags.base_url` = `''` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.tts_audio_tags.api_key` = `''` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.tts_audio_tags.timeout` = `30` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.tts_audio_tags.reasoning_effort` = `''` → `config-b.auxiliary.tts_audio_tags`
- `auxiliary.triage_specifier.provider` = `'auto'` → `config-b.auxiliary.triage_specifier`
- `auxiliary.triage_specifier.model` = `''` → `config-b.auxiliary.triage_specifier`
- `auxiliary.triage_specifier.base_url` = `''` → `config-b.auxiliary.triage_specifier`
- `auxiliary.triage_specifier.api_key` = `''` → `config-b.auxiliary.triage_specifier`
- `auxiliary.triage_specifier.timeout` = `120` → `config-b.auxiliary.triage_specifier`
- `auxiliary.triage_specifier.reasoning_effort` = `''` → `config-b.auxiliary.triage_specifier`
- `auxiliary.kanban_decomposer.provider` = `'auto'` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.kanban_decomposer.model` = `''` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.kanban_decomposer.base_url` = `''` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.kanban_decomposer.api_key` = `''` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.kanban_decomposer.timeout` = `180` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.kanban_decomposer.reasoning_effort` = `''` → `config-b.auxiliary.kanban_decomposer`
- `auxiliary.profile_describer.provider` = `'auto'` → `config-b.auxiliary.profile_describer`
- `auxiliary.profile_describer.model` = `''` → `config-b.auxiliary.profile_describer`
- `auxiliary.profile_describer.base_url` = `''` → `config-b.auxiliary.profile_describer`
- `auxiliary.profile_describer.api_key` = `''` → `config-b.auxiliary.profile_describer`
- `auxiliary.profile_describer.timeout` = `60` → `config-b.auxiliary.profile_describer`
- `auxiliary.profile_describer.reasoning_effort` = `''` → `config-b.auxiliary.profile_describer`
- `auxiliary.goal_judge.provider` = `'auto'` → `config-b.auxiliary.goal_judge`
- `auxiliary.goal_judge.model` = `''` → `config-b.auxiliary.goal_judge`
- `auxiliary.goal_judge.base_url` = `''` → `config-b.auxiliary.goal_judge`
- `auxiliary.goal_judge.api_key` = `''` → `config-b.auxiliary.goal_judge`
- `auxiliary.goal_judge.timeout` = `60` → `config-b.auxiliary.goal_judge`
- `auxiliary.goal_judge.reasoning_effort` = `''` → `config-b.auxiliary.goal_judge`
- `auxiliary.curator.provider` = `'auto'` → `config-b.auxiliary.curator`
- `auxiliary.curator.model` = `''` → `config-b.auxiliary.curator`
- `auxiliary.curator.base_url` = `''` → `config-b.auxiliary.curator`
- `auxiliary.curator.api_key` = `''` → `config-b.auxiliary.curator`
- `auxiliary.curator.timeout` = `600` → `config-b.auxiliary.curator`
- `auxiliary.curator.reasoning_effort` = `''` → `config-b.auxiliary.curator`
- `auxiliary.monitor.provider` = `'auto'` → `config-b.auxiliary.monitor`
- `auxiliary.monitor.model` = `''` → `config-b.auxiliary.monitor`
- `auxiliary.monitor.base_url` = `''` → `config-b.auxiliary.monitor`
- `auxiliary.monitor.api_key` = `''` → `config-b.auxiliary.monitor`
- `auxiliary.monitor.timeout` = `60` → `config-b.auxiliary.monitor`
- `auxiliary.monitor.reasoning_effort` = `''` → `config-b.auxiliary.monitor`
- `auxiliary.background_review.enabled` = `True` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.provider` = `'auto'` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.model` = `''` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.base_url` = `''` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.api_key` = `''` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.timeout` = `120` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.reasoning_effort` = `''` → `config-b.auxiliary.background_review`
- `auxiliary.background_review.max_input_tokens` = `600000` → `config-b.auxiliary.background_review`
- `auxiliary.moa_reference.provider` = `'auto'` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_reference.model` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_reference.base_url` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_reference.api_key` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_reference.timeout` = `900` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_aggregator.provider` = `'auto'` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_aggregator.model` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_aggregator.base_url` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_aggregator.api_key` = `''` → `config-b.auxiliary.moa_tasks`
- `auxiliary.moa_aggregator.timeout` = `900` → `config-b.auxiliary.moa_tasks`

**bedrock** (8 fields)

- `bedrock.region` = `''` → `config-b.bedrock.region`
- `bedrock.discovery.enabled` = `True` → `config-b.bedrock.discovery`
- `bedrock.discovery.provider_filter` = `[]` → `config-b.bedrock.discovery`
- `bedrock.discovery.refresh_interval` = `3600` → `config-b.bedrock.discovery`
- `bedrock.guardrail.guardrail_identifier` = `''` → `config-b.bedrock.guardrail`
- `bedrock.guardrail.guardrail_version` = `''` → `config-b.bedrock.guardrail`
- `bedrock.guardrail.stream_processing_mode` = `'async'` → `config-b.bedrock.guardrail`
- `bedrock.guardrail.trace` = `'disabled'` → `config-b.bedrock.guardrail`

**curator** (10 fields)

- `curator.enabled` = `True` → `config-b.curator.enabled`
- `curator.interval_hours` = `168` → `config-b.curator.cadence`
- `curator.min_idle_hours` = `2` → `config-b.curator.cadence`
- `curator.stale_after_days` = `30` → `config-b.curator.inactivity`
- `curator.archive_after_days` = `90` → `config-b.curator.inactivity`
- `curator.consolidate` = `False` → `config-b.curator.consolidate`
- `curator.prune_builtins` = `True` → `config-b.curator.prune_builtins`
- `curator.archive_ttl_days` = `0` → `config-b.curator.archive_ttl_days`
- `curator.backup.enabled` = `True` → `config-b.curator.backup`
- `curator.backup.keep` = `5` → `config-b.curator.backup`

**database** (3 fields)

- `database.journal_mode` = `'wal'` → `config-b.database.journal_mode`
- `database.wal_autocheckpoint` = `None` → `config-b.database.wal_sizing`
- `database.journal_size_limit` = `None` → `config-b.database.wal_sizing`

**desktop** (11 fields)

- `desktop.repo_scan_enabled` = `True` → `config-b.desktop.repo_scan`
- `desktop.repo_scan_roots` = `[]` → `config-b.desktop.repo_scan`
- `desktop.repo_scan_exclude_paths` = `[]` → `config-b.desktop.repo_scan`
- `desktop.electron_flags` = `[]` → `config-b.desktop.electron_flags`
- `desktop.ozone_platform_hint` = `'auto'` → `config-b.desktop.ozone_platform_hint`
- `desktop.disable_gpu` = `'auto'` → `config-b.desktop.disable_gpu`
- `desktop.password_store` = `'auto'` → `config-b.desktop.password_store`
- `desktop.macos_signing_identity` = `''` → `config-b.desktop.macos_signing_identity`
- `desktop.auto_continue.enabled` = `True` → `config-b.desktop.auto_continue`
- `desktop.auto_continue.freshness_minutes` = `15` → `config-b.desktop.auto_continue`
- `desktop.auto_continue.max_attempts` = `2` → `config-b.desktop.auto_continue`

**gateway** (22 fields)

- `gateway.multiplex_profile_allowlist` = `None` → `config-b.gateway.multiplex_profile_allowlist`
- `gateway.signal_interrupt_grace_timeout` = `1` → `config-b.gateway.signal_interrupt_grace_timeout`
- `gateway.delivery_ledger` = `True` → `config-b.gateway.delivery_ledger`
- `gateway.platform_connect_timeout` = `30` → `config-b.gateway.platform_connect_timeout`
- `gateway.loop_watchdog` = `True` → `config-b.gateway.loop_watchdog`
- `gateway.loop_watchdog_probe_interval_s` = `30.0` → `config-b.gateway.loop_watchdog`
- `gateway.loop_watchdog_probe_timeout_s` = `10.0` → `config-b.gateway.loop_watchdog`
- `gateway.loop_watchdog_max_strikes` = `3` → `config-b.gateway.loop_watchdog`
- `gateway.write_sessions_json` = `True` → `config-b.gateway.write_sessions_json`
- `gateway.scale_to_zero.idle_timeout_minutes` = `2` → `config-b.gateway.scale_to_zero`
- `gateway.restart_loop_guard.max_restarts` = `3` → `config-b.gateway.restart_loop_guard`
- `gateway.restart_loop_guard.window_seconds` = `60` → `config-b.gateway.restart_loop_guard`
- `gateway.restart_loop_guard.max_gap_seconds` = `300` → `config-b.gateway.restart_loop_guard`
- `gateway.respawn_storm.max_starts` = `5` → `config-b.gateway.respawn_storm`
- `gateway.respawn_storm.window_seconds` = `120` → `config-b.gateway.respawn_storm`
- `gateway.message_timestamps.enabled` = `False` → `config-b.gateway.message_timestamps`
- `gateway.max_inbound_media_bytes` = `134217728` → `config-b.gateway.max_inbound_media_bytes`
- `gateway.strict` = `False` → `config-b.gateway.strict`
- `gateway.media_delivery_allow_dirs` = `[]` → `config-b.gateway.media_delivery_allow_dirs`
- `gateway.trust_recent_files` = `True` → `config-b.gateway.trust_recent_files`
- `gateway.trust_recent_files_seconds` = `600` → `config-b.gateway.trust_recent_files`
- `gateway.api_server.max_concurrent_runs` = `10` → `config-b.gateway.api_server_max_concurrent_runs`

**kanban** (16 fields)

- `kanban.auto_subscribe_on_create` = `True` → `config-b.kanban.auto_subscribe_on_create`
- `kanban.dispatch_in_gateway` = `True` → `config-b.kanban.dispatch_in_gateway`
- `kanban.review_dispatch` = `True` → `config-b.kanban.review_dispatch`
- `kanban.dispatch_interval_seconds` = `60` → `config-b.kanban.dispatch_interval_seconds`
- `kanban.failure_limit` = `2` → `config-b.kanban.failure_limit`
- `kanban.worker_log_rotate_bytes` = `2097152` → `config-b.kanban.worker_logs`
- `kanban.worker_log_backup_count` = `1` → `config-b.kanban.worker_logs`
- `kanban.orchestrator_profile` = `''` → `config-b.kanban.orchestrator_profile`
- `kanban.default_assignee` = `''` → `config-b.kanban.default_assignee`
- `kanban.max_in_progress` = `None` → `config-b.kanban.max_in_progress`
- `kanban.max_in_progress_per_profile` = `None` → `config-b.kanban.max_in_progress_per_profile`
- `kanban.auto_decompose` = `True` → `config-b.kanban.auto_decompose`
- `kanban.auto_decompose_per_tick` = `3` → `config-b.kanban.auto_decompose`
- `kanban.dispatch_stale_timeout_seconds` = `14400` → `config-b.kanban.dispatch_stale_timeout_seconds`
- `kanban.reconcile_orphans` = `True` → `config-b.kanban.reconcile_orphans`
- `kanban.done_sub_retention_days` = `30` → `config-b.kanban.done_sub_retention_days`

**loops** (4 fields)

- `loops.min_interval_seconds` = `30` → `config-b.loops.min_interval_seconds`
- `loops.max_ticks` = `100` → `config-b.loops.max_ticks`
- `loops.self_paced_floor_seconds` = `60` → `config-b.loops.self_paced_bounds`
- `loops.self_paced_ceiling_seconds` = `900` → `config-b.loops.self_paced_bounds`

**lsp** (5 fields)

- `lsp.enabled` = `True` → `config-b.lsp.enabled`
- `lsp.wait_mode` = `'document'` → `config-b.lsp.wait`
- `lsp.wait_timeout` = `5.0` → `config-b.lsp.wait`
- `lsp.install_strategy` = `'auto'` → `config-b.lsp.install_strategy`
- `lsp.idle_timeout` = `600.0` → `config-b.lsp.idle_timeout`

**matrix** (3 fields)

- `matrix.require_mention` = `True` → `config-b.matrix.require_mention`
- `matrix.free_response_rooms` = `''` → `config-b.matrix.free_response_rooms`
- `matrix.allowed_rooms` = `''` → `config-b.matrix.allowed_rooms`

**mattermost** (3 fields)

- `mattermost.require_mention` = `True` → `config-b.mattermost.require_mention`
- `mattermost.free_response_channels` = `''` → `config-b.mattermost.free_response_channels`
- `mattermost.allowed_channels` = `''` → `config-b.mattermost.allowed_channels`

**moa** (10 fields)

- `moa.default_preset` = `'default'` → `config-b.moa.preset_selection`
- `moa.active_preset` = `''` → `config-b.moa.preset_selection`
- `moa.save_traces` = `False` → `config-b.moa.traces`
- `moa.trace_dir` = `''` → `config-b.moa.traces`
- `moa.privacy_filter` = `''` → `config-b.moa.privacy_filter`
- `moa.presets.default.reference_models` = `[{'provider': 'openai-codex', 'model': 'gpt-5.5'}, {'provider': 'openrouter', 'model': 'deepseek/deepseek-v4-pro'}]` → `config-b.moa.presets_default`
- `moa.presets.default.aggregator.provider` = `'openrouter'` → `config-b.moa.presets_default`
- `moa.presets.default.aggregator.model` = `'anthropic/claude-opus-4.8'` → `config-b.moa.presets_default`
- `moa.presets.default.max_tokens` = `4096` → `config-b.moa.presets_default`
- `moa.presets.default.enabled` = `True` → `config-b.moa.presets_default`

**model_catalog** (3 fields)

- `model_catalog.enabled` = `True` → `config-b.model_catalog`
- `model_catalog.url` = `'https://hermes-agent.nousresearch.com/docs/api/model-catalog.json'` → `config-b.model_catalog`
- `model_catalog.ttl_hours` = `1` → `config-b.model_catalog`

**monitoring** (11 fields)

- `monitoring.install_id` = `''` → `config-b.monitoring.install_id`
- `monitoring.gateway_health_export.enabled` = `False` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.metrics_enabled` = `True` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.diagnostic_events_enabled` = `True` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.warning_error_events_enabled` = `True` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.export_interval_seconds` = `60` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.logs_export_interval_seconds` = `5` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.resource_attributes.service.name` = `'hermes-gateway'` → `config-b.monitoring.gateway_health_export`
- `monitoring.gateway_health_export.resource_attributes.deployment.environment.name` = `'production'` → `config-b.monitoring.gateway_health_export`
- `monitoring.export.otlp.enabled` = `False` → `config-b.monitoring.export_otlp`
- `monitoring.export.otlp.endpoint` = `''` → `config-b.monitoring.export_otlp`

**openrouter** (3 fields)

- `openrouter.response_cache` = `True` → `config-b.openrouter.response_cache`
- `openrouter.response_cache_ttl` = `300` → `config-b.openrouter.response_cache`
- `openrouter.min_coding_score` = `0.65` → `config-b.openrouter.min_coding_score`

**proxy** (5 fields)

- `proxy.tunnel_port` = `9090` → `config-b.proxy.tunnel_port`
- `proxy.auto_install` = `True` → `config-b.proxy.auto_install`
- `proxy.allow_env_fallback` = `False` → `config-b.proxy.allow_env_fallback`
- `proxy.upstream_deny_cidrs` = `None` → `config-b.proxy.upstream_deny_cidrs`
- `proxy.extra_allowed_hosts` = `[]` → `config-b.proxy.extra_allowed_hosts`

**secrets** (15 fields)

- `secrets.bitwarden.enabled` = `False` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.access_token_env` = `'BWS_ACCESS_TOKEN'` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.project_id` = `''` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.cache_ttl_seconds` = `300` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.encrypted_cache.enabled` = `False` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.encrypted_cache.max_stale_seconds` = `0` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.override_existing` = `True` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.auto_install` = `True` → `config-b.secrets.bitwarden`
- `secrets.bitwarden.server_url` = `''` → `config-b.secrets.bitwarden`
- `secrets.onepassword.enabled` = `False` → `config-b.secrets.onepassword`
- `secrets.onepassword.account` = `''` → `config-b.secrets.onepassword`
- `secrets.onepassword.service_account_token_env` = `'OP_SERVICE_ACCOUNT_TOKEN'` → `config-b.secrets.onepassword`
- `secrets.onepassword.binary_path` = `''` → `config-b.secrets.onepassword`
- `secrets.onepassword.cache_ttl_seconds` = `300` → `config-b.secrets.onepassword`
- `secrets.onepassword.override_existing` = `True` → `config-b.secrets.onepassword`

**sessions** (13 fields)

- `sessions.auto_prune` = `False` → `config-b.sessions.auto_prune`
- `sessions.retention_days` = `90` → `config-b.sessions.auto_prune`
- `sessions.auto_archive` = `False` → `config-b.sessions.auto_archive`
- `sessions.auto_archive_days` = `3` → `config-b.sessions.auto_archive`
- `sessions.vacuum_after_prune` = `True` → `config-b.sessions.vacuum`
- `sessions.min_vacuum_interval_days` = `30` → `config-b.sessions.vacuum`
- `sessions.min_interval_hours` = `24` → `config-b.sessions.min_interval_hours`
- `sessions.write_json_snapshots` = `False` → `config-b.sessions.write_json_snapshots`
- `sessions.fts_optimize_notice` = `'advise'` → `config-b.sessions.fts_optimize_notice`
- `sessions.cjk_fts` = `True` → `config-b.sessions.cjk_fts`
- `sessions.search_slow_ms` = `1000` → `config-b.sessions.search_slow_ms`
- `sessions.max_resume_messages` = `20000` → `config-b.sessions.transcript_limits`
- `sessions.max_export_messages` = `20000` → `config-b.sessions.transcript_limits`

**slack** (6 fields)

- `slack.require_mention` = `True` → `config-b.slack.require_mention`
- `slack.free_response_channels` = `''` → `config-b.slack.free_response_channels`
- `slack.allowed_channels` = `''` → `config-b.slack.allowed_channels`
- `slack.require_mention_channels` = `''` → `config-b.slack.require_mention_channels`
- `slack.ignore_other_user_mentions` = `False` → `config-b.slack.ignore_other_user_mentions`
- `slack.thread_require_mention` = `False` → `config-b.slack.thread_require_mention`

**streaming** (6 fields)

- `streaming.enabled` = `False` → `config-b.streaming.enabled`
- `streaming.transport` = `'auto'` → `config-b.streaming.transport`
- `streaming.edit_interval` = `0.8` → `config-b.streaming.pacing`
- `streaming.buffer_threshold` = `24` → `config-b.streaming.pacing`
- `streaming.cursor` = `' ▉'` → `config-b.streaming.cursor`
- `streaming.fresh_final_after_seconds` = `0.0` → `config-b.streaming.fresh_final_after_seconds`

**tool_loop_guardrails** (10 fields)

- `tool_loop_guardrails.warnings_enabled` = `True` → `config-b.tool_loop_guardrails.switches`
- `tool_loop_guardrails.hard_stop_enabled` = `False` → `config-b.tool_loop_guardrails.switches`
- `tool_loop_guardrails.warn_after.exact_failure` = `2` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.warn_after.same_tool_failure` = `3` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.warn_after.idempotent_no_progress` = `2` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.hard_stop_after.exact_failure` = `5` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.hard_stop_after.same_tool_failure` = `8` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.hard_stop_after.idempotent_no_progress` = `5` → `config-b.tool_loop_guardrails.thresholds`
- `tool_loop_guardrails.loop_caps.max_web_searches` = `50` → `config-b.tool_loop_guardrails.loop_caps`
- `tool_loop_guardrails.loop_caps.max_subagents` = `50` → `config-b.tool_loop_guardrails.loop_caps`

**tool_output** (3 fields)

- `tool_output.max_bytes` = `50000` → `config-b.tool_output`
- `tool_output.max_lines` = `2000` → `config-b.tool_output`
- `tool_output.max_line_length` = `2000` → `config-b.tool_output`

**tools** (6 fields)

- `tools.tool_search.enabled` = `'auto'` → `config-b.tools.tool_search`
- `tools.tool_search.threshold_pct` = `5` → `config-b.tools.tool_search`
- `tools.tool_search.search_default_limit` = `5` → `config-b.tools.tool_search`
- `tools.tool_search.max_search_limit` = `25` → `config-b.tools.tool_search`
- `tools.tool_search.listing` = `'auto'` → `config-b.tools.tool_search`
- `tools.tool_search.listing_max_tokens` = `4000` → `config-b.tools.tool_search`

**vertex** (2 fields)

- `vertex.project_id` = `''` → `config-b.vertex`
- `vertex.region` = `'global'` → `config-b.vertex`

**wake_word** (14 fields)

- `wake_word.enabled` = `False` → `config-b.wake_word.enabled`
- `wake_word.surface` = `'auto'` → `config-b.wake_word.surface`
- `wake_word.input_device` = `None` → `config-b.wake_word.input_device`
- `wake_word.capture` = `'auto'` → `config-b.wake_word.capture`
- `wake_word.provider` = `'openwakeword'` → `config-b.wake_word.provider`
- `wake_word.phrase` = `'hey hermes'` → `config-b.wake_word.phrase`
- `wake_word.sensitivity` = `0.6` → `config-b.wake_word.thresholds`
- `wake_word.confirmation_frames` = `3` → `config-b.wake_word.thresholds`
- `wake_word.start_new_session` = `True` → `config-b.wake_word.start_new_session`
- `wake_word.profile_routing` = `True` → `config-b.wake_word.profile_routing`
- `wake_word.openwakeword.model` = `'hey_hermes'` → `config-b.wake_word.openwakeword`
- `wake_word.openwakeword.inference_framework` = `''` → `config-b.wake_word.openwakeword`
- `wake_word.sherpa.model_dir` = `''` → `config-b.wake_word.sherpa_model_dir`
- `wake_word.porcupine.keyword` = `'jarvis'` → `config-b.wake_word.porcupine_keyword`

**web** (9 fields)

- `web.backend` = `''` → `config-b.web.backends`
- `web.search_backend` = `''` → `config-b.web.backends`
- `web.extract_backend` = `''` → `config-b.web.backends`
- `web.extract_char_limit` = `15000` → `config-b.web.extract_char_limit`
- `web.keyless_fallback` = `True` → `config-b.web.keyless`
- `web.keyless_rescue` = `True` → `config-b.web.keyless`
- `web.cache_enabled` = `True` → `config-b.web.cache`
- `web.cache_ttl_minutes` = `20` → `config-b.web.cache`
- `web.cache_exempt_hosts` = `[]` → `config-b.web.cache`

**x_search** (4 fields)

- `x_search.model` = `'grok-4.5'` → `config-b.x_search`
- `x_search.reasoning_effort` = `None` → `config-b.x_search`
- `x_search.timeout_seconds` = `180` → `config-b.x_search`
- `x_search.retries` = `2` → `config-b.x_search`

## Handoffs

- `proxy.enabled`, `proxy.credential_source`, `proxy.enforce_on_docker` — the live schema files these three under the **security** category, so they belong to the config-a shard even though they are part of the `proxy:` block documented here.
- `hermes secrets bitwarden setup|status|sync` and `hermes secrets onepassword …` — the CLI commands themselves (flags `--access-token`, `--account`, `--token-env`, `--binary-path`, `--apply`, …) belong to a CLI shard; only the config keys they write are covered here.
- `hermes kanban specify|decompose|…`, `hermes curator run|purge|rollback` (incl. `--consolidate`, `--dry-run`), `hermes sessions prune|export|optimize-storage`, `hermes moa`, `hermes lsp status`, `hermes model` (auxiliary picker `_AUX_TASKS`), `hermes tools` (web backend + "Free (keyless)" / "Paid (API key)" rows writing `web.provider_tier`), `hermes proxy`, `hermes desktop`, `hermes loop` — command surfaces belong to the CLI shards.
- Kanban dashboard plugin API `GET /orchestration` + `PUT /orchestration` (body fields `orchestrator_profile`, `default_assignee`, `auto_decompose`, `auto_promote_children`; 400 `profile '<name>' does not exist`) — an API/plugin shard.
- The gateway monitoring status printer block (`Gateway monitoring`, `  Health export:  …`, `    Content safety:     always on (rendered messages are never exported; not configurable)`) at `hermes_cli/main.py:12995-13010` — CLI shard.
- The Discord voice mixer implementation (`plugins/platforms/discord/voice_mixer.py`), the `tool_search` bridge tool itself, the `web_search`/`web_extract` tools and the keyless free-tier ring (`plugins/web/keyless_mcp.py`) — tool shards.
- Web dashboard **Config** page chrome beyond field rendering (search box, `SECTIONS` rail with per-category counts, `YAML` / form toggle, `Save`, import/export, reset dialog, `t.config.*` i18n keys) — web shard.
- `OPTIONAL_ENV_VARS` and the full environment-variable reference (671 documented / 1056 read in code), including every `DISCORD_*`, `SLACK_*`, `MATRIX_*`, `MATTERMOST_*`, `TELEGRAM_*`, `HERMES_MEDIA_*`, `HERMES_GATEWAY_*`, `HERMES_OPENROUTER_*`, `VERTEX_*`, `BWS_*`, `OP_SERVICE_ACCOUNT_TOKEN`, `PORCUPINE_ACCESS_KEY`, `XAI_API_KEY` named above — env shard.
- `bedrock.discovery.enabled` / `.provider_filter` / `.refresh_interval` are declared but never read in v2026.8.31 (verified by grep over every `get("bedrock")` consumer) — worth flagging to whoever writes the "declared but inert" summary.
