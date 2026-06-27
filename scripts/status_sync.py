#!/usr/bin/env python3
"""status_sync.py — single source for the volatile counts in STATUS.md (CDX-5).

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

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "STATUS.md"
ROUTE_SNAPSHOT = REPO / "tests" / "_snapshots" / "route_surface.json"

# The two header tokens, e.g. "Tests:** ~3,011 passed" and "HTTP routes:** 327".
_TESTS_RE = re.compile(r"(Tests:\*\* ~)([\d,]+)( passed)")
_ROUTES_RE = re.compile(r"(HTTP routes:\*\* )(\d+)")


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
    out = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:xdist", "-o", "addopts="],
        cwd=str(repo), capture_output=True, text=True,
    ).stdout
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    if m:
        return int(m.group(1))
    # Fallback: count the "path::test" item lines pytest prints.
    return sum(1 for ln in out.splitlines() if "::" in ln)


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
    check = "--check" in argv
    routes = count_routes()
    tests = count_tests()
    derived = {"tests": tests, "routes": routes}
    # Pin UTF-8 (STATUS.md has →/✅/emoji) — the platform default is cp1252 on Windows
    # and would raise UnicodeDecodeError; newline="\n" on write keeps the repo's LF.
    text = STATUS.read_text(encoding="utf-8")
    cur = current_counts(text)

    if check:
        drift = {k: {"status": cur[k], "actual": derived[k]} for k in derived if cur[k] != derived[k]}
        if drift:
            print("STATUS.md out of sync:", json.dumps(drift))
            print("Fix with: python scripts/status_sync.py")
            return 1
        print("STATUS.md in sync:", json.dumps(derived))
        return 0

    new = apply_to_status(text, tests=tests, routes=routes)
    if new != text:
        STATUS.write_text(new, encoding="utf-8", newline="\n")
        print(f"STATUS.md updated → tests={_fmt(tests)} routes={routes} (was {cur})")
    else:
        print("STATUS.md already in sync:", json.dumps(derived))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
