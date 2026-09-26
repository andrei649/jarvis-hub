# FLAGS.md — action-posture flags: know what flipping costs

Environment flags change what Nerva may do without asking you. **Nearly every flag on
this page ships default-off** (`env_flag` returns False unless explicitly set,
`agents/core/env_config.py:78`); string/list flags are unset by default and the
surface behind them refuses by name. The two exceptions ship **on** because off is the
dangerous setting: `JARVIS_CHANNEL_PAIRING` (an unpaired chat bot answers anyone) and,
since H502, `JARVIS_MCP_STDIO_ENV_BASELINE` (off hands every spawned MCP server the
whole keyring). The `Default` column of the decision table is the authority. This is what each one actually buys you — and
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
`action:media.present` (`agents/core/media_director.py:1092`), then `perform()`:
missing required params → `refused` before any authorization
(`capability_actions.py:139`); kernel DENY → `refused`, QUEUE → `queued` with an
approval card, GRANT → handler runs (`capability_actions.py:175`). With either
flag off the same POST returns `status: "disabled"` — a refusal, never a device
command.

**The model's `speak` tool (H313) takes the same facade.** Registered only while
`JARVIS_MEDIA_DIRECTOR` is on, it is a gated ToolRPC tool (owner at the HUD or
voice loop only — never inbound, guest or unattended turns): the call is an
approval card naming the device, raised through the kernel as the exact
`toolrpc.speak` row it becomes, and only that accepted row synthesizes the clip
and `perform()`s `action:media.present` in `announce` mode; the kernel's `queue`
on that present is honoured as the accepted row and logged as
`speak.durably_approved`. No card is raised that could only be refused: with
either flag off, no bound kernel, no media root, no speech backend, no driver
for the device, or (for `presence:auto`) no configured presence room with a
speaker, the call refuses by name (`unified_action_api_disabled`,
`action_kernel_disabled`, `kernel_unavailable`, `media_root_unconfigured`,
`tts_unavailable`, `no_media_driver`, `presence_room_unconfigured`). It never
reaches a driver itself. Clips live under `<first JARVIS_MEDIA_ROOTS>/.nerva-speak`
(owner-only files; the newest 16 are kept because an async driver may still be
streaming one, and partial writes older than 5 minutes are removed). An
`announce` session never holds its device: the next present there is not refused
by etiquette and spends no interrupt budget, and what the announcement cut into
stays the restore point.

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
**ON:** `file_read` / `file_list` / `file_search` are ungated *inside* `JARVIS_FILE_ROOTS`
(no `..`, no symlink escape, secret-looking names refused, bytes/entries/matches bounded;
`file_search` is a *literal* content search — no regex, no ripgrep — that reports every cap
it hit; `file_read` returns a `.pdf`/`.docx` as extracted text when `pypdf`/`python-docx` is
installed, and names the missing parser otherwise);
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

### `JARVIS_MCP_HTTP_CLIENT` · `JARVIS_MCP_STDIO_ENV_BASELINE` · `JARVIS_MCP_STDIO_ALLOWED_ENV`

