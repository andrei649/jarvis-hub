#!/usr/bin/env python3
"""Offline, exact-commit, bounded H277 valid-empty retry mutation verification."""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

COMMIT = ""  # Required --commit from the coordinator's frozen-source notice.
REPO = Path("/Users/andrei649/Projects/nerva-pr-worktrees/integration")
OUT = Path("/tmp/nerva-video-empty-mutations-20261002")
PYTHON = Path("/tmp/nerva-pr-python-20261001/bin/python")
ANALYSIS = "agents/core/video_analysis.py"
PARSER = "agents/core/llm/video_retry.py"
NATIVE = "agents/core/llm/video_native.py"
TESTS = [
    "tests/test_h277_video_empty_retry.py",
    "tests/test_h277_video_analysis.py",
    "tests/test_h277_video_fallback.py",
    "tests/test_h277_video_routes.py",
    "tests/test_h277_video_candidate_consent.py",
    "tests/test_h277_video_provider_chain.py",
    "tests/test_h277_video_failures.py",
    "tests/test_h277_video_boundaries.py",
    "tests/test_h277_video_native.py",
    "tests/test_h277_video_gemini.py",
    "tests/test_h277_video_retry.py",
    "tests/test_h513_data_handling.py",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def manifest_path() -> Path:
    return OUT / "source_manifest.json"


def load_manifest() -> dict:
    return json.loads(manifest_path().read_text())


def tracked_regular_files() -> list[dict]:
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", COMMIT], cwd=REPO)
    entries = []
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, object_id = metadata.split(b" ")
        if mode in {b"100644", b"100755"} and kind == b"blob":
            entries.append({"path": os.fsdecode(name), "mode": mode.decode(),
                            "git_object": object_id.decode()})
    return entries


def archive_exact_commit() -> Path:
    root = Path(tempfile.mkdtemp(prefix="nerva-h277-video-empty-mutations-", dir="/tmp")).resolve()
    proc = subprocess.Popen(["git", "archive", "--format=tar", COMMIT], cwd=REPO,
                            stdout=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            for member in archive:
                target = (root / member.name).resolve()
                if not target.is_relative_to(root):
                    raise RuntimeError(f"unsafe archive path: {member.name}")
                archive.extract(member, root, filter="data")
    finally:
        proc.stdout.close()
    if proc.wait() != 0:
        raise RuntimeError("git archive failed")
    return root


def source_inventory(root: Path, entries: list[dict]) -> dict[str, str]:
    hashes = {}
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing tracked regular file: {path}")
        hashes[entry["path"]] = sha256(path.read_bytes())
    return hashes


def verify_source(root: Path, expected: dict[str, str]) -> dict:
    actual = {name: sha256((root / name).read_bytes()) for name in expected}
    changed = [name for name in expected if actual[name] != expected[name]]
    return {"ok": not changed, "changed": changed, "files_checked": len(expected)}


def expanded_tests(root: Path) -> list[str]:
    missing = [name for name in TESTS if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"frozen archive lacks focused tests: {missing}")
    return TESTS


def pytest_command(root: Path, junit: Path, selection: list[str] | None = None) -> list[str]:
    return [str(PYTHON), "-m", "pytest", *(selection or expanded_tests(root)),
            "-p", "no:cacheprovider", "--tb=short", f"--junitxml={junit}"]


def test_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root),
                "JARVIS_TESTING": "1", "JARVIS_RATE_LIMIT": "0",
                "JARVIS_STRICT_EGRESS": "0"})
    return env


def junit_counts(path: Path) -> dict:
    if not path.exists():
        return {"junit_missing": True}
    doc = ET.parse(path).getroot()
    cases = list(doc.iter("testcase"))
    return {"tests": len(cases),
            "failures": sum(child.tag == "failure" for case in cases for child in case),
            "errors": sum(child.tag == "error" for case in cases for child in case),
            "skipped": sum(child.tag == "skipped" for case in cases for child in case),
            "failed_tests": [f"{case.get('classname')}::{case.get('name')}"
                             for case in cases if any(child.tag == "failure" for child in case)]}


