#!/usr/bin/env python3
"""Second, serial pass: first-pass survivors against the selected 153-case baseline."""
import json
from pathlib import Path

import run_bounded as runner

OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / "source_manifest.json").read_text())
plan = json.loads((OUT / "plan.json").read_text())
first = {r["label"]: r for r in json.loads((OUT / "results_provisional.json").read_text())["results"]}
snapshot = Path(manifest["snapshot"])
runner.verify_snapshot(manifest)
results = []
for case in plan["mutations"]:
    if first[case["label"]]["provisional"] != "survived":
        continue
    path = snapshot / case["file"]
    original = path.read_text()
    row = {"label": case["label"], "selectors": plan["baseline_tests"]}
    try:
        assert original.count(case["a"]) == 1
        changed = original.replace(case["a"], case["b"])
        compile(changed, case["file"], "exec")
        path.write_text(changed)
        evidence, traces = runner.invoke(snapshot, case["label"] + "__broad", plan["baseline_tests"])
        row.update(evidence)
        row["provisional"] = runner.provisional_result(evidence, traces)
        row["failure_excerpts"] = [t[:700] for t in traces]
    finally:
        path.write_text(original)
        assert runner.digest(path) == manifest["files"][case["file"]]
    results.append(row)
    runner.write_json("results_broad.json", {"head": manifest["head"], "results": results})
    print(len(results), case["label"], row["provisional"], flush=True)
runner.verify_snapshot(manifest)
runner.write_json("restoration_broad.json", {"result": "passed", "tracked_files_checked": len(manifest["files"]),
                                              "source_sha256": manifest["source_sha256"]})
