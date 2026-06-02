"""HTTP tests for the H12.1 reversible-approval + security-posture endpoints."""
import sys
from pathlib import Path

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


def test_security_posture_shape(token_client):
    r = token_client.get("/api/security/posture", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["secrets"]["encrypted_at_rest"] is True
    assert data["secrets"]["backend"] in ("fernet", "hmac-fallback", "unavailable")
    assert "require_signed" in data["skills"]
    assert "total" in data["skills"]
    assert "docker_available" in data["sandbox"]
    assert "mode" in data["guardrails"]


def test_security_posture_requires_admin(token_client):
    assert token_client.get("/api/security/posture").status_code in (401, 403)
