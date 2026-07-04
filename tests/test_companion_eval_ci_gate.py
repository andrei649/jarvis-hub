"""M2.4 scheduled companion eval gate.

Plain asserts only so the sandbox can run this directly without pytest.
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability import companion_eval as ce  # noqa: E402
from agents.core.observability.datasets import DatasetStore  # noqa: E402


def test_ci_gate_cli_can_use_explicit_store_root():
    with TemporaryDirectory() as d:
        root = Path(d)
        store_root = root / "persisted-eval-store"
        rc = ce._main(["--ci-gate", "--store-root", str(store_root)])

        assert rc == 0
        assert (store_root / "datasets" / ce.DATASET_NAME / "runs.jsonl").exists()


def test_ci_gate_records_run_and_summary():
    with TemporaryDirectory() as d:
        root = Path(d)
        store = DatasetStore(root=root / "eval")
        summary = root / "summary.md"

        result = ce.run_ci_gate(store=store, summary_path=summary)

        assert result["ok"] is True
        assert result["score"] == 1.0
        assert result["passed"] == result["total"]
        assert result["store_root"] == str(store.root)
        assert result["self_check_failures"] == 0
        assert result["north_star_guardrails"]["mode"] == "offline-scheduled"
        assert result["north_star_guardrails"]["breaches"] == []
        assert store.runs(ce.DATASET_NAME)[0]["run_id"] == result["run_id"]
        text = summary.read_text(encoding="utf-8")
        assert "Companion Eval Gate" in text
        assert "North-Star Guardrails" in text


def test_ci_gate_compares_against_previous_run():
    with TemporaryDirectory() as d:
        store = DatasetStore(root=Path(d) / "eval")

        first = ce.run_ci_gate(store=store)
        second = ce.run_ci_gate(store=store)

        assert first["baseline_compare"] is None
        assert second["baseline_compare"]["regression"] is False
        assert second["baseline_compare"]["score_delta"] == 0.0


def test_ci_gate_fails_if_threshold_is_stricter_than_possible():
    with TemporaryDirectory() as d:
        store = DatasetStore(root=Path(d) / "eval")

        result = ce.run_ci_gate(store=store, min_score=1.01)

        assert result["ok"] is False
        assert result["score"] == 1.0
        assert result["min_score"] == 1.01


def test_eval_nightly_workflow_persists_companion_eval_store():
    workflow = (repo_root / ".github" / "workflows" / "eval-nightly.yml").read_text(encoding="utf-8")

    assert "JARVIS_EVAL_STORE:" in workflow
    assert "actions/cache/restore@0057852bfaa89a56745cba8c7296529d2fc39830  # v4.3.0" in workflow
    assert "actions/cache/save@0057852bfaa89a56745cba8c7296529d2fc39830  # v4.3.0" in workflow
    assert "path: ${{ env.JARVIS_EVAL_STORE }}" in workflow
    assert "restore-keys:" in workflow
    assert "--store-root \"$JARVIS_EVAL_STORE\"" in workflow
