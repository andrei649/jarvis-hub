"""V2 — capability readiness registry: derivation, honest states, endpoint.

The registry DERIVES one record per capability from the existing plugin/component/skill
registries and assigns SEAM/WIRED — and crucially never VERIFIED/GA until the V1 reality
harness exists. These tests pin that honesty so a future change can't silently fabricate
"verified".
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from agents.core.observability import capability_registry as cr


def teardown_function():
    cr._OVERRIDES.clear()


def _fake_orch():
    return SimpleNamespace(
        components=SimpleNamespace(status={"arena": "ok", "broken_thing": "failed"}),
        skills=SimpleNamespace(
            skills={
                "loaded_skill": SimpleNamespace(module=object(), agents=["stark"], trusted=True),
                "stub_skill": SimpleNamespace(module=None, agents=[], trusted=False),
            }
        ),
    )


# ── derivation ───────────────────────────────────────────────────────────────
def test_plugins_and_actions_derive_statically_without_orch():
    recs = cr.build_records(orch=None)
    assert recs, "expected plugin records from BUILTIN_PLUGINS"
    assert {r.kind for r in recs} == {"plugin", "action"}
    weather = next(r for r in recs if r.id == "plugin:weather")
    assert weather.state == cr.WIRED          # enabled manifest → wired
    assert weather.detail["network_access"]   # carries policy metadata for the board
    assert weather.description
    assert weather.inputs["type"] == "object"
    assert weather.risk == "sensitive"
    assert weather.requires
    assert weather.supports
    assert weather.verification
    assert weather.rollback.mode == "disable"
    assert weather.rollback.description
    assert 0.0 <= weather.confidence <= 1.0
    assert weather.implementation

    payment = next(r for r in recs if r.id == "action:payment")
    assert payment.kind == "action"
    assert payment.risk == "irreversible_or_money"
    assert payment.rollback.mode == "cancel"
    assert payment.rollback.automatic is False
    assert "settled" in payment.rollback.limitations
    assert payment.contract_ref == "agents.core.payments:PAYMENT_CONTRACT"
    assert payment.detail["mediation"] == "kernel"


def test_plugin_detail_carries_no_honesty_fields_without_orch():
    # orch=None is the static-derivation path (state/policy only) — adding the
    # live honesty mirror must not leak honesty keys when there is no orch to
    # resolve a live plugin instance against.
    weather = next(r for r in cr.build_records(orch=None) if r.id == "plugin:weather")
    for key in ("configured", "honesty", "degraded", "degraded_reason", "degraded_needs"):
        assert key not in weather.detail


def test_plugin_detail_degrades_honestly_when_orch_has_no_plugins():
    # A fake orch with no `.plugins` registry must resolve every plugin as
    # not-loaded rather than crash — same fail-closed posture as `/plugins`.
    weather = next(r for r in cr.build_records(orch=_fake_orch()) if r.id == "plugin:weather")
    assert weather.detail["configured"] is False
    assert weather.detail["honesty"]["status"] == "needs_config"
    assert weather.detail["degraded"] is False  # weather has no degradation_info()


def test_plugin_detail_mirrors_live_honesty_and_degradation():
    # The exact verdict `/plugins` renders must also land in the capability
    # board's `detail`, so `/api/capabilities` can't imply a mock plugin is live.
    class _MockOnlyPlugin:
        def available(self):
            return False

        def degradation_info(self):
            return {"reason": "no source configured", "needs": ["plugins.gecko_ing_client_id"]}

    class _LivePlugin:
        def available(self):
            return True

    orch = SimpleNamespace(plugins={"balance": _MockOnlyPlugin(), "websearch": _LivePlugin()})
    recs = {r.id: r for r in cr.build_records(orch=orch)}

    balance = recs["plugin:balance"].detail
    assert balance["configured"] is False
    assert balance["honesty"]["status"] == "needs_config"
    assert balance["degraded"] is True
    assert balance["degraded_reason"] == "no source configured"
    assert "plugins.gecko_ing_client_id" in balance["degraded_needs"]

    websearch = recs["plugin:websearch"].detail
    assert websearch["configured"] is True
    assert websearch["honesty"]["status"] == "live"
    assert websearch["degraded"] is False


def test_components_and_skills_derive_from_orch():
    recs = {r.id: r for r in cr.build_records(orch=_fake_orch())}
    assert recs["component:arena"].state == cr.WIRED      # init ok
    assert recs["component:broken_thing"].state == cr.SEAM  # init failed → not wired
    assert recs["skill:loaded_skill"].state == cr.WIRED   # module loaded
    assert recs["skill:stub_skill"].state == cr.SEAM      # no module → stub
    assert recs["skill:loaded_skill"].owner_agent == "stark"
    assert recs["component:arena"].confidence == 0.0
    assert recs["skill:loaded_skill"].confidence == 0.0


def test_nothing_is_verified_until_harness_lands():
    snap = cr.snapshot(orch=_fake_orch())
    assert snap["by_state"]["verified"] == 0
    assert snap["by_state"]["ga"] == 0
    assert snap["harness_pending"] is True
    assert snap["total"] == len(snap["capabilities"])
    assert snap["by_kind"]["plugin"] > 0
    assert snap["by_kind"]["action"] > 0


def test_every_registry_record_serializes_a_complete_rollback_contract():
    rows = cr.snapshot(orch=_fake_orch())["capabilities"]
    assert rows
    for row in rows:
        assert set(row["rollback"]) == {
            "mode", "description", "automatic", "handler_ref", "limitations",
        }
        assert row["rollback"]["description"].strip()
        if row["rollback"]["automatic"]:
            assert row["rollback"]["handler_ref"]


# ── overrides (demote-only) ───────────────────────────────────────────────────
def test_override_can_demote_but_not_fabricate_verified():
    cr.set_override("plugin:weather", cr.SEAM)
    recs = {r.id: r for r in cr.build_records()}
    assert recs["plugin:weather"].state == cr.SEAM  # demoted

    cr.set_override("plugin:weather", cr.VERIFIED)   # refused — only the harness promotes
    recs = {r.id: r for r in cr.build_records()}
    assert recs["plugin:weather"].state == cr.SEAM   # unchanged from the rejected override


# ── endpoint ───────────────────────────────────────────────────────────────────
def test_endpoint_503_until_orchestrator_ready(monkeypatch):
    from agents import web
    from agents.core.routers import analytics
    monkeypatch.setattr(analytics, "get_orch", lambda: None)
    resp = TestClient(web.app).get("/api/metrics/capabilities")
    assert resp.status_code == 503


def test_endpoint_returns_registry(monkeypatch):
    from agents import web
    from agents.core.routers import analytics
    monkeypatch.setattr(analytics, "get_orch", _fake_orch)
    resp = TestClient(web.app).get("/api/metrics/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["harness_pending"] is True
    assert body["by_kind"]["plugin"] > 0
    assert body["by_kind"]["action"] > 0
    assert any(c["id"] == "component:arena" for c in body["capabilities"])
    assert any(c["id"] == "action:payment" for c in body["capabilities"])
    payment = next(c for c in body["capabilities"] if c["id"] == "action:payment")
    assert payment["rollback"]["mode"] == "cancel"
    assert payment["rollback"]["automatic"] is False
    assert "no-store" in resp.headers.get("cache-control", "")


def test_canonical_capabilities_endpoint_is_user_guarded_and_returns_registry(monkeypatch):
    from agents import web
    from agents.core.routers import analytics

    monkeypatch.setattr(analytics, "get_orch", _fake_orch)
    client = TestClient(web.app)
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(body["capabilities"])
    assert any(row["id"] == "component:arena" for row in body["capabilities"])
    assert "no-store" in response.headers.get("cache-control", "")
