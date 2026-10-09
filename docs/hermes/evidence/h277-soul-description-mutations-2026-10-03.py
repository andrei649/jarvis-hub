"""Isolated runtime mutants for governed SOUL-description drafting."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = {
    "ignore_task_model": (
        "tests/test_h277_soul_description_auxiliary.py::"
        "test_soul_draft_uses_independent_selected_local_model"
    ),
    "skip_h513_scope": (
        "tests/test_h277_soul_description_auxiliary.py::"
        "test_soul_draft_rechecks_h513_at_physical_request"
    ),
    "allow_proxy": (
        "tests/test_h277_soul_description_auxiliary.py::"
        "test_soul_draft_refuses_proxy_before_persona_egress"
    ),
    "ignore_model_body": (
        "tests/test_h277_soul_description_auxiliary.py::"
        "test_soul_draft_binds_selected_payload_at_physical_request[model]"
    ),
}
PATCHES = {
    "ignore_task_model": (
        "auxiliary_text.resolve_auxiliary_model = lambda task, active_model: active_model"
    ),
    "skip_h513_scope": (
        "auxiliary_text.auxiliary_request_scope = "
        "lambda *args, **kwargs: contextlib.nullcontext()"
    ),
    "allow_proxy": (
        "direct_transport.require_direct_async_transport = lambda client, url: None"
    ),
    "ignore_model_body": (
        "auxiliary_text._direct_local_request_check = "
        "lambda *args: (lambda request: None)"
    ),
}
SOURCES = (
    "agents/core/llm/auxiliary_text.py",
    "agents/core/llm/data_handling.py",
    "agents/core/llm/egress.py",
    "agents/core/soul_edit.py",
    "tests/test_h277_soul_description_auxiliary.py",
    "tests/test_soul_edit_route.py",
)


def run(name: str, mutant: bool) -> dict:
    code = f"""
import contextlib
import pytest
from agents.core.llm import auxiliary_text, direct_transport
{PATCHES[name] if mutant else ''}
raise SystemExit(pytest.main(['-q', '--disable-warnings', {CASES[name]!r}]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, check=False, timeout=120,
    )
    output = result.stdout + result.stderr
    expected = result.returncode == (1 if mutant else 0)
    if mutant:
        expected = expected and "FAILED " in output
    if not expected:
        raise AssertionError(f"{name} mutant={mutant} unexpected result:\n{output[-3_000:]}")
    return {"case": name, "mutant": mutant, "exit_code": result.returncode,
            "baseline_passed": not mutant, "killed": mutant}


def main() -> None:
    results = [run(name, False) for name in CASES]
    results.extend(run(name, True) for name in CASES)
    report = {
        "scope": "H277 governed SOUL description producer",
        "files_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SOURCES
        },
        "baseline_passed": len(CASES),
        "mutants_killed": len(CASES),
        "mutants_total": len(CASES),
        "results": results,
    }
    Path(__file__).with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
