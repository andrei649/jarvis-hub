"""H022 admin audit: real route authority, bounded inputs, and governed lookup."""

from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.routers import security as security_router
from agents.core.security import dep_audit


class _NoNetworkOSV:
    def __init__(self):
        self.queries = []

    def query_batch(self, queries):
        self.queries.extend(queries)
        return [[] for _ in queries]

    def vulnerability(self, vuln_id):
        raise AssertionError(f"unexpected advisory {vuln_id}")


def _payload():
    return {
        "components": [
            {"surface": "installed", "name": "package", "version": "1.0",
             "origin": "importlib.metadata", "ecosystem": "PyPI"},
            {"surface": "mcp", "name": "@scope/server", "version": "2.0",
             "origin": "search", "ecosystem": "npm"},
        ],
        "errors": [], "fail_on": "low", "ignore_vuln": [],
        "osv_url": "https://api.osv.dev",
        "skip": {"venv": False, "plugins": False, "mcp": False},
    }


def test_h022_route_requires_admin_and_queries_both_ecosystems(monkeypatch):
    from agents.core.kernel import Decision, Verdict, binding

    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "audit-admin"
    monkeypatch.setattr(security_router, "get_orch", lambda: SimpleNamespace())
    monkeypatch.setattr(binding, "make_action_kernel", lambda orch: lambda action: Decision(Verdict.GRANT))
    fake = _NoNetworkOSV()
    monkeypatch.setattr(dep_audit, "default_client", lambda url, **kwargs: fake)
    try:
        client = TestClient(web.app)
        assert client.post("/api/security/dependencies/audit", json=_payload()).status_code in (401, 403)
        assert fake.queries == []
        response = client.post("/api/security/dependencies/audit", json=_payload(),
                               headers={"X-Admin-Token": "audit-admin"})
        assert response.status_code == 200
        body = response.json()
        assert body["report"]["status"] == "clean"
        assert {(q["package"]["name"], q["package"]["ecosystem"]) for q in fake.queries} == {
            ("package", "PyPI"), ("@scope/server", "npm")
        }
    finally:
        web.ADMIN_TOKEN = old


def test_h022_route_rejects_oversized_batch_before_lookup(monkeypatch):
    from agents.core.kernel import Decision, Verdict, binding

    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "audit-admin"
    monkeypatch.setattr(security_router, "get_orch", lambda: SimpleNamespace())
    monkeypatch.setattr(binding, "make_action_kernel", lambda orch: lambda action: Decision(Verdict.GRANT))
    fake = _NoNetworkOSV()
    monkeypatch.setattr(dep_audit, "default_client", lambda url, **kwargs: fake)
    try:
        payload = _payload()
        payload["components"] *= 3000
        response = TestClient(web.app).post("/api/security/dependencies/audit", json=payload,
                                            headers={"X-Admin-Token": "audit-admin"})
        assert response.status_code == 422
        assert fake.queries == []
    finally:
        web.ADMIN_TOKEN = old


def test_h022_route_rejects_impossible_ecosystem_and_oversized_ignore_id(monkeypatch):
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "audit-admin"
    fake = _NoNetworkOSV()
    monkeypatch.setattr(dep_audit, "default_client", lambda url, **kwargs: fake)
    try:
        client = TestClient(web.app)
        for mutation in (
            lambda body: body["components"][0].update(ecosystem="npm"),
            lambda body: body["ignore_vuln"].append("X" * 1000),
        ):
            payload = _payload()
            mutation(payload)
            response = client.post("/api/security/dependencies/audit", json=payload,
                                   headers={"X-Admin-Token": "audit-admin"})
            assert response.status_code == 422
        assert fake.queries == []
    finally:
        web.ADMIN_TOKEN = old


def test_h022_kernel_grants_once_and_halt_denies_before_http_in_both_flag_modes(
    monkeypatch, tmp_path,
):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.security.capability import KillSwitch

    class Audit:
        def __init__(self):
            self.records = []

        def record(self, actor, action, why, metadata=None):
            self.records.append((actor, action, why, metadata))

    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "audit-admin"
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    requests = []

    def transport(_target):
        def answer(request):
            requests.append(request)
            return httpx.Response(200, json={"results": [{"vulns": []} for _ in _payload()["components"]]})

        return httpx.MockTransport(answer)

    def client_for(url, *, authorize_egress):
        return dep_audit.OSVHttpClient(
            url, authorize_egress=authorize_egress,
            resolver=lambda host, mode: (["8.8.8.8"], None),
            transport_factory=transport,
        )

    monkeypatch.setattr(dep_audit, "default_client", client_for)
    try:
        for flag in ("0", "1"):
            monkeypatch.setenv("JARVIS_ACTION_KERNEL", flag)
            kill = KillSwitch(tmp_path / f"kill-{flag}.json")
            audit = Audit()
            orch = SimpleNamespace(autonomy_policy=AutonomyPolicy(), kill_switch=kill,
                                   intent_log=audit, capabilities=None)
            monkeypatch.setattr(security_router, "get_orch", lambda current=orch: current)
            client = TestClient(web.app)
            response = client.post("/api/security/dependencies/audit", json=_payload(),
                                   headers={"X-Admin-Token": "audit-admin"})
            assert response.status_code == 200, response.text
            assert response.json()["report"]["status"] == "clean", response.json()
            assert len(requests) == (1 if flag == "0" else 2)
            assert [row[1] for row in audit.records] == ["authorize:plugin.egress"]

            kill.engage(reason="owner halt")
            denied = client.post("/api/security/dependencies/audit", json=_payload(),
                                 headers={"X-Admin-Token": "audit-admin"})
            assert denied.status_code == 200
            assert denied.json()["report"]["status"] == "unavailable"
            assert len(requests) == (1 if flag == "0" else 2)
            assert [row[1] for row in audit.records] == ["authorize:plugin.egress"] * 2
    finally:
        web.ADMIN_TOKEN = old
