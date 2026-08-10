#!/usr/bin/env python3
"""Generate project status and synchronize volatile documentation (CDX-5/H23.26).

The backend, frontend, mobile, and HTTP-route counts in the STATUS.md header get
derived here from their authoritative sources instead of being hand-bumped (and
silently going stale). Run it to either *check* STATUS.md against the live counts
or *rewrite* them in place:

    python scripts/status_sync.py            # --write (default): update STATUS.md
    python scripts/status_sync.py --check     # exit 1 if STATUS.md is out of sync

Sources (reused, not duplicated):
  * routes → ``tests/_snapshots/route_surface.json`` — the route-parity guard's
    canonical, de-duplicated METHOD+PATH surface, already kept honest by CI. Reading
    the snapshot avoids importing the whole app just to count routes.
  * tests  → ``pytest --collect-only -q`` — the exact collected-test count when
    explicitly refreshing counts; ``project-status.json`` is the tracked count source
    for the fast generated-artifact gate.

There are deliberately two policies:

* ``--check --reuse-test-counts`` is the cheap, blocking generated-artifact gate. It
  recomputes version/routes/agents/backlog projections but reuses all three tracked
  test counts, so it is safe to invoke from pytest and catches BACKLOG-only drift
  without recursively collecting the full suite.
* ``--check`` (or the default write command) performs the slower live test-count
  refresh. The header carries a ``~`` because count freshness itself is informative,
  not a reason to nest a second full test run inside the release-gate test.

``--check`` deliberately ignores the ``latest_ci_commit`` stamp (it adopts whatever
the committed files carry): the stamp is cosmetic provenance and inherently
self-referential — a merge advances main's tip but leaves the stamp pointing at the
pre-merge base, so gating on it fails every subsequent PR until a manual restamp.
Counts/routes/agents/gates are still checked against reality; ``--write`` still
records the live stamp.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil

# Local CLI orchestrates fixed pytest/npm/git argv and never invokes a shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "STATUS.md"
ROUTE_SNAPSHOT = REPO / "tests" / "_snapshots" / "route_surface.json"
PROJECT_STATUS = REPO / "project-status.json"
REGISTRY = REPO / "agents" / "_system" / "agents.yaml"
BACKLOG = REPO / "BACKLOG.md"
GENERATED_DOCS = {
    REPO / "README.md": ("badges", "run", "readme-status"),
    REPO / "NERVA.md": ("jarvis-stats",),
    REPO / "GO_LIVE_PLAN.md": ("go-live-header",),
}

# The header tokens, e.g. "Tests:** ~3,011 collected" and "HTTP routes:** 327".
# Accept the historical ``passed`` wording on input so the generator migrates old docs.
_TESTS_RE = re.compile(r"(Tests:\*\* ~)([\d,]+)(?: passed| collected)")
_FRONTEND_TESTS_RE = re.compile(r"(frontend \*\*)([\d,]+)( vitest\*\*)")
_MOBILE_TESTS_RE = re.compile(r"(mobile \*\*)([\d,]+)( jest\*\*)")
_ROUTES_RE = re.compile(r"(HTTP routes:\*\* )(\d+)")
_LANE_ROW_RE = re.compile(r"^\|\s*(A\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_VERSION_RE = re.compile(r"__version__\s*=\s*[\"']([^\"']+)[\"']")
FAST_FIX_COMMAND = "python scripts/status_sync.py --reuse-test-counts"


def count_routes() -> int:
    """Number of distinct METHOD+PATH routes, from the parity snapshot."""
    return len(json.loads(ROUTE_SNAPSHOT.read_text(encoding="utf-8")))


def count_tests(repo: Path = REPO) -> int:
    """Collected-test count via ``pytest --collect-only``.

    ``-o addopts=""`` clears the repo's ini ``addopts`` (which sets ``-q``; a second
    ``-q`` would suppress the "N tests collected" summary), and ``-p no:xdist`` keeps
    collection on the master process so the count is printed once. Heavy (imports
    every test module) — call only from the CLI paths, never from a unit test (it
    would recurse into a full collection).
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "refusing nested pytest collection; use --reuse-test-counts inside a pytest run"
        )
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:xdist",
            "-o",
            "addopts=",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return parse_pytest_count(proc.stdout + "\n" + proc.stderr, proc.returncode)


