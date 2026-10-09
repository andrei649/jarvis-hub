# H487 classification and live producer prerequisites

Goal: complete all 697 Hermes capabilities locally, including real reusable
session/always consent, follower decisions and revocation before effects.
Generated 2026-10-03; base/head `27bf6cb043a029bf2cee1e6c777a0ef38cc3263c`.
Continuation of [the consent design](h487-reusable-consent-design-2026-10-03.md).
Owner-directed autonomous local implementation uses at most two Sol High writers;
no external publication, activation or paid calls. No approval pause is needed.

## Verified constraints and chosen approach

ToolRPC's `_grouping_epoch` is random per registration. It correctly isolates
notification groups and detects in-process replacement but cannot identify an
always grant after restarting. Do not replace that epoch or make it public.
Introduce an additional, registrar-owned versioned consent contract. Only tools
whose server registration declares a bounded `consent_revision` may expose
stable consent provenance. Ordinary tools retain independent approvals. Changing
the declaration, advertised base schema, capability or callback implementation
changes its key; the original random epoch still checks live replacement.

A code fingerprint alone cannot prove mutable closure, external service or target
configuration. The registrar revision explicitly declares the semantic contract;
policy and target configuration must be separately bound and revalidated by the
future queue/dispatch consumer. This registration key is provenance, not consent
or authorization. Unknown/unreadable callback implementation refuses a key.
This boundary must not be advertised as an implemented always permission.

Pinned Hermes approval detection is a pure stdlib classifier except three leaf
imports. Port its complete detector and MIT notice into the autonomy module,
preserving command normalization and risk descriptions. Adapt ANSI stripping
locally, avoid imports of an installed Hermes runtime, and provide an explicit
resolved-home argument rather than reading private Hermes configuration. The
gateway lifecycle fallback is Hermes-specific; expose it as an explicit optional
trusted predicate and report it unavailable if absent. Nerva hardline, taint,
target and kernel floors remain independent. A detection result grants nothing.

## Fixed interfaces and single writers

Writer A owns `agents/core/autonomy/hermes_command_detection.py`,
`agents/core/autonomy/terminal_consent_categories.py`,
`tests/test_h487_terminal_consent_categories.py`, and an MIT notice in
`docs/hermes/licenses/hermes-command-detection-MIT.txt` only.
`terminal_consent_catalog() -> tuple[ConsentCategory, ...]` returns reviewed
static warning keys including parser-limit and execution-flag categories.
`terminal_consent_categories(command: str) -> tuple[ConsentCategory, ...] | None`
returns the pinned detector's first dangerous category (the same Hermes priority),
empty tuple for a benign command and None for malformed/unclassifiable input.
All returned categories must belong to the catalog. Parser-limit/unknown-content
findings are session-max; fixed detector categories are permanent-capable.
Keep the existing Nerva hardline gate authoritative; add no execution calls.

Writer B owns `agents/core/autonomy/consent_registration.py`,
`agents/core/autonomy/approval_grouping.py`, `agents/core/tool_rpc.py`, and
`tests/test_h487_consent_registration.py` only.
`trusted_registration_key(name: str, spec: dict) -> str | None` canonicalizes
the declared consent revision, tool name, static input schema, capability,
gated/trusted/output flags and fingerprints callbacks handler/preflight/classifier/
gated_intake/gated_review/schema_overrides. Fingerprint Python code recursively
without installation path or line-number noise, plus readable implementation
module source bytes. Callable instances include their Python __call__ code;
opaque/builtin/unreadable callbacks refuse. Bound mutable state is not a key;
the explicit registrar contract and separate target/policy scope cover it.
`register_tool(..., consent_revision: str | None = None)` validates declaration,
stores `_consent_registration_key`, and keeps the existing random grouping epoch.
`model_request_scope(..., registration_key=None, registration_key_is_live=None)`
captures it only from trusted server registration after the separate callback
`registration_key_is_live(candidate_key) -> bool` verifies the fresh descriptor.
The existing registration-is-live callback remains boolean and unchanged for
notification grouping. A new `model_consent_semantics(context, task)` returns the
existing verified model semantics plus `registration_key` only for an exact
live producer with a valid key; the old grouping semantics remain byte-compatible.
ToolRPC passes its stored key on the generic producer path. Specialized producer
wiring remains a coordinator integration task, not this writer's scope.

Coordinator owns `agents/core/autonomy_coordinator.py` and
`tests/test_h487_terminal_consent_provenance.py`: declare the actual terminal
registrar revision `nerva.terminal_run.v1`, pass its private stored key and a
fresh-descriptor/live-object verifier into specialized intake. Real coordinator
tests prove stable re-registration, private exact owner provenance at enqueue,
no provenance without verified owner origin, no permission transition or spawn,
and no private key in public task payload/model results. This does not replace
the still-required durable source capture and owner decision integration.

Coordinator also owns `agents/core/autonomy/consent_sources.py`, the localized
queue schema/private wrappers in `queue.py`, the enqueue hook in `worker.py`,
and the actual terminal provenance tests. Capture one signed private source
after the real governed task becomes BLOCKED, while the verified model producer
still lives. Bind queue namespace, durable id/birth, current immutable approval
snapshot, the exact existing chat origin/task association and server-supplied
policy plus producer semantics. Require the existing ready chat association to
belong to the producer's real turn; never reconstruct identity from task payload.
Capture failure leaves the ordinary durable ask intact. Private read requires
signature/purpose/version/namespace, pending task/snapshot, unchanged chat origin
association and no taint or canonical smart DENY. This provenance is not a B7
receipt or consent grant; no task status, owner attribution or execution changes.
Tests use actual coordinator/queue intake, reopen its DB with same signer, mutate
stored source/task/origin, and verify no replay to another row or raw enqueue.
Owner/dispatch must separately revalidate live policy/registration/target before
using any captured source. No new public projection or route exposes it.

## TDD, integration and continuing work

A: prove expected rm/git/chmod/SQL/network-execution category keys against pinned
Hermes, equivalent spelling variants, benign quoted prose, parser bounds,
content permanence, all returned keys in catalog and no runtime dependency.
Use explicit synthetic paths/environment overrides in tests, no personal config.
B: prove identical explicit registration is stable across two server instances;
schema/revision/callback changes invalidate it; undeclared/opaque/malformed state
refuses; only verified owner model provenance exports it; copied task/context,
expired scope and model-supplied authority cannot borrow it. Existing grouping
behavior stays unchanged. No new queue transitions or executor permissions.
Both writers demonstrate RED before implementation, run focused guards and Ruff,
then freeze owned files. Coordinator reviews and runs relevant ToolRPC/grouping
integration, rebuilds/checks Graft and records exact limitations.

Required next unit: persist signed producer/intent/policy/target/category evidence
at real enqueue; atomically apply owner session/always choices and matching
follower decisions, each with independent B7 proof; consume/revoke through a
monotonic anchor at actual dispatch. Then wire HTTP/HUD/Telegram and other accepted
producers and channels. An exact-request-only permission is not a replacement
for the accepted category semantics. H487 remains incomplete until these flows
work; no equivalent credit is granted for this prerequisite unit.
Rollback: revert these localized modules/registration additions; ordinary task,
chat and approval history is retained and existing approvals remain independent.
