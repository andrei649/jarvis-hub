# Adversarial QA pass — E6.0 / E6.1 / E9.1 (exact head c6a2db5f)

- **Date:** 2026-08-08
- **Worktree:** `.worktrees/qa-adversarial-e6e9`
- **Branch:** `qa/adversarial-e6e9-exact-head`
- **Head:** `c6a2db5fded55426fa395e0ff640a02a3127c2da` (= `origin/main`)
- **Method:** hostile probes first (red-prove before xfail), then a collectible
  regression file `tests/test_adversarial_e6_e9.py` (20 tests), then a full
  re-run of the pre-existing baselines.
- **Scope:** `nerva.lesson.v1` / `nerva.outcome-observation.v1` (E6.0,
  `proposal_only`), `nerva.lesson.evaluation.v1` (E6.1, `evaluation_only`),
  `nerva.benchmark.report.v1` (E9.1, `evaluation_only`).

## Verbatim test results

### Before fixes (QA-only pass)

- `tests/test_adversarial_e6_e9.py` → **17 passed, 3 xfailed (0 failed)**
- `tests/test_daily_reflection.py` → **14 passed** (unchanged)
- `tests/test_nerva_benchmark_e9_0.py` → **12 passed** (unchanged)

```
tests\test_adversarial_e6_e9.py .................x..xx  [100%]
======================== 17 passed, 3 xfailed in 1.90s =========================
```

### After fixes (ADV-03 + ADV-09 implemented, same worktree)

- `tests/test_adversarial_e6_e9.py` → **20 passed (0 failed, 0 xfailed)**
- `tests/test_daily_reflection.py` → **14 passed** (unchanged)
- `tests/test_nerva_benchmark_e9_0.py` → **12 passed** (unchanged)

```
46 passed in 2.39s
```

The three `xfail(strict=False)` regression tests flipped to plain tests
(only the decorator removed; bodies unchanged) and now pass against the
production emission-time fixes.

## Findings

| ID | Epic | Severity | Evidence | Required correction | Regression test |
| --- | --- | --- | --- | --- | --- |
| ADV-03 | E6.0 + E9.1 | medium | The `init=False` authority-ceiling fields (`can_execute`, `can_authorize`, `can_change_routing`, ...) are frozen against the *constructor*, but `object.__setattr__` still flips them after `__post_init__`, and the mutated value was serialized into the canonical payload (`canonical_payload()` / `to_dict()`). Probe on `OutcomeObservation` and `LessonProposal` (E6.0) and `RegressionReport` (E9.1) confirmed the flipped flag reached JSON. Contradicts the "immutable `init=False` fields, so the ceiling is serialized into every record" claim in `docs/nerva2/REFLECTION_E6_0.md` (§authority ceiling) and `docs/nerva2/RESEARCH_LAB_E9_1.md` (line 29). | **FIXED:** serialize the authority fields from module constants at emission time — `_PROPOSAL_ONLY_CEILING` in `reflection_lesson.py`, hard-coded `evaluation_only` flags in `reflection_evaluation.py`, `cortex_measured_compare.py` and `scheduled_report.py`. A post-construction mutation never reaches the emitted payload. | `test_e60_authority_ceiling_is_immutable`, `test_e91_authority_ceiling_is_immutable` (plain, green) |
| ADV-09 | E9.1 | low | `_validate_totals()` accepted a summary with `scored > 0` and `quality_mean is None`, but a real `BenchmarkRun.summary` always derives `quality_mean` from the measured candidate values, so no real run can produce that summary. The validator is documented to "reject a summary that cannot describe a real benchmark run" but did not reject this impossible combination. | **FIXED:** added the converse invariant in `_validate_totals` (`scheduled_report.py`): `scored > 0` implies `quality_mean` is not null (mirror of the existing `scored == 0` rule). | `test_e91_totals_cannot_say_scored_without_quality` (plain, green) |

## Candidates probed and rejected (no defect)

