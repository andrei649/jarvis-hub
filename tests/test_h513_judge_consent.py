"""Approval judge consent is a separate, audited configuration target."""
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.llm import data_handling as dh
from tests.test_h513_data_handling import Audit, router

TARGET = "role:approval_judge"
ROLE_SETTING = ("security", "data_training_role_ack")


@pytest.fixture
def configured(tmp_path, monkeypatch):
    from agents.core.autonomy import approval_judge
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-role-key")
    target = SimpleNamespace(target_id=TARGET, provider="openai-compatible", model="judge-model",
                             mode="dedicated", policy="unknown", note="Unverified account terms",
                             binding=("approval_judge-wire-v1", "openai-compatible", "judge-model", "dedicated",
                                      "https://user:private@synthetic.invalid/v1/?token=private", "Bearer private-key", "unknown", ()))
    current = [target]
    original_descriptor = approval_judge.describe_data_target
    monkeypatch.setattr(approval_judge, "describe_data_target", lambda *args, **kwargs: current[0], raising=False)
    return SimpleNamespace(router=router(), target=target, current=current, audit=Audit(),
                           _real_descriptor=original_descriptor)


def grant(configured):
    return dh.acknowledge(configured.router, configured.target.provider, True,
                          dh.role_target_scope(configured.target), configured.audit, target=TARGET)


def test_provider_and_judge_grants_are_isolated(configured):
    row = dh.posture(configured.router)["providers"][0]
    dh.acknowledge(configured.router, row["provider"], True, row["scope"], configured.audit)
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(configured.router, configured.target)
    dh.acknowledge(configured.router, row["provider"], False, row["scope"], configured.audit)
    assert grant(configured)["target"] == TARGET
    assert dh.authorize_role_target(configured.router, configured.target)["acknowledged"]
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize(configured.router, configured.router._compatible_backend, "synthetic-model", principal=Principal())


@pytest.mark.parametrize("field,value", [
    ("model", "new-model"), ("mode", "active"), ("policy", "trains-on-inputs"),
    ("binding", ("approval_judge-wire-v1", "new-endpoint-or-header")),
])
def test_target_changes_invalidate_grant(configured, field, value):
    old_scope = dh.role_target_scope(configured.target)
    grant(configured)
    setattr(configured.target, field, value)
    assert dh.role_target_scope(configured.target) != old_scope
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(configured.router, configured.target)
    with pytest.raises(dh.StaleAcknowledgment):
        dh.acknowledge(configured.router, configured.target.provider, True, old_scope, configured.audit, target=TARGET)


def test_target_scope_is_domain_separated_and_public_posture_has_no_binding(configured):
    import json
    scope = dh.role_target_scope(configured.target)
    row = dh.posture(configured.router)["targets"][0]
    assert row["target_id"] == TARGET and row["scope"] == scope
    assert row["label"] == "Approval judge"
    assert "private" not in json.dumps(row) and "Bearer" not in json.dumps(row)
    assert dh.posture(configured.router)["role_settings_readable"] is True
    assert scope != dh.posture(configured.router)["providers"][0]["scope"]


def test_safe_target_without_scope_does_not_record_configuration_usage(configured, monkeypatch):
    configured.target.policy = "local"
    def unavailable():
        raise RuntimeError("secret store unavailable")
    monkeypatch.setattr(dh, "_scope_key", unavailable)
    assert dh.authorize_role_target(configured.router, configured.target)["scope"] == ""
    assert not getattr(configured.router, "_data_handling_role_used", {})
    assert dh.posture(configured.router)["targets"][0]["last_used"] is None


def test_role_revoke_is_audited_and_does_not_revoke_provider(configured):
    provider = dh.posture(configured.router)["providers"][0]
    dh.acknowledge(configured.router, provider["provider"], True, provider["scope"], configured.audit)
    grant(configured)
    dh.acknowledge(configured.router, configured.target.provider, False,
                   dh.role_target_scope(configured.target), configured.audit, target=TARGET)
    assert configured.audit.rows[-1].action_taken == "model_training_consent_revoked"
    assert dh.posture(configured.router)["providers"][0]["acknowledged"]
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(configured.router, configured.target)