def run_pytest(root: Path, stem: str, selection: list[str] | None = None) -> dict:
    junit = OUT / f"{stem}.xml"
    log = OUT / f"{stem}.log"
    command = pytest_command(root, junit, selection)
    started = time.monotonic()
    with log.open("w") as stream:
        stream.write("command: " + json.dumps(command) + "\n")
        stream.write("cwd: " + str(root) + "\n")
        stream.write("PYTHONDONTWRITEBYTECODE=1\n\n")
        stream.flush()
        try:
            result = subprocess.run(command, cwd=root, env=test_env(root), stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120)
            returncode = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
            stream.write("\nRUNNER TIMEOUT 120 seconds\n")
    return {"command": command, "cwd": str(root), "log": str(log), "junit": str(junit),
            "returncode": returncode, "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 3), **junit_counts(junit)}


CASES = [
    {"id": "01_empty_policy_hmac", "file": ANALYSIS,
     "anchor": '        if empty_count:\n            material = {**material, "_internal_video_empty_policy": "consumer-once:v1"}\n',
     "replacement": '        if False:\n            material = {**material, "_internal_video_empty_policy": "consumer-once:v1"}\n',
     "intent": "Remove the enabled consumer policy marker from signed class material.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_setting_flip_after_signed_approval_refuses_before_model_send",
               "tests/test_h277_video_empty_retry.py::test_setting_flip_on_first_client_close_blocks_restart"]},
    {"id": "02_empty_notice_disclosure", "file": ANALYSIS,
     "anchor": '            elif empty_count:\n                prefix = "Video full-chain empty restart once: "\n',
     "replacement": '            elif empty_count:\n                prefix = "Video primary retry once: "\n',
     "intent": "Omit explicit full-chain retry disclosure from the empty-only notice.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_setting_flip_after_signed_approval_refuses_before_model_send"]},
    {"id": "03_empty_parser_budget_two", "file": PARSER,
     "anchor": '    if value == "1":\n        return 1\n    raise VideoEmptyRetryConfigError("invalid video empty retry setting")\n',
     "replacement": '    if value in {"1", "2"}:\n        return int(value)\n    raise VideoEmptyRetryConfigError("invalid video empty retry setting")\n',
     "intent": "Accept owner empty retry budget two, outside the fixed 0/1 contract.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_empty_budget_invalid_values_are_sanitized"]},
    {"id": "04_consumer_cap_only", "file": ANALYSIS,
     "anchor": '                for consumer_call in range(1, 2 + empty_count):\n',
     "replacement": '                for consumer_call in range(1, 3 + empty_count):\n',
     "intent": "Raise the loop cap alone; the second-empty terminal guard remains.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_second_empty_is_terminal_and_never_starts_third_call",
               "tests/test_h277_video_empty_retry.py::test_five_route_chain_never_exceeds_two_full_calls"]},
    {"id": "05_second_empty_guard_only", "file": ANALYSIS,
     "anchor": '                                if consumer_call > empty_count:\n',
     "replacement": '                                if consumer_call > empty_count + 1:\n',
     "intent": "Relax the terminal guard alone; the two-call loop cap remains.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_second_empty_is_terminal_and_never_starts_third_call",
               "tests/test_h277_video_empty_retry.py::test_five_route_chain_never_exceeds_two_full_calls"]},
    {"id": "06_compound_cap_and_terminal", "file": ANALYSIS,
     "edits": [
         ('                for consumer_call in range(1, 2 + empty_count):\n',
          '                for consumer_call in range(1, 3 + empty_count):\n'),
         ('                                if consumer_call > empty_count:\n',
          '                                if consumer_call > empty_count + 1:\n')],
     "intent": "COMPOUND: relax BOTH call-cap guards to allow an actual third consumer call.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_second_empty_is_terminal_and_never_starts_third_call",
               "tests/test_h277_video_empty_retry.py::test_five_route_chain_never_exceeds_two_full_calls"]},
    {"id": "07_disable_chain_restart", "file": ANALYSIS,
     "anchor": '                    if not restart:\n                        break\n',
     "replacement": '                    if restart:\n                        break\n',
     "intent": "Prevent the valid-empty second full chain, including fallback-empty restart at primary.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_empty_fallback_restarts_from_primary",
               "tests/test_h277_video_empty_retry.py::test_signed_compatible_primary_empty_restarts_full_consumer"]},
    {"id": "08_transient_budget_per_call", "file": ANALYSIS,
     "anchor": '                        max_attempts = 1 + retry_count if route_index == 0 else 1\n',
     "replacement": '                        max_attempts = 1 + retry_count if route_index == 0 and consumer_call == 1 else 1\n',
     "intent": "Remove the primary transient retry budget from the second consumer call.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_primary_transient_budget_is_fresh_in_each_consumer_call"]},
    {"id": "09_chosen_call_provenance", "file": ANALYSIS,
     "anchor": '                                    result["chosen_call"] = consumer_call\n',
     "replacement": '                                    pass  # chosen_call provenance removed\n',
     "intent": "Remove chosen consumer-call provenance; a result-shape check, not physical-send proof.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_enabled_first_call_success_reports_provenance",
               "tests/test_h277_video_empty_retry.py::test_signed_compatible_primary_empty_restarts_full_consumer"]},
    {"id": "10_compatible_finish_exclusion", "file": ANALYSIS,
     "anchor": '    if choice.get("finish_reason") != "stop" or not isinstance(message, dict) or "content" not in message:\n',
     "replacement": '    if choice.get("finish_reason") not in {"stop", "length"} or not isinstance(message, dict) or "content" not in message:\n',
     "intent": "Treat length-truncated compatible empty content as an eligible empty success.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_compatible_invalid_or_nonempty_reasoning_never_restarts"]},
    {"id": "11_compatible_reasoning_exclusion", "file": ANALYSIS,
     "anchor": '        if value is not None and (not isinstance(value, str) or bool(value.strip())):\n',
     "replacement": '        if False and value is not None and (not isinstance(value, str) or bool(value.strip())):\n',
     "intent": "Allow meaningful reasoning-only output to masquerade as a valid empty answer.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_compatible_invalid_or_nonempty_reasoning_never_restarts"]},
    {"id": "12_gemini_finish_exclusion", "file": NATIVE,
     "anchor": '    if not isinstance(candidate, dict) or candidate.get("finishReason") != "STOP":\n',
     "replacement": '    if not isinstance(candidate, dict) or candidate.get("finishReason") not in {"STOP", "MAX_TOKENS"}:\n',
     "intent": "Treat a truncated Gemini candidate as a typed valid empty response.",
     "tests": ["tests/test_h277_video_empty_retry.py::test_gemini_invalid_empty_never_gets_typed_recovery"]},
]


