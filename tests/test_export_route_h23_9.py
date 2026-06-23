"""H23.9 — the data export has an HTTP surface (POST /api/admin/export).

The export_data() logic is covered by test_data_export.py; this pins the new
admin-guarded route: it is classified 'admin' in the parity snapshot and, when
invoked, returns the portable manifest (user-content DBs only, no secrets).
"""
import json
import sqlite3
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import _deps


def test_export_route_is_admin_guarded():
    snap = json.loads((repo_root / "tests" / "_snapshots" / "route_auth.json").read_text())
    assert snap.get("POST /api/admin/export") == "admin"


def test_export_route_returns_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    # Seed a user-content DB so the export has something to dump.
    conn = sqlite3.connect(str(tmp_path / "notes.db"))
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO notes (v) VALUES ('hello')")
    conn.commit()
    conn.close()

    web.app.dependency_overrides[_deps.admin_guard] = lambda: None
    try:
        client = TestClient(web.app)
        resp = client.post("/api/admin/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "export" in body and "row_counts" in body
        assert body["row_counts"].get("notes.db") == 1
        assert Path(body["export"]).exists()
    finally:
        web.app.dependency_overrides.pop(_deps.admin_guard, None)
