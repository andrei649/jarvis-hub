"""timeline.py — unified "Today in Jarvis" feed (P1 proof-gap G1).

Fuses what Jarvis *did* (autonomy tasks that reached ``done``) with what it
*learned* (new / updated memory facts & preferences) into one timestamp-ordered
feed. Before this, ``autonomy/digest.py`` (task recap) and ``memory/digest.py``
(learnings) were **separate** — nothing showed "did *and* learned" as a single
chronological story, so theme 0.38's "Today in Jarvis" had no backing surface.

Pure builder over injected data (a ``TaskQueue`` + already-read memory rows), so
it unit-tests offline with no async, network, or real store — the same discipline
as ``observability/north_star.py``. Reuses existing rows: **no new capture, no
schema, no behaviour change.**

H046 — every item carries a stable ``entry_id`` (Hermes ``hermes journey`` lists,
edits and deletes individual nodes). The id names the row an item is read from,
never its text: ``learning:<memory row id>`` (SQLite ``AUTOINCREMENT``: it survives
an edit of the value and is never handed to another fact after a delete),
``action:<task id>``, and ``followup:<reason>:<source>`` for a derived follow-up,
where ``<source>`` is ``task:<id>`` or the ``learning:<id>`` it was read from.
Only a learning is learned material; the routes that read, change and delete one
by its id are in ``routers/dashboard.py`` and cross ``kg.write``.

H046 review — what the assistant really learns is held in three stores, and each is a
``learning`` here with its own id (``store`` says which):

* the two curated rings every prompt carries (Hermes's ``MEMORY.md`` / ``USER.md``
  cards, ``cognition.memory.CoreMemory``: the agent's notes and the user profile, which
  the model's ``memory`` tool, the post-turn review and the daily reflection write):
  ``memory:<memory|user>:<digest>``. A ring keeps no time per fact, so a fact carries the
  time its ring was last saved, as Hermes dates a card by its file's mtime, and its place
  in the ring orders it. The digest is a keyed hash of the fact under a key drawn when
  the process starts and never written down: stable while the hub runs (``journey
  list`` then ``journey edit``), and no log that outlives a forget can be matched back
  to a short fact (the memory tool keeps no hash of a fact in the intent log either). An
  id read before a restart answers "not found": list again;
* the skills it learned (Hermes's agent-created or used skills): ``skill:<name>``, dated
  by its last use, view or patch (else when the sidecar first saw it, else its
  ``SKILL.md``), as Hermes dates a skill node;
* the structured fact store (``memory/store.py``): ``learning:<row id>``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, datetime

from agents.core.autonomy.followups import build_caring_followups

_DAY_SECONDS = 86_400

#: The kinds an item can be, in the feed and in an ``entry_id``.
ENTRY_KINDS = ("action", "learning", "followup")
#: SQLite's largest rowid: a bigger number is no row's id.
_MAX_ROW_ID = 2**63 - 1
_ROW_ID = r"[1-9][0-9]{0,18}"
_ENTRY_ID = re.compile(
    rf"(?P<kind>action|learning):(?P<row>{_ROW_ID})"
    rf"|followup:(?P<reason>[a-z_]{{1,40}}):(?P<source>(?:task|learning):{_ROW_ID})"
    r"|memory:(?P<ring>memory|user):(?P<digest>[0-9a-f]{16})"
    # A skill's registered name: its manifest's (a generated skill's is a title, with
    # spaces), never a control character or a path separator, at most 128 characters.
    r"|skill:(?P<skill>[^\x00-\x20\x7f/\\](?:[^\x00-\x1f\x7f/\\]{0,126}[^\x00-\x20\x7f/\\])?)"
)
#: H046 review — where a learned entry is kept: the fact store, a curated ring (``memory``:
#: the agent's notes, ``user``: the user profile) or the skill library.
LEARNED_STORES = ("facts", "memory", "user", "skill")
#: Each ring in the owner's words (``memory_tool.STORE_LABELS``).
RING_LABELS = {"memory": "agent notes", "user": "user profile"}
#: The key of a ring fact's id: drawn per process, never stored (see the module doc).
_FACT_ID_KEY = secrets.token_bytes(32)


def _row_ref(value) -> str | None:
    """The decimal text of a positive SQLite row id, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= _MAX_ROW_ID:
        return None
    return str(value)


def learning_entry_id(row_id) -> str | None:
    """``learning:<row id>`` for a memory row, or None when the row carries no id."""
    ref = _row_ref(row_id)
    return f"learning:{ref}" if ref else None


