"""Admin-only projection of verified task-mediation evidence."""

import asyncio
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.queue import TaskQueue, TaskQueueError

_ADMIN = "mediation-status-test-admin"
_HEADERS = {"X-Admin-Token": _ADMIN}
_COUNTS = {
    "authorized_enqueue": 2,
    "governed": 3,
    "refused_unmediated": 4,
    "ungoverned_detected": 5,
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _ADMIN)
    monkeypatch.setattr(web, "get_token_store", lambda: SimpleNamespace(
        verify=lambda _token: None,
        env_revoked=lambda _scope: False,
        list_tokens=lambda: [],
    ))
    monkeypatch.setattr(web, "orch", None)
    return TestClient(web.app)


def _queue_orch(monkeypatch, queue):
    monkeypatch.setattr(web, "orch", SimpleNamespace(autonomy_queue=queue))


def _assert_generic_unavailable(response):
    assert response.status_code == 503
    assert response.json() == {"error": "mediation status unavailable"}
    assert "no-store" in response.headers["cache-control"]


def test_admin_guard_is_required_before_queue_verification(client, monkeypatch):
    queue = SimpleNamespace(
        mediation_mode="enforce",
        verified_mediation_stats=Mock(return_value={"valid": True, **_COUNTS}),
    )
    _queue_orch(monkeypatch, queue)
    assert client.get("/autonomy/mediation").status_code == 401
    assert client.get("/autonomy/mediation", headers={"X-User-Token": _ADMIN}).status_code == 401
    assert queue.verified_mediation_stats.call_count == 0
    response = client.get("/autonomy/mediation", headers=_HEADERS)
    assert response.status_code == 200
    queue.verified_mediation_stats.assert_called_once_with()


@pytest.mark.parametrize("mode", ["off", "hold", "enforce"])
def test_exact_valid_projection_drops_internal_values(client, monkeypatch, mode):
    queue = SimpleNamespace(
        mediation_mode=mode,
        verified_mediation_stats=Mock(return_value={
            "valid": True, **_COUNTS, "private_receipt": "do-not-report",
        }),
    )
    _queue_orch(monkeypatch, queue)
    response = client.get("/autonomy/mediation", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"mode": mode, "valid": True, "stats": _COUNTS}
    assert "no-store" in response.headers["cache-control"]
    queue.verified_mediation_stats.assert_called_once_with()


def test_invalid_evidence_never_exposes_placeholder_counts(client, monkeypatch):
    queue = SimpleNamespace(
        mediation_mode="hold",
        verified_mediation_stats=Mock(return_value={"valid": False, **_COUNTS}),
    )
    _queue_orch(monkeypatch, queue)
    response = client.get("/autonomy/mediation", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"mode": "hold", "valid": False, "stats": None}


def test_verifier_runs_without_an_event_loop_and_openapi_declares_response(client, monkeypatch):
    def verified():
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return {"valid": True, **_COUNTS}

    _queue_orch(monkeypatch, SimpleNamespace(
        mediation_mode="off", verified_mediation_stats=verified,
    ))
    assert client.get("/autonomy/mediation", headers=_HEADERS).status_code == 200

    operation = client.get("/openapi.json").json()["paths"]["/autonomy/mediation"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/MediationStatus"}
    definitions = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(definitions["MediationCounts"]["required"]) == set(_COUNTS)
    assert set(definitions["MediationStatus"]["required"]) == {"mode", "valid", "stats"}


@pytest.mark.parametrize("snapshot", [
    None,
    [],
    {"valid": "yes", **_COUNTS},
    {"valid": True, **{**_COUNTS, "governed": True}},
    {"valid": True, **{**_COUNTS, "governed": -1}},
    {"valid": True, **{**_COUNTS, "governed": 1.5}},
    {"valid": True, **{k: v for k, v in _COUNTS.items() if k != "governed"}},
])
def test_malformed_verified_snapshot_is_unavailable(client, monkeypatch, snapshot):
    _queue_orch(monkeypatch, SimpleNamespace(
        mediation_mode="enforce",
        verified_mediation_stats=Mock(return_value=snapshot),
    ))
    _assert_generic_unavailable(client.get("/autonomy/mediation", headers=_HEADERS))


def test_missing_queue_bad_mode_and_verifier_exception_are_generic(client, monkeypatch):
    _assert_generic_unavailable(client.get("/autonomy/mediation", headers=_HEADERS))
    _queue_orch(monkeypatch, SimpleNamespace(autonomy_queue=None))
    _assert_generic_unavailable(client.get("/autonomy/mediation", headers=_HEADERS))
    for mode, verifier in [
        ("unknown", Mock(return_value={"valid": True, **_COUNTS})),
        ("enforce", Mock(side_effect=RuntimeError("secret path and signature"))),
    ]:
        _queue_orch(monkeypatch, SimpleNamespace(
            mediation_mode=mode, verified_mediation_stats=verifier,
        ))
        response = client.get("/autonomy/mediation", headers=_HEADERS)
        _assert_generic_unavailable(response)
        assert "secret path" not in response.text


def test_real_signed_queue_read_then_tamper_hides_counts_without_writes(client, monkeypatch, tmp_path):
    head = {"value": None}

    def compare_and_swap(expected, replacement):
        if head["value"] != expected:
            return False
        head["value"] = replacement
        return True

    signer = DetachedHMACSigner(
        lambda payload: hmac.new(b"mediation-status-test-key", payload, hashlib.sha256).hexdigest(),
    )
    queue = TaskQueue(
        str(tmp_path / "mediation.db"), mediation_mode="enforce",
        mediation_signer=signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head["value"], compare_and_swap),
        mediation_classifier=lambda _kind: True,
    ).initialize()
    try:
        with pytest.raises(TaskQueueError, match="requires mediation"):
            queue.enqueue("ultron", "filesystem.write", "Refused unmediated write")
        _queue_orch(monkeypatch, queue)
        before = queue._conn.total_changes
        head_before = head["value"]
        response = client.get("/autonomy/mediation", headers=_HEADERS)
        assert response.status_code == 200
        assert response.json() == {
            "mode": "enforce", "valid": True,
            "stats": {**dict.fromkeys(_COUNTS, 0), "refused_unmediated": 1},
        }
        assert queue._conn.total_changes == before
        assert head["value"] == head_before

        queue._conn.execute("UPDATE task_mediation_events SET signature=?", ("0" * 64,))
        queue._conn.commit()
        before = queue._conn.total_changes
        invalid = client.get("/autonomy/mediation", headers=_HEADERS)
        assert invalid.status_code == 200
        assert invalid.json() == {"mode": "enforce", "valid": False, "stats": None}
        assert queue._conn.total_changes == before
        assert head["value"] == head_before
    finally:
        queue.close()
