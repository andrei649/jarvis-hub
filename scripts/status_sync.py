#!/usr/bin/env python3
"""Generate project status and synchronize volatile documentation (CDX-5/H23.26).

The two numbers in the STATUS.md header that drift on almost every PR — the test
count and the HTTP-route count — get derived here from their authoritative sources
instead of being hand-bumped (and silently going stale). Run it to either *check*
STATUS.md against the live counts or *rewrite* them in place:

    python scripts/status_sync.py            # --write (default): update STATUS.md
    python scripts/status_sync.py --check     # exit 1 if STATUS.md is out of sync

Sources (reused, not duplicated):
  * routes → ``tests/_snapshots/route_surface.json`` — the route-parity guard's
    canonical, de-duplicated METHOD+PATH surface, already kept honest by CI. Reading
    the snapshot avoids importing the whole app just to count routes.
  * tests  → ``pytest --collect-only -q`` — the exact collected-test count.

Intentionally NOT wired as a blocking CI gate: the header count carries a ``~`` to
signal it's approximate, so a one-test drift shouldn't fail a build. ``--check`` is
here for whoever wants a periodic nudge, not a merge wall.
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
    REPO / "JARVIS.md": ("jarvis-stats",),
    REPO / "GO_LIVE_PLAN.md": ("go-live-header",),
}

# The two header tokens, e.g. "Tests:** ~3,011 passed" and "HTTP routes:** 327".
_TESTS_RE = re.compile(r"(Tests:\*\* ~)([\d,]+)( passed)")
_ROUTES_RE = re.compile(r"(HTTP routes:\*\* )(\d+)")
_HORIZON_ROW_RE = re.compile(r"^\|\s*(H(\d+)\.\d+[^|]*)\|", re.MULTILINE)
_LANE_ROW_RE = re.compile(r"^\|\s*(A\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_VERSION_RE = re.compile(r"__version__\s*=\s*[\"']([^\"']+)[\"']")


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
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    args = ["git", "rev-parse", "origin/main"]
    if runner is not None:
        code, output = runner(args)
        return output.strip() if code == 0 else "unknown"
    proc = subprocess.run(  # noqa: S603  # nosec B603
        args, cwd=str(REPO), capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def collect_project_status() -> dict:
    return build_project_status(
        version=_version(),
        backend_tests=count_tests(),
        frontend_tests=count_frontend_tests(),
        mobile_tests=count_mobile_tests(),
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


def apply_to_status(text: str, *, tests: int | None = None, routes: int | None = None) -> str:
    """Return ``text`` with the test/route tokens rewritten. Only the matched
    digits change — surrounding version numbers, route-counts-in-prose, etc. are
    left untouched (single, anchored substitution per token)."""
    if tests is not None:
        text = _TESTS_RE.sub(lambda m: f"{m.group(1)}{_fmt(tests)}{m.group(3)}", text, count=1)
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    status = collect_project_status()
    expected_json = json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        expected_docs = _expected_docs(status)
    except ValueError as exc:
        print(f"Generated project status cannot be synchronized: {exc}")
        return 1
    if args.check:
        drift = []
        if (
            not PROJECT_STATUS.exists()
            or PROJECT_STATUS.read_text(encoding="utf-8") != expected_json
        ):
            drift.append(str(PROJECT_STATUS.relative_to(REPO)))
        drift.extend(
            str(path.relative_to(REPO))
            for path, expected in expected_docs.items()
            if path.read_text(encoding="utf-8") != expected
        )
        if drift:
            print("Generated project status out of sync:", ", ".join(drift))
            print("Fix with: python scripts/status_sync.py")
            return 1
        print("Generated project status in sync:", json.dumps(status["tests"]))
        return 0

    PROJECT_STATUS.write_text(expected_json, encoding="utf-8", newline="\n")
    for path, expected in expected_docs.items():
        path.write_text(expected, encoding="utf-8", newline="\n")
    print(format_update_message(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