def ring_fact_id(target: str, fact: str) -> str:
    """``memory:<target>:<digest>`` for one fact of a curated ring (see the module doc)."""
    digest = hmac.new(_FACT_ID_KEY, f"{target}\n{fact}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"memory:{target}:{digest}"


def skill_entry_id(name) -> str | None:
    """``skill:<name>``, or None for a name an id cannot carry."""
    entry_id = f"skill:{name}" if isinstance(name, str) else None
    return entry_id if entry_id and _ENTRY_ID.fullmatch(entry_id) else None


def parse_entry_id(entry_id) -> tuple[str, str] | None:
    """``(kind, ref)`` for a well-formed entry id, else None.

    ``ref`` is the row id (as text) of an action or a learning; for a follow-up it is
    the entry the follow-up was derived from (``task:<id>`` or ``learning:<id>``); for a
    ring fact (kind ``memory``) it is ``<target>:<digest>``; for a skill, its name.
    """
    if not isinstance(entry_id, str):
        return None
    m = _ENTRY_ID.fullmatch(entry_id)
    if m is None:
        return None
    if m.group("ring"):
        return "memory", f"{m.group('ring')}:{m.group('digest')}"
    if m.group("skill"):
        return "skill", m.group("skill")
    if m.group("kind"):
        kind, ref, number = m.group("kind"), m.group("row"), m.group("row")
    else:
        kind, ref = "followup", m.group("source")
        number = ref.split(":", 1)[1]
    return (kind, ref) if int(number) <= _MAX_ROW_ID else None


def _ts_epoch(value) -> float | None:
    """Epoch seconds for an ISO / SQLite timestamp; naive stamps are read as UTC.

    Handles both the autonomy queue's tz-aware ISO (``…+00:00``) and the memory
    store's SQLite ``datetime('now')`` form (``'YYYY-MM-DD HH:MM:SS'``, naive UTC).
    Returns None when unparseable.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _iso(epoch) -> str | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat()


def learning_item(row: dict) -> dict:
    """One memory row as the feed shows it — also what the entry routes answer."""
    ts = row.get("updated_at") or row.get("created_at")
    category, key = row.get("category"), row.get("key")
    return {
        "entry_id": learning_entry_id(row.get("id")),
        "ts": ts,
        "epoch": _ts_epoch(ts),
        "kind": "learning",
        "store": "facts",
        "label": "/".join(str(part) for part in (category, key) if part),
        "category": category,
        "key": key,
        "value": row.get("value"),
    }


def ring_items(target: str, facts, saved_epoch=None) -> list[dict]:
    """The facts of curated ring *target* (``memory`` | ``user``), oldest first, as the
    feed shows them. *saved_epoch* is when the ring's file was last written (None: no
    file yet): the time every fact of it carries, its place in the ring (``order``)
    ordering them, as Hermes dates its memory cards."""
    label = RING_LABELS[target]
    out = []
    for position, fact in enumerate(facts or ()):
        if not isinstance(fact, str) or not fact:
            continue
        out.append({
            "entry_id": ring_fact_id(target, fact),
            "ts": _iso(saved_epoch),
            "epoch": float(saved_epoch) if _iso(saved_epoch) else None,
            "order": position,
            "kind": "learning",
            "store": target,
            "label": label,
            "category": target,
            "key": None,
            "value": fact,
        })
    return out


def skill_item(name: str, usage: dict | None = None, *, description: str = "", file_epoch=None) -> dict:
    """One learned skill as the feed shows it. *usage* is its usage-sidecar record (the
    counters, ``origin``, ``pinned``, ``state``); its time is the latest use, view, patch
    or switch-on, else ``created_at``, else *file_epoch* (its ``SKILL.md``), as Hermes
    dates a skill node."""
    from agents.core.skills.usage import latest_activity_at

    rec = usage if isinstance(usage, dict) else {}
    latest = latest_activity_at(rec)
    epoch = latest.timestamp() if latest is not None else _ts_epoch(rec.get("created_at"))
    if epoch is None and _iso(file_epoch):
        epoch = float(file_epoch)
    try:
        uses = int(rec.get("use_count") or 0)
    except (TypeError, ValueError):
        uses = 0
    return {
        "entry_id": skill_entry_id(name),
        "ts": _iso(epoch),
        "epoch": epoch,
        "kind": "learning",
        "store": "skill",
        "label": name,
        "category": "skill",
        "key": name,
        "value": description or "",
        "origin": str(rec.get("origin") or "bundled"),
        "use_count": uses,
        "pinned": bool(rec.get("pinned")),
        "state": str(rec.get("state") or "active"),
    }


def _order(item: dict) -> tuple:
    """Oldest first: an undated entry before every dated one (Hermes sorts it as 0), then
    by time, then by its place in its ring."""
    epoch = item.get("epoch")
    return (epoch is not None, epoch or 0.0, item.get("order") or 0)


def journey_entries(memory_entries=None, learned=None, *, store=None) -> list[dict]:
    """Every learned entry, whatever its age, oldest first (Hermes's ``journey list``):
    the fact store's rows (*memory_entries*) and the ring facts and skills already shaped
    by :func:`ring_items` / :func:`skill_item` (*learned*). *store* keeps one store."""
    items = [learning_item(e) for e in (memory_entries or [])]
    items.extend(dict(it) for it in (learned or []))
    if store is not None:
        items = [it for it in items if it.get("store") == store]
    items.sort(key=_order)
    return items


def build_unified_digest(queue, memory_entries=None, *, now=None, days=1, limit=50, kind=None,
                         learned=None) -> dict:
    """One timestamp-ordered feed of done-tasks + new memory facts in the window.

    Parameters
    ----------
    queue:
        An autonomy ``TaskQueue`` (or None). Source of completed actions
        (``status="done"``, windowed by ``updated_at`` — when the action finished).
    memory_entries:
        An iterable of memory-store row dicts (or None) — typically
        ``MemoryStore.get_all()`` flattened. Each carries
        ``id`` / ``category`` / ``key`` / ``value`` / ``updated_at``. A *learning*
        is windowed by ``updated_at`` (when the fact was recorded or changed).
    now, days:
        Trailing-window reference epoch (default ``time.time()``) and length
        (default 1 = "today"); clamped to ≥1 day.
    limit:
        Max items returned (newest first). ``counts`` reflects the full in-window
        set, not the truncated list.
    kind:
        Keep only the items of this kind (``action`` | ``learning`` | ``followup``)
        before ``limit`` applies; None keeps every kind. ``counts`` is unchanged.
    learned:
        H046 review — the curated rings' facts and the learned skills, shaped by
        :func:`ring_items` / :func:`skill_item`: learnings too, windowed by their time.

    Returns a JSON-safe dict: ``period`` / ``days`` / ``generated_at`` /
    ``counts`` / ``items``. Every item carries ``entry_id`` / ``ts`` / ``epoch`` /
    ``kind`` (``action`` | ``learning`` | ``followup``) plus its kind-specific
    fields; ``entry_id`` is None only for a row that has no id to name.
    """
    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    cutoff = now - days * _DAY_SECONDS

    items: list[dict] = []

    # ── what Jarvis *did* (completed autonomy actions) ──────────────────────
    if queue is not None:
        try:
            done = queue.list(status="done", limit=500)
        except Exception:
            done = []
        for t in done:
            ep = _ts_epoch(getattr(t, "updated_at", None))
            if ep is not None and ep < cutoff:
                continue
            ref = _row_ref(getattr(t, "id", None))
            items.append({
                "entry_id": f"action:{ref}" if ref else None,
                "ts": getattr(t, "updated_at", None),
                "epoch": ep,
                "kind": "action",
                "title": getattr(t, "title", None),
                "id": getattr(t, "id", None),
                "tier": getattr(t, "risk_tier", None),
                "agent": getattr(t, "agent_id", None) or getattr(t, "agent", None),
            })

    # ── what Jarvis *learned* (new / updated facts & preferences) ───────────
    learned_ids: dict[tuple, str] = {}
    for e in (memory_entries or []):
        item = learning_item(e)
        if item["entry_id"]:
            learned_ids[(item["category"], item["key"])] = item["entry_id"]
        if item["epoch"] is not None and item["epoch"] < cutoff:
            continue
        items.append(item)
    for item in (learned or []):
        if item.get("epoch") is not None and item["epoch"] < cutoff:
            continue
        items.append(dict(item))

    for f in build_caring_followups(queue, memory_entries, now=now, days=days, limit=500):
        if f.get("source") == "task":
            ref = _row_ref(f.get("id"))
            source = f"task:{ref}" if ref else None
        else:
            source = learned_ids.get((f.get("category"), f.get("key")))
        reason = f.get("kind")
        items.append({
            "entry_id": f"followup:{reason}:{source}" if source and reason else None,
            "ts": f.get("ts"),
            "epoch": f.get("epoch"),
            "kind": "followup",
            "reason": reason,
            "source": f.get("source"),
            "title": f.get("title"),
            "detail": f.get("detail"),
            "id": f.get("id"),
            "category": f.get("category"),
            "key": f.get("key"),
        })

    # Newest first. Unparseable timestamps (epoch None) sink to the bottom but are
    # never dropped — a real row with a bad stamp still shows (honesty over tidiness).
    items.sort(key=_order, reverse=True)

    actions = sum(1 for it in items if it["kind"] == "action")
    learnings = sum(1 for it in items if it["kind"] == "learning")
    followups = sum(1 for it in items if it["kind"] == "followup")
    counts = {"actions": actions, "learnings": learnings, "total": len(items)}
    if followups:
        counts["followups"] = followups
    shown = items if kind is None else [it for it in items if it["kind"] == kind]
    return {
        "period": "today" if days == 1 else f"{days}d",
        "days": days,
        "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
        "counts": counts,
        "items": shown[:limit],
    }
