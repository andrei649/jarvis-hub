"""Persistent company workspace and credential isolation."""

import json

from agents.core.business.store import BusinessStore


def test_profile_and_connection_survive_restart_without_plaintext_credentials(tmp_path):
    first = BusinessStore(tmp_path)
    assert first.profile()["local_only"] is True
    first.update_profile({"name": "Acme", "industry": "services", "currency": "EUR", "local_only": True})
    connection = first.add_connection("hubspot", "Sales", "https://api.hubapi.com", {"access_token": "SECRET-123"})
    assert "SECRET-123" not in json.dumps(connection)
    assert "SECRET-123" not in (tmp_path / "business.db").read_bytes().decode("latin1")
    second = BusinessStore(tmp_path)
    assert second.profile()["name"] == "Acme"
    assert second.credentials(connection["id"]) == {"access_token": "SECRET-123"}
    assert "SECRET-123" not in json.dumps(second.list_connections())


def test_failed_sync_keeps_previous_snapshot_and_marks_stale(tmp_path):
    store = BusinessStore(tmp_path)
    connection = store.add_connection("hubspot", "Sales", "https://api.hubapi.com", {"access_token": "secret"})
    snapshot = {"records": {"orders": [], "products": [], "deals": [{"id": "d1", "amount": "9", "currency": "EUR", "stage": "won", "name": "One"}]}, "complete": True, "coverage": "all"}
    store.replace_snapshot(connection["id"], snapshot)
    store.mark_sync_error(connection["id"], "Provider unavailable")
    assert store.get_connection(connection["id"])["status"] == "stale"
    assert store.get_connection(connection["id"])["error"] == "Provider unavailable"
    assert store.snapshots()[0]["records"]["deals"][0]["id"] == "d1"


def test_snapshot_replacement_rolls_back_on_invalid_record(tmp_path):
    store = BusinessStore(tmp_path)
    cid = store.add_connection("csv", "Import", "", {})["id"]
    original = {"records": {"orders": [{"id": "one"}], "products": [], "deals": []}, "complete": True, "coverage": "one row"}
    store.replace_snapshot(cid, original)
    broken = {"records": {"orders": [{"id": "two"}, object()], "products": [], "deals": []}, "complete": True, "coverage": "two rows"}
    try:
        store.replace_snapshot(cid, broken)
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("invalid snapshot was accepted")
    assert store.snapshots()[0]["records"]["orders"] == [{"id": "one"}]


def test_reports_and_activity_are_bounded(tmp_path):
    store = BusinessStore(tmp_path)
    report = {"workflow_id": "sales_overview", "title": "Sales", "summary": "Summary", "metrics": {}, "rows": [], "coverage": [], "warnings": []}
    for _ in range(110):
        store.save_report(report)
    assert len(store.list_reports()) <= 100
    assert len(store.list_activity()) <= 200


def test_connection_count_is_bounded(tmp_path):
    store = BusinessStore(tmp_path)
    for number in range(100):
        store.add_connection("csv", f"Import {number}", "", {})
    try:
        store.add_connection("csv", "Too many", "", {})
    except ValueError:
        pass
    else:
        raise AssertionError("connection limit was ignored")
    assert len(store.list_connections()) == 100
