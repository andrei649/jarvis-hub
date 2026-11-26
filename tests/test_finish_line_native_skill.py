"""Finish line #5: a reviewed Markdown-only skill changes a later owner turn.

The real-model leg is explicit: set NERVA_RUN_SKILL_ACCEPTANCE=1 and
NERVA_SKILL_MODEL to an installed local Ollama model. No live hub is contacted.
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest


def _isolated_hub(tmp_path, monkeypatch):
    home = tmp_path / "nerva-home"
    skills = tmp_path / "skills"
    home.mkdir()
    skills.mkdir()
    (home / "keys").mkdir()
    (home / "user").mkdir()
    # Runtime data, personas, credentials and provider choices must all be synthetic
    # before product modules take any import-time environment snapshots.
    for key in tuple(os.environ):
        if key.startswith(("JARVIS_", "NERVA_", "GEMINI_", "ANTHROPIC_", "OPENAI_",
                           "OPENROUTER_", "XAI_", "DEEPINFRA_")) or key.upper() in {
                           "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("HOME", str(home / "user"))
    monkeypatch.setenv("USERPROFILE", str(home / "user"))
    for key, value in {
        "JARVIS_HOME": str(home), "JARVIS_USER_HOME": str(home / "user"),
        "JARVIS_KEY_DIR": str(home / "keys"), "JARVIS_TESTING": "1",
        "JARVIS_LLM_WARMUP": "0", "JARVIS_DRIVE_AI_SYNC": "0",
        "JARVIS_OLLAMA_URL": "http://127.0.0.1:11434",
        "JARVIS_LM_STUDIO_URL": "http://127.0.0.1:9", "MEMORY_EMBED_TURNS": "0",
    }.items():
        monkeypatch.setenv(key, value)

    from agents.core import agent as agent_mod
    from agents.core import paths, settings_db
    # The repo-local .local.md overlays are independent of JARVIS_HOME; pin the
    # shipped templates so no owner-authored persona enters the model prompt.
    shipped = Path(__file__).resolve().parents[1] / "agents"
    monkeypatch.setattr(agent_mod, "soul_path_for", lambda agent: shipped / agent / "SOUL.md")
    monkeypatch.setattr(agent_mod, "identity_path", lambda: shipped / "_identity" / "IDENTITY.md")
    assert agent_mod.soul_path_for("jarvis").is_file() and agent_mod.identity_path().is_file()
    assert paths.data_root() == home
    assert paths.user_home() == home / "user"

    from agents import web
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator
    from agents.core.routers import skills as skills_router
    from agents.core.skills import loader as loader_mod
    from agents.core.skills.usage import SkillUsageStore
    monkeypatch.setattr(settings_db, "DB_PATH", home / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    settings_db.put_category("llm", {"backend_type": "ollama", "cloud_fallback": "never"})
    settings_db.put_category("memory", {"recall_enabled": False})
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path / "bundled")
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: skills)
    monkeypatch.setattr(skills_router, "_writable_skills_dir", lambda: skills)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "finish-skill-admin")
    monkeypatch.setattr(web, "_AGENT_SETTINGS", {})
    orch = Orchestrator(JarvisConfig())
    orch.skill_usage = SkillUsageStore(home / "learning" / "skill_usage.json")
    orch.skills.attach_usage(orch.skill_usage)
    monkeypatch.setattr(web, "orch", orch)
    return orch, web.app, skills


async def test_reviewed_markdown_skill_is_available_to_later_native_turn(tmp_path, monkeypatch):
    """Model-free review/discovery evidence; use test below for actual application."""
    from agents.core.skills.usage import WRITE_REVIEWED_REPLY
    orch, app, skills = _isolated_hub(tmp_path, monkeypatch)
    request_id = uuid.uuid4().hex
    steps = ["Replace the word sun with orb in the owner's input.",
             "Sort the resulting words alphabetically.",
             "Answer with only the resulting words separated by commas."]
    headers = {"X-Admin-Token": "finish-skill-admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post("/api/skills/procedures", headers=headers, json={
            "agent": "jarvis", "description": "Transform and sort the owner's words",
            "steps": steps, "request_id": request_id})
        assert created.status_code == 202, created.text
        name = created.json()["skill"]
        folder = skills / f"procedure_{request_id}"
        assert (folder / "SKILL.md").is_file() and not (folder / "main.py").exists()
        assert (folder / "PENDING_REVIEW").is_file()
        assert orch.skills.get_skill(name).sandboxed is True

        reviewed = await client.get(f"/api/skills/pending/{name}", headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        detail = reviewed.json()
        assert detail["quarantined"] is True
        assert "main.py" not in {row["path"] for row in detail["files"]}
        assert all(step in detail["files"][0]["text"] for step in steps)
        approved = await client.post(f"/api/skills/{name}/approve", headers=headers,
                                     json={"expected_fingerprint": detail["fingerprint"]})
        assert approved.status_code == 200, approved.text
        assert approved.json()["approved"] is True
        assert not (folder / "PENDING_REVIEW").exists()
        assert not (folder / "main.py").exists()
        orch.skills.discover()
        skill = orch.skills.get_skill(name)
        assert skill is not None and not skill.sandboxed and skill.module is None
        assert orch.skills.catalog_gate(skill, "jarvis") == ""
        assert orch.skill_usage.get(name)["write_origin"] == WRITE_REVIEWED_REPLY


async def test_reviewed_markdown_skill_applies_in_owner_chat(tmp_path, monkeypatch):
    if os.getenv("NERVA_RUN_SKILL_ACCEPTANCE") != "1":
        pytest.skip("set NERVA_RUN_SKILL_ACCEPTANCE=1 with a local NERVA_SKILL_MODEL")
    model = os.getenv("NERVA_SKILL_MODEL", "")
    assert model and not model.endswith(":cloud"), "name an installed, non-cloud NERVA_SKILL_MODEL"
    orch, app, skills = _isolated_hub(tmp_path, monkeypatch)
    from agents.core import settings_db
    from agents.core.llm.base import OllamaBackend

    settings_db.put_category("llm", {"default_model": model})
    await orch.load_agents()
    assert orch.llm_router._backend_name == "ollama" and orch.llm_router._local_available
    assert orch.llm_router._local_model == model
    assert not orch.llm_router._cloud_available and not orch.llm_router._claude_available
    assert orch.llm_router.ollama_url == "http://127.0.0.1:11434"
    selected = orch.llm_router.select_backend

    def local_only(agent, prompt):
        backend, chosen, route = selected(agent, prompt)
        assert isinstance(backend, OllamaBackend)
        assert urlsplit(backend.base_url).hostname == "127.0.0.1"
        assert chosen == model and route.startswith("local")
        return backend, chosen, route

    monkeypatch.setattr(orch.llm_router, "select_backend", local_only)
    async with httpx.AsyncClient(timeout=10, trust_env=False) as local:
        installed = (await local.get(f"{orch.llm_router.ollama_url}/api/tags")).json()["models"]
    assert any(row["name"] == model and row["size"] > 0 for row in installed), "local model is not installed"

    request_id = uuid.uuid4().hex
    headers = {"X-Admin-Token": "finish-skill-admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post("/api/skills/procedures", headers=headers, json={
            "agent": "jarvis", "description": "Transform and sort the owner's words",
            "steps": ["Replace the word sun with orb in the owner's input.",
                      "Sort the resulting words alphabetically.",
                      "Answer with only the resulting words separated by commas."],
            "request_id": request_id})
        assert created.status_code == 202, created.text
        name = created.json()["skill"]
        detail = (await client.get(f"/api/skills/pending/{name}", headers=headers)).json()
        approved = await client.post(f"/api/skills/{name}/approve", headers=headers,
                                     json={"expected_fingerprint": detail["fingerprint"]})
        assert approved.status_code == 200, approved.text
        folder = skills / f"procedure_{request_id}"
        assert not (folder / "main.py").exists()
        await orch.new_session()
        answer = await client.post("/chat", headers=headers, json={
            "agent": "jarvis", "message": f"/{folder.name} sun pear"})
        assert answer.status_code == 200
        assert answer.json()["reply"].strip().lower() == "orb, pear"
        assert orch.skill_usage.get(name)["view_count"] >= 1
