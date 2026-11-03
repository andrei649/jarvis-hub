"""HTTP integration tests for skills endpoints.

Covers:
  POST /skills/import              — DEV_MODE gate, source routing, 404 not-found
  GET  /skills/imported            — list imported skills
  GET  /api/skills/marketplace     — list marketplace catalogue (admin)
  POST /api/skills/marketplace/publish  — publish a skill (admin)
  POST /api/skills/marketplace/install  — install by name (admin)
  POST /api/skills/marketplace/install-zip — install from base64 zip (admin)
"""
import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.routers.skills as skills_router
import agents.web as web

_NO_ORCH = TestClient(web.app)
_TOKEN = "skills-test-token"
_HDR = {"X-Admin-Token": _TOKEN}


def _mock_orch() -> MagicMock:
    m = MagicMock()
    m.skill_importer.import_from_hermes = AsyncMock(return_value=True)
    m.skill_importer.import_from_openclaw = AsyncMock(return_value=True)
    m.skill_importer.import_from_github = AsyncMock(return_value=True)
    m.skill_importer.list_imported = MagicMock(return_value=["calendar", "spotify"])
    m.skills.discover = MagicMock()
    m.marketplace.list_skills = MagicMock(return_value=[
        {"name": "weather-pro", "version": "1.0", "description": "Extended weather"},
    ])
    m.marketplace.publish_skill = MagicMock(return_value={"name": "my-skill", "version": "1.0"})
    m.marketplace.install_skill = MagicMock(return_value=True)
    m.marketplace.install_from_zip = MagicMock(return_value=True)
    return m


# ---------------------------------------------------------------------------
# POST /skills/import
# ---------------------------------------------------------------------------

def test_skills_import_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    resp = _NO_ORCH.post("/skills/import", json={"skill": "test", "source": "hermes"}, headers=_HDR)
    assert resp.status_code == 503


def test_skills_import_blocked_without_dev_mode(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", False)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"skill": "test"}, headers=_HDR)
    assert resp.status_code == 403
    assert "DEV_MODE" in resp.json()["error"]


def test_skills_import_missing_skill_name_returns_400(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"source": "hermes"}, headers=_HDR)
    assert resp.status_code == 400
    assert "skill" in resp.json()["error"].lower()


def test_skills_import_hermes_success(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"skill": "github", "source": "hermes"}, headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["skill"] == "github"
    assert data["source"] == "hermes"


def test_skills_import_hermes_not_found_returns_404(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    mock = _mock_orch()
    mock.skill_importer.import_from_hermes = AsyncMock(return_value=False)
    monkeypatch.setattr(web, "orch", mock)
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"skill": "unknown-skill", "source": "hermes"}, headers=_HDR)
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


def test_skills_import_openclaw_source(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"skill": "calc", "source": "openclaw"}, headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["source"] == "openclaw"


