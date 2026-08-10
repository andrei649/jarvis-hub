"""Windows server smoke should run only when boot/runtime inputs can change."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.load(
    (REPO / ".github/workflows/smoke.yml").read_text(encoding="utf-8"),
    Loader=yaml.BaseLoader,
)


def test_pull_and_push_use_the_same_runtime_only_paths():
    triggers = WORKFLOW["on"]
    pull_paths = triggers["pull_request"]["paths"]
    push_paths = triggers["push"]["paths"]

    assert pull_paths == push_paths
    assert "agents/**" in pull_paths
    assert "requirements*.lock" in pull_paths
    assert "*.md" not in pull_paths
    assert "BACKLOG.md" not in pull_paths


def test_windows_smoke_is_bounded_and_cancellable():
    assert WORKFLOW["concurrency"]["cancel-in-progress"] == "true"
    job = WORKFLOW["jobs"]["server-boot"]
    assert job["runs-on"] == "windows-latest"
    assert int(job["timeout-minutes"]) <= 10
