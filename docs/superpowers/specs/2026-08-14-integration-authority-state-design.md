# Integration Authority External State Design

**Goal:** Provide the candidate-independent, deterministic state-machine core that a separately
hosted GitHub App can use to record an independent acceptance for one exact repository / pull
request / base / head tuple.

**Base SHA:** `4b854d8cfde98615bccf47285b3709aa9970fdc3`

**Head SHA before implementation:** `4b854d8cfde98615bccf47285b3709aa9970fdc3`

**Planned changed paths:**

- `services/integration_authority/__init__.py`
- `services/integration_authority/state.py`
- `tests/test_integration_authority_state.py`
- `docs/superpowers/specs/2026-08-14-integration-authority-state-design.md`
- `docs/superpowers/plans/2026-08-14-integration-authority-state.md`

**Risk tier:** `R3` — this library is intended to become part of repository integration authority.
It is not authority merely because its source is present in this repository.

**Next action:** Execute Task 1 test-first; do not activate repository authority.

**Generated:** `2026-08-14T14:16:51+03:00`

## Scope

Task 1 implements only a deterministic library and hostile tests. The library consumes a policy
owned by the external service, exact live pull-request identity supplied by a future trusted
GitHub adapter, and bytes from a future external atomic store. It returns bounded decisions; it
does not call GitHub or the network.

The following remain owner-only and out of scope: App registration or installation, App keys,
webhook secrets, reviewer provisioning, external hosting/database provisioning, ruleset changes,
check publication, merge actions, and live sacrificial-PR testing. The library does not implement
the B2/#856 trusted-source verifier and makes no runtime or release-readiness claim.

## Authority boundary and threat model

Candidate-controlled repository files, pull-request title/body/labels, repository Actions, and
ordinary builder credentials are outside the trust boundary. A future external deployment must
pin a reviewed artifact digest and keep its store and credentials outside this repository and its
Actions secrets. Running a modified copy of this library locally cannot create repository trust.

The state machine accepts only an `AuthorityPolicy` provisioned by the external host. The policy
binds one numeric repository identity, one exact base ref, the repository owner identity, and a
non-empty allowlist of genuinely distinct reviewer identities. A review is rejected when its
reviewer is the pull-request author, last pusher, repository owner, or not allowlisted.

Every acceptance binds all of:

- numeric repository ID;
- positive pull-request number;
- exact base ref;
- lowercase 40-hex base SHA;
- lowercase 40-hex head SHA.

An acceptance for a previous head is never returned for a new tuple. Old records remain immutable
history and are logically stale. Candidate-editable prose and labels are absent from the API.

## Components and data flow

`services/integration_authority/state.py` provides immutable input/result data classes,
`AtomicStateStore`, `empty_state_bytes()`, and `AcceptanceStateMachine`.

`AtomicStateStore` has two operations: read the current bytes and atomically replace them only if
the bytes still equal the previously read version. A future database implementation must provide
that compare-and-swap transaction. Task 1 supplies no filesystem store and never silently creates
missing state.

`process_review()` performs this sequence:

1. Read external state. Missing, unavailable, or malformed state returns a non-accepting result.
2. Parse a closed JSON schema with duplicate-key rejection and canonical serialization.
3. Check whether the delivery ID was already processed. An identical replay returns the recorded
   result idempotently; conflicting reuse returns `delivery_conflict` without writing.
4. Validate the exact tuple, review state, and independent reviewer.
5. Append the delivery result and, only for a valid approval, one acceptance record.
6. Compare-and-swap the new state. A concurrent write returns `state_conflict`; it never returns
   acceptance until a retry observes committed state.

`verdict_for()` reads state and returns acceptance only for an exact valid tuple and configured
repository/base. It fails closed on missing, corrupt, or unavailable state.

The stored delivery fingerprint is an unkeyed replay/deduplication key, not a signature or source
authenticator. Trust comes only from the future external host, GitHub webhook authentication, and
the App-bound ruleset; candidate possession of the fingerprint algorithm grants nothing.

## Failure semantics

Operation and store failures are data: `AcceptanceResult(accepted=False, reason=...)`. Invalid
constructor inputs raise `ValueError` before state-machine execution; the future webhook adapter
must translate that boundary failure into a failing check without reflecting input. Untrusted
values are not reflected in operation reasons. Missing and corrupt state are different bounded
reasons, but both deny. Store exceptions and compare-and-swap conflicts deny. Rejected reviews are
recorded so an identical delivery is idempotent and a conflicting payload cannot reuse its
delivery ID.

`empty_state_bytes()` is an explicit provisioning primitive for the external owner/deployer. The
state machine never calls it automatically; deletion or replacement of the external state cannot
manufacture an acceptance.

## Test strategy

The hostile unit suite proves:

- an allowlisted distinct reviewer can accept one exact tuple;
- repository, PR, base ref, base SHA, and head SHA mismatches never inherit acceptance;
- author, last pusher, owner, unallowlisted reviewer, and non-approved review states are rejected;
- a head change makes the prior acceptance ineligible;
- identical delivery replay is idempotent, while conflicting reuse is rejected;
- missing, invalid JSON, duplicate-key, unsupported-schema, malformed-record, unavailable-store,
  and compare-and-swap-conflict cases fail closed.

Focused pytest, adjacent policy tests, Ruff format/check, the AI workflow policy checker, and
`git diff --check` are required before publication.

## Rollback and dependencies

Rollback deletes this isolated library, tests, design, and plan. No migrations, runtime product
state, repository settings, or credentials are touched. The only dependency is Python 3.12's
standard library. Path lease is `none`; live draft PR inspection found no overlap with the planned
paths.
