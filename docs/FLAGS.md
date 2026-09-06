# FLAGS.md — action-posture flags: know what flipping costs

Environment flags change what Nerva may do without asking you. **Every flag on this
page ships default-off** (`env_flag` returns False unless explicitly set,
`agents/core/env_config.py:78`); string/list flags are unset by default and the
surface behind them refuses by name. This is what each one actually buys you — and
what it costs. The first three are the posture flags everything else composes with;
verified against code at `75e92811`. The wave-2026-09-06 flags are appended after
them and verified against `214bc5eb`.

## `JARVIS_ACTION_KERNEL`

**Default: OFF.** The gate itself: `agents/core/kernel/flags.py:14`. Unset, every
broker hook no-ops or fails closed (`agents/core/http_client.py:48`,
`agents/core/acquisition/promotion.py:41`).

**What ON changes:** privileged actions cross `kernel.authorize` →
grant/deny/queue (`agents/core/kernel/__init__.py:131`). For request-path brokers
the wave-1 unconditional `ask` floor lifts: a broker enqueues with
`autonomy_level="ask"` by default, but a kernel **GRANT rewrites it to `"act"`**
(`agents/core/autonomy/call_broker.py:262`, `agents/core/channel_reply.py:107`).
That flips the downstream outcome: `act` tasks auto-approve
(`agents/core/autonomy/worker.py:634`); `ask` tasks land BLOCKED in your decision
inbox (`agents/core/autonomy/worker.py:643`).

**What stays gated anyway (honest limits of ON):**

- Policy floor survives: the worker keeps the *stricter* of requested level and
  policy outcome — money over cap/daily-ceiling still asks
  (`agents/core/autonomy/policy.py:230`, `agents/core/autonomy/worker.py:608`).
- Taint forces ask: tainted payload or untrusted origin escalates GRANT→QUEUE
  (`agents/core/kernel/__init__.py:224`; `agents/core/autonomy/worker.py:537`).
- Kernel QUEUE floors back to ASK (`agents/core/autonomy/worker.py:350`).
- Permanent owner floors a GRANT cannot bypass: skill installs
  (`agents/core/kernel/registry.py:96`) and house security-control confirmation
  (`agents/core/kernel/registry.py:87`).

**Gated surface:** the KERNEL-classed kinds in `ACTION_REGISTRY`
(`agents/core/kernel/registry.py:32`): calls, social, write-back, payments,
plugin egress, MCP mutations, host control, Tool-RPC, repo sync, admin
kill-switch/capability-issue, KG writes, media present/restore, desktop steps,
house control/security/recovery, channel replies, skill installs. Not gated:
internal KG ingestion writes directly by design (`registry.py:68`). Unclassified
kinds stay `PENDING_KERNEL` debt until their wave lands (`registry.py:26`).

**Risk delta vs OFF:** OFF, nothing executes without your inbox approval except
whatever legacy direct paths exist. ON, reversible actions that policy scores
ACT/NOTIFY execute autonomously on a GRANT — you find out from logs, not cards.
Money caps, taint, kill-switch, and the permanent floors above still hold.

## `JARVIS_UNIFIED_ACTION_API`

**Default: OFF.** Constant: `UNIFIED_ACTION_ENV`
(`agents/core/capability_actions.py:17`). It arms the `CapabilityActionAPI`
facade that house/media/desktop run through **exclusively** — there is no
unmediated fallback ("refuses honestly instead of driving devices unmediated",
`agents/core/routers/media_director.py:243`).

**Why BOTH flags:** `perform()` checks the unified flag first, then the kernel
flag — either unset returns `disabled`
(`agents/core/capability_actions.py:129`). So `JARVIS_ACTION_KERNEL=1` alone
lights nothing on these facades, and the unified flag alone has no authorizer
that will ever GRANT. All three facades bind it:
house (`agents/core/house/actuation.py:365`), media
(`agents/core/routers/media_director.py:164`), desktop
(`agents/core/desktop_operator.py:188`).

