"""The H067 session-command opt-out uses the governed permission ledger."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import permission_ledger as pl

KEY = "a" * 64


def _task(payload: dict, task_id: int, *, decided_by: str = "owner") -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        kind=pl.KIND,
        payload=payload,
        decided_by=decided_by,
        decision="accept",
        status="running",
        human_decision={"action": "accept", "by": decided_by},
    )


def _request(ledger: pl.PermissionLedger, key: str, scope: str = "always") -> tuple[int, dict]:
    queued: list[dict] = []

    def enqueue(**kwargs):
        queued.append(kwargs)
        return 71

    task_id = ledger.request("session_command", key, scope, "gateway", enqueue)
    assert len(queued) == 1
    assert queued[0]["kind"] == pl.KIND
    assert queued[0]["risk_tier"] == int(pl.RiskTier.EXTERNAL)
    assert queued[0]["autonomy_level"] == pl.ASK
    return task_id, queued[0]["payload"]


def test_session_command_key_is_exact_lowercase_digest():
    assert pl.normalize_key("session_command", KEY) == KEY
    for bad in (KEY.upper(), KEY[:-1], KEY + "0", "g" * 64, f" {KEY}", f"{KEY} ", None):
        assert pl.normalize_key("session_command", bad) == ""


def test_flag_off_new_consumer_asks_while_legacy_check_still_allows(tmp_path):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        assert ledger.check("session_command", KEY) == "allow"
        assert ledger.check_required("session_command", KEY) == "ask"
        assert ledger.check_required("session_command", "bad") == "deny"
        assert ledger.audit_rows() == []
    finally:
        ledger.close()


async def test_request_only_queues_and_human_approved_apply_grants(tmp_path):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        task_id, payload = _request(ledger, KEY)
        assert payload["key"] == KEY
        assert ledger.list_grants(include_inactive=True) == []
        assert ledger.check_required("session_command", KEY) == "ask"

        refused = await ledger.apply_grant(_task(payload, task_id, decided_by="policy"))
        assert refused["reason"] == "human_decision_required"
        assert ledger.check_required("session_command", KEY) == "ask"

        applied = await ledger.apply_grant(_task(payload, task_id))
        assert applied["status"] == "ok"
        assert applied["scope"] == "always"
        assert ledger.check_required("session_command", KEY) == "allow"
        assert [row["event"] for row in ledger.audit_rows()] == ["grant.applied", "grant.requested"]
    finally:
        ledger.close()


async def test_always_grant_survives_restart_and_revoke_restores_ask(tmp_path):
    path = tmp_path / "permissions.db"
    first = pl.PermissionLedger(path, enabled=False)
    try:
        task_id, payload = _request(first, KEY)
        grant_id = (await first.apply_grant(_task(payload, task_id)))["grant_id"]
    finally:
        first.close()

    restarted = pl.PermissionLedger(path, enabled=False)
    try:
        assert restarted.check_required("session_command", KEY) == "allow"
        assert restarted.revoke(grant_id).status == "revoked"
        assert restarted.check_required("session_command", KEY) == "ask"
    finally:
        restarted.close()


def test_never_entry_denies_required_check_and_cannot_be_requested(tmp_path):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        ledger.deny("session_command", KEY)
        assert ledger.check_required("session_command", KEY) == "deny"
        with pytest.raises(pl.PermissionRequestError, match="never_entry"):
            _request(ledger, KEY)
    finally:
        ledger.close()


@pytest.mark.parametrize("scope", ["once", "session", "never"])
async def test_session_command_rejects_non_always_scope(tmp_path, scope):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        with pytest.raises(pl.PermissionRequestError, match="scope_not_requestable"):
            _request(ledger, KEY, scope)
        payload = {
            "surface": "session_command",
            "key": KEY,
            "scope": scope,
            "requested_by": "gateway",
        }
        result = await ledger.apply_grant(_task(payload, 72))
        assert result["reason"] == "scope_not_requestable"
        assert ledger.list_grants(include_inactive=True) == []
    finally:
        ledger.close()


@pytest.mark.parametrize("key", ["A" * 64, "f" * 63, "z" * 64, " " + KEY])
async def test_session_command_rejects_invalid_key_on_both_widening_paths(tmp_path, key):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        with pytest.raises(pl.PermissionRequestError, match="invalid_key"):
            _request(ledger, key)
        payload = {
            "surface": "session_command",
            "key": key,
            "scope": "always",
            "requested_by": "gateway",
        }
        result = await ledger.apply_grant(_task(payload, 73))
        assert result["reason"] == "invalid_key"
        assert ledger.list_grants(include_inactive=True) == []
    finally:
        ledger.close()


async def test_required_check_consumes_legacy_once_grant_with_flag_off(tmp_path):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        queued: list[dict] = []

        def enqueue(**kwargs):
            queued.append(kwargs)
            return 74

        ledger.request("site", "example.com", "once", "browser", enqueue)
        result = await ledger.apply_grant(_task(queued[0]["payload"], 74))
        assert ledger.check_required("site", "example.com") == "allow"
        assert ledger.check_required("site", "example.com") == "ask"
        assert ledger.get(result["grant_id"]).status == "consumed"
    finally:
        ledger.close()


async def test_required_check_expires_legacy_session_grant_on_restart_with_flag_off(tmp_path):
    path = tmp_path / "permissions.db"
    first = pl.PermissionLedger(path, enabled=False)
    try:
        queued: list[dict] = []

        def enqueue(**kwargs):
            queued.append(kwargs)
            return 75

        first.request("site", "example.com", "session", "browser", enqueue)
        result = await first.apply_grant(_task(queued[0]["payload"], 75))
        assert first.check_required("site", "example.com") == "allow"
    finally:
        first.close()

    restarted = pl.PermissionLedger(path, enabled=False)
    try:
        assert restarted.check_required("site", "example.com") == "ask"
        assert restarted.get(result["grant_id"]).status == "expired"
    finally:
        restarted.close()


async def test_required_check_rejects_tampered_grant_fingerprint(tmp_path):
    ledger = pl.PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        task_id, payload = _request(ledger, KEY)
        grant_id = (await ledger.apply_grant(_task(payload, task_id)))["grant_id"]
        ledger._conn.execute("UPDATE grants SET requested_by='other' WHERE id=?", (grant_id,))
        ledger._conn.commit()
        with pytest.raises(ValueError, match="fingerprint mismatch"):
            ledger.check_required("session_command", KEY)
    finally:
        ledger.close()
