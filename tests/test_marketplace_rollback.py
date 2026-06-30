"""0.58 — marketplace package rollback (restore_prior_package).

publish_skill archives the version it replaces; restore_prior_package rolls back to
the most recent archived snapshot and is reversible (the current package is archived
first, so a second call rolls forward). Covers: archive-on-publish, restore restores
the real package bytes (not just the version string), the reversible toggle, the
no-prior / unknown-skill guards, and bounded archive retention. Offline.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.skills.marketplace as mp  # noqa: E402
from agents.core.skills.marketplace import SkillMarketplace  # noqa: E402


def _market(tmp_path):
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"),
                            db_path=str(tmp_path / "market.db"))


def _write_skill(market, name, version, body):
    d = market.skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"# {name}\n> a skill\n**Version:** {version}\n", encoding="utf-8")
    (d / "main.py").write_text(body, encoding="utf-8")
    return d


def _publish(market, name, version, body):
    _write_skill(market, name, version, body)
    return market.publish_skill(name)


def test_publish_archives_prior_and_rollback_restores(tmp_path):
    m = _market(tmp_path)
    _publish(m, "foo", "1.0.0", "def register(s):\n    return 'A'\n")
    _publish(m, "foo", "2.0.0", "def register(s):\n    return 'B'\n")
    assert m._registry_version("foo") == "2.0.0"

    res = m.restore_prior_package("foo")
    assert res["ok"] is True
    assert res["restored_version"] == "1.0.0"
    assert res["previous_version"] == "2.0.0"
    assert m._registry_version("foo") == "1.0.0"

    # the real package bytes came back: installing now writes v1's main.py to disk
    assert m.install_skill("foo") is True
    assert (m.skills_dir / "foo" / "main.py").read_text() == "def register(s):\n    return 'A'\n"


def test_rollback_is_reversible_toggle(tmp_path):
    m = _market(tmp_path)
    _publish(m, "foo", "1.0.0", "v1")
    _publish(m, "foo", "2.0.0", "v2")

    assert m.restore_prior_package("foo")["restored_version"] == "1.0.0"
    assert m._registry_version("foo") == "1.0.0"
    # calling again rolls forward to 2.0.0 (the current was archived on the way back)
    assert m.restore_prior_package("foo")["restored_version"] == "2.0.0"
    assert m._registry_version("foo") == "2.0.0"


def test_rollback_no_prior_version_returns_false(tmp_path):
    m = _market(tmp_path)
    _publish(m, "foo", "1.0.0", "only")          # first publish → nothing archived
    res = m.restore_prior_package("foo")
    assert res["ok"] is False
    assert "no prior version" in res["error"]
    assert m._registry_version("foo") == "1.0.0"  # unchanged


def test_rollback_unknown_skill_returns_false(tmp_path):
    m = _market(tmp_path)
    res = m.restore_prior_package("ghost")
    assert res["ok"] is False
    assert "not in registry" in res["error"]


def test_rollback_blank_name_returns_false(tmp_path):
    m = _market(tmp_path)
    assert m.restore_prior_package("   ")["ok"] is False


def test_archive_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_VERSION_KEEP", 3)
    m = _market(tmp_path)
    for i in range(6):
        _publish(m, "foo", f"1.0.{i}", f"body{i}")
    # 6 publishes → 5 prior snapshots produced, but only the 3 most recent are kept.
    import sqlite3
    conn = sqlite3.connect(str(m.db_path))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM marketplace_skill_versions WHERE name = ?", ("foo",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 3
