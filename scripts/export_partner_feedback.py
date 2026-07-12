#!/usr/bin/env python3
"""Create an explicit, local-only design-partner evidence packet (H23.27)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(
    os.environ.get("JARVIS_HOME", "").strip()
    or os.environ.get("JARVIS_MEMORY_DIR", "").strip()
    or REPO / "memory_logs"
)
_ENVIRONMENT_KEYS = (
    "app_version",
    "os",
    "os_version",
    "python",
    "architecture",
    "system_profile",
)
_NORTH_STAR_KEYS = {
    "period",
    "days",
    "north_star",
    "night_shift",
    "counter_metrics",
    "guardrail_breaches",
    "guardrails_ok",
    "interrupt_budget",
    "proposal_funnel",
    "raw",
}
_FORBIDDEN_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "conversation",
    "prompt",
    "preview",
    "payload",
    "session_id",
    "api_key",
)


def sanitize_environment(source: dict) -> dict:
    return {key: source[key] for key in _ENVIRONMENT_KEYS if source.get(key) not in (None, "")}


def _safe_aggregate(value: Any) -> Any:
    """Copy aggregate JSON while dropping credential/content-shaped keys."""
    if isinstance(value, dict):
        return {
            str(key): _safe_aggregate(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _FORBIDDEN_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_safe_aggregate(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sanitize_north_star(source: dict) -> dict:
    if not isinstance(source, dict):
        return {}
    return _safe_aggregate({key: source[key] for key in _NORTH_STAR_KEYS if key in source})


def _readonly_rows(path: Path, query: str) -> list[sqlite3.Row]:
    if not path.exists():
        return []
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query).fetchall()
    except sqlite3.Error:
        return []


def read_feedback_rows(path: Path) -> list[dict]:
    rows = _readonly_rows(
        path, "SELECT kind, score, message FROM feedback ORDER BY id ASC LIMIT 1000"
    )
    return [{"kind": row["kind"], "score": row["score"], "message": row["message"]} for row in rows]


def read_autonomy_rows(path: Path) -> list[dict]:
    rows = _readonly_rows(path, "SELECT status FROM tasks ORDER BY id ASC LIMIT 100000")
    return [{"status": row["status"]} for row in rows]


def read_analytics_events(path: Path) -> list[dict]:
    rows = _readonly_rows(
        path, "SELECT name FROM events WHERE name LIKE 'funnel.%' ORDER BY id ASC LIMIT 100000"
    )
    return [{"name": row["name"]} for row in rows]


def read_run_rows(path: Path) -> list[dict]:
    """Read only success and latency; previews are never copied into memory output."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    if isinstance(raw, dict):
        for agent_runs in raw.values():
            if not isinstance(agent_runs, list):
                continue
            for run in agent_runs:
                if not isinstance(run, dict):
                    continue
                try:
                    latency = float(run.get("latency_ms", 0))
                except (TypeError, ValueError):
                    latency = 0.0
                rows.append({"ok": bool(run.get("ok")), "latency_ms": latency})
    return rows


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 1)


def _onboarding(events: list[dict]) -> dict:
    seen = []
    completed = []
    for event in events:
        name = str(event.get("name", ""))
        match = re.fullmatch(r"funnel\.([a-z0-9_-]+)\.([a-z0-9_-]+)", name)
        if not match:
            continue
        step, action = match.groups()
        if step not in seen:
            seen.append(step)
        if action in ("complete", "completed", "done") and step not in completed:
            completed.append(step)
    return {
        "seen_steps": seen,
        "completed_steps": completed,
        "complete": bool(seen) and seen == completed,
    }


def _autonomy(rows: list[dict]) -> dict:
    statuses = [str(row.get("status", "")).lower() for row in rows]
    return {
        "accepted": statuses.count("done"),
        "rejected": statuses.count("rejected"),
        "failed": statuses.count("failed"),
        "total": len(statuses),
    }


def _reliability(rows: list[dict]) -> dict:
    latencies = []
    failures = 0
    for row in rows:
        if row.get("ok") is not True:
            failures += 1
        value = row.get("latency_ms")
        if isinstance(value, (int, float)) and value >= 0:
            latencies.append(float(value))
    return {
        "runs": len(rows),
        "failures": failures,
        "failure_rate": round(failures / len(rows), 4) if rows else None,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
    }


