"""Tests for scripts/status_sync.py (CDX-5).

Only the pure / fast parts are exercised — the route count (from the snapshot),
the STATUS.md rewrite, and the parse. ``count_tests()`` refuses to start a nested
``pytest --collect-only`` while this suite is running. The script is loaded by path
(scripts/ is not a package), mirroring tests/test_release_build.py.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "status_sync", REPO / "scripts" / "status_sync.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status_sync = _load()


def test_count_routes_matches_snapshot():
    n = status_sync.count_routes()
    snap = json.loads(
        (REPO / "tests" / "_snapshots" / "route_surface.json").read_text(encoding="utf-8")
    )
    assert n == len(snap)
    assert n > 300  # sanity: the app has hundreds of routes


def test_pytest_collection_parser_fails_closed_on_collection_error():
    assert status_sync.parse_pytest_count("4225 tests collected in 1.0s", 0) == 4225
    with pytest.raises(RuntimeError):
        status_sync.parse_pytest_count("12 tests collected\nERROR broken import", 1)
    with pytest.raises(RuntimeError):
        status_sync.parse_pytest_count("collection output without a count", 0)


def test_count_tests_refuses_nested_pytest_collection(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_status_sync.py::nested")
    with pytest.raises(RuntimeError, match="refusing nested pytest collection"):
        status_sync.count_tests()


def test_apply_to_status_rewrites_both_tokens():
    sample = "x · **Tests:** ~1,234 passed (6 skipped) · **HTTP routes:** 42 (+ feedback) y"
    out = status_sync.apply_to_status(sample, tests=9999, routes=100)
    assert "~9,999 collected" in out
    assert "HTTP routes:** 100 " in out
    assert "~1,234" not in out and "routes:** 42" not in out


def test_apply_is_anchored_leaves_other_numbers_untouched():
    # The version string and the "45 routers" prose must survive the rewrite.
    sample = "v0.11.0 · **Tests:** ~10 passed · **HTTP routes:** 5 — 45 per-domain routers"
    out = status_sync.apply_to_status(sample, tests=20, routes=6)
    assert "v0.11.0" in out and "45 per-domain routers" in out
    assert "~20 collected" in out and "HTTP routes:** 6 " in out


def test_apply_each_token_independently():
    sample = (
        "**Tests:** ~10 passed + frontend **8 vitest** + mobile **3 jest** · **HTTP routes:** 5"
    )
    assert "~10 passed" in status_sync.apply_to_status(sample, routes=6)  # tests untouched
    assert "HTTP routes:** 5" in status_sync.apply_to_status(sample, tests=20)  # routes untouched
    updated = status_sync.apply_to_status(sample, frontend=9, mobile=4)
    assert "frontend **9 vitest**" in updated
    assert "mobile **4 jest**" in updated


def test_apply_to_status_preserves_honest_collection_wording():
    sample = "**Tests:** ~10 collected · **HTTP routes:** 5"
    assert "~20 collected" in status_sync.apply_to_status(sample, tests=20)


def test_current_counts_parses_status():
    sample = "**Tests:** ~3,011 passed (6 skipped) ... **HTTP routes:** 327 (+ x)"
    c = status_sync.current_counts(sample)
    assert c["tests"] == 3011 and c["routes"] == 327


def test_current_counts_missing_tokens_are_none():
    assert status_sync.current_counts("no tokens here") == {"tests": None, "routes": None}


def test_live_status_md_tokens_are_parseable():
    # The real STATUS.md must carry both tokens so the tool can keep them in sync.
    # encoding pinned: STATUS.md is UTF-8 (→/✅/emoji); Windows' default cp1252 would raise.
    c = status_sync.current_counts((REPO / "STATUS.md").read_text(encoding="utf-8"))
    assert c["tests"] is not None and c["routes"] is not None


def test_count_active_agents_reads_only_active_registry_entries():
    registry = {
        "agents": {
            "jarvis": {"status": "active"},
            "athena": {"status": "active"},
            "retired": {"status": "parked"},
        },
        "bench": {"bruce": {"status": "bench"}},
    }
    assert status_sync.count_active_agents(registry) == 2


def test_horizon_rollups_and_open_release_gates_are_structured():
    backlog = """
