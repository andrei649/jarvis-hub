"""H31.6 — camera-intelligence reality pack and owner-gated live read."""

from __future__ import annotations

from importlib.util import find_spec

import pytest

from agents.core.observability.camera_reality import (
    H31_CAMERA_LIVE_CASES,
    H31_CAMERA_REALITY_CASES,
    CameraEventLedger,
)
from agents.core.observability.reality_harness import run_reality

HOST_ZERO = {
    "frigate_events": 0,
    "frigate_snapshot": 0,
    "local_vlm": 0,
}

EXPECTED_HOST_CALLS = {
    "camera-no-consent-zero-host-calls": dict(HOST_ZERO),
    "camera-private-pipeline-and-feeds": {
        "frigate_events": 1,
        "frigate_snapshot": 1,
        "local_vlm": 1,
    },
    "camera-kill-switch-zero-host-calls": dict(HOST_ZERO),
    "camera-mid-inference-revocation": {
        "frigate_events": 1,
        "frigate_snapshot": 1,
        "local_vlm": 1,
    },
    "camera-offline-honest-degradation": {
        "frigate_events": 2,
        "frigate_snapshot": 0,
        "local_vlm": 0,
    },
}


def test_camera_reality_pack_is_dependency_neutral_and_exact():
    assert find_spec("agents.core.observability.camera_reality") is not None
    assert [case.name for case in H31_CAMERA_REALITY_CASES] == list(EXPECTED_HOST_CALLS)
    assert all(case.live is False for case in H31_CAMERA_REALITY_CASES)
    assert all(
        case.metadata
        == {
            "suite": "h31-camera",
            "mode": "hermetic",
            "expected_ungoverned_actions": 0,
            "live_owner_validation": "required",
            "promotable": False,
        }
        for case in H31_CAMERA_REALITY_CASES
    )


@pytest.mark.asyncio
async def test_camera_reality_pack_proves_zero_bypass_and_privacy_contracts():
    result = await run_reality(H31_CAMERA_REALITY_CASES, promote=False)

    assert result["total"] == result["passed"] == len(EXPECTED_HOST_CALLS)
    assert result["skipped"] == 0
    for item in result["results"]:
        metadata = item["metadata"]
        assert metadata["host_calls"] == EXPECTED_HOST_CALLS[item["name"]]
        assert metadata["host_call_count"] == sum(metadata["host_calls"].values())
        assert metadata["counters"]["ungoverned_actions"] == 0
        assert metadata["external_host_calls"] == 0
        assert metadata["raw_frame_consumer_calls"] == 0

    by_name = {item["name"]: item["metadata"] for item in result["results"]}
    assert by_name["camera-no-consent-zero-host-calls"]["storage_touched"] is False
    assert by_name["camera-private-pipeline-and-feeds"]["masked_before_vlm"] is True
    assert by_name["camera-private-pipeline-and-feeds"]["encrypted_at_rest"] is True
    assert by_name["camera-private-pipeline-and-feeds"]["feed_restart_duplicates"] == 2
    assert by_name["camera-private-pipeline-and-feeds"]["snapshot_expired_exactly"] is True
    assert by_name["camera-private-pipeline-and-feeds"]["metadata_expired_exactly"] is True
    assert by_name["camera-kill-switch-zero-host-calls"]["events_after_halt"] == 0
    assert by_name["camera-mid-inference-revocation"]["purge_complete"] is True
    assert by_name["camera-mid-inference-revocation"]["events_after_revoke"] == 0
    assert by_name["camera-offline-honest-degradation"]["source_status"] == "offline"


def test_camera_ledger_detects_an_ungoverned_or_raw_frame_host_call():
    ledger = CameraEventLedger()
    ledger.host_call(
        "frigate_snapshot",
        governed=False,
        external=True,
        raw_frame_consumer=True,
    )

    result = ledger.result(True)

    assert result["passed"] is False
    assert result["metadata"]["counters"]["ungoverned_actions"] == 1
    assert result["metadata"]["external_host_calls"] == 1
    assert result["metadata"]["raw_frame_consumer_calls"] == 1


@pytest.mark.asyncio
async def test_owner_live_camera_probe_is_double_opt_in_and_never_mutates(monkeypatch):
    assert len(H31_CAMERA_LIVE_CASES) == 1
    assert H31_CAMERA_LIVE_CASES[0].live is True

    monkeypatch.delenv("JARVIS_REALITY_HARNESS", raising=False)
    monkeypatch.delenv("JARVIS_H31_FRIGATE_LIVE", raising=False)
    skipped = await run_reality(H31_CAMERA_LIVE_CASES, promote=False)
    assert skipped["skipped"] == 1 and skipped["total"] == 0

    monkeypatch.setenv("JARVIS_REALITY_HARNESS", "1")
    degraded = await run_reality(H31_CAMERA_LIVE_CASES, promote=False)
    assert degraded["total"] == 1 and degraded["passed"] == 0
    metadata = degraded["results"][0]["metadata"]
    assert metadata["status"] == "degraded"
    assert metadata["reason"] == "owner_live_opt_in_missing"
    assert metadata["mutation_probe"] is False