**Defaults: `JARVIS_MCP_HTTP_CLIENT` OFF · `JARVIS_MCP_STDIO_ENV_BASELINE` ON ·
`JARVIS_MCP_STDIO_ALLOWED_ENV` empty** (H502 — the env baseline flipped from opt-in to
the default; `JARVIS_MCP_STDIO_ALLOWED_ENV` is the narrow remedy, `=0` the blunt one).

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
  `STDIO_ENV_BASELINE_FLAG`) — **on by default since H502.** stdio MCP subprocesses are
  handed **only** `STDIO_ENV_ALLOWLIST` (PATH/HOME/locale/temp/platform/toolchain/TLS
  roots), the names in `JARVIS_MCP_STDIO_ALLOWED_ENV` and the per-server `env`
  overrides — they are not handed the hub's API keys, tokens or proxies. An MCP server
  is a third-party binary the owner attached; attaching it is not a decision to hand it
  every provider credential on the box, so withholding them is the default rather than
  an opt-in nobody sets. The drop is **not silent**: each connect logs one INFO line,
  `MCP <server>: <n> host variables withheld (allowlist baseline)` — the count only,
  never a variable name or value (the names alone would enumerate which provider keys
  this box holds). The count is of host **values** the child does not receive, so a
  per-server `env` that shadows a host variable is counted too. The live posture is
  reported as `env_baseline` by `GET /api/admin/mcp`, read from the flag at request
  time, so the admin panel cannot claim a posture the running process is not applying;
  a row that spawns no subprocess (non-stdio, or stdio with no `command`) reports
  `null` rather than a badge it has not earned.

  **What this is and is not.** It stops a server from *being handed* the hub's
  credentials. It is **defence in depth, not a security boundary**: the child runs as
  the same UID as the hub, in no namespace and no sandbox, so on Linux it can read the
  hub's real environment out of `/proc/<ppid>/environ` whatever it was handed. A
  deliberately hostile server — the "backdoor wearing an MCP costume" this work is aimed
  at — still recovers the withheld keys that way. What the baseline does buy is real:
  a careless or over-broad third-party server no longer sees credentials it never asked
  for, and they no longer leak into that server's logs, telemetry or crash reports. The
  boundary needs the still-unshipped command screener plus process isolation (separate
  UID, namespace or container).

  **If a server of yours broke on the upgrade**, set `JARVIS_MCP_STDIO_ALLOWED_ENV`
  (below). Do **not** reach for the per-server `env` block: it wins over the baseline,
  but it has no owner-facing surface — `POST /api/admin/mcp` has no `env` field,
  `MCPManager.to_config()` does not persist one and `load_from_config()` does not read
  one, so it is settable only from in-process Python (first-party callers such as
  `agents/core/mcp/worldview_write.py`) and does not survive a restart.
  `JARVIS_MCP_STDIO_ENV_BASELINE=0` restores the historical full inherit wholesale, for
  every stdio server on the box at once — the last resort, not the first.
- **`JARVIS_MCP_STDIO_ALLOWED_ENV`** (`agents/core/mcp/client.py`
  `STDIO_ENV_ALLOW_FLAG`, `stdio_env_extra_allowed`) — **empty by default.** A
  comma-separated list of host variable **names** stdio MCP servers may keep inheriting
  on top of the allow-list, e.g. `JARVIS_MCP_STDIO_ALLOWED_ENV=GITHUB_TOKEN`. This is
  the owner-reachable remedy for the H502 flip: it names the one credential a server
  legitimately needs instead of surrendering the whole environment. A name listed here
  is passed through **even when it looks like a credential** — naming one is the point.
  Host-wide, not per-server: every stdio MCP server the hub spawns sees every name on
  the list, so keep it to the minimum. Names are matched case-insensitively; names not
  set on the host are ignored.

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

## Wave 2026-09-07 — the front door (HA-5b)

Four variables, three doors. One of them is the exception to this page's rule: it ships
**default ON**, because it is a guard, not a capability — switching it off is what costs.

### `JARVIS_CHANNEL_PAIRING`

