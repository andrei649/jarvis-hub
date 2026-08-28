"""
digest.py — Daily Review Ritual (H6.4).

Pure builders for the morning brief and evening retro, rendered from the task
queue. Network-free so they're unit-testable; the orchestrator schedules them
(cron 07:00 / 20:00) and ships the text via Telegram, and the HUD reads the
same text via GET /autonomy/brief.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import List

from .followups import build_caring_followups
from .queue import Task, TaskQueue

_TIER = {0: "read-only", 1: "reversibil", 2: "extern", 3: "ireversibil/bani"}
_WINDOW_HOURS = 24


def _updated_epoch(iso: str):
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:  # treat a naive timestamp as UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _recent(tasks: List[Task], now, *, hours: int = _WINDOW_HOURS) -> List[Task]:
    """Keep only tasks updated within the trailing window.

    DONE/FAILED are terminal and accumulate forever, so without a window the
    daily ritual would re-render the same 50 old tasks as 'done overnight' /
    'delivered today'. A task whose timestamp can't be parsed is kept (fail-open).
    """
    now = time.time() if now is None else float(now)
    cutoff = now - hours * 3600
    kept = []
    for t in tasks:
        epoch = _updated_epoch(getattr(t, "updated_at", "") or "")
        if epoch is None or epoch >= cutoff:
            kept.append(t)
    return kept


def _titles(tasks: List[Task], limit: int = 8) -> str:
    if not tasks:
        return "  _(niciuna)_"
    lines = [f"  • {t.title} `#{t.id}`" for t in tasks[:limit]]
    if len(tasks) > limit:
        lines.append(f"  • …și încă {len(tasks) - limit}")
    return "\n".join(lines)


def build_morning_brief(
    queue: TaskQueue, memory_entries=None, *, now=None, runtime_health=None,
    signal_briefs=None,
) -> str:
    """What Jarvis did overnight, what it proposes today, and open decisions.

    ``runtime_health`` is the optional loop-health summary from
    ``agents.core.observability.runtime_log.read_runtime_health`` (H23.29). The
    caller reads it so this builder stays pure/network-free; omitting it leaves
    the brief byte-identical to before the runtime supervisor existed.

    ``signal_briefs`` (T-0.41) is an optional list of per-domain briefs, exactly
    as ``signal_routing.build_domain_brief`` returns them. Same convention and
    same reason: the caller fetches from the Signal Layer sidecar, this stays
    pure. Omitting it — the default, and the only possibility without a
    configured sidecar — leaves the brief byte-identical.
    """
    done = _recent(queue.list(status="done", limit=50), now)
    approved = queue.list(status="approved", limit=50)
    proposed = queue.list(status="proposed", limit=50)
    pending = queue.pending_decisions(limit=50)
    followups = build_caring_followups(queue, memory_entries, now=now, limit=8)

    parts = [
        "☀️ *Morning brief*",
        "",
        f"✅ *Făcute peste noapte* ({len(done)}):",
        _titles(done),
        "",
        f"⏳ *În lucru azi* ({len(approved)}):",
        _titles(approved),
    ]
    if proposed:
        parts += ["", f"💡 *Propuneri noi* ({len(proposed)}):", _titles(proposed)]
    if pending:
        parts += [
            "",
            f"🔔 *Așteaptă decizia ta* ({len(pending)}):",
            _decisions(pending),
        ]
    if followups:
        parts += [
            "",
            f"🤝 *Follow-ups* ({len(followups)}):",
            _followups(followups),
        ]
    signal_lines = _signal_briefs(signal_briefs)
    if signal_lines:
        parts += ["", "🌍 *Semnale externe*:", signal_lines]
    runtime_line = _runtime_health(runtime_health)
    if runtime_line:
        parts += ["", "🫀 *Runtime*:", runtime_line]
    return "\n".join(parts)


def build_evening_retro(queue: TaskQueue, *, now=None) -> str:
    """Delivered / failed / blocked, plus a batch-approve list for tomorrow."""
    done = _recent(queue.list(status="done", limit=50), now)
    failed = _recent(queue.list(status="failed", limit=50), now)
    pending = queue.pending_decisions(limit=50)

    parts = [
        "🌙 *Evening retro*",
        "",
        f"✅ *Livrate azi* ({len(done)}):",
        _titles(done),
    ]
    if failed:
        parts += ["", f"❌ *Eșuate* ({len(failed)}):", _titles(failed)]
    if pending:
        parts += [
            "",
            f"📋 *Batch approve pentru mâine* ({len(pending)}):",
            _decisions(pending),
            "",
            "_Aprobă din inbox sau spune-mi ce să rulez._",
        ]
    else:
        parts += ["", "_Nicio decizie în așteptare. 🎉_"]
    return "\n".join(parts)


def _decisions(tasks: List[Task], limit: int = 12) -> str:
    lines = []
    for t in tasks[:limit]:
        lines.append(f"  • `#{t.id}` {t.title} — *{_TIER.get(t.risk_tier, t.risk_tier)}*")
    if len(tasks) > limit:
        lines.append(f"  • …și încă {len(tasks) - limit}")
    return "\n".join(lines)


def _followups(items: list[dict], limit: int = 8) -> str:
    lines = []
    for item in items[:limit]:
        title = item.get("title") or "Follow-up"
        detail = item.get("detail") or ""
        if item.get("source") == "task":
            ident = f" `#{item.get('id')}`" if item.get("id") is not None else ""
            lines.append(f"  • {title}{ident} — {detail}")
        elif detail:
            lines.append(f"  • {title}: {detail}")
        else:
            lines.append(f"  • {title}")
    if len(items) > limit:
        lines.append(f"  • …și încă {len(items) - limit}")
    return "\n".join(lines)


_SIGNAL_TOP_PER_DOMAIN = 3


def _signal_briefs(briefs) -> str:
    """Per-domain world-signal lines for the morning brief (T-0.41).

    Returns "" when there is nothing to say — no sidecar configured, an
    unreachable one, or simply a quiet day. That silence is deliberate: an empty
    "Semnale externe" heading would imply the feed was consulted and found calm,
    which is exactly the kind of unearned reassurance the digest must not give.

    Never raises: the payload comes from an external sidecar, so a malformed
    entry is skipped rather than allowed to take the whole brief down with it.
    """
    if not isinstance(briefs, (list, tuple)):
        return ""
    lines: list[str] = []
    for brief in briefs:
        if not isinstance(brief, dict):
            continue
        domain = str(brief.get("domain") or "").strip()
        try:
            count = int(brief.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if not domain or count <= 0:
            continue          # a domain with no signals is not news
        lines.append(f"  *{domain}* — {count} semnal(e)")
        top = brief.get("top")
        if not isinstance(top, (list, tuple)):
            continue          # count still stands; we just have no titles to show
        for item in list(top)[:_SIGNAL_TOP_PER_DOMAIN]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if title:
                lines.append(f"    · {title[:120]}")
    return "\n".join(lines)


def _runtime_health(health) -> str:
    """One line on whether the always-on loop is actually ticking (H23.29).

    Returns "" when there is nothing to say — no summary passed, or no run-log
    on disk because the supervisor was never started. A *stale* last cycle is
    the case worth shouting about: the supervisor can die without writing a
    failure line, so a fresh-looking `ok: true` tail proves nothing on its own.
    """
    if not isinstance(health, dict) or not health.get("present"):
        return ""
    cycle = health.get("cycle")
    if cycle is None:
        return "  ⚠️ supervisor pornit, dar niciun ciclu încă"

    age = health.get("age_s")
    age_txt = f"{int(age // 60)}m" if isinstance(age, (int, float)) and age >= 60 else (
        f"{int(age)}s" if isinstance(age, (int, float)) else "necunoscut"
    )
    if health.get("stale"):
        head = f"  ⚠️ buclă *oprită* — ultimul ciclu `#{cycle}` acum {age_txt}"
    elif not health.get("last_ok"):
        err = (health.get("last_error") or "").strip()
        head = f"  ❌ ultimul ciclu `#{cycle}` a eșuat" + (f": {err[:120]}" if err else "")
    else:
        head = f"  ✅ buclă activă — ciclul `#{cycle}`, ultimul acum {age_txt}"

    notes = []
    failures = health.get("failures") or 0
    respawns = health.get("respawns") or 0
    if failures:
        notes.append(f"{failures} cicluri eșuate/24h")
    if respawns:
        notes.append(f"{respawns} reporniri/24h")
    return head + (f" ({', '.join(notes)})" if notes else "")
