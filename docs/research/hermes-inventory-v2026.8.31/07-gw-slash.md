# Gateway Slash Commands (Telegram & all chat platforms)

This shard documents every slash command a user can type into a Hermes chat platform
(Telegram, Discord, Slack, Matrix, WhatsApp, Signal, Email, Teams, Mattermost, IRC, LINE,
WeCom, Home Assistant, Relay, API-server rooms …) at tag `v2026.8.31`: the message→command
grammar, the dispatch/resolution order, the admin/user access gate, the running-agent
("busy") policy, the confirm sub-dialogs, every one of the 66 gateway-available registry
commands with all of its arguments and reply templates, plus the dynamic families
(skill commands, stacked skills, bundles, plugin commands, user-defined quick commands)
and the per-platform command-menu projections (Telegram BotCommands, Slack native slashes +
`/hermes <sub>`, Discord slash registration).
It deliberately leaves to sibling shards: the CLI/TUI/Desktop rendering of the same commands
(`cli-*`, `desktop-*`), the config keys themselves (`config-*`), the tools/toolsets a command
ends up invoking (`tools`), the platform adapters' transport internals (`platforms`), and the
dashboard's own command surfaces (`web-*`).

Primary sources: `gateway/slash_commands.py` (57 `_handle_*_command` handlers, 6466 lines),
`gateway/run.py` (dispatch site ~L18560–L19560, plain-handler table L17750–L17780, busy
dispatcher L17735–L17836), `hermes_cli/commands.py` (`COMMAND_REGISTRY`, the single source of
truth), `gateway/slash_access.py`, `hermes_cli/slash_exec.py`, `agent/skill_commands.py`,
`agent/skill_bundles.py`, `tools/slash_confirm.py`, `locales/en.yaml` (the `gateway.*` i18n
catalog — every quoted reply template below is transcribed from it), and
`website/docs/reference/slash-commands.md`.

---

## 1. Grammar, dispatch and gating

### Slash-command recognition (what counts as a command)  `id: gw-slash.command-grammar`
- **Surface:** Gateway/Telegram
- **Where:** Any chat message whose first non-whitespace character is `/` — e.g. `/status`, `/model gpt-5.5 --global`, `/new my-experiment`, `/queue write the tests`.
- **What it does:** Turns the first token of a chat message into a command name plus an argument string, so the gateway can route it to a handler instead of the LLM.
- **How it works:** `MessageEvent.is_command()` at `gateway/platforms/base.py:2518` returns `allow_gateway_control and text.lstrip().startswith("/")`. `MessageEvent.get_command()` (`base.py:2523`) takes `text.lstrip().split(maxsplit=1)[0][1:].lower()`, then strips a Telegram-style bot suffix (`raw.split("@",1)[0]` → `/status@HermesBot` = `status`), and returns `None` when the token still contains `/` (so a pasted path like `/home/user/x` is NOT a command). `MessageEvent.get_command_args()` (`base.py:2538`) returns everything after the first space and normalises iOS smart punctuation: `——`→`--`, `—`→`--`, `–`→`-`, so `/model gpt —global` still parses `--global`.
- **Inputs / options:** the raw message text; `event.allow_gateway_control` (False for proactive plugin events ⇒ no command recognition at all, the text stays conversational); `@botname` suffix; leading whitespace.
- **Outputs / side effects:** none by itself — produces `(canonical_name, args_string)` consumed by the dispatcher.
- **Config / env:** n/a.
- **Edge cases / guards:** a token containing `/` returns `None` (path guard); casing is folded to lowercase; `allow_gateway_control=False` disables the whole command plane for that event; media-only messages with a caption starting `/` still parse (e.g. `/queue` as a photo caption — see `gw-slash.queue`).
- **Rebuild notes:** parse `^\s*/([A-Za-z0-9_-]+)(?:@\S+)?(?:\s+(.*))?$`, lowercase the name, reject names containing `/`, normalise unicode dashes in the args. A better version would also accept a configurable prefix per platform and quote-aware arg tokenisation at parse time rather than per-handler `shlex.split`.

### `!command` prefix (Slack threads, Matrix)  `id: gw-slash.bang-prefix`
- **Surface:** Platform:slack | Platform:matrix
- **Where:** Typed in a Slack thread or a Matrix room: `!stop`, `!new`, `!status`, `@Hermes !stop`. Docs quote Slack's own refusal verbatim: `"/queue is not supported in threads. Sorry!"`.
- **What it does:** Lets users reach Hermes commands on platforms where a typed `/` is swallowed by the client (Slack threads) or reserved by the client (Matrix).
- **How it works:** each adapter declares `typed_command_prefix` (`gateway/platforms/base.py:3112` default `"/"`; `plugins/platforms/slack/adapter.py:1131` = `"!"`; `plugins/platforms/matrix/adapter.py:1182` = `"!"`). Slack rewrites on receive via `_rewrite_known_bang_command()` (`plugins/platforms/slack/adapter.py:445`): if text starts with `!`, take the first token, strip an `@suffix`, lowercase, reject if it contains `/`, and rewrite to `"/" + text[1:]` **only when `is_gateway_known_command(name)`** is true. Call sites: `adapter.py:6164` (plain message) and `adapter.py:6570` (mention-stripped). Matrix uses `_normalize_matrix_bang_command()` (`plugins/platforms/matrix/adapter.py:335`) with `_MATRIX_BANG_COMMAND_RE`; its resolver (`adapter.py:~300`) tries the raw lowercased token, then the hyphenated variant (`!reload_skills` → `reload-skills`), against `is_gateway_known_command()` and then against `get_skill_commands()` keys (`/candidate`).
- **Inputs / options:** `!<known-command> [args]`; `@Hermes !<cmd>`; `@Hermes /<cmd>`; underscore/hyphen variants on Matrix.
- **Outputs / side effects:** rewrites `event.text` in place before dispatch; unknown bangs are left untouched, so `!nice work` reaches the agent as ordinary prose.
- **Config / env:** n/a (adapter class attribute).
- **Edge cases / guards:** only the FIRST token is tested; only *known* commands are rewritten; the confirm keywords `always`/`cancel` are not registry commands, so `!always` / `!cancel` survive with the `!` and are handled by the confirm intercept's `lstrip("!/")` (see `gw-slash.slash-confirm`).
- **Rebuild notes:** keep a per-adapter prefix capability and rewrite only known names; instruction text must be rendered with `self._typed_command_prefix_for(platform)` (`gateway/slash_commands.py:131`) so prompts on Slack/Matrix say `!approve`, not `/approve`.

### Alias resolution and canonicalisation  `id: gw-slash.alias-resolution`
- **Surface:** Gateway/Telegram | Core
- **Where:** typing any alias in chat: `/reset`, `/fork`, `/ctx`, `/tasks`, `/q`, `/hb`, `/compact`, `/v`, `/bp`, `/suggest`, `/proactive`, `/set-home`, `/reload_mcp`, `/reload_skills`, `/codex_runtime`.
- **What it does:** maps every registered alias to its canonical command so dispatch, hooks and gating all key on one name.
- **How it works:** `_build_command_lookup()` (`hermes_cli/commands.py:450`) fills `_COMMAND_LOOKUP` with `cmd.name` and every entry of `cmd.aliases`; `resolve_command(name)` (`commands.py:463`) does `_COMMAND_LOOKUP.get(name.lower().lstrip("/"))`. The gateway calls it at `gateway/run.py:18888` (`_cmd_def = _resolve_cmd(command); canonical = _cmd_def.name if _cmd_def else command`) and again on the busy path (`run.py:18661`).
- **Inputs / options:** the complete alias set in v2026.8.31 — `new`→(`reset`), `save`, `prompt`→(`compose`), `branch`→(`fork`), `compress`→(`compact`), `snapshot`→(`snap`), `agents`→(`tasks`), `journey`→(`learning`,`memory-graph`), `queue`→(`q`), `heartbeat`→(`hb`), `loop`→(`proactive`), `sethome`→(`set-home`), `codex-runtime`→(`codex_runtime`), `statusbar`→(`sb`), `timestamps`→(`ts`), `reload-mcp`→(`reload_mcp`), `reload-skills`→(`reload_skills`), `suggestions`→(`suggest`), `blueprint`→(`bp`), `subscription`→(`upgrade`), `platforms`→(`gateway`), `version`→(`v`), `quit`→(`exit`).
- **Outputs / side effects:** the `command:<canonical>` hook, the access check, and the busy policy all use the canonical name; `raw_command` in the hook context preserves what the user actually typed.
- **Config / env:** n/a.
- **Edge cases / guards:** the docs claim CLI prefix matching (`/h`→`/help`); the **gateway does not do prefix matching** — an unmatched name falls through to quick/plugin/skill lookup and then the unknown-command notice. Underscore↔hyphen normalisation happens only in the skill/plugin lookup (`command.replace("_","-")`), not in `resolve_command`, which is why both `reload-mcp` and `reload_mcp` are registered as explicit aliases.
- **Rebuild notes:** one registry, one lookup dict containing names+aliases; never branch on the typed spelling after resolution.

### Dispatch order for a chat slash command  `id: gw-slash.dispatch-order`
- **Surface:** Gateway/Telegram | Core
- **Where:** invisible to the user, but determines which of two same-named things wins (e.g. a quick command named `status` vs the built-in `/status`).
- **What it does:** resolves one typed `/x` against six namespaces in a fixed precedence.
- **How it works:** in `GatewayRunner._handle_message` (`gateway/run.py:18033`+) the *cold path* (no running agent) runs, in order: **(1)** e-stop gate (`run.py:18270`) — recognised slash commands bypass a global pause; **(2)** pending `/update` prompt intercept (`run.py:18316`); **(3)** pending clarify intercept; **(4)** pending slash-confirm intercept (`run.py:18489`); **(5)** running-agent guard (`run.py:18650`) → `_dispatch_busy_slash_command`; then in the cold path: **(6)** `resolve_command(command)` → alias expansion; **(7)** *quick-command alias pre-expansion* — only when the typed name is NOT in the registry (`run.py:18866`), rewriting `event.text` to the alias target; **(8)** `_check_slash_access` (`run.py:18900`); **(9)** `fire_pre_command_hook` (`run.py:18915`); **(10)** `command:<canonical>` hook with deny/handled/rewrite decisions (`run.py:18940`); **(11)** `_gateway_plain_command_handlers()[canonical]` (21 entries, `run.py:17757`); **(12)** the `if canonical == "…"` chain (46 branches, `run.py:18994`–`19314`); **(13)** user-defined quick commands (`run.py:19326`); **(14)** plugin-registered commands (`run.py:19381`); **(15)** skill *bundles* (`run.py:19400`); **(16)** skill commands incl. stacked (`run.py:19430`); **(17)** `_check_unavailable_skill` (disabled / optional skills); **(18)** unknown-command notice; otherwise the (possibly rewritten) text falls through to the agent turn.
- **Inputs / options:** n/a (control flow).
- **Outputs / side effects:** exactly one of: a reply string, an `EphemeralReply`, `None` (adapter already sent, e.g. a picker), `""` (silent), or a fall-through to `_handle_message_with_agent`.
- **Config / env:** `quick_commands` (config.yaml) participates at steps 7 and 13.
- **Edge cases / guards:** built-ins always beat quick commands (step 7 only fires when `resolve_command` returned `None`); bundles beat individual skills; skills whose slug collides with a core command are never registered (`agent/skill_commands.py:~508`, logs *"collides with a core Hermes command; skipping auto-registration. Use '/skill <name>' instead."*).
- **Rebuild notes:** implement as an ordered resolver list returning `Optional[Reply]`; keep the "registry wins" rule so a user's quick command can never shadow `/stop`.

