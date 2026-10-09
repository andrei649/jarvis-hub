# H099 ntfy inbound integration

Generated: 2026-10-05. Goal: functional parity with all original 697 pinned
Hermes capabilities, continuing the local PR #1207 handoff. This is the H099
implementation unit, not a reduction of the full goal.
Base/head: `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`; existing dirty work preserved.
Reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`, MIT,
`plugins/platforms/ntfy/adapter.py` (stream, identity, dedup, reconnect, echo).

## Requirements and selected design

- Keep explicit owner URL/topic configuration and existing outbound notifications.
  Enable receiving only with `NTFY_INBOUND=1`; no implicit public server or live activation.
- Adapt Hermes' persistent `/json?poll=false` stream, 90 second read timeout,
  reconnect delays 2/5/10/30/60 seconds with reset after 60 healthy seconds,
  bounded 1000-message/300-second dedup and outbound echo tag. Cancel and await
  the listener on stop. Reject authentication/topic errors without retrying forever.
- Ignore malformed/oversized events; authorize the configured topic only, never
  a publisher title, sender, pairing code or different event topic. Use the one
  boot gateway and SenderPairing store. An absent gate cannot enable receiving.
- Persist received turns in the existing bounded Inbox, preserve inbound taint,
  and queue the exact stored turn's reply via `channel.reply`. Never POST an
  automatic reply directly or treat the handler's return value as a transport.
- Bind replies to the subscribed topic and a non-secret per-adapter configuration
  fingerprint (includes a private random epoch). Refuse changed URL/topic/token,
  adapter replacement/restart, or revoked pairing before POST. Store no URL or
  token in reply metadata. Recheck the exact stored inbound message at execution.
- Both GET and POST use existing PluginHTTPClient DNS pinning, redirect refusal,
  manifest allowlist and egress/kernel hooks. A restricted ntfy manifest names
  only the explicitly configured server through existing dynamic-domain registration.
  The adapter's private HTTP subclass rechecks the live per-request binding after
  DNS/policy waits; each outbound chunk checks it again. Optional Hermes server
  alias, publish topic, Basic authentication and Markdown flags are retained.
- Share the exact one-shot kernel proposal with governed intake; do not weaken
  binding checks. Preserve the originating principal's inbound provenance.

Alternatives considered: a separate ntfy gateway would duplicate pairing and
reply authority; importing Hermes' entire platform framework would add unrelated
dependencies. Adapt its small httpx algorithm into Nerva's current contracts.

## Owned paths, tests and rollback

Localized changes: `agents/core/channels/ntfy.py`, `channels/gateway.py`,
`channels/manager.py`, `channel_inbox.py`, `channel_reply.py`, `plugin_gate.py`,
the ntfy boot block in `agents/web.py` and governed reply branches in
`agents/core/orchestrator.py`; new focused ntfy tests, `.env.example`'s ntfy block,
the existing Architecture ntfy entry and H099 records/docs only.
No changes to the kernel mismatch guard, existing unrelated dirty paths, dependencies,
remote PRs, credentials, global configuration, live workers or services.

Test first: synthetic httpx streams exercise subscription, auth, malformed frames,
topic spoofing, echo filtering, dedup TTL/cap, disconnect/reconnect/fatal status,
cancelled stop and shared pairing. Integration uses the actual coordinator,
kernel, queue, Inbox and manager: hold unknown topic; persist paired inbound;
approval then exactly one POST; rejection/revocation/drift sends nothing;
failed persistence cannot substitute an event-supplied inbox id; egress denial
and redirected credentials cannot dial an alternative target. Re-run affected
channel/kernel/boot suites after each implementation step, then full backend
at this milestone. Existing frontend evidence predates this source unit.

Rollback: disable `NTFY_INBOUND` to restore outbound-only behavior; remove only
this unit's hunks if reverting, preserving inherited local work. Old queued
inbound replies remain held/refused rather than being silently redirected.
Next action at creation: write and observe focused failing tests, then implement.

## Implementation checkpoint

Receiving, reconnect/dedup/echo, Basic auth/server alias/publish topic/Markdown,
shared Inbox and governed replies are implemented locally. Observed failing
regressions were corrected for delayed DNS revocation, late events on a changed
subscription, same-instance restart and UTF-8 byte limits. A new inbound start
rotates the private epoch; the listener stops on configuration drift instead of
migrating to a new server. No live service or worker was activated.

Verification so far: 82 focused stream/inbox/approval cases and 300 affected
channel/egress/pairing cases passed. The independent Sol High implementer added
11 real coordinator/signed worker integration cases; root reran them in the
canonical Python 3.12 environment. Full backend and final records remain to run.

## Full-suite integration correction

First frozen backend attempt: 23,628 cases, 23,584 passed, nine failed,
34 ordinary skips and one existing xfail, with no changes to 4,689 frozen inputs.
The failures exposed HTTPX INFO topic logging, the new plugin registry count,
external-write agent scope and three collateral evidence pins. HTTPX redaction is
scoped to transport calls, ntfy agents are limited to jarvis/veronica, and registry
tests now require ntfy's actual executable case. The readiness snapshot changes
only plugin:ntfy to wired; no escape set or VERIFIED state changes.
Additional owned integration paths: tests/test_h27_capability_verification.py,
tests/test_reality_harness.py, tests/_snapshots/capability_readiness.json.
Round-two focused regressions: 86 passed; full corrected rerun remains required.

## Verified local acceptance

Corrected frozen backend: 23,629 cases, 23,594 passed, 34 ordinary skips,
one existing xfail and zero failures/errors. Serial frontend: 1,912/1,912 passed.
All 4,689 frozen inputs matched after both suites. Ruff and scoped Bandit passed;
strict scans found zero findings across 16 owned source/test/doc inputs and the
sanitized proof derivatives. The upstream MIT notice is preserved in
`docs/hermes/licenses/hermes-ntfy-MIT.txt`.
H099's accepted code contract is complete; real owner server/phone delivery was
not activated or accepted. The original 697-row goal remains active. H063 is next.
