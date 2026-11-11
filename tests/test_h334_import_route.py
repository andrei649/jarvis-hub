"""H334 remote import entry: real owner and kernel decisions before staging."""

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import load_set, safe_mode, settings_db
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.routers import skills as skills_router
from agents.core.security.capability import KillSwitch
from agents.core.skills import loader as skill_loader_module
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.importer import SkillImporter
from agents.core.skills.loader import SkillLoader


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None):
        self.records.append((actor, action, why))


class _Importer:
    def __init__(self):
        self.calls = 0
        self.last_refusal = []

    async def import_from_hermes(self, skill_name, **kwargs):
        from agents.core.skills.remote_pin import RemoteImportRefused

        self.calls += 1
        authorization = kwargs["authorization"]
        pin, entry = kwargs["pin"], kwargs["entry"]
        payload = {"kind": "skill.install", "action": "import", "name": skill_name,
                   "source": "hermes", "pinned": True, "requested_by": "owner", "risk_tier": 3,
                   "approval_mode": "owner", "quarantined": True,
                   "source_repository": pin.repository, "source_commit": pin.commit, "commit": pin.commit,
                   "source_path": entry.path, "content_sha256": entry.content_sha256,
                   "files": [{"path": path, "content_sha256": digest} for path, digest in entry.files]}
        for _ in range(2):
            decision = authorization.install_gate(payload)
            if decision not in {"grant", "queue"}:
                raise RemoteImportRefused("install_denied" if decision == "deny" else "authorization_unavailable")
            if authorization.egress_gate("skill_import", "GET", "https://raw.githubusercontent.com/pinned",
                                         "raw.githubusercontent.com") is not None:
                raise RemoteImportRefused("egress_denied")
        return True

    async def import_from_openclaw(self, skill_name, **kwargs):
        self.calls += 1
        return True

    async def import_from_github(self, repo, skill_name, **kwargs):
        self.calls += 1
        return True


