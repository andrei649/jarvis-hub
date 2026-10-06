# Pinned Hermes runtime in Jarvis Hub

PR #1233 adds the complete upstream Hermes source as an owner-provisioned runtime,
with a private profile and its own upstream-PM-managed Python 3.14. Jarvis keeps
Python 3.12, authentication, operator controls and Action Kernel authority.
The source pin is `0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7` from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7).

## Setup and use

From a Jarvis checkout with its dependencies installed:

```bash
export JARVIS_HOME=/absolute/path/to/private/jarvis-data
python scripts/hermes_runtime.py install
python scripts/hermes_runtime.py status
```

Installation downloads the complete SHA-256-pinned archive and uses upstream
`pm.cli install` for the locked interpreter, Python extras and browser/device
tools. It does not install Hermes into Jarvis's environment. The install requires
network access and disk space for those tools. This is a substantial runtime,
not a few-line or ultralight dependency. An existing owner profile and provider
credentials are not imported. Configure providers in the private Hermes home
under `$JARVIS_HOME/hermes-runtime/home`, using upstream's documented configuration.

Set `JARVIS_HERMES_ENABLED=1` and `JARVIS_ACTION_KERNEL=1` in the Hub environment.
Start the Hub and open **Admin → Hermes Runtime**. The panel starts/stops the
runtime, creates/lists sessions, submits JSON arguments to pinned RPC methods,
streams events, and answers interactive server requests. HTTP and WebSocket
access require the Hub's admin identity. Safe mode disables this runtime.

`prepare` downloads and verifies source only. `install` also provisions the
environment and atomically writes a private `runtime.json`. No HTTP endpoint
accepts a source path, executable, upstream URL, shell command for launching, or
an imported profile. The packaged Hub includes the pin, catalog, license notice
and worker bridge files; upstream dependencies remain in the owner's data root.
Provisioning currently runs from the checkout CLI, rather than the frozen Hub.

## Protocol and authorization

The catalog includes every pinned OpenRPC method: **251 client methods, 13
server requests and 75 notification types**. An exhaustive classification file
matches that catalog; new/unclassified methods fail closed. At this milestone,
85 read methods have tier 0, 15 session/prompt operations have tier 2, and the
remaining 151 methods retain a tier-3 approval floor. This is a single-owner
operator surface: all authenticated administrators control the same private
Hermes installation. It does not claim multi-user session isolation.

The worker runs Hermes's headless server and wraps its registered RPC handlers
and actual tool/connector dispatch boundaries. Jarvis asks the enabled, live
Kernel before execution. A DENY, QUEUE, unavailable broker, stale generation,
unclassified target or replayed bridge nonce never executes the guarded call.
The classification is server-owned; RPC/tool arguments cannot lower its tier.
Kernel audit payloads include owner, session identifier, target, arguments and
runtime generation. Native Hermes policy and hooks still run inside that gate.

The broker credential is private and removed from the worker environment after
bootstrap. Server-request responses must match a pending request and generation
and are consumed once. Lost RPC replies produce an unknown-outcome error; the
adapter never automatically repeats an accepted mutation. A new connection can
read session history/events or explicitly issue a new request.

The worker accepts only private `/api/ws` and authenticated readiness. Its REST,
PTY, original SPA and plugin HTTP routes are refused: they have separate effect
paths requiring further mediation. `hermes serve` and `hermes dashboard` are
different products surfaces; this integration uses the headless protocol and the
Jarvis HUD. Desktop/device clients and optional integrations still require their
own dependencies, configuration and capability adapters.

## Availability and remaining work

The complete engine is provisioned; catalog coverage does not prove executable
equivalence for every feature. Terminal, arbitrary code, plugin/connector writes,
payments, device effects, delegation and other unverified operations remain at
an approval floor. A Kernel QUEUE is reported as pending/refused; this milestone
does **not** manufacture an approved task or replay an operation from an approval
card. Durable, action-bound TaskQueue execution for these effects, followed by
live/offline probes of each family, remains necessary for full governed use.

All **697** Hermes parity contracts remain in scope in the existing inventory.
Adding an upstream runtime does not increase the native-equivalence count or
close unproved rows. Runtime-backed availability and native Jarvis equivalence
must be tracked separately. No provider-cost or real device probe is implicit
in setup or the tests.

## Verification and rollback

The focused suite covers source/archive/executable substitution, private
environment, readiness redirects, failed startup cleanup, replay/generation
checks, unknown targets, Kernel refusal, RPC disconnect/no replay, interactive
responses, authenticated HTTP/WS, concurrent server replies and HUD states.
`tests/test_hermes_runtime_live.py` is an opt-in test of the real pinned runtime
when `JARVIS_HERMES_SMOKE_ROOT` names an already provisioned test installation.

Stop the runtime in Admin, or stop the Hub, to revoke its broker generation and
terminate its owned process group. Disable `JARVIS_HERMES_ENABLED` to remove the
runtime from use while retaining private session data. Keep that profile out of
Git and backups intended for public sharing. The MIT attribution is retained
in `runtime/hermes/NOTICE.md`; upstream's original LICENSE remains in the verified
complete source archive.
