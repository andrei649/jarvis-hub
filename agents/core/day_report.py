"""day_report.py — the shareable "what Nerva did today" report + Proof-of-Action receipts.

Two trust artefacts a user can hand to someone else without handing over their
life:

* :func:`build_day_report` — a **redacted, allow-listed, payload-free** daily
  summary. Counts come from the north-star meter (``observability.north_star``)
  and the autonomy ``TaskQueue``; the only free text that survives is a task
  *title*, and it survives only after the secret + PII scanners have run over
  it. Task ``payload`` / ``result`` never enter the report — not "redacted",
  *absent by construction* (:data:`ACTION_KEYS` is the whole vocabulary).
  An empty day says so (``empty: true`` + a reason) instead of rendering zeros
  as if they were a measurement.
* :func:`build_receipt` — a **Proof-of-Action receipt** for one entry of the
  hash-chained, HMAC-signed :class:`security.anchor.IntentLog`. The receipt
  re-links the entry to its predecessor, verifies the whole chain, and renders
  a card whose free-text fields (``why``/``cause``) pass through the same
  scanners. Only a user-owned chain can give this: the receipt is checkable
  against the owner's own log, not against a vendor's word.

Governance (MOONSHOT §5): the report is a *read* of the owner's own stores.
The one effect — :meth:`DayReportExporter.export` writing a file — lands only
under ``data_path('reports')`` (never CWD), is bounded by
:data:`EXPORT_CONTRACT`, and consults an *injected* Action-Kernel authorizer
(``authorize(Action) -> Decision``) with the kind :data:`KIND` before the
bytes move — DENY refuses, QUEUE refuses with ``approval_required``. Nothing
here self-authorizes; the registry entry is the integrator's edit. Local-first,
no network, no new dependencies, no shell.

Every report and receipt carries a ``fingerprint`` — the SHA-256 of its
canonical JSON — so a shared copy can be matched against the original.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.paths import data_path

logger = logging.getLogger("jarvis.day_report")

# ── vocabulary ───────────────────────────────────────────────────────────────

KIND = "report.export"
REPORT_SCHEMA = "nerva.day-report.v1"
RECEIPT_SCHEMA = "nerva.receipt.v1"
EXPORT_FORMATS = ("json", "html")
DEFAULT_MAX_EXPORT_BYTES = 2_000_000
MAX_ACTIONS = 50
MAX_TITLE_CHARS = 120
MAX_TEXT_CHARS = 240
_DAY_SECONDS = 86_400
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# The allow-lists ARE the contract: a key that is not here cannot reach a
# report, whatever the source row carries. Tests pin them.
REPORT_KEYS = frozenset({
    "schema", "date", "generated_at", "window", "empty", "reason", "sources",
    "counts", "north_star", "actions", "model", "fingerprint",
})
ACTION_KEYS = frozenset({
    "task_id", "title", "kind", "agent", "status", "tier", "decided_by", "at", "night",
})
NORTH_STAR_KEYS = frozenset({
    "days", "accepted_per_active_user", "total_accepted", "local_pct", "reject_rate",
    "interrupt_rate_per_day", "p95_latency_ms", "guardrails_ok", "night_shift_done",
})
RECEIPT_KEYS = frozenset({
    "schema", "audit_id", "at", "actor", "action", "why", "cause", "decision",
    "entry_hash", "prev_hash", "signed", "chain", "verified", "reason", "fingerprint",
})
# metadata keys the kernel writes on every decision (kernel._emit_audit) — the
# only ones a receipt shows; anything else in metadata is payload-tier.
DECISION_KEYS = ("verdict", "tier", "scope", "agent")
# Fields that never leave a task row, listed so the leakage test can name them.
FORBIDDEN_ACTION_FIELDS = ("payload", "result", "mediation_receipt", "kernel_intake_evidence")

# statuses folded into the counts block
_ACCEPTED = {"done"}
_REJECTED = {"rejected"}
_FAILED = {"failed"}
_PENDING = {"pending", "blocked", "queued", "running", "approved", "deferred"}


# ── redaction ────────────────────────────────────────────────────────────────

class Redactor:
    """Secret + PII scanners composed once (same pair AuditLogger uses)."""

    def __init__(self, secret_scanner=None, pii_scanner=None):
        if secret_scanner is None or pii_scanner is None:
            from agents.core.security.scanner import PIIScanner, SecretScanner

            secret_scanner = secret_scanner or SecretScanner()
            pii_scanner = pii_scanner or PIIScanner()
        self._secret = secret_scanner
        self._pii = pii_scanner

    def __call__(self, text: object, *, limit: int = MAX_TEXT_CHARS) -> str:
        """Redact-then-truncate (truncating first can split a key so no pattern
        matches — the ``AuditLogger.preview`` lesson). Fails closed."""
        raw = str(text or "")
        if not raw:
            return ""
        try:
            clean = self._pii.redact(self._secret.redact(raw))
        except Exception:
            return "[REDACTED:scan_failed]"
        clean = " ".join(clean.split())
        return clean[: max(1, int(limit))]


_DEFAULT_REDACTOR: Redactor | None = None


def default_redactor() -> Redactor:
    global _DEFAULT_REDACTOR
    if _DEFAULT_REDACTOR is None:
        _DEFAULT_REDACTOR = Redactor()
    return _DEFAULT_REDACTOR


# ── helpers ──────────────────────────────────────────────────────────────────

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint_of(obj: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON with any existing ``fingerprint`` removed."""
    body = {k: v for k, v in obj.items() if k != "fingerprint"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _iso_to_epoch(value: object) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError):
        return None


