# Atlas E2.0 — identity, provenance and read-only snapshot

Parent slice: #781 · Epic: #760 · Program: #757

Status: candidate on `nerva2/e2-0-atlas-snapshot`; not accepted until an
independent integrator reviews the exact head and merges it.

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
  - explicit privacy scope on every query;
  - deletion/export lineage for each derived observation;
  - deterministic integrity hashes and replay fingerprints;
  - immutable snapshot values and fixed read-only authority flags.
- `tests/_nerva_e2_0_checks.py`
  - projection of existing facts without source mutation;
  - valid-time and known-time behavior;
  - private-scope denial;
  - contradiction and lineage preservation;
  - immutable values and no writable store handle;
  - deterministic replay, integrity, truncation and malformed-input failures.
- `tests/test_h14_1_bitemporal_kg.py`
  - invokes the bounded Atlas checks from an existing collected test so the
    repository's pinned test-count contract is not changed for bookkeeping.

## Legacy compatibility policy

Legacy `BiTemporalKG` rows do not currently carry canonical source, confidence
or privacy metadata. The adapter therefore labels them honestly:

- source: `legacy.bitemporal` plus the existing fact ID;
- confidence: `unknown` unless an explicit resolver supplies measured evidence;
- privacy: `private_local` unless an explicit resolver supplies a recognized
  privacy class.

Unknown privacy is never treated as public. Every query must supply one or more
allowed privacy classes, and non-matching observations are omitted with a
visible `denied_count`.

The adapter does not infer that two differently named subjects are the same
entity. It only gives the same normalized legacy subject a stable projected
entity ID. Cross-connector identity resolution remains future Atlas work.

## Temporal and contradiction semantics

- `temporal_axis="valid"` uses the existing `BiTemporalKG.as_of` view.
- `temporal_axis="known"` uses the existing `BiTemporalKG.known_as_of` view.
- invalidated observations retain `valid_to` and `invalidated_at`;
- contradictory historical rows remain separately addressable;
- snapshots are detached frozen values, so later source writes do not rewrite a
  previously returned snapshot.

## Security and authority boundary

Atlas E2.0 is read-only.

- no mutation endpoint is added;
- no database handle is returned to consumers;
- no privacy class is broadened implicitly;
- no probability, Reflection proposal or E12 belief becomes a fact;
- no action is authorized or executed;
- no task is marked complete;
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

Integrity hashes detect accidental or unauthorized modification of a projected
observation. They are evidence identifiers, not signatures and not a substitute
for access control or an audit log.

## Explicit exclusions

This slice does not provide:

- a new Atlas database or broad ontology;
- automatic connector identity merging;
- production Atlas HTTP/API exposure;
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
  tests/_nerva_e2_0_checks.py tests/test_h14_1_bitemporal_kg.py
```

Repository CI remains the integration evidence and must be green on the exact
reviewed head before merge.

## Migration and rollback

No data migration occurs. Existing `bitemporal_kg.json` content and the
`BiTemporalKG` API are unchanged.

The coherent rollback is:

1. delete `agents/core/memory/atlas_snapshot.py`;
2. delete `tests/_nerva_e2_0_checks.py`;
3. remove the helper import and invocation from
   `tests/test_h14_1_bitemporal_kg.py`;
4. remove the E2.0 candidate/accepted snapshot from
   `docs/nerva2/M1_DELIVERY.md` and this document.

Rollback must not delete or rewrite the existing bi-temporal store. Partial
rollback that leaves the test wiring or a misleading delivery claim is invalid.

## Residual risks and next package

The contract exposes honest defaults for legacy rows but does not create missing
source metadata. Query-time filtering is proven at the adapter seam, not yet at
a production API boundary. Deletion lineage is represented but no deletion
executor is added. Stable subject hashing is compatibility identity, not
cross-domain entity resolution.

After independent acceptance, #782 Episodes is unblocked. The next Atlas package
should exercise explicit identity/provenance adapters across three bounded real
domains, while preserving correction, privacy and deletion semantics.
