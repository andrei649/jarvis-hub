# Hermes full-contract closure — batch 02

Generated 2026-10-10 UTC. Goal: continue toward 697 accepted complete contracts,
from 127/697. Base and initial head: `2a2b966a6e3f0c38e046aad176831b637f3e619c`;
branch `codex/hermes-closure-02-20261010`. Local work only. No push, merge,
deployment, paid providers, or changes to personal runtime data.

## H689: one identity, separate profile state

Extract `paths.install_root(environ=None)` from the existing unprofiled root
selection. `data_root` still validates the profile and selects its sibling root.
The no-argument install identity belongs to the unprofiled root; explicit-root
identity calls keep their current meaning. Hub locks/PIDs, profile `.env`,
settings and credentials remain per data root. An invalid selected profile must
still fail closed rather than accidentally selecting the default runtime.

Under the shared identity lock, preserve a valid canonical ID. If no canonical
file exists, inspect only direct valid profile siblings for legacy IDs, without
following symlinks. Adopt one unambiguous valid legacy ID; mint only if there is
no legacy identity. Conflicting, malformed, symlinked or unreadable legacy state
returns None with a fixed actionable migration diagnostic. Never overwrite a
corrupt canonical file, silently pick the first profile, or create an ephemeral
fallback. Lock, atomic write, fsync and read-back remain mandatory. Cover the
Windows content-before-byte-lock rule without damaging readable holder PID
data; keep locking changes within the identity module and disclose native-host
verification limits.

Existing canonical identity wins over legacy profile files; old pinned links or
satellite credentials must be re-paired if they refer to another ID, never
accepted through an automatic foreign-ID alias. Retain legacy bytes for repair.
An activation record may adopt the canonical ID only when its prior valid ID is
proven to be this selected profile's legacy on-disk ID; retain that old identity
as historical metadata. A different copied/foreign valid ID must remain
unmodified on disk and be reported as migration-required rather than presented
as the current install. Missing IDs never create unscoped node capability tokens
or portable deeplinks. Use a typed unavailable exception and a fixed 503
response in the existing owner routes; refuse legacy unbound deeplink redemption
without approving a sender. No broad changes to other pairing modes.

One gpt-6-sol/high implementer owns `agents/core/paths.py`,
`agents/core/install_identity.py`, `agents/core/first_action.py`,
`agents/core/node_mesh.py`, `agents/core/channels/pairing.py`,
`agents/core/routers/mesh.py`, `agents/core/routers/pairing.py`,
`tests/test_h689_install_identity.py`, and a new
`tests/test_h689_shared_identity.py`. Existing related test expectations may be
extended only after notifying root of the specific required path. Do not edit
satellite authority rules: existing pinned-ID refusal is the desired migration
behavior, verified by a regression.

TDD: shared default/named-profile identity under all existing base selectors;
cross-process first-mint race; canonical preservation, sole-legacy adoption and
conflict/refusal/recovery; activation migration proof; no token/link or sender
approval when identity is missing; route 503 behavior; separate profile hub locks
and credentials; Windows lock content and PID compatibility. Use existing focused
identity, profile, activation, node, pairing and satellite regressions. All test
data is isolated and disposable; no real profile is migrated by this task.

## H413: a dedicated default title model

The title selector must not silently inherit an arbitrary large active chat
model. Use the repository's declared small local default (`DEFAULT_LOCAL_MODEL`,
currently qwen3:7b) for session titles when no task override is configured. Retain
the explicit owner `JARVIS_AUX_SESSION_TITLE_MODEL` override and existing strict-
local transport, validation and per-call read behavior. Owner-selected overrides
remain deliberate configuration; no model-name size guessing, forced download,
cloud fallback or new model-discovery feature is introduced. Other auxiliary
tasks keep their existing active-model fallback. If the dedicated model is
unavailable, keep the already-persisted instant title under the existing failure
path, without retrying against the large chat model.

The second gpt-6-sol/high implementer owns only
`agents/core/llm/auxiliary_text.py`, `tests/test_h277_local_auxiliary.py`, and
`tests/test_h413_session_titles.py`. TDD: a large active chat model must not receive
a default title call; explicit overrides still work and are reread; other tasks
retain their prior selectors; provider unavailability leaves the instant title,
with no cloud or active-model retry. Reuse the full two-stage/once-only/CAS title
and auxiliary test suites. Root adjudicates the final whole-contract verdict.

The H413 ownership extension is limited to session-title expected-model assertions
in `tests/test_h277_auxiliary_parameter_recovery.py` and
`tests/test_h513_auxiliary_integration.py`. H689 additionally owns the legacy
unbound-link expectations in `tests/test_pairing_secrets_at_rest.py`.

## H256: consent writes honor corrupt-store refusal

The read-only config review found that provider and role consent writers bypass
the full settings-store readability guard. Root reproduced the defect in a
temporary database: an unrelated row with invalid JSON in `opts` made the shared
integrity preflight refuse, while `data_handling.acknowledge` still persisted a
grant. No personal database or provider was used.

After freezing H689, its implementer may own only
`agents/core/llm/data_handling.py` and a new
`tests/test_h256_consent_writes.py` for a separate rollback unit. Reuse the
existing settings initialization/readability boundary before opening the consent
transaction, then validate readability again after `BEGIN IMMEDIATE` and before
audit or mutation. This closes the interval between preflight and acquiring the
write lock. Do not change consent scopes, audit requirements, grant/revoke
semantics, generic read fallbacks, or the other writers. Existing appearance and
composer writers already invoke the initialization/readability guard; no broad
database refactor is needed for this reproduced defect.

