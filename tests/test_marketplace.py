"""
test_marketplace.py — Integration tests for Agent Marketplace & Skill Sharing (H5.8).
"""
import base64
import io
import shutil
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.skills.marketplace import SkillMarketplace

HEADERS = {"X-Admin-Token": "test-secret"}


@pytest.fixture(scope="module")
def token_client():
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


@pytest.fixture(scope="function")
def temp_skills_dir(tmp_path):
    # We point the SkillMarketplace instance to use a temporary skills dir
    # so we don't pollute the real dynamic skills/ folder in production.
    return tmp_path / "skills"


@pytest.fixture(scope="function")
def marketplace(temp_skills_dir, monkeypatch):
    temp_skills_dir.mkdir(parents=True, exist_ok=True)
    
    # We mock the DB path for testing to keep tests perfectly clean and isolated
    temp_db_path = temp_skills_dir.parent / "test_marketplace.db"
    
    # Point marketplace to this temp db and temp skills dir
    monkeypatch.setattr("agents.core.skills.marketplace.DB_PATH", temp_db_path)
    
    mp = SkillMarketplace(skills_dir=str(temp_skills_dir))
    return mp


def test_marketplace_seeding_and_empty_list(marketplace):
    # SEED checks
    assert marketplace.db_path.exists()
    
    # Empty listing check
    skills = marketplace.list_skills()
    assert isinstance(skills, list)
    assert len(skills) == 0


def test_publish_and_install_workflow(marketplace, temp_skills_dir):
    # 1. Create a dummy skill in the temporary folder
    skill_name = "weather_tracker"
    skill_dir = temp_skills_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    skill_md = """# Weather Tracker
> track local weather accurately

**Version:** 1.2.3
**Author:** jarvis-agent:steve
**Agents:** steve, ultron
**Requires:** httpx

## Commands
- `track_weather <city>` — fetch and log weather for city
"""
    main_py = """
async def handle(cmd: str, args: str, context: dict) -> str:
    return f"Weather in {args} is sunny."

def get_commands() -> list[str]:
    return ["track_weather"]

def register(skill):
    skill.register_command("track_weather", handle)
"""
    
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (skill_dir / "main.py").write_text(main_py, encoding="utf-8")
    
    # 2. Publish it to the marketplace DB
    meta = marketplace.publish_skill(skill_name)
    assert meta["name"] == "Weather Tracker"
    assert meta["version"] == "1.2.3"
    assert meta["author"] == "jarvis-agent:steve"
    
    # 3. Verify it is listed in the marketplace
    catalog = marketplace.list_skills()
    assert len(catalog) == 1
    assert catalog[0]["name"] == "Weather Tracker"
    assert catalog[0]["version"] == "1.2.3"
    assert "steve" in catalog[0]["agents"]
    assert "httpx" in catalog[0]["requires"]
    
    # 4. Remove the original folder to simulate clean system import
    shutil.rmtree(skill_dir)
    assert not skill_dir.exists()
    
    # 5. Install it from the marketplace DB
    ok = marketplace.install_skill("Weather Tracker")
    assert ok is True
    
    # 6. Verify that files are correctly recreated under target folder
    # skill name lowercase-replaced with underscore
    installed_dir = temp_skills_dir / "weather_tracker"
    assert installed_dir.exists()
    assert (installed_dir / "SKILL.md").exists()
    assert (installed_dir / "main.py").exists()
    assert "track local weather accurately" in (installed_dir / "SKILL.md").read_text(encoding="utf-8")


def test_install_nonexistent_raises(marketplace):
    with pytest.raises(ValueError):
        marketplace.install_skill("Nonexistent")


def test_install_zip_workflow(marketplace, temp_skills_dir):
    # Build a ZIP in memory representing a dummy skill
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        skill_md = """# Photo Enhancer
> clean photos dynamically

**Version:** 0.2.5
**Author:** jarvis-agent:ultron
**Agents:** ultron

## Commands
- `enhance_photo <path>` — clean image at path
"""
        zip_file.writestr("SKILL.md", skill_md)
        zip_file.writestr("main.py", "# mock python")
        zip_file.writestr("OWNER_APPROVED_IN_PROCESS", "package-supplied")
        
    zip_data = zip_buffer.getvalue()
    
    # Install from ZIP bytes
    ok = marketplace.install_from_zip(zip_data)
    assert ok is True
    
    installed_dir = temp_skills_dir / "photo_enhancer"
    assert installed_dir.exists()
    assert (installed_dir / "SKILL.md").exists()
    assert (installed_dir / "main.py").exists()
    assert (installed_dir / "EXTERNAL_SOURCE").exists()
    assert not (installed_dir / "OWNER_APPROVED_IN_PROCESS").exists()


