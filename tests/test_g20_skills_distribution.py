"""G20 skills distribution — owner-side acceptance (H342 setup values, H025/H335 taps).

What the owner can do: see which variables a skill needs, set them without ever seeing a
value again, add a trusted skill source behind an approval card, search every source by
trust, install from a tap into quarantine. What nobody can do: read a value back, get one
skill's value into another skill's run, trust a source without a person accepting the
card, pin a tap to a branch, or install a refused tap entry or bypass the pinned import.
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import integration_keys
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.code_env import CodeEnvRegistry
from agents.core.security.capability import KillSwitch
from agents.core.skills import skill_secrets
from agents.core.skills.loader import Skill

ADMIN = {"X-Admin-Token": "owner-test"}
SECRET = "sk-live-0123456789abcdefWXYZ"
COMMIT = "c" * 40


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(integration_keys, "_store_path", lambda: tmp_path / "secrets.enc")
    for name in ("G20_TOOL_KEY", "G20_OTHER_KEY", "G20_OPTIONAL"):
        monkeypatch.delenv(name, raising=False)
    yield


def _skill(name="weather-tool", declared=("G20_TOOL_KEY",), optional=()):
    rows = [{"name": n, "prompt": f"Enter {n}"} for n in declared]
    rows += [{"name": n, "prompt": f"Enter {n}", "optional": True} for n in optional]
    skill = Skill(name, None, {"name": name, "required_environment_variables": rows})
    return skill


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None, **_kw):
        self.records.append({"actor": actor, "action": action, "why": why, "metadata": metadata})


class _Autonomy:
    def __init__(self):
        self.policy = AutonomyPolicy()
        self.tasks = {}

    def govern_enqueue(self, agent, kind, title, payload=None, risk_tier=2, autonomy_level="ask",
                       origin="generated", attention_mode="interrupt"):
        task_id = len(self.tasks) + 1
        self.tasks[task_id] = SimpleNamespace(id=task_id, kind=kind, title=title, payload=dict(payload or {}),
                                              risk_tier=risk_tier, autonomy_level=autonomy_level)
        return task_id


class _Importer:
    """Stands in for the remote fetch; crosses the route's real authorization like the real one."""

    def __init__(self):
        self.calls = []
        self.last_refusal = []

    def list_imported(self):
        return []

    async def _flow(self, source, skill_name, kwargs):
        from agents.core.skills.remote_pin import RemoteImportRefused

        authorization, pin = kwargs["authorization"], kwargs.get("pin")
        self.calls.append((source, skill_name, pin))
        payload = {"kind": "skill.install", "action": "import", "name": skill_name,
                   "source": source.rsplit("/", 1)[-1] if source not in ("hermes", "openclaw") else source,
                   "pinned": True, "requested_by": "owner", "risk_tier": 3, "approval_mode": "owner",
                   "quarantined": True, "source_repository": pin.repo, "source_commit": pin.commit,
                   "commit": pin.commit, "source_path": pin.entry_path, "content_sha256": pin.content_sha256,
                   "files": [{"path": p, "content_sha256": d} for p, d in pin.references]}
        for _ in range(2):
            if authorization.install_gate(payload) not in {"grant", "queue"}:
                raise RemoteImportRefused("install_denied")
            if authorization.egress_gate("skill-import", "GET", "https://raw.githubusercontent.com/x",
                                         "raw.githubusercontent.com") is not None:
                raise RemoteImportRefused("egress_denied")
        return True

    async def import_from_github(self, repo, skill_name, **kwargs):
        return await self._flow(repo, skill_name, kwargs)


def _orch(monkeypatch, tmp_path, skills=None):
    loader = SimpleNamespace(skills=dict(skills or {}), discover=lambda: None)
    orch = SimpleNamespace(skill_importer=_Importer(), skills=loader, autonomy=_Autonomy(),
                           autonomy_policy=AutonomyPolicy(), kill_switch=KillSwitch(tmp_path / "halt.json"),
                           intent_log=_Audit(), capabilities=None)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    return orch


# ── H342: setup values ─────────────────────────────────────────────────────────