**Default: ON** (`agents/core/channels/pairing.py`, `env_flag(..., True)`). An unknown sender on a
chat channel is held until the owner pairs them (HUD Pairing card, or the single-use
`t.me/<bot>?start=<token>` deeplink). **What `0` changes:** every sender is admitted — and the
boot guard `assert_guarded_channels` then refuses to start a channel whose token is set unless
an allowlist names at least one id or `JARVIS_CHANNEL_OPEN=1` acknowledges an open bot. A typo
refuses boot like the other posture flags. The guard runs twice: early, and again from the
lifespan once `.env` is loaded (`assert_front_door`), so a token that lives only in `.env` is
seen. The doors it counts: the Telegram and Discord bots, Slack Socket Mode when both
`SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set, the webhook map, the IMAP inbox
(whose sender is the `From` address — forgeable without DMARC, so a paired address is a held
stranger let in, not an authenticated owner). **Cost of ON:** on upgrade the owner must pair
themselves once — or set `TELEGRAM_ALLOWED_USER_IDS`, which now passes the gate on its own.
With pairing on, the unauthenticated `POST /api/channels/pairing/request` door is live too
(bounded pending list, store-wide code-guess budget, the rate limiter); `0` closes it.

### `JARVIS_CHANNEL_OPEN`

**Default: OFF.** The acknowledgement that a chat bot with no allowlist and pairing switched off
may answer anyone. Prints a `[SECURITY]` line at boot. Applies to every listed inbound channel
at once — there is no per-channel form; set it only on a box that talks to nobody but you.

### `JARVIS_CA_BUNDLE`

**Default: unset** (`agents/core/tls_trust.py`, re-exported by `agents/core/http_client.py`).
A PEM file of extra certificate authorities to trust for plugin **and model** egress. Every
plugin client is built `trust_env=False` — so a hostile environment cannot silently redirect
egress through a proxy nobody chose — and therefore verified against certifi alone. Behind a
TLS-inspecting proxy or a private CA that meant every outbound call failed, the search backend
swallowed the error, and `web_search` answered `count: 0`: indistinguishable from "nothing
found". Point this at the inspecting proxy's root and it works and stays verified. Since H504
every model backend's client (`llm_async_client`: Anthropic, Gemini, OpenRouter, OpenAI
Responses, xAI, LM Studio, Ollama, the VLM) verifies against the same anchor, always as an
explicit SSLContext, so httpx never reads `SSL_CERT_FILE` on its own. `SSL_CERT_FILE` is
honoured as a second spelling. **It can only ADD.** There is no value of either variable that
turns certificate checking off, and none that removes an anchor the box already trusted.

**At start (H504) a broken value stops the hub.** The lifespan checks every CA variable that is
set — `JARVIS_CA_BUNDLE`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` (each must be
a file that loads and holds at least one certificate; a pinned self-signed server certificate
counts) and `SSL_CERT_DIR` (each entry a directory) — and certifi itself. A problem is printed
with the variable, its value, what is wrong, a command that repairs it for this shell (and the
`.env` file that set it, when one did), instead of an unnamed `FileNotFoundError` on the first
model call. On a home LAN you will never need any of this.

### `JARVIS_TLS_INSECURE_TARGETS`

**Default: unset** (`agents/core/tls_trust.py` `verify_for`). Comma-separated model provider
ids (`ollama`, `lm-studio`, `vlm`, …) or hosts (`gpu.lan`) whose clients are built **without**
certificate verification — for a LAN model server on a self-signed certificate you cannot
anchor. Matching is exact (case-insensitive, a trailing dot ignored): `lan` does not match
`gpu.lan`. It is the only way verification is ever off: a bad CA path never is. Every client
built that way logs a WARNING naming its URL, and the start logs the list once. **The hardened
profile (`JARVIS_HARDENED=1`) ignores the list** and logs an ERROR instead. Prefer
`JARVIS_CA_BUNDLE` with the server's certificate: that keeps the check on.

### `JARVIS_TRUSTED_PROXIES`

**Default: unset** (`agents/core/proxy_trust.py`). Comma-separated networks or addresses
(`127.0.0.1/32`, `10.0.0.5`, `fd00::/64`) of the reverse proxies whose forwarding headers may
be believed. An entry is the proxy's **own address**, never a range that also contains
clients — a client inside a listed range can name any client it likes; an entry wider than
/24 (v6: /64) is warned about at boot by position. The chain is walked right-to-left and an
all-trusted chain yields the hop the proxy saw, never a typed leftmost value. The same list
decides `X-Forwarded-Proto`: from a listed peer, one `http`/`https` value becomes the request
scheme (so the widget snippet and the MCP resource URL say `https://` behind a TLS proxy);
from anyone else it is ignored. Unset: forwarding headers are ignored — not even loopback's
are believed — a request that carries them fails the localhost gate closed, is
rate-limited by its socket address, and is **not** localhost-exempt from the throttle even
when that address is `127.0.0.1` (an unlisted same-box proxy is not a local client). `*`,
`/0` and more than 64 entries refuse boot naming the variable. Set in `.env` like
everything else: the lifespan re-checks the list once `.env` is loaded. Once it is loaded,
the set the box ended up trusting is logged once at INFO under `jarvis.proxy_trust`, e.g.
`JARVIS_TRUSTED_PROXIES: trusting 2 proxy network(s): 127.0.0.1/32, 10.0.0.5/32`, next to
the warnings that belong with it (a wide entry, the legacy flag) — formatted, redacted and
in the log file, never on bare stderr at import. The line uses the canonical form, so
`10.1.2.3/24` reads back as `10.1.2.0/24` and duplicates are folded. It is said again
whenever the value changes, and never when nothing is trusted. The old
`JARVIS_TRUSTED_PROXY=1` is deprecated and now means *loopback only* (a same-box Caddy) with
a one-time warning, and its INFO line names `127.0.0.0/8, ::1/128`; it never widens past
that.

