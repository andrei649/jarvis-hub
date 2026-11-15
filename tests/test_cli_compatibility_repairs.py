"""Regression contracts for explicit CLI environment and delegation compatibility."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.cli import import_cmd, skins
from agents.core.tool_profiles import _check_scope_key


@pytest.mark.parametrize("env,home,profile", [
    ({"NERVA_HOME": "/preferred", "NERVA_PROFILE": "preferred"}, "/preferred", "preferred"),
    ({"JARVIS_HOME": "/legacy", "JARVIS_PROFILE": "legacy"}, "/legacy", "legacy"),
    ({"NERVA_HOME": "/preferred", "JARVIS_HOME": "/legacy",
      "NERVA_PROFILE": "preferred", "JARVIS_PROFILE": "legacy"}, "/legacy", "legacy"),
    ({"NERVA_HOME": " ", "JARVIS_HOME": "/legacy",
      "NERVA_PROFILE": " ", "JARVIS_PROFILE": "legacy"}, "/legacy", "legacy"),
])
def test_cli_and_probe_scope_use_shared_alias_resolution(env, home, profile):
    ctx = SimpleNamespace(environ=env)
    assert import_cmd._data_root_for(ctx) == Path(home)
    assert skins._skins_dir_for(ctx) == Path(home) / "skins"
    assert _check_scope_key(env) == f"{home}::{profile}"


def test_skin_help_and_missing_yaml_execution_without_site_packages(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "nerva.py"
    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")
           if name in os.environ}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "HOME": str(home),
                "JARVIS_HOME": str(home), "JARVIS_USER_HOME": str(home)})
    help_result = subprocess.run(
        [sys.executable, "-S", str(script), "skin", "--help"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert all(verb in help_result.stdout for verb in ("list", "use", "set", "show", "render"))
    runtime_result = subprocess.run(
        [sys.executable, "-S", str(script), "skin", "list"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert runtime_result.returncode == 1
    assert runtime_result.stdout == ""
    assert "PyYAML" in runtime_result.stderr and "install" in runtime_result.stderr.lower()
    assert "Traceback" not in runtime_result.stderr
    assert list(home.iterdir()) == []
