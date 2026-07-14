"""Regression proof that pytest never writes to an ambient operator data root."""

import os
import subprocess
import sys
from pathlib import Path


def _metadata_fingerprint(root: Path) -> tuple[tuple[str, str, int, int], ...]:
    """Fingerprint names and stat metadata without opening any sentinel file."""
    entries = [root, *sorted(root.rglob("*"))]
    return tuple(
        (
            "." if path == root else path.relative_to(root).as_posix(),
            "dir" if path.is_dir() else "file",
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in entries
    )


def test_child_pytest_overrides_ambient_operator_roots_before_jarvis_import(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    operator_root = tmp_path / "operator-sentinel"
    operator_root.mkdir()
    (operator_root / "operator-owned.marker").write_text("sentinel\n", encoding="utf-8")
    before = _metadata_fingerprint(operator_root)

    env = os.environ.copy()
    env["JARVIS_HOME"] = str(operator_root)
    env["JARVIS_KEY_DIR"] = str(operator_root / "keys")
    env["JARVIS_TEST_OPERATOR_SENTINEL"] = str(operator_root)
    child_basetemp = tmp_path / "child-pytest"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/support/pytest_data_root_probe.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(child_basetemp),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _metadata_fingerprint(operator_root) == before
