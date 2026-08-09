# E1/E6/E9 Authority-Ceiling + Totals-Invariant Successors (from closed #854 aggregate)

> **Status:** EXECUTING (owner-authorized). #856/#858 is fully green but not yet merged (review
> blocked); the owner explicitly instructed development to proceed, so the serialization guard's
> "merge before materializing" is overridden by direct owner consent (2026-08-09).
> **Provenance:** closed PR #854 (`qa/adversarial-e6e9-exact-head`, frozen `21a37f81`) — owner decision:
> the 11-file aggregate is the wrong integration unit; these four bounded successors reconstruct
> only the accepted fixes with successor-local hostile regressions and their own generated truth.
> **Successor serialization:** E1 → E6 → E9-authority → E9-totals (each phase starts after the previous
> merged; E1 is running now).

## Goal

Restore the emission-time authority ceiling on four Nerva report/lesson surfaces so a mutated
`can_*`/`authority` field (flipped via `object.__setattr__` after construction, or in persisted
JSON) can never serialize elevated authority, and make the E9 totals cannot claim `scored > 0`
without a `quality_mean`. Four small, independently reviewable PRs.

## Non-goals

- NO change to `test_adversarial_e6_e9.py` (the aggregate test file stays closed/never-merged).
- NO touch to shared generated-truth surfaces beyond the mechanical `status_sync.py` re-run.
- NO new behavior, authority, or runtime wiring. Each fix is emission-time constancy only.
- NO parallel branches — each phase starts after the previous phase merged into `main`.

## Serialization & branch map

| # | Branch | Production file(s) | Defect |
| --- | --- | --- | --- |
| 1 | `nerva2/e1-authority-ceiling-hardening` | `agents/core/cortex_measured_compare.py` | ADV-03 (E1.2a measured report) |
| 2 | `nerva2/e6-authority-ceiling-hardening` | `agents/core/reflection_lesson.py`, `agents/core/reflection_evaluation.py` | ADV-03 (E6.0/E6.1) |
| 3 | `nerva2/e9-authority-ceiling-hardening` | `agents/core/observability/scheduled_report.py` | ADV-03 (E9.1) + ADV-09 scope-grant emission |
| 4 | `nerva2/e9-totals-invariant` | `agents/core/observability/scheduled_report.py` | ADV-09 `_validate_totals` semantic invariant |

## Common per-phase workflow (every phase)

