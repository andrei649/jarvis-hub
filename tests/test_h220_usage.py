"""H220 usage accounting from routed calls, including persisted uncertainty."""
import json
import threading

import pytest

from agents.core import cost_tracker


@pytest.fixture(autouse=True)
def isolated_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_store_path", lambda: tmp_path / "usage.json")
    cost_tracker.reset()
    yield
    cost_tracker.reset()


def test_mixed_routes_split_tokens_cost_and_unpriced_calls_by_measurement():
    # The same model name can run locally or over a billable route. The route is proof.
    cost_tracker.record("jarvis", 1000, 500, "gpt-4o", route="local")
    cost_tracker.record("jarvis", 2000, 1000, "gpt-4o", route="cloud")
    cost_tracker.record("friday", 3000, 1000, "unlisted-model", route="cloud")
    cost_tracker.record("friday", 400, 200, "gpt-4o", route="")

    apm = cost_tracker.apm_summary()
    locality = apm["by_locality"]
    assert locality["local"] == {"runs": 1, "input_tokens": 1000, "output_tokens": 500,
                                  "cost_usd": 0.0, "unpriced_calls": 0}
    assert locality["cloud"] == {"runs": 2, "input_tokens": 5000, "output_tokens": 2000,
                                  "cost_usd": 0.015, "unpriced_calls": 1}
    assert locality["unknown"] == {"runs": 1, "input_tokens": 400, "output_tokens": 200,
                                    "cost_usd": 0.003, "unpriced_calls": 0}
    assert apm["totals"]["runs"] == 4
    assert sum(row["runs"] for row in locality.values()) == 4
    assert {row["model"]: row["runs"] for row in apm["by_model"]} == {
        "gpt-4o": 3, "unlisted-model": 1}


def test_locality_survives_reload_and_legacy_calls_remain_unknown():
    cost_tracker.record("athena", 200, 100, "gpt-4o", route="cloud-flash")
    cost_tracker._usage.clear()
    cost_tracker._daily.clear()
    cost_tracker._state["loaded"] = False
    assert cost_tracker.apm_summary()["by_locality"]["cloud"]["runs"] == 1

    path = cost_tracker._store_path()
    old = json.loads(path.read_text())
    old["agents"]["legacy"] = {"calls": 2, "input_tokens": 70, "output_tokens": 30,
                               "cost_usd": 0.004, "model": "gpt-4o", "unpriced_calls": 0}
    path.write_text(json.dumps(old))
    cost_tracker._usage.clear()
    cost_tracker._daily.clear()
    cost_tracker._state["loaded"] = False
    apm = cost_tracker.apm_summary()
    assert apm["by_locality"]["unknown"]["runs"] == 2
    assert apm["by_locality"]["unknown"]["cost_usd"] == 0.004


def test_unfamiliar_route_is_unknown_even_with_local_model_name():
    cost_tracker.record("friday", 100, 20, "qwen3", route="new-provider")
    cost_tracker.record("friday", 200, 40, "qwen3", route="cloud-compatible")
    apm = cost_tracker.apm_summary()["by_locality"]
    assert apm["unknown"]["runs"] == 1
    assert apm["unknown"]["unpriced_calls"] == 1
    assert apm["cloud"]["runs"] == 1
    assert apm["local"]["runs"] == 0


def test_zero_price_model_name_cannot_claim_free_cloud_or_unknown_route():
    cost_tracker.record("jarvis", 100, 20, "qwen", route="cloud-compatible")
    cost_tracker.record("jarvis", 100, 20, "qwen", route="new-provider")
    apm = cost_tracker.apm_summary()["by_locality"]
    assert apm["cloud"]["unpriced_calls"] == 1
    assert apm["unknown"]["unpriced_calls"] == 1
    assert apm["local"]["runs"] == 0


def test_legacy_model_tally_survives_next_record_and_reconciles():
    path = cost_tracker._store_path()
    path.write_text(json.dumps({"agents": {"jarvis": {"calls": 2, "input_tokens": 70,
        "output_tokens": 30, "cost_usd": 0.004, "model": "gpt-4o"}}}))
    cost_tracker._state["loaded"] = False
    cost_tracker.record("jarvis", 10, 5, "gpt-4o-mini", route="cloud")
    apm = cost_tracker.apm_summary()
    by_model = {row["model"]: row for row in apm["by_model"]}
    assert by_model["gpt-4o"]["runs"] == 2
    assert by_model["gpt-4o"]["estimated_from_last_model"] is True
    assert by_model["gpt-4o-mini"]["runs"] == 1
    assert sum(row["runs"] for row in by_model.values()) == apm["totals"]["runs"]
    assert sum(row["input_tokens"] for row in by_model.values()) == apm["totals"]["input_tokens"]
    assert sum(row["output_tokens"] for row in by_model.values()) == apm["totals"]["output_tokens"]