**End-to-end — `POST /api/media/present`:** the route builds a request-scoped
facade whose authorizer is the bound kernel (`make_action_kernel`,
`agents/core/routers/media_director.py:156`), registers
`action:media.present` (`agents/core/media_director.py:1061`), then `perform()`:
missing required params → `refused` before any authorization
(`capability_actions.py:139`); kernel DENY → `refused`, QUEUE → `queued` with an
approval card, GRANT → handler runs (`capability_actions.py:175`). With either
flag off the same POST returns `status: "disabled"` — a refusal, never a device
command.

**Risk delta vs OFF:** OFF, these surfaces are inert refusals. ON, house
mutations / media playback / desktop steps can complete on a kernel GRANT
(house security control still demands owner confirmation,
`registry.py:87`). This is the flag that makes the smart-home story real — flip
it deliberately, together with the kernel flag.

## `JARVIS_WEBHOOK_CHANNELS`

**Default: empty (no channels wired).** JSON object env:
`{"<kind>": {<config>}}` read at startup (`agents/web.py:423`).

**The cheap win holds — all five adapters exist**, in
`agents/core/channels/webhook_channels.py`: WhatsApp Cloud API (`:127`), Signal
via signal-cli REST (`:158`), Matrix client-server (`:183`), Teams
(`:214`), Google Chat (`:239`). Registry + builder: `:262`. **No new pip
dependency:** outbound uses an injectable transport defaulting to the in-house
egress-gated HTTP client (`webhook_channels.py:113`); `httpx` is already base
(`requirements.txt:8`).

Reality notes per channel:

- **Signal** needs a *running signal-cli REST daemon* somewhere reachable
  (`base_url` config) — not a pip install, but an external process you operate.
- **Inbound delivery** posts to `/api/channels/{id}/inbound`
  (`agents/core/routers/integrations.py:211`), user-guarded, and provider
  signature verification is deliberately a host seam — front it with the signed-
  webhook path in production (`integrations.py:217`). Outbound Teams/Google Chat
  need an incoming-webhook URL in config.
- **Governance applies regardless:** inbound senders thread through the pairing
  gate (`agents/core/channels/gateway.py:65`); outbound is rate-limited only if
  you opt in (`webhook_channels.py:66`, unlimited by default). iMessage is
  intentionally excluded (`webhook_channels.py:17`).

**Risk delta vs none:** a misconfigured channel is a door into the governed
gateway — pairing gate and guardrails hold, but anyone who can reach the inbound
endpoint with a paired sender can drive the agent. Configure pairing first.


---

## Wave 2026-09-06 flags (all default OFF)

