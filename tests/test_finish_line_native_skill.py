"""Finish-line items 4 and 5: reviewed Markdown skills change a later owner turn.

The real-model legs are explicit: set NERVA_RUN_SKILL_ACCEPTANCE=1 for the
owner-authored path, NERVA_RUN_PROPOSED_SKILL_ACCEPTANCE=1 for the native
model-authored tool path, or NERVA_RUN_LEGACY_LESSON_ACCEPTANCE=1 for the
assistant's chat lesson marker, with NERVA_SKILL_MODEL set to an installed local Ollama model.
No live hub is contacted.
"""

import asyncio
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


def test_chat_lesson_keeps_format_rule_without_turning_narration_into_example(tmp_path, monkeypatch):
    orch, _, skills = _isolated_hub(tmp_path, monkeypatch)
    reply = (
        "Sir, I inferred a reusable label transformation from the owner's example.\n"
        "agent=intruder\n"
        "For future inputs I will sort unique uppercase labels and add TAG:. "
        "[learn: normalize labels | uppercase and deduplicate labels, sort labels, "
        "return only semicolon-separated TAG:LABEL tokens without explanation | normalize_labels]"
        " unique_tail_" + "Z" * 300
    )
    name = orch._detect_skill_learning({"jarvis": reply}, reply, None)
    assert name
    body = (skills / name / "SKILL.md").read_text(encoding="utf-8")
    assert "return only semicolon-separated TAG:LABEL tokens without explanation" in body
    assert "## Example Output" not in body
    assert "Sir, I inferred" not in body
    detail = orch.skills.pending_skill_detail(name)
    assert detail
    note = detail["review_note"]
    expected_excerpt = reply[:200].replace("\n", "\\n")
    assert f"source_excerpt_for_review_only={expected_excerpt}" in note
    assert "unique_tail_" not in note
    assert [line for line in note.splitlines() if line.startswith("agent=")] == ["agent=jarvis"]

    explicit = orch.skills.generate_skill(
        "jarvis", "render a real sample", ["return only the sample"],
        output="TAG:APPLE;TAG:MANGO",
    )
    assert explicit
    assert "## Example Output\n```\nTAG:APPLE;TAG:MANGO\n```" in (
        skills / explicit / "SKILL.md").read_text(encoding="utf-8")


def test_chat_lesson_prompt_requests_explicit_output_rules():
    from agents.core.agent import Agent

    agent = Agent.__new__(Agent)
    agent.id = "jarvis"
    agent.name = "Jarvis"
    prompt = agent.build_prompt("Teach this transformation", {"_can_propose_skill_marker": True})
    assert "Include any required response format and what to omit in the steps" in prompt


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


