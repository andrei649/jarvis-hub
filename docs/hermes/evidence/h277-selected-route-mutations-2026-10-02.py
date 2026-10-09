#!/usr/bin/env python3
"""Offline, exact-commit mutation probes for selected-conversation image routing."""

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

REPO = Path("/Users/andrei649/Projects/nerva-pr-worktrees/integration")
PYTHON = Path("/tmp/nerva-pr-python-20261001/bin/python")
REVIEW = "agents/core/llm/vision_review.py"
COMPOSER = "agents/core/routers/composer_vision.py"
MAIN = "agents/core/llm/vision_main.py"
SCOPE = {REVIEW, COMPOSER, MAIN}
TEST = "tests/test_h277_selected_composer.py"


def case(id, intent, tests, *edits):
    return {"id": id, "intent": intent, "tests": [f"{TEST}::{name}" for name in tests],
            "edits": [{"file": file, "anchor": anchor, "replacement": replacement}
                      for file, anchor, replacement in edits]}


CASES = [
    case("01_cross_agent_fingerprint", "Drop agent identity from the one-use review fingerprint.",
         ["test_selected_review_fingerprint_binds_agent_with_identical_route"],
         (REVIEW, "_digest((session_id, agent_id, prompt, model, route, binding)),",
          "_digest((session_id, prompt, model, route, binding)),")),
    case("02_session_switch_at_physical_guard", "Ignore a shared-session switch after review consumption.",
         ["test_selected_session_switch_after_review_consume_refuses_at_physical_guard"],
         (COMPOSER, "(orch is None or orch.session_id != turn.session_id\n"
                    "            or history_fingerprint(orch, turn.session_id) != turn.history_digest):",
          "(orch is None\n            or history_fingerprint(orch, turn.session_id) != turn.history_digest):")),
    case("03_route_switch_at_physical_guard", "Ignore selected route drift after review consumption.",
         ["test_selected_route_switch_after_review_consume_refuses_at_physical_guard"],
         (COMPOSER, "if backend is not turn.backend or model != turn.model or route != turn.route:",
          "if backend is not turn.backend or model != turn.model:")),
    case("04_text_only_main", "Offer an explicitly text-only selected main model as a vision route.",
         ["test_selected_image_turn_skips_explicitly_text_only_main"],
         (COMPOSER, "if main_vision_eligibility(backend, model) is False:", "if False:")),
    case("05_local_only_remote_fallback", "Permit a strict-local agent to discover remote fallback.",
         ["test_strict_local_agent_never_discovers_remote_image_fallback"],
         (COMPOSER, "if main is None and agent in LOCAL_ONLY_AGENTS:", "if False:"),
         (COMPOSER, "if agent in LOCAL_ONLY_AGENTS and not config.is_local:", "if False:")),
    case("06_selected_backend_key", "Borrow an ambient key for a selected compatible backend.",
         ["test_selected_remote_model_uses_only_its_backend_key_and_origin"],
         (MAIN, 'key = getattr(backend, "api_key", None)',
          'key = __import__("os").environ.get("OPENROUTER_API_KEY")')),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def test_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root),
                "JARVIS_TESTING": "1", "JARVIS_RATE_LIMIT": "0", "JARVIS_STRICT_EGRESS": "0"})
    return env


