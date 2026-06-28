"""pack.py — 0.43 Learning Coach Pack (spaced repetition + curriculum planning).

A pure, offline, **stateless** study-coach pack. The caller holds the card state;
this module computes the schedule. Three capabilities:

  * **Spaced repetition** — the well-known **SM-2** algorithm (Anki's lineage):
    `review(card, quality)` returns the card's next interval / ease / due day.
  * **Review session** — `build_session(cards, ...)` selects what to study today:
    everything *due* plus up to a daily cap of *new* cards.
  * **Curriculum planning** — `plan_curriculum(topics, ...)` orders topics by
    declared prerequisites (a deterministic topological order; cycles are reported,
    never silently dropped) and splits them into evenly-sized sessions.

Deterministic and honest: it is a *scheduler/planner*, not a content generator — it
never invents lesson material, and it surfaces what it can't resolve (cycles,
unknown prereqs) rather than guessing. No network, no persistence, no side effects.
"""

from __future__ import annotations

# SM-2 constants.
_MIN_EASE = 1.3
_DEFAULT_EASE = 2.5
_FIRST_INTERVAL = 1
_SECOND_INTERVAL = 6


def _clampi(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def review(card: dict | None, quality: int, *, now_day: int = 0) -> dict:
    """Apply one SM-2 review to *card* and return the updated card.

    ``quality`` is the recall grade 0–5 (5 = perfect). A grade < 3 is a lapse: the
    repetition count resets and the card is seen again tomorrow. The ease factor is
    nudged by SM-2's formula and floored at 1.3. ``now_day`` is an integer day index
    (the caller's clock); ``due_day = now_day + interval``.

    Input ``card`` keys (all optional, sensible defaults): ``id``,
    ``repetitions``, ``interval``, ``ease``. Pure — the input is not mutated.
    """
    card = dict(card or {})
    q = _clampi(int(quality), 0, 5)
    reps = max(0, int(card.get("repetitions", 0)))
    interval = max(0, int(card.get("interval", 0)))
    ease = float(card.get("ease", _DEFAULT_EASE))

    if q < 3:
        # Lapse: relearn from the start, but keep the (penalised) ease.
        reps = 0
        interval = _FIRST_INTERVAL
    else:
        if reps == 0:
            interval = _FIRST_INTERVAL
        elif reps == 1:
            interval = _SECOND_INTERVAL
        else:
            interval = max(1, round(interval * ease))
        reps += 1

    # SM-2 ease update, floored at 1.3.
    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ease = round(max(_MIN_EASE, ease), 4)

    out = dict(card)
    out.update({
        "id": card.get("id"),
        "repetitions": reps,
        "interval": interval,
        "ease": ease,
        "last_quality": q,
        "due_day": int(now_day) + interval,
        "lapsed": q < 3,
    })
    return out


def is_due(card: dict, now_day: int) -> bool:
    """True when *card* is due for review at *now_day* (a never-reviewed card with
    no ``due_day`` is treated as due)."""
    due = card.get("due_day")
    return True if due is None else int(due) <= int(now_day)


def build_session(cards: list[dict], *, now_day: int = 0, new_limit: int = 20,
                  max_reviews: int = 200) -> dict:
    """Select today's study session: all *due* cards (capped) + up to *new_limit*
    brand-new cards (``repetitions == 0`` and never scheduled).

    Honest counts: returns how many were due vs. new and how many were deferred by
    the caps, so a backlog is visible rather than silently truncated.
    """
    new_limit = _clampi(int(new_limit), 0, 1000)
    max_reviews = _clampi(int(max_reviews), 1, 5000)

    due, new = [], []
    for c in cards or []:
        scheduled = c.get("due_day") is not None or int(c.get("repetitions", 0)) > 0
        if scheduled:
            if is_due(c, now_day):
                due.append(c)
        else:
            new.append(c)

    due_sel = due[:max_reviews]
    new_sel = new[:new_limit]
    return {
        "now_day": int(now_day),
        "due": due_sel,
        "new": new_sel,
        "counts": {
            "due_total": len(due), "due_selected": len(due_sel),
            "new_total": len(new), "new_selected": len(new_sel),
            "deferred": (len(due) - len(due_sel)) + (len(new) - len(new_sel)),
        },
    }


def plan_curriculum(topics: list[dict], *, per_session: int = 3) -> dict:
    """Order *topics* by their declared prerequisites and split into sessions.

    Each topic is ``{"id": str, "prereqs"?: [id, ...], "title"?: str}``. Produces a
    deterministic topological order (ties broken by input order). Prereq edges that
    reference an **unknown** id are reported under ``unknown_prereqs`` (the edge is
    ignored, not fabricated). A prerequisite **cycle** is reported under ``cycles``
    and those topics are appended after the resolvable ones rather than dropped.
    """
    per_session = _clampi(int(per_session), 1, 100)
    items = [t for t in (topics or []) if t.get("id")]
    by_id = {t["id"]: t for t in items}
    order_index = {t["id"]: i for i, t in enumerate(items)}

    # Build dependency edges, recording unknown references honestly.
    unknown_prereqs: list[dict] = []
    deps: dict[str, set[str]] = {t["id"]: set() for t in items}
    for t in items:
        for p in t.get("prereqs", []) or []:
            if p in by_id:
                deps[t["id"]].add(p)
            else:
                unknown_prereqs.append({"topic": t["id"], "missing_prereq": p})

    # Kahn's algorithm, with deterministic tie-breaking by original input order.
    resolved: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted([tid for tid, ps in remaining.items() if not ps],
                       key=lambda tid: order_index[tid])
        if not ready:
            break  # a cycle remains among the rest
        for tid in ready:
            resolved.append(tid)
            del remaining[tid]
            for ps in remaining.values():
                ps.discard(tid)

    cycles = sorted(remaining.keys(), key=lambda tid: order_index[tid])
    ordered_ids = resolved + cycles  # never drop a topic; cyclic ones come last
    ordered = [by_id[tid] for tid in ordered_ids]

    sessions = [ordered[i:i + per_session] for i in range(0, len(ordered), per_session)]
    return {
        "order": ordered,
        "sessions": sessions,
        "session_count": len(sessions),
        "unknown_prereqs": unknown_prereqs,
        "cycles": cycles,
    }
