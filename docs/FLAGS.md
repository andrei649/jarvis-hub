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

### `JARVIS_VOICE_COMMANDS` · `JARVIS_VOICE_COMMAND_TIMEOUT_S`

**Defaults: OFF · `30`s for TTS, `120`s for STT (an override is clamped to 1–600).**

**OFF:** the owner's TTS/STT command providers (`voice.tts_command`,
`voice.stt_command`, H613) never run, and `POST /api/admin/voice/commands` refuses to
ask for one (`409 not_armed`); clearing one still works.
**ON:** an approved command runs: argv-only (never a shell), in a private 0700 run
directory, scrubbed environment, one deadline, capped stdout/stderr; only audio (or a
transcript) it writes inside that directory is read back.
**What stays gated anyway:** the two settings are ROUTE_ONLY — a generic settings write,
an import, a reset, an undo and `nerva config set` cannot touch them — and setting one
waits for a human in the Decision Inbox (irreversible tier, kind
`settings.voice_command`); the card names every file that runs (the program and, for an
interpreter, its script, each with its size and sha256), the full argv and who it runs
as, and only a plain accept of that card writes it. Every spawn re-validates the argv
(absolute program that exists, not a shell or a launcher — nor a program that runs code
from its arguments, such as the dynamic loader, `find`, `awk`, `git`, an editor — no
inline-code interpreter, hardline denylist, no credential in the line) and checks every
bound file's identity (device, inode, size, mtime, sha256) against the approval, once more
right before the spawn: a replaced, rewritten or upgraded file needs approving again. A
bound file may not sit under a directory another user can write (group- or
world-writable without the sticky bit). A timeout ends the command's whole process group.
For whisper.cpp, its `[00:00:00.000 --> …]` timestamps are stripped (or pass `-nt`). Off
in safe mode.
In task-mediation `enforce` mode, command registration requires signed kernel
authority and still waits for a human; `hold` refuses registration. The worker
validates the recorded decision, current policy/scope and halt state at execution.
A speech call waiting for a process slot keeps its original approval and bound
file identities: reapproving even identical argv does not authorize that old call.
Named commands use the same gate: the admin route accepts an optional `provider_id`,
and Settings → Voice lists independent TTS/STT providers. Choose `provider:<id>` as
the TTS voice or set `voice.stt_command_provider` for command STT (empty keeps the
legacy slot). Invalid or absent named selections never select the legacy command.
Names are lowercase, at most 32 characters, and cannot replace built-in providers.
The separate settings-database table retains revisions and cleared-name tombstones:
16 active and 128 historical names per side. Clear invalidates pending approvals
and waiting calls for that name; it does not terminate a program already running.
Generic settings reset/import/undo cannot install or erase named command authority.
**Cost:** an approved program runs as the hub's user, with that user's permissions.
**Revert:** unset + restart, or clear the command in Console → Admin → Settings → Voice → Command providers.
**`voice.local_only`:** keeps speech on this machine — only Piper, Kokoro or XTTS speak. It never
runs the TTS command: a command is the escape hatch for any provider (a cloud one included), and
the hub cannot check where it sends the text, so availability reports never count it as local.

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
builds, but a blocked run could never be resumed, so it says so. The runtime is
built from the **orchestrator's own queue and intake** (`autonomy_queue`,
`autonomy.govern_enqueue`; H464b — before that it looked for names the orchestrator
never had, so in production it never built and no sweep ran). **Safe mode leaves it
out** (H464c): no runtime is built and no sweep is scheduled, and a sweep that finds
safe mode on does nothing.

**What it will actually do.** The planner is the **checklist the owner read on the
approval card** (`GoalDraft.plan`, inside the payload fingerprint, so editing it
invalidates the approval). A goal approved with **no** plan and no explicitly-passed
model planner **proposes nothing** and goes straight to grading: "you approved a goal
with no plan, so nothing happened" is a better outcome than a model improvising a
night's work from a one-line title. The checklist is **read back from the goal's own
approval task** (the task in the run's `approved_by`): a human must have accepted
that very task, the goal must match the run (approval, title, deadline, budget), and
its payload must fingerprint to **the fingerprint the run pinned when it opened**
(H464c) — never merely to the one the payload now carries about itself. **One
approval task opens one run**: a retried `goal.approve` gets the run it already
opened. A read that **fails just now holds** the run (no step, no park, no grade —
the next sweep reads again); the first held tick writes a `hold.start` event (one
per hold, not one per sweep), the tick that can plan again writes `hold.end`, and
the brief says `held — …` with the reason meanwhile (H464d). A goal that **provably
does not bind** (a policy decision, an edit, another run's goal, a run opened before
the pin existed, an approval task that can no longer be minted into a goal at all)
**stops** the run with the reason on its record
(`plan not bound to its approval: …`, shown in plain words in the brief); an
approved row the scope refuses stops it too (`approved row refused by scope: …`) —
neither is ever graded as a finished checklist. A row's queued task kind must be
inside the goal's scope (it is a scope kind or sits under a whole one, then a dot:
`research.collect` under `research`, `file.write.append` under `file.write`), or the
card is refused. A row whose step **failed** (the governed intake raised or returned
no task, or its task vanished) is not done: it is tried again on a later sweep, at
most 3 times in all, then the run stops with `approved row kept failing: <row>` —
and a read of the run's own steps that fails holds the tick rather than asking for
row 1 again (H464d).

