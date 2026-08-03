# Nerva Episodes E3.0 — typed records and deterministic manual boundaries

Status date: 2026-08-03  
Delivery state: **candidate until independent exact-head integration**  
Issue: #782 · Epic: #761 · Program: #757

## Dependency and authority boundary

E3.0 begins only after the minimum Atlas prerequisite was independently
accepted: #781 / PR #794 landed on `main` as
`f2901528e452586f9702c7df1678e72ca36ca2ee`.

Episodes owns experience-memory records. It does not own source facts, source
deletion, action authorization, execution, task completion or production
recall. Every `EpisodeRecord` and audit event has authority fixed to
`memory_record_only`, with `can_authorize=false`, `can_execute=false` and
`can_mark_complete=false`. Ultron / `nerva.action.v1` remains the sole
privileged-action authority.

## Included contract

`agents/core/memory/episodes.py` exposes the bounded facade over immutable values in
`agents/core/memory/_episode_values.py` and deterministic manual operations in
`agents/core/memory/_episode_operations.py` for:

- `EpisodeReference` — a content-free pointer to an Atlas observation, turn,
  event, decision, action or verified outcome;
- `EpisodeAssertion` — a direct or explicitly qualified inferred statement
  with evidence-reference IDs and confidence provenance;
- `EpisodeRecord` — `nerva.episode.v1` with the lifecycle `open`, `settled`,
  `consolidated`, `superseded`;
- `EpisodeAuditEvent` and `EpisodeMutation` — deterministic integrity evidence
  plus the exact pre-mutation values needed for rollback;
- `EpisodePartition`, `EpisodeDerivativeTrace`, `EpisodeQuery` and
  `EpisodeMatch` — bounded manual split, deletion/export traversal and pure
  retrieval fixtures.

The logical `episode_id` remains stable across correction, settlement and
consolidation revisions. Every immutable revision receives a deterministic
`record_id`, integrity digest and `supersedes_record_id`. Merge and split create
new logical episodes and supersede their inputs without deleting history.

## Reference-only storage

Episode records never copy source values or raw transcripts. A source reference
contains only stable source identifiers, source schema/kind, privacy class,
integrity digest, event time, confidence metadata and deletion root. Atlas
observations must pass their own integrity check before they can become episode
references.

Derived goal, summary and significance assertions may contain bounded episode
text, but each assertion must name existing evidence references. Assertion text
is fail-closed at 4096 characters and audit reasons at 1024 characters; these
are storage bounds, not semantic transcript detection. Unknown privacy is never
widened, source identity is never merged implicitly, and a reference tombstone
removes assertions that depended on that source.

The bounded `nerva.episode.manual.v0` migration accepts reference-only payloads
and recursively rejects raw-content fields such as `transcript`,
`raw_transcript`, `messages`, `turns` and `content`.

## Deterministic manual operations

This slice deliberately implements manual boundaries before learned boundary
detection:

1. `open_episode(...)` creates a stable open record from source references.
2. `settle_episode(...)` closes the time range and may add decision, action or
   outcome references.
3. `consolidate_episode(...)` records an explicit lifecycle transition without
   promoting lessons or mutating Atlas.
4. `correct_episode(...)` creates a new revision and preserves the old record.
5. `merge_episodes(...)` supersedes two or more current episodes and emits one
   deterministic successor.
6. `split_episode(...)` requires disjoint partitions that cover every source
   reference exactly once.
7. `tombstone_sources(...)` traverses deletion roots, tombstones affected
   references and removes derivative assertions that can no longer be
   supported.

Participant, reference and evidence ordering is canonicalized before identity,
integrity and audit fingerprints are calculated. Replaying equivalent manual
inputs therefore yields the same records and audit event. Mutation occurrence
time cannot precede an input revision, and deletion time cannot precede the
affected source occurrence or exceed the mutation time.

## Confidence and product-truth rules

Low-confidence inference is never silently promoted to settled history. A
direct assertion can settle because its evidence is explicit. An inferred
assertion requires measured confidence of at least `0.75`; unknown or weaker
inference is rejected when a record enters `settled` or `consolidated`.