def edits_for(case: dict) -> list[tuple[str, str]]:
    if "edits" in case:
        return case["edits"]
    return [(case["anchor"], case["replacement"])]


def run_case(root: Path, expected_hashes: dict[str, str], case: dict) -> dict:
    path = root / case["file"]
    original = path.read_bytes()
    result = {"id": case["id"], "intent": case["intent"], "file": case["file"],
              "original_sha256": sha256(original), "edits": [], "status": "INVALID"}
    if sha256(original) != expected_hashes[case["file"]]:
        result["invalid_reason"] = "source hash does not match frozen archive"
        return result
    text = original.decode("utf-8")
    try:
        for anchor, replacement in edits_for(case):
            count = text.count(anchor)
            result["edits"].append({"anchor": anchor, "replacement": replacement,
                                    "anchor_count": count})
            if count != 1:
                raise ValueError(f"anchor count {count}, expected 1")
            text = text.replace(anchor, replacement, 1)
        ast.parse(text, filename=case["file"])
        changed = text.encode("utf-8")
        if changed == original:
            raise ValueError("mutant identical to source")
        result["mutant_sha256"] = sha256(changed)
        diff = "".join(difflib.unified_diff(original.decode().splitlines(keepends=True),
                                            text.splitlines(keepends=True),
                                            fromfile=f"a/{case['file']}",
                                            tofile=f"b/{case['file']}"))
        diff_path = OUT / f"{case['id']}.diff"
        diff_path.write_text(diff)
        result["diff"] = str(diff_path)
        path.write_bytes(changed)
        test = run_pytest(root, case["id"], case["tests"])
        result["test"] = test
        if test["timed_out"] or test.get("junit_missing"):
            result["invalid_reason"] = "test infrastructure timeout or missing JUnit"
        elif test["returncode"] == 0 and test["failures"] == 0 and test["errors"] == 0:
            result["status"] = "SURVIVED"
        elif test["failures"] > 0 and test["errors"] == 0:
            result["status"] = "KILLED"
        else:
            result["invalid_reason"] = "setup/collection/runtime error; no valid assertion kill"
    except (SyntaxError, ValueError) as exc:
        result["invalid_reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        path.write_bytes(original)
        result["restored_sha256"] = sha256(path.read_bytes())
        result["restored"] = result["restored_sha256"] == expected_hashes[case["file"]]
        if not result["restored"]:
            raise RuntimeError(f"failed to restore {case['file']}")
    return result


def baseline() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"[0-9a-f]{40}", COMMIT):
        raise RuntimeError("a full frozen commit SHA is required")
    if subprocess.check_output(["git", "cat-file", "-t", COMMIT], cwd=REPO,
                               text=True).strip() != "commit":
        raise RuntimeError("frozen source is not a commit")
    if manifest_path().exists():
        manifest = load_manifest()
        if manifest["commit"] != COMMIT or not verify_source(Path(manifest["archive_root"]),
                                                                 manifest["sha256_by_file"])["ok"]:
            raise RuntimeError("existing archive is not the frozen source")
        root = Path(manifest["archive_root"])
    else:
        if not PYTHON.is_file():
            raise RuntimeError(f"missing interpreter {PYTHON}")
        root = archive_exact_commit()
        entries = tracked_regular_files()
        hashes = source_inventory(root, entries)
        import_command = [str(PYTHON), "-c", "import agents; print(agents.__file__)"]
        imported = subprocess.check_output(import_command, cwd=root, env=test_env(root), text=True).strip()
        if not Path(imported).resolve().is_relative_to(root):
            raise RuntimeError(f"agents import escaped archive: {imported}")
        if list(root.rglob("*.pyc")):
            raise RuntimeError("archive unexpectedly contains bytecode")
        manifest = {"commit": COMMIT, "git_head_at_start": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "archive_root": str(root), "interpreter": str(PYTHON), "import_command": import_command,
            "imported_agents_path": imported, "tracked_regular_files": entries,
            "sha256_by_file": hashes, "source_verification_at_start": verify_source(root, hashes),
            "test_selection": expanded_tests(root), "pytest_command_template": pytest_command(root, OUT / "NAME.xml"),
            "targeted_case_selection": {case["id"]: case["tests"] for case in CASES},
            "pytest_guards": {"PYTHONDONTWRITEBYTECODE": "1", "socket_allow_hosts": "127.0.0.1,::1,localhost",
                              "timeout_seconds": 30, "pytest_cacheprovider": "disabled"}}
        write_json(manifest_path(), manifest)
    result = run_pytest(root, "baseline")
    write_json(OUT / "baseline.json", result)
    if result["returncode"] != 0 or result["failures"] or result["errors"]:
        raise RuntimeError(f"baseline not green: {result}")
    print(f"BASELINE GREEN: {result['tests']} tests, {result['duration_seconds']} s; archive {root}", flush=True)


