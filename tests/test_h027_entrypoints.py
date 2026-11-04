"""Actual CLI → authenticated hub → exact owner card → curator filesystem path."""

import io
import json
import urllib.error
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.cli.client import HubClient
from agents.cli.nerva import Context, main
from agents.core import settings_db
from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.security.capability import KillSwitch
from agents.core.skills import loader as loader_module
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.curator import SkillCurator
from agents.core.skills.curator_operations import CuratorOperations
from agents.core.skills.loader import SkillLoader
from agents.core.skills.references import Holders
from agents.core.skills.usage import ORIGIN_AGENT, SkillUsageStore


@pytest.fixture
def owner(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_SAFE_MODE", "0")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "0")
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    root = tmp_path / "personal-skills"
    root.mkdir()
    skill = root / "local-curation"
    skill.mkdir()
    original = b"---\nname: local-curation\ndescription: Local curator fixture\n---\n\n# Local\n\nRead fixture data.\n"
    (skill / "SKILL.md").write_bytes(original)
    monkeypatch.setattr(loader_module, "SKILLS_DIR", tmp_path / "shipped")
    monkeypatch.setattr(loader_module, "_user_skills_dir", lambda: root)
    monkeypatch.setattr(loader_module, "_index_snapshot_path", lambda: tmp_path / "index.json")
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "standing.json"))
    usage = SkillUsageStore(tmp_path / "usage.json")
    loader.attach_usage(usage)
    loader._load_skill(skill, discovery_root=root)
    assert "local-curation" in loader.skills
    usage.note_created("local-curation", ORIGIN_AGENT)
    approvals = ActionApprovalQueue(tmp_path / "approval-cards.json")
    curator = SkillCurator(loader, usage, approvals=approvals, archive_dir=tmp_path / "archive")
    settings_db.ensure_initialized()

    def get_setting(key, default=None):
        category, name = key.split(".", 1)
        return settings_db.get_value(category, name, default)

    def holders():
        return Holders(bundles=lambda: [], switches=lambda: {"disabled": [], "channel_disabled": {}},
                       load_set=lambda: {"disabled": [], "only": []})

    operations = CuratorOperations(loader, usage, curator, approvals,
                                    state_dir=tmp_path / "operations", archive_dir=tmp_path / "archive",
                                    get_setting=get_setting, holders=holders)
    orch = SimpleNamespace(skills=loader, skill_usage=usage, curator=curator,
                           action_approvals=approvals, curator_operations=operations,
                           autonomy_policy=AutonomyPolicy(), capabilities=None, intent_log=None,
                           kill_switch=KillSwitch(tmp_path / "halt.json"))
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-curator")
    client = TestClient(web.app)

    def opener(request, timeout):
        response = client.request(request.method, urlsplit(request.full_url).path,
                                  content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "hub refusal",
                                         {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    def invoke(*argv):
        output, error = io.StringIO(), io.StringIO()
        context = Context(environ={"JARVIS_ADMIN_TOKEN": "owner-curator"}, out=output, err=error,
                          client_factory=lambda env: HubClient.from_env(env, opener=opener))
        code = main(["curator", *argv, "--json"], context=context)
        assert code == 0, error.getvalue()
        return json.loads(output.getvalue())

    def decide(card_id):
        response = client.post(f"/api/actions/{card_id}/decide", json={"approved": True},
                               headers={"X-Admin-Token": "owner-curator"})
        assert response.status_code == 200, response.text
        return response.json()["action"]["applied"]

    return SimpleNamespace(orch=orch, path=skill, original=original, invoke=invoke,
                           client=client, decide=decide, operations=operations, approvals=approvals)


def test_real_owner_cli_archives_and_restores_only_after_each_exact_card(owner):
    before = owner.orch.skill_usage.path.read_bytes()
    preview = owner.invoke("archive", "local-curation", "--dry-run")
    assert preview["ok"] is True
    assert owner.approvals.list() == [] and owner.path.is_dir()
    assert owner.orch.skill_usage.path.read_bytes() == before

    pending = owner.invoke("archive", "local-curation")
    assert pending["status"] == "pending" and owner.path.is_dir()
    applied = owner.decide(pending["card_id"])
    assert applied["ok"] is True and applied["status"] == "applied"
    assert not owner.path.exists()
    archives = owner.invoke("list-archived")["items"]
    assert len(archives) == 1
    pending = owner.invoke("restore", archives[0]["id"])
    assert pending["status"] == "pending" and not owner.path.exists()
    assert owner.decide(pending["card_id"])["status"] == "applied"
    assert (owner.path / "SKILL.md").read_bytes() == owner.original
    assert owner.orch.skill_usage.get("local-curation")["state"] == "active"
    assert "local-curation" in owner.orch.skills.skills
    ledger = owner.invoke("ledger")["items"]
    assert len(ledger) == 2 and {row["operation"] for row in ledger} == {"archive", "restore"}


def test_owner_halt_after_queue_refuses_real_pin_without_usage_change(owner):
    pending = owner.invoke("pin", "local-curation")
    assert pending["status"] == "pending"
    before = owner.orch.skill_usage.path.read_bytes()
    owner.orch.kill_switch.engage(reason="owner halt after review")
    outcome = owner.decide(pending["card_id"])
    assert outcome["ok"] is False and outcome["status"] == "refused"
    assert owner.orch.skill_usage.path.read_bytes() == before
    assert (owner.path / "SKILL.md").read_bytes() == owner.original


@pytest.mark.parametrize("invalid", [True, 1.5, -1, 36_501])
def test_owner_curator_age_settings_are_registered_and_invalid_purge_age_cannot_persist(owner, invalid):
    headers = {"X-Admin-Token": "owner-curator"}
    response = owner.client.get("/api/admin/settings", headers=headers)
    assert response.status_code == 200
    fields = {row["key"]: row for row in response.json()["learning"]}
    assert fields["curator_stale_days"]["default"] == 30
    assert fields["curator_archive_days"]["default"] == 90
    assert fields["curator_purge_days"]["default"] == 0
    response = owner.client.put("/api/admin/settings/learning", headers=headers,
                                json={"values": {"curator_purge_days": invalid}})
    assert response.status_code == 422
    assert settings_db.get_value("learning", "curator_purge_days") == 0


async def test_actual_isolated_hub_boot_exposes_curator_without_creating_an_operation_store(monkeypatch, tmp_path):
    from scripts.install_smoke import _build_fake_orchestrator

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-curator")
    orch, _backend = await _build_fake_orchestrator(tmp_path, "local boot fixture")
    try:
        assert orch.curator_operations is not None
        monkeypatch.setattr(web, "orch", orch)
        response = TestClient(web.app).get("/api/curator/status",
                                           headers={"X-Admin-Token": "owner-curator"})
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True
        assert not (tmp_path / "learning" / "curator").exists()
    finally:
        await orch.aclose()


def test_existing_cognition_entrypoint_reads_the_governed_curator_run(owner, monkeypatch):
    from agents.core.cognition import api as cognition_api

    monkeypatch.setattr(cognition_api, "_facade", lambda: SimpleNamespace(
        module=lambda _name: SimpleNamespace(status=lambda: {"available": True})))
    headers = {"X-Admin-Token": "owner-curator"}
    response = owner.client.put("/api/admin/settings/cognition", headers=headers,
                                json={"values": {"review_enabled": True}})
    assert response.status_code == 200
    pending = owner.invoke("run")
    assert owner.decide(pending["card_id"])["status"] == "applied"
    current = owner.invoke("status")
    response = owner.client.get("/api/cognition/learning", headers=headers)
    assert response.status_code == 200
    report = response.json()["curator"]
    assert report["available"] is True
    assert report["last_run"] == current["last_run"][:10]
    assert report["last_result"]["date"] == current["last_run"][:10]
    assert set(report["last_result"]["lifecycle"]) == {"considered", "stale", "archived"}
    assert str(owner.path) not in response.text
