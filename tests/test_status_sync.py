"""Tests for scripts/status_sync.py (CDX-5).

Only the pure / fast parts are exercised — the route count (from the snapshot),
the STATUS.md rewrite, and the parse. `count_tests()` is deliberately NOT called:
it shells out to a full `pytest --collect-only`, which would recurse into this very
collection. The script is loaded by path (scripts/ is not a package), mirroring
tests/test_release_build.py.
"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("status_sync", REPO / "scripts" / "status_sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status_sync = _load()


def test_count_routes_matches_snapshot():
    n = status_sync.count_routes()
    snap = json.loads((REPO / "tests" / "_snapshots" / "route_surface.json").read_text())
    assert n == len(snap)
    assert n > 300  # sanity: the app has hundreds of routes


def test_apply_to_status_rewrites_both_tokens():
    sample = "x · **Tests:** ~1,234 passed (6 skipped) · **HTTP routes:** 42 (+ feedback) y"
    out = status_sync.apply_to_status(sample, tests=9999, routes=100)
    assert "~9,999 passed" in out
    assert "HTTP routes:** 100 " in out
    assert "~1,234" not in out and "routes:** 42" not in out


def test_apply_is_anchored_leaves_other_numbers_untouched():
    # The version string and the "45 routers" prose must survive the rewrite.
    sample = "v0.11.0 · **Tests:** ~10 passed · **HTTP routes:** 5 — 45 per-domain routers"
    out = status_sync.apply_to_status(sample, tests=20, routes=6)
    assert "v0.11.0" in out and "45 per-domain routers" in out
    assert "~20 passed" in out and "HTTP routes:** 6 " in out


def test_apply_each_token_independently():
    sample = "**Tests:** ~10 passed · **HTTP routes:** 5"
    assert "~10 passed" in status_sync.apply_to_status(sample, routes=6)        # tests untouched
    assert "HTTP routes:** 5" in status_sync.apply_to_status(sample, tests=20)   # routes untouched


def test_current_counts_parses_status():
    sample = "**Tests:** ~3,011 passed (6 skipped) ... **HTTP routes:** 327 (+ x)"
    c = status_sync.current_counts(sample)
    assert c["tests"] == 3011 and c["routes"] == 327


def test_current_counts_missing_tokens_are_none():
    assert status_sync.current_counts("no tokens here") == {"tests": None, "routes": None}


def test_live_status_md_tokens_are_parseable():
    # The real STATUS.md must carry both tokens so the tool can keep them in sync.
    c = status_sync.current_counts((REPO / "STATUS.md").read_text())
    assert c["tests"] is not None and c["routes"] is not None