### Running-agent (busy) slash dispatch  `id: gw-slash.busy-dispatch`
- **Surface:** Gateway/Telegram | Core
- **Where:** typing any command while Hermes is mid-turn; user sees either the command's normal reply, a special mid-run reply, or `⏳ Agent is running — `/<name>` can't run mid-turn. Wait for the current response or `/stop` first.`
- **What it does:** decides per-command whether it runs mid-turn, interrupts the turn first, or is refused.
- **How it works:** every `CommandDef` carries `busy_policy ∈ {"dispatch","reject","interrupt_then_dispatch"}` and an optional `busy_handler` key (`hermes_cli/commands.py:100`–`137`, `VALID_BUSY_POLICIES` at `:138`). `_dispatch_busy_slash_command` (`gateway/run.py:17781`) resolves in order: (a) `busy_handler` → one of the special table `{"start": _busy_start_command, "stop": _busy_stop_command, "new": _busy_new_command, "queue": _busy_queue_command, "steer": _busy_steer_command, "egress": _busy_egress_command, "goal": _busy_goal_command, "loop": _busy_loop_command}` (`run.py:17811`); (b) `busy_handler` naming an entry in `_BUSY_REJECT_TEXT` (`run.py:17745`) — `model`: `"Agent is running — wait or /stop first, then switch models."`, `codex-runtime`: `"Agent is running — wait or /stop first, then change runtime."`, `moa`: `"Agent is running — wait or /stop first, then run /moa."`; (c) `busy_policy in ("dispatch","interrupt_then_dispatch")` → `_gateway_plain_command_handlers()[name]`; (d) the catch-all reject text above. `/status` and `/context` are dispatched *before* the access gate so state is always visible (`run.py:18663–18667`).
- **Inputs / options:** the 21 mid-run-capable plain handlers: `status, context, restart, approve, deny, pause, agents, bg, btw, kanban, subgoal, heartbeat, busy, yolo, verbose, footer, help, commands, profile, update, version`. `interrupt_then_dispatch` commands: `new`(+`reset`) and `stop`. Mid-run variants: `/start` (silent ping), `/stop` (hard kill), `/new` (interrupt then reset), `/queue` (FIFO enqueue), `/steer` (mid-tool injection), `/egress` (status text), `/goal` (control verbs only), `/loop` (control verbs only).
- **Outputs / side effects:** may interrupt and release the session slot; may enqueue a FIFO event; never queues a *recognised* command as user text (`should_bypass_active_session()` returns True for any resolvable command, `hermes_cli/commands.py:595`).
- **Config / env:** `display.busy_input_mode` governs what *non-command* text does (see `gw-slash.busy`).
- **Edge cases / guards:** issues #5057/#6252/#10370 — before this table a mid-run `/model` interrupted the agent AND was discarded, producing a zero-char reply. `ACTIVE_SESSION_BYPASS_COMMANDS` (`commands.py:575`) is derived as every command whose `busy_policy != "reject"`. Guard 1 lives in `gateway/platforms/base.py` and routes `is_interrupt_then_dispatch()` names through the cancel-handoff path.
- **Rebuild notes:** declare mid-run behaviour on the command definition, not in an if-chain; always answer a recognised command, never silently drop it.

### Slash-command access control (admin / user tiers)  `id: gw-slash.access-control`
- **Surface:** Gateway/Telegram | Config
- **Where:** configured under a platform's `extra:` block in `~/.hermes/gateway-config.yaml`; surfaced to the user as `⛔ /<cmd> is admin-only here. …` and by `/whoami`.
- **What it does:** splits the users already allowed to talk to the bot into **admins** (every registered slash command) and **users** (only the names listed for that scope, plus a floor of `/help` and `/whoami`).
- **How it works:** `gateway/slash_access.py`. `policy_for_source(gateway_config, source)` (`:186`) resolves the platform's `PlatformConfig.extra`, maps `source.chat_type` to a scope via `_scope_for_chat_type` (`:135`; `{"dm","direct","private",""}` → `"dm"`, everything else → `"group"`), then `policy_from_extra(extra, scope)` (`:160`) reads `allow_admin_from` / `user_allowed_commands` for DM and `group_allow_admin_from` / `group_user_allowed_commands` for group. `_coerce_id_list` (`:88`) accepts None/list/tuple/set/comma-separated string/scalar; `_coerce_command_list` (`:110`) additionally strips a leading `/` and lowercases. DM scope falls back to `group_user_allowed_commands` when its own list is unset (admin lists never cross scope). `enabled = bool(admin_ids)` — **if no admin list is set for the scope, gating is off entirely and everyone can run everything** (backward compatibility). `SlashAccessPolicy.can_run` (`:76`) allows when gating is off, when the user is an admin, when the command is in `_ALWAYS_ALLOWED_FOR_USERS = frozenset({"help","whoami"})` (`:52`), or when it is in `user_allowed_commands`. The gateway calls `_check_slash_access` (`gateway/run.py:22988`) on the cold path (`run.py:18900`), the busy path (`run.py:18675`) and again for quick commands (`run.py:19335`, issue #44727).
- **Inputs / options:** `allow_admin_from`, `user_allowed_commands`, `group_allow_admin_from`, `group_user_allowed_commands`.
- **Outputs / side effects:** denial reply, built at `run.py:23016`: with a configured list — `⛔ /<cmd> is admin-only here. You can run: /a, /b, …` (first 12, `…` if more) + `. Use /whoami for the full list.`; with an empty list — `⛔ /<cmd> is admin-only here. No slash commands are enabled for non-admins on this platform. Ask an admin to add you to allow_admin_from or to set user_allowed_commands.` A log line `Slash command /%s denied for %s:%s (not admin, not in user_allowed_commands)`.
- **Config / env:** the four keys above, per platform, inside `platforms.<name>.extra`.
- **Edge cases / guards:** plain chat is never gated — only slash commands. `/status` is intentionally *pre-gate* on the busy path. `/approvals` re-checks admin at its own side-effect boundary (`gateway/slash_commands.py:4177`) because it mutates profile-wide security policy. `/sessions all` and `/resume --all` are additionally gated on `_resume_caller_is_admin`.
- **Rebuild notes:** two lists per (platform, scope), a hard floor of read-only discovery commands, and a fail-open default so upgrades don't lock operators out. A better version would add per-command rate limits and an audit log (explicitly dropped from PR #4443 when this was salvaged — see the module docstring).

### Unknown-command notice  `id: gw-slash.unknown-command`
- **Surface:** Gateway/Telegram
- **Where:** reply to any unrecognised `/word`.
- **What it does:** tells the user the command doesn't exist instead of silently feeding `/word …` to the LLM.
- **How it works:** `gateway/run.py:19527` — reached only after quick, plugin, bundle and skill lookup all miss and `_check_unavailable_skill()` returns None; guarded by `if command.replace("_", "-") not in GATEWAY_KNOWN_COMMANDS`. Logs `Unrecognized slash command /%s from %s — replying with unknown-command notice`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** returns exactly: `` Unknown command `/<command>`. Type /commands to see what's available, or resend without the leading slash to send as a regular message. ``
- **Config / env:** n/a.
- **Edge cases / guards:** a registry-known command with **no** gateway handler (today: `/curator`) skips this branch and its literal text is forwarded to the model — see `gw-slash.curator`. Known-but-disabled skills get a different message: `` The **<name>** skill is installed but disabled.\nEnable it with: `hermes skills config` `` (`gateway/run.py:3985`); optional (not installed) skills get their own install hint from the same helper.
- **Rebuild notes:** always answer an unrecognised slash; suggest the discovery command; never forward `/x` to the model as prose.

### Command hooks: `pre_command` and `command:<name>`  `id: gw-slash.command-hooks`
- **Surface:** Gateway/Telegram | Core
- **Where:** invisible; plugins/hook scripts observe or intercept commands.
- **What it does:** gives plugins an observation point before every recognised slash command, and a veto/rewrite point.
- **How it works:** `fire_pre_command_hook(surface="gateway", command, alias_used, args_raw, session_key, platform)` (`gateway/run.py:18917`, observer-only in v1, return ignored). Then `await self.hooks.emit_collect(f"command:{canonical}", hook_ctx)` (`run.py:18956`) with `hook_ctx = {platform, user_id, command, raw_command, args, raw_args}`. Each dict result may carry `decision`: `"allow"`/empty (continue), `"deny"` (return `message` or `` Command `/<command>` was blocked by a hook. ``), `"handled"` (return `message` or None), `"rewrite"` (`command_name` + `raw_args` → `event.text = "/<new> <args>"`, re-resolve, break).
- **Inputs / options:** hook names are `command:<canonical>`; `is_gateway_known_command()` (`hermes_cli/commands.py:549`) decides eligibility and covers plugin-registered commands too.
- **Outputs / side effects:** can short-circuit dispatch or rewrite the command.
- **Config / env:** plugin/hook configuration (sibling shard).
- **Edge cases / guards:** deliberately NOT fired on the running-agent intercept path — the docstring at `run.py:18906` explains that `/stop`, `/approve` etc. are operator escape hatches and must not be interceptable by a slow or hostile plugin. Hook failures are swallowed (`logger.debug`).
- **Rebuild notes:** collect-style hook returning a decision object; never allow hooks on the interrupt/approval control plane.

### Slash-confirm dialog (Approve Once / Always Approve / Cancel)  `id: gw-slash.slash-confirm`
- **Surface:** Gateway/Telegram
- **Where:** appears for `/reload-mcp`, for a guarded `/model <name>` switch, and (via the destructive gate) for `/new`, `/reset`, `/undo`. Buttons are labelled **Approve Once**, **Always Approve**, **Cancel**; the text fallback line reads ``_Text fallback: reply `/approve`, `/always`, or `/cancel`._`` (with `!` instead of `/` on Slack/Matrix).
- **What it does:** a three-way confirmation that works with native buttons where available and with typed replies everywhere else.
- **How it works:** `tools/slash_confirm.py` keeps a module-level `_pending: {session_key: {confirm_id, command, handler, created_at}}` guarded by an `RLock`, with `DEFAULT_TIMEOUT_SECONDS = 300`. `GatewayRunner._request_slash_confirm` (`gateway/run.py:25597`) mints `confirm_id` from `self._slash_confirm_counter`, calls `register()` **before** attempting the send (so a fast button click can't race), then tries `adapter.send_slash_confirm(chat_id, title, message, session_key, confirm_id, metadata)`. If buttons rendered it returns `None` (no redundant text); otherwise it returns the prompt text itself as the reply. Resolution: buttons call `tools.slash_confirm.resolve(session_key, confirm_id, choice)`; typed replies are intercepted at `gateway/run.py:18489` — `/approve|yes|ok|confirm` → `"once"`, `/always|remember` → `"always"`, `/cancel|no|deny|nevermind` → `"cancel"`, and the bare (non-slash) words after `lstrip("!/")`: `approve`, `approve once`, `once` → once; `always`, `always approve` → always; `cancel`, `nevermind`, `no` → cancel.
- **Inputs / options:** three button choices; six+ typed spellings per choice; `!`-prefixed variants.
- **Outputs / side effects:** runs the registered handler on the event loop and sends its return value; `clear_if_stale()` drops a >300 s pending confirm when an unrelated command arrives.
- **Config / env:** `approvals.mcp_reload_confirm` (default true), `approvals.destructive_slash_confirm` (default true).
- **Edge cases / guards:** if a **tool** approval is live (`tools.approval.has_blocking_approval`) it takes precedence and `/approve` unblocks the tool thread instead (`run.py:18494`). A newer confirm on the same session overwrites the older one; a mismatched `confirm_id` resolves to `None`.
- **Rebuild notes:** register-then-send, id-scoped, TTL'd, with a typed fallback vocabulary; render the fallback with the platform's typed prefix.

### Destructive-command confirmation (`/new`, `/reset`, `/undo`)  `id: gw-slash.destructive-confirm`
- **Surface:** Gateway/Telegram | Config
- **Where:** the prompt bubble before a `/new`, `/reset` or `/undo` actually runs.
- **What it does:** guards commands that discard conversation state, with a persistent opt-out.
- **How it works:** `_maybe_confirm_destructive_slash(event, command, title, detail, execute)` (`gateway/run.py:25485`). Reads `approvals.destructive_slash_confirm` from `self._read_user_config()`; when false it awaits `execute()` immediately. Otherwise it builds the prompt and routes through `_request_slash_confirm`. Choice handling: `cancel` → `` 🟡 /<command> cancelled. Conversation unchanged. ``; `once` → run; `always` → `save_config_value("approvals.destructive_slash_confirm", False)` then run, appending either `\n\nℹ️ Future /clear, /new, /reset, and /undo will run without confirmation. Re-enable via `approvals.destructive_slash_confirm: true` in config.yaml.` on a successful write, or `\n\n⚠️ Could not save that preference (config.yaml is not writable), so /clear, /new, /reset, and /undo will ask again next time. To silence it permanently, set `approvals.destructive_slash_confirm: false` in config.yaml.` when the write failed (the note is only appended to plain-string results; `EphemeralReply` results are left untouched).
- **Inputs / options:** prompt body (verbatim):
  `⚠️ **Confirm /<command>**` / blank / `<detail>` / blank / `Choose:` / `• **Approve Once** — proceed this time only` / `• **Always Approve** — proceed and silence this prompt permanently` / `• **Cancel** — keep current conversation` / blank / ``_Text fallback: reply `<p>approve`, `<p>always`, or `<p>cancel`._`` where `<p>` is the platform's typed prefix. Details used: `/new` → `"This starts a fresh session and discards the current conversation history."` (`run.py:19001`); `/undo` (N=1) → `"This removes the last user/assistant exchange from history."`, (N>1) → `"This removes the last <N> user turns from history."` (`run.py:19181`).
- **Outputs / side effects:** may persist `approvals.destructive_slash_confirm: false`; log lines `User opted out of destructive slash confirm (session=%s)` / `Could not persist destructive_slash_confirm=false (session=%s); config.yaml is not writable`.
- **Config / env:** `approvals.destructive_slash_confirm` (bool, default `true`).
- **Edge cases / guards:** the docs describe an inline skip (`now`, `--yes`, `-y`) for the **CLI**; the gateway path has no such parsing — `/new --yes foo` would set the title to `--yes foo` (discrepancy, see `gw-slash.docs-reconciliation`).
- **Rebuild notes:** a generic `confirm(destructive_action)` wrapper keyed by one config flag; report honestly when the opt-out could not be persisted (this implementation does).

### EphemeralReply (self-deleting system notices)  `id: gw-slash.ephemeral-reply`
- **Surface:** Gateway/Telegram
- **Where:** the reply bubbles for `/new`/`/reset`, `/stop`, `/yolo`, `/busy`, `/restart` — they disappear after a TTL on platforms that support message deletion.
- **What it does:** marks a slash reply as a transient system notice so it doesn't clutter the transcript.
- **How it works:** `class EphemeralReply(str)` (`gateway/platforms/base.py:2764`) subclasses `str` with an extra `ttl_seconds` attribute, so all existing string handling keeps working; the send path checks `isinstance(r, EphemeralReply)` and schedules `delete_message` after the TTL. `ttl_seconds=None` uses `display.ephemeral_system_ttl`; a configured `0` disables deletion globally.
- **Inputs / options:** `EphemeralReply(text, ttl_seconds=None)`.
- **Outputs / side effects:** a scheduled message deletion.
- **Config / env:** `display.ephemeral_system_ttl`.
- **Edge cases / guards:** platforms without `delete_message` ignore the TTL silently.
- **Rebuild notes:** subclassing `str` is the cheap trick that keeps the whole return-type contract unchanged; keep it.

### Emergency-stop pass-through for slash commands  `id: gw-slash.estop-gate`
- **Surface:** Gateway/Telegram
- **Where:** while `/pause` is engaged, ordinary messages get the paused notice but slash commands still work.
- **What it does:** guarantees a messaging-only operator can always lift a global pause from chat.
- **How it works:** `gateway/run.py:18270`+ — before the paused notice is returned, `_estop_allow` is set true when `resolve_command(event.get_command())` is not None, or the session has `update_prompt_pending`, or the session is running (so steering/interrupting still works), or `tools.slash_confirm.get_pending(key)` exists, or `tools.approval.has_blocking_approval(key)` is true. Otherwise it logs `Gateway turn paused by global emergency stop (platform=%s chat=%s)` and returns the paused notice.
- **Inputs / options:** n/a.
- **Outputs / side effects:** none.
- **Config / env:** e-stop state lives in `agent.estop`.
- **Edge cases / guards:** unrecognised text is still blocked; only *recognised* commands pass.
- **Rebuild notes:** never let a kill-switch lock out its own off-switch.

### Plain-text `restart gateway` coercion  `id: gw-slash.plaintext-restart`
- **Surface:** Gateway/Telegram
- **Where:** typing `restart gateway`, `please restart the gateway`, `restart the hermes gateway`, `restart hermes` (with optional trailing `.`/`!`/`?`) in a **DM**.
- **What it does:** rewrites a small set of admin phrases into `/restart` so they don't reach the LLM (which would restart the gateway from inside the very agent being drained).
- **How it works:** `coerce_plaintext_gateway_command(event)` (`gateway/platforms/base.py:2557`) matches `_PLAINTEXT_GATEWAY_RESTART_PATTERNS` (`base.py:2549`): `^(?:please\s+)?restart\s+(?:the\s+)?gateway[.!?\s]*$`, `^(?:please\s+)?restart\s+(?:the\s+)?hermes\s+gateway[.!?\s]*$`, `^(?:please\s+)?restart\s+hermes[.!?\s]*$` — all case-insensitive. Only for `MessageType.TEXT`, only when the text does not already start with `/`, and only when `source.chat_type == "dm"`.
- **Inputs / options:** the three phrase families above.
- **Outputs / side effects:** sets `event.text = "/restart"`.
- **Config / env:** n/a.
- **Edge cases / guards:** group chats keep natural-language semantics deliberately.
- **Rebuild notes:** keep the phrase list tiny and DM-only; anything broader is a footgun.

### User-defined quick commands (`type: exec` / `type: alias`)  `id: gw-slash.quick-commands`
- **Surface:** Config | Gateway/Telegram
- **Where:** `~/.hermes/config.yaml` → `quick_commands:` ; then typed as `/status`, `/deploy`, `/inbox` in any chat.
- **What it does:** maps a short slash name to either a shell command executed in the gateway process, or to another slash command with arguments prepended.
- **How it works:** two touch points in `gateway/run.py`. **Pre-expansion** (`:18866`) runs only when `resolve_command()` missed and the entry is `type: alias`: `target` is normalised to start with `/`, `event.text = f"{target} {user_args}".strip()`, then re-resolved so `/inbox unread` reaches `/gmail unread`'s handler. **Main handling** (`:19326`) re-applies `_check_slash_access(source, command)` on the raw typed name (#44727), then: `type: exec` → `asyncio.create_subprocess_shell(exec_cmd, env=build_subprocess_env())` (from `tools.environments.local`, a sanitised env so API keys are not leaked), `await asyncio.wait_for(proc.communicate(), timeout=30)`, output = `(stdout or stderr).decode().strip()` passed through `agent.redact.redact_sensitive_text`. `type: alias` with a target rewrites `event.text` and falls through.
- **Inputs / options:** per entry — `type` (`exec` | `alias`), `command` (for exec), `target` (for alias). Example from the docs:
  ```yaml
  quick_commands:
    status:  {type: exec,  command: systemctl status hermes-agent}
    deploy:  {type: exec,  command: scripts/deploy.sh}
    inbox:   {type: alias, target: /gmail unread}
  ```
- **Outputs / side effects:** runs an arbitrary shell command as the gateway user; replies with its output or `Command returned no output.`
- **Config / env:** `quick_commands.*`; env is sanitised via `build_subprocess_env()`.
- **Edge cases / guards:** built-ins always win, so a quick command named `status` is unreachable in chat (the registry's `/status` runs); 30 s timeout → `Quick command timed out (30s).`; exceptions → `Quick command error: <e>`; missing command → `` Quick command '/<name>' has no command defined. ``; missing target → `` Quick command '/<name>' has no target defined. ``; wrong type → `` Quick command '/<name>' has unsupported type (supported: 'exec', 'alias'). ``. Docs note string-only prompt shortcuts are NOT supported.
- **Rebuild notes:** sanitise the subprocess environment, redact output, cap runtime, and apply the same permission gate you apply to built-ins.

### Plugin-registered slash commands  `id: gw-slash.plugin-commands`
- **Surface:** Gateway/Telegram | Tool
- **Where:** any `/name` a plugin registered via `PluginContext.register_command`; they show up in the Telegram menu, in Slack's `/hermes <sub>` map and in Discord's slash picker.
- **What it does:** lets a plugin own a slash command on every chat platform.
- **How it works:** `_iter_plugin_command_entries()` (`hermes_cli/commands.py:687`) lazily imports `hermes_cli.plugins.get_plugin_commands()` and yields `(name, description, args_hint)`. Dispatch: `gateway/run.py:19381` calls `get_plugin_command_handler(command.replace("_","-"))` — the underscore→hyphen normalisation exists so Telegram's underscored autocomplete form resolves — then `result = plugin_handler(user_args)`, awaits it if it is a coroutine, and returns `str(result)` or `None`.
- **Inputs / options:** the raw argument string; the plugin's own `args_hint` and `description`.
- **Outputs / side effects:** whatever the plugin does; failures log `Plugin command dispatch failed: %s` and fall through.
- **Config / env:** plugin config (sibling shard).
- **Edge cases / guards:** plugin commands that *require* arguments (`args_hint` starting with `<`) are excluded from Telegram's `setMyCommands` menu (`commands.py:663` `_requires_argument`, used at `:751`) because plugins may not have a no-arg usage fallback; built-ins with required args ARE included (issue #24312) because their handlers print usage.
- **Rebuild notes:** lazy plugin discovery (never at import time), name normalisation at the lookup boundary, and menu exclusion for arg-required third-party commands.

### Skill slash commands (`/<skill-name>`)  `id: gw-slash.skill-commands`
- **Surface:** Skill | Gateway/Telegram
- **Where:** typing `/gif-search`, `/github-pr-workflow`, `/excalidraw`, `/claude_code` (Telegram underscore form) etc. in chat; listed under `⚡ **Skill Commands** (<n> active):` in `/help` and `⚡ **Skill Commands**:` in `/commands`.
- **What it does:** loads the full SKILL.md body into the next user turn so the model follows that skill's instructions, optionally with the text the user typed after the command.
- **How it works:** `agent/skill_commands.py`. `scan_skill_commands()` (`:427`) walks project skill dirs → `SKILLS_DIR` (`~/.hermes/skills`) → external dirs, reads each `SKILL.md` frontmatter, skips `.git/.github/.hub/.archive` paths, skips skills failing `skill_matches_platform` / `skill_matches_environment`, skips names in the disabled list, derives the slug (`name.lower()` → spaces/underscores→`-` → strip chars outside `[a-z0-9-]` → collapse `--` → strip `-`), and **skips any slug that `resolve_command()` resolves to a core command**. First-wins dedup on the slug. Results are published under `_publish_lock` together with the platform and home tags. `get_skill_commands()` rescans when the active platform (#14536) or profile home (#88023) changes. `resolve_skill_command_key(command)` (`:645`) looks up `"/" + command.replace("_","-")`. Dispatch at `gateway/run.py:19430`: per-platform disabled re-check, then `build_skill_invocation_message(cmd_key, user_instruction, task_id=session_key)` (`skill_commands.py:664`) which loads the payload, bumps `tools.skill_usage.bump_use` for the Curator, and builds the message via `_build_skill_message` (`:311`).
- **Inputs / options:** `/<slug> [free-text instruction]`; hyphen and underscore spellings both resolve.
- **Outputs / side effects:** rewrites `event.text` to the scaffolded message and falls through to the normal agent turn. Scaffold shape: activation note `[IMPORTANT: The user has invoked the "<name>" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]`, blank line, the skill body (with `template_vars` substitution and optional `inline_shell` expansion), `[Skill directory: <abs path>]` plus the "Resolve any relative paths…" instruction, injected skill config values, optional `[Skill setup note: …]`, a supporting-files list with a `skill_view(name=…, file_path=…)` hint, then `The user has provided the following instruction alongside the skill invocation: <text>` and an optional `[Runtime note: …]`. A stable-prefix cache breakpoint is registered before the volatile instruction (#81867).
- **Config / env:** `skills.disabled`, `skills.platform_disabled`, `skills.external_dirs`, `skills.template_vars` (default true), `skills.inline_shell` (default false), `skills.inline_shell_timeout` (default 10).
- **Edge cases / guards:** a skill disabled for this platform replies `` The **<name>** skill is disabled for <platform>.\nEnable it with: `hermes skills config` ``; a slug colliding with a core command is never registered (log: *"…collides with a core Hermes command; skipping auto-registration. Use '/skill <name>' instead."*); a duplicate slug logs *"…already claimed by %r; keeping the first and skipping this one."*
- **Rebuild notes:** scan → slug → collision-check against the core registry → publish atomically; keep the user's own instruction recoverable from the scaffold (see `extract_user_instruction_from_skill_message`, `:97`) so memory providers don't store the whole skill body.

### Stacked skill invocations (`/a /b do XYZ`)  `id: gw-slash.stacked-skills`
- **Surface:** Skill | Gateway/Telegram
- **Where:** typing several skill commands in a row: `/writing-style /code-review look at PR 12`.
- **What it does:** loads every leading skill (up to 5) rather than only the first.
- **How it works:** `split_stacked_skill_commands(rest)` (`agent/skill_commands.py:728`) consumes leading `/`-tokens that resolve via `resolve_skill_command_key`, stopping at the first non-skill token, capped by `_MAX_STACKED_SKILLS = 5` (so at most 4 extra keys). `build_stacked_skill_invocation_message([first,*extra], instruction, task_id)` (`:760`) reuses the **bundle** scaffolding markers so instruction extraction keeps working. Gateway wiring at `gateway/run.py:19461`–`19511`, including a per-platform disabled re-check over every stacked key.
- **Inputs / options:** up to 5 leading skill commands, then free text.
- **Outputs / side effects:** rewrites `event.text` with the combined scaffold; on failure returns `` Failed to load stacked skills for /<command>. ``
- **Config / env:** as `gw-slash.skill-commands`.
- **Edge cases / guards:** disabled stacked skills reply `` The **<a, b>** skill(s) in this stacked invocation are disabled for <platform>.\nEnable them with: `hermes skills config` ``; duplicate keys stop the scan. Inspired by Claude Code v2.1.199.
- **Rebuild notes:** greedy leading-token consumption with a hard cap, and reuse of the bundle markers so downstream extraction needs no new plumbing.

### Skill bundles (`/<bundle-slug>`)  `id: gw-slash.bundle-commands`
- **Surface:** Skill | Gateway/Telegram
- **Where:** typing a bundle's slug in chat; listed by `/bundles`.
- **What it does:** loads several skills at once under one slash alias.
- **How it works:** dispatched **before** individual skills (`gateway/run.py:19400`). `resolve_bundle_command_key(command)` then `build_bundle_invocation_message(bundle_key, user_instruction, task_id=session_key, platform=<source platform>)` — the platform is passed explicitly because bundle loading bypasses the scan-time disabled filter and one gateway process serves many platforms (#58888). Missing skills are logged (`Bundle %s skipped missing skills: %s`) but do not fail the load.
- **Inputs / options:** `/<bundle-slug> [instruction]`.
- **Outputs / side effects:** `event.text` becomes the bundle scaffold and falls through to the agent.
- **Config / env:** `bundles:` in `~/.hermes/config.yaml`; bundle files under the bundles dir reported by `/bundles`.
- **Edge cases / guards:** bundle dispatch failures log `Bundle dispatch failed: %s` and fall through to individual skill lookup.
- **Rebuild notes:** bundles must outrank single skills so a bundle can share a name with one of its members.

### Telegram command menu (`setMyCommands`)  `id: gw-slash.telegram-menu`
- **Surface:** Platform:telegram
- **Where:** the `/` autocomplete menu inside a Telegram chat with the bot.
- **What it does:** publishes a capped, prioritised list of commands (built-ins + plugins + skills) to Telegram.
- **How it works:** `telegram_bot_commands(include_plugins=True)` (`hermes_cli/commands.py:719`) emits every gateway-available `CommandDef` (name sanitised) plus plugin commands that do not require arguments. `telegram_menu_commands(max_commands)` (`:1157`) merges core + plugin + skill candidates, orders them via `_prioritize_telegram_menu_candidates` (`:892`) and truncates, returning `(menu, hidden_count)`. Name sanitisation `_sanitize_telegram_name` (`:952`): lowercase → `-`→`_` → strip anything outside `[a-z0-9_]` → collapse `__` → strip leading/trailing `_`, max 32 chars via `_clamp_command_names` (`:966`) which on truncation collision appends digits `0`–`9` and drops the entry if all ten are taken.
- **Inputs / options:** `platforms.telegram.extra.command_menu.max_commands` (default 60, clamped 1…100), `.priority_mode` (`prepend` default | `append` | `replace`), `.priority` (list or single string of command names). Built-in default priority list `_TELEGRAM_MENU_PRIORITY` (`:764`), in order: `help, new, stop, status, egress, resume, sessions, model, debug, restart, update, verbose, commands, approve, deny, queue, steer, bg, btw, reasoning, usage, platforms, platform, profile, whoami`.
- **Outputs / side effects:** the visible Telegram menu; `hidden_count` reports how many were cut.
- **Config / env:** the three `command_menu` keys above.
- **Edge cases / guards:** Telegram's hard API limit is 100 (`_TELEGRAM_BOT_API_MAX_COMMANDS`); user-installed hub skills are excluded (reachable via `/skills`); skills disabled for `"telegram"` are excluded entirely; priority tiers are core > plugin > skill unless overridden.
- **Rebuild notes:** derive the menu from the registry, make the cap and priority configurable, and report the hidden count instead of silently truncating.

### Slack native slash commands and `/hermes <subcommand>`  `id: gw-slash.slack-slashes`
- **Surface:** Platform:slack
- **Where:** Slack's slash picker (`/stop`, `/model`, `/btw`, …) and the catch-all `/hermes` with description `Talk to Hermes or run a subcommand` and usage hint `[subcommand] [args]`.
- **What it does:** projects the registry onto Slack's 50-slash-command cap, with `/hermes <verb>` as the universal fallback.
- **How it works:** `slack_native_slashes()` (`hermes_cli/commands.py:1496`) reserves `hermes` first, then adds (1) `_SLACK_PRIORITY_ALIASES` (currently empty), (2) canonical names, (3) aliases (described as `Alias for /<name> — <description>`), (4) plugin commands — each through `_add()` which sanitises via `_sanitize_slack_name` (`:1484`, lowercase, strip anything outside `[a-z0-9_-]`, trim `-_`, 32 chars), skips duplicates, skips `_SLACK_RESERVED_COMMANDS`, skips `_SLACK_VIA_HERMES_ONLY`, and stops at `_SLACK_MAX_SLASH_COMMANDS = 50`; descriptions clamp to 140 chars, hints to 100. `slack_app_manifest(request_url)` (`:1577`) renders the `features.slash_commands` block. `slack_subcommand_map()` (`:1604`) maps every canonical name and alias (plus plugin names) to `/<name>` for the `/hermes` handler.
- **Inputs / options:** `_SLACK_RESERVED_COMMANDS` (Slack built-ins that can never be registered): `me, status, away, dnd, shrug, remind, msg, feed, who, collapse, expand, leave, join, open, search, topic, mute, pro, shortcuts`. `_SLACK_VIA_HERMES_ONLY` (deliberately demoted to `/hermes <cmd>`): `topup, moa, debug, egress, init, version, diff, update, heartbeat, refine, review, pause, whoami, platform, insights`.
- **Outputs / side effects:** the Slack app manifest / registered slash list.
- **Config / env:** n/a beyond Slack app setup.
- **Edge cases / guards:** because `/status` and `/topic` are Slack built-ins, they are ONLY reachable as `/hermes status` / `/hermes topic` (or `!status` in a thread). The docs' per-command notes ("On Slack use `/hermes heartbeat …`") match `_SLACK_VIA_HERMES_ONLY`.
- **Rebuild notes:** reserve a namespace command first, pin high-value aliases, and keep an explicit demotion list so a new command can never silently clamp an existing one off the cap.

### Discord slash registration for skills  `id: gw-slash.discord-skill-slashes`
- **Surface:** Platform:discord
- **Where:** Discord's native `/` picker and the `/skill` autocomplete dropdown.
- **What it does:** registers built-in commands plus as many skill commands as fit in Discord's 100-command budget.
- **How it works:** `discord_skill_commands(max_slots, reserved_names)` (`hermes_cli/commands.py:1199`) reuses `_collect_gateway_skill_entries(platform="discord", desc_limit=100)` — same plugin>skill priority, hub exclusion and per-platform disabled filtering as Telegram, but hyphens are preserved (no `-`→`_`). `discord_skill_commands_by_category(reserved_names)` (`:1232`) groups skills nested ≥2 levels under a scan root by their top-level category for the `/skill` autocomplete. `/reload-skills` calls each adapter's `refresh_skill_group()` so the dropdown refreshes without a restart (`gateway/slash_commands.py:5986`).
- **Inputs / options:** `max_slots` = 100 − built-ins; `reserved_names`.
- **Outputs / side effects:** `(entries, hidden_count)`; entries are `(discord_name, description, cmd_key)`.
- **Config / env:** `skills.platform_disabled` for `discord`.
- **Edge cases / guards:** the adapter's own registration code lives in `plugins/platforms/discord/adapter.py` (`_register_slash_commands`) — see Handoffs.
- **Rebuild notes:** one shared skill-collection helper with per-platform name/description constraints injected.

### Telegram command-mention rewriting in help text  `id: gw-slash.telegramize-mentions`
- **Surface:** Platform:telegram
- **Where:** the bodies of `/help` and `/commands` on Telegram — `/reload-mcp` renders as `/reload_mcp`, `/codex-runtime` as `/codex_runtime`, so the mention stays tappable.
- **What it does:** rewrites slash mentions inside outgoing help text into Telegram-valid command names.
- **How it works:** `_telegramize_command_mentions(text, platform)` (`gateway/run.py:1257`) short-circuits unless `platform.value == "telegram"`, then `re.sub(_TELEGRAM_COMMAND_MENTION_RE, …)` applying `_sanitize_telegram_name` to each capture; an empty sanitisation leaves the original text. Applied in `_handle_help_command` (`gateway/slash_commands.py:1725`) and `_handle_commands_command` (`:1737`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** display-only.
- **Config / env:** n/a.
- **Edge cases / guards:** other platforms are byte-identical to the canonical text.
- **Rebuild notes:** decorate at the surface, never in the shared executor (that's the `slash_exec` invariant).

---

## 2. Session lifecycle commands

### `/start`  `id: gw-slash.start`
- **Surface:** Gateway/Telegram
- **Where:** sent automatically by Telegram/Discord the first time a user opens the bot conversation (deep links included); also typable by hand.
- **What it does:** acknowledges a platform handshake ping silently — no reply, no session burn, no agent interrupt.
- **How it works:** registry entry `CommandDef("start", "Acknowledge platform start pings without a reply", "Session", gateway_only=True, busy_policy="dispatch", busy_handler="start")` (`hermes_cli/commands.py:149`). Cold path: `gateway/run.py:19011` logs `Ignoring /start platform ping for session %s` and returns `""`. Busy path: `_busy_start_command` (`gateway/run.py:17879`) logs `Ignoring /start platform ping for active session %s` and returns `""`.
- **Inputs / options:** none (arguments are ignored, including Telegram deep-link payloads).
- **Outputs / side effects:** an empty string, i.e. nothing is sent.
- **Config / env:** n/a.
- **Edge cases / guards:** gateway-only (never in the CLI); explicitly mid-run safe so a re-open during a turn cannot dump help or interrupt.
- **Rebuild notes:** treat protocol pings as no-ops with an explicit empty reply; do not let them create sessions.

### `/new` (alias `/reset`)  `id: gw-slash.new`
- **Surface:** Gateway/Telegram
- **Where:** any chat. Reply headers: `✨ Session reset! Starting fresh.` / `✨ New session started!` / `✨ New session started: <title>`.
- **What it does:** ends the current conversation and starts a fresh session id with empty history; an optional argument becomes the new session's title.
- **How it works:** registry: `CommandDef("new", …, aliases=("reset",), args_hint="[name]", busy_policy="interrupt_then_dispatch", busy_handler="new")` (`commands.py:151`). Mid-run: `_busy_new_command` (`gateway/run.py:17896`) interrupts and clears the session with `interrupt_reason=_INTERRUPT_REASON_RESET`, `invalidation_reason="new_command"` (so the stale `/reset` text isn't replayed as user input, #2170), then calls the handler. Cold path (`run.py:18994`) first checks `_is_telegram_topic_root_lobby` then wraps the handler in `_maybe_confirm_destructive_slash`. `_handle_reset_command` (`gateway/slash_commands.py:144`) then: invalidates the run generation (`reason="session_reset"`), releases the running-agent slot (#28686), snapshots the old entry, off-loads `_cleanup_agent_resources` to a worker thread with `_RESET_CLEANUP_TIMEOUT_S = 30.0` (#35994) and proceeds even on timeout, evicts the cached agent, calls `_clear_conversation_scope(reason="session_reset")` (model/reasoning overrides, one-turn restores, model notes, last-resolved cache, `/queue` overflow, security state), interrupts in-flight async delegations via `tools.async_delegation.interrupt_for_session(session_key, parent_session_id, reason="session_reset")` (#55578), clears env-passthrough and credential files, `reset_session(session_key)`, fires `on_session_finalize` off-loop, emits the `session:end` and `session:reset` hooks, resolves `_reset_notice_session_info(source)`, invokes `on_session_reset`, rebinds a Telegram DM topic binding when in a topic lane, and appends a random tip.
- **Inputs / options:** `[name]` — free text title, sanitised by `SessionDB.sanitize_title`.
- **Outputs / side effects:** new session row; `EphemeralReply(header + "\n\n" + session_info + tip)` or `EphemeralReply(header + tip)`. Title notes: `\n⚠️ Title rejected: <error>`, `\n⚠️ <error> — session started untitled.`, `\n⚠️ Title is empty after cleanup — session started untitled.` Tip line: `\n✦ Tip: <tip>` from `hermes_cli.tips.get_random_tip`.
- **Config / env:** `approvals.destructive_slash_confirm`.
- **Edge cases / guards:** inside a Telegram DM topic root ("All Messages" lobby) it instead returns the lobby guidance (`gw-slash.topic`); inside a topic lane the header comes from `_telegram_topic_new_header`, which appends the "for parallel work, open All Messages…" tip.
- **Rebuild notes:** a session reset must be a *funnel* — one call that clears every per-conversation cache, kills child work, rotates the id, and fires lifecycle hooks; anything left behind becomes a zombie.

### `/topic`  `id: gw-slash.topic`
- **Surface:** Platform:telegram
- **Where:** Telegram **private chats only**. `/topic`, `/topic off`, `/topic help`, `/topic <session-id>`.
- **What it does:** enables (or inspects/disables) user-managed multi-session topic mode, where each Telegram forum topic in the DM is an independent Hermes session; with a session id inside a topic it restores that session into the topic.
- **How it works:** `_handle_topic_command` (`gateway/slash_commands.py:4909`). Rejects non-Telegram/non-DM with `The /topic command is only available in Telegram private chats.`; requires `self._session_db` else `format_session_db_unavailable(prefix="Session database not available")`; re-checks `_is_user_authorized(source)` (defence in depth) → `You are not authorized to use /topic on this bot.`. `help|?|-h|--help` → `_telegram_topic_help_text()`. `off|disable|stop` → `_disable_telegram_topic_mode_for_chat(source)`. Any other argument requires `source.thread_id`, else `To restore a session, first create or open a Telegram topic, then send /topic <session-id> inside that topic. To create a new topic, open All Messages and send any message there.`; with a thread it calls `_restore_telegram_topic_session(event, args)`. Bare `/topic` probes `_get_telegram_topic_capabilities(source)` and, when topics are off or user-creation is disallowed, sends a BotFather setup screenshot (debounced by `_should_send_telegram_capability_hint`) plus the matching message; otherwise `session_db.enable_telegram_topic_mode(chat_id, user_id, has_topics_enabled, allows_users_to_create_topics)`, ensures the system topic, and reports binding state.
- **Inputs / options:** `off` | `disable` | `stop`; `help` | `?` | `-h` | `--help`; `<session-id>`; bare.
- **Outputs / side effects:** writes topic-mode rows and per-thread bindings into `state.db`; may send an image. Replies (verbatim): topics disabled — `Telegram topics are not enabled for this bot yet.\n\nHow to enable them:\n1. Open @BotFather.\n2. Choose your bot.\n3. Open Bot Settings → Threads Settings.\n4. Turn on Threaded Mode and make sure users are allowed to create new threads.\n\nThen send /topic again.`; users disallowed — `Telegram topics are enabled, but users are not allowed to create topics.\n\nOpen @BotFather → choose your bot → Bot Settings → Threads Settings, then turn off 'Disallow users to create new threads'.\n\nThen send /topic again.`; enable failure — `Failed to enable Telegram topic mode: <error>`; bound topic — `This topic is linked to:\nSession: <label>\nID: <session_id>\n\nUse /new to replace this topic with a fresh session.\nFor parallel work, open All Messages and send a message there to create another topic.` (label falls back to `Untitled session`); fresh topic — `Telegram multi-session topics are enabled.\n\nThis topic will be used as an independent Hermes session. Use /new to replace this topic's current session. For parallel work, open All Messages and send a message there to create another topic.`
- **Config / env:** Telegram BotFather Threads Settings; session DB.
- **Edge cases / guards:** in the topic root ("lobby"), ordinary messages get `This main chat is reserved for system commands.\n\nTo start a new Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for that message; each topic works as an independent Hermes session.` (`gateway/run.py:8496`, debounced by `_TELEGRAM_LOBBY_REMINDER_COOLDOWN_S`), and `/new` there gets `To start a new parallel Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for it.\n\nEach topic is an independent Hermes session. Use /new inside an existing topic only if you want to replace that topic's current session.` (`run.py:8505`).
- **Rebuild notes:** bind (chat_id, thread_id) → session_id in a side table, rewrite the binding on `/new`, and probe the platform's capabilities before promising the feature.