def _local_dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch).astimezone()


def day_window(now: float, *, day: str | None = None) -> tuple[float, float, str]:
    """``(start, end, date)`` of the local calendar day holding ``now`` (or
    ``day`` as ``YYYY-MM-DD``). Local time: the same convention the autonomy
    worker uses for its night window."""
    if day is not None:
        if not _DATE_RE.match(str(day)):
            raise ValueError("bad_day")
        anchor = datetime.strptime(str(day), "%Y-%m-%d").astimezone()
        start_dt = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start_dt = _local_dt(now).replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    return start_dt.timestamp(), end_dt.timestamp(), start_dt.strftime("%Y-%m-%d")


def _clean_int(value: object, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _clean_number(value: object) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return None


# ── the day report ───────────────────────────────────────────────────────────

def _project_action(task: Any, redact: Callable[..., str], night_window: tuple[int, int]) -> dict:
    """One allow-listed, payload-free action row. Reads attributes by name so a
    ``Task`` dataclass, a SimpleNamespace fake or a dict all project the same."""
    get = (lambda k: task.get(k)) if isinstance(task, Mapping) else (lambda k: getattr(task, k, None))
    at = str(get("updated_at") or "")
    ep = _iso_to_epoch(at)
    night = False
    if ep is not None:
        hour = _local_dt(ep).hour
        start, end = night_window
        night = (hour >= start or hour < end) if start > end else (start <= hour < end)
    row = {
        "task_id": _clean_int(get("id")),
        "title": redact(get("title"), limit=MAX_TITLE_CHARS),
        "kind": redact(get("kind"), limit=64),
        "agent": redact(get("agent"), limit=64),
        "status": str(get("status") or "").lower()[:32],
        "tier": _clean_int(get("risk_tier")),
        "decided_by": redact(get("decided_by"), limit=32) or None,
        "at": at[:40],
        "night": night,
    }
    return {k: v for k, v in row.items() if k in ACTION_KEYS}


def _project_north_star(north_star: Mapping[str, Any] | None) -> dict | None:
    """The allow-listed subset of ``compute_north_star``'s payload."""
    if not isinstance(north_star, Mapping):
        return None
    ns = north_star.get("north_star") if isinstance(north_star.get("north_star"), Mapping) else {}
    cm = north_star.get("counter_metrics") if isinstance(north_star.get("counter_metrics"), Mapping) else {}
    night = north_star.get("night_shift") if isinstance(north_star.get("night_shift"), Mapping) else {}
    out = {
        "days": _clean_int(north_star.get("days"), 1),
        "accepted_per_active_user": _clean_number(ns.get("accepted_per_active_user")),
        "total_accepted": _clean_int(ns.get("total_accepted"), 0),
        "local_pct": _clean_number(cm.get("local_pct")),
        "reject_rate": _clean_number(cm.get("reject_rate")),
        "interrupt_rate_per_day": _clean_number(cm.get("interrupt_rate_per_day")),
        "p95_latency_ms": _clean_number(cm.get("p95_latency_ms")),
        "guardrails_ok": bool(north_star.get("guardrails_ok", True)),
        "night_shift_done": _clean_int(night.get("done"), 0),
    }
    return {k: v for k, v in out.items() if k in NORTH_STAR_KEYS}


def build_day_report(
    north_star: Mapping[str, Any] | None,
    queue: Any,
    *,
    now: float | None = None,
    day: str | None = None,
    model: Mapping[str, Any] | None = None,
    night_window: tuple[int, int] = (23, 6),
    fetch_limit: int = 5000,
    redactor: Callable[..., str] | None = None,
) -> dict:
    """Build the allow-listed, payload-free report for one local calendar day.

    ``north_star`` is a ``compute_north_star`` payload (or None); ``queue`` an
    autonomy ``TaskQueue`` exposing ``list(limit=)`` (or None). Pure over its
    inputs — ``now`` is injectable, nothing is read from the environment.
    """
    redact = redactor or default_redactor()
    now = time.time() if now is None else float(now)
    start, end, date = day_window(now, day=day)

    counts = {"accepted": 0, "rejected": 0, "failed": 0, "pending": 0, "night_shift": 0, "interrupts": 0}
    actions: list[dict] = []
    queue_available = queue is not None
    if queue_available:
        try:
            tasks = list(queue.list(limit=fetch_limit))
        except Exception:
            logger.warning("day report: queue read failed", exc_info=True)
            tasks, queue_available = [], False
        for task in tasks:
            get = (lambda k, _t=task: _t.get(k)) if isinstance(task, Mapping) else (
                lambda k, _t=task: getattr(_t, k, None))
            ep = _iso_to_epoch(get("updated_at"))
            if ep is None or not (start <= ep < end):
                continue
            row = _project_action(task, redact, night_window)
            st = row["status"]
            if st in _ACCEPTED:
                counts["accepted"] += 1
                if row["night"]:
                    counts["night_shift"] += 1
            elif st in _REJECTED:
                counts["rejected"] += 1
            elif st in _FAILED:
                counts["failed"] += 1
            elif st in _PENDING:
                counts["pending"] += 1
            if get("pushed"):
                counts["interrupts"] += 1
            if st in _ACCEPTED | _REJECTED | _FAILED:
                actions.append(row)
    actions.sort(key=lambda r: r["at"], reverse=True)
    actions = actions[:MAX_ACTIONS]

    ns_block = _project_north_star(north_star)
    decisions = counts["accepted"] + counts["rejected"] + counts["failed"]
    empty = decisions == 0 and not actions
    if not queue_available:
        reason = "autonomy queue not available — nothing can be counted"
    elif empty:
        reason = "no autonomy decisions recorded on this day"
    else:
        reason = None

    model_block = {"name": None, "backend": None}
    if isinstance(model, Mapping):
        model_block = {
            "name": redact(model.get("name"), limit=96) or None,
            "backend": redact(model.get("backend"), limit=32) or None,
        }

    report = {
        "schema": REPORT_SCHEMA,
        "date": date,
        "generated_at": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
        "window": {
            "start": datetime.fromtimestamp(start).astimezone().isoformat(timespec="seconds"),
            "end": datetime.fromtimestamp(end).astimezone().isoformat(timespec="seconds"),
        },
        "empty": empty,
        "reason": reason,
        "sources": {"queue": queue_available, "north_star": ns_block is not None},
        "counts": counts,
        "north_star": ns_block,
        "actions": actions,
        "model": model_block,
    }
    report = {k: v for k, v in report.items() if k in REPORT_KEYS}
    report["fingerprint"] = fingerprint_of(report)
    return report


# ── HTML card ────────────────────────────────────────────────────────────────

_CARD_CSS = (
    "body{margin:0;background:#04070e;color:#e9f4fd;font:14px/1.5 system-ui,sans-serif}"
    ".card{max-width:640px;margin:24px auto;padding:20px 24px;border:1px solid rgba(120,190,240,.25);"
    "border-radius:6px;background:#060b15}"
    "h1{font-size:16px;letter-spacing:.12em;margin:0 0 4px}"
    ".sub,.foot{color:rgba(233,244,253,.62);font-size:12px}"
    ".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}"
    ".n{font-size:26px;color:#8fe0ff}.k{font-size:11px;letter-spacing:.08em;color:rgba(233,244,253,.62)}"
    "ul{padding-left:18px;margin:8px 0}li{margin:2px 0}.tag{font-size:11px;color:#41f59b}"
    ".empty{color:#ffc24d}code{font-size:11px;word-break:break-all}"
)


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def render_report_html(report: Mapping[str, Any]) -> str:
    """A self-contained (no script, no external asset) HTML card for the report.
    Every value is escaped; the input is already allow-listed and redacted."""
    counts = report.get("counts") or {}
    ns = report.get("north_star") or {}
    rows = "".join(
        f"<li>{_esc(a.get('title'))} <span class='tag'>{_esc(a.get('status'))}"
        f"{' · night' if a.get('night') else ''}</span></li>"
        for a in (report.get("actions") or [])
    )
    local = ns.get("local_pct")
    body = (
        f"<p class='empty'>{_esc(report.get('reason'))}</p>" if report.get("empty")
        else f"<ul>{rows}</ul>"
    )
    model = (report.get("model") or {}).get("name")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Nerva · {_esc(report.get('date'))}</title><style>{_CARD_CSS}</style></head><body>"
        "<div class='card'><h1>NERVA · TODAY</h1>"
        f"<div class='sub'>{_esc(report.get('date'))} · {_esc(report.get('schema'))}</div>"
        "<div class='grid'>"
        f"<div><div class='n'>{_esc(counts.get('accepted', 0))}</div><div class='k'>ACCEPTED</div></div>"
        f"<div><div class='n'>{_esc(counts.get('rejected', 0))}</div><div class='k'>REJECTED</div></div>"
        f"<div><div class='n'>{_esc(counts.get('night_shift', 0))}</div><div class='k'>WHILE YOU SLEPT</div></div>"
        "</div>"
        f"{body}"
        f"<div class='foot'>local: {_esc('not measured' if local is None else f'{local}%')}"
        f" · model: {_esc(model or 'not reported')}</div>"
        f"<div class='foot'>fingerprint <code>{_esc(report.get('fingerprint'))}</code></div>"
        "</div></body></html>"
    )


