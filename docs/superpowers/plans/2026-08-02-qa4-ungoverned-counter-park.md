# PARKED — QA4 / A8-iv: the live ungoverned-actions counter

**Parked 2026-08-02** during the finish-line run, **for a design flaw, not for time.**
A first implementation was written, passed 12 targeted tests and 7 blast-radius suites in
isolation, and was then **withdrawn** when a full-suite run exposed that it under-reports
breaches. This document exists so the next attempt starts from the finding rather than
repeating it.

## What A8-iv needs

Owner gate A8 asks for `ungoverned_actions == 0` on a real host. Today that number exists
only inside the hermetic reality packs (`observability/{operator,media,house,camera,ambient}_reality.py`),
and the live meter `GET /api/metrics/kernel` cannot even distinguish **"nothing ran"** from
**"the kernel is off"** — with `JARVIS_ACTION_KERNEL` unset every tally sits at zero either way.

## The approach that failed, and why

The withdrawn attempt marked the context inside `authorize()` with a ContextVar
(`kernel/mediation_marker.py`, a sibling of `action_origin.py`'s origin var) and had the
autonomy worker ask `was_mediated()` immediately before executing an approved task.

Two independent defects:

1. **The marker is never reset, so it goes stale within one tick.** A worker tick runs many
   tasks in a single async context. Task A's execution may call `authorize()`, which sets the
   marker; task B's check then reads `True` and **B is not counted even if it genuinely bypassed
   the kernel**. The counter under-reports breaches — the dishonest direction for a security
   metric, and exactly what ADV-091 / `tests/test_audit_gates_measure_substance.py` exist to
   prevent. Caught by `test_authorize_marks_the_context_as_mediated` failing under the full
   suite (`assert True is False`) while passing in isolation.

2. **A ContextVar cannot bridge enqueue → execute at all.** A broker calls `authorize()` at
   *enqueue* time in a request context; the worker executes the task later in a *different*
   context, possibly a different process after a restart. So legitimately-governed queued tasks
   read as breaches (false positives) while in-tick bypasses read as clean (false negatives).
   Both directions wrong.

The ContextVar idea is sound for a **synchronous** facade → `authorize` → execute flow. It was
applied to the **queued** seam, where it cannot work.

## The design that should work

Per-task **persisted** evidence, not per-context:

1. At the governed intake — `AutonomyWorker.govern_enqueue`, the single funnel O26-P0.7 (F3)
   created — stamp the kernel decision onto the task payload, mirroring the existing
   `_mark_payload_for_origin`.
2. At the worker seam, read that stamp instead of any ContextVar.
3. A kind that `kernel/registry.classify()` marks `Mediation.KERNEL`, arriving with **no** stamp,
   is the breach.

This survives restarts, cannot leak between tasks, and is attributable per task.

## What was sound and worth reusing

* `KernelMetrics.record_ungoverned(kind, reason)` / `record_refused_unmediated(kind)` plus the
  `reset()` extension.
* Snapshot fields `enabled` (from `kernel_enabled()`), `ungoverned_actions`,
  `ungoverned_by_kind`, `refused_unmediated`. **`enabled` is independently valuable**: without
  it a zero cannot be interpreted.
* Counting a facade refusal (`capability_actions.py`, `action_kernel_disabled`) **separately**
  from breaches — a fail-closed refusal is correct behavior and must never inflate the breach
  count.
* The rule that the packs' "action_calls − governed_calls" formula must **not** be lifted into
  production: `authorize()` is also reached by brokers, routers and the egress hook that never
  touch the action facade, so the two counts are not comparable process-wide. One seam, or
  per-action correlation, or nothing.

## Do not ship the metrics fields alone

With the worker seam removed, `ungoverned_actions` becomes structurally incapable of being
non-zero — a literal `0` wearing a metric's clothes, which is precisely the anti-pattern the
audit-gate tests forbid. Ship the persisted-stamp design, or ship nothing.

## Lesson for the process

Isolated test runs cannot catch context leakage; the full suite can. **Any change that reads or
writes shared context (ContextVars, module singletons, process-wide state) must be verified with
a full-suite run before it ships**, not only with its own file.
