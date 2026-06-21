"""Regression tests for GET /api/admin/audit (audit-log page).

Pins the behavior of the audit-log endpoint after the A4 hardening pass moved its
blocking sqlite read onto a worker thread (`asyncio.to_thread`): the response shape,
row ordering (newest first), pagination, table fallback, and the empty-db case must be
unchanged. Fully offline — seeds a temp sqlite db and points the route at it.
"""
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


AUTH = {"X-Admin-Token": "test-secret"}


def _seed(db_path: Path, table: str, rows: list[tuple]) -> None:
    """Create `table` with the columns the route selects and insert `rows`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"CREATE TABLE {table} (timestamp TEXT, event_type TEXT, "
            "content_preview TEXT, findings_json TEXT)"
        )
        conn.executemany(
            f"INSERT INTO {table} (timestamp, event_type, content_preview, findings_json) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _point_route_at(monkeypatch, db_path: Path) -> None:
    from agents.core.routers import admin
    monkeypatch.setattr(admin, "data_path", lambda *parts: db_path)


def test_audit_returns_rows_newest_first(token_client, monkeypatch, tmp_path):
    db = tmp_path / "audit.db"
    _seed(db, "audit_events", [
        ("2026-01-01T00:00:00", "scan", "first", "{}"),
        ("2026-01-02T00:00:00", "scan", "second", "{}"),
        ("2026-01-03T00:00:00", "block", "third", "{}"),
    ])
    _point_route_at(monkeypatch, db)

    resp = token_client.get("/api/admin/audit", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    # rowid DESC → most-recently-inserted first.
    summaries = [r["summary"] for r in data["rows"]]
    assert summaries == ["third", "second", "first"]
    assert {"timestamp", "event_type", "summary", "details"} <= set(data["rows"][0])


def test_audit_pagination(token_client, monkeypatch, tmp_path):
    db = tmp_path / "audit.db"
    _seed(db, "audit_events", [
        (f"2026-01-{i:02d}T00:00:00", "scan", f"row{i}", "{}") for i in range(1, 6)
    ])
    _point_route_at(monkeypatch, db)

    page1 = token_client.get("/api/admin/audit?page=1&limit=2", headers=AUTH).json()
    page2 = token_client.get("/api/admin/audit?page=2&limit=2", headers=AUTH).json()
    page3 = token_client.get("/api/admin/audit?page=3&limit=2", headers=AUTH).json()
    assert page1["total"] == page2["total"] == 5
    assert [r["summary"] for r in page1["rows"]] == ["row5", "row4"]
    assert [r["summary"] for r in page2["rows"]] == ["row3", "row2"]
    assert [r["summary"] for r in page3["rows"]] == ["row1"]  # last page, partial


def test_audit_falls_back_to_security_events_table(token_client, monkeypatch, tmp_path):
    db = tmp_path / "audit.db"
    _seed(db, "security_events", [("2026-01-01T00:00:00", "pii", "redacted", "{}")])
    _point_route_at(monkeypatch, db)

    data = token_client.get("/api/admin/audit", headers=AUTH).json()
    assert data["total"] == 1
    assert data["rows"][0]["summary"] == "redacted"


def test_audit_empty_when_db_missing(token_client, monkeypatch, tmp_path):
    _point_route_at(monkeypatch, tmp_path / "does-not-exist.db")
    data = token_client.get("/api/admin/audit", headers=AUTH).json()
    assert data == {"page": 1, "limit": 50, "total": 0, "rows": []}