# ── the export contract + exporter ───────────────────────────────────────────

def _export_contract_template() -> ContractTemplate:
    def right_kind(view, now):
        return view.get("kind") == KIND

    def known_format(view, now):
        return view.get("format") in EXPORT_FORMATS

    def valid_date(view, now):
        return isinstance(view.get("date"), str) and bool(_DATE_RE.match(view["date"]))

    def path_inside_reports(view, now):
        path, root = view.get("path"), view.get("root")
        if not isinstance(path, str) or not isinstance(root, str) or not root:
            return False
        p, r = Path(path), Path(root)
        return p.is_absolute() and (p == r or r in p.parents)

    def bytes_within_cap(view, now):
        size, cap = view.get("bytes"), view.get("max_bytes")
        if isinstance(size, bool) or isinstance(cap, bool):
            return False
        return isinstance(size, int) and isinstance(cap, int) and 0 < size <= cap

    def fingerprinted(view, now):
        fp = view.get("fingerprint")
        return isinstance(fp, str) and bool(_HEX64.match(fp))

    return ContractTemplate(kind="report_export", constraints=(
        predicate("right_kind", right_kind, reason="invalid_kind"),
        predicate("known_format", known_format, reason="invalid_format"),
        predicate("valid_date", valid_date, reason="bad_date"),
        predicate("path_inside_reports", path_inside_reports, reason="outside_scope"),
        predicate("bytes_within_cap", bytes_within_cap, reason="too_large"),
        predicate("fingerprinted", fingerprinted, reason="missing_fingerprint"),
    ), requires_approval=False, description=(
        "Admissibility for exporting a redacted day report: a known format, a dated, "
        "fingerprinted report, written only under the local reports directory and under the byte cap."
    ))


