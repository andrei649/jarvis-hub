# H513 approval-judge consent target

Status: coordinator-approved local design, 2026-09-27. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus preserved sprint changes.
Goal: independently acknowledge the approval judge's actual account/destination
and enforce fresh consent at its physical request boundary. Next action: settle
the descriptor interface below between the two writers, then implement with
RED/GREEN regressions. No publication, new providers or live/paid model calls.

## Separate authority and backward compatibility

Keep provider consent and its existing API behavior intact. Add protected
`security.data_training_role_ack`, default `{}`, accepting only an
`approval_judge` key with a 64-hex scope. A provider acknowledgment never grants
role consent, even for identical credentials. Add optional request field
`target: Literal["role:approval_judge"] | None`; absence/None retains the current
provider path. The server resolves the finite target and checks provider/scope.
Add the setting to existing route-only protection for generic settings/import/
reset paths. Use the existing required audit and transaction pattern, including
a fresh configuration check after audit and no grant on failed writes.

## Pure configured identity and actual wire identity

Runtime writer owns a frozen `JudgeDataTarget` descriptor and
`describe_data_target(router=None, *, env=None)` in approval_judge.py. Shared
fields: `target_id` (fixed `role:approval_judge`), `provider`, `model`, `mode`
(`active` or `dedicated`), `policy`, `note`, and private `binding` material with
`repr=False`. Resolve only supported configured roles; unavailable or malformed
configuration returns no grantable descriptor. Status never creates clients,
calls `_backend_for`, or probes models/network. Configuration may be described
while another H277 policy disables judging; acknowledging it cannot bypass that
policy. Public output excludes URLs, Authorization and other key material.

Binding includes role/mode/model, actual provider, full effective wire endpoint,
effective sent Authorization and provider policy declarations. Dedicated
compatible credentials come from `_key`; dedicated LM Studio/Ollama credentials
are in client headers; active mode uses the actual selected local adapter.
Share key resolution between construction and descriptor, including injected
environment behavior, rather than reading two inconsistent configurations.
Unsupported adapter/auth arrangements fail closed. Store writer derives a keyed
scope with explicit role-target domain separation; no unkeyed fallback.

## Runtime contract

Store writer exposes `authorize_role_target(router, descriptor, *, actual_use=True)`
and `role_target_scope(descriptor)` in data_handling.py. The descriptor's policy
is always evaluated as unattended work. Unknown/training policies require the
role-specific acknowledgment; local/no-training policies retain their existing
behavior. Warnings remain after acknowledgment. Scope/last-use projections remain
bounded and contain no secrets.

Runtime writer freezes a configured descriptor and selected backend for one
judgment. Its guard must compare the actual constructed adapter's endpoint and
effective auth to that descriptor, re-reading mutable actual adapter/client
fields for each physical request. It must also re-resolve current configuration,
status, agent policy and taint eligibility; any mismatch refuses the old call.
Call authorization before generation and inside `physical_request_scope` for
every physical request/retry. Do not change that shared guard's callback API.

AdvisoryJudgements additionally supplies a trusted context-local validity callback
around `judge.score`, preserving the existing two-argument score protocol. Capture
that callback in the native judge's request guard. It must re-read the pending
queue snapshot, require the same attached judge, and preserve original/current
eligibility. Existing task revision validation and final annotation CAS remain.
No scope spans ToolRPC or other unrelated model work. Existing fresh contexts,
slot limits, timeout, job-pin exclusion and all H277 remote opt-in/strict-local/
host/selection/taint rules stay effective. Policy refusal produces no opinion and
does not approve, reject, enqueue or execute an action.

## Status and interface

Posture adds optional `data_handling.targets` with finite target ID, label,
provider/model/mode, policy, scope, warning and acknowledgment availability.
Unreadable role settings disable their controls independently of provider rows.
HUD renders the role separately and sends its exact target; provider buttons,
loading/error behavior and old requests remain compatible. No URL/key is shown.
The role-target control is not a control for enabling remote judging itself.

## Ownership, tests and rollback

Runtime writer: approval_judge.py, advisory_judgements.py, a new judge policy test
module and explicitly coordinated H277 fixtures. Store/UI writer:
data_handling.py, settings_db.py, routers/security.py, DataHandling HUD component,
new target-store/API tests and existing posture-panel tests. Coordinator owns
integration, records and scope. Settle descriptor names before source edits; a
writer must not edit the other's files. Test fakes declare truthful wire metadata;
no bypass or skipped assertion for custom factories.

Test wrong target/provider/scope, primary/role account isolation, key/header/
endpoint/model changes, active backend identity, zero-client posture reads,
revocation during slot wait and between physical requests, swallowed refusal,
closed child lifetimes, decided/edited items, audit/store failures, route-only
protection and unchanged provider API/UI behavior. Run focused H277/H513 and HUD
tests per implementation, then one integrated backend/frontend milestone.

Rollback removes role-target UI/API/runtime additions without changing queued
tasks, signatures, decisions or existing provider consent. The separate setting
does not grant authority outside the new consumer. H513 remains partial for VLM,
embedding and other independent clients; H277's other parity gaps remain open.

## Verified design delta: physical request identity

The zero-argument configuration callback remains compatible. An optional
`request_check` keyword on `physical_request_scope` validates the actual HTTP
request after the configuration check; when present, DELETE is validated too.
Native judge calls pin the provider POST path, full URL and effective Authorization,
reject cookies and follow-redirect mode, and mark each validated request to refuse
redirect/reused-request hops. Rebuilt native retries remain valid. The offline
307 regression failed before the fix. No other routed client claims this new
judge-specific wire identity check.
