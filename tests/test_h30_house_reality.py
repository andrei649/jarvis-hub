"""H30.7 — hermetic house-brain reality pack and honest owner live gate."""

from __future__ import annotations

from importlib.util import find_spec

import pytest

from agents.core.observability.house_reality import (
    H30_HOUSE_LIVE_CASES,
    H30_HOUSE_REALITY_CASES,
    HouseEventLedger,
)
from agents.core.observability.reality_harness import run_reality

HOST_ZERO = {
    "ha_rest_read": 0,
    "ha_websocket": 0,
    "ha_service": 0,
    "media_driver": 0,
}

EXPECTED_HOST_CALLS = {
    "house-adapter-read-reconnect-offline": {
        **HOST_ZERO,
        "ha_rest_read": 2,
        "ha_websocket": 3,
    },
    "house-graph-presence-privacy-purge": {**HOST_ZERO, "ha_rest_read": 1},
    "house-approved-reversible-actuation": {
        **HOST_ZERO,
        "ha_rest_read": 2,
        "ha_service": 1,
    },
    "house-security-strong-confirmation": {
        **HOST_ZERO,
        "ha_rest_read": 3,
        "ha_service": 1,
    },
    "house-verification-rollback": {
        **HOST_ZERO,
        "ha_rest_read": 3,
        "ha_service": 2,
    },
    "house-kernel-halt": {**HOST_ZERO, "ha_rest_read": 1},
    "house-room-output-governed": {**HOST_ZERO, "media_driver": 2},
}

EXPECTED_COUNTERS = {
    "house-adapter-read-reconnect-offline": (0, 0, 0, 0),
    "house-graph-presence-privacy-purge": (0, 0, 0, 0),
    "house-approved-reversible-actuation": (1, 1, 1, 0),
    "house-security-strong-confirmation": (2, 2, 1, 1),
    "house-verification-rollback": (2, 2, 2, 0),
    "house-kernel-halt": (1, 1, 0, 1),
    "house-room-output-governed": (1, 1, 1, 0),
}


def test_house_reality_pack_is_dependency_neutral_and_exact():
    assert find_spec("agents.core.observability.house_reality") is not None
    assert [case.name for case in H30_HOUSE_REALITY_CASES] == list(EXPECTED_HOST_CALLS)
    assert all(case.live is False for case in H30_HOUSE_REALITY_CASES)
    assert all(
        case.metadata
        == {
            "suite": "h30-house",
            "mode": "hermetic",
            "expected_ungoverned_actions": 0,
            "live_owner_validation": "required",
            "promotable": False,
        }
        for case in H30_HOUSE_REALITY_CASES
    )


@pytest.mark.asyncio
async def test_house_reality_pack_proves_causal_zero_bypass_contracts():
    result = await run_reality(H30_HOUSE_REALITY_CASES, promote=False)

    assert result["total"] == result["passed"] == len(EXPECTED_HOST_CALLS)
    assert result["skipped"] == 0
    for item in result["results"]:
        metadata = item["metadata"]
        counters = metadata["counters"]
        assert (
            counters["attempted_actions"],
            counters["governance_checks"],
            counters["executed_actions"],
            counters["blocked_actions"],
        ) == EXPECTED_COUNTERS[item["name"]]
        assert counters["ungoverned_actions"] == 0
        assert metadata["host_calls"] == EXPECTED_HOST_CALLS[item["name"]]
        assert metadata["host_call_count"] == sum(metadata["host_calls"].values())

    by_name = {item["name"]: item["metadata"] for item in result["results"]}
    assert by_name["house-adapter-read-reconnect-offline"]["reconnect_delays"] == [0.25, 0.5]
    assert by_name["house-graph-presence-privacy-purge"]["private_facts_after_purge"] == 0
    assert by_name["house-approved-reversible-actuation"]["approved_task_executor"] is True
    assert by_name["house-security-strong-confirmation"]["strong_confirmation_consumed"] is True
    assert by_name["house-verification-rollback"]["rollback_status"] == "verified"
    assert by_name["house-kernel-halt"]["ha_service_calls"] == 0
    assert by_name["house-room-output-governed"]["identity_refusals"] == 2
    assert by_name["house-room-output-governed"]["resolved_target"] == "speaker-kitchen"


def test_house_ledger_detects_an_ungoverned_or_unapproved_ha_mutation():
    ledger = HouseEventLedger()
    ledger.record("bypass", "attempt", "direct-service-call")
    ledger.host_call("bypass", "ha_service", governed=True)
    ledger.record("bypass", "execute", "direct-service-call")

    result = ledger.result(True)

    assert result["passed"] is False
    assert result["metadata"]["counters"]["ungoverned_actions"] == 1
    assert result["metadata"]["unapproved_host_actions"] == 1


@pytest.mark.asyncio
async def test_owner_live_probe_is_double_opt_in_and_missing_configuration_is_not_a_pass(
    monkeypatch,
):
    assert len(H30_HOUSE_LIVE_CASES) == 1
    case = H30_HOUSE_LIVE_CASES[0]
    assert case.live is True

    monkeypatch.delenv("JARVIS_REALITY_HARNESS", raising=False)
    monkeypatch.delenv("JARVIS_H30_HA_LIVE", raising=False)
    skipped = await run_reality(H30_HOUSE_LIVE_CASES, promote=False)
    assert skipped["skipped"] == 1 and skipped["total"] == 0

    monkeypatch.setenv("JARVIS_REALITY_HARNESS", "1")
    degraded = await run_reality(H30_HOUSE_LIVE_CASES, promote=False)
    assert degraded["total"] == 1 and degraded["passed"] == 0
    assert degraded["results"][0]["metadata"]["status"] == "degraded"
    assert degraded["results"][0]["metadata"]["reason"] == "owner_live_opt_in_missing"

