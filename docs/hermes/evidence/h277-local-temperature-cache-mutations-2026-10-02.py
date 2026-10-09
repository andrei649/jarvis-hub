"""Isolated runtime mutants for learned local auxiliary temperature omission."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = {
    "ignore_cache": (
        "tests/test_h277_auxiliary_parameter_recovery.py::"
        "test_successful_repair_is_remembered_for_later_local_auxiliary_call"
    ),
    "forget_rejection": (
        "tests/test_h277_auxiliary_parameter_recovery.py::"
        "test_successful_repair_is_remembered_for_later_local_auxiliary_call"
    ),
    "reuse_other_client": (
        "tests/test_h277_auxiliary_parameter_recovery.py::"
        "test_cached_auxiliary_omission_is_bound_to_exact_route[client]"
    ),
}
PATCHES = {
    "ignore_cache": "base.omit_rejected_temperature = lambda backend, model: False",
    "forget_rejection": "base.remember_temperature_rejection = lambda backend, model: None",
    "reuse_other_client": """
original = auxiliary_recovery._temperature_cache
def stale_client(backend, *, create):
    cache = vars(backend).get("_auxiliary_temperature_cache")
    if cache is not None and not create:
        cache.client = backend.client
        cache.base_url = backend.base_url
        cache.client_base_url = str(backend.client.base_url)
        url = backend.client.build_request("POST", "/v1/chat/completions").url
        cache.transport = backend.client._transport_for_url(url)
    return original(backend, create=create)
auxiliary_recovery._temperature_cache = stale_client
""",
}
SOURCES = (
    "agents/core/llm/auxiliary_recovery.py",
    "agents/core/llm/base.py",
    "tests/test_h277_auxiliary_parameter_recovery.py",
)


def run(name: str, mutant: bool) -> dict:
    code = f"""
import pytest
from agents.core.llm import auxiliary_recovery, base
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
        "scope": "H277 local auxiliary temperature capability memory",
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
