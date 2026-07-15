"""Regression proof that pytest never writes to an ambient operator data root."""

import os
import subprocess
import sys
import tempfile
import time
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
    root_report = tmp_path / "child-pytest-root.txt"
    env["JARVIS_TEST_ROOT_REPORT"] = str(root_report)
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
    child_root = Path(root_report.read_text(encoding="utf-8").strip()).resolve()
    assert child_root.parent == Path(tempfile.gettempdir()).resolve()
    assert child_root.name.startswith("jarvis-pytest-")
    deadline = time.monotonic() + 15
    while child_root.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not child_root.exists(), f"child pytest root leaked after process exit: {child_root}"
    assert _metadata_fingerprint(operator_root) == before


def test_cleanup_helper_refuses_nested_target_without_deleting_it(tmp_path):
    unsafe_root = tmp_path / "nested" / "jarvis-pytest-unsafe"
    unsafe_root.mkdir(parents=True)
    marker = unsafe_root / "must-survive.marker"
    marker.write_text("sentinel\n", encoding="utf-8")
    helper = Path(__file__).parent / "support" / "pytest_root_cleanup.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(helper),
            str(unsafe_root),
            "--attempts",
            "1",
            "--delay",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 2
    assert "refusing unsafe pytest root" in completed.stderr.lower()
    assert marker.read_text(encoding="utf-8") == "sentinel\n"
