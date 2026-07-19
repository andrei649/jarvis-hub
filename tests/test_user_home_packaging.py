"""User data home + frozen-app path anchoring (agents/core/paths.py).

The packaged executable keeps all personal state in one owner-visible folder
(~/Documents/Jarvis by default): .env, memory/, skills/, souls/. A plain dev
checkout has NO user home (user_home() is None) so every overlay/scaffold path
is inert and behavior is byte-identical to before.

All offline: env vars via monkeypatch, filesystem via tmp_path.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import paths  # noqa: E402


def _clear_env(monkeypatch):
    for var in ("JARVIS_USER_HOME", "JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_APP_ROOT"):
        monkeypatch.delenv(var, raising=False)


# ── resolution precedence ───────────────────────────────────────────

def test_dev_checkout_has_no_user_home(monkeypatch):
    _clear_env(monkeypatch)
    assert paths.user_home() is None
    assert paths.user_skills_dir() is None
    assert paths.user_souls_dir() is None
    assert paths.ensure_user_home() is None
    assert paths.data_root() == repo_root / "memory_logs"


def test_env_user_home_wins(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path / "docs" / "Jarvis"))
    home = paths.user_home()
    assert home == tmp_path / "docs" / "Jarvis"
    assert paths.user_skills_dir() == home / "skills"
    assert paths.user_souls_dir() == home / "souls"
    assert paths.data_root() == home / "memory"


def test_frozen_defaults_to_documents_jarvis(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        assert paths.is_frozen() is True
        assert paths.user_home() == Path.home() / "Documents" / "Jarvis"
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)


def test_jarvis_home_still_wins_over_user_home(monkeypatch, tmp_path):
    """$JARVIS_HOME is the established data-root override — a user home must
    not displace it (existing deployments keep working unchanged)."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "legacy-root"))
    assert paths.data_root() == tmp_path / "legacy-root"


def test_app_root_env_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    assert paths.app_root() == repo_root
    monkeypatch.setenv("JARVIS_APP_ROOT", str(tmp_path))
    assert paths.app_root() == tmp_path


# ── first-run scaffold ─────────────────────────────────────────────

