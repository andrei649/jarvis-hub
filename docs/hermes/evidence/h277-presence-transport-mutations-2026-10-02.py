"""Runtime mutation probes for the H277 strict-local transport guard.

Each mutant runs in a fresh Python process; source files remain untouched.
This proves two distinct guard positions are observed by the focused tests.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEST = "tests/test_h513_presence_policy.py"
CASES = {
    "preflight": "test_strict_local_explanation_refuses_proxy_before_generator",
    "physical": "test_strict_local_explanation_rechecks_late_proxy_mount",
}


def run(case: str, *, mutant: bool) -> dict:
    code = f"""
import pytest
from agents.core.llm import direct_transport

original = direct_transport.require_direct_async_transport
calls = 0

def modified(client, url):
    global calls
    calls += 1
    if {mutant!r} and (({case!r} == 'preflight' and calls == 1)
                         or ({case!r} == 'physical' and calls > 1)):
        return None
    return original(client, url)

direct_transport.require_direct_async_transport = modified
raise SystemExit(pytest.main(['-q', '--disable-warnings',
    '{TEST}::{CASES[case]}']))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, check=False, timeout=90,
    )
    output = result.stdout + result.stderr
    expected = result.returncode != 0 if mutant else result.returncode == 0
    if mutant:
        expected = expected and "Failed: DID NOT RAISE DataHandlingRefused" in output
    if not expected:
        raise AssertionError(f"{case} mutant={mutant} unexpected result:\n{output[-3_000:]}")
    return {"case": case, "mutant": mutant, "exit_code": result.returncode,
            "killed": mutant and expected, "baseline_passed": not mutant and expected}


def main() -> None:
    source = ROOT / "agents/core/house/presence.py"
    test = ROOT / TEST
    results = [run(case, mutant=False) for case in CASES]
    results += [run(case, mutant=True) for case in CASES]
    report = {
        "scope": "H277 House presence direct-transport preflight and physical hook",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(test.read_bytes()).hexdigest(),
        "baseline": sum(item["baseline_passed"] for item in results),
        "mutants_killed": sum(item["killed"] for item in results),
        "mutants_total": len(CASES),
        "results": results,
    }
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
