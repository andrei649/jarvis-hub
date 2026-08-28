"""Tests for scripts/soak_report.py (H23.24 — the 72h-soak evidence collector)."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "soak_report", REPO / "scripts" / "soak_report.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


soak = _load()


def _fetch_factory(payloads: dict, *, down: set | None = None):
    down = down or set()

    def fetch(path: str):
        if path in down:
            return None, "unreachable: connection refused"
        return 200, payloads.get(path, {})

    return fetch


def _sample(
    uptime=None,
    ready=True,
    rss=None,
    db_total=None,
    wal=0,
    breaches=None,
    audit_ok=True,
    breakers=None,
    log_errors=None,
    at="t",
):
    sample = {
        "at": at,
        "health": {"status": 200, "body": {"status": "ok", "uptime_seconds": uptime}},
        "ready": {"status": 200 if ready else 503, "body": {"ready": ready}},
        "north_star": {
            "status": 200,
            "body": {
                "north_star": {"accepted_per_week": 3},
                "guardrail_breaches": breaches or [],
            },
        },
        "kernel": {"status": 200, "body": {"totals": {"grant": 5}}},
        "resilience": {"status": 200, "body": {"circuit_breakers": breakers or {}}},
        "audit": {"status": 200, "body": {"ok": audit_ok}},
    }
    if rss is not None:
        sample["memory"] = {"rss_bytes": rss, "source": "pid:1"}
    if db_total is not None:
        sample["db"] = {"files": {}, "total_bytes": db_total, "wal_bytes": wal}
    if log_errors is not None:
        sample["log_errors"] = log_errors
    return sample


def test_parse_duration_units_and_junk():
    assert soak.parse_duration("72h") == 72 * 3600
    assert soak.parse_duration("30m") == 1800
    assert soak.parse_duration("45") == 45
    assert soak.parse_duration("1.5d") == 1.5 * 86400
    try:
        soak.parse_duration("three days")
    except ValueError:
        pass
    else:  # pragma: no cover - failure path
        raise AssertionError("junk duration must raise")


def test_http_fetcher_rejects_non_http_schemes():
    with pytest.raises(ValueError):
        soak.http_fetcher("file:///etc/passwd")
    with pytest.raises(ValueError):
        soak.http_fetcher("ftp://localhost/data")


def test_collect_sample_shape_and_outage_is_recorded_not_raised():
    fetch = _fetch_factory(
        {"/healthz": {"status": "ok", "uptime_seconds": 12.5}},
        down={"/api/metrics/kernel"},
    )
    sample = soak.collect_sample(fetch, mem_reader=lambda: {"rss_bytes": 42, "source": "test"})
    assert sample["health"]["status"] == 200
    assert sample["health"]["body"]["uptime_seconds"] == 12.5
    assert sample["kernel"]["status"] is None
    assert "unreachable" in sample["kernel"]["error"]
    assert sample["memory"] == {"rss_bytes": 42, "source": "test"}


def test_queue_sample_keeps_depth_and_age_but_drops_task_content():
    fetch = _fetch_factory(
        {
            "/autonomy/status": {
                "stats": {"blocked": 1, "done": 2},
                "interrupt_budget_remaining": 3,
                "pending_decisions": [
                    {
                        "created_at": "2026-07-11T23:59:00+00:00",
                        "title": "private task title",
                        "payload": {"prompt": "private prompt"},
                    }
                ],
            }
        }
    )
    sample = soak.collect_sample(
        fetch,
        mem_reader=lambda: {},
        now_iso="2026-07-12T00:00:00+00:00",
    )
    body = sample["queue"]["body"]
    assert body == {
        "stats": {"blocked": 1, "done": 2},
        "depth": 1,
        "pending_decisions": 1,
        "oldest_pending_age_seconds": 60.0,
        "interrupt_budget_remaining": 3,
        "interrupt_budget_per_day": None,
    }
    assert "private" not in json.dumps(sample).lower()


def test_audit_endpoint_outage_is_an_audit_failure():
    sample = _sample(uptime=1, at="t1")
    sample["audit"] = {"status": None, "error": "unreachable"}
    assert soak.summarize([sample])["audit"]["failures"] == ["t1"]


def test_restart_detection_counts_uptime_resets():
    samples = [_sample(uptime=value) for value in (100.0, 200.0, 50.0, 60.0, 10.0)]
    summary = soak.summarize(samples)
    assert summary["availability"]["restarts_detected"] == 2
    assert summary["availability"]["last_uptime_seconds"] == 10.0


def test_memory_and_db_growth_math():
    samples = [
        _sample(uptime=1, rss=100, db_total=1000, wal=10),
        _sample(uptime=2, rss=150, db_total=1500, wal=600),
        _sample(uptime=3, rss=120, db_total=1400, wal=20),
    ]
    summary = soak.summarize(samples)
    assert summary["memory"]["growth_bytes"] == 20
    assert summary["memory"]["peak_rss"] == 150
    assert summary["database"]["growth_bytes"] == 400
    assert summary["database"]["wal_peak_bytes"] == 600


def test_guardrail_breaches_audit_failures_and_breakers_aggregate():
    samples = [
        _sample(
            uptime=1,
            breaches=["interrupt_rate"],
            audit_ok=True,
            breakers={"weather": {"state": "open"}},
        ),
        _sample(uptime=2, breaches=["interrupt_rate", "p95_latency"], audit_ok=False, at="t2"),
    ]
    summary = soak.summarize(samples)
    assert summary["guardrails"]["samples_with_breaches"] == 2
    assert summary["guardrails"]["breach_counts"]["interrupt_rate"] == 2
    assert summary["audit"]["failures"] == ["t2"]
    assert summary["circuit_breakers_non_closed"] == {"weather": 1}


def test_error_signatures_collapse_paths_hex_and_digits():
    counts = soak.scan_error_lines(
        [
            "2026-07-12 ERROR failed to open /home/andrei/data/file123.db after 42ms",
            "2026-07-13 ERROR failed to open /home/andrei/data/file999.db after 7ms",
            "INFO all good",
        ]
    )
    assert len(counts) == 1
    ((signature, count),) = counts.items()
    assert count == 2
    assert "/home" not in signature and "42" not in signature
    assert "<path>" in signature and "<n>" in signature


def test_summarize_empty_and_malformed_samples_never_raise():
    assert soak.summarize([]) == {"samples": 0}
    summary = soak.summarize([{"at": "x"}, {"garbage": True}])
    assert summary["samples"] == 2
    assert summary["availability"]["health_ok"] == 0


def test_render_report_sections_and_partial_marker():
    samples = [
        _sample(uptime=1, rss=100, db_total=1000),
        _sample(uptime=2, rss=110, db_total=1100),
    ]
    report = soak.render_report(
        soak.summarize(samples),
        generated_at="2026-07-12T00:00:00+00:00",
        meta={"interval": 300, "base_url": "http://x"},
        partial=True,
    )
    for heading in (
        "# Soak report",
        "## Availability & restarts",
        "## Process memory",
        "## Guardrails",
        "## North-star",
        "## Audit-chain",
        "## Error signatures",
    ):
        assert heading in report
    assert "Partial window" in report
    assert "Restarts detected" in report


def test_jsonl_roundtrip_skips_torn_lines(tmp_path):
    path = tmp_path / "samples.jsonl"
    good = _sample(uptime=5)
    path.write_text(json.dumps(good) + "\n{torn-line\n" + json.dumps(good) + "\n", encoding="utf-8")
    samples = soak.load_samples(path)
    assert len(samples) == 2
    assert soak.summarize(samples)["samples"] == 2


def test_sqlite_sizes_walks_data_dir(tmp_path):
    (tmp_path / "a.db").write_bytes(b"x" * 10)
    (tmp_path / "a.db-wal").write_bytes(b"x" * 5)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.sqlite").write_bytes(b"x" * 3)
    (tmp_path / "note.txt").write_bytes(b"ignored")
    sizes = soak.sqlite_sizes(tmp_path)
    assert sizes["total_bytes"] == 18
    assert sizes["wal_bytes"] == 5
    assert set(sizes["files"]) == {"a.db", "a.db-wal", str(Path("sub") / "b.sqlite")}


def test_cli_pid_is_optional_and_gating_is_opt_in():
    parser = soak.build_parser()
    bare = parser.parse_args([])
    # No --pid: the collector must not silently measure its own process. It records no
    # RSS series at all, and evaluate() downgrades the leak check to INCONCLUSIVE.
    assert bare.pid is None
    assert bare.fail_on_verdict is False
    assert parser.parse_args(["--pid", "123"]).pid == 123
    assert parser.parse_args(["--fail-on-verdict"]).fail_on_verdict is True


def _clean_summary(**overrides):
    """A summary that clears every A2 threshold; override one key to break one check."""
    samples = [
        _sample(uptime=i * 60, rss=100_000_000, db_total=1_000, wal=1_000, at=f"t{i}")
        for i in range(20)
    ]
    summary = soak.summarize(samples)
    summary.update(overrides)
    return summary


def test_evaluate_passes_a_clean_window():
    verdict = soak.evaluate(_clean_summary())
    assert verdict["verdict"] == soak.PASS
    assert verdict["failed"] == []
    assert verdict["inconclusive"] == []
    # every check carries its own evidence line for the report
    assert all(check["detail"] for check in verdict["checks"])


@pytest.mark.parametrize(
    ("overrides", "expected_check"),
    [
        ({"availability": {"health_ok": 1, "ready_ok": 20}}, "availability_health"),
        ({"availability": {"health_ok": 20, "ready_ok": 1}}, "availability_ready"),
        ({"availability": {"health_ok": 20, "ready_ok": 20, "restarts_detected": 1}}, "restarts"),
        ({"audit": {"failures": ["t3"], "last": {}}}, "audit_chain"),
        ({"guardrails": {"samples_with_breaches": 1, "breach_counts": {"x": 1}}}, "guardrails"),
        ({"circuit_breakers_non_closed": {"ollama": 2}}, "circuit_breakers"),
        ({"memory": {"first_rss": 100, "growth_bytes": 90}}, "memory_growth"),
        ({"database": {"wal_peak_bytes": 999 * 1024 * 1024}}, "wal_size"),
    ],
)
def test_evaluate_fails_each_threshold_independently(overrides, expected_check):
    verdict = soak.evaluate(_clean_summary(**overrides))
    assert verdict["verdict"] == soak.FAIL
    assert verdict["failed"] == [expected_check]


def test_evaluate_never_passes_without_evidence():
    # A missing RSS series is not a pass — it is an ungraded check.
    verdict = soak.evaluate(_clean_summary(memory={}))
    assert verdict["verdict"] == soak.INCONCLUSIVE
    assert verdict["inconclusive"] == ["memory_growth"]
    assert verdict["failed"] == []
    # An empty summary is inconclusive on availability, not a silent pass.
    assert soak.evaluate({"samples": 0}, complete=False)["verdict"] == soak.FAIL


def test_evaluate_partial_window_is_inconclusive_not_pass():
    verdict = soak.evaluate(_clean_summary(), complete=False)
    assert verdict["verdict"] == soak.INCONCLUSIVE
    assert "window_complete" in verdict["inconclusive"]


def test_evaluate_reports_failure_before_missing_evidence():
    verdict = soak.evaluate(_clean_summary(memory={}, circuit_breakers_non_closed={"x": 1}))
    assert verdict["verdict"] == soak.FAIL


def test_report_renders_the_verdict_block():
    summary = _clean_summary()
    report = soak.render_report(
        summary,
        generated_at="2026-08-28T00:00:00+00:00",
        meta={"interval": 300, "duration": 259200, "base_url": "http://127.0.0.1:8080"},
        verdict=soak.evaluate(summary),
    )
    assert "## Verdict — **PASS**" in report
    assert "`audit_chain`" in report
    assert "no owner sign-off step" in report


def test_verdict_exit_codes_distinguish_fail_from_inconclusive():
    assert soak._VERDICT_EXIT[soak.PASS] == 0
    assert soak._VERDICT_EXIT[soak.FAIL] == 1
    assert soak._VERDICT_EXIT[soak.INCONCLUSIVE] == 3