def test_partially_upgraded_model_tally_keeps_residual_unknown():
    path = cost_tracker._store_path()
    path.write_text(json.dumps({"agents": {"jarvis": {"calls": 3, "input_tokens": 80,
        "output_tokens": 35, "cost_usd": 0.004005, "model": "gpt-4o-mini",
        "models": {"gpt-4o-mini": {"calls": 1, "input_tokens": 10,
            "output_tokens": 5, "cost_usd": 0.000005, "unpriced_calls": 0}}}}}))
    cost_tracker._state["loaded"] = False
    apm = cost_tracker.apm_summary()
    by_model = {row["model"]: row for row in apm["by_model"]}
    assert by_model["unknown legacy model"]["runs"] == 2
    assert by_model["unknown legacy model"]["legacy_unattributed"] is True
    assert sum(row["runs"] for row in by_model.values()) == apm["totals"]["runs"]


def test_concurrent_records_never_split_one_snapshot_across_totals_and_locality():
    stop = threading.Event()
    start = threading.Event()
    errors = []

    def write():
        start.wait()
        for _ in range(150):
            cost_tracker.record("jarvis", 10, 2, "gpt-4o", route="cloud")
        stop.set()

    worker = threading.Thread(target=write)
    worker.start()
    start.set()
    reads = 0
    while not stop.is_set():
        apm = cost_tracker.apm_summary()
        reads += 1
        if apm["totals"]["runs"] != sum(row["runs"] for row in apm["by_locality"].values()):
            errors.append(apm)
            break
    worker.join()
    assert reads > 0
    assert errors == []


def test_corrupt_locality_rollup_cannot_claim_local_or_crash():
    path = cost_tracker._store_path()
    path.write_text(json.dumps({"agents": {"old": {"calls": 2, "input_tokens": 80,
        "output_tokens": 20, "cost_usd": 0.005, "model": "qwen3",
        "localities": {"local": {"calls": "two", "input_tokens": 80}, "cloud": []}}}}))
    cost_tracker._state["loaded"] = False
    apm = cost_tracker.apm_summary()
    assert apm["by_locality"]["unknown"]["runs"] == 2
    assert apm["by_locality"]["local"]["runs"] == 0
    cost_tracker.record("old", 10, 2, "gpt-4o", route="cloud")
    assert cost_tracker.apm_summary()["by_locality"]["cloud"]["runs"] == 1


def test_selected_context_outcome_carries_collector_usage_cost_with_basis():
    from agents import web

    class Orch:
        def get_setting(self, key, default=None):
            return ["context_detail", "context_pct"] if key == "display.status_bar_fields" else default

    measured = {"context_detail": {"prompt_tokens": 600, "window_tokens": 1200},
                "context_pct": 50.0}
    usage = {"input_tokens": 1000, "output_tokens": 200,
             "estimated_cost_usd": 0.0042, "usage_basis": "provider_complete",
             "cost_basis": "price_table"}
    result = web._selected_turn_outcome(Orch(), measured, usage=usage)
    assert result["usage_detail"] == {
        "input_tokens": 1000, "output_tokens": 200,
        "estimated_cost_usd": 0.0042, "usage_basis": "provider_complete",
        "cost_basis": "price_table"}

    usage.update(input_tokens=None, output_tokens=None, estimated_cost_usd=None,
                 usage_basis="unknown", cost_basis="unknown")
    assert web._selected_turn_outcome(Orch(), measured, usage=usage)["usage_detail"] == {
        "input_tokens": None, "output_tokens": None,
        "estimated_cost_usd": None, "usage_basis": "unknown", "cost_basis": "unknown"}


def test_unselected_context_does_not_project_usage_detail():
    from agents import web

    class Orch:
        def get_setting(self, key, default=None):
            return ["latency"] if key == "display.status_bar_fields" else default

    result = web._selected_turn_outcome(Orch(), {"latency_ms": 3}, usage={
        "input_tokens": 10, "output_tokens": 1, "estimated_cost_usd": 0.01,
        "usage_basis": "provider_complete", "cost_basis": "price_table"})
    assert result == {"latency_ms": 3}
