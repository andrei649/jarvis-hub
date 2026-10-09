#!/usr/bin/env python3
"""Bounded, isolated mutation check for the H277 compression stream increment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PYTHON = Path("/tmp/nerva-pr-python-20261001/bin/python")
BASE = "4668be6cd3cfcc2c231edcb7feeaeca30ff26265"
OUT = Path(__file__).with_suffix(".json")
BASE_PY = "agents/core/llm/base.py"
RECOVERY_PY = "agents/core/llm/auxiliary_recovery.py"
TEXT_PY = "agents/core/llm/auxiliary_text.py"
HOLD_PY = "agents/core/compaction_hold.py"
BACKEND_TEST = "tests/test_h277_stream_temperature_backend.py"
COMPRESSION_TEST = "tests/test_h277_compression_temperature_recovery.py"
HASHED = (BASE_PY, RECOVERY_PY, TEXT_PY, HOLD_PY, BACKEND_TEST, COMPRESSION_TEST)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_result(junit: Path) -> dict:
    if not junit.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "failed_tests": []}
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    failed = [f"{case.get('classname')}::{case.get('name')}" for case in cases
              if any(child.tag == "failure" for child in case)]
    return {
        "tests": len(cases), "failures": len(failed),
        "errors": sum(child.tag == "error" for case in cases for child in case),
        "failed_tests": failed,
    }


def run(root: Path, logs: Path, name: str, selectors: tuple[str, ...]) -> dict:
    log = logs / f"{name}.log"
    junit = logs / f"{name}.xml"
    command = [str(PYTHON), "-m", "pytest", *selectors, "-p", "no:cacheprovider",
               "--tb=short", f"--junitxml={junit}"]
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root),
                "JARVIS_TESTING": "1", "JARVIS_RATE_LIMIT": "0",
                "JARVIS_STRICT_EGRESS": "0"})
    started = time.monotonic()
    with log.open("w") as stream:
        try:
            result = subprocess.run(command, cwd=root, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=45, check=False)
            code, timed_out = result.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
    return {"returncode": code, "timed_out": timed_out,
            "seconds": round(time.monotonic() - started, 3),
            "log": str(log), **test_result(junit)}


def copy_source(root: Path) -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "agents"], cwd=REPO)
    paths = [os.fsdecode(item) for item in tracked.split(b"\0") if item]
    paths = [item for item in paths if item.endswith(".py")]
    paths += [BACKEND_TEST, COMPRESSION_TEST, "tests/conftest.py",
              "tests/support/pytest_root_cleanup.py", "pytest.ini"]
    for name in paths:
        src, dest = REPO / name, root / name
        if not src.is_file() or src.is_symlink():
            raise RuntimeError(f"expected regular source file: {name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)


def mutate(root: Path, relative: str, old: str, new: str, originals: dict[str, bytes]) -> None:
    source = originals[relative].decode()
    if source.count(old) != 1:
        raise RuntimeError(f"mutation anchor is not unique: {relative} ({source.count(old)})")
    (root / relative).write_text(source.replace(old, new, 1))


def main() -> None:
    if not PYTHON.is_file():
        raise RuntimeError(f"missing pinned Python: {PYTHON}")
    root = Path(tempfile.mkdtemp(prefix="h277-stream-temperature-mutations-", dir="/tmp"))
    logs = root / "logs"
    logs.mkdir()
    copy_source(root)
    originals = {name: (root / name).read_bytes() for name in HASHED}
    hashes = {name: sha256(content) for name, content in originals.items()}
    summary = {"base": BASE, "timestamp_utc": datetime.now(UTC).isoformat(),
               "python": str(PYTHON), "temporary_root": str(root),
               "source_and_test_sha256": hashes, "mutants": []}
    tests = (BACKEND_TEST, COMPRESSION_TEST)
    summary["baseline"] = run(root, logs, "baseline", tests)
    if (summary["baseline"]["returncode"] != 0 or
            summary["baseline"]["tests"] != 31 or
            summary["baseline"]["failures"] or summary["baseline"]["errors"]):
        summary["status"] = "invalid_baseline"
        OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        raise RuntimeError("isolated baseline failed; see temporary log")

    cases = [
        ("temperature_scope_removed", RECOVERY_PY,
         "return bool(state is not None and state.active and state.backend is backend\n"
         "                and state.model == model and state.task is _current_task()\n"
         "                and (state.route is None\n"
         "                     or _temperature_cache(backend, create=False) is state.route))",
         "return True", (BACKEND_TEST + "::test_temperature_repair_requires_exact_scope[False]",)),
        ("partial_activity_replay_allowed", BASE_PY,
         "can_retry = not (stream_activity if auxiliary_recovery else emitted)\n"
         "                if auxiliary_recovery:\n"
         "                    can_retry = (can_retry and response_cleanup_ok",
         "can_retry = not emitted\n"
         "                if auxiliary_recovery:\n"
         "                    can_retry = (can_retry and True",
         (BACKEND_TEST + "::test_reasoning_frame_blocks_replay_even_if_callback_raises_unload_status",)),
        ("cleanup_gate_removed", BASE_PY,
         "can_retry = (can_retry and response_cleanup_ok",
         "can_retry = (can_retry and True",
         (BACKEND_TEST + "::test_cleanup_exception_that_looks_like_rejection_never_retries",)),
        ("revoked_scope_ignored", RECOVERY_PY,
         "state is not None and state.active and state.backend is backend",
         "state is not None and True and state.backend is backend",
         (BACKEND_TEST + "::test_revoked_scope_blocks_unload_retry",)),
        ("repeated_temperature_retry", BASE_PY,
         "if (auxiliary_recovery and can_retry and not temperature_retried\n"
         "                        and \"temperature\" in payload",
         "if (auxiliary_recovery and can_retry and True\n"
         "                        and True",
         (BACKEND_TEST + "::test_same_rejection_twice_stops_after_two_sends",)),
        ("cache_incomplete_or_error", BASE_PY,
         "temperature_retried and completed and not usage_failed and not refused",
         "temperature_retried",
         (BACKEND_TEST + "::test_incomplete_error_refused_or_degraded_repair_is_not_learned",)),
        ("exact_route_identity_removed", RECOVERY_PY,
         "and (state.route is None\n"
         "                     or _temperature_cache(backend, create=False) is state.route))",
         "and True)",
         (BACKEND_TEST + "::test_repaired_response_cannot_cache_on_client_replaced_during_cleanup",)),
        ("supervisor_revoke_removed", HOLD_PY,
         "if revoke_call is not None:\n            revoke_call()",
         "if revoke_call is not None:\n            pass",
         (COMPRESSION_TEST + "::test_summary_worker_scope_is_revoked_before_cancellation_cleanup",)),
    ]
    for name, relative, old, new, selectors in cases:
        try:
            mutate(root, relative, old, new, originals)
            result = run(root, logs, name, selectors)
            if result["timed_out"] or result["tests"] == 0 or result["errors"]:
                outcome = "invalid"
            elif result["returncode"] == 0:
                outcome = "survived"
            elif result["failures"]:
                outcome = "killed"
            else:
                outcome = "invalid"
            summary["mutants"].append({"name": name, "path": relative,
                                       "outcome": outcome, **result})
        finally:
            (root / relative).write_bytes(originals[relative])
    summary["restored_baseline"] = run(root, logs, "restored_baseline", tests)
    summary["restoration_sha256_match"] = all(
        sha256((root / name).read_bytes()) == hashes[name] for name in HASHED)
    summary["counts"] = {kind: sum(item["outcome"] == kind for item in summary["mutants"])
                         for kind in ("killed", "survived", "invalid")}
    summary["survivor_gaps"] = [item["name"] for item in summary["mutants"]
                                if item["outcome"] == "survived"]
    summary["excluded_equivalent_mutant"] = {
        "name": "activity_guard_removed",
        "prior_observation": "A prior isolated run stayed green with only the activity flag disabled.",
        "reason": "Native retryable HTTP status is captured before frame parsing. A later "
                  "callback exception exits the response context without setting "
                  "response_cleanup_ok, so the separate cleanup gate still prevents replay. "
                  "The single-guard mutation did not change reachable retry behavior.",
    }
    summary["status"] = "complete" if (summary["restoration_sha256_match"] and
        summary["restored_baseline"]["returncode"] == 0 and
        summary["restored_baseline"]["tests"] == 31) else "invalid_restoration"
    OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
