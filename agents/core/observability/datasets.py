"""
datasets.py — H9.3b Dataset Regression Tracking (extends H9.3 eval harness).

Persistent, *versioned* eval datasets (JSONL) plus a run log, so eval scores can
be tracked over time and two runs compared to catch regressions — the piece a CI
gate needs on top of the in-memory H9.3 EvalHarness.

Layout (under ``root``, default ``memory_logs/eval``)::

    datasets/<name>/v1.jsonl        # one JSON case per line
    datasets/<name>/v2.jsonl
    datasets/<name>/runs.jsonl      # one JSON run-summary per line

A *case* is ``{"name", "prompt", "expect_contains"?, "metadata"?}``. Scorers are
callables and can't be serialized, so file datasets use ``expect_contains``
(substring) checks; in-process suites can still use the full EvalHarness.

Pure-Python, file-based, fully offline-testable (inject a fake runner).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .eval import EvalCase, EvalHarness


class DatasetStore:
    def __init__(self, root: str | Path = "memory_logs/eval") -> None:
        self.root = Path(root)
        self.datasets_dir = self.root / "datasets"

    # ── paths ────────────────────────────────────────────────────────────────

    def _dir(self, name: str) -> Path:
        return self.datasets_dir / name

    def _version_file(self, name: str, version: int) -> Path:
        return self._dir(name) / f"v{version}.jsonl"

    def _runs_file(self, name: str) -> Path:
        return self._dir(name) / "runs.jsonl"

    # ── dataset versions ─────────────────────────────────────────────────────

    def versions(self, name: str) -> list[int]:
        d = self._dir(name)
        if not d.exists():
            return []
        out = []
        for f in d.glob("v*.jsonl"):
            try:
                out.append(int(f.stem[1:]))
            except ValueError:
                continue
        return sorted(out)

    def latest_version(self, name: str) -> Optional[int]:
        vs = self.versions(name)
        return vs[-1] if vs else None

    def save_version(self, name: str, cases: list[dict]) -> int:
        """Write *cases* as a new auto-incremented version; return its number."""
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        version = (self.latest_version(name) or 0) + 1
        path = self._version_file(name, version)
        with path.open("w", encoding="utf-8") as fh:
            for case in cases:
                fh.write(json.dumps(case, ensure_ascii=False) + "\n")
        return version

    def load(self, name: str, version: Optional[int] = None) -> list[dict]:
        """Load cases for *version* (default: latest). Empty list if missing."""
        if version is None:
            version = self.latest_version(name)
        if version is None:
            return []
        path = self._version_file(name, version)
        if not path.exists():
            return []
        cases = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                cases.append(json.loads(line))
        return cases

    def list_datasets(self) -> list[dict]:
        if not self.datasets_dir.exists():
            return []
        out = []
        for d in sorted(self.datasets_dir.iterdir()):
            if not d.is_dir():
                continue
            latest = self.latest_version(d.name)
            runs = self._read_runs(d.name)
            out.append({
                "name": d.name,
                "latest_version": latest,
                "versions": self.versions(d.name),
                "cases": len(self.load(d.name, latest)) if latest else 0,
                "last_score": runs[-1]["score"] if runs else None,
                "runs": len(runs),
            })
        return out

    # ── runs ─────────────────────────────────────────────────────────────────

    def _read_runs(self, name: str) -> list[dict]:
        path = self._runs_file(name)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def record_run(self, name: str, version: int, result: dict) -> str:
        """Append a run summary (from EvalHarness.run) and return its run_id."""
        run_id = uuid.uuid4().hex[:8]
        record = {
            "run_id": run_id,
            "ts": time.time(),
            "version": version,
            "score": round(result.get("score", 0.0), 4),
            "passed": result.get("passed", 0),
            "total": result.get("total", 0),
            # keep per-case pass/score (drop responses) so we can diff later
            "cases": [
                {"name": r["name"], "passed": r["passed"], "score": r["score"]}
                for r in result.get("results", [])
            ],
        }
        self._dir(name).mkdir(parents=True, exist_ok=True)
        with self._runs_file(name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return run_id

    def runs(self, name: str, last_n: int = 20) -> list[dict]:
        """Run summaries (without per-case detail), most-recent first."""
        items = self._read_runs(name)
        items.reverse()
        return [
            {k: v for k, v in r.items() if k != "cases"} for r in items[:last_n]
        ]

    def get_run(self, name: str, run_id: str) -> Optional[dict]:
        for r in self._read_runs(name):
            if r["run_id"] == run_id:
                return r
        return None

    def compare(self, name: str, run_a: str, run_b: str) -> dict:
        """Diff two runs: per-case regressions/improvements + score delta.

        ``run_a`` is the baseline, ``run_b`` the candidate. A *regression* is a
        case that passed in the baseline but fails in the candidate.
        """
        a = self.get_run(name, run_a)
        b = self.get_run(name, run_b)
        if a is None or b is None:
            return {"error": "run not found", "a": run_a, "b": run_b}
        a_cases = {c["name"]: c for c in a["cases"]}
        b_cases = {c["name"]: c for c in b["cases"]}
        shared = a_cases.keys() & b_cases.keys()
        regressed = sorted(
            n for n in shared if a_cases[n]["passed"] and not b_cases[n]["passed"]
        )
        improved = sorted(
            n for n in shared if not a_cases[n]["passed"] and b_cases[n]["passed"]
        )
        return {
            "dataset": name,
            "a": {"run_id": run_a, "version": a["version"], "score": a["score"]},
            "b": {"run_id": run_b, "version": b["version"], "score": b["score"]},
            "score_delta": round(b["score"] - a["score"], 4),
            "regressed": regressed,
            "improved": improved,
            "regression": bool(regressed),
        }

    # ── run a dataset through a runner (production: orchestrator.handle_input) ─

    async def run_dataset(
        self,
        name: str,
        runner: Callable[[str], Awaitable[str]],
        version: Optional[int] = None,
    ) -> dict:
        """Load a dataset version, evaluate it via EvalHarness, record the run."""
        if version is None:
            version = self.latest_version(name)
        if version is None:
            return {"error": f"dataset '{name}' has no versions"}
        raw = self.load(name, version)
        cases = [
            EvalCase(
                name=c.get("name", f"case-{i}"),
                prompt=c.get("prompt", ""),
                expect_contains=c.get("expect_contains"),
                metadata=c.get("metadata", {}),
            )
            for i, c in enumerate(raw)
        ]
        result = await EvalHarness(runner).run(cases)
        run_id = self.record_run(name, version, result)
        return {
            "run_id": run_id,
            "version": version,
            "score": result["score"],
            "passed": result["passed"],
            "total": result["total"],
            "results": result["results"],
        }
