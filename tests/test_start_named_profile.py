"""The source checkout and the owner data directory can be chosen independently."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import start_profile


def test_existing_profile_reuses_its_installation_and_only_system_environment(tmp_path, monkeypatch):
    profile = tmp_path / "owner hub-profiles" / "studio"
    profile.mkdir(parents=True)
    monkeypatch.setenv("NERVA_HOST", "ambient.invalid")
    monkeypatch.setenv("NERVA_PROFILE", "unrelated")
    monkeypatch.setenv("JARVIS_HOME", "unrelated")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private")
    monkeypatch.setenv("PYTHONPATH", "ambient-import-path")
    monkeypatch.setenv("TMP", str(tmp_path))
    env = start_profile.profile_environment(profile)
    assert Path(env["JARVIS_HOME"]) == tmp_path / "owner hub"
    assert env["JARVIS_PROFILE"] == "studio"
    assert env["JARVIS_HOST"] == "127.0.0.1"
    assert env["TMP"] == str(tmp_path)
    assert not {"NERVA_HOST", "NERVA_PROFILE", "OPENAI_API_KEY", "PYTHONPATH"} & env.keys()


@pytest.mark.parametrize("parent,name", [("hub", "studio"), ("-profiles", "studio"),
                                        ("hub-profiles", "default"), ("hub-profiles", "two names")])
def test_refuses_an_existing_directory_outside_the_named_profile_layout(tmp_path, parent, name):
    candidate = tmp_path / parent / name
    candidate.mkdir(parents=True)
    with pytest.raises(ValueError):
        start_profile.profile_environment(candidate)


def test_check_prints_selected_paths_without_reading_dotenv_or_starting_the_hub(tmp_path, capsys, monkeypatch):
    profile = tmp_path / "hub-profiles" / "studio"
    with pytest.raises(ValueError):
        start_profile.profile_environment(profile)
    assert not profile.exists()
    profile.mkdir(parents=True)
    dotenv = profile / ".env"
    dotenv.write_text("SYNTHETIC_SECRET=do-not-print-this\n", encoding="utf-8")
    monkeypatch.setattr(start_profile.subprocess, "Popen", lambda *a, **kw: pytest.fail("started hub"))
    assert start_profile.main(["--check", str(profile)]) == 0
    output = capsys.readouterr()
    assert str(profile) in output.out and str(start_profile.ROOT) in output.out
    assert "do-not-print-this" not in output.out + output.err
    assert list(profile.iterdir()) == [dotenv]
    assert not (tmp_path / "hub").exists()


def test_normal_launch_runs_this_checkout_and_forwards_safe_mode(tmp_path, monkeypatch):
    profile = tmp_path / "hub & echo injected-profiles" / "studio"
    profile.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_HOST", "ambient.invalid")
    monkeypatch.setenv("PYTHONPATH", str(profile))
    env = start_profile.profile_environment(profile)
    assert env["JARVIS_HOST"] == "127.0.0.1" and "PYTHONPATH" not in env
    expected = [sys.executable, "-s", str(start_profile.ROOT / "serve.py"), "--safe-mode"]
    with monkeypatch.context() as unsafe:
        unsafe.setattr(sys, "executable", "untrusted-python")
        unsafe.setattr(start_profile.subprocess, "Popen", lambda *a, **kw: pytest.fail("started hub"))
        unsafe.setattr(start_profile.os, "execve", lambda *a: pytest.fail("started hub"))
        with pytest.raises(SystemExit) as refused:
            start_profile.main([str(profile)])
        assert refused.value.code == 2
    if os.name == "nt":
        hub = MagicMock()
        hub.__enter__.return_value = hub
        hub.wait.side_effect = [KeyboardInterrupt(), 23]
        create = MagicMock(return_value=hub)
        monkeypatch.setattr(start_profile.subprocess, "Popen", create)
        assert start_profile.main([str(profile), "--safe-mode"]) == 23
        create.assert_called_once_with(expected, cwd=start_profile.ROOT, env=env, shell=False)
    else:
        monkeypatch.chdir(tmp_path)

        def replace(executable, command, child_env):
            assert Path.cwd() == start_profile.ROOT
            assert executable == sys.executable and command == expected
            assert child_env == env
            raise SystemExit(23)

        monkeypatch.setattr(start_profile.os, "execve", replace)
        with pytest.raises(SystemExit) as replaced:
            start_profile.main([str(profile), "--safe-mode"])
        assert replaced.value.code == 23
