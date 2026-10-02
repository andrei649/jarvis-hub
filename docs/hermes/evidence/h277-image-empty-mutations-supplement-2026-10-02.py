#!/usr/bin/env python3
"""Two exact-commit supplemental governed image retry mutation probes."""

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
OUT = Path("/tmp/nerva-image-empty-mutations-20261002/supplement")
PYTHON = Path("/tmp/nerva-pr-python-20261001/bin/python")
VISION_POLICY = "agents/core/llm/vision_policy.py"
VISION_RETRY = "agents/core/llm/vision_retry.py"
NATIVE_RESPONSE = "agents/core/llm/native_response.py"
VLM = "agents/core/llm/vlm.py"
VIDEO_ANALYSIS = "agents/core/video_analysis.py"
SOURCE_SCOPE = [VISION_POLICY, VISION_RETRY, NATIVE_RESPONSE, VLM, VIDEO_ANALYSIS]
TESTS = [
    "tests/test_h277_image_retry_scope_edges.py",
    "tests/test_h277_image_empty_retry.py",
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
    root = Path(tempfile.mkdtemp(prefix="nerva-h277-image-empty-supplement-", dir="/tmp")).resolve()
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
    {"id": "S01_final_http_hook_position", "file": VISION_POLICY,
     "anchor": "        if backend.client.event_hooks['request'][-1] is not last_request_hook:\n",
     "replacement": "        if False:\n",
     "intent": "Remove the final-hook-position guard against an appended mutator.",
     "tests": ["tests/test_h277_image_retry_scope_edges.py::test_hook_appended_after_scope_guard_cannot_reach_transport"]},
    {"id": "S02_governed_text_only_gate", "file": VLM,
     "anchor": "        if scope is not None and image_bearing:\n",
     "replacement": "        if scope is not None:\n",
     "intent": "Allow an empty text-only call to enter the governed image retry path.",
     "tests": ["tests/test_h277_image_retry_scope_edges.py::test_text_only_call_in_governed_scope_never_retries"]},
]


def edits_for(case: dict) -> list[dict]:
    if "edits" in case:
        return case["edits"]
    return [{"file": case["file"], "anchor": case["anchor"],
             "replacement": case["replacement"]}]


def verify_case_tests(root: Path) -> None:
    for case in CASES:
        if not case["tests"]:
            raise RuntimeError(f"case has no tests: {case['id']}")
        for node in case["tests"]:
            name, marker = node.split("::", 1)
            path = root / name
            if not path.is_file() or f"def {marker}(" not in path.read_text():
                raise RuntimeError(f"frozen archive lacks targeted test: {node}")


def run_case(root: Path, expected_hashes: dict[str, str], case: dict) -> dict:
    edits = edits_for(case)
    files = sorted({edit["file"] for edit in edits})
    if not set(files).issubset(SOURCE_SCOPE):
        raise RuntimeError(f"case escaped the five-source scope: {case['id']}")
    original = {name: (root / name).read_bytes() for name in files}
    result = {"id": case["id"], "intent": case["intent"], "files": files,
              "original_sha256_by_file": {name: sha256(data) for name, data in original.items()},
              "edits": [], "status": "INVALID"}
    if any(sha256(original[name]) != expected_hashes[name] for name in files):
        result["invalid_reason"] = "source hash does not match frozen archive"
        return result
    text_by_file = {name: original[name].decode("utf-8") for name in files}
    try:
        for edit in edits:
            name, anchor, replacement = edit["file"], edit["anchor"], edit["replacement"]
            count = text_by_file[name].count(anchor)
            result["edits"].append({**edit, "anchor_count": count})
            if count != 1:
                raise ValueError(f"{name} anchor count {count}, expected 1")
            text_by_file[name] = text_by_file[name].replace(anchor, replacement, 1)
        for name, text in text_by_file.items():
            ast.parse(text, filename=name)
            if text.encode("utf-8") == original[name]:
                raise ValueError(f"mutant identical to source: {name}")
        result["mutant_sha256_by_file"] = {name: sha256(text.encode("utf-8"))
                                            for name, text in text_by_file.items()}
        diff = "".join("".join(difflib.unified_diff(
            original[name].decode().splitlines(keepends=True),
            text_by_file[name].splitlines(keepends=True),
            fromfile=f"a/{name}", tofile=f"b/{name}")) for name in files)
        diff_path = OUT / f"{case['id']}.diff"
        diff_path.write_text(diff)
        result["diff"] = str(diff_path)
        for name, text in text_by_file.items():
            (root / name).write_bytes(text.encode("utf-8"))
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
        for name, data in original.items():
            (root / name).write_bytes(data)
        result["restored_sha256_by_file"] = {name: sha256((root / name).read_bytes()) for name in files}
        result["restored"] = all(result["restored_sha256_by_file"][name] == expected_hashes[name]
                                 for name in files)
        if not result["restored"]:
            raise RuntimeError(f"failed to restore case {case['id']}")
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
            "five_source_sha256": {name: hashes[name] for name in SOURCE_SCOPE},
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
    verify_case_tests(root)
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
