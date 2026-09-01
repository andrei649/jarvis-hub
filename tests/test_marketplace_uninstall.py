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


# ── purge must actually unpublish (the registry is keyed by MANIFEST TITLE) ──
#
# publish_skill stores `manifest.get("name", skill_name)` — the SKILL.md '# ' heading —
# in marketplace_skills.name (marketplace.py:367), but uninstall_skill(purge=True) called
# remove_from_registry(skill_name) with the ON-DISK FOLDER, and discarded its boolean. For
# every skill bundled in this repo the two differ (skills/weather -> '# Weather Intel'), so
# the delete matched nothing while the caller was told the package was gone. The HUD then
# rendered `"purged": body.purge` — the request flag echoed back — as a result, so the
# operator read "registry row purged" at the moment the published package survived, blob
# and all, re-installable by anyone with the admin token.

_WEATHER = "# Weather Intel\n> forecasts\n**Version:** 1.0.0\n"


def test_purge_unpublishes_a_skill_whose_title_differs_from_its_folder(tmp_path):
    m = _market(tmp_path)
    _make_installed(m, name="weather", body=_WEATHER)
    m.publish_skill("weather")
    assert [s["name"] for s in m.list_skills()] == ["Weather Intel"]

    assert m.uninstall_skill("weather", purge=True) is True
    assert m.list_skills() == [], (
        "purge left the published package behind — it is still installable by anyone "
        "with the admin token"
    )


def test_purge_reports_whether_the_registry_row_actually_went(tmp_path):
    """The caller must be able to tell an unpublish from a no-op."""
    m = _market(tmp_path)
    _make_installed(m, name="weather", body=_WEATHER)
    m.publish_skill("weather")

    assert m.purge_registry_row("weather") is True     # published -> deleted
    assert m.purge_registry_row("weather") is False    # already gone -> honest False


def test_purge_of_an_unpublished_skill_still_uninstalls_and_says_nothing_was_purged(tmp_path):
    m = _market(tmp_path)
    d = _make_installed(m, name="weather", body=_WEATHER)   # installed, never published

    assert m.uninstall_skill("weather", purge=True) is True   # the directory did go
    assert not d.exists()
    assert m.purge_registry_row("weather") is False           # and there was no row to drop


# ── the API surface: `purged` must be an OBSERVATION, never the request flag ──

def test_api_reports_purged_false_when_nothing_was_published(tmp_path, monkeypatch):
    """POST .../uninstall {purge: true} on an unpublished skill must not claim a purge.

    The route used to return `"purged": body.purge`, so this case answered purged=true
    while no row had ever existed. An operator reading that believes the published
    package is gone.
    """
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import agents.web as web

    m = _market(tmp_path)
    _make_installed(m, name="weather", body=_WEATHER)     # installed, never published

    skills = SimpleNamespace(skills={}, revoke_approval=lambda *_a, **_k: None)
    monkeypatch.setattr(web, "orch", SimpleNamespace(marketplace=m, skills=skills))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "t")
    client = TestClient(web.app)                          # no lifespan: web.orch stays ours

    r = client.post("/api/skills/marketplace/uninstall",
                    json={"name": "weather", "purge": True},
                    headers={"X-Admin-Token": "t"})
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True                     # the directory really went
    assert r.json()["purged"] is False, "claimed a purge with no registry row to purge"


def test_api_reports_purged_true_only_when_the_row_really_went(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import agents.web as web

    m = _market(tmp_path)
    _make_installed(m, name="weather", body=_WEATHER)
    m.publish_skill("weather")
    assert [s["name"] for s in m.list_skills()] == ["Weather Intel"]

    skills = SimpleNamespace(skills={}, revoke_approval=lambda *_a, **_k: None)
    monkeypatch.setattr(web, "orch", SimpleNamespace(marketplace=m, skills=skills))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "t")
    client = TestClient(web.app)

    r = client.post("/api/skills/marketplace/uninstall",
                    json={"name": "weather", "purge": True},
                    headers={"X-Admin-Token": "t"})
    assert r.status_code == 200, r.text
    assert r.json()["purged"] is True
    assert m.list_skills() == []
