# FLAGS.md — action-posture flags: know what flipping costs

Three environment flags change what Nerva may do without asking you. All ship
**default-off** (`env_flag` returns False unless explicitly set,
`agents/core/env_config.py:78`). This is what each one actually buys you — and
what it costs. Verified against code at `75e92811`.

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

## Decision table

| Flag | Default | Effect ON | Cost / risk | Revert story |
|---|---|---|---|---|
| `JARVIS_ACTION_KERNEL` | off (`kernel/flags.py:14`) | Broker GRANTs enqueue as `act` (auto-run) instead of inbox-blocked; DENY blocks early | Autonomous execution of reversible actions; money/taint/owner floors remain | Unset + restart: hooks no-op structurally (`http_client.py:48`), tasks return to ask-floor |
| `JARVIS_UNIFIED_ACTION_API` | off (`capability_actions.py:17`) | Arms house/media/desktop facade; without it those routes refuse forever | Real-world side effects (lights, playback, desktop input) on GRANT | Unset + restart: `perform()` returns `disabled` (`capability_actions.py:129`) |
| `JARVIS_WEBHOOK_CHANNELS` | `{}` (`web.py:423`) | Wires configured governed channels (WhatsApp/Signal/Matrix/Teams/Google Chat) | New inbound attack surface; Signal needs external daemon; verify signatures at host | Remove key/kinds + restart: nothing registered; unknown kinds warn-and-skip (`webhook_channels.py:290`) |
| `JARVIS_TERMINAL_TARGETS` | off (checked in the `terminal_run` tool handler) | Arms the gated `terminal_run` ToolRPC tool: post-approval shell commands on named targets through the audit-chained policy plane, docker transport only (`environments/execution.py`) | Approved commands actually execute in the containment sandbox; local/ssh backends still refuse (`*_transport_not_implemented`) | Unset + restart: the tool refuses `terminal_targets_disabled`; policy plane and audit chain stay inert |

Kernel flag alone ≠ smart home. Both kernel + unified flags = facades live.
Webhook channels cost no dependency, only configuration discipline.