def test_web_endpoints_integration(token_client, monkeypatch, tmp_path):
    # In order to test the endpoints in FastAPI, we point the global web.orch marketplace to our test DB/dir
    temp_skills_dir = tmp_path / "web_skills"
    temp_skills_dir.mkdir(parents=True, exist_ok=True)
    temp_db_path = tmp_path / "web_marketplace.db"
    
    monkeypatch.setattr("agents.core.skills.marketplace.DB_PATH", temp_db_path)
    
    # Point the global orchestrator's marketplace to these temp structures
    import agents.web as web_module
    
    # Ensure orch is active in the module
    assert web_module.orch is not None
    
    old_mp = web_module.orch.marketplace
    from agents.core.skills.marketplace import SkillMarketplace
    web_module.orch.marketplace = SkillMarketplace(skills_dir=str(temp_skills_dir))
    
    # Mock skills folder path inside the global loader as well, so it discovers in our temp dir
    import agents.core.skills.loader as loader_module
    old_loader_dir = loader_module.SKILLS_DIR
    monkeypatch.setattr("agents.core.skills.loader.SKILLS_DIR", temp_skills_dir)
    web_module.orch.skills.skills.clear()  # clear list
    
    try:
        # 1. Listing should be empty
        resp = token_client.get("/api/skills/marketplace", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"skills": []}
        
        # 2. Try publishing nonexistent - expect 404
        resp = token_client.post("/api/skills/marketplace/publish", json={"name": "nonexistent"}, headers=HEADERS)
        assert resp.status_code == 404
        assert "error" in resp.json()
        
        # 3. Create a real local folder in temp_skills_dir to publish
        skill_name = "translator_skill"
        skill_dir = temp_skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        (skill_dir / "SKILL.md").write_text("""# Translator Skill
> translates text bilingually

**Version:** 1.0.0
**Author:** jarvis-agent:friday

## Commands
- `translate_ro <text>` — translate to Romanian
""", encoding="utf-8")
        (skill_dir / "main.py").write_text("# mock python code", encoding="utf-8")
        
        # 4. Publish via endpoint
        resp = token_client.post("/api/skills/marketplace/publish", json={"name": skill_name}, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["published"]["name"] == "Translator Skill"
        
        # 5. List via endpoint and check catalog has our skill
        resp = token_client.get("/api/skills/marketplace", headers=HEADERS)
        assert resp.status_code == 200
        catalog = resp.json()["skills"]
        assert len(catalog) == 1
        assert catalog[0]["name"] == "Translator Skill"
        
        # 6. Delete folder and install via dynamic endpoint
        shutil.rmtree(skill_dir)
        assert not skill_dir.exists()
        
        resp = token_client.post("/api/skills/marketplace/install", json={"name": "Translator Skill"}, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["installed"] == "Translator Skill"
        
        # Re-check that files are back!
        installed_dir = temp_skills_dir / "translator_skill"
        assert installed_dir.exists()
        assert (installed_dir / "SKILL.md").exists()
        
        # 7. Test install ZIP via base64 upload
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("SKILL.md", """# Calc Skill
> does basic additions

**Version:** 0.1.0
**Author:** jarvis-agent:friday

## Commands
- `add_numbers <num>` — add numbers
""")
            zip_file.writestr("main.py", "# code")
            
        zip_base64 = base64.b64encode(zip_buffer.getvalue()).decode("utf-8")
        
        resp = token_client.post("/api/skills/marketplace/install-zip", json={"zip_base64": zip_base64}, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        
        # Re-check calc_skill folder exists!
        assert (temp_skills_dir / "calc_skill").exists()
        assert (temp_skills_dir / "calc_skill" / "SKILL.md").exists()
        
    finally:
        # Restore defaults
        web_module.orch.marketplace = old_mp
        monkeypatch.setattr("agents.core.skills.loader.SKILLS_DIR", old_loader_dir)
