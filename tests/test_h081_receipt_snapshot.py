"""Owner delivery receipts are bounded and describe the shared database truth."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agents.core.channels import delivery_ledger
from agents.core.channels.delivery_ledger import ReliabilityStore


def test_dead_target_authority_follows_another_connection(tmp_path):
    first = ReliabilityStore(tmp_path / "shared.sqlite")
    second = ReliabilityStore(tmp_path / "shared.sqlite")
    assert first.mark_dead("telegram", "123", "forbidden")
    assert second.is_dead("telegram", "123")
    assert second.stats()["dead_targets"] == 1
    refused = second.open_delivery("telegram", "123", "body", key="reply:1")
    assert not refused.send and refused.dead
    assert second.clear_dead("telegram", "123")
    assert not first.is_dead("telegram", "123")
    assert first.stats()["dead_targets"] == 0
    assert first.open_delivery("telegram", "123", "body", key="reply:2").send


def test_receipt_snapshot_is_one_read_version(tmp_path, monkeypatch):
    first = ReliabilityStore(tmp_path / "shared.sqlite")
    second = ReliabilityStore(tmp_path / "shared.sqlite")
    original_stats = first.stats

    def stats_then_concurrent_mark():
        result = original_stats()
        assert second.mark_dead("telegram", "123", "forbidden")
        return result

    monkeypatch.setattr(first, "stats", stats_then_concurrent_mark)
    view = first.receipt_snapshot(limit=50, dead_limit=200)
    assert view["stats"]["dead_targets"] == 0
    assert view["dead_targets"] == []
    assert view["dead_targets_truncated"] is False
    assert second.stats()["dead_targets"] == 1


def test_http_receipt_view_is_admin_only_bounded_and_body_free(tmp_path, monkeypatch):
    from agents import web

    store = ReliabilityStore(tmp_path / "shared.sqlite")
    for index in range(205):
        store.mark_dead("telegram", str(1000 + index), "forbidden")
    sent = store.open_delivery("telegram", "42", "private message body", key="private:key")
    assert sent.attempting_checked()
    sent.finished(True)
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    client = TestClient(web.app)
    assert client.get("/api/channels/deliveries").status_code == 401
    response = client.get("/api/channels/deliveries?limit=50", headers={"x-admin-token": "secret"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    view = response.json()
    assert len(view["dead_targets"]) == 200
    assert view["dead_targets_truncated"] is True
    assert view["stats"]["dead_targets"] == 205
    assert view["retention"] == {
        "window_seconds": delivery_ledger.IDEMPOTENCY_WINDOW_S,
        "protected_limit": delivery_ledger.MAX_PROTECTED_KEYED_ROWS,
        "protected_count": 1,
        "retention_seconds": delivery_ledger.RETENTION_S,
        "ordinary_row_limit": delivery_ledger.MAX_ROWS,
    }
    assert view["deliveries"][0]["state"] == "sent"
    assert view["deliveries"][0]["keyed"] is True
    assert "private message body" not in response.text
    assert "private:key" not in response.text


def test_http_unavailable_store_is_an_error(tmp_path, monkeypatch):
    from agents import web

    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    response = TestClient(web.app).get(
        "/api/channels/deliveries", headers={"x-admin-token": "secret"})
    assert response.status_code == 503
    assert response.json() == {"error": "delivery ledger unavailable"}