**When the checklist is done.** A step's task counts as done for the checklist once
it is *approved*, so the plan can finish while that work is still running. A
finished plan then **waits on its own approved tasks that are still running** — no
step and no verdict, only wall-clock time (at most once per task; "stop waiting"
sticks): the run is parked on `task:<id>` and resumes on the first sweep after the
task finishes. The wait is capped at 6 h and at the time left **less a grading
margin**, the same before a deadline as before the end of the budget (H464d: exactly
what grading needs — the time from a tick to the next sweep on which the run is due
again, given the sweep cadence `autonomy.company_tick_seconds` and the scheduler's
per-run interval of 300 s, plus a minute: 360 s at the default 300 s cadence, 360 s
at 60 s, 420 s at 120 s, 1,260 s at 1,200 s; never a share of the budget), so the run
is still due, and graded, on a sweep before it runs out at any cadence; with no time
to spare past the margin it does not wait at all. A run with more time left than that
waits for its task and is graded on the finished work. A sweep that starts a moment
early (the timer's own jitter, up to 1 s) still counts as one interval since the
run's last tick. Production still has **no grader wired**, so after that the run idles
("no work left, and no grader is wired") until its budget ends — and then the sweep
**settles it** like any spent run (`stopped`, `budget:<limit>`, "ran out of budget"
in the brief), where before it was skipped and left open for ever (H464d).

**Cost:** an active run consumes its own budget — steps, elapsed seconds, deadline and
a hard cap on how many times it may interrupt you. With the runtime's authoritative
task reader, a proven pending human approval excludes up to 360 seconds per
approval-block interval from elapsed-seconds accounting. Overlapping asks share
that cap; a task deadline can shorten it. Auto-approved tasks and unproven waits
receive no credit. The first durable human decision ends the interval, including
defer followed by a later approval. An ask the owner edits before deciding cannot use
its decision time and is credited up to the last sweep that saw it still open: the
sweep's reconcile records the open wait on every pass (H464d), so that credit is the
same whether or not anyone opened the HUD — the report routes only read it. This does not create an approval timeout or
extend the absolute goal deadline. Budget diagnostics separately report raw wall
time and excluded human-wait time. Running out of interrupts
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

### `security.data_training_ack` (H513 unattended provider consent)

**Default: empty.** This route-only setting is changed through Security Posture
or admin `POST /api/security/data-handling/ack`, using the current opaque `scope`
returned by posture. Generic settings writes, imports and reset undo cannot grant
this permission. A successful consent audit precedes a durable grant.

**What acknowledgment changes:** routed internal work may use a configured provider
whose effective policy is `unknown` or `trains-on-inputs`. Owner-started builder
and workflow work still count as internal. Interactive use continues to warn;
acknowledged unattended use also continues to warn. Consent is scoped to the actual
provider configuration, credentials and effective policy. A changed configuration
requires a fresh acknowledgment; an ambiguous provider/account cannot be granted
from a stale or incomplete posture row.

**Cost:** prompts can leave the machine under the provider's terms and may be used
for training. Existing profile policy labels are declarations, not a verification
of the owner's account contract. No provider calls are made by inspecting posture.
Local routes do not acquire a cloud fallback through this setting.

**Rollback:** revoke in Security Posture. Fresh dispatch checks block unacknowledged
internal requests, including subsequent tool-loop requests. Revocation cannot
recall bytes already sent. Independent direct backend clients are outside this
router boundary and retain their own controls; this is not universal cloud egress
protection. See `agents/core/llm/data_handling.py` and the reported posture coverage.

### `security.data_training_role_ack` (H513 independent role consent)

**Default: empty.** Admin Security Posture controls acknowledge one exact configured
role: approval judge, Telegram image descriptions or camera descriptions. The
finite `target` is added to the same audited acknowledgment API; provider grants
and grants for another role never substitute for it. Generic settings/import/reset
cannot create this permission. Unknown or training policies require acknowledgment;
known-local policies do not. Warnings remain visible after a grant.

**Risk and scope:** granting does not enable remote judging, remote image delivery,
camera capture, event descriptions or household consent. Telegram and camera native
VLM requests stay strictly on loopback. Custom camera endpoints remain unknown;
locality does not establish the server's data practices. Posture is pure metadata,
not a probe or verification of provider terms. Unconfigured/disabled camera targets
are omitted; camera provisioning remains separate H31 work.

**Revocation:** the role is checked before actual sends/retries and through awaited
cleanup. The original household camera privacy lease is checked independently.
Camera configuration uses the effective orchestrator settings view; changes become
visible after its settings refresh, and an old cached runtime refuses changed
configuration until rebuilt. Role revocation reads its durable store at dispatch.
Neither mechanism recalls data already sent. Pure injected library adapters are
not claimed to be universally mediated. See posture's current coverage statement.

### `JARVIS_ROLE_VISION_EMPTY_RETRIES`

**Default: 0.** Accepts only unset/ASCII-space blank/0 or 1; invalid, overlong,
control-character and non-ASCII values refuse. At 1, an image-bearing call inside
the governed native vision scope may send the same prepared image/question to the
same model once more after a structurally valid empty successful response. This
covers the composer (including acknowledged remote use), local describe, screen
reflex, unattended media reader and camera descriptions. Unguarded/direct backend
calls, ordinary text-only calls and injected library adapters gain no recovery.

Enabled policy enters the frozen destination binding and unattended role scope.
Changing it invalidates old composer destination confirmations and unknown/training
role grants. Status exposes the extra call budget before the composer sends images;
local panels and role notes retain the disclosure alongside privacy warnings.
The existing remote acknowledgment still applies to the exact displayed binding.
Default zero preserves legacy bindings and public/result shapes.

The enabled path permits at most two native sends under one 180-second generation
deadline, with the same model, prepared content, token cap and temperature. Existing
shorter caller deadlines and cleanup checks remain authoritative. Each request gets
fresh policy/consent checks, exact prepared-body validation and a one-send limit;
the response closes before another request. Clients retain their existing owners.
Responses are streamed with a 512,000-byte cap. Only one explicit stopped choice
with blank/null content and no error/tool/refusal/meaningful reasoning output can
trigger recovery. Malformed, blocked, truncated, oversized or failed responses,
cancellation and content that merely becomes empty after thinking removal cannot.
No provider switch, credential change, source download or transport retry is added.
The setting is not proof of live model compatibility or broader Hermes parity.

### `JARVIS_ROLE_<NAME>_PROVIDER` · `_MODEL` · `_BASE_URL` (H277 model roles)

**Default: unset** — every role behaves exactly as before. `agents/core/llm/model_roles.py`
is a frozen table of five roles; the new names win when set, the old ones are fallbacks:

| Role | New names | Fallback | Providers | Read by |
|---|---|---|---|---|
| `main` | none (`JARVIS_ROLE_MAIN_*` is **ignored**, the doctor says so) | settings `llm.*` | not env-selectable: the main model is chosen on the H378-guarded settings surfaces | the router |
| `deep` | `JARVIS_ROLE_DEEP_MODEL` | `JARVIS_DEEP_MODEL`, then `deepseek-r1-distill-qwen-32b` | none (the router's local backend; `_PROVIDER`/`_BASE_URL` ignored) | the deep slot |
| `vision` | `JARVIS_ROLE_VISION_PROVIDER` / `_MODEL` / `_BASE_URL` | legacy `JARVIS_VLM_*` for LM Studio/custom; none for OpenRouter/DeepInfra | `lm-studio` (= backend `lmstudio`), `openai-compatible` (= `custom`), explicit `openrouter` or `deepinfra` | `resolve_vlm_config`; OpenRouter/DeepInfra composer/native backend; other consumers keep their local-only guards |
| `video` | `JARVIS_ROLE_VIDEO_PROVIDER` / `_MODEL` / `_BASE_URL` | resolved vision route when video provider/base are unset | `lm-studio`, `openai-compatible`, `gemini` | opt-in, owner-approved `video_analyze` ToolRPC |
| `approval_judge` | `JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER` / `_MODEL` / `_BASE_URL` | none | `lm-studio` (default), `ollama`, `openai-compatible` | `autonomy/approval_judge.py` |

A provider value is a ProviderProfile id: an unknown one refuses `role_provider_unknown`
(vision: `VLMNotConfigured("role_provider_unknown")`), a real one the role cannot speak to
(`anthropic` for vision) refuses `role_provider_unsupported`. **Keys never follow an
address they were not issued for.** `JARVIS_VLM_KEY` works exactly as before for
`JARVIS_VLM_URL` (or LM Studio's default); a `JARVIS_ROLE_VISION_BASE_URL` receives it only
when its scheme, host and port equal that address's, and otherwise only the dedicated
`JARVIS_ROLE_VISION_KEY` (optional; ignored without a role base URL). The judge's only
dedicated credential is `JARVIS_ROLE_APPROVAL_JUDGE_KEY` (optional): with it set, that key
and no other goes to the judge's address; without it, an `lm-studio` / `ollama` judge gets
no key, and an `openai-compatible` judge gets `OPENAI_API_KEY` only when its base URL has
the scheme, host and port of `OPENAI_BASE_URL` (else of `https://api.openai.com/v1`).
Base URLs: vision keeps the VLM `/v1` convention (LM Studio default
`http://localhost:1234/v1`, never `JARVIS_LM_STUDIO_URL`); the judge and explicit video routes use the
provider profile's address (`JARVIS_LM_STUDIO_URL` / `JARVIS_OLLAMA_URL` / `OPENAI_BASE_URL`,
else `http://localhost:1234` / `http://localhost:11434` / `https://api.openai.com/v1`).
Explicit Gemini video defaults to `https://generativelanguage.googleapis.com/v1beta`;
this video-only default does not change the chat backend or vision role.
`python scripts/doctor.py` lists every role (row `model_roles`) and warns on a bad
provider id, a shadowed legacy name (compared exactly; only the provider selector ignores
case) or an ignored variable. Its vision line is `resolve_vlm_config`'s own verdict: a
setup every vision consumer refuses (`vlm_model_unset`, `vlm_url_unset`,
`vlm_preset_unknown`, …) shows `off (<reason>)` and warns, and its local/remote label is
`VLMConfig.is_local` (a loopback custom VLM is local).
Local addresses in doctor/judge status expose only the loopback HTTP origin;
userinfo, path, query and fragment are never displayed. The roles API omits URLs entirely.

**Explicit OpenRouter vision** uses `JARVIS_ROLE_VISION_PROVIDER=openrouter` and a
required `JARVIS_ROLE_VISION_MODEL`. It defaults to `https://openrouter.ai/api/v1`.
The dedicated `JARVIS_ROLE_VISION_KEY` takes precedence, including at that default;
otherwise `OPENROUTER_API_KEY` is used only on the canonical HTTPS origin (default
port 443). Another `JARVIS_ROLE_VISION_BASE_URL` requires a dedicated role key.
Remote HTTP, URL userinfo/query/fragment, malformed models/keys and missing keys
refuse. Legacy VLM variables and `OPENROUTER_BASE_URL` do not configure this route.

The composer discloses the selected model, destination and effective data policy.
It sends all six validated live `llm.openrouter_*` routing controls; an unreadable
or malformed setting refuses instead of dropping a restriction. Those controls
are included in the consent binding and checked at the final HTTP hook, even with
empty recovery disabled. Changed settings/keys/models require a fresh preview.
Status discloses any `selection_requirements` for the chosen route. The HUD offers
separate training and expensive-model confirmations, initially unchecked, for
this image draft. CLI image turns require `--acknowledge-training` and/or
`--confirm-expensive` when requested, in addition to `--remote-vision URL` for a
remote destination. The POST flags are strict booleans and default to false;
remote acknowledgement alone cannot clear them. The exact guard findings, prices
and threshold participate in the destination binding and physical-send checks.
Required training consent must reach the audit before any model client is made;
cost confirmation keeps the existing best-effort audit. These confirmations grant
no reusable provider or unattended-role permission. In particular, `:free` models
and `data_collection=allow` do not silently bypass training guards.
The inherited video route reports
`video_vision_provider_unsupported`; signed OpenRouter video and automatic provider
discovery remain separate unfinished increments.

**Nous account authentication** is a provider-discovery prerequisite, available via
`nerva auth nous login|status|logout --profile NAME`. Set a registered public OAuth
client ID in `JARVIS_NOUS_CLIENT_ID` on the hub; this build does not assume that a
Nerva registration exists or reuse the Hermes application's identity. Optional
`JARVIS_NOUS_PORTAL_URL` and `JARVIS_NOUS_INFERENCE_BASE_URL` are explicit operator
overrides. Account data stays encrypted under the Nerva data root. All four
`/api/oauth/nous/*` routes require admin authorization; status makes no provider
request, and logout removes only the selected local profile. Login alone does not
configure vision or main-chat routing. See [Nous account setup](nous-auth.md).

**Explicit DeepInfra vision** uses `JARVIS_ROLE_VISION_PROVIDER=deepinfra`.
`JARVIS_ROLE_VISION_MODEL` pins a model and bypasses metadata discovery. Without
that pin, composer status selects the first served chat/vision model from the
credential-scoped catalog, preserving catalog order and Hermes's legacy ID filter
for entries without surface tags. No catalog selection means unavailable.
The base is the role base, then `DEEPINFRA_BASE_URL`, then
`https://api.deepinfra.com/v1/openai`. The dedicated role key wins; ambient
`DEEPINFRA_API_KEY` is accepted only on the canonical HTTPS origin/default port443.
A custom origin requires a dedicated role key; legacy VLM variables are ignored.

For this provider, `GET /api/vlm/composer/status` may send an authenticated metadata
request to `/models?filter=true&sort_by=hermes`. It sends no prompt or image;
`reachable=null` still means inference connectivity is untested. Positive model
selections persist in a bounded process-local cache; failures retry after60 seconds.
`refresh_catalog=true`, used by the HUD's Refresh vision destination button,
refreshes metadata and revokes the old selection on failure. Explicit models bypass
catalog refresh. Catalog requests use a direct transport, no redirects, a five-second
deadline and a2 MiB response limit. A later image POST never discovers another
model: it requires the reviewed selection and independent remote/selection
confirmations. Keys, models and physical-request changes invalidate old approval.
Data policy is unknown. Local-only consumers stay local; inherited signed video
refuses with `video_vision_provider_unsupported`. Automatic cross-provider discovery,
Nous authentication and main-chat DeepInfra routing remain unfinished.

**Video understanding** requires `JARVIS_VIDEO_ANALYSIS=1` and a valid resolved video
route. When both video provider and base URL are unset, a configured vision route
supplies its actual native endpoint; a nonblank, non-`auto` video model overrides its
model, otherwise video inherits the resolved vision model. An explicit video provider
or base URL needs its own model. When inheriting vision, an invalid configured vision route refuses instead
of silently selecting another destination. With no vision configuration, the existing
explicit video-model route remains available. It reads one file within `JARVIS_FILE_ROOTS` or one public HTTP(S) video
URL, then sends a `video_url` message to LM Studio/OpenAI-compatible, or native
`contents`/`inline_data` to an explicit Gemini route. The configured model must understand
that native payload; listing an adapter does not prove the installed model supports
video. There is no frame extraction, Ollama video adapter,
inbound attachment ingestion, or video generation in this consumer.

The tool is offered through the `video` job toolset when enabled, and every execution
requires its own Decision Inbox approval and signed task mediation. Configure
`JARVIS_TASK_MEDIATION=enforce`; other mediation modes refuse video intake and execution.
The source, question, role configuration
and credentials are bound to that approval. `JARVIS_ROLE_VIDEO_KEY` wins when set;
otherwise video may inherit the vision adapter's guarded effective key only for the
same provider and normalized complete native request URL. Same-host/different-path
destinations cannot borrow that key; no raw global provider key is read. Changing
inherited configuration invalidates the approval before network dispatch and withholds
late results. Explicit Gemini video uses only `JARVIS_ROLE_VIDEO_KEY` as
`x-goog-api-key`; it never reads `GEMINI_API_KEY` or inherits a vision key/configuration.
Its primary key, like fallback keys, is limited to 4096 printable ASCII characters.
Gemini models accept an optional `models/` prefix followed by one ASCII model slug
using letters, digits, dots, underscores and hyphens; the slug starts alphanumerically.
Recomputing the approval class can still read the scoped local file to
verify its content hash. Local files use bounded,
descriptor-scoped reads on POSIX systems. Public URL reads validate DNS and redirects,
refuse embedded credentials, and cap the download at 37,500,000 bytes (50,000,000
base64 characters). Private-network URL sources are refused.

Container MIME declarations follow the extension: MP4 `video/mp4`, WebM `video/webm`,
MOV `video/quicktime`, AVI `video/avi`, MKV `video/x-matroska`, MPEG/MPG `video/mpeg`.
This is a declaration, not media decoding or verification. Gemini refuses Matroska;
if any configured candidate cannot accept the declared MIME, intake refuses the chain.
Native Gemini JSON must be **strictly below 20,000,000 UTF-8 bytes**, including prompt
and base64. This conservative local implementation bound is checked before any model
client or lane send and again on actual request bytes. Larger upload/lifecycle support
remains open. A Gemini success must contain one unblocked STOP candidate and nonempty
visible text; thought parts are omitted. Blocked, malformed or empty success neither
discloses an answer nor authorizes fallback.

Remote destinations require HTTPS, `JARVIS_ROLE_VIDEO_ALLOW_REMOTE=1`, per-call
`allow_remote=true`, and an independent, configuration-bound **Video analysis**
acknowledgment in Security Posture. Strict-local mode, `llm.cloud_fallback=never`,
and local-only agents still forbid remote model use; safe mode refuses this tool.
Both feature flags default to off. This control
does not turn on a model or authorize a paid service. Provider/model behavior still
requires a separate live acceptance run.

An optional `JARVIS_ROLE_VIDEO_FALLBACKS` JSON array configures up to four ordered
fallbacks. Every record must contain exactly `provider`, `model` and `base_url`;
the native `lm-studio`, `openai-compatible` and `gemini` adapters are supported. The raw
array is capped at 8192 UTF-8 bytes; model names at 256 characters, URLs at 2048,
and fixed slot keys at 4096 printable ASCII characters. Blank/`auto` models,
extra fields, incompatible protocol hosts, URL credentials/query/fragment and
remote HTTP refuse the entire chain, including an invalid candidate that would
otherwise remain unused. LM Studio endpoints must be loopback.

Credentials come only from `JARVIS_ROLE_VIDEO_FALLBACK_1_KEY` through `_4_KEY`.
Empty keys support keyless local/custom servers. Fallbacks never borrow primary,
vision or main-model credentials. Security Posture exposes independently scoped
**Video fallback 1–4** controls for configured candidates. Each remote destination
needs its own current acknowledgment as well as the existing remote and cost
permissions, even if the primary is local. Unconfigured slots remain hidden.
Adding, removing, reordering or changing a configured route invalidates the task
approval; changing its destination/model/key also invalidates that candidate's
consent. With an empty chain, the existing primary approval and consent format
remains unchanged. Configuration and consent do not establish provider entitlement.
Approval notices show origin-only destinations; long chains use compact model/origin
labels with a digest to fit the existing 200-character ToolRPC label limit. The
complete ordered identities remain bound to the signed approval.

By default the approved chain sends once per candidate and only advances after recognized
provider failures: authentication, payment/quota, rate limits, narrowly classified
model incompatibility, or owned transport timeout/connection failures. Body-based
classification reads bounded structured error fields; a generic 400/403/5xx,
malformed successful JSON or an empty answer does not select another provider.
Neither source failures nor kernel, consent, request-integrity or cancellation
failures permit fallback. SDK-specific credential/parameter recovery remains separate. Structurally valid
empty results have the independently approved consumer-retry option below.

`JARVIS_ROLE_VIDEO_TRANSIENT_RETRIES=1` permits **one additional primary attempt**
after an owned typed connection/remote-protocol failure or a bounded HTTP 408/5xx
response within each consumer call. It never transiently retries a fallback candidate or an ordinary timeout; timeout
retains the existing approved fallback behavior. After retry exhaustion, connection
failures may use that existing fallback, while generic HTTP 408/5xx refuses without
switching provider. Auth/payment/rate/model failures use the existing fallback
directly. Source, factory, hook, policy, consent, kernel, cancellation, cleanup,
oversized-response and malformed/blocked/empty-success failures never use this
transient retry. Valid empty results use only the separate option below.

The setting accepts only `0` or `1` (unset/blank means `0`); surrounding ASCII
spaces are normalized, controls/non-ASCII/overlong values refuse. Enabled policy is
bound into each task approval and displayed in its notice. Changing it invalidates
pending execution. Destination/model/key consent scopes stay unchanged, and zero
retains the existing approval class, notice and result format. An enabled call
reports failed attempts with a one-based `attempt` per route and, on success,
chosen-route/provider/model plus `chosen_attempt`, including single-route calls.
The retry reconstructs the body and client after cleanup and fresh authority checks,
without fetching the source URL again. No backoff or SDK retry is hidden underneath.

`JARVIS_ROLE_VIDEO_EMPTY_RETRIES=1` permits **one additional whole-chain call**
after a structurally valid successful response has no visible analysis. It uses
the same strict0/1 parser and is bound into the individual signed task approval;
changing the setting invalidates pending execution. The approval notice describes
both budgets when enabled. Default0 preserves existing class, notice and result
formats. Each new call starts at the primary, including after an empty fallback;
this does not advance to another fallback on an empty result.

The existing transient budget applies independently within each call, for at most
`2 * (route_count + primary_transient_budget)` native sends under the same180-second
total deadline. Source bytes and question are prepared once; clients and bodies
are fresh for each physical send. Full task/kernel/consent/route checks run before
send and after cleanup. A second empty response refuses. Exhausted provider chains
without valid empty output do not restart.

Compatible empty classification requires one explicit `stop` choice, a present
string/null content field, and no refusal/tool/function or meaningful reasoning
output. Gemini requires one unblocked `STOP` candidate with valid text parts and
no visible text. Malformed, missing/unknown finish, truncated or blocked responses
never qualify. Existing nonempty reply behavior is preserved. Enabled provenance
uses fixed `empty_output` failure category, `consumer_call` and per-route `attempt`;
success includes `chosen_call`, `chosen_attempt` and selected route/provider/model.
No provider body or credential enters that provenance. Image and other-adapter
recovery and wider upstream output normalization remain separate work.

One 180-second execution deadline includes source access, model attempts and
cleanup. Each model attempt has a 65-second ceiling and a 60-second native HTTPX
timeout; the source download retains its 35-second sub-limit. Model responses,
including error bodies, are capped at 512,000 bytes. Each client closes before the
next attempt or lane. Authority and the whole approved chain are rechecked at transitions,
physical sends and disclosure. The prepared video and question are reused without
fetching a URL source again; local-file checks can reread bytes to verify their
approved hash. Results expose fixed attempt categories and the successful model,
without failed provider bodies, destination paths or credentials.

**Shared local auxiliary models (H277).** Six optional model IDs select a model
on the router's existing local backend independently of the conversation model:

| Setting | Consumer | Fallback when unset or ASCII-space-only |
|---|---|---|
| `JARVIS_AUX_SESSION_TITLE_MODEL` | Session title generation | Active local model, then `qwen3:7b` |
| `JARVIS_AUX_QUERY_REWRITE_MODEL` | Recall query rewriting | Active local model, then `qwen3:7b` |
| `JARVIS_AUX_REVIEW_MODEL` | Background/on-demand conversation review | Active local model, then `google/gemma-4-31b-a4b` |
| `JARVIS_AUX_COMPRESSION_MODEL` | Context compression summary | Active local model, then `qwen3:7b` |
| `JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL` | Governed capability generation | Active local model, then `local` |
| `JARVIS_AUX_ACQUISITION_DRAFT_MODEL` | Grounded acquisition plan drafting | Active local model, then `local` |

Read when each operation starts; changing one does not change the active
conversation model or the other auxiliary tasks. Acquisition captures the backend
and model once for both JSON attempts; a new operation can see later changes. Values are opaque printable Unicode model IDs,
at most 256 raw characters; surrounding ASCII spaces are removed. Invalid types,
controls/nonprintable characters or oversized values refuse that auxiliary call without echoing
the value or silently selecting another model. These settings do not install a
model, choose a provider/URL/key, enable a feature, or add retries/cloud fallback.

The shared invocation retains the existing H513 policy checks at every attempt
and physical request. Titles, rewriting, review and compression reject job-model
pins. Acquisition retains its existing strict-local behavior independent of job
pins; these settings do not make a job pin select its acquisition model. Titles and rewriting keep their token
budgets and Qwen3 `/no_think` behavior; review keeps its bounded learning settings;
compression keeps streamed activity, inactivity/hold limits and offline digest
fallback. Acquisition keeps its two-attempt JSON bound, 2048/1024-token budgets and
temperature progression from 0.2 to 0; policy, configuration and provider failures
do not become JSON retries. There is no model-ID editor or auxiliary listing in the HUD/native app
for these environment settings. Broader auxiliary discovery/recovery remains open.

**The approval judge** (`JARVIS_ROLE_APPROVAL_JUDGE_MODEL` set): each tool call queued on
the action-approval queue is shown to that model **after** the card exists; its risk
score (0–100) and one-line reason appear on the card as a labelled *model opinion*, with
the judge's provider and model on the item and in the signed audit rows
(`action_approval.judged`, `action_approval.decided`). It never changes the status, never
approves, never blocks, and the request never waits for it. Skill-change cards are not
judged. `JARVIS_ROLE_APPROVAL_JUDGE_MODEL=active` reuses the model LM Studio / Ollama
already has loaded (no second model on the GPU; any other LM Studio model may load one
next to the main one).

Blocked Decision Inbox tasks use the same optional judge and shared capacity
(two concurrent calls, at most 32 queued/running opinions). Task annotations live
in separate SQLite tables, outside signed payloads and receipts; edits invalidate
the previous opinion. Notification delivery does not. The HUD keeps decisions
available while waiting and stops polling each card after `17 * timeout + 5`
seconds. An opinion is never an approval or an execution receipt.

`GET /api/llm/roles` requires user authentication and returns configuration only:
all base URLs are omitted and `reachable` is null. `/api/vlm/describe` refuses
non-loopback endpoints and selection-guard findings before creating a client,
including when its request selects a model override.

**Where the text goes.** For each queued approval, its tool name, agent, summary and
arguments (fenced as untrusted data, invisible characters stripped, capped only when the
whole snapshot exceeds 4000 characters, cutting the largest values first so every key
stays visible) are sent to the judge model.
When anything was cut the judge is told to score the call as high risk, the item and the
audit row carry `truncated: true`, and the card says "judged on a shortened copy".
Snapshots beyond the scan depth fail closed with `nesting_too_deep` and `truncated: true`;
a remote judge refuses them. If keys alone cannot fit the budget, no judgement is
dispatched. By default there is no judge. A local judge
(`lm-studio` / `ollama` on a loopback address) keeps the text on this machine (still an
`llm:<provider>` row in the egress ledger). Any other judge — a LAN LM Studio, or any
`openai-compatible` endpoint, even on loopback — sends that text to its base URL and runs
only with `JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE=1`; it is off under
`JARVIS_STRICT_LOCAL=1`, `llm.cloud_fallback=never`, and safe mode (safe mode turns off
even a local judge), and never sees an item from a local-policy agent or a tainted one: a
`tainted` mark on the action, its metadata or anywhere in its arguments, or a queue from a
turn with an untrusted origin (with a configured judge, the item is stored with
`tainted: true`). Queued and running cards expose runtime-only `judge_pending: true`;
dispatch re-checks live privacy policy and pending state after its slot wait, counting
revocations as `skipped_revoked`. A model the H378 guards flag (trains on inputs, or over
the cost line) keeps
the judge off (`judge_trains_on_inputs` / `judge_over_cost_line`): an env choice cannot
carry the acknowledgement the settings surfaces ask for. The judge's state and reason are
on `GET /api/actions/pending` as `judge`.

`JARVIS_ROLE_APPROVAL_JUDGE_TIMEOUT` (default `20` s) bounds each judgement: a value
below 1 s or unparsable falls back to 20 s, and a value above 60 s is 60 s. A timeout, an
error or a reply that is not exactly `{"risk", "why"}` stores nothing. At most 2 judge
calls run at once and at most 32 are in flight or waiting; past that a queued item is not
judged (its card says "not available"; `judge.skipped_busy` on `/api/actions/pending`
counts them). Injection flags are computed over every string in the call (keys and values,
at any depth), so a newline or tab between the words does not hide them.
**Cost/benefit:** a second opinion on each queued call for one small-model call each, at
the price of sending the call's text to the judge (local by default). **Revert:** unset
`JARVIS_ROLE_APPROVAL_JUDGE_MODEL`; stored opinions stay on their items.

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
| `JARVIS_VOICE_COMMANDS` (+ `JARVIS_VOICE_COMMAND_TIMEOUT_S`) | off · `30`s TTS / `120`s STT (cap 600) (`voice/local_providers.py`) | The owner's approved TTS/STT command providers may run (argv-only, private run dir, capped, kill-on-timeout) | An approved program runs as the hub's user; the settings stay ROUTE_ONLY, a set waits for a human, every spawn re-checks the program's identity, off in safe mode | Unset + restart: command voices fall back to the default voice, STT to Whisper or `[STT unavailable]` |
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
| `JARVIS_ROLE_<NAME>_*` (H277: `DEEP_MODEL`, `VISION_PROVIDER/_MODEL/_BASE_URL`, `VIDEO_*`, `APPROVAL_JUDGE_*`) | unset (`llm/model_roles.py`) | Picks a model per job; the `JARVIS_VLM_*` / `JARVIS_DEEP_MODEL` names stay the fallbacks. `APPROVAL_JUDGE_MODEL` turns on an advisory judge that scores queued tool-call approvals off the request path | The judge sees each queued call's arguments: local by default; remote only with `JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE=1`, never under strict-local / `cloud_fallback=never` / safe mode / H378 findings, never for local-policy agents or tainted items. It decides nothing | Unset: roles fall back to the legacy names; no judge |
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
