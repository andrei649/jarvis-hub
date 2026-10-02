"""Configured video candidates have independent, current, audited consent."""
import json
import os
from dataclasses import replace

import pytest

from agents.core import settings_db
from agents.core.llm import data_handling as dh
from agents.core.llm import video_policy as vp
from tests.test_h513_data_handling import Audit, router


def stored_roles(value):
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category=? AND key=?",
                     (json.dumps(value), *dh.ROLE_SETTING))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(settings_db, "_initialized", True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"synthetic-candidate-scope")
    monkeypatch.setattr(vp, "_scope_key", lambda: b"synthetic-candidate-scope")
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_MODEL", "primary-model")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_BASE_URL", "https://primary.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_KEY", "primary-secret")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "openai-compatible", "model": "fallback-one", "base_url": "https://one.example/v1"},
        {"provider": "openai-compatible", "model": "fallback-two", "base_url": "https://two.example/v1"},
    ]))
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "one-secret")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "two-secret")
    return router(), Audit()


def test_route_set_has_distinct_scopes_and_private_fixed_slot_keys(candidates):
    identities = vp.describe_video_route_set()
    assert [i.target_id for i in identities] == [
        "role:video_analysis", "role:video_fallback_1", "role:video_fallback_2"]
    assert [i.authorization for i in identities] == [
        "Bearer primary-secret", "Bearer one-secret", "Bearer two-secret"]
    assert len({dh.role_target_scope(i) for i in identities}) == 3
    assert vp.describe_video_data_target().binding == identities[0].binding
    assert vp.describe_video_data_target("role:video_fallback_2") == identities[2]
    assert vp.describe_video_data_target("role:video_fallback_3") is None
    with pytest.raises(vp.VideoPolicyRefused):
        vp.describe_video_data_target("role:unregistered")
    assert vp.describe_video_data_target("role:video_fallback_1").request_url == "https://one.example/v1/chat/completions"
    public = json.dumps(dh.posture(candidates[0])["targets"])
    assert "secret" not in public and "one.example" not in public
    assert "secret" not in repr(identities)


def test_independent_grants_revocation_and_other_role_preservation(candidates):
    owner_router, audit = candidates
    primary, first, second = vp.describe_video_route_set()
    previous = {"approval_judge": "a" * 64}
    stored_roles(previous)
    dh.acknowledge(owner_router, first.provider, True, dh.role_target_scope(first), audit, target=first.target_id)
    assert settings_db.get_value(*dh.ROLE_SETTING) == {
        **previous, "video_fallback_1": dh.role_target_scope(first)}
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(owner_router, second, actual_use=False)
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(owner_router, primary, actual_use=False)
    dh.acknowledge(owner_router, second.provider, True, dh.role_target_scope(second), audit, target=second.target_id)
    dh.authorize_role_target(owner_router, first, actual_use=True)
    assert owner_router._data_handling_role_used == {first.target_id: {
        "scope": dh.role_target_scope(first), "at": owner_router._data_handling_role_used[first.target_id]["at"]}}
    dh.acknowledge(owner_router, first.provider, False, dh.role_target_scope(first), audit, target=first.target_id)
    assert settings_db.get_value(*dh.ROLE_SETTING) == {
        **previous, "video_fallback_2": dh.role_target_scope(second)}
    assert dh.authorize_role_target(owner_router, second, actual_use=False)["acknowledged"]
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(owner_router, first, actual_use=False)


@pytest.mark.parametrize("change", ["model", "base_url", "key", "order"])
def test_candidate_change_stales_old_scope(candidates, monkeypatch, change):
    owner_router, audit = candidates
    first = vp.describe_video_data_target("role:video_fallback_1")
    scope = dh.role_target_scope(first)
    dh.acknowledge(owner_router, first.provider, True, scope, audit, target=first.target_id)
    rows = json.loads(os.environ["JARVIS_ROLE_VIDEO_FALLBACKS"])
    if change == "model":
        rows[0]["model"] = "rotated"
    elif change == "base_url":
        rows[0]["base_url"] = "https://new.example/v1"
    elif change == "order":
        rows.reverse()
    else:
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "rotated-key")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps(rows))
    current = vp.describe_video_data_target(first.target_id)
    assert dh.role_target_scope(current) != scope
    with pytest.raises(dh.StaleAcknowledgment):
        dh.acknowledge(owner_router, first.provider, True, scope, audit, target=first.target_id)
    with pytest.raises(vp.VideoPolicyRefused, match="configuration changed"):
        vp.authorization_check(first, allow_remote=True, confirm_expensive=True, router=owner_router)


def test_reordering_same_model_and_key_stales_both_address_scopes(candidates, monkeypatch):
    owner_router, audit = candidates
    rows = json.loads(os.environ["JARVIS_ROLE_VIDEO_FALLBACKS"])
    rows[1]["model"] = rows[0]["model"]
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_2_KEY", "one-secret")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps(rows))
    before = vp.describe_video_route_set()[1:]
    old_scopes = [dh.role_target_scope(identity) for identity in before]
    for identity, scope in zip(before, old_scopes, strict=True):
        dh.acknowledge(owner_router, identity.provider, True, scope, audit, target=identity.target_id)
    assert before[0].provider == before[1].provider
    assert before[0].model == before[1].model
    assert before[0].authorization == before[1].authorization
    assert before[0].request_url != before[1].request_url
    rows.reverse()
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps(rows))
    after = vp.describe_video_route_set()[1:]
    assert [identity.target_id for identity in after] == [identity.target_id for identity in before]
    assert [identity.request_url for identity in after] == [identity.request_url for identity in reversed(before)]
    assert all(dh.role_target_scope(identity) != scope
               for identity, scope in zip(after, old_scopes, strict=True))
    assert all(not row["acknowledged"] for row in dh.posture(owner_router)["targets"]
               if row["target_id"] in {identity.target_id for identity in before})


