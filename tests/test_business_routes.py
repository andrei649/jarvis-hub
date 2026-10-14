"""Business routes keep administrator actions gated and responses credential free."""

import json
import sys
import types

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agents.core.routers import business as business_routes
from agents.core.routers._deps import admin_guard, user_guard
from tests._route_introspect import iter_effective_routes


def _client(tmp_path, monkeypatch, enabled=True, admin=True):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("NERVA_BUSINESS_ENABLED", "1" if enabled else "0")
    app = FastAPI()
    app.include_router(business_routes.router)
    app.dependency_overrides[user_guard] = lambda: None
    if admin:
        app.dependency_overrides[admin_guard] = lambda: None
    else:
        def deny():
            raise HTTPException(403, "administrator required")
        app.dependency_overrides[admin_guard] = deny
    return TestClient(app)


def test_catalog_and_workspace_report_disabled_state_without_creating_data(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, enabled=False)
    catalog = c.get("/api/business/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["enabled"] is False
    assert {item["id"] for item in catalog.json()["templates"]} == {"ecommerce", "automotive", "services"}
    workspace = c.get("/api/business/workspace")
    assert workspace.json()["workspace"]["local_only"] is True
    assert workspace.json()["connections"] == []
    assert c.put("/api/business/workspace", json={"name": "A", "industry": "services", "currency": "EUR", "local_only": True}).status_code == 409
    assert not (tmp_path / "business").exists()


def test_admin_actions_require_admin_and_body_rejects_extras(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, admin=False)
    assert c.get("/api/business/workspace").status_code == 200
    assert c.put("/api/business/workspace", json={"name": "A", "industry": "services", "currency": "EUR", "local_only": True}).status_code == 403
    assert c.post("/api/business/import", json={"name": "A", "kind": "orders", "csv_text": "id,total\na,2"}).status_code == 403
    allowed = _client(tmp_path, monkeypatch)
    assert allowed.post("/api/business/ask", json={"question": "hello", "secret": "x"}).status_code == 422


def test_connection_save_is_pending_and_never_discloses_credentials(tmp_path, monkeypatch):
    connector = types.ModuleType("agents.core.business.connectors")
    connector.validate_connection = lambda provider, url, credentials: url
    monkeypatch.setitem(sys.modules, "agents.core.business.connectors", connector)
    c = _client(tmp_path, monkeypatch)
    response = c.post("/api/business/connections", json={"provider": "hubspot", "name": "Sales", "base_url": "https://api.hubapi.com", "credentials": {"access_token": "SECRET-123"}})
    assert response.status_code == 200, response.text
    connection = response.json()["connection"]
    assert connection["status"] == "pending"
    assert "SECRET-123" not in response.text
    assert "SECRET-123" not in c.get("/api/business/workspace").text
    assert c.delete(f"/api/business/connections/{connection['id']}").json() == {"ok": True}


def test_hubspot_default_url_and_credential_bounds(tmp_path, monkeypatch):
    connector = types.ModuleType("agents.core.business.connectors")
    connector.validate_connection = lambda provider, url, credentials: url or "https://api.hubapi.com"
    monkeypatch.setitem(sys.modules, "agents.core.business.connectors", connector)
    c = _client(tmp_path, monkeypatch)
    body = {"provider": "hubspot", "name": "CRM", "base_url": "", "credentials": {"access_token": "x"}}
    assert c.post("/api/business/connections", json=body).json()["connection"]["base_url"] == "https://api.hubapi.com"
    body["credentials"] = {"access_token": "SECRET-OVERSIZE" * 400}
    rejected = c.post("/api/business/connections", json=body)
    assert rejected.status_code == 422
    assert "SECRET-OVERSIZE" not in rejected.text


def test_csv_import_report_and_reimport_use_current_snapshot(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    first = c.post("/api/business/import", json={"name": "Orders", "kind": "orders", "csv_text": "id,status,total,currency,created_at\na,completed,25.00,EUR,2026-10-13\nb,cancelled,99.00,EUR,2026-10-13"})
    assert first.status_code == 200, first.text
    cid = first.json()["connection"]["id"]
    report = c.post("/api/business/reports/sales_overview/run")
    assert report.status_code == 200, report.text
    assert report.json()["report"]["metrics"]["sales_by_currency"] == {"EUR": "25.00"}
    second = c.post("/api/business/import", json={"name": "Orders", "kind": "orders", "csv_text": "id,status,total,currency\nc,completed,10.00,RON"})
    assert second.json()["connection"]["id"] == cid
    current = c.post("/api/business/reports/sales_overview/run").json()["report"]
    assert current["metrics"]["sales_by_currency"] == {"RON": "10.00"}


def test_csv_same_name_different_kind_is_refused_without_replacing_orders(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    original = c.post("/api/business/import", json={"name": "Daily file", "kind": "orders", "csv_text": "id,status,total,currency\na,completed,25.00,EUR"})
    assert original.status_code == 200
    cid = original.json()["connection"]["id"]
    conflict = c.post("/api/business/import", json={"name": "Daily file", "kind": "products", "csv_text": "id,name,stock_quantity\np,Widget,4"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "source_kind_mismatch"
    assert c.get("/api/business/workspace").json()["connections"][0]["id"] == cid
    report = c.post("/api/business/reports/sales_overview/run").json()["report"]
    assert report["metrics"]["sales_by_currency"] == {"EUR": "25.00"}


def test_failed_refresh_marks_snapshot_stale_and_hides_provider_exception(tmp_path, monkeypatch):
    connector = types.ModuleType("agents.core.business.connectors")
    connector.validate_connection = lambda provider, url, credentials: url
    connector.ConnectorError = type("ConnectorError", (Exception,), {})

    async def fail_fetch(*args):
        raise RuntimeError("SECRET-123 raw provider response")

    connector.fetch_snapshot = fail_fetch
    monkeypatch.setitem(sys.modules, "agents.core.business.connectors", connector)
    c = _client(tmp_path, monkeypatch)
    response = c.post("/api/business/connections", json={"provider": "hubspot", "name": "Sales", "base_url": "https://api.hubapi.com", "credentials": {"access_token": "SECRET-123"}})
    cid = response.json()["connection"]["id"]
    from agents.core.business.store import BusinessStore
    BusinessStore(tmp_path / "business").replace_snapshot(cid, {"records": {"orders": [], "products": [], "deals": [{"id": "one"}]}, "complete": True, "coverage": "one deal"})
    sync = c.post(f"/api/business/connections/{cid}/sync")
    assert sync.status_code == 502
    assert "SECRET-123" not in sync.text
    assert c.get("/api/business/workspace").json()["connections"][0]["status"] == "stale"
    assert BusinessStore(tmp_path / "business").snapshots()[0]["records"]["deals"][0]["id"] == "one"


def test_report_failure_has_safe_error_envelope(tmp_path, monkeypatch):
    reports = types.ModuleType("agents.core.business.reports")
    reports.ReportFilterError = type("ReportFilterError", (ValueError,), {})

    def broken(*args, **kwargs):
        raise RuntimeError("SECRET-RAW provider payload")

    reports.build_report = broken
    monkeypatch.setitem(sys.modules, "agents.core.business.reports", reports)
    c = _client(tmp_path, monkeypatch)
    result = c.post("/api/business/reports/sales_overview/run")
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "report_failed"
    assert "SECRET-RAW" not in result.text


def test_question_context_contains_aggregates_only(tmp_path, monkeypatch):
    from agents.core.business.store import BusinessStore

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    store = BusinessStore(tmp_path / "business")
    cid = store.add_connection("csv", "Sales source", "", {})["id"]
    store.replace_snapshot(cid, {"records": {"orders": [{"id": "SECRET-ROW", "status": "completed", "total": "125.50", "currency": "EUR", "created_at": "2026-10-13"}], "products": [], "deals": []}, "complete": True, "coverage": "imported orders"})
    from agents.core.business import assistant

    async def answer(question, context, local_only):
        assert local_only is True
        serialized = json.dumps(context)
        assert "125.50" in serialized
        assert "Sales source" in serialized
        assert "synced_at" in serialized
        assert "SECRET-ROW" not in serialized
        return {"answer": "125.50", "model": "local", "route": "local"}

    monkeypatch.setattr(assistant, "answer_question", answer)
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/business/ask", json={"question": "How much?"}).json()["answer"] == "125.50"


def test_safe_assistant_refusal_is_visible(tmp_path, monkeypatch):
    from agents.core.business import assistant

    async def refuse(*args):
        raise assistant.BusinessAIError("Local model required")

    monkeypatch.setattr(assistant, "answer_question", refuse)
    c = _client(tmp_path, monkeypatch)
    result = c.post("/api/business/ask", json={"question": "Status?"})
    assert result.status_code == 503
    assert result.json()["error"]["message"] == "Local model required"


def test_route_guard_classification():
    app = FastAPI()
    app.include_router(business_routes.router)
    expected_admin = {"PUT /api/business/workspace", "POST /api/business/connections", "POST /api/business/connections/{connection_id}/sync", "DELETE /api/business/connections/{connection_id}", "POST /api/business/import"}
    expected_user = {"GET /api/business/catalog", "GET /api/business/workspace", "POST /api/business/reports/{workflow_id}/run", "POST /api/business/ask"}
    seen = {}
    for route in iter_effective_routes(app):
        if not route.path.startswith("/api/business"):
            continue
        dependencies = {d.call for d in route.dependant.dependencies}
        for method in route.methods:
            seen[f"{method} {route.path}"] = dependencies
    assert set(seen) == expected_admin | expected_user
    for path in expected_admin:
        assert admin_guard in seen[path]
    for path in expected_user:
        assert user_guard in seen[path]


def test_actual_guard_dependencies_reject_unauthorized_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("NERVA_BUSINESS_ENABLED", "1")
    app = FastAPI()
    app.include_router(business_routes.router)

    def no_user():
        raise HTTPException(401, "user token required")

    def no_admin():
        raise HTTPException(403, "administrator required")

    app.dependency_overrides[user_guard] = no_user
    app.dependency_overrides[admin_guard] = no_admin
    c = TestClient(app)
    assert c.get("/api/business/catalog").status_code == 401
    assert c.get("/api/business/workspace").status_code == 401
    assert c.post("/api/business/reports/sales_overview/run").status_code == 401
    assert c.post("/api/business/ask", json={"question": "What changed?"}).status_code == 401
    assert c.put("/api/business/workspace", json={"name": "A", "industry": "services", "currency": "EUR", "local_only": True}).status_code == 403
    assert c.post("/api/business/connections", json={"provider": "hubspot", "name": "CRM", "base_url": "", "credentials": {"access_token": "x"}}).status_code == 403
    assert c.post("/api/business/connections/x/sync").status_code == 403
    assert c.delete("/api/business/connections/x").status_code == 403
    assert c.post("/api/business/import", json={"name": "A", "kind": "orders", "csv_text": "x"}).status_code == 403


def test_report_can_select_one_source_and_invalid_source_is_refused(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    first = c.post('/api/business/import', json={'name': 'First', 'kind': 'orders',
        'csv_text': 'id,status,total,currency,created_at\na,completed,10,EUR,2026-10-01'}).json()['connection']
    c.post('/api/business/import', json={'name': 'Second', 'kind': 'orders',
        'csv_text': 'id,status,total,currency,created_at\na,completed,99,EUR,2026-10-02'})
    response = c.post('/api/business/reports/sales_overview/run', json={'connection_id': first['id']})
    assert response.status_code == 200, response.text
    report = response.json()['report']
    assert report['metrics']['sales_by_currency'] == {'EUR': '10.00'}
    assert report['source_selection'] == {'connection_id': first['id']}
    assert [source['source'] for source in report['coverage']] == ['First']
    assert c.post('/api/business/reports/sales_overview/run', json={'connection_id': '0' * 32}).status_code == 404


def test_selected_report_question_uses_historical_filtered_metrics(tmp_path, monkeypatch):
    from agents.core.business import assistant
    c = _client(tmp_path, monkeypatch)
    original = {'name': 'Orders', 'kind': 'orders', 'csv_text': 'id,status,total,currency\nPRIVATE-ROW,completed,10,EUR'}
    c.post('/api/business/import', json=original)
    report = c.post('/api/business/reports/sales_overview/run').json()['report']
    original['csv_text'] = 'id,status,total,currency\nPRIVATE-ROW,completed,999,EUR'
    c.post('/api/business/import', json=original)
    contexts = []
    async def answer(question, context, local_only):
        contexts.append(context)
        return {'answer': '10 EUR', 'model': 'local', 'route': 'local'}
    monkeypatch.setattr(assistant, 'answer_question', answer)
    result = c.post('/api/business/ask', json={'question': 'How much?', 'report_id': report['id']})
    assert result.status_code == 200, result.text
    assert contexts[0]['scope'] == 'saved_report'
    assert contexts[0]['reports'][0]['metrics']['sales_by_currency'] == {'EUR': '10.00'}
    assert contexts[0]['reports'][0]['created_at'] == report['created_at']
    assert 'PRIVATE-ROW' not in json.dumps(contexts)
    assert c.post('/api/business/ask', json={'question': 'What?', 'report_id': '0' * 32}).status_code == 404
    assert len(contexts) == 1


def test_csv_error_identifies_row_and_field_without_echoing_cell(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    response = c.post('/api/business/import', json={'name': 'Orders', 'kind': 'orders',
        'csv_text': 'id,status,total,currency\na,completed,12,EUR\nb,completed,PRIVATE-CELL,EUR'})
    assert response.status_code == 422
    message = response.json()['error']['message']
    assert '3' in message and 'total' in message
    assert 'PRIVATE-CELL' not in response.text
    assert c.get('/api/business/workspace').json()['connections'] == []


def test_safe_connector_failure_explains_status_to_operator(tmp_path, monkeypatch):
    from agents.core.business import connectors
    async def fail(*args):
        raise connectors.ConnectorError('Acces refuzat (HTTP 401). Verifică tokenul de acces.')
    monkeypatch.setattr(connectors, 'fetch_snapshot', fail)
    c = _client(tmp_path, monkeypatch)
    cid = c.post('/api/business/connections', json={'provider': 'hubspot', 'name': 'CRM',
        'base_url': '', 'credentials': {'access_token': 'PRIVATE-TOKEN'}}).json()['connection']['id']
    response = c.post(f'/api/business/connections/{cid}/sync')
    assert response.status_code == 502
    assert '401' in response.json()['error']['message']
    assert 'PRIVATE-TOKEN' not in response.text
    assert c.get('/api/business/workspace').json()['connections'][0]['status'] == 'error'


def test_date_filters_are_validated_and_recorded_in_saved_report(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post('/api/business/import', json={'name': 'Dated', 'kind': 'orders',
        'csv_text': 'id,status,total,currency,created_at\na,completed,10,EUR,2026-10-01T23:00:00Z\nb,completed,99,EUR,2026-10-02T01:00:00Z'})
    response = c.post('/api/business/reports/sales_overview/run', json={
        'start_date': '2026-10-01', 'end_date': '2026-10-01'})
    assert response.status_code == 200, response.text
    report = response.json()['report']
    assert report['metrics']['sales_by_currency'] == {'EUR': '10.00'}
    assert report['filters'] == {'start_date': '2026-10-01', 'end_date': '2026-10-01'}
    for bad in ({'start_date': '2026-10-02', 'end_date': '2026-10-01'}, {'start_date': '2026-02-30'}):
        rejected = c.post('/api/business/reports/sales_overview/run', json=bad)
        assert rejected.status_code == 422
        assert rejected.json()['error']['code'] == 'invalid_report_filter'
    assert c.post('/api/business/reports/stock_watch/run', json={'start_date': '2026-10-01'}).status_code == 422
    assert len(c.get('/api/business/workspace').json()['reports']) == 1


def test_unexpected_csv_exception_is_sanitized(tmp_path, monkeypatch):
    from agents.core.business import connectors
    def broken(*args):
        raise ValueError('PRIVATE-PROVIDER-PAYLOAD')
    monkeypatch.setattr(connectors, 'parse_csv', broken)
    c = _client(tmp_path, monkeypatch)
    result = c.post('/api/business/import', json={'name': 'File', 'kind': 'orders', 'csv_text': 'x'})
    assert result.status_code == 422
    assert 'PRIVATE-PROVIDER-PAYLOAD' not in result.text