| ID | Claim probed | Result |
| --- | --- | --- |
| ADV-01 | `RegressionReport.prereq_ok` (or property) treats non-`blocked` `PrerequisiteError` as okay | No such attribute exists. `main()` catches `PrerequisiteError` and returns exit code 2, writing a visible `### Nerva E9.1 — FAILED` block; `run_scheduled_suite` raises before any run. Verified in source. |
| ADV-02 | JSON serialization non-canonical / heap insertion-order dependent | All three modules serialize through `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. Probe rebuilt a proposal from a reversed-key dict and got byte-identical `to_json()`; replay fingerprints stable. |
| ADV-04 | `load_lesson_proposal` tolerates unknown payload fields | Rejected: payload with an extra key fails the byte-identical canonical-JSON check. |
| ADV-05 | `BenchmarkRun.from_json` tolerates unknown fields | Rejected: strict key-set enforcement (`_strict_keys`) raises for unknown members. |
| ADV-06 | Newline/pipe claim can forge markdown | `LessonProposal` has no `to_markdown`; `EnvironmentProfile` fields are single-line and control-character free; `RegressionReport.to_markdown` renders numeric rows plus `sort_keys` totals. No injection surface. |
| ADV-07 | E6.1 candidate/baseline get unequal budgets | `_paired_contexts` shares one budget: candidate is derived from the baseline context under the same `max_context_chars`, so equal-size, equal-budget. |
| ADV-08 | Non-finite JSON constants (NaN/Infinity) accepted in runs | Rejected at `json.loads` strict path and at `Measurement.__post_init__` (`_finite`); `_strict_json` in E6.1 also rejects non-finite constants. |
| — | Hidden network / subprocess / filesystem surface in the 4 accepted modules | None of `reflection_lesson.py`, `reflection_evaluation.py`, `scheduled_report.py`, `benchmark.py` imports `subprocess`, `socket`, `requests`, `urllib`, `httpx`, `aiohttp`, or `webbrowser`; verified by source scan (now pinned in `test_e91_no_hidden_network_or_subprocess_imports`). |
| — | Credential/secret keys in serialized payloads | `run.to_json()` and `report.to_json()` carry only identity/totals/comparisons; key-level scan finds no `token`/`password`/`secret`/`api_key`/`credential`/`authorization` keys (pinned in `test_e91_no_credential_keys_in_serialized_payloads`). |
| — | Direct construction bypass of advanced lifecycle/report states | `LessonProposal` beyond `proposed` requires `_TRANSITION_GUARD`; `RegressionReport` requires `_REPORT_GUARD`; `EnvironmentProfile` requires `_ENVIRONMENT_GUARD`. All direct constructions probed raise `ValueError`. |
| — | Duplicate/ghost evidence handling | Duplicate observed references rejected; a verdict key for an unobserved reference is ignored rather than fabricated into eligible evidence; tombstoned expected decisions rejected. |

## Files changed

- `tests/test_adversarial_e6_e9.py` — new (20 tests; the 3 ADV-03/ADV-09 xfails
  flipped to plain tests once the production fixes landed).
- `docs/qa-runs/2026-08-08-adversarial-e6e9.md` — this report.
- `agents/core/reflection_lesson.py` — ADV-03: `_PROPOSAL_ONLY_CEILING` module
  constant re-asserted in `OutcomeObservation.canonical_payload` and
  `LessonProposal.canonical_payload` (emission-time only; fields, constructors
  and guards unchanged).
- `agents/core/reflection_evaluation.py` — ADV-03: `LessonEvaluationReport.to_dict`
  emits the `evaluation_only` ceiling constants (emission-time only).
- `agents/core/cortex_measured_compare.py` — ADV-03: `MeasuredComparisonReport._payload`
  emits the `evaluation_only` ceiling constants (emission-time only).
- `agents/core/observability/scheduled_report.py` — ADV-03: `RegressionReport.to_dict`
  emits the `evaluation_only` ceiling constants; ADV-09: `_validate_totals` rejects
  `scored > 0` with `quality_mean is None`.
- No existing test touched beyond the hostile file; no `BACKLOG.md` / `STATUS.md`
  change (this is a QA branch, not merged).

## Final status

`draft-hold` — findings ADV-03 (medium) and ADV-09 (low) were real, are now
regression-pinned AND fixed by the production emission-time changes in the
same worktree. Full matrix green (20 + 14 + 12 = 46). Branch pushed
(`qa/adversarial-e6e9-exact-head`), **not merged**. Rollback: revert the
production changes; the three flipped tests go back to `xfail`.
