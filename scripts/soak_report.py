#!/usr/bin/env python3
"""Collect and render evidence for the unattended 72-hour release soak (H23.24).

The collector is deliberately resilient: a failed endpoint, unreadable log, or
missing process metric is recorded in the sample instead of stopping the soak.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO / "memory_logs"
DEFAULT_OUTPUT_DIR = REPO / "docs" / "research"

_ENDPOINTS = {
    "health": "/healthz",
    "ready": "/readyz",
    "north_star": "/api/metrics/north-star",
    "kernel": "/api/metrics/kernel",
    "queue": "/autonomy/status",
    "audit": "/api/security/audit/verify",
    "resilience": "/api/resilience",
    "capabilities": "/api/metrics/capabilities",
}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)(?:[^\s:]+[/\\])+[^\s:]+")
_HEX_RE = re.compile(r"\b(?:0x)?[0-9a-f]{12,}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ERROR_RE = re.compile(r"\b(?:error|exception|failed|failure|traceback|critical)\b", re.IGNORECASE)
_OPEN_QUEUE_STATES = {"proposed", "approved", "running", "blocked", "deferred"}

Fetch = Callable[[str], tuple[int | None, Any]]

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"

# The A2 bar, written down. These are the numbers the owner used to apply by eye when
# reading the rendered report; encoding them here is what turns the soak from a gate
# somebody has to sign into a check that reports its own verdict.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_samples": 12,
    "min_availability": 0.99,  # share of samples where /healthz and /readyz were OK
    "max_restarts": 0,  # "unattended" means the process never came back up
    "max_audit_failures": 0,  # AUD-0: the audit chain verifies at every single sample
    "max_breach_samples": 0,  # any north-star guardrail breach sinks the window
    "max_breaker_samples": 0,  # no circuit breaker may sit open
    "max_rss_growth_ratio": 0.15,  # RSS may not grow more than 15% across the window
    "max_wal_bytes": 64 * 1024 * 1024,
}


def parse_duration(value: str) -> float:
    """Parse seconds or a compact s/m/h/d duration."""
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"invalid duration: {value!r}")
    amount = float(match.group(1))
    multiplier = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]
    return amount * multiplier


def http_fetcher(base_url: str, *, admin_token: str = "", timeout: float = 10) -> Fetch:
    """Return the real HTTP reader used by the CLI."""
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base URL must use http:// or https://")
    base = base_url.rstrip("/")

    def fetch(path: str) -> tuple[int | None, Any]:
        headers = {"Accept": "application/json"}
        if admin_token:
            headers["X-Admin-Token"] = admin_token
        request = urllib.request.Request(f"{base}{path}", headers=headers)
        try:
            # Operator-selected endpoint; scheme was restricted to HTTP(S) above.
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request, timeout=timeout
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    return response.status, json.loads(raw)
                except json.JSONDecodeError:
                    return response.status, {"raw": raw[:1000]}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw[:1000]
            return exc.code, payload
        except (OSError, urllib.error.URLError) as exc:
            return None, f"unreachable: {type(exc).__name__}: {exc}"

    return fetch


def process_memory(pid: int | None = None) -> dict:
    """Best-effort resident memory with no mandatory third-party dependency."""
    target = pid or os.getpid()
    try:
        import psutil  # type: ignore[import-not-found]

        return {
            "rss_bytes": int(psutil.Process(target).memory_info().rss),
            "source": f"pid:{target}",
        }
    except (ImportError, OSError):
        pass
    status = Path(f"/proc/{target}/status")
    if status.exists():
        match = re.search(r"^VmRSS:\s+(\d+)\s+kB", status.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return {"rss_bytes": int(match.group(1)) * 1024, "source": f"pid:{target}"}
    return {"rss_bytes": None, "source": "unavailable"}


def sqlite_sizes(root: Path) -> dict:
    """Snapshot SQLite database, journal and WAL sizes below *root*."""
    files: dict[str, int] = {}
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if not (name.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm", "-journal"))):
                continue
            try:
                files[str(path.relative_to(root))] = path.stat().st_size
            except OSError:
                continue
    return {
        "files": files,
        "total_bytes": sum(files.values()),
        "wal_bytes": sum(size for name, size in files.items() if name.lower().endswith("-wal")),
    }


def _signature(line: str) -> str:
    text = _PATH_RE.sub("<path>", line.strip())
    text = _HEX_RE.sub("<hex>", text)
    text = _NUMBER_RE.sub("<n>", text)
    return re.sub(r"\s+", " ", text)[:500]


def scan_error_lines(lines: list[str]) -> dict[str, int]:
    """Collapse error lines into redacted signatures (paths/ids/numbers removed)."""
    return dict(Counter(_signature(line) for line in lines if _ERROR_RE.search(line)))


def read_log_errors(path: Path | None, *, tail_bytes: int = 1_000_000) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - tail_bytes))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        return scan_error_lines(lines)
    except OSError:
        return {}


def _queue_evidence(payload: Any, at: str) -> dict:
    """Reduce the admin queue response to counts/age; never persist task content."""
    source = payload if isinstance(payload, dict) else {}
    stats = source.get("stats", {})
    stats = stats if isinstance(stats, dict) else {}
    clean_stats = {str(key): int(value) for key, value in stats.items() if isinstance(value, int)}
    pending = source.get("pending_decisions", [])
    pending_rows = pending if isinstance(pending, list) else []
    ages = []
    try:
        sampled_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        for row in pending_rows:
            created = row.get("created_at") if isinstance(row, dict) else None
            if not created:
                continue
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            ages.append(max(0.0, (sampled_at - created_at).total_seconds()))
    except (TypeError, ValueError):
        ages = []
    return {
        "stats": clean_stats,
        "depth": sum(value for key, value in clean_stats.items() if key in _OPEN_QUEUE_STATES),
        "pending_decisions": len(pending_rows),
        "oldest_pending_age_seconds": max(ages) if ages else None,
        "interrupt_budget_remaining": source.get("interrupt_budget_remaining"),
        "interrupt_budget_per_day": source.get("interrupt_budget_per_day"),
    }


def collect_sample(
    fetch: Fetch,
    *,
    mem_reader: Callable[[], dict] = process_memory,
    db_reader: Callable[[], dict] | None = None,
    log_reader: Callable[[], dict[str, int]] | None = None,
    now_iso: str | None = None,
) -> dict:
    """Collect one sample; every individual failure is recorded, never raised."""
    sample: dict[str, Any] = {"at": now_iso or datetime.now(UTC).isoformat(timespec="seconds")}
    for key, path in _ENDPOINTS.items():
        try:
            status, payload = fetch(path)
            if status is None:
                sample[key] = {"status": None, "error": str(payload)}
            else:
                if key == "queue":
                    payload = _queue_evidence(payload, sample["at"])
                sample[key] = {"status": status, "body": payload}
        except Exception as exc:  # collector boundary: evidence must continue
            sample[key] = {"status": None, "error": f"{type(exc).__name__}: {exc}"}
    for key, reader in (("memory", mem_reader), ("db", db_reader), ("log_errors", log_reader)):
        if reader is None:
            continue
        try:
            sample[key] = reader()
        except Exception as exc:  # collector boundary: evidence must continue
            sample[key] = {"error": f"{type(exc).__name__}: {exc}"}
    return sample


def _body(sample: dict, key: str) -> dict:
    value = sample.get(key, {})
    body = value.get("body", {}) if isinstance(value, dict) else {}
    return body if isinstance(body, dict) else {}


def _series(samples: list[dict], section: str, key: str) -> list[int | float]:
    values = []
    for sample in samples:
        value = sample.get(section, {})
        if isinstance(value, dict) and isinstance(value.get(key), (int, float)):
            values.append(value[key])
    return values


def summarize(samples: list[dict]) -> dict:
    """Aggregate a possibly partial/malformed soak sample list."""
    if not samples:
        return {"samples": 0}
    uptimes = [
        _body(sample, "health").get("uptime_seconds")
        for sample in samples
        if isinstance(_body(sample, "health").get("uptime_seconds"), (int, float))
    ]
    restarts = sum(
        1 for previous, current in zip(uptimes, uptimes[1:], strict=False) if current < previous
    )
    rss = _series(samples, "memory", "rss_bytes")
    db_sizes = _series(samples, "db", "total_bytes")
    wal_sizes = _series(samples, "db", "wal_bytes")

    breaches: Counter[str] = Counter()
    breach_samples = 0
    audit_failures: list[str] = []
    breakers: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    for sample in samples:
        north = _body(sample, "north_star")
        sample_breaches = north.get("guardrail_breaches", [])
        if isinstance(sample_breaches, dict):
            sample_breaches = [key for key, value in sample_breaches.items() if value]
        if isinstance(sample_breaches, list) and sample_breaches:
            breach_samples += 1
            breaches.update(str(item) for item in sample_breaches)

        audit_record = sample.get("audit", {})
        audit_status = audit_record.get("status") if isinstance(audit_record, dict) else None
        audit = _body(sample, "audit")
        audit_ok = audit.get("valid", audit.get("ok", True))
        if audit_status != 200 or (audit and audit_ok is not True):
            audit_failures.append(str(sample.get("at", "unknown")))

        for name, state in _body(sample, "resilience").get("circuit_breakers", {}).items():
            current = state.get("state") if isinstance(state, dict) else state
            if str(current).lower() not in ("closed", "ok", "none"):
                breakers[str(name)] += 1
        log_errors = sample.get("log_errors", {})
        if isinstance(log_errors, dict):
            errors.update(
                {
                    str(key): int(value)
                    for key, value in log_errors.items()
                    if isinstance(value, int)
                }
            )

    return {
        "samples": len(samples),
        "window": {"first": samples[0].get("at"), "last": samples[-1].get("at")},
        "availability": {
            "health_ok": sum(
                1 for sample in samples if sample.get("health", {}).get("status") == 200
            ),
            "ready_ok": sum(
                1
                for sample in samples
                if sample.get("ready", {}).get("status") == 200
                and _body(sample, "ready").get("ready") is True
            ),
            "restarts_detected": restarts,
            "last_uptime_seconds": uptimes[-1] if uptimes else None,
        },
        "memory": {
            "first_rss": rss[0] if rss else None,
            "last_rss": rss[-1] if rss else None,
            "growth_bytes": rss[-1] - rss[0] if rss else None,
            "peak_rss": max(rss) if rss else None,
        },
        "database": {
            "first_bytes": db_sizes[0] if db_sizes else None,
            "last_bytes": db_sizes[-1] if db_sizes else None,
            "growth_bytes": db_sizes[-1] - db_sizes[0] if db_sizes else None,
            "wal_peak_bytes": max(wal_sizes) if wal_sizes else None,
        },
        "guardrails": {
            "samples_with_breaches": breach_samples,
            "breach_counts": dict(breaches),
        },
        "north_star": _body(samples[-1], "north_star"),
        "kernel": _body(samples[-1], "kernel"),
        "queue": _body(samples[-1], "queue"),
        "audit": {"failures": audit_failures, "last": _body(samples[-1], "audit")},
        "circuit_breakers_non_closed": dict(breakers),
        "capabilities": _body(samples[-1], "capabilities"),
        "error_signatures": dict(errors),
    }


def evaluate(
    summary: dict,
    *,
    thresholds: dict[str, float] | None = None,
    complete: bool = True,
) -> dict:
    """Grade a soak summary against the A2 bar.

    Returns ``PASS`` only when every check has evidence and every check clears.
    A check with no evidence (no RSS series because ``--pid`` was not supplied, say)
    is ``None`` and downgrades the window to ``INCONCLUSIVE`` — never to a quiet pass.
    """
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    samples = int(summary.get("samples", 0) or 0)
    availability = summary.get("availability", {})
    memory = summary.get("memory", {})
    database = summary.get("database", {})
    guardrails = summary.get("guardrails", {})
    audit_failures = summary.get("audit", {}).get("failures", []) or []
    breakers = summary.get("circuit_breakers_non_closed", {}) or {}

    checks: list[dict[str, Any]] = []

    def add(check_id: str, ok: bool | None, detail: str) -> None:
        checks.append({"id": check_id, "ok": ok, "detail": detail})

    add(
        "samples",
        samples >= limits["min_samples"],
        f"{samples} samples (need ≥ {int(limits['min_samples'])})",
    )
    add(
        "window_complete",
        True if complete else None,
        "collector reached the requested duration"
        if complete
        else "window ended early — not enough evidence to grade",
    )

    if samples:
        for name, key in (("availability_health", "health_ok"), ("availability_ready", "ready_ok")):
            ok_count = int(availability.get(key, 0) or 0)
            ratio = ok_count / samples
            add(
                name,
                ratio >= limits["min_availability"],
                f"{ok_count}/{samples} OK ({ratio:.3%}, need ≥ {limits['min_availability']:.1%})",
            )
    else:
        add("availability_health", None, "no samples")
        add("availability_ready", None, "no samples")

    restarts = int(availability.get("restarts_detected", 0) or 0)
    add(
        "restarts",
        restarts <= limits["max_restarts"],
        f"{restarts} restart(s) detected (allowed {int(limits['max_restarts'])})",
    )
    add(
        "audit_chain",
        len(audit_failures) <= limits["max_audit_failures"],
        f"{len(audit_failures)} sample(s) failed audit verification (AUD-0 allows "
        f"{int(limits['max_audit_failures'])})",
    )
    breach_samples = int(guardrails.get("samples_with_breaches", 0) or 0)
    add(
        "guardrails",
        breach_samples <= limits["max_breach_samples"],
        f"{breach_samples} sample(s) reported a guardrail breach "
        f"(allowed {int(limits['max_breach_samples'])})",
    )
    open_breakers = sum(int(value) for value in breakers.values() if isinstance(value, int))
    add(
        "circuit_breakers",
        open_breakers <= limits["max_breaker_samples"],
        f"{open_breakers} non-closed breaker sample(s) across {sorted(breakers)}"
        if breakers
        else "no breaker left its closed state",
    )

    first_rss, growth = memory.get("first_rss"), memory.get("growth_bytes")
    if (
        not isinstance(first_rss, (int, float))
        or not first_rss
        or not isinstance(growth, (int, float))
    ):
        add("memory_growth", None, "no RSS series (run with --pid to measure the server process)")
    else:
        ratio = growth / first_rss
        add(
            "memory_growth",
            ratio <= limits["max_rss_growth_ratio"],
            f"RSS grew {ratio:+.2%} ({int(growth):,} B, limit "
            f"{limits['max_rss_growth_ratio']:.0%})",
        )

    wal_peak = database.get("wal_peak_bytes")
    if not isinstance(wal_peak, (int, float)):
        add("wal_size", None, "no WAL series (check --data-dir)")
    else:
        add(
            "wal_size",
            wal_peak <= limits["max_wal_bytes"],
            f"WAL peaked at {int(wal_peak):,} B (limit {int(limits['max_wal_bytes']):,} B)",
        )

    failed = [check["id"] for check in checks if check["ok"] is False]
    unknown = [check["id"] for check in checks if check["ok"] is None]
    verdict = FAIL if failed else (INCONCLUSIVE if unknown else PASS)
    return {
        "verdict": verdict,
        "checks": checks,
        "failed": failed,
        "inconclusive": unknown,
        "thresholds": limits,
    }


_VERDICT_EXIT = {PASS: 0, FAIL: 1, INCONCLUSIVE: 3}
_VERDICT_MARK = {True: "✅", False: "❌", None: "❔"}


def _fmt_bytes(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unavailable"
    return f"{int(value):,} B"


def render_report(
    summary: dict,
    *,
    generated_at: str,
    meta: dict,
    partial: bool = False,
    verdict: dict | None = None,
) -> str:
    """Render the human-readable evidence companion to the raw JSONL samples."""
    availability = summary.get("availability", {})
    memory = summary.get("memory", {})
    database = summary.get("database", {})
    guardrails = summary.get("guardrails", {})
    audit = summary.get("audit", {})
    lines = [
        f"# Soak report — {generated_at[:10]}",
        "",
        "> **Partial window.** The requested soak did not reach its full duration."
        if partial
        else "> Complete collector window.",
        "",
        f"Generated: `{generated_at}` · samples: **{summary.get('samples', 0)}** · "
        f"interval: **{meta.get('interval')}s** · source: `{meta.get('base_url')}`",
        "",
    ]
    if verdict is not None:
        lines += [
            f"## Verdict — **{verdict.get('verdict', INCONCLUSIVE)}**",
            "",
            "Graded automatically against the A2 thresholds; no owner sign-off step.",
            "",
            *[
                f"- {_VERDICT_MARK[check['ok']]} `{check['id']}` — {check['detail']}"
                for check in verdict.get("checks", [])
            ],
            "",
        ]
    lines += [
        "## Availability & restarts",
        "",
        f"- Health samples OK: **{availability.get('health_ok', 0)}/{summary.get('samples', 0)}**",
        f"- Ready samples OK: **{availability.get('ready_ok', 0)}/{summary.get('samples', 0)}**",
        f"- Restarts detected: **{availability.get('restarts_detected', 0)}**",
        f"- Last uptime: **{availability.get('last_uptime_seconds')} seconds**",
        "",
        "## Process memory",
        "",
        f"- First / last RSS: {_fmt_bytes(memory.get('first_rss'))} / {_fmt_bytes(memory.get('last_rss'))}",
        f"- Growth / peak: {_fmt_bytes(memory.get('growth_bytes'))} / {_fmt_bytes(memory.get('peak_rss'))}",
        "",
        "## SQLite & WAL",
        "",
        f"- Database growth: {_fmt_bytes(database.get('growth_bytes'))}",
        f"- WAL peak: {_fmt_bytes(database.get('wal_peak_bytes'))}",
        "",
        "## Guardrails",
        "",
        f"- Samples with breaches: **{guardrails.get('samples_with_breaches', 0)}**",
        f"- Breach counts: `{json.dumps(guardrails.get('breach_counts', {}), sort_keys=True)}`",
        "",
        "## North-star",
        "",
        f"```json\n{json.dumps(summary.get('north_star', {}), indent=2, ensure_ascii=False)}\n```",
        "",
        "## Queue & kernel",
        "",
        f"```json\n{json.dumps({'queue': summary.get('queue', {}), 'kernel': summary.get('kernel', {})}, indent=2, ensure_ascii=False)}\n```",
        "",
        "## Audit-chain",
        "",
        f"- Failed verification samples: `{json.dumps(audit.get('failures', []))}`",
        "",
        "## Circuit breakers & plugin capability failures",
        "",
        f"- Non-closed breaker samples: `{json.dumps(summary.get('circuit_breakers_non_closed', {}), sort_keys=True)}`",
        f"- Latest capability snapshot: `{json.dumps(summary.get('capabilities', {}), sort_keys=True)}`",
        "",
        "## Error signatures",
        "",
        "Only redacted, collapsed signatures are retained; raw log lines and paths are not copied.",
        "",
    ]
    signatures = summary.get("error_signatures", {})
    lines.extend(
        [f"- **{count}×** `{signature}`" for signature, count in sorted(signatures.items())]
        or ["- None observed."]
    )
    return "\n".join(lines) + "\n"


def load_samples(path: Path) -> list[dict]:
    """Load durable JSONL, ignoring torn lines from an interrupted final write."""
    samples = []
    if not path.exists():
        return samples
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            samples.append(value)
    return samples


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--duration", default="72h")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--admin-token", default=os.environ.get("JARVIS_ADMIN_TOKEN", ""))
    parser.add_argument(
        "--pid",
        type=int,
        help="Jarvis server PID used for process-RSS evidence. Omitted: the leak check "
        "reports INCONCLUSIVE rather than measuring the collector's own process.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--fail-on-verdict",
        action="store_true",
        help=f"Exit {_VERDICT_EXIT[FAIL]} on {FAIL} and {_VERDICT_EXIT[INCONCLUSIVE]} on "
        f"{INCONCLUSIVE}, so an unattended runner can gate on the soak.",
    )
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    duration = parse_duration(args.duration)
    interval = parse_duration(args.interval)
    if interval <= 0 or duration <= 0:
        parser.error("duration and interval must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).date().isoformat()
    sample_path = args.output_dir / f"{day}-soak-samples.jsonl"
    report_path = args.output_dir / f"{day}-soak-report.md"
    verdict_path = args.output_dir / f"{day}-soak-verdict.json"
    fetch = http_fetcher(args.base_url, admin_token=args.admin_token)
    started = time.monotonic()
    interrupted = False
    try:
        while True:
            sample = collect_sample(
                fetch,
                mem_reader=(
                    (lambda: process_memory(args.pid))
                    if args.pid
                    else (lambda: {"rss_bytes": None, "source": "not_configured"})
                ),
                db_reader=lambda: sqlite_sizes(args.data_dir),
                log_reader=lambda: read_log_errors(args.log),
            )
            with sample_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            elapsed = time.monotonic() - started
            if elapsed >= duration:
                break
            time.sleep(min(interval, duration - elapsed))
    except KeyboardInterrupt:
        interrupted = True

    samples = load_samples(sample_path)
    summary = summarize(samples)
    partial = interrupted or (time.monotonic() - started < duration)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    verdict = evaluate(summary, complete=not partial)
    report = render_report(
        summary,
        generated_at=generated_at,
        meta={"interval": interval, "duration": duration, "base_url": args.base_url},
        partial=partial,
        verdict=verdict,
    )
    report_path.write_text(report, encoding="utf-8", newline="\n")
    verdict_path.write_text(
        json.dumps(
            {"generated_at": generated_at, "samples": summary.get("samples", 0), **verdict},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"samples: {sample_path}")
    print(f"report:  {report_path}")
    print(f"verdict: {verdict_path} -> {verdict['verdict']}")
    for check in verdict["checks"]:
        print(f"  {_VERDICT_MARK[check['ok']]} {check['id']}: {check['detail']}")
    if interrupted:
        return 130
    return _VERDICT_EXIT[verdict["verdict"]] if args.fail_on_verdict else 0


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
