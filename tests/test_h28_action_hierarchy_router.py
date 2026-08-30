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


# ── DRA-22 / DRA-42: the selector must actually be wired ───────────────────────
#
# H28.2 was ✅ with the selector built but never constructed and nothing
# registered. These pin the production half: real capability ids, real runtime
# gates, and one factory behind both surfaces.

from agents.core.operator_router import (  # noqa: E402
    build_operator_router,
    default_implementations,
    plan_payload,
)


class _FakeToolRPC:
    """Mirrors the ToolRPC surface the capability registry actually reads.

    `_tool_records` derives `tool:*` capabilities from `server.tools()`, so a
    double that only implements `handle` would leave the CLI/UI legs reporting
    `capability_missing` — the registry, not the runtime gate, would be doing the
    rejecting, and the availability wiring would go untested.
    """

    def __init__(self, tools=("desktop_run", "terminal_run")):
        self._tools = tuple(tools)

    def tools(self):
        return [
            {"name": name, "capability_id": f"tool:{name}", "gated": True}
            for name in self._tools
        ]

    async def handle(self, _payload, actor="jarvis"):
        return {"ok": True}


def test_every_registered_capability_id_exists_in_the_live_registry():
    """A plausible-but-unpublished id would report capability_missing forever."""
    from agents.core.observability.capability_registry import build_records

    known = {record.id for record in build_records(None)}
    declared = {impl.capability_id for impl in default_implementations(None)}
    # tool:* ids come from ToolRPC registration, which needs a live orchestrator.
    action_ids = {cap for cap in declared if cap.startswith("action:")}

    assert action_ids, "expected at least one action-backed operator surface"
    missing = action_ids - known
    assert not missing, f"registered against capability ids nothing publishes: {missing}"


def test_tool_backed_ids_match_the_real_toolrpc_registrations():
    """The tool:* legs must name tools autonomy_coordinator actually registers."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "agents" / "core" / "autonomy_coordinator.py"
    ).read_text(encoding="utf-8")
    declared = {impl.capability_id for impl in default_implementations(None)}
    for capability_id in {cap for cap in declared if cap.startswith("tool:")}:
        assert f'capability_id="{capability_id}"' in source, (
            f"{capability_id} is not registered by autonomy_coordinator"
        )


def test_no_visual_implementation_is_faked():
    """No governed visual surface exists yet; claiming one would be fiction."""
    routes = {impl.route for impl in default_implementations(None)}
    assert OperatorRoute.VISUAL not in routes
    assert OperatorRoute.API in routes


def test_default_install_reports_gated_surfaces_unavailable(monkeypatch):
    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_HOST", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_ISOLATED", raising=False)

    payload = plan_payload("open the dashboard", orch=SimpleNamespace(tool_rpc=_FakeToolRPC()))

    assert payload["selected_id"] == "tool_rpc"
    assert payload["route"] == "api"
    assert payload["capability_id"] == "action:tool.rpc"
    reasons = {item["id"]: item["reason"] for item in payload["considered"]}
    assert reasons["terminal_run"] == "unavailable"
    assert reasons["desktop_run"] == "unavailable"


def test_without_tool_rpc_the_answer_is_an_honest_no_route(monkeypatch):
    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_HOST", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_ISOLATED", raising=False)

    payload = plan_payload("open the dashboard", orch=SimpleNamespace())

    assert payload["ok"] is False
    assert payload["selected_id"] is None
    assert payload["reason"] == "no_eligible_implementation"


def test_terminal_becomes_eligible_only_behind_its_real_flag(monkeypatch):
    monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "1")
    impls = {impl.id: impl for impl in default_implementations(None)}
    assert impls["terminal_run"].availability() is True

    monkeypatch.setenv("JARVIS_TERMINAL_TARGETS", "0")
    assert impls["terminal_run"].availability() is False


def test_desktop_availability_tracks_desktop_host_enabled(monkeypatch):
    """Guards the deliberate core/-side copy of the routers/ flag pair."""
    from agents.core.routers.multimodal import desktop_host_enabled

    impls = {impl.id: impl for impl in default_implementations(None)}
    for host, isolated in (("0", "0"), ("1", "0"), ("0", "1"), ("1", "1")):
        monkeypatch.setenv("JARVIS_DESKTOP_HOST", host)
        monkeypatch.setenv("JARVIS_DESKTOP_ISOLATED", isolated)
        assert impls["desktop_run"].availability() == desktop_host_enabled()


def test_explicit_route_constraint_is_honoured(monkeypatch):
    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    orch = SimpleNamespace(tool_rpc=_FakeToolRPC())

    payload = plan_payload("run a command", orch=orch, params={"routes": ["cli"]})

    reasons = {item["id"]: item["reason"] for item in payload["considered"]}
    assert reasons["tool_rpc"] == "goal_not_matched"
    assert payload["selected_id"] is None


def test_factory_registers_against_the_live_registry():
    instance = build_operator_router(SimpleNamespace(tool_rpc=_FakeToolRPC()))
    decision = instance.plan("anything")
    assert decision.selected_id == "tool_rpc"
    assert instance.audit_log[-1]["selected_id"] == "tool_rpc"


def test_operator_plan_tool_is_registered_on_the_real_toolrpc_surface():
    """The agent-facing half of the wiring (the route is the client-facing half)."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "agents" / "core" / "autonomy_coordinator.py"
    ).read_text(encoding="utf-8")
    assert '"operator_plan"' in source
    assert 'capability_id="tool:operator_plan"' in source
    assert "from .operator_router import plan_payload" in source


def test_operator_plan_route_returns_a_decision(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import multimodal

    monkeypatch.delenv("JARVIS_TERMINAL_TARGETS", raising=False)
    monkeypatch.setattr(
        multimodal, "get_orch", lambda: SimpleNamespace(tool_rpc=_FakeToolRPC())
    )

    response = TestClient(web.app).post(
        "/api/operator/plan", json={"goal": "open the dashboard"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_id"] == "tool_rpc"
    assert body["route"] == "api"
    assert body["capability_id"] == "action:tool.rpc"


def test_operator_plan_route_is_503_without_an_orchestrator(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import multimodal

    monkeypatch.setattr(multimodal, "get_orch", lambda: None)

    response = TestClient(web.app).post("/api/operator/plan", json={"goal": "anything"})

    assert response.status_code == 503


def test_operator_plan_route_rejects_an_empty_goal(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import multimodal

    monkeypatch.setattr(
        multimodal, "get_orch", lambda: SimpleNamespace(tool_rpc=_FakeToolRPC())
    )

    response = TestClient(web.app).post("/api/operator/plan", json={"goal": "   "})

    assert response.status_code == 400
    assert response.json()["ok"] is False