def test_unrelated_configured_role_update_preserves_both_fallback_grants(candidates, monkeypatch):
    from agents.core.autonomy.approval_judge import describe_data_target

    owner_router, audit = candidates
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_KEY", "judge-secret")
    judge = describe_data_target(owner_router)
    assert judge is not None and judge.target_id == dh.JUDGE_TARGET
    candidates_by_id = vp.describe_video_route_set()[1:]
    fallback_scopes = {identity.target_id.removeprefix("role:"): dh.role_target_scope(identity)
                       for identity in candidates_by_id}
    for identity in candidates_by_id:
        dh.acknowledge(owner_router, identity.provider, True, dh.role_target_scope(identity),
                       audit, target=identity.target_id)
    assert settings_db.get_value(*dh.ROLE_SETTING) == fallback_scopes
    dh.acknowledge(owner_router, judge.provider, True, dh.role_target_scope(judge),
                   audit, target=dh.JUDGE_TARGET)
    expected = {**fallback_scopes, "approval_judge": dh.role_target_scope(judge)}
    assert settings_db.get_value(*dh.ROLE_SETTING) == expected
    assert all(dh.authorize_role_target(owner_router, identity, actual_use=False)["acknowledged"]
               for identity in candidates_by_id)
    with pytest.raises(ValueError, match="finite role target"):
        dh.acknowledge(owner_router, judge.provider, True, dh.role_target_scope(judge),
                       audit, target="role:unregistered")
    assert settings_db.get_value(*dh.ROLE_SETTING) == expected


def test_change_during_audit_grants_nothing(candidates, monkeypatch):
    owner_router, audit = candidates
    first = vp.describe_video_data_target("role:video_fallback_1")
    old_log = audit.log
    def rotate(event):
        old_log(event)
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACK_1_KEY", "changed-during-audit")
    audit.log = rotate
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(owner_router, first.provider, True, dh.role_target_scope(first), audit, target=first.target_id)
    assert settings_db.get_value(*dh.ROLE_SETTING) == {}


def test_authorization_rejects_candidate_identity_with_mismatched_fields(candidates, monkeypatch):
    monkeypatch.setenv("JARVIS_VIDEO_ANALYSIS", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_ALLOW_REMOTE", "1")
    first = vp.describe_video_data_target("role:video_fallback_1")
    with pytest.raises(vp.VideoPolicyRefused, match="configuration changed"):
        vp.authorization_check(replace(first, provider="lm-studio"), allow_remote=True,
                               confirm_expensive=True, router=candidates[0])


def test_unreadable_and_missing_store_cannot_grant_candidate(candidates, monkeypatch):
    owner_router, audit = candidates
    first = vp.describe_video_data_target("role:video_fallback_1")
    original = settings_db.read_setting
    monkeypatch.setattr(settings_db, "read_setting", lambda category, key:
                        (False, None) if (category, key) == dh.ROLE_SETTING else original(category, key))
    row = next(r for r in dh.posture(owner_router)["targets"] if r["target_id"] == first.target_id)
    assert row["can_acknowledge"] is False
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(owner_router, first, actual_use=False)
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(owner_router, first.provider, True, dh.role_target_scope(first), None, target=first.target_id)
    monkeypatch.setattr(settings_db, "read_setting", original)
    stored_roles({"unknown": "a" * 64})
    assert dh.posture(owner_router)["role_settings_readable"] is False
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(owner_router, first.provider, True, dh.role_target_scope(first), audit, target=first.target_id)


def test_missing_role_setting_cannot_grant_candidate(candidates):
    owner_router, audit = candidates
    first = vp.describe_video_data_target("role:video_fallback_1")
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category=? AND key=?", dh.ROLE_SETTING)
        conn.commit()
    finally:
        conn.close()
    assert dh.posture(owner_router)["role_settings_readable"] is False
    with pytest.raises(dh.ConsentUnavailable):
        dh.acknowledge(owner_router, first.provider, True, dh.role_target_scope(first), audit,
                       target=first.target_id)


def test_admin_api_accepts_only_finite_configured_candidate(candidates, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web

    owner_router, audit = candidates
    first = vp.describe_video_data_target("role:video_fallback_1")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "candidate-admin")
    monkeypatch.setattr(web, "orch", SimpleNamespace(llm_router=owner_router, audit=audit))
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "candidate-admin"}
    body = {"provider": first.provider, "scope": dh.role_target_scope(first),
            "acknowledged": True, "target": first.target_id}
    response = client.post("/api/security/data-handling/ack", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["target"] == first.target_id
    assert client.post("/api/security/data-handling/ack", json={**body, "target": "role:outside"},
                       headers=headers).status_code == 422
    assert client.post("/api/security/data-handling/ack", json={**body, "target": "role:video_fallback_4"},
                       headers=headers).status_code == 422


def test_invalid_chain_refuses_primary_and_missing_primary_refuses_fallback(candidates, monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", '[{"provider":"openai-compatible"}]')
    with pytest.raises(vp.VideoPolicyRefused, match="invalid video fallback configuration"):
        vp.describe_video_route_set()
    with pytest.raises(vp.VideoPolicyRefused):
        vp.describe_video_data_target()
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([
        {"provider": "openai-compatible", "model": "fallback", "base_url": "https://one.example/v1"}]))
    monkeypatch.delenv("JARVIS_ROLE_VIDEO_PROVIDER")
    with pytest.raises(vp.VideoPolicyRefused):
        vp.describe_video_route_set()