def parse_pytest_count(output: str, returncode: int) -> int:
    """Parse collection only when pytest itself succeeded; never mask import errors."""
    if returncode != 0:
        raise RuntimeError(f"pytest collection failed (exit {returncode})")
    match = re.search(r"(\d+)\s+tests?\s+collected", output)
    if match:
        return int(match.group(1))
    items = sum(1 for line in output.splitlines() if "::" in line)
    if items:
        return items
    raise RuntimeError("pytest collection produced no count")


def parse_json_test_count(output: str) -> int:
    """Read numTotalTests regardless of Vitest/Jest top-level key order."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", output):
        try:
            payload, _ = decoder.raw_decode(output[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "numTotalTests" in payload:
            return int(payload["numTotalTests"])
    raise ValueError("JSON test result with numTotalTests not found")


def reported_test_count_result(
    surface: str, output: str, *, existing: dict | None = None
) -> dict[str, object]:
    """Compare an already-produced JS reporter result with tracked truth."""
    if surface not in {"frontend", "mobile"}:
        raise ValueError(f"unsupported JS test surface: {surface}")
    if existing is None:
        try:
            existing = json.loads(PROJECT_STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("tracked project status is missing or invalid") from exc
    tests = existing.get("tests", {}) if isinstance(existing, dict) else {}
    expected = tests.get(surface)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise RuntimeError(f"tracked project status has no reusable {surface} count")
    try:
        actual = parse_json_test_count(output)
    except ValueError as exc:
        raise RuntimeError(f"test-count JSON missing for {surface}") from exc
    return {
        "status": "in_sync" if actual == expected else "out_of_sync",
        "surface": surface,
        "expected": expected,
        "actual": actual,
    }


def _json_test_count(package_dir: Path, extra_args: list[str]) -> int:
    """Run a JS test suite with its JSON reporter and return the collected count."""
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [npm, "test", "--", *extra_args],
        cwd=str(package_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = proc.stdout + "\n" + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"test-count command failed in {package_dir} (exit {proc.returncode})")
    try:
        return parse_json_test_count(output)
    except ValueError as exc:
        raise RuntimeError(f"test-count JSON missing in {package_dir}") from exc


def count_frontend_tests(repo: Path = REPO) -> int:
    return _json_test_count(repo / "frontend", ["--reporter=json"])


def count_mobile_tests(repo: Path = REPO) -> int:
    return _json_test_count(repo / "mobile", ["--runInBand", "--json"])


def js_test_counts(*, reuse: bool, existing: dict | None = None) -> tuple[int, int]:
    """Run JS suites, or explicitly reuse their tracked counts in Python-only CI jobs."""
    if not reuse:
        return count_frontend_tests(), count_mobile_tests()
    if existing is None:
        try:
            existing = json.loads(PROJECT_STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    tests = existing.get("tests", {}) if isinstance(existing, dict) else {}
    frontend, mobile = tests.get("frontend"), tests.get("mobile")
    if not isinstance(frontend, int) or not isinstance(mobile, int):
        raise RuntimeError("tracked project status has no reusable frontend/mobile counts")
    return frontend, mobile


def tracked_test_counts(existing: dict | None = None) -> tuple[int, int, int]:
    """Return backend/frontend/mobile counts from the tracked status artifact.

    This is intentionally a consistency source, not a claim that the counts were
    freshly collected. A live refresh remains available through the default CLI.
    """
    if existing is None:
        try:
            existing = json.loads(PROJECT_STATUS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("tracked project status is missing or invalid") from exc
    tests = existing.get("tests", {}) if isinstance(existing, dict) else {}
    names = ("backend", "frontend", "mobile")
    values = tuple(tests.get(name) for name in names)
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        raise RuntimeError("tracked project status has no reusable backend/frontend/mobile counts")
    return int(values[0]), int(values[1]), int(values[2])


def count_active_agents(registry: dict) -> int:
    agents = registry.get("agents", {}) if isinstance(registry, dict) else {}
    return sum(
        1
        for config in agents.values()
        if isinstance(config, dict) and str(config.get("status", "")).lower() == "active"
    )


def load_registry(path: Path = REGISTRY) -> dict:
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def horizon_rollups(backlog_text: str) -> dict[str, dict[str, int]]:
    """Aggregate machine-readable done/blocked/open counts by H-number."""
    rollups: dict[str, dict[str, int]] = {}
    for line in backlog_text.splitlines():
        match = re.match(r"^\|\s*(H(\d+)\.\d+[^|]*)\|", line)
        if not match:
            continue
        item, number = match.groups()
        horizon = f"H{number}"
        row = rollups.setdefault(horizon, {"total": 0, "done": 0, "blocked": 0, "open": 0})
        row["total"] += 1
        lowered = line.lower()
        if "✅" in item or "🟢" in line or "done" in lowered or "merged" in lowered:
            row["done"] += 1
        elif "🔴" in line or "blocked" in lowered:
            row["blocked"] += 1
        else:
            row["open"] += 1
    return dict(sorted(rollups.items(), key=lambda item: int(item[0][1:])))


def open_release_gates(backlog_text: str) -> list[dict[str, str]]:
    gates = []
    for match in _LANE_ROW_RE.finditer(backlog_text):
        gate_id, name, status = (part.strip() for part in match.groups())
        if "✅" not in status:
            gates.append({"id": gate_id, "name": name, "status": status})
    return gates


def build_project_status(
    *,
    version: str,
    backend_tests: int,
    frontend_tests: int,
    mobile_tests: int,
    routes: int,
    registry: dict,
    backlog_text: str,
    latest_ci_commit: str,
) -> dict:
    return {
        "version": version,
        "tests": {
            "backend": backend_tests,
            "frontend": frontend_tests,
            "mobile": mobile_tests,
        },
        "routes": routes,
        "active_agents": count_active_agents(registry),
        "horizons": horizon_rollups(backlog_text),
        "latest_ci_commit": latest_ci_commit,
        "open_release_gates": open_release_gates(backlog_text),
    }


def replace_generated_block(text: str, name: str, content: str, *, strict: bool = False) -> str:
    start = f"<!-- project-status:{name}:start -->"
    end = f"<!-- project-status:{name}:end -->"
    pattern = re.compile(rf"{re.escape(start)}\n.*?\n{re.escape(end)}", re.DOTALL)
    if not pattern.search(text):
        if strict:
            raise ValueError(f"generated block markers missing: {name}")
        return text
    return pattern.sub(f"{start}\n{content.rstrip()}\n{end}", text, count=1)


def generated_snippets(status: dict) -> dict[str, str]:
    tests = status["tests"]
    gates = status["open_release_gates"]
    gate_ids = ", ".join(gate["id"] for gate in gates) or "none"
    h23 = status["horizons"].get("H23", {"total": 0, "done": 0, "blocked": 0, "open": 0})
    commit = status["latest_ci_commit"][:12]
    matrix = (
        f"backend **{tests['backend']:,}** · frontend **{tests['frontend']:,}** · "
        f"mobile **{tests['mobile']:,}**"
    )
    return {
        "badges": "\n".join(
            [
                f"![Backend tests](https://img.shields.io/badge/backend_tests-{tests['backend']}-brightgreen?logo=pytest)",
                f"![Version](https://img.shields.io/badge/version-{status['version']}-orange)",
            ]
        ),
        "run": f"Generated test matrix: {matrix}. Route surface: **{status['routes']}**.",
        "readme-status": (
            f"Generated status: **v{status['version']}** · {matrix} · **{status['routes']}** routes · "
            f"**{status['active_agents']}** active agents · open release gates: **{gate_ids}** · "
            f"source commit `{commit}`. Full data: [`project-status.json`](project-status.json)."
        ),
        "jarvis-stats": "\n".join(
            [
                f"- {status['active_agents']} active agents; registry-derived",
                f"- {status['routes']} HTTP routes; parity-snapshot-derived",
                f"- Tests: {matrix}",
                f"- Version: **v{status['version']}** · source commit `{commit}`",
                f"- H23 roll-up: {h23['done']}/{h23['total']} done, {h23['blocked']} blocked, {h23['open']} open; release gates: {gate_ids}",
            ]
        ),
        "go-live-header": (
            f"> Generated project status: **v{status['version']}** · {matrix} · "
            f"**{status['routes']}** routes · **{status['active_agents']}** active agents · "
            f"open owner gates: **{gate_ids}** · commit `{commit}`."
        ),
    }


def _version() -> str:
    match = _VERSION_RE.search((REPO / "agents" / "__init__.py").read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def latest_ci_commit(*, env=None, runner=None) -> str:
    """Last verified main commit, not the self-referential commit being generated."""
    env = os.environ if env is None else env
    override = env.get("JARVIS_LATEST_CI_COMMIT", "").strip()
    if override:
        return override
    event_path = env.get("GITHUB_EVENT_PATH", "").strip()
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            base_sha = event.get("pull_request", {}).get("base", {}).get("sha", "")
            if base_sha:
                return str(base_sha)
            before_sha = str(event.get("before", "")).strip()
            if before_sha and before_sha.strip("0"):
                return before_sha
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    def run_git_argv(args: list) -> tuple[int, str]:
        if runner is not None:
            code, output = runner(args)
            return code, output.strip()
        proc = subprocess.run(  # noqa: S603  # nosec B603
            args, cwd=str(REPO), capture_output=True, text=True
        )
        return proc.returncode, proc.stdout.strip()

    def run_git(ref: str) -> tuple[int, str]:
        return run_git_argv(["git", "rev-parse", ref])

    main_code, main_sha = run_git("origin/main")
    if main_code != 0:
        return "unknown"
    head_code, head_sha = run_git("HEAD")
    if head_code == 0 and head_sha == main_sha:
        # Self-reference guard: when generating ON main itself, "origin/main"
        # would be the very commit being described, so step back one. A feature
        # branch whose HEAD merely EQUALS the main tip (freshly branched, no
        # commits yet) must NOT step back — CI compares against the PR base,
        # which is exactly origin/main. (This mismatch broke three PR runs.)
        branch_code, branch_name = run_git_argv(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch_code == 0 and branch_name in ("main", "HEAD"):
            parent_code, parent_sha = run_git("origin/main^")
            if parent_code == 0 and parent_sha:
                return parent_sha
    return main_sha


def collect_project_status(
    *, reuse_js_counts: bool = False, reuse_test_counts: bool = False
) -> dict:
    if reuse_test_counts:
        backend_tests, frontend_tests, mobile_tests = tracked_test_counts()
    else:
        backend_tests = count_tests()
        frontend_tests, mobile_tests = js_test_counts(reuse=reuse_js_counts)
    return build_project_status(
        version=_version(),
        backend_tests=backend_tests,
        frontend_tests=frontend_tests,
        mobile_tests=mobile_tests,
        routes=count_routes(),
        registry=load_registry(),
        backlog_text=BACKLOG.read_text(encoding="utf-8"),
        latest_ci_commit=latest_ci_commit(),
    )


def _expected_docs(status: dict) -> dict[Path, str]:
    snippets = generated_snippets(status)
    expected = {}
    for path, blocks in GENERATED_DOCS.items():
        text = path.read_text(encoding="utf-8")
        for block in blocks:
            text = replace_generated_block(text, block, snippets[block], strict=True)
        expected[path] = text
    expected[STATUS] = apply_to_status(
        STATUS.read_text(encoding="utf-8"),
        tests=status["tests"]["backend"],
        frontend=status["tests"]["frontend"],
        mobile=status["tests"]["mobile"],
        routes=status["routes"],
    )
    return expected


def format_update_message(status: dict) -> str:
    """Keep CLI output printable on Windows consoles still using cp1252."""
    return (
        f"Project status updated -> tests={status['tests']} routes={status['routes']} "
        f"agents={status['active_agents']}"
    )


def _fmt(n: int) -> str:
    return f"{n:,}"


def apply_to_status(
    text: str,
    *,
    tests: int | None = None,
    frontend: int | None = None,
    mobile: int | None = None,
    routes: int | None = None,
) -> str:
    """Return ``text`` with the test/route tokens rewritten. Only the matched
    digits change — surrounding version numbers, route-counts-in-prose, etc. are
    left untouched (single, anchored substitution per token)."""
    if tests is not None:
        text = _TESTS_RE.sub(lambda m: f"{m.group(1)}{_fmt(tests)} collected", text, count=1)
    if frontend is not None:
        text = _FRONTEND_TESTS_RE.sub(
            lambda m: f"{m.group(1)}{_fmt(frontend)}{m.group(3)}", text, count=1
        )
    if mobile is not None:
        text = _MOBILE_TESTS_RE.sub(
            lambda m: f"{m.group(1)}{_fmt(mobile)}{m.group(3)}", text, count=1
        )
    if routes is not None:
        text = _ROUTES_RE.sub(lambda m: f"{m.group(1)}{routes}", text, count=1)
    return text


def current_counts(text: str) -> dict:
    """The counts STATUS.md currently asserts (None if the token is missing)."""
    t = _TESTS_RE.search(text)
    r = _ROUTES_RE.search(text)
    return {
        "tests": int(t.group(2).replace(",", "")) if t else None,
        "routes": int(r.group(2)) if r else None,
    }


def _committed_commit(path: Path | None = None) -> str:
    """The commit stamp the committed project-status.json currently carries, or
    ``""`` if the file is absent/unreadable/lacks the field. Used by ``--check``
    to exclude the volatile stamp from drift detection (see ``_status_for_check``).

    ``path`` defaults to the module-level ``PROJECT_STATUS`` resolved *at call
    time* (not bound as a default arg) so tests can monkeypatch it."""
    target = PROJECT_STATUS if path is None else path
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("latest_ci_commit", "")) if isinstance(data, dict) else ""


def _status_for_check(status: dict) -> dict:
    """The ``--check`` view of *status*: adopt the commit stamp the committed
    files already carry so the gate ignores it.

    The commit stamp is cosmetic provenance and inherently self-referential —
    merging a PR advances main's tip but leaves the stamp inside it pointing at
    the pre-merge base, so the next PR's base never matches and the gate fails
    until a manual restamp (it bit several PRs in a row). Every meaningful field
    (counts, routes, agents, gates) is still checked against reality; only the
    volatile hash is neutralized. ``--write`` is unaffected and records the live
    stamp. No-op when the committed file is absent/unreadable."""
    committed = _committed_commit()
    if committed:
        return {**status, "latest_ci_commit": committed}
    return status


def changed_status_keys(current: object, expected: object, prefix: str = "") -> list[str]:
    """Return stable dotted paths for semantic JSON differences."""
    if isinstance(current, dict) and isinstance(expected, dict):
        changed = []
        for key in sorted(set(current) | set(expected)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in current or key not in expected:
                changed.append(path)
            else:
                changed.extend(changed_status_keys(current[key], expected[key], path))
        return changed
    if current != expected:
        return [prefix or "$root"]
    return []


def generated_drift(status: dict, expected_docs: dict[Path, str]) -> dict[str, list[str]]:
    """Describe generated JSON keys and files that differ without mutating them."""
    try:
        current_status = json.loads(PROJECT_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current_status = None
    keys = changed_status_keys(current_status, status)
    files = []
    expected_json = json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        current_json = PROJECT_STATUS.read_text(encoding="utf-8")
    except OSError:
        current_json = ""
    if current_json != expected_json:
        files.append(str(PROJECT_STATUS.relative_to(REPO)))
    for path, expected in expected_docs.items():
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current != expected:
            files.append(str(path.relative_to(REPO)))
    return {"changed_keys": keys, "files": files}


def fix_command(*, reuse_js_counts: bool, reuse_test_counts: bool) -> str:
    if reuse_test_counts:
        return FAST_FIX_COMMAND
    if reuse_js_counts:
        return "python scripts/status_sync.py --reuse-js-counts"
    return "python scripts/status_sync.py"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--reuse-js-counts",
        action="store_true",
        help="reuse tracked frontend/mobile counts (for Python-only CI jobs)",
    )
    parser.add_argument(
        "--reuse-test-counts",
        action="store_true",
        help="reuse all tracked test counts for the fast generated-artifact gate",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    parser.add_argument(
        "--verify-test-count",
        choices=("frontend", "mobile"),
        help="verify an existing Vitest/Jest JSON report against tracked status",
    )
    parser.add_argument("--test-result", type=Path, help="Vitest/Jest JSON report path")
    args = parser.parse_args(argv)
    if args.verify_test_count:
        if args.test_result is None:
            parser.error("--verify-test-count requires --test-result")
        try:
            result = reported_test_count_result(
                args.verify_test_count,
                args.test_result.read_text(encoding="utf-8", errors="replace"),
            )
        except (OSError, RuntimeError) as exc:
            result = {"status": "error", "error": str(exc)}
            print(
                json.dumps(result, sort_keys=True)
                if args.json
                else f"Test-count check failed: {exc}"
            )
            return 2
        print(
            json.dumps(result, sort_keys=True)
            if args.json
            else (
                f"{result['surface']} test count: {result['actual']} "
                f"(tracked {result['expected']})"
            )
        )
        return 0 if result["status"] == "in_sync" else 1
    try:
        status = collect_project_status(
            reuse_js_counts=args.reuse_js_counts,
            reuse_test_counts=args.reuse_test_counts,
        )
    except RuntimeError as exc:
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, sort_keys=True) if args.json else f"Status sync failed: {exc}")
        return 2
    if args.check:
        # Exclude the volatile, self-referential commit stamp from the gate.
        status = _status_for_check(status)
    try:
        expected_docs = _expected_docs(status)
    except ValueError as exc:
        payload = {"status": "error", "error": str(exc)}
        print(
            json.dumps(payload, sort_keys=True)
            if args.json
            else f"Generated project status cannot be synchronized: {exc}"
        )
        return 1
    drift = generated_drift(status, expected_docs)
    command = fix_command(
        reuse_js_counts=args.reuse_js_counts,
        reuse_test_counts=args.reuse_test_counts,
    )
    if args.check:
        if drift["files"]:
            payload = {
                "status": "out_of_sync",
                **drift,
                "fix_command": command,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            else:
                print("Generated project status out of sync:", ", ".join(drift["files"]))
                print("Changed status keys:", ", ".join(drift["changed_keys"]) or "none")
                print(f"Fix with: {command}")
            return 1
        payload = {
            "status": "in_sync",
            **drift,
            "fix_command": None,
            "tests": status["tests"],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print("Generated project status in sync:", json.dumps(status["tests"]))
        return 0

    expected_json = json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    PROJECT_STATUS.write_text(expected_json, encoding="utf-8", newline="\n")
    for path, expected in expected_docs.items():
        path.write_text(expected, encoding="utf-8", newline="\n")
    if args.json:
        print(
            json.dumps(
                {"status": "updated", **drift, "fix_command": None, "tests": status["tests"]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print(format_update_message(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
