"""Routes for the day report + Proof-of-Action receipts (agents/core/routers/report.py).

The router is mounted into a small FastAPI app with the user guard overridden
(the guard itself is tested in test_user_guard_hf1.py); `get_orch` is
monkeypatched on both the router and the shared component guard. The
orchestrator is a SimpleNamespace carrying a fake queue, a real IntentLog on
tmp_path and a spy kernel; the north-star meter is patched to a fixed payload
so the route test does not re-test compute_north_star.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import day_report as dr  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.routers import _component, report  # noqa: E402
from agents.core.routers._deps import user_guard  # noqa: E402
from agents.core.security.anchor import IntentLog  # noqa: E402

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
NOW = datetime.now().astimezone()


def _task(i, status="done", title="cleaned the downloads folder"):
    when = (NOW - timedelta(hours=1)).isoformat()
    return SimpleNamespace(
        id=i, agent="ops", kind="fs.clean", title=title, payload={"token": SECRET}, risk_tier=1,
        status=status, autonomy_level="ask", origin="generated", attempts=1,
        result={"echo": SECRET}, decided_by="owner", decision=None, pushed=0,
        created_at=when, updated_at=when,
    )


class _Queue:
    def __init__(self, tasks):
        self._tasks = tasks

    def list(self, status=None, origin=None, limit=100):
        return [t for t in self._tasks if status is None or t.status == status][:limit]


class _Kernel:
    def __init__(self, verdict=Verdict.GRANT, reason="ok"):
        self.calls = []
        self.verdict, self.reason = verdict, reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self.verdict, reason=self.reason)


def _orch(tmp_path, *, tasks=None, intent_log=True, queue=True):
    log = IntentLog(tmp_path / "intent_log.json", secret_key="k") if intent_log else None
    if log is not None:
        log.record("kernel", "authorize:call.outbound", "grant:allowed",
                   metadata={"verdict": "grant", "tier": 2, "scope": "global", "agent": "jarvis"})
    settings = {"autonomy.night_start": 23, "autonomy.night_end": 6}
    return SimpleNamespace(
        autonomy_queue=_Queue(tasks if tasks is not None else [_task(1)]) if queue else None,
        intent_log=log,
        llm_router=SimpleNamespace(active_model="qwen3-8b", name="lmstudio"),
        get_setting=lambda k, d=None: settings.get(k, d),
        run_history=None, tracer=None, autonomy=None, attention_ledger=None,
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(report.router)
    app.dependency_overrides[user_guard] = lambda: None
    state = {"orch": _orch(tmp_path), "kernel": _Kernel()}
    monkeypatch.setattr(report, "get_orch", lambda: state["orch"])
    monkeypatch.setattr(_component, "get_orch", lambda: state["orch"])
    monkeypatch.setattr(
        "agents.core.observability.north_star.compute_north_star",
        lambda queue, *a, **k: {
            "days": 1,
            "north_star": {"accepted_per_active_user": 1.0, "total_accepted": 1, "active_users": 1},
            "night_shift": {"done": 0, "pct": 0.0, "window": [23, 6]},
            "counter_metrics": {"interrupt_rate_per_day": 0.0, "reject_rate": 0.0,
                                "local_pct": 100.0, "p95_latency_ms": None},
            "guardrails_ok": True,
        },
    )
    monkeypatch.setattr(report, "_exporter", lambda orch, authorizer=None: dr.DayReportExporter(
        tmp_path / "reports", authorizer=state["kernel"]))
    c = TestClient(app)
    c.state_ = state
    c.reports_dir = tmp_path / "reports"
    yield c


# ── GET /api/report/today ────────────────────────────────────────────────────

def test_today_returns_the_allow_listed_payload_free_report(client):
    r = client.get("/api/report/today")
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("no-cache")
    body = r.json()
    assert set(body) == dr.REPORT_KEYS
    assert body["counts"]["accepted"] == 1 and body["empty"] is False
    assert body["model"] == {"name": "qwen3-8b", "backend": "lmstudio"}
    assert body["north_star"]["local_pct"] == 100.0
    assert SECRET not in r.text and "payload" not in r.text and "result" not in r.text


def test_today_html_card_is_a_self_contained_page(client):
    r = client.get("/api/report/today", params={"format": "html"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"].startswith("no-cache")
    assert "NERVA · TODAY" in r.text and "<script" not in r.text and SECRET not in r.text
    assert client.get("/api/report/today", params={"format": "pdf"}).status_code == 422


def test_today_is_honest_when_the_queue_is_missing_and_503_without_orch(client):
    client.state_["orch"] = _orch(client.reports_dir.parent, queue=False)
    body = client.get("/api/report/today").json()
    assert body["empty"] is True and body["sources"]["queue"] is False
    assert body["north_star"] is None
    client.state_["orch"] = None
    assert client.get("/api/report/today").status_code == 503


# ── POST /api/report/today/export ────────────────────────────────────────────

def test_export_writes_under_reports_and_returns_the_fingerprint(client):
    r = client.post("/api/report/today/export", json={"format": "html"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["format"] == "html"
    path = Path(body["path"])
    assert path.parent == client.reports_dir.resolve() and path.exists()
    assert body["fingerprint"] == client.get("/api/report/today").json()["fingerprint"]
    assert SECRET not in path.read_text(encoding="utf-8")
    # default format is json; an empty / malformed body is tolerated
    r2 = client.post("/api/report/today/export", content=b"not json",
                     headers={"content-type": "application/json"})
    assert r2.status_code == 200 and r2.json()["format"] == "json"


def test_export_refuses_a_bad_format_before_building_anything(client):
    r = client.post("/api/report/today/export", json={"format": "pdf"})
    assert r.status_code == 400 and r.json() == {"ok": False, "reason": "invalid_format"}
    assert not client.reports_dir.exists()


def test_export_crosses_the_kernel_and_surfaces_a_refusal(client, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    client.state_["kernel"] = _Kernel(Verdict.DENY, "kill-switch engaged")
    r = client.post("/api/report/today/export", json={"format": "json"})
    assert r.status_code == 403
    assert r.json() == {"ok": False, "reason": "kernel_denied:kill-switch engaged"}
    assert not client.reports_dir.exists()
    action = client.state_["kernel"].calls[0]
    assert action.kind == "report.export"

    client.state_["kernel"] = _Kernel(Verdict.QUEUE, "ask")
    r = client.post("/api/report/today/export", json={"format": "json"})
    assert r.status_code == 403 and r.json()["reason"] == "approval_required"

    client.state_["kernel"] = _Kernel(Verdict.GRANT)
    assert client.post("/api/report/today/export", json={"format": "json"}).status_code == 200


def test_export_503_without_orch(client):
    client.state_["orch"] = None
    assert client.post("/api/report/today/export", json={}).status_code == 503


# ── GET /api/report/receipt/{audit_id} ───────────────────────────────────────

def test_receipt_renders_a_verified_card_for_a_real_entry(client):
    r = client.get("/api/report/receipt/1")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == dr.RECEIPT_KEYS
    assert body["verified"] is True and body["chain"]["ok"] is True
    assert body["decision"]["verdict"] == "grant" and body["signed"] is True
    assert body["action"] == "authorize:call.outbound"


def test_receipt_refusals_are_named(client):
    assert client.get("/api/report/receipt/abc").status_code == 400
    assert client.get("/api/report/receipt/abc").json() == {"error": "bad_audit_id"}
    assert client.get("/api/report/receipt/0").status_code == 400
    assert client.get("/api/report/receipt/42").status_code == 404
    assert client.get("/api/report/receipt/42").json() == {"error": "not_found"}
    client.state_["orch"] = _orch(client.reports_dir.parent / "b", intent_log=False)
    r = client.get("/api/report/receipt/1")
    assert r.status_code == 503 and r.json() == {"error": "intent log not available"}


def test_receipt_goes_unverified_when_the_log_is_tampered(client):
    log = client.state_["orch"].intent_log
    log._entries[0]["why"] = "grant:something else"
    log._save()
    body = client.get("/api/report/receipt/1").json()
    assert body["verified"] is False and body["reason"] == "chain_broken:1"


def test_routes_are_user_guarded():
    guarded = {r.path: r for r in report.router.routes}
    assert set(guarded) == {"/api/report/today", "/api/report/today/export",
                            "/api/report/receipt/{audit_id}"}
    for route in guarded.values():
        assert any(d.dependency is user_guard for d in route.dependencies), route.path


def test_export_result_is_json_serialisable_and_carries_no_task_fields(client):
    body = client.post("/api/report/today/export", json={"format": "json"}).json()
    on_disk = json.loads(Path(body["path"]).read_text(encoding="utf-8"))
    assert set(on_disk) == dr.REPORT_KEYS
    for row in on_disk["actions"]:
        assert set(row) == dr.ACTION_KEYS
