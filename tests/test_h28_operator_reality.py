"""H28.5 — hermetic operator S1 reality pack on production governance rails."""

import subprocess
import sys
from collections import Counter

import pytest

from agents.core.observability import reality_harness as rh

EXPECTED_CASES = {
    "operator-browser-playwright-governed",
    "operator-desktop-accessibility-fallback",
    "operator-durable-desktop-actuation",
    "operator-kernel-halt-deny",
    "operator-live-injection-block",
    "operator-malformed-disabled-paths",
    "operator-runtime-cleanup",
}
COUNTER_KEYS = {
    "attempted_actions",
    "governance_checks",
    "approved_actions",
    "executed_actions",
    "blocked_actions",
    "ungoverned_actions",
    "cleanup_calls",
}
EXPECTED_HOST_EXECUTIONS = {
    "operator-browser-playwright-governed": ["browser:allowed"],
    "operator-desktop-accessibility-fallback": [
        "desktop:locate-save",
        "desktop:locate-missing",
    ],
    "operator-durable-desktop-actuation": [
        "desktop:preflight-observe",
        "desktop:click",
        "desktop:type",
        "desktop:launch",
    ],
    "operator-kernel-halt-deny": [],
    "operator-live-injection-block": ["desktop:preflight-observe"],
    "operator-malformed-disabled-paths": ["desktop:malformed-host"],
    "operator-runtime-cleanup": [
        "desktop:preflight-observe",
        "desktop:requested-observe",
    ],
}
EXPECTED_BLOCKED_ACTIONS = {
    "operator-browser-playwright-governed": {
        "browser:blocked": ["attempt", "govern", "block"],
    },
    "operator-desktop-accessibility-fallback": {},
    "operator-durable-desktop-actuation": {
        "desktop:bypass": ["attempt", "govern", "block"],
    },
    "operator-kernel-halt-deny": {
        "desktop:halted-click": ["attempt", "govern", "block"],
    },
    "operator-live-injection-block": {
        "desktop:injected-click": ["attempt", "govern", "block"],
    },
    "operator-malformed-disabled-paths": {
        "workflow:malformed-observation": ["attempt", "govern", "block"],
        "desktop:disabled": ["attempt", "govern", "block"],
    },
    "operator-runtime-cleanup": {
        "browser:startup": ["attempt", "govern", "approve", "block"],
    },
}


def _operator_cases():
    cases = getattr(rh, "OPERATOR_CAPABILITY_CASES", None)
    assert cases is not None, "Task 4 must expose canonical OPERATOR_CAPABILITY_CASES"
    return cases


@pytest.mark.asyncio
async def test_empty_operator_plan_is_blocked_before_runtime_construction(monkeypatch):
    from agents.core.routers import multimodal

    runtime_calls = []

    def unexpected_runtime(*_args, **_kwargs):
        runtime_calls.append(True)
        pytest.fail("an empty proposal must not construct a desktop runtime")

    monkeypatch.setattr(multimodal, "build_desktop_runtime", unexpected_runtime)

    result = await multimodal.execute_desktop_steps(object(), [])

    assert result == {"ok": False, "reason": "empty_steps"}
    assert runtime_calls == []


