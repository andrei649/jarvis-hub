"""V62 — bounded owner pagination over the complete saved-session list."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core.checkpoint import CheckpointManager  # noqa: E402


@pytest.fixture
def cp(tmp_path):
    manager = CheckpointManager(str(tmp_path / "checkpoints.db"))
    manager.initialize()
    yield manager
    manager.close()


def _client(monkeypatch, cp, *, remote=False):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions

    monkeypatch.setattr(sessions, "get_orch", lambda: SimpleNamespace(checkpoints=cp))
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    return TestClient(web.app, client=("192.0.2.10", 4000) if remote else ("127.0.0.1", 4000))


def _seed(cp, count=27):
    for index in range(count):
        sid = f"session-{index:02d}"
        cp.create_session_record(sid)
        # Deliberate ties prove the id is the stable second ordering key.
        started = f"2026-11-{1 + index // 3:02d}T10:00:00+00:00"
        with cp._lock:
            cp._conn.execute("UPDATE sessions SET started_at=? WHERE id=?", (started, sid))
        cp._conn.commit()


def test_owner_page_endpoint_is_additive_and_lists_beyond_legacy_twenty(cp, monkeypatch):
    _seed(cp)
    client = _client(monkeypatch, cp)

    legacy = client.get("/sessions")
    assert legacy.status_code == 200
    assert len(legacy.json()["sessions"]) == 20

    first = client.get("/sessions/page", params={"limit": 7})
    assert first.status_code == 200
    body = first.json()
    assert len(body["sessions"]) == 7
    assert body["next_cursor"]
    all_rows = list(body["sessions"])
    cursor = body["next_cursor"]
    while cursor:
        page = client.get("/sessions/page", params={"limit": 7, "cursor": cursor})
        assert page.status_code == 200
        next_body = page.json()
        all_rows.extend(next_body["sessions"])
        cursor = next_body["next_cursor"]

    assert [row["id"] for row in all_rows] == [f"session-{i:02d}" for i in range(26, -1, -1)]
    assert len({row["id"] for row in all_rows}) == 27


def test_page_applies_archived_and_continuation_filters_before_limit(cp, monkeypatch):
    _seed(cp, 6)
    # The newest row is a continued part and must not consume a visible page slot.
    from agents.core.session_continuation import ContinuationStore

    child = ContinuationStore(cp).create(
        "session-05", "00000000-0000-4000-8000-000000000123",
        [{"role": "user", "content": "Continue", "timestamp": datetime.now(UTC).isoformat(),
          "token_count": 1}],
        cp.clock_snapshot("session-05"),
    )["session_id"]
    assert cp.set_archived("session-04", True)
    client = _client(monkeypatch, cp)

    live = client.get("/sessions/page", params={"limit": 2}).json()["sessions"]
    assert [row["id"] for row in live] == [child, "session-03"]
    archived = client.get("/sessions/page", params={"archived": "true", "limit": 2}).json()["sessions"]
    assert [row["id"] for row in archived] == ["session-04"]


@pytest.mark.parametrize("cursor", ["!", "e30", "eyJ2IjoxfQ", "a" * 513])
def test_malformed_cursor_fails_closed(cp, monkeypatch, cursor):
    response = _client(monkeypatch, cp).get("/sessions/page", params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_cursor"


def test_cursor_cannot_be_reused_for_different_archive_view(cp, monkeypatch):
    _seed(cp)
    client = _client(monkeypatch, cp)
    cursor = client.get("/sessions/page", params={"limit": 1}).json()["next_cursor"]
    response = client.get("/sessions/page", params={"archived": "true", "cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_cursor"


def test_page_endpoint_requires_owner_authentication(cp, monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "owner-secret")
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions

    monkeypatch.setattr(sessions, "get_orch", lambda: SimpleNamespace(checkpoints=cp))
    response = TestClient(web.app, client=("192.0.2.10", 4000)).get("/sessions/page")
    assert response.status_code in (401, 403)


def test_user_credential_cannot_read_owner_page_but_admin_can(cp, monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "owner-secret")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "guest-secret")
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions

    monkeypatch.setattr(sessions, "get_orch", lambda: SimpleNamespace(checkpoints=cp))
    client = TestClient(web.app, client=("192.0.2.10", 4000))
    denied = client.get("/sessions/page", headers={"X-User-Token": "guest-secret"})
    assert denied.status_code in (401, 403)
    allowed = client.get("/sessions/page", headers={"X-Admin-Token": "owner-secret"})
    assert allowed.status_code == 200


def test_cursor_is_a_boundary_not_a_reference_to_a_live_row(cp, monkeypatch):
    _seed(cp)
    client = _client(monkeypatch, cp)
    first = client.get("/sessions/page", params={"limit": 3}).json()
    cursor = first["next_cursor"]
    boundary_id = first["sessions"][-1]["id"]
    with cp._lock:
        cp._conn.execute("DELETE FROM sessions WHERE id=?", (boundary_id,))
        cp._conn.execute("INSERT INTO sessions(id,started_at,metadata) VALUES(?,?,?)",
                          ("newer-arrival", "2026-12-01T00:00:00+00:00", "{}"))
        cp._conn.commit()
    second = client.get("/sessions/page", params={"limit": 3, "cursor": cursor})
    assert second.status_code == 200
    ids = [row["id"] for row in second.json()["sessions"]]
    assert boundary_id not in ids
    assert "newer-arrival" not in ids
    assert ids == ["session-23", "session-22", "session-21"]


def test_null_timestamps_are_paginated_after_dated_rows_by_id(cp, monkeypatch):
    _seed(cp, 5)
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET started_at=NULL WHERE id IN (?,?)",
                         ("session-01", "session-03"))
        cp._conn.commit()
    client = _client(monkeypatch, cp)
    rows = []
    cursor = None
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/sessions/page", params=params).json()
        rows.extend(row["id"] for row in body["sessions"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert rows == ["session-04", "session-02", "session-00", "session-03", "session-01"]


@pytest.mark.parametrize("limit", [0, 101])
def test_page_limit_is_bounded(cp, monkeypatch, limit):
    assert _client(monkeypatch, cp).get("/sessions/page", params={"limit": limit}).status_code == 422


def test_closed_checkpoint_store_is_unavailable_not_exhausted(cp, monkeypatch):
    client = _client(monkeypatch, cp)
    cp.close()
    response = client.get("/sessions/page")
    assert response.status_code == 503
    assert response.json() == {"error": "session_page_unavailable"}


def test_page_success_and_cursor_errors_are_never_cached(cp, monkeypatch):
    client = _client(monkeypatch, cp)
    for params in ({}, {"cursor": "!"}):
        response = client.get("/sessions/page", params=params)
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("limit", [True, 0, 101, "20"])
def test_store_rejects_invalid_page_limits(cp, limit):
    with pytest.raises(ValueError, match="invalid session page limit"):
        cp.get_sessions_page(limit)