Seventeen slices landed on 2026-09-06 (`opus-integration`, PR #1039). Each new
capability sits behind its own flag; none of them changes behaviour until it is set,
and every privileged effect behind them still crosses the Action Kernel.

### `JARVIS_PERMISSION_LEDGER`

**Default: OFF.** Read per call via `agents.core.env_config.env_flag`
(`PermissionLedger(enabled=…)` overrides it for tests).

**OFF:** `PermissionLedger.check()` answers `allow` for legacy callers and records
nothing — today's behaviour, byte-identical.
**ON:** first contact with an app / site / OS-input device / file root / terminal
target answers `ask`; grants are widened **only** through the `permission.grant`
approval task (EXTERNAL tier → decision inbox, applied from the human-decided task);
the curated default-deny list (banks, brokerages, crypto wallets, password managers,
SSO IdPs, adult; secret file roots) and any `never` row always deny.
**Cost:** more approval cards the first time Nerva touches something new.
**Revert:** unset + restart; `never` rows and the SQLite ledger survive, inert.

### `JARVIS_FILE_TOOLS` · `JARVIS_FILE_ROOTS` · `JARVIS_FILE_MAX_BYTES`

**Defaults: OFF · `<data root>/workspace` · `2000000`.**

**OFF:** `register_file_tools` is a no-op — **no file tool exists on the ToolRPC
allowlist at all**.
**ON:** `file_read` / `file_list` are ungated *inside* `JARVIS_FILE_ROOTS` (no `..`,
no symlink escape, secret-looking names refused, bytes/entries bounded);
`file_write` / `file_delete` are **gated** ask-tier ToolRPC tasks
(`toolrpc.file_write`, `toolrpc.file_delete`) that snapshot the previous bytes before
touching the file, cross the kernel as `file.write`, and are reversible through
`restore_snapshot(ref)`.
`JARVIS_FILE_ROOTS` is a comma list of **absolute** roots; `JARVIS_FILE_MAX_BYTES`
(minimum 1) caps both read and write.
**Cost:** the model loop can read and — after your approval — replace or delete files
inside the roots you named. Snapshots have no retention/GC yet.
**Revert:** unset + restart; the tools disappear from the allowlist.

### `JARVIS_TERMINAL_LOCAL_HOST` · `JARVIS_TERMINAL_LOCAL_ROOTS` · `JARVIS_TERMINAL_TIMEOUT_S`

**Defaults: OFF · `data_path('workspace')` (created on first use) · `60` (capped 600).**

**OFF:** the `local-host` inventory row is absent and `LocalHostTransport` is not
constructed — the refusal is the byte-identical `local_transport_not_implemented`.
**ON:** the local host becomes a terminal target, argv-only, cwd-jailed to
`JARVIS_TERMINAL_LOCAL_ROOTS`, output-capped, killed on timeout.
**What stays gated anyway:** the static HARDLINE denylist is evaluated **before**
authorize on every backend including docker (a hit leaves no audit entry and never
spawns); then the target policy, then a **durable approved task**, then the
`terminal.exec` contract, then an Action-Kernel GRANT. `JARVIS_ACTION_KERNEL` is
mandatory — without it the backend refuses `kernel_unavailable`.
**Cost:** approved commands really run on your machine, as you. Rollback is `none`
— shell effects are not automatically reversible, and the contract says so.
**Revert:** unset + restart.

### `JARVIS_BROWSER_ALLOW_PRIVATE_URLS`

**Default: OFF.** Read by `PlaywrightBrowserDriver.from_env` and
`PinnedResolver.from_env`.

**ON:** `PinnedResolver` runs in `lan` mode and the driver's route layer admits
RFC1918 / loopback literals, so the governed browser can reach house devices.
**Honest limit:** `BrowserPolicy.domain_allowed` (`browser_agent.py`) still calls
`check_ssrf` in public mode, so end-to-end LAN browsing **also** needs a
`BrowserPolicy` lan mode — not shipped in this wave.
**Revert:** unset + restart; unpinned hosts fail at name resolution again.

*Related, unchanged default:* `JARVIS_PLAYWRIGHT_HOST` (default off, no section of its
own on this page) still decides whether a real browser runtime may start at all. With
`chromium`, `PlaywrightBrowserDriver.from_env()` now binds the IP-pinned transport
(`agents/core/browser_transport.py`) so navigation **can** start; `firefox`/`webkit`
stay transport-less and refuse `pinned_transport_requires_chromium`.

### `JARVIS_COMPANY_MODE`

**Default: OFF** (`autonomy/company_supervisor.py` `FLAG`, plus
`SupervisorConfig.enabled`, which defaults to `False` independently — a supervisor
built by accident still does nothing).

**ON:** the runtime may construct a `CompanySupervisor` and tick an open work run:
a single owner-approved goal worked continuously across turns and reboots
(`autonomy/work_runs.py`, `work_verifier.py`, `work_judge.py`).

What the flag does **not** change: who may authorise an effect. Every action the
supervisor arranges is handed to the same governed intake as everything else and
lands in the decision inbox as an ask-tier task — the contract's authority is
`delegated_execution_only`. A run cannot open without an owner-approved goal, a
step that changed something with no durable task id fails verification, and only
the judge (after the verifier) can mark a run succeeded.

**What it takes to actually run.** As of `company_runtime.py`, the flag being set
**at boot** is what registers the `company-mode-sweep` job
(`scheduler_service.schedule_company_mode`, every `autonomy.company_tick_seconds`,
floor 60s). The asymmetry is deliberate: **clearing the flag stops work at the very
next tick** (the runtime re-reads it each sweep), while **setting it needs a
restart** — a capability that can start a night of autonomous work should not begin
because a config file changed while nobody was looking. Nothing is registered if the
chain cannot be built, and every refusal is named in the log: no work-run ledger, no
governed intake. A missing task queue is reported rather than fatal — the runtime
builds, but a blocked run could never be resumed, so it says so.

**What it will actually do.** The planner is the **checklist the owner read on the
approval card** (`GoalDraft.plan`, inside the payload fingerprint, so editing it
invalidates the approval). A goal approved with **no** plan and no explicitly-passed
model planner **proposes nothing** and goes straight to grading: "you approved a goal
with no plan, so nothing happened" is a better outcome than a model improvising a
night's work from a one-line title. A goal that cannot be read yields an *empty*
plan, never an unrestricted one.

**Cost:** an active run consumes its own budget — steps, wall-clock, deadline and
a hard cap on how many times it may interrupt you. Running out of interrupts
blocks the run rather than ending it, so the work waits instead of nagging.
**Revert:** unset; the next sweep answers `company mode is off`, every tick answers
`disabled` and no run is opened. Existing run rows stay in `work_runs.db` as a
record and can be purged with a forget.

### `JARVIS_MODEL_PULL`

**Default: OFF** (`routers/model_setup.py` `_enabled`, `env_flag`).

**ON:** `POST /api/onboarding/model-pull` may reach the unified action facade
(`action:model.pull`). It still needs `JARVIS_UNIFIED_ACTION_API` **and**
`JARVIS_ACTION_KERNEL` or it refuses `unified_action_api_disabled` /
`action_kernel_disabled`; a kernel DENY answers 403 and a QUEUE 202; the Ollama URL
must be loopback (`ollama_url_not_loopback`); the cumulative layer size must stay
under the `llm.model_pull_max_gb` setting (`model_too_large`); one pull at a time
(`pull_in_progress`).
**Cost:** bandwidth and disk. Rollback is `ollama rm` (compensating, not automatic).
**Revert:** unset; the route refuses `model_pull_disabled`.

### `JARVIS_HESTIA_BRIDGE` · `JARVIS_WLED_URL`

**Defaults: OFF · unset.**

**`JARVIS_HESTIA_BRIDGE` ON:** `HestiaBridge.observe()` / `propose()` may run —
observation is a strict-local snapshot with **aggregate occupancy only**, and every
proposal becomes an ask-tier house task through `HouseActuator.request_*` →
`govern_enqueue` (per-cycle, cooldown and daily caps in memory per process).
**`JARVIS_WLED_URL`:** a LAN `http(s)` origin; unset ⇒ `wled_not_configured`. Writes
are echo-verified (`"v": true`), unchanged scenes are a no-op, and an unreachable
strip says `wled_unreachable` rather than guessing.
**Both still require** `JARVIS_ACTION_KERNEL` + `JARVIS_UNIFIED_ACTION_API`: every
`set_scene` crosses the kernel under the existing `house.control` kind, exactly like
`HouseActuator.execute_task` (DENY → nothing sent, QUEUE → `approval_required`).
**Revert:** unset either; nothing is driven.

### `JARVIS_WRITEBACK_LIVE` · `JARVIS_SOCIAL_LIVE` · `JARVIS_CALL_LIVE`

**Defaults: all OFF.** These are the three *live rails*. OFF, each broker builds the
Null client and the result is deferred/degraded — byte-identical to before.

- **`JARVIS_WRITEBACK_LIVE`** (`agents/core/writeback.py` `live_rail_enabled`): ON,
  `WriteBackBroker` constructs `HttpWriteBackClient`, so an **APPROVED** `writeback.*`
  or mapped `create_task` task performs the real Notion / GitHub / Calendar / Linear /
  Asana / Trello / Todoist / ClickUp / Sheets / M365 HTTP write. Refuses
  `credential_not_configured` when the SecretBroker lacks `<target>_token` — never an
  unauthenticated request; the `CONNECTOR_HOSTS` allowlist is asserted before every send.
- **`JARVIS_SOCIAL_LIVE`** (`agents/core/social.py`): ON, `HttpSocialClient` posts /
  replies / DMs on X after approval; needs secret `x_api_token`; the Postiz path is
  unaffected.
- **`JARVIS_CALL_LIVE`** (`agents/core/autonomy/call_broker.py`): ON, `HttpCallClient`
  dials via Twilio/Telnyx after approval **and** within the interrupt budget; needs
  `twilio_auth_token` / `telnyx_api_key` plus `JARVIS_CALL_CONFIG`
  `{provider: {account_sid|connection_id, from}}` or it refuses
  `call_config_missing:<keys>` before spending a budget slot.

**Approval queue unchanged:** every one of these stays ask-tier and kernel-mediated.
**Cost:** real external writes, posts and phone calls — after your approval.
**Revert:** unset + restart → Null clients.

### `JARVIS_MCP_HTTP_CLIENT` · `JARVIS_MCP_STDIO_ENV_BASELINE`

**Defaults: both OFF.**

- **`JARVIS_MCP_HTTP_CLIENT`** (`agents/core/mcp/http_transport.py:61`): ON,
  `MCPServer.connect()` speaks Streamable HTTP for `transport: streamable-http`
  configs and the tool-call contract widens to stdio + streamable-http via
  `client.active_tool_call_contract()` (**re-read per call**, so unsetting the flag
  revokes a persisted HTTP server at the next call). Outbound HTTP goes to configured
  MCP endpoints through the SSRF-pinned `PluginHTTPClient`; bearer headers live in
  memory only and are never persisted by `to_config`. OFF: `connect()` refuses
  `transport_disabled:JARVIS_MCP_HTTP_CLIENT`. The deprecated HTTP+SSE pair stays
  refused by name (`unsupported_transport:sse`) either way.
- **`JARVIS_MCP_STDIO_ENV_BASELINE`** (`agents/core/mcp/client.py`
  `STDIO_ENV_BASELINE_FLAG`): ON, stdio MCP subprocesses inherit **only**
  `STDIO_ENV_ALLOWLIST` (PATH/HOME/locale/temp/platform/toolchain/TLS roots) plus the
  per-server `env` overrides — never the hub's API keys, tokens or proxies. A server
  that relied on inheriting a hub credential stops seeing it; pass it explicitly in
  that server's `env`. Default off precisely so nothing breaks silently.

### `JARVIS_VLM_PRESET`

**Default: unset** (absolute pixels assumed — the only convention
`label at (x, y)` ever promised).

**Set:** names a pinned open grounder from `agents/core/llm/vlm.py:VLM_PRESETS`
(`qwen3-vl-4b`, `qwen3-vl-8b`, `ui-tars-1.5-7b`, `holo-3.1-35b-a3b`, `qwen3.8-27b` —
all Apache-2.0) so `screen_locator.LocalVLMLocator` normalizes that model's
coordinate convention (0–1000 relative vs absolute-on-resized) **before** a click.
Still requires `JARVIS_VLM_MODEL` (refuses `vlm_model_unset`); an unknown id refuses
`vlm_preset_unknown`.
**Cost/benefit:** the right preset makes grounding clicks land where the model meant;
the **wrong** preset mis-clicks — which is exactly why it is explicit rather than
guessed.

### `JARVIS_FAULT_INJECT` (test lane only)

**Default: OFF.** Arms the in-process failure-injection harness
(`agents/core/observability/fault_injection.py`: `llm_down` / `db_corrupt` /
`disk_full` / `clock_skew`) **for the test lane**.

**ON:** `inject(FaultPlan)` may patch httpx send, `open()` / `sqlite3.connect` under
the data root, and `time.time` for the duration of a `with` block. Nothing outside
`data_root()` is ever touched.
**What stays gated:** `JARVIS_HARDENED=1` refuses unconditionally
(`fault_injection_refused:hardened`, surfaced at boot via `boot_problem()`); path
targets outside `data_root()` are refused by name; a misspelled value stays off
(AUD-14).
**Cost:** none when off — the module is only imported by tests.

## Decision table

| Flag | Default | Effect ON | Cost / risk | Revert story |
|---|---|---|---|---|
| `JARVIS_ACTION_KERNEL` | off (`kernel/flags.py:14`) | Broker GRANTs enqueue as `act` (auto-run) instead of inbox-blocked; DENY blocks early | Autonomous execution of reversible actions; money/taint/owner floors remain | Unset + restart: hooks no-op structurally (`http_client.py:48`), tasks return to ask-floor |
| `JARVIS_UNIFIED_ACTION_API` | off (`capability_actions.py:17`) | Arms house/media/desktop facade; without it those routes refuse forever | Real-world side effects (lights, playback, desktop input) on GRANT | Unset + restart: `perform()` returns `disabled` (`capability_actions.py:129`) |
| `JARVIS_WEBHOOK_CHANNELS` | `{}` (`web.py:423`) | Wires configured governed channels (WhatsApp/Signal/Matrix/Teams/Google Chat) | New inbound attack surface; Signal needs external daemon; verify signatures at host | Remove key/kinds + restart: nothing registered; unknown kinds warn-and-skip (`webhook_channels.py:290`) |
| `JARVIS_TERMINAL_TARGETS` | off (checked in the `terminal_run` tool handler) | Arms the gated `terminal_run` ToolRPC tool: post-approval shell commands on named targets through the audit-chained policy plane, docker transport only (`environments/execution.py`) | Approved commands actually execute in the containment sandbox; **ssh** still refuses (`ssh_transport_not_implemented`), and the local host is available only with `JARVIS_TERMINAL_LOCAL_HOST` + `JARVIS_ACTION_KERNEL` + a durable approval (row below) | Unset + restart: the tool refuses `terminal_targets_disabled`; policy plane and audit chain stay inert |

| `JARVIS_PERMISSION_LEDGER` | off (`permission_ledger.py`) | Consent ledger enforces: first contact with an app/site/device/file-root/terminal-target answers `ask`; widening is the `permission.grant` approval task | More approval cards early on; `never` rows and the default-deny list always deny | Unset + restart: `check()` allows legacy callers again, ledger inert |
| `JARVIS_FILE_TOOLS` (+ `JARVIS_FILE_ROOTS`, `JARVIS_FILE_MAX_BYTES`) | off · `<data root>/workspace` · `2000000` | Registers `file_read`/`file_list` (ungated inside the roots) and gated `file_write`/`file_delete` ask-tier ToolRPC tasks with snapshot-restore | The model loop can read your files and, after approval, replace/delete them inside the named roots; snapshots have no GC yet | Unset + restart: `register_file_tools` is a no-op, no file tool on the allowlist |
| `JARVIS_TERMINAL_LOCAL_HOST` (+ `JARVIS_TERMINAL_LOCAL_ROOTS`, `JARVIS_TERMINAL_TIMEOUT_S`) | off · `data_path('workspace')` · `60`s (cap 600) | Adds the `local-host` target and `LocalHostTransport` (argv-only, cwd-jailed, capped, kill-on-timeout) | Approved commands really run on your host; rollback `none`. Hardline denylist → target policy → durable approval → contract → kernel GRANT all still apply, and `JARVIS_ACTION_KERNEL` is mandatory | Unset + restart: byte-identical `local_transport_not_implemented` |
| `JARVIS_BROWSER_ALLOW_PRIVATE_URLS` | off (`browser_transport.py`) | `PinnedResolver` in `lan` mode; the driver route layer admits RFC1918/loopback literals | Governed browsing can reach house devices. Honest limit: `BrowserPolicy.domain_allowed` still runs `check_ssrf` in public mode, so end-to-end LAN browsing needs a `BrowserPolicy` lan mode too | Unset + restart: unpinned hosts fail at name resolution |
| `JARVIS_COMPANY_MODE` | off (`autonomy/company_supervisor.py`) | Arms the work-run loop: one owner-approved goal worked across turns/reboots, ticked one governed step at a time | Sustained autonomous *sequencing*; authority is unchanged — every action still enters the approval queue, budgets (steps/seconds/deadline/interrupts) are hard, and only the judge can mark a run succeeded | Unset: every tick answers `disabled`; run rows remain as a record and are purged by a forget |
| `JARVIS_MODEL_PULL` | off (`routers/model_setup.py`) | `POST /api/onboarding/model-pull` may reach `action:model.pull` | Bandwidth + disk; needs both posture flags, loopback Ollama, and stays under `llm.model_pull_max_gb`; rollback is a manual `ollama rm` | Unset: the route refuses `model_pull_disabled` |
| `JARVIS_HESTIA_BRIDGE` | off (`house/hestia_bridge.py`) | Hestia may `observe()` (aggregate occupancy only) and `propose()` house tasks through `govern_enqueue` | Proposals land in the approval queue, capped per cycle/cooldown/day (in-memory, reset by a restart) | Unset + restart: no observation, no proposals |
| `JARVIS_WLED_URL` | unset (`house/wled.py`) | Names a LAN `http(s)` WLED origin so orb state can drive the strip | Real light writes — still `house.control` through the kernel (DENY → nothing sent, QUEUE → `approval_required`); needs `JARVIS_ACTION_KERNEL` + `JARVIS_UNIFIED_ACTION_API` | Unset: `wled_not_configured`, nothing is sent |
| `JARVIS_WRITEBACK_LIVE` | off (`writeback.py` `live_rail_enabled`) | APPROVED `writeback.*` / mapped `create_task` tasks perform the real Notion/GitHub/Calendar/Linear/Asana/Trello/Todoist/ClickUp/Sheets/M365 HTTP write | Real external writes after approval; refuses `credential_not_configured` without `<target>_token`; host allowlist asserted per send | Unset + restart: Null client, deferred/degraded results |
| `JARVIS_SOCIAL_LIVE` | off (`social.py`) | `HttpSocialClient` posts/replies/DMs on X after approval | Real posts; needs secret `x_api_token`; Postiz path unaffected | Unset + restart: Null client |
| `JARVIS_CALL_LIVE` | off (`autonomy/call_broker.py`) | `HttpCallClient` dials via Twilio/Telnyx after approval **and** within the interrupt budget | Real phone calls; refuses `credential_not_configured` / `call_config_missing:<keys>` before spending a budget slot; needs `JARVIS_CALL_CONFIG` | Unset + restart: Null client |
| `JARVIS_MCP_HTTP_CLIENT` | off (`mcp/http_transport.py:61`) | `MCPServer.connect()` speaks Streamable HTTP for `transport: streamable-http`; the tool-call contract widens via `active_tool_call_contract()` | Outbound HTTP to configured MCP endpoints through the SSRF-pinned `PluginHTTPClient`; bearer headers in memory only | Unset (no restart): `connect()` refuses `transport_disabled:JARVIS_MCP_HTTP_CLIENT`, contract reverts to stdio-only at the next call |
| `JARVIS_MCP_STDIO_ENV_BASELINE` | off (`mcp/client.py` `STDIO_ENV_BASELINE_FLAG`) | stdio MCP subprocesses inherit only `STDIO_ENV_ALLOWLIST` plus the per-server `env` — never the hub's API keys, tokens or proxies | A server that relied on inheriting a hub credential stops seeing it; pass it explicitly in that server's `env` | Unset + reconnect: full parent env inherited again |
| `JARVIS_VLM_PRESET` | unset (absolute pixels assumed) | Names a pinned open grounder from `vlm.py:VLM_PRESETS` so `LocalVLMLocator` normalizes 0–1000-relative vs absolute-on-resized coordinates before a click | Right preset = clicks land where the model meant; **wrong** preset = mis-clicks (why it is explicit). Still needs `JARVIS_VLM_MODEL` (`vlm_model_unset`); unknown id → `vlm_preset_unknown` | Unset: the locator assumes absolute pixels on the original screenshot |
| `JARVIS_FAULT_INJECT` | off (`observability/fault_injection.py`) | Arms the in-process failure-injection harness (llm_down / db_corrupt / disk_full / clock_skew) for the **test lane** | `inject()` may patch httpx send, `open()`/`sqlite3.connect` under the data root, and `time.time` inside a `with` block; nothing outside `data_root()` is touched | Unset: nothing is patched. `JARVIS_HARDENED=1` refuses unconditionally (`fault_injection_refused:hardened`) |

Kernel flag alone ≠ smart home. Both kernel + unified flags = facades live.
Webhook channels cost no dependency, only configuration discipline.
