#!/usr/bin/env python3
"""Serial, current-commit H277 video mutation audit in an immutable /tmp archive."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
PYTHON = Path(sys.executable)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def file_hashes(snapshot: Path, names: list[str]) -> tuple[dict[str, str], list[str]]:
    hashes, missing = {}, []
    for name in names:
        path = snapshot / name
        if path.is_file():
            hashes[name] = digest(path)
        else:
            missing.append(name)
    return hashes, missing


def fingerprint(hashes: dict[str, str], missing: list[str]) -> str:
    return hashlib.sha256(json.dumps({"files": hashes, "missing": missing},
                                     sort_keys=True).encode()).hexdigest()


def validate_mutant(snapshot: Path, case: dict) -> dict:
    path = snapshot / case["file"]
    source = path.read_text()
    row = {"label": case["label"], "anchor_count": source.count(case["a"])}
    if row["anchor_count"] != 1:
        row["error"] = "anchor count must be exactly one"
        return row
    try:
        changed = source.replace(case["a"], case["b"])
        ast.parse(changed, filename=case["file"])
        compile(changed, case["file"], "exec")
    except (SyntaxError, ValueError) as exc:
        row["error"] = f"compile error: {exc}"
    return row


def prepare() -> None:
    if (OUT / "source_manifest.json").exists():
        raise RuntimeError("Snapshot already prepared; preserve evidence.")
    plan = json.loads((OUT / "plan.json").read_text())
    ref = plan["source_ref"]
    if git("rev-parse", ref).decode().strip() != ref:
        raise RuntimeError("Pinned source ref changed")
    snapshot = Path(tempfile.mkdtemp(prefix="h277-video-mutations-"))
    archive = snapshot.parent / (snapshot.name + ".tar")
    try:
        archive.write_bytes(git("archive", "--format=tar", ref))
        with tarfile.open(archive) as tar:
            tar.extractall(snapshot, filter="data")
    finally:
        archive.unlink(missing_ok=True)
    names = sorted(filter(None, git("ls-tree", "-r", "--name-only", "-z", ref).decode().split("\0")))
    hashes, missing = file_hashes(snapshot, names)
    manifest = {"head": ref, "snapshot": str(snapshot), "files": hashes, "missing": missing,
                "source_sha256": fingerprint(hashes, missing), "plan_sha256": digest(OUT / "plan.json"),
                "prepared_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dirty_overlay": [], "included_untracked": []}
    write_json("source_manifest.json", manifest)
    checks = [validate_mutant(snapshot, case) for case in plan["mutations"]]
    write_json("anchor_checks.json", checks)
    write_json("state.json", {"status": "prepared", "source_sha256": manifest["source_sha256"],
                              "cases": len(checks), "invalid_preflight": sum("error" in c for c in checks)})
    print(json.dumps({"snapshot": str(snapshot), "cases": len(checks),
                      "invalid_preflight": sum("error" in c for c in checks)}), flush=True)


def verify_snapshot(manifest: dict) -> None:
    snap = Path(manifest["snapshot"])
    for name, expected in manifest["files"].items():
        if digest(snap / name) != expected:
            raise RuntimeError(f"Snapshot hash mismatch: {name}")
    if any((snap / name).exists() for name in manifest["missing"]):
        raise RuntimeError("Snapshot gained a previously missing path")


def junit_summary(path: Path) -> tuple[dict, list[str]]:
    if not path.exists():
        return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}, ["JUnit missing"]
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}, ["JUnit invalid"]
    counts = {name: int(suite.attrib.get(name, 0)) for name in ("tests", "failures", "errors", "skipped")}
    traces = []
    for case in root.iter("testcase"):
        for child in case:
            if child.tag in {"failure", "error"}:
                traces.append(f"{case.attrib.get('name')} [{child.tag}] {child.attrib.get('message', '')}\n{child.text or ''}")
    return counts, traces


def invoke(snapshot: Path, label: str, tests: list[str]) -> tuple[dict, list[str]]:
    (OUT / "logs").mkdir(exist_ok=True)
    (OUT / "junit").mkdir(exist_ok=True)
    xml = OUT / "junit" / (label + ".xml")
    command = [str(PYTHON), "-B", "-m", "pytest", *tests, "-q", f"--junitxml={xml}"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(snapshot))
    start = time.monotonic()
    try:
        process = subprocess.run(command, cwd=snapshot, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=120, text=True)
        rc, output = process.returncode, process.stdout
    except subprocess.TimeoutExpired as exc:
        rc, output = 124, (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout)
    log = OUT / "logs" / (label + ".log")
    log.write_text("COMMAND " + json.dumps(command) + "\n" + output)
    counts, traces = junit_summary(xml)
    record = {"returncode": rc, "elapsed_seconds": round(time.monotonic() - start, 2),
              "command": command, "log": str(log.relative_to(ROOT)),
              "junit": str(xml.relative_to(ROOT)), "junit_counts": counts,
              "log_sha256": digest(log)}
    return record, traces


def provisional_result(evidence: dict, traces: list[str]) -> str:
    counts = evidence["junit_counts"]
    if evidence["returncode"] == 0 and counts["tests"] > 0 and not counts["failures"] and not counts["errors"]:
        return "survived"
    if (evidence["returncode"] != 1 or counts["tests"] <= 0 or counts["errors"]
            or not counts["failures"]):
        return "invalid"
    joined = "\n".join(traces)
    if any(word in joined for word in ("NameError", "ImportError", "ModuleNotFoundError", "TypeError",
                                       "SyntaxError", "RecursionError", "FixtureLookupError")):
        return "invalid"
    if all(("AssertionError" in trace or "DID NOT RAISE" in trace or "Regex pattern did not match" in trace)
           for trace in traces):
        return "assertion_failure"
    return "invalid"


def run() -> None:
    manifest = json.loads((OUT / "source_manifest.json").read_text())
    plan = json.loads((OUT / "plan.json").read_text())
    if digest(OUT / "plan.json") != manifest["plan_sha256"]:
        raise RuntimeError("Mutation plan changed after preparation")
    if any("error" in row for row in json.loads((OUT / "anchor_checks.json").read_text())):
        raise RuntimeError("Initial anchor or compile validation failed")
    snapshot = Path(manifest["snapshot"])
    verify_snapshot(manifest)
    baseline, traces = invoke(snapshot, "baseline", plan["baseline_tests"])
    write_json("baseline.json", baseline)
    if baseline["returncode"] or baseline["junit_counts"]["errors"] or baseline["junit_counts"]["failures"]:
        raise RuntimeError("Baseline tests failed; no mutants run")
    print("BASELINE", baseline["junit_counts"], flush=True)
    results = []
    for index, case in enumerate(plan["mutations"], 1):
        path = snapshot / case["file"]
        original = path.read_text()
        row = {"label": case["label"], "file": case["file"], "invariant": case["invariant"],
               "selectors": case["tests"], "anchor_sha256": hashlib.sha256(case["a"].encode()).hexdigest()}
        try:
            if original.count(case["a"]) != 1:
                row.update(provisional="invalid", reason="anchor mismatch at execution")
            else:
                changed = original.replace(case["a"], case["b"])
                compile(changed, case["file"], "exec")
                path.write_text(changed)
                evidence, traces = invoke(snapshot, case["label"], case["tests"])
                row.update(evidence)
                row["provisional"] = provisional_result(evidence, traces)
                row["failure_excerpts"] = [t[:700] for t in traces]
        except (SyntaxError, ValueError) as exc:
            row.update(provisional="invalid", reason=f"compile: {exc}")
        finally:
            path.write_text(original)
            if digest(path) != manifest["files"][case["file"]]:
                raise RuntimeError("Mutation was not restored: " + case["label"])
        results.append(row)
        write_json("results_provisional.json", {"head": manifest["head"], "results": results})
        print(index, len(plan["mutations"]), case["label"], row["provisional"], flush=True)
    verify_snapshot(manifest)
    write_json("restoration.json", {"result": "passed", "tracked_files_checked": len(manifest["files"]),
                                    "missing_paths_checked": len(manifest["missing"]),
                                    "source_sha256": manifest["source_sha256"]})
    write_json("state.json", {"status": "executed_pending_review", "source_sha256": manifest["source_sha256"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "run"])
    mode = parser.parse_args().mode
    prepare() if mode == "prepare" else run()
