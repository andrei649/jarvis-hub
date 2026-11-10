"""The real CLI, hub client, route and authority path compose into one audit."""

from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.cli.client import HubClient
from agents.cli.nerva import Context, main
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.extensions.consent import ExtensionConsentStore
from agents.core.extensions.manifest import parse_manifest
from agents.core.routers import security
from agents.core.security import dep_audit
from agents.core.security.capability import KillSwitch


@pytest.fixture
def durable_egress(monkeypatch, tmp_path):
    from agents.core import http_client
    from agents.core.observability.egress_monitor import EgressLedgerStore, EgressMonitor

    store = EgressLedgerStore(tmp_path / "audit-egress.db")
    monitor = EgressMonitor(store=store)
    monkeypatch.setattr(http_client, "EGRESS_MONITOR", monitor)
    try:
        yield monitor, store
    finally:
        assert monitor.flush(timeout=3)
        store.close()


def test_cli_inventory_to_guarded_audit_and_live_halt(monkeypatch, tmp_path, durable_egress):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-audit-admin")
    manifest = parse_manifest({
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": [], "tools": [], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": {"requests": "2.31.0"}},
    })
    # An owner declaration is discoverable without installing/activating its code.
    ExtensionConsentStore().grant(manifest)
    from agents.core.paths import data_path

    with sqlite3.connect(data_path("settings.db")) as connection:
        connection.execute("CREATE TABLE settings (category TEXT, key TEXT, value TEXT)")
        connection.execute("INSERT INTO settings VALUES (?, ?, ?)", ("mcp", "servers", json.dumps([
            {"name": "fixture-server", "command": "npx --yes @example/server@1.2.3"},
        ])))
    monkeypatch.setattr(dep_audit, "enumerate_installed", lambda: ([
        dep_audit.Component("installed", "audit-fixture", "1.0.0", "importlib.metadata"),
    ], []))
    kill = KillSwitch(tmp_path / "kill.json")
    orch = SimpleNamespace(autonomy_policy=AutonomyPolicy(), kill_switch=kill,
                           intent_log=None, capabilities=None)
    monkeypatch.setattr(security, "get_orch", lambda: orch)
    external = []

    def answer(request):
        external.append(request)
        if request.url.path == "/v1/querybatch":
            queries = json.loads(request.content)["queries"]
            assert {(q["package"]["ecosystem"], q["package"]["name"]) for q in queries} == {
                ("PyPI", "audit-fixture"), ("PyPI", "requests"), ("npm", "@example/server"),
            }
            return httpx.Response(200, json={"results": [
                {"vulns": [{"id": "GHSA-test-0001"}]} if q["package"]["name"] == "audit-fixture"
                else {} for q in queries
            ]})
        assert request.url.path == "/v1/vulns/GHSA-test-0001"
        return httpx.Response(200, json={
            "id": "GHSA-test-0001", "database_specific": {"severity": "HIGH"},
            "affected": [{"package": {"ecosystem": "PyPI", "name": "audit-fixture"}}],
        })

    monkeypatch.setattr(dep_audit, "default_client", lambda url, **kwargs: dep_audit.OSVHttpClient(
        url, **kwargs, resolver=lambda host, mode: (["8.8.8.8"], None),
        transport_factory=lambda target: httpx.MockTransport(answer),
    ))
    client = TestClient(web.app)

    def opener(request, timeout):
        # Replace only the local wire; HubClient still serializes and authenticates,
        # while FastAPI performs the real request validation and dependency guards.
        response = client.request(request.method, urlsplit(request.full_url).path,
                                  content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "hub refusal",
                                         {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    def invoke():
        output = io.StringIO()
        context = Context(environ={"JARVIS_ADMIN_TOKEN": "test-audit-admin"},
                          out=output, err=io.StringIO(),
                          client_factory=lambda env: HubClient.from_env(env, opener=opener))
        code = main(["security", "audit", "--json", "--fail-on", "high"], context=context)
        return code, json.loads(output.getvalue())

    code, report = invoke()
    assert code == 1 and report["status"] == "findings"
    assert report["queried"] == 3
    assert {key: value["count"] for key, value in report["surfaces"].items()} == {
        "installed": 1, "extension": 1, "mcp": 1,
    }
    assert [finding["id"] for finding in report["findings"]] == ["GHSA-test-0001"]
    assert len(external) == 2
    kill.engage(reason="owner halt during audit campaign")
    code, report = invoke()
    assert code == 5 and report["status"] == "unavailable"
    assert len(external) == 2, "a refused kernel grant must precede every external request"
    monitor, store = durable_egress
    assert monitor.flush(timeout=3)
    # Reopen the actual ledger, without the monitor's in-memory counters.
    from agents.core.observability.egress_monitor import EgressLedgerStore

    restored = EgressLedgerStore(store.path).read("another-process", "dep_audit", 10)
    assert restored["plugins"]["dep_audit"]["allowed"] == 2
    assert restored["plugins"]["dep_audit"]["blocked"] == 1
    assert len(restored["recent"]) == 3
    assert all(row["origin"] == "restored" for row in restored["recent"])
