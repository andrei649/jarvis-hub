from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_new_health_debt", ROOT / "scripts" / "check_new_health_debt.py"
)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


def _ruff_for(contents: dict[str, list[dict]]):
    return lambda content, filename: contents.get(content, [])


def test_existing_complexity_is_allowed_even_when_line_moves():
    issue = {"code": "C901", "message": "`route` is too complex (14 > 12)", "location": {"row": 3}}
    result = health.compare_file(
        "agents/route.py",
        base_content="old",
        current_content="new",
        ruff_runner=_ruff_for({"old": [issue], "new": [{**issue, "location": {"row": 20}}]}),
    )
    assert result == []
    improved = {**issue, "message": "`route` is too complex (13 > 12)"}
    assert health.compare_file(
        "agents/route.py",
        base_content="old",
        current_content="better",
        ruff_runner=_ruff_for({"old": [issue], "better": [improved]}),
    ) == []


def test_new_complexity_is_blocked_with_actionable_location():
    issue = {"code": "C901", "message": "`route` is too complex (14 > 12)", "location": {"row": 9}}
    result = health.compare_file(
        "agents/route.py",
        base_content="old",
        current_content="new",
        ruff_runner=_ruff_for({"old": [], "new": [issue]}),
    )
    assert result == [
        {
            "kind": "C901",
            "path": "agents/route.py",
            "line": 9,
            "message": "`route` is too complex (14 > 12)",
        }
    ]


def test_duplicate_complexity_fingerprint_growth_is_still_blocked():
    issue = {"code": "C901", "message": "`inner` is too complex (14 > 12)"}
    result = health.compare_file(
        "agents/route.py",
        base_content="old",
        current_content="new",
        ruff_runner=_ruff_for(
            {
                "old": [{**issue, "location": {"row": 3}}],
                "new": [
                    {**issue, "location": {"row": 3}},
                    {**issue, "location": {"row": 30}},
                ],
            }
        ),
    )
    assert len(result) == 1
    assert result[0]["line"] == 30


def test_existing_ts_nocheck_is_allowed_but_growth_is_blocked():
    assert health.compare_file(
        "frontend/a.ts", base_content="// @ts-nocheck\n", current_content="// @ts-nocheck\n"
    ) == []
    findings = health.compare_file(
        "frontend/a.ts",
        base_content="",
        current_content="// @ts-nocheck\nconst value = 1\n",
    )
    assert findings[0]["kind"] == "ts-nocheck"
    assert findings[0]["line"] == 1


def test_removing_debt_is_allowed():
    issue = {"code": "C901", "message": "`route` is too complex (14 > 12)"}
    result = health.compare_file(
        "agents/route.py",
        base_content="old",
        current_content="new",
        ruff_runner=_ruff_for({"old": [issue], "new": []}),
    )
    assert result == []


def test_evaluate_only_checks_supported_source_files():
    seen = []

    def base_reader(base, path):
        seen.append((base, path))
        return ""

    result = health.evaluate(
        ["README.md", "frontend/a.ts", "agents/a_renamed.py", "frontend/a.ts"],
        base="abc",
        base_reader=base_reader,
        current_reader=lambda path: "",
        ruff_runner=lambda content, filename: [],
        base_paths={"agents/a_renamed.py": "agents/a.py"},
    )
    assert result["status"] == "passed"
    assert result["files_checked"] == ["agents/a_renamed.py", "frontend/a.ts"]
    assert seen == [("abc", "agents/a.py"), ("abc", "frontend/a.ts")]


def test_evaluate_reports_new_debt_count():
    result = health.evaluate(
        ["frontend/a.ts"],
        base="abc",
        base_reader=lambda base, path: "",
        current_reader=lambda path: "// @ts-nocheck\n",
        ruff_runner=lambda content, filename: [],
    )
    assert result["status"] == "failed"
    assert result["new_debt_count"] == 1