TDD covers provider and role grant/revoke, unrelated invalid value/opts JSON,
unchanged consent rows and no audit/listener on refusal, and corruption committed
after initial preflight but before the write transaction. A repaired store must
allow the same explicit action again. Run config recovery and the existing
provider/role-consent suites. Native fresh-start refusal is deliberate: H256's
own Nerva rationale explicitly requires refusing startup when no last-good
policy exists rather than silently restoring weaker defaults. Retain that
behavior; this is not an unresolved owner decision.

## Integration

Root owns scope, interfaces, plans, evidence and delivery docs. Optional
gpt-6-luna/medium investigation is read-only. Maximum four active agents,
including root; no subdelegation. One writer per path. After declaring source
frozen, implementers must stop edits and notify root before any further mutation.
The two implementation units get independent review and separate rollback
commits. Do not refresh unrelated stale pins. Run focused tests during each unit,
then one serial integrated backend milestone after stable source/evidence.

Rollback restores each implementation unit and its reviewed evidence together.
No personal state or external authority is changed during development. The
implementation and focused review are complete; current verification and next
action are recorded below.

## Integrated candidate

Candidate head: `293536f5` (2026-10-10 UTC), on the branch/base above; production
source is unchanged from the integrated run at `94e69d32`.
Changed paths include the three implementation units, their focused tests,
assessment, generated status, identity/auxiliary documentation and client parity
notes. Metadata checks pass; this documentation commit saves the local evidence.
Next action: start the isolated batch-03 branch. Do not publish.

H413 is independently reversible in `a673b11e`. Red-first regressions proved
that a large active chat model was selected and read. The nine-module implementer
selection passes 399 cases; root's four-module independent selection passes 250.
Both use simulated generation/HTTP, not a downloaded or queried local model.

H689 is independently reversible in `828b9242`. Fourteen initial red cases
covered shared-root identity, conservative migration and missing-ID grants.
Root and independent review also caught Windows truncation/append-mode PID
problems and symlinked activation proof; all were corrected before freezing.
Final implementer selection passes 199 cases; independent seven-module review
passes 169. Simulated Windows checks include existing lock byte, holder PID,
release/reacquisition and same inode; native Windows acceptance remains open as
a verification limit. See the [migration guide](../install-identity.md).

H256 is independently reversible in `94e69d32`. Root reproduced a durable grant
against an unrelated corrupt JSON row, then ten red-first regressions covered
provider/role grant/revoke, invalid value/opts and corruption between preflight
and the lock. Both implementer and independent five-module selections pass 95
cases. Fresh startup refusal is intentional under the frozen Nerva rationale;
no permissive-default fallback was added. Existing appearance/composer writers
already use the shared preflight; runtime YAML has no writer in this surface.

Root reconfirmed H671 and H679 against the frozen contracts and actual
continuation/compaction/provider paths. The combined eleven-module run passes
318 cases (111 clock/continuation, 207 reasoning). H298's four focused modules
pass; root checked threshold precedence, actual spill/paging gates, taint and
bounded output integration. Pinned file_read prevents recursive spill and its
repeated pages may exceed the nominal spill allowance; this is distinct from
the final request context budget. Retention/storage-failure limits remain
explicit. H296's 144 focused cases pass for generic hooks and refresh, but six
named producers and memory target narrowing are absent, so the verdict is
partial. Passing helper tests did not close that contract.

The assessment changes seven fully reviewed rows and two collateral pins:
H504's trust-anchor implementation/section are unchanged; only the title-model
row in its pinned FLAGS document changed. H153's production webhook behavior
is unchanged; its audit test excludes asynchronous guard telemetry using the
existing helper while requiring both expected webhook actions. All other stale
review hashes remain untouched. The frozen 697-row inventory and reopenings are
unchanged. Current local count is 133 equivalent, 233 partial, 56 missing and
275 needing review (19.1%, 564 unfinished). Of the equivalents, 25 have current
review records and 108 are inherited baseline claims, not 133 fresh full audits.
Main still carries 116/697; none of this batch is pushed.

Focused counts overlap and are not summed as a unique suite total. Ruff on each
implementation unit and whitespace checks pass. The integrated backend collection
contains 25,624 cases; frontend 2,177/mobile 359 counts are reused because their
source is unchanged. HTTP routes remain 622 and active agents 18. Full-suite and
fresh-app smoke outcomes are recorded below after execution.

The fresh-process HTTP smoke passed against the actual FastAPI app with temporary
home/key roots and loopback only. A corrupt canonical identity returned the fixed
503 `install_identity_unavailable` response from both node registration and
pairing-link creation, with no-cache headers and damaged bytes preserved. After
repairing that disposable canonical file, a separately started named profile
returned 200 from both routes, bound the canonical identity, and did not mint a
second profile identity. No personal profile, external sender or live provider
was used. Native Windows behavior remains covered by simulations only.

The single integrated backend run executed 25,624 cases in 393.55 seconds:
25,564 passed, 58 skipped, one expected failure and one failure. The failure was
`test_h153b_webhook_delivery.py::test_a_destination_change_is_audited`: it assumed
the last audit entry was the webhook change, while asynchronous guard telemetry
could append a successful authentication afterward. The production webhook
change audit is awaited; the test now uses the existing `_action_events` helper
and requires exactly create/update plus the destination fields. This is a test
ordering repair, not a product or additional absorption claim. The six-module
webhook/authentication rerun passed all 306 cases. The original full run is not described as
green, and was not repeated after this test-only repair.

Final metadata selection passes 86 tests. Both generated-status checkers and
`git diff --check` pass. The frozen ledger is byte-for-byte unchanged from the
batch base; exactly nine assessment review records changed (seven complete
source reviews and two bounded collateral updates). All other evidence pins
and scope reopenings are preserved. No external publication occurred.
