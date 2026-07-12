from types import SimpleNamespace

import pytest

from agents.core.operator_router import (
    ActionHierarchyRouter,
    OperatorImplementation,
    OperatorRoute,
)


def _record(capability_id, state="wired", risk="read_only"):
    return SimpleNamespace(id=capability_id, state=state, risk=risk)


def _impl(name, route, capability_id=None, *, matches=True, available=True, priority=100):
    def _matches(_goal, _params):
        if isinstance(matches, Exception):
            raise matches
        return matches

    def _available():
        if isinstance(available, Exception):
            raise available
        return available

    return OperatorImplementation(
        id=name,
        route=route,
        capability_id=capability_id or f"action:{name}",
        matcher=_matches,
        availability=_available,
        priority=priority,
    )


def test_fixed_hierarchy_beats_registration_order_and_priority():
    implementations = [
        _impl("visual", OperatorRoute.VISUAL, priority=0),
        _impl("ui", OperatorRoute.STRUCTURED_UI, priority=0),
        _impl("cli", OperatorRoute.CLI, priority=0),
        _impl("api", OperatorRoute.API, priority=999),
    ]
    records = [_record(impl.capability_id) for impl in implementations]
    router = ActionHierarchyRouter(lambda: records)
    for impl in implementations:
        router.register(impl)

    decision = router.plan("create a report", allow_visual_fallback=True)

    assert decision.selected_id == "api"
    assert decision.route == OperatorRoute.API
    assert decision.capability_id == "action:api"
    assert decision.risk == "read_only"
    assert [item["id"] for item in decision.considered] == ["api", "cli", "ui", "visual"]


def test_falls_through_failed_candidates_and_tie_breaks_deterministically():
    records = [
        _record("action:api", state="seam"),
        _record("action:cli-a"),
        _record("action:cli-b"),
        _record("action:ui"),
    ]
    router = ActionHierarchyRouter(lambda: records)
    router.register(_impl("ui", OperatorRoute.STRUCTURED_UI, capability_id="action:ui"))
    router.register(_impl(
        "api", OperatorRoute.API, capability_id="action:api", available=RuntimeError("down")
    ))
    router.register(_impl(
        "cli-b", OperatorRoute.CLI, capability_id="action:cli-b", priority=5
    ))
    router.register(_impl(
        "cli-a", OperatorRoute.CLI, capability_id="action:cli-a", priority=5
    ))

    decision = router.plan("create a report")

    assert decision.selected_id == "cli-a"
    reasons = {item["id"]: item["reason"] for item in decision.considered}
    assert reasons["api"] == "capability_not_ready:seam"
    assert reasons["cli-a"] == "selected"
    assert reasons["cli-b"] == "higher_risk_or_priority_alternative"


def test_visual_is_never_default_and_requires_explicit_opt_in():
    impl = _impl("vision", OperatorRoute.VISUAL)
    router = ActionHierarchyRouter(lambda: [_record(impl.capability_id)])
    router.register(impl)

    refused = router.plan("click the unlabeled control")
    selected = router.plan("click the unlabeled control", allow_visual_fallback=True)

    assert refused.selected_id is None
    assert refused.reason == "no_eligible_implementation"
    assert refused.considered[0]["reason"] == "visual_fallback_not_allowed"
    assert selected.selected_id == "vision"
    assert selected.route == OperatorRoute.VISUAL


def test_registry_and_candidate_failures_are_isolated_and_fail_closed():
    broken = ActionHierarchyRouter(lambda: (_ for _ in ()).throw(RuntimeError("registry")))
    broken.register(_impl("api", OperatorRoute.API))
    assert broken.plan("goal").reason == "capability_registry_unavailable"

    records = [_record("action:bad"), _record("action:good")]
    router = ActionHierarchyRouter(lambda: records)
    router.register(_impl(
        "bad", OperatorRoute.API, capability_id="action:bad", matches=RuntimeError("matcher")
    ))
    router.register(_impl(
        "unavailable",
        OperatorRoute.API,
        capability_id="action:bad",
        available=RuntimeError("probe"),
    ))
    router.register(_impl("missing", OperatorRoute.API, capability_id="action:missing"))
    router.register(_impl("good", OperatorRoute.CLI, capability_id="action:good"))

    decision = router.plan("goal")

    assert decision.selected_id == "good"
    reasons = {item["id"]: item["reason"] for item in decision.considered}
    assert reasons["bad"] == "matcher_failed"
    assert reasons["unavailable"] == "availability_failed"
    assert reasons["missing"] == "capability_missing"

    duplicate_registry = ActionHierarchyRouter(
        lambda: [_record("action:duplicate"), _record("action:duplicate")]
    )
    duplicate_registry.register(_impl(
        "duplicate", OperatorRoute.API, capability_id="action:duplicate"
    ))
    duplicate = duplicate_registry.plan("goal")
    assert duplicate.selected_id is None
    assert duplicate.considered[0]["reason"] == "capability_missing"


def test_registration_and_inputs_are_validated():
    router = ActionHierarchyRouter(lambda: [])
    impl = _impl("api", OperatorRoute.API)
    router.register(impl)

    with pytest.raises(ValueError, match="duplicate"):
        router.register(impl)
    with pytest.raises(ValueError, match="goal"):
        router.plan("   ")
    with pytest.raises(ValueError, match="priority"):
        OperatorImplementation(
            id="bad",
            route=OperatorRoute.API,
            capability_id="action:bad",
            matcher=lambda _goal, _params: True,
            priority=-1,
        )


def test_audit_is_bounded_and_redacts_goal_and_params():
    external = []
    impl = _impl("api", OperatorRoute.API)
    router = ActionHierarchyRouter(
        lambda: [_record(impl.capability_id)], audit_sink=external.append, audit_limit=2
    )
    router.register(impl)

    for index in range(3):
        router.plan(
            f"secret goal {index}",
            params={"token": "never-log-this"},
        )

    assert len(router.audit_log) == 2
    assert len(external) == 3
    encoded = repr(router.audit_log) + repr(external)
    assert "secret goal" not in encoded
    assert "never-log-this" not in encoded
    assert all(len(item["goal_sha256"]) == 64 for item in router.audit_log)
    assert router.audit_log[-1]["selected_id"] == "api"


def test_external_audit_failure_does_not_erase_internal_trace():
    def _broken_sink(_event):
        raise RuntimeError("sink down")

    impl = _impl("api", OperatorRoute.API)
    router = ActionHierarchyRouter(
        lambda: [_record(impl.capability_id)], audit_sink=_broken_sink
    )
    router.register(impl)

    decision = router.plan("safe goal")

    assert decision.selected_id == "api"
    assert router.audit_log[-1]["external_audit"] == "failed"