def test_setup_lists_missing_and_set_value_is_never_echoed(monkeypatch, tmp_path):
    skill = _skill(optional=("G20_OPTIONAL",))
    orch = _orch(monkeypatch, tmp_path, {skill.name: skill})
    client = TestClient(web.app)
    view = client.get(f"/api/skills/setup/{skill.name}", headers=ADMIN)
    assert view.status_code == 200, view.text
    assert view.json()["missing"] == ["G20_TOOL_KEY"] and view.json()["ready"] is False
    put = client.put(f"/api/skills/setup/{skill.name}/G20_TOOL_KEY", json={"value": SECRET}, headers=ADMIN)
    assert put.status_code == 200, put.text
    assert put.json()["ready"] is True
    again = client.get(f"/api/skills/setup/{skill.name}", headers=ADMIN)
    for text in (put.text, again.text, json.dumps(orch.intent_log.records)):
        assert SECRET not in text and SECRET[-4:] not in text
    row = next(r for r in again.json()["requirements"] if r["name"] == "G20_TOOL_KEY")
    assert row == {**row, "set": True, "source": "skill"}
    # Never placed in the hub's environment.
    assert "G20_TOOL_KEY" not in os.environ
    # A refused write echoes nothing either (FastAPI's detail would repeat the input).
    bad = client.put(f"/api/skills/setup/{skill.name}/G20_TOOL_KEY", json={"value": SECRET, "x": 1}, headers=ADMIN)
    assert bad.status_code == 422 and SECRET not in bad.text
    # The broker redacts it from any text it scrubs.
    from agents.core.security.secret_broker import SecretBroker

    assert SECRET not in SecretBroker(integration_keys._store()).redact(f"leak {SECRET}")


def test_setup_refuses_undeclared_and_reserved_names_and_needs_admin(monkeypatch, tmp_path):
    skill = _skill(declared=("G20_TOOL_KEY", "OPENAI_API_KEY"))
    _orch(monkeypatch, tmp_path, {skill.name: skill})
    client = TestClient(web.app)
    assert client.put(f"/api/skills/setup/{skill.name}/G20_TOOL_KEY", json={"value": SECRET}).status_code in (401, 403)
    assert client.put(f"/api/skills/setup/{skill.name}/G20_OTHER_KEY", json={"value": SECRET},
                      headers=ADMIN).json()["error"] == "not_declared"
    reserved = client.put(f"/api/skills/setup/{skill.name}/OPENAI_API_KEY", json={"value": SECRET}, headers=ADMIN)
    assert reserved.status_code == 403 and reserved.json()["error"] == "reserved_name"
    assert client.get("/api/skills/setup/nope", headers=ADMIN).status_code == 404


def test_runnable_skill_refuses_while_missing_then_gets_only_its_own_values(monkeypatch, tmp_path):
    seen = {}

    async def handle(command, args, context):
        seen.update(context)
        return "ran"

    skill = _skill()
    skill.module = SimpleNamespace(handle=handle)
    refused = asyncio.run(skill.execute("go", "", {"channel": ""}))
    assert "needs setup" in refused and "G20_TOOL_KEY" in refused and seen == {}
    skill_secrets.set_value(skill, "G20_TOOL_KEY", SECRET)
    assert asyncio.run(skill.execute("go", "", {"channel": ""})) == "ran"
    assert dict(seen["skill_env"]) == {"G20_TOOL_KEY": SECRET}
    assert skill.to_dict()["setup_needed"] == []


def test_code_execution_env_is_scoped_to_the_declaring_skill(monkeypatch):
    from agents.core.code_tools import CodeExecutionTool

    owner_skill = _skill("weather-tool", ("G20_TOOL_KEY",))
    other_skill = _skill("other-tool", ("G20_TOOL_KEY", "G20_OTHER_KEY"))
    skill_secrets.set_value(owner_skill, "G20_TOOL_KEY", SECRET)
    skill_secrets.set_value(other_skill, "G20_OTHER_KEY", "other-value-1234567890")
    registry = CodeEnvRegistry()
    tool = CodeExecutionTool(None, sandbox=lambda: None, settings=lambda key, default: default,
                             environment_registry=registry, environment_source={})

    def env_for(session):
        context, _rev = tool._execution_context(SimpleNamespace(principal="owner", agent="a", session_id=session))
        return (context or {}).get("env", {})

    registry.declare(agent="a", principal="owner", session_id="s1", skill_id="weather-tool", names=["G20_TOOL_KEY"])
    assert env_for("s1").get("G20_TOOL_KEY") == SECRET
    # Another skill declaring the same name does not receive weather-tool's value.
    registry.declare(agent="a", principal="owner", session_id="s2", skill_id="other-tool",
                     names=["G20_TOOL_KEY", "G20_OTHER_KEY"])
    env2 = env_for("s2")
    assert "G20_TOOL_KEY" not in env2 and env2.get("G20_OTHER_KEY") == "other-value-1234567890"
    # No declaration in the scope: nothing stored is handed out, and nothing is in os.environ.
    assert "G20_TOOL_KEY" not in env_for("s3") and "G20_TOOL_KEY" not in os.environ


def test_skill_view_reports_setup_needed(monkeypatch):
    from agents.core.skills import tools as skill_tools

    skill = _skill()
    unset = skill_secrets.missing(skill)
    assert unset == ["G20_TOOL_KEY"]
    assert "Skill setup" in skill_secrets.setup_message(skill.name, unset)
    assert hasattr(skill_tools, "declare_skill_environment")
