"""Fail-closed policy tests for the hourly pull-request conductor."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO / ".github" / "workflows" / "pr-auto-merge.yml"

NERVA_PREFIX = "nerva2/"
START_MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
END_MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
OID_A = "a" * 40
OID_B = "b" * 40
PR_FIELDS = "number,isDraft,mergeStateStatus,headRefOid,headRefName,body"
PREDICATE_FILTER = (
    "(.headRefName | startswith($prefix)) or (.body | contains($marker))"
)

def _select_bash() -> str | None:
    """Prefer Git Bash on Windows; fall back to the ambient Bash."""

    if os.name == "nt":
        git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    return shutil.which("bash")


BASH = _select_bash()


def _command_in_bash(command: str) -> str | None:
    """Resolve a command where the selected Bash will actually execute it."""

    if BASH is None:
        return None
    result = subprocess.run(
        [BASH, "-lc", f"command -v {command}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    return resolved or None


def _path_for_bash(path: Path) -> str:
    """Translate a host path for Git Bash or WSL when needed."""

    resolved = str(path.resolve())
    if os.name != "nt" or BASH is None:
        return resolved
    drive, tail = os.path.splitdrive(resolved)
    if not drive:
        return path.as_posix()
    platform = subprocess.run(
        [BASH, "-lc", "uname -s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    ).stdout.strip()
    root = f"/mnt/{drive[0].lower()}" if platform == "Linux" else f"/{drive[0].lower()}"
    return root + tail.replace("\\", "/")


JQ_IN_BASH = _command_in_bash("jq")
_RUNTIME_MISSING = [
    name for name, executable in (("bash", BASH), ("jq", JQ_IN_BASH)) if executable is None
]
requires_policy_runtime = pytest.mark.skipif(
    bool(_RUNTIME_MISSING),
    reason="executable policy harness requires " + ", ".join(_RUNTIME_MISSING),
)


@dataclass(frozen=True)
class GhResponse:
    """Configured stdout and exit status for one fake GitHub CLI call."""

    stdout: str
    exit_code: int = 0


_FAKE_GH = r"""import json
import os
from pathlib import Path
import re
import sys


def emit(path_name):
    sys.stdout.write(Path(os.environ[path_name]).read_text(encoding="utf-8"))


args = sys.argv[1:]
with Path(os.environ["TRACE_PATH"]).open("a", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(args, ensure_ascii=True, separators=(",", ":")) + "\n")

repo = os.environ["REPO"]
fields = os.environ["PR_FIELDS"]
expected_list = [
    "pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", fields
]

if args == expected_list:
    emit("LIST_PAYLOAD_PATH")
    raise SystemExit(int(os.environ.get("LIST_EXIT", "0")))

if (
    len(args) == 7
    and args[:2] == ["pr", "view"]
    and args[2].isdigit()
    and args[3:] == ["--repo", repo, "--json", fields]
):
    fixtures = json.loads(Path(os.environ["RECHECKS_PATH"]).read_text(encoding="utf-8"))
    fixture = fixtures.get(args[2])
    if not isinstance(fixture, dict):
        raise SystemExit(92)
    sys.stdout.write(fixture["stdout"])
    raise SystemExit(int(fixture["exit_code"]))

if (
    len(args) == 8
    and args[:2] == ["pr", "merge"]
    and args[2].isdigit()
    and args[3:7] == ["--repo", repo, "--squash", "--match-head-commit"]
    and re.fullmatch(r"[0-9a-f]{40}", args[7])
):
    raise SystemExit(int(os.environ.get("MERGE_EXIT", "0")))

raise SystemExit(97)
"""

_FAKE_GH_WRAPPER = r"""#!/usr/bin/env bash
exec "$POLICY_TEST_PYTHON" "$POLICY_TEST_FAKE_GH" "$@"
"""

_FAKE_JQ = r"""#!/usr/bin/env bash
set -u

