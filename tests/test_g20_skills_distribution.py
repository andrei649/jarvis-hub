"""G20 skills distribution — owner-side acceptance (H342 setup values, H025/H335 taps).

What the owner can do: see which variables a skill needs, set them without ever seeing a
value again, add a trusted skill source behind an approval card, search every source by
trust, install from a tap into quarantine. What nobody can do: read a value back, get one
skill's value into another skill's run, trust a source without a person accepting the
card, pin a tap to a branch, or install a refused tap entry or bypass the pinned import.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import integration_keys
from agents.core.autonomy import irreversible
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.code_env import CodeEnvRegistry
from agents.core.routers import skill_taps as taps_router
from agents.core.security.capability import KillSwitch
from agents.core.skills import skill_secrets, taps
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


# ── H025: taps ─────────────────────────────────────────────────────────────────

def _skill_md(name, description="A tapped skill.", extra=""):
    return (f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n# {name}\n\nDo the thing.\n").encode()


GOOD = _skill_md("good-skill", extra="required_environment_variables:\n  - G20_TOOL_KEY\n")
REF = b"reference notes\n"
FILES = {
    "skills/good-skill/SKILL.md": GOOD,
    "skills/good-skill/references/notes.md": REF,
    "skills/good-skill/scripts/run.py": b"print(1)\n",
    "skills/liar/SKILL.md": _skill_md("someone-else"),
    "skills/Bad_Name/SKILL.md": _skill_md("Bad_Name"),
    "skills/broken/SKILL.md": b"no frontmatter at all",
    "skills/escape/../../etc/SKILL.md": _skill_md("escape"),
    "docs/README.md": b"not a skill",
}


def _fake_fetcher(log, files=FILES):
    @asynccontextmanager
    async def opener(orch, gate):
        async def fetch(url, limit):
            from urllib.parse import urlparse

            host = urlparse(url).hostname
            assert gate("skill-import", "GET", url, host) is None
            log.append(url)
            assert COMMIT in url
            if host == "api.github.com":
                tree = [{"type": "blob", "path": p} for p in files]
                return json.dumps({"sha": "t" * 40, "tree": tree, "truncated": False}).encode()
            return files[url.split(f"/{COMMIT}/", 1)[1]]
        yield fetch
    return opener


def _add_and_approve(client, orch, *, trust="trusted"):
    response = client.post("/api/skills/taps", json={"repo": "acme/skills", "commit": COMMIT, "trust": trust},
                           headers=ADMIN)
    assert response.status_code == 202, response.text
    task = orch.autonomy.tasks[response.json()["task_id"]]
    task.decided_by, task.decision = "owner", "accept"
    assert asyncio.run(irreversible.execute(task, orch=orch))["status"] == "ok"
    return task


def test_tap_add_needs_admin_a_pinned_commit_and_a_human_accepted_card(monkeypatch, tmp_path):
    orch = _orch(monkeypatch, tmp_path)
    client = TestClient(web.app)
    body = {"repo": "acme/skills", "commit": COMMIT, "trust": "trusted"}
    assert client.post("/api/skills/taps", json=body).status_code in (401, 403)
    branch = client.post("/api/skills/taps", json={**body, "commit": "main".ljust(40, "x")}, headers=ADMIN)
    assert branch.status_code == 422 and branch.json()["error"] == "commit_not_pinned"
    assert client.post("/api/skills/taps", json={**body, "trust": "official"},
                       headers=ADMIN).json()["error"] == "invalid_trust"
    queued = client.post("/api/skills/taps", json=body, headers=ADMIN)
    assert queued.status_code == 202 and queued.json()["status"] == "pending_approval"
    task = orch.autonomy.tasks[queued.json()["task_id"]]
    assert task.kind == taps.APPROVAL_KIND and task.risk_tier == irreversible.RISK_TIER
    assert task.payload["source_url"] == f"https://github.com/acme/skills/tree/{COMMIT}/skills"
    assert client.post("/api/skills/taps", json=body, headers=ADMIN).json()["error"] == "exists"
    # Pending: not searchable, not refreshable.
    assert all(r["tap"] != "acme--skills" for r in client.get("/api/skills/taps/search?q=good").json()["results"])
    assert client.post("/api/skills/taps/acme--skills/refresh", json={}, headers=ADMIN).json()["error"] == "not_approved"
    # A machine decision, or an edited card, does not activate it.
    task.decided_by, task.decision = "policy", "accept"
    assert asyncio.run(irreversible.execute(task, orch=orch))["reason"] == "human_decision_required"
    task.decided_by, task.decision = "owner", "accept"
    task.payload = {**task.payload, "commit": "d" * 40}
    assert asyncio.run(irreversible.execute(task, orch=orch))["reason"] == "payload_changed"
    task.payload = {**task.payload, "commit": COMMIT}
    assert asyncio.run(irreversible.execute(task, orch=orch))["status"] == "ok"
    listed = {t["id"]: t for t in client.get("/api/skills/taps").json()["taps"]}
    assert listed["acme--skills"]["status"] == "active" and listed["acme--skills"]["approved_by"] == "owner"
    assert any(r["action"] == "skill.tap.add" for r in orch.intent_log.records)
    # Removing narrows trust at once; built-ins cannot be removed.
    assert client.delete("/api/skills/taps/acme--skills", headers=ADMIN).json()["removed"] == "acme--skills"
    assert asyncio.run(irreversible.execute(task, orch=orch))["reason"] == "not_requested"


def test_refresh_crosses_egress_and_refuses_untrusted_tap_content(monkeypatch, tmp_path):
    orch = _orch(monkeypatch, tmp_path)
    client = TestClient(web.app)
    _add_and_approve(client, orch)
    log = []
    monkeypatch.setattr(taps_router, "_open_fetcher", _fake_fetcher(log))
    refreshed = client.post("/api/skills/taps/acme--skills/refresh", json={}, headers=ADMIN)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["egress_grants"] == len(log) >= 3
    assert all(url.startswith(("https://api.github.com/", "https://raw.githubusercontent.com/")) for url in log)
    index = {e["slug"]: e for e in taps._read()["taps"][0]["index"]}
    good = index["good-skill"]
    assert good["content_sha256"] == hashlib.sha256(GOOD).hexdigest()
    assert good["references"] == [{"path": "skills/good-skill/references/notes.md",
                                   "content_sha256": hashlib.sha256(REF).hexdigest()}]
    assert good["carries_code"] is True and good["required_env"] == ["G20_TOOL_KEY"]
    assert index["liar"]["refused"] == "name_mismatch"
    assert index["Bad_Name"]["refused"] == "unsafe_name"
    assert index["broken"]["refused"] == "invalid_skill_md"
    assert index["escape"]["refused"] == "unsafe_path"
    assert not any("escape" in url or "etc" in url for url in log)
    refused = client.post("/api/skills/taps/install", json={"tap": "acme--skills", "skill": "liar"}, headers=ADMIN)
    assert refused.status_code == 422 and refused.json()["error"] == "refused_entry"
    assert orch.skill_importer.calls == []


def test_egress_gate_refuses_hosts_outside_the_tap_hosts(monkeypatch, tmp_path):
    orch = _orch(monkeypatch, tmp_path)
    gate = taps_router._egress_gate(orch, [0])
    assert gate("skill-import", "GET", "https://evil.example/x", "evil.example") == "host_not_allowed"


def test_real_refresh_client_is_governed_and_follows_no_redirect(monkeypatch, tmp_path):
    """The production fetcher: the egress client with the kernel gate, no redirects."""
    import httpx

    orch = _orch(monkeypatch, tmp_path)
    seen = []

    def transport_factory(_target):
        def respond(request):
            # The client pins the resolved address; the name it asked for is the Host header.
            seen.append(request.headers["host"] + request.url.path)
            if request.headers["host"] == "api.github.com":
                return httpx.Response(200, json={"tree": [{"type": "blob", "path": "skills/good-skill/SKILL.md"}]})
            if request.url.path.endswith("/good-skill/SKILL.md"):
                return httpx.Response(302, headers={"location": "https://evil.example/x"})
            return httpx.Response(404)
        return httpx.MockTransport(respond)

    orch.skill_importer._remote_resolver = lambda host, *, mode: (["93.184.216.34"], None)
    orch.skill_importer._remote_transport_factory = transport_factory
    client = TestClient(web.app)
    _add_and_approve(client, orch)
    refused = client.post("/api/skills/taps/acme--skills/refresh", json={}, headers=ADMIN)
    assert refused.status_code == 502 and refused.json()["error"] == "fetch_failed"
    assert len(seen) == 2 and not any("evil.example" in url for url in seen), seen
    assert [r["action"] for r in orch.intent_log.records].count("authorize:plugin.egress") == 2


def test_tap_install_goes_through_the_pinned_quarantined_import(monkeypatch, tmp_path):
    orch = _orch(monkeypatch, tmp_path)
    client = TestClient(web.app)
    _add_and_approve(client, orch)
    monkeypatch.setattr(taps_router, "_open_fetcher", _fake_fetcher([]))
    assert client.post("/api/skills/taps/acme--skills/refresh", json={}, headers=ADMIN).status_code == 200
    assert client.post("/api/skills/taps/install", json={"tap": "acme--skills", "skill": "good-skill"}
                       ).status_code in (401, 403)
    response = client.post("/api/skills/taps/install", json={"tap": "acme--skills", "skill": "good-skill"},
                           headers=ADMIN)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["quarantined"] is True and answer["status"] == "installed_review_required"
    assert answer["tap"] == "acme--skills" and answer["trust"] == "trusted"
    (source, name, pin), = orch.skill_importer.calls
    assert source == "acme/skills" and name == "good-skill"
    assert (pin.repo, pin.commit, pin.entry_path) == ("acme/skills", COMMIT, "skills/good-skill/SKILL.md")
    assert pin.content_sha256 == hashlib.sha256(GOOD).hexdigest()
    actions = [r["action"] for r in orch.intent_log.records]
    assert actions.count("authorize:skill.install") == 2
    # A tampered index on disk is not trusted: the entry no longer holds up, nothing is fetched.
    data = taps._read()
    entry = next(e for e in data["taps"][0]["index"] if e["slug"] == "good-skill")
    entry["entry_path"] = "../../SKILL.md"
    taps._write(data)
    tampered = client.post("/api/skills/taps/install", json={"tap": "acme--skills", "skill": "good-skill"},
                           headers=ADMIN)
    assert tampered.status_code == 422 and len(orch.skill_importer.calls) == 1
    assert client.post("/api/skills/taps/install", json={"tap": "hermes-catalog", "skill": "x"},
                       headers=ADMIN).status_code == 409


def test_search_ranks_by_trust_and_lists_pins(monkeypatch, tmp_path):
    orch = _orch(monkeypatch, tmp_path)
    client = TestClient(web.app)
    _add_and_approve(client, orch, trust="community")
    monkeypatch.setattr(taps_router, "_open_fetcher", _fake_fetcher([]))
    client.post("/api/skills/taps/acme--skills/refresh", json={}, headers=ADMIN)
    everything = client.get("/api/skills/taps/search?limit=100").json()["results"]
    ranks = [taps.TRUST_RANK[r["trust"]] for r in everything]
    assert ranks == sorted(ranks)
    found = client.get("/api/skills/taps/search?q=good-skill").json()["results"]
    assert [(r["tap"], r["slug"], r["installable"]) for r in found] == [("acme--skills", "good-skill", True)]
    assert client.get("/api/skills/taps/search?q=good&tap=acme--skills").json()["matched"] >= 1
    listing = client.get("/api/skills/taps").json()
    ids = [t["id"] for t in listing["taps"]]
    assert ids[:2] == ["hermes-catalog", "hermes"]
    align = listing["pin_alignment"]
    assert align["available"] is True and align["aligned"] is False
    assert align["same_bytes"] + align["changed"] + align["not_in_catalog"] == align["import_pin"]["skills"]
    assert client.delete("/api/skills/taps/hermes--x", headers=ADMIN).status_code == 404
