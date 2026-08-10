# Cortex E1.1 — privacy-minimised comparison baseline

Program: #757 · Epic: #759 · Slice: #792 · Prerequisite: E1.0/#780/#791

## Purpose

E1.1 adds a deterministic evaluation harness over the current `IntentRouter`
and the accepted `nerva.decision.v1` observation contract. It establishes a
reproducible baseline before any scored selector is proposed.

The harness is not a router, trace store, authorization service, executor or
completion signal.

## Baseline contract

`nerva.cortex.comparison.v1` records:

- fixture case ID and explicit privacy class;
- normalized request digest, never request text;
- `nerva.decision.v1` replay fingerprint;
- expected and observed primary route and decision source;
- candidate, fallback and hard-rejection counts;
- aggregate primary/source fixture agreement;
- source/privacy distributions and evaluation failures.

Every fixture must explicitly declare `synthetic_public` or `redacted_local`;
missing or invalid classifications fail closed. The checked-in suite contains
20 synthetic prompts covering current keyword, wake-word and general-route
behavior.

A normalized SHA-256 request digest is **pseudonymous, not anonymous**. Common
or guessable inputs may be recoverable through dictionary comparison, and the
digest can link repeated inputs. Any `redacted_local` evaluation and its report
therefore remain subject to local access, retention and deletion controls. The
harness removes raw request text from the report; it does not claim that the
digest is safe for unrestricted sharing.

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

The E1.1 helper was originally invoked from `tests/test_router_v2.py` to keep
the then-pinned collected-test ledger unchanged. That historical embedding has
been removed: `tests/test_nerva_e1_1_collected.py` now collects the helper as an
independent Nerva contract node, while the router regression remains focused on
router behavior.

Rollback requires one coherent revert:

- delete `agents/core/cortex_compare.py`;
- delete `tests/_nerva_e1_1_checks.py`;
- delete `tests/test_nerva_e1_1_collected.py`;
- delete `tests/fixtures/nerva/cortex_e1_1_cases.json`;
- delete this document and `docs/nerva2/M1_DELIVERY.md`.

Removing that complete set leaves the existing router and E1.0 shadow contract
unchanged. Partial deletion is not a valid rollback because it could leave a
broken test import or stale delivery claim.

## Next slice

Run a separate shadow-comparison experiment that consumes this report contract
and adds explicitly measured latency/cost data only where a trustworthy source
exists. Durable persistence, scored selection and production route changes
remain separate decisions.