1. Create the worktree only after the previous phase merged (Phase 1 was owner-authorized to start
   while #858 waits on review). Rebase-first: `git fetch origin` then `git rebase origin/main`.
2. TDD: write the hostile regression test FIRST, run it, confirm it fails (RED) on current main.
3. Apply the emission-time constant fix (GREEN). Run the focused test file → pass.
4. `python scripts/status_sync.py --reuse-js-counts` (test count changes with each new test file).
5. `ruff check . && ruff format --check .` on touched files; run `python -m pytest tests/ -q` (full suite).
6. Commit, push, `gh pr create --draft --base main --head <branch>`, CI green, `gh pr ready`, wait acceptance.
7. Do NOT force-push (re-drafts PRs).

Interpreter on Windows: `C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe`
(worktrees have no `.venv` of their own).

## Phase 1 — E1 authority-ceiling repair (`nerva2/e1-authority-ceiling-hardening`)

### RED test — `tests/test_e1_authority_ceiling.py`

Reuse the established E1 fixture helpers (they stay in `tests/_nerva_e1_2_checks.py`; no changes there):

```python
from __future__ import annotations

from pathlib import Path

from tests._nerva_e1_2_checks import _build_report, _report_fixture


def test_e1_authority_ceiling_is_immutable(tmp_path: Path) -> None:
    label_set, batch, store, _environment = _report_fixture(tmp_path)
    report = _build_report(batch, store, label_set)

    object.__setattr__(report, "can_execute", True)
    object.__setattr__(report, "authority", "operator")

    payload = report.to_dict()
    assert payload["authority"] == "evaluation_only"
    assert payload["can_execute"] is False
    assert payload["can_authorize"] is False
    assert payload["can_change_routing"] is False
    assert payload["can_promote"] is False
    assert payload["can_mark_complete"] is False
```

RED evidence: on current main, `report.to_dict()` serializes the mutated `self.can_execute`/`self.authority`.

### GREEN fix — `agents/core/cortex_measured_compare.py` `MeasuredComparisonReport._payload()` (line ~1069)

Replace these six payload lines:

```python
"authority": self.authority,
"can_change_routing": self.can_change_routing,
"can_authorize": self.can_authorize,
"can_execute": self.can_execute,
"can_mark_complete": self.can_mark_complete,
"can_promote": self.can_promote,
```

with the constants already asserted by `from_json` (lines ~1154-1161):

```python
"authority": "evaluation_only",
"can_change_routing": False,
"can_authorize": False,
"can_execute": False,
"can_mark_complete": False,
"can_promote": False,
```

Keep the remaining `_payload()` keys unchanged (fingerprint/measurement fields stay `self.*`).

### Verification

- `pytest tests/test_e1_authority_ceiling.py -q` → pass.
- `pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday` → pass (runs E1.2 checks).
- Full suite + status_sync + release gate per the common workflow.

## Phase 2 — E6 authority-ceiling repair (`nerva2/e6-authority-ceiling-hardening`)

### RED tests — `tests/test_e6_authority_ceiling.py`

Fixtures copied from the accepted #854 test (proven, minimal):

```python
from __future__ import annotations

import agents.core.reflection_lesson as reflection_lesson

_REVISION = "a" * 40


def _reference(source: str, sequence: int, route_id: str = "C0-main") -> reflection_lesson.EpisodeReference:
    return reflection_lesson.EpisodeReference.build(
        atlas_conf=reflection_lesson.AtlasConfidence(
            confidence_label="validated",
            claims=("qa-authority-ceiling",),
        ),
        route_id=route_id,
        source=source,
        sequence=sequence,
        goal="review architecture",
        owner="qa-owner",
        is_owner=True,
        updated="2026-08-08T00:00:00Z",
        nonce="qa-authority-ceiling",
    )


def _confirmed(source: str, sequence: int) -> reflection_lesson.OutcomeObservation:
    return reflection_lesson.OutcomeObservation.from_episode(
        reference=_reference(source, sequence), success=True
    )


def _proposal(source: str, sequence: int) -> reflection_lesson.LessonProposal:
    return reflection_lesson.LessonProposal.from_proposal(
        reference=_reference(source, sequence), insight="qa-authority-ceiling"
    )


def _evaluation(source: str, sequence: int):
    import agents.core.reflection_evaluation as reflection_evaluation

    return reflection_evaluation.evaluate_lesson(
        outcome=_confirmed(source, sequence), proposal=_proposal(source, sequence)
    )


def test_e60_authority_ceiling_is_immutable() -> None:
    observation = _confirmed(source="e60-a", sequence=1)
    object.__setattr__(observation, "can_authorize", True)
    assert observation.canonical_payload()["can_authorize"] is False

    proposal = _proposal(source="e60-b", sequence=2)
    object.__setattr__(proposal, "can_execute", True)
    assert proposal.canonical_payload()["can_execute"] is False


def test_e61_evaluation_record_authority_ceiling_is_immutable() -> None:
    evaluation = _evaluation(source="e61-a", sequence=3)
    object.__setattr__(evaluation, "can_execute", True)
    object.__setattr__(evaluation, "can_promote", True)
    payload = evaluation.to_dict()
    assert payload["authority"] == "evaluation_only"
    assert payload["can_execute"] is False
    assert payload["can_promote"] is False
```

RED evidence: `canonical_payload()`/`to_dict()` serialize mutated flags on current main.

### GREEN fixes

- `agents/core/reflection_lesson.py` `LessonProposal.canonical_payload()` (~line 542):
  `payload["can_execute"] = self.can_execute` → `payload["can_execute"] = False`.
  (Sibling flags `can_authorize`/`can_mark_complete`/`can_change_*`/`can_promote` are already `False`; verify `OutcomeObservation.canonical_payload` at ~351 too and hard-code any remaining `self.can_*`.)
- `agents/core/reflection_evaluation.py` `LessonEvaluationReport.to_dict()` (~line 846): the payload currently starts as `dict(self.__dict__)` (copies mutable `can_*`), then overrides some flags. Hard-code the FULL ceiling — `authority = "evaluation_only"` and every `can_*`/`can_grant_*` field present on the dataclass → `False` — so no `self.can_*` value survives into the emitted dict.

## Phase 3 — E9 authority-ceiling repair (`nerva2/e9-authority-ceiling-hardening`)

### RED tests — `tests/test_e9_authority_ceiling.py`

```python
from __future__ import annotations

import asyncio
from pathlib import Path

import agents.core.observability.benchmark as benchmark
import agents.core.observability.scheduled_report as scheduled_report

_REVISION = "a" * 40


def _build_benchmark_report(store_root: Path, run_id: str = "qa-adv") -> object:
    run = asyncio.run(
        scheduled_report.run_scheduled_suite(
            benchmark.BenchmarkStore(store_root), revision=_REVISION, run_id=run_id
        )
    )
    return scheduled_report.build_report(
        run,
        store=benchmark.BenchmarkStore(store_root),
        environment=scheduled_report.EnvironmentProfile.detect(runner_id="qa-e9-successor"),
        previous=None,
    )


def test_e91_authority_ceiling_is_immutable(tmp_path) -> None:
    report = _build_benchmark_report(tmp_path)
    object.__setattr__(report, "can_change_routing", True)
    object.__setattr__(report, "can_grant_inference_scope", True)
    payload = report.to_dict()
    assert payload["can_change_routing"] is False
    assert payload["can_grant_inference_scope"] is False
    assert payload["authority"] == "evaluation_only"
```

(`EnvironmentProfile` is imported by `scheduled_report` from `agents.common.environment` and
re-exported — confirmed at `scheduled_report.py:10`.)

### GREEN fixes — `agents/core/observability/scheduled_report.py`

TWO emission sites leak `self.*` authority (both confirmed on current main):

1. ~lines 1248-1253 (`RegressionReport.to_dict`): `can_grant_inference_scope`, `can_grant_atlas_promotion_scope`,
   `can_grant_reflection_scope`, `authority`, `can_change_routing`, ... → hard-code
   `False`/`"evaluation_only"` for all authority/scope fields.
2. ~lines 1258-1268 (report `to_dict`): `authority`, `can_authorize`, `can_change_routing`, `can_execute`,
   `can_promote`, `can_mark_complete` → hard-code constants.

Verified fix shape from accepted #854 (hunks at 1269-1275 and 1596-1620): every `self.can_*` and
`self.can_grant_*` payload assignment becomes `False`; every `self.authority` becomes `"evaluation_only"`.

## Phase 4 — E9 totals invariant (`nerva2/e9-totals-invariant`)

Start AFTER Phase 3 merged (both touch `scheduled_report.py`).

### RED test — `tests/test_e9_totals_invariant.py`

```python
from __future__ import annotations

import pytest

from agents.core.observability.scheduled_report import _validate_totals


def test_e91_totals_cannot_say_scored_without_quality() -> None:
    with pytest.raises(ValueError):
        _validate_totals(
            {
                "total": 2,
                "scored": 2,
                "passed": 2,
                "failed": 0,
                "unscored": 0,
                "errors": 0,
                "quality_mean": None,
                "baseline_quality_mean": None,
            }
        )


def test_e91_scored_with_quality_is_valid() -> None:
    # control: scored > 0 WITH a quality mean is accepted
    _validate_totals(
        {
            "total": 2,
            "scored": 2,
            "passed": 2,
            "failed": 0,
            "unscored": 0,
            "errors": 0,
            "quality_mean": 0.9,
            "baseline_quality_mean": 0.8,
        }
    )
```

RED evidence: `_validate_totals({... scored: 2, quality_mean: None ...})` passes on current main.

### GREEN fix — `agents/core/observability/scheduled_report.py` `_validate_totals` (line ~590)

After the existing per-field checks (before the means/regression computations), add:

```python
if counts["scored"] > 0 and totals["quality_mean"] is None:
    raise ValueError("cannot report scored > 0 without a non-null quality_mean")
```

Keep `_validate_totals` returning `None` (its sole caller at line ~93 in `build_report` already
calls it for side-effect validation).

## Traceability & acceptance

- Each PR body: cite the closure-note provenance (closed #854, `21a37f81`), the bounded scope claim,
  the RED→GREEN evidence, and the generated-truth delta.
- After Phase 4 merges, optionally add a short `docs/qa-runs/` note per successor recording the runs
  (matching the #854 QA-run doc style but successor-local).
