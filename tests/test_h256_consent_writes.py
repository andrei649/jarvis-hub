"""H256: consent writers refuse a damaged settings store before audit or grant."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.llm import data_handling as dh
from tests.test_h513_data_handling import Audit, router


@pytest.fixture
def consent(tmp_path, monkeypatch):
    from agents.core.autonomy import approval_judge

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(settings_db, "_change_listeners", [])
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-h256-key")
    target = SimpleNamespace(
        target_id="role:approval_judge", provider="openai-compatible", model="judge-model",
        mode="dedicated", policy="unknown", note="Unverified terms",
        binding=("judge-wire", "openai-compatible", "judge-model", "dedicated"),
    )
    monkeypatch.setattr(approval_judge, "describe_data_target", lambda *a, **k: target)
    configured = router()
    provider_row = dh.posture(configured)["providers"][0]
    return SimpleNamespace(router=configured, provider=provider_row, target=target)


def _action(case, kind, grant, audit):
    if kind == "provider":
        row = case.provider
        return dh.acknowledge(case.router, row["provider"], grant, row["scope"], audit)
    return dh.acknowledge(case.router, case.target.provider, grant,
                          dh.role_target_scope(case.target), audit, target=case.target.target_id)


def _raw_consent(kind):
    key = "data_training_ack" if kind == "provider" else "data_training_role_ack"
    conn = settings_db.get_conn()
    try:
        return conn.execute("SELECT value FROM settings WHERE category='security' AND key=?", (key,)).fetchone()[0]
    finally:
        conn.close()


def _damage(column):
    conn = settings_db.get_conn()
    try:
        original = conn.execute(
            f"SELECT {column} FROM settings WHERE category='security' AND key='guardrails_mode'"
        ).fetchone()[0]
        conn.execute(
            f"UPDATE settings SET {column}=? WHERE category='security' AND key='guardrails_mode'",
            ("{",),
        )
        conn.commit()
        return original
    finally:
        conn.close()


def _repair(column, original):
    conn = settings_db.get_conn()
    try:
        conn.execute(
            f"UPDATE settings SET {column}=? WHERE category='security' AND key='guardrails_mode'",
            (original,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["provider", "role"])
@pytest.mark.parametrize("grant", [False, True])
@pytest.mark.parametrize("column", ["value", "opts"])
def test_unrelated_invalid_json_refuses_consent_before_audit_or_listener(consent, kind, grant, column):
    if not grant:
        _action(consent, kind, True, Audit())  # a real grant must survive a refused revoke
    before = _raw_consent(kind)
    changes = []
    settings_db.on_change(lambda *args: changes.append(args))
    audit = Audit()
    original = _damage(column)

    with pytest.raises(dh.ConsentUnavailable):
        _action(consent, kind, grant, audit)

    assert _raw_consent(kind) == before
    assert audit.rows == [] and changes == []
    _repair(column, original)
    assert _action(consent, kind, grant, audit)["ok"] is True
    assert len(audit.rows) == len(changes) == 1


@pytest.mark.parametrize("kind", ["provider", "role"])
def test_corruption_between_preflight_and_write_lock_still_refuses(consent, kind, monkeypatch):
    before = _raw_consent(kind)
    changes = []
    settings_db.on_change(lambda *args: changes.append(args))
    audit = Audit()
    real_get_conn = settings_db.get_conn
    damaged = []

    def race_get_conn():
        if not damaged:
            damaged.append(True)
            conn = real_get_conn()
            try:
                conn.execute("UPDATE settings SET opts='{' WHERE category='security' AND key='guardrails_mode'")
                conn.commit()
            finally:
                conn.close()
        return real_get_conn()

    monkeypatch.setattr(settings_db, "get_conn", race_get_conn)
    with pytest.raises(dh.ConsentUnavailable):
        _action(consent, kind, True, audit)
    assert damaged and _raw_consent(kind) == before
    assert audit.rows == [] and changes == []
