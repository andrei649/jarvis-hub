"""Bundle path references use path bounds, without expanding skill-name authority."""
import json

import pytest

from agents.core.skills import bundles
from agents.core.skills import loader as loader_mod
from tests.test_h026_skill_bundles import _admin, _client, _folder
from tests.test_h026_skill_bundles import isolated as isolated  # noqa: F401


def test_long_absolute_installed_member_survives_save_and_resolution(tmp_path, monkeypatch):
    root = tmp_path / ("owner-directory-" * 7) / "skills"
    skill = _folder(root / "notes", "Notes")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root)
    absolute = str(skill.path)
    assert len(absolute) > 128

    saved, _ = bundles.save("Research", [absolute, absolute])
    assert saved.skills == (absolute,)
    loaded = bundles.get("research")
    assert bundles.describe(loaded, [skill])["installed"] == ["Notes"]
    assert bundles.describe(loaded, [skill])["missing"] == []


def test_bundle_api_resolves_a_long_absolute_path_before_storing_the_name(tmp_path, monkeypatch):
    root = tmp_path / ("owner-directory-" * 7)
    client, orch = _client(monkeypatch, root)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root / "skills")
    path = str(root / "skills" / "weather")
    assert len(path) > 128

    response = _admin(client, "POST", "/api/skills/bundles", {"name": "Morning", "skills": [path]})
    assert response.status_code == 200, response.text
    assert response.json()["bundle"]["skills"] == ["Weather Intel"]
    assert response.json()["bundle"]["missing"] == []
    assert orch.skills.skills["Weather Intel"].path == root / "skills" / "weather"


def test_optional_upstream_path_resolves_only_its_exact_imported_folder(tmp_path):
    skill = _folder(tmp_path / "home" / "skills" / "github", "github")
    (skill.path / "manifest.json").write_text(json.dumps({
        "source_repository": "NousResearch/hermes-agent",
        "source_path": "optional-skills/development/github/SKILL.md",
    }))
    assert bundles.find_member([skill], "development/github") == (skill, "")
    assert bundles.find_member([skill], "unrelated/github") == (None, bundles.PATH_NOT_FOUND)


@pytest.mark.parametrize("member", ["x" * 129, "/" + "x" * 4096, "relative/" + "x" * 4096,
                                   "/notes/\x00hidden", "/notes/\nhidden"])
def test_member_path_support_keeps_name_size_path_size_and_control_bounds(member):
    with pytest.raises(bundles.BundleError):
        bundles.clean_members([member])