def test_ensure_user_home_scaffolds_once(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    home_dir = tmp_path / "Jarvis"
    monkeypatch.setenv("JARVIS_USER_HOME", str(home_dir))
    # Point app_root at a fake tree carrying .env.example so the copy is exercised.
    app = tmp_path / "app"
    app.mkdir()
    (app / ".env.example").write_text("EXAMPLE_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_APP_ROOT", str(app))

    result = paths.ensure_user_home()
    assert result == home_dir
    for sub in ("memory", "skills", "souls"):
        assert (home_dir / sub).is_dir()
    assert "your data" in (home_dir / "README.md").read_text(encoding="utf-8").lower()
    assert (home_dir / ".env").read_text(encoding="utf-8") == "EXAMPLE_KEY=\n"

    # Idempotent + never overwrites: owner edits survive a re-run.
    (home_dir / ".env").write_text("EXAMPLE_KEY=my-secret\n", encoding="utf-8")
    (home_dir / "README.md").write_text("mine", encoding="utf-8")
    paths.ensure_user_home()
    assert (home_dir / ".env").read_text(encoding="utf-8") == "EXAMPLE_KEY=my-secret\n"
    assert (home_dir / "README.md").read_text(encoding="utf-8") == "mine"


def test_ensure_user_home_without_env_example(monkeypatch, tmp_path):
    """A missing .env.example (unusual bundle) must not break the scaffold."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("JARVIS_APP_ROOT", str(tmp_path / "empty-app"))
    home = paths.ensure_user_home()
    assert home is not None and (home / "memory").is_dir()
    assert not (home / ".env").exists()


# ── skills: dual-root discovery + personal writes ───────────────────

def _write_skill(root: Path, name: str, version: str = "0.1.0"):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"# {name}\n**Version:** {version}\n**Author:** t\n**Agents:** jarvis\n",
        encoding="utf-8",
    )
    return d


def test_discover_loads_bundled_and_user_skills(monkeypatch, tmp_path):
    from agents.core.skills import loader as loader_mod
    _clear_env(monkeypatch)
    bundled = tmp_path / "bundled-skills"
    bundled.mkdir()
    _write_skill(bundled, "alpha")
    home = tmp_path / "Jarvis"
    _write_skill(home / "skills", "beta")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled)
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))

    skills = loader_mod.SkillLoader().discover()
    assert "alpha" in skills and "beta" in skills


def test_user_skill_wins_registry_slot_on_name_clash(monkeypatch, tmp_path):
    from agents.core.skills import loader as loader_mod
    _clear_env(monkeypatch)
    bundled = tmp_path / "bundled-skills"
    bundled.mkdir()
    _write_skill(bundled, "alpha", version="0.1.0")
    home = tmp_path / "Jarvis"
    user_dir = _write_skill(home / "skills", "alpha", version="9.9.9")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled)
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))

    skills = loader_mod.SkillLoader().discover()
    assert skills["alpha"].version == "9.9.9"
    assert Path(skills["alpha"].path) == user_dir


def test_discover_without_user_home_is_single_root(monkeypatch, tmp_path):
    from agents.core.skills import loader as loader_mod
    _clear_env(monkeypatch)
    bundled = tmp_path / "bundled-skills"
    bundled.mkdir()
    _write_skill(bundled, "alpha")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled)
    skills = loader_mod.SkillLoader().discover()
    assert list(skills) == ["alpha"]


def test_generated_skill_written_to_user_home(monkeypatch, tmp_path):
    """LLM-generated skills are personal content → the user skills dir (still
    quarantined PENDING_REVIEW by CDX-8, exactly as in the bundled root)."""
    from agents.core.skills import loader as loader_mod
    _clear_env(monkeypatch)
    bundled = tmp_path / "bundled-skills"
    bundled.mkdir()
    home = tmp_path / "Jarvis"
    (home / "skills").mkdir(parents=True)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled)
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))

    sl = loader_mod.SkillLoader()
    name = sl.generate_skill(
        agent_id="jarvis",
        task_description="summarize weekly expenses",
        solution_steps=["load data", "sum by week"],
    )
    assert name is not None
    assert (home / "skills" / name / "SKILL.md").exists()
    assert (home / "skills" / name / "PENDING_REVIEW").exists()
    assert not (bundled / name).exists()


def test_marketplace_default_targets_user_home(monkeypatch, tmp_path):
    from agents.core.skills.marketplace import SkillMarketplace
    _clear_env(monkeypatch)
    home = tmp_path / "Jarvis"
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    m = SkillMarketplace(db_path=str(tmp_path / "mk.db"))
    assert m.skills_dir == home / "skills"


# ── heartbeat overlay from the user home ───────────────────────────

_HB = """---
agent: {agent}
cadence: cron:30 6 * * *
enabled: true
checklist:
  - {item}
---
# beat
"""


def test_heartbeat_user_home_overlay_wins(monkeypatch, tmp_path):
    from agents.core.heartbeat import HeartbeatScheduler
    _clear_env(monkeypatch)
    agents_dir = tmp_path / "agents"
    d = agents_dir / "baz"
    d.mkdir(parents=True)
    (d / "HEARTBEAT.md").write_text(_HB.format(agent="baz", item="generic step"), encoding="utf-8")
    home = tmp_path / "Jarvis"
    overlay = home / "souls" / "baz"
    overlay.mkdir(parents=True)
    (overlay / "HEARTBEAT.local.md").write_text(
        _HB.format(agent="baz", item="documents step"), encoding="utf-8")
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))

    sched = HeartbeatScheduler(agents_dir=str(agents_dir))
    sched.load_all()
    assert "documents step" in str(sched._heartbeat_configs["baz"])