def test_operator_reality_module_imports_without_harness_import_order_dependency():
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            (
                "import agents.core.observability.operator_reality as module; "
                "assert len(module.OPERATOR_CAPABILITY_CASES) == 7"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_reality_runner_preserves_static_and_measured_probe_metadata():
    async def measured_probe():
        return {
            "passed": True,
            "metadata": {"counters": {"ungoverned_actions": 0}},
        }

    case = rh.RealityCase(
        "operator:test",
        "operator-structured-result",
        "structured measurements survive the runner",
        measured_probe,
        metadata={"suite": "operator-s1"},
    )

    result = await rh.run_reality([case], promote=False)

    assert result["passed"] == 1
    assert result["results"][0]["metadata"] == {
        "suite": "operator-s1",
        "counters": {"ungoverned_actions": 0},
    }


def test_operator_reality_cases_are_canonical_and_owner_live_gate_stays_honest():
    cases = _operator_cases()

    assert {case.name for case in cases} == EXPECTED_CASES
    assert len({case.ref for case in cases}) == len(cases)
    assert all(case.live is False for case in cases)
    assert all(
        case.metadata
        == {
            "suite": "operator-s1",
            "mode": "hermetic",
            "expected_ungoverned_actions": 0,
            "live_owner_validation": "required",
            "promotable": False,
        }
        for case in cases
    )


@pytest.mark.asyncio
async def test_operator_reality_pack_passes_with_measured_zero_ungoverned_actions():
    result = await rh.run_reality(_operator_cases(), promote=False)

    assert result["total"] == result["passed"] == len(EXPECTED_CASES)
    assert result["skipped"] == 0
    for item in result["results"]:
        assert item["passed"] is True
        assert item["metadata"]["suite"] == "operator-s1"
        counters = item["metadata"]["counters"]
        assert set(counters) == COUNTER_KEYS
        assert all(type(value) is int and value >= 0 for value in counters.values())
        assert counters["ungoverned_actions"] == 0
        assert counters["attempted_actions"] == (
            counters["executed_actions"] + counters["blocked_actions"]
        )
        events = item["metadata"]["events"]
        for event in (event for event in events if event["phase"] == "execute"):
            assert any(
                prior["action_id"] == event["action_id"]
                and prior["phase"] == "govern"
                and prior["sequence"] < event["sequence"]
                for prior in events
            )


@pytest.mark.asyncio
async def test_every_case_accounts_for_exact_host_boundary_executions():
    result = await rh.run_reality(_operator_cases(), promote=False)

    for item in result["results"]:
        events = item["metadata"]["events"]
        host_execution_ids = [event["action_id"] for event in events if event["phase"] == "execute"]
        assert host_execution_ids == EXPECTED_HOST_EXECUTIONS[item["name"]]
        assert item["metadata"]["host_execution_count"] == len(host_execution_ids)
        assert item["metadata"]["driver_call_count"] == len(host_execution_ids)
        for action_id in host_execution_ids:
            if action_id in {"desktop:click", "desktop:type", "desktop:launch"}:
                continue  # the durable case has additional upstream events, asserted below
            action_events = [event for event in events if event["action_id"] == action_id]
            assert [event["phase"] for event in action_events] == [
                "attempt",
                "govern",
                "approve",
                "execute",
            ]
            expected_seam = (
                "playwright.page.goto"
                if action_id == "browser:allowed"
                else "windows_desktop_driver.perform"
            )
            assert action_events[-1]["seam"] == expected_seam
        for action_id, expected_phases in EXPECTED_BLOCKED_ACTIONS[item["name"]].items():
            action_events = [event for event in events if event["action_id"] == action_id]
            assert [event["phase"] for event in action_events] == expected_phases


@pytest.mark.asyncio
async def test_operator_cases_reach_real_production_governance_seams(monkeypatch):
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.browser_agent import GovernedBrowser
    from agents.core.browser_playwright import PlaywrightBrowserDriver
    from agents.core.desktop_host import WindowsDesktopDriver
    from agents.core.desktop_operator import DesktopActionExecutor
    from agents.core.tool_rpc import ToolRPCServer

    reached = Counter()

    def wrap_async(cls, method_name, label):
        original = getattr(cls, method_name)

        async def wrapped(self, *args, **kwargs):
            reached[label] += 1
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(cls, method_name, wrapped)

    wrap_async(GovernedBrowser, "run_step", "governed_browser")
    wrap_async(PlaywrightBrowserDriver, "navigate", "playwright_driver")
    wrap_async(WindowsDesktopDriver, "perform", "windows_desktop_driver")
    wrap_async(DesktopActionExecutor, "perform", "desktop_action_executor")
    wrap_async(ToolRPCServer, "handle", "toolrpc_handle")
    wrap_async(AutonomyWorker, "tick", "autonomy_tick")

    result = await rh.run_reality(_operator_cases(), promote=False)

    assert result["passed"] == len(EXPECTED_CASES)
    assert all(
        reached[name] > 0
        for name in {
            "governed_browser",
            "playwright_driver",
            "windows_desktop_driver",
            "desktop_action_executor",
            "toolrpc_handle",
            "autonomy_tick",
        }
    )


@pytest.mark.asyncio
async def test_operator_failure_cases_measure_blocks_and_cleanup_without_actuation():
    result = await rh.run_reality(_operator_cases(), promote=False)
    by_name = {item["name"]: item for item in result["results"]}

    for name in {
        "operator-kernel-halt-deny",
        "operator-live-injection-block",
        "operator-malformed-disabled-paths",
    }:
        counters = by_name[name]["metadata"]["counters"]
        assert counters["blocked_actions"] > 0
        assert counters["ungoverned_actions"] == 0

    cleanup = by_name["operator-runtime-cleanup"]["metadata"]["counters"]
    assert cleanup["cleanup_calls"] >= 2
    assert cleanup["ungoverned_actions"] == 0


@pytest.mark.asyncio
async def test_cleanup_case_releases_resources_from_governed_paths(monkeypatch):
    from agents.core.browser_agent import GovernedBrowser
    from agents.core.desktop_operator import DesktopActionExecutor

    reached = Counter()

    def wrap_async(cls, method_name, label):
        original = getattr(cls, method_name)

        async def wrapped(self, *args, **kwargs):
            reached[label] += 1
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(cls, method_name, wrapped)

    wrap_async(GovernedBrowser, "run_step", "browser_governance")
    wrap_async(DesktopActionExecutor, "perform", "desktop_governance")
    [case] = [case for case in _operator_cases() if case.name == "operator-runtime-cleanup"]

    result = await rh.run_reality([case], promote=False)

    assert result["passed"] == 1
    assert reached["browser_governance"] == 1
    assert reached["desktop_governance"] >= 2


def test_operator_event_ledger_fails_closed_on_bypass_or_conflicting_terminal_event():
    ledger_cls = getattr(rh, "OperatorEventLedger", None)
    assert ledger_cls is not None, "operator counters must come from a causal event ledger"

    bypass = ledger_cls()
    bypass.record("click", "attempt", "toolrpc")
    bypass.record("click", "execute", "driver")
    bypass_result = bypass.result(True, driver_call_count=1)

    assert bypass_result["passed"] is False
    assert bypass_result["metadata"]["counters"]["ungoverned_actions"] == 1

    conflict = ledger_cls()
    conflict.record("click", "attempt", "toolrpc")
    conflict.record("click", "govern", "kernel")
    conflict.record("click", "block", "kernel")
    conflict.record("click", "execute", "driver")

    assert conflict.result(True, driver_call_count=1)["passed"] is False

    fabricated = ledger_cls()
    fabricated.record("click", "attempt", "executor")
    fabricated.record("click", "govern", "kernel")
    fabricated.record("click", "execute", "caller-authored-fake")

    assert fabricated.result(True, driver_call_count=0)["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("ordered", ["pass-first", "fail-first"])
async def test_reality_promotes_shared_capability_once_only_if_all_contracts_pass(
    monkeypatch,
    ordered,
):
    async def good():
        return True

    async def bad():
        return False

    probes = [good, bad] if ordered == "pass-first" else [bad, good]
    cases = [
        rh.RealityCase("action:desktop.step", f"shared-{index}", "contract", probe)
        for index, probe in enumerate(probes)
    ]
    promotions = []
    monkeypatch.setattr(
        rh,
        "_promote",
        lambda capability_id, _ts, passed: promotions.append((capability_id, passed)),
    )

    result = await rh.run_reality(cases, promote=True)

    assert promotions == [("action:desktop.step", False)]
    assert result["promoted"] == []


@pytest.mark.asyncio
async def test_operator_benchmark_identities_are_never_promoted(monkeypatch):
    promotions = []
    monkeypatch.setattr(
        rh,
        "_promote",
        lambda *args: promotions.append(args),
    )

    result = await rh.run_reality(_operator_cases(), promote=True)

    assert result["passed"] == len(EXPECTED_CASES)
    assert result["promoted"] == []
    assert promotions == []


@pytest.mark.asyncio
async def test_explicit_non_promotable_identity_is_not_written(monkeypatch):
    async def good():
        return True

    promotions = []
    monkeypatch.setattr(rh, "_promote", lambda *args: promotions.append(args))
    case = rh.RealityCase(
        "operator:unknown",
        "unknown-benchmark",
        "benchmark only",
        good,
        metadata={"promotable": False},
    )

    result = await rh.run_reality([case], promote=True)

    assert result["passed"] == 1
    assert result["promoted"] == []
    assert promotions == []


@pytest.mark.asyncio
async def test_skipped_live_contract_does_not_demote_existing_verification(monkeypatch):
    async def live_probe():
        return True

    promotions = []
    monkeypatch.setattr(rh, "reality_enabled", lambda: False)
    monkeypatch.setattr(rh, "_promote", lambda *args: promotions.append(args))
    case = rh.RealityCase(
        "action:desktop.step",
        "owner-host-live",
        "owner-host evidence",
        live_probe,
        live=True,
    )

    result = await rh.run_reality([case], promote=True)

    assert result["skipped"] == 1
    assert result["promoted"] == []
    assert promotions == []


@pytest.mark.asyncio
async def test_durable_case_instruments_real_kernel_authorize(monkeypatch):
    from agents.core import kernel

    calls = []
    original = kernel.authorize

    def wrapped(*args, **kwargs):
        calls.append(args[0].kind)
        return original(*args, **kwargs)

    monkeypatch.setattr(kernel, "authorize", wrapped)
    [case] = [
        case for case in _operator_cases() if case.name == "operator-durable-desktop-actuation"
    ]

    result = await rh.run_reality([case], promote=False)

    assert result["passed"] == 1
    assert calls.count("tool.rpc") >= 2
    assert calls.count("desktop.step") == 4

    events = result["results"][0]["metadata"]["events"]
    for action_id in {"desktop:click", "desktop:type", "desktop:launch"}:
        action_events = [event for event in events if event["action_id"] == action_id]
        assert [event["phase"] for event in action_events] == [
            "attempt",
            "govern",
            "approve",
            "govern",
            "govern",
            "approve",
            "execute",
        ]
        assert [event["seam"] for event in action_events] == [
            "toolrpc.handle",
            "toolrpc.durable_queue",
            "durable_operator_decision",
            "task_executor.dispatch",
            "desktop.action_kernel",
            "desktop.action_kernel",
            "windows_desktop_driver.perform",
        ]


@pytest.mark.asyncio
async def test_throwing_operator_probe_still_closes_desktop_runtime(monkeypatch):
    from agents.core.desktop_host import WindowsDesktopDriver
    from agents.core.desktop_operator import GovernedDesktop

    closes = []
    original_close = WindowsDesktopDriver.close

    async def tracked_close(self):
        closes.append(self)
        return await original_close(self)

    async def explode(_self, *_args, **_kwargs):
        raise RuntimeError("forced operator probe failure")

    monkeypatch.setattr(WindowsDesktopDriver, "close", tracked_close)
    monkeypatch.setattr(GovernedDesktop, "run_live", explode)
    [case] = [case for case in _operator_cases() if case.name == "operator-live-injection-block"]

    result = await rh.run_reality([case], promote=False)

    assert result["passed"] == 0
    assert len(closes) == 1