### `/save`  `id: gw-slash.save`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/save`, `/save md`, `/save html notes.html`, `/save json export.json redact`.
- **What it does:** exports the current conversation to a file and sends it back as a document attachment.
- **How it works:** `_handle_save_command` (`gateway/slash_commands.py:4998`). Bare `/save` returns `SAVE_USAGE` from `hermes_cli/session_export.py`. A trailing `redact` / `--redact` token sets `redact=True` and is stripped. `normalize_save_format(parts[0])` validates the format (ValueError → `<e>\n\n<SAVE_USAGE>`). Filename = `parts[1]` or `default_save_filename(session_id, fmt)`, then forced through `os.path.basename()` (chat input is never trusted with path separators). `export_session(session_id)` (async DB); optional `redact_session_data`. Rendering + write happen in one `asyncio.to_thread` hop (multi-MB transcripts must not stall the loop). The file is written into `tempfile.mkdtemp(prefix="hermes_save_")` and sent via `adapter.send_document(chat_id, file_path, caption=f"Session export: {filename}", file_name=filename)`; the temp file and dir are removed in `finally`.
- **Inputs / options:** `<json|md|html>` (required), `[filename]`, `[redact|--redact]` (must be last).
- **Outputs / side effects:** a document in the chat; replies `Export complete.` / `Platform adapter not found to send the document.` / `No stored messages found for this session (<session_id>).` / `Session database not available.` / `Error exporting session: <e>` (logged as `Session /save failed: %s`).
- **Config / env:** n/a.
- **Edge cases / guards:** path traversal blocked by `basename`; empty basename falls back to the default name.
- **Rebuild notes:** render off-loop, sanitise the filename, always clean up the temp dir, and offer redaction as an opt-in token.

### `/retry`  `id: gw-slash.retry`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** removes the last real user turn from the transcript and re-sends its text to the agent.
- **How it works:** `_handle_retry_command` (`gateway/slash_commands.py:2644`). Loads the transcript, then scans backwards for the last message where `user_originated_turn_view(msg)` is not None — this filter exists because bookkeeping rows carry `role=user` with `display_kind ∈ {model_switch, async_delegation_complete, auto_continue, hidden}` and must never be retried. `history_before_user_originated_turn` + `retryable_user_text` + `split_user_originated_turn` (all from `agent/context_compressor.py`) resolve the live text and the scaffold prefix. If the row is a composite compaction carrier it uses `rewind_session(session_id, 1, require_retryable_composite=True)`; otherwise `rewrite_transcript(session_id, truncated, active_only=True, reject_active_turn_lease=True)`. `session_entry.last_prompt_tokens = 0`. Finally it builds a synthetic `MessageEvent(text=last_user_msg, message_type=TEXT, source, raw_message, channel_prompt)` and re-enters `_handle_message`.
- **Inputs / options:** none.
- **Outputs / side effects:** the transcript loses the last user turn (rows kept as `active=0`); the agent runs again. Errors: `No previous message to retry.` / `Cannot retry that message safely: <exc>` / `Retry failed; transcript was not changed.`
- **Config / env:** n/a.
- **Edge cases / guards:** media/unknown content is rejected rather than truncating the session; an active turn lease blocks the rewrite.
- **Rebuild notes:** define a canonical "user-originated turn" projection and retry only through it; never rewrite the transcript before you know the retry can succeed.

### `/undo [N]`  `id: gw-slash.undo`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/undo`, `/undo 3`.
- **What it does:** backs the conversation up by N user turns (default 1) and echoes the removed prompt so the user can edit and resend it.
- **How it works:** cold path at `gateway/run.py:19174` parses N (`max(1, int(first_token))`, non-numeric → 1) purely to build the confirm detail, then routes through `_maybe_confirm_destructive_slash`. `_handle_undo_command` (`gateway/slash_commands.py:3225`) re-parses: non-integer first token → `Invalid count "<arg>" — use /undo or /undo N.`; `n < 1` → 1. `rewind_session(session_id, n)` soft-deletes the rows (`active=0`, kept for audit and hidden from re-prompts/search), resets `last_prompt_tokens`, and evicts the cached agent via `build_session_key(source)` so the next turn rebuilds from the active-only transcript.
- **Inputs / options:** `[N]` integer.
- **Outputs / side effects:** `↩️ Undid <turns> turn(s) (<count> message(s)).\nBacked up to: "<preview>"\nCopy/edit the text above and send it to re-prompt from here.` (preview truncated at 200 chars + `...`); nothing to undo → `Nothing to undo.`
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.undo.removed` (`locales/en.yaml:391` → emitted at `gateway/slash_commands.py:3268`) — `rewind_session(session_id, n)` returned a result — `turns` is `result["turns_undone"]`, `count` is `result["rewound_count"]`, `preview` is `result["target_text"]` truncated at 200 chars with `...`; the echoed prompt is what makes the undo hand-reversible:

    ```text
    ↩️ Undid {turns} turn(s) ({count} message(s)).
    Backed up to: "{preview}"
    Copy/edit the text above and send it to re-prompt from here.
    ```
- **Config / env:** `approvals.destructive_slash_confirm`.
- **Edge cases / guards:** the destructive confirm wraps it; cached-agent eviction failures are logged only (`undo: cached-agent eviction skipped: %s`).
- **Rebuild notes:** soft-delete rather than delete, echo the text back so the undo is reversible by hand, and invalidate the agent cache.

### `/title [name]`  `id: gw-slash.title`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/title`, `/title My Session Name`.
- **What it does:** sets or shows the current session's title (used by `/resume` and `/sessions`).
- **How it works:** `_handle_title_command` (`gateway/slash_commands.py:5083`). Requires `_session_db`. If `get_session_title()` returns None it first `create_session(session_id, source=<platform>, user_id, chat_id, chat_type, thread_id)` so a later `/resume` can prove ownership (IDOR scoping). With an argument: `SessionDB.sanitize_title(title_arg)` (ValueError → `⚠️ <error>`), empty result → `⚠️ Title is empty after cleanup. Please use printable characters.`, then `set_session_title`. On success it also calls `_schedule_telegram_topic_title_rename(source, session_id, sanitized)` off-thread so a Telegram forum topic gets the user's chosen name.
- **Inputs / options:** `[name]` free text.
- **Outputs / side effects:** DB title + possibly a Telegram topic rename. Replies: `✏️ Session title set: **<title>**`; `Session not found in database.`; bare form → `📌 Session: `<session_id>`\nTitle: **<title>**` or `📌 Session: `<session_id>`\nNo title set. Usage: `/title My Session Name``; DB missing → `Session database not available.`
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.title.current_no_title` (`locales/en.yaml:375` → emitted at `gateway/slash_commands.py:5153`) — bare `/title` on a session whose DB row has no title — prints the session id and the usage line (the titled counterpart is `gateway.title.current_with_title`):

    ```text
    📌 Session: `{session_id}`
    No title set. Usage: `/title My Session Name`
    ```
- **Config / env:** Telegram topic auto-rename setting (adapter-side).
- **Edge cases / guards:** `create_session` failures are swallowed ("might already exist").
- **Rebuild notes:** persist chat/thread origin at title time — that row is what later authorises resume.

### `/branch [name]` (alias `/fork`)  `id: gw-slash.branch`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/branch`, `/branch experiment-2`, `/fork`.
- **What it does:** copies the current conversation into a new session and switches to it, so a different path can be explored without losing the original.
- **How it works:** `_handle_branch_command` (`gateway/slash_commands.py:5394`). New id = `f"{now:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"`. Title = the argument, else `get_next_title_in_lineage(current_title or "branch")`. `create_session(...)` forwards **all** routing columns at CREATE time (`user_id, session_key, chat_id, chat_type, thread_id, origin_json, display_name`) plus `parent_session_id` and `model_config={"_branched_from": parent}` so the branch stays visible in `/resume` / `/sessions` even after the parent is re-ended. History is copied with `append_messages_batch(new_id, [...], chunk_rows=500)` preserving `role, content, tool_name, tool_calls, tool_call_id, finish_reason, reasoning, reasoning_content, reasoning_details, codex_reasoning_items, codex_message_items, api_content` (the wire-bytes sidecar keeps the provider prompt cache warm) and `timestamp`. Then `set_session_title`, `switch_session(session_key, new_id)`, `_clear_session_boundary_security_state`, `_evict_cached_agent`.
- **Inputs / options:** `[name]`.
- **Outputs / side effects:** `⑂ Branched to **<title>** (<n> message copied)\nOriginal: `<parent>`\nBranch: `<new>`\nUse `/resume` to switch back to the original.` (singular) or `… (<n> messages copied) …` (plural). Errors: `Session database not available.`, `No conversation to branch — send a message first.`, `Failed to create branch: <error>` (logged `Failed to create branch session: %s`), `Branch created but failed to switch to it.`
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.branch.branched_one` (`locales/en.yaml:102` → emitted at `gateway/slash_commands.py:5541`) — singular success form, chosen when exactly one user message was copied into the fork (`msg_count == 1`):

    ```text
    ⑂ Branched to **{title}** ({count} message copied)
    Original: `{parent}`
    Branch: `{new}`
    Use `/resume` to switch back to the original.
    ```

  - `gateway.branch.branched_many` (`locales/en.yaml:103` → emitted at `gateway/slash_commands.py:5541`) — plural success form for 0 or 2+ copied user messages; `parent`/`new` are the raw session ids so the user can address either explicitly:

    ```text
    ⑂ Branched to **{title}** ({count} messages copied)
    Original: `{parent}`
    Branch: `{new}`
    Use `/resume` to switch back to the original.
    ```
- **Config / env:** n/a.
- **Edge cases / guards:** the history copy is best-effort (a partial branch is still usable); routing columns are written at create time so a crash mid-copy can't leave an unroutable row.
- **Rebuild notes:** copy the api_content sidecar (cache parity), write routing identity at creation, and batch the inserts.

### `/compress` (alias `/compact`)  `id: gw-slash.compress`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/compress`, `/compress here`, `/compress here 4`, `/compress focus deployment plan`, `/compress --preview`, `/compress --dry-run`.
- **What it does:** manually summarises the conversation to free context, optionally keeping the last N exchanges verbatim or focusing the summary on a topic; `--preview` reports what *would* happen.
- **How it works:** wrapper `_handle_compress_command` (`gateway/slash_commands.py:4430`) installs the per-profile secret scope on multiplexed gateways (`_profile_runtime_scope`) — without it manual compression died with `UnscopedSecretError`. `_handle_compress_command_inner` (`:4513`): needs ≥4 messages; `extract_compress_flags` strips `--preview`/`--dry-run`/`--aggressive`; `parse_partial_compress_args` yields `(partial, keep_last, focus_topic)`. `--aggressive` is refused. `--preview` renders `summarize_compress_preview(...)` lines each prefixed `🗜️ `. Codex app-server sessions divert to `_compress_codex_app_server_session` (`:4452`) which compacts the live thread via `_compress_context(..., force=True)` rather than building a temp agent. Otherwise a throwaway `AIAgent` is built with `max_iterations=4, quiet_mode=True, skip_memory=not checkpoint_required, enabled_toolsets=["memory"], session_id=<current>`, seeded with the live session's system prompt, bound to the source platform + `gateway_session_key`; `_compress_context(head, "", approx_tokens, focus_topic, force=True, defer_context_engine_notification=True)` runs through `_run_in_executor_with_context`. Rotation vs in-place vs failure is handled explicitly (#61145, #44794): only a **rotated** session id triggers `rewrite_transcript`; in-place compaction is already persisted; a non-rotated non-in-place result preserves the original transcript and logs a warning.
- **Inputs / options:** `here [N]` (default N=2), `focus <topic>` / bare focus text, `--preview` / `--dry-run`, `--aggressive` (unsupported).
- **Outputs / side effects:** new session id (legacy rotation) or compacted rows in place; `last_prompt_tokens` reset; cached agent evicted; temp agent torn down off-loop. Reply: `🗜️ <headline>` + optional `Focus: "<topic>"` + `<token_line>` + optional note, plus one of: `⚠️ Summary generation failed (<error>). <count> historical message(s) were removed and replaced with a placeholder; earlier context is no longer recoverable. Consider checking your auxiliary.compression model configuration.` / `⚠️ Compression aborted (<error>). No messages were dropped — conversation is unchanged. Run /compress to retry, /reset for a clean session, or check your auxiliary.compression model configuration.` / `ℹ️ Configured compression model `<model>` failed (<error>). Recovered using your main model — context is intact — but you may want to check `auxiliary.compression.model` in config.yaml.` Other replies: `Not enough conversation to compress (need at least 4 messages).`, `No provider configured -- cannot compress.`, `Nothing to compress yet (the transcript is still all protected context).`, `--aggressive is not supported; use '/compress here [N]' to keep only recent exchanges, or /undo to drop turns.`, `Compression failed: <error>`, `ℹ️ Context compression deferred — summary still streaming. Continuing without compression this turn.`, and for a held lock `describe_compression_lock_skip(...)`. Codex path: `🗜️ Codex app-server thread compacted (thread/compact). The transcript mirror is unchanged by design — the app-server now carries the compacted context.` / `⚠️ Codex app-server compaction did not complete — the thread is unchanged. Check the app-server logs, retry /compress, or /reset for a clean session.` / `🗜️ Nothing to compact: this session runs on the Codex app-server runtime, whose context lives in a Codex-owned thread that only exists while the agent is active. Send a message first, then /compress — or /reset to start fresh.`
- **Config / env:** `auxiliary.compression.model`, `compression.checkpoint_required`, `compression.in_place`, `compression.codex_app_server_auto`, `agent.secret_scope` (multiplexing).
- **Edge cases / guards:** provider exception text is force-redacted at this UI boundary via `redact_sensitive_text(..., force=True)`; the transcript is written **before** the session entry is repointed so a failed write can't orphan the conversation.
- **Rebuild notes:** three distinct outcomes (rotate / compact-in-place / refuse) must be distinguishable, and only the rotating one may rewrite the transcript.

### `/rollback [number] [--all]`  `id: gw-slash.rollback`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/rollback`, `/rollback 3`, `/rollback 3 --all`, `/rollback <hash>`.
- **What it does:** lists filesystem checkpoints for the working directory, or restores one; by default a restore preserves files you hand-edited since the checkpoint.
- **How it works:** `_handle_rollback_command` (`gateway/slash_commands.py:3426`). Reads `_checkpoint_agent_kwargs(_load_gateway_config())`; if checkpoints are off returns the enable snippet. Builds `CheckpointManager(enabled=True, max_snapshots, max_total_size_mb, max_file_size_mb)`. `cwd = os.getenv("TERMINAL_CWD", str(Path.home()))`. Tokens `--all` / `--force` set `restore_all=True` and are stripped from the positional argument. No argument → `format_checkpoint_list(mgr.list_checkpoints(cwd), cwd)`. Otherwise a 1-based index selects a hash (out of range → error), a non-numeric argument is treated as a hash, then `mgr.restore(cwd, target_hash, safe=not restore_all)`.
- **Inputs / options:** `[number]` (1-based), `[hash]`, `--all` / `--force`.
- **Outputs / side effects:** files on disk are restored and a pre-rollback snapshot is taken automatically. Replies: `Checkpoints are not enabled.\nEnable in config.yaml:\n```\ncheckpoints:\n  enabled: true\n```` ; `No checkpoints found for <cwd>`; `Invalid checkpoint number. Use 1-<max>.`; `✅ Restored to checkpoint <hash>: <reason>\nA pre-rollback snapshot was saved automatically.` plus optional lines `↷ Kept your hand-edits: <files>\nUse /rollback <N> --all to restore those too.`, `↷ Kept (too large for checkpoints, no stored copy to revert to): <files>`, `⚠️ Could not remove (left in place): <files>` (each list shows 5 entries then `(+N)`); failure → `❌ <error>`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.rollback.not_enabled` (`locales/en.yaml:303` → emitted at `gateway/slash_commands.py:3434`) — `_checkpoint_agent_kwargs(...)["checkpoints_enabled"]` is false — the reply is the complete config.yaml snippet needed to turn the subsystem on:

    ~~~text
    Checkpoints are not enabled.
    Enable in config.yaml:
    ```
    checkpoints:
      enabled: true
    ```
    ~~~

  - `gateway.rollback.restored` (`locales/en.yaml:306` → emitted at `gateway/slash_commands.py:3478`) — `CheckpointManager.restore(cwd, target_hash, safe=not restore_all)` returned `success` — `hash` is `result["restored_to"]`, `reason` the checkpoint's stored reason:

    ```text
    ✅ Restored to checkpoint {hash}: {reason}
    A pre-rollback snapshot was saved automatically.
    ```

  - `gateway.rollback.kept_user_edits` (`locales/en.yaml:307` → emitted at `gateway/slash_commands.py:3487`) — appended to the success message when `result["skipped_user_edits"]` is non-empty; at most 5 names are shown followed by ` (+<n>)`:

    ```text
    ↷ Kept your hand-edits: {files}
    Use /rollback <N> --all to restore those too.
    ```
- **Config / env:** `checkpoints.enabled`, `checkpoints.max_snapshots`, `checkpoints.max_total_size_mb`, `checkpoints.max_file_size_mb`; `TERMINAL_CWD`.
- **Edge cases / guards:** safe mode is the default; the `--all` escape hatch is named in the reply itself.
- **Rebuild notes:** snapshot before restoring, and tell the user exactly which files you refused to overwrite.

### `/stop`  `id: gw-slash.stop`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments. Also `!stop` in Slack threads.
- **What it does:** interrupts the running agent and releases the session lock, keeping the conversation so it can continue.
- **How it works:** two paths. **Mid-run** `_busy_stop_command` (`gateway/run.py:17883`) hard-kills: `_interrupt_and_clear_session(quick_key, source, interrupt_reason=_INTERRUPT_REASON_STOP, invalidation_reason="stop_command")`, logs `STOP for session %s — agent interrupted, session lock released`, returns `EphemeralReply(t("gateway.stop.stopped"))`. A soft `agent.interrupt()` is deliberately not enough because a wedged executor thread never checks the flag. **Cold** `_handle_stop_command` (`gateway/slash_commands.py:1426`): if the slot holds `_AGENT_PENDING_SENTINEL` it force-clears it (`invalidation_reason="stop_command_pending"`) and replies `⚡ Stopped. The agent hadn't started yet — you can continue this session.`; if an agent exists it clears with `"stop_command_handler"` and replies `⚡ Stopped. You can continue this session.`; otherwise it looks for **sibling thread runs** via `_sibling_thread_run_keys(source, session_key)` (per-user thread sessions, `thread_sessions_per_user=True`) and, gated on `_is_user_authorized(source)`, interrupts each (log `STOP (thread sibling) by %s — interrupted %d run(s) in thread: %s`), else best-effort clears a stuck typing indicator via `adapter._stop_typing_with_metadata` (Slack's persistent `assistant.threads.setStatus` survives restarts, #32295) and replies `No active task to stop.`
- **Inputs / options:** none.
- **Outputs / side effects:** running-agent slot released, run generation invalidated, typing indicator cleared.
- **Config / env:** `thread_sessions_per_user` (per platform).
- **Edge cases / guards:** the pending-sentinel path also exists inline in `_handle_message` (`run.py:18720`) returning `⚡ Force-stopped. The agent was still starting — session unlocked.`
- **Rebuild notes:** `/stop` must work when everything else is wedged: force-clear the slot, don't await the agent's cooperation, and clear platform-side status.

### `/pause [reason | off]`  `id: gw-slash.pause`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/pause`, `/pause deploying`, `/pause off` (also `resume`, `stop`, `disengage`).
- **What it does:** engages/lifts the global emergency stop — new cron/kanban/gateway work is refused while in-flight work finishes.
- **How it works:** `_handle_pause_command` (`gateway/run.py:17838`), `busy_policy="dispatch"`, `gateway_only=True`. Uses `agent.estop`. Args lowercased: `{"off","resume","stop","disengage"}` → `estop.disengage()` → `▶️ Resumed — new work is accepted again.` or `Hermes wasn't paused.` With no args and an existing state → `⏸️ Hermes is already paused (reason: <reason>). Use `/pause off` to resume.` (the ` (reason: …)` suffix is omitted when there is no reason). Otherwise `estop.engage(reason=args or None)` → `⏸️ Paused (reason: <args>). New cron/kanban/gateway work is on hold; in-flight work finishes normally. Use `/pause off` to resume.`
- **Inputs / options:** `[reason]` free text; `off` | `resume` | `stop` | `disengage`.
- **Outputs / side effects:** global e-stop state.
- **Config / env:** n/a.
- **Edge cases / guards:** while paused, recognised slash commands still dispatch (`gw-slash.estop-gate`) — that is the in-band resume path for messaging-only operators. On Slack it is reachable only as `/hermes pause` (`_SLACK_VIA_HERMES_ONLY`). Not listed in the docs' messaging table.
- **Rebuild notes:** a global kill-switch needs an in-band, always-reachable off switch and must never block its own command.

### `/approve [all] [session|always]`  `id: gw-slash.approve`
- **Surface:** Gateway/Telegram
- **Where:** the reply to a dangerous-command approval prompt. Forms: `/approve`, `/approve all`, `/approve session`, `/approve all session`, `/approve always`, `/approve all always`.
- **What it does:** unblocks the agent thread(s) waiting inside `tools/approval.py`, so the dangerous command executes.
- **How it works:** `_handle_approve_command` (`gateway/slash_commands.py:6089`), `busy_policy="dispatch"`, `gateway_only=True`, `desktop="messaging"`. `has_blocking_approval(session_key)` gates: if false and a stale `_pending_approvals` entry exists it pops it and returns `⚠️ Approval expired (agent is no longer waiting). Ask the agent to try again.`, else `No pending command to approve.` Args are lowercased and split: `all` anywhere → `resolve_all=True`; remaining tokens `{"always","permanent","permanently"}` → `choice="always"`, `{"session","ses"}` → `"session"`, else `"once"`. `resolve_gateway_approval(session_key, choice, resolve_all)` returns a count; `0` → `No pending command to approve.` Then `adapter.resume_typing_for_chat(chat_id)` and log `User approved %d dangerous command(s) via /approve (%s)`.
- **Inputs / options:** `all`, `session`/`ses`, `always`/`permanent`/`permanently`, and any combination.
- **Outputs / side effects:** confirmation text keyed `gateway.approve.<choice>_<singular|plural>`: `✅ Command approved. The agent is resuming...` / `✅ Commands approved (<count> commands). The agent is resuming...` / `✅ Command approved (pattern approved for this session). The agent is resuming...` / `✅ Commands approved (pattern approved for this session) (<count> commands). The agent is resuming...` / `✅ Command approved (pattern approved permanently). The agent is resuming...` / `✅ Commands approved (pattern approved permanently) (<count> commands). The agent is resuming...` The `always` choice writes the pattern to the permanent allowlist.
- **Config / env:** `approvals.mode` (see `/approvals`); `_APPROVAL_TIMEOUT_SECONDS = 300` (`gateway/run.py:25786`).
- **Edge cases / guards:** adapters with `SUPPORTS_NATIVE_STREAMING is True` (WeCom-style) get the confirmation via a direct `adapter.send(..., metadata={"is_approval_prompt": True, "force_proactive_send": True})` and the handler returns `None`; everyone else returns the text. A live tool approval takes precedence over a pending slash-confirm (`gw-slash.slash-confirm`). Bare "yes" in prose never approves anything — deliberate (`gateway/run.py:19541`).
- **Rebuild notes:** support multi-approval (parallel subagents) with an explicit `all`, three memory scopes, and a proactive send path for streaming-only transports.

### `/deny [all] [reason]`  `id: gw-slash.deny`
- **Surface:** Gateway/Telegram
- **Where:** the reply to an approval prompt: `/deny`, `/deny all`, `/deny not on prod`, `/deny all wrong directory`.
- **What it does:** rejects pending dangerous command(s), optionally relaying a one-line reason to the agent so it can adapt.
- **How it works:** `_handle_deny_command` (`gateway/slash_commands.py:6175`). Same `has_blocking_approval` gate → `❌ Command denied (approval was stale).` (stale pending entry) or `No pending command to deny.` Leading token `all` (case-insensitive) → `resolve_all=True` and the remainder is the reason; otherwise the whole argument string is the reason. Reason is capped at 280 chars. `resolve_gateway_approval(session_key, "deny", resolve_all, reason=reason or None)`; then `resume_typing_for_chat`; log `User denied %d dangerous command(s) via /deny%s` (` (with reason)`).
- **Inputs / options:** `all`, `<reason>` (≤280 chars).
- **Outputs / side effects:** `❌ Command denied.` / `❌ Commands denied (<count> commands).` / `❌ Command denied. Reason relayed to the agent: "<reason>"` / `❌ Commands denied (<count> commands). Reason relayed to the agent: "<reason>"`
- **Config / env:** n/a.
- **Edge cases / guards:** same native-streaming carve-out as `/approve`. Ported from qwibitai/nanoclaw#2832.
- **Rebuild notes:** a deny with a reason turns a dead end into steering; cap it and relay it as tool output.

---

## 3. Background, async and automation commands

### `/bg <prompt>`  `id: gw-slash.bg`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/bg Summarize the top HN stories today`.
- **What it does:** runs a prompt in a completely separate background session; the current chat stays free and the result is delivered back to the same chat when finished.
- **How it works:** `_handle_background_command` (`gateway/slash_commands.py:3619`), `busy_policy="dispatch"`. Empty prompt → the usage text. `task_id = f"bg_{HHMMSS}_{os.urandom(3).hex()}"`. Captures the reply anchor and forwards `event.media_urls` / `event.media_types` so the background agent can see attachments. Fires `asyncio.create_task(self._run_background_task(prompt, source, task_id, event_message_id=…, media_urls=…, media_types=…))`, registered in `self._background_tasks` with a `discard` done-callback.
- **Inputs / options:** `<prompt>` (required); inherited image/audio attachments.
- **Outputs / side effects:** usage — `Usage: /bg <prompt>\nExample: /bg Summarize the top HN stories today\n\nRuns the prompt in a separate session. You can keep chatting — the result will appear here when done.`; started — `🔄 Background task started: "<preview>"\nTask ID: <task_id>\nYou can keep chatting — results will appear when done.` (preview = first 60 chars + `...`).
- **Config / env:** n/a.
- **Edge cases / guards:** the current session's history is untouched; results arrive as a separate message.
- **Rebuild notes:** separate session id, media forwarding, and a task registry so `/agents` can report it.

