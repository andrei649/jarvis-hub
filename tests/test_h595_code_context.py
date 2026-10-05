"""H595 project context and bounded projection contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agents.core.code_context import (
    CHILD_CONTEXT_SOURCE,
    ProjectSnapshotError,
    normalize_mode,
    prepare_project,
    resolve_child_context,
)


def _python(venv: Path) -> Path:
    path = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    path.parent.mkdir(parents=True)
    path.write_text("placeholder", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_modes_cwd_and_backend_local_interpreter(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    project = tmp_path / "project"
    stage.mkdir()
    project.mkdir()
    python = _python(tmp_path / "venv")
    payload = {"mode": "project", "cwd": str(project), "staging_dir": str(stage),
               "env": {"VIRTUAL_ENV": str(python.parent.parent)}}
    assert normalize_mode(None) == "project"
    assert resolve_child_context(payload, probe=lambda candidate: candidate == str(python)) == {
        "mode": "project", "cwd": str(project), "python": str(python),
    }
    assert resolve_child_context({**payload, "mode": "strict"}, probe=lambda _: False) == {
        "mode": "strict", "cwd": str(stage), "python": sys.executable,
    }
    assert resolve_child_context({**payload, "cwd": str(tmp_path / "missing")},
                                 probe=lambda _: True)["cwd"] == str(stage)
    assert resolve_child_context({"staging_dir": str(stage), "env": {}},
                                 probe=lambda _: True)["cwd"] == str(stage)


def test_broken_and_old_venv_falls_through_to_conda_then_default(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    venv = _python(tmp_path / "venv")
    conda = _python(tmp_path / "conda")
    payload = {"mode": "project", "staging_dir": str(stage), "env": {
        "VIRTUAL_ENV": str(venv.parent.parent), "CONDA_PREFIX": str(conda.parent.parent),
    }}
    assert resolve_child_context(payload, probe=lambda candidate: candidate == str(conda))["python"] == str(conda)
    assert resolve_child_context(payload, probe=lambda _: False)["python"] == sys.executable


def test_mode_and_stage_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid_mode"):
        normalize_mode("permissive")
    with pytest.raises(ValueError, match="missing_staging_dir"):
        resolve_child_context({"mode": "strict"})


def test_child_source_works_without_nerva_imports(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    python = _python(tmp_path / "venv")
    namespace: dict[str, object] = {}
    exec(CHILD_CONTEXT_SOURCE, namespace)
    child = namespace["resolve_child_context"]
    assert child({"mode": "strict", "staging_dir": str(stage), "env": {}}) == {
        "mode": "strict", "cwd": str(stage), "python": sys.executable,
    }
    assert child({"mode": "project", "staging_dir": str(stage),
                  "env": {"VIRTUAL_ENV": str(python.parent.parent)}},
                 probe=lambda _: True)["python"] == str(python)


def test_project_projection_imports_data_and_excludes_sensitive_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("from .thing import VALUE\n", encoding="utf-8")
    (root / "pkg" / "thing.py").write_text("VALUE = 7\n", encoding="utf-8")
    (root / "data.bin").write_bytes(b"\x00\xff\x10")
    (root / ".env").write_text("PRIVATE=example", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("private", encoding="utf-8")
    (root / ".config" / "gcloud").mkdir(parents=True)
    (root / ".config" / "gcloud" / "application_default_credentials.json").write_text(
        "private", encoding="utf-8",
    )
    (root / "api_token.txt").write_text("private", encoding="utf-8")
    (root / "redacted.txt").write_text("replace-me", encoding="utf-8")
    (root / "safe.txt").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)
    (root / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    destination = tmp_path / "snapshot"
    result = prepare_project(root, destination, redact=lambda text: text.replace("replace-me", "[redacted]"))
    assert result["files"] == 4
    assert (destination / "pkg" / "thing.py").read_text(encoding="utf-8") == "VALUE = 7\n"
    assert (destination / "data.bin").read_bytes() == b"\x00\xff\x10"
    imported = subprocess.run(
        [sys.executable, "-c", "import pkg; print(pkg.VALUE)"], cwd=destination,
        capture_output=True, text=True, check=True,
    )
    assert imported.stdout.strip() == "7"
    for name in (".env", ".git", ".config/gcloud", "api_token.txt", "redacted.txt",
                 "escape.txt", "linkdir"):
        assert not (destination / name).exists()


def test_projection_rejects_bounds_without_partial_tree(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("aaaa", encoding="utf-8")
    (root / "b.txt").write_text("bbbb", encoding="utf-8")
    with pytest.raises(ProjectSnapshotError, match="file_limit"):
        prepare_project(root, tmp_path / "files", max_files=1)
    assert not (tmp_path / "files").exists()
    with pytest.raises(ProjectSnapshotError, match="byte_limit"):
        prepare_project(root, tmp_path / "bytes", max_bytes=7)
    assert not (tmp_path / "bytes").exists()


def test_destination_inside_root_is_not_recursively_copied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.py").write_text("A = 1\n", encoding="utf-8")
    dest = root / "mirror"
    assert prepare_project(root, dest)["files"] == 1
    assert (dest / "a.py").exists()
    assert not (dest / "mirror").exists()


def test_source_swapped_to_symlink_during_projection_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "ordinary.txt"
    source.write_text("ordinary", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    def swap(text: str) -> str:
        source.unlink()
        source.symlink_to(outside)
        return text

    destination = tmp_path / "snapshot"
    with pytest.raises(ProjectSnapshotError, match="source_changed"):
        prepare_project(root, destination, redact=swap)
    assert not destination.exists()