The included `retrieve_episodes(...)` path is a focused, in-memory fixture for
situation terms, participants and verified outcome IDs. Tombstoned references
cannot satisfy situation or outcome signals. The fixture is not wired into
production recall and makes no claim that Episodes improves the current memory
baseline. A later package must compare deterministic episode retrieval against
the current longitudinal recall path before any production adoption.

## Audit, deletion/export traversal and atomic rollback

Every manual operation returns one `EpisodeMutation`:

```text
before records + after records + deterministic integrity audit + rollback value
```

The canonical audit payload is round-trippable and rejects changed content,
authority flags, logical episode IDs or unrelated affected-reference IDs. Its
plain SHA-256 digest detects accidental or uncoordinated modification. It does not authenticate a signer and does not provide non-repudiation.

`rollback()` returns the exact immutable `before` tuple. Persisting an operation
is therefore an atomic caller responsibility: write the complete `after` set
and its audit event, or restore the complete `before` set. Merge and split must
never be partially persisted because their successor and supersession records
are one coherent mutation.

`trace_source_derivatives(...)` maps a canonical deletion root within one
caller-supplied episode revision to its references and assertions. Merge and
split preserve source deletion roots in successor references; callers traversing
a persisted graph must supply each relevant descendant revision. The function
is intentionally not a durable collection-level graph walker.
`tombstone_sources(...)` keeps an explicit tombstone and scrubs assertions whose
evidence was deleted. This is a traversal/value contract only; it does not
implement the external source deletion executor or a durable episode database.

## Tests and evidence

`tests/_nerva_e3_0_checks.py`, invoked by the existing bi-temporal regression
test, covers:

- deterministic open/replay with reordered inputs;
- Atlas integrity and no-raw-transcript boundaries;
- fixed memory-only authority;
- low-confidence settlement rejection;
- settle, consolidate and correction revision chains;
- record and audit round-trip serialization plus tamper rejection;
- deterministic audited merge and exact-cover split;
- source derivative tracing across merge/split, tombstones and rollback;
- bounded assertion/audit text and monotonic time rejection;
- tombstoned retrieval-signal exclusion;
- reference-only v0 migration and raw-content rejection;
- focused situation/outcome retrieval without production wiring.

The candidate branch must be reconciled with the current accepted `main` and
pass blocking Ruff plus the complete repository workflow families on the same
exact head. Local compilation or a focused fixture is supporting evidence only;
it never substitutes for exact-head CI or independent review.

Repository placement is transition evidence only. E3.0 remains `VERIFYING`
until an independent integrator reviews one exact head, required CI is green,
review concerns are resolved and the PR is safely merged.

## Excluded from E3.0

- learned/model-driven event-boundary detection;
- a durable episode store or broad memory migration;
- automatic lesson or Reflection promotion;
- production recall/ranking changes or performance claims;
- source-fact mutation, source deletion execution or automatic identity merge;
- HTTP/API exposure;
- action authorization, execution or completion authority.

## Coherent rollback

Revert the complete E3.0 candidate as one unit:

1. remove `agents/core/memory/episodes.py`,
   `agents/core/memory/_episode_values.py` and
   `agents/core/memory/_episode_operations.py`;
2. remove `tests/_nerva_e3_0_checks.py`;
3. remove its import and invocation from
   `tests/test_h14_1_bitemporal_kg.py`;
4. remove `docs/nerva2/EPISODES_E3_0.md`;
5. restore the prior `docs/nerva2/M1_DELIVERY.md` transition snapshot.

No source `BiTemporalKG`, Atlas observation or existing memory record is
modified by this package. Partial rollback is invalid because leaving the test
hook, documentation, or delivery snapshot without the contract would make the
repository fail or misstate delivery truth.

## Next coherent package

After independent E3.0 acceptance, measure deterministic episode retrieval on a
privacy-safe longitudinal fixture against the current memory baseline. Keep
learned boundary detection, Reflection integration, persistence and production
recall changes as separate independently reversible decisions.