### `/btw <question>`  `id: gw-slash.btw`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/btw which file was that error in?`.
- **What it does:** answers a side question **about the current conversation** without interrupting it; the live transcript and prompt cache are untouched.
- **How it works:** `_handle_btw_command` (`gateway/slash_commands.py:3656`), `busy_policy="dispatch"`. Loads the transcript snapshot, resolves the session runtime (`_resolve_session_agent_runtime`), and requires an `api_key`. Prefers the **cache-parity fork**: if a live cached `AIAgent` exists it is passed as `parent_agent` so the snapshot replays against the warm provider prefix cache at cache-read prices; otherwise `answer_side_question` falls back to a one-shot digest. Runs in `asyncio.to_thread(answer_side_question, question, history_snapshot, parent_agent=…, main_runtime=…)` inside a fire-and-forget task, then sends the answer through `adapter.send(chat_id, …, metadata=thread_metadata)`.
- **Inputs / options:** `<question>` (required).
- **Outputs / side effects:** usage — `Usage: /btw <question>\nExample: /btw which file was that error in?\n\nAnswers a quick side question about this conversation without interrupting it. For an independent background task, use /bg <prompt>.`; no transcript — `No conversation yet — send your question as a normal message instead.`; no credentials — `❌ Cannot answer side question: no provider credentials configured.`; ack — `💬 Side question: "<preview>"\nAnswering from a snapshot of this conversation — the current work continues.`; answer — `💬 /btw: "<preview>"\n\n<answer>`; failure — `❌ /btw failed: "<preview>"\n<error>` (logged `/btw side question failed: %s`).
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.btw.usage` (`locales/en.yaml:90` → emitted at `gateway/slash_commands.py:3670`) — `/btw` typed with an empty argument — the built-in help, which also steers the user to `/bg` for independent background work:

    ```text
    Usage: /btw <question>
    Example: /btw which file was that error in?

    Answers a quick side question about this conversation without interrupting it. For an independent background task, use /bg <prompt>.
    ```

  - `gateway.btw.started` (`locales/en.yaml:93` → emitted at `gateway/slash_commands.py:3749`) — immediate acknowledgement returned the moment the side question is dispatched against the transcript snapshot (`preview` = the question, truncated); the live turn keeps running:

    ```text
    💬 Side question: "{preview}"
    Answering from a snapshot of this conversation — the current work continues.
    ```
- **Config / env:** the session's model route (`main_runtime`: model, provider, base_url, api_key, api_mode).
- **Edge cases / guards:** explicitly contrasted with `/bg` (fresh contextless session) in both the docstring and the usage text.
- **Rebuild notes:** read-only snapshot + parent-agent cache parity is the whole trick; never mutate the live history for a side question.

### `/agents` (alias `/tasks`)  `id: gw-slash.agents`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments. Header `🤖 **Active Agents & Tasks**`.
- **What it does:** lists every running agent, background OS process, gateway async job and background delegation, with uptimes.
- **How it works:** `_handle_agents_command` (`gateway/slash_commands.py:1275`), `busy_policy="dispatch"`. Builds `agent_rows` from `self._running_agents` + `self._running_agents_ts`, marking `_AGENT_PENDING_SENTINEL` entries as `starting` and others `running`, sorted by elapsed descending. Processes come from `tools.process_registry.process_registry.list_sessions()` filtered to `status == "running"`. Async jobs = not-done entries of `self._background_tasks`. Delegations come from `tools.async_delegation.list_async_delegations()` filtered to status `running|stalling|finalizing`, including per-child progress from the registry sampler (#51690).
- **Inputs / options:** none.
- **Outputs / side effects:** read-only. Layout: `🤖 **Active Agents & Tasks**` / blank / `**Active agents:** <n>` then up to 12 rows `` <i>. `<session_key>` · <state> · <uptime>[ · `<session_id>`][ · `<model>`][ · this chat] `` and `... and <n> more`; blank / `**Running background processes:** <n>` then up to 12 `` - `<session_id>` · <uptime> · `<cmd>` `` (command squashed to single spaces, truncated at 90 chars with `...`); blank / `**Gateway async jobs:** <n>`; when delegations exist, blank / `**Background delegations:** <n>` then up to 12 `` - `<delegation_id>` · <status>[ · no progress <n>s][ · quiet <n>s][ · <goal>] `` (goal truncated at 70) with child lines `  - child <i>: <api_calls> api calls · `<tool>`|between turns[ · active <n>s ago]`. When everything is empty: blank + `No active agents or running tasks.`
- **Config / env:** n/a.
- **Edge cases / guards:** all four sources are individually try/except'd to empty lists.
- **Rebuild notes:** one command that answers "what is this thing doing right now" across four different runtimes; include the *pending* state so a starting agent isn't invisible.

### `/queue <prompt>` (alias `/q`)  `id: gw-slash.queue`
- **Surface:** Gateway/Telegram
- **Where:** any chat while Hermes is working: `/queue write the tests next`, or `/queue` as a photo caption.
- **What it does:** queues a prompt as its own full agent turn after the current one, without interrupting.
- **How it works:** mid-run `_busy_queue_command` (`gateway/run.py:17914`): `queued_text = args`; `has_media = bool(event.media_urls)`; empty text **and** no media → `Usage: /queue <prompt>`. Builds a fresh `MessageEvent` preserving `message_type` (kept when media present), `raw_message`, `message_id`, `media_urls`, `media_types`, `media_text_inlined`, all five `reply_to_*` fields, `auto_skill`, `channel_prompt`, `channel_context`, `internal`, `timestamp`, then `self._enqueue_fifo(quick_key, queued_event, adapter)`. Cold path (`run.py:19243`): with no running agent it simply strips the prefix (`event.text = payload`) and falls through as a normal turn; empty payload → `Usage: /queue <prompt>`.
- **Inputs / options:** `<prompt>`; attachments count as payload.
- **Outputs / side effects:** FIFO depth grows. Reply: `Queued for the next turn.` when depth ≤ 1, else `Queued for the next turn. (<depth> queued)`.
- **Config / env:** `display.busy_input_mode` (`queue` makes plain messages behave the same way).
- **Edge cases / guards:** each `/queue` is a separate turn — messages are never merged. Dropping media fields used to silently lose the attachment; the explicit field copy is the fix.
- **Rebuild notes:** copy the whole event, not just the text.

### `/steer <prompt>`  `id: gw-slash.steer`
- **Surface:** Gateway/Telegram
- **Where:** any chat while a tool is running: `/steer focus on the auth module`.
- **What it does:** injects a note that reaches the agent **after the next tool call** — no interrupt, no new user turn, no role-alternation break.
- **How it works:** mid-run `_busy_steer_command` (`gateway/run.py:17968`). Empty → `Usage: /steer <prompt>`. If the slot holds `_AGENT_PENDING_SENTINEL` it enqueues instead and replies `Agent still starting — /steer queued for the next turn.` If the running agent has `steer()`: `accepted = running_agent.steer(text)`; on exception → `⚠️ Steer failed: <exc>` (log `Steer failed for session %s: %s`); accepted → `⏩ Steer queued — arrives after the next tool call: '<preview>'` (60-char preview + `...`); rejected → `Steer rejected (empty payload).` No `steer()` → enqueue + `No active agent — /steer queued for the next turn.` Cold path (`run.py:19256`) strips the prefix and sends as a normal message; empty → `Usage: /steer <prompt>  (no agent is running; sending as a normal message)`.
- **Inputs / options:** `<prompt>`.
- **Outputs / side effects:** appends to the last tool result's content inside the running loop.
- **Config / env:** `display.busy_input_mode: steer` applies the same semantics to plain messages.
- **Edge cases / guards:** falls back to queue semantics whenever steering is impossible.
- **Rebuild notes:** steering belongs between tool iterations, not at turn boundaries — that is what distinguishes it from `/queue`.

### `/goal`  `id: gw-slash.goal`
- **Surface:** Gateway/Telegram
- **Where:** any chat. Full grammar: `/goal <text>`, `/goal`, `/goal status`, `/goal show`, `/goal pause`, `/goal resume`, `/goal clear` (`stop`, `done`), `/goal draft <objective>`, `/goal wait <pid> [reason]`, `/goal unwait`, `/goal gate` / `gate list` / `gate add <command>` / `gate remove <N>` (`rm`) / `gate clear`.
- **What it does:** sets a standing goal Hermes keeps working on across turns (the Ralph loop); after each turn a judge model decides DONE/CONTINUE and auto-continues until done, paused, cleared, or the turn budget runs out.
- **How it works:** `_handle_goal_command` (`gateway/slash_commands.py:2733`), `busy_policy="dispatch"`, `busy_handler="goal"`. `_get_goal_manager_for_event` resolves a `GoalManager` bound to the session (None → `Goals unavailable on this session.`). Bare/`status` → `mgr.status_line()`. `show` → `status_line()` + `render_contract()`. `pause` → `mgr.pause(reason="user-paused")` then `_clear_goal_pending_continuations(quick_key, adapter)`. `resume` → `mgr.resume()` then enqueue `mgr.next_continuation_prompt()` through the adapter FIFO so work restarts immediately (#75362). `clear|stop|done` → `mgr.clear()` + continuation cleanup. `wait <pid> [reason]` → `mgr.wait_on(pid, reason)`. `unwait` → `mgr.stop_waiting()`. `gate …` → `render_gates()` / `add_gate(command)` / `remove_gate(int)` / `clear_gates()`. `draft <objective>` → `hermes_cli.goals.draft_contract(objective)` in an executor; otherwise `parse_contract(args)` splits inline `field: value` lines into a completion contract plus a headline. Setting a goal calls `mgr.set(args, contract=contract)` and enqueues the goal text as an immediate kickoff turn.
- **Inputs / options:** every sub-form above; `args_hint="[text | draft <text> | show | gate add <cmd> | pause | resume | clear | status | wait <pid> | unwait]"`.
- **Outputs / side effects:** goal state persisted per session; FIFO kickoff/continuation events. Replies: `Goals unavailable on this session.`, `No goal set.`, `⏸ Goal paused: <goal>`, `No goal to resume.`, `▶ Goal resumed: <goal>\nContinuing now — I'll take the next step right away.`, `✓ Goal cleared.` / `No active goal.`, `Invalid goal: <error>`, `⊙ Goal set (<budget>-turn budget): <goal>\nI'll keep working until the goal is done, you pause/clear it, or the budget is exhausted.\nControls: /goal status · /goal pause · /goal resume · /goal clear` (+ `\nCompletion contract:\n<block>` when a contract exists, or `\n(Couldn't draft a contract — running as a free-form goal.)` when `draft` failed). Gate/wait replies: `Usage: /goal wait <pid> [reason]`, `/goal wait: <pid> must be an integer process id.`, `/goal wait: <exc>`, `⏳ Goal parked on pid <pid> (<reason>). Loop pauses until it exits.`, `▶ Wait barrier cleared — goal loop resumes.`, `No wait barrier set.`, `⚿ Gate added: $ <command> (<n> retries, <n>s timeout). It must pass before the goal can complete.`, `/goal gate add: <exc>`, `✓ Gate removed: $ <command>`, `/goal gate remove: <exc>`, `✓ Cleared <n> gate(s).`, `/goal gate clear: <exc>`, `Usage: /goal gate [list | add <command> | remove <N> | clear]`, `Usage: /goal draft <objective in plain language>`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.goal.resumed` (`locales/en.yaml:169` → emitted at `gateway/slash_commands.py:2796`) — `/goal resume` — `mgr.resume()` returned a state, and the canonical continuation prompt was enqueued through the adapter FIFO (`_enqueue_fifo`) so work restarts immediately instead of only flipping persisted state (#75362):

    ```text
    ▶ Goal resumed: {goal}
    Continuing now — I'll take the next step right away.
    ```

  - `gateway.goal.set` (`locales/en.yaml:171` → emitted at `gateway/slash_commands.py:2918`) — a new goal was accepted by `mgr.set(args, contract=...)`; the goal text is also enqueued as an immediate kickoff turn. `budget` is `state.max_turns`. When the goal has a completion contract, `\nCompletion contract:\n<block>` is appended; when `draft` was requested but no contract could be produced, `\n(Couldn't draft a contract — running as a free-form goal.)` is appended instead:

    ```text
    ⊙ Goal set ({budget}-turn budget): {goal}
    I'll keep working until the goal is done, you pause/clear it, or the budget is exhausted.
    Controls: /goal status · /goal pause · /goal resume · /goal clear
    ```
- **Config / env:** `goals.max_turns` (default 20, resolved by `_goal_max_turns_from_config`, `gateway/run.py:23233`).
- **Edge cases / guards:** mid-run only the control verbs run — `_busy_goal_command` (`gateway/run.py:18004`) allows empty, `status`, `pause`, `resume`, `clear`, `stop`, `done`, `unwait`, plus the verbs `wait` and `gate`; anything else replies `Agent is running — use /goal status / pause / clear / wait mid-run, or /stop before setting a new goal.` A real user message preempts the continuation loop. The goals SessionDB cache is warmed off-loop first (`_warm_goals_session_db`) so a cold cache can't silently drop the write.
- **Rebuild notes:** goal + subgoals + deterministic gates + a wait barrier + a turn budget, with every mutation readable at the next turn boundary so control verbs are safe mid-run.

### `/subgoal`  `id: gw-slash.subgoal`
- **Surface:** Gateway/Telegram
- **Where:** any chat with an active goal: `/subgoal`, `/subgoal also update the docs`, `/subgoal remove 2`, `/subgoal clear`.
- **What it does:** appends user-supplied criteria to the active goal mid-loop; the judge will not mark the goal done until the goal **and** every subgoal are met.
- **How it works:** `_handle_subgoal_command` (`gateway/slash_commands.py:3100`), `busy_policy="dispatch"` (safe mid-run because the state is read at the next turn boundary). No manager → `Goals unavailable on this session.`; no goal → `No active goal. Set one with /goal <text>.` Bare → `status_line()` + `render_subgoals()`. First token `remove` → integer 1-based index → `mgr.remove_subgoal(idx)`. `clear` → `mgr.clear_subgoals()`. Anything else → `mgr.add_subgoal(args)`.
- **Inputs / options:** `[text | remove N | clear]`.
- **Outputs / side effects:** `✓ Added subgoal <i>: <text>`, `✓ Removed subgoal <i>: <text>`, `Usage: /subgoal remove <n>`, `/subgoal remove: <n> must be an integer (1-based index).`, `/subgoal remove: <exc>`, `✓ Cleared <n> subgoal(s).`, `No subgoals to clear.`, `/subgoal clear: <exc>`, `/subgoal: <exc>`.
- **Config / env:** n/a.
- **Edge cases / guards:** requires an active `/goal`.
- **Rebuild notes:** subgoals are verbatim additions to the judge's completion contract — surface them in the continuation prompt too.

### `/heartbeat` (alias `/hb`)  `id: gw-slash.heartbeat`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/heartbeat every 10m Check CI`, `/heartbeat 10m Check CI`, `/heartbeat status|pause|resume|clear` (also `stop`, `off`).
- **What it does:** sets one recurring prompt that re-enters **this** session as an ordinary user turn whenever the session is idle and the interval has elapsed.
- **How it works:** `_handle_heartbeat_command` (`gateway/slash_commands.py:2926`), `busy_policy="dispatch"`. Manager via `_get_heartbeat_manager_for_event` (None → `Heartbeats unavailable (no session).`). Parsing: tokens split with `maxsplit=2`; `every <interval> <prompt>` uses `parse_interval(f"every {tok1}")`, otherwise `parse_interval(tok0)` and the rest is the prompt. `mgr.set(prompt, interval)` plus `_register_heartbeat_watch(quick_key, source, mgr.session_id)`; `pause`/`resume`/`clear` mutate state and (un)register the watch.
- **Inputs / options:** `every <interval> <prompt>`, `<interval> <prompt>`, `status`, `pause`, `resume`, `clear|stop|off`.
- **Outputs / side effects:** `♥ Heartbeat set (every <interval>): <prompt>\nFires as a normal turn whenever this session is idle and the interval has elapsed. Lives while the gateway runs — use `hermes cron` for durable schedules.`; `⏸ Heartbeat paused: <prompt>` / `No heartbeat set.`; `▶ Heartbeat resumed (every <interval>): <prompt>` / `No heartbeat to resume.`; `✓ Heartbeat cleared.` / `No heartbeat set.`; usage — `Usage: /heartbeat every <interval> <prompt>  (e.g. /heartbeat every 10m Check CI)\nAlso: /heartbeat status | pause | resume | clear`; `Interval too small — minimum is <MIN_INTERVAL_SECONDS>s.`; `Usage: /heartbeat every <interval> <prompt> — the prompt is required.`; `Invalid heartbeat: <exc>`.
- **Config / env:** `hermes_cli.heartbeat.MIN_INTERVAL_SECONDS` (docs say 60 s); missed ticks coalesce.
- **Edge cases / guards:** session-scoped and in-process only — the reply itself points at `hermes cron` for durable schedules. Slack-only via `/hermes heartbeat …`.
- **Rebuild notes:** one heartbeat per session, injected through the same FIFO real messages use, so alternation and caching are untouched.

### `/refine [focus]`  `id: gw-slash.refine`
- **Surface:** Gateway/Telegram
- **Where:** any chat between turns: `/refine`, `/refine save the deploy workflow as a skill`.
- **What it does:** runs the background memory/skill self-improvement review right now instead of waiting for the automatic post-turn trigger.
- **How it works:** `_handle_refine_command` (`gateway/slash_commands.py:2998`). Requires a session key (`Refine unavailable (no session).`) and that the session is **not** running (`Agent is running — wait for the turn to finish, then /refine.`). Pulls the cached `AIAgent` from `_agent_cache` under `_agent_cache_lock` (`Nothing to refine yet — send a message first.`), snapshots `agent._session_messages` (`Nothing to refine yet — the conversation is empty.`), sets `review_skills = "skill_manage" in agent.valid_tool_names`, then `agent._spawn_background_review(messages_snapshot=…, review_memory=True, review_skills=…, focus=args or None)` in a daemon thread against the snapshot.
- **Inputs / options:** `[focus instructions]` free text.
- **Outputs / side effects:** `⚗ Reviewing this conversation in the background (focus: <args>) — any memory/skill updates will be reported when done.`; start failure → `/refine failed to start: <exc>`.
- **Config / env:** memory/skill write-approval gates decide whether results are staged or applied.
- **Edge cases / guards:** the live session and prompt cache are untouched. Slack-only via `/hermes refine …`.
- **Rebuild notes:** fork against a snapshot, never the live message list.

### `/review [instructions]`  `id: gw-slash.review`
- **Surface:** Gateway/Telegram
- **Where:** any chat between turns: `/review`, `/review check the migration for data loss`.
- **What it does:** spawns an independent, full-privilege reviewer subagent for the work just discussed; its review re-enters the chat as a background-subagent completion.
- **How it works:** `_handle_review_command` (`gateway/slash_commands.py:3042`). Same session/running/cached-agent guards as `/refine` (`Review unavailable (no session).`, `Agent is running — wait for the turn to finish, then /review.`, `Nothing to review yet — send a message first.`). Snapshots `agent._session_messages`, then in an executor binds the approval session key (`tools.approval.set_current_session_key(quick_key)`, reset in `finally`) — without this the completion would carry no gateway route — and calls `agent.review_engine.start_review(agent, snapshot, args)`. The reply is `agent.review_engine.format_dispatch_note(result, args)`. `ValueError` from the engine is returned verbatim; other exceptions → `/review failed to start: <exc>`.
- **Inputs / options:** `[review instructions]`; the engine reads the last 10 chat messages.
- **Outputs / side effects:** an async delegation on the background rail; the finished review arrives as a normal completion turn.
- **Config / env:** `auxiliary.review` pins a dedicated review model (defaults to the main model).
- **Edge cases / guards:** Slack-only via `/hermes review …`.
- **Rebuild notes:** bind the routing contextvar explicitly when dispatching outside an agent turn, or the result has nowhere to land.

### `/loop` (alias `/proactive`)  `id: gw-slash.loop`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/loop 5m check the deploy status`, `/loop every 10m /recap`, `/loop keep fixing tests until green`, `/loop 2m poll CI --times 30`, `/loop 5m watch the queue --until queue is empty`, `/loop status|pause|resume|stop|clear|cancel|help`.
- **What it does:** re-runs a prompt on a recurring interval inside this session (or self-paced with back-off), with optional run-count and stop-condition limits.
- **How it works:** `_handle_loop_command` (`gateway/slash_commands.py:3176`), `busy_policy="dispatch"`, `busy_handler="loop"`. `_get_loop_manager_for_event` (`:3151`) warms the goals SessionDB off-loop then builds `LoopManager(session_id)` (None → `Loops unavailable (no active session).`; import failure → `Loops unavailable.`). A `route` dict is captured from the event (`platform, chat_id, chat_type, thread_id, user_id, user_name`, empty values dropped) so the idle loop-wakeup watcher can inject ticks back into this chat after a restart. Then `dispatch_loop_command(mgr, args, route=route)` (`hermes_cli/loops.py:855`). When a loop was created and `goal_blocks_loop_tick(session_id)` is true it appends `\nNote: an active /goal is driving this session — loop wakeups defer until the goal finishes, pauses, or parks.`
- **Inputs / options:** `[interval] <prompt>`, `--times N`, `--until <condition>`, `status`, `pause`, `resume`, `stop|clear|cancel`, `help|--help|-h`.
- **Outputs / side effects:** loop state persisted per session. Replies: status → `mgr.status_line()`; `⏸ Loop paused: <prompt>\nUse /loop resume to continue.` / `No loop set.`; `▶ Loop resumed (<cadence>): <prompt>` / `No loop to resume.`; `✓ Loop stopped.` / `No active loop.`; help (verbatim) — `Usage: /loop [interval] <prompt> [--times N] [--until <condition>]` / `  /loop 5m check the deploy status      — first run now, then every 5m` / `  /loop every 10m /recap                — loop a slash command` / `  /loop keep fixing tests until green   — self-paced (backs off while output is unchanged)` / `  /loop 2m poll CI --times 30           — stop after 30 runs` / `  /loop 5m watch the queue --until queue is empty` / `Controls: /loop status · /loop pause · /loop resume · /loop stop` / `The loop also stops itself when the agent replies with <LOOP_COMPLETE_MARKER>.`; creation — `↻ Loop set (<cadence>): <prompt>` plus optional `(interval raised to the <x> minimum — loops.min_interval_seconds)`, `Self-paced: first check in <x>; backs off up to <y> while nothing changes.`, `Runs <n> time(s), then stops.`, `Stops when: <until>`, `Backstop budget: <n> ticks (loops.max_ticks; 0 = unlimited).`, `First wakeup fires now, then on the cadence above. Controls: /loop status · pause · resume · stop.` or `First wakeup <remaining>. Controls: …`, and `(replaced the previous loop for this session)` inserted as line 2 when replacing; errors — `Usage: /loop [interval] <prompt> — see /loop help.` and `/loop: <error>`.
- **Config / env:** `loops.min_interval_seconds`, `loops.max_ticks`, self-paced ceiling from `self_paced_ceiling_seconds()`.
- **Edge cases / guards:** mid-run `_busy_loop_command` (`gateway/run.py:18025`) allows empty/`status`/`pause`/`resume`/`stop`/`clear`/`cancel`/`help`/`--help`/`-h`; anything else → `Agent is running — use /loop status / pause / stop mid-run, or /stop before setting a new loop.`
- **Rebuild notes:** store the originating route with the loop so wakeups survive a restart; let the agent end its own loop with a sentinel marker.

### `/plan [task]`  `id: gw-slash.plan`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/plan`, `/plan migrate the auth module to OAuth`.
- **What it does:** writes a markdown implementation plan into `.hermes/plans/` in the active workspace — planning only, no execution.
- **How it works:** cold-path branch at `gateway/run.py:19065`. `build_plan_prompt(task)` (`agent/plan_prompt.py`) rewrites `event.text` and the turn falls through to normal agent processing (the same fall-through pattern as `/learn`, chosen so role alternation is preserved). An acknowledgement is sent first through the adapter: `Planning: <task[:80]>…` (ellipsis only when truncated) or `Planning from this conversation's context…`. Prompt-build failure → `Could not start /plan — please try again.`
- **Inputs / options:** `[task]`; empty infers the task from the conversation.
- **Outputs / side effects:** the ack message, then a normal agent turn that writes the plan file via `write_file`.
- **Config / env:** n/a — "no engine, works on any backend".
- **Edge cases / guards:** ack send failures are logged (`plan ack send failed`) and ignored.
- **Rebuild notes:** prompt rewriting + fall-through beats a bespoke engine; it inherits every tool and model the session already has.

### `/moa <prompt>`  `id: gw-slash.moa`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/moa design the schema`.
- **What it does:** runs exactly one prompt through the default Mixture-of-Agents preset, then restores the session's previous model.
- **How it works:** cold-path branch at `gateway/run.py:19277`. Empty payload → `moa_usage()`. Loads `moa` config via `normalize_moa_config(load_config().get("moa"))`, takes `default_preset`, sets `event.text = payload`, saves `event._moa_restore_override = session.conversation.model_override`, then installs the virtual override `{"provider": "moa", "model": <preset>, "base_url": "moa://local", "api_key": "moa-virtual-provider", "api_mode": "chat_completions"}`, evicts the cached agent and sets `event._moa_disable_after_turn = True`. The revert runs in `_restore_moa_one_shot` (`run.py:19652`) from the `finally` of the message handler, so it fires on success, exception and interrupt alike. Setup failure → `Failed to prepare MoA turn.`
- **Inputs / options:** `<prompt>` (required).
- **Outputs / side effects:** one turn on the MoA preset; the prior override is restored afterwards.
- **Config / env:** `moa.default_preset` and the rest of the `moa` block.
- **Edge cases / guards:** `busy_policy="reject"` with `busy_handler="moa"` → mid-run reply `Agent is running — wait or /stop first, then run /moa.` To *switch* to MoA for the whole session, pick a MoA preset from the `/model` picker (they surface as a virtual "Mixture of Agents" provider). Slack-only via `/hermes moa`.
- **Rebuild notes:** a one-shot model override must be restored in a `finally`, or it leaks permanently.

### `/learn <what to learn from>`  `id: gw-slash.learn`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/learn the deploy workflow we just did`, `/learn https://example.com/guide`, `/learn ./scripts`.
- **What it does:** distils a reusable skill from anything the user describes — a directory, a URL, this conversation, or pasted notes.
- **How it works:** cold-path branch at `gateway/run.py:19037`. Sends an ack first — `Learning a skill from what you described…` when an argument is present, else `Learning a skill from this conversation…` — then rewrites `event.text = build_learn_prompt(request)` (`agent/learn_prompt.py`) and falls through to the agent, which gathers sources with `read_file` / `web_extract` and authors the skill via `skill_manage`. Failure → `Could not start /learn — please try again.`
- **Inputs / options:** `<what to learn from>` free text (optional in practice — empty means "this conversation").
- **Outputs / side effects:** a new SKILL.md (subject to `skills.write_approval`).
- **Config / env:** `skills.write_approval` decides whether the write is staged for `/skills approve`.
- **Edge cases / guards:** ack send failure logged as `learn ack send failed`.
- **Rebuild notes:** same prompt-rewrite pattern as `/plan` and `/init`.

### `/init [notes]`  `id: gw-slash.init`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/init`, `/init emphasise the test commands`.
- **What it does:** generates or merge-updates `AGENTS.md` project instructions from a repo scan (a port of Codex `/init`).
- **How it works:** cold-path branch at `gateway/run.py:19091`. `build_init_prompt_for_cwd(extra=notes)` (`hermes_cli/init_command.py`); on exception → `Could not start /init — please try again.` The ack is chosen by inspecting the built prompt: `Updating AGENTS.md from a project scan…` when it contains `UPDATE the existing AGENTS.md`, else `Generating AGENTS.md from a project scan…`. Then `event.text = _init_prompt` and fall-through.
- **Inputs / options:** `[notes]` free text to steer emphasis.
- **Outputs / side effects:** `AGENTS.md` written/updated by the agent's own `write_file`.
- **Config / env:** n/a.
- **Edge cases / guards:** Slack-only via `/hermes init`; ack failures logged as `init ack send failed`.
- **Rebuild notes:** decide create-vs-update in the prompt builder, and let the ack tell the truth about which one is happening.

### `/suggestions` (alias `/suggest`)  `id: gw-slash.suggestions`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/suggestions`, `/suggestions accept 2`, `/suggestions dismiss 3`, `/suggestions catalog`, `/suggestions clear`.
- **What it does:** reviews the automations Hermes proposed — list, accept (creates a cron job), dismiss, seed a curated catalog, or clear resolved records.
- **How it works:** `_handle_suggestions_command` (`gateway/run.py:23167`) builds `origin = {platform, chat_id, chat_name, thread_id}` from the event so an accepted job delivers back to this chat/thread, then calls `handle_suggestions_command(args, origin=origin, surface="gateway")` (`hermes_cli/suggestions_cmd.py:66`). Sub-verbs: bare → `_fmt_pending(store.list_pending())`; `accept|add|schedule <number|id>` → `store.accept_suggestion(rest, origin=origin)`; `dismiss|no|reject <number|id>` → `store.dismiss_suggestion(rest)`; `catalog` → `seed_catalog_suggestions()`; `clear` → `store.clear_resolved()`.
- **Inputs / options:** `accept|add|schedule <n>`, `dismiss|no|reject <n>`, `catalog`, `clear`.
- **Outputs / side effects:** cron jobs created/removed. Replies: `Suggestions are unavailable in this build.`; `Usage: /suggestions accept <number|id>`; `Scheduled '<name>' (<schedule>). Ask me to list, pause, or remove it any time.` (gateway wording; the CLI says `Manage it with /cron.`); `No pending suggestion matches '<rest>'. Run /suggestions to list them.`; `Usage: /suggestions dismiss <number|id>`; `Dismissed. Won't suggest that again.` / `No pending suggestion matches '<rest>'.`; `Couldn't load the catalog.`; `No new catalog automations to add (already offered, dismissed, or your suggestion list is full). Run /suggestions to see pending.`; `Added <n> suggestion(s): <titles>.\nRun /suggestions to review.`; `Cleared <n> resolved suggestion record(s).`; unknown verb → the 5-line usage block `Usage:\n  /suggestions              list pending\n  /suggestions accept N     schedule suggestion N\n  /suggestions dismiss N    dismiss suggestion N\n  /suggestions catalog      add curated starter automations\n  /suggestions clear        housekeeping`; wrapper failure → `Suggestions command failed: <e>`. A `CronSchedulerRegistrationError` is surfaced via `e.user_message()`.
- **Config / env:** cron store; `args_hint="[accept|dismiss N | catalog]"` (the registry hint omits `clear`, which the handler supports).
- **Edge cases / guards:** accepted jobs preserve the current surface as delivery origin.
- **Rebuild notes:** one shared handler with a `surface` parameter so CLI and chat wording differ only where they must.

### `/blueprint [name] [slot=value …]` (alias `/bp`)  `id: gw-slash.blueprint`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/blueprint`, `/blueprint standup`, `/blueprint standup time=09:00 channel=eng`.
- **What it does:** sets up a scheduled automation from a template — bare lists the catalog, a name alone starts a guided slot-filling conversation, and a name with inline slot values creates the job directly.
- **How it works:** `_handle_blueprint_command` (`gateway/run.py:23197`) builds the same `origin` dict and calls `handle_blueprint_command(args, origin, surface="gateway")` (`hermes_cli/blueprint_cmd.py:246`), which returns a `BlueprintCommandResult(text, agent_seed=None)`. Tokens are parsed with `shlex.split` (falling back to `.split()`), `tokens[0]` is the query and the rest is parsed as `key=value` pairs. `match_blueprint(query)` returns a blueprint or candidate list. With no slot values it returns `agent_seed = build_blueprint_seed(blueprint)` and text `Setting up '<title>' (<schedule>). I'll ask you a couple of things…`; the dispatch site (`run.py:19141`) sends that text as an ack through the adapter, sets `event.text = seed` and falls through to the agent (the `/steer` pattern). With slot values it calls `fill_blueprint` then `create_job_with_scheduler_registration(**spec)` directly.
- **Inputs / options:** `[name]`, `slot=value` pairs (quote-aware).
- **Outputs / side effects:** a cron job delivering back to this chat/thread. Replies: catalog listing, candidate list, no-match text, `Can't set up '<title>': <e>\nOr just run /blueprint <key> and I'll ask you for the values.`, `Failed to create the job: <e>`, `Automation Blueprints are unavailable in this build.`, `Cron blueprint command failed: <e>`.
- **Config / env:** blueprint catalog; cron scheduler.
- **Edge cases / guards:** if the seed cannot be assigned to `event.text` the handler returns the result text instead.
- **Rebuild notes:** two modes from one command — deterministic when fully specified, conversational when not.

### `/curator`  `id: gw-slash.curator`
- **Surface:** Gateway/Telegram (declared) — **not actually handled on the gateway**
- **Where:** documented as `/curator [status|run|pin|archive]` in the messaging table of `website/docs/reference/slash-commands.md:~290` and listed by `/help` as `` `/curator [subcommand]` -- Background skill maintenance (status, run, pin, archive, list-archived) ``.
- **What it does:** *intended*: background skill maintenance (status / run / pause / resume / pin / unpin / restore / list-archived).
- **How it works:** `CommandDef("curator", …, subcommands=("status","run","pause","resume","pin","unpin","restore","list-archived"), desktop="advanced")` (`hermes_cli/commands.py:341`) is **not** `cli_only`, so it appears in gateway help, the Telegram menu and Slack's native slashes — but `gateway/run.py` has neither a `_gateway_plain_command_handlers` entry nor a `canonical == "curator"` branch, and there is no `_handle_curator_command`. Because `"curator" ∈ GATEWAY_KNOWN_COMMANDS`, the unknown-command notice is also skipped (`run.py:19525`), so the literal text `/curator status` falls through to `_handle_message_with_agent` and is sent to the model as an ordinary user message.
- **Inputs / options:** `status`, `run`, `pause`, `resume`, `pin`, `unpin`, `restore`, `list-archived` — all inert on chat platforms.
- **Outputs / side effects:** whatever the LLM decides to do with the text `/curator status`; no curator state is touched deterministically.
- **Config / env:** `curator.*` (consumed by the background curator itself, `agent/curator.py`, invoked from the maintenance loop at `gateway/run.py:22 03`).
- **Edge cases / guards:** verified by enumeration — of the 66 gateway-available registry commands, `curator` is the only one with no handler.
- **Rebuild notes:** either add a handler or mark it `cli_only`; a command that is advertised in help but silently becomes prose is the worst of both worlds. A better version would fail loudly at startup when a gateway-available `CommandDef` has no resolvable handler.

### `/kanban <action>`  `id: gw-slash.kanban`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/kanban`, `/kanban list --mine`, `/kanban show t_abc`, `/kanban create "title" --assignee X`, `/kanban comment t_abc "text"`, `/kanban unblock t_abc`, `/kanban dispatch`, `/kanban boards switch <slug>`, `/kanban --board <slug> <action>`, `/kanban <sub> -h`.
- **What it does:** drives the multi-profile, multi-project collaboration board from chat with the same argument surface as the `hermes kanban` CLI.
- **How it works:** `_handle_kanban_command` (`gateway/slash_commands.py:459`), `busy_policy="dispatch"` (mutations included — the board is profile-agnostic and doesn't touch the running agent). Strips the leading `/kanban`, `shlex.split`s the rest, scans for `--board <slug>` / `--board=<slug>` to capture `requested_board` and identify the first positional as `action`. Runs `await asyncio.to_thread(run_slash, text)` (`hermes_cli/kanban.py:3467`), which for bare/`help`/`--help`/`-h`/`?` returns the curated `_SLASH_KANBAN_HELP` block instead of argparse's full tree, and otherwise drives a single argparse tree rooted at `/kanban` (per-subcommand `-h` still works, and `prog` is rewritten to `/kanban <name>` so usage text reads correctly). **Auto-subscribe on create:** the output is scanned with `re.search(r"Created\s+(t_[0-9a-f]+)\b", output)`; on a match it inserts a notify subscription via `kanban_db.add_notify_sub(conn, task_id, platform, chat_id, chat_type, thread_id, user_id, user_id_alt, notifier_profile, delivery_mode="notify+wake", delivery_metadata=<thread metadata + chat_type>)` — `user_id_alt` (Signal UUID, Feishu union_id) is persisted because `build_session_key` keys the participant on `user_id_alt or user_id`.
- **Inputs / options:** the 47 argparse subcommands in v2026.8.31 — `archive, assign, assignees, attach, attach-rm, attachments, block, boards, claim, comment, complete, context, create, daemon, decompose, diag, diagnostics, dispatch, edit, gc, heartbeat, init, link, list, log, ls, notify-list, notify-subscribe, notify-unsubscribe, promote, reassign, reclaim, reopen-review, repair, request-changes, request-review, runs, schedule, set-model, show, specify, stats, swarm, tail, unblock, unlink, watch` — plus the global `--board <slug>` / `--board=<slug>` and `--json`.
- **Outputs / side effects:** board mutations in the kanban DB; a notify subscription on create. Replies: the CLI's captured stdout/stderr; `⚠ kanban error: <error>`; `(no output)`; the create suffix `(subscribed — you'll be notified when <task_id> completes or blocks)`; output over 3800 chars is cut with `… (truncated; use `hermes kanban …` in your terminal for full output)`. The curated help block (verbatim) lists `list` (alias `ls`), `show <id>`, `stats`, `create <title>…`, `comment <id> <msg>`, `attach <id> <path>` (+`attachments <id>`), `complete <id>…`, `request-review <id>` / `request-changes <id> <reason>`, `block <id> [reason]` / `schedule <id> [reason]` / `unblock <id>`, `assign <id> <profile>`, `boards list`, `assignees`, `context <id>`, `runs <id>`, `log <id>`, and closes with `Run `/kanban <subcommand> -h` for arguments. Read-only commands are safe while an agent is running.`
- **Config / env:** kanban DB path/board config; `_kanban_notifier_profile` / active profile for the notifier.
- **Edge cases / guards:** `--json` invocations are NOT auto-subscribed ("they're clearly scripting"); subscribe failures log `kanban create auto-subscribe failed: %s` and do not fail the command. Wake messages use the `gateway.kanban.wake.*` templates — `[kanban] Task <id> <status>.\nTitle: <title>\nAssignee: @<assignee>\nBoard: <board>\n\nCheck the result or decide the next step.` with statuses `completed`, `gave up (retries exhausted)`, `crashed (worker exited); dispatcher will retry`, `timed out; dispatcher will retry`, `blocked; needs attention`, `handed off for review; the implementation is done`, `review requested changes (BLOCK); implementation is not approved`, `routed to triage after repeated blocks; needs a decision`, `status changed`.
- **Rebuild notes:** reuse the CLI's argparse tree verbatim, capture stdout, curate the bare-help output for chat bubbles, and auto-subscribe the originating chat on create.

---

## 4. Configuration commands

### `/model`  `id: gw-slash.model`
- **Surface:** Gateway/Telegram
- **Where:** any chat. Bare `/model` opens a provider→model picker on platforms with inline keyboards (Telegram/Discord); otherwise a text list. Typed forms: `/model claude-sonnet-4.6`, `/model zai:glm-5`, `/model custom:model`, `/model custom:local:qwen`, `/model custom`, `/model fav` (user alias), `/model gpt-5.5 --provider openrouter --global`, `/model --provider anthropic`, `/model x --once`, `/model x --session`, `/model --refresh`.
- **What it does:** shows or switches the model (and optionally the provider) for the session, the next turn only, or globally.
- **How it works:** `_handle_model_command` (`gateway/slash_commands.py:1751`), `busy_policy="reject"` with `busy_handler="model"` → mid-run reply `Agent is running — wait or /stop first, then switch models.` Flags are parsed by the single shared parser `parse_model_switch_args(raw_args)` (`hermes_cli/model_switch.py`) giving `target, explicit_provider, is_global, is_session, is_once, force_refresh, errors`; parse errors return `❌ <first error>`. `resolve_persist_behavior(is_global, is_session, is_once, explicit_provider)` decides whether the switch persists. `--refresh` calls `clear_provider_models_cache()`. Current model/provider/base_url are read from the profile-scoped `config.yaml` (`model.default`, `model.provider`, `model.base_url`, plus `providers`, `get_compatible_custom_providers(cfg)` and `model_catalog.excluded_providers`), then overridden by any session override. The source is normalised with `_normalize_source_for_session_key` before the override key is derived (#30479). **Picker path** (no target, no `--provider`): if the adapter type defines `send_model_picker`, `list_picker_providers(current_provider, current_base_url, current_model, user_providers, custom_providers, max_models=50, include_moa=True, excluded_providers=…)` runs in a thread (a cold cache can hit a synchronous 15 s HTTP fetch, #41289/#20525) and `adapter.send_model_picker(chat_id, providers, current_model, current_provider, session_key, on_model_selected, metadata)` renders it; a successful send returns `None`. **Text fallback:** `list_authenticated_providers(..., max_models=5)` renders `**<name>** `--provider <slug>`[ (current)]:` lines with up to 5 back-ticked model ids and a ` (+<n> more)` suffix, or the provider's `api_url`. **Switch path:** `_model_switch_skew_guard()` first (`slash_commands.py:72`) — if `detect_code_skew()` reports the gateway booted from a different revision than the checkout, it refuses with `Error: This gateway is running code from <boot> but the checkout on disk is now <disk>. Switching models would risk a stale-module crash — restart the gateway to load the new code: hermes gateway restart`. Then `switch_model(...)` runs in a thread; on failure `Error: <message>`. `enrich_model_switch_warnings_for_gateway` adds preflight-compression warnings. A **selection guard** (`combined_selection_warning`, cost + data-policy) may route through `_request_slash_confirm` with the message `⚠️ **<title>**\n\n<message>\n\n_Text fallback: reply `<p>approve` to switch or `<p>cancel` to keep the current model._`; `cancel` → `🟡 Model switch cancelled. Current model unchanged (<current>).`, both `once` and `always` proceed (there is no persistent opt-out for selection guards). `_finish_switch()` then: swaps the cached agent in place via `agent.switch_model(new_model, new_provider, api_key, base_url, api_mode, capabilities)` — a raised exception rolls the agent back and **aborts the whole commit** (`Error: Model switch to <m> failed (<exc>); staying on <old>.`, #50163); persists to the session DB (`update_session_model`); stores `_pending_model_notes[session_key] = "[Note: model was just switched from <old> to <new> via <provider label>. [This override applies to the next turn only. ]Adjust your self-identification accordingly.]"`; sets `_session_model_overrides[session_key] = {model, provider, api_key, base_url, api_mode, request_overrides, capabilities}`; for `--once` stores the restore snapshot in `_pending_one_turn_model_restores` and **skips** the write-through (#29923); otherwise write-throughs the non-secret parts via `async_session_store.set_model_override`; evicts the cached agent; and when persisting, rewrites `model.default` / `model.provider` (+ `base_url` / `api_mode` set-or-cleared for custom providers, #25107) after possibly dropping a stale `model.context_length` via `should_clear_context_pin_async`.
- **Inputs / options:** positional `[model]`; `--provider <slug>`; `--global`; `--session`; `--once`; `--refresh`. Model forms: bare name, `provider:model`, `custom:model`, `custom:<name>:<model>`, bare `custom` (auto-detect), user aliases from `model_aliases` / `model.aliases` (full form with `model`/`provider`/`base_url`/`key_env`/`api_key`, or short `provider/model`; aliases are case-insensitive and shadow built-in short names).
- **Outputs / side effects:** reply lines — `Model switched to `<model>``, `Provider: <label>`, `Context: <n> tokens`, `Max output: <n> tokens`, `Capabilities: <caps>`, `Prompt caching: enabled` (OpenRouter+claude or `api_mode == "anthropic_messages"`), `Warning: <warning>`, then one of `Saved to config.yaml (`--global`)`, `    (next turn only — restores after one response)`, or `_(session only — add `--global` to persist)_`. Bare text list header: `Current: `<model>` on <provider>` plus the three usage lines `` `/model <name>` — switch model ``, `` `/model <name> --provider <slug>` — switch provider ``, `` `/model <name> --global` — persist ``.
- **Config / env:** `model.default`, `model.provider`, `model.base_url`, `model.api_mode`, `model.context_length`, `model.persist_switch_by_default`, `model_catalog.excluded_providers`, `providers`, `custom_providers`, `model_aliases` / `model.aliases`, `moa` (picker shows MoA presets as a virtual provider).
- **Edge cases / guards:** `/model` can only switch between **already-configured** providers — adding one requires `hermes model` from a terminal. A mid-conversation switch resets the provider prompt cache (documented cost note). `api_key` is never persisted to the session store. Opaque Palantir RIDs are shortened for display by `format_model_for_display` while the override keeps the full id.
- **Rebuild notes:** one parser, one switch function, and an in-place agent swap that is atomic — a failed switch must be a complete no-op, not a half-committed override.

### `/codex-runtime` (alias `/codex_runtime`)  `id: gw-slash.codex-runtime`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/codex-runtime`, `/codex-runtime auto`, `/codex-runtime codex_app_server`, `/codex-runtime on`, `/codex-runtime off`.
- **What it does:** toggles the optional Codex app-server runtime for OpenAI/Codex models (native shell, apply_patch, ChatGPT-subscription auth, migrated Codex plugins) versus Hermes' standard chat-completions path.
- **How it works:** `_handle_codex_runtime_command` (`gateway/slash_commands.py:2538`), `busy_policy="reject"` with `busy_handler="codex-runtime"` → mid-run `Agent is running — wait or /stop first, then change runtime.` `crs.parse_args(raw)` (`hermes_cli/codex_runtime_switch.py:39`): empty → None (show state); `on|codex|enable` → `codex_app_server`; `off|default|disable|hermes` → `auto`; the literal values in `VALID_RUNTIMES = ("auto","codex_app_server")`; anything else → error `Unknown runtime '<raw>'. Use one of: auto, codex_app_server, on, off`. Then `crs.apply(cfg, new_value, persist_callback=save_config if changing)`, and on a real change with `requires_new_session` the cached agent is evicted so the next message builds a fresh `AIAgent` with the new `api_mode`.
- **Inputs / options:** `auto`, `codex_app_server`, `on`, `codex`, `enable`, `off`, `default`, `disable`, `hermes`, or nothing.
- **Outputs / side effects:** persists `model.openai_runtime`; reply is `✓ <result.message>` or `✗ <result.message>`; config load failure → `❌ Could not load config: <exc>`; parse errors → `❌ <e1>\n❌ <e2>…`.
- **Config / env:** `model.openai_runtime` (`auto` default).
- **Edge cases / guards:** effective on the next session/message; `/compress` has a dedicated Codex path (see `gw-slash.compress`).
- **Rebuild notes:** accept human synonyms, persist one key, evict the cache — and keep CLI and gateway on the same shared module.

### `/personality [name]`  `id: gw-slash.personality`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/personality`, `/personality pirate`, `/personality none` (also `default`, `neutral`).
- **What it does:** lists the configured personality overlays or applies one to the session's system prompt.
- **How it works:** `_handle_personality_command` (`gateway/slash_commands.py:2583`). All resolution/persistence goes through `hermes_cli.personality` (`available_personalities`, `active_personality_name`, `describe_personality`, `resolve_personality`, `persist_personality`, `prompt_text`). Bare → the list with a ` ✓` marker on the active one. With an argument, `resolve_personality(args, config)` raises `ValueError` for unknown names. `persist_personality(name)` writes the selection only — it never writes `agent.system_prompt` (user-owned manual overlay). Clearing sets `self._ephemeral_system_prompt = prompt_text(cfg.agent.system_prompt)`; setting stores the new prompt in `_ephemeral_system_prompt` so it takes effect on the very next message.
- **Inputs / options:** `[name]`; `none` / `default` / `neutral` clear.
- **Outputs / side effects:** replies — `🎭 **Available Personalities**\n` + `• `none` — (no personality overlay)` + per entry `• `<name>[ ✓]` — <preview>` + `\nUsage: `/personality <name>``; `No personalities configured in `<path>/config.yaml``; `Unknown personality: `<name>`\n\nAvailable: `none`, `a`, `b`…`; `🎭 Personality cleared — using base agent behavior.\n_(takes effect on next message)_`; `🎭 Personality set to **<name>**\n_(takes effect on next message)_`; `⚠️ Failed to save personality change: config write failed`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.personality.cleared` (`locales/en.yaml:210` → emitted at `gateway/slash_commands.py:2638`) — `/personality none` — `resolve_personality` returned an empty name, `persist_personality("")` succeeded and `self._ephemeral_system_prompt` was reset to the user's own `agent.system_prompt`:

    ```text
    🎭 Personality cleared — using base agent behavior.
    _(takes effect on next message)_
    ```

  - `gateway.personality.set_to` (`locales/en.yaml:211` → emitted at `gateway/slash_commands.py:2642`) — a known personality was resolved and persisted; `self._ephemeral_system_prompt` is swapped in memory so the overlay applies from the next message:

    ```text
    🎭 Personality set to **{name}**
    _(takes effect on next message)_
    ```

  - `gateway.personality.unknown` (`locales/en.yaml:212` → emitted at `gateway/slash_commands.py:2627`) — `resolve_personality` raised `ValueError`; `available` is built as ``"`none`, "`` plus every configured personality name in backticks:

    ```text
    Unknown personality: `{name}`

    Available: {available}
    ```
- **Config / env:** `personalities` in config.yaml; `agent.system_prompt`.
- **Edge cases / guards:** `argument_mode="options"` so desktop/TUI render a picker.
- **Rebuild notes:** never overwrite the user's own system prompt when applying a preset overlay.

### `/reasoning`  `id: gw-slash.reasoning`
- **Surface:** Gateway/Telegram
- **Where:** any chat. Bare `/reasoning` opens a choice picker where supported, else a status card. Typed: `/reasoning high`, `/reasoning none`, `/reasoning max --global`, `/reasoning reset`, `/reasoning show`, `/reasoning hide`, `/reasoning on`, `/reasoning off`.
- **What it does:** sets the model's reasoning-effort level (session or global) and toggles whether the model's thinking is shown in replies on this platform.
- **How it works:** `_handle_reasoning_command` (`gateway/slash_commands.py:3897`). `_parse_reasoning_command_args(raw)` strips `--global` from any position and normalises unicode dashes. The source is normalised before deriving the override key (#30479). Effort resolution uses the session's *effective* model so per-model `reasoning_overrides` display correctly. Bare form builds `level` (`medium (default)` when unset, `none (disabled)` when `enabled is False`, else the effort), `scope` (`session override` when `session_key ∈ _session_reasoning_overrides`, else `global config`), `display` (`on ✓` / `off`), then tries `_try_send_choice_picker` (`:3859`, gated on `type(adapter).send_choice_picker`) with the picker title and `_reasoning_picker_choices(current_effort)` (`:3831`): `none — disable reasoning`, then every entry of `VALID_REASONING_EFFORTS` as its own label, then `reset — clear session override`, `show reasoning in replies`, `hide reasoning from replies`; a successful send returns `None`. Typed and picked values share `_apply_reasoning_selection(session_key, platform_key, value, persist_global)` (`:3774`): `show|on` / `hide|off` set `self._show_reasoning` and save `display.platforms.<platform>.show_reasoning`; `reset` clears the session override (refused with `--global`); otherwise `parse_reasoning_effort(value)` validates and either saves `agent.reasoning_effort` globally or sets a session override — every path evicts the cached agent.
- **Inputs / options:** levels `none, minimal, low, medium, high, xhigh, max, ultra`; `reset`; display `show|on|hide|off`; the registry also advertises `full` and `clamp` in `args_hint`/`subcommands`; flag `--global`.
- **Outputs / side effects:** `🧠 **Reasoning Settings**\n\n**Effort:** `<level>`\n**Scope:** <scope>\n**Display:** <display>\n\n_Usage:_ `/reasoning <none|minimal|low|medium|high|xhigh|max|ultra|reset|show|hide> [--global]``; `🧠 ✓ Reasoning display: **ON**\nModel thinking will be shown before each response on **<platform>**.`; `🧠 ✓ Reasoning display: **OFF** for **<platform>**`; `⚠️ `/reasoning reset --global` is not supported. Use `/reasoning <level> --global` to change the global default.`; `🧠 ✓ Session reasoning override cleared; falling back to global config.`; `⚠️ Unknown argument: `<arg>`\n\n**Valid levels:** none, minimal, low, medium, high, xhigh, max, ultra\n**Display:** show, hide\n**Persist:** add `--global` to save beyond this session`; `🧠 ✓ Reasoning effort set to `<effort>` (saved to config)\n_(takes effect on next message)_`; `🧠 ✓ Reasoning effort set to `<effort>` (session only — config save failed)\n_(takes effect on next message)_`; `🧠 ✓ Reasoning effort set to `<effort>` (session only — add `--global` to persist)\n_(takes effect on next message)_`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.reasoning.status` (`locales/en.yaml:223` → emitted at `gateway/slash_commands.py:3978`) — text status card for bare `/reasoning`, returned when no inline picker could be sent; `level` is the effort or `medium (default)` / `none (disabled)`, `scope` is `session override` or `global config`, `display` is `on ✓` or `off`:

    ```text
    🧠 **Reasoning Settings**

    **Effort:** `{level}`
    **Scope:** {scope}
    **Display:** {display}

    _Usage:_ `/reasoning <none|minimal|low|medium|high|xhigh|max|ultra|reset|show|hide> [--global]`
    ```

  - `gateway.reasoning.display_set_on` (`locales/en.yaml:226` → emitted at `gateway/slash_commands.py:3797`) — `/reasoning show` (or `on`) — sets `self._show_reasoning = True` and persists `display.platforms.<platform>.show_reasoning: true`:

    ```text
    🧠 ✓ Reasoning display: **ON**
    Model thinking will be shown before each response on **{platform}**.
    ```

  - `gateway.reasoning.unknown_arg` (`locales/en.yaml:230` → emitted at `gateway/slash_commands.py:3815`) — `parse_reasoning_effort(value)` returned None — the argument was not a level, not `show`/`hide`/`on`/`off` and not `reset`:

    ```text
    ⚠️ Unknown argument: `{arg}`

    **Valid levels:** none, minimal, low, medium, high, xhigh, max, ultra
    **Display:** show, hide
    **Persist:** add `--global` to save beyond this session
    ```

  - `gateway.reasoning.picker_title` (`locales/en.yaml:231` → emitted at `gateway/slash_commands.py:3966`) — title of the inline choice picker built by `_reasoning_picker_choices(current_effort)` (one button per level plus `none — disable reasoning`, `reset — clear session override`, `show reasoning in replies`, `hide reasoning from replies`):

    ```text
    🧠 **Reasoning Settings**

    **Effort:** `{level}`
    **Scope:** {scope}
    **Display:** {display}

    Pick an option:
    ```

  - `gateway.reasoning.set_global` (`locales/en.yaml:236` → emitted at `gateway/slash_commands.py:3822`) — `/reasoning <level> --global` and the `agent.reasoning_effort` config write succeeded; the session override is cleared and the cached agent evicted:

    ```text
    🧠 ✓ Reasoning effort set to `{effort}` (saved to config)
    _(takes effect on next message)_
    ```

  - `gateway.reasoning.set_global_save_failed` (`locales/en.yaml:237` → emitted at `gateway/slash_commands.py:3825`) — `--global` was requested but `_save_gateway_config_key("agent.reasoning_effort", value)` returned False — the parsed effort is still applied as a session override so the user's choice is not silently lost:

    ```text
    🧠 ✓ Reasoning effort set to `{effort}` (session only — config save failed)
    _(takes effect on next message)_
    ```

  - `gateway.reasoning.set_session` (`locales/en.yaml:238` → emitted at `gateway/slash_commands.py:3829`) — plain `/reasoning <level>` — `_set_session_reasoning_override(session_key, parsed)` plus cache eviction, with the `--global` hint for persistence:

    ```text
    🧠 ✓ Reasoning effort set to `{effort}` (session only — add `--global` to persist)
    _(takes effect on next message)_
    ```
- **Config / env:** `agent.reasoning_effort`, `display.platforms.<platform>.show_reasoning`, per-model `reasoning_overrides`.
- **Edge cases / guards:** `full` / `clamp` appear in the command definition but are not handled by `_apply_reasoning_selection` — `parse_reasoning_effort` decides whether they resolve; anything it rejects yields the "Unknown argument" card (see `gw-slash.docs-reconciliation`). A failed global write degrades to a session override rather than silently dropping the choice.
- **Rebuild notes:** one applier shared by the typed path and the picker; report honestly when persistence failed.

### `/fast`  `id: gw-slash.fast`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/fast`, `/fast fast`, `/fast normal`, `/fast status`, `/fast on`, `/fast off`, `/fast fast --global`.
- **What it does:** toggles OpenAI Priority Processing / Anthropic Fast Mode for the session (or globally).
- **How it works:** `_handle_fast_command` (`gateway/slash_commands.py:4092`). Reuses `_parse_reasoning_command_args` so `--global` works in any position. `model_supports_fast_mode(_resolve_gateway_model(config))` gates the whole command. Bare/`status` renders the current mode and tries `_try_send_choice_picker` with two choices; a successful send returns `None`. `_apply_fast_selection(value, persist)`: `fast|on` → `service_tier="priority"`, saved value `fast`, label `FAST`; `normal|off` → `tier=None`, saved value `normal`, label `NORMAL`; anything else → the unknown-argument card. With `--global` it writes `agent.service_tier` and clears any session override; a failed write falls back to a session override. Every path evicts the cached agent.
- **Inputs / options:** `normal`, `fast`, `status`, `on`, `off`, `--global`.
- **Outputs / side effects:** `⚡ /fast is only available for OpenAI models that support Priority Processing.`; `⚡ Priority Processing\n\nCurrent mode: `<fast|normal>`\n\n_Usage:_ `/fast <normal|fast|status>``; `⚠️ Unknown argument: `<arg>`\n\n**Valid options:** normal, fast, status`; `⚡ ✓ Priority Processing: **FAST|NORMAL** (saved to config)\n_(takes effect on next message)_`; `⚡ ✓ Priority Processing: **FAST|NORMAL** (this session only)`; picker title `⚡ **Priority Processing**\n\nCurrent mode: `<mode>`\n\nPick an option:` with choices `fast — Priority Processing on` and `normal — standard processing`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.fast.status` (`locales/en.yaml:144` → emitted at `gateway/slash_commands.py:4173`) — text status card for `/fast` or `/fast status`, returned when the platform cannot render an inline choice picker (`_try_send_choice_picker` returned False); `mode` is `fast` or `normal`:

    ```text
    ⚡ Priority Processing

    Current mode: `{mode}`

    _Usage:_ `/fast <normal|fast|status>`
    ```

  - `gateway.fast.unknown_arg` (`locales/en.yaml:145` → emitted at `gateway/slash_commands.py:4126`) — `_apply_fast_selection` fell through: the argument was neither `fast`/`on` nor `normal`/`off`:

    ```text
    ⚠️ Unknown argument: `{arg}`

    **Valid options:** normal, fast, status
    ```

  - `gateway.fast.saved` (`locales/en.yaml:146` → emitted at `gateway/slash_commands.py:4135`) — `/fast <mode> --global` succeeded — `agent.service_tier` was written to `~/.hermes/config.yaml` (`fast` → provider `service_tier=priority`), the session override was cleared and the cached agent evicted; `label` is `FAST` or `NORMAL`:

    ```text
    ⚡ ✓ Priority Processing: **{label}** (saved to config)
    _(takes effect on next message)_
    ```

  - `gateway.fast.picker_title` (`locales/en.yaml:152` → emitted at `gateway/slash_commands.py:4155`) — title of the two-button inline picker (`fast — Priority Processing on` / `normal — standard processing`) sent on button-capable adapters instead of the text status card:

    ```text
    ⚡ **Priority Processing**

    Current mode: `{mode}`

    Pick an option:
    ```
- **Config / env:** `agent.service_tier` (`fast` | `normal`).
- **Edge cases / guards:** the support check runs before argument handling, so even `/fast status` is refused on unsupported models.
- **Rebuild notes:** same picker/applier split as `/reasoning`; gate on model capability first.

### `/voice`  `id: gw-slash.voice`
- **Surface:** Gateway/Telegram | Platform:discord
- **Where:** any chat: `/voice`, `/voice on|enable`, `/voice off|disable`, `/voice tts`, `/voice status`, `/voice channel|join`, `/voice leave`.
- **What it does:** controls spoken replies per chat: off, reply-with-voice-to-voice, or TTS for every reply; on Discord it also joins/leaves a live voice channel.
- **How it works:** `_handle_voice_command` (`gateway/slash_commands.py:3345`). The mode is stored per `(platform, chat_id)` in `self._voice_mode` (`off` | `voice_only` | `all`) and persisted with `_save_voice_modes()`; each change also flips the adapter's auto-TTS flag (`_set_adapter_auto_tts_enabled` / `_set_adapter_auto_tts_disabled`). `channel|join` → `_handle_voice_channel_join` (`gateway/run.py:23804`): requires `adapter.join_voice_channel` (`Voice channels are not supported on this platform.`), a guild (`This command only works in a Discord server.`) and the user to be in a channel (`You need to be in a voice channel first.`); wires `_voice_input_callback` / `_on_voice_disconnect` / `_voice_mode_getter` **before** joining so early audio isn't lost, then joins; on success it records the text channel + source, sets mode `all`, enables auto-TTS and replies `Joined voice channel **<name>**.\nI'll speak my replies and listen to you. Use /voice leave to disconnect.`; on failure `Failed to join voice channel. Check bot permissions (Connect + Speak).`, and PyNaCl/davey errors give `Voice dependencies are missing (PyNaCl / davey). Install with: `<python> -m pip install PyNaCl``, other exceptions `Failed to join voice channel: <e>`. `leave` → `_handle_voice_channel_leave` (`run.py:23862`): `Not in a voice channel.` when there is no guild/method or `is_in_voice_channel()` is false, otherwise leaves, forces mode `off`, disables auto-TTS, clears the input callback and replies `Left voice channel.` Bare `/voice` toggles off↔voice_only and appends the help block.
- **Inputs / options:** `on`, `enable`, `off`, `disable`, `tts`, `status`, `channel`, `join`, `leave`, or nothing.
- **Outputs / side effects:** `Voice mode enabled.\nI'll reply with voice when you send voice messages.\nUse /voice tts to get voice replies for all messages.`; `Voice mode disabled. Text-only replies.`; `Auto-TTS enabled.\nAll replies will include a voice message.`; status — `Voice mode: <Off (text only)|On (voice reply to voice messages)|TTS (voice reply to all messages)>` and, when a Discord voice channel is connected, additionally `Voice channel: #<name>`, `Participants: <n>` and per member `  - <display_name>[ (speaking)]`. Bare toggle returns `<Voice mode enabled.|Voice mode disabled.>\n\n**How /voice works**\n• `/voice on` — voice reply when you send a voice message\n• `/voice tts` — voice reply to *every* message\n• `/voice off` — back to text-only replies\n• `/voice status` — show the current mode\n• `/voice` (no argument) — quick toggle between on and off` plus, on adapters exposing `join_voice_channel`, `\n\n**Live voice channels (Discord)**\n• Join a voice channel first, then `/voice channel` — I'll join, listen, and speak my replies\n• `/voice leave` — disconnect from the voice channel`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.voice.enabled_voice_only` (`locales/en.yaml:447` → emitted at `gateway/slash_commands.py:3359`) — `/voice on` or `/voice enable` — mode `voice_only` stored for `(platform, chat_id)`, `_save_voice_modes()` persists it and `_set_adapter_auto_tts_enabled(adapter, chat_id, enabled=True)` arms adapter-side TTS; the third line cross-sells `/voice tts`:

    ```text
    Voice mode enabled.
    I'll reply with voice when you send voice messages.
    Use /voice tts to get voice replies for all messages.
    ```

  - `gateway.voice.tts_enabled` (`locales/en.yaml:449` → emitted at `gateway/slash_commands.py:3371`) — `/voice tts` — mode `all` stored and persisted the same way, so every reply is additionally delivered as a voice message:

    ```text
    Auto-TTS enabled.
    All replies will include a voice message.
    ```

  - `gateway.voice.help` (`locales/en.yaml:460` → emitted at `gateway/slash_commands.py:3424`) — returned by BARE `/voice`, which first toggles `off ↔ voice_only` and then appends this discoverability explainer; `{toggle}` is `gateway.voice.enabled_short` (`Voice mode enabled.`) or `gateway.voice.disabled_short` (`Voice mode disabled.`):

    ```text
    {toggle}

    **How /voice works**
    • `/voice on` — voice reply when you send a voice message
    • `/voice tts` — voice reply to *every* message
    • `/voice off` — back to text-only replies
    • `/voice status` — show the current mode
    • `/voice` (no argument) — quick toggle between on and off{channels}
    ```

  - `gateway.voice.help_channels` (`locales/en.yaml:461` → emitted at `gateway/slash_commands.py:3422`) — substituted into `{channels}` only when the platform adapter exposes `join_voice_channel` (Discord); otherwise `{channels}` is the empty string:

    ```text


    **Live voice channels (Discord)**
    • Join a voice channel first, then `/voice channel` — I'll join, listen, and speak my replies
    • `/voice leave` — disconnect from the voice channel
    ```
- **Config / env:** persisted voice-mode store; `voice.*` TTS/STT settings (sibling shard).
- **Edge cases / guards:** an adapter-side inactivity timeout calls `_handle_voice_timeout_cleanup(chat_id)` which forces the mode back to `off`. The registry's `args_hint` is `[on|off|tts|status]` — `channel`/`join`/`leave` are handled but undocumented there.
- **Rebuild notes:** wire input callbacks before joining; clean up state even when leaving raises.

### `/yolo`  `id: gw-slash.yolo`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** toggles YOLO mode — all dangerous-command approvals are auto-approved **for this session only**.
- **How it works:** `_handle_yolo_command` (`gateway/slash_commands.py:4194`), `busy_policy="dispatch"`. Reads `tools.approval.is_session_yolo_enabled(session_key)` and flips via `disable_session_yolo` / `enable_session_yolo`.
- **Inputs / options:** none (pure toggle).
- **Outputs / side effects:** `EphemeralReply("⚡ YOLO mode **ON** for this session — all commands auto-approved. Use with caution.")` / `EphemeralReply("⚠️ YOLO mode **OFF** for this session — dangerous commands will require approval.")`
- **Config / env:** none persisted — session-scoped in-memory state, cleared at a conversation boundary by `_clear_conversation_scope`.
- **Edge cases / guards:** deliberately not persistent; the persistent equivalent is `/approvals off`.
- **Rebuild notes:** keep the dangerous toggle session-scoped and ephemeral, and say so in the reply.

### `/approvals [manual|smart|off]`  `id: gw-slash.approvals`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/approvals`, `/approvals manual`, `/approvals smart`, `/approvals off`.
- **What it does:** shows or persists the profile-wide dangerous-command approval mode.
- **How it works:** `_handle_approvals_command` (`gateway/slash_commands.py:4177`). Because this mutates profile-wide security policy and the central gate may allow selected commands to non-admins, it re-checks admin at the side-effect boundary: `policy_for_source(self.config, source).is_admin(user_id)` — a non-admin passing an argument gets `Only gateway admins can change the persistent approval mode.` Then `run_approval_mode_command(requested)` (`hermes_cli/approval_mode.py:34`) which reads the effective mode, validates against `VALID_APPROVAL_MODES`, and writes through `set_config_value("approvals.mode", requested)` with stdout/stderr captured so a managed-scope `SystemExit` or a fail-closed `RuntimeError` becomes a message instead of killing the worker. The cached agent is deliberately **not** evicted (approval checks load config dynamically, and touching the system prompt/tool schema would break the prompt-cache prefix).
- **Inputs / options:** `manual`, `smart`, `off`; bare shows the state.
- **Outputs / side effects:** `Approval mode: <mode> (persistent profile setting).`; `Usage: /approvals [manual|smart|off]`; managed policy → the captured stderr text or `Approval mode is managed and cannot be changed.`; `Failed to save approval mode: <exc>`; `Approval mode remains <effective>; the requested value did not become effective.`
- **Config / env:** `approvals.mode`.
- **Edge cases / guards:** unconfigured slash policies remain unrestricted (the admin re-check is a no-op then).
- **Rebuild notes:** re-authorise at the mutation site, not only at the dispatch gate; never invalidate the prompt cache for a policy read.

### `/busy [queue|steer|interrupt|status]`  `id: gw-slash.busy`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/busy`, `/busy status`, `/busy queue`, `/busy steer`, `/busy interrupt`.
- **What it does:** decides what happens to a plain message sent while Hermes is working — queue it for the next turn, steer it into the current run after the next tool call, or interrupt immediately.
- **How it works:** `_handle_busy_command` (`gateway/slash_commands.py:4275`), `busy_policy="dispatch"`. Bare/`status` reports `self._effective_busy_input_mode(source)`. Unknown values are rejected. A valid value is persisted **before** mutating live state via `save_config_value("display.busy_input_mode", arg)`; on success, when a profile name resolves it re-snapshots the profile's busy modes from `_load_gateway_runtime_config()`, otherwise it sets `self._busy_input_mode` and re-derives `self._busy_text_mode = self._load_busy_text_mode()` (without this the config was saved but the live session kept interrupting until restart); finally the source's adapter gets `adapter._busy_text_mode = self._effective_busy_text_mode(source)`.
- **Inputs / options:** `queue`, `steer`, `interrupt`, `status`, or nothing.
- **Outputs / side effects:** `EphemeralReply("**Busy input mode: `<mode>`\nMessages while busy: _<behavior>_\nChange with `/busy queue`, `/busy steer`, or `/busy interrupt`.")` where behaviour is `queues for next turn` / `steers into current run (after next tool call)` / `interrupts current run`; `EphemeralReply("Unknown mode `<arg>`. Use `/busy queue`, `/busy steer`, or `/busy interrupt`.")`; `EphemeralReply("Busy input mode set to **`<arg>`** (saved).\n_<behavior sentence>_")` where the sentences are `Messages will be queued for the next turn while Hermes is busy.` / `Messages will be steered into the current run (after the next tool call).` / `Messages will interrupt the current run while Hermes is busy.`; failure → `EphemeralReply("Busy input mode could not be saved to config. Mode unchanged.")`
- **Config / env:** `display.busy_input_mode`.
- **Edge cases / guards:** `queue` mode also changes what happens during a gateway drain and for Telegram follow-up bursts (`gateway/run.py:18700`+).
- **Rebuild notes:** persist first, then update every live copy of the derived state (runner, adapter) — a half-applied mode is worse than none.

### `/footer [on|off|status]`  `id: gw-slash.footer`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/footer`, `/footer on|enable|true|1`, `/footer off|disable|false|0`, `/footer status|?`.
- **What it does:** toggles the runtime-metadata footer appended to final replies (model, context %, cwd).
- **How it works:** `_handle_footer_command` (`gateway/slash_commands.py:4344`), `busy_policy="dispatch"`. Note: the argument is parsed from `getattr(event, "message", None)` (not `get_command_args()`), splitting the raw text once. `resolve_footer_config(user_config, platform_key)` gives the effective state and field list; the toggle writes the **global** `display.runtime_footer.enabled` with `atomic_config_write`, leaving per-platform overrides under `display.platforms.<platform>.runtime_footer` untouched (edit config.yaml for those). When enabling, a preview is rendered via `format_runtime_footer(model=<resolved gateway model>, context_tokens=0, context_length=None, fields=<effective or ["model","context_pct","cwd"]>)`.
- **Inputs / options:** `on|enable|true|1`, `off|disable|false|0`, `status|?`, bare (toggle).
- **Outputs / side effects:** `📎 Runtime footer: **ON|OFF**\nFields: `<f1, f2>`\nPlatform: `<platform>``; `Usage: `/footer [on|off|status]``; `📎 Runtime footer: **ON|OFF**[\nExample: `<preview>`]\n_(saved globally — takes effect on next message)_`; `⚠️ Could not read config.yaml: <error>`; `⚠️ Could not save config: <error>` (logged `Failed to save runtime_footer.enabled: %s`).
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.footer.status` (`locales/en.yaml:157` → emitted at `gateway/slash_commands.py:4387`) — `/footer status` (or `/footer ?`) — reads the effective per-platform footer via `resolve_footer_config(user_config, platform_key)`; `state` is `ON`/`OFF`, `fields` the comma-joined enabled field list, `platform` the `_platform_config_key()` value:

    ```text
    📎 Runtime footer: **{state}**
    Fields: `{fields}`
    Platform: `{platform}`
    ```

  - `gateway.footer.saved` (`locales/en.yaml:159` → emitted at `gateway/slash_commands.py:4428`) — after `display.runtime_footer.enabled` was written globally with `atomic_config_write`; when the new state is ON, `{example}` is filled with `gateway.footer.example_line` — `\nExample: `<preview>`` — rendered by `format_runtime_footer(...)`:

    ```text
    📎 Runtime footer: **{state}**{example}
    _(saved globally — takes effect on next message)_
    ```
- **Config / env:** `display.runtime_footer.enabled`, `display.runtime_footer.fields`, `display.platforms.<platform>.runtime_footer`.
- **Edge cases / guards:** the status form reports the *effective* (per-platform-resolved) state while the toggle only writes the global flag — a per-platform override can make the two disagree.
- **Rebuild notes:** show a live preview when enabling a display feature; say explicitly which scope you wrote.

### `/verbose`  `id: gw-slash.verbose`
- **Surface:** Gateway/Telegram | Config-gated
- **Where:** any chat, no arguments — each invocation advances the mode.
- **What it does:** cycles the per-platform tool-progress display through off → new → all → verbose → log → off.
- **How it works:** `_handle_verbose_command` (`gateway/slash_commands.py:4211`), `busy_policy="dispatch"`. The `CommandDef` is `cli_only=True` with `gateway_config_gate="display.tool_progress_command"` (`hermes_cli/commands.py:277`), so it only appears in gateway help/menus when that key is truthy — but the handler exists regardless and re-checks the gate itself. The current effective mode comes from `resolve_display_setting(user_config, platform_key, "tool_progress", "all")` (`gateway/display_config.py`); unknown values snap to `all`; the next mode is `cycle[(index+1) % 5]` where `cycle = ["off","new","all","verbose","log"]`. The new value is written to `display.platforms.<platform>.tool_progress` with `atomic_config_write`.
- **Inputs / options:** none.
- **Outputs / side effects:** one of `⚙️ Tool progress: **OFF** — no tool activity shown.`, `⚙️ Tool progress: **NEW** — shown when tool changes (preview length: `display.tool_preview_length`, default 40).`, `⚙️ Tool progress: **ALL** — every tool call shown (preview length: `display.tool_preview_length`, default 40).`, `⚙️ Tool progress: **VERBOSE** — every tool call with full arguments.`, `⚙️ Tool progress: **LOG** — silent in chat; tool calls written to ~/.hermes/logs/tool_calls.log.` — followed by `_(saved for **<platform>** — takes effect on next message)_` or `_(could not save to config: <error>)_`. Gate off → `The `/verbose` command is not enabled for messaging platforms.\n\nEnable it in `config.yaml`:\n```yaml\ndisplay:\n  tool_progress_command: true\n```` .
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.verbose.not_enabled` (`locales/en.yaml:437` → emitted at `gateway/slash_commands.py:4236`) — the `display.tool_progress_command` gate is falsy (its default), so the off → new → all → verbose → log cycle is refused with the exact YAML needed to enable it:

    ~~~text
    The `/verbose` command is not enabled for messaging platforms.

    Enable it in `config.yaml`:
    ```yaml
    display:
      tool_progress_command: true
    ```
    ~~~
- **Config / env:** `display.tool_progress_command` (gate), `display.platforms.<platform>.tool_progress`, `display.tool_preview_length`.
- **Edge cases / guards:** the docs/registry describe a 4-step cycle ("off → new → all → verbose") but the implementation cycles **five** modes including `log` (see `gw-slash.docs-reconciliation`).
- **Rebuild notes:** per-platform verbosity is the right granularity for a multi-platform gateway; keep the gate so noisy tool spam is opt-in on chat.

### `/memory`  `id: gw-slash.memory`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/memory`, `/memory pending`, `/memory approve <id>`, `/memory approve all`, `/memory reject <id>`, `/memory approval on|off`.
- **What it does:** reviews memory writes staged by the write-approval gate and toggles the gate itself.
- **How it works:** `_handle_memory_command` (`gateway/slash_commands.py:3990`). Args are whitespace-split and handed to `handle_pending_subcommand(wa.MEMORY, args, memory_store=load_on_disk_store(), set_mode_fn=_set_approval)` (`hermes_cli/write_approval_commands.py:54`). `_set_approval(enabled)` does a raw config round-trip (`read_user_config_raw` → `memory.write_approval` → `atomic_config_write`) and evicts the cached agent so the setting applies next message. The store is loaded fresh from disk because the gateway has no long-lived agent; it honours the user's configured char limits and persists to the same `MEMORY/USER.md`.
- **Inputs / options:** `pending`; `approve|apply <id|all>`; `reject|deny|drop <id|all>`; `approval|mode <on|true|yes|1|enable|enabled | off|false|no|0|disable|disabled>`.
- **Outputs / side effects:** bare → `memory.write_approval = on|off` + blank + the pending list; pending list → `No pending memory writes.` or `Pending memory writes (<n>):` + `  <id>[ [auto]]  <summary>` + blank + `Apply: /memory approve <id>   Reject: /memory reject <id>`; approve → `Approved <n> memory write(s).` (+ `Failed:` lines `  <id>: <msg>`) or `No pending memory writes.` / `No pending memory write with id '<id>'.` / `Usage: /memory approve <id>`; reject → `Rejected <n> pending memory write(s).` / `Rejected pending memory write '<id>'.` / `No pending memory write with id '<id>'.`; approval → `memory.write_approval = on|off\nSet with: /memory approval <on|off>` or `memory.write_approval set to 'on|off'.` or `Invalid value '<arg>'. Use: on or off.` or `Failed to set memory.write_approval: <e>`; unknown verb → `Unknown /memory subcommand. Use: pending, approve <id>, reject <id>, approval <on|off>.`
- **Config / env:** `memory.write_approval`.
- **Edge cases / guards:** `[auto]` marks entries whose `origin == "background_review"` (i.e. staged by `/refine` or the automatic post-turn review).
- **Rebuild notes:** one shared pending-review module for every gated subsystem; the surface only supplies the persistence callback.

### `/skills` (gateway subset)  `id: gw-slash.skills`
- **Surface:** Gateway/Telegram | Config-gated
- **Where:** any chat: `/skills`, `/skills pending`, `/skills approve <id>`, `/skills reject <id>`, `/skills diff <id>`, `/skills approval on|off`.
- **What it does:** on chat platforms, `/skills` is **only** the write-approval review surface for staged skill writes — search/browse/install stay CLI-only.
- **How it works:** `_handle_skills_command` (`gateway/slash_commands.py:4031`). The `CommandDef` is `cli_only=True` with `gateway_config_gate="skills.write_approval"` (`hermes_cli/commands.py:319`). The handler adds its own soft gate: when the gate is off, the caller isn't toggling it (`args[0] ∈ {"approval","mode"}`) and `wa.pending_count(wa.SKILLS) == 0`, it returns `Skill write approval is off (skills.write_approval). Enable it with /skills approval on, then review staged writes here with /skills pending.` — so staged writes are never stranded after the gate is turned off. Otherwise it delegates to the same `handle_pending_subcommand(wa.SKILLS, args, set_mode_fn=…)` with a `_set_approval` that writes `skills.write_approval` and evicts the cached agent.
- **Inputs / options:** `pending`, `approve|apply <id|all>`, `reject|deny|drop <id|all>`, `diff <id>`, `approval|mode <on|off>`.
- **Outputs / side effects:** the same templates as `/memory` with `skills` substituted, plus `Review full diff: /skills diff <id>` on the pending list; `diff` returns `# Pending skill write <id>: <summary>\n\n<diff>` or `Usage: /skills diff <id>` / `No pending skill write with id '<id>'.` A diff longer than 3000 chars is cut to `out[:3000] + "\n… (truncated — full diff in ~/.hermes/pending/skills/<id>.json)"`. Unknown verb → `Unknown /skills subcommand on this platform. Use: pending, approve <id>, reject <id>, diff <id>, approval <on|off>. (Search/install are CLI-only.)`
- **Config / env:** `skills.write_approval`; staged writes live in `~/.hermes/pending/skills/<id>.json`.
- **Edge cases / guards:** the docstring notes this `diff <id>` is the *write-approval* diff, distinct from the CLI's `hermes skills diff <name>` (bundled-vs-stock).
- **Rebuild notes:** never strand pending items behind a gate you just turned off.

---

## 5. Information, session-browsing and maintenance commands

### `/status`  `id: gw-slash.status`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments. Header `📊 **Hermes Gateway Status**`.
- **What it does:** shows the current session's id, title, timestamps, model, context usage, lifetime token spend, whether an agent is running, queued follow-ups, Matrix scope details, and the connected platforms.
- **How it works:** `_handle_status_command` (`gateway/slash_commands.py:576`), `busy_policy="dispatch"` and dispatched **before** the access gate on the busy path so state is always visible. Token totals come from the SQLite session row (`input+output+cache_read+cache_write+reasoning`), never from `SessionEntry.total_tokens` (which is always 0 because per-turn deltas are persisted by `run_agent.py`). Model/context resolution cascades: live running agent → cached agent (`_agent_cache` under lock) → `get_dominant_session_model_route(session_id)` (`billing_provider` / `billing_base_url`) → the session row's `model`/`billing_provider` → `_load_gateway_config()` + `_resolve_gateway_model()` + `model.context_length`. Context percent = `min(100, round(used/total*100))`. Queue depth from `_queue_depth(session_key, adapter)`.
- **Inputs / options:** none.
- **Outputs / side effects:** read-only. Lines: `📊 **Hermes Gateway Status**`, blank, `**Session ID:** `<id>``, optional `**Title:** <title>`, `**Created:** <YYYY-MM-DD HH:MM>`, `**Last Activity:** <YYYY-MM-DD HH:MM>`, optional `**Model:** `<model>`` or `**Model:** `<model>` (<provider>)`, optional `**Context:** <used> / <total> (<pct>%)` or `**Context:** ~<used> tokens`, `**Lifetime tokens billed:** <n> _(not your current context size; use `/context`)_`, `**Agent Running:** Yes ⚡|No`, optional `**Queued follow-ups:** <n>`; on Matrix additionally blank + `**Matrix scope:**` / `  room: <name>` / `  room_id: <id>` / `  thread_id: <id|none>` / `  session_scope: <scope>` / `  session_key: sha256:<12 hex>`; then blank + `**Connected Platforms:** <a, b, c>`.
- **Config / env:** `MATRIX_SESSION_SCOPE` (or the adapter's `_matrix_session_scope`, default `auto`); `model.context_length`.
- **Edge cases / guards:** the Matrix session key is redacted through `_redact_matrix_session_key` (`slash_commands.py:774`, `sha256:` + first 12 hex chars) because a shared room's status is visible to everyone. On Slack `/status` is a reserved built-in — use `/hermes status` or `!status`.
- **Rebuild notes:** never show a token counter without saying whether it is context or lifetime spend; this reply does both and cross-links `/context`.

### `/context [all]` (alias `/ctx`)  `id: gw-slash.context`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/context`, `/context all` (also `full`, `details`). Header `🧠 **Context Window**`.
- **What it does:** the deep context-window view — a usage gauge, auto-compression threshold and headroom, compression count and last savings, cumulative throughput, and an estimated per-category breakdown; `all` adds per-skill and per-toolset cost listings.
- **How it works:** `_handle_context_command` (`gateway/slash_commands.py:780`), `busy_policy="dispatch"`, pre-gate on the busy path. Resolution cascade: running agent → cached agent → `SessionStore.last_prompt_tokens` for `used`; `agent.model` → session row `model`; `compressor.context_length` → `_resolve_gateway_model_context(model)` (inside `_profile_runtime_scope` when multiplexed) → `get_model_context_length(model)`. The gauge is a 24-cell bar: `filled = round(pct/100*24)`, `"█"*filled + "░"*(24-filled)`. Compression/throughput lines require a live compressor. The category breakdown comes from `_context_breakdown_block(agent, source, expanded)` (`:5578`) → `compute_session_context_breakdown` + `render_context_breakdown_lines(..., grid=False)` (plain text — monospace isn't guaranteed on chat platforms); `expanded` adds `compute_context_details(agent)` (per-skill index vs SKILL.md load cost, per-toolset schema tokens). Last resort: a rough transcript estimate via `estimate_messages_tokens_rough`.
- **Inputs / options:** `all` | `full` | `details`.
- **Outputs / side effects:** read-only. Gauge block: `🧠 **Context Window**`, blank, `Model: `<model|?>``, `Window: <total> tokens`, `In use: <used> / <total> (<pct>%)`, `<bar>`, `Headroom to limit: <n> tokens`; then blank + either `Auto-compresses at: <threshold> (<pct>%) — <to_go> to go` or `⚠️ **Over auto-compression threshold (<threshold>, <pct>%)**`; `Compressions this session: <n>`; `Last compression freed: <n>% of context`; blank + `Session totals (cumulative across <n> API calls)` + `Input <n> · Output <n> · Reasoning <n>` + `Total billed: <n>` + `_Throughput, not context size — each call re-sends the window above._`; without a live compressor, `_(Full compression and throughput stats available after the first agent response)_`. Estimate fallback: `🧠 **Context Window**`, blank, `Estimated context: ~<n> tokens across <m> messages`, `_(Full compression and throughput stats…)_`. Nothing at all → `No context data available yet. Send a message to start a session.`
- **Config / env:** compression threshold settings; model context length.
- **Edge cases / guards:** the breakdown is fail-open — any exception returns `[]` and the gauge still renders.
- **Rebuild notes:** label throughput explicitly so users stop confusing cumulative tokens with context size; compute the breakdown in a thread and never let it break the gauge.

### `/whoami`  `id: gw-slash.whoami`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** reports the caller's platform, scope (DM vs group/channel), user id, access tier and the exact list of slash commands they may run here.
- **How it works:** `_handle_whoami_command` (`gateway/slash_commands.py:408`). Always available — it is in `_ALWAYS_ALLOWED_FOR_USERS`. `policy_for_source(self.config, source)`; scope label is `DM` when `chat_type.lower() ∈ {"dm","direct","private",""}` else `group/channel`. Non-admin listing = the floor `["help","whoami"]` first, then `sorted(policy.user_allowed_commands)`, deduped order-preserving.
- **Inputs / options:** none.
- **Outputs / side effects:** three shapes — gating off: `**You** — <platform> (<scope>)\nUser ID: `<id>`\nTier: unrestricted (no admin list configured for this scope)\nSlash commands: all available`; admin: `…\nTier: **admin**\nSlash commands: all available`; user: `…\nTier: user\nSlash commands you can run: /help, /whoami, …` (or `(none)`).
- **Config / env:** the four `allow_admin_from` / `user_allowed_commands` keys.
- **Edge cases / guards:** missing platform/user render as `?`; missing `chat_type` defaults to `dm`. Slack-only via `/hermes whoami`.
- **Rebuild notes:** a permission system needs a self-service introspection command, and it must be un-gateable.

### `/profile`  `id: gw-slash.profile`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** shows which Hermes profile is serving this chat and its home directory.
- **How it works:** `_handle_profile_command` (`gateway/slash_commands.py:355`), `busy_policy="dispatch"`, `execute="profile"`. On a **multiplexed** gateway (`config.multiplex_profiles`) the process-level active profile is always the multiplexer's own, so the handler reads `source.profile` (stamped by a `/p/<profile>/` URL prefix, a per-credential adapter, or a room→profile map) and resolves the home inside `_profile_runtime_scope(self._resolve_profile_home_for_source(source))`. Those pre-resolved values ride into the shared executor `_exec_profile` (`hermes_cli/slash_exec.py:82`) as `options={"profile_name","home_display"}`; when multiplexing is off both are empty and the executor falls back to `get_active_profile_name()` and `display_hermes_home()`. The executor also builds a presentation label via `format_profile_label(profile_name, read_profile_meta(get_profile_dir(name))["display_name"])` while keeping the canonical id in `data["profile"]`.
- **Inputs / options:** none.
- **Outputs / side effects:** `👤 **Profile:** `<profile>`` and `📂 **Home:** `<home>`` (the gateway re-renders the executor's `data` through the i18n templates rather than using its plain text).
- **Config / env:** `multiplex_profiles`; profile dirs and `profile.yaml` `display_name`.
- **Edge cases / guards:** not in the docs' messaging table even though it is gateway-available.
- **Rebuild notes:** keep the canonical id and the display label separate — routing must never depend on a display name.

### `/sethome` (alias `/set-home`)  `id: gw-slash.sethome`
- **Surface:** Gateway/Telegram
- **Where:** typed in the chat you want to become the platform's home channel.
- **What it does:** marks the current chat (and, where meaningful, thread) as the delivery target for cron jobs and cross-platform messages.
- **How it works:** `_handle_set_home_command` (`gateway/slash_commands.py:3274`), `gateway_only=True`. Builds `HomeChannel(platform, chat_id, name=chat_name or chat_id, thread_id, user_id, scope_id)`. The thread id comes from `_home_thread_from_source(source)` (`slash_commands.py:101`): on **Slack**, when `thread_id == message_id` the thread is synthetic (a session key, not a durable location) and is dropped — otherwise every bare-platform delivery would be pinned into the ephemeral thread the `/sethome` message spawned. Relay-delivered sources are additionally validated: the adapter must expose `fronts_platform(source.platform)` and the source must have a `user_id` and a real logical platform, else the save is refused. `persist_home_channel(home, enabled_if_new=not via_relay)` writes config.yaml (canonical because it can persist authenticated logical-target provenance across restarts), then legacy env vars are saved via `save_env_value(_home_target_env_var(platform), chat_id)` and `save_env_value(_home_thread_env_var(platform), thread_id or "")`, and the in-memory `self.config.platforms[<platform>].home_channel` is updated so the pre-restart notification path sees it.
- **Inputs / options:** none.
- **Outputs / side effects:** `✅ Home channel set to **<name>** (ID: <chat_id>).\nCron jobs and cross-platform messages will be delivered here.`; failures — `Failed to save home channel: Missing logical platform`, `Failed to save home channel: Relay does not authenticate this logical home target`, `Failed to save home channel: <exception>`. Legacy env persistence failure logs `Home config saved but legacy env persistence failed: %s` without failing the command.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.set_home.success` (`locales/en.yaml:319` → emitted at `gateway/slash_commands.py:3343 (delivery consumer gateway/run.py:19197)`) — `persist_home_channel(home, enabled_if_new=not via_relay)` succeeded; `name` is `source.chat_name or chat_id` and `chat_id` the raw platform id now stored in `config.yaml` plus the legacy `*_HOME_*` env keys:

    ```text
    ✅ Home channel set to **{name}** (ID: {chat_id}).
    Cron jobs and cross-platform messages will be delivered here.
    ```
- **Config / env:** `platforms.<name>.home_channel` in `gateway-config.yaml`; `HERMES_<PLATFORM>_HOME_*` env vars.
- **Edge cases / guards:** `desktop="terminal"` (not offered in the desktop composer).
- **Rebuild notes:** distinguish a durable thread from a synthetic per-message thread before pinning anything to it.

### `/resume [name]`  `id: gw-slash.resume`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/resume`, `/resume 1`, `/resume "Project A Plan"`, `/resume <session_id>`, `/resume --all`, `/resume --cross-room <name>`.
- **What it does:** lists recent named sessions for this chat, or switches the chat onto a previous session (restoring its transcript).
- **How it works:** `_handle_resume_command` (`gateway/slash_commands.py:5155`). Requires `_session_db`. The source is normalised first. Arguments are `shlex.split` (ValueError → parse-error reply); `--all` and `--cross-room` are extracted and the remainder joined as the name; literal wrapping `<>`/`[]`/`""`/`''` is stripped so a user copying the usage hint still works. `_list_titled_sessions()` calls `list_sessions_rich(source=<platform>, session_key=None if (allow_all and admin) else session_key, limit=10)` and keeps only titled rows; each row is then filtered by `_resume_row_visible(source, row, allow_all)`. A numeric name selects from that list. A non-numeric name first tries a **direct session-id** lookup, then `resolve_session_by_title(name)`. `resolve_resume_session_id(target_id)` follows compression continuations (#15000). Matrix gets a room guard (`_same_matrix_room`); every other platform gets the IDOR guard `_resume_target_allowed(source, target_id, allow_override=allow_all or allow_cross_room)`. On success: release the running-agent slot, `switch_session(session_key, target_id)`, `_clear_conversation_scope(reason="resume")` (model/reasoning overrides #10702, one-turn restores, model notes, last-resolved cache #58403, `/queue` overflow, security state), `_evict_cached_agent` (#6672 — a cached memory provider would otherwise keep writing into the old session).
- **Inputs / options:** `[name]` (title, id, or 1-based index), `--all` (admin-only widening), `--cross-room` (Matrix).
- **Outputs / side effects:** the chat's routing key now points at the old session. Replies: `Session database not available.`; ``⚠️ Could not parse `/resume` arguments: <error>.\nUse quotes around titles with spaces, for example: `/resume "Project A Plan"`.``; empty list — `No named sessions found.\nUse `/title My Session` to name your current session, then `/resume My Session` to return to it later.` or, on Matrix without `--all`, `No named sessions found for this Matrix room.\nUse `/title My Session` to name the current room session, `/resume --all` to list all Matrix sessions, or `/resume --cross-room <session name>` to explicitly cross room boundaries.`; listing — `📋 **Named Sessions**\n` + `<i>. **<title>** — _<preview≤40>_` + `\nUsage: `/resume <session name>` or `/resume <number>` (e.g. `/resume 1` for the most recent)`; `Could not list sessions: <error>`; `Resume index <i> is out of range.\nUse `/resume` with no arguments to see available sessions.`; `No session found matching '**<name>**'.\nUse `/resume` with no arguments to see available sessions.`; `📌 Already on session **<name>**.`; `Failed to switch session.`; success — `↻ Resumed session **<title>** (<n> message[s]). Conversation restored.` or `↻ Resumed session **<title>**. Conversation restored.`; Matrix guards — `⚠️ Matrix /resume blocked: this named session has no recorded room origin, so Hermes will not resume it inside the current room by default. Use `/resume --cross-room <name>` if you intentionally want to cross room boundaries.`, `⚠️ Matrix /resume blocked: that session belongs to a different Matrix room (<room>). Use `/resume --cross-room <name>` if you intentionally want to resume it here.`, `⚠️ Cross-room resume: resumed **<title>** inside Matrix room **<room>**.\nFuture messages in this room will use that transcript until `/reset` or another `/resume`.<msg_part>`; IDOR guard — `⚠️ /resume blocked: '**<name>**' belongs to a different user or chat. You can only resume sessions from this chat.`
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.resume.parse_error` (`locales/en.yaml:277` → emitted at `gateway/slash_commands.py:5169 (also reused by /sessions at :5341)`) — `shlex.split(raw_args)` raised `ValueError` (typically an unbalanced quote); the reply teaches the quoting form for multi-word titles:

    ```text
    ⚠️ Could not parse `/resume` arguments: {error}.
    Use quotes around titles with spaces, for example: `/resume "Project A Plan"`.
    ```

  - `gateway.resume.matrix_no_named_sessions` (`locales/en.yaml:278` → emitted at `gateway/slash_commands.py:5204`) — bare `/resume` on Matrix without `--all` when no titled session survived the room-visibility filter; documents both room-boundary escapes:

    ```text
    No named sessions found for this Matrix room.
    Use `/title My Session` to name the current room session, `/resume --all` to list all Matrix sessions, or `/resume --cross-room <session name>` to explicitly cross room boundaries.
    ```

  - `gateway.resume.matrix_cross_room_success` (`locales/en.yaml:281` → emitted at `gateway/slash_commands.py:5312`) — `/resume --cross-room <name>` on Matrix succeeded — deliberately warning-flavoured because the transcript now belongs to a different room; `room` is `source.chat_name or source.chat_id`, `msg_part` is ` (<n> message[s])` or empty:

    ```text
    ⚠️ Cross-room resume: resumed **{title}** inside Matrix room **{room}**.
    Future messages in this room will use that transcript until `/reset` or another `/resume`.{msg_part}
    ```

  - `gateway.resume.no_named_sessions` (`locales/en.yaml:283` → emitted at `gateway/slash_commands.py:5205`) — bare `/resume` on every non-Matrix platform (and on Matrix with `--all`) when the titled-session list is empty; teaches the `/title` → `/resume` workflow:

    ```text
    No named sessions found.
    Use `/title My Session` to name your current session, then `/resume My Session` to return to it later.
    ```

  - `gateway.resume.out_of_range` (`locales/en.yaml:291` → emitted at `gateway/slash_commands.py:5235`) — `/resume <N>` where N < 1 or N > len(visible titled sessions):

    ```text
    Resume index {index} is out of range.
    Use `/resume` with no arguments to see available sessions.
    ```

  - `gateway.resume.not_found` (`locales/en.yaml:292` → emitted at `gateway/slash_commands.py:5248`) — neither the direct session-id lookup nor `resolve_session_by_title(name)` produced a target id:

    ```text
    No session found matching '**{name}**'.
    Use `/resume` with no arguments to see available sessions.
    ```

  - `gateway.resume.resumed_one` (`locales/en.yaml:295` → emitted at `gateway/slash_commands.py:5320`) — success with exactly one user message in the restored transcript:

    ```text
    ↻ Resumed session **{title}** ({count} message). Conversation restored.
    ```

  - `gateway.resume.resumed_many` (`locales/en.yaml:296` → emitted at `gateway/slash_commands.py:5321`) — success with 2+ user messages (0 messages uses `gateway.resume.resumed_no_count` instead):

    ```text
    ↻ Resumed session **{title}** ({count} messages). Conversation restored.
    ```
- **Config / env:** session DB; admin list for `--all`.
- **Edge cases / guards:** a session id/title is treated as a routing handle, not authority — the ownership check is mandatory on every non-Matrix adapter.
- **Rebuild notes:** resolve title → id → compression tip, then authorise; never authorise on the handle alone.

### `/sessions`  `id: gw-slash.sessions`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/sessions`, `/sessions all`, `/sessions search <query>`, `/sessions <name-or-id>`.
- **What it does:** lists previous sessions for this chat (or, for admins, across origins), or jumps straight to one.
- **How it works:** `_handle_sessions_command` (`gateway/slash_commands.py:5323`). `parse_session_listing_args(raw)` (`hermes_cli/session_listing.py`) returns `(include_all, include_unnamed, target, search_query)`; a ValueError reuses the `/resume` parse-error template. `search_query == ""` (i.e. bare `search`) → `Usage: `/sessions search <query>``. A `target` is delegated to `/resume` by cloning the event with `dataclasses.replace(event, text=f"/resume {target}")`. Otherwise `cross_origin = include_all and self._resume_caller_is_admin(source)` — this gate exists because `all` is just a user argument and without it any caller could enumerate other origins' ids/titles/previews (the enumeration half of the `/resume` IDOR). `query_session_listing(db, source, session_key=None if cross_origin else session_key, current_session_id, include_all_sources, include_unnamed, search_query, limit=50 if search_query else 10, exclude_sources=["tool"])` runs in a thread; non-cross-origin rows are then filtered by `_resume_row_visible(..., allow_all=False)` and capped at 10. Rendered by `format_gateway_session_listing(rows, include_source=cross_origin, title=…)`.
- **Inputs / options:** `all`, `search <query>`, a session name/id, and whatever else `parse_session_listing_args` accepts (unnamed inclusion).
- **Outputs / side effects:** read-only listing; the title line is `Sessions matching “<query>”`, `Sessions` (when unnamed are included) or `Named Sessions`.
- **Config / env:** session DB; admin list.
- **Edge cases / guards:** search over-fetches (50) before the visibility cut so origin-invisible matches can't consume the page.
- **Rebuild notes:** apply the same ownership filter to listing that you apply to resuming — enumeration is half the vulnerability.

### `/egress [status]`  `id: gw-slash.egress`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/egress`, `/egress status`.
- **What it does:** shows the Docker egress-proxy status — enabled/configured/running state, credential source, token mappings, uncovered providers and the next remediation step.
- **How it works:** `execute="egress"` → `_exec_egress` (`hermes_cli/slash_exec.py:75`) returning `format_status_text()` from `hermes_cli/proxy_cli.py`. The gateway calls it directly in two places: the cold-path branch `gateway/run.py:19018` and the mid-run handler `_busy_egress_command` (`run.py:17876`), both `from hermes_cli.proxy_cli import format_status_text; return format_status_text()`.
- **Inputs / options:** `status` (accepted, no behavioural difference — the executor ignores args).
- **Outputs / side effects:** read-only text.
- **Config / env:** the Docker egress-proxy configuration block.
- **Edge cases / guards:** Slack-only via `/hermes egress`; identical text on CLI, TUI, desktop chat and gateway by construction (the `slash_exec` surface-invariance rule).
- **Rebuild notes:** registry-owned executors are how you keep one command's text identical on five surfaces.

### `/usage [reset [--force]]`  `id: gw-slash.usage`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/usage`, `/usage reset`, `/usage reset --force`.
- **What it does:** shows session token usage, cost/rate-limit state, context window, per-category context breakdown, provider account limits and Nous credits; `reset` redeems a banked Codex rate-limit reset.
- **How it works:** `_handle_usage_command` (`gateway/slash_commands.py:5656`). Args: first token must be `reset` or the command errors. Agent resolution: running agent → cached agent. Billing route resolution when no agent is resident: `get_dominant_session_model_route(session_id).billing_provider/billing_base_url`, falling back to the session row's `billing_provider`/`billing_base_url`. **Reset path:** requires `provider == "openai-codex"`; `--force` anywhere after `reset`; `redeem_codex_reset_credit(base_url, api_key, force)` in a thread; returns `result.message`. **Display path:** `fetch_account_usage(provider, base_url, api_key)` → `render_account_usage_lines(..., markdown=True)` (off-loop, failures non-fatal); `nous_credits_lines(markdown=True)` gated only on "a Nous account is logged in" (deliberately not nested under `if provider:` so a Nous-credentialled user running inference elsewhere still sees a balance); rate limits from `agent.get_rate_limit_state()` + `format_rate_limit_compact`; the per-category breakdown from `_context_breakdown_lines(agent, source)` (`:5615`).
- **Inputs / options:** `reset`, `--force`.
- **Outputs / side effects:** read-only (except the reset redemption). Lines: `⏱️ **Rate Limits:** <state>`; `📊 **Session Token Usage**`, `Model: `<model>``, `Input tokens: <n>`, `Output tokens: <n>`, `Total: <n>`, `API calls: <n>`, `Context: <used> / <total> (<pct>%)`, `Compressions: <n>`; breakdown `🧩 **Context breakdown** _(estimated)_` + `• <label>: ~<n> (<pct>%)` with labels `System prompt`, `Tool definitions`, `Rules`, `Skills`, `MCP`, `Subagent definitions`, `Memory`, `Conversation`; no-agent fallback `📊 **Session Info**`, `Messages: <n>`, `Estimated context: ~<n> tokens`, `_(Detailed usage available after the first agent response)_`; `No usage data available for this session.`; `Unknown /usage subcommand: `<args>`. Try `/usage` or `/usage reset [--force]`.`; `Banked usage resets are only available on the openai-codex provider. Switch with `/model` first.`; Nous credits also use `Not logged into Nous Portal. Log in to see your credit balance and top up.` The catalog additionally defines `Cache read tokens: <n>`, `Cache write tokens: <n>`, `Cost: <prefix>$<amount>` and `Cost: included`, used by the shared renderers.
- **Config / env:** provider credentials; Nous portal auth.
- **Edge cases / guards:** every network fetch is off-loop and fail-open. Messaging binds no recovery-notice consumer, so `/usage` only displays.
- **Rebuild notes:** separate "this session", "this account", and "this subscription" clearly; make every remote fetch optional.

### `/topup`  `id: gw-slash.topup`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** shows the Nous credit balance and hands off to the billing portal via a tappable URL.
- **How it works:** `_handle_topup_command` (`gateway/slash_commands.py:5544`). `build_credits_view(markdown=True)` runs in a thread; failures or `not view.logged_in` → the not-logged-in message. Otherwise it prints `💳 **Nous balance**` followed by `view.balance_lines` with any line whose lstrip starts with `📈` dropped (the helper's own header), then a blank line + `view.identity_line`, then a blank line + `Manage billing on the portal: <topup_url>` + `Top up and manage billing in the browser — your balance updates here after.`
- **Inputs / options:** none.
- **Outputs / side effects:** read-only; no charge, confirmation or payment tracking happens in chat by design. Not-logged-in reply: `Not logged into Nous Portal. Log in to see your credit balance and top up.`
- **Config / env:** Nous portal auth.
- **Edge cases / guards:** the tappable URL works on button-less transports (SMS/email) too. Slack-only via `/hermes topup`.
- **Rebuild notes:** never take payment inside a chat command; link out and re-read the balance next time.

### `/insights [days]`  `id: gw-slash.insights`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/insights`, `/insights 7`, `/insights --days 7`, `/insights --source telegram`.
- **What it does:** shows usage analytics over a window of days, optionally filtered by source.
- **How it works:** `_handle_insights_command` (`gateway/slash_commands.py:5839`). Unicode dashes are repaired first: `re.sub(r'[‒–—―](days|source)', r'--\1', args)` (Telegram/iOS auto-convert `--`). Then a small loop parses `--days <n>`, `--source <name>` and a bare integer; `days` defaults to 30. Runs `InsightsEngine(SessionDB()).generate(days, source)` → `format_gateway(report)` in an executor, closing the DB in `finally`.
- **Inputs / options:** `[days]` bare integer, `--days <n>`, `--source <name>`.
- **Outputs / side effects:** read-only report text. Errors: `Invalid --days value: <value>`; `Error generating insights: <error>` (logged with traceback).
- **Config / env:** session DB.
- **Edge cases / guards:** unrecognised tokens are skipped rather than erroring. Slack-only via `/hermes insights`.
- **Rebuild notes:** repair smart punctuation before flag parsing on mobile-first surfaces.

### `/version` (alias `/v`)  `id: gw-slash.version`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** prints the running Hermes Agent version banner label.
- **How it works:** `_handle_version_command` (`gateway/slash_commands.py:1714`), `busy_policy="dispatch"`, `execute="version"` → `_exec_version` (`hermes_cli/slash_exec.py:68`) returning `format_banner_version_label()` from `hermes_cli/banner.py`.
- **Inputs / options:** none.
- **Outputs / side effects:** one line of text.
- **Config / env:** n/a.
- **Edge cases / guards:** Slack-only via `/hermes version`; not in the docs' messaging table.
- **Rebuild notes:** trivial, but keep it in the shared executor registry so every surface reports the same string.

### `/help [skills|<filter>]`  `id: gw-slash.help`
- **Surface:** Gateway/Telegram
- **Where:** any chat, typically the first command a user runs. Header `📖 **Hermes Commands**`.
- **What it does:** lists every gateway-available command with its usage hint and description, plus the first 10 skill commands.
- **How it works:** `_handle_help_command` (`gateway/slash_commands.py:1720`), `busy_policy="dispatch"`, `execute="gateway_help"`, and in the always-allowed access floor. `_exec_help` (`hermes_cli/slash_exec.py:157`) builds `[t("gateway.help.header"), *gateway_help_lines()]` then, when skills exist, `t("gateway.help.skill_header", count=…)` followed by the first 10 sorted skill keys as `` `<key>` — <description> `` and, if more, `t("gateway.help.more_use_commands", count=…)`. `gateway_help_lines()` (`hermes_cli/commands.py:668`) emits one line per gateway-available `CommandDef`: `` `/<name>[ <args_hint>]` -- <description>[ (alias: `/a`, `/b`)] ``, skipping "internal" aliases whose hyphen/underscore normalisation equals the canonical name (so `/reload_mcp` is not shown as an alias of `/reload-mcp`). The result is passed through `_telegramize_command_mentions`.
- **Inputs / options:** the registry advertises `[skills|<filter>]` — **the gateway handler passes no args to the executor**, so on chat platforms `/help skills` and `/help model` render the identical full list (see `gw-slash.docs-reconciliation`).
- **Outputs / side effects:** 66 command lines + up to 10 skill lines. Templates: `📖 **Hermes Commands**\n`; `\n⚡ **Skill Commands** (<n> active):`; `\n... and <n> more. Use `/commands` for the full paginated list.`
- **Config / env:** config gates decide whether `/verbose` and `/skills` appear (`display.tool_progress_command`, `skills.write_approval`).
- **Edge cases / guards:** the reply can be long — `/commands` is the paginated alternative.
- **Rebuild notes:** generate help from the registry so it can never drift; and actually honour the documented filter argument.

### `/commands [page]`  `id: gw-slash.commands`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/commands`, `/commands 3`.
- **What it does:** the paginated browser over every command **and** every skill command.
- **How it works:** `_handle_commands_command` (`gateway/slash_commands.py:1731`), `gateway_only=True`, `busy_policy="dispatch"`, `execute="gateway_commands"`. Page size is a surface parameter: **15 on Telegram, 20 everywhere else** (`slash_commands.py:1736`). `_exec_commands` (`hermes_cli/slash_exec.py:182`): a non-integer argument returns the usage line; entries = `gateway_help_lines()` plus, when skills exist, a blank line, the skill header and one `` `<key>` — <desc|Skill command> `` per sorted skill key. `total_pages = ceil(len/page_size)`; the requested page is clamped into range and slice `[start:start+page_size]` is rendered. Output is passed through `_telegramize_command_mentions`.
- **Inputs / options:** `[page]` integer.
- **Outputs / side effects:** `📚 **Commands** (<total> total, page <p>/<n>)` + blank + entries; when `total_pages > 1` a blank line then a nav line joining `` `/commands <p-1>` ← prev `` and `` next → `/commands <p+1>` `` with ` | `; when the page was clamped, `_(Requested page <r> was out of range, showing page <p>.)_`. Other replies: `Usage: `/commands [page]``, `No commands available.`, `⚡ **Skill Commands**:`, `Skill command` (default description).
- **Config / env:** as `/help`.
- **Edge cases / guards:** gateway-only; the unknown-command notice points users here.
- **Rebuild notes:** clamp instead of erroring, and tell the user you clamped.

### `/bundles`  `id: gw-slash.bundles`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** lists the configured skill bundles — the `/<slug>` aliases that preload several skills at once — and the skills inside each.
- **How it works:** `_handle_bundles_command` (`gateway/slash_commands.py:6053`), `execute="bundles"`. Calls `execute_command("bundles", CommandContext(surface="gateway"))` → `_exec_bundles` (`hermes_cli/slash_exec.py:124`) which imports `agent.skill_bundles.list_bundles` / `_bundles_dir`; an import failure returns `Bundles subsystem unavailable: <exc>` in `data["error"]` and the gateway logs `Bundles command unavailable: %s` and returns that text. The gateway then re-renders `reply.data["bundles"]` with markdown decoration of its own.
- **Inputs / options:** none.
- **Outputs / side effects:** `**Skill Bundles** (<n> installed):` + blank + per bundle `` • `/<slug>` — <description|Load <n> skills> _(<n> skills)_ `` and one `    · <skill>` per member, then blank + `Invoke a bundle with `/<slug>` to load all its skills.` Empty → `No skill bundles installed.\nCreate one on the host with:\n  `hermes bundles create <name> --skill <s1> --skill <s2>`\nDirectory: `<dir>``.
- **Config / env:** `bundles:` in `~/.hermes/config.yaml`; the bundles directory.
- **Edge cases / guards:** listing only — bundles are loaded by typing their own `/<slug>` (see `gw-slash.bundle-commands`).
- **Rebuild notes:** the shared executor returns structured `data` so each surface can decorate; keep the plain text as the fallback.

### `/diff [staged|all|session] [--stat] [path…]`  `id: gw-slash.diff`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/diff`, `/diff staged`, `/diff all`, `/diff session`, `/diff --stat`, `/diff session --stat`.
- **What it does:** shows git changes in the working directory, fenced and truncated for chat.
- **How it works:** `_handle_diff_command` (`gateway/slash_commands.py:3509`). Token scan (lowercased): `--stat`/`stat` → `stat_only`; `staged`/`--staged`/`cached`/`--cached` → mode `staged`; `all`/`--all`/`head` → mode `all`; `session` → mode `session`; default mode `working`. `cwd = os.getenv("TERMINAL_CWD", str(Path.home()))`. `session` diverts to `_gateway_session_diff(cwd, stat_only)` (`:3566`) which requires checkpoints and uses `CheckpointManager.session_diff(cwd)`. Otherwise `collect_working_diff(cwd, mode)` (`tools/working_diff.py`) in a thread. Output assembly: a fenced `stat` block, then `**Untracked:**` with up to 15 `+ <rel>` lines and `\n... and <n> more`, then the diff via `_fenced_truncated_diff` (`:3600`) which caps at **60 lines / 3000 chars** and appends `\n... (truncated — <total> lines total; use /diff --stat for a summary)` inside a ```diff fence.
- **Inputs / options:** `staged|--staged|cached|--cached`, `all|--all|head`, `session`, `--stat|stat`, and (per the docs/`args_hint`) `path…` restrictions.
- **Outputs / side effects:** read-only. `No changes.`; `<error>` (the `gateway.diff.failed` template is the bare error string); session mode without checkpoints → `Checkpoints are not enabled, so there's no session baseline.\nEnable in config.yaml:\n```\ncheckpoints:\n  enabled: true\n```\nPlain /diff still works — it uses git directly.`
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.diff.not_enabled` (`locales/en.yaml:313` → emitted at `gateway/slash_commands.py:3573 (_gateway_session_diff)`) — `/diff session` was requested while checkpoints are disabled, so there is no session baseline to diff against; the last line makes clear the git-backed `/diff` and `/diff staged|all` still work:

    ~~~text
    Checkpoints are not enabled, so there's no session baseline.
    Enable in config.yaml:
    ```
    checkpoints:
      enabled: true
    ```
    Plain /diff still works — it uses git directly.
    ~~~
- **Config / env:** `checkpoints.enabled` (+ the three size caps); `TERMINAL_CWD`.
- **Edge cases / guards:** path arguments are accepted by the docs and `args_hint` but the gateway token scan ignores unrecognised tokens — they do **not** reach `collect_working_diff` (see `gw-slash.docs-reconciliation`). Slack-only via `/hermes diff`.
- **Rebuild notes:** three truncation layers (handler → adapter split → platform cap) is deliberate; always name the escape hatch (`--stat`) in the truncation notice.

### `/debug [nous|local]`  `id: gw-slash.debug`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/debug`.
- **What it does:** collects a system-info + log-tail report, uploads it to a paste service and returns shareable links.
- **How it works:** `_handle_debug_command` (`gateway/slash_commands.py:6266`). All blocking work runs in an executor: `_best_effort_sweep_expired_pastes()`, `_capture_dump()`, `collect_debug_report(log_lines=200, dump_text=…)`, `upload_to_pastebin(report)`, `_schedule_auto_delete(urls)`. **Only the summary report is uploaded — never full log files** — to protect conversation privacy; the reply says so and points at the CLI for full uploads.
- **Inputs / options:** the registry advertises `[nous|local]`; the gateway handler ignores arguments entirely.
- **Outputs / side effects:** a paste URL that auto-deletes. Reply: `<_GATEWAY_PRIVACY_NOTICE>` + blank + `**Debug report uploaded:**` + blank + `` `Report    `  <url> `` (label padded to the widest key) + blank + `⏱ Pastes will auto-delete in 6 hours.` + `For full log uploads, use `hermes debug share` from the CLI.` + `Share these links with the Hermes team for support.` Upload failure → `✗ Failed to upload debug report: <error>`.
- **Config / env:** paste-service configuration in `hermes_cli/debug.py`.
- **Edge cases / guards:** Slack-only via `/hermes debug`.
- **Rebuild notes:** privacy notice first, summary-only by default, TTL on the paste, and an explicit CLI escape hatch for the full dump.

### `/platform <list|pause|resume> [name]`  `id: gw-slash.platform`
- **Surface:** Gateway/Telegram
- **Where:** any chat: `/platform`, `/platform list`, `/platform pause whatsapp`, `/platform resume whatsapp`.
- **What it does:** shows every gateway adapter's state and lets an operator stop or restart the reconnect watcher for a failing platform, without unloading it.
- **How it works:** `_handle_platform_command` (`gateway/slash_commands.py:1509`), `gateway_only=True`. Note it parses `event.content` (not `get_command_args()`), splitting `maxsplit=2` and dropping a leading token that starts with `platform`. Default action is `list`. `_resolve_platform(name)` matches `Platform` enum values case-insensitively. `list` reads `self.adapters` for connected names and `self._failed_platforms` for failed/paused ones. `pause` calls `self._pause_failed_platform(platform, reason="paused via /platform pause")`; `resume` calls `self._resume_paused_platform(platform)`.
- **Inputs / options:** `list` (default), `pause <name>`, `resume <name>`.
- **Outputs / side effects:** adapter dispatch is suspended/resumed and a tripped circuit breaker is cleared on resume. Replies: `**Gateway platforms**` + `Connected: <a, b>` or `Connected: (none)` + either per failed platform `  · <name> — PAUSED (<reason>). Resume with `/platform resume <name>`.` / `  · <name> — retrying (attempt <n>)`, or `Failed/paused: (none)`; `Usage: /platform pause <name>`; `Unknown platform: <target>`; `<name> is not in the retry queue (it's either connected or not enabled).`; `<name> is already paused.`; `✓ <name> paused. Resume with `/platform resume <name>` or `hermes gateway restart` to reset.`; `<name> is not in the retry queue — nothing to resume.`; `<name> is already retrying — no resume needed.`; `✓ <name> resumed — retrying on next watcher tick.`; fallthrough usage — `Usage: /platform <list|pause|resume> [name]\n  /platform list — show platform status\n  /platform pause <name> — stop retrying a failing platform\n  /platform resume <name> — re-queue a paused platform`.
- **Config / env:** n/a (runtime state).
- **Edge cases / guards:** Slack-only via `/hermes platform`.
- **Rebuild notes:** expose the reconnect watcher's state and give the operator a pause button — a hammering reconnect loop is a real outage mode.

### `/restart`  `id: gw-slash.restart`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments; also reachable from the DM phrases handled by `gw-slash.plaintext-restart`.
- **What it does:** gracefully restarts the gateway after draining active runs, and notifies the requester's chat once it is back.
- **How it works:** `_handle_restart_command` (`gateway/slash_commands.py:1602`), `gateway_only=True`, `busy_policy="dispatch"`. **Redelivery guard first:** `_is_stale_restart_redelivery(event)` — PTB's graceful-shutdown `get_updates` ACK can fail, so Telegram redelivers the same `/restart` to the *new* process, which would restart again forever; a redelivery logs `Ignoring redelivered /restart (platform=%s, update_id=%s) — already processed by a previous gateway instance.` and returns `""`. If a restart is already requested or draining it returns the drain/in-progress text. Then it writes `~/.hermes/.restart_notify.json` (`platform, chat_id, chat_type`, plus `delivered_via_upstream_relay`/`user_id`/`scope_id` for relay sources, `thread_id`, `message_id`) via `atomic_json_write` and stashes `self._restart_command_source`; and `~/.hermes/.restart_last_processed.json` (`platform, requested_at, update_id`) as a persistent dedup marker (the notify file is unlinked once the new gateway reports back, this one is not). Restart mode: when `is_gateway_supervisor_process()` (systemd/launchd) or `is_container_restart_context()` (Docker/Podman) is true it uses `request_restart(detached=False, via_service=True)` — exit code 75 so the supervisor restarts it, because a detached `setsid`+bash helper dies with the cgroup under systemd `KillMode=mixed` and with tini in Docker; otherwise `request_restart(detached=True, via_service=False)`.
- **Inputs / options:** none.
- **Outputs / side effects:** two JSON marker files; the process exits/respawns. Replies: `⏳ Draining <count> active agent(s) before restart...` when agents are running; otherwise `EphemeralReply("♻ Restarting gateway. If you aren't notified within 60 seconds, restart from the console with `hermes gateway restart`.")`; already in progress → `EphemeralReply("⏳ Gateway restart already in progress...")`.
- **Config / env:** none directly; supervisor/container detection in `gateway/restart.py`.
- **Edge cases / guards:** file-write failures are logged (`Failed to write restart notify file: %s` / `Failed to write restart dedup marker: %s`) and do not abort the restart.
- **Rebuild notes:** a restart command must be idempotent against transport redelivery, and must know whether something else will restart it.

### `/update`  `id: gw-slash.update`
- **Surface:** Gateway/Telegram
- **Where:** any messaging chat, no arguments.
- **What it does:** launches `hermes update` detached so it survives the gateway restart it may trigger, and streams progress back to the chat.
- **How it works:** `_handle_update_command` (`gateway/slash_commands.py:6310`), `busy_policy="dispatch"`. Platform gate: `event.source.platform ∈ self._UPDATE_ALLOWED_PLATFORMS` (built-in messaging platforms; ACP, API server and webhooks are excluded) or the plugin platform's `PlatformEntry.allow_update_command` is true. `is_managed()` blocks managed installs. Requires `.git` under the project root and `_resolve_hermes_bin()`. Writes `~/.hermes/.update_pending.json` atomically (`platform, chat_id, chat_type, user_id, session_key, timestamp`, plus `thread_id` / `message_id` when present) and deletes `.update_exit_code`. Spawn: on **win32** an inline Python helper is launched via `sys.executable -c …` running `python -m hermes_cli.main update --gateway` with stdout/stderr redirected to `.update_output.txt` and the return code written to `.update_exit_code` (invoking the module rather than `hermes.exe` because the shim holds its own file open and the update must replace it); elsewhere `setsid bash -c "PYTHONUNBUFFERED=1 <hermes> update --gateway > .update_output.txt 2>&1; rc=$?; printf '%s' \"$rc\" > .update_exit_code"` (falling back to `bash -c` with `start_new_session=True` when `setsid` is absent; `rc=` rather than `status=` keeps the template zsh-safe). Then `_schedule_update_notification_watch()`.
- **Inputs / options:** none.
- **Outputs / side effects:** three marker files under `~/.hermes/`; a detached updater process; interactive updater prompts are forwarded to the chat through the `--gateway` file-IPC channel (answered with `/approve`→`y` / `/deny`→`n`, `gateway/run.py:18337`). Replies: `⚕ Starting Hermes update… I'll stream progress here.`; `✗ /update is only available from messaging platforms. Run `hermes update` from the terminal.`; `✗ <managed message>`; `✗ Not a git repository — cannot update.`; `✗ Could not locate the `hermes` command. Hermes is running, but the update command could not find the executable on PATH or via the current Python interpreter. Try running `hermes update` manually in your terminal.`; `✗ Failed to start update: <error>` (markers cleaned up first).
- **Config / env:** managed-install policy; `PYTHONUNBUFFERED=1` for line-buffered streaming.
- **Edge cases / guards:** Slack-only via `/hermes update`.
- **Rebuild notes:** detach properly per platform, stream via a file the survivor can read, and make the answer channel work for the interactive prompts the updater still asks.

### `/reload-mcp` (alias `/reload_mcp`)  `id: gw-slash.reload-mcp`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments; normally answered with the confirm buttons.
- **What it does:** reconnects the MCP servers from config and rebuilds the session's tool set.
- **How it works:** `_handle_reload_mcp_command` (`gateway/slash_commands.py:5890`). Reads `approvals.mcp_reload_confirm` **fresh from disk** (`self._read_user_config()`) so a prior "Always Approve" takes effect without a gateway restart; when false it runs `_execute_mcp_reload(event)` immediately. Otherwise it routes through `_request_slash_confirm` with the localized confirm prompt. `_on_confirm`: `cancel` → `🟡 /reload-mcp cancelled. MCP tools unchanged.`; `always` → `save_config_value("approvals.mcp_reload_confirm", False)` (log `User opted out of /reload-mcp confirmation (session=%s)`; failures log `Failed to persist mcp_reload_confirm=false: %s`) then run and append `\n\nℹ️ Future `/reload-mcp` calls will run without confirmation. Re-enable via `approvals.mcp_reload_confirm: true` in config.yaml.`; `once` → run.
- **Inputs / options:** none; the confirm's three choices.
- **Outputs / side effects:** MCP servers reconnected; the provider prompt cache for the session is invalidated (tool schemas live in the system prompt). Confirm prompt (verbatim): `⚠️ **Confirm /reload-mcp**\n\nReloading MCP servers rebuilds the tool set for this session and **invalidates the provider prompt cache** — the next message will re-send full input tokens.  On long-context or high-reasoning models this can be expensive.\n\nChoose:\n• **Approve Once** — reload now\n• **Always Approve** — reload now and silence this prompt permanently\n• **Cancel** — leave MCP tools unchanged\n\n_Text fallback: reply `/approve`, `/always`, or `/cancel`._` Result: `🔄 **MCP Servers Reloaded**\n` + `♻️ Reconnected: <names>` / `➕ Added: <names>` / `➖ Removed: <names>` / `No MCP servers connected.` + `\n🔧 <n> tool(s) available from <m> server(s)`; failure `❌ MCP reload failed: <error>`.
- **Outputs / side effects — verbatim reply templates (round-0 gap-fill, transcribed character-for-character from `locales/en.yaml` with real line breaks and the shipped `{placeholders}`):**
  - `gateway.reload_mcp.confirm_prompt` (`locales/en.yaml:243` → emitted at `gateway/slash_commands.py:5944`) — the cost-warning prompt handed to `_request_slash_confirm(command="reload-mcp", title="/reload-mcp", ...)` whenever `approvals.mcp_reload_confirm` is not false; the three named choices map to the confirm outcomes `once` / `always` / `cancel`, and the text fallback lets button-less platforms answer by typing:

    ```text
    ⚠️ **Confirm /reload-mcp**

    Reloading MCP servers rebuilds the tool set for this session and **invalidates the provider prompt cache** — the next message will re-send full input tokens.  On long-context or high-reasoning models this can be expensive.

    Choose:
    • **Approve Once** — reload now
    • **Always Approve** — reload now and silence this prompt permanently
    • **Cancel** — leave MCP tools unchanged

    _Text fallback: reply `/approve`, `/always`, or `/cancel`._
    ```
- **Config / env:** `approvals.mcp_reload_confirm`; the `mcp_servers` config block.
- **Edge cases / guards:** the confirm text is one of the few places the product explains a *cost* rather than a risk.
- **Rebuild notes:** gate expensive-but-safe operations behind a confirm that explains the cost, and make the opt-out durable.

### `/reload-skills` (alias `/reload_skills`)  `id: gw-slash.reload-skills`
- **Surface:** Gateway/Telegram
- **Where:** any chat, no arguments.
- **What it does:** re-scans `~/.hermes/skills/` for newly installed or removed skills and tells the model about the diff on the next turn.
- **How it works:** `_handle_reload_skills_command` (`gateway/slash_commands.py:5953`). `agent.skill_commands.reload_skills()` runs in an executor returning `{added:[{name,description}], removed:[…], total:int}`. Then every connected adapter's `refresh_skill_group()` is invoked (awaited when awaitable) so platform-side caches refresh — today that is Discord's `/skill` autocomplete; adapters without the method are skipped, exceptions log `Adapter %s refresh_skill_group raised: %s`. **The prompt cache is deliberately NOT cleared** — skills are invoked via `/skill-name`, `skills_list` or `skill_view` at runtime and don't need to be in the system prompt. When something changed, a one-shot note is stored on `self._pending_skills_reload_notes[session_key]` and prepended to the NEXT user message (consumer in `_run_agent_turn`), so nothing is written to the transcript out-of-band and alternation is preserved. The note reads `[USER INITIATED SKILLS RELOAD:` / blank / `Added Skills:` / `    - <name>: <desc>` / blank / `Removed Skills:` / … / blank / `Use skills_list to see the updated catalog.]`
- **Inputs / options:** none.
- **Outputs / side effects:** `🔄 **Skills Reloaded**\n` + either `No new skills detected.` or `➕ **Added Skills:**` / `➖ **Removed Skills:**` with `    - <name>: <desc>` (or `    - <name>` without a description), then `\n📚 <n> skill(s) available`; failure `❌ Skills reload failed: <error>` (logged `Skills reload failed: %s`).
- **Config / env:** `skills.external_dirs`, `skills.disabled`, `skills.platform_disabled`.
- **Edge cases / guards:** the note is one-shot and cleared after consumption.
- **Rebuild notes:** don't invalidate the prompt cache for data the model fetches on demand; deliver the diff as a prepended note rather than a synthetic transcript row.

---

## 6. Docs-vs-code reconciliation

### Discrepancies between `website/docs/reference/slash-commands.md` and the shipped gateway code  `id: gw-slash.docs-reconciliation`
- **Surface:** Docs
- **Where:** `/tmp/claude-0/-home-user-jarvis-hub/8afd1338-a973-516f-b42c-2b3685ad04f8/scratchpad/hermes-agent/website/docs/reference/slash-commands.md` (332 lines; 161 table rows total, of which the "Messaging slash commands" table at L233–L305 holds 63 rows covering 61 distinct commands plus a duplicated `/sessions` row and a `/<skill-name>` row).
- **What it does:** records every place the reference doc and the v2026.8.31 gateway implementation disagree, so a rebuild does not copy a documented behaviour that does not exist (or miss one that does).
- **How it works:** verified by enumerating `COMMAND_REGISTRY` through `_is_gateway_available()` (66 gateway-available commands, matching `gateway_help_lines()`'s 66 lines) and diffing against `_gateway_plain_command_handlers()` (21 names) ∪ the `canonical == …` branch set (46 names) and against the doc's messaging table.
- **Inputs / options:** the findings —
  1. **`/curator` is advertised but unhandled.** It is in the messaging table, in `/help` and in the Telegram/Slack menus, yet there is no gateway handler; the text falls through to the LLM. Only such command among the 66.
  2. **Seven gateway-available commands are missing from the messaging table:** `/save`, `/pause`, `/profile`, `/version`, `/busy`, `/approvals`, `/loop`. (`/loop` and `/busy` are described in the CLI table only; `/pause` only in the CLI Session table.)
  3. **`/help <filter>` and `/help skills` do nothing on chat platforms.** The `CommandDef` advertises `args_hint="[skills|<filter>]"` and the description promises filtering, but `_handle_help_command` (`gateway/slash_commands.py:1720`) constructs `CommandContext(surface="gateway")` **without `args`**, and `_exec_help` never reads `ctx.args`.
  4. **`/verbose` cycles five modes, not four.** Registry description and docs say "off → new → all → verbose"; `gateway/slash_commands.py:4256` uses `cycle = ["off","new","all","verbose","log"]` and the catalog carries a `gateway.verbose.mode_log` string.
  5. **`/reasoning full` and `/reasoning clamp` are unsupported on the gateway.** Both appear in the registry `args_hint`/`subcommands` and in both doc tables, but `parse_reasoning_effort()` returns `None` for them (`VALID_REASONING_EFFORTS = ('minimal','low','medium','high','xhigh','max','ultra')`), so `_apply_reasoning_selection` answers with the "⚠️ Unknown argument" card.
  6. **`/diff path…` arguments are ignored on the gateway.** The docs and `args_hint` promise "path arguments restrict the diff", but the token scan in `_handle_diff_command` only recognises the mode/`--stat` tokens and `collect_working_diff(cwd, mode)` takes no paths.
  7. **The inline destructive-confirm skip (`now`, `--yes`, `-y`) is CLI-only.** The docs present it under a heading that also covers messaging; the gateway's `_maybe_confirm_destructive_slash` has no such parsing, so `/new --yes foo` titles the new session `--yes foo`.
  8. **`/voice channel|join|leave` are undocumented in the registry hint.** `args_hint="[on|off|tts|status]"` while the handler also accepts `channel`, `join`, `leave`, `enable`, `disable`; only the messaging doc table lists the full set.
  9. **`/debug [nous|local]` arguments are ignored.** The handler never reads `get_command_args()`.
  10. **`/suggestions clear` is implemented but missing from the registry hint** (`args_hint="[accept|dismiss N | catalog]"`), although the docs do mention it.
  11. **`/sessions` has no `args_hint` in the registry** (so `/help` shows a bare `/sessions`) while both the docs and `parse_session_listing_args` support `all`, `search <query>` and a direct target.
  12. **Prefix matching is CLI-only.** The doc's "Alias Resolution" section ("typing `/h` resolves to `/help`") describes `hermes_cli` autocomplete; the gateway's `resolve_command()` is exact-match on names+aliases only.
  13. **`/topic` and `/status` are unreachable as native Slack slashes** (Slack reserves both); the doc's Slack note covers `!`-prefix usage but the reserved-name list (`hermes_cli/commands.py:1414`) is the authority.
  14. **`/skills` and `/verbose` only appear in gateway help when their config gate is on** (`skills.write_approval`, `display.tool_progress_command`) — the docs' Notes section states this for `/verbose` and partially for `/skills`.
- **Outputs / side effects:** n/a — an audit result.
- **Config / env:** n/a.
- **Edge cases / guards:** counts were taken from the live checkout at tag `v2026.8.31` with `HERMES_HOME` pointed at a scratch profile, so config-gated commands (`/verbose`, `/skills`) were **absent** from the 66-line `/help` render; on an install with those gates on, `gateway_help_lines()` returns 68 lines.
- **Rebuild notes:** add a startup assertion that every gateway-available `CommandDef` resolves to a handler, and generate the reference doc from the registry (description + `args_hint` + aliases + surface flags) so rows cannot drift from code.

---

## Handoffs

- CLI/TUI dispatch of the same `COMMAND_REGISTRY` (`cli.py process_command`, prompt_toolkit `SlashCommandCompleter` / `SlashCommandAutoSuggest`, `/palette`, `/focus`, `/skin`, `/pet`, `/hatch`, `/worktree`, `/handoff`, `/journey`, `/snapshot`, `/export`, `/import`, `/tools`, `/toolsets`, `/browser`, `/cron`, `/plugins`, `/config`, `/reload`, `/statusbar`, `/battery`, `/timestamps`, `/indicator`, `/wake`, `/copy`, `/paste`, `/image`, `/quit`, `/clear`, `/redraw`, `/history`, `/prompt`, `/subscription`) → `cli-*` shards.
- Desktop composer command popover semantics (`CommandDef.desktop` values `terminal | messaging | settings | advanced | composer-voice | hidden` and `infer_argument_mode` / `command_desktop_meta`, `hermes_cli/commands.py:427`–`449`) → `desktop-*` shard.
- Discord adapter's actual slash registration and `/skill` autocomplete callback (`plugins/platforms/discord/adapter.py::_register_slash_commands`) → platforms shard.
- Slack `/hermes` command handler wiring and Socket-Mode event routing (`plugins/platforms/slack/adapter.py`) → platforms shard.
- `tools/approval.py` (`resolve_gateway_approval`, `has_blocking_approval`, session YOLO store) and the dangerous-command prompt itself → tools/approvals shard.
- `agent/goals.py` / `hermes_cli/goals.py` `GoalManager` internals (status_line, render_contract, render_gates, render_subgoals, judge loop) → core shard.
- `hermes_cli/loops.py` `LoopManager`/`parse_loop_args` internals and the idle loop-wakeup watcher → core shard.
- `hermes_cli/kanban.py` full CLI surface (47 subcommands with all their flags) → cli shard.
- `agent/skill_bundles.py` bundle file format and `list_bundles()` → skills shard.
- Config keys touched here (`approvals.*`, `display.*`, `model.*`, `goals.max_turns`, `loops.*`, `skills.*`, `memory.write_approval`, `quick_commands`, `platforms.*.extra.*`) → `config-*` shards.
- `gateway/run.py` message pipeline outside command dispatch (busy input modes, drain gate, turn leases, compression-in-flight demotion, Telegram follow-up grace) → gateway-core shard.