**This is the only forwarding-header allowlist.** uvicorn has its own (`proxy_headers` +
`forwarded_allow_ips`, loopback by default) that would rewrite the client address and
scheme before this list is consulted. `serve.py` builds uvicorn with it switched off, and
`docker-compose.yml` passes `--no-proxy-headers`. `FORWARDED_ALLOW_IPS`,
`UVICORN_FORWARDED_ALLOW_IPS` and, on a `uvicorn` command line, `--forwarded-allow-ips` are
checked at boot: an entry that is `*`, a `/0`, not an address, or a peer outside this list
(and outside uvicorn's own loopback default) refuses boot naming the variable — list the
proxy here instead. A raw `python -m uvicorn agents.web:app` without `--no-proxy-headers`
still believes loopback's headers inside uvicorn, and the boot says so at INFO
(`uvicorn proxy headers (uvicorn CLI): … believed from 127.0.0.1/32, ::1/128 …`). A
launcher that embeds uvicorn some other way (`uvicorn.run(app, forwarded_allow_ips=…)`, a
gunicorn worker) passes its value out of the app's sight — use `serve.py`.

### `JARVIS_ALLOWED_HOSTS`

**Default: unset** (`agents/core/host_policy.py`). Names that may appear in the `Host`
header besides the ones always accepted (loopback names, IP literals, the bind and server
address): `nerva.<tailnet>.ts.net`, the Caddy site name. Any other name is `400 host not
allowed` — that is the DNS-rebinding defence. `*` and leading-dot wildcards refuse boot.
`/healthz`, `/readyz`, `/metrics` are exempt. No WebSocket route exists today; a future one
must call `host_accepted` itself, since the HTTP middleware would not cover it.

## Wave 2026-09-10 — the model may write a script (K1)

One switch, and the only one on this page that is a **runtime setting** rather than an
environment variable: it lives in the settings store next to the rest of the `llm.*`
family, and it is read at composition time, so switching it on needs a restart the way
`JARVIS_FILE_TOOLS` does.

### `llm.execute_code`

**Default: OFF** (`agents/core/code_tools.py`).

**OFF:** `register_code_tools` is a no-op — **`execute_code` does not exist on the
ToolRPC allowlist at all**, so no profile can offer it and no turn can name it. Off has
to mean absent rather than present-and-refusing: a tool the model can see but never use
costs context on every turn and teaches it to keep trying.

**ON:** the model may submit one Python script that runs in the sandbox, where
`jarvis_tool_call(name, args)` reaches tools over the existing file-RPC bridge. The
point is arithmetic, not authority: a script can make many calls and return one answer,
so a large intermediate result is filtered inside the container instead of being paid
for in context.

**What it does not widen.** The script's reach is bound by K0
(`agents/core/sandbox_invocation.py`) from the turn's own principal and origin, so it is
exactly the set that turn was offered — a guest's script gets a guest's tools. It cannot
call `execute_code` (one turn, one container). A **gated** tool called from inside still
only enqueues an ask-tier task and returns `approval_required`; that invariant is the
reason `execute_code` itself is ungated. The container is the sandbox's own:
`--network none`, read-only, memory/pids/wall bounded, and every response is
secret-scrubbed on the way back.

**When it refuses:** `sandbox_not_isolated` when the host has no Docker/WASM backend —
model-written code never falls back to the host interpreter, even where
`allow_subprocess` would let a developer's own script run; `sandbox_unavailable` with no
sandbox composed; `authority_unavailable` if the binding fails; `code_execution_disabled`
if the setting is switched off after boot (it is re-read on every call).

**Cost:** the model can run arbitrary code inside the container, and a script's inner
calls are not visible to the tool loop's per-tool caps or its repeated-call detector —
they are bounded instead by `security.sandbox_max_tool_calls` (default 50) and the
sandbox's wall clock. Output is capped per stream at the smaller of 50 KB and the
sandbox's own `max_output_bytes`; the overflow is dropped with a notice saying how much,
not spilled to a file.

**Revert:** set it back to `false` and restart; the tool disappears from the allowlist.
A call already in flight is refused on its next tool call.

### `llm.execute_code_sessions` (+ `llm.execute_code_image`, `llm.execute_code_max_kernels`, `llm.execute_code_idle_ttl`)

**Defaults: OFF · unset · `4` · `900`s.** Runtime settings, read at composition.

**OFF:** every `execute_code` call is the K1 one-shot — a container per call, nothing
kept. The tool's schema has no `reset` and its description promises no persistence, so
the model is never told about a kernel that is not there.

**ON:** the model gets a **resident interpreter per authorized session**. Variables,
imports and loaded data survive between calls, which is the difference between an
analysis that finishes and one that spends its context re-loading the same dataframe.
It needs `llm.execute_code_image` **pinned by digest** (`repo@sha256:…`); an unpinned
or missing image leaves sessions off with a warning, because a kernel that lives for an
hour deserves the pin the acquisition profile already demands.

**What keeps a long-lived interpreter from being a bypass.** An interpreter authorized
once and then fed arbitrary later code is a kernel bypass with extra steps: cell 1 is
reviewed, cell 400 is not. So *state* persists and *permission* does not.

| every cell | what happens |
|---|---|
| binds fresh | a new K0 `SandboxInvocation` from the live principal — a variable created while a tool was offered is still just a variable once it is not |
| crosses the kernel | the cell is a `tool.rpc` action; a DENY (halted kill-switch, over budget, runaway loop) refuses it **before** a byte reaches the interpreter. No new action kind |
| gets its own mailbox | tool calls go to a directory created for that cell and removed after, serviced under that cell's authority; a `jarvis_tool_call` captured ten cells ago writes where nobody is reading |
| checks the stop | ESTOP is read before every cell, and an engaged stop **tears every kernel down** rather than leaving processes alive to resume |

**Which kernel you get** is keyed to agent × principal × session × data scope, all read
off the invocation the host resolved. There is no model-supplied kernel id, so two
sessions cannot share one even by asking for the same name.

**Losing state is always named.** `reset`, idle expiry, eviction (past
`llm.execute_code_max_kernels`), a crash, a cell timeout and ESTOP each produce a
`continuity` reason on the next cell with `state_lost: true`. A fresh kernel reads
`new`; a continuing one reads `continued`. Nothing silently hands a caller a new
interpreter while they think they still hold their data.

**Cost:** a long-lived process per active session (memory, pids and wall bounded by the
container), and a cell can leave a thread running between cells — it keeps the CPU it
was given and gets `tool_calls_unavailable` if it tries to call a tool with no cell in
flight. Cells in one session serialize; a full pool with every kernel busy refuses the
newcomer rather than killing a running cell.

**Revert:** set it back to `false` and restart. The next call is a one-shot again, and
says nothing about continuity — the fallback is named in the result shape, not silent.

## Decision table

| Flag | Default | Effect ON | Cost / risk | Revert story |
|---|---|---|---|---|
| `JARVIS_ACTION_KERNEL` | off (`kernel/flags.py:14`) | Broker GRANTs enqueue as `act` (auto-run) instead of inbox-blocked; DENY blocks early | Autonomous execution of reversible actions; money/taint/owner floors remain | Unset + restart: hooks no-op structurally (`http_client.py:48`), tasks return to ask-floor |
| `JARVIS_UNIFIED_ACTION_API` | off (`capability_actions.py:17`) | Arms house/media/desktop facade; without it those routes refuse forever | Real-world side effects (lights, playback, desktop input) on GRANT | Unset + restart: `perform()` returns `disabled` (`capability_actions.py:129`) |
| `JARVIS_WEBHOOK_CHANNELS` | `{}` (`web.py:423`) | Wires configured governed channels (WhatsApp/Signal/Matrix/Teams/Google Chat) | New inbound attack surface; Signal needs external daemon; verify signatures at host | Remove key/kinds + restart: nothing registered; unknown kinds warn-and-skip (`webhook_channels.py:290`) |
| `JARVIS_TERMINAL_TARGETS` | off (checked in the `terminal_run` tool handler) | Arms the gated `terminal_run` ToolRPC tool: post-approval shell commands on named targets through the audit-chained policy plane, docker transport only (`environments/execution.py`) | Approved commands actually execute in the containment sandbox; **ssh** still refuses (`ssh_transport_not_implemented`), and the local host is available only with `JARVIS_TERMINAL_LOCAL_HOST` + `JARVIS_ACTION_KERNEL` + a durable approval (row below) | Unset + restart: the tool refuses `terminal_targets_disabled`; policy plane and audit chain stay inert |

| `JARVIS_PERMISSION_LEDGER` | off (`permission_ledger.py`) | Consent ledger enforces: first contact with an app/site/device/file-root/terminal-target answers `ask`; widening is the `permission.grant` approval task | More approval cards early on; `never` rows and the default-deny list always deny | Unset + restart: `check()` allows legacy callers again, ledger inert |
| `JARVIS_FILE_TOOLS` (+ `JARVIS_FILE_ROOTS`, `JARVIS_FILE_MAX_BYTES`) | off · `<data root>/workspace` · `2000000` | Registers `file_read`/`file_list`/`file_search` (ungated inside the roots) and gated `file_write`/`file_delete` ask-tier ToolRPC tasks with snapshot-restore | The model loop can read and search your files and, after approval, replace/delete them inside the named roots; snapshots have no GC yet | Unset + restart: `register_file_tools` is a no-op, no file tool on the allowlist |
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
| `JARVIS_MCP_STDIO_ENV_BASELINE` | **on** (`mcp/client.py` `STDIO_ENV_BASELINE_FLAG`) | stdio MCP subprocesses are handed only `STDIO_ENV_ALLOWLIST` + `JARVIS_MCP_STDIO_ALLOWED_ENV` + the per-server `env` — they are not handed the hub's API keys, tokens or proxies; one INFO line per connect reports the withheld **count** of host values (never names or values) and `GET /api/admin/mcp` reports `env_baseline` per spawning row (`null` for rows that spawn nothing) | **Defence in depth, not a boundary:** the child is same-UID, so a hostile server still reads the hub env from `/proc/<ppid>/environ`; the boundary needs the unshipped command screener + process isolation. A server that relied on inheriting a hub credential stops seeing it — the remedy is `JARVIS_MCP_STDIO_ALLOWED_ENV`, **not** the per-server `env` (in-process only, no config surface) | `JARVIS_MCP_STDIO_ENV_BASELINE=0` + reconnect: full parent env inherited again, for every stdio server at once |
| `JARVIS_MCP_STDIO_ALLOWED_ENV` | empty (`mcp/client.py` `STDIO_ENV_ALLOW_FLAG`) | Comma-separated host variable **names** stdio MCP servers may keep inheriting on top of the allow-list; a listed name passes through even if it looks like a credential | Host-wide, not per-server: every stdio MCP server sees every listed name — list the minimum. Still narrower than `=0`, which surrenders the whole environment | Remove the name + reconnect: that variable is withheld again |
| `JARVIS_VLM_PRESET` | unset (absolute pixels assumed) | Names a pinned open grounder from `vlm.py:VLM_PRESETS` so `LocalVLMLocator` normalizes 0–1000-relative vs absolute-on-resized coordinates before a click | Right preset = clicks land where the model meant; **wrong** preset = mis-clicks (why it is explicit). Still needs `JARVIS_VLM_MODEL` (`vlm_model_unset`); unknown id → `vlm_preset_unknown` | Unset: the locator assumes absolute pixels on the original screenshot |
| `JARVIS_FAULT_INJECT` | off (`observability/fault_injection.py`) | Arms the in-process failure-injection harness (llm_down / db_corrupt / disk_full / clock_skew) for the **test lane** | `inject()` may patch httpx send, `open()`/`sqlite3.connect` under the data root, and `time.time` inside a `with` block; nothing outside `data_root()` is touched | Unset: nothing is patched. `JARVIS_HARDENED=1` refuses unconditionally (`fault_injection_refused:hardened`) |
| `JARVIS_CHANNEL_PAIRING` | **on** (`channels/pairing.py`) | `0` admits every sender; the boot guard then demands an allowlist or `JARVIS_CHANNEL_OPEN=1` | Off = anyone who finds the bot talks to it | Set back to `1` (or unset) + restart: strangers are held again |
| `JARVIS_CHANNEL_OPEN` | off (`channels/pairing.py`) | Acknowledges an open chat bot (no allowlist, pairing off) so boot proceeds with a `[SECURITY]` line | Every listed channel answers anyone | Unset + restart: boot refuses until an allowlist or pairing guards the channel |
| `JARVIS_CA_BUNDLE` | unset (`tls_trust.py`) | Extra CA roots for plugin and model egress (adds only; verification stays on); every set CA variable and certifi validated at start | A root you add is trusted for every plugin fetch and model call — point it at your own proxy's CA, nothing else; a broken CA variable refuses boot with its repair | Unset + restart: back to certifi alone |
| `JARVIS_TLS_INSECURE_TARGETS` | unset (`tls_trust.py` `verify_for`) | Named model provider ids or hosts get clients with certificate verification **off**, each announced by a WARNING naming the URL | A listed target can be impersonated by anyone on the path — list only a LAN server you cannot anchor; ignored (ERROR) under `JARVIS_HARDENED=1` | Unset + restart: every client verifies again |
| `JARVIS_TRUSTED_PROXIES` | unset (`proxy_trust.py`) | Forwarding headers (`X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Proto`) believed only from these networks; XFF walked right-to-left; uvicorn's own proxy-header layer is off under `serve.py` | A listed peer can name any client address — list only proxies you run; a malformed list, or a `FORWARDED_ALLOW_IPS` wider than it, refuses boot | Unset + restart: headers ignored, fail closed |
| `JARVIS_ALLOWED_HOSTS` | unset (`host_policy.py`) | Extra `Host` names accepted by the rebinding guard | A listed name is reachable from any page that can resolve it to the box — list only names you own; `*` refuses boot | Unset + restart: only loopback names, IP literals and the bind/server address pass |
| `llm.execute_code` *(runtime setting)* | off (`code_tools.py`) | Registers ungated `execute_code`: one model-written Python script per call, running in the sandbox, calling tools over file-RPC | Arbitrary code inside the container; inner calls bypass the tool loop's per-tool caps and repeated-call detector (bounded instead by `security.sandbox_max_tool_calls` and the sandbox timeout). Reach is K0-bound to the turn's own offered set, gated tools still only enqueue, and no isolated backend means `sandbox_not_isolated` rather than a host run | Set `false` + restart: `register_code_tools` is a no-op, nothing on the allowlist |
| `llm.execute_code_sessions` *(runtime setting)* | off · needs `llm.execute_code_image` pinned by digest (`session_kernels.py`) | A resident interpreter per agent×principal×session×data-scope: variables, imports and loaded data persist between `execute_code` calls | A long-lived process per active session. Every cell still re-binds K0 authority, crosses the Action Kernel, gets its own tool-call mailbox and re-reads ESTOP — so state persists and permission does not; every loss of state is named on the next cell | Set `false` + restart: back to the K1 one-shot, kernels destroyed |
| `llm.tool_result_thresholds` *(runtime setting)* | `{}` (`tool_result_store.py`) | Per-tool byte ceilings for what a result may put in the context window, as `{tool: bytes}`. Beats the tool's own declaration and the `mcp_` family default; loses to a pinned tool (`file_read` is pinned to no limit, because it is how a spilled result is read back) | Raising one lets that tool fill more of the window; lowering it sends more of its output to disk. Nothing is lost either way — over the ceiling the full result is spilled and the model gets a preview naming the file | Set `{}` (no restart): back to the window-scaled default |
| `llm.tool_result_context_window` *(runtime setting)* | `0` = auto (`agent_runtime.py`) | The context window the per-result (15 %) and per-turn (30 %) budgets scale against, with 8 KB / 16 KB floors. `0` reads the window of the model the turn is actually running on | Setting it wrong-large lets a turn overfill a small window; wrong-small spills results that would have fit. Distinct from `llm.tool_loop_context_tokens`, which is the *transcript* budget compaction folds against | Set `0` (no restart): the model's own window again |
| `llm.tool_result_retention_seconds` · `llm.tool_result_max_files` *(runtime settings)* | `86400` · `512` (`tool_result_store.py`) | How long a spilled result stays readable under `data/workspace/tool_results/`, and how many are kept. Swept on every write, oldest first, never the file just written | Longer retention keeps more tool output on disk; shorter can retire a spill the model has not read back yet | Set back (no restart): the next write sweeps to the new limits |

Kernel flag alone ≠ smart home. Both kernel + unified flags = facades live.
Webhook channels cost no dependency, only configuration discipline.
