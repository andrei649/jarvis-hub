"""Focused tests for the generated-status changed-file preflight."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "status_preflight", REPO / "scripts" / "status_preflight.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


preflight = _load()


def _status_result(status, **extra):
    return json.dumps({"status": status, **extra}) + "\n"


def test_changed_file_discovery_unions_branch_local_and_untracked_paths():
    outputs = iter(
        [
            (0, "BACKLOG.md\ntests/test_new.py\n"),
            (0, "BACKLOG.md\nSTATUS.md\n"),
            (0, "notes.tmp\n"),
        ]
    )
    commands = []
    files = preflight.discover_changed_files(
        base="origin/main", runner=lambda args: commands.append(args) or next(outputs)
    )
    assert files == ["BACKLOG.md", "STATUS.md", "notes.tmp", "tests/test_new.py"]
    assert all("--diff-filter=ACMRD" in command for command in commands[:2])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_status_sync.py", ["backend"]),
        ("pytest.ini", ["backend"]),
        ("frontend/src/status.test.ts", ["frontend"]),
        ("frontend/vite.config.ts", ["frontend"]),
        ("mobile/__tests__/status.test.ts", ["mobile"]),
        ("tests/_snapshots/route_surface.json", []),
        ("agents/core/router.py", []),
    ],
)
def test_test_count_impact_is_narrow_and_deterministic(path, expected):
    assert preflight.affected_test_counts([path]) == expected


def test_backlog_only_drift_uses_fast_gate_and_returns_exact_diagnostics():
    seen = []
    result = _status_result(
        "out_of_sync",
        changed_keys=["horizons.H35.open", "horizons.H35.total"],
        files=["project-status.json", "README.md"],
        fix_command="python scripts/status_sync.py --reuse-test-counts",
    )
    code, payload = preflight.run_preflight(
        ["BACKLOG.md"], runner=lambda args: seen.append(args) or (1, result)
    )
    assert code == 1
    assert seen[0][-3:] == ["--check", "--reuse-test-counts", "--json"]
    assert payload["changed_keys"] == ["horizons.H35.open", "horizons.H35.total"]
    assert payload["generated_files"] == ["project-status.json", "README.md"]
    assert payload["fix_command"] == "python scripts/status_sync.py --reuse-test-counts"


def test_backlog_only_clean_projection_passes_with_tracked_counts():
    result = _status_result(
        "in_sync", changed_keys=[], files=[], fix_command=None, tests={"backend": 1}
    )
    code, payload = preflight.run_preflight(
        ["BACKLOG.md"], runner=lambda args: (0, result)
    )
    assert code == 0
    assert payload["status"] == "in_sync"
    assert payload["mode"] == "tracked-test-counts"


def test_backend_test_change_requires_deliberate_count_refresh_before_fast_gate():
    result = _status_result("in_sync", changed_keys=[], files=[], fix_command=None)
    code, payload = preflight.run_preflight(
        ["tests/test_new_surface.py"],
        runner=lambda args: (0, result),
    )
    assert code == 0
    assert payload["status"] == "in_sync"
    # The fast gate checks projections; the selected runtime lane proves the
    # live count and catches both added and deleted test nodes.
    assert preflight.affected_test_counts(["tests/deleted_surface.py"]) == ["backend"]


def test_changed_project_status_proves_count_refresh_and_runs_projection_check():
    result = _status_result("in_sync", changed_keys=[], files=[], fix_command=None)
    current = preflight.PROJECT_STATUS.read_text(encoding="utf-8")

    def runner(args):
        if args[:2] == ["git", "show"]:
            return 0, current
        return 0, result

    code, payload = preflight.run_preflight(
        ["tests/test_new_surface.py", "project-status.json"],
        runner=runner,
    )
    assert code == 0
    assert payload["status"] == "in_sync"

    unrelated_base = json.loads(current)
    unrelated_base["tests"]["mobile"] += 1
    code, payload = preflight.run_preflight(
        ["tests/test_new_surface.py", "project-status.json"],
        runner=lambda args: (0, json.dumps(unrelated_base))
        if args[:2] == ["git", "show"]
        else (0, result),
    )
    assert code == 1
    assert payload["status"] == "refresh_required"
    assert payload["changed_keys"] == ["tests.mobile"]


def test_unrelated_change_skips_generated_status_work():
    code, payload = preflight.run_preflight(
        ["agents/core/router.py"],
        runner=lambda args: pytest.fail("status sync is irrelevant for this change"),
    )
    assert code == 0
    assert payload["status"] == "skipped"
    assert payload["fix_command"] is None


def test_human_output_exposes_keys_files_and_fix_command():
    rendered = preflight.render(
        {
            "status": "out_of_sync",
            "mode": "tracked-test-counts",
            "changed_files": ["BACKLOG.md"],
            "status_inputs": ["BACKLOG.md"],
            "changed_keys": ["horizons.H35.total"],
            "generated_files": ["project-status.json"],
            "fix_command": "python scripts/status_sync.py --reuse-test-counts",
        }
    )
    assert "Changed status keys: horizons.H35.total" in rendered
    assert "Generated files: project-status.json" in rendered
    assert "Fix with: python scripts/status_sync.py --reuse-test-counts" in rendered
