# Nerva E3.1 — longitudinal Episode retrieval comparison

Status: draft implementation evidence for #798 / #761. This document does not
claim production recall improvement or epic completion.

## Purpose

E3.1 compares the accepted E3.0 Episodes retrieval facade with the current real
`MemoryManager.remember()/recall()` baseline over one bounded longitudinal
fixture. The output is a deterministic, text-free
`nerva.episode.comparison.v1` report intended only for evaluation and review.

## Dependency and authority boundary

- prerequisite: accepted E3.0 / #782 / PR #796;
- repository security prerequisite #800 is already accepted in `main`;
- no dependency on E8 Synapse or an E9 production benchmark service;
- report authority is fixed to `evaluation_only`;
- Episodes remain `memory_record_only`;
- the package cannot authorize, execute, or mark work complete;
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Reused implementation

The package reuses:

- `MemoryEvalCase`, `run_recall_eval`, `keyword_answer`, and `score_answer` from
  `agents/core/memory/eval.py`;
- accepted immutable Episode records, current-revision selection, tombstone
  behavior, `EpisodeQuery`, and `retrieve_episodes` from E3.0;
- the existing H14.1 regression hook and full cross-platform repository CI.

No second memory store, scorer, permission system, or signing mechanism is
introduced.

## Included coherent slice

The PR contains one evaluation package with a single dependency gate, authority
boundary, test surface, and rollback:

1. `agents/core/memory/episode_compare.py` — typed comparison input, result, and
   canonical report;
2. `tests/_nerva_e3_1_checks.py` — longitudinal, privacy, provenance, budget,
   determinism, revision, and failure-isolation regressions;
3. `tests/test_h14_1_bitemporal_kg.py` — count-neutral invocation through the
   established E2/E3 full-suite hook;
4. this evidence document.

Splitting these files would leave either an untested contract or tests without
their declared evidence and rollback boundary.

## Evidence semantics

Each comparison case runs both paths over the same transient facts, question,
expected answer, and abstention rule. Canonical reports retain only:

- bounded content-free case and ability identifiers;
- explicit fixture privacy class;
- pass/fail booleans and retrieved/match counts;
- exception type names, never exception messages;
- baseline and Episode accuracy, delta, wins/ties/losses, and failure counts;
- one explicit shared retrieval budget;
- deterministic privacy distribution and replay fingerprint;
- explicit `not_measured` latency and real-outcome quality.

The report does not retain fixture facts, questions, expected text, Episode
assertion text, retrieved snippets, answers, or exception messages.

`no_regression=true` is derived, not caller-controlled. It requires zero
baseline failures, zero Episode failures, and Episode accuracy greater than or
equal to the baseline on the bounded fixture.

## Independent-review corrections

The candidate fails closed on the three evidence gaps identified during
independent integration review:

### Baseline provenance binding

The canonical source `memory.eval.run_recall_eval` is accepted only when the
actual callable is the imported `run_recall_eval` function. An injected runner
must declare a different bounded source identifier, and the real runner may not
be relabeled as a test double. This prevents injected code from claiming the
real MemoryManager path.

### Typed privacy compatibility

A case labeled `synthetic_public` may contain only Episode references whose
typed privacy class is `public`. Non-public typed references require the
`redacted_local` fixture class. This makes the reported privacy distribution
consistent with the typed Episode evidence available to the comparison.

This check cannot infer whether caller-authored strings are semantically
sensitive. Fixture authors remain responsible for ensuring synthetic text is
actually synthetic and redacted text remains locally governed.

### Equal retrieval budgets

`top_k` is the single explicit comparison retrieval budget. Every
`EpisodeQuery.limit` must equal it before either path runs. Baseline reports that
claim a different budget or return more than the requested number of snippets
fail closed; Episode results exceeding the same bound also fail. The canonical
report records the shared budget.

## Longitudinal fixture

The owned fixture covers:

- a stable verified outcome;
- a multi-session locally redacted fact;
- a corrected Episode where obsolete evidence must not be scored as current;
- tombstoned outcome evidence that must no longer support retrieval;
- conflicting current revisions, which surface as bounded failure evidence.

The fixture is deliberately small. It is not a production user study and does
not establish broad semantic-memory quality.

## Determinism and failure behavior

- cases are ordered by content-free case ID;
- duplicate IDs are rejected;
- derived totals are recomputed and validated by the report constructor;
- malformed or failed baseline evidence cannot produce a positive result;
- baseline and Episode failures are isolated per path and retained only by
  exception type;
- canonical JSON and SHA-256 replay fingerprints are stable under case-order
  changes.

## Explicit exclusions

This package does not add:

- production recall, ranking, prompt, or routing changes;
- comparison or Episode persistence;
- learned event-boundary detection;
- Reflection or lesson promotion;
- source deletion execution or identity merge;
- HTTP/API exposure;
- latency, cost, energy, or real-world outcome claims;
- action authorization, execution, or completion authority.

## Residual risks

- keyword scoring can understate or overstate semantic answer quality;
- the real baseline transiently ingests fixture text even though reports omit it;
- bounded identifiers remain linkable and must not encode personal content;
- `redacted_local` data still requires local access and retention governance;
- current-revision guarantees are bounded by supplied immutable revisions;
- fixture success alone does not justify a production recall change.

## Tests

The focused regression surface verifies:

- the real MemoryManager and accepted Episodes paths;
- equal per-path retrieval budgets and over-budget failure behavior;
- injected-runner provenance binding;
- typed public/local privacy compatibility;
- corrected, tombstoned, stable, multi-session, and forked histories;
- canonical derived values, deterministic JSON, and replay fingerprint;
- content-free retained evidence and exception-type-only failures;
- fixed evaluation-only authority.

Acceptance still requires the complete exact-head repository workflow matrix and
fresh independent review.

## Rollback

Revert the four-file E3.1 diff as one unit. This removes the comparison module,
its focused checks, the two-line H14.1 hook, and this document. Accepted E3.0,
the existing memory evaluation harness, production recall, and stored data are
unchanged; no migration or compensating action is required.

## Next work package

After independent acceptance, any production recall experiment, durable
comparison storage, learned Episode boundary work, or Reflection integration
must be proposed as a separate independently reversible package with its own
authority, privacy, test, and rollback evidence.
