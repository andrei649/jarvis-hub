"""H29 Task 3 — hermetic, causal media reality pack."""

from importlib.util import find_spec

import pytest

from agents.core.observability.media_reality import H29_MEDIA_REALITY_CASES
from agents.core.observability.reality_harness import run_reality

EXPECTED_HOST_CALLS = {
    "media-defaults-fail-closed": {
        "image_backend": 0,
        "media_backend": 0,
        "approval_queue": 0,
        "downloader": 0,
        "transcriber": 0,
        "summarizer": 0,
        "browser_driver": 0,
        "media_driver": 0,
    },
    "media-local-catalog-presentation": {
        "image_backend": 0,
        "media_backend": 1,
        "approval_queue": 0,
        "downloader": 0,
        "transcriber": 0,
        "summarizer": 0,
        "browser_driver": 0,
        "media_driver": 2,
    },
    "media-cloud-approval-durable": {
        "image_backend": 0,
        "media_backend": 0,
        "approval_queue": 1,
        "downloader": 0,
        "transcriber": 0,
        "summarizer": 0,
        "browser_driver": 0,
        "media_driver": 0,
    },
    "media-summarizer-governed-download": {
        "image_backend": 0,
        "media_backend": 0,
        "approval_queue": 0,
        "downloader": 1,
        "transcriber": 1,
        "summarizer": 1,
        "browser_driver": 0,
        "media_driver": 0,
    },
    "media-kernel-halt-driver-deny": {
        "image_backend": 0,
        "media_backend": 0,
        "approval_queue": 0,
        "downloader": 0,
        "transcriber": 0,
        "summarizer": 0,
        "browser_driver": 0,
        "media_driver": 0,
    },
}

EXPECTED_COUNTERS = {
    "media-defaults-fail-closed": (3, 0, 0, 3),
    "media-local-catalog-presentation": (2, 2, 2, 0),
    "media-cloud-approval-durable": (1, 1, 0, 1),
    "media-summarizer-governed-download": (2, 1, 1, 1),
    "media-kernel-halt-driver-deny": (1, 1, 0, 1),
}


def test_media_reality_pack_has_a_dependency_neutral_module():
    assert find_spec("agents.core.observability.media_reality") is not None


def test_media_reality_pack_has_the_exact_h29_contracts():
    assert [case.name for case in H29_MEDIA_REALITY_CASES] == list(EXPECTED_HOST_CALLS)
    assert all(case.live is False for case in H29_MEDIA_REALITY_CASES)
    assert all(
        case.metadata
        == {
            "suite": "h29-media",
            "mode": "hermetic",
            "expected_ungoverned_actions": 0,
            "live_owner_validation": "required",
            "promotable": False,
        }
        for case in H29_MEDIA_REALITY_CASES
    )


@pytest.mark.asyncio
async def test_media_reality_pack_returns_causal_measured_host_counters():
    out = await run_reality(H29_MEDIA_REALITY_CASES, promote=False)

    assert out["total"] == out["passed"] == len(EXPECTED_HOST_CALLS)
    assert out["skipped"] == 0
    for result in out["results"]:
        metadata = result["metadata"]
        counters = metadata["counters"]
        host_calls = metadata["host_calls"]
        assert (
            counters["attempted_actions"],
            counters["governance_checks"],
            counters["executed_actions"],
            counters["blocked_actions"],
        ) == EXPECTED_COUNTERS[result["name"]]
        assert counters["ungoverned_actions"] == 0
        assert counters["attempted_actions"] == (
            counters["executed_actions"] + counters["blocked_actions"]
        )
        assert host_calls == EXPECTED_HOST_CALLS[result["name"]]
        assert metadata["host_call_count"] == sum(host_calls.values())
        assert metadata["events"]

    by_name = {result["name"]: result["metadata"] for result in out["results"]}
    assert by_name["media-defaults-fail-closed"]["default_bindings"] == {
        "image_backend": False,
        "llm_unload": False,
        "llm_load": False,
        "media_backends": 0,
        "approval_queue": False,
        "media_catalog": False,
        "local_guard": False,
        "downloader": False,
        "transcriber": False,
        "summarizer": False,
        "url_guard": False,
    }
    assert by_name["media-defaults-fail-closed"]["ambient_host_calls"] == {
        "network": 0,
        "process": 0,
        "urlopen": 0,
    }
    assert (
        by_name["media-defaults-fail-closed"]["tripwire_scope"]
        == "construction-and-execution"
    )
    assert by_name["media-cloud-approval-durable"]["queue_reopen_count"] == 1
