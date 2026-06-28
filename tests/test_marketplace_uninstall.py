"""0.58 — Pack Manager: uninstall an installed skill (safe remove + optional purge)."""

import pytest

from agents.core.skills.marketplace import SkillMarketplace


def _market(tmp_path):
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"),
                            db_path=str(tmp_path / "market.db"))


def _make_installed(market, name="foo", body="# Foo\n> a skill\n**Version:** 0.1.0\n"):
    d = market.skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    (d / "main.py").write_text("def register(skill):\n    pass\n", encoding="utf-8")
    return d


def test_uninstall_removes_the_installed_directory(tmp_path):
    m = _market(tmp_path)
    d = _make_installed(m)
    assert d.exists()
    assert m.uninstall_skill("foo") is True
    assert not d.exists()


def test_uninstall_missing_skill_returns_false(tmp_path):
    m = _market(tmp_path)
    assert m.uninstall_skill("nope") is False


@pytest.mark.parametrize("bad", ["../evil", "a/b", "..", ".", "x\\y", "n\x00ull", ""])
def test_uninstall_refuses_unsafe_names(tmp_path, bad):
    m = _market(tmp_path)
    with pytest.raises(ValueError):
        m.uninstall_skill(bad)


def test_uninstall_refuses_to_delete_skills_dir_itself(tmp_path):
    m = _market(tmp_path)
    # a name that resolves back to skills_dir must be refused
    with pytest.raises(ValueError):
        m.uninstall_skill(".")


def test_purge_removes_the_registry_row(tmp_path):
    m = _market(tmp_path)
    _make_installed(m, "foo")
    m.publish_skill("foo")
    assert any(s["name"] == "Foo" or s["name"] == "foo" for s in m.list_skills())
    # uninstall WITHOUT purge keeps the registry row (so reinstall can restore it)
    assert m.uninstall_skill("foo", purge=False) is True
    assert m.list_skills(), "package retained for reinstall when not purged"
    # publishing keys the row by the manifest *name* ("Foo"); purge by that key
    assert m.remove_from_registry("Foo") is True
    assert m.list_skills() == []


def test_remove_from_registry_unknown_is_false(tmp_path):
    m = _market(tmp_path)
    assert m.remove_from_registry("ghost") is False
