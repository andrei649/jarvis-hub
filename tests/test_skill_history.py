"""0.58 — skill version-history ledger (the rollback-target foundation).

Covers agents/core/skills/skill_history.py: event recording + required fields,
history ordering/filtering, current vs rollback-target derivation (incl. upgrade
chains and uninstall-ignored-for-version), distinct versions, persistence,
corrupt-file safety, bounded pruning, and stats.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills.skill_history import SkillHistory  # noqa: E402


def _h(tmp_path, **kw):
    return SkillHistory(tmp_path / "history.json", **kw)


def test_record_shape_and_required_fields(tmp_path):
    h = _h(tmp_path)
    e = h.record("weather", "1.0.0", "install", now=10.0, meta={"by": "owner"})
    assert e["id"].startswith("sh-")
    assert e["name"] == "weather" and e["version"] == "1.0.0"
    assert e["action"] == "install" and e["at"] == 10.0 and e["meta"] == {"by": "owner"}
    with pytest.raises(ValueError):
        h.record("", "1.0.0", "install", now=1.0)
    with pytest.raises(ValueError):
        h.record("x", "", "install", now=1.0)


def test_history_newest_first_and_filtered(tmp_path):
    h = _h(tmp_path)
    h.record("a", "1", "install", now=1.0)
    h.record("b", "1", "install", now=2.0)
    h.record("a", "2", "install", now=3.0)
    assert [e["version"] for e in h.history("a")] == ["2", "1"]
    assert [e["name"] for e in h.history()] == ["a", "b", "a"]   # all, newest-first


def test_current_and_rollback_target_on_upgrade_chain(tmp_path):
    h = _h(tmp_path)
    h.record("pkg", "1.0.0", "publish", now=1.0)
    h.record("pkg", "1.0.0", "install", now=2.0)
    h.record("pkg", "2.0.0", "install", now=3.0)   # upgrade
    h.record("pkg", "3.0.0", "install", now=4.0)   # upgrade again

    assert h.current_version("pkg") == "3.0.0"
    assert h.rollback_target("pkg") == "2.0.0"     # the version before current
    assert h.versions("pkg") == ["3.0.0", "2.0.0", "1.0.0"]


def test_single_version_has_no_rollback_target(tmp_path):
    h = _h(tmp_path)
    h.record("solo", "1.0.0", "install", now=1.0)
    assert h.current_version("solo") == "1.0.0"
    assert h.rollback_target("solo") is None


def test_unknown_skill_is_none(tmp_path):
    h = _h(tmp_path)
    assert h.current_version("ghost") is None
    assert h.rollback_target("ghost") is None
    assert h.versions("ghost") == []


def test_uninstall_does_not_establish_a_version(tmp_path):
    h = _h(tmp_path)
    h.record("pkg", "1.0.0", "install", now=1.0)
    h.record("pkg", "2.0.0", "install", now=2.0)
    h.record("pkg", "2.0.0", "uninstall", now=3.0)   # recorded for audit only
    # uninstall is ignored for version derivation → current still reflects installs
    assert h.current_version("pkg") == "2.0.0"
    assert h.rollback_target("pkg") == "1.0.0"
    # ...but the uninstall event is in the audit history
    assert any(e["action"] == "uninstall" for e in h.history("pkg"))


def test_reinstall_of_older_version_moves_current(tmp_path):
    # install 1, upgrade to 2, then roll back to 1 → current is 1 again, rollback→2
    h = _h(tmp_path)
    h.record("pkg", "1.0.0", "install", now=1.0)
    h.record("pkg", "2.0.0", "install", now=2.0)
    h.record("pkg", "1.0.0", "install", now=3.0)
    assert h.current_version("pkg") == "1.0.0"
    assert h.rollback_target("pkg") == "2.0.0"
    assert h.versions("pkg") == ["1.0.0", "2.0.0"]   # distinct, by most-recent occurrence


def test_persistence_corrupt_safety_and_stats(tmp_path):
    p = tmp_path / "history.json"
    h = SkillHistory(p)
    h.record("a", "1", "install", now=1.0)
    h.record("a", "1", "uninstall", now=2.0)
    h.record("b", "1", "publish", now=3.0)
    # survives a fresh instance over the same path
    assert SkillHistory(p).stats() == {"total": 3, "skills": 2,
                                       "by_action": {"install": 1, "uninstall": 1, "publish": 1}}
    # corrupt file degrades to empty, still writable
    p.write_text("garbage {{")
    h2 = SkillHistory(p)
    assert h2.stats()["total"] == 0
    assert h2.record("c", "1", "install", now=4.0)["name"] == "c"


def test_bounded_prunes_oldest_first(tmp_path):
    h = _h(tmp_path, max_keep=3)
    for i in range(5):
        h.record("a", str(i), "install", now=float(i))
    kept = {e["version"] for e in h.history("a")}
    assert kept == {"2", "3", "4"}   # the 2 oldest evicted