if [ "$#" -eq 8 ] \
  && [ "$1" = "-e" ] \
  && [ "$2" = "--arg" ] \
  && [ "$3" = "prefix" ] \
  && [ "$4" = "nerva2/" ] \
  && [ "$5" = "--arg" ] \
  && [ "$6" = "marker" ] \
  && [ "$7" = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->" ] \
  && [ "${8}" = '(.headRefName | startswith($prefix)) or (.body | contains($marker))' ]; then
  count=0
  if [ -f "$PREDICATE_COUNT_PATH" ]; then
    count="$(cat "$PREDICATE_COUNT_PATH")"
  fi
  count=$((count + 1))
  printf '%s' "$count" >"$PREDICATE_COUNT_PATH"
  if [ -n "${FORCE_PREDICATE_ERROR_AT:-}" ] \
    && [ "$count" -eq "$FORCE_PREDICATE_ERROR_AT" ]; then
    exit 3
  fi
fi

exec "$REAL_JQ" "$@"
"""


def _workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _workflow_script() -> str:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    auto_merge = jobs["auto-merge"]
    assert isinstance(auto_merge, dict)
    steps = auto_merge["steps"]
    assert isinstance(steps, list)
    first_step = steps[0]
    assert isinstance(first_step, dict)
    script = first_step["run"]
    assert isinstance(script, str)
    return script


def _record(
    number: object = 123,
    *,
    is_draft: object = False,
    state: object = "CLEAN",
    oid: object = OID_A,
    branch: object = "feature/ordinary",
    body: object = "",
) -> dict[str, object]:
    return {
        "number": number,
        "isDraft": is_draft,
        "mergeStateStatus": state,
        "headRefOid": oid,
        "headRefName": branch,
        "body": body,
    }


def _stdout(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _fixture(value: object) -> dict[str, object]:
    if isinstance(value, GhResponse):
        return {"stdout": value.stdout, "exit_code": value.exit_code}
    return {"stdout": _stdout(value), "exit_code": 0}


def _run_policy(
    tmp_path: Path,
    list_payload: object,
    rechecks: dict[int, object] | None = None,
    *,
    list_exit: int = 0,
    merge_exit: int = 0,
    predicate_error_at: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the real workflow shell with a hermetic GitHub CLI fake."""

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(_FAKE_GH_WRAPPER, encoding="utf-8", newline="\n")
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    fake_gh_impl = tmp_path / "fake_gh.py"
    fake_gh_impl.write_text(_FAKE_GH, encoding="utf-8", newline="\n")
    fake_jq = fake_bin / "jq"
    fake_jq.write_text(_FAKE_JQ, encoding="utf-8", newline="\n")
    fake_jq.chmod(fake_jq.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    list_payload_path = tmp_path / "list-payload.txt"
    list_payload_path.write_text(_stdout(list_payload), encoding="utf-8", newline="")
    rechecks_path = tmp_path / "rechecks.json"
    rechecks_path.write_text(
        json.dumps(
            {str(number): _fixture(value) for number, value in (rechecks or {}).items()},
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
        newline="\n",
    )
    trace_path = tmp_path / "trace.jsonl"
    predicate_count_path = tmp_path / "predicate-count.txt"

    env = os.environ.copy()
    env.update(
        {
            "GH_TOKEN": "test-token",
            "REPO": "andrei649/jarvis-hub",
            "LIST_PAYLOAD_PATH": str(list_payload_path),
            "RECHECKS_PATH": str(rechecks_path),
            "TRACE_PATH": str(trace_path),
            "LIST_EXIT": str(list_exit),
            "MERGE_EXIT": str(merge_exit),
            "PR_FIELDS": PR_FIELDS,
            "POLICY_TEST_PYTHON": _path_for_bash(Path(sys.executable)),
            "POLICY_TEST_FAKE_GH": str(fake_gh_impl),
            "POLICY_FAKE_BIN": _path_for_bash(fake_bin),
            "REAL_JQ": JQ_IN_BASH or "jq",
            "PREDICATE_COUNT_PATH": _path_for_bash(predicate_count_path),
            "FORCE_PREDICATE_ERROR_AT": (
                "" if predicate_error_at is None else str(predicate_error_at)
            ),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return subprocess.run(
        [BASH, "-c", 'export PATH="$POLICY_FAKE_BIN:$PATH"\n' + _workflow_script()],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def _trace(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _calls(tmp_path: Path, operation: str) -> list[list[str]]:
    return [args for args in _trace(tmp_path) if args[:2] == ["pr", operation]]


def _expected_list_call() -> list[str]:
    return [
        "pr",
        "list",
        "--repo",
        "andrei649/jarvis-hub",
        "--state",
        "open",
        "--limit",
        "100",
        "--json",
        PR_FIELDS,
    ]


def _expected_view_call(number: int) -> list[str]:
    return [
        "pr",
        "view",
        str(number),
        "--repo",
        "andrei649/jarvis-hub",
        "--json",
        PR_FIELDS,
    ]


def _assert_no_view_or_merge(tmp_path: Path) -> None:
    assert _calls(tmp_path, "view") == []
    assert _calls(tmp_path, "merge") == []


@pytest.mark.skipif(BASH is None, reason="path bridge check requires Bash")
def test_selected_bash_path_bridge_preserves_file_and_directory(
    tmp_path: Path,
) -> None:
    targets = [(Path(sys.executable), "-f"), (tmp_path, "-d")]
    for target, predicate in targets:
        translated = _path_for_bash(target)
        result = subprocess.run(
            [BASH, "-lc", f"test {predicate} {shlex.quote(translated)}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, (translated, result.stderr)


def test_workflow_preserves_triggers_permissions_and_concurrency() -> None:
    workflow = _workflow()

    assert workflow["on"] == {
        "workflow_dispatch": {},
        "schedule": [{"cron": "13 * * * *"}],
    }
    assert workflow["concurrency"] == {
        "group": "pr-auto-merge",
        "cancel-in-progress": "false",
    }
    assert workflow["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }
    assert "defaults" not in workflow

    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"auto-merge"}
    job = jobs["auto-merge"]
    assert isinstance(job, dict)
    assert job["runs-on"] == "ubuntu-latest"
    assert "permissions" not in job
    assert "defaults" not in job
    assert "continue-on-error" not in job
    steps = job["steps"]
    assert isinstance(steps, list)
    assert len(steps) == 1
    step = steps[0]
    assert step["name"] == "Merge PRs that are fully green"
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
    }
    assert step.get("shell") in (None, "bash")
    assert "continue-on-error" not in step


def test_workflow_pins_exact_nerva_contract_bytes() -> None:
    script = _workflow_script()

    assert f'readonly NERVA_BRANCH_PREFIX="{NERVA_PREFIX}"' in script
    assert f'readonly NERVA_START_MARKER="{START_MARKER}"' in script
    assert END_MARKER not in script


def test_workflow_requests_only_complete_trusted_records_twice() -> None:
    script = _workflow_script()

    assert script.count(PR_FIELDS) == 2
    assert "title" not in script


def test_workflow_has_two_explicit_fail_closed_predicate_calls() -> None:
    script = _workflow_script()

    assert script.count("manual_status=0") == 2
    assert script.count('|| manual_status=$?') == 2
    assert script.count("jq -s") >= 2
    assert script.count(PREDICATE_FILTER) == 1
    assert script.count('case "$manual_status" in') == 2
    assert script.count("Fatal Nerva policy evaluation error") == 2


def test_workflow_preserves_bounded_squash_merge() -> None:
    script = _workflow_script()

    assert "--squash" in script
    assert "--match-head-commit" in script
    assert "--auto" not in script
    assert "--admin" not in script
    assert "--delete-branch" not in script


@requires_policy_runtime
@pytest.mark.parametrize(
    ("branch", "body"),
    [
        ("nerva2/b2-live-issue-ledger-enforcement", ""),
        ("feature/ordinary", f"prefix\n{START_MARKER}\nsuffix"),
    ],
)
def test_list_stage_skips_exact_nerva_branch_or_marker(
    tmp_path: Path, branch: str, body: str
) -> None:
    record = _record(branch=branch, body=body)

    result = _run_policy(tmp_path, [record], {123: record})

    assert result.returncode == 0, result.stderr
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
@pytest.mark.parametrize(
    ("branch", "body"),
    [
        ("nerva2x/topic", ""),
        ("NERVA2/topic", ""),
        ("feature/nerva2/topic", ""),
        (" nerva2/topic", ""),
        ("\tnerva2/topic", ""),
        ("feature/ordinary", END_MARKER),
        ("feature/ordinary", "<!-- NERVA2:MOVEMENT-ATTESTATION:STAR -->"),
        ("feature/ordinary", "<!-- nerva2:MOVEMENT-ATTESTATION:START -->"),
        ("feature/ordinary", "<!-- NERVA2:movement-attestation:start -->"),
    ],
)
def test_prefix_and_marker_lookalikes_remain_non_nerva(
    tmp_path: Path, branch: str, body: str
) -> None:
    record = _record(branch=branch, body=body)

    result = _run_policy(tmp_path, [record], {123: record})

    assert result.returncode == 0, result.stderr
    assert len(_calls(tmp_path, "view")) == 1
    assert len(_calls(tmp_path, "merge")) == 1


@requires_policy_runtime
def test_manual_status_does_not_leak_between_list_records(tmp_path: Path) -> None:
    ordinary = _record(number=123)
    nerva = _record(number=124, branch="nerva2/second")

    result = _run_policy(tmp_path, [ordinary, nerva], {123: ordinary})

    assert result.returncode == 0, result.stderr
    assert [call[2] for call in _calls(tmp_path, "view")] == ["123"]
    assert [call[2] for call in _calls(tmp_path, "merge")] == ["123"]


@requires_policy_runtime
def test_empty_list_is_a_clean_noop(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [])

    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path, "list") == [_expected_list_call()]
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
def test_candidates_are_processed_in_pr_number_order(tmp_path: Path) -> None:
    later = _record(number=124, oid=OID_B)
    earlier = _record(number=123, oid=OID_A)

    result = _run_policy(
        tmp_path,
        [later, earlier],
        {123: earlier, 124: later},
    )

    assert result.returncode == 0, result.stderr
    assert [call[2] for call in _calls(tmp_path, "view")] == ["123", "124"]
    assert [call[2] for call in _calls(tmp_path, "merge")] == ["123", "124"]


@requires_policy_runtime
@pytest.mark.parametrize(
    ("is_draft", "state"),
    [(True, "CLEAN"), (False, "BLOCKED")],
)
def test_list_stage_preserves_ordinary_readiness_skips(
    tmp_path: Path, is_draft: bool, state: str
) -> None:
    record = _record(is_draft=is_draft, state=state)

    result = _run_policy(tmp_path, [record])

    assert result.returncode == 0, result.stderr
    _assert_no_view_or_merge(tmp_path)


def _recheck_drift(kind: str) -> dict[str, object]:
    if kind == "nerva-branch":
        return _record(branch="nerva2/recheck")
    if kind == "marker":
        return _record(body=START_MARKER)
    if kind == "draft":
        return _record(is_draft=True)
    if kind == "blocked":
        return _record(state="BLOCKED")
    if kind == "head":
        return _record(oid=OID_B)
    raise AssertionError(f"unknown drift kind: {kind}")


@requires_policy_runtime
@pytest.mark.parametrize("kind", ["nerva-branch", "marker", "draft", "blocked", "head"])
def test_recheck_stage_skips_nerva_or_readiness_drift(tmp_path: Path, kind: str) -> None:
    listed = _record()

    result = _run_policy(tmp_path, [listed], {123: _recheck_drift(kind)})

    assert result.returncode == 0, result.stderr
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
def test_list_predicate_evaluation_error_is_fatal(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_record()], predicate_error_at=1)

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
def test_recheck_predicate_evaluation_error_is_fatal(tmp_path: Path) -> None:
    record = _record()

    result = _run_policy(
        tmp_path,
        [record],
        {123: record},
        predicate_error_at=2,
    )

    assert result.returncode != 0
    assert _calls(tmp_path, "view") == [_expected_view_call(123)]
    assert _calls(tmp_path, "merge") == []


_MALFORMED_LIST_DOCUMENTS = [
    pytest.param("", id="zero-documents"),
    pytest.param(" \n\t", id="whitespace-only"),
    pytest.param("not-json", id="invalid-json"),
    pytest.param("[]\n[]", id="two-documents"),
    pytest.param(_stdout([_record()]) + "\nnull", id="trailing-json"),
    pytest.param(_record(), id="non-array"),
    pytest.param([42], id="non-object-record"),
]


@requires_policy_runtime
@pytest.mark.parametrize("payload", _MALFORMED_LIST_DOCUMENTS)
def test_malformed_list_document_fails_before_effects(tmp_path: Path, payload: object) -> None:
    result = _run_policy(tmp_path, payload)

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


_REQUIRED_FIELDS = [
    "number",
    "isDraft",
    "mergeStateStatus",
    "headRefOid",
    "headRefName",
    "body",
]


@requires_policy_runtime
@pytest.mark.parametrize("field", _REQUIRED_FIELDS)
def test_list_record_missing_any_required_field_fails_before_effects(
    tmp_path: Path, field: str
) -> None:
    malformed = _record()
    malformed.pop(field)

    result = _run_policy(tmp_path, [malformed])

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


_JSON_TYPE_SAMPLES = {
    "null": None,
    "boolean": True,
    "number": 7,
    "string": "wrong-type",
    "array": [],
    "object": {},
}
_EXPECTED_FIELD_TYPES = {
    "number": "number",
    "isDraft": "boolean",
    "mergeStateStatus": "string",
    "headRefOid": "string",
    "headRefName": "string",
    "body": "string",
}
_WRONG_FIELD_TYPES = [
    pytest.param(field, value, id=f"{field}-{type_name}")
    for field, expected_type in _EXPECTED_FIELD_TYPES.items()
    for type_name, value in _JSON_TYPE_SAMPLES.items()
    if type_name != expected_type
]


@requires_policy_runtime
@pytest.mark.parametrize(("field", "value"), _WRONG_FIELD_TYPES)
def test_list_record_wrong_field_type_fails_before_effects(
    tmp_path: Path, field: str, value: object
) -> None:
    malformed = _record()
    malformed[field] = value

    result = _run_policy(tmp_path, [malformed])

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


_INVALID_FIELD_VALUES = [
    pytest.param("number", 0, id="number-zero"),
    pytest.param("number", -1, id="number-negative"),
    pytest.param("number", 1.5, id="number-fractional"),
    pytest.param("headRefName", "", id="branch-empty"),
    pytest.param("headRefOid", "a" * 39, id="oid-short"),
    pytest.param("headRefOid", "A" * 40, id="oid-uppercase"),
    pytest.param("headRefOid", "z" * 40, id="oid-non-hex"),
]


@requires_policy_runtime
@pytest.mark.parametrize(("field", "value"), _INVALID_FIELD_VALUES)
def test_list_record_invalid_value_fails_before_effects(
    tmp_path: Path, field: str, value: object
) -> None:
    malformed = _record()
    malformed[field] = value

    result = _run_policy(tmp_path, [malformed])

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
def test_duplicate_list_numbers_fail_before_effects(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_record(), _record(branch="feature/second")])

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
def test_malformed_late_list_record_blocks_earlier_valid_record(tmp_path: Path) -> None:
    malformed = _record(number=124)
    malformed.pop("body")

    result = _run_policy(tmp_path, [_record(number=123), malformed], {123: _record()})

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


@requires_policy_runtime
def test_failing_list_call_discards_partial_valid_stdout(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_record()], list_exit=41)

    assert result.returncode != 0
    _assert_no_view_or_merge(tmp_path)


_MALFORMED_RECHECK_DOCUMENTS = [
    pytest.param("", id="zero-documents"),
    pytest.param(" \n\t", id="whitespace-only"),
    pytest.param("not-json", id="invalid-json"),
    pytest.param(_stdout(_record()) + "\n{}", id="two-documents"),
    pytest.param(_stdout(_record()) + "\nnull", id="trailing-json"),
    pytest.param([_record()], id="non-object"),
]


@requires_policy_runtime
@pytest.mark.parametrize("payload", _MALFORMED_RECHECK_DOCUMENTS)
def test_malformed_recheck_document_fails_without_merge(
    tmp_path: Path, payload: object
) -> None:
    result = _run_policy(tmp_path, [_record()], {123: payload})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
@pytest.mark.parametrize("field", _REQUIRED_FIELDS)
def test_recheck_missing_any_required_field_fails_without_merge(
    tmp_path: Path, field: str
) -> None:
    malformed = _record()
    malformed.pop(field)

    result = _run_policy(tmp_path, [_record()], {123: malformed})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
@pytest.mark.parametrize(("field", "value"), _WRONG_FIELD_TYPES)
def test_recheck_wrong_field_type_fails_without_merge(
    tmp_path: Path, field: str, value: object
) -> None:
    malformed = _record()
    malformed[field] = value

    result = _run_policy(tmp_path, [_record()], {123: malformed})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
@pytest.mark.parametrize(("field", "value"), _INVALID_FIELD_VALUES)
def test_recheck_invalid_value_fails_without_merge(
    tmp_path: Path, field: str, value: object
) -> None:
    malformed = _record()
    malformed[field] = value

    result = _run_policy(tmp_path, [_record()], {123: malformed})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
def test_recheck_number_mismatch_fails_without_merge(tmp_path: Path) -> None:
    result = _run_policy(tmp_path, [_record()], {123: _record(number=124)})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
def test_failing_view_call_discards_partial_valid_stdout(tmp_path: Path) -> None:
    response = GhResponse(_stdout(_record()), exit_code=42)

    result = _run_policy(tmp_path, [_record()], {123: response})

    assert result.returncode != 0
    assert len(_calls(tmp_path, "view")) == 1
    assert _calls(tmp_path, "merge") == []


@requires_policy_runtime
@pytest.mark.parametrize("kind", ["nerva-branch", "nerva-marker", "state-skip"])
def test_skip_paths_never_log_untrusted_record_bytes(tmp_path: Path, kind: str) -> None:
    token = f"UNTRUSTED-{kind.upper()}-TOKEN"
    hostile_bytes = f"{token}\n::stop-commands::hostile\n\x1b[31m$(false)\x1b[0m"
    if kind == "nerva-branch":
        record = _record(branch=f"nerva2/{hostile_bytes}")
    elif kind == "nerva-marker":
        record = _record(body=f"{START_MARKER}\n{hostile_bytes}")
    else:
        record = _record(state=hostile_bytes)

    result = _run_policy(tmp_path, [record])

    assert result.returncode == 0, result.stderr
    _assert_no_view_or_merge(tmp_path)
    combined_log = result.stdout + result.stderr
    assert token not in combined_log
    assert "::stop-commands::" not in combined_log
    assert "\x1b" not in combined_log


@requires_policy_runtime
@pytest.mark.parametrize("kind", ["nerva-branch", "nerva-marker", "state-skip"])
def test_recheck_skip_paths_never_log_untrusted_record_bytes(
    tmp_path: Path, kind: str
) -> None:
    token = f"UNTRUSTED-RECHECK-{kind.upper()}-TOKEN"
    hostile_bytes = f"{token}\n::stop-commands::hostile\n\x1b[31m$(false)\x1b[0m"
    if kind == "nerva-branch":
        fresh = _record(branch=f"nerva2/{hostile_bytes}")
    elif kind == "nerva-marker":
        fresh = _record(body=f"{START_MARKER}\n{hostile_bytes}")
    else:
        fresh = _record(state=hostile_bytes)

    result = _run_policy(tmp_path, [_record()], {123: fresh})

    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path, "view") == [_expected_view_call(123)]
    assert _calls(tmp_path, "merge") == []
    combined_log = result.stdout + result.stderr
    assert token not in combined_log
    assert "::stop-commands::" not in combined_log
    assert "\x1b" not in combined_log


@requires_policy_runtime
def test_untrusted_branch_and_body_bytes_are_inert_and_not_logged(tmp_path: Path) -> None:
    sentinel = tmp_path / "shell-injection-must-not-exist"
    sentinel_arg = shlex.quote(_path_for_bash(sentinel))
    branch_token = "UNTRUSTED-BRANCH-TOKEN"
    body_token = "UNTRUSTED-BODY-TOKEN"
    hostile = _record(
        branch=f"feature/{branch_token}-$(touch {sentinel_arg})",
        body=(
            f"{body_token}\n::stop-commands::hostile\n"
            f"\x1b[31m$(touch {sentinel_arg})\x1b[0m"
        ),
    )

    result = _run_policy(tmp_path, [hostile], {123: hostile})

    assert result.returncode == 0, result.stderr
    assert len(_calls(tmp_path, "merge")) == 1
    assert not sentinel.exists()
    combined_log = result.stdout + result.stderr
    assert branch_token not in combined_log
    assert body_token not in combined_log
    assert "::stop-commands::" not in combined_log
    assert "\x1b" not in combined_log


@requires_policy_runtime
def test_merge_failure_fails_after_one_bounded_attempt(tmp_path: Path) -> None:
    first = _record(number=123, oid=OID_A)
    second = _record(number=124, oid=OID_B)

    result = _run_policy(
        tmp_path,
        [second, first],
        {123: first, 124: second},
        merge_exit=43,
    )

    assert result.returncode != 0
    assert _calls(tmp_path, "view") == [_expected_view_call(123)]
    assert _calls(tmp_path, "merge") == [
        [
            "pr",
            "merge",
            "123",
            "--repo",
            "andrei649/jarvis-hub",
            "--squash",
            "--match-head-commit",
            OID_A,
        ]
    ]


@requires_policy_runtime
def test_stable_non_nerva_clean_pr_keeps_exact_squash_merge(tmp_path: Path) -> None:
    record = _record()

    result = _run_policy(tmp_path, [record], {123: record})

    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path, "list") == [_expected_list_call()]
    assert _calls(tmp_path, "view") == [_expected_view_call(123)]
    assert _calls(tmp_path, "merge") == [
        [
            "pr",
            "merge",
            "123",
            "--repo",
            "andrei649/jarvis-hub",
            "--squash",
            "--match-head-commit",
            OID_A,
        ]
    ]
