"""HTTP tests for the H12.1 reversible-approval + security-posture endpoints."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

HEADERS = {"X-Admin-Token": "test-secret"}


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


def test_approvals_requires_admin(token_client):
    assert token_client.get("/autonomy/approvals").status_code in (401, 403)


def test_approvals_buckets_shape(token_client):
    r = token_client.get("/autonomy/approvals", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert set(["pending", "reversible", "irreversible", "counts"]).issubset(data)
    assert data["counts"]["total"] == len(data["pending"])
    assert data["counts"]["reversible"] == len(data["reversible"])
    assert data["counts"]["irreversible"] == len(data["irreversible"])


def test_irreversible_action_appears_in_irreversible_bucket(token_client):
    # An irreversible task (delete) is blocked → shows up as irreversible.
    sub = token_client.post(
        "/autonomy/tasks",
        json={"agent": "jarvis", "kind": "delete_file", "title": "Delete prod db"},
        headers=HEADERS,
    ).json()["task"]
    assert sub["status"] == "blocked"

    r = token_client.get("/autonomy/approvals", headers=HEADERS)
    data = r.json()
    ids_irrev = {t["id"] for t in data["irreversible"]}
    assert sub["id"] in ids_irrev
    match = next(t for t in data["pending"] if t["id"] == sub["id"])
    assert match["reversible"] is False
    assert match["reversibility"] == "irreversible"
    assert match["tier_name"] == "IRREVERSIBLE_OR_MONEY"
    assert match["rollback"] is None


def test_registered_action_approval_includes_machine_readable_rollback(token_client):
    sub = token_client.post(
        "/autonomy/tasks",
        json={"agent": "jarvis", "kind": "payment", "title": "Pay invoice"},
        headers=HEADERS,
    ).json()["task"]
    assert sub["status"] == "blocked"

    pending = token_client.get("/autonomy/approvals", headers=HEADERS).json()["pending"]
    match = next(task for task in pending if task["id"] == sub["id"])
    assert match["capability_id"] == "action:payment"
    assert match["rollback"]["mode"] == "cancel"
    assert match["rollback"]["automatic"] is False
    assert "settled" in match["rollback"]["limitations"]


def test_wildcard_action_projection_and_unknown_kind_fail_honestly():
    from agents.core.routers.autonomy import _approval_projection

    def task(kind):
        row = {"id": 1, "kind": kind, "risk_tier": 3}
        return SimpleNamespace(**row, to_dict=lambda: dict(row))

    social = _approval_projection(task("social.post"))
    unknown = _approval_projection(task("unregistered.mutation"))
    assert social["capability_id"] == "action:social.*"
    assert social["rollback"]["mode"] == "compensate"
    assert unknown["capability_id"] is None
    assert unknown["rollback"] is None


def test_security_posture_shape(token_client):
    r = token_client.get("/api/security/posture", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    secrets = data["secrets"]
    assert secrets["backend"] in ("fernet", "hmac-fallback", "unavailable")
    # encrypted_at_rest is DERIVED from the backend, not asserted. It used to be a
    # hardcoded `True`, so this line passed even on a box where the secret store
    # could not be opened — a green "encrypted" badge for an unknown state.
    if secrets["backend"] in ("fernet", "hmac-fallback"):
        assert secrets["encrypted_at_rest"] is True
    else:
        assert secrets["encrypted_at_rest"] is None
    assert "require_signed" in data["skills"]
    assert "total" in data["skills"]
    assert "docker_available" in data["sandbox"]
    assert "mode" in data["guardrails"]
    assert data["product_posture"]["name"] in ("off", "companion_wave1", "design_partner")
    assert "memory.recall_enabled" in data["product_posture"]["flags"]


def test_security_posture_requires_admin(token_client):
    assert token_client.get("/api/security/posture").status_code in (401, 403)


def test_security_posture_does_not_claim_encryption_it_could_not_verify(token_client, monkeypatch):
    """The regression: an unopenable secret store must report unknown, not true.

    `encrypted_at_rest` was the literal `True` in the response dict — never read
    from anything — so the security-posture page, whose whole job is to report
    posture honestly, showed a green "encrypted" badge unconditionally.
    """
    # The handler does `from core.secrets import SecretStore`, and `core.secrets`
    # and `agents.core.secrets` are DISTINCT module objects under this repo's dual
    # sys.path — patching the wrong one silently does nothing.
    import core.secrets as secrets_mod

    class _Broken:
        def __init__(self, *a, **k):
            raise OSError("secret store cannot be opened")

    monkeypatch.setattr(secrets_mod, "SecretStore", _Broken)
    data = token_client.get("/api/security/posture", headers=HEADERS).json()

    assert data["secrets"]["backend"] == "unavailable"
    # None, not True (a false assurance) and not False (also a claim — we did not
    # observe plaintext, we failed to look).
    assert data["secrets"]["encrypted_at_rest"] is None
    assert "unknown" in data["secrets"]["note"]


def test_security_posture_flags_the_weaker_fallback_cipher(token_client, monkeypatch):
    """fernet and hmac-fallback are both real encryption, but not equivalent, and
    the posture page should not present them as identical."""
    import core.secrets as secrets_mod

    class _Fallback:
        backend = "hmac-fallback"

        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(secrets_mod, "SecretStore", _Fallback)
    secrets = token_client.get("/api/security/posture", headers=HEADERS).json()["secrets"]

    assert secrets["encrypted_at_rest"] is True
    assert secrets["strength"] == "fallback-cipher"
    assert "cryptography" in secrets["note"]
