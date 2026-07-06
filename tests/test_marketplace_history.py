"""0.58 — marketplace ↔ version-history wiring (opt-in).

The SkillHistory ledger is populated by the marketplace install/publish/uninstall
flow when a ledger is attached: publish/install record the version, uninstall is
recorded for the audit trail, and an upgrade chain yields a rollback target. With
no ledger attached the flow is unchanged (covered by the existing marketplace
tests).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills.marketplace import SkillMarketplace  # noqa: E402
from agents.core.skills.skill_history import SkillHistory  # noqa: E402


def _make_skill(market, name="foo", version="1.0.0"):
    d = market.skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"# {name}\n> a skill\n**Version:** {version}\n", encoding="utf-8")
    (d / "main.py").write_text("def register(skill):\n    pass\n", encoding="utf-8")
    return d


class _Clock:
    """A monotonic test clock (each call advances) — mirrors real time.time()
    advancing between successive publish/install events."""
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _market(tmp_path, *, with_history=True):
    hist = SkillHistory(tmp_path / "hist.json") if with_history else None
    m = SkillMarketplace(skills_dir=str(tmp_path / "skills"),
                         db_path=str(tmp_path / "market.db"),
                         history=hist, clock=_Clock() if with_history else None)
    return m, hist


def test_publish_and_install_recorded(tmp_path):
    m, hist = _market(tmp_path)
    _make_skill(m, "foo", "1.0.0")
    pub = m.publish_skill("foo")
    name, version = pub["name"], pub["version"]

    assert any(e["action"] == "publish" and e["version"] == version for e in hist.history(name))
    assert m.install_skill(name) is True
    assert any(e["action"] == "install" and e["version"] == version for e in hist.history(name))
    assert hist.current_version(name) == version


def test_upgrade_chain_yields_rollback_target(tmp_path):
    m, hist = _market(tmp_path)
    _make_skill(m, "foo", "1.0.0")
    p1 = m.publish_skill("foo")
    m.install_skill(p1["name"])
    # bump the manifest version and re-publish + re-install (an upgrade)
    (m.skills_dir / "foo" / "SKILL.md").write_text(
        "# foo\n> a skill\n**Version:** 2.0.0\n", encoding="utf-8")
    p2 = m.publish_skill("foo")
    m.install_skill(p2["name"])

    name = p2["name"]
    assert hist.current_version(name) == "2.0.0"
    assert hist.rollback_target(name) == "1.0.0"


def test_uninstall_is_recorded_for_audit(tmp_path):
    m, hist = _market(tmp_path)
    _make_skill(m, "foo", "1.0.0")
    pub = m.publish_skill("foo")
    m.install_skill(pub["name"])
    # uninstall takes the on-disk dir name; the version is read from the registry
    assert m.uninstall_skill("foo") is True
    assert any(e["action"] == "uninstall" for e in hist.history())


def test_no_history_attached_is_silent_and_unchanged(tmp_path):
    m, hist = _market(tmp_path, with_history=False)
    assert hist is None
    _make_skill(m, "foo", "1.0.0")
    pub = m.publish_skill("foo")          # works without a ledger, no crash
    assert pub["version"] == "1.0.0"
    assert m.install_skill(pub["name"]) is True
    assert m.uninstall_skill("foo") is True


# ── history_view() read surface (powers GET /api/skills/marketplace/history) ──

def test_history_view_reports_disabled_without_ledger(tmp_path):
    m, _ = _market(tmp_path, with_history=False)
    v = m.history_view()
    assert v["enabled"] is False
    assert v["events"] == [] and v["stats"]["total"] == 0


def test_history_view_returns_events_stats_and_rollback_target(tmp_path):
    m, _ = _market(tmp_path)
    _make_skill(m, "foo", "1.0.0")
    p1 = m.publish_skill("foo")
    m.install_skill(p1["name"])
    (m.skills_dir / "foo" / "SKILL.md").write_text(
        "# foo\n> a skill\n**Version:** 2.0.0\n", encoding="utf-8")
    p2 = m.publish_skill("foo")
    m.install_skill(p2["name"])
    name = p2["name"]

    v = m.history_view(name)
    assert v["enabled"] is True
    assert v["stats"]["total"] >= 4
    assert v["current_version"] == "2.0.0" and v["rollback_target"] == "1.0.0"
    assert v["events"] and all(e["name"] == name for e in v["events"])  # filtered by name


def test_history_view_without_name_omits_version_fields(tmp_path):
    m, _ = _market(tmp_path)
    _make_skill(m, "foo", "1.0.0")
    m.publish_skill("foo")
    v = m.history_view()
    assert v["enabled"] is True and "current_version" not in v


def test_orchestrator_skill_history_uses_shared_env_flag(monkeypatch):
    from agents.core import orchestrator

    src = (repo_root / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert 'os.environ.get("JARVIS_SKILL_HISTORY"' not in src
    assert 'env_flag("JARVIS_SKILL_HISTORY")' in src

    monkeypatch.setenv("JARVIS_SKILL_HISTORY", "0")
    assert orchestrator.skill_history_enabled() is False
    monkeypatch.setenv("JARVIS_SKILL_HISTORY", "on")
    assert orchestrator.skill_history_enabled() is True
