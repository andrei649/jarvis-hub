"""Isolated runtime mutants for selected-main local vision metadata."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CASES = {
    "negative_verdict": (
        "tests/test_h277_selected_composer.py::"
        "test_selected_image_turn_uses_local_model_vision_metadata"
    ),
    "review_refresh": (
        "tests/test_h277_selected_composer.py::"
        "test_changed_local_vision_capability_invalidates_image_review"
    ),
    "direct_transport": (
        "tests/test_h277_local_vision_metadata.py::"
        "test_proxy_transport_does_not_receive_model_identity"
    ),
}
SOURCE_PATHS = (
    "agents/core/llm/vision_capability.py",
    "agents/core/routers/composer_vision.py",
    "tests/test_h277_selected_composer.py",
    "tests/test_h277_local_vision_metadata.py",
)


def run(name: str, *, mutant: bool) -> dict:
    patch = {
        "negative_verdict": "vision_capability._lm_studio_verdict = lambda payload, model: None",
        "review_refresh": """
original = vision_capability.prepare_local_model_vision
calls = 0
async def stale_after_review(backend, model):
    global calls
    calls += 1
    if calls == 2:
        return vision_capability.main_vision_eligibility(backend, model)
    return await original(backend, model)
vision_capability.prepare_local_model_vision = stale_after_review
""",
        "direct_transport": (
            "direct_transport.require_direct_async_transport = lambda client, url: None"
        ),
    }[name]
    code = f"""
import pytest
from agents.core.llm import direct_transport, vision_capability
{patch if mutant else ''}
raise SystemExit(pytest.main(['-q', '--disable-warnings', {CASES[name]!r}]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, check=False, timeout=120,
    )
    output = result.stdout + result.stderr
    expected = result.returncode == (1 if mutant else 0)
    if mutant:
        expected = expected and f"FAILED {CASES[name]}" in output
    if not expected:
        raise AssertionError(f"{name} mutant={mutant} unexpected result:\n{output[-3_000:]}")
    return {"case": name, "mutant": mutant, "exit_code": result.returncode,
            "killed": mutant and expected, "baseline_passed": not mutant and expected}


def main() -> None:
    results = [run(name, mutant=False) for name in CASES]
    results += [run(name, mutant=True) for name in CASES]
    report = {
        "scope": "H277 local model vision metadata at composer preparation",
        "files_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SOURCE_PATHS
        },
        "baseline_passed": sum(item["baseline_passed"] for item in results),
        "mutants_killed": sum(item["killed"] for item in results),
        "mutants_total": len(CASES),
        "results": results,
    }
    Path(__file__).with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
