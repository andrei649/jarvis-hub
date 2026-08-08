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

- `tests/test_adversarial_e6_e9.py` → **17 passed, 3 xfailed (0 failed)**
- `tests/test_daily_reflection.py` → **14 passed** (unchanged)
- `tests/test_nerva_benchmark_e9_0.py` → **12 passed** (unchanged)

```
tests\test_adversarial_e6_e9.py .................x..xx  [100%]
======================== 17 passed, 3 xfailed in 1.90s ========================
```

## Findings

| ID | Epic | Severity | Evidence | Required correction | Regression test |
| --- | --- | --- | --- | --- | --- |
| ADV-03 | E6.0 + E9.1 | medium | The `init=False` authority-ceiling fields (`can_execute`, `can_authorize`, `can_change_routing`, ...) are frozen against the *constructor*, but `object.__setattr__` still flips them after `__post_init__`, and the mutated value is serialized into the canonical payload (`canonical_payload()` / `to_dict()`). Probe on `OutcomeObservation` and `LessonProposal` (E6.0) and `RegressionReport` (E9.1) confirms the flipped flag reaches JSON. Contradicts the "immutable `init=False` fields, so the ceiling is serialized into every record" claim in `docs/nerva2/REFLECTION_E6_0.md` (§authority ceiling) and `docs/nerva2/RESEARCH_LAB_E9_1.md` (line 29). | Serialize the authority fields from module constants at emission time (e.g. always re-assert `False`/`proposal_only`/`evaluation_only` inside `canonical_payload`/`to_dict`), or hash the authority block into the replay fingerprint so a mutated flag invalidates the fingerprint. | `test_e60_authority_ceiling_is_immutable`, `test_e91_authority_ceiling_is_immutable` (both `xfail(strict=False)` with `ADV-03`) |
| ADV-09 | E9.1 | low | `_validate_totals()` accepts a summary with `scored > 0` and `quality_mean is None`, but a real `BenchmarkRun.summary` always derives `quality_mean` from the measured candidate values, so no real run can produce that summary. The validator is documented to "reject a summary that cannot describe a real benchmark run" but does not reject this impossible combination. | Add the converse invariant in `_validate_totals`: `scored > 0` implies `quality_mean` is not null (mirror of the existing `scored == 0` rule). | `test_e91_totals_cannot_say_scored_without_quality` (`xfail(strict=False)` with `ADV-09`) |

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

- `tests/test_adversarial_e6_e9.py` — new (20 tests: 17 green + 3 `xfail(strict=False)`).
- `docs/qa-runs/2026-08-08-adversarial-e6e9.md` — this report.
- No production module touched; no existing test touched; no `BACKLOG.md` / `STATUS.md` change (this is a QA-only branch, not merged).

## Final status

`draft-hold` — findings ADV-03 (medium) and ADV-09 (low) are real and now
regression-pinned. Branch pushed (`qa/adversarial-e6e9-exact-head`), **not
merged**. Fixes belong in production modules, which were out of scope for this
QA-only pass.