@pytest.mark.parametrize("flag", ["0", "1"])
def test_owner_remote_import_uses_live_skill_install_even_when_dev_and_global_kernel_off(
    monkeypatch, tmp_path, flag,
):
    importer = _Importer()
    audit = _Audit()
    orch = SimpleNamespace(skill_importer=importer, skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=audit, capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(web, "DEV_MODE", False)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", flag)
    response = TestClient(web.app).post("/skills/import", json={"source": "hermes", "skill": "github"},
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "installed_review_required"
    assert importer.calls == 1
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress",
                                               "authorize:skill.install", "authorize:plugin.egress"]


@pytest.mark.parametrize("source,pin", [
    ("openclaw", None),
    ("openclaw", {"repo": "openclaw/skills", "commit": "main",
                  "entry_path": "skills/calc/SKILL.md", "content_sha256": "b" * 64}),
    ("other/repo", {"repo": "wrong/repo", "commit": "a" * 40,
                    "entry_path": "skills/calc/SKILL.md", "content_sha256": "b" * 64}),
])
def test_generic_remote_import_refuses_unverified_or_wrong_source_pin_before_authority(
    monkeypatch, tmp_path, source, pin,
):
    importer = _Importer()
    audit = _Audit()
    orch = SimpleNamespace(skill_importer=importer, skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=audit, capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(web, "DEV_MODE", True)
    payload = {"source": source, "skill": "calc"}
    if pin is not None:
        payload["pin"] = pin
    response = TestClient(web.app).post("/skills/import", json=payload,
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 422, response.text
    assert importer.calls == 0
    assert audit.records == []


def test_route_refuses_importer_success_that_never_crossed_install_authority(monkeypatch, tmp_path):
    class SkippingImporter(_Importer):
        async def import_from_hermes(self, skill_name, **kwargs):
            self.calls += 1
            return True

    importer = SkippingImporter()
    orch = SimpleNamespace(skill_importer=importer, skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=_Audit(), capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(web, "DEV_MODE", False)
    response = TestClient(web.app).post("/skills/import", json={"source": "hermes", "skill": "github"},
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "authorization_unavailable"


def test_invalid_remote_document_retains_validator_detail(monkeypatch, tmp_path):
    from agents.core.skills.remote_pin import RemoteImportRefused

    class InvalidImporter(_Importer):
        async def import_from_hermes(self, skill_name, **kwargs):
            self.last_refusal = [SimpleNamespace(as_dict=lambda: {"field": "name", "reason": "mismatch"})]
            raise RemoteImportRefused("invalid_skill")

    importer = InvalidImporter()
    orch = SimpleNamespace(skill_importer=importer, skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=_Audit(), capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    response = TestClient(web.app).post("/skills/import", json={"source": "hermes", "skill": "github"},
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 422
    assert response.json()["reason"] == "invalid_skill_md"
    assert response.json()["problems"] == [{"field": "name", "reason": "mismatch"}]


_CALC_SKILL = (b"---\nname: calc\ndescription: A pinned calculation skill for local tests.\n"
               b"---\n\n# Calc\n\nFollow the owner's calculation request.\n")


def _real_import_route(monkeypatch, tmp_path, *, on_fetch=None, repo="example/tools"):
    source_dir = tmp_path / "owner-skills"
    kill = KillSwitch(tmp_path / "halt.json")
    requests = []

    def answer(request):
        requests.append(request)
        assert request.url.path == f"/{repo}/{'a' * 40}/skills/calc/SKILL.md"
        assert request.headers["host"] == "raw.githubusercontent.com"
        if on_fetch is not None:
            on_fetch(kill)
        return httpx.Response(200, content=_CALC_SKILL)

    importer = SkillImporter(str(source_dir), resolver=lambda host, mode: (["8.8.8.8"], None),
                             transport_factory=lambda target: httpx.MockTransport(answer))
    audit = _Audit()
    orch = SimpleNamespace(skill_importer=importer, skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(), kill_switch=kill,
                           intent_log=audit, capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    monkeypatch.setattr(web, "DEV_MODE", False)
    payload = {"source": repo, "skill": "calc",
               "pin": {"repo": repo, "commit": "a" * 40,
                       "entry_path": "skills/calc/SKILL.md",
                       "content_sha256": hashlib.sha256(_CALC_SKILL).hexdigest(),
                       "references": []}}
    return TestClient(web.app), payload, source_dir, kill, audit, requests


def test_server_pinned_hermes_route_uses_verified_bytes_without_client_pin(monkeypatch, tmp_path):
    from agents.core.skills.importer import _HermesPin, _HermesPinEntry

    client, payload, source_dir, _kill, audit, requests = _real_import_route(
        monkeypatch, tmp_path, repo="NousResearch/hermes-agent")
    entry = _HermesPinEntry("calc", "skills/calc/SKILL.md", hashlib.sha256(_CALC_SKILL).hexdigest(),
                            "bundled", ())
    pin = _HermesPin("NousResearch/hermes-agent", "v2026.8.31", "a" * 40, "c" * 40, (entry,))
    monkeypatch.setattr(skills_router, "_load_hermes_pin", lambda: pin)
    payload = {"source": "hermes", "skill": "calc"}
    response = client.post("/skills/import", json=payload, headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 200, response.text
    assert (source_dir / "calc/SKILL.md").read_bytes() == _CALC_SKILL
    assert (source_dir / "calc/PENDING_REVIEW").is_file()
    assert len(requests) == 1
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress",
                                               "authorize:skill.install"]


@pytest.mark.parametrize("flag", ["0", "1"])
def test_real_pinned_import_stages_exact_bytes_without_owner_activation(monkeypatch, tmp_path, flag):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", flag)
    client, payload, source_dir, _kill, audit, requests = _real_import_route(monkeypatch, tmp_path)
    response = client.post("/skills/import", json=payload, headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "installed_review_required"
    target = source_dir / "calc"
    assert (target / "SKILL.md").read_bytes() == _CALC_SKILL
    assert (target / "PENDING_REVIEW").is_file()
    sidecar = json.loads((target / "manifest.json").read_text())
    assert sidecar["source_commit"] == "a" * 40
    assert sidecar["content_sha256"] == hashlib.sha256(_CALC_SKILL).hexdigest()
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "approvals.json"))
    loader._load_skill(target, discovery_root=source_dir)
    assert loader.skills["calc"].sandboxed is True
    assert loader.skills["calc"].module is None
    assert len(requests) == 1
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress",
                                               "authorize:skill.install"]


@pytest.mark.parametrize("safe,loadset_only", [("1", None), ("0", ["unrelated"])])
def test_remote_import_stays_out_of_loader_and_index_when_safe_or_loadset_narrows(
    monkeypatch, tmp_path, safe, loadset_only,
):
    monkeypatch.setenv("JARVIS_SAFE_MODE", safe)
    client, payload, source_dir, _kill, audit, requests = _real_import_route(monkeypatch, tmp_path)
    shipped_dir = tmp_path / "shipped-skills"
    monkeypatch.setattr(skill_loader_module, "SKILLS_DIR", shipped_dir)
    monkeypatch.setattr(skill_loader_module, "_user_skills_dir", lambda: source_dir)
    monkeypatch.setattr(skill_loader_module, "_index_snapshot_path", lambda: tmp_path / "skills-index.json")
    if loadset_only is not None:
        monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
        monkeypatch.setattr(settings_db, "_initialized", False)
        updated, skipped = settings_db.put_category("loadset", {"skills_only": ",".join(loadset_only)})
        assert (updated, skipped) == (1, [])
        assert load_set.declared("skills")["only"] == loadset_only
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "approvals.json"))
    discoveries = []
    discover = loader.discover

    def observed_discover():
        discoveries.append(True)
        return discover()

    monkeypatch.setattr(loader, "discover", observed_discover)
    web.orch.skills = loader
    response = client.post("/skills/import", json=payload, headers={"X-Admin-Token": "owner-test"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "installed_review_required"
    assert response.json()["quarantined"] is True
    target = source_dir / "calc"
    assert (target / "SKILL.md").read_bytes() == _CALC_SKILL
    assert (target / "PENDING_REVIEW").is_file()
    assert discoveries == [True]
    assert loader.get_skill("calc") is None
    assert "calc" not in loader.prompt_index()
    if safe == "1":
        assert safe_mode.enabled() is True
        loader._load_skill(target, discovery_root=source_dir)
        assert loader.get_skill("calc") is None
    assert len(requests) == 1
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress",
                                               "authorize:skill.install"]


def test_real_import_halt_after_fetch_refuses_staging(monkeypatch, tmp_path):
    client, payload, source_dir, _kill, audit, requests = _real_import_route(
        monkeypatch, tmp_path, on_fetch=lambda halt: halt.engage(reason="owner stop"))
    response = client.post("/skills/import", json=payload, headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "install_denied"
    assert not (source_dir / "calc").exists()
    assert len(requests) == 1
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress",
                                               "authorize:skill.install"]


def test_inbound_origin_refuses_real_egress_before_transport(monkeypatch, tmp_path):
    from agents.core import action_origin
    from agents.core.kernel import binding

    client, payload, source_dir, _kill, audit, requests = _real_import_route(monkeypatch, tmp_path)
    original = binding.make_action_kernel
    actions = []

    def observed_kernel(orch):
        bound = original(orch)

        def authorize(action):
            actions.append((action.kind, action.origin))
            return bound(action)

        return authorize

    monkeypatch.setattr(binding, "make_action_kernel", observed_kernel)
    token = action_origin.bind_action_origin("inbound")
    try:
        response = client.post("/skills/import", json=payload, headers={"X-Admin-Token": "owner-test"})
    finally:
        action_origin.reset_action_origin(token)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "egress_denied"
    assert requests == []
    assert not (source_dir / "calc").exists()
    assert actions == [("skill.install", "inbound"), ("plugin.egress", "inbound")]
    assert [row[1] for row in audit.records] == ["authorize:skill.install", "authorize:plugin.egress"]


def test_route_refuses_install_payload_that_disagrees_with_validated_pin(monkeypatch, tmp_path):
    class ForgedImporter(_Importer):
        async def import_from_github(self, repo, skill_name, **kwargs):
            auth = kwargs["authorization"]
            forged = {"kind": "skill.install", "action": "import", "name": skill_name,
                      "source_repository": repo, "source_commit": "a" * 40,
                      "source_path": "skills/calc/SKILL.md", "content_sha256": "f" * 64,
                      "files": []}
            auth.install_gate(forged)
            auth.install_gate(forged)
            auth.egress_gate("skill-import", "GET", "https://raw.githubusercontent.com/example/tools",
                             "raw.githubusercontent.com")
            return True

    audit = _Audit()
    orch = SimpleNamespace(skill_importer=ForgedImporter(), skills=SimpleNamespace(discover=lambda: None),
                           autonomy_policy=AutonomyPolicy(),
                           kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=audit, capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    response = TestClient(web.app).post("/skills/import", json={"source": "example/tools", "skill": "calc",
                                                           "pin": {"repo": "example/tools", "commit": "a" * 40,
                                                                   "entry_path": "skills/calc/SKILL.md",
                                                                   "content_sha256": "b" * 64}},
                                        headers={"X-Admin-Token": "owner-test"})
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "authorization_unavailable"
    assert all(row[1] != "authorize:skill.install" for row in audit.records)