@pytest.mark.timeout(300)
async def test_local_model_proposes_and_uses_reviewed_procedure(tmp_path, monkeypatch):
    """A native owner tool call learns steps from an example, then review changes a fresh run."""
    if os.getenv("NERVA_RUN_PROPOSED_SKILL_ACCEPTANCE") != "1":
        pytest.skip("set NERVA_RUN_PROPOSED_SKILL_ACCEPTANCE=1 with a local NERVA_SKILL_MODEL")
    model = os.getenv("NERVA_SKILL_MODEL", "")
    assert model and not model.endswith(":cloud")
    orch, app, skills = _isolated_hub(tmp_path, monkeypatch)
    from agents.core import settings_db
    from agents.core.llm.base import OllamaBackend
    from agents.core.skills.usage import WRITE_TOOL

    settings_db.put_category("llm", {"default_model": model, "tool_loop_enabled": True})
    orch.load_runtime_settings()
    assert orch.get_setting("llm.tool_loop_enabled") is True
    await orch.load_agents()
    # Detection prefers a different model already resident in Ollama.
    orch.llm_router.set_active_model(model)
    assert orch.llm_router._backend_name == "ollama" and orch.llm_router._local_available
    assert orch.llm_router._local_model == model and not orch.llm_router._cloud_available
    assert not orch.llm_router._claude_available
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
        installed = (await local.get("http://127.0.0.1:11434/api/tags")).json()["models"]
    assert any(row["name"] == model and row["size"] > 0 for row in installed)

    observed = []
    offered = []
    generate = OllamaBackend.generate_tool_turn

    async def trace(self, *args, **kwargs):
        offered.extend(tool.name for tool in kwargs.get("tools", []))
        turn = await generate(self, *args, **kwargs)
        observed.extend(turn.tool_calls)
        return turn

    monkeypatch.setattr(OllamaBackend, "generate_tool_turn", trace)
    headers = {"X-Admin-Token": "finish-skill-admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        await orch.new_session()
        taught = await asyncio.wait_for(client.post("/chat", headers=headers, json={
            "agent": "jarvis", "message": (
                "A label-cleanup task succeeded. Input: pear, lime, pear. "
                "Output: TAG:LIME | TAG:PEAR. Infer the reusable transformation "
                "from that example and save it as a new skill for my review. "
                "Do not apply it to another input yet.")}), timeout=150)
        assert taught.status_code == 200, taught.text
        assert "skill_propose" in offered, offered
        proposals = [call for call in observed if call.name == "skill_propose"]
        assert proposals, (taught.json()["reply"], [call.name for call in observed])
        assert taught.json()["model_calls"] == [{"provider": "ollama", "model": model}]
        args = proposals[-1].arguments
        assert args and isinstance(args.get("description"), str)
        assert isinstance(args.get("steps"), list) and args["steps"]
        folders = [path for path in skills.iterdir() if (path / "PENDING_REVIEW").is_file()]
        assert len(folders) == 1, (taught.json()["reply"], args)
        folder = folders[0]
        assert not (folder / "main.py").exists()
        name = orch.skills.manifest_name(folder, (folder / "SKILL.md").read_text(encoding="utf-8"))
        usage = orch.skill_usage.get(name)
        assert usage["agent_created"] is True and usage["write_origin"] == WRITE_TOOL
        assert orch.skills.get_skill(name).sandboxed is True

        # The same challenge cannot use the quarantined skill before review.
        challenge = f"/{folder.name} mango, apple, mango"
        await orch.new_session()
        before = await client.post("/chat", headers=headers, json={"agent": "jarvis", "message": challenge})
        assert before.status_code == 200 and before.json()["reply"].strip() != "TAG:APPLE | TAG:MANGO"
        detail = await client.get(f"/api/skills/pending/{name}", headers=headers)
        assert detail.status_code == 200 and detail.json()["quarantined"] is True
        reviewed = detail.json()
        assert reviewed["fingerprint"] and any(row["path"] == "SKILL.md" for row in reviewed["files"])
        approved = await client.post(f"/api/skills/{name}/approve", headers=headers,
                                     json={"expected_fingerprint": reviewed["fingerprint"]})
        assert approved.status_code == 200 and approved.json()["approved"] is True
        assert not (folder / "PENDING_REVIEW").exists()
        assert orch.skills.catalog_gate(orch.skills.get_skill(name), "jarvis") == ""

        await orch.new_session()
        used = await asyncio.wait_for(client.post("/chat", headers=headers, json={
            "agent": "jarvis", "message": challenge}), timeout=90)
        assert used.status_code == 200, used.text
        assert len({taught.json()["session_id"], before.json()["session_id"], used.json()["session_id"]}) == 3
        assert used.json()["model_calls"] == [{"provider": "ollama", "model": model}]
        assert used.json()["reply"].strip() == "TAG:APPLE | TAG:MANGO", used.json()["reply"]
        assert orch.skill_usage.get(name)["view_count"] >= 1


@pytest.mark.timeout(300)
async def test_local_model_chat_lesson_changes_later_reviewed_turn(tmp_path, monkeypatch):
    """Ordinary owner chat learns a legacy marker; review makes its Markdown useful later."""
    if os.getenv("NERVA_RUN_LEGACY_LESSON_ACCEPTANCE") != "1":
        pytest.skip("set NERVA_RUN_LEGACY_LESSON_ACCEPTANCE=1 with a local NERVA_SKILL_MODEL")
    model = os.getenv("NERVA_SKILL_MODEL", "")
    assert model and not model.endswith(":cloud"), "name an installed, non-cloud NERVA_SKILL_MODEL"
    orch, app, skills = _isolated_hub(tmp_path, monkeypatch)
    from agents.core import settings_db
    from agents.core.llm.base import OllamaBackend
    from agents.core.skills.usage import WRITE_LEARNING
    from agents.web import ChatRequest

    assert ChatRequest.model_fields["agent"].default == "jarvis"

    settings_db.put_category("llm", {"default_model": model, "tool_loop_enabled": False})
    orch.load_runtime_settings()
    assert orch.get_setting("llm.tool_loop_enabled") is False
    await orch.load_agents()
    orch.llm_router.set_active_model(model)
    assert orch.llm_router._backend_name == "ollama" and orch.llm_router._local_available
    assert orch.llm_router._local_model == model and not orch.llm_router._cloud_available
    assert not orch.llm_router._claude_available
    assert orch.llm_router.ollama_url == "http://127.0.0.1:11434"
    selected = orch.llm_router.select_backend

    def local_only(agent, prompt):
        backend, chosen, route = selected(agent, prompt)
        assert isinstance(backend, OllamaBackend)
        assert urlsplit(backend.base_url).hostname == "127.0.0.1"
        assert chosen == model and route.startswith("local")
        return backend, chosen, route

    monkeypatch.setattr(orch.llm_router, "select_backend", local_only)
    detect = orch._detect_skill_learning
    saw_jarvis_marker = False

    def observe_lesson(responses, synthesized, intent):
        nonlocal saw_jarvis_marker
        reply = responses.get("jarvis")
        saw_jarvis_marker |= isinstance(reply, str) and "[learn:" in reply
        return detect(responses, synthesized, intent)

    monkeypatch.setattr(orch, "_detect_skill_learning", observe_lesson)
    async with httpx.AsyncClient(timeout=10, trust_env=False) as local:
        installed = (await local.get("http://127.0.0.1:11434/api/tags")).json()["models"]
    assert any(row["name"] == model and row["size"] > 0 for row in installed)

    headers = {"X-Admin-Token": "finish-skill-admin"}
    author_id = await orch.new_session(f"lesson_author_{uuid.uuid4().hex}")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        taught = await asyncio.wait_for(client.post("/chat", headers=headers, json={
            "session_id": author_id,
            "message": ("A label task just succeeded. Input: pear lime pear. "
                        "Output: TAG:LIME;TAG:PEAR. Infer the reusable transformation "
                        "from this example and propose it for review using your normal lesson marker. "
                        "Keep each step short. For future inputs, return only the transformed "
                        "result without explanation or code fences. Do not process another input yet.")}), timeout=150)
        assert taught.status_code == 200
        assert taught.json()["session_id"] == author_id
        assert taught.json()["model_calls"] == [{"provider": "ollama", "model": model}]
        assert saw_jarvis_marker
        folders = [path for path in skills.iterdir() if (path / "PENDING_REVIEW").is_file()]
        assert len(folders) == 1
        folder = folders[0]
        assert (folder / "SKILL.md").is_file()
        name = orch.skills.manifest_name(folder, (folder / "SKILL.md").read_text(encoding="utf-8"))
        usage = orch.skill_usage.get(name)
        assert usage["agent_created"] is True and usage["write_origin"] == WRITE_LEARNING
        assert orch.skills.get_skill(name).sandboxed is True
        assert orch.skills.catalog_gate(orch.skills.get_skill(name), "jarvis") == "sandboxed"

        challenge = f"/{folder.name} mango apple mango"
        expected = "TAG:APPLE;TAG:MANGO"
        before_id = await orch.new_session(f"lesson_before_{uuid.uuid4().hex}")
        before = await client.post("/chat", headers=headers, json={
            "session_id": before_id, "message": challenge})
        assert before.status_code == 200 and before.json()["session_id"] == before_id
        assert before.json().get("model_calls") is None
        assert before.json()["reply"].strip() != expected
        assert orch.skill_usage.get(name)["view_count"] == 0

        reviewed = await client.get(f"/api/skills/pending/{name}", headers=headers)
        assert reviewed.status_code == 200 and reviewed.json()["quarantined"] is True
        detail = reviewed.json()
        assert detail["fingerprint"] and detail["review_note"].startswith("agent=jarvis\n")
        assert detail["more_files"] == 0
        assert {row["path"] for row in detail["files"]} == {
            path.name for path in folder.iterdir() if path.is_file() and path.name != "PENDING_REVIEW"}
        assert all(isinstance(row.get("text"), str) and not row.get("truncated") for row in detail["files"])
        approved = await client.post(f"/api/skills/{name}/approve", headers=headers,
                                     json={"expected_fingerprint": detail["fingerprint"]})
        assert approved.status_code == 200 and approved.json()["approved"] is True
        assert not (folder / "PENDING_REVIEW").exists()
        assert orch.skills.catalog_gate(orch.skills.get_skill(name), "jarvis") == ""

        after_id = await orch.new_session(f"lesson_after_{uuid.uuid4().hex}")
        used = await asyncio.wait_for(client.post("/chat", headers=headers, json={
            "session_id": after_id, "message": challenge}), timeout=90)
        assert used.status_code == 200
        assert used.json()["session_id"] == after_id
        assert len({author_id, before_id, after_id}) == 3
        assert used.json()["model_calls"] == [{"provider": "ollama", "model": model}]
        assert used.json()["reply"].strip() == expected
        assert orch.skill_usage.get(name)["view_count"] >= 1