def mutations() -> None:
    write_json(OUT / "cases.json", CASES)
    manifest = load_manifest()
    root = Path(manifest["archive_root"])
    expected = manifest["sha256_by_file"]
    before = verify_source(root, expected)
    if not before["ok"]:
        raise RuntimeError(f"archive drift before mutations: {before['changed']}")
    baseline_result = json.loads((OUT / "baseline.json").read_text())
    if baseline_result["returncode"] != 0:
        raise RuntimeError("baseline did not pass")
    results_path = OUT / "results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else []
    if [row["id"] for row in results] != [case["id"] for case in CASES[:len(results)]]:
        raise RuntimeError("existing results are not a prefix of the frozen case list")
    for case in CASES:
        if len(results) and case["id"] in {row["id"] for row in results}:
            continue
        result = run_case(root, expected, case)
        results.append(result)
        write_json(results_path, results)
        print(f"{case['id']}: {result['status']}", flush=True)
    final = run_pytest(root, "final_baseline")
    final_source = verify_source(root, expected)
    manifest["final_restoration"] = final_source
    manifest["final_pytest"] = final
    write_json(manifest_path(), manifest)
    summary = {"commit": COMMIT, "cases": len(results),
               "killed": sum(row["status"] == "KILLED" for row in results),
               "survived": sum(row["status"] == "SURVIVED" for row in results),
               "invalid": sum(row["status"] == "INVALID" for row in results),
               "baseline_tests": baseline_result["tests"],
               "final_tests": final.get("tests"), "final_green": final["returncode"] == 0
               and final.get("failures") == 0 and final.get("errors") == 0,
               "final_source_restored": final_source["ok"]}
    write_json(OUT / "summary.json", summary)
    print("FINAL: " + json.dumps(summary, sort_keys=True), flush=True)
    if not summary["final_green"] or not summary["final_source_restored"]:
        raise RuntimeError("final baseline or source restoration failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "mutations"])
    parser.add_argument("--commit", required=True, help="full SHA from coordinator frozen-source notice")
    args = parser.parse_args()
    COMMIT = args.commit
    if args.phase == "baseline":
        baseline()
    else:
        mutations()