def archive(commit: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="nerva-h277-selected-route-", dir="/tmp")).resolve()
    proc = subprocess.Popen(["git", "archive", "--format=tar", commit], cwd=REPO,
                            stdout=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as source:
            for member in source:
                target = (root / member.name).resolve()
                if not target.is_relative_to(root):
                    raise RuntimeError(f"unsafe archive path: {member.name}")
                source.extract(member, root, filter="data")
    finally:
        proc.stdout.close()
    if proc.wait() != 0:
        raise RuntimeError("git archive failed")
    return root


def inventory(commit: str, root: Path) -> dict[str, str]:
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", commit], cwd=REPO)
    hashes = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, _object_id = metadata.split(b" ")
        if mode in {b"100644", b"100755"} and kind == b"blob":
            path = os.fsdecode(name)
            file = root / path
            if not file.is_file() or file.is_symlink():
                raise RuntimeError(f"archive missing tracked file: {path}")
            hashes[path] = digest(file.read_bytes())
    return hashes


def verify(root: Path, expected: dict[str, str]) -> dict:
    changed = [path for path, sha in expected.items()
               if not (root / path).is_file() or digest((root / path).read_bytes()) != sha]
    return {"ok": not changed, "changed": changed, "files_checked": len(expected)}


def junit(path: Path) -> dict:
    if not path.exists():
        return {"junit_missing": True}
    cases = list(ET.parse(path).getroot().iter("testcase"))
    return {"tests": len(cases), "failures": sum(c.tag == "failure" for row in cases for c in row),
            "errors": sum(c.tag == "error" for row in cases for c in row),
            "skipped": sum(c.tag == "skipped" for row in cases for c in row),
            "failed_tests": [f"{row.get('classname')}::{row.get('name')}" for row in cases
                             if any(c.tag == "failure" for c in row)]}


def run_pytest(root: Path, out: Path, stem: str, selected: list[str]) -> dict:
    xml = out / f"{stem}.xml"
    log = out / f"{stem}.log"
    command = [str(PYTHON), "-m", "pytest", *selected, "-p", "no:cacheprovider",
               "--tb=short", f"--junitxml={xml}"]
    start = time.monotonic()
    with log.open("w") as stream:
        stream.write(f"command: {json.dumps(command)}\ncwd: {root}\n\n")
        stream.flush()
        try:
            process = subprocess.run(command, cwd=root, env=test_env(root), stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=120)
            code, timed_out = process.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
            stream.write("\nRUNNER TIMEOUT 120 seconds\n")
    return {"command": command, "cwd": str(root), "log": str(log), "junit": str(xml),
            "returncode": code, "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - start, 3), **junit(xml)}


def mutate(root: Path, out: Path, expected: dict[str, str], item: dict) -> dict:
    files = sorted({edit["file"] for edit in item["edits"]})
    if not set(files) <= SCOPE:
        raise RuntimeError(f"mutant escaped scope: {item['id']}")
    original = {path: (root / path).read_bytes() for path in files}
    result = {"id": item["id"], "intent": item["intent"], "files": files,
              "status": "INVALID", "edits": [],
              "original_sha256_by_file": {path: digest(data) for path, data in original.items()}}
    if any(digest(data) != expected[path] for path, data in original.items()):
        result["invalid_reason"] = "mutated source did not match frozen hash"
        return result
    changed = {path: data.decode("utf-8") for path, data in original.items()}
    try:
        for edit in item["edits"]:
            path, anchor, replacement = edit["file"], edit["anchor"], edit["replacement"]
            count = changed[path].count(anchor)
            result["edits"].append({**edit, "anchor_count": count})
            if count != 1:
                raise ValueError(f"{path} anchor count {count}, expected 1")
            changed[path] = changed[path].replace(anchor, replacement, 1)
        for path, source in changed.items():
            ast.parse(source, filename=path)
            if source.encode() == original[path]:
                raise ValueError(f"identical mutant: {path}")
        result["mutant_sha256_by_file"] = {path: digest(source.encode())
                                            for path, source in changed.items()}
        diff = "".join("".join(difflib.unified_diff(
            original[path].decode().splitlines(keepends=True),
            changed[path].splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}")) for path in files)
        diff_path = out / f"{item['id']}.diff"
        diff_path.write_text(diff)
        result["diff"] = str(diff_path)
        for path, source in changed.items():
            (root / path).write_bytes(source.encode())
        trial = run_pytest(root, out, item["id"], item["tests"])
        result["test"] = trial
        if trial["timed_out"] or trial.get("junit_missing"):
            result["invalid_reason"] = "test timeout or missing JUnit"
        elif trial["returncode"] == 0 and trial["failures"] == 0 and trial["errors"] == 0:
            result["status"] = "SURVIVED"
        elif trial["failures"] > 0 and trial["errors"] == 0:
            result["status"] = "KILLED"
        else:
            result["invalid_reason"] = "collection/setup/runtime error; no valid assertion kill"
    except (SyntaxError, ValueError) as exc:
        result["invalid_reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        for path, data in original.items():
            (root / path).write_bytes(data)
        result["restored_sha256_by_file"] = {path: digest((root / path).read_bytes()) for path in files}
        result["restored"] = all(result["restored_sha256_by_file"][path] == expected[path]
                                 for path in files)
        if not result["restored"]:
            raise RuntimeError(f"failed to restore {item['id']}")
    return result


def main(commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("full frozen commit SHA required")
    if subprocess.check_output(["git", "cat-file", "-t", commit], cwd=REPO,
                               text=True).strip() != "commit":
        raise RuntimeError("source is not a commit")
    if not PYTHON.is_file():
        raise RuntimeError(f"missing interpreter: {PYTHON}")
    out = Path(f"/tmp/nerva-h277-selected-route-mutations-20261002-{commit[:12]}")
    if out.exists():
        raise RuntimeError(f"campaign output already exists; use a fresh frozen commit: {out}")
    out.mkdir()
    root = archive(commit)
    hashes = inventory(commit, root)
    for path in SCOPE | {TEST}:
        if path not in hashes:
            raise RuntimeError(f"frozen commit lacks campaign source or test: {path}")
    for item in CASES:
        for node in item["tests"]:
            name = node.split("::", 1)[1]
            if f"def {name}(" not in (root / TEST).read_text():
                raise RuntimeError(f"frozen commit lacks target test: {node}")
    imported = subprocess.check_output([str(PYTHON), "-c", "import agents; print(agents.__file__)"],
                                       cwd=root, env=test_env(root), text=True).strip()
    if not Path(imported).resolve().is_relative_to(root):
        raise RuntimeError(f"agents import escaped archive: {imported}")
    if list(root.rglob("*.pyc")):
        raise RuntimeError("archive unexpectedly contains bytecode")
    manifest = {"commit": commit, "git_head_at_start": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "archive_root": str(root), "interpreter": str(PYTHON), "imported_agents_path": imported,
        "sha256_by_file": hashes, "source_scope_sha256": {path: hashes[path] for path in SCOPE},
        "test_selection": [TEST], "targeted_case_selection": {row["id"]: row["tests"] for row in CASES},
        "pytest_guards": {"PYTHONDONTWRITEBYTECODE": "1", "socket_allow_hosts": "127.0.0.1,::1,localhost",
                          "timeout_seconds": 30, "pytest_cacheprovider": "disabled"},
        "source_verification_at_start": verify(root, hashes)}
    write_json(out / "source_manifest.json", manifest)
    write_json(out / "cases.json", CASES)
    baseline = run_pytest(root, out, "baseline", [TEST])
    write_json(out / "baseline.json", baseline)
    if baseline["returncode"] != 0 or baseline["failures"] or baseline["errors"]:
        raise RuntimeError(f"baseline not green; inspect {baseline['log']}")
    results = []
    for item in CASES:
        result = mutate(root, out, hashes, item)
        results.append(result)
        write_json(out / "results.json", results)
        print(f"{item['id']}: {result['status']}", flush=True)
    final = run_pytest(root, out, "final_baseline", [TEST])
    restored = verify(root, hashes)
    manifest.update(final_restoration=restored, final_pytest=final)
    write_json(out / "source_manifest.json", manifest)
    summary = {"commit": commit, "cases": len(results),
               "valid": sum(row["status"] != "INVALID" for row in results),
               "killed": sum(row["status"] == "KILLED" for row in results),
               "survived": sum(row["status"] == "SURVIVED" for row in results),
               "invalid": sum(row["status"] == "INVALID" for row in results),
               "baseline_tests": baseline["tests"], "final_tests": final.get("tests"),
               "final_green": final["returncode"] == 0 and final.get("failures") == 0
               and final.get("errors") == 0, "final_source_restored": restored["ok"]}
    write_json(out / "summary.json", summary)
    print(json.dumps({"output": str(out), **summary}, sort_keys=True), flush=True)
    if not summary["final_green"] or not summary["final_source_restored"]:
        raise RuntimeError("final baseline or archive restoration failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True, help="coordinator's committed frozen-source SHA")
    main(parser.parse_args().commit)