def _feedback(rows: list[dict]) -> dict:
    scores = [
        int(row["score"])
        for row in rows
        if row.get("kind") == "nps" and isinstance(row.get("score"), int)
    ]
    promoters = sum(1 for score in scores if score >= 9)
    detractors = sum(1 for score in scores if score <= 6)
    by_kind: dict[str, int] = {}
    written = []
    for row in rows:
        kind = str(row.get("kind", "comment"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if row.get("message"):
            written.append(
                {
                    "kind": kind,
                    "score": row.get("score"),
                    "message": str(row["message"])[:4000],
                }
            )
    return {
        "nps": round((promoters - detractors) / len(scores) * 100) if scores else None,
        "responses": len(scores),
        "promoters": promoters,
        "detractors": detractors,
        "by_kind": by_kind,
        "written": written,
    }


def build_packet(
    *,
    environment: dict,
    analytics_events: list[dict],
    autonomy_rows: list[dict],
    run_rows: list[dict],
    feedback_rows: list[dict],
    north_star: dict,
    generated_at: str,
) -> dict:
    return {
        "meta": {
            "schema": "jarvis-design-partner-export/v1",
            "generated_at": generated_at,
            "local_generation_only": True,
            "conversation_content_included": False,
            "excluded": [
                "conversation content",
                "prompts and responses",
                "autonomy task titles and payloads",
                "credentials and tokens",
                "hostnames, usernames, paths, and session identifiers",
            ],
        },
        "environment": sanitize_environment(environment),
        "onboarding": _onboarding(analytics_events),
        "autonomy": _autonomy(autonomy_rows),
        "reliability": _reliability(run_rows),
        "feedback": _feedback(feedback_rows),
        "north_star": sanitize_north_star(north_star),
    }


def render_markdown(packet: dict) -> str:
    meta = packet["meta"]
    lines = [
        "# Design-partner feedback export",
        "",
        f"Generated: `{meta['generated_at']}` · schema: `{meta['schema']}`",
        "",
        "## Privacy boundary",
        "",
        "**No conversation content is included.** This packet was generated locally and is not sent anywhere automatically.",
        "Excluded: " + "; ".join(meta["excluded"]) + ".",
        "",
        "## Install environment",
        "",
        f"```json\n{json.dumps(packet['environment'], indent=2, ensure_ascii=False)}\n```",
        "",
        "## Onboarding",
        "",
        f"```json\n{json.dumps(packet['onboarding'], indent=2, ensure_ascii=False)}\n```",
        "",
        "## Autonomous actions & reliability",
        "",
        f"```json\n{json.dumps({'autonomy': packet['autonomy'], 'reliability': packet['reliability']}, indent=2, ensure_ascii=False)}\n```",
        "",
        "## Feedback",
        "",
        f"```json\n{json.dumps(packet['feedback'], indent=2, ensure_ascii=False)}\n```",
        "",
        "## North-star",
        "",
        f"```json\n{json.dumps(packet['north_star'], indent=2, ensure_ascii=False)}\n```",
        "",
    ]
    return "\n".join(lines)


def _app_version() -> str:
    text = (REPO / "agents" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text)
    return match.group(1) if match else "unknown"


def install_environment() -> dict:
    return {
        "app_version": _app_version(),
        "os": platform.system(),
        "os_version": platform.release(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "system_profile": os.environ.get("JARVIS_SYSTEM_PROFILE", "balanced"),
    }


def fetch_north_star(base_url: str, timeout: float = 10) -> dict:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base URL must use http:// or https://")
    request = urllib.request.Request(  # noqa: S310
        f"{base_url.rstrip('/')}/api/metrics/north-star", headers={"Accept": "application/json"}
    )
    try:
        # Operator-selected endpoint; scheme was restricted to HTTP(S) above.
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            request, timeout=timeout
        ) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output_dir", type=Path, help="local directory to receive the JSON/MD pair")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args(argv)
    packet = build_packet(
        environment=install_environment(),
        analytics_events=read_analytics_events(args.data_root / "analytics.db"),
        autonomy_rows=read_autonomy_rows(args.data_root / "autonomy.db"),
        run_rows=read_run_rows(args.data_root / "run_history.json"),
        feedback_rows=read_feedback_rows(args.data_root / "feedback.db"),
        north_star=fetch_north_star(args.base_url),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(UTC).date().isoformat()}-partner-feedback"
    json_path = args.output_dir / f"{stem}.json"
    md_path = args.output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_path.write_text(render_markdown(packet), encoding="utf-8", newline="\n")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print("Nothing was uploaded; share only the files you explicitly choose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