| H23.24 | Collector | 🟢 done | 0.20 |
| H23.25 | Gate | 🔴 blocked on owner | 1.0 |
| H24.1 ⬜ | Kernel | 3 | P0 | — |
| H24.2 ✅ | Audit | 2 | P0 | — |
| A1 | Manual | ⬜ the gate |
| A2 | Soak | ✅ report |
"""
    assert status_sync.horizon_rollups(backlog) == {
        "H23": {"total": 2, "done": 1, "delivered": 0, "blocked": 1, "open": 0},
        "H24": {"total": 2, "done": 1, "delivered": 0, "blocked": 0, "open": 1},
    }
    assert status_sync.open_release_gates(backlog) == [
        {"id": "A1", "name": "Manual", "status": "⬜ the gate"}
    ]


def test_horizon_rollups_count_delivered_rows_as_their_own_bucket():
    # D4(a): 🔨 = code delivered, runtime proof pending — neither done nor open.
    backlog = """
| H19.1.1 🔨 | **Sursă ADS-B reală** — **Livrat:** `adsb/sources.py`; **AC îndeplinit** | 5 | P1 |
| H19.1.2 🔨 | **Sursă AIS reală** | 5 | P1 |
| H19.0.1 ✅ | done row | 1 | P1 |
| H19.0.2 ⬜ | open row | 1 | P1 |
"""
    rollups = status_sync.horizon_rollups(backlog)
    assert rollups == {
        "H19": {"total": 4, "done": 1, "delivered": 2, "blocked": 0, "open": 1},
    }
    row = rollups["H19"]
    assert row["done"] + row["delivered"] + row["blocked"] + row["open"] == row["total"]
    totals = status_sync.horizon_totals(rollups)
    assert totals["delivered"] == 2
    assert totals["open_or_blocked"] == 1  # delivered rows never inflate open/blocked
    assert status_sync.horizon_summary("H19", row) == (
        "H19 — 1 done · 2 delivered (runtime proof pending) · 1 open"
    )


def test_row_state_comes_from_the_leading_marker_not_prose():
    # D4(b): a "✅" quoted inside explanatory prose must not flip an open row to done,
    # and "done"/"merged" inside prose must not either.
    backlog = """