def test_skills_import_github_source(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = TestClient(web.app)
    resp = client.post("/skills/import", json={"skill": "notes", "source": "github.com/user/repo"}, headers=_HDR)
    assert resp.status_code == 200


def test_pinned_hermes_catalog_lists_tiers_and_reference_counts_without_fetch(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    response = client.get("/skills/hermes/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["release_tag"] == "v2026.8.31"
    github = next(row for row in data["skills"] if row["slug"] == "github")
    grill = next(row for row in data["skills"] if row["slug"] == "grill-me")
    assert github["tier"] == "bundled" and github["reference_count"] == 10
    assert grill["tier"] == "optional"


def test_remote_skill_import_requires_admin_even_with_user_access(monkeypatch):
    mock = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    monkeypatch.setattr(web, "DEV_MODE", True)
    response = TestClient(web.app).post("/skills/import", json={"skill": "github"})
    assert response.status_code == 401
    mock.skill_importer.import_from_hermes.assert_not_awaited()


def test_remote_hermes_kernel_denial_prevents_fetch_and_install(monkeypatch):
    mock = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    monkeypatch.setattr(web, "DEV_MODE", True)
    monkeypatch.setattr(skills_router, "_remote_import_gate", lambda payload: "deny")
    response = TestClient(web.app).post(
        "/skills/import", json={"skill": "github", "source": "hermes"}, headers=_HDR
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "kernel_denied"
    mock.skill_importer.import_from_hermes.assert_not_awaited()


def test_remote_hermes_gate_binds_pin_and_files(monkeypatch):
    mock = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    monkeypatch.setattr(web, "DEV_MODE", True)
    seen = []
    monkeypatch.setattr(skills_router, "_remote_import_gate", lambda payload: seen.append(payload) or "grant")
    response = TestClient(web.app).post(
        "/skills/import", json={"skill": "github", "source": "hermes"}, headers=_HDR
    )
    assert response.status_code == 200
    assert seen[0]["pinned"] is True
    assert seen[0]["commit"] == "29112bef099274229cadff79cdff7bf7b99c4b77"
    assert len(seen[0]["files"]) == 10


def _optional_route_fixture(monkeypatch, tmp_path, verdict="queue"):
    source = tmp_path / "optional" / "calendar"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Calendar\n\n> Schedule tasks.\n", encoding="utf-8")
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    dest = tmp_path / "owner-skills"
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    monkeypatch.setattr(skills_router, "_optional_skills_root", lambda: source.parent)
    monkeypatch.setattr(skills_router, "_writable_skills_dir", lambda: dest)
    monkeypatch.setattr(skills_router, "_optional_install_gate", lambda payload: verdict)
    return source, dest


def test_optional_catalog_and_install_requires_admin(monkeypatch, tmp_path):
    source, dest = _optional_route_fixture(monkeypatch, tmp_path)
    client = TestClient(web.app)
    assert client.get("/api/skills/optional/catalog").status_code == 401
    assert client.post("/api/skills/optional/install", json={"name": "calendar"}).status_code == 401
    assert not dest.exists()
    response = client.get("/api/skills/optional/catalog", headers=_HDR)
    assert response.status_code == 200
    assert any(row["name"] == "calendar" and row["tier"] == "optional"
               for row in response.json()["skills"])


def test_optional_install_kernel_denial_writes_nothing(monkeypatch, tmp_path):
    _, dest = _optional_route_fixture(monkeypatch, tmp_path, verdict="deny")
    response = TestClient(web.app).post(
        "/api/skills/optional/install", json={"name": "calendar"}, headers=_HDR
    )
    assert response.status_code == 403
    assert response.json()["status"] == "refused"
    assert not dest.exists()


@pytest.mark.parametrize("verdict", ["grant", "queue"])
def test_optional_install_stays_pending_review_after_kernel_allow(monkeypatch, tmp_path, verdict):
    _, dest = _optional_route_fixture(monkeypatch, tmp_path, verdict=verdict)
    response = TestClient(web.app).post(
        "/api/skills/optional/install", json={"name": "calendar"}, headers=_HDR
    )
    assert response.status_code == 200
    assert response.json()["status"] == "installed_review_required"
    assert response.json()["kernel"] == verdict
    assert (dest / "calendar/PENDING_REVIEW").exists()
    assert (dest / "calendar/main.py").read_bytes() == b"VALUE = 1\n"


def test_optional_install_refuses_unknown_and_symlinked_source_before_gate(monkeypatch, tmp_path):
    source, dest = _optional_route_fixture(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(skills_router, "_optional_install_gate", lambda payload: calls.append(payload))
    client = TestClient(web.app)
    unknown = client.post("/api/skills/optional/install", json={"name": "../calendar"}, headers=_HDR)
    assert unknown.status_code == 404
    (source / "link.py").symlink_to(source / "SKILL.md")
    linked = client.post("/api/skills/optional/install", json={"name": "calendar"}, headers=_HDR)
    assert linked.status_code == 422
    assert calls == []
    assert not dest.exists()


# ---------------------------------------------------------------------------
# GET /skills/imported
# ---------------------------------------------------------------------------

def test_skills_imported_no_orch_returns_503():
    resp = _NO_ORCH.get("/skills/imported")
    assert resp.status_code == 503


def test_skills_imported_returns_list(monkeypatch):
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.get("/skills/imported")
    assert resp.status_code == 200
    data = resp.json()
    assert "imported" in data
    assert isinstance(data["imported"], list)
    assert "calendar" in data["imported"]


# ---------------------------------------------------------------------------
# GET /api/skills/marketplace (admin-guarded)
# ---------------------------------------------------------------------------

def test_marketplace_list_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/api/skills/marketplace", headers=_HDR)
    assert resp.status_code == 503


def test_marketplace_list_returns_skills(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.get("/api/skills/marketplace", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    assert isinstance(data["skills"], list)
    assert data["skills"][0]["name"] == "weather-pro"


# ---------------------------------------------------------------------------
# POST /api/skills/marketplace/publish (admin-guarded)
# ---------------------------------------------------------------------------

def test_marketplace_publish_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/publish", json={"name": "my-skill"}, headers=_HDR)
    assert resp.status_code == 503


def test_marketplace_publish_not_found_returns_404(monkeypatch):
    mock = _mock_orch()
    mock.marketplace.publish_skill = MagicMock(side_effect=FileNotFoundError("not found"))
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/publish", json={"name": "ghost"}, headers=_HDR)
    assert resp.status_code == 404


def test_marketplace_publish_success(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/publish", json={"name": "my-skill"}, headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# POST /api/skills/marketplace/install (admin-guarded)
# ---------------------------------------------------------------------------

def test_marketplace_install_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/install", json={"name": "x"}, headers=_HDR)
    assert resp.status_code == 503


def test_marketplace_install_not_found_returns_404(monkeypatch):
    mock = _mock_orch()
    mock.marketplace.install_skill = MagicMock(side_effect=ValueError("not found"))
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/install", json={"name": "ghost"}, headers=_HDR)
    assert resp.status_code == 404


def test_marketplace_install_success(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    resp = client.post("/api/skills/marketplace/install", json={"name": "weather-pro"}, headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["installed"] == "weather-pro"


def test_marketplace_install_triggers_discover(monkeypatch):
    mock = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", mock)
    client = TestClient(web.app)
    client.post("/api/skills/marketplace/install", json={"name": "weather-pro"}, headers=_HDR)
    mock.skills.discover.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/skills/marketplace/install-zip (admin-guarded)
# ---------------------------------------------------------------------------

def test_marketplace_install_zip_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    payload = base64.b64encode(b"fake zip content").decode()
    resp = client.post("/api/skills/marketplace/install-zip", json={"zip_base64": payload}, headers=_HDR)
    assert resp.status_code == 503


def test_marketplace_install_zip_success(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch())
    client = TestClient(web.app)
    payload = base64.b64encode(b"fake zip content").decode()
    resp = client.post("/api/skills/marketplace/install-zip", json={"zip_base64": payload}, headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# GET /skills — per-skill usage counters (H354)
# ---------------------------------------------------------------------------

def _usage_orch(tmp_path):
    """A loader with two skills and a real usage sidecar, the way the orchestrator wires it."""
    from types import SimpleNamespace

    from agents.core.skills.usage import SkillUsageStore

    def skill(name):
        return SimpleNamespace(name=name, version="1.0", description=name, agents=["jarvis"],
                               commands_meta={}, hermes_meta=None, platforms=None, path=None,
                               module=object(), trusted=True)

    orch = SimpleNamespace(skills=SimpleNamespace(skills={"Weather Intel": skill("Weather Intel"),
                                                          "Spotify": skill("Spotify")}))
    orch.skill_usage = SkillUsageStore(tmp_path / "skill_usage.json")
    return orch


def test_skills_list_carries_usage_counters_and_last_used(monkeypatch, tmp_path):
    orch = _usage_orch(tmp_path)
    store = orch.skill_usage
    store.bump("Weather Intel", "use")
    store.bump("Weather Intel", "use")
    store.bump("Weather Intel", "patch")
    monkeypatch.setattr(web, "orch", orch)
    body = TestClient(web.app).get("/skills").json()

    weather = body["skills"]["Weather Intel"]["usage"]
    rec = store.get("Weather Intel")
    assert weather == {
        "use_count": 2, "view_count": 0, "patch_count": 1,
        "last_used_at": rec["last_used_at"], "last_viewed_at": rec["last_viewed_at"],
        "last_patched_at": rec["last_patched_at"],
        "origin": "bundled", "state": "active", "pinned": False,
    }
    # `view` is counted by the real skill_view tool: see tests/test_h318_skill_tools.py.
    assert weather["last_used_at"] and weather["last_patched_at"] and weather["last_viewed_at"] is None
    # A skill the sidecar never saw is reported with zeros — not omitted, not an error.
    spotify = body["skills"]["Spotify"]["usage"]
    assert spotify["use_count"] == spotify["view_count"] == spotify["patch_count"] == 0
    assert spotify["last_used_at"] is None and spotify["origin"] == "bundled"
    # Reading the listing writes nothing: the untouched skill still has no record.
    assert store.get("Spotify") is None


def test_skills_list_usage_is_zero_when_the_sidecar_is_absent(monkeypatch, tmp_path):
    orch = _usage_orch(tmp_path)
    orch.skill_usage = None               # the orchestrator's learning init failed
    monkeypatch.setattr(web, "orch", orch)
    body = TestClient(web.app).get("/skills").json()
    assert body["skills"]["Spotify"]["usage"]["use_count"] == 0
    assert body["skills"]["Spotify"]["usage"]["last_used_at"] is None
