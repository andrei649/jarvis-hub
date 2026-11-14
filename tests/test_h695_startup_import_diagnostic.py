"""Subprocess coverage for actionable first-party startup import failures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO / "serve.py"


def _injector(tmp_path: Path, target: str, *, emulate_transitive_external: bool = False) -> Path:
    path = tmp_path / "injector"
    path.mkdir()
    find_spec_patch = ""
    if emulate_transitive_external:
        find_spec_patch = """
import importlib.util
from importlib.machinery import ModuleSpec
_real_find_spec = importlib.util.find_spec
def _probe(name, *args, **kwargs):
    if name == 'fastapi':
        return ModuleSpec(name, loader=None)
    return _real_find_spec(name, *args, **kwargs)
importlib.util.find_spec = _probe
"""
    (path / "sitecustomize.py").write_text(
        "import sys\nfrom importlib.abc import MetaPathFinder\n"
        "class _Failure(MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        f"        if fullname == {target!r}:\n"
        "            raise ModuleNotFoundError(f\"No module named '{fullname}'\", name=fullname)\n"
        "sys.meta_path.insert(0, _Failure())\n" + find_spec_patch,
        encoding="utf-8",
    )
    return path


def _run(tmp_path: Path, *, fail_import: str | None = None, extra_env: dict[str, str] | None = None,
         external_failure: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("JARVIS_PROFILE", "NERVA_PROFILE", "JARVIS_SAFE_MODE", "NERVA_SAFE_MODE",
                "NERVA_RESTART_PREDECESSOR", "JARVIS_SELF_RESTART", "NERVA_SELF_RESTART",
                "NOTIFY_SOCKET", "WATCHDOG_USEC"):
        env.pop(key, None)
    env["JARVIS_HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_injector(tmp_path, fail_import or "", emulate_transitive_external=external_failure)), str(REPO)]
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(CANDIDATE)], cwd=REPO, env=env, capture_output=True, text=True, timeout=60,
    )


def test_early_first_party_import_failure_gets_hint_and_original_traceback(tmp_path):
    result = _run(tmp_path, fail_import="agents.core.sd_notify")
    assert result.returncode == 1
    assert "first-party startup import failed: agents.core.sd_notify" in result.stderr
    assert "mismatched or incomplete install, or a code defect" in result.stderr
    assert "ModuleNotFoundError: No module named 'agents.core.sd_notify'" in result.stderr
    assert "Traceback (most recent call last)" in result.stderr


def test_later_first_party_app_import_failure_gets_hint_before_server_start(tmp_path):
    result = _run(tmp_path, fail_import="agents.web")
    assert result.returncode == 1
    assert "first-party startup import failed: agents.web" in result.stderr
    assert "mismatched or incomplete install, or a code defect" in result.stderr
    assert "ModuleNotFoundError: No module named 'agents.web'" in result.stderr
    assert "Nerva starting at http://" not in result.stdout


def test_transitive_external_module_failure_keeps_external_diagnostic(tmp_path):
    result = _run(tmp_path, fail_import="fastapi", external_failure=True)
    assert result.returncode == 1
    assert "first-party startup import failed" not in result.stderr
    assert "No module named 'fastapi'" in result.stderr


def test_profile_configuration_refusal_keeps_its_status_and_message(tmp_path):
    result = _run(tmp_path, extra_env={"JARVIS_PROFILE": "Bad"})
    assert result.returncode == 78
    assert "JARVIS_PROFILE='Bad' is not a profile name" in result.stderr
    assert "first-party startup import failed" not in result.stderr
    assert "Traceback" not in result.stderr