| H40.1 ⬜ | Reading this row as "✅ done — settings applied" is what went wrong; PR merged | 1 |
| H40.2 | Name mentions done work | ⬜ **owner tail** — the dev half is ✅ done (#512) | 1 |
| H40.3 | Name | 🟡 partial — first half done | 1 |
| H40.4 | Name | 🔴 blocked on owner | 1 |
| H40.5 | Name | **✅ done** (#300) | 1 |
| H40.6 | Name | 🟢 **backend done** | 1 |
| H40.7 | Name | 3 | P1 | — |
"""
    assert status_sync.horizon_rollups(backlog) == {
        "H40": {"total": 7, "done": 2, "delivered": 0, "blocked": 1, "open": 4},
    }
    assert status_sync.leading_marker_state("  **✅ done**") == "done"
    assert status_sync.leading_marker_state("🔨 shipped") == "delivered"
    assert status_sync.leading_marker_state("prose that says ✅ later") is None
    assert status_sync.leading_marker_state("Done (2026-07-01)") == "done"
    assert status_sync.leading_marker_state("") is None
    assert status_sync.classify_row(["H1.1 ⬜", "x ✅ y"]) == "open"
    assert status_sync.classify_row(["H1.1", "name", "✅ done"]) == "done"
    assert status_sync.classify_row(["H1.1", "name", "3", "P1"]) == "open"


def test_open_release_gates_ignore_checkmarks_quoted_in_prose():
    # Lane A: only a *leading* ✅ closes a gate. A4's prose quotes the misreading
    # ("✅ done — settings applied") while its status is 🟡 partial — it is open.
    backlog = """
| A4 | GitHub settings batch | 🟡 **partial (owner)** — reading this row as "✅ done — settings applied" was the bug |
| A5 | License flip | 🟢 prep done — the flip itself is 3 owner commands |
| A7 | Partners | ✅ **done (owner, 2026-08-28)** |
| A2 | Soak | **✅ automated — gate removed** |
| A0 | Old | done (owner) |
"""
    gates = status_sync.open_release_gates(backlog)
    assert [gate["id"] for gate in gates] == ["A4", "A5"]
    assert status_sync.gate_is_closed("✅ done")
    assert status_sync.gate_is_closed("**✅** done")
    assert not status_sync.gate_is_closed("🟢 half done, prose says ✅")
    assert not status_sync.gate_is_closed("⬜ pending ✅")


def test_live_backlog_a4_reads_open_and_h19_delivered():
    # Ledger truth on the real BACKLOG (D4): A4 is an open owner item even though its
    # prose quotes "✅ done", and every 🔨 H19 row lands in the delivered bucket.
    backlog = (REPO / "BACKLOG.md").read_text(encoding="utf-8")
    gates = {gate["id"] for gate in status_sync.open_release_gates(backlog)}
    assert "A4" in gates
    rollups = status_sync.horizon_rollups(backlog)
    h19 = rollups["H19"]
    h19_rows = sum(1 for line in backlog.splitlines() if line.startswith("| H19."))
    assert h19["total"] == h19_rows
    assert h19["delivered"] == h19_rows - h19["done"] - h19["open"] - h19["blocked"]
    assert h19["delivered"] > 0
    assert sum(row["total"] for row in rollups.values()) == sum(
        row["done"] + row["delivered"] + row["blocked"] + row["open"] for row in rollups.values()
    )


def test_owner_gates_a2_and_a8_are_closed_not_blocking():
    # Owner directive 2026-08-28: the proof-track gates are removed. A8's owner-host
    # proof ran on real hardware, and A2 no longer needs a human at all — the soak
    # grades itself. Both must read as closed in Lane A, or STATUS.md and
    # project-status.json will keep reporting a gate nobody is waiting on.
    backlog = (REPO / "BACKLOG.md").read_text(encoding="utf-8")
    gates = {gate["id"]: gate for gate in status_sync.open_release_gates(backlog)}
    assert "A8" not in gates
    assert "A2" not in gates

    # The A2 automation is the thing that replaced the gate — it has to exist.
    assert (REPO / ".github" / "workflows" / "soak.yml").exists()
    soak = (REPO / "scripts" / "soak_report.py").read_text(encoding="utf-8")
    assert "def evaluate(" in soak and "--fail-on-verdict" in soak

    # The §N seams stay guarded even though the gate is gone: the chapter is still the
    # written record of what the owner-host proof covered.
    owner_tasks = (REPO / "docs" / "OWNER_TASKS.md").read_text(encoding="utf-8")
    manual = (REPO / "docs" / "MANUAL_TESTING.md").read_text(encoding="utf-8")
    assert "A8 — AI-OS v1 owner-host proof" in owner_tasks
    assert "## N. AI-OS owner-host v1 proof (A8)" in manual
    for live_seam in (
        "Chromium",
        "Windows UIA",
        "Home Assistant",
        "Frigate",
        "occupant",
        "Presence-aware",
        "≥2",
    ):
        assert live_seam in manual


def test_build_project_status_has_one_machine_readable_truth():
    status = status_sync.build_project_status(
        version="0.11.0",
        backend_tests=4200,
        frontend_tests=208,
        mobile_tests=55,
        routes=368,
        registry={"agents": {"jarvis": {"status": "active"}}},
        backlog_text="| H23.24 | Collector | ⬜ MISSING | 0.20 |\n| A1 | Manual | ⬜ |",
        latest_ci_commit="abcdef1234567890",
    )
    assert status["version"] == "0.11.0"
    assert status["tests"] == {"backend": 4200, "frontend": 208, "mobile": 55}
    assert status["routes"] == 368 and status["active_agents"] == 1
    assert status["horizons"]["H23"]["open"] == 1
    assert status["horizons"]["H23"]["delivered"] == 0
    assert status["horizon_totals"] == {
        "total": 1,
        "done": 0,
        "delivered": 0,
        "blocked": 0,
        "open": 1,
        "open_or_blocked": 1,
    }
    assert status["open_release_gates"][0]["id"] == "A1"
    assert status["latest_ci_commit"] == "abcdef1234567890"
    json.dumps(status, sort_keys=True)


def test_marker_replacement_is_bounded_and_idempotent():
    text = (
        "before\n<!-- project-status:demo:start -->\nold\n<!-- project-status:demo:end -->\nafter\n"
    )
    updated = status_sync.replace_generated_block(text, "demo", "new\nvalue")
    assert updated == (
        "before\n<!-- project-status:demo:start -->\nnew\nvalue\n"
        "<!-- project-status:demo:end -->\nafter\n"
    )
    assert status_sync.replace_generated_block(updated, "demo", "new\nvalue") == updated
    assert status_sync.replace_generated_block("no markers", "demo", "x") == "no markers"
    with pytest.raises(ValueError):
        status_sync.replace_generated_block("no markers", "demo", "x", strict=True)


def test_generated_snippets_include_all_counts_and_open_gates():
    status = {
        "version": "0.11.0",
        "tests": {"backend": 4200, "frontend": 208, "mobile": 55},
        "routes": 368,
        "active_agents": 17,
        "horizons": {
            "H19": {"total": 35, "done": 2, "delivered": 33, "blocked": 0, "open": 0},
            "H23": {"total": 28, "done": 23, "blocked": 0, "open": 5},
        },
        "latest_ci_commit": "abcdef1234567890",
        "open_release_gates": [{"id": "A1", "name": "Manual", "status": "⬜"}],
    }
    snippets = status_sync.generated_snippets(status)
    assert set(snippets) == {"badges", "run", "readme-status", "jarvis-stats", "go-live-header"}
    joined = "\n".join(snippets.values())
    for token in ("4,200", "208", "55", "368", "17", "A1", "abcdef123456"):
        assert token in joined
    # D4(a): every done/open surface shows the delivered bucket explicitly and the
    # global open-or-blocked figure excludes delivered rows (5 open, not 38).
    ledger = "25 done · 33 delivered (runtime proof pending) · 5 open or blocked of 63 horizon rows"
    for name in ("readme-status", "jarvis-stats", "go-live-header"):
        assert ledger in snippets[name], name
    assert (
        "Runtime proof pending: H19 — 2 done · 33 delivered (runtime proof pending) · 0 open"
        in snippets["jarvis-stats"]
    )
    assert (
        "H23 roll-up: 23/28 done, 0 delivered (runtime proof pending), 0 blocked, 5 open"
        in (snippets["jarvis-stats"])
    )


def test_json_test_count_parser_accepts_vitest_and_jest_key_order():
    vitest = 'npm preface\n{"numTotalTestSuites": 2, "numTotalTests": 8, "success": true}'
    jest = 'console noise\n{"numFailedTestSuites": 0, "numTotalTests": 55, "success": true}'
    junit = (
        '<?xml version="1.0"?><testsuites name="pytest tests">'
        '<testsuite failures="0" tests="6540"></testsuite></testsuites>'
    )
    assert status_sync.parse_json_test_count(vitest) == 8
    assert status_sync.parse_json_test_count(jest) == 55
    assert status_sync.parse_junit_test_count(junit) == 6540
    assert status_sync.reported_test_count_result(
        "backend", junit, existing={"tests": {"backend": 6540}}
    ) == {"status": "in_sync", "surface": "backend", "expected": 6540, "actual": 6540}
    assert status_sync.reported_test_count_result(
        "frontend", vitest, existing={"tests": {"frontend": 8}}
    ) == {"status": "in_sync", "surface": "frontend", "expected": 8, "actual": 8}
    assert status_sync.reported_test_count_result(
        "mobile", jest, existing={"tests": {"mobile": 54}}
    ) == {"status": "out_of_sync", "surface": "mobile", "expected": 54, "actual": 55}


def test_reuse_js_counts_is_explicit_and_reads_tracked_status_only():
    existing = {"tests": {"frontend": 208, "mobile": 55}}
    assert status_sync.js_test_counts(reuse=True, existing=existing) == (208, 55)
    with pytest.raises(RuntimeError):
        status_sync.js_test_counts(reuse=True, existing={})


def test_all_test_counts_can_reuse_tracked_status_without_any_test_runner():
    existing = {"tests": {"backend": 6341, "frontend": 515, "mobile": 96}}
    assert status_sync.tracked_test_counts(existing) == (6341, 515, 96)
    with pytest.raises(RuntimeError, match="backend/frontend/mobile"):
        status_sync.tracked_test_counts({"tests": {"backend": True}})


def test_collect_project_status_tracked_mode_never_calls_test_runners(monkeypatch):
    monkeypatch.setattr(status_sync, "tracked_test_counts", lambda: (10, 20, 30))
    monkeypatch.setattr(status_sync, "load_registry", lambda: {"agents": {}})
    monkeypatch.setattr(
        status_sync,
        "count_tests",
        lambda: pytest.fail("live backend collection must not run"),
    )
    monkeypatch.setattr(
        status_sync,
        "js_test_counts",
        lambda **kwargs: pytest.fail("live JS suites must not run"),
    )
    result = status_sync.collect_project_status(reuse_test_counts=True)
    assert result["tests"] == {"backend": 10, "frontend": 20, "mobile": 30}


def test_update_message_is_safe_on_default_windows_console():
    message = status_sync.format_update_message(
        {"tests": {"backend": 1, "frontend": 2, "mobile": 3}, "routes": 4, "active_agents": 5}
    )
    message.encode("cp1252")
    assert "tests=" in message and "routes=4" in message


def test_latest_ci_commit_uses_last_verified_main_not_self_referential_head():
    seen = []
    outputs = {
        ("git", "rev-parse", "origin/main"): (0, "abc123\n"),
        ("git", "rev-parse", "HEAD"): (0, "feature789\n"),
    }
    value = status_sync.latest_ci_commit(
        env={}, runner=lambda args: seen.append(args) or outputs[tuple(args)]
    )
    assert value == "abc123"
    assert seen == [
        ["git", "rev-parse", "origin/main"],
        ["git", "rev-parse", "HEAD"],
    ]
    assert (
        status_sync.latest_ci_commit(
            env={"JARVIS_LATEST_CI_COMMIT": "verified789"}, runner=lambda args: (1, "")
        )
        == "verified789"
    )


def test_latest_ci_commit_reads_pull_request_base_from_actions_event(tmp_path):
    event = tmp_path / "event.json"
    event.write_text('{"pull_request":{"base":{"sha":"base123"}}}', encoding="utf-8")
    assert (
        status_sync.latest_ci_commit(
            env={"GITHUB_EVENT_PATH": str(event)},
            runner=lambda args: (_ for _ in ()).throw(AssertionError("git must not run")),
        )
        == "base123"
    )


def test_latest_ci_commit_reads_previous_main_from_push_event(tmp_path):
    event = tmp_path / "event.json"
    event.write_text('{"before":"previous123"}', encoding="utf-8")
    assert (
        status_sync.latest_ci_commit(
            env={"GITHUB_EVENT_PATH": str(event)},
            runner=lambda args: (_ for _ in ()).throw(AssertionError("git must not run")),
        )
        == "previous123"
    )


def test_latest_ci_commit_uses_first_parent_when_checkout_is_origin_main():
    # ON main (or a detached HEAD at the main tip), "origin/main" would be the
    # very commit being generated — step back one so the ref isn't self-referential.
    seen = []
    outputs = {
        ("git", "rev-parse", "origin/main"): (0, "current123\n"),
        ("git", "rev-parse", "HEAD"): (0, "current123\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): (0, "main\n"),
        ("git", "rev-parse", "origin/main^"): (0, "previous123\n"),
    }

    def runner(args):
        seen.append(args)
        return outputs[tuple(args)]

    assert status_sync.latest_ci_commit(env={}, runner=runner) == "previous123"
    assert seen == [
        ["git", "rev-parse", "origin/main"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        ["git", "rev-parse", "origin/main^"],
    ]


def test_committed_commit_reads_value_and_fails_soft(tmp_path):
    good = tmp_path / "project-status.json"
    good.write_text('{"latest_ci_commit": "abc123def456", "tests": {}}', encoding="utf-8")
    assert status_sync._committed_commit(good) == "abc123def456"
    # absent / malformed / non-dict → "" (fail soft, never raise)
    assert status_sync._committed_commit(tmp_path / "missing.json") == ""
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert status_sync._committed_commit(bad) == ""
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    assert status_sync._committed_commit(arr) == ""


def test_check_ignores_lagging_commit_stamp(tmp_path, monkeypatch):
    """The gate must not fail merely because the committed commit stamp lags the
    live tip (the merge treadmill). --check adopts the committed stamp so only the
    meaningful fields gate; --write is unaffected and records the live stamp."""
    committed = tmp_path / "project-status.json"
    committed.write_text('{"latest_ci_commit": "oldbase00base"}', encoding="utf-8")
    monkeypatch.setattr(status_sync, "PROJECT_STATUS", committed)

    live = {"latest_ci_commit": "newtip99tip99", "tests": {"backend": 1}}
    checked = status_sync._status_for_check(live)
    assert checked["latest_ci_commit"] == "oldbase00base"  # adopted the committed stamp
    assert checked["tests"] == {"backend": 1}  # every other field preserved
    assert live["latest_ci_commit"] == "newtip99tip99"  # input dict not mutated


def test_status_for_check_is_noop_without_committed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(status_sync, "PROJECT_STATUS", tmp_path / "absent.json")
    live = {"latest_ci_commit": "keepme", "tests": {}}
    assert status_sync._status_for_check(live)["latest_ci_commit"] == "keepme"


def test_changed_status_keys_are_stable_and_specific():
    current = {"horizons": {"H35": {"open": 2, "total": 2}}, "tests": {"backend": 5}}
    expected = {
        "horizons": {"H35": {"open": 3, "total": 3}},
        "tests": {"backend": 5},
        "version": "0.27.0",
    }
    assert status_sync.changed_status_keys(current, expected) == [
        "horizons.H35.open",
        "horizons.H35.total",
        "version",
    ]


def test_fast_gate_reports_the_exact_cheap_fix_command():
    assert (
        status_sync.fix_command(reuse_js_counts=False, reuse_test_counts=True)
        == "python scripts/status_sync.py --reuse-test-counts"
    )


def test_latest_ci_commit_feature_branch_at_main_tip_does_not_step_back():
    """A freshly-created feature branch (no commits yet) sits AT the main tip.

    CI's release gate compares the committed docs against the PR base — which
    is exactly origin/main — so stepping back to origin/main^ here bakes a
    stale ref into the docs and fails the gate (bit three PRs before this
    guard). Only a checkout that IS main steps back."""
    outputs = {
        ("git", "rev-parse", "origin/main"): (0, "current123\n"),
        ("git", "rev-parse", "HEAD"): (0, "current123\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): (0, "claude/feature-branch\n"),
    }
    assert (
        status_sync.latest_ci_commit(env={}, runner=lambda args: outputs[tuple(args)])
        == "current123"
    )