EXPORT_CONTRACT = _export_contract_template()


class DayReportExporter:
    """Writes a built report to ``<data_root>/reports/`` after contract + kernel checks.

    ``authorizer`` is the injected kernel hook (``authorize(Action) -> Decision``);
    like ``FileTools`` it is consulted only while ``JARVIS_ACTION_KERNEL`` is on,
    so an unset flag is structurally the pre-kernel path, not a silent grant.
    """

    def __init__(self, reports_dir: str | os.PathLike | None = None, *, authorizer=None,
                 agent: str = "jarvis", max_bytes: int = DEFAULT_MAX_EXPORT_BYTES):
        self.reports_dir = Path(reports_dir) if reports_dir is not None else data_path("reports")
        self._authorizer = authorizer
        self.agent = agent
        self.max_bytes = max(1, int(max_bytes))

    def target_for(self, report: Mapping[str, Any], fmt: str) -> Path:
        fp = str(report.get("fingerprint") or "")[:12] or "nofp"
        return (self.reports_dir / f"{report.get('date')}-{fp}.{fmt}").resolve()

    def export(self, report: Mapping[str, Any], fmt: str = "json") -> dict:
        """Synchronous (callers offload with ``asyncio.to_thread``). Returns
        ``{"ok": True, path, bytes, sha256, format}`` or ``{"ok": False, reason}``."""
        fmt = str(fmt or "").lower()
        if fmt not in EXPORT_FORMATS:
            return {"ok": False, "reason": "invalid_format"}
        if not isinstance(report, Mapping) or report.get("schema") != REPORT_SCHEMA:
            return {"ok": False, "reason": "invalid_report"}
        if fingerprint_of(report) != report.get("fingerprint"):
            return {"ok": False, "reason": "fingerprint_mismatch"}
        data = (render_report_html(report) if fmt == "html" else canonical_json(report)).encode("utf-8")
        target = self.target_for(report, fmt)
        payload = {
            "kind": KIND, "format": fmt, "date": report.get("date"), "path": str(target),
            "root": str(self.reports_dir.resolve()), "bytes": len(data),
            "max_bytes": self.max_bytes, "fingerprint": report.get("fingerprint"),
        }
        decision = EXPORT_CONTRACT.evaluate(payload, now=time.time())
        if not decision.admissible:
            return {"ok": False, "reason": decision.reason or "contract_denied"}
        refused = self._authorize(payload)
        if refused:
            return {"ok": False, "reason": refused}
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".export-", dir=str(self.reports_dir))
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, target)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError:
            logger.warning("day report export failed", exc_info=True)
            return {"ok": False, "reason": "write_failed"}
        return {
            "ok": True, "path": str(target), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "format": fmt,
        }

    def _authorize(self, payload: dict) -> str | None:
        if self._authorizer is None:
            return None
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            return None
        action = Action(
            kind=KIND, agent=self.agent, title=f"export day report {payload['date']}",
            payload={k: payload[k] for k in ("format", "date", "path", "bytes", "fingerprint")},
            origin=current_action_origin(),
        )
        try:
            decision = self._authorizer(action)
        except Exception:
            logger.warning("day report kernel hook failed closed", exc_info=True)
            return "kernel_error"
        verdict = getattr(decision, "verdict", None)
        if verdict is Verdict.DENY:
            return f"kernel_denied:{getattr(decision, 'reason', '') or 'denied'}"
        if verdict is Verdict.QUEUE:
            return "approval_required"
        if verdict is not Verdict.GRANT:
            return "kernel_error"
        return None


