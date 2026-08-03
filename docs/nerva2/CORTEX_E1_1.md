# Cortex E1.1 — privacy-safe comparison baseline

Program: #757 · Epic: #759 · Slice: #792 · Prerequisite: E1.0/#780/#791

## Purpose

E1.1 adds a deterministic evaluation harness over the current `IntentRouter`
and the accepted `nerva.decision.v1` observation contract. It establishes a
reproducible baseline before any scored selector is proposed.

The harness is not a router, trace store, authorization service, executor or
completion signal.

## Baseline contract

`nerva.cortex.comparison.v1` records:

- fixture case ID;
- normalized request digest, never request text;
- `nerva.decision.v1` replay fingerprint;
- expected and observed primary route and decision source;
- candidate, fallback and hard-rejection counts;
- aggregate primary/source fixture agreement;
- source distribution and evaluation failures.

Only fixtures classified as `synthetic_public` or `redacted_local` are
accepted. The checked-in suite contains 20 synthetic prompts covering current
keyword, wake-word and general-route behavior.

Fixture agreement means only that the current deterministic router still
matches the checked-in expectation. It is not real-world outcome quality and
must not be presented as such.

## Honest evidence limits

The first baseline intentionally records these dimensions as `not_measured`:

- latency;
- cost;
- real-outcome quality.

No benchmark superiority, production selector or E1 completion claim is made.

## Failure behavior

Cases are evaluated independently. A router exception produces a bounded
failure result containing only the exception type. The exception message and
fixture text are excluded from the report.

## Authority boundary

The report is `evaluation_only` and fixes:

```text
can_authorize = false
can_execute = false
can_mark_complete = false
```

Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Migration and rollback

Adoption is explicit: callers import and run `compare_router()` in tests or an
evaluation process. No production construction path is changed.

Rollback is deletion of:

- `agents/core/cortex_compare.py`;
- `tests/test_cortex_compare.py`;
- `tests/fixtures/nerva/cortex_e1_1_cases.json`;
- this document and the M1 delivery snapshot.

Removing the harness leaves the existing router and E1.0 shadow contract
unchanged.

## Next slice

Run a separate shadow-comparison experiment that consumes this report contract
and adds explicitly measured latency/cost data only where a trustworthy source
exists. Durable persistence, scored selection and production route changes
remain separate decisions.
