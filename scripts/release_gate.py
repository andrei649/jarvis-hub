#!/usr/bin/env python3
"""Answer whether a release candidate is mechanically ready (H23.25)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3

# Local gate executes fixed pytest/Python/git argv and never invokes a shell.
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT_GUARD_TESTS = [
    "tests/test_route_parity_guard.py",
    "tests/test_openapi_parity_guard.py",
    "tests/test_route_auth_matrix.py",
    "tests/test_action_auth_matrix.py",
    "tests/test_capability_readiness_matrix.py",
    "tests/test_h2311_operability.py",
    "tests/test_lifespan_smoke.py",
]
DOC_LINK_FILES = [
    "README.md",
    "MOONSHOT.md",
    "NERVA_VISION.md",
    "BACKLOG.md",
    "GO_LIVE_PLAN.md",
    "STATUS.md",
]
RELEASE_TOOLING = [
    "scripts/soak_report.py",
    "scripts/release_gate.py",
    "scripts/status_sync.py",
    "scripts/export_partner_feedback.py",
    "scripts/park_guard.py",
    "project-status.json",
]
_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
_LANE_ROW_RE = re.compile(r"^\|\s*(A\d)\s*\|(.*)\|\s*(.*?)\s*\|\s*$")
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
# H23.4: live-model eval evidence lanes (companion_eval.live_dataset_name).
LIVE_EVAL_PREFIX = "companion_v1-live"
LIVE_EVAL_STALE_DAYS = 30.0


def _result(tier: str, name: str, status: str, detail: str) -> dict:
    return {"tier": tier, "name": name, "status": status, "detail": detail}


def check_code_complete() -> dict:
    missing = [name for name in RELEASE_TOOLING if not (REPO / name).exists()]
    if missing:
        return _result("code", "release-tooling", FAIL, f"missing: {', '.join(missing)}")
    return _result(
        "code", "release-tooling", PASS, f"{len(RELEASE_TOOLING)} required artifacts present"
    )


def check_suite(*, skip: bool, runner=None) -> dict:
    runner = runner or (
        lambda args: (
            subprocess.run(  # noqa: S603  # nosec B603
                [sys.executable, "-m", "pytest", "-q", *args], cwd=str(REPO)
            ).returncode
        )
    )
    if skip:
        code = runner(SNAPSHOT_GUARD_TESTS)
        if code == 0:
            return _result(
                "machine",
                "snapshot-guards",
                WARN,
                "full suite skipped; route/OpenAPI/auth/action-auth guards green",
            )
        return _result("machine", "snapshot-guards", FAIL, f"snapshot guards failed ({code})")
    code = runner([])
    if code == 0:
        return _result("machine", "offline-suite", PASS, "pytest green")
    return _result("machine", "offline-suite", FAIL, f"pytest exit {code}")


def check_status_sync(*, runner=None) -> dict:
    """Run the cheap generated-projection gate without recursively collecting pytest."""
    script = str(REPO / "scripts" / "status_sync.py")
    runner = runner or (
        lambda args: (
            subprocess.run(  # noqa: S603  # nosec B603
                [sys.executable, *args], cwd=str(REPO)
            ).returncode
        )
    )
    code = runner([script, "--check", "--reuse-test-counts"])
    if code == 0:
        return _result(
            "machine",
            "status-sync",
            PASS,
            "all generated artifacts in sync (tracked test counts)",
        )
    return _result(
        "machine",
        "status-sync",
        FAIL,
        f"fast status check failed ({code}); fix: python scripts/status_sync.py "
        "--reuse-test-counts",
    )


def check_companion_gate(*, runner=None) -> dict:
    """Run the deterministic companion eval gate (H23.4) against an ephemeral store.

    The ephemeral store keeps the release gate read-only for the repo: the run
    exercises rubric/golden drift and the gate's own machinery without touching
    (or reading) any persistent baseline.
    """
    runner = runner or (
        lambda args: (
            subprocess.run(  # noqa: S603  # nosec B603
                [sys.executable, *args], cwd=str(REPO)
            ).returncode
        )
    )
    with tempfile.TemporaryDirectory(prefix="release-gate-eval-") as tmp:
        code = runner(
            [
                "-m",
                "agents.core.observability.companion_eval",
                "--ci-gate",
                "--store-root",
                str(Path(tmp) / "eval"),
            ]
        )
    if code == 0:
        return _result("machine", "companion-eval", PASS, "golden drift gate green")
    return _result("machine", "companion-eval", FAIL, f"companion eval gate failed ({code})")


def _eval_store_root() -> Path:
    """Mirror agents.core.paths.data_root() resolution without importing agents."""
    explicit = os.environ.get("JARVIS_EVAL_STORE", "").strip()
    if explicit:
        return Path(explicit)
    for env in ("JARVIS_HOME", "JARVIS_MEMORY_DIR"):
        base = os.environ.get(env, "").strip()
        if base:
            return Path(base) / "eval"
    return REPO / "memory_logs" / "eval"


def check_live_eval_evidence(*, store_root: Path | None = None, now: float | None = None) -> dict:
    """Owner row: has the H23.4 live fidelity lane actually run on this box?

    Reads the recorded live-lane runs straight from the eval store (stdlib
    only); a recorded run is evidence the owner exercised a real model against
    the golden suite. Never auto-passes: no runs → FAIL with the exact command.
    """
    root = Path(store_root) if store_root is not None else _eval_store_root()
    latest: dict | None = None
    lane = ""
    datasets_dir = root / "datasets"
    if datasets_dir.is_dir():
        for lane_dir in sorted(datasets_dir.iterdir()):
            if not lane_dir.is_dir() or not lane_dir.name.startswith(LIVE_EVAL_PREFIX):
                continue
            runs_file = lane_dir / "runs.jsonl"
            if not runs_file.is_file():
                continue
            for line in runs_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    run = json.loads(line)
                except ValueError:
                    continue
                if latest is None or float(run.get("ts", 0)) > float(latest.get("ts", 0)):
                    latest, lane = run, lane_dir.name
    if latest is None:
        return _result(
            "owner",
            "live-eval-evidence",
            FAIL,
            "no live-model eval recorded — run `python -m "
            "agents.core.observability.companion_eval --live-gate` on the owner box (H23.4)",
        )
    age_days = (float(now if now is not None else time.time()) - float(latest.get("ts", 0))) / 86400
    detail = f"lane {lane}: score {latest.get('score')} · {age_days:.1f}d ago"
    if age_days > LIVE_EVAL_STALE_DAYS:
        return _result("owner", "live-eval-evidence", WARN, detail + " (stale — re-run)")
    return _result("owner", "live-eval-evidence", PASS, detail)


def check_doc_links(files: list[str] | None = None) -> dict:
    broken = []
    for name in files or DOC_LINK_FILES:
        doc = REPO / name
        if not doc.exists():
            broken.append(f"{name} (missing)")
            continue
        for target in _LINK_RE.findall(doc.read_text(encoding="utf-8")):
            if not (doc.parent / target).exists():
                broken.append(f"{name} → {target}")
    if broken:
        return _result("machine", "doc-links", FAIL, "; ".join(broken[:8]))
    return _result("machine", "doc-links", PASS, "canonical relative links resolve")


def read_version() -> str:
    text = (REPO / "agents" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text)
    return match.group(1) if match else ""


def check_version_tag(*, tag_reader=None) -> dict:
    version = read_version()
    if not version:
        return _result("machine", "version-tag", FAIL, "agents.__version__ not found")
    if tag_reader is None:

        def tag_reader() -> str:
            git = shutil.which("git")
            if not git:
                return ""
            proc = subprocess.run(  # noqa: S603  # nosec B603
                [git, "describe", "--tags", "--abbrev=0"],
                cwd=str(REPO),
                capture_output=True,
                text=True,
            )
            return proc.stdout.strip() if proc.returncode == 0 else ""

    tag = tag_reader()
    if not tag:
        return _result("machine", "version-tag", WARN, f"__version__={version}; no git tag")
    if tag.lstrip("v") == version:
        return _result("machine", "version-tag", PASS, f"tag {tag} matches __version__")
    return _result("machine", "version-tag", WARN, f"latest tag {tag} != __version__ {version}")


def check_park_guard() -> dict:
    # The CI enforcement workflow was removed 2026-08-29 (owner de-gated PR
    # merges); the guard script remains available for manual/release checks.
    expected = (REPO / "scripts" / "park_guard.py",)
    if all(path.exists() for path in expected):
        return _result("machine", "park-guard", PASS, "guard script present (manual)")
    missing = [str(path.relative_to(REPO)) for path in expected if not path.exists()]
    return _result("machine", "park-guard", FAIL, f"missing: {', '.join(missing)} (H23.28)")


def lane_a_status(backlog_text: str) -> dict[str, str]:
    rows = {}
    for line in backlog_text.splitlines():
        match = _LANE_ROW_RE.match(line)
        if match:
            rows.setdefault(match.group(1), match.group(3))
    return rows


def _owner_row(
    rows: dict[str, str], key: str, name: str, missing_detail: str, tier: str = "owner"
) -> dict:
    if "✅" in rows.get(key, ""):
        return _result(tier, name, PASS, f"recorded in BACKLOG Lane A {key} (owner-asserted)")
    return _result(tier, name, FAIL, missing_detail)


def check_owner_and_market(
    *,
    backlog_text: str | None = None,
    feedback_db: Path | None = None,
    soak_reports: list[Path] | None = None,
) -> list[dict]:
    text = backlog_text or (REPO / "BACKLOG.md").read_text(encoding="utf-8")
    rows = lane_a_status(text)
    results = [
        _owner_row(
            rows,
            "A1",
            "b0-manual-signoff",
            "manual B0 governed-autonomy run not recorded (Lane A A1)",
        )
    ]
    if soak_reports is None:
        soak_reports = sorted((REPO / "docs" / "research").glob("*soak-report*.md"))
    soak = _owner_row(rows, "A2", "72h-soak", "72h soak not recorded (Lane A A2)")
    if soak["status"] == PASS and not soak_reports:
        soak = _result("owner", "72h-soak", WARN, "A2 ticked but evidence file is absent")
    elif soak["status"] == FAIL and soak_reports:
        soak["detail"] += f" (evidence exists: {soak_reports[-1].name})"
    results.append(soak)
    results.append(
        _owner_row(rows, "A7", "design-partners", "no design partner recorded", tier="market")
    )

    db = feedback_db or (REPO / "agents" / "data" / "feedback.db")
    if not db.exists():
        results.append(_result("market", "partner-feedback", FAIL, "no feedback recorded"))
    else:
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                count = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            results.append(
                _result(
                    "market",
                    "partner-feedback",
                    PASS if count else FAIL,
                    f"{count} feedback record(s) in the local store",
                )
            )
        except sqlite3.Error as exc:
            results.append(
                _result("market", "partner-feedback", WARN, f"feedback DB unreadable: {exc}")
            )
    return results


def run_gate(
    *,
    skip_tests: bool,
    suite_runner=None,
    tag_reader=None,
    backlog_text: str | None = None,
    feedback_db: Path | None = None,
    soak_reports: list[Path] | None = None,
) -> list[dict]:
    results = [
        check_code_complete(),
        check_suite(skip=skip_tests, runner=suite_runner),
        check_companion_gate(),
        check_status_sync(),
        check_doc_links(),
        check_version_tag(tag_reader=tag_reader),
        check_park_guard(),
    ]
    results.append(check_live_eval_evidence())
    results.extend(
        check_owner_and_market(
            backlog_text=backlog_text, feedback_db=feedback_db, soak_reports=soak_reports
        )
    )
    return results


def render(results: list[dict]) -> str:
    width = max(len(result["name"]) for result in results)
    lines = []
    for tier in ("code", "machine", "owner", "market"):
        rows = [result for result in results if result["tier"] == tier]
        if not rows:
            continue
        label = "code-complete" if tier == "code" else f"{tier}-verified"
        lines.append(f"-- {label} " + "-" * (58 - len(label)))
        for result in rows:
            lines.append(f"{result['status']:<5} {result['name']:<{width}}  {result['detail']}")
    fails = sum(1 for result in results if result["status"] == FAIL)
    warns = sum(1 for result in results if result["status"] == WARN)
    verdict = "READY (machine-side)" if not fails else "NOT READY"
    lines.extend(["", f"{verdict} — {fails} FAIL, {warns} WARN."])
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    results = run_gate(skip_tests=args.skip_tests)
    print(json.dumps(results, ensure_ascii=False, indent=2) if args.json else render(results))
    return 1 if any(result["status"] == FAIL for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