# ── Proof-of-Action receipts ─────────────────────────────────────────────────

def parse_audit_id(value: object) -> int | None:
    """An intent-log ``seq`` (positive int) or None for anything else."""
    if isinstance(value, bool):
        return None
    try:
        seq = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seq if seq > 0 else None


def build_receipt(intent_log: Any, audit_id: object, *, redactor: Callable[..., str] | None = None,
                  now: float | None = None) -> dict:
    """Render one intent-log entry as a verifiable card.

    Returns ``{"ok": bool, "reason": str|None, "receipt": dict|None}``. ``ok`` is
    True whenever a card could be built; ``receipt.verified`` says whether the
    chain and the entry's own link hold. ``reason`` is ``bad_audit_id`` /
    ``not_found`` / ``intent_log_unavailable`` when no card exists.
    """
    redact = redactor or default_redactor()
    seq = parse_audit_id(audit_id)
    if seq is None:
        return {"ok": False, "reason": "bad_audit_id", "receipt": None}
    if intent_log is None:
        return {"ok": False, "reason": "intent_log_unavailable", "receipt": None}
    try:
        entries = {int(e.get("seq")): e for e in intent_log.list(limit=1_000_000) if isinstance(e, Mapping)}
    except Exception:
        logger.warning("receipt: intent log read failed", exc_info=True)
        return {"ok": False, "reason": "intent_log_unavailable", "receipt": None}
    entry = entries.get(seq)
    if entry is None:
        return {"ok": False, "reason": "not_found", "receipt": None}

    try:
        chain = intent_log.verify()
    except Exception:
        chain = {"ok": False, "bad_seq": None, "reason": "verify_failed", "n": len(entries)}
    chain_ok = bool(chain.get("ok"))
    # the entry's own link: its prev_hash must be the predecessor's entry_hash
    prev = entries.get(seq - 1)
    expected_prev = str(prev.get("entry_hash") or "") if prev else ""
    linked = str(entry.get("prev_hash") or "") == expected_prev
    bad_seq = chain.get("bad_seq")
    # a break AFTER this entry does not touch it; a break at or before it does
    entry_intact = chain_ok or (isinstance(bad_seq, int) and bad_seq > seq)
    verified = linked and entry_intact
    if not verified:
        reason = "unlinked" if not linked else f"chain_broken:{bad_seq if bad_seq is not None else 'unknown'}"
    else:
        reason = None

    meta = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
    decision = {k: meta.get(k) for k in DECISION_KEYS if k in meta}
    if "tier" in decision:
        decision["tier"] = _clean_int(decision["tier"])
    for k in ("verdict", "scope", "agent"):
        if k in decision:
            decision[k] = redact(decision[k], limit=64)
    ts = entry.get("ts")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "audit_id": seq,
        "at": datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds")
        if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None,
        "actor": redact(entry.get("actor"), limit=64),
        "action": redact(entry.get("action"), limit=96),
        "why": redact(entry.get("why")),
        "cause": redact(entry.get("cause")) or None,
        "decision": decision,
        "entry_hash": str(entry.get("entry_hash") or ""),
        "prev_hash": str(entry.get("prev_hash") or ""),
        "signed": bool(entry.get("signature")),
        "chain": {
            "ok": chain_ok,
            "entries": _clean_int(chain.get("n"), len(entries)),
            "bad_seq": _clean_int(bad_seq),
            "verified_at": datetime.fromtimestamp(time.time() if now is None else float(now))
            .astimezone().isoformat(timespec="seconds"),
        },
        "verified": verified,
        "reason": reason,
    }
    receipt = {k: v for k, v in receipt.items() if k in RECEIPT_KEYS}
    receipt["fingerprint"] = fingerprint_of(receipt)
    return {"ok": True, "reason": reason, "receipt": receipt}


__all__ = [
    "KIND", "REPORT_SCHEMA", "RECEIPT_SCHEMA", "EXPORT_FORMATS", "EXPORT_CONTRACT",
    "REPORT_KEYS", "ACTION_KEYS", "NORTH_STAR_KEYS", "RECEIPT_KEYS", "DECISION_KEYS",
    "FORBIDDEN_ACTION_FIELDS", "MAX_ACTIONS", "Redactor", "default_redactor",
    "canonical_json", "fingerprint_of", "day_window", "build_day_report",
    "render_report_html", "DayReportExporter", "parse_audit_id", "build_receipt",
]
