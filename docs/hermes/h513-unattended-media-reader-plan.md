# H513 unattended Telegram image descriptions

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus local sprint changes. Goal: bring the production inbound image reader under
fresh actual-dispatch data policy, without granting authority from a Telegram
sender or an inherited interactive request. Next action: implement owned slices,
review native transport behavior, then focused and serial milestone verification.

## Decisions and shared contract

Reuse the audited role-consent store with a closed set of two target IDs:
`role:approval_judge` (unchanged scopes) and `role:telegram_media_reader`.
The latter label is `Telegram image descriptions`, mode `dedicated`, and uses the
actual resolved VLM model, provider profile, policy, endpoint, effective auth and
binding from vision_policy.describe. LM Studio remains declared local; custom
compatible endpoints remain unknown even on loopback. Unknown/training unattended
use requires its own current audited scope. No provider/judge grant substitution,
no new remote eligibility, no inherited principal authority. Public status is pure
and contains no URL/auth/binding secrets. A missing/invalid configuration grants
nothing. Preserve existing judge scope hashes and grant/revoke semantics.

The owner API retains its existing schema except for the additional finite target
literal. Posture returns the existing targets array with optional media target.
Role persistence remains bounded, atomic and audit-first with exact live descriptor
re-resolution after audit; revoking one role does not alter another. Keep last-used
entries distinct and bounded. Generic settings cannot bypass the audited route.

Production readers created by from_env must re-resolve live configuration for each
read and physical send: an old object cannot silently use an old granted endpoint.
Refusal before download when policy is unavailable/denied; a bounded distinct
reason explains the owner configuration requirement without revealing secrets.
Native backend construction uses scoped auth and trust_env=False. Factor/reuse the
existing wire validator without fabricating a web principal; unattended request
scope checks exact model, URL/auth, policy/config, native route, revocation and
selection guards at entry, each physical request/retry and scope exit. Retain
remembered denial when adapters swallow errors. Preserve resource cleanup and
bounded untrusted-output fencing/sentinel handling. Existing injected generators
are explicit pure test/library seams, not newly claimed production governance.

## Ownership and verification

Writer A (Sol High): data_handling.py, vision_policy.py,
channels/media_reader.py, routers/security.py, settings_db.py (label only), new
focused tests and narrowly necessary existing fixtures; declare extra fixtures
before edits. No camera, unrelated VLM routes, UI, generated files or ledger edits.
RED/GREEN tests for role separation, grant/revoke/stale scope/audit race, malformed
store, config/key/policy drift, native transport overrides/proxy refusal, teardown,
pre-download refusal, output fencing and unchanged judge/composer contracts.

Writer B (Sol High): frontend/src/panels/data-handling.tsx and
frontend/src/test/governance-posture-panel.test.tsx only. Closed role label mapping;
render and grant/revoke the new role independently, preserve judge labels and
provider compatibility, explain local-only media and separate role consent. No
invented camera controls yet. Unknown IDs have no controls. Test both roles with
same provider, exact target/scope payloads, failed save, unreadable role store and
legacy provider-only response. Focused tests/typecheck, no generated build writes.

Coordinator owns integration/review, generated API/build, manual/mobile records,
Hermes evidence and status. Run full suites serially only after the coherent slice
passes focused review. No live model calls, publication, paid services, global
settings or unrelated modifications. Roll back only these incremental hunks.

## Remaining independent scope

Camera uses a separate global config and household consent; implement its own
role binding later, retaining custom/unknown unless genuine provider metadata is
configured. Standalone locator/legacy clients and mobile acceptance remain open.
This slice does not claim all H513 or Hermes parity complete.

Coordinator GO: shared interfaces above are released for parallel implementation.
