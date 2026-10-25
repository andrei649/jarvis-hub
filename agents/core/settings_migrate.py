"""H006 — what a build writes into an existing settings store, planned before it is done.

``settings_db.init_db`` already brings a store up to date every time the hub (or an
offline verb) first touches it: it seeds the declared settings a store lacks, applies the
shipped defaults a later build changed (``_CHANGED_DEFAULTS``) and rewrites the one
retired Claude default. That happens silently and only at init. This module is the same
work as a plan an operator can read first (``nerva config migrate --dry-run``), then
apply, plus the part init does not do: a model id a vendor retired is rewritten wherever
a model setting holds it, not only on the row that shipped it — the equivalent of
``hermes migrate xai`` for every vendor in :data:`RETIRED_MODELS`.

The planner reads the raw store (read-only, before any init, so a dry run sees what a
boot would change); ``apply`` writes exactly the plan in one transaction. Secret values
are never part of a plan: no model setting is a secret, and a seed carries a declared
default only.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Any

from agents.core.llm.model_config import DEFAULT_CLAUDE_MODEL, RETIRED_CLAUDE_DEFAULT


@dataclass(frozen=True)
class RetiredModel:
    """A model id a vendor no longer serves, and the id a store holding it moves to."""

    vendor: str
    retired: str
    replacement: str
    source: str       # where the repo records the retirement (a path, never a memory)
    since: str = ""   # the retirement date that source records (ISO day); "" when it records none


#: The rewrite table — data, pinned by tests/test_settings_db_migrate.py: one row per
#: retired id, each with the repo file that records its retirement, and a replacement
#: the cost estimator prices and that is not itself retired. The first row is the
#: shipped Claude default's own retirement, single-sourced from ``model_config`` so the
#: boot migration and this table can never disagree. The other rows are the retirements
#: ``agents/core/llm/cost_estimator.py`` and docs/research/2026-08-18-llm-pricing-
#: verification.md record (the estimator keeps the retired rows priced so past runs stay
#: answerable). The repo records no vendor-recommended successor, so the replacement is
#: this table's own choice: the same family on the 4.6 generation the hub's Claude
#: default runs (``DEFAULT_CLAUDE_MODEL``), and for Haiku, which has no 4.6, the newest
#: Haiku the estimator prices.
#:
#: Only Anthropic ids are listed, deliberately: nothing in the repo records a retired
#: xAI (``llm.compatible_provider = xai``), OpenAI, Google or OpenRouter id, and a
#: retirement is not taken from memory. ``llm.compatible_model`` and ``llm.gemini_model``
#: are still scanned, so the day such a row is added here (with its source) `nerva
#: config migrate` rewrites it, with no code change — that is the whole of the
#: vendor-specific `hermes migrate xai`, as data.
RETIRED_MODELS: tuple[RetiredModel, ...] = (
    RetiredModel("anthropic", RETIRED_CLAUDE_DEFAULT, DEFAULT_CLAUDE_MODEL,
                 "agents/core/llm/model_config.py"),
    RetiredModel("anthropic", "claude-opus-4-20250514", "claude-opus-4-6",
                 "agents/core/llm/cost_estimator.py", "2026-06-15"),
    RetiredModel("anthropic", "claude-opus-4-1-20250805", "claude-opus-4-6",
                 "agents/core/llm/cost_estimator.py", "2026-08-05"),
    RetiredModel("anthropic", "claude-3-5-haiku-20241022", "claude-haiku-4-5",
                 "agents/core/llm/cost_estimator.py", "2026-02-19"),
)

#: The declared settings whose whole value is one model id. A retired id is rewritten
#: only here: a free-text or json setting that merely mentions a model is the owner's.
MODEL_SETTINGS: tuple[tuple[str, str], ...] = (
    ("llm", "claude_model"),
    ("llm", "default_model"),
    ("llm", "gemini_model"),
    ("llm", "compatible_model"),
    ("autonomy", "subagent_model"),
)

#: H329 — switch rows ``init_db`` never reseeds once the switches have observed a store
#: (a missing row is damage the strict reader reports); the planner lists them as kept.
_SKILL_SWITCH_ROWS = frozenset({("skills", "disabled"), ("skills", "channel_disabled")})
_SKILL_SWITCH_TABLE = "skill_switch_revision"


def replacement_for(model: str) -> str | None:
    """The id *model* moves to, or None when no vendor retired it."""
    for row in RETIRED_MODELS:
        if row.retired == model:
            return row.replacement
    return None


@dataclass(frozen=True)
class Change:
    """One line of the plan. *kind*: ``seed`` (a declared setting the store lacks),
    ``default`` (the old shipped default, moved to the new one), ``retired`` (a model
    id a vendor retired) or ``kept`` (named, deliberately not written)."""

    setting: str
    kind: str
    before: Any
    after: Any
    why: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_store(path) -> tuple[dict[tuple[str, str], Any], set[str], bool] | None:
    """``(raw values, applied migration names, switches observed)`` from the store at
    *path*, read-only; None when there is no store. Raises ``sqlite3.Error`` when the
    file is not a readable store (the caller names it; nothing is guessed)."""
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        return None
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "settings" not in tables:
            raise sqlite3.DatabaseError(f"{path} has no settings table")
        values = {(c, k): json.loads(v) for c, k, v in conn.execute("SELECT category, key, value FROM settings")}
        applied = ({r[0] for r in conn.execute("SELECT name FROM settings_migrations")}
                   if "settings_migrations" in tables else set())
        return values, applied, _SKILL_SWITCH_TABLE in tables
    finally:
        conn.close()


_MISSING = object()


def plan(path=None, table: tuple[RetiredModel, ...] | None = None) -> list[Change] | None:
    """What :func:`apply` would write into the store at *path* (the active store when
    None), in the order it would write it; ``[]`` when it is current, None when there
    is no store yet (a boot, or :func:`create`, seeds every declared default). *table*
    replaces :data:`RETIRED_MODELS` (a test, or a caller with a vendor's own list)."""
    from agents.core import settings_db

    read = _read_store(settings_db.DB_PATH if path is None else path)
    if read is None:
        return None
    values, applied, switches_observed = read
    changes: list[Change] = []
    seen: set[tuple[str, str]] = set()
    for spec in settings_db.DEFAULTS:
        name = (spec["category"], spec["key"])
        if name in values or name in seen:      # DEFAULTS declares a few keys twice; one row
            continue
        seen.add(name)
        if switches_observed and name in _SKILL_SWITCH_ROWS:
            changes.append(Change(".".join(name), "kept", None, None,
                                  "a skill switch row the switches have observed is never reseeded "
                                  "(H329: a missing one is reported, see `nerva skills list`)"))
            continue
        changes.append(Change(".".join(name), "seed", None, spec["value"], "new in this build"))
    for marker, category, key, old, new in settings_db._CHANGED_DEFAULTS:
        if marker in applied or values.get((category, key), _MISSING) != old:
            continue
        changes.append(Change(f"{category}.{key}", "default", old, new, "the shipped default changed"))
    for category, key in MODEL_SETTINGS:
        current = values.get((category, key))
        if not isinstance(current, str):
            continue
        row = next((r for r in (RETIRED_MODELS if table is None else table) if r.retired == current), None)
        if row is not None:
            changes.append(Change(f"{category}.{key}", "retired", current, row.replacement,
                                  f"{row.vendor} retired it" + (f" ({row.since})" if row.since else "")))
    return changes


def apply(changes: list[Change]) -> list[Change]:
    """Write *changes* (a :func:`plan`) into the active store in one transaction, each
    guarded by the same ``WHERE`` a boot uses, so a value the owner changed between
    the plan and now is left alone. Returns the changes written (``kept`` rows are not)."""
    from agents.core import settings_db

    written: list[Change] = []
    touched: dict[str, dict[str, Any]] = {}
    conn = settings_db.get_conn()
    try:
        with conn:
            conn.executescript(settings_db.SCHEMA)       # an old store may lack settings_migrations
            for change in changes:
                category, _, key = change.setting.partition(".")
                if change.kind == "seed":
                    spec = settings_db._SPEC[(category, key)]
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO settings (category, key, value, label, kind, opts) "
                        "VALUES (?,?,?,?,?,?)",
                        (category, key, json.dumps(spec["value"]), spec["label"], spec["kind"],
                         json.dumps(spec.get("opts", []))))
                elif change.kind in ("default", "retired"):
                    cur = conn.execute(
                        "UPDATE settings SET value=? WHERE category=? AND key=? AND value=?",
                        (json.dumps(change.after), category, key, json.dumps(change.before)))
                    if change.kind == "default":
                        marker = next(m for m, c, k, _o, _n in settings_db._CHANGED_DEFAULTS
                                      if (c, k) == (category, key))
                        conn.execute("INSERT OR IGNORE INTO settings_migrations (name, applied_at) VALUES (?, ?)",
                                     (marker, time.time()))
                else:
                    continue
                if cur.rowcount > 0:
                    written.append(change)
                    touched.setdefault(category, {})[key] = change.after
    finally:
        conn.close()
    settings_db._require_readable_store()
    for category, values in touched.items():
        settings_db._changed(category, values)
    return written


def create() -> int:
    """Seed a store that does not exist yet, as a first boot would; how many declared
    settings it now holds."""
    from agents.core import settings_db

    settings_db.ensure_initialized()
    return sum(len(rows) for rows in settings_db.get_all().values())
