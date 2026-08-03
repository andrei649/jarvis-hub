# Atlas E2.0 — identity, provenance and read-only snapshot

Parent slice: #781 · Epic: #760 · Program: #757

## Delivery status

E2.0 is accepted. PR #794 was independently reviewed at exact head
`f01b13e354eb64504d7996cc4d87d4828ae74330` and squash-merged to `main` as
`f2901528e452586f9702c7df1678e72ca36ca2ee`.

The historical transition rule was: #782 becomes eligible when the exact
reviewed head lands on `main`. That condition is now satisfied; #782 is eligible
for a separate bounded E3.0 package. This sentence records the former gate and
must not be read as an active blocker.

## Outcome

E2.0 adds a typed compatibility layer over the existing `BiTemporalKG`. A
consumer can request a bounded valid-time or known-time snapshot and receive
immutable `nerva.observation.v1` values inside a deterministic
`nerva.atlas.snapshot.v1` result.

The source of truth remains `agents/core/memory/bitemporal.py`. This slice does
not add a replacement database or migrate existing data.

## Included artifacts

- `agents/core/memory/atlas_snapshot.py`
  - stable source, entity, observation and snapshot identifiers;
  - visible valid time and ingestion time;
  - explicit provenance and confidence state;
  - contradiction-preserving projection of historical facts;
  - requested privacy scope separated from a trusted access grant;
  - authorization before any source-store read or projection;
  - deletion/export lineage for each derived observation;
  - deterministic integrity hashes and replay fingerprints;
  - immutable snapshot values and fixed read-only authority flags;
  - fail-closed direct-construction validation for type, scope, integrity,
    duplicate identity, ordering and query consistency.
- `tests/_nerva_e2_0_checks.py`
  - projection of existing facts without source mutation;
  - valid-time and known-time behavior;
  - unauthorized-scope refusal before the source store is read;
  - authorized classification filtering without unauthorized-record counts;
  - contradiction and lineage preservation;
  - immutable values and no writable store handle;
  - deterministic replay, integrity, truncation and malformed-input failures;
  - direct-construction rejection of forged or inconsistent snapshots.
- `tests/test_h14_1_bitemporal_kg.py`
  - invokes the bounded Atlas checks from an existing collected test so the
    repository's pinned test-count contract is not changed for bookkeeping.
- `tests/_nerva_e1_1_checks.py`
  - keeps the accepted E1.1 M1 ledger guard aligned with the durable E2.0
    delivery-state wording and the coherent rollback contract.

## Legacy compatibility policy

Legacy `BiTemporalKG` rows do not currently carry canonical source, confidence
or privacy metadata. The adapter therefore labels them honestly:

- source: `legacy.bitemporal` plus the existing fact ID;
- confidence: `unknown` unless an explicit resolver supplies measured evidence;
- privacy: `private_local` unless an explicit resolver supplies a recognized
  privacy class.

Unknown privacy is never treated as public. Every query declares requested
privacy classes, but the query is not an authorization decision. A trusted
`AtlasAccessAuthorizer` must grant the principal an effective scope before the
source store is read. If the requested classes are not a subset of the trusted
grant, the read fails closed. Non-matching observations are omitted without
exposing how many unauthorized source records existed. Snapshot counts describe
only records eligible for the requested and granted scope.

The trusted authorizer is injected by the application composition root or
governed policy layer. Request handlers and downstream consumers may supply a
principal identifier and requested scope, but must not construct or select the
effective grant. This slice defines and tests that seam; it deliberately does
not add production Atlas authentication or an HTTP endpoint. The fixture
authorizer in tests is not a production policy implementation.

The adapter does not infer that two differently named subjects are the same
entity. Compatibility entity IDs are source-scoped: the same normalized subject
within the same declared source receives a stable ID, while a different source
receives a different ID until an explicit future identity-resolution contract
links them. This prevents implicit cross-connector merging.

Normalized source/subject hashes are deterministic and therefore
pseudonymous/linkable; they still require normal access, retention and deletion
controls.

## Temporal and contradiction semantics

- `temporal_axis="valid"` uses the existing `BiTemporalKG.as_of` view.
- `temporal_axis="known"` uses the existing `BiTemporalKG.known_as_of` view.
- invalidated observations retain `valid_to` and `invalidated_at`;
- contradictory historical rows remain separately addressable;
- snapshots are detached frozen values, so later source writes do not rewrite a
  previously returned snapshot.

The compatibility adapter does not repair pre-existing transaction-history
limitations inside `BiTemporalKG`; it preserves the current store's behavior and
makes the selected temporal axis explicit for later migration work.

## Security and authority boundary

Atlas E2.0 is read-only.

- requested privacy classes never grant access by themselves;
- the trusted grant is evaluated before the source store is read;
- no mutation endpoint is added;
- no database handle is returned to consumers;
- no privacy class is broadened implicitly;
- no unauthorized-record count is exposed in a filtered snapshot;
- forged observations, invalid hashes, duplicate IDs and out-of-scope values
  fail closed at snapshot construction;
- no probability, Reflection proposal or E12 belief becomes a fact;
- no action is authorized or executed;
- no task is marked complete;
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

Integrity hashes detect accidental or unauthorized modification of a projected
observation. They are evidence identifiers, not signatures and not a substitute
for access control, trusted grant issuance or an audit log.

## Explicit exclusions

This slice does not provide:

- a new Atlas database or broad ontology;
- automatic connector identity merging;
- production Atlas HTTP/API exposure or authentication;
- source writes, correction execution or deletion execution;
- derived-index deletion traversal beyond the declared lineage contract;
- three-domain live integration evidence;
- Episodes, Reflection, Howard or World Model behavior;
- any production routing or action-authority change.

## Verification

Focused verification:

```bash
pytest -q tests/test_h14_1_bitemporal_kg.py
ruff check agents/core/memory/atlas_snapshot.py \
  tests/_nerva_e2_0_checks.py tests/test_h14_1_bitemporal_kg.py \
  tests/_nerva_e1_1_checks.py
```

Repository CI was green on the accepted exact head. Future modifications must
again pass exact-head CI before merge.

## Migration and rollback

No data migration occurs. Existing `bitemporal_kg.json` content and the
`BiTemporalKG` API are unchanged.

The coherent rollback is:

1. delete `agents/core/memory/atlas_snapshot.py`;
2. delete `tests/_nerva_e2_0_checks.py`;
3. remove the helper import and invocation from
   `tests/test_h14_1_bitemporal_kg.py`;
4. restore the pre-E2.0 M1 assertions in `tests/_nerva_e1_1_checks.py` together
   with the pre-E2.0 `docs/nerva2/M1_DELIVERY.md` content;
5. remove this E2.0 contract document.

Rollback must not delete or rewrite the existing bi-temporal store. Partial rollback that leaves the test wiring or a misleading delivery claim is invalid.

## Residual risks and next package

The contract exposes honest defaults for legacy rows but does not create missing
source metadata. The authorizer seam is proven at library composition and is not
yet wired to a production identity/policy boundary. Deletion lineage is
represented but no deletion executor is added. Source-scoped subject hashing is
compatibility identity, not cross-domain entity resolution. Access-grant IDs are
audit references, not signatures.

The next coherent package is #782: typed Episode values plus deterministic
manual open/settle/merge/split operations, source-reference and deletion-lineage
tests, and rollback documentation. Learned boundary detection, Reflection,
production recall changes and action authority remain separate.
