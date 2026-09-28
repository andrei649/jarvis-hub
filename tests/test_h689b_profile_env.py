"""H689b — a profile's credentials come from its own root, and only from there.

H689 gave ``JARVIS_PROFILE=<name>`` its own data root (settings, memory, the secret
store, the install id and lock), but every profile still loaded the repo ``.env`` and the
data-home ``.env``, which hold the provider keys, the channel bot tokens, the admin token
and the token keys. A profile's hub now reads one file, ``<profile root>/.env``; the shared
ones are not read. The process environment still wins, as it does for any hub. The
doctor's prediction, ``hub_value`` (the read that never loads) and the files the load
reports follow the same rule, and a refused profile name stops the load rather than fall
back to the shared files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agents.core import env_provenance as ep
from agents.core import paths

KEYS = ("H689B_KEY", "H689B_REPO_ONLY", "H689B_HOME_ONLY", "H689B_PROFILE_ONLY")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    repo_env = tmp_path / "repo.env"
    repo_env.write_text("H689B_KEY=repo\nH689B_REPO_ONLY=r\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("H689B_KEY=home\nH689B_HOME_ONLY=h\n", encoding="utf-8")
    base = tmp_path / "data"
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.setenv("JARVIS_HOME", str(base))
    monkeypatch.setenv("JARVIS_USER_HOME", str(home))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    for key in KEYS:
        monkeypatch.setenv(key, "")               # so the teardown unsets what a load set
        monkeypatch.delenv(key)
    profile_root = tmp_path / "data-profiles" / "work"
    return repo_env, home, profile_root


def _profile(monkeypatch, root: Path, text: str | None = "H689B_KEY=profile\nH689B_PROFILE_ONLY=p\n"):
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    if text is not None:
        root.mkdir(parents=True, exist_ok=True)
        (root / ".env").write_text(text, encoding="utf-8")


def test_a_profile_reads_only_its_own_env(roots, monkeypatch):
    _repo, _home, root = roots
    _profile(monkeypatch, root)
    assert paths.data_root() == root
    table = ep.load_hub_env()
    assert os.environ["H689B_KEY"] == "profile"
    assert os.environ["H689B_PROFILE_ONLY"] == "p"
    assert "H689B_REPO_ONLY" not in os.environ and "H689B_HOME_ONLY" not in os.environ
    assert table["H689B_KEY"] == {"layer": ep.USER_ENV, "shadowed": []}      # nothing shared behind it


def test_without_a_profile_the_shared_files_load_as_before(roots):
    ep.load_hub_env()
    assert os.environ["H689B_KEY"] == "repo"                                  # the repo's value wins
    assert os.environ["H689B_HOME_ONLY"] == "h" and os.environ["H689B_REPO_ONLY"] == "r"


def test_the_default_profile_name_is_the_default_hub(roots, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "default")
    ep.load_hub_env()
    assert os.environ["H689B_KEY"] == "repo"


def test_the_process_still_wins_for_a_profile(roots, monkeypatch):
    _repo, _home, root = roots
    _profile(monkeypatch, root)
    monkeypatch.setenv("H689B_KEY", "process")
    ep.load_hub_env()
    assert os.environ["H689B_KEY"] == "process"


def test_a_profile_without_a_file_gets_nothing_from_the_shared_ones(roots, monkeypatch):
    _repo, _home, root = roots
    _profile(monkeypatch, root, text=None)
    ep.load_hub_env()
    assert not any(key in os.environ for key in KEYS)
    assert ep.files()[ep.USER_ENV]["path"] == str(root / ".env")
    assert ep.files()[ep.USER_ENV]["present"] is False


def test_the_load_says_which_files_a_profile_did_not_read(roots, monkeypatch):
    repo, home, root = roots
    _profile(monkeypatch, root)
    ep.load_hub_env()
    files = ep.files()
    assert files[ep.USER_ENV]["path"] == str(root / ".env") and files[ep.USER_ENV]["read"] is True
    assert files[ep.REPO_ENV]["read"] is False and files[ep.REPO_ENV]["path"] is None
    assert "profile" in files[ep.REPO_ENV]["kind"]
    assert not (home / ".env").read_text().startswith("H689B_KEY=profile")     # the data home is untouched


def test_a_refused_profile_name_stops_the_load(roots, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "Not A Name")
    with pytest.raises(RuntimeError, match="JARVIS_PROFILE"):
        ep.load_hub_env()
    assert "H689B_KEY" not in os.environ                                     # never the shared files instead


def test_hub_value_follows_the_profile(roots, monkeypatch):
    _repo, _home, root = roots
    assert ep.hub_value("H689B_KEY") == "repo"
    _profile(monkeypatch, root)
    assert ep.hub_value("H689B_KEY") == "profile"
    assert ep.hub_value("H689B_REPO_ONLY") is None and ep.hub_value("H689B_HOME_ONLY") is None
    assert "H689B_KEY" not in os.environ                                     # it never loads
    monkeypatch.setenv("JARVIS_PROFILE", "Not A Name")
    assert ep.hub_value("H689B_KEY") is None


def test_the_profile_file_is_found_for_a_given_environment(roots, monkeypatch, tmp_path):
    _repo, _home, root = roots
    env = dict(os.environ, JARVIS_PROFILE="work")
    assert ep.profile_env_file(env) == root / ".env"
    assert ep.profile_env_file(dict(env, JARVIS_PROFILE="default")) is None
    assert ep.profile_env_file(dict(env, JARVIS_PROFILE="")) is None
    other = dict(env, JARVIS_HOME=str(tmp_path / "elsewhere"))
    assert ep.profile_env_file(other) == tmp_path / "elsewhere-profiles" / "work" / ".env"
    with pytest.raises(RuntimeError):
        ep.profile_env_file(dict(env, JARVIS_PROFILE="../x"))
    assert paths.data_root(env) == root and paths.data_root(dict(env, JARVIS_PROFILE="")) == tmp_path / "data"


def test_the_doctor_predicts_the_profile_table(roots, monkeypatch):
    from scripts import doctor

    repo, _home, root = roots
    _profile(monkeypatch, root)
    check = doctor.check_config_sources(repo.parent, dict(os.environ))
    text = str(check)
    assert "H689B_KEY" in text or "profile" in text
    table = ep.derive(None, ep.profile_env_file(dict(os.environ)), dict(os.environ))
    assert table["H689B_KEY"]["layer"] == ep.USER_ENV
    assert "H689B_REPO_ONLY" not in table and "H689B_HOME_ONLY" not in table
    assert "profile" in doctor._config_sources(repo.parent, dict(os.environ), None, None).detail


def test_hub_value_keeps_the_loads_own_rules_for_a_profile(roots, monkeypatch):
    _repo, _home, root = roots
    _profile(monkeypatch, root, text="H689B_KEY=profile\nJARVIS_MEMORY_DIR=/elsewhere\n")
    assert ep.hub_value("H689B_KEY") == "profile"
    assert ep.hub_value("JARVIS_MEMORY_DIR") is None                           # never from a file
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")                          # python-dotenv's own switch
    assert ep.hub_value("H689B_KEY") is None


def test_a_profile_root_follows_the_given_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.setenv("JARVIS_USER_HOME", str(tmp_path / "mine"))
    env = {"JARVIS_USER_HOME": str(tmp_path / "theirs"), "JARVIS_PROFILE": "work"}
    assert paths.data_root(env) == tmp_path / "theirs" / "memory-profiles" / "work"
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    with pytest.raises(RuntimeError):
        paths.data_root({"JARVIS_USER_HOME": str(tmp_path / "theirs"), "JARVIS_PROFILE": "Not A Name"})


def test_the_doctor_lists_no_shared_key_for_a_profile(roots, monkeypatch):
    from scripts import doctor

    repo, _home, root = roots
    (repo.parent / ".env").write_text("JARVIS_H689B_REPO=r\n", encoding="utf-8")         # the checkout's own
    monkeypatch.setenv("JARVIS_H689B_REPO", "")
    monkeypatch.delenv("JARVIS_H689B_REPO")
    _profile(monkeypatch, root)
    check = doctor._config_sources(repo.parent, dict(os.environ), None, None)
    keys = {row["key"] for row in check.data["sources"]}
    assert "H689B_PROFILE_ONLY" in keys and "H689B_HOME_ONLY" not in keys
    assert "JARVIS_H689B_REPO" not in keys                                    # a Nerva name would be listed
    assert all(row["layer"] != ep.REPO_ENV for row in check.data["sources"])
