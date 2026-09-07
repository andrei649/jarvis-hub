"""Day report + Proof-of-Action receipts (agents/core/day_report.py).

Pins the four promises the slice makes:
  * allow-list — a report / action row / receipt carries only the declared keys;
  * no payload leakage — a task payload, result and a secret/PII-bearing title
    never reach the report bytes;
  * empty-day honesty — a day with nothing decided says so instead of zeros;
  * receipt verifies chain — an intent-log entry renders as a receipt whose
    ``verified`` flag follows the real hash chain (a tampered log goes False).
Hermetic: fake queue rows, a real IntentLog on tmp_path with an explicit key,
a spy kernel; no network, no orchestrator.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import day_report as dr  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.security.anchor import IntentLog  # noqa: E402

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
EMAIL = "victim@example.com"
NOW = datetime(2026, 9, 6, 15, 30).astimezone()
NOW_TS = NOW.timestamp()


def _iso(dt):
    return dt.astimezone().isoformat()


def _task(i, status="done", *, title="renamed the invoices folder", when=None, pushed=0,
          payload=None, result=None):
    when = when or (NOW - timedelta(hours=2))
    return SimpleNamespace(
        id=i, agent="ops", kind="fs.rename", title=title, payload=payload or {"secret": SECRET},
        risk_tier=1, status=status, autonomy_level="ask", origin="generated", attempts=1,
        result=result or {"stdout": "raw model output " + SECRET}, decided_by="owner",
        decision="approve" if status == "done" else None, pushed=pushed,
        created_at=_iso(when - timedelta(minutes=5)), updated_at=_iso(when),
    )


class _Queue:
    def __init__(self, tasks):
        self._tasks = list(tasks)

    def list(self, status=None, origin=None, limit=100):
        rows = [t for t in self._tasks if status is None or t.status == status]
        return rows[:limit]


def _north_star(**over):
    base = {
        "days": 1,
        "north_star": {"accepted_per_active_user": 2.0, "total_accepted": 2, "active_users": 1},
        "night_shift": {"done": 1, "pct": 0.5, "window": [23, 6]},
        "counter_metrics": {"interrupt_rate_per_day": 1.0, "reject_rate": 0.25, "local_pct": 87.5,
                            "p95_latency_ms": 412.0},
        "guardrails_ok": True,
        "raw": {"accepted": 2, "rejected": 1, "decisions": 3, "interrupts": 1, "latency_samples": 9},
        "proposal_funnel": {"proposed": 3},
    }
    base.update(over)
    return base


class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls = []
        self.verdict = verdict
        self.reason = reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self.verdict, reason=self.reason)


# ── allow-list ───────────────────────────────────────────────────────────────

def test_report_and_action_rows_carry_only_allow_listed_keys():
    q = _Queue([_task(1), _task(2, "rejected"), _task(3, "pending"), _task(4, "done", pushed=1)])
    rep = dr.build_day_report(_north_star(), q, now=NOW_TS, model={"name": "qwen3", "backend": "lmstudio"})
    assert set(rep) == dr.REPORT_KEYS
    assert rep["actions"], "decided rows must be listed"
    for row in rep["actions"]:
        assert set(row) == dr.ACTION_KEYS
        for forbidden in dr.FORBIDDEN_ACTION_FIELDS:
            assert forbidden not in row
    assert set(rep["north_star"]) == dr.NORTH_STAR_KEYS
    assert rep["north_star"]["local_pct"] == 87.5
    assert rep["north_star"]["reject_rate"] == 0.25
    assert rep["model"] == {"name": "qwen3", "backend": "lmstudio"}
    assert rep["counts"] == {"accepted": 2, "rejected": 1, "failed": 0, "pending": 1,
                             "night_shift": 0, "interrupts": 1}
    assert rep["empty"] is False and rep["reason"] is None
    assert rep["schema"] == dr.REPORT_SCHEMA and rep["date"] == "2026-09-06"


def test_north_star_extra_blocks_are_dropped_not_forwarded():
    ns = _north_star(attention={"pushes": 3}, raw={"accepted": 9, "secret": SECRET})
    rep = dr.build_day_report(ns, _Queue([_task(1)]), now=NOW_TS)
    assert "attention" not in json.dumps(rep)
    assert SECRET not in dr.canonical_json(rep)


# ── no payload leakage ───────────────────────────────────────────────────────

def test_payload_result_and_secret_bearing_title_never_reach_the_report_bytes():
    q = _Queue([
        _task(1, title=f"mail {EMAIL} the key {SECRET}", payload={"body": "CNP 1960101123456 " + SECRET},
              result={"echo": SECRET}),
    ])
    rep = dr.build_day_report(_north_star(), q, now=NOW_TS)
    blob = dr.canonical_json(rep)
    assert SECRET not in blob
    assert EMAIL not in blob
    assert "raw model output" not in blob
    assert '"payload"' not in blob and '"result"' not in blob
    title = rep["actions"][0]["title"]
    assert "[REDACTED:anthropic_key]" in title
    assert "[REDACTED:email]" in title
    assert len(title) <= dr.MAX_TITLE_CHARS


def test_html_card_is_escaped_self_contained_and_free_of_secrets():
    q = _Queue([_task(1, title=f"<script>alert(1)</script> {SECRET}")])
    rep = dr.build_day_report(_north_star(), q, now=NOW_TS)
    page = dr.render_report_html(rep)
    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert SECRET not in page
    assert "src=" not in page and "href=" not in page
    assert rep["fingerprint"] in page


def test_redactor_fails_closed_and_truncates_after_redacting():
    class _Boom:
        def redact(self, text):
            raise RuntimeError("scanner down")

    broken = dr.Redactor(secret_scanner=_Boom(), pii_scanner=_Boom())
    assert broken("anything") == "[REDACTED:scan_failed]"
    good = dr.default_redactor()
    out = good("x" * 10 + SECRET, limit=20)
    assert SECRET[:10] not in out and len(out) <= 20


# ── empty-day honesty ────────────────────────────────────────────────────────

def test_empty_day_is_declared_not_rendered_as_zeros():
    yesterday = NOW - timedelta(days=1, hours=1)
    q = _Queue([_task(1, when=yesterday), _task(2, "pending")])  # nothing decided today
    rep = dr.build_day_report(_north_star(), q, now=NOW_TS)
    assert rep["empty"] is True
    assert rep["reason"] == "no autonomy decisions recorded on this day"
    assert rep["actions"] == []
    assert rep["counts"]["accepted"] == 0 and rep["counts"]["pending"] == 1
    assert rep["sources"] == {"queue": True, "north_star": True}
    assert dr.render_report_html(rep).count("no autonomy decisions") == 1


def test_missing_queue_and_meter_are_named_not_faked():
    rep = dr.build_day_report(None, None, now=NOW_TS)
    assert rep["empty"] is True
    assert rep["reason"] == "autonomy queue not available — nothing can be counted"
    assert rep["sources"] == {"queue": False, "north_star": False}
    assert rep["north_star"] is None
    assert rep["model"] == {"name": None, "backend": None}


def test_window_is_the_local_calendar_day_and_explicit_day_is_honoured():
    start, end, date = dr.day_window(NOW_TS)
    assert date == "2026-09-06" and end - start == 86_400
    assert start <= NOW_TS < end
    s2, _, d2 = dr.day_window(NOW_TS, day="2026-09-01")
    assert d2 == "2026-09-01" and s2 < start
    with pytest.raises(ValueError):
        dr.day_window(NOW_TS, day="not-a-day")
    late = NOW.replace(hour=23, minute=40)
    early = NOW.replace(hour=0, minute=10)
    q = _Queue([_task(1, when=late), _task(2, when=early), _task(3, when=NOW + timedelta(days=1))])
    rep = dr.build_day_report(_north_star(), q, now=NOW_TS)
    assert [r["task_id"] for r in rep["actions"]] == [1, 2]
    assert rep["actions"][0]["night"] is True and rep["actions"][1]["night"] is True
    assert rep["counts"]["night_shift"] == 2


def test_fingerprint_is_stable_and_detects_edits():
    q = _Queue([_task(1)])
    a = dr.build_day_report(_north_star(), q, now=NOW_TS)
    b = dr.build_day_report(_north_star(), q, now=NOW_TS)
    assert a["fingerprint"] == b["fingerprint"] == dr.fingerprint_of(a)
    edited = dict(a, counts=dict(a["counts"], accepted=99))
    assert dr.fingerprint_of(edited) != a["fingerprint"]


# ── export: contract + kernel ────────────────────────────────────────────────

def _report():
    return dr.build_day_report(_north_star(), _Queue([_task(1)]), now=NOW_TS)


def test_export_writes_json_and_html_only_under_the_reports_dir(tmp_path):
    ex = dr.DayReportExporter(tmp_path / "reports")
    rep = _report()
    out = ex.export(rep, "json")
    assert out["ok"] is True and out["format"] == "json"
    path = Path(out["path"])
    assert path.parent == (tmp_path / "reports").resolve()
    assert json.loads(path.read_text(encoding="utf-8"))["fingerprint"] == rep["fingerprint"]
    assert out["bytes"] == path.stat().st_size
    html_out = ex.export(rep, "html")
    assert html_out["ok"] and Path(html_out["path"]).suffix == ".html"
    assert "<!doctype html>" in Path(html_out["path"]).read_text(encoding="utf-8")
    assert not [p for p in (tmp_path / "reports").iterdir() if p.name.startswith(".export-")]


def test_export_refuses_bad_format_tampered_report_and_oversize(tmp_path):
    ex = dr.DayReportExporter(tmp_path)
    rep = _report()
    assert ex.export(rep, "pdf") == {"ok": False, "reason": "invalid_format"}
    assert ex.export({"schema": "other"}, "json") == {"ok": False, "reason": "invalid_report"}
    tampered = dict(rep, counts=dict(rep["counts"], accepted=99))
    assert ex.export(tampered, "json") == {"ok": False, "reason": "fingerprint_mismatch"}
    tiny = dr.DayReportExporter(tmp_path, max_bytes=10)
    assert tiny.export(rep, "json") == {"ok": False, "reason": "too_large"}
    assert not list(tmp_path.iterdir())


def test_export_contract_names_each_violation():
    good = {"kind": dr.KIND, "format": "json", "date": "2026-09-06", "path": "/r/x.json",
            "root": "/r", "bytes": 10, "max_bytes": 100, "fingerprint": "a" * 64}
    assert dr.EXPORT_CONTRACT.evaluate(good).admissible
    assert dr.EXPORT_CONTRACT.requires_approval is False
    for field, value, reason in [
        ("kind", "file.write", "invalid_kind"), ("format", "pdf", "invalid_format"),
        ("date", "today", "bad_date"), ("path", "/elsewhere/x.json", "outside_scope"),
        ("path", "r/x.json", "outside_scope"), ("bytes", 0, "too_large"),
        ("bytes", True, "too_large"), ("fingerprint", "zz", "missing_fingerprint"),
    ]:
        assert dr.EXPORT_CONTRACT.evaluate(dict(good, **{field: value})).reason == reason


def test_export_consults_the_kernel_only_when_enabled_and_never_self_authorizes(tmp_path, monkeypatch):
    rep = _report()
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    off = _SpyKernel(Verdict.DENY, "would deny")
    assert dr.DayReportExporter(tmp_path / "off", authorizer=off).export(rep)["ok"] is True
    assert off.calls == []  # default-off: the hook is bound, not consulted

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    deny = _SpyKernel(Verdict.DENY, "kill-switch")
    out = dr.DayReportExporter(tmp_path / "deny", authorizer=deny).export(rep)
    assert out == {"ok": False, "reason": "kernel_denied:kill-switch"}
    assert not (tmp_path / "deny").exists()
    action = deny.calls[0]
    assert action.kind == dr.KIND and action.payload["fingerprint"] == rep["fingerprint"]
    assert set(action.payload) == {"format", "date", "path", "bytes", "fingerprint"}

    queue = _SpyKernel(Verdict.QUEUE, "ask")
    assert dr.DayReportExporter(tmp_path / "q", authorizer=queue).export(rep) == {
        "ok": False, "reason": "approval_required"}

    def boom(action, capability=None, budget=None):
        raise RuntimeError("hook down")

    assert dr.DayReportExporter(tmp_path / "e", authorizer=boom).export(rep)["reason"] == "kernel_error"

    grant = _SpyKernel(Verdict.GRANT)
    assert dr.DayReportExporter(tmp_path / "g", authorizer=grant).export(rep)["ok"] is True


def test_default_reports_dir_lives_under_data_root_not_cwd():
    from agents.core.paths import data_path, data_root

    ex = dr.DayReportExporter()
    assert ex.reports_dir == data_path("reports")
    assert data_root() in ex.reports_dir.parents
    assert ex.reports_dir != Path(os.getcwd()) / "reports"


# ── receipts ─────────────────────────────────────────────────────────────────

def _log(tmp_path):
    log = IntentLog(tmp_path / "intent_log.json", secret_key="test-key")
    log.record("kernel", "authorize:call.outbound", "grant:policy allows",
               cause=f"user asked to ring {EMAIL}",
               metadata={"verdict": "grant", "tier": 2, "scope": "global", "agent": "jarvis",
                         "payload": {"number": "+40712345678", "token": SECRET}})
    log.record("kernel", "authorize:file.write", "deny:kill-switch engaged",
               metadata={"verdict": "deny", "tier": 3, "scope": "global", "agent": "jarvis"})
    log.record("worker", "task.done", f"finished with {SECRET}")
    return log


def test_receipt_verifies_the_chain_and_redacts_free_text(tmp_path):
    log = _log(tmp_path)
    out = dr.build_receipt(log, "2", now=NOW_TS)
    assert out["ok"] is True and out["reason"] is None
    r = out["receipt"]
    assert set(r) == dr.RECEIPT_KEYS
    assert r["verified"] is True and r["chain"]["ok"] is True and r["chain"]["entries"] == 3
    assert r["signed"] is True and r["audit_id"] == 2
    assert r["decision"] == {"verdict": "deny", "tier": 3, "scope": "global", "agent": "jarvis"}
    entries = {e["seq"]: e for e in log.list(10)}
    assert r["prev_hash"] == entries[1]["entry_hash"] and r["entry_hash"] == entries[2]["entry_hash"]
    assert r["fingerprint"] == dr.fingerprint_of(r)

    first = dr.build_receipt(log, 1)["receipt"]
    blob = dr.canonical_json(first)
    assert EMAIL not in blob and SECRET not in blob and "+40712345678" not in blob
    assert "payload" not in first["decision"]
    assert "[REDACTED:email]" in first["cause"]
    third = dr.build_receipt(log, 3)["receipt"]
    assert SECRET not in third["why"] and "[REDACTED:anthropic_key]" in third["why"]
    assert third["decision"] == {}


def test_receipt_goes_unverified_when_the_log_is_tampered(tmp_path):
    log = _log(tmp_path)
    # rewrite entry 1's intent in place — the hash no longer matches the body
    log._entries[0]["why"] = "grant:owner never said this"
    log._save()
    reloaded = IntentLog(tmp_path / "intent_log.json", secret_key="test-key")
    broken = dr.build_receipt(reloaded, 1)
    assert broken["ok"] is True  # the card exists — its verdict is what changed
    assert broken["receipt"]["verified"] is False
    assert broken["receipt"]["reason"] == "chain_broken:1"
    assert broken["receipt"]["chain"]["ok"] is False
    later = dr.build_receipt(reloaded, 2)["receipt"]
    assert later["verified"] is False and later["reason"] == "chain_broken:1"


def test_receipt_detects_a_spliced_entry_by_its_link(tmp_path):
    log = _log(tmp_path)
    log._entries[1]["prev_hash"] = "0" * 64
    log._save()
    reloaded = IntentLog(tmp_path / "intent_log.json", secret_key="test-key")
    r = dr.build_receipt(reloaded, 2)["receipt"]
    assert r["verified"] is False and r["reason"] == "unlinked"
    untouched = dr.build_receipt(reloaded, 1)["receipt"]
    assert untouched["verified"] is True  # the break is after it


def test_receipt_refuses_bad_ids_and_missing_entries(tmp_path):
    log = _log(tmp_path)
    for bad in ("abc", "0", "-3", "", None, True, "1.5"):
        assert dr.build_receipt(log, bad) == {"ok": False, "reason": "bad_audit_id", "receipt": None}
    assert dr.build_receipt(log, 99) == {"ok": False, "reason": "not_found", "receipt": None}
    assert dr.build_receipt(None, 1) == {"ok": False, "reason": "intent_log_unavailable", "receipt": None}

    class _Down:
        def list(self, limit=100):
            raise RuntimeError("disk")

    assert dr.build_receipt(_Down(), 1)["reason"] == "intent_log_unavailable"