def test_failed_sql_write_after_audit_preserves_prior_role_grant(configured):
    grant(configured)
    original = settings_db.get_value(*ROLE_SETTING)
    conn = settings_db.get_conn()
    try:
        conn.execute("CREATE TRIGGER refuse_role_update BEFORE UPDATE ON settings "
                     "WHEN NEW.category='security' AND NEW.key='data_training_role_ack' "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(configured.router, configured.target.provider, False,
                       dh.role_target_scope(configured.target), configured.audit, target=TARGET)
    assert configured.audit.rows[-1].action_taken == "model_training_consent_revoked"
    assert settings_db.get_value(*ROLE_SETTING) == original


def test_posture_describes_real_role_without_constructing_clients(configured, monkeypatch):
    from agents.core.autonomy import approval_judge
    env = {"JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER": "openai-compatible",
           "JARVIS_ROLE_APPROVAL_JUDGE_MODEL": "judge-model",
           "JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL": "https://synthetic.invalid/v1",
           "JARVIS_ROLE_APPROVAL_JUDGE_KEY": "private-key"}
    # Restore the real pure descriptor while keeping every client constructor forbidden.
    original = configured._real_descriptor
    monkeypatch.setattr(approval_judge, "describe_data_target", lambda r: original(r, env=env))
    monkeypatch.setattr(approval_judge, "_backend_for", lambda *a, **kw: pytest.fail("posture constructed a client"))
    rows = dh.posture(configured.router)["targets"]
    assert len(rows) == 1 and rows[0]["model"] == "judge-model"


def test_audit_failure_and_postaudit_rotation_grant_nothing(configured):
    configured.audit.fail = True
    with pytest.raises(dh.ConsentUnavailable):
        grant(configured)
    assert settings_db.get_value(*ROLE_SETTING) == {}
    configured.audit.fail = False
    old_log = configured.audit.log
    def rotate(event):
        old_log(event)
        configured.target.model = "changed-during-audit"
    configured.audit.log = rotate
    with pytest.raises(dh.ConsentUnavailable):
        grant(configured)
    assert settings_db.get_value(*ROLE_SETTING) == {}


def test_role_store_is_finite_and_unreadability_does_not_disable_provider_rows(configured):
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?", ('{"other":"' + 'a' * 64 + '"}', *ROLE_SETTING))
        conn.commit()
    finally:
        conn.close()
    value = dh.posture(configured.router)
    assert value["role_settings_readable"] is False and value["settings_readable"] is True
    assert value["targets"][0]["can_acknowledge"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(configured.router, configured.target)


def test_missing_role_setting_disables_role_controls_without_disabling_providers(configured, monkeypatch):
    original = settings_db.read_setting
    monkeypatch.setattr(settings_db, "read_setting", lambda category, key:
                        (False, None) if (category, key) == ROLE_SETTING else original(category, key))
    value = dh.posture(configured.router)
    assert value["role_settings_readable"] is False and value["settings_readable"] is True
    assert value["targets"][0]["can_acknowledge"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(configured.router, configured.target)


def test_generic_settings_import_and_reset_cannot_grant_role_consent(configured):
    value = {"approval_judge": dh.role_target_scope(configured.target)}
    assert settings_db.route_only_problems("security", [ROLE_SETTING[1]])
    changes, errors = settings_db.plan_import({"settings": {"security": {ROLE_SETTING[1]: value}}})
    assert errors and not changes
    assert ROLE_SETTING[1] not in settings_db.plan_reset("security").get("security", {})


def test_admin_api_validates_target_provider_scope_and_preserves_old_request(configured, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "role-admin")
    monkeypatch.setattr(web, "orch", SimpleNamespace(llm_router=configured.router, audit=configured.audit))
    client = TestClient(web.app)
    body = {"provider": configured.target.provider, "scope": dh.role_target_scope(configured.target),
            "acknowledged": True, "target": TARGET}
    headers = {"X-Admin-Token": "role-admin"}
    assert client.post("/api/security/data-handling/ack", json=body).status_code in (401, 403)
    for extra, status in (({"target": "role:other"}, 422), ({"provider": "gemini"}, 422), ({"scope": "0" * 64}, 409)):
        assert client.post("/api/security/data-handling/ack", json={**body, **extra}, headers=headers).status_code == status
    response = client.post("/api/security/data-handling/ack", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["target"] == TARGET
    row = dh.posture(configured.router)["providers"][0]
    old = {"provider": row["provider"], "scope": row["scope"], "acknowledged": True}
    assert client.post("/api/security/data-handling/ack", json=old, headers=headers).status_code == 200
